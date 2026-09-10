from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import numpy as np
from PIL import Image
import tkinter as tk


sys.path.insert(0, str(Path(__file__).resolve().parent))

import spectrum_mapper_hotfix as _hotfix  # noqa: E402,F401
from spectrum_mapper.i18n import Translator  # noqa: E402
from spectrum_mapper.paint_gui import (  # noqa: E402
    MANUAL_ZOOM_MAX,
    PaintEditorWindow,
    overlay_visible_creases,
)


class _Var:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class ManualPaintR24CopyTests(unittest.TestCase):
    def test_removed_color_refine_has_no_ui_or_help_entry(self) -> None:
        root = Path(__file__).resolve().parent / "spectrum_mapper"
        paint_source = (root / "paint_gui.py").read_text(encoding="utf-8")
        i18n_source = (root / "i18n.py").read_text(encoding="utf-8")
        for text in (paint_source, i18n_source):
            self.assertNotIn("paint.refine", text)
            self.assertNotIn("palette_tab_refine", text)
            self.assertNotIn("色を整える", text)
            self.assertNotIn("Refine Colors", text)

    def test_new_tool_labels_are_concise_in_both_languages(self) -> None:
        for language in ("ja", "en"):
            translator = Translator(language)
            for key in (
                "paint.airbrush",
                "paint.eyedropper_3d",
                "paint.smudge",
                "paint.crease_overlay",
                "paint.zoom",
            ):
                with self.subTest(language=language, key=key):
                    value = translator.text(key)
                    self.assertNotEqual(value, key)
                    self.assertLessEqual(len(value), 18)

    def test_crease_guard_copy_names_local_tools_and_help_lists_scope(self) -> None:
        ja = Translator("ja")
        en = Translator("en")
        self.assertEqual(ja.text("paint.edge_guard"), "局所ツールを折り目で止める")
        self.assertEqual(en.text("paint.edge_guard"), "Stop Local Tools at Creases")
        for translator in (ja, en):
            help_copy = translator.text(
                "help_center.topic.manual_editing.step4_guard"
            )
            self.assertIn("B/A/M/S/E", help_copy)
            self.assertIn("F", help_copy)


class ManualPaintR24CreaseTests(unittest.TestCase):
    def _image_for_angle(self, angle: float, threshold: float) -> Image.Image:
        radians = np.deg2rad(angle)
        normals = np.asarray(
            [[0.0, 0.0, 1.0], [np.sin(radians), 0.0, np.cos(radians)]],
            dtype=np.float64,
        )
        image = Image.new("RGB", (8, 4), (116, 43, 160))
        face_ids = np.zeros((4, 8), dtype=np.int32)
        face_ids[:, 4:] = 1
        return overlay_visible_creases(image, face_ids, normals, threshold)

    def test_crease_classification_at_30_45_and_75_degrees(self) -> None:
        original = np.asarray(Image.new("RGB", (8, 4), (116, 43, 160)))
        for angle, threshold, expected in (
            (30.0, 45.0, False),
            (45.0, 45.0, False),
            (45.01, 45.0, True),
            (75.0, 45.0, True),
            (45.0, 75.0, False),
        ):
            with self.subTest(angle=angle, threshold=threshold):
                result = np.asarray(self._image_for_angle(angle, threshold))
                self.assertEqual(bool(np.any(result != original)), expected)

    def test_overlay_uses_dark_halo_and_bright_core(self) -> None:
        pixels = np.asarray(self._image_for_angle(60.0, 45.0))
        colours = {tuple(int(channel) for channel in pixel) for pixel in pixels.reshape(-1, 3)}
        self.assertIn((13, 18, 25), colours)
        self.assertIn((255, 220, 112), colours)


class ManualPaintR24InteractionTests(unittest.TestCase):
    def test_eyedropper_samples_current_state_and_returns_to_previous_tool(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor.effective_indices = np.asarray([7], dtype=np.int8)
        editor.paint_state_var = _Var(1)
        editor.status_var = _Var("")
        editor.i18n = Translator("en")
        editor.state_names = tuple(f"State {index + 1}" for index in range(32))
        editor._update_selected_palette_label = lambda: None

        self.assertTrue(PaintEditorWindow._sample_current_3d_state(editor, 0))
        self.assertEqual(editor.paint_state_var.get(), 7)
        self.assertIn("Color 8", editor.status_var.get())

    def test_eyedropper_routes_visible_adaptive_state_through_core(self) -> None:
        calls: list[tuple[int, int | None]] = []

        class _Session:
            def sample_painted_state(self, face, adaptive_state=None):
                calls.append((int(face), adaptive_state))
                return adaptive_state

        editor = object.__new__(PaintEditorWindow)
        editor.effective_indices = np.asarray([3], dtype=np.int8)
        editor.paint_state_var = _Var(1)
        editor.status_var = _Var("")
        editor.i18n = Translator("en")
        editor.state_names = tuple(f"State {index + 1}" for index in range(32))
        editor._session = _Session()
        editor._adaptive_state_at = lambda _face, _event: 11
        editor._update_selected_palette_label = lambda: None

        self.assertTrue(
            PaintEditorWindow._sample_current_3d_state(
                editor,
                0,
                SimpleNamespace(x=20, y=20),
            )
        )
        self.assertEqual(calls, [(0, 11)])
        self.assertEqual(editor.paint_state_var.get(), 11)

    def test_dedicated_eyedropper_is_one_shot(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor._close_requested = False
        editor._topology_change_pending = False
        editor.tool_var = _Var("eyedropper")
        editor.reference_mapping = None
        editor.effective_indices = np.asarray([9], dtype=np.int8)
        editor.paint_state_var = _Var(1)
        editor.status_var = _Var("")
        editor.i18n = Translator("en")
        editor.state_names = tuple(f"State {index + 1}" for index in range(32))
        editor._eyedropper_return_tool = "airbrush"
        editor._point_inside = lambda *_args: False
        editor._face_at = lambda *_args: 0
        editor._update_selected_palette_label = lambda: None
        changed: list[str] = []
        editor._on_tool_changed = lambda **_kwargs: changed.append(
            editor.tool_var.get()
        )

        PaintEditorWindow._on_left_press(
            editor,
            SimpleNamespace(x=20, y=20, state=0),
        )

        self.assertEqual(editor.paint_state_var.get(), 9)
        self.assertEqual(editor.tool_var.get(), "airbrush")
        self.assertEqual(changed, ["airbrush"])

    def test_airbrush_and_smudge_selection_show_one_line_guidance(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor.tool_var = _Var("airbrush")
        editor._last_tool_mode = "brush"
        editor.status_var = _Var("")
        editor.i18n = Translator("en")
        editor._select_ribbon_for_tool = lambda _tool: None

        PaintEditorWindow._on_tool_changed(editor)
        self.assertEqual(
            editor.status_var.get(),
            "Airbrush: drag to paint softly with pressure and strength",
        )

        editor.tool_var.set("smudge")
        PaintEditorWindow._on_tool_changed(editor)
        self.assertIn("color you want to keep", editor.status_var.get())

    def test_zoom_clamps_to_24x_and_keeps_status_readable(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor.camera = SimpleNamespace(zoom=1.0)
        # dataclasses.replace needs a dataclass camera in the real method; use
        # the production CameraState through reset-compatible construction.
        from spectrum_mapper.renderer import CameraState

        editor.camera = CameraState()
        editor.zoom_status_var = _Var("")
        editor._schedule_render = lambda **_kwargs: None
        PaintEditorWindow._set_zoom(editor, 100.0)
        self.assertEqual(editor.camera.zoom, MANUAL_ZOOM_MAX)
        self.assertEqual(editor.zoom_status_var.get(), "2400%")

    def _queue_editor(self):
        editor = object.__new__(PaintEditorWindow)
        editor.brush_radius_var = _Var(2.5)
        editor.airbrush_strength_var = _Var(35.0)
        editor.smudge_strength_var = _Var(65.0)
        editor.edge_guard_var = _Var(True)
        editor.edge_angle_var = _Var(45.0)
        editor.paint_state_var = _Var(6)
        editor.palette_rgb = np.zeros((32, 3), dtype=np.float64)
        editor.level = SimpleNamespace(faces=np.zeros((4, 3), dtype=np.int32))
        editor.face_ids = np.asarray([[1, 2], [1, -1]], dtype=np.int32)
        editor._render_dirty = False
        editor.camera = object()
        editor._hotfix_pick_camera = editor.camera
        editor._visible_face_mask_cache_key = None
        editor._visible_face_mask_cache = None
        editor._visible_face_mask_source = None
        editor._drag_mode = None
        editor._stroke_faces = []
        editor.i18n = Translator("en")
        editor._active_palette = lambda: SimpleNamespace(
            enabled_states=np.asarray([index != 6 for index in range(32)], dtype=bool)
        )
        editor._worker_refresh_after_edit = lambda label, changed: (label, changed)
        editor._submit = lambda _kind, work: work()
        return editor

    def test_color_only_redraw_keeps_exact_visible_mask_but_camera_change_blocks(self) -> None:
        editor = self._queue_editor()
        editor._render_dirty = True

        mask = PaintEditorWindow._visible_face_mask_for_stroke(editor)
        self.assertIsNotNone(mask)
        self.assertEqual(mask.tolist(), [False, True, True, False])

        editor._hotfix_pick_camera = object()
        self.assertIsNone(PaintEditorWindow._visible_face_mask_for_stroke(editor))

    def test_airbrush_submits_one_density_stable_seed_set(self) -> None:
        calls = []

        class _Session:
            def airbrush_stroke(self, *args, **kwargs):
                calls.append((args, kwargs))
                return np.asarray([1, 2], dtype=np.int64)

        editor = self._queue_editor()
        editor._session = _Session()
        PaintEditorWindow._queue_airbrush(editor, [1, 1, 2, 1], pressure=0.4)
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[0], [1, 2])
        self.assertEqual(args[1:4], (6, 2.5, 0.35))
        self.assertEqual(kwargs["pressure"], 0.4)
        self.assertEqual(kwargs["dab_count"], 1)
        self.assertTrue(kwargs["enabled_states"][6])
        self.assertEqual(
            kwargs["visible_face_mask"].tolist(),
            [False, True, True, False],
        )
        self.assertTrue(kwargs["protect_sharp_edges"])
        self.assertEqual(kwargs["max_angle_degrees"], 45.0)

    def test_pressure_brush_keeps_ordered_seed_path(self) -> None:
        calls = []

        class _Session:
            def begin_stroke(self, label):
                calls.append(("begin", label))

            def paint_brush(self, *args, **kwargs):
                calls.append(("paint", args, kwargs))

            def end_stroke(self):
                calls.append(("end",))
                return 3

            def cancel_stroke(self):
                calls.append(("cancel",))

        editor = self._queue_editor()
        editor._session = _Session()
        PaintEditorWindow._queue_stroke(editor, [1, 2, 1], False)
        self.assertEqual(
            [call[1][0] for call in calls if call[0] == "paint"],
            [1, 2, 1],
        )
        for call in (call for call in calls if call[0] == "paint"):
            self.assertTrue(call[2]["protect_sharp_edges"])
            self.assertEqual(call[2]["max_angle_degrees"], 45.0)
            self.assertEqual(
                call[2]["visible_face_mask"].tolist(),
                [False, True, True, False],
            )

    def test_smudge_preserves_backtracking_path_for_directional_blend(self) -> None:
        calls = []

        class _Session:
            def smudge_stroke(self, *args, **kwargs):
                calls.append((args, kwargs))
                return np.asarray([1, 2], dtype=np.int64)

        editor = self._queue_editor()
        editor._session = _Session()
        PaintEditorWindow._queue_smudge(editor, [1, 2, 1], pressure=0.7)
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[0], [1, 2, 1])
        self.assertEqual(args[1:3], (2.5, 0.65))
        self.assertEqual(kwargs["pressure"], 0.7)
        self.assertTrue(kwargs["protect_sharp_edges"])
        self.assertEqual(kwargs["max_angle_degrees"], 45.0)
        self.assertEqual(
            kwargs["visible_face_mask"].tolist(),
            [False, True, True, False],
        )

    def test_smooth_is_visible_local_but_fill_keeps_connected_semantics(self) -> None:
        calls = []

        class _Session:
            def smooth_boundary(self, *args, **kwargs):
                calls.append(("smooth", args, kwargs))
                return np.asarray([1], dtype=np.int64)

            def fill(self, *args, **kwargs):
                calls.append(("fill", args, kwargs))
                return np.asarray([1, 2], dtype=np.int64)

        editor = self._queue_editor()
        editor.smooth_passes_var = _Var(2)
        editor._session = _Session()
        PaintEditorWindow._queue_smooth(editor, 1)
        PaintEditorWindow._queue_fill(editor, 1)

        smooth = next(call for call in calls if call[0] == "smooth")
        self.assertEqual(
            smooth[2]["visible_face_mask"].tolist(),
            [False, True, True, False],
        )
        fill = next(call for call in calls if call[0] == "fill")
        self.assertEqual(fill[1], (1, 6))
        self.assertEqual(fill[2], {})

    def test_visible_face_mask_is_reused_for_one_exact_frame(self) -> None:
        editor = self._queue_editor()
        first = PaintEditorWindow._visible_face_mask_for_stroke(editor)
        second = PaintEditorWindow._visible_face_mask_for_stroke(editor)
        self.assertIs(first, second)
        self.assertEqual(first.tolist(), [False, True, True, False])

        editor.face_ids = np.asarray([[0, 3]], dtype=np.int32)
        third = PaintEditorWindow._visible_face_mask_for_stroke(editor)
        self.assertIsNot(third, first)
        self.assertEqual(third.tolist(), [True, False, False, True])


class ManualPaintR24RealTkTests(unittest.TestCase):
    def test_real_editor_builds_two_tool_rows_and_side_panels(self) -> None:
        from test_gui_integration import _pump, _tetra_prepared
        from spectrum_mapper.models import AppSettings, GeometrySettings

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        editor = None
        try:
            editor = PaintEditorWindow(
                root,
                _tetra_prepared(),
                AppSettings(
                    geometry=GeometrySettings(
                        height_mm=50.0,
                        target_faces=1_000,
                        preview_faces=1_000,
                        up_axis="Y",
                        min_component_faces=1,
                    )
                ),
                None,
                None,
                lambda _values: None,
            )
            editor.window.geometry("1080x700+0+0")
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.face_ids is not None
                        and editor.target_mapping is not None
                        and not editor._job_running
                    ),
                ),
                editor.status_var.get(),
            )
            self.assertEqual(
                set(editor.paint_tool_buttons),
                {
                    "brush",
                    "airbrush",
                    "eyedropper",
                    "smudge",
                    "fill",
                    "smooth",
                    "erase",
                },
            )
            self.assertEqual(
                {editor.paint_tool_buttons[name].grid_info()["row"] for name in ("brush", "airbrush", "eyedropper", "smudge")},
                {0},
            )
            self.assertEqual(
                {editor.paint_tool_buttons[name].grid_info()["row"] for name in ("fill", "smooth", "erase")},
                {1},
            )

            tool_windows = (
                editor.palette_tool_window,
                editor.parts_tool_window,
                editor.help_tool_window,
            )

            def tool_windows_have_stable_geometry() -> bool:
                try:
                    return all(
                        window.winfo_ismapped()
                        and window.winfo_x() >= 0
                        and window.winfo_y() >= 0
                        and window.winfo_width() > 1
                        and window.winfo_height() > 1
                        for window in tool_windows
                    )
                except tk.TclError:
                    return False

            self.assertTrue(
                _pump(root, tool_windows_have_stable_geometry, timeout=5.0),
                [
                    (window.state(), window.geometry())
                    for window in tool_windows
                ],
            )
            palette_x = editor.palette_tool_window.winfo_x()
            parts_x = editor.parts_tool_window.winfo_x()
            help_x = editor.help_tool_window.winfo_x()
            self.assertLess(palette_x, parts_x)
            self.assertLess(palette_x, help_x)
            self.assertLessEqual(
                editor.parts_tool_window.winfo_y()
                + editor.parts_tool_window.winfo_height(),
                editor.help_tool_window.winfo_y(),
            )
            editor._set_zoom(24.0, immediate=True)
            root.update()
            self.assertEqual(editor.zoom_status_var.get(), "2400%")
        finally:
            if editor is not None:
                try:
                    editor.close()
                    _pump(root, lambda: not editor.window.winfo_exists(), 5.0)
                except Exception:
                    pass
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
