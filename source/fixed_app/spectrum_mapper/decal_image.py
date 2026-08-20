"""Bounded, offline PNG/SVG loading for the beta decal paint tool.

PNG decoding uses Pillow. SVG rasterization uses the pinned ``resvg`` wheel
only after a strict XML preflight. Active content and every resource-bearing
construct are rejected before resvg sees the document; no resource directory
or system fonts are made available to untrusted input.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError


SUPPORTED_DECAL_SUFFIXES = (".png", ".svg")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
_XML_DECLARATION_RE = re.compile(r"^\s*<\?xml\s+[^?]*\?>", re.IGNORECASE)
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Plain SVG export can convert these constructs to paths before decal import.
# They otherwise execute/animate content, access data/fonts, or greatly expand
# render work. ``url(...)`` references are rejected separately, including
# same-document references, so there is no hidden external-resource boundary.
_FORBIDDEN_ELEMENTS = frozenset(
    {
        "a",
        "animate",
        "animatemotion",
        "animatetransform",
        "audio",
        "canvas",
        "cursor",
        "discard",
        "embed",
        "feimage",
        "filter",
        "font-face",
        "font-face-uri",
        "foreignobject",
        "iframe",
        "image",
        "mpath",
        "object",
        "script",
        "set",
        "style",
        "text",
        "textpath",
        "tspan",
        "use",
        "video",
        "view",
    }
)
_REFERENCE_ATTRIBUTE_NAMES = frozenset({"href", "src", "base", "cursor"})
_REFERENCE_VALUE_MARKERS = (
    "url(",
    "@import",
    "javascript:",
    "data:",
    "file:",
    "http:",
    "https:",
    "ftp:",
    "\\\\",
)


@dataclass(frozen=True, slots=True)
class DecalLimits:
    """Resource limits applied before decoded pixels are allocated."""

    max_file_bytes: int = 8 * 1024 * 1024
    max_width: int = 4096
    max_height: int = 4096
    max_pixels: int = 16 * 1024 * 1024
    max_svg_nodes: int = 10_000
    max_svg_depth: int = 64
    max_svg_attributes: int = 40_000
    max_svg_path_characters: int = 1_000_000
    # Approximate raster work as pixels multiplied by vector complexity.  This
    # closes the otherwise-valid worst case where thousands of overlapping
    # vector objects each repaint a 4096 x 4096 canvas.  Complex artwork can
    # still be supplied as a bounded PNG.
    max_svg_render_work: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_DECAL_LIMITS = DecalLimits()


class DecalImageError(ValueError):
    """A user-facing import failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)


@dataclass(frozen=True, slots=True)
class DecalImage:
    """Normalized decal pixels and portable source identity.

    Loader-created ``sha256`` values identify the original PNG/SVG bytes.
    Programmatically constructed instances may omit it; then normalized pixel
    bytes are hashed to give generated/test decals a stable identity.
    """

    rgba: np.ndarray
    source_kind: str
    sha256: str = ""
    source_path: Path | None = None

    def __post_init__(self) -> None:
        array = np.array(self.rgba, dtype=np.uint8, copy=True, order="C")
        if array.ndim != 3 or array.shape[2] != 4:
            raise ValueError("rgba must have shape (height, width, 4)")
        if array.shape[0] <= 0 or array.shape[1] <= 0:
            raise ValueError("rgba must not be empty")
        kind = str(self.source_kind).strip().casefold()
        if kind not in {"png", "svg"}:
            raise ValueError("source_kind must be 'png' or 'svg'")
        digest = str(self.sha256).strip().casefold()
        if not digest:
            digest = hashlib.sha256(array.tobytes(order="C")).hexdigest()
        if _HEX_SHA256_RE.fullmatch(digest) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        source_path = None if self.source_path is None else Path(self.source_path)
        array.setflags(write=False)
        object.__setattr__(self, "rgba", array)
        object.__setattr__(self, "source_kind", kind)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "source_path", source_path)

    @property
    def source_format(self) -> str:
        return self.source_kind.upper()

    @property
    def width(self) -> int:
        return int(self.rgba.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgba.shape[0])

    @property
    def has_transparency(self) -> bool:
        return bool(np.any(self.rgba[:, :, 3] < 255))

    def copy_rgba(self) -> np.ndarray:
        """Return a writable copy for the paint pipeline."""

        return self.rgba.copy()


def load_decal_image(
    path: str | Path,
    *,
    svg_raster_size: tuple[int, int] | None = None,
    limits: DecalLimits = DEFAULT_DECAL_LIMITS,
) -> DecalImage:
    """Load a user-selected PNG or SVG without exposing its directory to SVG."""

    source = Path(path)
    try:
        stat = source.stat()
    except OSError as exc:
        raise DecalImageError("file_unreadable", "デカール画像を読み込めません。") from exc
    if not source.is_file():
        raise DecalImageError("not_a_file", "デカール画像には通常のファイルを指定してください。")
    _validate_file_size(int(stat.st_size), limits)
    try:
        # Recheck through a bounded read so replacing/growing the file between
        # ``stat`` and ``open`` cannot make the importer allocate an
        # arbitrarily large buffer (TOCTOU).  The second size validation also
        # catches a file that changed after the first check.
        with source.open("rb") as stream:
            payload = stream.read(limits.max_file_bytes + 1)
    except OSError as exc:
        raise DecalImageError("file_unreadable", "デカール画像を読み込めません。") from exc
    return load_decal_bytes(
        payload,
        filename=source.name,
        svg_raster_size=svg_raster_size,
        limits=limits,
        _source_path=source,
    )


def load_decal_bytes(
    payload: bytes | bytearray | memoryview,
    *,
    filename: str,
    svg_raster_size: tuple[int, int] | None = None,
    limits: DecalLimits = DEFAULT_DECAL_LIMITS,
    _source_path: Path | None = None,
) -> DecalImage:
    """Decode project-bundled bytes without granting SVG file-system access."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise DecalImageError("invalid_payload", "デカール画像のデータ形式が不正です。")
    try:
        payload_size = payload.nbytes if isinstance(payload, memoryview) else len(payload)
        _validate_file_size(payload_size, limits)
        data = bytes(payload)
    except DecalImageError:
        raise
    except (TypeError, ValueError, BufferError) as exc:
        raise DecalImageError("invalid_payload", "デカール画像のデータ形式が不正です。") from exc
    # A defensive equality check protects against unusual buffer exporters.
    if len(data) != payload_size:
        raise DecalImageError("invalid_payload", "デカール画像のデータ長が一致しません。")
    suffix = Path(str(filename)).suffix.casefold()
    if suffix not in SUPPORTED_DECAL_SUFFIXES:
        raise DecalImageError(
            "unsupported_file_type", "デカール画像はPNGまたはSVGを指定してください。"
        )
    digest = hashlib.sha256(data).hexdigest()
    if suffix == ".png":
        rgba = _decode_png(data, limits, expected_size=None)
        kind = "png"
    else:
        rgba = _decode_svg(data, svg_raster_size, limits)
        kind = "svg"
    return DecalImage(
        rgba=rgba,
        source_kind=kind,
        sha256=digest,
        source_path=_source_path,
    )


def _validate_file_size(size: int, limits: DecalLimits) -> None:
    if size <= 0:
        raise DecalImageError("empty_file", "デカール画像が空です。")
    if size > limits.max_file_bytes:
        raise DecalImageError(
            "file_too_large",
            f"デカール画像は{limits.max_file_bytes // (1024 * 1024)} MiB以下にしてください。",
        )


def _validate_dimensions(width: int, height: int, limits: DecalLimits) -> None:
    if width <= 0 or height <= 0:
        raise DecalImageError("invalid_dimensions", "画像の幅と高さは1以上である必要があります。")
    if width > limits.max_width or height > limits.max_height:
        raise DecalImageError(
            "dimensions_too_large",
            f"画像は最大{limits.max_width}×{limits.max_height}pxです。",
        )
    if width * height > limits.max_pixels:
        raise DecalImageError(
            "pixel_limit_exceeded",
            f"画像の総画素数は{limits.max_pixels:,}以下にしてください。",
        )


def _normalize_raster_size(
    value: tuple[int, int] | None,
    limits: DecalLimits,
) -> tuple[int, int] | None:
    if value is None:
        return None
    try:
        width, height = value
    except (TypeError, ValueError) as exc:
        raise DecalImageError(
            "invalid_svg_raster_size", "SVG出力サイズは幅と高さで指定してください。"
        ) from exc
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
    ):
        raise DecalImageError(
            "invalid_svg_raster_size", "SVG出力サイズは整数で指定してください。"
        )
    _validate_dimensions(width, height, limits)
    return width, height


def _decode_png(
    data: bytes,
    limits: DecalLimits,
    *,
    expected_size: tuple[int, int] | None,
) -> np.ndarray:
    if not data.startswith(_PNG_SIGNATURE):
        raise DecalImageError("content_mismatch", "拡張子はPNGですが、内容がPNGではありません。")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise DecalImageError(
                    "content_mismatch", "拡張子はPNGですが、内容がPNGではありません。"
                )
            width, height = map(int, image.size)
            _validate_dimensions(width, height, limits)
            if expected_size is not None and (width, height) != expected_size:
                raise DecalImageError(
                    "svg_render_size_mismatch", "SVGのラスタライズ結果サイズが一致しません。"
                )
            if int(getattr(image, "n_frames", 1)) != 1:
                raise DecalImageError(
                    "animated_png_unsupported", "アニメーションPNGはデカールに使用できません。"
                )
            image.seek(0)
            image.load()
            return np.asarray(image.convert("RGBA"), dtype=np.uint8)
    except DecalImageError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise DecalImageError("invalid_png", "PNG画像が破損しているか対応外です。") from exc


def _decode_svg(
    data: bytes,
    raster_size: tuple[int, int] | None,
    limits: DecalLimits,
) -> np.ndarray:
    requested_size = _normalize_raster_size(raster_size, limits)
    text, node_count, path_characters = _decode_and_preflight_svg(data, limits)
    try:
        import resvg
    except (ImportError, OSError) as exc:
        raise DecalImageError(
            "svg_renderer_unavailable", "SVG描画エンジンを読み込めません。PNGを使用してください。"
        ) from exc
    try:
        options = resvg.usvg.Options.default()
        if options.resources_dir is not None:
            raise RuntimeError("resvg default unexpectedly enables a resource directory")
        tree = resvg.usvg.Tree.from_str(text, options)
        natural_width, natural_height = map(int, tree.int_size())
    except (RuntimeError, ValueError, OSError) as exc:
        raise DecalImageError("invalid_svg", "SVGの解析または描画準備に失敗しました。") from exc
    _validate_dimensions(natural_width, natural_height, limits)
    output_size = requested_size or (natural_width, natural_height)
    complexity_units = node_count + math.ceil(path_characters / 256)
    render_work = output_size[0] * output_size[1] * max(1, complexity_units)
    if render_work > limits.max_svg_render_work:
        raise DecalImageError(
            "svg_render_work_limit",
            "SVGの解像度と複雑さの組み合わせが上限を超えています。PNGに変換してください。",
        )
    scale_x = output_size[0] / natural_width
    scale_y = output_size[1] / natural_height
    transform = (scale_x, 0.0, 0.0, 0.0, scale_y, 0.0)
    if not all(math.isfinite(value) for value in transform):
        raise DecalImageError("invalid_svg_dimensions", "SVGの出力倍率が不正です。")
    try:
        rendered = bytes(
            resvg.render(
                tree,
                transform,
                bg_size=output_size,
                bg_color=(0, 0, 0, 0),
            )
        )
    except (RuntimeError, ValueError, OSError) as exc:
        raise DecalImageError("svg_render_failed", "SVGのラスタライズに失敗しました。") from exc
    return _decode_png(rendered, limits, expected_size=output_size)


def _decode_and_preflight_svg(
    data: bytes, limits: DecalLimits
) -> tuple[str, int, int]:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in data[:256]:
        raise DecalImageError("svg_encoding_unsupported", "SVGはUTF-8で保存してください。")
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise DecalImageError("svg_encoding_unsupported", "SVGはUTF-8で保存してください。") from exc
    folded = text.casefold()
    if "<!doctype" in folded or "<!entity" in folded:
        raise DecalImageError(
            "svg_unsafe_xml", "DOCTYPEやENTITYを含むSVGは読み込めません。"
        )
    if "<?" in _XML_DECLARATION_RE.sub("", text, count=1):
        raise DecalImageError("svg_unsafe_xml", "処理命令を含むSVGは読み込めません。")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise DecalImageError("invalid_svg", "SVGのXML構造が正しくありません。") from exc
    root_namespace, root_name = _split_xml_name(root.tag)
    if root_name.casefold() != "svg" or root_namespace not in {"", _SVG_NAMESPACE}:
        raise DecalImageError("invalid_svg_root", "SVGのルート要素が見つかりません。")

    node_count = 0
    attribute_count = 0
    path_characters = 0
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        node_count += 1
        if node_count > limits.max_svg_nodes:
            raise DecalImageError("svg_node_limit", "SVGの要素数が上限を超えています。")
        if depth > limits.max_svg_depth:
            raise DecalImageError("svg_depth_limit", "SVGの入れ子が深すぎます。")
        namespace, local_name = _split_xml_name(element.tag)
        local = local_name.casefold()
        if namespace not in {"", _SVG_NAMESPACE}:
            raise DecalImageError(
                "svg_external_reference", "外部名前空間を含むSVGは読み込めません。"
            )
        if local in _FORBIDDEN_ELEMENTS:
            code = (
                "svg_external_reference"
                if local in {"a", "image", "use", "feimage"}
                else "svg_active_content"
            )
            raise DecalImageError(code, f"SVG要素 <{local_name}> はデカールに使用できません。")
        attribute_count += len(element.attrib)
        if attribute_count > limits.max_svg_attributes:
            raise DecalImageError("svg_attribute_limit", "SVGの属性数が上限を超えています。")
        for raw_name, raw_value in element.attrib.items():
            attr_namespace, attr_name = _split_xml_name(raw_name)
            attr = attr_name.casefold()
            if attr_namespace not in {"", _XML_NAMESPACE}:
                raise DecalImageError(
                    "svg_external_reference", "外部名前空間や参照を含むSVGは読み込めません。"
                )
            if attr_namespace == _XML_NAMESPACE and attr != "space":
                raise DecalImageError(
                    "svg_external_reference", "XML外部参照属性を含むSVGは読み込めません。"
                )
            if attr.startswith("on"):
                raise DecalImageError("svg_active_content", "イベント属性を含むSVGは読み込めません。")
            if attr == "style":
                raise DecalImageError("svg_active_content", "style属性を含むSVGは読み込めません。")
            if attr in _REFERENCE_ATTRIBUTE_NAMES:
                raise DecalImageError(
                    "svg_external_reference", "参照属性を含むSVGは読み込めません。"
                )
            folded_value = str(raw_value).casefold()
            if any(marker in folded_value for marker in _REFERENCE_VALUE_MARKERS):
                raise DecalImageError(
                    "svg_external_reference", "外部参照やURLを含むSVGは読み込めません。"
                )
            if attr == "d":
                path_characters += len(str(raw_value))
                if path_characters > limits.max_svg_path_characters:
                    raise DecalImageError("svg_path_limit", "SVGパスのデータ量が上限を超えています。")
        stack.extend((child, depth + 1) for child in reversed(list(element)))
    return text, node_count, path_characters


def _split_xml_name(name: str) -> tuple[str, str]:
    if name.startswith("{") and "}" in name:
        namespace, local = name[1:].split("}", 1)
        return namespace, local
    return "", name


__all__ = [
    "DEFAULT_DECAL_LIMITS",
    "SUPPORTED_DECAL_SUFFIXES",
    "DecalImage",
    "DecalImageError",
    "DecalLimits",
    "load_decal_bytes",
    "load_decal_image",
]
