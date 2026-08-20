from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.filament_database import FilamentProduct, FilamentRepository
from spectrum_mapper import mixer
from spectrum_mapper.owned_filaments import (
    OwnedFilamentInventory,
    OwnedFilamentSelectionError,
    load_owned_filament_inventory,
    recommend_from_owned_filaments,
    save_owned_filament_inventory,
)


def product(
    product_id: str,
    color: str,
    *,
    brand: str = "Test Brand",
    series: str = "PLA",
    finish: str = "標準/不透明",
    source_kind: str = "catalog",
) -> FilamentProduct:
    return FilamentProduct(
        product_id=product_id,
        brand=brand,
        series=series,
        color_name=product_id,
        matched_hex=color,
        finish_class=finish,
        source_kind=source_kind,
        source_url="https://example.invalid/product",
        record_id=product_id,
        measurement_id=None,
        alias_product_ids=(product_id,),
    )


class _FakeRepository:
    def __init__(self, products: tuple[FilamentProduct, ...]) -> None:
        self.products = products

    def list_products(self, *, prefer_measured: bool = True):
        del prefer_measured
        return self.products


class FilamentProductListingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = FilamentRepository()

    def test_products_are_stable_grouped_and_measured_preferred(self) -> None:
        products = self.repository.list_products(prefer_measured=True, material="PLA")
        self.assertGreater(len(products), 2_000)
        self.assertTrue(all(item.product_id for item in products))
        self.assertEqual(len({item.product_id for item in products}), len(products))
        groups = self.repository.products_grouped_by_brand(material="PLA")
        self.assertEqual(len(groups), 19)
        self.assertEqual(sum(len(items) for _brand, items in groups), len(products))

        red_id = "catalog:ofd:02eaa799-16a4-5a41-a641-980f31312c69"
        red = self.repository.get_products(
            (red_id,), prefer_measured=True, material="PLA"
        )
        self.assertEqual(len(red), 1)
        self.assertEqual(red[0].source_kind, "measured")
        self.assertEqual(red[0].measurement_id, "measured:001")

    def test_bad_catalog_link_does_not_merge_different_series(self) -> None:
        products = self.repository.list_products(prefer_measured=True)
        measurement_ids = {item.measurement_id for item in products}
        self.assertIn("measured:024", measurement_ids)
        self.assertIn("measured:025", measurement_ids)
        self.assertIn("measured:020", measurement_ids)
        self.assertIn("measured:021", measurement_ids)


class OwnedInventoryPersistenceTests(unittest.TestCase):
    def test_snapshots_are_portable_and_current_database_wins(self) -> None:
        old = product("catalog:test-red", "#CC0000")
        current = product("catalog:test-red", "#D01010")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owned_filaments.json"
            save_owned_filament_inventory(OwnedFilamentInventory((old,)), path)
            raw_text = path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            self.assertEqual(raw["products"][0]["matched_hex"], "#CC0000")
            self.assertNotIn(str(Path(directory).resolve()), raw_text)

            loaded = load_owned_filament_inventory(
                path,
                repository=_FakeRepository((current,)),  # type: ignore[arg-type]
            )
            self.assertEqual(loaded.products, (current,))
            self.assertEqual(loaded.stale_product_ids, ())

    def test_missing_database_product_uses_snapshot_and_warns(self) -> None:
        saved = product("catalog:retired-blue", "#204FD0")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owned_filaments.json"
            save_owned_filament_inventory((saved,), path)
            loaded = load_owned_filament_inventory(
                path,
                repository=_FakeRepository(()),  # type: ignore[arg-type]
            )
            self.assertEqual(loaded.products[0].matched_hex, "#204FD0")
            self.assertEqual(loaded.stale_product_ids, (saved.product_id,))
            self.assertTrue(any("保存時の色情報" in text for text in loaded.diagnostics))

            unverified = load_owned_filament_inventory(path)
            self.assertEqual(
                unverified.stale_product_ids,
                (saved.product_id,),
            )

    def test_legacy_unknown_id_is_preserved_as_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owned_filaments.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "product_ids": ["catalog:no-longer-present"],
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_owned_filament_inventory(
                path,
                repository=_FakeRepository(()),  # type: ignore[arg-type]
            )
            self.assertEqual(
                loaded.unresolved_product_ids,
                ("catalog:no-longer-present",),
            )
            save_owned_filament_inventory(loaded, path)
            reloaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                reloaded["unresolved_product_ids"],
                ["catalog:no-longer-present"],
            )

    def test_duplicate_hex_is_diagnosed_and_not_counted_twice(self) -> None:
        inventory = OwnedFilamentInventory(
            (
                product("a", "#111111"),
                product("b", "#111111", source_kind="measured"),
                product("c", "#FFFFFF"),
                product("d", "#FF0000"),
            )
        )
        self.assertEqual(len(inventory.duplicate_color_groups), 1)
        self.assertEqual(len(inventory.recommendable_products), 3)
        self.assertFalse(inventory.can_recommend)


class OwnedRecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.products = (
            product("black", "#101010"),
            product("white", "#F5F5F5"),
            product("red", "#E02030"),
            product("blue", "#204FD0", finish="マット"),
        )
        self.target = np.asarray(
            (
                (16, 16, 16),
                (245, 245, 245),
                (224, 32, 48),
                (32, 79, 208),
                (120, 60, 120),
            ),
            dtype=np.uint8,
        )

    def test_less_than_four_distinct_hex_is_an_explicit_error(self) -> None:
        with self.assertRaisesRegex(OwnedFilamentSelectionError, "異なるHEX色"):
            recommend_from_owned_filaments(
                self.target,
                owned_products=(
                    product("a", "#000000"),
                    product("b", "#000000"),
                    product("c", "#FFFFFF"),
                    product("d", "#FF0000"),
                ),
                max_passes=1,
            )

    def test_16_24_32_keep_stable_state_counts_and_return_atomic_fields(self) -> None:
        for state_count in (16, 24, 32):
            with self.subTest(state_count=state_count):
                result = recommend_from_owned_filaments(
                    self.target,
                    np.ones(len(self.target)),
                    owned_products=self.products,
                    palette_state_count=state_count,
                    max_passes=2,
                )
                self.assertEqual(len(result.candidates), 4)
                self.assertEqual(len(result.physical_hex), 4)
                self.assertEqual(len(result.mix_ratios_b), 6)
                self.assertEqual(len(result.secondary_mix_ratios_b), 6)
                self.assertEqual(len(result.palette_hex), state_count)
                self.assertLessEqual(
                    result.mean_delta_e76,
                    result.before_mean_delta_e76 + 1e-12,
                )
                self.assertGreaterEqual(result.refined_combination_count, 1)
                self.assertLessEqual(
                    result.refined_combination_count,
                    4,
                )
                self.assertEqual(
                    tuple(item.matched_hex for item in result.candidates),
                    result.physical_hex,
                )
                self.assertTrue(result.special_finish_products)
                self.assertTrue(any("特殊質感" in text for text in result.warnings))

    def test_secondary_ratio_optimization_is_opt_in_and_reported(self) -> None:
        black = np.asarray((16, 16, 16), dtype=np.uint8)
        white = np.asarray((245, 245, 245), dtype=np.uint8)
        # The release installs its Orca-compatible mixer hotfix at runtime;
        # resolve through the module so the target and optimiser use the same
        # active implementation regardless of test import order.
        target = mixer.mix_rgb8(black, white, 0.42).reshape(1, 3)
        enabled = [False] * 16
        enabled[10] = True  # secondary F1/F2 state only
        result = mixer.optimize_global_mix_ratios(
            target,
            (black, white, (255, 0, 0), (0, 0, 255)),
            initial_ratios_b=(33,) * 6,
            secondary_ratios_b=(67,) * 6,
            enabled_states=enabled,
            max_passes=2,
            optimize_secondary_ratios=True,
        )
        self.assertEqual(result.initial_secondary_mix_ratios_b[0], 67)
        # Integer RGB quantisation can make adjacent recipes exactly equal.
        self.assertIn(result.secondary_mix_ratios_b[0], (41, 42))
        self.assertAlmostEqual(result.weighted_mean_delta_e76, 0.0, places=10)

    def test_pink_protection_is_used_for_slot_order_and_ratio_fit(self) -> None:
        products = (
            product("black", "#101010"),
            product("white", "#F5F5F5"),
            product("red", "#E02030"),
            product("pink", "#FF80B0"),
        )
        target = np.asarray(
            (
                (16, 16, 16),
                (245, 245, 245),
                (224, 32, 48),
                (255, 128, 176),
            ),
            dtype=np.uint8,
        )
        result = recommend_from_owned_filaments(
            target,
            np.ones(len(target)),
            owned_products=products,
            pink_protection_mask=(False, False, False, True),
            max_passes=2,
        )

        # The application reserves the F4 family for protected faces.  The
        # owned-filament selector must therefore place the pink spool in F4,
        # then optimise ratios under the same restriction as final recolour.
        self.assertEqual(result.candidates[3].product_id, "pink")
        self.assertAlmostEqual(result.mean_delta_e76, 0.0, places=10)

    def test_pink_protection_mask_length_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "pink_protection_mask"):
            recommend_from_owned_filaments(
                self.target,
                owned_products=self.products,
                pink_protection_mask=(False, True),
                max_passes=1,
            )

    def test_pink_protection_keeps_reference_samples_and_their_weight(self) -> None:
        products = (
            product("black", "#101010"),
            product("white", "#F5F5F5"),
            product("red", "#E02030"),
            product("pink", "#FF80B0"),
        )
        object_rgb = np.asarray(
            ((16, 16, 16), (255, 128, 176)),
            dtype=np.uint8,
        )
        reference_rgb = np.asarray(((0, 255, 0),), dtype=np.uint8)

        with patch(
            "spectrum_mapper.owned_filaments.optimize_global_mix_ratios",
            wraps=mixer.optimize_global_mix_ratios,
        ) as optimize:
            recommend_from_owned_filaments(
                object_rgb,
                np.asarray((3.0, 1.0)),
                owned_products=products,
                reference_rgb=reference_rgb,
                reference_weights=np.asarray((1_000_000.0,)),
                reference_confidence=0.5,
                pink_protection_mask=(False, True),
                max_passes=1,
            )

        self.assertGreater(optimize.call_count, 0)
        call = optimize.call_args_list[-1]
        optimized_rgb = np.asarray(call.args[0])
        optimized_weights = np.asarray(call.kwargs["weights"])
        optimized_pink = np.asarray(call.kwargs["pink_protection_mask"])
        unrestricted = np.asarray(call.kwargs["unrestricted_state_mask"])
        self.assertEqual(unrestricted.dtype, np.bool_)
        self.assertEqual(len(unrestricted), len(optimized_rgb))
        self.assertAlmostEqual(float(optimized_weights.sum()), 1.0)
        # Reference fraction is capped at 30% then scaled by 0.5 confidence.
        self.assertAlmostEqual(float(optimized_weights[unrestricted].sum()), 0.15)
        self.assertTrue(
            np.any(np.all(optimized_rgb[unrestricted] == reference_rgb[0], axis=1))
        )
        self.assertTrue(np.all(~optimized_pink[unrestricted]))

    def test_unrestricted_reference_sample_can_use_either_palette_family(self) -> None:
        enabled = [False] * 16
        enabled[0] = True
        enabled[3] = True
        result = mixer.optimize_global_mix_ratios(
            np.asarray(((255, 128, 176),), dtype=np.uint8),
            ("#101010", "#F5F5F5", "#E02030", "#FF80B0"),
            enabled_states=enabled,
            pink_protection_mask=(False,),
            unrestricted_state_mask=(True,),
            max_passes=1,
        )
        self.assertAlmostEqual(result.weighted_mean_delta_e76, 0.0, places=10)

    def test_larger_palette_guard_keeps_real_snapshot_quality_monotonic(self) -> None:
        # Twelve portable snapshots from the release smoke inventory.  This
        # previously selected a different F1..F4 order at 32 states and
        # regressed mean Delta E from 15.583 to 15.766 even though states
        # 1..16 are still present.
        smoke_products = tuple(
            product(product_id, color)
            for product_id, color in (
                (
                    "catalog:ofd:4709c8d1-6be4-5c89-a051-ac0b5c1a22df",
                    "#492972",
                ),
                (
                    "catalog:ofd:54ec4f8e-725a-5e13-90f5-c291d736a3e0",
                    "#55331A",
                ),
                (
                    "catalog:ofd:17c4c80b-5116-5f92-be3f-5f3dba26d853",
                    "#34695A",
                ),
                (
                    "catalog:ofd:cb05a6df-27c7-5dc1-99c0-eab83b10f715",
                    "#444A62",
                ),
                (
                    "catalog:ofd:949c8793-68be-53e0-8972-6fa27f036120",
                    "#CCA897",
                ),
                (
                    "catalog:ofd:fc18dfb6-cf6a-54cb-a676-1aa9fd677182",
                    "#062B4D",
                ),
                (
                    "catalog:ofd:7869ac03-624d-5610-a6b0-367867b06621",
                    "#724E3D",
                ),
                (
                    "catalog:ofd:10a25712-52e7-59b6-b24c-9cb265dde53b",
                    "#515234",
                ),
                (
                    "catalog:ofd:feed3a98-9c66-5d3a-a23b-54377f56b353",
                    "#000000",
                ),
                (
                    "catalog:ofd:a9910b6c-9c78-543c-a48f-d78a4a85d787",
                    "#FFFFFF",
                ),
                (
                    "catalog:ofd:b6c06a35-59cc-5002-9c45-1987d266d822",
                    "#C8E6A0",
                ),
                (
                    "catalog:ofd:977726ff-40b5-5716-8dca-0afdc526116d",
                    "#485155",
                ),
            )
        )
        target = np.asarray(
            (
                (15, 15, 18),
                (245, 240, 232),
                (198, 47, 57),
                (40, 87, 185),
                (230, 174, 52),
                (174, 112, 87),
                (95, 55, 130),
                (78, 80, 84),
            ),
            dtype=np.uint8,
        )
        weights = np.asarray((4, 3, 2, 2, 1, 2, 1, 2), dtype=np.float64)
        results = {}
        optimizer_calls = {}
        for state_count in (16, 24, 32):
            with patch(
                "spectrum_mapper.owned_filaments.optimize_global_mix_ratios",
                wraps=mixer.optimize_global_mix_ratios,
            ) as optimize:
                results[state_count] = recommend_from_owned_filaments(
                    target,
                    weights,
                    owned_products=smoke_products,
                    palette_state_count=state_count,
                    max_passes=3,
                )
                optimizer_calls[state_count] = optimize.call_count

        tolerance = 1e-10
        self.assertLessEqual(
            results[24].mean_delta_e76,
            results[16].mean_delta_e76 + tolerance,
        )
        self.assertLessEqual(
            results[32].mean_delta_e76,
            results[16].mean_delta_e76 + tolerance,
        )
        self.assertTrue(
            all(
                count <= 4
                for count in optimizer_calls.values()
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
