from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pymeshlab as ml
import trimesh
from mapbox_earcut import triangulate_float64
from scipy.spatial import cKDTree
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import polylabel


class AssemblyError(RuntimeError):
    pass


@dataclass(frozen=True)
class BoundaryLoop:
    part_id: int
    loop_id: int
    vertex_ids: np.ndarray
    points_unit: np.ndarray
    center_unit: np.ndarray
    perimeter_unit: float
    span_unit: float
    adjacent_face_ids: np.ndarray


@dataclass(frozen=True)
class SeamPair:
    seam_id: int
    first: BoundaryLoop
    second: BoundaryLoop
    match_rms_unit: float
    match_max_unit: float


def _edge_topology(faces: np.ndarray, vertex_count: int) -> dict[str, int | bool]:
    faces = np.asarray(faces, dtype=np.int64)
    if not len(faces):
        return {
            "unique_edges": 0,
            "boundary_edges": 0,
            "nonmanifold_edges": 0,
            "inconsistent_winding_edges": 0,
            "watertight": False,
        }
    directed = np.vstack(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])
    )
    lo = np.minimum(directed[:, 0], directed[:, 1])
    hi = np.maximum(directed[:, 0], directed[:, 1])
    key = lo * np.int64(vertex_count) + hi
    direction = np.where(directed[:, 0] == lo, 1, -1).astype(np.int8)
    order = np.argsort(key)
    key = key[order]
    direction = direction[order]
    _, start, counts = np.unique(key, return_index=True, return_counts=True)
    paired = counts == 2
    inconsistent = int(
        np.count_nonzero(
            direction[start[paired]] == direction[start[paired] + 1]
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


def _boundary_edges_with_face_ids(
    faces: np.ndarray,
    vertex_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    faces = np.asarray(faces, dtype=np.int64)
    if not len(faces):
        return (
            np.empty((0, 2), dtype=np.int32),
            np.empty(0, dtype=np.int32),
        )
    directed = np.vstack(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])
    )
    face_ids = np.tile(np.arange(len(faces), dtype=np.int32), 3)
    lo = np.minimum(directed[:, 0], directed[:, 1])
    hi = np.maximum(directed[:, 0], directed[:, 1])
    key = lo * np.int64(vertex_count) + hi
    order = np.argsort(key)
    key = key[order]
    lo = lo[order]
    hi = hi[order]
    face_ids = face_ids[order]
    _, start, counts = np.unique(key, return_index=True, return_counts=True)
    boundary = counts == 1
    return (
        np.column_stack((lo[start[boundary]], hi[start[boundary]])).astype(
            np.int32
        ),
        face_ids[start[boundary]].astype(np.int32),
    )


def _boundary_edges(faces: np.ndarray, vertex_count: int) -> np.ndarray:
    return _boundary_edges_with_face_ids(faces, vertex_count)[0]


def _ordered_boundary_components(edges: np.ndarray) -> list[np.ndarray]:
    adjacency: dict[int, list[int]] = {}
    for left, right in np.asarray(edges, dtype=np.int64):
        adjacency.setdefault(int(left), []).append(int(right))
        adjacency.setdefault(int(right), []).append(int(left))
    remaining = set(adjacency)
    loops: list[np.ndarray] = []
    while remaining:
        start = min(remaining)
        component: list[int] = []
        stack = [start]
        remaining.remove(start)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in adjacency[current]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
        if any(len(adjacency[vertex]) != 2 for vertex in component):
            continue
        ordered = [min(component)]
        previous = -1
        current = ordered[0]
        for _ in range(len(component) - 1):
            candidates = [
                value for value in adjacency[current] if value != previous
            ]
            if not candidates:
                break
            next_vertex = candidates[0]
            if next_vertex == ordered[0]:
                break
            ordered.append(next_vertex)
            previous, current = current, next_vertex
        if len(ordered) == len(component):
            loops.append(np.asarray(ordered, dtype=np.int32))
    loops.sort(key=len, reverse=True)
    return loops


def find_boundary_loops(
    part_id: int,
    vertices: np.ndarray,
    faces: np.ndarray,
) -> list[BoundaryLoop]:
    vertices = np.asarray(vertices, dtype=np.float64)
    edges, edge_face_ids = _boundary_edges_with_face_ids(
        faces, len(vertices)
    )
    face_by_edge = {
        int(left) * len(vertices) + int(right): int(face_id)
        for (left, right), face_id in zip(edges, edge_face_ids, strict=True)
    }
    result: list[BoundaryLoop] = []
    for loop_id, vertex_ids in enumerate(_ordered_boundary_components(edges)):
        points = vertices[vertex_ids]
        closed = np.vstack((points, points[:1]))
        perimeter = float(np.linalg.norm(np.diff(closed, axis=0), axis=1).sum())
        next_ids = np.roll(vertex_ids, -1)
        adjacent_face_ids = np.unique(
            np.asarray(
                [
                    face_by_edge[
                        min(int(left), int(right)) * len(vertices)
                        + max(int(left), int(right))
                    ]
                    for left, right in zip(vertex_ids, next_ids, strict=True)
                ],
                dtype=np.int32,
            )
        )
        result.append(
            BoundaryLoop(
                part_id=int(part_id),
                loop_id=int(loop_id),
                vertex_ids=vertex_ids,
                points_unit=points,
                center_unit=points.mean(axis=0),
                perimeter_unit=perimeter,
                span_unit=float(np.linalg.norm(np.ptp(points, axis=0))),
                adjacent_face_ids=adjacent_face_ids,
            )
        )
    return result


def pair_matching_loops(
    loops: Iterable[BoundaryLoop],
    *,
    height_mm: float,
    tolerance_mm: float = 0.05,
) -> list[SeamPair]:
    candidates = list(loops)
    scored: list[tuple[float, float, int, int]] = []
    tolerance_unit = float(tolerance_mm) / max(float(height_mm), 1e-9)
    for left_index, left in enumerate(candidates):
        for right_index in range(left_index + 1, len(candidates)):
            right = candidates[right_index]
            if left.part_id == right.part_id:
                continue
            perimeter_ratio = left.perimeter_unit / max(
                right.perimeter_unit, 1e-12
            )
            if perimeter_ratio < 0.92 or perimeter_ratio > 1.08:
                continue
            if (
                float(np.linalg.norm(left.center_unit - right.center_unit))
                > max(tolerance_unit * 2.0, 0.02 * left.span_unit)
            ):
                continue
            left_tree = cKDTree(left.points_unit)
            right_tree = cKDTree(right.points_unit)
            left_distances = left_tree.query(right.points_unit, workers=-1)[0]
            right_distances = right_tree.query(left.points_unit, workers=-1)[0]
            distances = np.concatenate((left_distances, right_distances))
            rms = float(np.sqrt(np.mean(distances * distances)))
            maximum = float(distances.max(initial=0.0))
            if maximum <= tolerance_unit:
                scored.append((rms, maximum, left_index, right_index))
    scored.sort()
    used: set[int] = set()
    result: list[SeamPair] = []
    for rms, maximum, left_index, right_index in scored:
        if left_index in used or right_index in used:
            continue
        used.add(left_index)
        used.add(right_index)
        result.append(
            SeamPair(
                seam_id=len(result),
                first=candidates[left_index],
                second=candidates[right_index],
                match_rms_unit=rms,
                match_max_unit=maximum,
            )
        )
    return result


def weld_matching_seams(
    meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    seams: Iterable[SeamPair],
    *,
    height_mm: float,
    tolerance_mm: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Rejoin Tripo's coincident open patches without inventing cap faces.

    Tripo multipart exports commonly duplicate the vertices on both sides of a
    cut.  Joining only those strictly paired vertices restores the original
    closed shell while preserving every source triangle and its colour.  A
    mismatched tessellation is rejected: blindly welding it would create a
    non-manifold edge and hand the slicer another repair problem.
    """

    if not meshes:
        raise AssemblyError("溶接するメッシュがありません")
    seam_list = list(seams)
    vertex_counts = np.asarray(
        [len(mesh[0]) for mesh in meshes], dtype=np.int64
    )
    offsets = np.concatenate(
        (np.asarray([0], dtype=np.int64), np.cumsum(vertex_counts))
    )
    vertices = np.vstack(
        [np.asarray(mesh[0], dtype=np.float64) for mesh in meshes]
    )
    colors = np.vstack(
        [np.asarray(mesh[2], dtype=np.float64) for mesh in meshes]
    )
    faces = np.vstack(
        [
            np.asarray(mesh[1], dtype=np.int64) + int(offsets[part_id])
            for part_id, mesh in enumerate(meshes)
        ]
    )
    before = _edge_topology(faces, len(vertices))
    tolerance_unit = float(tolerance_mm) / max(float(height_mm), 1e-9)
    parent = np.arange(len(vertices), dtype=np.int64)

    def find(value: int) -> int:
        current = int(value)
        while int(parent[current]) != current:
            parent[current] = parent[int(parent[current])]
            current = int(parent[current])
        return current

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            if first_root < second_root:
                parent[second_root] = first_root
            else:
                parent[first_root] = second_root

    matched_vertices = 0
    maximum_distance = 0.0
    for seam in seam_list:
        first_part = int(seam.first.part_id)
        second_part = int(seam.second.part_id)
        if not (0 <= first_part < len(meshes)) or not (
            0 <= second_part < len(meshes)
        ):
            raise AssemblyError(
                f"継ぎ目{seam.seam_id + 1}のパーツ番号が範囲外です"
            )
        first_ids = np.asarray(seam.first.vertex_ids, dtype=np.int64)
        second_ids = np.asarray(seam.second.vertex_ids, dtype=np.int64)
        if len(first_ids) != len(second_ids):
            raise AssemblyError(
                f"継ぎ目{seam.seam_id + 1}は左右の頂点数が異なります "
                f"({len(first_ids)} / {len(second_ids)})"
            )
        first_points = np.asarray(meshes[first_part][0], dtype=np.float64)[
            first_ids
        ]
        second_points = np.asarray(meshes[second_part][0], dtype=np.float64)[
            second_ids
        ]
        distances, nearest = cKDTree(second_points).query(
            first_points, k=1, workers=-1
        )
        if len(np.unique(nearest)) != len(second_ids):
            raise AssemblyError(
                f"継ぎ目{seam.seam_id + 1}を一対一で対応付けできません"
            )
        seam_maximum = float(np.max(distances, initial=0.0))
        if seam_maximum > tolerance_unit:
            raise AssemblyError(
                f"継ぎ目{seam.seam_id + 1}のずれが許容値を超えています: "
                f"{seam_maximum * height_mm:.4f} mm"
            )
        maximum_distance = max(maximum_distance, seam_maximum)
        first_global = first_ids + int(offsets[first_part])
        second_global = second_ids[nearest] + int(offsets[second_part])
        for first_vertex, second_vertex in zip(
            first_global, second_global, strict=True
        ):
            union(int(first_vertex), int(second_vertex))
        matched_vertices += len(first_ids)

    # Compress the sparse union-find forest, then average the two coincident
    # samples.  Averaging avoids bias toward whichever Tripo part was listed
    # first and keeps the displacement below the measured seam tolerance.
    while True:
        compressed = parent[parent]
        if np.array_equal(compressed, parent):
            break
        parent = compressed
    roots, inverse = np.unique(parent, return_inverse=True)
    counts = np.bincount(inverse, minlength=len(roots)).astype(np.float64)
    welded_vertices = np.zeros((len(roots), 3), dtype=np.float64)
    welded_colors = np.zeros((len(roots), 3), dtype=np.float64)
    np.add.at(welded_vertices, inverse, vertices)
    np.add.at(welded_colors, inverse, colors)
    welded_vertices /= counts[:, None]
    welded_colors /= counts[:, None]
    welded_faces = inverse[faces].astype(np.int32)
    degenerate = np.any(
        np.column_stack(
            (
                welded_faces[:, 0] == welded_faces[:, 1],
                welded_faces[:, 1] == welded_faces[:, 2],
                welded_faces[:, 2] == welded_faces[:, 0],
            )
        ),
        axis=1,
    )
    if np.any(degenerate):
        raise AssemblyError(
            f"境界溶接で縮退面が {int(np.count_nonzero(degenerate))} 面発生しました"
        )

    after = _edge_topology(welded_faces, len(welded_vertices))
    if not bool(after["watertight"]):
        raise AssemblyError(
            "対応境界を溶接しても閉立体になりませんでした: "
            f"境界 {after['boundary_edges']}, "
            f"非多様体 {after['nonmanifold_edges']}"
        )
    if int(after["inconsistent_winding_edges"]):
        mesh_set = ml.MeshSet()
        mesh_set.add_mesh(
            ml.Mesh(
                vertex_matrix=welded_vertices,
                face_matrix=welded_faces,
                v_color_matrix=np.column_stack(
                    (welded_colors, np.ones(len(welded_colors)))
                ),
            ),
            "welded Tripo shell",
        )
        mesh_set.apply_filter("meshing_re_orient_faces_coherently")
        mesh = mesh_set.current_mesh()
        welded_vertices = np.asarray(mesh.vertex_matrix(), dtype=np.float64)
        welded_faces = np.asarray(mesh.face_matrix(), dtype=np.int32)
        rgba = np.asarray(mesh.vertex_color_matrix(), dtype=np.float64)
        welded_colors = np.clip(rgba[:, :3], 0.0, 1.0)
        after = _edge_topology(welded_faces, len(welded_vertices))
        if not bool(after["watertight"]) or int(
            after["inconsistent_winding_edges"]
        ):
            raise AssemblyError("境界溶接後の面方向を正常化できませんでした")

    return (
        welded_vertices,
        welded_faces,
        np.clip(welded_colors, 0.0, 1.0),
        {
            "method": "matched_seam_weld",
            "source_parts": int(len(meshes)),
            "matched_seams": int(len(seam_list)),
            "matched_vertices_per_side": int(matched_vertices),
            "merged_vertices": int(len(vertices) - len(welded_vertices)),
            "maximum_displacement_mm": float(
                maximum_distance * float(height_mm) * 0.5
            ),
            "added_faces": 0,
            "before": before,
            "after": after,
            "closed": True,
        },
    )


def _directed_boundary_edges(
    faces: np.ndarray,
    vertex_count: int,
) -> np.ndarray:
    """Return the single directed occurrence of every boundary edge."""

    faces = np.asarray(faces, dtype=np.int64)
    if not len(faces):
        return np.empty((0, 2), dtype=np.int32)
    directed = np.vstack(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])
    )
    lo = np.minimum(directed[:, 0], directed[:, 1])
    hi = np.maximum(directed[:, 0], directed[:, 1])
    key = lo * np.int64(vertex_count) + hi
    order = np.argsort(key)
    key = key[order]
    directed = directed[order]
    _, start, counts = np.unique(key, return_index=True, return_counts=True)
    return directed[start[counts == 1]].astype(np.int32)


def _orient_cap_against_source(
    source_faces: np.ndarray,
    cap_faces: np.ndarray,
    vertex_count: int,
) -> np.ndarray:
    """Orient a cap so every shared boundary edge opposes the source shell."""

    result = np.asarray(cap_faces, dtype=np.int32).copy()
    source_boundary = {
        (int(left), int(right))
        for left, right in _directed_boundary_edges(
            source_faces, vertex_count
        )
    }
    cap_boundary = _directed_boundary_edges(result, vertex_count)
    if not len(cap_boundary):
        raise AssemblyError("共有組立面に外周エッジがありません")
    same = sum(
        (int(left), int(right)) in source_boundary
        for left, right in cap_boundary
    )
    opposite = sum(
        (int(right), int(left)) in source_boundary
        for left, right in cap_boundary
    )
    if same == len(cap_boundary) and opposite == 0:
        result[:, [1, 2]] = result[:, [2, 1]]
    elif opposite != len(cap_boundary) or same != 0:
        raise AssemblyError(
            "共有組立面と元パーツの境界方向を一意に対応できません"
        )
    return result


def _signed_mesh_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
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


def _strict_mesh_record(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    part_id: int,
) -> tuple[np.ndarray, dict[str, object]]:
    """Validate a printable part and return outward-oriented faces."""

    vertices = np.asarray(vertices, dtype=np.float64)
    result_faces = np.asarray(faces, dtype=np.int32).copy()
    topology = _edge_topology(result_faces, len(vertices))
    if not bool(topology["watertight"]):
        raise AssemblyError(
            f"パーツ{part_id + 1}を閉立体にできませんでした: "
            f"境界 {topology['boundary_edges']}, "
            f"非多様体 {topology['nonmanifold_edges']}"
        )
    if int(topology["inconsistent_winding_edges"]):
        raise AssemblyError(
            f"パーツ{part_id + 1}の面方向が共有組立面で一致しません"
        )
    triangles = vertices[result_faces]
    repeated = np.any(
        np.column_stack(
            (
                result_faces[:, 0] == result_faces[:, 1],
                result_faces[:, 1] == result_faces[:, 2],
                result_faces[:, 2] == result_faces[:, 0],
            )
        ),
        axis=1,
    )
    doubled_area = np.linalg.norm(
        np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        ),
        axis=1,
    )
    degenerate = int(
        np.count_nonzero(repeated | (doubled_area <= 1e-14))
    )
    if degenerate:
        raise AssemblyError(
            f"パーツ{part_id + 1}の共有組立面に縮退面が "
            f"{degenerate} 面あります"
        )
    signed_volume = _signed_mesh_volume(vertices, result_faces)
    reoriented = signed_volume < 0.0
    if reoriented:
        result_faces[:, [1, 2]] = result_faces[:, [2, 1]]
        signed_volume = -signed_volume
    if not np.isfinite(signed_volume) or signed_volume <= 1e-14:
        raise AssemblyError(f"パーツ{part_id + 1}の体積が正になりません")
    volume = trimesh.Trimesh(
        vertices=vertices,
        faces=result_faces,
        process=False,
    )
    bodies = list(volume.split(only_watertight=False))
    if not volume.is_watertight or not volume.is_volume:
        raise AssemblyError(f"パーツ{part_id + 1}が正しい閉立体ではありません")
    if len(bodies) != 1:
        raise AssemblyError(
            f"パーツ{part_id + 1}が {len(bodies)} 個の離れた立体に分かれています"
        )
    mesh_set = ml.MeshSet()
    mesh_set.add_mesh(
        ml.Mesh(vertex_matrix=vertices, face_matrix=result_faces),
        f"partitioned part {part_id + 1}",
    )
    try:
        mesh_set.apply_filter(
            "compute_selection_by_self_intersections_per_face"
        )
        self_intersections = int(
            mesh_set.current_mesh().selected_face_number()
        )
    except Exception as exc:  # pragma: no cover - plugin failures vary
        raise AssemblyError(
            f"パーツ{part_id + 1}の自己交差検査を実行できません: {exc}"
        ) from exc
    if self_intersections:
        raise AssemblyError(
            f"パーツ{part_id + 1}の共有組立面が元の外面と交差します "
            f"({self_intersections} 面)。安全のため閉立体化を中止しました"
        )
    return result_faces, {
        "topology": topology,
        "body_count": 1,
        "volume_unit3": float(signed_volume),
        "positive_volume": True,
        "degenerate_faces": 0,
        "self_intersections": 0,
        "reoriented": bool(reoriented),
    }


def _shared_planar_interface(
    first_points: np.ndarray,
    second_points: np.ndarray,
    *,
    height_mm: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """Create one conservative cap shared by both sides of a seam.

    The source curve may be slightly noisy, but a strongly warped or
    self-overlapping projection is deliberately rejected.  Such a seam needs
    a volumetric partitioner; returning a plausible-looking intersecting cap
    would only defer corruption to the slicer.
    """

    first_points = np.asarray(first_points, dtype=np.float64)
    second_points = np.asarray(second_points, dtype=np.float64)
    canonical = 0.5 * (first_points + second_points)
    center = canonical.mean(axis=0)
    _u, _singular, vh = np.linalg.svd(
        canonical - center, full_matrices=False
    )
    axis_u = np.asarray(vh[0], dtype=np.float64)
    normal = np.asarray(vh[-1], dtype=np.float64)
    largest_normal_axis = int(np.argmax(np.abs(normal)))
    if normal[largest_normal_axis] < 0.0:
        normal *= -1.0
    axis_u -= normal * float(np.dot(axis_u, normal))
    axis_u /= max(float(np.linalg.norm(axis_u)), 1e-12)
    axis_v = np.cross(normal, axis_u)
    axis_v /= max(float(np.linalg.norm(axis_v)), 1e-12)
    coordinates = np.column_stack(
        ((canonical - center) @ axis_u, (canonical - center) @ axis_v)
    )
    residual = np.abs((canonical - center) @ normal)
    span_mm = float(np.linalg.norm(np.ptp(canonical, axis=0))) * float(
        height_mm
    )
    maximum_planarity_mm = float(residual.max(initial=0.0)) * float(
        height_mm
    )
    rms_planarity_mm = float(np.sqrt(np.mean(residual * residual))) * float(
        height_mm
    )
    planarity_limit_mm = max(0.25, 0.015 * span_mm)
    if maximum_planarity_mm > planarity_limit_mm:
        raise AssemblyError(
            "Tripoパーツ境界が安全な共有組立面として扱える範囲を超えて"
            f"湾曲しています: 最大 {maximum_planarity_mm:.2f} mm / "
            f"許容 {planarity_limit_mm:.2f} mm"
        )
    polygon = Polygon(coordinates)
    if (
        not polygon.is_valid
        or not polygon.exterior.is_simple
        or polygon.area <= 1e-12
    ):
        raise AssemblyError(
            "Tripoパーツ境界の平面投影が自己交差しています。"
            "安全な体積分割が必要です"
        )
    local_faces = np.asarray(
        triangulate_float64(
            np.ascontiguousarray(coordinates, dtype=np.float64),
            np.asarray([len(coordinates)], dtype=np.uint32),
        ),
        dtype=np.int32,
    ).reshape((-1, 3))
    if not len(local_faces):
        raise AssemblyError("共有組立面を三角形分割できませんでした")
    local_edges = _boundary_edges(local_faces, len(canonical))
    expected_edges = {
        tuple(sorted((index, (index + 1) % len(canonical))))
        for index in range(len(canonical))
    }
    actual_edges = {
        tuple(sorted((int(left), int(right))))
        for left, right in local_edges
    }
    if actual_edges != expected_edges:
        raise AssemblyError(
            "共有組立面の三角形分割が元の境界全体を保持できません"
        )
    label = polylabel(
        polygon,
        tolerance=max(1e-7, 0.05 / max(float(height_mm), 1e-9)),
    )
    plane_point = (
        center + axis_u * float(label.x) + axis_v * float(label.y)
    )
    cap_mesh = trimesh.Trimesh(
        vertices=canonical,
        faces=local_faces,
        process=False,
    )
    surface_point, _distance, anchor_triangle = (
        trimesh.proximity.closest_point_naive(cap_mesh, [plane_point])
    )
    return canonical, local_faces, {
        "center_unit": center.round(9).tolist(),
        "surface_point_unit": surface_point[0].round(9).tolist(),
        "anchor_triangle": int(anchor_triangle[0]),
        "axis_u": axis_u.round(9).tolist(),
        "axis_v": axis_v.round(9).tolist(),
        "normal_unit": normal.round(9).tolist(),
        "safe_radius_mm": float(label.distance(polygon.boundary))
        * float(height_mm),
        "span_mm": span_mm,
        "planarity_max_mm": maximum_planarity_mm,
        "planarity_rms_mm": rms_planarity_mm,
        "planarity_limit_mm": planarity_limit_mm,
    }


def repair_small_unmatched_boundaries(
    meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    loops: Iterable[BoundaryLoop],
    *,
    height_mm: float,
    maximum_span_mm: float = 2.0,
    maximum_planarity_mm: float = 0.02,
) -> tuple[
    list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    list[dict[str, object]],
]:
    """Cap only tiny, strictly planar boundary loops in-place by part.

    The caller must pass only loops which could not be paired to another Tripo
    part.  No vertices are invented or moved: each cap is triangulated from the
    existing boundary vertices and oriented against the source shell.  Larger,
    warped, self-crossing, or stale loops fail closed so this helper cannot turn
    an actual missing limb or assembly seam into a plausible-looking surface.
    """

    if not meshes:
        raise AssemblyError("局所修復するパーツがありません")
    if not np.isfinite(height_mm) or float(height_mm) <= 0.0:
        raise AssemblyError("造形高さが不正です")
    if not np.isfinite(maximum_span_mm) or float(maximum_span_mm) <= 0.0:
        raise AssemblyError("局所修復の最大幅が不正です")
    if (
        not np.isfinite(maximum_planarity_mm)
        or float(maximum_planarity_mm) <= 0.0
    ):
        raise AssemblyError("局所修復の平面許容値が不正です")

    output: list[list[np.ndarray]] = [
        [
            np.asarray(vertices, dtype=np.float64).copy(),
            np.asarray(faces, dtype=np.int32).copy(),
            np.asarray(colors, dtype=np.float64).copy(),
        ]
        for vertices, faces, colors in meshes
    ]
    records: list[dict[str, object]] = []
    for loop in loops:
        part_id = int(loop.part_id)
        if not 0 <= part_id < len(output):
            raise AssemblyError(
                f"未対応境界{loop.loop_id + 1}のパーツ番号が不正です"
            )
        vertices, faces, _colors = output[part_id]
        vertex_ids = np.asarray(loop.vertex_ids, dtype=np.int64)
        if (
            len(vertex_ids) < 3
            or len(np.unique(vertex_ids)) != len(vertex_ids)
            or int(vertex_ids.min(initial=0)) < 0
            or int(vertex_ids.max(initial=-1)) >= len(vertices)
        ):
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}が不正です"
            )

        current_boundary = {
            tuple(sorted((int(left), int(right))))
            for left, right in _boundary_edges(faces, len(vertices))
        }
        loop_edges = {
            tuple(sorted((int(left), int(right))))
            for left, right in zip(
                vertex_ids, np.roll(vertex_ids, -1), strict=True
            )
        }
        if len(loop_edges) != len(vertex_ids) or not loop_edges.issubset(
            current_boundary
        ):
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}は"
                "現在の開口境界と一致しません"
            )

        points = vertices[vertex_ids]
        center = points.mean(axis=0)
        span_mm = float(np.linalg.norm(np.ptp(points, axis=0))) * float(
            height_mm
        )
        perimeter_mm = float(loop.perimeter_unit) * float(height_mm)
        if span_mm > float(maximum_span_mm) + 1e-9:
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}は"
                f"局所修復の最大幅を超えています: {span_mm:.3f} mm / "
                f"{float(maximum_span_mm):.3f} mm"
            )

        try:
            _u, singular_values, vh = np.linalg.svd(
                points - center, full_matrices=False
            )
        except np.linalg.LinAlgError as exc:
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}の"
                "平面性を判定できません"
            ) from exc
        if vh.shape != (3, 3) or len(singular_values) < 2:
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}を"
                "平面へ投影できません"
            )
        axis_u = np.asarray(vh[0], dtype=np.float64)
        normal = np.asarray(vh[-1], dtype=np.float64)
        axis_v = np.cross(normal, axis_u)
        axis_v_norm = float(np.linalg.norm(axis_v))
        if axis_v_norm <= 1e-12:
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}が"
                "退化しています"
            )
        axis_v /= axis_v_norm
        residual = np.abs((points - center) @ normal)
        planarity_max_mm = float(residual.max(initial=0.0)) * float(
            height_mm
        )
        planarity_rms_mm = float(
            np.sqrt(np.mean(residual * residual)) * float(height_mm)
        )
        # At most 1% of the tiny opening span, with a 0.005 mm numerical floor
        # and an absolute 0.02 mm ceiling.  This is deliberately much stricter
        # than the normal paired-seam reconstruction tolerance.
        planarity_limit_mm = min(
            float(maximum_planarity_mm),
            max(0.005, 0.01 * span_mm),
        )
        if planarity_max_mm > planarity_limit_mm + 1e-9:
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}は"
                "局所修復できる平面性を超えています: "
                f"{planarity_max_mm:.4f} mm / {planarity_limit_mm:.4f} mm"
            )

        coordinates = np.column_stack(
            ((points - center) @ axis_u, (points - center) @ axis_v)
        )
        polygon = Polygon(coordinates)
        if (
            not polygon.is_valid
            or not polygon.exterior.is_simple
            or polygon.area <= 1e-16
        ):
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}の"
                "平面投影が退化または自己交差しています"
            )
        local_faces = np.asarray(
            triangulate_float64(
                np.ascontiguousarray(coordinates, dtype=np.float64),
                np.asarray([len(coordinates)], dtype=np.uint32),
            ),
            dtype=np.int32,
        ).reshape((-1, 3))
        if not len(local_faces):
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}を"
                "三角形分割できませんでした"
            )
        expected_edges = {
            tuple(sorted((index, (index + 1) % len(vertex_ids))))
            for index in range(len(vertex_ids))
        }
        actual_edges = {
            tuple(sorted((int(left), int(right))))
            for left, right in _boundary_edges(local_faces, len(vertex_ids))
        }
        if actual_edges != expected_edges:
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}を"
                "外周を保ったまま三角形分割できませんでした"
            )

        cap_faces = _orient_cap_against_source(
            faces,
            vertex_ids[local_faces],
            len(vertices),
        )
        doubled_areas = np.linalg.norm(
            np.cross(
                vertices[cap_faces[:, 1]] - vertices[cap_faces[:, 0]],
                vertices[cap_faces[:, 2]] - vertices[cap_faces[:, 0]],
            ),
            axis=1,
        )
        if np.any(doubled_areas <= 1e-16):
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}に"
                "縮退する修復面があります"
            )

        before = _edge_topology(faces, len(vertices))
        cap_start = int(len(faces))
        repaired_faces = np.vstack((faces, cap_faces)).astype(np.int32)
        after = _edge_topology(repaired_faces, len(vertices))
        expected_boundary_edges = int(before["boundary_edges"]) - len(
            vertex_ids
        )
        if (
            int(after["boundary_edges"]) != expected_boundary_edges
            or int(after["nonmanifold_edges"])
            != int(before["nonmanifold_edges"])
            or int(after["inconsistent_winding_edges"])
            > int(before["inconsistent_winding_edges"])
        ):
            raise AssemblyError(
                f"パーツ{part_id + 1}の未対応境界{loop.loop_id + 1}を"
                "局所修復するとトポロジーが悪化します"
            )
        output[part_id][1] = repaired_faces
        records.append(
            {
                "part_id": part_id,
                "loop_id": int(loop.loop_id),
                "method": "strict_planar_local_cap",
                "boundary_vertices": int(len(vertex_ids)),
                "span_mm": span_mm,
                "perimeter_mm": perimeter_mm,
                "planarity_max_mm": planarity_max_mm,
                "planarity_rms_mm": planarity_rms_mm,
                "planarity_limit_mm": planarity_limit_mm,
                "added_faces": int(len(cap_faces)),
                "cap_face_ids": list(
                    range(cap_start, cap_start + len(cap_faces))
                ),
                "before": before,
                "after": after,
                "closed_loop": True,
            }
        )

    return (
        [
            (
                np.asarray(vertices, dtype=np.float64),
                np.asarray(faces, dtype=np.int32),
                np.clip(np.asarray(colors, dtype=np.float64), 0.0, 1.0),
            )
            for vertices, faces, colors in output
        ],
        records,
    )


def solidify_partitioned_parts(
    meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    seams: Iterable[SeamPair],
    *,
    height_mm: float,
) -> tuple[
    list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    dict[str, object],
]:
    """Close Tripo partitions without discarding their original identities.

    A simple, near-planar paired seam receives exactly the same cap geometry
    on both source parts, with opposite winding.  Every result is then checked
    as a printable solid.  Complex warped seams are rejected so a later
    volumetric partitioner can handle them without silently corrupting colour
    or anatomy.
    """

    if not meshes:
        raise AssemblyError("閉立体化するパーツがありません")
    if not np.isfinite(height_mm) or float(height_mm) <= 0.0:
        raise AssemblyError("造形高さが不正です")
    seam_list = list(seams)
    output: list[list[np.ndarray]] = []
    before_topology: list[dict[str, int | bool]] = []
    actual_loops: list[BoundaryLoop] = []
    for part_id, mesh in enumerate(meshes):
        if len(mesh) != 3:
            raise AssemblyError(f"パーツ{part_id + 1}のメッシュ形式が不正です")
        vertices = np.asarray(mesh[0], dtype=np.float64)
        faces = np.asarray(mesh[1], dtype=np.int32)
        colors = np.asarray(mesh[2], dtype=np.float64)
        if (
            vertices.ndim != 2
            or vertices.shape[1] != 3
            or faces.ndim != 2
            or faces.shape[1] != 3
            or colors.shape != (len(vertices), 3)
            or not len(vertices)
            or not len(faces)
            or int(faces.min()) < 0
            or int(faces.max()) >= len(vertices)
            or not np.isfinite(vertices).all()
            or not np.isfinite(colors).all()
        ):
            raise AssemblyError(f"パーツ{part_id + 1}の頂点・面・色が不正です")
        topology = _edge_topology(faces, len(vertices))
        before_topology.append(topology)
        output.append([vertices.copy(), faces.copy(), colors.copy()])
        actual_loops.extend(find_boundary_loops(part_id, vertices, faces))

    if not actual_loops:
        if seam_list:
            raise AssemblyError("閉じたパーツに不要なTripo境界情報があります")
        part_records: list[dict[str, object]] = []
        results: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        for part_id, (vertices, faces, colors) in enumerate(output):
            validated_faces, validation = _strict_mesh_record(
                vertices, faces, part_id=part_id
            )
            results.append((vertices, validated_faces, colors))
            part_records.append(
                {
                    "part_id": part_id,
                    "before": before_topology[part_id],
                    "after": validation["topology"],
                    "added_faces": 0,
                    **{
                        key: value
                        for key, value in validation.items()
                        if key != "topology"
                    },
                }
            )
        return results, {
            "method": "partitioned_shared_caps",
            "identity": True,
            "source_parts": len(meshes),
            "output_parts": len(results),
            "matched_seams": 0,
            "interfaces": [],
            "parts": part_records,
            "closed": True,
        }

    loop_keys = {
        (loop.part_id, frozenset(int(value) for value in loop.vertex_ids))
        for loop in actual_loops
    }
    seam_loop_keys: list[tuple[int, frozenset[int]]] = []
    for seam in seam_list:
        for loop in (seam.first, seam.second):
            seam_loop_keys.append(
                (
                    int(loop.part_id),
                    frozenset(int(value) for value in loop.vertex_ids),
                )
            )
    if len(set(seam_loop_keys)) != len(seam_loop_keys):
        raise AssemblyError("同じTripo境界が複数の継ぎ目に使われています")
    missing = loop_keys - set(seam_loop_keys)
    extra = set(seam_loop_keys) - loop_keys
    if missing or extra or len(seam_loop_keys) != len(loop_keys):
        raise AssemblyError(
            "Tripoパーツの開口境界をすべて一対一で対応できません: "
            f"未対応 {len(missing)}, 不一致 {len(extra)}"
        )

    tolerance_unit = 0.05 / float(height_mm)
    interfaces: list[dict[str, object]] = []
    added_faces = np.zeros(len(meshes), dtype=np.int64)
    for seam in seam_list:
        first_part = int(seam.first.part_id)
        second_part = int(seam.second.part_id)
        if (
            first_part == second_part
            or not 0 <= first_part < len(meshes)
            or not 0 <= second_part < len(meshes)
        ):
            raise AssemblyError(
                f"継ぎ目{seam.seam_id + 1}のパーツ番号が不正です"
            )
        first_ids = np.asarray(seam.first.vertex_ids, dtype=np.int64)
        second_ids = np.asarray(seam.second.vertex_ids, dtype=np.int64)
        if len(first_ids) != len(second_ids) or len(first_ids) < 3:
            raise AssemblyError(
                f"継ぎ目{seam.seam_id + 1}の左右で境界頂点数が一致しません"
            )
        first_vertices = output[first_part][0]
        second_vertices = output[second_part][0]
        first_points = first_vertices[first_ids]
        second_points = second_vertices[second_ids]
        distances, nearest = cKDTree(second_points).query(
            first_points, workers=-1
        )
        if len(np.unique(nearest)) != len(second_ids):
            raise AssemblyError(
                f"継ぎ目{seam.seam_id + 1}を一対一で対応できません"
            )
        maximum_mismatch = float(distances.max(initial=0.0))
        if maximum_mismatch > tolerance_unit:
            raise AssemblyError(
                f"継ぎ目{seam.seam_id + 1}のずれが0.05 mmを超えています: "
                f"{maximum_mismatch * height_mm:.4f} mm"
            )
        aligned_second_ids = second_ids[nearest]
        expected_second_edges = {
            tuple(
                sorted(
                    (
                        int(second_ids[index]),
                        int(second_ids[(index + 1) % len(second_ids)]),
                    )
                )
            )
            for index in range(len(second_ids))
        }
        aligned_second_edges = {
            tuple(
                sorted(
                    (
                        int(aligned_second_ids[index]),
                        int(
                            aligned_second_ids[
                                (index + 1) % len(aligned_second_ids)
                            ]
                        ),
                    )
                )
            )
            for index in range(len(aligned_second_ids))
        }
        if expected_second_edges != aligned_second_edges:
            raise AssemblyError(
                f"継ぎ目{seam.seam_id + 1}の境界順序が左右で一致しません"
            )
        canonical, local_faces, frame = _shared_planar_interface(
            first_points,
            second_points[nearest],
            height_mm=height_mm,
        )
        first_vertices[first_ids] = canonical
        second_vertices[aligned_second_ids] = canonical
        first_cap = _orient_cap_against_source(
            output[first_part][1],
            first_ids[local_faces],
            len(first_vertices),
        )
        second_cap = _orient_cap_against_source(
            output[second_part][1],
            aligned_second_ids[local_faces],
            len(second_vertices),
        )
        first_start = int(len(output[first_part][1]))
        second_start = int(len(output[second_part][1]))
        output[first_part][1] = np.vstack(
            (output[first_part][1], first_cap)
        ).astype(np.int32)
        output[second_part][1] = np.vstack(
            (output[second_part][1], second_cap)
        ).astype(np.int32)
        added_faces[first_part] += len(first_cap)
        added_faces[second_part] += len(second_cap)
        first_normal = trimesh.triangles.normals(
            first_vertices[first_cap]
        )[0].mean(axis=0)
        second_normal = trimesh.triangles.normals(
            second_vertices[second_cap]
        )[0].mean(axis=0)
        first_normal /= max(float(np.linalg.norm(first_normal)), 1e-12)
        second_normal /= max(float(np.linalg.norm(second_normal)), 1e-12)
        interfaces.append(
            {
                "seam_id": int(seam.seam_id),
                "parts": [first_part, second_part],
                "boundary_vertices": int(len(first_ids)),
                "cap_faces": int(len(local_faces)),
                "maximum_boundary_mismatch_mm": maximum_mismatch
                * float(height_mm),
                "cap_face_range_by_part": {
                    str(first_part): [
                        first_start,
                        first_start + len(first_cap),
                    ],
                    str(second_part): [
                        second_start,
                        second_start + len(second_cap),
                    ],
                },
                "boundary_vertex_ids_by_part": {
                    str(first_part): first_ids.astype(int).tolist(),
                    str(second_part): aligned_second_ids.astype(int).tolist(),
                },
                "outward_normal_by_part": {
                    str(first_part): first_normal.round(9).tolist(),
                    str(second_part): second_normal.round(9).tolist(),
                },
                **frame,
            }
        )

    results = []
    part_records = []
    for part_id, (vertices, faces, colors) in enumerate(output):
        validated_faces, validation = _strict_mesh_record(
            vertices, faces, part_id=part_id
        )
        results.append(
            (
                vertices,
                validated_faces,
                np.clip(colors, 0.0, 1.0),
            )
        )
        part_records.append(
            {
                "part_id": part_id,
                "before": before_topology[part_id],
                "after": validation["topology"],
                "added_faces": int(added_faces[part_id]),
                **{
                    key: value
                    for key, value in validation.items()
                    if key != "topology"
                },
            }
        )
    return results, {
        "method": "partitioned_shared_caps",
        "identity": False,
        "source_parts": len(meshes),
        "output_parts": len(results),
        "matched_seams": len(seam_list),
        "interfaces": interfaces,
        "parts": part_records,
        "closed": True,
    }


def close_open_mesh(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int32)
    colors = np.asarray(colors, dtype=np.float64)
    before = _edge_topology(faces, len(vertices))
    if bool(before["watertight"]):
        return (
            vertices.copy(),
            faces.copy(),
            colors.copy(),
            {
                "before": before,
                "after": before,
                "added_faces": 0,
                "closed": True,
            },
        )
    rgba = np.column_stack((colors, np.ones(len(colors), dtype=np.float64)))
    mesh_set = ml.MeshSet()
    mesh_set.add_mesh(
        ml.Mesh(
            vertex_matrix=vertices,
            face_matrix=faces,
            v_color_matrix=rgba,
        ),
        "open part",
    )
    mesh_set.apply_filter(
        "meshing_close_holes",
        maxholesize=max(30, int(before["boundary_edges"]) + 8),
        selected=False,
        newfaceselected=True,
        # Avoiding self-intersections can leave tiny openings.  The original
        # Tripo seams are paired boundaries, so closing every loop is safer
        # than sending an open colored shell to the slicer repair command.
        selfintersection=False,
        refinehole=False,
    )
    mesh_set.apply_filter("meshing_re_orient_faces_coherently")
    mesh = mesh_set.current_mesh()
    repaired_vertices = np.asarray(mesh.vertex_matrix(), dtype=np.float64)
    repaired_faces = np.asarray(mesh.face_matrix(), dtype=np.int32)
    rgba_out = np.asarray(mesh.vertex_color_matrix(), dtype=np.float64)
    if rgba_out.shape[0] != len(repaired_vertices) or rgba_out.shape[1] < 3:
        raise AssemblyError("閉立体化中に頂点色が失われました")
    repaired_colors = np.clip(rgba_out[:, :3], 0.0, 1.0)
    after = _edge_topology(repaired_faces, len(repaired_vertices))
    if not bool(after["watertight"]):
        raise AssemblyError(
            "切断境界を閉じ切れませんでした: "
            f"境界 {after['boundary_edges']}, "
            f"非多様体 {after['nonmanifold_edges']}"
        )
    return (
        repaired_vertices,
        repaired_faces,
        repaired_colors,
        {
            "before": before,
            "after": after,
            "added_faces": int(len(repaired_faces) - len(faces)),
            "closed": True,
        },
    )


def _positive_watertight_body_volumes(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    require_positive_volume: bool = True,
) -> list[float]:
    """Validate every disconnected shell without requiring one body only."""

    volume_mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int32),
        process=False,
    )
    if not volume_mesh.is_watertight or not volume_mesh.is_winding_consistent:
        raise AssemblyError("継ぎ目統合後の閉立体トポロジーを検証できません")
    bodies = list(volume_mesh.split(only_watertight=False))
    if not bodies:
        raise AssemblyError("継ぎ目統合後の閉立体を取得できません")
    dimensions = np.ptp(np.asarray(vertices, dtype=np.float64), axis=0)
    scale = max(float(np.max(dimensions, initial=0.0)), 1.0e-12)
    volume_epsilon = max(np.finfo(np.float64).eps * scale**3 * 1024.0, 1.0e-18)
    body_volumes: list[float] = []
    for body_index, body in enumerate(bodies):
        body_volume = float(body.volume)
        invalid_volume = not np.isfinite(body_volume) or (
            bool(require_positive_volume) and body_volume <= volume_epsilon
        )
        if (
            not body.is_watertight
            or not body.is_winding_consistent
            or invalid_volume
        ):
            raise AssemblyError(
                f"継ぎ目統合後の連結立体{body_index + 1}が正の閉立体になりません"
            )
        body_volumes.append(body_volume)
    return body_volumes


def solidify_coincident_shells(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    *,
    require_positive_volume: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Close a logical single mesh by welding exact duplicate seam vertices.

    GLB exporters commonly duplicate vertices along UV/material seams even when
    the rendered surface is geometrically closed.  An indexed-mesh topology
    check then mistakes every duplicated seam for a real opening.  This repair
    proves exact reverse-oriented 1:1 boundary-edge pairs and merges *only*
    their matching endpoints.  It keeps every triangle and its order, and
    averages colour only where paired seam vertices become one.  Coincident
    interior vertices are deliberately left separate.

    A genuine hole has no coincident partner and therefore remains open.  Such
    input is rejected instead of inventing a large cap.  Every disconnected
    closed shell is allowed to remain in the same logical print object, but is
    validated independently as a positive-volume watertight body.  The one
    pre-clean pipeline call may defer only the signed-volume check: tiny
    inward-wound islands are removed and the survivors coherently oriented
    before the final strict call.  Callers can consequently treat any final
    exception as a transaction failure and retain the original mesh unchanged.
    """

    source_vertices = np.asarray(vertices, dtype=np.float64)
    source_faces = np.asarray(faces, dtype=np.int32)
    source_colors = np.asarray(colors, dtype=np.float64)
    if source_vertices.ndim != 2 or source_vertices.shape[1:] != (3,):
        raise AssemblyError("閉立体化する頂点配列が不正です")
    if source_faces.ndim != 2 or source_faces.shape[1:] != (3,):
        raise AssemblyError("閉立体化する面配列が不正です")
    if source_colors.shape != (len(source_vertices), 3):
        raise AssemblyError("閉立体化する頂点色配列が不正です")
    if not len(source_vertices) or not len(source_faces):
        raise AssemblyError("閉立体化するメッシュが空です")
    if not np.isfinite(source_vertices).all() or not np.isfinite(
        source_colors
    ).all():
        raise AssemblyError("閉立体化する頂点または頂点色に非有限値があります")
    if int(source_faces.min(initial=0)) < 0 or int(
        source_faces.max(initial=-1)
    ) >= len(source_vertices):
        raise AssemblyError("閉立体化する面の頂点番号が範囲外です")

    before = _edge_topology(source_faces, len(source_vertices))
    if bool(before["watertight"]):
        body_volumes = _positive_watertight_body_volumes(
            source_vertices,
            source_faces,
            require_positive_volume=require_positive_volume,
        )
        return (
            source_vertices.copy(),
            source_faces.copy(),
            source_colors.copy(),
            {
                "method": "already_watertight",
                "before": before,
                "after": before,
                "source_vertices": int(len(source_vertices)),
                "output_vertices": int(len(source_vertices)),
                "source_faces": int(len(source_faces)),
                "output_faces": int(len(source_faces)),
                "merged_vertices": 0,
                "body_count": int(len(body_volumes)),
                "minimum_body_volume_unit3": float(min(body_volumes)),
                "maximum_body_volume_unit3": float(max(body_volumes)),
                "positive_volume_validated": bool(require_positive_volume),
                "closed": True,
                "identity": True,
            },
        )
    if int(before["nonmanifold_edges"]):
        raise AssemblyError(
            "同一座標の継ぎ目を統合する前から非多様体辺が "
            f"{before['nonmanifold_edges']} 本あります"
        )
    if int(before["inconsistent_winding_edges"]):
        raise AssemblyError(
            "同一座標の継ぎ目を統合する前から面向き不整合が "
            f"{before['inconsistent_winding_edges']} 本あります"
        )

    # Prove that every indexed boundary is only a duplicated texture seam:
    # each geometric edge must occur exactly twice, with opposite directions.
    # Global coordinate welding is intentionally forbidden because unrelated
    # interior surfaces may legally touch at one position.
    (
        position_values,
        position_inverse,
        position_counts,
    ) = np.unique(
        source_vertices,
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    directed_boundary = _directed_boundary_edges(
        source_faces, len(source_vertices)
    ).astype(np.int64, copy=False)
    if len(directed_boundary) != int(before["boundary_edges"]):
        raise AssemblyError("境界エッジの安全対応を取得できません")
    boundary_positions = position_inverse[directed_boundary]
    if np.any(boundary_positions[:, 0] == boundary_positions[:, 1]):
        raise AssemblyError("同一点へ退化した境界エッジがあるため統合できません")
    edge_lo = np.minimum(boundary_positions[:, 0], boundary_positions[:, 1])
    edge_hi = np.maximum(boundary_positions[:, 0], boundary_positions[:, 1])
    edge_direction = np.where(
        boundary_positions[:, 0] == edge_lo, 1, -1
    ).astype(np.int8)
    edge_keys = edge_lo * np.int64(len(position_values)) + edge_hi
    edge_order = np.argsort(edge_keys, kind="stable")
    sorted_keys = edge_keys[edge_order]
    _keys, edge_starts, edge_counts = np.unique(
        sorted_keys, return_index=True, return_counts=True
    )
    unmatched_edge_groups = int(np.count_nonzero(edge_counts == 1))
    ambiguous_edge_groups = int(np.count_nonzero(edge_counts > 2))
    paired_mask = edge_counts == 2
    paired_starts = edge_starts[paired_mask]
    same_direction_groups = int(
        np.count_nonzero(
            edge_direction[edge_order[paired_starts]]
            == edge_direction[edge_order[paired_starts + 1]]
        )
    )
    if unmatched_edge_groups or ambiguous_edge_groups or same_direction_groups:
        raise AssemblyError(
            "実際の開口、または1対1でない境界があり、"
            "逆向き同一座標継ぎ目だけでは閉じられません: "
            f"相手なし {unmatched_edge_groups}, "
            f"曖昧 {ambiguous_edge_groups}, "
            f"同方向 {same_direction_groups}"
        )

    parent = np.arange(len(source_vertices), dtype=np.int64)

    def find(vertex_id: int) -> int:
        current = int(vertex_id)
        while int(parent[current]) != current:
            parent[current] = parent[int(parent[current])]
            current = int(parent[current])
        return current

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if first_root < second_root:
            parent[second_root] = first_root
        else:
            parent[first_root] = second_root

    for start in paired_starts:
        first_edge = directed_boundary[int(edge_order[int(start)])]
        second_edge = directed_boundary[int(edge_order[int(start) + 1])]
        first_positions = position_inverse[first_edge]
        second_positions = position_inverse[second_edge]
        if not (
            int(first_positions[0]) == int(second_positions[1])
            and int(first_positions[1]) == int(second_positions[0])
        ):
            raise AssemblyError("逆向き境界エッジの端点対応が一致しません")
        union(int(first_edge[0]), int(second_edge[1]))
        union(int(first_edge[1]), int(second_edge[0]))

    while True:
        compressed = parent[parent]
        if np.array_equal(compressed, parent):
            break
        parent = compressed
    stable_roots, inverse = np.unique(parent, return_inverse=True)
    stable_counts = np.bincount(inverse, minlength=len(stable_roots)).astype(
        np.int64
    )
    repaired_vertices = source_vertices[stable_roots].copy()
    if not np.array_equal(repaired_vertices[inverse], source_vertices):
        raise AssemblyError("境界統合で元の三角形座標が変化するため停止しました")
    merged_vertex_count = int(len(source_vertices) - len(repaired_vertices))
    if merged_vertex_count <= 0:
        raise AssemblyError(
            "同一座標の継ぎ目が見つからず、実際の開口を安全に閉じられません"
        )

    repaired_faces = inverse[source_faces].astype(np.int32, copy=False)
    repeated = (
        (repaired_faces[:, 0] == repaired_faces[:, 1])
        | (repaired_faces[:, 1] == repaired_faces[:, 2])
        | (repaired_faces[:, 2] == repaired_faces[:, 0])
    )
    if np.any(repeated):
        raise AssemblyError(
            "同一座標の継ぎ目統合で縮退面が "
            f"{int(np.count_nonzero(repeated))} 面発生するため元形状を保持します"
        )

    colour_sums = np.zeros((len(repaired_vertices), 3), dtype=np.float64)
    np.add.at(colour_sums, inverse, source_colors)
    repaired_colors = colour_sums / stable_counts[:, None]
    colour_adjustment = np.abs(source_colors - repaired_colors[inverse])
    changed_source_vertices = int(
        np.count_nonzero(np.any(colour_adjustment > 1.0e-12, axis=1))
    )

    after = _edge_topology(repaired_faces, len(repaired_vertices))
    if not bool(after["watertight"]):
        raise AssemblyError(
            "同一座標の継ぎ目を統合しても実際の開口が残ります: "
            f"境界 {after['boundary_edges']}, "
            f"非多様体 {after['nonmanifold_edges']}"
        )
    if int(after["inconsistent_winding_edges"]):
        raise AssemblyError(
            "同一座標の継ぎ目統合後に面向き不整合が "
            f"{after['inconsistent_winding_edges']} 本残ります"
        )

    # A single GLB node may intentionally contain many disconnected printable
    # shells.  Keep them in one logical object, but require every shell to be a
    # closed, consistently oriented positive volume before committing.
    body_volumes = _positive_watertight_body_volumes(
        repaired_vertices,
        repaired_faces,
        require_positive_volume=require_positive_volume,
    )

    return (
        repaired_vertices,
        repaired_faces,
        repaired_colors,
        {
            "method": "coincident_vertex_seam_weld",
            "before": before,
            "after": after,
            "source_vertices": int(len(source_vertices)),
            "output_vertices": int(len(repaired_vertices)),
            "source_faces": int(len(source_faces)),
            "output_faces": int(len(repaired_faces)),
            "merged_vertices": merged_vertex_count,
            "coincident_groups": int(np.count_nonzero(stable_counts > 1)),
            "paired_boundary_coordinate_edges": int(len(paired_starts)),
            "unmatched_boundary_coordinate_edges": unmatched_edge_groups,
            "ambiguous_boundary_coordinate_edges": ambiguous_edge_groups,
            "same_direction_boundary_coordinate_edges": same_direction_groups,
            "boundary_pairing_proven": True,
            "global_coincident_vertex_excess": int(
                len(source_vertices) - len(position_values)
            ),
            "unmerged_interior_coincident_vertex_excess": int(
                len(source_vertices)
                - len(position_values)
                - merged_vertex_count
            ),
            "global_coincident_position_groups": int(
                np.count_nonzero(position_counts > 1)
            ),
            "changed_source_vertex_colors": changed_source_vertices,
            "mean_vertex_color_adjustment": float(colour_adjustment.mean()),
            "maximum_vertex_color_adjustment": float(
                colour_adjustment.max(initial=0.0)
            ),
            "body_count": int(len(body_volumes)),
            "minimum_body_volume_unit3": float(min(body_volumes)),
            "maximum_body_volume_unit3": float(max(body_volumes)),
            "positive_volume_validated": bool(require_positive_volume),
            "face_count_preserved": True,
            "face_order_preserved": True,
            "geometry_coordinates_preserved": True,
            "part_identity_preserved": True,
            "closed": True,
            "identity": False,
        },
    )


def split_watertight_bodies(
    mesh: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> tuple[
    list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    dict[str, object],
]:
    """Separate disconnected closed bodies while preserving exact colours."""

    vertices, faces, colors = mesh
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int32)
    colors = np.asarray(colors, dtype=np.float64)
    volume = trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        process=False,
    )
    volume.fix_normals(multibody=True)
    if not volume.is_watertight or not volume.is_volume:
        raise AssemblyError("連結成分の分離には閉じた正体積メッシュが必要です")
    components = list(volume.split(only_watertight=False))
    if not components:
        raise AssemblyError("閉立体の連結成分を取得できません")
    tree = cKDTree(vertices)
    indexed: list[
        tuple[int, tuple[np.ndarray, np.ndarray, np.ndarray], dict[str, object]]
    ] = []
    for component in components:
        component.fix_normals(multibody=True)
        if not component.is_watertight or not component.is_volume:
            raise AssemblyError("分離後に閉立体でない連結成分が見つかりました")
        component_vertices = np.asarray(component.vertices, dtype=np.float64)
        distances, source_indices = tree.query(component_vertices, workers=-1)
        if float(np.max(distances, initial=0.0)) > 1e-10:
            raise AssemblyError("連結成分の分離中に元頂点との対応が失われました")
        component_faces = np.asarray(component.faces, dtype=np.int32)
        source_minimum = int(source_indices.min())
        indexed.append(
            (
                source_minimum,
                (
                    component_vertices,
                    component_faces,
                    colors[source_indices],
                ),
                {
                    "vertices": int(len(component_vertices)),
                    "faces": int(len(component_faces)),
                    "volume_unit3": float(abs(component.volume)),
                },
            )
        )
    indexed.sort(key=lambda value: value[0])
    return (
        [value[1] for value in indexed],
        {
            "body_count": int(len(indexed)),
            "bodies": [value[2] for value in indexed],
        },
    )


def _largest_polygon(value: Polygon | MultiPolygon) -> Polygon:
    if isinstance(value, Polygon):
        return value
    if isinstance(value, MultiPolygon) and len(value.geoms):
        return max(value.geoms, key=lambda polygon: polygon.area)
    raise AssemblyError("継ぎ目の断面を多角形として解釈できません")


def _joint_frame(
    loop: BoundaryLoop,
    *,
    height_mm: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    points_mm = np.asarray(loop.points_unit, dtype=np.float64) * float(height_mm)
    center = points_mm.mean(axis=0)
    _u, _s, vh = np.linalg.svd(points_mm - center, full_matrices=False)
    axis_u = vh[0]
    normal = vh[-1]
    axis_u = axis_u - normal * float(np.dot(axis_u, normal))
    axis_u /= max(float(np.linalg.norm(axis_u)), 1e-12)
    axis_v = np.cross(normal, axis_u)
    axis_v /= max(float(np.linalg.norm(axis_v)), 1e-12)
    coordinates = np.column_stack(
        ((points_mm - center) @ axis_u, (points_mm - center) @ axis_v)
    )
    polygon: Polygon | MultiPolygon = Polygon(coordinates)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    polygon = _largest_polygon(polygon)
    if polygon.area <= 1e-6:
        raise AssemblyError("継ぎ目の断面積が小さすぎます")
    label = polylabel(polygon, tolerance=0.05)
    available_radius = float(label.distance(polygon.boundary))
    origin = (
        center
        + axis_u * float(label.x)
        + axis_v * float(label.y)
    )
    return origin, axis_u, axis_v, normal, available_radius


def _as_volume_mesh(
    vertices_unit: np.ndarray,
    faces: np.ndarray,
    height_mm: float,
) -> trimesh.Trimesh:
    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices_unit, dtype=np.float64) * float(height_mm),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    mesh.fix_normals(multibody=True)
    if not mesh.is_watertight or not mesh.is_volume:
        raise AssemblyError("ジョイント加工には閉じた正体積メッシュが必要です")
    if len(mesh.split(only_watertight=False)) != 1:
        raise AssemblyError(
            "分割対象は1つにつながった閉立体である必要があります"
        )
    return mesh


def _keyed_box(
    center_mm: np.ndarray,
    axis_u: np.ndarray,
    axis_v: np.ndarray,
    axis_depth: np.ndarray,
    width_mm: float,
    height_mm: float,
    depth_mm: float,
) -> trimesh.Trimesh:
    transform = np.eye(4, dtype=np.float64)
    transform[:3, 0] = axis_u
    transform[:3, 1] = axis_v
    transform[:3, 2] = axis_depth
    transform[:3, 3] = center_mm
    return trimesh.creation.box(
        extents=(float(width_mm), float(height_mm), float(depth_mm)),
        transform=transform,
    )


def _transfer_vertex_colors(
    source_vertices: np.ndarray,
    source_colors: np.ndarray,
    target_vertices: np.ndarray,
    source_faces: np.ndarray | None = None,
) -> np.ndarray:
    source_vertices = np.asarray(source_vertices, dtype=np.float64)
    source_colors = np.asarray(source_colors, dtype=np.float64)
    target_vertices = np.asarray(target_vertices, dtype=np.float64)
    if source_faces is None:
        tree = cKDTree(source_vertices)
        indices = tree.query(target_vertices, workers=-1)[1]
        return source_colors[indices]

    source_faces = np.asarray(source_faces, dtype=np.int64)
    source_mesh = trimesh.Trimesh(
        vertices=source_vertices,
        faces=source_faces,
        process=False,
    )
    try:
        closest, _distances, triangle_ids = trimesh.proximity.closest_point(
            source_mesh, target_vertices
        )
    except Exception as exc:
        raise AssemblyError(
            f"立体加工後の色を元表面から補間できません: {exc}"
        ) from exc
    source_triangles = source_vertices[source_faces[triangle_ids]]
    weights = trimesh.triangles.points_to_barycentric(
        source_triangles, closest
    )
    weights = np.clip(weights, 0.0, 1.0)
    weight_sum = weights.sum(axis=1)
    valid = np.isfinite(weights).all(axis=1) & (weight_sum > 1e-12)
    weights[valid] /= weight_sum[valid, None]
    result = np.empty((len(target_vertices), 3), dtype=np.float64)
    result[valid] = np.einsum(
        "ij,ijk->ik",
        weights[valid],
        source_colors[source_faces[triangle_ids[valid]]],
    )
    if not np.all(valid):
        tree = cKDTree(source_vertices)
        indices = tree.query(target_vertices[~valid], workers=-1)[1]
        result[~valid] = source_colors[indices]
    return np.clip(result, 0.0, 1.0)


def add_keyed_joint_for_seam(
    first_mesh: tuple[np.ndarray, np.ndarray, np.ndarray],
    second_mesh: tuple[np.ndarray, np.ndarray, np.ndarray],
    seam: SeamPair,
    *,
    height_mm: float,
    requested_width_mm: float,
    requested_height_mm: float,
    depth_mm: float,
    clearance_mm: float,
) -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
    dict[str, object],
]:
    first_vertices, first_faces, first_colors = first_mesh
    second_vertices, second_faces, second_colors = second_mesh
    origin, axis_u, axis_v, normal, available_radius = _joint_frame(
        seam.first, height_mm=height_mm
    )
    minimum_radius = max(2.0, 0.5 * float(requested_height_mm))
    if available_radius < minimum_radius:
        raise AssemblyError(
            f"継ぎ目内にジョイント用の余白がありません ({available_radius:.2f} mm)"
        )
    scale = min(
        1.0,
        available_radius
        / max(
            0.65
            * float(
                np.hypot(requested_width_mm, requested_height_mm)
            ),
            1e-9,
        ),
    )
    width = max(2.4, float(requested_width_mm) * scale)
    key_height = max(1.8, float(requested_height_mm) * scale)
    depth = max(2.0, float(depth_mm))
    clearance = max(0.05, float(clearance_mm))

    first_volume = _as_volume_mesh(first_vertices, first_faces, height_mm)
    second_volume = _as_volume_mesh(second_vertices, second_faces, height_mm)
    first_centroid = np.asarray(first_volume.center_mass, dtype=np.float64)
    second_centroid = np.asarray(second_volume.center_mass, dtype=np.float64)
    first_inside = first_centroid - origin
    second_inside = second_centroid - origin
    if float(np.dot(first_inside, normal)) < 0.0:
        normal = -normal
    first_inside_normal = normal
    second_inside_normal = -normal

    if len(first_faces) <= len(second_faces):
        male_index = 0
        male_volume, female_volume = first_volume, second_volume
        male_inside = first_inside_normal
        female_inside = second_inside_normal
    else:
        male_index = 1
        male_volume, female_volume = second_volume, first_volume
        male_inside = second_inside_normal
        female_inside = first_inside_normal

    male_outward = -male_inside
    embed = min(1.0, depth * 0.25)
    male_extent = depth + embed
    male_center = origin + male_outward * ((depth - embed) * 0.5)
    male_tool = _keyed_box(
        male_center,
        axis_u,
        axis_v,
        male_outward,
        width,
        key_height,
        male_extent,
    )
    socket_depth = depth + max(0.35, clearance)
    socket_center = origin + female_inside * (socket_depth * 0.5 - 0.5)
    socket_tool = _keyed_box(
        socket_center,
        axis_u,
        axis_v,
        female_inside,
        width + 2.0 * clearance,
        key_height + 2.0 * clearance,
        socket_depth + 1.0,
    )
    try:
        male_result = trimesh.boolean.union(
            [male_volume, male_tool], engine="manifold"
        )
        female_result = trimesh.boolean.difference(
            [female_volume, socket_tool], engine="manifold"
        )
    except Exception as exc:  # pragma: no cover - backend detail varies
        raise AssemblyError(f"ジョイントの立体演算に失敗しました: {exc}") from exc
    if not isinstance(male_result, trimesh.Trimesh) or not isinstance(
        female_result, trimesh.Trimesh
    ):
        raise AssemblyError("ジョイントの立体演算結果がメッシュではありません")
    for label, mesh in (("雄側", male_result), ("雌側", female_result)):
        mesh.fix_normals(multibody=True)
        if not mesh.is_watertight or not mesh.is_volume:
            raise AssemblyError(f"{label}ジョイントが閉立体になりませんでした")
        if len(mesh.split(only_watertight=False)) != 1:
            raise AssemblyError(
                f"{label}ジョイントが本体とつながっていません"
            )

    male_vertices_unit = np.asarray(male_result.vertices) / float(height_mm)
    female_vertices_unit = np.asarray(female_result.vertices) / float(height_mm)
    if male_index == 0:
        first_result = (
            male_vertices_unit,
            np.asarray(male_result.faces, dtype=np.int32),
            _transfer_vertex_colors(
                first_vertices,
                first_colors,
                male_vertices_unit,
                first_faces,
            ),
        )
        second_result = (
            female_vertices_unit,
            np.asarray(female_result.faces, dtype=np.int32),
            _transfer_vertex_colors(
                second_vertices,
                second_colors,
                female_vertices_unit,
                second_faces,
            ),
        )
    else:
        first_result = (
            female_vertices_unit,
            np.asarray(female_result.faces, dtype=np.int32),
            _transfer_vertex_colors(
                first_vertices,
                first_colors,
                female_vertices_unit,
                first_faces,
            ),
        )
        second_result = (
            male_vertices_unit,
            np.asarray(male_result.faces, dtype=np.int32),
            _transfer_vertex_colors(
                second_vertices,
                second_colors,
                male_vertices_unit,
                second_faces,
            ),
        )
    return (
        first_result,
        second_result,
        {
            "seam_id": int(seam.seam_id),
            "parts": [int(seam.first.part_id), int(seam.second.part_id)],
            "male_part": int(
                seam.first.part_id if male_index == 0 else seam.second.part_id
            ),
            "female_part": int(
                seam.second.part_id if male_index == 0 else seam.first.part_id
            ),
            "shape": "keyed_rectangle",
            "center_mm": origin.round(6).tolist(),
            "width_mm": float(width),
            "height_mm": float(key_height),
            "depth_mm": float(depth),
            "clearance_mm": float(clearance),
            "available_radius_mm": float(available_radius),
            "match_rms_mm": float(seam.match_rms_unit * height_mm),
            "match_max_mm": float(seam.match_max_unit * height_mm),
        },
    )


def add_keyed_joints(
    meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    seams: Iterable[SeamPair],
    *,
    height_mm: float,
    width_mm: float,
    key_height_mm: float,
    depth_mm: float,
    clearance_mm: float,
    minimum_span_mm: float,
) -> tuple[
    list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    list[dict[str, object]],
    list[str],
]:
    result = list(meshes)
    records: list[dict[str, object]] = []
    warnings: list[str] = []
    for seam in seams:
        span_mm = min(seam.first.span_unit, seam.second.span_unit) * float(
            height_mm
        )
        if span_mm < float(minimum_span_mm):
            warnings.append(
                f"継ぎ目{seam.seam_id + 1}は小さいためジョイントを省略しました"
            )
            continue
        first_id = seam.first.part_id
        second_id = seam.second.part_id
        try:
            first, second, record = add_keyed_joint_for_seam(
                result[first_id],
                result[second_id],
                seam,
                height_mm=height_mm,
                requested_width_mm=width_mm,
                requested_height_mm=key_height_mm,
                depth_mm=depth_mm,
                clearance_mm=clearance_mm,
            )
        except AssemblyError as exc:
            warnings.append(
                f"継ぎ目{seam.seam_id + 1}のジョイントを省略しました: {exc}"
            )
            continue
        result[first_id] = first
        result[second_id] = second
        records.append(record)
    return result, records, warnings


def _box_from_bounds(bounds: np.ndarray) -> trimesh.Trimesh:
    bounds = np.asarray(bounds, dtype=np.float64)
    extents = bounds[1] - bounds[0]
    if np.any(extents <= 0.0):
        raise AssemblyError("分割用の立体範囲が不正です")
    transform = np.eye(4, dtype=np.float64)
    transform[:3, 3] = bounds.mean(axis=0)
    return trimesh.creation.box(extents=extents, transform=transform)


def split_closed_mesh_with_joint(
    mesh: tuple[np.ndarray, np.ndarray, np.ndarray],
    *,
    height_mm: float,
    axis: str,
    position_percent: float,
    add_joint: bool,
    requested_width_mm: float,
    requested_height_mm: float,
    depth_mm: float,
    clearance_mm: float,
    minimum_span_mm: float = 0.0,
) -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
    dict[str, object],
]:
    vertices, faces, colors = mesh
    volume = _as_volume_mesh(vertices, faces, height_mm)
    axis_name = str(axis).upper()
    if axis_name not in {"X", "Y", "Z"}:
        raise AssemblyError("分割軸はX・Y・Zから選択してください")
    axis_index = {"X": 0, "Y": 1, "Z": 2}[axis_name]
    percent = float(position_percent)
    if not 5.0 <= percent <= 95.0:
        raise AssemblyError("分割位置は5～95%で指定してください")
    bounds = np.asarray(volume.bounds, dtype=np.float64)
    plane_value = float(
        bounds[0, axis_index]
        + (bounds[1, axis_index] - bounds[0, axis_index])
        * percent
        / 100.0
    )
    normal = np.zeros(3, dtype=np.float64)
    normal[axis_index] = 1.0
    plane_origin = bounds.mean(axis=0)
    plane_origin[axis_index] = plane_value
    section = volume.section(
        plane_origin=plane_origin,
        plane_normal=normal,
    )
    if section is None:
        raise AssemblyError("指定位置では形状と分割面が交差しません")
    try:
        path_2d, to_3d = section.to_2D()
        polygons = path_2d.polygons_full
    except Exception as exc:
        raise AssemblyError(f"分割断面を解析できません: {exc}") from exc
    if not polygons:
        raise AssemblyError("分割断面が閉じた輪郭になりません")
    polygon = max(polygons, key=lambda value: value.area)
    label = polylabel(polygon, tolerance=0.05)
    available_radius = float(label.distance(polygon.boundary))
    joint_origin = trimesh.transform_points(
        np.asarray([[label.x, label.y, 0.0]], dtype=np.float64),
        to_3d,
    )[0]
    axis_u = np.asarray(to_3d[:3, 0], dtype=np.float64)
    axis_v = np.asarray(to_3d[:3, 1], dtype=np.float64)
    axis_u /= max(float(np.linalg.norm(axis_u)), 1e-12)
    axis_v /= max(float(np.linalg.norm(axis_v)), 1e-12)

    margin = max(float(np.ptp(bounds, axis=0).max()), float(depth_mm)) + 2.0
    negative_bounds = bounds.copy()
    positive_bounds = bounds.copy()
    negative_bounds[0] -= margin
    positive_bounds[1] += margin
    negative_bounds[1, axis_index] = plane_value
    positive_bounds[0, axis_index] = plane_value
    try:
        negative = trimesh.boolean.intersection(
            [volume, _box_from_bounds(negative_bounds)], engine="manifold"
        )
        positive = trimesh.boolean.intersection(
            [volume, _box_from_bounds(positive_bounds)], engine="manifold"
        )
    except Exception as exc:  # pragma: no cover - backend detail varies
        raise AssemblyError(f"平面分割の立体演算に失敗しました: {exc}") from exc
    if not isinstance(negative, trimesh.Trimesh) or not isinstance(
        positive, trimesh.Trimesh
    ):
        raise AssemblyError("平面分割結果がメッシュではありません")
    for label_name, split_mesh in (("A側", negative), ("B側", positive)):
        split_mesh.fix_normals(multibody=True)
        if not split_mesh.is_watertight or not split_mesh.is_volume:
            raise AssemblyError(f"分割後の{label_name}が閉立体になりません")
        if len(split_mesh.split(only_watertight=False)) != 1:
            raise AssemblyError(
                f"分割後の{label_name}が複数の離れた形状になります。"
                "分割軸または位置を変更してください"
            )

    joint_record: dict[str, object] = {
        "type": "plane_split",
        "axis": axis_name,
        "position_percent": percent,
        "plane_mm": float(plane_value),
        "joint": None,
    }
    if add_joint:
        minimum_radius = max(
            2.0,
            0.5 * float(requested_height_mm),
            0.5 * max(0.0, float(minimum_span_mm)),
        )
        if available_radius < minimum_radius:
            raise AssemblyError(
                "分割断面にジョイント用の余白がありません: "
                f"{available_radius:.2f} mm"
            )
        scale = min(
            1.0,
            available_radius
            / max(
                0.65
                * float(
                    np.hypot(requested_width_mm, requested_height_mm)
                ),
                1e-9,
            ),
        )
        width = max(2.4, float(requested_width_mm) * scale)
        key_height = max(1.8, float(requested_height_mm) * scale)
        depth = max(2.0, float(depth_mm))
        clearance = max(0.05, float(clearance_mm))
        negative_is_male = abs(float(negative.volume)) <= abs(
            float(positive.volume)
        )
        if negative_is_male:
            male, female = negative, positive
            male_inside, female_inside = -normal, normal
            male_name, female_name = "A", "B"
        else:
            male, female = positive, negative
            male_inside, female_inside = normal, -normal
            male_name, female_name = "B", "A"
        male_outward = -male_inside
        embed = min(1.0, depth * 0.25)
        male_tool = _keyed_box(
            joint_origin + male_outward * ((depth - embed) * 0.5),
            axis_u,
            axis_v,
            male_outward,
            width,
            key_height,
            depth + embed,
        )
        socket_depth = depth + max(0.35, clearance)
        socket_tool = _keyed_box(
            joint_origin + female_inside * (socket_depth * 0.5 - 0.5),
            axis_u,
            axis_v,
            female_inside,
            width + 2.0 * clearance,
            key_height + 2.0 * clearance,
            socket_depth + 1.0,
        )
        male_result = trimesh.boolean.union(
            [male, male_tool], engine="manifold"
        )
        female_result = trimesh.boolean.difference(
            [female, socket_tool], engine="manifold"
        )
        if not isinstance(male_result, trimesh.Trimesh) or not isinstance(
            female_result, trimesh.Trimesh
        ):
            raise AssemblyError("分割ジョイントの立体演算に失敗しました")
        for label_name, joint_mesh in (
            ("雄側", male_result),
            ("雌側", female_result),
        ):
            joint_mesh.fix_normals(multibody=True)
            if not joint_mesh.is_watertight or not joint_mesh.is_volume:
                raise AssemblyError(
                    f"分割後の{label_name}ジョイントが閉立体になりません"
                )
            if len(joint_mesh.split(only_watertight=False)) != 1:
                raise AssemblyError(
                    f"分割後の{label_name}ジョイントが複数の離れた形状です"
                )
        if negative_is_male:
            negative, positive = male_result, female_result
        else:
            positive, negative = male_result, female_result
        joint_record["joint"] = {
            "shape": "keyed_rectangle",
            "center_mm": joint_origin.round(6).tolist(),
            "male_side": male_name,
            "female_side": female_name,
            "width_mm": float(width),
            "height_mm": float(key_height),
            "depth_mm": float(depth),
            "clearance_mm": float(clearance),
            "minimum_span_mm": float(max(0.0, minimum_span_mm)),
            "available_radius_mm": float(available_radius),
        }

    source_vertices = np.asarray(vertices, dtype=np.float64)
    negative_vertices = np.asarray(negative.vertices) / float(height_mm)
    positive_vertices = np.asarray(positive.vertices) / float(height_mm)
    negative_result = (
        negative_vertices,
        np.asarray(negative.faces, dtype=np.int32),
        _transfer_vertex_colors(
            source_vertices, colors, negative_vertices, faces
        ),
    )
    positive_result = (
        positive_vertices,
        np.asarray(positive.faces, dtype=np.int32),
        _transfer_vertex_colors(
            source_vertices, colors, positive_vertices, faces
        ),
    )
    joint_record["result_faces"] = [
        int(len(negative_result[1])),
        int(len(positive_result[1])),
    ]
    return negative_result, positive_result, joint_record


def mesh_is_watertight(vertices: np.ndarray, faces: np.ndarray) -> bool:
    return bool(_edge_topology(faces, len(vertices))["watertight"])


__all__ = [
    "AssemblyError",
    "BoundaryLoop",
    "SeamPair",
    "add_keyed_joint_for_seam",
    "add_keyed_joints",
    "close_open_mesh",
    "find_boundary_loops",
    "mesh_is_watertight",
    "pair_matching_loops",
    "repair_small_unmatched_boundaries",
    "solidify_coincident_shells",
    "solidify_partitioned_parts",
    "split_watertight_bodies",
    "split_closed_mesh_with_joint",
    "weld_matching_seams",
]
