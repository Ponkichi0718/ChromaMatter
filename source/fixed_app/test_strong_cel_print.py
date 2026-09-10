from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import numpy as np

from spectrum_mapper.engine import (
    _apply_strong_cel_selective_highlight_profile,
    _apply_tone_with_selective_faces,
    _strong_cel_broad_connected_material_mask,
    _fill_strong_cel_garment_mask_holes,
    _grow_strong_cel_selective_plateaus,
    _grow_strong_cel_garment_highlight_regions,
    _refine_strong_cel_source_detail_bands,
    _recover_strong_cel_full_spectrum_warm_recipes,
    _select_strong_cel_base_mid_faces,
    _smooth_strong_cel_band_ids,
    _strong_cel_smoothing_protected_mask,
    strong_cel_required_physical_rgb,
    strong_cel_required_warm_rgb,
    srgb_to_lab,
)
from spectrum_mapper.filament_recommender import recommend_basic_filaments
from spectrum_mapper.gui import _merge_required_physical_rgb
from spectrum_mapper.models import (
    COLOR_MODE_FLAT_FOUR,
    COLOR_MODE_FULL_SPECTRUM,
    ToneSettings,
)


class StrongCelPrintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tone = ToneSettings(illustration_mode="cel_strong")

    def test_flat_reserves_black_mid_and_peak_for_a_large_black_surface(self) -> None:
        source = np.full((100, 3), 0.04, dtype=np.float64)
        styled = np.full((100, 3), 0.06, dtype=np.float64)
        styled[60:90] = 0.50
        styled[90:] = 0.74
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            np.ones(100),
            self.tone,
            COLOR_MODE_FLAT_FOUR,
        )
        self.assertIsNotNone(required)
        assert required is not None
        self.assertEqual(required.shape, (3, 3))
        self.assertLess(float(required[0].mean()), 0.10)
        np.testing.assert_allclose(required[1], (0.50, 0.50, 0.50))
        self.assertGreater(float(required[2].mean()), 0.85)

    def test_flat_does_not_spend_a_slot_on_a_tiny_peak(self) -> None:
        source = np.full((4, 3), 0.04, dtype=np.float64)
        styled = np.asarray(
            ((0.06,) * 3, (0.50,) * 3, (0.50,) * 3, (0.74,) * 3),
            dtype=np.float64,
        )
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            np.asarray((0.80, 0.15, 0.046, 0.004)),
            self.tone,
            COLOR_MODE_FLAT_FOUR,
        )
        self.assertIsNotNone(required)
        assert required is not None
        self.assertEqual(required.shape, (2, 3))

    def test_full_spectrum_uses_black_light_and_cool_cloth_endpoints(self) -> None:
        source = np.full((20, 3), 0.04, dtype=np.float64)
        styled = np.full((20, 3), 0.55, dtype=np.float64)
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            np.ones(20),
            self.tone,
            COLOR_MODE_FULL_SPECTRUM,
        )
        self.assertIsNotNone(required)
        assert required is not None
        self.assertEqual(required.shape, (3, 3))
        self.assertLess(float(required[0].mean()), 0.10)
        self.assertGreater(float(required[1].mean()), 0.85)
        self.assertGreater(float(required[2, 2]), float(required[2, 0]))

    def test_full_spectrum_blue_black_cloth_preserves_its_cool_hue(
        self,
    ) -> None:
        source_color = (
            np.asarray((0x33, 0x38, 0x4A), dtype=np.float64) / 255.0
        )
        source = np.tile(source_color, (20, 1))
        styled = np.full((20, 3), 0.55, dtype=np.float64)
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            np.ones(20),
            self.tone,
            COLOR_MODE_FULL_SPECTRUM,
        )
        self.assertIsNotNone(required)
        assert required is not None
        self.assertEqual(required.shape, (3, 3))
        self.assertLess(float(required[0].mean()), 0.10)
        self.assertGreater(float(required[1].mean()), 0.85)
        self.assertGreater(float(required[2, 2]), float(required[2, 0]))
        self.assertGreater(float(required[2, 2]), float(required[2, 1]))

    def test_full_spectrum_muted_violet_cloth_preserves_violet_hue(
        self,
    ) -> None:
        source_color = (
            np.asarray((0x20, 0x18, 0x2A), dtype=np.float64) / 255.0
        )
        source = np.tile(source_color, (20, 1))
        styled = np.full((20, 3), 0.55, dtype=np.float64)
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            np.ones(20),
            self.tone,
            COLOR_MODE_FULL_SPECTRUM,
        )
        self.assertIsNotNone(required)
        assert required is not None
        self.assertGreater(float(required[2, 2]), float(required[2, 0]))
        self.assertGreater(float(required[2, 0]), float(required[2, 1]))
        recommendation = recommend_basic_filaments(
            styled,
            np.ones(20),
            include_mixed_states=True,
            required_physical_rgb=required,
            alternative_count=0,
            max_candidates=None,
        )
        self.assertIn(
            "cool_violet_gray",
            {candidate.id for candidate in recommendation.candidates},
        )

    def test_cool_endpoint_is_not_reserved_for_a_small_black_eye(self) -> None:
        source = np.vstack(
            (
                np.full((2, 3), 0.04),
                np.full((98, 3), 0.72),
            )
        )
        styled = source.copy()
        styled[:2] = 0.55
        self.assertIsNone(
            strong_cel_required_physical_rgb(
                source,
                styled,
                np.ones(100),
                self.tone,
                COLOR_MODE_FULL_SPECTRUM,
            )
        )

    def test_disconnected_small_dark_parts_do_not_form_a_blue_grey_material(
        self,
    ) -> None:
        source = np.vstack(
            (
                np.full((24, 3), 0.04),
                np.full((76, 3), 0.72),
            )
        )
        styled = source.copy()
        styled[:24] = 0.55
        group_ids = np.concatenate(
            (
                np.repeat(np.arange(4, dtype=np.int32), 6),
                np.full(76, 4, dtype=np.int32),
            )
        )
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            np.ones(100),
            self.tone,
            COLOR_MODE_FULL_SPECTRUM,
            face_group_ids=group_ids,
        )
        self.assertIsNotNone(required)
        assert required is not None
        # The legacy black/light safeguard may still apply to 24% total dark
        # detail, but no one six-percent part may force a cool physical spool.
        self.assertEqual(required.shape, (2, 3))

    def test_cool_ramp_keeps_a_disconnected_small_black_detail_out(self) -> None:
        garment = np.asarray(
            (True, True, True, True, True, True, True, True, False),
            dtype=bool,
        )
        areas = np.asarray((10, 10, 10, 10, 10, 10, 2, 2, 36), dtype=float)
        neighbors = np.asarray(
            (
                (1, 2, -1),
                (0, 2, -1),
                (0, 1, 3),
                (2, 4, 5),
                (3, 5, -1),
                (3, 4, -1),
                (7, -1, -1),
                (6, -1, -1),
                (-1, -1, -1),
            ),
            dtype=np.int32,
        )

        result = _strong_cel_broad_connected_material_mask(
            garment,
            areas,
            neighbors,
        )

        np.testing.assert_array_equal(
            result,
            np.asarray(
                (True, True, True, True, True, True, False, False, False),
                dtype=bool,
            ),
        )

    def test_cool_endpoint_is_not_reserved_for_saturated_coloured_armour(
        self,
    ) -> None:
        source = np.tile(
            np.asarray((0x0D, 0x17, 0x30), dtype=np.float64) / 255.0,
            (20, 1),
        )
        styled = np.full((20, 3), 0.55, dtype=np.float64)
        self.assertIsNone(
            strong_cel_required_physical_rgb(
                source,
                styled,
                np.ones(20),
                self.tone,
                COLOR_MODE_FULL_SPECTRUM,
            )
        )

    def test_cool_endpoint_is_not_reserved_below_strong_style_amount(
        self,
    ) -> None:
        source = np.full((20, 3), 0.04, dtype=np.float64)
        styled = np.full((20, 3), 0.55, dtype=np.float64)
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            np.ones(20),
            ToneSettings(
                illustration_mode="cel_strong",
                illustration_strength=0.40,
            ),
            COLOR_MODE_FULL_SPECTRUM,
        )
        self.assertIsNotNone(required)
        assert required is not None
        self.assertEqual(required.shape, (2, 3))

    def test_dark_skin_does_not_trigger_neutral_filament_reservation(self) -> None:
        source = np.tile((0.30, 0.12, 0.08), (20, 1))
        styled = np.tile((0.70, 0.42, 0.30), (20, 1))
        self.assertIsNone(
            strong_cel_required_physical_rgb(
                source,
                styled,
                np.ones(20),
                self.tone,
                COLOR_MODE_FLAT_FOUR,
            )
        )

    def test_existing_white_detail_does_not_duplicate_peak_reservation(self) -> None:
        required = np.asarray(
            ((0.055,) * 3, (0.50,) * 3, (0.94,) * 3),
            dtype=np.float64,
        )
        merged = _merge_required_physical_rgb(
            required,
            np.asarray((0.97, 0.96, 0.95)),
        )
        self.assertIsNotNone(merged)
        assert merged is not None
        self.assertEqual(merged.shape, (3, 3))

    def test_flat_auto_proposal_keeps_three_neutral_bands_and_skin(self) -> None:
        source = np.vstack(
            (
                np.full((90, 3), 0.04),
                np.tile((0.30, 0.18, 0.12), (10, 1)),
            )
        )
        styled = source.copy()
        styled[55:80] = 0.50
        styled[80:90] = 0.74
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            np.ones(100),
            self.tone,
            COLOR_MODE_FLAT_FOUR,
        )
        required = _merge_required_physical_rgb(
            required,
            strong_cel_required_warm_rgb(source, np.ones(100), self.tone),
        )
        result = recommend_basic_filaments(
            styled,
            np.ones(100),
            include_mixed_states=False,
            required_physical_rgb=required,
            alternative_count=0,
            max_candidates=None,
        )
        selected_ids = {candidate.id for candidate in result.candidates}
        self.assertEqual(
            selected_ids,
            {
                "neutral_black",
                "neutral_gray",
                "neutral_white",
                "skin_medium",
            },
        )

    def test_full_auto_proposal_keeps_black_light_skin_and_cool_material(
        self,
    ) -> None:
        source = np.vstack(
            (
                np.full((90, 3), 0.04),
                np.tile((0.30, 0.18, 0.12), (10, 1)),
            )
        )
        styled = source.copy()
        styled[55:80] = 0.50
        styled[80:90] = 0.74
        areas = np.ones(100)
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            areas,
            self.tone,
            COLOR_MODE_FULL_SPECTRUM,
            face_group_ids=np.zeros(100, dtype=np.int32),
        )
        required = _merge_required_physical_rgb(
            required,
            strong_cel_required_warm_rgb(source, areas, self.tone),
        )
        result = recommend_basic_filaments(
            styled,
            areas,
            include_mixed_states=True,
            required_physical_rgb=required,
            alternative_count=0,
            max_candidates=None,
        )

        self.assertEqual(
            {candidate.id for candidate in result.candidates},
            {
                "neutral_black",
                "neutral_white",
                "cool_blue_gray",
                "skin_medium",
            },
        )

    def test_smoothing_protects_a_coherent_highlight_but_not_a_speck(self) -> None:
        source = np.full((4, 3), 0.04, dtype=np.float64)
        areas = np.full(4, 0.2, dtype=np.float64)
        neighbors = np.asarray(
            ((1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2)),
            dtype=np.int32,
        )
        coherent = np.full((4, 3), 0.05, dtype=np.float64)
        coherent[:3] = 0.55
        protected = _strong_cel_smoothing_protected_mask(
            source, coherent, areas, neighbors, self.tone
        )
        np.testing.assert_array_equal(
            protected, np.asarray((True, True, True, False))
        )

        speck = np.full((4, 3), 0.05, dtype=np.float64)
        speck[0] = 0.55
        protected_speck = _strong_cel_smoothing_protected_mask(
            source, speck, areas, neighbors, self.tone
        )
        np.testing.assert_array_equal(protected_speck, np.zeros(4, dtype=bool))

    def test_light_band_cleanup_removes_only_a_small_isolated_triangle(self) -> None:
        bands = np.asarray((3, 0, 0, 0), dtype=np.uint8)
        garment = np.ones(4, dtype=bool)
        neighbors = np.asarray(
            ((1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2)),
            dtype=np.int32,
        )
        small = _smooth_strong_cel_band_ids(
            bands,
            garment,
            np.asarray((0.2, 0.2, 0.2, 0.2)),
            neighbors,
        )
        np.testing.assert_array_equal(small, np.zeros(4, dtype=np.uint8))

        deliberate_large_highlight = _smooth_strong_cel_band_ids(
            bands,
            garment,
            np.asarray((2.0, 0.2, 0.2, 0.2)),
            neighbors,
        )
        self.assertEqual(int(deliberate_large_highlight[0]), 3)

    @staticmethod
    def _chain_neighbors(count: int) -> np.ndarray:
        result = np.full((count, 3), -1, dtype=np.int32)
        for face_id in range(count):
            if face_id:
                result[face_id, 0] = face_id - 1
            if face_id + 1 < count:
                result[face_id, 1] = face_id + 1
        return result

    def test_source_detail_moves_only_coherent_wrinkles_one_band(self) -> None:
        count = 10
        bands = np.full(count, 2, dtype=np.uint8)
        source = np.full((count, 3), 0.18, dtype=np.float64)
        source[:2] = 0.05
        source[-2:] = 0.34
        result = _refine_strong_cel_source_detail_bands(
            bands,
            np.ones(count, dtype=bool),
            source,
            np.ones(count, dtype=np.float64),
            self._chain_neighbors(count),
            band_count=4,
            detail_strength=1.0,
        )
        np.testing.assert_array_equal(result[:2], np.full(2, 1, dtype=np.uint8))
        np.testing.assert_array_equal(result[2:-2], np.full(6, 2, dtype=np.uint8))
        np.testing.assert_array_equal(result[-2:], np.full(2, 3, dtype=np.uint8))

    def test_source_detail_rejects_single_triangle_noise(self) -> None:
        count = 10
        bands = np.full(count, 2, dtype=np.uint8)
        source = np.full((count, 3), 0.18, dtype=np.float64)
        source[0] = 0.03
        source[-1] = 0.38
        result = _refine_strong_cel_source_detail_bands(
            bands,
            np.ones(count, dtype=bool),
            source,
            np.ones(count, dtype=np.float64),
            self._chain_neighbors(count),
            band_count=4,
            detail_strength=1.0,
        )
        np.testing.assert_array_equal(result, bands)

    def test_source_detail_excludes_warm_skin_even_from_a_wide_mask(self) -> None:
        count = 12
        bands = np.full(count, 2, dtype=np.uint8)
        source = np.full((count, 3), 0.18, dtype=np.float64)
        source[:2] = np.asarray((0.23, 0.13, 0.075))
        source[-2:] = 0.36
        result = _refine_strong_cel_source_detail_bands(
            bands,
            np.ones(count, dtype=bool),
            source,
            np.ones(count, dtype=np.float64),
            self._chain_neighbors(count),
            band_count=4,
            detail_strength=1.0,
        )
        np.testing.assert_array_equal(result[:2], bands[:2])

    def test_source_detail_default_and_missing_topology_are_exact_noops(self) -> None:
        bands = np.asarray((0, 1, 2, 3, 2, 1), dtype=np.uint8)
        source = np.tile((0.12, 0.12, 0.12), (len(bands), 1))
        garment = np.ones(len(bands), dtype=bool)
        areas = np.ones(len(bands), dtype=np.float64)
        neighbors = self._chain_neighbors(len(bands))
        default = _refine_strong_cel_source_detail_bands(
            bands,
            garment,
            source,
            areas,
            neighbors,
            band_count=4,
            detail_strength=0.0,
        )
        no_topology = _refine_strong_cel_source_detail_bands(
            bands,
            garment,
            source,
            areas,
            None,
            band_count=4,
            detail_strength=1.0,
        )
        np.testing.assert_array_equal(default, bands)
        np.testing.assert_array_equal(no_topology, bands)
        self.assertFalse(np.shares_memory(default, bands))

    def test_source_detail_never_exceeds_requested_band_range(self) -> None:
        count = 10
        source = np.full((count, 3), 0.18, dtype=np.float64)
        source[:2] = 0.03
        source[-2:] = 0.38
        for base in (0, 3):
            with self.subTest(base=base):
                bands = np.full(count, base, dtype=np.uint8)
                result = _refine_strong_cel_source_detail_bands(
                    bands,
                    np.ones(count, dtype=bool),
                    source,
                    np.ones(count, dtype=np.float64),
                    self._chain_neighbors(count),
                    band_count=4,
                    detail_strength=1.0,
                )
                self.assertGreaterEqual(int(result.min()), 0)
                self.assertLessEqual(int(result.max()), 3)

    def test_full_spectrum_detail_recovers_same_lightness_warm_recipe(self) -> None:
        palette_rgb = np.full((16, 3), 0.50, dtype=np.float64)
        palette_rgb[0] = (0.05, 0.05, 0.05)
        palette_rgb[1] = (0.95, 0.95, 0.95)
        palette_rgb[2] = (0.12, 0.20, 0.38)
        palette_rgb[3] = (0.72, 0.42, 0.25)
        palette_rgb[4] = (0.25, 0.25, 0.25)
        palette_rgb[5] = (0.38, 0.20, 0.11)
        source = np.asarray(
            (
                (0.23, 0.13, 0.075),
                (0.08, 0.08, 0.09),
                (0.23, 0.13, 0.075),
            ),
            dtype=np.float64,
        )
        indices = np.asarray((4, 4, 1), dtype=np.int8)
        result, changed = _recover_strong_cel_full_spectrum_warm_recipes(
            indices,
            source,
            srgb_to_lab(source),
            srgb_to_lab(palette_rgb),
            np.ones(16, dtype=bool),
            detail_strength=1.0,
        )
        self.assertEqual(int(result[0]), 5)
        # Neutral/cool cloth is excluded by source hue, while the bright warm
        # face has no equivalent-L* warm recipe and keeps its highlight state.
        self.assertEqual(int(result[1]), 4)
        self.assertEqual(int(result[2]), 1)
        self.assertEqual(changed, 1)

    def test_full_spectrum_warm_recovery_is_exactly_off_by_default(self) -> None:
        palette_rgb = np.full((16, 3), 0.50, dtype=np.float64)
        palette_rgb[4] = (0.25, 0.25, 0.25)
        palette_rgb[5] = (0.38, 0.20, 0.11)
        source = np.asarray(((0.23, 0.13, 0.075),), dtype=np.float64)
        indices = np.asarray((4,), dtype=np.int8)
        result, changed = _recover_strong_cel_full_spectrum_warm_recipes(
            indices,
            source,
            srgb_to_lab(source),
            srgb_to_lab(palette_rgb),
            np.ones(16, dtype=bool),
            detail_strength=0.0,
        )
        np.testing.assert_array_equal(result, indices)
        self.assertEqual(changed, 0)

    @staticmethod
    def _selective_fixture(
        *,
        count: int = 100,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
    ]:
        source = np.tile((0.08, 0.085, 0.095), (count, 1)).astype(
            np.float64
        )
        ordinary = np.full((count, 3), 0.48, dtype=np.float64)
        bands = np.zeros(count, dtype=np.uint8)
        bands[:2] = 3
        bands[2:8] = 2
        bands[8:60] = 1
        areas = np.ones(count, dtype=np.float64)
        neighbors = StrongCelPrintTests._chain_neighbors(count)
        vertices = np.zeros((3, 3), dtype=np.float64)
        faces = np.zeros((count, 3), dtype=np.int32)
        scores = np.repeat(
            np.linspace(1.0, 0.02, count // 2), 2
        ).astype(np.float64)
        return source, ordinary, bands, areas, neighbors, vertices, faces, scores

    def test_selective_profile_caps_all_lifted_bands_at_eight_percent(
        self,
    ) -> None:
        (
            source,
            ordinary,
            bands,
            areas,
            neighbors,
            vertices,
            faces,
            scores,
        ) = self._selective_fixture()
        normals = np.tile((0.0, 0.0, 1.0), (len(bands), 1))
        tone = ToneSettings(
            illustration_mode="cel_strong",
            illustration_bands=4,
            illustration_selective_highlight_fraction=0.08,
        )
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            return_value=(scores, normals),
        ):
            output, result_bands, applied = (
                _apply_strong_cel_selective_highlight_profile(
                    source,
                    ordinary,
                    bands,
                    areas,
                    neighbors,
                    vertices,
                    faces,
                    tone,
                )
            )
        lifted_area = float(areas[result_bands >= 2].sum())
        peak_area = float(areas[result_bands == 3].sum())
        self.assertEqual(lifted_area, 8.0)
        self.assertEqual(peak_area, 2.0)
        self.assertLessEqual(lifted_area / float(areas.sum()), 0.08)
        self.assertLessEqual(peak_area / float(areas.sum()), 0.03)
        self.assertEqual(int(np.count_nonzero(result_bands == 1)), 40)
        self.assertEqual(int(np.count_nonzero(result_bands == 0)), 52)
        self.assertLess(float(output[result_bands <= 1].mean()), 0.10)
        self.assertLessEqual(len(np.unique(result_bands)), 4)
        self.assertTrue(applied)

    def test_selective_frontier_growth_matches_full_edge_reference(self) -> None:
        def reference(
            seed: np.ndarray,
            areas: np.ndarray,
            scores: np.ndarray,
            edge_rows: np.ndarray,
            edge_cols: np.ndarray,
            target: float,
        ) -> tuple[np.ndarray, float]:
            selected = seed.copy()
            blocked = np.zeros(len(seed), dtype=bool)
            selected_area = float(areas[selected].sum())
            for _pass in range(len(seed)):
                touches = np.zeros(len(seed), dtype=bool)
                boundary = (~selected[edge_rows]) & selected[edge_cols]
                np.logical_or.at(touches, edge_rows[boundary], True)
                candidates = np.flatnonzero(
                    touches & ~selected & ~blocked
                )
                if not len(candidates):
                    break
                score = int(np.max(scores[candidates]))
                group = candidates[scores[candidates] == score]
                group_area = float(areas[group].sum())
                if selected_area + group_area <= target + 1.0e-12:
                    selected[group] = True
                    selected_area += group_area
                else:
                    blocked[group] = True
            return selected, selected_area

        rng = np.random.default_rng(20260831)
        component_count = 80
        undirected = {(index, index + 1) for index in range(component_count - 1)}
        while len(undirected) < 180:
            left, right = sorted(
                rng.choice(component_count, size=2, replace=False).tolist()
            )
            undirected.add((left, right))
        pairs = np.asarray(sorted(undirected), dtype=np.int32)
        edge_rows = np.concatenate((pairs[:, 0], pairs[:, 1]))
        edge_cols = np.concatenate((pairs[:, 1], pairs[:, 0]))
        for case in range(40):
            with self.subTest(case=case):
                areas = rng.uniform(0.05, 2.0, size=component_count)
                scores = rng.integers(0, 12, size=component_count, dtype=np.int64)
                seed = np.zeros(component_count, dtype=bool)
                seed[rng.choice(component_count, size=3, replace=False)] = True
                target = float(areas[seed].sum() + rng.uniform(2.0, 25.0))
                expected, expected_area = reference(
                    seed,
                    areas,
                    scores,
                    edge_rows,
                    edge_cols,
                    target,
                )
                actual, actual_area = _grow_strong_cel_selective_plateaus(
                    seed,
                    areas,
                    scores,
                    edge_rows,
                    edge_cols,
                    target,
                )
                np.testing.assert_array_equal(actual, expected)
                self.assertAlmostEqual(actual_area, expected_area, places=12)

    def test_selective_base_mid_matches_full_face_scan_reference(self) -> None:
        def reference(
            remaining: np.ndarray,
            scores: np.ndarray,
            areas: np.ndarray,
            budget: float,
        ) -> tuple[np.ndarray, float]:
            selected = np.zeros(len(remaining), dtype=bool)
            selected_area = 0.0
            for score in np.unique(scores[remaining])[::-1]:
                group = remaining & (scores == score)
                group_area = float(areas[group].sum())
                if selected_area + group_area > budget + 1.0e-12:
                    break
                selected[group] = True
                selected_area += group_area
            return selected, selected_area

        rng = np.random.default_rng(20260831)
        for case in range(80):
            with self.subTest(case=case):
                face_count = int(rng.integers(1, 500))
                remaining = rng.random(face_count) >= 0.2
                scores = rng.integers(
                    0,
                    max(2, face_count // 3),
                    size=face_count,
                    dtype=np.int64,
                )
                areas = rng.uniform(0.0, 3.0, size=face_count)
                budget = float(areas[remaining].sum() * rng.random())
                expected, expected_area = reference(
                    remaining,
                    scores,
                    areas,
                    budget,
                )
                actual, actual_area = _select_strong_cel_base_mid_faces(
                    remaining,
                    scores,
                    areas,
                    budget,
                )
                np.testing.assert_array_equal(actual, expected)
                self.assertEqual(actual_area, expected_area)

    def test_selective_base_mid_stops_before_oversized_tie_group(self) -> None:
        remaining = np.ones(7, dtype=bool)
        scores = np.asarray((9, 9, 8, 8, 8, 7, 6), dtype=np.int64)
        areas = np.asarray((1.0, 1.0, 2.0, 2.0, 2.0, 0.1, 0.1))
        selected, selected_area = _select_strong_cel_base_mid_faces(
            remaining,
            scores,
            areas,
            4.0,
        )
        np.testing.assert_array_equal(
            selected,
            np.asarray((True, True, False, False, False, False, False)),
        )
        self.assertEqual(selected_area, 2.0)

    def test_selective_base_mid_handles_many_distinct_scores(self) -> None:
        face_count = 100_000
        remaining = np.ones(face_count, dtype=bool)
        scores = np.arange(face_count, dtype=np.int64)
        areas = np.ones(face_count, dtype=np.float64)
        selected, selected_area = _select_strong_cel_base_mid_faces(
            remaining,
            scores,
            areas,
            40_000.0,
        )
        self.assertEqual(int(np.count_nonzero(selected)), 40_000)
        self.assertTrue(np.all(selected[-40_000:]))
        self.assertFalse(np.any(selected[:-40_000]))
        self.assertEqual(selected_area, 40_000.0)

    def test_selective_profile_accepts_exact_precomputed_geometry(self) -> None:
        fixture = self._selective_fixture()
        scores = fixture[-1]
        normals = np.tile((0.0, 0.0, 1.0), (len(scores), 1))
        tone = ToneSettings(
            illustration_mode="cel_strong",
            illustration_bands=4,
            illustration_selective_highlight_fraction=0.08,
        )
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            return_value=(scores, normals),
        ):
            expected = _apply_strong_cel_selective_highlight_profile(
                *fixture[:-1],
                tone,
            )
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            side_effect=AssertionError("cached geometry was not used"),
        ):
            actual = _apply_strong_cel_selective_highlight_profile(
                *fixture[:-1],
                tone,
                _precomputed_light_scores=scores,
                _precomputed_face_normals=normals,
            )
        np.testing.assert_array_equal(actual[0], expected[0])
        np.testing.assert_array_equal(actual[1], expected[1])
        self.assertEqual(actual[2], expected[2])

    def test_selective_tone_pipeline_reuses_first_normal_pass(self) -> None:
        count = 100
        colors = np.tile((0.08, 0.085, 0.095), (3, 1)).astype(
            np.float64
        )
        vertices = np.zeros((3, 3), dtype=np.float64)
        faces = np.zeros((count, 3), dtype=np.int32)
        tone = ToneSettings(
            illustration_mode="cel_strong",
            illustration_bands=4,
            illustration_selective_highlight_fraction=0.08,
        )
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry"
        ) as standalone_geometry:
            result = _apply_tone_with_selective_faces(
                colors,
                tone,
                vertices_unit=vertices,
                faces=faces,
                areas_unit=np.ones(count, dtype=np.float64),
                neighbors=self._chain_neighbors(count),
                face_part_ids=None,
                height_mm=1.0,
            )
        standalone_geometry.assert_not_called()
        self.assertEqual(result[0].shape, colors.shape)
        self.assertEqual(result[1].shape, (count, 3))
        self.assertEqual(result[2].shape, (count,))

    def test_selective_profile_never_splits_an_oversized_peak_plateau(
        self,
    ) -> None:
        fixture = list(self._selective_fixture())
        scores = fixture[-1]
        scores[:4] = 1.0
        fixture[-1] = scores
        normals = np.tile((0.0, 0.0, 1.0), (len(scores), 1))
        tone = ToneSettings(
            illustration_mode="cel_strong",
            illustration_bands=4,
            illustration_selective_highlight_fraction=0.08,
        )
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            return_value=(scores, normals),
        ):
            output, result_bands, applied = (
                _apply_strong_cel_selective_highlight_profile(
                    *fixture[:-1], tone
                )
            )
        np.testing.assert_array_equal(output, fixture[1])
        np.testing.assert_array_equal(result_bands, fixture[2])
        self.assertFalse(applied)

    def test_selective_profile_rejects_single_face_peak_and_bad_topology(
        self,
    ) -> None:
        fixture = list(self._selective_fixture())
        scores = np.linspace(1.0, 0.0, len(fixture[2]))
        fixture[-1] = scores
        fixture[2][1] = 2
        isolated_neighbors = fixture[4].copy()
        isolated_neighbors[0] = -1
        isolated_neighbors[1, 0] = -1
        fixture[4] = isolated_neighbors
        normals = np.tile((0.0, 0.0, 1.0), (len(scores), 1))
        tone = ToneSettings(
            illustration_mode="cel_strong",
            illustration_bands=4,
            illustration_selective_highlight_fraction=0.08,
        )
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            return_value=(scores, normals),
        ):
            singleton_output, singleton_bands, singleton_applied = (
                _apply_strong_cel_selective_highlight_profile(
                    *fixture[:-1], tone
                )
            )
        np.testing.assert_array_equal(singleton_output, fixture[1])
        np.testing.assert_array_equal(singleton_bands, fixture[2])
        self.assertFalse(singleton_applied)

        bad_neighbors = fixture[4].copy()
        bad_neighbors[2, 0] = 0
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            return_value=(fixture[-1], normals),
        ):
            bad_output, bad_bands, bad_applied = (
                _apply_strong_cel_selective_highlight_profile(
                    fixture[0],
                    fixture[1],
                    fixture[2],
                    fixture[3],
                    bad_neighbors,
                    fixture[5],
                    fixture[6],
                    tone,
                )
            )
        np.testing.assert_array_equal(bad_output, fixture[1])
        np.testing.assert_array_equal(bad_bands, fixture[2])
        self.assertFalse(bad_applied)

    def test_selective_profile_excludes_warm_skin_from_highlights(self) -> None:
        fixture = list(self._selective_fixture())
        fixture[0][:2] = (0.23, 0.13, 0.075)
        scores = fixture[-1]
        normals = np.tile((0.0, 0.0, 1.0), (len(scores), 1))
        tone = ToneSettings(
            illustration_mode="cel_strong",
            illustration_bands=4,
            illustration_selective_highlight_fraction=0.08,
        )
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            return_value=(scores, normals),
        ):
            output, result_bands, applied = (
                _apply_strong_cel_selective_highlight_profile(
                    *fixture[:-1], tone
                )
            )
        # The warm local maximum cannot seed a peak, so the optional profile
        # fails closed rather than selecting a lower arbitrary region.
        np.testing.assert_array_equal(output, fixture[1])
        np.testing.assert_array_equal(result_bands, fixture[2])
        self.assertFalse(applied)

    def test_selective_profile_darkens_coherent_geometry_crease_one_band(
        self,
    ) -> None:
        fixture = list(self._selective_fixture())
        scores = fixture[-1]
        neighbors = fixture[4].copy()
        neighbors[3] = (2, 4, 5)
        neighbors[4] = (3, 5, -1)
        neighbors[5] = (3, 4, 6)
        fixture[4] = neighbors
        smooth_normals = np.tile((0.0, 0.0, 1.0), (len(scores), 1))
        crease_normals = smooth_normals.copy()
        crease_normals[4:6] = (0.0, 1.0, 0.0)
        tone = ToneSettings(
            illustration_mode="cel_strong",
            illustration_bands=4,
            illustration_selective_highlight_fraction=0.08,
        )
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            return_value=(scores, smooth_normals),
        ):
            _smooth_output, smooth_bands, smooth_applied = (
                _apply_strong_cel_selective_highlight_profile(
                    *fixture[:-1], tone
                )
            )
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            return_value=(scores, crease_normals),
        ):
            crease_output, crease_bands, crease_applied = (
                _apply_strong_cel_selective_highlight_profile(
                    *fixture[:-1], tone
                )
            )
        self.assertTrue(smooth_applied)
        self.assertTrue(crease_applied)
        for face_id in (4, 5):
            self.assertEqual(
                int(crease_bands[face_id]),
                max(int(smooth_bands[face_id]) - 1, 0),
            )
        self.assertLessEqual(
            float(fixture[3][crease_bands >= 2].sum()),
            0.08 * float(fixture[3].sum()),
        )
        self.assertTrue(np.isfinite(crease_output).all())

    def test_selective_contour_policies_add_only_requested_evidence(self) -> None:
        fixture = list(self._selective_fixture())
        scores = fixture[-1]
        neighbors = fixture[4].copy()
        for first in (14, 24, 34):
            previous = first - 1
            second = first + 1
            following = first + 2
            neighbors[previous] = (previous - 1, first, second)
            neighbors[first] = (previous, second, -1)
            neighbors[second] = (previous, first, following)
        fixture[4] = neighbors

        normals = np.tile((0.0, 0.0, 1.0), (len(scores), 1))
        shallow = math.radians(2.5)
        normals[13] = (0.0, -math.sin(shallow), math.cos(shallow))
        normals[14:16] = (
            0.0,
            math.sin(shallow),
            math.cos(shallow),
        )
        sharp = math.radians(25.0)
        normals[24:26] = (math.sin(sharp), 0.0, math.cos(sharp))
        fold = math.radians(15.0)
        normals[34:36] = (math.sin(fold), 0.0, math.cos(fold))
        fixture[0][34:36] = (0.01, 0.01, 0.01)

        results: dict[str, tuple[np.ndarray, np.ndarray, bool]] = {}
        for policy in ("outer", "outer_crease", "outer_crease_fold"):
            tone = ToneSettings(
                illustration_mode="cel_strong",
                illustration_bands=4,
                illustration_selective_highlight_fraction=0.08,
                illustration_contour_policy=policy,
            )
            with patch(
                "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
                return_value=(scores, normals),
            ):
                results[policy] = (
                    _apply_strong_cel_selective_highlight_profile(
                        *fixture[:-1], tone
                    )
                )

        outer_bands = results["outer"][1]
        crease_bands = results["outer_crease"][1]
        fold_bands = results["outer_crease_fold"][1]
        self.assertTrue(all(result[2] for result in results.values()))
        np.testing.assert_array_equal(
            crease_bands[14:16], outer_bands[14:16]
        )
        np.testing.assert_array_equal(
            fold_bands[14:16], outer_bands[14:16]
        )
        np.testing.assert_array_equal(
            crease_bands[24:26],
            np.maximum(outer_bands[24:26].astype(np.int16) - 1, 0),
        )
        np.testing.assert_array_equal(
            fold_bands[24:26], crease_bands[24:26]
        )
        np.testing.assert_array_equal(
            fold_bands[34:36],
            np.maximum(crease_bands[34:36].astype(np.int16) - 1, 0),
        )
        self.assertFalse(
            np.array_equal(outer_bands, crease_bands)
        )
        self.assertFalse(
            np.array_equal(crease_bands, fold_bands)
        )

        default_tone = ToneSettings(
            illustration_mode="cel_strong",
            illustration_bands=4,
            illustration_selective_highlight_fraction=0.08,
        )
        del default_tone.illustration_contour_policy
        with patch(
            "spectrum_mapper.illustration_filter.strong_cel_face_light_geometry",
            return_value=(scores, normals),
        ):
            legacy_output, legacy_bands, legacy_applied = (
                _apply_strong_cel_selective_highlight_profile(
                    *fixture[:-1], default_tone
                )
            )
        np.testing.assert_array_equal(
            legacy_output, results["outer_crease_fold"][0]
        )
        np.testing.assert_array_equal(
            legacy_bands, results["outer_crease_fold"][1]
        )
        self.assertEqual(legacy_applied, results["outer_crease_fold"][2])

    def test_selective_contour_invalid_mutation_fails_closed(self) -> None:
        fixture = self._selective_fixture()
        tone = ToneSettings(
            illustration_mode="cel_strong",
            illustration_selective_highlight_fraction=0.08,
        )
        tone.illustration_contour_policy = "unknown"
        output, result_bands, applied = (
            _apply_strong_cel_selective_highlight_profile(
                *fixture[:-1], tone
            )
        )
        np.testing.assert_array_equal(output, fixture[1])
        np.testing.assert_array_equal(result_bands, fixture[2])
        self.assertFalse(applied)

    def test_selective_profile_zero_is_exact_for_detail_zero_and_one(self) -> None:
        fixture = self._selective_fixture()
        for detail in (0.0, 1.0):
            with self.subTest(detail=detail):
                tone = ToneSettings(
                    illustration_mode="cel_strong",
                    illustration_detail_strength=detail,
                    illustration_selective_highlight_fraction=0.0,
                )
                output, result_bands, applied = (
                    _apply_strong_cel_selective_highlight_profile(
                        *fixture[:-1], tone
                    )
                )
                np.testing.assert_array_equal(output, fixture[1])
                np.testing.assert_array_equal(result_bands, fixture[2])
                self.assertFalse(applied)

    def test_garment_cleanup_fills_only_a_tiny_low_chroma_hole(self) -> None:
        garment = np.asarray((False, True, True, False), dtype=bool)
        source = np.asarray(
            (
                (0.34, 0.34, 0.34),
                (0.18, 0.18, 0.19),
                (0.19, 0.19, 0.20),
                (0.10, 0.02, 0.20),
            ),
            dtype=np.float64,
        )
        from spectrum_mapper.engine import srgb_to_lab

        neighbors = np.asarray(
            ((1, 2, -1), (0, 2, -1), (0, 1, -1), (1, 2, -1)),
            dtype=np.int32,
        )
        vertices, faces = self._separate_triangles(("flat",) * len(source))
        filled = _fill_strong_cel_garment_mask_holes(
            garment,
            source,
            srgb_to_lab(source),
            np.asarray((0.2, 0.2, 0.2, 0.2)),
            neighbors,
            vertices_unit=vertices,
            faces=faces,
        )
        np.testing.assert_array_equal(
            filled,
            np.asarray((True, True, True, False)),
        )

    def test_garment_cleanup_does_not_absorb_dim_silver_or_cross_a_crease(
        self,
    ) -> None:
        from spectrum_mapper.engine import srgb_to_lab

        garment = np.asarray((False, True, True), dtype=bool)
        neighbors = np.asarray(
            ((1, 2, -1), (0, 2, -1), (0, 1, -1)),
            dtype=np.int32,
        )
        areas = np.full(3, 0.2, dtype=np.float64)

        silver = np.asarray(
            (
                (0.37, 0.37, 0.38),
                (0.18, 0.18, 0.19),
                (0.19, 0.19, 0.20),
            ),
            dtype=np.float64,
        )
        flat_vertices, flat_faces = self._separate_triangles(
            ("flat",) * len(silver)
        )
        silver_result = _fill_strong_cel_garment_mask_holes(
            garment,
            silver,
            srgb_to_lab(silver),
            areas,
            neighbors,
            vertices_unit=flat_vertices,
            faces=flat_faces,
        )
        np.testing.assert_array_equal(silver_result, garment)

        crease_hole = np.asarray(
            (
                (0.34, 0.34, 0.34),
                (0.18, 0.18, 0.19),
                (0.19, 0.19, 0.20),
            ),
            dtype=np.float64,
        )
        crease_vertices, crease_faces = self._separate_triangles(
            ("crease", "flat", "flat")
        )
        crease_result = _fill_strong_cel_garment_mask_holes(
            garment,
            crease_hole,
            srgb_to_lab(crease_hole),
            areas,
            neighbors,
            vertices_unit=crease_vertices,
            faces=crease_faces,
        )
        np.testing.assert_array_equal(crease_result, garment)

    @staticmethod
    def _separate_triangles(
        normal_classes: tuple[str, ...],
    ) -> tuple[np.ndarray, np.ndarray]:
        vertices: list[tuple[float, float, float]] = []
        for face_id, normal_class in enumerate(normal_classes):
            x = float(face_id * 3)
            if normal_class == "crease":
                vertices.extend(
                    (
                        (x, 0.0, 0.0),
                        (x + 1.0, 0.0, 0.0),
                        (x, np.sqrt(0.5), np.sqrt(0.5)),
                    )
                )
            else:
                vertices.extend(
                    (
                        (x, 0.0, 0.0),
                        (x + 1.0, 0.0, 0.0),
                        (x, 1.0, 0.0),
                    )
                )
        faces = np.arange(len(vertices), dtype=np.int32).reshape((-1, 3))
        return np.asarray(vertices, dtype=np.float64), faces

    def test_garment_region_grow_absorbs_only_broad_smooth_gray_highlight(
        self,
    ) -> None:
        # Faces 2..4 form a broad grey patch connected to two distinct black
        # garment seeds.  Face 5 is a small coplanar silver detail, face 6 is
        # eye white, and face 7 is warm skin; none may be absorbed.
        garment = np.asarray(
            (True, True, False, False, False, False, False, False),
            dtype=bool,
        )
        source = np.asarray(
            (
                (0.10, 0.10, 0.11),
                (0.11, 0.11, 0.12),
                (0.40, 0.40, 0.41),
                (0.41, 0.41, 0.42),
                (0.39, 0.39, 0.40),
                (0.45, 0.45, 0.46),
                (0.92, 0.92, 0.92),
                (0.45, 0.40, 0.38),
            ),
            dtype=np.float64,
        )
        neighbors = np.asarray(
            (
                (2, 5, 6),
                (3, 5, 7),
                (0, 3, 4),
                (1, 2, 4),
                (2, 3, -1),
                (0, 1, -1),
                (0, 1, -1),
                (0, 1, -1),
            ),
            dtype=np.int32,
        )
        vertices, faces = self._separate_triangles(("flat",) * len(source))
        from spectrum_mapper.engine import srgb_to_lab

        grown = _grow_strong_cel_garment_highlight_regions(
            garment,
            source,
            srgb_to_lab(source),
            np.asarray((0.5, 0.5, 0.6, 0.6, 0.6, 0.3, 0.3, 0.3)),
            neighbors,
            vertices,
            faces,
        )

        np.testing.assert_array_equal(
            grown,
            np.asarray(
                (True, True, True, True, True, False, False, False),
                dtype=bool,
            ),
        )

    def test_garment_region_grow_stops_at_a_hard_crease(self) -> None:
        garment = np.asarray((True, True, False, False, False), dtype=bool)
        source = np.asarray(
            (
                (0.10, 0.10, 0.11),
                (0.11, 0.11, 0.12),
                (0.40, 0.40, 0.41),
                (0.41, 0.41, 0.42),
                (0.39, 0.39, 0.40),
            ),
            dtype=np.float64,
        )
        neighbors = np.asarray(
            (
                (2, -1, -1),
                (3, -1, -1),
                (0, 3, 4),
                (1, 2, 4),
                (2, 3, -1),
            ),
            dtype=np.int32,
        )
        vertices, faces = self._separate_triangles(
            ("flat", "flat", "crease", "crease", "crease")
        )
        from spectrum_mapper.engine import srgb_to_lab

        grown = _grow_strong_cel_garment_highlight_regions(
            garment,
            source,
            srgb_to_lab(source),
            np.asarray((0.5, 0.5, 0.6, 0.6, 0.6)),
            neighbors,
            vertices,
            faces,
        )

        np.testing.assert_array_equal(grown, garment)

    def test_garment_region_grow_ignores_one_reversed_triangle(self) -> None:
        outer = np.asarray(
            [
                (
                    np.cos(2.0 * np.pi * index / 5.0),
                    np.sin(2.0 * np.pi * index / 5.0),
                    0.0,
                )
                for index in range(5)
            ],
            dtype=np.float64,
        )
        vertices = np.vstack((np.zeros((1, 3), dtype=np.float64), outer))
        faces = np.asarray(
            [
                (0, index + 1, ((index + 1) % 5) + 1)
                for index in range(5)
            ],
            dtype=np.int32,
        )
        reversed_faces = faces.copy()
        reversed_faces[3] = reversed_faces[3, ::-1]
        neighbors = np.asarray(
            [
                ((index - 1) % 5, (index + 1) % 5, -1)
                for index in range(5)
            ],
            dtype=np.int32,
        )
        garment = np.asarray((True, True, False, False, False), dtype=bool)
        source = np.asarray(
            (
                (0.18, 0.18, 0.19),
                (0.19, 0.19, 0.20),
                (0.40, 0.40, 0.41),
                (0.41, 0.41, 0.42),
                (0.39, 0.39, 0.40),
            ),
            dtype=np.float64,
        )
        from spectrum_mapper.engine import srgb_to_lab

        grown = _grow_strong_cel_garment_highlight_regions(
            garment,
            source,
            srgb_to_lab(source),
            np.full(5, 0.6, dtype=np.float64),
            neighbors,
            vertices,
            reversed_faces,
        )

        np.testing.assert_array_equal(grown, np.ones(5, dtype=bool))

    def test_garment_region_grow_preserves_a_broad_muted_warm_surface(
        self,
    ) -> None:
        garment = np.asarray((True, True, False, False), dtype=bool)
        source = np.asarray(
            (
                (0.18, 0.18, 0.19),
                (0.19, 0.19, 0.20),
                (0.45, 0.40, 0.38),
                (0.46, 0.41, 0.39),
            ),
            dtype=np.float64,
        )
        neighbors = np.asarray(
            (
                (2, -1, -1),
                (3, -1, -1),
                (0, 3, -1),
                (1, 2, -1),
            ),
            dtype=np.int32,
        )
        vertices, faces = self._separate_triangles(("flat",) * len(source))
        from spectrum_mapper.engine import srgb_to_lab

        grown = _grow_strong_cel_garment_highlight_regions(
            garment,
            source,
            srgb_to_lab(source),
            np.asarray((0.5, 0.5, 0.8, 0.8)),
            neighbors,
            vertices,
            faces,
        )

        np.testing.assert_array_equal(grown, garment)

    def test_garment_region_grow_respects_part_local_adjacency(self) -> None:
        garment = np.asarray((True, True, False, False), dtype=bool)
        source = np.asarray(
            (
                (0.10, 0.10, 0.11),
                (0.11, 0.11, 0.12),
                (0.40, 0.40, 0.41),
                (0.41, 0.41, 0.42),
            ),
            dtype=np.float64,
        )
        # The complete topology could connect 0-2 and 1-3, but the recolour
        # entry point replaces cross-part entries with -1 before this helper.
        part_local_neighbors = np.asarray(
            (
                (-1, -1, -1),
                (-1, -1, -1),
                (3, -1, -1),
                (2, -1, -1),
            ),
            dtype=np.int32,
        )
        vertices, faces = self._separate_triangles(("flat",) * len(source))
        from spectrum_mapper.engine import srgb_to_lab

        grown = _grow_strong_cel_garment_highlight_regions(
            garment,
            source,
            srgb_to_lab(source),
            np.asarray((0.5, 0.5, 0.8, 0.8)),
            part_local_neighbors,
            vertices,
            faces,
        )

        np.testing.assert_array_equal(grown, garment)


if __name__ == "__main__":
    unittest.main()
