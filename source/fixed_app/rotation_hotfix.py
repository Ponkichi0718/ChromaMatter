"""Responsive orbit rendering patch for the recovered paint editor.

The original editor uses a 28 ms trailing debounce and only presents a render
when its camera is still byte-for-byte current at the next 30 ms worker poll.
That combination drops nearly every frame during a continuous mouse drag.
Its Z-up yaw/pitch camera also stops before either pole.  Right-drag orbiting
is therefore promoted to a quaternion virtual trackball on first use, while
the existing fitted orthographic projection, zoom, pan and front reset remain
compatible with the recovered editor.

This module deliberately stays independent from ``spectrum_mapper_hotfix``.
Call ``apply_rotation_hotfix(spectrum_mapper.paint_gui)`` *after* the existing
hotfix module has installed its paint and picker corrections.
"""

from __future__ import annotations

import functools

from dataclasses import dataclass, is_dataclass, replace
import math
import queue
from typing import Any

import numpy as np


THROTTLE_MS = 8
ACTIVE_POLL_MS = 8
IDLE_POLL_MS = 30


@dataclass(frozen=True, slots=True)
class _PanCameraState:
    """Camera-compatible state with pan and an optional arcball orientation.

    The recovered renderer's public ``CameraState`` has only yaw, pitch and
    zoom.  Keeping pan and the quaternion in this private, value-comparable
    type lets the existing latest-only render and exact picker-camera guards
    include the complete view without changing the recovered bytecode API.

    ``orientation=None`` deliberately means "use the recovered yaw/pitch
    projection".  This preserves an existing view exactly when the user only
    pans or zooms.  The first orbit gesture promotes the state to a normalized
    quaternion and removes the old pitch stop/gimbal singularity.
    """

    yaw_degrees: float = 0.0
    pitch_degrees: float = 0.0
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    orientation: tuple[float, float, float, float] | None = None


_IDENTITY_QUATERNION = (1.0, 0.0, 0.0, 0.0)
_BASE_VIEW_ROTATION = np.asarray(
    (
        (1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, -1.0, 0.0),
    ),
    dtype=np.float64,
)


def _normalize_quaternion(
    quaternion: tuple[float, float, float, float] | np.ndarray,
) -> tuple[float, float, float, float]:
    values = np.asarray(quaternion, dtype=np.float64)
    if values.shape != (4,) or not np.isfinite(values).all():
        raise ValueError("Camera orientation must contain four finite numbers.")
    length = float(np.linalg.norm(values))
    if length <= 1e-12:
        raise ValueError("Camera orientation must not be the zero quaternion.")
    values /= length

    # q and -q describe the same orientation.  Canonicalizing the sign keeps
    # dataclass equality stable for the exact face-picker camera guard.
    for value in values:
        if abs(float(value)) <= 1e-14:
            continue
        if value < 0.0:
            values *= -1.0
        break
    return tuple(float(value) for value in values)  # type: ignore[return-value]


def _quaternion_multiply(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return _normalize_quaternion(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        )
    )


def _quaternion_between(
    start: np.ndarray, end: np.ndarray
) -> tuple[float, float, float, float]:
    """Return the shortest rotation taking unit vector ``start`` to ``end``."""

    start_value = np.asarray(start, dtype=np.float64)
    end_value = np.asarray(end, dtype=np.float64)
    start_value /= max(float(np.linalg.norm(start_value)), 1e-12)
    end_value /= max(float(np.linalg.norm(end_value)), 1e-12)
    dot = float(np.clip(np.dot(start_value, end_value), -1.0, 1.0))
    if dot >= 1.0 - 1e-12:
        return _IDENTITY_QUATERNION
    if dot <= -1.0 + 1e-9:
        # Opposite points have infinitely many valid axes.  Pick the most
        # stable perpendicular rather than letting a tiny cross product flip.
        basis = np.zeros(3, dtype=np.float64)
        basis[int(np.argmin(np.abs(start_value)))] = 1.0
        axis = np.cross(start_value, basis)
        axis /= max(float(np.linalg.norm(axis)), 1e-12)
        return _normalize_quaternion((0.0, axis[0], axis[1], axis[2]))
    cross = np.cross(start_value, end_value)
    return _normalize_quaternion((1.0 + dot, cross[0], cross[1], cross[2]))


def _quaternion_matrix(
    quaternion: tuple[float, float, float, float]
) -> np.ndarray:
    w, x, y, z = _normalize_quaternion(quaternion)
    return np.asarray(
        (
            (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)),
            (2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)),
            (2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)),
        ),
        dtype=np.float64,
    )


def _matrix_quaternion(matrix: np.ndarray) -> tuple[float, float, float, float]:
    """Convert a proper 3x3 rotation matrix to a stable quaternion."""

    value = np.asarray(matrix, dtype=np.float64)
    trace = float(np.trace(value))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quaternion = (
            0.25 * scale,
            (value[2, 1] - value[1, 2]) / scale,
            (value[0, 2] - value[2, 0]) / scale,
            (value[1, 0] - value[0, 1]) / scale,
        )
    else:
        index = int(np.argmax(np.diag(value)))
        if index == 0:
            scale = math.sqrt(max(1.0 + value[0, 0] - value[1, 1] - value[2, 2], 0.0)) * 2.0
            quaternion = (
                (value[2, 1] - value[1, 2]) / scale,
                0.25 * scale,
                (value[0, 1] + value[1, 0]) / scale,
                (value[0, 2] + value[2, 0]) / scale,
            )
        elif index == 1:
            scale = math.sqrt(max(1.0 + value[1, 1] - value[0, 0] - value[2, 2], 0.0)) * 2.0
            quaternion = (
                (value[0, 2] - value[2, 0]) / scale,
                (value[0, 1] + value[1, 0]) / scale,
                0.25 * scale,
                (value[1, 2] + value[2, 1]) / scale,
            )
        else:
            scale = math.sqrt(max(1.0 + value[2, 2] - value[0, 0] - value[1, 1], 0.0)) * 2.0
            quaternion = (
                (value[1, 0] - value[0, 1]) / scale,
                (value[0, 2] + value[2, 0]) / scale,
                (value[1, 2] + value[2, 1]) / scale,
                0.25 * scale,
            )
    return _normalize_quaternion(quaternion)


def _quaternion_from_yaw_pitch(
    yaw_degrees: float, pitch_degrees: float
) -> tuple[float, float, float, float]:
    """Promote the recovered Z-up orbit view without a visible camera jump."""

    yaw = math.radians(math.fmod(float(yaw_degrees), 360.0))
    pitch = math.radians(max(-84.0, min(84.0, float(pitch_degrees))))
    sin_yaw, cos_yaw = math.sin(yaw), math.cos(yaw)
    sin_pitch, cos_pitch = math.sin(pitch), math.cos(pitch)
    recovered_rotation = np.asarray(
        (
            (cos_yaw, sin_yaw, 0.0),
            (-sin_yaw * sin_pitch, cos_yaw * sin_pitch, cos_pitch),
            (sin_yaw * cos_pitch, -cos_yaw * cos_pitch, sin_pitch),
        ),
        dtype=np.float64,
    )
    return _matrix_quaternion(recovered_rotation @ _BASE_VIEW_ROTATION.T)


def _view_angles(
    quaternion: tuple[float, float, float, float]
) -> tuple[float, float]:
    """Return compatibility yaw/pitch labels for an arbitrary arcball view."""

    view_rotation = _quaternion_matrix(quaternion) @ _BASE_VIEW_ROTATION
    eye_direction = view_rotation[2]
    yaw = math.degrees(math.atan2(float(eye_direction[0]), -float(eye_direction[1])))
    pitch = math.degrees(math.asin(float(np.clip(eye_direction[2], -1.0, 1.0))))
    return math.fmod(yaw, 360.0), pitch


def _arcball_vector(
    x: float,
    y: float,
    mapping: tuple[int, int, int, int, int, int],
) -> np.ndarray:
    """Map a canvas point to a unit virtual sphere over the model viewport."""

    left, top, width, height, _render_width, _render_height = mapping
    radius = max(1.0, 0.5 * float(min(width, height)))
    value = np.asarray(
        (
            (float(x) - (float(left) + float(width) * 0.5)) / radius,
            ((float(top) + float(height) * 0.5) - float(y)) / radius,
            0.0,
        ),
        dtype=np.float64,
    )
    squared = float(value[0] * value[0] + value[1] * value[1])
    if squared <= 1.0:
        value[2] = math.sqrt(max(0.0, 1.0 - squared))
    else:
        value /= math.sqrt(squared)
    return value / max(float(np.linalg.norm(value)), 1e-12)


def _pan_camera(camera: Any, pan_x: float, pan_y: float) -> _PanCameraState:
    orientation = getattr(camera, "orientation", None)
    if orientation is not None:
        orientation = _normalize_quaternion(orientation)
        yaw, pitch = _view_angles(orientation)
    else:
        yaw = math.fmod(float(camera.yaw_degrees), 360.0)
        pitch = max(-84.0, min(84.0, float(camera.pitch_degrees)))
    return _PanCameraState(
        # Match the recovered renderer's sanitization so its returned camera
        # stays exactly equal to the request and can unlock the final picker.
        yaw_degrees=yaw,
        pitch_degrees=pitch,
        zoom=max(0.05, min(40.0, float(camera.zoom))),
        pan_x=float(pan_x),
        pan_y=float(pan_y),
        orientation=orientation,
    )


def _arcball_camera(camera: Any) -> _PanCameraState:
    """Return a normalized quaternion camera preserving the current view."""

    orientation = getattr(camera, "orientation", None)
    if orientation is None:
        orientation = _quaternion_from_yaw_pitch(
            float(camera.yaw_degrees), float(camera.pitch_degrees)
        )
    else:
        orientation = _normalize_quaternion(orientation)
    yaw, pitch = _view_angles(orientation)
    return _PanCameraState(
        yaw_degrees=yaw,
        pitch_degrees=pitch,
        zoom=max(0.05, min(40.0, float(camera.zoom))),
        pan_x=float(getattr(camera, "pan_x", 0.0)),
        pan_y=float(getattr(camera, "pan_y", 0.0)),
        orientation=orientation,
    )


def _arcball_camera_mvp(
    vertices: np.ndarray,
    size: tuple[int, int],
    camera: _PanCameraState,
    renderer_module: Any,
) -> tuple[np.ndarray, _PanCameraState, float]:
    """Build the fitted orthographic MVP for a roll-safe arcball camera."""

    values = np.asarray(vertices, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or not len(values):
        raise ValueError("Arcball projection requires an Nx3 vertex array.")
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        raise ValueError("Arcball projection requires a positive viewport size.")

    orientation = _normalize_quaternion(camera.orientation)
    numeric_values = (
        float(camera.yaw_degrees),
        float(camera.pitch_degrees),
        float(camera.zoom),
        float(camera.pan_x),
        float(camera.pan_y),
    )
    if not all(math.isfinite(value) for value in numeric_values):
        raise ValueError("Arcball camera values must be finite numbers.")
    if not 0.05 <= float(camera.zoom) <= 40.0:
        raise ValueError("Arcball camera zoom is outside the supported range.")
    # Interaction methods construct an already-normalized immutable state.
    # Return that exact object so face-ID picking can compare it byte-for-byte
    # with the request even if re-normalizing the quaternion changes a low bit.
    clean = camera
    minimum = values.min(axis=0)
    maximum = values.max(axis=0)
    center = (minimum + maximum) * 0.5
    extents = maximum - minimum
    diagonal = max(float(np.linalg.norm(extents)), 1e-6)
    distance = max(diagonal * 2.5, 1.0)

    view_rotation = _quaternion_matrix(orientation) @ _BASE_VIEW_ROTATION
    view = np.eye(4, dtype=np.float64)
    view[:3, :3] = view_rotation
    view[:3, 3] = -(view_rotation @ center)
    view[2, 3] -= distance

    corners = np.asarray(
        [
            (x, y, z)
            for x in (minimum[0], maximum[0])
            for y in (minimum[1], maximum[1])
            for z in (minimum[2], maximum[2])
        ],
        dtype=np.float64,
    )
    camera_space = (corners - center) @ view_rotation.T
    projected_width = max(float(np.ptp(camera_space[:, 0])), 1e-6)
    projected_height = max(float(np.ptp(camera_space[:, 1])), 1e-6)
    aspect = float(width) / float(height)
    half_height = max(
        projected_height * 0.55,
        projected_width * 0.55 / aspect,
        1e-5,
    )
    half_height /= clean.zoom
    orthographic = getattr(renderer_module, "_orthographic", None)
    if callable(orthographic):
        projection = orthographic(
            -half_height * aspect,
            half_height * aspect,
            -half_height,
            half_height,
            0.001,
            distance + diagonal * 3.0,
        )
    else:
        # Kept local so unit tests and recovered builds can install the patch
        # without depending on a private renderer helper being exported.
        left, right = -half_height * aspect, half_height * aspect
        bottom, top = -half_height, half_height
        near, far = 0.001, distance + diagonal * 3.0
        projection = np.eye(4, dtype=np.float64)
        projection[0, 0] = 2.0 / (right - left)
        projection[1, 1] = 2.0 / (top - bottom)
        projection[2, 2] = -2.0 / (far - near)
        projection[0, 3] = -(right + left) / (right - left)
        projection[1, 3] = -(top + bottom) / (top - bottom)
        projection[2, 3] = -(far + near) / (far - near)

    pixels_per_unit = float(height) / (2.0 * half_height)
    return projection @ view, clean, pixels_per_unit


def _install_pan_projection(paint_gui: Any, renderer_module: Any = None) -> None:
    """Teach the recovered renderer and adaptive overlay about screen pan."""

    if renderer_module is None:
        renderer_module = getattr(paint_gui, "renderer", None)
    if renderer_module is None or bool(
        getattr(renderer_module, "_rotation_hotfix_pan_projection", False)
    ):
        return
    original_orbit_camera_mvp = getattr(renderer_module, "_orbit_camera_mvp", None)
    if original_orbit_camera_mvp is None:
        return

    def _orbit_camera_mvp_with_pan(vertices, size, camera):
        if isinstance(camera, _PanCameraState) and camera.orientation is not None:
            mvp, clean_camera, pixels_per_unit = _arcball_camera_mvp(
                vertices, size, camera, renderer_module
            )
        else:
            mvp, clean_camera, pixels_per_unit = original_orbit_camera_mvp(
                vertices, size, camera
            )
        if not isinstance(camera, _PanCameraState):
            return mvp, clean_camera, pixels_per_unit

        pan_x = float(camera.pan_x)
        pan_y = float(camera.pan_y)
        if not math.isfinite(pan_x) or not math.isfinite(pan_y):
            raise ValueError("Camera pan values must be finite numbers.")

        # MVP uses column vectors.  A clip-space translation before the
        # recovered projection shifts colour and picker renders identically.
        translation = np.eye(4, dtype=np.asarray(mvp).dtype)
        translation[0, 3] = 2.0 * pan_x
        translation[1, 3] = -2.0 * pan_y
        moved_mvp = translation @ np.asarray(mvp)
        if camera.orientation is not None:
            # The arcball builder already validated this immutable state and
            # used its pan values.  Keep the exact instance so the settled
            # face-ID frame unlocks picking without a floating-point mismatch.
            moved_camera = camera
        else:
            moved_camera = _PanCameraState(
                yaw_degrees=float(clean_camera.yaw_degrees),
                pitch_degrees=float(clean_camera.pitch_degrees),
                zoom=float(clean_camera.zoom),
                pan_x=pan_x,
                pan_y=pan_y,
                orientation=None,
            )
        return moved_mvp, moved_camera, pixels_per_unit

    renderer_module._orbit_camera_mvp = _orbit_camera_mvp_with_pan
    renderer_module._rotation_hotfix_pan_projection = True


def _camera_equal(left: Any, right: Any) -> bool:
    try:
        return bool(left == right)
    except Exception:
        return left is right


def _rotation_is_active(editor: Any) -> bool:
    return bool(getattr(editor, "_rotation_hotfix_active", False))


def _restore_cached_active_part_outline(
    editor: Any,
    frame: Any,
    camera: Any,
    renderer_module: Any,
) -> Any:
    """Decorate a settled colour-only frame with the exact cached pick map.

    A same-camera post-edit render deliberately skips the GPU face-ID pass.
    The active-part outline is image-space decoration, though, and the
    renderer normally adds it only while producing IDs.  Reusing the existing
    exact map restores that decoration without slowing fast orbit frames or
    changing which pick map the editor accepts.
    """

    if (
        frame is None
        or renderer_module is None
        or _rotation_is_active(editor)
        or not _camera_equal(getattr(editor, "_hotfix_pick_camera", None), camera)
    ):
        return frame
    target = getattr(frame, "target", None)
    cached_ids = getattr(editor, "face_ids", None)
    backend = getattr(editor, "_renderer", None)
    active_part = getattr(backend, "_active_part_id", None)
    # The renderer owns the normalized face-to-part table.  In legacy and
    # single-part projects ``level.face_part_ids`` may intentionally be the
    # empty sentinel even though the renderer has expanded it to one entry per
    # face.  Using the raw level table made colour-only post-edit frames lose
    # their outline while the next exact pick render restored it.
    face_part_ids = getattr(backend, "_face_part_ids", None)
    if face_part_ids is None:
        level = getattr(editor, "level", None)
        face_part_ids = getattr(level, "face_part_ids", None)
    overlay = getattr(renderer_module, "overlay_active_part_outline", None)
    if (
        target is None
        or cached_ids is None
        or active_part is None
        or face_part_ids is None
        or not callable(overlay)
        or not hasattr(target, "size")
    ):
        return frame
    ids = np.asarray(cached_ids)
    width, height = target.size
    if ids.shape != (int(height), int(width)) or not np.issubdtype(
        ids.dtype, np.integer
    ):
        return frame
    try:
        outlined = overlay(
            target,
            ids,
            np.asarray(face_part_ids),
            int(active_part),
            color=getattr(backend, "_active_part_accent", (36, 224, 255)),
            thickness=int(
                getattr(backend, "_active_part_outline_thickness", 2)
            ),
        )
    except Exception:
        # Decoration must never make a valid colour render fail.  The next
        # settled ID frame remains the authoritative fallback.
        return frame
    if is_dataclass(frame):
        try:
            return replace(frame, target=outlined)
        except (TypeError, ValueError):
            pass
    try:
        frame.target = outlined
    except Exception:
        return frame
    return frame


def _begin_rotation(editor: Any) -> None:
    editor._rotation_hotfix_active = True
    # A final-ID job from a preceding wheel/release must not make picking live
    # in the middle of a new drag.
    editor._rotation_hotfix_force_final = False
    editor._render_dirty = True
    mark_decal_stale = getattr(editor, "_mark_decal_preview_stale", None)
    if callable(mark_decal_stale):
        mark_decal_stale("decal.view_wait", view_change=True)


def _finish_rotation(editor: Any) -> None:
    editor._rotation_hotfix_active = False
    editor._rotation_hotfix_force_final = True
    editor._render_dirty = True
    editor._schedule_render(immediate=True)


def _poll_delay(editor: Any) -> int:
    if (
        _rotation_is_active(editor)
        or bool(getattr(editor, "_rotation_hotfix_force_final", False))
        or getattr(editor, "_rotation_hotfix_inflight", None) is not None
    ):
        return ACTIVE_POLL_MS
    return IDLE_POLL_MS


def _schedule_next_poll(editor: Any) -> None:
    if getattr(editor, "_closing", False):
        return
    window = getattr(editor, "window", None)
    if window is None:
        return
    try:
        if window.winfo_exists():
            window.after(_poll_delay(editor), editor._poll_worker)
    except Exception:
        # The recovered editor treats a destroyed Tk window as the end of the
        # polling loop.  Keep the same close-time behaviour here.
        return


def _consume_rotation_render_done(editor: Any, payload: Any) -> None:
    """Present a colour frame, but only adopt an exact, settled ID frame.

    Slightly stale colour images are useful animation frames.  Face IDs are
    selection data, so accepting them for a different camera would paint the
    wrong triangle.  Existing IDs remain stored during an orbit, but
    ``_render_dirty`` and the existing picker-camera guard keep them unusable.
    """

    editor._rotation_hotfix_inflight = None
    rendered_camera, frame = payload if payload is not None else (None, None)

    if frame is None:
        if not getattr(editor, "_close_requested", False):
            editor._pending_render = True
        return

    frame_camera = getattr(frame, "camera", rendered_camera)
    exact_camera = _camera_equal(rendered_camera, editor.camera) and _camera_equal(
        frame_camera, editor.camera
    )
    active = _rotation_is_active(editor)

    target = getattr(frame, "target", None)
    if target is not None:
        editor.target_image = target
        editor._rotation_hotfix_display_camera = rendered_camera

    pixels_per_unit = getattr(frame, "pixels_per_unit", None)
    if pixels_per_unit is not None:
        editor._render_pixels_per_unit = pixels_per_unit

    incoming_ids = getattr(frame, "face_ids", None)
    accepted_new_ids = bool(not active and exact_camera and incoming_ids is not None)
    if accepted_new_ids:
        editor.face_ids = incoming_ids
        editor._hotfix_pick_camera = rendered_camera

    retained_ids_are_exact = bool(
        not active
        and exact_camera
        and incoming_ids is None
        and getattr(editor, "face_ids", None) is not None
        and _camera_equal(
            getattr(editor, "_hotfix_pick_camera", None), rendered_camera
        )
        and not bool(getattr(editor, "_rotation_hotfix_force_final", False))
    )
    pick_is_exact = accepted_new_ids or retained_ids_are_exact

    # Set this before drawing.  The existing draw hotfix only advances its
    # picker-camera marker when _render_dirty is false.
    editor._render_dirty = not pick_is_exact
    if pick_is_exact:
        editor._rotation_hotfix_force_final = False
    if accepted_new_ids:
        accept_decal_frame = getattr(editor, "_accept_decal_exact_frame", None)
        if callable(accept_decal_frame):
            accept_decal_frame(incoming_ids, rendered_camera)

    if target is not None:
        editor._draw_canvas()

    # Coalesce all intervening mouse events to the latest editor.camera.  A
    # release also requires one exact frame carrying IDs, even when the colour
    # frame that just completed already used the final camera.
    if not exact_camera or (
        bool(getattr(editor, "_rotation_hotfix_force_final", False))
        and not accepted_new_ids
    ):
        editor._pending_render = True


class _PrefetchedQueue:
    """Let the original poller consume an item already removed for inspection."""

    def __init__(self, underlying: Any, first: Any):
        self._underlying = underlying
        self._first = first

    def get_nowait(self):
        if self._first is not None:
            item = self._first
            self._first = None
            return item
        return self._underlying.get_nowait()

    def __getattr__(self, name: str):
        return getattr(self._underlying, name)


def _call_original_poller(
    editor: Any, original_poller: Any, prefetched_item: Any
) -> None:
    """Delegate edit/error/close messages without copying fragile close logic."""

    real_queue = editor._work_queue
    editor._work_queue = _PrefetchedQueue(real_queue, prefetched_item)

    # The original poller always waits 30 ms after it finishes.  Temporarily
    # adapt only that self-rescheduling call while an orbit/final render is
    # active.  All other Tk ``after`` calls retain their requested delay.
    window = editor.window
    original_after = window.after
    window_dict = getattr(window, "__dict__", {})
    had_instance_after = "after" in window_dict
    previous_instance_after = window_dict.get("after")

    def adaptive_after(delay, callback, *args):
        if (
            int(delay) == IDLE_POLL_MS
            and getattr(callback, "__self__", None) is editor
            and getattr(callback, "__name__", "") == "_poll_worker_rotation"
        ):
            delay = _poll_delay(editor)
        return original_after(delay, callback, *args)

    try:
        window.after = adaptive_after
        original_poller(editor)
    finally:
        editor._work_queue = real_queue
        if had_instance_after:
            window.after = previous_instance_after
        else:
            try:
                del window.after
            except AttributeError:
                pass


def apply_rotation_hotfix(paint_gui: Any, renderer_module: Any = None):
    """Patch ``paint_gui.PaintEditorWindow`` and return the patched class.

    The operation is idempotent for a class.  It intentionally patches only
    orbit scheduling/presentation and leaves edits, undo/redo, errors and close
    jobs with the recovered implementation.
    """

    editor_class = paint_gui.PaintEditorWindow
    if bool(getattr(editor_class, "_rotation_hotfix_applied", False)):
        return editor_class

    _install_pan_projection(paint_gui, renderer_module)

    original_editor_init = editor_class.__init__
    original_poll_worker = editor_class._poll_worker
    original_left_press = editor_class._on_left_press
    original_right_press = editor_class._on_right_press
    original_left_release = editor_class._on_left_release
    original_right_release = editor_class._on_right_release
    original_orbit_to = getattr(editor_class, "_orbit_to", None)
    original_mousewheel = getattr(editor_class, "_on_mousewheel", None)

    def _bind_middle_pan(self) -> None:
        canvas = getattr(self, "canvas", None)
        if canvas is None or bool(
            getattr(self, "_rotation_hotfix_pan_bindings", False)
        ):
            return
        canvas.bind("<ButtonPress-2>", self._on_middle_press, add="+")
        canvas.bind("<B2-Motion>", self._on_middle_motion, add="+")
        canvas.bind("<ButtonRelease-2>", self._on_middle_release, add="+")
        # Keep release reliable when the pointer reaches another child widget.
        window = getattr(self, "window", None)
        if window is not None and hasattr(window, "bind"):
            window.bind("<ButtonRelease-2>", self._on_middle_release, add="+")
        self._rotation_hotfix_pan_bindings = True

        # Update the one-line help without rebuilding the editor.  The ribbon
        # UI exposes the label directly; retain the tree walk for older builds.
        hint_text = (
            "左: 塗る／元画像から色選択　右ドラッグ: 回転　"
            "ホイールドラッグ: 移動　ホイール: ズーム　"
            "Alt+左: 3D色を取得"
        )
        translator = getattr(self, "i18n", None)
        translate = getattr(translator, "text", None)
        if callable(translate):
            try:
                translated = str(translate("paint.controls_hint"))
                if translated and translated != "paint.controls_hint":
                    hint_text = translated
            except Exception:
                pass
        # Current builds publish both the compact Home hint and the detached
        # Controls tool-window hint.  Keep them in sync without walking the
        # widget tree; the traversal below is only for recovered/older builds
        # that did not expose either label.
        configured_hint = False
        for attribute in ("controls_hint_label", "help_controls_hint_label"):
            controls_hint_label = getattr(self, attribute, None)
            if controls_hint_label is None:
                continue
            try:
                controls_hint_label.configure(text=hint_text)
                configured_hint = True
            except Exception:
                pass
        if configured_hint:
            return
        if window is None or not hasattr(window, "winfo_children"):
            return
        pending = list(window.winfo_children())
        while pending:
            widget = pending.pop()
            try:
                pending.extend(widget.winfo_children())
            except Exception:
                pass
            try:
                label = str(widget.cget("text"))
                if label.startswith("左: 塗る／元画像から色選択"):
                    widget.configure(text=hint_text)
                    break
            except Exception:
                pass

    @functools.wraps(original_editor_init)
    def _editor_init_rotation(self, *args, **kwargs) -> None:
        original_editor_init(self, *args, **kwargs)
        _bind_middle_pan(self)

    def _schedule_render_rotation(self, *, immediate: bool = False) -> None:
        if getattr(self, "_close_requested", False):
            return
        self._render_dirty = True
        mark_decal_stale = getattr(self, "_mark_decal_preview_stale", None)
        if callable(mark_decal_stale):
            mark_decal_stale("decal.view_wait", view_change=True)

        # A running worker already represents the single in-flight slot.  A
        # boolean pending flag is the one latest-only slot; camera itself holds
        # the most recent requested state.
        if getattr(self, "_job_running", False):
            self._pending_render = True
            return

        existing = getattr(self, "_render_after", None)
        if existing is not None:
            if not immediate:
                return
            try:
                self.window.after_cancel(existing)
            except Exception:
                pass

        delay = 1 if immediate else THROTTLE_MS
        self._render_after = self.window.after(delay, self._request_render)

    def _request_render_rotation(self) -> None:
        self._render_after = None
        if getattr(self, "_close_requested", False) or getattr(
            self, "_closing", False
        ):
            return
        if getattr(self, "_job_running", False):
            self._pending_render = True
            return

        camera = self.camera
        active = _rotation_is_active(self)
        need_face_ids = bool(
            not active
            and (
                bool(getattr(self, "_rotation_hotfix_force_final", False))
                or getattr(self, "face_ids", None) is None
                or not _camera_equal(
                    getattr(self, "_hotfix_pick_camera", None), camera
                )
            )
        )
        self._rotation_hotfix_inflight = (camera, need_face_ids)

        def work():
            if self._renderer is None or self._display_colors is None:
                return None
            set_focus = getattr(
                self._renderer,
                "set_palette_usage_focus",
                None,
            )
            if callable(set_focus):
                focus_enabled = bool(
                    getattr(self, "_palette_usage_focus_enabled", False)
                )
                set_focus(
                    (
                        int(getattr(self, "_palette_usage_focus_state", 0))
                        if focus_enabled
                        else None
                    ),
                    part_id=int(getattr(self, "active_part_id", 0)),
                )
            diagnostic_colors = getattr(
                self,
                "_diagnostic_render_colors",
                None,
            )
            render_colors = (
                diagnostic_colors()
                if callable(diagnostic_colors)
                else self._display_colors
            )
            frame = self._renderer.render(
                render_colors,
                camera=camera,
                render_source=False,
                render_target=True,
                render_face_ids=need_face_ids,
            )
            if not active and not need_face_ids:
                frame = _restore_cached_active_part_outline(
                    self, frame, camera, renderer_module
                )
            return camera, frame

        self._submit("render", work)

    def _poll_worker_rotation(self) -> None:
        if getattr(self, "_closing", False):
            return

        while True:
            try:
                item = self._work_queue.get_nowait()
            except queue.Empty:
                _schedule_next_poll(self)
                return

            kind, payload = item
            if kind != "render_done":
                if kind == "job_error":
                    try:
                        failed_kind = payload[0]
                    except Exception:
                        failed_kind = None
                    if failed_kind == "render":
                        self._rotation_hotfix_inflight = None
                elif kind == "close_done":
                    self._rotation_hotfix_inflight = None
                _call_original_poller(self, original_poll_worker, item)
                return

            self._job_running = False
            _consume_rotation_render_done(self, payload)
            self._start_next_pending()

    def _on_left_press_rotation(self, event) -> None:
        original_left_press(self, event)
        if getattr(self, "_drag_mode", None) == "orbit":
            _begin_rotation(self)

    def _on_right_press_rotation(self, event) -> None:
        original_right_press(self, event)
        if getattr(self, "_drag_mode", None) == "orbit":
            _begin_rotation(self)

    def _on_left_release_rotation(self, event) -> None:
        was_orbit = getattr(self, "_drag_mode", None) == "orbit"
        original_left_release(self, event)
        if was_orbit:
            _finish_rotation(self)

    def _on_right_release_rotation(self, event) -> None:
        was_orbit = getattr(self, "_drag_mode", None) == "orbit"
        original_right_release(self, event)
        if was_orbit:
            _finish_rotation(self)

    def _on_middle_press_rotation(self, event) -> None:
        if getattr(self, "_close_requested", False) or getattr(
            self, "_drag_mode", None
        ) is not None:
            return
        mapping = getattr(self, "target_mapping", None)
        if mapping is None:
            return
        try:
            inside = bool(self._point_inside(event, mapping))
        except Exception:
            x, y, width, height, _ow, _oh = mapping
            inside = bool(
                x <= int(event.x) < x + width
                and y <= int(event.y) < y + height
            )
        if not inside:
            return

        self._drag_mode = "pan"
        self._drag_last = (int(event.x), int(event.y))
        _begin_rotation(self)
        try:
            self.canvas.configure(cursor="fleur")
        except Exception:
            pass

    def _on_middle_motion_rotation(self, event) -> None:
        if getattr(self, "_drag_mode", None) != "pan":
            return
        previous = getattr(self, "_drag_last", None)
        mapping = getattr(self, "target_mapping", None)
        if previous is None or mapping is None:
            return
        x = int(event.x)
        y = int(event.y)
        dx = x - int(previous[0])
        dy = y - int(previous[1])
        self._drag_last = (x, y)
        if dx == 0 and dy == 0:
            return

        display_width = max(1.0, float(mapping[2]))
        display_height = max(1.0, float(mapping[3]))
        camera = self.camera
        pan_x = float(getattr(camera, "pan_x", 0.0)) + dx / display_width
        pan_y = float(getattr(camera, "pan_y", 0.0)) + dy / display_height
        self.camera = _pan_camera(camera, pan_x, pan_y)
        self._schedule_render()

    def _on_middle_release_rotation(self, _event) -> None:
        if getattr(self, "_drag_mode", None) != "pan":
            return
        self._drag_mode = None
        self._drag_last = None
        try:
            self.canvas.configure(cursor="arrow")
        except Exception:
            pass
        _finish_rotation(self)

    def _orbit_to_with_pan(self, x: int, y: int) -> None:
        previous = getattr(self, "_drag_last", None)
        mapping = getattr(self, "target_mapping", None)
        if previous is None or mapping is None:
            if original_orbit_to is not None:
                original_orbit_to(self, x, y)
            return

        previous_x, previous_y = int(previous[0]), int(previous[1])
        current_x, current_y = int(x), int(y)
        self._drag_last = (current_x, current_y)
        if current_x == previous_x and current_y == previous_y:
            return

        camera = _arcball_camera(self.camera)
        previous_vector = _arcball_vector(previous_x, previous_y, mapping)
        current_vector = _arcball_vector(current_x, current_y, mapping)

        # The default direction matches the recovered editor.  Users who think
        # of dragging the object rather than moving the camera can persist the
        # exact inverse arcball delta from the manual editor ribbon.
        orbit_inverted_var = getattr(self, "orbit_inverted_var", None)
        try:
            orbit_inverted = bool(orbit_inverted_var.get())
        except Exception:
            orbit_inverted = False
        delta = (
            _quaternion_between(previous_vector, current_vector)
            if orbit_inverted
            else _quaternion_between(current_vector, previous_vector)
        )
        orientation = _quaternion_multiply(delta, camera.orientation)
        yaw, pitch = _view_angles(orientation)
        self.camera = _PanCameraState(
            yaw_degrees=yaw,
            pitch_degrees=pitch,
            zoom=camera.zoom,
            pan_x=camera.pan_x,
            pan_y=camera.pan_y,
            orientation=orientation,
        )
        self._schedule_render()

    def _on_mousewheel_with_pan(self, event) -> None:
        camera = self.camera
        if not isinstance(camera, _PanCameraState) or original_mousewheel is None:
            if original_mousewheel is not None:
                original_mousewheel(self, event)
            return
        if getattr(self, "_close_requested", False):
            return
        factor = float(getattr(paint_gui, "MANUAL_ZOOM_STEP", 1.22))
        if int(event.delta) <= 0:
            factor = 1.0 / factor
        set_zoom = getattr(self, "_set_zoom", None)
        if callable(set_zoom):
            set_zoom(camera.zoom * factor)
            return
        minimum_zoom = float(getattr(paint_gui, "MANUAL_ZOOM_MIN", 0.35))
        maximum_zoom = float(getattr(paint_gui, "MANUAL_ZOOM_MAX", 24.0))
        self.camera = _PanCameraState(
            yaw_degrees=camera.yaw_degrees,
            pitch_degrees=camera.pitch_degrees,
            zoom=max(minimum_zoom, min(maximum_zoom, camera.zoom * factor)),
            pan_x=camera.pan_x,
            pan_y=camera.pan_y,
            orientation=camera.orientation,
        )
        update_status = getattr(self, "_update_zoom_status", None)
        if callable(update_status):
            update_status()
        self._schedule_render()

    editor_class.__init__ = _editor_init_rotation
    editor_class._schedule_render = _schedule_render_rotation
    editor_class._request_render = _request_render_rotation
    editor_class._poll_worker = _poll_worker_rotation
    editor_class._on_left_press = _on_left_press_rotation
    editor_class._on_right_press = _on_right_press_rotation
    editor_class._on_left_release = _on_left_release_rotation
    editor_class._on_right_release = _on_right_release_rotation
    editor_class._on_middle_press = _on_middle_press_rotation
    editor_class._on_middle_motion = _on_middle_motion_rotation
    editor_class._on_middle_release = _on_middle_release_rotation
    if original_orbit_to is not None:
        editor_class._orbit_to = _orbit_to_with_pan
    if original_mousewheel is not None:
        editor_class._on_mousewheel = _on_mousewheel_with_pan
    editor_class._rotation_hotfix_applied = True
    return editor_class


__all__ = [
    "ACTIVE_POLL_MS",
    "IDLE_POLL_MS",
    "THROTTLE_MS",
    "_restore_cached_active_part_outline",
    "apply_rotation_hotfix",
]
