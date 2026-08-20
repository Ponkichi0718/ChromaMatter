"""Persistent, shape-aware brush cursor for the recovered paint editor.

The original editor deletes and recreates an oval on every pointer event.  This
adapter keeps one Canvas item and changes only its coordinates and visibility.
It is deliberately independent from the smooth-paint implementation; install
it after the input/paint patches have finished wrapping ``PaintEditorWindow``.
"""

from __future__ import annotations

from dataclasses import dataclass
import functools
import math
from typing import Any, Literal


CURSOR_TAG = "paint-brush-cursor-hotfix"
DEFAULT_MARKER_ANGLE_DEGREES = 0.0
MARKER_THICKNESS_RATIO = 0.25
_DIRECTION_EPSILON = 0.45


@dataclass(frozen=True, slots=True)
class BrushCursorGeometry:
    kind: Literal["oval", "polygon"]
    coordinates: tuple[float, ...]


def brush_cursor_geometry(
    center_xy: tuple[float, float],
    radius_pixels: float,
    shape: str,
    *,
    marker_angle_degrees: float = DEFAULT_MARKER_ANGLE_DEGREES,
    marker_thickness_ratio: float = MARKER_THICKNESS_RATIO,
) -> BrushCursorGeometry:
    """Return Canvas coordinates for a round or rectangular brush nib."""

    x = float(center_xy[0])
    y = float(center_xy[1])
    radius = float(radius_pixels)
    if not all(math.isfinite(value) for value in (x, y, radius)) or radius <= 0.0:
        raise ValueError("cursor center and radius must be finite; radius must be positive")
    if str(shape) != "marker":
        return BrushCursorGeometry(
            "oval",
            (x - radius, y - radius, x + radius, y + radius),
        )

    ratio = float(marker_thickness_ratio)
    angle = float(marker_angle_degrees)
    if not math.isfinite(ratio) or ratio <= 0.0:
        raise ValueError("marker_thickness_ratio must be finite and positive")
    if not math.isfinite(angle):
        raise ValueError("marker_angle_degrees must be finite")
    half_thickness = max(0.5, radius * ratio)
    radians = math.radians(angle)
    major_x = math.cos(radians) * radius
    major_y = math.sin(radians) * radius
    minor_x = -math.sin(radians) * half_thickness
    minor_y = math.cos(radians) * half_thickness
    coordinates: list[float] = []
    for major_sign, minor_sign in (
        (-1.0, -1.0),
        (1.0, -1.0),
        (1.0, 1.0),
        (-1.0, 1.0),
    ):
        coordinates.extend(
            (
                x + major_sign * major_x + minor_sign * minor_x,
                y + major_sign * major_y + minor_sign * minor_y,
            )
        )
    return BrushCursorGeometry("polygon", tuple(coordinates))


def _mapping_contains(mapping: Any, x: float, y: float) -> bool:
    if not isinstance(mapping, (tuple, list)) or len(mapping) < 4:
        return False
    try:
        left, top, width, height = (float(mapping[index]) for index in range(4))
    except (TypeError, ValueError):
        return False
    return bool(width > 0.0 and height > 0.0 and left <= x < left + width and top <= y < top + height)


def _brush_shape(editor: Any) -> str:
    tool = ""
    try:
        tool = str(editor.tool_var.get())
    except Exception:
        pass
    if tool not in ("brush", "erase"):
        return "round"
    variable = getattr(editor, "_hotfix_brush_shape_var", None)
    try:
        return "marker" if str(variable.get()) == "marker" else "round"
    except Exception:
        return "round"


def _paint_tool_active(editor: Any) -> bool:
    try:
        return str(editor.tool_var.get()) in (
            "brush",
            "airbrush",
            "smudge",
            "erase",
            "smooth",
        )
    except Exception:
        return False


def _item_exists(canvas: Any, item: Any) -> bool:
    if item is None:
        return False
    try:
        return bool(canvas.type(item))
    except Exception:
        return False


def _hide_cursor(editor: Any, *, forget_pointer: bool = False) -> None:
    item = getattr(editor, "_hotfix_brush_cursor_item", None)
    canvas = getattr(editor, "canvas", None)
    if canvas is not None and _item_exists(canvas, item):
        try:
            canvas.itemconfigure(item, state="hidden")
        except Exception:
            pass
    if forget_pointer:
        editor._hotfix_brush_cursor_pointer = None
        editor._hotfix_brush_cursor_last_pointer = None


def _delete_cursor(editor: Any) -> None:
    canvas = getattr(editor, "canvas", None)
    item = getattr(editor, "_hotfix_brush_cursor_item", None)
    if canvas is not None and item is not None:
        try:
            canvas.delete(item)
        except Exception:
            pass
    editor._hotfix_brush_cursor_item = None
    editor._hotfix_brush_cursor_kind = None


def _record_pointer(editor: Any, x: float, y: float) -> None:
    point = (float(x), float(y))
    previous = getattr(editor, "_hotfix_brush_cursor_last_pointer", None)
    if previous is not None:
        dx = point[0] - float(previous[0])
        dy = point[1] - float(previous[1])
        if math.hypot(dx, dy) >= _DIRECTION_EPSILON:
            # A marker nib's long edge remains perpendicular to its travel.
            editor._hotfix_brush_cursor_angle = math.degrees(math.atan2(dy, dx)) + 90.0
    editor._hotfix_brush_cursor_pointer = point
    editor._hotfix_brush_cursor_last_pointer = point


def _pointer_is_on_target(editor: Any, point: tuple[float, float]) -> bool:
    x, y = point
    mapping = getattr(editor, "target_mapping", None)
    if not _mapping_contains(mapping, x, y):
        return False
    face_at = getattr(editor, "_face_at", None)
    if not callable(face_at):
        return True
    try:
        return int(face_at(int(round(x)), int(round(y)))) >= 0
    except Exception:
        return False


def _ensure_canvas_item(editor: Any, geometry: BrushCursorGeometry) -> Any:
    canvas = editor.canvas
    item = getattr(editor, "_hotfix_brush_cursor_item", None)
    current_kind = getattr(editor, "_hotfix_brush_cursor_kind", None)
    if not _item_exists(canvas, item) or current_kind != geometry.kind:
        _delete_cursor(editor)
        options = {
            "fill": "",
            "outline": getattr(editor, "_hotfix_brush_cursor_color", "#58D5FF"),
            "width": 2,
            "state": "hidden",
            "tags": (CURSOR_TAG,),
        }
        if geometry.kind == "polygon":
            item = canvas.create_polygon(*geometry.coordinates, **options)
        else:
            item = canvas.create_oval(*geometry.coordinates, **options)
        editor._hotfix_brush_cursor_item = item
        editor._hotfix_brush_cursor_kind = geometry.kind
    return item


def _refresh_cursor(editor: Any) -> None:
    if bool(getattr(editor, "_hotfix_brush_cursor_closed", False)):
        return
    if getattr(editor, "_drag_mode", None) is not None or not _paint_tool_active(editor):
        _hide_cursor(editor)
        return
    point = getattr(editor, "_hotfix_brush_cursor_pointer", None)
    if point is None or not _pointer_is_on_target(editor, point):
        _hide_cursor(editor)
        return
    try:
        radius = max(0.5, float(editor._brush_radius_pixels()))
        geometry = brush_cursor_geometry(
            point,
            radius,
            _brush_shape(editor),
            marker_angle_degrees=float(
                getattr(
                    editor,
                    "_hotfix_brush_cursor_angle",
                    DEFAULT_MARKER_ANGLE_DEGREES,
                )
            ),
        )
        item = _ensure_canvas_item(editor, geometry)
        editor.canvas.coords(item, *geometry.coordinates)
        editor.canvas.itemconfigure(
            item,
            outline=getattr(editor, "_hotfix_brush_cursor_color", "#58D5FF"),
            state="normal",
        )
        try:
            editor.canvas.tag_raise(item)
        except Exception:
            pass
    except Exception:
        _hide_cursor(editor)


def _remove_traces(editor: Any) -> None:
    for variable, mode, token in list(
        getattr(editor, "_hotfix_brush_cursor_traces", ())
    ):
        try:
            variable.trace_remove(mode, token)
        except Exception:
            pass
    editor._hotfix_brush_cursor_traces = []


def apply_brush_cursor_hotfix(paint_gui: Any) -> Any:
    """Patch ``PaintEditorWindow`` with one reusable shape-aware cursor item."""

    editor_class = paint_gui.PaintEditorWindow
    if bool(getattr(editor_class, "_brush_cursor_hotfix_applied", False)):
        return editor_class

    original_init = editor_class.__init__
    original_pointer_motion = getattr(editor_class, "_on_pointer_motion", None)
    original_draw_canvas = getattr(editor_class, "_draw_canvas", None)
    original_close = getattr(editor_class, "close", None)

    @functools.wraps(original_init)
    def init_cursor(self, *args, **kwargs):
        self._hotfix_brush_cursor_item = None
        self._hotfix_brush_cursor_kind = None
        self._hotfix_brush_cursor_pointer = None
        self._hotfix_brush_cursor_last_pointer = None
        self._hotfix_brush_cursor_angle = DEFAULT_MARKER_ANGLE_DEGREES
        self._hotfix_brush_cursor_closed = False
        self._hotfix_brush_cursor_traces = []
        self._hotfix_brush_cursor_color = str(getattr(paint_gui, "ACCENT", "#58D5FF"))
        original_init(self, *args, **kwargs)

        try:
            self.canvas.bind(
                "<Leave>",
                lambda _event: _hide_cursor(self, forget_pointer=True),
                add="+",
            )
        except Exception:
            pass

        def changed(*_ignored):
            _refresh_cursor(self)

        for variable in (
            getattr(self, "tool_var", None),
            getattr(self, "_hotfix_brush_shape_var", None),
            getattr(self, "brush_radius_var", None),
        ):
            if variable is None:
                continue
            try:
                token = variable.trace_add("write", changed)
                self._hotfix_brush_cursor_traces.append((variable, "write", token))
            except Exception:
                pass

    def pointer_motion_cursor(self, event):
        if bool(getattr(self, "_close_requested", False)):
            _hide_cursor(self, forget_pointer=True)
            return None
        _record_pointer(self, float(event.x), float(event.y))
        _refresh_cursor(self)
        return None

    def draw_canvas_cursor(self, *args, **kwargs):
        # The recovered renderer deletes every Canvas item while rebuilding the
        # two panels.  Forget that stale numeric handle and create one new item
        # after the new target mapping is known.
        self._hotfix_brush_cursor_item = None
        self._hotfix_brush_cursor_kind = None
        result = original_draw_canvas(self, *args, **kwargs)
        _refresh_cursor(self)
        return result

    def close_cursor(self, *args, **kwargs):
        if not bool(getattr(self, "_hotfix_brush_cursor_closed", False)):
            self._hotfix_brush_cursor_closed = True
            _remove_traces(self)
            _delete_cursor(self)
            self._hotfix_brush_cursor_pointer = None
            self._hotfix_brush_cursor_last_pointer = None
        return original_close(self, *args, **kwargs)

    def wrap_drag(name: str, *, release: bool = False) -> None:
        original = getattr(editor_class, name, None)
        if not callable(original):
            return

        def wrapped(self, event, _original=original):
            if event is not None and hasattr(event, "x") and hasattr(event, "y"):
                _record_pointer(self, float(event.x), float(event.y))
            _hide_cursor(self)
            result = _original(self, event)
            if release:
                _hide_cursor(self, forget_pointer=True)
            else:
                _hide_cursor(self)
            return result

        setattr(editor_class, name, wrapped)

    editor_class.__init__ = init_cursor
    if callable(original_pointer_motion):
        editor_class._on_pointer_motion = pointer_motion_cursor
    if callable(original_draw_canvas):
        editor_class._draw_canvas = draw_canvas_cursor
    if callable(original_close):
        editor_class.close = close_cursor
    for method_name in (
        "_on_left_press",
        "_on_left_motion",
        "_on_right_press",
        "_on_right_motion",
        "_on_middle_press",
        "_on_middle_motion",
    ):
        wrap_drag(method_name)
    for method_name in (
        "_on_left_release",
        "_on_right_release",
        "_on_middle_release",
    ):
        wrap_drag(method_name, release=True)
    editor_class._brush_cursor_hotfix_applied = True
    return editor_class


__all__ = [
    "BrushCursorGeometry",
    "CURSOR_TAG",
    "DEFAULT_MARKER_ANGLE_DEGREES",
    "MARKER_THICKNESS_RATIO",
    "apply_brush_cursor_hotfix",
    "brush_cursor_geometry",
]
