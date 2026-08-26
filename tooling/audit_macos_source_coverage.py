#!/usr/bin/env python3
"""Fail-closed macOS native/source coverage audit.

This tool consumes the deterministic ``MACOS_ALPHA_APP_INVENTORY.json`` made
on Apple Silicon.  It classifies every observed Mach-O path, verifies that the
macOS wheel lock and source catalog describe the same dependency set, and
keeps known source, build-provenance, and relinking gaps visible.

An optional exact-wheel inspection reads Mach-O ``LC_ID_DYLIB`` load commands
and binary string probes directly from hash-locked wheel files.  The resulting
report is engineering evidence, not a legal conclusion.
``--require-engineering-gate-passed`` fails unless the mechanically checked
coverage evidence is complete; a status string in a plan can never pass the
gate.
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tempfile
from typing import Any, Iterable, Sequence
import unicodedata
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = Path(__file__).with_name("macos_source_coverage_plan.json")
DEFAULT_CATALOG = Path(__file__).with_name("macos_compliance_components.json")
DEFAULT_LOCK = REPO_ROOT / "source" / "fixed_app" / "requirements-build-macos-arm64.lock"
REPORT_SCHEMA = "chromamatter.macos-source-coverage-report.v1"
PLAN_SCHEMA = "chromamatter.macos-source-coverage-plan.v1"
CATALOG_SCHEMA = "chromamatter.macos-compliance-component-catalog.v1"
INVENTORY_SCHEMA = "chromamatter.macos-app-inventory"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
LOCK_REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
LOCK_HASH_RE = re.compile(r"sha256:([0-9a-f]{64})")
LC_ID_DYLIB = 0x0D


class CoverageError(RuntimeError):
    """Raised when inputs are malformed or contradict one another."""


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoverageError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CoverageError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _resolved_portable_parts(path: Path) -> tuple[str, ...]:
    """Return a conservative Windows/macOS collision key for a filesystem path."""

    resolved = path.expanduser().resolve(strict=False)
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in resolved.parts)


def paths_overlap(first: Path, second: Path) -> bool:
    """Treat equal paths and either ancestor relationship as overlapping.

    Case-folding and Unicode normalization are deliberately applied on every
    platform.  That is conservative on a case-sensitive filesystem and avoids
    publishing a recipe which becomes unsafe on default Windows/macOS volumes.
    """

    first_parts = _resolved_portable_parts(first)
    second_parts = _resolved_portable_parts(second)
    common = min(len(first_parts), len(second_parts))
    return first_parts[:common] == second_parts[:common]


def reject_output_overlap(
    output: Path,
    *,
    output_label: str,
    inputs: Sequence[tuple[str, Path]],
) -> None:
    """Reject an output which could replace, contain, or be contained by input."""

    for input_label, input_path in inputs:
        if paths_overlap(output, input_path):
            raise CoverageError(
                f"Unsafe {output_label}: it overlaps {input_label} ({input_path})"
            )


def _safe_posix_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CoverageError(f"{label} must be a non-empty POSIX path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise CoverageError(f"Unsafe {label}: {value!r}")
    return pure.as_posix()


def parse_lock(path: Path) -> dict[str, dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    locked: dict[str, dict[str, str]] = {}
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        match = LOCK_REQUIREMENT_RE.match(stripped)
        if not match:
            index += 1
            continue
        name = canonical_name(match.group(1))
        version = match.group(2)
        hash_match = LOCK_HASH_RE.search(stripped)
        scan = index + 1
        while hash_match is None and scan < len(lines):
            continuation = lines[scan].strip()
            if continuation and not continuation.startswith("--hash="):
                break
            hash_match = LOCK_HASH_RE.search(continuation)
            scan += 1
        if hash_match is None:
            raise CoverageError(f"Locked requirement has no SHA-256: {name}=={version}")
        if name in locked:
            raise CoverageError(f"Duplicate locked requirement: {name}")
        locked[name] = {"version": version, "wheel_sha256": hash_match.group(1)}
        index = scan
    if not locked:
        raise CoverageError(f"No locked requirements in {path}")
    return locked


def _validated_source_identity(component: dict[str, Any]) -> tuple[bool, str]:
    url = component.get("source_url")
    digest = component.get("source_sha256")
    commit = component.get("source_commit")
    if not isinstance(url, str) or not url.startswith("https://"):
        return False, "source URL is not fixed HTTPS"
    if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
        return True, "archive-sha256"
    if isinstance(commit, str) and COMMIT_RE.fullmatch(commit):
        return True, "git-commit"
    return False, "source has neither an archive SHA-256 nor an exact git commit"


def validate_catalog(
    catalog: dict[str, Any], locked: dict[str, dict[str, str]]
) -> dict[str, dict[str, Any]]:
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise CoverageError("Unsupported macOS component catalog schema")
    raw = catalog.get("distributions")
    if not isinstance(raw, dict):
        raise CoverageError("Catalog distributions must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_name, component in raw.items():
        name = canonical_name(str(raw_name))
        if name in normalized or not isinstance(component, dict):
            raise CoverageError(f"Invalid or duplicate catalog distribution: {raw_name}")
        normalized[name] = component
    if set(normalized) != set(locked):
        missing = sorted(set(locked) - set(normalized))
        extra = sorted(set(normalized) - set(locked))
        raise CoverageError(f"Catalog/lock package mismatch; missing={missing}, extra={extra}")
    for name, lock_fact in locked.items():
        component = normalized[name]
        if component.get("version") != lock_fact["version"]:
            raise CoverageError(
                f"Catalog version mismatch for {name}: "
                f"{component.get('version')!r} != {lock_fact['version']!r}"
            )
        license_value = component.get("license_declared")
        if not isinstance(license_value, str) or not license_value.strip():
            raise CoverageError(f"Catalog has no declared license for {name}")
    return normalized


def _validate_plan(
    plan: dict[str, Any], locked: dict[str, dict[str, str]], source_commit: str
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise CoverageError("Unsupported macOS source coverage plan schema")

    raw_wheels = plan.get("wheel_artifacts")
    if not isinstance(raw_wheels, list):
        raise CoverageError("wheel_artifacts must be an array")
    wheels: dict[str, dict[str, Any]] = {}
    for item in raw_wheels:
        if not isinstance(item, dict):
            raise CoverageError("wheel_artifacts entries must be objects")
        name = canonical_name(str(item.get("distribution", "")))
        if not name or name in wheels:
            raise CoverageError(f"Invalid or duplicate wheel artifact: {name!r}")
        filename = item.get("filename")
        url = item.get("url")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith(".whl")
        ):
            raise CoverageError(f"Unsafe wheel filename for {name}")
        if not isinstance(url, str) or not url.startswith("https://files.pythonhosted.org/"):
            raise CoverageError(f"Wheel URL is not an immutable PyPI file URL for {name}")
        if url.rsplit("/", 1)[-1] != filename:
            raise CoverageError(f"Wheel URL/filename mismatch for {name}")
        wheels[name] = item
    if set(wheels) != set(locked):
        raise CoverageError(
            "Wheel plan/lock package mismatch; "
            f"missing={sorted(set(locked) - set(wheels))}, "
            f"extra={sorted(set(wheels) - set(locked))}"
        )
    for name, lock_fact in locked.items():
        item = wheels[name]
        if item.get("version") != lock_fact["version"]:
            raise CoverageError(f"Wheel version mismatch for {name}")
        if item.get("sha256") != lock_fact["wheel_sha256"]:
            raise CoverageError(f"Wheel SHA-256 mismatch for {name}")

    raw_gaps = plan.get("known_gaps")
    if not isinstance(raw_gaps, list):
        raise CoverageError("known_gaps must be an array")
    gaps: dict[str, dict[str, Any]] = {}
    for item in raw_gaps:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise CoverageError("Each known gap must have an id")
        gap_id = item["id"]
        if gap_id in gaps:
            raise CoverageError(f"Duplicate known gap: {gap_id}")
        if item.get("blocks_release") is not True:
            raise CoverageError(f"Current plan gap must fail closed: {gap_id}")
        gaps[gap_id] = item

    raw_materials = plan.get("fixed_native_source_materials")
    if not isinstance(raw_materials, list) or not raw_materials:
        raise CoverageError("fixed_native_source_materials must be a non-empty array")
    materials: dict[str, dict[str, Any]] = {}
    for item in raw_materials:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise CoverageError("Each fixed native source material must have an id")
        material_id = item["id"]
        if material_id in materials:
            raise CoverageError(f"Duplicate fixed native source material: {material_id}")
        if not isinstance(item.get("license_declared"), str) or not item["license_declared"]:
            raise CoverageError(f"Native source material has no license: {material_id}")
        url = item.get("source_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise CoverageError(f"Native source material has no fixed HTTPS URL: {material_id}")
        identity_kind = item.get("identity_kind")
        if identity_kind == "archive-sha256":
            if not isinstance(item.get("source_sha256"), str) or not SHA256_RE.fullmatch(
                item["source_sha256"]
            ):
                raise CoverageError(f"Native source archive has no SHA-256: {material_id}")
        elif identity_kind == "git-commit":
            if not isinstance(item.get("source_commit"), str) or not COMMIT_RE.fullmatch(
                item["source_commit"]
            ):
                raise CoverageError(f"Native git source has no exact commit: {material_id}")
        elif identity_kind == "audit-source-commit":
            item = {**item, "source_commit": source_commit}
        else:
            raise CoverageError(f"Unknown native source identity kind: {material_id}")
        materials[material_id] = item

    runtime = plan.get("python_runtime_binary_provenance")
    if not isinstance(runtime, dict):
        raise CoverageError("python_runtime_binary_provenance must be an object")
    if (
        not isinstance(runtime.get("filename"), str)
        or Path(runtime["filename"]).name != runtime["filename"]
        or not isinstance(runtime.get("url"), str)
        or not runtime["url"].startswith("https://github.com/actions/python-versions/releases/")
        or not isinstance(runtime.get("sha256"), str)
        or not SHA256_RE.fullmatch(runtime["sha256"])
        or not isinstance(runtime.get("builder_source_commit"), str)
        or not COMMIT_RE.fullmatch(runtime["builder_source_commit"])
    ):
        raise CoverageError("Python runtime binary provenance is not exact")

    workflow_evidence = plan.get("upstream_workflow_evidence")
    if not isinstance(workflow_evidence, list) or not workflow_evidence:
        raise CoverageError("upstream_workflow_evidence must be a non-empty array")
    workflow_ids: set[str] = set()
    for item in workflow_evidence:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise CoverageError("Each upstream workflow evidence record must have an id")
        evidence_id = item["id"]
        url = item.get("source_url")
        facts = item.get("observed_facts")
        if evidence_id in workflow_ids:
            raise CoverageError(f"Duplicate upstream workflow evidence: {evidence_id}")
        workflow_ids.add(evidence_id)
        if (
            not isinstance(url, str)
            or not url.startswith("https://raw.githubusercontent.com/")
            or re.search(r"/[0-9a-f]{40}/", url) is None
        ):
            raise CoverageError(f"Workflow evidence URL is not commit-fixed: {evidence_id}")
        if not isinstance(facts, list) or not facts or any(
            not isinstance(fact, str) or not fact for fact in facts
        ):
            raise CoverageError(f"Workflow evidence has no observed facts: {evidence_id}")

    raw_groups = plan.get("native_groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise CoverageError("native_groups must be a non-empty array")
    groups: list[dict[str, Any]] = []
    group_ids: set[str] = set()
    for item in raw_groups:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise CoverageError("Each native group must have an id")
        group_id = item["id"]
        if group_id in group_ids:
            raise CoverageError(f"Duplicate native group: {group_id}")
        group_ids.add(group_id)
        prefixes = item.get("path_prefixes")
        if not isinstance(prefixes, list) or not prefixes:
            raise CoverageError(f"Native group {group_id} has no path prefixes")
        item = copy.deepcopy(item)
        item["path_prefixes"] = [
            _safe_posix_path(prefix, f"{group_id} path prefix") for prefix in prefixes
        ]
        package_names = item.get("distributions", [])
        if not isinstance(package_names, list):
            raise CoverageError(f"Native group {group_id} distributions must be an array")
        item["distributions"] = [canonical_name(str(name)) for name in package_names]
        unknown_packages = sorted(set(item["distributions"]) - set(locked))
        if unknown_packages:
            raise CoverageError(f"Native group {group_id} has unknown packages: {unknown_packages}")
        gap_ids = item.get("gap_ids", [])
        if not isinstance(gap_ids, list) or any(not isinstance(value, str) for value in gap_ids):
            raise CoverageError(f"Native group {group_id} gap_ids must be strings")
        unknown_gaps = sorted(set(gap_ids) - set(gaps))
        if unknown_gaps:
            raise CoverageError(f"Native group {group_id} has unknown gaps: {unknown_gaps}")
        if item.get("relink_status") not in ("not-required", "complete", "unresolved"):
            raise CoverageError(f"Native group {group_id} has invalid relink_status")
        source_material_ids = item.get("source_material_ids", [])
        if not isinstance(source_material_ids, list) or any(
            not isinstance(value, str) for value in source_material_ids
        ):
            raise CoverageError(f"Native group {group_id} source_material_ids must be strings")
        unknown_materials = sorted(set(source_material_ids) - set(materials))
        if unknown_materials:
            raise CoverageError(
                f"Native group {group_id} has unknown source materials: {unknown_materials}"
            )
        groups.append(item)
    return wheels, gaps, groups, materials


def _matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _packaged_distributions(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = inventory.get("packaged_distributions")
    if not isinstance(raw, list):
        raise CoverageError("Inventory packaged_distributions must be an array")
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("canonical_name"), str):
            raise CoverageError("Invalid inventory distribution record")
        name = canonical_name(item["canonical_name"])
        if name in result:
            raise CoverageError(f"Duplicate inventory distribution: {name}")
        result[name] = item
    return result


def _macho_files(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    raw = inventory.get("regular_files")
    if not isinstance(raw, list):
        raise CoverageError("Inventory regular_files must be an array")
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or "mach_o" not in item:
            continue
        path = _safe_posix_path(item.get("path"), "inventory Mach-O path")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise CoverageError(f"Inventory Mach-O has invalid SHA-256: {path}")
        macho = item.get("mach_o")
        if not isinstance(macho, dict):
            raise CoverageError(f"Inventory Mach-O record is invalid: {path}")
        result.append({**item, "path": path})
    if not result:
        raise CoverageError("Inventory contains no Mach-O regular files")
    result.sort(key=lambda item: item["path"])
    return result


def _format_macho_version(value: int) -> str:
    return f"{value >> 16}.{(value >> 8) & 0xff}.{value & 0xff}"


def macho_load_identity(data: bytes) -> dict[str, Any] | None:
    """Return a thin Mach-O LC_ID_DYLIB fact, or None for non-Mach-O bytes."""

    if len(data) < 4:
        return None
    magic_bytes = data[:4]
    layouts = {
        b"\xcf\xfa\xed\xfe": ("<", True),
        b"\xfe\xed\xfa\xcf": (">", True),
        b"\xce\xfa\xed\xfe": ("<", False),
        b"\xfe\xed\xfa\xce": (">", False),
    }
    layout = layouts.get(magic_bytes)
    if layout is None:
        return None
    endian, is_64 = layout
    header_size = 32 if is_64 else 28
    if len(data) < header_size:
        raise CoverageError("Truncated Mach-O header")
    ncmds = struct.unpack_from(endian + "I", data, 16)[0]
    sizeofcmds = struct.unpack_from(endian + "I", data, 20)[0]
    if header_size + sizeofcmds > len(data):
        raise CoverageError("Truncated Mach-O load-command area")
    offset = header_size
    identities: list[dict[str, Any]] = []
    for _ in range(ncmds):
        if offset + 8 > len(data):
            raise CoverageError("Truncated Mach-O load command")
        command, command_size = struct.unpack_from(endian + "II", data, offset)
        if command_size < 8 or offset + command_size > len(data):
            raise CoverageError("Invalid Mach-O load command size")
        if command == LC_ID_DYLIB:
            if command_size < 24:
                raise CoverageError("Invalid LC_ID_DYLIB command size")
            name_offset, timestamp, current, compatibility = struct.unpack_from(
                endian + "IIII", data, offset + 8
            )
            if name_offset < 24 or name_offset >= command_size:
                raise CoverageError("Invalid LC_ID_DYLIB name offset")
            start = offset + name_offset
            end = data.find(b"\0", start, offset + command_size)
            if end < 0:
                raise CoverageError("Unterminated LC_ID_DYLIB name")
            try:
                name = data[start:end].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CoverageError("Invalid UTF-8 LC_ID_DYLIB name") from exc
            identities.append(
                {
                    "compatibility_version": _format_macho_version(compatibility),
                    "current_version": _format_macho_version(current),
                    "name": name,
                    "timestamp": timestamp,
                }
            )
        offset += command_size
    if len(identities) > 1:
        raise CoverageError("Mach-O contains multiple LC_ID_DYLIB commands")
    return {
        "format": "mach-o-64" if is_64 else "mach-o-32",
        "lc_id_dylib": identities[0] if identities else None,
    }


def _zip_regular_members(archive: zipfile.ZipFile) -> Iterable[zipfile.ZipInfo]:
    for info in archive.infolist():
        path = _safe_posix_path(info.filename.rstrip("/"), "wheel member")
        if info.is_dir():
            continue
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        if unix_mode and (unix_mode & 0o170000) == 0o120000:
            continue
        if info.file_size > 512 * 1024 * 1024:
            raise CoverageError(f"Unreasonably large wheel member: {path}")
        yield info


def inspect_wheel(path: Path, expected: dict[str, Any], probes: list[dict[str, Any]]) -> dict[str, Any]:
    if path.name != expected["filename"]:
        raise CoverageError(f"Wrong wheel filename for {expected['distribution']}: {path.name}")
    digest = sha256_file(path)
    if digest != expected["sha256"]:
        raise CoverageError(f"Wheel SHA-256 mismatch: {path.name}")
    license_members: list[str] = []
    macho_members: list[dict[str, Any]] = []
    probe_results: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        for info in _zip_regular_members(archive):
            member = info.filename
            lowered = member.casefold()
            if ".dist-info/" in lowered and any(
                token in lowered.rsplit("/", 1)[-1]
                for token in ("license", "copying", "notice")
            ):
                license_members.append(member)
            applicable = [probe for probe in probes if fnmatch.fnmatchcase(member, probe["member_glob"])]
            needs_bytes = bool(applicable) or member.endswith((".dylib", ".so")) or ".framework/" in member
            if not needs_bytes:
                continue
            data = archive.read(info)
            identity = macho_load_identity(data)
            if identity is not None:
                macho_members.append({"member": member, **identity})
            for probe in applicable:
                needle = probe["ascii"].encode("ascii")
                matched = needle in data
                probe_results.append(
                    {
                        "ascii": probe["ascii"],
                        "fact": probe["fact"],
                        "matched": matched,
                        "member": member,
                        "member_glob": probe["member_glob"],
                    }
                )
    license_members.sort()
    macho_members.sort(key=lambda item: item["member"])
    probe_results.sort(key=lambda item: (item["fact"], item["member"]))
    missing_probe_facts = sorted(
        {
            probe["fact"]
            for probe in probes
            if not any(result["fact"] == probe["fact"] and result["matched"] for result in probe_results)
        }
    )
    return {
        "distribution": canonical_name(expected["distribution"]),
        "filename": path.name,
        "license_members": license_members,
        "mach_o_members": macho_members,
        "missing_probe_facts": missing_probe_facts,
        "probe_results": probe_results,
        "sha256": digest,
        "size": path.stat().st_size,
    }


def audit(
    *,
    inventory: dict[str, Any],
    inventory_sha256: str,
    locked: dict[str, dict[str, str]],
    lock_sha256: str,
    catalog: dict[str, Any],
    catalog_sha256: str,
    plan: dict[str, Any],
    plan_sha256: str,
    source_commit: str,
    wheel_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    if inventory.get("schema") != INVENTORY_SCHEMA or inventory.get("schema_version") != 1:
        raise CoverageError("Unsupported macOS app inventory schema")
    if not COMMIT_RE.fullmatch(source_commit):
        raise CoverageError("source_commit must be an exact lowercase 40-hex commit")
    catalog_distributions = validate_catalog(catalog, locked)
    wheel_plan, gaps, groups, native_materials = _validate_plan(plan, locked, source_commit)

    intentionally_absent_raw = plan.get("intentionally_not_packaged", [])
    if not isinstance(intentionally_absent_raw, list):
        raise CoverageError("intentionally_not_packaged must be an array")
    intentionally_absent: dict[str, str] = {}
    for item in intentionally_absent_raw:
        if not isinstance(item, dict):
            raise CoverageError("intentionally_not_packaged entries must be objects")
        name = canonical_name(str(item.get("distribution", "")))
        reason = item.get("reason")
        if name in intentionally_absent or name not in locked or not isinstance(reason, str) or not reason:
            raise CoverageError(f"Invalid intentionally absent distribution: {name!r}")
        intentionally_absent[name] = reason

    packaged = _packaged_distributions(inventory)
    expected_packaged = set(locked) - set(intentionally_absent)
    package_missing = sorted(expected_packaged - set(packaged))
    package_unexpected = sorted(set(packaged) - expected_packaged)
    package_version_mismatches: list[dict[str, str]] = []
    for name in sorted(expected_packaged & set(packaged)):
        observed = packaged[name].get("version")
        expected = locked[name]["version"]
        if observed != expected:
            package_version_mismatches.append(
                {"distribution": name, "expected": expected, "observed": str(observed)}
            )

    source_records: list[dict[str, Any]] = []
    unfixed_source_packages: list[str] = []
    for name in sorted(locked):
        component = catalog_distributions[name]
        fixed, identity_kind = _validated_source_identity(component)
        if not fixed:
            unfixed_source_packages.append(name)
        source_records.append(
            {
                "distribution": name,
                "fixed_identity": fixed,
                "identity_kind": identity_kind,
                "license_declared": component["license_declared"],
                "source_commit": component.get("source_commit"),
                "source_sha256": component.get("source_sha256"),
                "source_url": component.get("source_url"),
                "version": locked[name]["version"],
                "wheel_filename": wheel_plan[name]["filename"],
                "wheel_sha256": locked[name]["wheel_sha256"],
            }
        )

    entries: list[dict[str, Any]] = []
    unmatched_paths: list[str] = []
    ambiguous_paths: list[dict[str, Any]] = []
    unresolved_paths: list[str] = []
    group_counts = {group["id"]: {"mapped": 0, "unresolved": 0} for group in groups}
    for item in _macho_files(inventory):
        path = item["path"]
        matching = [
            group
            for group in groups
            if any(_matches_prefix(path, prefix) for prefix in group["path_prefixes"])
        ]
        if not matching:
            unmatched_paths.append(path)
            entries.append(
                {
                    "dependencies": item["mach_o"].get("dependencies", []),
                    "group_id": None,
                    "open_gap_ids": ["unmapped-native-path"],
                    "path": path,
                    "sha256": item["sha256"],
                    "source_coverage": "unresolved",
                }
            )
            continue
        if len(matching) > 1:
            group_ids = sorted(group["id"] for group in matching)
            ambiguous_paths.append({"group_ids": group_ids, "path": path})
            entries.append(
                {
                    "dependencies": item["mach_o"].get("dependencies", []),
                    "group_id": None,
                    "matching_group_ids": group_ids,
                    "open_gap_ids": ["ambiguous-native-path"],
                    "path": path,
                    "sha256": item["sha256"],
                    "source_coverage": "unresolved",
                }
            )
            continue
        group = matching[0]
        open_gaps = sorted(set(group.get("gap_ids", [])))
        if group["relink_status"] == "unresolved":
            open_gaps.append("relink-materials-unresolved")
        unfixed_group_sources = sorted(
            name
            for name in group["distributions"]
            if name in unfixed_source_packages
        )
        if unfixed_group_sources:
            open_gaps.append("distribution-source-identity-unfixed")
        open_gaps = sorted(set(open_gaps))
        state = "fixed-source-identity" if not open_gaps else "unresolved"
        group_counts[group["id"]]["mapped"] += 1
        if open_gaps:
            group_counts[group["id"]]["unresolved"] += 1
            unresolved_paths.append(path)
        entries.append(
            {
                "dependencies": item["mach_o"].get("dependencies", []),
                "distributions": group["distributions"],
                "group_id": group["id"],
                "open_gap_ids": open_gaps,
                "path": path,
                "relink_status": group["relink_status"],
                "sha256": item["sha256"],
                "source_material_ids": group.get("source_material_ids", []),
                "source_coverage": state,
            }
        )

    probes_by_distribution: dict[str, list[dict[str, Any]]] = {}
    for probe in plan.get("wheel_string_probes", []):
        if not isinstance(probe, dict):
            raise CoverageError("wheel_string_probes entries must be objects")
        name = canonical_name(str(probe.get("distribution", "")))
        if name not in wheel_plan:
            raise CoverageError(f"String probe references unknown wheel: {name}")
        if not all(isinstance(probe.get(key), str) and probe[key] for key in ("fact", "member_glob", "ascii")):
            raise CoverageError(f"Invalid string probe for {name}")
        try:
            probe["ascii"].encode("ascii")
        except UnicodeEncodeError as exc:
            raise CoverageError(f"String probe is not ASCII for {name}") from exc
        probes_by_distribution.setdefault(name, []).append(probe)

    supplied_wheels: dict[str, Path] = {}
    expected_by_filename = {item["filename"]: name for name, item in wheel_plan.items()}
    for raw_path in wheel_paths:
        path = Path(raw_path)
        name = expected_by_filename.get(path.name)
        if name is None:
            raise CoverageError(f"Wheel is not part of the macOS lock: {path.name}")
        if name in supplied_wheels:
            raise CoverageError(f"Duplicate wheel supplied for inspection: {name}")
        supplied_wheels[name] = path

    wheel_inspections = [
        inspect_wheel(path, wheel_plan[name], probes_by_distribution.get(name, []))
        for name, path in sorted(supplied_wheels.items())
    ]
    inspection_by_name = {item["distribution"]: item for item in wheel_inspections}
    required_inspections = sorted(
        canonical_name(str(name)) for name in plan.get("required_wheel_inspections", [])
    )
    if any(name not in wheel_plan for name in required_inspections):
        raise CoverageError("required_wheel_inspections references an unknown wheel")
    missing_required_inspections = sorted(set(required_inspections) - set(inspection_by_name))
    failed_probe_wheels = sorted(
        item["distribution"] for item in wheel_inspections if item["missing_probe_facts"]
    )

    blockers: list[str] = []
    if package_missing:
        blockers.append("packaged-distributions-missing")
    if package_unexpected:
        blockers.append("packaged-distributions-unexpected")
    if package_version_mismatches:
        blockers.append("packaged-distribution-version-mismatch")
    if unfixed_source_packages:
        blockers.append("distribution-source-identities-unfixed")
    if unmatched_paths:
        blockers.append("unmapped-native-paths")
    if ambiguous_paths:
        blockers.append("ambiguous-native-paths")
    if unresolved_paths:
        blockers.append("native-source-or-relink-gaps")
    if gaps:
        blockers.append("known-source-closure-gaps")
    if missing_required_inspections:
        blockers.append("required-wheel-inspections-missing")
    if failed_probe_wheels:
        blockers.append("required-wheel-string-probes-failed")
    blockers = sorted(set(blockers))
    engineering_gate_passed = not blockers

    return {
        "engineering_gate": {
            "blockers": blockers,
            "engineering_gate_passed": engineering_gate_passed,
            "legal_conclusion": False,
            "plan_declared_status_ignored": plan.get("declared_status"),
            "status": "coverage-complete" if engineering_gate_passed else "candidate-only",
        },
        "inputs": {
            "catalog_sha256": catalog_sha256,
            "inventory_sha256": inventory_sha256,
            "lock_sha256": lock_sha256,
            "plan_sha256": plan_sha256,
            "source_commit": source_commit,
        },
        "known_gaps": [gaps[key] for key in sorted(gaps)],
        "mach_o_coverage": {
            "ambiguous_paths": ambiguous_paths,
            "entries": entries,
            "group_counts": group_counts,
            "mapped_count": len(entries) - len(unmatched_paths) - len(ambiguous_paths),
            "total_count": len(entries),
            "unmatched_paths": unmatched_paths,
            "unresolved_count": len(unresolved_paths) + len(unmatched_paths) + len(ambiguous_paths),
            "unresolved_paths": unresolved_paths,
        },
        "package_coverage": {
            "expected_packaged": sorted(expected_packaged),
            "intentionally_not_packaged": intentionally_absent,
            "missing": package_missing,
            "observed_packaged": sorted(packaged),
            "unexpected": package_unexpected,
            "version_mismatches": package_version_mismatches,
        },
        "purpose": (
            "engineering evidence only; every Mach-O path must be mapped and every "
            "source/build/relink gap must be resolved before tester distribution"
        ),
        "schema": REPORT_SCHEMA,
        "fixed_native_source_materials": [
            native_materials[key] for key in sorted(native_materials)
        ],
        "python_runtime_binary_provenance": plan["python_runtime_binary_provenance"],
        "source_records": source_records,
        "upstream_workflow_evidence": plan["upstream_workflow_evidence"],
        "wheel_inspection": {
            "failed_probe_wheels": failed_probe_wheels,
            "inspections": wheel_inspections,
            "missing_required": missing_required_inspections,
            "required": required_inspections,
        },
    }


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--wheel", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-engineering-gate-passed", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    try:
        input_paths = [
            ("inventory input", arguments.inventory),
            ("lock input", arguments.lock),
            ("catalog input", arguments.catalog),
            ("plan input", arguments.plan),
            *((f"wheel input {index}", path) for index, path in enumerate(arguments.wheel, 1)),
        ]
        if arguments.output is not None:
            reject_output_overlap(
                arguments.output,
                output_label="coverage report output",
                inputs=input_paths,
            )
        inventory = read_json(arguments.inventory)
        plan = read_json(arguments.plan)
        catalog = read_json(arguments.catalog)
        locked = parse_lock(arguments.lock)
        report = audit(
            inventory=inventory,
            inventory_sha256=sha256_file(arguments.inventory),
            locked=locked,
            lock_sha256=sha256_file(arguments.lock),
            catalog=catalog,
            catalog_sha256=sha256_file(arguments.catalog),
            plan=plan,
            plan_sha256=sha256_file(arguments.plan),
            source_commit=arguments.source_commit,
            wheel_paths=arguments.wheel,
        )
        if arguments.output is not None:
            write_json(arguments.output, report)
        gate = report["engineering_gate"]
        if arguments.require_engineering_gate_passed and not gate["engineering_gate_passed"]:
            blockers = ", ".join(gate["blockers"])
            print(f"macOS source coverage engineering gate did not pass: {blockers}", file=sys.stderr)
            return 3
    except (CoverageError, OSError, zipfile.BadZipFile) as exc:
        print(f"macOS source coverage audit failed: {exc}", file=sys.stderr)
        return 2
    coverage = report["mach_o_coverage"]
    print(
        "macOS source coverage: "
        f"{report['engineering_gate']['status']}; "
        f"Mach-O {coverage['mapped_count']}/{coverage['total_count']} mapped, "
        f"{coverage['unresolved_count']} unresolved"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
