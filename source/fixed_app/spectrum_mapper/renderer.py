from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import threading
from typing import Literal, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import ColorResult, MeshLevel
from .ui_fonts import linux_pillow_font_candidates


try:
    import moderngl
except Exception as exc:  # pragma: no cover - exercised on machines without OpenGL support
    moderngl = None  # type: ignore[assignment]
    _MODERNGL_IMPORT_ERROR: Exception | None = exc
else:
    _MODERNGL_IMPORT_ERROR = None


ColorMode = Literal["source", "target"]
PreviewDirection = Literal["front", "back", "left", "right", "top", "bottom"]
ViewTheme = Literal["auto", "dark", "light", "neutral"]
RGB = tuple[int, int, int]

VIEW_THEME_VALUES: tuple[ViewTheme, ...] = ("auto", "dark", "light", "neutral")
VIEW_THEME_BACKGROUNDS: dict[str, RGB] = {
    "dark": (9, 12, 17),
    "light": (232, 236, 242),
    "neutral": (112, 117, 125),
}

# Per-face display modes used by the manual correction window.  Keeping these
# as tiny integer attributes lets the GPU discard hidden faces before depth is
# written, which is essential for real click-through picking.
PART_VISIBLE = 0
PART_TRANSPARENT = 1
PART_HIDDEN = 2
PART_VISIBILITY_VALUES = (PART_VISIBLE, PART_TRANSPARENT, PART_HIDDEN)
VISIBILITY_INFO_KEY = "tripo_spectrum_part_visibility_filter"
VISIBILITY_FACE_MODES_INFO_KEY = "tripo_spectrum_part_visibility_face_modes"


@dataclass(frozen=True, slots=True)
class CameraState:
    """Orbit-camera state used by :class:`InteractiveMeshRenderer`.

    Angles are expressed in degrees.  ``yaw_degrees=0`` preserves the
    application's existing front view (the camera looks from -Y), while
    positive yaw orbits towards +X.  Zoom is an orthographic scale where 1.0
    fits the model in the viewport.
    """

    yaw_degrees: float = 0.0
    pitch_degrees: float = 0.0
    zoom: float = 1.0


@dataclass(frozen=True, slots=True)
class ViewAppearance:
    """Resolved colours for the manual correction model viewport.

    ``requested_theme`` is kept so the per-model preference can remain
    ``"auto"`` while ``resolved_theme`` records the concrete high-contrast
    background selected for the current model colours.
    """

    requested_theme: ViewTheme
    resolved_theme: Literal["dark", "light", "neutral"]
    background: RGB
    active_part_accent: RGB
    model_luminance: float | None


@dataclass(frozen=True, slots=True)
class InteractiveRenderFrame:
    """Images and the optional face-picking map produced by one render."""

    source: Image.Image | None
    target: Image.Image | None
    face_ids: np.ndarray | None
    camera: CameraState
    pixels_per_unit: float


@dataclass(frozen=True, slots=True)
class FrontPreviewPair:
    """Fixed-front source/target previews and their shared visible face map.

    ``face_ids`` uses the same top-left origin as the two PIL images, stores
    ``-1`` for background pixels, and otherwise indexes ``level.faces``.
    Both images deliberately use the legacy :func:`render_front_preview`
    camera and shading path so callers can add selection feedback without
    changing the established comparison framing.
    """

    source: Image.Image
    target: Image.Image
    face_ids: np.ndarray


class RendererError(RuntimeError):
    """Raised when preview input or the standalone OpenGL renderer fails."""


def _normalize(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if not np.isfinite(length) or length <= 1e-12:
        raise RendererError("カメラ方向を正規化できません。モデル寸法を確認してください。")
    return vector / length


def _look_at(eye: np.ndarray, center: np.ndarray, up: np.ndarray) -> np.ndarray:
    forward = _normalize(center - eye)
    side = _normalize(np.cross(forward, up))
    camera_up = np.cross(side, forward)
    matrix = np.eye(4, dtype=np.float32)
    matrix[0, :3] = side
    matrix[1, :3] = camera_up
    matrix[2, :3] = -forward
    matrix[:3, 3] = -matrix[:3, :3] @ eye
    return matrix


def _orthographic(
    left: float,
    right: float,
    bottom: float,
    top: float,
    near: float,
    far: float,
) -> np.ndarray:
    if right <= left or top <= bottom or far <= near:
        raise RendererError("プレビュー投影範囲が不正です。")
    matrix = np.eye(4, dtype=np.float32)
    matrix[0, 0] = 2.0 / (right - left)
    matrix[1, 1] = 2.0 / (top - bottom)
    matrix[2, 2] = -2.0 / (far - near)
    matrix[0, 3] = -(right + left) / (right - left)
    matrix[1, 3] = -(top + bottom) / (top - bottom)
    matrix[2, 3] = -(far + near) / (far - near)
    return matrix


def _validate_size(size: tuple[int, int]) -> tuple[int, int]:
    if len(size) != 2:
        raise RendererError("プレビューサイズは (幅, 高さ) で指定してください。")
    width, height = int(size[0]), int(size[1])
    if width < 8 or height < 8:
        raise RendererError("プレビューサイズは幅・高さとも8 px以上にしてください。")
    return width, height


def _validate_rgb(value: Sequence[int], name: str) -> RGB:
    if len(value) != 3:
        raise RendererError(f"{name}はRGB 3要素で指定してください。")
    rgb = tuple(int(channel) for channel in value)
    if any(channel < 0 or channel > 255 for channel in rgb):
        raise RendererError(f"{name}は0～255のRGBで指定してください。")
    return rgb  # type: ignore[return-value]


def _model_luminance(face_rgb: np.ndarray | Sequence[Sequence[float]] | None) -> float | None:
    """Return a robust perceived luminance for a model colour table.

    Both 0..1 floating-point arrays and 0..255 image-style arrays are accepted.
    The median deliberately follows the dominant surface colours instead of a
    few tiny white or black accents that should not decide the whole viewport.
    """

    if face_rgb is None:
        return None
    colors = np.asarray(face_rgb, dtype=np.float64)
    if colors.size == 0:
        return None
    if colors.ndim != 2 or colors.shape[1] != 3:
        raise RendererError("model colours must be an Nx3 RGB array")
    if not np.all(np.isfinite(colors)):
        raise RendererError("model colours must contain only finite values")
    if float(colors.max()) > 1.0 + 1e-6:
        colors = colors / 255.0
    colors = np.clip(colors, 0.0, 1.0)
    # WCAG relative luminance is a better predictor of viewport contrast than
    # an arithmetic RGB average, especially for saturated purple/red models.
    linear = np.where(
        colors <= 0.04045,
        colors / 12.92,
        ((colors + 0.055) / 1.055) ** 2.4,
    )
    luminance = linear @ np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float64)
    return float(np.median(luminance))


def resolve_view_appearance(
    theme: ViewTheme | str,
    face_rgb: np.ndarray | Sequence[Sequence[float]] | None = None,
) -> ViewAppearance:
    """Resolve a user-selected viewport theme against the model colours.

    Auto mode chooses a light canvas for predominantly dark models and a dark
    canvas for predominantly light models.  This intentionally leaves neutral
    grey as an explicit user choice because grey is useful for colour judging,
    but is not reliably high contrast for arbitrary mid-tone models.
    """

    requested = str(theme).strip().lower()
    if requested not in VIEW_THEME_VALUES:
        raise RendererError(
            f"unknown view theme {theme!r}; expected one of {VIEW_THEME_VALUES}"
        )
    luminance = _model_luminance(face_rgb)
    if requested == "auto":
        # No model table is available during a few early loading frames.  Keep
        # the established dark canvas until real colours can make the choice.
        resolved = "dark" if luminance is None else ("light" if luminance < 0.36 else "dark")
    else:
        resolved = requested
    background = VIEW_THEME_BACKGROUNDS[resolved]
    # Cyan remains legible on the dark/neutral canvases and is deliberately
    # outside the usual red/purple/gold model palettes.  Deep blue gives the
    # light canvas the same clear editing-state cue without a white halo.
    accent = (0, 102, 224) if resolved == "light" else (36, 224, 255)
    return ViewAppearance(
        requested_theme=requested,  # type: ignore[arg-type]
        resolved_theme=resolved,  # type: ignore[arg-type]
        background=background,
        active_part_accent=accent,
        model_luminance=luminance,
    )


def _expand_binary_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    expanded = np.asarray(mask, dtype=bool).copy()
    for _ in range(max(0, int(radius))):
        source = expanded
        padded = np.pad(source, 1, mode="constant", constant_values=False)
        expanded = (
            padded[1:-1, 1:-1]
            | padded[:-2, 1:-1]
            | padded[2:, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
            | padded[:-2, :-2]
            | padded[:-2, 2:]
            | padded[2:, :-2]
            | padded[2:, 2:]
        )
    return expanded


def _erode_binary_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    eroded = np.asarray(mask, dtype=bool).copy()
    for _ in range(max(0, int(radius))):
        source = eroded
        padded = np.pad(source, 1, mode="constant", constant_values=False)
        eroded = (
            padded[1:-1, 1:-1]
            & padded[:-2, 1:-1]
            & padded[2:, 1:-1]
            & padded[1:-1, :-2]
            & padded[1:-1, 2:]
            & padded[:-2, :-2]
            & padded[:-2, 2:]
            & padded[2:, :-2]
            & padded[2:, 2:]
        )
    return eroded


def overlay_active_part_outline(
    image: Image.Image,
    face_ids: np.ndarray,
    face_part_ids: np.ndarray | Sequence[int],
    active_part_id: int | None,
    *,
    color: Sequence[int] = (36, 224, 255),
    thickness: int = 2,
) -> Image.Image:
    """Return a copy with the visible boundary of one OBJ part outlined.

    This is a pure image-space helper, so the UI can use the exact face-ID map
    already produced for painting.  It never changes mesh colours or exported
    data.  Background pixels are ``-1`` and safely ignored.
    """

    output = image.convert("RGB").copy()
    output.info.update(image.info)
    if active_part_id is None:
        return output
    ids = np.asarray(face_ids)
    parts = np.asarray(face_part_ids)
    if ids.ndim != 2 or ids.shape != (output.height, output.width):
        raise RendererError("face ID map must match the image height and width")
    if parts.ndim != 1 or not np.issubdtype(parts.dtype, np.integer):
        raise RendererError("face part IDs must be a one-dimensional integer array")
    if not np.issubdtype(ids.dtype, np.integer):
        raise RendererError("face ID map must contain integers")
    if int(active_part_id) < 0:
        raise RendererError("active part ID must be zero or greater")
    valid = (ids >= 0) & (ids < len(parts))
    active = np.zeros(ids.shape, dtype=bool)
    if bool(np.any(valid)):
        active[valid] = parts[ids[valid].astype(np.int64)] == int(active_part_id)
    if not bool(np.any(active)):
        return output

    width = max(1, min(8, int(thickness)))
    # A centred outline marks both the silhouette and shared visible boundaries
    # between parts.  Drawing on both sides keeps a two-pixel cue visible even
    # on very narrow parts.
    outline = _expand_binary_mask(active, width) & ~_erode_binary_mask(active, width)
    pixels = np.asarray(output, dtype=np.uint8).copy()
    pixels[outline] = np.asarray(_validate_rgb(color, "active part outline"), dtype=np.uint8)
    highlighted = Image.fromarray(pixels, mode="RGB")
    highlighted.info.update(output.info)
    return highlighted


def _validate_mesh(level: MeshLevel) -> tuple[np.ndarray, np.ndarray]:
    vertices = np.asarray(level.vertices_unit)
    faces = np.asarray(level.faces)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3:
        raise RendererError("MeshLevel.vertices_unit は3頂点以上の Nx3 配列が必要です。")
    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) < 1:
        raise RendererError("MeshLevel.faces は1面以上の Mx3 三角形配列が必要です。")
    if not np.all(np.isfinite(vertices)):
        raise RendererError("モデル頂点にNaNまたは無限値があります。")
    if not np.issubdtype(faces.dtype, np.integer):
        raise RendererError("面インデックスは整数である必要があります。")
    minimum = int(faces.min())
    maximum = int(faces.max())
    if minimum < 0 or maximum >= len(vertices):
        raise RendererError(
            f"面インデックスが頂点範囲外です: min={minimum}, max={maximum}, vertices={len(vertices)}"
        )
    extents = np.ptp(vertices.astype(np.float64), axis=0)
    if float(extents[2]) <= 1e-12:
        raise RendererError("モデルの高さが0です。")
    return vertices.astype(np.float32, copy=False), faces.astype(np.int32, copy=False)


def _face_colors(result: ColorResult, mode: ColorMode, face_count: int) -> np.ndarray:
    if mode == "source":
        colors = np.asarray(result.source_face_rgb)
    elif mode == "target":
        colors = np.asarray(result.target_face_rgb)
    else:
        raise RendererError(f"未対応の色モードです: {mode}")
    if colors.shape != (face_count, 3):
        raise RendererError(
            f"ColorResultの{mode}面色数がメッシュと一致しません: "
            f"colors={colors.shape}, faces=({face_count}, 3)"
        )
    if not np.all(np.isfinite(colors)):
        raise RendererError(f"ColorResultの{mode}面色にNaNまたは無限値があります。")
    return np.clip(colors, 0.0, 1.0).astype(np.float32, copy=False)


def _effective_shaded(
    result: ColorResult,
    mode: ColorMode,
    requested: bool,
) -> bool:
    """Avoid applying a second light to a baked illustration target.

    Cel/Noir palette assignment already contains its selected fixed-front
    light.  The ordinary viewport shader remains useful for the AI/source
    colour, but applying its fixed upper-left light to the converted target
    would contradict Front or Upper Right and misrepresent the 3MF colours.
    """

    return bool(requested) and not (
        mode == "target"
        and bool(getattr(result, "tone_face_rgb_flat", False))
    )


def _create_context():
    if moderngl is None:
        detail = f" ({_MODERNGL_IMPORT_ERROR})" if _MODERNGL_IMPORT_ERROR else ""
        raise RendererError(
            "ModernGLを読み込めません。moderngl/glcontextを同梱またはインストールしてください。"
            + detail
        )
    try:
        return moderngl.create_standalone_context(require=330)
    except Exception as exc:
        raise RendererError(
            "ModernGL standalone contextの作成に失敗しました。"
            " OpenGL 3.3対応ドライバーとglcontextを確認してください。"
            f" 原因: {exc}"
        ) from exc


def _release(resource: object | None) -> None:
    if resource is None:
        return
    release = getattr(resource, "release", None)
    if callable(release):
        try:
            release()
        except Exception:
            pass


PREVIEW_DIRECTIONS: tuple[PreviewDirection, ...] = (
    "front",
    "back",
    "left",
    "right",
    "top",
    "bottom",
)


def _camera_mvp(
    vertices: np.ndarray,
    size: tuple[int, int],
    direction: PreviewDirection = "front",
) -> np.ndarray:
    minimum = vertices.min(axis=0).astype(np.float64)
    maximum = vertices.max(axis=0).astype(np.float64)
    center = (minimum + maximum) * 0.5
    extents = maximum - minimum
    diagonal = max(float(np.linalg.norm(extents)), 1e-6)

    if direction not in PREVIEW_DIRECTIONS:
        raise RendererError(f"Unknown preview direction: {direction}")

    # Preserve the established front-view framing byte-for-byte. Other named
    # views use the same orthographic margin while fitting the two axes visible
    # from that direction.
    distance = max(diagonal * 2.5, float(extents[1]) * 3.0, 1.0)
    if direction == "front":
        eye_offset = (0.0, -distance, 0.01 * extents[2])
        up = (0.0, 0.0, 1.0)
        visible_width = float(extents[0])
        visible_height = float(extents[2])
    else:
        camera_specs = {
            "back": ((0.0, distance, 0.0), (0.0, 0.0, 1.0), extents[0], extents[2]),
            "left": ((-distance, 0.0, 0.0), (0.0, 0.0, 1.0), extents[1], extents[2]),
            "right": ((distance, 0.0, 0.0), (0.0, 0.0, 1.0), extents[1], extents[2]),
            "top": ((0.0, 0.0, distance), (0.0, 1.0, 0.0), extents[0], extents[1]),
            "bottom": ((0.0, 0.0, -distance), (0.0, -1.0, 0.0), extents[0], extents[1]),
        }
        eye_offset, up, visible_width, visible_height = camera_specs[direction]
    eye = center + np.asarray(eye_offset, dtype=np.float64)
    view = _look_at(
        eye.astype(np.float32),
        center.astype(np.float32),
        np.asarray(up, dtype=np.float32),
    )

    aspect = size[0] / size[1]
    half_height = max(
        float(visible_height) * 0.55,
        float(visible_width) * 0.55 / aspect,
        1e-5,
    )
    projection = _orthographic(
        -half_height * aspect,
        half_height * aspect,
        -half_height,
        half_height,
        0.001,
        distance + diagonal * 3.0,
    )
    return projection @ view


def _sanitize_camera(camera: CameraState | None) -> CameraState:
    value = camera or CameraState()
    yaw = float(value.yaw_degrees)
    pitch = float(value.pitch_degrees)
    zoom = float(value.zoom)
    if not all(math.isfinite(item) for item in (yaw, pitch, zoom)):
        raise RendererError("Camera values must be finite numbers.")
    if zoom <= 0.0:
        raise RendererError("Camera zoom must be greater than zero.")
    return CameraState(
        yaw_degrees=math.fmod(yaw, 360.0),
        pitch_degrees=max(-84.0, min(84.0, pitch)),
        zoom=max(0.05, min(40.0, zoom)),
    )


def _orbit_camera_mvp(
    vertices: np.ndarray,
    size: tuple[int, int],
    camera: CameraState | None,
) -> tuple[np.ndarray, CameraState, float]:
    """Build a fitted orthographic orbit-camera matrix.

    The projected extents are computed from the eight mesh bounding-box
    corners.  This keeps the whole model visible at zoom 1.0 at every angle
    without scanning every vertex on each drag frame.
    """

    state = _sanitize_camera(camera)
    minimum = vertices.min(axis=0).astype(np.float64)
    maximum = vertices.max(axis=0).astype(np.float64)
    center = (minimum + maximum) * 0.5
    extents = maximum - minimum
    diagonal = max(float(np.linalg.norm(extents)), 1e-6)

    yaw = math.radians(state.yaw_degrees)
    pitch = math.radians(state.pitch_degrees)
    horizontal = math.cos(pitch)
    eye_direction = np.asarray(
        (
            math.sin(yaw) * horizontal,
            -math.cos(yaw) * horizontal,
            math.sin(pitch),
        ),
        dtype=np.float64,
    )
    distance = max(diagonal * 2.5, 1.0)
    eye = center + eye_direction * distance
    view = _look_at(
        eye.astype(np.float32),
        center.astype(np.float32),
        np.asarray((0.0, 0.0, 1.0), dtype=np.float32),
    )

    corners = np.asarray(
        [
            (x, y, z)
            for x in (minimum[0], maximum[0])
            for y in (minimum[1], maximum[1])
            for z in (minimum[2], maximum[2])
        ],
        dtype=np.float64,
    )
    camera_space = (corners - center) @ view[:3, :3].astype(np.float64).T
    projected_width = max(float(np.ptp(camera_space[:, 0])), 1e-6)
    projected_height = max(float(np.ptp(camera_space[:, 1])), 1e-6)
    aspect = size[0] / size[1]
    half_height = max(projected_height * 0.55, projected_width * 0.55 / aspect, 1e-5)
    half_height /= state.zoom
    projection = _orthographic(
        -half_height * aspect,
        half_height * aspect,
        -half_height,
        half_height,
        0.001,
        distance + diagonal * 3.0,
    )
    pixels_per_unit = float(size[1]) / (2.0 * half_height)
    return projection @ view, state, pixels_per_unit


def _render_with_context(
    context,
    level: MeshLevel,
    result: ColorResult,
    *,
    mode: ColorMode,
    size: tuple[int, int],
    background: RGB,
    shaded: bool,
    direction: PreviewDirection = "front",
) -> Image.Image:
    vertices, faces = _validate_mesh(level)
    colors = _face_colors(result, mode, len(faces))

    tri = vertices[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(lengths[:, None], 1e-12)
    packed = np.hstack(
        (
            tri.reshape(-1, 3),
            np.repeat(normals, 3, axis=0),
            np.repeat(colors, 3, axis=0),
        )
    ).astype(np.float32, copy=False)
    packed = np.ascontiguousarray(packed)

    program = None
    framebuffer = None
    buffer = None
    vao = None
    try:
        program = context.program(
            vertex_shader="""
                #version 330
                uniform mat4 mvp;
                in vec3 in_position;
                in vec3 in_normal;
                in vec3 in_color;
                out vec3 v_normal;
                out vec3 v_color;
                void main() {
                    gl_Position = mvp * vec4(in_position, 1.0);
                    v_normal = in_normal;
                    v_color = in_color;
                }
            """,
            fragment_shader="""
                #version 330
                uniform float shade_strength;
                in vec3 v_normal;
                in vec3 v_color;
                out vec4 frag_color;
                void main() {
                    vec3 light = normalize(vec3(-0.25, -0.75, 0.62));
                    float diffuse = max(dot(normalize(v_normal), light), 0.0);
                    float lit = mix(1.0, 0.82 + 0.18 * diffuse, shade_strength);
                    vec3 corrected = pow(clamp(v_color * lit, 0.0, 1.0), vec3(1.0 / 1.04));
                    frag_color = vec4(corrected, 1.0);
                }
            """,
        )
        mvp = _camera_mvp(vertices, size, direction)
        program["mvp"].write(mvp.T.astype(np.float32).tobytes())
        program["shade_strength"].value = (
            1.0 if _effective_shaded(result, mode, shaded) else 0.0
        )

        framebuffer = context.simple_framebuffer(size, components=4)
        framebuffer.use()
        clear = tuple(channel / 255.0 for channel in background)
        framebuffer.clear(clear[0], clear[1], clear[2], 1.0)
        context.enable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        buffer = context.buffer(packed.tobytes())
        vao = context.vertex_array(
            program,
            [(buffer, "3f 3f 3f", "in_position", "in_normal", "in_color")],
        )
        vao.render(mode=moderngl.TRIANGLES)
        pixels = framebuffer.read(components=4, alignment=1)
        return Image.frombytes("RGBA", size, pixels).transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert(
            "RGB"
        )
    except RendererError:
        raise
    except Exception as exc:
        raise RendererError(f"ModernGLプレビュー描画に失敗しました: {exc}") from exc
    finally:
        _release(vao)
        _release(buffer)
        _release(framebuffer)
        _release(program)


def _render_front_face_ids_with_context(
    context,
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    size: tuple[int, int],
    direction: PreviewDirection = "front",
) -> np.ndarray:
    """Render face IDs with the exact camera used by the legacy front view."""

    positions = np.ascontiguousarray(vertices[faces].reshape(-1, 3), dtype=np.float32)
    program = None
    framebuffer = None
    texture = None
    depth = None
    buffer = None
    vao = None
    try:
        program = context.program(
            vertex_shader="""
                #version 330
                uniform mat4 mvp;
                in vec3 in_position;
                flat out uint v_face_id;
                void main() {
                    gl_Position = mvp * vec4(in_position, 1.0);
                    v_face_id = uint(gl_VertexID / 3) + 1u;
                }
            """,
            fragment_shader="""
                #version 330
                flat in uint v_face_id;
                layout(location = 0) out uint out_face_id;
                void main() {
                    out_face_id = v_face_id;
                }
            """,
        )
        mvp = _camera_mvp(vertices, size, direction)
        program["mvp"].write(mvp.T.astype(np.float32).tobytes())

        texture = context.texture(size, components=1, dtype="u4")
        depth = context.depth_renderbuffer(size)
        framebuffer = context.framebuffer(
            color_attachments=[texture],
            depth_attachment=depth,
        )
        framebuffer.use()
        framebuffer.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        context.enable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        buffer = context.buffer(positions.tobytes())
        vao = context.vertex_array(
            program,
            [(buffer, "3f", "in_position")],
        )
        vao.render(mode=moderngl.TRIANGLES)
        pixels = framebuffer.read(components=1, dtype="u4", alignment=1)
        raw = np.frombuffer(pixels, dtype=np.uint32).reshape(size[1], size[0])
        top_left = np.flipud(raw).astype(np.int64, copy=True)
        top_left -= 1
        return top_left.astype(np.int32, copy=False)
    except RendererError:
        raise
    except Exception as exc:
        raise RendererError(f"ModernGL正面face-ID描画に失敗しました: {exc}") from exc
    finally:
        _release(vao)
        _release(buffer)
        _release(framebuffer)
        _release(depth)
        _release(texture)
        _release(program)


class InteractiveMeshRenderer:
    """Persistent off-screen renderer for orbiting and face picking.

    The renderer expands the mesh once and keeps all OpenGL resources alive,
    so orbiting only changes a matrix uniform.  OpenGL contexts are thread
    affine: construct, call and close an instance on the same worker thread.

    Face IDs correspond exactly to ``level.faces``.  The returned map uses a
    top-left image origin and stores ``-1`` for background pixels.
    """

    def __init__(
        self,
        level: MeshLevel,
        *,
        size: tuple[int, int] = (560, 700),
        background: Sequence[int] = (9, 12, 17),
    ) -> None:
        self._owner_thread = threading.get_ident()
        self._closed = False
        self._vertices, self._faces = _validate_mesh(level)
        self._face_count = len(self._faces)
        self._size = _validate_size(size)
        self._background = _validate_rgb(background, "background")
        raw_part_ids = getattr(level, "face_part_ids", None)
        if raw_part_ids is None or np.asarray(raw_part_ids).size == 0:
            # Legacy/synthetic single-part MeshLevel values used an empty
            # array.  Treat that established representation as one whole
            # model, while keeping strict validation for malformed non-empty
            # multipart metadata.
            self._face_part_ids = np.zeros(self._face_count, dtype=np.int32)
        else:
            part_ids = np.asarray(raw_part_ids)
            if (
                part_ids.shape != (self._face_count,)
                or not np.issubdtype(part_ids.dtype, np.integer)
                or (len(part_ids) and int(part_ids.min()) < 0)
            ):
                raise RendererError("face_part_ids must contain one non-negative integer per face")
            self._face_part_ids = part_ids.astype(np.int32, copy=True)
        self._active_part_id: int | None = None
        self._active_part_accent: RGB = (36, 224, 255)
        self._active_part_outline_thickness = 2
        self._highlight_active_part_in_source = False
        self._source_array_ref: object | None = None
        self._target_array_ref: object | None = None
        self._face_visibility = np.zeros(self._face_count, dtype=np.uint8)
        self._visibility_active = False
        self._pick_transparent = False
        # Optional display-only palette-state focus.  The base colour buffer is
        # supplied by PaintEditorWindow; the adaptive GPU overlay reads these
        # values so leaf triangles follow the same diagnostic view.
        self._palette_usage_focus_state: int | None = None
        self._palette_usage_focus_part_id: int | None = None

        self._context = None
        self._program = None
        self._pick_program = None
        self._visibility_program = None
        self._visibility_pick_program = None
        self._position_buffer = None
        self._normal_buffer = None
        self._visibility_buffer = None
        self._source_color_buffer = None
        self._target_color_buffer = None
        self._source_vao = None
        self._target_vao = None
        self._pick_vao = None
        self._visibility_source_vao = None
        self._visibility_target_vao = None
        self._visibility_pick_vao = None
        self._color_framebuffer = None
        self._pick_texture = None
        self._pick_depth = None
        self._pick_framebuffer = None

        try:
            self._context = _create_context()
            self._create_mesh_resources()
            self._allocate_framebuffers(self._size)
        except Exception:
            self._release_resources()
            self._closed = True
            raise

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    @property
    def face_count(self) -> int:
        return self._face_count

    @property
    def background(self) -> RGB:
        return self._background

    def _ensure_usable(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RendererError(
                "InteractiveMeshRenderer must be used on the thread that created it."
            )
        if self._closed or self._context is None:
            raise RendererError("InteractiveMeshRenderer is already closed.")

    def _create_mesh_resources(self) -> None:
        context = self._context
        if context is None:
            raise RendererError("OpenGL context is unavailable.")

        tri = self._vertices[self._faces]
        face_normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        lengths = np.linalg.norm(face_normals, axis=1)
        face_normals /= np.maximum(lengths[:, None], 1e-12)
        positions = np.ascontiguousarray(tri.reshape(-1, 3), dtype=np.float32)
        normals = np.ascontiguousarray(np.repeat(face_normals, 3, axis=0), dtype=np.float32)
        color_bytes = positions.shape[0] * 3 * np.dtype(np.float32).itemsize

        self._program = context.program(
            vertex_shader="""
                #version 330
                uniform mat4 mvp;
                in vec3 in_position;
                in vec3 in_normal;
                in vec3 in_color;
                out vec3 v_normal;
                out vec3 v_color;
                void main() {
                    gl_Position = mvp * vec4(in_position, 1.0);
                    v_normal = in_normal;
                    v_color = in_color;
                }
            """,
            fragment_shader="""
                #version 330
                uniform float shade_strength;
                in vec3 v_normal;
                in vec3 v_color;
                out vec4 frag_color;
                void main() {
                    vec3 light = normalize(vec3(-0.25, -0.75, 0.62));
                    float diffuse = max(dot(normalize(v_normal), light), 0.0);
                    float lit = mix(1.0, 0.82 + 0.18 * diffuse, shade_strength);
                    vec3 corrected = pow(clamp(v_color * lit, 0.0, 1.0), vec3(1.0 / 1.04));
                    frag_color = vec4(corrected, 1.0);
                }
            """,
        )
        self._pick_program = context.program(
            vertex_shader="""
                #version 330
                uniform mat4 mvp;
                in vec3 in_position;
                flat out uint v_face_id;
                void main() {
                    gl_Position = mvp * vec4(in_position, 1.0);
                    v_face_id = uint(gl_VertexID / 3) + 1u;
                }
            """,
            fragment_shader="""
                #version 330
                flat in uint v_face_id;
                layout(location = 0) out uint out_face_id;
                void main() {
                    out_face_id = v_face_id;
                }
            """,
        )
        self._visibility_program = context.program(
            vertex_shader="""
                #version 330
                uniform mat4 mvp;
                in vec3 in_position;
                in vec3 in_normal;
                in vec3 in_color;
                in float in_visibility;
                out vec3 v_normal;
                out vec3 v_color;
                flat out int v_visibility;
                void main() {
                    gl_Position = mvp * vec4(in_position, 1.0);
                    v_normal = in_normal;
                    v_color = in_color;
                    v_visibility = int(in_visibility + 0.5);
                }
            """,
            fragment_shader="""
                #version 330
                uniform float shade_strength;
                uniform int render_pass;
                in vec3 v_normal;
                in vec3 v_color;
                flat in int v_visibility;
                out vec4 frag_color;
                void main() {
                    if ((render_pass == 0 && v_visibility != 0) ||
                        (render_pass == 1 && v_visibility != 1)) {
                        discard;
                    }
                    vec3 light = normalize(vec3(-0.25, -0.75, 0.62));
                    float diffuse = max(dot(normalize(v_normal), light), 0.0);
                    float lit = mix(1.0, 0.82 + 0.18 * diffuse, shade_strength);
                    vec3 corrected = pow(clamp(v_color * lit, 0.0, 1.0), vec3(1.0 / 1.04));
                    float alpha = render_pass == 1 ? 0.24 : 1.0;
                    frag_color = vec4(corrected, alpha);
                }
            """,
        )
        self._visibility_pick_program = context.program(
            vertex_shader="""
                #version 330
                uniform mat4 mvp;
                in vec3 in_position;
                in float in_visibility;
                flat out uint v_face_id;
                flat out int v_visibility;
                void main() {
                    gl_Position = mvp * vec4(in_position, 1.0);
                    v_face_id = uint(gl_VertexID / 3) + 1u;
                    v_visibility = int(in_visibility + 0.5);
                }
            """,
            fragment_shader="""
                #version 330
                uniform int pick_transparent;
                flat in uint v_face_id;
                flat in int v_visibility;
                layout(location = 0) out uint out_face_id;
                void main() {
                    if (v_visibility == 2 ||
                        (v_visibility == 1 && pick_transparent == 0)) {
                        discard;
                    }
                    out_face_id = v_face_id;
                }
            """,
        )

        self._position_buffer = context.buffer(positions.tobytes())
        self._normal_buffer = context.buffer(normals.tobytes())
        visibility_values = np.zeros(positions.shape[0], dtype=np.float32)
        self._visibility_buffer = context.buffer(
            visibility_values.tobytes(), dynamic=True
        )
        self._source_color_buffer = context.buffer(reserve=color_bytes, dynamic=True)
        self._target_color_buffer = context.buffer(reserve=color_bytes, dynamic=True)
        self._source_vao = context.vertex_array(
            self._program,
            [
                (self._position_buffer, "3f", "in_position"),
                (self._normal_buffer, "3f", "in_normal"),
                (self._source_color_buffer, "3f", "in_color"),
            ],
        )
        self._target_vao = context.vertex_array(
            self._program,
            [
                (self._position_buffer, "3f", "in_position"),
                (self._normal_buffer, "3f", "in_normal"),
                (self._target_color_buffer, "3f", "in_color"),
            ],
        )
        self._pick_vao = context.vertex_array(
            self._pick_program,
            [(self._position_buffer, "3f", "in_position")],
        )
        self._visibility_source_vao = context.vertex_array(
            self._visibility_program,
            [
                (self._position_buffer, "3f", "in_position"),
                (self._normal_buffer, "3f", "in_normal"),
                (self._source_color_buffer, "3f", "in_color"),
                (self._visibility_buffer, "1f", "in_visibility"),
            ],
        )
        self._visibility_target_vao = context.vertex_array(
            self._visibility_program,
            [
                (self._position_buffer, "3f", "in_position"),
                (self._normal_buffer, "3f", "in_normal"),
                (self._target_color_buffer, "3f", "in_color"),
                (self._visibility_buffer, "1f", "in_visibility"),
            ],
        )
        self._visibility_pick_vao = context.vertex_array(
            self._visibility_pick_program,
            [
                (self._position_buffer, "3f", "in_position"),
                (self._visibility_buffer, "1f", "in_visibility"),
            ],
        )

    def _allocate_framebuffers(self, size: tuple[int, int]) -> None:
        context = self._context
        if context is None:
            raise RendererError("OpenGL context is unavailable.")
        render_size = _validate_size(size)
        color_framebuffer = None
        pick_texture = None
        pick_depth = None
        pick_framebuffer = None
        try:
            color_framebuffer = context.simple_framebuffer(render_size, components=4)
            pick_texture = context.texture(render_size, components=1, dtype="u4")
            pick_depth = context.depth_renderbuffer(render_size)
            pick_framebuffer = context.framebuffer(
                color_attachments=[pick_texture],
                depth_attachment=pick_depth,
            )
        except Exception:
            _release(pick_framebuffer)
            _release(pick_depth)
            _release(pick_texture)
            _release(color_framebuffer)
            raise

        _release(self._pick_framebuffer)
        _release(self._pick_depth)
        _release(self._pick_texture)
        _release(self._color_framebuffer)
        self._color_framebuffer = color_framebuffer
        self._pick_texture = pick_texture
        self._pick_depth = pick_depth
        self._pick_framebuffer = pick_framebuffer
        self._size = render_size

    def resize(self, size: tuple[int, int]) -> None:
        self._ensure_usable()
        render_size = _validate_size(size)
        if render_size != self._size:
            self._allocate_framebuffers(render_size)

    def set_background(self, background: Sequence[int]) -> bool:
        """Change the viewport clear colour without rebuilding GPU resources."""

        self._ensure_usable()
        requested = _validate_rgb(background, "background")
        changed = requested != self._background
        self._background = requested
        return changed

    def set_active_part(
        self,
        part_id: int | None,
        *,
        color: Sequence[int] | None = None,
        thickness: int = 2,
        highlight_source: bool = False,
    ) -> bool:
        """Select a part for a non-destructive image-space editing outline."""

        self._ensure_usable()
        if part_id is None:
            requested_part = None
        else:
            requested_part = int(part_id)
            if requested_part < 0 or not bool(
                np.any(self._face_part_ids == requested_part)
            ):
                raise RendererError(f"unknown active part ID: {part_id}")
        requested_color = (
            self._active_part_accent
            if color is None
            else _validate_rgb(color, "active part outline")
        )
        requested_thickness = max(1, min(8, int(thickness)))
        requested_source = bool(highlight_source)
        changed = (
            requested_part != self._active_part_id
            or requested_color != self._active_part_accent
            or requested_thickness != self._active_part_outline_thickness
            or requested_source != self._highlight_active_part_in_source
        )
        self._active_part_id = requested_part
        self._active_part_accent = requested_color
        self._active_part_outline_thickness = requested_thickness
        self._highlight_active_part_in_source = requested_source
        return changed

    def invalidate_colors(self, *, source: bool = True, target: bool = True) -> None:
        """Mark in-place colour-array edits for upload on the next render."""

        self._ensure_usable()
        if source:
            self._source_array_ref = None
        if target:
            self._target_array_ref = None

    def set_face_visibility(
        self,
        face_modes: np.ndarray | Sequence[int] | None,
        *,
        pick_transparent: bool = False,
    ) -> bool:
        """Set lightweight per-face display and picking modes.

        ``PART_VISIBLE`` is rendered and picked normally, ``PART_TRANSPARENT``
        is alpha-blended and is included in the face-ID pass only when
        ``pick_transparent`` is true, and ``PART_HIDDEN`` is discarded from
        both passes.  The method must run on the renderer's owner thread.

        Returns ``True`` when either the modes or picking policy changed.
        """

        self._ensure_usable()
        if face_modes is None:
            values = np.zeros(self._face_count, dtype=np.uint8)
        else:
            raw = np.asarray(face_modes)
            if raw.shape != (self._face_count,):
                raise RendererError(
                    "face visibility must contain exactly one mode per face"
                )
            if not np.issubdtype(raw.dtype, np.integer):
                raise RendererError("face visibility modes must be integers")
            if len(raw) and (
                int(raw.min()) < PART_VISIBLE or int(raw.max()) > PART_HIDDEN
            ):
                raise RendererError(
                    "face visibility modes must be visible, transparent, or hidden"
                )
            values = raw.astype(np.uint8, copy=False)

        requested_pick = bool(pick_transparent)
        changed_modes = not np.array_equal(values, self._face_visibility)
        changed_pick = requested_pick != self._pick_transparent
        if changed_modes:
            self._face_visibility = values.copy()
            vertex_modes = np.ascontiguousarray(
                np.repeat(self._face_visibility, 3), dtype=np.float32
            )
            if self._visibility_buffer is None:
                raise RendererError("face visibility buffer is unavailable")
            self._visibility_buffer.write(vertex_modes.tobytes())
            self._visibility_active = bool(
                np.any(self._face_visibility != PART_VISIBLE)
            )
        self._pick_transparent = requested_pick
        return bool(changed_modes or changed_pick)

    def set_palette_usage_focus(
        self,
        state: int | None,
        *,
        part_id: int | None = None,
    ) -> bool:
        """Route a read-only state focus to optional adaptive render layers."""

        self._ensure_usable()
        if state is None:
            requested_state = None
            requested_part = None
        else:
            requested_state = int(state)
            if requested_state < 0:
                raise RendererError("palette focus state must be non-negative")
            requested_part = None if part_id is None else int(part_id)
            if requested_part is not None and (
                requested_part < 0
                or not bool(np.any(self._face_part_ids == requested_part))
            ):
                raise RendererError(f"unknown palette focus part ID: {part_id}")
        changed = (
            requested_state != self._palette_usage_focus_state
            or requested_part != self._palette_usage_focus_part_id
        )
        self._palette_usage_focus_state = requested_state
        self._palette_usage_focus_part_id = requested_part
        return changed

    def _upload_face_colors(self, colors: np.ndarray, buffer) -> None:
        vertex_colors = np.ascontiguousarray(np.repeat(colors, 3, axis=0), dtype=np.float32)
        buffer.write(vertex_colors.tobytes())

    def update_colors(
        self,
        result: ColorResult,
        *,
        source: bool = True,
        target: bool = True,
        force: bool = False,
    ) -> None:
        """Upload changed source and target face colours to the GPU.

        Array identity is used as the inexpensive change token.  Call
        :meth:`invalidate_colors` after mutating a colour array in place.
        """

        self._ensure_usable()
        if source:
            original = result.source_face_rgb
            if force or original is not self._source_array_ref:
                colors = _face_colors(result, "source", self._face_count)
                self._upload_face_colors(colors, self._source_color_buffer)
                self._source_array_ref = original
        if target:
            original = result.target_face_rgb
            if force or original is not self._target_array_ref:
                colors = _face_colors(result, "target", self._face_count)
                self._upload_face_colors(colors, self._target_color_buffer)
                self._target_array_ref = original

    def _prepare_draw_state(self) -> None:
        context = self._context
        if context is None:
            raise RendererError("OpenGL context is unavailable.")
        context.enable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        context.disable(moderngl.BLEND)
        context.front_face = "ccw"
        context.cull_face = "back"

    def _render_visibility_color_image(self, vao) -> Image.Image:
        """Render opaque faces first, then a non-depth-writing transparent pass."""

        context = self._context
        framebuffer = self._color_framebuffer
        program = self._visibility_program
        if context is None or framebuffer is None or program is None:
            raise RendererError("Part-visibility framebuffer is unavailable.")
        if vao is self._source_vao:
            visibility_vao = self._visibility_source_vao
        elif vao is self._target_vao:
            visibility_vao = self._visibility_target_vao
        else:
            # Adaptive overlays call this method only with a base source/target
            # VAO.  Refuse an unknown VAO instead of silently drawing the wrong
            # colour buffer.
            raise RendererError("Unknown colour VAO for part visibility render.")
        if visibility_vao is None:
            raise RendererError("Part-visibility colour VAO is unavailable.")

        framebuffer.use()
        context.viewport = (0, 0, self._size[0], self._size[1])
        clear = tuple(channel / 255.0 for channel in self._background)
        framebuffer.clear(clear[0], clear[1], clear[2], 1.0, depth=1.0)

        program["render_pass"].value = 0
        visibility_vao.render(mode=moderngl.TRIANGLES)

        if bool(np.any(self._face_visibility == PART_TRANSPARENT)):
            context.enable(moderngl.BLEND)
            context.blend_func = (
                moderngl.SRC_ALPHA,
                moderngl.ONE_MINUS_SRC_ALPHA,
            )
            context.depth_mask = False
            context.disable(moderngl.CULL_FACE)
            try:
                program["render_pass"].value = 1
                visibility_vao.render(mode=moderngl.TRIANGLES)
            finally:
                context.depth_mask = True
                context.disable(moderngl.BLEND)
                context.enable(moderngl.CULL_FACE)
                context.front_face = "ccw"
                context.cull_face = "back"

        pixels = framebuffer.read(components=4, alignment=1)
        image = Image.frombytes("RGBA", self._size, pixels).transpose(
            Image.Transpose.FLIP_TOP_BOTTOM
        ).convert("RGB")
        # Internal PIL metadata lets the adaptive-paint fallback suppress
        # hidden/transparent roots without changing exported paint data.
        image.info[VISIBILITY_INFO_KEY] = True
        image.info[VISIBILITY_FACE_MODES_INFO_KEY] = self._face_visibility
        return image

    def _render_color_image(self, vao) -> Image.Image:
        if self._visibility_active:
            return self._render_visibility_color_image(vao)
        context = self._context
        framebuffer = self._color_framebuffer
        if context is None or framebuffer is None:
            raise RendererError("Colour framebuffer is unavailable.")
        framebuffer.use()
        context.viewport = (0, 0, self._size[0], self._size[1])
        clear = tuple(channel / 255.0 for channel in self._background)
        framebuffer.clear(clear[0], clear[1], clear[2], 1.0, depth=1.0)
        vao.render(mode=moderngl.TRIANGLES)
        pixels = framebuffer.read(components=4, alignment=1)
        return Image.frombytes("RGBA", self._size, pixels).transpose(
            Image.Transpose.FLIP_TOP_BOTTOM
        ).convert("RGB")

    def _render_face_id_map(self) -> np.ndarray:
        context = self._context
        framebuffer = self._pick_framebuffer
        if context is None or framebuffer is None or self._pick_vao is None:
            raise RendererError("Face-ID framebuffer is unavailable.")
        framebuffer.use()
        context.viewport = (0, 0, self._size[0], self._size[1])
        framebuffer.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        if self._visibility_active:
            if self._visibility_pick_vao is None or self._visibility_pick_program is None:
                raise RendererError("Part-visibility face-ID VAO is unavailable.")
            self._visibility_pick_program["pick_transparent"].value = (
                1 if self._pick_transparent else 0
            )
            self._visibility_pick_vao.render(mode=moderngl.TRIANGLES)
        else:
            self._pick_vao.render(mode=moderngl.TRIANGLES)
        pixels = framebuffer.read(components=1, dtype="u4", alignment=1)
        raw = np.frombuffer(pixels, dtype=np.uint32).reshape(self._size[1], self._size[0])
        top_left = np.flipud(raw).astype(np.int64, copy=True)
        top_left -= 1
        return top_left.astype(np.int32, copy=False)

    def render(
        self,
        result: ColorResult,
        *,
        camera: CameraState | None = None,
        render_source: bool = True,
        render_target: bool = True,
        render_face_ids: bool = True,
        shaded: bool = True,
    ) -> InteractiveRenderFrame:
        """Render synchronized source/target views and an optional pick map."""

        self._ensure_usable()
        try:
            mvp, state, pixels_per_unit = _orbit_camera_mvp(
                self._vertices, self._size, camera
            )
            self.update_colors(
                result,
                source=bool(render_source),
                target=bool(render_target),
            )
            self._prepare_draw_state()
            self._program["mvp"].write(mvp.T.astype(np.float32).tobytes())
            self._pick_program["mvp"].write(mvp.T.astype(np.float32).tobytes())
            if self._visibility_program is not None:
                self._visibility_program["mvp"].write(
                    mvp.T.astype(np.float32).tobytes()
                )
            if self._visibility_pick_program is not None:
                self._visibility_pick_program["mvp"].write(
                    mvp.T.astype(np.float32).tobytes()
                )

            def set_shading(mode: ColorMode) -> None:
                active = _effective_shaded(result, mode, shaded)
                self._program["shade_strength"].value = 1.0 if active else 0.0
                if self._visibility_program is not None:
                    self._visibility_program["shade_strength"].value = (
                        1.0 if active else 0.0
                    )

            source_image = None
            if render_source:
                set_shading("source")
                source_image = self._render_color_image(self._source_vao)
            target_image = None
            if render_target:
                set_shading("target")
                target_image = self._render_color_image(self._target_vao)
            # Rotation preview frames deliberately pass ``render_face_ids=False``
            # to stay fluid.  Active-part decoration must never turn that heavy
            # picking pass back on; the outline is refreshed on the next settled
            # frame that already needs IDs for painting.
            internal_face_ids = self._render_face_id_map() if render_face_ids else None
            if internal_face_ids is not None and self._active_part_id is not None:
                outline_options = {
                    "color": self._active_part_accent,
                    "thickness": self._active_part_outline_thickness,
                }
                if target_image is not None:
                    target_image = overlay_active_part_outline(
                        target_image,
                        internal_face_ids,
                        self._face_part_ids,
                        self._active_part_id,
                        **outline_options,
                    )
                if source_image is not None and self._highlight_active_part_in_source:
                    source_image = overlay_active_part_outline(
                        source_image,
                        internal_face_ids,
                        self._face_part_ids,
                        self._active_part_id,
                        **outline_options,
                    )
            face_ids = internal_face_ids if render_face_ids else None
            return InteractiveRenderFrame(
                source=source_image,
                target=target_image,
                face_ids=face_ids,
                camera=state,
                pixels_per_unit=pixels_per_unit,
            )
        except RendererError:
            raise
        except Exception as exc:
            raise RendererError(f"Interactive ModernGL render failed: {exc}") from exc

    def _release_resources(self) -> None:
        for name in (
            "_pick_framebuffer",
            "_pick_depth",
            "_pick_texture",
            "_color_framebuffer",
            "_pick_vao",
            "_visibility_pick_vao",
            "_visibility_target_vao",
            "_visibility_source_vao",
            "_target_vao",
            "_source_vao",
            "_target_color_buffer",
            "_source_color_buffer",
            "_normal_buffer",
            "_visibility_buffer",
            "_position_buffer",
            "_visibility_pick_program",
            "_visibility_program",
            "_pick_program",
            "_program",
            "_context",
        ):
            resource = getattr(self, name, None)
            _release(resource)
            setattr(self, name, None)

    def close(self) -> None:
        if self._closed:
            return
        self._ensure_usable()
        self._release_resources()
        self._closed = True

    def __enter__(self) -> "InteractiveMeshRenderer":
        self._ensure_usable()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


def render_front_preview(
    level: MeshLevel,
    result: ColorResult,
    *,
    mode: ColorMode = "target",
    size: tuple[int, int] = (600, 740),
    background: Sequence[int] = (9, 10, 13),
    shaded: bool = True,
    direction: PreviewDirection = "front",
) -> Image.Image:
    """Render a front-view model preview as a new RGB ``PIL.Image``.

    ``level`` and ``result`` must describe the same face set. ``mode="source"``
    shows the tone-adjusted model colour; ``mode="target"`` shows the assigned
    ten-state Full Spectrum colours.
    """

    render_size = _validate_size(size)
    render_background = _validate_rgb(background, "背景色")
    context = _create_context()
    try:
        return _render_with_context(
            context,
            level,
            result,
            mode=mode,
            size=render_size,
            background=render_background,
            shaded=bool(shaded),
            direction=direction,
        )
    finally:
        _release(context)


def render_front_preview_pair(
    level: MeshLevel,
    result: ColorResult,
    *,
    size: tuple[int, int] = (600, 740),
    background: Sequence[int] = (9, 10, 13),
    shaded: bool = True,
    active_part_id: int | None = None,
    outline_color: Sequence[int] = (36, 224, 255),
    outline_thickness: int = 2,
    direction: PreviewDirection = "front",
) -> FrontPreviewPair:
    """Render synchronized fixed-front source/target previews and face IDs.

    With ``active_part_id=None`` the two images follow the exact legacy
    :func:`render_front_preview` camera, shader, shading and background path.
    Selecting a part adds the existing non-destructive image-space outline to
    both images.  The outline is never written into ``result`` or the mesh.
    """

    render_size = _validate_size(size)
    render_background = _validate_rgb(background, "背景色")
    vertices, faces = _validate_mesh(level)
    context = _create_context()
    try:
        source = _render_with_context(
            context,
            level,
            result,
            mode="source",
            size=render_size,
            background=render_background,
            shaded=bool(shaded),
            direction=direction,
        )
        target = _render_with_context(
            context,
            level,
            result,
            mode="target",
            size=render_size,
            background=render_background,
            shaded=bool(shaded),
            direction=direction,
        )
        face_ids = _render_front_face_ids_with_context(
            context,
            vertices,
            faces,
            size=render_size,
            direction=direction,
        )
    finally:
        _release(context)

    if active_part_id is not None:
        raw_part_ids = getattr(level, "face_part_ids", None)
        if raw_part_ids is None or np.asarray(raw_part_ids).size == 0:
            face_part_ids = np.zeros(len(faces), dtype=np.int32)
        else:
            part_ids = np.asarray(raw_part_ids)
            if (
                part_ids.shape != (len(faces),)
                or not np.issubdtype(part_ids.dtype, np.integer)
                or (len(part_ids) and int(part_ids.min()) < 0)
            ):
                raise RendererError(
                    "face_part_ids must contain one non-negative integer per face"
                )
            face_part_ids = part_ids.astype(np.int32, copy=False)
        selected_part = int(active_part_id)
        if selected_part < 0 or not bool(np.any(face_part_ids == selected_part)):
            raise RendererError(f"unknown active part ID: {active_part_id}")
        options = {
            "color": outline_color,
            "thickness": outline_thickness,
        }
        source = overlay_active_part_outline(
            source,
            face_ids,
            face_part_ids,
            selected_part,
            **options,
        )
        target = overlay_active_part_outline(
            target,
            face_ids,
            face_part_ids,
            selected_part,
            **options,
        )

    return FrontPreviewPair(source=source, target=target, face_ids=face_ids)


def write_front_preview_png(
    path: Path | str,
    level: MeshLevel,
    result: ColorResult,
    **render_options: object,
) -> Path:
    """Render and atomically save one front-view preview as PNG."""

    output = Path(path)
    image = render_front_preview(level, result, **render_options)  # type: ignore[arg-type]
    return _save_png_atomic(image, output)


def _load_reference_image(value: Path | str | Image.Image) -> Image.Image:
    try:
        if isinstance(value, Image.Image):
            image = value.copy()
        else:
            with Image.open(Path(value)) as opened:
                image = opened.copy()
        return ImageOps.exif_transpose(image)
    except Exception as exc:
        raise RendererError(f"参照画像を読み込めません: {exc}") from exc


def _contain_on_panel(image: Image.Image, size: tuple[int, int], background: RGB) -> Image.Image:
    panel = Image.new("RGB", size, background)
    contained = ImageOps.contain(image.convert("RGBA"), size, method=Image.Resampling.LANCZOS)
    left = (size[0] - contained.width) // 2
    top = (size[1] - contained.height) // 2
    panel.paste(contained, (left, top), contained)
    return panel


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (*linux_pillow_font_candidates(),
        Path("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),
        Path("/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path(r"C:\Windows\Fonts\YuGothM.ttc"),
        Path(r"C:\Windows\Fonts\meiryo.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
    )
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before the optional size argument
        return ImageFont.load_default()


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    area: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.ImageFont,
    fill: RGB,
) -> None:
    box = draw.textbbox((0, 0), text, font=text_font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = area[0] + (area[2] - area[0] - width) / 2.0
    y = area[1] + (area[3] - area[1] - height) / 2.0 - box[1]
    draw.text((x, y), text, font=text_font, fill=fill)


def render_three_column_comparison(
    reference_image: Path | str | Image.Image,
    level: MeshLevel,
    result: ColorResult,
    *,
    panel_size: tuple[int, int] = (480, 600),
    labels: tuple[str, str, str] = ("元画像", "元モデル色", "変換色"),
    background: Sequence[int] = (15, 18, 24),
    panel_background: Sequence[int] = (9, 10, 13),
    text_color: Sequence[int] = (235, 239, 246),
    margin: int = 24,
    gap: int = 20,
    label_height: int = 52,
    shaded: bool = True,
) -> Image.Image:
    """Create a reference/source/converted three-column comparison image."""

    size = _validate_size(panel_size)
    if len(labels) != 3:
        raise RendererError("比較画像のラベルは3個必要です。")
    canvas_background = _validate_rgb(background, "比較画像背景色")
    model_background = _validate_rgb(panel_background, "パネル背景色")
    label_color = _validate_rgb(text_color, "文字色")
    margin = max(0, int(margin))
    gap = max(0, int(gap))
    label_height = max(24, int(label_height))

    reference = _contain_on_panel(_load_reference_image(reference_image), size, model_background)
    context = _create_context()
    try:
        source = _render_with_context(
            context,
            level,
            result,
            mode="source",
            size=size,
            background=model_background,
            shaded=bool(shaded),
        )
        target = _render_with_context(
            context,
            level,
            result,
            mode="target",
            size=size,
            background=model_background,
            shaded=bool(shaded),
        )
    finally:
        _release(context)

    width = margin * 2 + size[0] * 3 + gap * 2
    height = margin * 2 + label_height + size[1]
    canvas = Image.new("RGB", (width, height), canvas_background)
    draw = ImageDraw.Draw(canvas)
    label_font = _font(max(16, min(28, label_height // 2)))
    panels = (reference, source, target)
    for index, (label, panel) in enumerate(zip(labels, panels, strict=True)):
        left = margin + index * (size[0] + gap)
        _draw_centered_text(
            draw,
            (left, margin, left + size[0], margin + label_height),
            str(label),
            label_font,
            label_color,
        )
        canvas.paste(panel, (left, margin + label_height))
    return canvas


def write_three_column_comparison_png(
    path: Path | str,
    reference_image: Path | str | Image.Image,
    level: MeshLevel,
    result: ColorResult,
    **comparison_options: object,
) -> Path:
    """Render and atomically save the three-column comparison as PNG."""

    output = Path(path)
    image = render_three_column_comparison(
        reference_image,
        level,
        result,
        **comparison_options,  # type: ignore[arg-type]
    )
    return _save_png_atomic(image, output)


def _save_png_atomic(image: Image.Image, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        image.save(temporary, format="PNG", optimize=True)
        temporary.replace(output)
    except Exception as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RendererError(f"PNGを書き出せません: {output}: {exc}") from exc
    return output


# Short aliases for GUI call sites.
render_comparison_image = render_three_column_comparison
write_comparison_png = write_three_column_comparison_png


__all__ = [
    "CameraState",
    "FrontPreviewPair",
    "ViewAppearance",
    "ViewTheme",
    "VIEW_THEME_VALUES",
    "VIEW_THEME_BACKGROUNDS",
    "InteractiveRenderFrame",
    "InteractiveMeshRenderer",
    "PART_VISIBLE",
    "PART_TRANSPARENT",
    "PART_HIDDEN",
    "PART_VISIBILITY_VALUES",
    "VISIBILITY_INFO_KEY",
    "VISIBILITY_FACE_MODES_INFO_KEY",
    "RendererError",
    "resolve_view_appearance",
    "overlay_active_part_outline",
    "render_front_preview",
    "render_front_preview_pair",
    "write_front_preview_png",
    "render_three_column_comparison",
    "write_three_column_comparison_png",
    "render_comparison_image",
    "write_comparison_png",
]
