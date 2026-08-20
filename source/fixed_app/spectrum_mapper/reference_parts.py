from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .mixer import PALETTE_STATE_COUNT
from PIL import Image, ImageOps
from scipy import ndimage

from .models import ColorResult, MeshLevel


DEFAULT_RENDER_SIZE = (512, 512)
DEFAULT_CORNER_FRACTION = 0.04
DEFAULT_BACKGROUND_RGB_DISTANCE = 30.0
DEFAULT_MINIMUM_IOU = 0.30
DEFAULT_MAX_SAMPLES_PER_PART = 20_000
DEFAULT_MAX_TOTAL_SAMPLES = 100_000


RenderFrontCallback = Callable[..., Image.Image | np.ndarray]
BBox = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class ForegroundExtraction:
    rgb: np.ndarray
    mask: np.ndarray
    bbox: BBox | None
    corner_rgb: tuple[tuple[int, int, int], ...]
    foreground_fraction: float


@dataclass(frozen=True, slots=True)
class ReferencePartSamples:
    part_id: int
    part_key: str
    part_name: str
    rgb_samples: np.ndarray
    confidence: float
    visible_pixels: int
    matched_pixels: int

    @property
    def sample_count(self) -> int:
        return int(len(self.rgb_samples))


@dataclass(frozen=True, slots=True)
class ReferencePartMatch:
    matched: bool
    mirrored: bool
    confidence: float
    selected_iou: float
    normal_iou: float
    mirrored_iou: float
    foreground_bbox: BBox | None
    silhouette_bbox: BBox | None
    render_size: tuple[int, int]
    foreground_fraction: float
    parts: tuple[ReferencePartSamples, ...]
    reason: str

    @property
    def fallback_used(self) -> bool:
        return not self.matched

    @property
    def samples_by_part_id(self) -> dict[int, ReferencePartSamples]:
        return {part.part_id: part for part in self.parts}


def _coerce_reference_image(
    value: Path | str | Image.Image | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(value, (str, Path)):
        with Image.open(Path(value)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
        rgba = np.asarray(image, dtype=np.uint8)
    elif isinstance(value, Image.Image):
        rgba = np.asarray(
            ImageOps.exif_transpose(value.copy()).convert("RGBA"),
            dtype=np.uint8,
        )
    else:
        raw = np.asarray(value)
        if raw.ndim != 3 or raw.shape[2] not in (3, 4):
            raise ValueError("reference image must be H x W x 3 or H x W x 4")
        if raw.shape[0] < 2 or raw.shape[1] < 2:
            raise ValueError("reference image must be at least 2 x 2 pixels")
        try:
            numeric = raw.astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError("reference image must contain numeric RGB values") from exc
        if not np.all(np.isfinite(numeric)) or np.any(numeric < 0.0):
            raise ValueError("reference image contains invalid RGB values")
        if np.issubdtype(raw.dtype, np.floating) and float(numeric.max()) <= 1.0:
            numeric *= 255.0
        if np.any(numeric > 255.0):
            raise ValueError("reference image RGB values must be in 0..1 or 0..255")
        converted = np.clip(np.rint(numeric), 0, 255).astype(np.uint8)
        if converted.shape[2] == 3:
            alpha = np.full(converted.shape[:2] + (1,), 255, dtype=np.uint8)
            rgba = np.concatenate((converted, alpha), axis=2)
        else:
            rgba = converted
    return rgba[:, :, :3].copy(), rgba[:, :, 3].copy()


def _mask_bbox(mask: np.ndarray) -> BBox | None:
    rows, columns = np.nonzero(mask)
    if len(rows) == 0:
        return None
    return (
        int(columns.min()),
        int(rows.min()),
        int(columns.max()) + 1,
        int(rows.max()) + 1,
    )


def extract_corner_foreground(
    reference: Path | str | Image.Image | np.ndarray,
    *,
    corner_fraction: float = DEFAULT_CORNER_FRACTION,
    background_rgb_distance: float = DEFAULT_BACKGROUND_RGB_DISTANCE,
    alpha_threshold: int = 8,
    minimum_component_pixels: int = 4,
) -> ForegroundExtraction:
    """Remove background regions connected to the four image corners.

    Four corner-patch medians allow a modest background gradient.  A colour is
    removed only when it is both close to a corner colour and connected to the
    image border, which avoids deleting a similarly coloured enclosed region.
    """

    if not math.isfinite(float(corner_fraction)) or not 0.0 < float(
        corner_fraction
    ) <= 0.25:
        raise ValueError("corner_fraction must be in (0, 0.25]")
    if not math.isfinite(float(background_rgb_distance)) or float(
        background_rgb_distance
    ) < 0.0:
        raise ValueError("background_rgb_distance must be non-negative")
    if isinstance(alpha_threshold, bool) or not isinstance(
        alpha_threshold, int
    ) or not 0 <= alpha_threshold <= 255:
        raise ValueError("alpha_threshold must be an integer in 0..255")
    if isinstance(minimum_component_pixels, bool) or not isinstance(
        minimum_component_pixels, int
    ) or minimum_component_pixels < 1:
        raise ValueError("minimum_component_pixels must be positive")

    rgb, alpha = _coerce_reference_image(reference)
    height, width = rgb.shape[:2]
    patch_size = max(1, int(round(min(width, height) * float(corner_fraction))))
    patch_size = min(patch_size, 32, width, height)
    corner_slices = (
        (slice(0, patch_size), slice(0, patch_size)),
        (slice(0, patch_size), slice(width - patch_size, width)),
        (slice(height - patch_size, height), slice(0, patch_size)),
        (
            slice(height - patch_size, height),
            slice(width - patch_size, width),
        ),
    )
    corner_colors = np.asarray(
        [
            np.median(rgb[rows, columns].reshape(-1, 3), axis=0)
            for rows, columns in corner_slices
        ],
        dtype=np.float64,
    )
    pixel_rgb = rgb.astype(np.int32)
    minimum_distance_squared = np.full((height, width), np.iinfo(np.int32).max)
    for corner_color in np.rint(corner_colors).astype(np.int32):
        delta = pixel_rgb - corner_color[None, None, :]
        distance_squared = np.sum(delta * delta, axis=2)
        np.minimum(
            minimum_distance_squared,
            distance_squared,
            out=minimum_distance_squared,
        )
    background_candidate = (
        minimum_distance_squared <= float(background_rgb_distance) ** 2
    ) | (alpha <= alpha_threshold)

    seeds = np.zeros((height, width), dtype=bool)
    seeds[0, :] = background_candidate[0, :]
    seeds[-1, :] = background_candidate[-1, :]
    seeds[:, 0] = background_candidate[:, 0]
    seeds[:, -1] = background_candidate[:, -1]
    connected_background = ndimage.binary_propagation(
        seeds,
        structure=np.asarray(((0, 1, 0), (1, 1, 1), (0, 1, 0)), dtype=bool),
        mask=background_candidate,
    )
    foreground = (alpha > alpha_threshold) & ~connected_background

    labels, component_count = ndimage.label(foreground)
    if component_count:
        counts = np.bincount(labels.reshape(-1))
        keep_labels = np.flatnonzero(counts >= minimum_component_pixels)
        keep_labels = keep_labels[keep_labels != 0]
        foreground = np.isin(labels, keep_labels)

    bbox = _mask_bbox(foreground)
    return ForegroundExtraction(
        rgb=rgb,
        mask=foreground,
        bbox=bbox,
        corner_rgb=tuple(
            tuple(int(channel) for channel in np.rint(color).astype(np.uint8))
            for color in corner_colors
        ),
        foreground_fraction=float(np.count_nonzero(foreground) / foreground.size),
    )


def _part_color(part_id: int) -> tuple[int, int, int]:
    # Multiplication by an odd number is one-to-one modulo 2**24, giving a
    # stable, non-black RGB key for every practical part id.
    value = ((int(part_id) + 1) * 0x9E3779) & 0xFFFFFF
    if value == 0:
        value = 1
    return (value >> 16, (value >> 8) & 0xFF, value & 0xFF)


def _mesh_part_metadata(
    level: MeshLevel,
) -> tuple[np.ndarray, tuple[str, ...], tuple[str, ...]]:
    faces = np.asarray(level.faces)
    raw_ids = np.asarray(level.face_part_ids)
    if raw_ids.size == 0:
        face_part_ids = np.zeros(len(faces), dtype=np.int32)
    else:
        if raw_ids.shape != (len(faces),) or not np.issubdtype(
            raw_ids.dtype, np.integer
        ):
            raise ValueError("MeshLevel.face_part_ids must match level.faces")
        face_part_ids = raw_ids.astype(np.int32, copy=False)
    if len(face_part_ids) and int(face_part_ids.min()) < 0:
        raise ValueError("MeshLevel.face_part_ids must be non-negative")
    maximum_id = int(face_part_ids.max()) if len(face_part_ids) else 0
    part_count = max(maximum_id + 1, len(level.part_names), len(level.part_keys), 1)
    names = tuple(
        level.part_names[index]
        if index < len(level.part_names) and level.part_names[index]
        else f"part_{index}"
        for index in range(part_count)
    )
    keys = tuple(
        level.part_keys[index]
        if index < len(level.part_keys) and level.part_keys[index]
        else f"part_{index}"
        for index in range(part_count)
    )
    return face_part_ids, names, keys


def _dummy_part_color_result(
    level: MeshLevel,
    face_part_ids: np.ndarray,
) -> tuple[ColorResult, dict[int, tuple[int, int, int]]]:
    color_map = {
        part_id: _part_color(part_id)
        for part_id in sorted(int(value) for value in np.unique(face_part_ids))
    }
    encoded_rgb = np.asarray(
        [color_map[int(part_id)] for part_id in face_part_ids],
        dtype=np.float64,
    ) / 255.0
    # render_front_preview applies pow(color, 1 / 1.04) even with shading
    # disabled.  Its inverse keeps the framebuffer bytes at the desired ID
    # colours instead of making the decoder depend on display gamma.
    face_rgb = np.power(encoded_rgb, 1.04)
    return (
        ColorResult(
            tone_vertex_rgb=np.zeros(
                (len(level.vertices_unit), 3), dtype=np.float64
            ),
            source_face_rgb=face_rgb,
            palette_indices=np.zeros(len(level.faces), dtype=np.int8),
            target_face_rgb=face_rgb,
            delta_e=np.zeros(len(level.faces), dtype=np.float64),
            smoothed_faces=0,
            palette_face_counts=np.zeros(PALETTE_STATE_COUNT, dtype=np.int64),
            palette_area_fractions=np.zeros(PALETTE_STATE_COUNT, dtype=np.float64),
            pink_area_fraction=0.0,
        ),
        color_map,
    )


def _decode_rendered_part_ids(
    rendered: Image.Image | np.ndarray,
    color_map: dict[int, tuple[int, int, int]],
) -> np.ndarray:
    if isinstance(rendered, Image.Image):
        raw = np.asarray(rendered.convert("RGB"), dtype=np.uint8)
    else:
        raw = np.asarray(rendered)
    if raw.ndim == 2:
        if not np.issubdtype(raw.dtype, np.integer):
            raise ValueError("2D part-id render must contain integers")
        return raw.astype(np.int32, copy=True)
    if raw.ndim != 3 or raw.shape[2] not in (3, 4):
        raise ValueError("part-id renderer must return a 2D id map or RGB image")
    rgb = raw[:, :, :3].astype(np.uint32, copy=False)
    result = np.full(rgb.shape[:2], -1, dtype=np.int32)
    best_distance = np.full(rgb.shape[:2], np.iinfo(np.int32).max, dtype=np.int32)
    pixel_rgb = rgb.astype(np.int32, copy=False)
    for part_id, color in color_map.items():
        expected = np.asarray(color, dtype=np.int32)
        distance = np.sum((pixel_rgb - expected[None, None, :]) ** 2, axis=2)
        better = distance < best_distance
        result[better] = part_id
        best_distance[better] = distance[better]
    # One framebuffer quantization step per channel is expected; a radius of
    # four tolerates driver rounding without admitting black background or
    # antialiased boundary colours as a part.
    result[best_distance > 4**2] = -1
    return result


def render_front_part_ids(
    level: MeshLevel,
    *,
    size: tuple[int, int] = DEFAULT_RENDER_SIZE,
    render_callback: RenderFrontCallback | None = None,
) -> np.ndarray:
    """Render a front-view integer part-id map.

    The injected callback follows ``render_front_preview(level, result, ...)``.
    For OpenGL-free tests it may directly return a 2D integer map using ``-1``
    for background.
    """

    if len(size) != 2 or int(size[0]) < 8 or int(size[1]) < 8:
        raise ValueError("render size must contain width and height of at least 8")
    face_part_ids, names, _keys = _mesh_part_metadata(level)
    result, color_map = _dummy_part_color_result(level, face_part_ids)
    if render_callback is None:
        from .renderer import render_front_preview

        render_callback = render_front_preview
    rendered = render_callback(
        level,
        result,
        mode="target",
        size=(int(size[0]), int(size[1])),
        background=(0, 0, 0),
        shaded=False,
    )
    part_ids = _decode_rendered_part_ids(rendered, color_map)
    if part_ids.ndim != 2 or part_ids.size == 0:
        raise ValueError("part-id renderer returned an empty map")
    visible = part_ids[part_ids >= 0]
    if len(visible) and int(visible.max()) >= len(names):
        raise ValueError("part-id renderer returned an unknown part id")
    return part_ids


def _normalize_reference_to_silhouette(
    extraction: ForegroundExtraction,
    silhouette_shape: tuple[int, int],
    silhouette_bbox: BBox,
    *,
    mirrored: bool,
) -> tuple[np.ndarray, np.ndarray]:
    if extraction.bbox is None:
        raise ValueError("reference foreground is empty")
    source_left, source_top, source_right, source_bottom = extraction.bbox
    target_left, target_top, target_right, target_bottom = silhouette_bbox
    source_rgb = extraction.rgb[
        source_top:source_bottom, source_left:source_right
    ]
    source_mask = extraction.mask[
        source_top:source_bottom, source_left:source_right
    ]
    if mirrored:
        source_rgb = np.flip(source_rgb, axis=1)
        source_mask = np.flip(source_mask, axis=1)
    target_width = target_right - target_left
    target_height = target_bottom - target_top
    resized_rgb = np.asarray(
        Image.fromarray(source_rgb, mode="RGB").resize(
            (target_width, target_height),
            resample=Image.Resampling.BILINEAR,
        ),
        dtype=np.uint8,
    )
    resized_mask = np.asarray(
        Image.fromarray(source_mask.astype(np.uint8) * 255, mode="L").resize(
            (target_width, target_height),
            resample=Image.Resampling.NEAREST,
        ),
        dtype=np.uint8,
    ) > 0
    normalized_rgb = np.zeros(silhouette_shape + (3,), dtype=np.uint8)
    normalized_mask = np.zeros(silhouette_shape, dtype=bool)
    normalized_rgb[
        target_top:target_bottom, target_left:target_right
    ] = resized_rgb
    normalized_mask[
        target_top:target_bottom, target_left:target_right
    ] = resized_mask
    return normalized_rgb, normalized_mask


def _intersection_over_union(first: np.ndarray, second: np.ndarray) -> float:
    union = np.count_nonzero(first | second)
    if union == 0:
        return 0.0
    return float(np.count_nonzero(first & second) / union)


def _empty_part_samples(
    visible_ids: Sequence[int],
    names: tuple[str, ...],
    keys: tuple[str, ...],
    part_ids: np.ndarray,
) -> tuple[ReferencePartSamples, ...]:
    return tuple(
        ReferencePartSamples(
            part_id=int(part_id),
            part_key=keys[int(part_id)],
            part_name=names[int(part_id)],
            rgb_samples=np.empty((0, 3), dtype=np.uint8),
            confidence=0.0,
            visible_pixels=int(np.count_nonzero(part_ids == part_id)),
            matched_pixels=0,
        )
        for part_id in visible_ids
    )


def _sample_indices(indices: np.ndarray, maximum: int) -> np.ndarray:
    if maximum <= 0 or len(indices) == 0:
        return np.empty(0, dtype=np.int64)
    if len(indices) <= maximum:
        return indices
    positions = np.floor(
        np.arange(maximum, dtype=np.float64) * (len(indices) / maximum)
    ).astype(np.int64)
    return indices[positions]


def match_reference_to_parts(
    level: MeshLevel,
    reference: Path | str | Image.Image | np.ndarray,
    *,
    render_callback: RenderFrontCallback | None = None,
    render_size: tuple[int, int] = DEFAULT_RENDER_SIZE,
    minimum_iou: float = DEFAULT_MINIMUM_IOU,
    max_samples_per_part: int = DEFAULT_MAX_SAMPLES_PER_PART,
    max_total_samples: int = DEFAULT_MAX_TOTAL_SAMPLES,
    corner_fraction: float = DEFAULT_CORNER_FRACTION,
    background_rgb_distance: float = DEFAULT_BACKGROUND_RGB_DISTANCE,
) -> ReferencePartMatch:
    """Map an original image to visible front-view 3D parts.

    Only a simple silhouette correspondence is claimed.  A low-IoU result
    intentionally returns empty samples so the caller can fall back to OBJ
    vertex colours instead of applying unrelated image colours.
    """

    if not math.isfinite(float(minimum_iou)) or not 0.0 <= float(minimum_iou) <= 1.0:
        raise ValueError("minimum_iou must be in 0..1")
    for name, value in (
        ("max_samples_per_part", max_samples_per_part),
        ("max_total_samples", max_total_samples),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")

    _face_ids, names, keys = _mesh_part_metadata(level)
    rendered_part_ids = render_front_part_ids(
        level, size=render_size, render_callback=render_callback
    )
    silhouette = rendered_part_ids >= 0
    silhouette_bbox = _mask_bbox(silhouette)
    visible_ids = tuple(
        int(value) for value in np.unique(rendered_part_ids[silhouette])
    )
    actual_render_size = (
        int(rendered_part_ids.shape[1]),
        int(rendered_part_ids.shape[0]),
    )
    extraction = extract_corner_foreground(
        reference,
        corner_fraction=corner_fraction,
        background_rgb_distance=background_rgb_distance,
    )

    if silhouette_bbox is None or not visible_ids:
        return ReferencePartMatch(
            matched=False,
            mirrored=False,
            confidence=0.0,
            selected_iou=0.0,
            normal_iou=0.0,
            mirrored_iou=0.0,
            foreground_bbox=extraction.bbox,
            silhouette_bbox=silhouette_bbox,
            render_size=actual_render_size,
            foreground_fraction=extraction.foreground_fraction,
            parts=(),
            reason="3D front render contains no visible parts",
        )
    if extraction.bbox is None:
        return ReferencePartMatch(
            matched=False,
            mirrored=False,
            confidence=0.0,
            selected_iou=0.0,
            normal_iou=0.0,
            mirrored_iou=0.0,
            foreground_bbox=None,
            silhouette_bbox=silhouette_bbox,
            render_size=actual_render_size,
            foreground_fraction=0.0,
            parts=_empty_part_samples(
                visible_ids, names, keys, rendered_part_ids
            ),
            reason="reference foreground could not be extracted",
        )

    normal_rgb, normal_mask = _normalize_reference_to_silhouette(
        extraction,
        silhouette.shape,
        silhouette_bbox,
        mirrored=False,
    )
    mirrored_rgb, mirrored_mask = _normalize_reference_to_silhouette(
        extraction,
        silhouette.shape,
        silhouette_bbox,
        mirrored=True,
    )
    normal_iou = _intersection_over_union(normal_mask, silhouette)
    mirrored_iou = _intersection_over_union(mirrored_mask, silhouette)
    mirrored = mirrored_iou > normal_iou
    if mirrored:
        selected_rgb, selected_mask, selected_iou = (
            mirrored_rgb,
            mirrored_mask,
            mirrored_iou,
        )
    else:
        selected_rgb, selected_mask, selected_iou = (
            normal_rgb,
            normal_mask,
            normal_iou,
        )

    if selected_iou < float(minimum_iou):
        return ReferencePartMatch(
            matched=False,
            mirrored=mirrored,
            confidence=float(selected_iou),
            selected_iou=float(selected_iou),
            normal_iou=float(normal_iou),
            mirrored_iou=float(mirrored_iou),
            foreground_bbox=extraction.bbox,
            silhouette_bbox=silhouette_bbox,
            render_size=actual_render_size,
            foreground_fraction=extraction.foreground_fraction,
            parts=_empty_part_samples(
                visible_ids, names, keys, rendered_part_ids
            ),
            reason=(
                f"reference/3D silhouette IoU {selected_iou:.3f} is below "
                f"the {float(minimum_iou):.3f} threshold"
            ),
        )

    total_base = max_total_samples // len(visible_ids)
    total_remainder = max_total_samples % len(visible_ids)
    parts: list[ReferencePartSamples] = []
    for order, part_id in enumerate(visible_ids):
        visible_mask = rendered_part_ids == part_id
        matched_mask = visible_mask & selected_mask
        visible_pixels = int(np.count_nonzero(visible_mask))
        matched_pixels = int(np.count_nonzero(matched_mask))
        total_share = total_base + (1 if order < total_remainder else 0)
        sample_limit = min(max_samples_per_part, total_share)
        flat_indices = np.flatnonzero(matched_mask)
        selected_indices = _sample_indices(flat_indices, sample_limit)
        samples = selected_rgb.reshape(-1, 3)[selected_indices].copy()
        overlap_fraction = matched_pixels / max(visible_pixels, 1)
        part_confidence = float(
            min(1.0, selected_iou * math.sqrt(max(overlap_fraction, 0.0)))
        )
        parts.append(
            ReferencePartSamples(
                part_id=part_id,
                part_key=keys[part_id],
                part_name=names[part_id],
                rgb_samples=samples,
                confidence=part_confidence,
                visible_pixels=visible_pixels,
                matched_pixels=matched_pixels,
            )
        )
    return ReferencePartMatch(
        matched=True,
        mirrored=mirrored,
        confidence=float(selected_iou),
        selected_iou=float(selected_iou),
        normal_iou=float(normal_iou),
        mirrored_iou=float(mirrored_iou),
        foreground_bbox=extraction.bbox,
        silhouette_bbox=silhouette_bbox,
        render_size=actual_render_size,
        foreground_fraction=extraction.foreground_fraction,
        parts=tuple(parts),
        reason="reference foreground matched to the 3D front silhouette",
    )


__all__ = [
    "ForegroundExtraction",
    "ReferencePartMatch",
    "ReferencePartSamples",
    "extract_corner_foreground",
    "match_reference_to_parts",
    "render_front_part_ids",
]
