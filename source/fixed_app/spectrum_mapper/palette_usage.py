from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator, Mapping

import numpy as np

from .mixer import (
    PALETTE_STATE_COUNT,
    orca_effective_mix_ratio,
    print_palette_mix_specs,
)
from .models import ColorResult, MeshLevel


def _pattern_weights(pattern: str) -> np.ndarray:
    """Return exact F1..F4 shares of one Orca Cycle pattern group."""

    tokens = [int(value) for value in str(pattern)]
    if not tokens or any(value < 1 or value > 4 for value in tokens):
        raise ValueError("surface-shell pattern must contain only F1..F4 tokens")
    counts = np.bincount(np.asarray(tokens, dtype=np.int8), minlength=5)[1:5]
    return counts.astype(np.float64) / float(len(tokens))


@dataclass(frozen=True, slots=True)
class PaletteUsage:
    """Read-only usage statistics for one palette state in one mesh scope."""

    state: int
    part_id: int | None
    face_count: int
    scope_face_count: int
    area_mm2: float
    scope_area_mm2: float
    adaptive_root_count: int = 0
    adaptive_leaf_count: int = 0
    selected_adaptive_root_count: int = 0
    selected_adaptive_leaf_count: int = 0

    @property
    def face_fraction(self) -> float:
        if self.scope_face_count <= 0:
            return 0.0
        return float(self.face_count / self.scope_face_count)

    @property
    def area_fraction(self) -> float:
        if self.scope_area_mm2 <= 0.0:
            return 0.0
        return float(self.area_mm2 / self.scope_area_mm2)


def _validated_indices(level: MeshLevel, palette_indices: np.ndarray) -> np.ndarray:
    values = np.asarray(palette_indices)
    if values.shape != (len(level.faces),):
        raise ValueError("palette_indices must contain one state per face")
    if not np.issubdtype(values.dtype, np.integer):
        raise ValueError("palette_indices must be integers")
    return values


def _scope_mask(level: MeshLevel, part_id: int | None) -> np.ndarray:
    face_count = len(level.faces)
    if part_id is None:
        return np.ones(face_count, dtype=bool)
    part_ids = np.asarray(level.face_part_ids)
    if part_ids.shape != (face_count,):
        if int(part_id) == 0:
            return np.ones(face_count, dtype=bool)
        raise ValueError(f"unknown part ID: {part_id}")
    scope = part_ids == int(part_id)
    if not bool(np.any(scope)):
        raise ValueError(f"unknown part ID: {part_id}")
    return scope


def _iter_adaptive_leaf_fractions(
    node: object,
    fraction: float = 1.0,
) -> Iterator[tuple[int, float]]:
    """Yield ``(state, area_fraction)`` without depending on hotfix imports."""

    children = getattr(node, "children", None)
    if children is None:
        state = int(getattr(node, "state"))
        if state < 0 or state >= PALETTE_STATE_COUNT:
            raise ValueError("adaptive leaf references an invalid palette state")
        yield state, float(fraction)
        return
    values = tuple(children)
    split_sides = int(getattr(node, "split_sides", 3))
    if split_sides == 1:
        weights = (0.5, 0.5)
    elif split_sides == 2:
        weights = (0.25, 0.25, 0.5)
    else:
        weights = (0.25, 0.25, 0.25, 0.25)
    if len(values) != len(weights):
        raise ValueError("adaptive node child count does not match split mode")
    for child, weight in zip(values, weights, strict=True):
        yield from _iter_adaptive_leaf_fractions(
            child,
            float(fraction) * float(weight),
        )


def _state_area_distribution(
    level: MeshLevel,
    indices: np.ndarray,
    height_mm: float,
    scope: np.ndarray,
    adaptive_trees: Mapping[int, object] | None,
) -> tuple[np.ndarray, dict[int, tuple[tuple[int, float], ...]]]:
    areas_mm2 = np.asarray(level.areas_unit, dtype=np.float64) * height_mm * height_mm
    by_state = np.bincount(
        indices[scope].astype(np.int64, copy=False),
        weights=areas_mm2[scope],
        minlength=PALETTE_STATE_COUNT,
    )[:PALETTE_STATE_COUNT].astype(np.float64, copy=False)
    adaptive: dict[int, tuple[tuple[int, float], ...]] = {}
    if not adaptive_trees:
        return by_state, adaptive
    for raw_face, node in tuple(adaptive_trees.items()):
        face = int(raw_face)
        if face < 0 or face >= len(indices) or not bool(scope[face]):
            continue
        try:
            leaves = tuple(_iter_adaptive_leaf_fractions(node))
        except (AttributeError, TypeError, ValueError):
            # An invalid external tree must not make the diagnostic unusable;
            # retain the authoritative face-level state for that root.
            continue
        if not leaves:
            continue
        fraction_sum = float(sum(fraction for _state, fraction in leaves))
        if not np.isfinite(fraction_sum) or abs(fraction_sum - 1.0) > 1.0e-6:
            continue
        root_area = float(areas_mm2[face])
        by_state[int(indices[face])] -= root_area
        for leaf_state, fraction in leaves:
            by_state[leaf_state] += root_area * fraction
        adaptive[face] = leaves
    # Avoid harmless negative ulps after subtracting and redistributing roots.
    np.maximum(by_state, 0.0, out=by_state)
    return by_state, adaptive


def analyze_palette_usage(
    level: MeshLevel,
    palette_indices: np.ndarray,
    state: int,
    height_mm: float,
    *,
    part_id: int | None = None,
    adaptive_trees: Mapping[int, object] | None = None,
) -> PaletteUsage:
    """Measure one state without changing mesh, palette, or paint data.

    ``areas_unit`` is normalized to model height, so multiplying by the square
    of ``height_mm`` gives the same real surface-area convention used by the
    recoloring and export reports.
    """

    indices = _validated_indices(level, palette_indices)
    selected_state = int(state)
    if not 0 <= selected_state < PALETTE_STATE_COUNT:
        raise ValueError(f"state must be between 0 and {PALETTE_STATE_COUNT - 1}")
    height = float(height_mm)
    if not np.isfinite(height) or height <= 0.0:
        raise ValueError("height_mm must be positive")
    areas_unit = np.asarray(level.areas_unit, dtype=np.float64)
    if areas_unit.shape != (len(level.faces),):
        raise ValueError("areas_unit must contain one area per face")
    if not np.isfinite(areas_unit).all() or bool(np.any(areas_unit < 0.0)):
        raise ValueError("areas_unit must contain finite non-negative values")

    scope = _scope_mask(level, part_id)
    areas_mm2 = areas_unit * height * height
    by_state, adaptive = _state_area_distribution(
        level,
        indices,
        height,
        scope,
        adaptive_trees,
    )
    selected_roots = scope & (indices == selected_state)
    selected_adaptive_roots = 0
    selected_adaptive_leaves = 0
    adaptive_leaf_count = 0
    for face, leaves in adaptive.items():
        has_selected = any(
            leaf_state == selected_state for leaf_state, _fraction in leaves
        )
        selected_roots[face] = has_selected
        adaptive_leaf_count += len(leaves)
        if has_selected:
            selected_adaptive_roots += 1
            selected_adaptive_leaves += sum(
                leaf_state == selected_state
                for leaf_state, _fraction in leaves
            )
    return PaletteUsage(
        state=selected_state,
        part_id=None if part_id is None else int(part_id),
        face_count=int(np.count_nonzero(selected_roots)),
        scope_face_count=int(np.count_nonzero(scope)),
        area_mm2=float(by_state[selected_state]),
        scope_area_mm2=float(areas_mm2[scope].sum()),
        adaptive_root_count=len(adaptive),
        adaptive_leaf_count=int(adaptive_leaf_count),
        selected_adaptive_root_count=int(selected_adaptive_roots),
        selected_adaptive_leaf_count=int(selected_adaptive_leaves),
    )


def palette_state_base_weights(
    state: int,
    mix_ratios_b: list[int] | tuple[int, ...] | None = None,
    secondary_mix_ratios_b: list[int] | tuple[int, ...] | None = None,
    output_mix_ratios_b: list[int] | tuple[int, ...] | None = None,
    *,
    surface_shell_enabled: bool = False,
    physical_hex: list[str] | tuple[str, ...] | None = None,
) -> tuple[float, float, float, float]:
    """Return the effective F1..F4 layer share of one Full Spectrum state."""

    selected_state = int(state)
    if not 0 <= selected_state < PALETTE_STATE_COUNT:
        raise ValueError(f"state must be between 0 and {PALETTE_STATE_COUNT - 1}")
    weights = np.zeros(4, dtype=np.float64)
    if selected_state < 4:
        weights[selected_state] = 1.0
    else:
        specs = print_palette_mix_specs(
            mix_ratios_b,
            secondary_mix_ratios_b,
            output_mix_ratios_b,
        )
        left, right, ratio_b = specs[selected_state - 4]
        shell = None
        if surface_shell_enabled:
            # Imported lazily to avoid making ordinary editor diagnostics pay
            # the engine's heavier import cost.
            from .engine import build_surface_shell_output_specs

            shell = build_surface_shell_output_specs(
                physical_hex,
                list(mix_ratios_b) if mix_ratios_b is not None else [33] * 6,
                secondary_mix_ratios_b,
                output_mix_ratios_b,
            )[selected_state - 4]
        if shell is not None and shell.applied:
            weights[shell.outer_filament - 1] += 0.5
            weights += 0.5 * _pattern_weights(shell.inner_pattern or "")
        else:
            effective_b = orca_effective_mix_ratio(float(ratio_b) / 100.0)
            weights[left] = 1.0 - effective_b
            weights[right] = effective_b
    return tuple(float(value) for value in weights)


def estimate_base_filament_contributions(
    level: MeshLevel,
    palette_indices: np.ndarray,
    height_mm: float,
    mix_ratios_b: list[int] | tuple[int, ...] | None = None,
    secondary_mix_ratios_b: list[int] | tuple[int, ...] | None = None,
    output_mix_ratios_b: list[int] | tuple[int, ...] | None = None,
    *,
    surface_shell_enabled: bool = False,
    physical_hex: list[str] | tuple[str, ...] | None = None,
    part_id: int | None = None,
    adaptive_trees: Mapping[int, object] | None = None,
) -> tuple[float, float, float, float]:
    """Estimate F1..F4 shares from state-assigned surface area.

    This is deliberately labelled an estimate in the UI: infill, supports,
    purge/tower paths and slicer wall decisions are not represented by OBJ
    surface assignments.  It is nevertheless useful for detecting a palette
    whose dark base participates in most of the visible surface states.
    """

    indices = _validated_indices(level, palette_indices)
    height = float(height_mm)
    if not np.isfinite(height) or height <= 0.0:
        raise ValueError("height_mm must be positive")
    areas = np.asarray(level.areas_unit, dtype=np.float64)
    if areas.shape != (len(level.faces),):
        raise ValueError("areas_unit must contain one area per face")
    scope = _scope_mask(level, part_id)
    by_state, _adaptive = _state_area_distribution(
        level,
        indices,
        height,
        scope,
        adaptive_trees,
    )
    total = float(by_state.sum())
    if total <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)
    contributions = np.zeros(4, dtype=np.float64)
    for state, state_area in enumerate(by_state):
        if state_area <= 0.0:
            continue
        contributions += state_area * np.asarray(
            palette_state_base_weights(
                state,
                mix_ratios_b,
                secondary_mix_ratios_b,
                output_mix_ratios_b,
                surface_shell_enabled=surface_shell_enabled,
                physical_hex=physical_hex,
            )
        )
    contributions /= total
    return tuple(float(value) for value in contributions)


def focus_palette_state(
    result: ColorResult,
    level: MeshLevel,
    state: int,
    *,
    part_id: int | None = None,
    muted_rgb: tuple[float, float, float] = (0.075, 0.085, 0.10),
    retained_color: float = 0.10,
    accent_rgb: tuple[float, float, float] = (0.22, 0.88, 1.0),
    accent_mix: float = 0.28,
) -> ColorResult:
    """Return a display-only result that makes one palette state conspicuous.

    All non-selected faces are reduced to a dim shape-preserving neutral.  The
    selected state keeps most of its converted colour and receives a small
    cyan lift so even a true black filament remains visible.  Only
    ``target_face_rgb`` is replaced; state assignments and export metadata are
    retained by identity.
    """

    indices = _validated_indices(level, result.palette_indices)
    target = np.asarray(result.target_face_rgb, dtype=np.float64)
    if target.shape != (len(level.faces), 3):
        raise ValueError("target_face_rgb must contain one RGB value per face")
    selected_state = int(state)
    if not 0 <= selected_state < PALETTE_STATE_COUNT:
        raise ValueError(f"state must be between 0 and {PALETTE_STATE_COUNT - 1}")
    keep = float(retained_color)
    lift = float(accent_mix)
    if not 0.0 <= keep <= 1.0:
        raise ValueError("retained_color must be between 0 and 1")
    if not 0.0 <= lift <= 1.0:
        raise ValueError("accent_mix must be between 0 and 1")
    muted = np.asarray(muted_rgb, dtype=np.float64)
    accent = np.asarray(accent_rgb, dtype=np.float64)
    if muted.shape != (3,) or accent.shape != (3,):
        raise ValueError("display colors must be RGB triples")

    scope = _scope_mask(level, part_id)
    selected = scope & (indices == selected_state)
    focused = np.clip(muted[None, :] + target * keep, 0.0, 1.0)
    if bool(np.any(selected)):
        focused[selected] = np.clip(
            target[selected] * (1.0 - lift) + accent[None, :] * lift,
            0.0,
            1.0,
        )
    return replace(result, target_face_rgb=focused)


__all__ = [
    "PaletteUsage",
    "analyze_palette_usage",
    "estimate_base_filament_contributions",
    "focus_palette_state",
    "palette_state_base_weights",
]
