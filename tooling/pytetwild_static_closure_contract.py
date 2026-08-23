#!/usr/bin/env python3
"""Load and validate the PyTetWild static-link closure contract.

The checked-in manifest describes native projects whose code is expected to be
compiled into the controlled ``PyfTetWildWrapper.pyd``.  This module is the
single strict parser for that manifest.  A structurally invalid or locally
unverifiable manifest raises :class:`ContractError`.  A well-formed manifest
whose release gate is intentionally blocked still loads, but its returned
contract is not release eligible and carries deterministic release issues.

The loader deliberately does not inspect a frozen application directory.  It
returns the exact controlled wrapper identity and packaged licence paths so a
binary-inventory caller can bind those records to the matching packaged file.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
MANIFEST_ID = "chromamatter-pytetwild-static-closure"
MANIFEST_REPOSITORY_PATH = "tooling/pytetwild_static_closure.json"
APPLICATION_LOCK_REPOSITORY_PATH = "source/fixed_app/requirements-build.lock"
RECIPE_REPOSITORY_PATH = "tooling/BUILD_PYTETWILD_WINDOWS.ps1"
LICENSE_REPOSITORY_PREFIX = PurePosixPath(
    "source/fixed_app/licenses/pytetwild-closure"
)
PACKAGED_LICENSE_PREFIX = PurePosixPath("_internal/licenses/pytetwild-closure")

PYTETWILD_PACKAGE = "pytetwild"
PYTETWILD_VERSION = "0.3.0"
PYTETWILD_WHEEL_TAG = "cp312-abi3-win_amd64"
PYTETWILD_PYD_RELATIVE_PATH = "pytetwild/PyfTetWildWrapper.pyd"

HISTORICAL_PYTETWILD_WHEEL_SHA256 = (
    "11964e295a54cf9e2f6920a920aeeba27668c9b14e369a86f72ec5baa4f46060"
)
HISTORICAL_PYTETWILD_PYD_BYTES = 5_897_728
HISTORICAL_PYTETWILD_PYD_SHA256 = (
    "ac801b37e298ee83be35f41193d384f64ef4b5064006e0019a209edff48495de"
)

EXPECTED_CMAKE_DEFINITIONS = frozenset(
    {
        "BUILD_SHARED_LIBS=OFF",
        "EIGEN_MPL2_ONLY=ON",
        "FLOAT_TETWILD_ENABLE_TBB=ON",
        "GEOGRAM_WITH_TBB=OFF",
        "LIBIGL_WITH_PREDICATES=ON",
    }
)
EXPECTED_COMPONENT_IDS = frozenset(
    {
        "eigen",
        "fmt",
        "ftetwild",
        "geogram",
        "geogram-amgcl",
        "geogram-libmeshb",
        "geogram-poissonrecon",
        "geogram-rply",
        "geogram-stb-image",
        "geogram-stb-image-write",
        "geogram-xatlas",
        "geogram-zlib",
        "jdumas-json",
        "libigl",
        "libigl-predicates",
        "nanobind",
        "nanobind-robin-map",
        "onetbb",
        "pytetwild",
        "spdlog",
    }
)
EXPECTED_SOURCE_ARCHIVE_IDS = frozenset(
    {
        "eigen-source",
        "fmt-source",
        "ftetwild-source",
        "geogram-amgcl-source",
        "geogram-libmeshb-source",
        "geogram-rply-source",
        "geogram-source",
        "jdumas-json-source",
        "libigl-predicates-source",
        "libigl-source",
        "nanobind-robin-map-source",
        "nanobind-source",
        "onetbb-source",
        "pytetwild-source",
        "spdlog-source",
    }
)
EXPECTED_LICENSE_ASSET_IDS = frozenset(
    {
        "eigen-apache",
        "eigen-bsd",
        "eigen-gpl",
        "eigen-lgpl",
        "eigen-minpack",
        "eigen-mpl2",
        "eigen-readme",
        "fmt-license",
        "ftetwild-mpl2",
        "geogram-amgcl-license",
        "geogram-libmeshb-license",
        "geogram-license",
        "geogram-poissonrecon-license",
        "geogram-rply-license",
        "geogram-stb-image-notice",
        "geogram-stb-image-write-notice",
        "geogram-xatlas-header-notice",
        "geogram-xatlas-source-notices",
        "geogram-zlib-license",
        "jdumas-json-license",
        "libigl-gpl",
        "libigl-mpl2",
        "libigl-predicates-readme",
        "libigl-predicates-source-notice",
        "nanobind-license",
        "nanobind-robin-map-license",
        "onetbb-license",
        "pytetwild-license",
        "spdlog-license",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REQUIREMENT_RE = re.compile(
    r"^pytetwild==(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)\s+"
    r"--hash=sha256:(?P<sha256>[0-9a-f]{64})$",
    re.IGNORECASE,
)
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)


class ContractError(RuntimeError):
    """Raised when the static-closure manifest cannot be trusted."""


@dataclass(frozen=True)
class ReleaseIssue:
    """One deterministic reason why this contract cannot approve a release."""

    code: str
    message: str


@dataclass(frozen=True)
class SourceArchive:
    archive_id: str
    filename: str
    kind: str
    source_url: str
    version: str
    revision: str
    bytes_size: int
    sha256: str


@dataclass(frozen=True)
class LicenseAsset:
    asset_id: str
    repository_path: str
    filesystem_path: Path
    packaged_path: str
    upstream_path: str
    bytes_size: int
    sha256: str


@dataclass(frozen=True)
class StaticComponent:
    component_id: str
    name: str
    version: str
    license_expression: str
    source_archive_ids: tuple[str, ...]
    license_asset_ids: tuple[str, ...]
    inclusion_basis: str
    dependencies: tuple[str, ...]
    license_route: str | None


@dataclass(frozen=True)
class PyTetWildStaticClosureContract:
    """Validated data needed by frozen-binary compliance integration."""

    manifest_path: Path
    manifest_sha256: str
    repository_root: Path
    recipe_path: Path
    recipe_sha256: str
    application_requirements_lock_path: Path
    application_requirements_lock_sha256: str
    application_wheel_sha256: str
    manifest_claims_release_eligible: bool
    release_eligible: bool
    release_issues: tuple[ReleaseIssue, ...]
    controlled_wheel_sha256: str | None
    controlled_pyd_sha256: str | None
    controlled_pyd_relative_path: str
    packaged_pyd_path: str
    historical_wheel_sha256: str
    historical_pyd_sha256: str
    source_archives: Mapping[str, SourceArchive]
    license_assets: Mapping[str, LicenseAsset]
    components: Mapping[str, StaticComponent]
    static_component_ids: tuple[str, ...]
    packaged_license_paths: Mapping[str, str]

    @property
    def release_issue_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.release_issues)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON member: {key}")
        result[key] = value
    return result


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"Cannot read {label}: {path}: {exc}") from exc
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{label} is not strict UTF-8: {path}") from exc
    try:
        value = json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except ContractError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"{label} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} root must be an object")
    return value, hashlib.sha256(payload).hexdigest()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContractError(f"{label} must be a non-empty trimmed string")
    if "\x00" in value:
        raise ContractError(f"{label} contains NUL")
    return value


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{label} must be a boolean")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ContractError(
            f"{label} members differ; missing={missing}, unexpected={unexpected}"
        )


def _id(value: Any, label: str) -> str:
    result = _string(value, label)
    if not _ID_RE.fullmatch(result):
        raise ContractError(f"{label} is not a canonical lowercase identifier")
    return result


def _sha256_value(value: Any, label: str) -> str:
    result = _string(value, label)
    if not _SHA256_RE.fullmatch(result):
        raise ContractError(f"{label} must be one lowercase SHA-256")
    return result


def _canonical_relative_path(value: Any, label: str) -> PurePosixPath:
    text = _string(value, label)
    if "\\" in text or ":" in text:
        raise ContractError(f"{label} must use a portable POSIX relative path")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or str(path) != text
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ContractError(f"{label} is not a canonical relative path")
    for part in path.parts:
        if part.rstrip(" .") != part:
            raise ContractError(f"{label} has a Windows-dangerous path segment")
        base = part.split(".", 1)[0].upper()
        if base in _WINDOWS_RESERVED_NAMES:
            raise ContractError(f"{label} contains a reserved Windows name")
    return path


def _safe_leaf(value: Any, label: str) -> str:
    path = _canonical_relative_path(value, label)
    if len(path.parts) != 1:
        raise ContractError(f"{label} must be a filename without directories")
    return path.name


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True


def _plain_file_under(
    repository_root: Path,
    relative_path: PurePosixPath,
    allowed_root: Path,
    label: str,
) -> Path:
    cursor = repository_root
    for part in relative_path.parts:
        cursor = cursor / part
        if _is_link_like(cursor):
            raise ContractError(f"{label} is or traverses a link/reparse point: {cursor}")
    if not cursor.is_file():
        raise ContractError(f"{label} is missing or not a file: {cursor}")
    try:
        resolved = cursor.resolve(strict=True)
        resolved_allowed = allowed_root.resolve(strict=True)
        resolved.relative_to(resolved_allowed)
    except (OSError, ValueError) as exc:
        raise ContractError(f"{label} escaped its allowed directory: {cursor}") from exc
    return resolved


def _canonical_repository_file(
    repository_root: Path,
    repository_path: str,
    supplied_path: str | os.PathLike[str] | None,
    label: str,
) -> Path:
    relative = _canonical_relative_path(repository_path, f"{label} repository path")
    expected = repository_root.joinpath(*relative.parts)
    candidate = expected if supplied_path is None else Path(supplied_path)
    try:
        if candidate.resolve(strict=True) != expected.resolve(strict=True):
            raise ContractError(f"{label} must be the canonical repository file: {expected}")
    except OSError as exc:
        raise ContractError(f"{label} is missing: {candidate}") from exc
    return _plain_file_under(repository_root, relative, repository_root, label)


def _string_id_array(value: Any, label: str) -> tuple[str, ...]:
    items = _list(value, label)
    if not items:
        raise ContractError(f"{label} must not be empty")
    result = tuple(_id(item, f"{label}[{index}]") for index, item in enumerate(items))
    if len(result) != len(set(result)):
        raise ContractError(f"{label} contains duplicates")
    return result


def _https_url(value: Any, label: str) -> str:
    url = _string(value, label)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ContractError(f"{label} must be a credential-free HTTPS URL")
    return url


def _parse_source_archives(value: Any) -> dict[str, SourceArchive]:
    raw = _mapping(value, "source_archives")
    if set(raw) != EXPECTED_SOURCE_ARCHIVE_IDS:
        raise ContractError(
            "source_archives must contain the complete conservative source set; "
            f"expected={sorted(EXPECTED_SOURCE_ARCHIVE_IDS)}, actual={sorted(raw)}"
        )
    result: dict[str, SourceArchive] = {}
    filenames: set[str] = set()
    for archive_id in sorted(raw):
        _id(archive_id, f"source_archives key {archive_id!r}")
        record = _mapping(raw[archive_id], f"source_archives.{archive_id}")
        _exact_keys(
            record,
            {"filename", "kind", "source_url", "version", "revision", "bytes", "sha256"},
            f"source_archives.{archive_id}",
        )
        filename = _safe_leaf(record["filename"], f"source_archives.{archive_id}.filename")
        folded_filename = filename.casefold()
        if folded_filename in filenames:
            raise ContractError(f"Duplicate source archive filename: {filename}")
        filenames.add(folded_filename)
        kind = _string(record["kind"], f"source_archives.{archive_id}.kind")
        if kind not in {"git-archive-zip", "github-codeload-zip", "upstream-tar-gz"}:
            raise ContractError(f"source_archives.{archive_id}.kind is unsupported")
        revision = _string(record["revision"], f"source_archives.{archive_id}.revision")
        if not _SHA1_RE.fullmatch(revision):
            raise ContractError(f"source_archives.{archive_id}.revision must be a full commit")
        result[archive_id] = SourceArchive(
            archive_id=archive_id,
            filename=filename,
            kind=kind,
            source_url=_https_url(
                record["source_url"], f"source_archives.{archive_id}.source_url"
            ),
            version=_string(record["version"], f"source_archives.{archive_id}.version"),
            revision=revision,
            bytes_size=_positive_integer(
                record["bytes"], f"source_archives.{archive_id}.bytes"
            ),
            sha256=_sha256_value(
                record["sha256"], f"source_archives.{archive_id}.sha256"
            ),
        )
    return result


def _parse_license_assets(
    value: Any,
    repository_root: Path,
) -> dict[str, LicenseAsset]:
    raw = _mapping(value, "license_assets")
    if set(raw) != EXPECTED_LICENSE_ASSET_IDS:
        raise ContractError(
            "license_assets must contain the complete conservative notice set; "
            f"expected={sorted(EXPECTED_LICENSE_ASSET_IDS)}, actual={sorted(raw)}"
        )
    asset_root = repository_root.joinpath(*LICENSE_REPOSITORY_PREFIX.parts)
    result: dict[str, LicenseAsset] = {}
    repository_paths: set[str] = set()
    packaged_paths: set[str] = set()
    for asset_id in sorted(raw):
        _id(asset_id, f"license_assets key {asset_id!r}")
        record = _mapping(raw[asset_id], f"license_assets.{asset_id}")
        _exact_keys(
            record,
            {"path", "upstream_path", "bytes", "sha256"},
            f"license_assets.{asset_id}",
        )
        repository_path = _canonical_relative_path(
            record["path"], f"license_assets.{asset_id}.path"
        )
        if repository_path.parts[: len(LICENSE_REPOSITORY_PREFIX.parts)] != (
            LICENSE_REPOSITORY_PREFIX.parts
        ):
            raise ContractError(
                f"license_assets.{asset_id}.path is outside {LICENSE_REPOSITORY_PREFIX}"
            )
        suffix = repository_path.parts[len(LICENSE_REPOSITORY_PREFIX.parts) :]
        if not suffix:
            raise ContractError(f"license_assets.{asset_id}.path names no file")
        packaged_path = PACKAGED_LICENSE_PREFIX.joinpath(*suffix)
        repository_key = str(repository_path).casefold()
        packaged_key = str(packaged_path).casefold()
        if repository_key in repository_paths or packaged_key in packaged_paths:
            raise ContractError(f"Duplicate/colliding licence asset path for {asset_id}")
        repository_paths.add(repository_key)
        packaged_paths.add(packaged_key)
        filesystem_path = _plain_file_under(
            repository_root,
            repository_path,
            asset_root,
            f"license_assets.{asset_id}.path",
        )
        bytes_size = _positive_integer(
            record["bytes"], f"license_assets.{asset_id}.bytes"
        )
        sha256 = _sha256_value(
            record["sha256"], f"license_assets.{asset_id}.sha256"
        )
        if filesystem_path.stat().st_size != bytes_size:
            raise ContractError(f"Licence asset byte count changed: {asset_id}")
        if _sha256(filesystem_path) != sha256:
            raise ContractError(f"Licence asset SHA-256 changed: {asset_id}")
        upstream_path = _canonical_relative_path(
            record["upstream_path"], f"license_assets.{asset_id}.upstream_path"
        )
        result[asset_id] = LicenseAsset(
            asset_id=asset_id,
            repository_path=str(repository_path),
            filesystem_path=filesystem_path,
            packaged_path=str(packaged_path),
            upstream_path=str(upstream_path),
            bytes_size=bytes_size,
            sha256=sha256,
        )
    return result


def _parse_components(
    value: Any,
    source_archives: Mapping[str, SourceArchive],
    license_assets: Mapping[str, LicenseAsset],
) -> dict[str, StaticComponent]:
    raw = _mapping(value, "components")
    if set(raw) != EXPECTED_COMPONENT_IDS:
        raise ContractError(
            "components must contain the complete conservative static closure; "
            f"expected={sorted(EXPECTED_COMPONENT_IDS)}, actual={sorted(raw)}"
        )
    result: dict[str, StaticComponent] = {}
    used_sources: set[str] = set()
    used_assets: set[str] = set()
    allowed_fields = {
        "name",
        "version",
        "license_expression",
        "source_archive_ids",
        "license_asset_ids",
        "inclusion_basis",
        "dependencies",
        "license_route",
    }
    required_fields = allowed_fields - {"dependencies", "license_route"}
    for component_id in sorted(raw):
        _id(component_id, f"components key {component_id!r}")
        record = _mapping(raw[component_id], f"components.{component_id}")
        actual_fields = set(record)
        if not required_fields <= actual_fields or not actual_fields <= allowed_fields:
            raise ContractError(
                f"components.{component_id} members differ; "
                f"missing={sorted(required_fields - actual_fields)}, "
                f"unexpected={sorted(actual_fields - allowed_fields)}"
            )
        source_ids = _string_id_array(
            record["source_archive_ids"],
            f"components.{component_id}.source_archive_ids",
        )
        asset_ids = _string_id_array(
            record["license_asset_ids"],
            f"components.{component_id}.license_asset_ids",
        )
        unknown_sources = set(source_ids) - set(source_archives)
        unknown_assets = set(asset_ids) - set(license_assets)
        if unknown_sources:
            raise ContractError(
                f"components.{component_id} references unknown source archives: "
                f"{sorted(unknown_sources)}"
            )
        if unknown_assets:
            raise ContractError(
                f"components.{component_id} references unknown licence assets: "
                f"{sorted(unknown_assets)}"
            )
        dependencies = (
            _string_id_array(
                record["dependencies"], f"components.{component_id}.dependencies"
            )
            if "dependencies" in record
            else ()
        )
        unknown_dependencies = set(dependencies) - EXPECTED_COMPONENT_IDS
        if unknown_dependencies or component_id in dependencies:
            raise ContractError(
                f"components.{component_id} has invalid dependencies: "
                f"{sorted(unknown_dependencies | ({component_id} & set(dependencies)))}"
            )
        license_route = (
            _string(record["license_route"], f"components.{component_id}.license_route")
            if "license_route" in record
            else None
        )
        result[component_id] = StaticComponent(
            component_id=component_id,
            name=_string(record["name"], f"components.{component_id}.name"),
            version=_string(record["version"], f"components.{component_id}.version"),
            license_expression=_string(
                record["license_expression"],
                f"components.{component_id}.license_expression",
            ),
            source_archive_ids=source_ids,
            license_asset_ids=asset_ids,
            inclusion_basis=_string(
                record["inclusion_basis"], f"components.{component_id}.inclusion_basis"
            ),
            dependencies=dependencies,
            license_route=license_route,
        )
        used_sources.update(source_ids)
        used_assets.update(asset_ids)
    if used_sources != set(source_archives):
        raise ContractError(
            f"Unreferenced source archives: {sorted(set(source_archives) - used_sources)}"
        )
    if used_assets != set(license_assets):
        raise ContractError(
            f"Unreferenced licence assets: {sorted(set(license_assets) - used_assets)}"
        )
    _reject_dependency_cycles(result)
    return result


def _reject_dependency_cycles(components: Mapping[str, StaticComponent]) -> None:
    active: set[str] = set()
    complete: set[str] = set()

    def visit(component_id: str) -> None:
        if component_id in complete:
            return
        if component_id in active:
            raise ContractError(f"Static component dependency cycle at {component_id}")
        active.add(component_id)
        for dependency in components[component_id].dependencies:
            visit(dependency)
        active.remove(component_id)
        complete.add(component_id)

    for component_id in components:
        visit(component_id)


def _parse_release_gate(value: Any) -> tuple[bool, list[dict[str, Any]]]:
    gate = _mapping(value, "release_gate")
    _exact_keys(gate, {"status", "release_eligible", "blockers"}, "release_gate")
    status = _string(gate["status"], "release_gate.status")
    claimed_eligible = _boolean(
        gate["release_eligible"], "release_gate.release_eligible"
    )
    blockers = _list(gate["blockers"], "release_gate.blockers")
    if not blockers:
        raise ContractError("release_gate.blockers must preserve the controlled-build gate")
    parsed: list[dict[str, Any]] = []
    blocker_ids: set[str] = set()
    for index, item in enumerate(blockers):
        blocker = _mapping(item, f"release_gate.blockers[{index}]")
        _exact_keys(
            blocker,
            {"id", "resolved", "reason"},
            f"release_gate.blockers[{index}]",
        )
        blocker_id = _id(blocker["id"], f"release_gate.blockers[{index}].id")
        if blocker_id in blocker_ids:
            raise ContractError(f"Duplicate release blocker: {blocker_id}")
        blocker_ids.add(blocker_id)
        parsed.append(
            {
                "id": blocker_id,
                "resolved": _boolean(
                    blocker["resolved"],
                    f"release_gate.blockers[{index}].resolved",
                ),
                "reason": _string(
                    blocker["reason"], f"release_gate.blockers[{index}].reason"
                ),
            }
        )
    unresolved = [blocker for blocker in parsed if not blocker["resolved"]]
    if claimed_eligible:
        if status != "release-approved" or unresolved:
            raise ContractError(
                "release_gate claims eligibility without release-approved/all-resolved state"
            )
    elif status != "blocked" or not unresolved:
        raise ContractError(
            "release_gate must be blocked with at least one unresolved blocker"
        )
    return claimed_eligible, parsed


def _parse_build_binding(
    value: Any,
    repository_root: Path,
    claimed_eligible: bool,
) -> tuple[Path, str, str | None, str | None, str]:
    build = _mapping(value, "build_binding")
    _exact_keys(
        build,
        {
            "recipe_path",
            "recipe_bytes",
            "recipe_sha256",
            "required_cmake_definitions",
            "source_archive_recipe",
            "historical_audited_package",
            "controlled_rebuild",
        },
        "build_binding",
    )
    recipe_relative = _canonical_relative_path(
        build["recipe_path"], "build_binding.recipe_path"
    )
    if str(recipe_relative) != RECIPE_REPOSITORY_PATH:
        raise ContractError(
            f"build_binding.recipe_path must be {RECIPE_REPOSITORY_PATH}"
        )
    recipe_path = _plain_file_under(
        repository_root,
        recipe_relative,
        repository_root / "tooling",
        "build recipe",
    )
    recipe_bytes = _positive_integer(build["recipe_bytes"], "build_binding.recipe_bytes")
    recipe_sha256 = _sha256_value(
        build["recipe_sha256"], "build_binding.recipe_sha256"
    )
    if recipe_path.stat().st_size != recipe_bytes:
        raise ContractError("Controlled PyTetWild recipe byte count changed")
    if _sha256(recipe_path) != recipe_sha256:
        raise ContractError("Controlled PyTetWild recipe SHA-256 changed")

    definitions_raw = _list(
        build["required_cmake_definitions"],
        "build_binding.required_cmake_definitions",
    )
    definitions = tuple(
        _string(item, f"build_binding.required_cmake_definitions[{index}]")
        for index, item in enumerate(definitions_raw)
    )
    if len(definitions) != len(set(definitions)) or set(definitions) != EXPECTED_CMAKE_DEFINITIONS:
        raise ContractError("Controlled PyTetWild CMake definitions are incomplete or changed")
    try:
        recipe_text = recipe_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ContractError("Controlled PyTetWild recipe is not readable UTF-8") from exc
    for definition in definitions:
        if f"'-D{definition}'" not in recipe_text:
            raise ContractError(f"Controlled recipe does not apply -D{definition}")

    archive_recipe = _mapping(
        build["source_archive_recipe"], "build_binding.source_archive_recipe"
    )
    _exact_keys(
        archive_recipe,
        {"tool", "tool_version", "arguments", "note"},
        "build_binding.source_archive_recipe",
    )
    if (
        _string(archive_recipe["tool"], "build_binding.source_archive_recipe.tool")
        != "PortableGit"
        or _string(
            archive_recipe["tool_version"],
            "build_binding.source_archive_recipe.tool_version",
        )
        != "2.55.0.windows.5"
        or archive_recipe["arguments"] != ["archive", "--format=zip"]
    ):
        raise ContractError("Controlled source-archive recipe identity changed")
    _string(archive_recipe["note"], "build_binding.source_archive_recipe.note")

    historical = _mapping(
        build["historical_audited_package"],
        "build_binding.historical_audited_package",
    )
    _exact_keys(
        historical,
        {
            "package",
            "version",
            "pyd_relative_path",
            "pyd_bytes",
            "pyd_sha256",
            "disposition",
            "reason",
        },
        "build_binding.historical_audited_package",
    )
    historical_values = {
        "package": PYTETWILD_PACKAGE,
        "version": PYTETWILD_VERSION,
        "pyd_relative_path": PYTETWILD_PYD_RELATIVE_PATH,
        "pyd_bytes": HISTORICAL_PYTETWILD_PYD_BYTES,
        "pyd_sha256": HISTORICAL_PYTETWILD_PYD_SHA256,
        "disposition": "excluded-historical-audit-only",
    }
    for field, expected in historical_values.items():
        if historical.get(field) != expected:
            raise ContractError(
                f"Historical PyTetWild identity/disposition changed at {field}"
            )
    _string(historical["reason"], "build_binding.historical_audited_package.reason")

    controlled = _mapping(
        build["controlled_rebuild"], "build_binding.controlled_rebuild"
    )
    _exact_keys(
        controlled,
        {
            "status",
            "package",
            "version",
            "wheel_tag",
            "wheel_sha256",
            "pyd_relative_path",
            "pyd_sha256",
            "approval_requires",
        },
        "build_binding.controlled_rebuild",
    )
    exact_controlled = {
        "package": PYTETWILD_PACKAGE,
        "version": PYTETWILD_VERSION,
        "wheel_tag": PYTETWILD_WHEEL_TAG,
        "pyd_relative_path": PYTETWILD_PYD_RELATIVE_PATH,
    }
    for field, expected in exact_controlled.items():
        if controlled.get(field) != expected:
            raise ContractError(f"Controlled PyTetWild identity changed at {field}")
    approval_requires = _list(
        controlled["approval_requires"],
        "build_binding.controlled_rebuild.approval_requires",
    )
    if (
        not all(isinstance(item, str) and item for item in approval_requires)
        or len(approval_requires) != len(set(approval_requires))
        or not {"wheel_sha256", "pyd_sha256"} <= set(approval_requires)
    ):
        raise ContractError("Controlled rebuild approval requirements are incomplete")

    status = _string(controlled["status"], "build_binding.controlled_rebuild.status")
    wheel_sha256 = controlled["wheel_sha256"]
    pyd_sha256 = controlled["pyd_sha256"]
    if claimed_eligible:
        if status != "approved":
            raise ContractError("Release-approved manifest lacks an approved controlled rebuild")
        wheel_sha256 = _sha256_value(
            wheel_sha256, "build_binding.controlled_rebuild.wheel_sha256"
        )
        pyd_sha256 = _sha256_value(
            pyd_sha256, "build_binding.controlled_rebuild.pyd_sha256"
        )
        if wheel_sha256 == HISTORICAL_PYTETWILD_WHEEL_SHA256:
            raise ContractError("Controlled wheel identity equals the excluded historical wheel")
        if pyd_sha256 == HISTORICAL_PYTETWILD_PYD_SHA256:
            raise ContractError("Controlled PYD identity equals the excluded historical PYD")
        if wheel_sha256 == pyd_sha256:
            raise ContractError("Controlled wheel and PYD cannot share one byte identity")
    else:
        if status != "blocked-awaiting-build" or wheel_sha256 is not None or pyd_sha256 is not None:
            raise ContractError(
                "Blocked manifest must await the build with null wheel/PYD identities"
            )
    return recipe_path, recipe_sha256, wheel_sha256, pyd_sha256, status


def _logical_requirement_records(text: str) -> list[str]:
    records: list[str] = []
    pending: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        continued = stripped.endswith("\\")
        piece = stripped[:-1].rstrip() if continued else stripped
        if piece:
            pending.append(piece)
        if continued:
            continue
        if pending:
            records.append(" ".join(pending))
            pending = []
    if pending:
        raise ContractError("Application requirements lock has an unterminated continuation")
    return records


def _application_pytetwild_binding(path: Path) -> tuple[str, str, str]:
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
    except OSError as exc:
        raise ContractError(f"Cannot read application requirements lock: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ContractError("Application requirements lock is not strict UTF-8") from exc
    matches: list[re.Match[str]] = []
    for record in _logical_requirement_records(text):
        if not re.match(r"^pytetwild(?:==|\s|\[)", record, re.IGNORECASE):
            continue
        match = _REQUIREMENT_RE.fullmatch(record)
        if match is None:
            raise ContractError(
                "PyTetWild application-lock record must contain one exact version and SHA-256"
            )
        matches.append(match)
    if len(matches) != 1:
        raise ContractError(
            f"Application requirements lock must contain one PyTetWild record, found {len(matches)}"
        )
    version = matches[0].group("version")
    sha256 = matches[0].group("sha256")
    if version != PYTETWILD_VERSION:
        raise ContractError(
            f"Application lock PyTetWild version is {version}, expected {PYTETWILD_VERSION}"
        )
    return version, sha256, hashlib.sha256(payload).hexdigest()


def load_pytetwild_static_closure_contract(
    manifest_path: str | os.PathLike[str] | None = None,
    *,
    repository_root: str | os.PathLike[str] | None = None,
    application_requirements_lock_path: str | os.PathLike[str] | None = None,
) -> PyTetWildStaticClosureContract:
    """Load the canonical repository manifest and validate it fail closed.

    ``release_eligible`` in the returned object is an effective decision.  It
    is true only when the manifest itself is release-approved *and* the
    canonical application requirements lock pins the exact controlled wheel.
    """

    root_input = (
        Path(repository_root)
        if repository_root is not None
        else Path(__file__).resolve().parents[1]
    )
    if not root_input.is_dir() or _is_link_like(root_input):
        raise ContractError(f"Repository root is missing or link-like: {root_input}")
    root = root_input.resolve(strict=True)
    manifest_file = _canonical_repository_file(
        root,
        MANIFEST_REPOSITORY_PATH,
        manifest_path,
        "PyTetWild static-closure manifest",
    )
    application_lock = _canonical_repository_file(
        root,
        APPLICATION_LOCK_REPOSITORY_PATH,
        application_requirements_lock_path,
        "application requirements lock",
    )
    manifest, manifest_sha256 = _load_json(
        manifest_file, "PyTetWild static-closure manifest"
    )
    _exact_keys(
        manifest,
        {
            "schema_version",
            "manifest_id",
            "scope",
            "release_gate",
            "build_binding",
            "source_archives",
            "license_assets",
            "components",
        },
        "manifest",
    )
    if manifest["schema_version"] != SCHEMA_VERSION or isinstance(
        manifest["schema_version"], bool
    ):
        raise ContractError(f"Unsupported static-closure schema: {manifest['schema_version']!r}")
    if manifest["manifest_id"] != MANIFEST_ID:
        raise ContractError(f"Unexpected static-closure manifest_id: {manifest['manifest_id']!r}")
    _string(manifest["scope"], "manifest.scope")

    claimed_eligible, blockers = _parse_release_gate(manifest["release_gate"])
    recipe_path, recipe_sha256, controlled_wheel, controlled_pyd, controlled_status = (
        _parse_build_binding(manifest["build_binding"], root, claimed_eligible)
    )
    source_archives = _parse_source_archives(manifest["source_archives"])
    license_assets = _parse_license_assets(manifest["license_assets"], root)
    components = _parse_components(
        manifest["components"], source_archives, license_assets
    )

    _version, application_wheel, application_lock_sha256 = (
        _application_pytetwild_binding(application_lock)
    )
    issues: list[ReleaseIssue] = []
    for blocker in blockers:
        if not blocker["resolved"]:
            issues.append(
                ReleaseIssue(
                    code=f"release-gate-blocker:{blocker['id']}",
                    message=blocker["reason"],
                )
            )
    if controlled_status != "approved":
        issues.append(
            ReleaseIssue(
                code="controlled-rebuild-not-approved",
                message="The controlled PyTetWild rebuild is not approved.",
            )
        )
    if controlled_wheel is None:
        issues.append(
            ReleaseIssue(
                code="controlled-wheel-identity-unavailable",
                message="The controlled PyTetWild wheel SHA-256 is unavailable.",
            )
        )
    if controlled_pyd is None:
        issues.append(
            ReleaseIssue(
                code="controlled-pyd-identity-unavailable",
                message="The controlled PyfTetWildWrapper.pyd SHA-256 is unavailable.",
            )
        )
    if application_wheel == HISTORICAL_PYTETWILD_WHEEL_SHA256:
        issues.append(
            ReleaseIssue(
                code="application-lock-uses-excluded-historical-wheel",
                message="The application lock still pins the excluded historical PyTetWild wheel.",
            )
        )
    if controlled_wheel is not None and application_wheel != controlled_wheel:
        issues.append(
            ReleaseIssue(
                code="application-lock-not-bound-to-controlled-wheel",
                message=(
                    "The canonical application lock does not pin the exact controlled "
                    "PyTetWild wheel SHA-256."
                ),
            )
        )

    effective_eligible = claimed_eligible and not issues
    packaged_pyd = str(
        PurePosixPath("_internal").joinpath(
            *_canonical_relative_path(
                PYTETWILD_PYD_RELATIVE_PATH, "controlled pyd relative path"
            ).parts
        )
    )
    packaged_license_paths = {
        asset_id: asset.packaged_path for asset_id, asset in license_assets.items()
    }
    return PyTetWildStaticClosureContract(
        manifest_path=manifest_file,
        manifest_sha256=manifest_sha256,
        repository_root=root,
        recipe_path=recipe_path,
        recipe_sha256=recipe_sha256,
        application_requirements_lock_path=application_lock,
        application_requirements_lock_sha256=application_lock_sha256,
        application_wheel_sha256=application_wheel,
        manifest_claims_release_eligible=claimed_eligible,
        release_eligible=effective_eligible,
        release_issues=tuple(issues),
        controlled_wheel_sha256=controlled_wheel,
        controlled_pyd_sha256=controlled_pyd,
        controlled_pyd_relative_path=PYTETWILD_PYD_RELATIVE_PATH,
        packaged_pyd_path=packaged_pyd,
        historical_wheel_sha256=HISTORICAL_PYTETWILD_WHEEL_SHA256,
        historical_pyd_sha256=HISTORICAL_PYTETWILD_PYD_SHA256,
        source_archives=MappingProxyType(source_archives),
        license_assets=MappingProxyType(license_assets),
        components=MappingProxyType(components),
        static_component_ids=tuple(sorted(components)),
        packaged_license_paths=MappingProxyType(packaged_license_paths),
    )


__all__ = [
    "ContractError",
    "LicenseAsset",
    "PyTetWildStaticClosureContract",
    "ReleaseIssue",
    "SourceArchive",
    "StaticComponent",
    "load_pytetwild_static_closure_contract",
]
