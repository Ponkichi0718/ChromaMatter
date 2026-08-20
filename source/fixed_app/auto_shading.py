"""Automatic intra-face colour shading using Orca-compatible paint trees.

The normal mapper selects one Full Spectrum state for each source triangle.
This module keeps the source mesh unchanged, samples the tone-adjusted vertex
colour inside triangles, and emits sparse :class:`smooth_paint.PaintNode`
trees only where a palette boundary crosses a face.  Automatic trees are kept
shallower than the manual brush trees and are bounded by physical size and a
global leaf budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Iterable

import numpy as np

import smooth_paint


_AUTO_MAX_DEPTH = 3
_PROBE_BARYCENTRIC = np.asarray(
    (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.5, 0.5, 0.0),
        (0.0, 0.5, 0.5),
        (0.5, 0.0, 0.5),
        (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0),
    ),
    dtype=np.float64,
)


class AutoShadingError(ValueError):
    """Raised for invalid automatic-shading input or limits."""


@dataclass(frozen=True, slots=True)
class AutoShadingOptions:
    """Quality and resource limits for automatic paint-tree generation.

    ``units_to_mm`` converts ``vertices`` into millimetres.  The mapper's
    normalized ``vertices_unit`` therefore uses the requested model height.
    A triangle is subdivided while its longest root edge is larger than
    ``min_edge_mm``, but never past ``max_depth``.
    """

    units_to_mm: float = 1.0
    min_edge_mm: float = 0.30
    max_depth: int = 2
    max_adaptive_faces: int = 75_000
    max_total_leaves: int = 600_000
    min_variation_delta_e: float = 2.0
    dither: bool = False
    dither_seed: int = 0
    batch_faces: int = 4096
    enabled_states: tuple[bool, ...] | None = None
    # Appended to preserve the positional meaning of every pre-existing
    # option.  Zero is nearest-colour quantization; one is the original full
    # deterministic two-colour dither.
    dither_strength: float = 1.0


@dataclass(frozen=True, slots=True)
class AutoShadingResult:
    """Sparse automatic trees plus deterministic budget statistics."""

    trees: dict[int, smooth_paint.PaintNode]
    candidate_faces: int
    selected_faces: int
    adaptive_faces: int
    total_leaves: int
    reserved_leaves: int
    skipped_small_faces: int
    budget_limited: bool


def _as_rgb(values: np.ndarray, label: str) -> np.ndarray:
    rgb = np.asarray(values, dtype=np.float64)
    if rgb.ndim != 2 or rgb.shape[1] != 3 or not bool(np.all(np.isfinite(rgb))):
        raise AutoShadingError(f"{label} must be a finite Nx3 RGB array")
    minimum = float(rgb.min(initial=0.0))
    maximum = float(rgb.max(initial=0.0))
    if minimum < -1.0e-9 or maximum > 255.0 + 1.0e-9:
        raise AutoShadingError(f"{label} RGB values must be in 0..1 or 0..255")
    if maximum > 1.5:
        rgb = rgb / 255.0
    return np.clip(rgb, 0.0, 1.0)


def srgb_to_lab(values: np.ndarray) -> np.ndarray:
    """Convert an arbitrary ``...x3`` sRGB array to CIE Lab (D65)."""

    rgb = np.asarray(values, dtype=np.float64)
    if rgb.shape[-1:] != (3,) or not bool(np.all(np.isfinite(rgb))):
        raise AutoShadingError("sRGB values must be a finite ...x3 array")
    if float(rgb.max(initial=0.0)) > 1.5:
        rgb = rgb / 255.0
    rgb = np.clip(rgb, 0.0, 1.0)
    linear = np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )
    matrix = np.asarray(
        (
            (0.4124564, 0.3575761, 0.1804375),
            (0.2126729, 0.7151522, 0.0721750),
            (0.0193339, 0.1191920, 0.9503041),
        ),
        dtype=np.float64,
    )
    xyz = linear @ matrix.T
    xyz = xyz / np.asarray((0.95047, 1.0, 1.08883), dtype=np.float64)
    delta = 6.0 / 29.0
    transformed = np.where(
        xyz > delta**3,
        np.cbrt(xyz),
        xyz / (3.0 * delta**2) + 4.0 / 29.0,
    )
    result = np.empty_like(transformed)
    result[..., 0] = 116.0 * transformed[..., 1] - 16.0
    result[..., 1] = 500.0 * (transformed[..., 0] - transformed[..., 1])
    result[..., 2] = 200.0 * (transformed[..., 1] - transformed[..., 2])
    return result


def _validate_options(options: AutoShadingOptions, state_count: int) -> np.ndarray:
    scale = float(options.units_to_mm)
    minimum_edge = float(options.min_edge_mm)
    variation = float(options.min_variation_delta_e)
    dither_strength = float(options.dither_strength)
    if not math.isfinite(scale) or scale <= 0.0:
        raise AutoShadingError("units_to_mm must be finite and positive")
    if not math.isfinite(minimum_edge) or minimum_edge <= 0.0:
        raise AutoShadingError("min_edge_mm must be finite and positive")
    if not math.isfinite(variation) or variation < 0.0:
        raise AutoShadingError("min_variation_delta_e must be finite and non-negative")
    if (
        not math.isfinite(dither_strength)
        or dither_strength < 0.0
        or dither_strength > 1.0
    ):
        raise AutoShadingError("dither_strength must be finite and in 0..1")
    if int(options.max_depth) not in (1, 2, 3):
        raise AutoShadingError("automatic max_depth must be 1, 2, or 3")
    if int(options.max_adaptive_faces) < 0:
        raise AutoShadingError("max_adaptive_faces must be non-negative")
    if int(options.max_total_leaves) < 0:
        raise AutoShadingError("max_total_leaves must be non-negative")
    if int(options.batch_faces) <= 0:
        raise AutoShadingError("batch_faces must be positive")
    if options.enabled_states is None:
        enabled = np.ones(state_count, dtype=bool)
    else:
        enabled = np.asarray(options.enabled_states, dtype=bool)
        if enabled.shape != (state_count,):
            raise AutoShadingError(
                f"enabled_states must contain exactly {state_count} values"
            )
    if not bool(np.any(enabled)):
        raise AutoShadingError("at least one palette state must be enabled")
    return enabled


def _nearest_states(lab: np.ndarray, active_lab: np.ndarray, active_ids: np.ndarray) -> np.ndarray:
    flat = np.asarray(lab, dtype=np.float64).reshape(-1, 3)
    difference = flat[:, None, :] - active_lab[None, :, :]
    distance_sq = np.einsum("nki,nki->nk", difference, difference, optimize=True)
    nearest = np.argmin(distance_sq, axis=1)
    return active_ids[nearest].reshape(lab.shape[:-1])


@lru_cache(maxsize=3)
def _leaf_barycentric_centroids(depth: int) -> np.ndarray:
    triangles = [np.eye(3, dtype=np.float64)]
    for _ in range(int(depth)):
        next_triangles: list[np.ndarray] = []
        for triangle in triangles:
            next_triangles.extend(smooth_paint.subdivide_triangle(triangle))
        triangles = next_triangles
    output = np.asarray([triangle.mean(axis=0) for triangle in triangles])
    output.setflags(write=False)
    return output


def _tree_from_leaf_states(states: np.ndarray, depth: int) -> smooth_paint.PaintNode:
    values = np.asarray(states, dtype=np.int16)
    expected = 4 ** int(depth)
    if values.shape != (expected,):
        raise AutoShadingError(
            f"depth {depth} requires {expected} leaf states, got {values.shape}"
        )

    def build(start: int, count: int, remaining: int) -> smooth_paint.PaintNode:
        first = int(values[start])
        if bool(np.all(values[start : start + count] == first)):
            return smooth_paint.PaintNode(first)
        if remaining <= 0:
            return smooth_paint.PaintNode(first)
        child_count = count // 4
        children = tuple(
            build(start + child * child_count, child_count, remaining - 1)
            for child in range(4)
        )
        node = smooth_paint.PaintNode.branch(children, split_sides=3)
        node.collapse()
        return node

    return build(0, expected, int(depth))


def _hash_thresholds(
    face_indices: np.ndarray,
    leaf_count: int,
    seed: int,
) -> np.ndarray:
    faces = np.asarray(face_indices, dtype=np.uint64)[:, None]
    leaves = np.arange(int(leaf_count), dtype=np.uint64)[None, :]
    mask = np.uint64(0xFFFFFFFFFFFFFFFF)
    with np.errstate(over="ignore"):
        values = (
            faces * np.uint64(0x9E3779B185EBCA87)
            + leaves * np.uint64(0xD1B54A32D192ED03)
            + np.uint64(int(seed) & int(mask))
        )
        values ^= values >> np.uint64(30)
        values *= np.uint64(0xBF58476D1CE4E5B9)
        values ^= values >> np.uint64(27)
        values *= np.uint64(0x94D049BB133111EB)
        values ^= values >> np.uint64(31)
    return (values >> np.uint64(11)).astype(np.float64) * (1.0 / 2.0**53)


def _dithered_states(
    target_lab: np.ndarray,
    active_lab: np.ndarray,
    active_ids: np.ndarray,
    face_indices: np.ndarray,
    seed: int,
    strength: float = 1.0,
) -> np.ndarray:
    face_count, leaf_count, _channels = target_lab.shape
    flat = target_lab.reshape(-1, 3)
    difference = flat[:, None, :] - active_lab[None, :, :]
    distance_sq = np.einsum("nki,nki->nk", difference, difference, optimize=True)
    if len(active_ids) == 1:
        return np.full((face_count, leaf_count), int(active_ids[0]), dtype=np.int16)
    order = np.argsort(distance_sq, axis=1, kind="stable")[:, :2]
    first_id = active_ids[order[:, 0]]
    second_id = active_ids[order[:, 1]]
    first_lab = active_lab[order[:, 0]]
    second_lab = active_lab[order[:, 1]]
    axis = second_lab - first_lab
    denominator = np.einsum("ni,ni->n", axis, axis, optimize=True)
    numerator = np.einsum("ni,ni->n", flat - first_lab, axis, optimize=True)
    amount = np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator),
        where=denominator > 1.0e-12,
    )
    # Reuse one stable threshold field for every strength.  Scaling only the
    # second-colour probability makes the result monotonic: a leaf enabled at
    # strength S remains enabled for every greater strength.
    amount = (
        np.clip(amount, 0.0, 1.0).reshape(face_count, leaf_count)
        * float(strength)
    )
    thresholds = _hash_thresholds(face_indices, leaf_count, seed)
    first = first_id.reshape(face_count, leaf_count)
    second = second_id.reshape(face_count, leaf_count)
    return np.where(thresholds < amount, second, first).astype(np.int16, copy=False)


def _face_max_edges_mm(
    faces: np.ndarray,
    vertices: np.ndarray,
    units_to_mm: float,
) -> np.ndarray:
    geometry = vertices[faces, :3] * float(units_to_mm)
    edge_ab = geometry[:, 1] - geometry[:, 0]
    edge_bc = geometry[:, 2] - geometry[:, 1]
    edge_ca = geometry[:, 0] - geometry[:, 2]
    squared = np.stack(
        (
            np.einsum("ni,ni->n", edge_ab, edge_ab, optimize=True),
            np.einsum("ni,ni->n", edge_bc, edge_bc, optimize=True),
            np.einsum("ni,ni->n", edge_ca, edge_ca, optimize=True),
        ),
        axis=1,
    )
    return np.sqrt(np.max(squared, axis=1))


def generate_auto_shading(
    faces: np.ndarray,
    vertices: np.ndarray,
    tone_vertex_rgb: np.ndarray,
    current_face_states: np.ndarray,
    palette_rgb: np.ndarray,
    *,
    options: AutoShadingOptions | None = None,
    face_mask: np.ndarray | Iterable[bool] | None = None,
) -> AutoShadingResult:
    """Generate sparse Orca paint trees for intra-triangle colour changes.

    The function is deterministic and does not mutate any input.  Returned
    trees contain four-way midpoint subdivisions only, are collapsed whenever
    a branch becomes uniform, and never exceed automatic depth three.
    """

    settings = options or AutoShadingOptions()
    face_values = np.asarray(faces)
    vertex_values = np.asarray(vertices, dtype=np.float64)
    if face_values.ndim != 2 or face_values.shape[1] != 3:
        raise AutoShadingError("faces must be an Fx3 index array")
    if not np.issubdtype(face_values.dtype, np.integer):
        if not bool(np.all(np.equal(face_values, np.floor(face_values)))):
            raise AutoShadingError("faces contain a non-integer index")
    face_values = face_values.astype(np.int64, copy=False)
    if vertex_values.ndim != 2 or vertex_values.shape[1] < 3:
        raise AutoShadingError("vertices must be a finite VxD array with D >= 3")
    if not bool(np.all(np.isfinite(vertex_values))):
        raise AutoShadingError("vertices contain a non-finite coordinate")
    if len(face_values) and (
        int(face_values.min()) < 0 or int(face_values.max()) >= len(vertex_values)
    ):
        raise AutoShadingError("faces contain an out-of-range vertex index")

    tone_rgb = _as_rgb(tone_vertex_rgb, "tone_vertex_rgb")
    palette = _as_rgb(palette_rgb, "palette_rgb")
    if len(tone_rgb) != len(vertex_values):
        raise AutoShadingError("tone_vertex_rgb count must match vertices")
    if len(palette) < 1 or len(palette) > smooth_paint.STATE_COUNT:
        raise AutoShadingError(
            f"palette_rgb must contain 1..{smooth_paint.STATE_COUNT} states"
        )
    states = np.asarray(current_face_states)
    if states.shape != (len(face_values),):
        raise AutoShadingError("current_face_states must contain one state per face")
    if len(states) and (
        int(states.min()) < 0 or int(states.max()) >= len(palette)
    ):
        raise AutoShadingError("current_face_states contain an invalid palette state")
    states = states.astype(np.int16, copy=False)
    enabled = _validate_options(settings, len(palette))
    dither_strength = float(settings.dither_strength)
    dither_active = bool(settings.dither) and dither_strength > 0.0
    active_ids = np.flatnonzero(enabled).astype(np.int16)
    palette_lab = srgb_to_lab(palette)
    active_lab = palette_lab[active_ids]

    if face_mask is None:
        scope = np.ones(len(face_values), dtype=bool)
    else:
        scope = np.asarray(face_mask, dtype=bool)
        if scope.shape != (len(face_values),):
            raise AutoShadingError("face_mask must contain one value per face")

    if len(face_values) == 0 or int(settings.max_adaptive_faces) == 0:
        return AutoShadingResult({}, 0, 0, 0, 0, 0, 0, bool(len(face_values)))

    maximum_edges = _face_max_edges_mm(
        face_values,
        vertex_values,
        float(settings.units_to_mm),
    )
    physically_eligible = maximum_edges > float(settings.min_edge_mm)
    skipped_small = int(np.count_nonzero(scope & ~physically_eligible))

    candidate_parts: list[np.ndarray] = []
    score_parts: list[np.ndarray] = []
    batch = int(settings.batch_faces)
    for start in range(0, len(face_values), batch):
        stop = min(len(face_values), start + batch)
        local_scope = scope[start:stop] & physically_eligible[start:stop]
        if not bool(np.any(local_scope)):
            continue
        local_faces = face_values[start:stop]
        face_rgb = tone_rgb[local_faces]
        probe_rgb = np.einsum(
            "pk,fkc->fpc",
            _PROBE_BARYCENTRIC,
            face_rgb,
            optimize=True,
        )
        probe_lab = srgb_to_lab(probe_rgb)
        probe_states = _nearest_states(probe_lab, active_lab, active_ids)
        state_boundary = np.min(probe_states, axis=1) != np.max(probe_states, axis=1)
        spread = np.linalg.norm(
            np.max(probe_lab, axis=1) - np.min(probe_lab, axis=1),
            axis=1,
        )
        candidate = state_boundary
        if dither_active:
            candidate = candidate | (
                spread >= float(settings.min_variation_delta_e)
            )
        candidate &= local_scope
        local_indices = np.flatnonzero(candidate)
        if len(local_indices) == 0:
            continue

        # Prefer faces with a strong continuous colour span and with a large
        # improvement over their current root state.  Index is the stable tie
        # break applied after all chunks have been joined.
        center_lab = probe_lab[:, -1]
        root_error = np.linalg.norm(center_lab - palette_lab[states[start:stop]], axis=1)
        nearest_center = _nearest_states(center_lab, active_lab, active_ids)
        best_error = np.linalg.norm(center_lab - palette_lab[nearest_center], axis=1)
        score = spread + np.maximum(root_error - best_error, 0.0)
        candidate_parts.append(local_indices.astype(np.int64) + start)
        score_parts.append(score[local_indices])

    if not candidate_parts:
        return AutoShadingResult({}, 0, 0, 0, 0, 0, skipped_small, False)

    candidate_indices = np.concatenate(candidate_parts)
    candidate_scores = np.concatenate(score_parts)
    candidate_count = int(len(candidate_indices))
    priority_order = np.lexsort((candidate_indices, -candidate_scores))
    candidate_indices = candidate_indices[priority_order]

    face_limit = int(settings.max_adaptive_faces)
    face_limited = candidate_count > face_limit
    if face_limited:
        candidate_indices = candidate_indices[:face_limit]

    ratios = maximum_edges[candidate_indices] / float(settings.min_edge_mm)
    desired_depths = np.ceil(np.log2(np.maximum(ratios, 1.0))).astype(np.int8)
    desired_depths = np.clip(desired_depths, 1, int(settings.max_depth))

    selected_faces: list[int] = []
    selected_depths: list[int] = []
    reserved_leaves = 0
    leaf_limit = int(settings.max_total_leaves)
    leaf_limited = False
    for raw_face, raw_depth in zip(candidate_indices, desired_depths, strict=True):
        depth = int(raw_depth)
        while depth >= 1 and reserved_leaves + 4**depth > leaf_limit:
            depth -= 1
        if depth < 1:
            leaf_limited = True
            continue
        selected_faces.append(int(raw_face))
        selected_depths.append(depth)
        reserved_leaves += 4**depth

    trees: dict[int, smooth_paint.PaintNode] = {}
    selected_array = np.asarray(selected_faces, dtype=np.int64)
    depths_array = np.asarray(selected_depths, dtype=np.int8)
    for depth in range(1, int(settings.max_depth) + 1):
        depth_faces = selected_array[depths_array == depth]
        if len(depth_faces) == 0:
            continue
        barycentric = _leaf_barycentric_centroids(depth)
        leaf_count = len(barycentric)
        for start in range(0, len(depth_faces), batch):
            current_faces = depth_faces[start : start + batch]
            face_rgb = tone_rgb[face_values[current_faces]]
            leaf_rgb = np.einsum(
                "lk,fkc->flc",
                barycentric,
                face_rgb,
                optimize=True,
            )
            leaf_lab = srgb_to_lab(leaf_rgb)
            if dither_active:
                leaf_states = _dithered_states(
                    leaf_lab,
                    active_lab,
                    active_ids,
                    current_faces,
                    int(settings.dither_seed),
                    dither_strength,
                )
            else:
                leaf_states = _nearest_states(
                    leaf_lab,
                    active_lab,
                    active_ids,
                ).astype(np.int16, copy=False)
            for offset, raw_face in enumerate(current_faces):
                node = _tree_from_leaf_states(leaf_states[offset], depth)
                # A uniform result belongs in the ordinary face-state array;
                # retaining it in the sparse tree store would only waste GPU
                # and 3MF metadata.  Automatic shading owns mixed roots only.
                if not node.is_leaf:
                    trees[int(raw_face)] = node

    total_leaves = int(sum(node.leaf_count() for node in trees.values()))
    return AutoShadingResult(
        trees=trees,
        candidate_faces=candidate_count,
        selected_faces=len(selected_faces),
        adaptive_faces=len(trees),
        total_leaves=total_leaves,
        reserved_leaves=reserved_leaves,
        skipped_small_faces=skipped_small,
        budget_limited=bool(face_limited or leaf_limited),
    )


__all__ = [
    "AutoShadingError",
    "AutoShadingOptions",
    "AutoShadingResult",
    "generate_auto_shading",
    "srgb_to_lab",
]
