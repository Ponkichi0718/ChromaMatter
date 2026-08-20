from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest
from zipfile import ZipFile

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import engine, mixer
from spectrum_mapper.models import AppSettings, MeshLevel, PaletteSettings, ToneSettings
from spectrum_mapper.paint_gui import (
    _copy_palette_settings,
    _is_manual_only_palette_state,
)
from spectrum_mapper.parts import palette_identity, print_palette_identity


PHYSICAL = ["#111111", "#F6F6F6", "#E32636", "#7A4A32"]


def _two_face_level(face_rgb: np.ndarray) -> MeshLevel:
    vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [2.0, 0.0, 0.0],
            [3.0, 0.0, 0.0],
            [2.0, 1.0, 0.0],
        ],
        dtype=np.float64,
    )
    return MeshLevel(
        vertices_unit=vertices,
        faces=np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int32),
        vertex_colors=np.repeat(np.asarray(face_rgb), 3, axis=0),
        areas_unit=np.asarray([0.5, 0.5], dtype=np.float64),
        neighbors=None,
    )


class BlackFreeGradientTests(unittest.TestCase):
    def test_state_helpers_keep_pure_black_and_preserve_stable_ids(self) -> None:
        self.assertEqual(
            mixer.black_containing_mixed_states(16, 0),
            (4, 5, 6, 10, 11, 12),
        )
        self.assertEqual(
            mixer.black_containing_mixed_states(24, 0),
            (4, 5, 6, 10, 11, 12, 16, 17, 18, 22, 23),
        )
        self.assertNotIn(0, mixer.black_containing_mixed_states(32, 0))
        self.assertEqual(
            mixer.black_free_replacement_states(16, 2, 3),
            (2, 3, 9, 15),
        )
        self.assertEqual(
            mixer.black_free_replacement_states(24, 2, 3),
            (2, 3, 9, 15, 21),
        )
        enabled = [False] * mixer.PALETTE_STATE_COUNT
        enabled[15] = True
        self.assertEqual(
            mixer.black_free_replacement_states(16, 2, 3, enabled),
            (15,),
        )

    def test_slots_are_strict_distinct_zero_based_indices(self) -> None:
        for values in ((True, 2, 3), (0, 0, 3), (0, 2, 4), (0, 2, 2)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                PaletteSettings(
                    black_free_black_slot=values[0],
                    black_free_red_slot=values[1],
                    black_free_brown_slot=values[2],
                )

    def test_project_round_trip_and_identity_policy(self) -> None:
        plain = PaletteSettings(physical_hex=PHYSICAL)
        black_free = PaletteSettings(
            physical_hex=PHYSICAL,
            black_free_gradient_enabled=True,
            black_free_black_slot=0,
            black_free_red_slot=2,
            black_free_brown_slot=3,
        )
        restored = AppSettings.from_dict(
            AppSettings(
                palette=black_free,
                part_palettes={"head": black_free},
            ).to_dict()
        )
        self.assertTrue(restored.palette.black_free_gradient_enabled)
        self.assertEqual(restored.palette.black_free_red_slot, 2)
        self.assertTrue(
            restored.part_palettes["head"].black_free_gradient_enabled
        )
        self.assertNotEqual(palette_identity(plain), palette_identity(black_free))
        self.assertEqual(
            print_palette_identity(plain),
            print_palette_identity(black_free),
        )
        copied = _copy_palette_settings(black_free)
        self.assertTrue(copied.black_free_gradient_enabled)
        self.assertEqual(copied.black_free_black_slot, 0)
        self.assertEqual(copied.black_free_red_slot, 2)
        self.assertEqual(copied.black_free_brown_slot, 3)

    def test_black_mixes_are_marked_manual_only_without_disabling_paint(self) -> None:
        plain = PaletteSettings(physical_hex=PHYSICAL)
        black_free = PaletteSettings(
            physical_hex=PHYSICAL,
            black_free_gradient_enabled=True,
        )
        self.assertFalse(_is_manual_only_palette_state(plain, 5))
        self.assertTrue(_is_manual_only_palette_state(black_free, 5))
        self.assertFalse(_is_manual_only_palette_state(black_free, 0))
        black_free.enabled_states[2] = False
        self.assertTrue(_is_manual_only_palette_state(black_free, 2))

    def test_automatic_black_mix_is_remapped_but_pure_black_is_preserved(self) -> None:
        plain = PaletteSettings(physical_hex=PHYSICAL)
        black_free = PaletteSettings(
            physical_hex=PHYSICAL,
            black_free_gradient_enabled=True,
        )
        _hex, palette_rgb = mixer.build_palette_rgb(
            plain.physical_hex,
            plain.mix_hex_overrides,
            plain.mix_ratios_b,
            plain.secondary_mix_ratios_b,
        )
        black_red_state = 5
        level = _two_face_level(
            np.asarray([palette_rgb[black_red_state], palette_rgb[0]])
        )
        tone = ToneSettings(white_point=1.0, smoothing=False)

        baseline = engine.recolor_level(level, 10.0, tone, plain)
        result = engine.recolor_level(level, 10.0, tone, black_free)

        np.testing.assert_array_equal(baseline.palette_indices, [5, 0])
        self.assertIn(
            int(result.palette_indices[0]),
            mixer.black_free_replacement_states(16, 2, 3),
        )
        self.assertEqual(int(result.palette_indices[1]), 0)
        self.assertEqual(result.black_free_remapped_faces, 1)
        self.assertFalse(
            np.isin(
                result.palette_indices,
                mixer.black_containing_mixed_states(16, 0),
            ).any()
        )

    def test_hotfix_counts_black_mix_inside_final_adaptive_paint_tree(self) -> None:
        import smooth_paint
        import spectrum_mapper_hotfix as hotfix
        from test_generated_surface_color import _fixture

        prepared, colors = _fixture()
        colors.palette_indices[:] = 2
        colors.black_free_remapped_faces = 9
        prepared._hotfix_subtriangle_paint = {
            0: smooth_paint.PaintNode.branch(
                tuple(
                    smooth_paint.PaintNode(state)
                    for state in (5, 2, 2, 2)
                )
            )
        }
        palette = PaletteSettings(
            physical_hex=PHYSICAL,
            black_free_gradient_enabled=True,
        )

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "adaptive-black-free.3mf"
            validation = hotfix._write_3mf_atomic_fixed(
                path,
                prepared,
                colors,
                10.0,
                palette,
            )
            self.assertEqual(validation["remaining_black_mix_faces"], 1)
            self.assertAlmostEqual(
                validation["remaining_black_mix_leaf_area"], 0.25
            )
            with ZipFile(path) as archive:
                metadata = json.loads(
                    archive.read(
                        "Metadata/full_spectrum_palette.json"
                    ).decode("utf-8")
                )["black_free_gradient"]
            self.assertEqual(metadata["remaining_black_mix_faces"], 1)
            self.assertAlmostEqual(
                metadata["remaining_black_mix_leaf_area"], 0.25
            )

    def test_manual_black_mix_remains_explicit_and_counter_is_preserved(self) -> None:
        palette = PaletteSettings(
            physical_hex=PHYSICAL,
            black_free_gradient_enabled=True,
        )
        _hex, palette_rgb = mixer.build_palette_rgb(
            palette.physical_hex,
            palette.mix_hex_overrides,
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
        level = _two_face_level(np.asarray([palette_rgb[5], palette_rgb[0]]))
        automatic = engine.recolor_level(
            level,
            10.0,
            ToneSettings(white_point=1.0, smoothing=False),
            palette,
        )

        manual = engine.apply_palette_overrides(
            level,
            10.0,
            palette,
            automatic,
            np.asarray([5, -1], dtype=np.int8),
        )

        self.assertEqual(int(manual.palette_indices[0]), 5)
        self.assertEqual(manual.manual_override_faces, 1)
        self.assertEqual(
            manual.black_free_remapped_faces,
            automatic.black_free_remapped_faces,
        )

    def test_mode_fails_closed_when_no_red_brown_candidate_is_enabled(self) -> None:
        enabled = [True] * mixer.PALETTE_STATE_COUNT
        for state in mixer.black_free_replacement_states(16, 2, 3):
            enabled[state] = False
        palette = PaletteSettings(
            physical_hex=PHYSICAL,
            enabled_states=enabled,
            black_free_gradient_enabled=True,
        )
        _hex, palette_rgb = mixer.build_palette_rgb(
            palette.physical_hex,
            palette.mix_hex_overrides,
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
        level = _two_face_level(np.asarray([palette_rgb[5], palette_rgb[0]]))

        with self.assertRaisesRegex(engine.EngineError, "1色以上"):
            engine.recolor_level(
                level,
                10.0,
                ToneSettings(white_point=1.0, smoothing=False),
                palette,
            )

    def test_multipart_validation_uses_any_enabled_and_ambiguous_slots_are_null(self) -> None:
        from test_generated_surface_color import _fixture

        prepared, colors = _fixture()
        global_palette = PaletteSettings(physical_hex=PHYSICAL)
        local_palette = PaletteSettings(
            physical_hex=PHYSICAL,
            black_free_gradient_enabled=True,
            black_free_black_slot=1,
            black_free_red_slot=2,
            black_free_brown_slot=3,
        )
        colors.palette_indices[:] = 2
        local_face = int(np.flatnonzero(prepared.final.face_part_ids == 1)[0])
        colors.palette_indices[local_face] = 7
        colors.palette_face_counts = np.bincount(
            colors.palette_indices,
            minlength=mixer.PALETTE_STATE_COUNT,
        )

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "multipart-black-free.3mf"
            validation = engine.write_3mf_atomic(
                path,
                prepared,
                colors,
                10.0,
                global_palette,
                {"1:cool": local_palette},
            )
            self.assertTrue(validation["black_free_gradient_enabled"])
            self.assertIsNone(validation["black_free_black_slot"])
            self.assertIsNone(validation["black_free_red_slot"])
            self.assertIsNone(validation["black_free_brown_slot"])
            self.assertEqual(validation["remaining_black_mix_faces"], 1)
            records = validation["black_free_gradient_parts"]
            self.assertFalse(records[0]["enabled"])
            self.assertTrue(records[1]["enabled"])
            self.assertEqual(records[1]["black_slot"], 1)
            with ZipFile(path) as archive:
                metadata = json.loads(
                    archive.read(
                        "Metadata/full_spectrum_palette.json"
                    ).decode("utf-8")
                )["black_free_gradient"]
            self.assertTrue(metadata["enabled"])
            self.assertIsNone(metadata["black_slot"])
            self.assertEqual(metadata["remaining_black_mix_faces"], 1)
            report = engine.make_report(
                prepared,
                colors,
                10.0,
                ToneSettings(smoothing=False),
                global_palette,
                validation,
            )
            self.assertTrue(report["color"]["black_free_gradient_enabled"])
            self.assertIsNone(report["color"]["black_free_black_slot"])
            self.assertEqual(
                report["color"]["remaining_black_mix_faces"], 1
            )

    def test_part_local_policy_only_remaps_the_enabled_part(self) -> None:
        enabled_palette = PaletteSettings(
            physical_hex=PHYSICAL,
            black_free_gradient_enabled=True,
        )
        plain_palette = PaletteSettings(physical_hex=PHYSICAL)
        _hex, palette_rgb = mixer.build_palette_rgb(
            enabled_palette.physical_hex,
            enabled_palette.mix_hex_overrides,
            enabled_palette.mix_ratios_b,
            enabled_palette.secondary_mix_ratios_b,
        )
        level = _two_face_level(
            np.asarray([palette_rgb[5], palette_rgb[5]])
        )
        level.face_part_ids = np.asarray([0, 1], dtype=np.int16)
        level.part_keys = ("body", "head")
        level.part_names = ("body", "head")

        result = engine.recolor_level_parts(
            level,
            10.0,
            ToneSettings(white_point=1.0, smoothing=False),
            enabled_palette,
            {"head": plain_palette},
        )

        self.assertNotIn(
            int(result.palette_indices[0]),
            mixer.black_containing_mixed_states(16, 0),
        )
        self.assertEqual(int(result.palette_indices[1]), 5)
        self.assertEqual(result.black_free_remapped_faces, 1)
        self.assertEqual(
            [metric["black_free_remapped_faces"] for metric in result.part_metrics],
            [1, 0],
        )

    def test_3mf_metadata_reports_final_remaining_manual_black_mix(self) -> None:
        from test_generated_surface_color import _fixture

        prepared, colors = _fixture()
        palette = PaletteSettings(
            physical_hex=PHYSICAL,
            black_free_gradient_enabled=True,
        )
        colors.palette_indices[:] = 2
        colors.palette_indices[0] = 5  # explicit/manual black+red mix
        colors.palette_face_counts = np.bincount(
            colors.palette_indices,
            minlength=mixer.PALETTE_STATE_COUNT,
        )
        colors.black_free_remapped_faces = 17

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "black-free.3mf"
            validation = engine.write_3mf_atomic(
                path,
                prepared,
                colors,
                10.0,
                palette,
            )
            self.assertTrue(validation["black_free_gradient_enabled"])
            self.assertEqual(validation["black_free_remapped_faces"], 17)
            self.assertEqual(validation["remaining_black_mix_faces"], 1)
            with ZipFile(path) as archive:
                metadata = json.loads(
                    archive.read(
                        "Metadata/full_spectrum_palette.json"
                    ).decode("utf-8")
                )
                project = json.loads(
                    archive.read(
                        "Metadata/project_settings.config"
                    ).decode("utf-8")
                )
            policy = metadata["black_free_gradient"]
            self.assertEqual(policy["slot_index_base"], 0)
            self.assertEqual(policy["black_slot"], 0)
            self.assertEqual(policy["red_slot"], 2)
            self.assertEqual(policy["brown_slot"], 3)
            self.assertEqual(policy["remaining_black_mix_faces"], 1)
            self.assertEqual(
                project["mixed_filament_definitions"],
                engine.make_portable_mixed_definitions(
                    palette.mix_ratios_b,
                    palette.secondary_mix_ratios_b,
                    palette.palette_state_count,
                    palette.output_mix_ratios_b,
                ),
            )


if __name__ == "__main__":
    unittest.main()
