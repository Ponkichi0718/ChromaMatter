from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import ColorResult, MeshLevel  # noqa: E402
from spectrum_mapper.renderer import (  # noqa: E402
    RendererError,
    _effective_shaded,
    overlay_active_part_outline,
    render_front_preview,
    render_front_preview_pair,
)


RENDER_SIZE = (96, 120)
BACKGROUND = (9, 12, 17)


def _two_part_level() -> MeshLevel:
    # Both triangles face the established -Y front camera.
    vertices = np.asarray(
        [
            [-1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [-1.0, 0.0, 1.0],
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    faces = np.asarray([[0, 1, 2], [1, 3, 4]], dtype=np.int32)
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=np.zeros((len(vertices), 3), dtype=np.float64),
        areas_unit=np.ones(len(faces), dtype=np.float64),
        neighbors=None,
        face_part_ids=np.asarray([0, 1], dtype=np.int16),
        part_names=("left", "right"),
        part_keys=("part-left", "part-right"),
    )


def _color_result() -> ColorResult:
    return ColorResult(
        tone_vertex_rgb=np.zeros((5, 3), dtype=np.float64),
        source_face_rgb=np.asarray(
            [[0.82, 0.08, 0.10], [0.08, 0.18, 0.82]], dtype=np.float64
        ),
        palette_indices=np.asarray([2, 7], dtype=np.int16),
        target_face_rgb=np.asarray(
            [[0.18, 0.82, 0.22], [0.82, 0.70, 0.08]], dtype=np.float64
        ),
        delta_e=np.asarray([1.5, 2.5], dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=np.zeros(16, dtype=np.int64),
        palette_area_fractions=np.zeros(16, dtype=np.float64),
        pink_area_fraction=0.0,
    )


class FixedFrontPreviewPairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # The production build includes ModernGL, but source-only test runners
        # may intentionally omit it. Keep the rest of the unit suite usable in
        # that environment while exercising real GPU pixels when available.
        try:
            render_front_preview_pair(
                _two_part_level(),
                _color_result(),
                size=(32, 40),
                background=BACKGROUND,
            )
        except RendererError as exc:
            raise unittest.SkipTest(str(exc)) from exc

    def test_no_selection_is_pixel_identical_to_two_legacy_front_renders(self) -> None:
        level = _two_part_level()
        result = _color_result()
        legacy_source = render_front_preview(
            level,
            result,
            mode="source",
            size=RENDER_SIZE,
            background=BACKGROUND,
        )
        legacy_target = render_front_preview(
            level,
            result,
            mode="target",
            size=RENDER_SIZE,
            background=BACKGROUND,
        )

        pair = render_front_preview_pair(
            level,
            result,
            size=RENDER_SIZE,
            background=BACKGROUND,
            active_part_id=None,
        )

        np.testing.assert_array_equal(np.asarray(pair.source), np.asarray(legacy_source))
        np.testing.assert_array_equal(np.asarray(pair.target), np.asarray(legacy_target))
        self.assertEqual(pair.face_ids.shape, (RENDER_SIZE[1], RENDER_SIZE[0]))
        self.assertEqual(pair.face_ids.dtype, np.dtype(np.int32))
        self.assertEqual(set(np.unique(pair.face_ids)), {-1, 0, 1})

    def test_selection_outlines_both_images_without_changing_color_data(self) -> None:
        level = _two_part_level()
        result = _color_result()
        color_snapshots = {
            name: np.asarray(getattr(result, name)).copy()
            for name in (
                "tone_vertex_rgb",
                "source_face_rgb",
                "palette_indices",
                "target_face_rgb",
                "delta_e",
                "palette_face_counts",
                "palette_area_fractions",
            )
        }
        plain = render_front_preview_pair(
            level,
            result,
            size=RENDER_SIZE,
            background=BACKGROUND,
        )

        outlined = render_front_preview_pair(
            level,
            result,
            size=RENDER_SIZE,
            background=BACKGROUND,
            active_part_id=0,
        )

        expected_source = overlay_active_part_outline(
            plain.source,
            outlined.face_ids,
            level.face_part_ids,
            0,
        )
        expected_target = overlay_active_part_outline(
            plain.target,
            outlined.face_ids,
            level.face_part_ids,
            0,
        )
        np.testing.assert_array_equal(
            np.asarray(outlined.source), np.asarray(expected_source)
        )
        np.testing.assert_array_equal(
            np.asarray(outlined.target), np.asarray(expected_target)
        )
        self.assertGreater(
            int(
                np.count_nonzero(
                    np.any(
                        np.asarray(outlined.source) != np.asarray(plain.source),
                        axis=2,
                    )
                )
            ),
            0,
        )
        for name, before in color_snapshots.items():
            with self.subTest(color_array=name):
                np.testing.assert_array_equal(np.asarray(getattr(result, name)), before)

    def test_unknown_active_part_is_rejected(self) -> None:
        with self.assertRaisesRegex(RendererError, "unknown active part ID"):
            render_front_preview_pair(
                _two_part_level(),
                _color_result(),
                size=RENDER_SIZE,
                background=BACKGROUND,
                active_part_id=9,
            )

    def test_baked_illustration_target_is_unlit_but_source_stays_lit(self) -> None:
        ordinary = _color_result()
        self.assertTrue(_effective_shaded(ordinary, "source", True))
        self.assertTrue(_effective_shaded(ordinary, "target", True))
        ordinary.tone_face_rgb_flat = True
        self.assertTrue(_effective_shaded(ordinary, "source", True))
        self.assertFalse(_effective_shaded(ordinary, "target", True))
        self.assertFalse(_effective_shaded(ordinary, "source", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
