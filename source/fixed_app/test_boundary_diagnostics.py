from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import ColorResult
from spectrum_mapper.paint_gui import PaintEditorWindow


def _colors() -> ColorResult:
    return ColorResult(
        tone_vertex_rgb=np.zeros((3, 3), dtype=np.float64),
        source_face_rgb=np.zeros((3, 3), dtype=np.float64),
        palette_indices=np.zeros(3, dtype=np.int8),
        target_face_rgb=np.full((3, 3), 0.25, dtype=np.float64),
        delta_e=np.zeros(3, dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=np.zeros(16, dtype=np.int64),
        palette_area_fractions=np.zeros(16, dtype=np.float64),
        pink_area_fraction=0.0,
    )


class BoundaryDiagnosticPaintTests(unittest.TestCase):
    def test_face_id_validation_is_sorted_unique_and_in_range(self) -> None:
        result = PaintEditorWindow._validated_diagnostic_face_ids(
            [2, -1, 1, 2, 99], 3
        )

        np.testing.assert_array_equal(result, [1, 2])
        self.assertEqual(result.dtype, np.int32)

    def test_problem_faces_render_red_and_matched_faces_yellow(self) -> None:
        editor = PaintEditorWindow.__new__(PaintEditorWindow)
        original = _colors()
        editor._display_colors = original
        editor._diagnostic_enabled = True
        editor._matched_boundary_face_ids = np.asarray([0, 1], dtype=np.int32)
        editor._unmatched_boundary_face_ids = np.asarray([1], dtype=np.int32)

        rendered = editor._diagnostic_render_colors()

        self.assertIsNot(rendered, original)
        np.testing.assert_allclose(rendered.target_face_rgb[0], [1.0, 0.64, 0.03])
        np.testing.assert_allclose(rendered.target_face_rgb[1], [1.0, 0.02, 0.08])
        np.testing.assert_allclose(rendered.target_face_rgb[2], [0.25, 0.25, 0.25])
        np.testing.assert_allclose(original.target_face_rgb, 0.25)

    def test_disabled_diagnostics_reuse_the_original_color_result(self) -> None:
        editor = PaintEditorWindow.__new__(PaintEditorWindow)
        original = _colors()
        editor._display_colors = original
        editor._diagnostic_enabled = False
        editor._matched_boundary_face_ids = np.asarray([0], dtype=np.int32)
        editor._unmatched_boundary_face_ids = np.asarray([1], dtype=np.int32)

        self.assertIs(editor._diagnostic_render_colors(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
