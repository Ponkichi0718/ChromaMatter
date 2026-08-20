from __future__ import annotations

import unittest

import numpy as np
import smooth_paint

from spectrum_mapper import mixer
from spectrum_mapper.models import ColorResult, MeshLevel
from spectrum_mapper.palette_usage import (
    analyze_palette_usage,
    estimate_base_filament_contributions,
    focus_palette_state,
    palette_state_base_weights,
)


def _level() -> MeshLevel:
    return MeshLevel(
        vertices_unit=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
                [2.0, 0.0, 0.0],
                [2.0, 1.0, 0.0],
            ],
            dtype=np.float64,
        ),
        faces=np.asarray(
            [[0, 1, 2], [1, 3, 2], [1, 4, 3], [4, 5, 3]],
            dtype=np.int32,
        ),
        vertex_colors=np.full((6, 3), 0.5, dtype=np.float64),
        areas_unit=np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float64),
        neighbors=None,
        face_part_ids=np.asarray([0, 0, 1, 1], dtype=np.int16),
        part_names=("left", "right"),
        part_keys=("left", "right"),
    )


def _colors() -> ColorResult:
    source = np.full((4, 3), 0.6, dtype=np.float64)
    target = np.asarray(
        [
            [0.02, 0.02, 0.02],
            [0.45, 0.20, 0.10],
            [0.50, 0.25, 0.10],
            [0.90, 0.10, 0.10],
        ],
        dtype=np.float64,
    )
    return ColorResult(
        tone_vertex_rgb=np.full((6, 3), 0.5, dtype=np.float64),
        source_face_rgb=source,
        palette_indices=np.asarray([0, 4, 4, 1], dtype=np.int8),
        target_face_rgb=target,
        delta_e=np.zeros(4, dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=np.zeros(32, dtype=np.int64),
        palette_area_fractions=np.zeros(32, dtype=np.float64),
        pink_area_fraction=0.0,
    )


class PaletteUsageTests(unittest.TestCase):
    def test_usage_accepts_the_upper_state_of_16_24_and_32_color_modes(self) -> None:
        indices = np.asarray([15, 23, 31, 0], dtype=np.int8)
        for configured_count, state, expected_area in (
            (16, 15, 100.0),
            (24, 23, 200.0),
            (32, 31, 300.0),
        ):
            with self.subTest(configured_count=configured_count):
                usage = analyze_palette_usage(
                    _level(),
                    indices,
                    state,
                    10.0,
                )
                self.assertEqual(usage.face_count, 1)
                self.assertAlmostEqual(usage.area_mm2, expected_area)
                self.assertAlmostEqual(sum(palette_state_base_weights(state)), 1.0)

    def test_usage_is_scoped_to_selected_part_and_real_height(self) -> None:
        usage = analyze_palette_usage(
            _level(),
            np.asarray([0, 4, 4, 1], dtype=np.int8),
            4,
            10.0,
            part_id=0,
        )
        self.assertEqual(usage.face_count, 1)
        self.assertEqual(usage.scope_face_count, 2)
        self.assertAlmostEqual(usage.face_fraction, 0.5)
        self.assertAlmostEqual(usage.area_mm2, 200.0)
        self.assertAlmostEqual(usage.scope_area_mm2, 300.0)
        self.assertAlmostEqual(usage.area_fraction, 2.0 / 3.0)

    def test_state_recipe_exposes_effective_base_share(self) -> None:
        self.assertEqual(palette_state_base_weights(0), (1.0, 0.0, 0.0, 0.0))
        weights = palette_state_base_weights(4)
        np.testing.assert_allclose(weights, (2.0 / 3.0, 1.0 / 3.0, 0.0, 0.0))

    def test_requested_ratio_is_reported_as_effective_orca_cadence(self) -> None:
        # A requested 60% B cannot be printed continuously.  Orca turns it
        # into one A layer followed by two B layers, so diagnostics must show
        # the actual 1:2 physical cadence rather than the requested slider.
        weights = palette_state_base_weights(4, [60] * 6, [67] * 6)
        np.testing.assert_allclose(
            weights,
            (1.0 / 3.0, 2.0 / 3.0, 0.0, 0.0),
        )

    def test_surface_shell_reports_actual_black_partner_core_and_outer_share(self) -> None:
        output = mixer.black_output_ratio_preset(0)
        weights = palette_state_base_weights(
            5,  # state 6: F1 black + F3 partner
            [33] * 6,
            [67] * 6,
            output,
            surface_shell_enabled=True,
            physical_hex=["#111111", "#FFFFFF", "#E32636", "#7A4A32"],
        )
        # Corrected black remains 20%; the partner owns one complete outer
        # wall and the non-black remainder of the equal-width inner core.
        np.testing.assert_allclose(weights, (0.2, 0.0, 0.8, 0.0))

    def test_surface_shell_nonblack_pair_preserves_legacy_total_share(self) -> None:
        weights = palette_state_base_weights(
            7,  # state 8: F2 + F3 B33%
            [33] * 6,
            [67] * 6,
            mixer.black_output_ratio_preset(0),
            surface_shell_enabled=True,
            physical_hex=["#111111", "#FFFFFF", "#E32636", "#7A4A32"],
        )
        np.testing.assert_allclose(weights, (0.0, 2.0 / 3.0, 1.0 / 3.0, 0.0))

    def test_surface_estimate_uses_effective_cadence_for_adaptive_leaves(self) -> None:
        tree = smooth_paint.PaintNode.branch(
            (
                smooth_paint.PaintNode(4),
                smooth_paint.PaintNode(4),
                smooth_paint.PaintNode(1),
                smooth_paint.PaintNode(1),
            )
        )
        contributions = estimate_base_filament_contributions(
            _level(),
            np.asarray([0, 4, 4, 1], dtype=np.int8),
            10.0,
            [60] * 6,
            [67] * 6,
            part_id=0,
            adaptive_trees={1: tree},
        )
        # The scoped surface is one third F1, one third F2 and one third of
        # state 4.  State 4's requested 60% cadence is physically 1:2, making
        # the total effective contribution F1=4/9 and F2=5/9.
        np.testing.assert_allclose(
            contributions,
            (4.0 / 9.0, 5.0 / 9.0, 0.0, 0.0),
        )

    def test_surface_weighted_base_estimate_uses_all_states(self) -> None:
        contributions = estimate_base_filament_contributions(
            _level(),
            np.asarray([0, 4, 4, 1], dtype=np.int8),
            10.0,
            part_id=0,
        )
        np.testing.assert_allclose(
            contributions,
            (7.0 / 9.0, 2.0 / 9.0, 0.0, 0.0),
        )
        self.assertAlmostEqual(sum(contributions), 1.0)

    def test_adaptive_leaves_replace_root_area_in_usage_and_estimate(self) -> None:
        tree = smooth_paint.PaintNode.branch(
            (
                smooth_paint.PaintNode(4),
                smooth_paint.PaintNode(4),
                smooth_paint.PaintNode(1),
                smooth_paint.PaintNode(1),
            )
        )
        usage = analyze_palette_usage(
            _level(),
            np.asarray([0, 4, 4, 1], dtype=np.int8),
            4,
            10.0,
            part_id=0,
            adaptive_trees={1: tree},
        )
        self.assertEqual(usage.face_count, 1)
        self.assertAlmostEqual(usage.area_mm2, 100.0)
        self.assertEqual(usage.adaptive_root_count, 1)
        self.assertEqual(usage.adaptive_leaf_count, 4)
        self.assertEqual(usage.selected_adaptive_root_count, 1)
        self.assertEqual(usage.selected_adaptive_leaf_count, 2)

        contributions = estimate_base_filament_contributions(
            _level(),
            np.asarray([0, 4, 4, 1], dtype=np.int8),
            10.0,
            part_id=0,
            adaptive_trees={1: tree},
        )
        np.testing.assert_allclose(
            contributions,
            (5.0 / 9.0, 4.0 / 9.0, 0.0, 0.0),
        )

    def test_focus_is_display_only_and_scoped(self) -> None:
        level = _level()
        original = _colors()
        before = original.target_face_rgb.copy()
        focused = focus_palette_state(original, level, 4, part_id=0)

        self.assertIs(focused.palette_indices, original.palette_indices)
        self.assertIs(focused.source_face_rgb, original.source_face_rgb)
        np.testing.assert_array_equal(original.target_face_rgb, before)
        self.assertGreater(float(focused.target_face_rgb[1, 1]), 0.20)
        # The same state on another part remains muted because recipes can be
        # different for each part palette.
        self.assertLess(float(focused.target_face_rgb[2].max()), 0.20)
        self.assertLess(float(focused.target_face_rgb[0].max()), 0.20)

    def test_invalid_shapes_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            analyze_palette_usage(_level(), np.zeros(3), 0, 10.0)
        with self.assertRaises(ValueError):
            palette_state_base_weights(32)


if __name__ == "__main__":
    unittest.main()
