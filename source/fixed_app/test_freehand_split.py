from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from spectrum_mapper.engine import edge_topology, triangle_areas
from spectrum_mapper.freehand_split import (
    FreehandSplitError,
    apply_lasso_split,
    apply_level_partition_to_prepared,
    canvas_polygon_to_render,
    decode_manual_part_partition,
    encode_manual_part_partition,
    inherit_explicit_part_palette,
    plan_lasso_component_split,
)
from spectrum_mapper.models import (
    AppSettings,
    MeshLevel,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
)
from spectrum_mapper.paint import (
    decode_manual_overrides,
    encode_manual_overrides,
    mesh_fingerprint,
)
from spectrum_mapper.parts import resolve_palette_for_part_key
from spectrum_mapper.workflow import export_bundle


def two_tetrahedra_level() -> MeshLevel:
    vertices = np.asarray(
        [
            (0.0, 0.0, 0.0),
            (0.2, 0.0, 0.0),
            (0.0, 0.2, 0.0),
            (0.0, 0.0, 0.2),
            (0.7, 0.0, 0.0),
            (0.9, 0.0, 0.0),
            (0.7, 0.2, 0.0),
            (0.7, 0.0, 0.2),
        ],
        dtype=np.float64,
    )
    tetra = np.asarray(
        [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)],
        dtype=np.int32,
    )
    faces = np.vstack((tetra, tetra + 4))
    colors = np.asarray(
        [
            (0.10, 0.10, 0.10),
            (0.25, 0.25, 0.25),
            (0.45, 0.45, 0.45),
            (0.65, 0.65, 0.65),
            (0.80, 0.20, 0.30),
            (0.90, 0.30, 0.40),
            (0.75, 0.15, 0.25),
            (0.95, 0.40, 0.50),
        ],
        dtype=np.float64,
    )
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=colors,
        areas_unit=triangle_areas(vertices, faces),
        neighbors=None,
        face_part_ids=np.zeros(len(faces), dtype=np.int16),
        part_names=("whole",),
        part_keys=("0:whole",),
    )


def lasso_plan(level: MeshLevel):
    ids = np.full((20, 30), -1, dtype=np.int32)
    ids[3:17, 2:12] = 0
    ids[5:15, 20:28] = 4
    polygon = ((18, 3), (29, 3), (29, 17), (18, 17))
    return plan_lasso_component_split(level, ids, polygon, 0)


def prepared_from_level(level: MeshLevel) -> PreparedGeometry:
    source = ObjAsset(
        path=Path("two_tetrahedra.obj"),
        sha256="0" * 64,
        file_size=1,
        vertices=level.vertices_unit.copy(),
        colors=level.vertex_colors.copy(),
        faces=level.faces.copy(),
        original_vertex_count=len(level.vertices_unit),
        original_face_count=len(level.faces),
        warnings=[],
        part_names=("whole",),
        part_keys=("0:whole",),
        face_part_ids=np.zeros(len(level.faces), dtype=np.int16),
        part_face_counts=(len(level.faces),),
        part_vertex_counts=(len(level.vertices_unit),),
    )
    topology = edge_topology(level.faces, len(level.vertices_unit))
    return PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(level.vertices_unit),
        clean_face_count=len(level.faces),
        removed_vertices=0,
        removed_faces=0,
        topology=topology,
        source_area_unit=float(level.areas_unit.sum()),
        source_volume_unit=0.0,
        simplified_area_unit=float(level.areas_unit.sum()),
        simplified_volume_unit=0.0,
        source_dimensions_unit=np.ptp(level.vertices_unit, axis=0),
        warnings=[],
        part_names=level.part_names,
        part_keys=level.part_keys,
        part_stats=[],
        assembly={"all_parts_watertight": True},
    )


class FreehandSplitTests(unittest.TestCase):
    def test_canvas_points_map_to_face_id_render_space(self) -> None:
        mapping = (100, 50, 400, 200, 800, 600)
        self.assertEqual(
            canvas_polygon_to_render(
                mapping,
                ((100, 50), (500, 250), (300, 150)),
            ),
            ((0.0, 0.0), (800.0, 600.0), (400.0, 300.0)),
        )
        with self.assertRaisesRegex(FreehandSplitError, "3点以上"):
            canvas_polygon_to_render(mapping, ((100, 50), (500, 250)))

    def test_lasso_expands_visible_seed_to_closed_component(self) -> None:
        level = two_tetrahedra_level()
        plan = lasso_plan(level)
        np.testing.assert_array_equal(plan.selected_faces, np.arange(4, 8))
        self.assertEqual(plan.remaining_faces, 4)
        self.assertAlmostEqual(plan.selected_visible_coverage, 1.0)

        before_faces = level.faces.copy()
        before_colors = level.vertex_colors.copy()
        split = apply_lasso_split(level, plan)
        np.testing.assert_array_equal(split.faces, before_faces)
        np.testing.assert_array_equal(split.vertex_colors, before_colors)
        np.testing.assert_array_equal(split.face_part_ids[:4], 0)
        np.testing.assert_array_equal(split.face_part_ids[4:], 1)
        self.assertEqual(split.part_keys[1], "0:whole/cut:lasso-1")
        self.assertTrue(
            edge_topology(split.faces[:4], len(split.vertices_unit))["watertight"]
        )
        self.assertTrue(
            edge_topology(split.faces[4:], len(split.vertices_unit))["watertight"]
        )

    def test_connected_model_is_refused_instead_of_creating_open_parts(self) -> None:
        level = two_tetrahedra_level()
        connected = MeshLevel(
            vertices_unit=level.vertices_unit[:4],
            faces=level.faces[:4],
            vertex_colors=level.vertex_colors[:4],
            areas_unit=level.areas_unit[:4],
            neighbors=None,
            face_part_ids=np.zeros(4, dtype=np.int16),
            part_names=("one",),
            part_keys=("0:one",),
        )
        ids = np.zeros((10, 10), dtype=np.int32)
        with self.assertRaisesRegex(FreehandSplitError, "1つにつながって"):
            plan_lasso_component_split(
                connected,
                ids,
                ((1, 1), (8, 1), (8, 8), (1, 8)),
                0,
            )

    def test_project_partition_round_trip_keeps_face_indices_and_paint_ids(self) -> None:
        original = two_tetrahedra_level()
        split = apply_lasso_split(original, lasso_plan(original))
        paint_ids = np.asarray([0, 1, 2, 3, 4, 5, 6, 7], dtype=np.int8)
        fingerprint = mesh_fingerprint(split)
        payload = encode_manual_part_partition(split, fingerprint)
        paint_payload = encode_manual_overrides(paint_ids, fingerprint)
        restored = decode_manual_part_partition(
            original,
            payload,
            expected_fingerprint=fingerprint,
        )
        np.testing.assert_array_equal(restored.faces, original.faces)
        np.testing.assert_array_equal(restored.face_part_ids, split.face_part_ids)
        self.assertEqual(restored.part_names, split.part_names)
        self.assertEqual(restored.part_keys, split.part_keys)
        restored_paint = decode_manual_overrides(
            paint_payload,
            expected_face_count=len(restored.faces),
            expected_fingerprint=mesh_fingerprint(restored),
        )
        np.testing.assert_array_equal(restored_paint, paint_ids)

    def test_new_part_inherits_source_custom_palette(self) -> None:
        level = two_tetrahedra_level()
        split = apply_lasso_split(level, lasso_plan(level))
        custom = PaletteSettings(
            physical_hex=["#102030", "#405060", "#708090", "#A0B0C0"]
        )
        settings = AppSettings(part_palettes={"0:whole": custom})
        self.assertTrue(
            inherit_explicit_part_palette(
                settings,
                "0:whole",
                split.part_keys[1],
            )
        )
        self.assertIn(split.part_keys[1], settings.part_palettes)
        self.assertIsNot(settings.part_palettes[split.part_keys[1]], custom)
        self.assertIs(
            resolve_palette_for_part_key(settings, split.part_keys[1]),
            settings.part_palettes[split.part_keys[1]],
        )
        self.assertEqual(
            settings.part_palettes[split.part_keys[1]].physical_hex,
            custom.physical_hex,
        )

    def test_export_writes_two_coloured_objects_and_two_individual_3mfs(self) -> None:
        level = two_tetrahedra_level()
        split = apply_lasso_split(level, lasso_plan(level))
        prepared = prepared_from_level(level)
        apply_level_partition_to_prepared(prepared, split)
        settings = AppSettings()
        settings.geometry.height_mm = 50.0
        settings.geometry.export_individual_parts = True
        settings.tone.smoothing = False
        manual = np.asarray([0, 1, 2, 3, 4, 5, 6, 7], dtype=np.int8)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "lasso.3mf"
            result = export_bundle(
                prepared,
                settings,
                destination,
                include_vertex_obj=False,
                manual_overrides=manual,
            )
            self.assertTrue(result.model_path.is_file())
            self.assertEqual(len(result.part_model_paths), 2)
            self.assertTrue(all(path.is_file() for path in result.part_model_paths))
            self.assertEqual(result.validation["parts"], 2)
            self.assertEqual(len(result.validation["part_topologies"]), 2)
            self.assertEqual(result.validation["watertight_parts"], 2)
            self.assertTrue(
                all(
                    topology["watertight"] and topology["positive_volume"]
                    for topology in result.validation["part_topologies"]
                )
            )


if __name__ == "__main__":
    unittest.main()
