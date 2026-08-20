from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import AppSettings, MeshLevel, PaletteSettings
from spectrum_mapper.parts import (
    DEFAULT_PART_KEY,
    PartPaletteError,
    build_part_palette_rgb_tables,
    face_rgb_from_local_states,
    face_rgb_from_tables,
    palette_identity,
    palettes_are_identical,
    palettes_are_print_compatible,
    plan_palette_groups,
    print_palette_identity,
    resolve_palette_for_part_key,
    resolve_part_palette_settings,
    validate_part_layout,
)


def make_level(
    face_part_ids: list[int] | np.ndarray,
    part_keys: tuple[str, ...],
    *,
    face_count: int | None = None,
) -> MeshLevel:
    ids = np.asarray(face_part_ids, dtype=np.int32)
    count = len(ids) if face_count is None else face_count
    return MeshLevel(
        vertices_unit=np.zeros((1, 3), dtype=np.float32),
        faces=np.zeros((count, 3), dtype=np.int32),
        vertex_colors=np.zeros((1, 3), dtype=np.float32),
        areas_unit=np.zeros(count, dtype=np.float64),
        neighbors=None,
        face_part_ids=ids,
        part_keys=part_keys,
    )


def make_palette(
    physical: list[str],
    *,
    primary: list[int] | None = None,
    secondary: list[int] | None = None,
    enabled: list[bool] | None = None,
    overrides: list[str | None] | None = None,
) -> PaletteSettings:
    return PaletteSettings(
        physical_hex=physical,
        enabled_states=enabled if enabled is not None else [True] * 16,
        mix_hex_overrides=overrides if overrides is not None else [None] * 6,
        mix_ratios_b=primary if primary is not None else [33] * 6,
        secondary_mix_ratios_b=secondary if secondary is not None else [67] * 6,
    )


GLOBAL_PHYSICAL = ["#101010", "#F0F0F0", "#B0B0B0", "#F2B5C8"]
BLUE_PHYSICAL = ["#081020", "#F8FCFF", "#2878D0", "#79D8FF"]


class PartLayoutTests(unittest.TestCase):
    def test_old_mesh_without_part_metadata_falls_back_to_whole_model(self) -> None:
        level = make_level([], (), face_count=3)

        layout = validate_part_layout(level)

        self.assertEqual(layout.part_keys, (DEFAULT_PART_KEY,))
        np.testing.assert_array_equal(layout.face_part_ids, [0, 0, 0])
        self.assertFalse(layout.face_part_ids.flags.writeable)

    def test_missing_keys_are_deterministically_synthesized_from_ids(self) -> None:
        level = make_level([2, 0, 2], ())

        layout = validate_part_layout(level)

        self.assertEqual(
            layout.part_keys, ("__part_0__", "__part_1__", "__part_2__")
        )
        np.testing.assert_array_equal(layout.face_part_ids, [2, 0, 2])

    def test_multiple_explicit_parts_cannot_guess_missing_face_ids(self) -> None:
        level = make_level([], ("0:body", "1:eyes"), face_count=2)

        with self.assertRaisesRegex(PartPaletteError, "face_part_ids are required"):
            validate_part_layout(level)

    def test_invalid_part_metadata_is_rejected(self) -> None:
        cases = (
            make_level([0], ("",)),
            make_level([0], ("same", "same")),
            make_level([-1], ("part",)),
            make_level([1], ("only",)),
            make_level([0], ("part",), face_count=2),
        )
        for level in cases:
            with self.subTest(level=level):
                with self.assertRaises(PartPaletteError):
                    validate_part_layout(level)


class PaletteResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.global_palette = make_palette(GLOBAL_PHYSICAL)
        self.blue_palette = make_palette(BLUE_PHYSICAL)
        self.level = make_level([0, 1, 1], ("0:body", "1:coat"))

    def test_exact_override_and_global_fallback_are_resolved_in_part_order(self) -> None:
        settings = AppSettings(
            palette=self.global_palette,
            part_palettes={"1:coat": self.blue_palette},
        )

        resolved = resolve_part_palette_settings(settings, self.level)

        self.assertIs(resolved[0], self.global_palette)
        self.assertIs(resolved[1], self.blue_palette)
        self.assertIs(
            resolve_palette_for_part_key(settings, "not-present"),
            self.global_palette,
        )

    def test_unknown_override_key_is_ignored_without_changing_inputs(self) -> None:
        settings = AppSettings(
            palette=self.global_palette,
            part_palettes={"old:key": self.blue_palette},
        )
        before = settings.to_dict()

        resolved = resolve_part_palette_settings(settings, self.level)

        self.assertEqual(resolved, (self.global_palette, self.global_palette))
        self.assertEqual(settings.to_dict(), before)

    def test_malformed_resolved_palette_is_rejected(self) -> None:
        bad = make_palette(GLOBAL_PHYSICAL)
        bad.mix_ratios_b = [33] * 5
        settings = AppSettings(
            palette=self.global_palette,
            part_palettes={"1:coat": bad},
        )

        with self.assertRaisesRegex(PartPaletteError, "six integer ratios"):
            resolve_part_palette_settings(settings, self.level)


class PartRgbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.global_palette = make_palette(GLOBAL_PHYSICAL)
        self.blue_palette = make_palette(BLUE_PHYSICAL)
        self.settings = AppSettings(
            palette=self.global_palette,
            part_palettes={"1:coat": self.blue_palette},
        )
        self.level = make_level([0, 1, 1, 0], ("0:body", "1:coat"))

    def test_builds_one_16_state_rgb_table_per_part(self) -> None:
        tables = build_part_palette_rgb_tables(self.settings, self.level)

        self.assertEqual(tables.shape, (2, 32, 3))
        expected_global = np.asarray(
            [[int(value[index : index + 2], 16) for index in (1, 3, 5)]
             for value in GLOBAL_PHYSICAL],
            dtype=np.float64,
        ) / 255.0
        expected_blue = np.asarray(
            [[int(value[index : index + 2], 16) for index in (1, 3, 5)]
             for value in BLUE_PHYSICAL],
            dtype=np.float64,
        ) / 255.0
        np.testing.assert_allclose(tables[0, :4], expected_global)
        np.testing.assert_allclose(tables[1, :4], expected_blue)

    def test_local_state_ids_are_interpreted_inside_each_part_palette(self) -> None:
        states = np.asarray([0, 0, 3, 2], dtype=np.int16)
        tables = build_part_palette_rgb_tables(self.settings, self.level)

        expected = tables[[0, 1, 1, 0], states]
        actual_from_tables = face_rgb_from_tables(self.level, states, tables)
        actual_direct = face_rgb_from_local_states(
            self.settings, self.level, states
        )

        np.testing.assert_allclose(actual_from_tables, expected)
        np.testing.assert_allclose(actual_direct, expected)

    def test_state_and_table_validation_prevents_silent_wrong_colours(self) -> None:
        tables = build_part_palette_rgb_tables(self.settings, self.level)
        invalid_states = (
            np.asarray([0, 1, 2], dtype=np.int16),
            np.asarray([0.0, 1.0, 2.0, 3.0]),
            np.asarray([0, 1, 32, 3], dtype=np.int16),
        )
        for states in invalid_states:
            with self.subTest(states=states):
                with self.assertRaises(PartPaletteError):
                    face_rgb_from_tables(self.level, states, tables)

        with self.assertRaisesRegex(PartPaletteError, "shape"):
            face_rgb_from_tables(
                self.level,
                np.zeros(4, dtype=np.int16),
                tables[:1],
            )
        invalid_tables = tables.copy()
        invalid_tables[0, 0, 0] = np.nan
        with self.assertRaisesRegex(PartPaletteError, "0..1"):
            face_rgb_from_tables(
                self.level,
                np.zeros(4, dtype=np.int16),
                invalid_tables,
            )


class PaletteIdentityAndGroupingTests(unittest.TestCase):
    def test_complete_and_print_identities_have_deliberate_semantics(self) -> None:
        first = make_palette(GLOBAL_PHYSICAL)
        second = make_palette(
            [value.lower().removeprefix("#") for value in GLOBAL_PHYSICAL],
            enabled=[False] + [True] * 15,
            overrides=["#123456"] + [None] * 5,
        )

        self.assertNotEqual(palette_identity(first), palette_identity(second))
        self.assertFalse(palettes_are_identical(first, second))
        self.assertEqual(print_palette_identity(first), print_palette_identity(second))
        self.assertTrue(palettes_are_print_compatible(first, second))

    def test_print_equivalent_parts_use_one_job(self) -> None:
        local = make_palette(
            GLOBAL_PHYSICAL,
            enabled=[True] * 15 + [False],
            overrides=[None, "#345678", None, None, None, None],
        )
        level = make_level([0, 1], ("0:first", "1:second"))
        settings = AppSettings(
            palette=make_palette(GLOBAL_PHYSICAL),
            part_palettes={"1:second": local},
        )

        plan = plan_palette_groups(settings, level)

        self.assertEqual(plan.mode, "one-job")
        self.assertTrue(plan.one_job)
        self.assertFalse(plan.requires_separate_jobs)
        self.assertEqual(plan.part_group_ids, (0, 0))
        self.assertEqual(plan.groups[0].part_indices, (0, 1))

    def test_different_print_palettes_form_stable_first_seen_groups(self) -> None:
        global_palette = make_palette(GLOBAL_PHYSICAL)
        blue_palette = make_palette(BLUE_PHYSICAL)
        global_clone = make_palette([value.lower() for value in GLOBAL_PHYSICAL])
        level = make_level([0, 1, 2], ("body", "coat", "boots"))
        settings = AppSettings(
            palette=global_palette,
            part_palettes={"coat": blue_palette, "boots": global_clone},
        )

        plan = plan_palette_groups(settings, level)

        self.assertEqual(plan.mode, "per-group")
        self.assertFalse(plan.one_job)
        self.assertTrue(plan.requires_separate_jobs)
        self.assertEqual(plan.part_group_ids, (0, 1, 0))
        self.assertEqual(len(plan.groups), 2)
        self.assertEqual(plan.groups[0].group_id, 0)
        self.assertEqual(plan.groups[0].part_indices, (0, 2))
        self.assertEqual(plan.groups[0].part_keys, ("body", "boots"))
        self.assertEqual(plan.groups[1].part_indices, (1,))

    def test_different_mix_ratios_require_separate_groups(self) -> None:
        alternate = make_palette(GLOBAL_PHYSICAL, primary=[25] * 6)
        level = make_level([0, 1], ("first", "second"))
        settings = AppSettings(
            palette=make_palette(GLOBAL_PHYSICAL),
            part_palettes={"second": alternate},
        )

        plan = plan_palette_groups(settings, level)

        self.assertEqual(plan.mode, "per-group")
        self.assertEqual(plan.part_group_ids, (0, 1))


if __name__ == "__main__":
    unittest.main()
