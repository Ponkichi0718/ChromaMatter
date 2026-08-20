"""Connect adaptive Orca paint trees to the recovered paint editor.

The recovered application owns one colour per source triangle.  This adapter
keeps that fast base mesh for rendering and adds a sparse midpoint subdivision
tree only where a circular screen-space brush crosses a colour boundary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import functools
import math
import time
import tkinter as tk
from tkinter import ttk
import weakref
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

import auto_shading
import adaptive_gpu_overlay
import smooth_paint
from spectrum_mapper import parts as part_palette_module
from spectrum_mapper.paint import exact_face_paint_identity
from spectrum_mapper.pen_pressure import (
    PenPressureBridge,
    pressure_or_taper_scales,
    pressure_radius_scale,
)
from spectrum_mapper.paint_tools import (
    accumulated_airbrush_deposit,
    airbrush_hold_dab_count,
    airbrush_radius_scale,
    airbrush_state_layers,
    soft_falloff,
)


_LEVEL_CONTEXTS: dict[int, tuple[weakref.ReferenceType[Any], weakref.ReferenceType[Any]]] = {}
_GPU_OVERLAY_INFO_KEY = "tripo_spectrum_adaptive_gpu_revision"
_VISIBILITY_FACE_MODES_INFO_KEY = "tripo_spectrum_part_visibility_face_modes"
_STROKE_DEBOUNCE_MS = 300
# Keep held-spray feedback within two 60 Hz frames.  The callback updates only
# the live head now; it never rebuilds the accumulated path.
_AIRBRUSH_PREVIEW_REFRESH_MS = 32
_AIRBRUSH_FEEDBACK_RADII = np.linspace(
    0.96, 0.04, 16, dtype=np.float64
)
_AIRBRUSH_FEEDBACK_FALLOFF = soft_falloff(
    _AIRBRUSH_FEEDBACK_RADII, 1.0
)
_AUTO_SHADING_QUALITY_LABELS = {
    "高速": "fast",
    "標準": "standard",
    "高品質": "high",
    "Fast": "fast",
    "Standard": "standard",
    "High Quality": "high",
}
_AUTO_SHADING_QUALITY_PRESETS = {
    "fast": {
        "min_edge_mm": 0.60,
        "max_depth": 1,
        "max_adaptive_faces": 20_000,
        "max_total_leaves": 80_000,
        "min_variation_delta_e": 5.0,
        "batch_faces": 8192,
    },
    "standard": {
        "min_edge_mm": 0.30,
        "max_depth": 2,
        "max_adaptive_faces": 75_000,
        "max_total_leaves": 600_000,
        "min_variation_delta_e": 2.0,
        "batch_faces": 4096,
    },
    "high": {
        "min_edge_mm": 0.18,
        "max_depth": 3,
        "max_adaptive_faces": 100_000,
        "max_total_leaves": 800_000,
        "min_variation_delta_e": 1.0,
        "batch_faces": 2048,
    },
}


@dataclass(frozen=True, slots=True)
class _SmoothStrokeCapture:
    """Small immutable input snapshot; the large face-ID array is shared read-only."""

    camera: Any
    mapping: tuple[Any, ...]
    face_ids: np.ndarray
    pixels_per_unit: float
    radius_mm: float
    height_mm: float
    protect_edges: bool
    edge_angle_degrees: float
    selected_state: int
    shape: str
    erase: bool
    feedback_color: str
    feedback_radius_pixels: float
    tool: str = "brush"
    airbrush_strength: float = 1.0
    palette_rgb: tuple[tuple[float, float, float], ...] = ()
    enabled_states: tuple[bool, ...] = ()


@dataclass(frozen=True, slots=True)
class _SmoothStrokeRequest:
    points: tuple[tuple[float, float], ...]
    capture: _SmoothStrokeCapture
    feedback_token: int | None
    radius_scales: tuple[float, ...] | None = None
    width_source: str = "fixed"
    pressure: float = 1.0
    dab_count: int = 1


@dataclass(frozen=True, slots=True)
class _SmoothStrokeResult:
    feedback_token: int | None
    revision: int
    changed_roots: int
    label: str
    error: str | None = None


class _StrokeBatch:
    """UI-owned FIFO handed to the worker only after a quiet-period debounce."""

    def __init__(self, serial: int):
        self.serial = int(serial)
        self._requests: deque[_SmoothStrokeRequest] = deque()
        self._accepting = True

    def append(self, request: _SmoothStrokeRequest) -> bool:
        if not self._accepting:
            return False
        self._requests.append(request)
        return True

    def seal(self) -> None:
        self._accepting = False

    def drain(self):
        """Yield every accepted request in FIFO order, then close the batch."""

        self._accepting = False
        while self._requests:
            yield self._requests.popleft()


def _drain_stroke_batch(
    batch: _StrokeBatch,
    processor: Any,
    current_revision: Any,
) -> list[_SmoothStrokeResult]:
    """Run a batch without letting one malformed stroke strand later input."""

    results: list[_SmoothStrokeResult] = []
    for request in batch.drain():
        try:
            results.append(processor(request))
        except Exception as exc:
            results.append(
                _SmoothStrokeResult(
                    request.feedback_token,
                    int(current_revision()),
                    0,
                    "",
                    f"{type(exc).__name__}: {exc}",
                )
            )
    return results


def _gpu_overlay_revision(image: Image.Image | None) -> int | None:
    if image is None:
        return None
    raw = getattr(image, "info", {}).get(_GPU_OVERLAY_INFO_KEY)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _ensure_store(prepared: Any) -> dict[int, smooth_paint.PaintNode]:
    store = getattr(prepared, "_hotfix_subtriangle_paint", None)
    if not isinstance(store, dict):
        store = {}
        prepared._hotfix_subtriangle_paint = store
    if not hasattr(prepared, "_hotfix_tree_revision"):
        prepared._hotfix_tree_revision = 0
    return store


def _register_level(prepared: Any) -> dict[int, smooth_paint.PaintNode]:
    store = _ensure_store(prepared)
    level = prepared.final
    _LEVEL_CONTEXTS[id(level)] = (weakref.ref(level), weakref.ref(prepared))
    return store


def carry_adaptive_trees_if_face_identity_exact(
    before: Any,
    after: Any,
) -> tuple[bool, int]:
    """Clone adaptive roots onto *after* only after an exact face proof.

    The helper is intentionally all-or-nothing.  It is used by the explicit
    single-GLB texture-seam repair, where vertex indices can change without any
    ordered triangle or part assignment changing.  General remesh/QEM paths do
    not call it and continue to flatten/remap paint through their established
    workflow.
    """

    try:
        if not exact_face_paint_identity(before.final, after.final):
            return False, 0
    except (AttributeError, TypeError, ValueError):
        return False, 0

    source = getattr(before, "_hotfix_subtriangle_paint", None)
    if source is None:
        return True, 0
    if not isinstance(source, dict):
        return False, 0
    if not source:
        return True, 0

    face_count = len(after.final.faces)
    cloned: dict[int, smooth_paint.PaintNode] = {}
    try:
        for raw_face, node in source.items():
            if isinstance(raw_face, bool) or not isinstance(raw_face, (int, np.integer)):
                return False, 0
            face = int(raw_face)
            if face < 0 or face >= face_count or not isinstance(
                node, smooth_paint.PaintNode
            ):
                return False, 0
            cloned[face] = node.clone()
    except (AttributeError, TypeError, ValueError):
        return False, 0

    # Install only after every key and node has been validated and cloned, so a
    # malformed store can never leave a partially carried result behind.
    after._hotfix_subtriangle_paint = cloned
    after._hotfix_tree_revision = int(
        getattr(before, "_hotfix_tree_revision", 0)
    )
    return True, len(cloned)


def lookup_tree_context(level: Any) -> tuple[dict[int, smooth_paint.PaintNode], int] | None:
    cached = _LEVEL_CONTEXTS.get(id(level))
    if cached is None:
        return None
    current_level = cached[0]()
    prepared = cached[1]()
    if current_level is not level or prepared is None:
        _LEVEL_CONTEXTS.pop(id(level), None)
        return None
    return _ensure_store(prepared), int(getattr(prepared, "_hotfix_tree_revision", 0))


def _bump_revision(owner: Any) -> None:
    if owner is not None:
        owner._hotfix_tree_revision = int(
            getattr(owner, "_hotfix_tree_revision", 0)
        ) + 1


def _clone_store_subset(
    store: dict[int, smooth_paint.PaintNode], keys: set[int]
) -> dict[int, smooth_paint.PaintNode]:
    return {key: store[key].clone() for key in keys if key in store}


def _restore_tree_snapshot(
    store: dict[int, smooth_paint.PaintNode],
    keys: set[int],
    snapshot: dict[int, smooth_paint.PaintNode],
) -> None:
    for key in keys:
        store.pop(int(key), None)
    for key, node in snapshot.items():
        store[int(key)] = node.clone()


def _attach_tree_history(
    command: Any,
    keys: set[int],
    before: dict[int, smooth_paint.PaintNode],
    after: dict[int, smooth_paint.PaintNode],
) -> None:
    object.__setattr__(command, "_hotfix_tree_keys", frozenset(int(key) for key in keys))
    object.__setattr__(
        command,
        "_hotfix_tree_before",
        {int(key): node.clone() for key, node in before.items()},
    )
    object.__setattr__(
        command,
        "_hotfix_tree_after",
        {int(key): node.clone() for key, node in after.items()},
    )


def _auto_shading_face_mask(
    session: Any,
    paint_trees: dict[int, smooth_paint.PaintNode],
    *,
    boundary_only: bool,
) -> np.ndarray:
    """Return unedited root faces that automatic shading may safely own.

    Manual root overrides and every existing adaptive tree are deliberately
    excluded.  In boundary-only mode, the remaining scope is limited to the
    two faces directly touching an edge whose current root states differ.
    """

    states = np.asarray(session.effective_indices(), dtype=np.int16)
    overrides = np.asarray(session.overrides, dtype=np.int8)
    if overrides.shape != states.shape:
        raise RuntimeError("色修正データと面数が一致しません")
    allowed = overrides < 0
    if paint_trees:
        protected = np.fromiter(
            (
                int(face)
                for face in paint_trees
                if 0 <= int(face) < len(states)
            ),
            dtype=np.intp,
        )
        if len(protected):
            allowed[protected] = False
    if not boundary_only or len(states) == 0:
        return allowed

    neighbors = np.asarray(session.neighbors)
    if neighbors.shape != (len(states), 3):
        raise RuntimeError("面の隣接情報を取得できません")
    valid = (neighbors >= 0) & (neighbors < len(states))
    safe_neighbors = np.where(valid, neighbors, 0).astype(np.intp, copy=False)
    touches_different_root = np.any(
        valid & (states[safe_neighbors] != states[:, None]), axis=1
    )
    return allowed & touches_different_root


def _auto_shading_options(
    quality: str,
    *,
    height_mm: float,
    enabled_states: Any,
    dither_strength: float,
) -> auto_shading.AutoShadingOptions:
    preset = _AUTO_SHADING_QUALITY_PRESETS.get(
        str(quality), _AUTO_SHADING_QUALITY_PRESETS["standard"]
    )
    strength = float(np.clip(float(dither_strength), 0.0, 1.0))
    return auto_shading.AutoShadingOptions(
        units_to_mm=max(float(height_mm), 1.0e-9),
        min_edge_mm=float(preset["min_edge_mm"]),
        max_depth=int(preset["max_depth"]),
        max_adaptive_faces=int(preset["max_adaptive_faces"]),
        max_total_leaves=int(preset["max_total_leaves"]),
        min_variation_delta_e=float(preset["min_variation_delta_e"]),
        dither=strength > 0.0,
        dither_strength=strength,
        dither_seed=0,
        batch_faces=int(preset["batch_faces"]),
        enabled_states=tuple(bool(value) for value in enabled_states),
    )


def _project_points(
    vertices: np.ndarray,
    mvp: np.ndarray,
    size: tuple[int, int],
) -> np.ndarray:
    values = np.asarray(vertices, dtype=np.float64)
    homogeneous = np.concatenate(
        (values[:, :3], np.ones((len(values), 1), dtype=np.float64)), axis=1
    )
    clip = homogeneous @ np.asarray(mvp, dtype=np.float64).T
    divisor = clip[:, 3]
    safe = np.where(np.abs(divisor) > 1.0e-12, divisor, np.nan)
    ndc = clip[:, :2] / safe[:, None]
    width, height = int(size[0]), int(size[1])
    output = np.empty_like(ndc)
    output[:, 0] = (ndc[:, 0] * 0.5 + 0.5) * width
    output[:, 1] = (0.5 - ndc[:, 1] * 0.5) * height
    return output


def _palette_rgb(palette: Any, mixer_module: Any) -> np.ndarray:
    _hex_values, rgb = mixer_module.build_palette_rgb(
        list(palette.physical_hex),
        list(palette.mix_hex_overrides),
        list(palette.mix_ratios_b),
        list(palette.secondary_mix_ratios_b),
    )
    values = np.asarray(rgb, dtype=np.float64)
    if float(values.max(initial=0.0)) > 1.5:
        values = values / 255.0
    return np.clip(values, 0.0, 1.0)


def _configure_gpu_palette_routing(settings: Any, level: Any) -> None:
    """Attach immutable per-part GPU tables only when their colours differ."""

    layout = part_palette_module.validate_part_layout(level)
    palettes = part_palette_module.resolve_part_palette_settings(settings, layout)
    tables = np.ascontiguousarray(
        part_palette_module.build_part_palette_rgb_tables(settings, layout),
        dtype=np.float32,
    )
    level._hotfix_palette = palettes[0]

    multipart = len(tables) > 1 and any(
        not np.array_equal(tables[0], table) for table in tables[1:]
    )
    if not multipart:
        level._hotfix_part_palette_rgb_tables = None
        level._hotfix_face_part_ids = None
        level._hotfix_part_palette_tokens = None
        return

    face_part_ids = np.array(layout.face_part_ids, dtype=np.int64, copy=True)
    tables.setflags(write=False)
    face_part_ids.setflags(write=False)
    level._hotfix_part_palette_rgb_tables = tables
    level._hotfix_face_part_ids = face_part_ids
    level._hotfix_part_palette_tokens = tuple(
        np.ascontiguousarray(table).tobytes() for table in tables
    )


def compose_target_image(
    image: Image.Image,
    level: Any,
    paint_trees: dict[int, smooth_paint.PaintNode],
    *,
    camera: Any,
    face_ids: np.ndarray | None,
    palette: Any,
    part_palette_rgb_tables: np.ndarray | None = None,
    face_part_ids: np.ndarray | None = None,
    focus_state: int | None = None,
    focus_part_id: int | None = None,
    renderer_module: Any,
    mixer_module: Any,
) -> Image.Image:
    """Overlay adaptive leaves on a shaded base render.

    The exact face-ID map clips every subtriangle to the visible source face,
    so painting never leaks through to a hidden surface.
    """

    # The persistent GPU renderer marks images that already contain this exact
    # adaptive pass.  Never paint a second CPU overlay over those pixels.
    if _gpu_overlay_revision(image) is not None:
        return image
    if not paint_trees or face_ids is None:
        return image
    width, height = image.size
    ids = np.asarray(face_ids)
    if ids.shape != (height, width):
        return image

    mvp, _state, _pixels_per_unit = renderer_module._orbit_camera_mvp(
        level.vertices_unit, (width, height), camera
    )
    palette_rgb = _palette_rgb(palette, mixer_module)
    part_tables = (
        None
        if part_palette_rgb_tables is None
        else np.asarray(part_palette_rgb_tables, dtype=np.float64)
    )
    part_ids = (
        None
        if face_part_ids is None
        else np.asarray(face_part_ids, dtype=np.int64)
    )
    if (
        part_tables is not None
        and (
            part_tables.ndim != 3
            or part_tables.shape[1:] != palette_rgb.shape
            or part_ids is None
            or part_ids.shape != (len(level.faces),)
        )
    ):
        part_tables = None
        part_ids = None
    if focus_state is not None:
        selected_state = int(focus_state)
        if part_tables is None:
            palette_rgb = adaptive_gpu_overlay._palette_usage_focus_table(
                palette_rgb,
                selected_state,
                highlight=True,
            )
        else:
            requested_part = (
                None if focus_part_id is None else int(focus_part_id)
            )
            part_tables = np.stack(
                tuple(
                    adaptive_gpu_overlay._palette_usage_focus_table(
                        table,
                        selected_state,
                        highlight=(
                            requested_part is None
                            or part_index == requested_part
                        ),
                    )
                    for part_index, table in enumerate(part_tables)
                ),
                axis=0,
            )
    source = np.asarray(image.convert("RGB"), dtype=np.uint8)
    output = source.copy()
    faces = np.asarray(level.faces, dtype=np.int64)
    vertices = np.asarray(level.vertices_unit, dtype=np.float64)
    raw_visibility = image.info.get(_VISIBILITY_FACE_MODES_INFO_KEY)
    visibility = (
        np.asarray(raw_visibility, dtype=np.uint8)
        if raw_visibility is not None
        else None
    )
    if visibility is not None and visibility.shape != (len(faces),):
        visibility = None
    luma_weights = np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float64)

    for raw_face, node in tuple(paint_trees.items()):
        face = int(raw_face)
        if face < 0 or face >= len(faces):
            continue
        # Adaptive detail is composited only onto ordinary opaque roots.
        # Hidden roots must stay absent, and applying an opaque CPU overlay to
        # a transparent root would contradict the renderer's alpha pass.
        if visibility is not None and int(visibility[face]) != 0:
            continue
        face_palette_rgb = (
            part_tables[int(part_ids[face])]
            if part_tables is not None and part_ids is not None
            else palette_rgb
        )
        root_geometry = vertices[faces[face]]
        root_screen = _project_points(root_geometry, mvp, (width, height))
        if not bool(np.all(np.isfinite(root_screen))):
            continue
        x0 = max(0, int(math.floor(float(root_screen[:, 0].min()))) - 1)
        y0 = max(0, int(math.floor(float(root_screen[:, 1].min()))) - 1)
        x1 = min(width, int(math.ceil(float(root_screen[:, 0].max()))) + 2)
        y1 = min(height, int(math.ceil(float(root_screen[:, 1].max()))) + 2)
        if x1 <= x0 or y1 <= y0:
            continue
        visible = ids[y0:y1, x0:x1] == face
        if not bool(np.any(visible)):
            continue

        state_image = Image.new("I", (x1 - x0, y1 - y0), 0)
        drawing = ImageDraw.Draw(state_image)
        # The viewer uses an orthographic camera, so midpoint subdivision in
        # screen space is exactly the projection of midpoint subdivision in
        # model space.  Project the root once instead of thousands of leaves.
        for leaf in smooth_paint.iter_leaf_triangles(node, root_screen):
            projected = leaf.vertices
            polygon = [
                (float(point[0] - x0), float(point[1] - y0)) for point in projected
            ]
            drawing.polygon(polygon, fill=int(leaf.state) + 1)
        state_map = np.asarray(state_image, dtype=np.int16) - 1
        valid = visible & (state_map >= 0) & (state_map < smooth_paint.STATE_COUNT)
        if not bool(np.any(valid)):
            continue

        dominant = int(node.dominant_state())
        base_luma = max(float(face_palette_rgb[dominant] @ luma_weights), 0.018)
        local_source = source[y0:y1, x0:x1].astype(np.float64) / 255.0
        local_luma = local_source @ luma_weights
        shade = np.clip(local_luma / base_luma, 0.22, 1.35)
        requested = np.clip(
            face_palette_rgb[
                np.clip(state_map, 0, smooth_paint.STATE_COUNT - 1)
            ]
            * shade[:, :, None],
            0.0,
            1.0,
        )
        local_output = output[y0:y1, x0:x1]
        local_output[valid] = np.rint(requested[valid] * 255.0).astype(np.uint8)

    composite = Image.fromarray(output, mode="RGB")
    composite.info.update(image.info)
    return composite


def _overlay_cache_matches(
    cached: Any,
    image: Image.Image,
    face_ids: np.ndarray,
    camera: Any,
    revision: int,
) -> bool:
    """Return whether a cached adaptive composite belongs to this exact frame.

    Keeping the source image and ID array themselves in the cache is
    intentional.  The previous implementation cached only ``id(...)`` values;
    once a rendered PIL image was released, CPython could reuse that integer
    identity for a later frame and incorrectly resurrect an older composite.
    """

    return bool(
        isinstance(cached, tuple)
        and len(cached) == 5
        and cached[0] is image
        and cached[1] is face_ids
        and cached[2] == camera
        and int(cached[3]) == int(revision)
    )


def _mark_feedback_committed(
    pending: list[dict[str, Any]],
    token: int,
    *,
    base_image: Image.Image | None,
    revision: int,
) -> bool:
    """Mark a visible stroke as committed but not yet accurately rendered."""

    for entry in pending:
        if int(entry.get("token", -1)) != int(token):
            continue
        entry["committed"] = True
        entry["base_image"] = base_image
        entry["revision"] = int(revision)
        return True
    return False


def _feedback_has_final_frame(
    entry: dict[str, Any],
    *,
    image: Image.Image | None,
    revision: int,
    exact_frame: bool,
) -> bool:
    """Return true only after a post-commit, exact-camera frame is visible."""

    if not exact_frame or image is None or not bool(entry.get("committed", False)):
        return False
    committed_revision = entry.get("revision")
    if committed_revision is None or int(revision) < int(committed_revision):
        return False
    # A snapshot is consumed before the render requested for that edit.  The
    # image visible at snapshot time is therefore the last pre-edit frame.
    return image is not entry.get("base_image")


def _canvas_to_render(
    points: list[tuple[float, float]], mapping: tuple[int, int, int, int, int, int]
) -> list[np.ndarray]:
    left, top, width, height, render_width, render_height = mapping
    if width <= 0 or height <= 0:
        return []
    output: list[np.ndarray] = []
    for x, y in points:
        point = np.asarray(
            [
                (float(x) - left) * render_width / width,
                (float(y) - top) * render_height / height,
            ],
            dtype=np.float64,
        )
        if output and float(np.linalg.norm(point - output[-1])) < 0.45:
            continue
        output.append(point)
    if len(output) == 1:
        output.append(output[0].copy())
    return output


def _canvas_profile_to_render(
    points: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    radius_scales: tuple[float, ...] | list[float],
    mapping: tuple[int, int, int, int, int, int],
) -> tuple[list[np.ndarray], list[float]]:
    """Map a stroke and its immutable width profile without losing alignment."""

    if len(points) != len(radius_scales):
        raise ValueError("stroke points and radius scales must have equal length")
    left, top, width, height, render_width, render_height = mapping
    if width <= 0 or height <= 0:
        return [], []
    output: list[np.ndarray] = []
    scales: list[float] = []
    for (x, y), raw_scale in zip(points, radius_scales, strict=True):
        point = np.asarray(
            [
                (float(x) - left) * render_width / width,
                (float(y) - top) * render_height / height,
            ],
            dtype=np.float64,
        )
        scale = float(np.clip(float(raw_scale), 0.01, 1.0))
        if output and float(np.linalg.norm(point - output[-1])) < 0.45:
            # Retain the latest pressure even when Tk emitted another event at
            # the same sub-pixel location.
            output[-1] = point
            scales[-1] = scale
            continue
        output.append(point)
        scales.append(scale)
    if len(output) == 1:
        output.append(output[0].copy())
        scales.append(scales[0])
    return output, scales


def _simplify_polyline_indices(
    points: list[np.ndarray], tolerance: float = 0.65
) -> list[int]:
    if len(points) <= 2:
        return list(range(len(points)))
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    threshold_sq = float(tolerance) ** 2
    while pending:
        first, last = pending.pop()
        start = points[first]
        end = points[last]
        delta = end - start
        length_sq = float(delta @ delta)
        farthest = -1
        maximum = threshold_sq
        for index in range(first + 1, last):
            point = points[index]
            if length_sq <= 1.0e-12:
                distance_sq = float((point - start) @ (point - start))
            else:
                amount = min(
                    1.0,
                    max(0.0, float((point - start) @ delta / length_sq)),
                )
                difference = point - (start + amount * delta)
                distance_sq = float(difference @ difference)
            if distance_sq > maximum:
                maximum = distance_sq
                farthest = index
        if farthest >= 0:
            keep.add(farthest)
            pending.append((first, farthest))
            pending.append((farthest, last))
    return sorted(keep)


def _simplify_polyline(points: list[np.ndarray], tolerance: float = 0.65) -> list[np.ndarray]:
    """Remove sub-pixel mouse jitter while preserving every visible bend."""

    return [points[index] for index in _simplify_polyline_indices(points, tolerance)]


def _arc_length_weighted_pressure(
    points: tuple[tuple[float, float], ...],
    pressures: tuple[float, ...],
) -> float:
    """Average pressure by travelled distance, independent of event density."""

    if len(points) != len(pressures) or not points:
        return 1.0
    values = np.clip(np.asarray(pressures, dtype=np.float64), 0.0, 1.0)
    if len(points) == 1:
        return float(values[0])
    coordinates = np.asarray(points, dtype=np.float64)
    lengths = np.linalg.norm(np.diff(coordinates, axis=0), axis=1)
    total = float(lengths.sum())
    if total <= 1.0e-9:
        return float(values.mean())
    segment_pressure = (values[:-1] + values[1:]) * 0.5
    return float(np.dot(segment_pressure, lengths) / total)


def _segment_face_ids(
    face_ids: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    radius: float,
) -> np.ndarray:
    height, width = face_ids.shape
    x0 = max(0, int(math.floor(min(start[0], end[0]) - radius - 1.0)))
    y0 = max(0, int(math.floor(min(start[1], end[1]) - radius - 1.0)))
    x1 = min(width, int(math.ceil(max(start[0], end[0]) + radius + 1.0)) + 1)
    y1 = min(height, int(math.ceil(max(start[1], end[1]) + radius + 1.0)) + 1)
    if x1 <= x0 or y1 <= y0:
        return np.empty(0, dtype=np.int32)

    yy, xx = np.ogrid[y0:y1, x0:x1]
    delta = end - start
    length_sq = float(delta @ delta)
    if length_sq <= 1.0e-12:
        distance_sq = (xx - start[0]) ** 2 + (yy - start[1]) ** 2
    else:
        amount = np.clip(
            ((xx - start[0]) * delta[0] + (yy - start[1]) * delta[1])
            / length_sq,
            0.0,
            1.0,
        )
        closest_x = start[0] + amount * delta[0]
        closest_y = start[1] + amount * delta[1]
        distance_sq = (xx - closest_x) ** 2 + (yy - closest_y) ** 2
    values = face_ids[y0:y1, x0:x1][distance_sq <= radius * radius]
    if values.size == 0:
        return np.empty(0, dtype=np.int32)
    return np.unique(values[values >= 0]).astype(np.int32, copy=False)


def _point_face(face_ids: np.ndarray, point: np.ndarray) -> int:
    x = min(face_ids.shape[1] - 1, max(0, int(round(float(point[0])))))
    y = min(face_ids.shape[0] - 1, max(0, int(round(float(point[1])))))
    return int(face_ids[y, x])


def _effective_states_for_face_mapping(
    session: Any,
    face_mapping: dict[int, Any],
) -> tuple[np.ndarray, np.ndarray]:
    """Return mapping keys and effective states in the same stable order."""

    faces = np.fromiter(
        face_mapping,
        dtype=np.intp,
        count=len(face_mapping),
    )
    states = np.asarray(
        session.effective_indices_for_faces(faces),
        dtype=np.int8,
    )
    if states.shape != faces.shape:
        raise RuntimeError("局所有効色の面数が一致しません")
    return faces, states


def _stroke_geometry_arrays(
    session: Any,
    level: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """Reuse geometry arrays already validated by :class:`PaintSession`.

    Prepared OBJ faces are intentionally stored as ``int32``.  Upcasting the
    complete Mx3 array to ``int64`` for every brush release copied tens of
    megabytes on large models even though NumPy advanced indexing accepts the
    validated ``int32`` indices directly.  The session also owns a cached
    float64 vertex array, so prefer both caches and retain a small compatibility
    fallback for test doubles and recovered callers that predate them.
    """

    raw_faces = getattr(session, "faces", None)
    if raw_faces is None:
        raw_faces = level.faces
    faces = np.asarray(raw_faces)
    if faces.ndim != 2 or faces.shape[1:] != (3,):
        raise RuntimeError("ブラシ対象の面配列が不正です")
    if not np.issubdtype(faces.dtype, np.integer):
        raise RuntimeError("ブラシ対象の面インデックスが整数ではありません")

    raw_vertices = getattr(session, "vertices", None)
    if raw_vertices is None:
        raw_vertices = level.vertices_unit
    vertices = np.asarray(raw_vertices)
    if vertices.ndim != 2 or vertices.shape[1:] != (3,):
        raise RuntimeError("ブラシ対象の頂点配列が不正です")
    return faces, vertices


def _edge_guard_faces(
    session: Any,
    candidates: set[int],
    seeds: set[int],
    max_angle_degrees: float,
) -> set[int]:
    if not candidates:
        return set()
    valid_seeds = {seed for seed in seeds if seed in candidates}
    if not valid_seeds:
        return candidates
    neighbors = np.asarray(session.neighbors, dtype=np.int32)
    normals = np.asarray(session.normals, dtype=np.float64)
    normal_valid = np.asarray(session.normal_valid, dtype=bool)
    threshold = math.cos(math.radians(float(max_angle_degrees)))
    accepted = set(valid_seeds)
    pending = deque(valid_seeds)
    while pending:
        face = pending.popleft()
        for raw_neighbor in neighbors[face]:
            neighbor = int(raw_neighbor)
            if neighbor < 0 or neighbor not in candidates or neighbor in accepted:
                continue
            crosses = True
            if normal_valid[face] and normal_valid[neighbor]:
                dot = float(np.clip(normals[face] @ normals[neighbor], -1.0, 1.0))
                crosses = dot >= threshold
            if crosses:
                accepted.add(neighbor)
                pending.append(neighbor)
    return accepted


def _find_legacy_paint_option_parent(window: Any) -> Any | None:
    """Find the pre-ribbon options row for backwards compatibility only."""

    pending = list(window.winfo_children())
    while pending:
        widget = pending.pop()
        try:
            pending.extend(widget.winfo_children())
        except Exception:
            pass
        try:
            if str(widget.cget("text")) == "ブラシ半径":
                return widget.master
        except Exception:
            pass
    return None


def _resolve_paint_extension_hosts(
    editor: Any,
) -> tuple[Any | None, Any | None, Any | None]:
    """Return the public brush/shading hosts, then an old-UI fallback.

    ``brush_shape_host`` may live in a detached ``palette_tool_window``.  It
    remains the stable insertion surface, so add-ons must not infer a parent
    from the tool window itself or from localized widget text.  The legacy
    traversal is retained solely for recovered builds without public hosts.
    """

    brush_host = getattr(editor, "brush_shape_host", None)
    shading_host = getattr(editor, "auto_shading_host", None)
    legacy_host = None
    if brush_host is None or shading_host is None:
        legacy_host = _find_legacy_paint_option_parent(editor.window)
    return (
        brush_host if brush_host is not None else legacy_host,
        shading_host if shading_host is not None else legacy_host,
        legacy_host,
    )


def apply_smooth_paint_hotfix(
    paint_gui: Any,
    paint_module: Any,
    renderer_module: Any,
    mixer_module: Any,
    engine_module: Any,
) -> Any:
    """Install the adaptive brush, history, and editor preview patches."""

    editor_class = paint_gui.PaintEditorWindow
    if bool(getattr(editor_class, "_smooth_paint_hotfix_applied", False)):
        return editor_class

    session_class = paint_module.PaintSession
    original_editor_init = editor_class.__init__
    original_worker_initialize = editor_class._worker_initialize
    original_left_press = editor_class._on_left_press
    original_left_motion = editor_class._on_left_motion
    original_right_press = getattr(editor_class, "_on_right_press", None)
    original_middle_press = getattr(editor_class, "_on_middle_press", None)
    original_schedule_render = getattr(editor_class, "_schedule_render", None)
    original_commit_stroke = editor_class._commit_active_stroke
    original_consume_snapshot = editor_class._consume_snapshot
    original_draw_canvas = editor_class._draw_canvas
    original_editor_undo = editor_class._undo
    original_editor_redo = editor_class._redo
    original_editor_clear = editor_class._clear_all
    original_queue_fill = editor_class._queue_fill
    original_queue_smooth = editor_class._queue_smooth
    original_editor_close = editor_class.close
    original_editor_set_language = editor_class.set_language

    original_fill = session_class.fill
    original_smooth = session_class.smooth_boundary
    original_clear = session_class.clear_overrides
    original_undo = session_class.undo
    original_redo = session_class.redo

    def session_context(session: Any):
        store = getattr(session, "_hotfix_tree_store", None)
        owner = getattr(session, "_hotfix_tree_owner", None)
        return store if isinstance(store, dict) else None, owner

    def finish_tree_only_command(
        session: Any,
        undo_size: int,
        keys: set[int],
        before_nodes: dict[int, smooth_paint.PaintNode],
        label: str,
        before_values: np.ndarray,
    ) -> None:
        if not keys:
            return
        store, owner = session_context(session)
        if store is None:
            return
        after_nodes = _clone_store_subset(store, keys)
        if len(session._undo) > undo_size:
            command = session._undo[-1]
        else:
            indices = np.asarray(sorted(keys), dtype=np.int32)
            current = np.asarray(session.overrides[indices], dtype=np.int8).copy()
            command = paint_module.PaintCommand(
                indices,
                np.asarray(before_values, dtype=np.int8).copy(),
                current,
                label,
            )
            session._push_command(command)
        _attach_tree_history(command, keys, before_nodes, after_nodes)
        _bump_revision(owner)

    def fill_tree_aware(self, seed_face, state):
        store, _owner = session_context(self)
        if not store:
            return original_fill(self, seed_face, state)
        faces = np.asarray(self.connected_fill_faces(seed_face), dtype=np.int32)
        keys = {int(face) for face in faces if int(face) in store}
        if not keys:
            return original_fill(self, seed_face, state)
        before_nodes = _clone_store_subset(store, keys)
        ordered = np.asarray(sorted(keys), dtype=np.int32)
        before_values = np.asarray(self.overrides[ordered], dtype=np.int8).copy()
        undo_size = len(self._undo)
        changed = self._set_overrides(
            faces, self._validate_state(state), "塗りつぶし"
        )
        for key in keys:
            store.pop(key, None)
        finish_tree_only_command(
            self, undo_size, keys, before_nodes, "塗りつぶし", before_values
        )
        if len(changed) == 0:
            return ordered
        return np.unique(np.concatenate((np.asarray(changed, dtype=np.int32), ordered)))

    def smooth_tree_aware(self, *args, **kwargs):
        store, _owner = session_context(self)
        undo_size = len(self._undo)
        changed = original_smooth(self, *args, **kwargs)
        if not store or len(changed) == 0:
            return changed
        keys = {int(face) for face in np.asarray(changed) if int(face) in store}
        if not keys:
            return changed
        before_nodes = _clone_store_subset(store, keys)
        ordered = np.asarray(sorted(keys), dtype=np.int32)
        before_values = np.asarray(self.overrides[ordered], dtype=np.int8).copy()
        # The root colour was already changed by the original command.  The
        # old override values are stored on that command, when available.
        if len(self._undo) > undo_size:
            command = self._undo[-1]
            lookup = {int(face): value for face, value in zip(command.indices, command.before)}
            before_values = np.asarray(
                [lookup.get(int(face), self.overrides[int(face)]) for face in ordered],
                dtype=np.int8,
            )
        for key in keys:
            store.pop(key, None)
        finish_tree_only_command(
            self, undo_size, keys, before_nodes, "境界ならし", before_values
        )
        return changed

    def clear_tree_aware(self):
        store, _owner = session_context(self)
        undo_size = len(self._undo)
        changed = original_clear(self)
        if not store:
            return changed
        keys = set(int(key) for key in store)
        before_nodes = _clone_store_subset(store, keys)
        ordered = np.asarray(sorted(keys), dtype=np.int32)
        before_values = np.asarray(self.overrides[ordered], dtype=np.int8).copy()
        if len(self._undo) > undo_size:
            command = self._undo[-1]
            lookup = {int(face): value for face, value in zip(command.indices, command.before)}
            before_values = np.asarray(
                [lookup.get(int(face), before_values[index]) for index, face in enumerate(ordered)],
                dtype=np.int8,
            )
        store.clear()
        finish_tree_only_command(
            self, undo_size, keys, before_nodes, "全修正を解除", before_values
        )
        if len(changed) == 0:
            return ordered
        return np.unique(np.concatenate((np.asarray(changed, dtype=np.int32), ordered)))

    def undo_tree_aware(self):
        command = original_undo(self)
        if command is None:
            return None
        store, owner = session_context(self)
        keys = getattr(command, "_hotfix_tree_keys", None)
        snapshot = getattr(command, "_hotfix_tree_before", None)
        if store is not None and keys is not None and snapshot is not None:
            _restore_tree_snapshot(store, set(keys), snapshot)
            _bump_revision(owner)
        return command

    def redo_tree_aware(self):
        command = original_redo(self)
        if command is None:
            return None
        store, owner = session_context(self)
        keys = getattr(command, "_hotfix_tree_keys", None)
        snapshot = getattr(command, "_hotfix_tree_after", None)
        if store is not None and keys is not None and snapshot is not None:
            _restore_tree_snapshot(store, set(keys), snapshot)
            _bump_revision(owner)
        return command

    session_class.fill = fill_tree_aware
    session_class.smooth_boundary = smooth_tree_aware
    session_class.clear_overrides = clear_tree_aware
    session_class.undo = undo_tree_aware
    session_class.redo = redo_tree_aware

    def editor_palette(self):
        resolver = getattr(self, "_active_palette", None)
        if callable(resolver):
            try:
                return resolver()
            except (AttributeError, IndexError, ValueError):
                pass
        return self.settings.palette

    @functools.wraps(original_editor_init)
    def editor_init_smooth(self, *args, **kwargs):
        prepared = kwargs.get("prepared")
        if prepared is None and len(args) >= 2:
            prepared = args[1]
        initial_settings = kwargs.get("settings")
        if initial_settings is None and len(args) >= 3:
            initial_settings = args[2]
        if prepared is not None:
            self._hotfix_tree_store = _register_level(prepared)
            self._hotfix_tree_owner = prepared
            # The recovered editor queues its renderer worker at the end of
            # ``__init__``.  Configure the shared level before that queue can
            # race ahead, then refresh from the editor's cloned settings below.
            if initial_settings is not None:
                _configure_gpu_palette_routing(
                    initial_settings, prepared.final
                )
        original_editor_init(self, *args, **kwargs)
        if prepared is not None:
            self._hotfix_tree_store = _ensure_store(prepared)
            self._hotfix_tree_owner = prepared
            _configure_gpu_palette_routing(self.settings, self.level)
        self._hotfix_smooth_points = None
        self._hotfix_smooth_pressures = None
        self._hotfix_smooth_radius_scales = None
        self._hotfix_smooth_capture = None
        self._hotfix_overlay_cache = None
        # Provisional feedback remains visible until the first exact
        # post-commit render. Airbrush uses a clean non-paint guide rather than
        # an opaque spray simulation, so keeping it across worker acceptance
        # prevents a one-frame flash back to the unpainted base image.
        # There may be several queued strokes, so retain one entry per gesture.
        self._hotfix_feedback_serial = 0
        self._hotfix_pending_feedback = []
        self._hotfix_active_feedback = None
        self._hotfix_pending_stroke_batch = None
        self._hotfix_stroke_batch_serial = 0
        self._hotfix_stroke_debounce_after = None
        self._hotfix_airbrush_preview_after = None
        self._hotfix_stroke_debounce_ms = _STROKE_DEBOUNCE_MS
        self._hotfix_deferred_paint_render = False
        self._hotfix_brush_shape_var = tk.StringVar(
            master=self.window, value="round"
        )
        self._hotfix_pressure_status_var = tk.StringVar(master=self.window)
        try:
            self._hotfix_pen_pressure_bridge = PenPressureBridge(self.canvas)
        except Exception:
            # Native pressure is optional.  The pressure nib remains useful
            # through its deterministic arc-length taper fallback.
            self._hotfix_pen_pressure_bridge = None
        quality_values = tuple(
            self.i18n.text(f"paint.auto_quality_{code}")
            for code in ("fast", "standard", "high")
        )
        self._hotfix_auto_shading_quality_var = tk.StringVar(
            master=self.window, value=quality_values[1]
        )
        self._hotfix_auto_shading_strength_var = tk.DoubleVar(
            master=self.window, value=50.0
        )
        self._hotfix_auto_shading_boundary_var = tk.BooleanVar(
            master=self.window, value=True
        )
        self._hotfix_auto_shading_active = False
        self._hotfix_auto_shading_button = None

        # Current builds publish separate extension hosts, including when the
        # brush host is inside a detached Toplevel. Retain the recovered
        # options-row lookup only for old UI packages so this adapter remains
        # backwards compatible. Marker width follows the existing brush
        # diameter and its long edge stays perpendicular to the current stroke.
        try:
            brush_parent, shading_parent, legacy_parent = (
                _resolve_paint_extension_hosts(self)
            )
            if brush_parent is not None:
                modern_brush_host = brush_parent is not legacy_parent
                brush_row = 0 if modern_brush_host else 1
                ttk.Label(
                    brush_parent,
                    text=self.i18n.text("paint.nib"),
                    style="PaintPanel.TLabel",
                ).grid(row=brush_row, column=0, sticky="nw", pady=(4, 0))
                ttk.Radiobutton(
                    brush_parent,
                    text=self.i18n.text("paint.round_nib"),
                    value="round",
                    variable=self._hotfix_brush_shape_var,
                    style="Paint.Tool.TRadiobutton",
                ).grid(row=brush_row, column=1, sticky="w", pady=(4, 0))
                ttk.Radiobutton(
                    brush_parent,
                    text=self.i18n.text("paint.marker_nib"),
                    value="marker",
                    variable=self._hotfix_brush_shape_var,
                    style="Paint.Tool.TRadiobutton",
                ).grid(
                    row=brush_row + (1 if modern_brush_host else 0),
                    column=1 if modern_brush_host else 2,
                    columnspan=4,
                    sticky="w",
                    pady=(4, 0),
                )
                ttk.Radiobutton(
                    brush_parent,
                    text=self.i18n.text("paint.pressure_taper_nib"),
                    value="pressure_taper",
                    variable=self._hotfix_brush_shape_var,
                    style="Paint.Tool.TRadiobutton",
                ).grid(
                    row=brush_row + (2 if modern_brush_host else 0),
                    column=1 if modern_brush_host else 6,
                    columnspan=5,
                    sticky="w",
                    pady=(4, 0),
                )
                ttk.Label(
                    brush_parent,
                    text=self.i18n.text("paint.marker_hint"),
                    style="PaintPanelMuted.TLabel",
                    wraplength=320 if modern_brush_host else 0,
                ).grid(
                    row=brush_row + 3 if modern_brush_host else brush_row,
                    column=0 if modern_brush_host else 5,
                    columnspan=5 if modern_brush_host else 5,
                    sticky="w",
                    padx=(0, 0) if modern_brush_host else (10, 0),
                    pady=(4, 0),
                )
                ttk.Label(
                    brush_parent,
                    textvariable=self._hotfix_pressure_status_var,
                    style="PaintPanelMuted.TLabel",
                    wraplength=430 if modern_brush_host else 0,
                ).grid(
                    row=brush_row + 4 if modern_brush_host else brush_row + 1,
                    column=0,
                    columnspan=8,
                    sticky="w",
                    pady=(3, 0),
                )

            shading = None
            if shading_parent is not None:
                if shading_parent is legacy_parent:
                    shading = ttk.Frame(
                        shading_parent,
                        style="PaintPanel.TFrame",
                    )
                    shading.grid(
                        row=2,
                        column=0,
                        columnspan=10,
                        sticky="ew",
                        pady=(7, 0),
                    )
                else:
                    shading = shading_parent

            if shading is not None:
                shading.columnconfigure(4, weight=1)
                ttk.Label(
                    shading,
                    text=self.i18n.text("paint.auto_shading"),
                    style="PaintPanel.TLabel",
                ).grid(row=0, column=0, sticky="w")
                ttk.Label(
                    shading,
                    text=self.i18n.text("paint.auto_quality"),
                    style="PaintPanelMuted.TLabel",
                ).grid(row=0, column=1, sticky="e", padx=(12, 4))
                self._hotfix_auto_shading_quality_selector = ttk.Combobox(
                    shading,
                    textvariable=self._hotfix_auto_shading_quality_var,
                    values=quality_values,
                    state="readonly",
                    width=8,
                    style="HighContrast.TCombobox",
                )
                self._hotfix_auto_shading_quality_selector.grid(
                    row=0, column=2, sticky="w"
                )
                ttk.Label(
                    shading,
                    text=self.i18n.text("paint.auto_strength"),
                    style="PaintPanelMuted.TLabel",
                ).grid(row=0, column=3, sticky="e", padx=(12, 4))
                tk.Scale(
                    shading,
                    from_=0,
                    to=100,
                    resolution=5,
                    orient=tk.HORIZONTAL,
                    variable=self._hotfix_auto_shading_strength_var,
                    bg=getattr(paint_gui, "PANEL", "#151A22"),
                    fg=getattr(paint_gui, "TEXT", "#E8EDF4"),
                    troughcolor="#303A49",
                    activebackground=getattr(paint_gui, "ACCENT", "#56C2FF"),
                    highlightthickness=0,
                    length=180,
                ).grid(row=0, column=4, sticky="ew")
                ttk.Checkbutton(
                    shading,
                    text=self.i18n.text("paint.auto_boundary_only"),
                    variable=self._hotfix_auto_shading_boundary_var,
                    style="Paint.TCheckbutton",
                ).grid(row=0, column=5, sticky="w", padx=(12, 4))
                self._hotfix_auto_shading_button = ttk.Button(
                    shading,
                    text=self.i18n.text("paint.auto_apply"),
                    command=lambda: queue_auto_shading(self),
                    style="PaintGood.TButton",
                )
                self._hotfix_auto_shading_button.grid(
                    row=0, column=6, sticky="e", padx=(8, 0)
                )

            # These controls are added after the editor's first localization
            # capture. Register each distinct extension surface so language
            # changes update the nib and auto-shading labels as well.
            captured: set[int] = set()
            for host in (brush_parent, shading_parent):
                if host is None or id(host) in captured:
                    continue
                self.localizer.capture(host)
                captured.add(id(host))
            if captured:
                self.localizer.apply()
            update_pressure_status(self)
        except Exception:
            # Painting remains fully usable if a future recovered UI changes
            # the option-row widget hierarchy.
            pass

    def worker_initialize_smooth(self):
        snapshot = original_worker_initialize(self)
        if self._session is None:
            return snapshot
        store = getattr(self, "_hotfix_tree_store", _ensure_store(self.prepared))
        self._session._hotfix_tree_store = store
        self._session._hotfix_tree_owner = self.prepared
        if not store:
            return snapshot

        roots = np.asarray(
            sorted(face for face in store if 0 <= int(face) < len(self.level.faces)),
            dtype=np.int32,
        )
        if len(roots) == 0:
            return snapshot
        self._session.overrides[roots] = np.asarray(
            [store[int(face)].dominant_state() for face in roots], dtype=np.int8
        )
        self._display_colors = engine_module.apply_palette_overrides_parts(
            self.level,
            self.settings.geometry.height_mm,
            self.settings.palette,
            self.settings.part_palettes,
            self._auto_colors,
            self._session.overrides,
        )
        self._renderer.invalidate_colors(source=False, target=True)
        frame = self._renderer.render(
            self._display_colors,
            camera=self.camera,
            render_source=False,
            render_target=True,
            render_face_ids=True,
        )
        return self._worker_snapshot(frame, "滑らかブラシの色修正を復元しました")

    def feedback_color(self, erase: bool) -> str:
        if erase:
            return "#DDE6EE"
        state = int(self.paint_state_var.get())
        palette = editor_palette(self)
        values, _rgb = mixer_module.build_palette_rgb(
            list(palette.physical_hex),
            list(palette.mix_hex_overrides),
            list(palette.mix_ratios_b),
            list(palette.secondary_mix_ratios_b),
        )
        return str(values[state])

    def update_pressure_status(self) -> None:
        variable = getattr(self, "_hotfix_pressure_status_var", None)
        if variable is None:
            return
        bridge = getattr(self, "_hotfix_pen_pressure_bridge", None)
        if bridge is not None and bool(getattr(bridge, "detected", False)):
            key = "paint.pressure_detected"
        elif bridge is not None and bool(getattr(bridge, "enabled", False)):
            key = "paint.pressure_waiting"
        else:
            key = "paint.pressure_unavailable"
        try:
            variable.set(self.i18n.text(key))
        except Exception:
            pass

    def event_pressure(self, event: Any) -> float | None:
        bridge = getattr(self, "_hotfix_pen_pressure_bridge", None)
        if bridge is None:
            return None
        try:
            pressure = bridge.pressure_for_event(event)
        except Exception:
            pressure = None
        update_pressure_status(self)
        return pressure

    def brush_shape(self) -> str:
        variable = getattr(self, "_hotfix_brush_shape_var", None)
        try:
            value = str(variable.get())
            return value if value in ("marker", "pressure_taper") else "round"
        except Exception:
            return "round"

    def feedback_rgb(self, color: str) -> tuple[int, int, int]:
        try:
            values = self.canvas.winfo_rgb(str(color))
            return tuple(int(round(value / 257.0)) for value in values)
        except Exception:
            return (128, 128, 128)

    def feedback_backdrop_rgb(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> tuple[int, int, int]:
        try:
            mapping = self.target_mapping
            image = self.target_image
            left, top, width, height, render_width, render_height = mapping
            midpoint_x = (float(start[0]) + float(end[0])) * 0.5
            midpoint_y = (float(start[1]) + float(end[1])) * 0.5
            if (
                image is not None
                and width > 0
                and height > 0
                and left <= midpoint_x < left + width
                and top <= midpoint_y < top + height
            ):
                pixel_x = int(
                    np.clip(
                        (midpoint_x - left) * render_width / width,
                        0,
                        render_width - 1,
                    )
                )
                pixel_y = int(
                    np.clip(
                        (midpoint_y - top) * render_height / height,
                        0,
                        render_height - 1,
                    )
                )
                pixel = image.getpixel((pixel_x, pixel_y))
                if isinstance(pixel, tuple) and len(pixel) >= 3:
                    return tuple(int(value) for value in pixel[:3])
                return tuple(
                    int(value)
                    for value in image.convert("RGB").getpixel(
                        (pixel_x, pixel_y)
                    )
                )
        except Exception:
            pass
        try:
            return feedback_rgb(self, str(self.canvas.cget("background")))
        except Exception:
            return (9, 12, 17)

    def blended_feedback_color(
        target_rgb: tuple[int, int, int],
        backdrop_rgb: tuple[int, int, int],
        opacity: float,
    ) -> str:
        alpha = float(np.clip(float(opacity), 0.0, 1.0))
        channels = tuple(
            int(round(background * (1.0 - alpha) + target * alpha))
            for target, background in zip(
                target_rgb, backdrop_rgb, strict=True
            )
        )
        return "#{:02X}{:02X}{:02X}".format(*channels)

    def draw_feedback_segment(
        self,
        start,
        end,
        erase: bool,
        color: str | None = None,
        shape: str | None = None,
        radius_pixels: float | None = None,
        start_scale: float = 1.0,
        end_scale: float = 1.0,
        airbrush_opacities: tuple[float, ...] | list[float] | None = None,
    ) -> None:
        try:
            base_radius = float(
                self._brush_radius_pixels()
                if radius_pixels is None
                else radius_pixels
            )
            stroke_color = color or feedback_color(self, erase)
            current_shape = brush_shape(self) if shape is None else str(shape)
            radius = base_radius * float(
                np.clip((float(start_scale) + float(end_scale)) * 0.5, 0.01, 1.0)
            )
            if current_shape == "airbrush":
                # The old preview stacked 16 opaque Canvas capsules for every
                # pointer event.  Overlapping backdrop-preblended colours made
                # a false dark halo and a bead-like smear even though the
                # committed adaptive paint was clean.  Keep the exact capsule
                # centreline/radius as a lightweight outline instead.  The
                # current head below communicates falloff and hold density;
                # final colour remains the authoritative mesh result.
                opacity_values = tuple(
                    float(value) for value in (airbrush_opacities or ())
                )
                if len(opacity_values) != len(_AIRBRUSH_FEEDBACK_RADII):
                    opacity_values = tuple(
                        float(value)
                        for value in accumulated_airbrush_deposit(
                            _AIRBRUSH_FEEDBACK_FALLOFF,
                            1.0,
                            1.0,
                            1,
                        )
                    )
                if start == end:
                    draw_airbrush_head(
                        self,
                        end,
                        stroke_color,
                        base_radius,
                        end_scale,
                        opacity_values,
                    )
                    return
                if not airbrush_feedback_segment_is_paintable(self, start, end):
                    return
                dx = float(end[0]) - float(start[0])
                dy = float(end[1]) - float(start[1])
                length = max(math.hypot(dx, dy), 1.0e-9)
                normal_x = -dy / length
                normal_y = dx / length
                start_radius = max(1.0, base_radius * float(start_scale))
                end_radius = max(1.0, base_radius * float(end_scale))
                guide_color = stroke_color
                for direction in (-1.0, 1.0):
                    boundary_start = (
                        float(start[0]) + normal_x * start_radius * direction,
                        float(start[1]) + normal_y * start_radius * direction,
                    )
                    boundary_end = (
                        float(end[0]) + normal_x * end_radius * direction,
                        float(end[1]) + normal_y * end_radius * direction,
                    )
                    # Boundary hints are useful only on pixels the final tool
                    # may touch. Suppress the side that falls outside the
                    # visible/active surface instead of drawing a false halo
                    # across the model silhouette.
                    if not airbrush_feedback_segment_is_paintable(
                        self, boundary_start, boundary_end
                    ):
                        continue
                    self.canvas.create_line(
                        boundary_start[0],
                        boundary_start[1],
                        boundary_end[0],
                        boundary_end[1],
                        fill=guide_color,
                        width=1,
                        tags=("smooth-stroke-feedback", "smooth-airbrush-guide"),
                    )
                self.canvas.create_line(
                    start[0],
                    start[1],
                    end[0],
                    end[1],
                    fill=guide_color,
                    width=2,
                    capstyle="round",
                    tags=("smooth-stroke-feedback", "smooth-airbrush-guide"),
                )
            elif current_shape == "marker":
                polygon = smooth_paint.marker_stroke_polygon(
                    np.asarray(start, dtype=np.float64),
                    np.asarray(end, dtype=np.float64),
                    radius * 2.0,
                    thickness=max(1.0, radius * 2.0 * 0.25),
                    angle_degrees=None,
                )
                self.canvas.create_polygon(
                    *[float(value) for point in polygon for value in point],
                    fill=stroke_color,
                    outline="",
                    stipple="gray50" if erase else "",
                    tags=("smooth-stroke-feedback",),
                )
            elif start == end:
                self.canvas.create_oval(
                    start[0] - radius,
                    start[1] - radius,
                    start[0] + radius,
                    start[1] + radius,
                    fill=stroke_color,
                    outline="",
                    stipple="gray50" if erase else "",
                    tags=("smooth-stroke-feedback",),
                )
            else:
                self.canvas.create_line(
                    start[0],
                    start[1],
                    end[0],
                    end[1],
                    fill=stroke_color,
                    width=max(2, int(round(radius * 2.0))),
                    capstyle="round",
                    smooth=True,
                    stipple="gray50" if erase else "",
                    tags=("smooth-stroke-feedback",),
                )
        except Exception:
            pass

    def feedback_point_face(self, point) -> int:
        """Return a visible, currently paintable face below one Canvas point."""

        try:
            face = int(self._face_at(int(round(point[0])), int(round(point[1]))))
            if face < 0:
                return -1
            session = getattr(self, "_session", None)
            allowed = getattr(session, "allowed_face_mask", None)
            if allowed is not None:
                allowed = np.asarray(allowed, dtype=bool)
                if face >= len(allowed) or not bool(allowed[face]):
                    return -1
            visible_resolver = getattr(self, "_visible_face_mask_for_stroke", None)
            if callable(visible_resolver):
                visible = visible_resolver()
                if visible is not None:
                    visible = np.asarray(visible, dtype=bool)
                    if face >= len(visible) or not bool(visible[face]):
                        return -1
            return face
        except Exception:
            return -1

    def airbrush_feedback_segment_is_paintable(self, start, end) -> bool:
        """Fail closed when a guide would cross hidden/background pixels."""

        midpoint = (
            (float(start[0]) + float(end[0])) * 0.5,
            (float(start[1]) + float(end[1])) * 0.5,
        )
        return all(
            feedback_point_face(self, point) >= 0
            for point in (start, midpoint, end)
        )

    def draw_airbrush_head(
        self,
        point,
        color: str,
        radius_pixels: float,
        radius_scale: float,
        opacities: tuple[float, ...] | list[float],
    ) -> None:
        """Draw one O(1) falloff cursor; never repaint the accumulated trail."""

        try:
            self.canvas.delete("smooth-airbrush-head")
            if feedback_point_face(self, point) < 0:
                return
            radius = max(1.0, float(radius_pixels) * float(radius_scale))
            density = float(np.clip(max(opacities, default=0.0), 0.0, 1.0))
            core_radius = max(1.5, radius * (0.08 + 0.18 * density))
            self.canvas.create_oval(
                float(point[0]) - radius,
                float(point[1]) - radius,
                float(point[0]) + radius,
                float(point[1]) + radius,
                fill="",
                outline=color,
                width=2,
                dash=(3, 3),
                tags=("smooth-stroke-feedback", "smooth-airbrush-head"),
            )
            self.canvas.create_oval(
                float(point[0]) - core_radius,
                float(point[1]) - core_radius,
                float(point[0]) + core_radius,
                float(point[1]) + core_radius,
                fill=color,
                outline="",
                tags=("smooth-stroke-feedback", "smooth-airbrush-head"),
            )
        except Exception:
            pass

    def redraw_pending_feedback(self) -> None:
        """Rebuild every not-yet-presented stroke after a Canvas redraw."""

        try:
            self.canvas.delete("smooth-stroke-feedback")
        except Exception:
            return
        for entry in list(getattr(self, "_hotfix_pending_feedback", ())):
            # Canvas points belong to the camera/mapping captured when the
            # gesture started.  Once the view changes those coordinates cannot
            # be projected safely without the touched 3D points, so keep the
            # token for worker/Undo ordering but never redraw a stale guide.
            if bool(entry.get("view_suppressed", False)):
                continue
            points = list(entry.get("points") or ())
            if not points:
                continue
            erase = bool(entry.get("erase", False))
            color = entry.get("color")
            shape = entry.get("shape", "round")
            radius_pixels = entry.get("radius_pixels")
            airbrush_opacities = entry.get("airbrush_opacities")
            radius_scales = list(entry.get("radius_scales") or ())
            if len(radius_scales) != len(points):
                radius_scales = [1.0] * len(points)
            if len(points) == 1:
                draw_feedback_segment(
                    self,
                    points[0],
                    points[0],
                    erase,
                    color,
                    shape,
                    radius_pixels,
                    radius_scales[0],
                    radius_scales[0],
                    airbrush_opacities,
                )
                continue
            for index, (start, end) in enumerate(zip(points, points[1:])):
                draw_feedback_segment(
                    self,
                    start,
                    end,
                    erase,
                    color,
                    shape,
                    radius_pixels,
                    radius_scales[index],
                    radius_scales[index + 1],
                    airbrush_opacities,
                )
            if str(shape) == "airbrush":
                draw_airbrush_head(
                    self,
                    points[-1],
                    str(color or feedback_color(self, False)),
                    float(
                        self._brush_radius_pixels()
                        if radius_pixels is None
                        else radius_pixels
                    ),
                    float(radius_scales[-1]),
                    tuple(float(value) for value in (airbrush_opacities or ())),
                )

    def cancel_airbrush_preview(self) -> None:
        """Cancel the sole live-hold timer without leaving a late callback."""

        after_id = getattr(self, "_hotfix_airbrush_preview_after", None)
        self._hotfix_airbrush_preview_after = None
        if after_id is not None:
            try:
                self.window.after_cancel(after_id)
            except Exception:
                pass

    def suppress_pending_feedback_for_view_change(
        self, *, force: bool = False
    ) -> bool:
        """Hide screen-space guides before their camera becomes obsolete.

        Feedback entries also carry the worker commit token, so deleting them
        here would break the exact-render acceptance boundary and could strand
        Undo ordering.  Suppression is deliberately display-only: the entry
        remains pending until its edit is accepted and an exact frame for the
        current camera/revision retires it normally.
        """

        current_camera = getattr(self, "camera", None)
        changed = False
        for entry in list(getattr(self, "_hotfix_pending_feedback", ())):
            if bool(entry.get("view_suppressed", False)):
                continue
            captured_camera = entry.get("view_camera")
            camera_matches = captured_camera is current_camera
            if not camera_matches:
                try:
                    camera_matches = bool(captured_camera == current_camera)
                except Exception:
                    camera_matches = False
            if force or (captured_camera is not None and not camera_matches):
                entry["view_suppressed"] = True
                changed = True
        if not changed:
            return False
        cancel_airbrush_preview(self)
        try:
            self.canvas.delete("smooth-stroke-feedback")
        except Exception:
            pass
        return True

    def current_airbrush_preview_pressure(self) -> float:
        points = getattr(self, "_hotfix_smooth_points", None)
        raw_pressures = getattr(self, "_hotfix_smooth_pressures", None)
        if not isinstance(points, (list, tuple)) or not points:
            return 1.0
        if (
            not isinstance(raw_pressures, (list, tuple))
            or len(raw_pressures) != len(points)
        ):
            return 1.0
        values = tuple(
            1.0 if value is None else float(value) for value in raw_pressures
        )
        return _arc_length_weighted_pressure(tuple(points), values)

    def airbrush_preview_opacities(
        self,
        capture: _SmoothStrokeCapture,
        pressure: float,
        dab_count: int,
    ) -> tuple[float, ...]:
        return tuple(
            float(value)
            for value in accumulated_airbrush_deposit(
                _AIRBRUSH_FEEDBACK_FALLOFF,
                float(capture.airbrush_strength),
                float(pressure),
                max(1, int(dab_count)),
            )
        )

    def refresh_airbrush_preview(self) -> None:
        """Advance held-airbrush feedback from elapsed time on the Tk thread."""

        self._hotfix_airbrush_preview_after = None
        if bool(getattr(self, "_close_requested", False)):
            return
        if getattr(self, "_drag_mode", None) != "airbrush-stroke":
            return
        capture = getattr(self, "_hotfix_smooth_capture", None)
        feedback = getattr(self, "_hotfix_active_feedback", None)
        if not isinstance(capture, _SmoothStrokeCapture) or not isinstance(
            feedback, dict
        ):
            return
        if bool(feedback.get("view_suppressed", False)):
            return
        started_at = getattr(self, "_airbrush_started_at", None)
        if started_at is None:
            started_at = feedback.get("airbrush_started_at")
        duration = (
            max(0.0, time.monotonic() - float(started_at))
            if started_at is not None
            else 0.0
        )
        dab_count = airbrush_hold_dab_count(duration)
        pressure = current_airbrush_preview_pressure(self)
        opacities = airbrush_preview_opacities(
            self, capture, pressure, dab_count
        )
        if (
            int(feedback.get("airbrush_dab_count", 0)) != dab_count
            or tuple(feedback.get("airbrush_opacities") or ()) != opacities
        ):
            feedback["airbrush_dab_count"] = dab_count
            feedback["airbrush_pressure"] = pressure
            feedback["airbrush_opacities"] = opacities
            points = list(feedback.get("points") or ())
            radius_scales = list(feedback.get("radius_scales") or ())
            if points:
                draw_airbrush_head(
                    self,
                    points[-1],
                    str(feedback.get("color") or feedback_color(self, False)),
                    float(
                        feedback.get("radius_pixels")
                        or self._brush_radius_pixels()
                    ),
                    float(radius_scales[-1] if radius_scales else 1.0),
                    opacities,
                )
        try:
            self._hotfix_airbrush_preview_after = self.window.after(
                _AIRBRUSH_PREVIEW_REFRESH_MS,
                lambda: refresh_airbrush_preview(self),
            )
        except Exception:
            self._hotfix_airbrush_preview_after = None

    def schedule_airbrush_preview(self) -> None:
        cancel_airbrush_preview(self)
        try:
            self._hotfix_airbrush_preview_after = self.window.after(
                _AIRBRUSH_PREVIEW_REFRESH_MS,
                lambda: refresh_airbrush_preview(self),
            )
        except Exception:
            self._hotfix_airbrush_preview_after = None

    def restart_stroke_debounce(self) -> None:
        """Postpone all heavy paint work while the user keeps drawing."""

        pending = getattr(self, "_hotfix_pending_stroke_batch", None)
        if pending is None:
            return
        after_id = getattr(self, "_hotfix_stroke_debounce_after", None)
        if after_id is not None:
            try:
                self.window.after_cancel(after_id)
            except Exception:
                pass
        delay = max(1, int(getattr(self, "_hotfix_stroke_debounce_ms", 300)))
        self._hotfix_stroke_debounce_after = self.window.after(
            delay, lambda: flush_smooth_batch(self, wait_for_release=True)
        )

    def left_press_smooth(self, event):
        result = original_left_press(self, event)
        drag_mode = getattr(self, "_drag_mode", None)
        if drag_mode == "orbit":
            suppress_pending_feedback_for_view_change(self, force=True)
            return result
        if drag_mode not in ("stroke", "airbrush-stroke"):
            return result
        mapping = getattr(self, "target_mapping", None)
        ids = getattr(self, "face_ids", None)
        if mapping is None or ids is None:
            return result
        point = (float(event.x), float(event.y))
        is_airbrush = drag_mode == "airbrush-stroke"
        erase = bool(self._stroke_erase) if not is_airbrush else False
        color = feedback_color(self, erase)
        shape = "airbrush" if is_airbrush else brush_shape(self)
        radius_pixels = float(self._brush_radius_pixels())
        pressure = (
            event_pressure(self, event)
            if shape in ("pressure_taper", "airbrush")
            else None
        )
        if shape == "airbrush":
            effective_pressure = 1.0 if pressure is None else float(pressure)
            initial_scale = airbrush_radius_scale(effective_pressure)
            stored_pressure = effective_pressure
        elif shape == "pressure_taper":
            initial_scale = (
                pressure_radius_scale(pressure) if pressure is not None else 0.15
            )
            stored_pressure = pressure
        else:
            initial_scale = 1.0
            stored_pressure = pressure
        selected_state = int(self.paint_state_var.get())
        palette = editor_palette(self)
        active_states = list(bool(value) for value in palette.enabled_states)
        if 0 <= selected_state < len(active_states):
            active_states[selected_state] = True
        captured_palette_rgb = _palette_rgb(palette, mixer_module)
        self._hotfix_smooth_points = [point]
        self._hotfix_smooth_pressures = [stored_pressure]
        self._hotfix_smooth_radius_scales = [initial_scale]
        self._hotfix_smooth_capture = _SmoothStrokeCapture(
            camera=self.camera,
            mapping=tuple(mapping),
            face_ids=ids,
            pixels_per_unit=float(self._render_pixels_per_unit or 1.0),
            radius_mm=float(self.brush_radius_var.get()),
            height_mm=float(self.settings.geometry.height_mm),
            protect_edges=bool(self.edge_guard_var.get()),
            edge_angle_degrees=float(self.edge_angle_var.get()),
            selected_state=selected_state,
            shape=shape,
            erase=erase,
            feedback_color=color,
            feedback_radius_pixels=radius_pixels,
            tool="airbrush" if is_airbrush else "brush",
            airbrush_strength=(
                float(np.clip(float(self.airbrush_strength_var.get()) / 100.0, 0.0, 1.0))
                if is_airbrush
                else 1.0
            ),
            palette_rgb=tuple(
                tuple(float(channel) for channel in rgb)
                for rgb in captured_palette_rgb
            ),
            enabled_states=tuple(active_states),
        )
        preview_dab_count = 1
        preview_pressure = (
            float(stored_pressure) if is_airbrush else 1.0
        )
        preview_opacities = (
            airbrush_preview_opacities(
                self,
                self._hotfix_smooth_capture,
                preview_pressure,
                preview_dab_count,
            )
            if is_airbrush
            else ()
        )
        self._stroke_faces.clear()
        self._hotfix_feedback_serial = int(
            getattr(self, "_hotfix_feedback_serial", 0)
        ) + 1
        feedback = {
            "token": self._hotfix_feedback_serial,
            "points": self._hotfix_smooth_points,
            "erase": erase,
            "color": color,
            "shape": shape,
            "radius_pixels": radius_pixels,
            "radius_scales": self._hotfix_smooth_radius_scales,
            "width_source": "pressure" if pressure is not None else (
                "taper" if shape == "pressure_taper" else "fixed"
            ),
            "committed": False,
            "base_image": None,
            "revision": None,
            # Provisional geometry is Canvas-space, not mesh-space.  The
            # camera identity lets the render scheduler retire it immediately
            # when zoom/pan/orbit starts, while preserving this entry's commit
            # token until an exact final frame arrives.
            "view_camera": self.camera,
            "view_suppressed": False,
            "airbrush_started_at": (
                getattr(self, "_airbrush_started_at", None)
                if is_airbrush
                else None
            ),
            "airbrush_dab_count": preview_dab_count if is_airbrush else None,
            "airbrush_pressure": preview_pressure if is_airbrush else None,
            "airbrush_opacities": preview_opacities,
        }
        self._hotfix_active_feedback = feedback
        self._hotfix_pending_feedback.append(feedback)
        # Do not rebuild every older pending stroke here.  During a debounce
        # burst that would turn the UI path into O(stroke history).  Only the
        # newly pressed nib is missing from the existing Canvas.
        draw_feedback_segment(
            self,
            point,
            point,
            erase,
            color,
            shape,
            radius_pixels,
            initial_scale,
            initial_scale,
            preview_opacities,
        )
        if is_airbrush:
            schedule_airbrush_preview(self)
        restart_stroke_debounce(self)
        return result

    def right_press_smooth(self, event):
        if original_right_press is None:
            return None
        result = original_right_press(self, event)
        if getattr(self, "_drag_mode", None) == "orbit":
            # Clear on gesture start, not after the first throttled render, so
            # a stationary right press cannot leave a previous path floating.
            suppress_pending_feedback_for_view_change(self, force=True)
        return result

    def middle_press_smooth(self, event):
        if original_middle_press is None:
            return None
        result = original_middle_press(self, event)
        if getattr(self, "_drag_mode", None) == "pan":
            suppress_pending_feedback_for_view_change(self, force=True)
        return result

    def schedule_render_smooth(self, *, immediate: bool = False) -> None:
        # Zoom, pan, orbit and Reset all mutate ``camera`` before scheduling.
        # Comparing at this single choke point also covers keyboard/programmatic
        # view changes without coupling this paint patch to rotation_hotfix.
        suppress_pending_feedback_for_view_change(self)
        if original_schedule_render is None:
            return None
        return original_schedule_render(self, immediate=immediate)

    def left_motion_smooth(self, event):
        points = getattr(self, "_hotfix_smooth_points", None)
        drag_mode = getattr(self, "_drag_mode", None)
        if drag_mode not in ("stroke", "airbrush-stroke") or not points:
            return original_left_motion(self, event)
        point = (float(event.x), float(event.y))
        previous = points[-1]
        capture = getattr(self, "_hotfix_smooth_capture", None)
        shape = str(getattr(capture, "shape", brush_shape(self)))
        minimum_step = (
            max(
                1.25,
                min(
                    3.0,
                    float(getattr(capture, "feedback_radius_pixels", 8.0)) * 0.08,
                ),
            )
            if shape == "airbrush"
            else 0.45
        )
        if math.hypot(point[0] - previous[0], point[1] - previous[1]) < minimum_step:
            return None
        points.append(point)
        pressures = getattr(self, "_hotfix_smooth_pressures", None)
        radius_scales = getattr(self, "_hotfix_smooth_radius_scales", None)
        pressure = (
            event_pressure(self, event)
            if shape in ("pressure_taper", "airbrush")
            else None
        )
        if shape == "airbrush" and pressure is None:
            pressure = next(
                (
                    float(value)
                    for value in reversed(pressures or ())
                    if value is not None
                ),
                1.0,
            )
        if isinstance(pressures, list):
            pressures.append(pressure)
        if shape == "airbrush":
            scale = airbrush_radius_scale(float(pressure))
        elif shape == "pressure_taper":
            if pressure is not None:
                scale = pressure_radius_scale(pressure)
            else:
                previous_pressure = next(
                    (
                        value
                        for value in reversed(pressures[:-1] if isinstance(pressures, list) else ())
                        if value is not None
                    ),
                    None,
                )
                scale = (
                    pressure_radius_scale(previous_pressure)
                    if previous_pressure is not None
                    else 0.15
                )
        else:
            scale = 1.0
        if isinstance(radius_scales, list):
            radius_scales.append(scale)
        self._stroke_last_xy = (int(event.x), int(event.y))
        feedback = getattr(self, "_hotfix_active_feedback", None)
        color = feedback.get("color") if isinstance(feedback, dict) else None
        shape = feedback.get("shape") if isinstance(feedback, dict) else None
        radius_pixels = (
            feedback.get("radius_pixels") if isinstance(feedback, dict) else None
        )
        airbrush_opacities = (
            feedback.get("airbrush_opacities")
            if isinstance(feedback, dict)
            else None
        )
        feedback_suppressed = bool(
            isinstance(feedback, dict)
            and feedback.get("view_suppressed", False)
        )
        if not feedback_suppressed:
            draw_feedback_segment(
                self,
                previous,
                point,
                bool(self._stroke_erase),
                color,
                shape,
                radius_pixels,
                (
                    radius_scales[-2]
                    if isinstance(radius_scales, list) and len(radius_scales) >= 2
                    else 1.0
                ),
                scale,
                airbrush_opacities,
            )
            if shape == "airbrush":
                draw_airbrush_head(
                    self,
                    point,
                    str(color or feedback_color(self, False)),
                    float(radius_pixels or self._brush_radius_pixels()),
                    float(scale),
                    tuple(float(value) for value in (airbrush_opacities or ())),
                )
        restart_stroke_debounce(self)
        return None

    def current_tree_revision(self) -> int:
        return int(getattr(self._hotfix_tree_owner, "_hotfix_tree_revision", 0))

    def auto_shading_snapshot(
        self,
        message: str,
        *,
        changed: int = 0,
        error: str | None = None,
        result: auto_shading.AutoShadingResult | None = None,
    ) -> dict[str, Any]:
        try:
            if self._session is not None:
                snapshot = self._worker_snapshot(None, message, changed)
            else:
                snapshot = {"message": message, "changed": int(changed)}
        except Exception:
            snapshot = {"message": message, "changed": int(changed)}
        snapshot["_hotfix_auto_shading_done"] = True
        if error:
            snapshot["_hotfix_auto_shading_error"] = str(error)
        if result is not None:
            snapshot["_hotfix_auto_shading_stats"] = {
                "candidate_faces": int(result.candidate_faces),
                "selected_faces": int(result.selected_faces),
                "adaptive_faces": int(result.adaptive_faces),
                "total_leaves": int(result.total_leaves),
                "budget_limited": bool(result.budget_limited),
            }
        return snapshot

    def run_auto_shading(
        self,
        quality: str,
        dither_strength: float,
        boundary_only: bool,
    ) -> dict[str, Any]:
        """Generate and atomically commit automatic trees on the paint worker."""

        try:
            if self._session is None or self._auto_colors is None:
                raise RuntimeError("色修正の準備中です")
            store = getattr(self, "_hotfix_tree_store", None)
            if not isinstance(store, dict):
                store = _ensure_store(self.prepared)
            current_states = np.asarray(
                self._session.effective_indices(), dtype=np.int8
            )
            scope = _auto_shading_face_mask(
                self._session,
                store,
                boundary_only=bool(boundary_only),
            )
            if not bool(np.any(scope)):
                return auto_shading_snapshot(
                    self,
                    "手描き修正を除く陰影補正対象がありません",
                )

            palette = editor_palette(self)
            try:
                scope &= np.asarray(self._active_face_mask(), dtype=bool)
            except (AttributeError, IndexError, ValueError):
                pass
            palette_rgb = _palette_rgb(palette, mixer_module)
            options = _auto_shading_options(
                quality,
                height_mm=float(self.settings.geometry.height_mm),
                enabled_states=palette.enabled_states,
                dither_strength=dither_strength,
            )
            shading_result = auto_shading.generate_auto_shading(
                np.asarray(self.level.faces),
                np.asarray(self.level.vertices_unit),
                np.asarray(self._auto_colors.tone_vertex_rgb),
                current_states,
                palette_rgb,
                options=options,
                face_mask=scope,
            )
            if not shading_result.trees:
                return auto_shading_snapshot(
                    self,
                    "補正できる面内グラデーションは見つかりませんでした",
                    result=shading_result,
                )

            invalid_roots = [
                int(face)
                for face in shading_result.trees
                if not (0 <= int(face) < len(scope) and bool(scope[int(face)]))
            ]
            if invalid_roots:
                raise RuntimeError("陰影計算が保護対象の面を変更しようとしました")

            changed_roots = np.asarray(
                sorted(int(face) for face in shading_result.trees),
                dtype=np.int32,
            )
            before_values = np.asarray(
                self._session.overrides[changed_roots], dtype=np.int8
            ).copy()
            tree_keys = set(int(face) for face in changed_roots)
            before_nodes = _clone_store_subset(store, tree_keys)
            # The generator hands these fresh nodes to this store.  Keep one
            # live copy here; _attach_tree_history makes the independent Undo
            # snapshot needed before later brush edits may mutate a tree.
            after_nodes = {
                int(face): shading_result.trees[int(face)]
                for face in changed_roots
            }
            after_values = np.asarray(
                [after_nodes[int(face)].dominant_state() for face in changed_roots],
                dtype=np.int8,
            )

            try:
                self._session.overrides[changed_roots] = after_values
                for face, node in after_nodes.items():
                    store[int(face)] = node
                command = paint_module.PaintCommand(
                    changed_roots,
                    before_values,
                    after_values.copy(),
                    "面内グラデーション補正",
                )
                _attach_tree_history(
                    command,
                    tree_keys,
                    before_nodes,
                    after_nodes,
                )
                self._session._push_command(command)
            except Exception:
                self._session.overrides[changed_roots] = before_values
                _restore_tree_snapshot(store, tree_keys, before_nodes)
                raise

            _bump_revision(self._hotfix_tree_owner)
            # The original snapshot consumer appends ``changed`` as
            # ``（N面）``.  Keep the message itself count-free so the status
            # bar does not display the same face count twice.
            label = "面内グラデーションを生成しました"
            if shading_result.budget_limited:
                label += "・品質上限内で適用"
            snapshot = self._worker_refresh_after_edit(
                label,
                len(changed_roots),
            )
            if not isinstance(snapshot, dict):
                snapshot = {"message": label, "changed": len(changed_roots)}
            snapshot["_hotfix_auto_shading_done"] = True
            snapshot["_hotfix_auto_shading_stats"] = {
                "candidate_faces": int(shading_result.candidate_faces),
                "selected_faces": int(shading_result.selected_faces),
                "adaptive_faces": int(shading_result.adaptive_faces),
                "total_leaves": int(shading_result.total_leaves),
                "budget_limited": bool(shading_result.budget_limited),
            }
            return snapshot
        except Exception as exc:
            details = f"{type(exc).__name__}: {exc}"
            return auto_shading_snapshot(
                self,
                "陰影の自動補正を適用できませんでした",
                error=details,
            )

    def queue_auto_shading(self) -> None:
        if bool(getattr(self, "_close_requested", False)):
            return
        if bool(getattr(self, "_hotfix_auto_shading_active", False)):
            self.status_var.set("陰影の自動補正を処理中です…")
            return

        self._commit_active_stroke()
        flush_smooth_batch(self)
        quality_label = str(self._hotfix_auto_shading_quality_var.get())
        quality = _AUTO_SHADING_QUALITY_LABELS.get(quality_label, "standard")
        strength = float(
            np.clip(
                float(self._hotfix_auto_shading_strength_var.get()),
                0.0,
                100.0,
            )
        ) / 100.0
        boundary_only = bool(self._hotfix_auto_shading_boundary_var.get())
        self._hotfix_auto_shading_active = True
        button = getattr(self, "_hotfix_auto_shading_button", None)
        if button is not None:
            button.configure(state="disabled")
        self.status_var.set("面内グラデーションを生成しています…")
        try:
            self._submit(
                "edit",
                lambda: run_auto_shading(
                    self,
                    quality,
                    strength,
                    boundary_only,
                ),
            )
        except Exception:
            self._hotfix_auto_shading_active = False
            if button is not None:
                button.configure(state="normal")
            raise

    def process_smooth_request(
        self, request: _SmoothStrokeRequest
    ) -> _SmoothStrokeResult:
        """Apply one immutable gesture on the editor worker thread."""

        if self._session is None:
            raise RuntimeError("色修正の準備中です")
        capture = request.capture
        store = self._hotfix_tree_store
        ids = np.asarray(capture.face_ids, dtype=np.int32)
        render_size = (ids.shape[1], ids.shape[0])
        mvp, _clean_camera, computed_ppu = renderer_module._orbit_camera_mvp(
            self.level.vertices_unit, render_size, capture.camera
        )
        ppu = float(computed_ppu or capture.pixels_per_unit or 1.0)
        height_mm = max(float(capture.height_mm), 1.0e-9)
        radius_px = max(1.25, float(capture.radius_mm) / height_mm * ppu)
        min_edge_px = max(0.65, 0.05 / height_mm * ppu)
        is_airbrush = capture.tool == "airbrush" or capture.shape == "airbrush"
        variable_radius = capture.shape == "pressure_taper" or is_airbrush
        if variable_radius:
            request_scales = request.radius_scales
            if request_scales is None:
                request_scales = tuple(1.0 for _point in request.points)
            raw_render_points, raw_radius_scales = _canvas_profile_to_render(
                request.points,
                request_scales,
                capture.mapping,
            )
            # The UI thread already simplified the immutable point/width
            # profile used to redraw feedback.  Preserve those exact segment
            # pairs here so the pending overlay and final geometry agree.
            render_points = raw_render_points
            render_radius_scales = raw_radius_scales
        else:
            raw_render_points = _canvas_to_render(request.points, capture.mapping)
            render_points = _simplify_polyline(raw_render_points, tolerance=0.65)
            render_radius_scales = [1.0] * len(render_points)
        if len(render_points) < 2:
            return _SmoothStrokeResult(
                request.feedback_token,
                current_tree_revision(self),
                0,
                "筆跡はありません",
            )

        if variable_radius:
            segment_radii = np.asarray(
                [
                    max(
                        0.65,
                        radius_px
                        * 0.5
                        * (render_radius_scales[index] + render_radius_scales[index + 1]),
                    )
                    for index in range(len(render_points) - 1)
                ],
                dtype=np.float64,
            )
        else:
            segment_radii = np.full(
                len(render_points) - 1, radius_px, dtype=np.float64
            )
        segment_candidates: list[np.ndarray] = []
        candidate_union: set[int] = set()
        center_seeds: set[int] = set()
        for point in raw_render_points:
            seed = _point_face(ids, point)
            if seed >= 0:
                center_seeds.add(seed)
        for segment_index, (start, end) in enumerate(
            zip(render_points, render_points[1:])
        ):
            candidates = _segment_face_ids(
                ids,
                start,
                end,
                float(segment_radii[segment_index]),
            )
            segment_candidates.append(candidates)
            candidate_union.update(int(value) for value in candidates)
        allowed_face_mask = np.asarray(
            getattr(
                self._session,
                "allowed_face_mask",
                np.ones(len(self.level.faces), dtype=bool),
            ),
            dtype=bool,
        )
        if allowed_face_mask.shape == (len(self.level.faces),):
            candidate_union = {
                face
                for face in candidate_union
                if 0 <= face < len(allowed_face_mask) and allowed_face_mask[face]
            }
        if capture.protect_edges:
            allowed = _edge_guard_faces(
                self._session,
                candidate_union,
                center_seeds,
                capture.edge_angle_degrees,
            )
        else:
            allowed = candidate_union
        if not allowed:
            return _SmoothStrokeResult(
                request.feedback_token,
                current_tree_revision(self),
                0,
                "筆跡はありません",
            )

        automatic = np.asarray(self._session.auto_indices, dtype=np.int8)
        faces, vertices = _stroke_geometry_arrays(self._session, self.level)
        segment_pairs = tuple(zip(render_points, render_points[1:]))
        segments_xy = np.asarray(segment_pairs, dtype=np.float64)
        face_segment_indices: dict[int, list[int]] = {}
        for segment_index, candidates in enumerate(segment_candidates):
            for raw_face in candidates:
                face = int(raw_face)
                if face not in allowed or face < 0 or face >= len(faces):
                    continue
                face_segment_indices.setdefault(face, []).append(segment_index)

        # A screen-space stroke normally reaches only a tiny fraction of a
        # large mesh.  Read effective states for those candidate roots only;
        # materialising the complete face-state array here made every release
        # proportional to the whole OBJ before adaptive painting even began.
        process_faces, effective_states = _effective_states_for_face_mapping(
            self._session,
            face_segment_indices,
        )
        effective_by_face = {
            int(face): int(state)
            for face, state in zip(process_faces, effective_states, strict=True)
        }

        working: dict[int, smooth_paint.PaintNode] = {}
        for raw_face, effective_state in zip(
            process_faces,
            effective_states,
            strict=True,
        ):
            face = int(raw_face)
            segment_indices = face_segment_indices[face]
            existing = store.get(face)
            requested = (
                int(automatic[face])
                if capture.erase
                else int(capture.selected_state)
            )
            # Repainting an already uniform root cannot change its adaptive
            # tree.  Skip projection and depth-six relation tests entirely;
            # this is especially important when a user repeatedly traces the
            # same correction while refining an edge.
            if existing is None and int(effective_state) == requested:
                continue
            if (
                existing is not None
                and existing.is_leaf
                and int(existing.state) == requested
            ):
                continue
            node = (
                existing.clone()
                if existing is not None
                else smooth_paint.PaintNode(int(effective_state))
            )
            projected_geometry = _project_points(
                vertices[faces[face]], mvp, render_size
            )
            face_segments = segments_xy[
                np.asarray(segment_indices, dtype=np.intp)
            ]
            if is_airbrush:
                palette_rgb = np.asarray(capture.palette_rgb, dtype=np.float64)
                if palette_rgb.ndim != 2 or palette_rgb.shape[1:] != (3,):
                    continue
                enabled = np.asarray(capture.enabled_states, dtype=bool)
                try:
                    layers = airbrush_state_layers(
                        int(node.dominant_state()),
                        int(capture.selected_state),
                        palette_rgb,
                        enabled,
                        strength=float(capture.airbrush_strength),
                        pressure=float(request.pressure),
                        dab_count=max(1, int(request.dab_count)),
                    )
                except Exception:
                    layers = ()
                selected_segment_indices = np.asarray(
                    segment_indices, dtype=np.intp
                )
                layer_result = (
                    smooth_paint.apply_layered_variable_capsule_segments(
                        node,
                        projected_geometry,
                        face_segments,
                        segment_radii[selected_segment_indices],
                        layers,
                        max_depth=smooth_paint.MAX_DEPTH,
                        min_edge_pixels=min_edge_px,
                        boundary_rule="center",
                    )
                )
                any_changed = bool(layer_result.changed)
                paint_result = None
            elif capture.shape == "marker":
                paint_result = smooth_paint.apply_marker_segments(
                    node,
                    projected_geometry,
                    face_segments,
                    radius_px * 2.0,
                    requested,
                    thickness=max(1.0, radius_px * 2.0 * 0.25),
                    angle_degrees=None,
                    max_depth=smooth_paint.MAX_DEPTH,
                    min_edge_pixels=min_edge_px,
                    boundary_rule="center",
                )
            elif variable_radius:
                selected_segment_indices = np.asarray(
                    segment_indices, dtype=np.intp
                )
                paint_result = smooth_paint.apply_variable_capsule_segments(
                    node,
                    projected_geometry,
                    face_segments,
                    segment_radii[selected_segment_indices],
                    requested,
                    max_depth=smooth_paint.MAX_DEPTH,
                    min_edge_pixels=min_edge_px,
                    boundary_rule="center",
                )
            else:
                paint_result = smooth_paint.apply_capsule_segments(
                    node,
                    projected_geometry,
                    face_segments,
                    radius_px,
                    requested,
                    max_depth=smooth_paint.MAX_DEPTH,
                    min_edge_pixels=min_edge_px,
                    boundary_rule="center",
                )
            if (any_changed if is_airbrush else bool(paint_result.changed)):
                working[face] = node

        changed_roots: list[int] = []
        before_nodes: dict[int, smooth_paint.PaintNode] = {}
        after_nodes: dict[int, smooth_paint.PaintNode] = {}
        final_uniform: dict[int, int] = {}
        for face, node in working.items():
            node.collapse()
            existing = store.get(face)
            before_code = (
                smooth_paint.encode_paint_color(existing)
                if existing is not None
                else smooth_paint.encode_paint_color(
                    smooth_paint.PaintNode(effective_by_face[face])
                )
            )
            after_code = smooth_paint.encode_paint_color(node)
            if before_code == after_code:
                continue
            changed_roots.append(face)
            if existing is not None:
                before_nodes[face] = existing.clone()
            if node.is_leaf:
                final_uniform[face] = int(node.state)
            else:
                after_nodes[face] = node.clone()
        if not changed_roots:
            return _SmoothStrokeResult(
                request.feedback_token,
                current_tree_revision(self),
                0,
                "色は変わりませんでした",
            )

        changed_roots.sort()
        indices = np.asarray(changed_roots, dtype=np.int32)
        before_values = np.asarray(
            self._session.overrides[indices], dtype=np.int8
        ).copy()
        after_values = np.empty(len(indices), dtype=np.int8)
        tree_keys = set(changed_roots)
        try:
            for offset, face in enumerate(changed_roots):
                if face in after_nodes:
                    store[face] = after_nodes[face].clone()
                    after_values[offset] = after_nodes[face].dominant_state()
                else:
                    store.pop(face, None)
                    uniform = int(final_uniform[face])
                    after_values[offset] = (
                        -1 if uniform == int(automatic[face]) else uniform
                    )
            self._session.overrides[indices] = after_values
            command = paint_module.PaintCommand(
                indices,
                before_values,
                after_values.copy(),
                (
                    "滑らか消去ブラシ"
                    if capture.erase
                    else "滑らかエアブラシ"
                    if is_airbrush
                    else "滑らかブラシ"
                ),
            )
            _attach_tree_history(command, tree_keys, before_nodes, after_nodes)
            self._session._push_command(command)
        except Exception:
            self._session.overrides[indices] = before_values
            _restore_tree_snapshot(store, tree_keys, before_nodes)
            raise

        _bump_revision(self._hotfix_tree_owner)
        if capture.erase:
            label = "滑らかブラシで自動色へ戻しました"
        elif is_airbrush:
            label = f"色 {capture.selected_state + 1} をエアブラシで重ねました"
        else:
            if capture.shape == "marker":
                nib = "マーカー"
            elif capture.shape == "pressure_taper":
                nib = "筆圧ペン" if request.width_source == "pressure" else "先細りペン"
            else:
                nib = "滑らか"
            label = f"色 {capture.selected_state + 1} で{nib}に塗りました"
        return _SmoothStrokeResult(
            request.feedback_token,
            current_tree_revision(self),
            len(indices),
            label,
        )

    def run_smooth_batch(self, batch: _StrokeBatch):
        results = _drain_stroke_batch(
            batch,
            lambda request: process_smooth_request(self, request),
            lambda: current_tree_revision(self),
        )
        changed = sum(result.changed_roots for result in results)
        failed = [result for result in results if result.error]
        succeeded = len(results) - len(failed)
        if failed:
            label = f"{succeeded}筆を確定、{len(failed)}筆を処理できませんでした"
        elif len(results) > 1:
            label = f"{len(results)}筆を順番に確定しました"
        elif results:
            label = results[0].label
        else:
            label = "筆跡はありません"

        snapshot = self._worker_refresh_after_edit(label, changed)
        if isinstance(snapshot, dict):
            snapshot["_hotfix_smooth_commits"] = tuple(
                (int(result.feedback_token), int(result.revision))
                for result in results
                if result.feedback_token is not None
            )
            snapshot["_hotfix_smooth_batch_id"] = int(batch.serial)
            snapshot["_hotfix_smooth_stroke_count"] = len(results)
            snapshot["_hotfix_smooth_tree_revision"] = current_tree_revision(self)
            if failed:
                snapshot["_hotfix_smooth_errors"] = tuple(
                    result.error for result in failed
                )
        return snapshot

    def flush_smooth_batch(self, *, wait_for_release: bool = False) -> None:
        after_id = getattr(self, "_hotfix_stroke_debounce_after", None)
        self._hotfix_stroke_debounce_after = None
        if after_id is not None:
            try:
                self.window.after_cancel(after_id)
            except Exception:
                pass
        if wait_for_release and getattr(self, "_drag_mode", None) in (
            "stroke",
            "airbrush-stroke",
        ):
            restart_stroke_debounce(self)
            return
        batch = getattr(self, "_hotfix_pending_stroke_batch", None)
        if batch is None:
            return
        self._hotfix_pending_stroke_batch = None
        batch.seal()
        self._submit(
            "edit", lambda batch=batch: run_smooth_batch(self, batch)
        )

    def enqueue_smooth_request(self, request: _SmoothStrokeRequest) -> None:
        batch = getattr(self, "_hotfix_pending_stroke_batch", None)
        if batch is None or not batch.append(request):
            self._hotfix_stroke_batch_serial += 1
            batch = _StrokeBatch(self._hotfix_stroke_batch_serial)
            if not batch.append(request):
                raise RuntimeError("筆跡キューを開始できませんでした")
            self._hotfix_pending_stroke_batch = batch
        restart_stroke_debounce(self)

    def commit_stroke_smooth(self):
        points = getattr(self, "_hotfix_smooth_points", None)
        capture = getattr(self, "_hotfix_smooth_capture", None)
        drag_mode = getattr(self, "_drag_mode", None)
        if drag_mode == "airbrush-stroke":
            cancel_airbrush_preview(self)
        if (
            drag_mode in ("stroke", "airbrush-stroke")
            and points
            and capture is not None
        ):
            is_airbrush = capture.tool == "airbrush" or capture.shape == "airbrush"
            feedback = getattr(self, "_hotfix_active_feedback", None)
            token = feedback.get("token") if isinstance(feedback, dict) else None
            point_values = tuple((float(x), float(y)) for x, y in points)
            if capture.shape == "pressure_taper":
                raw_pressures = getattr(self, "_hotfix_smooth_pressures", None)
                pressures = (
                    tuple(raw_pressures)
                    if isinstance(raw_pressures, (list, tuple))
                    and len(raw_pressures) == len(point_values)
                    else tuple(None for _point in point_values)
                )
                radius_scales, width_source = pressure_or_taper_scales(
                    point_values,
                    pressures,
                    base_radius_pixels=float(capture.feedback_radius_pixels),
                )
                augmented = [
                    np.asarray(
                        (
                            point[0],
                            point[1],
                            radius_scales[index]
                            * max(float(capture.feedback_radius_pixels), 4.0),
                        ),
                        dtype=np.float64,
                    )
                    for index, point in enumerate(point_values)
                ]
                keep_indices = _simplify_polyline_indices(
                    augmented, tolerance=0.65
                )
                point_values = tuple(point_values[index] for index in keep_indices)
                radius_scales = tuple(
                    radius_scales[index] for index in keep_indices
                )
                airbrush_pressure = 1.0
                dab_count = 1
            elif is_airbrush:
                raw_pressures = getattr(self, "_hotfix_smooth_pressures", None)
                has_native_pressure = bool(
                    isinstance(raw_pressures, (list, tuple))
                    and any(value is not None for value in raw_pressures)
                )
                if (
                    isinstance(raw_pressures, (list, tuple))
                    and len(raw_pressures) == len(point_values)
                ):
                    pressure_values = tuple(
                        1.0 if value is None else float(value)
                        for value in raw_pressures
                    )
                else:
                    pressure_values = tuple(1.0 for _point in point_values)
                raw_scales = getattr(self, "_hotfix_smooth_radius_scales", None)
                if (
                    isinstance(raw_scales, (list, tuple))
                    and len(raw_scales) == len(point_values)
                ):
                    radius_scales = tuple(float(value) for value in raw_scales)
                else:
                    radius_scales = tuple(
                        airbrush_radius_scale(value) for value in pressure_values
                    )
                # A stationary held pen is a real circular dab.  Represent it as
                # a zero-length capsule so feedback and adaptive commit share the
                # exact same geometry path.
                if len(point_values) == 1:
                    point_values = (point_values[0], point_values[0])
                    pressure_values = (pressure_values[0], pressure_values[0])
                    radius_scales = (radius_scales[0], radius_scales[0])
                elif len(point_values) > 2:
                    augmented = [
                        np.asarray(
                            (
                                point[0],
                                point[1],
                                radius_scales[index]
                                * max(float(capture.feedback_radius_pixels), 4.0),
                            ),
                            dtype=np.float64,
                        )
                        for index, point in enumerate(point_values)
                    ]
                    keep_indices = _simplify_polyline_indices(
                        augmented, tolerance=0.65
                    )
                    point_values = tuple(point_values[index] for index in keep_indices)
                    pressure_values = tuple(
                        pressure_values[index] for index in keep_indices
                    )
                    radius_scales = tuple(
                        radius_scales[index] for index in keep_indices
                    )
                airbrush_pressure = _arc_length_weighted_pressure(
                    point_values,
                    pressure_values,
                )
                started_at = getattr(self, "_airbrush_started_at", None)
                duration = (
                    max(0.0, time.monotonic() - float(started_at))
                    if started_at is not None
                    else 0.0
                )
                dab_count = airbrush_hold_dab_count(duration)
                width_source = "pressure" if has_native_pressure else "fixed"
            else:
                radius_scales = tuple(1.0 for _point in point_values)
                width_source = "fixed"
                airbrush_pressure = 1.0
                dab_count = 1
            if isinstance(feedback, dict):
                feedback["points"] = list(point_values)
                feedback["radius_scales"] = list(radius_scales)
                feedback["width_source"] = width_source
                if is_airbrush:
                    feedback["airbrush_dab_count"] = dab_count
                    feedback["airbrush_pressure"] = airbrush_pressure
                    feedback["airbrush_opacities"] = airbrush_preview_opacities(
                        self,
                        capture,
                        airbrush_pressure,
                        dab_count,
                    )
                # Finalize the pending Canvas overlay from the exact same
                # immutable profile that the worker will consume.
                redraw_pending_feedback(self)
            request = _SmoothStrokeRequest(
                points=point_values,
                capture=capture,
                feedback_token=int(token) if token is not None else None,
                radius_scales=radius_scales,
                width_source=width_source,
                pressure=airbrush_pressure,
                dab_count=dab_count,
            )
            enqueue_smooth_request(self, request)
            if is_airbrush:
                # Airbrush processing is already local to the touched render
                # crop.  Start it immediately on release instead of waiting for
                # the generic 300 ms multi-stroke debounce.
                flush_smooth_batch(self)
            self._drag_mode = None
            self._stroke_faces.clear()
            self._hotfix_smooth_points = None
            self._hotfix_smooth_pressures = None
            self._hotfix_smooth_radius_scales = None
            self._hotfix_smooth_capture = None
            self._hotfix_active_feedback = None
            self._airbrush_started_at = None
            return None
        return original_commit_stroke(self)

    def mark_snapshot_feedback(
        self,
        value: Any,
        *,
        base_image: Image.Image | None,
    ) -> None:
        """Mark accepted gestures only after snapshot state has been consumed.

        ``original_consume_snapshot`` updates effective/undo state and draws
        the current frame.  Marking before it allowed ``draw_canvas_smooth`` to
        remove the airbrush guide while that frame was still the pre-edit base.
        The guide now survives until a different exact rendered image proves
        the committed tree revision is actually visible.
        """

        if not isinstance(value, dict):
            return
        commits = value.get("_hotfix_smooth_commits")
        if commits is not None:
            for token, revision in commits:
                _mark_feedback_committed(
                    getattr(self, "_hotfix_pending_feedback", []),
                    int(token),
                    base_image=base_image,
                    revision=int(revision),
                )
        token = value.get("_hotfix_smooth_commit_token")
        if token is not None:  # compatibility with pre-pipeline snapshots
            _mark_feedback_committed(
                getattr(self, "_hotfix_pending_feedback", []),
                int(token),
                base_image=base_image,
                revision=int(
                    value.get(
                        "_hotfix_smooth_tree_revision",
                        getattr(
                            self._hotfix_tree_owner,
                            "_hotfix_tree_revision",
                            0,
                        ),
                    )
                ),
            )
        # A future compatibility path may deliver the exact frame in the edit
        # snapshot itself. Re-run Canvas presentation after marking so that
        # such a frame can retire the guide immediately and safely.
        if getattr(self, "target_image", None) is not base_image:
            self._draw_canvas()

    def consume_snapshot_smooth(self, value):
        base_image = getattr(self, "target_image", None)
        if isinstance(value, dict):
            if value.get("_hotfix_auto_shading_done"):
                self._hotfix_auto_shading_active = False
                button = getattr(self, "_hotfix_auto_shading_button", None)
                if button is not None and not bool(
                    getattr(self, "_close_requested", False)
                ):
                    try:
                        button.configure(state="normal")
                    except Exception:
                        pass
                error = value.get("_hotfix_auto_shading_error")
                if error and not bool(getattr(self, "_close_requested", False)):
                    try:
                        paint_gui.messagebox.showerror(
                            "面内グラデーションを生成できません",
                            str(error),
                            parent=self.window,
                        )
                    except Exception:
                        pass
        defer_render = bool(
            isinstance(value, dict)
            and value.get("_hotfix_smooth_commits") is not None
            and (
                getattr(self, "_drag_mode", None) == "stroke"
                or getattr(self, "_hotfix_pending_stroke_batch", None) is not None
            )
        )
        if not defer_render:
            if (
                isinstance(value, dict)
                and value.get("_hotfix_smooth_commits") is not None
            ):
                self._hotfix_deferred_paint_render = False
            result = original_consume_snapshot(self, value)
            mark_snapshot_feedback(self, value, base_image=base_image)
            return result

        # Batch A may finish while the user is already drawing/debouncing B.
        # Suppress A's automatic render; B's final snapshot will refresh the
        # latest revision once the user actually pauses.
        self._hotfix_deferred_paint_render = True
        had_override = "_schedule_render" in self.__dict__
        previous = self.__dict__.get("_schedule_render")
        self._schedule_render = lambda *args, **kwargs: None
        try:
            result = original_consume_snapshot(self, value)
        finally:
            if had_override:
                self._schedule_render = previous
            else:
                del self.__dict__["_schedule_render"]
        mark_snapshot_feedback(self, value, base_image=base_image)
        return result

    def barrier_then(self, original, *args, **kwargs):
        self._commit_active_stroke()
        flush_smooth_batch(self)
        return original(self, *args, **kwargs)

    def undo_smooth(self, *args, **kwargs):
        return barrier_then(self, original_editor_undo, *args, **kwargs)

    def redo_smooth(self, *args, **kwargs):
        return barrier_then(self, original_editor_redo, *args, **kwargs)

    def clear_smooth(self, *args, **kwargs):
        return barrier_then(self, original_editor_clear, *args, **kwargs)

    def queue_fill_smooth(self, *args, **kwargs):
        return barrier_then(self, original_queue_fill, *args, **kwargs)

    def queue_boundary_smooth(self, *args, **kwargs):
        return barrier_then(self, original_queue_smooth, *args, **kwargs)

    def close_smooth(self, *args, **kwargs):
        cancel_airbrush_preview(self)
        bridge = getattr(self, "_hotfix_pen_pressure_bridge", None)
        if bridge is not None:
            try:
                bridge.close()
            except Exception:
                pass
        update_pressure_status(self)
        return barrier_then(self, original_editor_close, *args, **kwargs)

    def set_language_smooth(self, language: str):
        current_label = str(self._hotfix_auto_shading_quality_var.get())
        current_code = _AUTO_SHADING_QUALITY_LABELS.get(
            current_label, "standard"
        )
        result = original_editor_set_language(self, language)
        values = tuple(
            self.i18n.text(f"paint.auto_quality_{code}")
            for code in ("fast", "standard", "high")
        )
        selector = getattr(self, "_hotfix_auto_shading_quality_selector", None)
        if selector is not None:
            selector.configure(values=values)
        code_index = {"fast": 0, "standard": 1, "high": 2}
        self._hotfix_auto_shading_quality_var.set(
            values[code_index.get(current_code, 1)]
        )
        update_pressure_status(self)
        return result

    def reset_adaptive_geometry_context(
        self, prepared, *, preserve: bool = False
    ) -> None:
        """Move adaptive/GPU routing to a replacement joint topology."""

        cancel_airbrush_preview(self)
        store = _register_level(prepared)
        if not preserve and store:
            store.clear()
            _bump_revision(prepared)
        self._hotfix_tree_store = store
        self._hotfix_tree_owner = prepared
        _configure_gpu_palette_routing(self.settings, prepared.final)
        self._hotfix_overlay_cache = None
        self._hotfix_pending_feedback = []
        self._hotfix_active_feedback = None
        self._hotfix_smooth_points = None
        self._hotfix_smooth_pressures = None
        self._hotfix_smooth_radius_scales = None
        self._hotfix_smooth_capture = None

    def flush_pending_paint(self) -> None:
        self._commit_active_stroke()
        flush_smooth_batch(self)

    def draw_canvas_smooth(self):
        store = getattr(self, "_hotfix_tree_store", None)
        image = getattr(self, "target_image", None)
        ids = getattr(self, "face_ids", None)
        exact_pick = getattr(self, "_hotfix_pick_camera", None) == self.camera
        active_rotation = bool(getattr(self, "_rotation_hotfix_active", False))
        revision = int(getattr(self._hotfix_tree_owner, "_hotfix_tree_revision", 0))
        gpu_revision = _gpu_overlay_revision(image)
        visibility_filtered = bool(
            image is not None
            and image.info.get(_VISIBILITY_FACE_MODES_INFO_KEY) is not None
        )
        exact_frame = bool(
            image is not None and ids is not None and exact_pick and not active_rotation
        )
        cpu_overlay_presented = False

        # The visibility renderer intentionally shows adaptive roots by their
        # dominant base colour while a part is transparent/hidden.  Rebuilding
        # the old CPU overlay here would be costly on large manual jobs and
        # could make a transparent root opaque.  Returning every part to
        # Visible immediately restores the persistent GPU detail pass.
        if store and exact_frame and gpu_revision is None and not visibility_filtered:
            cached = getattr(self, "_hotfix_overlay_cache", None)
            if not _overlay_cache_matches(cached, image, ids, self.camera, revision):
                composite = compose_target_image(
                    image,
                    self.level,
                    store,
                    camera=self.camera,
                    face_ids=ids,
                    palette=self.settings.palette,
                    part_palette_rgb_tables=(
                        part_palette_module.build_part_palette_rgb_tables(
                            self.settings, self.level
                        )
                    ),
                    face_part_ids=self.level.face_part_ids,
                    focus_state=(
                        int(self._palette_usage_focus_state)
                        if bool(
                            getattr(
                                self,
                                "_palette_usage_focus_enabled",
                                False,
                            )
                        )
                        else None
                    ),
                    focus_part_id=int(self.active_part_id),
                    renderer_module=renderer_module,
                    mixer_module=mixer_module,
                )
                # Hold strong references to the precise source frame and ID
                # map so object-id reuse cannot select a stale composite.
                cached = (image, ids, self.camera, revision, composite)
                self._hotfix_overlay_cache = cached
            cpu_overlay_presented = True
            self.target_image = cached[4]
            try:
                result = original_draw_canvas(self)
            finally:
                self.target_image = image
        else:
            result = original_draw_canvas(self)

        pending = getattr(self, "_hotfix_pending_feedback", None)
        if isinstance(pending, list) and pending:
            # A GPU frame proves which tree revision its pixels contain.  The
            # CPU fallback is built synchronously from the current store.  Do
            # not clear feedback for an older marked frame even if its camera
            # is exact, otherwise a just-painted area visibly reverts until the
            # next render.
            if gpu_revision is not None:
                presented_revision = gpu_revision
                paint_frame_is_exact = bool(
                    exact_frame and gpu_revision >= revision
                )
            else:
                presented_revision = revision
                paint_frame_is_exact = bool(
                    exact_frame
                    and (not store or cpu_overlay_presented or visibility_filtered)
                )
            pending[:] = [
                entry
                for entry in pending
                if not _feedback_has_final_frame(
                    entry,
                    image=image,
                    revision=presented_revision,
                    exact_frame=paint_frame_is_exact,
                )
            ]
            # Any interim/stale render can rebuild the Canvas, including a
            # render that was already in flight when the stroke was queued.
            # Repaint feedback until an exact post-commit frame replaces it.
            redraw_pending_feedback(self)
        return result

    editor_class.__init__ = editor_init_smooth
    editor_class._worker_initialize = worker_initialize_smooth
    editor_class._on_left_press = left_press_smooth
    editor_class._on_left_motion = left_motion_smooth
    if original_right_press is not None:
        editor_class._on_right_press = right_press_smooth
    if original_middle_press is not None:
        editor_class._on_middle_press = middle_press_smooth
    if original_schedule_render is not None:
        editor_class._schedule_render = schedule_render_smooth
    editor_class._commit_active_stroke = commit_stroke_smooth
    editor_class._consume_snapshot = consume_snapshot_smooth
    editor_class._draw_canvas = draw_canvas_smooth
    editor_class._undo = undo_smooth
    editor_class._redo = redo_smooth
    editor_class._clear_all = clear_smooth
    editor_class._queue_fill = queue_fill_smooth
    editor_class._queue_smooth = queue_boundary_smooth
    editor_class._queue_auto_shading = queue_auto_shading
    editor_class._run_auto_shading = run_auto_shading
    editor_class._reset_adaptive_geometry_context = (
        reset_adaptive_geometry_context
    )
    editor_class._flush_pending_paint = flush_pending_paint
    editor_class.close = close_smooth
    editor_class.set_language = set_language_smooth
    editor_class._smooth_paint_hotfix_applied = True
    return editor_class


__all__ = [
    "_auto_shading_face_mask",
    "_auto_shading_options",
    "apply_smooth_paint_hotfix",
    "compose_target_image",
    "lookup_tree_context",
]
