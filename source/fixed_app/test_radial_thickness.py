from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.filament_database import srgb_hex_to_lab
from spectrum_mapper.models import (
    PaletteSettings,
    RADIAL_SKIN_MODE_ADAPTIVE,
    RadialSettings,
)
from spectrum_mapper.radial_thickness import (
    RADIAL_THICKNESS_SCHEDULE_SCHEMA,
    RadialThicknessError,
    derive_radial_thickness_schedule,
)


def _palette() -> PaletteSettings:
    return PaletteSettings(
        palette_state_count=16,
        physical_hex=["#111111", "#FFFFFF", "#FF7040", "#FFD040"],
    )


class RadialThicknessScheduleTests(unittest.TestCase):
    def test_target_lstar_schedule_matches_radial_settings_for_all_ui_ranges(self) -> None:
        palette = _palette()
        black_lstar = float(srgb_hex_to_lab(palette.physical_hex[0])[0])
        partner_lstar = float(srgb_hex_to_lab(palette.physical_hex[1])[0])
        for gamma in (0.25, 1.0, 4.0):
            for bands in (4, 5, 6):
                with self.subTest(gamma=gamma, bands=bands):
                    schedule = derive_radial_thickness_schedule(
                        palette,
                        black_slot=0,
                        eligible_state_partners={4: 2, 10: 2},
                        minimum_thickness_mm=0.10,
                        maximum_thickness_mm=0.30,
                        band_count=bands,
                        gamma=gamma,
                        basis="target_lstar",
                    )
                    settings = RadialSettings(
                        skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
                        adaptive_skin_min_thickness_mm=0.10,
                        adaptive_skin_max_thickness_mm=0.30,
                        adaptive_skin_gamma=gamma,
                        adaptive_skin_bands=bands,
                    )
                    for state in schedule.states:
                        expected = settings.skin_thickness_for_lstar(
                            state.target_lstar,
                            black_lstar,
                            partner_lstar,
                        )
                        self.assertAlmostEqual(state.thickness_mm, expected, places=12)

    def test_mix_ratio_respects_pair_orientation_and_quantizes_deterministically(self) -> None:
        palette = PaletteSettings(
            palette_state_count=16,
            physical_hex=["#FFFFFF", "#111111", "#FF7040", "#FFD040"],
        )
        first = derive_radial_thickness_schedule(
            palette,
            black_slot=1,
            eligible_state_partners={4: 1, 10: 1},
            minimum_thickness_mm=0.10,
            maximum_thickness_mm=0.30,
            band_count=5,
            gamma=1.0,
            basis="mix_ratio",
        )
        second = derive_radial_thickness_schedule(
            palette,
            black_slot=1,
            eligible_state_partners={10: 1, 4: 1},
            minimum_thickness_mm=0.10,
            maximum_thickness_mm=0.30,
            band_count=5,
            gamma=1.0,
            basis="mix_ratio",
        )

        self.assertAlmostEqual(first.states[0].partner_fraction, 0.67)
        self.assertAlmostEqual(first.states[1].partner_fraction, 0.33)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertGreater(first.thickness_by_state[4], first.thickness_by_state[10])

    def test_uniform_range_preserves_one_legacy_depth(self) -> None:
        schedule = derive_radial_thickness_schedule(
            _palette(),
            black_slot=0,
            eligible_state_partners={4: 2, 10: 2},
            minimum_thickness_mm=0.15,
            maximum_thickness_mm=0.15,
            band_count=6,
            gamma=4.0,
        )
        self.assertEqual(set(schedule.thickness_by_state.values()), {0.15})
        self.assertEqual(schedule.to_dict()["schema"], RADIAL_THICKNESS_SCHEDULE_SCHEMA)

    def test_display_override_uses_same_target_lstar_as_palette_preview(self) -> None:
        palette = _palette()
        palette.mix_hex_overrides[0] = "#808080"
        schedule = derive_radial_thickness_schedule(
            palette,
            black_slot=0,
            eligible_state_partners={4: 2},
            minimum_thickness_mm=0.10,
            maximum_thickness_mm=0.30,
            band_count=5,
        )
        self.assertAlmostEqual(
            schedule.states[0].target_lstar,
            float(srgb_hex_to_lab("#808080")[0]),
            places=12,
        )

    def test_computed_pure_white_lstar_roundoff_is_clipped(self) -> None:
        palette = _palette()
        palette.mix_hex_overrides[0] = "#FFFFFF"
        schedule = derive_radial_thickness_schedule(
            palette,
            black_slot=0,
            eligible_state_partners={4: 2},
            minimum_thickness_mm=0.10,
            maximum_thickness_mm=0.30,
            band_count=5,
        )
        self.assertEqual(schedule.states[0].target_lstar, 100.0)
        self.assertEqual(schedule.states[0].band_index, 4)

    def test_invalid_or_mismatched_inputs_fail_with_stable_codes(self) -> None:
        cases = (
            ({"band_count": 3}, "invalid_band_count"),
            ({"gamma": 4.01}, "invalid_gamma"),
            ({"eligible_state_partners": {4: 3}}, "eligible_partner_mismatch"),
            ({"target_lstar_by_state": {5: 50.0}}, "target_lstar_state_not_eligible"),
        )
        for extra, code in cases:
            kwargs = {
                "black_slot": 0,
                "eligible_state_partners": {4: 2},
                "minimum_thickness_mm": 0.10,
                "maximum_thickness_mm": 0.30,
                "band_count": 5,
                "gamma": 1.0,
            }
            kwargs.update(extra)
            with self.subTest(code=code):
                with self.assertRaises(RadialThicknessError) as caught:
                    derive_radial_thickness_schedule(_palette(), **kwargs)
                self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
