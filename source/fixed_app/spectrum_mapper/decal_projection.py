"""Screen-space decal projection for the Manual Editing workspace.

The renderer's exact face-ID buffer is the authority for visibility.  A decal
is transformed in render pixels, clipped to the active/visible surface, and
then converted to the already configured Full Spectrum palette states.  Bake
planning is read-only; :func:`commit_decal_bake` is the single atomic history
boundary and uses the same sparse adaptive triangle trees as smooth painting.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping

import numpy as np
from PIL import Image

import smooth_paint

from . import renderer as renderer_module
from .decal_image import DecalImage
from .engine import srgb_to_lab
from .models import MeshLevel
from .paint import PaintCommand, PaintSession


DecalMode = Literal["image", "selected"]
ProgressCallback = Callable[[str, float], None]
CancelCallback = Callable[[], bool]


class DecalProjectionError(ValueError):
    """A decal cannot be projected or committed safely."""


class DecalProjectionCancelled(DecalProjectionError):
    """The caller cancelled a potentially expensive bake plan."""


class DecalStalePreviewError(DecalProjectionError):
    """The camera, render generation, mesh, or paint state changed."""


@dataclass(frozen=True, slots=True)
class DecalTransform:
    """One image transform in top-left-origin render pixels."""

    center_xy: tuple[float, float]
    width_px: float
    rotation_degrees: float = 0.0
    flip_x: bool = False
    flip_y: bool = False
    opacity: float = 1.0

    def __post_init__(self) -> None:
        if len(self.center_xy) != 2 or not all(
            math.isfinite(float(value)) for value in self.center_xy
        ):
            raise DecalProjectionError("デカール中心座標が不正です")
        if not math.isfinite(float(self.width_px)) or float(self.width_px) <= 0.0:
            raise DecalProjectionError("デカール幅は0より大きくしてください")
        if not math.isfinite(float(self.rotation_degrees)):
            raise DecalProjectionError("デカール回転角が不正です")
        if not math.isfinite(float(self.opacity)) or not 0.0 <= float(self.opacity) <= 1.0:
            raise DecalProjectionError("デカール不透明度は0～1で指定してください")


@dataclass(frozen=True, slots=True)
class DecalPreviewMetrics:
    footprint_pixels: int
    opaque_pixels: int
    eligible_pixels: int
    clipped_pixels: int
    candidate_faces: int
    support_faces: int
    mean_delta_e76: float
    p90_delta_e76: float


@dataclass(frozen=True, slots=True)
class DecalPreview:
    """Immutable placement preview tied to one exact face-ID generation."""

    overlay_rgba: np.ndarray
    quantized_overlay_rgba: np.ndarray
    state_map: np.ndarray
    face_ids: np.ndarray
    candidate_faces: np.ndarray
    support_faces: np.ndarray
    anchor_face: int
    frame_generation: int | None
    transform: DecalTransform
    mode: DecalMode
    metrics: DecalPreviewMetrics


@dataclass(frozen=True, slots=True)
class DecalBakePlan:
    """Read-only adaptive-tree proposal ready for an atomic commit."""

    mesh_fingerprint: str
    frame_generation: int | None
    camera_signature: tuple[object, ...]
    face_indices: np.ndarray
    expected_overrides: np.ndarray
    expected_tree_codes: Mapping[int, str | None]
    nodes_by_face: Mapping[int, smooth_paint.PaintNode]
    protected_faces: int
    disconnected_faces: int
    adaptive_roots: int
    total_nodes: int
    target_pixels: int


@dataclass(frozen=True, slots=True)
class DecalBakeResult:
    changed_faces: np.ndarray
    adaptive_roots: int
    uniform_roots: int
    target_pixels: int
    command: PaintCommand | None = field(default=None, repr=False, compare=False)


def decal_width_mm_to_pixels(
    width_mm: float,
    model_height_mm: float,
    pixels_per_unit: float,
) -> float:
    """Convert a physical decal width to the renderer's current pixel scale."""

    width = float(width_mm)
    height = float(model_height_mm)
    ppu = float(pixels_per_unit)
    if not all(math.isfinite(value) for value in (width, height, ppu)):
        raise DecalProjectionError("デカール寸法または表示倍率が不正です")
    if width <= 0.0 or height <= 0.0 or ppu <= 0.0:
        raise DecalProjectionError("デカール寸法と表示倍率は0より大きくしてください")
    return width / height * ppu


def _readonly(values: np.ndarray, dtype: np.dtype[Any] | type[Any]) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype)
    if result.base is not None or result.flags.writeable:
        result = result.copy()
    result.flags.writeable = False
    return result


def _image_rgba(image: DecalImage | np.ndarray | object) -> np.ndarray:
    raw = image if isinstance(image, np.ndarray) else getattr(image, "rgba", None)
    values = np.asarray(raw)
    if values.ndim != 3 or values.shape[2] != 4 or values.dtype != np.uint8:
        raise DecalProjectionError("デカール画像はuint8のHxWx4 RGBAである必要があります")
    if values.shape[0] < 1 or values.shape[1] < 1:
        raise DecalProjectionError("デカール画像が空です")
    if values.shape[0] * values.shape[1] > 16_777_216:
        raise DecalProjectionError("デカール画像が大きすぎます（最大1,677万画素）")
    return np.ascontiguousarray(values)


def _validate_face_inputs(
    face_ids: np.ndarray,
    allowed_face_mask: np.ndarray,
    visible_face_mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ids = np.asarray(face_ids)
    allowed = np.asarray(allowed_face_mask, dtype=bool)
    if ids.ndim != 2 or not np.issubdtype(ids.dtype, np.integer):
        raise DecalProjectionError("face IDマップは2次元整数配列で指定してください")
    if allowed.ndim != 1 or len(allowed) < 1:
        raise DecalProjectionError("編集可能面マスクが不正です")
    if visible_face_mask is None:
        visible = np.ones(len(allowed), dtype=bool)
    else:
        visible = np.asarray(visible_face_mask, dtype=bool)
        if visible.shape != allowed.shape:
            raise DecalProjectionError("可視面マスクの面数が一致しません")
    return ids.astype(np.int32, copy=False), allowed, visible


def _sample_transformed_rgba(
    rgba: np.ndarray,
    transform: DecalTransform,
    output_shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Return a full-size RGBA overlay and geometric footprint mask."""

    height, width = (int(output_shape[0]), int(output_shape[1]))
    if height < 1 or width < 1:
        raise DecalProjectionError("3D表示サイズが不正です")
    source_height, source_width = rgba.shape[:2]
    target_width = float(transform.width_px)
    target_height = target_width * source_height / source_width
    radians = math.radians(float(transform.rotation_degrees) % 360.0)
    cosine, sine = math.cos(radians), math.sin(radians)
    extent_x = 0.5 * (abs(cosine) * target_width + abs(sine) * target_height)
    extent_y = 0.5 * (abs(sine) * target_width + abs(cosine) * target_height)
    center_x, center_y = (float(value) for value in transform.center_xy)
    x0 = max(0, int(math.floor(center_x - extent_x - 1.0)))
    x1 = min(width, int(math.ceil(center_x + extent_x + 1.0)))
    y0 = max(0, int(math.floor(center_y - extent_y - 1.0)))
    y1 = min(height, int(math.ceil(center_y + extent_y + 1.0)))
    output = np.zeros((height, width, 4), dtype=np.uint8)
    footprint = np.zeros((height, width), dtype=bool)
    if x0 >= x1 or y0 >= y1 or float(transform.opacity) <= 0.0:
        return output, footprint

    grid_y, grid_x = np.mgrid[y0:y1, x0:x1]
    dx = grid_x.astype(np.float64) + 0.5 - center_x
    dy = grid_y.astype(np.float64) + 0.5 - center_y
    local_x = cosine * dx + sine * dy
    local_y = -sine * dx + cosine * dy
    if transform.flip_x:
        local_x = -local_x
    if transform.flip_y:
        local_y = -local_y
    inside = (np.abs(local_x) <= target_width * 0.5) & (
        np.abs(local_y) <= target_height * 0.5
    )
    if not bool(np.any(inside)):
        return output, footprint
    source_x = (local_x / target_width + 0.5) * source_width - 0.5
    source_y = (local_y / target_height + 0.5) * source_height - 0.5
    source_x = np.clip(source_x, 0.0, source_width - 1.0)
    source_y = np.clip(source_y, 0.0, source_height - 1.0)
    left = np.floor(source_x).astype(np.intp)
    top = np.floor(source_y).astype(np.intp)
    right = np.minimum(left + 1, source_width - 1)
    bottom = np.minimum(top + 1, source_height - 1)
    weight_x = source_x - left
    weight_y = source_y - top
    weights = (
        ((1.0 - weight_x) * (1.0 - weight_y)),
        (weight_x * (1.0 - weight_y)),
        ((1.0 - weight_x) * weight_y),
        (weight_x * weight_y),
    )
    corners = (
        rgba[top, left].astype(np.float64),
        rgba[top, right].astype(np.float64),
        rgba[bottom, left].astype(np.float64),
        rgba[bottom, right].astype(np.float64),
    )
    # Interpolate premultiplied colour.  Straight-RGBA interpolation would mix
    # arbitrary RGB stored in fully transparent pixels into an antialiased
    # logo edge and create a dark/white halo after palette quantization.
    sampled_alpha = sum(
        corner[..., 3] * weight for corner, weight in zip(corners, weights, strict=True)
    )
    sampled_premultiplied = sum(
        corner[..., :3]
        * (corner[..., 3:4] / 255.0)
        * weight[..., None]
        for corner, weight in zip(corners, weights, strict=True)
    )
    sampled_rgb = np.zeros_like(sampled_premultiplied)
    nonzero_alpha = sampled_alpha > 1.0e-12
    sampled_rgb[nonzero_alpha] = (
        sampled_premultiplied[nonzero_alpha]
        / (sampled_alpha[nonzero_alpha, None] / 255.0)
    )
    sampled = np.concatenate(
        (sampled_rgb, (sampled_alpha * float(transform.opacity))[..., None]), axis=2
    )
    sampled = np.clip(np.rint(sampled), 0.0, 255.0).astype(np.uint8)
    sampled[~inside] = 0
    output[y0:y1, x0:x1] = sampled
    footprint[y0:y1, x0:x1] = inside
    return output, footprint


def _palette_table(
    palette_rgb: np.ndarray,
    enabled_states: np.ndarray | list[bool] | tuple[bool, ...],
) -> tuple[np.ndarray, np.ndarray]:
    palette = np.asarray(palette_rgb, dtype=np.float64)
    if palette.ndim != 2 or palette.shape[1] != 3 or not np.isfinite(palette).all():
        raise DecalProjectionError("パレットRGBは有限なNx3配列で指定してください")
    if len(palette) < 1 or len(palette) > 32:
        raise DecalProjectionError("パレット色数は1～32で指定してください")
    if float(palette.max(initial=0.0)) > 1.5:
        palette = palette / 255.0
    if float(palette.min(initial=0.0)) < 0.0 or float(palette.max(initial=0.0)) > 1.0:
        raise DecalProjectionError("パレットRGBは0～1または0～255で指定してください")
    enabled = np.asarray(enabled_states, dtype=bool)
    if enabled.ndim != 1 or len(enabled) < len(palette):
        raise DecalProjectionError("有効色マスクがパレット色数と一致しません")
    active = np.flatnonzero(enabled[: len(palette)]).astype(np.int8)
    if len(active) == 0:
        raise DecalProjectionError("デカールに使用できるパレット色がありません")
    return np.clip(palette, 0.0, 1.0), active


def _nearest_palette_states(
    rgb8: np.ndarray,
    palette: np.ndarray,
    active_states: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    pixels = np.asarray(rgb8, dtype=np.uint8).reshape(-1, 3)
    if len(pixels) == 0:
        return np.empty(0, dtype=np.int8), np.empty(0, dtype=np.float64)
    packed = (
        (pixels[:, 0].astype(np.uint32) << 16)
        | (pixels[:, 1].astype(np.uint32) << 8)
        | pixels[:, 2].astype(np.uint32)
    )
    unique, inverse = np.unique(packed, return_inverse=True)
    unique_rgb = np.column_stack(
        ((unique >> 16) & 255, (unique >> 8) & 255, unique & 255)
    ).astype(np.float64) / 255.0
    palette_lab = srgb_to_lab(palette[active_states.astype(np.intp)])
    unique_states = np.empty(len(unique), dtype=np.int8)
    unique_errors = np.empty(len(unique), dtype=np.float64)
    for start in range(0, len(unique), 16_384):
        stop = min(len(unique), start + 16_384)
        lab = srgb_to_lab(unique_rgb[start:stop])
        distance = np.linalg.norm(lab[:, None, :] - palette_lab[None, :, :], axis=2)
        nearest = np.argmin(distance, axis=1)
        unique_states[start:stop] = active_states[nearest]
        unique_errors[start:stop] = distance[np.arange(stop - start), nearest]
    return unique_states[inverse], unique_errors[inverse]


def _linear_srgb(values: np.ndarray) -> np.ndarray:
    rgb = np.asarray(values, dtype=np.float64)
    return np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )


def _encoded_srgb(values: np.ndarray) -> np.ndarray:
    linear = np.asarray(values, dtype=np.float64)
    return np.where(
        linear <= 0.0031308,
        12.92 * linear,
        1.055 * np.power(np.maximum(linear, 0.0), 1.0 / 2.4) - 0.055,
    )


def _underlying_states(
    ids: np.ndarray,
    target: np.ndarray,
    palette_count: int,
    *,
    base_face_states: np.ndarray | None,
    base_state_map: np.ndarray | None,
) -> np.ndarray | None:
    if base_state_map is not None:
        state_pixels = np.asarray(base_state_map)
        if state_pixels.shape != ids.shape or not np.issubdtype(
            state_pixels.dtype, np.integer
        ):
            raise DecalProjectionError("下地色マップはface IDマップと同じ整数配列にしてください")
        result = state_pixels[target].astype(np.int16, copy=False)
    elif base_face_states is not None:
        face_states = np.asarray(base_face_states)
        if face_states.ndim != 1 or not np.issubdtype(face_states.dtype, np.integer):
            raise DecalProjectionError("下地色は面ごとの整数配列で指定してください")
        selected_faces = ids[target]
        if len(selected_faces) and int(selected_faces.max()) >= len(face_states):
            raise DecalProjectionError("下地色の面数がface IDマップと一致しません")
        result = face_states[selected_faces].astype(np.int16, copy=False)
    else:
        return None
    if len(result) and (int(result.min()) < 0 or int(result.max()) >= palette_count):
        raise DecalProjectionError("下地色に現在のパレット範囲外の色があります")
    return result.astype(np.intp, copy=False)


def _nearest_anchor_face(
    face_ids: np.ndarray,
    target_mask: np.ndarray,
    support_mask: np.ndarray,
    center_xy: tuple[float, float],
) -> int:
    height, width = face_ids.shape
    x = int(np.clip(math.floor(float(center_xy[0])), 0, width - 1))
    y = int(np.clip(math.floor(float(center_xy[1])), 0, height - 1))
    if support_mask[y, x] and face_ids[y, x] >= 0:
        return int(face_ids[y, x])
    search = target_mask if bool(np.any(target_mask)) else support_mask
    ys, xs = np.nonzero(search)
    if len(xs) == 0:
        return -1
    distances = (xs + 0.5 - float(center_xy[0])) ** 2 + (
        ys + 0.5 - float(center_xy[1])
    ) ** 2
    return int(face_ids[ys[int(np.argmin(distances))], xs[int(np.argmin(distances))]])


def build_decal_preview(
    image: DecalImage | np.ndarray | object,
    transform: DecalTransform,
    face_ids: np.ndarray,
    allowed_face_mask: np.ndarray,
    visible_face_mask: np.ndarray | None,
    palette_rgb: np.ndarray,
    enabled_states: np.ndarray | list[bool] | tuple[bool, ...],
    *,
    mode: DecalMode = "image",
    selected_state: int | None = None,
    alpha_threshold: int = 8,
    frame_generation: int | None = None,
    base_face_states: np.ndarray | None = None,
    base_state_map: np.ndarray | None = None,
) -> DecalPreview:
    """Transform, clip, and quantize one placement without changing paint."""

    if mode not in ("image", "selected"):
        raise DecalProjectionError("デカール色モードはimageまたはselectedです")
    threshold = int(alpha_threshold)
    if threshold < 1 or threshold > 255:
        raise DecalProjectionError("透明度しきい値は1～255で指定してください")
    ids, allowed, visible = _validate_face_inputs(
        face_ids, allowed_face_mask, visible_face_mask
    )
    palette, active_states = _palette_table(palette_rgb, enabled_states)
    if mode == "selected":
        if selected_state is None or int(selected_state) not in set(
            int(value) for value in active_states
        ):
            raise DecalProjectionError("選択色は現在有効なパレット色から指定してください")

    overlay, footprint = _sample_transformed_rgba(
        _image_rgba(image), transform, ids.shape
    )
    valid_id = (ids >= 0) & (ids < len(allowed))
    eligible = np.zeros(ids.shape, dtype=bool)
    eligible[valid_id] = allowed[ids[valid_id]] & visible[ids[valid_id]]
    support = footprint & eligible
    opaque = overlay[..., 3] >= threshold
    target = opaque & eligible
    state_map = np.full(ids.shape, -1, dtype=np.int8)
    errors = np.empty(0, dtype=np.float64)
    if bool(np.any(target)):
        if mode == "selected":
            state_map[target] = int(selected_state)
            errors = np.zeros(int(np.count_nonzero(target)), dtype=np.float64)
        else:
            target_rgb = overlay[..., :3][target].astype(np.float64) / 255.0
            target_alpha = overlay[..., 3][target].astype(np.float64) / 255.0
            partially_transparent = target_alpha < (1.0 - 1.0e-12)
            if bool(np.any(partially_transparent)):
                underlying = _underlying_states(
                    ids,
                    target,
                    len(palette),
                    base_face_states=base_face_states,
                    base_state_map=base_state_map,
                )
                if underlying is None:
                    raise DecalProjectionError(
                        "半透明デカールの色再現には現在の面色を指定してください"
                    )
                foreground_linear = _linear_srgb(target_rgb)
                background_linear = _linear_srgb(palette[underlying])
                target_rgb = np.clip(
                    _encoded_srgb(
                        foreground_linear * target_alpha[:, None]
                        + background_linear * (1.0 - target_alpha[:, None])
                    ),
                    0.0,
                    1.0,
                )
            states, errors = _nearest_palette_states(
                np.rint(target_rgb * 255.0).astype(np.uint8), palette, active_states
            )
            state_map[target] = states

    clipped_overlay = overlay.copy()
    clipped_overlay[~eligible] = 0
    quantized = np.zeros_like(overlay)
    if bool(np.any(target)):
        quantized[..., :3][target] = np.rint(
            palette[state_map[target].astype(np.intp)] * 255.0
        ).astype(np.uint8)
        # The bake stores one final palette state, not translucent pigment.
        # Alpha was already resolved against the current surface above.
        quantized[..., 3][target] = 255
    candidate = np.unique(ids[target]).astype(np.int32) if bool(np.any(target)) else np.empty(0, dtype=np.int32)
    support_faces = np.unique(ids[support]).astype(np.int32) if bool(np.any(support)) else np.empty(0, dtype=np.int32)
    anchor = _nearest_anchor_face(ids, target, support, transform.center_xy)
    mean_error = float(np.mean(errors)) if len(errors) else 0.0
    p90_error = float(np.percentile(errors, 90.0)) if len(errors) else 0.0
    metrics = DecalPreviewMetrics(
        footprint_pixels=int(np.count_nonzero(footprint)),
        opaque_pixels=int(np.count_nonzero(opaque)),
        eligible_pixels=int(np.count_nonzero(target)),
        clipped_pixels=int(np.count_nonzero(opaque & ~eligible)),
        candidate_faces=len(candidate),
        support_faces=len(support_faces),
        mean_delta_e76=mean_error,
        p90_delta_e76=p90_error,
    )
    return DecalPreview(
        overlay_rgba=_readonly(clipped_overlay, np.uint8),
        quantized_overlay_rgba=_readonly(quantized, np.uint8),
        state_map=_readonly(state_map, np.int8),
        face_ids=_readonly(ids, np.int32),
        candidate_faces=_readonly(candidate, np.int32),
        support_faces=_readonly(support_faces, np.int32),
        anchor_face=anchor,
        frame_generation=(None if frame_generation is None else int(frame_generation)),
        transform=transform,
        mode=mode,
        metrics=metrics,
    )


def composite_decal_preview(
    base: Image.Image,
    preview: DecalPreview,
    *,
    quantized: bool = True,
) -> Image.Image:
    """Alpha-composite a placement on the current 3D render."""

    if base.size != (preview.state_map.shape[1], preview.state_map.shape[0]):
        raise DecalProjectionError("プレビュー画像と3D表示サイズが一致しません")
    overlay = preview.quantized_overlay_rgba if quantized else preview.overlay_rgba
    result = Image.alpha_composite(base.convert("RGBA"), Image.fromarray(overlay, "RGBA"))
    result.info.update(base.info)
    return result


def _camera_signature(camera: object) -> tuple[object, ...]:
    orientation = getattr(camera, "orientation", None)
    if orientation is not None:
        values = np.asarray(orientation, dtype=np.float64).reshape(-1)
        orientation_value: tuple[float, ...] | None = tuple(float(value) for value in values)
    else:
        orientation_value = None
    return (
        type(camera).__module__,
        type(camera).__qualname__,
        float(getattr(camera, "yaw_degrees", 0.0)),
        float(getattr(camera, "pitch_degrees", 0.0)),
        float(getattr(camera, "zoom", 1.0)),
        float(getattr(camera, "pan_x", 0.0)),
        float(getattr(camera, "pan_y", 0.0)),
        orientation_value,
    )


def _project_triangles(
    level: MeshLevel,
    face_indices: np.ndarray,
    camera: object,
    render_size: tuple[int, int],
) -> np.ndarray:
    vertices = np.asarray(level.vertices_unit, dtype=np.float64)
    faces = np.asarray(level.faces, dtype=np.int64)
    width, height = (int(render_size[0]), int(render_size[1]))
    if width < 2 or height < 2 or (height, width) == (0, 0):
        raise DecalProjectionError("3D表示サイズが不正です")
    mvp, _clean, _ppu = renderer_module._orbit_camera_mvp(
        vertices, (width, height), camera
    )
    triangles = vertices[faces[face_indices.astype(np.intp)]]
    homogeneous = np.concatenate(
        (triangles, np.ones((*triangles.shape[:2], 1), dtype=np.float64)), axis=2
    )
    clip = homogeneous @ np.asarray(mvp, dtype=np.float64).T
    divisor = clip[..., 3]
    if np.any(~np.isfinite(clip)) or np.any(np.abs(divisor) <= 1.0e-12):
        raise DecalProjectionError("デカール対象面を画面へ投影できません")
    ndc = clip[..., :2] / divisor[..., None]
    output = np.empty_like(ndc)
    output[..., 0] = (ndc[..., 0] * 0.5 + 0.5) * width
    output[..., 1] = (0.5 - ndc[..., 1] * 0.5) * height
    return output


def _validate_state_raster_inputs(
    level: MeshLevel,
    face_ids: np.ndarray,
    render_size: tuple[int, int],
) -> tuple[np.ndarray, int, int]:
    """Validate the common inputs used by exact adaptive-tree rasters."""

    width, height = (int(render_size[0]), int(render_size[1]))
    if width < 2 or height < 2:
        raise DecalProjectionError("3D表示サイズが不正です")
    ids = np.asarray(face_ids)
    if ids.shape != (height, width) or not np.issubdtype(ids.dtype, np.integer):
        raise DecalProjectionError("face IDマップと3D表示サイズが一致しません")
    faces = np.asarray(level.faces)
    if faces.ndim != 2 or faces.shape[1:] != (3,):
        raise DecalProjectionError("デカール対象の三角形データが不正です")
    return ids.astype(np.int32, copy=False), width, height


def _gpu_projected_triangles(
    triangles_world: np.ndarray,
    mvp: np.ndarray,
    render_size: tuple[int, int],
) -> np.ndarray:
    """Project triangles with the same float32 stages as the ModernGL shader.

    ``InteractiveMeshRenderer`` uploads both mesh vertices and its MVP matrix
    as float32 values.  The adaptive GPU overlay also casts every subdivided
    leaf back to float32 before drawing it.  We first reproduce those upload
    rounding boundaries, then evaluate the dot products in float64.  The latter
    is a deterministic CPU representation of the shader's fused multiply-add
    result; NumPy's float32 BLAS accumulation differs by one ULP on a few
    depth-six edges and can otherwise choose the neighbouring pixel centre.
    """

    width, height = (int(render_size[0]), int(render_size[1]))
    triangles_upload = np.asarray(triangles_world, dtype=np.float32)
    triangles = triangles_upload.astype(np.float64)
    if triangles.ndim != 3 or triangles.shape[1:] != (3, 3):
        raise DecalProjectionError("デカール細分化三角形が不正です")
    if not bool(np.all(np.isfinite(triangles))):
        raise DecalProjectionError("デカール細分化三角形を画面へ投影できません")
    homogeneous = np.empty((*triangles.shape[:2], 4), dtype=np.float64)
    homogeneous[..., :3] = triangles
    homogeneous[..., 3] = 1.0
    # Round exactly as the uniform upload does before the deterministic dot.
    uploaded_mvp = np.asarray(mvp, dtype=np.float32).astype(np.float64)
    clip = homogeneous @ uploaded_mvp.T
    divisor = clip[..., 3]
    if np.any(~np.isfinite(clip)) or np.any(np.abs(divisor) <= 1.0e-12):
        raise DecalProjectionError("デカール細分化三角形を画面へ投影できません")
    ndc = clip[..., :2] / divisor[..., None]
    output = np.empty_like(ndc, dtype=np.float64)
    output[..., 0] = (ndc[..., 0] * 0.5 + 0.5) * width
    # The framebuffer is flipped after readback, so its pixel centres are
    # (x + 0.5, y + 0.5) in this top-left-origin coordinate system.
    output[..., 1] = (0.5 - ndc[..., 1] * 0.5) * height
    return output


def _rasterize_gl_triangle(
    output: np.ndarray,
    face_ids: np.ndarray,
    triangle: np.ndarray,
    *,
    face: int,
    state: int,
) -> None:
    """Raster one leaf with OpenGL's pixel-centre/top-left fill convention.

    PIL polygon filling includes both sides of a shared edge and rounds its
    floating vertices to an integer-grid convention.  ModernGL/OpenGL samples
    at half-integer pixel centres and makes shared edges half-open.  In a
    top-left-origin image, after normalising the winding, an edge is inclusive
    when it travels upward, or leftward when horizontal.  This is the flipped
    equivalent of OpenGL's lower-left window-coordinate rule.

    The exact face-ID buffer remains authoritative: even a numerically valid
    leaf can only replace pixels where the production picking pass selected
    its source face.
    """

    points = np.asarray(triangle, dtype=np.float64)
    if points.shape != (3, 2) or not bool(np.all(np.isfinite(points))):
        return
    height, width = output.shape
    x0 = max(0, int(math.ceil(float(points[:, 0].min()) - 0.5)))
    y0 = max(0, int(math.ceil(float(points[:, 1].min()) - 0.5)))
    x1 = min(width - 1, int(math.floor(float(points[:, 0].max()) - 0.5)))
    y1 = min(height - 1, int(math.floor(float(points[:, 1].max()) - 0.5)))
    if x1 < x0 or y1 < y0:
        return

    a, b, c = points
    area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if not math.isfinite(float(area)) or float(area) == 0.0:
        return
    orientation = 1.0 if area > 0.0 else -1.0
    pixel_x = np.arange(x0, x1 + 1, dtype=np.float64)[None, :] + 0.5
    pixel_y = np.arange(y0, y1 + 1, dtype=np.float64)[:, None] + 0.5
    covered = np.ones((y1 - y0 + 1, x1 - x0 + 1), dtype=bool)
    for first, second in ((a, b), (b, c), (c, a)):
        dx = float(second[0] - first[0])
        dy = float(second[1] - first[1])
        edge = orientation * (
            dx * (pixel_y - float(first[1]))
            - dy * (pixel_x - float(first[0]))
        )
        oriented_dx = orientation * dx
        oriented_dy = orientation * dy
        inclusive = oriented_dy < 0.0 or (
            oriented_dy == 0.0 and oriented_dx < 0.0
        )
        covered &= edge >= 0.0 if inclusive else edge > 0.0
        if not bool(np.any(covered)):
            return

    local_ids = face_ids[y0 : y1 + 1, x0 : x1 + 1]
    covered &= local_ids == int(face)
    if bool(np.any(covered)):
        local_output = output[y0 : y1 + 1, x0 : x1 + 1]
        local_output[covered] = np.int8(state)


def _rasterize_tree_nodes(
    level: MeshLevel,
    nodes_by_face: Mapping[int, smooth_paint.PaintNode],
    face_ids: np.ndarray,
    camera: object,
    render_size: tuple[int, int],
    output: np.ndarray,
    *,
    cancelled: CancelCallback | None = None,
) -> None:
    """Raster adaptive leaves exactly like the production ModernGL overlay."""

    if not nodes_by_face:
        return
    _check_cancel(cancelled)
    ids, width, height = _validate_state_raster_inputs(level, face_ids, render_size)
    faces: list[int] = []
    nodes: list[smooth_paint.PaintNode] = []
    face_count = len(level.faces)
    visible_ids = ids[(ids >= 0) & (ids < face_count)]
    visible_faces = set(int(value) for value in np.unique(visible_ids))
    for offset, (raw_face, node) in enumerate(nodes_by_face.items()):
        if offset % 64 == 0:
            _check_cancel(cancelled)
        face = int(raw_face)
        if face < 0 or face >= face_count:
            raise DecalProjectionError("デカール面番号が形状の範囲外です")
        # A large manual-paint history can contain thousands of roots behind
        # the model.  They cannot affect this exact face-ID frame, so do not
        # validate/project/traverse them for a small decal preview.
        if face not in visible_faces:
            continue
        if not isinstance(node, smooth_paint.PaintNode):
            raise DecalProjectionError("デカール細分化ツリーが不正です")
        node.validate(max_depth=smooth_paint.MAX_DEPTH)
        faces.append(face)
        nodes.append(node)
    if not faces:
        _check_cancel(cancelled)
        return
    _check_cancel(cancelled)
    # Match InteractiveMeshRenderer's uploaded geometry and camera fit, not
    # the float64 source array that may have carried extra OBJ precision.
    vertices_gpu = np.asarray(level.vertices_unit, dtype=np.float32)
    faces_gpu = np.asarray(level.faces, dtype=np.int32)
    mvp, _clean_camera, _pixels_per_unit = renderer_module._orbit_camera_mvp(
        vertices_gpu, (width, height), camera
    )
    for face_offset, (face, node) in enumerate(zip(faces, nodes, strict=True)):
        if face_offset % 64 == 0:
            _check_cancel(cancelled)
        visible = ids == face
        if not bool(np.any(visible)):
            continue
        if node.is_leaf:
            output[visible] = np.int8(node.state)
            continue

        # adaptive_gpu_overlay builds its leaves from the float32 root in
        # model space, then uploads each leaf as float32.  Reproduce those
        # rounding points before applying the same MVP/viewport transform.
        root_world = vertices_gpu[faces_gpu[face]]
        leaves = tuple(
            smooth_paint.iter_leaf_triangles(
                node, root_world, max_depth=smooth_paint.MAX_DEPTH
            )
        )
        if not leaves:
            continue
        leaf_world = np.asarray(
            [np.asarray(leaf.vertices, dtype=np.float32) for leaf in leaves],
            dtype=np.float32,
        )
        leaf_screen = _gpu_projected_triangles(
            leaf_world, mvp, (width, height)
        )
        for leaf_offset, (leaf, triangle) in enumerate(
            zip(leaves, leaf_screen, strict=True)
        ):
            if leaf_offset % 256 == 0:
                _check_cancel(cancelled)
            _rasterize_gl_triangle(
                output,
                ids,
                triangle[:, :2],
                face=face,
                state=int(leaf.state),
            )


def rasterize_existing_tree_states(
    level: MeshLevel,
    tree_store: Mapping[int, smooth_paint.PaintNode] | None,
    face_ids: np.ndarray,
    camera: object,
    render_size: tuple[int, int],
    base_face_states: np.ndarray,
    *,
    cancelled: CancelCallback | None = None,
) -> np.ndarray:
    """Return the exact current visible state at every picked surface pixel.

    ``base_face_states`` is the effective uniform/root state for every face.
    Adaptive leaves in ``tree_store`` replace it only where the exact face-ID
    buffer says that root is visible.  The returned map uses ``-1`` for the
    background and is suitable as the semi-transparent decal underlay.
    """

    _check_cancel(cancelled)
    ids, width, height = _validate_state_raster_inputs(level, face_ids, render_size)
    base = np.asarray(base_face_states)
    if (
        base.shape != (len(level.faces),)
        or not np.issubdtype(base.dtype, np.integer)
    ):
        raise DecalProjectionError("下地色の面数が形状と一致しません")
    if len(base) and (
        int(base.min()) < 0 or int(base.max()) >= smooth_paint.STATE_COUNT
    ):
        raise DecalProjectionError("下地色に現在のパレット範囲外の色があります")
    result = np.full((height, width), -1, dtype=np.int8)
    valid = (ids >= 0) & (ids < len(base))
    if bool(np.any(valid)):
        result[valid] = base[ids[valid]].astype(np.int8, copy=False)
    _rasterize_tree_nodes(
        level,
        tree_store or {},
        ids,
        camera,
        (width, height),
        result,
        cancelled=cancelled,
    )
    _check_cancel(cancelled)
    return _readonly(result, np.int8)


def rasterize_decal_bake_plan(
    level: MeshLevel,
    preview: DecalPreview,
    plan: DecalBakePlan,
    camera: object,
    render_size: tuple[int, int],
    *,
    base_state_map: np.ndarray | None = None,
    base_face_states: np.ndarray | None = None,
    existing_trees: Mapping[int, smooth_paint.PaintNode] | None = None,
    changed_only: bool = True,
    cancelled: CancelCallback | None = None,
) -> np.ndarray:
    """Raster the *planned tree*, not the pre-plan source decal.

    The result is an ``int8`` state map with ``-1`` outside planned roots.
    When a current ``base_state_map`` (or ``base_face_states`` plus the current
    tree store) is supplied, the default ``changed_only`` mode also writes
    ``-1`` for pixels whose final state is unchanged.  Consequently protected
    faces, transparent no-ops, and cloned adaptive underlay remain untouched
    by the preview overlay.

    Without current base-state data an exact changed/unchanged comparison is
    impossible; in that case the final state of every visible planned leaf is
    returned.  This remains visually safe with the shading-aware compositor.
    """

    _check_cancel(cancelled)
    ids, width, height = _validate_state_raster_inputs(
        level, preview.face_ids, render_size
    )
    if preview.state_map.shape != (height, width):
        raise DecalStalePreviewError("3D表示サイズが変わったためデカールを再配置してください")
    if plan.frame_generation != preview.frame_generation:
        raise DecalStalePreviewError("デカール計画とプレビュー世代が一致しません")
    if _camera_signature(camera) != plan.camera_signature:
        raise DecalStalePreviewError("視点が変わったためデカールを再配置してください")
    planned_faces = tuple(int(value) for value in np.asarray(plan.face_indices))
    if set(planned_faces) != set(int(value) for value in plan.nodes_by_face):
        raise DecalProjectionError("デカール計画の面と細分化ツリーが一致しません")
    if existing_trees is not None:
        for face in planned_faces:
            if _tree_code(existing_trees.get(face)) != plan.expected_tree_codes.get(face):
                raise DecalStalePreviewError(
                    "滑らかな手修正が変わったためデカールを再配置してください"
                )

    current: np.ndarray | None = None
    if base_state_map is not None:
        raw_current = np.asarray(base_state_map)
        if raw_current.shape != (height, width) or not np.issubdtype(
            raw_current.dtype, np.integer
        ):
            raise DecalProjectionError("下地色マップはface IDマップと同じ整数配列にしてください")
        if len(raw_current) and (
            int(raw_current.min()) < -1
            or int(raw_current.max()) >= smooth_paint.STATE_COUNT
        ):
            raise DecalProjectionError("下地色マップにパレット範囲外の色があります")
        current = raw_current.astype(np.int8, copy=False)
    elif base_face_states is not None:
        current = rasterize_existing_tree_states(
            level,
            existing_trees,
            ids,
            camera,
            (width, height),
            base_face_states,
            cancelled=cancelled,
        )

    result = np.full((height, width), -1, dtype=np.int8)
    _rasterize_tree_nodes(
        level,
        plan.nodes_by_face,
        ids,
        camera,
        (width, height),
        result,
        cancelled=cancelled,
    )
    _check_cancel(cancelled)
    if bool(changed_only) and current is not None:
        result[(result >= 0) & (result == current)] = -1
    return _readonly(result, np.int8)


def _normalized_palette_rgb(palette_rgb: np.ndarray) -> np.ndarray:
    palette = np.asarray(palette_rgb, dtype=np.float64)
    if palette.ndim != 2 or palette.shape[1:] != (3,) or not np.isfinite(palette).all():
        raise DecalProjectionError("パレットRGBは有限なNx3配列で指定してください")
    if len(palette) < 1 or len(palette) > smooth_paint.STATE_COUNT:
        raise DecalProjectionError("パレット色数は1～32で指定してください")
    if float(palette.max(initial=0.0)) > 1.5:
        palette = palette / 255.0
    if float(palette.min(initial=0.0)) < 0.0 or float(palette.max(initial=0.0)) > 1.0:
        raise DecalProjectionError("パレットRGBは0～1または0～255で指定してください")
    return np.clip(palette, 0.0, 1.0)


def composite_planned_decal_preview(
    base: Image.Image,
    planned_state_map: np.ndarray,
    face_ids: np.ndarray,
    plan: DecalBakePlan,
    palette_rgb: np.ndarray,
    *,
    base_state_map: np.ndarray | None = None,
    base_face_states: np.ndarray | None = None,
    part_palette_rgb_tables: np.ndarray | None = None,
    face_part_ids: np.ndarray | None = None,
) -> Image.Image:
    """Composite exact planned states while retaining renderer lighting.

    Lighting is recovered per pixel from the current displayed RGB divided by
    the palette luminance of that pixel's current state.  This is the same
    ``0.22..1.35`` luma-ratio rule used by ``smooth_paint_hotfix`` and remains
    correct when the underlay is already an adaptive tree.  Supplying
    ``base_state_map`` therefore gives the closest preview/post-bake parity.
    """

    width, height = base.size
    planned = np.asarray(planned_state_map)
    ids = np.asarray(face_ids)
    if (
        planned.shape != (height, width)
        or ids.shape != (height, width)
        or not np.issubdtype(planned.dtype, np.integer)
        or not np.issubdtype(ids.dtype, np.integer)
    ):
        raise DecalProjectionError("計画色マップ、face IDマップ、3D表示サイズが一致しません")
    palette = _normalized_palette_rgb(palette_rgb)
    if planned.size and (
        int(planned.min()) < -1 or int(planned.max()) >= len(palette)
    ):
        raise DecalProjectionError("計画色マップにパレット範囲外の色があります")
    part_tables = None
    part_ids = None
    if (part_palette_rgb_tables is None) != (face_part_ids is None):
        raise DecalProjectionError("パーツ別パレットと面パーツ番号は両方指定してください")
    if part_palette_rgb_tables is not None and face_part_ids is not None:
        raw_tables = np.asarray(part_palette_rgb_tables, dtype=np.float64)
        raw_part_ids = np.asarray(face_part_ids)
        if float(raw_tables.max(initial=0.0)) > 1.5:
            raw_tables = raw_tables / 255.0
        if (
            raw_tables.ndim != 3
            or raw_tables.shape[1:] != palette.shape
            or not np.isfinite(raw_tables).all()
            or float(raw_tables.min(initial=0.0)) < 0.0
            or float(raw_tables.max(initial=0.0)) > 1.0
            or raw_part_ids.ndim != 1
            or len(raw_part_ids) <= max(-1, int(ids.max(initial=-1)))
            or not np.issubdtype(raw_part_ids.dtype, np.integer)
        ):
            raise DecalProjectionError("パーツ別パレット情報が不正です")
        part_tables = np.clip(raw_tables, 0.0, 1.0)
        part_ids = raw_part_ids.astype(np.intp, copy=False)

    current: np.ndarray | None = None
    if base_state_map is not None:
        raw_current = np.asarray(base_state_map)
        if raw_current.shape != (height, width) or not np.issubdtype(
            raw_current.dtype, np.integer
        ):
            raise DecalProjectionError("下地色マップはface IDマップと同じ整数配列にしてください")
        if raw_current.size and (
            int(raw_current.min()) < -1 or int(raw_current.max()) >= len(palette)
        ):
            raise DecalProjectionError("下地色マップにパレット範囲外の色があります")
        current = raw_current.astype(np.int16, copy=False)
    elif base_face_states is not None:
        roots = np.asarray(base_face_states)
        if roots.ndim != 1 or not np.issubdtype(roots.dtype, np.integer):
            raise DecalProjectionError("下地色は面ごとの整数配列で指定してください")
        if roots.size and (
            int(roots.min()) < 0 or int(roots.max()) >= len(palette)
        ):
            raise DecalProjectionError("下地色にパレット範囲外の色があります")
        current = np.full((height, width), -1, dtype=np.int16)
        root_valid = (ids >= 0) & (ids < len(roots))
        current[root_valid] = roots[ids[root_valid]]

    plan_face_mask = np.zeros(
        max(
            0 if face_part_ids is None else len(face_part_ids),
            int(ids.max(initial=-1)) + 1,
        ),
        dtype=bool,
    )
    for raw_face in np.asarray(plan.face_indices):
        face = int(raw_face)
        if face >= 0:
            if face >= len(plan_face_mask):
                plan_face_mask = np.pad(plan_face_mask, (0, face + 1 - len(plan_face_mask)))
            plan_face_mask[face] = True
    picked = (ids >= 0) & (ids < len(plan_face_mask))
    valid = np.zeros((height, width), dtype=bool)
    valid[picked] = plan_face_mask[ids[picked]]
    valid &= (planned >= 0) & (planned < len(palette))
    if not bool(np.any(valid)):
        result = base.convert("RGB")
        result.info.update(base.info)
        return result

    source = np.asarray(base.convert("RGB"), dtype=np.uint8)
    output = source.copy()
    luma_weights = np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float64)
    source_luma = (source.astype(np.float64) / 255.0) @ luma_weights

    def colors_for(states: np.ndarray, pixels: np.ndarray) -> np.ndarray:
        clipped = np.clip(states[pixels], 0, len(palette) - 1).astype(np.intp)
        if part_tables is None or part_ids is None:
            return palette[clipped]
        pixel_faces = ids[pixels].astype(np.intp)
        pixel_parts = part_ids[pixel_faces]
        if len(pixel_parts) and (
            int(pixel_parts.min()) < 0 or int(pixel_parts.max()) >= len(part_tables)
        ):
            raise DecalProjectionError("面のパーツ番号がパーツ別パレット範囲外です")
        return part_tables[pixel_parts, clipped]

    if current is None:
        # Fallback for callers that have not yet built the exact current state
        # map.  A planned root's dominant state mirrors the adaptive CPU
        # compositor, but an explicit base map is required for pixel-perfect
        # parity over an existing multi-state tree.
        current = np.full((height, width), -1, dtype=np.int16)
        for raw_face, node in plan.nodes_by_face.items():
            current[ids == int(raw_face)] = int(node.dominant_state())
    shade_valid = valid & (current >= 0) & (current < len(palette))
    shade = np.ones((height, width), dtype=np.float64)
    if bool(np.any(shade_valid)):
        current_colors = colors_for(current, shade_valid)
        current_luma = np.maximum(current_colors @ luma_weights, 0.018)
        shade[shade_valid] = np.clip(
            source_luma[shade_valid] / current_luma, 0.22, 1.35
        )
    requested = colors_for(planned, valid) * shade[valid, None]
    output[valid] = np.rint(np.clip(requested, 0.0, 1.0) * 255.0).astype(np.uint8)
    result = Image.fromarray(output, mode="RGB")
    result.info.update(base.info)
    return result


def _surface_island(
    session: PaintSession,
    support_faces: np.ndarray,
    anchor_face: int,
    max_angle_degrees: float,
) -> set[int]:
    support = {int(value) for value in np.asarray(support_faces, dtype=np.int32)}
    anchor = int(anchor_face)
    if anchor not in support:
        return set()
    angle = float(max_angle_degrees)
    if not math.isfinite(angle) or angle <= 0.0 or angle > 180.0:
        raise DecalProjectionError("最大投影角は0より大きく180以下にしてください")
    minimum_dot = math.cos(math.radians(angle))
    normals = np.asarray(session.normals, dtype=np.float64)
    normal_valid = np.asarray(session.normal_valid, dtype=bool)
    neighbors = np.asarray(session.neighbors, dtype=np.int32)
    if not normal_valid[anchor]:
        return {anchor}
    reference = normals[anchor]
    reached = {anchor}
    pending: deque[int] = deque((anchor,))
    while pending:
        current = pending.popleft()
        for raw_neighbor in neighbors[current]:
            neighbor = int(raw_neighbor)
            if neighbor < 0 or neighbor in reached or neighbor not in support:
                continue
            if not normal_valid[current] or not normal_valid[neighbor]:
                continue
            if float(np.dot(normals[current], normals[neighbor])) < minimum_dot:
                continue
            if float(np.dot(reference, normals[neighbor])) < minimum_dot:
                continue
            reached.add(neighbor)
            pending.append(neighbor)
    return reached


def _point_membership(points: np.ndarray, triangles: tuple[np.ndarray, ...]) -> np.ndarray:
    """Assign every point to exactly one closest child triangle."""

    scores = np.full((len(points), len(triangles)), -np.inf, dtype=np.float64)
    for column, triangle in enumerate(triangles):
        a, b, c = triangle[:, :2]
        matrix = np.column_stack((a - c, b - c))
        determinant = float(np.linalg.det(matrix))
        if not math.isfinite(determinant) or abs(determinant) <= 1.0e-12:
            continue
        first_second = (points - c) @ np.linalg.inv(matrix).T
        barycentric = np.column_stack(
            (first_second, 1.0 - first_second[:, 0] - first_second[:, 1])
        )
        scores[:, column] = np.min(barycentric, axis=1)
    return np.argmax(scores, axis=1).astype(np.int8)


def _sample_triangle_states(
    triangle: np.ndarray,
    state_map: np.ndarray,
    face_ids: np.ndarray,
    face_id: int,
) -> np.ndarray:
    barycentric = np.asarray(
        (
            (1 / 3, 1 / 3, 1 / 3),
            (0.80, 0.10, 0.10),
            (0.10, 0.80, 0.10),
            (0.10, 0.10, 0.80),
            (0.45, 0.45, 0.10),
            (0.10, 0.45, 0.45),
            (0.45, 0.10, 0.45),
        ),
        dtype=np.float64,
    )
    points = barycentric @ triangle[:, :2]
    x = np.floor(points[:, 0]).astype(np.intp)
    y = np.floor(points[:, 1]).astype(np.intp)
    valid = (x >= 0) & (x < state_map.shape[1]) & (y >= 0) & (y < state_map.shape[0])
    result = np.full(len(points), -1, dtype=np.int8)
    if bool(np.any(valid)):
        selected_x, selected_y = x[valid], y[valid]
        same_face = face_ids[selected_y, selected_x] == int(face_id)
        values = np.full(len(selected_x), -1, dtype=np.int8)
        values[same_face] = state_map[selected_y[same_face], selected_x[same_face]]
        result[valid] = values
    return result


@dataclass(slots=True)
class _NodeBudget:
    limit: int
    count: int = 0

    def add(self, amount: int = 1) -> None:
        self.count += int(amount)
        if self.count > self.limit:
            raise DecalProjectionError(
                "デカール境界が複雑すぎます。サイズまたは品質を下げてください"
            )


def _paint_tree_samples(
    node: smooth_paint.PaintNode,
    triangle: np.ndarray,
    points: np.ndarray,
    states: np.ndarray,
    *,
    state_map: np.ndarray,
    face_ids: np.ndarray,
    face_id: int,
    depth: int,
    max_depth: int,
    min_edge_pixels: float,
    budget: _NodeBudget,
) -> smooth_paint.PaintNode:
    if len(points) == 0:
        return node.clone()
    painted = states >= 0
    if not bool(np.any(painted)):
        return node.clone()
    unique = np.unique(states[painted])
    sampled = _sample_triangle_states(triangle, state_map, face_ids, face_id)
    # ``states`` contains every visible pixel of this root, including -1 for
    # transparent decal holes.  Replacing a complete subtree is safe only when
    # the whole sampled surface is opaque and has one target state.  This is
    # what keeps logos with counters (O/A/P etc.) from being filled solid.
    if len(unique) == 1 and np.all(states >= 0) and np.all(sampled == int(unique[0])):
        budget.add()
        return smooth_paint.PaintNode(int(unique[0]))

    edges = triangle[[1, 2, 0], :2] - triangle[:, :2]
    maximum_edge = float(np.linalg.norm(edges, axis=1).max(initial=0.0))
    if depth >= max_depth or maximum_edge <= float(min_edge_pixels):
        # Match the smooth-brush centre boundary rule.  A transparent centre
        # leaves the prior leaf/subtree untouched even if an antialiased edge
        # contributes a few target pixels to this smallest printable cell.
        centre_state = int(sampled[0])
        if centre_state < 0:
            return node.clone()
        budget.add()
        return smooth_paint.PaintNode(centre_state)

    if node.is_leaf:
        split_sides, special_side = 3, 0
        child_nodes = tuple(smooth_paint.PaintNode(int(node.state)) for _ in range(4))
    else:
        split_sides = int(node.split_sides)
        special_side = int(node.special_side)
        child_nodes = tuple(child.clone() for child in node.children or ())
    child_triangles = smooth_paint.subdivide_triangle(
        triangle, split_sides=split_sides, special_side=special_side
    )
    membership = _point_membership(points, child_triangles)
    children: list[smooth_paint.PaintNode] = []
    budget.add()
    for index, (child, child_triangle) in enumerate(
        zip(child_nodes, child_triangles, strict=True)
    ):
        selected = membership == index
        children.append(
            _paint_tree_samples(
                child,
                child_triangle,
                points[selected],
                states[selected],
                state_map=state_map,
                face_ids=face_ids,
                face_id=face_id,
                depth=depth + 1,
                max_depth=max_depth,
                min_edge_pixels=min_edge_pixels,
                budget=budget,
            )
            if bool(np.any(selected))
            else child.clone()
        )
    return smooth_paint.PaintNode.branch(
        tuple(children), split_sides=split_sides, special_side=special_side
    ).collapse()


def _tree_code(node: smooth_paint.PaintNode | None) -> str | None:
    return None if node is None else smooth_paint.encode_paint_color(node)


def _check_cancel(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and bool(cancelled()):
        raise DecalProjectionCancelled("デカール処理をキャンセルしました")


def plan_decal_bake(
    level: MeshLevel,
    session: PaintSession,
    preview: DecalPreview,
    camera: object,
    render_size: tuple[int, int],
    existing_trees: Mapping[int, smooth_paint.PaintNode] | None,
    *,
    protect_manual: bool = True,
    max_projection_angle_degrees: float = 75.0,
    max_depth: int = smooth_paint.MAX_DEPTH,
    min_edge_pixels: float = 0.75,
    max_candidate_faces: int = 100_000,
    max_adaptive_roots: int = 25_000,
    max_total_nodes: int = 1_000_000,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> DecalBakePlan:
    """Build adaptive decal trees on a worker thread without mutating paint."""

    if level is not session.level:
        raise DecalProjectionError("デカール対象と手修正モデルが一致しません")
    width, height = (int(render_size[0]), int(render_size[1]))
    if preview.state_map.shape != (height, width):
        raise DecalStalePreviewError("3D表示サイズが変わったためデカールを再配置してください")
    depth_limit = int(max_depth)
    if depth_limit < 0 or depth_limit > smooth_paint.MAX_DEPTH:
        raise DecalProjectionError(f"デカール品質は0～{smooth_paint.MAX_DEPTH}で指定してください")
    if not math.isfinite(float(min_edge_pixels)) or float(min_edge_pixels) < 0.0:
        raise DecalProjectionError("最小境界サイズが不正です")
    candidates = np.asarray(preview.candidate_faces, dtype=np.int32)
    if len(candidates) > int(max_candidate_faces):
        raise DecalProjectionError(
            f"デカール対象面が多すぎます: {len(candidates):,} / {int(max_candidate_faces):,}"
        )
    _check_cancel(cancelled)
    if progress is not None:
        progress("surface", 0.02)
    island = _surface_island(
        session,
        preview.support_faces,
        preview.anchor_face,
        max_projection_angle_degrees,
    )
    connected = np.asarray(
        [face for face in candidates if int(face) in island], dtype=np.int32
    )
    disconnected = len(candidates) - len(connected)
    if len(connected) == 0:
        return DecalBakePlan(
            mesh_fingerprint=session.fingerprint,
            frame_generation=preview.frame_generation,
            camera_signature=_camera_signature(camera),
            face_indices=_readonly(np.empty(0, dtype=np.int32), np.int32),
            expected_overrides=_readonly(np.empty(0, dtype=np.int8), np.int8),
            expected_tree_codes=MappingProxyType({}),
            nodes_by_face=MappingProxyType({}),
            protected_faces=0,
            disconnected_faces=disconnected,
            adaptive_roots=0,
            total_nodes=0,
            target_pixels=0,
        )

    tree_store = dict(existing_trees or {})
    protected = np.zeros(len(connected), dtype=bool)
    if bool(protect_manual):
        protected = (session.overrides[connected] >= 0) | np.asarray(
            [int(face) in tree_store for face in connected], dtype=bool
        )
    work_faces = connected[~protected]
    protected_count = int(np.count_nonzero(protected))
    if len(work_faces) == 0:
        return DecalBakePlan(
            mesh_fingerprint=session.fingerprint,
            frame_generation=preview.frame_generation,
            camera_signature=_camera_signature(camera),
            face_indices=_readonly(np.empty(0, dtype=np.int32), np.int32),
            expected_overrides=_readonly(np.empty(0, dtype=np.int8), np.int8),
            expected_tree_codes=MappingProxyType({}),
            nodes_by_face=MappingProxyType({}),
            protected_faces=protected_count,
            disconnected_faces=disconnected,
            adaptive_roots=0,
            total_nodes=0,
            target_pixels=0,
        )

    triangles = _project_triangles(level, work_faces, camera, (width, height))
    # Keep transparent pixels on the visible target roots in the recursive
    # sample set.  Supplying only opaque pixels would make an otherwise solid
    # decal incorrectly fill every transparent hole in a PNG/SVG logo.
    face_filter = np.zeros(len(level.faces), dtype=bool)
    face_filter[work_faces] = True
    visible_id = (preview.face_ids >= 0) & (preview.face_ids < len(face_filter))
    surface_mask = np.zeros(preview.face_ids.shape, dtype=bool)
    if bool(np.any(visible_id)):
        surface_mask[visible_id] = face_filter[preview.face_ids[visible_id]]
    surface_y, surface_x = np.nonzero(surface_mask)
    surface_face = preview.face_ids[surface_y, surface_x]
    surface_state = preview.state_map[surface_y, surface_x]
    order = np.argsort(surface_face, kind="stable")
    surface_y, surface_x, surface_face, surface_state = (
        values[order]
        for values in (surface_y, surface_x, surface_face, surface_state)
    )
    starts = np.searchsorted(surface_face, work_faces, side="left")
    stops = np.searchsorted(surface_face, work_faces, side="right")
    effective = session.effective_indices_for_faces(work_faces)
    budget = _NodeBudget(max(1, int(max_total_nodes)))
    changed_nodes: dict[int, smooth_paint.PaintNode] = {}
    expected_codes: dict[int, str | None] = {}
    expected_values: list[int] = []
    changed_faces: list[int] = []
    adaptive_roots = 0
    target_pixels = 0
    for offset, face in enumerate(work_faces):
        if offset % 128 == 0:
            _check_cancel(cancelled)
            if progress is not None:
                progress("adaptive", 0.05 + 0.90 * offset / max(1, len(work_faces)))
        start, stop = int(starts[offset]), int(stops[offset])
        if start == stop:
            continue
        points = np.column_stack(
            (surface_x[start:stop].astype(np.float64) + 0.5,
             surface_y[start:stop].astype(np.float64) + 0.5)
        )
        states = surface_state[start:stop].astype(np.int8, copy=False)
        face_target_pixels = int(np.count_nonzero(states >= 0))
        if face_target_pixels == 0:
            continue
        face_id = int(face)
        existing = tree_store.get(face_id)
        root = existing.clone() if existing is not None else smooth_paint.PaintNode(int(effective[offset]))
        result = _paint_tree_samples(
            root,
            triangles[offset],
            points,
            states,
            state_map=preview.state_map,
            face_ids=preview.face_ids,
            face_id=face_id,
            depth=0,
            max_depth=depth_limit,
            min_edge_pixels=float(min_edge_pixels),
            budget=budget,
        ).collapse()
        if existing is not None and _tree_code(existing) == _tree_code(result):
            continue
        if existing is None and result.is_leaf and int(result.state) == int(effective[offset]):
            continue
        if not result.is_leaf:
            adaptive_roots += 1
            if adaptive_roots > int(max_adaptive_roots):
                raise DecalProjectionError(
                    "デカール境界の細分化面が多すぎます。サイズまたは品質を下げてください"
                )
        changed_faces.append(face_id)
        expected_values.append(int(session.overrides[face_id]))
        expected_codes[face_id] = _tree_code(existing)
        changed_nodes[face_id] = result.clone()
        target_pixels += face_target_pixels
    _check_cancel(cancelled)
    if progress is not None:
        progress("done", 1.0)
    indices = np.asarray(changed_faces, dtype=np.int32)
    return DecalBakePlan(
        mesh_fingerprint=session.fingerprint,
        frame_generation=preview.frame_generation,
        camera_signature=_camera_signature(camera),
        face_indices=_readonly(indices, np.int32),
        expected_overrides=_readonly(np.asarray(expected_values, dtype=np.int8), np.int8),
        expected_tree_codes=MappingProxyType(dict(expected_codes)),
        nodes_by_face=MappingProxyType(
            {face: node.clone() for face, node in changed_nodes.items()}
        ),
        protected_faces=protected_count,
        disconnected_faces=disconnected,
        adaptive_roots=adaptive_roots,
        total_nodes=budget.count,
        target_pixels=target_pixels,
    )


def _attach_tree_history(
    command: PaintCommand,
    keys: set[int],
    before: Mapping[int, smooth_paint.PaintNode],
    after: Mapping[int, smooth_paint.PaintNode],
) -> None:
    """Attach the exact attributes consumed by smooth_paint_hotfix Undo/Redo."""

    object.__setattr__(command, "_hotfix_tree_keys", frozenset(keys))
    object.__setattr__(
        command, "_hotfix_tree_before", {key: node.clone() for key, node in before.items()}
    )
    object.__setattr__(
        command, "_hotfix_tree_after", {key: node.clone() for key, node in after.items()}
    )


def commit_decal_bake(
    session: PaintSession,
    tree_store: dict[int, smooth_paint.PaintNode],
    tree_owner: object | None,
    plan: DecalBakePlan,
    *,
    label: str = "デカール",
    current_frame_generation: int | None = None,
    current_camera: object | None = None,
    render_dirty: bool = False,
) -> DecalBakeResult:
    """Atomically commit one plan as one tree-aware Undo command."""

    if bool(render_dirty):
        raise DecalStalePreviewError("視点変更後の描画が未完了です。デカールを再確認してください")
    if plan.frame_generation is not None and current_frame_generation != plan.frame_generation:
        raise DecalStalePreviewError("3D表示が変わったためデカールを再配置してください")
    if current_camera is not None and _camera_signature(current_camera) != plan.camera_signature:
        raise DecalStalePreviewError("視点が変わったためデカールを再配置してください")
    if session.fingerprint != plan.mesh_fingerprint:
        raise DecalStalePreviewError("形状が変わったためデカールを適用できません")
    if getattr(session, "_stroke_before", None) is not None:
        raise DecalProjectionError("進行中のブラシ操作を確定してからデカールを適用してください")
    indices = np.asarray(plan.face_indices, dtype=np.int32)
    if len(indices) == 0:
        return DecalBakeResult(indices.copy(), 0, 0, plan.target_pixels, None)
    if not bool(np.all(session.allowed_face_mask[indices])):
        raise DecalStalePreviewError("編集パーツが変わったためデカールを再配置してください")
    if not np.array_equal(session.overrides[indices], plan.expected_overrides):
        raise DecalStalePreviewError("手修正が変わったためデカールを再配置してください")
    for face in indices:
        face_id = int(face)
        if _tree_code(tree_store.get(face_id)) != plan.expected_tree_codes.get(face_id):
            raise DecalStalePreviewError("滑らかな手修正が変わったためデカールを再配置してください")

    before_values = session.overrides[indices].copy()
    before_nodes = {
        int(face): tree_store[int(face)].clone()
        for face in indices
        if int(face) in tree_store
    }
    after_nodes: dict[int, smooth_paint.PaintNode] = {}
    after_values = np.empty(len(indices), dtype=np.int8)
    automatic = np.asarray(session.auto_indices, dtype=np.int8)
    try:
        for offset, raw_face in enumerate(indices):
            face = int(raw_face)
            node = plan.nodes_by_face[face].clone().collapse()
            if node.is_leaf:
                tree_store.pop(face, None)
                state = int(node.state)
                after_values[offset] = -1 if state == int(automatic[face]) else state
            else:
                tree_store[face] = node.clone()
                after_nodes[face] = node.clone()
                after_values[offset] = node.dominant_state()
        session.overrides[indices] = after_values
        command = PaintCommand(
            indices.copy(), before_values, after_values.copy(), str(label)
        )
        _attach_tree_history(command, set(int(face) for face in indices), before_nodes, after_nodes)
        session._push_command(command)
    except Exception:
        session.overrides[indices] = before_values
        for raw_face in indices:
            tree_store.pop(int(raw_face), None)
        for face, node in before_nodes.items():
            tree_store[face] = node.clone()
        raise
    if tree_owner is not None:
        setattr(
            tree_owner,
            "_hotfix_tree_revision",
            int(getattr(tree_owner, "_hotfix_tree_revision", 0)) + 1,
        )
    adaptive = sum(1 for face in indices if int(face) in after_nodes)
    return DecalBakeResult(
        changed_faces=indices.copy(),
        adaptive_roots=adaptive,
        uniform_roots=len(indices) - adaptive,
        target_pixels=plan.target_pixels,
        command=command,
    )


__all__ = [
    "DecalBakePlan",
    "DecalBakeResult",
    "DecalMode",
    "DecalPreview",
    "DecalPreviewMetrics",
    "DecalProjectionCancelled",
    "DecalProjectionError",
    "DecalStalePreviewError",
    "DecalTransform",
    "build_decal_preview",
    "commit_decal_bake",
    "composite_planned_decal_preview",
    "composite_decal_preview",
    "decal_width_mm_to_pixels",
    "plan_decal_bake",
    "rasterize_decal_bake_plan",
    "rasterize_existing_tree_states",
]
