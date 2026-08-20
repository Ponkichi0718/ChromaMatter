from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import engine, mixer
from spectrum_mapper.models import (
    AppSettings,
    MeshLevel,
    PaletteSettings,
    ToneSettings,
)
from spectrum_mapper.paint_gui import _copy_palette_settings
from spectrum_mapper.palette_usage import palette_state_base_weights
from spectrum_mapper.parts import (
    palette_identity,
    palettes_are_identical,
    palettes_are_print_compatible,
    print_palette_identity,
)


def _row_ratios(definitions: str, count: int) -> list[int]:
    return [
        int(row.split(",")[4])
        for row in definitions.split(";")[: count - 4]
    ]


def _one_face_level() -> MeshLevel:
    return MeshLevel(
        vertices_unit=np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float64,
        ),
        faces=np.asarray([[0, 1, 2]], dtype=np.int32),
        vertex_colors=np.asarray(
            [[0.40, 0.12, 0.08], [0.40, 0.12, 0.08], [0.40, 0.12, 0.08]],
            dtype=np.float64,
        ),
        areas_unit=np.asarray([0.5], dtype=np.float64),
        neighbors=None,
    )


class OutputOnlyBlackCorrectionTests(unittest.TestCase):
    def test_f1_preset_has_expected_full_28_state_recipes(self) -> None:
        output = mixer.black_output_ratio_preset(0)

        self.assertEqual(len(output), mixer.MIXED_STATE_COUNT)
        for state in (5, 6, 7):
            self.assertEqual(output[state - 5], 80)
        for state in (11, 12, 13):
            self.assertEqual(output[state - 5], 90)
        for state in (17, 18, 19):
            self.assertEqual(output[state - 5], 86)
        self.assertEqual(
            {state: output[state - 5] for state in range(23, 29)},
            {23: 75, 24: 95, 25: 75, 26: 95, 27: 75, 28: 95},
        )

    def test_black_as_b_uses_direct_weak_black_percentages(self) -> None:
        output = mixer.black_output_ratio_preset(1)

        # F1+F2 is the first pair in every ratio family, and F2 is B.
        self.assertEqual(output[0], 10)   # target black 33 -> physical 10
        self.assertEqual(output[6], 20)   # target black 67 -> physical 20
        self.assertEqual(output[12], 14)  # target black 50 -> physical ~14.3
        self.assertEqual(output[18], 5)   # target black 25 -> physical 5
        self.assertEqual(output[19], 25)  # target black 75 -> physical 25
        self.assertAlmostEqual(
            palette_state_base_weights(16, output_mix_ratios_b=output)[1],
            1.0 / 7.0,
        )

    def test_16_24_32_exports_use_only_the_selected_output_prefix(self) -> None:
        output = mixer.black_output_ratio_preset(0)
        expected = mixer.print_palette_mix_specs(
            output_mix_ratios_b=output
        )
        for count in mixer.SUPPORTED_PALETTE_STATE_COUNTS:
            with self.subTest(count=count):
                definitions = engine.make_portable_mixed_definitions(
                    [33] * 6,
                    [67] * 6,
                    count,
                    output,
                )
                self.assertEqual(
                    _row_ratios(definitions, count),
                    [ratio for _a, _b, ratio in expected[: count - 4]],
                )
                palette = PaletteSettings(
                    palette_state_count=count,
                    enabled_states=[True] * count,
                    output_mix_ratios_b=output,
                )
                project = json.loads(engine._make_project_settings(palette))
                self.assertEqual(
                    project["mixed_filament_definitions"], definitions
                )

    def test_none_is_a_legacy_no_op_and_is_omitted_from_project_data(self) -> None:
        legacy = engine.make_portable_mixed_definitions([33] * 6, [67] * 6)
        explicit_none = engine.make_portable_mixed_definitions(
            [33] * 6,
            [67] * 6,
            16,
            None,
        )

        self.assertEqual(legacy, explicit_none)
        self.assertEqual(legacy, engine.PORTABLE_MIXED_DEFINITIONS)
        self.assertNotIn(
            "output_mix_ratios_b",
            AppSettings(palette=PaletteSettings()).to_dict()["palette"],
        )

    def test_output_recipe_does_not_change_display_recolor_or_manual_ids(self) -> None:
        plain = PaletteSettings(
            physical_hex=["#111111", "#F5F5F5", "#E32636", "#7A4A32"],
        )
        corrected = PaletteSettings(
            physical_hex=list(plain.physical_hex),
            output_mix_ratios_b=mixer.black_output_ratio_preset(0),
        )
        plain_hex, plain_rgb = mixer.build_palette_rgb(
            plain.physical_hex,
            plain.mix_hex_overrides,
            plain.mix_ratios_b,
            plain.secondary_mix_ratios_b,
        )
        corrected_hex, corrected_rgb = mixer.build_palette_rgb(
            corrected.physical_hex,
            corrected.mix_hex_overrides,
            corrected.mix_ratios_b,
            corrected.secondary_mix_ratios_b,
        )
        self.assertEqual(plain_hex, corrected_hex)
        np.testing.assert_array_equal(plain_rgb, corrected_rgb)

        level = _one_face_level()
        tone = ToneSettings(smoothing=False)
        plain_result = engine.recolor_level(level, 10.0, tone, plain)
        corrected_result = engine.recolor_level(level, 10.0, tone, corrected)
        np.testing.assert_array_equal(
            plain_result.palette_indices,
            corrected_result.palette_indices,
        )
        np.testing.assert_array_equal(
            plain_result.target_face_rgb,
            corrected_result.target_face_rgb,
        )

        manual = np.asarray([7], dtype=np.int8)
        plain_manual = engine.apply_palette_overrides(
            level, 10.0, plain, plain_result, manual
        )
        corrected_manual = engine.apply_palette_overrides(
            level, 10.0, corrected, corrected_result, manual
        )
        self.assertEqual(int(plain_manual.palette_indices[0]), 7)
        np.testing.assert_array_equal(
            plain_manual.palette_indices,
            corrected_manual.palette_indices,
        )
        np.testing.assert_array_equal(
            plain_manual.target_face_rgb,
            corrected_manual.target_face_rgb,
        )
        self.assertEqual(engine.PAINT_CODES[7], engine._paint_code_for_state(7))

    def test_project_round_trip_and_paint_copy_preserve_full_override(self) -> None:
        output = mixer.black_output_ratio_preset(0)
        settings = AppSettings(
            palette=PaletteSettings(output_mix_ratios_b=output),
            part_palettes={
                "part": PaletteSettings(output_mix_ratios_b=list(output))
            },
        )

        encoded = settings.to_dict()
        self.assertEqual(encoded["palette"]["output_mix_ratios_b"], output)
        restored = AppSettings.from_dict(encoded)
        self.assertEqual(restored.palette.output_mix_ratios_b, output)
        self.assertEqual(
            restored.part_palettes["part"].output_mix_ratios_b,
            output,
        )
        copied = _copy_palette_settings(restored.palette)
        self.assertEqual(copied.output_mix_ratios_b, output)
        self.assertIsNot(copied.output_mix_ratios_b, restored.palette.output_mix_ratios_b)

    def test_palette_identity_and_print_grouping_include_output_recipe(self) -> None:
        plain = PaletteSettings()
        corrected = PaletteSettings(
            output_mix_ratios_b=mixer.black_output_ratio_preset(0)
        )

        self.assertNotEqual(palette_identity(plain), palette_identity(corrected))
        self.assertNotEqual(
            print_palette_identity(plain),
            print_palette_identity(corrected),
        )
        self.assertFalse(palettes_are_identical(plain, corrected))
        self.assertFalse(palettes_are_print_compatible(plain, corrected))

    def test_invalid_full_override_and_black_slot_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "28 integers"):
            PaletteSettings(output_mix_ratios_b=[80] * 12)
        with self.assertRaisesRegex(ValueError, "0 to 100"):
            PaletteSettings(output_mix_ratios_b=[80] * 27 + [101])
        for invalid in (-1, 4, True, "0"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    mixer.black_output_ratio_preset(invalid)  # type: ignore[arg-type]

    def test_guide_separates_display_target_from_output_and_pure_slots(self) -> None:
        corrected = PaletteSettings(
            output_mix_ratios_b=mixer.black_output_ratio_preset(0)
        )
        with tempfile.TemporaryDirectory() as folder:
            corrected_path = Path(folder) / "corrected.txt"
            legacy_path = Path(folder) / "legacy.txt"
            engine.write_guide(
                corrected_path,
                Path("model.3mf"),
                100.0,
                corrected,
            )
            engine.write_guide(
                legacy_path,
                Path("model.3mf"),
                100.0,
                PaletteSettings(),
            )
            corrected_text = corrected_path.read_text(encoding="utf-8-sig")
            legacy_text = legacy_path.read_text(encoding="utf-8-sig")

        self.assertIn(
            "ID 5: F1+F2 目標/画面 B33% → 実機出力 B80%",
            corrected_text,
        )
        self.assertIn("Orca実効 B80% (A1:B4)", corrected_text)
        self.assertIn("state ID", corrected_text)
        self.assertIn("paint_color", corrected_text)
        self.assertIn("純色ID 1〜4", corrected_text)
        self.assertNotIn("目標/画面", legacy_text)
        self.assertIn("ID 5: F1+F2 （F2 33% / F1 67%）", legacy_text)


if __name__ == "__main__":
    unittest.main()
