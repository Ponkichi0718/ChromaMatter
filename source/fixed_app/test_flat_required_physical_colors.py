from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.filament_recommender import (
    CATEGORY_PRIMARY,
    FilamentCandidate,
    recommend_basic_filaments,
)
from spectrum_mapper.filament_database import FilamentProduct
from spectrum_mapper.owned_filaments import recommend_from_owned_filaments


def _candidate(product_id: str, color: str) -> FilamentCandidate:
    return FilamentCandidate(
        product_id,
        product_id,
        color,
        CATEGORY_PRIMARY,
    )


def _product(product_id: str, color: str) -> FilamentProduct:
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


class FlatRequiredPhysicalColorTests(unittest.TestCase):
    COLORS = (
        ("black", "#101010"),
        ("navy", "#33384A"),
        ("skin", "#EDC09D"),
        ("red", "#E02030"),
        ("white", "#F5F5F5"),
    )

    def test_small_required_eye_white_survives_final_standard_proposal(
        self,
    ) -> None:
        catalog = tuple(
            _candidate(product_id, color)
            for product_id, color in self.COLORS
        )
        target_rgb = np.asarray(
            [candidate.rgb8 for candidate in catalog],
            dtype=np.uint8,
        )

        result = recommend_basic_filaments(
            target_rgb,
            np.asarray([100.0, 80.0, 60.0, 30.0, 0.1]),
            catalog=catalog,
            in_stock_only=False,
            include_mixed_states=False,
            max_candidates=4,
            required_physical_rgb=np.asarray([[245, 245, 245]], dtype=np.uint8),
        )

        self.assertEqual(len(result.candidates), 4)
        self.assertIn("white", result.candidate_ids)
        self.assertEqual(result.palette_hex, result.physical_hex)

    def test_integer_required_rgb_normalizes_identically_for_both_paths(
        self,
    ) -> None:
        catalog = tuple(
            _candidate(product_id, color)
            for product_id, color in self.COLORS
        )
        owned = tuple(
            _product(product_id, color)
            for product_id, color in self.COLORS
        )
        target_rgb = np.asarray(
            [candidate.rgb8 for candidate in catalog], dtype=np.uint8
        )
        weights = np.asarray([100.0, 80.0, 60.0, 30.0, 0.1])
        required_integer = np.asarray([[245, 245, 245]], dtype=np.uint8)
        required_unit = required_integer.astype(np.float64) / 255.0

        standard_integer = recommend_basic_filaments(
            target_rgb,
            weights,
            catalog=catalog,
            in_stock_only=False,
            include_mixed_states=False,
            max_candidates=4,
            required_physical_rgb=required_integer,
        )
        standard_unit = recommend_basic_filaments(
            target_rgb,
            weights,
            catalog=catalog,
            in_stock_only=False,
            include_mixed_states=False,
            max_candidates=4,
            required_physical_rgb=required_unit,
        )
        owned_integer = recommend_from_owned_filaments(
            target_rgb,
            weights,
            owned_products=owned,
            include_mixed_states=False,
            max_candidates=4,
            max_passes=1,
            required_physical_rgb=required_integer,
        )
        owned_unit = recommend_from_owned_filaments(
            target_rgb,
            weights,
            owned_products=owned,
            include_mixed_states=False,
            max_candidates=4,
            max_passes=1,
            required_physical_rgb=required_unit,
        )

        self.assertEqual(
            standard_integer.candidate_ids, standard_unit.candidate_ids
        )
        self.assertEqual(owned_integer.candidate_ids, owned_unit.candidate_ids)
        self.assertIn("white", standard_integer.candidate_ids)
        self.assertIn("white", owned_integer.candidate_ids)


if __name__ == "__main__":
    unittest.main()
