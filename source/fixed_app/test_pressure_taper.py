from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

import spectrum_mapper_hotfix  # noqa: F401 - installs the packaged wrapper stack
import smooth_paint
import smooth_paint_hotfix
from spectrum_mapper import paint_gui
from spectrum_mapper.renderer import CameraState


def _painted_fraction(node: smooth_paint.PaintNode, triangle: np.ndarray) -> float:
    return sum(
        leaf.area_fraction
        for leaf in smooth_paint.iter_leaf_triangles(node, triangle)
        if leaf.state == 1
    )


class _FakeWindow:
    def __init__(self) -> None:
        self.callbacks = {}
        self.serial = 0

    def after(self, _delay, callback):
        self.serial += 1
        token = f"after-{self.serial}"
        self.callbacks[token] = callback
        return token

    def after_cancel(self, token):
        self.callbacks.pop(token, None)


class _FakeCanvas:
    def __init__(self) -> None:
        self.lines = []

    def delete(self, _tag):
        self.lines.clear()

    def create_line(self, *args, **kwargs):
        self.lines.append((args, kwargs))
        return len(self.lines)

    def create_oval(self, *args, **kwargs):
        self.lines.append((args, kwargs))
        return len(self.lines)

    def create_polygon(self, *args, **kwargs):
        self.lines.append((args, kwargs))
        return len(self.lines)


class PressureTaperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.triangle = np.asarray(
            ((0.0, 0.0), (24.0, 0.0), (0.0, 24.0)),
            dtype=np.float64,
        )

    def test_constant_variable_radii_exactly_match_existing_round_api(self) -> None:
        segments = np.asarray(
            (
                ((3.0, 5.0), (9.0, 5.0)),
                ((9.0, 5.0), (14.0, 8.0)),
            ),
            dtype=np.float64,
        )
        existing = smooth_paint.PaintNode(0)
        variable = smooth_paint.PaintNode(0)
        smooth_paint.apply_capsule_segments(
            existing,
            self.triangle,
            segments,
            2.5,
            1,
            max_depth=5,
            min_edge_pixels=0.25,
        )
        smooth_paint.apply_variable_capsule_segments(
            variable,
            self.triangle,
            segments,
            np.asarray((2.5, 2.5)),
            1,
            max_depth=5,
            min_edge_pixels=0.25,
        )
        self.assertEqual(
            smooth_paint.encode_paint_color(variable),
            smooth_paint.encode_paint_color(existing),
        )

    def test_variable_radius_changes_final_geometry(self) -> None:
        segment = np.asarray((((4.0, 7.0), (16.0, 7.0)),), dtype=np.float64)
        thin = smooth_paint.PaintNode(0)
        thick = smooth_paint.PaintNode(0)
        smooth_paint.apply_variable_capsule_segments(
            thin,
            self.triangle,
            segment,
            np.asarray((0.75,)),
            1,
            max_depth=6,
            min_edge_pixels=0.15,
        )
        smooth_paint.apply_variable_capsule_segments(
            thick,
            self.triangle,
            segment,
            np.asarray((4.0,)),
            1,
            max_depth=6,
            min_edge_pixels=0.15,
        )
        self.assertGreater(
            _painted_fraction(thick, self.triangle),
            _painted_fraction(thin, self.triangle),
        )

    def test_zero_length_click_still_paints(self) -> None:
        node = smooth_paint.PaintNode(0)
        result = smooth_paint.apply_variable_capsule_segments(
            node,
            self.triangle,
            np.asarray((((5.0, 5.0), (5.0, 5.0)),), dtype=np.float64),
            np.asarray((1.5,)),
            1,
            max_depth=6,
            min_edge_pixels=0.15,
        )
        self.assertTrue(result.changed)
        self.assertGreater(_painted_fraction(node, self.triangle), 0.0)

    def test_variable_api_rejects_misaligned_or_invalid_radii(self) -> None:
        segments = np.asarray((((1.0, 1.0), (2.0, 2.0)),), dtype=np.float64)
        with self.assertRaises(smooth_paint.SmoothPaintError):
            smooth_paint.apply_variable_capsule_segments(
                smooth_paint.PaintNode(0),
                self.triangle,
                segments,
                np.asarray((1.0, 2.0)),
                1,
            )
        with self.assertRaises(smooth_paint.SmoothPaintError):
            smooth_paint.apply_variable_capsule_segments(
                smooth_paint.PaintNode(0),
                self.triangle,
                segments,
                np.asarray((np.nan,)),
                1,
            )

    def _capture(self, shape: str = "pressure_taper"):
        return smooth_paint_hotfix._SmoothStrokeCapture(
            camera=CameraState(),
            mapping=(0, 0, 20, 20, 20, 20),
            face_ids=np.zeros((20, 20), dtype=np.int32),
            pixels_per_unit=1.0,
            radius_mm=2.0,
            height_mm=100.0,
            protect_edges=False,
            edge_angle_degrees=45.0,
            selected_state=1,
            shape=shape,
            erase=False,
            feedback_color="#ffffff",
            feedback_radius_pixels=4.0,
        )

    def _editor_for_commit(self):
        editor = object.__new__(paint_gui.PaintEditorWindow)
        editor.window = _FakeWindow()
        editor.canvas = _FakeCanvas()
        editor._hotfix_pending_stroke_batch = None
        editor._hotfix_stroke_batch_serial = 0
        editor._hotfix_stroke_debounce_after = None
        editor._hotfix_stroke_debounce_ms = 300
        editor._hotfix_pending_feedback = []
        editor._stroke_faces = set()
        editor._stroke_erase = False
        editor._submit = lambda *_args, **_kwargs: None
        return editor

    def test_commit_freezes_same_fallback_profile_for_feedback_and_worker(self) -> None:
        editor = self._editor_for_commit()
        editor._drag_mode = "stroke"
        editor._hotfix_smooth_points = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]
        editor._hotfix_smooth_pressures = [None, None, None]
        editor._hotfix_smooth_capture = self._capture()
        feedback = {
            "token": 9,
            "points": editor._hotfix_smooth_points,
            "erase": False,
            "color": "#ffffff",
            "shape": "pressure_taper",
            "radius_pixels": 4.0,
            "radius_scales": [0.15, 0.15, 0.15],
        }
        editor._hotfix_active_feedback = feedback
        editor._hotfix_pending_feedback.append(feedback)

        editor._commit_active_stroke()

        batch = editor._hotfix_pending_stroke_batch
        self.assertIsNotNone(batch)
        request = batch._requests[0]
        self.assertEqual(request.width_source, "taper")
        self.assertEqual(request.radius_scales, (0.15, 1.0, 0.15))
        self.assertEqual(tuple(feedback["radius_scales"]), request.radius_scales)
        self.assertEqual(tuple(feedback["points"]), request.points)
        self.assertGreater(len(editor.canvas.lines), 0)

    def test_click_profile_maps_to_one_degenerate_worker_segment(self) -> None:
        points, scales = smooth_paint_hotfix._canvas_profile_to_render(
            ((5.0, 6.0),),
            (0.15,),
            (0, 0, 20, 20, 20, 20),
        )
        self.assertEqual(len(points), 2)
        self.assertEqual(scales, [0.15, 0.15])
        np.testing.assert_array_equal(points[0], points[1])

    def test_legacy_request_defaults_leave_round_and_marker_fixed(self) -> None:
        for shape in ("round", "marker"):
            request = smooth_paint_hotfix._SmoothStrokeRequest(
                ((0.0, 0.0), (1.0, 1.0)),
                self._capture(shape),
                1,
            )
            self.assertIsNone(request.radius_scales)
            self.assertEqual(request.width_source, "fixed")

    def test_real_editor_fallback_taper_reaches_final_adaptive_geometry(self) -> None:
        import tkinter as tk

        from source.fixed_app.test_gui_integration import _pump, _tetra_prepared
        from spectrum_mapper.models import AppSettings, GeometrySettings
        from spectrum_mapper.paint_gui import PaintEditorWindow

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        prepared = _tetra_prepared()
        editor = None
        try:
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

            def canvas_point(rx, ry):
                return (
                    int(round(left + (rx + 0.5) * width / render_width)),
                    int(round(top + (ry + 0.5) * height / render_height)),
                )

            points = None
            for row in sorted(
                range(ids.shape[0]),
                key=lambda y: int(np.count_nonzero(ids[y] >= 0)),
                reverse=True,
            ):
                visible = np.flatnonzero(ids[row] >= 0)
                if len(visible) < 20:
                    continue
                candidates = tuple(
                    canvas_point(int(visible[len(visible) * part // 4]), row)
                    for part in (1, 2, 3)
                )
                if all(editor._face_at(*point) >= 0 for point in candidates):
                    points = candidates
                    break
            self.assertIsNotNone(points, "no paintable taper segment was found")
            start, middle, end = points
            face = editor._face_at(*start)
            automatic = int(editor._session.effective_indices()[face])
            editor.tool_var.set("brush")
            editor.paint_state_var.set((automatic + 1) % 10)
            editor.edge_guard_var.set(False)
            editor.brush_radius_var.set(4.0)
            editor._hotfix_brush_shape_var.set("pressure_taper")
            revision_before = int(prepared._hotfix_tree_revision)

            editor._on_left_press(SimpleNamespace(x=start[0], y=start[1], state=0))
            editor._on_left_motion(SimpleNamespace(x=middle[0], y=middle[1], state=0x0100))
            editor._on_left_motion(SimpleNamespace(x=end[0], y=end[1], state=0x0100))
            editor._on_left_release(SimpleNamespace(x=end[0], y=end[1], state=0))

            request = editor._hotfix_pending_stroke_batch._requests[0]
            self.assertEqual(request.width_source, "taper")
            self.assertAlmostEqual(request.radius_scales[0], 0.15)
            self.assertAlmostEqual(request.radius_scales[-1], 0.15)
            self.assertGreater(max(request.radius_scales), 0.9)
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and editor._hotfix_pending_stroke_batch is None
                        and int(prepared._hotfix_tree_revision) > revision_before
                    ),
                ),
                editor.status_var.get(),
            )
            self.assertTrue(prepared._hotfix_subtriangle_paint)

            # A tap has only one Tk point.  It must still become one
            # zero-length variable-radius capsule rather than being discarded
            # by the polyline path.
            click_revision = int(prepared._hotfix_tree_revision)
            editor.paint_state_var.set((automatic + 2) % 10)
            editor._on_left_press(
                SimpleNamespace(x=middle[0], y=middle[1], state=0)
            )
            editor._on_left_release(
                SimpleNamespace(x=middle[0], y=middle[1], state=0)
            )
            click_request = editor._hotfix_pending_stroke_batch._requests[0]
            self.assertEqual(len(click_request.points), 1)
            self.assertEqual(click_request.radius_scales, (0.15,))
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and editor._hotfix_pending_stroke_batch is None
                        and int(prepared._hotfix_tree_revision) > click_revision
                    ),
                ),
                editor.status_var.get(),
            )
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
