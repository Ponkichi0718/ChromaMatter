"""Deterministic helpers for discrete-state manual painting.

The editor does not paint arbitrary RGB values: every visible result must be a
real, enabled filament/palette state.  This module contains the geometry and
quantisation pieces used by :mod:`spectrum_mapper.paint` while deliberately
remaining independent from Tk and the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Iterable, Sequence

import numpy as np


class PaintToolError(ValueError):
    """Raised when a manual-paint planning input is invalid."""


@dataclass(frozen=True)
class SurfaceRegion:
    """A crease-bounded geodesic brush region.

    ``faces`` and ``distances_mm`` use matching positions and are ordered by
    increasing geodesic distance (then face ID).  Keeping the measured distance
    lets airbrush/smudge tools share exactly the same soft falloff.
    """

    faces: np.ndarray
    distances_mm: np.ndarray

    def __post_init__(self) -> None:
        faces = np.asarray(self.faces)
        distances = np.asarray(self.distances_mm)
        if faces.ndim != 1 or not np.issubdtype(faces.dtype, np.integer):
            raise PaintToolError("surface-region faces must be a 1D integer array")
        if distances.shape != faces.shape or not np.issubdtype(
            distances.dtype, np.floating
        ):
            raise PaintToolError(
                "surface-region distances must be a matching floating array"
            )
        if len(distances) and (
            not np.all(np.isfinite(distances)) or np.any(distances < 0.0)
        ):
            raise PaintToolError("surface-region distances must be finite and >= 0")


@dataclass(frozen=True)
class PaintPlan:
    """A non-mutating discrete palette-state proposal."""

    faces: np.ndarray
    states: np.ndarray

    def __post_init__(self) -> None:
        faces = np.asarray(self.faces)
        states = np.asarray(self.states)
        if faces.ndim != 1 or not np.issubdtype(faces.dtype, np.integer):
            raise PaintToolError("paint-plan faces must be a 1D integer array")
        if states.shape != faces.shape or not np.issubdtype(states.dtype, np.integer):
            raise PaintToolError("paint-plan states must be a matching integer array")


@dataclass(frozen=True)
class CreaseEdgeData:
    """World-space edge geometry for a visible crease overlay.

    Boundary entries use ``-1`` for the second face and ``True`` in
    ``boundary_mask``.  ``segments_unit`` can be projected by any renderer;
    the core intentionally does not assume a particular camera/canvas.
    """

    vertex_pairs: np.ndarray
    face_pairs: np.ndarray
    segments_unit: np.ndarray
    angles_degrees: np.ndarray
    boundary_mask: np.ndarray

    def __post_init__(self) -> None:
        vertex_pairs = np.asarray(self.vertex_pairs)
        face_pairs = np.asarray(self.face_pairs)
        segments = np.asarray(self.segments_unit)
        angles = np.asarray(self.angles_degrees)
        boundaries = np.asarray(self.boundary_mask)
        count = len(vertex_pairs)
        if vertex_pairs.shape != (count, 2) or not np.issubdtype(
            vertex_pairs.dtype, np.integer
        ):
            raise PaintToolError("crease vertex_pairs must have shape (E, 2)")
        if face_pairs.shape != (count, 2) or not np.issubdtype(
            face_pairs.dtype, np.integer
        ):
            raise PaintToolError("crease face_pairs must have shape (E, 2)")
        if segments.shape != (count, 2, 3):
            raise PaintToolError("crease segments_unit must have shape (E, 2, 3)")
        if angles.shape != (count,) or boundaries.shape != (count,):
            raise PaintToolError("crease angle/boundary arrays must match the edges")


def validate_strength(value: float, name: str = "strength") -> float:
    result = float(value)
    if not np.isfinite(result) or result < 0.0 or result > 1.0:
        raise PaintToolError(f"{name} must be in the 0..1 range")
    return result


AIRBRUSH_DAB_INTERVAL_SECONDS = 0.12


def airbrush_hold_dab_count(
    duration_seconds: float,
    *,
    interval_seconds: float = AIRBRUSH_DAB_INTERVAL_SECONDS,
    maximum: int = 64,
) -> int:
    """Return the time-based number of deposits for one pointer press.

    The first deposit happens immediately.  Later deposits are derived only
    from elapsed time, never from the number of pointer-motion events, so a
    stationary pen and mice with different event rates produce the same result.
    A finite cap prevents a forgotten press from turning into unbounded work.
    """

    duration = float(duration_seconds)
    interval = float(interval_seconds)
    limit = int(maximum)
    if not math.isfinite(duration) or duration < 0.0:
        raise PaintToolError("duration_seconds must be finite and >= 0")
    if not math.isfinite(interval) or interval <= 0.0:
        raise PaintToolError("interval_seconds must be finite and > 0")
    if limit < 1:
        raise PaintToolError("maximum must be positive")
    # The epsilon makes exact interval boundaries deterministic despite normal
    # binary floating-point representation (0.36 / 0.12, for example).
    return min(limit, 1 + int(math.floor((duration + interval * 1.0e-9) / interval)))


def airbrush_radius_scale(
    pressure: float,
    *,
    minimum: float = 0.35,
    gamma: float = 0.70,
) -> float:
    """Map normalized pen pressure to a readable airbrush radius multiplier."""

    value = validate_strength(pressure, "pressure")
    floor = float(minimum)
    exponent = float(gamma)
    if not math.isfinite(floor) or floor < 0.0 or floor > 1.0:
        raise PaintToolError("minimum must be in the 0..1 range")
    if not math.isfinite(exponent) or exponent <= 0.0:
        raise PaintToolError("gamma must be finite and > 0")
    return float(floor + (1.0 - floor) * value**exponent)


def accumulated_airbrush_deposit(
    falloff: np.ndarray | Sequence[float] | float,
    strength: float,
    pressure: float,
    dab_count: int,
) -> np.ndarray:
    """Accumulate repeated airbrush deposits without pointer-rate dependence.

    Repeated pigment uses the standard source-over recurrence
    ``1 - (1 - alpha) ** count``.  It grows monotonically while remaining in
    0..1 and therefore gives a held pen a natural gradual build-up.
    """

    profile = np.asarray(falloff, dtype=np.float64)
    if not np.all(np.isfinite(profile)) or np.any(profile < 0.0) or np.any(profile > 1.0):
        raise PaintToolError("falloff must contain finite values in the 0..1 range")
    amount = validate_strength(strength)
    pen_pressure = validate_strength(pressure, "pressure")
    count = int(dab_count)
    if count < 1:
        raise PaintToolError("dab_count must be positive")
    per_dab = np.clip(profile * amount * pen_pressure, 0.0, 1.0)
    return (1.0 - np.power(1.0 - per_dab, count)).astype(np.float32)


def airbrush_state_layers(
    source_state: int,
    target_state: int,
    palette_rgb: np.ndarray,
    enabled_states: Sequence[bool] | Sequence[int] | np.ndarray | None,
    *,
    strength: float,
    pressure: float,
    dab_count: int,
    layer_count: int = 16,
) -> tuple[tuple[float, int], ...]:
    """Quantize a soft radial airbrush profile into adaptive paint bands.

    Each returned ``(radius_fraction, state)`` entry is ordered outer-to-inner.
    Applying those entries successively to an adaptive subtriangle tree creates
    a circular falloff without exposing the source mesh's triangle footprint.
    Only enabled printable states are selected.
    """

    colors = np.asarray(palette_rgb, dtype=np.float64)
    if colors.ndim != 2 or colors.shape[1] != 3 or len(colors) < 1:
        raise PaintToolError("palette_rgb must have shape (S, 3)")
    if not np.all(np.isfinite(colors)):
        raise PaintToolError("palette_rgb must be finite")
    if float(colors.max(initial=0.0)) > 1.5:
        colors = colors / 255.0
    colors = np.clip(colors, 0.0, 1.0)
    source = int(source_state)
    target = int(target_state)
    if source < 0 or source >= len(colors) or target < 0 or target >= len(colors):
        raise PaintToolError("source/target state is outside palette_rgb")
    active = enabled_state_ids(enabled_states, len(colors)).astype(np.intp)
    if target not in set(int(value) for value in active):
        raise PaintToolError("target_state must be enabled")
    count = int(layer_count)
    if count < 2:
        raise PaintToolError("layer_count must be at least two")

    # Leave an extremely thin untouched rim and retain a non-zero innermost
    # radius so the centre of a stationary dab is always represented.
    radii = np.linspace(0.96, 0.04, count, dtype=np.float64)
    falloff = soft_falloff(radii, 1.0)
    deposits = accumulated_airbrush_deposit(
        falloff,
        strength,
        pressure,
        dab_count,
    ).astype(np.float64)
    source_rgb = colors[source]
    target_rgb = colors[target]
    active_rgb = colors[active]
    previous = source
    previous_distance = float(np.linalg.norm(source_rgb - target_rgb))
    result: list[tuple[float, int]] = []
    for radius, deposit in zip(radii, deposits, strict=True):
        mixed = source_rgb * (1.0 - float(deposit)) + target_rgb * float(deposit)
        distances = np.linalg.norm(active_rgb - mixed[None, :], axis=1)
        candidate = int(active[int(np.argmin(distances))])
        target_distance = float(np.linalg.norm(colors[candidate] - target_rgb))
        # A palette Voronoi boundary can occasionally select a colour farther
        # from the target.  Refuse that reversal so the visible rings always
        # progress monotonically toward the chosen paint colour.
        if target_distance > previous_distance + 1.0e-12:
            candidate = previous
            target_distance = previous_distance
        if candidate != previous:
            result.append((float(radius), candidate))
            previous = candidate
            previous_distance = target_distance
    return tuple(result)


def enabled_state_ids(
    enabled_states: Sequence[bool] | Sequence[int] | np.ndarray | None,
    state_count: int,
) -> np.ndarray:
    """Normalise a bool mask or an ID sequence into sorted unique state IDs."""

    count = int(state_count)
    if count < 1:
        raise PaintToolError("state_count must be positive")
    if enabled_states is None:
        return np.arange(count, dtype=np.int8)
    source = np.asarray(enabled_states)
    if source.ndim != 1:
        raise PaintToolError("enabled_states must be a 1D mask or ID sequence")
    if np.issubdtype(source.dtype, np.bool_):
        if len(source) != count:
            raise PaintToolError("enabled-state mask length does not match palette")
        result = np.flatnonzero(source)
    elif np.issubdtype(source.dtype, np.integer):
        result = np.unique(source.astype(np.int64, copy=False))
    else:
        raise PaintToolError("enabled_states must contain bools or integer IDs")
    if len(result) == 0:
        raise PaintToolError("at least one palette state must be enabled")
    if int(result[0]) < 0 or int(result[-1]) >= count:
        raise PaintToolError("enabled_states contains an out-of-range palette ID")
    return result.astype(np.int8, copy=False)


def surface_region(
    seed_face: int,
    radius_mm: float,
    neighbors: np.ndarray,
    edge_costs_mm: np.ndarray,
    *,
    distance_scale: float = 1.0,
    allowed_faces: np.ndarray | None = None,
    traversal_mask: np.ndarray | None = None,
    edge_crossable: np.ndarray | None = None,
    face_normals: np.ndarray | None = None,
    normal_valid: np.ndarray | None = None,
    minimum_normal_dot: float | None = None,
) -> SurfaceRegion:
    """Traverse a local surface without allocating arrays for the whole mesh.

    Boundary/non-manifold edges are represented by ``-1`` in ``neighbors``.
    ``traversal_mask`` is a transient visibility/selection guard in addition to
    the persistent ``allowed_faces`` mask.  Both the seed and every traversed
    face must pass it, so a visible front face cannot reach a hidden back face
    by walking around a thin fold.  ``edge_crossable`` can additionally block
    crease edges.  The sparse Dijkstra implementation matters for
    multi-million-face meshes because a brush dab normally touches only a tiny
    fraction of the model.
    """

    adjacent = np.asarray(neighbors)
    costs = np.asarray(edge_costs_mm, dtype=np.float64)
    if adjacent.ndim != 2 or adjacent.shape[1] != 3 or not np.issubdtype(
        adjacent.dtype, np.integer
    ):
        raise PaintToolError("neighbors must be an Mx3 integer array")
    if costs.shape != adjacent.shape:
        raise PaintToolError("edge_costs_mm must match neighbors")
    face_count = len(adjacent)
    seed = int(seed_face)
    if seed < 0 or seed >= face_count:
        raise PaintToolError("seed face is outside the mesh")
    radius = float(radius_mm)
    if not np.isfinite(radius) or radius < 0.0:
        raise PaintToolError("radius_mm must be finite and >= 0")
    scale = float(distance_scale)
    if not np.isfinite(scale) or scale <= 0.0:
        raise PaintToolError("distance_scale must be finite and > 0")

    if allowed_faces is None:
        allowed = None
    else:
        allowed = np.asarray(allowed_faces, dtype=bool)
        if allowed.shape != (face_count,):
            raise PaintToolError("allowed_faces does not match the mesh")
        if not bool(allowed[seed]):
            return SurfaceRegion(
                np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float32)
            )
    if traversal_mask is None:
        traversal = None
    else:
        traversal = np.asarray(traversal_mask, dtype=bool)
        if traversal.shape != (face_count,):
            raise PaintToolError("traversal_mask does not match the mesh")
        if not bool(traversal[seed]):
            return SurfaceRegion(
                np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float32)
            )
    if edge_crossable is None:
        crossable = None
    else:
        crossable = np.asarray(edge_crossable, dtype=bool)
        if crossable.shape != adjacent.shape:
            raise PaintToolError("edge_crossable must match neighbors")
    if minimum_normal_dot is None:
        normals = None
        valid_normals = None
    else:
        threshold = float(minimum_normal_dot)
        if not np.isfinite(threshold) or threshold < -1.0 or threshold > 1.0:
            raise PaintToolError("minimum_normal_dot must be in the -1..1 range")
        normals = np.asarray(face_normals, dtype=np.float64)
        valid_normals = np.asarray(normal_valid, dtype=bool)
        if normals.shape != (face_count, 3) or valid_normals.shape != (face_count,):
            raise PaintToolError("face normals do not match neighbors")

    # A dict is intentionally used instead of an M-face distance array.  It is
    # deterministic because the heap key is (distance, face ID), and it scales
    # with the brush footprint rather than total model size.
    best: dict[int, float] = {seed: 0.0}
    pending: list[tuple[float, int]] = [(0.0, seed)]
    ordered_faces: list[int] = []
    ordered_distances: list[float] = []
    while pending:
        distance, face = heapq.heappop(pending)
        if distance != best.get(face):
            continue
        if distance > radius:
            break
        ordered_faces.append(face)
        ordered_distances.append(distance)
        for slot in range(3):
            neighbor = int(adjacent[face, slot])
            if neighbor < 0:
                continue
            if allowed is not None and not bool(allowed[neighbor]):
                continue
            if traversal is not None and not bool(traversal[neighbor]):
                continue
            if crossable is not None and not bool(crossable[face, slot]):
                continue
            if (
                normals is not None
                and bool(valid_normals[face])
                and bool(valid_normals[neighbor])
                and float(np.dot(normals[face], normals[neighbor])) < threshold
            ):
                continue
            step = float(costs[face, slot]) * scale
            if not np.isfinite(step) or step < 0.0:
                continue
            candidate = distance + step
            if candidate > radius:
                continue
            previous = best.get(neighbor)
            if previous is None or candidate < previous:
                best[neighbor] = candidate
                heapq.heappush(pending, (candidate, neighbor))

    return SurfaceRegion(
        np.asarray(ordered_faces, dtype=np.int32),
        np.asarray(ordered_distances, dtype=np.float32),
    )


def multi_seed_surface_region(
    seed_faces: Sequence[int] | np.ndarray,
    radius_mm: float,
    neighbors: np.ndarray,
    edge_costs_mm: np.ndarray,
    **kwargs: object,
) -> SurfaceRegion:
    """Return distance to the nearest stroke dab in one sparse Dijkstra pass.

    This is the long-stroke counterpart of :func:`surface_region`: overlapping
    brush footprints do not multiply work or pigment, and duplicate pointer
    events have no effect.  The accepted keyword arguments are the same geometry
    guards as ``surface_region``.
    """

    adjacent = np.asarray(neighbors)
    costs = np.asarray(edge_costs_mm, dtype=np.float64)
    if adjacent.ndim != 2 or adjacent.shape[1] != 3 or not np.issubdtype(
        adjacent.dtype, np.integer
    ):
        raise PaintToolError("neighbors must be an Mx3 integer array")
    if costs.shape != adjacent.shape:
        raise PaintToolError("edge_costs_mm must match neighbors")
    seeds_source = np.asarray(seed_faces)
    if seeds_source.ndim != 1:
        raise PaintToolError("seed_faces must be a 1D integer array")
    if len(seeds_source) == 0:
        return SurfaceRegion(
            np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float32)
        )
    if not np.issubdtype(seeds_source.dtype, np.integer):
        raise PaintToolError("seed_faces must be a 1D integer array")
    seeds = np.unique(seeds_source.astype(np.int64, copy=False))
    if int(seeds[0]) < 0 or int(seeds[-1]) >= len(adjacent):
        raise PaintToolError("seed_faces contains a face outside the mesh")

    radius = float(radius_mm)
    if not np.isfinite(radius) or radius < 0.0:
        raise PaintToolError("radius_mm must be finite and >= 0")
    scale = float(kwargs.pop("distance_scale", 1.0))
    if not np.isfinite(scale) or scale <= 0.0:
        raise PaintToolError("distance_scale must be finite and > 0")
    allowed_value = kwargs.pop("allowed_faces", None)
    allowed = (
        None
        if allowed_value is None
        else np.asarray(allowed_value, dtype=bool)
    )
    if allowed is not None and allowed.shape != (len(adjacent),):
        raise PaintToolError("allowed_faces does not match the mesh")
    traversal_value = kwargs.pop("traversal_mask", None)
    traversal = (
        None
        if traversal_value is None
        else np.asarray(traversal_value, dtype=bool)
    )
    if traversal is not None and traversal.shape != (len(adjacent),):
        raise PaintToolError("traversal_mask does not match the mesh")
    crossable_value = kwargs.pop("edge_crossable", None)
    crossable = (
        None
        if crossable_value is None
        else np.asarray(crossable_value, dtype=bool)
    )
    if crossable is not None and crossable.shape != adjacent.shape:
        raise PaintToolError("edge_crossable must match neighbors")
    normals_value = kwargs.pop("face_normals", None)
    valid_normals_value = kwargs.pop("normal_valid", None)
    minimum_dot_value = kwargs.pop("minimum_normal_dot", None)
    if kwargs:
        raise PaintToolError(f"unsupported surface option: {next(iter(kwargs))}")
    if minimum_dot_value is None:
        normals = None
        valid_normals = None
        threshold = None
    else:
        threshold = float(minimum_dot_value)
        normals = np.asarray(normals_value, dtype=np.float64)
        valid_normals = np.asarray(valid_normals_value, dtype=bool)
        if (
            not np.isfinite(threshold)
            or threshold < -1.0
            or threshold > 1.0
            or normals.shape != (len(adjacent), 3)
            or valid_normals.shape != (len(adjacent),)
        ):
            raise PaintToolError("face normals/minimum dot are invalid")

    if allowed is not None:
        seeds = seeds[allowed[seeds]]
    if traversal is not None:
        seeds = seeds[traversal[seeds]]
    if len(seeds) == 0:
        return SurfaceRegion(
            np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float32)
        )
    best: dict[int, float] = {int(seed): 0.0 for seed in seeds}
    pending: list[tuple[float, int]] = [(0.0, int(seed)) for seed in seeds]
    heapq.heapify(pending)
    ordered_faces: list[int] = []
    ordered_distances: list[float] = []
    while pending:
        distance, face = heapq.heappop(pending)
        if distance != best.get(face):
            continue
        if distance > radius:
            break
        ordered_faces.append(face)
        ordered_distances.append(distance)
        for slot in range(3):
            neighbor = int(adjacent[face, slot])
            if neighbor < 0:
                continue
            if allowed is not None and not bool(allowed[neighbor]):
                continue
            if traversal is not None and not bool(traversal[neighbor]):
                continue
            if crossable is not None and not bool(crossable[face, slot]):
                continue
            if (
                threshold is not None
                and bool(valid_normals[face])
                and bool(valid_normals[neighbor])
                and float(np.dot(normals[face], normals[neighbor])) < threshold
            ):
                continue
            step = float(costs[face, slot]) * scale
            if not np.isfinite(step) or step < 0.0:
                continue
            candidate = distance + step
            if candidate > radius:
                continue
            previous = best.get(neighbor)
            if previous is None or candidate < previous:
                best[neighbor] = candidate
                heapq.heappush(pending, (candidate, neighbor))
    return SurfaceRegion(
        np.asarray(ordered_faces, dtype=np.int32),
        np.asarray(ordered_distances, dtype=np.float32),
    )


def soft_falloff(distances_mm: np.ndarray, radius_mm: float) -> np.ndarray:
    """Return a smooth, compact radial falloff in the 0..1 range."""

    distances = np.asarray(distances_mm, dtype=np.float64)
    radius = float(radius_mm)
    if distances.ndim != 1 or not np.all(np.isfinite(distances)):
        raise PaintToolError("distances_mm must be a finite 1D array")
    if not np.isfinite(radius) or radius < 0.0:
        raise PaintToolError("radius_mm must be finite and >= 0")
    if radius == 0.0:
        return np.where(distances <= 1e-12, 1.0, 0.0).astype(np.float32)
    x = np.clip(1.0 - distances / radius, 0.0, 1.0)
    # cubic smoothstep gives a soft edge without a hard linear ring
    return (x * x * (3.0 - 2.0 * x)).astype(np.float32)


def deterministic_thresholds(
    face_ids: np.ndarray,
    source_states: np.ndarray,
    target_state: int,
) -> np.ndarray:
    """Stable per-face thresholds for discrete airbrush coverage.

    Staggering thresholds prevents a low-strength airbrush from producing one
    conspicuous polygon ring.  Integer hashing avoids Python's salted hash and
    therefore produces identical plans on every run/platform.
    """

    faces = np.asarray(face_ids, dtype=np.uint64)
    sources = np.asarray(source_states, dtype=np.uint64)
    if faces.shape != sources.shape or faces.ndim != 1:
        raise PaintToolError("face_ids and source_states must be matching vectors")
    target = int(target_state)
    target_term = np.uint64(
        ((target + 1) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    )
    with np.errstate(over="ignore"):
        x = faces + np.uint64(0x9E3779B97F4A7C15)
        x ^= (sources + np.uint64(1)) * np.uint64(0xBF58476D1CE4E5B9)
        x ^= target_term
        x ^= x >> np.uint64(30)
        x *= np.uint64(0xBF58476D1CE4E5B9)
        x ^= x >> np.uint64(27)
        x *= np.uint64(0x94D049BB133111EB)
        x ^= x >> np.uint64(31)
    unit = ((x >> np.uint64(40)) & np.uint64(0xFFFFFF)).astype(np.float64)
    unit /= float(1 << 24)
    # Cover the full slider range: even a 5% released stroke changes roughly
    # five percent of centre faces instead of making the low settings dead.
    # A tiny positive floor avoids an exact-zero threshold.
    epsilon = 1.0 / float(1 << 25)
    return (epsilon + unit * (1.0 - epsilon)).astype(np.float32)


def merge_airbrush_regions(
    regions: Iterable[tuple[SurfaceRegion, float]],
    radius_mm: float,
    strength: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Combine stroke dabs by maximum deposit, independent of event density."""

    amount = validate_strength(strength)
    merged: dict[int, float] = {}
    for region, pressure_value in regions:
        pressure = validate_strength(pressure_value, "pressure")
        if pressure == 0.0 or amount == 0.0 or len(region.faces) == 0:
            continue
        deposits = soft_falloff(region.distances_mm, radius_mm) * amount * pressure
        for face, deposit in zip(region.faces, deposits, strict=True):
            value = float(deposit)
            key = int(face)
            if value > merged.get(key, 0.0):
                merged[key] = value
    if not merged:
        return np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float32)
    faces = np.fromiter(sorted(merged), dtype=np.int32)
    deposits = np.asarray([merged[int(face)] for face in faces], dtype=np.float32)
    return faces, deposits


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    values = np.asarray(rgb, dtype=np.float64)
    linear = np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )
    xyz = linear @ np.asarray(
        (
            (0.4124564, 0.3575761, 0.1804375),
            (0.2126729, 0.7151522, 0.0721750),
            (0.0193339, 0.1191920, 0.9503041),
        ),
        dtype=np.float64,
    ).T
    xyz /= np.asarray((0.95047, 1.0, 1.08883), dtype=np.float64)
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


def _nearest_enabled_rgb(
    rgb: np.ndarray,
    palette_rgb: np.ndarray,
    active_ids: np.ndarray,
    *,
    chunk_size: int = 65_536,
) -> np.ndarray:
    result = np.empty(len(rgb), dtype=np.int8)
    candidates = _srgb_to_lab(palette_rgb[active_ids])
    for start in range(0, len(rgb), chunk_size):
        stop = min(len(rgb), start + chunk_size)
        sample_lab = _srgb_to_lab(rgb[start:stop])
        delta = sample_lab[:, None, :] - candidates[None, :, :]
        distances = np.einsum("ijk,ijk->ij", delta, delta, optimize=True)
        result[start:stop] = active_ids[np.argmin(distances, axis=1)]
    return result


def plan_smudge(
    region: SurfaceRegion,
    current_states: np.ndarray,
    neighbors: np.ndarray,
    palette_rgb: np.ndarray,
    enabled_states: Sequence[bool] | Sequence[int] | np.ndarray | None,
    strength: float,
    *,
    pressure: float = 1.0,
    radius_mm: float,
    allowed_faces: np.ndarray | None = None,
    edge_crossable: np.ndarray | None = None,
    source_state: int | None = None,
) -> PaintPlan:
    """Diffuse neighbouring/current colours, then quantise to enabled states.

    The calculation uses a snapshot, not in-place propagation, so face order
    cannot change the result.  Only enabled palette IDs can be emitted.
    """

    labels = np.asarray(current_states)
    adjacent = np.asarray(neighbors)
    palette = np.asarray(palette_rgb, dtype=np.float64)
    if labels.ndim != 1 or not np.issubdtype(labels.dtype, np.integer):
        raise PaintToolError("current_states must be a 1D integer array")
    if adjacent.shape != (len(labels), 3):
        raise PaintToolError("neighbors must have shape (len(current_states), 3)")
    if palette.ndim != 2 or palette.shape[1] != 3 or len(palette) < 1:
        raise PaintToolError("palette_rgb must be an Nx3 table")
    if not np.all(np.isfinite(palette)) or np.any(palette < 0.0) or np.any(palette > 1.0):
        raise PaintToolError("palette_rgb values must be finite and in 0..1")
    if len(labels) and (int(labels.min()) < 0 or int(labels.max()) >= len(palette)):
        raise PaintToolError("current_states references a missing palette state")
    active = enabled_state_ids(enabled_states, len(palette))
    amount = validate_strength(strength)
    pen_pressure = validate_strength(pressure, "pressure")
    faces = np.asarray(region.faces, dtype=np.int32)
    if len(faces) == 0 or amount == 0.0 or pen_pressure == 0.0:
        return PaintPlan(np.empty(0, dtype=np.int32), np.empty(0, dtype=np.int8))

    if allowed_faces is None:
        allowed = np.ones(len(labels), dtype=bool)
    else:
        allowed = np.asarray(allowed_faces, dtype=bool)
        if allowed.shape != labels.shape:
            raise PaintToolError("allowed_faces does not match current_states")
    if edge_crossable is None:
        crossable_rows = np.ones((len(faces), 3), dtype=bool)
    else:
        crossable = np.asarray(edge_crossable, dtype=bool)
        if crossable.shape == adjacent.shape:
            crossable_rows = crossable[faces]
        elif crossable.shape == (len(faces), 3):
            crossable_rows = crossable
        else:
            raise PaintToolError("edge_crossable does not match neighbors/region")

    neighbor_ids = adjacent[faces]
    valid = neighbor_ids >= 0
    safe_ids = np.where(valid, neighbor_ids, 0)
    valid &= allowed[safe_ids]
    valid &= crossable_rows
    neighbor_colors = palette[labels[safe_ids]]
    neighbor_colors *= valid[..., None]
    neighbor_count = valid.sum(axis=1)
    own_colors = palette[labels[faces]]
    # Isolated faces retain their current colour. Otherwise the guide begins at
    # the average of its edge-connected neighbours.
    local_mean = np.where(
        (neighbor_count > 0)[:, None],
        neighbor_colors.sum(axis=1) / np.maximum(neighbor_count[:, None], 1.0),
        own_colors,
    )
    if source_state is not None:
        source = int(source_state)
        if source < 0 or source >= len(palette):
            raise PaintToolError("source_state references a missing palette state")
        # A smudge stroke drags the colour under its seed while still consulting
        # the local neighbourhood.  This remains useful even for a two-state
        # palette, where symmetric averaging would otherwise quantise to a no-op.
        local_mean = palette[source] * 0.90 + local_mean * 0.10
    # A perceptual "strength" control needs to remain useful after discrete
    # quantisation.  The ease-out curve makes the middle of the slider strong
    # enough to transport colour across a two-state boundary while preserving
    # fine control near zero.
    effective_amount = 1.0 - (1.0 - amount) ** 2
    alpha = (
        soft_falloff(region.distances_mm, radius_mm).astype(np.float64)
        * effective_amount
        * pen_pressure
    )
    blended = own_colors * (1.0 - alpha[:, None]) + local_mean * alpha[:, None]
    states = _nearest_enabled_rgb(blended, palette, active)
    changed = states != labels[faces]
    return PaintPlan(faces[changed], states[changed])
