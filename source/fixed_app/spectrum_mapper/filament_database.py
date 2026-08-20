from __future__ import annotations

import math
import os
import re
import sqlite3
import sys
import threading
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .filament_materials import (
    DEFAULT_FILAMENT_MATERIAL,
    normalize_filament_material,
)

DATABASE_FILENAME = "filament_color_database_2026-08.sqlite"
_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")

# ``measured_swatches`` does not carry a finish_penalty column.  Most rows are
# linked to ``catalog_colors`` and inherit its value, but an independently
# measured product can legitimately have no catalog row.  These fallbacks are
# the same rules used to build the bundled database.  An unknown finish uses a
# conservative 2.0 instead of silently treating it as standard opaque (0.0).
_FINISH_CLASS_FALLBACK_PENALTIES = {
    "標準/不透明": 0.0,
    "マット": 1.0,
    "シルク/メタリック/光沢": 2.5,
    "カーボン繊維": 3.0,
    "ガラス繊維": 3.0,
    "発泡/LW": 3.0,
    "木質": 4.0,
    "マーブル/ストーン": 4.0,
    "蓄光": 4.0,
    "透明/半透明": 6.0,
    "マルチカラー/グラデーション": 99.0,
}
_UNKNOWN_FINISH_CLASS_PENALTY = 2.0

_REQUIRED_COLUMNS = {
    "catalog_colors": frozenset(
        {
            "record_id",
            "material",
            "brand",
            "series",
            "color_name",
            "finish_class",
            "reference_hex",
            "lab_l",
            "lab_a",
            "lab_b",
            "comparison_eligible",
            "finish_penalty",
            "catalog_status",
            "data_confidence",
            "brand_official_url",
            "catalog_source_url",
        }
    ),
    "measured_swatches": frozenset(
        {
            "measurement_id",
            "brand",
            "series",
            "color_name",
            "finish_class",
            "measured_hex",
            "lab_l",
            "lab_a",
            "lab_b",
            "matched_catalog_record_id",
            "source_url",
        }
    ),
    "meta": frozenset({"key", "value"}),
}


class FilamentDatabaseError(RuntimeError):
    """Base class for failures that disable only filament lookup."""


class FilamentDatabaseNotFoundError(FilamentDatabaseError):
    pass


class FilamentDatabaseSchemaError(FilamentDatabaseError):
    pass


class FilamentDatabaseCorruptError(FilamentDatabaseError):
    pass


@dataclass(frozen=True, slots=True)
class FilamentMatch:
    brand: str
    series: str
    color_name: str
    matched_hex: str
    delta_e_2000: float
    score: float
    finish_class: str
    source_kind: str
    source_url: str | None
    record_id: str | None
    measurement_id: str | None
    finish_penalty: float = 0.0
    catalog_status: str | None = None
    data_confidence: str | None = None
    material: str = DEFAULT_FILAMENT_MATERIAL


@dataclass(frozen=True, slots=True)
class FilamentProduct:
    """One stable, user-selectable filament product from the bundled DB.

    ``product_id`` is deliberately opaque.  It is the only value that should
    be persisted in the user's owned-filament inventory; display names and HEX
    values may be corrected by a later database revision.  A measured swatch
    and its linked catalog row keep the same product ID, while the measured
    colour is preferred for display and colour matching by default.

    ``alias_product_ids`` covers exact duplicate catalog variants that the UI
    collapses into one row.  Keeping those aliases lets an inventory created by
    an older database revision resolve to the canonical product instead of
    becoming stale unnecessarily.
    """

    product_id: str
    brand: str
    series: str
    color_name: str
    matched_hex: str
    finish_class: str
    source_kind: str
    source_url: str | None
    record_id: str | None
    measurement_id: str | None
    finish_penalty: float = 0.0
    catalog_status: str | None = None
    data_confidence: str | None = None
    material: str = DEFAULT_FILAMENT_MATERIAL
    alias_product_ids: tuple[str, ...] = ()
    # When ``source_kind == "snapshot"``, retain the original catalog/measured
    # provenance here while clearly labeling the active colour as unverified.
    snapshot_source_kind: str | None = None

    def __post_init__(self) -> None:
        product_id = str(self.product_id).strip()
        if not product_id:
            raise ValueError("filament product_id must not be empty")
        try:
            penalty = float(self.finish_penalty)
        except (TypeError, ValueError) as exc:
            raise ValueError("finish_penalty must be a finite non-negative number") from exc
        if not math.isfinite(penalty) or penalty < 0.0:
            raise ValueError("finish_penalty must be a finite non-negative number")
        aliases = {
            str(value).strip()
            for value in self.alias_product_ids
            if str(value).strip()
        }
        aliases.add(product_id)
        object.__setattr__(self, "product_id", product_id)
        object.__setattr__(
            self,
            "material",
            normalize_filament_material(
                self.material, default=DEFAULT_FILAMENT_MATERIAL
            ),
        )
        object.__setattr__(self, "matched_hex", normalize_hex(self.matched_hex))
        object.__setattr__(self, "finish_penalty", penalty)
        object.__setattr__(
            self,
            "alias_product_ids",
            tuple(sorted(aliases, key=lambda value: (value.casefold(), value))),
        )

    @property
    def id(self) -> str:
        """Compatibility alias for recommendation candidate APIs."""

        return self.product_id

    @property
    def hex_color(self) -> str:
        """Compatibility alias for recommendation candidate APIs."""

        return self.matched_hex

    @property
    def label(self) -> str:
        parts = tuple(
            value for value in (self.brand, self.series, self.color_name) if value
        )
        return " / ".join(parts) or self.product_id


@dataclass(frozen=True, slots=True)
class _FilamentRecord:
    material: str
    brand: str
    series: str
    color_name: str
    matched_hex: str
    lab: tuple[float, float, float]
    finish_class: str
    finish_penalty: float
    source_kind: str
    source_url: str | None
    record_id: str | None
    measurement_id: str | None
    matched_catalog_record_id: str | None
    catalog_identity_matches: bool
    catalog_status: str | None
    data_confidence: str | None

    @property
    def stable_product_id(self) -> str:
        linked_id = (
            self.matched_catalog_record_id
            if self.catalog_identity_matches
            else None
        ) or (self.record_id if self.source_kind == "catalog" else None)
        if linked_id:
            return f"catalog:{linked_id}"
        if self.measurement_id:
            return f"measurement:{self.measurement_id}"
        # The bundled schema requires identifiers, so this branch is only a
        # defensive guard for a future externally supplied database.
        raise FilamentDatabaseSchemaError(
            "フィラメント製品に安定IDがありません: "
            f"{self.brand} / {self.series} / {self.color_name}"
        )

    @property
    def product_key(self) -> tuple[str, ...]:
        return ("stable", self.stable_product_id)

    @property
    def duplicate_key(self) -> tuple[str, ...]:
        return (
            self.material,
            self.brand.casefold(),
            self.series.casefold(),
            self.color_name.casefold(),
            self.matched_hex,
        )


def normalize_hex(value: str) -> str:
    """Return strict, uppercase ``#RRGGBB`` form."""

    if not isinstance(value, str):
        raise ValueError("色は #RRGGBB 形式で指定してください")
    match = _HEX_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError("色は #RRGGBB 形式で指定してください")
    return f"#{match.group(1).upper()}"


def srgb_hex_to_lab(value: str) -> tuple[float, float, float]:
    """Convert an sRGB colour to CIELAB using the D65 reference white."""

    normalized = normalize_hex(value)
    channels = tuple(int(normalized[index : index + 2], 16) / 255.0 for index in (1, 3, 5))

    def linearize(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linearize(channel) for channel in channels)
    x = 0.4124564 * red + 0.3575761 * green + 0.1804375 * blue
    y = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue
    z = 0.0193339 * red + 0.1191920 * green + 0.9503041 * blue

    epsilon = 216.0 / 24_389.0
    kappa = 24_389.0 / 27.0

    def pivot(component: float) -> float:
        if component > epsilon:
            return component ** (1.0 / 3.0)
        return (kappa * component + 16.0) / 116.0

    fx = pivot(x / 0.95047)
    fy = pivot(y)
    fz = pivot(z / 1.08883)
    return (
        116.0 * fy - 16.0,
        500.0 * (fx - fy),
        200.0 * (fy - fz),
    )


def ciede2000(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    """Compute the CIEDE2000 colour difference (kL = kC = kH = 1)."""

    try:
        l1, a1, b1 = (float(value) for value in first)
        l2, a2, b2 = (float(value) for value in second)
    except (TypeError, ValueError) as exc:
        raise ValueError("Lab values must contain three finite numbers") from exc
    if not all(math.isfinite(value) for value in (l1, a1, b1, l2, a2, b2)):
        raise ValueError("Lab values must contain three finite numbers")

    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    c_bar_seventh = c_bar**7
    g = 0.5 * (1.0 - math.sqrt(c_bar_seventh / (c_bar_seventh + 25.0**7)))
    a1_prime = (1.0 + g) * a1
    a2_prime = (1.0 + g) * a2
    c1_prime = math.hypot(a1_prime, b1)
    c2_prime = math.hypot(a2_prime, b2)

    def hue_degrees(a_value: float, b_value: float) -> float:
        if a_value == 0.0 and b_value == 0.0:
            return 0.0
        return math.degrees(math.atan2(b_value, a_value)) % 360.0

    h1_prime = hue_degrees(a1_prime, b1)
    h2_prime = hue_degrees(a2_prime, b2)
    delta_l_prime = l2 - l1
    delta_c_prime = c2_prime - c1_prime

    if c1_prime * c2_prime == 0.0:
        delta_h_degrees = 0.0
    else:
        delta_h_degrees = h2_prime - h1_prime
        if delta_h_degrees > 180.0:
            delta_h_degrees -= 360.0
        elif delta_h_degrees < -180.0:
            delta_h_degrees += 360.0
    delta_h_prime = 2.0 * math.sqrt(c1_prime * c2_prime) * math.sin(
        math.radians(delta_h_degrees / 2.0)
    )

    l_bar_prime = (l1 + l2) / 2.0
    c_bar_prime = (c1_prime + c2_prime) / 2.0
    if c1_prime * c2_prime == 0.0:
        h_bar_prime = h1_prime + h2_prime
    elif abs(h1_prime - h2_prime) <= 180.0:
        h_bar_prime = (h1_prime + h2_prime) / 2.0
    elif h1_prime + h2_prime < 360.0:
        h_bar_prime = (h1_prime + h2_prime + 360.0) / 2.0
    else:
        h_bar_prime = (h1_prime + h2_prime - 360.0) / 2.0

    t = (
        1.0
        - 0.17 * math.cos(math.radians(h_bar_prime - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * h_bar_prime))
        + 0.32 * math.cos(math.radians(3.0 * h_bar_prime + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * h_bar_prime - 63.0))
    )
    delta_theta = 30.0 * math.exp(-(((h_bar_prime - 275.0) / 25.0) ** 2))
    c_bar_prime_seventh = c_bar_prime**7
    r_c = 2.0 * math.sqrt(
        c_bar_prime_seventh / (c_bar_prime_seventh + 25.0**7)
    )
    s_l = 1.0 + 0.015 * (l_bar_prime - 50.0) ** 2 / math.sqrt(
        20.0 + (l_bar_prime - 50.0) ** 2
    )
    s_c = 1.0 + 0.045 * c_bar_prime
    s_h = 1.0 + 0.015 * c_bar_prime * t
    r_t = -math.sin(math.radians(2.0 * delta_theta)) * r_c

    l_term = delta_l_prime / s_l
    c_term = delta_c_prime / s_c
    h_term = delta_h_prime / s_h
    squared = l_term**2 + c_term**2 + h_term**2 + r_t * c_term * h_term
    return math.sqrt(max(0.0, squared))


def resolve_filament_database_path(
    explicit_path: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve the DB in development, PyInstaller, and external-resource layouts."""

    if explicit_path is not None:
        return Path(explicit_path).expanduser().resolve()

    candidates: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "resources" / "filament_db" / DATABASE_FILENAME)
    if getattr(sys, "frozen", False):
        candidates.append(
            Path(sys.executable).resolve().parent
            / "resources"
            / "filament_db"
            / DATABASE_FILENAME
        )
    candidates.append(
        Path(__file__).resolve().parent.parent
        / "resources"
        / "filament_db"
        / DATABASE_FILENAME
    )

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return candidates[0].resolve()


class FilamentRepository:
    """Validated, read-only access to the bundled filament database."""

    def __init__(self, database_path: str | os.PathLike[str] | None = None) -> None:
        self.database_path = resolve_filament_database_path(database_path)
        self._lock = threading.RLock()
        self._records: tuple[_FilamentRecord, ...] | None = None
        self._products: dict[bool, tuple[FilamentProduct, ...]] = {}
        self._meta: dict[str, str] = {}
        self.catalog_count = 0
        self.measured_count = 0
        self._validate()

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise FilamentDatabaseNotFoundError(
                f"フィラメントデータベースが見つかりません: {self.database_path}"
            )
        uri = f"{self.database_path.as_uri()}?mode=ro&immutable=1"
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
            connection.execute("PRAGMA query_only = ON")
            connection.row_factory = sqlite3.Row
            return connection
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise FilamentDatabaseCorruptError(
                f"フィラメントデータベースを読み取れません: {exc}"
            ) from exc

    def _validate(self) -> None:
        if not self.database_path.is_file():
            raise FilamentDatabaseNotFoundError(
                f"フィラメントデータベースが見つかりません: {self.database_path}"
            )
        try:
            with closing(self._connect()) as connection:
                quick_check = connection.execute("PRAGMA quick_check").fetchone()
                if quick_check is None or quick_check[0] != "ok":
                    detail = "unknown" if quick_check is None else str(quick_check[0])
                    raise FilamentDatabaseCorruptError(
                        f"フィラメントデータベースが破損しています: {detail}"
                    )
                table_names = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                missing_tables = sorted(set(_REQUIRED_COLUMNS) - table_names)
                if missing_tables:
                    raise FilamentDatabaseSchemaError(
                        "フィラメントDBの必須テーブルがありません: "
                        + ", ".join(missing_tables)
                    )
                for table, required in _REQUIRED_COLUMNS.items():
                    actual = {
                        str(row[1])
                        for row in connection.execute(f'PRAGMA table_info("{table}")')
                    }
                    missing_columns = sorted(required - actual)
                    if missing_columns:
                        raise FilamentDatabaseSchemaError(
                            f"フィラメントDBの {table} に必須列がありません: "
                            + ", ".join(missing_columns)
                        )
                self.catalog_count = int(
                    connection.execute("SELECT COUNT(*) FROM catalog_colors").fetchone()[0]
                )
                self.measured_count = int(
                    connection.execute("SELECT COUNT(*) FROM measured_swatches").fetchone()[0]
                )
                self._meta = {
                    str(row[0]): str(row[1])
                    for row in connection.execute("SELECT key, value FROM meta")
                }
        except FilamentDatabaseError:
            raise
        except sqlite3.DatabaseError as exc:
            raise FilamentDatabaseCorruptError(
                f"フィラメントデータベースが破損しています: {exc}"
            ) from exc
        except (OSError, ValueError) as exc:
            raise FilamentDatabaseCorruptError(
                f"フィラメントデータベースを読み取れません: {exc}"
            ) from exc

    @property
    def meta(self) -> dict[str, str]:
        return dict(self._meta)

    @property
    def records(self) -> tuple[_FilamentRecord, ...]:
        with self._lock:
            if self._records is None:
                self._records = self._load_records()
            return self._records

    @staticmethod
    def _record_preference_key(
        record: _FilamentRecord,
        *,
        prefer_measured: bool,
    ) -> tuple[object, ...]:
        preferred_kind = "measured" if prefer_measured else "catalog"
        return (
            0 if record.source_kind == preferred_kind else 1,
            record.finish_penalty,
            record.stable_product_id.casefold(),
            record.stable_product_id,
            record.matched_hex,
            record.measurement_id or "",
            record.record_id or "",
        )

    @staticmethod
    def _product_from_record(
        record: _FilamentRecord,
        aliases: Iterable[str],
    ) -> FilamentProduct:
        product_id = record.stable_product_id
        normalized_aliases = tuple(
            sorted(
                {str(value).strip() for value in aliases if str(value).strip()},
                key=lambda value: (value.casefold(), value),
            )
        )
        if product_id not in normalized_aliases:
            normalized_aliases = tuple(
                sorted(
                    (*normalized_aliases, product_id),
                    key=lambda value: (value.casefold(), value),
                )
            )
        return FilamentProduct(
            product_id=product_id,
            brand=record.brand,
            series=record.series,
            color_name=record.color_name,
            matched_hex=record.matched_hex,
            finish_class=record.finish_class,
            source_kind=record.source_kind,
            source_url=record.source_url,
            record_id=record.record_id,
            measurement_id=record.measurement_id,
            finish_penalty=record.finish_penalty,
            catalog_status=record.catalog_status,
            data_confidence=record.data_confidence,
            material=record.material,
            alias_product_ids=normalized_aliases,
        )

    def list_products(
        self,
        *,
        prefer_measured: bool = True,
        brands: Iterable[str] | str | None = None,
        material: str | None = None,
    ) -> tuple[FilamentProduct, ...]:
        """Return selectable products with stable IDs and duplicate collapse.

        Linked catalog/measured rows are always one product.  Exact repeated
        display variants are collapsed deterministically and retain all stable
        IDs as aliases.  Filtering happens after canonicalisation, so it cannot
        change which duplicate becomes canonical.
        """

        preference = bool(prefer_measured)
        with self._lock:
            cached = self._products.get(preference)
            if cached is None:
                by_product: dict[str, list[_FilamentRecord]] = {}
                for record in self.records:
                    by_product.setdefault(record.stable_product_id, []).append(record)

                resolved: list[tuple[_FilamentRecord, tuple[str, ...]]] = []
                for product_id, variants in by_product.items():
                    selected = min(
                        variants,
                        key=lambda record: self._record_preference_key(
                            record, prefer_measured=preference
                        ),
                    )
                    resolved.append((selected, (product_id,)))

                by_display: dict[
                    tuple[str, ...], list[tuple[_FilamentRecord, tuple[str, ...]]]
                ] = {}
                for record, aliases in resolved:
                    by_display.setdefault(record.duplicate_key, []).append(
                        (record, aliases)
                    )

                products: list[FilamentProduct] = []
                for duplicates in by_display.values():
                    selected, _selected_aliases = min(
                        duplicates,
                        key=lambda item: self._record_preference_key(
                            item[0], prefer_measured=preference
                        ),
                    )
                    aliases = tuple(
                        alias
                        for _record, record_aliases in duplicates
                        for alias in record_aliases
                    )
                    products.append(self._product_from_record(selected, aliases))

                products.sort(
                    key=lambda product: (
                        product.brand.casefold(),
                        product.brand,
                        product.series.casefold(),
                        product.series,
                        product.color_name.casefold(),
                        product.color_name,
                        product.product_id.casefold(),
                        product.product_id,
                    )
                )
                cached = tuple(products)
                self._products[preference] = cached

        material_filter = (
            None
            if material is None
            else normalize_filament_material(material)
        )
        material_products = tuple(
            product
            for product in cached
            if material_filter is None or product.material == material_filter
        )
        if brands is None:
            return material_products
        if isinstance(brands, str):
            brands = (brands,)
        brand_filter = {
            str(value).strip().casefold()
            for value in brands
            if str(value).strip()
        }
        if not brand_filter:
            return material_products
        return tuple(
            product
            for product in material_products
            if product.brand.casefold() in brand_filter
        )

    def products_grouped_by_brand(
        self,
        *,
        prefer_measured: bool = True,
        material: str | None = None,
    ) -> tuple[tuple[str, tuple[FilamentProduct, ...]], ...]:
        """Return products in deterministic manufacturer groups for the UI."""

        grouped: dict[str, list[FilamentProduct]] = {}
        for product in self.list_products(
            prefer_measured=prefer_measured, material=material
        ):
            grouped.setdefault(product.brand or "(Unknown)", []).append(product)
        return tuple(
            (brand, tuple(grouped[brand]))
            for brand in sorted(grouped, key=lambda value: (value.casefold(), value))
        )

    def get_products(
        self,
        product_ids: Iterable[str] | str,
        *,
        prefer_measured: bool = True,
        material: str | None = None,
    ) -> tuple[FilamentProduct, ...]:
        """Resolve canonical or duplicate-alias IDs, preserving input order."""

        if isinstance(product_ids, str):
            product_ids = (product_ids,)
        products = self.list_products(
            prefer_measured=prefer_measured, material=material
        )
        lookup = {
            alias: product
            for product in products
            for alias in product.alias_product_ids
        }
        result: list[FilamentProduct] = []
        seen: set[str] = set()
        for value in product_ids:
            product = lookup.get(str(value).strip())
            if product is None or product.product_id in seen:
                continue
            seen.add(product.product_id)
            result.append(product)
        return tuple(result)

    @staticmethod
    def _text(value: object) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _optional_text(value: object) -> str | None:
        text = FilamentRepository._text(value)
        return text or None

    @staticmethod
    def _lab_from_row(row: sqlite3.Row, matched_hex: str) -> tuple[float, float, float]:
        try:
            lab = (float(row["lab_l"]), float(row["lab_a"]), float(row["lab_b"]))
        except (TypeError, ValueError):
            return srgb_hex_to_lab(matched_hex)
        return lab if all(math.isfinite(value) for value in lab) else srgb_hex_to_lab(matched_hex)

    @staticmethod
    def _penalty(value: object, *, fallback: float = 0.0) -> float:
        try:
            penalty = float(value)
        except (TypeError, ValueError):
            return fallback
        return penalty if math.isfinite(penalty) and penalty >= 0.0 else fallback

    @staticmethod
    def _fallback_finish_penalty(finish_class: str) -> float:
        return _FINISH_CLASS_FALLBACK_PENALTIES.get(
            finish_class,
            _UNKNOWN_FINISH_CLASS_PENALTY,
        )

    def _load_records(self) -> tuple[_FilamentRecord, ...]:
        records: list[_FilamentRecord] = []
        try:
            with closing(self._connect()) as connection:
                for row in connection.execute(
                    """
                    SELECT record_id, material, brand, series, color_name, finish_class,
                           reference_hex, lab_l, lab_a, lab_b, finish_penalty,
                           catalog_status, data_confidence, brand_official_url,
                           catalog_source_url
                      FROM catalog_colors
                     WHERE comparison_eligible = 1
                    """
                ):
                    try:
                        matched_hex = normalize_hex(self._text(row["reference_hex"]))
                    except ValueError:
                        continue
                    record_id = self._optional_text(row["record_id"])
                    records.append(
                        _FilamentRecord(
                            material=normalize_filament_material(row["material"]),
                            brand=self._text(row["brand"]),
                            series=self._text(row["series"]),
                            color_name=self._text(row["color_name"]),
                            matched_hex=matched_hex,
                            lab=self._lab_from_row(row, matched_hex),
                            finish_class=self._text(row["finish_class"]),
                            finish_penalty=self._penalty(row["finish_penalty"]),
                            source_kind="catalog",
                            source_url=self._optional_text(row["catalog_source_url"])
                            or self._optional_text(row["brand_official_url"]),
                            record_id=record_id,
                            measurement_id=None,
                            matched_catalog_record_id=None,
                            catalog_identity_matches=False,
                            catalog_status=self._optional_text(row["catalog_status"]),
                            data_confidence=self._optional_text(row["data_confidence"]),
                        )
                    )

                for row in connection.execute(
                    """
                    SELECT m.measurement_id, m.brand, m.series, m.color_name,
                           m.finish_class, m.measured_hex, m.lab_l, m.lab_a, m.lab_b,
                           m.matched_catalog_record_id, m.source_url,
                           c.record_id AS catalog_record_id,
                           COALESCE(c.material, 'PLA') AS material,
                           c.brand AS catalog_brand,
                           c.series AS catalog_series,
                           c.color_name AS catalog_color_name,
                           c.comparison_eligible AS catalog_comparison_eligible,
                           c.finish_penalty AS catalog_finish_penalty,
                           c.catalog_status AS catalog_status,
                           c.data_confidence AS data_confidence
                      FROM measured_swatches AS m
                 LEFT JOIN catalog_colors AS c
                        ON c.record_id = m.matched_catalog_record_id
                     WHERE c.record_id IS NULL OR c.comparison_eligible = 1
                    """
                ):
                    try:
                        matched_hex = normalize_hex(self._text(row["measured_hex"]))
                    except ValueError:
                        continue
                    finish_class = self._text(row["finish_class"])
                    matched_record_id = self._optional_text(
                        row["matched_catalog_record_id"]
                    )
                    catalog_identity_matches = bool(
                        matched_record_id
                        and self._text(row["brand"]).casefold()
                        == self._text(row["catalog_brand"]).casefold()
                        and self._text(row["series"]).casefold()
                        == self._text(row["catalog_series"]).casefold()
                        and self._text(row["color_name"]).casefold()
                        == self._text(row["catalog_color_name"]).casefold()
                    )
                    records.append(
                        _FilamentRecord(
                            material=normalize_filament_material(row["material"]),
                            brand=self._text(row["brand"]),
                            series=self._text(row["series"]),
                            color_name=self._text(row["color_name"]),
                            matched_hex=matched_hex,
                            lab=self._lab_from_row(row, matched_hex),
                            finish_class=finish_class,
                            finish_penalty=self._penalty(
                                row["catalog_finish_penalty"],
                                fallback=self._fallback_finish_penalty(finish_class),
                            ),
                            source_kind="measured",
                            source_url=self._optional_text(row["source_url"]),
                            record_id=matched_record_id,
                            measurement_id=self._optional_text(row["measurement_id"]),
                            matched_catalog_record_id=matched_record_id,
                            catalog_identity_matches=catalog_identity_matches,
                            catalog_status=self._optional_text(row["catalog_status"]),
                            data_confidence=self._optional_text(row["data_confidence"]),
                        )
                    )
        except FilamentDatabaseError:
            raise
        except sqlite3.DatabaseError as exc:
            raise FilamentDatabaseCorruptError(
                f"フィラメントデータベースを読み取れません: {exc}"
            ) from exc
        return tuple(records)


class FilamentMatcher:
    """Failure-isolated nearest-filament lookup for one target colour."""

    def __init__(self, database_path: str | os.PathLike[str] | None = None) -> None:
        self.database_path = resolve_filament_database_path(database_path)
        self.repository: FilamentRepository | None = None
        self.error_message: str | None = None
        self._records: tuple[_FilamentRecord, ...] = ()
        self.catalog_count = 0
        self.measured_count = 0
        try:
            repository = FilamentRepository(self.database_path)
            records = repository.records
        except FilamentDatabaseError as exc:
            self.error_message = str(exc)
        else:
            self.repository = repository
            self._records = records
            self.catalog_count = repository.catalog_count
            self.measured_count = repository.measured_count

    @property
    def is_available(self) -> bool:
        return self.repository is not None and self.error_message is None

    def available_brands(self, material: str | None = None) -> tuple[str, ...]:
        if not self.is_available:
            return ()
        material_filter = None if material is None else normalize_filament_material(material)
        return tuple(
            sorted(
                {
                    record.brand
                    for record in self._records
                    if record.brand
                    and (material_filter is None or record.material == material_filter)
                },
                key=lambda value: (value.casefold(), value),
            )
        )

    def available_finish_classes(self, material: str | None = None) -> tuple[str, ...]:
        if not self.is_available:
            return ()
        material_filter = None if material is None else normalize_filament_material(material)
        return tuple(
            sorted(
                {
                    record.finish_class
                    for record in self._records
                    if record.finish_class
                    and (material_filter is None or record.material == material_filter)
                },
                key=lambda value: (value.casefold(), value),
            )
        )

    @staticmethod
    def _normalize_filter(values: Iterable[str] | str | None) -> tuple[str, ...]:
        if values is None:
            return ()
        if isinstance(values, str):
            values = (values,)
        normalized = {str(value).strip().casefold() for value in values if str(value).strip()}
        return tuple(sorted(normalized))

    def find_matches(
        self,
        target_hex: str,
        limit: int = 3,
        brands: Iterable[str] | str | None = None,
        finish_classes: Iterable[str] | str | None = None,
        prefer_measured: bool = True,
        material: str = DEFAULT_FILAMENT_MATERIAL,
    ) -> tuple[FilamentMatch, ...]:
        normalized = normalize_hex(target_hex)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        brand_filter = self._normalize_filter(brands)
        finish_filter = self._normalize_filter(finish_classes)
        material_filter = normalize_filament_material(material)
        if not self.is_available:
            return ()
        return self._find_cached(
            normalized,
            limit,
            brand_filter,
            finish_filter,
            bool(prefer_measured),
            material_filter,
        )

    @lru_cache(maxsize=256)
    def _find_cached(
        self,
        target_hex: str,
        limit: int,
        brands: tuple[str, ...],
        finish_classes: tuple[str, ...],
        prefer_measured: bool,
        material: str,
    ) -> tuple[FilamentMatch, ...]:
        target_lab = srgb_hex_to_lab(target_hex)
        brand_set = set(brands)
        finish_set = set(finish_classes)
        scored: list[tuple[_FilamentRecord, FilamentMatch]] = []
        for record in self._records:
            if record.material != material:
                continue
            if brand_set and record.brand.casefold() not in brand_set:
                continue
            if finish_set and record.finish_class.casefold() not in finish_set:
                continue
            # Stored Lab values are rounded for portability.  Equal source HEX
            # values are the same sRGB point even if that rounding leaves a
            # microscopic non-zero Lab distance.
            delta_e = (
                0.0
                if target_hex == record.matched_hex
                else ciede2000(target_lab, record.lab)
            )
            match = FilamentMatch(
                brand=record.brand,
                series=record.series,
                color_name=record.color_name,
                matched_hex=record.matched_hex,
                delta_e_2000=delta_e,
                score=delta_e + record.finish_penalty,
                finish_class=record.finish_class,
                source_kind=record.source_kind,
                source_url=record.source_url,
                record_id=record.record_id,
                measurement_id=record.measurement_id,
                finish_penalty=record.finish_penalty,
                catalog_status=record.catalog_status,
                data_confidence=record.data_confidence,
                material=record.material,
            )
            scored.append((record, match))

        # A measured swatch and its catalog row describe one product.  Keep one
        # according to the user's preference, independently of their raw score.
        by_product: dict[tuple[str, ...], tuple[_FilamentRecord, FilamentMatch]] = {}
        preferred_kind = "measured" if prefer_measured else "catalog"
        for record, match in scored:
            previous = by_product.get(record.product_key)
            if previous is None:
                by_product[record.product_key] = (record, match)
                continue
            previous_record, previous_match = previous
            if record.source_kind == preferred_kind and previous_record.source_kind != preferred_kind:
                by_product[record.product_key] = (record, match)
            elif record.source_kind == previous_record.source_kind and (
                match.score,
                match.delta_e_2000,
            ) < (previous_match.score, previous_match.delta_e_2000):
                by_product[record.product_key] = (record, match)

        # Some catalogs repeat the same variant under different internal IDs.
        # Collapse exact display duplicates after measured/catalog resolution.
        deduplicated: dict[tuple[str, ...], tuple[_FilamentRecord, FilamentMatch]] = {}
        for record, match in by_product.values():
            previous = deduplicated.get(record.duplicate_key)
            if previous is None:
                deduplicated[record.duplicate_key] = (record, match)
                continue
            previous_record, previous_match = previous
            current_key = (
                match.score,
                0 if record.source_kind == preferred_kind else 1,
                match.record_id or "",
                match.measurement_id or "",
            )
            previous_key = (
                previous_match.score,
                0 if previous_record.source_kind == preferred_kind else 1,
                previous_match.record_id or "",
                previous_match.measurement_id or "",
            )
            if current_key < previous_key:
                deduplicated[record.duplicate_key] = (record, match)

        ranked = sorted(
            (pair[1] for pair in deduplicated.values()),
            key=lambda match: (
                match.score,
                match.delta_e_2000,
                0 if match.source_kind == preferred_kind else 1,
                match.brand.casefold(),
                match.series.casefold(),
                match.color_name.casefold(),
                match.matched_hex,
                match.record_id or "",
                match.measurement_id or "",
            ),
        )
        return tuple(ranked[:limit])


FilamentDatabaseRepository = FilamentRepository


__all__ = [
    "DATABASE_FILENAME",
    "FilamentDatabaseCorruptError",
    "FilamentDatabaseError",
    "FilamentDatabaseNotFoundError",
    "FilamentDatabaseRepository",
    "FilamentDatabaseSchemaError",
    "FilamentMatch",
    "FilamentMatcher",
    "FilamentProduct",
    "FilamentRepository",
    "ciede2000",
    "normalize_hex",
    "resolve_filament_database_path",
    "srgb_hex_to_lab",
]
