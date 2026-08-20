from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import engine, mixer
from spectrum_mapper.models import (
    AppSettings,
    PaletteSettings,
    SURFACE_SHELL_OUTPUT_ENABLED,
    without_surface_shell_output,
)


PHYSICAL = ["#111111", "#F5F5F5", "#E32636", "#7A4A32"]
SHELL_ONLY_PROJECT_KEYS = (
    "wall_loops",
    "wall_generator",
    "outer_wall_line_width",
    "inner_wall_line_width",
    "support_filament",
    "support_interface_filament",
    "flush_into_infill",
    "flush_into_support",
    "flush_into_objects",
)


class SurfaceShellFailClosedTests(unittest.TestCase):
    def test_production_switch_is_disabled(self) -> None:
        self.assertIs(SURFACE_SHELL_OUTPUT_ENABLED, False)

    def test_old_global_and_part_flags_migrate_off_without_touching_black_ratio(self) -> None:
        output = mixer.black_output_ratio_preset(0)
        restored = AppSettings.from_dict(
            {
                "palette": {
                    "physical_hex": list(PHYSICAL),
                    "output_mix_ratios_b": list(output),
                    "surface_shell_enabled": True,
                },
                "part_palettes": {
                    "coat": {
                        "physical_hex": list(PHYSICAL),
                        "output_mix_ratios_b": list(output),
                        "surface_shell_enabled": True,
                    }
                },
            }
        )

        self.assertFalse(restored.palette.surface_shell_enabled)
        self.assertFalse(restored.part_palettes["coat"].surface_shell_enabled)
        self.assertEqual(restored.palette.output_mix_ratios_b, output)
        self.assertEqual(
            restored.part_palettes["coat"].output_mix_ratios_b, output
        )
        encoded = restored.to_dict()
        self.assertNotIn("surface_shell_enabled", encoded["palette"])
        self.assertNotIn(
            "surface_shell_enabled", encoded["part_palettes"]["coat"]
        )

    def test_setting_remains_strictly_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            PaletteSettings(surface_shell_enabled=1)  # type: ignore[arg-type]
        self.assertFalse(PaletteSettings(surface_shell_enabled=True).surface_shell_enabled)

    def test_direct_grouped_cycle_request_is_byte_exact_ratio_output(self) -> None:
        output = mixer.black_output_ratio_preset(0)
        safe = engine.make_portable_mixed_definitions(
            [33] * 6, [67] * 6, 32, output, False, PHYSICAL
        )
        requested = engine.make_portable_mixed_definitions(
            [33] * 6, [67] * 6, 32, output, True, PHYSICAL
        )

        self.assertEqual(requested.encode("utf-8"), safe.encode("utf-8"))
        self.assertNotIn(",cm1,", requested)
        self.assertEqual(
            [int(row.split(",")[4]) for row in requested.split(";")[:28]],
            output,
        )

    def test_mutated_palette_is_sanitized_without_changing_ratio_project_bytes(self) -> None:
        output = mixer.black_output_ratio_preset(0)
        safe = PaletteSettings(
            palette_state_count=32,
            physical_hex=list(PHYSICAL),
            output_mix_ratios_b=list(output),
        )
        mutated = PaletteSettings(
            palette_state_count=32,
            physical_hex=list(PHYSICAL),
            output_mix_ratios_b=list(output),
        )
        mutated.surface_shell_enabled = True

        safe_bytes = engine._make_project_settings(safe)
        requested_bytes = engine._make_project_settings(mutated)
        self.assertEqual(requested_bytes, safe_bytes)
        project = json.loads(requested_bytes)
        self.assertNotIn(",cm1,", project["mixed_filament_definitions"])
        for key in SHELL_ONLY_PROJECT_KEYS:
            self.assertNotIn(key, project)

    def test_writer_boundary_copy_preserves_caller_and_black_correction(self) -> None:
        output = mixer.black_output_ratio_preset(0)
        safe = PaletteSettings(output_mix_ratios_b=list(output))
        self.assertIs(without_surface_shell_output(safe), safe)

        mutated = PaletteSettings(output_mix_ratios_b=list(output))
        mutated.surface_shell_enabled = True
        sanitized = without_surface_shell_output(mutated)
        self.assertIsNot(sanitized, mutated)
        self.assertTrue(mutated.surface_shell_enabled)
        self.assertFalse(sanitized.surface_shell_enabled)
        self.assertEqual(sanitized.output_mix_ratios_b, output)

    def test_experimental_recipe_math_is_retained_but_not_serialized(self) -> None:
        output = mixer.black_output_ratio_preset(0)
        specs = engine.build_surface_shell_output_specs(
            PHYSICAL, [33] * 6, [67] * 6, output
        )
        self.assertTrue(any(spec.applied for spec in specs))
        self.assertTrue(any(spec.manual_pattern for spec in specs))
        serialized = engine.make_portable_mixed_definitions(
            [33] * 6, [67] * 6, 32, output, True, PHYSICAL
        )
        self.assertNotIn(",cm1,", serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
