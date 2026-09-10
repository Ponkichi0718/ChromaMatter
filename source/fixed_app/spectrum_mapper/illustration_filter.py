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


ILLUSTRATION_MODES: Final[tuple[str, ...]] = (
    "off",
    "cel",
    "cel_strong",
    "noir",
)
ILLUSTRATION_LIGHTS: Final[tuple[str, ...]] = (
    "front_left",
    "top",
    "front_right",
    "left",
    "front",
    "right",
    "bottom_left",
    "bottom",
    "bottom_right",
)

_LIGHT_DIRECTIONS: Final[dict[str, tuple[float, float, float]]] = {
    # The fixed front preview camera looks from -Y.  The first vector mirrors
    # the established preview light closely, so baked shade and editor lighting
    # remain understandable together.
    "front_left": (-0.25, -0.75, 0.62),
    "top": (0.0, -0.68, 0.74),
    "front_right": (0.25, -0.75, 0.62),
    "left": (-0.62, -0.78, 0.10),
    "front": (0.0, -0.93, 0.37),
    "right": (0.62, -0.78, 0.10),
    "bottom_left": (-0.45, -0.75, -0.48),
    "bottom": (0.0, -0.75, -0.66),
    "bottom_right": (0.45, -0.75, -0.48),
}
_VIEW_DIRECTION: Final[np.ndarray] = np.asarray(
    (0.0, -1.0, 0.0), dtype=np.float64
)
_NORMAL_BATCH_FACES: Final[int] = 100_000
_DARK_WARM_LUMA_MIN: Final[float] = 0.12
_DARK_WARM_LUMA_MAX: Final[float] = 0.32
_DARK_WARM_RED_GREEN_MIN: Final[float] = 0.035
_DARK_WARM_RED_BLUE_MIN: Final[float] = 0.040
_DARK_WARM_GREEN_BLUE_MIN: Final[float] = -0.005
_DETAIL_WARM_LUMA_MIN: Final[float] = 0.07
_DETAIL_WARM_LUMA_MAX: Final[float] = 0.45
_DETAIL_WARM_RED_GREEN_MIN: Final[float] = 0.020
_DETAIL_WARM_RED_BLUE_MIN: Final[float] = 0.030
_DETAIL_WARM_GREEN_BLUE_MIN: Final[float] = -0.015
_DEFAULT_LIGHT_RANGE: Final[float] = 0.4
_DEFAULT_LIGHT_WRAP: Final[float] = 0.28
_MAX_LIGHT_WRAP: Final[float] = 0.82
_MAX_REAR_FILL: Final[float] = 0.16
_CREASE_SMOOTH_FULL_ANGLE_DEGREES: Final[float] = 5.0
_CREASE_SMOOTH_RELEASE_ANGLE_DEGREES: Final[float] = 20.0


class IllustrationFilterError(ValueError):
    """Raised when an illustration-filter request is unsafe or invalid."""


def strong_cel_dark_warm_mask(source_rgb: np.ndarray) -> np.ndarray:
    """Return dark warm material that should retain a skin/brown colour ramp.

    The deliberately narrow channel-direction gate excludes neutral and mildly
    warm blacks while retaining low-light skin such as ``#3B2B28``.  Keeping
    this classifier beside the filter lets palette mapping and automatic
    filament selection use the exact same material boundary.
    """

    rgb = np.asarray(source_rgb, dtype=np.float64)
    if rgb.ndim != 2 or rgb.shape[1:] != (3,):
        raise IllustrationFilterError("source_rgb must be an Nx3 array")
    if not bool(np.all(np.isfinite(rgb))) or bool(
        np.any((rgb < 0.0) | (rgb > 1.0))
    ):
        raise IllustrationFilterError("source_rgb must contain finite values in 0..1")
    luminance = rgb @ np.asarray((0.2126, 0.7152, 0.0722))
    red_green = rgb[:, 0] - rgb[:, 1]
    red_blue = rgb[:, 0] - rgb[:, 2]
    green_blue = rgb[:, 1] - rgb[:, 2]
    return (
        (luminance >= _DARK_WARM_LUMA_MIN)
        & (luminance <= _DARK_WARM_LUMA_MAX)
        & (red_green >= _DARK_WARM_RED_GREEN_MIN)
        & (red_blue >= _DARK_WARM_RED_BLUE_MIN)
        & (green_blue >= _DARK_WARM_GREEN_BLUE_MIN)
    )


def strong_cel_detail_warm_mask(source_rgb: np.ndarray) -> np.ndarray:
    """Return the wider skin/brown guard used only by the opt-in detail pass.

    The legacy classifier above remains deliberately narrow and unchanged.
    Detail preservation needs a wider guard because a baked shadow can push
    otherwise ordinary skin below that luminance interval.  Channel-direction
    evidence is still required, so neutral/cool black cloth cannot enter this
    family merely because it is dark.
    """

    rgb = np.asarray(source_rgb, dtype=np.float64)
    if rgb.ndim != 2 or rgb.shape[1:] != (3,):
        raise IllustrationFilterError("source_rgb must be an Nx3 array")
    if not bool(np.all(np.isfinite(rgb))) or bool(
        np.any((rgb < 0.0) | (rgb > 1.0))
    ):
        raise IllustrationFilterError("source_rgb must contain finite values in 0..1")
    luminance = rgb @ np.asarray((0.2126, 0.7152, 0.0722))
    return (
        (luminance >= _DETAIL_WARM_LUMA_MIN)
        & (luminance <= _DETAIL_WARM_LUMA_MAX)
        & (rgb[:, 0] - rgb[:, 1] >= _DETAIL_WARM_RED_GREEN_MIN)
        & (rgb[:, 0] - rgb[:, 2] >= _DETAIL_WARM_RED_BLUE_MIN)
        & (rgb[:, 1] - rgb[:, 2] >= _DETAIL_WARM_GREEN_BLUE_MIN)
    )


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


def _crease_aware_face_normals(
    vertices: np.ndarray,
    faces: np.ndarray,
    vertex_normals: np.ndarray,
    *,
    detail_strength: float = 0.0,
) -> np.ndarray:
    """Suppress triangle noise without rounding deliberate sharp folds.

    Generated character meshes often approximate one broad cloth panel with
    thousands of slightly misaligned triangles.  Independent face normals turn
    that harmless tessellation noise into a salt-and-pepper cel pattern.  An
    area-weighted vertex normal provides the stable broad surface direction,
    but it must not be used blindly across armour corners or a garment fold.
    Near-coplanar differences up to five degrees are treated as tessellation
    noise.  Between five and twenty degrees the independent face direction is
    restored progressively, preserving a real shallow wrinkle without turning
    every tiny triangle mismatch back into salt-and-pepper bands.  Larger
    creases keep their independent direction completely.
    """

    face_normals = _face_normals(vertices, faces)
    smooth = vertex_normals[faces].sum(axis=1)
    lengths = np.linalg.norm(smooth, axis=1)
    valid = lengths > 1.0e-15
    smooth[valid] /= lengths[valid, None]
    smooth[~valid] = face_normals[~valid]
    agreement = np.clip(
        np.einsum("ij,ij->i", face_normals, smooth, optimize=True),
        -1.0,
        1.0,
    )
    legacy = face_normals.copy()
    legacy[
        agreement >= math.cos(
            math.radians(_CREASE_SMOOTH_RELEASE_ANGLE_DEGREES)
        )
    ] = smooth[
        agreement >= math.cos(
            math.radians(_CREASE_SMOOTH_RELEASE_ANGLE_DEGREES)
        )
    ]
    amount = float(detail_strength)
    if amount <= 0.0:
        # Return before the normalization needed only by interpolation.  This
        # is the exact former all-or-nothing result, including its floating-
        # point bytes, for every existing project.
        return legacy
    # The explicitly gated detail path restores shallow fold normals
    # progressively.
    angle = np.degrees(np.arccos(agreement))
    release = np.clip(
        (
            angle - _CREASE_SMOOTH_FULL_ANGLE_DEGREES
        )
        / (
            _CREASE_SMOOTH_RELEASE_ANGLE_DEGREES
            - _CREASE_SMOOTH_FULL_ANGLE_DEGREES
        ),
        0.0,
        1.0,
    )
    release = release * release * (3.0 - 2.0 * release)
    enhanced = (
        smooth * (1.0 - release[:, None])
        + face_normals * release[:, None]
    )
    result = legacy * (1.0 - amount) + enhanced * amount
    result_lengths = np.linalg.norm(result, axis=1)
    result_valid = result_lengths > 1.0e-15
    result[result_valid] /= result_lengths[result_valid, None]
    result[~result_valid] = face_normals[~result_valid]
    return result


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
    stepped, _band_ids = _stepped_with_ids(values, bands)
    return stepped


def _stepped_with_ids(
    values: np.ndarray,
    bands: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return quantised light plus its stable 0..bands-1 region ID."""

    # Midpoint rounding gives both end points a half-width bin and avoids the
    # permanently dark result produced by floor quantisation.
    scale = float(bands - 1)
    band_ids = np.floor(
        np.clip(values, 0.0, 1.0) * scale + 0.5
    ).astype(np.uint8)
    return band_ids.astype(np.float64) / scale, band_ids


def _smoothstep01(values: np.ndarray) -> np.ndarray:
    bounded = np.clip(values, 0.0, 1.0)
    return bounded * bounded * (3.0 - 2.0 * bounded)


def _strong_cel_rgb(
    rgb: np.ndarray,
    linear: np.ndarray,
    graphic_light: np.ndarray,
    *,
    light_intensity: float = 1.0,
    detail_strength: float = 0.0,
) -> np.ndarray:
    """Return print-visible cel bands while retaining the source hue.

    Ordinary multiplicative lighting cannot create a grey highlight from a
    black garment: multiplying near-zero RGB values still produces near zero.
    That weak difference is visible on a monitor but is normally swallowed by
    an opaque black filament.  High-contrast cel therefore gives dark faces an
    absolute perceptual-lightness target for each lit band.  The target is
    converted back through linear light and retains a bounded amount of the
    source channel balance, so navy/red/brown highlights remain tinted instead
    of becoming arbitrary white patches.

    The darkest band is deliberately left close to black.  With four bands the
    neutral targets are approximately 5%, 20%, 55%, and 92% sRGB before the
    user strength blend.  The first lit band therefore remains dark ink while
    the two upper bands survive nearest-palette mapping as grey and light-grey
    graphic highlights even at the default 78% strength.
    """

    luminance_weights = np.asarray(
        (0.2126, 0.7152, 0.0722), dtype=np.float64
    )
    source_linear_luminance = np.einsum(
        "ij,j->i", linear, luminance_weights, optimize=True
    )
    source_perceptual_luminance = _linear_to_srgb(
        source_linear_luminance[:, None]
    )[:, 0]

    # Keep the legacy multiplicative character for bright colours, but make
    # its shadow slightly more graphic in the explicitly strong mode.
    shade_factor = np.clip(
        0.26 + 0.80 * graphic_light * light_intensity,
        0.0,
        1.36,
    )
    multiplied = _linear_to_srgb(
        np.clip(linear * shade_factor[:, None], 0.0, 1.0)
    )

    # Generated "black" cloth is frequently stored as blue-black or purple-
    # black.  Restricting absolute highlights to mathematically neutral RGB is
    # why shoes could light correctly while the larger garment stayed almost
    # black.  Treat every genuinely dark material as a graphic ramp: values up
    # to 30% perceived brightness use the full absolute target and then blend
    # back to ordinary colour by 50%.  Hue retention below keeps deliberate
    # navy/red/green/purple and dark skin chromatic.
    base_dark_weight = 1.0 - _smoothstep01(
        (source_perceptual_luminance - 0.30) / (0.50 - 0.30)
    )
    source_span = np.ptp(rgb, axis=1)
    relative_span = source_span / np.maximum(
        source_perceptual_luminance,
        0.04,
    )
    neutral_weight = 1.0 - _smoothstep01(
        (relative_span - 0.25) / (0.85 - 0.25)
    )
    warm_mask = strong_cel_dark_warm_mask(rgb)
    detail = float(detail_strength)
    detail_warm_mask = (
        strong_cel_detail_warm_mask(rgb) if detail > 0.0 else warm_mask
    )
    dark_weight = np.where(
        warm_mask,
        base_dark_weight,
        base_dark_weight * neutral_weight,
    )
    if detail > 0.0:
        shadow_weight = np.power(
            np.clip(1.0 - graphic_light, 0.0, 1.0),
            0.8,
        )
        detail_blend = detail * shadow_weight
        dark_weight = np.where(
            detail_warm_mask,
            dark_weight
            + (base_dark_weight - dark_weight) * detail_blend,
            dark_weight,
        )
    legacy_targets = np.asarray((0.045, 0.20, 0.55, 0.92))
    target_perceptual_luminance = np.interp(
        graphic_light,
        np.asarray((0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)),
        legacy_targets,
    )
    if detail > 0.0:
        # Expand contrast downward only.  The exponent keeps a useful middle
        # ramp while multiplying the already-established absolute target by
        # 0.68 / 0.77 / 0.87 / 1.00 at the four default bands.  ``gl == 1`` is
        # exactly unchanged, so source-detail recovery cannot blow out the
        # established lightest printable band.
        target_perceptual_luminance *= 1.0 - 0.32 * detail * shadow_weight
    # Scale the energy of each already-selected band around the ink floor.
    # This preserves the spatial band boundaries chosen by Light Range while
    # allowing a strong white blast to be reduced to blue-grey or mid-grey.
    target_perceptual_luminance = np.clip(
        0.045
        + (target_perceptual_luminance - 0.045) * light_intensity,
        0.0,
        1.0,
    )
    target_linear_luminance = _srgb_to_linear(
        target_perceptual_luminance[:, None]
    )[:, 0]

    safe_source_luminance = np.maximum(source_linear_luminance, 1.0e-4)
    hue_scaled_linear = linear * (
        target_linear_luminance / safe_source_luminance
    )[:, None]
    near_absolute_black = source_linear_luminance < 1.0e-4
    hue_scaled_linear[near_absolute_black] = target_linear_luminance[
        near_absolute_black, None
    ]
    # Neutral blacks stay neutral.  As the source becomes more chromatic, keep
    # more of its linear-light channel ratio while still reserving headroom.
    hue_retention = 0.35 + 0.35 * np.clip(source_span / 0.25, 0.0, 1.0)
    hue_retention = np.where(warm_mask, np.maximum(hue_retention, 0.86), hue_retention)
    if detail > 0.0:
        # Dark skin is explicitly excluded from the garment-detail mask.  Its
        # own ramp nevertheless benefits from stronger source channel-ratio
        # retention, preventing a lifted shadow from drifting toward grey.
        # Reach 0.95 only in the deepest shadow.  The lightest face retains the
        # exact legacy channel balance as well as its exact legacy lightness.
        warm_retention = np.maximum(hue_retention, 0.95)
        hue_retention = np.where(
            detail_warm_mask,
            hue_retention
            + (warm_retention - hue_retention) * detail * shadow_weight,
            hue_retention,
        )
    lifted_linear = target_linear_luminance[:, None] + (
        hue_scaled_linear - target_linear_luminance[:, None]
    ) * hue_retention[:, None]
    lifted = _linear_to_srgb(np.clip(lifted_linear, 0.0, 1.0))

    return multiplied * (1.0 - dark_weight[:, None]) + lifted * dark_weight[
        :, None
    ]


def _validated_controls(
    mode: str,
    strength: float,
    bands: int,
    light: str,
    light_intensity: float,
    light_range: float,
    detail_strength: float,
) -> tuple[str, float, int, str, float, float, float]:
    normalized_mode = str(mode).strip().lower()
    normalized_light = str(light).strip().lower()
    if normalized_mode not in ILLUSTRATION_MODES:
        raise IllustrationFilterError(f"unknown illustration mode: {mode}")
    if normalized_light not in ILLUSTRATION_LIGHTS:
        raise IllustrationFilterError(f"unknown illustration light: {light}")
    amount = float(strength)
    if not math.isfinite(amount) or amount < 0.0 or amount > 1.0:
        raise IllustrationFilterError("illustration strength must be in 0..1")
    intensity = float(light_intensity)
    if not math.isfinite(intensity) or not 0.0 <= intensity <= 1.5:
        raise IllustrationFilterError(
            "illustration light intensity must be in 0..1.5"
        )
    coverage = float(light_range)
    if not math.isfinite(coverage) or not 0.0 <= coverage <= 1.0:
        raise IllustrationFilterError("illustration light range must be in 0..1")
    detail = float(detail_strength)
    if not math.isfinite(detail) or not 0.0 <= detail <= 1.0:
        raise IllustrationFilterError(
            "illustration detail strength must be in 0..1"
        )
    if isinstance(bands, bool) or int(bands) != bands or not 2 <= int(bands) <= 6:
        raise IllustrationFilterError("illustration bands must be an integer in 2..6")
    return (
        normalized_mode,
        amount,
        int(bands),
        normalized_light,
        intensity,
        coverage,
        detail,
    )


def _wrapped_light_with_range(
    diffuse: np.ndarray,
    light_range: float,
) -> np.ndarray:
    """Return key-light coverage without changing its brightness.

    ``light_range`` controls two related physical ideas: the angular wrap of a
    broad source and, above the legacy default, a small amount of indirect rear
    fill.  The default 0.4 resolves to the historical ``(+0.28) / 1.28``
    curve exactly, so projects saved before this control existed keep their
    previous result.  Wider settings progressively reveal the unlit rear; they
    do not make front-facing highlights brighter.
    """

    coverage = float(light_range)
    if coverage <= _DEFAULT_LIGHT_RANGE:
        wrap = _DEFAULT_LIGHT_WRAP * coverage / _DEFAULT_LIGHT_RANGE
        rear_fill = 0.0
    else:
        progress = (coverage - _DEFAULT_LIGHT_RANGE) / (
            1.0 - _DEFAULT_LIGHT_RANGE
        )
        wrap = _DEFAULT_LIGHT_WRAP + (
            _MAX_LIGHT_WRAP - _DEFAULT_LIGHT_WRAP
        ) * progress
        smooth_progress = progress * progress * (3.0 - 2.0 * progress)
        rear_fill = _MAX_REAR_FILL * smooth_progress
    direct = np.clip((diffuse + wrap) / (1.0 + wrap), 0.0, 1.0)
    return rear_fill + (1.0 - rear_fill) * direct


def _style_rgb_with_bands(
    rgb: np.ndarray,
    normals: np.ndarray,
    *,
    mode: str,
    amount: float,
    bands: int,
    light: str,
    light_intensity: float = 1.0,
    light_range: float = _DEFAULT_LIGHT_RANGE,
    detail_strength: float = 0.0,
) -> tuple[np.ndarray, np.ndarray | None]:
    if amount <= 0.0:
        return np.ascontiguousarray(rgb.copy()), None
    light_vector = np.asarray(_LIGHT_DIRECTIONS[light], dtype=np.float64)
    light_vector /= np.linalg.norm(light_vector)

    # Coverage and energy are intentionally independent.  Range chooses which
    # faces belong to each light band; intensity changes how bright those
    # already-established bands become.  The user's 2-6 band choice therefore
    # remains a quantisation control rather than a disguised exposure slider.
    diffuse = np.einsum("ij,j->i", normals, light_vector, optimize=True)
    wrapped = _wrapped_light_with_range(diffuse, light_range)
    facing = np.abs(
        np.einsum("ij,j->i", normals, _VIEW_DIRECTION, optimize=True)
    )
    outline = np.power(np.clip(1.0 - facing, 0.0, 1.0), 4.0)

    linear = _srgb_to_linear(rgb)
    band_ids: np.ndarray | None = None
    if mode == "cel":
        # Fold/silhouette emphasis is quantised together with Lambert light.
        # Applying a continuous outline after stepping would silently create
        # hundreds of extra shades despite a 2-6 band selection.
        graphic_light, band_ids = _stepped_with_ids(
            np.clip(wrapped * (1.0 - 0.30 * outline), 0.0, 1.0),
            bands,
        )
        shade_factor = np.clip(
            0.34 + 0.72 * graphic_light * light_intensity,
            0.0,
            1.34,
        )
        styled = _linear_to_srgb(
            np.clip(linear * shade_factor[:, None], 0.0, 1.0)
        )
        output = rgb * (1.0 - amount) + styled * amount
    elif mode == "cel_strong":
        # A small perceptual expansion creates broad graphic light regions;
        # quantisation still guarantees no more than the requested band count.
        # Silhouettes remain in the darkest band to preserve the inked look.
        graphic_light, band_ids = _stepped_with_ids(
            np.clip(
                np.power(wrapped, 0.62) * (1.0 - 0.36 * outline),
                0.0,
                1.0,
            ),
            bands,
        )
        styled = _strong_cel_rgb(
            rgb,
            linear,
            graphic_light,
            light_intensity=light_intensity,
            detail_strength=detail_strength,
        )
        output = rgb * (1.0 - amount) + styled * amount
    else:
        stepped_light, _diffuse_band_ids = _stepped_with_ids(wrapped, bands)
        source_luminance = np.einsum(
            "ij,j->i",
            linear,
            np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float64),
            optimize=True,
        )
        generated_luminance = np.clip(
            0.08 + 0.90 * stepped_light * light_intensity,
            0.0,
            1.0,
        )
        luminance = (
            source_luminance * (1.0 - 0.72 * amount)
            + generated_luminance * (0.72 * amount)
        )
        luminance *= 1.0 - 0.42 * amount * outline
        luminance, band_ids = _stepped_with_ids(
            np.clip(luminance, 0.0, 1.0),
            bands,
        )
        output = _linear_to_srgb(np.repeat(luminance[:, None], 3, axis=1))

    return (
        np.ascontiguousarray(np.clip(output, 0.0, 1.0), dtype=np.float64),
        None if band_ids is None else np.ascontiguousarray(band_ids),
    )


def _style_rgb(
    rgb: np.ndarray,
    normals: np.ndarray,
    *,
    mode: str,
    amount: float,
    bands: int,
    light: str,
    light_intensity: float = 1.0,
    light_range: float = _DEFAULT_LIGHT_RANGE,
    detail_strength: float = 0.0,
) -> np.ndarray:
    output, _band_ids = _style_rgb_with_bands(
        rgb,
        normals,
        mode=mode,
        amount=amount,
        bands=bands,
        light=light,
        light_intensity=light_intensity,
        light_range=light_range,
        detail_strength=detail_strength,
    )
    return output


def apply_illustration_filter(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    *,
    mode: str,
    strength: float,
    bands: int,
    light: str,
    light_intensity: float = 1.0,
    light_range: float = _DEFAULT_LIGHT_RANGE,
    detail_strength: float = 0.0,
) -> np.ndarray:
    """Return a vertex-colour approximation of the illustration finish."""

    (
        normalized_mode,
        amount,
        band_count,
        normalized_light,
        intensity,
        coverage,
        _detail,
    ) = _validated_controls(
        mode,
        strength,
        bands,
        light,
        light_intensity,
        light_range,
        detail_strength,
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
        light_intensity=intensity,
        light_range=coverage,
        detail_strength=_detail,
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
    light_intensity: float = 1.0,
    light_range: float = _DEFAULT_LIGHT_RANGE,
    detail_strength: float = 0.0,
) -> np.ndarray:
    """Apply stepped shading independently to printable triangles.

    Cel bands must not be averaged through shared vertices: that would create
    extra intermediate bands and make armour creases depend on whether an
    importer happened to split a vertex.  This face-level path is therefore
    the authoritative input to palette assignment and 3MF output.
    """

    output, _band_ids = apply_illustration_filter_faces_with_bands(
        vertices,
        faces,
        face_colors,
        mode=mode,
        strength=strength,
        bands=bands,
        light=light,
        light_intensity=light_intensity,
        light_range=light_range,
        detail_strength=detail_strength,
    )
    return output


def apply_illustration_filter_faces_with_bands(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_colors: np.ndarray,
    *,
    mode: str,
    strength: float,
    bands: int,
    light: str,
    light_intensity: float = 1.0,
    light_range: float = _DEFAULT_LIGHT_RANGE,
    detail_strength: float = 0.0,
    _capture_strong_cel_geometry: bool = False,
) -> (
    tuple[np.ndarray, np.ndarray | None]
    | tuple[
        np.ndarray,
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray | None,
    ]
):
    """Apply face shading and retain the geometric light-band identity.

    The RGB output intentionally preserves some source hue.  Full Spectrum
    must not interpret those harmless within-band texture variations as new
    printable shades, so the companion IDs are carried to palette mapping.
    """

    (
        normalized_mode,
        amount,
        band_count,
        normalized_light,
        intensity,
        coverage,
        detail,
    ) = _validated_controls(
        mode,
        strength,
        bands,
        light,
        light_intensity,
        light_range,
        detail_strength,
    )
    geometry, triangles = _validated_geometry(vertices, faces)
    rgb = _validated_colors(face_colors, len(triangles), owner="face")
    if normalized_mode == "off" or len(rgb) == 0:
        basic_result = (np.ascontiguousarray(rgb.copy()), None)
        if _capture_strong_cel_geometry:
            return (*basic_result, None, None)
        return basic_result
    output = np.empty_like(rgb)
    all_band_ids = np.empty(len(triangles), dtype=np.uint8)
    has_band_ids = True
    capture_geometry = bool(
        _capture_strong_cel_geometry and normalized_mode == "cel_strong"
    )
    all_light_scores = (
        np.empty(len(triangles), dtype=np.float64)
        if capture_geometry
        else None
    )
    all_face_normals = (
        np.empty((len(triangles), 3), dtype=np.float64)
        if capture_geometry
        else None
    )
    capture_light_vector = None
    if capture_geometry:
        capture_light_vector = np.asarray(
            _LIGHT_DIRECTIONS[normalized_light], dtype=np.float64
        )
        capture_light_vector /= np.linalg.norm(capture_light_vector)
    normal_faces = _oriented_faces_for_normals(geometry, triangles)
    smooth_vertex_normals = (
        _vertex_normals(geometry, normal_faces)
        if normalized_mode == "cel_strong"
        else None
    )
    for start in range(0, len(triangles), _NORMAL_BATCH_FACES):
        stop = min(start + _NORMAL_BATCH_FACES, len(triangles))
        current = normal_faces[start:stop]
        normals = (
            _crease_aware_face_normals(
                geometry,
                current,
                smooth_vertex_normals,
                detail_strength=detail,
            )
            if smooth_vertex_normals is not None
            else _face_normals(geometry, current)
        )
        styled, band_ids = _style_rgb_with_bands(
            rgb[start:stop],
            normals,
            mode=normalized_mode,
            amount=amount,
            bands=band_count,
            light=normalized_light,
            light_intensity=intensity,
            light_range=coverage,
            detail_strength=detail,
        )
        output[start:stop] = styled
        if band_ids is None:
            has_band_ids = False
        else:
            all_band_ids[start:stop] = band_ids
        if capture_geometry:
            assert all_light_scores is not None
            assert all_face_normals is not None
            assert capture_light_vector is not None
            diffuse = np.einsum(
                "ij,j->i",
                normals,
                capture_light_vector,
                optimize=True,
            )
            wrapped = _wrapped_light_with_range(diffuse, coverage)
            facing = np.abs(
                np.einsum(
                    "ij,j->i",
                    normals,
                    _VIEW_DIRECTION,
                    optimize=True,
                )
            )
            outline = np.power(
                np.clip(1.0 - facing, 0.0, 1.0),
                4.0,
            )
            all_light_scores[start:stop] = np.clip(
                np.power(wrapped, 0.62) * (1.0 - 0.36 * outline),
                0.0,
                1.0,
            )
            all_face_normals[start:stop] = normals
    basic_result = (
        np.ascontiguousarray(output),
        np.ascontiguousarray(all_band_ids) if has_band_ids else None,
    )
    if _capture_strong_cel_geometry:
        return (
            *basic_result,
            None
            if all_light_scores is None
            else np.ascontiguousarray(all_light_scores),
            None
            if all_face_normals is None
            else np.ascontiguousarray(all_face_normals),
        )
    return basic_result


def strong_cel_face_light_geometry(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    light: str,
    light_range: float = _DEFAULT_LIGHT_RANGE,
    detail_strength: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return opt-in Strong-Cel light scores and crease-aware face normals.

    The ordinary filter does not expose its continuous pre-quantisation score.
    Selective Highlight needs that score to grow whole topology components
    without cutting an equal-score plateau by triangle order.  This helper is
    additive and is called only by the separate internal trial gate.
    """

    (
        _mode,
        _amount,
        _bands,
        normalized_light,
        _intensity,
        coverage,
        detail,
    ) = _validated_controls(
        "cel_strong",
        1.0,
        4,
        light,
        1.0,
        light_range,
        detail_strength,
    )
    geometry, triangles = _validated_geometry(vertices, faces)
    if not len(triangles):
        return (
            np.empty(0, dtype=np.float64),
            np.empty((0, 3), dtype=np.float64),
        )
    normal_faces = _oriented_faces_for_normals(geometry, triangles)
    smooth_vertex_normals = _vertex_normals(geometry, normal_faces)
    light_vector = np.asarray(
        _LIGHT_DIRECTIONS[normalized_light], dtype=np.float64
    )
    light_vector /= np.linalg.norm(light_vector)
    scores = np.empty(len(triangles), dtype=np.float64)
    normals = np.empty((len(triangles), 3), dtype=np.float64)
    for start in range(0, len(triangles), _NORMAL_BATCH_FACES):
        stop = min(start + _NORMAL_BATCH_FACES, len(triangles))
        current_normals = _crease_aware_face_normals(
            geometry,
            normal_faces[start:stop],
            smooth_vertex_normals,
            detail_strength=detail,
        )
        diffuse = np.einsum(
            "ij,j->i", current_normals, light_vector, optimize=True
        )
        wrapped = _wrapped_light_with_range(diffuse, coverage)
        facing = np.abs(
            np.einsum(
                "ij,j->i",
                current_normals,
                _VIEW_DIRECTION,
                optimize=True,
            )
        )
        outline = np.power(np.clip(1.0 - facing, 0.0, 1.0), 4.0)
        scores[start:stop] = np.clip(
            np.power(wrapped, 0.62) * (1.0 - 0.36 * outline),
            0.0,
            1.0,
        )
        normals[start:stop] = current_normals
    return np.ascontiguousarray(scores), np.ascontiguousarray(normals)


__all__ = [
    "ILLUSTRATION_LIGHTS",
    "ILLUSTRATION_MODES",
    "IllustrationFilterError",
    "apply_illustration_filter",
    "apply_illustration_filter_faces",
    "apply_illustration_filter_faces_with_bands",
    "strong_cel_dark_warm_mask",
    "strong_cel_detail_warm_mask",
    "strong_cel_face_light_geometry",
]
