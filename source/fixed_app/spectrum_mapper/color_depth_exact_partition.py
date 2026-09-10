"""Exact TetGen/level-set partition provider for ColorDepth Lab.

This module is the production implementation of the lazy provider contract in
``color_depth_head_geometry``.  It has no model-specific paths, state tables,
or precomputed masks.  Given a validated visible source surface and explicit
ordered recipes it:

* preserves the source PLC boundary with TetGen;
* completes labels for any coplanar boundary subtriangles;
* face-cone refines boundary tetrahedra carrying conflicting target labels;
* inserts an interior centroid when an otherwise all-outer tetrahedron hides a
  true depth sample beyond the requested threshold;
* constructs closest-surface owner and distance fields;
* stratifies the complete tetrahedral complex at every distinct requested
  outer depth, so per-target thickness changes still share one exact global
  face/edge registry instead of cutting adjacent owners independently;
* derives a one-edge-ring unsafe source mask from true interface-distance
  error and changes those complete owner columns to outer-only material; and
* directly joins every generated threshold triangle to its two final child
  cells before certifying the array contract.

The output remains uncalibrated and SLICE ONLY.  A finite backing/core recipe
requires another conforming threshold and is rejected rather than silently
approximated by cell centroids.
"""

from __future__ import annotations

import hashlib
import math
import time
from typing import Callable, Mapping

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from .color_depth import ColorDepthRecipe
from .color_depth_head_geometry import (
    ColorDepthSourceSurface,
    ConformingColorDepthPartition,
)


COLOR_DEPTH_EXACT_PARTITION_SCHEMA = (
    "tripo-spectrum-mapper.color-depth.exact-partition.experimental.v1"
)
_TET_FACES = np.asarray(
    ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)), dtype=np.int32
)
_TET_EDGES = np.asarray(
    ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
    dtype=np.int32,
)
_BOUNDARY_TRANSFER_TOLERANCE_MM = 1e-7
_DEFAULT_INTERFACE_ERROR_LIMIT_MM = 0.05
_MAX_VARIABLE_OUTER_THICKNESS_BANDS = 6
_VARIABLE_AFFINE_REFINEMENT_PASSES = 1
_MAX_VARIABLE_PARTITION_CELLS = 2_000_000
_ADAPTIVE_EDGE_ROOT_BISECTION_PASSES = 8
_MAX_ADAPTIVE_EDGE_ROOT_SAMPLES = 20_000_000
_ADAPTIVE_INTERFACE_REFINEMENT_PASSES = 7
_ADAPTIVE_PARTNER_REFINEMENT_PASSES = 2
_ADAPTIVE_TOTAL_REFINEMENT_PASSES = 8
_ADAPTIVE_STAGNATION_FALLBACK_PASSES = 1
_ADAPTIVE_STAGNATION_MAX_PARENT_CELLS = 32
_ADAPTIVE_STAGNATION_MINIMUM_OVERDEPTH_REDUCTION_FRACTION = 0.10
_ADAPTIVE_STAGNATION_MAX_CHILD_DIAMETER_RATIO = 0.90
_ADAPTIVE_STAGNATION_DIAMETER_REFINEMENT_PASSES = 3
_ADAPTIVE_STAGNATION_MAX_DIRECTION_SEED_EDGES = 256


class ColorDepthExactPartitionError(RuntimeError):
    """Stable fail-closed diagnostic from the exact provider."""

    def __init__(
        self,
        code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(self.code)


class _AdaptiveInterfaceRefinementRequired(RuntimeError):
    """Internal request to edge-star refine offending input tetrahedra."""

    def __init__(
        self,
        *,
        threshold_mm: float,
        maximum_overdepth_mm: float,
        maximum_vertex_overdepth_mm: float,
        maximum_interior_overdepth_mm: float,
        parent_cells: np.ndarray,
        violating_triangles: int,
        three_edge_parent_cells: int,
        four_edge_parent_cells: int,
        violating_sample_roles: Mapping[str, int],
        maximum_sample_roles: Mapping[str, int],
        maximum_overdepth_by_sample_role_mm: Mapping[str, float],
        refinement_edges: np.ndarray,
        refinement_edge_record: Mapping[str, object],
        cause: str = "interface",
        violating_partner_cells: int = 0,
        cause_details: Mapping[str, object] | None = None,
    ) -> None:
        self.threshold_mm = float(threshold_mm)
        self.maximum_overdepth_mm = float(maximum_overdepth_mm)
        self.maximum_vertex_overdepth_mm = float(
            maximum_vertex_overdepth_mm
        )
        self.maximum_interior_overdepth_mm = float(
            maximum_interior_overdepth_mm
        )
        self.parent_cells = np.ascontiguousarray(
            np.asarray(parent_cells, dtype=np.int32)
        )
        self.violating_triangles = int(violating_triangles)
        self.three_edge_parent_cells = int(three_edge_parent_cells)
        self.four_edge_parent_cells = int(four_edge_parent_cells)
        self.violating_sample_roles = {
            str(role): int(count)
            for role, count in violating_sample_roles.items()
        }
        self.maximum_sample_roles = {
            str(role): int(count)
            for role, count in maximum_sample_roles.items()
        }
        self.maximum_overdepth_by_sample_role_mm = {
            str(role): float(value)
            for role, value in maximum_overdepth_by_sample_role_mm.items()
        }
        self.refinement_edges = np.ascontiguousarray(
            np.asarray(refinement_edges, dtype=np.int32).reshape((-1, 2))
        )
        self.refinement_edge_record = dict(refinement_edge_record)
        self.cause = str(cause)
        self.violating_partner_cells = int(violating_partner_cells)
        self.cause_details = dict(cause_details or {})
        super().__init__("localized_threshold_interface_refinement_required")


def _raise(code: str, **details: object) -> None:
    raise ColorDepthExactPartitionError(code, details)


def _progress(
    callback: Callable[..., object] | None,
    phase: str,
    fraction: float,
    message: str,
) -> None:
    if callback is not None:
        callback(phase, max(0.0, min(1.0, float(fraction))), message)


def _adaptive_interface_stagnation_policy(
    *,
    cause: str,
    maximum_overdepth_mm: float,
    violating_triangles: int,
    violating_parent_cells: int,
    three_edge_parent_cells: int,
    four_edge_parent_cells: int,
    violating_sample_roles: Mapping[str, int],
    unique_seed_edges: int,
    violating_origin_cells: np.ndarray,
    completed_records: list[Mapping[str, object]],
) -> Mapping[str, object]:
    """Detect repeated four-edge violations that fail to contract."""

    origin_cells = np.unique(
        np.asarray(violating_origin_cells, dtype=np.int64).reshape(-1)
    )
    if not len(origin_cells) or np.any(origin_cells < 0):
        _raise("invalid_adaptive_stagnation_origin_cells")
    origin_bytes = np.ascontiguousarray(origin_cells.astype("<i8")).tobytes()
    spatial_lineage = {
        "origin_cells": int(len(origin_cells)),
        "origin_cell_sha256": hashlib.sha256(origin_bytes).hexdigest(),
        "origin_cell_ids": [
            int(value) for value in origin_cells[:32]
        ],
        "origin_cell_ids_complete": bool(len(origin_cells) <= 32),
        "origin_cell_examples": [
            int(value) for value in origin_cells[:20]
        ],
        "origin_cell_examples_complete": bool(len(origin_cells) <= 20),
    }
    signature = {
        "violating_triangles": int(violating_triangles),
        "violating_parent_cells": int(violating_parent_cells),
        "three_edge_parent_cells": int(three_edge_parent_cells),
        "four_edge_parent_cells": int(four_edge_parent_cells),
        "violating_sample_roles": {
            str(role): int(count)
            for role, count in sorted(violating_sample_roles.items())
        },
        "unique_seed_edges": int(unique_seed_edges),
        "spatial_lineage": spatial_lineage,
    }
    previous = next(
        (
            record
            for record in reversed(completed_records)
            if str(record.get("cause", "")) == "interface"
        ),
        None,
    )
    current_overdepth = float(maximum_overdepth_mm)
    previous_overdepth_value = (
        float(previous["trigger_maximum_overdepth_mm"])
        if previous is not None
        else None
    )
    contraction_ratio_value = (
        current_overdepth / previous_overdepth_value
        if previous_overdepth_value is not None
        and previous_overdepth_value > 0.0
        and math.isfinite(previous_overdepth_value)
        else None
    )
    previous_signature = (
        dict(previous.get("trigger_signature", {}))
        if previous is not None
        else {}
    )
    previous_spatial = dict(previous_signature.get("spatial_lineage", {}))
    previous_structure = {
        key: value
        for key, value in previous_signature.items()
        if key != "spatial_lineage"
    }
    current_structure = {
        key: value for key, value in signature.items() if key != "spatial_lineage"
    }
    previous_origin_cells = set(
        map(int, previous_spatial.get("origin_cell_ids", ()))
    )
    current_origin_cells = set(map(int, spatial_lineage["origin_cell_ids"]))
    spatial_sets_complete = bool(
        spatial_lineage["origin_cell_ids_complete"]
        and previous_spatial.get("origin_cell_ids_complete", False)
    )
    lineage_overlap = len(current_origin_cells & previous_origin_cells)
    lineage_overlap_denominator = min(
        len(current_origin_cells), len(previous_origin_cells)
    )
    lineage_overlap_fraction = (
        float(lineage_overlap) / float(lineage_overlap_denominator)
        if lineage_overlap_denominator
        else 0.0
    )
    same_spatial_lineage = bool(
        spatial_sets_complete and lineage_overlap_fraction >= 0.75
    )
    structural_diagnostics_match = bool(
        previous is not None and previous_structure == current_structure
    )
    repeated_signature = bool(previous is not None and same_spatial_lineage)
    maximum_poor_ratio = (
        1.0 - _ADAPTIVE_STAGNATION_MINIMUM_OVERDEPTH_REDUCTION_FRACTION
    )
    poor_contraction = bool(
        contraction_ratio_value is not None
        and math.isfinite(contraction_ratio_value)
        and contraction_ratio_value > maximum_poor_ratio + 1e-12
    )
    four_edge_only = bool(
        int(violating_parent_cells) > 0
        and int(three_edge_parent_cells) == 0
        and int(four_edge_parent_cells) == int(violating_parent_cells)
    )
    small_parent_set = bool(
        0 < int(violating_parent_cells)
        <= _ADAPTIVE_STAGNATION_MAX_PARENT_CELLS
    )
    previous_used_fallback = bool(
        previous is not None
        and previous.get("stagnation_full_diameter_fallback", False)
    )
    eligible = bool(
        str(cause) == "interface"
        and current_overdepth >= 0.0
        and math.isfinite(current_overdepth)
        and four_edge_only
        and small_parent_set
        and same_spatial_lineage
        and poor_contraction
    )
    hard_stop = bool(eligible and previous_used_fallback)
    use_full_diameter_fallback = bool(eligible and not hard_stop)
    if hard_stop:
        reason = "post_fallback_overdepth_stagnation"
    elif use_full_diameter_fallback:
        reason = "same_lineage_four_edge_family_poor_contraction"
    elif not four_edge_only:
        reason = "not_four_edge_only"
    elif not small_parent_set:
        reason = "violating_parent_cell_limit"
    elif not same_spatial_lineage:
        reason = "spatial_lineage_not_repeated"
    elif not poor_contraction:
        reason = "overdepth_contracted"
    else:
        reason = "not_eligible"
    return {
        "use_full_diameter_fallback": use_full_diameter_fallback,
        "hard_stop": hard_stop,
        "reason": reason,
        "signature": signature,
        "repeated_signature": repeated_signature,
        "structural_diagnostics_match": structural_diagnostics_match,
        "structural_counts_and_roles_are_diagnostic_only": True,
        "same_spatial_lineage": same_spatial_lineage,
        "spatial_lineage_overlap_fraction": lineage_overlap_fraction,
        "poor_contraction": poor_contraction,
        "previous_used_fallback": previous_used_fallback,
        "current_maximum_overdepth_mm": current_overdepth,
        "previous_maximum_overdepth_mm": previous_overdepth_value,
        "overdepth_contraction_ratio": contraction_ratio_value,
        "maximum_poor_contraction_ratio": float(maximum_poor_ratio),
        "minimum_overdepth_reduction_fraction": float(
            _ADAPTIVE_STAGNATION_MINIMUM_OVERDEPTH_REDUCTION_FRACTION
        ),
        "maximum_violating_parent_cells": int(
            _ADAPTIVE_STAGNATION_MAX_PARENT_CELLS
        ),
    }


def _adaptive_refinement_budget_route(
    *,
    adaptive_stage_b: bool,
    cause: str,
    ordinary_interface_rounds: int,
    partner_rounds: int,
    stagnation_fallback_rounds: int,
    total_rounds: int,
    stagnation_policy: Mapping[str, object],
) -> Mapping[str, object]:
    """Choose one bounded adaptive refinement route, or fail closed.

    The seven interface rounds remain the budget for the ordinary edge-star
    heuristic.  A policy-authorized full-diameter refinement is tracked
    separately and may consume the eighth *total* round after those seven
    ordinary rounds are exhausted.  It is therefore a bounded replacement
    route, not an extension of either the ordinary-interface or total budget.
    """

    cause = str(cause)
    ordinary_interface_rounds = int(ordinary_interface_rounds)
    partner_rounds = int(partner_rounds)
    stagnation_fallback_rounds = int(stagnation_fallback_rounds)
    total_rounds = int(total_rounds)
    counts = (
        ordinary_interface_rounds,
        partner_rounds,
        stagnation_fallback_rounds,
        total_rounds,
    )
    if any(value < 0 for value in counts):
        _raise(
            "invalid_adaptive_refinement_round_counts",
            ordinary_interface_rounds=ordinary_interface_rounds,
            partner_rounds=partner_rounds,
            stagnation_fallback_rounds=stagnation_fallback_rounds,
            total_rounds=total_rounds,
        )
    if total_rounds != (
        ordinary_interface_rounds
        + partner_rounds
        + stagnation_fallback_rounds
    ):
        _raise(
            "inconsistent_adaptive_refinement_round_counts",
            ordinary_interface_rounds=ordinary_interface_rounds,
            partner_rounds=partner_rounds,
            stagnation_fallback_rounds=stagnation_fallback_rounds,
            total_rounds=total_rounds,
        )
    policy_requests_fallback = bool(
        stagnation_policy.get("use_full_diameter_fallback", False)
    )
    total_budget_available = bool(
        total_rounds < _ADAPTIVE_TOTAL_REFINEMENT_PASSES
    )
    fallback_budget_available = bool(
        stagnation_fallback_rounds
        < _ADAPTIVE_STAGNATION_FALLBACK_PASSES
    )
    interface_budget_exhausted = bool(
        ordinary_interface_rounds
        >= _ADAPTIVE_INTERFACE_REFINEMENT_PASSES
    )
    partner_budget_exhausted = bool(
        partner_rounds >= _ADAPTIVE_PARTNER_REFINEMENT_PASSES
    )
    use_fallback = bool(
        adaptive_stage_b
        and cause == "interface"
        and policy_requests_fallback
        and total_budget_available
        and fallback_budget_available
    )
    if not adaptive_stage_b:
        allowed = False
        reason = "adaptive_stage_b_disabled"
    elif not total_budget_available:
        allowed = False
        reason = "total_refinement_budget_exhausted"
    elif use_fallback:
        allowed = True
        reason = (
            "exhausted_interface_budget_stagnation_fallback"
            if interface_budget_exhausted
            else "policy_authorized_stagnation_fallback"
        )
    elif cause == "interface" and interface_budget_exhausted:
        allowed = False
        reason = "ordinary_interface_refinement_budget_exhausted"
    elif cause == "partner" and partner_budget_exhausted:
        allowed = False
        reason = "partner_refinement_budget_exhausted"
    elif cause == "interface":
        allowed = True
        reason = "ordinary_interface_refinement"
    elif cause == "partner":
        allowed = True
        reason = "ordinary_partner_refinement"
    else:
        allowed = False
        reason = "invalid_adaptive_refinement_cause"
    return {
        "allowed": bool(allowed),
        "reason": str(reason),
        "route": (
            "stagnation_full_diameter_fallback"
            if use_fallback
            else "ordinary_edge_star"
        ),
        "use_full_diameter_fallback": bool(use_fallback),
        "policy_requested_full_diameter_fallback": bool(
            policy_requests_fallback
        ),
        "exhausted_interface_budget_replacement": bool(
            use_fallback and interface_budget_exhausted
        ),
        "ordinary_interface_rounds": ordinary_interface_rounds,
        "stagnation_fallback_rounds": stagnation_fallback_rounds,
        "partner_rounds": partner_rounds,
        "total_rounds": total_rounds,
        "maximum_ordinary_interface_rounds": int(
            _ADAPTIVE_INTERFACE_REFINEMENT_PASSES
        ),
        "maximum_stagnation_fallback_rounds": int(
            _ADAPTIVE_STAGNATION_FALLBACK_PASSES
        ),
        "maximum_partner_rounds": int(
            _ADAPTIVE_PARTNER_REFINEMENT_PASSES
        ),
        "maximum_total_rounds": int(_ADAPTIVE_TOTAL_REFINEMENT_PASSES),
    }


def _signed_six(nodes: np.ndarray, tets: np.ndarray) -> np.ndarray:
    points = nodes[tets]
    return np.einsum(
        "ij,ij->i",
        points[:, 1] - points[:, 0],
        np.cross(
            points[:, 2] - points[:, 0],
            points[:, 3] - points[:, 0],
        ),
    )


def _tet_volumes(nodes: np.ndarray, tets: np.ndarray) -> np.ndarray:
    return np.abs(_signed_six(nodes, tets)) / 6.0


def _cell_face_table(
    tets: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = np.asarray(tets, dtype=np.int32)[:, _TET_FACES].reshape((-1, 3))
    keys = np.sort(raw, axis=1)
    order = np.lexsort((keys[:, 2], keys[:, 1], keys[:, 0]))
    ordered = keys[order]
    starts = np.r_[
        0, np.flatnonzero(np.any(ordered[1:] != ordered[:-1], axis=1)) + 1
    ].astype(np.int64, copy=False)
    counts = np.diff(np.r_[starts, len(order)]).astype(np.int32, copy=False)
    return raw, order.astype(np.int64, copy=False), starts, counts


def _oriented_boundary_faces(
    nodes: np.ndarray, tets: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    raw, order, starts, counts = _cell_face_table(tets)
    if np.any(counts > 2):
        _raise(
            "nonmanifold_tetgen_cell_complex",
            faces=int(np.count_nonzero(counts > 2)),
        )
    rows = order[starts[counts == 1]]
    faces = raw[rows].copy()
    owners = (rows // 4).astype(np.int32)
    opposite = tets[owners, rows % 4]
    points = nodes[faces]
    normals = np.cross(
        points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]
    )
    inward = np.einsum(
        "ij,ij->i", normals, nodes[opposite] - points[:, 0]
    ) > 0.0
    if np.any(inward):
        faces[inward, 1:3] = faces[inward, 2:0:-1]
    return np.asarray(faces, dtype=np.int32), owners


def _closest_source(
    mesh: trimesh.Trimesh,
    query: np.ndarray,
    *,
    chunk_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(query, dtype=np.float64)
    if not len(points):
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.int32)
    distances: list[np.ndarray] = []
    face_ids: list[np.ndarray] = []
    for start in range(0, len(points), int(chunk_size)):
        _closest, distance, faces = trimesh.proximity.closest_point(
            mesh, points[start : start + int(chunk_size)]
        )
        distance = np.asarray(distance, dtype=np.float64)
        if not np.isfinite(distance).all():
            _raise("nonfinite_closest_surface_distance")
        distances.append(distance)
        face_ids.append(np.asarray(faces, dtype=np.int32))
    return np.concatenate(distances), np.concatenate(face_ids)


def _validate_source_for_tetgen(
    source: ColorDepthSourceSurface,
) -> trimesh.Trimesh:
    """Reject malformed public-contract arrays before entering native TetGen."""

    try:
        vertices = np.asarray(source.vertices_mm, dtype=np.float64)
        faces_raw = np.asarray(source.faces)
        labels_raw = np.asarray(source.face_target_labels)
        height_mm = float(source.height_mm)
        declared_volume = float(source.source_volume_mm3)
    except (TypeError, ValueError, OverflowError) as exc:
        _raise("invalid_source_surface_arrays", error=str(exc))
    if (
        vertices.ndim != 2
        or vertices.shape[1:] != (3,)
        or len(vertices) < 4
        or not np.isfinite(vertices).all()
    ):
        _raise("invalid_source_vertices", shape=tuple(vertices.shape))
    if (
        faces_raw.ndim != 2
        or faces_raw.shape[1:] != (3,)
        or len(faces_raw) < 4
        or not np.issubdtype(faces_raw.dtype, np.integer)
    ):
        _raise("invalid_source_faces", shape=tuple(faces_raw.shape))
    faces_i64 = np.asarray(faces_raw, dtype=np.int64)
    if int(faces_i64.min()) < 0 or int(faces_i64.max()) >= len(vertices):
        _raise("source_face_index_out_of_range")
    if np.any(
        (faces_i64[:, 0] == faces_i64[:, 1])
        | (faces_i64[:, 1] == faces_i64[:, 2])
        | (faces_i64[:, 2] == faces_i64[:, 0])
    ):
        _raise("source_face_has_repeated_vertex")
    faces = np.asarray(faces_i64, dtype=np.int32)
    triangles = vertices[faces]
    twice_area = np.linalg.norm(
        np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        ),
        axis=1,
    )
    if np.any(~np.isfinite(twice_area)) or np.any(twice_area <= 1e-14):
        _raise(
            "degenerate_source_triangle",
            faces=int(np.count_nonzero(twice_area <= 1e-14)),
        )
    if (
        labels_raw.shape != (len(faces),)
        or not np.issubdtype(labels_raw.dtype, np.integer)
    ):
        _raise(
            "invalid_source_target_labels",
            expected=(int(len(faces)),),
            actual=tuple(labels_raw.shape),
        )
    labels_i64 = np.asarray(labels_raw, dtype=np.int64)
    if (
        np.any(labels_i64 < 0)
        or np.any(labels_i64 >= np.iinfo(np.int32).max)
    ):
        _raise("source_target_label_out_of_range")
    if not math.isfinite(height_mm) or height_mm <= 0.0:
        _raise("invalid_source_height_mm", value=source.height_mm)
    if not math.isfinite(declared_volume) or declared_volume <= 0.0:
        _raise("invalid_declared_source_volume", value=source.source_volume_mm3)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if not mesh.is_watertight:
        _raise("watertight_source_required")
    if not mesh.is_winding_consistent:
        _raise("consistent_source_winding_required")
    measured_volume = float(mesh.volume)
    if not mesh.is_volume or not math.isfinite(measured_volume) or measured_volume <= 0.0:
        _raise("positive_oriented_source_volume_required", volume_mm3=measured_volume)
    volume_error = abs(measured_volume - declared_volume)
    if volume_error > 1e-8 * max(measured_volume, declared_volume, 1.0):
        _raise(
            "declared_source_volume_mismatch",
            declared_volume_mm3=declared_volume,
            measured_volume_mm3=measured_volume,
            absolute_error_mm3=volume_error,
        )
    return mesh


def _validate_recipes(
    source: ColorDepthSourceSurface,
    recipes: Mapping[int, ColorDepthRecipe],
) -> tuple[dict[int, float], dict[int, int], dict[int, int]]:
    used = set(map(int, np.unique(source.face_target_labels)))
    missing = sorted(used - {int(value) for value in recipes})
    if missing:
        _raise("source_recipe_missing", target_labels=missing)
    thresholds: dict[int, float] = {}
    outer: dict[int, int] = {}
    backing: dict[int, int] = {}
    for raw_label, recipe in recipes.items():
        label = int(raw_label)
        if not isinstance(recipe, ColorDepthRecipe) or recipe.target_label != label:
            _raise("invalid_recipe", target_label=label)
        if recipe.backing_depth_mm is not None or recipe.core_physical is not None:
            _raise(
                "finite_backing_depth_not_yet_supported",
                target_label=label,
            )
        thresholds[label] = float(recipe.outer_thickness_mm)
        outer[label] = int(recipe.outer_physical)
        backing[label] = int(recipe.backing_physical)
    if not thresholds:
        _raise("recipes_required")
    return thresholds, outer, backing


def _tetrahedralize_exact_boundary(
    source: ColorDepthSourceSurface,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]]:
    try:
        import tetgen
    except Exception as exc:  # pragma: no cover - packaging diagnostic
        _raise("tetgen_dependency_missing", error=str(exc))
    vertices = np.asarray(source.vertices_mm, dtype=np.float64)
    faces = np.asarray(source.faces, dtype=np.int32)
    # TetGen facet markers cannot use zero, so encode only for PLC provenance.
    markers = np.asarray(source.face_target_labels, dtype=np.int32) + 1
    started = time.perf_counter()
    try:
        generator = tetgen.TetGen(vertices, faces, markers)
        nodes, tets, _attributes, _output_markers = generator.tetrahedralize(
            plc=True,
            quality=True,
            minratio=1.5,
            mindihedral=10.0,
            nobisect=True,
            facesout=True,
            order=1,
            docheck=True,
            quiet=True,
            nowarning=False,
        )
    except Exception as exc:
        _raise("tetgen_exact_boundary_failed", error=str(exc))
    nodes = np.asarray(nodes, dtype=np.float64)
    tets = np.asarray(tets, dtype=np.int32)
    if (
        nodes.ndim != 2
        or nodes.shape[1:] != (3,)
        or not np.isfinite(nodes).all()
    ):
        _raise("tetgen_returned_invalid_nodes", shape=tuple(nodes.shape))
    if tets.ndim != 2 or tets.shape[1:] != (4,) or not len(tets):
        _raise("tetgen_returned_invalid_cells", shape=tuple(tets.shape))
    if int(tets.min()) < 0 or int(tets.max()) >= len(nodes):
        _raise("tetgen_cell_index_out_of_range")
    if (
        len(nodes) < len(vertices)
        or not np.allclose(
            nodes[: len(vertices)], vertices, rtol=0.0, atol=1e-12
        )
    ):
        _raise("tetgen_source_vertex_prefix_changed")
    volumes = _tet_volumes(nodes, tets)
    if np.any(~np.isfinite(volumes)) or np.any(volumes <= 0.0):
        _raise(
            "tetgen_returned_degenerate_cells",
            cells=int(np.count_nonzero(volumes <= 0.0)),
        )
    tet_volume = float(volumes.sum())
    volume_error = abs(tet_volume - float(source.source_volume_mm3))
    if volume_error > 1e-8 * max(tet_volume, source.source_volume_mm3, 1.0):
        _raise(
            "tetgen_volume_mismatch",
            declared_volume_mm3=float(source.source_volume_mm3),
            tetrahedral_volume_mm3=tet_volume,
            absolute_error_mm3=volume_error,
        )
    boundary_faces, boundary_cells = _oriented_boundary_faces(nodes, tets)
    return nodes, tets, boundary_faces, boundary_cells, {
        "engine": "TetGen",
        "input_vertices": int(len(vertices)),
        "input_faces": int(len(faces)),
        "nodes": int(len(nodes)),
        "tetrahedra": int(len(tets)),
        "boundary_faces": int(len(boundary_faces)),
        "tetrahedral_volume_mm3": tet_volume,
        "volume_error_mm3": volume_error,
        "source_vertex_prefix_preserved": True,
        "seconds": float(time.perf_counter() - started),
    }


def _complete_boundary_labels(
    source: ColorDepthSourceSurface,
    source_mesh: trimesh.Trimesh,
    nodes: np.ndarray,
    boundary_faces: np.ndarray,
    *,
    chunk_size: int,
) -> tuple[np.ndarray, np.ndarray, Mapping[str, object]]:
    source_lookup = {
        tuple(sorted(map(int, face))): (int(label), int(face_id))
        for face_id, (face, label) in enumerate(
            zip(
                source.faces,
                source.face_target_labels,
                strict=True,
            )
        )
    }
    labels = np.full(len(boundary_faces), -1, dtype=np.int32)
    parents = np.full(len(boundary_faces), -1, dtype=np.int32)
    exact = 0
    unresolved: list[int] = []
    for boundary_id, face in enumerate(boundary_faces):
        value = source_lookup.get(tuple(sorted(map(int, face))))
        if value is None:
            unresolved.append(boundary_id)
        else:
            labels[boundary_id], parents[boundary_id] = value
            exact += 1
    maximum_distance = 0.0
    if unresolved:
        unresolved_ids = np.asarray(unresolved, dtype=np.int32)
        query = nodes[boundary_faces[unresolved_ids]].mean(axis=1)
        distance, closest = _closest_source(
            source_mesh, query, chunk_size=chunk_size
        )
        maximum_distance = float(np.max(distance, initial=0.0))
        if maximum_distance > _BOUNDARY_TRANSFER_TOLERANCE_MM:
            _raise(
                "boundary_label_transfer_too_far",
                maximum_distance_mm=maximum_distance,
                unresolved_faces=int(len(unresolved)),
            )
        parents[unresolved_ids] = closest
        labels[unresolved_ids] = source.face_target_labels[closest]
    if np.any(labels < 0) or np.any(parents < 0):
        _raise("boundary_label_completion_failed")
    return labels, parents, {
        "boundary_faces": int(len(boundary_faces)),
        "exact_source_triangles": int(exact),
        "transferred_subtriangles": int(len(unresolved)),
        "maximum_transfer_distance_mm": maximum_distance,
    }


def _split_conflicting_boundary_cells(
    nodes: np.ndarray,
    tets: np.ndarray,
    boundary_faces: np.ndarray,
    boundary_cells: np.ndarray,
    boundary_labels: np.ndarray,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    Mapping[str, object],
]:
    by_cell: dict[int, dict[tuple[int, int, int], int]] = {}
    for face, cell, label in zip(
        boundary_faces, boundary_cells, boundary_labels, strict=True
    ):
        key = tuple(sorted(map(int, face)))
        if key in by_cell.setdefault(int(cell), {}):
            _raise("duplicate_boundary_face_in_cell", cell=int(cell))
        by_cell[int(cell)][key] = int(label)
    conflicts = {
        cell
        for cell, values in by_cell.items()
        if len(set(values.values())) > 1
    }
    extra_nodes: list[np.ndarray] = []
    output_tets: list[np.ndarray] = []
    parent_cells: list[int] = []
    forced_labels: list[int] = []
    boundary_lookup: dict[tuple[int, int, int], int] = {}
    source_volume = float(_tet_volumes(nodes, tets).sum())
    for cell_id, tet in enumerate(tets):
        boundary_for_cell = by_cell.get(cell_id, {})
        if cell_id not in conflicts:
            output_id = len(output_tets)
            candidate = tet.copy()
            if _signed_six(nodes, candidate.reshape((1, 4)))[0] < 0.0:
                candidate[[1, 2]] = candidate[[2, 1]]
            output_tets.append(candidate)
            parent_cells.append(cell_id)
            unique_labels = set(boundary_for_cell.values())
            forced_labels.append(
                next(iter(unique_labels)) if len(unique_labels) == 1 else -1
            )
            for key in boundary_for_cell:
                boundary_lookup[key] = output_id
            continue
        centroid_id = len(nodes) + len(extra_nodes)
        centroid = nodes[tet].mean(axis=0)
        extra_nodes.append(centroid)
        for local_face in _TET_FACES:
            face = tet[local_face]
            key = tuple(sorted(map(int, face)))
            child = np.asarray(
                (int(face[0]), int(face[1]), int(face[2]), centroid_id),
                dtype=np.int32,
            )
            points = np.vstack((nodes[face], centroid))
            signed = float(
                np.dot(
                    points[1] - points[0],
                    np.cross(points[2] - points[0], points[3] - points[0]),
                )
            )
            if signed < 0.0:
                child[[1, 2]] = child[[2, 1]]
                signed = -signed
            if not math.isfinite(signed) or signed <= 0.0:
                _raise("degenerate_boundary_face_cone", cell=int(cell_id))
            output_id = len(output_tets)
            output_tets.append(child)
            parent_cells.append(cell_id)
            forced_labels.append(int(boundary_for_cell.get(key, -1)))
            if key in boundary_for_cell:
                boundary_lookup[key] = output_id
    refined_nodes = (
        np.vstack((nodes, np.asarray(extra_nodes, dtype=np.float64)))
        if extra_nodes
        else nodes.copy()
    )
    refined_tets = np.asarray(output_tets, dtype=np.int32)
    parents = np.asarray(parent_cells, dtype=np.int32)
    forced = np.asarray(forced_labels, dtype=np.int32)
    new_boundary_cells = np.asarray(
        [
            boundary_lookup[tuple(sorted(map(int, face)))]
            for face in boundary_faces
        ],
        dtype=np.int32,
    )
    if not np.array_equal(forced[new_boundary_cells], boundary_labels):
        _raise("boundary_owner_not_preserved_by_face_cones")
    output_volume = float(_tet_volumes(refined_nodes, refined_tets).sum())
    volume_error = abs(output_volume - source_volume)
    if volume_error > 1e-12 * max(source_volume, 1.0):
        _raise(
            "boundary_face_cone_volume_drift",
            source_volume_mm3=source_volume,
            output_volume_mm3=output_volume,
            volume_error_mm3=volume_error,
        )
    return (
        refined_nodes,
        refined_tets,
        parents,
        forced,
        new_boundary_cells,
        {
            "input_tetrahedra": int(len(tets)),
            "conflicting_boundary_tetrahedra": int(len(conflicts)),
            "added_centroid_nodes": int(len(extra_nodes)),
            "output_tetrahedra": int(len(refined_tets)),
            "boundary_faces_preserved_as_single_triangles": True,
            "volume_error_mm3": volume_error,
        },
    )


def _insert_hidden_threshold_centroids(
    *,
    source_mesh: trimesh.Trimesh,
    nodes: np.ndarray,
    tets: np.ndarray,
    boundary_faces: np.ndarray,
    boundary_cells: np.ndarray,
    boundary_labels: np.ndarray,
    boundary_parent_faces: np.ndarray,
    threshold_mm: float,
    chunk_size: int,
    scan_local_hidden: bool = False,
    return_parent_cells: bool = False,
    candidate_cell_mask: np.ndarray | None = None,
    node_depth_mm: np.ndarray | None = None,
    affine_error_limit_mm: float | None = None,
    force_candidate_refinement: bool = False,
) -> tuple[object, ...]:
    """Expose a depth threshold hidden by boundary-only TetGen vertices.

    TetGen is allowed to fill a simple convex PLC entirely with input boundary
    vertices.  Closest-surface distance is then zero at every volumetric node,
    even though the solid has a backing region.  A conforming edge split cannot
    recover an interface which is absent from that nodal field.

    For each all-outer tetrahedron we therefore sample its interior centroid.
    If that true sample is beyond the common threshold, the tetrahedron is
    replaced by the four exact face cones around the centroid.  This changes no
    existing face (including the visible exterior), preserves volume, and gives
    the subsequent common edge registry a positive endpoint.  This is a narrow
    visibility repair rather than a global volume-size heuristic, so a simple
    cube works without making a real model needlessly enormous.
    """

    source_nodes = np.asarray(nodes, dtype=np.float64)
    source_tets = np.asarray(tets, dtype=np.int32)
    if node_depth_mm is None:
        node_depth, _node_faces = _closest_source(
            source_mesh, source_nodes, chunk_size=chunk_size
        )
    else:
        supplied_depth = np.asarray(node_depth_mm, dtype=np.float64)
        if (
            supplied_depth.shape != (len(source_nodes),)
            or not np.isfinite(supplied_depth).all()
            or np.any(supplied_depth < 0.0)
        ):
            _raise(
                "invalid_hidden_threshold_node_depth",
                expected=(int(len(source_nodes)),),
                actual=tuple(supplied_depth.shape),
            )
        node_depth = supplied_depth.copy()
    boundary_node_ids = np.unique(np.asarray(boundary_faces, dtype=np.int32))
    node_depth[boundary_node_ids] = 0.0
    scalar = node_depth - float(threshold_mm)
    existing_positive = int(
        np.count_nonzero(scalar > 1e-12)
    )
    # Normal production meshes already contain a resolved positive side.  In
    # that case retain the scratch/proof path exactly and avoid a second
    # closest-point pass over potentially millions of cell centres.
    if existing_positive and not scan_local_hidden:
        result = (
            source_nodes.copy(),
            source_tets.copy(),
            np.asarray(boundary_faces, dtype=np.int32).copy(),
            np.asarray(boundary_cells, dtype=np.int32).copy(),
            np.asarray(boundary_labels, dtype=np.int32).copy(),
            np.asarray(boundary_parent_faces, dtype=np.int32).copy(),
            np.ascontiguousarray(node_depth, dtype=np.float64),
            {
                "mode": "existing_positive_nodes",
                "existing_positive_nodes": existing_positive,
                "candidate_all_outer_cells": 0,
                "hidden_threshold_cells": 0,
                "added_centroid_nodes": 0,
                "output_tetrahedra": int(len(source_tets)),
                "visible_boundary_preserved": True,
                "volume_error_mm3": 0.0,
            },
        )
        return (
            (*result, np.arange(len(source_tets), dtype=np.int32))
            if return_parent_cells
            else result
        )
    cell_node_depth = node_depth[source_tets]
    all_outer = np.max(scalar[source_tets], axis=1) <= 1e-12
    if affine_error_limit_mm is None:
        affine_limit = None
    else:
        affine_limit = float(affine_error_limit_mm)
        if not math.isfinite(affine_limit) or affine_limit <= 0.0:
            _raise(
                "invalid_hidden_threshold_affine_error_limit",
                affine_error_limit_mm=affine_error_limit_mm,
            )
    force_refinement = bool(force_candidate_refinement)
    if force_refinement and candidate_cell_mask is None:
        _raise("forced_hidden_threshold_refinement_requires_candidate_mask")
    if candidate_cell_mask is None:
        supplied_candidates = np.ones(len(source_tets), dtype=bool)
    else:
        supplied_candidates = np.asarray(candidate_cell_mask)
        if (
            supplied_candidates.shape != (len(source_tets),)
            or supplied_candidates.dtype.kind != "b"
        ):
            _raise(
                "invalid_hidden_threshold_candidate_mask",
                expected=(int(len(source_tets)),),
                actual=tuple(supplied_candidates.shape),
            )
    if force_refinement:
        candidates = supplied_candidates
    else:
        candidates = (
            all_outer & supplied_candidates
            if affine_limit is None
            else supplied_candidates
            & (
                np.min(cell_node_depth, axis=1)
                <= float(threshold_mm) + affine_limit
            )
        )
    candidate_ids = np.flatnonzero(candidates)
    if len(candidate_ids):
        candidate_centers = source_nodes[source_tets[candidate_ids]].mean(axis=1)
        center_depth, _center_faces = _closest_source(
            source_mesh, candidate_centers, chunk_size=chunk_size
        )
        candidate_node_depth = cell_node_depth[candidate_ids]
        interpolated_center_depth = candidate_node_depth.mean(axis=1)
        hidden_positive = (
            np.max(candidate_node_depth, axis=1)
            <= float(threshold_mm) + 1e-12
        ) & (center_depth > float(threshold_mm) + 1e-12)
        hidden_negative = (
            np.min(candidate_node_depth, axis=1)
            >= float(threshold_mm) - 1e-12
        ) & (center_depth < float(threshold_mm) - 1e-12)
        affine_residual = np.abs(center_depth - interpolated_center_depth)
        nodal_crossing = (
            np.min(candidate_node_depth, axis=1)
            < float(threshold_mm) - 1e-12
        ) & (
            np.max(candidate_node_depth, axis=1)
            > float(threshold_mm) + 1e-12
        )
        affine_refinement = (
            np.zeros(len(candidate_ids), dtype=bool)
            if affine_limit is None
            else nodal_crossing
            & (affine_residual > affine_limit + 1e-12)
        )
        refine_mask = (
            np.ones(len(candidate_ids), dtype=bool)
            if force_refinement
            else hidden_positive | hidden_negative | affine_refinement
        )
        hidden_ids = candidate_ids[refine_mask]
        hidden_centers = candidate_centers[refine_mask]
        hidden_depth = center_depth[refine_mask]
        hidden_count = int(
            np.count_nonzero((hidden_positive | hidden_negative) & refine_mask)
        )
        affine_refinement_count = int(
            np.count_nonzero(affine_refinement & refine_mask)
        )
        forced_refinement_count = int(
            len(candidate_ids) if force_refinement else 0
        )
        maximum_affine_residual = float(
            np.max(affine_residual, initial=0.0)
        )
    else:
        center_depth = np.empty(0, dtype=np.float64)
        hidden_ids = np.empty(0, dtype=np.int32)
        hidden_centers = np.empty((0, 3), dtype=np.float64)
        hidden_depth = np.empty(0, dtype=np.float64)
        hidden_count = 0
        affine_refinement_count = 0
        forced_refinement_count = 0
        maximum_affine_residual = 0.0

    if not len(hidden_ids):
        result = (
            source_nodes.copy(),
            source_tets.copy(),
            np.asarray(boundary_faces, dtype=np.int32).copy(),
            np.asarray(boundary_cells, dtype=np.int32).copy(),
            np.asarray(boundary_labels, dtype=np.int32).copy(),
            np.asarray(boundary_parent_faces, dtype=np.int32).copy(),
            np.ascontiguousarray(node_depth, dtype=np.float64),
            {
                "mode": (
                    "forced_local_interface_refinement"
                    if force_refinement
                    else "boundary_only_visibility_probe"
                ),
                "existing_positive_nodes": existing_positive,
                "candidate_cells": int(len(candidate_ids)),
                "candidate_all_outer_cells": int(
                    np.count_nonzero(all_outer[candidate_ids])
                ),
                "hidden_threshold_cells": 0,
                "affine_error_refinement_cells": 0,
                "forced_candidate_refinement_cells": 0,
                "added_centroid_nodes": 0,
                "output_tetrahedra": int(len(source_tets)),
                "visible_boundary_preserved": True,
                "volume_error_mm3": 0.0,
                "maximum_candidate_centroid_depth_mm": float(
                    np.max(center_depth, initial=0.0)
                ),
                "maximum_candidate_affine_residual_mm": (
                    maximum_affine_residual
                ),
            },
        )
        return (
            (*result, np.arange(len(source_tets), dtype=np.int32))
            if return_parent_cells
            else result
        )

    predicted_output_tetrahedra = int(
        len(source_tets) + 3 * len(hidden_ids)
    )
    if (
        force_refinement
        and predicted_output_tetrahedra > _MAX_VARIABLE_PARTITION_CELLS
    ):
        _raise(
            "variable_partition_cell_limit_exceeded",
            threshold_mm=float(threshold_mm),
            phase="adaptive_interface_local_refinement_preallocation",
            input_cells=int(len(source_tets)),
            refined_parent_cells=int(len(hidden_ids)),
            predicted_output_cells=predicted_output_tetrahedra,
            maximum=int(_MAX_VARIABLE_PARTITION_CELLS),
        )

    hidden_lookup = np.full(len(source_tets), -1, dtype=np.int32)
    hidden_lookup[hidden_ids] = np.arange(len(hidden_ids), dtype=np.int32)
    centroid_ids = np.arange(
        len(source_nodes),
        len(source_nodes) + len(hidden_ids),
        dtype=np.int32,
    )
    refined_nodes = np.vstack((source_nodes, hidden_centers))
    refined_tets = np.empty(
        (predicted_output_tetrahedra, 4), dtype=np.int32
    )
    output_parent_cells = np.empty(len(refined_tets), dtype=np.int32)
    cursor = 0
    for cell_id, tet in enumerate(source_tets):
        hidden_local = int(hidden_lookup[cell_id])
        if hidden_local < 0:
            candidate = tet.copy()
            if _signed_six(refined_nodes, candidate.reshape((1, 4)))[0] < 0.0:
                candidate[[1, 2]] = candidate[[2, 1]]
            refined_tets[cursor] = candidate
            output_parent_cells[cursor] = int(cell_id)
            cursor += 1
            continue
        centroid_id = int(centroid_ids[hidden_local])
        for local_face in _TET_FACES:
            child = np.asarray(
                (*map(int, tet[local_face]), centroid_id), dtype=np.int32
            )
            signed = float(
                _signed_six(refined_nodes, child.reshape((1, 4)))[0]
            )
            if signed < 0.0:
                child[[1, 2]] = child[[2, 1]]
                signed = -signed
            if not math.isfinite(signed) or signed <= 0.0:
                _raise(
                    "degenerate_hidden_threshold_face_cone",
                    parent_cell=int(cell_id),
                )
            refined_tets[cursor] = child
            output_parent_cells[cursor] = int(cell_id)
            cursor += 1
    if cursor != len(refined_tets):
        _raise("hidden_threshold_child_count_mismatch")

    refined_boundary_faces, refined_boundary_cells = _oriented_boundary_faces(
        refined_nodes, refined_tets
    )
    old_keys = np.sort(np.asarray(boundary_faces, dtype=np.int32), axis=1)
    new_keys = np.sort(refined_boundary_faces, axis=1)
    old_order = np.lexsort((old_keys[:, 2], old_keys[:, 1], old_keys[:, 0]))
    new_order = np.lexsort((new_keys[:, 2], new_keys[:, 1], new_keys[:, 0]))
    if (
        len(old_keys) != len(new_keys)
        or not np.array_equal(old_keys[old_order], new_keys[new_order])
    ):
        _raise("hidden_threshold_refinement_changed_visible_boundary")
    label_by_key = {
        tuple(map(int, key)): int(label)
        for key, label in zip(old_keys, boundary_labels, strict=True)
    }
    parent_by_key = {
        tuple(map(int, key)): int(parent)
        for key, parent in zip(old_keys, boundary_parent_faces, strict=True)
    }
    refined_labels = np.asarray(
        [label_by_key[tuple(map(int, key))] for key in new_keys],
        dtype=np.int32,
    )
    refined_parents = np.asarray(
        [parent_by_key[tuple(map(int, key))] for key in new_keys],
        dtype=np.int32,
    )
    source_volume = float(_tet_volumes(source_nodes, source_tets).sum())
    output_volume = float(_tet_volumes(refined_nodes, refined_tets).sum())
    volume_error = abs(output_volume - source_volume)
    if volume_error > 1e-12 * max(source_volume, 1.0):
        _raise(
            "hidden_threshold_refinement_volume_drift",
            source_volume_mm3=source_volume,
            output_volume_mm3=output_volume,
            volume_error_mm3=volume_error,
        )
    result = (
        np.ascontiguousarray(refined_nodes, dtype=np.float64),
        np.ascontiguousarray(refined_tets, dtype=np.int32),
        np.ascontiguousarray(refined_boundary_faces, dtype=np.int32),
        np.ascontiguousarray(refined_boundary_cells, dtype=np.int32),
        np.ascontiguousarray(refined_labels, dtype=np.int32),
        np.ascontiguousarray(refined_parents, dtype=np.int32),
        np.ascontiguousarray(
            np.concatenate((node_depth, hidden_depth)), dtype=np.float64
        ),
        {
            "mode": (
                "forced_local_interface_refinement"
                if force_refinement
                else "boundary_only_visibility_probe"
            ),
            "existing_positive_nodes": existing_positive,
            "candidate_cells": int(len(candidate_ids)),
            "candidate_all_outer_cells": int(
                np.count_nonzero(all_outer[candidate_ids])
            ),
            "hidden_threshold_cells": int(hidden_count),
            "affine_error_refinement_cells": int(
                affine_refinement_count
            ),
            "forced_candidate_refinement_cells": int(
                forced_refinement_count
            ),
            "added_centroid_nodes": int(len(hidden_ids)),
            "output_tetrahedra": int(len(refined_tets)),
            "visible_boundary_preserved": True,
            "volume_error_mm3": volume_error,
            "maximum_candidate_centroid_depth_mm": float(
                np.max(center_depth, initial=0.0)
            ),
            "maximum_candidate_affine_residual_mm": (
                maximum_affine_residual
            ),
            "minimum_inserted_centroid_depth_mm": float(
                np.min(hidden_depth)
            ),
        },
    )
    return (
        (*result, np.ascontiguousarray(output_parent_cells, dtype=np.int32))
        if return_parent_cells
        else result
    )


def _bisect_internal_edge_stars(
    *,
    source_mesh: trimesh.Trimesh,
    nodes: np.ndarray,
    tets: np.ndarray,
    boundary_faces: np.ndarray,
    boundary_cells: np.ndarray,
    boundary_labels: np.ndarray,
    boundary_parent_faces: np.ndarray,
    node_depth_mm: np.ndarray,
    seed_edges: np.ndarray,
    threshold_mm: float,
    chunk_size: int,
) -> tuple[object, ...]:
    """Conformingly bisect every tetrahedron incident to selected edges.

    The midpoint of one seed edge is a single global vertex shared by its
    complete edge star.  Splitting every incident tetrahedron into the two
    exact cones ``[u,m,a,b]`` and ``[m,v,a,b]`` therefore preserves all
    neighbouring faces.  When a selected edge is on the visible PLC, its two
    incident boundary triangles are split by that same midpoint and retain
    their exact label/source-face provenance.  Thus the boundary geometry is
    unchanged even though its triangle registry is conformingly subdivided.
    """

    source_nodes = np.asarray(nodes, dtype=np.float64)
    source_tets = np.asarray(tets, dtype=np.int32)
    source_boundary_faces = np.asarray(boundary_faces, dtype=np.int32)
    source_boundary_cells = np.asarray(boundary_cells, dtype=np.int32)
    source_boundary_labels = np.asarray(boundary_labels, dtype=np.int32)
    source_boundary_parents = np.asarray(
        boundary_parent_faces, dtype=np.int32
    )
    source_depth = np.asarray(node_depth_mm, dtype=np.float64)
    raw_edges = np.asarray(seed_edges)
    if (
        raw_edges.ndim != 2
        or raw_edges.shape[1:] != (2,)
        or not np.issubdtype(raw_edges.dtype, np.integer)
    ):
        _raise(
            "invalid_adaptive_interface_refinement_edges",
            shape=tuple(raw_edges.shape),
            dtype=str(raw_edges.dtype),
        )
    if source_depth.shape != (len(source_nodes),) or not np.isfinite(
        source_depth
    ).all():
        _raise(
            "invalid_adaptive_interface_refinement_node_depth",
            expected=(int(len(source_nodes)),),
            actual=tuple(source_depth.shape),
        )
    if (
        source_boundary_cells.shape != (len(source_boundary_faces),)
        or source_boundary_labels.shape != (len(source_boundary_faces),)
        or source_boundary_parents.shape != (len(source_boundary_faces),)
    ):
        _raise("invalid_adaptive_interface_refinement_boundary_arrays")
    if not len(raw_edges):
        _raise("adaptive_interface_refinement_edges_required")
    edges_i64 = np.asarray(raw_edges, dtype=np.int64)
    if (
        int(edges_i64.min()) < 0
        or int(edges_i64.max()) >= len(source_nodes)
        or np.any(edges_i64[:, 0] == edges_i64[:, 1])
    ):
        _raise("adaptive_interface_refinement_edge_index_invalid")
    canonical_edges = np.unique(
        np.sort(np.asarray(edges_i64, dtype=np.int32), axis=1), axis=0
    )
    midpoint_coordinates = source_nodes[canonical_edges].mean(axis=1)
    edge_lengths = np.linalg.norm(
        source_nodes[canonical_edges[:, 1]]
        - source_nodes[canonical_edges[:, 0]],
        axis=1,
    )
    if (
        not np.isfinite(midpoint_coordinates).all()
        or not np.isfinite(edge_lengths).all()
        or np.any(edge_lengths <= 0.0)
    ):
        _raise("degenerate_adaptive_interface_refinement_edge")
    coordinate_scale = max(
        float(np.max(np.abs(source_nodes), initial=0.0)), 1.0
    )
    collision_tolerance = 1e-12 * coordinate_scale
    if len(midpoint_coordinates) > 1:
        midpoint_separation, _midpoint_nearest = cKDTree(
            midpoint_coordinates,
            compact_nodes=True,
            balanced_tree=True,
        ).query(midpoint_coordinates, k=2)
        if np.any(midpoint_separation[:, 1] <= collision_tolerance):
            _raise(
                "adaptive_interface_refinement_midpoint_collision",
                kind="selected_edge_midpoints",
                tolerance_mm=float(collision_tolerance),
            )
    existing_distance, _existing_nearest = cKDTree(
        source_nodes,
        compact_nodes=True,
        balanced_tree=True,
    ).query(midpoint_coordinates, k=1)
    existing_collision = np.flatnonzero(
        existing_distance <= collision_tolerance
    )
    if len(existing_collision):
        midpoint_index = int(existing_collision[0])
        _raise(
            "adaptive_interface_refinement_midpoint_collision",
            kind="existing_node",
            edge=list(map(int, canonical_edges[midpoint_index])),
            tolerance_mm=float(collision_tolerance),
        )
    midpoint_depth, _midpoint_face = _closest_source(
        source_mesh, midpoint_coordinates, chunk_size=chunk_size
    )
    midpoint_ids = np.arange(
        len(source_nodes),
        len(source_nodes) + len(canonical_edges),
        dtype=np.int32,
    )
    current_nodes = np.vstack((source_nodes, midpoint_coordinates))
    current_depth = np.concatenate((source_depth, midpoint_depth))
    current_tets = source_tets.copy()
    current_parents = np.arange(len(source_tets), dtype=np.int32)
    current_boundary_faces = source_boundary_faces.copy()
    current_boundary_labels = source_boundary_labels.copy()
    current_boundary_parents = source_boundary_parents.copy()
    star_sizes: list[int] = []
    local_volume_error = 0.0
    split_boundary_faces = 0
    boundary_seed_edges = 0
    for edge_index, (raw_u, raw_v) in enumerate(canonical_edges):
        u = int(raw_u)
        v = int(raw_v)
        contains_u = np.any(current_tets == u, axis=1)
        contains_v = np.any(current_tets == v, axis=1)
        star_ids = np.flatnonzero(contains_u & contains_v)
        if not len(star_ids):
            _raise(
                "adaptive_interface_refinement_edge_star_missing",
                edge=[u, v],
                completed_edges=int(edge_index),
            )
        predicted = int(len(current_tets) + len(star_ids))
        if predicted > _MAX_VARIABLE_PARTITION_CELLS:
            _raise(
                "variable_partition_cell_limit_exceeded",
                threshold_mm=float(threshold_mm),
                phase="adaptive_interface_edge_star_preallocation",
                input_cells=int(len(current_tets)),
                incident_cells=int(len(star_ids)),
                predicted_output_cells=predicted,
                completed_edges=int(edge_index),
                total_edges=int(len(canonical_edges)),
                maximum=int(_MAX_VARIABLE_PARTITION_CELLS),
            )
        keep = ~(contains_u & contains_v)
        star_tets = current_tets[star_ids]
        other_mask = (star_tets != u) & (star_tets != v)
        if np.any(np.count_nonzero(other_mask, axis=1) != 2):
            _raise(
                "invalid_adaptive_interface_refinement_edge_star",
                edge=[u, v],
            )
        other = star_tets[other_mask].reshape((-1, 2))
        midpoint = int(midpoint_ids[edge_index])
        first_children = np.column_stack(
            (
                np.full(len(star_ids), u, dtype=np.int32),
                np.full(len(star_ids), midpoint, dtype=np.int32),
                other,
            )
        )
        second_children = np.column_stack(
            (
                np.full(len(star_ids), midpoint, dtype=np.int32),
                np.full(len(star_ids), v, dtype=np.int32),
                other,
            )
        )
        children = np.vstack((first_children, second_children)).astype(
            np.int32, copy=False
        )
        signed = _signed_six(current_nodes, children)
        reverse = signed < 0.0
        if np.any(reverse):
            children[reverse, 1:3] = children[reverse, 2:0:-1]
            signed[reverse] *= -1.0
        if np.any(~np.isfinite(signed)) or np.any(signed <= 0.0):
            _raise(
                "degenerate_adaptive_interface_edge_star_child",
                edge=[u, v],
                children=int(np.count_nonzero(signed <= 0.0)),
                minimum_signed_six=float(np.min(signed, initial=math.inf)),
            )
        parent_volume = float(
            _tet_volumes(current_nodes, star_tets).sum()
        )
        child_volume = float(_tet_volumes(current_nodes, children).sum())
        edge_volume_error = abs(child_volume - parent_volume)
        local_volume_error = max(local_volume_error, edge_volume_error)
        if edge_volume_error > 1e-12 * max(parent_volume, 1.0):
            _raise(
                "adaptive_interface_edge_star_volume_drift",
                edge=[u, v],
                source_volume_mm3=parent_volume,
                output_volume_mm3=child_volume,
                volume_error_mm3=edge_volume_error,
            )
        star_parents = current_parents[star_ids]
        current_tets = np.vstack((current_tets[keep], children))
        current_parents = np.concatenate(
            (current_parents[keep], star_parents, star_parents)
        )
        boundary_contains_u = np.any(current_boundary_faces == u, axis=1)
        boundary_contains_v = np.any(current_boundary_faces == v, axis=1)
        boundary_star_ids = np.flatnonzero(
            boundary_contains_u & boundary_contains_v
        )
        if len(boundary_star_ids):
            if len(boundary_star_ids) != 2:
                _raise(
                    "adaptive_interface_refinement_boundary_edge_not_two_sided",
                    edge=[u, v],
                    boundary_faces=int(len(boundary_star_ids)),
                )
            current_depth[midpoint] = 0.0
            boundary_children: list[tuple[int, int, int]] = []
            for boundary_face in current_boundary_faces[boundary_star_ids]:
                directed_start = -1
                directed_end = -1
                third = -1
                for face_offset in range(3):
                    first = int(boundary_face[face_offset])
                    second = int(boundary_face[(face_offset + 1) % 3])
                    if {first, second} == {u, v}:
                        directed_start = first
                        directed_end = second
                        third = int(boundary_face[(face_offset + 2) % 3])
                        break
                if directed_start < 0 or third < 0:
                    _raise(
                        "adaptive_interface_refinement_boundary_edge_order_invalid",
                        edge=[u, v],
                    )
                boundary_children.extend(
                    (
                        (directed_start, midpoint, third),
                        (midpoint, directed_end, third),
                    )
                )
            boundary_keep = ~(
                boundary_contains_u & boundary_contains_v
            )
            inherited_labels = current_boundary_labels[boundary_star_ids]
            inherited_parents = current_boundary_parents[boundary_star_ids]
            current_boundary_faces = np.vstack(
                (
                    current_boundary_faces[boundary_keep],
                    np.asarray(boundary_children, dtype=np.int32),
                )
            )
            current_boundary_labels = np.concatenate(
                (
                    current_boundary_labels[boundary_keep],
                    np.repeat(inherited_labels, 2),
                )
            )
            current_boundary_parents = np.concatenate(
                (
                    current_boundary_parents[boundary_keep],
                    np.repeat(inherited_parents, 2),
                )
            )
            boundary_seed_edges += 1
            split_boundary_faces += int(len(boundary_star_ids))
        star_sizes.append(int(len(star_ids)))

    refined_boundary_faces, refined_boundary_cells = _oriented_boundary_faces(
        current_nodes, current_tets
    )
    old_keys = np.sort(current_boundary_faces, axis=1)
    new_keys = np.sort(refined_boundary_faces, axis=1)
    old_order = np.lexsort((old_keys[:, 2], old_keys[:, 1], old_keys[:, 0]))
    new_order = np.lexsort((new_keys[:, 2], new_keys[:, 1], new_keys[:, 0]))
    if (
        len(old_keys) != len(new_keys)
        or not np.array_equal(old_keys[old_order], new_keys[new_order])
    ):
        _raise("adaptive_interface_edge_star_changed_visible_boundary")
    label_by_key = {
        tuple(map(int, key)): int(label)
        for key, label in zip(
            old_keys, current_boundary_labels, strict=True
        )
    }
    parent_by_key = {
        tuple(map(int, key)): int(parent)
        for key, parent in zip(
            old_keys, current_boundary_parents, strict=True
        )
    }
    refined_labels = np.asarray(
        [label_by_key[tuple(map(int, key))] for key in new_keys],
        dtype=np.int32,
    )
    refined_parents = np.asarray(
        [parent_by_key[tuple(map(int, key))] for key in new_keys],
        dtype=np.int32,
    )
    source_volume = float(_tet_volumes(source_nodes, source_tets).sum())
    output_volume = float(_tet_volumes(current_nodes, current_tets).sum())
    volume_error = abs(output_volume - source_volume)
    if volume_error > 1e-12 * max(source_volume, 1.0):
        _raise(
            "adaptive_interface_edge_star_total_volume_drift",
            source_volume_mm3=source_volume,
            output_volume_mm3=output_volume,
            volume_error_mm3=volume_error,
        )
    return (
        np.ascontiguousarray(current_nodes, dtype=np.float64),
        np.ascontiguousarray(current_tets, dtype=np.int32),
        np.ascontiguousarray(refined_boundary_faces, dtype=np.int32),
        np.ascontiguousarray(refined_boundary_cells, dtype=np.int32),
        np.ascontiguousarray(refined_labels, dtype=np.int32),
        np.ascontiguousarray(refined_parents, dtype=np.int32),
        np.ascontiguousarray(current_depth, dtype=np.float64),
        {
            "mode": "adaptive_interface_internal_edge_star_bisection",
            "seed_edges": int(len(canonical_edges)),
            "added_midpoint_nodes": int(len(canonical_edges)),
            "incident_tetrahedron_splits": int(sum(star_sizes)),
            "maximum_edge_star_tetrahedra": int(max(star_sizes, default=0)),
            "input_tetrahedra": int(len(source_tets)),
            "output_tetrahedra": int(len(current_tets)),
            "visible_boundary_preserved": True,
            "boundary_seed_edges": int(boundary_seed_edges),
            "source_boundary_faces_subdivided": int(split_boundary_faces),
            "boundary_labels_and_source_face_provenance_inherited": True,
            "shared_edge_midpoint_registry": True,
            "maximum_local_volume_error_mm3": float(local_volume_error),
            "volume_error_mm3": float(volume_error),
        },
        np.ascontiguousarray(current_parents, dtype=np.int32),
    )


def _tetrahedron_diameters(nodes: np.ndarray, tets: np.ndarray) -> np.ndarray:
    coordinates = np.asarray(nodes, dtype=np.float64)
    cells = np.asarray(tets, dtype=np.int32)
    if cells.ndim != 2 or cells.shape[1:] != (4,):
        _raise("invalid_adaptive_stagnation_diameter_cells")
    edge_nodes = cells[:, _TET_EDGES]
    lengths = np.linalg.norm(
        coordinates[edge_nodes[:, :, 1]]
        - coordinates[edge_nodes[:, :, 0]],
        axis=2,
    )
    diameters = np.max(lengths, axis=1, initial=0.0)
    if not np.isfinite(diameters).all() or np.any(diameters <= 0.0):
        _raise("invalid_adaptive_stagnation_tetrahedron_diameter")
    return np.ascontiguousarray(diameters, dtype=np.float64)


def _refine_stagnant_four_edge_parent_diameters(
    *,
    source_mesh: trimesh.Trimesh,
    nodes: np.ndarray,
    tets: np.ndarray,
    boundary_faces: np.ndarray,
    boundary_cells: np.ndarray,
    boundary_labels: np.ndarray,
    boundary_parent_faces: np.ndarray,
    node_depth_mm: np.ndarray,
    parent_cells: np.ndarray,
    threshold_mm: float,
    chunk_size: int,
) -> tuple[object, ...]:
    """Refine every parent direction, then prove child-diameter contraction."""

    source_nodes = np.asarray(nodes, dtype=np.float64)
    source_tets = np.asarray(tets, dtype=np.int32)
    parents = np.unique(np.asarray(parent_cells, dtype=np.int32))
    if (
        not len(parents)
        or len(parents) > _ADAPTIVE_STAGNATION_MAX_PARENT_CELLS
        or np.any(parents < 0)
        or np.any(parents >= len(source_tets))
    ):
        _raise(
            "invalid_adaptive_stagnation_parent_cells",
            parent_cells=int(len(parents)),
            maximum=int(_ADAPTIVE_STAGNATION_MAX_PARENT_CELLS),
        )
    parent_diameter = _tetrahedron_diameters(
        source_nodes, source_tets[parents]
    )
    all_parent_edges = source_tets[parents][:, _TET_EDGES].reshape((-1, 2))
    seed_edges = np.unique(np.sort(all_parent_edges, axis=1), axis=0)
    if not len(seed_edges):
        _raise("adaptive_stagnation_parent_edges_required")

    current_nodes = source_nodes
    current_tets = source_tets
    current_boundary_faces = np.asarray(boundary_faces, dtype=np.int32)
    current_boundary_cells = np.asarray(boundary_cells, dtype=np.int32)
    current_boundary_labels = np.asarray(boundary_labels, dtype=np.int32)
    current_boundary_parents = np.asarray(
        boundary_parent_faces, dtype=np.int32
    )
    current_depth = np.asarray(node_depth_mm, dtype=np.float64)
    current_provenance = np.arange(len(source_tets), dtype=np.int32)
    pass_records: list[Mapping[str, object]] = []
    maximum_ratio = math.inf
    for diameter_pass in range(
        _ADAPTIVE_STAGNATION_DIAMETER_REFINEMENT_PASSES
    ):
        try:
            pass_result = _bisect_internal_edge_stars(
                source_mesh=source_mesh,
                nodes=current_nodes,
                tets=current_tets,
                boundary_faces=current_boundary_faces,
                boundary_cells=current_boundary_cells,
                boundary_labels=current_boundary_labels,
                boundary_parent_faces=current_boundary_parents,
                node_depth_mm=current_depth,
                seed_edges=seed_edges,
                threshold_mm=threshold_mm,
                chunk_size=chunk_size,
            )
        except ColorDepthExactPartitionError as refinement_error:
            failure_details = dict(refinement_error.details)
            failure_details.update(
                {
                    "stagnation_diameter_pass": int(diameter_pass + 1),
                    "completed_stagnation_diameter_passes": [
                        dict(record) for record in pass_records
                    ],
                }
            )
            raise ColorDepthExactPartitionError(
                refinement_error.code,
                failure_details,
            ) from refinement_error
        (
            current_nodes,
            current_tets,
            current_boundary_faces,
            current_boundary_cells,
            current_boundary_labels,
            current_boundary_parents,
            current_depth,
            edge_star_record,
            pass_parents,
        ) = pass_result
        current_provenance = current_provenance[
            np.asarray(pass_parents, dtype=np.int32)
        ]
        ratio_by_parent: dict[int, float] = {}
        unresolved_children: list[int] = []
        for parent, diameter in zip(parents, parent_diameter, strict=True):
            child_ids = np.flatnonzero(current_provenance == int(parent))
            if not len(child_ids):
                _raise(
                    "adaptive_stagnation_parent_descendants_missing",
                    parent_cell=int(parent),
                )
            child_diameters = _tetrahedron_diameters(
                current_nodes, current_tets[child_ids]
            )
            ratios = child_diameters / float(diameter)
            parent_ratio = float(np.max(ratios, initial=0.0))
            ratio_by_parent[int(parent)] = parent_ratio
            unresolved_children.extend(
                map(
                    int,
                    child_ids[
                        ratios
                        > _ADAPTIVE_STAGNATION_MAX_CHILD_DIAMETER_RATIO
                        + 1e-12
                    ],
                )
            )
        maximum_ratio = float(max(ratio_by_parent.values(), default=math.inf))
        pass_records.append(
            {
                "pass": int(diameter_pass + 1),
                "seed_edges": int(len(seed_edges)),
                "seed_edge_examples": [
                    [int(edge[0]), int(edge[1])]
                    for edge in seed_edges[:20]
                ],
                "seed_edge_examples_complete": bool(len(seed_edges) <= 20),
                "maximum_child_parent_diameter_ratio": maximum_ratio,
                "child_parent_diameter_ratio_by_parent": {
                    str(parent): float(ratio)
                    for parent, ratio in ratio_by_parent.items()
                },
                "unresolved_children": int(len(unresolved_children)),
                "edge_star": dict(edge_star_record),
            }
        )
        if (
            maximum_ratio
            <= _ADAPTIVE_STAGNATION_MAX_CHILD_DIAMETER_RATIO + 1e-12
        ):
            source_volume = float(
                _tet_volumes(source_nodes, source_tets).sum()
            )
            output_volume = float(
                _tet_volumes(current_nodes, current_tets).sum()
            )
            volume_error = abs(output_volume - source_volume)
            if volume_error > 1e-12 * max(source_volume, 1.0):
                _raise(
                    "adaptive_stagnation_refinement_volume_drift",
                    source_volume_mm3=source_volume,
                    output_volume_mm3=output_volume,
                    volume_error_mm3=volume_error,
                )
            return (
                np.ascontiguousarray(current_nodes, dtype=np.float64),
                np.ascontiguousarray(current_tets, dtype=np.int32),
                np.ascontiguousarray(current_boundary_faces, dtype=np.int32),
                np.ascontiguousarray(current_boundary_cells, dtype=np.int32),
                np.ascontiguousarray(current_boundary_labels, dtype=np.int32),
                np.ascontiguousarray(current_boundary_parents, dtype=np.int32),
                np.ascontiguousarray(current_depth, dtype=np.float64),
                {
                    "mode": (
                        "adaptive_interface_stagnation_full_diameter_refinement"
                    ),
                    "input_tetrahedra": int(len(source_tets)),
                    "output_tetrahedra": int(len(current_tets)),
                    "seed_edges": int(
                        sum(int(record["seed_edges"]) for record in pass_records)
                    ),
                    "added_midpoint_nodes": int(
                        len(current_nodes) - len(source_nodes)
                    ),
                    "incident_tetrahedron_splits": int(
                        len(current_tets) - len(source_tets)
                    ),
                    "diameter_refinement_passes": int(len(pass_records)),
                    "maximum_child_parent_diameter_ratio": maximum_ratio,
                    "maximum_allowed_child_parent_diameter_ratio": float(
                        _ADAPTIVE_STAGNATION_MAX_CHILD_DIAMETER_RATIO
                    ),
                    "diameter_contraction_verified": True,
                    "visible_boundary_preserved": True,
                    "volume_error_mm3": float(volume_error),
                    "passes": pass_records,
                },
                np.ascontiguousarray(current_provenance, dtype=np.int32),
            )
        if diameter_pass + 1 >= (
            _ADAPTIVE_STAGNATION_DIAMETER_REFINEMENT_PASSES
        ):
            break
        unresolved = np.unique(np.asarray(unresolved_children, dtype=np.int32))
        child_cells = current_tets[unresolved]
        edge_nodes = child_cells[:, _TET_EDGES]
        edge_lengths = np.linalg.norm(
            current_nodes[edge_nodes[:, :, 1]]
            - current_nodes[edge_nodes[:, :, 0]],
            axis=2,
        )
        longest = np.argmax(edge_lengths, axis=1)
        seed_edges = np.unique(
            np.sort(edge_nodes[np.arange(len(edge_nodes)), longest], axis=1),
            axis=0,
        )
        if (
            not len(seed_edges)
            or len(seed_edges) > _ADAPTIVE_STAGNATION_MAX_DIRECTION_SEED_EDGES
        ):
            _raise(
                "adaptive_stagnation_direction_seed_limit",
                seed_edges=int(len(seed_edges)),
                maximum=int(_ADAPTIVE_STAGNATION_MAX_DIRECTION_SEED_EDGES),
                passes=pass_records,
            )

    _raise(
        "adaptive_interface_stagnation_diameter_not_contracted",
        parent_cells=int(len(parents)),
        refinement_passes=int(len(pass_records)),
        maximum_child_parent_diameter_ratio=float(maximum_ratio),
        maximum_allowed_child_parent_diameter_ratio=float(
            _ADAPTIVE_STAGNATION_MAX_CHILD_DIAMETER_RATIO
        ),
        maximum_cells=int(_MAX_VARIABLE_PARTITION_CELLS),
        passes=pass_records,
    )


def _adaptive_interface_refinement_edges(
    *,
    nodes: np.ndarray,
    tets: np.ndarray,
    scalar: np.ndarray,
    interface_triangles: np.ndarray,
    interface_parent: np.ndarray,
    base_node_count: int,
    unique_edges: np.ndarray,
    violating_triangle_ids: np.ndarray,
    violating_sample_mask: np.ndarray,
) -> tuple[np.ndarray, Mapping[str, object]]:
    """Map unsafe interface samples back to conforming mesh-edge seeds."""

    coordinates = np.asarray(nodes, dtype=np.float64)
    cells = np.asarray(tets, dtype=np.int32)
    level = np.asarray(scalar, dtype=np.float64)
    triangles = np.asarray(interface_triangles, dtype=np.int32)
    triangle_parents = np.asarray(interface_parent, dtype=np.int32)
    roots = np.asarray(unique_edges, dtype=np.int32)
    triangle_ids = np.asarray(violating_triangle_ids, dtype=np.int64)
    violation_mask = np.asarray(violating_sample_mask, dtype=bool)
    if violation_mask.shape != (len(triangle_ids), 7):
        _raise(
            "invalid_adaptive_interface_violation_sample_mask",
            expected=(int(len(triangle_ids)), 7),
            actual=tuple(violation_mask.shape),
        )
    if np.any(violation_mask[:, :3]):
        _raise("adaptive_interface_vertex_violation_has_no_refinement_edge")
    interface_begin = int(base_node_count)
    interface_end = interface_begin + len(roots)
    role_vertex_pairs = ((0, 1), (0, 2), (1, 2))
    seeds: list[tuple[int, int]] = []
    opposite_face_edges = 0
    diagonal_fallback_edges = 0
    diagonal_fallback_events = 0
    centroid_fallback_edges = 0
    centroid_refinement_events = 0

    def same_sign_edges(parent: int) -> np.ndarray:
        parent_tet = cells[int(parent)]
        candidates = np.sort(parent_tet[_TET_EDGES], axis=1)
        same_sign = (
            level[candidates[:, 0]] * level[candidates[:, 1]] > 0.0
        )
        candidates = np.unique(candidates[same_sign], axis=0)
        if not len(candidates):
            _raise(
                "adaptive_interface_parent_has_no_same_sign_edge",
                parent_cell=int(parent),
            )
        order = np.lexsort((candidates[:, 1], candidates[:, 0]))
        return np.ascontiguousarray(candidates[order], dtype=np.int32)

    def longest_same_sign_edge(parent: int) -> tuple[int, int]:
        candidates = same_sign_edges(parent)
        lengths = np.linalg.norm(
            coordinates[candidates[:, 1]]
            - coordinates[candidates[:, 0]],
            axis=1,
        )
        if not np.isfinite(lengths).all() or np.any(lengths <= 0.0):
            _raise(
                "invalid_adaptive_interface_same_sign_edge_length",
                parent_cell=int(parent),
            )
        return tuple(map(int, candidates[int(np.argmax(lengths))]))

    def two_two_same_sign_edges(parent: int) -> list[tuple[int, int]]:
        parent_level = level[cells[int(parent)]]
        negative_count = int(np.count_nonzero(parent_level < 0.0))
        positive_count = int(np.count_nonzero(parent_level > 0.0))
        candidates = same_sign_edges(parent)
        if negative_count != 2 or positive_count != 2 or len(candidates) != 2:
            _raise(
                "adaptive_interface_invalid_two_two_same_sign_edges",
                parent_cell=int(parent),
                negative_vertices=negative_count,
                positive_vertices=positive_count,
                same_sign_edges=int(len(candidates)),
            )
        return [tuple(map(int, edge)) for edge in candidates]

    for local_id, raw_triangle_id in enumerate(triangle_ids):
        triangle_id = int(raw_triangle_id)
        if triangle_id < 0 or triangle_id >= len(triangles):
            _raise("adaptive_interface_violation_triangle_index_invalid")
        parent = int(triangle_parents[triangle_id])
        if parent < 0 or parent >= len(cells):
            _raise("adaptive_interface_violation_parent_index_invalid")
        parent_nodes = set(map(int, cells[parent]))
        edge_roles = np.flatnonzero(violation_mask[local_id, 3:6])
        for edge_role in edge_roles:
            first_local, second_local = role_vertex_pairs[int(edge_role)]
            first_root_id = int(triangles[triangle_id, first_local])
            second_root_id = int(triangles[triangle_id, second_local])
            if not (
                interface_begin <= first_root_id < interface_end
                and interface_begin <= second_root_id < interface_end
            ):
                _raise(
                    "adaptive_interface_root_provenance_missing",
                    triangle=int(triangle_id),
                )
            first_edge = roots[first_root_id - interface_begin]
            second_edge = roots[second_root_id - interface_begin]
            if (
                not set(map(int, first_edge)).issubset(parent_nodes)
                or not set(map(int, second_edge)).issubset(parent_nodes)
            ):
                _raise(
                    "adaptive_interface_root_edge_not_in_parent",
                    triangle=int(triangle_id),
                    parent_cell=parent,
                )
            shared = np.intersect1d(first_edge, second_edge)
            if len(shared) == 1:
                shared_node = int(shared[0])
                opposite = sorted(
                    [
                        int(value)
                        for value in np.concatenate((first_edge, second_edge))
                        if int(value) != shared_node
                    ]
                )
                if len(opposite) != 2 or len(set(opposite)) != 2:
                    _raise(
                        "adaptive_interface_opposite_edge_provenance_invalid",
                        triangle=int(triangle_id),
                    )
                seed = (int(opposite[0]), int(opposite[1]))
                if (
                    not set(seed).issubset(parent_nodes)
                    or level[seed[0]] * level[seed[1]] <= 0.0
                ):
                    _raise(
                        "adaptive_interface_opposite_edge_not_same_sign",
                        triangle=int(triangle_id),
                        parent_cell=parent,
                        edge=list(seed),
                    )
                opposite_face_edges += 1
                edge_seeds = [tuple(sorted(seed))]
            elif len(shared) == 0 and len(
                np.unique(np.concatenate((first_edge, second_edge)))
            ) == 4:
                negative_count = int(
                    np.count_nonzero(level[cells[parent]] < 0.0)
                )
                if negative_count != 2:
                    _raise(
                        "adaptive_interface_diagonal_without_two_two_topology",
                        triangle=int(triangle_id),
                        parent_cell=parent,
                        negative_vertices=negative_count,
                    )
                edge_seeds = two_two_same_sign_edges(parent)
                diagonal_fallback_edges += len(edge_seeds)
                diagonal_fallback_events += 1
            else:
                _raise(
                    "adaptive_interface_root_edge_relationship_invalid",
                    triangle=int(triangle_id),
                    shared_vertices=int(len(shared)),
                )
            seeds.extend(edge_seeds)
        if bool(violation_mask[local_id, 6]):
            parent_level = level[cells[parent]]
            if (
                int(np.count_nonzero(parent_level < 0.0)) == 2
                and int(np.count_nonzero(parent_level > 0.0)) == 2
            ):
                centroid_seeds = two_two_same_sign_edges(parent)
            else:
                centroid_seeds = [longest_same_sign_edge(parent)]
            seeds.extend(centroid_seeds)
            centroid_fallback_edges += len(centroid_seeds)
            centroid_refinement_events += 1
    if not seeds:
        _raise("adaptive_interface_refinement_produced_no_edges")
    refinement_edges = np.unique(
        np.asarray(seeds, dtype=np.int32).reshape((-1, 2)), axis=0
    )
    return (
        np.ascontiguousarray(refinement_edges, dtype=np.int32),
        {
            "raw_edge_requests": int(len(seeds)),
            "unique_seed_edges": int(len(refinement_edges)),
            "opposite_same_sign_face_edges": int(opposite_face_edges),
            "two_two_diagonal_fallback_edges": int(
                diagonal_fallback_edges
            ),
            "two_two_diagonal_fallback_events": int(
                diagonal_fallback_events
            ),
            "face_centroid_fallback_edges": int(centroid_fallback_edges),
            "face_centroid_refinement_events": int(
                centroid_refinement_events
            ),
            "seed_edge_examples": [
                [int(edge[0]), int(edge[1])]
                for edge in refinement_edges[:20]
            ],
            "seed_edge_examples_complete": bool(
                len(refinement_edges) <= 20
            ),
            "selection": (
                "interface_root_provenance_opposite_same_sign_edge_or_both_"
                "two_two_same_sign_edges_with_independent_centroid_evidence"
            ),
        },
    )


def _adaptive_partner_refinement_edges(
    *,
    nodes: np.ndarray,
    tets: np.ndarray,
    scalar: np.ndarray,
    output_tets: np.ndarray,
    output_parents: np.ndarray,
    base_node_count: int,
    output_node_count: int,
    unique_edges: np.ndarray,
    violating_output_cell_ids: np.ndarray,
    violating_sample_role_ids: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, Mapping[str, object]]:
    """Map failed 15-point partner proofs to current conforming edge stars.

    The proof runs on provisional threshold children, but that provisional cut
    is discarded before retrying.  A generated threshold-root ID must
    therefore never escape as a refinement seed.  Exact child edges are used
    only when both endpoints are nodes of the current input tetrahedron;
    otherwise the deterministic longest input-parent edge is bisected.  The
    latter monotonically reduces that parent's diameter while the complete
    global edge star preserves conformity.
    """

    coordinates = np.asarray(nodes, dtype=np.float64)
    cells = np.asarray(tets, dtype=np.int32)
    level = np.asarray(scalar, dtype=np.float64)
    children = np.asarray(output_tets, dtype=np.int32)
    child_parents = np.asarray(output_parents, dtype=np.int32)
    roots = np.asarray(unique_edges, dtype=np.int32)
    output_ids = np.asarray(violating_output_cell_ids, dtype=np.int64)
    role_ids = np.asarray(violating_sample_role_ids, dtype=np.int64)
    if output_ids.ndim != 1 or role_ids.shape != output_ids.shape:
        _raise(
            "invalid_adaptive_partner_violation_records",
            output_cell_shape=tuple(output_ids.shape),
            role_shape=tuple(role_ids.shape),
        )
    if not len(output_ids):
        _raise("adaptive_partner_refinement_produced_no_cells")
    if np.any(output_ids < 0) or np.any(output_ids >= len(children)):
        _raise("adaptive_partner_violation_output_cell_index_invalid")
    if np.any(role_ids < 0) or np.any(role_ids >= 15):
        _raise("adaptive_partner_violation_sample_role_invalid")
    if np.any(role_ids < 4):
        first = int(np.flatnonzero(role_ids < 4)[0])
        output_cell = int(output_ids[first])
        _raise(
            "adaptive_partner_vertex_violation_has_no_refinement_edge",
            output_cell=output_cell,
            parent_cell=int(child_parents[output_cell]),
            sample_role=int(role_ids[first]),
        )

    interface_begin = int(base_node_count)
    interface_end = interface_begin + len(roots)
    generated_nonroot_nodes = 0
    seeds: list[tuple[int, int]] = []
    parent_ids: list[int] = []
    exact_child_edges = 0
    generated_edge_fallbacks = 0
    centroid_fallbacks = 0

    def parent_edges(parent: int) -> np.ndarray:
        result = np.unique(
            np.sort(cells[int(parent)][_TET_EDGES], axis=1), axis=0
        )
        order = np.lexsort((result[:, 1], result[:, 0]))
        return result[order]

    def longest_parent_edge(parent: int) -> tuple[int, int]:
        candidates = parent_edges(parent)
        lengths = np.linalg.norm(
            coordinates[candidates[:, 1]]
            - coordinates[candidates[:, 0]],
            axis=1,
        )
        if not np.isfinite(lengths).all() or np.any(lengths <= 0.0):
            _raise(
                "invalid_adaptive_partner_parent_edge_length",
                parent_cell=int(parent),
            )
        return tuple(map(int, candidates[int(np.argmax(lengths))]))

    for raw_output_id, raw_role_id in zip(output_ids, role_ids, strict=True):
        output_id = int(raw_output_id)
        role_id = int(raw_role_id)
        parent = int(child_parents[output_id])
        if parent < 0 or parent >= len(cells):
            _raise(
                "adaptive_partner_violation_parent_index_invalid",
                output_cell=output_id,
                parent_cell=parent,
            )
        parent_nodes = set(map(int, cells[parent]))
        for raw_node in children[output_id]:
            node = int(raw_node)
            if node < 0 or node >= int(output_node_count):
                _raise(
                    "adaptive_partner_child_node_index_invalid",
                    output_cell=output_id,
                    parent_cell=parent,
                    node=node,
                    output_nodes=int(output_node_count),
                )
            if node < interface_begin:
                if node not in parent_nodes:
                    _raise(
                        "adaptive_partner_child_node_not_in_parent",
                        output_cell=output_id,
                        parent_cell=parent,
                        node=node,
                    )
                continue
            if node >= interface_end:
                # A non-adaptive side-centroid fan may add provisional nodes
                # after the edge-root registry.  They can participate in the
                # failed proof, but must never become persistent split seeds;
                # the deterministic input-parent fallback below handles them.
                generated_nonroot_nodes += 1
                continue
            if not set(map(int, roots[node - interface_begin])).issubset(
                parent_nodes
            ):
                _raise(
                    "adaptive_partner_root_edge_not_in_parent",
                    output_cell=output_id,
                    parent_cell=parent,
                    node=node,
                )

        seed: tuple[int, int] | None = None
        if 4 <= role_id < 10:
            local_edge = _TET_EDGES[role_id - 4]
            endpoints = tuple(
                sorted(
                    map(
                        int,
                        children[output_id][local_edge],
                    )
                )
            )
            candidates = parent_edges(parent)
            is_parent_edge = np.any(
                np.all(candidates == np.asarray(endpoints), axis=1)
            )
            if (
                endpoints[1] < interface_begin
                and is_parent_edge
                and level[endpoints[0]] * level[endpoints[1]] > 0.0
            ):
                seed = endpoints
                exact_child_edges += 1
            else:
                generated_edge_fallbacks += 1
        else:
            centroid_fallbacks += 1
        if seed is None:
            seed = longest_parent_edge(parent)
        if seed[0] >= interface_begin or seed[1] >= interface_begin:
            _raise(
                "adaptive_partner_refinement_seed_is_generated_node",
                output_cell=output_id,
                parent_cell=parent,
                edge=list(seed),
            )
        seeds.append(tuple(sorted(seed)))
        parent_ids.append(parent)

    refinement_edges = np.unique(
        np.asarray(seeds, dtype=np.int32).reshape((-1, 2)), axis=0
    )
    unique_parents = np.unique(
        np.asarray(parent_ids, dtype=np.int32)
    ).astype(np.int32, copy=False)
    if not len(refinement_edges) or not len(unique_parents):
        _raise("adaptive_partner_refinement_produced_no_edges")
    return (
        np.ascontiguousarray(refinement_edges, dtype=np.int32),
        np.ascontiguousarray(unique_parents, dtype=np.int32),
        {
            "raw_edge_requests": int(len(seeds)),
            "unique_seed_edges": int(len(refinement_edges)),
            "violating_output_children": int(len(output_ids)),
            "unique_input_parent_cells": int(len(unique_parents)),
            "exact_child_parent_edges": int(exact_child_edges),
            "generated_child_edge_longest_parent_fallbacks": int(
                generated_edge_fallbacks
            ),
            "face_or_cell_centroid_longest_parent_fallbacks": int(
                centroid_fallbacks
            ),
            "selection": (
                "exact_base_child_edge_else_deterministic_longest_input_"
                "parent_edge"
            ),
            "provisional_generated_nodes_used_as_seeds": 0,
            "generated_nonroot_child_node_references": int(
                generated_nonroot_nodes
            ),
        },
    )


def _source_face_one_ring(
    source_faces: np.ndarray, raw_mask: np.ndarray
) -> np.ndarray:
    faces = np.asarray(source_faces, dtype=np.int32)
    unsafe = np.asarray(raw_mask, dtype=bool)
    if unsafe.shape != (len(faces),):
        _raise("invalid_unsafe_source_mask")
    edges = np.sort(
        faces[:, ((0, 1), (1, 2), (2, 0))], axis=2
    ).reshape((-1, 2))
    owners = np.repeat(np.arange(len(faces), dtype=np.int32), 3)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    sorted_edges = edges[order]
    starts = np.r_[
        0,
        np.flatnonzero(np.any(sorted_edges[1:] != sorted_edges[:-1], axis=1))
        + 1,
    ]
    counts = np.diff(np.r_[starts, len(order)])
    if np.any(counts != 2):
        _raise(
            "source_surface_edge_not_two_sided",
            edge_groups=int(np.count_nonzero(counts != 2)),
        )
    pairs = owners[order].reshape((-1, 2))
    affected = np.any(unsafe[pairs], axis=1)
    result = unsafe.copy()
    result[pairs[affected].reshape(-1)] = True
    return result


def _canonical_cycle(values: list[int]) -> list[int]:
    sequence = list(dict.fromkeys(map(int, values)))
    if len(sequence) < 3:
        _raise("threshold_polygon_has_fewer_than_three_vertices")
    candidates: list[tuple[int, ...]] = []
    for source in (sequence, list(reversed(sequence))):
        for offset in range(len(source)):
            candidates.append(tuple(source[offset:] + source[:offset]))
    return list(min(candidates))


def _fan(values: list[int]) -> list[tuple[int, int, int]]:
    cycle = _canonical_cycle(values)
    return [
        (cycle[0], cycle[index], cycle[index + 1])
        for index in range(1, len(cycle) - 1)
    ]


def _clip_face(
    face: np.ndarray,
    scalar: np.ndarray,
    crossing: Mapping[int, int],
    *,
    negative: bool,
) -> list[int]:
    source = list(map(int, face))
    result: list[int] = []
    for index, first in enumerate(source):
        second = source[(index + 1) % 3]
        first_inside = scalar[first] < 0.0 if negative else scalar[first] > 0.0
        second_inside = scalar[second] < 0.0 if negative else scalar[second] > 0.0
        if first_inside:
            result.append(first)
        if first_inside != second_inside:
            low, high = sorted((first, second))
            result.append(int(crossing[(low << 32) | high]))
    compact: list[int] = []
    for value in result:
        if not compact or compact[-1] != value:
            compact.append(value)
    if len(compact) > 1 and compact[0] == compact[-1]:
        compact.pop()
    return compact


def _interface_cycle(
    values: list[int], coordinates: np.ndarray, gradient: np.ndarray
) -> list[int]:
    unique = list(dict.fromkeys(map(int, values)))
    if len(unique) < 3:
        _raise("threshold_interface_polygon_too_small")
    points = coordinates[np.asarray(unique, dtype=np.int64)]
    center = points.mean(axis=0)
    normal = np.asarray(gradient, dtype=np.float64)
    length = float(np.linalg.norm(normal))
    if not math.isfinite(length) or length <= 1e-14:
        _raise("threshold_tetrahedron_has_no_scalar_gradient")
    normal /= length
    relative = points - center
    anchor = int(np.argmax(np.linalg.norm(relative, axis=1)))
    axis_u = relative[anchor]
    axis_u /= np.linalg.norm(axis_u)
    axis_v = np.cross(normal, axis_u)
    angles = np.arctan2(relative @ axis_v, relative @ axis_u)
    return _canonical_cycle([unique[index] for index in np.argsort(angles)])


def _structured_triangle_keys(values: np.ndarray) -> np.ndarray:
    dtype = np.dtype([("a", "<i4"), ("b", "<i4"), ("c", "<i4")])
    return np.ascontiguousarray(np.asarray(values, dtype=np.int32)).view(
        dtype
    ).reshape(-1)


def _boundary_vertex_fan_capacity(
    noncrossing_count: int,
    crossing_edge_counts: np.ndarray,
    *,
    threshold_mm: float | None = None,
) -> int:
    """Return the exact adaptive-fan child count and enforce its hard cap.

    A nondegenerate threshold cuts either three or four edges of a
    tetrahedron. The deterministic boundary-vertex fan emits four children
    for the 1/3 sign topology and six for the 2/2 topology, respectively, so
    the exact count per crossed cell is ``2 * edge_count - 2``. The older
    side-centroid fan needed a 16-child allocation bound; retaining that bound
    here would reject valid adaptive partitions before their actual output
    cell count reaches the safety limit.
    """

    counts = np.asarray(crossing_edge_counts)
    if counts.ndim != 1 or not np.issubdtype(counts.dtype, np.integer):
        _raise(
            "invalid_threshold_crossing_edge_counts",
            shape=tuple(counts.shape),
            dtype=str(counts.dtype),
        )
    invalid = ~np.isin(counts, np.asarray((3, 4), dtype=counts.dtype))
    if np.any(invalid):
        _raise(
            "invalid_threshold_crossing_edge_counts",
            values=[int(value) for value in np.unique(counts[invalid])],
        )
    noncrossing = int(noncrossing_count)
    if noncrossing < 0:
        _raise(
            "invalid_threshold_noncrossing_cell_count",
            value=noncrossing,
        )
    three_edge = int(np.count_nonzero(counts == 3))
    four_edge = int(np.count_nonzero(counts == 4))
    capacity = int(
        noncrossing
        + np.sum(2 * counts.astype(np.int64) - 2, dtype=np.int64)
    )
    legacy_worst_case = int(noncrossing + 16 * len(counts))
    if capacity > _MAX_VARIABLE_PARTITION_CELLS:
        threshold_details = (
            {}
            if threshold_mm is None
            else {"threshold_mm": float(threshold_mm)}
        )
        _raise(
            "variable_partition_cell_limit_exceeded",
            **threshold_details,
            phase="preallocation",
            predicted_capacity=capacity,
            exact_capacity=capacity,
            legacy_worst_case_capacity=legacy_worst_case,
            input_cells=int(noncrossing + len(counts)),
            noncrossing_cells=noncrossing,
            crossing_cells=int(len(counts)),
            three_edge_crossing_cells=three_edge,
            four_edge_crossing_cells=four_edge,
            maximum=int(_MAX_VARIABLE_PARTITION_CELLS),
        )
    return capacity


def _adaptive_true_distance_edge_roots(
    *,
    source_mesh: trimesh.Trimesh,
    nodes: np.ndarray,
    node_depth: np.ndarray,
    node_scalar: np.ndarray,
    unique_edges: np.ndarray,
    threshold_mm: float,
    error_limit_mm: float,
    chunk_size: int,
) -> tuple[np.ndarray, np.ndarray, Mapping[str, object]]:
    """Locate the outer-side true-distance root on every crossed edge.

    Linear interpolation of closest-surface distances is not a valid level
    set on a curved mesh.  On coarse tetrahedra it can place an adaptive skin
    interface several tenths of a millimetre too deep even when both endpoint
    distances are exact.  This routine keeps the global shared-edge registry,
    but walks each edge from its shallow endpoint and brackets the *first*
    authoritative distance crossing before bisecting it.

    The march spacing is at most ``2 * error_limit_mm``.  Euclidean distance
    to a closed set is 1-Lipschitz, so an interval whose sampled endpoints are
    both no deeper than the threshold cannot hide an overdepth greater than
    ``error_limit_mm``.  The shallow side of the final bracket is preferred.
    If bisection never moves it away from the original endpoint, the deep
    bracket point is used instead; its possible overdepth is bounded by the
    certified final bracket length.  The existing interface-triangle and
    partner-cell true-distance proofs remain mandatory and still fail closed.
    """

    coordinates = np.asarray(nodes, dtype=np.float64)
    depths = np.asarray(node_depth, dtype=np.float64)
    scalar = np.asarray(node_scalar, dtype=np.float64)
    edges = np.asarray(unique_edges, dtype=np.int32)
    threshold = float(threshold_mm)
    root_level = threshold
    limit = float(error_limit_mm)
    if edges.ndim != 2 or edges.shape[1:] != (2,):
        _raise("invalid_adaptive_crossing_edges", shape=tuple(edges.shape))
    if not len(edges):
        return (
            np.empty((0, 3), dtype=np.float64),
            np.empty(0, dtype=np.float64),
            {
                "method": "outer_first_true_distance_lipschitz_bracket",
                "edges": 0,
                "march_samples": 0,
                "bisection_samples": 0,
                "maximum_march_step_mm": 0.0,
                "maximum_root_underdepth_mm": 0.0,
                "lipschitz_prefix_overdepth_bound_mm": 0.0,
            },
        )
    if (
        coordinates.ndim != 2
        or coordinates.shape[1:] != (3,)
        or depths.shape != (len(coordinates),)
        or scalar.shape != (len(coordinates),)
        or not np.isfinite(coordinates).all()
        or not np.isfinite(depths).all()
        or not np.isfinite(scalar).all()
    ):
        _raise("invalid_adaptive_edge_root_inputs")
    if not math.isfinite(threshold) or threshold <= 0.0:
        _raise("invalid_adaptive_edge_root_threshold", value=threshold_mm)
    if not math.isfinite(limit) or limit <= 0.0:
        _raise("invalid_adaptive_edge_root_limit", value=error_limit_mm)

    edge_scalar = scalar[edges]
    negative = edge_scalar < 0.0
    if np.any(np.sum(negative, axis=1) != 1):
        _raise(
            "adaptive_edge_root_not_bracketed",
            edges=int(len(edges)),
            invalid=int(np.count_nonzero(np.sum(negative, axis=1) != 1)),
        )
    shallow_column = np.argmax(negative, axis=1)
    deep_column = 1 - shallow_column
    row_ids = np.arange(len(edges), dtype=np.int64)
    shallow_ids = edges[row_ids, shallow_column]
    deep_ids = edges[row_ids, deep_column]
    shallow_points = coordinates[shallow_ids].copy()
    deep_points = coordinates[deep_ids].copy()
    shallow_depth = depths[shallow_ids].copy()
    deep_depth = depths[deep_ids].copy()
    if np.any(shallow_depth >= root_level) or np.any(
        deep_depth < root_level
    ):
        _raise("adaptive_edge_root_endpoint_sign_mismatch")

    edge_vectors = deep_points - shallow_points
    edge_lengths = np.linalg.norm(edge_vectors, axis=1)
    if np.any(~np.isfinite(edge_lengths)) or np.any(edge_lengths <= 0.0):
        _raise("invalid_adaptive_crossing_edge_length")
    step_counts = np.maximum(
        1,
        np.ceil(edge_lengths / (2.0 * limit)).astype(np.int64),
    )
    maximum_step = float(np.max(edge_lengths / step_counts, initial=0.0))
    if maximum_step > 2.0 * limit + 1e-12:
        _raise(
            "adaptive_edge_root_march_step_exceeded",
            maximum_step_mm=maximum_step,
            limit_mm=float(2.0 * limit),
        )

    # Retain the original endpoints for a deterministic absolute parameter
    # march.  Moving by a fraction of the current bracket could skip the first
    # crossing when the distance field is non-monotone along an edge.
    origin = shallow_points.copy()
    full_vector = edge_vectors.copy()
    bracket_low = shallow_points.copy()
    bracket_low_depth = shallow_depth.copy()
    bracket_high = deep_points.copy()
    bracket_high_depth = deep_depth.copy()
    found = np.zeros(len(edges), dtype=bool)
    march_samples = 0
    maximum_prefix_upper_bound = 0.0
    maximum_steps = int(np.max(step_counts, initial=0))
    for step_index in range(1, maximum_steps + 1):
        active = np.flatnonzero(~found & (step_counts >= step_index))
        if not len(active):
            break
        if march_samples + len(active) > _MAX_ADAPTIVE_EDGE_ROOT_SAMPLES:
            _raise(
                "adaptive_edge_root_sample_limit_exceeded",
                phase="march",
                samples=int(march_samples + len(active)),
                maximum=int(_MAX_ADAPTIVE_EDGE_ROOT_SAMPLES),
                edges=int(len(edges)),
            )
        fraction = step_index / step_counts[active]
        samples = origin[active] + fraction[:, None] * full_vector[active]
        sample_depth, _sample_face = _closest_source(
            source_mesh,
            samples,
            chunk_size=chunk_size,
        )
        march_samples += int(len(active))
        crossed = sample_depth >= root_level
        if np.any(crossed):
            crossed_ids = active[crossed]
            bracket_high[crossed_ids] = samples[crossed]
            bracket_high_depth[crossed_ids] = sample_depth[crossed]
            found[crossed_ids] = True
        if np.any(~crossed):
            safe_ids = active[~crossed]
            segment_length = np.linalg.norm(
                samples[~crossed] - bracket_low[safe_ids], axis=1
            )
            # For a 1-Lipschitz distance field, the two endpoint cones give
            # this upper bound over the complete segment between samples.
            prefix_upper = 0.5 * (
                bracket_low_depth[safe_ids]
                + sample_depth[~crossed]
                + segment_length
            )
            maximum_prefix_upper_bound = max(
                maximum_prefix_upper_bound,
                float(np.max(prefix_upper, initial=0.0)),
            )
            bracket_low[safe_ids] = samples[~crossed]
            bracket_low_depth[safe_ids] = sample_depth[~crossed]
    if not np.all(found):
        _raise(
            "adaptive_edge_root_first_crossing_not_found",
            edges=int(len(edges)),
            missing=int(np.count_nonzero(~found)),
        )
    march_bracket_low = bracket_low.copy()
    march_bracket_low_depth = bracket_low_depth.copy()
    bisection_samples = 0
    predicted_bisection_samples = int(
        len(edges) * _ADAPTIVE_EDGE_ROOT_BISECTION_PASSES
    )
    if march_samples + predicted_bisection_samples > (
        _MAX_ADAPTIVE_EDGE_ROOT_SAMPLES
    ):
        _raise(
            "adaptive_edge_root_sample_limit_exceeded",
            phase="bisection",
            samples=int(march_samples + predicted_bisection_samples),
            maximum=int(_MAX_ADAPTIVE_EDGE_ROOT_SAMPLES),
            edges=int(len(edges)),
        )
    for _pass in range(_ADAPTIVE_EDGE_ROOT_BISECTION_PASSES):
        midpoint = 0.5 * (bracket_low + bracket_high)
        midpoint_depth, _midpoint_face = _closest_source(
            source_mesh,
            midpoint,
            chunk_size=chunk_size,
        )
        bisection_samples += int(len(midpoint))
        crossed = midpoint_depth >= root_level
        bracket_high[crossed] = midpoint[crossed]
        bracket_high_depth[crossed] = midpoint_depth[crossed]
        bracket_low[~crossed] = midpoint[~crossed]
        bracket_low_depth[~crossed] = midpoint_depth[~crossed]
    root_underdepth = threshold - bracket_low_depth
    maximum_root_underdepth = float(np.max(root_underdepth, initial=0.0))
    final_bracket_lengths = np.linalg.norm(
        bracket_high - bracket_low, axis=1
    )
    maximum_final_bracket = float(
        np.max(final_bracket_lengths, initial=0.0)
    )
    crossing_prefix_length = np.linalg.norm(
        bracket_low - march_bracket_low, axis=1
    )
    crossing_prefix_upper = 0.5 * (
        march_bracket_low_depth
        + bracket_low_depth
        + crossing_prefix_length
    )
    maximum_prefix_upper_bound = max(
        maximum_prefix_upper_bound,
        float(np.max(crossing_prefix_upper, initial=0.0)),
    )
    if maximum_prefix_upper_bound > threshold + limit + 1e-12:
        _raise(
            "adaptive_edge_root_prefix_not_certified",
            threshold_mm=threshold,
            maximum_certified_upper_depth_mm=maximum_prefix_upper_bound,
            limit_mm=limit,
        )
    # Since the high endpoint is deeper than the threshold and distance is
    # 1-Lipschitz, the shallow endpoint cannot be farther below the threshold
    # than the remaining spatial bracket length.
    if np.any(root_underdepth < -1e-12) or np.any(
        root_underdepth > final_bracket_lengths + 1e-12
    ):
        _raise(
            "adaptive_edge_root_bisection_not_certified",
            maximum_underdepth_mm=maximum_root_underdepth,
            maximum_bracket_length_mm=maximum_final_bracket,
        )
    low_displacement = np.linalg.norm(bracket_low - origin, axis=1)
    use_deep_bound = low_displacement <= 1e-15
    if np.any(use_deep_bound):
        deep_interval_upper = 0.5 * (
            bracket_low_depth[use_deep_bound]
            + bracket_high_depth[use_deep_bound]
            + final_bracket_lengths[use_deep_bound]
        )
        maximum_prefix_upper_bound = max(
            maximum_prefix_upper_bound,
            float(np.max(deep_interval_upper, initial=0.0)),
        )
        if maximum_prefix_upper_bound > threshold + limit + 1e-12:
            _raise(
                "adaptive_edge_root_deep_interval_not_certified",
                threshold_mm=threshold,
                maximum_certified_upper_depth_mm=(
                    maximum_prefix_upper_bound
                ),
                limit_mm=limit,
            )
    certified_nudge_limit = np.minimum(0.25 * limit, 0.25 * edge_lengths)
    if np.any(
        use_deep_bound
        & (final_bracket_lengths > certified_nudge_limit + 1e-12)
    ):
        _raise(
            "adaptive_edge_root_deep_bound_nudge_exceeded",
            maximum_nudge_mm=float(
                np.max(final_bracket_lengths[use_deep_bound], initial=0.0)
            ),
            maximum_allowed_mm=float(
                np.max(certified_nudge_limit[use_deep_bound], initial=0.0)
            ),
        )
    selected_points = bracket_low.copy()
    selected_depth = bracket_low_depth.copy()
    selected_points[use_deep_bound] = bracket_high[use_deep_bound]
    selected_depth[use_deep_bound] = bracket_high_depth[use_deep_bound]
    selected_overdepth = np.maximum(selected_depth - threshold, 0.0)
    if np.any(selected_overdepth > final_bracket_lengths + 1e-12):
        _raise(
            "adaptive_edge_root_deep_bound_not_certified",
            maximum_overdepth_mm=float(
                np.max(selected_overdepth, initial=0.0)
            ),
            maximum_bracket_length_mm=maximum_final_bracket,
        )
    return (
        np.ascontiguousarray(selected_points, dtype=np.float64),
        np.ascontiguousarray(selected_depth, dtype=np.float64),
        {
            "method": "outer_first_true_distance_lipschitz_bracket",
            "edges": int(len(edges)),
            "march_samples": int(march_samples),
            "bisection_samples": int(bisection_samples),
            "bisection_passes": int(_ADAPTIVE_EDGE_ROOT_BISECTION_PASSES),
            "maximum_march_step_mm": maximum_step,
            "maximum_root_underdepth_mm": maximum_root_underdepth,
            "maximum_final_bracket_length_mm": maximum_final_bracket,
            "maximum_certified_prefix_depth_mm": float(
                maximum_prefix_upper_bound
            ),
            "lipschitz_prefix_overdepth_bound_mm": limit,
            "returned_root_side": "shallow_or_certified_deep_bound",
            "deep_bound_substituted_edges": int(
                np.count_nonzero(use_deep_bound)
            ),
            "zero_fraction_policy": "certified_shallow_lipschitz_nudge",
            "maximum_substituted_shallow_underdepth_mm": float(
                np.max(root_underdepth[use_deep_bound], initial=0.0)
            ),
            "maximum_deep_bound_nudge_mm": float(
                np.max(final_bracket_lengths[use_deep_bound], initial=0.0)
            ),
            "maximum_deep_bound_nudge_limit_mm": float(
                np.max(certified_nudge_limit[use_deep_bound], initial=0.0)
            ),
            "maximum_returned_overdepth_mm": float(
                np.max(selected_overdepth, initial=0.0)
            ),
        },
    )


def _build_threshold_partition(
    *,
    source: ColorDepthSourceSurface,
    source_mesh: trimesh.Trimesh,
    recipes: Mapping[int, ColorDepthRecipe],
    threshold_mm: float,
    outer_by_label: Mapping[int, int],
    backing_by_label: Mapping[int, int],
    nodes: np.ndarray,
    tets: np.ndarray,
    owner_labels: np.ndarray,
    owner_source_faces: np.ndarray,
    boundary_faces: np.ndarray,
    boundary_cells: np.ndarray,
    boundary_labels: np.ndarray,
    boundary_parent_faces: np.ndarray,
    node_depth: np.ndarray | None,
    parent_depth_bounds_mm: np.ndarray | None = None,
    parent_materials: np.ndarray | None = None,
    initial_parent_unsafe: np.ndarray | None = None,
    material_changing_labels: frozenset[int] | None = None,
    use_boundary_vertex_fan: bool = False,
    localize_unsafe_partner_columns: bool = False,
    error_limit_mm: float,
    chunk_size: int,
    progress: Callable[..., object] | None,
) -> tuple[ConformingColorDepthPartition, np.ndarray]:
    if node_depth is None:
        node_depth, _node_closest = _closest_source(
            source_mesh, nodes, chunk_size=chunk_size
        )
    else:
        node_depth = np.asarray(node_depth, dtype=np.float64).copy()
        if node_depth.shape != (len(nodes),) or not np.isfinite(node_depth).all():
            _raise(
                "invalid_precomputed_node_depth",
                expected=(int(len(nodes)),),
                actual=tuple(node_depth.shape),
            )
    boundary_node_ids = np.unique(boundary_faces)
    node_depth[boundary_node_ids] = 0.0
    scalar = node_depth - float(threshold_mm)
    changing_labels = (
        frozenset(int(value) for value in owner_labels)
        if material_changing_labels is None
        else frozenset(int(value) for value in material_changing_labels)
    )
    near_zero = np.abs(scalar) <= 1e-12
    if localize_unsafe_partner_columns:
        # In adaptive mode an authoritative node exactly on the requested
        # level belongs to the deep side.  Truly shallower near-zero nodes stay
        # shallow and are handled by the certified deep-bracket fallback if
        # their first root is too close for the bisection's shallow endpoint
        # to move.  Legacy single-threshold behaviour is unchanged.
        scalar[near_zero] = np.where(
            scalar[near_zero] < 0.0,
            -1e-12,
            1e-12,
        )
    else:
        scalar[near_zero] = np.where(
            scalar[near_zero] <= 0.0,
            -1e-12,
            1e-12,
        )

    values = scalar[tets]
    has_negative = np.min(values, axis=1) < 0.0
    has_positive = np.max(values, axis=1) > 0.0
    crossing_ids = np.flatnonzero(has_negative & has_positive)
    crossing_edges_raw = tets[crossing_ids][:, _TET_EDGES]
    edge_values = scalar[crossing_edges_raw]
    edge_crosses = edge_values[:, :, 0] * edge_values[:, :, 1] < 0.0
    crossing_edges = np.sort(crossing_edges_raw[edge_crosses], axis=1)
    if len(crossing_edges):
        unique_edges, crossing_edge_inverse = np.unique(
            crossing_edges, axis=0, return_inverse=True
        )
        first_value = scalar[unique_edges[:, 0]]
        second_value = scalar[unique_edges[:, 1]]
        fraction = first_value / (first_value - second_value)
        interface_points = nodes[unique_edges[:, 0]] + fraction[:, None] * (
            nodes[unique_edges[:, 1]] - nodes[unique_edges[:, 0]]
        )
    else:
        unique_edges = np.empty((0, 2), dtype=np.int32)
        crossing_edge_inverse = np.empty(0, dtype=np.int64)
        interface_points = np.empty((0, 3), dtype=np.float64)
    edge_root_record: Mapping[str, object] = {
        "method": "affine_nodal_distance_interpolation",
        "edges": int(len(unique_edges)),
        "march_samples": 0,
        "bisection_samples": 0,
    }
    if localize_unsafe_partner_columns and len(unique_edges):
        (
            true_root_points,
            _true_root_distance,
            edge_root_record,
        ) = _adaptive_true_distance_edge_roots(
            source_mesh=source_mesh,
            nodes=nodes,
            node_depth=node_depth,
            node_scalar=scalar,
            unique_edges=unique_edges,
            threshold_mm=threshold_mm,
            error_limit_mm=error_limit_mm,
            chunk_size=chunk_size,
        )
        # Independent true roots on the four crossed edges of a 2/2-sign
        # tetrahedron are generally non-coplanar.  Substituting those points
        # directly would violate the piecewise-affine level-set assumption and
        # can create degenerate, overlapping, or volume-drifting child tets.
        # Instead, turn every outer-first root into a constraint on its shared
        # positive endpoint scalar.  Raising that one nodal scalar moves the
        # affine edge crossing to the root or shallower.  Taking the maximum
        # constraint across all incident edges leaves one scalar per global
        # node, so every per-tet interface remains planar and conforming.
        edge_scalar = scalar[unique_edges]
        shallow_column = np.argmin(edge_scalar, axis=1)
        deep_column = 1 - shallow_column
        row_ids = np.arange(len(unique_edges), dtype=np.int64)
        shallow_ids = unique_edges[row_ids, shallow_column]
        deep_ids = unique_edges[row_ids, deep_column]
        shallow_points = nodes[shallow_ids]
        edge_vectors = nodes[deep_ids] - shallow_points
        edge_length_squared = np.einsum(
            "ij,ij->i", edge_vectors, edge_vectors
        )
        root_fraction = np.einsum(
            "ij,ij->i", true_root_points - shallow_points, edge_vectors
        ) / edge_length_squared
        if np.any(~np.isfinite(root_fraction)) or np.any(
            (root_fraction <= 0.0) | (root_fraction >= 1.0)
        ):
            _raise(
                "adaptive_edge_root_fraction_invalid",
                minimum=float(np.min(root_fraction, initial=math.inf)),
                maximum=float(np.max(root_fraction, initial=-math.inf)),
            )
        negative_magnitude = -scalar[shallow_ids]
        required_positive = (
            negative_magnitude
            * (1.0 - root_fraction)
            / root_fraction
        )
        if np.any(~np.isfinite(required_positive)) or np.any(
            required_positive <= 0.0
        ):
            _raise("adaptive_edge_root_scalar_constraint_invalid")
        original_scalar = scalar.copy()
        np.maximum.at(scalar, deep_ids, required_positive)
        if np.any(scalar[shallow_ids] >= 0.0) or np.any(
            scalar[deep_ids] <= 0.0
        ):
            _raise("adaptive_edge_root_scalar_sign_changed")
        first_value = scalar[unique_edges[:, 0]]
        second_value = scalar[unique_edges[:, 1]]
        fraction = first_value / (first_value - second_value)
        interface_points = nodes[unique_edges[:, 0]] + fraction[:, None] * (
            nodes[unique_edges[:, 1]] - nodes[unique_edges[:, 0]]
        )
        applied_fraction = np.where(
            shallow_column == 0,
            fraction,
            1.0 - fraction,
        )
        if np.any(applied_fraction > root_fraction + 1e-12):
            _raise(
                "adaptive_edge_root_scalar_constraint_not_applied",
                maximum_fraction_excess=float(
                    np.max(
                        applied_fraction - root_fraction,
                        initial=0.0,
                    )
                ),
            )
        edge_root_record = {
            **dict(edge_root_record),
            "application": "conservative_positive_nodal_scalar_elevation",
            "direct_nonplanar_root_points_used": False,
            "shared_piecewise_affine_level_set_preserved": True,
            "constrained_positive_nodes": int(
                np.count_nonzero(scalar > original_scalar + 1e-15)
            ),
            "maximum_positive_scalar_elevation_mm": float(
                np.max(scalar - original_scalar, initial=0.0)
            ),
            "maximum_edge_fraction_retreat": float(
                np.max(
                    root_fraction - applied_fraction,
                    initial=0.0,
                )
            ),
        }
    interface_distance, interface_closest_face = _closest_source(
        source_mesh, interface_points, chunk_size=chunk_size
    )
    interface_error = np.abs(interface_distance - float(threshold_mm))
    crossing_counts = edge_crosses.sum(axis=1)
    crossing_parent_for_edge = np.repeat(crossing_ids, crossing_counts)
    interface_relevant = np.zeros(len(unique_edges), dtype=bool)
    if len(crossing_parent_for_edge):
        np.logical_or.at(
            interface_relevant,
            crossing_edge_inverse,
            np.isin(
                owner_labels[crossing_parent_for_edge],
                np.asarray(tuple(changing_labels), dtype=np.int32),
            ),
        )
    raw_unsafe_source = np.zeros(len(source.faces), dtype=bool)
    bad_interface = interface_relevant & (
        interface_error > float(error_limit_mm) + 1e-12
    )
    raw_unsafe_source[interface_closest_face[bad_interface]] = True
    unsafe_source = _source_face_one_ring(source.faces, raw_unsafe_source)
    # A threshold pass changes material only for its scheduled owner labels.
    # One-ring expansion may cross a visible colour boundary; carrying that
    # fallback into a label whose own depth has not been processed would
    # permanently erase its later backing region.  Keep the geometric safety
    # ring, but apply outer-only fallback only to source owners whose material
    # actually changes in this pass.  Other labels are independently checked
    # when their own threshold is processed.
    changing_source = np.isin(
        np.asarray(source.face_target_labels, dtype=np.int32),
        np.asarray(tuple(changing_labels), dtype=np.int32),
    )
    unsafe_source &= changing_source
    interface_unsafe = interface_relevant & (
        unsafe_source[interface_closest_face]
        | (interface_error > float(error_limit_mm) + 1e-12)
    )

    centers = nodes[tets].mean(axis=1)
    _center_depth, closest_parent_face = _closest_source(
        source_mesh, centers, chunk_size=chunk_size
    )
    parent_source_face = np.asarray(owner_source_faces, dtype=np.int32).copy()
    unset = parent_source_face < 0
    parent_source_face[unset] = closest_parent_face[unset]
    # New fallback discovered by this pass belongs only to labels whose
    # physical material changes at this threshold.  ``parent_source_face`` is
    # a proximity/provenance representative and can legitimately point across
    # a paint boundary for an interior cell; using it without the owner gate
    # would mark a later-band owner unsafe before that owner's own threshold is
    # evaluated, permanently suppressing its backing material.
    changing_owner = np.isin(
        np.asarray(owner_labels, dtype=np.int32),
        np.asarray(tuple(changing_labels), dtype=np.int32),
    )
    parent_unsafe = unsafe_source[parent_source_face] & changing_owner
    if initial_parent_unsafe is not None:
        inherited_unsafe = np.asarray(initial_parent_unsafe)
        if inherited_unsafe.shape != (len(tets),) or inherited_unsafe.dtype.kind != "b":
            _raise(
                "invalid_initial_parent_unsafe",
                expected=(int(len(tets)),),
                actual=tuple(inherited_unsafe.shape),
            )
        parent_unsafe |= inherited_unsafe
    boundary_face_unsafe = unsafe_source[boundary_parent_faces] & np.isin(
        boundary_labels,
        np.asarray(tuple(changing_labels), dtype=np.int32),
    )
    np.logical_or.at(
        parent_unsafe,
        boundary_cells,
        boundary_face_unsafe & changing_owner[boundary_cells],
    )
    if np.any(~parent_unsafe[boundary_cells[boundary_face_unsafe]]):
        _raise("boundary_unsafe_or_aggregation_failed")
    if len(crossing_parent_for_edge):
        unsafe_crossing_edge = interface_unsafe[crossing_edge_inverse] & np.isin(
            owner_labels[crossing_parent_for_edge],
            np.asarray(tuple(changing_labels), dtype=np.int32),
        )
        np.logical_or.at(
            parent_unsafe,
            crossing_parent_for_edge,
            unsafe_crossing_edge,
        )

    base_node_count = len(nodes)
    edge_node_ids = np.arange(
        base_node_count,
        base_node_count + len(unique_edges),
        dtype=np.int32,
    )
    crossing_registry = {
        (int(edge[0]) << 32) | int(edge[1]): int(node_id)
        for edge, node_id in zip(unique_edges, edge_node_ids, strict=True)
    }
    side_centroid_count = 0 if use_boundary_vertex_fan else 2 * len(crossing_ids)
    all_coordinates = np.empty(
        (len(nodes) + len(interface_points) + side_centroid_count, 3),
        dtype=np.float64,
    )
    all_coordinates[: len(nodes)] = nodes
    all_coordinates[
        len(nodes) : len(nodes) + len(interface_points)
    ] = interface_points
    all_node_depth = np.empty(len(all_coordinates), dtype=np.float64)
    all_node_depth[: len(nodes)] = node_depth
    all_node_depth[
        len(nodes) : len(nodes) + len(interface_points)
    ] = interface_distance
    noncrossing = np.flatnonzero(~(has_negative & has_positive))
    capacity = (
        _boundary_vertex_fan_capacity(
            len(noncrossing),
            crossing_counts,
            threshold_mm=threshold_mm,
        )
        if use_boundary_vertex_fan
        else int(len(noncrossing) + 16 * len(crossing_ids))
    )
    output_tets = np.empty((capacity, 4), dtype=np.int32)
    output_parents = np.empty(capacity, dtype=np.int32)
    output_side = np.empty(capacity, dtype=np.int8)
    output_owner = np.empty(capacity, dtype=np.int32)
    output_source_face = np.empty(capacity, dtype=np.int32)
    output_unsafe = np.empty(capacity, dtype=bool)
    output_localized = np.empty(capacity, dtype=bool)
    output_material = np.empty(capacity, dtype=np.int8)
    output_bounds = np.empty((capacity, 2), dtype=np.float64)
    interface_triangles = np.empty(
        (2 * len(crossing_ids), 3), dtype=np.int32
    )
    interface_parent = np.empty(2 * len(crossing_ids), dtype=np.int32)
    cursor = 0
    interface_cursor = 0
    side_centroid_depth_error = 0.0
    maximum_depth = max(
        float(np.max(node_depth, initial=0.0)),
        threshold_mm,
        max(
            float(recipe.outer_thickness_mm)
            for recipe in recipes.values()
        ),
    )
    if parent_depth_bounds_mm is None:
        parent_bounds = None
    else:
        parent_bounds = np.asarray(parent_depth_bounds_mm, dtype=np.float64)
        if (
            parent_bounds.shape != (len(tets), 2)
            or not np.isfinite(parent_bounds).all()
            or np.any(parent_bounds < 0.0)
            or np.any(parent_bounds[:, 1] < parent_bounds[:, 0])
        ):
            _raise(
                "invalid_parent_depth_bounds",
                expected=(int(len(tets)), 2),
                actual=tuple(parent_bounds.shape),
            )
        maximum_depth = max(maximum_depth, float(np.max(parent_bounds[:, 1], initial=0.0)))
    if parent_materials is None:
        inherited_materials = None
    else:
        inherited_materials = np.asarray(parent_materials)
        if (
            inherited_materials.shape != (len(tets),)
            or not np.issubdtype(inherited_materials.dtype, np.integer)
            or any(not 1 <= int(value) <= 4 for value in np.unique(inherited_materials))
        ):
            _raise(
                "invalid_parent_materials",
                expected=(int(len(tets)),),
                actual=tuple(inherited_materials.shape),
            )
        inherited_materials = np.asarray(inherited_materials, dtype=np.int8)

    def append_child(
        values: tuple[int, int, int, int], parent: int, side: int
    ) -> None:
        nonlocal cursor
        if cursor >= capacity:
            _raise("threshold_child_capacity_exceeded")
        candidate = np.asarray(values, dtype=np.int32)
        points = all_coordinates[candidate]
        signed = float(
            np.dot(
                points[1] - points[0],
                np.cross(points[2] - points[0], points[3] - points[0]),
            )
        )
        if signed < 0.0:
            candidate[[1, 2]] = candidate[[2, 1]]
            signed = -signed
        if not math.isfinite(signed) or signed <= 0.0:
            _raise(
                "degenerate_threshold_child",
                parent_cell=int(parent),
                signed_six=signed,
            )
        label = int(owner_labels[parent])
        unsafe = bool(parent_unsafe[parent])
        # Multi-threshold adaptive skins must never turn an inaccurate source
        # owner column into partner material for its complete depth.  The
        # legacy single-threshold provider intentionally keeps that
        # outer-only fallback, but the adaptive path localises a rejected
        # interface to the already-conforming shallow/deep children and proves
        # below that no partner child reaches past its requested depth.
        localized = bool(unsafe and localize_unsafe_partner_columns)
        material = (
            int(outer_by_label[label])
            if inherited_materials is None
            else int(inherited_materials[parent])
        )
        if label in changing_labels:
            material = int(outer_by_label[label])
            if side > 0 and not unsafe:
                material = int(backing_by_label[label])
            if side > 0 and localized:
                material = int(backing_by_label[label])
        if unsafe and not localized:
            material = int(outer_by_label[label])
        output_tets[cursor] = candidate
        output_parents[cursor] = parent
        output_side[cursor] = side
        output_owner[cursor] = label
        output_source_face[cursor] = int(parent_source_face[parent])
        output_unsafe[cursor] = bool(unsafe and not localized)
        output_localized[cursor] = localized
        output_material[cursor] = material
        if unsafe and not localized:
            output_bounds[cursor] = (
                0.0,
                float(recipes[label].outer_thickness_mm),
            )
        elif label not in changing_labels:
            # A global geometric threshold is only a material/depth boundary
            # for the owner labels scheduled in this pass.  Other owners may
            # be subdivided for conformity, but carrying this unrelated band
            # into their semantic recipe interval can invert bounds when their
            # own threshold is processed later.  Preserve their interval
            # unchanged until the pass that actually changes their material.
            output_bounds[cursor] = (
                (0.0, maximum_depth)
                if parent_bounds is None
                else parent_bounds[parent]
            )
        elif parent_bounds is None:
            output_bounds[cursor] = (
                (0.0, threshold_mm)
                if side < 0
                else (threshold_mm, maximum_depth)
            )
        else:
            low, high = map(float, parent_bounds[parent])
            child_bounds = (
                (low, min(high, threshold_mm))
                if side < 0
                else (max(low, threshold_mm), high)
            )
            if child_bounds[1] + 1e-12 < child_bounds[0]:
                _raise(
                    "threshold_child_depth_bounds_inverted",
                    parent_cell=int(parent),
                    threshold_mm=float(threshold_mm),
                    parent_bounds_mm=(low, high),
                    child_bounds_mm=child_bounds,
                )
            output_bounds[cursor] = child_bounds
        cursor += 1

    for parent in map(int, noncrossing):
        side = -1 if bool(has_negative[parent]) else 1
        append_child(tuple(map(int, tets[parent])), parent, side)

    centroid_base = len(nodes) + len(interface_points)
    for sequence, parent in enumerate(map(int, crossing_ids)):
        tet = tets[parent]
        affine = np.column_stack((nodes[tet], np.ones(4)))
        try:
            coefficients = np.linalg.solve(affine, scalar[tet])
        except np.linalg.LinAlgError:
            _raise("singular_threshold_tetrahedron", parent_cell=parent)
        gradient = coefficients[:3]
        interface_ids: list[int] = []
        for edge in tet[_TET_EDGES]:
            first, second = map(int, edge)
            if scalar[first] * scalar[second] < 0.0:
                low, high = sorted((first, second))
                interface_ids.append(crossing_registry[(low << 32) | high])
        cycle = _interface_cycle(interface_ids, all_coordinates, gradient)
        for triangle in _fan(cycle):
            interface_triangles[interface_cursor] = triangle
            interface_parent[interface_cursor] = parent
            interface_cursor += 1
        for side in (-1, 1):
            polygons: list[list[int]] = []
            for local_face in _TET_FACES:
                polygon = _clip_face(
                    tet[local_face],
                    scalar,
                    crossing_registry,
                    negative=side < 0,
                )
                if len(polygon) >= 3:
                    polygons.append(polygon)
            polygons.append(cycle)
            used = np.unique(
                np.asarray(
                    [value for polygon in polygons for value in polygon],
                    dtype=np.int32,
                )
            )
            if use_boundary_vertex_fan:
                # A clipped tetrahedron is convex.  Coning every boundary
                # polygon not incident to one deterministic boundary vertex
                # fills it exactly without introducing a side centroid.  The
                # polygon triangulation remains the same canonical global-ID
                # fan on both neighbouring cells, so the cell complex stays
                # conforming while avoiding exponential centroid growth over
                # four-to-six threshold passes.
                anchor = int(np.min(used))
                emitted = 0
                for polygon in polygons:
                    if anchor in polygon:
                        continue
                    for triangle in _fan(polygon):
                        append_child(
                            (
                                triangle[0],
                                triangle[1],
                                triangle[2],
                                anchor,
                            ),
                            parent,
                            side,
                        )
                        emitted += 1
                if emitted < 1:
                    _raise(
                        "threshold_boundary_vertex_fan_empty",
                        parent_cell=int(parent),
                        side=int(side),
                    )
                continue
            centroid_id = centroid_base + 2 * sequence + (0 if side < 0 else 1)
            all_coordinates[centroid_id] = all_coordinates[used].mean(axis=0)
            centroid_depth = float(np.mean(all_node_depth[used]))
            all_node_depth[centroid_id] = centroid_depth
            side_centroid_depth_error = max(
                side_centroid_depth_error,
                abs(centroid_depth - float(np.mean(all_node_depth[used]))),
            )
            for polygon in polygons:
                for triangle in _fan(polygon):
                    append_child(
                        (
                            triangle[0],
                            triangle[1],
                            triangle[2],
                            centroid_id,
                        ),
                        parent,
                        side,
                    )
        if (sequence + 1) % 50_000 == 0:
            _progress(
                progress,
                "color_depth_exact_split",
                0.40 + 0.25 * (sequence + 1) / max(len(crossing_ids), 1),
                f"ColorDepth conforming split {sequence + 1}/{len(crossing_ids)}",
            )

    side_centroid_ids = np.arange(
        centroid_base,
        centroid_base + side_centroid_count,
        dtype=np.int32,
    )
    if len(side_centroid_ids):
        true_centroid_depth, _true_centroid_face = _closest_source(
            source_mesh,
            all_coordinates[side_centroid_ids],
            chunk_size=chunk_size,
        )
        side_centroid_depth_error = float(
            np.max(
                np.abs(
                    true_centroid_depth - all_node_depth[side_centroid_ids]
                ),
                initial=0.0,
            )
        )
        all_node_depth[side_centroid_ids] = true_centroid_depth

    if use_boundary_vertex_fan and cursor != capacity:
        _raise(
            "threshold_boundary_vertex_fan_child_count_mismatch",
            expected_cells=int(capacity),
            actual_cells=int(cursor),
            input_cells=int(len(tets)),
            crossing_cells=int(len(crossing_ids)),
        )
    output_tets = output_tets[:cursor].copy()
    output_parents = output_parents[:cursor].copy()
    output_side = output_side[:cursor].copy()
    output_owner = output_owner[:cursor].copy()
    output_source_face = output_source_face[:cursor].copy()
    output_unsafe = output_unsafe[:cursor].copy()
    output_localized = output_localized[:cursor].copy()
    output_material = output_material[:cursor].copy()
    output_bounds = output_bounds[:cursor].copy()
    interface_triangles = interface_triangles[:interface_cursor].copy()
    interface_parent = interface_parent[:interface_cursor].copy()
    if (
        use_boundary_vertex_fan
        and len(output_tets) > _MAX_VARIABLE_PARTITION_CELLS
    ):
        _raise(
            "variable_partition_cell_limit_exceeded",
            phase="post_split",
            output_cells=int(len(output_tets)),
            maximum=int(_MAX_VARIABLE_PARTITION_CELLS),
        )

    raw, order, starts, counts = _cell_face_table(output_tets)
    if np.any(counts > 2):
        _raise(
            "threshold_split_nonmanifold_cell_complex",
            faces=int(np.count_nonzero(counts > 2)),
        )
    exterior_rows = order[starts[counts == 1]]
    exterior_faces = raw[exterior_rows]
    exterior_cells = (exterior_rows // 4).astype(np.int32)
    expected_keys = np.sort(boundary_faces, axis=1)
    actual_keys = np.sort(exterior_faces, axis=1)
    expected_order = np.lexsort(
        (expected_keys[:, 2], expected_keys[:, 1], expected_keys[:, 0])
    )
    actual_order = np.lexsort(
        (actual_keys[:, 2], actual_keys[:, 1], actual_keys[:, 0])
    )
    if (
        len(expected_keys) != len(actual_keys)
        or not np.array_equal(
            expected_keys[expected_order], actual_keys[actual_order]
        )
    ):
        _raise("threshold_split_changed_visible_exterior")
    label_by_key = {
        tuple(map(int, key)): int(label)
        for key, label in zip(expected_keys, boundary_labels, strict=True)
    }
    parent_by_key = {
        tuple(map(int, key)): int(parent)
        for key, parent in zip(expected_keys, boundary_parent_faces, strict=True)
    }
    expected_exterior_labels = np.asarray(
        [label_by_key[tuple(map(int, key))] for key in actual_keys],
        dtype=np.int32,
    )
    exterior_parent_faces = np.asarray(
        [parent_by_key[tuple(map(int, key))] for key in actual_keys],
        dtype=np.int32,
    )
    if not np.array_equal(
        output_owner[exterior_cells], expected_exterior_labels
    ):
        _raise("threshold_split_changed_visible_owner")
    expected_outer = np.asarray(
        [outer_by_label[int(label)] for label in expected_exterior_labels],
        dtype=np.int8,
    )
    if not np.array_equal(output_material[exterior_cells], expected_outer):
        _raise("threshold_split_exposed_backing_material")

    source_volume = float(_tet_volumes(nodes, tets).sum())
    child_volume = _tet_volumes(all_coordinates, output_tets)
    output_volume = float(child_volume.sum())
    volume_error = abs(output_volume - source_volume)
    if volume_error > 1e-10 * max(source_volume, 1.0):
        _raise(
            "threshold_split_volume_drift",
            source_volume_mm3=source_volume,
            output_volume_mm3=output_volume,
            volume_error_mm3=volume_error,
        )

    if len(interface_triangles):
        interface_vertex_ids = np.unique(interface_triangles)
        expected_interface_ids = np.arange(
            base_node_count,
            base_node_count + len(interface_points),
            dtype=np.int32,
        )
        if not np.array_equal(interface_vertex_ids, expected_interface_ids):
            _raise("threshold_interface_vertex_registry_incomplete")
        unique_keys = np.sort(raw[order[starts]], axis=1)
        threshold_keys = np.sort(interface_triangles, axis=1)
        unique_struct = _structured_triangle_keys(unique_keys)
        threshold_struct = _structured_triangle_keys(threshold_keys)
        positions = np.searchsorted(unique_struct, threshold_struct)
        if (
            np.any(positions >= len(unique_struct))
            or not np.array_equal(unique_struct[positions], threshold_struct)
        ):
            _raise("threshold_triangle_missing_from_final_cells")
        if np.any(counts[positions] != 2):
            _raise("threshold_triangle_not_two_sided")
        first_rows = order[starts[positions]]
        second_rows = order[starts[positions] + 1]
        first_cells = first_rows // 4
        second_cells = second_rows // 4
        interface_local = np.full(len(all_coordinates), -1, dtype=np.int32)
        interface_local[interface_vertex_ids] = np.arange(
            len(interface_vertex_ids), dtype=np.int32
        )
        triangle_local = interface_local[interface_triangles]
        triangle_error = interface_error[triangle_local].max(axis=1)
        triangle_relevant = np.isin(
            owner_labels[interface_parent],
            np.asarray(tuple(changing_labels), dtype=np.int32),
        )
        triangle_unsafe = triangle_relevant & (
            interface_unsafe[triangle_local].any(axis=1)
            | (triangle_error > float(error_limit_mm) + 1e-12)
        )
        triangle_unsafe |= parent_unsafe[interface_parent]
        material_changes = (
            output_material[first_cells] != output_material[second_cells]
        )
        unsafe_changing = triangle_unsafe & material_changes
        if np.any(unsafe_changing) and not localize_unsafe_partner_columns:
            _raise(
                "unsafe_threshold_triangle_changes_material",
                faces=int(np.count_nonzero(unsafe_changing)),
            )
        changing_error = triangle_error[material_changes]
        changing_vertex_depth = interface_distance[triangle_local].max(axis=1)[
            material_changes
        ]
        changing_interface_depth = changing_vertex_depth
        adaptive_interface_sample_count = 0
        changing_interior_depth = np.empty(0, dtype=np.float64)
        changing_sample_argmax = np.empty(0, dtype=np.int8)
        changing_sample_violations = np.empty((0, 7), dtype=bool)
        changing_sample_maximum_by_role = np.zeros(7, dtype=np.float64)
        if localize_unsafe_partner_columns and np.any(material_changes):
            # The exact source distance is nonlinear along the affine level-set
            # triangle.  Vertex-only checks therefore do not prove that its
            # interior stays inside the requested partner depth.  Sample all
            # vertices, all three edge midpoints, and the face centroid with
            # the authoritative closest-source query.  This remains an
            # intentionally conservative fail-closed gate; it does not change
            # the emitted conforming interface geometry.
            changing_ids = np.flatnonzero(material_changes)
            sampled_maxima: list[np.ndarray] = []
            sampled_interior_maxima: list[np.ndarray] = []
            sampled_argmax: list[np.ndarray] = []
            sampled_violations: list[np.ndarray] = []
            triangle_batch = max(1, int(chunk_size) // 7)
            for start in range(0, len(changing_ids), triangle_batch):
                batch_ids = changing_ids[start : start + triangle_batch]
                points = all_coordinates[interface_triangles[batch_ids]]
                samples = np.concatenate(
                    (
                        points,
                        0.5 * (points[:, 0:1] + points[:, 1:2]),
                        0.5 * (points[:, 0:1] + points[:, 2:3]),
                        0.5 * (points[:, 1:2] + points[:, 2:3]),
                        points.mean(axis=1, keepdims=True),
                    ),
                    axis=1,
                )
                true_depth, _true_face = _closest_source(
                    source_mesh,
                    samples.reshape((-1, 3)),
                    chunk_size=chunk_size,
                )
                sampled = true_depth.reshape((len(batch_ids), 7))
                sampled_maxima.append(sampled.max(axis=1))
                sampled_interior_maxima.append(sampled[:, 3:].max(axis=1))
                sampled_argmax.append(
                    np.asarray(sampled.argmax(axis=1), dtype=np.int8)
                )
                sampled_violations.append(
                    sampled
                    > float(threshold_mm) + float(error_limit_mm) + 1e-12
                )
                changing_sample_maximum_by_role = np.maximum(
                    changing_sample_maximum_by_role,
                    np.max(sampled, axis=0, initial=0.0),
                )
                adaptive_interface_sample_count += int(7 * len(batch_ids))
            changing_interface_depth = np.concatenate(sampled_maxima)
            changing_interior_depth = np.concatenate(
                sampled_interior_maxima
            )
            changing_sample_argmax = np.concatenate(sampled_argmax)
            changing_sample_violations = np.concatenate(
                sampled_violations, axis=0
            )
        maximum_changing_overdepth = float(
            np.max(
                changing_interface_depth - float(threshold_mm),
                initial=0.0,
            )
        )
        maximum_changing_vertex_overdepth = float(
            np.max(
                changing_vertex_depth - float(threshold_mm),
                initial=0.0,
            )
        )
        maximum_changing_interior_overdepth = float(
            np.max(
                changing_interior_depth - float(threshold_mm),
                initial=0.0,
            )
        )
        if localize_unsafe_partner_columns:
            if maximum_changing_overdepth > error_limit_mm + 1e-12:
                violating_positions = np.flatnonzero(
                    changing_interface_depth - float(threshold_mm)
                    > float(error_limit_mm) + 1e-12
                )
                sample_role_names = (
                    "vertex_0",
                    "vertex_1",
                    "vertex_2",
                    "edge_midpoint_01",
                    "edge_midpoint_02",
                    "edge_midpoint_12",
                    "face_centroid",
                )
                violating_role_ids = changing_sample_argmax[
                    violating_positions
                ]
                maximum_sample_roles = {
                    role: int(np.count_nonzero(violating_role_ids == role_id))
                    for role_id, role in enumerate(sample_role_names)
                    if np.any(violating_role_ids == role_id)
                }
                role_violations = changing_sample_violations[
                    violating_positions
                ]
                violating_sample_roles = {
                    role: int(np.count_nonzero(role_violations[:, role_id]))
                    for role_id, role in enumerate(sample_role_names)
                    if np.any(role_violations[:, role_id])
                }
                maximum_overdepth_by_sample_role_mm = {
                    role: float(
                        max(
                            0.0,
                            changing_sample_maximum_by_role[role_id]
                            - float(threshold_mm),
                        )
                    )
                    for role_id, role in enumerate(sample_role_names)
                }
                if np.any(role_violations[:, :3]):
                    _raise(
                        "localized_threshold_interface_too_deep",
                        threshold_mm=float(threshold_mm),
                        maximum_overdepth_mm=maximum_changing_overdepth,
                        maximum_vertex_overdepth_mm=(
                            maximum_changing_vertex_overdepth
                        ),
                        maximum_interior_sample_overdepth_mm=(
                            maximum_changing_interior_overdepth
                        ),
                        violating_triangles=int(len(violating_positions)),
                        violating_sample_roles=violating_sample_roles,
                        maximum_sample_roles=maximum_sample_roles,
                        maximum_overdepth_by_sample_role_mm=(
                            maximum_overdepth_by_sample_role_mm
                        ),
                        reason="adaptive_edge_root_vertex_contract_failed",
                        limit_mm=float(error_limit_mm),
                    )
                violating_triangle_ids = changing_ids[violating_positions]
                violating_parent_cells = np.unique(
                    interface_parent[violating_triangle_ids]
                ).astype(np.int32, copy=False)
                if not len(violating_parent_cells):
                    _raise(
                        "localized_threshold_interface_too_deep",
                        threshold_mm=float(threshold_mm),
                        maximum_overdepth_mm=maximum_changing_overdepth,
                        maximum_vertex_overdepth_mm=(
                            maximum_changing_vertex_overdepth
                        ),
                        maximum_interior_sample_overdepth_mm=(
                            maximum_changing_interior_overdepth
                        ),
                        violating_triangles=int(len(violating_triangle_ids)),
                        limit_mm=float(error_limit_mm),
                    )
                negative_vertex_counts = np.count_nonzero(
                    scalar[tets[violating_parent_cells]] < 0.0,
                    axis=1,
                )
                (
                    refinement_edges,
                    refinement_edge_record,
                ) = _adaptive_interface_refinement_edges(
                    nodes=nodes,
                    tets=tets,
                    scalar=scalar,
                    interface_triangles=interface_triangles,
                    interface_parent=interface_parent,
                    base_node_count=base_node_count,
                    unique_edges=unique_edges,
                    violating_triangle_ids=violating_triangle_ids,
                    violating_sample_mask=role_violations,
                )
                raise _AdaptiveInterfaceRefinementRequired(
                    threshold_mm=float(threshold_mm),
                    maximum_overdepth_mm=maximum_changing_overdepth,
                    maximum_vertex_overdepth_mm=(
                        maximum_changing_vertex_overdepth
                    ),
                    maximum_interior_overdepth_mm=(
                        maximum_changing_interior_overdepth
                    ),
                    parent_cells=violating_parent_cells,
                    violating_triangles=int(len(violating_triangle_ids)),
                    three_edge_parent_cells=int(
                        np.count_nonzero(
                            (negative_vertex_counts == 1)
                            | (negative_vertex_counts == 3)
                        )
                    ),
                    four_edge_parent_cells=int(
                        np.count_nonzero(negative_vertex_counts == 2)
                    ),
                    violating_sample_roles=violating_sample_roles,
                    maximum_sample_roles=maximum_sample_roles,
                    maximum_overdepth_by_sample_role_mm=(
                        maximum_overdepth_by_sample_role_mm
                    ),
                    refinement_edges=refinement_edges,
                    refinement_edge_record=refinement_edge_record,
                )
        elif float(np.max(changing_error, initial=0.0)) > error_limit_mm + 1e-12:
            _raise("material_changing_threshold_error_exceeded")
        unsafe_cells = np.concatenate(
            (first_cells[triangle_unsafe], second_cells[triangle_unsafe])
        )
        if not localize_unsafe_partner_columns:
            if np.any(~output_unsafe[unsafe_cells]):
                _raise("unsafe_threshold_child_not_flagged")
            unsafe_expected_outer = np.asarray(
                [outer_by_label[int(label)] for label in output_owner[unsafe_cells]],
                dtype=np.int8,
            )
            if not np.array_equal(
                output_material[unsafe_cells], unsafe_expected_outer
            ):
                _raise("unsafe_threshold_child_not_outer_only")
        safe_changing_error = float(np.max(changing_error, initial=0.0))
    else:
        triangle_error = np.empty(0, dtype=np.float64)
        triangle_unsafe = np.empty(0, dtype=bool)
        material_changes = np.empty(0, dtype=bool)
        first_cells = np.empty(0, dtype=np.int32)
        second_cells = np.empty(0, dtype=np.int32)
        safe_changing_error = 0.0
        maximum_changing_overdepth = 0.0
        maximum_changing_vertex_overdepth = 0.0
        maximum_changing_interior_overdepth = 0.0
        adaptive_interface_sample_count = 0

    # A localised adaptive fallback is acceptable only when every emitted
    # partner cell remains inside its label's requested shell.  Interface
    # vertices alone are insufficient because a closest-surface distance field
    # can peak inside a tetrahedron.  Evaluate the 4 vertices, 6 edge
    # midpoints, 4 face centroids, and cell centroid (15 samples per cell) with
    # the authoritative source-surface query.
    maximum_partner_sample_depth = 0.0
    adaptive_partner_sample_count = 0
    partner_role_names = (
        "vertex_0",
        "vertex_1",
        "vertex_2",
        "vertex_3",
        "edge_midpoint_01",
        "edge_midpoint_02",
        "edge_midpoint_03",
        "edge_midpoint_12",
        "edge_midpoint_13",
        "edge_midpoint_23",
        "face_centroid_123",
        "face_centroid_032",
        "face_centroid_013",
        "face_centroid_021",
        "cell_centroid",
    )
    partner_maximum_overdepth_by_role = np.full(
        15, -np.inf, dtype=np.float64
    )
    partner_violation_count_by_role = np.zeros(15, dtype=np.int64)
    partner_argmax_count_by_role = np.zeros(15, dtype=np.int64)
    violating_partner_output_batches: list[np.ndarray] = []
    violating_partner_role_batches: list[np.ndarray] = []
    maximum_partner_overdepth = 0.0
    maximum_partner_vertex_overdepth = 0.0
    maximum_partner_interior_overdepth = 0.0
    worst_partner_target_label = -1
    worst_partner_sample_depth = 0.0
    if localize_unsafe_partner_columns:
        changing_array = np.asarray(tuple(changing_labels), dtype=np.int32)
        changing_owner_cells = np.isin(output_owner, changing_array)
        expected_outer_for_cell = np.asarray(
            [outer_by_label[int(label)] for label in output_owner], dtype=np.int8
        )
        expected_backing_for_cell = np.asarray(
            [backing_by_label[int(label)] for label in output_owner], dtype=np.int8
        )
        partner_cells = (
            changing_owner_cells
            & (expected_outer_for_cell != expected_backing_for_cell)
            & (output_material == expected_outer_for_cell)
        )
        partner_ids = np.flatnonzero(partner_cells)
    else:
        partner_ids = np.empty(0, dtype=np.int64)
    if len(partner_ids):
        partner_batch = max(1, int(chunk_size) // 15)
        for start in range(0, len(partner_ids), partner_batch):
            batch_ids = partner_ids[start : start + partner_batch]
            points = all_coordinates[output_tets[batch_ids]]
            samples = np.concatenate(
                (
                    points,
                    0.5
                    * (
                        points[:, _TET_EDGES[:, 0]]
                        + points[:, _TET_EDGES[:, 1]]
                    ),
                    points[:, _TET_FACES].mean(axis=2),
                    points.mean(axis=1, keepdims=True),
                ),
                axis=1,
            )
            true_depth, _true_face = _closest_source(
                source_mesh,
                samples.reshape((-1, 3)),
                chunk_size=chunk_size,
            )
            partner_sample_depth = true_depth.reshape((len(batch_ids), 15))
            partner_sample_max = partner_sample_depth.max(axis=1)
            requested = np.asarray(
                [
                    float(recipes[int(output_owner[cell])].outer_thickness_mm)
                    for cell in batch_ids
                ],
                dtype=np.float64,
            )
            sample_overdepth = partner_sample_depth - requested[:, None]
            overdeep = sample_overdepth.max(axis=1)
            maximum_partner_sample_depth = max(
                maximum_partner_sample_depth,
                float(np.max(partner_sample_max, initial=0.0)),
            )
            adaptive_partner_sample_count += int(15 * len(batch_ids))
            partner_maximum_overdepth_by_role = np.maximum(
                partner_maximum_overdepth_by_role,
                np.max(sample_overdepth, axis=0),
            )
            maximum_partner_overdepth = max(
                maximum_partner_overdepth,
                float(np.max(overdeep, initial=0.0)),
            )
            maximum_partner_vertex_overdepth = max(
                maximum_partner_vertex_overdepth,
                float(np.max(sample_overdepth[:, :4], initial=0.0)),
            )
            maximum_partner_interior_overdepth = max(
                maximum_partner_interior_overdepth,
                float(np.max(sample_overdepth[:, 4:], initial=0.0)),
            )
            violation_mask = (
                sample_overdepth > float(error_limit_mm) + 1e-12
            )
            violating_rows = np.flatnonzero(np.any(violation_mask, axis=1))
            if len(violating_rows):
                partner_violation_count_by_role += np.count_nonzero(
                    violation_mask[violating_rows], axis=0
                )
                argmax_roles = np.argmax(
                    sample_overdepth[violating_rows], axis=1
                ).astype(np.int64, copy=False)
                partner_argmax_count_by_role += np.bincount(
                    argmax_roles, minlength=15
                )
                violating_partner_output_batches.append(
                    np.asarray(batch_ids[violating_rows], dtype=np.int64)
                )
                violating_partner_role_batches.append(argmax_roles)
                local_worst = int(violating_rows[np.argmax(overdeep[violating_rows])])
                if float(overdeep[local_worst]) >= maximum_partner_overdepth - 1e-15:
                    worst_cell = int(batch_ids[local_worst])
                    worst_partner_target_label = int(output_owner[worst_cell])
                    worst_partner_sample_depth = float(
                        partner_sample_max[local_worst]
                    )

    if violating_partner_output_batches:
        violating_partner_output_ids = np.concatenate(
            violating_partner_output_batches
        )
        violating_partner_role_ids = np.concatenate(
            violating_partner_role_batches
        )
        violating_sample_roles = {
            role: int(partner_violation_count_by_role[role_id])
            for role_id, role in enumerate(partner_role_names)
            if partner_violation_count_by_role[role_id]
        }
        maximum_sample_roles = {
            role: int(partner_argmax_count_by_role[role_id])
            for role_id, role in enumerate(partner_role_names)
            if partner_argmax_count_by_role[role_id]
        }
        maximum_overdepth_by_sample_role_mm = {
            role: float(
                max(0.0, partner_maximum_overdepth_by_role[role_id])
            )
            for role_id, role in enumerate(partner_role_names)
        }
        if np.any(partner_violation_count_by_role[:4]):
            _raise(
                "adaptive_partner_cell_too_deep",
                target_label=int(worst_partner_target_label),
                threshold_mm=float(threshold_mm),
                sampled_depth_mm=float(worst_partner_sample_depth),
                overdepth_mm=float(maximum_partner_overdepth),
                maximum_vertex_overdepth_mm=float(
                    maximum_partner_vertex_overdepth
                ),
                maximum_interior_sample_overdepth_mm=float(
                    maximum_partner_interior_overdepth
                ),
                limit_mm=float(error_limit_mm),
                proof_samples_per_cell=15,
                violating_output_children=int(
                    len(violating_partner_output_ids)
                ),
                violating_sample_roles=violating_sample_roles,
                maximum_sample_roles=maximum_sample_roles,
                maximum_overdepth_by_sample_role_mm=(
                    maximum_overdepth_by_sample_role_mm
                ),
                reason="adaptive_partner_vertex_contract_failed",
            )
        (
            refinement_edges,
            violating_parent_cells,
            refinement_edge_record,
        ) = _adaptive_partner_refinement_edges(
            nodes=nodes,
            tets=tets,
            scalar=scalar,
            output_tets=output_tets,
            output_parents=output_parents,
            base_node_count=base_node_count,
            output_node_count=len(all_coordinates),
            unique_edges=unique_edges,
            violating_output_cell_ids=violating_partner_output_ids,
            violating_sample_role_ids=violating_partner_role_ids,
        )
        negative_vertex_counts = np.count_nonzero(
            scalar[tets[violating_parent_cells]] < 0.0,
            axis=1,
        )
        raise _AdaptiveInterfaceRefinementRequired(
            threshold_mm=float(threshold_mm),
            maximum_overdepth_mm=float(maximum_partner_overdepth),
            maximum_vertex_overdepth_mm=float(
                maximum_partner_vertex_overdepth
            ),
            maximum_interior_overdepth_mm=float(
                maximum_partner_interior_overdepth
            ),
            parent_cells=violating_parent_cells,
            violating_triangles=0,
            three_edge_parent_cells=int(
                np.count_nonzero(
                    (negative_vertex_counts == 1)
                    | (negative_vertex_counts == 3)
                )
            ),
            four_edge_parent_cells=int(
                np.count_nonzero(negative_vertex_counts == 2)
            ),
            violating_sample_roles=violating_sample_roles,
            maximum_sample_roles=maximum_sample_roles,
            maximum_overdepth_by_sample_role_mm=(
                maximum_overdepth_by_sample_role_mm
            ),
            refinement_edges=refinement_edges,
            refinement_edge_record=refinement_edge_record,
            cause="partner",
            violating_partner_cells=int(len(violating_partner_output_ids)),
            cause_details={
                "target_label": int(worst_partner_target_label),
                "sampled_depth_mm": float(worst_partner_sample_depth),
            },
        )

    unsafe_ids = np.flatnonzero(output_unsafe)
    if len(unsafe_ids):
        expected = np.asarray(
            [outer_by_label[int(label)] for label in output_owner[unsafe_ids]],
            dtype=np.int8,
        )
        if not np.array_equal(output_material[unsafe_ids], expected):
            _raise("unsafe_column_contains_backing_material")
    anchored_unsafe = np.unique(
        exterior_parent_faces[unsafe_source[exterior_parent_faces]]
    )
    if not np.array_equal(anchored_unsafe, np.flatnonzero(unsafe_source)):
        missing = np.setdiff1d(np.flatnonzero(unsafe_source), anchored_unsafe)
        _raise(
            "unsafe_source_faces_not_anchored",
            examples=[int(value) for value in missing[:20]],
        )
    safe_interface_error = interface_error[
        interface_relevant & ~interface_unsafe
    ]
    maximum_safe_error = float(np.max(safe_interface_error, initial=0.0))
    if maximum_safe_error > error_limit_mm + 1e-12:
        _raise(
            "safe_interface_error_exceeded",
            maximum_error_mm=maximum_safe_error,
        )
    _progress(
        progress,
        "color_depth_exact_proof",
        0.72,
        "ColorDepth threshold and fallback proof complete",
    )
    partition = ConformingColorDepthPartition(
        nodes_mm=np.ascontiguousarray(all_coordinates, dtype=np.float64),
        tetrahedra=np.ascontiguousarray(output_tets, dtype=np.int32),
        cell_owner_labels=np.ascontiguousarray(output_owner, dtype=np.int32),
        cell_depth_bounds_mm=np.ascontiguousarray(output_bounds, dtype=np.float64),
        cell_materials=np.ascontiguousarray(output_material, dtype=np.int8),
        unsafe_outer_only_cells=np.ascontiguousarray(output_unsafe, dtype=bool),
        exterior_faces=np.ascontiguousarray(exterior_faces, dtype=np.int32),
        exterior_owner_cells=np.ascontiguousarray(exterior_cells, dtype=np.int32),
        exterior_source_face_ids=np.ascontiguousarray(
            exterior_parent_faces, dtype=np.int32
        ),
        threshold_interface_conforming=True,
        shared_interface_partition_exact=True,
        max_safe_threshold_error_mm=maximum_safe_error,
        max_safe_threshold_error_limit_mm=float(error_limit_mm),
        metadata={
            "schema": COLOR_DEPTH_EXACT_PARTITION_SCHEMA,
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "physical_materials_only": True,
            "legacy_mix_percentages_used": False,
            "centroid_approximation": False,
            "threshold_mm": float(threshold_mm),
            "input_cells": int(len(tets)),
            "crossing_input_cells": int(len(crossing_ids)),
            "output_cells": int(len(output_tets)),
            "output_nodes": int(len(all_coordinates)),
            "source_volume_mm3": source_volume,
            "output_volume_mm3": output_volume,
            "volume_error_mm3": volume_error,
            "visible_exterior_triangle_sets_exact": True,
            "visible_owner_labels_exact": True,
            "visible_outer_physical_exact": True,
            "cell_complex_faces_incidence_gt2": 0,
            "unsafe_source_faces_raw": int(np.count_nonzero(raw_unsafe_source)),
            "unsafe_source_faces_one_ring": int(np.count_nonzero(unsafe_source)),
            "unsafe_outer_only_cells": int(np.count_nonzero(output_unsafe)),
            "localized_adaptive_fallback_cells": int(
                np.count_nonzero(output_localized)
            ),
            "boundary_unsafe_or_aggregation_verified": True,
            "unsafe_columns_outer_only_verified": True,
            "interface_vertices": int(len(interface_points)),
            "adaptive_edge_root": dict(edge_root_record),
            "threshold_tetrahedralization": (
                "boundary_vertex_fan"
                if use_boundary_vertex_fan
                else "side_centroid_fan"
            ),
            "side_fan_centroid_nodes": int(side_centroid_count),
            "added_node_depths_exact_affine": False,
            "added_node_depths_recomputed_from_source_surface": True,
            "maximum_side_fan_centroid_depth_interpolation_error_mm": float(
                side_centroid_depth_error
            ),
            "interface_triangles": int(len(interface_triangles)),
            "unsafe_interface_vertices": int(np.count_nonzero(interface_unsafe)),
            "material_changing_threshold_triangles": int(
                np.count_nonzero(material_changes)
            ),
            "unsafe_material_changing_threshold_triangles": 0,
            "maximum_safe_interface_error_mm": maximum_safe_error,
            "maximum_material_changing_interface_error_mm": safe_changing_error,
            "maximum_material_changing_interface_overdepth_mm": float(
                maximum_changing_overdepth
            ),
            "maximum_material_changing_interface_vertex_overdepth_mm": float(
                maximum_changing_vertex_overdepth
            ),
            "maximum_material_changing_interface_interior_overdepth_mm": float(
                maximum_changing_interior_overdepth
            ),
            "maximum_partner_cell_sample_depth_mm": float(
                maximum_partner_sample_depth
            ),
            "adaptive_interface_proof_samples_per_triangle": (
                7 if localize_unsafe_partner_columns else 0
            ),
            "adaptive_interface_true_distance_sample_count": int(
                adaptive_interface_sample_count
            ),
            "adaptive_partner_proof_samples_per_cell": (
                15 if localize_unsafe_partner_columns else 0
            ),
            "adaptive_partner_true_distance_sample_count": int(
                adaptive_partner_sample_count
            ),
            "adaptive_partner_depth_samples_verified": bool(
                localize_unsafe_partner_columns
            ),
            "interface_error_limit_mm": float(error_limit_mm),
            "direct_threshold_child_join_verified": True,
            "threshold_interface_conforming": True,
            "shared_interface_partition_exact": True,
            "parent_cells_preserved": int(len(output_parents)),
            "interface_parent_records": int(len(interface_parent)),
            "side_counts": {
                str(int(side)): int(count)
                for side, count in zip(
                    *np.unique(output_side, return_counts=True), strict=True
                )
            },
            "material_cell_counts": {
                str(int(material)): int(count)
                for material, count in zip(
                    *np.unique(output_material, return_counts=True), strict=True
                )
            },
        },
    )
    if (
        all_node_depth.shape != (len(all_coordinates),)
        or not np.isfinite(all_node_depth).all()
        or np.any(all_node_depth < 0.0)
    ):
        _raise("invalid_output_node_depth_field")
    return partition, np.ascontiguousarray(all_node_depth, dtype=np.float64)


def build_conforming_color_depth_partition(
    source: ColorDepthSourceSurface,
    recipes: Mapping[int, ColorDepthRecipe],
    *,
    progress: Callable[..., object] | None = None,
    interface_error_limit_mm: float = _DEFAULT_INTERFACE_ERROR_LIMIT_MM,
    proximity_chunk_size: int = 20_000,
) -> ConformingColorDepthPartition:
    """Build a conforming physical-material partition from one source mesh."""

    started = time.perf_counter()
    if not isinstance(source, ColorDepthSourceSurface):
        _raise("invalid_source_surface", type=type(source).__name__)
    error_limit = float(interface_error_limit_mm)
    if (
        not math.isfinite(error_limit)
        or error_limit <= 0.0
        or error_limit > _DEFAULT_INTERFACE_ERROR_LIMIT_MM + 1e-12
    ):
        _raise(
            "invalid_interface_error_limit",
            interface_error_limit_mm=interface_error_limit_mm,
        )
    chunk_size = int(proximity_chunk_size)
    if chunk_size < 1:
        _raise("invalid_proximity_chunk_size", value=proximity_chunk_size)
    source_mesh = _validate_source_for_tetgen(source)
    thresholds_by_label, outer, backing = _validate_recipes(source, recipes)
    used_labels = tuple(int(value) for value in np.unique(source.face_target_labels))
    unique_thresholds = tuple(
        sorted({float(thresholds_by_label[label]) for label in used_labels})
    )
    adaptive_stage_b = bool(
        len(unique_thresholds) > 1
        and any(
            bool(recipe.metadata.get("radial_stage_b"))
            and bool(recipe.metadata.get("adaptive_outer_skin"))
            for recipe in recipes.values()
        )
    )
    if len(unique_thresholds) > _MAX_VARIABLE_OUTER_THICKNESS_BANDS:
        _raise(
            "too_many_outer_thickness_bands",
            maximum=int(_MAX_VARIABLE_OUTER_THICKNESS_BANDS),
            actual=int(len(unique_thresholds)),
            outer_thicknesses_mm=[float(value) for value in unique_thresholds],
        )
    near_duplicate = [
        (float(first), float(second))
        for first, second in zip(unique_thresholds, unique_thresholds[1:])
        if 0.0 < second - first <= _BOUNDARY_TRANSFER_TOLERANCE_MM
    ]
    if near_duplicate:
        _raise(
            "outer_thickness_bands_too_close",
            minimum_separation_mm=float(_BOUNDARY_TRANSFER_TOLERANCE_MM),
            pairs_mm=near_duplicate,
        )
    threshold = float(unique_thresholds[0])
    _progress(
        progress,
        "color_depth_exact_tetgen",
        0.15,
        "ColorDepth exact TetGen boundary",
    )
    nodes, tets, boundary_faces, boundary_cells, tetgen_record = (
        _tetrahedralize_exact_boundary(source)
    )
    boundary_labels, boundary_parents, boundary_record = (
        _complete_boundary_labels(
            source,
            source_mesh,
            nodes,
            boundary_faces,
            chunk_size=chunk_size,
        )
    )
    _progress(
        progress,
        "color_depth_exact_owner",
        0.28,
        "ColorDepth boundary ownership",
    )
    (
        refined_nodes,
        refined_tets,
        _parent_tets,
        forced_labels,
        refined_boundary_cells,
        cone_record,
    ) = _split_conflicting_boundary_cells(
        nodes,
        tets,
        boundary_faces,
        boundary_cells,
        boundary_labels,
    )
    (
        refined_nodes,
        refined_tets,
        boundary_faces,
        refined_boundary_cells,
        boundary_labels,
        boundary_parents,
        refined_node_depth,
        visibility_record,
    ) = _insert_hidden_threshold_centroids(
        source_mesh=source_mesh,
        nodes=refined_nodes,
        tets=refined_tets,
        boundary_faces=boundary_faces,
        boundary_cells=refined_boundary_cells,
        boundary_labels=boundary_labels,
        boundary_parent_faces=boundary_parents,
        threshold_mm=threshold,
        chunk_size=chunk_size,
    )
    centers = refined_nodes[refined_tets].mean(axis=1)
    _center_depth, closest_faces = _closest_source(
        source_mesh, centers, chunk_size=chunk_size
    )
    owner_labels = np.asarray(
        source.face_target_labels[closest_faces], dtype=np.int32
    )
    # Rebuild forced visible ownership after the optional centroid repair.
    # Only boundary-incident children are forced; interior siblings retain
    # closest-surface ownership.
    forced_labels = np.full(len(refined_tets), -1, dtype=np.int32)
    for cell, label in zip(
        refined_boundary_cells, boundary_labels, strict=True
    ):
        existing = int(forced_labels[int(cell)])
        if existing >= 0 and existing != int(label):
            _raise(
                "conflicting_boundary_owner_after_visibility_refinement",
                cell=int(cell),
                first=existing,
                second=int(label),
            )
        forced_labels[int(cell)] = int(label)
    forced = forced_labels >= 0
    owner_labels[forced] = forced_labels[forced]
    owner_source_faces = closest_faces.copy()
    # Exact boundary provenance overrides proximity ties.  Aggregate a
    # deterministic representative; unsafe status is OR-aggregated later.
    boundary_min = np.full(
        len(refined_tets), np.iinfo(np.int32).max, dtype=np.int32
    )
    np.minimum.at(boundary_min, refined_boundary_cells, boundary_parents)
    touched = boundary_min != np.iinfo(np.int32).max
    owner_source_faces[touched] = boundary_min[touched]
    if not np.array_equal(
        owner_labels[refined_boundary_cells], boundary_labels
    ):
        _raise("visible_boundary_owner_changed_before_threshold")
    _progress(
        progress,
        "color_depth_exact_split",
        0.40,
        (
            "ColorDepth common-depth conforming split"
            if len(unique_thresholds) == 1
            else f"ColorDepth conforming depth bands 1/{len(unique_thresholds)}"
        ),
    )
    current_nodes = refined_nodes
    current_tets = refined_tets
    current_owner = owner_labels
    current_source_faces = owner_source_faces
    current_boundary_faces = boundary_faces
    current_boundary_cells = refined_boundary_cells
    current_boundary_labels = boundary_labels
    current_boundary_parents = boundary_parents
    current_node_depth: np.ndarray | None = refined_node_depth
    current_bounds: np.ndarray | None = None
    current_materials: np.ndarray | None = None
    current_unsafe: np.ndarray | None = None
    threshold_pass_records: list[Mapping[str, object]] = []
    variable_visibility_records: list[Mapping[str, object]] = []
    maximum_safe_error = 0.0
    result: ConformingColorDepthPartition | None = None
    for pass_index, pass_threshold in enumerate(unique_thresholds):
        changing = frozenset(
            label
            for label in used_labels
            if abs(float(thresholds_by_label[label]) - pass_threshold) <= 1e-12
        )
        if len(unique_thresholds) > 1:
            refinement_records: list[Mapping[str, object]] = []
            for refinement_round in range(_VARIABLE_AFFINE_REFINEMENT_PASSES):
                candidate_mask = np.isin(
                    current_owner,
                    np.asarray(tuple(changing), dtype=np.int32),
                )
                if current_unsafe is not None:
                    candidate_mask &= ~current_unsafe
                (
                    current_nodes,
                    current_tets,
                    current_boundary_faces,
                    current_boundary_cells,
                    current_boundary_labels,
                    current_boundary_parents,
                    current_node_depth,
                    later_visibility,
                    refinement_parents,
                ) = _insert_hidden_threshold_centroids(
                    source_mesh=source_mesh,
                    nodes=current_nodes,
                    tets=current_tets,
                    boundary_faces=current_boundary_faces,
                    boundary_cells=current_boundary_cells,
                    boundary_labels=current_boundary_labels,
                    boundary_parent_faces=current_boundary_parents,
                    threshold_mm=pass_threshold,
                    chunk_size=chunk_size,
                    scan_local_hidden=True,
                    return_parent_cells=True,
                    candidate_cell_mask=candidate_mask,
                    node_depth_mm=current_node_depth,
                    affine_error_limit_mm=0.5 * error_limit,
                )
                refinement_parents = np.asarray(
                    refinement_parents, dtype=np.int32
                )
                current_owner = current_owner[refinement_parents]
                if current_bounds is not None:
                    current_bounds = current_bounds[refinement_parents]
                if current_materials is not None:
                    current_materials = current_materials[refinement_parents]
                if current_unsafe is not None:
                    current_unsafe = current_unsafe[refinement_parents]
                refinement_record = {
                    "round": int(refinement_round + 1),
                    **dict(later_visibility),
                }
                refinement_records.append(refinement_record)
                if len(current_tets) > _MAX_VARIABLE_PARTITION_CELLS:
                    _raise(
                        "variable_partition_cell_limit_exceeded",
                        threshold_mm=float(pass_threshold),
                        cells=int(len(current_tets)),
                        maximum=int(_MAX_VARIABLE_PARTITION_CELLS),
                    )
                centers = current_nodes[current_tets].mean(axis=1)
                _center_depth, current_source_faces = _closest_source(
                    source_mesh, centers, chunk_size=chunk_size
                )
                current_source_faces = np.asarray(
                    current_source_faces, dtype=np.int32
                )
                current_source_faces[current_boundary_cells] = (
                    current_boundary_parents
                )
                if int(later_visibility["added_centroid_nodes"]) == 0:
                    break
            variable_visibility_records.append(
                {
                    "threshold_mm": float(pass_threshold),
                    "round_count": int(len(refinement_records)),
                    "rounds": refinement_records,
                    "added_centroid_nodes": int(
                        sum(
                            int(record["added_centroid_nodes"])
                            for record in refinement_records
                        )
                    ),
                }
            )
            _progress(
                progress,
                "color_depth_exact_split",
                0.40 + 0.30 * pass_index / max(len(unique_thresholds), 1),
                (
                    f"ColorDepth conforming depth bands "
                    f"{pass_index + 1}/{len(unique_thresholds)}"
                ),
            )
        assert current_node_depth is not None
        adaptive_interface_refinement_records: list[Mapping[str, object]] = []
        ordinary_interface_refinement_rounds = 0
        stagnation_fallback_refinement_rounds = 0
        partner_refinement_rounds = 0
        current_adaptive_origin_cells = np.arange(
            len(current_tets), dtype=np.int32
        )
        for adaptive_refinement_round in range(
            _ADAPTIVE_TOTAL_REFINEMENT_PASSES + 1
        ):
            try:
                result, output_node_depth = _build_threshold_partition(
                    source=source,
                    source_mesh=source_mesh,
                    recipes=recipes,
                    threshold_mm=pass_threshold,
                    outer_by_label=outer,
                    backing_by_label=backing,
                    nodes=current_nodes,
                    tets=current_tets,
                    owner_labels=current_owner,
                    owner_source_faces=current_source_faces,
                    boundary_faces=current_boundary_faces,
                    boundary_cells=current_boundary_cells,
                    boundary_labels=current_boundary_labels,
                    boundary_parent_faces=current_boundary_parents,
                    node_depth=current_node_depth,
                    parent_depth_bounds_mm=current_bounds,
                    parent_materials=current_materials,
                    initial_parent_unsafe=current_unsafe,
                    material_changing_labels=changing,
                    use_boundary_vertex_fan=len(unique_thresholds) > 1,
                    localize_unsafe_partner_columns=adaptive_stage_b,
                    error_limit_mm=error_limit,
                    chunk_size=chunk_size,
                    progress=progress,
                )
            except _AdaptiveInterfaceRefinementRequired as requested:
                if requested.cause not in {"interface", "partner"}:
                    _raise(
                        "invalid_adaptive_refinement_cause",
                        cause=requested.cause,
                    )
                requested_parent_cells = np.asarray(
                    requested.parent_cells, dtype=np.int64
                )
                if (
                    requested_parent_cells.ndim != 1
                    or not len(requested_parent_cells)
                    or np.any(requested_parent_cells < 0)
                    or np.any(requested_parent_cells >= len(current_tets))
                ):
                    _raise(
                        "invalid_adaptive_interface_refinement_parent_cells",
                        input_cells=int(len(current_tets)),
                        requested_cells=int(len(requested_parent_cells)),
                        shape=tuple(requested_parent_cells.shape),
                    )
                cause_rounds = (
                    ordinary_interface_refinement_rounds
                    if requested.cause == "interface"
                    else partner_refinement_rounds
                )
                parent_count = int(len(np.unique(requested.parent_cells)))
                raw_refinement_edges = np.asarray(requested.refinement_edges)
                if (
                    raw_refinement_edges.ndim == 2
                    and raw_refinement_edges.shape[1:] == (2,)
                    and len(raw_refinement_edges)
                ):
                    unique_seed_edges = int(
                        len(
                            np.unique(
                                np.sort(raw_refinement_edges, axis=1),
                                axis=0,
                            )
                        )
                    )
                else:
                    unique_seed_edges = -1
                stagnation_policy = _adaptive_interface_stagnation_policy(
                    cause=requested.cause,
                    maximum_overdepth_mm=requested.maximum_overdepth_mm,
                    violating_triangles=requested.violating_triangles,
                    violating_parent_cells=parent_count,
                    three_edge_parent_cells=(
                        requested.three_edge_parent_cells
                    ),
                    four_edge_parent_cells=(
                        requested.four_edge_parent_cells
                    ),
                    violating_sample_roles=(
                        requested.violating_sample_roles
                    ),
                    unique_seed_edges=unique_seed_edges,
                    violating_origin_cells=current_adaptive_origin_cells[
                        requested_parent_cells
                    ],
                    completed_records=adaptive_interface_refinement_records,
                )
                budget_route = _adaptive_refinement_budget_route(
                    adaptive_stage_b=adaptive_stage_b,
                    cause=requested.cause,
                    ordinary_interface_rounds=(
                        ordinary_interface_refinement_rounds
                    ),
                    partner_rounds=partner_refinement_rounds,
                    stagnation_fallback_rounds=(
                        stagnation_fallback_refinement_rounds
                    ),
                    total_rounds=len(adaptive_interface_refinement_records),
                    stagnation_policy=stagnation_policy,
                )
                if stagnation_policy["hard_stop"]:
                    _raise(
                        "adaptive_interface_stagnation_not_contracted",
                        threshold_mm=float(requested.threshold_mm),
                        maximum_overdepth_mm=float(
                            requested.maximum_overdepth_mm
                        ),
                        maximum_vertex_overdepth_mm=float(
                            requested.maximum_vertex_overdepth_mm
                        ),
                        maximum_interior_sample_overdepth_mm=float(
                            requested.maximum_interior_overdepth_mm
                        ),
                        limit_mm=float(error_limit),
                        violating_triangles=int(
                            requested.violating_triangles
                        ),
                        violating_parent_cells=parent_count,
                        violating_parent_cell_examples=[
                            int(value)
                            for value in requested.parent_cells[:20]
                        ],
                        three_edge_parent_cells=int(
                            requested.three_edge_parent_cells
                        ),
                        four_edge_parent_cells=int(
                            requested.four_edge_parent_cells
                        ),
                        violating_sample_roles=dict(
                            requested.violating_sample_roles
                        ),
                        refinement_edge_selection=dict(
                            requested.refinement_edge_record
                        ),
                        stagnation_policy=dict(stagnation_policy),
                        refinement_budget_route=dict(budget_route),
                        total_local_refinement_rounds=int(
                            len(adaptive_interface_refinement_records)
                        ),
                        total_rounds=int(
                            len(adaptive_interface_refinement_records)
                        ),
                        ordinary_interface_refinement_rounds=int(
                            ordinary_interface_refinement_rounds
                        ),
                        stagnation_fallback_refinement_rounds=int(
                            stagnation_fallback_refinement_rounds
                        ),
                        fallback_rounds=int(
                            stagnation_fallback_refinement_rounds
                        ),
                        partner_refinement_rounds=int(
                            partner_refinement_rounds
                        ),
                        completed_local_refinement_rounds=[
                            dict(record)
                            for record in adaptive_interface_refinement_records
                        ],
                    )
                if not budget_route["allowed"]:
                    common_failure = {
                        "threshold_mm": float(requested.threshold_mm),
                        "maximum_overdepth_mm": float(
                            requested.maximum_overdepth_mm
                        ),
                        "maximum_vertex_overdepth_mm": float(
                            requested.maximum_vertex_overdepth_mm
                        ),
                        "maximum_interior_sample_overdepth_mm": float(
                            requested.maximum_interior_overdepth_mm
                        ),
                        "limit_mm": float(error_limit),
                        "violating_triangles": int(
                            requested.violating_triangles
                        ),
                        "violating_parent_cells": int(
                            len(requested.parent_cells)
                        ),
                        "violating_parent_cell_examples": [
                            int(value) for value in requested.parent_cells[:20]
                        ],
                        "three_edge_parent_cells": int(
                            requested.three_edge_parent_cells
                        ),
                        "four_edge_parent_cells": int(
                            requested.four_edge_parent_cells
                        ),
                        "violating_sample_roles": dict(
                            requested.violating_sample_roles
                        ),
                        "maximum_sample_roles": dict(
                            requested.maximum_sample_roles
                        ),
                        "maximum_overdepth_by_sample_role_mm": dict(
                            requested.maximum_overdepth_by_sample_role_mm
                        ),
                        "refinement_edge_selection": dict(
                            requested.refinement_edge_record
                        ),
                        "refinement_cause": str(requested.cause),
                        "local_refinement_rounds": int(
                            len(adaptive_interface_refinement_records)
                        ),
                        "total_rounds": int(
                            len(adaptive_interface_refinement_records)
                        ),
                        "interface_refinement_rounds": int(
                            ordinary_interface_refinement_rounds
                        ),
                        "ordinary_interface_refinement_rounds": int(
                            ordinary_interface_refinement_rounds
                        ),
                        "stagnation_fallback_refinement_rounds": int(
                            stagnation_fallback_refinement_rounds
                        ),
                        "fallback_rounds": int(
                            stagnation_fallback_refinement_rounds
                        ),
                        "partner_refinement_rounds": int(
                            partner_refinement_rounds
                        ),
                        "maximum_total_local_refinement_rounds": int(
                            _ADAPTIVE_TOTAL_REFINEMENT_PASSES
                        ),
                        "maximum_interface_refinement_rounds": int(
                            _ADAPTIVE_INTERFACE_REFINEMENT_PASSES
                        ),
                        "stagnation_policy": dict(stagnation_policy),
                        "refinement_budget_route": dict(budget_route),
                        "completed_local_refinement_rounds": [
                            dict(record)
                            for record in adaptive_interface_refinement_records
                        ],
                    }
                    if requested.cause == "partner":
                        _raise(
                            "adaptive_partner_cell_too_deep",
                            **common_failure,
                            violating_output_children=int(
                                requested.violating_partner_cells
                            ),
                            overdepth_mm=float(
                                requested.maximum_overdepth_mm
                            ),
                            proof_samples_per_cell=15,
                            **dict(requested.cause_details),
                        )
                    _raise(
                        "localized_threshold_interface_too_deep",
                        **common_failure,
                    )
                if (
                    requested.refinement_edges.ndim != 2
                    or requested.refinement_edges.shape[1:] != (2,)
                    or not len(requested.refinement_edges)
                ):
                    _raise(
                        "invalid_adaptive_interface_refinement_edges",
                        shape=tuple(requested.refinement_edges.shape),
                    )
                input_cell_count = int(len(current_tets))
                input_node_count = int(len(current_nodes))
                refinement_function = (
                    _refine_stagnant_four_edge_parent_diameters
                    if budget_route["use_full_diameter_fallback"]
                    else _bisect_internal_edge_stars
                )
                refinement_arguments = {
                    "source_mesh": source_mesh,
                    "nodes": current_nodes,
                    "tets": current_tets,
                    "boundary_faces": current_boundary_faces,
                    "boundary_cells": current_boundary_cells,
                    "boundary_labels": current_boundary_labels,
                    "boundary_parent_faces": current_boundary_parents,
                    "node_depth_mm": current_node_depth,
                    "threshold_mm": pass_threshold,
                    "chunk_size": chunk_size,
                }
                if budget_route["use_full_diameter_fallback"]:
                    refinement_arguments["parent_cells"] = (
                        requested.parent_cells
                    )
                else:
                    refinement_arguments["seed_edges"] = (
                        requested.refinement_edges
                    )
                try:
                    refinement_result = refinement_function(
                        **refinement_arguments
                    )
                except ColorDepthExactPartitionError as refinement_error:
                    failure_details = dict(refinement_error.details)
                    failure_details.update(
                        {
                            "adaptive_refinement_cause": str(
                                requested.cause
                            ),
                            "stagnation_policy": dict(stagnation_policy),
                            "refinement_budget_route": dict(budget_route),
                            "completed_local_refinement_rounds": [
                                dict(record)
                                for record in (
                                    adaptive_interface_refinement_records
                                )
                            ],
                        }
                    )
                    raise ColorDepthExactPartitionError(
                        refinement_error.code,
                        failure_details,
                    ) from refinement_error
                (
                    current_nodes,
                    current_tets,
                    current_boundary_faces,
                    current_boundary_cells,
                    current_boundary_labels,
                    current_boundary_parents,
                    current_node_depth,
                    local_refinement,
                    refinement_parents,
                ) = refinement_result
                refinement_parents = np.asarray(
                    refinement_parents, dtype=np.int32
                )
                current_adaptive_origin_cells = current_adaptive_origin_cells[
                    refinement_parents
                ]
                current_owner = current_owner[refinement_parents]
                if current_bounds is not None:
                    current_bounds = current_bounds[refinement_parents]
                if current_materials is not None:
                    current_materials = current_materials[refinement_parents]
                if current_unsafe is not None:
                    current_unsafe = current_unsafe[refinement_parents]
                if len(current_tets) > _MAX_VARIABLE_PARTITION_CELLS:
                    _raise(
                        "variable_partition_cell_limit_exceeded",
                        threshold_mm=float(pass_threshold),
                        phase="adaptive_interface_local_refinement",
                        cells=int(len(current_tets)),
                        maximum=int(_MAX_VARIABLE_PARTITION_CELLS),
                    )
                centers = current_nodes[current_tets].mean(axis=1)
                _center_depth, current_source_faces = _closest_source(
                    source_mesh, centers, chunk_size=chunk_size
                )
                current_source_faces = np.asarray(
                    current_source_faces, dtype=np.int32
                )
                current_source_faces[current_boundary_cells] = (
                    current_boundary_parents
                )
                adaptive_interface_refinement_records.append(
                    {
                        "round": int(adaptive_refinement_round + 1),
                        "cause": str(requested.cause),
                        "cause_round": int(
                            stagnation_fallback_refinement_rounds + 1
                            if budget_route["use_full_diameter_fallback"]
                            else cause_rounds + 1
                        ),
                        "cause_round_kind": (
                            "stagnation_fallback"
                            if budget_route["use_full_diameter_fallback"]
                            else str(requested.cause)
                        ),
                        "threshold_mm": float(pass_threshold),
                        "trigger_maximum_overdepth_mm": float(
                            requested.maximum_overdepth_mm
                        ),
                        "trigger_maximum_vertex_overdepth_mm": float(
                            requested.maximum_vertex_overdepth_mm
                        ),
                        "trigger_maximum_interior_sample_overdepth_mm": float(
                            requested.maximum_interior_overdepth_mm
                        ),
                        "trigger_violating_triangles": int(
                            requested.violating_triangles
                        ),
                        "trigger_violating_partner_cells": int(
                            requested.violating_partner_cells
                        ),
                        "refined_parent_cells": int(
                            len(requested.parent_cells)
                        ),
                        "refined_parent_cell_examples": [
                            int(value)
                            for value in requested.parent_cells[:20]
                        ],
                        "refined_parent_cell_examples_complete": bool(
                            len(requested.parent_cells) <= 20
                        ),
                        "three_edge_parent_cells": int(
                            requested.three_edge_parent_cells
                        ),
                        "four_edge_parent_cells": int(
                            requested.four_edge_parent_cells
                        ),
                        "violating_sample_roles": dict(
                            requested.violating_sample_roles
                        ),
                        "maximum_sample_roles": dict(
                            requested.maximum_sample_roles
                        ),
                        "maximum_overdepth_by_sample_role_mm": dict(
                            requested.maximum_overdepth_by_sample_role_mm
                        ),
                        "refinement_edge_selection": dict(
                            requested.refinement_edge_record
                        ),
                        "trigger_signature": dict(
                            stagnation_policy["signature"]
                        ),
                        "stagnation_policy": dict(stagnation_policy),
                        "refinement_budget_route": dict(budget_route),
                        "stagnation_full_diameter_fallback": bool(
                            budget_route["use_full_diameter_fallback"]
                        ),
                        "ordinary_interface_rounds_after": int(
                            ordinary_interface_refinement_rounds
                            + (
                                requested.cause == "interface"
                                and not budget_route[
                                    "use_full_diameter_fallback"
                                ]
                            )
                        ),
                        "stagnation_fallback_rounds_after": int(
                            stagnation_fallback_refinement_rounds
                            + bool(
                                budget_route[
                                    "use_full_diameter_fallback"
                                ]
                            )
                        ),
                        "partner_rounds_after": int(
                            partner_refinement_rounds
                            + (requested.cause == "partner")
                        ),
                        "total_rounds_after": int(
                            len(adaptive_interface_refinement_records) + 1
                        ),
                        "input_nodes": input_node_count,
                        "input_tetrahedra": input_cell_count,
                        **dict(local_refinement),
                    }
                )
                if budget_route["use_full_diameter_fallback"]:
                    stagnation_fallback_refinement_rounds += 1
                elif requested.cause == "interface":
                    ordinary_interface_refinement_rounds += 1
                else:
                    partner_refinement_rounds += 1
                _progress(
                    progress,
                    "color_depth_exact_split",
                    0.40
                    + 0.30
                    * (pass_index + 0.5)
                    / max(len(unique_thresholds), 1),
                    (
                        "ColorDepth adaptive "
                        f"{budget_route['route']} local "
                        "refinement "
                        f"{adaptive_refinement_round + 1}/"
                        f"{_ADAPTIVE_TOTAL_REFINEMENT_PASSES}"
                    ),
                )
                continue
            break
        material_visibility: dict[str, Mapping[str, object]] = {}
        for label in sorted(changing):
            outer_material = int(outer[label])
            backing_material = int(backing[label])
            if outer_material == backing_material:
                continue
            safe_owner = (
                (result.cell_owner_labels == int(label))
                & ~result.unsafe_outer_only_cells
            )
            owner_materials = result.cell_materials[safe_owner]
            outer_cells = int(
                np.count_nonzero(owner_materials == outer_material)
            )
            backing_cells = int(
                np.count_nonzero(owner_materials == backing_material)
            )
            material_visibility[str(int(label))] = {
                "outer_physical": outer_material,
                "backing_physical": backing_material,
                "safe_outer_cells": outer_cells,
                "safe_backing_cells": backing_cells,
            }
            if len(unique_thresholds) > 1 and backing_cells < 1:
                _raise(
                    "variable_threshold_material_visibility_missing",
                    target_label=int(label),
                    threshold_mm=float(pass_threshold),
                    outer_physical=outer_material,
                    backing_physical=backing_material,
                    safe_outer_cells=outer_cells,
                    safe_backing_cells=backing_cells,
                )
        threshold_pass_records.append(
            {
                **dict(result.metadata),
                "material_visibility_by_label": material_visibility,
                "adaptive_interface_local_refinement": {
                    "round_count": int(
                        len(adaptive_interface_refinement_records)
                    ),
                    "total_rounds": int(
                        len(adaptive_interface_refinement_records)
                    ),
                    "interface_round_count": int(
                        sum(
                            record.get("cause") == "interface"
                            and not record.get(
                                "stagnation_full_diameter_fallback", False
                            )
                            for record in adaptive_interface_refinement_records
                        )
                    ),
                    "interface_operation_round_count": int(
                        sum(
                            record.get("cause") == "interface"
                            for record in adaptive_interface_refinement_records
                        )
                    ),
                    "ordinary_interface_round_count": int(
                        sum(
                            record.get("cause") == "interface"
                            and not record.get(
                                "stagnation_full_diameter_fallback", False
                            )
                            for record in adaptive_interface_refinement_records
                        )
                    ),
                    "ordinary_interface_rounds": int(
                        ordinary_interface_refinement_rounds
                    ),
                    "stagnation_fallback_round_count": int(
                        sum(
                            bool(
                                record.get(
                                    "stagnation_full_diameter_fallback", False
                                )
                            )
                            for record in adaptive_interface_refinement_records
                        )
                    ),
                    "fallback_rounds": int(
                        stagnation_fallback_refinement_rounds
                    ),
                    "partner_round_count": int(
                        sum(
                            record.get("cause") == "partner"
                            for record in adaptive_interface_refinement_records
                        )
                    ),
                    "maximum_interface_rounds": int(
                        _ADAPTIVE_INTERFACE_REFINEMENT_PASSES
                    ),
                    "maximum_stagnation_fallback_rounds": int(
                        _ADAPTIVE_STAGNATION_FALLBACK_PASSES
                    ),
                    "maximum_partner_rounds": int(
                        _ADAPTIVE_PARTNER_REFINEMENT_PASSES
                    ),
                    "maximum_total_rounds": int(
                        _ADAPTIVE_TOTAL_REFINEMENT_PASSES
                    ),
                    "rounds": adaptive_interface_refinement_records,
                    "added_midpoint_nodes": int(
                        sum(
                            int(record["added_midpoint_nodes"])
                            for record in adaptive_interface_refinement_records
                        )
                    ),
                    "boundary_faces_preserved": True,
                    "piecewise_affine_level_set_recomputed": True,
                },
            }
        )
        maximum_safe_error = max(
            maximum_safe_error,
            float(result.max_safe_threshold_error_mm),
        )
        current_nodes = result.nodes_mm
        current_tets = result.tetrahedra
        current_owner = result.cell_owner_labels
        current_boundary_faces = result.exterior_faces
        current_boundary_cells = result.exterior_owner_cells
        current_boundary_labels = current_owner[current_boundary_cells]
        current_boundary_parents = result.exterior_source_face_ids
        current_node_depth = output_node_depth
        current_bounds = result.cell_depth_bounds_mm
        current_materials = result.cell_materials
        current_unsafe = result.unsafe_outer_only_cells
    assert result is not None
    if len(unique_thresholds) > 1:
        result = ConformingColorDepthPartition(
            nodes_mm=result.nodes_mm,
            tetrahedra=result.tetrahedra,
            cell_owner_labels=result.cell_owner_labels,
            cell_depth_bounds_mm=result.cell_depth_bounds_mm,
            cell_materials=result.cell_materials,
            unsafe_outer_only_cells=result.unsafe_outer_only_cells,
            exterior_faces=result.exterior_faces,
            exterior_owner_cells=result.exterior_owner_cells,
            exterior_source_face_ids=result.exterior_source_face_ids,
            threshold_interface_conforming=result.threshold_interface_conforming,
            shared_interface_partition_exact=result.shared_interface_partition_exact,
            max_safe_threshold_error_mm=maximum_safe_error,
            max_safe_threshold_error_limit_mm=result.max_safe_threshold_error_limit_mm,
            metadata={
                **dict(result.metadata),
                "threshold_mm": None,
                "variable_outer_thickness": True,
                "thresholds_mm_by_label": {
                    str(label): float(thresholds_by_label[label])
                    for label in used_labels
                },
                "unique_thresholds_mm": [float(value) for value in unique_thresholds],
                "threshold_pass_count": int(len(unique_thresholds)),
                "threshold_passes": threshold_pass_records,
                "variable_threshold_visibility_passes": (
                    variable_visibility_records
                ),
                "maximum_safe_interface_error_mm": maximum_safe_error,
                "maximum_material_changing_interface_error_mm": max(
                    float(record.get("maximum_material_changing_interface_error_mm", 0.0))
                    for record in threshold_pass_records
                ),
                "multi_threshold_global_stratification": True,
                "adaptive_stage_b_partner_depth_guard": bool(adaptive_stage_b),
                "piecewise_linear_depth_field_preserved_across_bands": True,
            },
        )
    metadata = {
        **dict(result.metadata),
        "tetrahedralization": tetgen_record,
        "boundary_label_completion": boundary_record,
        "conflicting_boundary_face_cones": cone_record,
        "hidden_threshold_visibility": visibility_record,
        "owner_field": {
            "cells": int(len(refined_tets)),
            "forced_boundary_cells": int(np.count_nonzero(forced)),
            "visible_boundary_owner_exact": True,
            "closest_source_face_tie_policy": (
                "trimesh closest triangle; visible boundary overridden exactly"
            ),
        },
        "elapsed_seconds": float(time.perf_counter() - started),
    }
    _progress(
        progress,
        "color_depth_exact_done",
        0.75,
        "ColorDepth exact partition ready",
    )
    return ConformingColorDepthPartition(
        nodes_mm=result.nodes_mm,
        tetrahedra=result.tetrahedra,
        cell_owner_labels=result.cell_owner_labels,
        cell_depth_bounds_mm=result.cell_depth_bounds_mm,
        cell_materials=result.cell_materials,
        unsafe_outer_only_cells=result.unsafe_outer_only_cells,
        exterior_faces=result.exterior_faces,
        exterior_owner_cells=result.exterior_owner_cells,
        exterior_source_face_ids=result.exterior_source_face_ids,
        threshold_interface_conforming=result.threshold_interface_conforming,
        shared_interface_partition_exact=result.shared_interface_partition_exact,
        max_safe_threshold_error_mm=result.max_safe_threshold_error_mm,
        max_safe_threshold_error_limit_mm=result.max_safe_threshold_error_limit_mm,
        metadata=metadata,
    )


__all__ = [
    "COLOR_DEPTH_EXACT_PARTITION_SCHEMA",
    "ColorDepthExactPartitionError",
    "build_conforming_color_depth_partition",
]
