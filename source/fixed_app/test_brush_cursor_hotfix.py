from __future__ import annotations

from types import SimpleNamespace
import unittest

import brush_cursor_hotfix as cursor_hotfix


class FakeVariable:
    def __init__(self, value):
        self.value = value
        self._callbacks: dict[str, object] = {}
        self._serial = 0

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value
        for callback in tuple(self._callbacks.values()):
            callback("variable", "", "write")

    def trace_add(self, _mode: str, callback) -> str:
        self._serial += 1
        token = f"trace-{self._serial}"
        self._callbacks[token] = callback
        return token

    def trace_remove(self, _mode: str, token: str) -> None:
        self._callbacks.pop(token, None)


class FakeCanvas:
    def __init__(self) -> None:
        self.items: dict[int, dict[str, object]] = {}
        self.bindings: dict[str, list[object]] = {}
        self.next_item = 1
        self.create_count = 0
        self.raise_count = 0

    def _create(self, kind: str, coordinates, options) -> int:
        item = self.next_item
        self.next_item += 1
        self.create_count += 1
        self.items[item] = {
            "kind": kind,
            "coordinates": tuple(float(value) for value in coordinates),
            "options": dict(options),
        }
        return item

    def create_oval(self, *coordinates, **options) -> int:
        return self._create("oval", coordinates, options)

    def create_polygon(self, *coordinates, **options) -> int:
        return self._create("polygon", coordinates, options)

    def coords(self, item: int, *coordinates):
        if coordinates:
            self.items[item]["coordinates"] = tuple(float(value) for value in coordinates)
        return self.items[item]["coordinates"]

    def itemconfigure(self, item: int, **options) -> None:
        self.items[item]["options"].update(options)

    def type(self, item: int) -> str:
        value = self.items.get(item)
        return "" if value is None else str(value["kind"])

    def delete(self, value) -> None:
        if value == "all":
            self.items.clear()
            return
        if isinstance(value, int):
            self.items.pop(value, None)
            return
        doomed = []
        for item, data in self.items.items():
            tags = data["options"].get("tags", ())
            if isinstance(tags, str):
                tags = (tags,)
            if value in tags:
                doomed.append(item)
        for item in doomed:
            self.items.pop(item, None)

    def tag_raise(self, _item: int) -> None:
        self.raise_count += 1

    def bind(self, sequence: str, callback, add=None) -> None:
        if add != "+":
            self.bindings[sequence] = []
        self.bindings.setdefault(sequence, []).append(callback)

    def fire(self, sequence: str, event) -> None:
        for callback in tuple(self.bindings.get(sequence, ())):
            callback(event)


def make_editor_class():
    class FakeEditor:
        def __init__(self):
            self.canvas = FakeCanvas()
            self.tool_var = FakeVariable("brush")
            self._hotfix_brush_shape_var = FakeVariable("round")
            self.brush_radius_var = FakeVariable(3.0)
            self.target_mapping = (10, 20, 100, 80, 200, 160)
            self.scale = 2.0
            self.face_enabled = True
            self._drag_mode = None
            self._close_requested = False
            self.closed = False
            self.draw_count = 0
            self.drag_calls: list[str] = []

        def _brush_radius_pixels(self) -> float:
            return float(self.brush_radius_var.get()) * float(self.scale)

        def _face_at(self, x: int, y: int) -> int:
            left, top, width, height, _rw, _rh = self.target_mapping
            inside = left <= x < left + width and top <= y < top + height
            return 4 if inside and self.face_enabled else -1

        def _on_pointer_motion(self, _event) -> None:
            raise AssertionError("the allocating recovered cursor must not run")

        def _draw_canvas(self) -> None:
            self.draw_count += 1
            self.canvas.delete("all")

        def _on_left_press(self, _event) -> None:
            self.drag_calls.append("left_press")
            self._drag_mode = "stroke"

        def _on_left_motion(self, _event) -> None:
            self.drag_calls.append("left_motion")

        def _on_left_release(self, _event) -> None:
            self.drag_calls.append("left_release")
            self._drag_mode = None

        def _on_right_press(self, _event) -> None:
            self._drag_mode = "orbit"

        def _on_right_motion(self, _event) -> None:
            pass

        def _on_right_release(self, _event) -> None:
            self._drag_mode = None

        def _on_middle_press(self, _event) -> None:
            self._drag_mode = "pan"

        def _on_middle_motion(self, _event) -> None:
            pass

        def _on_middle_release(self, _event) -> None:
            self._drag_mode = None

        def close(self, *_args, **_kwargs) -> None:
            self.closed = True

    return FakeEditor


def patched_editor():
    editor_class = make_editor_class()
    module = SimpleNamespace(PaintEditorWindow=editor_class, ACCENT="#35C8FF")
    cursor_hotfix.apply_brush_cursor_hotfix(module)
    return editor_class()


class BrushCursorGeometryTests(unittest.TestCase):
    def test_round_and_oriented_marker_dimensions(self) -> None:
        round_geometry = cursor_hotfix.brush_cursor_geometry((50.0, 40.0), 10.0, "round")
        self.assertEqual(round_geometry.kind, "oval")
        self.assertEqual(round_geometry.coordinates, (40.0, 30.0, 60.0, 50.0))

        horizontal = cursor_hotfix.brush_cursor_geometry(
            (50.0, 40.0), 10.0, "marker", marker_angle_degrees=0.0
        )
        self.assertEqual(horizontal.kind, "polygon")
        xs = horizontal.coordinates[0::2]
        ys = horizontal.coordinates[1::2]
        self.assertEqual((min(xs), max(xs)), (40.0, 60.0))
        self.assertEqual((min(ys), max(ys)), (37.5, 42.5))

        vertical = cursor_hotfix.brush_cursor_geometry(
            (50.0, 40.0), 10.0, "marker", marker_angle_degrees=90.0
        )
        xs = vertical.coordinates[0::2]
        ys = vertical.coordinates[1::2]
        self.assertAlmostEqual(min(xs), 47.5)
        self.assertAlmostEqual(max(xs), 52.5)
        self.assertAlmostEqual(min(ys), 30.0)
        self.assertAlmostEqual(max(ys), 50.0)

    def test_invalid_geometry_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cursor_hotfix.brush_cursor_geometry((0.0, 0.0), 0.0, "round")
        with self.assertRaises(ValueError):
            cursor_hotfix.brush_cursor_geometry(
                (0.0, 0.0), 2.0, "marker", marker_thickness_ratio=0.0
            )


class BrushCursorPatchTests(unittest.TestCase):
    def test_round_cursor_reuses_one_canvas_item_per_motion(self) -> None:
        editor = patched_editor()
        editor._on_pointer_motion(SimpleNamespace(x=50, y=50))
        item = editor._hotfix_brush_cursor_item
        self.assertEqual(editor.canvas.type(item), "oval")
        self.assertEqual(editor.canvas.create_count, 1)
        self.assertEqual(editor.canvas.items[item]["options"]["state"], "normal")

        editor._on_pointer_motion(SimpleNamespace(x=55, y=52))
        self.assertEqual(editor._hotfix_brush_cursor_item, item)
        self.assertEqual(editor.canvas.create_count, 1)
        self.assertEqual(
            editor.canvas.coords(item),
            (49.0, 46.0, 61.0, 58.0),
        )

        editor._on_pointer_motion(SimpleNamespace(x=200, y=52))
        self.assertEqual(editor.canvas.items[item]["options"]["state"], "hidden")
        self.assertEqual(editor.canvas.create_count, 1)

    def test_marker_tracks_last_motion_direction_without_reallocation(self) -> None:
        editor = patched_editor()
        editor._hotfix_brush_shape_var.set("marker")
        editor._on_pointer_motion(SimpleNamespace(x=50, y=50))
        item = editor._hotfix_brush_cursor_item
        first = editor.canvas.coords(item)
        self.assertEqual(editor.canvas.type(item), "polygon")
        self.assertEqual((min(first[0::2]), max(first[0::2])), (44.0, 56.0))

        # Travel to the right rotates the long nib edge to vertical.
        editor._on_pointer_motion(SimpleNamespace(x=60, y=50))
        vertical = editor.canvas.coords(item)
        self.assertEqual(editor._hotfix_brush_cursor_item, item)
        self.assertEqual(editor.canvas.create_count, 1)
        self.assertAlmostEqual(min(vertical[0::2]), 58.5)
        self.assertAlmostEqual(max(vertical[0::2]), 61.5)
        self.assertAlmostEqual(min(vertical[1::2]), 44.0)
        self.assertAlmostEqual(max(vertical[1::2]), 56.0)

        # The cursor is hidden while dragging, but the last stroke direction is
        # retained and used after the next ordinary Motion event.
        editor._on_left_press(SimpleNamespace(x=60, y=50))
        editor._on_left_motion(SimpleNamespace(x=70, y=50))
        self.assertEqual(editor.canvas.items[item]["options"]["state"], "hidden")
        editor._on_left_release(SimpleNamespace(x=70, y=50))
        editor._on_pointer_motion(SimpleNamespace(x=70, y=50))
        after_drag = editor.canvas.coords(item)
        self.assertAlmostEqual(min(after_drag[0::2]), 68.5)
        self.assertAlmostEqual(max(after_drag[0::2]), 71.5)
        self.assertAlmostEqual(min(after_drag[1::2]), 44.0)
        self.assertAlmostEqual(max(after_drag[1::2]), 56.0)

    def test_radius_shape_zoom_and_mapping_refresh_at_stationary_pointer(self) -> None:
        editor = patched_editor()
        editor._on_pointer_motion(SimpleNamespace(x=50, y=50))
        first_item = editor._hotfix_brush_cursor_item

        editor.brush_radius_var.set(4.0)
        self.assertEqual(editor._hotfix_brush_cursor_item, first_item)
        self.assertEqual(editor.canvas.coords(first_item), (42.0, 42.0, 58.0, 58.0))

        editor._hotfix_brush_shape_var.set("marker")
        marker_item = editor._hotfix_brush_cursor_item
        self.assertNotEqual(marker_item, first_item)
        self.assertEqual(editor.canvas.type(marker_item), "polygon")

        # A full redraw deletes all items.  The wrapper creates exactly one new
        # cursor from the updated display scale and target mapping.
        editor.scale = 3.0
        editor._draw_canvas()
        redrawn_item = editor._hotfix_brush_cursor_item
        self.assertNotEqual(redrawn_item, marker_item)
        coordinates = editor.canvas.coords(redrawn_item)
        self.assertEqual((min(coordinates[0::2]), max(coordinates[0::2])), (38.0, 62.0))

        editor.target_mapping = (100, 100, 40, 40, 80, 80)
        editor._draw_canvas()
        self.assertIsNone(editor._hotfix_brush_cursor_item)

    def test_model_hit_tool_leave_and_close_remove_all_remnants(self) -> None:
        editor = patched_editor()
        editor.face_enabled = False
        editor._on_pointer_motion(SimpleNamespace(x=50, y=50))
        self.assertIsNone(editor._hotfix_brush_cursor_item)

        editor.face_enabled = True
        editor._on_pointer_motion(SimpleNamespace(x=50, y=50))
        item = editor._hotfix_brush_cursor_item
        editor.tool_var.set("fill")
        self.assertEqual(editor.canvas.items[item]["options"]["state"], "hidden")
        editor.tool_var.set("brush")
        self.assertEqual(editor.canvas.items[item]["options"]["state"], "normal")

        editor.canvas.fire("<Leave>", SimpleNamespace(x=0, y=0))
        self.assertEqual(editor.canvas.items[item]["options"]["state"], "hidden")
        self.assertIsNone(editor._hotfix_brush_cursor_pointer)

        editor._on_pointer_motion(SimpleNamespace(x=55, y=55))
        editor.close()
        self.assertTrue(editor.closed)
        self.assertIsNone(editor._hotfix_brush_cursor_item)
        self.assertEqual(editor.canvas.items, {})
        self.assertEqual(editor._hotfix_brush_cursor_traces, [])
        before = editor.canvas.create_count
        editor.brush_radius_var.set(9.0)
        editor._on_pointer_motion(SimpleNamespace(x=60, y=60))
        self.assertEqual(editor.canvas.create_count, before)

    def test_apply_is_idempotent(self) -> None:
        editor_class = make_editor_class()
        module = SimpleNamespace(PaintEditorWindow=editor_class, ACCENT="#35C8FF")
        first = cursor_hotfix.apply_brush_cursor_hotfix(module)
        second = cursor_hotfix.apply_brush_cursor_hotfix(module)
        self.assertIs(first, second)
        editor = editor_class()
        self.assertEqual(len(editor._hotfix_brush_cursor_traces), 3)
        self.assertEqual(len(editor.canvas.bindings["<Leave>"]), 1)


if __name__ == "__main__":
    unittest.main()
