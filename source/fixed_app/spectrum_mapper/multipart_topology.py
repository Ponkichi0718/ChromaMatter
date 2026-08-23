"""Conservative exact-coordinate normalization for multipart glTF surfaces.

Some static glTF exporters retain UV/texture seam vertices and emit triangles
which collapse only after those vertices are identified by position.  A
multipart asset cannot use the single-mesh seam weld because part identity is
authoritative.  This module normalizes each logical part independently:

* coordinates never move and parts never share indices;
* only faces with a repeated exact-coordinate corner are removed;
* ordinary geometric half-edges must pair in reversed directions;
* balanced high-incidence self-contact edges are separated into uniquely
  proven smooth sectors; and
* vertex-link components receive separate indices at coincident contacts.

True boundary edges remain boundaries for the existing strict tiny-hole path.
Any odd, unbalanced, same-winding, collinear, or geometrically ambiguous case
fails closed without returning partial output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from scipy import sparse
from scipy.optimize import linear_sum_assignment
from scipy.sparse.csgraph import connected_components


MULTIPART_TOPOLOGY_SCHEMA = "obj-adjuster.multipart-exact-topology.v1"
# The proof below deliberately uses a dense assignment matrix and verifies
# the second-best solution.  Real exported surface contacts use incidence 4;
# bounding the exceptional case keeps adversarial inputs fail-closed before
# any quadratic allocation.
_MAX_GEOMETRIC_EDGE_INCIDENCE = 16
_FLOAT32_SECTOR_MARGIN_FACTOR = 64.0
# Normalization expands every triangle into three half-edge/corner records and
# then builds several sorting and sparse-connectivity work arrays.  Keep this
# proof bounded per logical part so a valid-but-huge single-node glTF cannot
# exhaust the desktop process before the normal target-face reduction runs.
# The limits remain above the largest part in the real multipart acceptance
# fixture (about 592k faces / 296k referenced vertices).
_MAX_PART_FACE_COUNT = 650_000
_MAX_PART_VERTEX_COUNT = 750_000


class MultipartTopologyError(RuntimeError):
    """Stable fail-closed error from exact multipart normalization."""

    def __init__(self, code: str, **details: object) -> None:
        self.code = str(code)
        self.details = dict(details)
        super().__init__(self.code)


def _raise(code: str, **details: object) -> None:
    raise MultipartTopologyError(code, **details)


@dataclass(frozen=True, slots=True)
class MultipartTopologyResult:
    vertices: np.ndarray
    faces: np.ndarray
    colors: np.ndarray
    output_face_source: np.ndarray
    metadata: Mapping[str, object]


def _topology(faces: np.ndarray, vertex_count: int) -> dict[str, int | bool]:
    values = np.asarray(faces, dtype=np.int64)
    if not len(values):
        return {
            "unique_edges": 0,
            "boundary_edges": 0,
            "nonmanifold_edges": 0,
            "inconsistent_winding_edges": 0,
            "watertight": False,
        }
    directed = values[:, ((0, 1), (1, 2), (2, 0))].reshape((-1, 2))
    low = np.minimum(directed[:, 0], directed[:, 1])
    high = np.maximum(directed[:, 0], directed[:, 1])
    keys = low * np.int64(vertex_count) + high
    direction = directed[:, 0] == low
    order = np.argsort(keys, kind="stable")
    _unique, starts, counts = np.unique(
        keys[order], return_index=True, return_counts=True
    )
    paired = counts == 2
    inconsistent = int(
        np.count_nonzero(
            direction[order[starts[paired]]]
            == direction[order[starts[paired] + 1]]
        )
    )
    boundary = int(np.count_nonzero(counts == 1))
    nonmanifold = int(np.count_nonzero(counts > 2))
    return {
        "unique_edges": int(len(counts)),
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "inconsistent_winding_edges": inconsistent,
        "watertight": boundary == 0 and nonmanifold == 0,
    }


def _pair(mates: np.ndarray, edges: np.ndarray, first: int, second: int) -> None:
    if mates[first] >= 0 or mates[second] >= 0:
        _raise("halfedge_paired_twice")
    if not (
        int(edges[first, 0]) == int(edges[second, 1])
        and int(edges[first, 1]) == int(edges[second, 0])
    ):
        _raise("halfedge_winding_mismatch")
    mates[first] = second
    mates[second] = first


def _unique_smooth_assignment(
    position_values: np.ndarray,
    edges: np.ndarray,
    third_vertices: np.ndarray,
    halfedges: np.ndarray,
) -> tuple[list[tuple[int, int]], float, float]:
    """Return the unique minimum-dihedral reversed pairing or fail closed."""

    ids = np.asarray(halfedges, dtype=np.int64)
    low = min(int(edges[ids[0], 0]), int(edges[ids[0], 1]))
    high = max(int(edges[ids[0], 0]), int(edges[ids[0], 1]))
    forward = ids[edges[ids, 0] == low]
    reverse = ids[edges[ids, 0] == high]
    if len(forward) != len(reverse) or not len(forward):
        _raise(
            "unbalanced_high_incidence_edge",
            incidence=int(len(ids)),
            forward=int(len(forward)),
            reverse=int(len(reverse)),
        )
    if len(forward) == 1:
        return [(int(forward[0]), int(reverse[0]))], float("inf"), 0.0

    first = np.asarray(position_values[low], dtype=np.float64)
    axis = np.asarray(position_values[high], dtype=np.float64) - first
    axis_length = float(np.linalg.norm(axis))
    if not np.isfinite(axis_length) or axis_length <= 0.0:
        _raise("collapsed_geometric_edge")
    axis /= axis_length

    def radial(selected: np.ndarray) -> np.ndarray:
        values = (
            np.asarray(position_values[third_vertices[selected]], dtype=np.float64)
            - first
        )
        values -= np.outer(values @ axis, axis)
        lengths = np.linalg.norm(values, axis=1)
        if np.any(~np.isfinite(lengths) | (lengths <= 0.0)):
            _raise("collinear_edge_sector")
        return values / lengths[:, None]

    forward_radial = radial(forward)
    reverse_radial = radial(reverse)
    # 1-dot is monotonic with unsigned dihedral angle and remains stable near
    # zero, where acos loses useful separation.  No coordinate is changed.
    costs = 1.0 - np.clip(
        forward_radial @ reverse_radial.T, -1.0, 1.0
    )
    rows, columns = linear_sum_assignment(costs)
    best = float(costs[rows, columns].sum())
    if not np.isfinite(best):
        _raise("nonfinite_sector_assignment")

    alternative = float("inf")
    for row, column in zip(rows, columns, strict=True):
        trial = costs.copy()
        trial[int(row), int(column)] = np.inf
        trial_rows, trial_columns = linear_sum_assignment(trial)
        trial_cost = float(trial[trial_rows, trial_columns].sum())
        alternative = min(alternative, trial_cost)
    scale = max(1.0, abs(best), abs(alternative) if np.isfinite(alternative) else 1.0)
    tolerance = max(
        np.finfo(np.float64).eps * 4096.0 * scale * len(rows),
        np.finfo(np.float32).eps
        * _FLOAT32_SECTOR_MARGIN_FACTOR
        * len(rows),
    )
    margin = alternative - best
    if not np.isfinite(margin) or margin <= tolerance:
        _raise(
            "ambiguous_high_incidence_edge_sectors",
            incidence=int(len(ids)),
            best_cost=best,
            alternative_cost=alternative,
        )
    return (
        [
            (int(forward[int(row)]), int(reverse[int(column)]))
            for row, column in zip(rows, columns, strict=True)
        ],
        float(margin),
        float(tolerance),
    )


def _halfedge_mates(
    position_values: np.ndarray,
    coordinate_faces: np.ndarray,
) -> tuple[np.ndarray, Mapping[str, object]]:
    faces = np.asarray(coordinate_faces, dtype=np.int64)
    edges = faces[:, ((0, 1), (1, 2), (2, 0))].reshape((-1, 2))
    third = faces[:, (2, 0, 1)].reshape(-1)
    low = np.minimum(edges[:, 0], edges[:, 1])
    high = np.maximum(edges[:, 0], edges[:, 1])
    keys = low * np.int64(len(position_values)) + high
    order = np.argsort(keys, kind="stable")
    _unique, starts, counts = np.unique(
        keys[order], return_index=True, return_counts=True
    )
    mates = np.full(len(edges), -1, dtype=np.int64)

    paired_starts = starts[counts == 2]
    first = order[paired_starts]
    second = order[paired_starts + 1]
    reversed_pair = (
        (edges[first, 0] == edges[second, 1])
        & (edges[first, 1] == edges[second, 0])
    )
    if np.any(~reversed_pair):
        _raise(
            "same_direction_two_sided_edges",
            count=int(np.count_nonzero(~reversed_pair)),
        )
    mates[first] = second
    mates[second] = first

    high_mask = counts > 2
    if np.any(counts[high_mask] > _MAX_GEOMETRIC_EDGE_INCIDENCE):
        _raise(
            "excessive_high_incidence_edge",
            count=int(
                np.count_nonzero(
                    counts[high_mask] > _MAX_GEOMETRIC_EDGE_INCIDENCE
                )
            ),
            maximum_incidence=int(counts[high_mask].max(initial=0)),
            supported_maximum=int(_MAX_GEOMETRIC_EDGE_INCIDENCE),
        )
    if np.any((counts[high_mask] % 2) != 0):
        _raise(
            "odd_high_incidence_edges",
            count=int(np.count_nonzero((counts[high_mask] % 2) != 0)),
            maximum_incidence=int(counts[high_mask].max(initial=0)),
        )

    high_incidence_edges = 0
    exact_counterpart_pairs = 0
    smooth_sector_pairs = 0
    minimum_assignment_margin = float("inf")
    maximum_required_assignment_margin = 0.0
    maximum_incidence = int(counts.max(initial=0))
    for start, count in zip(starts[high_mask], counts[high_mask], strict=True):
        selected = order[int(start) : int(start + count)]
        direction = edges[selected, 0] == low[selected]
        if int(np.count_nonzero(direction)) * 2 != int(count):
            _raise(
                "unbalanced_high_incidence_edge",
                incidence=int(count),
                forward=int(np.count_nonzero(direction)),
                reverse=int(np.count_nonzero(~direction)),
            )
        high_incidence_edges += 1
        remaining: list[int] = []
        third_order = np.argsort(third[selected], kind="stable")
        ordered_selected = selected[third_order]
        _third, third_starts, third_counts = np.unique(
            third[ordered_selected], return_index=True, return_counts=True
        )
        for third_start, third_count in zip(
            third_starts, third_counts, strict=True
        ):
            group = ordered_selected[
                int(third_start) : int(third_start + third_count)
            ]
            if int(third_count) == 1:
                remaining.append(int(group[0]))
                continue
            if int(third_count) != 2:
                _raise(
                    "ambiguous_coincident_face_multiplicity",
                    multiplicity=int(third_count),
                )
            left, right = map(int, group)
            if not (
                int(edges[left, 0]) == int(edges[right, 1])
                and int(edges[left, 1]) == int(edges[right, 0])
            ):
                _raise("same_direction_coincident_faces")
            _pair(mates, edges, left, right)
            exact_counterpart_pairs += 1
        if remaining:
            if len(remaining) % 2:
                _raise(
                    "odd_unassigned_edge_sectors",
                    count=int(len(remaining)),
                )
            pairs, margin, required_margin = _unique_smooth_assignment(
                position_values,
                edges,
                third,
                np.asarray(remaining, dtype=np.int64),
            )
            for left, right in pairs:
                _pair(mates, edges, left, right)
            smooth_sector_pairs += len(pairs)
            minimum_assignment_margin = min(
                minimum_assignment_margin, margin
            )
            maximum_required_assignment_margin = max(
                maximum_required_assignment_margin, required_margin
            )

    expected_unpaired = int(np.count_nonzero(counts == 1))
    if int(np.count_nonzero(mates < 0)) != expected_unpaired:
        _raise(
            "halfedge_accounting_failed",
            expected_boundary_halfedges=expected_unpaired,
            actual_unpaired_halfedges=int(np.count_nonzero(mates < 0)),
        )
    return mates, {
        "geometric_edges": int(len(starts)),
        "geometric_boundary_edges": expected_unpaired,
        "high_incidence_geometric_edges": int(high_incidence_edges),
        "maximum_geometric_edge_incidence": maximum_incidence,
        "exact_counterpart_sector_pairs": int(exact_counterpart_pairs),
        "smooth_sector_pairs": int(smooth_sector_pairs),
        "minimum_unique_assignment_margin": (
            None
            if not np.isfinite(minimum_assignment_margin)
            else float(minimum_assignment_margin)
        ),
        "maximum_required_assignment_margin": float(
            maximum_required_assignment_margin
        ),
        "all_paired_halfedges_reversed": True,
    }


def _split_vertex_links(
    source_vertices: np.ndarray,
    source_faces: np.ndarray,
    source_colors: np.ndarray,
    coordinate_faces: np.ndarray,
    mates: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]]:
    corner_count = len(source_faces) * 3
    halfedge_ids = np.arange(len(mates), dtype=np.int64)
    paired = halfedge_ids[(mates >= 0) & (halfedge_ids < mates)]
    partners = mates[paired]
    first_faces, first_local = np.divmod(paired, 3)
    second_faces, second_local = np.divmod(partners, 3)
    first_start = first_faces * 3 + first_local
    first_end = first_faces * 3 + ((first_local + 1) % 3)
    second_start = second_faces * 3 + second_local
    second_end = second_faces * 3 + ((second_local + 1) % 3)
    left = np.concatenate((first_start, first_end))
    right = np.concatenate((second_end, second_start))
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
    # Count the corner-link multigraph before CSR coalesces parallel arcs.
    # A two-triangle closed sheet legitimately connects the same two corners
    # through both incident surface edges and therefore has degree two, not
    # one, at each corner.
    degrees = np.bincount(
        np.concatenate((left, right)), minlength=corner_count
    ).astype(np.int32, copy=False)
    if np.any(degrees > 2):
        _raise(
            "branched_vertex_link",
            corners=int(np.count_nonzero(degrees > 2)),
        )
    sizes = np.bincount(labels, minlength=component_count)
    degree_zero = np.bincount(
        labels[degrees == 0], minlength=component_count
    )
    degree_one = np.bincount(
        labels[degrees == 1], minlength=component_count
    )
    valid = (
        ((degree_one == 0) & (degree_zero == 0))
        | ((degree_one == 2) & (degree_zero == 0))
        | ((sizes == 1) & (degree_zero == 1))
    )
    if np.any(~valid):
        _raise(
            "invalid_vertex_link_component",
            count=int(np.count_nonzero(~valid)),
        )

    corner_positions = np.asarray(coordinate_faces, dtype=np.int64).reshape(-1)
    minimum_position = np.full(
        component_count, np.iinfo(np.int64).max, dtype=np.int64
    )
    maximum_position = np.full(component_count, -1, dtype=np.int64)
    np.minimum.at(minimum_position, labels, corner_positions)
    np.maximum.at(maximum_position, labels, corner_positions)
    if not np.array_equal(minimum_position, maximum_position):
        _raise("vertex_link_joined_distinct_coordinates")

    source_corner_vertices = np.asarray(source_faces, dtype=np.int64).reshape(-1)
    minimum_source = np.full(
        component_count, np.iinfo(np.int64).max, dtype=np.int64
    )
    minimum_corner = np.full(
        component_count, np.iinfo(np.int64).max, dtype=np.int64
    )
    np.minimum.at(minimum_source, labels, source_corner_vertices)
    np.minimum.at(
        minimum_corner, labels, np.arange(corner_count, dtype=np.int64)
    )
    component_order = np.lexsort((minimum_corner, minimum_source))
    remap = np.empty(component_count, dtype=np.int32)
    remap[component_order] = np.arange(component_count, dtype=np.int32)
    output_faces = remap[labels].reshape((-1, 3)).astype(np.int32)
    if np.any(np.diff(np.sort(output_faces, axis=1), axis=1) == 0):
        _raise("repeated_output_face_vertex")
    output_vertices = np.asarray(
        source_vertices[minimum_source[component_order]], dtype=np.float64
    ).copy()

    # Average each distinct source vertex once per abstract vertex.  This
    # avoids tessellation-weighted colour shifts while retaining the existing
    # single-mesh seam-weld colour contract.
    pair_keys = labels.astype(np.int64) * np.int64(len(source_vertices))
    pair_keys += source_corner_vertices
    unique_pairs = np.unique(pair_keys)
    pair_components = unique_pairs // np.int64(len(source_vertices))
    pair_sources = unique_pairs % np.int64(len(source_vertices))
    colour_sums = np.zeros((component_count, 3), dtype=np.float64)
    np.add.at(colour_sums, pair_components, source_colors[pair_sources])
    colour_counts = np.bincount(
        pair_components, minlength=component_count
    ).astype(np.float64)
    output_colors = (
        colour_sums / colour_counts[:, None]
    )[component_order]
    source_adjustment = np.abs(
        source_colors[pair_sources]
        - (colour_sums / colour_counts[:, None])[pair_components]
    )

    if not np.array_equal(
        output_vertices[output_faces], source_vertices[source_faces]
    ):
        _raise("face_coordinates_changed")
    return output_vertices, output_faces, output_colors, {
        "vertex_link_components": int(component_count),
        "closed_vertex_links": int(
            np.count_nonzero((degree_one == 0) & (degree_zero == 0))
        ),
        "open_vertex_links": int(
            np.count_nonzero(
                ((degree_one == 2) & (degree_zero == 0))
                | ((sizes == 1) & (degree_zero == 1))
            )
        ),
        "changed_source_vertex_colors": int(
            np.count_nonzero(np.any(source_adjustment > 1.0e-12, axis=1))
        ),
        "maximum_vertex_color_adjustment": float(
            source_adjustment.max(initial=0.0)
        ),
    }


def normalize_multipart_part(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    *,
    allow_color_merge: bool = False,
) -> MultipartTopologyResult:
    """Normalize one glTF node without moving geometry or crossing parts."""

    source_vertices = np.asarray(vertices, dtype=np.float64)
    source_faces = np.asarray(faces, dtype=np.int32)
    source_colors = np.asarray(colors, dtype=np.float64)
    if source_vertices.ndim != 2 or source_vertices.shape[1:] != (3,):
        _raise("invalid_vertices", shape=tuple(source_vertices.shape))
    if source_faces.ndim != 2 or source_faces.shape[1:] != (3,):
        _raise("invalid_faces", shape=tuple(source_faces.shape))
    if source_colors.shape != (len(source_vertices), 3):
        _raise("invalid_colors", shape=tuple(source_colors.shape))
    if not len(source_vertices) or not len(source_faces):
        _raise("empty_part")
    if (
        len(source_faces) > _MAX_PART_FACE_COUNT
        or len(source_vertices) > _MAX_PART_VERTEX_COUNT
    ):
        _raise(
            "normalization_work_budget_exceeded",
            source_faces=int(len(source_faces)),
            source_vertices=int(len(source_vertices)),
            maximum_faces=int(_MAX_PART_FACE_COUNT),
            maximum_vertices=int(_MAX_PART_VERTEX_COUNT),
        )
    if not np.isfinite(source_vertices).all() or not np.isfinite(
        source_colors
    ).all():
        _raise("nonfinite_input")
    if int(source_faces.min(initial=0)) < 0 or int(
        source_faces.max(initial=-1)
    ) >= len(source_vertices):
        _raise("face_index_out_of_range")

    position_values, position_inverse, position_counts = np.unique(
        source_vertices,
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    coordinate_faces_all = position_inverse[source_faces]
    sorted_coordinates = np.sort(coordinate_faces_all, axis=1)
    collapsed = (
        (sorted_coordinates[:, 0] == sorted_coordinates[:, 1])
        | (sorted_coordinates[:, 1] == sorted_coordinates[:, 2])
    )
    output_face_source = np.flatnonzero(~collapsed).astype(np.int32)
    if not len(output_face_source):
        _raise("all_faces_collapsed")
    kept_faces = source_faces[output_face_source]
    coordinate_faces = coordinate_faces_all[output_face_source]
    referenced_source_vertices = int(np.unique(source_faces).size)
    kept_source_vertices = int(np.unique(kept_faces).size)
    referenced_positions = int(np.unique(coordinate_faces_all).size)
    kept_positions = int(np.unique(coordinate_faces).size)

    triangles = source_vertices[kept_faces]
    twice_areas = np.linalg.norm(
        np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        ),
        axis=1,
    )
    noncollapsed_degenerate = ~np.isfinite(twice_areas) | (
        twice_areas <= 0.0
    )
    if np.any(noncollapsed_degenerate):
        _raise(
            "noncollapsed_degenerate_faces",
            count=int(np.count_nonzero(noncollapsed_degenerate)),
        )

    mates, edge_record = _halfedge_mates(
        position_values, coordinate_faces
    )
    (
        output_vertices,
        output_faces,
        output_colors,
        link_record,
    ) = _split_vertex_links(
        source_vertices,
        kept_faces,
        source_colors,
        coordinate_faces,
        mates,
    )
    if (
        not allow_color_merge
        and int(link_record["changed_source_vertex_colors"]) > 0
    ):
        _raise(
            "authored_vertex_color_seam",
            changed_source_vertex_colors=int(
                link_record["changed_source_vertex_colors"]
            ),
            maximum_vertex_color_adjustment=float(
                link_record["maximum_vertex_color_adjustment"]
            ),
        )
    after = _topology(output_faces, len(output_vertices))
    if int(after["nonmanifold_edges"]) or int(
        after["inconsistent_winding_edges"]
    ):
        _raise("normalized_topology_invalid", topology=after)
    expected_boundary = int(edge_record["geometric_boundary_edges"])
    if int(after["boundary_edges"]) != expected_boundary:
        _raise(
            "normalized_boundary_mismatch",
            expected=expected_boundary,
            actual=int(after["boundary_edges"]),
        )
    if len(output_faces) != len(output_face_source):
        _raise("face_source_map_length_mismatch")

    return MultipartTopologyResult(
        vertices=np.ascontiguousarray(output_vertices, dtype=np.float64),
        faces=np.ascontiguousarray(output_faces, dtype=np.int32),
        colors=np.ascontiguousarray(output_colors, dtype=np.float64),
        output_face_source=np.ascontiguousarray(
            output_face_source, dtype=np.int32
        ),
        metadata={
            "schema": MULTIPART_TOPOLOGY_SCHEMA,
            "method": "exact_coordinate_sector_split",
            "source_vertices": int(len(source_vertices)),
            "source_faces": int(len(source_faces)),
            "output_vertices": int(len(output_vertices)),
            "output_faces": int(len(output_faces)),
            "exact_coordinate_positions": int(len(position_values)),
            "referenced_source_vertices": referenced_source_vertices,
            "kept_source_vertices": kept_source_vertices,
            "kept_exact_coordinate_positions": kept_positions,
            "input_unreferenced_vertices": int(
                len(source_vertices) - referenced_source_vertices
            ),
            "collapsed_only_source_vertices": int(
                referenced_source_vertices - kept_source_vertices
            ),
            "collapsed_only_exact_positions": int(
                referenced_positions - kept_positions
            ),
            "exact_coordinate_vertex_merges": int(
                kept_source_vertices - kept_positions
            ),
            "sector_split_vertices": int(
                len(output_vertices) - kept_positions
            ),
            "net_vertex_reduction": int(
                len(source_vertices) - len(output_vertices)
            ),
            "coincident_vertex_excess": int(
                len(source_vertices) - len(position_values)
            ),
            "coincident_position_groups": int(
                np.count_nonzero(position_counts > 1)
            ),
            "removed_collapsed_faces": int(np.count_nonzero(collapsed)),
            "removed_face_rule": "repeated_exact_coordinate_after_remap",
            "noncollapsed_degenerate_faces": 0,
            "face_order_preserved": True,
            "output_face_source_map": "stable_source_filter",
            "geometry_coordinates_preserved": True,
            "part_identity_preserved": True,
            "edge_pairing": dict(edge_record),
            "vertex_links": dict(link_record),
            "after": after,
        },
    )


__all__ = [
    "MULTIPART_TOPOLOGY_SCHEMA",
    "MultipartTopologyError",
    "MultipartTopologyResult",
    "normalize_multipart_part",
]
