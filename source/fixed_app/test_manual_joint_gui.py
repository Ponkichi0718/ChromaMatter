from __future__ import annotations

from pathlib import Path
import sys
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

# Install the same paint/rotation/adaptive wrapper stack used by the packaged
# application before constructing the editor.
import spectrum_mapper_hotfix  # noqa: F401,E402
from rotation_hotfix import _PanCameraState  # noqa: E402
from spectrum_mapper.manual_joints import (  # noqa: E402
    ManualJointSettings,
    resolve_manual_joint_target,
)
from spectrum_mapper.models import AppSettings, GeometrySettings  # noqa: E402
from spectrum_mapper.paint_gui import PaintEditorWindow  # noqa: E402
from spectrum_mapper.renderer import (  # noqa: E402
    PART_TRANSPARENT,
    VISIBILITY_FACE_MODES_INFO_KEY,
)
from test_manual_joints import HEIGHT_MM, _prepared_pair  # noqa: E402


def _pump(root: tk.Tk, predicate, timeout: float = 20.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.003)
    return False


def _widget_texts(window: tk.Misc) -> set[str]:
    result: set[str] = set()
    pending = list(window.winfo_children())
    while pending:
        widget = pending.pop()
        pending.extend(widget.winfo_children())
        try:
            value = str(widget.cget("text"))
        except Exception:
            continue
        if value:
            result.add(value)
    return result


class ManualJointEditorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk is unavailable: {exc}") from exc
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_joint_plan_blocks_old_face_actions_until_user_cancels(self) -> None:
        root = self.root
        prepared, repair = _prepared_pair()
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=HEIGHT_MM,
                target_faces=10_000,
                preview_faces=10_000,
                min_component_faces=1,
                auto_joints=False,
            )
        )
        editor = None
        release = threading.Event()
        try:
            editor = PaintEditorWindow(
                root,
                prepared,
                settings,
                None,
                None,
                lambda _values: None,
            )
            self.assertTrue(
                _pump(
                    root,
                    lambda: editor.face_ids is not None and not editor._job_running,
                )
            )
            part_faces = np.flatnonzero(prepared.final.face_part_ids == 0)
            start, end = repair["interfaces"][0]["cap_face_range_by_part"]["0"]
            male_face = int(part_faces[int(start) : int(end)][0])
            center = tuple(
                np.asarray(prepared.final.vertices_unit)[
                    np.asarray(prepared.final.faces)[male_face]
                ].mean(axis=0)
            )
            started = threading.Event()

            def delayed_resolve(*args, **kwargs):
                started.set()
                if not release.wait(5.0):
                    raise RuntimeError("test release timed out")
                return resolve_manual_joint_target(*args, **kwargs)

            with (
                patch(
                    "spectrum_mapper.paint_gui.resolve_manual_joint_target",
                    side_effect=delayed_resolve,
                ),
                patch(
                    "spectrum_mapper.paint_gui.messagebox.askyesno",
                    return_value=False,
                ),
            ):
                editor._queue_manual_joint_target(male_face, center)
                self.assertTrue(_pump(root, started.is_set, 5.0))
                self.assertTrue(editor._topology_change_pending)
                self.assertEqual(str(editor.part_selector.cget("state")), "disabled")

                modes_before = editor._part_visibility_modes.copy()
                self.assertFalse(editor.set_part_display_mode(1, PART_TRANSPARENT))
                np.testing.assert_array_equal(
                    editor._part_visibility_modes, modes_before
                )
                ran: list[bool] = []
                editor._submit("edit", lambda: ran.append(True))
                self.assertFalse(ran)
                self.assertFalse(editor._queued_actions)

                editor.tool_var.set("brush")
                editor._on_left_press(
                    type("Click", (), {"x": 10, "y": 10, "state": 0})()
                )
                self.assertNotEqual(editor._drag_mode, "stroke")
                self.assertEqual(editor.status_var.get(), editor.i18n.text("joint.wait"))

                release.set()
                self.assertTrue(
                    _pump(
                        root,
                        lambda: (
                            not editor._topology_change_pending
                            and not editor._job_running
                        ),
                    ),
                    editor.status_var.get(),
                )
            self.assertEqual(str(editor.part_selector.cget("state")), "readonly")
            self.assertIs(editor.prepared, prepared)
        finally:
            release.set()
            if editor is not None:
                try:
                    editor.close()
                    _pump(root, lambda: not editor.window.winfo_exists(), 5.0)
                    editor._executor.shutdown(wait=True)
                except Exception:
                    pass

    def test_failed_renderer_rebuild_rolls_back_to_live_old_editor(self) -> None:
        root = self.root
        prepared, repair = _prepared_pair()
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=HEIGHT_MM,
                target_faces=10_000,
                preview_faces=10_000,
                min_component_faces=1,
                auto_joints=False,
            )
        )
        geometry_events: list[object] = []
        editor = None
        try:
            editor = PaintEditorWindow(
                root,
                prepared,
                settings,
                None,
                None,
                lambda _values: None,
                on_geometry_changed=lambda *values: geometry_events.append(values),
            )
            self.assertTrue(
                _pump(
                    root,
                    lambda: editor.face_ids is not None and not editor._job_running,
                )
            )
            part_faces = np.flatnonzero(prepared.final.face_part_ids == 0)
            start, end = repair["interfaces"][0]["cap_face_range_by_part"]["0"]
            male_face = int(part_faces[int(start) : int(end)][0])
            center = tuple(
                np.asarray(prepared.final.vertices_unit)[
                    np.asarray(prepared.final.faces)[male_face]
                ].mean(axis=0)
            )
            joint_settings = ManualJointSettings()
            target = resolve_manual_joint_target(
                prepared,
                male_face_id=male_face,
                center_unit=center,
                height_mm=HEIGHT_MM,
                settings=joint_settings,
            )
            old_renderer = editor._renderer
            old_session = editor._session
            old_face_ids = np.asarray(editor.face_ids).copy()
            editor._set_topology_change_pending(True)
            with (
                patch.object(
                    PaintEditorWindow,
                    "_worker_initialize",
                    side_effect=RuntimeError("forced renderer rebuild failure"),
                ),
                patch("spectrum_mapper.paint_gui.messagebox.showerror"),
                patch("spectrum_mapper.paint_gui.messagebox.showwarning"),
            ):
                editor._apply_manual_joint_target(target, joint_settings)
                self.assertTrue(
                    _pump(
                        root,
                        lambda: (
                            not editor._topology_change_pending
                            and not editor._job_running
                        ),
                    ),
                    editor.status_var.get(),
                )

            self.assertIs(editor.prepared, prepared)
            self.assertIs(editor.level, prepared.final)
            self.assertIs(editor._renderer, old_renderer)
            self.assertIs(editor._session, old_session)
            self.assertFalse(geometry_events)
            np.testing.assert_array_equal(editor.face_ids, old_face_ids)

            # A new render proves the restored ModernGL context was not closed
            # during the failed transaction.
            editor._schedule_render(immediate=True)
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.face_ids is not None
                        and not editor._job_running
                        and not editor._render_dirty
                    ),
                ),
                editor.status_var.get(),
            )
        finally:
            if editor is not None:
                try:
                    editor.close()
                    _pump(root, lambda: not editor.window.winfo_exists(), 5.0)
                    editor._executor.shutdown(wait=True)
                except Exception:
                    pass

    def test_hidden_joint_engine_replaces_topology_and_undoes_live(self) -> None:
        root = self.root
        prepared, repair = _prepared_pair()
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=HEIGHT_MM,
                target_faces=10_000,
                preview_faces=10_000,
                up_axis="Y",
                min_component_faces=1,
                auto_joints=False,
            )
        )
        geometry_events: list[tuple[object, np.ndarray, dict | None]] = []
        editor = None
        try:
            editor = PaintEditorWindow(
                root,
                prepared,
                settings,
                None,
                None,
                lambda _values: None,
                on_geometry_changed=lambda new_prepared, overrides, record: (
                    geometry_events.append((new_prepared, overrides, record))
                ),
            )
            editor.window.geometry("1200x820+30+30")
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.face_ids is not None
                        and not editor._job_running
                        and not editor._render_dirty
                    ),
                ),
                editor.status_var.get(),
            )

            texts = _widget_texts(editor.window)
            self.assertNotIn("ジョイント配置 β", texts)
            self.assertNotIn("横幅", texts)
            self.assertNotIn("縦長さ", texts)
            self.assertNotIn("差込深さ", texts)
            self.assertNotIn("クリアランス", texts)
            self.assertFalse(hasattr(editor, "joint_panel"))
            self.assertFalse(hasattr(editor, "joint_undo_button"))
            self.assertNotIn("joint", editor.paint_tool_buttons)

            # Reveal the generated interface while keeping the active male
            # part selectable.  Picking policy must survive renderer rebuild.
            self.assertTrue(editor.set_part_display_mode(1, PART_TRANSPARENT))
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and editor.face_ids is not None
                        and not editor._render_dirty
                    ),
                ),
                editor.status_var.get(),
            )

            interface = repair["interfaces"][0]
            part_faces = np.flatnonzero(prepared.final.face_part_ids == 0)
            cap_start, cap_end = interface["cap_face_range_by_part"]["0"]
            cap_faces = part_faces[int(cap_start) : int(cap_end)]
            editor.camera = _PanCameraState(
                yaw_degrees=17.0,
                pitch_degrees=45.0,
                zoom=1.25,
                pan_x=0.08,
                pan_y=-0.06,
            )
            editor._schedule_render(immediate=True)
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and not editor._render_dirty
                        and editor.face_ids is not None
                        and editor._hotfix_pick_camera == editor.camera
                    ),
                ),
                editor.status_var.get(),
            )
            rendered_ids = np.asarray(editor.face_ids)
            cap_mask = np.isin(rendered_ids, cap_faces)
            cap_y, cap_x = np.nonzero(cap_mask)
            self.assertGreater(len(cap_x), 100)
            center_x = float(np.mean(cap_x))
            center_y = float(np.mean(cap_y))
            center_index = int(
                np.argmin((cap_x - center_x) ** 2 + (cap_y - center_y) ** 2)
            )
            render_x = int(cap_x[center_index])
            render_y = int(cap_y[center_index])
            left, top, width, height, render_width, render_height = (
                editor.target_mapping
            )
            click_x = int(round(left + (render_x + 0.5) * width / render_width))
            click_y = int(round(top + (render_y + 0.5) * height / render_height))
            selected_face = editor._face_at(click_x, click_y)
            self.assertIn(selected_face, set(map(int, cap_faces)))
            selected_center = tuple(
                np.asarray(prepared.final.vertices_unit)[
                    np.asarray(prepared.final.faces)[selected_face]
                ].mean(axis=0)
            )
            initial_faces = len(prepared.final.faces)

            with patch(
                "spectrum_mapper.paint_gui.messagebox.askyesno",
                return_value=True,
            ):
                # The public joint controls are intentionally absent in r25,
                # while the retained engine remains callable by developer
                # workflows and future dedicated tools.
                editor._queue_manual_joint_target(selected_face, selected_center)
                self.assertTrue(
                    _pump(
                        root,
                        lambda: (
                            len(geometry_events) == 1
                            and not editor._job_running
                            and not editor._render_dirty
                            and editor.face_ids is not None
                        ),
                    ),
                    editor.status_var.get(),
                )

            generated, overrides, record = geometry_events[0]
            self.assertIs(generated, editor.prepared)
            self.assertIsNot(generated, prepared)
            self.assertGreater(len(generated.final.faces), initial_faces)
            self.assertEqual(overrides.shape, (len(generated.final.faces),))
            self.assertIsInstance(record, dict)
            self.assertEqual(record["positioning"], "user_selected_surface_point")
            self.assertEqual(
                record["contact_diagnostics"]["contact_validation"],
                "passed_volume_balance",
            )
            self.assertGreater(record["adaptive_embed_mm"], 0.0)
            self.assertIn("生成しました", editor.status_var.get())
            self.assertIsNotNone(editor._manual_joint_undo_state)
            self.assertEqual(int(editor._part_visibility_modes[1]), PART_TRANSPARENT)
            self.assertFalse(editor.pick_transparent_var.get())
            self.assertIn(VISIBILITY_FACE_MODES_INFO_KEY, editor.target_image.info)
            visible_ids = np.asarray(editor.face_ids)
            self.assertTrue(
                np.all(
                    (visible_ids < 0)
                    | (visible_ids < len(editor.prepared.final.faces))
                )
            )

            with patch(
                "spectrum_mapper.paint_gui.messagebox.askyesno",
                return_value=True,
            ):
                editor._undo_manual_joint()
                self.assertTrue(
                    _pump(
                        root,
                        lambda: (
                            len(geometry_events) == 2
                            and not editor._job_running
                            and not editor._render_dirty
                            and editor.face_ids is not None
                        ),
                    ),
                    editor.status_var.get(),
                )
            restored, restored_overrides, restored_record = geometry_events[1]
            self.assertIs(restored, prepared)
            self.assertEqual(len(restored.final.faces), initial_faces)
            self.assertEqual(restored_overrides.shape, (initial_faces,))
            self.assertIsNone(restored_record)
            self.assertIsNone(editor._manual_joint_undo_state)
            self.assertIn("戻しました", editor.status_var.get())

            editor.set_language("en")
            root.update_idletasks()
            english_texts = _widget_texts(editor.window)
            self.assertNotIn("Place Joint β", english_texts)
            self.assertNotIn("Undo Joint", english_texts)
        finally:
            if editor is not None:
                try:
                    editor.close()
                    _pump(root, lambda: not editor.window.winfo_exists(), 5.0)
                    editor._executor.shutdown(wait=True)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
