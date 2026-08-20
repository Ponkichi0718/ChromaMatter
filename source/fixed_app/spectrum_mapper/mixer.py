from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np


PAIR_INDICES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
PHYSICAL_STATE_COUNT = 4
PRIMARY_MIX_STATE_COUNT = len(PAIR_INDICES)
# The first 16 states are a compatibility contract: four physical colours,
# then the original six primary and six secondary mixes.  New gradient states
# are appended so old project/manual-paint IDs never change meaning.
SECONDARY_MIX_STATE_COUNT = len(PAIR_INDICES)
SUPPORTED_PALETTE_STATE_COUNTS = (16, 24, 32)
DEFAULT_PALETTE_STATE_COUNT = 16
PALETTE_STATE_COUNT = max(SUPPORTED_PALETTE_STATE_COUNTS)
_EXTRA_MIX_SPECS = (
    # 16 -> 24: put a midpoint on every pair, then add two quarter shades to
    # F1/F2.  This gives a useful smooth ramp without changing states 1..16.
    *((left, right, 50) for left, right in PAIR_INDICES),
    (0, 1, 25),
    (0, 1, 75),
    # 24 -> 32: add quarter shades to four more pairs.  The last pair keeps
    # its 33/50/67 ramp so the total remains exactly 32 states.
    *((left, right, ratio) for left, right in PAIR_INDICES[1:5] for ratio in (25, 75)),
)
MIXED_STATE_COUNT = PALETTE_STATE_COUNT - PHYSICAL_STATE_COUNT
MAX_FULL_SPECTRUM_STATES = 64
_PAIR_TO_INDEX = {pair: index for index, pair in enumerate(PAIR_INDICES)}
DEFAULT_PRIMARY_MIX_RATIOS_B = (33,) * len(PAIR_INDICES)
DEFAULT_SECONDARY_MIX_RATIOS_B = (67,) * len(PAIR_INDICES)
_MIX_PAIR_SEQUENCE = PAIR_INDICES + PAIR_INDICES + tuple(
    (left, right) for left, right, _ratio in _EXTRA_MIX_SPECS
)
PINK_PALETTE_STATES = (3,) + tuple(
    PHYSICAL_STATE_COUNT + index
    for index, pair in enumerate(_MIX_PAIR_SEQUENCE)
    if 3 in pair
)
NEUTRAL_PALETTE_STATES = tuple(
    state
    for state in range(PALETTE_STATE_COUNT)
    if state not in PINK_PALETTE_STATES
)


def orca_effective_mix_ratio(requested_ratio_b: float) -> float:
    """Convert a requested B share to Snapmaker Orca's printable cadence.

    Full Spectrum realizes a two-colour ratio as an integer layer cycle: the
    minority receives one layer and the majority count is rounded to the
    nearest positive integer.  Keeping this pure helper in the core module
    lets previews, reports, diagnostics, and the packaged hotfix use exactly
    the same physical-layer interpretation.
    """

    ratio_b = min(1.0, max(0.0, float(requested_ratio_b)))
    if ratio_b <= 0.0 or ratio_b >= 1.0:
        return ratio_b
    percent_b = ratio_b * 100.0
    percent_a = 100.0 - percent_b
    if percent_b >= percent_a:
        major_layers = max(
            1,
            int(np.floor(percent_b / max(1.0, percent_a) + 0.5)),
        )
        layers_a, layers_b = 1, major_layers
    else:
        major_layers = max(
            1,
            int(np.floor(percent_a / max(1.0, percent_b) + 0.5)),
        )
        layers_a, layers_b = major_layers, 1
    return float(layers_b) / float(layers_a + layers_b)


def palette_mix_specs(
    mix_ratios_b: Sequence[int] | None = None,
    secondary_mix_ratios_b: Sequence[int] | None = None,
) -> tuple[tuple[int, int, int], ...]:
    """Return ``(left, right, ratio_b)`` in exact palette/3MF state order."""

    ratios = _coerce_mix_ratios(mix_ratios_b)
    primary = tuple(
        (left, right, int(ratio))
        for (left, right), ratio in zip(PAIR_INDICES, ratios, strict=True)
    )
    secondary_ratios = _coerce_secondary_mix_ratios(secondary_mix_ratios_b)
    secondary = tuple(
        (left, right, int(ratio))
        for (left, right), ratio in zip(
            PAIR_INDICES, secondary_ratios, strict=True
        )
    )
    result = primary + secondary + tuple(_EXTRA_MIX_SPECS)
    if len(result) != MIXED_STATE_COUNT:
        raise AssertionError("unexpected Full Spectrum palette layout")
    return result


def palette_family_display_state_indices(
    palette_state_count: int,
    mix_ratios_b: Sequence[int] | None = None,
    secondary_mix_ratios_b: Sequence[int] | None = None,
) -> tuple[int, ...]:
    """Return zero-based states in the public mixed-palette display order.

    The canonical state IDs remain the project, paint and 3MF compatibility
    contract.  This helper defines only the presentation order shared by the
    Filament Settings strips and the physical comparison-chart bundle:
    F1+F2 through F3+F4, each family running from filament A toward filament
    B, followed by the four unnumbered physical states.

    Keeping this mapping in the mixer core prevents the screen and exported
    chart from independently reimplementing (and eventually drifting from)
    the same family sort.
    """

    state_count = coerce_palette_state_count(palette_state_count)
    specs = palette_mix_specs(mix_ratios_b, secondary_mix_ratios_b)
    mixed: list[int] = []
    for pair in PAIR_INDICES:
        family = [
            (mixed_offset + PHYSICAL_STATE_COUNT, int(ratio_b))
            for mixed_offset, (left, right, ratio_b) in enumerate(specs)
            if (left, right) == pair
            and mixed_offset + PHYSICAL_STATE_COUNT < state_count
        ]
        family.sort(key=lambda item: (item[1], item[0]))
        mixed.extend(state_index for state_index, _ratio_b in family)
    order = tuple(mixed) + tuple(range(PHYSICAL_STATE_COUNT))
    if len(order) != state_count or len(set(order)) != state_count:
        raise AssertionError("unexpected public Full Spectrum palette order")
    return order


def validate_output_mix_ratios_b(
    value: Sequence[int] | None,
) -> tuple[int, ...] | None:
    """Validate the optional full printable recipe override.

    The override contains one B percentage for every mixed state (IDs 5..32)
    in the same stable order as :func:`palette_mix_specs`.  ``None`` is
    intentionally distinct from a list containing the display ratios: it
    keeps legacy projects and exports on the original byte-for-byte path.
    """

    if value is None:
        return None
    try:
        ratios = tuple(value)
    except TypeError as exc:
        raise ValueError(
            f"output_mix_ratios_b must contain {MIXED_STATE_COUNT} integers"
        ) from exc
    if len(ratios) != MIXED_STATE_COUNT or any(
        isinstance(ratio, (bool, np.bool_))
        or not isinstance(ratio, (int, np.integer))
        or not 0 <= int(ratio) <= 100
        for ratio in ratios
    ):
        raise ValueError(
            "output_mix_ratios_b must contain "
            f"{MIXED_STATE_COUNT} integers from 0 to 100"
        )
    return tuple(int(ratio) for ratio in ratios)


def print_palette_mix_specs(
    mix_ratios_b: Sequence[int] | None = None,
    secondary_mix_ratios_b: Sequence[int] | None = None,
    output_mix_ratios_b: Sequence[int] | None = None,
) -> tuple[tuple[int, int, int], ...]:
    """Return physical print recipes without changing display palette data.

    Pair identities and state IDs always come from the display palette.  An
    output override can replace only each mixed state's printable B cadence.
    This separation is what lets calibration weaken black in the 3MF while
    preserving RGB/Lab matching, recolouring, manual paint and ``paint_color``.
    """

    display_specs = palette_mix_specs(
        mix_ratios_b,
        secondary_mix_ratios_b,
    )
    overrides = validate_output_mix_ratios_b(output_mix_ratios_b)
    if overrides is None:
        return display_specs
    return tuple(
        (left, right, int(ratio_b))
        for (left, right, _display_ratio_b), ratio_b in zip(
            display_specs,
            overrides,
            strict=True,
        )
    )


_BLACK_OUTPUT_ANCHORS = (
    (0.0, 0.0),
    (25.0, 5.0),
    (33.0, 10.0),
    (50.0, 14.0),
    (67.0, 20.0),
    (75.0, 25.0),
    (100.0, 25.0),
)


def _calibrated_black_share(target_percent: int) -> int:
    """Map a design black share to the conservative physical black cadence."""

    target = float(min(100, max(0, int(target_percent))))
    for (x0, y0), (x1, y1) in zip(
        _BLACK_OUTPUT_ANCHORS,
        _BLACK_OUTPUT_ANCHORS[1:],
        strict=True,
    ):
        if target <= x1:
            if x1 == x0:
                return int(round(y1))
            t = (target - x0) / (x1 - x0)
            return int(round(y0 + (y1 - y0) * t))
    return 25


def black_output_ratio_preset(
    black_slot: int,
    mix_ratios_b: Sequence[int] | None = None,
    secondary_mix_ratios_b: Sequence[int] | None = None,
) -> list[int]:
    """Build all 28 output ratios for an output-only weak-black preset.

    ``black_slot`` is the zero-based F1..F4 physical slot.  Mixed states that
    do not include it retain their display recipe.  For black-containing
    states, target black shares 25/33/50/67/75 map monotonically to requested
    physical shares 5/10/14/20/25 percent.  Orca's integer layer cadence makes
    the requested 14 percent state effectively about 14.3 percent.  The four
    pure physical states are not represented here and therefore pure black is
    necessarily unchanged.
    """

    if isinstance(black_slot, (bool, np.bool_)) or not isinstance(
        black_slot, (int, np.integer)
    ):
        raise ValueError("black_slot must be an integer from 0 to 3")
    slot = int(black_slot)
    if not 0 <= slot < PHYSICAL_STATE_COUNT:
        raise ValueError("black_slot must be an integer from 0 to 3")

    result: list[int] = []
    for left, right, ratio_b in palette_mix_specs(
        mix_ratios_b,
        secondary_mix_ratios_b,
    ):
        if slot not in (left, right):
            result.append(int(ratio_b))
            continue
        target_black = int(ratio_b) if right == slot else 100 - int(ratio_b)
        physical_black = _calibrated_black_share(target_black)
        output_b = physical_black if right == slot else 100 - physical_black
        result.append(int(output_b))
    return result


def coerce_palette_state_count(value: int | None) -> int:
    """Validate a user-facing Full Spectrum palette size."""

    count = DEFAULT_PALETTE_STATE_COUNT if value is None else int(value)
    if count not in SUPPORTED_PALETTE_STATE_COUNTS:
        raise ValueError(
            f"palette_state_count must be one of {SUPPORTED_PALETTE_STATE_COUNTS}"
        )
    return count


def _coerce_physical_slot(value: int, label: str) -> int:
    """Return one strict zero-based F1..F4 slot index."""

    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, np.integer)
    ):
        raise ValueError(f"{label} must be an integer from 0 to 3")
    slot = int(value)
    if not 0 <= slot < PHYSICAL_STATE_COUNT:
        raise ValueError(f"{label} must be an integer from 0 to 3")
    return slot


def validate_black_free_slots(
    black_slot: int,
    red_slot: int,
    brown_slot: int,
) -> tuple[int, int, int]:
    """Validate the three distinct physical roles used by black-free mode."""

    slots = (
        _coerce_physical_slot(black_slot, "black_free_black_slot"),
        _coerce_physical_slot(red_slot, "black_free_red_slot"),
        _coerce_physical_slot(brown_slot, "black_free_brown_slot"),
    )
    if len(set(slots)) != len(slots):
        raise ValueError("black-free gradient slots must be distinct")
    return slots


def black_containing_mixed_states(
    palette_state_count: int,
    black_slot: int,
) -> tuple[int, ...]:
    """Return zero-based mixed state IDs containing ``black_slot``.

    Pure black is deliberately absent: the black-free gradient policy only
    replaces automatic *mixed* assignments and keeps intentional pure black.
    """

    count = coerce_palette_state_count(palette_state_count)
    slot = _coerce_physical_slot(black_slot, "black_free_black_slot")
    return tuple(
        PHYSICAL_STATE_COUNT + offset
        for offset, (left, right, _ratio_b) in enumerate(palette_mix_specs())
        if PHYSICAL_STATE_COUNT + offset < count and slot in (left, right)
    )


def black_free_replacement_states(
    palette_state_count: int,
    red_slot: int,
    brown_slot: int,
    enabled_states: Sequence[bool] | None = None,
) -> tuple[int, ...]:
    """Return stable red-to-brown replacement states for black-free mode.

    The two physical endpoints are followed by every in-range mixed state for
    that exact pair.  ``enabled_states`` is an optional automatic-candidate
    filter so the engine and GUI can honor the same user switches.
    """

    count = coerce_palette_state_count(palette_state_count)
    red = _coerce_physical_slot(red_slot, "black_free_red_slot")
    brown = _coerce_physical_slot(brown_slot, "black_free_brown_slot")
    if red == brown:
        raise ValueError("black-free red and brown slots must be distinct")
    pair = tuple(sorted((red, brown)))
    states = [red, brown]
    states.extend(
        PHYSICAL_STATE_COUNT + offset
        for offset, (left, right, _ratio_b) in enumerate(palette_mix_specs())
        if PHYSICAL_STATE_COUNT + offset < count and (left, right) == pair
    )
    if enabled_states is None:
        return tuple(states)
    enabled = tuple(enabled_states)
    if len(enabled) != PALETTE_STATE_COUNT or any(
        not isinstance(value, (bool, np.bool_)) for value in enabled
    ):
        raise ValueError(
            f"enabled_states must contain {PALETTE_STATE_COUNT} booleans"
        )
    return tuple(state for state in states if bool(enabled[state]))


def palette_state_names(
    mix_ratios_b: Sequence[int] | None = None,
    secondary_mix_ratios_b: Sequence[int] | None = None,
) -> tuple[str, ...]:
    """Return model-independent F1..F4 labels including every mix ratio."""

    physical = tuple(f"F{index}" for index in range(1, PHYSICAL_STATE_COUNT + 1))
    mixed = tuple(
        f"F{left + 1}+F{right + 1} B{ratio}%"
        for left, right, ratio in palette_mix_specs(
            mix_ratios_b, secondary_mix_ratios_b
        )
    )
    return physical + mixed


@dataclass(frozen=True, slots=True)
class MixRecipeCandidate:
    """目標色に近い、2本の物理フィラメントによる混色候補。

    ``ratio_b_percent`` は色Bの割合で、色Aの割合は
    ``100 - ratio_b_percent`` です。
    """

    color_a_index: int
    color_b_index: int
    color_a_rgb: tuple[int, int, int]
    color_b_rgb: tuple[int, int, int]
    ratio_b_percent: int
    predicted_rgb: tuple[int, int, int]
    predicted_lab: tuple[float, float, float]
    delta_e76: float

    @property
    def ratio_a_percent(self) -> int:
        return 100 - self.ratio_b_percent

    @property
    def predicted_hex(self) -> str:
        return rgb8_to_hex(self.predicted_rgb)


@dataclass(frozen=True, slots=True)
class GlobalMixOptimizationResult:
    """モデル全体に対して求めた6組の混色比率と評価値。

    ``mix_ratios_b`` は :data:`PAIR_INDICES` と同じ順で並ぶ色Bの割合です。
    評価値は入力された各色を有効な最大32色パレットへ割り当てたときの、重み付き
    CIE76平均です。``palette_weight_fractions`` は最終割り当てにおける各パレット
    状態（基本4色 + 混色12色）の重み比率で、無効な状態は0になります。
    """

    initial_mix_ratios_b: tuple[int, ...]
    mix_ratios_b: tuple[int, ...]
    palette_rgb: tuple[tuple[int, int, int], ...]
    palette_hex: tuple[str, ...]
    initial_weighted_mean_delta_e76: float
    weighted_mean_delta_e76: float
    improvement_delta_e76: float
    improvement_percent: float
    palette_weight_fractions: tuple[float, ...]
    passes: int
    converged: bool
    objective_evaluations: int
    sample_count: int
    histogram_color_count: int
    histogram_bins_per_channel: int
    total_weight: float
    # The established GUI optimiser changes only states 5..10.  Owned-spool
    # recommendation may opt into jointly fitting states 11..16 as well; these
    # fields expose that result without changing the legacy fields or default
    # behaviour.
    initial_secondary_mix_ratios_b: tuple[int, ...] = ()
    secondary_mix_ratios_b: tuple[int, ...] = ()


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


@lru_cache(maxsize=1)
def model_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with np.load(resource_path("assets/mixer_model.npz"), allow_pickle=False) as data:
        return data["powers"], data["coefficients"], data["intercept"]


def normalize_hex(value: str) -> str:
    text = value.strip().upper()
    if not text.startswith("#"):
        text = "#" + text
    if len(text) != 7 or any(ch not in "0123456789ABCDEF" for ch in text[1:]):
        raise ValueError(f"色は #RRGGBB 形式で入力してください: {value}")
    return text


def hex_to_rgb8(value: str) -> np.ndarray:
    text = normalize_hex(value)
    return np.asarray([int(text[index : index + 2], 16) for index in (1, 3, 5)], dtype=np.uint8)


def rgb8_to_hex(rgb: np.ndarray | tuple[int, int, int]) -> str:
    values = [int(value) for value in rgb]
    return "#" + "".join(f"{max(0, min(255, value)):02X}" for value in values)


def mix_rgb8(first: np.ndarray, second: np.ndarray, ratio: float = 0.5) -> np.ndarray:
    if ratio <= 0.0:
        return np.asarray(first, dtype=np.uint8).copy()
    if ratio >= 1.0:
        return np.asarray(second, dtype=np.uint8).copy()
    powers, coefficients, intercept = model_arrays()
    x = np.asarray(
        [float(first[0]), float(first[1]), float(first[2]), float(second[0]), float(second[1]), float(second[2]), float(ratio)],
        dtype=np.float64,
    )
    features = np.prod(np.power(x[None, :], powers, dtype=np.float64), axis=1)
    result = features @ coefficients + intercept
    return np.clip(result.astype(np.int64), 0, 255).astype(np.uint8)


def _coerce_rgb8(value: str | Sequence[int] | np.ndarray, name: str) -> np.ndarray:
    if isinstance(value, str):
        return hex_to_rgb8(value)
    rgb = np.asarray(value)
    if rgb.shape != (3,):
        raise ValueError(f"{name} はRGBの3要素で指定してください")
    try:
        numeric = rgb.astype(np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} は0～255の整数で指定してください") from exc
    if not np.all(np.isfinite(numeric)) or np.any(numeric < 0.0) or np.any(numeric > 255.0):
        raise ValueError(f"{name} は0～255の整数で指定してください")
    rounded = np.rint(numeric)
    if not np.allclose(numeric, rounded, rtol=0.0, atol=1e-9):
        raise ValueError(f"{name} は0～255の整数で指定してください")
    return rounded.astype(np.uint8)


def _rgb8_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 8-bitをD65基準のCIE L*a*b*へ変換する。"""

    srgb = np.asarray(rgb, dtype=np.float64).reshape(-1, 3) / 255.0
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    xyz = linear @ np.asarray(
        [
            [0.4124564, 0.2126729, 0.0193339],
            [0.3575761, 0.7151522, 0.1191920],
            [0.1804375, 0.0721750, 0.9503041],
        ],
        dtype=np.float64,
    )
    xyz /= np.asarray([0.95047, 1.0, 1.08883], dtype=np.float64)
    delta = 6.0 / 29.0
    transformed = np.where(
        xyz > delta**3,
        np.cbrt(xyz),
        xyz / (3.0 * delta**2) + 4.0 / 29.0,
    )
    return np.column_stack(
        (
            116.0 * transformed[:, 1] - 16.0,
            500.0 * (transformed[:, 0] - transformed[:, 1]),
            200.0 * (transformed[:, 1] - transformed[:, 2]),
        )
    )


def _coerce_rgb_distribution(value: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    """RGB色分布を0～255のfloat64配列へそろえる。

    浮動小数点入力がすべて0～1なら正規化sRGBとして扱う。整数入力と、1を
    超える浮動小数点入力は0～255として扱う。これによりエンジン内部の0～1
    RGB配列も、一般的な8-bit RGB配列もそのまま渡せる。
    """

    try:
        raw = np.asarray(value)
        numeric = raw.astype(np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("目標色分布はRGBのN×3配列で指定してください") from exc
    if numeric.ndim == 1 and numeric.shape == (3,):
        numeric = numeric.reshape(1, 3)
    if numeric.ndim != 2 or numeric.shape[1] != 3 or len(numeric) == 0:
        raise ValueError("目標色分布はRGBのN×3配列で指定してください")
    if not np.all(np.isfinite(numeric)) or np.any(numeric < 0.0):
        raise ValueError("目標色分布は0～255、または0～1のRGBで指定してください")
    if np.issubdtype(raw.dtype, np.floating) and float(numeric.max()) <= 1.0:
        numeric = numeric * 255.0
    if np.any(numeric > 255.0):
        raise ValueError("目標色分布は0～255、または0～1のRGBで指定してください")
    return numeric


def _coerce_weights(weights: Sequence[float] | np.ndarray | None, count: int) -> np.ndarray:
    if weights is None:
        return np.ones(count, dtype=np.float64)
    try:
        result = np.asarray(weights, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("weights は目標色と同じ長さの非負数で指定してください") from exc
    if result.shape != (count,):
        raise ValueError("weights は目標色と同じ長さで指定してください")
    if not np.all(np.isfinite(result)) or np.any(result < 0.0):
        raise ValueError("weights は有限の非負数で指定してください")
    if float(result.sum()) <= 0.0:
        raise ValueError("weights の合計は0より大きくしてください")
    return result


def _coerce_mix_ratios(value: Sequence[int] | None) -> tuple[int, ...]:
    ratios = DEFAULT_PRIMARY_MIX_RATIOS_B if value is None else tuple(value)
    if len(ratios) != len(PAIR_INDICES) or any(
        isinstance(ratio, bool)
        or not isinstance(ratio, (int, np.integer))
        or not 0 <= int(ratio) <= 100
        for ratio in ratios
    ):
        raise ValueError("initial_ratios_b は0～100の整数6個で指定してください")
    return tuple(int(ratio) for ratio in ratios)


def _coerce_secondary_mix_ratios(
    value: Sequence[int] | None,
) -> tuple[int, ...]:
    ratios = DEFAULT_SECONDARY_MIX_RATIOS_B if value is None else tuple(value)
    if len(ratios) != len(PAIR_INDICES) or any(
        isinstance(ratio, bool)
        or not isinstance(ratio, (int, np.integer))
        or not 0 <= int(ratio) <= 100
        for ratio in ratios
    ):
        raise ValueError(
            "secondary_mix_ratios_b must contain six integers from 0 to 100"
        )
    return tuple(int(ratio) for ratio in ratios)


def _coerce_enabled_states(value: Sequence[bool] | None) -> tuple[bool, ...]:
    enabled = (
        (True,) * DEFAULT_PALETTE_STATE_COUNT
        + (False,) * (PALETTE_STATE_COUNT - DEFAULT_PALETTE_STATE_COUNT)
        if value is None
        else tuple(value)
    )
    if len(enabled) not in ((10,) + SUPPORTED_PALETTE_STATE_COUNTS) or any(
        not isinstance(item, (bool, np.bool_)) for item in enabled
    ):
        raise ValueError(
            f"enabled_states は従来10色または拡張{PALETTE_STATE_COUNT}色の真偽値で指定してください"
        )
    if len(enabled) < PALETTE_STATE_COUNT:
        enabled = enabled + (False,) * (PALETTE_STATE_COUNT - len(enabled))
    result = tuple(bool(item) for item in enabled)
    if not any(result):
        raise ValueError("enabled_states は少なくとも1色を有効にしてください")
    return result


def _coerce_pink_protection_mask(
    value: Sequence[bool] | np.ndarray | None,
    count: int,
) -> np.ndarray | None:
    if value is None:
        return None
    raw = np.asarray(value)
    if raw.shape != (count,):
        raise ValueError("pink_protection_mask は目標色と同じ長さで指定してください")
    if not np.issubdtype(raw.dtype, np.bool_):
        raise ValueError("pink_protection_mask は真偽値で指定してください")
    return raw.astype(bool, copy=True)


def _coerce_unrestricted_state_mask(
    value: Sequence[bool] | np.ndarray | None,
    count: int,
    pink_protection_mask: np.ndarray | None,
) -> np.ndarray | None:
    """Validate samples that may use either protected palette family.

    This is primarily used for reference-image representatives: unlike OBJ
    faces they do not have a face-level F4 protection classification, so they
    must retain their original ability to match any enabled palette state.
    """

    if value is None:
        return None
    if pink_protection_mask is None:
        raise ValueError(
            "unrestricted_state_mask requires pink_protection_mask"
        )
    raw = np.asarray(value)
    if raw.shape != (count,):
        raise ValueError(
            "unrestricted_state_mask must match the target color count"
        )
    if not np.issubdtype(raw.dtype, np.bool_):
        raise ValueError("unrestricted_state_mask must contain booleans")
    return raw.astype(bool, copy=True)


@lru_cache(maxsize=16)
def _mix_ratio_grid(physical_key: tuple[tuple[int, int, int], ...]) -> np.ndarray:
    """6ペア×101比率の公式予測色をキャッシュする。"""

    physical = [np.asarray(rgb, dtype=np.uint8) for rgb in physical_key]
    result = np.empty((len(PAIR_INDICES), 101, 3), dtype=np.uint8)
    for pair_index, (left, right) in enumerate(PAIR_INDICES):
        for ratio_b in range(101):
            result[pair_index, ratio_b] = mix_rgb8(
                physical[left], physical[right], ratio_b / 100.0
            )
    result.setflags(write=False)
    return result


def _weighted_rgb_histogram(
    rgb: np.ndarray,
    weights: np.ndarray,
    bins_per_channel: int,
) -> tuple[np.ndarray, np.ndarray]:
    """量子化セルごとの重み付きRGB重心を返す。"""

    quantized = np.floor(rgb * (bins_per_channel / 256.0)).astype(np.int64)
    np.clip(quantized, 0, bins_per_channel - 1, out=quantized)
    keys = (
        quantized[:, 0] * bins_per_channel * bins_per_channel
        + quantized[:, 1] * bins_per_channel
        + quantized[:, 2]
    )
    _, inverse = np.unique(keys, return_inverse=True)
    histogram_weights = np.bincount(inverse, weights=weights).astype(np.float64, copy=False)
    keep = histogram_weights > 0.0
    colors = np.empty((int(np.count_nonzero(keep)), 3), dtype=np.float64)
    for channel in range(3):
        sums = np.bincount(inverse, weights=weights * rgb[:, channel])
        colors[:, channel] = sums[keep] / histogram_weights[keep]
    return colors, histogram_weights[keep]


def _squared_distances(points: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    """各点と各候補のユークリッド距離の二乗を行列で返す。"""

    result = (
        np.einsum("ij,ij->i", points, points)[:, None]
        + np.einsum("ij,ij->i", candidates, candidates)[None, :]
        - 2.0 * points @ candidates.T
    )
    return np.maximum(result, 0.0)


def _palette_from_ratios(
    physical: np.ndarray,
    mix_grid: np.ndarray,
    ratios: Sequence[int],
    secondary_ratios: Sequence[int],
) -> np.ndarray:
    mixed = np.asarray(
        [
            mix_grid[_PAIR_TO_INDEX[(left, right)], int(ratio)]
            for left, right, ratio in palette_mix_specs(
                ratios, secondary_ratios
            )
        ],
        dtype=np.uint8,
    )
    return np.vstack((physical, mixed))


def _palette_metrics(
    target_lab: np.ndarray,
    weights: np.ndarray,
    palette_rgb: np.ndarray,
    enabled_states: tuple[bool, ...],
    pink_protection_mask: np.ndarray | None = None,
    unrestricted_state_mask: np.ndarray | None = None,
) -> tuple[float, np.ndarray]:
    palette_lab = _rgb8_to_lab(palette_rgb)
    assignments = np.empty(len(target_lab), dtype=np.int64)
    minimum = np.empty(len(target_lab), dtype=np.float64)
    if pink_protection_mask is None:
        groups = (
            (np.ones(len(target_lab), dtype=bool), tuple(range(PALETTE_STATE_COUNT))),
        )
    else:
        unrestricted = (
            np.zeros(len(target_lab), dtype=bool)
            if unrestricted_state_mask is None
            else unrestricted_state_mask
        )
        groups = (
            (unrestricted, tuple(range(PALETTE_STATE_COUNT))),
            (
                (~pink_protection_mask) & (~unrestricted),
                NEUTRAL_PALETTE_STATES,
            ),
            (pink_protection_mask & (~unrestricted), PINK_PALETTE_STATES),
        )
    for group_mask, allowed_states in groups:
        sample_indices = np.flatnonzero(group_mask)
        if len(sample_indices) == 0:
            continue
        active_indices = np.asarray(
            [state for state in allowed_states if enabled_states[state]],
            dtype=np.int64,
        )
        if len(active_indices) == 0:
            raise ValueError("割り当て可能な有効パレット色がありません")
        for start in range(0, len(sample_indices), 25_000):
            batch = sample_indices[start : start + 25_000]
            distances = _squared_distances(
                target_lab[batch], palette_lab[active_indices]
            )
            local_assignments = np.argmin(distances, axis=1)
            assignments[batch] = active_indices[local_assignments]
            minimum[batch] = np.sqrt(
                distances[np.arange(len(batch)), local_assignments]
            )
    total_weight = float(weights.sum())
    score = float(np.dot(weights, minimum) / total_weight)
    fractions = (
        np.bincount(
            assignments, weights=weights, minlength=PALETTE_STATE_COUNT
        )
        / total_weight
    )
    return score, fractions


def optimize_global_mix_ratios(
    target_rgb: Sequence[Sequence[float]] | np.ndarray,
    physical_rgb: Sequence[str | Sequence[int] | np.ndarray],
    *,
    weights: Sequence[float] | np.ndarray | None = None,
    initial_ratios_b: Sequence[int] | None = None,
    secondary_ratios_b: Sequence[int] | None = None,
    enabled_states: Sequence[bool] | None = None,
    pink_protection_mask: Sequence[bool] | np.ndarray | None = None,
    unrestricted_state_mask: Sequence[bool] | np.ndarray | None = None,
    histogram_bins_per_channel: int = 32,
    max_passes: int = 8,
    optimize_secondary_ratios: bool = False,
) -> GlobalMixOptimizationResult:
    """モデル全体に合う6組のFull Spectrum混色比率を求める。

    目標RGB分布を量子化した重み付きヒストグラムへ圧縮し、4基本色、6個の
    編集可能な主混色6色、設定へ保存される追加混色6色の
    最近傍CIE76誤差が最小になるよう、各混色ペアの0～100%を決定論的な座標
    降下で探索します。混色予測には :func:`mix_rgb8` と同じ公式モデルを使用
    します。``weights`` には面積を渡せるため、大きい三角形ほど強く反映できます。

    ``target_rgb`` はN×3の0～255 RGBです。浮動小数点で全値が0～1なら正規化
    sRGBとして自動認識します。``enabled_states`` は最大32色の状態順です。
    ``pink_protection_mask`` を渡した場合は、Falseの面をF1～F3系状態だけ、Trueの
    面をF4系状態だけへ割り当て、エンジンのF4系保護と同じ制約で探索します。
    ``unrestricted_state_mask`` がTrueの試料はこの二分を上書きし、全有効状態を
    使用できます。面の分類を持たない参照画像の代表色を保つ用途です。
    無効な混色状態の比率は初期値から変更しません。既定では従来どおり主混色
    6色だけを動かします。``optimize_secondary_ratios=True`` の場合は追加混色
    6色（状態11～16）も同じ目的関数で同時に調整します。この関数は入力や設定を
    変更せず、同じ入力には常に同じ結果を返します。
    """

    if len(physical_rgb) != 4:
        raise ValueError("物理フィラメントは4色必要です")
    if (
        isinstance(histogram_bins_per_channel, bool)
        or not isinstance(histogram_bins_per_channel, int)
        or not 2 <= histogram_bins_per_channel <= 256
    ):
        raise ValueError("histogram_bins_per_channel は2～256の整数で指定してください")
    if isinstance(max_passes, bool) or not isinstance(max_passes, int) or max_passes <= 0:
        raise ValueError("max_passes は1以上の整数で指定してください")

    target = _coerce_rgb_distribution(target_rgb)
    sample_weights = _coerce_weights(weights, len(target))
    initial = _coerce_mix_ratios(initial_ratios_b)
    secondary = _coerce_secondary_mix_ratios(secondary_ratios_b)
    enabled = _coerce_enabled_states(enabled_states)
    pink_mask = _coerce_pink_protection_mask(pink_protection_mask, len(target))
    unrestricted_mask = _coerce_unrestricted_state_mask(
        unrestricted_state_mask,
        len(target),
        pink_mask,
    )
    if pink_mask is not None:
        if not any(enabled[state] for state in NEUTRAL_PALETTE_STATES):
            raise ValueError("F4系保護にはF1～F3系パレットを1色以上有効にしてください")
        if not any(enabled[state] for state in PINK_PALETTE_STATES):
            raise ValueError("F4系保護にはF4を含むパレットを1色以上有効にしてください")
    physical = np.asarray(
        [
            _coerce_rgb8(value, f"物理フィラメント{index + 1}")
            for index, value in enumerate(physical_rgb)
        ],
        dtype=np.uint8,
    )
    physical_key = tuple(tuple(int(channel) for channel in rgb) for rgb in physical)
    mix_grid = _mix_ratio_grid(physical_key)
    mix_grid_lab = _rgb8_to_lab(mix_grid.reshape(-1, 3)).reshape(len(PAIR_INDICES), 101, 3)
    physical_lab = _rgb8_to_lab(physical)
    # States 11..32 are fixed while the optimiser moves the six primary
    # ratios in states 5..10.  Keep their ordered recipes available here;
    # treating every state after 10 as one of only six secondary recipes made
    # the 24/32-state optimiser index past that six-element array.
    fixed_mix_specs = palette_mix_specs(initial, secondary)

    # 重み0の面は目的関数に影響しないため、ヒストグラムと正確な最終評価から除く。
    positive = sample_weights > 0.0
    active_target = target[positive]
    active_weights = sample_weights[positive]
    active_pink_mask = pink_mask[positive] if pink_mask is not None else None
    active_unrestricted_mask = (
        unrestricted_mask[positive] if unrestricted_mask is not None else None
    )
    optimization_groups: list[tuple[np.ndarray, np.ndarray, tuple[int, ...]]] = []
    if active_pink_mask is None:
        histogram_rgb, histogram_weights = _weighted_rgb_histogram(
            active_target, active_weights, histogram_bins_per_channel
        )
        optimization_groups.append(
            (
                _rgb8_to_lab(histogram_rgb),
                histogram_weights,
                tuple(range(PALETTE_STATE_COUNT)),
            )
        )
    else:
        unrestricted = (
            np.zeros(len(active_target), dtype=bool)
            if active_unrestricted_mask is None
            else active_unrestricted_mask
        )
        for group_mask, allowed_states in (
            (unrestricted, tuple(range(PALETTE_STATE_COUNT))),
            ((~active_pink_mask) & (~unrestricted), NEUTRAL_PALETTE_STATES),
            (active_pink_mask & (~unrestricted), PINK_PALETTE_STATES),
        ):
            if not np.any(group_mask):
                continue
            histogram_rgb, histogram_weights = _weighted_rgb_histogram(
                active_target[group_mask],
                active_weights[group_mask],
                histogram_bins_per_channel,
            )
            optimization_groups.append(
                (_rgb8_to_lab(histogram_rgb), histogram_weights, allowed_states)
            )
    histogram_color_count = sum(len(group_lab) for group_lab, _, _ in optimization_groups)
    total_histogram_weight = sum(
        float(group_weights.sum()) for _, group_weights, _ in optimization_groups
    )

    ratios = np.asarray(initial, dtype=np.int16)
    secondary_values = np.asarray(secondary, dtype=np.int16)
    coordinates: list[tuple[int, int, np.ndarray]] = [
        (4 + pair_index, pair_index, ratios)
        for pair_index in range(len(PAIR_INDICES))
    ]
    if optimize_secondary_ratios:
        coordinates.extend(
            (10 + pair_index, pair_index, secondary_values)
            for pair_index in range(len(PAIR_INDICES))
        )
    evaluations = 0
    passes = 0
    converged = False
    tolerance = 1e-12

    for pass_index in range(max_passes):
        changed = False
        considered = False
        for candidate_state, pair_index, ratio_values in coordinates:
            if not enabled[candidate_state]:
                continue
            considered = True

            scores = np.zeros(101, dtype=np.float64)
            for histogram_lab, histogram_weights, allowed_states in optimization_groups:
                fixed_labs: list[np.ndarray] = []
                for state in allowed_states:
                    if state == candidate_state or not enabled[state]:
                        continue
                    if state < 4:
                        fixed_labs.append(physical_lab[state])
                    elif state < 10:
                        other = state - 4
                        fixed_labs.append(mix_grid_lab[other, int(ratios[other])])
                    elif state < 16:
                        other = state - 10
                        fixed_labs.append(
                            mix_grid_lab[other, int(secondary_values[other])]
                        )
                    else:
                        left, right, fixed_ratio = fixed_mix_specs[state - 4]
                        fixed_labs.append(
                            mix_grid_lab[
                                _PAIR_TO_INDEX[(left, right)],
                                int(fixed_ratio),
                            ]
                        )
                if fixed_labs:
                    fixed_distances = _squared_distances(
                        histogram_lab, np.asarray(fixed_labs, dtype=np.float64)
                    ).min(axis=1)
                else:
                    fixed_distances = np.full(
                        len(histogram_lab), np.inf, dtype=np.float64
                    )

                if candidate_state not in allowed_states:
                    scores += float(
                        np.dot(histogram_weights, np.sqrt(fixed_distances))
                    )
                    continue

                # 101候補を小分けにして、巨大モデルでも一時行列を抑える。
                for start in range(0, 101, 16):
                    stop = min(101, start + 16)
                    candidate_distances = _squared_distances(
                        histogram_lab, mix_grid_lab[pair_index, start:stop]
                    )
                    nearest = np.minimum(
                        fixed_distances[:, None], candidate_distances
                    )
                    scores[start:stop] += np.sum(
                        np.sqrt(nearest) * histogram_weights[:, None], axis=0
                    )
            scores /= total_histogram_weight
            evaluations += 101

            current_ratio = int(ratio_values[pair_index])
            best_ratio = int(np.argmin(scores))
            # 同点なら現在値を維持し、無意味な比率移動や往復を防ぐ。
            if scores[best_ratio] < scores[current_ratio] - tolerance:
                ratio_values[pair_index] = best_ratio
                changed = True

        if considered:
            passes = pass_index + 1
        if not changed:
            converged = True
            break
        if not considered:
            converged = True
            break

    # 報告値はヒストグラム近似ではなく、元の全サンプルで正確に計算する。
    target_lab = _rgb8_to_lab(active_target)
    initial_palette = _palette_from_ratios(
        physical, mix_grid, initial, secondary
    )
    initial_score, _ = _palette_metrics(
        target_lab,
        active_weights,
        initial_palette,
        enabled,
        active_pink_mask,
        active_unrestricted_mask,
    )
    optimized = tuple(int(value) for value in ratios)
    optimized_secondary = tuple(int(value) for value in secondary_values)
    palette = _palette_from_ratios(
        physical, mix_grid, optimized, optimized_secondary
    )
    final_score, fractions = _palette_metrics(
        target_lab,
        active_weights,
        palette,
        enabled,
        active_pink_mask,
        active_unrestricted_mask,
    )

    # ヒストグラム近似がまれに元分布を悪化させた場合は、安全に初期値へ戻す。
    if final_score > initial_score + tolerance:
        optimized = initial
        optimized_secondary = secondary
        palette = initial_palette
        final_score, fractions = _palette_metrics(
            target_lab,
            active_weights,
            palette,
            enabled,
            active_pink_mask,
            active_unrestricted_mask,
        )

    improvement = max(0.0, initial_score - final_score)
    improvement_percent = 0.0 if initial_score <= tolerance else improvement / initial_score * 100.0
    palette_rgb_tuple = tuple(
        tuple(int(channel) for channel in rgb) for rgb in palette
    )
    return GlobalMixOptimizationResult(
        initial_mix_ratios_b=initial,
        mix_ratios_b=optimized,
        palette_rgb=palette_rgb_tuple,
        palette_hex=tuple(rgb8_to_hex(rgb) for rgb in palette_rgb_tuple),
        initial_weighted_mean_delta_e76=float(initial_score),
        weighted_mean_delta_e76=float(final_score),
        improvement_delta_e76=float(improvement),
        improvement_percent=float(improvement_percent),
        palette_weight_fractions=tuple(float(value) for value in fractions),
        passes=passes,
        converged=converged,
        objective_evaluations=evaluations,
        sample_count=len(target),
        histogram_color_count=histogram_color_count,
        histogram_bins_per_channel=histogram_bins_per_channel,
        total_weight=float(sample_weights.sum()),
        initial_secondary_mix_ratios_b=secondary,
        secondary_mix_ratios_b=optimized_secondary,
    )


def find_best_mix_recipes(
    target_rgb: str | Sequence[int] | np.ndarray,
    physical_rgb: Sequence[str | Sequence[int] | np.ndarray],
    *,
    top_n: int = 10,
) -> list[MixRecipeCandidate]:
    """4基本色から目標色に近い混色レシピをCIE76順で返す。

    4色から作れる全6ペアについて、色Bの割合を0～100%まで1%刻みで
    網羅的に探索します。予測色はSnapmaker Orca由来の
    :func:`mix_rgb8` で計算します。入力は ``#RRGGBB`` または0～255の
    RGB 3要素です。この関数はファイルやグローバル設定を変更しません。
    """

    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n <= 0:
        raise ValueError("top_n は1以上の整数で指定してください")
    if len(physical_rgb) != 4:
        raise ValueError("物理フィラメントは4色必要です")

    target = _coerce_rgb8(target_rgb, "目標色")
    physical = [
        _coerce_rgb8(value, f"物理フィラメント{index + 1}")
        for index, value in enumerate(physical_rgb)
    ]

    metadata: list[tuple[int, int, int]] = []
    predicted: list[np.ndarray] = []
    for color_a_index, color_b_index in PAIR_INDICES:
        color_a = physical[color_a_index]
        color_b = physical[color_b_index]
        for ratio_b_percent in range(101):
            predicted.append(mix_rgb8(color_a, color_b, ratio_b_percent / 100.0))
            metadata.append((color_a_index, color_b_index, ratio_b_percent))

    predicted_array = np.asarray(predicted, dtype=np.uint8)
    predicted_lab = _rgb8_to_lab(predicted_array)
    target_lab = _rgb8_to_lab(target)[0]
    delta_e76 = np.linalg.norm(predicted_lab - target_lab, axis=1)
    ranked_indices = np.argsort(delta_e76, kind="stable")[:top_n]

    candidates: list[MixRecipeCandidate] = []
    for candidate_index in ranked_indices:
        color_a_index, color_b_index, ratio_b_percent = metadata[int(candidate_index)]
        mixed_rgb = predicted_array[candidate_index]
        mixed_lab = predicted_lab[candidate_index]
        candidates.append(
            MixRecipeCandidate(
                color_a_index=color_a_index,
                color_b_index=color_b_index,
                color_a_rgb=tuple(int(value) for value in physical[color_a_index]),
                color_b_rgb=tuple(int(value) for value in physical[color_b_index]),
                ratio_b_percent=ratio_b_percent,
                predicted_rgb=tuple(int(value) for value in mixed_rgb),
                predicted_lab=tuple(float(value) for value in mixed_lab),
                delta_e76=float(delta_e76[candidate_index]),
            )
        )
    return candidates


def build_palette_rgb(
    physical_hex: list[str],
    mix_hex_overrides: list[str | None] | None = None,
    mix_ratios_b: list[int] | None = None,
    secondary_mix_ratios_b: list[int] | None = None,
) -> tuple[list[str], np.ndarray]:
    if len(physical_hex) != 4:
        raise ValueError("物理フィラメントは4色必要です")
    physical = [hex_to_rgb8(value) for value in physical_hex]
    overrides = mix_hex_overrides or [None] * 6
    if len(overrides) != 6:
        raise ValueError("混色上書きは6色必要です")
    ratios_b = _coerce_mix_ratios(mix_ratios_b)
    if len(ratios_b) != 6:
        raise ValueError("混色比率は6組必要です")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not 0 <= int(value) <= 100
        for value in ratios_b
    ):
        raise ValueError("混色比率は0～100の整数で指定してください")
    mixed: list[np.ndarray] = []
    secondary_ratios_b = _coerce_secondary_mix_ratios(
        secondary_mix_ratios_b
    )
    for index, (left, right, ratio_b) in enumerate(
        palette_mix_specs(ratios_b, secondary_ratios_b)
    ):
        # The six display overrides remain attached to the original editable
        # states only.  Added gradient shades always use the printable mixer
        # prediction so their Orca and application colours stay in agreement.
        override = overrides[index] if index < PRIMARY_MIX_STATE_COUNT else None
        mixed.append(
            hex_to_rgb8(override)
            if override
            else mix_rgb8(physical[left], physical[right], int(ratio_b) / 100.0)
        )
    values = physical + mixed
    return [rgb8_to_hex(value) for value in values], np.asarray(values, dtype=np.float64) / 255.0
