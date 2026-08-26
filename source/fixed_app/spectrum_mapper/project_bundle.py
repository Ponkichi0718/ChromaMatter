"""Portable, fail-closed project folders for ChromaMatter.

The historical project format stored an absolute ``obj_path`` in a standalone
JSON document.  That path is neither portable nor a proof that the file still
contains the geometry that was painted.  This module owns the public folder
format instead:

``project folder/project.json``
    Settings and a manifest containing only relative member names.

``project folder/source.obj`` or ``project folder/source.glb``
    A byte-for-byte *copy* of the selected source model, protected by SHA-256.

An optional prepared-geometry ``.npz`` can be supplied by a future cache
serializer.  Merely bundling the source OBJ cannot promise that face IDs will
be reproduced if a geometry backend is nondeterministic.  Consequently the
load result exposes the saved mesh-fingerprint contracts and explicitly tells
the caller whether rebuilt geometry still needs verification before manual
paint/part/joint records are applied.

This module deliberately has no Tk dependency.  The GUI can use the structured
result to decide which message to show and when to start geometry processing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

import numpy as np

from .models import MeshLevel, ObjAsset, PreparedGeometry
from .paint import mesh_fingerprint


LEGACY_BUNDLE_SCHEMA = "obj-adjuster.project-bundle.v1"
BUNDLE_SCHEMA = "obj-adjuster.project-bundle.v2"
CURRENT_PROJECT_SCHEMA = "obj-adjuster.project.v13"
PROJECT_JSON_NAME = "project.json"
SOURCE_OBJ_NAME = "source.obj"
SOURCE_GLB_NAME = "source.glb"
SUPPORTED_SOURCE_FORMATS = {"obj": ".obj", "glb": ".glb"}
PREPARED_GEOMETRY_NAME = "prepared_geometry.npz"
MAX_PROJECT_JSON_BYTES = 32 * 1024 * 1024
MAX_SNAPSHOT_METADATA_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024
PREPARED_SNAPSHOT_SCHEMA = "obj-adjuster.prepared-geometry.v1"

# Exact snapshots are an untrusted cache, not an authority that may widen the
# raw-model import budget.  Keep these absolute decoder limits independent of
# GUI labels and source-file suffixes so a renamed or externally edited bundle
# cannot allocate arrays beyond the supported large-model route.
_HARD_SNAPSHOT_SOURCE_VERTEX_LIMIT = 3_000_000
_HARD_SNAPSHOT_SOURCE_FACE_LIMIT = 5_000_000
_HARD_SNAPSHOT_LEVEL_VERTEX_LIMIT = 3_000_000
_HARD_SNAPSHOT_LEVEL_FACE_LIMIT = 3_000_000
_HARD_LARGE_SNAPSHOT_FACE_THRESHOLD = 3_000_000
_HARD_LARGE_SNAPSHOT_FINAL_FACE_LIMIT = 450_000

_SNAPSHOT_REQUIRED_ARRAYS = frozenset(
    {
        "metadata",
        "asset_vertices",
        "asset_colors",
        "asset_faces",
        "asset_face_part_ids",
        "final_vertices_unit",
        "final_faces",
        "final_vertex_colors",
        "final_areas_unit",
        "final_face_part_ids",
        "final_face_provenance",
        "preview_vertices_unit",
        "preview_faces",
        "preview_vertex_colors",
        "preview_areas_unit",
        "preview_face_part_ids",
        "preview_face_provenance",
        "source_dimensions_unit",
    }
)
_SNAPSHOT_OPTIONAL_ARRAYS = frozenset({"final_neighbors", "preview_neighbors"})
_SNAPSHOT_ARRAYS = _SNAPSHOT_REQUIRED_ARRAYS | _SNAPSHOT_OPTIONAL_ARRAYS

_PROJECT_SCHEMA_RE = re.compile(r"^obj-adjuster\.project\.v[1-9][0-9]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_INVALID_WINDOWS_NAME_CHARS = frozenset('<>:"/\\|?*')
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


class ProjectLoadState(str, Enum):
    """Whether the selected project already has a verified bundled source."""

    READY = "ready"
    READY_REQUIRES_GEOMETRY_VERIFICATION = (
        "ready_requires_geometry_verification"
    )
    NEEDS_SOURCE_OBJ = "needs_source_obj"


class GeometryRestoreState(str, Enum):
    """Safety contract for face-indexed manual records."""

    NOT_REQUIRED = "not_required"
    REBUILD_AND_VERIFY = "rebuild_and_verify"
    SNAPSHOT_AVAILABLE_UNVERIFIED = "snapshot_available_unverified"


class ProjectBundleError(ValueError):
    """Stable, GUI-localizable failure raised at a bundle trust boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: Path | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.path = path
        self.details = dict(details or {})


@dataclass(frozen=True)
class ProjectBundleSaveResult:
    folder: Path
    project_json: Path
    source_obj: Path
    source_sha256: str
    source_size_bytes: int
    geometry_restore_state: GeometryRestoreState
    source_format: str = "obj"
    expected_mesh_fingerprints: Mapping[str, str] = field(default_factory=dict)
    prepared_geometry_snapshot: Path | None = None
    reference_image: Path | None = None
    omitted_private_fields: tuple[str, ...] = ()

    @property
    def source_asset(self) -> Path:
        """Generic source-model alias; ``source_obj`` remains API-compatible."""

        return self.source_obj


@dataclass(frozen=True)
class PreparedGeometrySnapshotResult:
    prepared: PreparedGeometry
    geometry_key: tuple[object, ...]
    source_sha256: str
    paint_mesh_fingerprint: str


@dataclass(frozen=True)
class PreparedGeometrySnapshotWorkload:
    """Array counts read from NPY headers without expanding mesh payloads."""

    asset_vertex_count: int
    asset_face_count: int
    final_face_count: int


@dataclass(frozen=True)
class ProjectLoadResult:
    """Validated project information ready for GUI wiring.

    ``project_data`` is the historical inner project mapping accepted by the
    existing settings loader.  For a portable bundle, ``source_obj`` is fully
    resolved and its bytes have already passed the manifest checks.  A legacy
    JSON deliberately returns ``NEEDS_SOURCE_OBJ`` and never follows its stale
    absolute path.
    """

    state: ProjectLoadState
    project_data: Mapping[str, object]
    project_json: Path
    bundle_folder: Path | None
    source_obj: Path | None
    source_sha256: str | None
    source_size_bytes: int | None
    geometry_restore_state: GeometryRestoreState
    source_format: str | None = None
    expected_mesh_fingerprints: Mapping[str, str] = field(default_factory=dict)
    prepared_geometry_snapshot: Path | None = None
    prepared_geometry_snapshot_sha256: str | None = None
    prepared_geometry_snapshot_size_bytes: int | None = None
    reference_image: Path | None = None
    legacy_source_name: str | None = None
    ignored_features: tuple[str, ...] = ()
    geometry_restore_reason: str | None = None
    snapshot_geometry_key: tuple[object, ...] | None = None

    @property
    def source_asset(self) -> Path | None:
        """Generic source-model alias; ``source_obj`` remains API-compatible."""

        return self.source_obj

    @property
    def source_ready(self) -> bool:
        return (
            self.state
            in {
                ProjectLoadState.READY,
                ProjectLoadState.READY_REQUIRES_GEOMETRY_VERIFICATION,
            }
            and self.source_obj is not None
        )

    @property
    def manual_geometry_verification_required(self) -> bool:
        return self.geometry_restore_state is not GeometryRestoreState.NOT_REQUIRED

    def verify_prepared_mesh_fingerprint(
        self,
        actual_fingerprint: str,
        *,
        scope: str = "manual_paint",
    ) -> bool:
        """Verify rebuilt/snapshotted face identity before restoring a record.

        A mismatch is a hard safety failure.  It can be caused by a different
        OBJ or by nondeterministic preprocessing; in either case applying the
        saved face indices would paint the wrong triangles.
        """

        expected = self.expected_mesh_fingerprints.get(scope)
        if expected is None:
            return True
        actual = str(actual_fingerprint).strip()
        if actual != expected:
            raise ProjectBundleError(
                "prepared_geometry_fingerprint_mismatch",
                "Prepared geometry does not match the saved face-index contract; "
                "manual edits were not restored.",
                path=self.source_obj,
                details={"scope": scope, "expected": expected, "actual": actual},
            )
        return True

    def load_exact_prepared_geometry(
        self,
        *,
        expected_geometry_key: tuple[object, ...],
    ) -> PreparedGeometrySnapshotResult:
        """Decode and fully verify the bundled exact geometry cache."""

        if self.prepared_geometry_snapshot is None:
            raise ProjectBundleError(
                "prepared_geometry_snapshot_missing",
                "This project has no exact prepared-geometry snapshot.",
                path=self.project_json,
            )
        if self.source_obj is None or self.source_sha256 is None:
            raise ProjectBundleError(
                "source_obj_required",
                "The bundled source model must be verified before its snapshot.",
                path=self.project_json,
            )
        manual_fingerprint = self.expected_mesh_fingerprints.get("manual_paint")
        return decode_prepared_geometry_snapshot(
            self.prepared_geometry_snapshot,
            bundled_source_obj=self.source_obj,
            expected_source_sha256=self.source_sha256,
            expected_geometry_key=expected_geometry_key,
            expected_paint_mesh_fingerprint=manual_fingerprint,
            expected_snapshot_sha256=self.prepared_geometry_snapshot_sha256,
            expected_snapshot_size_bytes=(
                self.prepared_geometry_snapshot_size_bytes
            ),
        )

    def inspect_prepared_geometry_workload(
        self,
    ) -> PreparedGeometrySnapshotWorkload:
        """Inspect exact-snapshot mesh sizes before allocating their arrays."""

        if self.prepared_geometry_snapshot is None:
            raise ProjectBundleError(
                "prepared_geometry_snapshot_missing",
                "This project has no exact prepared-geometry snapshot.",
                path=self.project_json,
            )
        return inspect_prepared_geometry_snapshot_workload(
            self.prepared_geometry_snapshot
        )


def _error(code: str, message: str, path: Path | None = None, **details: object):
    raise ProjectBundleError(code, message, path=path, details=details)


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = int(getattr(info, "st_file_attributes", 0))
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _assert_not_link_or_reparse(path: Path, *, code: str) -> None:
    if path.is_symlink() or _is_reparse_point(path):
        _error(code, "Symbolic links and reparse points are not accepted.", path)


def _validate_member_name(name: str, *, code: str = "unsafe_member_name") -> str:
    value = str(name)
    if not value or value in {".", ".."}:
        _error(code, "A project member name is empty or reserved.")
    if value != Path(value).name or "/" in value or "\\" in value:
        _error(code, "A project member name must not contain a path.", name=value)
    if value[-1] in {" ", "."}:
        _error(code, "A project member name must not end with a space or dot.", name=value)
    if any(ord(character) < 32 for character in value):
        _error(code, "A project member name contains a control character.", name=value)
    if any(character in _INVALID_WINDOWS_NAME_CHARS for character in value):
        _error(code, "A project member name contains a reserved character.", name=value)
    stem = value.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        _error(code, "A project member name is reserved by Windows.", name=value)
    return value


def _safe_relative_member(value: object, *, suffix: str) -> str:
    if not isinstance(value, str) or not value:
        _error("unsafe_relative_path", "A bundle member path is missing.")
    if "\\" in value:
        _error("unsafe_relative_path", "Bundle member paths must use portable names.")
    pure = PurePosixPath(value)
    if pure.is_absolute() or len(pure.parts) != 1 or pure.parts[0] in {".", ".."}:
        _error("unsafe_relative_path", "A bundle member path escapes its folder.")
    name = _validate_member_name(pure.name)
    if Path(name).suffix.lower() != suffix.lower():
        _error("unexpected_member_type", f"Expected a {suffix} bundle member.")
    return name


def _assert_regular_file(path: Path, *, suffix: str, code: str) -> None:
    if not path.exists():
        _error(code, "The selected file does not exist.", path)
    _assert_not_link_or_reparse(path, code="unsafe_link_or_reparse")
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        _error(code, f"The selected file cannot be inspected: {exc}", path)
    if not stat.S_ISREG(mode):
        _error(code, "The selected path is not a regular file.", path)
    if path.suffix.lower() != suffix.lower():
        _error("unexpected_member_type", f"Expected a {suffix} file.", path)


def _source_format_for_path(path: Path | str) -> str:
    suffix = Path(path).suffix.lower()
    for source_format, expected_suffix in SUPPORTED_SOURCE_FORMATS.items():
        if suffix == expected_suffix:
            return source_format
    _error(
        "unsupported_source_format",
        "Only Wavefront OBJ and binary GLB source models are supported.",
        Path(path),
        suffix=suffix,
    )


def _source_member_name(source_format: str) -> str:
    if source_format == "obj":
        return SOURCE_OBJ_NAME
    if source_format == "glb":
        return SOURCE_GLB_NAME
    _error("unsupported_source_format", "The project source format is invalid.")


def _assert_source_file(path: Path, *, code: str) -> str:
    source_format = _source_format_for_path(path)
    _assert_regular_file(
        path,
        suffix=SUPPORTED_SOURCE_FORMATS[source_format],
        code=code,
    )
    return source_format


def _looks_absolute_path(value: str) -> bool:
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        return value.lower().startswith("file://")
    if value.startswith(("/", "\\", "file://", "file:\\")):
        return True
    windows = PureWindowsPath(value)
    return windows.is_absolute() or bool(windows.drive)


def _validate_json_value(value: object, trail: tuple[str, ...] = ()) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and _looks_absolute_path(value):
            _error(
                "absolute_path_in_project",
                "Shareable project data must not contain an absolute path.",
                field=".".join(trail),
            )
        return
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            _error("invalid_project_json", "Project data contains a non-finite number.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, trail + (str(index),))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                _error("invalid_project_json", "Project object keys must be strings.")
            _validate_json_value(item, trail + (key,))
        return
    _error(
        "invalid_project_json",
        f"Project data contains a non-JSON value: {type(value).__name__}.",
    )


def _project_schema(data: Mapping[str, object], *, for_save: bool) -> str:
    schema = str(data.get("schema", "")).strip()
    if for_save:
        if schema != CURRENT_PROJECT_SCHEMA:
            _error(
                "unsupported_project_schema",
                f"Only {CURRENT_PROJECT_SCHEMA} can be saved as a new bundle.",
                schema=schema,
            )
    elif schema and not _PROJECT_SCHEMA_RE.fullmatch(schema):
        _error(
            "unsupported_project_schema",
            "This JSON is not a supported ChromaMatter project.",
            schema=schema,
        )
    return schema


def _portable_project_copy(
    project_data: Mapping[str, object],
) -> tuple[dict[str, object], tuple[str, ...]]:
    if not isinstance(project_data, Mapping):
        _error("invalid_project_json", "Project data must be a JSON object.")
    try:
        copied = json.loads(
            json.dumps(dict(project_data), ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        _error("invalid_project_json", f"Project data is not JSON serializable: {exc}")
    if not isinstance(copied, dict):
        _error("invalid_project_json", "Project data must be a JSON object.")
    _project_schema(copied, for_save=True)
    omitted: list[str] = []
    # Manual split/joint editing has been removed from the public r25 workflow.
    # Do not invisibly carry those geometry-changing records into a new bundle.
    for field_name in (
        "obj_path",
        "reference_path",
        "manual_parts",
        "manual_joint",
    ):
        if field_name in copied:
            copied.pop(field_name, None)
            omitted.append(field_name)
    _validate_json_value(copied)
    return copied, tuple(omitted)


def _legacy_project_copy(project_data: Mapping[str, object]) -> dict[str, object]:
    copied = json.loads(json.dumps(dict(project_data), ensure_ascii=False))
    if isinstance(copied, dict):
        # The name is returned separately as a non-authoritative hint.  Never
        # feed an obsolete absolute path back into the old GUI loader.
        copied.pop("obj_path", None)
        copied.pop("reference_path", None)
        copied.pop("manual_parts", None)
        copied.pop("manual_joint", None)
    return copied


def _fingerprint_contracts(project_data: Mapping[str, object]) -> dict[str, str]:
    contracts: dict[str, str] = {}
    # Public r25 restores manual paint only.  Historical manual part/joint
    # records are intentionally reported and ignored rather than invisibly
    # mutating geometry after their UI was removed.
    sources = (("manual_paint", "mesh_fingerprint"),)
    for scope, field_name in sources:
        record = project_data.get(scope)
        if not isinstance(record, Mapping):
            continue
        fingerprint = record.get(field_name)
        if isinstance(fingerprint, str) and fingerprint.strip():
            contracts[scope] = fingerprint.strip()
    return contracts


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _sha256_open_handle(handle: Any) -> tuple[str, int]:
    """Hash the bytes owned by one already-open regular-file handle."""

    handle.seek(0)
    digest = hashlib.sha256()
    size = 0
    while True:
        block = handle.read(1024 * 1024)
        if not block:
            break
        digest.update(block)
        size += len(block)
    return digest.hexdigest(), size


def _copy_regular_file(source: Path, destination: Path) -> tuple[str, int]:
    """Copy bytes while calculating the digest of the actual bundled member."""

    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while True:
            block = reader.read(1024 * 1024)
            if not block:
                break
            writer.write(block)
            digest.update(block)
            size += len(block)
        writer.flush()
        os.fsync(writer.fileno())
    try:
        shutil.copystat(source, destination, follow_symlinks=False)
    except OSError:
        # Metadata preservation is helpful but not part of the content trust
        # contract.  The copied bytes and SHA-256 are authoritative.
        pass
    return digest.hexdigest(), size


def _write_json_exclusive(path: Path, value: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _metadata_json_value(value: object, trail: tuple[str, ...] = ()) -> object:
    """Convert trusted runtime metadata to JSON without pickle or paths."""

    if value is None or isinstance(value, (bool, str, int)):
        if isinstance(value, str) and _looks_absolute_path(value):
            _error(
                "absolute_path_in_snapshot_metadata",
                "Prepared-geometry metadata must not contain absolute paths.",
                field=".".join(trail),
            )
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            _error("invalid_snapshot_metadata", "Snapshot metadata is not finite.")
        return value
    if isinstance(value, np.generic):
        return _metadata_json_value(value.item(), trail)
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            _error("unsafe_snapshot_dtype", "Object arrays are not accepted.")
        return _metadata_json_value(value.tolist(), trail)
    if isinstance(value, (list, tuple)):
        return [
            _metadata_json_value(item, trail + (str(index),))
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _error(
                    "invalid_snapshot_metadata",
                    "Snapshot metadata keys must be strings.",
                )
            result[key] = _metadata_json_value(item, trail + (key,))
        return result
    _error(
        "invalid_snapshot_metadata",
        f"Unsupported snapshot metadata value: {type(value).__name__}.",
    )


def _normal_geometry_key(value: object) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        _error("invalid_geometry_key", "The prepared geometry key must be a sequence.")
    normal = _metadata_json_value(list(value), ("geometry_key",))
    if not isinstance(normal, list):
        _error("invalid_geometry_key", "The prepared geometry key is invalid.")
    for item in normal:
        if item is not None and not isinstance(item, (bool, int, float, str)):
            _error(
                "invalid_geometry_key",
                "The prepared geometry key may contain only scalar values.",
            )
    return tuple(normal)


def _level_arrays(prefix: str, level: MeshLevel) -> dict[str, np.ndarray]:
    arrays = {
        f"{prefix}_vertices_unit": np.ascontiguousarray(
            level.vertices_unit, dtype=np.float64
        ),
        f"{prefix}_faces": np.ascontiguousarray(level.faces, dtype=np.int32),
        f"{prefix}_vertex_colors": np.ascontiguousarray(
            level.vertex_colors, dtype=np.float64
        ),
        f"{prefix}_areas_unit": np.ascontiguousarray(
            level.areas_unit, dtype=np.float64
        ),
        f"{prefix}_face_part_ids": np.ascontiguousarray(
            level.face_part_ids, dtype=np.int32
        ),
        f"{prefix}_face_provenance": np.ascontiguousarray(
            level.face_provenance, dtype=np.uint8
        ),
    }
    if level.neighbors is not None:
        arrays[f"{prefix}_neighbors"] = np.ascontiguousarray(
            level.neighbors, dtype=np.int32
        )
    return arrays


def encode_prepared_geometry_snapshot(
    destination: Path | str,
    prepared: PreparedGeometry,
    *,
    source_sha256: str,
    geometry_key: tuple[object, ...],
    expected_paint_mesh_fingerprint: str | None = None,
) -> tuple[str, int, tuple[object, ...], str]:
    """Write a pickle-free exact PreparedGeometry cache.

    The returned tuple is ``(file_sha256, size, geometry_key,
    paint_mesh_fingerprint)``.  The destination is created exclusively.
    """

    path = Path(destination)
    if path.exists() or path.is_symlink():
        _error("snapshot_destination_exists", "Snapshot destination exists.", path)
    source_digest = str(source_sha256).lower()
    if not _SHA256_RE.fullmatch(source_digest):
        _error("invalid_sha256_manifest", "The source SHA-256 is invalid.")
    asset_digest = str(prepared.source.sha256).lower()
    if asset_digest != source_digest:
        _error(
            "snapshot_source_sha256_mismatch",
            "Prepared geometry was not built from the bundled source-model bytes.",
            path,
            asset=asset_digest,
            source=source_digest,
        )
    normalized_key = _normal_geometry_key(geometry_key)
    paint_fingerprint = mesh_fingerprint(prepared.final)
    if (
        expected_paint_mesh_fingerprint is not None
        and paint_fingerprint != str(expected_paint_mesh_fingerprint)
    ):
        _error(
            "prepared_geometry_fingerprint_mismatch",
            "Prepared geometry does not match the saved manual paint.",
            path,
        )

    metadata: dict[str, object] = {
        "schema": PREPARED_SNAPSHOT_SCHEMA,
        "source_sha256": source_digest,
        "geometry_key": list(normalized_key),
        "paint_mesh_fingerprint": paint_fingerprint,
        "asset": {
            "original_vertex_count": int(prepared.source.original_vertex_count),
            "original_face_count": int(prepared.source.original_face_count),
            "warnings": list(prepared.source.warnings),
            "part_names": list(prepared.source.part_names),
            "part_keys": list(prepared.source.part_keys),
            "part_face_counts": list(prepared.source.part_face_counts),
            "part_vertex_counts": list(prepared.source.part_vertex_counts),
            "part_marker_kind": prepared.source.part_marker_kind,
            "has_explicit_parts": bool(prepared.source.has_explicit_parts),
            "import_metadata": dict(prepared.source.import_metadata),
        },
        "final": {
            "part_names": list(prepared.final.part_names),
            "part_keys": list(prepared.final.part_keys),
            "has_neighbors": prepared.final.neighbors is not None,
        },
        "preview": {
            "part_names": list(prepared.preview.part_names),
            "part_keys": list(prepared.preview.part_keys),
            "has_neighbors": prepared.preview.neighbors is not None,
        },
        "prepared": {
            "clean_vertex_count": int(prepared.clean_vertex_count),
            "clean_face_count": int(prepared.clean_face_count),
            "removed_vertices": int(prepared.removed_vertices),
            "removed_faces": int(prepared.removed_faces),
            "topology": dict(prepared.topology),
            "source_area_unit": float(prepared.source_area_unit),
            "source_volume_unit": float(prepared.source_volume_unit),
            "simplified_area_unit": float(prepared.simplified_area_unit),
            "simplified_volume_unit": float(prepared.simplified_volume_unit),
            "warnings": list(prepared.warnings),
            "part_names": list(prepared.part_names),
            "part_keys": list(prepared.part_keys),
            "part_stats": prepared.part_stats,
            "assembly": prepared.assembly,
        },
    }
    safe_metadata = _metadata_json_value(metadata)
    encoded_metadata = json.dumps(
        safe_metadata,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded_metadata) > MAX_SNAPSHOT_METADATA_BYTES:
        _error(
            "snapshot_metadata_too_large",
            "Prepared-geometry metadata is too large to bundle safely.",
            path,
        )

    arrays: dict[str, np.ndarray] = {
        "metadata": np.frombuffer(encoded_metadata, dtype=np.uint8),
        "asset_vertices": np.ascontiguousarray(
            prepared.source.vertices, dtype=np.float64
        ),
        "asset_colors": np.ascontiguousarray(
            prepared.source.colors, dtype=np.float64
        ),
        "asset_faces": np.ascontiguousarray(
            prepared.source.faces, dtype=np.int32
        ),
        "asset_face_part_ids": np.ascontiguousarray(
            prepared.source.face_part_ids, dtype=np.int32
        ),
        "source_dimensions_unit": np.ascontiguousarray(
            prepared.source_dimensions_unit, dtype=np.float64
        ),
        **_level_arrays("final", prepared.final),
        **_level_arrays("preview", prepared.preview),
    }
    with path.open("xb") as handle:
        np.savez_compressed(handle, **arrays)
        handle.flush()
        os.fsync(handle.fileno())
    digest, size = _sha256(path)
    return digest, size, normalized_key, paint_fingerprint


def _check_snapshot_archive_members(
    archive: zipfile.ZipFile,
    path: Path,
) -> None:
    names = [record.filename for record in archive.infolist()]
    if len(names) != len(set(names)):
        _error("duplicate_snapshot_member", "Snapshot members are duplicated.", path)
    expected_names = {f"{key}.npy" for key in _SNAPSHOT_ARRAYS}
    actual_names = set(names)
    required_names = {f"{key}.npy" for key in _SNAPSHOT_REQUIRED_ARRAYS}
    if not required_names.issubset(actual_names) or not actual_names.issubset(
        expected_names
    ):
        _error(
            "invalid_snapshot_members",
            "The prepared snapshot contains missing or unexpected arrays.",
            path,
        )
    uncompressed = 0
    for record in archive.infolist():
        if record.flag_bits & 0x1:
            _error("encrypted_snapshot", "Encrypted snapshots are not accepted.", path)
        uncompressed += int(record.file_size)
        if uncompressed > MAX_SNAPSHOT_UNCOMPRESSED_BYTES:
            _error("snapshot_too_large", "The prepared snapshot is too large.", path)


@dataclass(frozen=True)
class _SnapshotArraySpec:
    dtype: np.dtype[Any]
    ndim: int
    shape_tail: tuple[int, ...] = ()
    exact_shape: tuple[int, ...] | None = None


@dataclass(frozen=True)
class _SnapshotArrayHeader:
    shape: tuple[int, ...]
    dtype: np.dtype[Any]
    data_offset: int
    member_size: int


@dataclass(frozen=True)
class _SnapshotHeaderLayout:
    workload: PreparedGeometrySnapshotWorkload
    headers: Mapping[str, _SnapshotArrayHeader]


_SNAPSHOT_ARRAY_SPECS: Mapping[str, _SnapshotArraySpec] = {
    "metadata": _SnapshotArraySpec(np.dtype(np.uint8), 1),
    "asset_vertices": _SnapshotArraySpec(np.dtype(np.float64), 2, (3,)),
    "asset_colors": _SnapshotArraySpec(np.dtype(np.float64), 2, (3,)),
    "asset_faces": _SnapshotArraySpec(np.dtype(np.int32), 2, (3,)),
    "asset_face_part_ids": _SnapshotArraySpec(np.dtype(np.int32), 1),
    "final_vertices_unit": _SnapshotArraySpec(np.dtype(np.float64), 2, (3,)),
    "final_faces": _SnapshotArraySpec(np.dtype(np.int32), 2, (3,)),
    "final_vertex_colors": _SnapshotArraySpec(np.dtype(np.float64), 2, (3,)),
    "final_areas_unit": _SnapshotArraySpec(np.dtype(np.float64), 1),
    "final_face_part_ids": _SnapshotArraySpec(np.dtype(np.int32), 1),
    "final_face_provenance": _SnapshotArraySpec(np.dtype(np.uint8), 1),
    "final_neighbors": _SnapshotArraySpec(np.dtype(np.int32), 2, (3,)),
    "preview_vertices_unit": _SnapshotArraySpec(np.dtype(np.float64), 2, (3,)),
    "preview_faces": _SnapshotArraySpec(np.dtype(np.int32), 2, (3,)),
    "preview_vertex_colors": _SnapshotArraySpec(np.dtype(np.float64), 2, (3,)),
    "preview_areas_unit": _SnapshotArraySpec(np.dtype(np.float64), 1),
    "preview_face_part_ids": _SnapshotArraySpec(np.dtype(np.int32), 1),
    "preview_face_provenance": _SnapshotArraySpec(np.dtype(np.uint8), 1),
    "preview_neighbors": _SnapshotArraySpec(np.dtype(np.int32), 2, (3,)),
    "source_dimensions_unit": _SnapshotArraySpec(
        np.dtype(np.float64),
        1,
        exact_shape=(3,),
    ),
}


def _snapshot_npy_header(
    archive: zipfile.ZipFile,
    path: Path,
    name: str,
) -> _SnapshotArrayHeader:
    """Read and type-check one NPY member without expanding its payload."""

    spec = _SNAPSHOT_ARRAY_SPECS[name]
    member = f"{name}.npy"
    try:
        record = archive.getinfo(member)
        with archive.open(record, "r") as stream:
            version = np.lib.format.read_magic(stream)
            if version == (1, 0):
                shape, _fortran_order, dtype = (
                    np.lib.format.read_array_header_1_0(stream)
                )
            elif version == (2, 0):
                shape, _fortran_order, dtype = (
                    np.lib.format.read_array_header_2_0(stream)
                )
            else:
                _error(
                    "invalid_snapshot_array",
                    f"Unsupported NPY header version for {name}: {version}",
                    path,
                )
            data_offset = int(stream.tell())
    except ProjectBundleError:
        raise
    except (KeyError, OSError, ValueError, EOFError) as exc:
        _error(
            "invalid_snapshot_array",
            f"Cannot read snapshot array header {name}: {exc}",
            path,
        )

    normalized_shape = tuple(int(value) for value in shape)
    normalized_dtype = np.dtype(dtype)
    if normalized_dtype.hasobject or normalized_dtype.fields is not None:
        _error("unsafe_snapshot_dtype", f"Unsafe dtype is forbidden for {name}.", path)
    if normalized_dtype != spec.dtype or normalized_dtype.itemsize != spec.dtype.itemsize:
        _error(
            "invalid_snapshot_dtype",
            f"Snapshot array {name} must have dtype {spec.dtype}.",
            path,
        )
    if len(normalized_shape) != spec.ndim:
        _error(
            "invalid_snapshot_shape",
            f"Snapshot array {name} has the wrong rank.",
            path,
        )
    if spec.shape_tail and normalized_shape[-len(spec.shape_tail) :] != spec.shape_tail:
        _error(
            "invalid_snapshot_shape",
            f"Snapshot array {name} has the wrong trailing dimensions.",
            path,
        )
    if spec.exact_shape is not None and normalized_shape != spec.exact_shape:
        _error(
            "invalid_snapshot_shape",
            f"Snapshot array {name} has the wrong shape.",
            path,
        )
    if any(value < 0 for value in normalized_shape):
        _error(
            "invalid_snapshot_shape",
            f"Snapshot array {name} has a negative dimension.",
            path,
        )
    return _SnapshotArrayHeader(
        shape=normalized_shape,
        dtype=normalized_dtype,
        data_offset=data_offset,
        member_size=int(record.file_size),
    )


def _snapshot_array_payload_size(header: _SnapshotArrayHeader) -> int:
    elements = 1
    for dimension in header.shape:
        elements *= dimension
    return elements * int(header.dtype.itemsize)


def _header_length(headers: Mapping[str, _SnapshotArrayHeader], name: str) -> int:
    return int(headers[name].shape[0])


def _require_zero_or_equal(
    headers: Mapping[str, _SnapshotArrayHeader],
    name: str,
    expected: int,
    path: Path,
) -> None:
    actual = _header_length(headers, name)
    if actual not in {0, expected}:
        _error(
            "invalid_snapshot_shape",
            f"Snapshot array {name} has an inconsistent length.",
            path,
            expected=expected,
            actual=actual,
        )


def _inspect_snapshot_headers_archive(
    archive: zipfile.ZipFile,
    path: Path,
) -> _SnapshotHeaderLayout:
    """Validate every NPY header and all count relationships before np.load."""

    _check_snapshot_archive_members(archive, path)
    member_names = {record.filename for record in archive.infolist()}
    array_names = set(_SNAPSHOT_REQUIRED_ARRAYS)
    array_names.update(
        name
        for name in _SNAPSHOT_OPTIONAL_ARRAYS
        if f"{name}.npy" in member_names
    )
    headers = {
        name: _snapshot_npy_header(archive, path, name)
        for name in sorted(array_names)
    }

    metadata_size = _header_length(headers, "metadata")
    if metadata_size > MAX_SNAPSHOT_METADATA_BYTES:
        _error(
            "snapshot_metadata_too_large",
            "Snapshot metadata is too large.",
            path,
            maximum=MAX_SNAPSHOT_METADATA_BYTES,
            actual=metadata_size,
        )

    asset_vertices = _header_length(headers, "asset_vertices")
    asset_faces = _header_length(headers, "asset_faces")
    final_vertices = _header_length(headers, "final_vertices_unit")
    final_faces = _header_length(headers, "final_faces")
    preview_vertices = _header_length(headers, "preview_vertices_unit")
    preview_faces = _header_length(headers, "preview_faces")
    workload = PreparedGeometrySnapshotWorkload(
        asset_vertex_count=asset_vertices,
        asset_face_count=asset_faces,
        final_face_count=final_faces,
    )
    _enforce_snapshot_workload_limits(workload, path)
    if (
        final_vertices > _HARD_SNAPSHOT_LEVEL_VERTEX_LIMIT
        or final_faces > _HARD_SNAPSHOT_LEVEL_FACE_LIMIT
        or preview_vertices > _HARD_SNAPSHOT_LEVEL_VERTEX_LIMIT
        or preview_faces > _HARD_SNAPSHOT_LEVEL_FACE_LIMIT
    ):
        _error(
            "snapshot_workload_too_large",
            "The prepared snapshot levels exceed the supported exact-cache workload.",
            path,
            final_vertices=final_vertices,
            final_faces=final_faces,
            preview_vertices=preview_vertices,
            preview_faces=preview_faces,
            maximum_level_vertices=_HARD_SNAPSHOT_LEVEL_VERTEX_LIMIT,
            maximum_level_faces=_HARD_SNAPSHOT_LEVEL_FACE_LIMIT,
        )
    if preview_faces > final_faces:
        _error(
            "invalid_snapshot_shape",
            "Preview face count cannot exceed final face count.",
            path,
            final_faces=final_faces,
            preview_faces=preview_faces,
        )

    if _header_length(headers, "asset_colors") != asset_vertices:
        _error("invalid_snapshot_shape", "Asset vertex/color lengths differ.", path)
    _require_zero_or_equal(headers, "asset_face_part_ids", asset_faces, path)
    for prefix, vertex_count, face_count in (
        ("final", final_vertices, final_faces),
        ("preview", preview_vertices, preview_faces),
    ):
        if _header_length(headers, f"{prefix}_vertex_colors") != vertex_count:
            _error(
                "invalid_snapshot_shape",
                f"{prefix} vertex/color lengths differ.",
                path,
            )
        if _header_length(headers, f"{prefix}_areas_unit") != face_count:
            _error(
                "invalid_snapshot_shape",
                f"{prefix} face/area lengths differ.",
                path,
            )
        _require_zero_or_equal(
            headers,
            f"{prefix}_face_part_ids",
            face_count,
            path,
        )
        _require_zero_or_equal(
            headers,
            f"{prefix}_face_provenance",
            face_count,
            path,
        )
        neighbor_name = f"{prefix}_neighbors"
        if neighbor_name in headers and _header_length(headers, neighbor_name) != face_count:
            _error(
                "invalid_snapshot_shape",
                f"{prefix} neighbors have the wrong length.",
                path,
            )

    # A forged shape with a tiny member body must fail before NumPy can try to
    # allocate the declared array.  This check is intentionally after the hard
    # count checks so a shape bomb receives the stable workload error.
    for name, header in headers.items():
        expected_member_size = (
            header.data_offset + _snapshot_array_payload_size(header)
        )
        if header.member_size != expected_member_size:
            _error(
                "invalid_snapshot_array_size",
                f"Snapshot array {name} payload size does not match its header.",
                path,
                expected=expected_member_size,
                actual=header.member_size,
            )
    return _SnapshotHeaderLayout(workload=workload, headers=headers)


def _inspect_snapshot_workload_archive(
    archive: zipfile.ZipFile,
    path: Path | None = None,
) -> PreparedGeometrySnapshotWorkload:
    """Compatibility wrapper returning the public three-count summary."""

    return _inspect_snapshot_headers_archive(
        archive,
        path or Path(PREPARED_GEOMETRY_NAME),
    ).workload


def inspect_prepared_geometry_snapshot_workload(
    snapshot_path: Path | str,
) -> PreparedGeometrySnapshotWorkload:
    """Read exact-snapshot mesh counts without decompressing the mesh arrays."""

    snapshot = Path(snapshot_path)
    _assert_regular_file(
        snapshot,
        suffix=".npz",
        code="prepared_geometry_snapshot_missing",
    )
    try:
        with snapshot.open("rb") as handle, zipfile.ZipFile(handle, "r") as archive:
            return _inspect_snapshot_headers_archive(archive, snapshot).workload
    except ProjectBundleError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        _error(
            "invalid_prepared_snapshot",
            f"The prepared snapshot is invalid: {exc}",
            snapshot,
        )


def _enforce_snapshot_workload_limits(
    workload: PreparedGeometrySnapshotWorkload,
    snapshot: Path,
) -> None:
    exceeds_limit = (
        workload.asset_vertex_count > _HARD_SNAPSHOT_SOURCE_VERTEX_LIMIT
        or workload.asset_face_count > _HARD_SNAPSHOT_SOURCE_FACE_LIMIT
        or workload.final_face_count > _HARD_SNAPSHOT_LEVEL_FACE_LIMIT
        or (
            workload.asset_face_count > _HARD_LARGE_SNAPSHOT_FACE_THRESHOLD
            and workload.final_face_count > _HARD_LARGE_SNAPSHOT_FINAL_FACE_LIMIT
        )
    )
    if exceeds_limit:
        _error(
            "snapshot_workload_too_large",
            "The prepared snapshot exceeds the supported exact-cache workload.",
            snapshot,
            asset_vertices=workload.asset_vertex_count,
            asset_faces=workload.asset_face_count,
            final_faces=workload.final_face_count,
            maximum_asset_vertices=_HARD_SNAPSHOT_SOURCE_VERTEX_LIMIT,
            maximum_asset_faces=_HARD_SNAPSHOT_SOURCE_FACE_LIMIT,
            maximum_final_faces=_HARD_SNAPSHOT_LEVEL_FACE_LIMIT,
            large_snapshot_threshold=_HARD_LARGE_SNAPSHOT_FACE_THRESHOLD,
            maximum_large_snapshot_final_faces=(
                _HARD_LARGE_SNAPSHOT_FINAL_FACE_LIMIT
            ),
        )


@contextmanager
def _validated_snapshot_arrays(
    snapshot: Path,
    *,
    expected_sha256: str | None,
    expected_size_bytes: int | None,
):
    """Yield lazy arrays from a private, verified byte-for-byte frozen copy."""

    normalized_digest: str | None = None
    if expected_sha256 is not None:
        normalized_digest = str(expected_sha256).lower()
        if not _SHA256_RE.fullmatch(normalized_digest):
            _error(
                "invalid_sha256_manifest",
                "The prepared snapshot SHA-256 value is invalid.",
                snapshot,
            )
    if expected_size_bytes is not None and (
        isinstance(expected_size_bytes, bool)
        or not isinstance(expected_size_bytes, int)
        or expected_size_bytes < 0
    ):
        _error(
            "invalid_size_manifest",
            "The prepared snapshot size value is invalid.",
            snapshot,
        )

    try:
        with tempfile.TemporaryFile(mode="w+b") as frozen:
            digest = hashlib.sha256()
            actual_size = 0
            with snapshot.open("rb") as source_handle:
                opened_status = os.fstat(source_handle.fileno())
                if not stat.S_ISREG(opened_status.st_mode):
                    _error(
                        "prepared_geometry_snapshot_missing",
                        "The prepared snapshot is not a regular file.",
                        snapshot,
                    )
                while True:
                    block = source_handle.read(1024 * 1024)
                    if not block:
                        break
                    frozen.write(block)
                    digest.update(block)
                    actual_size += len(block)
            actual_digest = digest.hexdigest()
            if actual_size != int(opened_status.st_size):
                _error(
                    "bundle_member_size_mismatch",
                    "The prepared snapshot changed while it was being copied.",
                    snapshot,
                    expected=int(opened_status.st_size),
                    actual=actual_size,
                )
            if expected_size_bytes is not None and actual_size != expected_size_bytes:
                _error(
                    "bundle_member_size_mismatch",
                    "The prepared snapshot size no longer matches project.json.",
                    snapshot,
                    expected=expected_size_bytes,
                    actual=actual_size,
                )
            if normalized_digest is not None and actual_digest != normalized_digest:
                _error(
                    "bundle_member_sha256_mismatch",
                    "The prepared snapshot was changed after the project was inspected.",
                    snapshot,
                    expected=normalized_digest,
                    actual=actual_digest,
                )

            frozen.flush()
            frozen_digest, frozen_size = _sha256_open_handle(frozen)
            if frozen_digest != actual_digest or frozen_size != actual_size:
                _error(
                    "bundle_member_sha256_mismatch",
                    "The private snapshot copy failed its identity check.",
                    snapshot,
                    expected=actual_digest,
                    actual=frozen_digest,
                    expected_size=actual_size,
                    actual_size=frozen_size,
                )

            frozen.seek(0)
            try:
                with zipfile.ZipFile(frozen, "r") as header_archive:
                    _inspect_snapshot_headers_archive(header_archive, snapshot)
            except ProjectBundleError:
                raise
            except (OSError, zipfile.BadZipFile) as exc:
                _error(
                    "invalid_prepared_snapshot",
                    f"The prepared snapshot is invalid: {exc}",
                    snapshot,
                )

            # NumPy reads only from this unlinked/private temporary file.  A
            # caller replacing or editing the original path after verification
            # cannot alter the bytes expanded below.
            frozen.seek(0)
            try:
                loaded_context = np.load(frozen, allow_pickle=False)
            except (OSError, ValueError) as exc:
                _error(
                    "invalid_prepared_snapshot",
                    f"Cannot open prepared snapshot: {exc}",
                    snapshot,
                )
            with loaded_context as archive:
                yield archive
    except ProjectBundleError:
        raise
    except OSError as exc:
        _error(
            "invalid_prepared_snapshot",
            f"Cannot read prepared snapshot: {exc}",
            snapshot,
        )


def _snapshot_array(
    archive: Mapping[str, np.ndarray],
    name: str,
    *,
    kind: str,
    ndim: int,
    shape_tail: tuple[int, ...] = (),
) -> np.ndarray:
    try:
        array = np.asarray(archive[name])
    except (KeyError, OSError, ValueError) as exc:
        _error("invalid_snapshot_array", f"Cannot read snapshot array {name}: {exc}")
    if array.dtype.hasobject:
        _error("unsafe_snapshot_dtype", f"Object dtype is forbidden for {name}.")
    if array.ndim != ndim or (shape_tail and array.shape[-len(shape_tail) :] != shape_tail):
        _error("invalid_snapshot_shape", f"Snapshot array {name} has the wrong shape.")
    if kind == "float":
        if array.dtype.kind != "f" or not np.all(np.isfinite(array)):
            _error("invalid_snapshot_dtype", f"Snapshot array {name} must be finite floats.")
    elif kind == "int":
        if array.dtype.kind not in "iu":
            _error("invalid_snapshot_dtype", f"Snapshot array {name} must contain integers.")
    elif kind == "uint8":
        if array.dtype != np.dtype(np.uint8):
            _error("invalid_snapshot_dtype", f"Snapshot array {name} must be uint8.")
    return np.ascontiguousarray(array)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _error("invalid_snapshot_metadata", f"{field_name} must be a string list.")
    return tuple(value)


def _decode_level(
    archive: Mapping[str, np.ndarray],
    metadata: Mapping[str, object],
    prefix: str,
) -> MeshLevel:
    vertices = _snapshot_array(
        archive, f"{prefix}_vertices_unit", kind="float", ndim=2, shape_tail=(3,)
    ).astype(np.float64, copy=False)
    faces = _snapshot_array(
        archive, f"{prefix}_faces", kind="int", ndim=2, shape_tail=(3,)
    ).astype(np.int32, copy=False)
    colors = _snapshot_array(
        archive, f"{prefix}_vertex_colors", kind="float", ndim=2, shape_tail=(3,)
    ).astype(np.float64, copy=False)
    areas = _snapshot_array(
        archive, f"{prefix}_areas_unit", kind="float", ndim=1
    ).astype(np.float64, copy=False)
    part_ids = _snapshot_array(
        archive, f"{prefix}_face_part_ids", kind="int", ndim=1
    ).astype(np.int32, copy=False)
    provenance = _snapshot_array(
        archive, f"{prefix}_face_provenance", kind="uint8", ndim=1
    )
    if len(colors) != len(vertices) or len(areas) != len(faces):
        _error("invalid_snapshot_shape", f"{prefix} array lengths are inconsistent.")
    if len(faces) and (int(faces.min()) < 0 or int(faces.max()) >= len(vertices)):
        _error("snapshot_face_index_out_of_bounds", f"{prefix} faces are out of bounds.")
    if len(part_ids) not in {0, len(faces)} or len(provenance) not in {0, len(faces)}:
        _error("invalid_snapshot_shape", f"{prefix} face metadata lengths are invalid.")
    names = _string_tuple(metadata.get("part_names"), f"{prefix}.part_names")
    keys = _string_tuple(metadata.get("part_keys"), f"{prefix}.part_keys")
    if len(names) != len(keys):
        _error("invalid_snapshot_metadata", f"{prefix} part names/keys differ.")
    if len(part_ids):
        if not names or int(part_ids.min()) < 0 or int(part_ids.max()) >= len(names):
            _error("snapshot_part_index_out_of_bounds", f"{prefix} part IDs are invalid.")
    has_neighbors = metadata.get("has_neighbors")
    if not isinstance(has_neighbors, bool):
        _error("invalid_snapshot_metadata", f"{prefix}.has_neighbors is invalid.")
    neighbor_name = f"{prefix}_neighbors"
    if has_neighbors:
        neighbors = _snapshot_array(
            archive, neighbor_name, kind="int", ndim=2, shape_tail=(3,)
        ).astype(np.int32, copy=False)
        if len(neighbors) != len(faces):
            _error("invalid_snapshot_shape", f"{prefix} neighbors have the wrong length.")
        if len(neighbors) and (
            int(neighbors.min()) < -1 or int(neighbors.max()) >= len(faces)
        ):
            _error("snapshot_neighbor_out_of_bounds", f"{prefix} neighbors are invalid.")
    else:
        if neighbor_name in archive:
            _error("invalid_snapshot_members", f"Unexpected {neighbor_name} array.")
        neighbors = None
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=colors,
        areas_unit=areas,
        neighbors=neighbors,
        face_part_ids=part_ids,
        part_names=names,
        part_keys=keys,
        face_provenance=provenance,
    )


def decode_prepared_geometry_snapshot(
    snapshot_path: Path | str,
    *,
    bundled_source_obj: Path | str,
    expected_source_sha256: str,
    expected_geometry_key: tuple[object, ...],
    expected_paint_mesh_fingerprint: str | None = None,
    expected_snapshot_sha256: str | None = None,
    expected_snapshot_size_bytes: int | None = None,
) -> PreparedGeometrySnapshotResult:
    """Decode an exact cache with strict dtype/topology/source validation."""

    snapshot = Path(snapshot_path)
    source_obj = Path(bundled_source_obj)
    _assert_regular_file(snapshot, suffix=".npz", code="prepared_geometry_snapshot_missing")
    _assert_source_file(
        source_obj,
        code=(
            "bundled_obj_missing"
            if source_obj.suffix.lower() == ".obj"
            else "bundled_source_missing"
        ),
    )
    expected_source = str(expected_source_sha256).lower()
    actual_source, actual_source_size = _sha256(source_obj)
    if actual_source != expected_source:
        _error("snapshot_source_sha256_mismatch", "Snapshot source-model SHA-256 differs.")
    with _validated_snapshot_arrays(
        snapshot,
        expected_sha256=expected_snapshot_sha256,
        expected_size_bytes=expected_snapshot_size_bytes,
    ) as archive:
        keys = set(archive.files)
        if not _SNAPSHOT_REQUIRED_ARRAYS.issubset(keys) or not keys.issubset(_SNAPSHOT_ARRAYS):
            _error("invalid_snapshot_members", "Snapshot array allowlist failed.", snapshot)
        metadata_array = _snapshot_array(
            archive, "metadata", kind="uint8", ndim=1
        )
        if len(metadata_array) > MAX_SNAPSHOT_METADATA_BYTES:
            _error("snapshot_metadata_too_large", "Snapshot metadata is too large.")
        try:
            metadata = json.loads(
                metadata_array.tobytes().decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except ProjectBundleError:
            raise
        except (UnicodeError, json.JSONDecodeError) as exc:
            _error("invalid_snapshot_metadata", f"Snapshot metadata is invalid: {exc}")
        if not isinstance(metadata, dict) or metadata.get("schema") != PREPARED_SNAPSHOT_SCHEMA:
            _error("unsupported_snapshot_format", "Snapshot metadata schema is unsupported.")
        if metadata.get("source_sha256") != expected_source:
            _error("snapshot_source_sha256_mismatch", "Snapshot metadata source differs.")
        geometry_key = _normal_geometry_key(metadata.get("geometry_key"))
        if geometry_key != _normal_geometry_key(expected_geometry_key):
            _error(
                "snapshot_geometry_key_mismatch",
                "Snapshot geometry settings differ from the loaded project.",
            )

        asset_meta = metadata.get("asset")
        final_meta = metadata.get("final")
        preview_meta = metadata.get("preview")
        prepared_meta = metadata.get("prepared")
        if not all(
            isinstance(item, Mapping)
            for item in (asset_meta, final_meta, preview_meta, prepared_meta)
        ):
            _error("invalid_snapshot_metadata", "Snapshot metadata sections are missing.")

        asset_vertices = _snapshot_array(
            archive, "asset_vertices", kind="float", ndim=2, shape_tail=(3,)
        ).astype(np.float64, copy=False)
        asset_colors = _snapshot_array(
            archive, "asset_colors", kind="float", ndim=2, shape_tail=(3,)
        ).astype(np.float64, copy=False)
        asset_faces = _snapshot_array(
            archive, "asset_faces", kind="int", ndim=2, shape_tail=(3,)
        ).astype(np.int32, copy=False)
        asset_part_ids = _snapshot_array(
            archive, "asset_face_part_ids", kind="int", ndim=1
        ).astype(np.int32, copy=False)
        if len(asset_colors) != len(asset_vertices):
            _error("invalid_snapshot_shape", "Asset vertex/color lengths differ.")
        if len(asset_faces) and (
            int(asset_faces.min()) < 0 or int(asset_faces.max()) >= len(asset_vertices)
        ):
            _error("snapshot_face_index_out_of_bounds", "Asset faces are out of bounds.")
        if len(asset_part_ids) not in {0, len(asset_faces)}:
            _error("invalid_snapshot_shape", "Asset part IDs have the wrong length.")
        asset_names = _string_tuple(asset_meta.get("part_names"), "asset.part_names")
        asset_keys = _string_tuple(asset_meta.get("part_keys"), "asset.part_keys")
        if len(asset_names) != len(asset_keys):
            _error("invalid_snapshot_metadata", "Asset part names/keys differ.")
        if len(asset_part_ids) and (
            not asset_names
            or int(asset_part_ids.min()) < 0
            or int(asset_part_ids.max()) >= len(asset_names)
        ):
            _error("snapshot_part_index_out_of_bounds", "Asset part IDs are invalid.")

        final_level = _decode_level(archive, final_meta, "final")
        preview_level = _decode_level(archive, preview_meta, "preview")
        dimensions = _snapshot_array(
            archive, "source_dimensions_unit", kind="float", ndim=1
        ).astype(np.float64, copy=False)
        if dimensions.shape != (3,):
            _error("invalid_snapshot_shape", "Source dimensions must contain 3 values.")

        def nonnegative_int(name: str) -> int:
            value = prepared_meta.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _error("invalid_snapshot_metadata", f"{name} must be nonnegative.")
            return value

        def finite_float(name: str) -> float:
            value = prepared_meta.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _error("invalid_snapshot_metadata", f"{name} must be numeric.")
            result = float(value)
            if not np.isfinite(result):
                _error("invalid_snapshot_metadata", f"{name} must be finite.")
            return result

        original_vertices = asset_meta.get("original_vertex_count")
        original_faces = asset_meta.get("original_face_count")
        if (
            isinstance(original_vertices, bool)
            or not isinstance(original_vertices, int)
            or original_vertices < len(asset_vertices)
            or isinstance(original_faces, bool)
            or not isinstance(original_faces, int)
            or original_faces < len(asset_faces)
        ):
            _error("invalid_snapshot_metadata", "Original asset counts are invalid.")
        asset_warnings = _string_tuple(asset_meta.get("warnings"), "asset.warnings")
        part_face_counts = asset_meta.get("part_face_counts")
        part_vertex_counts = asset_meta.get("part_vertex_counts")
        if not isinstance(part_face_counts, list) or not isinstance(part_vertex_counts, list):
            _error("invalid_snapshot_metadata", "Asset part counts are invalid.")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (*part_face_counts, *part_vertex_counts)):
            _error("invalid_snapshot_metadata", "Asset part counts are invalid.")
        marker = asset_meta.get("part_marker_kind")
        if marker is not None and not isinstance(marker, str):
            _error("invalid_snapshot_metadata", "Asset marker kind is invalid.")
        explicit = asset_meta.get("has_explicit_parts")
        if not isinstance(explicit, bool):
            _error("invalid_snapshot_metadata", "Asset explicit-parts flag is invalid.")
        import_metadata = asset_meta.get("import_metadata", {})
        if not isinstance(import_metadata, dict) or any(
            not isinstance(key, str)
            or not isinstance(value, (bool, int, float, str, type(None)))
            or (isinstance(value, float) and not np.isfinite(value))
            for key, value in import_metadata.items()
        ):
            _error("invalid_snapshot_metadata", "Asset import metadata is invalid.")

        topology = prepared_meta.get("topology")
        if not isinstance(topology, dict) or any(
            not isinstance(key, str)
            or isinstance(value, float)
            or not isinstance(value, (bool, int))
            for key, value in topology.items()
        ):
            _error("invalid_snapshot_metadata", "Prepared topology is invalid.")
        warnings = _string_tuple(prepared_meta.get("warnings"), "prepared.warnings")
        part_names = _string_tuple(prepared_meta.get("part_names"), "prepared.part_names")
        part_keys = _string_tuple(prepared_meta.get("part_keys"), "prepared.part_keys")
        part_stats = prepared_meta.get("part_stats")
        assembly = prepared_meta.get("assembly")
        if not isinstance(part_stats, list) or not isinstance(assembly, dict):
            _error("invalid_snapshot_metadata", "Prepared part/assembly metadata is invalid.")

        source = ObjAsset(
            path=source_obj,
            sha256=expected_source,
            file_size=actual_source_size,
            vertices=asset_vertices,
            colors=asset_colors,
            faces=asset_faces,
            original_vertex_count=original_vertices,
            original_face_count=original_faces,
            warnings=list(asset_warnings),
            part_names=asset_names,
            part_keys=asset_keys,
            face_part_ids=asset_part_ids,
            part_face_counts=tuple(part_face_counts),
            part_vertex_counts=tuple(part_vertex_counts),
            part_marker_kind=marker,
            has_explicit_parts=explicit,
            import_metadata=dict(import_metadata),
        )
        prepared = PreparedGeometry(
            source=source,
            final=final_level,
            preview=preview_level,
            clean_vertex_count=nonnegative_int("clean_vertex_count"),
            clean_face_count=nonnegative_int("clean_face_count"),
            removed_vertices=nonnegative_int("removed_vertices"),
            removed_faces=nonnegative_int("removed_faces"),
            topology=dict(topology),
            source_area_unit=finite_float("source_area_unit"),
            source_volume_unit=finite_float("source_volume_unit"),
            simplified_area_unit=finite_float("simplified_area_unit"),
            simplified_volume_unit=finite_float("simplified_volume_unit"),
            source_dimensions_unit=dimensions,
            warnings=list(warnings),
            part_names=part_names,
            part_keys=part_keys,
            part_stats=list(part_stats),
            assembly=dict(assembly),
        )

    actual_paint_fingerprint = mesh_fingerprint(prepared.final)
    recorded_paint_fingerprint = metadata.get("paint_mesh_fingerprint")
    if actual_paint_fingerprint != recorded_paint_fingerprint:
        _error(
            "prepared_geometry_fingerprint_mismatch",
            "Decoded prepared geometry does not match its metadata fingerprint.",
        )
    if (
        expected_paint_mesh_fingerprint is not None
        and actual_paint_fingerprint != str(expected_paint_mesh_fingerprint)
    ):
        _error(
            "prepared_geometry_fingerprint_mismatch",
            "Decoded prepared geometry does not match the manual-paint fingerprint.",
        )
    return PreparedGeometrySnapshotResult(
        prepared=prepared,
        geometry_key=geometry_key,
        source_sha256=expected_source,
        paint_mesh_fingerprint=actual_paint_fingerprint,
    )


def save_project_bundle(
    destination_folder: Path | str,
    source_obj: Path | str,
    project_data: Mapping[str, object],
    *,
    prepared_geometry_snapshot: Path | str | None = None,
    prepared_geometry: PreparedGeometry | None = None,
    prepared_geometry_key: tuple[object, ...] | None = None,
    reference_image: Path | str | None = None,
) -> ProjectBundleSaveResult:
    """Atomically create a new portable project folder without overwriting.

    The destination's parent must already exist.  Work happens in a unique
    sibling staging directory and becomes visible only through the final
    rename.  Any error removes that staging directory and leaves an existing
    destination untouched.
    """

    destination = Path(destination_folder)
    source = Path(source_obj)
    if destination.exists() or destination.is_symlink():
        _error(
            "destination_exists",
            "The project folder already exists and will not be overwritten.",
            destination,
        )
    _validate_member_name(destination.name, code="unsafe_project_folder_name")
    parent = destination.parent
    if not parent.exists() or not parent.is_dir():
        _error(
            "destination_parent_missing",
            "Choose an existing destination folder.",
            parent,
        )
    _assert_not_link_or_reparse(parent, code="unsafe_destination_parent")
    source_format = _assert_source_file(
        source,
        code=(
            "source_obj_missing"
            if source.suffix.lower() == ".obj"
            else "source_model_missing"
        ),
    )
    _validate_member_name(source.name)
    portable_project, omitted = _portable_project_copy(project_data)
    contracts = _fingerprint_contracts(portable_project)

    if prepared_geometry is not None and prepared_geometry_snapshot is not None:
        _error(
            "multiple_prepared_geometry_sources",
            "Supply prepared geometry or an existing snapshot, not both.",
        )
    if prepared_geometry is not None and prepared_geometry_key is None:
        _error(
            "prepared_geometry_key_required",
            "Prepared geometry requires its exact settings key.",
        )
    snapshot: Path | None = None
    if prepared_geometry_snapshot is not None:
        snapshot = Path(prepared_geometry_snapshot)
        _assert_regular_file(
            snapshot,
            suffix=".npz",
            code="prepared_geometry_snapshot_missing",
        )

    reference: Path | None = None
    reference_name: str | None = None
    if reference_image is not None:
        reference = Path(reference_image)
        allowed_reference_suffixes = {
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".tif",
            ".tiff",
            ".webp",
        }
        if reference.suffix.lower() not in allowed_reference_suffixes:
            _error(
                "unsupported_reference_image",
                "The reference image format is not supported.",
                reference,
            )
        _assert_regular_file(
            reference,
            suffix=reference.suffix,
            code="reference_image_missing",
        )
        reference_name = f"reference{reference.suffix.lower()}"

    staging = parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    try:
        staging.mkdir(mode=0o700)
        bundled_obj = staging / _source_member_name(source_format)
        source_digest, source_size = _copy_regular_file(source, bundled_obj)
        restore_mode = "none"
        if contracts:
            restore_mode = "rebuild-and-verify"

        prepared_manifest: dict[str, object] | None = None
        bundled_snapshot: Path | None = None
        if snapshot is not None:
            if prepared_geometry_key is None:
                _error(
                    "prepared_geometry_key_required",
                    "An existing snapshot requires its exact settings key.",
                )
            bundled_snapshot = staging / PREPARED_GEOMETRY_NAME
            snapshot_digest, snapshot_size = _copy_regular_file(
                snapshot, bundled_snapshot
            )
            decoded_snapshot = decode_prepared_geometry_snapshot(
                bundled_snapshot,
                bundled_source_obj=bundled_obj,
                expected_source_sha256=source_digest,
                expected_geometry_key=prepared_geometry_key,
                expected_paint_mesh_fingerprint=contracts.get("manual_paint"),
                expected_snapshot_sha256=snapshot_digest,
                expected_snapshot_size_bytes=snapshot_size,
            )
            prepared_manifest = {
                "relative_path": PREPARED_GEOMETRY_NAME,
                "sha256": snapshot_digest,
                "size_bytes": snapshot_size,
                "format": "obj-adjuster.prepared-geometry.npz.v1",
                "geometry_key": list(_normal_geometry_key(prepared_geometry_key)),
                "paint_mesh_fingerprint": (
                    decoded_snapshot.paint_mesh_fingerprint
                ),
            }
            restore_mode = "snapshot-and-verify" if contracts else "snapshot"
        elif prepared_geometry is not None:
            bundled_snapshot = staging / PREPARED_GEOMETRY_NAME
            (
                snapshot_digest,
                snapshot_size,
                snapshot_geometry_key,
                snapshot_paint_fingerprint,
            ) = encode_prepared_geometry_snapshot(
                bundled_snapshot,
                prepared_geometry,
                source_sha256=source_digest,
                geometry_key=prepared_geometry_key or (),
                expected_paint_mesh_fingerprint=contracts.get("manual_paint"),
            )
            prepared_manifest = {
                "relative_path": PREPARED_GEOMETRY_NAME,
                "sha256": snapshot_digest,
                "size_bytes": snapshot_size,
                "format": "obj-adjuster.prepared-geometry.npz.v1",
                "geometry_key": list(snapshot_geometry_key),
                "paint_mesh_fingerprint": snapshot_paint_fingerprint,
            }
            restore_mode = "snapshot-and-verify" if contracts else "snapshot"

        reference_manifest: dict[str, object] | None = None
        if reference is not None and reference_name is not None:
            bundled_reference = staging / reference_name
            reference_digest, reference_size = _copy_regular_file(
                reference, bundled_reference
            )
            reference_manifest = {
                "relative_path": reference_name,
                "sha256": reference_digest,
                "size_bytes": reference_size,
            }

        source_manifest: dict[str, object] = {
            "relative_path": bundled_obj.name,
            "original_name": source.name,
            "format": source_format,
            "sha256": source_digest,
            "fingerprint": f"sha256:{source_digest}",
            "size_bytes": source_size,
        }
        wrapper: dict[str, object] = {
            "schema": BUNDLE_SCHEMA,
            "source_asset": source_manifest,
            "restore_contract": {
                "mode": restore_mode,
                "expected_mesh_fingerprints": contracts,
            },
            "project": portable_project,
        }
        # Transitional OBJ alias: v2 readers use ``source_asset``; keeping an
        # exact duplicate for OBJ avoids breaking integrations that inspect
        # the old key.  Readers cross-check it and never trust two manifests.
        if source_format == "obj":
            wrapper["source_obj"] = dict(source_manifest)
        if prepared_manifest is not None:
            wrapper["prepared_geometry"] = prepared_manifest
        if reference_manifest is not None:
            wrapper["reference_image"] = reference_manifest
        _write_json_exclusive(staging / PROJECT_JSON_NAME, wrapper)
        _fsync_directory(staging)

        # ``rename`` is same-volume and atomic.  Python/Windows refuses an
        # existing target; the immediate recheck also closes normal UI races.
        if destination.exists() or destination.is_symlink():
            _error(
                "destination_exists",
                "The project folder appeared while saving; nothing was overwritten.",
                destination,
            )
        os.rename(staging, destination)
        _fsync_directory(parent)
    except Exception:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    has_snapshot = snapshot is not None or prepared_geometry is not None
    final_snapshot = destination / PREPARED_GEOMETRY_NAME if has_snapshot else None
    final_reference = (
        destination / reference_name if reference_name is not None else None
    )
    restore_state = GeometryRestoreState.NOT_REQUIRED
    if contracts:
        restore_state = (
            GeometryRestoreState.SNAPSHOT_AVAILABLE_UNVERIFIED
            if has_snapshot
            else GeometryRestoreState.REBUILD_AND_VERIFY
        )
    return ProjectBundleSaveResult(
        folder=destination,
        project_json=destination / PROJECT_JSON_NAME,
        source_obj=destination / _source_member_name(source_format),
        source_sha256=source_digest,
        source_size_bytes=source_size,
        geometry_restore_state=restore_state,
        source_format=source_format,
        expected_mesh_fingerprints=contracts,
        prepared_geometry_snapshot=final_snapshot,
        reference_image=final_reference,
        omitted_private_fields=omitted,
    )


def default_project_folder_name(source_obj: Path | str) -> str:
    """Return the public ``<model name>_project`` folder name."""

    source = Path(source_obj)
    stem = source.stem.strip()
    if not stem:
        stem = "model"
    return _validate_member_name(
        f"{stem}_project", code="unsafe_project_folder_name"
    )


def save_project_bundle_in_parent(
    parent_folder: Path | str,
    source_obj: Path | str,
    project_data: Mapping[str, object],
    *,
    project_folder_name: str | None = None,
    prepared_geometry_snapshot: Path | str | None = None,
    prepared_geometry: PreparedGeometry | None = None,
    prepared_geometry_key: tuple[object, ...] | None = None,
    reference_image: Path | str | None = None,
) -> ProjectBundleSaveResult:
    """Create ``<OBJ name>_project`` below a folder selected by the user."""

    parent = Path(parent_folder)
    name = (
        default_project_folder_name(source_obj)
        if project_folder_name is None
        else _validate_member_name(
            project_folder_name, code="unsafe_project_folder_name"
        )
    )
    return save_project_bundle(
        parent / name,
        source_obj,
        project_data,
        prepared_geometry_snapshot=prepared_geometry_snapshot,
        prepared_geometry=prepared_geometry,
        prepared_geometry_key=prepared_geometry_key,
        reference_image=reference_image,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _error("duplicate_json_key", f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json_object(path: Path) -> dict[str, object]:
    _assert_regular_file(path, suffix=".json", code="project_json_missing")
    try:
        size = path.stat().st_size
    except OSError as exc:
        _error("project_json_unreadable", str(exc), path)
    if size > MAX_PROJECT_JSON_BYTES:
        _error("project_json_too_large", "The project JSON is too large.", path)
    try:
        text = path.read_text(encoding="utf-8-sig")
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except ProjectBundleError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _error("invalid_project_json", f"The project JSON cannot be read: {exc}", path)
    if not isinstance(value, dict):
        _error("invalid_project_json", "The project JSON root must be an object.", path)
    return value


def _resolve_checked_member(root: Path, relative_name: object, *, suffix: str) -> Path:
    name = _safe_relative_member(relative_name, suffix=suffix)
    candidate = root / name
    # There are no intermediate members in v1, but keep both containment and
    # link checks explicit for future schema extensions.
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        _error("unsafe_relative_path", "A bundle member escapes its folder.", candidate)
    return candidate


def _validate_digest_manifest(
    path: Path,
    manifest: Mapping[str, object],
    *,
    missing_code: str,
) -> tuple[str, int]:
    _assert_regular_file(path, suffix=path.suffix, code=missing_code)
    expected_digest = str(manifest.get("sha256", "")).lower()
    if not _SHA256_RE.fullmatch(expected_digest):
        _error("invalid_sha256_manifest", "A bundle SHA-256 value is invalid.", path)
    expected_size = manifest.get("size_bytes")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
        _error("invalid_size_manifest", "A bundle size value is invalid.", path)
    actual_digest, actual_size = _sha256(path)
    if actual_size != expected_size:
        _error(
            "bundle_member_size_mismatch",
            "A bundled file size no longer matches project.json.",
            path,
            expected=expected_size,
            actual=actual_size,
        )
    if actual_digest != expected_digest:
        _error(
            "bundle_member_sha256_mismatch",
            "A bundled file was changed after the project was saved.",
            path,
            expected=expected_digest,
            actual=actual_digest,
        )
    return actual_digest, actual_size


def _legacy_source_name(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    # Accept either historical Windows or POSIX spelling but reveal only the
    # basename.  It is a label, never a path to follow automatically.
    normalized = value.strip().replace("/", "\\")
    name = PureWindowsPath(normalized).name
    if not name:
        return None
    try:
        return _validate_member_name(name)
    except ProjectBundleError:
        return None


def inspect_project_path(path: Path | str) -> ProjectLoadResult:
    """Inspect a portable folder/JSON or a legacy standalone project JSON."""

    selected = Path(path)
    if not selected.exists():
        _error("project_path_missing", "The selected project does not exist.", selected)
    _assert_not_link_or_reparse(selected, code="unsafe_link_or_reparse")
    if selected.is_dir():
        bundle_root = selected
        project_json = selected / PROJECT_JSON_NAME
    elif selected.is_file():
        bundle_root = selected.parent
        project_json = selected
    else:
        _error("invalid_project_path", "Select a project folder or JSON file.", selected)

    data = _read_json_object(project_json)
    bundle_schema = data.get("schema")
    if bundle_schema not in {BUNDLE_SCHEMA, LEGACY_BUNDLE_SCHEMA}:
        schema = _project_schema(data, for_save=False)
        if not schema and not (
            isinstance(data.get("settings"), Mapping)
            or any(key in data for key in ("geometry", "palette", "tone"))
        ):
            _error(
                "unsupported_project_schema",
                "This JSON is not a recognized legacy ChromaMatter project.",
                project_json,
            )
        contracts = _fingerprint_contracts(data)
        ignored = tuple(
            name
            for name in ("manual_parts", "manual_joint")
            if isinstance(data.get(name), Mapping)
        )
        legacy_source_name = _legacy_source_name(
            data.get("source_path", data.get("obj_path"))
        )
        legacy_source_format = None
        if legacy_source_name is not None:
            try:
                legacy_source_format = _source_format_for_path(
                    legacy_source_name
                )
            except ProjectBundleError:
                legacy_source_format = None
        return ProjectLoadResult(
            state=ProjectLoadState.NEEDS_SOURCE_OBJ,
            project_data=_legacy_project_copy(data),
            project_json=project_json,
            bundle_folder=None,
            source_obj=None,
            source_sha256=None,
            source_size_bytes=None,
            geometry_restore_state=(
                GeometryRestoreState.REBUILD_AND_VERIFY
                if contracts
                else GeometryRestoreState.NOT_REQUIRED
            ),
            source_format=legacy_source_format,
            expected_mesh_fingerprints=contracts,
            legacy_source_name=legacy_source_name,
            ignored_features=ignored,
            geometry_restore_reason=(
                "The legacy JSON has no bundled source model. Select the original model, "
                "rebuild it, and verify the saved manual-paint mesh fingerprint."
                if contracts
                else None
            ),
        )

    _assert_not_link_or_reparse(bundle_root, code="unsafe_link_or_reparse")
    if bundle_schema == BUNDLE_SCHEMA:
        source_manifest = data.get("source_asset")
    else:
        source_manifest = data.get("source_obj")
    project_data = data.get("project")
    restore_contract = data.get("restore_contract")
    if not isinstance(source_manifest, Mapping):
        _error("invalid_bundle_manifest", "The source-model manifest is missing.", project_json)
    if not isinstance(project_data, Mapping):
        _error("invalid_bundle_manifest", "The project settings are missing.", project_json)
    if not isinstance(restore_contract, Mapping):
        _error("invalid_bundle_manifest", "The geometry restore contract is missing.", project_json)

    raw_project_mapping = dict(project_data)
    _project_schema(raw_project_mapping, for_save=True)
    _validate_json_value(raw_project_mapping)
    ignored = tuple(
        name
        for name in ("manual_parts", "manual_joint")
        if isinstance(raw_project_mapping.get(name), Mapping)
    )
    project_mapping = _legacy_project_copy(raw_project_mapping)
    if bundle_schema == LEGACY_BUNDLE_SCHEMA:
        source_format = "obj"
    else:
        source_format = str(source_manifest.get("format", "")).lower()
        if source_format not in SUPPORTED_SOURCE_FORMATS:
            _error(
                "unsupported_source_format",
                "The project source format must be obj or glb.",
                project_json,
            )
        original_name = source_manifest.get("original_name")
        if not isinstance(original_name, str):
            _error(
                "invalid_bundle_manifest",
                "The original source-model name is missing.",
                project_json,
            )
        _validate_member_name(original_name)
        if _source_format_for_path(original_name) != source_format:
            _error(
                "source_format_mismatch",
                "The source format and original file name disagree.",
                project_json,
            )

    source_suffix = SUPPORTED_SOURCE_FORMATS[source_format]
    source_path = _resolve_checked_member(
        bundle_root,
        source_manifest.get("relative_path"),
        suffix=source_suffix,
    )
    if source_path.name != _source_member_name(source_format):
        _error(
            "invalid_bundle_manifest",
            "The bundled source model must use its canonical portable name.",
            source_path,
        )

    # v2 OBJ bundles deliberately include a deprecated manifest alias for
    # callers written against v1.  Validate it independently, then require an
    # exact match so there is only one authority for source bytes.
    if bundle_schema == BUNDLE_SCHEMA and "source_obj" in data:
        source_obj_alias = data.get("source_obj")
        if source_format != "obj" or not isinstance(source_obj_alias, Mapping):
            _error(
                "invalid_bundle_manifest",
                "Only an OBJ source may carry the deprecated source_obj alias.",
                project_json,
            )
        _resolve_checked_member(
            bundle_root,
            source_obj_alias.get("relative_path"),
            suffix=".obj",
        )
        if dict(source_obj_alias) != dict(source_manifest):
            _error(
                "source_manifest_alias_mismatch",
                "The source_asset and source_obj manifests disagree.",
                project_json,
            )
    source_digest, source_size = _validate_digest_manifest(
        source_path,
        source_manifest,
        missing_code=(
            "bundled_obj_missing"
            if source_format == "obj"
            else "bundled_source_missing"
        ),
    )
    expected_fingerprint = f"sha256:{source_digest}"
    if source_manifest.get("fingerprint") != expected_fingerprint:
        _error(
            "source_fingerprint_mismatch",
            "The source fingerprint in project.json is invalid.",
            source_path,
        )

    actual_contracts = _fingerprint_contracts(raw_project_mapping)
    recorded_contracts = restore_contract.get("expected_mesh_fingerprints", {})
    if not isinstance(recorded_contracts, Mapping) or dict(recorded_contracts) != actual_contracts:
        _error(
            "restore_contract_mismatch",
            "The saved manual-edit fingerprint contract is inconsistent.",
            project_json,
        )

    snapshot_path: Path | None = None
    snapshot_geometry_key: tuple[object, ...] | None = None
    snapshot_digest: str | None = None
    snapshot_size: int | None = None
    snapshot_manifest = data.get("prepared_geometry")
    if snapshot_manifest is not None:
        if not isinstance(snapshot_manifest, Mapping):
            _error("invalid_bundle_manifest", "The prepared snapshot manifest is invalid.")
        if snapshot_manifest.get("format") != "obj-adjuster.prepared-geometry.npz.v1":
            _error("unsupported_snapshot_format", "The prepared snapshot format is unsupported.")
        snapshot_path = _resolve_checked_member(
            bundle_root,
            snapshot_manifest.get("relative_path"),
            suffix=".npz",
        )
        snapshot_digest, snapshot_size = _validate_digest_manifest(
            snapshot_path,
            snapshot_manifest,
            missing_code="prepared_geometry_snapshot_missing",
        )
        snapshot_geometry_key = _normal_geometry_key(
            snapshot_manifest.get("geometry_key")
        )
        snapshot_paint_fingerprint = str(
            snapshot_manifest.get("paint_mesh_fingerprint", "")
        )
        if not _SHA256_RE.fullmatch(snapshot_paint_fingerprint):
            _error(
                "invalid_bundle_manifest",
                "The snapshot paint-mesh fingerprint is invalid.",
                project_json,
            )
        expected_manual_fingerprint = actual_contracts.get("manual_paint")
        if (
            expected_manual_fingerprint is not None
            and snapshot_paint_fingerprint != expected_manual_fingerprint
        ):
            _error(
                "restore_contract_mismatch",
                "The snapshot and manual-paint fingerprints differ.",
                project_json,
            )

    reference_path: Path | None = None
    reference_manifest = data.get("reference_image")
    if reference_manifest is not None:
        if not isinstance(reference_manifest, Mapping):
            _error("invalid_bundle_manifest", "The reference image manifest is invalid.")
        relative_reference = reference_manifest.get("relative_path")
        if not isinstance(relative_reference, str):
            _error("invalid_bundle_manifest", "The reference image path is missing.")
        suffix = Path(relative_reference).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
            _error("unsupported_reference_image", "The reference image format is unsupported.")
        reference_path = _resolve_checked_member(
            bundle_root,
            relative_reference,
            suffix=suffix,
        )
        _validate_digest_manifest(
            reference_path,
            reference_manifest,
            missing_code="reference_image_missing",
        )

    mode = str(restore_contract.get("mode", ""))
    expected_mode = "none"
    if actual_contracts:
        expected_mode = "rebuild-and-verify"
    if snapshot_path is not None:
        expected_mode = "snapshot-and-verify" if actual_contracts else "snapshot"
    if mode != expected_mode:
        _error(
            "restore_contract_mismatch",
            "The geometry restore mode is inconsistent with the project contents.",
            project_json,
        )

    restore_state = GeometryRestoreState.NOT_REQUIRED
    if actual_contracts:
        restore_state = (
            GeometryRestoreState.SNAPSHOT_AVAILABLE_UNVERIFIED
            if snapshot_path is not None
            else GeometryRestoreState.REBUILD_AND_VERIFY
        )
    return ProjectLoadResult(
        state=(
            ProjectLoadState.READY_REQUIRES_GEOMETRY_VERIFICATION
            if actual_contracts
            else ProjectLoadState.READY
        ),
        project_data=project_mapping,
        project_json=project_json,
        bundle_folder=bundle_root,
        source_obj=source_path,
        source_sha256=source_digest,
        source_size_bytes=source_size,
        geometry_restore_state=restore_state,
        source_format=source_format,
        expected_mesh_fingerprints=actual_contracts,
        prepared_geometry_snapshot=snapshot_path,
        prepared_geometry_snapshot_sha256=snapshot_digest,
        prepared_geometry_snapshot_size_bytes=snapshot_size,
        reference_image=reference_path,
        ignored_features=ignored,
        geometry_restore_reason=(
            "An exact prepared-geometry snapshot is bundled, but its decoded "
            "mesh fingerprint must still be verified before manual paint is applied."
            if actual_contracts and snapshot_path is not None
            else (
                "Only the source model is bundled. Geometry preprocessing may be "
                "nondeterministic, so the rebuilt mesh fingerprint must be verified "
                "before manual paint is applied."
                if actual_contracts
                else None
            )
        ),
        snapshot_geometry_key=snapshot_geometry_key,
    )


def load_project_bundle(path: Path | str) -> ProjectLoadResult:
    """Public loading alias used by the GUI integration layer."""

    return inspect_project_path(path)


__all__ = [
    "BUNDLE_SCHEMA",
    "LEGACY_BUNDLE_SCHEMA",
    "CURRENT_PROJECT_SCHEMA",
    "decode_prepared_geometry_snapshot",
    "default_project_folder_name",
    "encode_prepared_geometry_snapshot",
    "GeometryRestoreState",
    "PROJECT_JSON_NAME",
    "SOURCE_OBJ_NAME",
    "SOURCE_GLB_NAME",
    "SUPPORTED_SOURCE_FORMATS",
    "ProjectBundleError",
    "ProjectBundleSaveResult",
    "ProjectLoadResult",
    "ProjectLoadState",
    "PreparedGeometrySnapshotResult",
    "PreparedGeometrySnapshotWorkload",
    "inspect_project_path",
    "inspect_prepared_geometry_snapshot_workload",
    "load_project_bundle",
    "save_project_bundle",
    "save_project_bundle_in_parent",
]
