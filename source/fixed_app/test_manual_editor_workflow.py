from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.i18n import Translator  # noqa: E402
from spectrum_mapper.paint_gui import PaintEditorWindow  # noqa: E402
from spectrum_mapper.renderer import (  # noqa: E402
    PART_HIDDEN,
    PART_TRANSPARENT,
    PART_VISIBLE,
)


class _Var:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class _Canvas:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, tag: str) -> None:
        self.deleted.append(tag)


def _double_click_editor() -> PaintEditorWindow:
    editor = object.__new__(PaintEditorWindow)
    editor._close_requested = False
    editor._closing = False
    editor._topology_change_pending = False
    editor._render_dirty = False
    editor.target_mapping = (0, 0, 100, 100, 2, 1)
    editor.face_ids = np.asarray([[0, 1]], dtype=np.int32)
    editor.level = SimpleNamespace(
        faces=np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int32),
        face_part_ids=np.asarray([0, 1], dtype=np.int16),
    )
    editor.part_labels = ("1: Front", "2: Back")
    editor.part_names = ("Front", "Back")
    editor.active_part_id = 0
    editor.part_target_var = _Var("1: Front")
    editor.status_var = _Var("")
    editor.i18n = Translator("ja")
    editor.canvas = _Canvas()
    editor._drag_mode = None
    editor._stroke_faces = []
    editor._lasso_points = []
    return editor


class ManualEditorPartPickingTests(unittest.TestCase):
    def test_double_click_switches_to_the_part_in_the_visible_face_map(self) -> None:
        editor = _double_click_editor()
        selected: list[str] = []
        editor._on_editor_part_selected = lambda: selected.append(
            editor.part_target_var.get()
        )

        result = PaintEditorWindow._on_target_double_click(
            editor, SimpleNamespace(x=75, y=50)
        )

        self.assertEqual(result, "break")
        self.assertEqual(selected, ["2: Back"])
        self.assertEqual(editor.part_target_var.get(), "2: Back")
        self.assertIn("Back", editor.status_var.get())

    def test_double_click_cannot_select_a_face_missing_from_the_pick_map(self) -> None:
        editor = _double_click_editor()
        editor.face_ids[0, 1] = -1
        selected: list[str] = []
        editor._on_editor_part_selected = lambda: selected.append("called")

        result = PaintEditorWindow._on_target_double_click(
            editor, SimpleNamespace(x=75, y=50)
        )

        self.assertEqual(result, "break")
        self.assertEqual(selected, [])
        self.assertEqual(editor.part_target_var.get(), "1: Front")


class ManualEditorShortcutDispatchTests(unittest.TestCase):
    def _editor(self) -> PaintEditorWindow:
        editor = object.__new__(PaintEditorWindow)
        editor._close_requested = False
        editor._closing = False
        editor._topology_change_pending = False
        editor._drag_mode = None
        editor._stroke_faces = []
        editor._lasso_points = []
        editor.canvas = _Canvas()
        editor.tool_var = _Var("brush")
        editor.status_var = _Var("")
        editor.i18n = Translator("ja")
        editor.active_part_id = 2
        editor._on_tool_changed = lambda: None
        return editor

    def test_visibility_shortcuts_target_the_active_part(self) -> None:
        editor = self._editor()
        calls: list[tuple[int, int]] = []
        editor.set_part_display_mode = lambda part, mode: calls.append(
            (part, mode)
        )

        for action in ("part_visible", "part_transparent", "part_hidden"):
            self.assertTrue(
                PaintEditorWindow._dispatch_shortcut(editor, action, object())
            )

        self.assertEqual(
            calls,
            [
                (2, PART_VISIBLE),
                (2, PART_TRANSPARENT),
                (2, PART_HIDDEN),
            ],
        )

    def test_tool_shortcut_changes_tool_clears_lasso_without_stealing_ribbon(self) -> None:
        editor = self._editor()
        editor._lasso_points = [(1, 2), (3, 4)]
        selected_pages: list[str] = []
        editor._select_ribbon_for_tool = lambda tool: selected_pages.append(tool)

        self.assertTrue(
            PaintEditorWindow._dispatch_shortcut(editor, "tool_orbit", object())
        )

        self.assertEqual(editor.tool_var.get(), "orbit")
        self.assertEqual(editor._lasso_points, [])
        self.assertIn("split-lasso", editor.canvas.deleted)
        self.assertEqual(selected_pages, [])

    def test_repeated_tool_shortcut_keeps_current_ribbon_page(self) -> None:
        editor = self._editor()
        selected_pages: list[str] = []
        editor._select_ribbon_for_tool = lambda tool: selected_pages.append(tool)

        self.assertTrue(
            PaintEditorWindow._dispatch_shortcut(editor, "tool_brush", object())
        )

        self.assertEqual(editor.tool_var.get(), "brush")
        self.assertEqual(selected_pages, [])


class ManualEditorSolidifyRequestTests(unittest.TestCase):
    def test_confirmed_request_delegates_to_the_main_safe_flow(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor._topology_change_pending = False
        editor.status_var = _Var("")
        editor.i18n = Translator("ja")
        editor.window = object()
        calls: list[str] = []
        editor.on_solidify_requested = lambda: calls.append("solidify")

        with patch(
            "spectrum_mapper.paint_gui.messagebox.askyesno", return_value=True
        ):
            PaintEditorWindow._request_solidify(editor)

        self.assertEqual(calls, ["solidify"])
        self.assertIn("閉じ", editor.status_var.get())


if __name__ == "__main__":
    unittest.main()
