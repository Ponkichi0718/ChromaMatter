from __future__ import annotations

from pathlib import Path
import json
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import smooth_paint
from spectrum_mapper import engine, mixer
from spectrum_mapper.models import AppSettings, PaletteSettings
from test_orca_vectors import reference_encode_paint_color


PHYSICAL_HEX = ["#123456", "#D47A21", "#38AFC2", "#7B2DE2"]
PRIMARY_RATIOS_B = [20, 25, 40, 60, 75, 80]
SECONDARY_RATIOS_B = [80, 75, 60, 40, 25, 20]


class ExtendedPaletteTests(unittest.TestCase):
    def test_build_palette_has_32_states_and_preserves_the_legacy_first_sixteen(self) -> None:
        legacy_overrides = [
            "#0B1C2D",
            "#1C2D3E",
            "#2D3E4F",
            "#3E4F50",
            "#4F5061",
            "#506172",
        ]
        palette_hex, palette_rgb = mixer.build_palette_rgb(
            PHYSICAL_HEX,
            legacy_overrides,
            PRIMARY_RATIOS_B,
            SECONDARY_RATIOS_B,
        )

        expected_legacy = [
            *(mixer.normalize_hex(value) for value in PHYSICAL_HEX),
            *(mixer.normalize_hex(value) for value in legacy_overrides),
        ]
        self.assertEqual(mixer.PALETTE_STATE_COUNT, 32)
        self.assertEqual(len(palette_hex), 32)
        self.assertEqual(palette_rgb.shape, (32, 3))
        self.assertEqual(palette_hex[:10], expected_legacy)
        np.testing.assert_allclose(
            palette_rgb[:10],
            np.asarray([mixer.hex_to_rgb8(value) for value in expected_legacy]) / 255.0,
        )

    def test_each_pair_has_one_primary_and_one_secondary_ratio_in_stable_order(self) -> None:
        specs = mixer.palette_mix_specs(PRIMARY_RATIOS_B, SECONDARY_RATIOS_B)

        expected_primary = tuple(
            (left, right, ratio)
            for (left, right), ratio in zip(
                mixer.PAIR_INDICES, PRIMARY_RATIOS_B, strict=True
            )
        )
        expected_secondary = tuple(
            (left, right, ratio)
            for (left, right), ratio in zip(
                mixer.PAIR_INDICES, SECONDARY_RATIOS_B, strict=True
            )
        )
        self.assertEqual(len(specs), 28)
        self.assertEqual(specs[:6], expected_primary)
        self.assertEqual(specs[6:12], expected_secondary)
        self.assertEqual(specs[12:18], tuple(
            (left, right, 50) for left, right in mixer.PAIR_INDICES
        ))

    def test_mixed_definitions_have_12_custom_rows_then_6_deleted_rows(self) -> None:
        rows = [
            row.split(",")
            for row in engine.make_portable_mixed_definitions(
                PRIMARY_RATIOS_B, SECONDARY_RATIOS_B
            ).split(";")
        ]
        expected_specs = mixer.palette_mix_specs(
            PRIMARY_RATIOS_B, SECONDARY_RATIOS_B
        )[:12]

        self.assertEqual(len(expected_specs), 12)
        self.assertEqual(len(rows), 18)
        for row_index, (row, expected_spec) in enumerate(
            zip(rows[:12], expected_specs, strict=True)
        ):
            with self.subTest(custom_row=row_index + 1):
                left, right, ratio_b = expected_spec
                self.assertEqual(
                    (int(row[0]) - 1, int(row[1]) - 1, int(row[4])),
                    (left, right, ratio_b),
                )
                self.assertEqual(row[2:4], ["1", "1"])
                self.assertEqual(row[12:14], ["d0", "o0"])
                self.assertEqual(row[14], f"u{row_index + 1}")

        for deleted_index, (row, expected_pair) in enumerate(
            zip(rows[12:], mixer.PAIR_INDICES, strict=True), start=13
        ):
            with self.subTest(deleted_row=deleted_index):
                left, right = expected_pair
                self.assertEqual(
                    (int(row[0]) - 1, int(row[1]) - 1, int(row[4])),
                    (left, right, 50),
                )
                self.assertEqual(row[2:4], ["0", "0"])
                self.assertEqual(row[12:14], ["d1", "o1"])
                self.assertEqual(row[14], f"u{deleted_index}")

    def test_all_32_paint_codes_match_official_reference_codec(self) -> None:
        self.assertEqual(smooth_paint.STATE_COUNT, 32)
        self.assertEqual(len(engine.PAINT_CODES), 32)
        self.assertEqual(len(set(engine.PAINT_CODES)), 32)

        for state, actual_code in enumerate(engine.PAINT_CODES):
            with self.subTest(state=state):
                expected_code = reference_encode_paint_color({"state": state + 1})
                self.assertEqual(actual_code, expected_code)
                encoded = smooth_paint.encode_paint_color(
                    smooth_paint.PaintNode(state)
                )
                self.assertEqual(encoded, expected_code)
                self.assertEqual(smooth_paint.decode_paint_color(encoded).state, state)

        self.assertEqual(engine.PAINT_CODES[15], "DC")

    def test_selected_sizes_emit_contiguous_enabled_definition_rows(self) -> None:
        for count in mixer.SUPPORTED_PALETTE_STATE_COUNTS:
            with self.subTest(count=count):
                rows = engine.make_portable_mixed_definitions(
                    PRIMARY_RATIOS_B,
                    SECONDARY_RATIOS_B,
                    count,
                ).split(";")
                enabled_rows = rows[: count - 4]
                deleted_rows = rows[count - 4 :]
                self.assertEqual(len(enabled_rows), count - 4)
                self.assertEqual(len(deleted_rows), 6)
                self.assertTrue(all(row.split(",")[2:4] == ["1", "1"] for row in enabled_rows))
                self.assertTrue(all(row.split(",")[2:4] == ["0", "0"] for row in deleted_rows))

    def test_old_ten_enabled_flags_migrate_with_added_six_disabled(self) -> None:
        legacy_enabled = [True, False, True, False, True, True, False, True, False, True]
        settings = AppSettings.from_dict(
            {
                "palette": {
                    "physical_hex": PHYSICAL_HEX,
                    "enabled_states": legacy_enabled,
                    "mix_hex_overrides": [None] * 6,
                    "mix_ratios_b": PRIMARY_RATIOS_B,
                }
            }
        )

        self.assertEqual(len(settings.palette.enabled_states), 32)
        self.assertEqual(settings.palette.enabled_states[:10], legacy_enabled)
        self.assertEqual(settings.palette.enabled_states[10:], [False] * 22)
        self.assertEqual(settings.palette.palette_state_count, 16)
        self.assertEqual(settings.palette.secondary_mix_ratios_b, [67] * 6)
        self.assertEqual(settings.palette.physical_hex, PHYSICAL_HEX)

    def test_new_palette_defaults_to_two_adjustable_ratios_per_pair(self) -> None:
        palette = PaletteSettings()

        self.assertEqual(palette.mix_ratios_b, [33] * 6)
        self.assertEqual(palette.secondary_mix_ratios_b, [67] * 6)
        self.assertEqual(palette.palette_state_count, 16)
        self.assertEqual(palette.enabled_states, [True] * 16 + [False] * 16)

    def test_larger_development_palette_settings_are_safely_truncated(self) -> None:
        enabled = [index % 2 == 0 for index in range(40)]
        palette = PaletteSettings(enabled_states=enabled)

        self.assertEqual(palette.enabled_states, enabled[:16] + [False] * 16)

    def test_24_and_32_palettes_append_without_shifting_old_ids(self) -> None:
        palette_16 = PaletteSettings()
        palette_24 = PaletteSettings(
            palette_state_count=24,
            enabled_states=[True] * 24,
        )
        palette_32 = PaletteSettings(
            palette_state_count=32,
            enabled_states=[True] * 32,
        )
        self.assertEqual(palette_16.enabled_states[:16], palette_24.enabled_states[:16])
        self.assertEqual(palette_24.enabled_states[:24], palette_32.enabled_states[:24])
        names = mixer.palette_state_names(PRIMARY_RATIOS_B, SECONDARY_RATIOS_B)
        self.assertEqual(len(names[:16]), 16)
        self.assertEqual(names[16:22], tuple(
            f"F{left + 1}+F{right + 1} B50%" for left, right in mixer.PAIR_INDICES
        ))

    def test_project_migration_infers_24_or_32_from_saved_enabled_flags(self) -> None:
        for count in (24, 32):
            with self.subTest(count=count):
                settings = AppSettings.from_dict(
                    {"palette": {"enabled_states": [True] * count}}
                )
                self.assertEqual(settings.palette.palette_state_count, count)
                self.assertEqual(
                    settings.palette.enabled_states[:count], [True] * count
                )

    def test_project_settings_use_selected_count_and_generic_pla(self) -> None:
        for count in mixer.SUPPORTED_PALETTE_STATE_COUNTS:
            with self.subTest(count=count):
                palette = PaletteSettings(
                    palette_state_count=count,
                    enabled_states=[True] * count,
                )
                project = json.loads(engine._make_project_settings(palette))
                rows = project["mixed_filament_definitions"].split(";")
                self.assertEqual(len(rows), (count - 4) + 6)
                self.assertEqual(
                    project["filament_settings_id"], ["Generic PLA"] * 4
                )
                for key, expected in (
                    engine.FULL_SPECTRUM_STABLE_CADENCE_SETTINGS.items()
                ):
                    self.assertEqual(project[key], expected)
                for key, expected in (
                    engine.SNAPMAKER_U1_008_TRANSITION_SETTINGS.items()
                ):
                    self.assertEqual(project[key], expected)
                self.assertNotIn("enable_support", project)

    def test_stable_orca_process_settings_do_not_drift_by_material_or_depth(self) -> None:
        expected_profiles = {
            "PLA": "Generic PLA",
            "ABS": "Generic ABS",
            "PETG": "Generic PETG",
        }
        for material, profile in expected_profiles.items():
            for count in mixer.SUPPORTED_PALETTE_STATE_COUNTS:
                with self.subTest(material=material, count=count):
                    palette = PaletteSettings(
                        material=material,
                        palette_state_count=count,
                        enabled_states=[True] * count,
                    )
                    project = json.loads(engine._make_project_settings(palette))
                    self.assertEqual(project["filament_settings_id"], [profile] * 4)
                    self.assertTrue(
                        all(
                            project[key] == expected
                            for key, expected in (
                                engine.FULL_SPECTRUM_STABLE_CADENCE_SETTINGS.items()
                            )
                        )
                    )
                    self.assertTrue(
                        all(
                            project[key] == expected
                            for key, expected in (
                                engine.SNAPMAKER_U1_008_TRANSITION_SETTINGS.items()
                            )
                        )
                    )

    def test_optimizer_metrics_include_the_secondary_six_states(self) -> None:
        palette_hex, _palette_rgb = mixer.build_palette_rgb(
            PHYSICAL_HEX,
            [None] * 6,
            PRIMARY_RATIOS_B,
            SECONDARY_RATIOS_B,
        )
        enabled = [False] * 16
        enabled[10] = True
        target = np.asarray([mixer.hex_to_rgb8(palette_hex[10])])

        result = mixer.optimize_global_mix_ratios(
            target,
            PHYSICAL_HEX,
            initial_ratios_b=PRIMARY_RATIOS_B,
            secondary_ratios_b=SECONDARY_RATIOS_B,
            enabled_states=enabled,
            max_passes=1,
        )

        self.assertEqual(len(result.palette_rgb), 32)
        self.assertEqual(len(result.palette_weight_fractions), 32)
        self.assertAlmostEqual(
            result.weighted_mean_delta_e76,
            0.0,
            delta=1.0e-5,
        )
        self.assertAlmostEqual(result.palette_weight_fractions[10], 1.0)

    def test_optimizer_evaluates_added_24_and_32_state_recipes(self) -> None:
        palette_hex, _palette_rgb = mixer.build_palette_rgb(
            PHYSICAL_HEX,
            [None] * 6,
            PRIMARY_RATIOS_B,
            SECONDARY_RATIOS_B,
        )
        target = np.asarray(
            [
                mixer.hex_to_rgb8(palette_hex[4]),
                mixer.hex_to_rgb8(palette_hex[16]),
                mixer.hex_to_rgb8(palette_hex[23]),
                mixer.hex_to_rgb8(palette_hex[31]),
            ]
        )

        for count in (24, 32):
            with self.subTest(count=count):
                result = mixer.optimize_global_mix_ratios(
                    target,
                    PHYSICAL_HEX,
                    initial_ratios_b=PRIMARY_RATIOS_B,
                    secondary_ratios_b=SECONDARY_RATIOS_B,
                    enabled_states=[True] * count,
                    max_passes=2,
                )

                self.assertEqual(len(result.palette_rgb), 32)
                self.assertEqual(len(result.palette_weight_fractions), 32)
                self.assertLessEqual(
                    result.weighted_mean_delta_e76,
                    result.initial_weighted_mean_delta_e76 + 1.0e-12,
                )
                self.assertAlmostEqual(
                    sum(result.palette_weight_fractions[count:]), 0.0, places=12
                )

    def test_arbitrary_f1_to_f4_colors_use_only_model_independent_names(self) -> None:
        palette_hex, _palette_rgb = mixer.build_palette_rgb(
            PHYSICAL_HEX,
            [None] * 6,
            PRIMARY_RATIOS_B,
            SECONDARY_RATIOS_B,
        )
        names = mixer.palette_state_names(PRIMARY_RATIOS_B, SECONDARY_RATIOS_B)

        self.assertEqual(palette_hex[:4], PHYSICAL_HEX)
        self.assertEqual(names[:4], ("F1", "F2", "F3", "F4"))
        self.assertEqual(len(names), 32)
        self.assertTrue(all(name.startswith("F") for name in names))
        labels = " ".join((*names, *engine.STATE_NAMES)).casefold()
        for fixed_color_name in ("black", "white", "silver", "pink"):
            with self.subTest(fixed_color_name=fixed_color_name):
                self.assertNotIn(fixed_color_name, labels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
