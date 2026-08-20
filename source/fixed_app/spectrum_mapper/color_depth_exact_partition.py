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
* splits one common outer-depth level set conformingly through every crossed
  tetrahedron;
* derives a one-edge-ring unsafe source mask from true interface-distance
  error and changes those complete owner columns to outer-only material; and
* directly joins every generated threshold triangle to its two final child
  cells before certifying the array contract.

The output remains uncalibrated and SLICE ONLY.  A finite backing/core recipe
requires another conforming threshold and is rejected rather than silently
approximated by cell centroids.
"""

from __future__ import annotations

import math
import time
from typing import Callable, Mapping

import numpy as np
import trimesh

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
) -> tuple[float, dict[int, int], dict[int, int]]:
    used = set(map(int, np.unique(source.face_target_labels)))
    missing = sorted(used - {int(value) for value in recipes})
    if missing:
        _raise("source_recipe_missing", target_labels=missing)
    thresholds: list[float] = []
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
        thresholds.append(float(recipe.outer_thickness_mm))
        outer[label] = int(recipe.outer_physical)
        backing[label] = int(recipe.backing_physical)
    if not thresholds:
        _raise("recipes_required")
    threshold = thresholds[0]
    if any(abs(value - threshold) > 1e-12 for value in thresholds[1:]):
        _raise(
            "common_outer_thickness_required",
            outer_thicknesses_mm=sorted(set(thresholds)),
        )
    return threshold, outer, backing


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
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    Mapping[str, object],
]:
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
    node_depth, _node_faces = _closest_source(
        source_mesh, source_nodes, chunk_size=chunk_size
    )
    boundary_node_ids = np.unique(np.asarray(boundary_faces, dtype=np.int32))
    node_depth[boundary_node_ids] = 0.0
    scalar = node_depth - float(threshold_mm)
    existing_positive = int(
        np.count_nonzero(scalar > 1e-12)
    )
    # Normal production meshes already contain a resolved positive side.  In
    # that case retain the scratch/proof path exactly and avoid a second
    # closest-point pass over potentially millions of cell centres.
    if existing_positive:
        return (
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
    all_outer = np.max(scalar[source_tets], axis=1) <= 1e-12
    candidate_ids = np.flatnonzero(all_outer)
    if len(candidate_ids):
        candidate_centers = source_nodes[source_tets[candidate_ids]].mean(axis=1)
        center_depth, _center_faces = _closest_source(
            source_mesh, candidate_centers, chunk_size=chunk_size
        )
        hidden_mask = center_depth > float(threshold_mm) + 1e-12
        hidden_ids = candidate_ids[hidden_mask]
        hidden_centers = candidate_centers[hidden_mask]
        hidden_depth = center_depth[hidden_mask]
    else:
        center_depth = np.empty(0, dtype=np.float64)
        hidden_ids = np.empty(0, dtype=np.int32)
        hidden_centers = np.empty((0, 3), dtype=np.float64)
        hidden_depth = np.empty(0, dtype=np.float64)

    if not len(hidden_ids):
        return (
            source_nodes.copy(),
            source_tets.copy(),
            np.asarray(boundary_faces, dtype=np.int32).copy(),
            np.asarray(boundary_cells, dtype=np.int32).copy(),
            np.asarray(boundary_labels, dtype=np.int32).copy(),
            np.asarray(boundary_parent_faces, dtype=np.int32).copy(),
            np.ascontiguousarray(node_depth, dtype=np.float64),
            {
                "mode": "boundary_only_visibility_probe",
                "existing_positive_nodes": 0,
                "candidate_all_outer_cells": int(len(candidate_ids)),
                "hidden_threshold_cells": 0,
                "added_centroid_nodes": 0,
                "output_tetrahedra": int(len(source_tets)),
                "visible_boundary_preserved": True,
                "volume_error_mm3": 0.0,
                "maximum_candidate_centroid_depth_mm": float(
                    np.max(center_depth, initial=0.0)
                ),
            },
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
        (len(source_tets) + 3 * len(hidden_ids), 4), dtype=np.int32
    )
    cursor = 0
    for cell_id, tet in enumerate(source_tets):
        hidden_local = int(hidden_lookup[cell_id])
        if hidden_local < 0:
            candidate = tet.copy()
            if _signed_six(refined_nodes, candidate.reshape((1, 4)))[0] < 0.0:
                candidate[[1, 2]] = candidate[[2, 1]]
            refined_tets[cursor] = candidate
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
    return (
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
            "mode": "boundary_only_visibility_probe",
            "existing_positive_nodes": 0,
            "candidate_all_outer_cells": int(len(candidate_ids)),
            "hidden_threshold_cells": int(len(hidden_ids)),
            "added_centroid_nodes": int(len(hidden_ids)),
            "output_tetrahedra": int(len(refined_tets)),
            "visible_boundary_preserved": True,
            "volume_error_mm3": volume_error,
            "maximum_candidate_centroid_depth_mm": float(
                np.max(center_depth, initial=0.0)
            ),
            "minimum_inserted_centroid_depth_mm": float(
                np.min(hidden_depth)
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
    error_limit_mm: float,
    chunk_size: int,
    progress: Callable[..., object] | None,
) -> ConformingColorDepthPartition:
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
    near_zero = np.abs(scalar) <= 1e-12
    scalar[near_zero] = np.where(scalar[near_zero] <= 0.0, -1e-12, 1e-12)

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
    interface_distance, interface_closest_face = _closest_source(
        source_mesh, interface_points, chunk_size=chunk_size
    )
    interface_error = np.abs(interface_distance - float(threshold_mm))
    raw_unsafe_source = np.zeros(len(source.faces), dtype=bool)
    bad_interface = interface_error > float(error_limit_mm) + 1e-12
    raw_unsafe_source[interface_closest_face[bad_interface]] = True
    unsafe_source = _source_face_one_ring(source.faces, raw_unsafe_source)
    interface_unsafe = (
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
    parent_unsafe = unsafe_source[parent_source_face]
    boundary_face_unsafe = unsafe_source[boundary_parent_faces]
    np.logical_or.at(parent_unsafe, boundary_cells, boundary_face_unsafe)
    if np.any(~parent_unsafe[boundary_cells[boundary_face_unsafe]]):
        _raise("boundary_unsafe_or_aggregation_failed")
    crossing_counts = edge_crosses.sum(axis=1)
    crossing_parent_for_edge = np.repeat(crossing_ids, crossing_counts)
    if len(crossing_parent_for_edge):
        unsafe_crossing_edge = interface_unsafe[crossing_edge_inverse]
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
    all_coordinates = np.empty(
        (len(nodes) + len(interface_points) + 2 * len(crossing_ids), 3),
        dtype=np.float64,
    )
    all_coordinates[: len(nodes)] = nodes
    all_coordinates[
        len(nodes) : len(nodes) + len(interface_points)
    ] = interface_points
    noncrossing = np.flatnonzero(~(has_negative & has_positive))
    capacity = int(len(noncrossing) + 16 * len(crossing_ids))
    output_tets = np.empty((capacity, 4), dtype=np.int32)
    output_parents = np.empty(capacity, dtype=np.int32)
    output_side = np.empty(capacity, dtype=np.int8)
    output_owner = np.empty(capacity, dtype=np.int32)
    output_source_face = np.empty(capacity, dtype=np.int32)
    output_unsafe = np.empty(capacity, dtype=bool)
    output_material = np.empty(capacity, dtype=np.int8)
    output_bounds = np.empty((capacity, 2), dtype=np.float64)
    interface_triangles = np.empty(
        (2 * len(crossing_ids), 3), dtype=np.int32
    )
    interface_parent = np.empty(2 * len(crossing_ids), dtype=np.int32)
    cursor = 0
    interface_cursor = 0
    maximum_depth = max(float(np.max(node_depth, initial=0.0)), threshold_mm)

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
        material = int(outer_by_label[label])
        if side > 0 and not unsafe:
            material = int(backing_by_label[label])
        output_tets[cursor] = candidate
        output_parents[cursor] = parent
        output_side[cursor] = side
        output_owner[cursor] = label
        output_source_face[cursor] = int(parent_source_face[parent])
        output_unsafe[cursor] = unsafe
        output_material[cursor] = material
        output_bounds[cursor] = (
            (0.0, threshold_mm)
            if side < 0
            else (threshold_mm, maximum_depth)
        )
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
            centroid_id = centroid_base + 2 * sequence + (0 if side < 0 else 1)
            all_coordinates[centroid_id] = all_coordinates[used].mean(axis=0)
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

    output_tets = output_tets[:cursor].copy()
    output_parents = output_parents[:cursor].copy()
    output_side = output_side[:cursor].copy()
    output_owner = output_owner[:cursor].copy()
    output_source_face = output_source_face[:cursor].copy()
    output_unsafe = output_unsafe[:cursor].copy()
    output_material = output_material[:cursor].copy()
    output_bounds = output_bounds[:cursor].copy()
    interface_triangles = interface_triangles[:interface_cursor].copy()
    interface_parent = interface_parent[:interface_cursor].copy()

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
        triangle_unsafe = interface_unsafe[triangle_local].any(axis=1) | (
            triangle_error > float(error_limit_mm) + 1e-12
        )
        material_changes = (
            output_material[first_cells] != output_material[second_cells]
        )
        unsafe_changing = triangle_unsafe & material_changes
        if np.any(unsafe_changing):
            _raise(
                "unsafe_threshold_triangle_changes_material",
                faces=int(np.count_nonzero(unsafe_changing)),
            )
        changing_error = triangle_error[material_changes]
        if float(np.max(changing_error, initial=0.0)) > error_limit_mm + 1e-12:
            _raise("material_changing_threshold_error_exceeded")
        unsafe_cells = np.concatenate(
            (first_cells[triangle_unsafe], second_cells[triangle_unsafe])
        )
        if np.any(~output_unsafe[unsafe_cells]):
            _raise("unsafe_threshold_child_not_flagged")
        unsafe_expected_outer = np.asarray(
            [outer_by_label[int(label)] for label in output_owner[unsafe_cells]],
            dtype=np.int8,
        )
        if not np.array_equal(output_material[unsafe_cells], unsafe_expected_outer):
            _raise("unsafe_threshold_child_not_outer_only")
        safe_changing_error = float(np.max(changing_error, initial=0.0))
    else:
        triangle_error = np.empty(0, dtype=np.float64)
        triangle_unsafe = np.empty(0, dtype=bool)
        material_changes = np.empty(0, dtype=bool)
        first_cells = np.empty(0, dtype=np.int32)
        second_cells = np.empty(0, dtype=np.int32)
        safe_changing_error = 0.0

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
    safe_interface_error = interface_error[~interface_unsafe]
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
    return ConformingColorDepthPartition(
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
            "boundary_unsafe_or_aggregation_verified": True,
            "unsafe_columns_outer_only_verified": True,
            "interface_vertices": int(len(interface_points)),
            "interface_triangles": int(len(interface_triangles)),
            "unsafe_interface_vertices": int(np.count_nonzero(interface_unsafe)),
            "material_changing_threshold_triangles": int(
                np.count_nonzero(material_changes)
            ),
            "unsafe_material_changing_threshold_triangles": 0,
            "maximum_safe_interface_error_mm": maximum_safe_error,
            "maximum_material_changing_interface_error_mm": safe_changing_error,
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
    threshold, outer, backing = _validate_recipes(source, recipes)
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
        "ColorDepth common-depth conforming split",
    )
    result = _build_threshold_partition(
        source=source,
        source_mesh=source_mesh,
        recipes=recipes,
        threshold_mm=threshold,
        outer_by_label=outer,
        backing_by_label=backing,
        nodes=refined_nodes,
        tets=refined_tets,
        owner_labels=owner_labels,
        owner_source_faces=owner_source_faces,
        boundary_faces=boundary_faces,
        boundary_cells=refined_boundary_cells,
        boundary_labels=boundary_labels,
        boundary_parent_faces=boundary_parents,
        node_depth=refined_node_depth,
        error_limit_mm=error_limit,
        chunk_size=chunk_size,
        progress=progress,
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
