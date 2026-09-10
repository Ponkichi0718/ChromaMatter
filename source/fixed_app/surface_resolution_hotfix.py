"""Preserve curved-part solidification while honoring the requested face budget.

The r7 curved-boundary path intentionally uses a coarse fTetWild volume mesh
to obtain a robust topology. That topology is safe, but it also replaces a
450k/1.9M input surface with roughly 60k--70k triangles. Making fTetWild itself
very dense is not a practical fix: tetrahedra grow cubically with resolution.

This module keeps the validated fTetWild/harmonic result as the topology and
geometry authority and refines only its exterior triangulation afterwards.
Cross-part shared interface triangles are detected geometrically, locked
byte-for-byte, and never split. The production wrapper inserts exact linear
edge midpoints, so the strict-validated surface cannot move. Projection code
is retained only as an explicit opt-in experiment; it is never enabled by the
installed hotfix.

Recovered from the packaged r8 Python 3.13 code object and retained as a
source-level hotfix so builds do not depend on recovered bytecode.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from contextvars import ContextVar
from dataclasses import dataclass
import functools
import math
from typing import Callable, Iterable, Sequence

import numpy as np


SURFACE_RESOLUTION_HOTFIX_VERSION = "0.8beta-r8-surface-resolution-3"
DEFAULT_MAX_TARGET_FACES = 2_500_000
DEFAULT_PROJECTION_LIMIT_MM = 0.2
DEFAULT_PROJECTION_EDGE_FRACTION = 0.35
DEFAULT_MIN_NORMAL_DOT = 0.0
DEFAULT_MAX_VOLUME_CHANGE_RELATIVE = 0.02
DEFAULT_LINEAR_MAX_VOLUME_CHANGE_RELATIVE = 1e-10
INHERITED_SELF_INTERSECTION_CHECK = "inherited_from_strict_validated_base"

_LINEAR_EXPORT_VALIDATION_CONTEXT: ContextVar[dict[str, object] | None] = ContextVar(
    "r8_linear_export_validation_context", default=None
)
_FACE_PROVENANCE_PROPAGATION_CONTEXT: ContextVar[dict[str, object] | None] = (
    ContextVar("r8_surface_face_provenance_context", default=None)
)


class SurfaceResolutionError(RuntimeError):
    """Raised when refinement cannot preserve a verified solid/interface."""


@dataclass(frozen=True)
class _InterfaceDetection:
    masks: tuple[np.ndarray, ...]
    tolerance_unit: float
    shared_face_keys: int
    pair_face_counts: dict[str, int]
    signature: tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]
    byte_signature: tuple[tuple[int, tuple[bytes, ...]], ...]


@dataclass
class _ProjectionResult:
    points: np.ndarray
    accepted: np.ndarray
    distances: np.ndarray
    triangle_ids: np.ndarray


def _emit(
    progress: Callable[..., object] | None, fraction: float, message: str
) -> None:
    if progress is None:
        return
    try:
        progress("surface_resolution", float(fraction), str(message))
    except TypeError:
        progress(float(fraction), str(message))


def _mesh_tuple(
    mesh: Sequence[np.ndarray], label: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(mesh) != 3:
        raise SurfaceResolutionError(f"{label}: mesh must be (vertices, faces, colors)")
    vertices = np.asarray(mesh[0], dtype=np.float64)
    faces = np.asarray(mesh[1], dtype=np.int32)
    colors = np.asarray(mesh[2], dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise SurfaceResolutionError(f"{label}: invalid vertices")
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise SurfaceResolutionError(f"{label}: invalid faces")
    if len(faces) and (int(faces.min()) < 0 or int(faces.max()) >= len(vertices)):
        raise SurfaceResolutionError(f"{label}: face index out of range")
    if colors.ndim != 2 or len(colors) != len(vertices) or colors.shape[1] < 3:
        raise SurfaceResolutionError(f"{label}: invalid vertex colors")
    return vertices, faces, colors


def _face_cross(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    triangles = vertices[faces]
    return np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])


def _unit_rows(values: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(values, axis=1)
    result = np.zeros_like(values, dtype=np.float64)
    valid = lengths > 1e-30
    result[valid] = values[valid] / lengths[valid, None]
    return result


def _quantized_face_key(vertices_q: np.ndarray, face: np.ndarray) -> tuple[int, ...]:
    points = np.asarray(vertices_q[np.asarray(face, dtype=np.int64)])
    order = np.lexsort((points[:, 2], points[:, 1], points[:, 0]))
    return tuple(int(value) for value in points[order].reshape(-1))


def _interface_signature(
    meshes: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
    masks: Sequence[np.ndarray],
    tolerance_unit: float,
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    occurrences: defaultdict[tuple[int, ...], list[int]] = defaultdict(list)
    for part_id, ((vertices, faces, _colors), mask) in enumerate(
        zip(meshes, masks, strict=True)
    ):
        quantized = np.rint(vertices / tolerance_unit).astype(np.int64)
        for face in faces[np.asarray(mask, dtype=bool)]:
            occurrences[_quantized_face_key(quantized, face)].append(int(part_id))
    return tuple(
        sorted((key, tuple(sorted(part_ids))) for key, part_ids in occurrences.items())
    )


def _interface_byte_signature(
    meshes: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
    masks: Sequence[np.ndarray],
) -> tuple[tuple[int, tuple[bytes, ...]], ...]:
    result: list[tuple[int, tuple[bytes, ...]]] = []
    for part_id, ((vertices, faces, _colors), mask) in enumerate(
        zip(meshes, masks, strict=True)
    ):
        triangles = np.asarray(vertices, dtype=np.float64)[
            np.asarray(faces, dtype=np.int64)[np.asarray(mask, dtype=bool)]
        ]
        encoded = tuple(
            sorted(
                np.ascontiguousarray(triangle).view(np.uint8).tobytes()
                for triangle in triangles
            )
        )
        result.append((int(part_id), encoded))
    return tuple(result)


def detect_shared_interfaces(
    meshes: Sequence[Sequence[np.ndarray]], tolerance_unit: float | None = None
) -> _InterfaceDetection:
    """Find exact, oppositely wound faces shared by two output parts."""
    checked = [_mesh_tuple(mesh, f"part {index}") for index, mesh in enumerate(meshes)]
    if len(checked) < 2:
        raise SurfaceResolutionError("curved partition refinement needs at least two parts")
    all_vertices = np.vstack([mesh[0] for mesh in checked])
    extent = float(np.max(np.ptp(all_vertices, axis=0), initial=0.0))
    if tolerance_unit is None:
        tolerance_unit = max(extent * 1e-10, 1e-12)
    tolerance_unit = float(tolerance_unit)
    if not math.isfinite(tolerance_unit) or tolerance_unit <= 0.0:
        raise SurfaceResolutionError("invalid interface tolerance")

    occurrences: defaultdict[tuple[int, ...], list[tuple[int, int]]] = defaultdict(list)
    face_normals: list[np.ndarray] = []
    for part_id, (vertices, faces, _colors) in enumerate(checked):
        quantized = np.rint(vertices / tolerance_unit).astype(np.int64)
        face_normals.append(_unit_rows(_face_cross(vertices, faces)))
        for face_id, face in enumerate(faces):
            occurrences[_quantized_face_key(quantized, face)].append((part_id, face_id))

    masks = [np.zeros(len(mesh[1]), dtype=bool) for mesh in checked]
    pair_counts: Counter[str] = Counter()
    shared_keys = 0
    ambiguous = 0
    same_winding = 0
    for found in occurrences.values():
        part_ids = {part_id for part_id, _face_id in found}
        if len(part_ids) <= 1:
            continue
        if len(found) != 2 or len(part_ids) != 2:
            ambiguous += 1
            continue
        (first_part, first_face), (second_part, second_face) = found
        dot = float(
            np.dot(
                face_normals[first_part][first_face],
                face_normals[second_part][second_face],
            )
        )
        if not math.isfinite(dot) or dot > -0.999:
            same_winding += 1
            continue
        masks[first_part][first_face] = True
        masks[second_part][second_face] = True
        pair = f"{min(first_part, second_part)}-{max(first_part, second_part)}"
        pair_counts[pair] += 1
        shared_keys += 1

    if ambiguous:
        raise SurfaceResolutionError(f"ambiguous shared interface faces: {ambiguous}")
    if same_winding:
        raise SurfaceResolutionError(
            f"shared faces without opposite winding: {same_winding}"
        )
    if shared_keys <= 0:
        raise SurfaceResolutionError("no exact cross-part shared interface was found")

    checked_tuple = tuple(checked)
    masks_tuple = tuple(masks)
    signature = _interface_signature(checked_tuple, masks_tuple, tolerance_unit)
    byte_signature = _interface_byte_signature(checked_tuple, masks_tuple)
    return _InterfaceDetection(
        masks=masks_tuple,
        tolerance_unit=tolerance_unit,
        shared_face_keys=int(shared_keys),
        pair_face_counts=dict(sorted(pair_counts.items())),
        signature=signature,
        byte_signature=byte_signature,
    )


class _SourceProjector:
    def __init__(
        self,
        vertices: np.ndarray,
        faces: np.ndarray,
        colors: np.ndarray,
        *,
        chunk_size: int = 20_000,
    ) -> None:
        try:
            import trimesh
        except Exception as exc:
            raise SurfaceResolutionError(f"trimesh is unavailable: {exc}") from exc
        self._trimesh = trimesh
        self.vertices = np.asarray(vertices, dtype=np.float64)
        self.faces = np.asarray(faces, dtype=np.int64)
        self.colors = np.asarray(colors, dtype=np.float64)
        self.mesh = trimesh.Trimesh(
            vertices=self.vertices, faces=self.faces, process=False
        )
        self.face_normals = _unit_rows(_face_cross(self.vertices, self.faces))
        self.chunk_size = max(1_000, int(chunk_size))

    def closest(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        points = np.asarray(points, dtype=np.float64)
        closest_parts: list[np.ndarray] = []
        distance_parts: list[np.ndarray] = []
        triangle_parts: list[np.ndarray] = []
        for start in range(0, len(points), self.chunk_size):
            closest, distance, triangle_ids = self._trimesh.proximity.closest_point(
                self.mesh, points[start : start + self.chunk_size]
            )
            closest_parts.append(np.asarray(closest, dtype=np.float64))
            distance_parts.append(np.asarray(distance, dtype=np.float64))
            triangle_parts.append(np.asarray(triangle_ids, dtype=np.int64))
        if not closest_parts:
            return (
                np.empty((0, 3), dtype=np.float64),
                np.empty(0, dtype=np.float64),
                np.empty(0, dtype=np.int64),
            )
        return (
            np.vstack(closest_parts),
            np.concatenate(distance_parts),
            np.concatenate(triangle_parts),
        )

    def guarded_projection(
        self,
        points: np.ndarray,
        reference_normals: np.ndarray,
        maximum_distance: float | np.ndarray,
        *,
        minimum_normal_dot: float = DEFAULT_MIN_NORMAL_DOT,
    ) -> _ProjectionResult:
        points = np.asarray(points, dtype=np.float64)
        reference_normals = _unit_rows(np.asarray(reference_normals, dtype=np.float64))
        closest, distances, triangle_ids = self.closest(points)
        source_normals = self.face_normals[
            np.clip(triangle_ids, 0, max(0, len(self.face_normals) - 1))
        ]
        dots = np.einsum("ij,ij->i", reference_normals, source_normals)
        maximum = np.asarray(maximum_distance, dtype=np.float64)
        accepted = (
            np.isfinite(distances)
            & np.isfinite(closest).all(axis=1)
            & (distances <= maximum)
            & (dots >= float(minimum_normal_dot))
        )
        result = points.copy()
        result[accepted] = closest[accepted]
        return _ProjectionResult(result, accepted, distances, triangle_ids)

    def transfer_colors(self, points: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
        points = np.asarray(points, dtype=np.float64)
        closest, distances, triangle_ids = self.closest(points)
        triangles = self.vertices[self.faces[triangle_ids]]
        weights = self._trimesh.triangles.points_to_barycentric(triangles, closest)
        weights = np.clip(np.asarray(weights, dtype=np.float64), 0.0, 1.0)
        weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-15)
        colors = np.einsum("ij,ijk->ik", weights, self.colors[self.faces[triangle_ids]])
        return np.clip(colors, 0.0, 1.0), {
            "nearest_source_distance_max_unit": float(np.max(distances, initial=0.0)),
            "nearest_source_distance_mean_unit": (
                float(np.mean(distances)) if len(distances) else 0.0
            ),
        }


def _orientation_is_safe(
    old_vertices: np.ndarray,
    new_vertices: np.ndarray,
    faces: np.ndarray,
    *,
    minimum_cosine: float = 0.02,
) -> bool:
    old_cross = _face_cross(old_vertices, faces)
    new_cross = _face_cross(new_vertices, faces)
    old_length = np.linalg.norm(old_cross, axis=1)
    new_length = np.linalg.norm(new_cross, axis=1)
    scale = max(float(np.max(np.ptp(old_vertices, axis=0), initial=0.0)), 1.0)
    minimum_area2 = scale * scale * 1e-14
    valid = (old_length > minimum_area2) & (new_length > minimum_area2)
    if not np.all(valid):
        return False
    cosine = np.einsum("ij,ij->i", old_cross, new_cross) / np.maximum(
        old_length * new_length, 1e-30
    )
    return bool(np.all(cosine >= float(minimum_cosine)))


def _project_existing_exterior_vertices(
    vertices: np.ndarray,
    faces: np.ndarray,
    interface_faces: np.ndarray,
    projector: _SourceProjector,
    maximum_distance_unit: float,
) -> tuple[np.ndarray, dict[str, object]]:
    locked_vertices = np.zeros(len(vertices), dtype=bool)
    if bool(np.any(interface_faces)):
        locked_vertices[np.unique(faces[interface_faces])] = True
    movable = np.flatnonzero(~locked_vertices)
    if not len(movable):
        return vertices.copy(), {"movable": 0, "accepted": 0, "line_search": 0.0}
    face_cross = _face_cross(vertices, faces)
    vertex_normals = np.zeros_like(vertices, dtype=np.float64)
    for corner in range(3):
        np.add.at(vertex_normals, faces[:, corner], face_cross)
    vertex_normals = _unit_rows(vertex_normals)
    projected = projector.guarded_projection(
        vertices[movable], vertex_normals[movable], float(maximum_distance_unit)
    )
    displacement = projected.points - vertices[movable]
    accepted_count = int(np.count_nonzero(projected.accepted))
    chosen = vertices.copy()
    chosen_alpha = 0.0
    for alpha in (1.0, 0.5, 0.25):
        candidate = vertices.copy()
        candidate[movable] = vertices[movable] + alpha * displacement
        candidate[locked_vertices] = vertices[locked_vertices]
        if not _orientation_is_safe(vertices, candidate, faces):
            continue
        chosen = candidate
        chosen_alpha = alpha
        break
    return chosen, {
        "movable": int(len(movable)),
        "locked_interface_vertices": int(np.count_nonzero(locked_vertices)),
        "accepted": accepted_count,
        "rejected": int(len(movable) - accepted_count),
        "line_search": float(chosen_alpha),
        "maximum_query_distance_unit": float(
            np.max(projected.distances, initial=0.0)
        ),
    }


def _edge_table(
    faces: np.ndarray, interface_faces: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    face_count = len(faces)
    flat_edges = np.empty((face_count * 3, 2), dtype=np.int32)
    flat_edges[0::3] = faces[:, [0, 1]]
    flat_edges[1::3] = faces[:, [1, 2]]
    flat_edges[2::3] = faces[:, [2, 0]]
    flat_edges.sort(axis=1)
    unique_edges, inverse, counts = np.unique(
        flat_edges, axis=0, return_inverse=True, return_counts=True
    )
    inverse = np.asarray(inverse, dtype=np.int64)
    counts = np.asarray(counts, dtype=np.int64)
    edge_locked = np.zeros(len(unique_edges), dtype=bool)
    np.logical_or.at(
        edge_locked, inverse, np.repeat(np.asarray(interface_faces, dtype=bool), 3)
    )
    eligible = (counts == 2) & ~edge_locked
    return unique_edges, inverse, counts, edge_locked, eligible


def _children_for_pattern(
    pattern: int, vertices: np.ndarray, midpoints: np.ndarray
) -> np.ndarray:
    v0, v1, v2 = vertices[:, 0], vertices[:, 1], vertices[:, 2]
    m01, m12, m20 = midpoints[:, 0], midpoints[:, 1], midpoints[:, 2]
    if pattern == 0:
        return np.stack((v0, v1, v2), axis=1)[:, None, :]
    if pattern == 1:
        return np.stack(
            (np.stack((v0, m01, v2), 1), np.stack((m01, v1, v2), 1)), 1
        )
    if pattern == 2:
        return np.stack(
            (np.stack((v1, m12, v0), 1), np.stack((m12, v2, v0), 1)), 1
        )
    if pattern == 4:
        return np.stack(
            (np.stack((v2, m20, v1), 1), np.stack((m20, v0, v1), 1)), 1
        )
    if pattern == 3:
        return np.stack(
            (
                np.stack((v1, m12, m01), 1),
                np.stack((v0, m01, v2), 1),
                np.stack((m01, m12, v2), 1),
            ),
            1,
        )
    if pattern == 6:
        return np.stack(
            (
                np.stack((v2, m20, m12), 1),
                np.stack((v1, m12, v0), 1),
                np.stack((m12, m20, v0), 1),
            ),
            1,
        )
    if pattern == 5:
        return np.stack(
            (
                np.stack((v0, m01, m20), 1),
                np.stack((v2, m20, v1), 1),
                np.stack((m20, m01, v1), 1),
            ),
            1,
        )
    if pattern == 7:
        return np.stack(
            (
                np.stack((v0, m01, m20), 1),
                np.stack((m01, v1, m12), 1),
                np.stack((m20, m12, v2), 1),
                np.stack((m01, m12, m20), 1),
            ),
            1,
        )
    raise AssertionError(pattern)


def _split_edges_once(
    vertices: np.ndarray,
    faces: np.ndarray,
    interface_faces: np.ndarray,
    split_count: int,
    projector: _SourceProjector,
    maximum_distance_unit: float,
    *,
    projection_enabled: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    unique_edges, inverse, counts, _edge_locked, eligible = _edge_table(
        faces, interface_faces
    )
    if bool(np.any(counts != 2)):
        boundary = int(np.count_nonzero(counts == 1))
        nonmanifold = int(np.count_nonzero(counts > 2))
        raise SurfaceResolutionError(
            f"input is not a closed 2-manifold (boundary={boundary}, nonmanifold={nonmanifold})"
        )
    eligible_ids = np.flatnonzero(eligible)
    split_count = min(max(0, int(split_count)), len(eligible_ids))
    if split_count <= 0:
        raise SurfaceResolutionError("no exterior edge is available for safe refinement")

    edge_vectors = vertices[unique_edges[:, 1]] - vertices[unique_edges[:, 0]]
    edge_lengths = np.linalg.norm(edge_vectors, axis=1)
    if split_count < len(eligible_ids):
        eligible_lengths = edge_lengths[eligible_ids]
        choice = np.argpartition(eligible_lengths, len(eligible_lengths) - split_count)[
            -split_count:
        ]
        selected_ids = eligible_ids[choice]
    else:
        selected_ids = eligible_ids

    selected = np.zeros(len(unique_edges), dtype=bool)
    selected[selected_ids] = True
    midpoint_index = np.full(len(unique_edges), -1, dtype=np.int64)
    midpoint_index[selected_ids] = np.arange(
        len(vertices), len(vertices) + len(selected_ids), dtype=np.int64
    )
    raw_midpoints = (
        vertices[unique_edges[selected_ids, 0]] + vertices[unique_edges[selected_ids, 1]]
    ) * 0.5
    face_normals = _unit_rows(_face_cross(vertices, faces))

    if projection_enabled:
        edge_normal_sum = np.zeros((len(unique_edges), 3), dtype=np.float64)
        np.add.at(edge_normal_sum, inverse, np.repeat(face_normals, 3, axis=0))
        reference_normals = _unit_rows(edge_normal_sum[selected_ids])
        maximum = np.minimum(
            float(maximum_distance_unit),
            edge_lengths[selected_ids] * DEFAULT_PROJECTION_EDGE_FRACTION,
        )
        projected = projector.guarded_projection(
            raw_midpoints, reference_normals, maximum
        )
        midpoint_points = projected.points
        projection_accepted = np.asarray(projected.accepted, dtype=bool)
    else:
        midpoint_points = raw_midpoints
        projection_accepted = np.zeros(len(raw_midpoints), dtype=bool)

    new_vertices = np.vstack((vertices, midpoint_points))
    selected_by_face = selected[inverse].reshape((-1, 3))
    midpoint_by_face = midpoint_index[inverse].reshape((-1, 3))
    patterns = (
        selected_by_face[:, 0].astype(np.uint8)
        | (selected_by_face[:, 1].astype(np.uint8) << 1)
        | (selected_by_face[:, 2].astype(np.uint8) << 2)
    )
    child_counts = 1 + selected_by_face.sum(axis=1, dtype=np.int64)
    starts = np.empty(len(faces), dtype=np.int64)
    if len(starts):
        starts[0] = 0
        if len(starts) > 1:
            starts[1:] = np.cumsum(child_counts[:-1])
    output_count = int(child_counts.sum())
    expected_count = int(len(faces) + 2 * len(selected_ids))
    if output_count != expected_count:
        raise AssertionError((output_count, expected_count))
    new_faces = np.empty((output_count, 3), dtype=np.int32)
    new_interface = np.empty(output_count, dtype=bool)
    parent_faces = np.empty(output_count, dtype=np.int64)
    for pattern in range(8):
        face_ids = np.flatnonzero(patterns == pattern)
        if not len(face_ids):
            continue
        children = _children_for_pattern(
            pattern, faces[face_ids], midpoint_by_face[face_ids]
        )
        child_number = children.shape[1]
        destinations = starts[face_ids, None] + np.arange(
            child_number, dtype=np.int64
        )[None, :]
        destination_flat = destinations.reshape(-1)
        new_faces[destination_flat] = children.reshape((-1, 3)).astype(
            np.int32, copy=False
        )
        new_interface[destination_flat] = np.repeat(
            interface_faces[face_ids], child_number
        )
        parent_faces[destination_flat] = np.repeat(face_ids, child_number)

    original_face_normals = face_normals[parent_faces]
    projected_vertex_ids = np.arange(len(vertices), len(new_vertices), dtype=np.int64)
    reverted = np.zeros(len(projected_vertex_ids), dtype=bool)

    def unsafe_children() -> np.ndarray:
        child_cross = _face_cross(new_vertices, new_faces)
        child_norm = np.linalg.norm(child_cross, axis=1)
        dots = np.einsum(
            "ij,ij->i", _unit_rows(child_cross), original_face_normals
        )
        scale = max(
            float(np.max(np.ptp(vertices, axis=0), initial=0.0)),
            1.0,
        )
        return (child_norm <= scale * scale * 1e-14) | (dots < 0.02)

    for _attempt in range(8):
        bad = unsafe_children()
        if not bool(np.any(bad)):
            break
        bad_vertices = np.unique(new_faces[bad])
        bad_new = bad_vertices[bad_vertices >= len(vertices)] - len(vertices)
        if not len(bad_new):
            raise SurfaceResolutionError(
                "refinement produced an unsafe child triangle"
            )
        new_vertices[len(vertices) + bad_new] = raw_midpoints[bad_new]
        reverted[bad_new] = True
    else:
        new_vertices[len(vertices) :] = raw_midpoints
        reverted[:] = True
        if bool(np.any(unsafe_children())):
            raise SurfaceResolutionError(
                "linear refinement could not preserve orientation"
            )

    if int(np.count_nonzero(new_interface)) != int(np.count_nonzero(interface_faces)):
        raise SurfaceResolutionError(
            "shared interface triangles were unexpectedly subdivided"
        )

    provenance_context = _FACE_PROVENANCE_PROPAGATION_CONTEXT.get()
    if provenance_context is not None:
        from spectrum_mapper.generated_surface_color import (
            propagate_face_provenance,
        )

        part_id = int(provenance_context["part_id"])
        provenance_parts = provenance_context["parts"]
        provenance_parts[part_id] = propagate_face_provenance(
            provenance_parts[part_id], parent_faces
        )

    return new_vertices, new_faces, new_interface, {
        "split_edges": int(len(selected_ids)),
        "faces_before": int(len(faces)),
        "faces_after": int(len(new_faces)),
        "projection_enabled": bool(projection_enabled),
        "projection_accepted": int(np.count_nonzero(projection_accepted)),
        "projection_rejected": (
            int(len(projection_accepted) - np.count_nonzero(projection_accepted))
            if projection_enabled
            else 0
        ),
        "projection_reverted_for_orientation": int(np.count_nonzero(reverted)),
    }


def _signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    triangles = np.asarray(vertices, dtype=np.float64)[
        np.asarray(faces, dtype=np.int64)
    ]
    return float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )


def _mesh_body_count(faces: np.ndarray, vertex_count: int) -> int:
    """Count vertex-connected bodies on the small, validated base mesh."""
    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
    except Exception as exc:
        raise SurfaceResolutionError(
            f"body connectivity check is unavailable: {exc}"
        ) from exc
    faces = np.asarray(faces, dtype=np.int64)
    if not len(faces):
        return 0
    edges = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    rows = np.concatenate((edges[:, 0], edges[:, 1]))
    cols = np.concatenate((edges[:, 1], edges[:, 0]))
    graph = coo_matrix(
        (np.ones(len(rows), dtype=np.uint8), (rows, cols)),
        shape=(int(vertex_count), int(vertex_count)),
    ).tocsr()
    _count, labels = connected_components(graph, directed=False, return_labels=True)
    used = np.unique(faces)
    return int(len(np.unique(labels[used])))


def _edge_topology_counts(faces: np.ndarray) -> tuple[int, int, int]:
    """Return boundary/nonmanifold/winding errors with one edge sort."""
    faces = np.asarray(faces, dtype=np.int32)
    directed = np.empty((len(faces) * 3, 2), dtype=np.int32)
    directed[0::3] = faces[:, [0, 1]]
    directed[1::3] = faces[:, [1, 2]]
    directed[2::3] = faces[:, [2, 0]]
    direction = np.where(directed[:, 0] < directed[:, 1], 1, -1).astype(np.int8)
    directed.sort(axis=1)
    _unique, inverse, counts = np.unique(
        directed, axis=0, return_inverse=True, return_counts=True
    )
    direction_sum = np.zeros(len(counts), dtype=np.int16)
    np.add.at(direction_sum, inverse, direction)
    return (
        int(np.count_nonzero(counts == 1)),
        int(np.count_nonzero(counts > 2)),
        int(np.count_nonzero((counts == 2) & (direction_sum != 0))),
    )


def _byte_identical(first: np.ndarray, second: np.ndarray) -> bool:
    first = np.ascontiguousarray(first)
    second = np.ascontiguousarray(second)
    return bool(
        first.shape == second.shape
        and first.dtype == second.dtype
        and np.array_equal(first.view(np.uint8), second.view(np.uint8))
    )


def _basic_closed_topology(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    expected_body_count: int = 1,
    base_volume_unit3: float | None = None,
    base_vertices: np.ndarray | None = None,
    expected_face_count: int | None = None,
    maximum_volume_change_relative: float = DEFAULT_MAX_VOLUME_CHANGE_RELATIVE,
) -> dict[str, object]:
    boundary, nonmanifold, winding_mismatches = _edge_topology_counts(faces)
    cross = _face_cross(
        np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.int32)
    )
    degenerate = int(np.count_nonzero(np.linalg.norm(cross, axis=1) <= 1e-14))
    if boundary or nonmanifold or degenerate or winding_mismatches:
        raise SurfaceResolutionError(
            "refined mesh is invalid "
            f"(boundary={boundary}, nonmanifold={nonmanifold}, "
            f"degenerate={degenerate}, winding={winding_mismatches})"
        )
    if expected_face_count is not None and len(faces) != int(expected_face_count):
        raise SurfaceResolutionError(
            f"refined face target mismatch: {len(faces)} != {int(expected_face_count)}"
        )

    original_prefix_unchanged = True
    original_vertex_count = 0
    if base_vertices is not None:
        base_vertices = np.asarray(base_vertices, dtype=np.float64)
        original_vertex_count = int(len(base_vertices))
        original_prefix_unchanged = len(vertices) >= original_vertex_count and _byte_identical(
            np.asarray(vertices, dtype=np.float64)[:original_vertex_count], base_vertices
        )
        if not original_prefix_unchanged:
            raise SurfaceResolutionError(
                "validated base vertex prefix changed during refinement"
            )

    volume = _signed_volume(vertices, faces)
    if not math.isfinite(volume) or volume <= 0.0:
        raise SurfaceResolutionError(
            f"refined mesh does not have positive volume: {volume}"
        )
    volume_change = 0.0
    if base_volume_unit3 is not None:
        base_volume = float(base_volume_unit3)
        if not math.isfinite(base_volume) or base_volume <= 0.0:
            raise SurfaceResolutionError(
                f"validated base has invalid volume: {base_volume}"
            )
        volume_change = abs(volume - base_volume) / max(abs(base_volume), 1e-15)
        if volume_change > float(maximum_volume_change_relative):
            raise SurfaceResolutionError(
                "projected refinement changes volume too much: "
                f"{volume_change:.3%} > {float(maximum_volume_change_relative):.3%}"
            )

    return {
        "watertight": True,
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "degenerate_faces": degenerate,
        "edge_winding_mismatches": winding_mismatches,
        "body_count": int(expected_body_count),
        "body_count_basis": "one connected strict-validated base plus edge-conforming subdivision",
        "original_vertex_count": original_vertex_count,
        "original_vertices_prefix_bitwise_unchanged": bool(original_prefix_unchanged),
        "face_target_exact": expected_face_count is None
        or len(faces) == int(expected_face_count),
        "positive_volume": True,
        "volume_unit3": float(volume),
        "base_volume_unit3": (
            float(base_volume_unit3) if base_volume_unit3 is not None else None
        ),
        "volume_change_relative": float(volume_change),
        "self_intersection_basis": "r7_base_strict_validation_plus_locked-interface conforming subdivision; legacy coplanar-child detector intentionally not rerun",
    }


def _allocate_even_targets(
    base_counts: np.ndarray, source_counts: np.ndarray, requested_total: int
) -> tuple[np.ndarray, int]:
    base_counts = np.asarray(base_counts, dtype=np.int64)
    source_counts = np.asarray(source_counts, dtype=np.int64)
    minimum_total = int(base_counts.sum())
    effective_total = max(int(requested_total), minimum_total)
    if effective_total % 2:
        effective_total += 1
    remaining_pairs = (effective_total - minimum_total) // 2
    if remaining_pairs <= 0:
        return base_counts.copy(), effective_total
    weights = np.maximum(source_counts.astype(np.float64), 1.0)
    raw_pairs = remaining_pairs * weights / float(weights.sum())
    pair_counts = np.floor(raw_pairs).astype(np.int64)
    left = int(remaining_pairs - pair_counts.sum())
    if left:
        fractions = raw_pairs - pair_counts
        winners = np.argpartition(fractions, len(fractions) - left)[-left:]
        pair_counts[winners] += 1
    targets = base_counts + pair_counts * 2
    if int(targets.sum()) != effective_total or bool(np.any(targets < base_counts)):
        raise AssertionError((targets, effective_total))
    return targets, effective_total


def refine_solidified_parts(
    source_meshes: Sequence[Sequence[np.ndarray]],
    solidified_meshes: Sequence[Sequence[np.ndarray]],
    *,
    height_mm: float,
    target_total: int | None = None,
    progress: Callable[..., object] | None = None,
    strict_validator: Callable[
        [np.ndarray, np.ndarray, int], tuple[np.ndarray, dict[str, object]]
    ]
    | None = None,
    maximum_target_faces: int = DEFAULT_MAX_TARGET_FACES,
    maximum_projection_mm: float = DEFAULT_PROJECTION_LIMIT_MM,
    maximum_volume_change_relative: float = DEFAULT_MAX_VOLUME_CHANGE_RELATIVE,
    projection_enabled: bool = True,
    maximum_rounds: int = 8,
) -> tuple[list[tuple[np.ndarray, np.ndarray, np.ndarray]], dict[str, object]]:
    """Refine a verified multi-solid result without changing its interfaces."""
    sources = [
        _mesh_tuple(mesh, f"source part {i}") for i, mesh in enumerate(source_meshes)
    ]
    solids = [
        _mesh_tuple(mesh, f"solid part {i}")
        for i, mesh in enumerate(solidified_meshes)
    ]
    if len(sources) != len(solids) or len(solids) < 2:
        raise SurfaceResolutionError("source/output part counts do not match")
    height_mm = float(height_mm)
    if not math.isfinite(height_mm) or height_mm <= 0.0:
        raise SurfaceResolutionError("invalid model height")
    if target_total is None:
        target_total = int(sum(len(mesh[1]) for mesh in sources))
    if int(target_total) > int(maximum_target_faces):
        raise SurfaceResolutionError(
            f"requested {int(target_total):,} faces exceeds the safety cap "
            f"{int(maximum_target_faces):,}"
        )

    _emit(
        progress,
        0.89,
        "蜈ｱ譛画磁蜷磯擇繧貞崋螳壹＠縺ｦ譛邨り｡ｨ髱｢隗｣蜒丞ｺｦ繧呈ｺ門ｙ縺励※縺・∪縺・",
    )
    interfaces = detect_shared_interfaces(solids)
    base_counts = np.asarray([len(mesh[1]) for mesh in solids], dtype=np.int64)
    source_counts = np.asarray([len(mesh[1]) for mesh in sources], dtype=np.int64)
    targets, effective_total = _allocate_even_targets(
        base_counts, source_counts, int(target_total)
    )
    if int(targets.sum()) > int(maximum_target_faces):
        raise SurfaceResolutionError("safe minimum mesh exceeds the configured face cap")
    maximum_distance_unit = float(maximum_projection_mm) / height_mm
    validation_volume_limit = (
        float(maximum_volume_change_relative)
        if projection_enabled
        else min(
            float(maximum_volume_change_relative),
            DEFAULT_LINEAR_MAX_VOLUME_CHANGE_RELATIVE,
        )
    )

    refined: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    final_masks: list[np.ndarray] = []
    part_records: list[dict[str, object]] = []
    for part_id, (source, solid, interface_mask, target) in enumerate(
        zip(sources, solids, interfaces.masks, targets, strict=True)
    ):
        vertices, faces, _old_colors = solid
        base_vertices = np.asarray(vertices, dtype=np.float64).copy()
        base_body_count = _mesh_body_count(faces, len(vertices))
        if base_body_count != 1:
            raise SurfaceResolutionError(
                f"validated base part {part_id} has {base_body_count} disconnected bodies"
            )
        base_volume = _signed_volume(vertices, faces)
        if not math.isfinite(base_volume) or base_volume <= 0.0:
            raise SurfaceResolutionError(
                f"validated base part {part_id} does not have positive volume"
            )
        projector = _SourceProjector(*source)
        rounds: list[dict[str, object]] = []
        if int(target) > len(faces):
            existing_record: dict[str, object] = {
                "movable": 0,
                "accepted": 0,
                "line_search": 0.0,
                "skipped": "validated_topology_anchor",
            }
            for round_index in range(int(maximum_rounds)):
                remaining = int(target) - len(faces)
                if remaining <= 0:
                    break
                if remaining % 2:
                    raise SurfaceResolutionError(
                        "closed surface target has impossible parity"
                    )
                _unique, _inverse, counts, _edge_locked, eligible = _edge_table(
                    faces, interface_mask
                )
                if bool(np.any(counts != 2)):
                    raise SurfaceResolutionError(
                        "solid lost manifold topology before refinement"
                    )
                available = int(np.count_nonzero(eligible))
                split_count = min(remaining // 2, available)
                if split_count <= 0:
                    raise SurfaceResolutionError(
                        f"part {part_id} cannot reach its target safely"
                    )
                provenance_context = _FACE_PROVENANCE_PROPAGATION_CONTEXT.get()
                if provenance_context is not None:
                    provenance_context["part_id"] = int(part_id)
                vertices, faces, interface_mask, round_record = _split_edges_once(
                    vertices,
                    faces,
                    interface_mask,
                    split_count,
                    projector,
                    maximum_distance_unit,
                    projection_enabled=bool(projection_enabled),
                )
                round_record["round"] = int(round_index + 1)
                rounds.append(round_record)
                fraction = 0.9 + 0.07 * (
                    (
                        part_id
                        + min(1.0, len(faces) / max(1, int(target)))
                    )
                    / len(solids)
                )
                _emit(
                    progress,
                    fraction,
                    f"螟冶｡ｨ髱｢隗｣蜒丞ｺｦ {part_id + 1}/{len(solids)}: "
                    f"{len(faces):,}/{int(target):,}髱｢",
                )
            else:
                raise SurfaceResolutionError(
                    f"part {part_id} exceeded the refinement round cap"
                )
            if len(faces) != int(target):
                raise SurfaceResolutionError(
                    f"part {part_id} target mismatch: {len(faces)} != {int(target)}"
                )
        else:
            existing_record = {"movable": 0, "accepted": 0, "line_search": 0.0}

        validation = _basic_closed_topology(
            vertices,
            faces,
            expected_body_count=base_body_count,
            base_volume_unit3=base_volume,
            base_vertices=base_vertices,
            expected_face_count=int(target),
            maximum_volume_change_relative=validation_volume_limit,
        )
        if strict_validator is not None:
            validated_faces, strict_record = strict_validator(
                vertices, faces, part_id=int(part_id)
            )
            validated_faces = np.asarray(validated_faces, dtype=np.int32)
            if not _byte_identical(
                validated_faces, np.asarray(faces, dtype=np.int32)
            ):
                raise SurfaceResolutionError(
                    "optional strict validation changed refined faces"
                )
            validation = dict(validation)
            validation["optional_strict_validation"] = dict(strict_record)
        colors, color_record = projector.transfer_colors(vertices)
        refined.append((vertices, faces, colors))
        final_masks.append(np.asarray(interface_mask, dtype=bool))
        part_records.append(
            {
                "part_id": int(part_id),
                "source_faces": int(source_counts[part_id]),
                "before_faces": int(base_counts[part_id]),
                "target_faces": int(target),
                "after_faces": int(len(faces)),
                "interface_faces_locked": int(np.count_nonzero(interface_mask)),
                "existing_vertex_projection": existing_record,
                "rounds": rounds,
                "color_transfer": color_record,
                "validation": validation,
            }
        )

    final_signature = _interface_signature(
        refined, final_masks, interfaces.tolerance_unit
    )
    if final_signature != interfaces.signature:
        raise SurfaceResolutionError(
            "shared interface geometry changed during refinement"
        )
    final_byte_signature = _interface_byte_signature(refined, final_masks)
    if final_byte_signature != interfaces.byte_signature:
        raise SurfaceResolutionError(
            "shared interface bytes or winding changed during refinement"
        )
    if int(sum(len(mesh[1]) for mesh in refined)) != effective_total:
        raise SurfaceResolutionError("final global face budget mismatch")
    _emit(
        progress,
        0.98,
        f"譛邨り｡ｨ髱｢繧・{effective_total:,} 髱｢縺ｧ螳牙・縺ｫ遒ｺ螳壹＠縺ｾ縺励◆",
    )
    return refined, {
        "applied": bool(effective_total > int(base_counts.sum())),
        "method": (
            "locked_interface_conforming_projection"
            if projection_enabled
            else "locked_interface_conforming_linear_subdivision"
        ),
        "projection_enabled": bool(projection_enabled),
        "requested_faces": int(target_total),
        "effective_target_faces": int(effective_total),
        "before_faces": int(base_counts.sum()),
        "after_faces": int(sum(len(mesh[1]) for mesh in refined)),
        "shared_interface_face_keys": int(interfaces.shared_face_keys),
        "shared_interface_pair_counts": interfaces.pair_face_counts,
        "interface_tolerance_unit": float(interfaces.tolerance_unit),
        "projection_limit_mm": float(maximum_projection_mm),
        "maximum_volume_change_relative": float(validation_volume_limit),
        "maximum_target_faces": int(maximum_target_faces),
        "parts": part_records,
        "interfaces_unchanged": True,
        "interfaces_bitwise_unchanged": True,
    }


def _make_fixed_solidifier(
    original: Callable[..., object], volume_module: object, assembly_module: object
):
    @functools.wraps(original)
    def fixed(meshes, seams, height_mm, progress=None):
        outputs, record = original(
            meshes, seams, height_mm=height_mm, progress=progress
        )
        base_outputs = [
            tuple(np.asarray(value).copy() for value in mesh) for mesh in outputs
        ]
        updated_record = dict(record)
        if isinstance(updated_record.get("parts"), list):
            updated_record["parts"] = [
                dict(part) if isinstance(part, dict) else part
                for part in updated_record["parts"]
            ]

        provenance_context = None
        provenance_token = None
        provenance_diagnostic: dict[str, object]
        try:
            from spectrum_mapper.generated_surface_color import (
                derive_part_face_provenance,
            )

            base_provenance, provenance_diagnostic = derive_part_face_provenance(
                [len(mesh[1]) for mesh in base_outputs],
                [updated_record],
                topology_changed=False,
            )
            if base_provenance is not None:
                provenance_context = {
                    "parts": [np.asarray(value).copy() for value in base_provenance],
                    "part_id": -1,
                }
                provenance_token = _FACE_PROVENANCE_PROPAGATION_CONTEXT.set(
                    provenance_context
                )
        except Exception as exc:
            provenance_diagnostic = {
                "status": "unavailable",
                "reason": "surface_provenance_initialization_failed",
                "detail": str(exc),
            }
        try:
            refined, resolution_record = refine_solidified_parts(
                meshes,
                outputs,
                height_mm=float(height_mm),
                target_total=int(sum(len(np.asarray(mesh[1])) for mesh in meshes)),
                progress=progress,
                strict_validator=None,
                projection_enabled=False,
            )
        except Exception as exc:
            base_face_count = int(sum(len(mesh[1]) for mesh in base_outputs))
            resolution_record = {
                "applied": False,
                "method": "locked_interface_conforming_linear_subdivision",
                "projection_enabled": False,
                "rolled_back": True,
                "reason": str(exc),
                "before_faces": base_face_count,
                "after_faces": base_face_count,
            }
            _emit(
                progress,
                0.98,
                f"螟冶｡ｨ髱｢縺ｮ鬮倩ｧ｣蜒丞ｺｦ蛹悶ｒ螳牙・縺ｫ謌ｻ縺励∪縺励◆: {exc}",
            )
            refined = base_outputs
        finally:
            if provenance_token is not None:
                _FACE_PROVENANCE_PROPAGATION_CONTEXT.reset(provenance_token)

        if (
            provenance_context is not None
            and not bool(resolution_record.get("rolled_back", False))
        ):
            from spectrum_mapper.generated_surface_color import (
                FACE_PROVENANCE_SOURCE,
                encode_face_ranges,
            )

            record_parts = updated_record.get("parts")
            if not isinstance(record_parts, list):
                raise SurfaceResolutionError(
                    "volume record has no part list for propagated provenance"
                )
            parts_by_id = {
                int(part.get("part_id", index)): part
                for index, part in enumerate(record_parts)
                if isinstance(part, dict)
            }
            propagated_parts = provenance_context["parts"]
            for part_id, values in enumerate(propagated_parts):
                part_record = parts_by_id.get(part_id)
                if part_record is None:
                    raise SurfaceResolutionError(
                        f"volume record has no provenance part {part_id}"
                    )
                values = np.asarray(values)
                if values.shape != (len(refined[part_id][1]),):
                    raise SurfaceResolutionError(
                        f"propagated provenance size mismatch for part {part_id}"
                    )
                generated_ids = np.flatnonzero(values != FACE_PROVENANCE_SOURCE)
                part_record["generated_face_ranges"] = encode_face_ranges(
                    generated_ids
                )
            provenance_diagnostic = {
                "status": "fresh",
                "reason": "parent_face_ids_propagated",
                "part_face_counts": [
                    int(len(value)) for value in propagated_parts
                ],
                "generated_faces": int(
                    sum(
                        np.count_nonzero(
                            np.asarray(value) != FACE_PROVENANCE_SOURCE
                        )
                        for value in propagated_parts
                    )
                ),
            }
            resolution_record["face_provenance_propagated"] = True
        else:
            resolution_record["face_provenance_propagated"] = False
        resolution_record["face_provenance"] = provenance_diagnostic
        updated_record["surface_resolution"] = resolution_record
        return refined, updated_record

    fixed._surface_resolution_original = original
    fixed._surface_resolution_hotfix_version = SURFACE_RESOLUTION_HOTFIX_VERSION
    return fixed


def _iter_surface_resolution_records(
    value: object,
) -> Iterable[tuple[dict[str, object], dict[str, object]]]:
    """Yield each surface record together with its strict parent record."""
    pending = [value]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            if "surface_resolution" in current:
                candidate = current.get("surface_resolution")
                if isinstance(candidate, dict):
                    yield candidate, current
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)


def _make_provenance_refresh_prepare_geometry(original: Callable[..., object]):
    @functools.wraps(original)
    def prepare_geometry_r8(*args, **kwargs):
        prepared = original(*args, **kwargs)
        assembly = getattr(prepared, "assembly", None)
        surface_records = [
            record
            for record, _parent in _iter_surface_resolution_records(assembly)
            if record.get("face_provenance_propagated") is True
            and not bool(record.get("rolled_back", False))
        ]
        if not surface_records:
            return prepared
        try:
            from spectrum_mapper.generated_surface_color import (
                install_face_provenance,
            )

            installed = install_face_provenance(
                prepared,
                getattr(prepared.final, "face_provenance"),
                includes_topology_edits=False,
            )
            diagnostic = {
                "status": "fresh",
                "reason": "installed_after_surface_refinement",
                "face_count": int(installed["face_count"]),
                "topology_sha256": str(installed["topology_sha256"]),
            }
        except Exception as exc:
            diagnostic = {
                "status": "unavailable",
                "reason": "surface_provenance_install_failed",
                "detail": str(exc),
            }
        for record in surface_records:
            record["face_provenance_install"] = dict(diagnostic)
        return prepared

    prepare_geometry_r8._surface_resolution_prepare_version = (
        SURFACE_RESOLUTION_HOTFIX_VERSION
    )
    prepare_geometry_r8._surface_resolution_prepare_original = original
    return prepare_geometry_r8


def _verified_linear_part(part: object) -> bool:
    if not isinstance(part, dict):
        return False
    validation = part.get("validation")
    if not isinstance(validation, dict):
        return False
    try:
        exact_target = int(part.get("after_faces", -1)) == int(
            part.get("target_faces", -2)
        ) and bool(validation.get("face_target_exact"))
        topology_safe = (
            int(validation.get("boundary_edges", -1)) == 0
            and int(validation.get("nonmanifold_edges", -1)) == 0
            and int(validation.get("degenerate_faces", -1)) == 0
            and int(validation.get("edge_winding_mismatches", -1)) == 0
            and int(validation.get("body_count", 0)) == 1
            and bool(validation.get("positive_volume"))
        )
        inherited_geometry = bool(
            validation.get("original_vertices_prefix_bitwise_unchanged")
        ) and float(validation.get("volume_change_relative", math.inf)) <= (
            DEFAULT_LINEAR_MAX_VOLUME_CHANGE_RELATIVE
        )
        return bool(exact_target and topology_safe and inherited_geometry)
    except (TypeError, ValueError, OverflowError):
        return False


def _strict_base_validation(validation: object) -> bool:
    if not isinstance(validation, dict):
        return False
    topology = validation.get("topology")
    if not isinstance(topology, dict):
        return False
    try:
        return bool(
            topology.get("watertight") is True
            and int(topology.get("boundary_edges", -1)) == 0
            and int(topology.get("nonmanifold_edges", -1)) == 0
            and int(topology.get("inconsistent_winding_edges", -1)) == 0
            and int(validation.get("body_count", 0)) == 1
            and validation.get("positive_volume") is True
            and int(validation.get("degenerate_faces", -1)) == 0
            and int(validation.get("self_intersections", -1)) == 0
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _verified_linear_record(record: object, parent: object) -> bool:
    if not isinstance(record, dict) or not isinstance(parent, dict):
        return False
    if parent.get("method") != "recursive_volume_partition" or parent.get("closed") is not True:
        return False
    if not _strict_base_validation(parent.get("root_validation")):
        return False
    if record.get("method") != "locked_interface_conforming_linear_subdivision":
        return False
    if record.get("applied") is not True or record.get("projection_enabled") is not False:
        return False
    if bool(record.get("rolled_back", False)):
        return False
    if record.get("interfaces_bitwise_unchanged") is not True:
        return False
    parts = record.get("parts")
    if not isinstance(parts, list) or not parts or not all(
        _verified_linear_part(part) for part in parts
    ):
        return False
    base_parts = parent.get("parts")
    if not isinstance(base_parts, list) or len(base_parts) != len(parts):
        return False
    if not all(
        isinstance(part, dict) and _strict_base_validation(part.get("validation"))
        for part in base_parts
    ):
        return False
    try:
        after_faces = int(record.get("after_faces", -1))
        target_faces = int(record.get("effective_target_faces", -2))
        part_faces = sum(int(part.get("after_faces", -3)) for part in parts)
        before_faces = int(record.get("before_faces", -1))
        output_parts = int(parent.get("output_parts", -1))
        surface_by_id = {int(part.get("part_id", -1)): part for part in parts}
        base_by_id = {int(part.get("part_id", -1)): part for part in base_parts}
    except (TypeError, ValueError, OverflowError):
        return False
    if (
        len(surface_by_id) != len(parts)
        or len(base_by_id) != len(base_parts)
        or set(surface_by_id) != set(base_by_id)
        or output_parts != len(parts)
    ):
        return False
    try:
        base_face_total = sum(int(part.get("after_faces", -1)) for part in base_parts)
        part_alignment = all(
            int(base_by_id[part_id].get("after_faces", -1))
            == int(surface_by_id[part_id].get("before_faces", -2))
            for part_id in surface_by_id
        )
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(
        after_faces > 0
        and after_faces == target_faces == part_faces
        and before_faces == base_face_total
        and part_alignment
    )


def _linear_export_context(prepared: object) -> dict[str, object] | None:
    """Authorize inherited self-intersection status for one exact export."""
    final = getattr(prepared, "final", None)
    faces = getattr(final, "faces", None)
    assembly = getattr(prepared, "assembly", None)
    if faces is None or not isinstance(assembly, dict):
        return None
    if assembly.get("all_parts_watertight") is not True:
        return None
    try:
        final_face_count = int(len(faces))
        face_part_ids = np.asarray(getattr(final, "face_part_ids"), dtype=np.int64)
    except Exception:
        return None
    if face_part_ids.ndim != 1 or len(face_part_ids) != final_face_count:
        return None
    unique_part_ids, layout_counts = np.unique(face_part_ids, return_counts=True)
    observed_layout = {
        int(part_id): int(count)
        for part_id, count in zip(unique_part_ids, layout_counts, strict=True)
    }
    individual = bool(assembly.get("individual_part_export", False))
    source_part_id = None
    search_root = assembly
    if individual:
        try:
            source_part_id = int(assembly["source_part_index"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        search_root = assembly.get("parent_assembly")
        if not isinstance(search_root, dict):
            return None
    records = [
        (record, parent)
        for record, parent in _iter_surface_resolution_records(search_root)
        if _verified_linear_record(record, parent)
    ]
    for record, _parent in records:
        if individual:
            matching = [
                part
                for part in record["parts"]
                if int(part.get("part_id", -1)) == source_part_id
            ]
            if (
                len(matching) != 1
                or int(matching[0].get("after_faces", -1)) != final_face_count
            ):
                continue
            if observed_layout != {0: final_face_count}:
                continue
            expected_part_faces = [final_face_count]
        else:
            if int(record.get("after_faces", -1)) != final_face_count:
                continue
            expected_layout = {
                int(part["part_id"]): int(part["after_faces"])
                for part in record["parts"]
            }
            if observed_layout != expected_layout:
                continue
            expected_part_faces = [
                int(part["after_faces"]) for part in record["parts"]
            ]
        remaining_face_counts = dict(Counter(expected_part_faces))
        return {
            "check": INHERITED_SELF_INTERSECTION_CHECK,
            "faces": final_face_count,
            "individual_part": individual,
            "source_part_id": source_part_id,
            "surface_resolution_version": SURFACE_RESOLUTION_HOTFIX_VERSION,
            "inherited_calls": 0,
            "expected_part_faces": tuple(expected_part_faces),
            "remaining_face_counts": remaining_face_counts,
        }
    return None


def _wrapper_chain_has(function: object, attribute: str, value: object) -> bool:
    seen: set[int] = set()
    current = function
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, attribute, None) == value:
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _install_prepare_provenance_scope(
    engine_module: object,
    gui_module: object | None = None,
) -> dict[str, bool]:
    """Refresh the fail-closed provenance record after r8 topology changes.

    ``gui`` imports ``prepare_geometry`` into its own module namespace, so
    replacing only ``engine.prepare_geometry`` leaves the desktop path on the
    old callable.  Patch both bindings, while preserving either callable's
    existing wrapper chain and refusing to install the same r8 wrapper twice.
    """

    engine_changed = False
    gui_changed = False
    current = getattr(engine_module, "prepare_geometry", None)
    if callable(current):
        if not _wrapper_chain_has(
            current,
            "_surface_resolution_prepare_version",
            SURFACE_RESOLUTION_HOTFIX_VERSION,
        ):
            current = _make_provenance_refresh_prepare_geometry(current)
            engine_changed = True
        setattr(engine_module, "prepare_geometry", current)

    if gui_module is not None:
        gui_current = getattr(gui_module, "prepare_geometry", None)
        if callable(gui_current):
            if not _wrapper_chain_has(
                gui_current,
                "_surface_resolution_prepare_version",
                SURFACE_RESOLUTION_HOTFIX_VERSION,
            ):
                engine_original = getattr(
                    current, "_surface_resolution_prepare_original", None
                )
                if gui_current is engine_original:
                    gui_current = current
                else:
                    gui_current = _make_provenance_refresh_prepare_geometry(
                        gui_current
                    )
                gui_changed = True
            setattr(gui_module, "prepare_geometry", gui_current)

    return {
        "engine_changed": bool(engine_changed),
        "gui_changed": bool(gui_changed),
    }


def _make_scoped_mesh_quality(original: Callable[..., dict[str, object]]):
    @functools.wraps(original)
    def mesh_quality_r8(
        vertices,
        faces,
        *,
        check_self_intersections=False,
        self_intersection_face_id_limit=None,
    ):
        context = _LINEAR_EXPORT_VALIDATION_CONTEXT.get()
        face_count = int(len(faces)) if faces is not None else -1
        remaining = context.get("remaining_face_counts") if context is not None else None
        available = int(remaining.get(face_count, 0)) if isinstance(remaining, dict) else 0
        inherited = bool(
            context is not None and check_self_intersections and available > 0
        )
        quality_kwargs: dict[str, object] = {
            "check_self_intersections": (
                False if inherited else check_self_intersections
            )
        }
        if self_intersection_face_id_limit is not None:
            quality_kwargs["self_intersection_face_id_limit"] = (
                self_intersection_face_id_limit
            )
        result = original(vertices, faces, **quality_kwargs)
        if not inherited:
            return result
        remaining[face_count] = available - 1
        context["inherited_calls"] = int(context.get("inherited_calls", 0)) + 1
        updated = dict(result)
        updated["self_intersecting_faces"] = 0
        updated["self_intersection_check"] = INHERITED_SELF_INTERSECTION_CHECK
        return updated

    mesh_quality_r8._surface_resolution_quality_version = (
        SURFACE_RESOLUTION_HOTFIX_VERSION
    )
    mesh_quality_r8._surface_resolution_quality_original = original
    return mesh_quality_r8


def _make_scoped_3mf_writer(original: Callable[..., object]):
    @functools.wraps(original)
    def write_3mf_atomic_r8(
        destination,
        prepared,
        colors,
        height_mm,
        palette,
        part_palettes=None,
        print_uses_global_palette=False,
        *,
        export_validation_level="high",
    ):
        validation_kwargs = (
            {} if export_validation_level == "high"
            else {"export_validation_level": export_validation_level}
        )
        # Inherited strict SI proof is only an optimization of the high path.
        # Relaxed policies report their own unchecked SI status in the core.
        context = (
            _linear_export_context(prepared)
            if export_validation_level == "high" else None
        )
        if context is None:
            return original(
                destination,
                prepared,
                colors,
                height_mm,
                palette,
                part_palettes,
                print_uses_global_palette,
                **validation_kwargs,
            )
        token = _LINEAR_EXPORT_VALIDATION_CONTEXT.set(context)
        try:
            validation = original(
                destination,
                prepared,
                colors,
                height_mm,
                palette,
                part_palettes,
                print_uses_global_palette,
                **validation_kwargs,
            )
        finally:
            _LINEAR_EXPORT_VALIDATION_CONTEXT.reset(token)
        remaining = context.get("remaining_face_counts")
        expected = context.get("expected_part_faces")
        complete = bool(
            isinstance(remaining, dict)
            and isinstance(expected, tuple)
            and int(context.get("inherited_calls", 0)) == len(expected)
            and all(int(value) == 0 for value in remaining.values())
        )
        if isinstance(validation, dict) and complete:
            validation["self_intersection_check"] = INHERITED_SELF_INTERSECTION_CHECK
            validation["inherited_self_intersection_parts"] = int(
                context["inherited_calls"]
            )
        return validation

    write_3mf_atomic_r8._surface_resolution_writer_version = (
        SURFACE_RESOLUTION_HOTFIX_VERSION
    )
    write_3mf_atomic_r8._surface_resolution_writer_original = original
    return write_3mf_atomic_r8


def _install_export_validation_scope(
    engine_module: object, workflow_module: object
) -> dict[str, bool]:
    quality_changed = False
    writer_changed = False
    current_quality = getattr(engine_module, "mesh_quality", None)
    if callable(current_quality):
        if not _wrapper_chain_has(
            current_quality,
            "_surface_resolution_quality_version",
            SURFACE_RESOLUTION_HOTFIX_VERSION,
        ):
            current_quality = _make_scoped_mesh_quality(current_quality)
            quality_changed = True
        setattr(engine_module, "mesh_quality", current_quality)
        setattr(workflow_module, "mesh_quality", current_quality)
    current_writer = getattr(workflow_module, "write_3mf_atomic", None)
    if not callable(current_writer):
        current_writer = getattr(engine_module, "write_3mf_atomic", None)
    if callable(current_writer):
        if not _wrapper_chain_has(
            current_writer,
            "_surface_resolution_writer_version",
            SURFACE_RESOLUTION_HOTFIX_VERSION,
        ):
            current_writer = _make_scoped_3mf_writer(current_writer)
            writer_changed = True
        setattr(engine_module, "write_3mf_atomic", current_writer)
        setattr(workflow_module, "write_3mf_atomic", current_writer)
    return {
        "quality_changed": bool(quality_changed),
        "writer_changed": bool(writer_changed),
    }


def apply_surface_resolution_hotfix(
    volume_partition_module: object | None = None,
    engine_module: object | None = None,
    assembly_module: object | None = None,
    workflow_module: object | None = None,
) -> dict[str, object]:
    """Install the curved-solid surface-resolution patch exactly once."""
    engine_was_explicit = engine_module is not None
    gui_module = None
    if volume_partition_module is None:
        from spectrum_mapper import volume_partition as volume_partition_module
    if engine_module is None:
        from spectrum_mapper import engine as engine_module
    if assembly_module is None:
        from spectrum_mapper import assembly as assembly_module
    if workflow_module is None:
        if engine_was_explicit:
            workflow_module = engine_module
        else:
            from spectrum_mapper import workflow as workflow_module
    if not engine_was_explicit:
        try:
            from spectrum_mapper import gui as gui_module
        except ImportError:
            # Headless/CLI distributions need only the engine binding.
            gui_module = None

    current = getattr(volume_partition_module, "solidify_complex_partitions")
    if (
        getattr(current, "_surface_resolution_hotfix_version", None)
        == SURFACE_RESOLUTION_HOTFIX_VERSION
    ):
        fixed = current
        changed = False
    else:
        fixed = _make_fixed_solidifier(
            current, volume_partition_module, assembly_module
        )
        setattr(volume_partition_module, "solidify_complex_partitions", fixed)
        changed = True
    setattr(engine_module, "solidify_complex_partitions", fixed)
    export_scope = _install_export_validation_scope(engine_module, workflow_module)
    provenance_prepare_scope = _install_prepare_provenance_scope(
        engine_module, gui_module
    )
    return {
        "version": SURFACE_RESOLUTION_HOTFIX_VERSION,
        "installed": True,
        "changed": bool(changed),
        "export_validation_scope": export_scope,
        "provenance_prepare_scope": provenance_prepare_scope,
        "self_intersection_check": INHERITED_SELF_INTERSECTION_CHECK,
        "maximum_target_faces": int(DEFAULT_MAX_TARGET_FACES),
    }


install_surface_resolution_hotfix = apply_surface_resolution_hotfix

__all__ = [
    "DEFAULT_MAX_TARGET_FACES",
    "INHERITED_SELF_INTERSECTION_CHECK",
    "SURFACE_RESOLUTION_HOTFIX_VERSION",
    "SurfaceResolutionError",
    "apply_surface_resolution_hotfix",
    "install_surface_resolution_hotfix",
    "detect_shared_interfaces",
    "refine_solidified_parts",
]
