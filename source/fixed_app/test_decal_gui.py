from __future__ import annotations

from pathlib import Path
from types import MappingProxyType, SimpleNamespace
import sys
import threading
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

# Match the executable import/install order: this module installs the runtime
# paint wrappers before the editor class is used.
import spectrum_mapper_hotfix as _runtime_hotfix  # noqa: E402,F401
from spectrum_mapper import paint_gui as paint_gui_module  # noqa: E402
from spectrum_mapper.decal_projection import (  # noqa: E402
    DecalBakePlan,
    DecalBakeResult,
    DecalPreview,
    DecalPreviewMetrics,
    DecalTransform,
    _camera_signature,
)
from spectrum_mapper.paint_gui import PaintEditorWindow  # noqa: E402
from spectrum_mapper.renderer import CameraState  # noqa: E402
from spectrum_mapper.i18n import Translator  # noqa: E402


class Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class FakeI18n:
    language = "ja"

    @staticmethod
    def text(key: str, **values: object) -> str:
        return key if not values else f"{key}:{values}"


class FakeWindow:
    def __init__(self) -> None:
        self.idle_callbacks: list[tuple[str, object]] = []
        self.after_callbacks: list[tuple[str, int, object]] = []
        self.cancelled: list[object] = []
        self._serial = 0

    def after_idle(self, callback):
        self._serial += 1
        token = f"idle-{self._serial}"
        self.idle_callbacks.append((token, callback))
        return token

    def after(self, delay: int, callback):
        self._serial += 1
        token = f"after-{self._serial}"
        self.after_callbacks.append((token, int(delay), callback))
        return token

    def after_cancel(self, token) -> None:
        self.cancelled.append(token)


class FakeButton:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, *, state: str) -> None:
        self.state = state


def preview_fixture(
    *,
    mode: str = "selected",
    selected_state: int = 1,
    generation: int = 4,
    transform: DecalTransform | None = None,
) -> DecalPreview:
    state_map = np.full((2, 2), selected_state, dtype=np.int8)
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    metrics = DecalPreviewMetrics(
        footprint_pixels=4,
        opaque_pixels=4,
        eligible_pixels=4,
        clipped_pixels=0,
        candidate_faces=1,
        support_faces=1,
        mean_delta_e76=0.0,
        p90_delta_e76=0.0,
    )
    return DecalPreview(
        overlay_rgba=rgba,
        quantized_overlay_rgba=rgba.copy(),
        state_map=state_map,
        face_ids=np.zeros((2, 2), dtype=np.int32),
        candidate_faces=np.asarray((0,), dtype=np.int32),
        support_faces=np.asarray((0,), dtype=np.int32),
        anchor_face=0,
        frame_generation=generation,
        transform=transform or DecalTransform((1.0, 1.0), 2.0),
        mode=mode,
        metrics=metrics,
    )


def plan_fixture(camera: CameraState, *, generation: int = 4) -> DecalBakePlan:
    return DecalBakePlan(
        mesh_fingerprint="gui-test",
        frame_generation=generation,
        camera_signature=_camera_signature(camera),
        face_indices=np.asarray((0,), dtype=np.int32),
        expected_overrides=np.asarray((-1,), dtype=np.int8),
        expected_tree_codes=MappingProxyType({0: None}),
        nodes_by_face=MappingProxyType({}),
        protected_faces=0,
        disconnected_faces=0,
        adaptive_roots=1,
        total_nodes=4,
        target_pixels=4,
    )


def stale_editor() -> PaintEditorWindow:
    editor = object.__new__(PaintEditorWindow)
    editor.i18n = FakeI18n()
    editor.window = FakeWindow()
    editor.decal_status_var = Var()
    editor._decal_image = object()
    editor._decal_preview = object()
    editor._decal_bake_plan = object()
    editor._decal_planned_state_map = np.zeros((1, 1), dtype=np.int8)
    editor._decal_base_state_map = np.zeros((1, 1), dtype=np.int8)
    editor._decal_preview_palette_rgb = np.zeros((32, 3), dtype=np.float64)
    editor._decal_preview_enabled_states = np.ones(32, dtype=bool)
    editor._decal_preview_selected_state = 1
    editor._decal_preview_overwrite = False
    editor._decal_preview_camera = CameraState()
    editor._decal_preview_generation = 1
    editor._decal_preview_stale = False
    editor._decal_preview_running = False
    editor._decal_apply_running = False
    editor._decal_request_serial = 2
    editor._decal_cancel_event = None
    editor._decal_preview_cancel_event = None
    editor._decal_auto_repreview = False
    editor._decal_auto_repreview_after = None
    editor._ribbon_selected = "decal"
    editor._close_requested = False
    editor._refresh_decal_button_states = lambda: None
    editor._draw_canvas = lambda: None
    return editor


class DecalGuiContractTests(unittest.TestCase):
    def test_runtime_hotfix_order_preserves_pan_orbit_and_smooth_scheduler(self) -> None:
        self.assertEqual(PaintEditorWindow._orbit_to.__module__, "rotation_hotfix")
        self.assertEqual(
            PaintEditorWindow._schedule_render.__module__, "smooth_paint_hotfix"
        )
        self.assertTrue(callable(getattr(PaintEditorWindow, "_on_middle_motion", None)))

    def test_selected_state_change_invalidates_cached_plan_for_16_24_32(self) -> None:
        for state_count in (16, 24, 32):
            with self.subTest(state_count=state_count):
                editor = stale_editor()
                editor.paint_state_var = Var(0)
                editor._palette_usage_focus_state = 0
                editor._palette_usage_focus_enabled = False
                editor._renderer = None
                editor.state_names = tuple(f"S{i + 1}" for i in range(32))
                editor.palette_name_var = Var()
                editor.decal_mode_var = Var("selected")
                editor._active_palette = lambda count=state_count: SimpleNamespace(
                    palette_state_count=count,
                    enabled_states=tuple(True for _ in range(count)),
                )
                editor._invalidate_palette_usage_render_cache = lambda: None
                editor._update_palette_usage_summary = lambda: None

                editor.paint_state_var.set(state_count - 1)
                PaintEditorWindow._update_selected_palette_label(editor)

                self.assertTrue(editor._decal_preview_stale)
                self.assertIsNone(editor._decal_bake_plan)
                self.assertIsNone(editor._decal_preview)
                self.assertEqual(editor._decal_request_serial, 3)

    def test_overwrite_toggle_invalidates_and_schedules_one_repreview(self) -> None:
        editor = stale_editor()
        cancel = threading.Event()
        editor._decal_preview_cancel_event = cancel
        editor._decal_exact_frame_available = lambda: True
        calls: list[str] = []
        editor._preview_decal = lambda: calls.append("preview")

        PaintEditorWindow._on_decal_overwrite_changed(editor)

        self.assertTrue(cancel.is_set())
        self.assertIsNone(editor._decal_bake_plan)
        self.assertEqual(len(editor.window.idle_callbacks), 1)
        editor.window.idle_callbacks[0][1]()
        self.assertEqual(calls, ["preview"])

    def test_direct_canvas_drag_is_consumed_without_entering_brush(self) -> None:
        editor = stale_editor()
        editor._ribbon_selected = "decal"
        editor._decal_apply_running = False
        editor._topology_change_pending = False
        editor.target_mapping = (10, 20, 200, 100, 400, 200)
        editor.decal_x_var = Var(50.0)
        editor.decal_y_var = Var(50.0)
        editor._decal_syncing_controls = False
        editor._point_inside = lambda event, mapping: True
        editor._mark_decal_preview_stale = lambda *args, **kwargs: None
        editor._decal_exact_frame_available = lambda: True
        previews: list[str] = []
        editor._preview_decal = lambda: previews.append("preview")
        editor.tool_var = SimpleNamespace(
            get=lambda: (_ for _ in ()).throw(
                AssertionError("brush tool must not be queried for decal drag")
            )
        )
        editor._drag_mode = None
        editor._stroke_faces = []
        editor._stroke_pressures = []
        editor._airbrush_started_at = None
        press = SimpleNamespace(x=60, y=45, state=0)
        motion = SimpleNamespace(x=210, y=120, state=0)

        PaintEditorWindow._on_left_press(editor, press)
        self.assertEqual(editor._drag_mode, "decal")
        self.assertEqual((editor.decal_x_var.get(), editor.decal_y_var.get()), (25.0, 25.0))
        PaintEditorWindow._on_left_motion(editor, motion)
        self.assertEqual((editor.decal_x_var.get(), editor.decal_y_var.get()), (100.0, 100.0))
        PaintEditorWindow._on_left_release(editor, motion)
        self.assertIsNone(editor._drag_mode)
        self.assertEqual(previews, ["preview"])
        self.assertEqual(editor._stroke_faces, [])

    def test_pan_orbit_zoom_render_burst_repreviews_once_after_exact_settle(self) -> None:
        editor = stale_editor()
        editor._render_after = None
        editor._render_dirty = False
        editor._request_render = lambda: None
        editor._decal_auto_repreview_after = None
        editor._decal_exact_frame_available = lambda: True
        calls: list[str] = []
        editor._preview_decal = lambda: calls.append("preview")

        # Orbit, pan and wheel-zoom all converge on this same render scheduler.
        for _interaction in ("orbit", "pan", "zoom"):
            PaintEditorWindow._schedule_render(editor)
        self.assertTrue(editor._decal_auto_repreview)
        self.assertTrue(editor._decal_preview_stale)

        editor._render_dirty = False
        PaintEditorWindow._accept_decal_exact_frame(
            editor, np.zeros((2, 2), dtype=np.int32), CameraState()
        )
        PaintEditorWindow._accept_decal_exact_frame(
            editor, np.zeros((2, 2), dtype=np.int32), CameraState()
        )
        self.assertEqual(len(editor.window.idle_callbacks), 1)
        editor.window.idle_callbacks[0][1]()
        self.assertEqual(calls, ["preview"])
        self.assertFalse(editor._decal_auto_repreview)

    def test_latest_only_preview_and_stale_payload_keep_new_cancel_event(self) -> None:
        editor = stale_editor()
        editor._decal_preview_running = True
        editor._decal_preview_pending = False
        newest_cancel = threading.Event()
        editor._decal_preview_cancel_event = newest_cancel
        editor._submit = lambda *_args: self.fail("latest-only must not enqueue again")

        PaintEditorWindow._preview_decal(editor)
        PaintEditorWindow._preview_decal(editor)
        self.assertTrue(editor._decal_preview_pending)

        handled = PaintEditorWindow._consume_decal_payload(
            editor,
            {
                "decal_preview_error": RuntimeError("stale"),
                "decal_serial": editor._decal_request_serial - 1,
            },
        )
        self.assertTrue(handled)
        self.assertTrue(editor._decal_preview_running)
        self.assertIs(editor._decal_preview_cancel_event, newest_cancel)

        PaintEditorWindow._cancel_decal(editor)
        self.assertTrue(newest_cancel.is_set())
        self.assertFalse(editor._decal_preview_pending)

    def test_preview_plans_once_and_passes_protect_or_overwrite_contract(self) -> None:
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                editor = object.__new__(PaintEditorWindow)
                editor.i18n = FakeI18n()
                editor.window = FakeWindow()
                editor.decal_status_var = Var()
                editor._decal_image = np.asarray([[[255, 0, 0, 255]]], dtype=np.uint8)
                editor._decal_apply_running = False
                editor._decal_preview_running = False
                editor._decal_preview_pending = False
                editor._decal_auto_repreview = False
                editor._decal_auto_repreview_after = None
                editor._decal_request_serial = 0
                editor._decal_frame_generation = 4
                editor._close_requested = False
                editor.camera = CameraState()
                editor.level = object()
                editor.paint_state_var = Var(1)
                editor.decal_mode_var = Var("selected")
                editor.decal_overwrite_var = Var(overwrite)
                editor.palette_rgb = np.zeros((32, 3), dtype=np.float64)
                editor._hotfix_tree_store = {}
                editor._active_palette = lambda: SimpleNamespace(
                    enabled_states=tuple(True for _ in range(32))
                )
                ids = np.zeros((2, 2), dtype=np.int32)
                editor._decal_exact_inputs = lambda: (
                    ids.copy(), np.asarray((True,)), np.asarray((True,))
                )
                transform = DecalTransform((1.0, 1.0), 2.0)
                editor._decal_transform = lambda _shape: transform
                editor._commit_active_stroke = lambda: None
                editor._mark_decal_preview_stale = lambda *args, **kwargs: None
                editor._refresh_decal_button_states = lambda: None
                session = SimpleNamespace(
                    auto_indices=np.asarray((0,), dtype=np.int8),
                    overrides=np.asarray((-1,), dtype=np.int8),
                    allowed_face_mask=np.asarray((True,)),
                    _stroke_before=None,
                    effective_indices=lambda: np.asarray((0,), dtype=np.int8),
                )
                editor._session = session
                payloads: list[dict[str, object]] = []
                editor._submit = lambda _kind, work: payloads.append(work())
                preview = preview_fixture(transform=transform)
                plan = plan_fixture(editor.camera)
                base_map = np.zeros((2, 2), dtype=np.int8)
                planned_map = np.ones((2, 2), dtype=np.int8)

                with (
                    patch.object(
                        paint_gui_module,
                        "rasterize_existing_tree_states",
                        return_value=base_map,
                    ) as base_raster,
                    patch.object(
                        paint_gui_module, "build_decal_preview", return_value=preview
                    ),
                    patch.object(
                        paint_gui_module, "plan_decal_bake", return_value=plan
                    ) as planner,
                    patch.object(
                        paint_gui_module,
                        "rasterize_decal_bake_plan",
                        return_value=planned_map,
                    ) as planned_raster,
                ):
                    PaintEditorWindow._preview_decal(editor)

                planner.assert_called_once()
                self.assertEqual(
                    planner.call_args.kwargs["protect_manual"], not overwrite
                )
                self.assertFalse(planner.call_args.kwargs["cancelled"]())
                self.assertFalse(base_raster.call_args.kwargs["cancelled"]())
                self.assertFalse(planned_raster.call_args.kwargs["cancelled"]())
                self.assertEqual(len(payloads), 1)
                self.assertIs(payloads[0]["decal_preview_plan"], plan)

    def test_apply_commits_cached_plan_without_replanning(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor.i18n = FakeI18n()
        editor.window = FakeWindow()
        editor.decal_status_var = Var()
        editor.status_var = Var()
        editor._decal_preview_is_current = lambda: True
        editor._decal_apply_running = False
        editor.decal_overwrite_var = Var(False)
        editor._hotfix_tree_store = {}
        editor._session = object()
        editor.face_ids = np.zeros((2, 2), dtype=np.int32)
        editor.camera = CameraState()
        editor._decal_frame_generation = 4
        editor._render_dirty = False
        editor.prepared = object()
        editor._hotfix_tree_owner = object()
        editor._decal_preview = preview_fixture()
        plan = plan_fixture(editor.camera)
        editor._decal_bake_plan = plan
        editor._refresh_decal_button_states = lambda: None
        editor._worker_refresh_after_edit = lambda message, changed: {
            "message": message,
            "changed": changed,
        }
        payloads: list[dict[str, object]] = []
        editor._submit = lambda _kind, work: payloads.append(work())
        result = DecalBakeResult(
            changed_faces=np.asarray((0,), dtype=np.int32),
            adaptive_roots=1,
            uniform_roots=0,
            target_pixels=4,
            command=object(),
        )

        with (
            patch.object(
                paint_gui_module,
                "plan_decal_bake",
                side_effect=AssertionError("Apply must never plan again"),
            ) as planner,
            patch.object(
                paint_gui_module, "commit_decal_bake", return_value=result
            ) as commit,
        ):
            PaintEditorWindow._apply_decal(editor)

        planner.assert_not_called()
        commit.assert_called_once()
        self.assertIs(commit.call_args.args[3], plan)
        self.assertEqual(len(payloads), 1)
        self.assertIs(payloads[0]["decal_apply_plan"], plan)

    def test_atomic_apply_disables_cancel_then_enables_dedicated_undo(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor.i18n = FakeI18n()
        editor.decal_status_var = Var()
        editor._decal_image = object()
        editor._decal_load_running = False
        editor._decal_preview_running = False
        editor._decal_apply_running = True
        editor._decal_preview = preview_fixture()
        editor._decal_bake_plan = plan_fixture(CameraState())
        editor._decal_planned_state_map = np.ones((2, 2), dtype=np.int8)
        editor._decal_preview_stale = False
        editor._decal_undo_available = False
        editor._decal_last_command = None
        editor._decal_exact_frame_available = lambda: False
        for attribute in (
            "decal_import_button",
            "decal_preview_button",
            "decal_apply_button",
            "decal_cancel_button",
            "decal_undo_button",
        ):
            setattr(editor, attribute, FakeButton())

        PaintEditorWindow._refresh_decal_button_states(editor)
        self.assertEqual(editor.decal_cancel_button.state, "disabled")

        command = object()
        result = DecalBakeResult(
            changed_faces=np.asarray((0,), dtype=np.int32),
            adaptive_roots=1,
            uniform_roots=0,
            target_pixels=4,
            command=command,
        )
        handled = PaintEditorWindow._consume_decal_payload(
            editor,
            {
                "decal_apply_result": result,
                "decal_apply_plan": editor._decal_bake_plan,
            },
        )
        self.assertFalse(handled)
        self.assertIs(editor._decal_last_command, command)
        self.assertTrue(editor._decal_undo_available)
        self.assertEqual(editor.decal_undo_button.state, "normal")
        self.assertEqual(editor.decal_cancel_button.state, "disabled")
        applying = Translator("en").text("decal.applying")
        self.assertNotIn("Cancel", applying)
        self.assertIn("Undo Decal Once", applying)


if __name__ == "__main__":
    unittest.main()
