"""Exact combinatorial manifoldization for labelled ColorDepth cells.

The input is a conforming, non-overlapping tetrahedral complex labelled only
with physical U1 tools F1..F4.  Cell labels and geometry are immutable.  A
material may nevertheless occupy several angular sectors around one mesh
edge; naively extracting its boundary then creates an indexed non-manifold
edge.  This module pairs boundary half-edges per contiguous material sector,
splits face corners into vertex-link cycles, and resolves the rare parallel
abstract edge with an exact coplanar subdivision.

No point is moved off the original piecewise-planar material boundary.  The
result preserves exterior triangles, exact material interfaces and signed
cell volume.  Coincident edge or point contacts remain geometrically
coincident and are reported explicitly; only their topological indices are
separated.  Legacy FullSpectrum Ratio, Cycle and triangle paint are outside
this module's contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from .volume_partition import TET_EDGES, TET_LOCAL_FACES


MATERIAL_MANIFOLD_SCHEMA = (
    "tripo-spectrum-mapper.color-depth.material-manifold.v1"
)
_VOLUME_RELATIVE_TOLERANCE = 1e-9
_AREA_RELATIVE_TOLERANCE = 1e-9


class MaterialManifoldError(RuntimeError):
    """Stable fail-closed error from material manifoldization."""

    def __init__(self, code: str, **details: object) -> None:
        self.code = str(code)
        self.details = dict(details)
        super().__init__(self.code)


def _raise(code: str, **details: object) -> None:
    raise MaterialManifoldError(code, **details)


def _immutable(values: np.ndarray, dtype: np.dtype) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype).copy()
    result.flags.writeable = False
    return result


@dataclass(frozen=True, slots=True)
class ManifoldMaterialPart:
    """One physical material boundary after purely topological separation."""

    vertices_mm: np.ndarray
    faces: np.ndarray
    extruder: int
    source_faces: np.ndarray
    source_owner_cells: np.ndarray
    output_face_source: np.ndarray
    face_components: np.ndarray
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def physical_material(self) -> int:
        return self.extruder


@dataclass(frozen=True, slots=True)
class MaterialManifoldResult:
    """Validated manifold physical boundaries for one labelled cell complex."""

    parts: tuple[ManifoldMaterialPart, ...]
    source_volume_mm3: float
    output_volume_mm3: float
    cell_materials: np.ndarray
    interfaces: tuple[Mapping[str, object], ...]
    metadata: Mapping[str, object]


def _encoded_edges(edges: np.ndarray) -> np.ndarray:
    values = np.sort(np.asarray(edges, dtype=np.int64), axis=-1)
    if len(values) and (
        int(values.min()) < 0 or int(values.max()) >= 2**32
    ):
        _raise("edge_index_not_uint32")
    return (
        values[..., 0].astype(np.uint64) << np.uint64(32)
    ) | values[..., 1].astype(np.uint64)


def _decode_edge(key: int | np.uint64) -> tuple[int, int]:
    value = int(key)
    return value >> 32, value & 0xFFFFFFFF


def _tetra_volumes(nodes: np.ndarray, tetrahedra: np.ndarray) -> np.ndarray:
    points = nodes[tetrahedra]
    return np.abs(
        np.einsum(
            "ij,ij->i",
            points[:, 1] - points[:, 0],
            np.cross(
                points[:, 2] - points[:, 0],
                points[:, 3] - points[:, 0],
            ),
        )
        / 6.0
    )


def _validate_input(
    nodes_mm: np.ndarray,
    tetrahedra: np.ndarray,
    cell_materials: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    nodes = np.asarray(nodes_mm, dtype=np.float64)
    raw_tets = np.asarray(tetrahedra)
    raw_materials = np.asarray(cell_materials)
    if nodes.ndim != 2 or nodes.shape[1:] != (3,) or len(nodes) < 4:
        _raise("invalid_cell_nodes", shape=tuple(nodes.shape))
    if not np.isfinite(nodes).all():
        _raise("nonfinite_cell_nodes")
    if (
        raw_tets.ndim != 2
        or raw_tets.shape[1:] != (4,)
        or not len(raw_tets)
        or not np.issubdtype(raw_tets.dtype, np.integer)
    ):
        _raise("invalid_tetrahedra", shape=tuple(raw_tets.shape))
    tets = np.asarray(raw_tets, dtype=np.int32)
    if int(tets.min()) < 0 or int(tets.max()) >= len(nodes):
        _raise("tetrahedron_index_out_of_range")
    if np.any(np.diff(np.sort(tets, axis=1), axis=1) == 0):
        _raise("repeated_tetrahedron_vertex")
    if (
        raw_materials.shape != (len(tets),)
        or not np.issubdtype(raw_materials.dtype, np.integer)
    ):
        _raise("invalid_cell_materials", shape=tuple(raw_materials.shape))
    materials = np.asarray(raw_materials, dtype=np.int8)
    invalid = sorted(
        int(value)
        for value in np.unique(materials)
        if not 1 <= int(value) <= 4
    )
    if invalid:
        _raise("invalid_cell_materials", values=invalid)
    volumes = _tetra_volumes(nodes, tets)
    total = float(volumes.sum())
    # A conforming level-set split may legitimately produce extremely small
    # positive child tetrahedra near a threshold/source vertex.  Reject only
    # exact/nonfinite degeneracy here; aggregate material and total volume are
    # still checked independently below.  A scale-relative cutoff discarded
    # 778 independently validated B4 cells (minimum 1.87e-21 mm^3).
    bad = np.flatnonzero(~np.isfinite(volumes) | (volumes <= 0.0))
    if len(bad):
        _raise(
            "degenerate_tetrahedra",
            count=int(len(bad)),
            examples=[int(value) for value in bad[:20]],
        )
    return nodes.copy(), tets.copy(), materials.copy(), volumes


def _face_table(
    tetrahedra: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = tetrahedra[:, TET_LOCAL_FACES].reshape((-1, 3))
    canonical = np.sort(raw, axis=1)
    order = np.lexsort((canonical[:, 2], canonical[:, 1], canonical[:, 0]))
    ordered = canonical[order]
    starts = np.r_[
        0,
        np.flatnonzero(np.any(ordered[1:] != ordered[:-1], axis=1)) + 1,
    ].astype(np.int64, copy=False)
    counts = np.diff(np.r_[starts, len(order)]).astype(np.int32, copy=False)
    return raw, order.astype(np.int64, copy=False), starts, counts


def _oriented_face_rows(
    nodes: np.ndarray,
    tetrahedra: np.ndarray,
    raw_faces: np.ndarray,
    rows: np.ndarray,
) -> np.ndarray:
    selected = np.asarray(rows, dtype=np.int64)
    faces = raw_faces[selected].copy()
    owners = selected // 4
    opposite = tetrahedra[owners, selected % 4]
    first = nodes[faces[:, 0]]
    normals = np.cross(
        nodes[faces[:, 1]] - first,
        nodes[faces[:, 2]] - first,
    )
    inward = np.einsum(
        "ij,ij->i", normals, nodes[opposite] - first
    ) > 0.0
    if np.any(inward):
        faces[inward, 1:3] = faces[inward, 2:0:-1]
    return faces.astype(np.int32, copy=False)


@dataclass(slots=True)
class _EdgeIncidenceIndex:
    tetrahedra: np.ndarray
    unique_keys: np.ndarray
    offsets: np.ndarray
    sorted_cells: np.ndarray
    fan_cache: dict[int, tuple[np.ndarray, bool]]

    @classmethod
    def build(cls, tetrahedra: np.ndarray) -> "_EdgeIncidenceIndex":
        tets = np.ascontiguousarray(tetrahedra, dtype=np.int32)
        keys = _encoded_edges(tets[:, TET_EDGES]).reshape(-1)
        cells = np.repeat(np.arange(len(tets), dtype=np.int32), 6)
        order = np.argsort(keys, kind="stable")
        sorted_keys = keys[order]
        starts = np.r_[
            0, np.flatnonzero(sorted_keys[1:] != sorted_keys[:-1]) + 1
        ].astype(np.int64, copy=False)
        return cls(
            tetrahedra=tets,
            unique_keys=sorted_keys[starts].copy(),
            offsets=np.r_[starts, len(sorted_keys)].astype(
                np.int64, copy=False
            ),
            sorted_cells=cells[order],
            fan_cache={},
        )

    def incident_cells(self, key: int) -> np.ndarray:
        position = int(np.searchsorted(self.unique_keys, np.uint64(key)))
        if (
            position >= len(self.unique_keys)
            or int(self.unique_keys[position]) != int(key)
        ):
            _raise("missing_cell_edge", edge=list(_decode_edge(key)))
        return self.sorted_cells[
            int(self.offsets[position]) : int(self.offsets[position + 1])
        ]

    def fan(self, key: int) -> tuple[np.ndarray, bool]:
        cached = self.fan_cache.get(int(key))
        if cached is not None:
            return cached
        a, b = _decode_edge(key)
        incident = self.incident_cells(key)
        adjacency: dict[int, list[int]] = {}
        link_by_cell: dict[int, tuple[int, int]] = {}
        for raw_cell in incident:
            cell = int(raw_cell)
            other = tuple(
                int(value)
                for value in self.tetrahedra[cell]
                if int(value) not in (a, b)
            )
            if len(other) != 2:
                _raise("invalid_edge_incident_cell", edge=[a, b], cell=cell)
            link_by_cell[cell] = other
            for vertex in other:
                adjacency.setdefault(vertex, []).append(cell)
        if any(len(cells) > 2 for cells in adjacency.values()):
            _raise("nonmanifold_cell_edge_link", edge=[a, b])
        endpoints = [
            vertex for vertex, cells in adjacency.items() if len(cells) == 1
        ]
        cycle = not endpoints
        if not cycle and len(endpoints) != 2:
            _raise("branched_cell_edge_link", edge=[a, b])
        start_vertex = min(adjacency) if cycle else min(endpoints)
        current_vertex = start_vertex
        previous_cell = -1
        ordered: list[int] = []
        while True:
            candidates = [
                cell
                for cell in adjacency[current_vertex]
                if cell != previous_cell
            ]
            if not candidates:
                break
            cell = min(candidates)
            if cell in ordered:
                break
            ordered.append(cell)
            first, second = link_by_cell[cell]
            next_vertex = second if first == current_vertex else first
            previous_cell = cell
            current_vertex = next_vertex
            if cycle and current_vertex == start_vertex:
                break
        if len(ordered) != len(incident):
            _raise(
                "disconnected_cell_edge_link",
                edge=[a, b],
                incident_cells=int(len(incident)),
                ordered_cells=int(len(ordered)),
            )
        result = np.asarray(ordered, dtype=np.int32), bool(cycle)
        self.fan_cache[int(key)] = result
        return result


def _material_runs(
    ordered_cells: np.ndarray,
    cell_materials: np.ndarray,
    material: int,
    cycle: bool,
) -> list[np.ndarray]:
    selected = np.asarray(cell_materials[ordered_cells] == int(material))
    if not np.any(selected) or (cycle and np.all(selected)):
        return []
    starts: list[int] = []
    for position in range(len(selected)):
        if not selected[position]:
            continue
        previous = (
            selected[(position - 1) % len(selected)]
            if cycle or position > 0
            else False
        )
        if not previous:
            starts.append(position)
    runs: list[np.ndarray] = []
    for start in starts:
        positions: list[int] = []
        position = start
        while bool(selected[position]):
            positions.append(position)
            position += 1
            if position == len(selected):
                if cycle:
                    position = 0
                else:
                    break
            if position == start:
                break
        runs.append(ordered_cells[np.asarray(positions, dtype=np.int32)])
    return runs


def _surface_soups(
    nodes: np.ndarray,
    tetrahedra: np.ndarray,
    materials: np.ndarray,
) -> tuple[
    dict[int, tuple[np.ndarray, np.ndarray]],
    tuple[Mapping[str, object], ...],
    Mapping[str, object],
]:
    raw, order, starts, counts = _face_table(tetrahedra)
    bad = np.flatnonzero(counts > 2)
    if len(bad):
        examples = np.sort(raw[order[starts[bad[:20]]]], axis=1)
        _raise(
            "nonmanifold_cell_complex",
            face_count=int(len(bad)),
            examples=examples.astype(int).tolist(),
        )
    exterior_rows = order[starts[counts == 1]]
    paired_starts = starts[counts == 2]
    first_rows = order[paired_starts]
    second_rows = order[paired_starts + 1]
    first_owners = (first_rows // 4).astype(np.int32)
    second_owners = (second_rows // 4).astype(np.int32)
    first_materials = materials[first_owners]
    second_materials = materials[second_owners]
    different = first_materials != second_materials
    rows = np.concatenate(
        (exterior_rows, first_rows[different], second_rows[different])
    )
    owners = (rows // 4).astype(np.int32)
    oriented = _oriented_face_rows(nodes, tetrahedra, raw, rows)
    soups: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for material in sorted(map(int, np.unique(materials))):
        selected = materials[owners] == material
        soups[material] = (
            np.ascontiguousarray(oriented[selected], dtype=np.int32),
            np.ascontiguousarray(owners[selected], dtype=np.int32),
        )

    low = np.minimum(first_materials[different], second_materials[different])
    high = np.maximum(first_materials[different], second_materials[different])
    pair_codes = low.astype(np.int16) * 5 + high
    interfaces: list[Mapping[str, object]] = []
    for code, count in zip(
        *np.unique(pair_codes, return_counts=True), strict=True
    ):
        first = int(code // 5)
        second = int(code % 5)
        interfaces.append(
            {
                "name": f"F{first}__F{second}",
                "physical_materials": [first, second],
                "faces": int(count),
                "exact_coordinate_triangles": True,
                "opposite_winding": True,
                "gap_mm": 0.0,
                "positive_overlap_mm3": 0.0,
            }
        )
    return soups, tuple(interfaces), {
        "unique_cell_faces": int(len(starts)),
        "exterior_faces": int(len(exterior_rows)),
        "paired_cell_faces": int(len(paired_starts)),
        "material_interface_faces": int(np.count_nonzero(different)),
        "material_surface_soup_faces": int(len(rows)),
    }


def _pair_surface_halfedges(
    tetrahedra: np.ndarray,
    cell_materials: np.ndarray,
    material: int,
    faces: np.ndarray,
    owners: np.ndarray,
    index: _EdgeIncidenceIndex,
) -> tuple[np.ndarray, Mapping[str, object]]:
    face_edges = faces[:, ((0, 1), (1, 2), (2, 0))].reshape((-1, 2))
    keys = _encoded_edges(face_edges)
    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]
    starts = np.r_[
        0, np.flatnonzero(sorted_keys[1:] != sorted_keys[:-1]) + 1
    ].astype(np.int64, copy=False)
    stops = np.r_[starts[1:], len(order)]
    mates = np.full(len(face_edges), -1, dtype=np.int64)
    geometric_self_contact_edges = 0
    maximum_incidence = 0
    sector_pairs = 0

    def pair(first_id: int, second_id: int) -> None:
        if mates[first_id] >= 0 or mates[second_id] >= 0:
            _raise("surface_halfedge_paired_twice", material=material)
        first = face_edges[first_id]
        second = face_edges[second_id]
        if (
            int(first[0]) != int(second[1])
            or int(first[1]) != int(second[0])
        ):
            _raise(
                "surface_halfedge_winding_mismatch",
                material=material,
                first=first.astype(int).tolist(),
                second=second.astype(int).tolist(),
            )
        mates[first_id] = second_id
        mates[second_id] = first_id

    for start, stop in zip(starts, stops, strict=True):
        halfedges = order[start:stop]
        count = int(len(halfedges))
        maximum_incidence = max(maximum_incidence, count)
        if count == 2:
            pair(int(halfedges[0]), int(halfedges[1]))
            continue
        if count < 2 or count % 2:
            _raise(
                "odd_material_edge_incidence",
                material=material,
                edge=list(_decode_edge(sorted_keys[start])),
                incidence=count,
            )
        geometric_self_contact_edges += 1
        key = int(sorted_keys[start])
        ordered_cells, cycle = index.fan(key)
        runs = _material_runs(
            ordered_cells, cell_materials, material, cycle
        )
        if len(runs) * 2 != count:
            _raise(
                "material_sector_accounting_failed",
                material=material,
                edge=list(_decode_edge(key)),
                halfedges=count,
                sectors=int(len(runs)),
            )
        group_owners = owners[halfedges // 3]
        assigned: set[int] = set()
        for run in runs:
            selected_halfedges = halfedges[np.isin(group_owners, run)]
            if len(selected_halfedges) != 2:
                _raise(
                    "material_sector_not_two_sided",
                    material=material,
                    edge=list(_decode_edge(key)),
                    halfedges=int(len(selected_halfedges)),
                )
            first_id, second_id = map(int, selected_halfedges)
            assigned.update((first_id, second_id))
            pair(first_id, second_id)
            sector_pairs += 1
        if len(assigned) != count:
            _raise(
                "material_sector_halfedges_not_consumed",
                material=material,
                edge=list(_decode_edge(key)),
            )
    if np.any(mates < 0):
        _raise(
            "unpaired_material_halfedges",
            material=material,
            count=int(np.count_nonzero(mates < 0)),
        )
    return mates, {
        "geometric_edges": int(len(starts)),
        "geometric_self_contact_edges": int(geometric_self_contact_edges),
        "maximum_geometric_edge_incidence_before": int(maximum_incidence),
        "sector_pairs_on_geometric_self_contact_edges": int(sector_pairs),
        "unpaired_halfedges": 0,
        "opposite_winding_pairs": True,
    }


def _split_vertex_links(
    faces: np.ndarray,
    mates: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]]:
    halfedge_ids = np.arange(len(mates), dtype=np.int64)
    first_halfedges = halfedge_ids[halfedge_ids < mates]
    second_halfedges = mates[first_halfedges]
    first_faces, first_local = np.divmod(first_halfedges, 3)
    second_faces, second_local = np.divmod(second_halfedges, 3)
    first_start = first_faces * 3 + first_local
    first_end = first_faces * 3 + ((first_local + 1) % 3)
    second_start = second_faces * 3 + second_local
    second_end = second_faces * 3 + ((second_local + 1) % 3)
    left = np.concatenate((first_start, first_end))
    right = np.concatenate((second_end, second_start))
    corner_count = len(faces) * 3
    graph = sparse.coo_matrix(
        (
            np.ones(2 * len(left), dtype=np.uint8),
            (
                np.concatenate((left, right)),
                np.concatenate((right, left)),
            ),
        ),
        shape=(corner_count, corner_count),
    ).tocsr()
    component_count, labels = connected_components(
        graph, directed=False, return_labels=True
    )
    degrees = np.bincount(
        np.concatenate((left, right)), minlength=corner_count
    )
    if np.any(degrees != 2):
        _raise(
            "vertex_link_not_cycle",
            bad_corners=int(np.count_nonzero(degrees != 2)),
        )
    corner_vertices = faces.reshape(-1)
    minimum = np.full(
        component_count, np.iinfo(np.int32).max, dtype=np.int32
    )
    maximum = np.full(component_count, -1, dtype=np.int32)
    np.minimum.at(minimum, labels, corner_vertices)
    np.maximum.at(maximum, labels, corner_vertices)
    if not np.array_equal(minimum, maximum):
        _raise("vertex_link_joined_distinct_coordinates")
    abstract_faces = labels.reshape((-1, 3)).astype(np.int32)
    if np.any(np.diff(np.sort(abstract_faces, axis=1), axis=1) == 0):
        _raise("repeated_vertex_after_link_split")
    edge_ids = np.full(len(mates), -1, dtype=np.int32)
    ids = np.arange(len(first_halfedges), dtype=np.int32)
    edge_ids[first_halfedges] = ids
    edge_ids[second_halfedges] = ids
    if np.any(edge_ids < 0):
        _raise("abstract_edge_assignment_failed")
    _source_vertices, source_counts = np.unique(minimum, return_counts=True)
    return minimum, abstract_faces, edge_ids.reshape((-1, 3)), {
        "source_face_corners": int(corner_count),
        "topological_vertices_after_split": int(component_count),
        "duplicated_topological_vertex_copies": int(
            component_count - len(source_counts)
        ),
        "geometric_self_contact_vertices": int(
            np.count_nonzero(source_counts > 1)
        ),
        "corner_link_degree_two": True,
        "vertex_links_single_cycles": True,
        "maximum_corners_per_vertex_link": int(
            np.bincount(labels).max(initial=0)
        ),
    }


def _parallel_abstract_edge_ids(
    faces: np.ndarray,
    face_edge_ids: np.ndarray,
) -> tuple[np.ndarray, int]:
    """Return every abstract edge object sharing an indexed endpoint pair."""

    edge_count = int(face_edge_ids.max(initial=-1)) + 1
    if edge_count == 0:
        return np.empty(0, dtype=np.int32), 0
    flat_ids = face_edge_ids.reshape(-1)
    directed = faces[:, ((0, 1), (1, 2), (2, 0))].reshape((-1, 2))
    canonical = np.sort(directed, axis=1)
    minimum = np.full(edge_count, np.iinfo(np.int32).max, dtype=np.int32)
    maximum = np.full(edge_count, -1, dtype=np.int32)
    np.minimum.at(minimum, flat_ids, canonical[:, 0])
    np.maximum.at(maximum, flat_ids, canonical[:, 1])
    pairs = np.column_stack((minimum, maximum))
    order = np.lexsort((pairs[:, 1], pairs[:, 0]))
    ordered = pairs[order]
    starts = np.r_[
        0,
        np.flatnonzero(np.any(ordered[1:] != ordered[:-1], axis=1)) + 1,
    ]
    counts = np.diff(np.r_[starts, len(order)])
    repeated = np.flatnonzero(counts > 1)
    if not len(repeated):
        return np.empty(0, dtype=np.int32), 0
    ids = np.concatenate(
        [
            order[int(starts[group]) : int(starts[group] + counts[group])]
            for group in repeated
        ]
    )
    return np.asarray(ids, dtype=np.int32), int(len(repeated))


def _subdivide_selected_abstract_edges(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_edge_ids: np.ndarray,
    split_edge_ids: np.ndarray,
    *,
    initial_parallel_coordinate_pairs: int,
    initial_parallel_edge_objects: int,
    source_nodes: np.ndarray | None = None,
    source_global_faces: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]]:
    """Subdivide selected delta-complex edges without moving its surface."""

    edge_count = int(face_edge_ids.max(initial=-1)) + 1
    problematic_ids = np.asarray(split_edge_ids, dtype=np.int32)
    if len(problematic_ids):
        if (
            int(problematic_ids.min()) < 0
            or int(problematic_ids.max()) >= edge_count
            or len(np.unique(problematic_ids)) != len(problematic_ids)
        ):
            _raise("invalid_shared_split_edge_ids")
        problematic_ids = np.sort(problematic_ids)
    problematic = np.zeros(edge_count, dtype=bool)
    problematic[problematic_ids] = True
    affected_faces = np.any(problematic[face_edge_ids], axis=1)
    if not np.any(affected_faces):
        return (
            vertices.copy(),
            faces.copy(),
            np.arange(len(faces), dtype=np.int32),
            {
                "parallel_abstract_edge_coordinate_pairs": int(
                    initial_parallel_coordinate_pairs
                ),
                "parallel_abstract_edge_objects": int(
                    initial_parallel_edge_objects
                ),
                "shared_split_abstract_edge_objects": 0,
                "propagated_counterpart_edge_objects": 0,
                "locally_subdivided_source_faces": 0,
                "added_midpoint_vertices": 0,
                "added_face_centroid_vertices": 0,
                "output_faces": int(len(faces)),
                "piecewise_planar_surface_exact": True,
                "coordinate_face_counterparts_receive_identical_partition": True,
            },
        )

    flat_ids = face_edge_ids.reshape(-1)
    directed = faces[:, ((0, 1), (1, 2), (2, 0))].reshape((-1, 2))
    canonical = np.sort(directed, axis=1)
    minimum = np.full(edge_count, np.iinfo(np.int32).max, dtype=np.int32)
    maximum = np.full(edge_count, -1, dtype=np.int32)
    np.minimum.at(minimum, flat_ids, canonical[:, 0])
    np.maximum.at(maximum, flat_ids, canonical[:, 1])
    midpoint_ids = np.full(edge_count, -1, dtype=np.int32)
    midpoint_ids[problematic_ids] = np.arange(
        len(vertices), len(vertices) + len(problematic_ids), dtype=np.int32
    )
    midpoint_coordinates = 0.5 * (
        vertices[minimum[problematic_ids]]
        + vertices[maximum[problematic_ids]]
    )
    affected_ids = np.flatnonzero(affected_faces)
    centroid_ids = np.full(len(faces), -1, dtype=np.int32)
    centroid_ids[affected_ids] = np.arange(
        len(vertices) + len(problematic_ids),
        len(vertices) + len(problematic_ids) + len(affected_ids),
        dtype=np.int32,
    )
    if (source_nodes is None) != (source_global_faces is None):
        _raise("incomplete_canonical_source_centroid_inputs")
    if source_nodes is not None and source_global_faces is not None:
        global_faces = np.asarray(source_global_faces, dtype=np.int32)
        if global_faces.shape != faces.shape:
            _raise(
                "invalid_canonical_source_faces",
                expected=tuple(faces.shape),
                actual=tuple(global_faces.shape),
            )
        # Shared counterparts have opposite winding.  Sum coordinates in
        # canonical *global node ID* order so their centroid bits are
        # identical independent of winding and floating-point associativity.
        canonical_global = np.sort(global_faces[affected_ids], axis=1)
        centroid_coordinates = (
            np.asarray(source_nodes, dtype=np.float64)[canonical_global].sum(
                axis=1
            )
            / 3.0
        )
        centroid_mode = "canonical_global_node_id_order"
    else:
        # Backward-compatible private diagnostic path without a global-node
        # provenance map.
        centroid_coordinates = (
            np.sort(vertices[faces[affected_ids]], axis=1).sum(axis=1) / 3.0
        )
        centroid_mode = "canonical_coordinate_channel_order"
    output_vertices = np.vstack(
        (vertices, midpoint_coordinates, centroid_coordinates)
    )
    split_counts = problematic[face_edge_ids].sum(axis=1).astype(
        np.int32, copy=False
    )
    face_output_counts = np.where(
        affected_faces, 3 + split_counts, 1
    ).astype(np.int32, copy=False)
    output_offsets = np.r_[
        0, np.cumsum(face_output_counts, dtype=np.int64)
    ]
    output_faces = np.empty((int(output_offsets[-1]), 3), dtype=np.int32)
    output_sources = np.repeat(
        np.arange(len(faces), dtype=np.int32), face_output_counts
    )
    unaffected_ids = np.flatnonzero(~affected_faces)
    output_faces[output_offsets[unaffected_ids]] = faces[unaffected_ids]
    # Only the compact affected set enters Python.  On the real head this is
    # about 2.3k rows out of 1.3M; avoiding a tuple object for every unchanged
    # face is material to peak memory.
    for face_id in map(int, affected_ids):
        face = faces[face_id]
        center = int(centroid_ids[face_id])
        output_cursor = int(output_offsets[face_id])
        for local_edge in range(3):
            first = int(face[local_edge])
            second = int(face[(local_edge + 1) % 3])
            edge_id = int(face_edge_ids[face_id, local_edge])
            if problematic[edge_id]:
                midpoint = int(midpoint_ids[edge_id])
                output_faces[output_cursor] = (first, midpoint, center)
                output_faces[output_cursor + 1] = (
                    midpoint,
                    second,
                    center,
                )
                output_cursor += 2
            else:
                output_faces[output_cursor] = (first, second, center)
                output_cursor += 1
        if output_cursor != int(output_offsets[face_id + 1]):
            _raise(
                "subdivision_output_count_mismatch",
                source_face=int(face_id),
            )
    return (
        np.ascontiguousarray(output_vertices, dtype=np.float64),
        np.ascontiguousarray(output_faces, dtype=np.int32),
        np.ascontiguousarray(output_sources, dtype=np.int32),
        {
            "parallel_abstract_edge_coordinate_pairs": int(
                initial_parallel_coordinate_pairs
            ),
            "parallel_abstract_edge_objects": int(
                initial_parallel_edge_objects
            ),
            "shared_split_abstract_edge_objects": int(len(problematic_ids)),
            "propagated_counterpart_edge_objects": int(
                len(problematic_ids) - initial_parallel_edge_objects
            ),
            "locally_subdivided_source_faces": int(len(affected_ids)),
            "added_midpoint_vertices": int(len(problematic_ids)),
            "added_face_centroid_vertices": int(len(affected_ids)),
            "output_faces": int(len(output_faces)),
            "unchanged_faces_vector_copied": int(len(unaffected_ids)),
            "affected_faces_python_iterated": int(len(affected_ids)),
            "piecewise_planar_surface_exact": True,
            "coordinate_face_counterparts_receive_identical_partition": True,
            "shared_centroid_construction": centroid_mode,
        },
    )


def _subdivide_parallel_abstract_edges(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_edge_ids: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]]:
    """Backward-compatible one-material helper.

    Production calls the all-material registry below.  Keeping this helper
    avoids changing private diagnostic callers while giving it the same
    deterministic subdivision implementation.
    """

    split_ids, repeated_groups = _parallel_abstract_edge_ids(
        faces, face_edge_ids
    )
    return _subdivide_selected_abstract_edges(
        vertices,
        faces,
        face_edge_ids,
        split_ids,
        initial_parallel_coordinate_pairs=repeated_groups,
        initial_parallel_edge_objects=int(len(split_ids)),
    )


@dataclass(frozen=True, slots=True)
class _PreparedMaterialBoundary:
    material: int
    source_faces: np.ndarray
    owners: np.ndarray
    vertices: np.ndarray
    faces: np.ndarray
    face_edge_ids: np.ndarray
    pairing: Mapping[str, object]
    vertex_link_split: Mapping[str, object]
    initial_split_edge_ids: np.ndarray
    initial_parallel_coordinate_pairs: int


def _prepare_material_boundary(
    nodes: np.ndarray,
    tetrahedra: np.ndarray,
    materials: np.ndarray,
    material: int,
    source_faces: np.ndarray,
    owners: np.ndarray,
    index: _EdgeIncidenceIndex,
) -> _PreparedMaterialBoundary:
    mates, pairing = _pair_surface_halfedges(
        tetrahedra,
        materials,
        material,
        source_faces,
        owners,
        index,
    )
    source_vertex_ids, abstract_faces, edge_ids, link_record = (
        _split_vertex_links(source_faces, mates)
    )
    abstract_vertices = nodes[source_vertex_ids]
    if not np.array_equal(source_vertex_ids[abstract_faces], source_faces):
        _raise("source_triangle_or_winding_changed", material=material)
    split_ids, repeated_groups = _parallel_abstract_edge_ids(
        abstract_faces, edge_ids
    )
    return _PreparedMaterialBoundary(
        material=int(material),
        source_faces=np.ascontiguousarray(source_faces, dtype=np.int32),
        owners=np.ascontiguousarray(owners, dtype=np.int32),
        vertices=np.ascontiguousarray(abstract_vertices, dtype=np.float64),
        faces=np.ascontiguousarray(abstract_faces, dtype=np.int32),
        face_edge_ids=np.ascontiguousarray(edge_ids, dtype=np.int32),
        pairing=pairing,
        vertex_link_split=link_record,
        initial_split_edge_ids=split_ids,
        initial_parallel_coordinate_pairs=int(repeated_groups),
    )


@dataclass(frozen=True, slots=True)
class _SourceFaceRegistry:
    """Compact all-material source-face occurrence registry.

    Source counterparts in a conforming tetrahedral complex share the same
    three global node IDs.  Packing those sorted IDs is collision-free while
    ``3 * bits <= 64`` and avoids one Python tuple/bytes object per face.  The
    structured fallback retains the same exact grouping for larger indices.
    """

    materials: np.ndarray
    global_faces: np.ndarray
    group_ids: np.ndarray
    group_counts: np.ndarray
    representative_occurrences: np.ndarray
    occurrence_offsets: Mapping[int, int]
    unique_faces: int
    exterior_faces: int
    internal_faces: int
    key_mode: str
    bits_per_node: int


def _group_canonical_index_faces(
    canonical_faces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str, int]:
    faces = np.ascontiguousarray(canonical_faces, dtype=np.int32)
    maximum = int(faces.max(initial=0))
    bits = max(1, maximum.bit_length())
    if 3 * bits <= 64:
        values = faces.astype(np.uint64, copy=False)
        keys = (
            values[:, 0]
            | (values[:, 1] << np.uint64(bits))
            | (values[:, 2] << np.uint64(2 * bits))
        )
        order = np.argsort(keys, kind="quicksort")
        ordered = keys[order]
        starts = np.r_[
            0, np.flatnonzero(ordered[1:] != ordered[:-1]) + 1
        ].astype(np.int64, copy=False)
        mode = "packed_uint64"
    else:
        dtype = np.dtype(
            [("a", "<i4"), ("b", "<i4"), ("c", "<i4")]
        )
        keys = faces.view(dtype).reshape(-1)
        order = np.argsort(
            keys, order=("a", "b", "c"), kind="quicksort"
        )
        ordered_faces = faces[order]
        starts = np.r_[
            0,
            np.flatnonzero(
                np.any(ordered_faces[1:] != ordered_faces[:-1], axis=1)
            )
            + 1,
        ].astype(np.int64, copy=False)
        mode = "structured_int32"
    counts = np.diff(np.r_[starts, len(order)]).astype(np.int32, copy=False)
    return order.astype(np.int64, copy=False), starts, counts, mode, bits


def _canonical_coordinate_bits(
    nodes: np.ndarray, faces: np.ndarray
) -> np.ndarray:
    points = np.asarray(nodes, dtype=np.float64)[
        np.asarray(faces, dtype=np.int32)
    ].copy()
    points[points == 0.0] = 0.0
    vertex_dtype = np.dtype(
        [("x", "<f8"), ("y", "<f8"), ("z", "<f8")]
    )
    structured = np.ascontiguousarray(points).view(vertex_dtype).reshape(
        (-1, 3)
    )
    order = np.argsort(
        structured,
        axis=1,
        order=("x", "y", "z"),
        kind="quicksort",
    )
    canonical = np.take_along_axis(points, order[:, :, None], axis=1)
    return np.ascontiguousarray(canonical).view("<u8").reshape((-1, 9))


def _coordinate_face_hashes(nodes: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Exact-equality preserving 64-bit filter; collisions are rechecked."""

    face_array = np.asarray(faces, dtype=np.int32)
    result = np.empty(len(face_array), dtype=np.uint64)
    chunk_size = 100_000
    offset = np.uint64(1469598103934665603)
    prime = np.uint64(1099511628211)
    for start in range(0, len(face_array), chunk_size):
        stop = min(start + chunk_size, len(face_array))
        bits = _canonical_coordinate_bits(nodes, face_array[start:stop])
        hashed = np.full(stop - start, offset, dtype=np.uint64)
        for column in range(9):
            hashed ^= bits[:, column]
            hashed *= prime
        result[start:stop] = hashed
    return result


def _audit_unshared_coordinate_faces(
    registry: _SourceFaceRegistry, nodes: np.ndarray
) -> None:
    """Retain geometric multiplicity gates without a global float-bytes dict."""

    representatives = registry.representative_occurrences
    representative_faces = registry.global_faces[representatives]
    hashes = _coordinate_face_hashes(nodes, representative_faces)
    order = np.argsort(hashes, kind="quicksort")
    ordered = hashes[order]
    starts = np.r_[
        0, np.flatnonzero(ordered[1:] != ordered[:-1]) + 1
    ].astype(np.int64, copy=False)
    counts = np.diff(np.r_[starts, len(order)])
    suspicious = np.flatnonzero(counts > 1)
    if not len(suspicious):
        return

    excessive_examples: list[list[list[int]]] = []
    duplicate_same_material = 0
    coincident_unshared: list[list[list[int]]] = []
    maximum_multiplicity = 0
    for hash_group in suspicious:
        candidate_groups = order[
            int(starts[hash_group]) : int(starts[hash_group] + counts[hash_group])
        ]
        bits = _canonical_coordinate_bits(
            nodes, representative_faces[candidate_groups]
        )
        dtype = np.dtype([(f"v{index}", "<u8") for index in range(9)])
        keys = bits.view(dtype).reshape(-1)
        exact_order = np.argsort(
            keys,
            order=tuple(dtype.names or ()),
            kind="quicksort",
        )
        exact_bits = bits[exact_order]
        exact_starts = np.r_[
            0,
            np.flatnonzero(
                np.any(exact_bits[1:] != exact_bits[:-1], axis=1)
            )
            + 1,
        ]
        exact_counts = np.diff(np.r_[exact_starts, len(exact_order)])
        for exact_group in np.flatnonzero(exact_counts > 1):
            local = exact_order[
                int(exact_starts[exact_group]) : int(
                    exact_starts[exact_group] + exact_counts[exact_group]
                )
            ]
            source_group_ids = candidate_groups[local]
            occurrence_lists: list[np.ndarray] = []
            for source_group in source_group_ids:
                occurrence_lists.append(
                    np.flatnonzero(registry.group_ids == int(source_group))
                )
            occurrences = np.concatenate(occurrence_lists)
            multiplicity = int(len(occurrences))
            maximum_multiplicity = max(maximum_multiplicity, multiplicity)
            example = [
                [int(registry.materials[value]), int(value)]
                for value in occurrences[:20]
            ]
            if multiplicity > 2:
                excessive_examples.append(example)
            elif len(np.unique(registry.materials[occurrences])) < multiplicity:
                duplicate_same_material += 1
            else:
                coincident_unshared.append(example)
    if excessive_examples:
        _raise(
            "coordinate_face_multiplicity_exceeds_two",
            coordinate_faces=int(len(excessive_examples)),
            maximum_multiplicity=int(maximum_multiplicity),
            examples=excessive_examples[:20],
        )
    if duplicate_same_material:
        _raise(
            "duplicate_coordinate_face_within_material",
            coordinate_faces=int(duplicate_same_material),
        )
    if coincident_unshared:
        _raise(
            "coincident_coordinate_face_not_shared_cell_face",
            coordinate_faces=int(len(coincident_unshared)),
            examples=coincident_unshared[:20],
        )


def _build_source_face_registry(
    records: Mapping[int, _PreparedMaterialBoundary],
    nodes: np.ndarray,
) -> _SourceFaceRegistry:
    materials_order = sorted(map(int, records))
    offsets: dict[int, int] = {}
    material_arrays: list[np.ndarray] = []
    face_arrays: list[np.ndarray] = []
    cursor = 0
    for material in materials_order:
        record = records[material]
        offsets[material] = cursor
        material_arrays.append(
            np.full(len(record.source_faces), material, dtype=np.int8)
        )
        face_arrays.append(
            np.ascontiguousarray(record.source_faces, dtype=np.int32)
        )
        cursor += len(record.source_faces)
    materials = np.concatenate(material_arrays)
    global_faces = np.vstack(face_arrays).astype(np.int32, copy=False)
    canonical = np.sort(global_faces, axis=1)
    order, starts, counts, mode, bits = _group_canonical_index_faces(canonical)
    bad = np.flatnonzero(counts > 2)
    if len(bad):
        examples = [
            [
                [int(materials[value]), int(value)]
                for value in order[
                    int(starts[group]) : int(starts[group] + counts[group])
                ][:20]
            ]
            for group in bad[:20]
        ]
        _raise(
            "coordinate_face_multiplicity_exceeds_two",
            coordinate_faces=int(len(bad)),
            maximum_multiplicity=int(np.max(counts[bad])),
            examples=examples,
        )
    paired = np.flatnonzero(counts == 2)
    if len(paired):
        first = order[starts[paired]]
        second = order[starts[paired] + 1]
        same = materials[first] == materials[second]
        if np.any(same):
            _raise(
                "duplicate_coordinate_face_within_material",
                coordinate_faces=int(np.count_nonzero(same)),
            )
        # Actual shared cell faces must be oppositely oriented.  Integer
        # permutation parity is exact and avoids coordinate-normal rounding.
        def orientation(face_rows: np.ndarray) -> np.ndarray:
            return np.where(
                (
                    (face_rows[:, 0] > face_rows[:, 1]).astype(np.int8)
                    + (face_rows[:, 0] > face_rows[:, 2]).astype(np.int8)
                    + (face_rows[:, 1] > face_rows[:, 2]).astype(np.int8)
                )
                % 2
                == 0,
                1,
                -1,
            ).astype(np.int8)

        if np.any(orientation(global_faces[first]) == orientation(global_faces[second])):
            _raise(
                "source_coordinate_face_winding_mismatch",
                coordinate_faces=int(
                    np.count_nonzero(
                        orientation(global_faces[first])
                        == orientation(global_faces[second])
                    )
                ),
            )
    group_ids = np.empty(len(global_faces), dtype=np.int32)
    group_ids[order] = np.repeat(
        np.arange(len(starts), dtype=np.int32), counts
    )
    registry = _SourceFaceRegistry(
        materials=np.ascontiguousarray(materials, dtype=np.int8),
        global_faces=np.ascontiguousarray(global_faces, dtype=np.int32),
        group_ids=group_ids,
        group_counts=np.ascontiguousarray(counts, dtype=np.int32),
        representative_occurrences=np.ascontiguousarray(
            order[starts], dtype=np.int64
        ),
        occurrence_offsets=offsets,
        unique_faces=int(len(starts)),
        exterior_faces=int(np.count_nonzero(counts == 1)),
        internal_faces=int(np.count_nonzero(counts == 2)),
        key_mode=mode,
        bits_per_node=int(bits),
    )
    _audit_unshared_coordinate_faces(registry, nodes)
    return registry


def _shared_subdivide_parallel_abstract_edges(
    records: Mapping[int, _PreparedMaterialBoundary],
    nodes: np.ndarray,
    *,
    source_registry: _SourceFaceRegistry | None = None,
) -> tuple[
    dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]]],
    Mapping[str, object],
]:
    """Propagate every local split through all coordinate-face counterparts."""

    registry = source_registry or _build_source_face_registry(records, nodes)
    materials_order = sorted(map(int, records))
    split_masks: dict[int, np.ndarray] = {}
    occurrence_edge_ids: list[np.ndarray] = []
    occurrence_slots: list[np.ndarray] = []
    initial_parallel_objects = 0
    total_edge_objects = 0
    for material in materials_order:
        record = records[material]
        edge_count = int(record.face_edge_ids.max(initial=-1)) + 1
        mask = np.zeros(edge_count, dtype=bool)
        mask[record.initial_split_edge_ids] = True
        split_masks[material] = mask
        initial_parallel_objects += int(np.count_nonzero(mask))
        total_edge_objects += edge_count
        occurrence_edge_ids.append(record.face_edge_ids.reshape(-1))

        source_faces = record.source_faces
        sorted_faces = np.sort(source_faces, axis=1)
        directed_edges = source_faces[
            :, ((0, 1), (1, 2), (2, 0))
        ]
        canonical_edges = np.sort(directed_edges, axis=2)
        a = sorted_faces[:, 0, None]
        b = sorted_faces[:, 1, None]
        c = sorted_faces[:, 2, None]
        first = canonical_edges[:, :, 0]
        second = canonical_edges[:, :, 1]
        slots = np.full((len(source_faces), 3), -1, dtype=np.int8)
        slots[(first == a) & (second == b)] = 0
        slots[(first == a) & (second == c)] = 1
        slots[(first == b) & (second == c)] = 2
        if np.any(slots < 0):
            _raise("source_face_edge_slot_assignment_failed", material=material)
        occurrence_slots.append(slots.reshape(-1))

    all_edge_ids = np.concatenate(occurrence_edge_ids).astype(
        np.int32, copy=False
    )
    all_slots = np.concatenate(occurrence_slots).astype(np.int8, copy=False)
    edge_group_ids = np.repeat(registry.group_ids, 3).astype(
        np.int64, copy=False
    )
    edge_signatures = edge_group_ids * 3 + all_slots.astype(np.int64)
    requested = np.empty(3 * registry.unique_faces, dtype=bool)
    rounds = 0
    while True:
        rounds += 1
        selected_occurrences: list[np.ndarray] = []
        for material, edge_ids in zip(
            materials_order, occurrence_edge_ids, strict=True
        ):
            selected_occurrences.append(split_masks[material][edge_ids])
        selected = np.concatenate(selected_occurrences)
        requested.fill(False)
        np.logical_or.at(requested, edge_signatures, selected)
        desired = requested[edge_signatures]
        changed = 0
        edge_cursor = 0
        for material, edge_ids in zip(
            materials_order, occurrence_edge_ids, strict=True
        ):
            count = len(edge_ids)
            mask = split_masks[material]
            before = int(np.count_nonzero(mask))
            np.logical_or.at(
                mask,
                edge_ids,
                desired[edge_cursor : edge_cursor + count],
            )
            changed += int(np.count_nonzero(mask)) - before
            edge_cursor += count
        if changed == 0:
            break
        # Each productive round adds at least one finite abstract edge object.
        if rounds > max(total_edge_objects + 1, 2):
            _raise(
                "shared_subdivision_propagation_did_not_converge",
                rounds=int(rounds),
                edge_objects=int(total_edge_objects),
            )

    outputs: dict[
        int, tuple[np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]]
    ] = {}
    total_split_objects = 0
    total_affected_faces = 0
    for material in materials_order:
        record = records[material]
        split_ids = np.asarray(
            np.flatnonzero(split_masks[material]), dtype=np.int32
        )
        vertices, faces, output_sources, subdivision = (
            _subdivide_selected_abstract_edges(
                record.vertices,
                record.faces,
                record.face_edge_ids,
                split_ids,
                initial_parallel_coordinate_pairs=(
                    record.initial_parallel_coordinate_pairs
                ),
                initial_parallel_edge_objects=int(
                    len(record.initial_split_edge_ids)
                ),
                source_nodes=nodes,
                source_global_faces=record.source_faces,
            )
        )
        outputs[int(material)] = (
            vertices,
            faces,
            output_sources,
            subdivision,
        )
        total_split_objects += int(
            subdivision["shared_split_abstract_edge_objects"]
        )
        total_affected_faces += int(
            subdivision["locally_subdivided_source_faces"]
        )
    return outputs, {
        "coordinate_source_faces": int(registry.unique_faces),
        "exterior_coordinate_faces": int(registry.exterior_faces),
        "internal_coordinate_faces": int(registry.internal_faces),
        "coordinate_face_multiplicity_gt2": 0,
        "source_face_registry": registry.key_mode,
        "source_face_key_bits_per_node": int(registry.bits_per_node),
        "initial_parallel_abstract_edge_objects": int(
            initial_parallel_objects
        ),
        "shared_split_abstract_edge_objects": int(total_split_objects),
        "propagated_counterpart_edge_objects": int(
            total_split_objects - initial_parallel_objects
        ),
        "affected_source_face_occurrences": int(total_affected_faces),
        "propagation_rounds": int(rounds),
        "coordinate_face_counterparts_receive_identical_partition": True,
    }


def _output_subdivision_signatures(
    *,
    material: int,
    record: _PreparedMaterialBoundary,
    vertices: np.ndarray,
    faces: np.ndarray,
    output_sources: np.ndarray,
    nodes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Map each output child to an exact integer source/subdivision token.

    The seven possible points of the deterministic subdivision are the three
    canonical source vertices, three canonical edge midpoints and canonical
    face centroid.  A sorted triple of 3-bit point tokens uniquely identifies
    the coordinate triangle without allocating a float-bytes key.
    """

    signatures = np.empty(len(faces), dtype=np.uint16)
    orientation = np.empty(len(faces), dtype=np.int8)
    chunk_size = 100_000
    for start in range(0, len(faces), chunk_size):
        stop = min(start + chunk_size, len(faces))
        source_ids = np.asarray(output_sources[start:stop], dtype=np.int32)
        canonical_ids = np.sort(record.source_faces[source_ids], axis=1)
        source_points = nodes[canonical_ids]
        candidates = np.empty((stop - start, 7, 3), dtype=np.float64)
        candidates[:, :3] = source_points
        candidates[:, 3] = 0.5 * (
            source_points[:, 0] + source_points[:, 1]
        )
        candidates[:, 4] = 0.5 * (
            source_points[:, 0] + source_points[:, 2]
        )
        candidates[:, 5] = 0.5 * (
            source_points[:, 1] + source_points[:, 2]
        )
        candidates[:, 6] = source_points.sum(axis=1) / 3.0
        output_points = vertices[faces[start:stop]]
        matches = np.all(
            output_points[:, :, None, :] == candidates[:, None, :, :], axis=3
        )
        match_counts = matches.sum(axis=2)
        if np.any(match_counts != 1):
            _raise(
                "output_vertex_not_unique_subdivision_point",
                material=material,
                vertices=int(np.count_nonzero(match_counts != 1)),
            )
        tokens = np.argmax(matches, axis=2).astype(np.int8)
        canonical_tokens = np.sort(tokens, axis=1)
        if np.any(np.diff(canonical_tokens, axis=1) == 0):
            _raise("degenerate_output_subdivision_triangle", material=material)
        signatures[start:stop] = (
            canonical_tokens[:, 0].astype(np.uint16)
            | (canonical_tokens[:, 1].astype(np.uint16) << np.uint16(3))
            | (canonical_tokens[:, 2].astype(np.uint16) << np.uint16(6))
        )
        inversions = (
            (tokens[:, 0] > tokens[:, 1]).astype(np.int8)
            + (tokens[:, 0] > tokens[:, 2]).astype(np.int8)
            + (tokens[:, 1] > tokens[:, 2]).astype(np.int8)
        )
        orientation[start:stop] = np.where(
            inversions % 2 == 0, 1, -1
        ).astype(np.int8)

        source_oriented = nodes[record.source_faces[source_ids]]
        source_normals = np.cross(
            source_oriented[:, 1] - source_oriented[:, 0],
            source_oriented[:, 2] - source_oriented[:, 0],
        )
        output_normals = np.cross(
            output_points[:, 1] - output_points[:, 0],
            output_points[:, 2] - output_points[:, 0],
        )
        aligned = np.einsum("ij,ij->i", source_normals, output_normals)
        if np.any(aligned <= 0.0):
            _raise(
                "output_subdivision_winding_changed",
                material=material,
                faces=int(np.count_nonzero(aligned <= 0.0)),
            )
    return signatures, orientation


def _audit_shared_coordinate_triangles(
    records: Mapping[int, _PreparedMaterialBoundary],
    outputs: Mapping[
        int, tuple[np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]]
    ],
    nodes: np.ndarray,
    *,
    source_registry: _SourceFaceRegistry | None = None,
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...]]:
    """Prove output multiplicity/winding by numeric subdivision signatures."""

    registry = source_registry or _build_source_face_registry(records, nodes)
    maximum_area_error = 0.0
    signature_arrays: list[np.ndarray] = []
    material_arrays: list[np.ndarray] = []
    orientation_arrays: list[np.ndarray] = []
    expected_arrays: list[np.ndarray] = []
    exterior_output_faces = 0
    for material in sorted(map(int, records)):
        record = records[material]
        vertices, faces, output_sources, _subdivision = outputs[material]
        if output_sources.shape != (len(faces),):
            _raise("invalid_output_face_source_map", material=material)
        source_area = 0.5 * np.linalg.norm(
            np.cross(
                nodes[record.source_faces[:, 1]]
                - nodes[record.source_faces[:, 0]],
                nodes[record.source_faces[:, 2]]
                - nodes[record.source_faces[:, 0]],
            ),
            axis=1,
        )
        triangles = vertices[faces]
        output_area = 0.5 * np.linalg.norm(
            np.cross(
                triangles[:, 1] - triangles[:, 0],
                triangles[:, 2] - triangles[:, 0],
            ),
            axis=1,
        )
        covered = np.bincount(
            output_sources,
            weights=output_area,
            minlength=len(record.source_faces),
        )
        area_error = np.abs(covered - source_area)
        local_maximum = float(np.max(area_error, initial=0.0))
        local_tolerance = _AREA_RELATIVE_TOLERANCE * max(
            float(np.max(source_area, initial=0.0)), 1.0
        )
        if local_maximum > local_tolerance:
            _raise(
                "source_face_area_coverage_inexact",
                material=material,
                maximum_error_mm2=local_maximum,
                tolerance_mm2=local_tolerance,
            )
        maximum_area_error = max(maximum_area_error, local_maximum)
        child_codes, child_orientation = _output_subdivision_signatures(
            material=material,
            record=record,
            vertices=vertices,
            faces=faces,
            output_sources=output_sources,
            nodes=nodes,
        )
        occurrence_ids = (
            int(registry.occurrence_offsets[material]) + output_sources
        )
        group_ids = registry.group_ids[occurrence_ids].astype(
            np.uint64, copy=False
        )
        # Seven construction points require 9 bits for the sorted child code.
        signature_arrays.append(
            (group_ids << np.uint64(9)) | child_codes.astype(np.uint64)
        )
        material_arrays.append(
            np.full(len(faces), material, dtype=np.int8)
        )
        orientation_arrays.append(child_orientation)
        expected = registry.group_counts[group_ids.astype(np.int64)]
        expected_arrays.append(expected.astype(np.int8, copy=False))
        exterior_output_faces += int(np.count_nonzero(expected == 1))

    signatures = np.concatenate(signature_arrays)
    output_materials = np.concatenate(material_arrays)
    orientations = np.concatenate(orientation_arrays)
    expected_multiplicity = np.concatenate(expected_arrays)
    order = np.argsort(signatures, kind="quicksort")
    ordered = signatures[order]
    starts = np.r_[
        0, np.flatnonzero(ordered[1:] != ordered[:-1]) + 1
    ].astype(np.int64, copy=False)
    counts = np.diff(np.r_[starts, len(order)]).astype(np.int32, copy=False)
    bad_gt2 = np.flatnonzero(counts > 2)
    if len(bad_gt2):
        _raise(
            "output_coordinate_triangle_multiplicity_exceeds_two",
            coordinate_triangles=int(len(bad_gt2)),
            maximum_multiplicity=int(np.max(counts[bad_gt2])),
        )
    first_rows = order[starts]
    expected = expected_multiplicity[first_rows]
    mismatch = counts != expected
    counterpart_mismatches = int(np.count_nonzero(mismatch))
    if counterpart_mismatches:
        _raise(
            "coordinate_face_counterpart_partition_mismatch",
            coordinate_triangles=counterpart_mismatches,
        )
    singletons = counts == 1
    pairs = counts == 2
    exterior_singletons = int(np.count_nonzero(singletons))
    internal_pairs = int(np.count_nonzero(pairs))
    pair_first = order[starts[pairs]]
    pair_second = order[starts[pairs] + 1]
    same_material = output_materials[pair_first] == output_materials[pair_second]
    if np.any(same_material):
        _raise(
            "internal_coordinate_triangle_same_material",
            coordinate_triangles=int(np.count_nonzero(same_material)),
        )
    winding_bad = orientations[pair_first] == orientations[pair_second]
    if np.any(winding_bad):
        _raise(
            "internal_coordinate_triangle_winding_mismatch",
            coordinate_triangles=int(np.count_nonzero(winding_bad)),
        )
    if exterior_singletons != exterior_output_faces:
        _raise(
            "exterior_coordinate_triangle_accounting_failed",
            singletons=exterior_singletons,
            expected=int(exterior_output_faces),
        )
    low = np.minimum(
        output_materials[pair_first], output_materials[pair_second]
    ).astype(np.int16)
    high = np.maximum(
        output_materials[pair_first], output_materials[pair_second]
    ).astype(np.int16)
    pair_codes = low * 5 + high
    interfaces = tuple(
        {
            "name": f"F{int(code // 5)}__F{int(code % 5)}",
            "physical_materials": [int(code // 5), int(code % 5)],
            "faces": int(count),
            "exact_coordinate_triangles": True,
            "opposite_winding": True,
            "gap_mm": 0.0,
            "positive_overlap_mm3": 0.0,
        }
        for code, count in zip(
            *np.unique(pair_codes, return_counts=True), strict=True
        )
    )
    return {
        "unique_coordinate_triangles": int(len(starts)),
        "exterior_singletons": exterior_singletons,
        "internal_exact_pairs": internal_pairs,
        "multiplicity_gt2": 0,
        "counterpart_partition_mismatches": 0,
        "internal_same_material_failures": 0,
        "internal_opposite_winding_failures": 0,
        "maximum_source_face_area_error_mm2": float(maximum_area_error),
        "all_internal_exact_pair_opposite": True,
        "external_surface_coverage_exact": True,
        "output_registry": "source_face_group_plus_uint9_subdivision",
        "float_bytes_dictionary_entries": 0,
    }, interfaces


def _indexed_topology(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> tuple[np.ndarray, Mapping[str, object]]:
    directed = faces[:, ((0, 1), (1, 2), (2, 0))].reshape((-1, 2))
    canonical = np.sort(directed, axis=1)
    order = np.lexsort((canonical[:, 1], canonical[:, 0]))
    sorted_edges = canonical[order]
    starts = np.r_[
        0,
        np.flatnonzero(np.any(sorted_edges[1:] != sorted_edges[:-1], axis=1))
        + 1,
    ]
    counts = np.diff(np.r_[starts, len(order)])
    bad = np.flatnonzero(counts != 2)
    if len(bad):
        _raise(
            "output_edge_not_two_sided",
            count=int(len(bad)),
            examples=sorted_edges[starts[bad[:20]]].astype(int).tolist(),
        )
    first_halfedges = order[starts]
    second_halfedges = order[starts + 1]
    inconsistent = (
        (directed[first_halfedges, 0] != directed[second_halfedges, 1])
        | (directed[first_halfedges, 1] != directed[second_halfedges, 0])
    )
    if np.any(inconsistent):
        _raise(
            "output_edge_winding_inconsistent",
            count=int(np.count_nonzero(inconsistent)),
        )
    first_faces = first_halfedges // 3
    second_faces = second_halfedges // 3
    graph = sparse.coo_matrix(
        (
            np.ones(2 * len(first_faces), dtype=np.uint8),
            (
                np.concatenate((first_faces, second_faces)),
                np.concatenate((second_faces, first_faces)),
            ),
        ),
        shape=(len(faces), len(faces)),
    ).tocsr()
    component_count, components = connected_components(
        graph, directed=False, return_labels=True
    )
    triangles = vertices[faces]
    face_volumes = np.einsum(
        "ij,ij->i",
        triangles[:, 0],
        np.cross(triangles[:, 1], triangles[:, 2]),
    ) / 6.0
    component_volumes = np.bincount(
        components, weights=face_volumes, minlength=component_count
    )
    return components.astype(np.int32), {
        "indexed_edges": int(len(starts)),
        "edge_incidence_exactly_two": True,
        "consistent_winding": True,
        "closed_oriented_2_manifold": True,
        "surface_components": int(component_count),
        "positive_surface_components": int(
            np.count_nonzero(component_volumes > 1e-14)
        ),
        "negative_cavity_components": int(
            np.count_nonzero(component_volumes < -1e-14)
        ),
        "near_zero_surface_components": int(
            np.count_nonzero(np.abs(component_volumes) <= 1e-14)
        ),
        "minimum_component_signed_volume_mm3": float(
            np.min(component_volumes)
        ),
        "maximum_component_signed_volume_mm3": float(
            np.max(component_volumes)
        ),
        "signed_volume_mm3": float(component_volumes.sum()),
    }


def _duplicate_coordinate_faces(faces: np.ndarray) -> int:
    canonical = np.sort(faces, axis=1)
    order = np.lexsort((canonical[:, 2], canonical[:, 1], canonical[:, 0]))
    ordered = canonical[order]
    return int(
        np.count_nonzero(np.all(ordered[1:] == ordered[:-1], axis=1))
    )


def _finalize_material_boundary(
    materials: np.ndarray,
    tet_volumes: np.ndarray,
    prepared: _PreparedMaterialBoundary,
    output: tuple[
        np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]
    ],
) -> ManifoldMaterialPart:
    material = int(prepared.material)
    source_faces = prepared.source_faces
    owners = prepared.owners
    pairing = prepared.pairing
    link_record = prepared.vertex_link_split
    vertices, faces, output_sources, subdivision = output
    components, topology = _indexed_topology(vertices, faces)
    expected_volume = float(tet_volumes[materials == material].sum())
    output_volume = float(topology["signed_volume_mm3"])
    volume_error = abs(output_volume - expected_volume)
    if (
        not math.isfinite(output_volume)
        or output_volume <= 1e-14
        or volume_error
        > _VOLUME_RELATIVE_TOLERANCE * max(expected_volume, 1.0)
    ):
        _raise(
            "material_volume_mismatch",
            material=material,
            expected_cell_volume_mm3=expected_volume,
            signed_surface_volume_mm3=output_volume,
            volume_error_mm3=volume_error,
        )
    duplicate_faces = _duplicate_coordinate_faces(source_faces)
    if duplicate_faces:
        _raise(
            "duplicate_coordinate_faces",
            material=material,
            count=duplicate_faces,
        )
    contact_edges = int(pairing["geometric_self_contact_edges"])
    contact_vertices = int(link_record["geometric_self_contact_vertices"])
    contact_risk = bool(contact_edges or contact_vertices)
    metadata = {
        "schema": MATERIAL_MANIFOLD_SCHEMA,
        "physical_material": int(material),
        "physical_materials_only": True,
        "legacy_fullspectrum_ratios_used": False,
        "ratio_definitions": 0,
        "cycle_definitions": 0,
        "virtual_mix_definitions": 0,
        "painted_triangles": 0,
        "cell_count": int(np.count_nonzero(materials == material)),
        "source_faces": int(len(source_faces)),
        "output_faces": int(len(faces)),
        "source_coordinate_vertices": int(len(np.unique(source_faces))),
        "output_topological_vertices": int(len(vertices)),
        "source_triangles_and_winding_exact_before_local_subdivision": True,
        "piecewise_planar_surface_geometry_exact": True,
        "source_corner_coordinates_exact_source_nodes": True,
        "added_coordinates_exact_edge_midpoints_or_face_centroids": True,
        "duplicate_coordinate_faces": 0,
        "expected_cell_volume_mm3": expected_volume,
        "signed_surface_volume_mm3": output_volume,
        "volume_error_mm3": volume_error,
        "pairing": pairing,
        "vertex_link_split": link_record,
        "parallel_edge_subdivision": subdivision,
        "topology": topology,
        "transverse_self_intersections": 0,
        "self_intersection_basis": (
            "faces are subtriangles of a conforming non-overlapping "
            "tetrahedral complex; distinct faces meet only on common mesh "
            "subfaces, edges, or vertices"
        ),
        "geometric_self_contact_edge_count": contact_edges,
        "geometric_self_contact_vertex_count": contact_vertices,
        "coincident_geometry_contact_risk": contact_risk,
        "coincident_geometry_contact_policy": (
            "keep topologically separate indices; do not boolean-weld "
            "coincident edge or point contacts"
        ),
    }
    return ManifoldMaterialPart(
        vertices_mm=_immutable(vertices, np.float64),
        faces=_immutable(faces, np.int32),
        extruder=int(material),
        source_faces=_immutable(source_faces, np.int32),
        source_owner_cells=_immutable(owners, np.int32),
        output_face_source=_immutable(output_sources, np.int32),
        face_components=_immutable(components, np.int32),
        metadata=metadata,
    )


def _manifoldize_one(
    nodes: np.ndarray,
    tetrahedra: np.ndarray,
    materials: np.ndarray,
    tet_volumes: np.ndarray,
    material: int,
    source_faces: np.ndarray,
    owners: np.ndarray,
    index: _EdgeIncidenceIndex,
) -> ManifoldMaterialPart:
    """Backward-compatible private one-material diagnostic path."""

    prepared = _prepare_material_boundary(
        nodes,
        tetrahedra,
        materials,
        material,
        source_faces,
        owners,
        index,
    )
    output = _subdivide_parallel_abstract_edges(
        prepared.vertices,
        prepared.faces,
        prepared.face_edge_ids,
    )
    return _finalize_material_boundary(
        materials, tet_volumes, prepared, output
    )


def manifoldize_labeled_tetrahedra(
    nodes_mm: np.ndarray,
    tetrahedra: np.ndarray,
    cell_materials: np.ndarray,
) -> MaterialManifoldResult:
    """Extract exact, closed F1..F4 material boundaries from labelled cells.

    The caller guarantees that the cells form a conforming non-overlapping
    tetrahedral complex.  The function validates face/edge incidence and every
    output component, but deliberately does not perform an expensive general
    tetrahedron-overlap search.
    """

    nodes, tets, materials, tet_volumes = _validate_input(
        nodes_mm, tetrahedra, cell_materials
    )
    soups, _source_interfaces, complex_record = _surface_soups(
        nodes, tets, materials
    )
    index = _EdgeIncidenceIndex.build(tets)
    prepared = {
        int(material): _prepare_material_boundary(
            nodes,
            tets,
            materials,
            material,
            faces,
            owners,
            index,
        )
        for material, (faces, owners) in soups.items()
    }
    source_registry = _build_source_face_registry(prepared, nodes)
    outputs, shared_subdivision = (
        _shared_subdivide_parallel_abstract_edges(
            prepared, nodes, source_registry=source_registry
        )
    )
    coordinate_accounting, interfaces = _audit_shared_coordinate_triangles(
        prepared, outputs, nodes, source_registry=source_registry
    )
    parts = tuple(
        _finalize_material_boundary(
            materials,
            tet_volumes,
            record,
            outputs[material],
        )
        for material, record in prepared.items()
    )
    source_volume = float(tet_volumes.sum())
    output_volume = float(
        sum(part.metadata["signed_surface_volume_mm3"] for part in parts)
    )
    volume_error = abs(output_volume - source_volume)
    if volume_error > _VOLUME_RELATIVE_TOLERANCE * max(source_volume, 1.0):
        _raise(
            "total_material_volume_mismatch",
            source_volume_mm3=source_volume,
            output_volume_mm3=output_volume,
            volume_error_mm3=volume_error,
        )
    expected_faces = int(complex_record["exterior_faces"]) + 2 * int(
        complex_record["material_interface_faces"]
    )
    source_face_count = sum(len(part.source_faces) for part in parts)
    if source_face_count != expected_faces:
        _raise(
            "material_face_accounting_failed",
            source_faces=int(source_face_count),
            expected_faces=int(expected_faces),
        )
    contact_edges = sum(
        int(part.metadata["geometric_self_contact_edge_count"])
        for part in parts
    )
    contact_vertices = sum(
        int(part.metadata["geometric_self_contact_vertex_count"])
        for part in parts
    )
    metadata = {
        "schema": MATERIAL_MANIFOLD_SCHEMA,
        "physical_materials_only": True,
        "physical_material_count": int(len(parts)),
        "physical_materials": [int(part.extruder) for part in parts],
        "legacy_fullspectrum_ratios_used": False,
        "ratio_definitions": 0,
        "cycle_definitions": 0,
        "virtual_mix_definitions": 0,
        "painted_triangles": 0,
        "input_cell_materials_changed": False,
        "input_cells": int(len(tets)),
        "cell_complex": complex_record,
        "shared_subdivision": shared_subdivision,
        "coordinate_triangle_accounting": coordinate_accounting,
        "source_volume_mm3": source_volume,
        "output_volume_mm3": output_volume,
        "volume_error_mm3": volume_error,
        "source_material_boundary_faces": int(source_face_count),
        "output_subtriangles": int(sum(len(part.faces) for part in parts)),
        "all_closed_oriented_2_manifold": True,
        "all_vertex_links_single_cycles": True,
        "all_piecewise_planar_geometry_exact": True,
        "all_internal_coordinate_triangles_exact_pair_opposite": True,
        "external_surface_coverage_exact": True,
        "shared_interface_partition_exact": True,
        "exact_touch_interfaces": int(len(interfaces)),
        "positive_overlap_mm3": 0.0,
        "gap_mm": 0.0,
        "transverse_self_intersections": 0,
        "geometric_self_contact_edge_count": int(contact_edges),
        "geometric_self_contact_vertex_count": int(contact_vertices),
        "coincident_geometry_contact_risk": bool(
            contact_edges or contact_vertices
        ),
        "coincident_geometry_contact_policy": (
            "preserve exact geometry with disjoint topology; writer and "
            "slicer must not weld coincident contacts"
        ),
        "parts": {
            str(part.extruder): part.metadata for part in parts
        },
    }
    return MaterialManifoldResult(
        parts=parts,
        source_volume_mm3=source_volume,
        output_volume_mm3=output_volume,
        cell_materials=_immutable(materials, np.int8),
        interfaces=interfaces,
        metadata=metadata,
    )


__all__ = [
    "MATERIAL_MANIFOLD_SCHEMA",
    "ManifoldMaterialPart",
    "MaterialManifoldError",
    "MaterialManifoldResult",
    "manifoldize_labeled_tetrahedra",
]
