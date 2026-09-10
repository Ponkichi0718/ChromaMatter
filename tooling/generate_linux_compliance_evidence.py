#!/usr/bin/env python3
"""Generate fail-closed Linux x86_64 binary-compliance evidence.

The tool inventories an already audited PyInstaller one-folder application,
binds it to the exact Linux dependency lock and source commit, validates the
packaged licence payload, and writes a component map, SPDX 2.3 SBOM, and
corresponding-source candidate manifest.  It deliberately never grants
distribution approval.  Source staging, archive verification, and an explicit
owner decision are separate gates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.parser
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any, Iterable, Sequence
import unicodedata


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = Path(__file__).with_name("linux_compliance_components.json")
DEFAULT_CLOSURE_CONTRACT = Path(__file__).with_name(
    "linux_native_closure_contract.json"
)
DEFAULT_LOCK = (
    REPO_ROOT / "source" / "fixed_app" / "requirements-build-linux-x86_64.lock"
)
TEMPLATE_ROOT = REPO_ROOT / "licenses" / "linux"

APP_DIRECTORY_NAME = "ChromaMatter-Linux-Alpha"
APP_EXECUTABLE = "ChromaMatter"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
LOCK_RE = re.compile(
    r"^([A-Za-z0-9_.-]+)==([^\s]+)\s+--hash=sha256:([0-9a-f]{64})$"
)
EXPECTED_NATIVE_CLOSURE_OWNERS = (
    "native-runtime:bundled-linux-system-library-closure",
    "native-runtime:cpython-3.13.14-linux-runtime",
    "native-runtime:tcl-tk-9.0.4-linux-runtime",
    "python-distribution:glcontext",
    "python-distribution:manifold3d",
    "python-distribution:mapbox-earcut",
    "python-distribution:moderngl",
    "python-distribution:numpy",
    "python-distribution:pillow",
    "python-distribution:pyinstaller",
    "python-distribution:pymeshlab",
    "python-distribution:pytetwild",
    "python-distribution:rtree",
    "python-distribution:scipy",
    "python-distribution:shapely",
    "python-distribution:tetgen",
)
REQUIRED_CLOSURE_EVIDENCE = (
    "native-file-identity",
    "corresponding-source",
    "license-assets",
    "controlled-build",
    "runtime-dependency-map",
    "relink-validation",
    "functional-validation",
)
REQUIRED_CLOSURE_EVIDENCE_FILES = (
    "license_manifest",
    "build_attestation",
    "runtime_dependency_map",
    "relink_validation",
    "functional_validation",
)
CLOSURE_EVIDENCE_SCHEMAS = {
    label: f"chromamatter.linux-native-closure-{label.replace('_', '-')}.v1"
    for label in REQUIRED_CLOSURE_EVIDENCE_FILES
}
OWNERS_REQUIRING_ADDITIONAL_SOURCES = {
    "native-runtime:bundled-linux-system-library-closure",
    "native-runtime:tcl-tk-9.0.4-linux-runtime",
    "python-distribution:numpy",
    "python-distribution:pillow",
    "python-distribution:pymeshlab",
    "python-distribution:pytetwild",
    "python-distribution:rtree",
    "python-distribution:scipy",
    "python-distribution:shapely",
    "python-distribution:tetgen",
}
REQUIRED_AUDIT_FACTS = (
    "In-app display version: 0.9",
    "Dependency-wheel glibc floor: 2.35",
    "ELF architecture: x86_64 only",
    "Unresolved ELF dependencies: none",
    "Build-host absolute path leakage: none found",
    "Symlink confinement: passed",
    "Private model/toolpath payloads: none",
    "pip direct_url.json files: none",
    "Public or tester distribution approved: no",
)
TEMPLATE_OUTPUTS = {
    "BUILD_FROM_SOURCE_EN.md": "BUILD_FROM_SOURCE_EN.md",
    "BUILD_FROM_SOURCE_JA.md": "BUILD_FROM_SOURCE_JA.md",
    "RELINKING_EN.md": "RELINKING_EN.md",
    "RELINKING_JA.md": "RELINKING_JA.md",
    "SOURCE_OFFER_STATUS_EN.txt": "LINUX_ALPHA_SOURCE_OFFER_STATUS_EN.txt",
    "SOURCE_OFFER_STATUS_JA.txt": "LINUX_ALPHA_SOURCE_OFFER_STATUS_JA.txt",
}
REQUIRED_OUTPUTS = (
    "LINUX_APP_INVENTORY.json",
    "LINUX_NATIVE_CLOSURE_CONTRACT.json",
    "BINARY_COMPONENT_MAP.json",
    "SBOM.spdx.json",
    "CORRESPONDING_SOURCE_MANIFEST.json",
    "DISTRIBUTION_APPROVAL.json",
    *TEMPLATE_OUTPUTS.values(),
)


class EvidenceError(RuntimeError):
    """Raised when observed bytes cannot support honest evidence."""


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json_payload(payload: dict[str, Any]) -> str:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvidenceError(f"JSON root must be an object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def safe_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise EvidenceError(f"{label} must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise EvidenceError(f"{label} is unsafe: {value!r}")
    return path.as_posix()


def portable_key(value: str) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in PurePosixPath(value).parts)


def parse_lock(path: Path) -> dict[str, dict[str, str]]:
    try:
        logical = path.read_text(encoding="utf-8").replace("\\\n", " ")
    except (OSError, UnicodeError) as exc:
        raise EvidenceError(f"Cannot read Linux dependency lock: {exc}") from exc
    result: dict[str, dict[str, str]] = {}
    for line in logical.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = LOCK_RE.fullmatch(stripped)
        if match is None:
            raise EvidenceError(f"Malformed Linux lock row: {stripped!r}")
        name = canonical_name(match.group(1))
        if name in result:
            raise EvidenceError(f"Duplicate Linux lock package: {name}")
        result[name] = {"version": match.group(2), "wheel_sha256": match.group(3)}
    if not result:
        raise EvidenceError("Linux dependency lock contains no requirements")
    return result


def _validate_https(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise EvidenceError(f"{label} must be an HTTPS URL")
    return value


def validate_catalog(
    catalog: dict[str, Any], locked: dict[str, dict[str, str]]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if catalog.get("schema") != "chromamatter.linux-compliance-component-catalog.v1":
        raise EvidenceError("Unsupported Linux component catalog schema")
    application = catalog.get("application")
    if not isinstance(application, dict) or application.get("version") != "0.9":
        raise EvidenceError("Linux catalog application/version is invalid")
    _validate_https(application.get("source_url"), "application source URL")
    raw = catalog.get("distributions")
    if not isinstance(raw, dict):
        raise EvidenceError("Linux catalog distributions must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_name, component in raw.items():
        name = canonical_name(str(raw_name))
        if name in normalized or not isinstance(component, dict):
            raise EvidenceError(f"Invalid or duplicate Linux catalog entry: {raw_name}")
        if name not in locked or component.get("version") != locked[name]["version"]:
            raise EvidenceError(f"Linux catalog/lock version mismatch: {name}")
        if not isinstance(component.get("license_declared"), str):
            raise EvidenceError(f"Missing declared licence for {name}")
        _validate_https(component.get("source_url"), f"{name} source URL")
        source_sha = component.get("source_sha256")
        source_commit = component.get("source_commit")
        if bool(source_sha) == bool(source_commit):
            raise EvidenceError(f"{name} must have exactly one fixed source identity")
        if source_sha and (not isinstance(source_sha, str) or not SHA256_RE.fullmatch(source_sha)):
            raise EvidenceError(f"Invalid source SHA-256 for {name}")
        if source_commit and (
            not isinstance(source_commit, str) or not COMMIT_RE.fullmatch(source_commit)
        ):
            raise EvidenceError(f"Invalid source commit for {name}")
        prefixes = component.get("path_prefixes")
        if not isinstance(prefixes, list) or not prefixes:
            raise EvidenceError(f"No package path prefixes for {name}")
        for index, prefix in enumerate(prefixes):
            safe_relative_path(prefix, f"{name}.path_prefixes[{index}]")
        if not isinstance(component.get("native_closure_status"), str):
            raise EvidenceError(f"Missing native closure status for {name}")
        normalized[name] = component
    if set(normalized) != set(locked):
        raise EvidenceError(
            "Linux catalog does not exactly cover lock; "
            f"missing={sorted(set(locked) - set(normalized))}, "
            f"extra={sorted(set(normalized) - set(locked))}"
        )
    exclusions = catalog.get("intentionally_not_packaged")
    if not isinstance(exclusions, dict) or not exclusions:
        raise EvidenceError("Linux catalog has no explicit runtime exclusions")
    exclusion_names = {canonical_name(str(name)) for name in exclusions}
    if not exclusion_names <= set(locked):
        raise EvidenceError("Linux runtime exclusion is absent from the dependency lock")
    groups = catalog.get("native_runtime_groups")
    if not isinstance(groups, list) or not groups:
        raise EvidenceError("Linux catalog has no native runtime groups")
    seen_groups: set[str] = set()
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("id"), str):
            raise EvidenceError("Malformed native runtime group")
        group_id = group["id"]
        if group_id in seen_groups:
            raise EvidenceError(f"Duplicate native runtime group: {group_id}")
        seen_groups.add(group_id)
        _validate_https(group.get("source_url"), f"{group_id} source URL")
        source_sha = group.get("source_sha256")
        source_commit = group.get("source_commit")
        if source_sha is not None and (
            not isinstance(source_sha, str) or not SHA256_RE.fullmatch(source_sha)
        ):
            raise EvidenceError(f"Invalid native source SHA-256: {group_id}")
        if source_commit is not None and (
            not isinstance(source_commit, str) or not COMMIT_RE.fullmatch(source_commit)
        ):
            raise EvidenceError(f"Invalid native source commit: {group_id}")
        if not isinstance(group.get("closure_status"), str):
            raise EvidenceError(f"Missing native closure status: {group_id}")
        prefixes = group.get("path_prefixes", [])
        regexes = group.get("path_regexes", [])
        if not isinstance(prefixes, list) or not isinstance(regexes, list) or not (prefixes or regexes):
            raise EvidenceError(f"Native group has no ownership rule: {group_id}")
        for index, prefix in enumerate(prefixes):
            safe_relative_path(prefix, f"{group_id}.path_prefixes[{index}]")
        for expression in regexes:
            try:
                re.compile(expression)
            except (TypeError, re.error) as exc:
                raise EvidenceError(f"Invalid native group regex: {group_id}") from exc
    return normalized, groups


def _catalog_closure_statuses(
    components: dict[str, dict[str, Any]], groups: list[dict[str, Any]]
) -> dict[str, str]:
    statuses = {
        f"python-distribution:{name}": component["native_closure_status"]
        for name, component in components.items()
        if component["native_closure_status"] != "not-applicable"
    }
    statuses.update(
        {
            f"native-runtime:{group['id']}": group["closure_status"]
            for group in groups
            if group["closure_status"] != "not-applicable"
        }
    )
    return statuses


def validate_closure_contract(
    contract: dict[str, Any],
    components: dict[str, dict[str, Any]],
    groups: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if contract.get("schema") != "chromamatter.linux-native-closure-contract.v1":
        raise EvidenceError("Unsupported Linux native-closure contract schema")
    if contract.get("scope") != "linux-x86_64-technical-alpha":
        raise EvidenceError("Linux native-closure contract scope is invalid")
    if contract.get("expected_owner_count") != len(EXPECTED_NATIVE_CLOSURE_OWNERS):
        raise EvidenceError("Linux native-closure contract owner count is invalid")
    expected = set(EXPECTED_NATIVE_CLOSURE_OWNERS)
    catalog_statuses = _catalog_closure_statuses(components, groups)
    if set(catalog_statuses) != expected:
        raise EvidenceError(
            "Linux catalog native-closure owner set changed; "
            f"missing={sorted(expected - set(catalog_statuses))}, "
            f"extra={sorted(set(catalog_statuses) - expected)}"
        )
    owners = contract.get("owners")
    if not isinstance(owners, dict) or set(owners) != expected:
        observed = set(owners) if isinstance(owners, dict) else set()
        raise EvidenceError(
            "Linux native-closure contract owner coverage mismatch; "
            f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
        )
    normalized: dict[str, dict[str, Any]] = {}
    verified_count = 0
    required_keys = {
        "declared_status",
        "verification_status",
        "required_evidence",
        "proof",
    }
    for owner in EXPECTED_NATIVE_CLOSURE_OWNERS:
        record = owners[owner]
        if not isinstance(record, dict) or set(record) != required_keys:
            raise EvidenceError(f"Linux native-closure record fields are invalid: {owner}")
        if record.get("declared_status") != catalog_statuses[owner]:
            raise EvidenceError(
                f"Linux native-closure declared status differs from catalog: {owner}"
            )
        if record.get("required_evidence") != list(REQUIRED_CLOSURE_EVIDENCE):
            raise EvidenceError(
                f"Linux native-closure required evidence changed: {owner}"
            )
        status = record.get("verification_status")
        proof = record.get("proof")
        if status == "blocked-unverified":
            if proof is not None:
                raise EvidenceError(
                    f"Blocked Linux native closure must not carry an unvalidated proof: {owner}"
                )
        elif status == "verified":
            if not isinstance(proof, dict):
                raise EvidenceError(
                    f"Verified Linux native closure has no proof object: {owner}"
                )
            verified_count += 1
        else:
            raise EvidenceError(
                f"Linux native-closure verification status is invalid: {owner}"
            )
        normalized[owner] = record
    expected_contract_status = (
        "verified" if verified_count == len(EXPECTED_NATIVE_CLOSURE_OWNERS)
        else "blocked-unverified"
    )
    if contract.get("contract_status") != expected_contract_status:
        raise EvidenceError("Linux native-closure aggregate status is invalid")
    return normalized


def validate_audit_report(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EvidenceError(f"Cannot read Linux native audit report: {exc}") from exc
    missing = [fact for fact in REQUIRED_AUDIT_FACTS if fact not in text]
    match = re.search(r"^ELF files checked:\s*(\d+)\s*$", text, flags=re.MULTILINE)
    if missing or match is None or int(match.group(1)) <= 0:
        raise EvidenceError(
            f"Linux native audit report is incomplete; missing={missing}, elf_count={match.group(1) if match else None}"
        )
    return {
        "path_name": path.name,
        "sha256": sha256_file(path),
        "elf_files_checked": int(match.group(1)),
        "required_facts": list(REQUIRED_AUDIT_FACTS),
    }


def _is_elf_x86_64(path: Path) -> bool:
    with path.open("rb") as handle:
        header = handle.read(20)
    if not header.startswith(b"\x7fELF"):
        return False
    if len(header) < 20 or header[4] != 2 or header[5] != 1:
        raise EvidenceError(f"ELF is not 64-bit little-endian: {path}")
    if int.from_bytes(header[18:20], "little") != 62:
        raise EvidenceError(f"ELF machine is not x86_64: {path}")
    return True


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_entries(root: Path) -> Iterable[tuple[Path, os.stat_result]]:
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise EvidenceError(f"Cannot scan Linux application directory: {directory}") from exc
        subdirectories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise EvidenceError(f"Cannot stat Linux application entry: {path}") from exc
            yield path, info
            if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                subdirectories.append(path)
        stack.extend(reversed(subdirectories))


def _read_metadata(path: Path) -> tuple[str, str]:
    try:
        message = email.parser.Parser().parsestr(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise EvidenceError(f"Cannot read packaged METADATA: {path}") from exc
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        raise EvidenceError(f"Packaged METADATA is missing Name/Version: {path}")
    return canonical_name(name), version


def _match_glob(paths: list[str], pattern: str) -> list[str]:
    folded_pattern = pattern.casefold()
    return sorted(path for path in paths if fnmatch.fnmatchcase(path.casefold(), folded_pattern))


def collect_inventory(
    app_directory: Path,
    audit_report: Path,
    catalog: dict[str, Any],
    components: dict[str, dict[str, Any]],
    locked: dict[str, dict[str, str]],
) -> dict[str, Any]:
    if not app_directory.is_dir() or app_directory.is_symlink():
        raise EvidenceError("Linux application input must be a real directory")
    app_directory = app_directory.resolve()
    if app_directory.name != APP_DIRECTORY_NAME:
        raise EvidenceError(f"Unexpected Linux application directory name: {app_directory.name}")
    executable = app_directory / APP_EXECUTABLE
    if not executable.is_file() or executable.is_symlink():
        raise EvidenceError("Linux application executable is missing or unsafe")

    seen: dict[tuple[str, ...], str] = {}
    regular_files: list[dict[str, Any]] = []
    symlinks: list[dict[str, Any]] = []
    elf_count = 0
    for path, info in _iter_entries(app_directory):
        relative = _relative(app_directory, path)
        key = portable_key(relative)
        if key in seen:
            raise EvidenceError(f"Portable application path collision: {seen[key]!r} / {relative!r}")
        seen[key] = relative
        if stat.S_ISDIR(info.st_mode):
            continue
        if stat.S_ISLNK(info.st_mode):
            raw_target = os.readlink(path)
            target = (path.parent / raw_target).resolve(strict=False)
            try:
                target.relative_to(app_directory)
            except ValueError as exc:
                raise EvidenceError(f"Linux package symlink escapes root: {relative}") from exc
            if not target.exists():
                raise EvidenceError(f"Linux package symlink is broken: {relative}")
            symlinks.append(
                {
                    "path": relative,
                    "target": raw_target,
                    "confined_to_application": True,
                    "target_exists": True,
                }
            )
            continue
        if not stat.S_ISREG(info.st_mode):
            raise EvidenceError(f"Unsupported Linux package entry type: {relative}")
        is_elf = _is_elf_x86_64(path)
        if is_elf:
            elf_count += 1
        mode = stat.S_IMODE(info.st_mode)
        executable_bit = bool(info.st_mode & 0o111)
        # Windows cannot persist POSIX execute bits in an ordinary temporary
        # test fixture.  Production evidence still runs on Linux; this narrow
        # branch exists only so the pure inventory logic remains unit-testable.
        if os.name == "nt":
            executable_bit = os.access(path, os.X_OK)
        regular_files.append(
            {
                "path": relative,
                "size": info.st_size,
                "sha256": sha256_file(path),
                "mode": mode,
                "executable": executable_bit,
                "elf": {"class": 64, "endianness": "little", "machine": "x86_64"}
                if is_elf
                else None,
            }
        )
    regular_files.sort(key=lambda row: portable_key(row["path"]))
    symlinks.sort(key=lambda row: portable_key(row["path"]))
    if elf_count == 0:
        raise EvidenceError("Linux application contains no x86_64 ELF files")
    executable_row = next((row for row in regular_files if row["path"] == APP_EXECUTABLE), None)
    if executable_row is None or not executable_row["executable"] or executable_row["elf"] is None:
        raise EvidenceError("Linux launcher is not an executable x86_64 ELF file")

    paths = [row["path"] for row in regular_files] + [row["path"] for row in symlinks]
    forbidden: list[str] = []
    patterns = catalog.get("forbidden_payload_globs")
    if not isinstance(patterns, list) or not patterns:
        raise EvidenceError("Linux catalog has no forbidden-payload policy")
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            raise EvidenceError("Linux forbidden-payload glob is malformed")
        forbidden.extend(f"{pattern}:{match}" for match in _match_glob(paths, pattern))
    if forbidden:
        raise EvidenceError("Forbidden Linux package payloads: " + ", ".join(sorted(set(forbidden))))

    packaged: dict[str, dict[str, Any]] = {}
    for row in regular_files:
        path = row["path"]
        if not path.casefold().endswith(".dist-info/metadata"):
            continue
        name, version = _read_metadata(app_directory / PurePosixPath(path))
        if name in packaged:
            raise EvidenceError(f"Duplicate packaged distribution metadata: {name}")
        dist_info = str(PurePosixPath(path).parent)
        record_path = f"{dist_info}/RECORD"
        record = next((item for item in regular_files if item["path"].casefold() == record_path.casefold()), None)
        if record is None:
            raise EvidenceError(f"Packaged distribution has no RECORD: {name}")
        if name not in components or version != locked[name]["version"]:
            raise EvidenceError(f"Packaged distribution does not match Linux lock: {name} {version}")
        licence_prefix = f"_internal/licenses/wheels/{name}/"
        licence_files = [
            item
            for item in regular_files
            if item["path"].casefold().startswith(licence_prefix.casefold())
        ]
        if not licence_files:
            raise EvidenceError(f"Packaged distribution has no wheel licence payload: {name}")
        packaged[name] = {
            "name": name,
            "version": version,
            "dist_info_path": dist_info,
            "record": {key: record[key] for key in ("path", "size", "sha256")},
            "licence_files": [
                {key: item[key] for key in ("path", "size", "sha256")}
                for item in licence_files
            ],
            "direct_url_metadata_present": any(
                candidate.casefold() == f"{dist_info}/direct_url.json".casefold()
                for candidate in paths
            ),
            "locked_wheel_sha256": locked[name]["wheel_sha256"],
        }
        if packaged[name]["direct_url_metadata_present"]:
            raise EvidenceError(f"Packaged direct_url.json is forbidden: {name}")

    exclusions = {canonical_name(str(name)) for name in catalog["intentionally_not_packaged"]}
    expected = set(components) - exclusions
    if set(packaged) != expected:
        raise EvidenceError(
            "Packaged Linux distributions do not exactly match policy; "
            f"missing={sorted(expected - set(packaged))}, extra={sorted(set(packaged) - expected)}"
        )
    for excluded in exclusions:
        for prefix in components[excluded]["path_prefixes"]:
            if any(
                path.casefold() == prefix.casefold()
                or path.casefold().startswith(prefix.casefold().rstrip("/") + "/")
                for path in paths
            ):
                raise EvidenceError(f"Intentionally excluded distribution is packaged: {excluded}")

    required_globs = catalog.get("required_application_license_globs")
    if not isinstance(required_globs, list) or not required_globs:
        raise EvidenceError("Linux catalog has no application licence requirements")
    required_licences: list[dict[str, Any]] = []
    files_by_path = {row["path"].casefold(): row for row in regular_files}
    for pattern in required_globs:
        matches = _match_glob([row["path"] for row in regular_files], pattern)
        if len(matches) != 1:
            raise EvidenceError(f"Required Linux licence pattern must match once: {pattern} -> {matches}")
        row = files_by_path[matches[0].casefold()]
        required_licences.append({key: row[key] for key in ("path", "size", "sha256")})

    audit = validate_audit_report(audit_report.resolve(strict=True))
    if audit["elf_files_checked"] != elf_count:
        raise EvidenceError(
            f"Linux native audit/inventory ELF count mismatch: {audit['elf_files_checked']} != {elf_count}"
        )
    return {
        "schema": "chromamatter.linux-app-inventory.v1",
        "purpose": "exact application byte/mode/symlink inventory; not distribution approval",
        "application": {
            "root_name": app_directory.name,
            "executable": APP_EXECUTABLE,
            "version": "0.9",
        },
        "counts": {
            "regular_files": len(regular_files),
            "symlinks": len(symlinks),
            "elf_files": elf_count,
            "packaged_distributions": len(packaged),
        },
        "audit_report": audit,
        "regular_files": regular_files,
        "symlinks": symlinks,
        "packaged_distributions": [packaged[name] for name in sorted(packaged)],
        "licence_validation": {
            "status": "passed",
            "required_application_licences": required_licences,
            "wheel_licence_distribution_count": len(packaged),
        },
    }


def _prefix_match(path: str, prefix: str) -> bool:
    folded = path.casefold()
    normalized = prefix.casefold().rstrip("/")
    return folded == normalized or folded.startswith(normalized + "/") or folded.startswith(normalized + ".")


def _native_owner(
    path: str,
    components: dict[str, dict[str, Any]],
    groups: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    matches: list[tuple[int, str, str]] = []
    for name, component in components.items():
        for prefix in component["path_prefixes"]:
            if _prefix_match(path, prefix):
                matches.append((10000 + len(prefix), f"python-distribution:{name}", component["native_closure_status"]))
    for group in groups:
        for prefix in group.get("path_prefixes", []):
            if _prefix_match(path, prefix):
                matches.append((10000 + len(prefix), f"native-runtime:{group['id']}", group["closure_status"]))
        for expression in group.get("path_regexes", []):
            if re.fullmatch(expression, path, flags=re.IGNORECASE):
                # Regex rules are intentionally lower-priority catch-alls.
                # An explicit distribution/native prefix must win over the
                # broad top-level system-library expression.
                matches.append((len(expression), f"native-runtime:{group['id']}", group["closure_status"]))
    if not matches:
        return None, None
    best_length = max(row[0] for row in matches)
    best = {(owner, status) for length, owner, status in matches if length == best_length}
    if len(best) != 1:
        return None, "ambiguous-owner"
    return next(iter(best))


def _source_record(
    source_id: str,
    name: str,
    version: str,
    licence: str,
    source_url: str,
    *,
    source_sha256: str | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    identity_kind = "archive-sha256" if source_sha256 else "git-commit"
    return {
        "source_id": source_id,
        "name": name,
        "version": version,
        "license_declared": licence,
        "identity_kind": identity_kind,
        "source_url": source_url,
        "source_sha256": source_sha256,
        "source_commit": source_commit,
        "required_for_corresponding_source": True,
    }


def _validate_closure_source_record(
    owner: str, record: object
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise EvidenceError(f"Linux closure source record is not an object: {owner}")
    required = {
        "source_id",
        "name",
        "version",
        "license_declared",
        "identity_kind",
        "source_url",
        "source_sha256",
        "source_commit",
        "required_for_corresponding_source",
    }
    if set(record) != required:
        raise EvidenceError(f"Linux closure source record fields are invalid: {owner}")
    source_id = record.get("source_id")
    if (
        not isinstance(source_id, str)
        or not source_id.startswith(f"closure-source:{owner}:")
    ):
        raise EvidenceError(f"Linux closure source id is invalid: {owner}")
    for key in ("name", "version", "license_declared"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise EvidenceError(f"Linux closure source {key} is invalid: {source_id}")
    _validate_https(record.get("source_url"), f"{source_id} source URL")
    source_sha = record.get("source_sha256")
    source_commit = record.get("source_commit")
    expected_kind = "archive-sha256" if source_sha else "git-commit"
    if record.get("identity_kind") != expected_kind or bool(source_sha) == bool(source_commit):
        raise EvidenceError(f"Linux closure source identity kind is invalid: {source_id}")
    if source_sha and (
        not isinstance(source_sha, str) or not SHA256_RE.fullmatch(source_sha)
    ):
        raise EvidenceError(f"Linux closure source SHA-256 is invalid: {source_id}")
    if source_commit and (
        not isinstance(source_commit, str) or not COMMIT_RE.fullmatch(source_commit)
    ):
        raise EvidenceError(f"Linux closure source commit is invalid: {source_id}")
    if record.get("required_for_corresponding_source") is not True:
        raise EvidenceError(f"Linux closure source was marked optional: {source_id}")
    return dict(record)


def _validate_closure_evidence_file(
    owner: str,
    label: str,
    record: object,
    evidence_root: Path,
    native_file_set_sha256: str,
) -> dict[str, str]:
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise EvidenceError(
            f"Linux native-closure evidence reference is invalid: {owner}:{label}"
        )
    relative = safe_relative_path(
        record.get("path"), f"Linux native-closure evidence path {owner}:{label}"
    )
    digest = record.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise EvidenceError(
            f"Linux native-closure evidence SHA-256 is invalid: {owner}:{label}"
        )
    path = evidence_root.joinpath(*PurePosixPath(relative).parts)
    if not path.is_file() or path.is_symlink():
        raise EvidenceError(
            f"Linux native-closure evidence file is missing or unsafe: {owner}:{label}"
        )
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(evidence_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise EvidenceError(
            f"Linux native-closure evidence file escapes its root: {owner}:{label}"
        ) from exc
    if sha256_file(path) != digest:
        raise EvidenceError(
            f"Linux native-closure evidence file hash mismatch: {owner}:{label}"
        )
    payload = read_json(path)
    if (
        payload.get("schema") != CLOSURE_EVIDENCE_SCHEMAS[label]
        or payload.get("owner") != owner
        or payload.get("status") != "verified"
        or payload.get("native_file_set_sha256") != native_file_set_sha256
        or not isinstance(payload.get("evidence"), list)
        or not payload["evidence"]
    ):
        raise EvidenceError(
            f"Linux native-closure evidence payload is incomplete: {owner}:{label}"
        )
    return {
        "path": relative,
        "sha256": digest,
        "schema": CLOSURE_EVIDENCE_SCHEMAS[label],
    }


def evaluate_closure_contract(
    records: dict[str, dict[str, Any]],
    native_files_by_owner: dict[str, list[dict[str, Any]]],
    locked: dict[str, dict[str, str]],
    evidence_root: Path,
) -> tuple[dict[str, str], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    observed = set(native_files_by_owner)
    expected = set(EXPECTED_NATIVE_CLOSURE_OWNERS)
    if observed != expected:
        raise EvidenceError(
            "Linux application native-closure owner set changed; "
            f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
        )
    if not evidence_root.is_dir() or evidence_root.is_symlink():
        raise EvidenceError("Linux native-closure evidence root must be a real directory")
    statuses: dict[str, str] = {}
    gaps: list[str] = []
    proof_summaries: list[dict[str, Any]] = []
    additional_sources: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for owner in EXPECTED_NATIVE_CLOSURE_OWNERS:
        record = records[owner]
        declared = record["declared_status"]
        if record["verification_status"] == "blocked-unverified":
            statuses[owner] = declared
            gaps.append(f"native-closure-proof-blocked:{owner}:{declared}")
            proof_summaries.append(
                {
                    "owner": owner,
                    "verification_status": "blocked-unverified",
                    "effective_closure_status": declared,
                    "required_evidence": list(REQUIRED_CLOSURE_EVIDENCE),
                    "proof_bound": False,
                }
            )
            continue
        proof = record["proof"]
        required_proof_fields = {
            "schema",
            "owner",
            "locked_wheel_sha256",
            "native_files",
            "additional_sources",
            "evidence_files",
        }
        if set(proof) != required_proof_fields:
            raise EvidenceError(f"Linux native-closure proof fields are invalid: {owner}")
        if (
            proof.get("schema") != "chromamatter.linux-native-closure-proof.v1"
            or proof.get("owner") != owner
        ):
            raise EvidenceError(f"Linux native-closure proof identity is invalid: {owner}")
        wheel_sha = proof.get("locked_wheel_sha256")
        if owner.startswith("python-distribution:"):
            name = owner.split(":", 1)[1]
            if wheel_sha != locked[name]["wheel_sha256"]:
                raise EvidenceError(
                    f"Linux native-closure proof wheel identity mismatch: {owner}"
                )
        elif wheel_sha is not None:
            raise EvidenceError(
                f"Linux runtime closure proof must not claim a wheel identity: {owner}"
            )
        expected_native = sorted(
            (
                {key: row[key] for key in ("path", "size", "sha256", "mode")}
                for row in native_files_by_owner[owner]
            ),
            key=lambda row: portable_key(row["path"]),
        )
        observed_native = proof.get("native_files")
        if observed_native != expected_native:
            raise EvidenceError(
                f"Linux native-closure proof does not bind exact native files: {owner}"
            )
        native_file_set_sha256 = hashlib.sha256(
            json.dumps(
                expected_native, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        raw_sources = proof.get("additional_sources")
        if not isinstance(raw_sources, list):
            raise EvidenceError(f"Linux native-closure proof sources are invalid: {owner}")
        owner_sources = [
            _validate_closure_source_record(owner, source) for source in raw_sources
        ]
        if owner in OWNERS_REQUIRING_ADDITIONAL_SOURCES and not owner_sources:
            raise EvidenceError(
                f"Linux native closure still lacks fixed additional source identities: {owner}"
            )
        for source in owner_sources:
            source_id = source["source_id"]
            if source_id in source_ids:
                raise EvidenceError(f"Duplicate Linux closure source id: {source_id}")
            source_ids.add(source_id)
        evidence_files = proof.get("evidence_files")
        if (
            not isinstance(evidence_files, dict)
            or set(evidence_files) != set(REQUIRED_CLOSURE_EVIDENCE_FILES)
        ):
            raise EvidenceError(
                f"Linux native-closure proof evidence coverage mismatch: {owner}"
            )
        verified_files = {
            label: _validate_closure_evidence_file(
                owner,
                label,
                evidence_files[label],
                evidence_root,
                native_file_set_sha256,
            )
            for label in REQUIRED_CLOSURE_EVIDENCE_FILES
        }
        statuses[owner] = "verified-rebuild"
        additional_sources.extend(owner_sources)
        proof_summaries.append(
            {
                "owner": owner,
                "verification_status": "verified",
                "effective_closure_status": "verified-rebuild",
                "required_evidence": list(REQUIRED_CLOSURE_EVIDENCE),
                "proof_bound": True,
                "locked_wheel_sha256": wheel_sha,
                "native_file_count": len(expected_native),
                "native_file_set_sha256": native_file_set_sha256,
                "additional_source_ids": [source["source_id"] for source in owner_sources],
                "evidence_files": verified_files,
            }
        )
    return statuses, gaps, proof_summaries, additional_sources


def _spdx_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"SPDXRef-{kind}-{digest}"


def generate_payloads(
    inventory: dict[str, Any],
    source_commit: str,
    created_utc: str,
    catalog: dict[str, Any],
    components: dict[str, dict[str, Any]],
    groups: list[dict[str, Any]],
    locked: dict[str, dict[str, str]],
    lock_sha256: str,
    catalog_sha256: str,
    closure_contract: dict[str, Any],
    closure_contract_sha256: str,
    closure_evidence_root: Path,
) -> dict[str, dict[str, Any]]:
    if not COMMIT_RE.fullmatch(source_commit):
        raise EvidenceError("source commit must be exactly 40 lowercase hexadecimal characters")
    try:
        timestamp = dt.datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("created UTC time must be ISO-8601") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != dt.timedelta(0):
        raise EvidenceError("created UTC time must include UTC offset")

    inventory_bytes = (json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    inventory_sha256 = hashlib.sha256(inventory_bytes).hexdigest()
    closure_records = validate_closure_contract(
        closure_contract, components, groups
    )
    if not SHA256_RE.fullmatch(closure_contract_sha256):
        raise EvidenceError("Linux native-closure contract SHA-256 is invalid")
    if closure_contract_sha256 != sha256_json_payload(closure_contract):
        raise EvidenceError(
            "Linux native-closure contract hash does not bind the supplied contract"
        )
    native_files: list[dict[str, Any]] = []
    native_files_by_owner: dict[str, list[dict[str, Any]]] = {}
    issues: list[str] = []
    for row in inventory["regular_files"]:
        if row["elf"] is None:
            continue
        owner, declared_status = _native_owner(row["path"], components, groups)
        if owner is None:
            issues.append(f"unmapped-or-ambiguous-native-owner:{row['path']}")
            continue
        native_row = {
            "path": row["path"],
            "size": row["size"],
            "sha256": row["sha256"],
            "mode": row["mode"],
            "owner": owner,
            "declared_closure_status": declared_status,
        }
        native_files.append(native_row)
        native_files_by_owner.setdefault(owner, []).append(native_row)
    if len(native_files) != inventory["counts"]["elf_files"]:
        raise EvidenceError(
            "Every native file must have one unambiguous owner before closure evaluation"
        )
    (
        effective_statuses,
        closure_gap_rows,
        proof_summaries,
        closure_sources,
    ) = evaluate_closure_contract(
        closure_records,
        native_files_by_owner,
        locked,
        closure_evidence_root,
    )
    closure_gaps = set(closure_gap_rows)
    for native_row in native_files:
        native_row["closure_status"] = effective_statuses[native_row["owner"]]
    if inventory["licence_validation"]["status"] != "passed":
        issues.append("packaged-licence-validation-not-passed")

    common = {
        "source_commit": source_commit,
        "inventory_sha256": inventory_sha256,
        "lock_sha256": lock_sha256,
        "catalog_sha256": catalog_sha256,
        "closure_contract_sha256": closure_contract_sha256,
    }
    component_rows: list[dict[str, Any]] = []
    packaged_names = {row["name"] for row in inventory["packaged_distributions"]}
    for name in sorted(packaged_names):
        component = components[name]
        component_rows.append(
            {
                "id": f"python-distribution:{name}",
                "name": name,
                "version": component["version"],
                "license_declared": component["license_declared"],
                "declared_native_closure_status": component["native_closure_status"],
                "native_closure_status": effective_statuses.get(
                    f"python-distribution:{name}", component["native_closure_status"]
                ),
                "locked_wheel_sha256": locked[name]["wheel_sha256"],
                "source_url": component["source_url"],
                "source_sha256": component.get("source_sha256"),
                "source_commit": component.get("source_commit"),
            }
        )
    effective_groups = []
    for group in groups:
        owner = f"native-runtime:{group['id']}"
        effective_group = dict(group)
        effective_group["declared_closure_status"] = group["closure_status"]
        effective_group["closure_status"] = effective_statuses.get(
            owner, group["closure_status"]
        )
        effective_groups.append(effective_group)
    component_map = {
        "schema": "chromamatter.linux-binary-component-map.v1",
        "status": "complete" if not issues and not closure_gaps else "blocked",
        **common,
        "application": catalog["application"],
        "counts": inventory["counts"],
        "components": component_rows,
        "native_runtime_groups": effective_groups,
        "native_files": native_files,
        "native_closure_contract": {
            "schema": closure_contract["schema"],
            "contract_status": closure_contract["contract_status"],
            "expected_owner_count": len(EXPECTED_NATIVE_CLOSURE_OWNERS),
            "expected_owners": list(EXPECTED_NATIVE_CLOSURE_OWNERS),
            "sha256": closure_contract_sha256,
        },
        "native_closure_proofs": proof_summaries,
        "licence_validation": inventory["licence_validation"],
        "validation": {
            "mechanically_consistent": not issues,
            "issues": sorted(set(issues)),
            "native_closure_gaps": sorted(closure_gaps),
        },
    }

    sources = [
        _source_record(
            "application:chromamatter",
            "ChromaMatter",
            "0.9",
            "GPL-3.0-or-later",
            catalog["application"]["source_url"],
            source_commit=source_commit,
        )
    ]
    for name in sorted(packaged_names):
        component = components[name]
        sources.append(
            _source_record(
                f"python-distribution:{name}",
                name,
                component["version"],
                component["license_declared"],
                component["source_url"],
                source_sha256=component.get("source_sha256"),
                source_commit=component.get("source_commit"),
            )
        )
    sources.extend(closure_sources)
    if len({source["source_id"] for source in sources}) != len(sources):
        raise EvidenceError("Linux corresponding-source ids are not unique")
    source_gaps = set(closure_gaps)
    closure_source_owners = {
        owner
        for owner in EXPECTED_NATIVE_CLOSURE_OWNERS
        if any(
            source["source_id"].startswith(f"closure-source:{owner}:")
            for source in closure_sources
        )
    }
    for group in effective_groups:
        owner = f"native-runtime:{group['id']}"
        source_sha = group.get("source_sha256")
        source_commit_value = group.get("source_commit")
        if source_sha or source_commit_value:
            sources.append(
                _source_record(
                    f"native-runtime:{group['id']}",
                    group["id"],
                    "runtime-specific",
                    group["license_declared"],
                    group["source_url"],
                    source_sha256=source_sha,
                    source_commit=source_commit_value,
                )
            )
        elif not (
            effective_statuses.get(owner) == "verified-rebuild"
            and owner in closure_source_owners
        ):
            source_gaps.add(f"unfixed-native-source-identity:{owner}")
    if issues:
        source_gaps.update(issues)
    source_manifest = {
        "schema": "chromamatter.linux-corresponding-source-manifest.v1",
        "status": "complete" if not source_gaps else "candidate-only",
        **common,
        "component_sources": sources,
        "known_gaps": sorted(source_gaps),
        "stage_required": True,
        "stage_status": "not-staged",
        "build_instructions": ["BUILD_FROM_SOURCE_EN.md", "BUILD_FROM_SOURCE_JA.md"],
        "relinking_instructions": ["RELINKING_EN.md", "RELINKING_JA.md"],
    }

    application_spdx = _spdx_id("Package", "ChromaMatter")
    packages = [
        {
            "SPDXID": application_spdx,
            "name": "ChromaMatter",
            "versionInfo": "0.9",
            "downloadLocation": catalog["application"]["source_url"],
            "licenseDeclared": "GPL-3.0-or-later",
            "licenseConcluded": "NOASSERTION",
            "filesAnalyzed": False,
        }
    ]
    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": application_spdx,
        }
    ]
    for row in component_rows:
        spdx_id = _spdx_id("Package", row["id"])
        package = {
            "SPDXID": spdx_id,
            "name": row["name"],
            "versionInfo": row["version"],
            "downloadLocation": row["source_url"],
            "licenseDeclared": row["license_declared"],
            "licenseConcluded": "NOASSERTION",
            "filesAnalyzed": False,
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:pypi/{row['name']}@{row['version']}",
                }
            ],
            "comment": f"frozen Linux wheel sha256={row['locked_wheel_sha256']}",
        }
        if row["source_sha256"]:
            package["checksums"] = [
                {"algorithm": "SHA256", "checksumValue": row["source_sha256"]}
            ]
        packages.append(package)
        relationships.append(
            {
                "spdxElementId": application_spdx,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": spdx_id,
            }
        )
    for group in effective_groups:
        spdx_id = _spdx_id("Package", f"native-runtime:{group['id']}")
        packages.append(
            {
                "SPDXID": spdx_id,
                "name": group["id"],
                "versionInfo": "runtime-specific",
                "downloadLocation": group["source_url"],
                "licenseDeclared": group["license_declared"],
                "licenseConcluded": "NOASSERTION",
                "filesAnalyzed": False,
                "comment": f"closure_status={group['closure_status']}",
            }
        )
        relationships.append(
            {
                "spdxElementId": application_spdx,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": spdx_id,
            }
        )
    namespace_seed = f"{source_commit}:{inventory_sha256}"
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "ChromaMatter-0.9-Linux-x86_64-technical-alpha",
        "documentNamespace": (
            "https://chromamatter.app/spdx/linux-alpha/"
            + hashlib.sha256(namespace_seed.encode("ascii")).hexdigest()
        ),
        "creationInfo": {
            "created": timestamp.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "creators": ["Tool: ChromaMatter-generate-linux-compliance-evidence/1"],
            "licenseListVersion": "3.27",
        },
        "documentDescribes": [application_spdx],
        "packages": packages,
        "relationships": relationships,
        "annotations": [
            {
                "annotationType": "OTHER",
                "annotator": "Tool: ChromaMatter-generate-linux-compliance-evidence/1",
                "annotationDate": timestamp.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "comment": f"source_commit={source_commit}; inventory_sha256={inventory_sha256}",
            }
        ],
    }

    blockers = [
        *component_map["validation"]["issues"],
        *component_map["validation"]["native_closure_gaps"],
        *source_manifest["known_gaps"],
        "corresponding-source-stage-not-verified",
        "release-archive-and-fresh-extract-audit-not-verified",
        "explicit-owner-decision-not-recorded",
    ]
    approval = {
        "schema": "chromamatter.linux-distribution-approval.v1",
        "status": "blocked",
        **common,
        "automatic_approval_permitted": False,
        "scope": "linux-x86_64-technical-alpha",
        "blockers": sorted(set(blockers)),
        "owner_approval": {
            "decision": "not-recorded",
            "must_bind_archive_sha256": True,
            "must_bind_archive_audit_sha256": True,
            "must_bind_source_stage_sha256": True,
        },
        "failure_contract": (
            "Do not distribute the Linux application archive while this file says blocked or "
            "while any exact-byte source, licence, relinking, archive, fresh-extract, or owner gate is missing."
        ),
    }
    return {
        "LINUX_APP_INVENTORY.json": inventory,
        "LINUX_NATIVE_CLOSURE_CONTRACT.json": closure_contract,
        "BINARY_COMPONENT_MAP.json": component_map,
        "SBOM.spdx.json": sbom,
        "CORRESPONDING_SOURCE_MANIFEST.json": source_manifest,
        "DISTRIBUTION_APPROVAL.json": approval,
    }


def write_evidence(output_directory: Path, payloads: dict[str, dict[str, Any]]) -> None:
    if output_directory.exists():
        raise EvidenceError("Linux evidence output directory already exists")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}.", dir=output_directory.parent)
    )
    try:
        for name, payload in payloads.items():
            write_json(temporary / name, payload)
        for source_name, output_name in TEMPLATE_OUTPUTS.items():
            source = TEMPLATE_ROOT / source_name
            if not source.is_file() or source.is_symlink():
                raise EvidenceError(f"Canonical Linux compliance template is missing: {source}")
            write_text(temporary / output_name, source.read_text(encoding="utf-8"))
        validate_generated_evidence(temporary)
        os.replace(temporary, output_directory)
    finally:
        if temporary.exists():
            import shutil

            shutil.rmtree(temporary)


def validate_generated_evidence(output_directory: Path) -> None:
    for name in REQUIRED_OUTPUTS:
        path = output_directory / name
        if not path.is_file() or path.is_symlink():
            raise EvidenceError(f"Linux evidence output is missing or unsafe: {name}")
    for source_name, output_name in TEMPLATE_OUTPUTS.items():
        canonical = TEMPLATE_ROOT / source_name
        if not canonical.is_file() or canonical.is_symlink():
            raise EvidenceError(f"Canonical Linux compliance template is missing: {source_name}")
        if (output_directory / output_name).read_bytes() != canonical.read_bytes():
            raise EvidenceError(f"Generated Linux compliance template was modified: {output_name}")
    inventory = read_json(output_directory / "LINUX_APP_INVENTORY.json")
    closure_contract = read_json(
        output_directory / "LINUX_NATIVE_CLOSURE_CONTRACT.json"
    )
    component_map = read_json(output_directory / "BINARY_COMPONENT_MAP.json")
    sbom = read_json(output_directory / "SBOM.spdx.json")
    sources = read_json(output_directory / "CORRESPONDING_SOURCE_MANIFEST.json")
    approval = read_json(output_directory / "DISTRIBUTION_APPROVAL.json")
    schemas = (
        (inventory.get("schema"), "chromamatter.linux-app-inventory.v1"),
        (
            closure_contract.get("schema"),
            "chromamatter.linux-native-closure-contract.v1",
        ),
        (component_map.get("schema"), "chromamatter.linux-binary-component-map.v1"),
        (
            sources.get("schema"),
            "chromamatter.linux-corresponding-source-manifest.v1",
        ),
        (approval.get("schema"), "chromamatter.linux-distribution-approval.v1"),
    )
    if any(observed != expected for observed, expected in schemas):
        raise EvidenceError("Generated Linux evidence schema is invalid")
    if sbom.get("spdxVersion") != "SPDX-2.3":
        raise EvidenceError("Generated Linux SBOM is not SPDX 2.3")
    identity_keys = (
        "source_commit",
        "inventory_sha256",
        "lock_sha256",
        "catalog_sha256",
        "closure_contract_sha256",
    )
    for key in identity_keys:
        values = {payload.get(key) for payload in (component_map, sources, approval)}
        if len(values) != 1:
            raise EvidenceError(f"Generated Linux evidence identity mismatch: {key}")
    expected_inventory_sha256 = sha256_file(
        output_directory / "LINUX_APP_INVENTORY.json"
    )
    if component_map.get("inventory_sha256") != expected_inventory_sha256:
        raise EvidenceError("Generated Linux evidence does not bind exact inventory bytes")
    expected_contract_sha256 = sha256_file(
        output_directory / "LINUX_NATIVE_CLOSURE_CONTRACT.json"
    )
    if component_map.get("closure_contract_sha256") != expected_contract_sha256:
        raise EvidenceError(
            "Generated Linux evidence does not bind exact native-closure contract bytes"
        )
    contract_owners = closure_contract.get("owners")
    if (
        closure_contract.get("expected_owner_count")
        != len(EXPECTED_NATIVE_CLOSURE_OWNERS)
        or not isinstance(contract_owners, dict)
        or set(contract_owners) != set(EXPECTED_NATIVE_CLOSURE_OWNERS)
    ):
        raise EvidenceError("Generated Linux native-closure owner set is invalid")
    contract_summary = component_map.get("native_closure_contract", {})
    if (
        contract_summary.get("sha256") != expected_contract_sha256
        or contract_summary.get("expected_owners")
        != list(EXPECTED_NATIVE_CLOSURE_OWNERS)
        or contract_summary.get("contract_status")
        != closure_contract.get("contract_status")
    ):
        raise EvidenceError("Generated Linux native-closure summary is not bound")
    records = closure_contract["owners"]
    for owner, record in records.items():
        if (
            not isinstance(record, dict)
            or record.get("required_evidence") != list(REQUIRED_CLOSURE_EVIDENCE)
            or not isinstance(record.get("declared_status"), str)
            or (
                record.get("verification_status") == "blocked-unverified"
                and record.get("proof") is not None
            )
            or (
                record.get("verification_status") == "verified"
                and not isinstance(record.get("proof"), dict)
            )
            or record.get("verification_status")
            not in {"blocked-unverified", "verified"}
        ):
            raise EvidenceError(
                f"Generated Linux native-closure record is invalid: {owner}"
            )
    verified_owners = {
        owner
        for owner, record in records.items()
        if isinstance(record, dict)
        and record.get("verification_status") == "verified"
        and isinstance(record.get("proof"), dict)
    }
    aggregate_status = (
        "verified"
        if verified_owners == set(EXPECTED_NATIVE_CLOSURE_OWNERS)
        else "blocked-unverified"
    )
    if closure_contract.get("contract_status") != aggregate_status:
        raise EvidenceError("Generated Linux native-closure aggregate status is invalid")
    proof_rows = component_map.get("native_closure_proofs")
    if not isinstance(proof_rows, list) or len(proof_rows) != len(
        EXPECTED_NATIVE_CLOSURE_OWNERS
    ):
        raise EvidenceError("Generated Linux native-closure proof summaries are missing")
    proof_by_owner = {
        row.get("owner"): row for row in proof_rows if isinstance(row, dict)
    }
    if set(proof_by_owner) != set(EXPECTED_NATIVE_CLOSURE_OWNERS):
        raise EvidenceError("Generated Linux native-closure proof coverage is invalid")
    for owner in EXPECTED_NATIVE_CLOSURE_OWNERS:
        verified = owner in verified_owners
        summary = proof_by_owner[owner]
        if (
            summary.get("verification_status")
            != ("verified" if verified else "blocked-unverified")
            or summary.get("proof_bound") is not verified
            or summary.get("effective_closure_status")
            != ("verified-rebuild" if verified else records[owner].get("declared_status"))
        ):
            raise EvidenceError(
                f"Generated Linux native-closure proof summary is inconsistent: {owner}"
            )
    if component_map.get("status") == "complete" and aggregate_status != "verified":
        raise EvidenceError(
            "Linux component map cannot be complete while native closures are unverified"
        )
    if approval.get("status") != "blocked" or approval.get("automatic_approval_permitted") is not False:
        raise EvidenceError("Evidence generator must never grant Linux distribution approval")
    if inventory.get("licence_validation", {}).get("status") != "passed":
        raise EvidenceError("Generated Linux evidence has no successful licence validation")


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-directory", required=True, type=Path)
    parser.add_argument("--audit-report", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--created-utc", required=True)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--closure-contract", type=Path, default=DEFAULT_CLOSURE_CONTRACT
    )
    parser.add_argument(
        "--closure-evidence-root",
        type=Path,
        help="Root for hash-bound native-closure proof files (defaults to the contract directory)",
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--require-complete", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    try:
        if arguments.output_directory.exists():
            raise EvidenceError("Linux evidence output directory already exists")
        locked = parse_lock(arguments.lock.resolve(strict=True))
        catalog_path = arguments.catalog.resolve(strict=True)
        closure_contract_path = arguments.closure_contract.resolve(strict=True)
        lock_path = arguments.lock.resolve(strict=True)
        catalog = read_json(catalog_path)
        closure_contract = read_json(closure_contract_path)
        components, groups = validate_catalog(catalog, locked)
        validate_closure_contract(closure_contract, components, groups)
        closure_evidence_root = (
            arguments.closure_evidence_root.resolve(strict=True)
            if arguments.closure_evidence_root is not None
            else closure_contract_path.parent
        )
        inventory = collect_inventory(
            arguments.app_directory, arguments.audit_report, catalog, components, locked
        )
        payloads = generate_payloads(
            inventory,
            arguments.source_commit,
            arguments.created_utc,
            catalog,
            components,
            groups,
            locked,
            sha256_file(lock_path),
            sha256_file(catalog_path),
            closure_contract,
            sha256_json_payload(closure_contract),
            closure_evidence_root,
        )
        write_evidence(arguments.output_directory, payloads)
        if arguments.require_complete and (
            payloads["BINARY_COMPONENT_MAP.json"]["status"] != "complete"
            or payloads["CORRESPONDING_SOURCE_MANIFEST.json"]["status"] != "complete"
        ):
            raise EvidenceError("Linux compliance evidence is candidate-only")
    except (EvidenceError, OSError) as exc:
        print(f"Linux compliance evidence refused: {exc}", file=os.sys.stderr)
        return 3
    print(f"Linux compliance evidence written: {arguments.output_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
