"""Safe static glTF 2.0 import with colour baking.

The application works with one RGB value per mesh vertex.  This module turns
the static, rendered base colour of a glTF/GLB scene into that representation:

* scene and node transforms are baked into positions;
* each instantiated mesh node remains one stable application part;
* triangle lists, strips, and fans become indexed triangles;
* ``COLOR_0``, ``baseColorFactor``, and ``baseColorTexture`` are normally
  multiplied in linear space and encoded back to sRGB for the existing colour
  pipeline;
* the default ``auto`` policy recognizes a narrow multipart-segmentation
  signature and omits those categorical ``COLOR_0`` display IDs.  Callers can
  force either standards-compliant multiplication or omission explicitly.

Outside that documented compatibility signature, the importer deliberately
does not guess when a feature would change geometry or colour.  Animation,
skinning, morph targets, Draco/meshopt compression, BasisU textures, and
external URIs therefore stop with ``GltfImportError``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import math
import os
import re
import struct
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

import numpy as np
from PIL import Image, UnidentifiedImageError

from .models import ObjAsset, ProgressCallback


class GltfImportError(RuntimeError):
    """The file cannot be represented safely by the static colour pipeline."""


VertexColorPolicy = Literal["auto", "multiply", "ignore"]


_GLB_MAGIC = b"glTF"
_GLB_JSON_CHUNK = 0x4E4F534A
_GLB_BIN_CHUNK = 0x004E4942
_MAX_FILE_BYTES = 512 * 1024 * 1024
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_EMBEDDED_BYTES = _MAX_FILE_BYTES
_MAX_IMAGE_PIXELS = 100_000_000
_MAX_TOTAL_IMAGE_PIXELS = 128_000_000
_MAX_ACCESSOR_VALUES = 16_000_000
_MAX_TOTAL_ACCESSOR_VALUES = 64_000_000
_MAX_IMPORTED_VERTICES = 3_000_000
_MAX_IMPORTED_FACES = 3_000_000
# Indexed TRIANGLES use three scalar accessor values per face.  Keep this
# admission below the independent per-accessor limit as well as the other
# file, vertex, and total-accessor budgets enforced by the preflight.
_MAX_REDUCED_SOURCE_FACES = 5_250_000
LARGE_GLTF_REDUCTION_TARGET_FACES = 450_000
GLTF_SOURCE_VERTEX_LIMIT = _MAX_IMPORTED_VERTICES
GLTF_NORMAL_SOURCE_FACE_LIMIT = _MAX_IMPORTED_FACES
GLTF_REDUCED_SOURCE_FACE_LIMIT = _MAX_REDUCED_SOURCE_FACES
_TEXTURE_SAMPLE_CHUNK_VERTICES = 131_072
_MAX_NODES = 10_000
_MAX_PRIMITIVES = 10_000
_MAX_NODE_DEPTH = 512
_VERTEX_COLOR_POLICIES = frozenset({"auto", "multiply", "ignore"})
_GLTF_IMPORT_METADATA_SCHEMA = "obj-adjuster.gltf-import.v1"
_AUTO_SEGMENTATION_MIN_DOMINANT_SHARE = 0.85
_AUTO_SEGMENTATION_MIN_CHANNEL_RANGE = 32
# Known categorical sequence written by the compatible exploded-part export.
# Requiring the exact prefix makes an arbitrary authored per-part tint retain
# normal glTF multiplication even when it comes from the same Three.js stack.
_EXPLODED_PART_ID_PALETTE = (
    (31, 119, 180),
    (174, 199, 232),
    (255, 127, 14),
    (255, 187, 120),
    (44, 160, 44),
    (152, 223, 138),
    (214, 39, 40),
    (255, 152, 150),
    (148, 103, 189),
    (197, 176, 213),
    (140, 86, 75),
    (196, 156, 148),
    (227, 119, 194),
    (247, 182, 210),
    (127, 127, 127),
    (199, 199, 199),
    (188, 189, 34),
    (219, 219, 141),
    (23, 190, 207),
    (158, 218, 229),
)

_COMPONENTS = {
    5120: (np.dtype("i1"), 1),
    5121: (np.dtype("u1"), 1),
    5122: (np.dtype("<i2"), 2),
    5123: (np.dtype("<u2"), 2),
    5125: (np.dtype("<u4"), 4),
    5126: (np.dtype("<f4"), 4),
}
_TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
}
_UNSIGNED_INDEX_COMPONENTS = {5121, 5123, 5125}
_NORMALIZED_COLOR_COMPONENTS = {5121, 5123}
_NORMALIZED_TEXCOORD_COMPONENTS = {5121, 5123}
_SUPPORTED_REQUIRED_EXTENSIONS = {
    "KHR_materials_unlit",
    "KHR_texture_transform",
}
_FORBIDDEN_REQUIRED_EXTENSIONS = {
    "EXT_meshopt_compression",
    "KHR_draco_mesh_compression",
    "KHR_texture_basisu",
}
_VERSION_TOKEN = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")


@dataclass(frozen=True, slots=True)
class GltfImportPlan:
    """JSON-only workload estimate for the selected static glTF scene.

    The counts include every selected node instance.  Triangle count is the
    exact primitive workload before degenerate triangles are discarded;
    vertex count is a conservative POSITION-accessor upper bound before
    unreferenced vertices are compacted.
    """

    vertex_count_upper_bound: int
    triangle_count: int
    mesh_node_count: int
    primitive_instance_count: int
    primitive_modes: tuple[int, ...]

    @property
    def requires_reduced_mode(self) -> bool:
        return self.triangle_count > _MAX_IMPORTED_FACES

    @property
    def supports_reduced_mode(self) -> bool:
        return bool(
            self.requires_reduced_mode
            and self.vertex_count_upper_bound <= _MAX_IMPORTED_VERTICES
            and self.triangle_count <= _MAX_REDUCED_SOURCE_FACES
            and self.primitive_modes
            and all(mode == 4 for mode in self.primitive_modes)
        )


def _emit(
    callback: ProgressCallback | None,
    phase: str,
    fraction: float,
    message: str,
) -> None:
    if callback is not None:
        callback(phase, max(0.0, min(1.0, float(fraction))), message)


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GltfImportError(f"{label} must be an integer")
    if value < minimum:
        raise GltfImportError(f"{label} must be at least {minimum}")
    return int(value)


def _index(value: Any, sequence: Sequence[Any], label: str) -> int:
    result = _integer(value, label)
    if result >= len(sequence):
        raise GltfImportError(
            f"{label} is out of range: {result} / {len(sequence)}"
        )
    return result


def _array(value: Any, label: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GltfImportError(f"{label} must be an array")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GltfImportError(f"{label} must be an object")
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GltfImportError(f"glTF JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _decode_json(raw: bytes, label: str) -> dict[str, Any]:
    if len(raw) > _MAX_JSON_BYTES:
        raise GltfImportError(
            f"{label} JSON is too large ({len(raw):,} bytes)"
        )
    try:
        value = json.loads(
            raw.rstrip(b" \t\r\n\0").decode("utf-8-sig"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except RecursionError as exc:
        raise GltfImportError(f"{label} JSON nesting is too deep") from exc
    except MemoryError as exc:
        raise GltfImportError(f"{label} JSON exceeds safe memory limits") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GltfImportError(f"{label} JSON cannot be decoded: {exc}") from exc
    return _object(value, f"{label} root")


def _read_glb_json_only(path: Path) -> dict[str, Any]:
    """Read only the first GLB JSON chunk for a cheap workload preflight."""

    with path.open("rb") as stream:
        file_size = os.fstat(stream.fileno()).st_size
        if file_size < 20:
            raise GltfImportError("GLB is shorter than its required header/chunk")
        if file_size > _MAX_FILE_BYTES:
            raise GltfImportError("GLB exceeds the 512 MiB safe import limit")
        header = stream.read(12)
        if len(header) != 12:
            raise GltfImportError("GLB header is truncated")
        magic, version, declared_length = struct.unpack("<4sII", header)
        if magic != _GLB_MAGIC:
            raise GltfImportError("GLB magic is not 'glTF'")
        if version != 2:
            raise GltfImportError(f"Only GLB 2.0 is supported (found {version})")
        if declared_length != file_size:
            raise GltfImportError(
                "GLB declared length does not match the file: "
                f"{declared_length:,} / {file_size:,}"
            )
        chunk_header = stream.read(8)
        if len(chunk_header) != 8:
            raise GltfImportError("GLB chunk 1 header is truncated")
        chunk_length, chunk_type = struct.unpack("<II", chunk_header)
        if chunk_length % 4:
            raise GltfImportError("GLB chunk 1 is not 4-byte aligned")
        if chunk_type != _GLB_JSON_CHUNK:
            raise GltfImportError("The GLB JSON chunk must be first")
        if chunk_length > _MAX_JSON_BYTES:
            raise GltfImportError("GLB JSON chunk is too large")
        if chunk_length > file_size - stream.tell():
            raise GltfImportError("GLB chunk 1 is truncated")
        json_raw = stream.read(chunk_length)
    return _decode_json(json_raw, "GLB")


def _read_glb(
    path: Path,
) -> tuple[dict[str, Any], bytes | None, str, int]:
    with path.open("rb") as stream:
        file_size = os.fstat(stream.fileno()).st_size
        if file_size < 20:
            raise GltfImportError("GLB is shorter than its required header/chunk")
        if file_size > _MAX_FILE_BYTES:
            raise GltfImportError("GLB exceeds the 512 MiB safe import limit")
        digest = hashlib.sha256()

        def read_hashed(size: int) -> bytes:
            data = stream.read(size)
            digest.update(data)
            return data

        header = read_hashed(12)
        if len(header) != 12:
            raise GltfImportError("GLB header is truncated")
        magic, version, declared_length = struct.unpack("<4sII", header)
        if magic != _GLB_MAGIC:
            raise GltfImportError("GLB magic is not 'glTF'")
        if version != 2:
            raise GltfImportError(f"Only GLB 2.0 is supported (found {version})")
        if declared_length != file_size:
            raise GltfImportError(
                "GLB declared length does not match the file: "
                f"{declared_length:,} / {file_size:,}"
            )
        json_raw: bytes | None = None
        binary: bytes | None = None
        chunk_number = 0
        while stream.tell() < file_size:
            chunk_number += 1
            header_raw = read_hashed(8)
            if len(header_raw) != 8:
                raise GltfImportError(f"GLB chunk {chunk_number} header is truncated")
            chunk_length, chunk_type = struct.unpack("<II", header_raw)
            if chunk_length % 4:
                raise GltfImportError(
                    f"GLB chunk {chunk_number} is not 4-byte aligned"
                )
            if chunk_length > file_size - stream.tell():
                raise GltfImportError(f"GLB chunk {chunk_number} is truncated")
            if chunk_type == _GLB_JSON_CHUNK:
                if json_raw is not None:
                    raise GltfImportError("GLB contains more than one JSON chunk")
                if chunk_number != 1:
                    raise GltfImportError("The GLB JSON chunk must be first")
                if chunk_length > _MAX_JSON_BYTES:
                    raise GltfImportError("GLB JSON chunk is too large")
                json_raw = read_hashed(chunk_length)
            elif chunk_type == _GLB_BIN_CHUNK:
                if binary is not None:
                    raise GltfImportError("GLB contains more than one BIN chunk")
                if chunk_length > _MAX_EMBEDDED_BYTES:
                    raise GltfImportError("GLB BIN chunk is too large")
                binary = read_hashed(chunk_length)
            else:
                # glTF requires unknown chunks to be ignored.  Hash them in
                # bounded pieces so the returned identity still belongs to the
                # exact stream that supplied JSON and BIN.
                remaining = chunk_length
                while remaining:
                    block = read_hashed(min(remaining, 1024 * 1024))
                    if not block:
                        raise GltfImportError(
                            f"GLB chunk {chunk_number} is truncated"
                        )
                    remaining -= len(block)
        if json_raw is None:
            raise GltfImportError("GLB has no JSON chunk")
        if os.fstat(stream.fileno()).st_size != file_size:
            raise GltfImportError("GLB changed while it was being read")
    return (
        _decode_json(json_raw, "GLB"),
        binary,
        digest.hexdigest().upper(),
        file_size,
    )


def _read_document(
    path: Path,
) -> tuple[dict[str, Any], bytes | None, str, int]:
    suffix = path.suffix.lower()
    if suffix == ".glb":
        return _read_glb(path)
    if suffix == ".gltf":
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise GltfImportError(f"glTF cannot be read: {exc}") from exc
        return (
            _decode_json(raw, "glTF"),
            None,
            hashlib.sha256(raw).hexdigest().upper(),
            len(raw),
        )
    raise GltfImportError("Only .glb and .gltf files are supported")


def _read_document_json_only(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".glb":
        return _read_glb_json_only(path)
    if suffix == ".gltf":
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise GltfImportError(f"glTF cannot be read: {exc}") from exc
        return _decode_json(raw, "glTF")
    raise GltfImportError("Only .glb and .gltf files are supported")


def _decode_data_uri(uri: str, label: str) -> tuple[str, bytes]:
    if not uri.startswith("data:"):
        raise GltfImportError(
            f"{label} uses an external URI. Only GLB or embedded data URIs are allowed"
        )
    header, separator, payload = uri[5:].partition(",")
    if not separator:
        raise GltfImportError(f"{label} data URI has no comma")
    pieces = header.split(";") if header else [""]
    mime_type = pieces[0].strip().lower()
    is_base64 = bool(pieces and pieces[-1].lower() == "base64")
    try:
        if is_base64:
            compact = "".join(payload.split())
            raw = base64.b64decode(compact, validate=True)
        else:
            raw = urllib.parse.unquote_to_bytes(payload)
    except (ValueError, binascii.Error) as exc:
        raise GltfImportError(f"{label} data URI cannot be decoded") from exc
    if len(raw) > _MAX_EMBEDDED_BYTES:
        raise GltfImportError(f"{label} embedded data is too large")
    return mime_type, raw


def _image_mime_from_magic(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def _version_tuple(value: Any, label: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise GltfImportError(f"{label} must be a version string")
    match = _VERSION_TOKEN.fullmatch(value)
    if match is None:
        raise GltfImportError(f"Invalid {label}: {value!r}")
    return tuple(int(item or 0) for item in match.groups())  # type: ignore[return-value]


def _validate_document(document: Mapping[str, Any]) -> list[str]:
    asset = _object(document.get("asset"), "asset")
    version_value = asset.get("version")
    version = _version_tuple(version_value, "glTF asset.version")
    if version[0] != 2:
        raise GltfImportError(
            f"Only glTF 2.0 is supported (asset.version={version_value!r})"
        )
    if "minVersion" in asset:
        minimum = _version_tuple(asset["minVersion"], "glTF asset.minVersion")
        if minimum[:2] > (2, 0):
            raise GltfImportError(
                "glTF requires a newer implementation "
                f"(asset.minVersion={asset['minVersion']!r})"
            )
    if document.get("animations"):
        raise GltfImportError(
            "Animated glTF is not supported. Export a static/rest-pose mesh"
        )
    if document.get("skins"):
        raise GltfImportError(
            "Skinned glTF is not supported. Apply/bake the armature before export"
        )
    required = _array(document.get("extensionsRequired", []), "extensionsRequired")
    required_names: list[str] = []
    for item in required:
        if not isinstance(item, str):
            raise GltfImportError("extensionsRequired entries must be strings")
        required_names.append(item)
    forbidden = sorted(set(required_names) & _FORBIDDEN_REQUIRED_EXTENSIONS)
    if forbidden:
        raise GltfImportError(
            "Unsupported compressed glTF extension(s): " + ", ".join(forbidden)
        )
    unsupported = sorted(set(required_names) - _SUPPORTED_REQUIRED_EXTENSIONS)
    if unsupported:
        raise GltfImportError(
            "Unsupported required glTF extension(s): " + ", ".join(unsupported)
        )
    warnings: list[str] = []
    if document.get("extensionsUsed"):
        used = _array(document["extensionsUsed"], "extensionsUsed")
        optional_unknown = sorted(
            {
                str(item)
                for item in used
                if isinstance(item, str)
            }
            - set(required_names)
            - _SUPPORTED_REQUIRED_EXTENSIONS
        )
        if optional_unknown:
            warnings.append(
                "色と静的形状に影響しない任意拡張として読み飛ばしました: "
                + ", ".join(optional_unknown)
            )
    return warnings


class _Reader:
    def __init__(
        self,
        document: dict[str, Any],
        glb_binary: bytes | None,
        warnings: list[str],
    ) -> None:
        self.document = document
        self.warnings = warnings
        self.buffer_defs = _array(document.get("buffers", []), "buffers")
        self.buffer_views = _array(document.get("bufferViews", []), "bufferViews")
        self.accessors = _array(document.get("accessors", []), "accessors")
        self.images = _array(document.get("images", []), "images")
        self.textures = _array(document.get("textures", []), "textures")
        self.samplers = _array(document.get("samplers", []), "samplers")
        self.materials = _array(document.get("materials", []), "materials")
        for image_id, raw_image in enumerate(self.images):
            image_definition = _object(raw_image, f"images[{image_id}]")
            image_uri = image_definition.get("uri")
            if image_uri is not None and (
                not isinstance(image_uri, str) or not image_uri.startswith("data:")
            ):
                raise GltfImportError(
                    f"images[{image_id}] uses an external URI. "
                    "Only GLB or embedded data URIs are allowed"
                )
        self.buffers = self._load_buffers(glb_binary)
        # Opaque Hi3D base-colour maps can be 8192 x 8192.  Keep those as
        # three-channel RGB instead of expanding a JPEG to a 256 MiB RGBA
        # array.  Images which really contain alpha remain four-channel.
        self._image_cache: dict[int, np.ndarray] = {}
        self._accessor_cache: dict[int, tuple[np.ndarray, dict[str, Any]]] = {}
        self._decoded_accessor_values = 0
        self._decoded_image_pixels = 0
        self.ignored_appearance_maps: set[str] = set()

    def _load_buffers(self, glb_binary: bytes | None) -> list[bytes]:
        output: list[bytes] = []
        consumed_glb = False
        for buffer_index, raw_definition in enumerate(self.buffer_defs):
            definition = _object(raw_definition, f"buffers[{buffer_index}]")
            declared = _integer(
                definition.get("byteLength"),
                f"buffers[{buffer_index}].byteLength",
            )
            uri = definition.get("uri")
            if uri is None:
                if glb_binary is None or buffer_index != 0 or consumed_glb:
                    raise GltfImportError(
                        f"buffers[{buffer_index}] has no embedded GLB BIN data"
                    )
                raw = glb_binary
                consumed_glb = True
            else:
                if not isinstance(uri, str):
                    raise GltfImportError(f"buffers[{buffer_index}].uri must be text")
                _mime, raw = _decode_data_uri(uri, f"buffers[{buffer_index}]")
            if declared > len(raw):
                raise GltfImportError(
                    f"buffers[{buffer_index}] is truncated: {len(raw):,} / {declared:,} bytes"
                )
            # GLB permits up to three padding bytes after declared byteLength.
            if len(raw) - declared > 3 and uri is None:
                raise GltfImportError(
                    f"buffers[{buffer_index}] has unexpected BIN data after byteLength"
                )
            output.append(raw[:declared])
        if glb_binary is not None and not consumed_glb and glb_binary.rstrip(b"\0"):
            raise GltfImportError("GLB has a BIN chunk but no matching buffer")
        return output

    def _view(self, view_index: int, label: str) -> tuple[bytes, int, int, dict[str, Any]]:
        view_id = _index(view_index, self.buffer_views, label)
        view = _object(self.buffer_views[view_id], f"bufferViews[{view_id}]")
        extensions = view.get("extensions")
        if isinstance(extensions, dict) and "EXT_meshopt_compression" in extensions:
            raise GltfImportError("EXT_meshopt_compression buffer views are unsupported")
        buffer_id = _index(
            view.get("buffer"), self.buffers, f"bufferViews[{view_id}].buffer"
        )
        offset = _integer(
            view.get("byteOffset", 0), f"bufferViews[{view_id}].byteOffset"
        )
        length = _integer(
            view.get("byteLength"), f"bufferViews[{view_id}].byteLength"
        )
        if offset + length > len(self.buffers[buffer_id]):
            raise GltfImportError(f"bufferViews[{view_id}] exceeds its buffer")
        return self.buffers[buffer_id], offset, length, view

    @staticmethod
    def _normalize(values: np.ndarray, component_type: int) -> np.ndarray:
        if component_type == 5120:
            return np.maximum(values.astype(np.float64) / 127.0, -1.0)
        if component_type == 5121:
            return values.astype(np.float64) / 255.0
        if component_type == 5122:
            return np.maximum(values.astype(np.float64) / 32767.0, -1.0)
        if component_type == 5123:
            return values.astype(np.float64) / 65535.0
        if component_type == 5125:
            return values.astype(np.float64) / 4294967295.0
        return values.astype(np.float64)

    def _packed_array(
        self,
        *,
        view_index: int,
        byte_offset: int,
        count: int,
        components: int,
        component_type: int,
        label: str,
        honor_stride: bool,
    ) -> np.ndarray:
        dtype, item_size = _COMPONENTS[component_type]
        element_size = components * item_size
        raw, view_start, view_length, view = self._view(view_index, label)
        if byte_offset % item_size:
            raise GltfImportError(f"{label} byteOffset is not component-aligned")
        if not honor_stride and "byteStride" in view:
            raise GltfImportError(f"{label} sparse bufferView cannot have byteStride")
        stride_value = view.get("byteStride") if honor_stride else None
        if stride_value is None:
            stride = element_size
        else:
            stride = _integer(stride_value, f"{label} byteStride", minimum=4)
            if stride % 4 or stride > 252 or stride < element_size:
                raise GltfImportError(
                    f"{label} has invalid byteStride {stride} for {element_size}-byte elements"
                )
        required = 0 if count == 0 else (count - 1) * stride + element_size
        if byte_offset + required > view_length:
            raise GltfImportError(f"{label} exceeds its bufferView")
        absolute = view_start + byte_offset
        try:
            view_array = np.ndarray(
                shape=(count, components),
                dtype=dtype,
                buffer=raw,
                offset=absolute,
                strides=(stride, item_size),
            )
        except (TypeError, ValueError) as exc:
            raise GltfImportError(f"{label} cannot be decoded") from exc
        return view_array.copy()

    def accessor(
        self,
        accessor_index: int,
        label: str,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        accessor_id = _index(accessor_index, self.accessors, label)
        cached = self._accessor_cache.get(accessor_id)
        if cached is not None:
            return cached
        definition = _object(self.accessors[accessor_id], f"accessors[{accessor_id}]")
        if definition.get("extensions"):
            raise GltfImportError(f"accessors[{accessor_id}] uses unsupported extensions")
        component_type = _integer(
            definition.get("componentType"),
            f"accessors[{accessor_id}].componentType",
        )
        if component_type not in _COMPONENTS:
            raise GltfImportError(
                f"accessors[{accessor_id}] has unsupported componentType {component_type}"
            )
        accessor_type = definition.get("type")
        if accessor_type not in _TYPE_COMPONENTS:
            raise GltfImportError(
                f"accessors[{accessor_id}] has unsupported type {accessor_type!r}"
            )
        components = _TYPE_COMPONENTS[str(accessor_type)]
        count = _integer(
            definition.get("count"), f"accessors[{accessor_id}].count"
        )
        if count * components > _MAX_ACCESSOR_VALUES:
            raise GltfImportError(f"accessors[{accessor_id}] is too large")
        byte_offset = _integer(
            definition.get("byteOffset", 0),
            f"accessors[{accessor_id}].byteOffset",
        )
        view_value = definition.get("bufferView")
        sparse = definition.get("sparse")
        if view_value is None:
            if sparse is None:
                raise GltfImportError(
                    f"accessors[{accessor_id}] has neither bufferView nor sparse data"
                )
            if byte_offset:
                raise GltfImportError(
                    f"accessors[{accessor_id}] byteOffset requires a bufferView"
                )
            dtype = _COMPONENTS[component_type][0]
            values = np.zeros((count, components), dtype=dtype)
        else:
            values = self._packed_array(
                view_index=_integer(view_value, f"accessors[{accessor_id}].bufferView"),
                byte_offset=byte_offset,
                count=count,
                components=components,
                component_type=component_type,
                label=f"accessors[{accessor_id}]",
                honor_stride=True,
            )
        if sparse is not None:
            sparse_obj = _object(sparse, f"accessors[{accessor_id}].sparse")
            sparse_count = _integer(
                sparse_obj.get("count"),
                f"accessors[{accessor_id}].sparse.count",
            )
            if sparse_count > count:
                raise GltfImportError(
                    f"accessors[{accessor_id}] sparse count exceeds accessor count"
                )
            indices_def = _object(
                sparse_obj.get("indices"),
                f"accessors[{accessor_id}].sparse.indices",
            )
            sparse_component = _integer(
                indices_def.get("componentType"),
                f"accessors[{accessor_id}].sparse.indices.componentType",
            )
            if sparse_component not in _UNSIGNED_INDEX_COMPONENTS:
                raise GltfImportError("Sparse indices must be unsigned integers")
            sparse_indices = self._packed_array(
                view_index=_integer(
                    indices_def.get("bufferView"),
                    f"accessors[{accessor_id}].sparse.indices.bufferView",
                ),
                byte_offset=_integer(
                    indices_def.get("byteOffset", 0),
                    f"accessors[{accessor_id}].sparse.indices.byteOffset",
                ),
                count=sparse_count,
                components=1,
                component_type=sparse_component,
                label=f"accessors[{accessor_id}].sparse.indices",
                honor_stride=False,
            ).reshape(-1).astype(np.int64)
            if sparse_count and (
                int(sparse_indices[-1]) >= count
                or np.any(np.diff(sparse_indices) <= 0)
            ):
                raise GltfImportError(
                    f"accessors[{accessor_id}] sparse indices are invalid or unsorted"
                )
            values_def = _object(
                sparse_obj.get("values"),
                f"accessors[{accessor_id}].sparse.values",
            )
            sparse_values = self._packed_array(
                view_index=_integer(
                    values_def.get("bufferView"),
                    f"accessors[{accessor_id}].sparse.values.bufferView",
                ),
                byte_offset=_integer(
                    values_def.get("byteOffset", 0),
                    f"accessors[{accessor_id}].sparse.values.byteOffset",
                ),
                count=sparse_count,
                components=components,
                component_type=component_type,
                label=f"accessors[{accessor_id}].sparse.values",
                honor_stride=False,
            )
            values[sparse_indices] = sparse_values
        normalized = bool(definition.get("normalized", False))
        if normalized:
            values = self._normalize(values, component_type)
        self._decoded_accessor_values += int(values.size)
        if self._decoded_accessor_values > _MAX_TOTAL_ACCESSOR_VALUES:
            raise GltfImportError("Combined decoded accessor data is too large")
        result = (values, definition)
        self._accessor_cache[accessor_id] = result
        return result

    def image(self, image_index: int) -> np.ndarray:
        image_id = _index(image_index, self.images, "texture source")
        cached = self._image_cache.get(image_id)
        if cached is not None:
            return cached
        definition = _object(self.images[image_id], f"images[{image_id}]")
        if definition.get("extensions"):
            raise GltfImportError(f"images[{image_id}] uses unsupported extensions")
        uri = definition.get("uri")
        mime = str(definition.get("mimeType", "")).lower()
        if uri is not None:
            if not isinstance(uri, str):
                raise GltfImportError(f"images[{image_id}].uri must be text")
            data_mime, raw = _decode_data_uri(uri, f"images[{image_id}]")
            if mime and data_mime and mime != data_mime:
                raise GltfImportError(f"images[{image_id}] MIME types disagree")
            mime = mime or data_mime
        else:
            if "bufferView" not in definition or not mime:
                raise GltfImportError(
                    f"images[{image_id}] needs an embedded bufferView and mimeType"
                )
            raw_buffer, start, length, _view = self._view(
                _integer(definition["bufferView"], f"images[{image_id}].bufferView"),
                f"images[{image_id}].bufferView",
            )
            raw = raw_buffer[start : start + length]
        detected_mime = _image_mime_from_magic(raw)
        if mime and mime not in {"image/png", "image/jpeg"}:
            raise GltfImportError(
                f"images[{image_id}] has unsupported MIME type {mime!r}"
            )
        if detected_mime is None:
            raise GltfImportError(
                f"images[{image_id}] is not a supported PNG or JPEG image"
            )
        if mime and mime != detected_mime:
            raise GltfImportError(
                f"images[{image_id}] declared {mime!r} but contains {detected_mime!r}"
            )
        try:
            with Image.open(io.BytesIO(raw)) as source:
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > _MAX_IMAGE_PIXELS:
                    raise GltfImportError(
                        f"images[{image_id}] has unsafe dimensions {width} x {height}"
                    )
                self._decoded_image_pixels += int(width * height)
                if self._decoded_image_pixels > _MAX_TOTAL_IMAGE_PIXELS:
                    raise GltfImportError(
                        "Combined decoded base-colour texture area is too large"
                    )
                source.load()
                has_alpha = "A" in source.getbands() or "transparency" in source.info
                target_mode = "RGBA" if has_alpha else "RGB"
                converted = source if source.mode == target_mode else source.convert(target_mode)
                # ``np.asarray(PIL.Image)`` retains its immutable bytes owner,
                # so the array remains valid after Image.close without a
                # second full-size copy.  This matters for Hi3D's 8K JPEGs.
                pixels = np.asarray(converted, dtype=np.uint8)
                if not pixels.flags.c_contiguous:
                    pixels = np.ascontiguousarray(pixels)
        except GltfImportError:
            raise
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            raise GltfImportError(f"images[{image_id}] cannot be decoded") from exc
        self._image_cache[image_id] = pixels
        return pixels

    def texture(
        self,
        texture_info: Mapping[str, Any],
        texcoords: Mapping[str, Any],
        vertex_count: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        texture_id = _index(texture_info.get("index"), self.textures, "texture.index")
        texture = _object(self.textures[texture_id], f"textures[{texture_id}]")
        extensions = texture.get("extensions")
        if isinstance(extensions, dict) and "KHR_texture_basisu" in extensions:
            raise GltfImportError("KHR_texture_basisu textures are unsupported")
        if texture.get("source") is None:
            raise GltfImportError(f"textures[{texture_id}] has no core image source")
        texcoord_number = _integer(texture_info.get("texCoord", 0), "texture.texCoord")
        offset = np.asarray([0.0, 0.0], dtype=np.float64)
        scale = np.asarray([1.0, 1.0], dtype=np.float64)
        rotation = 0.0
        info_extensions = texture_info.get("extensions")
        if info_extensions is not None:
            info_extensions = _object(info_extensions, "baseColorTexture.extensions")
            unknown = set(info_extensions) - {"KHR_texture_transform"}
            if unknown:
                raise GltfImportError(
                    "Unsupported baseColorTexture extension(s): "
                    + ", ".join(sorted(unknown))
                )
            transform = info_extensions.get("KHR_texture_transform")
            if transform is not None:
                transform = _object(transform, "KHR_texture_transform")
                if "texCoord" in transform:
                    texcoord_number = _integer(
                        transform["texCoord"], "KHR_texture_transform.texCoord"
                    )
                if "offset" in transform:
                    offset = _float_vector(
                        transform["offset"], 2, "KHR_texture_transform.offset"
                    )
                if "scale" in transform:
                    scale = _float_vector(
                        transform["scale"], 2, "KHR_texture_transform.scale"
                    )
                if "rotation" in transform:
                    rotation = _finite_float(
                        transform["rotation"], "KHR_texture_transform.rotation"
                    )
        attribute_name = f"TEXCOORD_{texcoord_number}"
        if attribute_name not in texcoords:
            raise GltfImportError(
                f"baseColorTexture requires missing attribute {attribute_name}"
            )
        uv, definition = self.accessor(
            _integer(texcoords[attribute_name], attribute_name), attribute_name
        )
        if definition.get("type") != "VEC2" or len(uv) != vertex_count:
            raise GltfImportError(f"{attribute_name} must be VEC2 for every vertex")
        component = int(definition["componentType"])
        if component == 5126:
            if bool(definition.get("normalized", False)):
                raise GltfImportError(f"{attribute_name} FLOAT cannot be normalized")
        elif component not in _NORMALIZED_TEXCOORD_COMPONENTS or not bool(
            definition.get("normalized", False)
        ):
            raise GltfImportError(
                f"{attribute_name} must use FLOAT or normalized unsigned integers"
            )
        uv = np.asarray(uv, dtype=np.float64)
        if not np.isfinite(uv).all():
            raise GltfImportError(f"{attribute_name} contains NaN or infinity")
        cosine = math.cos(rotation)
        sine = math.sin(rotation)
        with np.errstate(over="ignore", invalid="ignore"):
            scaled = uv * scale
            transformed = np.empty_like(scaled)
            transformed[:, 0] = (
                offset[0] + cosine * scaled[:, 0] - sine * scaled[:, 1]
            )
            transformed[:, 1] = (
                offset[1] + sine * scaled[:, 0] + cosine * scaled[:, 1]
            )
        if not np.isfinite(transformed).all():
            raise GltfImportError(
                "Texture coordinates overflow after KHR_texture_transform"
            )
        sampler_id = texture.get("sampler")
        sampler = (
            {}
            if sampler_id is None
            else _object(
                self.samplers[_index(sampler_id, self.samplers, f"textures[{texture_id}].sampler")],
                f"samplers[{sampler_id}]",
            )
        )
        wrap_s = _sampler_enum(sampler.get("wrapS", 10497), "wrapS", {33071, 33648, 10497})
        wrap_t = _sampler_enum(sampler.get("wrapT", 10497), "wrapT", {33071, 33648, 10497})
        mag_filter = sampler.get("magFilter")
        min_filter = sampler.get("minFilter")
        if mag_filter is not None:
            mag_filter = _sampler_enum(mag_filter, "magFilter", {9728, 9729})
        if min_filter is not None:
            min_filter = _sampler_enum(
                min_filter, "minFilter", {9728, 9729, 9984, 9985, 9986, 9987}
            )
        nearest = (
            mag_filter == 9728
            if mag_filter is not None
            else min_filter in {9728, 9984, 9986}
        )
        image = self.image(_integer(texture["source"], f"textures[{texture_id}].source"))
        return _sample_image_linear(image, transformed, wrap_s, wrap_t, nearest)


def _sampler_enum(value: Any, label: str, allowed: set[int]) -> int:
    result = _integer(value, f"sampler.{label}")
    if result not in allowed:
        raise GltfImportError(f"sampler.{label} has invalid value {result}")
    return result


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GltfImportError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise GltfImportError(f"{label} must be finite")
    return result


def _float_vector(value: Any, length: int, label: str) -> np.ndarray:
    if not isinstance(value, list) or len(value) != length:
        raise GltfImportError(f"{label} must contain {length} numbers")
    return np.asarray(
        [_finite_float(item, f"{label}[{index}]") for index, item in enumerate(value)],
        dtype=np.float64,
    )


def _wrap_indices(indices: np.ndarray, size: int, mode: int) -> np.ndarray:
    if mode == 33071:
        return np.clip(indices, 0, size - 1)
    if mode == 10497:
        return np.mod(indices, size)
    period = size * 2
    mirrored = np.mod(indices, period)
    return np.where(mirrored < size, mirrored, period - 1 - mirrored)


def _sample_image_linear_chunk(
    image: np.ndarray,
    uv: np.ndarray,
    wrap_s: int,
    wrap_t: int,
    nearest: bool,
) -> tuple[np.ndarray, np.ndarray]:
    height, width = image.shape[:2]
    if nearest:
        x = _wrap_indices(np.floor(uv[:, 0] * width).astype(np.int64), width, wrap_s)
        y = _wrap_indices(np.floor(uv[:, 1] * height).astype(np.int64), height, wrap_t)
        sampled = image[y, x].astype(np.float64) / 255.0
        alpha = (
            sampled[:, 3]
            if sampled.shape[1] == 4
            else np.ones(len(sampled), dtype=np.float64)
        )
        return _srgb_to_linear(sampled[:, :3]), alpha
    x = uv[:, 0] * width - 0.5
    y = uv[:, 1] * height - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    tx = x - x0
    ty = y - y0
    x0w = _wrap_indices(x0, width, wrap_s)
    x1w = _wrap_indices(x0 + 1, width, wrap_s)
    y0w = _wrap_indices(y0, height, wrap_t)
    y1w = _wrap_indices(y0 + 1, height, wrap_t)
    weights = (
        (1.0 - tx) * (1.0 - ty),
        tx * (1.0 - ty),
        (1.0 - tx) * ty,
        tx * ty,
    )
    coordinates = ((y0w, x0w), (y0w, x1w), (y1w, x0w), (y1w, x1w))
    # Filtering must happen after decoding sRGB texels to linear light.  Doing
    # this only for the four samples used by each mesh vertex avoids a second
    # float copy of an 8K texture.
    rgb_linear = np.zeros((len(uv), 3), dtype=np.float64)
    alpha = np.zeros(len(uv), dtype=np.float64)
    has_alpha = image.shape[2] == 4
    for weight, (sample_y, sample_x) in zip(weights, coordinates, strict=True):
        sampled = image[sample_y, sample_x]
        encoded_rgb = sampled[:, :3].astype(np.float64) / 255.0
        rgb_linear += _srgb_to_linear(encoded_rgb) * weight[:, None]
        if has_alpha:
            alpha += sampled[:, 3].astype(np.float64) / 255.0 * weight
    if not has_alpha:
        alpha.fill(1.0)
    return rgb_linear, alpha


def _sample_image_linear(
    image: np.ndarray,
    uv: np.ndarray,
    wrap_s: int,
    wrap_t: int,
    nearest: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample large textures with a fixed temporary-memory ceiling."""

    uv = np.asarray(uv, dtype=np.float64)
    rgb_linear = np.empty((len(uv), 3), dtype=np.float64)
    alpha = np.empty(len(uv), dtype=np.float64)
    for start in range(0, len(uv), _TEXTURE_SAMPLE_CHUNK_VERTICES):
        stop = min(start + _TEXTURE_SAMPLE_CHUNK_VERTICES, len(uv))
        chunk_rgb, chunk_alpha = _sample_image_linear_chunk(
            image,
            uv[start:stop],
            wrap_s,
            wrap_t,
            nearest,
        )
        rgb_linear[start:stop] = chunk_rgb
        alpha[start:stop] = chunk_alpha
    return rgb_linear, alpha


def _srgb_to_linear(values: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0)
    return np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )


def _linear_to_srgb(values: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0)
    return np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * np.power(values, 1.0 / 2.4) - 0.055,
    )


def _local_matrix(node: Mapping[str, Any], node_id: int) -> np.ndarray:
    if "matrix" in node:
        if any(key in node for key in ("translation", "rotation", "scale")):
            raise GltfImportError(
                f"nodes[{node_id}] cannot define matrix together with TRS"
            )
        values = _float_vector(node["matrix"], 16, f"nodes[{node_id}].matrix")
        matrix = values.reshape((4, 4), order="F")
    else:
        translation = _float_vector(
            node.get("translation", [0.0, 0.0, 0.0]),
            3,
            f"nodes[{node_id}].translation",
        )
        scale = _float_vector(
            node.get("scale", [1.0, 1.0, 1.0]),
            3,
            f"nodes[{node_id}].scale",
        )
        quaternion = _float_vector(
            node.get("rotation", [0.0, 0.0, 0.0, 1.0]),
            4,
            f"nodes[{node_id}].rotation",
        )
        norm = float(np.linalg.norm(quaternion))
        if norm < 1e-12:
            raise GltfImportError(f"nodes[{node_id}].rotation is a zero quaternion")
        x, y, z, w = quaternion / norm
        rotation = np.asarray(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ],
            dtype=np.float64,
        )
        matrix = np.eye(4, dtype=np.float64)
        matrix[:3, :3] = rotation @ np.diag(scale)
        matrix[:3, 3] = translation
    if not np.isfinite(matrix).all() or not np.allclose(
        matrix[3], [0.0, 0.0, 0.0, 1.0], rtol=0.0, atol=1e-9
    ):
        raise GltfImportError(f"nodes[{node_id}] has a non-affine transform")
    determinant = float(np.linalg.det(matrix[:3, :3]))
    if not math.isfinite(determinant) or abs(determinant) < 1e-15:
        raise GltfImportError(f"nodes[{node_id}] has a singular transform")
    return matrix


def _triangles(indices: np.ndarray, mode: int, label: str) -> np.ndarray:
    indices = np.asarray(indices).reshape(-1)
    if len(indices) and (
        int(indices.min()) < 0
        or int(indices.max()) > int(np.iinfo(np.int32).max)
    ):
        raise GltfImportError(f"{label} indices exceed the supported range")
    indices = indices.astype(np.int32, copy=False)
    if mode == 4:
        if len(indices) % 3:
            raise GltfImportError(f"{label} TRIANGLES index count is not divisible by 3")
        return indices.reshape((-1, 3))
    if mode == 5:
        if len(indices) < 3:
            return np.empty((0, 3), dtype=np.int32)
        output = np.empty((len(indices) - 2, 3), dtype=np.int32)
        output[:, 0] = indices[:-2]
        output[:, 1] = indices[1:-1]
        output[:, 2] = indices[2:]
        odd = np.arange(len(output)) % 2 == 1
        output[odd, 0], output[odd, 1] = (
            output[odd, 1].copy(),
            output[odd, 0].copy(),
        )
        return output
    if mode == 6:
        if len(indices) < 3:
            return np.empty((0, 3), dtype=np.int32)
        return np.column_stack(
            (
                np.full(len(indices) - 2, indices[0], dtype=np.int32),
                indices[1:-1],
                indices[2:],
            )
        ).astype(np.int32, copy=False)
    raise GltfImportError(
        f"{label} uses non-triangle primitive mode {mode}; only 4, 5, and 6 are supported"
    )


def _material_colour(
    reader: _Reader,
    primitive: Mapping[str, Any],
    attributes: Mapping[str, Any],
    vertex_count: int,
    *,
    apply_vertex_colour: bool = True,
) -> tuple[np.ndarray, bool, bool]:
    rgba_linear = np.ones((vertex_count, 4), dtype=np.float64)
    used_vertex_colour = False
    used_texture = False
    if "COLOR_0" in attributes:
        colours, definition = reader.accessor(
            _integer(attributes["COLOR_0"], "COLOR_0"), "COLOR_0"
        )
        if definition.get("type") not in {"VEC3", "VEC4"} or len(colours) != vertex_count:
            raise GltfImportError("COLOR_0 must be VEC3/VEC4 for every vertex")
        component = int(definition["componentType"])
        if component == 5126:
            if bool(definition.get("normalized", False)):
                raise GltfImportError("FLOAT COLOR_0 cannot be normalized")
        elif component not in _NORMALIZED_COLOR_COMPONENTS or not bool(
            definition.get("normalized", False)
        ):
            raise GltfImportError(
                "COLOR_0 must use FLOAT or normalized unsigned byte/short"
            )
        colours = np.asarray(colours, dtype=np.float64)
        if not np.isfinite(colours).all() or np.any(colours < -1e-6) or np.any(colours > 1.000001):
            raise GltfImportError("COLOR_0 values must be finite and within 0..1")
        if apply_vertex_colour:
            rgba_linear[:, : colours.shape[1]] *= np.clip(colours, 0.0, 1.0)
            used_vertex_colour = True
    material_value = primitive.get("material")
    material: dict[str, Any] = {}
    if material_value is not None:
        material_id = _index(material_value, reader.materials, "primitive.material")
        material = _object(reader.materials[material_id], f"materials[{material_id}]")
        extensions = material.get("extensions")
        if isinstance(extensions, dict) and "KHR_materials_pbrSpecularGlossiness" in extensions:
            raise GltfImportError("KHR_materials_pbrSpecularGlossiness colour is unsupported")
    pbr = _object(material.get("pbrMetallicRoughness", {}), "pbrMetallicRoughness")
    if pbr.get("metallicRoughnessTexture") is not None:
        reader.ignored_appearance_maps.add("metallic-roughness")
    for material_key, label in (
        ("normalTexture", "normal"),
        ("occlusionTexture", "occlusion"),
        ("emissiveTexture", "emissive"),
    ):
        if material.get(material_key) is not None:
            reader.ignored_appearance_maps.add(label)
    emissive_factor = material.get("emissiveFactor")
    if emissive_factor is not None and any(
        abs(value) > 1e-12
        for value in _float_vector(emissive_factor, 3, "emissiveFactor")
    ):
        reader.ignored_appearance_maps.add("emissive")
    factor = _float_vector(
        pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0]),
        4,
        "baseColorFactor",
    )
    if np.any(factor < -1e-6) or np.any(factor > 1.000001):
        raise GltfImportError("baseColorFactor must be within 0..1")
    rgba_linear *= np.clip(factor, 0.0, 1.0)
    texture_info = pbr.get("baseColorTexture")
    if texture_info is not None:
        texture_info = _object(texture_info, "baseColorTexture")
        rgb_linear, alpha = reader.texture(texture_info, attributes, vertex_count)
        rgba_linear[:, :3] *= rgb_linear
        rgba_linear[:, 3] *= alpha
        used_texture = True
    return rgba_linear, used_vertex_colour, used_texture


def _clean_name(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.replace("\0", "").split())
    return cleaned[:160] or fallback


def _unique_name(name: str, counts: dict[str, int]) -> str:
    current = counts.get(name, 0) + 1
    counts[name] = current
    return name if current == 1 else f"{name} ({current})"


def _scene_roots(
    document: Mapping[str, Any], nodes: Sequence[Any], warnings: list[str]
) -> tuple[list[int], int | None]:
    scenes = _array(document.get("scenes", []), "scenes")
    if scenes:
        scene_value = document.get("scene")
        if scene_value is None:
            scene_id = 0
            warnings.append("既定scene指定がないためscene 0を読み込みました")
        else:
            scene_id = _index(scene_value, scenes, "scene")
        scene = _object(scenes[scene_id], f"scenes[{scene_id}]")
        roots = [
            _index(item, nodes, f"scenes[{scene_id}].nodes")
            for item in _array(scene.get("nodes", []), f"scenes[{scene_id}].nodes")
        ]
        if len(scenes) > 1:
            warnings.append(
                f"glTFの既定scene {scene_id}だけを読み込みました（全{len(scenes)} scene）"
            )
        return roots, scene_id
    children: set[int] = set()
    for node_id, raw_node in enumerate(nodes):
        node = _object(raw_node, f"nodes[{node_id}]")
        for child in _array(node.get("children", []), f"nodes[{node_id}].children"):
            children.add(_index(child, nodes, f"nodes[{node_id}].children"))
    roots = [index for index in range(len(nodes)) if index not in children]
    if nodes and not roots:
        raise GltfImportError("glTF node graph has no root (possible cycle)")
    return roots, None


def _primitive_triangle_count(count: int, mode: int, label: str) -> int:
    if mode == 4:
        if count % 3:
            raise GltfImportError(
                f"{label} TRIANGLES index count is not divisible by 3"
            )
        return count // 3
    if mode in {5, 6}:
        return max(0, count - 2)
    raise GltfImportError(
        f"{label} uses non-triangle primitive mode {mode}; "
        "only 4, 5, and 6 are supported"
    )


def _plan_static_scene(
    document: Mapping[str, Any],
    warnings: list[str],
) -> tuple[
    GltfImportPlan,
    list[Any],
    list[Any],
    list[int],
    int | None,
]:
    """Validate the selected node graph and count work from JSON metadata."""

    nodes = _array(document.get("nodes", []), "nodes")
    meshes = _array(document.get("meshes", []), "meshes")
    accessors = _array(document.get("accessors", []), "accessors")
    if not nodes or not meshes:
        raise GltfImportError("glTF contains no scene nodes or meshes")
    primitive_total = sum(
        len(
            _array(
                _object(mesh, f"meshes[{mesh_id}]").get("primitives", []),
                f"meshes[{mesh_id}].primitives",
            )
        )
        for mesh_id, mesh in enumerate(meshes)
    )
    if len(nodes) > _MAX_NODES or primitive_total > _MAX_PRIMITIVES:
        raise GltfImportError("glTF has too many nodes or mesh primitives")
    roots, scene_id = _scene_roots(document, nodes, warnings)
    if not roots:
        raise GltfImportError("The selected glTF scene has no root nodes")

    vertex_upper_bound = 0
    triangle_count = 0
    mesh_node_count = 0
    primitive_instance_count = 0
    primitive_modes: list[int] = []
    seen_nodes: set[int] = set()
    stack: list[tuple[int, int, frozenset[int], np.ndarray]] = [
        (root_id, 1, frozenset(), np.eye(4))
        for root_id in reversed(roots)
    ]
    while stack:
        node_id, depth, ancestors, parent_matrix = stack.pop()
        if node_id in ancestors:
            raise GltfImportError(f"glTF node cycle reaches nodes[{node_id}]")
        if depth > _MAX_NODE_DEPTH:
            raise GltfImportError("glTF node hierarchy is too deep")
        if node_id in seen_nodes:
            raise GltfImportError(
                f"nodes[{node_id}] is referenced more than once in the selected scene"
            )
        seen_nodes.add(node_id)
        node = _object(nodes[node_id], f"nodes[{node_id}]")
        node_extensions = node.get("extensions")
        if (
            isinstance(node_extensions, dict)
            and "EXT_mesh_gpu_instancing" in node_extensions
        ):
            raise GltfImportError("EXT_mesh_gpu_instancing nodes are unsupported")
        if "skin" in node:
            raise GltfImportError(f"nodes[{node_id}] uses unsupported skinning")
        if "weights" in node:
            raise GltfImportError(
                f"nodes[{node_id}] uses unsupported morph weights"
            )
        with np.errstate(over="ignore", invalid="ignore"):
            world = parent_matrix @ _local_matrix(node, node_id)
        if not np.isfinite(world).all() or not np.allclose(
            world[3], [0.0, 0.0, 0.0, 1.0], rtol=0.0, atol=1e-9
        ):
            raise GltfImportError(
                f"nodes[{node_id}] world transform overflows or is non-affine"
            )
        world_determinant = float(np.linalg.det(world[:3, :3]))
        if (
            not math.isfinite(world_determinant)
            or abs(world_determinant) < 1e-15
        ):
            raise GltfImportError(f"nodes[{node_id}] world transform is singular")
        mesh_value = node.get("mesh")
        if mesh_value is not None:
            mesh_node_count += 1
            mesh_id = _index(mesh_value, meshes, f"nodes[{node_id}].mesh")
            mesh = _object(meshes[mesh_id], f"meshes[{mesh_id}]")
            if mesh.get("weights") is not None:
                raise GltfImportError(
                    f"meshes[{mesh_id}] uses unsupported morph weights"
                )
            primitives = _array(
                mesh.get("primitives", []), f"meshes[{mesh_id}].primitives"
            )
            if not primitives:
                raise GltfImportError(f"meshes[{mesh_id}] has no primitives")
            for primitive_id, raw_primitive in enumerate(primitives):
                primitive_instance_count += 1
                if primitive_instance_count > _MAX_PRIMITIVES:
                    raise GltfImportError(
                        "The selected glTF scene instantiates too many mesh primitives"
                    )
                primitive = _object(
                    raw_primitive,
                    f"meshes[{mesh_id}].primitives[{primitive_id}]",
                )
                extensions = primitive.get("extensions")
                if (
                    isinstance(extensions, dict)
                    and "KHR_draco_mesh_compression" in extensions
                ):
                    raise GltfImportError(
                        "Draco (KHR_draco_mesh_compression) primitives are unsupported"
                    )
                if primitive.get("targets"):
                    raise GltfImportError("Morph target primitives are unsupported")
                attributes = _object(
                    primitive.get("attributes"),
                    f"meshes[{mesh_id}].primitives[{primitive_id}].attributes",
                )
                if "POSITION" not in attributes:
                    raise GltfImportError("Every mesh primitive needs POSITION")
                if "JOINTS_0" in attributes or "WEIGHTS_0" in attributes:
                    raise GltfImportError("Skinned vertex attributes are unsupported")
                position_id = _index(
                    _integer(attributes["POSITION"], "POSITION"),
                    accessors,
                    "POSITION",
                )
                position_def = _object(
                    accessors[position_id], f"accessors[{position_id}]"
                )
                if (
                    position_def.get("type") != "VEC3"
                    or int(position_def.get("componentType", -1)) != 5126
                    or bool(position_def.get("normalized", False))
                ):
                    raise GltfImportError(
                        "POSITION must be non-normalized FLOAT VEC3"
                    )
                position_count = _integer(
                    position_def.get("count"),
                    f"accessors[{position_id}].count",
                )
                index_value = primitive.get("indices")
                if index_value is None:
                    index_count = position_count
                else:
                    index_id = _index(
                        _integer(index_value, "primitive.indices"),
                        accessors,
                        "primitive.indices",
                    )
                    index_def = _object(
                        accessors[index_id], f"accessors[{index_id}]"
                    )
                    if (
                        index_def.get("type") != "SCALAR"
                        or int(index_def.get("componentType", -1))
                        not in _UNSIGNED_INDEX_COMPONENTS
                        or bool(index_def.get("normalized", False))
                    ):
                        raise GltfImportError(
                            "indices must be unsigned non-normalized SCALAR"
                        )
                    index_count = _integer(
                        index_def.get("count"),
                        f"accessors[{index_id}].count",
                    )
                mode = _integer(primitive.get("mode", 4), "primitive.mode")
                vertex_upper_bound += position_count
                triangle_count += _primitive_triangle_count(
                    index_count,
                    mode,
                    f"meshes[{mesh_id}].primitives[{primitive_id}]",
                )
                primitive_modes.append(mode)
        children = _array(node.get("children", []), f"nodes[{node_id}].children")
        next_ancestors = ancestors | {node_id}
        for child in reversed(children):
            child_id = _index(child, nodes, f"nodes[{node_id}].children")
            stack.append((child_id, depth + 1, next_ancestors, world))

    if not mesh_node_count or not primitive_instance_count:
        raise GltfImportError("The selected glTF scene contains no triangle mesh")
    return (
        GltfImportPlan(
            vertex_count_upper_bound=int(vertex_upper_bound),
            triangle_count=int(triangle_count),
            mesh_node_count=int(mesh_node_count),
            primitive_instance_count=int(primitive_instance_count),
            primitive_modes=tuple(primitive_modes),
        ),
        nodes,
        meshes,
        roots,
        scene_id,
    )


def inspect_gltf_asset(path: Path) -> GltfImportPlan:
    """Inspect selected-scene workload without reading GLB BIN/image payloads."""

    path = Path(path)
    if not path.is_file():
        raise GltfImportError(f"GLB/glTF file was not found: {path}")
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise GltfImportError(
            "GLB/glTF exceeds the 512 MiB safe import limit. "
            "Reduce the mesh or texture resolution before importing"
        )
    document = _read_document_json_only(path)
    warnings = _validate_document(document)
    plan, _nodes, _meshes, _roots, _scene_id = _plan_static_scene(
        document, warnings
    )
    return plan


def _selected_mesh_ids(
    nodes: Sequence[Any], meshes: Sequence[Any], roots: Sequence[int]
) -> list[int]:
    """Return distinct mesh definitions reachable from the selected scene."""

    selected: list[int] = []
    seen_meshes: set[int] = set()
    seen_nodes: set[int] = set()
    stack = list(reversed(roots))
    while stack:
        node_id = stack.pop()
        if node_id in seen_nodes:
            # The main traversal reports cycles and multiply-referenced nodes.
            # Avoid making an appearance-policy decision on an invalid graph.
            continue
        seen_nodes.add(node_id)
        node = _object(nodes[node_id], f"nodes[{node_id}]")
        mesh_value = node.get("mesh")
        if mesh_value is not None:
            mesh_id = _index(mesh_value, meshes, f"nodes[{node_id}].mesh")
            if mesh_id not in seen_meshes:
                seen_meshes.add(mesh_id)
                selected.append(mesh_id)
        children = _array(node.get("children", []), f"nodes[{node_id}].children")
        for child in reversed(children):
            stack.append(_index(child, nodes, f"nodes[{node_id}].children"))
    return selected


def _has_exploded_multipart_provenance(
    reader: _Reader,
    nodes: Sequence[Any],
    meshes: Sequence[Any],
    roots: Sequence[int],
) -> bool:
    """Return whether the scene carries the known part-explosion metadata.

    A shared texture plus nearly uniform per-part ``COLOR_0`` is valid authored
    glTF and is not, by itself, proof that the colours are disposable IDs.  The
    compatible multipart exporter also records every printable part beneath a
    ``world`` node with explicit original-position and explosion-direction
    vectors.  Auto suppression is restricted to that provenance; ordinary
    glTF keeps the standards-defined colour multiplication.
    """

    asset = _object(reader.document.get("asset"), "asset")
    generator = asset.get("generator")
    if not isinstance(generator, str) or not generator.startswith(
        "THREE.GLTFExporter "
    ):
        return False

    mesh_nodes: list[tuple[int, int]] = []
    reachable: list[int] = []
    seen_nodes: set[int] = set()
    stack = list(reversed(roots))
    while stack:
        node_id = stack.pop()
        if node_id in seen_nodes:
            return False
        seen_nodes.add(node_id)
        reachable.append(node_id)
        node = _object(nodes[node_id], f"nodes[{node_id}]")
        mesh_value = node.get("mesh")
        if mesh_value is not None:
            mesh_nodes.append(
                (node_id, _index(mesh_value, meshes, f"nodes[{node_id}].mesh"))
            )
        children = _array(node.get("children", []), f"nodes[{node_id}].children")
        for child in reversed(children):
            stack.append(_index(child, nodes, f"nodes[{node_id}].children"))

    if len(mesh_nodes) < 2 or len({mesh_id for _, mesh_id in mesh_nodes}) != len(
        mesh_nodes
    ):
        return False

    mesh_node_ids = {node_id for node_id, _ in mesh_nodes}
    world_parent_found = False
    for node_id in reachable:
        node = _object(nodes[node_id], f"nodes[{node_id}]")
        extras_value = node.get("extras")
        extras = extras_value if isinstance(extras_value, dict) else {}
        children = {
            _index(child, nodes, f"nodes[{node_id}].children")
            for child in _array(
                node.get("children", []), f"nodes[{node_id}].children"
            )
        }
        if (
            node.get("name") == "world"
            and extras.get("name") == "world"
            and mesh_node_ids.issubset(children)
        ):
            world_parent_found = True
    if not world_parent_found:
        return False

    for node_id, _mesh_id in mesh_nodes:
        node = _object(nodes[node_id], f"nodes[{node_id}]")
        name = node.get("name")
        extras_value = node.get("extras")
        if not isinstance(extras_value, dict):
            return False
        extras = extras_value
        if not isinstance(name, str) or not name or extras.get("name") != name:
            return False
        for key in ("_explodeOrigLocalPos", "_explodeWorldDir"):
            vector_value = extras.get(key)
            if not isinstance(vector_value, dict):
                return False
            vector = vector_value
            if set(vector) != {"x", "y", "z"}:
                return False
            values: list[float] = []
            for axis in ("x", "y", "z"):
                value = vector[axis]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return False
                values.append(float(value))
            if not np.isfinite(values).all():
                return False
    return True


def _auto_segmentation_vertex_colours(
    reader: _Reader,
    nodes: Sequence[Any],
    meshes: Sequence[Any],
    roots: Sequence[int],
) -> tuple[set[tuple[int, int]], int | None]:
    """Detect a narrow signature for categorical part-display ``COLOR_0``.

    There is no glTF semantic which marks a vertex colour as a segmentation
    overlay, so auto mode must fail closed.  A decision is made only when every
    colour-bearing primitive in the selected scene has all of these signals:

    * known multipart part-explosion provenance on every printable node;
    * its own material with an unchanged white baseColorFactor;
    * the same baseColorTexture declaration as the other primitives;
    * normalized unsigned-byte colour IDs with opaque alpha;
    * exactly one dominant chromatic ID plus a small white sentinel minority;
    * a distinct dominant ID and material for every primitive; and
    * the dominant IDs are exactly the exporter category-palette prefix for
      the detected part count.

    Anything else retains the glTF-standard multiplication path.
    """

    if not _has_exploded_multipart_provenance(reader, nodes, meshes, roots):
        return set(), None

    candidates: list[
        tuple[tuple[int, int], int, int, dict[str, Any], tuple[int, int, int]]
    ] = []
    selected_primitive_count = 0
    for mesh_id in _selected_mesh_ids(nodes, meshes, roots):
        mesh = _object(meshes[mesh_id], f"meshes[{mesh_id}]")
        primitives = _array(
            mesh.get("primitives", []), f"meshes[{mesh_id}].primitives"
        )
        for primitive_id, raw_primitive in enumerate(primitives):
            selected_primitive_count += 1
            primitive = _object(
                raw_primitive, f"meshes[{mesh_id}].primitives[{primitive_id}]"
            )
            attributes = _object(
                primitive.get("attributes"),
                f"meshes[{mesh_id}].primitives[{primitive_id}].attributes",
            )
            if "COLOR_0" not in attributes:
                return set(), None

            material_value = primitive.get("material")
            if material_value is None:
                return set(), None
            material_id = _index(
                material_value,
                reader.materials,
                f"meshes[{mesh_id}].primitives[{primitive_id}].material",
            )
            material = _object(
                reader.materials[material_id], f"materials[{material_id}]"
            )
            pbr = _object(
                material.get("pbrMetallicRoughness", {}),
                f"materials[{material_id}].pbrMetallicRoughness",
            )
            factor = _float_vector(
                pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0]),
                4,
                f"materials[{material_id}].baseColorFactor",
            )
            if not np.allclose(factor, 1.0, rtol=0.0, atol=1e-9):
                return set(), None
            texture_value = pbr.get("baseColorTexture")
            if texture_value is None:
                return set(), None
            texture_info = _object(
                texture_value, f"materials[{material_id}].baseColorTexture"
            )
            texture_id = _index(
                texture_info.get("index"),
                reader.textures,
                f"materials[{material_id}].baseColorTexture.index",
            )

            colours, definition = reader.accessor(
                _integer(attributes["COLOR_0"], "COLOR_0"), "COLOR_0"
            )
            if (
                definition.get("type") not in {"VEC3", "VEC4"}
                or int(definition.get("componentType", -1)) != 5121
                or not bool(definition.get("normalized", False))
                or definition.get("sparse") is not None
                or not len(colours)
            ):
                return set(), None
            encoded = np.rint(np.clip(np.asarray(colours), 0.0, 1.0) * 255.0).astype(
                np.uint8
            )
            if encoded.shape[1] == 4 and not np.all(encoded[:, 3] == 255):
                return set(), None
            unique, counts = np.unique(encoded[:, :3], axis=0, return_counts=True)
            if len(unique) != 2:
                return set(), None
            dominant_index = int(np.argmax(counts))
            dominant = unique[dominant_index]
            minority = unique[1 - dominant_index]
            if (
                float(counts[dominant_index]) / len(encoded)
                < _AUTO_SEGMENTATION_MIN_DOMINANT_SHARE
                or np.array_equal(dominant, [255, 255, 255])
                or not np.array_equal(minority, [255, 255, 255])
                or int(np.max(dominant)) - int(np.min(dominant))
                < _AUTO_SEGMENTATION_MIN_CHANNEL_RANGE
            ):
                return set(), None
            candidates.append(
                (
                    (mesh_id, primitive_id),
                    texture_id,
                    material_id,
                    dict(texture_info),
                    tuple(int(value) for value in dominant),
                )
            )

    if len(candidates) < 2 or len(candidates) != selected_primitive_count:
        return set(), None
    texture_ids = {item[1] for item in candidates}
    material_ids = {item[2] for item in candidates}
    dominant_ids = {item[4] for item in candidates}
    expected_dominant_ids = set(
        _EXPLODED_PART_ID_PALETTE[: len(candidates)]
    )
    first_texture_info = candidates[0][3]
    if (
        len(candidates) > len(_EXPLODED_PART_ID_PALETTE)
        or len(texture_ids) != 1
        or len(material_ids) != len(candidates)
        or len(dominant_ids) != len(candidates)
        or dominant_ids != expected_dominant_ids
        or any(item[3] != first_texture_info for item in candidates[1:])
    ):
        return set(), None
    return {item[0] for item in candidates}, next(iter(texture_ids))


def load_gltf_asset(
    path: Path,
    progress: ProgressCallback | None = None,
    *,
    vertex_color_policy: VertexColorPolicy = "auto",
    allow_large_reduced_source: bool = False,
    expected_plan: GltfImportPlan | None = None,
) -> ObjAsset:
    """Load a static GLB/glTF scene and bake its base colour to ``ObjAsset``.

    ``.gltf`` is intentionally limited to data URIs.  This keeps an imported
    document self-contained and prevents a model from reading arbitrary files
    next to it.  ``vertex_color_policy='multiply'`` always follows the glTF
    colour equation, while ``'ignore'`` always omits ``COLOR_0``.  The default
    ``'auto'`` only omits it for the conservative multipart segmentation
    signature documented by :func:`_auto_segmentation_vertex_colours`.

    ``allow_large_reduced_source`` explicitly admits a supported source above
    the normal face limit and within the configured reduced-source limit.  The
    returned asset records a hard 450,000-face working-model ceiling which
    ``prepare_geometry`` enforces on every initial or repeated processing pass.
    """

    if (
        not isinstance(vertex_color_policy, str)
        or vertex_color_policy not in _VERTEX_COLOR_POLICIES
    ):
        raise ValueError(
            "vertex_color_policy must be 'auto', 'multiply', or 'ignore'"
        )
    if not isinstance(allow_large_reduced_source, bool):
        raise ValueError("allow_large_reduced_source must be a boolean")
    if expected_plan is not None and not isinstance(expected_plan, GltfImportPlan):
        raise ValueError("expected_plan must be a GltfImportPlan or None")
    path = Path(path)
    if not path.is_file():
        raise GltfImportError(f"GLB/glTF file was not found: {path}")
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise GltfImportError(
            "GLB/glTF exceeds the 512 MiB safe import limit. "
            "Reduce the Hi3D mesh or texture resolution before importing"
        )
    _emit(progress, "scan", 0.0, "GLB/glTF構造を確認しています")
    preflight_document = _read_document_json_only(path)
    preflight_warnings = _validate_document(preflight_document)
    plan, _nodes, _meshes, _roots, _scene_id = _plan_static_scene(
        preflight_document, preflight_warnings
    )
    if expected_plan is not None and plan != expected_plan:
        raise GltfImportError(
            "GLB/glTF changed after the large-model confirmation. Re-open the file"
        )
    if plan.vertex_count_upper_bound > _MAX_IMPORTED_VERTICES:
        raise GltfImportError(
            "選択sceneの頂点数が安全上限を超えています: "
            f"{plan.vertex_count_upper_bound:,} / {_MAX_IMPORTED_VERTICES:,}。"
            "元モデルのメッシュ密度を下げてください"
        )
    if plan.requires_reduced_mode and not plan.supports_reduced_mode:
        raise GltfImportError(
            "この大規模GLBは安全な縮約読込の条件を満たしません: "
            f"{plan.triangle_count:,} 三角形 / "
            f"{plan.vertex_count_upper_bound:,} 頂点。"
            f"{_MAX_REDUCED_SOURCE_FACES:,}面以下の静的TRIANGLESへ変換してください"
        )
    if plan.requires_reduced_mode and not allow_large_reduced_source:
        raise GltfImportError(
            "選択sceneは大規模モデルです: "
            f"{plan.triangle_count:,} 三角形（通常上限 "
            f"{_MAX_IMPORTED_FACES:,}）。面数調整を有効にし、"
            f"{LARGE_GLTF_REDUCTION_TARGET_FACES:,} 面以下の作業用モデルとして"
            "開いてください"
        )
    face_limit = (
        _MAX_REDUCED_SOURCE_FACES
        if allow_large_reduced_source
        else _MAX_IMPORTED_FACES
    )
    _emit(
        progress,
        "scan",
        0.05,
        f"GLB/glTF事前確認: {plan.vertex_count_upper_bound:,}頂点 / "
        f"{plan.triangle_count:,}三角形",
    )
    # Only after the JSON-only workload admission succeeds do we allocate the
    # GLB BIN payload.  Re-plan the fully read document and compare the frozen
    # estimate so a file replacement between the two reads fails closed.
    document, glb_binary, source_sha256, source_file_size = _read_document(path)
    warnings = _validate_document(document)
    full_plan, nodes, meshes, roots, scene_id = _plan_static_scene(
        document, warnings
    )
    if full_plan != plan:
        raise GltfImportError(
            "GLB/glTF changed while it was being inspected. Re-open the file"
        )
    if plan.requires_reduced_mode:
        warnings.append(
            f"大規模GLB {plan.triangle_count:,} 面を、面数調整を有効にした"
            "作業用モデルとして読み込みました。閉立体化では元形状の"
            "同一座標継ぎ目を先に検証してから面数を調整します"
        )
    reader = _Reader(document, glb_binary, warnings)
    auto_ignored_colours: set[tuple[int, int]] = set()
    auto_shared_texture: int | None = None
    compatible_exploded_multipart = _has_exploded_multipart_provenance(
        reader, nodes, meshes, roots
    )
    if vertex_color_policy == "auto":
        auto_ignored_colours, auto_shared_texture = (
            _auto_segmentation_vertex_colours(reader, nodes, meshes, roots)
        )

    vertices_parts: list[np.ndarray] = []
    colours_parts: list[np.ndarray] = []
    face_parts: list[np.ndarray] = []
    face_part_ids_parts: list[np.ndarray] = []
    part_names: list[str] = []
    part_keys: list[str] = []
    part_face_counts: list[int] = []
    part_vertex_counts: list[int] = []
    name_counts: dict[str, int] = {}
    seen_nodes: set[int] = set()
    used_textures = False
    used_vertex_colours = False
    suppressed_vertex_colours = 0
    discarded_alpha = False
    primitive_count = 0
    dropped_degenerate = 0
    vertex_offset = 0

    stack: list[tuple[int, np.ndarray, tuple[int, ...], frozenset[int]]] = []
    for root_position, root_id in reversed(list(enumerate(roots))):
        stack.append((root_id, np.eye(4), (root_position,), frozenset()))
    processed_nodes = 0
    while stack:
        node_id, parent_matrix, traversal_path, ancestors = stack.pop()
        if node_id in ancestors:
            raise GltfImportError(f"glTF node cycle reaches nodes[{node_id}]")
        if len(traversal_path) > _MAX_NODE_DEPTH:
            raise GltfImportError("glTF node hierarchy is too deep")
        if node_id in seen_nodes:
            raise GltfImportError(
                f"nodes[{node_id}] is referenced more than once in the selected scene"
            )
        seen_nodes.add(node_id)
        node = _object(nodes[node_id], f"nodes[{node_id}]")
        node_extensions = node.get("extensions")
        if (
            isinstance(node_extensions, dict)
            and "EXT_mesh_gpu_instancing" in node_extensions
        ):
            raise GltfImportError("EXT_mesh_gpu_instancing nodes are unsupported")
        if "skin" in node:
            raise GltfImportError(f"nodes[{node_id}] uses unsupported skinning")
        if "weights" in node:
            raise GltfImportError(f"nodes[{node_id}] uses unsupported morph weights")
        with np.errstate(over="ignore", invalid="ignore"):
            world = parent_matrix @ _local_matrix(node, node_id)
        if not np.isfinite(world).all() or not np.allclose(
            world[3], [0.0, 0.0, 0.0, 1.0], rtol=0.0, atol=1e-9
        ):
            raise GltfImportError(
                f"nodes[{node_id}] world transform overflows or is non-affine"
            )
        world_determinant = float(np.linalg.det(world[:3, :3]))
        if not math.isfinite(world_determinant) or abs(world_determinant) < 1e-15:
            raise GltfImportError(f"nodes[{node_id}] world transform is singular")
        processed_nodes += 1
        mesh_value = node.get("mesh")
        if mesh_value is not None:
            mesh_id = _index(mesh_value, meshes, f"nodes[{node_id}].mesh")
            mesh = _object(meshes[mesh_id], f"meshes[{mesh_id}]")
            if mesh.get("weights") is not None:
                raise GltfImportError(f"meshes[{mesh_id}] uses unsupported morph weights")
            primitives = _array(mesh.get("primitives", []), f"meshes[{mesh_id}].primitives")
            if not primitives:
                raise GltfImportError(f"meshes[{mesh_id}] has no primitives")
            raw_name = node.get("name", mesh.get("name"))
            fallback_name = f"mesh_{mesh_id}"
            part_name = _unique_name(_clean_name(raw_name, fallback_name), name_counts)
            part_id = len(part_names)
            local_vertex_count = 0
            local_face_count = 0
            part_vertex_chunks: list[np.ndarray] = []
            part_colour_chunks: list[np.ndarray] = []
            part_face_chunks: list[np.ndarray] = []
            part_local_offset = 0
            for primitive_id, raw_primitive in enumerate(primitives):
                primitive_count += 1
                primitive = _object(
                    raw_primitive, f"meshes[{mesh_id}].primitives[{primitive_id}]"
                )
                extensions = primitive.get("extensions")
                if isinstance(extensions, dict) and "KHR_draco_mesh_compression" in extensions:
                    raise GltfImportError(
                        "Draco (KHR_draco_mesh_compression) primitives are unsupported"
                    )
                if primitive.get("targets"):
                    raise GltfImportError("Morph target primitives are unsupported")
                attributes = _object(primitive.get("attributes"), "primitive.attributes")
                if "JOINTS_0" in attributes or "WEIGHTS_0" in attributes:
                    raise GltfImportError("Skinned vertex attributes are unsupported")
                if "POSITION" not in attributes:
                    raise GltfImportError("Every mesh primitive needs POSITION")
                positions, position_def = reader.accessor(
                    _integer(attributes["POSITION"], "POSITION"), "POSITION"
                )
                if (
                    position_def.get("type") != "VEC3"
                    or int(position_def["componentType"]) != 5126
                    or bool(position_def.get("normalized", False))
                ):
                    raise GltfImportError("POSITION must be non-normalized FLOAT VEC3")
                positions = np.asarray(positions, dtype=np.float64)
                if not len(positions) or not np.isfinite(positions).all():
                    raise GltfImportError("POSITION is empty or contains NaN/infinity")
                index_value = primitive.get("indices")
                if index_value is None:
                    source_indices = np.arange(len(positions), dtype=np.int32)
                else:
                    decoded_indices, index_def = reader.accessor(
                        _integer(index_value, "primitive.indices"), "primitive.indices"
                    )
                    if (
                        index_def.get("type") != "SCALAR"
                        or int(index_def["componentType"]) not in _UNSIGNED_INDEX_COMPONENTS
                        or bool(index_def.get("normalized", False))
                    ):
                        raise GltfImportError("indices must be unsigned non-normalized SCALAR")
                    source_indices = np.asarray(decoded_indices).reshape(-1)
                mode = _integer(primitive.get("mode", 4), "primitive.mode")
                triangles = _triangles(source_indices, mode, "mesh primitive")
                if not len(triangles):
                    raise GltfImportError("A mesh primitive produced no triangles")
                if int(triangles.min()) < 0 or int(triangles.max()) >= len(positions):
                    raise GltfImportError("Mesh indices reference a missing POSITION")
                nondegenerate = (
                    (triangles[:, 0] != triangles[:, 1])
                    & (triangles[:, 1] != triangles[:, 2])
                    & (triangles[:, 2] != triangles[:, 0])
                )
                dropped_degenerate += int(np.count_nonzero(~nondegenerate))
                triangles = triangles[nondegenerate]
                if not len(triangles):
                    raise GltfImportError("A mesh primitive contains only degenerate triangles")
                suppress_vertex_colour = "COLOR_0" in attributes and (
                    vertex_color_policy == "ignore"
                    or (mesh_id, primitive_id) in auto_ignored_colours
                )
                rgba_linear, vertex_colour, texture_colour = _material_colour(
                    reader,
                    primitive,
                    attributes,
                    len(positions),
                    apply_vertex_colour=not suppress_vertex_colour,
                )
                if suppress_vertex_colour:
                    suppressed_vertex_colours += 1
                used_vertex_colours = used_vertex_colours or vertex_colour
                used_textures = used_textures or texture_colour
                discarded_alpha = discarded_alpha or bool(
                    np.any(rgba_linear[:, 3] < 0.999999)
                )
                # POSITION is capped below int32 range.  A boolean membership
                # pass avoids sorting and duplicating up to 15 million uint32
                # indices solely to discover which vertices are referenced.
                used_mask = np.zeros(len(positions), dtype=np.bool_)
                used_mask[triangles.reshape(-1)] = True
                used = np.flatnonzero(used_mask).astype(np.int32, copy=False)
                remap = np.full(len(positions), -1, dtype=np.int32)
                remap[used] = np.arange(len(used), dtype=np.int32)
                compact_faces = remap[triangles]
                compact_positions = positions[used]
                transformed = (
                    compact_positions @ world[:3, :3].T + world[:3, 3]
                )
                if not np.isfinite(transformed).all():
                    raise GltfImportError("A node transform produced NaN or infinity")
                if world_determinant < 0.0:
                    compact_faces[:, [1, 2]] = compact_faces[:, [2, 1]]
                compact_colours = _linear_to_srgb(rgba_linear[used, :3])
                part_vertex_chunks.append(transformed.astype(np.float32))
                part_colour_chunks.append(compact_colours.astype(np.float32))
                part_face_chunks.append(
                    (
                        compact_faces + np.int32(part_local_offset)
                    ).astype(np.int32, copy=False)
                )
                part_local_offset += len(compact_positions)
                local_vertex_count += len(compact_positions)
                local_face_count += len(compact_faces)
                if (
                    vertex_offset + local_vertex_count > _MAX_IMPORTED_VERTICES
                    or sum(part_face_counts) + local_face_count > face_limit
                ):
                    raise GltfImportError(
                        "Imported static mesh exceeds its admitted vertex/triangle limit: "
                        f"vertices {vertex_offset + local_vertex_count:,} / "
                        f"{_MAX_IMPORTED_VERTICES:,}, triangles "
                        f"{sum(part_face_counts) + local_face_count:,} / "
                        f"{face_limit:,}"
                    )
            if local_face_count:
                part_vertices = np.vstack(part_vertex_chunks)
                part_colours = np.vstack(part_colour_chunks)
                part_faces = np.vstack(part_face_chunks)
                if vertex_offset:
                    part_faces = part_faces + np.int32(vertex_offset)
                if vertex_offset + len(part_vertices) > np.iinfo(np.int32).max:
                    raise GltfImportError("Imported glTF has too many vertices")
                vertices_parts.append(part_vertices)
                colours_parts.append(part_colours)
                face_parts.append(part_faces.astype(np.int32, copy=False))
                face_part_ids_parts.append(
                    np.full(local_face_count, part_id, dtype=np.int32)
                )
                part_names.append(part_name)
                path_key = ".".join(str(value) for value in traversal_path)
                scene_key = "implicit" if scene_id is None else str(scene_id)
                part_keys.append(
                    f"gltf:scene={scene_key}:path={path_key}:node={node_id}:mesh={mesh_id}"
                )
                part_face_counts.append(local_face_count)
                part_vertex_counts.append(local_vertex_count)
                vertex_offset += len(part_vertices)
        children = _array(node.get("children", []), f"nodes[{node_id}].children")
        next_ancestors = ancestors | {node_id}
        for child_position, child_value in reversed(list(enumerate(children))):
            child_id = _index(child_value, nodes, f"nodes[{node_id}].children")
            stack.append(
                (
                    child_id,
                    world,
                    traversal_path + (child_position,),
                    next_ancestors,
                )
            )
        _emit(
            progress,
            "parse",
            0.15 + 0.75 * processed_nodes / max(len(nodes), 1),
            f"GLB/glTFノード読込: {processed_nodes:,}",
        )

    if not face_parts:
        raise GltfImportError("The selected glTF scene contains no triangle mesh")
    vertices = np.vstack(vertices_parts).astype(np.float32, copy=False)
    colours = np.vstack(colours_parts).astype(np.float32, copy=False)
    faces = np.vstack(face_parts).astype(np.int32, copy=False)
    face_part_ids = np.concatenate(face_part_ids_parts).astype(np.int32, copy=False)
    if not np.isfinite(vertices).all() or not np.isfinite(colours).all():
        raise GltfImportError("Imported mesh contains NaN or infinity")
    if used_textures:
        warnings.append(
            "UVテクスチャを各メッシュ頂点でサンプリングし、sRGB頂点色へ焼き付けました"
        )
    if reader.ignored_appearance_maps:
        warnings.append(
            "印刷色にはbaseColorだけを使用し、PBR表示用マップは意図的に除外しました: "
            + ", ".join(sorted(reader.ignored_appearance_maps))
        )
    if suppressed_vertex_colours:
        if vertex_color_policy == "auto":
            warnings.append(
                "COLOR_0自動判定: 共通baseColorTexture "
                f"(index {auto_shared_texture}) を使う {suppressed_vertex_colours} 個の"
                "primitiveで、パーツ分割表示用とみられるほぼ一様なカテゴリ頂点色を"
                "検出しました。COLOR_0は乗算せず、baseColorTexture/baseColorFactorだけを"
                "使用しました。glTF規格どおりに合成する場合は"
                "vertex_color_policy='multiply'を指定してください"
            )
        else:
            warnings.append(
                "vertex_color_policy='ignore'の指定により、"
                f"{suppressed_vertex_colours} 個のprimitiveのCOLOR_0を乗算せず、"
                "COLOR_0以外のbaseColor情報だけを使用しました"
            )
    if used_vertex_colours and used_textures:
        warnings.append("COLOR_0とbaseColorTextureをglTF規格どおり線形色で合成しました")
    if discarded_alpha:
        warnings.append("半透明情報は印刷用RGB頂点色に保持できないため、RGBだけを使用しました")
    if dropped_degenerate:
        warnings.append(f"縮退した三角形を {dropped_degenerate:,} 面除外しました")
    if len(part_names) > 1:
        warnings.append(f"glTFシーンのメッシュパーツを {len(part_names)} 個認識しました")
    if primitive_count > len(part_names):
        warnings.append(
            f"{primitive_count} 個のmesh primitiveをノード単位の {len(part_names)} パーツに保持しました"
        )
    _emit(progress, "parse", 1.0, "GLB/glTF読込完了")
    return ObjAsset(
        path=path,
        sha256=source_sha256,
        file_size=source_file_size,
        vertices=vertices,
        colors=np.clip(colours, 0.0, 1.0),
        faces=faces,
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=warnings,
        part_names=tuple(part_names),
        part_keys=tuple(part_keys),
        face_part_ids=face_part_ids,
        part_face_counts=tuple(part_face_counts),
        part_vertex_counts=tuple(part_vertex_counts),
        part_marker_kind="gltf_node",
        has_explicit_parts=len(part_names) > 1,
        import_metadata={
            "schema": _GLTF_IMPORT_METADATA_SCHEMA,
            "large_source_reduction_required": bool(
                plan.requires_reduced_mode
            ),
            "source_triangle_workload": int(plan.triangle_count),
            "maximum_final_faces": int(
                LARGE_GLTF_REDUCTION_TARGET_FACES
                if plan.requires_reduced_mode
                else _MAX_IMPORTED_FACES
            ),
            "compatible_exploded_multipart": bool(
                compatible_exploded_multipart
            ),
            "categorical_part_ids_detected": bool(auto_ignored_colours),
            "segmentation_vertex_colors_suppressed": bool(
                vertex_color_policy == "auto" and auto_ignored_colours
            ),
            "vertex_color_policy": vertex_color_policy,
        },
    )


__all__ = [
    "GLTF_NORMAL_SOURCE_FACE_LIMIT",
    "GLTF_REDUCED_SOURCE_FACE_LIMIT",
    "GLTF_SOURCE_VERTEX_LIMIT",
    "GltfImportError",
    "GltfImportPlan",
    "LARGE_GLTF_REDUCTION_TARGET_FACES",
    "VertexColorPolicy",
    "inspect_gltf_asset",
    "load_gltf_asset",
]
