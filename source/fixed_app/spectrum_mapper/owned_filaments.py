from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from itertools import permutations
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .filament_database import FilamentProduct, FilamentRepository, normalize_hex
from .filament_materials import (
    DEFAULT_FILAMENT_MATERIAL,
    normalize_filament_material,
)
from .filament_recommender import (
    _coerce_rgb_samples,
    CATEGORY_PRIMARY,
    DEFAULT_MAX_CANDIDATES,
    FilamentCandidate,
    PaletteProposal,
    build_representative_colors,
    recommend_basic_filaments,
)
from .mixer import (
    DEFAULT_PALETTE_STATE_COUNT,
    NEUTRAL_PALETTE_STATES,
    PALETTE_STATE_COUNT,
    PINK_PALETTE_STATES,
    SUPPORTED_PALETTE_STATE_COUNTS,
    GlobalMixOptimizationResult,
    build_palette_rgb,
    coerce_palette_state_count,
    optimize_global_mix_ratios,
)


OWNED_FILAMENT_INVENTORY_FILENAME = "owned_filaments.json"
OWNED_FILAMENT_INVENTORY_SCHEMA_VERSION = 1
MAX_OWNED_RECOMMENDATION_CANDIDATES = 24
OWNED_REFINEMENT_SHORTLIST_SIZE = 12
OWNED_RATIO_REFINEMENT_COMBINATIONS = 4
_DEFAULT_PRIMARY_RATIOS = (33,) * 6
_DEFAULT_SECONDARY_RATIOS = (67,) * 6


class OwnedFilamentInventoryError(RuntimeError):
    """A readable inventory could not be loaded or saved safely."""


class OwnedFilamentSelectionError(ValueError):
    """The owned pool cannot form a useful four-colour physical palette."""


def resolve_owned_filament_inventory_path(
    explicit_path: str | os.PathLike[str] | None = None,
) -> Path:
    """Return the model-independent inventory path.

    Only the resolved path is machine-specific.  The JSON itself contains no
    absolute paths, so it is safe to move between user profiles and computers.
    """

    if explicit_path is not None:
        return Path(explicit_path).expanduser().resolve()
    app_data = os.environ.get("APPDATA")
    base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
    return (base / "TripoSpectrumMapper" / OWNED_FILAMENT_INVENTORY_FILENAME).resolve()


def _product_preference_key(product: FilamentProduct) -> tuple[object, ...]:
    return (
        0 if product.source_kind == "measured" else 1,
        product.finish_penalty,
        product.product_id.casefold(),
        product.product_id,
    )


def _duplicate_color_groups(
    products: Sequence[FilamentProduct],
) -> tuple[tuple[str, ...], ...]:
    grouped: dict[str, list[str]] = {}
    for product in products:
        grouped.setdefault(product.matched_hex, []).append(product.product_id)
    duplicates = [
        tuple(sorted(ids, key=lambda value: (value.casefold(), value)))
        for ids in grouped.values()
        if len(ids) > 1
    ]
    duplicates.sort(key=lambda values: tuple(value.casefold() for value in values))
    return tuple(duplicates)


def _unique_color_products(
    products: Sequence[FilamentProduct],
) -> tuple[FilamentProduct, ...]:
    grouped: dict[str, list[FilamentProduct]] = {}
    for product in products:
        grouped.setdefault(product.matched_hex, []).append(product)
    selected = [min(group, key=_product_preference_key) for group in grouped.values()]
    selected.sort(key=lambda product: (product.product_id.casefold(), product.product_id))
    return tuple(selected)


@dataclass(frozen=True, slots=True)
class OwnedFilamentInventory:
    """Owned products plus explicit database/snapshot diagnostics."""

    products: tuple[FilamentProduct, ...] = ()
    stale_product_ids: tuple[str, ...] = ()
    unresolved_product_ids: tuple[str, ...] = ()
    invalid_entries: tuple[str, ...] = ()
    duplicate_color_groups: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        products = tuple(self.products)
        if not all(isinstance(product, FilamentProduct) for product in products):
            raise TypeError("products must contain FilamentProduct values")
        seen: set[str] = set()
        unique: list[FilamentProduct] = []
        for product in products:
            if product.product_id in seen:
                continue
            seen.add(product.product_id)
            unique.append(product)
        object.__setattr__(self, "products", tuple(unique))
        object.__setattr__(
            self,
            "stale_product_ids",
            _normalize_id_tuple(self.stale_product_ids),
        )
        object.__setattr__(
            self,
            "unresolved_product_ids",
            _normalize_id_tuple(self.unresolved_product_ids),
        )
        object.__setattr__(self, "invalid_entries", tuple(self.invalid_entries))
        object.__setattr__(
            self,
            "duplicate_color_groups",
            self.duplicate_color_groups or _duplicate_color_groups(tuple(unique)),
        )

    @property
    def product_ids(self) -> tuple[str, ...]:
        return tuple(product.product_id for product in self.products)

    @property
    def recommendable_products(self) -> tuple[FilamentProduct, ...]:
        """Owned products with duplicate HEX values collapsed for search."""

        return _unique_color_products(self.products)

    def products_for_material(self, material: str) -> tuple[FilamentProduct, ...]:
        selected = normalize_filament_material(material)
        return tuple(
            product for product in self.products if product.material == selected
        )

    def recommendable_for_material(
        self, material: str
    ) -> tuple[FilamentProduct, ...]:
        return _unique_color_products(self.products_for_material(material))

    @property
    def can_recommend(self) -> bool:
        return len(self.recommendable_products) >= 4

    @property
    def diagnostics(self) -> tuple[str, ...]:
        messages: list[str] = []
        if self.stale_product_ids:
            messages.append(
                "DBで確認できない手持ちフィラメントを保存時の色情報で使用します: "
                + ", ".join(self.stale_product_ids)
            )
        if self.unresolved_product_ids:
            messages.append(
                "DBにも保存時の色情報にもない手持ちフィラメントがあります: "
                + ", ".join(self.unresolved_product_ids)
            )
        if self.invalid_entries:
            messages.append(
                f"手持ちフィラメント設定の不正な項目を{len(self.invalid_entries)}件読み飛ばしました"
            )
        if self.duplicate_color_groups:
            messages.append(
                f"同じHEX色の手持ちフィラメントが{len(self.duplicate_color_groups)}組あります。"
                "自動4色構成では各色を1本として扱います"
            )
        if len(self.recommendable_products) < 4:
            messages.append(
                "自動4色構成には異なるHEX色の手持ちフィラメントが4本以上必要です"
            )
        return tuple(messages)


def _normalize_id_tuple(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _clean_text(value: object, *, maximum: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or len(text) > maximum:
        return ""
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        return ""
    return text


def _optional_text(value: object, *, maximum: int = 2048) -> str | None:
    text = _clean_text(value, maximum=maximum)
    return text or None


def _snapshot_from_mapping(value: object) -> FilamentProduct | None:
    if not isinstance(value, dict):
        return None
    product_id = _clean_text(value.get("product_id"), maximum=512)
    brand = _clean_text(value.get("brand"))
    color_name = _clean_text(value.get("color_name"))
    try:
        matched_hex = normalize_hex(value.get("matched_hex"))  # type: ignore[arg-type]
        material = normalize_filament_material(
            value.get("material", DEFAULT_FILAMENT_MATERIAL)
        )
    except ValueError:
        return None
    if not product_id or not brand or not color_name:
        return None
    try:
        finish_penalty = float(value.get("finish_penalty", 0.0))
    except (TypeError, ValueError):
        finish_penalty = 0.0
    if not math.isfinite(finish_penalty) or finish_penalty < 0.0:
        finish_penalty = 0.0
    original_source_kind = (
        _clean_text(value.get("source_kind"), maximum=40) or "snapshot"
    )
    record_id = _optional_text(value.get("record_id"), maximum=512)
    measurement_id = _optional_text(value.get("measurement_id"), maximum=512)
    return FilamentProduct(
        product_id=product_id,
        brand=brand,
        series=_clean_text(value.get("series")),
        color_name=color_name,
        matched_hex=matched_hex,
        finish_class=_clean_text(value.get("finish_class")),
        source_kind="snapshot",
        source_url=_optional_text(value.get("source_url")),
        record_id=record_id,
        measurement_id=measurement_id,
        finish_penalty=finish_penalty,
        catalog_status=_optional_text(value.get("catalog_status"), maximum=500),
        data_confidence=_optional_text(value.get("data_confidence"), maximum=500),
        alias_product_ids=(product_id,),
        snapshot_source_kind=original_source_kind,
        material=material,
    )


def _product_snapshot(product: FilamentProduct) -> dict[str, object]:
    return {
        "product_id": product.product_id,
        "brand": product.brand,
        "series": product.series,
        "color_name": product.color_name,
        "matched_hex": product.matched_hex,
        "finish_class": product.finish_class,
        "source_kind": product.snapshot_source_kind or product.source_kind,
        "source_url": product.source_url,
        "record_id": product.record_id,
        "measurement_id": product.measurement_id,
        "finish_penalty": float(product.finish_penalty),
        "catalog_status": product.catalog_status,
        "data_confidence": product.data_confidence,
        "material": product.material,
    }


def load_owned_filament_inventory(
    path: str | os.PathLike[str] | None = None,
    *,
    repository: FilamentRepository | None = None,
    prefer_measured: bool = True,
) -> OwnedFilamentInventory:
    """Load inventory, preferring current DB rows and retaining stale snapshots."""

    inventory_path = resolve_owned_filament_inventory_path(path)
    if not inventory_path.is_file():
        return OwnedFilamentInventory()
    try:
        raw = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OwnedFilamentInventoryError(
            f"手持ちフィラメント設定を読み取れません: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise OwnedFilamentInventoryError("手持ちフィラメント設定の形式が不正です")
    version = raw.get("schema_version", 1)
    if version != OWNED_FILAMENT_INVENTORY_SCHEMA_VERSION:
        raise OwnedFilamentInventoryError(
            f"未対応の手持ちフィラメント設定バージョンです: {version}"
        )

    current_lookup: dict[str, FilamentProduct] = {}
    if repository is not None:
        for product in repository.list_products(prefer_measured=prefer_measured):
            for alias in product.alias_product_ids:
                current_lookup[alias] = product

    entries = raw.get("products", ())
    if not isinstance(entries, list):
        entries = ()
    products: list[FilamentProduct] = []
    stale: list[str] = []
    unresolved: list[str] = []
    invalid: list[str] = []
    seen_current: set[str] = set()

    for index, value in enumerate(entries):
        product_id = (
            _clean_text(value.get("product_id"), maximum=512)
            if isinstance(value, dict)
            else ""
        )
        current = current_lookup.get(product_id)
        if current is not None:
            if current.product_id not in seen_current:
                products.append(current)
                seen_current.add(current.product_id)
            continue
        snapshot = _snapshot_from_mapping(value)
        if snapshot is None:
            if product_id:
                unresolved.append(product_id)
            invalid.append(f"products[{index}]")
            continue
        if snapshot.product_id not in seen_current:
            products.append(snapshot)
            seen_current.add(snapshot.product_id)
        # ``repository=None`` also means the current DB could not be checked.
        # Treat the portable snapshot as usable-but-unverified rather than
        # silently presenting it as a current catalog row.
        stale.append(snapshot.product_id)

    # v1 beta builds briefly persisted IDs without snapshots.  Keep those IDs
    # explicit so a missing DB row is never silently lost.
    legacy_ids = raw.get("product_ids", ())
    if isinstance(legacy_ids, list):
        for value in legacy_ids:
            product_id = _clean_text(value, maximum=512)
            if not product_id:
                invalid.append("product_ids")
                continue
            current = current_lookup.get(product_id)
            if current is not None:
                if current.product_id not in seen_current:
                    products.append(current)
                    seen_current.add(current.product_id)
            elif product_id not in seen_current:
                unresolved.append(product_id)

    persisted_unresolved = raw.get("unresolved_product_ids", ())
    if isinstance(persisted_unresolved, list):
        unresolved.extend(
            value
            for value in (_clean_text(item, maximum=512) for item in persisted_unresolved)
            if value
        )

    return OwnedFilamentInventory(
        products=tuple(products),
        stale_product_ids=_normalize_id_tuple(stale),
        unresolved_product_ids=_normalize_id_tuple(unresolved),
        invalid_entries=tuple(invalid),
    )


def save_owned_filament_inventory(
    inventory_or_products: OwnedFilamentInventory | Sequence[FilamentProduct],
    path: str | os.PathLike[str] | None = None,
) -> Path:
    """Atomically save IDs and portable display/colour snapshots."""

    if isinstance(inventory_or_products, OwnedFilamentInventory):
        inventory = inventory_or_products
    else:
        inventory = OwnedFilamentInventory(products=tuple(inventory_or_products))
    inventory_path = resolve_owned_filament_inventory_path(path)
    payload = {
        "schema_version": OWNED_FILAMENT_INVENTORY_SCHEMA_VERSION,
        "products": [_product_snapshot(product) for product in inventory.products],
        "unresolved_product_ids": list(inventory.unresolved_product_ids),
    }
    temporary = inventory_path.with_name(inventory_path.name + ".tmp")
    try:
        inventory_path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, inventory_path)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise OwnedFilamentInventoryError(
            f"手持ちフィラメント設定を保存できません: {exc}"
        ) from exc
    return inventory_path


@dataclass(frozen=True, slots=True)
class OwnedFilamentRecommendation:
    """Four owned spools plus ratios fitted to the supplied model colours."""

    candidates: tuple[FilamentProduct, ...]
    palette_state_count: int
    palette_hex: tuple[str, ...]
    mix_ratios_b: tuple[int, ...]
    secondary_mix_ratios_b: tuple[int, ...]
    initial_mix_ratios_b: tuple[int, ...]
    initial_secondary_mix_ratios_b: tuple[int, ...]
    mean_delta_e76: float
    before_mean_delta_e76: float
    improvement_delta_e76: float
    improvement_percent: float
    confidence: float
    candidate_pool_size: int
    evaluated_combinations: int
    ignored_duplicate_color_product_ids: tuple[str, ...]
    special_finish_products: tuple[FilamentProduct, ...]
    warnings: tuple[str, ...]
    refined_combination_count: int
    selection: PaletteProposal
    optimization: GlobalMixOptimizationResult

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate.product_id for candidate in self.candidates)

    @property
    def physical_hex(self) -> tuple[str, ...]:
        return tuple(candidate.matched_hex for candidate in self.candidates)


def _coerce_enabled_for_state_count(
    enabled_states: Sequence[bool] | None,
    palette_state_count: int,
) -> tuple[bool, ...]:
    if enabled_states is None:
        enabled = [True] * palette_state_count
    else:
        enabled = list(enabled_states)
        if len(enabled) not in (10, *SUPPORTED_PALETTE_STATE_COUNTS):
            raise ValueError("enabled_states must contain 10, 16, 24, or 32 booleans")
        if any(not isinstance(value, (bool, np.bool_)) for value in enabled):
            raise ValueError("enabled_states must contain only booleans")
    enabled += [False] * (PALETTE_STATE_COUNT - len(enabled))
    enabled = enabled[:PALETTE_STATE_COUNT]
    for index in range(palette_state_count, PALETTE_STATE_COUNT):
        enabled[index] = False
    if not any(enabled):
        raise ValueError("at least one palette state must be enabled")
    return tuple(bool(value) for value in enabled)


def _initial_order_score(
    products: Sequence[FilamentProduct],
    representative_rgb: np.ndarray,
    representative_weights: np.ndarray,
    *,
    state_count: int,
    enabled_states: Sequence[bool],
    initial_ratios_b: Sequence[int],
    secondary_ratios_b: Sequence[int],
    pink_protection_mask: np.ndarray | None = None,
    unrestricted_state_mask: np.ndarray | None = None,
) -> float:
    """Score one F1..F4 order using the application's exact palette model."""

    from .engine import srgb_to_lab

    _hex_values, palette_rgb = build_palette_rgb(
        [product.matched_hex for product in products],
        None,
        [int(value) for value in initial_ratios_b],
        [int(value) for value in secondary_ratios_b],
    )
    active_indices = np.flatnonzero(
        np.asarray(enabled_states[:state_count], dtype=bool)
    )
    target_lab = srgb_to_lab(
        np.asarray(representative_rgb, dtype=np.float64).reshape(-1, 3) / 255.0
    )
    if pink_protection_mask is None:
        palette_lab = srgb_to_lab(palette_rgb[active_indices])
        delta = target_lab[:, None, :] - palette_lab[None, :, :]
        distances = np.sqrt(np.sum(delta * delta, axis=2)).min(axis=1)
        return float(np.dot(representative_weights, distances))

    score = 0.0
    unrestricted = (
        np.zeros(len(representative_rgb), dtype=bool)
        if unrestricted_state_mask is None
        else unrestricted_state_mask
    )
    for group_mask, allowed_states in (
        (unrestricted, tuple(range(PALETTE_STATE_COUNT))),
        ((~pink_protection_mask) & (~unrestricted), NEUTRAL_PALETTE_STATES),
        (pink_protection_mask & (~unrestricted), PINK_PALETTE_STATES),
    ):
        if not np.any(group_mask):
            continue
        group_indices = np.asarray(
            [
                state
                for state in allowed_states
                if state < state_count and enabled_states[state]
            ],
            dtype=np.int64,
        )
        if len(group_indices) == 0:
            raise OwnedFilamentSelectionError(
                "F4系保護に必要なパレット状態が有効になっていません"
            )
        palette_lab = srgb_to_lab(palette_rgb[group_indices])
        delta = target_lab[group_mask, None, :] - palette_lab[None, :, :]
        distances = np.sqrt(np.sum(delta * delta, axis=2)).min(axis=1)
        score += float(np.dot(representative_weights[group_mask], distances))
    return score


def _best_initial_slot_order(
    products: Sequence[FilamentProduct],
    representative_rgb: np.ndarray,
    representative_weights: np.ndarray,
    *,
    state_count: int,
    enabled_states: Sequence[bool],
    initial_ratios_b: Sequence[int],
    secondary_ratios_b: Sequence[int],
    pink_protection_mask: np.ndarray | None = None,
    unrestricted_state_mask: np.ndarray | None = None,
) -> tuple[tuple[FilamentProduct, ...], float]:
    """Evaluate all 24 F1..F4 placements.

    The 24/32-state layouts are slot-asymmetric: quarter shades are attached
    to particular pairs.  Checking only an unordered set can therefore waste
    the added gradient states.  Twenty-four orders is small and deterministic.
    """

    ranked: list[tuple[float, tuple[str, ...], tuple[FilamentProduct, ...]]] = []
    for order in permutations(tuple(products), 4):
        score = _initial_order_score(
            order,
            representative_rgb,
            representative_weights,
            state_count=state_count,
            enabled_states=enabled_states,
            initial_ratios_b=initial_ratios_b,
            secondary_ratios_b=secondary_ratios_b,
            pink_protection_mask=pink_protection_mask,
            unrestricted_state_mask=unrestricted_state_mask,
        )
        ranked.append(
            (score, tuple(product.product_id for product in order), tuple(order))
        )
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][2], ranked[0][0]


def _shortlist_owned_products(
    products: Sequence[FilamentProduct],
    representative_rgb: np.ndarray,
    representative_weights: np.ndarray,
    maximum: int,
    required_physical_rgb: Sequence[Sequence[float]] | np.ndarray | None = None,
) -> tuple[FilamentProduct, ...]:
    """Bound combinations while retaining useful colour-gamut endpoints.

    A nearest-single-colour shortlist can discard red/blue endpoints when the
    model is mostly purple even though their physical mix is excellent.  Keep
    all six Lab-axis extrema first, then fill the remaining slots by weighted
    distance to the model.  The later exhaustive four-combination search still
    decides which of these candidates is actually useful.
    """

    values = tuple(products)
    from .engine import srgb_to_lab

    candidate_rgb = np.asarray(
        [
            tuple(int(product.matched_hex[index : index + 2], 16) for index in (1, 3, 5))
            for product in values
        ],
        dtype=np.float64,
    )
    candidate_lab = srgb_to_lab(candidate_rgb / 255.0)
    required_lab = None
    if required_physical_rgb is not None:
        required_rgb = _coerce_rgb_samples(
            required_physical_rgb,
            "required_physical_rgb",
        )
        if len(required_rgb) > 4:
            raise ValueError("required_physical_rgb may contain at most four colours")
        required_lab = srgb_to_lab(required_rgb / 255.0)
    if len(values) <= maximum:
        return values
    target_lab = srgb_to_lab(
        np.asarray(representative_rgb, dtype=np.float64).reshape(-1, 3) / 255.0
    )
    delta = target_lab[:, None, :] - candidate_lab[None, :, :]
    distances = np.sqrt(np.sum(delta * delta, axis=2))
    individual_scores = representative_weights @ distances

    selected_indices: list[int] = []
    selected_set: set[int] = set()
    if required_lab is not None:
        for target in required_lab:
            delta = candidate_lab - target[None, :]
            distances = np.sqrt(np.sum(delta * delta, axis=1))
            ranked_required = sorted(
                range(len(values)),
                key=lambda index: (
                    float(distances[index]),
                    values[index].product_id.casefold(),
                    values[index].product_id,
                ),
            )
            for index in ranked_required:
                if index not in selected_set:
                    selected_indices.append(index)
                    selected_set.add(index)
                    break
    for axis in range(3):
        for index in (int(np.argmin(candidate_lab[:, axis])), int(np.argmax(candidate_lab[:, axis]))):
            if len(selected_indices) >= maximum:
                break
            if index not in selected_set:
                selected_indices.append(index)
                selected_set.add(index)
    ranked = sorted(
        range(len(values)),
        key=lambda index: (
            float(individual_scores[index]),
            values[index].product_id.casefold(),
            values[index].product_id,
        ),
    )
    for index in ranked:
        if len(selected_indices) >= maximum:
            break
        if index in selected_set:
            continue
        selected_indices.append(index)
        selected_set.add(index)
    result = [values[index] for index in selected_indices]
    result.sort(key=lambda product: (product.product_id.casefold(), product.product_id))
    return tuple(result)


def _masked_representative_samples(
    object_rgb: Sequence[Sequence[float]] | np.ndarray,
    object_area_weights: Sequence[float] | np.ndarray | None,
    pink_protection_mask: Sequence[bool] | np.ndarray,
    *,
    reference_rgb: Sequence[Sequence[float]] | np.ndarray | None = None,
    reference_weights: Sequence[float] | np.ndarray | None = None,
    object_weight_fraction: float = 1.0,
    reference_weight_fraction: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compress protected OBJ and unrestricted reference samples separately.

    Reference pixels have no face-level protection mask.  They therefore keep
    the recommender's original meaning: a bounded supporting distribution that
    may match any enabled palette state.  Their configured fraction is retained
    instead of disappearing when OBJ F4 protection is active.
    """

    colors = np.asarray(object_rgb)
    if colors.ndim != 2 or colors.shape[1] != 3 or len(colors) == 0:
        raise ValueError("object_rgb must be a non-empty N x 3 array")
    mask = np.asarray(pink_protection_mask)
    if mask.ndim != 1 or len(mask) != len(colors):
        raise ValueError("pink_protection_mask must match object_rgb length")
    if mask.dtype != np.bool_:
        if not all(isinstance(value, (bool, np.bool_)) for value in mask.tolist()):
            raise ValueError("pink_protection_mask must contain only booleans")
        mask = mask.astype(bool)
    if object_area_weights is None:
        weights = np.ones(len(colors), dtype=np.float64)
    else:
        weights = np.asarray(object_area_weights, dtype=np.float64)
        if weights.ndim != 1 or len(weights) != len(colors):
            raise ValueError("object_area_weights must match object_rgb length")
        if not np.all(np.isfinite(weights)) or np.any(weights < 0.0):
            raise ValueError("object_area_weights must be finite and non-negative")
    positive_total = float(weights.sum())
    if positive_total <= 0.0:
        raise ValueError("object_area_weights must have positive total weight")

    rgb_values: list[tuple[int, int, int]] = []
    weight_values: list[float] = []
    mask_values: list[bool] = []
    unrestricted_values: list[bool] = []
    for protected in (False, True):
        group = (mask == protected) & (weights > 0.0)
        if not np.any(group):
            continue
        representative_set = build_representative_colors(
            colors[group],
            weights[group],
            max_colors=128,
        )
        group_fraction = (
            float(weights[group].sum())
            / positive_total
            * float(object_weight_fraction)
        )
        for representative in representative_set.colors:
            rgb_values.append(representative.rgb8)
            weight_values.append(representative.weight_fraction * group_fraction)
            mask_values.append(protected)
            unrestricted_values.append(False)

    if reference_rgb is not None and float(reference_weight_fraction) > 0.0:
        reference_set = build_representative_colors(
            reference_rgb,
            reference_weights,
            max_colors=128,
        )
        for representative in reference_set.colors:
            rgb_values.append(representative.rgb8)
            weight_values.append(
                representative.weight_fraction * float(reference_weight_fraction)
            )
            # The value is ignored for unrestricted samples, but False keeps
            # the boolean mask deterministic and easy to inspect in tests.
            mask_values.append(False)
            unrestricted_values.append(True)
    return (
        np.asarray(rgb_values, dtype=np.uint8),
        np.asarray(weight_values, dtype=np.float64),
        np.asarray(mask_values, dtype=bool),
        np.asarray(unrestricted_values, dtype=bool),
    )


def recommend_from_owned_filaments(
    object_rgb: Sequence[Sequence[float]] | np.ndarray,
    object_area_weights: Sequence[float] | np.ndarray | None = None,
    *,
    owned_products: Sequence[FilamentProduct],
    material: str = DEFAULT_FILAMENT_MATERIAL,
    reference_rgb: Sequence[Sequence[float]] | np.ndarray | None = None,
    reference_weights: Sequence[float] | np.ndarray | None = None,
    reference_confidence: float = 1.0,
    palette_state_count: int = DEFAULT_PALETTE_STATE_COUNT,
    initial_ratios_b: Sequence[int] | None = None,
    secondary_ratios_b: Sequence[int] | None = None,
    enabled_states: Sequence[bool] | None = None,
    include_mixed_states: bool = True,
    pink_protection_mask: Sequence[bool] | np.ndarray | None = None,
    required_physical_rgb: Sequence[Sequence[float]] | np.ndarray | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_passes: int = 8,
) -> OwnedFilamentRecommendation:
    """Choose four owned products and optionally fit both six-ratio ramps.

    Candidate search is capped before the O(n choose 4) evaluation so a large
    personal inventory cannot freeze the UI.  Same-HEX spools remain visible in
    the inventory but only one representative participates in automatic search.
    The final ratio fit uses the exact 16/24/32 active-state boundary supplied
    by the caller and the same mixer model as normal conversion.  When
    ``include_mixed_states`` is false, all four physical slots are evaluated
    and every mixed state is excluded; the stored ratios remain unchanged.
    """

    selected_material = normalize_filament_material(material)
    products = tuple(owned_products)
    if not all(isinstance(product, FilamentProduct) for product in products):
        raise TypeError("owned_products must contain FilamentProduct values")
    cross_material = tuple(
        product.product_id
        for product in products
        if product.material != selected_material
    )
    if cross_material:
        raise OwnedFilamentSelectionError(
            f"{selected_material}で混色する4本に異素材を含めることはできません: "
            + ", ".join(cross_material)
        )
    if len({product.product_id for product in products}) != len(products):
        raise OwnedFilamentSelectionError(
            "手持ちフィラメントに同じ製品IDが重複しています"
        )
    unique_products = _unique_color_products(products)
    if len(products) < 4:
        raise OwnedFilamentSelectionError(
            "自動4色構成には手持ちフィラメントが4本以上必要です"
        )
    if len(unique_products) < 4:
        raise OwnedFilamentSelectionError(
            "自動4色構成には異なるHEX色の手持ちフィラメントが4本以上必要です"
        )
    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or not 4 <= max_candidates <= MAX_OWNED_RECOMMENDATION_CANDIDATES
    ):
        raise ValueError(
            f"max_candidates must be an integer from 4 to {MAX_OWNED_RECOMMENDATION_CANDIDATES}"
        )
    state_count = coerce_palette_state_count(palette_state_count)
    enabled = _coerce_enabled_for_state_count(enabled_states, state_count)
    if not isinstance(include_mixed_states, (bool, np.bool_)):
        raise ValueError("include_mixed_states must be a boolean")
    include_mixed_states = bool(include_mixed_states)
    if not include_mixed_states:
        # Flat mode proposes four printable spools, so all four physical slots
        # participate in its score regardless of stale per-state switches from
        # a preceding Full Spectrum session.  Mixed states remain unavailable.
        enabled = tuple(index < 4 for index in range(len(enabled)))
    initial = tuple(_DEFAULT_PRIMARY_RATIOS if initial_ratios_b is None else initial_ratios_b)
    secondary = tuple(
        _DEFAULT_SECONDARY_RATIOS if secondary_ratios_b is None else secondary_ratios_b
    )

    representative_set = build_representative_colors(
        object_rgb,
        object_area_weights,
        reference_rgb=reference_rgb,
        reference_weights=reference_weights,
        reference_confidence=reference_confidence,
    )
    shortlist_rgb = np.asarray(
        [representative.rgb8 for representative in representative_set.colors],
        dtype=np.uint8,
    )
    shortlist_weights = np.asarray(
        [representative.weight_fraction for representative in representative_set.colors],
        dtype=np.float64,
    )
    search_products = _shortlist_owned_products(
        unique_products,
        shortlist_rgb,
        shortlist_weights,
        max_candidates,
        required_physical_rgb,
    )
    catalog = tuple(
        FilamentCandidate(
            id=product.product_id,
            label=product.label,
            hex_color=product.matched_hex,
            category=CATEGORY_PRIMARY,
            auto_allowed=True,
            in_stock=True,
            material=product.material,
        )
        for product in search_products
    )
    selection = recommend_basic_filaments(
        object_rgb,
        object_area_weights,
        reference_rgb=reference_rgb,
        reference_weights=reference_weights,
        reference_confidence=reference_confidence,
        catalog=catalog,
        in_stock_only=False,
        palette_state_count=state_count,
        include_mixed_states=include_mixed_states,
        alternative_count=OWNED_REFINEMENT_SHORTLIST_SIZE - 1,
        max_candidates=len(catalog),
        required_physical_rgb=required_physical_rgb,
    )
    # A larger palette is a strict superset of the first sixteen states, but
    # its approximate combination ranking can otherwise discard a good
    # 16-state physical set (or choose a worse F1..F4 order) before the exact
    # ratio refinement runs.  Keep the bounded 16-state proposal family as a
    # quality guard and re-evaluate every member with the requested state
    # count.  Only the final fixed-size refinement shortlist is optimised, so
    # this does not increase the expensive optimiser ceiling.
    legacy_selection = None
    if include_mixed_states and state_count > DEFAULT_PALETTE_STATE_COUNT:
        legacy_selection = recommend_basic_filaments(
            object_rgb,
            object_area_weights,
            reference_rgb=reference_rgb,
            reference_weights=reference_weights,
            reference_confidence=reference_confidence,
            catalog=catalog,
            in_stock_only=False,
            palette_state_count=DEFAULT_PALETTE_STATE_COUNT,
            include_mixed_states=True,
            alternative_count=OWNED_REFINEMENT_SHORTLIST_SIZE - 1,
            max_candidates=len(catalog),
            required_physical_rgb=required_physical_rgb,
        )
    product_lookup = {product.product_id: product for product in unique_products}
    representative_rgb = np.asarray(
        [representative.rgb8 for representative in selection.representatives],
        dtype=np.uint8,
    )
    representative_weights = np.asarray(
        [representative.weight_fraction for representative in selection.representatives],
        dtype=np.float64,
    )
    optimization_pink_mask: np.ndarray | None = None
    optimization_unrestricted_mask: np.ndarray | None = None
    if pink_protection_mask is not None:
        (
            representative_rgb,
            representative_weights,
            optimization_pink_mask,
            optimization_unrestricted_mask,
        ) = _masked_representative_samples(
            object_rgb,
            object_area_weights,
            pink_protection_mask,
            reference_rgb=reference_rgb,
            reference_weights=reference_weights,
            object_weight_fraction=representative_set.object_weight_fraction,
            reference_weight_fraction=representative_set.reference_weight_fraction,
        )
    proposal_by_set: dict[tuple[str, ...], PaletteProposal] = {}
    for proposal_source in (selection, legacy_selection):
        if proposal_source is None:
            continue
        for proposal in (proposal_source, *proposal_source.alternatives):
            set_key = tuple(sorted(candidate.id for candidate in proposal.candidates))
            proposal_by_set.setdefault(set_key, proposal)
    proposals = tuple(proposal_by_set.values())
    legacy_enabled = _coerce_enabled_for_state_count(
        enabled_states,
        DEFAULT_PALETTE_STATE_COUNT,
    )
    ordered_shortlist: list[
        tuple[float, tuple[str, ...], tuple[FilamentProduct, ...], PaletteProposal]
    ] = []
    ordered_by_ids: dict[
        tuple[str, ...],
        tuple[float, tuple[str, ...], tuple[FilamentProduct, ...], PaletteProposal],
    ] = {}
    legacy_guard_ids: tuple[str, ...] | None = None
    for proposal in proposals:
        proposal_products = tuple(
            product_lookup[candidate.id] for candidate in proposal.candidates
        )
        ordered_products, initial_score = _best_initial_slot_order(
            proposal_products,
            representative_rgb,
            representative_weights,
            state_count=state_count,
            enabled_states=enabled,
            initial_ratios_b=initial,
            secondary_ratios_b=secondary,
            pink_protection_mask=optimization_pink_mask,
            unrestricted_state_mask=optimization_unrestricted_mask,
        )
        ordered_ids = tuple(product.product_id for product in ordered_products)
        ordered_by_ids[ordered_ids] = (
            initial_score,
            ordered_ids,
            ordered_products,
            proposal,
        )
        if legacy_selection is not None:
            legacy_products, _legacy_score = _best_initial_slot_order(
                proposal_products,
                representative_rgb,
                representative_weights,
                state_count=DEFAULT_PALETTE_STATE_COUNT,
                enabled_states=legacy_enabled,
                initial_ratios_b=initial,
                secondary_ratios_b=secondary,
                pink_protection_mask=optimization_pink_mask,
                unrestricted_state_mask=optimization_unrestricted_mask,
            )
            legacy_ids = tuple(product.product_id for product in legacy_products)
            legacy_target_score = _initial_order_score(
                legacy_products,
                representative_rgb,
                representative_weights,
                state_count=state_count,
                enabled_states=enabled,
                initial_ratios_b=initial,
                secondary_ratios_b=secondary,
                pink_protection_mask=optimization_pink_mask,
                unrestricted_state_mask=optimization_unrestricted_mask,
            )
            existing = ordered_by_ids.get(legacy_ids)
            legacy_entry = (
                legacy_target_score,
                legacy_ids,
                legacy_products,
                proposal,
            )
            if existing is None or legacy_entry[:2] < existing[:2]:
                ordered_by_ids[legacy_ids] = legacy_entry
            if tuple(sorted(legacy_ids)) == tuple(
                sorted(candidate.id for candidate in legacy_selection.candidates)
            ):
                legacy_guard_ids = legacy_ids
    ordered_shortlist = list(ordered_by_ids.values())
    ordered_shortlist.sort(key=lambda item: (item[0], item[1]))

    refined: list[
        tuple[
            float,
            float,
            tuple[str, ...],
            tuple[FilamentProduct, ...],
            PaletteProposal,
            GlobalMixOptimizationResult,
        ]
    ] = []

    def refine_for_target(
        entry: tuple[
            float,
            tuple[str, ...],
            tuple[FilamentProduct, ...],
            PaletteProposal,
        ],
        *,
        seed_ratios_b: Sequence[int] = initial,
        seed_secondary_ratios_b: Sequence[int] = secondary,
    ) -> None:
        _initial_score, ordered_ids, ordered_products, proposal = entry
        candidate_optimization = optimize_global_mix_ratios(
            representative_rgb,
            [product.matched_hex for product in ordered_products],
            weights=representative_weights,
            initial_ratios_b=seed_ratios_b,
            secondary_ratios_b=seed_secondary_ratios_b,
            enabled_states=enabled,
            pink_protection_mask=optimization_pink_mask,
            unrestricted_state_mask=optimization_unrestricted_mask,
            histogram_bins_per_channel=32,
            max_passes=max_passes,
            optimize_secondary_ratios=include_mixed_states,
        )
        refined.append(
            (
                float(candidate_optimization.weighted_mean_delta_e76),
                float(candidate_optimization.initial_weighted_mean_delta_e76),
                ordered_ids,
                ordered_products,
                proposal,
                candidate_optimization,
            )
        )

    if legacy_guard_ids is None:
        for entry in ordered_shortlist[:OWNED_RATIO_REFINEMENT_COMBINATIONS]:
            refine_for_target(entry)
    else:
        # Spend two of the same fixed four expensive optimisation slots on a
        # monotonic legacy guard.  First find the 16-state ratios, then seed
        # the requested-state optimiser with them.  Because the requested
        # palette contains every enabled 16-state colour, its starting score
        # cannot be worse than the 16-state final score.
        guard_entry = ordered_by_ids[legacy_guard_ids]
        _guard_score, _guard_ids, guard_products, _guard_proposal = guard_entry
        legacy_optimization = optimize_global_mix_ratios(
            representative_rgb,
            [product.matched_hex for product in guard_products],
            weights=representative_weights,
            initial_ratios_b=initial,
            secondary_ratios_b=secondary,
            enabled_states=legacy_enabled,
            pink_protection_mask=optimization_pink_mask,
            unrestricted_state_mask=optimization_unrestricted_mask,
            histogram_bins_per_channel=32,
            max_passes=max_passes,
            optimize_secondary_ratios=True,
        )
        refine_for_target(
            guard_entry,
            seed_ratios_b=legacy_optimization.mix_ratios_b,
            seed_secondary_ratios_b=(
                legacy_optimization.secondary_mix_ratios_b or secondary
            ),
        )
        remaining_slots = max(0, OWNED_RATIO_REFINEMENT_COMBINATIONS - 2)
        for entry in (
            candidate
            for candidate in ordered_shortlist
            if candidate[1] != legacy_guard_ids
        ):
            if remaining_slots <= 0:
                break
            refine_for_target(entry)
            remaining_slots -= 1
    refined.sort(key=lambda item: (item[0], item[1], item[2]))
    (
        _final_score,
        _before_score,
        _ordered_ids,
        selected_products,
        selected_proposal,
        optimization,
    ) = refined[0]
    optimized_secondary = (
        optimization.secondary_mix_ratios_b
        or tuple(int(value) for value in secondary)
    )
    selected_ids = {product.product_id for product in unique_products}
    ignored_duplicates = tuple(
        product.product_id
        for product in products
        if product.product_id not in selected_ids
    )
    standard_finish = "標準/不透明"
    special_finish_products = tuple(
        product
        for product in selected_products
        if product.finish_class != standard_finish
    )
    warnings: list[str] = []
    if ignored_duplicates:
        warnings.append(
            "同じHEX色の手持ちフィラメントは自動構成で各色1本にまとめました"
        )
    if len(unique_products) > max_candidates:
        warnings.append(
            f"手持ち{len(unique_products)}色から計算量を抑えるため"
            f"モデルに近い{max_candidates}色を候補に絞りました"
        )
    if special_finish_products:
        warnings.append(
            "マット・メタリック・透明・繊維入り等の特殊質感は、画面上の混色予測と"
            "実物がずれる可能性があります: "
            + ", ".join(product.label for product in special_finish_products)
        )
    return OwnedFilamentRecommendation(
        candidates=selected_products,
        palette_state_count=state_count,
        palette_hex=tuple(optimization.palette_hex[:state_count]),
        mix_ratios_b=tuple(optimization.mix_ratios_b),
        secondary_mix_ratios_b=tuple(optimized_secondary),
        initial_mix_ratios_b=tuple(optimization.initial_mix_ratios_b),
        initial_secondary_mix_ratios_b=(
            optimization.initial_secondary_mix_ratios_b
            or tuple(int(value) for value in secondary)
        ),
        mean_delta_e76=float(optimization.weighted_mean_delta_e76),
        before_mean_delta_e76=float(
            optimization.initial_weighted_mean_delta_e76
        ),
        improvement_delta_e76=float(optimization.improvement_delta_e76),
        improvement_percent=float(optimization.improvement_percent),
        confidence=float(selected_proposal.confidence),
        candidate_pool_size=int(selection.candidate_pool_size),
        evaluated_combinations=int(selection.evaluated_combinations),
        ignored_duplicate_color_product_ids=ignored_duplicates,
        special_finish_products=special_finish_products,
        warnings=tuple(warnings),
        refined_combination_count=len(refined),
        selection=selected_proposal,
        optimization=optimization,
    )


__all__ = [
    "MAX_OWNED_RECOMMENDATION_CANDIDATES",
    "OWNED_FILAMENT_INVENTORY_FILENAME",
    "OWNED_FILAMENT_INVENTORY_SCHEMA_VERSION",
    "OwnedFilamentInventory",
    "OwnedFilamentInventoryError",
    "OwnedFilamentRecommendation",
    "OwnedFilamentSelectionError",
    "load_owned_filament_inventory",
    "recommend_from_owned_filaments",
    "resolve_owned_filament_inventory_path",
    "save_owned_filament_inventory",
]
