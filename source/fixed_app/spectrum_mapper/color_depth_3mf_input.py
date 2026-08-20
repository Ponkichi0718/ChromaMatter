"""Strict per-part FullSpectrum 3MF input for ColorDepth Lab.

This reader has a deliberately narrow contract.  It imports one printable,
closed mesh and its per-triangle palette-state identities; it never evaluates
Orca/Bambu paint strings, grouped Cycle recipes, Ratio cadence, support, or
toolpath settings.  The imported state IDs are merely target-colour labels for
the physical ColorDepth geometry provider.

Both Core 3MF and the one-level Production Extension layout emitted by the
application are supported.  Package paths, relationships, transforms, units,
material resources, topology, and palette identity all fail closed before the
result can cross the geometry boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Mapping, Sequence
from urllib.parse import unquote, urlsplit
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import trimesh

from .mixer import MAX_FULL_SPECTRUM_STATES, normalize_hex


_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PRODUCTION_NS = (
    "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
)
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MODEL_RELATIONSHIP = (
    "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
)
_PALETTE_MEMBER = "Metadata/full_spectrum_palette.json"
_ROOT_RELS_MEMBER = "_rels/.rels"
_MAX_ARCHIVE_MEMBERS = 256
_MAX_MEMBER_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200
_MAX_COMPONENT_DEPTH = 64
_MAX_VERTEX_COUNT = 10_000_000
_MAX_FACE_COUNT = 20_000_000
_UNIT_TO_MM = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}
_FORBIDDEN_XML = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_XML_ENCODING = re.compile(
    br"<\?xml[^>]*\bencoding\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


class ColorDepth3MFInputError(RuntimeError):
    """Stable fail-closed diagnostic for an unsafe or ambiguous source 3MF."""

    def __init__(
        self,
        code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(self.code)


def _raise(code: str, **details: object) -> None:
    raise ColorDepth3MFInputError(code, details)


def _immutable(values: np.ndarray, dtype: np.dtype) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype).copy()
    result.flags.writeable = False
    return result


@dataclass(frozen=True, slots=True)
class ImportedColorDepthPart:
    """One exact printable source part in millimetres.

    ``face_target_labels`` are zero-based palette-state labels.  The mixed
    pair tuple starts at state label four and contains only physical pair
    identity; source Ratio values are intentionally absent.
    """

    vertices_mm: np.ndarray
    faces: np.ndarray
    face_target_labels: np.ndarray
    physical_slot_order: tuple[str, str, str, str]
    palette_state_count: int
    print_mix_specs: tuple[tuple[int, int], ...]
    source_name: str
    source_sha256: str
    source_volume_mm3: float
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def physical_colors(self) -> tuple[str, str, str, str]:
        """GUI-friendly alias; embedded F1--F4 remain authoritative."""

        return self.physical_slot_order


@dataclass(frozen=True, slots=True)
class _Palette:
    physical: tuple[str, str, str, str]
    state_count: int
    state_names: tuple[str, ...]
    state_colors: tuple[str, ...]
    state_face_counts: tuple[int, ...] | None
    pairs: tuple[tuple[int, int], ...]
    sha256: str
    legacy_surface_shell_present: bool


@dataclass(frozen=True, slots=True)
class _ObjectDef:
    object_id: int
    name: str
    kind: str
    mesh: ET.Element | None
    components: tuple[ET.Element, ...]


@dataclass(frozen=True, slots=True)
class _ModelDef:
    member: str
    unit_scale_mm: float
    objects: Mapping[int, _ObjectDef]
    materials: Mapping[int, tuple[tuple[str, str], ...]]
    root: ET.Element
    sha256: str


@dataclass(frozen=True, slots=True)
class _Leaf:
    model: _ModelDef
    object_def: _ObjectDef
    world_from_leaf_mm: np.ndarray
    transform_chain: tuple[Mapping[str, object], ...]
    build_object_id: int
    build_index: int


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _normalise_member_name(name: str) -> str:
    raw = unicodedata.normalize("NFC", str(name))
    if (
        not raw
        or "\\" in raw
        or "\x00" in raw
        or raw.startswith("/")
        or re.match(r"^[A-Za-z]:", raw)
    ):
        _raise("archive_member_path_unsafe", member=name)
    decoded = unicodedata.normalize("NFC", unquote(raw))
    if "\\" in decoded or "\x00" in decoded or decoded.startswith("/"):
        _raise("archive_member_path_unsafe", member=name)
    parts = decoded.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _raise("archive_member_path_unsafe", member=name)
    return "/".join(parts)


def _archive_preflight(
    archive: zipfile.ZipFile,
) -> tuple[dict[str, zipfile.ZipInfo], dict[str, str]]:
    infos = archive.infolist()
    if len(infos) > _MAX_ARCHIVE_MEMBERS:
        _raise(
            "archive_member_count_exceeded",
            count=len(infos),
            maximum=_MAX_ARCHIVE_MEMBERS,
        )
    exact: dict[str, zipfile.ZipInfo] = {}
    canonical: dict[str, str] = {}
    total = 0
    for info in infos:
        # On Windows ``zipfile`` normalises backslashes in ``filename`` even
        # when the raw central-directory name contains them.  Validate the
        # preserved spelling first: otherwise an archive can bypass the
        # package-path policy before two names collapse onto one member.
        original_name = str(getattr(info, "orig_filename", info.filename))
        _normalise_member_name(original_name)
        name = str(info.filename)
        if original_name != name:
            _raise(
                "archive_member_path_unsafe",
                member=original_name,
                normalised_member=name,
            )
        if name in exact:
            _raise("archive_duplicate_member", member=name)
        normalised = _normalise_member_name(name)
        collision_key = normalised.casefold()
        previous = canonical.get(collision_key)
        if previous is not None:
            _raise(
                "archive_member_collision",
                first=previous,
                second=name,
            )
        canonical[collision_key] = name
        exact[name] = info
        if bool(info.flag_bits & 0x1):
            _raise("archive_encrypted_member", member=name)
        if info.is_dir():
            _raise("archive_member_path_unsafe", member=name)
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            _raise(
                "archive_compression_unsupported",
                member=name,
                compression=int(info.compress_type),
            )
        size = int(info.file_size)
        compressed = int(info.compress_size)
        if size < 0 or size > _MAX_MEMBER_UNCOMPRESSED_BYTES:
            _raise(
                "archive_member_size_exceeded",
                member=name,
                size=size,
                maximum=_MAX_MEMBER_UNCOMPRESSED_BYTES,
            )
        total += size
        if total > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            _raise(
                "archive_total_size_exceeded",
                size=total,
                maximum=_MAX_TOTAL_UNCOMPRESSED_BYTES,
            )
        ratio = float(size) / float(max(compressed, 1))
        if size > 4096 and ratio > float(_MAX_COMPRESSION_RATIO):
            _raise(
                "archive_compression_ratio_exceeded",
                member=name,
                ratio=ratio,
                maximum=_MAX_COMPRESSION_RATIO,
            )
    return exact, canonical


def _require_member(
    members: Mapping[str, zipfile.ZipInfo],
    name: str,
) -> zipfile.ZipInfo:
    info = members.get(name)
    if info is None:
        _raise("archive_required_member_missing", member=name)
    return info


def _read_member(
    archive: zipfile.ZipFile,
    members: Mapping[str, zipfile.ZipInfo],
    name: str,
) -> bytes:
    info = _require_member(members, name)
    try:
        payload = archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        _raise("archive_member_read_failed", member=name, error=str(exc))
    if len(payload) != int(info.file_size):
        _raise("archive_member_size_mismatch", member=name)
    return payload


def _parse_xml(payload: bytes, *, member: str) -> ET.Element:
    if _FORBIDDEN_XML.search(payload):
        _raise("xml_forbidden_construct", member=member)
    encoding = _XML_ENCODING.search(payload[:512])
    if encoding is not None and encoding.group(1).lower() not in {b"utf-8", b"utf8"}:
        _raise(
            "xml_encoding_unsupported",
            member=member,
            encoding=encoding.group(1).decode("ascii", "replace"),
        )
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        _raise("xml_invalid", member=member, error=str(exc))


def _strict_json(payload: bytes, *, member: str) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                _raise("metadata_duplicate_key", member=member, key=key)
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8-sig")
        return json.loads(text, object_pairs_hook=object_pairs)
    except ColorDepth3MFInputError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _raise("metadata_invalid", member=member, error=str(exc))


def _colour(value: object, *, code: str) -> str:
    text = str(value).strip().upper()
    if len(text) == 9 and text.startswith("#"):
        if text[-2:] != "FF":
            _raise(code, value=value, reason="nonopaque")
        text = text[:7]
    try:
        return normalize_hex(text)
    except (TypeError, ValueError) as exc:
        _raise(code, value=value, error=str(exc))


def _integer(value: object, *, code: str, field: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        _raise(code, field=field, value=value)
    try:
        text = str(value).strip()
        if not re.fullmatch(r"[+-]?\d+", text):
            raise ValueError(text)
        return int(text)
    except (TypeError, ValueError) as exc:
        _raise(code, field=field, value=value, error=str(exc))


def _parse_palette(payload: bytes) -> _Palette:
    raw = _strict_json(payload, member=_PALETTE_MEMBER)
    if not isinstance(raw, dict):
        _raise("palette_metadata_invalid", reason="root_not_mapping")
    physical_raw = raw.get("physical_slot_order")
    if not isinstance(physical_raw, list) or len(physical_raw) != 4:
        _raise("palette_physical_slot_order_invalid")
    physical = tuple(
        _colour(value, code="palette_physical_slot_order_invalid")
        for value in physical_raw
    )
    if len(set(physical)) != 4:
        _raise("palette_physical_slot_order_invalid", reason="duplicate_colours")
    state_count = _integer(
        raw.get("palette_state_count"),
        code="palette_state_count_invalid",
        field="palette_state_count",
    )
    if not 4 <= state_count <= MAX_FULL_SPECTRUM_STATES:
        _raise(
            "palette_state_count_invalid",
            state_count=state_count,
            maximum=MAX_FULL_SPECTRUM_STATES,
        )
    states = raw.get("states")
    if not isinstance(states, list) or len(states) != state_count:
        _raise(
            "palette_state_table_invalid",
            expected=state_count,
            actual=(len(states) if isinstance(states, list) else None),
        )
    names: list[str] = []
    colors: list[str] = []
    face_counts: list[int] = []
    any_face_counts = False
    all_face_counts = True
    for label, state in enumerate(states):
        if not isinstance(state, dict):
            _raise("palette_state_table_invalid", label=label)
        one_based = _integer(
            state.get("state"),
            code="palette_state_table_invalid",
            field="state",
        )
        if one_based != label + 1:
            _raise(
                "palette_state_table_invalid",
                label=label,
                state=one_based,
            )
        name = str(state.get("name", "")).strip()
        if not name or len(name) > 1024:
            _raise("palette_state_table_invalid", label=label, field="name")
        names.append(name)
        colors.append(
            _colour(
                state.get("display_rgb"),
                code="palette_state_table_invalid",
            )
        )
        if "face_count" in state:
            any_face_counts = True
            count = _integer(
                state.get("face_count"),
                code="palette_state_table_invalid",
                field="face_count",
            )
            if count < 0:
                _raise("palette_state_table_invalid", label=label, field="face_count")
            face_counts.append(count)
        else:
            all_face_counts = False
            face_counts.append(0)
    if any_face_counts and not all_face_counts:
        _raise("palette_state_table_invalid", reason="partial_face_counts")
    if tuple(colors[:4]) != physical:
        _raise("palette_state_table_invalid", reason="physical_state_colour_mismatch")

    specs = raw.get("print_mix_specs")
    expected_specs = state_count - 4
    if not isinstance(specs, list) or len(specs) != expected_specs:
        _raise(
            "palette_mix_table_invalid",
            expected=expected_specs,
            actual=(len(specs) if isinstance(specs, list) else None),
        )
    pairs: list[tuple[int, int]] = []
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            _raise("palette_mix_table_invalid", index=index)
        left = _integer(
            spec.get("physical_a"),
            code="palette_mix_table_invalid",
            field="physical_a",
        )
        right = _integer(
            spec.get("physical_b"),
            code="palette_mix_table_invalid",
            field="physical_b",
        )
        if not 1 <= left <= 4 or not 1 <= right <= 4 or left == right:
            _raise(
                "palette_mix_table_invalid",
                index=index,
                physical_pair=[left, right],
            )
        # ratio_b_percent and every Cycle/surface-shell field are data only.
        pairs.append((left, right))
    return _Palette(
        physical=physical,  # type: ignore[arg-type]
        state_count=state_count,
        state_names=tuple(names),
        state_colors=tuple(colors),
        state_face_counts=(tuple(face_counts) if all_face_counts else None),
        pairs=tuple(pairs),
        sha256=_sha256_bytes(payload),
        legacy_surface_shell_present=isinstance(raw.get("surface_shell"), dict),
    )


def _resolve_target(base_member: str, raw_target: object) -> str:
    target = str(raw_target or "").strip()
    parsed = urlsplit(target)
    if (
        not target
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or "\\" in target
    ):
        _raise("relationship_target_unsafe", target=target)
    decoded = unicodedata.normalize("NFC", unquote(parsed.path))
    if decoded.startswith("/"):
        candidate = decoded[1:]
    else:
        parent = PurePosixPath(base_member).parent
        candidate = str(parent / decoded) if str(parent) != "." else decoded
    return _normalise_member_name(candidate)


def _relationship_targets(
    archive: zipfile.ZipFile,
    members: Mapping[str, zipfile.ZipInfo],
    relationship_member: str,
    *,
    source_member: str,
    required: bool,
) -> tuple[tuple[str, str], ...]:
    if relationship_member not in members:
        if required:
            _raise("model_relationship_missing", member=relationship_member)
        return ()
    root = _parse_xml(
        _read_member(archive, members, relationship_member),
        member=relationship_member,
    )
    if root.tag != f"{{{_REL_NS}}}Relationships":
        _raise("relationship_xml_invalid", member=relationship_member)
    result: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for element in root.findall(f"{{{_REL_NS}}}Relationship"):
        relationship_id = str(element.attrib.get("Id", "")).strip()
        if not relationship_id or relationship_id in seen_ids:
            _raise("relationship_xml_invalid", member=relationship_member)
        seen_ids.add(relationship_id)
        target_mode = str(element.attrib.get("TargetMode", "")).strip().lower()
        if target_mode == "external":
            _raise(
                "relationship_external_target",
                member=relationship_member,
                relationship_id=relationship_id,
            )
        if target_mode not in {"", "internal"}:
            _raise(
                "relationship_target_mode_invalid",
                member=relationship_member,
                relationship_id=relationship_id,
                target_mode=target_mode,
            )
        if element.attrib.get("Type") == _MODEL_RELATIONSHIP:
            result.append(
                (
                    relationship_id,
                    _resolve_target(source_member, element.attrib.get("Target")),
                )
            )
    return tuple(result)


def _model_relationship_member(model_member: str) -> str:
    path = PurePosixPath(model_member)
    return str(path.parent / "_rels" / f"{path.name}.rels")


def _parse_model(
    archive: zipfile.ZipFile,
    members: Mapping[str, zipfile.ZipInfo],
    member: str,
) -> _ModelDef:
    payload = _read_member(archive, members, member)
    root = _parse_xml(payload, member=member)
    if root.tag != f"{{{_CORE_NS}}}model":
        _raise("model_xml_invalid", member=member, reason="wrong_root")
    unit = str(root.attrib.get("unit", "millimeter")).strip().lower()
    unit_scale = _UNIT_TO_MM.get(unit)
    if unit_scale is None:
        _raise("model_unit_unsupported", member=member, unit=unit)
    resources = root.find(f"{{{_CORE_NS}}}resources")
    if resources is None:
        _raise("model_xml_invalid", member=member, reason="resources_missing")
    materials: dict[int, tuple[tuple[str, str], ...]] = {}
    for group in resources.findall(f"{{{_CORE_NS}}}basematerials"):
        resource_id = _integer(
            group.attrib.get("id"),
            code="material_resource_invalid",
            field="id",
        )
        if resource_id <= 0 or resource_id in materials:
            _raise("material_resource_invalid", member=member, id=resource_id)
        rows: list[tuple[str, str]] = []
        for base in group.findall(f"{{{_CORE_NS}}}base"):
            name = str(base.attrib.get("name", "")).strip()
            if not name:
                _raise("material_resource_invalid", member=member, id=resource_id)
            color = _colour(
                base.attrib.get("displaycolor"),
                code="material_resource_invalid",
            )
            rows.append((name, color))
        if not rows:
            _raise("material_resource_invalid", member=member, id=resource_id)
        materials[resource_id] = tuple(rows)
    objects: dict[int, _ObjectDef] = {}
    for element in resources.findall(f"{{{_CORE_NS}}}object"):
        object_id = _integer(
            element.attrib.get("id"),
            code="model_object_invalid",
            field="id",
        )
        if object_id <= 0 or object_id in objects:
            _raise("model_object_invalid", member=member, object_id=object_id)
        kind = str(element.attrib.get("type", "model")).strip().lower()
        if kind != "model":
            _raise(
                "model_object_not_printable",
                member=member,
                object_id=object_id,
                object_type=kind,
            )
        mesh = element.find(f"{{{_CORE_NS}}}mesh")
        components_parent = element.find(f"{{{_CORE_NS}}}components")
        components = (
            tuple(components_parent.findall(f"{{{_CORE_NS}}}component"))
            if components_parent is not None
            else ()
        )
        if (mesh is None) == (not components):
            _raise(
                "model_object_invalid",
                member=member,
                object_id=object_id,
                reason="exactly_one_mesh_or_components_required",
            )
        objects[object_id] = _ObjectDef(
            object_id=object_id,
            name=str(element.attrib.get("name", f"object-{object_id}")),
            kind=kind,
            mesh=mesh,
            components=components,
        )
    if not objects:
        _raise("model_object_invalid", member=member, reason="no_objects")
    return _ModelDef(
        member=member,
        unit_scale_mm=float(unit_scale),
        objects=objects,
        materials=materials,
        root=root,
        sha256=_sha256_bytes(payload),
    )


def _parse_transform(raw: object, *, unit_scale_mm: float) -> np.ndarray:
    if raw is None or not str(raw).strip():
        return np.eye(4, dtype=np.float64)
    tokens = str(raw).strip().split()
    if len(tokens) != 12:
        _raise("transform_invalid", value=raw, count=len(tokens))
    try:
        values = np.asarray([float(value) for value in tokens], dtype=np.float64)
    except ValueError as exc:
        _raise("transform_invalid", value=raw, error=str(exc))
    if not np.isfinite(values).all():
        _raise("transform_nonfinite", value=raw)
    # 3MF serialises the first three columns of a row-vector affine matrix.
    # Convert once to the conventional column-vector matrix used below.
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = values[:9].reshape(3, 3).T
    matrix[:3, 3] = values[9:12] * float(unit_scale_mm)
    determinant = float(np.linalg.det(matrix[:3, :3]))
    if not math.isfinite(determinant):
        _raise("transform_nonfinite", value=raw)
    if abs(determinant) <= 1e-12:
        _raise("transform_singular", value=raw, determinant=determinant)
    if determinant < 0.0:
        _raise("transform_reflection", value=raw, determinant=determinant)
    return matrix


def _component_path(element: ET.Element) -> str | None:
    return element.attrib.get(f"{{{_PRODUCTION_NS}}}path")


def _build_path(element: ET.Element) -> str | None:
    return element.attrib.get(f"{{{_PRODUCTION_NS}}}path")


def _parse_object_id(element: ET.Element) -> int:
    return _integer(
        element.attrib.get("objectid"),
        code="component_reference_invalid",
        field="objectid",
    )


def _parse_mesh(
    leaf: _Leaf,
    palette: _Palette,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    mesh = leaf.object_def.mesh
    assert mesh is not None
    vertices_element = mesh.find(f"{{{_CORE_NS}}}vertices")
    triangles_element = mesh.find(f"{{{_CORE_NS}}}triangles")
    if vertices_element is None or triangles_element is None:
        _raise("mesh_structure_invalid")
    vertex_elements = vertices_element.findall(f"{{{_CORE_NS}}}vertex")
    triangle_elements = triangles_element.findall(f"{{{_CORE_NS}}}triangle")
    if not vertex_elements or len(vertex_elements) > _MAX_VERTEX_COUNT:
        _raise("mesh_vertex_count_invalid", count=len(vertex_elements))
    if not triangle_elements or len(triangle_elements) > _MAX_FACE_COUNT:
        _raise("mesh_face_count_invalid", count=len(triangle_elements))
    vertices_raw = np.empty((len(vertex_elements), 3), dtype=np.float64)
    for index, element in enumerate(vertex_elements):
        try:
            vertices_raw[index] = (
                float(element.attrib["x"]),
                float(element.attrib["y"]),
                float(element.attrib["z"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            _raise("mesh_vertex_invalid", vertex=index, error=str(exc))
    if not np.isfinite(vertices_raw).all():
        _raise("mesh_vertex_nonfinite")

    faces = np.empty((len(triangle_elements), 3), dtype=np.int32)
    labels = np.empty(len(triangle_elements), dtype=np.int32)
    used_material_id: int | None = None
    for index, element in enumerate(triangle_elements):
        try:
            raw_indices = [element.attrib[key] for key in ("v1", "v2", "v3")]
        except KeyError as exc:
            _raise("mesh_triangle_invalid", triangle=index, error=str(exc))
        indices = [
            _integer(
                value,
                code="mesh_triangle_invalid",
                field=f"v{position + 1}",
            )
            for position, value in enumerate(raw_indices)
        ]
        if min(indices) < 0 or max(indices) >= len(vertices_raw):
            _raise("mesh_triangle_index_out_of_bounds", triangle=index)
        if len(set(indices)) != 3:
            _raise("mesh_triangle_degenerate", triangle=index)
        faces[index] = indices
        if "pid" not in element.attrib or "p1" not in element.attrib:
            _raise("triangle_material_missing", triangle=index)
        material_id = _integer(
            element.attrib.get("pid"),
            code="triangle_material_invalid",
            field="pid",
        )
        label = _integer(
            element.attrib.get("p1"),
            code="triangle_material_invalid",
            field="p1",
        )
        if used_material_id is None:
            used_material_id = material_id
        elif used_material_id != material_id:
            _raise("triangle_material_resource_mismatch", triangle=index)
        for corner in ("p2", "p3"):
            if corner in element.attrib and _integer(
                element.attrib.get(corner),
                code="triangle_material_invalid",
                field=corner,
            ) != label:
                _raise("triangle_mixed_material_not_supported", triangle=index)
        if label < 0 or label >= palette.state_count:
            _raise(
                "material_index_out_of_bounds",
                triangle=index,
                material_index=label,
                state_count=palette.state_count,
            )
        labels[index] = label
    assert used_material_id is not None
    rows = leaf.model.materials.get(used_material_id)
    if rows is None:
        _raise("triangle_material_resource_missing", resource_id=used_material_id)
    if len(rows) != palette.state_count:
        _raise(
            "material_state_table_mismatch",
            resource_id=used_material_id,
            expected=palette.state_count,
            actual=len(rows),
        )
    for label, ((name, color), expected_name, expected_color) in enumerate(
        zip(rows, palette.state_names, palette.state_colors, strict=True)
    ):
        if name != expected_name or color != expected_color:
            _raise(
                "material_state_table_mismatch",
                resource_id=used_material_id,
                label=label,
            )
    if palette.state_face_counts is not None:
        histogram = np.bincount(labels, minlength=palette.state_count)
        if tuple(int(value) for value in histogram) != palette.state_face_counts:
            _raise(
                "palette_state_face_count_mismatch",
                expected=list(palette.state_face_counts),
                actual=[int(value) for value in histogram],
            )

    scale = np.eye(4, dtype=np.float64)
    scale[:3, :3] *= float(leaf.model.unit_scale_mm)
    composed = leaf.world_from_leaf_mm @ scale
    determinant = float(np.linalg.det(composed[:3, :3]))
    if not math.isfinite(determinant) or determinant <= 1e-12:
        _raise("transform_singular", determinant=determinant)
    homogeneous = np.column_stack(
        (vertices_raw, np.ones(len(vertices_raw), dtype=np.float64))
    )
    vertices_world = homogeneous @ composed.T
    if not np.isfinite(vertices_world).all():
        _raise("transform_nonfinite")
    w = vertices_world[:, 3]
    if not np.allclose(w, 1.0, rtol=0.0, atol=1e-12):
        _raise("transform_invalid", reason="non_affine_homogeneous_result")
    return vertices_world[:, :3], faces, labels, used_material_id


def _validate_and_canonicalise(
    vertices_world: np.ndarray,
    faces: np.ndarray,
) -> tuple[np.ndarray, float, dict[str, object]]:
    minimum = np.min(vertices_world, axis=0)
    maximum = np.max(vertices_world, axis=0)
    xy_center = 0.5 * (minimum[:2] + maximum[:2])
    min_z = float(minimum[2])
    translation = np.asarray([-xy_center[0], -xy_center[1], -min_z])
    vertices = np.ascontiguousarray(vertices_world + translation, dtype=np.float64)
    if not np.isfinite(vertices).all():
        _raise("mesh_vertex_nonfinite")
    triangles = vertices[faces]
    double_areas = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    )
    scale = float(np.max(np.ptp(vertices, axis=0), initial=0.0))
    tolerance = max(1e-18, scale * scale * 1e-14)
    degenerate = np.flatnonzero(~np.isfinite(double_areas) | (double_areas <= tolerance))
    if len(degenerate):
        _raise(
            "mesh_triangle_degenerate",
            count=int(len(degenerate)),
            first=int(degenerate[0]),
        )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if not bool(mesh.is_watertight):
        _raise("mesh_not_watertight")
    if not bool(mesh.is_winding_consistent):
        _raise("mesh_not_oriented")
    try:
        body_count = int(mesh.body_count)
    except (AttributeError, TypeError, ValueError):
        body_count = len(mesh.split(only_watertight=False))
    if body_count != 1:
        _raise("mesh_body_count_invalid", body_count=body_count)
    volume = float(mesh.volume)
    if not math.isfinite(volume) or volume <= 0.0:
        _raise("mesh_volume_nonpositive", volume_mm3=volume)
    return vertices, volume, {
        "xy_center_mm": [float(value) for value in xy_center],
        "min_z_mm": min_z,
        "translation_mm": [float(value) for value in translation],
        "policy": "xy-bbox-center-and-min-z",
    }


def _expected_pairs_mapping(pairs: Sequence[tuple[int, int]]) -> dict[int, tuple[int, int]]:
    return {index + 4: tuple(pair) for index, pair in enumerate(pairs)}


def import_color_depth_3mf(
    path: Path,
    *,
    expected_physical_slot_order: Sequence[str] | None = None,
    expected_state_pairs: Mapping[int, Sequence[int]] | None = None,
) -> ImportedColorDepthPart:
    """Import one ordinary per-part FullSpectrum 3MF without executing it."""

    source_path = Path(path).resolve()
    if not source_path.is_file():
        _raise("source_3mf_missing", path=str(source_path))
    source_sha256 = _sha256_file(source_path)
    try:
        archive = zipfile.ZipFile(source_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        _raise("archive_invalid", path=str(source_path), error=str(exc))
    with archive:
        members, _canonical = _archive_preflight(archive)
        palette_payload = _read_member(archive, members, _PALETTE_MEMBER)
        palette = _parse_palette(palette_payload)
        if expected_physical_slot_order is not None:
            try:
                expected_physical = tuple(
                    normalize_hex(str(value)) for value in expected_physical_slot_order
                )
            except (TypeError, ValueError) as exc:
                _raise("physical_slot_order_mismatch", error=str(exc))
            if expected_physical != palette.physical:
                _raise(
                    "physical_slot_order_mismatch",
                    expected=list(expected_physical),
                    actual=list(palette.physical),
                )
        embedded_pairs = _expected_pairs_mapping(palette.pairs)
        if expected_state_pairs is not None:
            try:
                expected_pairs = {
                    int(label): (int(pair[0]), int(pair[1]))
                    for label, pair in expected_state_pairs.items()
                }
            except (TypeError, ValueError, IndexError) as exc:
                _raise("palette_state_pair_mismatch", error=str(exc))
            if expected_pairs != embedded_pairs:
                _raise(
                    "palette_state_pair_mismatch",
                    expected={str(k): list(v) for k, v in expected_pairs.items()},
                    actual={str(k): list(v) for k, v in embedded_pairs.items()},
                )

        root_relationships = _relationship_targets(
            archive,
            members,
            _ROOT_RELS_MEMBER,
            source_member="",
            required=True,
        )
        if len(root_relationships) != 1:
            _raise(
                "model_relationship_count_invalid",
                count=len(root_relationships),
            )
        root_relationship_id, root_member = root_relationships[0]
        _require_member(members, root_member)
        model_cache: dict[str, _ModelDef] = {}

        def model(member: str) -> _ModelDef:
            current = model_cache.get(member)
            if current is None:
                current = _parse_model(archive, members, member)
                model_cache[member] = current
            return current

        root_model = model(root_member)
        build = root_model.root.find(f"{{{_CORE_NS}}}build")
        if build is None:
            _raise("printable_instance_count_invalid", count=0)
        printable: list[ET.Element] = []
        for item in build.findall(f"{{{_CORE_NS}}}item"):
            raw_printable = str(item.attrib.get("printable", "1")).strip().lower()
            if raw_printable not in {"0", "1", "false", "true"}:
                _raise("printable_flag_invalid", value=raw_printable)
            if raw_printable in {"1", "true"}:
                printable.append(item)
        if len(printable) != 1:
            _raise("printable_instance_count_invalid", count=len(printable))
        build_item = printable[0]
        build_object_id = _parse_object_id(build_item)
        build_matrix = _parse_transform(
            build_item.attrib.get("transform"),
            unit_scale_mm=root_model.unit_scale_mm,
        )
        build_path = _build_path(build_item)
        if build_path is not None:
            target_member = _resolve_target(root_member, build_path)
            root_model_rels = _relationship_targets(
                archive,
                members,
                _model_relationship_member(root_member),
                source_member=root_member,
                required=True,
            )
            if target_member not in {target for _rid, target in root_model_rels}:
                _raise("component_relationship_missing", target=target_member)
            target_model = model(target_member)
        else:
            target_member = root_member
            target_model = root_model

        leaves: list[_Leaf] = []

        def visit(
            current_model: _ModelDef,
            object_id: int,
            world: np.ndarray,
            chain: tuple[Mapping[str, object], ...],
            active: tuple[tuple[str, int], ...],
            depth: int,
        ) -> None:
            if depth > _MAX_COMPONENT_DEPTH:
                _raise("component_depth_exceeded", depth=depth)
            key = (current_model.member, int(object_id))
            if key in active:
                _raise("component_cycle", member=key[0], object_id=key[1])
            object_def = current_model.objects.get(int(object_id))
            if object_def is None:
                _raise(
                    "component_reference_invalid",
                    member=current_model.member,
                    object_id=object_id,
                )
            next_active = active + (key,)
            if object_def.mesh is not None:
                leaves.append(
                    _Leaf(
                        model=current_model,
                        object_def=object_def,
                        world_from_leaf_mm=np.asarray(world, dtype=np.float64),
                        transform_chain=chain,
                        build_object_id=build_object_id,
                        build_index=0,
                    )
                )
                return
            allowed_external: set[str] | None = None
            for component_index, component in enumerate(object_def.components):
                component_object_id = _parse_object_id(component)
                raw_path = _component_path(component)
                if raw_path is not None:
                    if current_model.member != root_member:
                        _raise(
                            "component_external_path_not_root",
                            member=current_model.member,
                        )
                    if allowed_external is None:
                        rels = _relationship_targets(
                            archive,
                            members,
                            _model_relationship_member(root_member),
                            source_member=root_member,
                            required=True,
                        )
                        allowed_external = {target for _rid, target in rels}
                    component_member = _resolve_target(root_member, raw_path)
                    if component_member not in allowed_external:
                        _raise(
                            "component_relationship_missing",
                            target=component_member,
                        )
                    component_model = model(component_member)
                else:
                    component_member = current_model.member
                    component_model = current_model
                component_matrix = _parse_transform(
                    component.attrib.get("transform"),
                    unit_scale_mm=current_model.unit_scale_mm,
                )
                record = {
                    "model_member": current_model.member,
                    "object_id": int(object_id),
                    "component_index": int(component_index),
                    "target_member": component_member,
                    "target_object_id": int(component_object_id),
                    "matrix": component_matrix.tolist(),
                }
                visit(
                    component_model,
                    component_object_id,
                    world @ component_matrix,
                    chain + (record,),
                    next_active,
                    depth + 1,
                )

        visit(
            target_model,
            build_object_id,
            build_matrix,
            (
                {
                    "kind": "build",
                    "root_model_member": root_member,
                    "target_member": target_member,
                    "object_id": int(build_object_id),
                    "matrix": build_matrix.tolist(),
                },
            ),
            (),
            1,
        )
        if len(leaves) != 1:
            _raise("printable_mesh_count_invalid", count=len(leaves))
        leaf = leaves[0]
        vertices_world, faces, labels, material_resource_id = _parse_mesh(
            leaf, palette
        )
        vertices, volume, canonicalization = _validate_and_canonicalise(
            vertices_world, faces
        )
        leaf_scale = np.eye(4, dtype=np.float64)
        leaf_scale[:3, :3] *= leaf.model.unit_scale_mm
        composed = leaf.world_from_leaf_mm @ leaf_scale
        determinant = float(np.linalg.det(composed[:3, :3]))
        geometry_digest = hashlib.sha256()
        geometry_digest.update(np.ascontiguousarray(vertices, dtype="<f8").tobytes())
        geometry_digest.update(np.ascontiguousarray(faces, dtype="<i4").tobytes())
        geometry_digest.update(np.ascontiguousarray(labels, dtype="<i4").tobytes())
        histogram = np.bincount(labels, minlength=palette.state_count)
        metadata = {
            "schema": "tripo-spectrum-mapper.color-depth.3mf-input.v1",
            "source_archive": {
                # Archive/report provenance must be safe to share.  The
                # resolved local path is intentionally kept out of the
                # returned object and all generator metadata; content identity
                # is carried by basename + SHA-256 + byte count.
                "name": source_path.name,
                "sha256": source_sha256,
                "bytes": int(source_path.stat().st_size),
                "member_count": int(len(members)),
            },
            "palette": {
                "member": _PALETTE_MEMBER,
                "sha256": palette.sha256,
                "physical_slot_order": list(palette.physical),
                "palette_state_count": int(palette.state_count),
                "state_pairs": {
                    str(label): list(pair)
                    for label, pair in embedded_pairs.items()
                },
                "legacy_ratio_values_used": False,
                "legacy_cycle_values_used": False,
                "legacy_surface_shell_present_in_source": bool(
                    palette.legacy_surface_shell_present
                ),
            },
            "model": {
                "root_relationship_id": root_relationship_id,
                "root_member": root_member,
                "root_sha256": root_model.sha256,
                "leaf_member": leaf.model.member,
                "leaf_sha256": leaf.model.sha256,
                "leaf_object_id": int(leaf.object_def.object_id),
                "leaf_object_name": leaf.object_def.name,
                "build_object_id": int(build_object_id),
                "build_item_index": 0,
                "material_resource_id": int(material_resource_id),
            },
            "transform": {
                "composed_3mf_matrix": composed.tolist(),
                "unit_scale_to_mm": float(leaf.model.unit_scale_mm),
                "determinant": determinant,
                "chain": [dict(value) for value in leaf.transform_chain],
            },
            "canonicalization": canonicalization,
            "geometry": {
                "vertices": int(len(vertices)),
                "faces": int(len(faces)),
                "target_state_histogram": [int(value) for value in histogram],
                "canonical_sha256": geometry_digest.hexdigest().upper(),
                "watertight": True,
                "oriented": True,
                "body_count": 1,
                "source_volume_mm3": float(volume),
            },
            "unsafe_source_execution_data_evaluated": False,
        }
        final_source_sha256 = _sha256_file(source_path)
        if final_source_sha256 != source_sha256:
            _raise(
                "source_archive_changed_during_read",
                initial_sha256=source_sha256,
                final_sha256=final_source_sha256,
            )
        return ImportedColorDepthPart(
            vertices_mm=_immutable(vertices, np.float64),
            faces=_immutable(faces, np.int32),
            face_target_labels=_immutable(labels, np.int32),
            physical_slot_order=palette.physical,
            palette_state_count=int(palette.state_count),
            print_mix_specs=palette.pairs,
            source_name=source_path.name,
            source_sha256=source_sha256,
            source_volume_mm3=float(volume),
            metadata=metadata,
        )


__all__ = [
    "ColorDepth3MFInputError",
    "ImportedColorDepthPart",
    "import_color_depth_3mf",
]
