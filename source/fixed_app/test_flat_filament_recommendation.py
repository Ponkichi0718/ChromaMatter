from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import mixer
from spectrum_mapper.filament_database import FilamentProduct
from spectrum_mapper.filament_recommender import (
    CATEGORY_PRIMARY,
    FilamentCandidate,
    recommend_basic_filaments,
)
from spectrum_mapper.owned_filaments import recommend_from_owned_filaments


def candidate(product_id: str, color: str) -> FilamentCandidate:
    return FilamentCandidate(
        product_id,
        product_id,
        color,
        CATEGORY_PRIMARY,
    )


def product(product_id: str, color: str) -> FilamentProduct:
    return FilamentProduct(
        product_id=product_id,
        brand="Test Brand",
        series="PLA",
        color_name=product_id,
        matched_hex=color,
        finish_class="標準/不透明",
        source_kind="catalog",
        source_url=None,
        record_id=product_id,
        measurement_id=None,
        alias_product_ids=(product_id,),
    )


FIVE_COLORS = (
    ("black", "#101010"),
    ("white", "#F5F5F5"),
    ("red", "#E02030"),
    ("green", "#159447"),
    ("blue", "#204FD0"),
)


class FlatFilamentRecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = tuple(candidate(product_id, color) for product_id, color in FIVE_COLORS)
        self.target_rgb = np.asarray(
            [item.rgb8 for item in self.catalog],
            dtype=np.uint8,
        )
        self.area_weights = np.asarray((9.0, 7.0, 5.0, 3.0, 1.0))

    def test_flat_proposal_contains_only_four_physical_states(self) -> None:
        with patch.object(
            mixer,
            "mix_rgb8",
            side_effect=AssertionError("flat proposal must not synthesize mixed colors"),
        ):
            result = recommend_basic_filaments(
                self.target_rgb,
                self.area_weights,
                catalog=self.catalog,
                in_stock_only=False,
                include_mixed_states=False,
                max_candidates=None,
            )

        self.assertEqual(len(result.candidates), 4)
        self.assertEqual(result.palette_hex, result.physical_hex)
        self.assertEqual(len(result.usage), 4)
        self.assertTrue(
            all(
                len(usage.component_ids) == 1 and usage.ratio_b_percent is None
                for usage in result.usage
            )
        )
        self.assertAlmostEqual(sum(result.base_usage_fractions), 1.0)

    def test_flat_proposal_is_area_weighted(self) -> None:
        compact = recommend_basic_filaments(
            self.target_rgb,
            self.area_weights,
            catalog=self.catalog,
            in_stock_only=False,
            include_mixed_states=False,
            max_candidates=None,
        )
        repeated = recommend_basic_filaments(
            np.repeat(self.target_rgb, self.area_weights.astype(np.int64), axis=0),
            catalog=self.catalog,
            in_stock_only=False,
            include_mixed_states=False,
            max_candidates=None,
        )

        self.assertEqual(compact.candidate_ids, repeated.candidate_ids)
        self.assertEqual(compact.candidate_ids, ("black", "green", "red", "white"))
        self.assertAlmostEqual(compact.score, repeated.score, places=12)
        self.assertAlmostEqual(
            compact.mean_delta_e76,
            repeated.mean_delta_e76,
            places=12,
        )
        np.testing.assert_allclose(
            compact.base_usage_fractions,
            repeated.base_usage_fractions,
            rtol=0.0,
            atol=1e-12,
        )

    def test_duplicate_hex_is_stably_deduplicated_before_shortlisting(self) -> None:
        catalog = (
            candidate("duplicate-z", "#E02030"),
            candidate("black", "#101010"),
            candidate("duplicate-a", "#E02030"),
            candidate("white", "#F5F5F5"),
            candidate("green", "#159447"),
            candidate("blue", "#204FD0"),
        )
        target = np.asarray(
            ((224, 32, 48), (16, 16, 16), (245, 245, 245), (21, 148, 71)),
            dtype=np.uint8,
        )

        results = tuple(
            recommend_basic_filaments(
                target,
                (20.0, 1.0, 1.0, 1.0),
                catalog=ordered,
                in_stock_only=False,
                include_mixed_states=False,
                max_candidates=4,
            )
            for ordered in (catalog, tuple(reversed(catalog)))
        )

        self.assertEqual(results[0].candidate_ids, results[1].candidate_ids)
        self.assertIn("duplicate-a", results[0].candidate_ids)
        self.assertNotIn("duplicate-z", results[0].candidate_ids)
        self.assertEqual(len(set(results[0].physical_hex)), 4)
        self.assertEqual(results[0].candidate_pool_size, 4)
        self.assertEqual(results[0].evaluated_combinations, math.comb(4, 4))

    def test_flat_proposal_requires_four_distinct_hex_colors(self) -> None:
        catalog = (
            candidate("red-a", "#E02030"),
            candidate("red-b", "#E02030"),
            candidate("white", "#F5F5F5"),
            candidate("black", "#101010"),
        )
        with self.assertRaisesRegex(ValueError, "four distinct filament colours"):
            recommend_basic_filaments(
                self.target_rgb,
                self.area_weights,
                catalog=catalog,
                in_stock_only=False,
                include_mixed_states=False,
                max_candidates=None,
            )

    def test_default_full_spectrum_proposal_still_builds_mixed_states(self) -> None:
        four_catalog = self.catalog[:4]
        with patch.object(mixer, "mix_rgb8", wraps=mixer.mix_rgb8) as mix_rgb8:
            result = recommend_basic_filaments(
                self.target_rgb[:4],
                self.area_weights[:4],
                catalog=four_catalog,
                in_stock_only=False,
                max_candidates=None,
            )

        self.assertGreater(mix_rgb8.call_count, 0)
        self.assertEqual(len(result.palette_hex), 16)
        self.assertEqual(len(result.usage), 16)


class OwnedFlatFilamentRecommendationTests(unittest.TestCase):
    def test_owned_flat_proposal_scores_only_the_four_physical_slots(self) -> None:
        owned_products = tuple(product(product_id, color) for product_id, color in FIVE_COLORS)
        target_rgb = np.asarray(
            [tuple(int(color[index : index + 2], 16) for index in (1, 3, 5)) for _, color in FIVE_COLORS],
            dtype=np.uint8,
        )
        # Simulate a stale Full Spectrum mask that had only a mixed state on.
        # Flat mode must enable all four proposed physical slots itself.
        enabled_states = [False] * 16
        enabled_states[4] = True

        result = recommend_from_owned_filaments(
            target_rgb,
            (9.0, 7.0, 5.0, 3.0, 1.0),
            owned_products=owned_products,
            enabled_states=enabled_states,
            include_mixed_states=False,
            max_candidates=5,
            max_passes=1,
        )

        self.assertEqual(len(result.candidates), 4)
        self.assertEqual(result.selection.palette_hex, result.selection.physical_hex)
        self.assertEqual(len(result.selection.usage), 4)
        self.assertEqual(result.optimization.objective_evaluations, 0)
        self.assertTrue(
            all(
                fraction == 0.0
                for fraction in result.optimization.palette_weight_fractions[4:]
            )
        )
        self.assertAlmostEqual(
            sum(result.optimization.palette_weight_fractions[:4]),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
