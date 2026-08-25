from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import mixer
from spectrum_mapper.engine import (
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


if __name__ == "__main__":
    unittest.main()
