from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import MapperApp  # noqa: E402
from spectrum_mapper.models import ColorResult, MeshLevel  # noqa: E402
from spectrum_mapper import renderer  # noqa: E402


def _level() -> MeshLevel:
    vertices = np.asarray(
        [
            [-2.0, -1.0, -0.5],
            [3.0, -1.0, -0.5],
            [-2.0, 4.0, 6.0],
        ],
        dtype=np.float64,
    )
    return MeshLevel(
        vertices_unit=vertices,
        faces=np.asarray([[0, 1, 2]], dtype=np.int32),
        vertex_colors=np.zeros((3, 3), dtype=np.float64),
        areas_unit=np.ones(1, dtype=np.float64),
        neighbors=None,
    )


def _result() -> ColorResult:
    return ColorResult(
        tone_vertex_rgb=np.zeros((3, 3), dtype=np.float64),
        source_face_rgb=np.asarray([[0.8, 0.1, 0.1]], dtype=np.float64),
        palette_indices=np.asarray([0], dtype=np.int16),
        target_face_rgb=np.asarray([[0.1, 0.8, 0.1]], dtype=np.float64),
        delta_e=np.asarray([1.0], dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=np.zeros(16, dtype=np.int64),
        palette_area_fractions=np.zeros(16, dtype=np.float64),
        pink_area_fraction=0.0,
    )


class _Variable:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class PreviewDirectionTests(unittest.TestCase):
    def test_front_default_preserves_the_legacy_matrix(self) -> None:
        vertices = _level().vertices_unit
        np.testing.assert_array_equal(
            renderer._camera_mvp(vertices, (320, 240)),
            renderer._camera_mvp(vertices, (320, 240), "front"),
        )

    def test_six_named_views_have_distinct_finite_matrices(self) -> None:
        vertices = _level().vertices_unit
        matrices = [
            renderer._camera_mvp(vertices, (320, 240), direction)
            for direction in renderer.PREVIEW_DIRECTIONS
        ]
        self.assertTrue(all(np.isfinite(matrix).all() for matrix in matrices))
        fingerprints = {matrix.astype(np.float32).tobytes() for matrix in matrices}
        self.assertEqual(len(fingerprints), 6)

    def test_unknown_direction_fails_closed(self) -> None:
        with self.assertRaisesRegex(renderer.RendererError, "Unknown preview direction"):
            renderer._camera_mvp(_level().vertices_unit, (320, 240), "diagonal")

    def test_pair_passes_one_direction_to_source_target_and_face_ids(self) -> None:
        image = Image.new("RGB", (32, 40), (0, 0, 0))
        face_ids = np.full((40, 32), -1, dtype=np.int32)
        with (
            patch.object(renderer, "_create_context", return_value=object()),
            patch.object(
                renderer,
                "_render_with_context",
                side_effect=(image, image.copy()),
            ) as render_color,
            patch.object(
                renderer,
                "_render_front_face_ids_with_context",
                return_value=face_ids,
            ) as render_ids,
            patch.object(renderer, "_release"),
        ):
            pair = renderer.render_front_preview_pair(
                _level(), _result(), size=(32, 40), direction="right"
            )

        self.assertIs(pair.face_ids, face_ids)
        self.assertEqual(
            [call.kwargs["direction"] for call in render_color.call_args_list],
            ["right", "right"],
        )
        self.assertEqual(render_ids.call_args.kwargs["direction"], "right")

    def test_gui_direction_change_schedules_one_immediate_pair_refresh(self) -> None:
        app = SimpleNamespace(
            preview_direction_var=_Variable("top"),
            prepared=object(),
            _schedule_preview=Mock(),
        )
        MapperApp._on_preview_direction_changed(app)
        app._schedule_preview.assert_called_once_with(immediate=True)

    def test_gui_invalid_direction_returns_to_front(self) -> None:
        app = SimpleNamespace(
            preview_direction_var=_Variable("diagonal"),
            prepared=None,
            _schedule_preview=Mock(),
        )
        MapperApp._on_preview_direction_changed(app)
        self.assertEqual(app.preview_direction_var.get(), "front")
        app._schedule_preview.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
