from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tkinter as tk
import time
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import spectrum_mapper_hotfix as _hotfix  # noqa: E402,F401
import spectrum_mapper.paint_gui as paint_gui_module  # noqa: E402
from spectrum_mapper.models import AppSettings, GeometrySettings, MeshLevel  # noqa: E402
from spectrum_mapper.paint import PaintError, PaintSession  # noqa: E402
from spectrum_mapper.paint_gui import (  # noqa: E402
    HELP_TOOL_DESIRED_SIZE,
    PaintEditorWindow,
    compute_manual_tool_window_layouts,
)
from spectrum_mapper.paint_tools import (  # noqa: E402
    accumulated_airbrush_deposit,
    airbrush_hold_dab_count,
    airbrush_radius_scale,
    airbrush_state_layers,
    soft_falloff,
)


def _disconnected_level(face_count: int) -> MeshLevel:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for index in range(int(face_count)):
        base = len(vertices)
        offset = float(index * 3)
        vertices.extend(
            ((offset, 0.0, 0.0), (offset + 1.0, 0.0, 0.0), (offset, 1.0, 0.0))
        )
        faces.append((base, base + 1, base + 2))
    points = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(faces, dtype=np.int32)
    return MeshLevel(
        vertices_unit=points,
        faces=triangles,
        vertex_colors=np.full((len(points), 3), 0.5, dtype=np.float64),
        areas_unit=np.full(len(triangles), 0.5, dtype=np.float64),
        neighbors=None,
    )


class AirbrushMathR25Tests(unittest.TestCase):
    def test_radial_falloff_is_continuous_and_monotone(self) -> None:
        distances = np.linspace(0.0, 10.0, 101)
        profile = soft_falloff(distances, 10.0)

        self.assertAlmostEqual(float(profile[0]), 1.0)
        self.assertAlmostEqual(float(profile[-1]), 0.0)
        self.assertTrue(np.all(np.diff(profile) <= 1.0e-7))
        self.assertGreater(len(np.unique(np.round(profile, 5))), 90)

    def test_hold_deposit_accumulates_by_time_not_pointer_events(self) -> None:
        self.assertEqual(airbrush_hold_dab_count(0.0), 1)
        self.assertEqual(airbrush_hold_dab_count(0.119), 1)
        self.assertEqual(airbrush_hold_dab_count(0.120), 2)
        self.assertEqual(airbrush_hold_dab_count(0.480), 5)
        self.assertEqual(airbrush_hold_dab_count(99.0), 64)

        falloff = np.asarray((1.0, 0.6, 0.2, 0.0))
        one = accumulated_airbrush_deposit(falloff, 0.35, 0.8, 1)
        held = accumulated_airbrush_deposit(falloff, 0.35, 0.8, 5)
        self.assertTrue(np.all(held >= one))
        self.assertGreater(float(held[0]), float(one[0]))
        self.assertEqual(float(held[-1]), 0.0)

    def test_pressure_changes_both_radius_and_strength(self) -> None:
        self.assertLess(airbrush_radius_scale(0.2), airbrush_radius_scale(0.8))
        light = accumulated_airbrush_deposit((1.0,), 0.5, 0.2, 3)
        firm = accumulated_airbrush_deposit((1.0,), 0.5, 0.8, 3)
        self.assertLess(float(light[0]), float(firm[0]))

    def test_adaptive_layers_progress_toward_target_without_disabled_states(self) -> None:
        palette = np.linspace(0.0, 1.0, 32)[:, None] * np.ones((1, 3))
        enabled = np.zeros(32, dtype=bool)
        enabled[::2] = True
        enabled[31] = True
        layers = airbrush_state_layers(
            0,
            31,
            palette,
            enabled,
            strength=0.35,
            pressure=1.0,
            dab_count=8,
        )

        self.assertTrue(layers)
        radii = [radius for radius, _state in layers]
        states = [state for _radius, state in layers]
        self.assertTrue(all(a > b for a, b in zip(radii, radii[1:])))
        self.assertTrue(all(enabled[state] for state in states))
        distances = [float(np.linalg.norm(palette[state] - palette[31])) for state in states]
        self.assertTrue(all(a >= b for a, b in zip(distances, distances[1:])))


class AirbrushSessionR25Tests(unittest.TestCase):
    def _session(self, count: int = 128) -> PaintSession:
        return PaintSession(
            _disconnected_level(count),
            100.0,
            np.zeros(count, dtype=np.int8),
        )

    @staticmethod
    def _enabled() -> np.ndarray:
        enabled = np.zeros(32, dtype=bool)
        enabled[[0, 5]] = True
        return enabled

    def test_hold_accumulation_is_density_independent_and_one_undo(self) -> None:
        sparse = self._session()
        dense = self._session()
        seeds = list(range(128))
        duplicated = [face for face in seeds for _ in range(7)]

        sparse_changed = sparse.airbrush_stroke(
            seeds,
            5,
            0.0,
            0.08,
            dab_count=5,
            enabled_states=self._enabled(),
        )
        dense_changed = dense.airbrush_stroke(
            duplicated,
            5,
            0.0,
            0.08,
            dab_count=5,
            enabled_states=self._enabled(),
        )

        np.testing.assert_array_equal(sparse_changed, dense_changed)
        np.testing.assert_array_equal(sparse.overrides, dense.overrides)
        self.assertEqual(sparse.undo_depth, 1)
        sparse.undo()
        np.testing.assert_array_equal(sparse.overrides, -1)

    def test_longer_hold_changes_more_faces_and_residual_never_leaks(self) -> None:
        tap = self._session()
        held = self._session()
        seeds = list(range(128))
        tap_changed = tap.airbrush_stroke(
            seeds, 5, 0.0, 0.08, dab_count=1, enabled_states=self._enabled()
        )
        held_changed = held.airbrush_stroke(
            seeds, 5, 0.0, 0.08, dab_count=8, enabled_states=self._enabled()
        )
        self.assertGreater(len(held_changed), len(tap_changed))
        self.assertEqual(tap._airbrush_residual, {})
        self.assertEqual(held._airbrush_residual, {})

    def test_disabled_target_and_invalid_dab_count_fail_closed(self) -> None:
        session = self._session(4)
        enabled = np.zeros(32, dtype=bool)
        enabled[0] = True
        with self.assertRaises(PaintError):
            session.airbrush_stroke((0,), 5, 1.0, 1.0, enabled_states=enabled)
        with self.assertRaises(PaintError):
            session.airbrush_stroke(
                (0,), 0, 1.0, 1.0, dab_count=0, enabled_states=enabled
            )
        np.testing.assert_array_equal(session.overrides, -1)


class ManualPaintUiContractR25Tests(unittest.TestCase):
    def test_ribbon_options_keep_only_safety_settings_and_radius_has_one_home(self) -> None:
        source = (
            Path(__file__).resolve().parent / "spectrum_mapper" / "paint_gui.py"
        ).read_text(encoding="utf-8")
        legacy_options = source.split("        options = ttk.Frame(", 1)[1].split(
            "        self.joint_panel = ttk.Frame(", 1
        )[0]
        build_ui = source.split("    def _build_ui(self)", 1)[1].split(
            "    def _on_ribbon_tab_clicked", 1
        )[0]
        floating = build_ui.split(
            "# The detached Brush & Color panel is the single home", 1
        )[1]
        ribbon = build_ui.split(
            "# The detached Brush & Color panel is the single home", 1
        )[0]

        # The retained legacy page must not accidentally reintroduce a second
        # drawing-parameter host when it is used by downstream integrations.
        self.assertNotIn("ブラシ半径", legacy_options)
        self.assertNotIn("brush_radius_var", legacy_options)
        self.assertNotIn("smooth_passes_var", legacy_options)
        self.assertIn("edge_guard_var", legacy_options)
        self.assertIn("edge_angle_var", legacy_options)
        self.assertIn("boundary_diagnostics_var", legacy_options)

        self.assertNotIn("paint.brush_radius", ribbon)
        self.assertNotIn("brush_radius_var", ribbon)
        self.assertIn("paint.brush_radius", floating)
        self.assertIn("brush_radius_var", floating)

    def test_release_source_keeps_tools_in_palette_and_hides_split_joint(self) -> None:
        source = (
            Path(__file__).resolve().parent / "spectrum_mapper" / "paint_gui.py"
        ).read_text(encoding="utf-8")
        build_ui = source.split("    def _build_ui(self)", 1)[1].split(
            "    def _on_ribbon_tab_clicked", 1
        )[0]
        floating = build_ui.split(
            "# The detached Brush & Color panel is the single home", 1
        )[1]
        ribbon = build_ui.split(
            "# The detached Brush & Color panel is the single home", 1
        )[0]

        for tool in ("brush", "airbrush", "eyedropper", "smudge", "fill", "smooth", "erase"):
            self.assertIn(f'"{tool}"', floating)
        self.assertNotIn('"shape": "paint.ribbon_shape"', ribbon)
        self.assertNotIn('self.ribbon_pages["shape"]', ribbon)
        self.assertNotIn('value="lasso"', build_ui)
        self.assertNotIn('value="joint"', build_ui)
        self.assertIn("self.crease_overlay_var = tk.BooleanVar(value=False)", source)

    def test_1920_layout_leaves_a_wide_unobscured_preview(self) -> None:
        layouts = compute_manual_tool_window_layouts(1920, 1080)

        def rect(key: str) -> tuple[int, int, int, int]:
            geometry = layouts[key][0]
            size, x_text, y_text = geometry.split("+", 2)
            width_text, height_text = size.split("x", 1)
            return int(x_text), int(y_text), int(width_text), int(height_text)

        palette = rect("palette")
        parts = rect("parts")
        guide = rect("help")
        self.assertEqual(palette, (20, 70, 540, 760))
        self.assertEqual(parts, (1430, 70, 470, 330))
        self.assertEqual(guide, (1540, 440, 360, 590))
        self.assertEqual(guide[2], HELP_TOOL_DESIRED_SIZE[0])
        preview_left = palette[0] + palette[2]
        preview_right = min(parts[0], guide[0])
        self.assertGreaterEqual(preview_right - preview_left, 870)
        self.assertGreaterEqual(guide[1], parts[1] + parts[3] + 30 + 10)
        self.assertLessEqual(guide[1] + guide[3] + 30, 1080 - 20)


class ManualPaintRealTkR25Tests(unittest.TestCase):
    def test_real_editor_uses_floating_tools_default_off_crease_and_slim_guide(self) -> None:
        from test_gui_integration import _pump, _tetra_prepared

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        editor = None
        original_schedule_render = None
        original_layout_function = paint_gui_module.compute_manual_tool_window_layouts
        paint_gui_module.compute_manual_tool_window_layouts = (
            lambda _screen_width, _screen_height: original_layout_function(1920, 1080)
        )
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
            editor.window.geometry("1920x1080+0+0")
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
            root.update()

            def actual_rect(window: tk.Toplevel) -> tuple[int, int, int, int]:
                return (
                    window.winfo_x(),
                    window.winfo_y(),
                    window.winfo_width(),
                    window.winfo_height(),
                )

            self.assertEqual(
                actual_rect(editor.palette_tool_window),
                (20, 70, 540, 760),
            )
            self.assertEqual(
                actual_rect(editor.parts_tool_window),
                (1430, 70, 470, 330),
            )
            self.assertEqual(
                actual_rect(editor.help_tool_window),
                (1540, 440, 360, 590),
            )

            self.assertFalse(editor.crease_overlay_var.get())
            self.assertEqual(
                set(editor.ribbon_pages),
                {"home", "brush", "shading"},
            )
            self.assertNotIn("decal", editor.ribbon_tab_buttons)
            self.assertFalse(hasattr(editor, "decal_import_button"))
            selected_ribbon = editor._ribbon_selected
            editor._select_ribbon("decal")
            self.assertEqual(editor._ribbon_selected, selected_ribbon)
            self.assertFalse(hasattr(editor, "joint_panel"))
            self.assertEqual(editor.window.bind("<KeyPress-l>"), "")
            self.assertEqual(editor.window.bind("<KeyPress-j>"), "")
            self.assertTrue(hasattr(editor, "_hotfix_pressure_status_var"))

            # Manual Painting uses the exact family-major presentation from
            # Filament Settings while every Radiobutton retains its canonical
            # palette-state value.
            self.assertEqual(editor.palette_buttons[0].cget("text"), "F1")
            self.assertEqual(editor.palette_buttons[3].cget("text"), "F4")
            self.assertEqual(editor.palette_buttons[4].cget("text"), "01")
            self.assertEqual(editor.palette_buttons[10].cget("text"), "02")
            self.assertEqual(
                (
                    int(editor.palette_buttons[4].grid_info()["row"]),
                    int(editor.palette_buttons[4].grid_info()["column"]),
                ),
                (2, 1),
            )
            self.assertEqual(
                (
                    int(editor.palette_buttons[10].grid_info()["row"]),
                    int(editor.palette_buttons[10].grid_info()["column"]),
                ),
                (2, 2),
            )
            editor.paint_state_var.set(10)
            editor._refresh_palette_buttons()
            self.assertEqual(editor.paint_state_var.get(), 10)

            def belongs_to_palette(widget: tk.Misc) -> bool:
                current: tk.Misc | None = widget
                while current is not None:
                    if current is editor.palette_tool_window:
                        return True
                    current = getattr(current, "master", None)
                return False

            self.assertTrue(
                all(belongs_to_palette(button) for button in editor.paint_tool_buttons.values())
            )
            self.assertLessEqual(editor.help_tool_window.winfo_width(), 360)
            self.assertGreaterEqual(
                editor.help_tool_window.winfo_y(),
                editor.parts_tool_window.winfo_y()
                + editor.parts_tool_window.winfo_height(),
            )

            # Exercise the production hotfix path, not just the pure planner:
            # one stationary held dab must become an adaptive circular tree and
            # still occupy exactly one undo slot.
            visible_pixels = np.argwhere(np.asarray(editor.face_ids) >= 0)
            self.assertGreater(len(visible_pixels), 0)
            render_y, render_x = visible_pixels[len(visible_pixels) // 2]
            left, top, width, height, render_width, render_height = editor.target_mapping
            canvas_x = int(left + (float(render_x) + 0.5) * width / render_width)
            canvas_y = int(top + (float(render_y) + 0.5) * height / render_height)
            face = editor._face_at(canvas_x, canvas_y)
            self.assertGreaterEqual(face, 0)
            source_state = int(editor.effective_indices[face])
            editor.paint_state_var.set((source_state + 7) % 32)
            editor.tool_var.set("airbrush")
            editor.airbrush_strength_var.set(100.0)
            editor.brush_radius_var.set(0.7)
            editor._hotfix_stroke_debounce_ms = 1
            event = SimpleNamespace(x=canvas_x, y=canvas_y, state=0)
            editor._on_left_press(event)
            self.assertEqual(editor._drag_mode, "airbrush-stroke")
            feedback = editor._hotfix_active_feedback
            self.assertIsNotNone(editor._hotfix_airbrush_preview_after)
            initial_opacities = tuple(feedback["airbrush_opacities"])
            initial_fills = tuple(
                editor.canvas.itemcget(item, "fill")
                for item in editor.canvas.find_withtag("smooth-stroke-feedback")
            )
            initial_coords = tuple(
                tuple(editor.canvas.coords(item))
                for item in editor.canvas.find_withtag("smooth-airbrush-head")
            )
            editor._airbrush_started_at = time.monotonic() - 0.50
            self.assertTrue(
                _pump(
                    root,
                    lambda: int(feedback["airbrush_dab_count"]) >= 5,
                    timeout=2.0,
                ),
                "stationary hold preview did not advance",
            )
            held_opacities = tuple(feedback["airbrush_opacities"])
            held_fills = tuple(
                editor.canvas.itemcget(item, "fill")
                for item in editor.canvas.find_withtag("smooth-stroke-feedback")
            )
            held_coords = tuple(
                tuple(editor.canvas.coords(item))
                for item in editor.canvas.find_withtag("smooth-airbrush-head")
            )
            self.assertTrue(
                all(after >= before for before, after in zip(initial_opacities, held_opacities))
            )
            self.assertGreater(held_opacities[1], initial_opacities[1])
            # Density growth changes only the O(1) current-head geometry.  It
            # must not rebuild a 16-band, backdrop-preblended trail.
            self.assertEqual(len(held_coords), 2)
            self.assertNotEqual(held_coords, initial_coords)
            self.assertEqual(held_fills, initial_fills)

            same_face_pixels = np.argwhere(np.asarray(editor.face_ids) == face)
            candidate = next(
                (
                    (int(x), int(y))
                    for y, x in same_face_pixels
                    if 5.0
                    <= float(np.hypot(float(x - render_x), float(y - render_y)))
                    <= 20.0
                ),
                None,
            )
            if candidate is not None:
                motion_x = int(
                    left + (float(candidate[0]) + 0.5) * width / render_width
                )
                motion_y = int(
                    top + (float(candidate[1]) + 0.5) * height / render_height
                )
                editor._on_left_motion(
                    SimpleNamespace(x=motion_x, y=motion_y, state=0)
                )
                feedback_items = editor.canvas.find_withtag(
                    "smooth-stroke-feedback"
                )
                # One segment is three thin guide lines plus the two-item head,
                # not sixteen solid capsules multiplied by pointer events.
                self.assertLessEqual(len(feedback_items), 5)
                expected_color = str(feedback["color"]).lower()
                for item in feedback_items:
                    option = (
                        "fill"
                        if editor.canvas.type(item) == "line"
                        else "outline"
                    )
                    shown = editor.canvas.itemcget(item, option)
                    if shown:
                        self.assertEqual(shown.lower(), expected_color)
            # Hold the exact render so the acceptance boundary can be audited:
            # the clean provisional guide must remain over the old base until
            # a different exact frame is actually available.
            base_image_before_release = editor.target_image
            scheduled_renders: list[bool] = []
            original_schedule_render = editor._schedule_render
            editor._schedule_render = lambda *, immediate=False: scheduled_renders.append(
                bool(immediate)
            )
            editor._on_left_release(event)
            self.assertIsNone(editor._hotfix_airbrush_preview_after)
            self.assertIsNone(editor._hotfix_pending_stroke_batch)
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor._session is not None
                        and editor._session.undo_depth == 1
                        and not editor._job_running
                    ),
                    timeout=5.0,
                ),
                editor.status_var.get(),
            )
            self.assertEqual(scheduled_renders, [True])
            self.assertIs(editor.target_image, base_image_before_release)
            self.assertEqual(len(editor._hotfix_pending_feedback), 1)
            self.assertTrue(editor._hotfix_pending_feedback[0]["committed"])
            self.assertTrue(
                editor.canvas.find_withtag("smooth-airbrush-head"),
                "accepted stroke flashed back to the unpainted base",
            )

            editor._schedule_render = original_schedule_render
            original_schedule_render = None
            editor._schedule_render(immediate=True)
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.target_image is not base_image_before_release
                        and not editor._hotfix_pending_feedback
                        and not editor._job_running
                    ),
                    timeout=5.0,
                ),
                editor.status_var.get(),
            )
            adaptive_nodes = tuple(editor._hotfix_tree_store.values())
            self.assertTrue(adaptive_nodes)
            self.assertTrue(any(not node.is_leaf for node in adaptive_nodes))
            self.assertEqual(editor._session.undo_depth, 1)
            self.assertEqual(
                editor.canvas.find_withtag("smooth-airbrush-head"), ()
            )
            editor._session.undo()
            self.assertEqual(editor._hotfix_tree_store, {})
            np.testing.assert_array_equal(editor._session.overrides, -1)
        finally:
            paint_gui_module.compute_manual_tool_window_layouts = original_layout_function
            if editor is not None and original_schedule_render is not None:
                editor._schedule_render = original_schedule_render
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

    def test_airbrush_pending_guide_is_hidden_on_zoom_without_losing_commit_or_undo(self) -> None:
        """A screen-space trail must not survive a camera transform."""

        from test_gui_integration import _pump, _tetra_prepared

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        editor = None
        original_submit = None
        try:
            prepared = _tetra_prepared()
            editor = PaintEditorWindow(
                root,
                prepared,
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
            editor.window.geometry("1100x780+30+30")
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

            ids = np.asarray(editor.face_ids)
            left, top, width, height, render_width, render_height = (
                editor.target_mapping
            )

            def canvas_point(rx: int, ry: int) -> tuple[int, int]:
                return (
                    int(round(left + (rx + 0.5) * width / render_width)),
                    int(round(top + (ry + 0.5) * height / render_height)),
                )

            start = end = None
            rows = sorted(
                range(ids.shape[0]),
                key=lambda y: int(np.count_nonzero(ids[y] >= 0)),
                reverse=True,
            )
            for row in rows:
                visible_x = np.flatnonzero(ids[row] >= 0)
                if len(visible_x) < 12:
                    continue
                candidate_start = canvas_point(
                    int(visible_x[len(visible_x) * 2 // 5]), row
                )
                candidate_end = canvas_point(
                    int(visible_x[len(visible_x) * 3 // 5]), row
                )
                if (
                    editor._face_at(*candidate_start) >= 0
                    and editor._face_at(*candidate_end) >= 0
                ):
                    start, end = candidate_start, candidate_end
                    break
            self.assertIsNotNone(start, "no paintable airbrush segment was found")
            self.assertIsNotNone(end, "no paintable airbrush segment was found")

            face = editor._face_at(*start)
            source_state = int(editor.effective_indices[face])
            editor.paint_state_var.set((source_state + 7) % 32)
            editor.tool_var.set("airbrush")
            editor.airbrush_strength_var.set(100.0)
            editor.brush_radius_var.set(0.7)
            editor.edge_guard_var.set(False)

            # Hold only the paint job so the test deterministically reproduces
            # the user's release-then-scroll window. View renders remain real.
            held_edits: list[tuple[str, object, dict[str, object]]] = []
            original_submit = editor._submit

            def hold_edit(kind, work, **kwargs):
                if kind == "edit":
                    held_edits.append((kind, work, dict(kwargs)))
                    return None
                return original_submit(kind, work, **kwargs)

            editor._submit = hold_edit
            editor._on_left_press(
                SimpleNamespace(x=start[0], y=start[1], state=0)
            )
            editor._on_left_motion(
                SimpleNamespace(x=end[0], y=end[1], state=0)
            )
            editor._on_left_release(
                SimpleNamespace(x=end[0], y=end[1], state=0)
            )
            self.assertEqual(len(held_edits), 1)
            self.assertEqual(len(editor._hotfix_pending_feedback), 1)
            self.assertTrue(
                editor.canvas.find_withtag("smooth-stroke-feedback"),
                "precondition: pending guide is not visible",
            )

            old_camera = editor.camera
            editor._on_mousewheel(SimpleNamespace(delta=120))
            self.assertNotEqual(editor.camera, old_camera)
            self.assertEqual(
                editor.canvas.find_withtag("smooth-stroke-feedback"), ()
            )
            self.assertTrue(
                editor._hotfix_pending_feedback[0]["view_suppressed"]
            )
            self.assertIsNone(editor._hotfix_airbrush_preview_after)
            # Display suppression must not discard the worker acceptance token.
            self.assertEqual(len(editor._hotfix_pending_feedback), 1)
            self.assertFalse(editor._hotfix_pending_feedback[0]["committed"])

            self.assertTrue(
                _pump(
                    root,
                    lambda: not editor._job_running and not editor._render_dirty,
                    timeout=5.0,
                ),
                editor.status_var.get(),
            )
            self.assertEqual(
                editor.canvas.find_withtag("smooth-stroke-feedback"), ()
            )
            self.assertEqual(len(editor._hotfix_pending_feedback), 1)

            def current_paintable_segment() -> tuple[tuple[int, int], tuple[int, int]]:
                current_ids = np.asarray(editor.face_ids)
                c_left, c_top, c_width, c_height, c_rw, c_rh = (
                    editor.target_mapping
                )

                def current_canvas_point(rx: int, ry: int) -> tuple[int, int]:
                    return (
                        int(round(c_left + (rx + 0.5) * c_width / c_rw)),
                        int(round(c_top + (ry + 0.5) * c_height / c_rh)),
                    )

                current_rows = sorted(
                    range(current_ids.shape[0]),
                    key=lambda y: int(np.count_nonzero(current_ids[y] >= 0)),
                    reverse=True,
                )
                for current_row in current_rows:
                    current_x = np.flatnonzero(current_ids[current_row] >= 0)
                    if len(current_x) < 12:
                        continue
                    current_start = current_canvas_point(
                        int(current_x[len(current_x) * 2 // 5]), current_row
                    )
                    current_end = current_canvas_point(
                        int(current_x[len(current_x) * 3 // 5]), current_row
                    )
                    if (
                        editor._face_at(*current_start) >= 0
                        and editor._face_at(*current_end) >= 0
                    ):
                        return current_start, current_end
                self.fail("no paintable segment after view change")

            def hold_one_more_stroke() -> tuple[tuple[int, int], tuple[int, int]]:
                current_start, current_end = current_paintable_segment()
                current_face = editor._face_at(*current_start)
                current_state = int(editor.effective_indices[current_face])
                editor.paint_state_var.set((current_state + 9) % 32)
                editor._on_left_press(
                    SimpleNamespace(
                        x=current_start[0], y=current_start[1], state=0
                    )
                )
                editor._on_left_motion(
                    SimpleNamespace(x=current_end[0], y=current_end[1], state=0)
                )
                editor._on_left_release(
                    SimpleNamespace(x=current_end[0], y=current_end[1], state=0)
                )
                self.assertTrue(
                    editor.canvas.find_withtag("smooth-stroke-feedback")
                )
                return current_start, current_end

            # Orbit hides the next guide at gesture start, even before its
            # throttled render can move a single pixel.
            orbit_start, orbit_end = hold_one_more_stroke()
            self.assertEqual(len(held_edits), 2)
            orbit_camera = editor.camera
            editor._on_right_press(
                SimpleNamespace(x=orbit_end[0], y=orbit_end[1], state=0)
            )
            self.assertEqual(
                editor.canvas.find_withtag("smooth-stroke-feedback"), ()
            )
            self.assertTrue(
                editor._hotfix_pending_feedback[-1]["view_suppressed"]
            )
            editor._on_right_motion(
                SimpleNamespace(x=orbit_end[0] + 24, y=orbit_end[1] + 12, state=0)
            )
            editor._on_right_release(
                SimpleNamespace(x=orbit_end[0] + 24, y=orbit_end[1] + 12, state=0)
            )
            self.assertNotEqual(editor.camera, orbit_camera)
            self.assertTrue(
                _pump(
                    root,
                    lambda: not editor._job_running and not editor._render_dirty,
                    timeout=5.0,
                ),
                editor.status_var.get(),
            )

            # Middle-button pan follows the same display-only suppression
            # contract and leaves all three edit tokens available to commit.
            pan_start, pan_end = hold_one_more_stroke()
            self.assertEqual(len(held_edits), 3)
            pan_camera = editor.camera
            editor._on_middle_press(
                SimpleNamespace(x=pan_start[0], y=pan_start[1], state=0)
            )
            self.assertEqual(
                editor.canvas.find_withtag("smooth-stroke-feedback"), ()
            )
            self.assertTrue(
                editor._hotfix_pending_feedback[-1]["view_suppressed"]
            )
            editor._on_middle_motion(
                SimpleNamespace(x=pan_start[0] + 18, y=pan_start[1] + 10, state=0)
            )
            editor._on_middle_release(
                SimpleNamespace(x=pan_start[0] + 18, y=pan_start[1] + 10, state=0)
            )
            self.assertNotEqual(editor.camera, pan_camera)
            self.assertEqual(len(editor._hotfix_pending_feedback), 3)
            self.assertTrue(
                _pump(
                    root,
                    lambda: not editor._job_running and not editor._render_dirty,
                    timeout=5.0,
                ),
                editor.status_var.get(),
            )

            editor._submit = original_submit
            original_submit = None
            for kind, work, kwargs in held_edits:
                editor._submit(kind, work, **kwargs)
            held_edits.clear()
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and not editor._hotfix_pending_feedback
                        and editor._session.undo_depth == 3
                        and editor.target_image.info.get(
                            "tripo_spectrum_adaptive_gpu_revision"
                        )
                        == int(prepared._hotfix_tree_revision)
                    ),
                    timeout=8.0,
                ),
                editor.status_var.get(),
            )
            self.assertEqual(
                editor.canvas.find_withtag("smooth-stroke-feedback"), ()
            )
            self.assertTrue(editor._hotfix_tree_store)

            editor._undo()
            editor._undo()
            editor._undo()
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and editor._session.undo_depth == 0
                        and not editor._hotfix_tree_store
                    ),
                    timeout=8.0,
                ),
                editor.status_var.get(),
            )
        finally:
            if editor is not None and original_submit is not None:
                editor._submit = original_submit
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
