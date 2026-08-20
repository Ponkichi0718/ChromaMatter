from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.color_depth import ColorDepthRecipe
from spectrum_mapper.color_depth_exact_partition import (
    COLOR_DEPTH_EXACT_PARTITION_SCHEMA,
    ColorDepthExactPartitionError,
    build_conforming_color_depth_partition,
)
from spectrum_mapper.color_depth_head_geometry import prepare_color_depth_source
from test_color_depth_head_geometry import _request


def _volume(nodes: np.ndarray, tets: np.ndarray) -> float:
    points = np.asarray(nodes, dtype=np.float64)[np.asarray(tets, dtype=np.int32)]
    six = np.einsum(
        "ij,ij->i",
        points[:, 1] - points[:, 0],
        np.cross(points[:, 2] - points[:, 0], points[:, 3] - points[:, 0]),
    )
    return float(np.abs(six).sum() / 6.0)


class ColorDepthExactPartitionTests(unittest.TestCase):
    def test_small_cube_exact_provider_e2e_and_outer_only_fallback(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        partition = build_conforming_color_depth_partition(
            source, request.recipes
        )

        self.assertEqual(
            partition.metadata["schema"], COLOR_DEPTH_EXACT_PARTITION_SCHEMA
        )
        self.assertTrue(partition.threshold_interface_conforming)
        self.assertTrue(partition.shared_interface_partition_exact)
        self.assertTrue(partition.metadata["direct_threshold_child_join_verified"])
        self.assertTrue(partition.metadata["visible_exterior_triangle_sets_exact"])
        self.assertTrue(partition.metadata["visible_owner_labels_exact"])
        self.assertTrue(partition.metadata["visible_outer_physical_exact"])
        self.assertEqual(partition.metadata["cell_complex_faces_incidence_gt2"], 0)
        self.assertGreater(
            partition.metadata["hidden_threshold_visibility"][
                "hidden_threshold_cells"
            ],
            0,
        )
        self.assertGreater(partition.metadata["interface_triangles"], 0)
        self.assertLessEqual(
            partition.max_safe_threshold_error_mm,
            partition.max_safe_threshold_error_limit_mm + 1e-12,
        )
        self.assertAlmostEqual(
            _volume(partition.nodes_mm, partition.tetrahedra), 480.0, places=8
        )
        exterior_labels = partition.cell_owner_labels[
            partition.exterior_owner_cells
        ]
        self.assertTrue(
            np.array_equal(
                exterior_labels,
                source.face_target_labels[partition.exterior_source_face_ids],
            )
        )
        self.assertTrue(
            np.all(partition.cell_materials[partition.exterior_owner_cells] == 3)
        )
        unsafe = partition.unsafe_outer_only_cells
        self.assertTrue(np.all(partition.cell_materials[unsafe] == 3))
        self.assertEqual(
            set(map(int, np.unique(partition.cell_materials))) - {1, 2, 3, 4},
            set(),
        )

    def test_conflicting_visible_labels_are_face_coned_and_preserved(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        labels = source.face_target_labels.copy()
        labels[::7] = 5
        source = replace(source, face_target_labels=labels)
        recipes = dict(request.recipes)
        recipes[5] = ColorDepthRecipe(
            target_label=5,
            outer_physical=2,
            outer_thickness_mm=0.15,
            backing_physical=4,
        )

        partition = build_conforming_color_depth_partition(source, recipes)

        self.assertGreater(
            partition.metadata["conflicting_boundary_face_cones"][
                "conflicting_boundary_tetrahedra"
            ],
            0,
        )
        self.assertTrue(
            np.array_equal(
                partition.cell_owner_labels[partition.exterior_owner_cells],
                labels[partition.exterior_source_face_ids],
            )
        )
        expected_outer = np.where(
            labels[partition.exterior_source_face_ids] == 5, 2, 3
        )
        self.assertTrue(
            np.array_equal(
                partition.cell_materials[partition.exterior_owner_cells],
                expected_outer,
            )
        )
        self.assertAlmostEqual(
            _volume(partition.nodes_mm, partition.tetrahedra), 480.0, places=8
        )

    def test_small_cube_safe_threshold_keeps_a_physical_backing_region(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        recipe = ColorDepthRecipe(
            target_label=4,
            outer_physical=3,
            outer_thickness_mm=1.0,
            backing_physical=1,
        )
        partition = build_conforming_color_depth_partition(source, {4: recipe})

        self.assertEqual(set(map(int, np.unique(partition.cell_materials))), {1, 3})
        self.assertGreater(
            partition.metadata["material_changing_threshold_triangles"], 0
        )
        self.assertEqual(
            partition.metadata["unsafe_material_changing_threshold_triangles"],
            0,
        )
        self.assertTrue(
            np.all(
                partition.cell_materials[partition.unsafe_outer_only_cells] == 3
            )
        )
        self.assertLessEqual(
            partition.metadata["maximum_material_changing_interface_error_mm"],
            0.05 + 1e-12,
        )

    def test_no_hidden_backing_is_valid_when_threshold_exceeds_inradius(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        recipe = ColorDepthRecipe(
            target_label=4,
            outer_physical=3,
            outer_thickness_mm=3.1,
            backing_physical=1,
        )
        partition = build_conforming_color_depth_partition(source, {4: recipe})
        self.assertEqual(
            partition.metadata["hidden_threshold_visibility"][
                "hidden_threshold_cells"
            ],
            0,
        )
        self.assertEqual(partition.metadata["crossing_input_cells"], 0)
        self.assertTrue(np.all(partition.cell_materials == 3))

    def test_recipe_contracts_fail_closed(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        finite = ColorDepthRecipe(
            target_label=4,
            outer_physical=3,
            outer_thickness_mm=0.15,
            backing_physical=1,
            backing_depth_mm=0.25,
            core_physical=2,
        )
        with self.assertRaises(ColorDepthExactPartitionError) as caught:
            build_conforming_color_depth_partition(source, {4: finite})
        self.assertEqual(caught.exception.code, "finite_backing_depth_not_yet_supported")

        with self.assertRaises(ColorDepthExactPartitionError) as caught:
            build_conforming_color_depth_partition(
                source, request.recipes, interface_error_limit_mm=0.051
            )
        self.assertEqual(caught.exception.code, "invalid_interface_error_limit")

    def test_malformed_public_source_fails_before_native_tetgen(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        invalid_faces = source.faces.copy()
        invalid_faces[0, 0] = len(source.vertices_mm)
        malformed = replace(source, faces=invalid_faces)
        with self.assertRaises(ColorDepthExactPartitionError) as caught:
            build_conforming_color_depth_partition(malformed, request.recipes)
        self.assertEqual(caught.exception.code, "source_face_index_out_of_range")


if __name__ == "__main__":
    unittest.main(verbosity=2)
