"""Fail-closed physical radial shell/core geometry for the r20 laboratory.

The production colour exporter represents mixed colours as virtual tools.  A
radial experiment instead turns one eligible black-containing surface recipe
into two *physical* material regions: a partner-colour skin which preserves
the complete source exterior, and an enclosed pure-black core.  Both regions
are exported as normal parts of one PrintObject by :mod:`radial_export`.

The first implementation deliberately supports only one closed source body
whose complete exterior has one recipe signature.  The public surface-analysis
API already represents multiple state/partner assignments so a later owner-
propagation partitioner can extend the feature without changing callers.  No
unsupported case is silently approximated or sent back to the Ratio/Cycle
path; it raises :class:`RadialShellError` instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from typing import Mapping

import numpy as np
import pymeshlab as ml
import trimesh

from .assembly import _edge_topology
from .models import MeshLevel
from .volume_partition import (
    VolumePartitionError,
    _exact_tetrahedralize,
    _extract_binary_surface,
    _mesh_volume,
    _tetra_volumes,
)


RADIAL_SHELL_SCHEMA = "tripo-spectrum-mapper.radial-shell.geometry.v1"
DEFAULT_SKIN_THICKNESS_MM = 0.15
_OUTER_MARKER = 0
_INTERFACE_MARKER = -1_000_001
_AREA_EPSILON = 1e-14
_VOLUME_RELATIVE_TOLERANCE = 1e-8


class RadialShellError(RuntimeError):
    """Stable, diagnostic error for a rejected radial-shell operation."""

    def __init__(
        self,
        code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class RadialSurfaceAssignment:
    """One eligible exterior state and its future inward-owner identity."""

    state_id: int
    partner_extruder: int
    face_count: int
    area_mm2: float
    area_fraction: float


@dataclass(frozen=True, slots=True)
class RadialSurfaceAnalysis:
    """Pure multi-state eligibility analysis used by Stage A and Stage B."""

    assignments: tuple[RadialSurfaceAssignment, ...]
    eligible_face_count: int
    total_face_count: int
    eligible_area_mm2: float
    total_area_mm2: float
    eligible_area_fraction: float
    unassigned_state_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RadialExportPart:
    """One disjoint physical material region in millimetres."""

    name: str
    vertices_mm: np.ndarray
    faces: np.ndarray
    extruder: int
    role: str
    # Legacy serializer handshake: this asserts a closed physical volume.  It
    # does not choose the slicer's sparse-infill density.
    solid_infill: bool = True
    source_state: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def physical_filament(self) -> int:
        """Compatibility alias for the dedicated radial serializer."""

        return self.extruder

    @property
    def source_state_id(self) -> int | None:
        return self.source_state


@dataclass(frozen=True, slots=True)
class RadialShellResult:
    """Validated, exact-touch physical shell/core partition."""

    parts: tuple[RadialExportPart, ...]
    skin_thickness_mm: float
    partner_extruder: int
    black_extruder: int
    eligible_state_id: int
    eligible_area_fraction: float
    source_fingerprint: str
    source_volume_mm3: float
    output_volume_mm3: float
    interfaces: tuple[Mapping[str, object], ...]
    metadata: Mapping[str, object]

    @property
    def darkest_filament(self) -> int:
        """Compatibility name retained for early serializer prototypes."""

        return self.black_extruder

    @property
    def diagnostics(self) -> Mapping[str, object]:
        value = self.metadata.get("diagnostics", {})
        return value if isinstance(value, Mapping) else {}


def _raise(code: str, **details: object) -> None:
    raise RadialShellError(code, details)


def _immutable_array(values: np.ndarray, dtype: np.dtype) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype).copy()
    result.flags.writeable = False
    return result


def _triangle_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    triangles = vertices[faces]
    return 0.5 * np.linalg.norm(
        np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        ),
        axis=1,
    )


def _signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    triangles = vertices[faces]
    return float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )


def _coordinate_triangle_keys(
    vertices: np.ndarray, faces: np.ndarray
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    keys = [
        tuple(sorted(tuple(map(float, vertices[index])) for index in face))
        for face in faces
    ]
    return tuple(sorted(keys))


def _oriented_coordinate_triangle_keys(
    vertices: np.ndarray, faces: np.ndarray
) -> dict[tuple[tuple[float, float, float], ...], int]:
    """Return canonical triangle keys with parity relative to sorted order."""

    result: dict[tuple[tuple[float, float, float], ...], int] = {}
    for face in faces:
        points = [tuple(map(float, vertices[index])) for index in face]
        sorted_points = sorted(points)
        permutation = [sorted_points.index(point) for point in points]
        inversions = sum(
            permutation[first] > permutation[second]
            for first in range(3)
            for second in range(first + 1, 3)
        )
        key = tuple(sorted_points)
        result[key] = -1 if inversions % 2 else 1
    return result


def _duplicate_coordinate_triangles(
    vertices: np.ndarray, faces: np.ndarray
) -> int:
    keys = _coordinate_triangle_keys(vertices, faces)
    return int(len(keys) - len(set(keys)))


def _self_intersection_count(
    vertices: np.ndarray, faces: np.ndarray, *, label: str
) -> int:
    mesh_set = ml.MeshSet()
    mesh_set.add_mesh(
        ml.Mesh(vertex_matrix=vertices, face_matrix=faces), label
    )
    try:
        mesh_set.apply_filter(
            "compute_selection_by_self_intersections_per_face"
        )
    except Exception as exc:  # pragma: no cover - plugin failure is external
        _raise("self_intersection_check_failed", part=label, error=str(exc))
    return int(mesh_set.current_mesh().selected_face_number())


def _mesh_record(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    label: str,
    expected_surface_components: int,
) -> dict[str, object]:
    topology = _edge_topology(faces, len(vertices))
    if (
        not bool(topology["watertight"])
        or int(topology["inconsistent_winding_edges"])
    ):
        _raise("output_not_closed_oriented", part=label, topology=topology)
    areas = _triangle_areas(vertices, faces)
    degenerate = int(
        np.count_nonzero(~np.isfinite(areas) | (areas <= _AREA_EPSILON))
    )
    duplicates = _duplicate_coordinate_triangles(vertices, faces)
    if degenerate or duplicates:
        _raise(
            "output_invalid_triangles",
            part=label,
            degenerate_faces=degenerate,
            duplicate_coordinate_triangles=duplicates,
        )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    surface_components = int(
        len(mesh.split(only_watertight=False)) if len(faces) else 0
    )
    volume = _signed_volume(vertices, faces)
    if (
        not mesh.is_watertight
        or not mesh.is_winding_consistent
        or not mesh.is_volume
        or not math.isfinite(volume)
        or volume <= _AREA_EPSILON
        or surface_components != int(expected_surface_components)
    ):
        _raise(
            "output_not_positive_volume",
            part=label,
            signed_volume_mm3=volume,
            surface_components=surface_components,
            expected_surface_components=int(expected_surface_components),
        )
    self_intersections = _self_intersection_count(
        vertices, faces, label=label
    )
    if self_intersections:
        _raise(
            "output_self_intersection",
            part=label,
            self_intersecting_faces=self_intersections,
        )
    return {
        "vertices": int(len(vertices)),
        "faces": int(len(faces)),
        "topology": topology,
        "surface_components": surface_components,
        "signed_volume_mm3": volume,
        "degenerate_faces": 0,
        "duplicate_coordinate_triangles": 0,
        "self_intersecting_faces": 0,
    }


def _validate_mesh_inputs(
    vertices_mm: np.ndarray,
    faces: np.ndarray,
    face_part_ids: np.ndarray | None,
    face_state_ids: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    vertices = np.asarray(vertices_mm, dtype=np.float64)
    raw_faces = np.asarray(faces)
    if vertices.ndim != 2 or vertices.shape[1:] != (3,) or len(vertices) < 4:
        _raise("invalid_vertices", shape=tuple(vertices.shape))
    if not np.isfinite(vertices).all():
        _raise("nonfinite_vertices")
    if (
        raw_faces.ndim != 2
        or raw_faces.shape[1:] != (3,)
        or len(raw_faces) < 4
    ):
        _raise("invalid_faces", shape=tuple(raw_faces.shape))
    if not np.issubdtype(raw_faces.dtype, np.integer):
        rounded = np.rint(raw_faces)
        if not np.array_equal(raw_faces, rounded):
            _raise("noninteger_faces")
        raw_faces = rounded
    checked_faces = np.asarray(raw_faces, dtype=np.int64)
    if int(checked_faces.min()) < 0 or int(checked_faces.max()) >= len(vertices):
        _raise(
            "face_index_out_of_range",
            minimum=int(checked_faces.min()),
            maximum=int(checked_faces.max()),
            vertex_count=int(len(vertices)),
        )
    if np.any(
        (checked_faces[:, 0] == checked_faces[:, 1])
        | (checked_faces[:, 1] == checked_faces[:, 2])
        | (checked_faces[:, 2] == checked_faces[:, 0])
    ):
        _raise("repeated_face_index")
    checked_faces = checked_faces.astype(np.int32)
    areas = _triangle_areas(vertices, checked_faces)
    if np.any(~np.isfinite(areas) | (areas <= _AREA_EPSILON)):
        _raise("degenerate_input_faces")
    if _duplicate_coordinate_triangles(vertices, checked_faces):
        _raise("duplicate_input_triangles")

    states_raw = np.asarray(face_state_ids)
    if states_raw.shape != (len(checked_faces),):
        _raise(
            "face_state_shape_mismatch",
            expected=int(len(checked_faces)),
            actual=tuple(states_raw.shape),
        )
    if not np.issubdtype(states_raw.dtype, np.integer):
        _raise("noninteger_face_states")
    states = np.asarray(states_raw, dtype=np.int32)
    if np.any(states < 0):
        _raise("negative_face_state")

    if face_part_ids is None or np.asarray(face_part_ids).size == 0:
        parts = np.zeros(len(checked_faces), dtype=np.int16)
    else:
        parts_raw = np.asarray(face_part_ids)
        if parts_raw.shape != (len(checked_faces),):
            _raise(
                "face_part_shape_mismatch",
                expected=int(len(checked_faces)),
                actual=tuple(parts_raw.shape),
            )
        if not np.issubdtype(parts_raw.dtype, np.integer):
            _raise("noninteger_face_parts")
        parts = np.asarray(parts_raw, dtype=np.int16)
    unique_parts = np.unique(parts)
    if len(unique_parts) != 1:
        _raise(
            "single_part_required",
            part_ids=[int(value) for value in unique_parts],
        )
    topology = _edge_topology(checked_faces, len(vertices))
    source = trimesh.Trimesh(
        vertices=vertices, faces=checked_faces, process=False
    )
    surface_components = int(len(source.split(only_watertight=False)))
    source_volume = _signed_volume(vertices, checked_faces)
    if (
        not bool(topology["watertight"])
        or int(topology["inconsistent_winding_edges"])
        or not source.is_watertight
        or not source.is_winding_consistent
        or not source.is_volume
        or surface_components != 1
        or not math.isfinite(source_volume)
        or source_volume <= _AREA_EPSILON
    ):
        _raise(
            "closed_positive_single_body_required",
            topology=topology,
            surface_components=surface_components,
            signed_volume_mm3=source_volume,
        )
    intersections = _self_intersection_count(
        vertices, checked_faces, label="radial source"
    )
    if intersections:
        _raise(
            "input_self_intersection",
            self_intersecting_faces=intersections,
        )
    return vertices.copy(), checked_faces.copy(), parts.copy(), states.copy()


def analyze_radial_surface_assignments(
    vertices_mm: np.ndarray,
    faces: np.ndarray,
    face_state_ids: np.ndarray,
    eligible_state_partners: Mapping[int, int],
) -> RadialSurfaceAnalysis:
    """Analyze eligible area without imposing the MVP's single-state limit.

    This is the stable Stage-B extension point.  A future volumetric owner
    propagation implementation can consume every returned assignment, whereas
    :func:`build_radial_shell` currently requires exactly one assignment and
    full exterior coverage.
    """

    vertices = np.asarray(vertices_mm, dtype=np.float64)
    checked_faces = np.asarray(faces, dtype=np.int32)
    states = np.asarray(face_state_ids)
    if vertices.ndim != 2 or vertices.shape[1:] != (3,):
        _raise("invalid_vertices", shape=tuple(vertices.shape))
    if checked_faces.ndim != 2 or checked_faces.shape[1:] != (3,):
        _raise("invalid_faces", shape=tuple(checked_faces.shape))
    if states.shape != (len(checked_faces),):
        _raise("face_state_shape_mismatch")
    if not np.issubdtype(states.dtype, np.integer):
        _raise("noninteger_face_states")
    if len(checked_faces) and (
        int(checked_faces.min()) < 0
        or int(checked_faces.max()) >= len(vertices)
    ):
        _raise("face_index_out_of_range")
    partners: dict[int, int] = {}
    for raw_state, raw_partner in eligible_state_partners.items():
        if isinstance(raw_state, bool) or isinstance(raw_partner, bool):
            _raise("invalid_state_partner_mapping")
        state = int(raw_state)
        partner = int(raw_partner)
        if state < 0 or not 1 <= partner <= 4:
            _raise(
                "invalid_state_partner_mapping",
                state_id=state,
                partner_extruder=partner,
            )
        partners[state] = partner
    areas = _triangle_areas(vertices, checked_faces)
    total_area = float(areas.sum())
    if not math.isfinite(total_area) or total_area <= _AREA_EPSILON:
        _raise("invalid_surface_area", total_area_mm2=total_area)
    state_values = np.asarray(states, dtype=np.int32)
    assignments: list[RadialSurfaceAssignment] = []
    eligible = np.zeros(len(checked_faces), dtype=bool)
    for state in sorted(partners):
        selected = state_values == state
        if not np.any(selected):
            continue
        eligible |= selected
        area = float(areas[selected].sum())
        assignments.append(
            RadialSurfaceAssignment(
                state_id=state,
                partner_extruder=partners[state],
                face_count=int(np.count_nonzero(selected)),
                area_mm2=area,
                area_fraction=area / total_area,
            )
        )
    eligible_area = float(areas[eligible].sum())
    unassigned = tuple(
        int(value)
        for value in np.unique(state_values[~eligible])
    )
    return RadialSurfaceAnalysis(
        assignments=tuple(assignments),
        eligible_face_count=int(np.count_nonzero(eligible)),
        total_face_count=int(len(checked_faces)),
        eligible_area_mm2=eligible_area,
        total_area_mm2=total_area,
        eligible_area_fraction=eligible_area / total_area,
        unassigned_state_ids=unassigned,
    )


def _closest_distances(
    mesh: trimesh.Trimesh, query: np.ndarray
) -> np.ndarray:
    values: list[np.ndarray] = []
    for start in range(0, len(query), 20_000):
        _closest, distance, _triangle_ids = trimesh.proximity.closest_point(
            mesh, query[start : start + 20_000]
        )
        values.append(np.asarray(distance, dtype=np.float64))
    return np.concatenate(values) if values else np.empty(0, dtype=np.float64)


def _fingerprint(vertices: np.ndarray, faces: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(vertices, dtype="<f8").tobytes())
    digest.update(np.ascontiguousarray(faces, dtype="<i4").tobytes())
    return digest.hexdigest()


def build_radial_shell(
    vertices_mm: np.ndarray,
    faces: np.ndarray,
    *,
    face_part_ids: np.ndarray | None = None,
    face_provenance: np.ndarray | None = None,
    face_state_ids: np.ndarray,
    eligible_state_partners: Mapping[int, int],
    black_extruder: int,
    skin_thickness_mm: float = DEFAULT_SKIN_THICKNESS_MM,
    minimum_eligible_area_fraction: float = 1.0,
    offset_resolution_mm: float | None = None,
) -> RadialShellResult:
    """Partition one eligible closed body into partner shell and black core.

    ``offset_resolution_mm`` is reserved for the Stage-B adaptive tetrahedral
    field.  Supplying it today fails explicitly rather than implying a quality
    guarantee which the MVP cannot yet provide.
    """

    if isinstance(black_extruder, bool) or not 1 <= int(black_extruder) <= 4:
        _raise("invalid_black_extruder", black_extruder=black_extruder)
    black = int(black_extruder)
    thickness = float(skin_thickness_mm)
    if not math.isfinite(thickness) or thickness <= 0.0:
        _raise("invalid_skin_thickness", skin_thickness_mm=thickness)
    minimum_fraction = float(minimum_eligible_area_fraction)
    if (
        not math.isfinite(minimum_fraction)
        or minimum_fraction <= 0.0
        or minimum_fraction > 1.0
    ):
        _raise(
            "invalid_minimum_eligible_fraction",
            minimum_eligible_area_fraction=minimum_fraction,
        )
    if offset_resolution_mm is not None:
        _raise(
            "offset_resolution_not_supported",
            offset_resolution_mm=float(offset_resolution_mm),
        )

    vertices, checked_faces, _parts, states = _validate_mesh_inputs(
        vertices_mm, faces, face_part_ids, face_state_ids
    )
    if face_provenance is not None and np.asarray(face_provenance).size:
        provenance = np.asarray(face_provenance)
        if provenance.shape != (len(checked_faces),):
            _raise(
                "face_provenance_shape_mismatch",
                expected=int(len(checked_faces)),
                actual=tuple(provenance.shape),
            )
        if not np.issubdtype(provenance.dtype, np.integer):
            _raise("noninteger_face_provenance")
        generated = int(np.count_nonzero(provenance))
        if generated:
            # A generated closure has no original visible colour sample.  The
            # MVP must not silently treat it as user-authored exterior; Stage
            # B will need an explicit cap-owner policy before accepting it.
            _raise(
                "generated_surface_not_supported",
                generated_face_count=generated,
                provenance_values=[
                    int(value) for value in np.unique(provenance[provenance != 0])
                ],
            )
    analysis = analyze_radial_surface_assignments(
        vertices,
        checked_faces,
        states,
        eligible_state_partners,
    )
    if not analysis.assignments:
        _raise(
            "no_eligible_surface",
            unassigned_state_ids=list(analysis.unassigned_state_ids),
        )
    if len(analysis.assignments) != 1:
        _raise(
            "multiple_eligible_states_not_supported",
            assignments=[
                {
                    "state_id": item.state_id,
                    "partner_extruder": item.partner_extruder,
                    "area_fraction": item.area_fraction,
                }
                for item in analysis.assignments
            ],
        )
    assignment = analysis.assignments[0]
    if assignment.partner_extruder == black:
        _raise(
            "partner_equals_black",
            partner_extruder=assignment.partner_extruder,
            black_extruder=black,
        )
    if analysis.eligible_area_fraction + 1e-12 < minimum_fraction:
        _raise(
            "eligible_coverage_too_low",
            eligible_area_fraction=analysis.eligible_area_fraction,
            minimum_eligible_area_fraction=minimum_fraction,
            unassigned_state_ids=list(analysis.unassigned_state_ids),
        )
    # Stage A has no safe side-wall closure for an unassigned patch.  A caller
    # may lower the reporting threshold, but geometry still remains fail-closed
    # until Stage B can propagate surface owners through a shared volume field.
    if analysis.eligible_face_count != analysis.total_face_count:
        _raise(
            "partial_surface_not_supported",
            eligible_area_fraction=analysis.eligible_area_fraction,
            unassigned_state_ids=list(analysis.unassigned_state_ids),
        )

    source_mesh = trimesh.Trimesh(
        vertices=vertices, faces=checked_faces, process=False
    )
    source_volume = _signed_volume(vertices, checked_faces)
    source_fp = _fingerprint(vertices, checked_faces)
    try:
        nodes, tetrahedra, boundary_faces, boundary_markers, tet_record = (
            _exact_tetrahedralize(
                vertices,
                checked_faces,
                np.full(len(checked_faces), _OUTER_MARKER, dtype=np.int32),
                part_count=1,
            )
        )
    except (VolumePartitionError, Exception) as exc:
        if isinstance(exc, RadialShellError):
            raise
        _raise("tetrahedralization_failed", error=str(exc))

    tetra_volume = float(_tetra_volumes(nodes, tetrahedra).sum())
    if (
        not math.isfinite(tetra_volume)
        or abs(tetra_volume - source_volume)
        > _VOLUME_RELATIVE_TOLERANCE * max(source_volume, 1.0)
    ):
        _raise(
            "tetrahedral_volume_drift",
            source_volume_mm3=source_volume,
            tetra_volume_mm3=tetra_volume,
        )
    distances = _closest_distances(source_mesh, nodes)
    # TetGen promises the original vertices first; hard-setting their exact
    # boundary value prevents closest-point roundoff from clipping the source.
    distances[: len(vertices)] = 0.0
    max_distance = float(np.max(distances, initial=0.0))
    if max_distance <= thickness * (1.0 + 1e-12):
        _raise(
            "skin_consumes_core",
            skin_thickness_mm=thickness,
            maximum_interior_distance_mm=max_distance,
        )
    scalar = distances - thickness
    scalar[np.abs(scalar) <= 1e-13] = -1e-13
    try:
        shell_surface, core_surface, interface_record = (
            _extract_binary_surface(
                nodes,
                tetrahedra,
                boundary_faces,
                boundary_markers,
                scalar,
                interface_marker=_INTERFACE_MARKER,
            )
        )
    except (VolumePartitionError, ValueError) as exc:
        _raise("radial_interface_failed", error=str(exc))

    outer_faces = shell_surface.faces[
        shell_surface.markers == _OUTER_MARKER
    ]
    shell_interface = shell_surface.faces[
        shell_surface.markers == _INTERFACE_MARKER
    ]
    core_interface = core_surface.faces[
        core_surface.markers == _INTERFACE_MARKER
    ]
    if len(outer_faces) != len(checked_faces) or len(core_surface.faces) != len(
        core_interface
    ):
        _raise(
            "unexpected_partition_boundaries",
            source_outer_faces=int(len(checked_faces)),
            shell_outer_faces=int(len(outer_faces)),
            core_noninterface_faces=int(
                len(core_surface.faces) - len(core_interface)
            ),
        )
    source_outer_keys = _coordinate_triangle_keys(vertices, checked_faces)
    output_outer_keys = _coordinate_triangle_keys(
        shell_surface.vertices, outer_faces
    )
    if source_outer_keys != output_outer_keys:
        _raise("source_exterior_not_preserved")
    shell_keys = _oriented_coordinate_triangle_keys(
        shell_surface.vertices, shell_interface
    )
    core_keys = _oriented_coordinate_triangle_keys(
        core_surface.vertices, core_interface
    )
    if shell_keys.keys() != core_keys.keys() or any(
        shell_keys[key] != -core_keys[key] for key in shell_keys
    ):
        _raise("shared_interface_mismatch")
    shell_record = _mesh_record(
        shell_surface.vertices,
        shell_surface.faces,
        label="partner outer shell",
        expected_surface_components=2,
    )
    core_record = _mesh_record(
        core_surface.vertices,
        core_surface.faces,
        label="pure black core",
        expected_surface_components=1,
    )
    shell_volume = _mesh_volume(shell_surface)
    core_volume = _mesh_volume(core_surface)
    output_volume = shell_volume + core_volume
    volume_error = abs(output_volume - source_volume)
    if volume_error > _VOLUME_RELATIVE_TOLERANCE * max(source_volume, 1.0):
        _raise(
            "partition_volume_drift",
            source_volume_mm3=source_volume,
            output_volume_mm3=output_volume,
            absolute_error_mm3=volume_error,
        )

    interface_vertices = shell_surface.vertices[np.unique(shell_interface)]
    # The nodal distance field is exact at its zero crossings; a triangle
    # center on that piecewise-planar interface need not itself lie on the
    # Euclidean offset (especially across a sharp box corner).  Report and
    # guard the generated interface vertices here.  Curved/face fidelity can
    # later be tightened by the public ``offset_resolution_mm`` Stage-B mesh.
    interface_distances = _closest_distances(
        source_mesh, interface_vertices
    )
    distance_min = float(np.min(interface_distances))
    distance_max = float(np.max(interface_distances))
    # Piecewise-linear interpolation of the exact nodal distance field is not
    # an exact Euclidean offset between nodes.  The guard is deliberately
    # conservative: it catches a collapsed/coarse field while retaining the
    # measured ~0.161 mm maximum for a 0.15 mm cube MVP.
    fidelity_limit = max(0.02, thickness * 0.20)
    if (
        distance_min < thickness - fidelity_limit
        or distance_max > thickness + fidelity_limit
    ):
        _raise(
            "offset_fidelity_failed",
            requested_mm=thickness,
            measured_min_mm=distance_min,
            measured_max_mm=distance_max,
            tolerance_mm=fidelity_limit,
        )

    shared_interface = {
        "name": "partner_shell__pure_black_core",
        "faces": int(len(shell_interface)),
        "vertices": int(len(np.unique(shell_interface))),
        "exact_coordinate_triangles": True,
        "opposite_winding": True,
        "gap_mm": 0.0,
        "positive_overlap_mm3": 0.0,
        "requested_depth_mm": thickness,
        "sampled_depth_min_mm": distance_min,
        "sampled_depth_max_mm": distance_max,
    }
    black_part = RadialExportPart(
        name="Radial pure black core",
        vertices_mm=_immutable_array(core_surface.vertices, np.float64),
        faces=_immutable_array(core_surface.faces, np.int32),
        extruder=black,
        role="pure_black_core",
        solid_infill=True,
        source_state=assignment.state_id,
        metadata={
            "schema": RADIAL_SHELL_SCHEMA,
            "region": "enclosed-core",
            "physical_material_only": True,
            "closed_physical_volume": True,
            "validation": core_record,
        },
    )
    shell_part = RadialExportPart(
        name="Radial partner outer shell",
        vertices_mm=_immutable_array(shell_surface.vertices, np.float64),
        faces=_immutable_array(shell_surface.faces, np.int32),
        extruder=assignment.partner_extruder,
        role="partner_outer_shell",
        solid_infill=True,
        source_state=assignment.state_id,
        metadata={
            "schema": RADIAL_SHELL_SCHEMA,
            "region": "visible-outer-skin",
            "physical_material_only": True,
            "requested_skin_thickness_mm": thickness,
            "source_exterior_preserved_exactly": True,
            "closed_physical_volume": True,
            "validation": shell_record,
        },
    )
    diagnostics = {
        "tetrahedralization": tet_record,
        "tetrahedral_volume_mm3": tetra_volume,
        "interface_extraction": interface_record,
        "shell": shell_record,
        "core": core_record,
        "interface_depth_min_mm": distance_min,
        "interface_depth_max_mm": distance_max,
        "interface_depth_tolerance_mm": fidelity_limit,
        "volume_error_mm3": volume_error,
    }
    metadata = {
        "schema": RADIAL_SHELL_SCHEMA,
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "physical_materials_only": True,
        "ratio_definitions": 0,
        "cycle_definitions": 0,
        "painted_triangles": 0,
        "source_part_count": 1,
        "source_surface_state_count": 1,
        "source_state_id": assignment.state_id,
        "partner_extruder": assignment.partner_extruder,
        "black_extruder": black,
        "skin_thickness_mm": thickness,
        "source_exterior_preserved_exactly": True,
        "exact_touch_interfaces": 1,
        "positive_overlap_mm3": 0.0,
        "gap_mm": 0.0,
        "closed_physical_volumes": True,
        "stage_b_surface_assignments_supported_by_api": True,
        "stage_b_owner_propagation_implemented": False,
        "diagnostics": diagnostics,
    }
    return RadialShellResult(
        # The serializer intentionally clips later normal parts over earlier
        # ones.  Exact-touch makes ordering geometrically irrelevant, but the
        # core-first / visible-shell-last order is the safest archive contract.
        parts=(black_part, shell_part),
        skin_thickness_mm=thickness,
        partner_extruder=assignment.partner_extruder,
        black_extruder=black,
        eligible_state_id=assignment.state_id,
        eligible_area_fraction=analysis.eligible_area_fraction,
        source_fingerprint=source_fp,
        source_volume_mm3=source_volume,
        output_volume_mm3=output_volume,
        interfaces=(shared_interface,),
        metadata=metadata,
    )


def build_radial_shell_from_level(
    level: MeshLevel,
    *,
    height_mm: float,
    face_state_ids: np.ndarray,
    eligible_state_partners: Mapping[int, int],
    black_extruder: int,
    skin_thickness_mm: float = DEFAULT_SKIN_THICKNESS_MM,
    minimum_eligible_area_fraction: float = 1.0,
    offset_resolution_mm: float | None = None,
) -> RadialShellResult:
    """Millimetre-safe adapter for the application's normalized MeshLevel."""

    scale = float(height_mm)
    if not math.isfinite(scale) or scale <= 0.0:
        _raise("invalid_height_mm", height_mm=scale)
    vertices_unit = np.asarray(level.vertices_unit, dtype=np.float64)
    return build_radial_shell(
        vertices_unit * scale,
        np.asarray(level.faces),
        face_part_ids=(
            None
            if np.asarray(level.face_part_ids).size == 0
            else np.asarray(level.face_part_ids)
        ),
        face_provenance=(
            None
            if np.asarray(level.face_provenance).size == 0
            else np.asarray(level.face_provenance)
        ),
        face_state_ids=face_state_ids,
        eligible_state_partners=eligible_state_partners,
        black_extruder=black_extruder,
        skin_thickness_mm=skin_thickness_mm,
        minimum_eligible_area_fraction=minimum_eligible_area_fraction,
        offset_resolution_mm=offset_resolution_mm,
    )


__all__ = [
    "DEFAULT_SKIN_THICKNESS_MM",
    "RADIAL_SHELL_SCHEMA",
    "RadialExportPart",
    "RadialShellError",
    "RadialShellResult",
    "RadialSurfaceAnalysis",
    "RadialSurfaceAssignment",
    "analyze_radial_surface_assignments",
    "build_radial_shell",
    "build_radial_shell_from_level",
]
