from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import mixer
from spectrum_mapper.engine import (
    _flat_four_selected_face_neighbors,
    _recover_flat_four_chromatic_shadow_regions,
    _recover_flat_four_chromatic_shadows,
    recolor_level,
    recolor_level_parts,
    srgb_to_lab,
)
from spectrum_mapper.models import (
    COLOR_MODE_FLAT_FOUR,
    COLOR_MODE_FULL_SPECTRUM,
    MeshLevel,
    PaletteSettings,
    ToneSettings,
)
from spectrum_mapper.parts import assignment_palette_rgb_table


NEUTRAL_AND_RED = ["#121212", "#BCBFC2", "#818184", "#EB3B41"]


def _level(colors: list[list[float]], part_keys: tuple[str, ...] = ()) -> MeshLevel:
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    vertex_colors: list[list[float]] = []
    for index, color in enumerate(colors):
        offset = 3 * index
        vertices.extend(
            (
                [3.0 * index, 0.0, 0.0],
                [3.0 * index + 1.0, 0.0, 0.0],
                [3.0 * index, 1.0, 0.0],
            )
        )
        faces.append([offset, offset + 1, offset + 2])
        vertex_colors.extend((color, color, color))
    return MeshLevel(
        vertices_unit=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int32),
        vertex_colors=np.asarray(vertex_colors, dtype=np.float64),
        areas_unit=np.full(len(faces), 0.5, dtype=np.float64),
        neighbors=None,
        face_part_ids=(
            np.arange(len(faces), dtype=np.int16)
            if part_keys
            else np.empty(0, dtype=np.int16)
        ),
        part_names=part_keys,
        part_keys=part_keys,
    )


def _region_level(
    colors: list[list[float]],
    *,
    face_part_ids: np.ndarray | None = None,
    hard_boundary: bool = False,
) -> MeshLevel:
    """Return two connected centre faces with four boundary supporters."""

    if len(colors) != 6:
        raise AssertionError("region fixture requires six face colours")
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    vertex_colors: list[list[float]] = []
    for index, color in enumerate(colors):
        offset = len(vertices)
        x = float(index * 2)
        if hard_boundary and index == 2:
            triangle = ([x, 0.0, 0.0], [x + 1.0, 0.0, 0.0], [x, 0.0, 1.0])
        else:
            triangle = ([x, 0.0, 0.0], [x + 1.0, 0.0, 0.0], [x, 1.0, 0.0])
        vertices.extend(triangle)
        faces.append([offset, offset + 1, offset + 2])
        vertex_colors.extend((color, color, color))
    return MeshLevel(
        vertices_unit=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int32),
        vertex_colors=np.asarray(vertex_colors, dtype=np.float64),
        areas_unit=np.full(6, 0.01, dtype=np.float64),
        neighbors=np.asarray(
            [
                [1, 2, 3],
                [0, 4, 5],
                [0, -1, -1],
                [0, -1, -1],
                [1, -1, -1],
                [1, -1, -1],
            ],
            dtype=np.int32,
        ),
        face_part_ids=(
            np.empty(0, dtype=np.int16)
            if face_part_ids is None
            else np.asarray(face_part_ids, dtype=np.int16)
        ),
    )


def _panel_level(
    colors: list[list[float]],
    *,
    open_edge: bool = False,
    hard_internal_face: bool = False,
) -> MeshLevel:
    """Return four candidate faces in a closed ring plus four boundary faces."""

    if len(colors) != 8:
        raise AssertionError("panel fixture requires eight face colours")
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    vertex_colors: list[list[float]] = []
    for index, color in enumerate(colors):
        offset = len(vertices)
        x = float(index * 2)
        if hard_internal_face and index == 2:
            triangle = (
                [x, 0.0, 0.0],
                [x + 1.0, 0.0, 0.0],
                [x, 0.0, 1.0],
            )
        else:
            triangle = (
                [x, 0.0, 0.0],
                [x + 1.0, 0.0, 0.0],
                [x, 1.0, 0.0],
            )
        vertices.extend(triangle)
        faces.append([offset, offset + 1, offset + 2])
        vertex_colors.extend((color, color, color))
    neighbors = np.asarray(
        [
            [1, 3, 4],
            [0, 2, 5],
            [1, 3, 6],
            [2, 0, 7],
            [0, -1, -1],
            [1, -1, -1],
            [2, -1, -1],
            [3, -1, -1],
        ],
        dtype=np.int32,
    )
    if open_edge:
        neighbors[0, 2] = -1
    return MeshLevel(
        vertices_unit=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int32),
        vertex_colors=np.asarray(vertex_colors, dtype=np.float64),
        areas_unit=np.full(8, 0.01, dtype=np.float64),
        neighbors=neighbors,
    )


def _dark_core_level(colors: list[list[float]]) -> MeshLevel:
    """Return a four-face colour ring surrounding one two-edge dark core."""

    if len(colors) != 8:
        raise AssertionError("dark-core fixture requires eight face colours")
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    vertex_colors: list[list[float]] = []
    for index, color in enumerate(colors):
        offset = len(vertices)
        x = float(index * 2)
        vertices.extend(
            (
                [x, 0.0, 0.0],
                [x + 1.0, 0.0, 0.0],
                [x, 1.0, 0.0],
            )
        )
        faces.append([offset, offset + 1, offset + 2])
        vertex_colors.extend((color, color, color))
    return MeshLevel(
        vertices_unit=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int32),
        vertex_colors=np.asarray(vertex_colors, dtype=np.float64),
        areas_unit=np.full(8, 0.01, dtype=np.float64),
        neighbors=np.asarray(
            [
                [1, 3, 4],
                [0, 2, 4],
                [1, 3, 5],
                [2, 0, 6],
                [0, 1, 7],
                [2, -1, -1],
                [3, -1, -1],
                [4, -1, -1],
            ],
            dtype=np.int32,
        ),
    )


class FlatChromaticShadowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tone = ToneSettings(white_point=1.0, smoothing=False)

    def _ordinary_nearest_physical(
        self, color: list[float], palette: PaletteSettings
    ) -> int:
        face_lab = srgb_to_lab(np.asarray([color], dtype=np.float64))
        palette_lab = srgb_to_lab(assignment_palette_rgb_table(palette)[:4])
        return int(
            np.argmin(np.sum((face_lab[:, None, :] - palette_lab) ** 2, axis=2))
        )

    def test_shadowed_red_recovers_from_ordinary_black_to_physical_red(self) -> None:
        shadowed_red = [0.18, 0.04, 0.04]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        self.assertEqual(
            self._ordinary_nearest_physical(shadowed_red, palette), 0
        )
        result = recolor_level(
            _level([shadowed_red]), 100.0, self.tone, palette
        )

        self.assertEqual(int(result.palette_indices[0]), 3)
        self.assertEqual(int(result.palette_face_counts[4:].sum()), 0)

    def test_true_neutral_black_and_tiny_warm_bias_remain_black(self) -> None:
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )
        level = _level(
            [
                [0.12, 0.12, 0.12],
                [0.13, 0.095, 0.095],
            ]
        )

        result = recolor_level(level, 100.0, self.tone, palette)

        np.testing.assert_array_equal(
            result.palette_indices, np.asarray([0, 0], dtype=np.int8)
        )

    def test_recovery_uses_the_best_enabled_chromatic_physical_slot(self) -> None:
        shadowed_blue = [0.03, 0.06, 0.20]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=["#121212", "#245BDB", "#818184", "#BCBFC2"],
        )

        self.assertEqual(
            self._ordinary_nearest_physical(shadowed_blue, palette), 0
        )
        result = recolor_level(
            _level([shadowed_blue]), 100.0, self.tone, palette
        )

        self.assertEqual(int(result.palette_indices[0]), 1)

    def test_disabled_chromatic_slot_is_not_recovered(self) -> None:
        enabled = [True] * mixer.PALETTE_STATE_COUNT
        enabled[3] = False
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
            enabled_states=enabled,
        )

        result = recolor_level(
            _level([[0.18, 0.04, 0.04]]),
            100.0,
            self.tone,
            palette,
        )

        self.assertEqual(int(result.palette_indices[0]), 0)

    def test_full_spectrum_keeps_ordinary_nearest_mixed_state(self) -> None:
        shadowed_red = [0.18, 0.04, 0.04]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            physical_hex=list(NEUTRAL_AND_RED),
        )
        with patch(
            "spectrum_mapper.engine._recover_flat_four_chromatic_shadows",
            side_effect=AssertionError("Flat Four recovery entered Full Spectrum"),
        ):
            result = recolor_level(
                _level([shadowed_red]), 100.0, self.tone, palette
            )

        self.assertGreaterEqual(int(result.palette_indices[0]), 4)

    def test_part_palette_recovery_stays_local_and_generalized(self) -> None:
        red_palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )
        blue_palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=["#121212", "#245BDB", "#818184", "#BCBFC2"],
        )
        level = _level(
            [[0.18, 0.04, 0.04], [0.03, 0.06, 0.20]],
            ("body", "accent"),
        )

        result = recolor_level_parts(
            level,
            100.0,
            self.tone,
            red_palette,
            {"accent": blue_palette},
        )

        np.testing.assert_array_equal(
            result.palette_indices, np.asarray([3, 1], dtype=np.int8)
        )

    def test_recovery_is_identical_across_the_large_model_chunk_boundary(self) -> None:
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )
        palette_rgb = assignment_palette_rgb_table(palette)
        palette_lab = srgb_to_lab(palette_rgb)
        face_rgb = np.repeat(
            np.asarray([[0.18, 0.04, 0.04]], dtype=np.float64),
            25_001,
            axis=0,
        )
        face_rgb = np.vstack((face_rgb, [[0.12, 0.12, 0.12]]))
        indices = np.zeros(len(face_rgb), dtype=np.int8)

        original_ptp = np.ptp
        scanned_chunk_sizes: list[int] = []

        def bounded_ptp(values, *args, **kwargs):
            scanned_chunk_sizes.append(len(values))
            self.assertLessEqual(len(values), 25_000)
            return original_ptp(values, *args, **kwargs)

        with patch(
            "spectrum_mapper.engine.np.ptp",
            side_effect=bounded_ptp,
        ):
            recovered, count = _recover_flat_four_chromatic_shadows(
                indices,
                face_rgb,
                srgb_to_lab(face_rgb),
                palette_rgb,
                palette_lab,
                np.asarray(palette.enabled_states, dtype=bool),
            )

        self.assertEqual(count, 25_001)
        self.assertTrue(np.all(recovered[:-1] == 3))
        self.assertEqual(int(recovered[-1]), 0)
        self.assertGreaterEqual(len(scanned_chunk_sizes), 2)

    def test_coherent_recovered_patch_is_not_smoothed_back_to_black(self) -> None:
        shadowed_red = [0.18, 0.04, 0.04]
        black = [0.12, 0.12, 0.12]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )
        tone = ToneSettings(white_point=1.0, smoothing=True)

        result = recolor_level(
            _region_level([shadowed_red, shadowed_red, black, black, black, black]),
            1.0,
            tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:2], [3, 3])
        self.assertEqual(result.smoothed_faces, 0)

    def test_isolated_recovered_speck_remains_eligible_for_smoothing(self) -> None:
        shadowed_red = [0.18, 0.04, 0.04]
        black = [0.12, 0.12, 0.12]
        level = _region_level(
            [shadowed_red, black, black, black, black, black]
        )
        level.neighbors[0] = [2, 3, 4]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            level,
            1.0,
            ToneSettings(white_point=1.0, smoothing=True),
            palette,
        )

        self.assertEqual(int(result.palette_indices[0]), 0)
        self.assertGreaterEqual(result.smoothed_faces, 1)

    def test_subthreshold_dark_red_region_recovers_from_red_boundary(self) -> None:
        weak_red = [0.10, 0.035, 0.035]
        red = [0.75, 0.10, 0.10]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )
        self.assertEqual(self._ordinary_nearest_physical(weak_red, palette), 0)

        result = recolor_level(
            _region_level([weak_red, weak_red, red, red, red, red]),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices, [3] * 6)

    def test_warm_biased_black_region_is_not_promoted(self) -> None:
        warm_black = [0.13, 0.095, 0.095]
        red = [0.75, 0.10, 0.10]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _region_level([warm_black, warm_black, red, red, red, red]),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:2], [0, 0])

    def test_region_recovery_requires_a_dominant_red_boundary(self) -> None:
        weak_red = [0.10, 0.035, 0.035]
        red = [0.75, 0.10, 0.10]
        black = [0.12, 0.12, 0.12]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _region_level([weak_red, weak_red, red, red, black, black]),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:2], [0, 0])

    def test_coherent_dark_panel_can_prove_its_colour_without_red_boundary(
        self,
    ) -> None:
        weak_red = [0.10, 0.035, 0.035]
        black = [0.12, 0.12, 0.12]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _panel_level([weak_red] * 4 + [black] * 4),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:4], [3] * 4)
        np.testing.assert_array_equal(result.palette_indices[4:], [0] * 4)

    def test_self_supported_panel_needs_multiple_strict_colour_faces(
        self,
    ) -> None:
        strict_red = [0.10, 0.035, 0.035]
        relaxed_red = [0.08, 0.025, 0.025]
        black = [0.12, 0.12, 0.12]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _panel_level(
                [strict_red] + [relaxed_red] * 3 + [black] * 4
            ),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:4], [0] * 4)

    def test_proven_panel_grows_into_a_two_edge_dark_red_core(self) -> None:
        weak_red = [0.10, 0.035, 0.035]
        deepest_red = [0.04, 0.015, 0.015]
        black = [0.12, 0.12, 0.12]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _dark_core_level(
                [weak_red] * 4 + [deepest_red] + [black] * 3
            ),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:5], [3] * 5)
        np.testing.assert_array_equal(result.palette_indices[5:], [0] * 3)

    def test_proven_panel_does_not_grow_into_warm_black(self) -> None:
        weak_red = [0.10, 0.035, 0.035]
        warm_black = [0.13, 0.095, 0.095]
        black = [0.12, 0.12, 0.12]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _dark_core_level(
                [weak_red] * 4 + [warm_black] + [black] * 3
            ),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:4], [3] * 4)
        self.assertEqual(int(result.palette_indices[4]), 0)

    def test_self_supported_panel_rejects_an_open_edge(self) -> None:
        weak_red = [0.10, 0.035, 0.035]
        black = [0.12, 0.12, 0.12]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _panel_level(
                [weak_red] * 4 + [black] * 4,
                open_edge=True,
            ),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:4], [0] * 4)

    def test_hard_internal_crease_splits_self_supported_panel(self) -> None:
        weak_red = [0.10, 0.035, 0.035]
        black = [0.12, 0.12, 0.12]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _panel_level(
                [weak_red] * 4 + [black] * 4,
                hard_internal_face=True,
            ),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:4], [0] * 4)

    def test_sparse_selected_adjacency_matches_full_closed_mesh(self) -> None:
        faces = np.asarray(
            [
                [0, 2, 1],
                [0, 1, 3],
                [1, 2, 3],
                [2, 0, 3],
            ],
            dtype=np.int32,
        )
        selected = np.asarray([0, 2], dtype=np.int32)

        sparse = _flat_four_selected_face_neighbors(faces, 4, selected)

        self.assertIsNotNone(sparse)
        expected_sets = (
            {1, 2, 3},
            {0, 1, 3},
        )
        for row, expected in zip(sparse, expected_sets, strict=True):
            self.assertEqual(set(int(value) for value in row), expected)

    def test_region_recovery_uses_sparse_adjacency_above_full_build_limit(
        self,
    ) -> None:
        vertices = np.asarray(
            [
                [float(x), float(y), 0.0]
                for y in range(4)
                for x in range(4)
            ],
            dtype=np.float64,
        )
        faces: list[list[int]] = []
        for y in range(3):
            for x in range(3):
                lower_left = y * 4 + x
                lower_right = lower_left + 1
                upper_left = lower_left + 4
                upper_right = upper_left + 1
                faces.extend(
                    (
                        [lower_left, lower_right, upper_right],
                        [lower_left, upper_right, upper_left],
                    )
                )
        triangles = np.asarray(faces, dtype=np.int32)
        weak_red = np.asarray([0.10, 0.035, 0.035])
        red = np.asarray([0.75, 0.10, 0.10])
        face_rgb = np.repeat(red[None, :], len(triangles), axis=0)
        centre = np.asarray([8, 9], dtype=np.int32)
        face_rgb[centre] = weak_red
        indices = np.full(len(triangles), 3, dtype=np.int8)
        indices[centre] = 0
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )
        palette_rgb = assignment_palette_rgb_table(palette)
        palette_lab = srgb_to_lab(palette_rgb)

        with patch(
            "spectrum_mapper.engine._FLAT_TOPOLOGY_BUILD_FACE_LIMIT",
            1,
        ):
            recovered, count, protected = (
                _recover_flat_four_chromatic_shadow_regions(
                    indices,
                    face_rgb,
                    srgb_to_lab(face_rgb),
                    palette_rgb,
                    palette_lab,
                    np.asarray(palette.enabled_states, dtype=bool),
                    None,
                    vertices,
                    triangles,
                )
            )

        self.assertEqual(count, 2)
        np.testing.assert_array_equal(recovered[centre], [3, 3])
        np.testing.assert_array_equal(protected[centre], [True, True])

    def test_single_dark_red_notch_with_two_red_edges_is_closed(self) -> None:
        weak_red = [0.10, 0.025, 0.025]
        red = [0.75, 0.10, 0.10]
        black = [0.12, 0.12, 0.12]
        level = _region_level([weak_red, black, red, red, black, black])
        level.neighbors[0] = [2, 3, 1]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(level, 1.0, self.tone, palette)

        self.assertEqual(int(result.palette_indices[0]), 3)

    def test_single_notch_with_only_one_red_edge_stays_black(self) -> None:
        weak_red = [0.10, 0.025, 0.025]
        red = [0.75, 0.10, 0.10]
        black = [0.12, 0.12, 0.12]
        level = _region_level([weak_red, black, red, black, black, black])
        level.neighbors[0] = [2, 3, 1]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(level, 1.0, self.tone, palette)

        self.assertEqual(int(result.palette_indices[0]), 0)

    def test_single_notch_on_an_open_edge_stays_black(self) -> None:
        weak_red = [0.10, 0.025, 0.025]
        red = [0.75, 0.10, 0.10]
        level = _region_level([weak_red, red, red, red, red, red])
        level.neighbors[0] = [2, 3, -1]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(level, 1.0, self.tone, palette)

        self.assertEqual(int(result.palette_indices[0]), 0)

    def test_single_true_black_between_red_faces_stays_black(self) -> None:
        black = [0.12, 0.12, 0.12]
        red = [0.75, 0.10, 0.10]
        level = _region_level([black, red, red, red, red, red])
        level.neighbors[0] = [2, 3, 1]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(level, 1.0, self.tone, palette)

        self.assertEqual(int(result.palette_indices[0]), 0)

    def test_single_warm_black_between_red_faces_stays_black(self) -> None:
        warm_black = [0.13, 0.095, 0.095]
        red = [0.75, 0.10, 0.10]
        level = _region_level([warm_black, red, red, red, red, red])
        level.neighbors[0] = [2, 3, 1]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(level, 1.0, self.tone, palette)

        self.assertEqual(int(result.palette_indices[0]), 0)

    def test_region_recovery_does_not_cross_part_boundaries(self) -> None:
        weak_red = [0.10, 0.035, 0.035]
        red = [0.75, 0.10, 0.10]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _region_level(
                [weak_red, weak_red, red, red, red, red],
                face_part_ids=np.asarray([0, 0, 1, 1, 1, 1]),
            ),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:2], [0, 0])

    def test_region_recovery_rejects_a_hard_surface_boundary(self) -> None:
        weak_red = [0.10, 0.035, 0.035]
        red = [0.75, 0.10, 0.10]
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(NEUTRAL_AND_RED),
        )

        result = recolor_level(
            _region_level(
                [weak_red, weak_red, red, red, red, red],
                hard_boundary=True,
            ),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices[:2], [0, 0])

    def test_full_spectrum_never_enters_region_shadow_recovery(self) -> None:
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            physical_hex=list(NEUTRAL_AND_RED),
        )
        with patch(
            "spectrum_mapper.engine._recover_flat_four_chromatic_shadow_regions",
            side_effect=AssertionError("Flat region recovery entered Full Spectrum"),
        ):
            recolor_level(
                _level([[0.10, 0.035, 0.035]]),
                1.0,
                self.tone,
                palette,
            )


if __name__ == "__main__":
    unittest.main()
