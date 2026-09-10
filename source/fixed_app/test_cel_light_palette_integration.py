from __future__ import annotations

import unittest

import numpy as np

from spectrum_mapper.engine import (
    _strong_cel_neutral_band_candidates,
    srgb_to_lab,
    strong_cel_required_physical_rgb,
    strong_cel_required_warm_rgb,
)
from spectrum_mapper.filament_recommender import recommend_basic_filaments
from spectrum_mapper.gui import _merge_required_physical_rgb
from spectrum_mapper.illustration_filter import (
    _LIGHT_DIRECTIONS,
    _style_rgb_with_bands,
)
from spectrum_mapper.mixer import build_palette_rgb, palette_mix_specs
from spectrum_mapper.models import (
    COLOR_MODE_FLAT_FOUR,
    COLOR_MODE_FULL_SPECTRUM,
    PaletteSettings,
    ToneSettings,
)


class CelLightPaletteIntegrationTests(unittest.TestCase):
    """Character-independent regression checks for the cel-print pipeline."""

    _REFERENCE_RAMP = (
        "#080C15",
        "#1F252D",
        "#445B78",
        "#536A8B",
    )

    @staticmethod
    def _hex_rgb(value: str) -> np.ndarray:
        return np.asarray(
            tuple(int(value[index : index + 2], 16) for index in (1, 3, 5)),
            dtype=np.float64,
        ) / 255.0

    @classmethod
    def _generic_material_scene(
        cls,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return cloth, skin, eye and armour samples without character data."""

        reference = np.vstack(
            tuple(cls._hex_rgb(value) for value in cls._REFERENCE_RAMP)
        )
        source = np.vstack(
            (
                np.tile(cls._hex_rgb("#121212"), (110, 1)),
                np.tile(cls._hex_rgb("#1F252D"), (30, 1)),
                np.tile(cls._hex_rgb("#4D291C"), (20, 1)),
                np.tile(cls._hex_rgb("#050505"), (2, 1)),
                np.tile(cls._hex_rgb("#8C0F1A"), (38, 1)),
            )
        )
        styled = source.copy()
        styled[:110] = np.tile(reference, (28, 1))[:110]
        styled[110:140] = np.tile(reference, (8, 1))[:30]
        styled[140:160] = cls._hex_rgb("#BF7A57")
        styled[160:162] = cls._hex_rgb("#050505")
        styled[162:] = cls._hex_rgb("#A61524")
        # Neutral and navy samples are one garment.  The eye is deliberately
        # separate so its tiny black area cannot masquerade as broad cloth.
        group_ids = np.concatenate(
            (
                np.zeros(140, dtype=np.int32),
                np.ones(20, dtype=np.int32),
                np.full(2, 2, dtype=np.int32),
                np.full(38, 3, dtype=np.int32),
            )
        )
        return source, styled, np.ones(len(source)), group_ids

    @staticmethod
    def _reference_tone() -> ToneSettings:
        return ToneSettings(
            illustration_mode="cel_strong",
            illustration_strength=0.78,
            illustration_bands=4,
            illustration_light="front",
            illustration_light_intensity=0.45,
            illustration_light_range=0.30,
        )

    def test_reference_controls_separate_coverage_from_band_energy(self) -> None:
        light = np.asarray(_LIGHT_DIRECTIONS["front"], dtype=np.float64)
        light /= np.linalg.norm(light)
        perpendicular = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
        dot_products = np.linspace(-1.0, 1.0, 81, dtype=np.float64)
        normals = np.asarray(
            [
                dot * light + np.sqrt(1.0 - dot * dot) * perpendicular
                for dot in dot_products
            ]
        )
        source = np.tile(self._hex_rgb("#121212"), (len(normals), 1))

        def render(intensity: float, light_range: float):
            return _style_rgb_with_bands(
                source,
                normals,
                mode="cel_strong",
                amount=0.78,
                bands=4,
                light="front",
                light_intensity=intensity,
                light_range=light_range,
            )

        reference_rgb, reference_bands = render(0.45, 0.30)
        brighter_rgb, brighter_bands = render(0.90, 0.30)
        wider_rgb, wider_bands = render(0.45, 0.75)

        # Intensity changes each non-black band's energy, never its placement.
        np.testing.assert_array_equal(reference_bands, brighter_bands)
        self.assertGreater(float(brighter_rgb.mean()), float(reference_rgb.mean()))
        # Range changes occupancy.  Where a face stays in the same band, that
        # band's RGB is exactly unchanged.
        self.assertTrue(np.any(reference_bands != wider_bands))
        unchanged_band = reference_bands == wider_bands
        self.assertTrue(np.any(unchanged_band))
        np.testing.assert_array_equal(
            reference_rgb[unchanged_band], wider_rgb[unchanged_band]
        )

        observed = np.vstack(
            tuple(reference_rgb[reference_bands == band][0] for band in range(4))
        )
        np.testing.assert_allclose(
            np.rint(observed * 255.0),
            np.asarray(
                (
                    (13, 13, 13),
                    (27, 27, 27),
                    (58, 58, 58),
                    (91, 91, 91),
                )
            ),
            rtol=0.0,
            atol=1.0,
        )

    def test_generic_scene_proposes_blue_black_full_spectrum_and_protects_skin(
        self,
    ) -> None:
        source, styled, areas, group_ids = self._generic_material_scene()
        tone = self._reference_tone()
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            areas,
            tone,
            COLOR_MODE_FULL_SPECTRUM,
            face_group_ids=group_ids,
        )
        self.assertIsNotNone(required)
        assert required is not None
        self.assertEqual(required.shape, (3, 3))
        self.assertGreater(float(required[2, 2]), float(required[2, 0]))
        required = _merge_required_physical_rgb(
            required,
            strong_cel_required_warm_rgb(source, areas, tone),
        )
        recommendation = recommend_basic_filaments(
            styled,
            areas,
            include_mixed_states=True,
            required_physical_rgb=required,
            alternative_count=0,
            max_candidates=None,
        )
        selected_ids = {candidate.id for candidate in recommendation.candidates}
        self.assertEqual(
            selected_ids,
            {
                "neutral_black",
                "neutral_white",
                "cool_blue_gray",
                "skin_medium",
            },
        )

        # The selected spools and their ordinary 32 Full Spectrum recipes can
        # reproduce the measured reference blue-black ladder.  Also ensure the
        # closest four cloth states never borrow the protected skin endpoint.
        selected = list(recommendation.candidates)
        _hexes, palette_rgb = build_palette_rgb(
            [candidate.hex_color for candidate in selected]
        )
        palette_lab = srgb_to_lab(palette_rgb)
        reference_lab = srgb_to_lab(
            np.vstack(tuple(self._hex_rgb(value) for value in self._REFERENCE_RAMP))
        )
        skin_slot = next(
            index for index, candidate in enumerate(selected) if candidate.category == "skin"
        )
        mix_specs = palette_mix_specs()
        closest_states: list[int] = []
        for target in reference_lab:
            delta_e = np.linalg.norm(palette_lab - target, axis=1)
            state = int(np.argmin(delta_e))
            closest_states.append(state)
            self.assertLess(float(delta_e[state]), 6.0)
            endpoints = (
                (state,)
                if state < 4
                else mix_specs[state - 4][:2]
            )
            self.assertNotIn(skin_slot, endpoints)
        self.assertEqual(len(set(closest_states)), 4)

    def test_gate_rejects_eye_skin_armour_and_non_strong_modes(self) -> None:
        tone = self._reference_tone()
        cases = (
            ("eye", "#050505", "#555555", 0.02),
            ("skin", "#4D291C", "#BF7A57", 1.0),
            ("armour", "#0D1730", "#536A8B", 1.0),
        )
        for label, source_hex, styled_hex, selected_fraction in cases:
            source = np.vstack(
                (
                    np.tile(self._hex_rgb(source_hex), (2, 1)),
                    np.tile(self._hex_rgb("#B8B8B8"), (98, 1)),
                )
            )
            styled = source.copy()
            styled[:2] = self._hex_rgb(styled_hex)
            areas = np.ones(100)
            areas[:2] = 50.0 * selected_fraction
            with self.subTest(material=label):
                self.assertIsNone(
                    strong_cel_required_physical_rgb(
                        source,
                        styled,
                        areas,
                        tone,
                        COLOR_MODE_FULL_SPECTRUM,
                        face_group_ids=np.concatenate(
                            (
                                np.zeros(2, dtype=np.int32),
                                np.ones(98, dtype=np.int32),
                            )
                        ),
                    )
                )

        source, styled, areas, group_ids = self._generic_material_scene()
        self.assertIsNone(
            strong_cel_required_physical_rgb(
                source,
                styled,
                areas,
                ToneSettings(illustration_mode="cel"),
                COLOR_MODE_FULL_SPECTRUM,
                face_group_ids=group_ids,
            )
        )

    def test_flat_four_and_unrelated_custom_endpoints_keep_legacy_ramps(self) -> None:
        source, styled, areas, group_ids = self._generic_material_scene()
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            areas,
            self._reference_tone(),
            COLOR_MODE_FLAT_FOUR,
            face_group_ids=group_ids,
        )
        self.assertIsNotNone(required)
        assert required is not None
        np.testing.assert_allclose(
            required,
            np.asarray(((0.055,) * 3, (0.50,) * 3)),
        )

        palette = PaletteSettings(
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            palette_state_count=32,
            physical_hex=["#111111", "#F5F5F5", "#18A858", "#C98B63"],
        )
        original_physical = list(palette.physical_hex)
        _hexes, palette_rgb = build_palette_rgb(palette.physical_hex)
        states = _strong_cel_neutral_band_candidates(
            palette,
            srgb_to_lab(palette_rgb),
            np.ones(len(palette_rgb), dtype=bool),
            self._reference_tone(),
        )
        self.assertGreaterEqual(len(states), 2)
        mix_specs = palette_mix_specs()
        for raw_state in states:
            state = int(raw_state)
            endpoints = (state,) if state < 4 else mix_specs[state - 4][:2]
            self.assertTrue(set(endpoints).issubset({0, 1}))
        self.assertEqual(palette.physical_hex, original_physical)


if __name__ == "__main__":
    unittest.main()
