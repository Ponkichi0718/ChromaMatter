from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np
import trimesh


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.color_depth import (
    ColorDepthError,
    ColorDepthRecipe,
    audit_material_cell_components,
    audit_material_union_topology,
    build_color_depth_materials,
    classify_color_depth_cells,
    extract_material_union_surfaces,
)


def _two_tetrahedra() -> tuple[np.ndarray, np.ndarray]:
    # Two conforming tetrahedra sharing exactly the face (1, 2, 3).  Their
    # union is a closed triangular bipyramid of volume 1/2.
    return (
        np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (1.0, 1.0, 1.0),
            ),
            dtype=np.float64,
        ),
        np.asarray(((0, 1, 2, 3), (1, 2, 3, 4)), dtype=np.int32),
    )


class ColorDepthRecipeTests(unittest.TestCase):
    def test_ordered_recipe_has_no_ratio_semantics(self) -> None:
        recipe = ColorDepthRecipe(
            target_label=6,
            outer_physical=3,
            outer_thickness_mm=0.15,
            backing_physical=1,
            backing_depth_mm=0.42,
            core_physical=2,
            target_lab=(42.0, 51.0, 29.0),
        )

        self.assertEqual(recipe.material_thresholds_mm, (0.15, 0.57))
        self.assertEqual(recipe.physical_at_depth(0.0), 3)
        self.assertEqual(recipe.physical_at_depth(0.149), 3)
        self.assertEqual(recipe.physical_at_depth(0.15), 1)
        self.assertEqual(recipe.physical_at_depth(0.56), 1)
        self.assertEqual(recipe.physical_at_depth(0.57), 2)

    def test_calibrated_recipe_requires_lut_identity(self) -> None:
        with self.assertRaises(ColorDepthError) as caught:
            ColorDepthRecipe(
                target_label=1,
                outer_physical=3,
                outer_thickness_mm=0.15,
                backing_physical=1,
                calibrated=True,
            )

        self.assertEqual(
            caught.exception.code,
            "calibrated_recipe_requires_calibration_id",
        )

    def test_unsplit_material_threshold_fails_closed(self) -> None:
        recipe = ColorDepthRecipe(6, 3, 0.15, 1)

        with self.assertRaises(ColorDepthError) as caught:
            classify_color_depth_cells(
                np.asarray((6,), dtype=np.int16),
                np.asarray(((0.0, 0.30),), dtype=np.float64),
                {6: recipe},
            )

        self.assertEqual(caught.exception.code, "unsplit_recipe_boundary")
        self.assertEqual(caught.exception.details["crossing_cell_count"], 1)

    def test_same_physical_material_may_cross_recipe_threshold(self) -> None:
        recipe = ColorDepthRecipe(3, 3, 0.15, 3)
        assignment = classify_color_depth_cells(
            np.asarray((3,), dtype=np.int16),
            np.asarray(((0.0, 4.0),), dtype=np.float64),
            {3: recipe},
        )

        self.assertEqual(assignment.cell_materials.tolist(), [3])
        self.assertFalse(assignment.cell_materials.flags.writeable)


class ColorDepthCellGeometryTests(unittest.TestCase):
    def test_two_materials_are_exact_touch_closed_unions(self) -> None:
        nodes, tetrahedra = _two_tetrahedra()
        result = extract_material_union_surfaces(
            nodes,
            tetrahedra,
            np.asarray((1, 3), dtype=np.int8),
            cell_owner_labels=np.asarray((5, 6), dtype=np.int16),
        )

        self.assertEqual([part.extruder for part in result.parts], [1, 3])
        self.assertEqual([len(part.faces) for part in result.parts], [4, 4])
        self.assertAlmostEqual(result.source_volume_mm3, 0.5, places=12)
        self.assertAlmostEqual(result.output_volume_mm3, 0.5, places=12)
        self.assertEqual(len(result.interfaces), 1)
        interface = result.interfaces[0]
        self.assertEqual(interface["physical_materials"], [1, 3])
        self.assertEqual(interface["faces"], 1)
        self.assertTrue(interface["exact_coordinate_triangles"])
        self.assertTrue(interface["opposite_winding"])
        self.assertEqual(interface["gap_mm"], 0.0)
        self.assertEqual(interface["positive_overlap_mm3"], 0.0)
        for part in result.parts:
            mesh = trimesh.Trimesh(
                vertices=part.vertices_mm,
                faces=part.faces,
                process=False,
            )
            self.assertTrue(mesh.is_watertight)
            self.assertTrue(mesh.is_winding_consistent)
            self.assertFalse(part.vertices_mm.flags.writeable)
            self.assertFalse(part.faces.flags.writeable)

    def test_same_material_removes_internal_face(self) -> None:
        nodes, tetrahedra = _two_tetrahedra()
        result = extract_material_union_surfaces(
            nodes,
            tetrahedra,
            np.asarray((4, 4), dtype=np.int8),
        )

        self.assertEqual(len(result.parts), 1)
        self.assertEqual(result.parts[0].extruder, 4)
        self.assertEqual(len(result.parts[0].faces), 6)
        self.assertEqual(result.interfaces, ())

    def test_disconnected_source_fails_closed(self) -> None:
        nodes, tetrahedra = _two_tetrahedra()
        shifted = nodes + np.asarray((3.0, 0.0, 0.0))
        all_nodes = np.vstack((nodes[:4], shifted[:4]))
        all_tetrahedra = np.asarray(
            ((0, 1, 2, 3), (4, 5, 6, 7)), dtype=np.int32
        )

        with self.assertRaises(ColorDepthError) as caught:
            extract_material_union_surfaces(
                all_nodes,
                all_tetrahedra,
                np.asarray((1, 2), dtype=np.int8),
            )

        self.assertEqual(
            caught.exception.code,
            "single_source_component_required",
        )

    def test_recipe_build_classifies_only_presegmented_cells(self) -> None:
        nodes, tetrahedra = _two_tetrahedra()
        recipes = {
            10: ColorDepthRecipe(10, 3, 0.15, 1),
            11: ColorDepthRecipe(11, 2, 0.15, 4),
        }
        result = build_color_depth_materials(
            nodes,
            tetrahedra,
            cell_owner_labels=np.asarray((10, 11), dtype=np.int16),
            cell_depth_bounds_mm=np.asarray(
                ((0.0, 0.10), (0.20, 0.40)), dtype=np.float64
            ),
            recipes=recipes,
        )

        self.assertEqual(result.cell_materials.tolist(), [3, 4])
        self.assertEqual(result.metadata["renderer"], "ColorDepth Lab")
        self.assertEqual(result.metadata["ratio_definitions"], 0)
        self.assertEqual(result.metadata["cycle_definitions"], 0)
        self.assertEqual(result.metadata["virtual_mix_definitions"], 0)
        self.assertFalse(result.metadata["recipes"]["10"]["calibrated"])
        self.assertEqual(
            result.metadata["cell_classification"][
                "uncalibrated_recipe_labels"
            ],
            [10, 11],
        )

    def test_alternating_material_fan_separates_face_connected_bodies(self) -> None:
        # Four tetrahedra wind around the shared edge (0, 1).  Alternating
        # materials meet only on that edge, producing four incident faces in
        # each material union.  A face-conforming tet labelling alone is not a
        # sufficient printable-manifold proof; the owner builder must refine
        # or regularise this edge fan before export.
        nodes = np.asarray(
            (
                (0.0, 0.0, -1.0),
                (0.0, 0.0, 1.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (-1.0, 0.0, 0.0),
                (0.0, -1.0, 0.0),
            ),
            dtype=np.float64,
        )
        tetrahedra = np.asarray(
            (
                (0, 1, 2, 3),
                (0, 1, 3, 4),
                (0, 1, 4, 5),
                (0, 1, 5, 2),
            ),
            dtype=np.int32,
        )

        result = extract_material_union_surfaces(
            nodes,
            tetrahedra,
            np.asarray((1, 3, 1, 3), dtype=np.int8),
        )
        self.assertEqual([part.extruder for part in result.parts], [1, 3])
        self.assertEqual(
            [
                part.metadata["validation"]["surface_components"]
                for part in result.parts
            ],
            [2, 2],
        )
        self.assertTrue(
            all(
                part.metadata["validation"][
                    "edge_or_point_touch_uses_disjoint_vertex_indices"
                ]
                for part in result.parts
            )
        )
        audit = audit_material_union_topology(
            nodes,
            tetrahedra,
            np.asarray((1, 3, 1, 3), dtype=np.int8),
        )
        self.assertFalse(audit["all_material_unions_printable"])
        self.assertGreater(
            audit["materials"]["1"]["topology"]["nonmanifold_edges"],
            0,
        )
        self.assertGreater(
            audit["materials"]["3"]["topology"]["nonmanifold_edges"],
            0,
        )
        component_audit = audit_material_cell_components(
            nodes,
            tetrahedra,
            np.asarray((1, 3, 1, 3), dtype=np.int8),
        )
        self.assertTrue(
            component_audit["all_face_connected_material_bodies_printable"]
        )
        self.assertEqual(
            component_audit["materials"]["1"][
                "face_connected_components"
            ],
            2,
        )
        self.assertEqual(
            component_audit["materials"]["3"][
                "face_connected_components"
            ],
            2,
        )


if __name__ == "__main__":
    unittest.main()
