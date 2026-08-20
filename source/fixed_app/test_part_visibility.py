from __future__ import annotations

from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest

import numpy as np
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import (
    AppSettings,
    ColorResult,
    GeometrySettings,
    MeshLevel,
    PreparedGeometry,
)
from spectrum_mapper.paint_gui import PaintEditorWindow
from spectrum_mapper import mixer as mixer_module
from spectrum_mapper import renderer as renderer_module
from spectrum_mapper.renderer import (
    InteractiveMeshRenderer,
    PART_HIDDEN,
    PART_TRANSPARENT,
    PART_VISIBLE,
    RendererError,
    VISIBILITY_FACE_MODES_INFO_KEY,
    VISIBILITY_INFO_KEY,
)


def _overlapping_two_part_mesh() -> tuple[MeshLevel, ColorResult]:
    # Camera looks from -Y.  Both quads face -Y; part 0 sits in front of part 1.
    vertices = np.asarray(
        [
            [-0.8, -0.12, 0.0],
            [0.8, -0.12, 0.0],
            [-0.8, -0.12, 1.0],
            [0.8, -0.12, 1.0],
            [-0.8, 0.12, 0.0],
            [0.8, 0.12, 0.0],
            [-0.8, 0.12, 1.0],
            [0.8, 0.12, 1.0],
        ],
        dtype=np.float32,
    )
    faces = np.asarray(
        [
            [0, 1, 2],
            [1, 3, 2],
            [4, 5, 6],
            [5, 7, 6],
        ],
        dtype=np.int32,
    )
    level = MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=np.ones((len(vertices), 3), dtype=np.float32),
        areas_unit=np.ones(len(faces), dtype=np.float64),
        neighbors=None,
        face_part_ids=np.asarray([0, 0, 1, 1], dtype=np.int16),
        part_names=("Front", "Back"),
        part_keys=("front", "back"),
    )
    colors = np.asarray(
        [
            [1.0, 0.05, 0.05],
            [1.0, 0.05, 0.05],
            [0.05, 1.0, 0.05],
            [0.05, 1.0, 0.05],
        ],
        dtype=np.float32,
    )
    result = ColorResult(
        tone_vertex_rgb=np.ones((len(vertices), 3), dtype=np.float32),
        source_face_rgb=colors.copy(),
        palette_indices=np.zeros(len(faces), dtype=np.int8),
        target_face_rgb=colors.copy(),
        delta_e=np.zeros(len(faces), dtype=np.float32),
        smoothed_faces=0,
        palette_face_counts=np.asarray([len(faces)], dtype=np.int64),
        palette_area_fractions=np.asarray([1.0], dtype=np.float64),
        pink_area_fraction=0.0,
    )
    return level, result


class PartVisibilityExpansionTests(unittest.TestCase):
    def test_editor_expands_part_modes_without_changing_part_or_color_data(self) -> None:
        level, _result = _overlapping_two_part_mesh()
        editor = object.__new__(PaintEditorWindow)
        editor.level = level
        editor._part_visibility_modes = np.asarray(
            [PART_TRANSPARENT, PART_HIDDEN], dtype=np.uint8
        )
        original_ids = level.face_part_ids.copy()
        expanded = editor._face_visibility_modes()
        np.testing.assert_array_equal(
            expanded,
            np.asarray(
                [PART_TRANSPARENT, PART_TRANSPARENT, PART_HIDDEN, PART_HIDDEN],
                dtype=np.uint8,
            ),
        )
        np.testing.assert_array_equal(level.face_part_ids, original_ids)

    def test_adaptive_cpu_overlay_does_not_make_transparent_root_opaque(self) -> None:
        import smooth_paint
        import smooth_paint_hotfix

        level, _result = _overlapping_two_part_mesh()
        tree = smooth_paint.PaintNode(0)
        tree.split_four()
        for index, child in enumerate(tree.children):
            child.make_leaf(index + 1)
        image = Image.new("RGB", (64, 64), (30, 40, 50))
        modes = np.asarray(
            [PART_TRANSPARENT, PART_TRANSPARENT, PART_VISIBLE, PART_VISIBLE],
            dtype=np.uint8,
        )
        image.info[VISIBILITY_INFO_KEY] = True
        image.info[VISIBILITY_FACE_MODES_INFO_KEY] = modes
        composed = smooth_paint_hotfix.compose_target_image(
            image,
            level,
            {0: tree},
            camera=None,
            face_ids=np.zeros((64, 64), dtype=np.int32),
            palette=AppSettings().palette,
            renderer_module=renderer_module,
            mixer_module=mixer_module,
        )
        np.testing.assert_array_equal(np.asarray(composed), np.asarray(image))
        np.testing.assert_array_equal(
            composed.info[VISIBILITY_FACE_MODES_INFO_KEY], modes
        )


class InteractivePartVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.level, cls.result = _overlapping_two_part_mesh()
        try:
            cls.renderer = InteractiveMeshRenderer(
                cls.level, size=(160, 160), background=(4, 6, 9)
            )
        except RendererError as exc:
            raise unittest.SkipTest(f"ModernGL is unavailable: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        renderer = getattr(cls, "renderer", None)
        if renderer is not None:
            renderer.close()

    @staticmethod
    def _center(frame) -> tuple[int, np.ndarray]:
        ids = np.asarray(frame.face_ids)
        y = ids.shape[0] // 2
        x = ids.shape[1] // 2
        pixel = np.asarray(frame.target, dtype=np.uint8)[y, x]
        return int(ids[y, x]), pixel

    def test_transparent_display_and_click_through_are_independent(self) -> None:
        visible = np.full(4, PART_VISIBLE, dtype=np.uint8)
        self.renderer.set_face_visibility(visible, pick_transparent=False)
        ordinary = self.renderer.render(
            self.result, render_source=False, render_target=True
        )
        ordinary_face, ordinary_pixel = self._center(ordinary)
        self.assertEqual(int(self.level.face_part_ids[ordinary_face]), 0)

        hidden_front = np.asarray(
            [PART_HIDDEN, PART_HIDDEN, PART_VISIBLE, PART_VISIBLE],
            dtype=np.uint8,
        )
        self.renderer.set_face_visibility(hidden_front, pick_transparent=False)
        hidden = self.renderer.render(
            self.result, render_source=False, render_target=True
        )
        hidden_face, hidden_pixel = self._center(hidden)
        self.assertEqual(int(self.level.face_part_ids[hidden_face]), 1)

        transparent_front = np.asarray(
            [PART_TRANSPARENT, PART_TRANSPARENT, PART_VISIBLE, PART_VISIBLE],
            dtype=np.uint8,
        )
        self.renderer.set_face_visibility(transparent_front, pick_transparent=False)
        click_through = self.renderer.render(
            self.result, render_source=False, render_target=True
        )
        through_face, transparent_pixel = self._center(click_through)
        self.assertEqual(int(self.level.face_part_ids[through_face]), 1)
        self.assertGreater(int(transparent_pixel[0]), int(hidden_pixel[0]))
        self.assertGreater(int(transparent_pixel[1]), int(ordinary_pixel[1]))
        self.assertTrue(click_through.target.info.get(VISIBILITY_INFO_KEY))
        np.testing.assert_array_equal(
            click_through.target.info[VISIBILITY_FACE_MODES_INFO_KEY],
            transparent_front,
        )

        self.renderer.set_face_visibility(transparent_front, pick_transparent=True)
        selectable = self.renderer.render(
            self.result, render_source=False, render_target=True
        )
        selectable_face, selectable_pixel = self._center(selectable)
        self.assertEqual(int(self.level.face_part_ids[selectable_face]), 0)
        np.testing.assert_array_equal(selectable_pixel, transparent_pixel)

    def test_hidden_faces_are_absent_from_color_and_pick_passes(self) -> None:
        all_hidden = np.full(4, PART_HIDDEN, dtype=np.uint8)
        self.renderer.set_face_visibility(all_hidden, pick_transparent=True)
        frame = self.renderer.render(
            self.result, render_source=False, render_target=True
        )
        face, pixel = self._center(frame)
        self.assertEqual(face, -1)
        np.testing.assert_array_equal(pixel, np.asarray([4, 6, 9], dtype=np.uint8))

    def test_visibility_updates_stay_renderer_thread_affine(self) -> None:
        errors: list[Exception] = []

        def update_from_wrong_thread() -> None:
            try:
                self.renderer.set_face_visibility(np.zeros(4, dtype=np.uint8))
            except Exception as exc:  # expected RendererError from owner check
                errors.append(exc)

        worker = threading.Thread(target=update_from_wrong_thread)
        worker.start()
        worker.join()
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RendererError)

    def test_invalid_visibility_table_is_rejected(self) -> None:
        with self.assertRaises(RendererError):
            self.renderer.set_face_visibility(np.zeros(3, dtype=np.uint8))
        with self.assertRaises(RendererError):
            self.renderer.set_face_visibility(np.asarray([0, 0, 0, 3]))


class RealEditorPartVisibilityTests(unittest.TestCase):
    def test_multipart_editor_switches_visibility_and_picker_live(self) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()

        # Install the production hotfix stack before the editor is created.
        # This covers the rotation scheduler and adaptive GPU wrapper as used
        # by the packaged application, not only the base classes above.
        import spectrum_mapper_hotfix  # noqa: F401

        level, _result = _overlapping_two_part_mesh()
        prepared = PreparedGeometry(
            source=SimpleNamespace(),
            final=level,
            preview=level,
            clean_vertex_count=len(level.vertices_unit),
            clean_face_count=len(level.faces),
            removed_vertices=0,
            removed_faces=0,
            topology={},
            source_area_unit=float(level.areas_unit.sum()),
            source_volume_unit=0.0,
            simplified_area_unit=float(level.areas_unit.sum()),
            simplified_volume_unit=0.0,
            source_dimensions_unit=np.ptp(level.vertices_unit, axis=0),
            warnings=[],
            part_names=level.part_names,
            part_keys=level.part_keys,
        )
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=50.0,
                target_faces=1000,
                preview_faces=1000,
                up_axis="Y",
                min_component_faces=1,
            )
        )
        editor = None

        def pump(predicate, timeout: float = 12.0) -> bool:
            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                root.update()
                if predicate():
                    return True
                time.sleep(0.003)
            return False

        try:
            editor = PaintEditorWindow(
                root,
                prepared,
                settings,
                None,
                None,
                lambda _values: None,
            )
            editor.window.geometry("1100x800+20+20")
            self.assertTrue(
                pump(
                    lambda: (
                        editor.face_ids is not None
                        and not editor._job_running
                        and not editor._render_dirty
                    )
                ),
                editor.status_var.get(),
            )
            self.assertEqual(str(editor.part_visibility_selector.cget("state")), "readonly")
            self.assertEqual(str(editor.pick_transparent_check.cget("state")), "normal")

            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            dropdowns = tuple(
                widget
                for widget in descendants(editor.window)
                if isinstance(widget, ttk.Combobox)
            )
            self.assertGreaterEqual(len(dropdowns), 3)
            self.assertTrue(
                all(
                    str(widget.cget("style")) == "HighContrast.TCombobox"
                    for widget in dropdowns
                )
            )
            combo_style = ttk.Style(root)
            self.assertEqual(
                combo_style.lookup(
                    "HighContrast.TCombobox", "foreground", ("readonly",)
                ).lower(),
                "#ffffff",
            )
            self.assertEqual(
                combo_style.lookup(
                    "HighContrast.TCombobox", "foreground", ("disabled",)
                ).lower(),
                "#d5dce5",
            )
            quality_selector = editor._hotfix_auto_shading_quality_selector
            self.assertEqual(
                tuple(quality_selector.cget("values")),
                ("高速", "標準", "高品質"),
            )
            editor._hotfix_auto_shading_quality_var.set("高品質")
            editor.set_language("en")
            self.assertEqual(
                tuple(quality_selector.cget("values")),
                ("Fast", "Standard", "High Quality"),
            )
            self.assertEqual(
                editor._hotfix_auto_shading_quality_var.get(), "High Quality"
            )
            editor.set_language("ja")
            self.assertEqual(editor._hotfix_auto_shading_quality_var.get(), "高品質")

            self.assertTrue(editor.set_part_display_mode(0, PART_TRANSPARENT))
            self.assertTrue(
                pump(
                    lambda: (
                        editor.face_ids is not None
                        and not editor._job_running
                        and not editor._render_dirty
                    )
                ),
                editor.status_var.get(),
            )
            ids = np.asarray(editor.face_ids)
            center_face = int(ids[ids.shape[0] // 2, ids.shape[1] // 2])
            self.assertEqual(int(level.face_part_ids[center_face]), 1)
            self.assertTrue(editor.target_image.info.get(VISIBILITY_INFO_KEY))

            self.assertTrue(editor.set_transparent_part_picking(True))
            self.assertTrue(
                pump(
                    lambda: (
                        editor.face_ids is not None
                        and not editor._job_running
                        and not editor._render_dirty
                    )
                ),
                editor.status_var.get(),
            )
            ids = np.asarray(editor.face_ids)
            center_face = int(ids[ids.shape[0] // 2, ids.shape[1] // 2])
            self.assertEqual(int(level.face_part_ids[center_face]), 0)

            editor.set_language("en")
            self.assertEqual(
                tuple(editor.part_visibility_selector.cget("values")),
                ("Visible", "Transparent", "Hidden"),
            )
            self.assertEqual(editor.part_visibility_var.get(), "Transparent")

            self.assertTrue(editor.set_part_display_mode(0, PART_HIDDEN))
            self.assertTrue(
                pump(
                    lambda: (
                        editor.face_ids is not None
                        and not editor._job_running
                        and not editor._render_dirty
                    )
                ),
                editor.status_var.get(),
            )
            ids = np.asarray(editor.face_ids)
            center_face = int(ids[ids.shape[0] // 2, ids.shape[1] // 2])
            self.assertEqual(int(level.face_part_ids[center_face]), 1)
        finally:
            if editor is not None:
                try:
                    editor.close()
                    pump(lambda: not editor.window.winfo_exists(), 5.0)
                except Exception:
                    pass
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
