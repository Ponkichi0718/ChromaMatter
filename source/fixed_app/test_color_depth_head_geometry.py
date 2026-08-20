from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import permutations
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.color_depth import ColorDepthRecipe
from spectrum_mapper.color_depth_head_geometry import (
    ColorDepthGeometryError,
    ColorDepthSourceSurface,
    ConformingColorDepthPartition,
    build_color_depth_head_materials,
)
from spectrum_mapper.color_depth_recipes import ColorDepthRecipePlan
from spectrum_mapper.engine import edge_topology, signed_volume, triangle_areas
from spectrum_mapper.models import MeshLevel, ObjAsset, PreparedGeometry
from spectrum_mapper.radial_export import package_from_color_depth


_TET_FACES = np.asarray(
    ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)), dtype=np.int32
)


@dataclass(frozen=True)
class _Request:
    prepared: PreparedGeometry
    height_mm: float
    face_target_labels: np.ndarray
    recipes: dict[int, ColorDepthRecipe]
    recipe_plan: ColorDepthRecipePlan
    progress: object | None = None


def _tet_face_table(tets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    raw = tets[:, _TET_FACES].reshape((-1, 3))
    keys = np.sort(raw, axis=1)
    order = np.lexsort((keys[:, 2], keys[:, 1], keys[:, 0]))
    ordered = keys[order]
    starts = np.r_[
        0, np.flatnonzero(np.any(ordered[1:] != ordered[:-1], axis=1)) + 1
    ]
    counts = np.diff(np.r_[starts, len(order)])
    rows = order[starts[counts == 1]]
    faces = raw[rows].copy()
    cells = (rows // 4).astype(np.int32)
    opposite = tets[cells, rows % 4]
    points = _CUBE_NODES[faces]
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    inward = np.einsum(
        "ij,ij->i", normals, _CUBE_NODES[opposite] - points[:, 0]
    ) > 0.0
    faces[inward, 1:3] = faces[inward, 2:0:-1]
    return faces, cells


def _cube_complex() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    axes = (
        (-5.0, -4.85, 4.85, 5.0),
        (-4.0, -3.85, 3.85, 4.0),
        (-3.0, -2.85, 2.85, 3.0),
    )
    nodes = np.asarray(
        [(x, y, z) for x in axes[0] for y in axes[1] for z in axes[2]],
        dtype=np.float64,
    )

    def vertex_id(index: np.ndarray) -> int:
        return int(index[0] * 16 + index[1] * 4 + index[2])

    tets: list[list[int]] = []
    shell: list[bool] = []
    for i in range(3):
        for j in range(3):
            for k in range(3):
                base = np.asarray((i, j, k), dtype=np.int32)
                is_shell = i in (0, 2) or j in (0, 2) or k in (0, 2)
                for order in permutations(range(3)):
                    path = [base.copy()]
                    current = base.copy()
                    for axis in order:
                        current = current.copy()
                        current[axis] += 1
                        path.append(current)
                    ids = [vertex_id(value) for value in path]
                    points = nodes[ids]
                    if float(np.linalg.det(points[1:] - points[0])) < 0.0:
                        ids[1], ids[2] = ids[2], ids[1]
                    tets.append(ids)
                    shell.append(is_shell)
    return (
        nodes,
        np.asarray(tets, dtype=np.int32),
        np.asarray(shell, dtype=bool),
        np.asarray((axes[0], axes[1], axes[2]), dtype=np.float64),
    )


_CUBE_NODES, _CUBE_TETS, _CUBE_SHELL, _CUBE_AXES = _cube_complex()
_CUBE_EXTERIOR, _CUBE_EXTERIOR_CELLS = _tet_face_table(_CUBE_TETS)


def _prepared_cube() -> tuple[PreparedGeometry, np.ndarray]:
    used = np.unique(_CUBE_EXTERIOR)
    remap = np.full(len(_CUBE_NODES), -1, dtype=np.int32)
    remap[used] = np.arange(len(used), dtype=np.int32)
    vertices_mm = _CUBE_NODES[used]
    faces = remap[_CUBE_EXTERIOR]
    height_mm = 6.0
    vertices_unit = vertices_mm / height_mm
    colours = np.tile(np.asarray((0.8, 0.1, 0.1)), (len(vertices_mm), 1))
    areas_unit = triangle_areas(vertices_mm, faces) / height_mm**2
    level = MeshLevel(
        vertices_unit=vertices_unit,
        faces=faces,
        vertex_colors=colours,
        areas_unit=areas_unit,
        neighbors=None,
        face_part_ids=np.zeros(len(faces), dtype=np.int16),
        part_names=("ColorDepth cube",),
        part_keys=("color-depth-cube",),
        face_provenance=np.zeros(len(faces), dtype=np.uint8),
    )
    source = ObjAsset(
        path=Path("color-depth-cube.obj"),
        sha256="b" * 64,
        file_size=1,
        vertices=vertices_unit.copy(),
        colors=colours.copy(),
        faces=faces.copy(),
        original_vertex_count=len(vertices_unit),
        original_face_count=len(faces),
        warnings=[],
        part_names=("ColorDepth cube",),
        part_keys=("color-depth-cube",),
        face_part_ids=np.zeros(len(faces), dtype=np.int16),
        part_face_counts=(len(faces),),
        part_vertex_counts=(len(vertices_unit),),
        part_marker_kind="object",
        has_explicit_parts=True,
    )
    volume_unit = signed_volume(vertices_unit, faces)
    prepared = PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(vertices_unit),
        clean_face_count=len(faces),
        removed_vertices=0,
        removed_faces=0,
        topology=edge_topology(faces, len(vertices_unit)),
        source_area_unit=float(areas_unit.sum()),
        source_volume_unit=float(volume_unit),
        simplified_area_unit=float(areas_unit.sum()),
        simplified_volume_unit=float(volume_unit),
        source_dimensions_unit=np.ptp(vertices_unit, axis=0),
        warnings=[],
        part_names=("ColorDepth cube",),
        part_keys=("color-depth-cube",),
        part_stats=[{"id": 0}],
        assembly={"all_parts_watertight": True},
    )
    labels = np.full(len(faces), 4, dtype=np.int16)
    return prepared, labels


def _recipe() -> tuple[dict[int, ColorDepthRecipe], ColorDepthRecipePlan]:
    recipe = ColorDepthRecipe(
        target_label=4,
        outer_physical=3,
        outer_thickness_mm=0.15,
        backing_physical=1,
    )
    recipes = {4: recipe}
    return recipes, ColorDepthRecipePlan(
        recipes=recipes,
        target_labels=(4,),
        collapsed_target_groups=(),
        physical_hex=("#111111", "#F5F5F5", "#E32636", "#7A4A32"),
        outer_thickness_mm=0.15,
        calibrated=False,
        metadata={
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "legacy_mix_percentages_used": False,
        },
    )


def _cube_provider(
    surface: ColorDepthSourceSurface,
    _recipes: dict[int, ColorDepthRecipe],
    *,
    progress=None,
) -> ConformingColorDepthPartition:
    del progress
    # The prepared surface is exactly the compact form of this boundary.  Map
    # every partition child to its coordinate-identical source triangle.
    source_keys = {
        np.round(surface.vertices_mm[face], 12)[
            np.lexsort(
                (
                    np.round(surface.vertices_mm[face], 12)[:, 2],
                    np.round(surface.vertices_mm[face], 12)[:, 1],
                    np.round(surface.vertices_mm[face], 12)[:, 0],
                )
            )
        ].astype("<f8").tobytes(): index
        for index, face in enumerate(surface.faces)
    }
    parents = []
    for face in _CUBE_EXTERIOR:
        points = np.round(_CUBE_NODES[face], 12)
        order = np.lexsort((points[:, 2], points[:, 1], points[:, 0]))
        parents.append(source_keys[points[order].astype("<f8").tobytes()])
    bounds = np.empty((len(_CUBE_TETS), 2), dtype=np.float64)
    bounds[_CUBE_SHELL] = (0.0, 0.15)
    bounds[~_CUBE_SHELL] = (0.15, 0.30)
    return ConformingColorDepthPartition(
        nodes_mm=_CUBE_NODES,
        tetrahedra=_CUBE_TETS,
        cell_owner_labels=np.full(len(_CUBE_TETS), 4, dtype=np.int32),
        cell_depth_bounds_mm=bounds,
        cell_materials=np.where(_CUBE_SHELL, 3, 1).astype(np.int8),
        unsafe_outer_only_cells=np.zeros(len(_CUBE_TETS), dtype=bool),
        exterior_faces=_CUBE_EXTERIOR,
        exterior_owner_cells=_CUBE_EXTERIOR_CELLS,
        exterior_source_face_ids=np.asarray(parents, dtype=np.int32),
        threshold_interface_conforming=True,
        shared_interface_partition_exact=True,
        max_safe_threshold_error_mm=0.0,
        metadata={
            "engine": "deterministic-cube-fixture",
            "centroid_approximation": False,
            "legacy_mix_percentages_used": False,
        },
    )


def _request() -> _Request:
    prepared, labels = _prepared_cube()
    recipes, plan = _recipe()
    return _Request(prepared, 6.0, labels, recipes, plan)


class ColorDepthHeadGeometryTests(unittest.TestCase):
    def test_request_to_physical_union_cube_is_exact_and_slice_only(self) -> None:
        result = build_color_depth_head_materials(
            _request(), partition_provider=_cube_provider
        )

        self.assertEqual([part.extruder for part in result.parts], [1, 3])
        self.assertAlmostEqual(result.source_volume_mm3, 480.0, places=9)
        self.assertAlmostEqual(result.output_volume_mm3, 480.0, places=9)
        self.assertEqual(result.metadata["ratio_definitions"], 0)
        self.assertEqual(result.metadata["cycle_definitions"], 0)
        self.assertEqual(result.metadata["virtual_mix_definitions"], 0)
        self.assertTrue(result.metadata["shared_interface_partition_exact"])
        self.assertTrue(result.metadata["external_surface_coverage_exact"])
        self.assertTrue(result.metadata["unsafe_columns_outer_only_verified"])
        self.assertEqual(
            result.metadata["coordinate_triangle_accounting"][
                "counterpart_partition_mismatches"
            ],
            0,
        )
        self.assertTrue(result.metadata["slice_only"])
        self.assertFalse(result.metadata["print_allowed"])
        self.assertEqual(
            result.metadata["visible_exterior"]["missing_source_faces"], 0
        )
        package = package_from_color_depth(
            result, ("#111111", "#F5F5F5", "#E32636", "#7A4A32")
        )
        self.assertEqual([part.extruder for part in package.parts], [1, 3])

    def test_unsplit_threshold_is_rejected_before_surface_extraction(self) -> None:
        def unsplit_provider(surface, recipes, *, progress=None):
            partition = _cube_provider(surface, recipes, progress=progress)
            bounds = np.asarray(partition.cell_depth_bounds_mm).copy()
            first_regular = int(np.flatnonzero(~partition.unsafe_outer_only_cells)[0])
            bounds[first_regular] = (0.0, 0.30)
            return replace(partition, cell_depth_bounds_mm=bounds)

        with self.assertRaises(Exception) as caught:
            build_color_depth_head_materials(
                _request(), partition_provider=unsplit_provider
            )
        self.assertEqual(getattr(caught.exception, "code", None), "unsplit_recipe_boundary")

    def test_unsafe_column_must_be_outer_material(self) -> None:
        def unsafe_provider(surface, recipes, *, progress=None):
            partition = _cube_provider(surface, recipes, progress=progress)
            unsafe = np.asarray(partition.unsafe_outer_only_cells).copy()
            materials = np.asarray(partition.cell_materials).copy()
            core = int(np.flatnonzero(~_CUBE_SHELL)[0])
            unsafe[core] = True
            materials[core] = 1
            return replace(
                partition,
                unsafe_outer_only_cells=unsafe,
                cell_materials=materials,
            )

        with self.assertRaises(ColorDepthGeometryError) as caught:
            build_color_depth_head_materials(
                _request(), partition_provider=unsafe_provider
            )
        self.assertEqual(caught.exception.code, "unsafe_column_contains_backing_material")

    def test_default_builder_uses_promoted_exact_provider(self) -> None:
        result = build_color_depth_head_materials(_request())
        self.assertAlmostEqual(result.source_volume_mm3, 480.0, places=9)
        self.assertAlmostEqual(result.output_volume_mm3, 480.0, places=9)
        self.assertTrue(result.metadata["threshold_interface_conforming"])
        self.assertTrue(result.metadata["shared_interface_partition_exact"])
        self.assertTrue(result.metadata["unsafe_columns_outer_only_verified"])
        self.assertEqual(
            result.metadata["partition"]["tetrahedralization"]["engine"],
            "TetGen",
        )
        self.assertTrue(
            result.metadata["partition"]["direct_threshold_child_join_verified"]
        )
        self.assertEqual(
            set(part.extruder for part in result.parts) - {1, 2, 3, 4}, set()
        )

    def test_default_builder_fails_closed_when_provider_is_absent(self) -> None:
        with mock.patch(
            "spectrum_mapper.color_depth_head_geometry._PROVIDER_CANDIDATES",
            (),
        ), self.assertRaises(ColorDepthGeometryError) as caught:
            build_color_depth_head_materials(_request())
        self.assertEqual(caught.exception.code, "exact_partition_provider_unavailable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
