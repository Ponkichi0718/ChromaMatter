"""Geometry-aware colour stylisation for 2D-painted figure finishes.

The normal tone controls only transform colours already stored on the model.
This module adds a deterministic, view-oriented key light and stepped shading
without changing vertices, faces, parts, or manual paint.  The result is still
ordinary RGB and therefore flows through the existing palette mapper, preview,
project, OBJ, and 3MF paths.

The filter intentionally stays simple and bounded.  It is not a screen-space
render effect: the generated shades are baked into printable colour targets.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np


ILLUSTRATION_MODES: Final[tuple[str, ...]] = ("off", "cel", "noir")
ILLUSTRATION_LIGHTS: Final[tuple[str, ...]] = (
    "front_left",
    "front",
    "front_right",
)

_LIGHT_DIRECTIONS: Final[dict[str, tuple[float, float, float]]] = {
    # The fixed front preview camera looks from -Y.  The first vector mirrors
    # the established preview light closely, so baked shade and editor lighting
    # remain understandable together.
    "front_left": (-0.25, -0.75, 0.62),
    "front": (0.0, -0.93, 0.37),
    "front_right": (0.25, -0.75, 0.62),
}
_VIEW_DIRECTION: Final[np.ndarray] = np.asarray(
    (0.0, -1.0, 0.0), dtype=np.float64
)
_NORMAL_BATCH_FACES: Final[int] = 100_000


class IllustrationFilterError(ValueError):
    """Raised when an illustration-filter request is unsafe or invalid."""


def _validated_geometry(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    geometry = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(faces)
    if geometry.ndim != 2 or geometry.shape[1] != 3:
        raise IllustrationFilterError("vertices must be a Vx3 array")
    if not bool(np.all(np.isfinite(geometry))):
        raise IllustrationFilterError("vertices contain a non-finite value")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise IllustrationFilterError("faces must be an Fx3 array")
    if not np.issubdtype(triangles.dtype, np.integer):
        raise IllustrationFilterError("faces must contain integer indices")
    if len(triangles) and (
        int(triangles.min()) < 0 or int(triangles.max()) >= len(geometry)
    ):
        raise IllustrationFilterError("faces contain an out-of-range index")
    # Keep the importer's compact int32 indices.  NumPy indexing accepts them,
    # and avoiding an unconditional int64 copy matters on large models.
    return geometry, np.ascontiguousarray(triangles)


def _validated_colors(
    colors: np.ndarray,
    expected_rows: int,
    *,
    owner: str,
) -> np.ndarray:
    rgb = np.asarray(colors, dtype=np.float64)
    if rgb.shape != (expected_rows, 3):
        raise IllustrationFilterError(
            f"colors must contain one RGB row per {owner}"
        )
    if not bool(np.all(np.isfinite(rgb))):
        raise IllustrationFilterError("colors contain a non-finite value")
    return np.clip(rgb, 0.0, 1.0)


def _vertex_normal_sums(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Return area-weighted normal sums with bounded temporary allocation."""

    sums = np.zeros((len(vertices), 3), dtype=np.float64)
    for start in range(0, len(faces), _NORMAL_BATCH_FACES):
        current = faces[start : start + _NORMAL_BATCH_FACES]
        triangle = vertices[current]
        cross = np.cross(
            triangle[:, 1] - triangle[:, 0],
            triangle[:, 2] - triangle[:, 0],
        )
        for corner in range(3):
            np.add.at(sums, current[:, corner], cross)
    return sums


def _vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Return area-weighted normals with a bounded temporary allocation."""

    normals = _vertex_normal_sums(vertices, faces)
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1.0e-15
    normals[valid] /= lengths[valid, None]
    normals[~valid] = np.asarray((0.0, -0.5, 0.8660254), dtype=np.float64)
    return normals


def _face_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Return one independent normal per printable triangle."""

    triangle = vertices[faces]
    normals = np.cross(
        triangle[:, 1] - triangle[:, 0],
        triangle[:, 2] - triangle[:, 0],
    )
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1.0e-15
    normals[valid] /= lengths[valid, None]
    normals[~valid] = np.asarray((0.0, -0.5, 0.8660254), dtype=np.float64)
    return normals


def _oriented_faces_for_normals(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> np.ndarray:
    """Return a geometry-preserving, coherently wound normal source.

    The actual model topology is never changed.  Trimesh only swaps the last
    two indices where needed, making neighbouring triangles coherent and
    orienting each closed body outward.  Open components retain a consistent
    orientation without being folded toward the camera.  Validation is
    batched so a malformed third-party implementation cannot reorder or
    replace triangles unnoticed.
    """

    if len(faces) == 0:
        return np.ascontiguousarray(faces.copy())
    try:
        import trimesh

        mesh = trimesh.Trimesh(
            vertices=vertices,
            faces=np.asarray(faces).copy(),
            process=False,
        )
        mesh.fix_normals(multibody=True)
        oriented = np.asarray(mesh.faces)
    except Exception as exc:
        raise IllustrationFilterError(
            f"could not orient illustration-filter normals: {exc}"
        ) from exc
    if oriented.shape != faces.shape:
        raise IllustrationFilterError(
            "normal orientation changed the triangle count"
        )
    for start in range(0, len(faces), _NORMAL_BATCH_FACES):
        stop = min(start + _NORMAL_BATCH_FACES, len(faces))
        if not np.array_equal(
            np.sort(oriented[start:stop], axis=1),
            np.sort(faces[start:stop], axis=1),
        ):
            raise IllustrationFilterError(
                "normal orientation changed triangle geometry"
            )
    return np.ascontiguousarray(oriented, dtype=faces.dtype)


def _srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )


def _linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    positive = np.maximum(rgb, 0.0)
    return np.where(
        positive <= 0.0031308,
        positive * 12.92,
        1.055 * np.power(positive, 1.0 / 2.4) - 0.055,
    )


def _stepped(values: np.ndarray, bands: int) -> np.ndarray:
    # Midpoint rounding gives both end points a half-width bin and avoids the
    # permanently dark result produced by floor quantisation.
    scale = float(bands - 1)
    return np.floor(np.clip(values, 0.0, 1.0) * scale + 0.5) / scale


def _validated_controls(
    mode: str,
    strength: float,
    bands: int,
    light: str,
) -> tuple[str, float, int, str]:
    normalized_mode = str(mode).strip().lower()
    normalized_light = str(light).strip().lower()
    if normalized_mode not in ILLUSTRATION_MODES:
        raise IllustrationFilterError(f"unknown illustration mode: {mode}")
    if normalized_light not in ILLUSTRATION_LIGHTS:
        raise IllustrationFilterError(f"unknown illustration light: {light}")
    amount = float(strength)
    if not math.isfinite(amount) or amount < 0.0 or amount > 1.0:
        raise IllustrationFilterError("illustration strength must be in 0..1")
    if isinstance(bands, bool) or int(bands) != bands or not 2 <= int(bands) <= 6:
        raise IllustrationFilterError("illustration bands must be an integer in 2..6")
    return normalized_mode, amount, int(bands), normalized_light


def _style_rgb(
    rgb: np.ndarray,
    normals: np.ndarray,
    *,
    mode: str,
    amount: float,
    bands: int,
    light: str,
) -> np.ndarray:
    if amount <= 0.0:
        return np.ascontiguousarray(rgb.copy())
    light_vector = np.asarray(_LIGHT_DIRECTIONS[light], dtype=np.float64)
    light_vector /= np.linalg.norm(light_vector)

    # Wrapped Lambert shading keeps the back half readable while still
    # producing decisive painted shadow bands.  A fixed-front grazing term
    # darkens silhouettes and strong folds without creating new geometry.
    diffuse = np.einsum("ij,j->i", normals, light_vector, optimize=True)
    wrapped = np.clip((diffuse + 0.28) / 1.28, 0.0, 1.0)
    facing = np.abs(
        np.einsum("ij,j->i", normals, _VIEW_DIRECTION, optimize=True)
    )
    outline = np.power(np.clip(1.0 - facing, 0.0, 1.0), 4.0)

    linear = _srgb_to_linear(rgb)
    if mode == "cel":
        # Fold/silhouette emphasis is quantised together with Lambert light.
        # Applying a continuous outline after stepping would silently create
        # hundreds of extra shades despite a 2-6 band selection.
        graphic_light = _stepped(
            np.clip(wrapped * (1.0 - 0.30 * outline), 0.0, 1.0),
            bands,
        )
        shade_factor = 0.34 + 0.72 * graphic_light
        styled = _linear_to_srgb(
            np.clip(linear * shade_factor[:, None], 0.0, 1.0)
        )
        output = rgb * (1.0 - amount) + styled * amount
    else:
        stepped_light = _stepped(wrapped, bands)
        source_luminance = np.einsum(
            "ij,j->i",
            linear,
            np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float64),
            optimize=True,
        )
        generated_luminance = 0.08 + 0.90 * stepped_light
        luminance = (
            source_luminance * (1.0 - 0.72 * amount)
            + generated_luminance * (0.72 * amount)
        )
        luminance *= 1.0 - 0.42 * amount * outline
        luminance = _stepped(np.clip(luminance, 0.0, 1.0), bands)
        output = _linear_to_srgb(np.repeat(luminance[:, None], 3, axis=1))

    return np.ascontiguousarray(np.clip(output, 0.0, 1.0), dtype=np.float64)


def apply_illustration_filter(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    *,
    mode: str,
    strength: float,
    bands: int,
    light: str,
) -> np.ndarray:
    """Return a vertex-colour approximation of the illustration finish."""

    normalized_mode, amount, band_count, normalized_light = _validated_controls(
        mode, strength, bands, light
    )
    geometry, triangles = _validated_geometry(vertices, faces)
    rgb = _validated_colors(colors, len(geometry), owner="vertex")
    if normalized_mode == "off" or len(rgb) == 0:
        return np.ascontiguousarray(rgb.copy())
    normal_faces = _oriented_faces_for_normals(geometry, triangles)
    return _style_rgb(
        rgb,
        _vertex_normals(geometry, normal_faces),
        mode=normalized_mode,
        amount=amount,
        bands=band_count,
        light=normalized_light,
    )


def apply_illustration_filter_faces(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_colors: np.ndarray,
    *,
    mode: str,
    strength: float,
    bands: int,
    light: str,
) -> np.ndarray:
    """Apply stepped shading independently to printable triangles.

    Cel bands must not be averaged through shared vertices: that would create
    extra intermediate bands and make armour creases depend on whether an
    importer happened to split a vertex.  This face-level path is therefore
    the authoritative input to palette assignment and 3MF output.
    """

    normalized_mode, amount, band_count, normalized_light = _validated_controls(
        mode, strength, bands, light
    )
    geometry, triangles = _validated_geometry(vertices, faces)
    rgb = _validated_colors(face_colors, len(triangles), owner="face")
    if normalized_mode == "off" or len(rgb) == 0:
        return np.ascontiguousarray(rgb.copy())
    output = np.empty_like(rgb)
    normal_faces = _oriented_faces_for_normals(geometry, triangles)
    for start in range(0, len(triangles), _NORMAL_BATCH_FACES):
        stop = min(start + _NORMAL_BATCH_FACES, len(triangles))
        current = normal_faces[start:stop]
        output[start:stop] = _style_rgb(
            rgb[start:stop],
            _face_normals(geometry, current),
            mode=normalized_mode,
            amount=amount,
            bands=band_count,
            light=normalized_light,
        )
    return np.ascontiguousarray(output)


__all__ = [
    "ILLUSTRATION_LIGHTS",
    "ILLUSTRATION_MODES",
    "IllustrationFilterError",
    "apply_illustration_filter",
    "apply_illustration_filter_faces",
]
