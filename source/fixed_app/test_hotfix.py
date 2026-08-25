from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest import mock
from zipfile import ZipFile

import numpy as np
from PIL import Image

import spectrum_mapper_hotfix as hotfix
import slicer_safety
import smooth_paint
import smooth_paint_hotfix
from spectrum_mapper import engine, mixer
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import (
    ColorResult,
    MeshLevel,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
)
from spectrum_mapper.paint import PaintSession
from spectrum_mapper.renderer import CameraState


def tiny_level() -> MeshLevel:
    vertices = np.asarray(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float64
    )
    faces = np.asarray([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
    colors = np.asarray(
        [[1, 0, 0], [1, 0, 0], [0, 1, 0], [0, 1, 0]], dtype=np.float64
    )
    return MeshLevel(vertices, faces, colors, np.ones(2, dtype=np.float64), None)


def tiny_color_result() -> ColorResult:
    return ColorResult(
        tone_vertex_rgb=np.asarray(
            [[1, 0, 0], [1, 0, 0], [0, 1, 0], [0, 1, 0]], dtype=np.float64
        ),
        source_face_rgb=np.asarray([[1, 0, 0], [0, 1, 0]], dtype=np.float64),
        palette_indices=np.asarray([0, 9], dtype=np.int8),
        target_face_rgb=np.asarray([[0.05, 0.05, 0.05], [0.8, 0.7, 0.75]], dtype=np.float64),
        delta_e=np.asarray([1.0, 2.0], dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=np.asarray([1, 0, 0, 0, 0, 0, 0, 0, 0, 1]),
        palette_area_fractions=np.asarray([0.5, 0, 0, 0, 0, 0, 0, 0, 0, 0.5]),
        pink_area_fraction=0.5,
        manual_override_faces=0,
    )


def tiny_closed_level() -> MeshLevel:
    vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        dtype=np.int32,
    )
    colors = np.asarray(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 1.0, 1.0],
        ],
        dtype=np.float64,
    )
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=colors,
        areas_unit=engine.triangle_areas(vertices, faces),
        neighbors=engine.face_neighbors(faces, len(vertices)),
        face_part_ids=np.zeros(4, dtype=np.int16),
        part_names=("body",),
        part_keys=("part:body",),
        face_provenance=np.zeros(4, dtype=np.uint8),
    )


def tiny_closed_color_result() -> ColorResult:
    level = tiny_closed_level()
    palette_indices = np.asarray([0, 9, 1, 2], dtype=np.int8)
    counts = np.bincount(palette_indices, minlength=32).astype(np.int64)
    return ColorResult(
        tone_vertex_rgb=level.vertex_colors.copy(),
        source_face_rgb=level.vertex_colors[level.faces].mean(axis=1),
        palette_indices=palette_indices,
        target_face_rgb=level.vertex_colors[level.faces].mean(axis=1),
        delta_e=np.zeros(4, dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=counts,
        palette_area_fractions=counts.astype(np.float64) / 4.0,
        pink_area_fraction=0.25,
        manual_override_faces=0,
    )


def tiny_closed_prepared(path: Path | None = None) -> PreparedGeometry:
    level = tiny_closed_level()
    source_path = Path("tiny.obj") if path is None else Path(path)
    source = ObjAsset(
        source_path,
        "0" * 64,
        1,
        level.vertices_unit.copy(),
        level.vertex_colors.copy(),
        level.faces.copy(),
        len(level.vertices_unit),
        len(level.faces),
        [],
        part_names=level.part_names,
        part_keys=level.part_keys,
        face_part_ids=level.face_part_ids.copy(),
        part_face_counts=(len(level.faces),),
        part_vertex_counts=(len(level.vertices_unit),),
    )
    area = float(level.areas_unit.sum())
    return PreparedGeometry(
        source,
        level,
        level,
        len(level.vertices_unit),
        len(level.faces),
        0,
        0,
        {
            "watertight": True,
            "boundary_edges": 0,
            "nonmanifold_edges": 0,
            "inconsistent_winding_edges": 0,
        },
        area,
        1.0 / 6.0,
        area,
        1.0 / 6.0,
        np.asarray([1.0, 1.0, 1.0]),
        [],
        part_names=level.part_names,
        part_keys=level.part_keys,
        assembly={"all_parts_watertight": True},
    )


class HotfixTests(unittest.TestCase):
    def test_only_converted_preview_is_manual_editing_click_target(self):
        class Canvas:
            def winfo_width(self):
                return 900

            def winfo_height(self):
                return 600

            def create_rectangle(self, *args, **kwargs):
                return (args, kwargs)

            def create_text(self, *args, **kwargs):
                return (args, kwargs)

        canvas = Canvas()
        dummy = SimpleNamespace(
            preview_canvas=canvas,
            prepared=object(),
            i18n=Translator("ja"),
        )
        with mock.patch.object(
            hotfix, "_cache_large_reference_for_draw", return_value=None
        ):
            hotfix._comparison_draw_fixed(dummy)

        # 900 px canvas: the sole target box starts at the third panel.
        self.assertEqual(len(dummy._hotfix_paint_panel_boxes), 1)
        left, top, right, bottom = dummy._hotfix_paint_panel_boxes[0]
        self.assertGreater(left, 900 / 2)
        self.assertEqual(top, 48)

        status = mock.Mock()
        open_editor = mock.Mock()
        root = SimpleNamespace(after_idle=lambda callback: callback())
        dummy.status_var = status
        dummy.root = root
        dummy.eyedropper_active = False
        dummy._open_paint_editor = open_editor
        dummy._hotfix_editor_open_pending = False

        with mock.patch.object(hotfix, "_original_canvas_click") as original:
            # Clicking the middle/source panel follows its normal read-only path.
            hotfix._canvas_click_fixed(
                dummy, SimpleNamespace(x=int(left - 30), y=int((top + bottom) / 2))
            )
            original.assert_called_once()
            open_editor.assert_not_called()

            # Clicking the third/converted panel opens Manual Editing.
            hotfix._canvas_click_fixed(
                dummy, SimpleNamespace(x=int((left + right) / 2), y=int((top + bottom) / 2))
            )
            open_editor.assert_called_once()
            status.set.assert_called_with("マニュアル修正を開いています…")

    def test_windows_numlock_is_not_mistaken_for_alt(self):
        self.assertEqual(
            hotfix._normalized_left_press_state(0x0008, windows=True, alt_down=False),
            0,
        )
        self.assertEqual(
            hotfix._normalized_left_press_state(0x0009, windows=True, alt_down=False),
            1,
        )
        self.assertEqual(
            hotfix._normalized_left_press_state(0x0008, windows=True, alt_down=True),
            8,
        )
        self.assertEqual(
            hotfix._normalized_left_press_state(0x20000, windows=True, alt_down=None)
            & 8,
            8,
        )

    def test_numlock_click_reaches_brush_branch(self):
        class Variable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        dummy = SimpleNamespace(
            _close_requested=False,
            reference_mapping=None,
            _point_inside=lambda _event, _mapping: False,
            _face_at=lambda _x, _y: 1,
            effective_indices=np.asarray([2, 3], dtype=np.int8),
            paint_state_var=Variable(6),
            tool_var=Variable("brush"),
            status_var=Variable(""),
        )
        event = SimpleNamespace(x=20, y=30, state=0x0008)
        with mock.patch.object(hotfix, "_windows_alt_key_down", return_value=False):
            hotfix._on_left_press_fixed(dummy, event)
        self.assertEqual(dummy._drag_mode, "stroke")
        self.assertEqual(dummy._stroke_faces, [1])
        self.assertEqual(dummy.paint_state_var.get(), 6)

    def test_windows_alt_click_remains_3d_eyedropper(self):
        class Variable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        dummy = SimpleNamespace(
            _close_requested=False,
            reference_mapping=None,
            _point_inside=lambda _event, _mapping: False,
            _face_at=lambda _x, _y: 1,
            effective_indices=np.asarray([2, 7], dtype=np.int8),
            paint_state_var=Variable(1),
            tool_var=Variable("brush"),
            status_var=Variable(""),
        )
        hotfix._on_left_press_fixed(
            dummy, SimpleNamespace(x=20, y=30, state=0x20000)
        )
        self.assertEqual(dummy.paint_state_var.get(), 7)
        self.assertFalse(hasattr(dummy, "_drag_mode"))

    def test_color_only_render_keeps_valid_face_picker(self):
        camera = CameraState()
        dummy = SimpleNamespace(
            target_mapping=(10, 20, 100, 100, 2, 2),
            face_ids=np.asarray([[4, 5], [6, 7]], dtype=np.int32),
            _render_dirty=True,
            _hotfix_pick_camera=camera,
            camera=camera,
        )
        self.assertEqual(hotfix._face_at_fixed(dummy, 80, 30), 5)

    def test_color_only_request_restores_outline_from_exact_cached_ids(self):
        camera = CameraState()
        cached_ids = np.full((7, 8), -1, dtype=np.int32)
        cached_ids[1:6, 1:4] = 0
        cached_ids[1:6, 4:7] = 1
        base = Image.new("RGB", (8, 7), (20, 30, 40))
        base.info["adaptive"] = "kept"
        render_calls = []

        class Backend:
            _active_part_id = 0
            _active_part_accent = (10, 220, 250)
            _active_part_outline_thickness = 1
            # Real legacy/single-part levels keep an empty raw sentinel while
            # the renderer owns the authoritative normalized table.
            _face_part_ids = np.asarray((0, 1), dtype=np.int16)

            def render(self, _colors, **kwargs):
                render_calls.append(dict(kwargs))
                return hotfix.renderer.InteractiveRenderFrame(
                    source=None,
                    target=base,
                    face_ids=None,
                    camera=kwargs["camera"],
                    pixels_per_unit=1.0,
                )

        completed = []
        backend = Backend()
        dummy = SimpleNamespace(
            _render_after="scheduled",
            _job_running=False,
            _pending_render=False,
            camera=camera,
            face_ids=cached_ids,
            _hotfix_pick_camera=camera,
            _renderer=backend,
            _display_colors=object(),
            level=SimpleNamespace(face_part_ids=np.empty(0, dtype=np.int16)),
            _submit=lambda kind, work: completed.append((kind, work())),
        )

        hotfix._request_render_fixed(dummy)

        self.assertFalse(render_calls[0]["render_face_ids"])
        self.assertEqual(len(completed), 1)
        _camera, frame = completed[0][1]
        self.assertIsNone(frame.face_ids)
        self.assertIs(dummy.face_ids, cached_ids)
        pixels = np.asarray(frame.target)
        np.testing.assert_array_equal(pixels[3, 3], (10, 220, 250))
        np.testing.assert_array_equal(pixels[3, 2], (20, 30, 40))
        self.assertEqual(frame.target.info["adaptive"], "kept")

    def test_changed_camera_rejects_stale_face_picker(self):
        dummy = SimpleNamespace(
            target_mapping=(0, 0, 100, 100, 2, 2),
            face_ids=np.asarray([[1, 2], [3, 4]], dtype=np.int32),
            _render_dirty=True,
            _hotfix_pick_camera=CameraState(yaw_degrees=0),
            camera=CameraState(yaw_degrees=10),
        )
        self.assertEqual(hotfix._face_at_fixed(dummy, 25, 25), -1)

    def test_completed_camera_render_restores_face_picker(self):
        camera = CameraState(yaw_degrees=10)
        dummy = SimpleNamespace(
            target_mapping=(0, 0, 100, 100, 2, 2),
            face_ids=np.asarray([[1, 2], [3, 4]], dtype=np.int32),
            _render_dirty=False,
            _hotfix_pick_camera=CameraState(yaw_degrees=0),
            camera=camera,
        )
        self.assertEqual(hotfix._face_at_fixed(dummy, 25, 25), 1)
        self.assertEqual(dummy._hotfix_pick_camera, camera)

    def test_orca_234_layer_cadence_is_used_for_mix_preview(self):
        self.assertAlmostEqual(hotfix._orca_effective_mix_ratio(0.60), 2.0 / 3.0)
        first = np.asarray([17, 17, 17], dtype=np.uint8)
        second = np.asarray([192, 192, 192], dtype=np.uint8)
        expected = hotfix._original_mix_rgb8(first, second, 2.0 / 3.0)
        np.testing.assert_array_equal(mixer.mix_rgb8(first, second, 0.60), expected)

    def test_same_visible_color_is_a_no_op(self):
        level = tiny_level()
        session = PaintSession(level, 100.0, np.asarray([2, 2], dtype=np.int8))
        changed = session.fill(0, 2)
        self.assertEqual(len(changed), 0)
        np.testing.assert_array_equal(session.overrides, [-1, -1])

    def test_normal_fill_keeps_legacy_connected_fill_override_compatible(self):
        class LegacyConnectedFillSession(PaintSession):
            def connected_fill_faces(self, seed_face):
                return super().connected_fill_faces(seed_face)

        level = tiny_level()
        session = LegacyConnectedFillSession(
            level,
            100.0,
            np.asarray([0, 0], dtype=np.int8),
        )

        changed = session.fill(0, 2)

        np.testing.assert_array_equal(changed, [0, 1])
        np.testing.assert_array_equal(session.overrides, [2, 2])

    def test_incremental_edit_matches_full_color_recalculation(self):
        level = tiny_level()
        palette = PaletteSettings()
        automatic = engine.apply_palette_overrides(
            level,
            100.0,
            palette,
            tiny_color_result(),
            np.full(2, -1, dtype=np.int8),
        )
        session = PaintSession(level, 100.0, automatic.palette_indices)
        session.overrides[0] = 3
        expected = engine.apply_palette_overrides(
            level, 100.0, palette, automatic, session.overrides
        )
        dummy = SimpleNamespace(
            _session=session,
            _auto_colors=automatic,
            _display_colors=automatic,
            level=level,
            settings=SimpleNamespace(
                geometry=SimpleNamespace(height_mm=100.0), palette=palette
            ),
            _renderer=None,
            _worker_snapshot=lambda frame, message, changed: (message, changed),
        )
        hotfix._worker_refresh_after_edit_fixed(dummy, "edited", 1)
        actual = dummy._display_colors
        for field in (
            "palette_indices",
            "target_face_rgb",
            "palette_face_counts",
            "palette_area_fractions",
        ):
            np.testing.assert_array_equal(getattr(actual, field), getattr(expected, field))
        np.testing.assert_allclose(actual.delta_e, expected.delta_e, rtol=0, atol=1e-12)
        self.assertEqual(actual.manual_override_faces, 1)

    def test_repeated_incremental_edits_never_restore_an_older_face_color(self):
        level = tiny_level()
        palette = PaletteSettings()
        automatic = engine.apply_palette_overrides(
            level,
            100.0,
            palette,
            tiny_color_result(),
            np.full(2, -1, dtype=np.int8),
        )
        session = PaintSession(level, 100.0, automatic.palette_indices)
        dummy = SimpleNamespace(
            _session=session,
            _auto_colors=automatic,
            _display_colors=automatic,
            level=level,
            settings=SimpleNamespace(
                geometry=SimpleNamespace(height_mm=100.0), palette=palette
            ),
            _renderer=None,
            _worker_snapshot=lambda frame, message, changed: (message, changed),
        )

        for state in (3, 7, 1, 9, 4):
            session.overrides[0] = state
            hotfix._worker_refresh_after_edit_fixed(dummy, "edited", 1)
            expected = engine.apply_palette_overrides(
                level, 100.0, palette, automatic, session.overrides
            )
            self.assertEqual(int(dummy._display_colors.palette_indices[0]), state)
            np.testing.assert_array_equal(
                dummy._display_colors.target_face_rgb,
                expected.target_face_rgb,
            )

    def test_adaptive_overlay_cache_holds_exact_frame_objects(self):
        first_image = Image.new("RGB", (2, 2), "black")
        second_image = Image.new("RGB", (2, 2), "white")
        first_ids = np.zeros((2, 2), dtype=np.int32)
        second_ids = np.zeros((2, 2), dtype=np.int32)
        camera = CameraState()
        composite = Image.new("RGB", (2, 2), "red")
        cached = (first_image, first_ids, camera, 12, composite)

        self.assertTrue(
            smooth_paint_hotfix._overlay_cache_matches(
                cached, first_image, first_ids, camera, 12
            )
        )
        self.assertFalse(
            smooth_paint_hotfix._overlay_cache_matches(
                cached, second_image, first_ids, camera, 12
            )
        )
        self.assertFalse(
            smooth_paint_hotfix._overlay_cache_matches(
                cached, first_image, second_ids, camera, 12
            )
        )

    def test_gpu_marked_frame_is_not_composited_twice(self):
        image = Image.new("RGB", (2, 2), "black")
        image.info["tripo_spectrum_adaptive_gpu_revision"] = 17
        tree = smooth_paint.PaintNode(0)
        tree.split_four()
        result = smooth_paint_hotfix.compose_target_image(
            image,
            None,
            {0: tree},
            camera=None,
            face_ids=np.zeros((2, 2), dtype=np.int32),
            palette=None,
            renderer_module=None,
            mixer_module=None,
        )
        self.assertIs(result, image)
        self.assertEqual(smooth_paint_hotfix._gpu_overlay_revision(image), 17)

    def test_stroke_feedback_waits_for_exact_post_commit_render(self):
        old_image = Image.new("RGB", (2, 2), "black")
        fresh_image = Image.new("RGB", (2, 2), "white")
        entry = {
            "token": 41,
            "points": [(1.0, 1.0), (2.0, 2.0)],
            "erase": False,
            "committed": False,
            "base_image": None,
            "revision": None,
        }
        pending = [entry]

        # A render that was already in flight while the user was drawing must
        # not make the visible feedback disappear.
        self.assertFalse(
            smooth_paint_hotfix._feedback_has_final_frame(
                entry, image=old_image, revision=8, exact_frame=True
            )
        )
        self.assertTrue(
            smooth_paint_hotfix._mark_feedback_committed(
                pending, 41, base_image=old_image, revision=9
            )
        )
        # Consuming the edit snapshot alone is not enough: its pixels still
        # belong to the previous colour state.
        self.assertFalse(
            smooth_paint_hotfix._feedback_has_final_frame(
                entry, image=old_image, revision=9, exact_frame=True
            )
        )
        self.assertFalse(
            smooth_paint_hotfix._feedback_has_final_frame(
                entry, image=fresh_image, revision=8, exact_frame=True
            )
        )
        self.assertFalse(
            smooth_paint_hotfix._feedback_has_final_frame(
                entry, image=fresh_image, revision=9, exact_frame=False
            )
        )
        self.assertTrue(
            smooth_paint_hotfix._feedback_has_final_frame(
                entry, image=fresh_image, revision=9, exact_frame=True
            )
        )

    def test_stroke_batch_stress_keeps_fifo_and_contains_one_bad_stroke(self):
        ids = np.zeros((2, 2), dtype=np.int32)
        capture = smooth_paint_hotfix._SmoothStrokeCapture(
            camera=CameraState(),
            mapping=(0, 0, 2, 2, 2, 2),
            face_ids=ids,
            pixels_per_unit=1.0,
            radius_mm=2.0,
            height_mm=100.0,
            protect_edges=True,
            edge_angle_degrees=45.0,
            selected_state=3,
            shape="round",
            erase=False,
            feedback_color="#ffffff",
            feedback_radius_pixels=2.0,
        )
        batch = smooth_paint_hotfix._StrokeBatch(17)
        requests = [
            smooth_paint_hotfix._SmoothStrokeRequest(
                ((0.0, 0.0), (1.0, 1.0)), capture, token
            )
            for token in range(500)
        ]
        for request in requests:
            self.assertTrue(batch.append(request))
        batch.seal()
        self.assertFalse(batch.append(requests[0]))

        revision = 0

        def process(request):
            nonlocal revision
            if request.feedback_token == 271:
                raise ValueError("synthetic bad stroke")
            revision += 1
            return smooth_paint_hotfix._SmoothStrokeResult(
                request.feedback_token, revision, 1, "ok"
            )

        results = smooth_paint_hotfix._drain_stroke_batch(
            batch, process, lambda: revision
        )
        self.assertEqual(
            [result.feedback_token for result in results], list(range(500))
        )
        self.assertEqual(sum(result.error is not None for result in results), 1)
        self.assertEqual(results[271].revision, 271)
        self.assertEqual(revision, 499)

    def test_rapid_releases_wait_for_one_debounced_worker_submit(self):
        from spectrum_mapper import paint_gui

        class FakeWindow:
            def __init__(self):
                self.serial = 0
                self.callbacks = {}
                self.cancelled = []

            def after(self, _delay, callback):
                self.serial += 1
                token = f"after-{self.serial}"
                self.callbacks[token] = callback
                return token

            def after_cancel(self, token):
                self.cancelled.append(token)
                self.callbacks.pop(token, None)

        ids = np.zeros((4, 4), dtype=np.int32)
        capture = smooth_paint_hotfix._SmoothStrokeCapture(
            camera=CameraState(),
            mapping=(0, 0, 4, 4, 4, 4),
            face_ids=ids,
            pixels_per_unit=1.0,
            radius_mm=2.0,
            height_mm=100.0,
            protect_edges=False,
            edge_angle_degrees=45.0,
            selected_state=2,
            shape="marker",
            erase=False,
            feedback_color="#ffffff",
            feedback_radius_pixels=2.0,
        )
        editor = object.__new__(paint_gui.PaintEditorWindow)
        editor.window = FakeWindow()
        editor._hotfix_pending_stroke_batch = None
        editor._hotfix_stroke_batch_serial = 0
        editor._hotfix_stroke_debounce_after = None
        editor._hotfix_stroke_debounce_ms = 300
        editor._stroke_faces = set()
        editor._stroke_erase = False
        submitted = []
        editor._submit = lambda kind, work, **_kwargs: submitted.append((kind, work))

        for token in range(100):
            editor._drag_mode = "stroke"
            editor._hotfix_smooth_points = [
                (float(token), 0.0),
                (float(token) + 1.0, 1.0),
            ]
            editor._hotfix_smooth_capture = capture
            editor._hotfix_active_feedback = {"token": token}
            editor._commit_active_stroke()

        self.assertEqual(submitted, [])
        self.assertEqual(len(editor.window.callbacks), 1)
        self.assertEqual(len(editor.window.cancelled), 99)
        self.assertIs(capture.face_ids, ids)

        callback = next(iter(editor.window.callbacks.values()))
        callback()
        self.assertEqual([kind for kind, _work in submitted], ["edit"])
        self.assertIsNone(editor._hotfix_pending_stroke_batch)

    def test_real_editor_batches_six_strokes_into_one_refresh_and_render(self):
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
        geometry = GeometrySettings(
            height_mm=50.0,
            target_faces=1_000,
            preview_faces=1_000,
            up_axis="Y",
            min_component_faces=1,
        )
        editor = None
        try:
            editor = PaintEditorWindow(
                root,
                prepared,
                AppSettings(geometry=geometry),
                None,
                None,
                lambda _values: None,
            )
            editor.window.geometry("1000x760+40+40")
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.face_ids is not None
                        and editor.target_mapping is not None
                        and not editor._job_running
                        and not editor._render_dirty
                    ),
                ),
                editor.status_var.get(),
            )
            ids = np.asarray(editor.face_ids)
            left, top, width, height, render_width, render_height = (
                editor.target_mapping
            )
            render_x = np.minimum(
                render_width - 1,
                np.arange(width, dtype=np.int64) * render_width // width,
            )
            render_y = np.minimum(
                render_height - 1,
                np.arange(height, dtype=np.int64) * render_height // height,
            )
            canvas_ids = ids[np.ix_(render_y, render_x)]
            best_y = max(
                range(canvas_ids.shape[0]),
                key=lambda y: int(np.count_nonzero(canvas_ids[y] >= 0)),
            )
            visible_x = np.flatnonzero(canvas_ids[best_y] >= 0)
            self.assertGreater(len(visible_x), 18)
            start = (
                left + int(visible_x[len(visible_x) * 2 // 5]),
                top + best_y,
            )
            end = (
                left + int(visible_x[len(visible_x) * 3 // 5]),
                top + best_y,
            )
            face = editor._face_at(*start)
            self.assertGreaterEqual(face, 0)
            automatic = int(editor._session.effective_indices()[face])
            states = ((automatic + 1) % 10, (automatic + 2) % 10)
            editor.tool_var.set("brush")
            editor.edge_guard_var.set(False)
            editor.brush_radius_var.set(2.0)
            editor._hotfix_brush_shape_var.set("round")

            refresh_calls = []
            original_refresh = editor._worker_refresh_after_edit

            def counted_refresh(message, changed):
                refresh_calls.append((message, changed))
                return original_refresh(message, changed)

            editor._worker_refresh_after_edit = counted_refresh
            render_calls = []
            original_render = editor._renderer.render

            def counted_render(*args, **kwargs):
                render_calls.append(dict(kwargs))
                return original_render(*args, **kwargs)

            editor._renderer.render = counted_render
            undo_before = len(editor._session._undo)
            revision_before = int(prepared._hotfix_tree_revision)

            for stroke in range(6):
                editor.paint_state_var.set(states[stroke % 2])
                editor._on_left_press(
                    SimpleNamespace(x=start[0], y=start[1], state=0x0008)
                )
                editor._on_left_motion(
                    SimpleNamespace(x=end[0], y=end[1], state=0x0108)
                )
                editor._on_left_release(
                    SimpleNamespace(x=end[0], y=end[1], state=0x0008)
                )

            self.assertFalse(editor._job_running)
            self.assertEqual(len(editor._hotfix_pending_feedback), 6)
            self.assertEqual(int(prepared._hotfix_tree_revision), revision_before)
            self.assertEqual(refresh_calls, [])
            self.assertEqual(render_calls, [])

            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and editor._hotfix_pending_stroke_batch is None
                        and not editor._hotfix_pending_feedback
                        and editor.target_image.info.get(
                            "tripo_spectrum_adaptive_gpu_revision"
                        )
                        == int(prepared._hotfix_tree_revision)
                    ),
                ),
                editor.status_var.get(),
            )
            self.assertEqual(len(refresh_calls), 1)
            self.assertEqual(len(render_calls), 1)
            self.assertFalse(render_calls[0].get("render_face_ids", False))
            self.assertEqual(
                int(prepared._hotfix_tree_revision) - revision_before, 6
            )
            self.assertEqual(len(editor._session._undo) - undo_before, 6)
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

    def test_close_flushes_every_debounced_stroke_before_destroying_editor(self):
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
                )
            )
            ids = np.asarray(editor.face_ids)
            left, top, width, height, render_width, render_height = (
                editor.target_mapping
            )

            def point(rx, ry):
                return (
                    int(round(left + (rx + 0.5) * width / render_width)),
                    int(round(top + (ry + 0.5) * height / render_height)),
                )

            # Rendering is commonly downsampled to the canvas.  A raw render
            # pixel centre can therefore round onto a canvas pixel whose
            # inverse pick lands on the neighbouring render row.  Choose the
            # widest visible rows first, but require both displayed endpoints
            # to be accepted by the editor's actual picker.
            start = end = None
            rows = sorted(
                range(ids.shape[0]),
                key=lambda y: int(np.count_nonzero(ids[y] >= 0)),
                reverse=True,
            )
            for row in rows:
                visible_x = np.flatnonzero(ids[row] >= 0)
                if len(visible_x) < 2:
                    continue
                candidate_start = point(
                    int(visible_x[len(visible_x) * 2 // 5]), row
                )
                candidate_end = point(
                    int(visible_x[len(visible_x) * 3 // 5]), row
                )
                if (
                    editor._face_at(*candidate_start) >= 0
                    and editor._face_at(*candidate_end) >= 0
                ):
                    start, end = candidate_start, candidate_end
                    break
            self.assertIsNotNone(start, "no paintable canvas segment was found")
            self.assertIsNotNone(end, "no paintable canvas segment was found")
            face = editor._face_at(*start)
            self.assertGreaterEqual(face, 0)
            automatic = int(editor._session.effective_indices()[face])
            editor.tool_var.set("brush")
            editor.edge_guard_var.set(False)
            editor.brush_radius_var.set(2.0)
            for stroke in range(3):
                editor.paint_state_var.set((automatic + stroke + 1) % 10)
                editor._on_left_press(
                    SimpleNamespace(x=start[0], y=start[1], state=0x0008)
                )
                editor._on_left_motion(
                    SimpleNamespace(x=end[0], y=end[1], state=0x0108)
                )
                editor._on_left_release(
                    SimpleNamespace(x=end[0], y=end[1], state=0x0008)
                )
            self.assertEqual(int(prepared._hotfix_tree_revision), 0)
            self.assertEqual(len(editor._hotfix_pending_feedback), 3)

            closed = []
            editor.close(lambda: closed.append(True))
            self.assertTrue(
                _pump(root, lambda: not editor.window.winfo_exists(), 10.0)
            )
            self.assertEqual(closed, [True])
            self.assertEqual(int(prepared._hotfix_tree_revision), 3)
            self.assertIsNone(editor._renderer)
        finally:
            if editor is not None and editor.window.winfo_exists():
                try:
                    editor.close()
                    _pump(root, lambda: not editor.window.winfo_exists(), 5.0)
                except Exception:
                    pass
            try:
                root.destroy()
            except Exception:
                pass

    def test_undo_is_ordered_after_unsubmitted_stroke_batch(self):
        from spectrum_mapper import paint_gui

        class FakeWindow:
            def after(self, _delay, callback):
                self.callback = callback
                return "debounce"

            def after_cancel(self, _token):
                return None

        capture = smooth_paint_hotfix._SmoothStrokeCapture(
            camera=CameraState(),
            mapping=(0, 0, 2, 2, 2, 2),
            face_ids=np.zeros((2, 2), dtype=np.int32),
            pixels_per_unit=1.0,
            radius_mm=2.0,
            height_mm=100.0,
            protect_edges=False,
            edge_angle_degrees=45.0,
            selected_state=2,
            shape="round",
            erase=False,
            feedback_color="#ffffff",
            feedback_radius_pixels=2.0,
        )
        editor = object.__new__(paint_gui.PaintEditorWindow)
        editor.window = FakeWindow()
        editor._hotfix_pending_stroke_batch = None
        editor._hotfix_stroke_batch_serial = 0
        editor._hotfix_stroke_debounce_after = None
        editor._hotfix_stroke_debounce_ms = 300
        editor._drag_mode = "stroke"
        editor._stroke_faces = set()
        editor._stroke_erase = False
        editor._hotfix_smooth_points = [(0.0, 0.0), (1.0, 1.0)]
        editor._hotfix_smooth_capture = capture
        editor._hotfix_active_feedback = {"token": 1}
        submitted = []
        editor._submit = lambda kind, work, **_kwargs: submitted.append((kind, work))

        editor._undo()
        self.assertEqual([kind for kind, _work in submitted], ["edit", "edit"])
        self.assertIsNone(editor._hotfix_pending_stroke_batch)

    def test_batch_snapshot_defers_render_while_next_stroke_is_pending(self):
        from spectrum_mapper import paint_gui

        class Variable:
            def set(self, _value):
                return None

        editor = object.__new__(paint_gui.PaintEditorWindow)
        editor._hotfix_pending_feedback = []
        editor._hotfix_pending_stroke_batch = object()
        editor._hotfix_tree_owner = SimpleNamespace(_hotfix_tree_revision=4)
        editor._hotfix_deferred_paint_render = False
        editor._rotation_hotfix_force_final = False
        editor._drag_mode = None
        editor._close_requested = False
        editor.target_image = Image.new("RGB", (2, 2), "black")
        editor.edit_count_var = Variable()
        editor.status_var = Variable()
        editor.on_overrides_changed = lambda _overrides: None
        render_calls = []
        editor._schedule_render = (
            lambda *args, **kwargs: render_calls.append((args, kwargs))
        )
        snapshot = {
            "frame": None,
            "_hotfix_smooth_commits": (),
            "_hotfix_smooth_tree_revision": 4,
        }

        editor._consume_snapshot(snapshot)
        self.assertEqual(render_calls, [])
        self.assertTrue(editor._hotfix_deferred_paint_render)
        self.assertFalse(editor._rotation_hotfix_force_final)

        editor._hotfix_pending_stroke_batch = None
        editor._consume_snapshot(snapshot)
        self.assertEqual(len(render_calls), 1)
        self.assertFalse(editor._hotfix_deferred_paint_render)
        self.assertFalse(editor._rotation_hotfix_force_final)

    def test_large_sparse_fill_matches_full_connected_region(self):
        count = 25_000
        neighbors = np.full((count, 2), -1, dtype=np.int32)
        neighbors[1:, 0] = np.arange(count - 1, dtype=np.int32)
        neighbors[:-1, 1] = np.arange(1, count, dtype=np.int32)
        labels = np.zeros(count, dtype=np.int8)
        labels[12_500:] = 1
        dummy = SimpleNamespace(
            faces=np.zeros((count, 3), dtype=np.int32),
            neighbors=neighbors,
            effective_indices=lambda: labels,
        )
        started = time.perf_counter()
        selected = hotfix._connected_fill_faces_fixed(dummy, 0)
        elapsed = time.perf_counter() - started
        np.testing.assert_array_equal(np.sort(selected), np.arange(12_500))
        self.assertLess(elapsed, 2.0)

    def test_large_sparse_fill_cannot_cross_active_part_mask(self):
        count = 25_000
        neighbors = np.full((count, 2), -1, dtype=np.int32)
        neighbors[1:, 0] = np.arange(count - 1, dtype=np.int32)
        neighbors[:-1, 1] = np.arange(1, count, dtype=np.int32)
        labels = np.zeros(count, dtype=np.int8)
        allowed = np.zeros(count, dtype=bool)
        allowed[:4_000] = True
        dummy = SimpleNamespace(
            faces=np.zeros((count, 3), dtype=np.int32),
            neighbors=neighbors,
            allowed_face_mask=allowed,
            effective_indices=lambda: labels,
        )

        selected = hotfix._connected_fill_faces_fixed(dummy, 0)

        np.testing.assert_array_equal(np.sort(selected), np.arange(4_000))

    def test_large_sparse_fill_uses_flat_visible_state_connectivity(self):
        count = 25_000
        neighbors = np.full((count, 2), -1, dtype=np.int32)
        neighbors[1:, 0] = np.arange(count - 1, dtype=np.int32)
        neighbors[:-1, 1] = np.arange(1, count, dtype=np.int32)
        labels = np.zeros(count, dtype=np.int8)
        labels[8_000:16_000] = 5
        labels[16_000:] = 2
        state_map = np.arange(mixer.PALETTE_STATE_COUNT, dtype=np.int8)
        state_map[5] = 0
        dummy = SimpleNamespace(
            faces=np.zeros((count, 3), dtype=np.int32),
            neighbors=neighbors,
            allowed_face_mask=np.ones(count, dtype=bool),
            effective_indices=lambda: labels,
        )

        selected = hotfix._connected_fill_faces_fixed(
            dummy,
            0,
            connectivity_state_map=state_map,
        )

        np.testing.assert_array_equal(np.sort(selected), np.arange(16_000))

    def test_3mf_contains_portable_and_orca_materials(self):
        prepared = tiny_closed_prepared()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "tiny.3mf"
            validation = hotfix._write_3mf_atomic_fixed(
                destination,
                prepared,
                tiny_closed_color_result(),
                100.0,
                PaletteSettings(),
            )
            with ZipFile(destination) as archive:
                model_settings = archive.read("Metadata/model_settings.config")
                project_settings = json.loads(
                    archive.read("Metadata/project_settings.config").decode("utf-8")
                )
            self.assertTrue(validation["portable_basematerials"])
            self.assertTrue(validation["portable_material_faces_match"])
            self.assertTrue(validation["portable_and_orca_states_match"])
            self.assertTrue(validation["portable_material_colors_match"])
            self.assertTrue(validation["snapmaker_u1_metadata"])
            self.assertTrue(validation["snapmaker_u1_print_settings"])
            self.assertTrue(validation["snapmaker_u1_layer_height_008"])
            self.assertTrue(validation["snapmaker_u1_transition_settings"])
            self.assertTrue(validation["full_spectrum_stable_cadence_settings"])
            self.assertTrue(validation["generic_pla_filament_settings"])
            self.assertTrue(validation["project_support_disabled"])
            self.assertTrue(validation["support_override_disabled"])
            self.assertTrue(validation["project_settings_line_width_safe"])
            self.assertTrue(validation["slicer_safe_project_defaults"])
            self.assertEqual(validation["project_settings_diagnostics"], [])
            self.assertEqual(validation["project_settings_error_count"], 0)
            self.assertEqual(validation["project_settings_warning_count"], 0)
            self.assertEqual(validation["snapmaker_orca_import_mode"], "open_as_project")
            self.assertEqual(validation["snapmaker_orca_tested_version"], "2.3.5")
            self.assertEqual(validation["hotfix_version"], "0.8beta")
            self.assertEqual(validation["portable_material_state_counts"][0], 1)
            self.assertEqual(validation["portable_material_state_counts"][9], 1)
            self.assertNotIn(b'key="enable_support" value="1"', model_settings)
            self.assertNotIn(b'key="enable_support"', model_settings)

            self.assertNotIn("enable_support", project_settings)
            self.assertEqual(
                project_settings["print_settings_id"],
                "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)",
            )
            self.assertEqual(project_settings["layer_height"], "0.08")
            self.assertEqual(project_settings["initial_layer_print_height"], "0.2")
            self.assertEqual(project_settings["adaptive_layer_height"], "0")
            self.assertEqual(
                project_settings["filament_settings_id"],
                ["Generic PLA"] * 4,
            )
            for key, expected in (
                engine.FULL_SPECTRUM_STABLE_CADENCE_SETTINGS.items()
            ):
                self.assertEqual(project_settings[key], expected)
            for key, expected in (
                engine.SNAPMAKER_U1_008_TRANSITION_SETTINGS.items()
            ):
                self.assertEqual(project_settings[key], expected)

            guide = Path(folder) / "tiny_使い方.txt"
            hotfix._write_guide_fixed(guide, destination, 100.0, PaletteSettings())
            instructions = guide.read_text(encoding="utf-8")
            self.assertIn("必ず『プロジェクトとして開く』", instructions)
            self.assertIn("2.3.5で確認済み", instructions)
            self.assertIn("リブ型プライムタワー", instructions)
            self.assertIn("Local Z", instructions)

    def test_3mf_validator_rejects_drifted_full_spectrum_or_transition_setting(self):
        prepared = tiny_closed_prepared()
        palette = PaletteSettings()
        for key, unsafe_value, expected_label in (
            ("dithering_local_z_mode", "1", "Full Spectrum固定レイヤー設定"),
            ("enable_prime_tower", "0", "U1 0.08 mmフィラメント切替設定"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / f"drift-{key}.3mf"
                hotfix._write_3mf_atomic_fixed(
                    destination,
                    prepared,
                    tiny_closed_color_result(),
                    100.0,
                    palette,
                )
                with ZipFile(destination, "r") as archive:
                    members = {
                        info.filename: archive.read(info.filename)
                        for info in archive.infolist()
                    }
                project = json.loads(
                    members["Metadata/project_settings.config"].decode("utf-8")
                )
                definitions = project["mixed_filament_definitions"]
                project[key] = unsafe_value
                members["Metadata/project_settings.config"] = json.dumps(
                    project, ensure_ascii=False, indent=2
                ).encode("utf-8")
                with ZipFile(destination, "w") as archive:
                    for name, payload in members.items():
                        archive.writestr(name, payload)

                with self.assertRaisesRegex(engine.EngineError, expected_label):
                    hotfix._original_validate_3mf(
                        destination,
                        4,
                        4,
                        ["#111111", "#FFFFFF", "#E32636", "#7A4A32"],
                        definitions,
                        1,
                    )

    def test_3mf_portable_material_count_follows_24_or_32_selection(self):
        prepared = tiny_closed_prepared()
        with tempfile.TemporaryDirectory() as folder:
            for count in (24, 32):
                with self.subTest(count=count):
                    palette = PaletteSettings(
                        palette_state_count=count,
                        enabled_states=[True] * count,
                    )
                    destination = Path(folder) / f"tiny-{count}.3mf"
                    validation = hotfix._write_3mf_atomic_fixed(
                        destination,
                        prepared,
                        tiny_closed_color_result(),
                        100.0,
                        palette,
                    )
                    self.assertTrue(validation["portable_basematerials"])
                    self.assertEqual(
                        validation["portable_palette_state_count"], count
                    )
                    with ZipFile(destination) as archive:
                        model = archive.read("3D/Objects/object_1.model")
                    self.assertEqual(model.count(b"<base "), count)

    def test_output_black_correction_survives_portable_rewrite(self):
        prepared = tiny_closed_prepared()
        output = mixer.black_output_ratio_preset(0)
        palette = PaletteSettings(output_mix_ratios_b=output)
        expected = engine.make_portable_mixed_definitions(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            palette.palette_state_count,
            output,
        )
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "corrected.3mf"
            validation = hotfix._write_3mf_atomic_fixed(
                destination,
                prepared,
                tiny_closed_color_result(),
                100.0,
                palette,
            )
            with ZipFile(destination) as archive:
                project = json.loads(
                    archive.read("Metadata/project_settings.config").decode("utf-8")
                )

        self.assertEqual(project["mixed_filament_definitions"], expected)
        self.assertEqual(
            validation["requested_output_mix_ratios_b_percent"],
            output[:12],
        )
        self.assertEqual(
            validation["effective_mix_ratios_b_percent"][:3],
            [80.0, 80.0, 80.0],
        )
        self.assertEqual(
            validation["secondary_effective_mix_ratios_b_percent"][:3],
            [90.0, 90.0, 90.0],
        )
        self.assertEqual(
            validation["display_mix_ratios_b_percent"], [33] * 6
        )
        self.assertTrue(validation["output_ratio_override_active"])
        self.assertTrue(validation["mixed_definitions_match_output_specs"])

    def test_no_output_override_keeps_legacy_portable_recipe(self):
        prepared = tiny_closed_prepared()
        palette = PaletteSettings()
        expected = engine.make_portable_mixed_definitions(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            palette.palette_state_count,
        )
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "legacy.3mf"
            validation = hotfix._write_3mf_atomic_fixed(
                destination,
                prepared,
                tiny_closed_color_result(),
                100.0,
                palette,
            )
            with ZipFile(destination) as archive:
                project = json.loads(
                    archive.read("Metadata/project_settings.config").decode("utf-8")
                )

        self.assertEqual(project["mixed_filament_definitions"], expected)
        self.assertEqual(
            validation["requested_output_mix_ratios_b_percent"],
            [33] * 6 + [67] * 6,
        )
        self.assertEqual(
            validation["effective_mix_ratios_b_percent"], [33.333] * 6
        )
        self.assertEqual(
            validation["secondary_effective_mix_ratios_b_percent"], [66.667] * 6
        )
        self.assertFalse(validation["output_ratio_override_active"])
        self.assertTrue(validation["mixed_definitions_match_output_specs"])

    def test_surface_shell_request_is_forced_to_safe_ratio_by_hotfix_writer(self):
        prepared = tiny_closed_prepared()
        palette = PaletteSettings(
            palette_state_count=32,
            physical_hex=["#111111", "#FFFFFF", "#E32636", "#7A4A32"],
            output_mix_ratios_b=mixer.black_output_ratio_preset(0),
        )
        # Cover post-init mutation as well as old project migration.
        palette.surface_shell_enabled = True
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "surface-shell.3mf"
            validation = hotfix._write_3mf_atomic_fixed(
                destination,
                prepared,
                tiny_closed_color_result(),
                100.0,
                palette,
            )
            with ZipFile(destination) as archive:
                project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
                metadata = json.loads(
                    archive.read("Metadata/full_spectrum_palette.json")
                )

        self.assertTrue(validation["mixed_definitions_match_output_specs"])
        self.assertTrue(validation["surface_shell_exact"])
        self.assertEqual(validation["surface_shell_applied_rows"], 0)
        self.assertEqual(validation["surface_shell_passthrough_rows"], 0)
        self.assertEqual(validation["surface_shell_fallback_rows"], 0)
        self.assertEqual(validation["mixed_definition_cycle_rows"], 0)
        self.assertTrue(validation["mixed_definition_cycle_rows_valid"])
        for key in (
            "wall_loops",
            "wall_generator",
            "outer_wall_line_width",
            "inner_wall_line_width",
            "support_filament",
            "support_interface_filament",
            "flush_into_infill",
            "flush_into_support",
            "flush_into_objects",
        ):
            self.assertNotIn(key, project)
        self.assertNotIn("enable_support", project)
        self.assertFalse(validation["surface_shell_grouped_cycle"])
        self.assertTrue(validation["surface_shell_support_tools_physical"])
        self.assertTrue(
            validation["surface_shell_support_uses_lightest_physical"]
        )
        self.assertTrue(validation["surface_shell_purge_to_print_disabled"])
        self.assertTrue(validation["surface_shell_tool_override_safe"])
        self.assertTrue(validation["slicer_safe_project_defaults"])
        self.assertFalse(validation["unsafe_grouped_cycle_detected"])
        active = project["mixed_filament_definitions"].split(";")[:28]
        self.assertTrue(all(",m2," in row for row in active))
        self.assertEqual(sum(",cm1," in row for row in active), 0)
        self.assertEqual(
            validation["requested_output_mix_ratios_b_percent"],
            mixer.black_output_ratio_preset(0),
        )
        self.assertNotIn("surface_shell", metadata)

    def test_old_grouped_cycle_archive_is_explicitly_detected(self):
        definitions = (
            "1,2,1,1,80,0,g,w,m2,z0,xa0,xb0,d0,o0,u1,cm1,2,12122;"
            "1,3,1,1,80,0,g,w,m2,z0,xa0,xb0,d0,o0,u2"
        )
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "old-unsafe.3mf"
            with ZipFile(destination, "w") as archive:
                archive.writestr(
                    "Metadata/project_settings.config",
                    json.dumps({"mixed_filament_definitions": definitions}),
                )
                archive.writestr(
                    "Metadata/full_spectrum_palette.json",
                    json.dumps(
                        {
                            "surface_shell": {
                                "schema": "tripo-spectrum-mapper.surface-shell.v2",
                                "enabled": True,
                            }
                        }
                    ),
                )

            report = hotfix._inspect_mixed_definition_recipes(destination)

        self.assertTrue(report["unsafe_grouped_cycle_detected"])
        self.assertEqual(report["mixed_definition_cycle_rows"], 1)
        self.assertTrue(report["mixed_definition_cycle_rows_valid"])

    def test_core_validator_rejects_old_grouped_cycle_archive(self):
        prepared = tiny_closed_prepared()
        palette = PaletteSettings(
            physical_hex=["#111111", "#FFFFFF", "#E32636", "#7A4A32"],
            output_mix_ratios_b=mixer.black_output_ratio_preset(0),
        )
        safe_definitions = engine.make_portable_mixed_definitions(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            palette.palette_state_count,
            palette.output_mix_ratios_b,
        )
        rows = safe_definitions.split(";")
        rows[0] += ",cm1,2,12122"
        unsafe_definitions = ";".join(rows)

        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "old-unsafe-full.3mf"
            hotfix._write_3mf_atomic_fixed(
                destination,
                prepared,
                tiny_closed_color_result(),
                100.0,
                palette,
            )
            with ZipFile(destination, "r") as archive:
                members = {
                    info.filename: archive.read(info.filename)
                    for info in archive.infolist()
                }
            project = json.loads(
                members["Metadata/project_settings.config"].decode("utf-8")
            )
            project["mixed_filament_definitions"] = unsafe_definitions
            members["Metadata/project_settings.config"] = json.dumps(
                project, ensure_ascii=False, indent=2
            ).encode("utf-8")
            metadata = json.loads(
                members["Metadata/full_spectrum_palette.json"].decode("utf-8")
            )
            metadata["surface_shell"] = {
                "schema": "tripo-spectrum-mapper.surface-shell.v2",
                "enabled": True,
            }
            members["Metadata/full_spectrum_palette.json"] = json.dumps(
                metadata, ensure_ascii=False, indent=2
            ).encode("utf-8")
            with ZipFile(destination, "w") as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)

            with self.assertRaisesRegex(engine.EngineError, "Grouped Cycle"):
                hotfix._original_validate_3mf(
                    destination,
                    4,
                    4,
                    ["#111111", "#FFFFFF", "#E32636", "#7A4A32"],
                    unsafe_definitions,
                    1,
                )

    def test_surface_shell_off_records_no_patterns_or_forced_wall_keys(self):
        prepared = tiny_closed_prepared()
        palette = PaletteSettings()
        with tempfile.TemporaryDirectory() as folder:
            validation = hotfix._write_3mf_atomic_fixed(
                Path(folder) / "legacy.3mf",
                prepared,
                tiny_closed_color_result(),
                100.0,
                palette,
            )
        self.assertTrue(validation["surface_shell_exact"])
        self.assertEqual(validation["mixed_definition_cycle_rows"], 0)
        self.assertTrue(validation["surface_shell_project_settings_absent"])
        self.assertFalse(validation["surface_shell_grouped_cycle"])
        self.assertTrue(validation["surface_shell_tool_override_safe"])

    def test_project_settings_line_width_diagnostics_are_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "unsafe-width.3mf"
            with ZipFile(destination, "w") as archive:
                archive.writestr(
                    "3D/Objects/object_1.model",
                    b'<model><resources/><mesh><triangles/></mesh></model>',
                )
                archive.writestr(
                    "Metadata/model_settings.config",
                    b'<config><metadata key="enable_support" value="0"/></config>',
                )
                archive.writestr(
                    "Metadata/project_settings.config",
                    json.dumps(
                        {
                            "printer_model": "Snapmaker U1",
                            "printer_variant": "0.4",
                            "print_settings_id": (
                                "0.20 Standard @Snapmaker U1 (0.4 nozzle)"
                            ),
                            "filament_settings_id": [
                                "Snapmaker PLA Full Spectrum @U1 0.4 nozzle"
                            ]
                            * 4,
                            "enable_support": "0",
                            "layer_height": "0.2",
                            "line_width": "0.01",
                        }
                    ).encode("utf-8"),
                )

            validation = hotfix._inspect_portable_materials(destination)

        self.assertFalse(validation["project_settings_line_width_safe"])
        self.assertFalse(validation["slicer_safe_project_defaults"])
        self.assertEqual(validation["project_settings_error_count"], 1)
        self.assertEqual(validation["project_settings_warning_count"], 0)
        self.assertEqual(
            [item["code"] for item in validation["project_settings_diagnostics"]],
            ["line_width_nonpositive_spacing"],
        )
        self.assertIn(
            "負またはゼロのspacing",
            validation["project_settings_diagnostics"][0]["message"],
        )

    def test_invalid_project_settings_json_is_recorded_without_inspection_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "invalid-project-settings.3mf"
            with ZipFile(destination, "w") as archive:
                archive.writestr(
                    "3D/Objects/object_1.model",
                    b'<model><resources/><mesh><triangles/></mesh></model>',
                )
                archive.writestr(
                    "Metadata/model_settings.config",
                    b'<config><metadata key="enable_support" value="0"/></config>',
                )
                archive.writestr("Metadata/project_settings.config", b"{")

            validation = hotfix._inspect_portable_materials(destination)

        self.assertFalse(validation["project_settings_line_width_safe"])
        self.assertFalse(validation["slicer_safe_project_defaults"])
        self.assertEqual(validation["project_settings_error_count"], 1)
        self.assertEqual(
            validation["project_settings_diagnostics"][0]["code"],
            "project_settings_invalid_json",
        )

    def test_portable_project_settings_selects_008_generic_pla_and_leaves_support_editable(self):
        source = json.dumps(
            {
                "enable_support": "1",
                "print_settings_id": "User reviewed safe profile",
                "filament_settings_id": ["User reviewed filament"] * 4,
            }
        ).encode("utf-8")

        settings = json.loads(hotfix._portable_project_settings(source).decode("utf-8"))

        self.assertNotIn("enable_support", settings)
        self.assertEqual(
            settings["print_settings_id"],
            "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)",
        )
        self.assertEqual(settings["layer_height"], "0.08")
        self.assertEqual(settings["initial_layer_print_height"], "0.2")
        self.assertEqual(settings["adaptive_layer_height"], "0")
        self.assertEqual(
            settings["filament_settings_id"], ["Generic PLA"] * 4
        )
        self.assertEqual(settings["tripo_spectrum_mapper_hotfix"], "0.8beta")

    def test_portable_project_settings_repairs_grouped_cycle_t17_conditions(self):
        source = json.dumps(
            {
                "enable_support": "1",
                "filament_colour": [
                    "#111111",
                    "#F5F5F5",
                    "#E32636",
                    "#7A4A32",
                ],
                "mixed_filament_definitions": (
                    "1,2,1,1,80,0,g,w,m2,z0,xa0,xb0,d0,o0,u1,cm1,2,12122;"
                ),
                "support_filament": "0",
                "support_interface_filament": "0",
                "flush_into_infill": "1",
                "flush_into_support": "1",
                "flush_into_objects": "1",
            }
        ).encode("utf-8")

        updated = hotfix._portable_project_settings(source)
        settings = json.loads(updated.decode("utf-8"))

        self.assertNotIn("enable_support", settings)
        self.assertEqual(settings["support_filament"], "2")
        self.assertEqual(settings["support_interface_filament"], "2")
        self.assertEqual(settings["flush_into_infill"], "0")
        self.assertEqual(settings["flush_into_support"], "0")
        self.assertEqual(settings["flush_into_objects"], "0")
        self.assertEqual(slicer_safety.diagnose_project_settings(updated), ())

    def test_adaptive_tree_is_written_as_orca_split_paint_color(self):
        prepared = tiny_closed_prepared()
        prepared._hotfix_subtriangle_paint = {
            0: smooth_paint.PaintNode.branch(
                tuple(smooth_paint.PaintNode(state) for state in (0, 1, 2, 3))
            )
        }
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "adaptive.3mf"
            validation = hotfix._write_3mf_atomic_fixed(
                destination,
                prepared,
                tiny_closed_color_result(),
                100.0,
                PaletteSettings(),
            )
            with ZipFile(destination) as archive:
                model = archive.read("3D/Objects/object_1.model")
            self.assertIn(b'paint_color="480C1C3"', model)
            self.assertIn(b'pid="2" p1="0" paint_color="480C1C3"', model)
            self.assertEqual(validation["adaptive_paint_faces"], 1)
            self.assertEqual(validation["unknown_paint_codes"], [])
            self.assertTrue(validation["portable_and_orca_states_match"])

    def test_whole_face_fill_undo_restores_adaptive_tree(self):
        level = tiny_level()
        session = PaintSession(level, 100.0, np.asarray([0, 1], dtype=np.int8))
        tree = smooth_paint.PaintNode.branch(
            tuple(smooth_paint.PaintNode(state) for state in (0, 0, 2, 2))
        )
        store = {0: tree}
        owner = SimpleNamespace(_hotfix_tree_revision=0)
        session._hotfix_tree_store = store
        session._hotfix_tree_owner = owner

        session.fill(0, 3)
        self.assertNotIn(0, store)
        command = session.undo()
        self.assertIsNotNone(command)
        self.assertEqual(smooth_paint.encode_paint_color(store[0]), "440C0C3")
        session.redo()
        self.assertNotIn(0, store)
        self.assertGreaterEqual(owner._hotfix_tree_revision, 3)

    def test_flat_visible_fill_undo_restores_neighbor_adaptive_tree(self):
        level = tiny_level()
        session = PaintSession(level, 100.0, np.asarray([0, 5], dtype=np.int8))
        tree = smooth_paint.PaintNode.branch(
            tuple(smooth_paint.PaintNode(state) for state in (5, 5, 2, 2))
        )
        store = {1: tree}
        owner = SimpleNamespace(_hotfix_tree_revision=0)
        session._hotfix_tree_store = store
        session._hotfix_tree_owner = owner
        state_map = np.arange(mixer.PALETTE_STATE_COUNT, dtype=np.int8)
        state_map[5] = 0

        changed = session.fill(
            0,
            2,
            connectivity_state_map=state_map,
        )

        np.testing.assert_array_equal(changed, [0, 1])
        np.testing.assert_array_equal(session.overrides, [2, 2])
        self.assertNotIn(1, store)
        session.undo()
        np.testing.assert_array_equal(session.overrides, [-1, -1])
        self.assertEqual(
            smooth_paint.encode_paint_color(store[1]),
            "3C3C0C0C3",
        )
        session.redo()
        np.testing.assert_array_equal(session.overrides, [2, 2])
        self.assertNotIn(1, store)

    def test_flat_visible_same_color_fill_preserves_canonical_tree(self):
        level = tiny_level()
        session = PaintSession(level, 100.0, np.asarray([0, 5], dtype=np.int8))
        tree = smooth_paint.PaintNode.branch(
            tuple(smooth_paint.PaintNode(state) for state in (5, 5, 2, 2))
        )
        store = {1: tree}
        owner = SimpleNamespace(_hotfix_tree_revision=0)
        session._hotfix_tree_store = store
        session._hotfix_tree_owner = owner
        state_map = np.arange(mixer.PALETTE_STATE_COUNT, dtype=np.int8)
        state_map[5] = 0

        changed = session.fill(
            0,
            0,
            connectivity_state_map=state_map,
        )

        self.assertEqual(len(changed), 0)
        np.testing.assert_array_equal(session.overrides, [-1, -1])
        self.assertIs(store[1], tree)
        self.assertEqual(
            smooth_paint.encode_paint_color(store[1]),
            "3C3C0C0C3",
        )
        self.assertEqual(session.undo_depth, 0)
        self.assertEqual(owner._hotfix_tree_revision, 0)

    def test_flat_visible_fill_stays_one_undo_at_history_capacity(self):
        level = tiny_level()
        session = PaintSession(
            level,
            100.0,
            np.asarray([0, 5], dtype=np.int8),
            max_history=2,
        )
        session._set_overrides(np.asarray([0], dtype=np.int32), 1, "first")
        session._set_overrides(np.asarray([0], dtype=np.int32), -1, "second")
        self.assertEqual(session.undo_depth, 2)
        np.testing.assert_array_equal(session.overrides, [-1, -1])

        tree = smooth_paint.PaintNode.branch(
            tuple(smooth_paint.PaintNode(state) for state in (5, 5, 2, 2))
        )
        store = {1: tree}
        owner = SimpleNamespace(_hotfix_tree_revision=0)
        session._hotfix_tree_store = store
        session._hotfix_tree_owner = owner
        state_map = np.arange(mixer.PALETTE_STATE_COUNT, dtype=np.int8)
        state_map[5] = 0

        changed = session.fill(
            0,
            2,
            connectivity_state_map=state_map,
        )

        np.testing.assert_array_equal(changed, [0, 1])
        np.testing.assert_array_equal(session.overrides, [2, 2])
        self.assertNotIn(1, store)
        self.assertEqual(session.undo_depth, 2)

        command = session.undo()
        self.assertIsNotNone(command)
        np.testing.assert_array_equal(session.overrides, [-1, -1])
        self.assertEqual(
            smooth_paint.encode_paint_color(store[1]),
            "3C3C0C0C3",
        )

        command = session.redo()
        self.assertIsNotNone(command)
        np.testing.assert_array_equal(session.overrides, [2, 2])
        self.assertNotIn(1, store)


if __name__ == "__main__":
    unittest.main(verbosity=2)
