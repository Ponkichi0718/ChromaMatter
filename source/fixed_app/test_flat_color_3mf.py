from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest
from zipfile import ZipFile

import numpy as np

import smooth_paint
import spectrum_mapper_hotfix as hotfix
from spectrum_mapper import engine, workflow
from spectrum_mapper.models import (
    COLOR_MODE_FLAT_FOUR,
    ColorResult,
    PaletteSettings,
)
from test_hotfix import tiny_closed_color_result, tiny_closed_prepared
from test_part_exports import (
    _settings_with_distinct_part_filaments,
    _two_watertight_tetrahedra,
)


def _flat_colors() -> ColorResult:
    source = tiny_closed_color_result()
    indices = np.asarray([0, 1, 2, 3], dtype=np.int8)
    counts = np.bincount(indices, minlength=32).astype(np.int64)
    return ColorResult(
        tone_vertex_rgb=source.tone_vertex_rgb,
        source_face_rgb=source.source_face_rgb,
        palette_indices=indices,
        target_face_rgb=source.target_face_rgb,
        delta_e=source.delta_e,
        smoothed_faces=source.smoothed_faces,
        palette_face_counts=counts,
        palette_area_fractions=counts.astype(np.float64) / 4.0,
        pink_area_fraction=0.25,
        manual_override_faces=0,
    )


class FlatColor3mfTests(unittest.TestCase):
    def test_public_writers_use_the_flat_aware_hotfix(self) -> None:
        self.assertIs(engine.write_3mf_atomic, hotfix._write_3mf_atomic_fixed)
        self.assertIs(workflow.write_3mf_atomic, hotfix._write_3mf_atomic_fixed)

    def test_hotfix_export_is_a_four_physical_color_project(self) -> None:
        prepared = tiny_closed_prepared()
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            palette_state_count=32,
            enabled_states=[True] * 32,
            output_mix_ratios_b=[25] * 28,
            black_free_gradient_enabled=True,
        )
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "flat.3mf"
            validation = hotfix._write_3mf_atomic_fixed(
                destination,
                prepared,
                _flat_colors(),
                100.0,
                palette,
            )
            guide_path = Path(folder) / "flat_使い方.txt"
            hotfix._write_guide_fixed(
                guide_path,
                destination,
                100.0,
                palette,
            )
            with ZipFile(destination) as archive:
                root = archive.read("3D/3dmodel.model").decode("utf-8")
                model_settings = archive.read(
                    "Metadata/model_settings.config"
                ).decode("utf-8")
                project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
                metadata = json.loads(
                    archive.read("Metadata/full_spectrum_palette.json")
                )
                object_xml = archive.read("3D/Objects/object_1.model")

            guide = guide_path.read_text(encoding="utf-8")

        self.assertEqual(validation["palette_mode"], COLOR_MODE_FLAT_FOUR)
        self.assertEqual(validation["active_palette_state_count"], 4)
        self.assertEqual(validation["portable_palette_state_count"], 4)
        self.assertEqual(validation["mixed_definition_active_rows"], 0)
        self.assertEqual(validation["requested_output_mix_ratios_b_percent"], [])
        self.assertFalse(validation["output_ratio_override_active"])
        self.assertFalse(validation["black_free_gradient_enabled"])
        self.assertTrue(validation["mixed_definitions_match_output_specs"])
        self.assertEqual(sum(validation["paint_color_state_counts"][4:]), 0)
        self.assertEqual(sum(validation["portable_material_state_counts"][4:]), 0)
        self.assertEqual(object_xml.count(b"<base "), 4)
        self.assertIn("Flat 4 Colors", root)
        self.assertIn('plater_name" value="Flat 4 Colors (F1-F4)', model_settings)
        definitions = project["mixed_filament_definitions"]
        self.assertEqual(definitions, engine.make_auto_mixed_tombstones())
        rows = [row.split(",") for row in definitions.split(";")]
        self.assertEqual(len(rows), 6)
        self.assertTrue(
            all(
                row[2:5] == ["0", "0", "50"]
                and "d1" in row
                and "o1" in row
                for row in rows
            )
        )
        self.assertFalse(
            any(row[2] == "1" and "d0" in row for row in rows)
        )
        self.assertEqual(len(project["filament_colour"]), 4)
        self.assertEqual(len(project["filament_multi_colors"]), 4)
        self.assertEqual(len(project["filament_settings_id"]), 4)
        self.assertEqual(
            project["chroma_matter_palette_mode"], COLOR_MODE_FLAT_FOUR
        )
        self.assertEqual(metadata["palette_mode"], COLOR_MODE_FLAT_FOUR)
        self.assertEqual(metadata["palette_state_count"], 4)
        self.assertEqual(metadata["configured_palette_state_count"], 32)
        self.assertEqual(metadata["mixed_state_count"], 0)
        self.assertEqual(
            metadata["snapmaker_orca_display_model"],
            "physical-F1-F4-only",
        )
        self.assertEqual(len(metadata["states"]), 4)
        self.assertNotIn("print_mix_specs", metadata)
        self.assertNotIn("output_mix_ratios_b_percent", metadata)
        self.assertEqual(metadata["mix_ratios_b_percent"], [])
        self.assertEqual(metadata["secondary_mix_ratios_b_percent"], [])
        self.assertNotRegex(
            model_settings,
            r'extruder" value="(?:[5-9]|[1-9][0-9]+)"',
        )
        self.assertFalse(
            any(
                int(value) > 3
                for value in re.findall(rb'\sp1="([0-9]+)"', object_xml)
            )
        )
        self.assertIn("混色stateは0色", guide)
        self.assertIn("色ID 1〜4", guide)

    def test_flat_writer_projects_a_remaining_mixed_face_without_mutating_source(self) -> None:
        colors = tiny_closed_color_result()
        # State 32 can survive in a project that was painted in the 32-state
        # Full Spectrum mode and later switched to Flat while keeping edits.
        colors.palette_indices[1] = 31
        original_indices = colors.palette_indices.copy()
        with tempfile.TemporaryDirectory() as folder:
            validation = hotfix._write_3mf_atomic_fixed(
                Path(folder) / "projected.3mf",
                tiny_closed_prepared(),
                colors,
                100.0,
                PaletteSettings(color_mode=COLOR_MODE_FLAT_FOUR),
            )

        np.testing.assert_array_equal(colors.palette_indices, original_indices)
        self.assertEqual(validation["flat_four_projected_faces"], 1)
        self.assertEqual(sum(validation["paint_color_state_counts"]), 4)
        self.assertEqual(sum(validation["paint_color_state_counts"][4:]), 0)
        self.assertEqual(sum(validation["portable_material_state_counts"][4:]), 0)

    def test_flat_projection_uses_each_parts_own_physical_palette(self) -> None:
        first = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=["#000000", "#FFFFFF", "#00FF00", "#FF0000"],
            mix_hex_overrides=["#00FF00", None, None, None, None, None],
        )
        second = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=["#FFFFFF", "#000000", "#FF0000", "#0000FF"],
            mix_hex_overrides=["#0000FF", None, None, None, None, None],
        )
        source = np.asarray([4, 4], dtype=np.int8)

        projected, count = engine._project_indices_to_flat_four(
            source,
            np.asarray([0, 1], dtype=np.int16),
            (first, second),
        )

        np.testing.assert_array_equal(source, np.asarray([4, 4], dtype=np.int8))
        np.testing.assert_array_equal(projected, np.asarray([2, 3], dtype=np.int8))
        self.assertEqual(count, 2)

    def test_flat_hotfix_does_not_restore_old_mixed_adaptive_paint(self) -> None:
        prepared = tiny_closed_prepared()
        prepared._hotfix_subtriangle_paint = {
            0: smooth_paint.PaintNode.branch(
                tuple(smooth_paint.PaintNode(state) for state in (0, 9, 2, 3))
            )
        }
        with tempfile.TemporaryDirectory() as folder:
            validation = hotfix._write_3mf_atomic_fixed(
                Path(folder) / "adaptive-flat.3mf",
                prepared,
                _flat_colors(),
                100.0,
                PaletteSettings(color_mode=COLOR_MODE_FLAT_FOUR),
            )

        self.assertEqual(validation["adaptive_paint_faces"], 0)
        self.assertEqual(sum(validation["paint_color_state_counts"][4:]), 0)
        self.assertEqual(sum(validation["paint_color_leaf_area_counts"][4:]), 0.0)

    def test_individual_flat_projects_use_flat_file_names_and_manifest(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _settings_with_distinct_part_filaments()
        settings.palette.color_mode = COLOR_MODE_FLAT_FOUR
        for palette in settings.part_palettes.values():
            palette.color_mode = COLOR_MODE_FLAT_FOUR

        with tempfile.TemporaryDirectory() as folder:
            paths = workflow._write_individual_part_models(
                prepared,
                settings,
                Path(folder) / "assembly.3mf",
                manual_overrides=None,
                progress=None,
            )
            manifest = json.loads(
                (paths[0].parent / "パーツ別3MF_manifest.json").read_text(
                    encoding="utf-8-sig"
                )
            )

        self.assertTrue(all(path.name.endswith("_Flat4.3mf") for path in paths))
        self.assertEqual(manifest["palette_modes"], [COLOR_MODE_FLAT_FOUR])
        self.assertTrue(
            all(
                item["palette_mode"] == COLOR_MODE_FLAT_FOUR
                for item in manifest["parts"]
            )
        )


if __name__ == "__main__":
    unittest.main()
