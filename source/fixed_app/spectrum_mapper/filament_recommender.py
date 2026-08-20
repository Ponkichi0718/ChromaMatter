from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Sequence

import numpy as np

from .mixer import (
    DEFAULT_PALETTE_STATE_COUNT,
    PAIR_INDICES,
    coerce_palette_state_count,
    hex_to_rgb8,
    normalize_hex,
    palette_mix_specs,
    rgb8_to_hex,
)
from .filament_materials import (
    DEFAULT_FILAMENT_MATERIAL,
    normalize_filament_material,
)


CATEGORY_NEUTRAL = "neutral"
CATEGORY_PRIMARY = "primary"
CATEGORY_SKIN = "skin"
CATEGORY_INTERMEDIATE = "intermediate"
ALLOWED_CATEGORIES = frozenset(
    {
        CATEGORY_NEUTRAL,
        CATEGORY_PRIMARY,
        CATEGORY_SKIN,
        CATEGORY_INTERMEDIATE,
    }
)

# The first two interior ramps remain the stable 4 + 6 + 6 compatibility
# layout.  When 24/32 states are requested, the recommender appends the exact
# quarter/midpoint recipes defined by ``mixer.palette_mix_specs`` without
# renumbering those first sixteen states.
DEFAULT_PRIMARY_RATIO_B_PERCENT = 33
DEFAULT_SECONDARY_RATIO_B_PERCENT = 67
DEFAULT_REFERENCE_FRACTION = 0.30
DEFAULT_COVERAGE_DELTA_E76 = 12.0
DEFAULT_HISTOGRAM_BINS_PER_CHANNEL = 16
DEFAULT_MAX_REPRESENTATIVE_COLORS = 256
DEFAULT_MAX_CANDIDATES = 18

# Product libraries sometimes classify a changing/multi-colour spool as a
# normal opaque filament. Such products remain useful in the manual product
# browser, but one HEX value cannot represent them in the automatic four-basic
# colour solver.
_NON_CONSTANT_COLORWAY_RE = re.compile(
    r"(?:"
    r"\bmulti[\s_-]*colou?rs?\b|"
    r"\b(?:bi|tri|dual|two|triple|three|four|\d+)"
    r"[\s_-]*(?:tri[\s_-]*)?colou?rs?\b|"
    r"\brainbow\b|\bgradient\b|\bchameleon\b|"
    r"\bcolou?r[\s_-]*(?:change(?:s|d|ing)?|shift(?:s|ed|ing)?)\b|"
    r"レインボー|グラデーション|カメレオン|多色|"
    r"(?:2|3|二|三)色"
    r")",
    re.IGNORECASE,
)
_MAGIC_MULTICOLOUR_NAME_RE = re.compile(r"\S+\s*\+\s*\S+")

# Ranking is still dominated by the area-weighted mean.  The tail and coverage
# terms prevent a small but important accent family from disappearing merely
# because a large neutral surface has a very good fit.
P90_SCORE_WEIGHT = 0.20
UNCOVERED_SCORE_PENALTY = 8.0


@dataclass(frozen=True, slots=True)
class FilamentCandidate:
    """One real, selectable basic filament.

    ``auto_allowed`` is an explicit catalog decision.  In addition, entries in
    the ``intermediate`` category are never selected automatically even if a
    malformed external catalog sets ``auto_allowed`` to true.  They remain
    useful for a future explicit/manual override UI.
    """

    id: str
    label: str
    hex_color: str
    category: str
    auto_allowed: bool = True
    in_stock: bool = True
    material: str = DEFAULT_FILAMENT_MATERIAL
    brand: str = ""
    series: str = ""
    color_name: str = ""
    finish_class: str = ""
    source_kind: str = ""
    source_url: str | None = None
    record_id: str | None = None
    measurement_id: str | None = None

    def __post_init__(self) -> None:
        candidate_id = str(self.id).strip()
        label = str(self.label).strip()
        category = str(self.category).strip().lower()
        if not candidate_id:
            raise ValueError("filament candidate id must not be empty")
        if not label:
            raise ValueError(f"filament candidate {candidate_id!r} needs a label")
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"filament candidate {candidate_id!r} has unknown category {category!r}"
            )
        object.__setattr__(self, "id", candidate_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "hex_color", normalize_hex(self.hex_color))
        object.__setattr__(self, "auto_allowed", bool(self.auto_allowed))
        object.__setattr__(self, "in_stock", bool(self.in_stock))
        object.__setattr__(
            self,
            "material",
            normalize_filament_material(
                self.material, default=DEFAULT_FILAMENT_MATERIAL
            ),
        )

    @property
    def product_id(self) -> str:
        return self.id

    @property
    def matched_hex(self) -> str:
        return self.hex_color

    @property
    def rgb8(self) -> tuple[int, int, int]:
        return tuple(int(channel) for channel in hex_to_rgb8(self.hex_color))


# These are generic starting points rather than claims about a specific brand.
# Projects should snapshot the chosen HEX values, and users can calibrate them
# to the actual spool.  Saturated hue families are treated as basic colours;
# muted/middle colours remain available for manual selection only.
DEFAULT_CURATED_CATALOG: tuple[FilamentCandidate, ...] = (
    FilamentCandidate("neutral_black", "ブラック", "#111111", CATEGORY_NEUTRAL),
    FilamentCandidate("neutral_white", "ホワイト", "#F5F5F5", CATEGORY_NEUTRAL),
    FilamentCandidate("neutral_gray", "グレー", "#7F8388", CATEGORY_NEUTRAL),
    FilamentCandidate("neutral_silver", "シルバー", "#C0C3C7", CATEGORY_NEUTRAL),
    FilamentCandidate("primary_red", "レッド", "#E32636", CATEGORY_PRIMARY),
    FilamentCandidate("primary_orange", "オレンジ", "#F36C21", CATEGORY_PRIMARY),
    FilamentCandidate("primary_yellow", "イエロー", "#F4D21F", CATEGORY_PRIMARY),
    FilamentCandidate("primary_green", "グリーン", "#159447", CATEGORY_PRIMARY),
    FilamentCandidate("primary_cyan", "シアン", "#00A6C7", CATEGORY_PRIMARY),
    FilamentCandidate("primary_blue", "ブルー", "#2453C7", CATEGORY_PRIMARY),
    FilamentCandidate("primary_violet", "バイオレット", "#6F38A8", CATEGORY_PRIMARY),
    FilamentCandidate("primary_magenta", "マゼンタ", "#D52078", CATEGORY_PRIMARY),
    FilamentCandidate("skin_light", "ライトスキン", "#F2C6A0", CATEGORY_SKIN),
    FilamentCandidate("skin_medium", "ミディアムスキン", "#C98B63", CATEGORY_SKIN),
    FilamentCandidate("skin_deep", "ディープスキン", "#7A4A32", CATEGORY_SKIN),
    FilamentCandidate(
        "intermediate_beige",
        "ベージュ（手動候補）",
        "#C7A78F",
        CATEGORY_INTERMEDIATE,
        auto_allowed=False,
    ),
    FilamentCandidate(
        "intermediate_dusty_rose",
        "ダスティローズ（手動候補）",
        "#B77A8B",
        CATEGORY_INTERMEDIATE,
        auto_allowed=False,
    ),
    FilamentCandidate(
        "intermediate_burgundy",
        "バーガンディ（手動候補）",
        "#6E2430",
        CATEGORY_INTERMEDIATE,
        auto_allowed=False,
    ),
)


@dataclass(frozen=True, slots=True)
class RepresentativeColor:
    rgb8: tuple[int, int, int]
    weight_fraction: float

    @property
    def hex_color(self) -> str:
        return rgb8_to_hex(self.rgb8)


@dataclass(frozen=True, slots=True)
class RepresentativeColorSet:
    colors: tuple[RepresentativeColor, ...]
    object_weight_fraction: float
    reference_weight_fraction: float
    object_input_weight: float
    reference_input_weight: float


@dataclass(frozen=True, slots=True)
class PaletteStateUsage:
    state_index: int
    component_ids: tuple[str, ...]
    ratio_b_percent: int | None
    weight_fraction: float

    @property
    def state_number(self) -> int:
        return self.state_index + 1


@dataclass(frozen=True, slots=True)
class PaletteProposal:
    candidates: tuple[FilamentCandidate, ...]
    palette_hex: tuple[str, ...]
    primary_ratio_b_percent: int
    secondary_ratio_b_percent: int
    score: float
    mean_delta_e76: float
    p90_delta_e76: float
    coverage_fraction: float
    confidence: float
    usage: tuple[PaletteStateUsage, ...]
    base_usage_fractions: tuple[float, ...]

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate.id for candidate in self.candidates)

    @property
    def physical_hex(self) -> tuple[str, ...]:
        return tuple(candidate.hex_color for candidate in self.candidates)


@dataclass(frozen=True, slots=True)
class FilamentRecommendation(PaletteProposal):
    alternatives: tuple[PaletteProposal, ...]
    representatives: tuple[RepresentativeColor, ...]
    object_weight_fraction: float
    reference_weight_fraction: float
    candidate_pool_size: int
    evaluated_combinations: int


@dataclass(frozen=True, slots=True)
class _PaletteEvaluation:
    candidates: tuple[FilamentCandidate, ...]
    palette_rgb8: np.ndarray
    assignments: np.ndarray
    usage_fractions: np.ndarray
    base_usage_fractions: np.ndarray
    score: float
    mean_delta_e76: float
    p90_delta_e76: float
    coverage_fraction: float
    confidence: float


def _is_constant_colorway(candidate: FilamentCandidate) -> bool:
    text = " ".join(
        (
            candidate.label,
            candidate.brand,
            candidate.series,
            candidate.color_name,
        )
    )
    if _NON_CONSTANT_COLORWAY_RE.search(text):
        return False
    # "Magic" alone is not sufficient: eSUN's Dark Twinkling PLA Magic has
    # ordinary single-colour Blue/Gold/Green/Purple entries. A plus-separated
    # colour name, however, explicitly identifies the multi-colour variants.
    return not (
        "magic" in text.casefold()
        and _MAGIC_MULTICOLOUR_NAME_RE.search(candidate.color_name)
    )


def _coerce_rgb_samples(
    value: Sequence[Sequence[float]] | np.ndarray,
    name: str,
) -> np.ndarray:
    try:
        raw = np.asarray(value)
        result = raw.astype(np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an N x 3 RGB array") from exc
    if result.ndim == 1 and result.shape == (3,):
        result = result.reshape(1, 3)
    if result.ndim != 2 or result.shape[1] != 3 or len(result) == 0:
        raise ValueError(f"{name} must be a non-empty N x 3 RGB array")
    if not np.all(np.isfinite(result)) or np.any(result < 0.0):
        raise ValueError(f"{name} contains a negative, NaN, or infinite value")
    if np.issubdtype(raw.dtype, np.floating) and float(result.max()) <= 1.0:
        result *= 255.0
    if np.any(result > 255.0):
        raise ValueError(f"{name} values must be in 0..1 or 0..255")
    return result


def _coerce_weights(
    value: Sequence[float] | np.ndarray | None,
    count: int,
    name: str,
) -> np.ndarray:
    if value is None:
        result = np.ones(count, dtype=np.float64)
    else:
        try:
            result = np.asarray(value, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a numeric vector") from exc
    if result.shape != (count,):
        raise ValueError(f"{name} must contain one value per RGB sample")
    if not np.all(np.isfinite(result)) or np.any(result < 0.0):
        raise ValueError(f"{name} contains a negative, NaN, or infinite value")
    if float(result.sum()) <= 0.0:
        raise ValueError(f"{name} must have positive total weight")
    return result


def _rgb255_to_lab(rgb255: np.ndarray) -> np.ndarray:
    """Use the engine's exact sRGB/D65 conversion used by colour assignment."""

    # Lazy import prevents a circular import when the engine later wires this
    # pure recommender into the application workflow.
    from .engine import srgb_to_lab

    return srgb_to_lab(np.asarray(rgb255, dtype=np.float64).reshape(-1, 3) / 255.0)


def _weighted_rgb_histogram(
    rgb255: np.ndarray,
    weights: np.ndarray,
    bins_per_channel: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    quantized = np.floor(rgb255 * (bins_per_channel / 256.0)).astype(np.int64)
    np.clip(quantized, 0, bins_per_channel - 1, out=quantized)
    keys = (
        quantized[:, 0] * bins_per_channel * bins_per_channel
        + quantized[:, 1] * bins_per_channel
        + quantized[:, 2]
    )
    unique_keys, inverse = np.unique(keys, return_inverse=True)
    histogram_weights = np.bincount(inverse, weights=weights).astype(
        np.float64, copy=False
    )
    keep = histogram_weights > 0.0
    histogram_weights = histogram_weights[keep]
    unique_keys = unique_keys[keep]
    weighted_sums = np.empty((len(histogram_weights), 3), dtype=np.float64)
    for channel in range(3):
        sums = np.bincount(inverse, weights=weights * rgb255[:, channel])
        weighted_sums[:, channel] = sums[keep]
    colors = weighted_sums / histogram_weights[:, None]
    return colors, histogram_weights, unique_keys


def _reduce_representatives(
    colors: np.ndarray,
    weights: np.ndarray,
    keys: np.ndarray,
    maximum: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(colors) <= maximum:
        return colors, weights, keys

    # Highest-area bins are anchors.  Lesser bins are merged into their nearest
    # anchor instead of being discarded, so their complete area is retained.
    ranked = np.lexsort((keys, -weights))
    kept_indices = ranked[:maximum]
    dropped_indices = ranked[maximum:]
    kept_colors = colors[kept_indices].copy()
    kept_weights = weights[kept_indices].copy()
    kept_sums = kept_colors * kept_weights[:, None]
    kept_keys = keys[kept_indices].copy()

    kept_lab = _rgb255_to_lab(kept_colors)
    dropped_lab = _rgb255_to_lab(colors[dropped_indices])
    for start in range(0, len(dropped_indices), 2_048):
        stop = min(len(dropped_indices), start + 2_048)
        delta = dropped_lab[start:stop, None, :] - kept_lab[None, :, :]
        nearest = np.argmin(np.sum(delta * delta, axis=2), axis=1)
        source_indices = dropped_indices[start:stop]
        np.add.at(kept_weights, nearest, weights[source_indices])
        for channel in range(3):
            np.add.at(
                kept_sums[:, channel],
                nearest,
                colors[source_indices, channel] * weights[source_indices],
            )
    kept_colors = kept_sums / kept_weights[:, None]
    return kept_colors, kept_weights, kept_keys


def build_representative_colors(
    object_rgb: Sequence[Sequence[float]] | np.ndarray,
    object_area_weights: Sequence[float] | np.ndarray | None = None,
    *,
    reference_rgb: Sequence[Sequence[float]] | np.ndarray | None = None,
    reference_weights: Sequence[float] | np.ndarray | None = None,
    reference_confidence: float = 1.0,
    maximum_reference_fraction: float = DEFAULT_REFERENCE_FRACTION,
    bins_per_channel: int = DEFAULT_HISTOGRAM_BINS_PER_CHANNEL,
    max_colors: int = DEFAULT_MAX_REPRESENTATIVE_COLORS,
) -> RepresentativeColorSet:
    """Build a bounded, area-weighted colour distribution.

    OBJ face colours are the primary 3D signal.  Reference pixels can account
    for at most 30% by default, and their contribution is multiplied by the
    caller's part-mask/alignment confidence.  Each source is normalized before
    fusion so image resolution cannot overwhelm physical surface area.
    """

    if not isinstance(bins_per_channel, int) or isinstance(
        bins_per_channel, bool
    ) or not 2 <= bins_per_channel <= 64:
        raise ValueError("bins_per_channel must be an integer from 2 to 64")
    if not isinstance(max_colors, int) or isinstance(max_colors, bool) or max_colors < 1:
        raise ValueError("max_colors must be a positive integer")
    if not math.isfinite(float(reference_confidence)) or not 0.0 <= float(
        reference_confidence
    ) <= 1.0:
        raise ValueError("reference_confidence must be in 0..1")
    if not math.isfinite(float(maximum_reference_fraction)) or not 0.0 <= float(
        maximum_reference_fraction
    ) <= 1.0:
        raise ValueError("maximum_reference_fraction must be in 0..1")

    object_samples = _coerce_rgb_samples(object_rgb, "object_rgb")
    object_weights = _coerce_weights(
        object_area_weights, len(object_samples), "object_area_weights"
    )
    object_input_weight = float(object_weights.sum())

    reference_input_weight = 0.0
    reference_fraction = 0.0
    if reference_rgb is not None:
        reference_samples = _coerce_rgb_samples(reference_rgb, "reference_rgb")
        reference_sample_weights = _coerce_weights(
            reference_weights, len(reference_samples), "reference_weights"
        )
        reference_input_weight = float(reference_sample_weights.sum())
        reference_fraction = float(maximum_reference_fraction) * float(
            reference_confidence
        )
        object_fraction = 1.0 - reference_fraction
        fused_rgb = np.vstack((object_samples, reference_samples))
        fused_weights = np.concatenate(
            (
                object_weights / object_input_weight * object_fraction,
                reference_sample_weights
                / reference_input_weight
                * reference_fraction,
            )
        )
    else:
        if reference_weights is not None:
            raise ValueError("reference_weights requires reference_rgb")
        object_fraction = 1.0
        fused_rgb = object_samples
        fused_weights = object_weights / object_input_weight

    colors, weights, keys = _weighted_rgb_histogram(
        fused_rgb, fused_weights, bins_per_channel
    )
    colors, weights, keys = _reduce_representatives(
        colors, weights, keys, max_colors
    )
    weights /= float(weights.sum())

    # Stable weight-first order makes serialization and tests independent of
    # np.unique's internal ordering details.
    ranked = np.lexsort((keys, -weights))
    colors = colors[ranked]
    weights = weights[ranked]
    representatives = tuple(
        RepresentativeColor(
            rgb8=tuple(
                int(channel)
                for channel in np.clip(np.rint(color), 0, 255).astype(np.uint8)
            ),
            weight_fraction=float(weight),
        )
        for color, weight in zip(colors, weights, strict=True)
    )
    return RepresentativeColorSet(
        colors=representatives,
        object_weight_fraction=float(object_fraction),
        reference_weight_fraction=float(reference_fraction),
        object_input_weight=object_input_weight,
        reference_input_weight=reference_input_weight,
    )


def _weighted_quantile(
    values: np.ndarray,
    weights: np.ndarray,
    quantile: float,
) -> float:
    order = np.argsort(values, kind="stable")
    ordered_values = values[order]
    cumulative = np.cumsum(weights[order])
    threshold = float(quantile) * float(cumulative[-1])
    index = int(np.searchsorted(cumulative, threshold, side="left"))
    return float(ordered_values[min(index, len(ordered_values) - 1)])


def _eligible_candidates(
    catalog: Sequence[FilamentCandidate],
    *,
    in_stock_only: bool,
) -> list[FilamentCandidate]:
    candidates = list(catalog)
    if not all(isinstance(candidate, FilamentCandidate) for candidate in candidates):
        raise TypeError("catalog must contain FilamentCandidate values")
    identifiers = [candidate.id for candidate in candidates]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("filament candidate ids must be unique")
    eligible = [
        candidate
        for candidate in candidates
        if candidate.auto_allowed
        and candidate.category != CATEGORY_INTERMEDIATE
        and (candidate.in_stock or not in_stock_only)
    ]
    eligible.sort(key=lambda candidate: (candidate.id.casefold(), candidate.id))
    if len(eligible) < 4:
        raise ValueError("at least four automatic basic filament candidates are required")
    return eligible


def _shortlist_candidates(
    candidates: list[FilamentCandidate],
    representative_lab: np.ndarray,
    representative_weights: np.ndarray,
    maximum: int | None,
) -> list[FilamentCandidate]:
    if maximum is None:
        return candidates
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 4:
        raise ValueError("max_candidates must be None or an integer of at least four")
    if len(candidates) <= maximum:
        return candidates
    candidate_rgb = np.asarray([candidate.rgb8 for candidate in candidates])
    candidate_lab = _rgb255_to_lab(candidate_rgb)
    delta = representative_lab[:, None, :] - candidate_lab[None, :, :]
    distances = np.sqrt(np.sum(delta * delta, axis=2))
    individual_scores = representative_weights @ distances
    ranked = sorted(
        range(len(candidates)),
        key=lambda index: (
            float(individual_scores[index]),
            candidates[index].id.casefold(),
            candidates[index].id,
        ),
    )[:maximum]
    result = [candidates[index] for index in ranked]
    result.sort(key=lambda candidate: (candidate.id.casefold(), candidate.id))
    return result


def map_catalog_to_curated_basics(
    catalog: Sequence[FilamentCandidate],
    *,
    in_stock_only: bool = True,
) -> tuple[FilamentCandidate, ...]:
    """Map one material's product catalog onto the stable basic-colour gamut.

    The original recommender evaluated a small curated set containing dark and
    light neutrals, saturated hues, and skin tones. Passing a large product
    database directly to its target-mean shortlist can fill all 18 slots with
    near-duplicate versions of the dominant model colour before the four-colour
    solver runs. This function restores the original semantics while keeping
    real product identity: each curated basic anchor is replaced by the nearest
    distinct, constant-colour product from the requested material.

    Colour-changing/multi-colour products are intentionally excluded only from
    automatic selection. They remain present in the source catalog for manual
    matching.
    """

    candidates = _eligible_candidates(catalog, in_stock_only=in_stock_only)
    materials = {candidate.material for candidate in candidates}
    if len(materials) != 1:
        raise ValueError("automatic basic filament catalog must use one material")

    constant_candidates = [
        candidate
        for candidate in candidates
        if _is_constant_colorway(candidate)
    ]
    unique_hex_count = len({candidate.hex_color for candidate in constant_candidates})
    if unique_hex_count < 4:
        raise ValueError(
            "at least four distinct constant-colour filament candidates are required"
        )

    anchors = tuple(
        candidate
        for candidate in DEFAULT_CURATED_CATALOG
        if candidate.auto_allowed and candidate.category != CATEGORY_INTERMEDIATE
    )
    anchor_lab = _rgb255_to_lab(
        np.asarray([anchor.rgb8 for anchor in anchors], dtype=np.uint8)
    )
    candidate_lab = _rgb255_to_lab(
        np.asarray(
            [candidate.rgb8 for candidate in constant_candidates], dtype=np.uint8
        )
    )
    squared = np.sum(
        (anchor_lab[:, None, :] - candidate_lab[None, :, :]) ** 2,
        axis=2,
    )

    used_ids: set[str] = set()
    used_hex: set[str] = set()
    mapped: list[FilamentCandidate] = []
    for anchor_index, anchor in enumerate(anchors):
        ranked = sorted(
            range(len(constant_candidates)),
            key=lambda index: (
                float(squared[anchor_index, index]),
                constant_candidates[index].id.casefold(),
                constant_candidates[index].id,
            ),
        )
        selected = next(
            (
                constant_candidates[index]
                for index in ranked
                if constant_candidates[index].id not in used_ids
                and constant_candidates[index].hex_color not in used_hex
            ),
            None,
        )
        if selected is None:
            continue
        used_ids.add(selected.id)
        used_hex.add(selected.hex_color)
        mapped.append(replace(selected, category=anchor.category))

    if len(mapped) < 4:
        raise ValueError("at least four distinct basic filament candidates are required")
    return tuple(mapped)


def _precompute_pair_mixes(
    candidates: Sequence[FilamentCandidate],
    mix_specs: Sequence[tuple[int, int, int]],
) -> dict[tuple[str, str, int], np.ndarray]:
    # ``spectrum_mapper_hotfix`` installs Orca's printable layer-cadence
    # mixer after this module can already have been imported.  Resolve the
    # function from the live module so shortlist scoring and final ratio
    # refinement never depend on import order or use different mix models.
    from . import mixer as runtime_mixer

    result: dict[tuple[str, str, int], np.ndarray] = {}
    ratios = tuple(sorted({int(spec[2]) for spec in mix_specs}))
    for first, second in combinations(candidates, 2):
        first_rgb = np.asarray(first.rgb8, dtype=np.uint8)
        second_rgb = np.asarray(second.rgb8, dtype=np.uint8)
        for ratio_b in ratios:
            result[(first.id, second.id, ratio_b)] = runtime_mixer.mix_rgb8(
                first_rgb, second_rgb, ratio_b / 100.0
            )
    return result


def _palette_for_candidates(
    candidates: tuple[FilamentCandidate, ...],
    pair_mixes: dict[tuple[str, str, int], np.ndarray],
    mix_specs: Sequence[tuple[int, int, int]],
) -> np.ndarray:
    physical = [np.asarray(candidate.rgb8, dtype=np.uint8) for candidate in candidates]
    mixed = [
        pair_mixes[(candidates[left].id, candidates[right].id, int(ratio_b))]
        for left, right, ratio_b in mix_specs
    ]
    return np.asarray(physical + mixed, dtype=np.uint8)


def _base_usage(
    state_usage: np.ndarray,
    mix_specs: Sequence[tuple[int, int, int]],
) -> np.ndarray:
    result = np.asarray(state_usage[:4], dtype=np.float64).copy()
    for mixed_offset, (left, right, ratio_b_percent) in enumerate(mix_specs):
        ratio_b = ratio_b_percent / 100.0
        fraction = float(state_usage[4 + mixed_offset])
        result[left] += fraction * (1.0 - ratio_b)
        result[right] += fraction * ratio_b
    total = float(result.sum())
    if total > 0.0:
        result /= total
    return result


def _confidence(mean_delta_e76: float, p90_delta_e76: float, coverage: float) -> float:
    value = (
        0.50 * coverage
        + 0.30 * math.exp(-mean_delta_e76 / 18.0)
        + 0.20 * math.exp(-p90_delta_e76 / 30.0)
    )
    return float(max(0.0, min(1.0, value)))


def _evaluate_palette(
    candidates: tuple[FilamentCandidate, ...],
    palette_rgb8: np.ndarray,
    representative_lab: np.ndarray,
    representative_weights: np.ndarray,
    coverage_delta_e76: float,
    mix_specs: Sequence[tuple[int, int, int]],
) -> _PaletteEvaluation:
    palette_lab = _rgb255_to_lab(palette_rgb8)
    delta = representative_lab[:, None, :] - palette_lab[None, :, :]
    squared = np.sum(delta * delta, axis=2)
    assignments = np.argmin(squared, axis=1)
    distances = np.sqrt(squared[np.arange(len(assignments)), assignments])
    mean_delta_e76 = float(np.dot(representative_weights, distances))
    p90_delta_e76 = _weighted_quantile(distances, representative_weights, 0.90)
    coverage_fraction = float(
        representative_weights[distances <= coverage_delta_e76].sum()
    )
    usage = np.bincount(
        assignments,
        weights=representative_weights,
        minlength=len(palette_rgb8),
    ).astype(np.float64, copy=False)
    usage /= max(float(usage.sum()), 1e-12)
    base_usage = _base_usage(usage, mix_specs)
    score = (
        mean_delta_e76
        + P90_SCORE_WEIGHT * p90_delta_e76
        + UNCOVERED_SCORE_PENALTY * (1.0 - coverage_fraction)
    )
    return _PaletteEvaluation(
        candidates=candidates,
        palette_rgb8=palette_rgb8,
        assignments=assignments,
        usage_fractions=usage,
        base_usage_fractions=base_usage,
        score=float(score),
        mean_delta_e76=mean_delta_e76,
        p90_delta_e76=p90_delta_e76,
        coverage_fraction=coverage_fraction,
        confidence=_confidence(
            mean_delta_e76, p90_delta_e76, coverage_fraction
        ),
    )


def _proposal_from_evaluation(
    evaluation: _PaletteEvaluation,
    primary_ratio_b_percent: int,
    secondary_ratio_b_percent: int,
    mix_specs: Sequence[tuple[int, int, int]],
) -> PaletteProposal:
    usage: list[PaletteStateUsage] = []
    for state_index, fraction in enumerate(evaluation.usage_fractions):
        if state_index < 4:
            component_ids = (evaluation.candidates[state_index].id,)
            ratio_b = None
        else:
            left, right, ratio_b = mix_specs[state_index - 4]
            component_ids = (
                evaluation.candidates[left].id,
                evaluation.candidates[right].id,
            )
        usage.append(
            PaletteStateUsage(
                state_index=state_index,
                component_ids=component_ids,
                ratio_b_percent=ratio_b,
                weight_fraction=float(fraction),
            )
        )
    return PaletteProposal(
        candidates=evaluation.candidates,
        palette_hex=tuple(rgb8_to_hex(rgb) for rgb in evaluation.palette_rgb8),
        primary_ratio_b_percent=primary_ratio_b_percent,
        secondary_ratio_b_percent=secondary_ratio_b_percent,
        score=evaluation.score,
        mean_delta_e76=evaluation.mean_delta_e76,
        p90_delta_e76=evaluation.p90_delta_e76,
        coverage_fraction=evaluation.coverage_fraction,
        confidence=evaluation.confidence,
        usage=tuple(usage),
        base_usage_fractions=tuple(
            float(value) for value in evaluation.base_usage_fractions
        ),
    )


def recommend_basic_filaments(
    object_rgb: Sequence[Sequence[float]] | np.ndarray,
    object_area_weights: Sequence[float] | np.ndarray | None = None,
    *,
    reference_rgb: Sequence[Sequence[float]] | np.ndarray | None = None,
    reference_weights: Sequence[float] | np.ndarray | None = None,
    reference_confidence: float = 1.0,
    catalog: Sequence[FilamentCandidate] = DEFAULT_CURATED_CATALOG,
    in_stock_only: bool = True,
    primary_ratio_b_percent: int = DEFAULT_PRIMARY_RATIO_B_PERCENT,
    secondary_ratio_b_percent: int = DEFAULT_SECONDARY_RATIO_B_PERCENT,
    palette_state_count: int = DEFAULT_PALETTE_STATE_COUNT,
    coverage_delta_e76: float = DEFAULT_COVERAGE_DELTA_E76,
    alternative_count: int = 2,
    max_candidates: int | None = DEFAULT_MAX_CANDIDATES,
    bins_per_channel: int = DEFAULT_HISTOGRAM_BINS_PER_CHANNEL,
    max_representative_colors: int = DEFAULT_MAX_REPRESENTATIVE_COLORS,
) -> FilamentRecommendation:
    """Recommend four printable basics for one part.

    Every four-colour combination is evaluated deterministically against the
    selected 16/24/32-state Full Spectrum layout used by the application.  Automatic
    selection is constrained to catalogued basic/skin/neutral colours; it never
    invents a convenient middle colour from the target image.
    """

    for name, value in (
        ("primary_ratio_b_percent", primary_ratio_b_percent),
        ("secondary_ratio_b_percent", secondary_ratio_b_percent),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError(f"{name} must be an integer in 0..100")
    if not math.isfinite(float(coverage_delta_e76)) or coverage_delta_e76 <= 0.0:
        raise ValueError("coverage_delta_e76 must be positive")
    if isinstance(alternative_count, bool) or not isinstance(
        alternative_count, int
    ) or alternative_count < 0:
        raise ValueError("alternative_count must be a non-negative integer")
    palette_state_count = coerce_palette_state_count(palette_state_count)

    representative_set = build_representative_colors(
        object_rgb,
        object_area_weights,
        reference_rgb=reference_rgb,
        reference_weights=reference_weights,
        reference_confidence=reference_confidence,
        maximum_reference_fraction=DEFAULT_REFERENCE_FRACTION,
        bins_per_channel=bins_per_channel,
        max_colors=max_representative_colors,
    )
    representative_rgb = np.asarray(
        [representative.rgb8 for representative in representative_set.colors],
        dtype=np.float64,
    )
    representative_weights = np.asarray(
        [representative.weight_fraction for representative in representative_set.colors],
        dtype=np.float64,
    )
    representative_lab = _rgb255_to_lab(representative_rgb)

    candidates = _eligible_candidates(catalog, in_stock_only=in_stock_only)
    candidates = _shortlist_candidates(
        candidates, representative_lab, representative_weights, max_candidates
    )
    mix_specs = palette_mix_specs(
        (primary_ratio_b_percent,) * len(PAIR_INDICES),
        (secondary_ratio_b_percent,) * len(PAIR_INDICES),
    )[: palette_state_count - 4]
    pair_mixes = _precompute_pair_mixes(
        candidates, mix_specs
    )

    evaluations: list[_PaletteEvaluation] = []
    for selected in combinations(candidates, 4):
        palette_rgb8 = _palette_for_candidates(selected, pair_mixes, mix_specs)
        evaluations.append(
            _evaluate_palette(
                selected,
                palette_rgb8,
                representative_lab,
                representative_weights,
                float(coverage_delta_e76),
                mix_specs,
            )
        )
    evaluations.sort(
        key=lambda evaluation: (
            evaluation.score,
            evaluation.mean_delta_e76,
            evaluation.p90_delta_e76,
            -evaluation.coverage_fraction,
            tuple(candidate.id for candidate in evaluation.candidates),
        )
    )
    best = _proposal_from_evaluation(
        evaluations[0],
        primary_ratio_b_percent,
        secondary_ratio_b_percent,
        mix_specs,
    )
    alternatives = tuple(
        _proposal_from_evaluation(
            evaluation,
            primary_ratio_b_percent,
            secondary_ratio_b_percent,
            mix_specs,
        )
        for evaluation in evaluations[1 : 1 + alternative_count]
    )
    return FilamentRecommendation(
        candidates=best.candidates,
        palette_hex=best.palette_hex,
        primary_ratio_b_percent=best.primary_ratio_b_percent,
        secondary_ratio_b_percent=best.secondary_ratio_b_percent,
        score=best.score,
        mean_delta_e76=best.mean_delta_e76,
        p90_delta_e76=best.p90_delta_e76,
        coverage_fraction=best.coverage_fraction,
        confidence=best.confidence,
        usage=best.usage,
        base_usage_fractions=best.base_usage_fractions,
        alternatives=alternatives,
        representatives=representative_set.colors,
        object_weight_fraction=representative_set.object_weight_fraction,
        reference_weight_fraction=representative_set.reference_weight_fraction,
        candidate_pool_size=len(candidates),
        evaluated_combinations=math.comb(len(candidates), 4),
    )


__all__ = [
    "CATEGORY_INTERMEDIATE",
    "CATEGORY_NEUTRAL",
    "CATEGORY_PRIMARY",
    "CATEGORY_SKIN",
    "DEFAULT_CURATED_CATALOG",
    "FilamentCandidate",
    "FilamentRecommendation",
    "PaletteProposal",
    "PaletteStateUsage",
    "RepresentativeColor",
    "RepresentativeColorSet",
    "build_representative_colors",
    "map_catalog_to_curated_basics",
    "recommend_basic_filaments",
]
