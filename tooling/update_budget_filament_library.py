#!/usr/bin/env python3
"""Rebuild the budget-brand extension of the bundled filament database.

The existing 15-brand PLA database remains the base. This migration adds ABS
and PETG for those brands, replaces the four selected budget-brand
PLA/ABS/PETG slices with catalog colours from the pinned Open Filament Database
snapshot, then stores dated Amazon.co.jp manufacturer-qualification evidence
in a separate table. Amazon data is never used as a colour source.

Example (from the repository root)::

    python tooling/update_budget_filament_library.py \
        --ofd-root C:/src/open-filament-database

The OFD checkout must be at ``dataset-v2026.08.16``.  Re-running the command on
an already migrated database is supported and produces the same logical data.
"""

from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import math
import os
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = (
    REPOSITORY_ROOT
    / "source"
    / "fixed_app"
    / "resources"
    / "filament_db"
    / "filament_color_database_2026-08.sqlite"
)
BASE_DATABASE_SHA256 = "5c75c3d81ad4f6517e0a914044ee8e0ea1f210a844126c505d3d6ffc6d7b4cf3"
OFD_TAG = "dataset-v2026.08.16"
OFD_VERSION = "v2026.08.16"
OFD_COMMIT = "81b06c646ef310fe7911cb230f96094e78bdeb43"
RETRIEVED_DATE = "2026-08-19"
SELECTED_BRAND_SLUGS = ("geeetech", "cc3d", "kingroon", "tinmorry")
BASE_BRAND_SLUGS = (
    "anycubic",
    "bambu_lab",
    "creality",
    "elegoo",
    "eryone",
    "esun_3d",
    "flashforge",
    "hatchbox",
    "jayo",
    "overture",
    "polymaker",
    "prusament",
    "qidi_tech",
    "snapmaker",
    "sunlu",
)
MATERIALS = ("PLA", "ABS", "PETG")
ACCEPTANCE_RULE = "Amazon.co.jp search result: rating >= 4.0 AND review_count >= 20"

# Search-result evidence is deliberately short and factual.  It establishes
# that a brand has a meaningfully reviewed PLA listing in Japan on one date;
# it neither certifies stock nor supplies a colour value.
AMAZON_JP_EVIDENCE = (
    {
        "brand": "Geeetech",
        "material": "PLA",
        "asin": "B0CNSJ58HH",
        "product_label": "PLA Black 1 kg",
        "rating": 4.3,
        "review_count": 2186,
        "search_query": "GEEETECH PLA フィラメント 1.75mm 1kg",
    },
    {
        "brand": "Geeetech",
        "material": "PLA",
        "asin": "B0CB68CYMB",
        "product_label": "PLA Skin 1 kg",
        "rating": 4.2,
        "review_count": 53,
        "search_query": "GEEETECH PLA フィラメント 1.75mm 1kg",
    },
    {
        "brand": "CC3D",
        "material": "PLA",
        "asin": "B06XSBFB17",
        "product_label": "Silk PLA Silver 1 kg",
        "rating": 4.3,
        "review_count": 13330,
        "search_query": "CC3D PLA フィラメント 1.75mm 1kg",
    },
    {
        "brand": "CC3D",
        "material": "PLA",
        "asin": "B099K27SQL",
        "product_label": "PLA MAX Steel Gray 1 kg",
        "rating": 4.5,
        "review_count": 222,
        "search_query": "CC3D PLA フィラメント 1.75mm 1kg",
    },
    {
        "brand": "CC3D",
        "material": "PLA",
        "asin": "B07R1L1J45",
        "product_label": "PLA MAX+ Black 1 kg",
        "rating": 4.3,
        "review_count": 3677,
        "search_query": "CC3D PLA フィラメント 1.75mm 1kg",
    },
    {
        "brand": "Kingroon",
        "material": "PLA",
        "asin": "B0DM8P2G1D",
        "product_label": "PLA Basic Bright Green 1 kg",
        "rating": 4.4,
        "review_count": 690,
        "search_query": "KINGROON PLA フィラメント 1.75mm 1kg",
    },
    {
        "brand": "Kingroon",
        "material": "PLA",
        "asin": "B0DMFD9FPY",
        "product_label": "Matte PLA Black 1 kg",
        "rating": 4.6,
        "review_count": 205,
        "search_query": "KINGROON PLA フィラメント 1.75mm 1kg",
    },
    {
        "brand": "TINMORRY",
        "material": "PLA",
        "asin": "B0G81BHMSB",
        "product_label": "High Speed PLA Black 1 kg",
        "rating": 4.2,
        "review_count": 1248,
        "search_query": "TINMORRY PLA フィラメント 1.75mm 1kg",
    },
    {
        "brand": "TINMORRY",
        "material": "PLA",
        "asin": "B0DHS588DK",
        "product_label": "Matte PLA Black 1 kg",
        "rating": 4.3,
        "review_count": 984,
        "search_query": "TINMORRY PLA フィラメント 1.75mm 1kg",
    },
    {
        "brand": "Geeetech",
        "material": "PETG",
        "asin": "B08DTHB3QL",
        "product_label": "PETG Gray 1 kg",
        "rating": 4.5,
        "review_count": 197,
        "search_query": "GEEETECH PETG フィラメント 1.75mm 1kg",
    },
    {
        "brand": "CC3D",
        "material": "PETG",
        "asin": "B0D91GX7SC",
        "product_label": "Standard PETG White 1 kg",
        "rating": 4.2,
        "review_count": 519,
        "search_query": "CC3D PETG フィラメント 1.75mm 1kg",
    },
    {
        "brand": "Kingroon",
        "material": "PETG",
        "asin": "B0CYC5J9SM",
        "product_label": "High Speed PETG Gray 1 kg",
        "rating": 4.6,
        "review_count": 306,
        "search_query": "KINGROON PETG フィラメント 1.75mm 1kg",
    },
    {
        "brand": "TINMORRY",
        "material": "ABS",
        "asin": "B0CVXJ74ZF",
        "product_label": "ABS Pro Black 1 kg",
        "rating": 4.0,
        "review_count": 67,
        "search_query": "TINMORRY ABS フィラメント 1.75mm 1kg",
    },
    {
        "brand": "TINMORRY",
        "material": "PETG",
        "asin": "B0BMTJCMFK",
        "product_label": "High Speed PETG Sky Blue 1 kg",
        "rating": 4.2,
        "review_count": 274,
        "search_query": "TINMORRY PETG フィラメント 1.75mm 1kg",
    },
)

CATALOG_COLUMNS = (
    "record_id",
    "brand",
    "brand_slug",
    "origin_country",
    "series",
    "material",
    "color_name",
    "color_category",
    "category_by_hex",
    "finish_class",
    "traits",
    "reference_hex",
    "r",
    "g",
    "b",
    "lab_l",
    "lab_a",
    "lab_b",
    "hsv_h",
    "hsv_s",
    "hsv_v",
    "comparison_eligible",
    "finish_penalty",
    "catalog_status",
    "data_type",
    "data_confidence",
    "brand_official_url",
    "catalog_source_url",
    "filament_id",
    "variant_id",
    "notes",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_hex(value: Any) -> str:
    text = str(value).strip().upper()
    if len(text) != 7 or text[0] != "#":
        raise ValueError(f"invalid OFD colour: {value!r}")
    int(text[1:], 16)
    return text


def _srgb_hex_to_lab(value: str) -> tuple[float, float, float]:
    channels = tuple(int(value[index : index + 2], 16) / 255.0 for index in (1, 3, 5))

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
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def _colour_category(red: int, green: int, blue: int) -> str:
    hue, saturation, value = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    if value <= 0.12:
        return "黒"
    if saturation <= 0.09:
        return "白" if value >= 0.88 else "グレー"
    degrees = hue * 360.0
    if degrees < 15.0 or degrees >= 345.0:
        return "赤"
    if degrees < 45.0:
        return "オレンジ/茶"
    if degrees < 75.0:
        return "黄"
    if degrees < 165.0:
        return "緑"
    if degrees < 195.0:
        return "シアン/青緑"
    if degrees < 255.0:
        return "青"
    if degrees < 285.0:
        return "紫"
    if degrees < 345.0:
        return "ピンク/マゼンタ"
    return "赤"


def _enabled_traits(variant: dict[str, Any]) -> tuple[str, ...]:
    traits = variant.get("traits") or {}
    if not isinstance(traits, dict):
        return ()
    return tuple(sorted(str(key) for key, enabled in traits.items() if enabled))


def _finish(traits: Iterable[str]) -> tuple[str, float]:
    values = set(traits)
    if "contains_carbon_fiber" in values:
        return "カーボン繊維", 3.0
    if "contains_glass_fiber" in values:
        return "ガラス繊維", 3.0
    if values & {"contains_wood", "imitates_wood"}:
        return "木質", 4.0
    if values & {"imitates_marble", "imitates_stone"}:
        return "マーブル/ストーン", 4.0
    if "glow" in values:
        return "蓄光", 4.0
    if values & {"transparent", "translucent"}:
        return "透明/半透明", 6.0
    if "matte" in values:
        return "マット", 1.0
    if values & {"silk", "metallic", "glitter", "iridescent", "imitates_metal"}:
        return "シルク/メタリック/光沢", 2.5
    return "標準/不透明", 0.0


def _validate_upstream(ofd_root: Path, *, skip_git_check: bool) -> None:
    if not (ofd_root / "data").is_dir():
        raise SystemExit(f"OFD data directory is missing: {ofd_root / 'data'}")
    if skip_git_check:
        return
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(ofd_root), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "The OFD source must be a git checkout at " + OFD_TAG
        ) from exc
    if commit != OFD_COMMIT:
        raise SystemExit(
            f"Unexpected OFD commit {commit}; expected {OFD_COMMIT} ({OFD_TAG})"
        )


def _catalog_rows(ofd_root: Path) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    import_plan = tuple(
        (brand_slug, material)
        for brand_slug in BASE_BRAND_SLUGS
        for material in ("ABS", "PETG")
    ) + tuple(
        (brand_slug, material)
        for brand_slug in SELECTED_BRAND_SLUGS
        for material in MATERIALS
    )
    for brand_slug, material in import_plan:
        brand_root = ofd_root / "data" / brand_slug
        brand = _read_json(brand_root / "brand.json")
        material_root = brand_root / material
        for filament_path in sorted(material_root.glob("*/filament.json")):
            filament = _read_json(filament_path)
            if bool(filament.get("discontinued")):
                continue
            filament_slug = filament_path.parent.name
            for variant_path in sorted(filament_path.parent.glob("*/variant.json")):
                variant = _read_json(variant_path)
                if bool(variant.get("discontinued")):
                    continue
                # A single screen colour is required for nearest-colour search.
                # OFD arrays describe gradient/co-extruded material and are not
                # silently collapsed to their first colour.
                raw_hex = variant.get("color_hex")
                if not isinstance(raw_hex, str):
                    continue
                reference_hex = _normalize_hex(raw_hex)
                red, green, blue = (
                    int(reference_hex[index : index + 2], 16) for index in (1, 3, 5)
                )
                lab_l, lab_a, lab_b = _srgb_hex_to_lab(reference_hex)
                hsv_h, hsv_s, hsv_v = colorsys.rgb_to_hsv(
                    red / 255.0, green / 255.0, blue / 255.0
                )
                traits = _enabled_traits(variant)
                finish_class, finish_penalty = _finish(traits)
                category = _colour_category(red, green, blue)
                variant_slug = variant_path.parent.name
                variant_uuid = str(variant["uuid"])
                source_url = (
                    "https://github.com/OpenFilamentCollective/"
                    "open-filament-database/blob/"
                    f"{OFD_TAG}/data/{brand_slug}/{material}/{filament_slug}/"
                    f"{variant_slug}/variant.json"
                )
                values = {
                    "record_id": f"ofd:{variant_uuid}",
                    "brand": str(brand["name"]),
                    "brand_slug": brand_slug,
                    "origin_country": str(brand.get("origin") or "Unknown"),
                    "series": str(filament["name"]),
                    "material": material,
                    "color_name": str(variant["name"]),
                    "color_category": category,
                    "category_by_hex": category,
                    "finish_class": finish_class,
                    "traits": ", ".join(traits),
                    "reference_hex": reference_hex,
                    "r": red,
                    "g": green,
                    "b": blue,
                    "lab_l": round(lab_l, 3),
                    "lab_a": round(lab_a, 3),
                    "lab_b": round(lab_b, 3),
                    "hsv_h": round(hsv_h * 360.0, 2),
                    "hsv_s": round(hsv_s * 100.0, 2),
                    "hsv_v": round(hsv_v * 100.0, 2),
                    "comparison_eligible": 1,
                    "finish_penalty": finish_penalty,
                    "catalog_status": "catalog_active (OFD)",
                    "data_type": "カタログ/画面表示色",
                    "data_confidence": "C（物理実測色ではない）",
                    "brand_official_url": str(brand.get("website") or ""),
                    "catalog_source_url": source_url,
                    "filament_id": str(filament["uuid"]),
                    "variant_id": variant_uuid,
                    "notes": (
                        f"OFD {OFD_VERSION} の color_hex。Amazon評価は色値に不使用。"
                        "catalog_active はOFD上で廃番指定がないことだけを示す。"
                    ),
                }
                rows.append(tuple(values[column] for column in CATALOG_COLUMNS))
    return rows


def _database_is_supported_base(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest == BASE_DATABASE_SHA256:
        return
    try:
        with closing(sqlite3.connect(path)) as connection:
            revision = connection.execute(
                "SELECT value FROM meta WHERE key = 'budget_library_revision'"
            ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise SystemExit(f"Invalid base database: {exc}") from exc
    if revision is None or revision[0] != RETRIEVED_DATE:
        raise SystemExit(
            "Refusing to migrate an unknown database revision. "
            f"Expected SHA-256 {BASE_DATABASE_SHA256}."
        )


def _apply_migration(path: Path, rows: list[tuple[Any, ...]]) -> None:
    placeholders = ", ".join("?" for _ in CATALOG_COLUMNS)
    columns_sql = ", ".join(f'"{column}"' for column in CATALOG_COLUMNS)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS amazon_jp_evidence (
                evidence_id TEXT PRIMARY KEY,
                brand TEXT NOT NULL,
                material TEXT NOT NULL CHECK (material IN ('PLA', 'ABS', 'PETG')),
                asin TEXT NOT NULL UNIQUE,
                product_label TEXT NOT NULL,
                product_url TEXT NOT NULL,
                rating REAL NOT NULL CHECK (rating >= 0.0 AND rating <= 5.0),
                review_count INTEGER NOT NULL CHECK (review_count >= 0),
                retrieved_date TEXT NOT NULL,
                search_query TEXT NOT NULL,
                acceptance_rule TEXT NOT NULL,
                evidence_scope TEXT NOT NULL,
                notes TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "DELETE FROM catalog_colors WHERE brand_slug = ? AND material IN ('ABS', 'PETG')",
            ((slug,) for slug in BASE_BRAND_SLUGS),
        )
        connection.executemany(
            "DELETE FROM catalog_colors WHERE brand_slug = ? AND material IN ('PLA', 'ABS', 'PETG')",
            ((slug,) for slug in SELECTED_BRAND_SLUGS),
        )
        connection.execute("DELETE FROM amazon_jp_evidence")
        connection.executemany(
            f"INSERT INTO catalog_colors ({columns_sql}) VALUES ({placeholders})",
            rows,
        )
        evidence_rows = []
        for evidence in AMAZON_JP_EVIDENCE:
            asin = str(evidence["asin"])
            evidence_rows.append(
                (
                    f"amazon-jp:{RETRIEVED_DATE}:{asin}",
                    evidence["brand"],
                    evidence["material"],
                    asin,
                    evidence["product_label"],
                    f"https://www.amazon.co.jp/dp/{asin}",
                    evidence["rating"],
                    evidence["review_count"],
                    RETRIEVED_DATE,
                    evidence["search_query"],
                    ACCEPTANCE_RULE,
                    "manufacturer qualification only",
                    (
                        "Representative product used only to qualify the manufacturer. "
                        "Rating/review count and availability can change; this does not mean "
                        "that every catalog row was individually reviewed. Not used for "
                        "reference_hex or colour accuracy."
                    ),
                )
            )
        connection.executemany(
            """
            INSERT INTO amazon_jp_evidence (
                evidence_id, brand, material, asin, product_label, product_url, rating,
                review_count, retrieved_date, search_query, acceptance_rule,
                evidence_scope, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            evidence_rows,
        )
        source_row = (
            "Open Filament Database material extension",
            "catalog/display colour",
            f"https://github.com/OpenFilamentCollective/open-filament-database/tree/{OFD_TAG}",
            "PLA/ABS/PETG catalog extension; four qualified budget brands plus ABS/PETG for the base brands",
        )
        connection.execute(
            "DELETE FROM sources WHERE source_name IN (?, ?)",
            (source_row[0], "Open Filament Database budget additions"),
        )
        connection.execute(
            "INSERT INTO sources (source_name, source_type, url, use) VALUES (?, ?, ?, ?)",
            source_row,
        )
        for legacy_key in (
            "raw_brand_count",
            "raw_filament_count",
            "raw_material_count",
            "raw_variant_count",
        ):
            row = connection.execute(
                "SELECT value FROM meta WHERE key = ?",
                (legacy_key,),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "INSERT INTO meta(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (f"base_{legacy_key}", row[0]),
                )
                connection.execute("DELETE FROM meta WHERE key = ?", (legacy_key,))
        metadata = {
            "database_name": "PLA / ABS / PETG Filament Color Database",
            "build_date": RETRIEVED_DATE,
            "brand_count": str(
                connection.execute(
                    "SELECT COUNT(DISTINCT brand) FROM catalog_colors"
                ).fetchone()[0]
            ),
            "catalog_color_count": str(
                connection.execute("SELECT COUNT(*) FROM catalog_colors").fetchone()[0]
            ),
            "scope": (
                "15-brand PLA v2026.07.31 base plus PLA/ABS/PETG catalog extensions "
                f"from OFD {OFD_VERSION}; active single-colour variants"
            ),
            "ofd_version": (
                "base PLA v2026.07.31; material extensions " + OFD_VERSION
            ),
            "ofd_generated": (
                "base 2026-07-31T23:14:28Z; extensions " + OFD_TAG
            ),
            "budget_library_revision": RETRIEVED_DATE,
            "budget_ofd_version": OFD_VERSION,
            "budget_ofd_commit": OFD_COMMIT,
            "budget_brand_count": str(len(SELECTED_BRAND_SLUGS)),
            "catalog_materials": ",".join(MATERIALS),
            "ofd_extension_catalog_color_count": str(len(rows)),
            "budget_catalog_color_count": str(
                connection.execute(
                    "SELECT COUNT(*) FROM catalog_colors WHERE brand_slug IN (?, ?, ?, ?)",
                    SELECTED_BRAND_SLUGS,
                ).fetchone()[0]
            ),
            "amazon_jp_evidence_date": RETRIEVED_DATE,
            "amazon_jp_evidence_count": str(len(evidence_rows)),
            "amazon_jp_acceptance_rule": ACCEPTANCE_RULE,
            "amazon_jp_evidence_note": (
                "Manufacturer qualification evidence only; it does not review every catalog "
                "row, is not live inventory, and is not a colour source."
            ),
        }
        for material in MATERIALS:
            metadata[f"catalog_color_count_{material.lower()}"] = str(
                connection.execute(
                    "SELECT COUNT(*) FROM catalog_colors WHERE material = ?",
                    (material,),
                ).fetchone()[0]
            )
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            sorted(metadata.items()),
        )
        connection.commit()
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise RuntimeError(f"SQLite quick_check failed: {result}")
        connection.execute("VACUUM")


def update_database(
    *,
    database: Path,
    ofd_root: Path,
    output: Path,
    skip_git_check: bool,
) -> tuple[int, str]:
    database = database.resolve()
    output = output.resolve()
    ofd_root = ofd_root.resolve()
    if not database.is_file():
        raise SystemExit(f"Database not found: {database}")
    _database_is_supported_base(database)
    _validate_upstream(ofd_root, skip_git_check=skip_git_check)
    rows = _catalog_rows(ofd_root)
    if len(rows) != 1080:
        raise SystemExit(
            f"Pinned OFD snapshot yielded {len(rows)} rows; expected 1080"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="obj-adjuster-filament-db-") as directory:
        work = Path(directory) / output.name
        shutil.copyfile(database, work)
        _apply_migration(work, rows)
        os.replace(work, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return len(rows), digest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="base or already migrated SQLite database",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output SQLite path (default: replace --database atomically)",
    )
    parser.add_argument(
        "--ofd-root",
        type=Path,
        required=True,
        help=f"Open Filament Database checkout at {OFD_TAG}",
    )
    parser.add_argument(
        "--skip-git-check",
        action="store_true",
        help="allow a source archive without .git; file contents remain schema-validated",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output = args.output or args.database
    row_count, digest = update_database(
        database=args.database,
        ofd_root=args.ofd_root,
        output=output,
        skip_git_check=bool(args.skip_git_check),
    )
    print(f"budget catalog rows: {row_count}")
    print(f"amazon evidence rows: {len(AMAZON_JP_EVIDENCE)}")
    print(f"output: {Path(output).resolve()}")
    print(f"sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
