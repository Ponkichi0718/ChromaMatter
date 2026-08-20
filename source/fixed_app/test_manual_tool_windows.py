from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

_PAINT_GUI_PATH = Path(__file__).resolve().parent / "spectrum_mapper" / "paint_gui.py"
_PAINT_GUI_SOURCE = _PAINT_GUI_PATH.read_text(encoding="utf-8")
_PAINT_GUI_TREE = ast.parse(_PAINT_GUI_SOURCE)
_PAINT_EDITOR_NODE = next(
    node
    for node in _PAINT_GUI_TREE.body
    if isinstance(node, ast.ClassDef) and node.name == "PaintEditorWindow"
)


def _method_source(name: str) -> str:
    node = next(
        child
        for child in _PAINT_EDITOR_NODE.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and child.name == name
    )
    return ast.get_source_segment(_PAINT_GUI_SOURCE, node) or ""

from spectrum_mapper.i18n import Translator  # noqa: E402
from spectrum_mapper.paint_gui import (  # noqa: E402
    PaintEditorWindow,
    TOOL_RESTORE_DELAY_MS,
    TOOL_RESTORE_RETRY_MS,
    TOOL_RESTORE_VERIFY_DELAY_MS,
    compute_manual_tool_window_layouts,
    compute_palette_tool_window_layout,
)
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


class _Renderer:
    def __init__(self) -> None:
        self.active_calls: list[tuple[int, object]] = []

    def set_active_part(self, part_id: int, *, color=None) -> None:
        self.active_calls.append((int(part_id), color))


class ManualWindowChromeTests(unittest.TestCase):
    def test_editor_is_a_normal_minimizable_non_modal_toplevel(self) -> None:
        source = _method_source("__init__")

        self.assertIn("tk.Toplevel(parent)", source)
        self.assertNotIn(".grab_set(", source)
        self.assertNotIn(".transient(", source)
        self.assertNotIn(".overrideredirect(", source)
        self.assertIn(".resizable(True, True)", source)

    def test_parts_is_not_a_ribbon_page_anymore(self) -> None:
        source = _method_source("_build_ui")

        self.assertNotIn('"parts": "paint.ribbon_parts"', source)
        self.assertNotIn("self.ribbon_pages[\"parts\"]", source)

    def test_view_controls_are_on_home_paint_tools_float_and_ribbon_has_guards(self) -> None:
        source = _method_source("_build_ui")
        home_block = source.split(
            'home = self.ribbon_pages["home"]', 1
        )[1].split('brush = self.ribbon_pages["brush"]', 1)[0]
        brush_block = source.split(
            'brush = self.ribbon_pages["brush"]', 1
        )[1].split('shading = self.ribbon_pages["shading"]', 1)[0]
        self.assertNotIn('"view": "paint.ribbon_view"', source)
        self.assertNotIn('self.ribbon_pages["view"]', source)
        self.assertNotIn('"shape": "paint.ribbon_shape"', source)
        self.assertNotIn('self.ribbon_pages["shape"]', source)
        for key in (
            "paint.orbit",
            "paint.view_background",
            "paint.orbit_inverted",
            "paint.reference_show",
            "paint.front",
        ):
            with self.subTest(home_key=key):
                self.assertIn(key, home_block)
        for key in (
            "paint.edge_guard",
            "paint.crease_overlay",
            "paint.front_visible_guard",
        ):
            with self.subTest(guard_key=key):
                self.assertIn(key, brush_block)
        self.assertIn(
            'self.boundary_diagnostics_check = ttk.Checkbutton(\n            self.ribbon_pages["brush"]',
            source,
        )
        floating_block = source.split(
            "# The detached Brush & Color panel is the single home", 1
        )[1].split("palette_grid = ttk.Frame", 1)[0]
        for key in (
            "paint.brush",
            "paint.airbrush",
            "paint.eyedropper_3d",
            "paint.smudge",
            "paint.fill",
            "paint.smooth",
            "paint.erase",
            "paint.clear",
            "paint.brush_radius",
            "paint.airbrush_strength",
            "paint.smudge_strength",
            "paint.smooth_passes",
        ):
            with self.subTest(floating_key=key):
                self.assertIn(key, floating_block)
        for key in ("paint.brush", "paint.fill", "paint.smooth", "paint.erase"):
            with self.subTest(not_on_ribbon=key):
                self.assertNotIn(key, home_block)
                self.assertNotIn(key, brush_block)
        self.assertIn("ensure_ribbon=True", home_block)
        self.assertNotIn("ensure_ribbon=True", floating_block)


class ManualToolWindowStructureTests(unittest.TestCase):
    def test_palette_window_uses_full_size_and_clamps_to_small_screens(self) -> None:
        geometry, minimum = compute_palette_tool_window_layout(1920, 1080)
        self.assertEqual(geometry, "540x760+60+70")
        self.assertEqual(minimum, (420, 520))

        geometry, minimum = compute_palette_tool_window_layout(800, 600)
        self.assertEqual(geometry, "540x520+60+70")
        self.assertEqual(minimum, (420, 520))

        geometry, minimum = compute_palette_tool_window_layout(400, 450)
        self.assertEqual(geometry, "320x370+60+30")
        self.assertEqual(minimum, (320, 370))

        source = _method_source("_build_ui")
        self.assertIn('wraplength=max(280, int(event.width) - 28)', source)
        self.assertIn('wraplength=360', source)

    @staticmethod
    def _geometry_rect(geometry: str) -> tuple[int, int, int, int]:
        size, x_text, y_text = geometry.split("+", 2)
        width_text, height_text = size.split("x", 1)
        return int(x_text), int(y_text), int(width_text), int(height_text)

    def test_three_tool_windows_tile_without_overlap_on_a_normal_screen(self) -> None:
        layouts = compute_manual_tool_window_layouts(1920, 1080)
        palette = self._geometry_rect(layouts["palette"][0])
        parts = self._geometry_rect(layouts["parts"][0])
        help_window = self._geometry_rect(layouts["help"][0])

        self.assertEqual(palette, (20, 70, 540, 760))
        self.assertEqual(parts, (1430, 70, 470, 330))
        self.assertEqual(help_window, (1540, 440, 360, 590))
        self.assertLessEqual(palette[0] + palette[2], help_window[0])
        # Client rectangles also reserve 30px for the native title/frame and
        # retain a visible 10px gap between the two right-side tool windows.
        self.assertLessEqual(parts[1] + parts[3] + 30 + 10, help_window[1])
        self.assertLessEqual(help_window[1] + help_window[3] + 30, 1080 - 20)
        self.assertEqual(parts[0] + parts[2], 1900)
        self.assertEqual(help_window[0] + help_window[2], 1900)

    def test_three_tool_windows_stay_clamped_when_the_screen_is_small(self) -> None:
        for screen_width, screen_height in ((800, 600), (400, 450), (1, 1)):
            with self.subTest(screen=(screen_width, screen_height)):
                layouts = compute_manual_tool_window_layouts(
                    screen_width, screen_height
                )
                origins: list[tuple[int, int]] = []
                for geometry, minimum in layouts.values():
                    x, y, width, height = self._geometry_rect(geometry)
                    origins.append((x, y))
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertGreater(width, 0)
                    self.assertGreater(height, 0)
                    self.assertLessEqual(x + width, screen_width)
                    self.assertLessEqual(y + height, screen_height)
                    self.assertLessEqual(minimum[0], width)
                    self.assertLessEqual(minimum[1], height)
                if screen_width > 1 and screen_height > 1:
                    self.assertGreater(len(set(origins)), 1)

    def test_all_three_tool_windows_are_initially_requested_and_deferred(self) -> None:
        init_source = _method_source("__init__")
        build_source = _method_source("_build_ui")

        self.assertIn("self.palette_visible_var = tk.BooleanVar(value=True)", init_source)
        self.assertIn(
            "self.parts_tool_visible_var = tk.BooleanVar(value=True)", init_source
        )
        self.assertIn(
            "self.help_tool_visible_var = tk.BooleanVar(value=True)", init_source
        )
        self.assertIn('self._ribbon_selected = "brush"', init_source)
        self.assertIn(
            'self._select_ribbon("brush", ensure_expanded=False)', build_source
        )
        self.assertIn("self.window.after_idle(", build_source)
        self.assertIn("self._show_initial_tool_windows", build_source)
        self.assertIn(
            'self.window.bind("<Destroy>", self._on_editor_destroyed, add="+")',
            build_source,
        )

    def test_initial_show_uses_the_shared_desired_visibility_path(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor._closing = False
        editor._close_requested = False
        editor._initial_tool_windows_after = "pending"
        calls: list[str] = []
        editor._apply_desired_tool_window_visibility = lambda: calls.append("show")

        PaintEditorWindow._show_initial_tool_windows(editor)

        self.assertIsNone(editor._initial_tool_windows_after)
        self.assertEqual(calls, ["show"])

    def test_direct_tk_destroy_cancels_the_initial_idle_callback_once(self) -> None:
        class _Window:
            def __init__(self) -> None:
                self.cancelled: list[str] = []

            def after_cancel(self, after_id: str) -> None:
                self.cancelled.append(after_id)

        editor = object.__new__(PaintEditorWindow)
        editor.window = _Window()
        editor._initial_tool_windows_after = "after-initial"

        PaintEditorWindow._on_editor_destroyed(
            editor, SimpleNamespace(widget=object())
        )
        self.assertEqual(editor._initial_tool_windows_after, "after-initial")

        event = SimpleNamespace(widget=editor.window)
        PaintEditorWindow._on_editor_destroyed(editor, event)
        PaintEditorWindow._on_editor_destroyed(editor, event)

        self.assertIsNone(editor._initial_tool_windows_after)
        self.assertEqual(editor.window.cancelled, ["after-initial"])

    def test_shared_initial_path_opens_all_three_requested_windows(self) -> None:
        class _ToolWindow:
            def __init__(self) -> None:
                self.deiconify_calls = 0
                self.lift_calls = 0

            def winfo_exists(self) -> bool:
                return True

            def deiconify(self) -> None:
                self.deiconify_calls += 1

            def lift(self) -> None:
                self.lift_calls += 1

        windows = [_ToolWindow(), _ToolWindow(), _ToolWindow()]
        editor = object.__new__(PaintEditorWindow)
        editor._tool_windows_with_desired_visibility = lambda: tuple(
            (window, _Var(True)) for window in windows
        )
        editor._sync_part_visibility_controls = lambda: None
        editor._refresh_workspace_controls = lambda: None

        PaintEditorWindow._apply_desired_tool_window_visibility(editor)

        self.assertEqual(
            [(window.deiconify_calls, window.lift_calls) for window in windows],
            [(1, 1), (1, 1), (1, 1)],
        )

    def test_tool_to_ribbon_mapping_matches_the_new_grouping(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        selected: list[str] = []
        editor._select_ribbon = selected.append

        for tool in (
            "orbit",
            "brush",
            "airbrush",
            "eyedropper",
            "smudge",
            "fill",
            "smooth",
            "erase",
            "lasso",
            "joint",
        ):
            PaintEditorWindow._select_ribbon_for_tool(editor, tool)
        PaintEditorWindow._select_ribbon_for_tool(editor, "unknown")

        self.assertEqual(
            selected,
            [
                "home",
                "brush",
                "brush",
                "brush",
                "brush",
                "brush",
                "brush",
                "brush",
            ],
        )

    def test_explicit_tool_click_routes_even_when_the_tool_is_already_active(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor.tool_var = _Var("brush")
        editor._last_tool_mode = "brush"
        selected: list[str] = []
        editor._select_ribbon_for_tool = selected.append

        PaintEditorWindow._on_tool_changed(editor)
        self.assertEqual(selected, [])

        PaintEditorWindow._on_tool_changed(editor, ensure_ribbon=True)
        self.assertEqual(selected, ["brush"])

    def test_brush_parts_and_help_are_real_os_tool_windows(self) -> None:
        source = _PAINT_GUI_SOURCE
        for attribute in (
            "palette_tool_window",
            "parts_tool_window",
            "help_tool_window",
        ):
            with self.subTest(attribute=attribute):
                assignment = rf"self\.{attribute}\s*=\s*tk\.Toplevel\("
                self.assertRegex(source, assignment)

    def test_tool_windows_are_not_embedded_or_clamped_to_the_editor(self) -> None:
        source = _PAINT_GUI_SOURCE
        for attribute in (
            "palette_tool_window",
            "parts_tool_window",
            "help_tool_window",
        ):
            with self.subTest(attribute=attribute):
                # A native Toplevel owns its screen coordinates.  Keeping these
                # windows out of Canvas/place-based positioning lets users move
                # them beyond the manual editor, including onto another monitor.
                self.assertNotRegex(
                    source,
                    rf"self\.{attribute}\.(?:place|place_configure)\(",
                )
                self.assertNotRegex(
                    source,
                    rf"self\.{attribute}\.overrideredirect\(True\)",
                )

        drag_source = _method_source("_drag_palette")
        self.assertIn("palette.geometry(", drag_source)
        self.assertNotIn("max(", drag_source)
        self.assertNotIn("min(", drag_source)

    def test_public_show_commands_exist_for_each_tool_window(self) -> None:
        for method in (
            "_show_palette_tool_window",
            "_show_parts_tool_window",
            "_show_shortcut_help",
        ):
            with self.subTest(method=method):
                self.assertTrue(callable(getattr(PaintEditorWindow, method, None)))

    def test_parts_tool_window_exposes_all_three_bulk_visibility_commands(self) -> None:
        source = _PAINT_GUI_SOURCE
        for command in (
            "show_only_active_part",
            "make_other_parts_transparent",
            "show_all_parts",
        ):
            with self.subTest(command=command):
                self.assertRegex(source, rf"command=self\.{command}\b")

    def test_brush_tool_window_accepts_negative_screen_coordinates(self) -> None:
        class _ToolWindow:
            def __init__(self) -> None:
                self.geometry_calls: list[str] = []

            def geometry(self, value: str) -> None:
                self.geometry_calls.append(value)

        editor = object.__new__(PaintEditorWindow)
        editor._palette_drag_origin = (100, 100, 20, 30)
        editor.floating_palette = _ToolWindow()

        PaintEditorWindow._drag_palette(
            editor,
            SimpleNamespace(x_root=-20, y_root=-40),
        )

        self.assertEqual(editor._palette_place, (-100, -110))
        self.assertEqual(
            editor.floating_palette.geometry_calls,
            ["-100-110"],
        )

    def test_parent_restore_reopens_only_panels_the_user_left_open(self) -> None:
        class _ParentWindow:
            def __init__(self) -> None:
                self.state_value = "iconic"
                self.after_calls: list[tuple[int, object]] = []
                self.cancelled: list[str] = []

            def state(self) -> str:
                return self.state_value

            def after(self, delay: int, callback) -> str:
                self.after_calls.append((int(delay), callback))
                return f"after-{len(self.after_calls)}"

            def after_cancel(self, after_id: str) -> None:
                self.cancelled.append(after_id)

        class _ToolWindow:
            def __init__(self) -> None:
                self.withdraw_calls = 0
                self.deiconify_calls = 0
                self.lift_calls = 0

            def winfo_exists(self) -> bool:
                return True

            def withdraw(self) -> None:
                self.withdraw_calls += 1

            def deiconify(self) -> None:
                self.deiconify_calls += 1

            def lift(self) -> None:
                self.lift_calls += 1

        editor = object.__new__(PaintEditorWindow)
        editor.window = _ParentWindow()
        editor._closing = False
        editor._close_requested = False
        editor._tool_restore_after = None
        editor._tool_restore_verify_after = None
        editor._tool_restore_attempts = 0
        editor.palette_tool_window = _ToolWindow()
        editor.parts_tool_window = _ToolWindow()
        editor.help_tool_window = _ToolWindow()
        editor.palette_visible_var = _Var(True)
        # The user explicitly closed Parts before minimizing Manual Editing.
        editor.parts_tool_visible_var = _Var(False)
        editor.help_tool_visible_var = _Var(True)
        editor._sync_part_visibility_controls = lambda: None
        editor._refresh_workspace_controls = lambda: None

        PaintEditorWindow._on_editor_unmapped(
            editor, SimpleNamespace(widget=editor.window)
        )
        PaintEditorWindow._on_editor_mapped(
            editor, SimpleNamespace(widget=editor.window)
        )
        self.assertEqual(editor.window.after_calls[0][0], TOOL_RESTORE_DELAY_MS)
        self.assertGreaterEqual(TOOL_RESTORE_DELAY_MS, 250)

        # Map may precede completion of SW_RESTORE; that pass must retry.
        editor.window.after_calls.pop(0)[1]()
        self.assertEqual(editor.window.after_calls[0][0], TOOL_RESTORE_RETRY_MS)
        self.assertEqual(editor.palette_tool_window.deiconify_calls, 0)

        # Once the parent is normal, restore and schedule a second Windows
        # ownership verification pass.
        editor.window.state_value = "normal"
        editor.window.after_calls.pop(0)[1]()
        self.assertEqual(
            editor.window.after_calls[0][0], TOOL_RESTORE_VERIFY_DELAY_MS
        )
        editor.window.after_calls.pop(0)[1]()

        self.assertEqual(editor.palette_tool_window.withdraw_calls, 1)
        self.assertEqual(editor.help_tool_window.withdraw_calls, 1)
        self.assertEqual(editor.parts_tool_window.withdraw_calls, 0)
        self.assertEqual(editor.palette_tool_window.deiconify_calls, 2)
        self.assertEqual(editor.help_tool_window.deiconify_calls, 2)
        self.assertEqual(editor.parts_tool_window.deiconify_calls, 0)


class ManualPartSelectionOutlineTests(unittest.TestCase):
    def test_part_selection_immediately_invalidates_and_queues_active_outline(self) -> None:
        editor = object.__new__(PaintEditorWindow)
        editor.active_part_id = 0
        editor.part_labels = ("1: Front", "2: Back")
        editor.part_names = ("Front", "Back")
        editor.part_target_var = _Var("2: Back")
        editor.level = SimpleNamespace(
            faces=np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int32),
            face_part_ids=np.asarray([0, 1], dtype=np.int16),
        )
        editor.i18n = Translator("en")
        editor._renderer = _Renderer()
        editor._view_appearance = SimpleNamespace(active_part_accent=(0, 220, 255))
        allowed_masks: list[np.ndarray] = []
        editor._session = SimpleNamespace(
            set_allowed_faces=lambda mask: allowed_masks.append(mask.copy())
        )
        editor._worker_snapshot = lambda frame, message: {
            "frame": frame,
            "message": message,
        }
        editor.face_ids = np.asarray([[0, 1]], dtype=np.int32)
        editor._render_dirty = False
        editor.parts_tool_window = None
        editor._reject_during_topology_change = lambda: False
        editor._commit_active_stroke = lambda: None
        editor._sync_part_visibility_controls = lambda: None
        editor._refresh_palette_buttons = lambda: None
        editor._sync_active_part_identity = lambda: None
        queued: list[tuple[str, object]] = []
        editor._submit = lambda name, work: queued.append((name, work))

        PaintEditorWindow._on_editor_part_selected(editor)

        self.assertEqual(editor.active_part_id, 1)
        self.assertIsNone(editor.face_ids)
        self.assertTrue(editor._render_dirty)
        self.assertEqual(editor._renderer.active_calls, [])
        self.assertEqual([name for name, _work in queued], ["part"])
        self.assertIsNone(editor.parts_tool_window)

        # Simulate the queued render-thread work.  GPU state must be updated
        # there, while opening the Parts palette remains completely unrelated.
        queued[0][1]()
        self.assertEqual(
            editor._renderer.active_calls,
            [(1, (0, 220, 255))],
        )
        np.testing.assert_array_equal(allowed_masks[0], [False, True])


class ManualBulkPartVisibilityTests(unittest.TestCase):
    def _editor(self, modes=(PART_VISIBLE, PART_VISIBLE, PART_VISIBLE)):
        editor = object.__new__(PaintEditorWindow)
        editor.active_part_id = 1
        editor.part_names = ("A", "B", "C")
        editor.part_labels = ("1: A", "2: B", "3: C")
        editor._part_visibility_modes = np.asarray(modes, dtype=np.uint8)
        editor.part_visibility_var = _Var("")
        editor.pick_transparent_var = _Var(False)
        editor.i18n = Translator("en")
        editor._reject_during_topology_change = lambda: False
        editor._commit_active_stroke = lambda: None
        editor._sync_part_visibility_controls = lambda: None
        updates: list[str] = []
        editor._queue_visibility_update = updates.append
        return editor, updates

    def test_show_only_active_hides_every_other_part(self) -> None:
        editor, updates = self._editor(
            (PART_TRANSPARENT, PART_HIDDEN, PART_VISIBLE)
        )

        PaintEditorWindow.show_only_active_part(editor)

        np.testing.assert_array_equal(
            editor._part_visibility_modes,
            np.asarray([PART_HIDDEN, PART_VISIBLE, PART_HIDDEN], dtype=np.uint8),
        )
        self.assertEqual(len(updates), 1)

    def test_make_others_transparent_keeps_active_part_opaque(self) -> None:
        editor, updates = self._editor(
            (PART_HIDDEN, PART_TRANSPARENT, PART_VISIBLE)
        )

        PaintEditorWindow.make_other_parts_transparent(editor)

        np.testing.assert_array_equal(
            editor._part_visibility_modes,
            np.asarray(
                [PART_TRANSPARENT, PART_VISIBLE, PART_TRANSPARENT],
                dtype=np.uint8,
            ),
        )
        self.assertEqual(len(updates), 1)

    def test_show_all_restores_every_part(self) -> None:
        editor, updates = self._editor(
            (PART_HIDDEN, PART_TRANSPARENT, PART_HIDDEN)
        )

        PaintEditorWindow.show_all_parts(editor)

        np.testing.assert_array_equal(
            editor._part_visibility_modes,
            np.full(3, PART_VISIBLE, dtype=np.uint8),
        )
        self.assertEqual(len(updates), 1)


if __name__ == "__main__":
    unittest.main()
