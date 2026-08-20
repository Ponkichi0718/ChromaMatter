from __future__ import annotations

import queue
import pathlib
import sys
import types
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rotation_hotfix


class Camera:
    def __init__(self, yaw: float, pitch: float = 0.0, zoom: float = 1.0):
        self.yaw = yaw
        self.yaw_degrees = yaw
        self.pitch_degrees = pitch
        self.zoom = zoom

    def __eq__(self, other):
        return (
            isinstance(other, Camera)
            and self.yaw == other.yaw
            and self.pitch_degrees == other.pitch_degrees
            and self.zoom == other.zoom
        )


class Event:
    def __init__(self, x=0, y=0, delta=0):
        self.x = x
        self.y = y
        self.delta = delta


class Canvas:
    def __init__(self):
        self.bindings = {}
        self.cursor = None

    def bind(self, sequence, callback, add=None):
        self.bindings[sequence] = (callback, add)

    def configure(self, **kwargs):
        if "cursor" in kwargs:
            self.cursor = kwargs["cursor"]


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class HintLabel:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = str(kwargs["text"])


class Window:
    def __init__(self):
        self.calls = []
        self.cancelled = []

    def after(self, delay, callback, *args):
        token = f"after-{len(self.calls)}"
        self.calls.append((delay, callback, args, token))
        return token

    def after_cancel(self, token):
        self.cancelled.append(token)

    def winfo_exists(self):
        return True

    def bind(self, sequence, callback, add=None):
        self.calls.append(("bind", sequence, callback, add))

    def winfo_children(self):
        return []


class Frame:
    def __init__(self, camera, *, target="pixels", face_ids=None):
        self.camera = camera
        self.target = target
        self.face_ids = face_ids
        self.pixels_per_unit = 123.0


def new_editor_class(renderer_module=None):
    class Editor:
        def _schedule_render(self, *, immediate=False):
            raise AssertionError("unpatched")

        def _request_render(self):
            raise AssertionError("unpatched")

        def _poll_worker(self):
            raise AssertionError("original poller is not used in these tests")

        def _on_left_press(self, _event):
            pass

        def _on_right_press(self, _event):
            self._drag_mode = "orbit"

        def _on_left_release(self, _event):
            self._drag_mode = None

        def _on_right_release(self, _event):
            self._drag_mode = None

        def _orbit_to(self, x, y):
            dx = x - self._drag_last[0]
            dy = y - self._drag_last[1]
            self._drag_last = (x, y)
            self.camera = Camera(
                self.camera.yaw_degrees + dx * 0.38,
                self.camera.pitch_degrees - dy * 0.32,
                self.camera.zoom,
            )
            self._schedule_render()

        def _on_mousewheel(self, event):
            factor = 1.12 if event.delta > 0 else 1.0 / 1.12
            self.camera = Camera(
                self.camera.yaw_degrees,
                self.camera.pitch_degrees,
                self.camera.zoom * factor,
            )
            self._schedule_render()

        @staticmethod
        def _point_inside(event, mapping):
            x, y, width, height, _ow, _oh = mapping
            return x <= event.x < x + width and y <= event.y < y + height

    rotation_hotfix.apply_rotation_hotfix(
        types.SimpleNamespace(PaintEditorWindow=Editor), renderer_module
    )
    return Editor


def new_editor(renderer_module=None):
    editor = new_editor_class(renderer_module)()
    editor.window = Window()
    editor.canvas = Canvas()
    editor._close_requested = False
    editor._closing = False
    editor._job_running = False
    editor._pending_render = False
    editor._render_after = None
    editor._render_dirty = False
    editor._work_queue = queue.Queue()
    editor._rotation_hotfix_inflight = None
    editor._rotation_hotfix_force_final = False
    editor._rotation_hotfix_active = False
    editor.camera = Camera(0)
    editor.face_ids = np.asarray([[10]], dtype=np.int32)
    editor._hotfix_pick_camera = Camera(0)
    editor.draw_states = []
    editor._draw_canvas = lambda: editor.draw_states.append(editor._render_dirty)
    editor._start_next_pending = lambda: None
    editor._drag_mode = None
    editor._drag_last = None
    editor.target_mapping = (100, 20, 400, 300, 640, 640)
    return editor


class RotationHotfixTests(unittest.TestCase):
    def test_editor_init_binds_all_middle_button_events(self):
        class Editor:
            def __init__(self):
                self.canvas = Canvas()
                self.window = Window()

            def _poll_worker(self):
                pass

            def _on_left_press(self, _event):
                pass

            def _on_right_press(self, _event):
                pass

            def _on_left_release(self, _event):
                pass

            def _on_right_release(self, _event):
                pass

        rotation_hotfix.apply_rotation_hotfix(
            types.SimpleNamespace(PaintEditorWindow=Editor)
        )
        editor = Editor()

        self.assertEqual(
            set(editor.canvas.bindings),
            {"<ButtonPress-2>", "<B2-Motion>", "<ButtonRelease-2>"},
        )
        self.assertTrue(
            all(add == "+" for _callback, add in editor.canvas.bindings.values())
        )

    def test_editor_init_prefers_exposed_controls_hint_label(self):
        class NoWalkWindow(Window):
            def winfo_children(self):
                raise AssertionError("legacy widget traversal must not run")

        class Editor:
            def __init__(self):
                self.canvas = Canvas()
                self.window = NoWalkWindow()
                self.controls_hint_label = HintLabel()

            def _poll_worker(self):
                pass

            def _on_left_press(self, _event):
                pass

            def _on_right_press(self, _event):
                pass

            def _on_left_release(self, _event):
                pass

            def _on_right_release(self, _event):
                pass

        rotation_hotfix.apply_rotation_hotfix(
            types.SimpleNamespace(PaintEditorWindow=Editor)
        )
        editor = Editor()

        self.assertIn("ホイールドラッグ: 移動", editor.controls_hint_label.text)

    def test_editor_init_synchronizes_detached_help_hint_label(self):
        class NoWalkWindow(Window):
            def winfo_children(self):
                raise AssertionError("legacy widget traversal must not run")

        class Editor:
            def __init__(self):
                self.canvas = Canvas()
                self.window = NoWalkWindow()
                self.controls_hint_label = HintLabel()
                self.help_controls_hint_label = HintLabel()

            def _poll_worker(self):
                pass

            def _on_left_press(self, _event):
                pass

            def _on_right_press(self, _event):
                pass

            def _on_left_release(self, _event):
                pass

            def _on_right_release(self, _event):
                pass

        rotation_hotfix.apply_rotation_hotfix(
            types.SimpleNamespace(PaintEditorWindow=Editor)
        )
        editor = Editor()

        self.assertEqual(
            editor.controls_hint_label.text,
            editor.help_controls_hint_label.text,
        )
        self.assertIn("ホイールドラッグ: 移動", editor.help_controls_hint_label.text)

    def test_motion_uses_leading_throttle_without_repeated_cancel(self):
        editor = new_editor()
        editor._schedule_render()
        first_token = editor._render_after
        editor._schedule_render()
        editor._schedule_render()

        self.assertEqual(len(editor.window.calls), 1)
        self.assertEqual(editor._render_after, first_token)
        self.assertEqual(editor.window.cancelled, [])
        self.assertEqual(editor.window.calls[0][0], rotation_hotfix.THROTTLE_MS)

    def test_running_job_has_only_one_latest_pending_slot(self):
        editor = new_editor()
        editor._job_running = True
        editor._schedule_render()
        editor.camera = Camera(50)
        editor._schedule_render()

        self.assertTrue(editor._pending_render)
        self.assertEqual(editor.window.calls, [])

    def test_preview_render_never_requests_face_ids(self):
        editor = new_editor()
        editor._rotation_hotfix_active = True
        calls = []

        class Renderer:
            def render(self, _colors, **kwargs):
                calls.append(kwargs)
                return Frame(kwargs["camera"])

        editor._renderer = Renderer()
        editor._display_colors = object()

        def submit(kind, function):
            editor._job_running = True
            editor._work_queue.put((kind + "_done", function()))

        editor._submit = submit
        editor._request_render()

        self.assertFalse(calls[0]["render_face_ids"])

    def test_settled_color_only_render_reuses_ids_for_active_outline(self):
        from spectrum_mapper import renderer as renderer_module

        editor = new_editor(renderer_module)
        editor.face_ids = np.full((7, 8), -1, dtype=np.int32)
        editor.face_ids[1:6, 1:4] = 0
        editor.face_ids[1:6, 4:7] = 1
        editor._hotfix_pick_camera = editor.camera
        editor.level = types.SimpleNamespace(
            face_part_ids=np.empty(0, dtype=np.int16)
        )
        base = Image.new("RGB", (8, 7), (20, 30, 40))
        calls = []

        class Renderer:
            _active_part_id = 0
            _active_part_accent = (10, 220, 250)
            _active_part_outline_thickness = 1
            _face_part_ids = np.asarray((0, 1), dtype=np.int16)

            def render(self, _colors, **kwargs):
                calls.append(dict(kwargs))
                return renderer_module.InteractiveRenderFrame(
                    source=None,
                    target=base,
                    face_ids=None,
                    camera=kwargs["camera"],
                    pixels_per_unit=1.0,
                )

        editor._renderer = Renderer()
        editor._display_colors = object()
        completed = []
        editor._submit = lambda kind, work: completed.append((kind, work()))

        editor._request_render()

        self.assertFalse(calls[0]["render_face_ids"])
        _camera, frame = completed[0][1]
        self.assertIsNone(frame.face_ids)
        pixels = np.asarray(frame.target)
        np.testing.assert_array_equal(pixels[3, 3], (10, 220, 250))
        np.testing.assert_array_equal(pixels[3, 2], (20, 30, 40))

    def test_packaged_rotation_path_preserves_palette_usage_focus(self):
        editor = new_editor()
        editor._rotation_hotfix_active = True
        editor._palette_usage_focus_enabled = True
        editor._palette_usage_focus_state = 7
        editor.active_part_id = 2
        display_colors = object()
        diagnostic_colors = object()
        editor._display_colors = display_colors
        editor._diagnostic_render_colors = lambda: diagnostic_colors
        focus_calls = []
        render_calls = []

        class Renderer:
            def set_palette_usage_focus(self, state, *, part_id=None):
                focus_calls.append((state, part_id))

            def render(self, colors, **kwargs):
                render_calls.append((colors, kwargs))
                return Frame(kwargs["camera"])

        editor._renderer = Renderer()
        editor._submit = lambda _kind, function: function()

        editor._request_render()

        self.assertEqual(focus_calls, [(7, 2)])
        self.assertIs(render_calls[0][0], diagnostic_colors)
        self.assertFalse(render_calls[0][1]["render_face_ids"])

        editor._palette_usage_focus_enabled = False
        editor._request_render()
        self.assertEqual(focus_calls[-1], (None, 2))

    def test_stale_preview_is_shown_but_old_ids_stay_guarded(self):
        editor = new_editor()
        old_ids = editor.face_ids
        editor._rotation_hotfix_active = True
        editor.camera = Camera(20)
        frame = Frame(Camera(10), target="stale-colour", face_ids=None)

        rotation_hotfix._consume_rotation_render_done(
            editor, (Camera(10), frame)
        )

        self.assertEqual(editor.target_image, "stale-colour")
        self.assertIs(editor.face_ids, old_ids)
        self.assertEqual(editor._hotfix_pick_camera, Camera(0))
        self.assertTrue(editor._render_dirty)
        self.assertTrue(editor._pending_render)
        self.assertEqual(editor.draw_states, [True])

    def test_stale_frame_cannot_replace_face_ids(self):
        editor = new_editor()
        old_ids = editor.face_ids
        editor.camera = Camera(20)
        editor._rotation_hotfix_force_final = True
        stale_ids = np.asarray([[999]], dtype=np.int32)
        frame = Frame(Camera(10), target="stale-colour", face_ids=stale_ids)

        rotation_hotfix._consume_rotation_render_done(
            editor, (Camera(10), frame)
        )

        self.assertIs(editor.face_ids, old_ids)
        self.assertEqual(editor._hotfix_pick_camera, Camera(0))
        self.assertTrue(editor._render_dirty)
        self.assertTrue(editor._pending_render)

    def test_release_exact_frame_adopts_ids_and_unlocks_picker(self):
        editor = new_editor()
        editor.camera = Camera(30)
        editor._rotation_hotfix_force_final = True
        new_ids = np.asarray([[77]], dtype=np.int32)
        frame = Frame(Camera(30), target="final-colour", face_ids=new_ids)

        rotation_hotfix._consume_rotation_render_done(
            editor, (Camera(30), frame)
        )

        self.assertIs(editor.face_ids, new_ids)
        self.assertEqual(editor._hotfix_pick_camera, Camera(30))
        self.assertFalse(editor._render_dirty)
        self.assertFalse(editor._rotation_hotfix_force_final)
        self.assertEqual(editor.draw_states, [False])

    def test_right_release_forces_immediate_exact_id_render(self):
        editor = new_editor()
        editor._on_right_press(None)
        self.assertTrue(editor._rotation_hotfix_active)

        editor._on_right_release(None)

        self.assertFalse(editor._rotation_hotfix_active)
        self.assertTrue(editor._rotation_hotfix_force_final)
        self.assertTrue(editor._render_dirty)
        self.assertEqual(editor.window.calls[-1][0], 1)

    def test_middle_drag_pans_without_changing_orbit_or_zoom(self):
        editor = new_editor()
        editor.camera = Camera(27.0, -13.0, 2.4)

        editor._on_middle_press(Event(300, 150))
        editor._on_middle_motion(Event(340, 180))

        self.assertEqual(editor._drag_mode, "pan")
        self.assertTrue(editor._rotation_hotfix_active)
        self.assertTrue(editor._render_dirty)
        self.assertEqual(editor.camera.yaw_degrees, 27.0)
        self.assertEqual(editor.camera.pitch_degrees, -13.0)
        self.assertEqual(editor.camera.zoom, 2.4)
        self.assertAlmostEqual(editor.camera.pan_x, 0.1)
        self.assertAlmostEqual(editor.camera.pan_y, 0.1)
        self.assertEqual(editor.canvas.cursor, "fleur")
        self.assertEqual(editor.window.calls[-1][0], rotation_hotfix.THROTTLE_MS)

    def test_pan_normalizes_recovered_camera_for_exact_frame_equality(self):
        editor = new_editor()
        editor.camera = Camera(725.0, 90.0, 50.0)

        editor._on_middle_press(Event(300, 150))
        editor._on_middle_motion(Event(304, 153))

        self.assertEqual(editor.camera.yaw_degrees, 5.0)
        self.assertEqual(editor.camera.pitch_degrees, 84.0)
        self.assertEqual(editor.camera.zoom, 40.0)

    def test_middle_release_requires_one_final_exact_id_frame(self):
        editor = new_editor()
        editor._on_middle_press(Event(300, 150))
        editor._on_middle_motion(Event(320, 160))
        editor._on_middle_release(Event(320, 160))

        self.assertIsNone(editor._drag_mode)
        self.assertFalse(editor._rotation_hotfix_active)
        self.assertTrue(editor._rotation_hotfix_force_final)
        self.assertTrue(editor._render_dirty)
        self.assertEqual(editor.canvas.cursor, "arrow")
        self.assertEqual(editor.window.calls[-1][0], 1)

        calls = []

        class Renderer:
            def render(self, _colors, **kwargs):
                calls.append(kwargs)
                return Frame(kwargs["camera"], face_ids=np.asarray([[22]]))

        editor._renderer = Renderer()
        editor._display_colors = object()
        editor._submit = lambda _kind, function: function()
        editor._request_render()
        self.assertTrue(calls[0]["render_face_ids"])

    def test_busy_pan_coalesces_to_latest_camera_and_final_id_request(self):
        editor = new_editor()
        editor._job_running = True
        editor._on_middle_press(Event(300, 150))
        editor._on_middle_motion(Event(320, 160))
        editor._on_middle_motion(Event(340, 170))
        editor._on_middle_motion(Event(380, 200))
        editor._on_middle_release(Event(380, 200))

        self.assertTrue(editor._pending_render)
        self.assertEqual(editor.window.calls, [])
        self.assertAlmostEqual(editor.camera.pan_x, 0.2)
        self.assertAlmostEqual(editor.camera.pan_y, 1.0 / 6.0)
        self.assertTrue(editor._rotation_hotfix_force_final)
        self.assertTrue(editor._render_dirty)

    def test_middle_press_outside_model_panel_does_not_start_pan(self):
        editor = new_editor()
        editor._on_middle_press(Event(50, 150))

        self.assertIsNone(editor._drag_mode)
        self.assertFalse(editor._rotation_hotfix_active)
        self.assertFalse(editor._render_dirty)

    def test_zoom_and_orbit_keep_existing_pan(self):
        editor = new_editor()
        editor.camera = rotation_hotfix._PanCameraState(
            yaw_degrees=5.0,
            pitch_degrees=7.0,
            zoom=1.5,
            pan_x=0.2,
            pan_y=-0.15,
        )

        editor._on_mousewheel(Event(delta=120))
        editor._drag_last = (300, 170)
        editor._orbit_to(340, 170)

        self.assertAlmostEqual(editor.camera.pan_x, 0.2)
        self.assertAlmostEqual(editor.camera.pan_y, -0.15)
        self.assertAlmostEqual(editor.camera.zoom, 1.5 * 1.22)
        self.assertIsNotNone(editor.camera.orientation)
        self.assertFalse(
            np.allclose(
                editor.camera.orientation,
                rotation_hotfix._quaternion_from_yaw_pitch(5.0, 7.0),
            )
        )

    def test_inverted_orbit_uses_the_exact_inverse_arcball_delta(self):
        normal = new_editor()
        normal.camera = rotation_hotfix._PanCameraState(
            orientation=rotation_hotfix._IDENTITY_QUATERNION
        )
        normal.orbit_inverted_var = Variable(False)
        normal._drag_last = (300, 170)
        normal._orbit_to(370, 135)

        inverted = new_editor()
        inverted.camera = rotation_hotfix._PanCameraState(
            orientation=rotation_hotfix._IDENTITY_QUATERNION
        )
        inverted.orbit_inverted_var = Variable(True)
        inverted._drag_last = (300, 170)
        inverted._orbit_to(370, 135)

        normal_matrix = rotation_hotfix._quaternion_matrix(
            normal.camera.orientation
        )
        inverted_matrix = rotation_hotfix._quaternion_matrix(
            inverted.camera.orientation
        )
        self.assertFalse(np.allclose(normal_matrix, inverted_matrix))
        np.testing.assert_allclose(
            normal_matrix @ inverted_matrix,
            np.eye(3),
            atol=1e-12,
        )

    def test_arcball_crosses_the_old_pitch_stop(self):
        editor = new_editor()
        # The model panel is x=100..500, y=20..320.  Center-to-top is a
        # quarter turn which the old +/-79 degree Euler orbit could not reach.
        editor._drag_last = (300, 170)
        editor._orbit_to(300, 20)

        self.assertIsNotNone(editor.camera.orientation)
        self.assertGreater(abs(editor.camera.pitch_degrees), 84.0)
        matrix = rotation_hotfix._quaternion_matrix(editor.camera.orientation)
        np.testing.assert_allclose(matrix.T @ matrix, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(float(np.linalg.det(matrix)), 1.0, places=12)

    def test_four_quarter_turn_drags_complete_a_full_rotation(self):
        editor = new_editor()
        editor.camera = rotation_hotfix._PanCameraState(
            zoom=2.0,
            pan_x=0.125,
            pan_y=-0.25,
            orientation=rotation_hotfix._IDENTITY_QUATERNION,
        )

        for _index in range(4):
            editor._drag_last = (300, 170)
            editor._orbit_to(450, 170)

        np.testing.assert_allclose(
            editor.camera.orientation,
            rotation_hotfix._IDENTITY_QUATERNION,
            atol=1e-12,
        )
        self.assertEqual(editor.camera.zoom, 2.0)
        self.assertEqual(editor.camera.pan_x, 0.125)
        self.assertEqual(editor.camera.pan_y, -0.25)

    def test_arcball_projection_returns_the_exact_camera_for_picker_guard(self):
        vertices = np.asarray(
            [
                [-1.0, -2.0, -3.0],
                [1.0, 2.0, 3.0],
                [0.5, -1.0, 2.0],
            ],
            dtype=np.float64,
        )
        orientation = rotation_hotfix._quaternion_multiply(
            rotation_hotfix._quaternion_between(
                np.asarray((1.0, 0.0, 0.0)),
                np.asarray((0.0, 1.0, 0.0)),
            ),
            rotation_hotfix._quaternion_from_yaw_pitch(21.0, -11.0),
        )
        camera = rotation_hotfix._PanCameraState(
            yaw_degrees=12.0,
            pitch_degrees=34.0,
            zoom=1.4,
            pan_x=0.1,
            pan_y=-0.2,
            orientation=orientation,
        )

        mvp, returned, pixels_per_unit = rotation_hotfix._arcball_camera_mvp(
            vertices,
            (640, 480),
            camera,
            types.SimpleNamespace(),
        )

        self.assertIs(returned, camera)
        self.assertEqual(mvp.shape, (4, 4))
        self.assertTrue(np.isfinite(mvp).all())
        self.assertGreater(pixels_per_unit, 0.0)

    def test_pan_projection_moves_colour_and_picker_mvp_together(self):
        class Editor:
            def _poll_worker(self):
                pass

            def _on_left_press(self, _event):
                pass

            def _on_right_press(self, _event):
                pass

            def _on_left_release(self, _event):
                pass

            def _on_right_release(self, _event):
                pass

        base_mvp = np.eye(4, dtype=np.float32)

        def orbit(_vertices, _size, camera):
            clean = Camera(
                camera.yaw_degrees, camera.pitch_degrees, camera.zoom
            )
            return base_mvp, clean, 123.0

        fake_renderer = types.SimpleNamespace(_orbit_camera_mvp=orbit)
        # The recovered paint_gui module does not expose renderer as an
        # attribute. Production passes the actual renderer module explicitly.
        rotation_hotfix.apply_rotation_hotfix(
            types.SimpleNamespace(PaintEditorWindow=Editor),
            fake_renderer,
        )
        camera = rotation_hotfix._PanCameraState(
            yaw_degrees=1.0,
            pitch_degrees=2.0,
            zoom=3.0,
            pan_x=0.25,
            pan_y=0.10,
        )

        moved, clean, ppu = fake_renderer._orbit_camera_mvp(
            np.zeros((3, 3)), (640, 640), camera
        )

        self.assertAlmostEqual(float(moved[0, 3]), 0.5)
        self.assertAlmostEqual(float(moved[1, 3]), -0.2)
        self.assertEqual(clean, camera)
        self.assertEqual(ppu, 123.0)

        arcball_camera = rotation_hotfix._PanCameraState(
            zoom=1.25,
            pan_x=-0.2,
            pan_y=0.15,
            orientation=rotation_hotfix._quaternion_from_yaw_pitch(33.0, 18.0),
        )
        arcball_mvp, arcball_clean, arcball_ppu = fake_renderer._orbit_camera_mvp(
            np.asarray(((-1.0, -2.0, -3.0), (1.0, 2.0, 3.0))),
            (640, 640),
            arcball_camera,
        )

        self.assertIs(arcball_clean, arcball_camera)
        self.assertTrue(np.isfinite(arcball_mvp).all())
        self.assertGreater(arcball_ppu, 0.0)


if __name__ == "__main__":
    unittest.main()
