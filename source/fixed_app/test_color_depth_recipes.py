from __future__ import annotations

import unittest

from spectrum_mapper.color_depth import ColorDepthError
from spectrum_mapper.color_depth_recipes import (
    build_uncalibrated_common_skin_recipes,
    relative_srgb_luminance,
)
from spectrum_mapper.models import PaletteSettings


class ColorDepthRecipePlanTests(unittest.TestCase):
    def palette(self) -> PaletteSettings:
        return PaletteSettings(
            palette_state_count=24,
            physical_hex=["#111111", "#F5F5F5", "#E32636", "#7A4A32"],
        )

    def test_luminance_orders_the_test_spools(self) -> None:
        values = [
            relative_srgb_luminance(value)
            for value in self.palette().physical_hex
        ]
        self.assertGreater(values[1], values[2])
        self.assertGreater(values[2], values[3])
        self.assertGreater(values[3], values[0])

    def test_mixed_target_uses_pair_but_ignores_percentage(self) -> None:
        # Zero-based states 5 and 11 are the two F1/F3 shades (legacy 33/67).
        plan = build_uncalibrated_common_skin_recipes(
            self.palette(), [5, 11], outer_thickness_mm=0.15
        )
        for label in (5, 11):
            recipe = plan.recipes[label]
            self.assertEqual((recipe.outer_physical, recipe.backing_physical), (3, 1))
            self.assertEqual(recipe.outer_thickness_mm, 0.15)
            self.assertTrue(recipe.metadata["legacy_ratio_ignored"])
        self.assertEqual(plan.collapsed_target_groups, ((5, 11),))
        self.assertFalse(plan.metadata["legacy_mix_percentages_used"])
        self.assertEqual(
            plan.metadata["ignored_legacy_ratios_by_target"], {5: 33, 11: 67}
        )

    def test_pure_target_is_unchanged(self) -> None:
        plan = build_uncalibrated_common_skin_recipes(self.palette(), [2])
        recipe = plan.recipes[2]
        self.assertEqual((recipe.outer_physical, recipe.backing_physical), (3, 3))
        self.assertEqual(recipe.metadata["source_kind"], "pure-physical")

    def test_plan_serialization_marks_slice_only_uncalibrated(self) -> None:
        value = build_uncalibrated_common_skin_recipes(
            self.palette(), [0, 5, 11]
        ).to_dict()
        self.assertFalse(value["legacy_mix_percentages_used"])
        self.assertFalse(value["calibrated"])
        self.assertFalse(value["metadata"]["print_allowed"])
        self.assertEqual(value["collapsed_target_groups"], [[5, 11]])

    def test_rejects_ambiguous_outer_material(self) -> None:
        palette = self.palette()
        palette.physical_hex[0] = "#111111"
        palette.physical_hex[1] = "#111111"
        with self.assertRaises(ColorDepthError) as captured:
            build_uncalibrated_common_skin_recipes(palette, [4])
        self.assertEqual(
            captured.exception.code, "provisional_outer_material_ambiguous"
        )

    def test_rejects_out_of_range_target(self) -> None:
        with self.assertRaises(ColorDepthError) as captured:
            build_uncalibrated_common_skin_recipes(self.palette(), [24])
        self.assertEqual(captured.exception.code, "target_label_out_of_range")


if __name__ == "__main__":
    unittest.main()
