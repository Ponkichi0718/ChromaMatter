from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.filament_recommender import (
    CATEGORY_INTERMEDIATE,
    CATEGORY_NEUTRAL,
    CATEGORY_PRIMARY,
    CATEGORY_SKIN,
    DEFAULT_RECOMMENDATION_POLICY,
    DEFAULT_CURATED_CATALOG,
    FilamentCandidate,
    RECOMMENDATION_POLICY_BASIC,
    RECOMMENDATION_POLICY_FLEXIBLE,
    build_representative_colors,
    curated_catalog_for_recommendation,
    map_catalog_to_curated_basics,
    normalize_recommendation_policy,
    recommend_basic_filaments,
)
from spectrum_mapper import mixer
from spectrum_mapper.mixer import hex_to_rgb8


def candidate(
    candidate_id: str,
    color: str,
    category: str = CATEGORY_PRIMARY,
    *,
    auto_allowed: bool = True,
) -> FilamentCandidate:
    return FilamentCandidate(
        candidate_id,
        candidate_id,
        color,
        category,
        auto_allowed=auto_allowed,
    )


def colors_for(catalog: tuple[FilamentCandidate, ...]) -> np.ndarray:
    return np.asarray([hex_to_rgb8(item.hex_color) for item in catalog])


class RepresentativeColorTests(unittest.TestCase):
    def test_triangle_area_weights_are_preserved(self) -> None:
        representatives = build_representative_colors(
            np.asarray(((255, 0, 0), (0, 0, 255))),
            np.asarray((9.0, 1.0)),
            bins_per_channel=16,
        )

        by_hex = {
            item.hex_color: item.weight_fraction
            for item in representatives.colors
        }
        self.assertAlmostEqual(by_hex["#FF0000"], 0.9)
        self.assertAlmostEqual(by_hex["#0000FF"], 0.1)
        self.assertAlmostEqual(representatives.object_weight_fraction, 1.0)
        self.assertAlmostEqual(representatives.reference_weight_fraction, 0.0)

    def test_reference_is_capped_at_thirty_percent_and_scaled_by_confidence(self) -> None:
        representatives = build_representative_colors(
            np.asarray(((255, 0, 0),)),
            np.asarray((1000.0,)),
            reference_rgb=np.asarray(((0, 0, 255),)),
            reference_weights=np.asarray((1_000_000.0,)),
            reference_confidence=0.5,
        )

        by_hex = {
            item.hex_color: item.weight_fraction
            for item in representatives.colors
        }
        self.assertAlmostEqual(representatives.object_weight_fraction, 0.85)
        self.assertAlmostEqual(representatives.reference_weight_fraction, 0.15)
        self.assertAlmostEqual(by_hex["#FF0000"], 0.85)
        self.assertAlmostEqual(by_hex["#0000FF"], 0.15)

    def test_representatives_are_bounded_without_losing_total_weight(self) -> None:
        samples = np.asarray(
            [
                (red, green, blue)
                for red in (0, 64, 128, 192, 255)
                for green in (0, 64, 128, 192, 255)
                for blue in (0, 64, 128, 192, 255)
            ]
        )
        representatives = build_representative_colors(
            samples,
            np.arange(1, len(samples) + 1, dtype=np.float64),
            bins_per_channel=16,
            max_colors=12,
        )

        self.assertEqual(len(representatives.colors), 12)
        self.assertAlmostEqual(
            sum(item.weight_fraction for item in representatives.colors),
            1.0,
        )


class FilamentRecommendationTests(unittest.TestCase):
    @staticmethod
    def _expanded_catalog(material: str = "PLA") -> tuple[FilamentCandidate, ...]:
        # Models with a dominant red/brown body exposed the expanded-library
        # regression: aggregate-mean shortlisting used all 18 places on these
        # nearby browns before black and gray reached the four-colour solver.
        browns = tuple(
            FilamentCandidate(
                f"{material.lower()}-brown-{index:02d}",
                f"Brown {index:02d}",
                f"#{70 + index % 30:02X}"
                f"{35 + (index * 3) % 35:02X}"
                f"{28 + (index * 5) % 28:02X}",
                CATEGORY_PRIMARY,
                material=material,
            )
            for index in range(60)
        )
        basics = (
            FilamentCandidate(
                f"{material.lower()}-black",
                "Black",
                "#111111",
                CATEGORY_PRIMARY,
                material=material,
            ),
            FilamentCandidate(
                f"{material.lower()}-light-gray",
                "Light Gray",
                "#D0D0D0",
                CATEGORY_PRIMARY,
                material=material,
            ),
            FilamentCandidate(
                f"{material.lower()}-red",
                "Red",
                "#D92030",
                CATEGORY_PRIMARY,
                material=material,
            ),
            FilamentCandidate(
                f"{material.lower()}-white",
                "White",
                "#F5F5F5",
                CATEGORY_PRIMARY,
                material=material,
            ),
            FilamentCandidate(
                f"{material.lower()}-blue",
                "Blue",
                "#204FD0",
                CATEGORY_PRIMARY,
                material=material,
            ),
            FilamentCandidate(
                f"{material.lower()}-green",
                "Green",
                "#159447",
                CATEGORY_PRIMARY,
                material=material,
            ),
            FilamentCandidate(
                f"{material.lower()}-skin",
                "Skin",
                "#F2C6A0",
                CATEGORY_PRIMARY,
                material=material,
            ),
        )
        return browns + basics

    def test_curated_catalog_exposes_basics_and_excludes_middle_colors(self) -> None:
        automatic = [item for item in DEFAULT_CURATED_CATALOG if item.auto_allowed]
        categories = {item.category for item in automatic}

        self.assertTrue(
            {CATEGORY_NEUTRAL, CATEGORY_PRIMARY, CATEGORY_SKIN}.issubset(categories)
        )
        self.assertTrue(
            any(item.category == CATEGORY_INTERMEDIATE for item in DEFAULT_CURATED_CATALOG)
        )
        self.assertTrue(
            all(
                not item.auto_allowed
                for item in DEFAULT_CURATED_CATALOG
                if item.category == CATEGORY_INTERMEDIATE
            )
        )

    def test_recommendation_policy_expands_curated_intermediates_and_preserves_legacy_basics(
        self,
    ) -> None:
        self.assertEqual(
            DEFAULT_RECOMMENDATION_POLICY,
            RECOMMENDATION_POLICY_FLEXIBLE,
        )
        flexible = curated_catalog_for_recommendation(
            RECOMMENDATION_POLICY_FLEXIBLE
        )
        basic = curated_catalog_for_recommendation(
            RECOMMENDATION_POLICY_BASIC
        )
        flexible_ids = {item.id for item in flexible if item.auto_allowed}
        basic_ids = {item.id for item in basic if item.auto_allowed}
        self.assertEqual(
            flexible_ids - basic_ids,
            {
                "cool_blue_gray",
                "cool_violet_gray",
                "intermediate_beige",
                "intermediate_dusty_rose",
                "intermediate_burgundy",
            },
        )
        self.assertEqual(len(flexible_ids), 20)
        self.assertEqual(len(basic_ids), 15)
        self.assertTrue(
            all(
                item.category == CATEGORY_PRIMARY and item.auto_allowed
                for item in flexible
                if item.id.startswith("intermediate_")
            )
        )
        self.assertTrue(
            all(
                not item.auto_allowed
                for item in DEFAULT_CURATED_CATALOG
                if item.category == CATEGORY_INTERMEDIATE
            )
        )
        self.assertEqual(
            normalize_recommendation_policy(" BASIC "),
            RECOMMENDATION_POLICY_BASIC,
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            normalize_recommendation_policy("invented")

    def test_flexible_and_basic_policies_produce_distinct_cool_shadow_proposals(
        self,
    ) -> None:
        target = np.asarray(
            (
                (92, 115, 143),
                (17, 17, 17),
                (245, 245, 245),
                (227, 38, 54),
            ),
            dtype=np.uint8,
        )
        weights = np.asarray((70.0, 10.0, 10.0, 10.0))
        flexible = recommend_basic_filaments(
            target,
            weights,
            catalog=curated_catalog_for_recommendation(
                RECOMMENDATION_POLICY_FLEXIBLE
            ),
            include_mixed_states=False,
            max_candidates=None,
        )
        basic = recommend_basic_filaments(
            target,
            weights,
            catalog=curated_catalog_for_recommendation(
                RECOMMENDATION_POLICY_BASIC
            ),
            include_mixed_states=False,
            max_candidates=None,
        )

        self.assertEqual(
            flexible.candidate_ids,
            (
                "cool_blue_gray",
                "neutral_black",
                "neutral_white",
                "primary_red",
            ),
        )
        self.assertNotIn("cool_blue_gray", basic.candidate_ids)
        self.assertNotIn("cool_violet_gray", basic.candidate_ids)
        self.assertLess(flexible.mean_delta_e76, basic.mean_delta_e76)

    def test_flexible_policy_can_propose_each_curated_intermediate_color(self) -> None:
        flexible_catalog = curated_catalog_for_recommendation(
            RECOMMENDATION_POLICY_FLEXIBLE
        )
        basic_catalog = curated_catalog_for_recommendation(
            RECOMMENDATION_POLICY_BASIC
        )
        anchor_ids = (
            "intermediate_beige",
            "intermediate_dusty_rose",
            "intermediate_burgundy",
        )
        by_id = {candidate.id: candidate for candidate in flexible_catalog}
        for anchor_id in anchor_ids:
            with self.subTest(anchor_id=anchor_id):
                anchor = by_id[anchor_id]
                target = np.asarray(
                    (
                        anchor.rgb8,
                        (17, 17, 17),
                        (245, 245, 245),
                        (36, 83, 199),
                    ),
                    dtype=np.uint8,
                )
                weights = np.asarray((70.0, 10.0, 10.0, 10.0))
                flexible = recommend_basic_filaments(
                    target,
                    weights,
                    catalog=flexible_catalog,
                    include_mixed_states=False,
                    max_candidates=None,
                )
                basic = recommend_basic_filaments(
                    target,
                    weights,
                    catalog=basic_catalog,
                    include_mixed_states=False,
                    max_candidates=None,
                )
                self.assertIn(anchor_id, flexible.candidate_ids)
                self.assertNotIn(anchor_id, basic.candidate_ids)

    def test_database_anchor_mapping_filters_before_product_identity_is_selected(
        self,
    ) -> None:
        product_catalog = tuple(
            FilamentCandidate(
                id=item.id,
                label=item.label,
                hex_color=item.hex_color,
                category=CATEGORY_PRIMARY,
                material="PLA",
            )
            for item in DEFAULT_CURATED_CATALOG
        )
        flexible = map_catalog_to_curated_basics(
            product_catalog,
            recommendation_policy=RECOMMENDATION_POLICY_FLEXIBLE,
        )
        basic = map_catalog_to_curated_basics(
            product_catalog,
            recommendation_policy=RECOMMENDATION_POLICY_BASIC,
        )

        self.assertIn("cool_blue_gray", {item.id for item in flexible})
        self.assertIn("cool_violet_gray", {item.id for item in flexible})
        self.assertTrue(
            {
                "intermediate_beige",
                "intermediate_dusty_rose",
                "intermediate_burgundy",
            }.issubset({item.id for item in flexible})
        )
        self.assertNotIn("cool_blue_gray", {item.id for item in basic})
        self.assertNotIn("cool_violet_gray", {item.id for item in basic})
        self.assertFalse(
            {
                "intermediate_beige",
                "intermediate_dusty_rose",
                "intermediate_burgundy",
            }
            & {item.id for item in basic}
        )

    def test_known_primary_set_is_recovered_exactly(self) -> None:
        wanted = (
            candidate("black", "#101010", CATEGORY_NEUTRAL),
            candidate("white", "#F5F5F5", CATEGORY_NEUTRAL),
            candidate("red", "#E02030"),
            candidate("blue", "#204FD0"),
        )
        catalog = wanted + (candidate("green", "#159447"),)
        result = recommend_basic_filaments(
            colors_for(wanted),
            np.ones(4),
            catalog=catalog,
            max_candidates=8,
        )

        self.assertEqual(set(result.candidate_ids), {item.id for item in wanted})
        self.assertAlmostEqual(result.mean_delta_e76, 0.0, places=10)
        self.assertAlmostEqual(result.p90_delta_e76, 0.0, places=10)
        self.assertAlmostEqual(result.coverage_fraction, 1.0)
        self.assertAlmostEqual(result.confidence, 1.0)

    def test_skin_candidate_is_selected_when_skin_is_a_required_endpoint(self) -> None:
        wanted = (
            candidate("black", "#111111", CATEGORY_NEUTRAL),
            candidate("white", "#F4F4F4", CATEGORY_NEUTRAL),
            candidate("red", "#E32636"),
            candidate("skin", "#F2C6A0", CATEGORY_SKIN),
        )
        catalog = wanted + (
            candidate("blue", "#2453C7"),
            candidate("green", "#159447"),
        )
        target = colors_for(wanted)
        weights = np.asarray((1.0, 1.0, 1.0, 8.0))

        result = recommend_basic_filaments(
            target,
            weights,
            catalog=catalog,
            max_candidates=8,
        )

        self.assertIn("skin", result.candidate_ids)
        self.assertEqual(set(result.candidate_ids), {item.id for item in wanted})

    def test_auto_allowed_false_and_intermediate_are_hard_excluded(self) -> None:
        catalog = (
            candidate("black", "#111111", CATEGORY_NEUTRAL),
            candidate("white", "#F5F5F5", CATEGORY_NEUTRAL),
            candidate("red", "#E32636"),
            candidate("blue", "#2453C7"),
            candidate(
                "forbidden_exact",
                "#B77A8B",
                CATEGORY_PRIMARY,
                auto_allowed=False,
            ),
            # Intermediate is excluded even if an external catalog incorrectly
            # marks it as automatically selectable.
            candidate(
                "intermediate_exact",
                "#C7A78F",
                CATEGORY_INTERMEDIATE,
                auto_allowed=True,
            ),
        )
        target = np.asarray(
            (
                (0xB7, 0x7A, 0x8B),
                (0xC7, 0xA7, 0x8F),
                (0x11, 0x11, 0x11),
            )
        )
        result = recommend_basic_filaments(
            target,
            np.asarray((20.0, 20.0, 1.0)),
            catalog=catalog,
            max_candidates=8,
        )

        self.assertNotIn("forbidden_exact", result.candidate_ids)
        self.assertNotIn("intermediate_exact", result.candidate_ids)
        self.assertEqual(
            set(result.candidate_ids), {"black", "white", "red", "blue"}
        )

    def test_metrics_alternatives_and_usage_are_complete(self) -> None:
        wanted = (
            candidate("black", "#111111", CATEGORY_NEUTRAL),
            candidate("white", "#F5F5F5", CATEGORY_NEUTRAL),
            candidate("red", "#E32636"),
            candidate("blue", "#2453C7"),
        )
        catalog = wanted + (candidate("green", "#159447"),)
        result = recommend_basic_filaments(
            colors_for(wanted),
            np.asarray((4.0, 3.0, 2.0, 1.0)),
            catalog=catalog,
            alternative_count=2,
            max_candidates=8,
        )

        self.assertEqual(result.candidate_pool_size, 5)
        self.assertEqual(result.evaluated_combinations, 5)
        self.assertEqual(len(result.alternatives), 2)
        self.assertEqual(len(result.palette_hex), 16)
        self.assertEqual(len(result.usage), 16)
        self.assertAlmostEqual(
            sum(state.weight_fraction for state in result.usage), 1.0
        )
        self.assertAlmostEqual(sum(result.base_usage_fractions), 1.0)
        self.assertTrue(0.0 <= result.mean_delta_e76)
        self.assertTrue(0.0 <= result.p90_delta_e76)
        self.assertTrue(0.0 <= result.coverage_fraction <= 1.0)
        self.assertTrue(0.0 <= result.confidence <= 1.0)

    def test_catalog_order_does_not_change_tie_breaking_or_result(self) -> None:
        catalog = (
            candidate("black", "#111111", CATEGORY_NEUTRAL),
            candidate("white", "#F5F5F5", CATEGORY_NEUTRAL),
            candidate("red", "#E32636"),
            candidate("blue", "#2453C7"),
            candidate("green", "#159447"),
        )
        target = colors_for(catalog[:4])
        first = recommend_basic_filaments(
            target,
            catalog=catalog,
            max_candidates=8,
        )
        second = recommend_basic_filaments(
            target,
            catalog=tuple(reversed(catalog)),
            max_candidates=8,
        )

        self.assertEqual(first.candidate_ids, second.candidate_ids)
        self.assertEqual(first.palette_hex, second.palette_hex)
        self.assertAlmostEqual(first.score, second.score, places=12)
        self.assertEqual(
            [alternative.candidate_ids for alternative in first.alternatives],
            [alternative.candidate_ids for alternative in second.alternatives],
        )

    def test_runtime_mixer_patch_is_used_after_recommender_import(self) -> None:
        catalog = (
            candidate("black", "#111111", CATEGORY_NEUTRAL),
            candidate("white", "#F5F5F5", CATEGORY_NEUTRAL),
            candidate("red", "#E32636"),
            candidate("blue", "#2453C7"),
        )
        original = mixer.mix_rgb8
        calls = []

        def runtime_mix(first, second, ratio=0.5):
            calls.append(float(ratio))
            return original(first, second, ratio)

        # Mirrors the release entrypoint installing the Orca cadence hotfix
        # after this recommender module has already been imported.
        with patch.object(mixer, "mix_rgb8", side_effect=runtime_mix):
            recommend_basic_filaments(
                colors_for(catalog),
                catalog=catalog,
                max_candidates=4,
            )

        self.assertTrue(calls)

    def test_expanded_catalog_keeps_red_black_and_light_gray_at_all_state_counts(
        self,
    ) -> None:
        target = np.asarray(
            (
                (220, 30, 45),
                (15, 15, 15),
                (205, 205, 205),
                (75, 75, 82),
            ),
            dtype=np.uint8,
        )
        weights = np.asarray((45.0, 25.0, 25.0, 5.0))
        balanced = map_catalog_to_curated_basics(self._expanded_catalog())

        self.assertEqual(len({item.hex_color for item in balanced}), len(balanced))
        for state_count in (16, 24, 32):
            with self.subTest(state_count=state_count):
                result = recommend_basic_filaments(
                    target,
                    weights,
                    catalog=balanced,
                    palette_state_count=state_count,
                    max_candidates=None,
                )
                chosen = np.asarray([item.rgb8 for item in result.candidates])
                self.assertTrue(np.any(np.max(chosen, axis=1) <= 40), result.physical_hex)
                self.assertTrue(
                    np.any(
                        (chosen[:, 0] >= 180)
                        & (chosen[:, 0] - chosen[:, 1] >= 100)
                    ),
                    result.physical_hex,
                )
                self.assertTrue(
                    np.any(
                        (np.min(chosen, axis=1) >= 180)
                        & (np.ptp(chosen, axis=1) <= 20)
                    ),
                    result.physical_hex,
                )
                self.assertGreaterEqual(result.coverage_fraction, 0.95)

    def test_basic_mapping_is_order_stable_and_excludes_changing_colorways(
        self,
    ) -> None:
        catalog = self._expanded_catalog() + (
            FilamentCandidate(
                "gray-triple",
                "Burnt Titanium Triple Color",
                "#7F8388",
                CATEGORY_PRIMARY,
                material="PLA",
                series="Triple Color PLA",
                color_name="Gray / Gold / Blue",
            ),
        )
        first = map_catalog_to_curated_basics(catalog)
        second = map_catalog_to_curated_basics(tuple(reversed(catalog)))

        self.assertEqual(
            tuple(item.hex_color for item in first),
            tuple(item.hex_color for item in second),
        )
        self.assertNotIn("gray-triple", {item.id for item in first})

    def test_real_database_multicolour_names_are_excluded_without_banning_single_magic(
        self,
    ) -> None:
        # These labels/series mirror records present in the bundled OFD
        # snapshot. Some are catalogued with an ordinary opaque finish, so the
        # automatic path must use their explicit colourway names as well.
        catalog = self._expanded_catalog() + (
            FilamentCandidate(
                "anycubic-dual-tricolor",
                "Anycubic / PLA Silk Dual-Tricolor / Black-Blue",
                "#7F8388",
                CATEGORY_PRIMARY,
                material="PLA",
                brand="Anycubic",
                series="PLA Silk Dual-Tricolor",
                color_name="Black-Blue",
            ),
            FilamentCandidate(
                "esun-magic-multi",
                "eSUN 3D / PLA-Silk Magic / Red+Gold",
                "#D52078",
                CATEGORY_PRIMARY,
                material="PLA",
                brand="eSUN 3D",
                series="PLA-Silk Magic",
                color_name="Red+Gold",
            ),
            FilamentCandidate(
                "esun-uv-change",
                "eSUN 3D / UV Change PLA UV Color Change / Red",
                "#F36C21",
                CATEGORY_PRIMARY,
                material="PLA",
                brand="eSUN 3D",
                series="UV Change PLA UV Color Change",
                color_name="Red",
            ),
            FilamentCandidate(
                "overture-six-color",
                "Overture / Matte PLA / 6-Color",
                "#F4D21F",
                CATEGORY_PRIMARY,
                material="PLA",
                brand="Overture",
                series="Matte PLA",
                color_name="6-Color",
            ),
            FilamentCandidate(
                "esun-magic-single-blue",
                "eSUN 3D / Dark Twinkling PLA Magic / Blue",
                "#2453C7",
                CATEGORY_PRIMARY,
                material="PLA",
                brand="eSUN 3D",
                series="Dark Twinkling PLA Magic",
                color_name="Blue",
            ),
        )

        mapped = map_catalog_to_curated_basics(catalog)
        selected_ids = {item.id for item in mapped}

        self.assertTrue(
            {
                "anycubic-dual-tricolor",
                "esun-magic-multi",
                "esun-uv-change",
                "overture-six-color",
            }.isdisjoint(selected_ids)
        )
        self.assertIn("esun-magic-single-blue", selected_ids)

    def test_basic_mapping_preserves_product_snapshot_identity(self) -> None:
        catalog = tuple(
            item
            for item in self._expanded_catalog()
            if item.id != "pla-red"
        ) + (
            FilamentCandidate(
                "measured-red-product",
                "Maker / PLA Basic / Signal Red",
                "#E32636",
                CATEGORY_PRIMARY,
                material="PLA",
                brand="Maker",
                series="PLA Basic",
                color_name="Signal Red",
                finish_class="標準/不透明",
                source_kind="measured",
                source_url="https://example.invalid/red",
                record_id="record-red",
                measurement_id="measurement-red",
            ),
        )

        mapped = map_catalog_to_curated_basics(catalog)
        selected = next(item for item in mapped if item.id == "measured-red-product")

        self.assertEqual(selected.category, CATEGORY_PRIMARY)
        self.assertEqual(selected.material, "PLA")
        self.assertEqual(selected.brand, "Maker")
        self.assertEqual(selected.series, "PLA Basic")
        self.assertEqual(selected.color_name, "Signal Red")
        self.assertEqual(selected.finish_class, "標準/不透明")
        self.assertEqual(selected.source_kind, "measured")
        self.assertEqual(selected.source_url, "https://example.invalid/red")
        self.assertEqual(selected.record_id, "record-red")
        self.assertEqual(selected.measurement_id, "measurement-red")

    def test_basic_mapping_rejects_too_few_constant_colors_and_mixed_materials(
        self,
    ) -> None:
        insufficient = (
            candidate("black", "#111111"),
            candidate("white", "#F5F5F5"),
            candidate("red", "#E32636"),
            FilamentCandidate(
                "gray-changing",
                "Gray Chameleon",
                "#7F8388",
                CATEGORY_PRIMARY,
                series="Color Changing",
            ),
        )
        with self.assertRaisesRegex(ValueError, "constant-colour"):
            map_catalog_to_curated_basics(insufficient)

        mixed = self._expanded_catalog() + (
            FilamentCandidate(
                "abs-black",
                "ABS Black",
                "#101010",
                CATEGORY_PRIMARY,
                material="ABS",
            ),
        )
        with self.assertRaisesRegex(ValueError, "one material"):
            map_catalog_to_curated_basics(mixed)

    def test_basic_mapping_never_crosses_pla_abs_or_petg(self) -> None:
        target = np.asarray(((220, 30, 45), (15, 15, 15), (205, 205, 205)))
        for material in ("PLA", "ABS", "PETG"):
            with self.subTest(material=material):
                balanced = map_catalog_to_curated_basics(
                    self._expanded_catalog(material)
                )
                result = recommend_basic_filaments(
                    target,
                    catalog=balanced,
                    max_candidates=None,
                )
                self.assertEqual({item.material for item in balanced}, {material})
                self.assertEqual(
                    {item.material for item in result.candidates}, {material}
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
