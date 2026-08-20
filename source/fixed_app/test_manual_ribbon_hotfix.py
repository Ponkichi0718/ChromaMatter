from __future__ import annotations

from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest import mock

from PIL import Image

import smooth_paint_hotfix
import spectrum_mapper_hotfix
from spectrum_mapper.i18n import Translator


class _Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class ManualRibbonHotfixTests(unittest.TestCase):
    def test_explicit_extension_hosts_avoid_legacy_text_search(self) -> None:
        brush = object()
        shading = object()
        editor = SimpleNamespace(
            window=object(),
            brush_shape_host=brush,
            auto_shading_host=shading,
        )
        with mock.patch.object(
            smooth_paint_hotfix,
            "_find_legacy_paint_option_parent",
            side_effect=AssertionError("legacy lookup must not run"),
        ):
            resolved = smooth_paint_hotfix._resolve_paint_extension_hosts(editor)
        self.assertEqual(resolved, (brush, shading, None))

    def test_missing_extension_hosts_keep_legacy_ui_compatible(self) -> None:
        legacy = object()
        editor = SimpleNamespace(window=object())
        with mock.patch.object(
            smooth_paint_hotfix,
            "_find_legacy_paint_option_parent",
            return_value=legacy,
        ):
            resolved = smooth_paint_hotfix._resolve_paint_extension_hosts(editor)
        self.assertEqual(resolved, (legacy, legacy, legacy))

    def test_ribbon_hosts_receive_separate_brush_and_shading_controls(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()

        class Localizer:
            def __init__(self):
                self.captured = []
                self.apply_count = 0

            def capture(self, widget):
                self.captured.append(widget)

            def apply(self):
                self.apply_count += 1

        def noop(*_args, **_kwargs):
            return None

        class Editor:
            def __init__(self):
                self.window = root
                self.brush_shape_host = ttk.Frame(root)
                self.auto_shading_host = ttk.Frame(root)
                self.i18n = Translator("ja")
                self.localizer = Localizer()

            _worker_initialize = noop
            _on_left_press = noop
            _on_left_motion = noop
            _commit_active_stroke = noop
            _consume_snapshot = noop
            _draw_canvas = noop
            _undo = noop
            _redo = noop
            _clear_all = noop
            _queue_fill = noop
            _queue_smooth = noop
            close = noop
            set_language = noop

        class Session:
            fill = noop
            smooth_boundary = noop
            clear_overrides = noop
            undo = noop
            redo = noop

        paint_gui = SimpleNamespace(
            PaintEditorWindow=Editor,
            PANEL="#151A22",
            TEXT="#E8EDF4",
            ACCENT="#56C2FF",
        )
        paint_module = SimpleNamespace(PaintSession=Session)
        try:
            smooth_paint_hotfix.apply_smooth_paint_hotfix(
                paint_gui,
                paint_module,
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(),
            )
            editor = Editor()

            def child_texts(parent):
                values = []
                pending = list(parent.winfo_children())
                while pending:
                    widget = pending.pop()
                    pending.extend(widget.winfo_children())
                    try:
                        values.append(str(widget.cget("text")))
                    except tk.TclError:
                        pass
                return values

            brush_text = child_texts(editor.brush_shape_host)
            shading_text = child_texts(editor.auto_shading_host)
            self.assertIn("筆先", brush_text)
            self.assertIn("マーカー（長方形）", brush_text)
            self.assertIn("筆圧ペン（未検出時は先細り）", brush_text)
            self.assertIn(
                "この環境では未検出",
                editor._hotfix_pressure_status_var.get(),
            )
            self.assertNotIn("面内グラデーション補正", brush_text)
            self.assertIn("面内グラデーション補正", shading_text)
            self.assertIn("面内グラデーションを生成", shading_text)
            self.assertNotIn("筆先", shading_text)
            self.assertEqual(
                editor.localizer.captured,
                [editor.brush_shape_host, editor.auto_shading_host],
            )
            self.assertEqual(editor.localizer.apply_count, 1)
        finally:
            root.destroy()

    def test_detached_palette_host_receives_brush_controls(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        palette_window = tk.Toplevel(root)
        palette_window.withdraw()

        class Localizer:
            def capture(self, _widget):
                pass

            def apply(self):
                pass

        def noop(*_args, **_kwargs):
            return None

        class Editor:
            def __init__(self):
                self.window = root
                self.palette_tool_window = palette_window
                self.brush_shape_host = ttk.Frame(palette_window)
                self.auto_shading_host = ttk.Frame(root)
                self.i18n = Translator("ja")
                self.localizer = Localizer()

            _worker_initialize = noop
            _on_left_press = noop
            _on_left_motion = noop
            _commit_active_stroke = noop
            _consume_snapshot = noop
            _draw_canvas = noop
            _undo = noop
            _redo = noop
            _clear_all = noop
            _queue_fill = noop
            _queue_smooth = noop
            close = noop
            set_language = noop

        class Session:
            fill = noop
            smooth_boundary = noop
            clear_overrides = noop
            undo = noop
            redo = noop

        try:
            paint_gui = SimpleNamespace(
                PaintEditorWindow=Editor,
                PANEL="#151A22",
                TEXT="#E8EDF4",
                ACCENT="#56C2FF",
            )
            smooth_paint_hotfix.apply_smooth_paint_hotfix(
                paint_gui,
                SimpleNamespace(PaintSession=Session),
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(),
            )
            editor = Editor()
            self.assertIs(editor.brush_shape_host.winfo_toplevel(), palette_window)
            texts = [
                str(child.cget("text"))
                for child in editor.brush_shape_host.winfo_children()
                if "text" in child.keys()
            ]
            self.assertIn("筆先", texts)
            self.assertIn("マーカー（長方形）", texts)
            self.assertIn("筆圧ペン（未検出時は先細り）", texts)
        finally:
            palette_window.destroy()
            root.destroy()

    def test_hidden_reference_bypasses_large_image_cache(self) -> None:
        sentinel = object()
        editor = SimpleNamespace(
            reference_visible_var=_Variable(False),
            face_ids=None,
        )
        with (
            mock.patch.object(
                spectrum_mapper_hotfix,
                "_original_paint_draw_canvas",
                return_value=sentinel,
            ) as original,
            mock.patch.object(
                spectrum_mapper_hotfix,
                "_cache_large_reference_for_draw",
            ) as cached,
        ):
            result = spectrum_mapper_hotfix._paint_draw_canvas_fixed(editor)
        self.assertIs(result, sentinel)
        original.assert_called_once_with(editor)
        cached.assert_not_called()

    def test_visible_reference_uses_responsive_layout_for_cache(self) -> None:
        source = Image.new("RGB", (1200, 1000), "white")

        class Canvas:
            @staticmethod
            def winfo_width():
                return 1000

            @staticmethod
            def winfo_height():
                return 600

        editor = SimpleNamespace(
            reference_image=source,
            reference_visible_var=_Variable(True),
            canvas=Canvas(),
            reference_mapping=None,
        )
        seen = []

        def draw(instance):
            seen.append(instance.reference_image.size)
            return "drawn"

        layout = {
            "reference": (14, 123),
            "panel_height": 234,
        }
        with mock.patch.object(
            spectrum_mapper_hotfix.paint_gui,
            "compute_manual_canvas_layout",
            return_value=layout,
            create=True,
        ) as helper:
            result = spectrum_mapper_hotfix._cache_large_reference_for_draw(
                editor, draw, "canvas", 2
            )

        self.assertEqual(result, "drawn")
        helper.assert_called_once_with(1000, 600, True)
        self.assertEqual(editor._hotfix_reference_cache[0][2:], (123, 234))
        self.assertLessEqual(seen[0][0], 123)
        self.assertLessEqual(seen[0][1], 234)
        self.assertIs(editor.reference_image, source)


if __name__ == "__main__":
    unittest.main()
