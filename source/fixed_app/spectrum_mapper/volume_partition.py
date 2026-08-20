"""Safe volumetric fallback for curved Tripo part boundaries.

The normal path in :mod:`spectrum_mapper.assembly` closes a near-planar pair
of source boundaries with an identical shared cap.  Some Tripo exports use
strongly warped cuts, where a planar cap can cross the visible surface.  This
module repairs the assembled shell with fTetWild and then restores the source
part identities by recursive, binary harmonic partitions.  Every generated
surface is validated before it can reach a 3MF export.

The implementation is rule-based geometry processing.  It runs locally and
does not call Codex, a network API, or a generative model.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Iterable

import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import spsolve
import trimesh

from .assembly import (
    AssemblyError,
    SeamPair,
    _edge_topology,
    _strict_mesh_record,
    weld_matching_seams,
)
from .generated_surface_color import encode_face_ranges
from .models import ProgressCallback


class VolumePartitionError(RuntimeError):
    """Raised when a curved partition cannot be made print-safe."""


TET_LOCAL_FACES = np.asarray(
    ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)),
    dtype=np.int32,
)
TET_EDGES = np.asarray(
    ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
    dtype=np.int32,
)

_DLL_HANDLES: list[object] = []
_TETWILD_WRAPPER: object | None = None
_TETWILD_CWD_LOCK = threading.Lock()


def _emit(
    progress: ProgressCallback | None,
    stage: str,
    fraction: float,
    message: str,
) -> None:
    if progress is not None:
        progress(stage, float(fraction), message)


def _load_tetwild_wrapper():
    """Load the small compiled wrapper without importing optional PyVista."""

    global _TETWILD_WRAPPER
    if _TETWILD_WRAPPER is not None:
        return _TETWILD_WRAPPER

    package_directories: list[Path] = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        package_directories.append(Path(frozen_root) / "pytetwild")
    try:
        package_spec = importlib.util.find_spec("pytetwild")
    except (ImportError, ModuleNotFoundError, ValueError):
        package_spec = None
    if package_spec is not None and package_spec.submodule_search_locations:
        package_directories.extend(
            Path(value) for value in package_spec.submodule_search_locations
        )

    checked: list[str] = []
    for package_directory in package_directories:
        checked.append(str(package_directory))
        if not package_directory.is_dir():
            continue
        library_directory = package_directory.parent / "pytetwild.libs"
        if library_directory.is_dir() and hasattr(os, "add_dll_directory"):
            _DLL_HANDLES.append(os.add_dll_directory(str(library_directory)))
        extensions = sorted(package_directory.glob("PyfTetWildWrapper*.pyd"))
        if not extensions:
            continue
        module_spec = importlib.util.spec_from_file_location(
            "PyfTetWildWrapper", extensions[0]
        )
        if module_spec is None or module_spec.loader is None:
            continue
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        _TETWILD_WRAPPER = module
        return module
    raise VolumePartitionError(
        "曲面境界用のfTetWild実行モジュールを読み込めません。"
        "アプリを配布フォルダーごと再展開してください"
        + (f"（確認先: {', '.join(checked)}）" if checked else "")
    )


def _tetra_face_table(
    elements: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw_faces = elements[:, TET_LOCAL_FACES].reshape(-1, 3)
    canonical = np.sort(raw_faces, axis=1)
    order = np.lexsort(
        (canonical[:, 2], canonical[:, 1], canonical[:, 0])
    )
    ordered = canonical[order]
    changed = np.ones(len(ordered), dtype=bool)
    changed[1:] = np.any(ordered[1:] != ordered[:-1], axis=1)
    starts = np.flatnonzero(changed)
    counts = np.diff(np.append(starts, len(ordered)))
    return raw_faces, order, starts, counts


def _oriented_boundary_faces(
    nodes: np.ndarray,
    elements: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    raw_faces, order, starts, counts = _tetra_face_table(elements)
    if np.any(counts > 2):
        raise VolumePartitionError(
            "体積メッシュ内部に3個以上の四面体が共有する面があります"
        )
    rows = order[starts[counts == 1]]
    faces = raw_faces[rows].copy()
    owners = (rows // 4).astype(np.int32)
    opposite_local = rows % 4
    opposite = elements[owners, opposite_local]
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
    return faces.astype(np.int32), owners


def _tetra_volumes(nodes: np.ndarray, elements: np.ndarray) -> np.ndarray:
    matrices = nodes[elements[:, 1:]] - nodes[elements[:, 0, None]]
    return np.abs(np.linalg.det(matrices)) / 6.0


def _boundary_edge_defects(
    faces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int]:
    edges = np.vstack(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])
    ).astype(np.int32)
    edges.sort(axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    bad = counts != 2
    defect = int(np.sum(np.abs(counts[bad] - 2)))
    return unique[bad], counts[bad], defect


def _tetra_component_labels(elements: np.ndarray) -> tuple[int, np.ndarray]:
    _raw, order, starts, counts = _tetra_face_table(elements)
    paired = starts[counts == 2]
    if not len(paired):
        return len(elements), np.arange(len(elements), dtype=np.int32)
    left = (order[paired] // 4).astype(np.int32)
    right = (order[paired + 1] // 4).astype(np.int32)
    graph = coo_matrix(
        (
            np.ones(len(left) * 2, dtype=np.uint8),
            (
                np.concatenate((left, right)),
                np.concatenate((right, left)),
            ),
        ),
        shape=(len(elements), len(elements)),
    ).tocsr()
    return connected_components(graph, directed=False)


def _compact_tetra_nodes(
    nodes: np.ndarray, elements: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    used = np.unique(elements)
    remap = np.full(len(nodes), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    return nodes[used], remap[elements].astype(np.int32)


def _clean_tetra_complex(
    nodes: np.ndarray,
    elements: np.ndarray,
    *,
    maximum_removed_volume_fraction: float = 1e-5,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """Remove only tiny disconnected or boundary-pinch tetrahedra."""

    raw_nodes = np.asarray(nodes)
    raw_elements = np.asarray(elements)
    try:
        removal_limit = float(maximum_removed_volume_fraction)
    except (TypeError, ValueError, OverflowError) as exc:
        raise VolumePartitionError("体積除去率の安全上限が不正です") from exc
    if (
        raw_nodes.ndim != 2
        or raw_nodes.shape[1] != 3
        or raw_elements.ndim != 2
        or raw_elements.shape[1] != 4
        or not len(raw_nodes)
        or not len(raw_elements)
        or not (
            np.issubdtype(raw_nodes.dtype, np.integer)
            or np.issubdtype(raw_nodes.dtype, np.floating)
        )
        or not np.issubdtype(raw_elements.dtype, np.integer)
        or not np.isfinite(raw_nodes).all()
        or not np.isfinite(removal_limit)
        or removal_limit < 0.0
        or removal_limit > 1.0
    ):
        raise VolumePartitionError("fTetWildの体積メッシュ形式が不正です")
    minimum_index = int(raw_elements.min())
    maximum_index = int(raw_elements.max())
    if minimum_index < 0 or maximum_index >= len(raw_nodes):
        raise VolumePartitionError("fTetWildの四面体indexが範囲外です")
    nodes = np.asarray(raw_nodes, dtype=np.float64)
    elements = np.asarray(raw_elements, dtype=np.int32)
    original_node_count = len(nodes)
    canonical_elements = np.sort(elements, axis=1)
    if len(np.unique(canonical_elements, axis=0)) != len(elements):
        raise VolumePartitionError("fTetWildの体積メッシュに重複四面体があります")
    original_count = len(elements)
    original_volumes = _tetra_volumes(nodes, elements)
    total_volume = float(original_volumes.sum())
    if total_volume <= 0.0 or not np.isfinite(total_volume):
        raise VolumePartitionError("fTetWildの体積が正値になりません")
    nondegenerate = original_volumes > max(total_volume * 1e-15, 1e-18)
    removed_indices: list[int] = np.flatnonzero(~nondegenerate).astype(int).tolist()
    elements = elements[nondegenerate]

    component_count, component_labels = _tetra_component_labels(elements)
    if component_count > 1:
        component_volumes = np.bincount(
            component_labels,
            weights=_tetra_volumes(nodes, elements),
            minlength=component_count,
        )
        keep_component = int(np.argmax(component_volumes))
        discarded_volume = float(component_volumes.sum() - component_volumes[keep_component])
        if discarded_volume / total_volume > removal_limit:
            raise VolumePartitionError(
                "fTetWild体積が複数の大きな塊へ分断されています"
            )
        keep = component_labels == keep_component
        removed_indices.extend(np.flatnonzero(~keep).astype(int).tolist())
        elements = elements[keep]

    removed_pinch_tetrahedra = 0
    two_step_lookahead_repairs = 0
    initial_bad_edges = 0
    while True:
        boundary_faces, boundary_owners = _oriented_boundary_faces(nodes, elements)
        if not len(boundary_faces):
            raise VolumePartitionError("fTetWildの体積メッシュに外側境界面がありません")
        bad_edges, _bad_counts, defect = _boundary_edge_defects(boundary_faces)
        if initial_bad_edges == 0:
            initial_bad_edges = int(len(bad_edges))
        if not len(bad_edges):
            break
        if removed_pinch_tetrahedra >= 32:
            raise VolumePartitionError(
                "fTetWild境界の非多様体pinchを32回以内に解消できません"
            )
        candidate_counter: Counter[int] = Counter()
        for edge in bad_edges:
            incident = np.sum(np.isin(boundary_faces, edge), axis=1) == 2
            candidate_counter.update(int(value) for value in boundary_owners[incident])
        if not candidate_counter:
            raise VolumePartitionError("非多様体境界に対応する四面体を特定できません")
        volumes = _tetra_volumes(nodes, elements)
        candidates = sorted(
            candidate_counter,
            key=lambda value: (
                -candidate_counter[value],
                float(volumes[value]),
                int(value),
            ),
        )[:16]
        current_volume = float(volumes.sum())
        already_removed = total_volume - current_volume
        remaining_volume_budget = removal_limit * total_volume - already_removed
        volume_blocked = False
        best: tuple[tuple[int, int, float, int], np.ndarray] | None = None
        for candidate in candidates:
            trial = np.delete(elements, candidate, axis=0)
            try:
                trial_boundary, _owners = _oriented_boundary_faces(nodes, trial)
            except VolumePartitionError:
                continue
            if not len(trial_boundary):
                continue
            _trial_bad, _trial_counts, trial_defect = _boundary_edge_defects(
                trial_boundary
            )
            if trial_defect >= defect:
                continue
            removed_volume = float(volumes[candidate])
            if removed_volume > remaining_volume_budget:
                volume_blocked = True
                continue
            score = (
                int(trial_defect),
                -candidate_counter[candidate],
                removed_volume,
                int(candidate),
            )
            if best is None or score < best[0]:
                best = (score, trial)

        # Some boundary pinches have a one-removal plateau: no single
        # deletion improves the defect, but a validated pair does.  Search a
        # deliberately small, deterministic two-step neighborhood only as a
        # fallback.  Both deletions are committed together after confirming
        # lower defect, one connected volume, and the same removal budget.
        if best is None:
            best_pair: tuple[
                tuple[int, int, int, float, int, int], np.ndarray
            ] | None = None
            if removed_pinch_tetrahedra <= 30:
                for first_candidate in candidates[:8]:
                    first_volume = float(volumes[first_candidate])
                    if first_volume > remaining_volume_budget:
                        volume_blocked = True
                        continue
                    first_trial = np.delete(elements, first_candidate, axis=0)
                    try:
                        first_boundary, first_owners = _oriented_boundary_faces(
                            nodes, first_trial
                        )
                    except VolumePartitionError:
                        continue
                    if not len(first_boundary):
                        continue
                    first_bad, _counts, first_defect = _boundary_edge_defects(
                        first_boundary
                    )
                    if first_defect > defect or not len(first_bad):
                        continue
                    first_counter: Counter[int] = Counter()
                    for edge in first_bad:
                        incident = (
                            np.sum(np.isin(first_boundary, edge), axis=1) == 2
                        )
                        first_counter.update(
                            int(value) for value in first_owners[incident]
                        )
                    first_volumes = _tetra_volumes(nodes, first_trial)
                    second_candidates = sorted(
                        first_counter,
                        key=lambda value: (
                            -first_counter[value],
                            float(first_volumes[value]),
                            int(value),
                        ),
                    )[:8]
                    for second_candidate in second_candidates:
                        pair_volume = first_volume + float(
                            first_volumes[second_candidate]
                        )
                        if pair_volume > remaining_volume_budget:
                            volume_blocked = True
                            continue
                        second_trial = np.delete(
                            first_trial, second_candidate, axis=0
                        )
                        try:
                            second_boundary, _owners = _oriented_boundary_faces(
                                nodes, second_trial
                            )
                        except VolumePartitionError:
                            continue
                        if not len(second_boundary):
                            continue
                        second_components, _labels = _tetra_component_labels(
                            second_trial
                        )
                        if second_components != 1:
                            continue
                        _second_bad, _counts, second_defect = (
                            _boundary_edge_defects(second_boundary)
                        )
                        if second_defect >= defect:
                            continue
                        pair_score = (
                            int(second_defect),
                            -candidate_counter[first_candidate],
                            -first_counter[second_candidate],
                            float(pair_volume),
                            int(first_candidate),
                            int(second_candidate),
                        )
                        if best_pair is None or pair_score < best_pair[0]:
                            best_pair = (pair_score, second_trial)
            if best_pair is not None:
                elements = best_pair[1]
                removed_pinch_tetrahedra += 2
                two_step_lookahead_repairs += 1
                continue
            if volume_blocked:
                raise VolumePartitionError(
                    "非多様体pinch修復に必要な体積除去量が安全上限を超えます"
                )
            raise VolumePartitionError(
                "fTetWild境界の非多様体pinchを安全な局所除去で解消できません"
            )
        elements = best[1]
        removed_pinch_tetrahedra += 1

    final_component_count, _labels = _tetra_component_labels(elements)
    if final_component_count != 1:
        raise VolumePartitionError("修復後の体積メッシュが1つにつながっていません")
    final_volume = float(_tetra_volumes(nodes, elements).sum())
    removed_fraction = max(0.0, (total_volume - final_volume) / total_volume)
    if removed_fraction > removal_limit:
        raise VolumePartitionError("体積メッシュ修復による体積差が上限を超えます")
    nodes, elements = _compact_tetra_nodes(nodes, elements)
    final_boundary, _owners = _oriented_boundary_faces(nodes, elements)
    if not len(final_boundary):
        raise VolumePartitionError("修復後の体積メッシュに外側境界面がありません")
    final_bad, _counts, _defect = _boundary_edge_defects(final_boundary)
    if len(final_bad):
        raise VolumePartitionError("修復後も体積境界に非多様体辺が残っています")
    return nodes, elements, {
        "input_nodes": int(original_node_count),
        "input_tetrahedra": int(original_count),
        "output_nodes": int(len(nodes)),
        "output_tetrahedra": int(len(elements)),
        "initial_nonmanifold_boundary_edges": int(initial_bad_edges),
        "removed_degenerate_or_disconnected": int(len(removed_indices)),
        "removed_boundary_pinch_tetrahedra": int(removed_pinch_tetrahedra),
        "two_step_lookahead_repairs": int(two_step_lookahead_repairs),
        "removed_volume_fraction": float(removed_fraction),
        "boundary_faces": int(len(final_boundary)),
    }


def _tetwild_tetrahedralize(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    started = time.perf_counter()
    try:
        # fTetWild writes ``__tracked_surface.stl`` into the process working
        # directory.  Since cwd is process-global, serialize this whole block
        # and isolate every invocation in a disposable directory.
        with _TETWILD_CWD_LOCK:
            wrapper = _load_tetwild_wrapper()
            previous_cwd = Path.cwd()
            with tempfile.TemporaryDirectory(prefix="tripo_tetwild_") as work:
                try:
                    os.chdir(work)
                    nodes, elements = wrapper.tetrahedralize_mesh(
                        np.asarray(vertices, dtype=np.float64),
                        np.asarray(faces, dtype=np.uint32),
                        True,  # optimize
                        False,  # allow safe envelope simplification
                        0.05,  # target edge length / bounding-box diagonal
                        0.0,  # no absolute edge length
                        5e-4,  # maximum surface envelope
                        10.0,  # stop energy
                        False,  # coarsen
                        0,  # all available threads
                        10,  # bounded optimization iterations
                        3,
                        True,  # quiet
                        False,  # native tetra ordering
                        False,  # keep only the interior volume
                    )
                finally:
                    os.chdir(previous_cwd)
    except Exception as exc:
        raise VolumePartitionError(
            f"fTetWildで曲面境界の体積化に失敗しました: {exc}"
        ) from exc
    raw_nodes = np.asarray(nodes, dtype=np.float64)
    raw_elements = np.asarray(elements, dtype=np.int32)
    clean_nodes, clean_elements, cleanup = _clean_tetra_complex(
        raw_nodes, raw_elements
    )
    return clean_nodes, clean_elements, {
        "engine": "fTetWild",
        "input_vertices": int(len(vertices)),
        "input_faces": int(len(faces)),
        "raw_nodes": int(len(raw_nodes)),
        "raw_tetrahedra": int(len(raw_elements)),
        "seconds": float(time.perf_counter() - started),
        "settings": {
            "edge_length_factor": 0.05,
            "epsilon": 5e-4,
            "optimization_iterations": 10,
        },
        "cleanup": cleanup,
    }


def _exact_tetrahedralize(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_markers: np.ndarray,
    *,
    part_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    try:
        import tetgen
    except Exception as exc:
        raise VolumePartitionError(
            "再帰分割用のTetGen実行モジュールを読み込めません"
        ) from exc
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int32)
    face_markers = np.asarray(face_markers, dtype=np.int32)
    encoded = np.where(
        face_markers >= 0,
        face_markers + 1,
        part_count + (-face_markers),
    ).astype(np.int32)
    started = time.perf_counter()
    try:
        generator = tetgen.TetGen(vertices, faces, encoded)
        nodes, elements, _attributes, _markers = generator.tetrahedralize(
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
        raise VolumePartitionError(
            f"閉立体の再帰四面体化に失敗しました: {exc}"
        ) from exc
    nodes = np.asarray(nodes, dtype=np.float64)
    elements = np.asarray(elements, dtype=np.int32)
    if len(nodes) < len(vertices) or not np.allclose(
        nodes[: len(vertices)], vertices, rtol=0.0, atol=1e-12
    ):
        raise VolumePartitionError("TetGenが既存の共有面頂点を保持しませんでした")
    boundary_faces, _owners = _oriented_boundary_faces(nodes, elements)
    lookup = {
        tuple(int(value) for value in np.sort(face)): int(marker)
        for face, marker in zip(faces, face_markers, strict=True)
    }
    boundary_markers = np.asarray(
        [
            lookup.get(tuple(int(value) for value in np.sort(face)), -2**30)
            for face in boundary_faces
        ],
        dtype=np.int32,
    )
    if np.any(boundary_markers == -2**30) or len(boundary_faces) != len(faces):
        raise VolumePartitionError("TetGenが既存の共有面三角形を完全保持しませんでした")
    return nodes, elements, boundary_faces, boundary_markers, {
        "engine": "TetGen",
        "input_vertices": int(len(vertices)),
        "input_faces": int(len(faces)),
        "nodes": int(len(nodes)),
        "tetrahedra": int(len(elements)),
        "seconds": float(time.perf_counter() - started),
        "boundary_preserved": True,
    }


def _closest_surface_labels(
    nodes: np.ndarray,
    boundary_faces: np.ndarray,
    surface_vertices: np.ndarray,
    surface_faces: np.ndarray,
    surface_labels: np.ndarray,
) -> tuple[np.ndarray, dict[str, float]]:
    centers = nodes[boundary_faces].mean(axis=1)
    source = trimesh.Trimesh(
        vertices=surface_vertices,
        faces=surface_faces,
        process=False,
    )
    distances: list[np.ndarray] = []
    triangles: list[np.ndarray] = []
    for start in range(0, len(centers), 20_000):
        _closest, distance, triangle_ids = trimesh.proximity.closest_point(
            source, centers[start : start + 20_000]
        )
        distances.append(np.asarray(distance, dtype=np.float64))
        triangles.append(np.asarray(triangle_ids, dtype=np.int64))
    distance = np.concatenate(distances)
    triangle_ids = np.concatenate(triangles)
    return np.asarray(surface_labels[triangle_ids], dtype=np.int32), {
        "face_center_distance_max_unit": float(
            np.max(distance, initial=0.0)
        ),
        "face_center_distance_p99_unit": float(
            np.quantile(distance, 0.99) if len(distance) else 0.0
        ),
        "face_center_distance_mean_unit": float(
            np.mean(distance) if len(distance) else 0.0
        ),
    }


def _surface_distance_record(
    source_vertices: np.ndarray,
    source_faces: np.ndarray,
    target_vertices: np.ndarray,
    target_faces: np.ndarray,
    *,
    height_mm: float,
) -> dict[str, float]:
    source = trimesh.Trimesh(
        vertices=source_vertices, faces=source_faces, process=False
    )
    target = trimesh.Trimesh(
        vertices=target_vertices, faces=target_faces, process=False
    )

    def distances(mesh: trimesh.Trimesh, query: np.ndarray) -> np.ndarray:
        values: list[np.ndarray] = []
        for start in range(0, len(query), 20_000):
            _closest, distance, _ids = trimesh.proximity.closest_point(
                mesh, query[start : start + 20_000]
            )
            values.append(np.asarray(distance, dtype=np.float64))
        return np.concatenate(values) if values else np.empty(0)

    target_surface_vertices = target_vertices[np.unique(target_faces)]
    forward = distances(source, target_surface_vertices)
    reverse = distances(target, source_vertices)
    scale = float(height_mm)
    return {
        "output_to_source_max_mm": float(
            np.max(forward, initial=0.0) * scale
        ),
        "output_to_source_p99_mm": float(
            (np.quantile(forward, 0.99) if len(forward) else 0.0) * scale
        ),
        "source_to_output_max_mm": float(
            np.max(reverse, initial=0.0) * scale
        ),
        "source_to_output_p99_mm": float(
            (np.quantile(reverse, 0.99) if len(reverse) else 0.0) * scale
        ),
    }


def _solve_active_harmonic(
    nodes: np.ndarray,
    elements: np.ndarray,
    boundary_faces: np.ndarray,
    boundary_markers: np.ndarray,
    *,
    leaf_label: int,
    active_labels: set[int],
) -> tuple[np.ndarray, dict[str, object]]:
    """Solve one negative-leaf/positive-rest Dirichlet field."""

    started = time.perf_counter()
    first = nodes[boundary_faces[:, 0]]
    areas = 0.5 * np.linalg.norm(
        np.cross(
            nodes[boundary_faces[:, 1]] - first,
            nodes[boundary_faces[:, 2]] - first,
        ),
        axis=1,
    )
    rest_labels = active_labels - {int(leaf_label)}
    valid = np.asarray(
        [int(value) in active_labels for value in boundary_markers],
        dtype=bool,
    )
    signs = np.zeros(len(boundary_faces), dtype=np.float64)
    signs[boundary_markers == int(leaf_label)] = -1.0
    signs[
        np.asarray(
            [int(value) in rest_labels for value in boundary_markers],
            dtype=bool,
        )
    ] = 1.0
    if not np.any(signs[valid] < 0.0) or not np.any(signs[valid] > 0.0):
        raise VolumePartitionError(
            f"パーツ{leaf_label + 1}と残りの外面に正負両方の境界がありません"
        )
    numerator = np.zeros(len(nodes), dtype=np.float64)
    denominator = np.zeros(len(nodes), dtype=np.float64)
    np.add.at(
        numerator,
        boundary_faces[valid].ravel(),
        np.repeat(areas[valid] * signs[valid], 3),
    )
    np.add.at(
        denominator,
        boundary_faces[valid].ravel(),
        np.repeat(areas[valid], 3),
    )
    fixed = denominator > 0.0
    fixed_values = np.zeros(len(nodes), dtype=np.float64)
    fixed_values[fixed] = numerator[fixed] / denominator[fixed]

    # Exact zero nodes create ambiguous marching-tetrahedra topology.  Resolve
    # a perfect area tie toward the largest incident labelled face, which is a
    # deterministic local decision and moves the interface by only roundoff.
    ambiguous = fixed & np.isclose(fixed_values, 0.0, atol=1e-14)
    if np.any(ambiguous):
        dominant_area = np.zeros(len(nodes), dtype=np.float64)
        dominant_sign = np.ones(len(nodes), dtype=np.float64)
        for face, area, sign, is_valid in zip(
            boundary_faces, areas, signs, valid, strict=True
        ):
            if not is_valid:
                continue
            for vertex_id in face:
                index = int(vertex_id)
                if float(area) > dominant_area[index]:
                    dominant_area[index] = float(area)
                    dominant_sign[index] = float(sign)
        fixed_values[ambiguous] = dominant_sign[ambiguous] * 1e-12

    edges = np.vstack(
        [elements[:, pair] for pair in TET_EDGES]
    ).astype(np.int32, copy=False)
    edges.sort(axis=1)
    edges = np.unique(edges, axis=0)
    lengths = np.linalg.norm(
        nodes[edges[:, 0]] - nodes[edges[:, 1]], axis=1
    )
    weights = 1.0 / np.maximum(lengths, 1e-12)
    adjacency = coo_matrix(
        (
            np.concatenate((weights, weights)),
            (
                np.concatenate((edges[:, 0], edges[:, 1])),
                np.concatenate((edges[:, 1], edges[:, 0])),
            ),
        ),
        shape=(len(nodes), len(nodes)),
    ).tocsr()
    laplacian = diags(np.asarray(adjacency.sum(axis=1)).ravel()) - adjacency
    free = ~fixed
    free_ids = np.flatnonzero(free)
    fixed_ids = np.flatnonzero(fixed)
    result = fixed_values.copy()
    solve_started = time.perf_counter()
    if len(free_ids):
        matrix = laplacian[free_ids][:, free_ids].tocsc()
        right_hand = -laplacian[free_ids][:, fixed_ids] @ fixed_values[fixed_ids]
        result[free_ids] = spsolve(matrix, right_hand)
        residual = matrix @ result[free_ids] - right_hand
        residual_linf = float(np.max(np.abs(residual), initial=0.0))
    else:
        residual_linf = 0.0
    if not np.isfinite(result).all():
        raise VolumePartitionError("調和場の解に非数が発生しました")
    result = np.clip(result, -1.0, 1.0)
    exact_zero = np.isclose(result, 0.0, rtol=0.0, atol=1e-15)
    if np.any(exact_zero):
        neighbor_sum = adjacency @ result
        neighbor_weight = np.asarray(adjacency.sum(axis=1)).ravel()
        direction = neighbor_sum / np.maximum(neighbor_weight, 1e-15)
        direction[direction == 0.0] = 1.0
        result[exact_zero] = np.sign(direction[exact_zero]) * 1e-14
    return result, {
        "leaf_label": int(leaf_label),
        "active_labels": sorted(int(value) for value in active_labels),
        "fixed_boundary_nodes": int(np.count_nonzero(fixed)),
        "free_nodes": int(np.count_nonzero(free)),
        "fixed_negative": int(np.count_nonzero(fixed_values[fixed] < 0.0)),
        "fixed_positive": int(np.count_nonzero(fixed_values[fixed] > 0.0)),
        "retired_or_interface_faces": int(np.count_nonzero(~valid)),
        "ambiguous_boundary_nodes_resolved": int(np.count_nonzero(ambiguous)),
        "residual_linf": residual_linf,
        "solve_seconds": float(time.perf_counter() - solve_started),
        "seconds": float(time.perf_counter() - started),
    }


class _ZeroVertexRegistry:
    def __init__(self, nodes: np.ndarray, scalar: np.ndarray) -> None:
        self.nodes = nodes
        self.scalar = scalar
        self.extra: list[np.ndarray] = []
        self.by_edge: dict[tuple[int, int], int] = {}

    def intersection(self, first: int, second: int) -> int:
        first = int(first)
        second = int(second)
        first_value = float(self.scalar[first])
        second_value = float(self.scalar[second])
        if first_value == 0.0:
            return first
        if second_value == 0.0:
            return second
        if first_value * second_value >= 0.0:
            raise VolumePartitionError(
                "符号が交差しない辺で分割点が要求されました"
            )
        key = (min(first, second), max(first, second))
        existing = self.by_edge.get(key)
        if existing is not None:
            return existing
        ratio = first_value / (first_value - second_value)
        position = self.nodes[first] + ratio * (
            self.nodes[second] - self.nodes[first]
        )
        vertex_id = len(self.nodes) + len(self.extra)
        self.extra.append(np.asarray(position, dtype=np.float64))
        self.by_edge[key] = vertex_id
        return vertex_id

    def coordinates(self, vertex_ids: Iterable[int]) -> np.ndarray:
        result: list[np.ndarray] = []
        for value in vertex_ids:
            vertex_id = int(value)
            if vertex_id < len(self.nodes):
                result.append(self.nodes[vertex_id])
            else:
                result.append(self.extra[vertex_id - len(self.nodes)])
        return np.asarray(result, dtype=np.float64)

    def array(self) -> np.ndarray:
        if not self.extra:
            return self.nodes.copy()
        return np.vstack((self.nodes, np.asarray(self.extra, dtype=np.float64)))


def _deduplicate_cycle(values: Iterable[int]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        item = int(value)
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _clip_triangle(
    face: np.ndarray,
    scalar: np.ndarray,
    registry: _ZeroVertexRegistry,
    *,
    keep_negative: bool,
) -> list[int]:
    polygon = [int(value) for value in face]
    output: list[int] = []
    previous = polygon[-1]
    previous_inside = (
        float(scalar[previous]) <= 0.0
        if keep_negative
        else float(scalar[previous]) >= 0.0
    )
    for current in polygon:
        current_inside = (
            float(scalar[current]) <= 0.0
            if keep_negative
            else float(scalar[current]) >= 0.0
        )
        if previous_inside != current_inside:
            output.append(registry.intersection(previous, current))
        if current_inside:
            output.append(current)
        previous = current
        previous_inside = current_inside
    return _deduplicate_cycle(output)


def _fan_triangulate(
    polygon: list[int], registry: _ZeroVertexRegistry
) -> list[np.ndarray]:
    result: list[np.ndarray] = []
    for index in range(1, len(polygon) - 1):
        face = np.asarray(
            (polygon[0], polygon[index], polygon[index + 1]),
            dtype=np.int32,
        )
        coordinates = registry.coordinates(face)
        doubled_area = np.linalg.norm(
            np.cross(
                coordinates[1] - coordinates[0],
                coordinates[2] - coordinates[0],
            )
        )
        if float(doubled_area) > 1e-14:
            result.append(face)
    return result


def _interface_polygon(
    element: np.ndarray,
    nodes: np.ndarray,
    scalar: np.ndarray,
    registry: _ZeroVertexRegistry,
) -> tuple[list[int], np.ndarray] | None:
    values = scalar[element]
    if float(np.min(values)) > 0.0 or float(np.max(values)) < 0.0:
        return None
    vertex_ids: list[int] = [
        int(element[index])
        for index in range(4)
        if float(values[index]) == 0.0
    ]
    for first_local, second_local in TET_EDGES:
        first = int(element[first_local])
        second = int(element[second_local])
        if float(scalar[first]) * float(scalar[second]) < 0.0:
            vertex_ids.append(registry.intersection(first, second))
    vertex_ids = _deduplicate_cycle(vertex_ids)
    if len(vertex_ids) < 3:
        return None
    positions = nodes[element]
    affine = np.column_stack((positions, np.ones(4, dtype=np.float64)))
    try:
        coefficients = np.linalg.solve(affine, values)
    except np.linalg.LinAlgError:
        return None
    gradient = coefficients[:3]
    gradient_length = float(np.linalg.norm(gradient))
    if gradient_length <= 1e-14:
        return None
    coordinates = registry.coordinates(vertex_ids)
    center = coordinates.mean(axis=0)
    normal = gradient / gradient_length
    relative = coordinates - center
    lengths = np.linalg.norm(relative, axis=1)
    anchor = int(np.argmax(lengths))
    if float(lengths[anchor]) <= 1e-14:
        return None
    axis_u = relative[anchor] / lengths[anchor]
    axis_v = np.cross(normal, axis_u)
    angles = np.arctan2(relative @ axis_v, relative @ axis_u)
    return [vertex_ids[index] for index in np.argsort(angles)], gradient


@dataclass
class _MarkedSurface:
    vertices: np.ndarray
    faces: np.ndarray
    markers: np.ndarray


def _compact_marked_surface(
    global_vertices: np.ndarray,
    global_faces: np.ndarray,
    markers: np.ndarray,
) -> _MarkedSurface:
    used = np.unique(global_faces)
    remap = np.full(len(global_vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    return _MarkedSurface(
        vertices=np.asarray(global_vertices[used], dtype=np.float64),
        faces=remap[global_faces].astype(np.int32),
        markers=np.asarray(markers, dtype=np.int32),
    )


def _extract_binary_surface(
    nodes: np.ndarray,
    elements: np.ndarray,
    boundary_faces: np.ndarray,
    boundary_markers: np.ndarray,
    scalar: np.ndarray,
    *,
    interface_marker: int,
) -> tuple[_MarkedSurface, _MarkedSurface, dict[str, object]]:
    started = time.perf_counter()
    registry = _ZeroVertexRegistry(nodes, scalar)
    outer_faces: dict[bool, list[np.ndarray]] = {True: [], False: []}
    outer_markers: dict[bool, list[int]] = {True: [], False: []}
    clipped = {"negative": 0, "positive": 0}
    for face, marker in zip(
        boundary_faces, boundary_markers, strict=True
    ):
        for keep_negative, name in ((True, "negative"), (False, "positive")):
            polygon = _clip_triangle(
                face, scalar, registry, keep_negative=keep_negative
            )
            triangles = _fan_triangulate(polygon, registry)
            if triangles:
                outer_faces[keep_negative].extend(triangles)
                outer_markers[keep_negative].extend(
                    [int(marker)] * len(triangles)
                )
                if len(polygon) != 3 or set(polygon) != set(map(int, face)):
                    clipped[name] += 1

    interface_by_key: dict[tuple[int, int, int], np.ndarray] = {}
    values = scalar[elements]
    candidate_ids = np.flatnonzero(
        (np.min(values, axis=1) <= 0.0)
        & (np.max(values, axis=1) >= 0.0)
    )
    numerical_skips = 0
    polygons = 0
    for tet_id in candidate_ids:
        polygon_result = _interface_polygon(
            elements[tet_id], nodes, scalar, registry
        )
        if polygon_result is None:
            numerical_skips += 1
            continue
        polygon, gradient = polygon_result
        accepted = 0
        for face in _fan_triangulate(polygon, registry):
            coordinates = registry.coordinates(face)
            normal = np.cross(
                coordinates[1] - coordinates[0],
                coordinates[2] - coordinates[0],
            )
            if float(np.dot(normal, gradient)) < 0.0:
                face[[1, 2]] = face[[2, 1]]
            key = tuple(sorted(map(int, face)))
            if key not in interface_by_key:
                interface_by_key[key] = face.copy()
                accepted += 1
        if accepted:
            polygons += 1
    if not interface_by_key:
        raise VolumePartitionError("内部共有面を生成できません")
    interface_faces = np.asarray(
        list(interface_by_key.values()), dtype=np.int32
    )
    global_vertices = registry.array()
    outputs: list[_MarkedSurface] = []
    for keep_negative in (True, False):
        oriented_interface = (
            interface_faces
            if keep_negative
            else interface_faces[:, [0, 2, 1]]
        )
        # One side of a binary volume split can have no source-boundary
        # triangles at all (for example, a radial core enclosed by a shell).
        # Keep the empty value two-dimensional so it can still be stacked
        # with the generated interface triangles.
        boundary_output = np.asarray(
            outer_faces[keep_negative], dtype=np.int32
        ).reshape((-1, 3))
        faces = np.vstack(
            (
                boundary_output,
                oriented_interface,
            )
        ).astype(np.int32)
        markers = np.concatenate(
            (
                np.asarray(outer_markers[keep_negative], dtype=np.int32),
                np.full(
                    len(oriented_interface),
                    int(interface_marker),
                    dtype=np.int32,
                ),
            )
        )
        outputs.append(_compact_marked_surface(global_vertices, faces, markers))
    interface_topology = _edge_topology(interface_faces, len(global_vertices))
    return outputs[0], outputs[1], {
        "marker": int(interface_marker),
        "interface_vertices": int(len(np.unique(interface_faces))),
        "interface_faces": int(len(interface_faces)),
        "interface_boundary_edges": int(interface_topology["boundary_edges"]),
        "interface_nonmanifold_edges": int(
            interface_topology["nonmanifold_edges"]
        ),
        "candidate_tetrahedra": int(len(candidate_ids)),
        "interface_polygons": int(polygons),
        "generated_zero_vertices": int(len(registry.extra)),
        "clipped_outer_polygons": clipped,
        "numerical_skips": int(numerical_skips),
        "seconds": float(time.perf_counter() - started),
    }


def _validate_surface(
    surface: _MarkedSurface,
    *,
    part_id: int,
) -> tuple[_MarkedSurface, dict[str, object]]:
    try:
        faces, record = _strict_mesh_record(
            surface.vertices, surface.faces, part_id=part_id
        )
    except AssemblyError as exc:
        raise VolumePartitionError(str(exc)) from exc
    return _MarkedSurface(
        vertices=surface.vertices,
        faces=faces,
        markers=surface.markers,
    ), record


def _mesh_volume(surface: _MarkedSurface) -> float:
    triangles = surface.vertices[surface.faces]
    return float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )


def _transfer_surface_colors(
    source_vertices: np.ndarray,
    source_faces: np.ndarray,
    source_colors: np.ndarray,
    query: np.ndarray,
) -> tuple[np.ndarray, dict[str, float]]:
    source = trimesh.Trimesh(
        vertices=source_vertices, faces=source_faces, process=False
    )
    closest_parts: list[np.ndarray] = []
    distance_parts: list[np.ndarray] = []
    triangle_parts: list[np.ndarray] = []
    for start in range(0, len(query), 20_000):
        closest, distance, triangle_ids = trimesh.proximity.closest_point(
            source, query[start : start + 20_000]
        )
        closest_parts.append(np.asarray(closest, dtype=np.float64))
        distance_parts.append(np.asarray(distance, dtype=np.float64))
        triangle_parts.append(np.asarray(triangle_ids, dtype=np.int64))
    closest = np.vstack(closest_parts)
    distances = np.concatenate(distance_parts)
    triangle_ids = np.concatenate(triangle_parts)
    triangles = source_vertices[source_faces[triangle_ids]]
    weights = trimesh.triangles.points_to_barycentric(triangles, closest)
    weights = np.clip(weights, 0.0, 1.0)
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-15)
    colors = np.einsum(
        "ij,ijk->ik", weights, source_colors[source_faces[triangle_ids]]
    )
    return np.clip(colors, 0.0, 1.0), {
        "nearest_source_distance_max_unit": float(
            np.max(distances, initial=0.0)
        ),
        "nearest_source_distance_mean_unit": float(
            np.mean(distances) if len(distances) else 0.0
        ),
    }


def _peeling_order(
    part_count: int,
    seams: Iterable[SeamPair],
    face_counts: list[int],
) -> list[int]:
    adjacency: dict[int, set[int]] = {
        part_id: set() for part_id in range(part_count)
    }
    for seam in seams:
        first = int(seam.first.part_id)
        second = int(seam.second.part_id)
        if first != second and first in adjacency and second in adjacency:
            adjacency[first].add(second)
            adjacency[second].add(first)
    active = set(range(part_count))
    order: list[int] = []
    while len(active) > 1:
        degrees = {
            part_id: len(adjacency[part_id] & active)
            for part_id in active
        }
        leaves = [part_id for part_id in active if degrees[part_id] <= 1]
        candidates = leaves if leaves else list(active)
        selected = min(
            candidates,
            key=lambda part_id: (
                degrees[part_id],
                int(face_counts[part_id]),
                int(part_id),
            ),
        )
        order.append(int(selected))
        active.remove(selected)
    return order


def _recursive_partition(
    current_surface: _MarkedSurface,
    active_labels: set[int],
    peeling_order: list[int],
    *,
    part_count: int,
    final_surfaces: dict[int, _MarkedSurface],
    interface_records: list[dict[str, object]],
    generation_records: list[dict[str, object]],
    progress: ProgressCallback | None,
    depth: int,
    volume_data: tuple[
        np.ndarray, np.ndarray, np.ndarray, np.ndarray
    ]
    | None = None,
) -> None:
    if len(active_labels) == 1:
        final_surfaces[int(next(iter(active_labels)))] = current_surface
        return
    if volume_data is None:
        _emit(
            progress,
            "volume_partition",
            0.67 + 0.08 * min(depth, 2),
            f"残り {len(active_labels)} パーツの共有面を再計算しています",
        )
        (
            nodes,
            elements,
            boundary_faces,
            boundary_markers,
            tetra_record,
        ) = _exact_tetrahedralize(
            current_surface.vertices,
            current_surface.faces,
            current_surface.markers,
            part_count=part_count,
        )
    else:
        nodes, elements, boundary_faces, boundary_markers = volume_data
        tetra_record = {"engine": "fTetWild root volume"}

    tetra_volume = float(_tetra_volumes(nodes, elements).sum())
    candidate_labels = [
        int(label) for label in peeling_order if label in active_labels
    ]
    candidate_labels.extend(
        sorted(
            int(label)
            for label in active_labels
            if int(label) not in candidate_labels
        )
    )
    failures: list[str] = []
    interface_marker = -(depth + 1)
    for leaf_label in candidate_labels:
        try:
            scalar, harmonic_record = _solve_active_harmonic(
                nodes,
                elements,
                boundary_faces,
                boundary_markers,
                leaf_label=leaf_label,
                active_labels=active_labels,
            )
            negative, positive, extraction_record = _extract_binary_surface(
                nodes,
                elements,
                boundary_faces,
                boundary_markers,
                scalar,
                interface_marker=interface_marker,
            )
            negative, negative_validation = _validate_surface(
                negative, part_id=leaf_label
            )
            remaining = set(active_labels) - {leaf_label}
            positive, positive_validation = _validate_surface(
                positive, part_id=min(remaining)
            )
            output_volume = abs(_mesh_volume(negative)) + abs(
                _mesh_volume(positive)
            )
            volume_error = abs(output_volume - tetra_volume)
            relative_error = volume_error / max(tetra_volume, 1e-15)
            if relative_error > 1e-8:
                raise VolumePartitionError(
                    "再帰分割の体積誤差が上限を超えます: "
                    f"{relative_error:.3e}"
                )
            if int(extraction_record["interface_nonmanifold_edges"]):
                raise VolumePartitionError("再帰分割の共有面が非多様体です")

            trial_surfaces = dict(final_surfaces)
            trial_interfaces = list(interface_records)
            trial_generations = list(generation_records)
            trial_surfaces[int(leaf_label)] = negative
            trial_interfaces.append(
                {
                    "generation": int(depth),
                    "marker": int(interface_marker),
                    "leaf_part": int(leaf_label),
                    "remaining_parts": sorted(
                        int(value) for value in remaining
                    ),
                    **extraction_record,
                    "volume_conservation_relative": float(relative_error),
                }
            )
            trial_generations.append(
                {
                    "generation": int(depth),
                    "active_parts": sorted(
                        int(value) for value in active_labels
                    ),
                    "leaf_part": int(leaf_label),
                    "tetrahedralization": tetra_record,
                    "harmonic": harmonic_record,
                    "negative_validation": negative_validation,
                    "positive_validation": positive_validation,
                    "volume_conservation_relative": float(relative_error),
                }
            )
            _recursive_partition(
                positive,
                remaining,
                peeling_order,
                part_count=part_count,
                final_surfaces=trial_surfaces,
                interface_records=trial_interfaces,
                generation_records=trial_generations,
                progress=progress,
                depth=depth + 1,
            )
        except VolumePartitionError as exc:
            failures.append(f"パーツ{leaf_label + 1}: {exc}")
            continue

        final_surfaces.clear()
        final_surfaces.update(trial_surfaces)
        interface_records[:] = trial_interfaces
        generation_records[:] = trial_generations
        return

    detail = " / ".join(failures[:4])
    if len(failures) > 4:
        detail += f" / ほか{len(failures) - 4}件"
    raise VolumePartitionError(
        f"残り{len(active_labels)}パーツを安全に分離できませんでした: {detail}"
    )


def solidify_complex_partitions(
    meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    seams: Iterable[SeamPair],
    *,
    height_mm: float,
    progress: ProgressCallback | None = None,
) -> tuple[
    list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    dict[str, object],
]:
    """Close strongly curved Tripo partitions without merging their IDs."""

    started = time.perf_counter()
    seam_list = list(seams)
    if len(meshes) < 2:
        raise VolumePartitionError(
            "曲面境界の再帰分割には2パーツ以上が必要です"
        )
    if not np.isfinite(height_mm) or float(height_mm) <= 0.0:
        raise VolumePartitionError("造形高さが不正です")
    _emit(
        progress,
        "volume_partition",
        0.57,
        "強く曲がった継ぎ目を安全な体積メッシュへ変換しています",
    )
    try:
        shell_vertices, shell_faces, shell_colors, weld_record = (
            weld_matching_seams(
                meshes,
                seam_list,
                height_mm=height_mm,
            )
        )
    except AssemblyError as exc:
        raise VolumePartitionError(
            f"Tripo境界を体積化用の外殻へ戻せません: {exc}"
        ) from exc
    source_face_counts = [int(len(mesh[1])) for mesh in meshes]
    source_labels = np.concatenate(
        [
            np.full(count, part_id, dtype=np.int32)
            for part_id, count in enumerate(source_face_counts)
        ]
    )
    if len(source_labels) != len(shell_faces):
        raise VolumePartitionError(
            "体積化用外殻で元パーツ面の対応を保持できません"
        )
    nodes, elements, tetwild_record = _tetwild_tetrahedralize(
        shell_vertices, shell_faces
    )
    boundary_faces, _boundary_owners = _oriented_boundary_faces(
        nodes, elements
    )
    boundary_markers, label_record = _closest_surface_labels(
        nodes,
        boundary_faces,
        shell_vertices,
        shell_faces,
        source_labels,
    )
    root_surface = _compact_marked_surface(
        nodes, boundary_faces, boundary_markers
    )
    root_surface, root_validation = _validate_surface(
        root_surface, part_id=0
    )
    fidelity = _surface_distance_record(
        shell_vertices,
        shell_faces,
        nodes,
        boundary_faces,
        height_mm=height_mm,
    )
    if (
        fidelity["output_to_source_p99_mm"] > 0.15
        or fidelity["source_to_output_p99_mm"] > 0.15
        or fidelity["output_to_source_max_mm"] > 0.40
        or fidelity["source_to_output_max_mm"] > 0.40
    ):
        raise VolumePartitionError(
            "曲面体積化の外形誤差が品質上限を超えます: "
            f"p99 {max(fidelity['output_to_source_p99_mm'], fidelity['source_to_output_p99_mm']):.3f} mm, "
            f"最大 {max(fidelity['output_to_source_max_mm'], fidelity['source_to_output_max_mm']):.3f} mm"
        )

    peeling_order = _peeling_order(
        len(meshes), seam_list, source_face_counts
    )
    final_surfaces: dict[int, _MarkedSurface] = {}
    interface_records: list[dict[str, object]] = []
    generation_records: list[dict[str, object]] = []
    _emit(
        progress,
        "volume_partition",
        0.64,
        f"体積メッシュから元の {len(meshes)} パーツを復元しています",
    )
    _recursive_partition(
        root_surface,
        set(range(len(meshes))),
        peeling_order,
        part_count=len(meshes),
        final_surfaces=final_surfaces,
        interface_records=interface_records,
        generation_records=generation_records,
        progress=progress,
        depth=0,
        volume_data=(nodes, elements, boundary_faces, boundary_markers),
    )
    if set(final_surfaces) != set(range(len(meshes))):
        raise VolumePartitionError("元パーツをすべて復元できません")

    outputs: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    part_records: list[dict[str, object]] = []
    _emit(
        progress,
        "volume_partition",
        0.87,
        "復元した各パーツに元の色を戻しています",
    )
    for part_id, source_mesh in enumerate(meshes):
        surface = final_surfaces[part_id]
        colors, color_record = _transfer_surface_colors(
            np.asarray(source_mesh[0], dtype=np.float64),
            np.asarray(source_mesh[1], dtype=np.int32),
            np.asarray(source_mesh[2], dtype=np.float64),
            surface.vertices,
        )
        validated, validation = _validate_surface(surface, part_id=part_id)
        generated_face_ids = np.flatnonzero(
            np.asarray(validated.markers, dtype=np.int32) < 0
        )
        outputs.append((validated.vertices, validated.faces, colors))
        part_records.append(
            {
                "part_id": int(part_id),
                "before_faces": int(len(source_mesh[1])),
                "after_faces": int(len(validated.faces)),
                "added_faces": 0,
                # Negative markers belong only to interfaces created by the
                # volume partitioner.  Preserve their *final* local IDs so a
                # later export never has to guess internal faces spatially.
                "generated_face_count": int(len(generated_face_ids)),
                "generated_face_ranges": encode_face_ranges(
                    generated_face_ids
                ),
                "validation": validation,
                "color_transfer": {
                    **color_record,
                    "nearest_source_distance_max_mm": float(
                        color_record["nearest_source_distance_max_unit"]
                        * float(height_mm)
                    ),
                },
            }
        )
    root_volume = float(_tetra_volumes(nodes, elements).sum())
    part_volume_sum = float(
        sum(abs(_mesh_volume(final_surfaces[index])) for index in final_surfaces)
    )
    final_volume_error = abs(part_volume_sum - root_volume) / max(
        root_volume, 1e-15
    )
    if final_volume_error > 1e-8:
        raise VolumePartitionError(
            f"最終パーツ合計の体積誤差が上限を超えます: {final_volume_error:.3e}"
        )
    return outputs, {
        "method": "recursive_volume_partition",
        "closed": True,
        "source_parts": int(len(meshes)),
        "output_parts": int(len(outputs)),
        "matched_seams": int(len(seam_list)),
        "peeling_order": peeling_order,
        "weld": weld_record,
        "tetrahedralization": tetwild_record,
        "boundary_label_transfer": {
            **label_record,
            "counts": {
                str(int(label)): int(count)
                for label, count in zip(
                    *np.unique(boundary_markers, return_counts=True),
                    strict=True,
                )
            },
        },
        "surface_fidelity": fidelity,
        "root_validation": root_validation,
        "interfaces": interface_records,
        "generations": generation_records,
        "parts": part_records,
        "volume_conservation_relative": float(final_volume_error),
        "supports_automatic_joints": False,
        "seconds": float(time.perf_counter() - started),
    }


__all__ = [
    "VolumePartitionError",
    "solidify_complex_partitions",
]
