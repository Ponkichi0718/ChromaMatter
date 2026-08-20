from __future__ import annotations

from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.renderer import (  # noqa: E402
    InteractiveMeshRenderer,
    RendererError,
    overlay_active_part_outline,
    resolve_view_appearance,
)


class ViewAppearanceTests(unittest.TestCase):
    def test_auto_uses_light_canvas_for_a_predominantly_dark_model(self) -> None:
        colors = np.asarray(
            [[0.02, 0.01, 0.03], [0.14, 0.02, 0.10], [0.18, 0.04, 0.22]],
            dtype=np.float32,
        )
        appearance = resolve_view_appearance("auto", colors)
        self.assertEqual(appearance.requested_theme, "auto")
        self.assertEqual(appearance.resolved_theme, "light")
        self.assertEqual(appearance.background, (232, 236, 242))
        self.assertIsNotNone(appearance.model_luminance)

    def test_auto_uses_dark_canvas_for_a_bright_model(self) -> None:
        colors = np.asarray([[240, 230, 238], [255, 255, 255]], dtype=np.uint8)
        appearance = resolve_view_appearance("auto", colors)
        self.assertEqual(appearance.resolved_theme, "dark")
        self.assertEqual(appearance.background, (9, 12, 17))

    def test_explicit_neutral_theme_is_not_overridden(self) -> None:
        appearance = resolve_view_appearance(
            "neutral", np.zeros((3, 3), dtype=np.float32)
        )
        self.assertEqual(appearance.resolved_theme, "neutral")
        self.assertEqual(appearance.background, (112, 117, 125))

    def test_invalid_theme_and_colour_shape_are_rejected(self) -> None:
        with self.assertRaises(RendererError):
            resolve_view_appearance("sepia")
        with self.assertRaises(RendererError):
            resolve_view_appearance("auto", np.zeros((3, 4), dtype=np.float32))


class ActivePartOutlineTests(unittest.TestCase):
    def test_outline_marks_silhouette_and_shared_part_boundary_only(self) -> None:
        image = Image.new("RGB", (8, 7), (20, 30, 40))
        image.info["keep"] = "metadata"
        face_ids = np.full((7, 8), -1, dtype=np.int32)
        face_ids[1:6, 1:4] = 0
        face_ids[1:6, 4:7] = 1
        outlined = overlay_active_part_outline(
            image,
            face_ids,
            np.asarray([0, 1], dtype=np.int16),
            0,
            color=(10, 220, 250),
            thickness=1,
        )
        pixels = np.asarray(outlined)
        np.testing.assert_array_equal(pixels[3, 2], (20, 30, 40))
        np.testing.assert_array_equal(pixels[3, 3], (10, 220, 250))
        np.testing.assert_array_equal(pixels[3, 4], (10, 220, 250))
        np.testing.assert_array_equal(pixels[3, 6], (20, 30, 40))
        self.assertEqual(outlined.info["keep"], "metadata")
        np.testing.assert_array_equal(np.asarray(image)[3, 3], (20, 30, 40))

    def test_no_active_or_occluded_part_returns_an_unchanged_copy(self) -> None:
        image = Image.new("RGB", (4, 4), (2, 3, 4))
        face_ids = np.full((4, 4), -1, dtype=np.int32)
        parts = np.asarray([0], dtype=np.int16)
        for active in (None, 0):
            result = overlay_active_part_outline(image, face_ids, parts, active)
            self.assertIsNot(result, image)
            np.testing.assert_array_equal(np.asarray(result), np.asarray(image))

    def test_invalid_pick_map_is_rejected(self) -> None:
        image = Image.new("RGB", (4, 4))
        with self.assertRaises(RendererError):
            overlay_active_part_outline(
                image,
                np.zeros((3, 4), dtype=np.int32),
                np.asarray([0]),
                0,
            )


class RendererAppearanceStateTests(unittest.TestCase):
    @staticmethod
    def _state_only_renderer() -> InteractiveMeshRenderer:
        renderer = object.__new__(InteractiveMeshRenderer)
        renderer._owner_thread = threading.get_ident()
        renderer._closed = False
        renderer._context = object()
        renderer._background = (9, 12, 17)
        renderer._face_part_ids = np.asarray([0, 0, 1], dtype=np.int32)
        renderer._active_part_id = None
        renderer._active_part_accent = (36, 224, 255)
        renderer._active_part_outline_thickness = 2
        renderer._highlight_active_part_in_source = False
        return renderer

    def test_background_changes_without_allocating_a_new_renderer(self) -> None:
        renderer = self._state_only_renderer()
        self.assertTrue(renderer.set_background((232, 236, 242)))
        self.assertEqual(renderer.background, (232, 236, 242))
        self.assertFalse(renderer.set_background((232, 236, 242)))

    def test_active_part_state_accepts_only_existing_stable_part_ids(self) -> None:
        renderer = self._state_only_renderer()
        self.assertTrue(
            renderer.set_active_part(
                1, color=(0, 102, 224), thickness=3, highlight_source=True
            )
        )
        self.assertEqual(renderer._active_part_id, 1)
        self.assertFalse(
            renderer.set_active_part(
                1, color=(0, 102, 224), thickness=3, highlight_source=True
            )
        )
        with self.assertRaises(RendererError):
            renderer.set_active_part(5)

    def test_active_outline_never_forces_pick_pass_during_fast_rotation_frame(self) -> None:
        class Uniform:
            value = None

            def write(self, _data) -> None:
                return None

        class Program:
            def __init__(self) -> None:
                self.uniforms = {"mvp": Uniform(), "shade_strength": Uniform()}

            def __getitem__(self, name: str) -> Uniform:
                return self.uniforms[name]

        renderer = self._state_only_renderer()
        renderer._vertices = np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float32,
        )
        renderer._size = (32, 32)
        renderer._active_part_id = 0
        renderer._program = Program()
        renderer._pick_program = Program()
        renderer._visibility_program = None
        renderer._visibility_pick_program = None
        renderer._source_vao = object()
        renderer._target_vao = object()
        renderer.update_colors = Mock()
        renderer._prepare_draw_state = Mock()
        renderer._render_color_image = Mock(
            return_value=Image.new("RGB", renderer._size, (9, 12, 17))
        )
        renderer._render_face_id_map = Mock(
            side_effect=AssertionError("fast frame must not render face IDs")
        )
        with patch(
            "spectrum_mapper.renderer._orbit_camera_mvp",
            return_value=(
                np.eye(4, dtype=np.float32),
                SimpleNamespace(),
                1.0,
            ),
        ):
            frame = renderer.render(
                object(),
                render_source=False,
                render_target=True,
                render_face_ids=False,
            )
        self.assertIsNone(frame.face_ids)
        renderer._render_face_id_map.assert_not_called()


if __name__ == "__main__":
    unittest.main()
