from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import time
import tkinter as tk
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spectrum_mapper_hotfix as hotfix
from spectrum_mapper.engine import load_vertex_color_obj
from spectrum_mapper.models import (
    AppSettings,
    GeometrySettings,
    MeshLevel,
    PreparedGeometry,
)
from spectrum_mapper.paint_gui import PaintEditorWindow


def _pump(root: tk.Tk, predicate, timeout: float = 15.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.003)
    return False


def _tetra_prepared() -> PreparedGeometry:
    asset = load_vertex_color_obj(Path(__file__).with_name("test_tetra.obj"))
    vertices = np.asarray(asset.vertices, dtype=np.float32)
    faces = np.asarray(asset.faces, dtype=np.int32)
    colors = np.asarray(asset.colors, dtype=np.float32)
    areas = (
        np.linalg.norm(
            np.cross(
                vertices[faces[:, 1]] - vertices[faces[:, 0]],
                vertices[faces[:, 2]] - vertices[faces[:, 0]],
            ),
            axis=1,
        )
        / 2.0
    ).astype(np.float32)
    level = MeshLevel(vertices, faces, colors, areas, None)
    total_area = float(areas.sum())
    return PreparedGeometry(
        asset,
        level,
        level,
        len(vertices),
        len(faces),
        0,
        0,
        {},
        total_area,
        1.0 / 6.0,
        total_area,
        1.0 / 6.0,
        np.ptp(vertices, axis=0),
        [],
    )


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


class RealTkGpuIntegrationTests(unittest.TestCase):
    def test_same_camera_color_only_render_preserves_legacy_part_outline(self) -> None:
        """A post-edit render must not drop the selected-part cyan outline.

        Tripo/legacy single-part levels use an empty ``face_part_ids`` sentinel;
        the live renderer expands that to one normalized entry per face.  This
        is the production condition that the lightweight post-decal render
        takes when its existing pick map is still exact.
        """

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
            editor.window.geometry("1100x800+30+30")
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.target_image is not None
                        and editor.face_ids is not None
                        and not editor._job_running
                        and not editor._render_dirty
                        and editor._hotfix_pick_camera == editor.camera
                    ),
                ),
                editor.status_var.get(),
            )
            self.assertEqual(np.asarray(editor.level.face_part_ids).size, 0)
            self.assertEqual(
                np.asarray(editor._renderer._face_part_ids).shape,
                (len(editor.level.faces),),
            )
            accent = np.asarray(
                editor._renderer._active_part_accent, dtype=np.uint8
            )

            def outlined_pixel_count() -> int:
                pixels = np.asarray(editor.target_image.convert("RGB"))
                return int(np.count_nonzero(np.all(pixels == accent, axis=2)))

            before = outlined_pixel_count()
            self.assertGreater(before, 0)
            previous = editor.target_image

            # Same camera + valid cached IDs is the colour-only path used by
            # a completed paint/decal edit.  It must remain a single colour
            # pass and restore the image-space outline from the cached map.
            editor._request_render()
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.target_image is not previous
                        and not editor._job_running
                        and not editor._render_dirty
                    ),
                ),
                editor.status_var.get(),
            )
            self.assertEqual(outlined_pixel_count(), before)
            self.assertEqual(editor._hotfix_pick_camera, editor.camera)
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

    def test_palette_usage_focus_changes_pixels_and_survives_rotation_patch(self) -> None:
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
            editor.window.geometry("1100x800+30+30")
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.target_image is not None
                        and editor.face_ids is not None
                        and editor.target_mapping is not None
                        and not editor._job_running
                        and not editor._render_dirty
                    ),
                ),
                editor.status_var.get(),
            )
            normal = np.asarray(editor.target_image.convert("RGB")).copy()
            state = int(
                np.bincount(
                    np.asarray(editor.effective_indices, dtype=np.int64),
                    minlength=32,
                ).argmax()
            )
            editor.paint_state_var.set(state)
            editor._update_selected_palette_label()
            editor.palette_usage_focus_var.set(True)
            previous = editor.target_image
            editor._on_palette_usage_focus_changed()
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.target_image is not previous
                        and not editor._job_running
                        and not editor._render_dirty
                    ),
                ),
                editor.status_var.get(),
            )
            focused = np.asarray(editor.target_image.convert("RGB")).copy()
            self.assertGreater(
                float(np.mean(np.abs(focused.astype(float) - normal.astype(float)))),
                1.0,
            )
            self.assertEqual(editor._renderer._palette_usage_focus_state, state)

            left, top, width, height, _rw, _rh = editor.target_mapping
            center_x = int(left + width * 0.55)
            center_y = int(top + height * 0.55)
            editor._on_right_press(
                SimpleNamespace(x=center_x, y=center_y, state=0)
            )
            editor._on_right_motion(
                SimpleNamespace(x=center_x + 35, y=center_y + 20, state=0x0200)
            )
            editor._on_right_release(
                SimpleNamespace(x=center_x + 35, y=center_y + 20, state=0)
            )
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and not editor._render_dirty
                        and editor._hotfix_pick_camera == editor.camera
                    ),
                ),
                editor.status_var.get(),
            )
            self.assertEqual(editor._renderer._palette_usage_focus_state, state)

            rotated_focus = np.asarray(editor.target_image.convert("RGB")).copy()
            previous = editor.target_image
            editor.palette_usage_focus_var.set(False)
            editor._on_palette_usage_focus_changed()
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.target_image is not previous
                        and not editor._job_running
                        and not editor._render_dirty
                    ),
                ),
                editor.status_var.get(),
            )
            rotated_normal = np.asarray(editor.target_image.convert("RGB")).copy()
            self.assertGreater(
                float(
                    np.mean(
                        np.abs(
                            rotated_focus.astype(float)
                            - rotated_normal.astype(float)
                        )
                    )
                ),
                1.0,
            )
            self.assertIsNone(editor._renderer._palette_usage_focus_state)
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

    def test_marker_paint_and_middle_pan_settle_on_exact_gpu_frame(self) -> None:
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
            editor.window.geometry("1100x800+30+30")
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

            texts = _widget_texts(editor.window)
            self.assertIn("筆先", texts)
            self.assertIn("丸筆", texts)
            self.assertIn("マーカー（長方形）", texts)
            self.assertEqual(editor._hotfix_brush_shape_var.get(), "round")

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
            self.assertGreater(len(visible_x), 12)
            start = (
                left + int(visible_x[len(visible_x) // 3]),
                top + best_y,
            )
            end = (
                left + int(visible_x[2 * len(visible_x) // 3]),
                top + best_y,
            )
            start_face = editor._face_at(*start)
            self.assertGreaterEqual(start_face, 0)
            self.assertGreaterEqual(editor._face_at(*end), 0)
            before = int(editor._session.effective_indices()[start_face])
            editor.paint_state_var.set((before + 2) % 10)
            editor.tool_var.set("brush")
            editor.brush_radius_var.set(3.0)
            editor._hotfix_brush_shape_var.set("marker")
            # X11 may deliver a real pointer-motion event while the editor is
            # being mapped.  Start this synthetic gesture from the documented
            # default nib angle instead of inheriting that unrelated event.
            editor._hotfix_brush_cursor_last_pointer = None
            editor._hotfix_brush_cursor_angle = 0.0

            # The real Tk Canvas must show the same rectangular nib that the
            # adaptive marker uses, and ordinary Motion must reuse its item.
            editor._on_pointer_motion(SimpleNamespace(x=start[0], y=start[1]))
            cursor_item = editor._hotfix_brush_cursor_item
            self.assertIsNotNone(cursor_item)
            self.assertEqual(editor.canvas.type(cursor_item), "polygon")
            initial_cursor = tuple(float(value) for value in editor.canvas.coords(cursor_item))
            self.assertEqual(len(initial_cursor), 8)
            self.assertGreater(
                max(initial_cursor[0::2]) - min(initial_cursor[0::2]),
                max(initial_cursor[1::2]) - min(initial_cursor[1::2]),
            )
            editor._on_pointer_motion(
                SimpleNamespace(x=start[0] + 5, y=start[1])
            )
            self.assertEqual(editor._hotfix_brush_cursor_item, cursor_item)
            moved_cursor = tuple(float(value) for value in editor.canvas.coords(cursor_item))
            self.assertGreater(
                max(moved_cursor[1::2]) - min(moved_cursor[1::2]),
                max(moved_cursor[0::2]) - min(moved_cursor[0::2]),
            )

            editor._on_left_press(
                SimpleNamespace(x=start[0], y=start[1], state=0)
            )
            for amount in np.linspace(0.0, 1.0, 12)[1:]:
                x = int(round(start[0] + amount * (end[0] - start[0])))
                y = int(round(start[1] + amount * (end[1] - start[1])))
                editor._on_left_motion(
                    SimpleNamespace(x=x, y=y, state=0x0100)
                )
                root.update()
            editor._on_left_release(
                SimpleNamespace(x=end[0], y=end[1], state=0)
            )
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and not editor._render_dirty
                        and bool(prepared._hotfix_subtriangle_paint)
                    ),
                ),
                editor.status_var.get(),
            )
            revision = int(prepared._hotfix_tree_revision)
            self.assertGreater(revision, 0)
            self.assertEqual(
                editor.target_image.info.get(
                    "tripo_spectrum_adaptive_gpu_revision"
                ),
                revision,
            )
            self.assertIn("マーカー", editor.status_var.get())

            old_camera = editor.camera
            center_x = int(left + width * 0.55)
            center_y = int(top + height * 0.55)
            editor._on_middle_press(
                SimpleNamespace(x=center_x, y=center_y, state=0)
            )
            editor._on_middle_motion(
                SimpleNamespace(x=center_x + 50, y=center_y + 35, state=0x0200)
            )
            editor._on_middle_release(
                SimpleNamespace(x=center_x + 50, y=center_y + 35, state=0)
            )
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        not editor._job_running
                        and not editor._render_dirty
                        and editor._hotfix_pick_camera == editor.camera
                    ),
                )
            )
            self.assertEqual(editor.camera.zoom, old_camera.zoom)
            self.assertNotEqual(editor.camera, old_camera)
            self.assertNotEqual(float(editor.camera.pan_x), 0.0)
            self.assertNotEqual(float(editor.camera.pan_y), 0.0)
            self.assertEqual(
                editor.target_image.info.get(
                    "tripo_spectrum_adaptive_gpu_revision"
                ),
                revision,
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
