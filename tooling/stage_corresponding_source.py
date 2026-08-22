#!/usr/bin/env python3
"""Stage a fail-closed corresponding-source bundle for ChromaMatter.

The release component list is deliberately data driven.  Git sources are
exported from exact full commit IDs (never from a working tree), archive
downloads are checked before use, and gitlinks are recursively populated.
The generated bundle remains a candidate unless every declared source gap is
closed by its bound, tool-verified evidence path.  Editing a status string is
never sufficient to produce a release-approved bundle.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import posixpath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


TOOL_VERSION = 1
CANDIDATE_BUNDLE_STATUS = "candidate-only-not-release-approved"
RELEASE_APPROVED_BUNDLE_STATUS = "release-approved"
PYTETWILD_REBUILD_RESOLVER = "pytetwild-controlled-rebuild"
DYNAMIC_ARCHIVE_LOCK_RESOLVER = "complete-dynamic-archive-sha256-lock"
DYNAMIC_ARCHIVE_LOCK_RESOLUTION = "verified-complete-dynamic-archive-sha256-lock"
EXTERNAL_ARCHIVE_LOCK_V1_STATUS = "verified-official-release-assets"
EXTERNAL_ARCHIVE_LOCK_V2_STATUS = "verified-official-release-inputs"
EXTERNAL_ARCHIVE_PROVENANCE_KINDS = {
    "github-release-asset",
    "github-tag-source-archive",
    "official-release-checksum",
    "official-project-file-release",
    "official-archive-byte-equivalence",
    "meshlab-historical-tag-archive",
}
APPLICATION_REQUIREMENTS_LOCK_PATH = "source/fixed_app/requirements-build.lock"
COMPONENT_MANIFEST_PATH = "tooling/corresponding_source_components.json"
EXTERNAL_ARCHIVE_LOCK_PATH = "tooling/meshlab_windows_external_archives.lock.json"
PYTETWILD_BUILD_RECIPE_PATH = "tooling/BUILD_PYTETWILD_WINDOWS.ps1"
PYTETWILD_BUILD_REQUIREMENTS_PATH = "tooling/requirements-pytetwild-build.lock"
PYTETWILD_REBUILD_TEMPLATE_PATH = "tooling/pytetwild_rebuild_lock.template.json"
PYTETWILD_SOURCE_PATCH_PATH = (
    "tooling/patches/pytetwild-0.3.0-optional-pyvista.patch"
)
MAX_ARCHIVE_MEMBERS = 500_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 40 * 1024 * 1024 * 1024
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MD5_RE = re.compile(r"^[0-9a-f]{32}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
EXACT_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)+(?:[A-Za-z0-9._+-]*)?$")
UTC_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
PRIVATE_PATH_PATTERNS = (
    re.compile(
        rb"(?i)[a-z]:[\\/]+users[\\/]+[^\\/\x00\r\n\"']+(?:[\\/]|(?=[\s\"']|$))"
    ),
    re.compile(rb"(?i)/(?:home|users)/[^/\x00\r\n\"']+(?:/|(?=[\s\"']|$))"),
    re.compile(
        rb"(?i)(?:\\{2,}|/{2})[^\\/\x00\r\n\"']+"
        rb"(?:[\\/]+[^\\/\x00\r\n\"']+)?"
        rb"[\\/]+(?:home|users)[\\/]+[^\\/\x00\r\n\"']+"
        rb"(?:[\\/]|(?=[\s\"']|$))"
    ),
)
PYTETWILD_AUDIT_LOG_FILES = {
    "visual_studio_layout_verification": "visual-studio-layout-verification.log",
    "build_wheel": "build-wheel.log",
    "raw_delvewheel_show": "delvewheel-show-raw.log",
    "delvewheel_repair": "delvewheel-repair.log",
    "abi3audit": "abi3audit.log",
    "native_dependency_closure": "native-dependency-closure.log",
    "native_smoke_install": "native-smoke-install.log",
    "native_normal_import": "native-normal-import.log",
}
PYTETWILD_MAX_AUDIT_LOG_BYTES = 64 * 1024 * 1024
PYTETWILD_LOCK_ENVIRONMENT_FIELDS = {
    "python_version",
    "pip_version",
    "cibuildwheel_version",
    "runner_image",
    "compiler",
    "compiler_family_requested_from_vsdevcmd",
    "visual_studio_installation_version",
    "cmake_version",
    "ninja_version",
    "nanobind_version",
    "build_version",
    "scikit_build_core_version",
    "delvewheel_version",
    "abi3audit_version",
    "numpy_version",
    "windows_sdk_version",
    "windows_sdk_servicing_version",
}
PYTETWILD_ATTESTATION_ENVIRONMENT_FIELDS = PYTETWILD_LOCK_ENVIRONMENT_FIELDS | {
    "compiler_path",
    "linker_path",
    "compiler_file_version",
    "compiler_product_version",
    "linker_file_version",
    "linker_product_version",
    "signtool_path",
    "cmake_cli",
    "ninja_cli",
}
PYTETWILD_SOURCE_ARCHIVE_FIELDS = {
    "pytetwild_sha256",
    "ftetwild_sha256",
    "fmt_sha256",
    "spdlog_sha256",
    "libigl_sha256",
    "predicates_sha256",
    "geogram_sha256",
    "geogram_amgcl_sha256",
    "geogram_libmeshb_sha256",
    "geogram_rply_sha256",
    "onetbb_sha256",
    "json_sha256",
}


class StageError(RuntimeError):
    """A validation or staging error that must fail the bundle closed."""


def _json_load_bytes(payload: bytes, label: str) -> dict:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StageError(f"Cannot read JSON {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise StageError(f"JSON root must be an object: {label}")
    return value


def _json_load(path: Path) -> dict:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise StageError(f"Cannot read JSON {path.name}: {exc}") from exc
    return _json_load_bytes(payload, path.name)


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise StageError(f"{label} must match {ID_RE.pattern!r}")
    return value


def _safe_relative(
    value: object,
    label: str,
    *,
    allow_glob_asterisk: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise StageError(f"{label} must be a non-empty relative path")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise StageError(f"{label} contains a control character: {value!r}")
    if unicodedata.normalize("NFC", value) != value:
        raise StageError(f"{label} is not NFC-normalized: {value!r}")
    if "\\" in value or WINDOWS_DRIVE_RE.match(value) or value.startswith("/"):
        raise StageError(f"{label} is not a normalized POSIX relative path: {value!r}")
    path = PurePosixPath(value)
    if str(path) != value or any(part in ("", ".", "..") for part in path.parts):
        raise StageError(f"{label} is not a normalized POSIX relative path: {value!r}")
    for part in path.parts:
        forbidden = '<>:"|?' if allow_glob_asterisk else '<>:"|?*'
        if any(character in forbidden for character in part):
            raise StageError(f"{label} contains a Windows-unsafe segment: {part!r}")
        if part.endswith((".", " ")):
            raise StageError(f"{label} contains a Windows-unsafe segment: {part!r}")
        stem = part.split(".", 1)[0].casefold()
        if stem in WINDOWS_RESERVED:
            raise StageError(f"{label} contains a reserved Windows name: {part!r}")
    return value


def _validate_https_url(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise StageError(f"{label} must be an HTTPS URL")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise StageError(f"{label} must be an HTTPS URL without credentials or fragment")
    return value


def _canonical_git_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(_validate_https_url(value, "git URL"))
    path = parsed.path.rstrip("/")
    if path.casefold().endswith(".git"):
        path = path[:-4]
    return urllib.parse.urlunsplit(("https", parsed.netloc.casefold(), path, "", ""))


def _validate_required_gitlinks(value: object, label: str, *, required: bool) -> None:
    if not isinstance(value, list) or (required and not value):
        qualifier = "a non-empty" if required else "an"
        raise StageError(f"{label} must be {qualifier} array")
    seen_paths: set[str] = set()
    for index, expectation in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(expectation, dict) or set(expectation) not in (
            {"path", "url"},
            {"path", "url", "commit"},
        ):
            raise StageError(f"{item_label} has an invalid schema")
        path = _safe_relative(expectation.get("path"), f"{item_label}.path")
        folded = path.casefold()
        if folded in seen_paths:
            raise StageError(f"{label} has a duplicate path: {path}")
        seen_paths.add(folded)
        _validate_https_url(expectation.get("url"), f"{item_label}.url")
        if "commit" in expectation:
            commit = expectation["commit"]
            if not isinstance(commit, str) or not SHA1_RE.fullmatch(commit):
                raise StageError(f"{item_label}.commit must be a full lowercase commit")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if reparse_attribute and (
        getattr(metadata, "st_file_attributes", 0) & reparse_attribute
    ):
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _assert_plain_directory(path: Path, label: str) -> None:
    if not path.is_dir() or _is_link_like(path):
        raise StageError(f"{label} must be a real directory, not a link: {path}")


def _component_map(manifest: dict) -> dict[str, dict]:
    components = manifest.get("components")
    if not isinstance(components, list) or not components:
        raise StageError("components must be a non-empty array")
    result: dict[str, dict] = {}
    destinations: dict[str, str] = {}
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            raise StageError(f"components[{index}] must be an object")
        component_id = _safe_id(component.get("id"), f"components[{index}].id")
        if component_id in result:
            raise StageError(f"Duplicate component id: {component_id}")
        destination = _safe_relative(
            component.get("destination"), f"component {component_id} destination"
        )
        folded = destination.casefold()
        if folded in destinations:
            raise StageError(
                f"Duplicate case-insensitive destination for {component_id} and "
                f"{destinations[folded]}"
            )
        destinations[folded] = component_id
        kind = component.get("kind")
        if kind == "git":
            _validate_https_url(component.get("url"), f"component {component_id} URL")
            commit = component.get("commit")
            if not isinstance(commit, str) or not SHA1_RE.fullmatch(commit):
                raise StageError(f"component {component_id} needs a full lowercase commit")
            required = component.get("required_paths", [])
            if not isinstance(required, list):
                raise StageError(f"component {component_id} required_paths must be an array")
            for path in required:
                _safe_relative(path, f"component {component_id} required path")
            _validate_required_gitlinks(
                component.get("required_gitlinks", []),
                f"component {component_id} required_gitlinks",
                required="required_gitlinks" in component,
            )
        elif kind == "archive":
            urls = component.get("urls")
            if not isinstance(urls, list) or not urls:
                raise StageError(f"archive component {component_id} needs URLs")
            for url in urls:
                _validate_https_url(url, f"archive component {component_id} URL")
            digest = component.get("sha256")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise StageError(f"archive component {component_id} needs lowercase SHA-256")
            if component.get("stage_mode") not in ("preserve", "extract"):
                raise StageError(
                    f"archive component {component_id} stage_mode must be preserve or extract"
                )
            for field in ("required_source_members", "required_source_prefixes"):
                if field not in component:
                    continue
                required = component[field]
                if not isinstance(required, list) or not required:
                    raise StageError(
                        f"archive component {component_id} {field} must be a non-empty array"
                    )
                seen_required: set[str] = set()
                for required_index, value in enumerate(required):
                    path = _safe_relative(
                        value,
                        f"archive component {component_id} {field}[{required_index}]",
                    )
                    folded_path = path.casefold()
                    if folded_path in seen_required:
                        raise StageError(
                            f"archive component {component_id} {field} has a "
                            f"duplicate case-insensitive path: {path}"
                        )
                    seen_required.add(folded_path)
        else:
            raise StageError(f"Unsupported component kind for {component_id}: {kind!r}")
        result[component_id] = component
    return result


def validate_component_manifest(manifest: dict) -> dict[str, dict]:
    if manifest.get("schema_version") != 1:
        raise StageError("Unsupported component manifest schema_version")
    _safe_id(manifest.get("bundle_id"), "bundle_id")
    if manifest.get("bundle_status") != CANDIDATE_BUNDLE_STATUS:
        raise StageError(f"bundle_status must remain {CANDIDATE_BUNDLE_STATUS}")
    known_gaps = manifest.get("known_gaps", [])
    if not isinstance(known_gaps, list):
        raise StageError("known_gaps must be an array")
    release_approval = manifest.get("release_approval")
    if release_approval is not None:
        if not isinstance(release_approval, dict) or set(release_approval) != {
            "status",
            "requires_all_known_gaps_resolved",
            "required_gap_ids",
        }:
            raise StageError("release_approval has an invalid schema")
        if (
            release_approval["status"] != RELEASE_APPROVED_BUNDLE_STATUS
            or release_approval["requires_all_known_gaps_resolved"] is not True
        ):
            raise StageError("release_approval must require every known gap to be resolved")
        required_gap_ids = release_approval["required_gap_ids"]
        if not isinstance(required_gap_ids, list) or not required_gap_ids:
            raise StageError("release_approval requires a non-empty required_gap_ids array")
        for index, gap_id in enumerate(required_gap_ids):
            _safe_id(gap_id, f"release_approval.required_gap_ids[{index}]")
        if len(set(required_gap_ids)) != len(required_gap_ids):
            raise StageError("release_approval has duplicate required_gap_ids")
    gap_ids: set[str] = set()
    gap_resolvers: dict[str, dict] = {}
    for index, gap in enumerate(known_gaps):
        if not isinstance(gap, dict):
            raise StageError(f"known_gaps[{index}] must be an object")
        gap_id = _safe_id(gap.get("id"), f"known_gaps[{index}].id")
        if gap_id in gap_ids or gap.get("status") != "unresolved":
            raise StageError(f"Invalid or duplicate unresolved gap: {gap_id}")
        if not isinstance(gap.get("reason"), str) or not gap["reason"]:
            raise StageError(f"known_gaps[{index}] needs a reason")
        resolver = gap.get("resolution_evidence")
        if release_approval is not None and not isinstance(resolver, dict):
            raise StageError(f"known_gaps[{index}] needs bound resolution_evidence")
        if release_approval is None and resolver is not None:
            raise StageError("resolution_evidence requires an explicit release_approval policy")
        if isinstance(resolver, dict):
            kind = resolver.get("kind")
            if kind == PYTETWILD_REBUILD_RESOLVER:
                expected_keys = {"kind"}
            elif kind == DYNAMIC_ARCHIVE_LOCK_RESOLVER:
                expected_keys = {"kind", "rule_id"}
                _safe_id(
                    resolver.get("rule_id"),
                    f"known_gaps[{index}].resolution_evidence.rule_id",
                )
            else:
                raise StageError(f"known_gaps[{index}] has an unsupported resolver")
            if set(resolver) != expected_keys:
                raise StageError(f"known_gaps[{index}] resolution_evidence has extra fields")
            gap_resolvers[gap_id] = resolver
        gap_ids.add(gap_id)
    if release_approval is not None and set(release_approval["required_gap_ids"]) != gap_ids:
        raise StageError("release_approval required_gap_ids must match every known gap")
    project = manifest.get("project")
    if not isinstance(project, dict):
        raise StageError("project must be an object")
    _safe_id(project.get("id"), "project.id")
    _validate_https_url(project.get("public_url"), "project.public_url")
    project_destination = _safe_relative(project.get("destination"), "project.destination")

    default_external_lock = manifest.get("default_external_archive_lock")
    if default_external_lock is not None:
        _safe_relative(default_external_lock, "default_external_archive_lock")

    suffixes = manifest.get("allowed_redirect_host_suffixes")
    if not isinstance(suffixes, list) or not suffixes:
        raise StageError("allowed_redirect_host_suffixes must be a non-empty array")
    for suffix in suffixes:
        if (
            not isinstance(suffix, str)
            or not suffix
            or "/" in suffix
            or ":" in suffix
            or suffix != suffix.casefold()
        ):
            raise StageError(f"Invalid redirect host suffix: {suffix!r}")

    components = _component_map(manifest)
    for component in components.values():
        destination = component["destination"]
        if destination.casefold() == project_destination.casefold():
            raise StageError("Project and dependency destinations collide")

    relations = manifest.get("submodule_relations", [])
    if not isinstance(relations, list):
        raise StageError("submodule_relations must be an array")
    child_parents: dict[str, tuple[str, str]] = {}
    relation_keys: set[tuple[str, str]] = set()
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            raise StageError(f"submodule_relations[{index}] must be an object")
        parent = relation.get("parent")
        child = relation.get("child")
        if parent not in components or child not in components:
            raise StageError(f"Unknown component in submodule relation {index}")
        if components[parent]["kind"] != "git" or components[child]["kind"] != "git":
            raise StageError("Submodule relations require git components")
        path = _safe_relative(relation.get("path"), f"submodule relation {index} path")
        key = (parent, path.casefold())
        if key in relation_keys:
            raise StageError(f"Duplicate submodule relation: {parent}:{path}")
        relation_keys.add(key)
        if child in child_parents:
            raise StageError(f"Submodule component has multiple parents: {child}")
        child_parents[child] = (parent, path)
        expected_destination = f"{components[parent]['destination']}/{path}"
        if components[child]["destination"] != expected_destination:
            raise StageError(
                f"Submodule {child} destination must be {expected_destination!r}"
            )

    ancestors: dict[str, set[str]] = {}
    for component_id in components:
        lineage: set[str] = set()
        current = component_id
        while current in child_parents:
            parent = child_parents[current][0]
            if parent == component_id or parent in lineage:
                raise StageError(f"Submodule relation cycle includes {component_id}")
            lineage.add(parent)
            current = parent
        ancestors[component_id] = lineage
    component_items = list(components.items())
    for outer_id, outer in component_items:
        outer_prefix = f"{outer['destination'].casefold()}/"
        for inner_id, inner in component_items:
            if outer_id == inner_id:
                continue
            if inner["destination"].casefold().startswith(outer_prefix) and outer_id not in ancestors[
                inner_id
            ]:
                raise StageError(
                    f"Nested component destination is not a submodule relation: "
                    f"{outer_id} -> {inner_id}"
                )

    rebuild_policy = manifest.get("pytetwild_rebuild_policy")
    if rebuild_policy is not None:
        if not isinstance(rebuild_policy, dict):
            raise StageError("pytetwild_rebuild_policy must be an object")
        component_id = rebuild_policy.get("component")
        if component_id not in components or components[component_id]["kind"] != "git":
            raise StageError("pytetwild_rebuild_policy has an invalid component")
        if rebuild_policy.get("known_gap_id") not in gap_ids:
            raise StageError("pytetwild_rebuild_policy known_gap_id is not unresolved")
        _safe_relative(rebuild_policy.get("template"), "pytetwild_rebuild_policy.template")
        destination = _safe_relative(
            rebuild_policy.get("nanobind_destination"),
            "pytetwild_rebuild_policy.nanobind_destination",
        )
        _validate_required_gitlinks(
            rebuild_policy.get("nanobind_required_gitlinks"),
            "pytetwild_rebuild_policy.nanobind_required_gitlinks",
            required=True,
        )
        if any(
            destination.casefold() == item["destination"].casefold()
            or destination.casefold().startswith(f"{item['destination'].casefold()}/")
            or item["destination"].casefold().startswith(f"{destination.casefold()}/")
            for item in components.values()
        ):
            raise StageError("pytetwild_rebuild_policy nanobind destination collides")
        if rebuild_policy.get("required_for_staging") is not True:
            raise StageError("pytetwild_rebuild_policy must be required_for_staging")
    pytetwild_gap_ids = {
        gap_id
        for gap_id, resolver in gap_resolvers.items()
        if resolver["kind"] == PYTETWILD_REBUILD_RESOLVER
    }
    if pytetwild_gap_ids:
        if rebuild_policy is None or pytetwild_gap_ids != {rebuild_policy.get("known_gap_id")}:
            raise StageError("PyTetWild gap resolver is not bound to its rebuild policy")

    evidence = manifest.get("pin_evidence", [])
    if not isinstance(evidence, list):
        raise StageError("pin_evidence must be an array")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict) or item.get("component") not in components:
            raise StageError(f"Invalid pin_evidence component at index {index}")
        _safe_relative(item.get("path"), f"pin_evidence[{index}].path")
        literals = item.get("required_literals")
        if not isinstance(literals, list) or not literals or not all(
            isinstance(value, str) and value for value in literals
        ):
            raise StageError(f"pin_evidence[{index}] needs required_literals")

    rules = manifest.get("dynamic_archive_rules", [])
    if not isinstance(rules, list):
        raise StageError("dynamic_archive_rules must be an array")
    rule_ids: set[str] = set()
    rules_by_id: dict[str, dict] = {}
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise StageError(f"dynamic_archive_rules[{index}] must be an object")
        rule_id = _safe_id(rule.get("id"), f"dynamic_archive_rules[{index}].id")
        if rule_id in rule_ids:
            raise StageError(f"Duplicate dynamic archive rule id: {rule_id}")
        rule_ids.add(rule_id)
        rules_by_id[rule_id] = rule
        component_id = rule.get("component")
        if component_id not in components or components[component_id]["kind"] != "git":
            raise StageError(f"Dynamic archive rule {rule_id} has invalid component")
        _safe_relative(
            rule.get("source_glob"),
            f"dynamic rule {rule_id} source_glob",
            allow_glob_asterisk=True,
        )
        _safe_relative(rule.get("destination"), f"dynamic rule {rule_id} destination")
        for field in ("link_variable_suffix", "md5_variable_suffix"):
            if not isinstance(rule.get(field), str) or not rule[field].startswith("_"):
                raise StageError(f"Dynamic rule {rule_id} has invalid {field}")
        unhashed = rule.get("known_unhashed_variables", [])
        excluded = rule.get("excluded_variables", {})
        if not isinstance(unhashed, list) or not all(
            isinstance(value, str) and value for value in unhashed
        ):
            raise StageError(f"Dynamic rule {rule_id} known_unhashed_variables is invalid")
        if len({value.casefold() for value in unhashed}) != len(unhashed):
            raise StageError(f"Dynamic rule {rule_id} has duplicate unhashed variables")
        if not isinstance(excluded, dict) or not all(
            isinstance(key, str)
            and key
            and isinstance(reason, str)
            and reason
            for key, reason in excluded.items()
        ):
            raise StageError(f"Dynamic rule {rule_id} excluded_variables is invalid")
    resolved_rule_ids: set[str] = set()
    for gap_id, resolver in gap_resolvers.items():
        if resolver["kind"] != DYNAMIC_ARCHIVE_LOCK_RESOLVER:
            continue
        rule_id = resolver["rule_id"]
        rule = rules_by_id.get(rule_id)
        if rule is None:
            raise StageError(f"Dynamic archive gap {gap_id} references an unknown rule")
        if rule_id in resolved_rule_ids:
            raise StageError(f"Dynamic archive rule {rule_id} resolves multiple gaps")
        resolved_rule_ids.add(rule_id)
        if (
            rule.get("require_sha256_lock_for_unhashed") is not True
            or rule.get("require_release_asset_provenance") is not True
        ):
            raise StageError(
                f"Dynamic archive gap {gap_id} requires SHA-256 and release provenance"
            )
    return components


def _run_git(repository: Path, arguments: list[str], *, allow_file: bool = False) -> str:
    command = [
        "git",
        "-c",
        "core.safecrlf=false",
        "-c",
        "http.followRedirects=false",
        "-c",
        f"protocol.file.allow={'always' if allow_file else 'never'}",
        "-C",
        str(repository),
        *arguments,
    ]
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
        env=environment,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        summary = detail[-1] if detail else f"exit {result.returncode}"
        raise StageError(f"git {' '.join(arguments[:2])} failed: {summary}")
    return result.stdout


def _git_object_exists(repository: Path, commit: str, *, allow_file: bool = False) -> bool:
    try:
        _run_git(repository, ["cat-file", "-e", f"{commit}^{{commit}}"], allow_file=allow_file)
    except StageError:
        return False
    return True


def _git_file_at_exact_commit(repository: Path, commit: str, relative: str) -> bytes:
    if not isinstance(commit, str) or not SHA1_RE.fullmatch(commit):
        raise StageError("Project commit must be a full lowercase 40-character commit")
    _assert_plain_directory(repository, "Project repository")
    resolved = _run_git(
        repository,
        ["rev-parse", f"{commit}^{{commit}}"],
        allow_file=True,
    ).strip()
    if resolved != commit:
        raise StageError("Project repository does not contain the exact requested commit")

    relative = _safe_relative(relative, "project commit file")
    tree_output = _run_git(
        repository,
        ["ls-tree", "-z", commit, "--", relative],
        allow_file=True,
    )
    records = [record for record in tree_output.split("\x00") if record]
    if len(records) != 1:
        raise StageError(f"Project commit lacks one exact regular file: {relative}")
    metadata, separator, tree_path = records[0].partition("\t")
    fields = metadata.split()
    if (
        separator != "\t"
        or tree_path != relative
        or len(fields) != 3
        or fields[0] not in ("100644", "100755")
        or fields[1] != "blob"
        or not re.fullmatch(r"[0-9a-f]{40,64}", fields[2])
    ):
        raise StageError(f"Project commit path is not one exact regular file: {relative}")

    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.safecrlf=false",
            "-c",
            "http.followRedirects=false",
            "-c",
            "protocol.file.allow=always",
            "-C",
            str(repository),
            "cat-file",
            "blob",
            fields[2],
        ],
        check=False,
        capture_output=True,
        env=environment,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        summary = detail[-1] if detail else f"exit {result.returncode}"
        raise StageError(f"Cannot read project commit file {relative}: {summary}")
    return result.stdout


def _cache_git_repository(
    component_id: str,
    public_url: str,
    commit: str,
    cache_root: Path,
    *,
    offline: bool,
    fixture_repository: Path | None,
) -> Path:
    cache_key = hashlib.sha256(public_url.encode("utf-8")).hexdigest()[:16]
    repository = cache_root / "git" / f"{component_id}-{cache_key}.git"
    repository.parent.mkdir(parents=True, exist_ok=True)
    if repository.exists():
        _assert_plain_directory(repository, "Git cache entry")
    else:
        if offline and fixture_repository is None:
            raise StageError(f"Offline git cache miss for {component_id}")
        temporary = repository.parent / f".{repository.name}.fetch-{uuid.uuid4().hex}"
        if temporary.exists():
            raise StageError(f"Unexpected git cache temporary path: {temporary}")
        try:
            temporary.mkdir()
            _run_git(temporary, ["init", "--bare"], allow_file=fixture_repository is not None)
            source = str(fixture_repository) if fixture_repository is not None else public_url
            _run_git(
                temporary,
                ["fetch", "--depth=1", "--no-tags", source, commit],
                allow_file=fixture_repository is not None,
            )
            resolved = _run_git(
                temporary, ["rev-parse", f"{commit}^{{commit}}"], allow_file=True
            ).strip()
            if resolved != commit:
                raise StageError(f"Git commit verification failed for {component_id}")
            os.replace(temporary, repository)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    if not _git_object_exists(repository, commit, allow_file=True):
        if offline and fixture_repository is None:
            raise StageError(f"Offline git cache lacks {component_id} commit {commit}")
        source = str(fixture_repository) if fixture_repository is not None else public_url
        _run_git(
            repository,
            ["fetch", "--depth=1", "--no-tags", source, commit],
            allow_file=fixture_repository is not None,
        )
    resolved = _run_git(repository, ["rev-parse", f"{commit}^{{commit}}"], allow_file=True).strip()
    if resolved != commit:
        raise StageError(f"Cached commit verification failed for {component_id}")
    return repository


def _archive_member_parts(
    name: str,
    strip_components: int = 0,
    *,
    is_directory: bool = False,
) -> tuple[str, ...] | None:
    """Return a canonical archive path without normalizing hostile input."""

    if not isinstance(strip_components, int) or strip_components < 0:
        raise StageError("Archive strip-components must be a non-negative integer")
    if not isinstance(name, str) or not name:
        raise StageError(f"Unsafe archive member name: {name!r}")
    if any(unicodedata.category(character) == "Cc" for character in name):
        raise StageError(f"Archive member contains a control character: {name!r}")
    if unicodedata.normalize("NFC", name) != name:
        raise StageError(f"Archive member is not NFC-normalized: {name!r}")
    if "\\" in name or name.startswith("/") or WINDOWS_DRIVE_RE.match(name):
        raise StageError(f"Unsafe archive member name: {name!r}")

    candidate = name
    if is_directory and candidate.endswith("/"):
        candidate = candidate[:-1]
    elif not is_directory and candidate.endswith("/"):
        raise StageError(f"Archive file has a directory path: {name!r}")
    if not candidate:
        raise StageError(f"Unsafe archive member name: {name!r}")
    windows_path = PureWindowsPath(candidate)
    if windows_path.drive or windows_path.root:
        raise StageError(f"Archive member has a Windows drive or root: {name!r}")

    # PurePosixPath silently removes empty and dot components, so split the
    # original spelling before constructing any normalized path object.
    raw_parts = candidate.split("/")
    if any(part == ".." for part in raw_parts):
        raise StageError(f"Archive traversal or non-normal path: {name!r}")
    if any(part in ("", ".") for part in raw_parts):
        raise StageError(f"Archive traversal or non-normal path: {name!r}")
    for part in raw_parts:
        if ":" in part:
            raise StageError(f"Archive member contains a Windows ADS segment: {name!r}")
        if part.endswith((".", " ")):
            raise StageError(f"Archive member contains a Windows-unsafe segment: {part!r}")
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED:
            raise StageError(f"Archive member contains a reserved Windows name: {part!r}")

    if len(raw_parts) <= strip_components:
        return None
    parts = raw_parts[strip_components:]
    _safe_relative("/".join(parts), f"archive member {name!r}")
    return tuple(parts)


def _register_archive_member(
    seen: dict[tuple[str, ...], str],
    known_ancestors: set[tuple[str, ...]],
    parts: tuple[str, ...],
    member_kind: str,
    name: str,
) -> bool:
    """Register a Windows-equivalent path and reject file/tree conflicts."""

    key = tuple(unicodedata.normalize("NFC", part).casefold() for part in parts)
    previous_kind = seen.get(key)
    if previous_kind is not None:
        if previous_kind == "directory" and member_kind == "directory":
            return False
        raise StageError(f"Duplicate case-insensitive archive member: {name!r}")

    parents = [key[:index] for index in range(1, len(key))]
    if any(seen.get(parent) == "file" for parent in parents):
        raise StageError(f"Archive file/ancestor conflict: {name!r}")
    if member_kind == "file" and key in known_ancestors:
        raise StageError(f"Archive file/ancestor conflict: {name!r}")

    seen[key] = member_kind
    known_ancestors.update(parents)
    return True


def _zip_member_details(
    member: zipfile.ZipInfo,
    strip_components: int = 0,
) -> tuple[str, tuple[str, ...] | None, str, int]:
    """Validate a ZIP member and return its raw name, path, kind, and mode."""

    raw_name = getattr(member, "orig_filename", member.filename)
    if raw_name != member.filename:
        # zipfile truncates filename at NUL but preserves the source spelling
        # in orig_filename. Any disagreement is therefore ambiguous.
        raise StageError(f"Unsafe ZIP member original name: {raw_name!r}")
    if member.flag_bits & 0x41:
        raise StageError(f"Encrypted archive member is forbidden: {raw_name!r}")
    if member.external_attr & 0x400:
        raise StageError(f"Archive reparse-point member is forbidden: {raw_name!r}")

    mode = (member.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if stat.S_ISLNK(mode):
        raise StageError(f"Archive links are forbidden: {raw_name!r}")
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise StageError(f"Archive special member is forbidden: {raw_name!r}")

    is_directory = member.is_dir()
    if (is_directory and file_type not in (0, stat.S_IFDIR)) or (
        not is_directory and file_type == stat.S_IFDIR
    ):
        raise StageError(f"Archive member type disagrees with its path: {raw_name!r}")
    member_kind = "directory" if is_directory else "file"
    parts = _archive_member_parts(
        raw_name,
        strip_components,
        is_directory=is_directory,
    )
    return raw_name, parts, member_kind, mode


def _target_for_parts(destination: Path, parts: tuple[str, ...]) -> Path:
    target = destination.joinpath(*parts)
    root = destination.resolve()
    resolved = target.resolve(strict=False)
    if not _is_relative_to(resolved, root):
        raise StageError(f"Archive path escaped destination: {'/'.join(parts)}")
    return target


def _safe_extract_tar(archive: Path, destination: Path, *, strip_components: int = 0) -> None:
    if destination.exists():
        raise StageError(f"Refusing to extract over existing path: {destination}")
    destination.mkdir(parents=True)
    seen: dict[tuple[str, ...], str] = {}
    known_ancestors: set[tuple[str, ...]] = set()
    count = 0
    total = 0
    with tarfile.open(archive, mode="r:*") as package:
        for member in package:
            count += 1
            if count > MAX_ARCHIVE_MEMBERS:
                raise StageError("Archive has too many members")
            if member.issym() or member.islnk():
                raise StageError(f"Archive links are forbidden: {member.name!r}")
            if not (member.isdir() or member.isfile()):
                raise StageError(f"Archive special member is forbidden: {member.name!r}")
            parts = _archive_member_parts(
                member.name,
                strip_components,
                is_directory=member.isdir(),
            )
            if parts is None:
                continue
            member_kind = "directory" if member.isdir() else "file"
            if not _register_archive_member(
                seen,
                known_ancestors,
                parts,
                member_kind,
                member.name,
            ):
                continue
            target = _target_for_parts(destination, parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += member.size
            if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise StageError("Archive expands beyond the safety limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = package.extractfile(member)
            if source is None:
                raise StageError(f"Cannot read archive member: {member.name!r}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def _safe_extract_zip(archive: Path, destination: Path, *, strip_components: int = 0) -> None:
    if destination.exists():
        raise StageError(f"Refusing to extract over existing path: {destination}")
    destination.mkdir(parents=True)
    seen: dict[tuple[str, ...], str] = {}
    known_ancestors: set[tuple[str, ...]] = set()
    count = 0
    total = 0
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            count += 1
            if count > MAX_ARCHIVE_MEMBERS:
                raise StageError("Archive has too many members")
            raw_name, parts, member_kind, mode = _zip_member_details(
                member,
                strip_components,
            )
            if parts is None:
                continue
            if not _register_archive_member(
                seen,
                known_ancestors,
                parts,
                member_kind,
                raw_name,
            ):
                continue
            target = _target_for_parts(destination, parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += member.file_size
            if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise StageError("Archive expands beyond the safety limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(member, "r") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            target.chmod(0o755 if mode & 0o111 else 0o644)


def _validate_archive_members(archive: Path) -> tuple[str, ...]:
    seen: dict[tuple[str, ...], str] = {}
    known_ancestors: set[tuple[str, ...]] = set()
    file_members: set[str] = set()
    count = 0
    total = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                count += 1
                if count > MAX_ARCHIVE_MEMBERS:
                    raise StageError("Archive has too many members")
                raw_name, parts, member_kind, _mode = _zip_member_details(member)
                if parts is None:
                    continue
                _register_archive_member(
                    seen,
                    known_ancestors,
                    parts,
                    member_kind,
                    raw_name,
                )
                if member_kind == "file":
                    file_members.add("/".join(parts))
                total += member.file_size
                if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise StageError("Archive expands beyond the safety limit")
        return tuple(sorted(file_members))
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive, mode="r:*") as package:
            for member in package:
                count += 1
                if count > MAX_ARCHIVE_MEMBERS:
                    raise StageError("Archive has too many members")
                if member.issym() or member.islnk():
                    raise StageError(f"Archive links are forbidden: {member.name!r}")
                if not (member.isdir() or member.isfile()):
                    raise StageError(
                        f"Archive special member is forbidden: {member.name!r}"
                    )
                parts = _archive_member_parts(
                    member.name,
                    is_directory=member.isdir(),
                )
                if parts is None:
                    continue
                member_kind = "directory" if member.isdir() else "file"
                _register_archive_member(
                    seen,
                    known_ancestors,
                    parts,
                    member_kind,
                    member.name,
                )
                if member_kind == "file":
                    file_members.add("/".join(parts))
                total += member.size
                if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise StageError("Archive expands beyond the safety limit")
        return tuple(sorted(file_members))
    raise StageError(f"Unsupported or damaged source archive: {archive.name}")


def _verify_required_source_archive_coverage(
    archive: Path,
    component: dict,
    *,
    validated_file_members: tuple[str, ...] | None = None,
) -> dict | None:
    """Verify exact source members and populated source-tree prefixes."""

    required_members = component.get("required_source_members", [])
    required_prefixes = component.get("required_source_prefixes", [])
    if not required_members and not required_prefixes:
        return None

    file_members = (
        validated_file_members
        if validated_file_members is not None
        else _validate_archive_members(archive)
    )
    file_member_set = set(file_members)
    missing_members = [
        path for path in required_members if path not in file_member_set
    ]
    if missing_members:
        raise StageError(
            f"Source archive {component['id']} lacks required source members: "
            + ", ".join(missing_members)
        )

    prefix_counts: list[dict[str, object]] = []
    missing_prefixes: list[str] = []
    for prefix in required_prefixes:
        marker = f"{prefix}/"
        count = sum(member.startswith(marker) for member in file_members)
        if count == 0:
            missing_prefixes.append(prefix)
        prefix_counts.append({"prefix": prefix, "file_count": count})
    if missing_prefixes:
        raise StageError(
            f"Source archive {component['id']} lacks files under required source "
            f"prefixes: " + ", ".join(missing_prefixes)
        )

    return {
        "required_source_members": list(required_members),
        "required_source_prefixes": prefix_counts,
    }


def _hash_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_extension(url: str) -> str:
    lowered = urllib.parse.urlsplit(url).path.casefold()
    for extension in (".tar.xz", ".tar.gz", ".tar.bz2", ".tgz", ".zip"):
        if extension in lowered:
            return extension
    return ".archive"


def _host_allowed(host: str | None, suffixes: tuple[str, ...]) -> bool:
    if not host:
        return False
    folded = host.casefold().rstrip(".")
    return any(folded == suffix or folded.endswith(f".{suffix}") for suffix in suffixes)


class _StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_suffixes: tuple[str, ...]) -> None:
        super().__init__()
        self.allowed_suffixes = allowed_suffixes

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        parsed = urllib.parse.urlsplit(new_url)
        if parsed.scheme.casefold() != "https" or not _host_allowed(
            parsed.hostname, self.allowed_suffixes
        ):
            raise StageError(f"Rejected download redirect to unexpected URL: {new_url}")
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


def _download_to_cache(
    component_id: str,
    urls: list[str],
    cache_root: Path,
    *,
    allowed_suffixes: tuple[str, ...],
    sha256: str | None,
    md5: str | None,
    expected_size: int | None = None,
    offline: bool,
    fixture_file: Path | None,
) -> tuple[Path, str, str]:
    if not sha256 and not md5:
        raise StageError(f"Archive {component_id} has no verification hash")
    for url in urls:
        _validate_https_url(url, f"archive {component_id} URL")
        parsed = urllib.parse.urlsplit(url)
        if not _host_allowed(parsed.hostname, allowed_suffixes):
            raise StageError(f"Archive host is not allowlisted for {component_id}: {parsed.hostname}")
    hash_label = f"sha256-{sha256}" if sha256 else f"md5-{md5}"
    extension = _archive_extension(urls[0])
    cache_path = cache_root / "downloads" / f"{component_id}-{hash_label}{extension}"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        if cache_path.is_symlink() or not cache_path.is_file():
            raise StageError(f"Download cache entry is not a regular file: {cache_path}")
        if sha256 and _hash_file(cache_path) != sha256:
            raise StageError(f"Cached SHA-256 mismatch for {component_id}")
        if md5 and _hash_file(cache_path, "md5") != md5:
            raise StageError(f"Cached MD5 mismatch for {component_id}")
        if expected_size is not None and cache_path.stat().st_size != expected_size:
            raise StageError(f"Cached byte-size mismatch for {component_id}")
        return cache_path, urls[0], _hash_file(cache_path)
    if offline and fixture_file is None:
        raise StageError(f"Offline download cache miss for {component_id}")

    temporary = cache_path.parent / f".{cache_path.name}.partial-{uuid.uuid4().hex}"
    selected_url = urls[0]
    try:
        if fixture_file is not None:
            if not fixture_file.is_file() or fixture_file.is_symlink():
                raise StageError(f"Fixture archive is missing or linked: {fixture_file.name}")
            shutil.copyfile(fixture_file, temporary)
        else:
            opener = urllib.request.build_opener(_StrictRedirectHandler(allowed_suffixes))
            last_error: Exception | None = None
            for candidate in urls:
                request = urllib.request.Request(
                    candidate,
                    headers={"User-Agent": "ChromaMatter-corresponding-source/1"},
                )
                try:
                    with opener.open(request, timeout=90) as response, temporary.open("xb") as output:
                        final_url = response.geturl()
                        parsed = urllib.parse.urlsplit(final_url)
                        if parsed.scheme.casefold() != "https" or not _host_allowed(
                            parsed.hostname, allowed_suffixes
                        ):
                            raise StageError(
                                f"Download ended at an unexpected URL for {component_id}"
                            )
                        shutil.copyfileobj(response, output, length=1024 * 1024)
                    selected_url = candidate
                    break
                except (OSError, urllib.error.URLError, StageError) as exc:
                    last_error = exc
                    temporary.unlink(missing_ok=True)
            else:
                raise StageError(
                    f"All download URLs failed for {component_id}: {last_error}"
                )
        actual_sha256 = _hash_file(temporary)
        if expected_size is not None and temporary.stat().st_size != expected_size:
            raise StageError(f"Downloaded byte-size mismatch for {component_id}")
        if sha256 and actual_sha256 != sha256:
            raise StageError(f"Downloaded SHA-256 mismatch for {component_id}")
        if md5 and _hash_file(temporary, "md5") != md5:
            raise StageError(f"Downloaded upstream MD5 mismatch for {component_id}")
        os.replace(temporary, cache_path)
        return cache_path, selected_url, actual_sha256
    finally:
        temporary.unlink(missing_ok=True)


def _list_gitlinks(repository: Path, commit: str) -> dict[str, str]:
    output = _run_git(repository, ["ls-tree", "-r", commit], allow_file=True)
    result: dict[str, str] = {}
    for line in output.splitlines():
        metadata, separator, path = line.partition("\t")
        fields = metadata.split()
        if separator and len(fields) == 3 and fields[0] == "160000" and fields[1] == "commit":
            result[_safe_relative(path, "gitlink path")] = fields[2]
    return result


def _gitmodules(repository: Path, commit: str) -> dict[str, str]:
    try:
        text = _run_git(repository, ["show", f"{commit}:.gitmodules"], allow_file=True)
    except StageError:
        return {}
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise StageError(f"Cannot parse .gitmodules at {commit}: {exc}") from exc
    result: dict[str, str] = {}
    for section in parser.sections():
        if not section.startswith('submodule "'):
            continue
        if not parser.has_option(section, "path") or not parser.has_option(section, "url"):
            raise StageError(f"Incomplete .gitmodules section: {section}")
        path = _safe_relative(parser.get(section, "path"), "submodule path")
        result[path] = parser.get(section, "url").strip()
    return result


def _resolve_submodule_url(parent_url: str, child_url: str) -> str:
    if child_url.startswith("https://"):
        return _validate_https_url(child_url, "submodule URL")
    if not child_url.startswith(("../", "./")):
        raise StageError(f"Submodule URL is not HTTPS or relative: {child_url!r}")
    parent = urllib.parse.urlsplit(_validate_https_url(parent_url, "parent git URL"))
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(parent.path), child_url))
    if not joined.startswith("/") or joined.startswith("/../"):
        raise StageError(f"Relative submodule URL escaped host root: {child_url!r}")
    if not joined.casefold().endswith(".git"):
        joined += ".git"
    return urllib.parse.urlunsplit(("https", parent.netloc, joined, "", ""))


def _verify_required_gitlinks(
    component: dict,
    gitlinks: dict[str, str],
    modules: dict[str, str],
) -> None:
    for expectation in component.get("required_gitlinks", []):
        path = expectation["path"]
        actual_commit = gitlinks.get(path)
        if actual_commit is None:
            raise StageError(
                f"Required gitlink is missing from {component['id']}: {path}"
            )
        expected_commit = expectation.get("commit")
        if expected_commit is not None and actual_commit != expected_commit:
            raise StageError(
                f"Required gitlink commit drift for {component['id']}:{path}; "
                f"tree has {actual_commit}, manifest requires {expected_commit}"
            )
        actual_url = _resolve_submodule_url(component["url"], modules[path])
        if _canonical_git_url(actual_url) != _canonical_git_url(expectation["url"]):
            raise StageError(f"Required gitlink URL drift for {component['id']}:{path}")


def _verify_required_paths(component: dict, destination: Path) -> None:
    for relative in component.get("required_paths", []):
        candidate = destination.joinpath(*PurePosixPath(relative).parts)
        if not candidate.is_file() or candidate.is_symlink():
            raise StageError(
                f"Component {component['id']} is missing required source path {relative}"
            )


def _export_git_tree(repository: Path, commit: str, destination: Path) -> None:
    if destination.exists():
        raise StageError(f"Refusing to export over an existing git destination: {destination}")
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    tree_result = subprocess.run(
        ["git", "-C", str(repository), "ls-tree", "-r", "-z", commit],
        check=False,
        capture_output=True,
        env=environment,
    )
    if tree_result.returncode != 0:
        detail = tree_result.stderr.decode("utf-8", errors="replace").strip()
        raise StageError(f"git ls-tree failed: {detail or tree_result.returncode}")

    entries: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for raw_entry in tree_result.stdout.split(b"\x00"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        fields = metadata.decode("ascii", errors="strict").split()
        if separator != b"\t" or len(fields) != 3:
            raise StageError("git ls-tree returned an invalid record")
        try:
            relative = raw_path.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise StageError("Git source contains a non-UTF-8 path") from exc
        relative = _safe_relative(relative, "git tree path")
        if relative.casefold() in seen:
            raise StageError(f"Git source has a case-insensitive path collision: {relative}")
        seen.add(relative.casefold())
        mode, object_type, object_id = fields
        if not re.fullmatch(r"[0-9a-f]{40,64}", object_id):
            raise StageError(f"Git tree has an invalid object ID: {relative}")
        if mode == "120000":
            raise StageError(f"Git source symlinks are forbidden: {relative}")
        if mode == "160000" and object_type == "commit":
            entries.append((mode, object_type, object_id, relative))
            continue
        if mode not in ("100644", "100755") or object_type != "blob":
            raise StageError(
                f"Unsupported git tree entry {mode} {object_type}: {relative}"
            )
        entries.append((mode, object_type, object_id, relative))

    destination.mkdir(parents=True)
    batch = subprocess.Popen(
        ["git", "-C", str(repository), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    try:
        if batch.stdin is None or batch.stdout is None or batch.stderr is None:
            raise StageError("Cannot open git cat-file batch pipes")
        for mode, object_type, object_id, relative in entries:
            target = destination.joinpath(*PurePosixPath(relative).parts)
            if mode == "160000" and object_type == "commit":
                target.mkdir(parents=True, exist_ok=False)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            batch.stdin.write(object_id.encode("ascii") + b"\n")
            batch.stdin.flush()
            header = batch.stdout.readline()
            header_fields = header.rstrip(b"\n").split()
            if len(header_fields) != 3 or header_fields[1] != b"blob":
                raise StageError(f"git cat-file returned an invalid header for {relative}")
            try:
                remaining = int(header_fields[2])
            except ValueError as exc:
                raise StageError(f"git cat-file returned an invalid size for {relative}") from exc
            with target.open("xb") as output:
                while remaining:
                    block = batch.stdout.read(min(1024 * 1024, remaining))
                    if not block:
                        raise StageError(f"git cat-file truncated source blob: {relative}")
                    output.write(block)
                    remaining -= len(block)
            if batch.stdout.read(1) != b"\n":
                raise StageError(f"git cat-file lost framing after {relative}")
            target.chmod(0o755 if mode == "100755" else 0o644)
        batch.stdin.close()
        return_code = batch.wait()
        if return_code != 0:
            detail = batch.stderr.read().decode("utf-8", errors="replace").strip()
            raise StageError(f"git cat-file failed: {detail or return_code}")
    finally:
        if batch.poll() is None:
            batch.kill()
            batch.wait()
        for stream in (batch.stdin, batch.stdout, batch.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _strip_cmake_comments(text: str) -> str:
    output: list[str] = []
    for line in text.splitlines():
        quoted = False
        escaped = False
        kept: list[str] = []
        for character in line:
            if escaped:
                kept.append(character)
                escaped = False
                continue
            if character == "\\":
                kept.append(character)
                escaped = True
                continue
            if character == '"':
                quoted = not quoted
                kept.append(character)
                continue
            if character == "#" and not quoted:
                break
            kept.append(character)
        output.append("".join(kept))
    return "\n".join(output)


def _cmake_set_variables(text: str) -> dict[str, list[str]]:
    cleaned = _strip_cmake_comments(text)
    result: dict[str, list[str]] = {}
    for match in re.finditer(
        r"(?is)(?<![A-Za-z0-9_])set\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*(.*?)\)",
        cleaned,
    ):
        name = match.group(1)
        lexer = shlex.shlex(io.StringIO(match.group(2)), posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        try:
            values = list(lexer)
        except ValueError as exc:
            raise StageError(f"Cannot tokenize CMake set({name}): {exc}") from exc
        result[name] = values
    return result


def _expand_cmake_token(
    token: str, variables: dict[str, list[str]], stack: tuple[str, ...] = ()
) -> list[str]:
    exact = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", token)
    if exact:
        name = exact.group(1)
        if name in stack:
            raise StageError(f"CMake variable cycle: {' -> '.join((*stack, name))}")
        values = variables.get(name)
        if values is None:
            raise StageError(f"Unresolved CMake variable in source URL: {name}")
        expanded: list[str] = []
        for value in values:
            expanded.extend(_expand_cmake_token(value, variables, (*stack, name)))
        return expanded

    result = token
    for name in re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", token):
        if name in stack:
            raise StageError(f"CMake variable cycle: {' -> '.join((*stack, name))}")
        values = variables.get(name)
        if values is None or len(values) != 1:
            raise StageError(f"Cannot scalar-expand CMake variable: {name}")
        replacement = _expand_cmake_token(values[0], variables, (*stack, name))
        if len(replacement) != 1:
            raise StageError(f"Cannot scalar-expand CMake variable: {name}")
        result = result.replace(f"${{{name}}}", replacement[0])
    return [result]


def _scan_cmake_links(source_root: Path, relative_glob: str, rule: dict) -> dict[str, dict]:
    link_suffix = rule["link_variable_suffix"]
    md5_suffix = rule["md5_variable_suffix"]
    found: dict[str, dict] = {}
    files = sorted(source_root.glob(relative_glob))
    if not files:
        raise StageError(f"Dynamic archive scan matched no files: {relative_glob}")
    for cmake_file in files:
        if not cmake_file.is_file() or cmake_file.is_symlink():
            raise StageError(f"Dynamic archive CMake input is not a regular file: {cmake_file}")
        variables = _cmake_set_variables(cmake_file.read_text(encoding="utf-8"))
        for name, raw_values in variables.items():
            if not name.endswith(link_suffix):
                continue
            expanded: list[str] = []
            for token in raw_values:
                expanded.extend(_expand_cmake_token(token, variables))
            urls = [value for value in expanded if value.startswith(("https://", "http://"))]
            if not urls:
                continue
            if name in found:
                raise StageError(f"Duplicate CMake link variable across files: {name}")
            base = name[: -len(link_suffix)]
            md5_name = f"{base}{md5_suffix}"
            md5: str | None = None
            if md5_name in variables:
                values: list[str] = []
                for token in variables[md5_name]:
                    values.extend(_expand_cmake_token(token, variables))
                if len(values) != 1 or not MD5_RE.fullmatch(values[0].casefold()):
                    raise StageError(f"Invalid active CMake MD5 variable: {md5_name}")
                md5 = values[0].casefold()
            found[name] = {
                "variable": name,
                "urls": urls,
                "md5": md5,
                "cmake_path": cmake_file.relative_to(source_root).as_posix(),
            }
    return found


def _external_lock_url_leaf(value: str) -> str:
    parts = [
        urllib.parse.unquote(part)
        for part in PurePosixPath(urllib.parse.urlsplit(value).path).parts
        if part not in ("", "/")
    ]
    if parts and parts[-1] == "download":
        parts.pop()
    return parts[-1] if parts else ""


def _external_lock_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise StageError(f"{label} must be a non-empty string")
    return value


def _external_lock_positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StageError(f"{label} must be a positive integer")
    return value


def _external_lock_timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise StageError(f"{label} must be a UTC timestamp")
    return value


def _external_lock_sha1(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA1_RE.fullmatch(value):
        raise StageError(f"{label} must be a full lowercase SHA-1")
    return value


def _external_lock_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise StageError(f"{label} must be a lowercase SHA-256")
    return value


def _github_repository_parts(value: object, label: str) -> tuple[str, str, str]:
    url = _validate_https_url(value, label)
    parsed = urllib.parse.urlsplit(url)
    parts = [part for part in PurePosixPath(parsed.path).parts if part not in ("", "/")]
    if (
        parsed.hostname.casefold() != "github.com"
        or parsed.query
        or len(parts) != 2
        or parts[1].casefold().endswith(".git")
    ):
        raise StageError(f"{label} must identify one canonical GitHub repository")
    return url, parts[0], parts[1]


def _validate_github_release_asset_provenance(
    variable: str,
    entry: dict,
    provenance: dict,
    *,
    legacy: bool,
) -> None:
    fields = {
        "asset_name",
        "github_asset_id",
        "github_release_id",
        "github_release_tag",
        "asset_created_at",
        "asset_updated_at",
        "release_repository_url",
        "release_api_url",
        "asset_api_url",
        "resolved_download_url",
        "sha256_method",
    }
    if not legacy:
        fields.add("provenance_kind")
    _require_exact_keys(provenance, fields, f"external lock {variable} provenance")
    if not legacy and provenance["provenance_kind"] != "github-release-asset":
        raise StageError(f"External lock {variable} has the wrong provenance kind")

    asset_id = _external_lock_positive_integer(
        provenance["github_asset_id"], f"external lock {variable} github_asset_id"
    )
    release_id = _external_lock_positive_integer(
        provenance["github_release_id"], f"external lock {variable} github_release_id"
    )
    for field in ("asset_created_at", "asset_updated_at"):
        _external_lock_timestamp(
            provenance[field], f"external lock {variable} provenance {field}"
        )
    asset_name = _external_lock_string(
        provenance["asset_name"], f"external lock {variable} asset_name"
    )
    tag = _external_lock_string(
        provenance["github_release_tag"], f"external lock {variable} release tag"
    )
    repository_url, owner, repository = _github_repository_parts(
        provenance["release_repository_url"],
        f"external lock {variable} release_repository_url",
    )
    expected_api_prefix = f"https://api.github.com/repos/{owner}/{repository}/releases"
    if provenance["release_api_url"] != f"{expected_api_prefix}/{release_id}":
        raise StageError(f"External lock {variable} release API identity does not match")
    if provenance["asset_api_url"] != f"{expected_api_prefix}/assets/{asset_id}":
        raise StageError(f"External lock {variable} asset API identity does not match")
    expected_download = f"{repository_url}/releases/download/{tag}/{asset_name}"
    if legacy:
        if _external_lock_url_leaf(provenance["resolved_download_url"]) != asset_name:
            raise StageError(
                f"External lock {variable} release download asset name does not match"
            )
    else:
        # MeshLab's exact CMake input may retain a pre-rename GitHub repository
        # path (for example embree/embree or oneapi-src/oneTBB).  Bind that
        # source URL's release/tag/asset shape while the API IDs and canonical
        # resolved_download_url bind the current repository identity.
        source_download = urllib.parse.urlsplit(entry["url"])
        source_parts = [
            urllib.parse.unquote(part)
            for part in PurePosixPath(source_download.path).parts
            if part not in ("", "/")
        ]
        if (
            provenance["resolved_download_url"] != expected_download
            or source_download.hostname.casefold() != "github.com"
            or source_download.query
            or len(source_parts) != 6
            or source_parts[2:5] != ["releases", "download", tag]
            or source_parts[5] != asset_name
        ):
            raise StageError(
                f"External lock {variable} release download identity does not match"
            )
    for field in ("release_api_url", "asset_api_url", "resolved_download_url"):
        _validate_https_url(
            provenance[field], f"external lock {variable} provenance {field}"
        )
    if provenance["sha256_method"] != "downloaded-official-github-release-asset":
        raise StageError(f"External lock {variable} has an unapproved SHA-256 method")
    if _external_lock_url_leaf(entry["url"]) != asset_name:
        raise StageError(f"External lock {variable} asset name does not match its source URL")


def _validate_github_tag_provenance(
    variable: str, entry: dict, provenance: dict
) -> None:
    common_fields = {
        "provenance_kind",
        "repository_url",
        "tag",
        "ref_api_url",
        "ref_object_type",
        "ref_object_sha",
        "peeled_commit_sha",
        "peeled_commit_api_url",
        "resolved_download_url",
        "sha256_method",
    }
    object_type = provenance.get("ref_object_type")
    expected_fields = set(common_fields)
    if object_type == "tag":
        expected_fields.update(("annotated_tag_sha", "tag_signature_verified"))
    elif object_type != "commit":
        raise StageError(f"External lock {variable} has an invalid GitHub ref object type")
    _require_exact_keys(
        provenance, expected_fields, f"external lock {variable} provenance"
    )
    if provenance["provenance_kind"] != "github-tag-source-archive":
        raise StageError(f"External lock {variable} has the wrong provenance kind")

    repository_url, owner, repository = _github_repository_parts(
        provenance["repository_url"], f"external lock {variable} repository_url"
    )
    tag = _external_lock_string(provenance["tag"], f"external lock {variable} tag")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        raise StageError(f"External lock {variable} has an unsafe GitHub tag")
    ref_sha = _external_lock_sha1(
        provenance["ref_object_sha"], f"external lock {variable} ref_object_sha"
    )
    commit = _external_lock_sha1(
        provenance["peeled_commit_sha"], f"external lock {variable} peeled_commit_sha"
    )
    expected_ref_api = f"https://api.github.com/repos/{owner}/{repository}/git/refs/tags/{tag}"
    expected_commit_api = (
        f"https://api.github.com/repos/{owner}/{repository}/git/commits/{commit}"
    )
    expected_download = f"{repository_url}/archive/refs/tags/{tag}.zip"
    if provenance["ref_api_url"] != expected_ref_api:
        raise StageError(f"External lock {variable} tag ref API identity does not match")
    if provenance["peeled_commit_api_url"] != expected_commit_api:
        raise StageError(f"External lock {variable} peeled commit identity does not match")
    if provenance["resolved_download_url"] != expected_download or entry["url"] != expected_download:
        raise StageError(f"External lock {variable} tag archive URL identity does not match")
    if object_type == "commit":
        if ref_sha != commit:
            raise StageError(f"External lock {variable} direct tag does not bind its commit")
    else:
        if provenance["annotated_tag_sha"] != ref_sha or not isinstance(
            provenance["tag_signature_verified"], bool
        ):
            raise StageError(f"External lock {variable} annotated tag identity is invalid")
    if provenance["sha256_method"] != "downloaded-github-tag-source-archive":
        raise StageError(f"External lock {variable} has an unapproved SHA-256 method")


def _validate_official_checksum_provenance(
    variable: str, entry: dict, provenance: dict
) -> None:
    _require_exact_keys(
        provenance,
        {
            "provenance_kind",
            "release_repository_url",
            "checksum_url",
            "release_file",
            "source_commit",
            "created_at",
            "resolved_download_url",
            "official_sha256",
            "sha256_method",
        },
        f"external lock {variable} provenance",
    )
    release_url = _validate_https_url(
        provenance["release_repository_url"],
        f"external lock {variable} release_repository_url",
    )
    checksum_url = _validate_https_url(
        provenance["checksum_url"], f"external lock {variable} checksum_url"
    )
    if (
        provenance["provenance_kind"] != "official-release-checksum"
        or provenance["sha256_method"]
        != "downloaded-official-release-archive-verified-by-official-sha256"
        or provenance["resolved_download_url"] != entry["url"]
        or provenance["official_sha256"] != entry["sha256"]
    ):
        raise StageError(f"External lock {variable} official checksum binding is invalid")
    _validate_https_url(
        provenance["resolved_download_url"],
        f"external lock {variable} resolved_download_url",
    )
    if urllib.parse.urlsplit(release_url).hostname.casefold() != urllib.parse.urlsplit(
        checksum_url
    ).hostname.casefold() or urllib.parse.urlsplit(entry["url"]).hostname.casefold() != (
        urllib.parse.urlsplit(release_url).hostname.casefold()
    ):
        raise StageError(f"External lock {variable} checksum host does not match its release")
    release_file = _external_lock_string(
        provenance["release_file"], f"external lock {variable} release_file"
    )
    if release_file != _external_lock_url_leaf(entry["url"]):
        raise StageError(f"External lock {variable} release filename does not match")
    _external_lock_sha1(
        provenance["source_commit"], f"external lock {variable} source_commit"
    )
    _external_lock_timestamp(
        provenance["created_at"], f"external lock {variable} created_at"
    )


def _validate_official_project_file_provenance(
    variable: str, entry: dict, provenance: dict
) -> None:
    _require_exact_keys(
        provenance,
        {
            "provenance_kind",
            "project_url",
            "file_page_url",
            "asset_name",
            "published_at",
            "resolved_download_url",
            "official_md5",
            "sha256_method",
        },
        f"external lock {variable} provenance",
    )
    project_url = _validate_https_url(
        provenance["project_url"], f"external lock {variable} project_url"
    )
    file_page_url = _validate_https_url(
        provenance["file_page_url"], f"external lock {variable} file_page_url"
    )
    if (
        urllib.parse.urlsplit(project_url).hostname.casefold() != "sourceforge.net"
        or urllib.parse.urlsplit(file_page_url).hostname.casefold() != "sourceforge.net"
        or urllib.parse.urlsplit(entry["url"]).hostname.casefold() != "sourceforge.net"
        or provenance["provenance_kind"] != "official-project-file-release"
        or provenance["sha256_method"]
        != "downloaded-official-sourceforge-release-file-verified-by-upstream-cmake-md5"
        or provenance["resolved_download_url"] != entry["url"]
        or provenance["official_md5"] != entry["upstream_md5"]
    ):
        raise StageError(f"External lock {variable} official project-file binding is invalid")
    _validate_https_url(
        provenance["resolved_download_url"],
        f"external lock {variable} resolved_download_url",
    )
    if provenance["asset_name"] != _external_lock_url_leaf(entry["url"]):
        raise StageError(f"External lock {variable} project asset name does not match")
    _external_lock_timestamp(
        provenance["published_at"], f"external lock {variable} published_at"
    )


def _validate_official_mirror_provenance(
    variable: str, entry: dict, provenance: dict
) -> None:
    expected_fields = {
        "provenance_kind",
        "official_reference_url",
        "official_reference_last_modified",
        "official_reference_etag",
        "official_reference_sha256",
        "official_reference_md5",
        "official_reference_byte_size",
        "resolved_download_url",
        "sha256_method",
    }
    if provenance.get("sha256_method") == (
        "downloaded-meshlab-mirror-byte-identical-to-apache-archive"
    ):
        expected_fields.add("cmake_primary_url_status")
    _require_exact_keys(
        provenance,
        expected_fields,
        f"external lock {variable} provenance",
    )
    reference_url = _validate_https_url(
        provenance["official_reference_url"],
        f"external lock {variable} official_reference_url",
    )
    resolved_url = _validate_https_url(
        provenance["resolved_download_url"],
        f"external lock {variable} resolved_download_url",
    )
    method_hosts = {
        "downloaded-meshlab-mirror-byte-identical-to-google-code-archive": (
            "storage.googleapis.com"
        ),
        "downloaded-meshlab-mirror-byte-identical-to-apache-archive": (
            "archive.apache.org"
        ),
    }
    reference_host = method_hosts.get(provenance["sha256_method"])
    if (
        provenance["provenance_kind"] != "official-archive-byte-equivalence"
        or reference_host is None
        or urllib.parse.urlsplit(reference_url).hostname.casefold() != reference_host
        or urllib.parse.urlsplit(resolved_url).hostname.casefold()
        not in ("meshlab.net", "www.meshlab.net")
        or resolved_url != entry["url"]
        or _external_lock_url_leaf(reference_url) != _external_lock_url_leaf(resolved_url)
        or provenance["official_reference_sha256"] != entry["sha256"]
        or provenance["official_reference_md5"] != entry["upstream_md5"]
        or provenance["official_reference_byte_size"] != entry["byte_size"]
        or (
            reference_host == "archive.apache.org"
            and provenance["cmake_primary_url_status"] != 404
        )
    ):
        raise StageError(f"External lock {variable} official mirror equivalence is invalid")
    _external_lock_timestamp(
        provenance["official_reference_last_modified"],
        f"external lock {variable} official_reference_last_modified",
    )
    _external_lock_string(
        provenance["official_reference_etag"],
        f"external lock {variable} official_reference_etag",
    )


def _validate_tinygltf_historical_provenance(
    variable: str, entry: dict, provenance: dict
) -> None:
    _require_exact_keys(
        provenance,
        {
            "provenance_kind",
            "repository_url",
            "tag",
            "ref_api_url",
            "ref_object_type",
            "ref_object_sha",
            "peeled_commit_sha",
            "peeled_commit_api_url",
            "current_github_tag_archive_sha256",
            "current_github_tag_archive_md5",
            "common_file_count",
            "common_file_content_mismatches",
            "meshlab_only_paths",
            "resolved_download_url",
            "sha256_method",
            "tag_tree_contains_meshlab_only_file",
            "meshlab_only_file_sha256",
            "meshlab_only_file_authenticode_status",
            "security_review_required",
            "known_difference",
            "meshlab_only_file_execution_policy",
            "release_review_status",
        },
        f"external lock {variable} provenance",
    )
    ref_sha = _external_lock_sha1(
        provenance["ref_object_sha"], f"external lock {variable} ref_object_sha"
    )
    commit = _external_lock_sha1(
        provenance["peeled_commit_sha"], f"external lock {variable} peeled_commit_sha"
    )
    current_sha256 = _external_lock_sha256(
        provenance["current_github_tag_archive_sha256"],
        f"external lock {variable} current GitHub archive SHA-256",
    )
    current_md5 = provenance["current_github_tag_archive_md5"]
    if not isinstance(current_md5, str) or not MD5_RE.fullmatch(current_md5):
        raise StageError(f"External lock {variable} current GitHub archive MD5 is invalid")
    if (
        variable != "TINYGLTF_LINK"
        or provenance["provenance_kind"] != "meshlab-historical-tag-archive"
        or provenance["repository_url"] != "https://github.com/syoyo/tinygltf"
        or provenance["tag"] != "v2.6.3"
        or provenance["ref_object_type"] != "tag"
        or provenance["ref_api_url"]
        != "https://api.github.com/repos/syoyo/tinygltf/git/refs/tags/v2.6.3"
        or provenance["peeled_commit_api_url"]
        != f"https://api.github.com/repos/syoyo/tinygltf/git/commits/{commit}"
        or provenance["resolved_download_url"] != entry["url"]
        or urllib.parse.urlsplit(entry["url"]).hostname.casefold()
        not in ("meshlab.net", "www.meshlab.net")
        or current_sha256 == entry["sha256"]
        or current_md5 == entry["upstream_md5"]
        or provenance["common_file_count"] != 1338
        or provenance["common_file_content_mismatches"] != 0
        or provenance["meshlab_only_paths"] != ["tools/windows/premake5.exe"]
        or provenance["tag_tree_contains_meshlab_only_file"] is not False
        or provenance["meshlab_only_file_authenticode_status"] != "NotSigned"
        or provenance["security_review_required"] is not True
        or provenance["known_difference"]
        != "meshlab-mirror-adds-one-unsigned-file-not-in-tag-tree"
        or provenance["meshlab_only_file_execution_policy"] != "preserve-do-not-execute"
        or provenance["release_review_status"] != "required-before-binary-release"
        or provenance["sha256_method"]
        != "downloaded-meshlab-historical-archive-verified-by-upstream-cmake-md5-and-tag-tree-comparison"
        or ref_sha == commit
    ):
        raise StageError(f"External lock {variable} historical mirror evidence is invalid")
    _external_lock_sha256(
        provenance["meshlab_only_file_sha256"],
        f"external lock {variable} MeshLab-only member SHA-256",
    )


def _validate_external_lock_v2_provenance(
    variable: str, entry: dict, provenance: object
) -> None:
    if not isinstance(provenance, dict):
        raise StageError(f"External lock {variable} lacks release provenance")
    kind = provenance.get("provenance_kind")
    if kind not in EXTERNAL_ARCHIVE_PROVENANCE_KINDS:
        raise StageError(f"External lock {variable} has an unsupported provenance kind")
    validators = {
        "github-release-asset": _validate_github_release_asset_provenance,
        "github-tag-source-archive": _validate_github_tag_provenance,
        "official-release-checksum": _validate_official_checksum_provenance,
        "official-project-file-release": _validate_official_project_file_provenance,
        "official-archive-byte-equivalence": _validate_official_mirror_provenance,
        "meshlab-historical-tag-archive": _validate_tinygltf_historical_provenance,
    }
    validator = validators[kind]
    if kind == "github-release-asset":
        validator(variable, entry, provenance, legacy=False)
    else:
        validator(variable, entry, provenance)


def _verify_declared_nonexecuted_archive_member(path: Path, entry: dict) -> None:
    provenance = entry.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("provenance_kind") != (
        "meshlab-historical-tag-archive"
    ):
        return
    relative = provenance["meshlab_only_paths"][0]
    expected_sha256 = provenance["meshlab_only_file_sha256"]
    try:
        with zipfile.ZipFile(path, "r") as package:
            matches = [
                item
                for item in package.infolist()
                if not item.is_dir()
                and (item.filename == relative or item.filename.endswith(f"/{relative}"))
            ]
            if len(matches) != 1:
                raise StageError(
                    "TinyGLTF historical archive does not contain one exact declared "
                    "non-executed member"
                )
            digest = hashlib.sha256()
            actual_size = 0
            with package.open(matches[0], "r") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
                    actual_size += len(block)
            if actual_size != matches[0].file_size or digest.hexdigest() != expected_sha256:
                raise StageError(
                    "TinyGLTF historical archive non-executed member does not match its lock"
                )
    except StageError:
        raise
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise StageError(
            f"Cannot verify TinyGLTF historical archive non-executed member: {exc}"
        ) from exc


def _verify_required_source_archive_members(path: Path, entry: dict) -> None:
    required = entry.get("required_source_members", [])
    if not required:
        return
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as package:
                present = {
                    member.filename
                    for member in package.infolist()
                    if not member.is_dir()
                }
        elif tarfile.is_tarfile(path):
            with tarfile.open(path, mode="r:*") as package:
                present = {
                    member.name
                    for member in package
                    if member.isfile()
                }
        else:
            raise StageError(
                f"Required-source member lock targets an unsupported archive: {path.name}"
            )
    except StageError:
        raise
    except (OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise StageError(
            f"Cannot verify required source members in {path.name}: {exc}"
        ) from exc
    missing = sorted(set(required) - present)
    if missing:
        raise StageError(
            f"External source archive {entry['variable']} lacks required source members: "
            f"{missing}"
        )


def _load_external_lock(
    path: Path | None,
    expected_commit: str,
    *,
    require_release_provenance: bool = False,
    expected_exclusions: dict[str, str] | None = None,
    payload: bytes | None = None,
) -> dict[str, dict]:
    if path is None and payload is None:
        return {}
    lock = (
        _json_load_bytes(payload, path.name if path is not None else "external archive lock")
        if payload is not None
        else _json_load(path)
    )
    schema_version = lock.get("schema_version")
    if schema_version not in (1, 2) or lock.get("meshlab_commit") != expected_commit:
        raise StageError("External archive lock schema or MeshLab commit does not match")
    if schema_version == 1:
        if require_release_provenance and lock.get("lock_status") != (
            EXTERNAL_ARCHIVE_LOCK_V1_STATUS
        ):
            raise StageError("Production external archive lock is not verified")
    else:
        _require_exact_keys(
            lock,
            {
                "schema_version",
                "lock_status",
                "meshlab_commit",
                "platform",
                "platform_exclusions",
                "archives",
            },
            "external archive lock v2",
        )
        if lock["lock_status"] != EXTERNAL_ARCHIVE_LOCK_V2_STATUS:
            raise StageError("Production external archive lock v2 is not verified")
        if lock["platform"] != "windows":
            raise StageError("External archive lock v2 targets the wrong platform")
        exclusions = lock["platform_exclusions"]
        if not isinstance(exclusions, dict) or not all(
            isinstance(name, str)
            and re.fullmatch(r"[A-Z][A-Z0-9_]*_LINK", name)
            and isinstance(reason, str)
            and reason
            for name, reason in exclusions.items()
        ):
            raise StageError("External archive lock v2 has invalid platform exclusions")
        if require_release_provenance and expected_exclusions is None:
            raise StageError("External archive lock v2 needs expected platform exclusions")
        if expected_exclusions is not None and exclusions != expected_exclusions:
            raise StageError("External archive lock v2 platform exclusions do not match")

    entries = lock.get("archives")
    if not isinstance(entries, list):
        raise StageError("External archive lock needs an archives array")
    result: dict[str, dict] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("variable"), str):
            raise StageError(f"Invalid external lock entry at index {index}")
        variable = entry["variable"]
        if variable in result:
            raise StageError(f"Duplicate external lock variable: {variable}")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*_LINK", variable):
            raise StageError(f"Invalid external lock variable: {variable}")
        _validate_https_url(entry.get("url"), f"external lock {variable} URL")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise StageError(f"External lock {variable} needs lowercase SHA-256")
        byte_size = entry.get("byte_size")
        if byte_size is not None and (
            isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size <= 0
        ):
            raise StageError(f"External lock {variable} has invalid byte_size")
        provenance = entry.get("provenance")
        if schema_version == 1 and require_release_provenance:
            if byte_size is None or not isinstance(provenance, dict):
                raise StageError(
                    f"External lock {variable} lacks official release provenance"
                )
            _validate_github_release_asset_provenance(
                variable, entry, provenance, legacy=True
            )
        elif schema_version == 2:
            required = {
                "variable",
                "url",
                "sha256",
                "byte_size",
                "upstream_md5",
                "cmake_path",
                "provenance",
            }
            allowed = required | {"fixture_file", "required_source_members"}
            actual = set(entry)
            if not required.issubset(actual) or not actual.issubset(allowed):
                raise StageError(
                    f"External lock {variable} fields do not match schema v2; "
                    f"missing={sorted(required - actual)}, unknown={sorted(actual - allowed)}"
                )
            upstream_md5 = entry["upstream_md5"]
            if upstream_md5 is not None and (
                not isinstance(upstream_md5, str) or not MD5_RE.fullmatch(upstream_md5)
            ):
                raise StageError(f"External lock {variable} has invalid upstream_md5")
            cmake_path = _safe_relative(
                entry["cmake_path"], f"external lock {variable} cmake_path"
            )
            if not cmake_path.startswith("src/external/") or not cmake_path.endswith(".cmake"):
                raise StageError(f"External lock {variable} has an invalid CMake source path")
            if byte_size is None:
                raise StageError(f"External lock {variable} v2 requires byte_size")
            required_source_members = entry.get("required_source_members", [])
            if not isinstance(required_source_members, list):
                raise StageError(
                    f"External lock {variable} required_source_members must be an array"
                )
            seen_required_source_members: set[str] = set()
            for member in required_source_members:
                canonical = _safe_relative(
                    member,
                    f"external lock {variable} required source member",
                )
                folded = canonical.casefold()
                if folded in seen_required_source_members:
                    raise StageError(
                        f"External lock {variable} repeats a required source member"
                    )
                seen_required_source_members.add(folded)
            _validate_external_lock_v2_provenance(variable, entry, provenance)
        fixture_file = entry.get("fixture_file")
        if fixture_file is not None:
            _safe_relative(fixture_file, f"external lock {variable} fixture_file")
            if schema_version == 2 and require_release_provenance:
                raise StageError(
                    f"Production external lock {variable} cannot use a fixture file"
                )
        result[variable] = entry
    return result


def _require_exact_keys(value: dict, expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise StageError(
            f"{label} fields do not match the schema; missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _require_exact_value(actual: object, expected: object, label: str) -> None:
    if type(actual) is not type(expected) or actual != expected:
        raise StageError(f"{label} differs from the controlled rebuild recipe")


def _safe_leaf(value: object, label: str) -> str:
    relative = _safe_relative(value, label)
    if len(PurePosixPath(relative).parts) != 1:
        raise StageError(f"{label} must be a file name without directories")
    return relative


def _verify_bound_file(specification: dict, path: Path, label: str) -> dict:
    _require_exact_keys(specification, {"filename", "sha256"}, label)
    filename = _safe_leaf(specification.get("filename"), f"{label}.filename")
    digest = specification.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise StageError(f"{label}.sha256 must be a lowercase SHA-256")
    if not path.is_file() or _is_link_like(path):
        raise StageError(f"{label} input is missing or linked")
    if path.name != filename:
        raise StageError(f"{label} filename does not match the rebuild lock")
    actual = _hash_file(path)
    if actual != digest:
        raise StageError(f"{label} SHA-256 does not match the rebuild lock")
    return {"filename": filename, "sha256": actual}


def _reject_private_absolute_paths(payload: bytes, label: str) -> None:
    if any(pattern.search(payload) for pattern in PRIVATE_PATH_PATTERNS):
        raise StageError(f"{label} contains a private absolute user path")


def _parse_dotnet_utc_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,7})?Z",
        value,
    ):
        raise StageError(f"{label} must be an exact UTC timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise StageError(f"{label} is not a valid UTC timestamp") from exc


def _validate_windows_executable_path(value: object, filename: str, label: str) -> None:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise StageError(f"{label} must be an absolute Windows executable path")
    path = PureWindowsPath(value)
    if (
        not path.is_absolute()
        or path.name.casefold() != filename.casefold()
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise StageError(f"{label} must be an absolute path to {filename}")
    _reject_private_absolute_paths(value.encode("utf-8"), label)


def _verify_pytetwild_audit_logs(
    directory: Path,
    specifications: object,
) -> tuple[dict[str, dict], list[tuple[Path, str]]]:
    _assert_plain_directory(directory, "PyTetWild audit-log directory")
    if not isinstance(specifications, dict):
        raise StageError("PyTetWild attestation audit_logs must be an object")
    _require_exact_keys(
        specifications,
        set(PYTETWILD_AUDIT_LOG_FILES),
        "PyTetWild attestation audit_logs",
    )
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise StageError(f"Cannot enumerate PyTetWild audit logs: {exc}") from exc
    actual_names = {entry.name for entry in entries}
    expected_names = set(PYTETWILD_AUDIT_LOG_FILES.values())
    if len(entries) != len(actual_names) or actual_names != expected_names:
        raise StageError(
            "PyTetWild audit-log directory must contain exactly the eight bound logs; "
            f"missing={sorted(expected_names - actual_names)}, "
            f"unknown={sorted(actual_names - expected_names)}"
        )

    evidence: dict[str, dict] = {}
    files: list[tuple[Path, str]] = []
    for key, expected_filename in PYTETWILD_AUDIT_LOG_FILES.items():
        specification = specifications[key]
        if not isinstance(specification, dict):
            raise StageError(f"PyTetWild audit log {key} evidence must be an object")
        _require_exact_keys(
            specification,
            {"filename", "sha256"},
            f"PyTetWild audit log {key} evidence",
        )
        if specification.get("filename") != expected_filename:
            raise StageError(f"PyTetWild audit log {key} has an unexpected filename")
        path = directory / expected_filename
        if not path.is_file() or _is_link_like(path):
            raise StageError(f"PyTetWild audit log {key} input is missing or linked")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise StageError(f"Cannot stat PyTetWild audit log {key}: {exc}") from exc
        if size <= 0 or size > PYTETWILD_MAX_AUDIT_LOG_BYTES:
            raise StageError(f"PyTetWild audit log {key} has an invalid byte size")
        item = _verify_bound_file(specification, path, f"PyTetWild audit log {key}")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise StageError(f"Cannot read PyTetWild audit log {key}: {exc}") from exc
        if (
            len(payload) != size
            or hashlib.sha256(payload).hexdigest() != item["sha256"]
        ):
            raise StageError(f"PyTetWild audit log {key} changed during verification")
        if payload.startswith(b"\xef\xbb\xbf"):
            raise StageError(f"PyTetWild audit log {key} must not contain a UTF-8 BOM")
        if b"\x00" in payload:
            raise StageError(f"PyTetWild audit log {key} contains a NUL byte")
        _reject_private_absolute_paths(payload, f"PyTetWild audit log {key}")
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise StageError(f"PyTetWild audit log {key} is not strict UTF-8") from exc
        exit_lines = [line for line in text.splitlines() if line.startswith("exit_code=")]
        if exit_lines != ["exit_code=0"]:
            raise StageError(f"PyTetWild audit log {key} lacks exact exit_code=0 evidence")
        evidence[key] = item
        files.append(
            (path, f"build-evidence/pytetwild/logs/{expected_filename}")
        )
    return evidence, files


def _verify_pytetwild_attestation_binding(
    path: Path,
    bound_evidence: dict[str, dict],
    wheel_specification: dict,
    wheel_evidence: dict,
    raw_wheel_path: Path,
    audit_log_directory: Path,
    expected_sources: dict[str, object],
    lock_environment: dict[str, str],
) -> tuple[dict, dict[str, dict], list[tuple[Path, str]]]:
    try:
        attestation_payload = path.read_bytes()
    except OSError as exc:
        raise StageError(f"Cannot read PyTetWild build attestation: {exc}") from exc
    if hashlib.sha256(attestation_payload).hexdigest() != bound_evidence[
        "attestation"
    ]["sha256"]:
        raise StageError("PyTetWild build attestation changed during verification")
    _reject_private_absolute_paths(
        attestation_payload,
        "PyTetWild build attestation",
    )
    attestation = _json_load_bytes(attestation_payload, path.name)
    _require_exact_keys(
        attestation,
        {
            "schema_version",
            "status",
            "scope",
            "started_utc",
            "finished_utc",
            "network_policy",
            "sources",
            "environment",
            "inputs",
            "output",
        },
        "PyTetWild build attestation",
    )
    for field, expected in {
        "schema_version": 1,
        "status": "verified-controlled-rebuild",
        "scope": "prospective-rebuild-only",
    }.items():
        _require_exact_value(
            attestation[field],
            expected,
            f"PyTetWild build attestation {field}",
        )
    started = _parse_dotnet_utc_timestamp(
        attestation["started_utc"],
        "PyTetWild build attestation started_utc",
    )
    finished = _parse_dotnet_utc_timestamp(
        attestation["finished_utc"],
        "PyTetWild build attestation finished_utc",
    )
    if finished < started:
        raise StageError("PyTetWild build attestation timestamps are out of order")

    network_policy = attestation["network_policy"]
    if not isinstance(network_policy, dict):
        raise StageError("PyTetWild build attestation network_policy must be an object")
    expected_network_policy = {
        "operator_confirmed_os_level_isolation": True,
        "os_level_enforcement_by_script": False,
        "script_enforcement_scope": "prebuild-probes-and-child-process-guards-only",
        "pip_no_index": True,
        "fetchcontent_fully_disconnected": True,
        "fetchcontent_try_find_package_mode": "NEVER",
        "git_https_rewritten_to_offline_invalid": True,
        "process_proxies_rejected_at_loopback_port_9": True,
        "prebuild_direct_connect_probes": "all-unreachable",
        "probe_targets": [
            "github.com:443",
            "pypi.org:443",
            "files.pythonhosted.org:443",
            "conda.anaconda.org:443",
        ],
    }
    _require_exact_keys(
        network_policy,
        set(expected_network_policy),
        "PyTetWild build attestation network_policy",
    )
    for field, expected in expected_network_policy.items():
        _require_exact_value(
            network_policy[field],
            expected,
            f"PyTetWild build attestation network_policy.{field}",
        )

    inputs = attestation.get("inputs")
    if not isinstance(inputs, dict):
        raise StageError("PyTetWild build attestation inputs must be an object")
    expected_inputs = {
        "build_recipe_sha256": bound_evidence["build_recipe"]["sha256"],
        "build_requirements_lock_sha256": bound_evidence["build_requirements_lock"][
            "sha256"
        ],
        "source_patch_sha256": bound_evidence["source_patch"]["sha256"],
        "python_installer_sha256": "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb",
        "portable_git_sha256": "5aa8a20f6e9abb2c755f0e73c91c687701a46b309ad84a0ca6509380fa4ae290",
        "visual_studio_bootstrapper_sha256": "236367b68ba9a51708263ab10a1c85546cc4a8eca78b365168811d19c4fb2f29",
        "visual_studio_catalog_sha256": "3891c3018a07338b3880cbb28088bb22ef7762eb9206523655b2e3972b9d527e",
        "visual_studio_channel_manifest_sha256": "4c81e902fb7fe2acea779b828e6dc548fe0bbb693df50eda0224263c16686bdd",
        "visual_studio_layout_sha256": "9707247b5e1c5ffdbd2ec97889db8e16ad97361840427a846e21f697c28ed494",
        "visual_studio_installer_opc_sha256": "e2c0a268ec9b678169ed5ff9c0162ea135d8868c27e7ac67a754b09d16841b71",
        "visual_studio_layout_file_count": 714,
        "visual_studio_layout_total_bytes": 2651377645,
        "visual_studio_layout_tree_sha256": "2b6a89bb69aa7de013fc055828258a3a91c7c333f0c6be831a750990922fed3a",
        "microsoft_visual_studio_layout_verifier_exit_code": 0,
    }
    _require_exact_keys(
        inputs,
        set(expected_inputs) | {"source_archives"},
        "PyTetWild build attestation inputs",
    )
    for field, expected in expected_inputs.items():
        _require_exact_value(
            inputs[field],
            expected,
            f"PyTetWild build attestation inputs.{field}",
        )
    source_archives = inputs["source_archives"]
    if not isinstance(source_archives, dict):
        raise StageError("PyTetWild build attestation source_archives must be an object")
    _require_exact_keys(
        source_archives,
        PYTETWILD_SOURCE_ARCHIVE_FIELDS,
        "PyTetWild build attestation source_archives",
    )
    for field, digest in source_archives.items():
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise StageError(
                f"PyTetWild build attestation source_archives.{field} is not SHA-256"
            )

    sources = attestation.get("sources")
    if not isinstance(sources, dict):
        raise StageError("PyTetWild build attestation sources must be an object")
    _require_exact_keys(
        sources,
        set(expected_sources),
        "PyTetWild build attestation sources",
    )
    for field, expected in expected_sources.items():
        _require_exact_value(
            sources[field],
            expected,
            f"PyTetWild build attestation sources.{field}",
        )

    environment = attestation.get("environment")
    if not isinstance(environment, dict):
        raise StageError("PyTetWild build attestation environment must be an object")
    _require_exact_keys(
        environment,
        PYTETWILD_ATTESTATION_ENVIRONMENT_FIELDS,
        "PyTetWild build attestation environment",
    )
    for field in PYTETWILD_LOCK_ENVIRONMENT_FIELDS:
        _require_exact_value(
            environment[field],
            lock_environment[field],
            f"PyTetWild build attestation environment.{field}",
        )
    _validate_windows_executable_path(
        environment["compiler_path"], "cl.exe", "PyTetWild compiler_path"
    )
    _validate_windows_executable_path(
        environment["linker_path"], "link.exe", "PyTetWild linker_path"
    )
    _validate_windows_executable_path(
        environment["signtool_path"], "signtool.exe", "PyTetWild signtool_path"
    )
    _require_exact_value(
        environment["compiler_file_version"],
        "19.44.35228.0",
        "PyTetWild build attestation environment.compiler_file_version",
    )
    _require_exact_value(
        environment["compiler_product_version"],
        "14.44.35228.0",
        "PyTetWild build attestation environment.compiler_product_version",
    )
    _require_exact_value(
        environment["linker_file_version"],
        "14.44.35228.0",
        "PyTetWild build attestation environment.linker_file_version",
    )
    _require_exact_value(
        environment["linker_product_version"],
        "14.44.35228.0",
        "PyTetWild build attestation environment.linker_product_version",
    )
    _require_exact_value(
        environment["cmake_cli"],
        f"cmake version {lock_environment['cmake_version']}",
        "PyTetWild build attestation environment.cmake_cli",
    )
    _require_exact_value(
        environment["ninja_cli"],
        "1.13.0.git.kitware.jobserver-pipe-1",
        "PyTetWild build attestation environment.ninja_cli",
    )

    output = attestation.get("output")
    if not isinstance(output, dict):
        raise StageError("PyTetWild build attestation output must be an object")
    expected_output = {
        "filename": wheel_evidence["filename"],
        "sha256": wheel_evidence["sha256"],
        "python_tag": wheel_specification["python_tag"],
        "abi_tag": wheel_specification["abi_tag"],
        "platform_tag": wheel_specification["platform_tag"],
        "zip_test": "passed",
        "raw_wheel_record": "passed",
        "repaired_wheel_record": "passed",
        "abi3audit_strict": "passed",
        "raw_delvewheel_show": "passed-no-not-found-markers",
        "repaired_native_dependency_closure": "passed",
        "repaired_delvewheel_metadata": "passed",
        "native_extension_load": "passed",
        "normal_isolated_package_import": "passed",
        "vendored_dll_load_order": "passed",
    }
    _require_exact_keys(
        output,
        set(expected_output)
        | {"raw_wheel_filename", "raw_wheel_sha256", "audit_logs"},
        "PyTetWild build attestation output",
    )
    for field, expected in expected_output.items():
        _require_exact_value(
            output[field],
            expected,
            f"PyTetWild build attestation output.{field}",
        )

    raw_specification = {
        "filename": _safe_leaf(
            output["raw_wheel_filename"],
            "PyTetWild build attestation output.raw_wheel_filename",
        ),
        "sha256": output["raw_wheel_sha256"],
    }
    raw_wheel_evidence = _verify_bound_file(
        raw_specification,
        raw_wheel_path,
        "raw wheel",
    )
    if raw_wheel_evidence["sha256"] == wheel_evidence["sha256"]:
        raise StageError("Raw and repaired PyTetWild wheels must be distinct artifacts")
    raw_wheel_specification = dict(
        raw_specification,
        python_tag=wheel_specification["python_tag"],
        abi_tag=wheel_specification["abi_tag"],
        platform_tag=wheel_specification["platform_tag"],
    )
    _verify_pytetwild_wheel(
        raw_wheel_path,
        raw_wheel_specification,
        require_repaired=False,
    )
    audit_log_evidence, audit_log_files = _verify_pytetwild_audit_logs(
        audit_log_directory,
        output["audit_logs"],
    )
    return raw_wheel_evidence, audit_log_evidence, audit_log_files


def _verify_project_file_binding(
    supplied_path: Path,
    expected_sha256: str,
    project_repository: Path,
    project_commit: str,
    repository_relative_path: str,
    label: str,
) -> None:
    committed = _git_file_at_exact_commit(
        project_repository,
        project_commit,
        repository_relative_path,
    )
    try:
        supplied = supplied_path.read_bytes()
    except OSError as exc:
        raise StageError(f"Cannot read {label}: {exc}") from exc
    committed_sha256 = hashlib.sha256(committed).hexdigest()
    if supplied != committed or committed_sha256 != expected_sha256:
        raise StageError(
            f"{label} does not byte-match the exact project commit"
        )


def _verify_release_input_project_binding(
    supplied_path: Path,
    project_repository: Path,
    project_commit: str,
    repository_relative_path: str,
    label: str,
) -> dict[str, object]:
    if not supplied_path.is_file() or _is_link_like(supplied_path):
        raise StageError(f"{label} is missing or linked")
    committed = _git_file_at_exact_commit(
        project_repository,
        project_commit,
        repository_relative_path,
    )
    try:
        supplied = supplied_path.read_bytes()
    except OSError as exc:
        raise StageError(f"Cannot read {label}: {exc}") from exc
    if supplied != committed:
        raise StageError(f"{label} does not byte-match the exact project commit")
    return {
        "payload": committed,
        "sha256": hashlib.sha256(committed).hexdigest(),
    }


def _verify_release_input_project_bindings(
    manifest_path: Path,
    project_repository: Path,
    project_commit: str,
    *,
    external_lock_argument: str | os.PathLike[str] | None = None,
    bind_external_lock: bool = True,
) -> tuple[dict, Path | None, dict[str, dict[str, object]]]:
    """Snapshot mutable release-control inputs from one exact project commit."""

    evidence = {}
    evidence["component_manifest"] = _verify_release_input_project_binding(
        manifest_path,
        project_repository,
        project_commit,
        COMPONENT_MANIFEST_PATH,
        "Component manifest",
    )
    manifest = _json_load_bytes(
        evidence["component_manifest"]["payload"],
        manifest_path.name,
    )

    policy = manifest.get("pytetwild_rebuild_policy")
    if policy is not None:
        relative_template = _safe_relative(
            policy.get("template"),
            "pytetwild_rebuild_policy.template",
        )
        lexical_template = manifest_path.parent.joinpath(
            *PurePosixPath(relative_template).parts
        )
        if _is_link_like(lexical_template):
            raise StageError("PyTetWild rebuild template is missing or linked")
        template_path = lexical_template.resolve()
        if not _is_relative_to(template_path, manifest_path.parent.resolve()):
            raise StageError("PyTetWild rebuild template escaped the manifest directory")
        evidence["pytetwild_rebuild_template"] = _verify_release_input_project_binding(
            template_path,
            project_repository,
            project_commit,
            PYTETWILD_REBUILD_TEMPLATE_PATH,
            "PyTetWild rebuild template",
        )

    external_lock_path = None
    if bind_external_lock and external_lock_argument:
        lexical_external_lock = Path(
            os.path.abspath(os.fspath(external_lock_argument))
        )
        if not lexical_external_lock.is_file() or _is_link_like(lexical_external_lock):
            raise StageError("External archive lock is missing or linked")
        external_lock_path = lexical_external_lock.resolve()
    elif bind_external_lock and manifest.get("default_external_archive_lock"):
        lexical_external_lock = manifest_path.parent.joinpath(
            *PurePosixPath(manifest["default_external_archive_lock"]).parts
        )
        if not lexical_external_lock.is_file() or _is_link_like(lexical_external_lock):
            raise StageError("External archive lock is missing or linked")
        external_lock_path = lexical_external_lock.resolve()
        if not _is_relative_to(external_lock_path, manifest_path.parent.resolve()):
            raise StageError("Default external archive lock escaped the manifest directory")
    if external_lock_path is not None:
        evidence["external_archive_lock"] = _verify_release_input_project_binding(
            external_lock_path,
            project_repository,
            project_commit,
            EXTERNAL_ARCHIVE_LOCK_PATH,
            "External archive lock",
        )
    return manifest, external_lock_path, evidence


def _hashed_python_requirements(
    path: Path,
    *,
    label: str,
    required_packages: set[str],
) -> dict[str, tuple[str, set[str]]]:
    try:
        physical_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise StageError(f"Cannot read {label}: {exc}") from exc
    logical_lines: list[str] = []
    pending = ""
    for physical in physical_lines:
        content = physical.split("#", 1)[0].strip()
        if not content:
            continue
        pending = f"{pending} {content}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical_lines.append(pending)
        pending = ""
    if pending:
        raise StageError(f"{label} ends in a continuation")
    result: dict[str, tuple[str, set[str]]] = {}
    for line in logical_lines:
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError as exc:
            raise StageError(f"Invalid {label} requirement: {exc}") from exc
        if not tokens:
            continue
        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+-]*)",
            tokens[0],
        )
        if match is None:
            raise StageError(
                f"{label} requirement is not an exact name==version pin: {tokens[0]}"
            )
        name = re.sub(r"[-_.]+", "-", match.group(1)).casefold()
        version = match.group(2)
        hash_tokens = [
            token.removeprefix("--hash=sha256:")
            for token in tokens[1:]
            if token.startswith("--hash=sha256:")
        ]
        hashes = set(hash_tokens)
        if not hashes or any(not SHA256_RE.fullmatch(item) for item in hashes):
            raise StageError(f"{label} requirement lacks valid SHA-256: {name}")
        if len(hash_tokens) != len(hashes):
            raise StageError(f"{label} requirement repeats a SHA-256: {name}")
        unexpected = [token for token in tokens[1:] if not token.startswith("--hash=sha256:")]
        if unexpected:
            raise StageError(f"Unsupported {label} requirement options: {unexpected}")
        if name in result:
            raise StageError(f"Duplicate {label} requirement: {name}")
        result[name] = (version, hashes)
    missing = sorted(required_packages - set(result))
    if missing:
        raise StageError(f"{label} requirements are incomplete: {missing}")
    return result


def _verify_application_requirements_lock(
    path: Path,
    repaired_wheel_sha256: str,
    historical_wheel_sha256: str,
) -> None:
    requirements = _hashed_python_requirements(
        path,
        label="Application requirements lock",
        required_packages={"pytetwild"},
    )
    version, hashes = requirements["pytetwild"]
    if historical_wheel_sha256 in hashes:
        raise StageError(
            "Application requirements lock still permits the historical PyTetWild wheel"
        )
    if version != "0.3.0":
        raise StageError("Application requirements lock must pin pytetwild==0.3.0")
    if hashes != {repaired_wheel_sha256}:
        raise StageError(
            "Application requirements lock must bind PyTetWild to exactly the repaired wheel"
        )
    duplicate_owners = sorted(
        name
        for name, (_other_version, other_hashes) in requirements.items()
        if name != "pytetwild" and repaired_wheel_sha256 in other_hashes
    )
    if duplicate_owners:
        raise StageError(
            "Application requirements lock assigns the repaired PyTetWild wheel hash "
            f"to other packages: {duplicate_owners}"
        )


def _verify_wheel_record(
    package: zipfile.ZipFile,
    record_name: str,
    file_names: list[str],
) -> None:
    archive_files = set(file_names)
    if len(archive_files) != len(file_names):
        raise StageError("PyTetWild wheel contains duplicate file entries")
    for name in file_names:
        parts = _archive_member_parts(name)
        if parts is None or "/".join(parts) != name:
            raise StageError(f"PyTetWild wheel contains a non-normal file path: {name!r}")

    entries: dict[str, tuple[str, str]] = {}
    folded_paths: set[str] = set()
    try:
        with package.open(record_name, "r") as raw_record, io.TextIOWrapper(
            raw_record,
            encoding="utf-8",
            errors="strict",
            newline="",
        ) as record_text:
            for row_number, row in enumerate(csv.reader(record_text, strict=True), start=1):
                if len(row) != 3:
                    raise StageError(
                        f"PyTetWild wheel RECORD row {row_number} must have exactly three fields"
                    )
                member_name, recorded_hash, recorded_size = row
                parts = _archive_member_parts(member_name)
                if parts is None or "/".join(parts) != member_name:
                    raise StageError(
                        f"PyTetWild wheel RECORD has a non-normal path: {member_name!r}"
                    )
                folded = member_name.casefold()
                if folded in folded_paths:
                    raise StageError(
                        f"PyTetWild wheel RECORD has a duplicate path: {member_name!r}"
                    )
                folded_paths.add(folded)
                entries[member_name] = (recorded_hash, recorded_size)
    except (
        UnicodeError,
        csv.Error,
        KeyError,
        RuntimeError,
        zipfile.BadZipFile,
        OSError,
    ) as exc:
        raise StageError(f"Cannot parse PyTetWild wheel RECORD: {exc}") from exc

    recorded_files = set(entries)
    unknown = sorted(recorded_files - archive_files)
    missing = sorted(archive_files - recorded_files)
    if unknown:
        raise StageError(f"PyTetWild wheel RECORD has unknown entries: {unknown}")
    if missing:
        raise StageError(f"PyTetWild wheel RECORD is missing entries: {missing}")

    for member_name in file_names:
        recorded_hash, recorded_size = entries[member_name]
        if member_name == record_name:
            if recorded_hash or recorded_size:
                raise StageError("PyTetWild wheel RECORD must leave its own hash and size empty")
            continue
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)", recorded_size):
            raise StageError(
                f"PyTetWild wheel RECORD has an invalid size for {member_name!r}"
            )
        expected_size = int(recorded_size)
        digest = hashlib.sha256()
        actual_size = 0
        try:
            with package.open(member_name, "r") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
                    actual_size += len(block)
        except (KeyError, RuntimeError, zipfile.BadZipFile, OSError) as exc:
            raise StageError(
                f"Cannot read PyTetWild wheel member {member_name!r}: {exc}"
            ) from exc
        if actual_size != package.getinfo(member_name).file_size or actual_size != expected_size:
            raise StageError(
                f"PyTetWild wheel RECORD size mismatch for {member_name!r}"
            )
        encoded = base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")
        if recorded_hash != f"sha256={encoded}":
            raise StageError(
                f"PyTetWild wheel RECORD SHA-256 mismatch for {member_name!r}"
            )


def _verify_pytetwild_wheel(
    path: Path,
    wheel_specification: dict,
    *,
    require_repaired: bool = True,
) -> None:
    _validate_archive_members(path)
    expected_tag = "-".join(
        wheel_specification[field]
        for field in ("python_tag", "abi_tag", "platform_tag")
    )
    with zipfile.ZipFile(path) as package:
        names = [item.filename for item in package.infolist() if not item.is_dir()]
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        wheel_names = [name for name in names if name.endswith(".dist-info/WHEEL")]
        record_names = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(metadata_names) != 1 or len(wheel_names) != 1 or len(record_names) != 1:
            raise StageError("PyTetWild wheel has incomplete or ambiguous dist-info metadata")
        roots = {name.rsplit("/", 1)[0] for name in (*metadata_names, *wheel_names, *record_names)}
        if len(roots) != 1:
            raise StageError("PyTetWild wheel dist-info files do not share one directory")
        dist_info_root = next(iter(roots))
        if dist_info_root != "pytetwild-0.3.0.dist-info":
            raise StageError("PyTetWild wheel has an unexpected dist-info directory")
        _verify_wheel_record(package, record_names[0], names)
        metadata = package.read(metadata_names[0]).decode("utf-8", errors="strict")
        wheel_metadata = package.read(wheel_names[0]).decode("utf-8", errors="strict")
        if not re.search(r"(?mi)^Name:\s*pytetwild\s*$", metadata) or not re.search(
            r"(?mi)^Version:\s*0\.3\.0\s*$", metadata
        ):
            raise StageError("PyTetWild wheel METADATA name/version does not match")
        if not re.search(rf"(?mi)^Tag:\s*{re.escape(expected_tag)}\s*$", wheel_metadata):
            raise StageError("PyTetWild wheel ABI/platform tag does not match")
        if not any(name.casefold().endswith(".pyd") for name in names):
            raise StageError("PyTetWild wheel lacks its compiled wrapper")
        delvewheel_metadata = [name for name in names if name.casefold().endswith(".dist-info/delvewheel")]
        expected_delvewheel_metadata = f"{dist_info_root}/DELVEWHEEL"
        if require_repaired and delvewheel_metadata != [expected_delvewheel_metadata]:
            raise StageError("Repaired PyTetWild wheel lacks exact DELVEWHEEL metadata")
        if not require_repaired and delvewheel_metadata:
            raise StageError("Raw PyTetWild wheel unexpectedly contains DELVEWHEEL metadata")
        has_mpir_runtime = any(
            name.casefold().startswith("pytetwild.libs/")
            and Path(name).name.casefold().startswith("mpir-")
            and name.casefold().endswith(".dll")
            for name in names
        )
        if require_repaired and not has_mpir_runtime:
            raise StageError("PyTetWild wheel lacks its repaired MPIR runtime DLL")


def _validate_blocked_rebuild_template_data(
    template: dict,
    expected_commit: str,
) -> None:
    if (
        template.get("schema_version") != 1
        or template.get("lock_status") != "blocked-template-do-not-use"
        or template.get("pytetwild", {}).get("commit") != expected_commit
    ):
        raise StageError("PyTetWild rebuild template schema or source commit has drifted")
    nanobind = template.get("nanobind")
    wheel = template.get("wheel")
    if not isinstance(nanobind, dict) or not isinstance(wheel, dict):
        raise StageError("PyTetWild rebuild template is incomplete")
    if nanobind.get("version") is not None or nanobind.get("commit") is not None:
        raise StageError("Blocked PyTetWild rebuild template must not guess nanobind")
    if wheel.get("filename") is not None or wheel.get("sha256") is not None:
        raise StageError("Blocked PyTetWild rebuild template must not claim a result wheel")


def _validate_blocked_rebuild_template(path: Path, expected_commit: str) -> None:
    _validate_blocked_rebuild_template_data(_json_load(path), expected_commit)


def _prepare_pytetwild_rebuild(
    manifest: dict,
    manifest_path: Path,
    args: argparse.Namespace,
    *,
    project_repository: Path,
    project_commit: str,
    rebuild_template_payload: bytes | None = None,
) -> tuple[dict | None, dict | None, list[tuple[Path, str, str]]]:
    policy = manifest.get("pytetwild_rebuild_policy")
    if policy is None:
        return None, None, []
    expected = next(
        item for item in manifest["components"] if item["id"] == policy["component"]
    )
    template_path = manifest_path.parent.joinpath(
        *PurePosixPath(policy["template"]).parts
    ).resolve()
    if not _is_relative_to(template_path, manifest_path.parent.resolve()):
        raise StageError("PyTetWild rebuild template escaped the manifest directory")
    if not template_path.is_file() or template_path.is_symlink():
        raise StageError("PyTetWild rebuild template is missing or linked")
    if rebuild_template_payload is None:
        _validate_blocked_rebuild_template(template_path, expected["commit"])
    else:
        _validate_blocked_rebuild_template_data(
            _json_load_bytes(rebuild_template_payload, template_path.name),
            expected["commit"],
        )

    lock_argument = getattr(args, "pytetwild_rebuild_lock", None)
    if not lock_argument:
        if policy.get("required_for_staging"):
            raise StageError(
                "PyTetWild nanobind provenance is historically unknowable. A controlled "
                "rebuild is required; copy pytetwild_rebuild_lock.template.json, rebuild "
                "with exact hashed inputs, and pass --pytetwild-rebuild-lock plus all "
                "bound evidence files."
            )
        return None, None, []

    required_arguments = {
        "pytetwild_wheel": "--pytetwild-wheel",
        "pytetwild_raw_wheel": "--pytetwild-raw-wheel",
        "pytetwild_audit_logs": "--pytetwild-audit-logs",
        "pytetwild_build_recipe": "--pytetwild-build-recipe",
        "pytetwild_build_requirements": "--pytetwild-build-requirements",
        "pytetwild_source_patch": "--pytetwild-source-patch",
        "pytetwild_build_attestation": "--pytetwild-build-attestation",
        "application_requirements_lock": "--application-requirements-lock",
    }
    missing_arguments = [
        option for attribute, option in required_arguments.items() if not getattr(args, attribute, None)
    ]
    if missing_arguments:
        raise StageError(
            f"Verified PyTetWild rebuild lock also requires: {', '.join(missing_arguments)}"
        )
    lock_path = Path(os.path.abspath(os.fspath(lock_argument)))
    if not lock_path.is_file() or _is_link_like(lock_path):
        raise StageError("PyTetWild rebuild lock is missing or linked")
    try:
        lock_payload = lock_path.read_bytes()
    except OSError as exc:
        raise StageError(f"Cannot read PyTetWild rebuild lock: {exc}") from exc
    lock_sha256 = hashlib.sha256(lock_payload).hexdigest()
    lock = _json_load_bytes(lock_payload, lock_path.name)
    expected_top = {
        "schema_version",
        "lock_status",
        "scope",
        "historical_wheel",
        "pytetwild",
        "ftetwild",
        "wheel",
        "nanobind",
        "build_recipe",
        "build_requirements_lock",
        "source_patch",
        "environment",
        "attestation",
        "release_binding",
    }
    _require_exact_keys(lock, expected_top, "PyTetWild rebuild lock")
    if (
        lock["schema_version"] != 1
        or lock["lock_status"] != "verified-controlled-rebuild"
        or lock["scope"] != "prospective-rebuild-only"
    ):
        raise StageError("PyTetWild rebuild lock is not a verified prospective rebuild")
    _require_exact_keys(
        lock["historical_wheel"],
        {"sha256", "nanobind_version_status", "release_disposition"},
        "historical_wheel",
    )
    if (
        lock["historical_wheel"]["sha256"]
        != "11964e295a54cf9e2f6920a920aeeba27668c9b14e369a86f72ec5baa4f46060"
        or lock["historical_wheel"]["nanobind_version_status"]
        != "unknown-not-asserted"
        or lock["historical_wheel"]["release_disposition"] != "excluded"
    ):
        raise StageError("PyTetWild historical-wheel boundary is invalid")
    _require_exact_keys(lock["pytetwild"], {"version", "commit"}, "pytetwild")
    if lock["pytetwild"] != {"version": "0.3.0", "commit": expected["commit"]}:
        raise StageError("PyTetWild rebuild source does not match the manifest")
    _require_exact_keys(lock["ftetwild"], {"commit"}, "ftetwild")
    if lock["ftetwild"]["commit"] != "d7d99bb4387a07895b9adce058dc7305f6b6e5ab":
        raise StageError("PyTetWild rebuild fTetWild commit does not match")

    wheel = lock["wheel"]
    _require_exact_keys(
        wheel,
        {"filename", "sha256", "python_tag", "abi_tag", "platform_tag"},
        "wheel",
    )
    for field, expected_value in {
        "python_tag": "cp312",
        "abi_tag": "abi3",
        "platform_tag": "win_amd64",
    }.items():
        if wheel[field] != expected_value:
            raise StageError(f"PyTetWild wheel {field} must be {expected_value}")
    wheel_path = Path(os.path.abspath(os.fspath(args.pytetwild_wheel)))
    wheel_evidence = _verify_bound_file(
        {"filename": wheel["filename"], "sha256": wheel["sha256"]},
        wheel_path,
        "wheel",
    )
    if wheel_evidence["sha256"] == lock["historical_wheel"]["sha256"]:
        raise StageError("Controlled rebuild must not reuse the provenance-unknown wheel")
    _verify_pytetwild_wheel(wheel_path, wheel, require_repaired=True)

    nanobind = lock["nanobind"]
    _require_exact_keys(
        nanobind,
        {"version", "source_url", "commit", "required_paths"},
        "nanobind",
    )
    version = nanobind["version"]
    if not isinstance(version, str) or not EXACT_VERSION_RE.fullmatch(version):
        raise StageError("nanobind version must be exact, not a range or placeholder")
    _validate_https_url(nanobind["source_url"], "nanobind.source_url")
    if not isinstance(nanobind["commit"], str) or not SHA1_RE.fullmatch(nanobind["commit"]):
        raise StageError("nanobind.commit must be a full lowercase commit")
    if version != "2.12.0" or nanobind["commit"] != (
        "2a61ad2494d09fecb2e13322c1383342c299900d"
    ):
        raise StageError("nanobind version/commit differs from the controlled recipe")
    if not isinstance(nanobind["required_paths"], list) or not nanobind["required_paths"]:
        raise StageError("nanobind.required_paths must be a non-empty array")
    for relative in nanobind["required_paths"]:
        _safe_relative(relative, "nanobind required path")

    bound_inputs = {
        "build_recipe": Path(os.path.abspath(os.fspath(args.pytetwild_build_recipe))),
        "build_requirements_lock": Path(
            os.path.abspath(os.fspath(args.pytetwild_build_requirements))
        ),
        "source_patch": Path(os.path.abspath(os.fspath(args.pytetwild_source_patch))),
        "attestation": Path(
            os.path.abspath(os.fspath(args.pytetwild_build_attestation))
        ),
        "release_binding": Path(
            os.path.abspath(os.fspath(args.application_requirements_lock))
        ),
    }
    bound_evidence = {
        key: _verify_bound_file(lock[key], path, key)
        for key, path in bound_inputs.items()
    }
    project_bindings = {
        "build_recipe": (PYTETWILD_BUILD_RECIPE_PATH, "PyTetWild build recipe"),
        "build_requirements_lock": (
            PYTETWILD_BUILD_REQUIREMENTS_PATH,
            "PyTetWild build requirements lock",
        ),
        "source_patch": (PYTETWILD_SOURCE_PATCH_PATH, "PyTetWild source patch"),
        "release_binding": (
            APPLICATION_REQUIREMENTS_LOCK_PATH,
            "Application requirements lock",
        ),
    }
    for key, (repository_relative_path, label) in project_bindings.items():
        _verify_project_file_binding(
            bound_inputs[key],
            bound_evidence[key]["sha256"],
            project_repository,
            project_commit,
            repository_relative_path,
            label,
        )
    requirements = _hashed_python_requirements(
        bound_inputs["build_requirements_lock"],
        label="PyTetWild build requirements lock",
        required_packages={
            "abi3audit",
            "build",
            "cibuildwheel",
            "cmake",
            "delvewheel",
            "nanobind",
            "ninja",
            "numpy",
            "scikit-build-core",
        },
    )
    if requirements["nanobind"][0] != version:
        raise StageError("nanobind version differs between rebuild lock and hashed requirements")
    environment = lock["environment"]
    if not isinstance(environment, dict):
        raise StageError("PyTetWild rebuild environment must be an object")
    _require_exact_keys(
        environment,
        PYTETWILD_LOCK_ENVIRONMENT_FIELDS,
        "environment",
    )
    expected_environment = {
        "python_version": "3.12.10",
        "pip_version": "25.0.1",
        "cibuildwheel_version": requirements["cibuildwheel"][0],
        "runner_image": "self-hosted-windows-controlled-offline",
        "compiler": "MSVC 14.44.35207",
        "compiler_family_requested_from_vsdevcmd": "14.44",
        "visual_studio_installation_version": "17.14.37614.0",
        "cmake_version": requirements["cmake"][0],
        "ninja_version": requirements["ninja"][0],
        "nanobind_version": requirements["nanobind"][0],
        "build_version": requirements["build"][0],
        "scikit_build_core_version": requirements["scikit-build-core"][0],
        "delvewheel_version": requirements["delvewheel"][0],
        "abi3audit_version": requirements["abi3audit"][0],
        "numpy_version": requirements["numpy"][0],
        "windows_sdk_version": "10.0.26100.0",
        "windows_sdk_servicing_version": "10.0.26100.7705",
    }
    for field, expected_value in expected_environment.items():
        _require_exact_value(
            environment[field],
            expected_value,
            f"PyTetWild rebuild environment.{field}",
        )

    expected_sources = {
        "pytetwild_commit": expected["commit"],
        "pytetwild_optional_pyvista_patch_sha256": bound_evidence["source_patch"][
            "sha256"
        ],
        "pytetwild_patched_accessor_sha256": "c1bfeb0417cd3109d0ef3ecde6e69e04573571f5050003d330a04c25a5d1030c",
        "ftetwild_commit": lock["ftetwild"]["commit"],
        "nanobind_commit": nanobind["commit"],
        "fmt_commit": "40626af88bd7df9a5fb80be7b25ac85b122d6c21",
        "spdlog_commit": "6fa36017cfd5731d617e1a934f0e5ea9c4445b13",
        "libigl_commit": "40e7900ccbd767f1f360e0eb10f0f1a6432e0993",
        "predicates_commit": "decb7bc1260e689cbe008109e3cc5d3a5a433aea",
        "geogram_commit": "fc3eb9bf44d2ee29686592e3ef5f5f4daeda27f8",
        "geogram_amgcl_commit": "ab57038d68ee372ed5df280631051b91f17ed2d1",
        "geogram_libmeshb_commit": "952a157c9d516b28cc6c69cd1550c3e48d4792f9",
        "geogram_rply_commit": "4296cc91b5c8c26d4e7d7aac0cee2b194ffc5800",
        "onetbb_commit": "06ce6212da6710f4bb2d20a1904b018aa44069bf",
        "json_commit": "0901d33bf6e7dfe6f70fd9d142c8f5c6695c6c5b",
        "eigen_archive_sha256": "8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72",
        "mpir_archive_sha256": "c7243b2c3f8e849a9367eab8d77babcd8dd5b828d6b5068441297edc86843b69",
    }
    raw_wheel_path = Path(os.path.abspath(os.fspath(args.pytetwild_raw_wheel)))
    audit_log_directory = Path(
        os.path.abspath(os.fspath(args.pytetwild_audit_logs))
    )
    raw_wheel_evidence, audit_log_evidence, audit_log_files = (
        _verify_pytetwild_attestation_binding(
            bound_inputs["attestation"],
            bound_evidence,
            wheel,
            wheel_evidence,
            raw_wheel_path,
            audit_log_directory,
            expected_sources,
            environment,
        )
    )

    _verify_application_requirements_lock(
        bound_inputs["release_binding"],
        wheel_evidence["sha256"],
        lock["historical_wheel"]["sha256"],
    )

    component = {
        "id": "pytetwild-nanobind-rebuild",
        "display_name": f"nanobind {version} used by controlled PyTetWild rebuild",
        "version": version,
        "kind": "git",
        "url": nanobind["source_url"],
        "commit": nanobind["commit"],
        "destination": policy["nanobind_destination"],
        "required_paths": nanobind["required_paths"],
        "required_gitlinks": [
            dict(expectation) for expectation in policy["nanobind_required_gitlinks"]
        ],
    }
    evidence = {
        "id": policy["known_gap_id"],
        "resolution": "verified-controlled-rebuild",
        "rebuild_lock_sha256": lock_sha256,
        "historical_wheel": lock["historical_wheel"],
        "wheel": wheel_evidence,
        "raw_wheel": raw_wheel_evidence,
        "nanobind": {
            "version": version,
            "source_url": nanobind["source_url"],
            "commit": nanobind["commit"],
        },
        "environment": environment,
        "bound_evidence": bound_evidence,
        "audit_logs": audit_log_evidence,
    }
    audit_log_hashes = {
        item["filename"]: item["sha256"] for item in audit_log_evidence.values()
    }
    files = [
        (
            lock_path,
            "build-evidence/pytetwild/pytetwild_rebuild.lock.json",
            lock_sha256,
        ),
        (
            raw_wheel_path,
            f"build-evidence/pytetwild/raw-wheel/{raw_wheel_evidence['filename']}",
            raw_wheel_evidence["sha256"],
        ),
        (
            wheel_path,
            f"build-evidence/pytetwild/repaired-wheel/{wheel_evidence['filename']}",
            wheel_evidence["sha256"],
        ),
        (
            bound_inputs["build_recipe"],
            f"build-evidence/pytetwild/{bound_evidence['build_recipe']['filename']}",
            bound_evidence["build_recipe"]["sha256"],
        ),
        (
            bound_inputs["build_requirements_lock"],
            "build-evidence/pytetwild/"
            f"{bound_evidence['build_requirements_lock']['filename']}",
            bound_evidence["build_requirements_lock"]["sha256"],
        ),
        (
            bound_inputs["source_patch"],
            f"build-evidence/pytetwild/{bound_evidence['source_patch']['filename']}",
            bound_evidence["source_patch"]["sha256"],
        ),
        (
            bound_inputs["attestation"],
            f"build-evidence/pytetwild/{bound_evidence['attestation']['filename']}",
            bound_evidence["attestation"]["sha256"],
        ),
        *[
            (source, relative, audit_log_hashes[source.name])
            for source, relative in audit_log_files
        ],
    ]
    return component, evidence, files


def _evaluate_release_state(
    manifest: dict,
    verified_evidence: list[dict],
) -> tuple[str, list[dict], list[dict]]:
    """Return output status, unresolved gaps, and validated resolution evidence."""

    known_gaps = manifest.get("known_gaps", [])
    gaps_by_id = {gap["id"]: gap for gap in known_gaps}
    evidence_by_id: dict[str, dict] = {}
    for index, evidence in enumerate(verified_evidence):
        if not isinstance(evidence, dict):
            raise StageError(f"Resolution evidence {index} must be an object")
        gap_id = _safe_id(evidence.get("id"), f"resolution evidence {index} id")
        if gap_id not in gaps_by_id:
            raise StageError(f"Resolution evidence targets an undeclared gap: {gap_id}")
        if gap_id in evidence_by_id:
            raise StageError(f"Duplicate resolution evidence for gap: {gap_id}")
        resolver = gaps_by_id[gap_id].get("resolution_evidence")
        if not isinstance(resolver, dict):
            raise StageError(f"Gap {gap_id} has no bound resolution evidence path")
        if resolver["kind"] == PYTETWILD_REBUILD_RESOLVER:
            _require_exact_keys(
                evidence,
                {
                    "id",
                    "resolution",
                    "rebuild_lock_sha256",
                    "historical_wheel",
                    "wheel",
                    "raw_wheel",
                    "nanobind",
                    "environment",
                    "bound_evidence",
                    "audit_logs",
                },
                f"PyTetWild gap {gap_id} evidence",
            )
            if evidence.get("resolution") != "verified-controlled-rebuild":
                raise StageError(f"PyTetWild gap {gap_id} lacks controlled-rebuild evidence")
            for field in ("rebuild_lock_sha256",):
                if not isinstance(evidence.get(field), str) or not SHA256_RE.fullmatch(
                    evidence[field]
                ):
                    raise StageError(f"PyTetWild gap {gap_id} has invalid {field}")
            historical = evidence.get("historical_wheel")
            wheel = evidence.get("wheel")
            raw_wheel = evidence.get("raw_wheel")
            nanobind = evidence.get("nanobind")
            environment = evidence.get("environment")
            bound_evidence = evidence.get("bound_evidence")
            audit_logs = evidence.get("audit_logs")
            if not all(
                isinstance(value, dict)
                for value in (
                    historical,
                    wheel,
                    raw_wheel,
                    nanobind,
                    environment,
                    bound_evidence,
                    audit_logs,
                )
            ):
                raise StageError(f"PyTetWild gap {gap_id} has incomplete rebuild evidence")
            _require_exact_keys(
                historical,
                {"sha256", "nanobind_version_status", "release_disposition"},
                f"PyTetWild gap {gap_id} historical wheel evidence",
            )
            if (
                historical["sha256"]
                != "11964e295a54cf9e2f6920a920aeeba27668c9b14e369a86f72ec5baa4f46060"
                or historical["nanobind_version_status"] != "unknown-not-asserted"
                or historical["release_disposition"] != "excluded"
            ):
                raise StageError(f"PyTetWild gap {gap_id} has invalid historical evidence")
            for label, specification in (
                ("wheel", wheel),
                ("raw_wheel", raw_wheel),
            ):
                _require_exact_keys(
                    specification,
                    {"filename", "sha256"},
                    f"PyTetWild gap {gap_id} {label} evidence",
                )
                _safe_leaf(
                    specification.get("filename"),
                    f"PyTetWild gap {gap_id} {label} filename",
                )
            historical_hash = historical.get("sha256")
            wheel_hash = wheel.get("sha256")
            raw_wheel_hash = raw_wheel.get("sha256")
            if (
                not isinstance(historical_hash, str)
                or not SHA256_RE.fullmatch(historical_hash)
                or not isinstance(wheel_hash, str)
                or not SHA256_RE.fullmatch(wheel_hash)
                or not isinstance(raw_wheel_hash, str)
                or not SHA256_RE.fullmatch(raw_wheel_hash)
                or wheel_hash == historical_hash
                or raw_wheel_hash in {historical_hash, wheel_hash}
            ):
                raise StageError(f"PyTetWild gap {gap_id} does not bind distinct new wheels")
            _require_exact_keys(
                nanobind,
                {"version", "source_url", "commit"},
                f"PyTetWild gap {gap_id} nanobind evidence",
            )
            if (
                nanobind.get("version") != "2.12.0"
                or nanobind.get("commit")
                != "2a61ad2494d09fecb2e13322c1383342c299900d"
                or nanobind.get("source_url")
                != "https://github.com/wjakob/nanobind.git"
            ):
                raise StageError(f"PyTetWild gap {gap_id} lacks exact build provenance")
            _validate_https_url(
                nanobind.get("source_url"),
                f"PyTetWild gap {gap_id} nanobind source_url",
            )
            _require_exact_keys(
                environment,
                PYTETWILD_LOCK_ENVIRONMENT_FIELDS,
                f"PyTetWild gap {gap_id} environment evidence",
            )
            if any(
                not isinstance(value, str) or not value.strip()
                for value in environment.values()
            ):
                raise StageError(f"PyTetWild gap {gap_id} has inexact environment evidence")
            expected_environment = {
                "python_version": "3.12.10",
                "pip_version": "25.0.1",
                "cibuildwheel_version": "3.3.1",
                "runner_image": "self-hosted-windows-controlled-offline",
                "compiler": "MSVC 14.44.35207",
                "compiler_family_requested_from_vsdevcmd": "14.44",
                "visual_studio_installation_version": "17.14.37614.0",
                "cmake_version": "3.29.6",
                "ninja_version": "1.13.0",
                "nanobind_version": "2.12.0",
                "build_version": "1.5.0",
                "scikit_build_core_version": "0.12.2",
                "delvewheel_version": "1.12.1",
                "abi3audit_version": "0.0.26",
                "numpy_version": "2.5.1",
                "windows_sdk_version": "10.0.26100.0",
                "windows_sdk_servicing_version": "10.0.26100.7705",
            }
            for field, expected_value in expected_environment.items():
                _require_exact_value(
                    environment[field],
                    expected_value,
                    f"PyTetWild gap {gap_id} environment.{field}",
                )
            required_bound_evidence = {
                "build_recipe",
                "build_requirements_lock",
                "source_patch",
                "attestation",
                "release_binding",
            }
            if set(bound_evidence) != required_bound_evidence:
                raise StageError(
                    f"PyTetWild gap {gap_id} lacks complete bound build evidence"
                )
            for field in sorted(required_bound_evidence):
                specification = bound_evidence[field]
                if not isinstance(specification, dict):
                    raise StageError(
                        f"PyTetWild gap {gap_id} has invalid {field} evidence"
                    )
                _require_exact_keys(
                    specification,
                    {"filename", "sha256"},
                    f"PyTetWild gap {gap_id} {field} evidence",
                )
                _safe_leaf(
                    specification.get("filename"),
                    f"PyTetWild gap {gap_id} {field} evidence filename",
                )
                if not isinstance(specification.get("sha256"), str) or not SHA256_RE.fullmatch(
                    specification["sha256"]
                ):
                    raise StageError(
                        f"PyTetWild gap {gap_id} has invalid {field} evidence SHA-256"
                    )
            _require_exact_keys(
                audit_logs,
                set(PYTETWILD_AUDIT_LOG_FILES),
                f"PyTetWild gap {gap_id} audit log evidence",
            )
            for field, expected_filename in PYTETWILD_AUDIT_LOG_FILES.items():
                specification = audit_logs[field]
                if not isinstance(specification, dict):
                    raise StageError(
                        f"PyTetWild gap {gap_id} has invalid {field} audit evidence"
                    )
                _require_exact_keys(
                    specification,
                    {"filename", "sha256"},
                    f"PyTetWild gap {gap_id} {field} audit evidence",
                )
                if specification.get("filename") != expected_filename:
                    raise StageError(
                        f"PyTetWild gap {gap_id} {field} audit filename is invalid"
                    )
                if not isinstance(specification.get("sha256"), str) or not SHA256_RE.fullmatch(
                    specification["sha256"]
                ):
                    raise StageError(
                        f"PyTetWild gap {gap_id} {field} audit SHA-256 is invalid"
                    )
        elif resolver["kind"] == DYNAMIC_ARCHIVE_LOCK_RESOLVER:
            variables = evidence.get("locked_variables")
            if (
                evidence.get("resolution") != DYNAMIC_ARCHIVE_LOCK_RESOLUTION
                or evidence.get("rule_id") != resolver["rule_id"]
                or not isinstance(evidence.get("external_archive_lock_sha256"), str)
                or not SHA256_RE.fullmatch(evidence["external_archive_lock_sha256"])
                or not isinstance(variables, list)
                or not variables
                or not all(isinstance(value, str) and value for value in variables)
                or variables != sorted(set(variables))
                or evidence.get("archive_count") != len(variables)
            ):
                raise StageError(f"Dynamic archive gap {gap_id} lacks a complete SHA-256 lock")
        else:  # validate_component_manifest rejects unknown resolver kinds.
            raise StageError(f"Gap {gap_id} has an unsupported resolver")
        evidence_by_id[gap_id] = evidence

    unresolved = [gap for gap in known_gaps if gap["id"] not in evidence_by_id]
    resolved = [evidence_by_id[gap["id"]] for gap in known_gaps if gap["id"] in evidence_by_id]
    status = CANDIDATE_BUNDLE_STATUS
    if manifest.get("release_approval") is not None and known_gaps and not unresolved:
        status = RELEASE_APPROVED_BUNDLE_STATUS
    return status, unresolved, resolved


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _scan_private_paths(project_root: Path) -> None:
    for path in sorted(project_root.rglob("*")):
        if path.is_symlink():
            raise StageError(f"Project source contains a link: {path.relative_to(project_root)}")
        if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
            continue
        payload = path.read_bytes()
        if b"\x00" in payload[:4096]:
            continue
        if any(pattern.search(payload) for pattern in PRIVATE_PATH_PATTERNS):
            raise StageError(
                f"Project source contains a private absolute user path: "
                f"{path.relative_to(project_root).as_posix()}"
            )


class _Stager:
    def __init__(
        self,
        manifest: dict,
        components: dict[str, dict],
        stage_root: Path,
        cache_root: Path,
        project_repository: Path,
        project_commit: str,
        *,
        external_lock_path: Path | None,
        external_lock_payload: bytes | None,
        external_lock_sha256: str | None,
        offline: bool,
        fixture_root: Path | None,
    ) -> None:
        self.manifest = manifest
        self.components = components
        self.stage_root = stage_root
        self.cache_root = cache_root
        self.project_repository = project_repository
        self.project_commit = project_commit
        self.external_lock_path = external_lock_path
        self.external_lock_payload = external_lock_payload
        self.external_lock_sha256 = external_lock_sha256
        self.offline = offline
        self.fixture_root = fixture_root
        self.records: list[dict] = []
        self.resolved_constraints: list[dict] = []
        self._staged_components: set[str] = set()
        self._relations = {
            (item["parent"], item["path"]): item["child"]
            for item in manifest.get("submodule_relations", [])
        }
        self._child_components = {item["child"] for item in manifest.get("submodule_relations", [])}
        self._dynamic_release_gap_ids = {
            gap["resolution_evidence"]["rule_id"]: gap["id"]
            for gap in manifest.get("known_gaps", [])
            if isinstance(gap.get("resolution_evidence"), dict)
            and gap["resolution_evidence"].get("kind") == DYNAMIC_ARCHIVE_LOCK_RESOLVER
        }
        self.allowed_suffixes = tuple(manifest["allowed_redirect_host_suffixes"])

    def _fixture_repository(self, component: dict) -> Path | None:
        if self.fixture_root is None:
            return None
        relative = component.get("fixture_repository")
        if relative is None:
            relative = f"git/{component['id']}"
        relative = _safe_relative(relative, f"fixture repository for {component['id']}")
        candidate = self.fixture_root.joinpath(*PurePosixPath(relative).parts)
        _assert_plain_directory(candidate, "Fixture git repository")
        return candidate

    def _stage_git_component(
        self,
        component: dict,
        *,
        parent_id: str | None = None,
        submodule_path: str | None = None,
        implicit: bool = False,
    ) -> None:
        component_id = component["id"]
        if component_id in self._staged_components:
            return
        repository = _cache_git_repository(
            component_id,
            component["url"],
            component["commit"],
            self.cache_root,
            offline=self.offline,
            fixture_repository=self._fixture_repository(component),
        )
        destination = self.stage_root.joinpath(*PurePosixPath(component["destination"]).parts)
        if destination.exists():
            if (
                parent_id is not None
                and destination.is_dir()
                and not destination.is_symlink()
                and not any(destination.iterdir())
            ):
                # git archive materializes a gitlink as an empty directory.
                # Remove only that verified empty placeholder before exporting
                # the exact child commit into the same path.
                destination.rmdir()
            else:
                raise StageError(f"Refusing to overwrite staged component: {component_id}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        _export_git_tree(repository, component["commit"], destination)
        _verify_required_paths(component, destination)
        self._staged_components.add(component_id)
        record = {
            "commit": component["commit"],
            "destination": component["destination"],
            "display_name": component.get("display_name", component_id),
            "id": component_id,
            "kind": "git",
            "source_url": component["url"],
            "version": component.get("version", component["commit"]),
        }
        if implicit:
            record["discovery"] = {
                "parent_component": parent_id,
                "submodule_path": submodule_path,
            }
        self.records.append(record)

        gitlinks = _list_gitlinks(repository, component["commit"])
        modules = _gitmodules(repository, component["commit"])
        if set(gitlinks) != set(modules):
            missing_urls = sorted(set(gitlinks) - set(modules))
            stale_modules = sorted(set(modules) - set(gitlinks))
            if missing_urls:
                raise StageError(
                    f"Gitlinks lack .gitmodules URLs in {component_id}: {missing_urls}"
                )
            # Stale .gitmodules entries are recorded source text but are not gitlinks.
            modules = {path: url for path, url in modules.items() if path in gitlinks}
        _verify_required_gitlinks(component, gitlinks, modules)
        for path, commit in sorted(gitlinks.items()):
            explicit_child_id = self._relations.get((component_id, path))
            resolved_url = _resolve_submodule_url(component["url"], modules[path])
            if explicit_child_id is not None:
                child = self.components[explicit_child_id]
                if child["commit"] != commit:
                    raise StageError(
                        f"Submodule commit drift for {component_id}:{path}; "
                        f"tree has {commit}, manifest has {child['commit']}"
                    )
                if _canonical_git_url(child["url"]) != _canonical_git_url(resolved_url):
                    raise StageError(f"Submodule URL drift for {component_id}:{path}")
                self._stage_git_component(
                    child,
                    parent_id=component_id,
                    submodule_path=path,
                )
                continue
            implicit_id_seed = f"{component_id}-{path.replace('/', '-')}"
            implicit_id = re.sub(r"[^a-z0-9._-]+", "-", implicit_id_seed.casefold()).strip("-")
            implicit_component = {
                "id": implicit_id,
                "display_name": f"Recursive submodule {component_id}:{path}",
                "version": commit,
                "kind": "git",
                "url": resolved_url,
                "commit": commit,
                "destination": f"{component['destination']}/{path}",
                "required_paths": [],
            }
            self.components[implicit_id] = implicit_component
            self._stage_git_component(
                implicit_component,
                parent_id=component_id,
                submodule_path=path,
                implicit=True,
            )

    def _stage_archive_component(self, component: dict) -> None:
        component_id = component["id"]
        fixture_file: Path | None = None
        if self.fixture_root is not None:
            relative = component.get("fixture_file", f"archives/{component_id}")
            relative = _safe_relative(relative, f"fixture archive for {component_id}")
            fixture_file = self.fixture_root.joinpath(*PurePosixPath(relative).parts)
        cached, selected_url, actual_sha256 = _download_to_cache(
            component_id,
            component["urls"],
            self.cache_root,
            allowed_suffixes=self.allowed_suffixes,
            sha256=component["sha256"],
            md5=None,
            offline=self.offline,
            fixture_file=fixture_file,
        )
        validated_file_members: tuple[str, ...] | None = None
        if (
            component.get("validate_archive_members", False)
            or component.get("required_source_members")
            or component.get("required_source_prefixes")
        ):
            validated_file_members = _validate_archive_members(cached)
        source_coverage = _verify_required_source_archive_coverage(
            cached,
            component,
            validated_file_members=validated_file_members,
        )
        destination = self.stage_root.joinpath(*PurePosixPath(component["destination"]).parts)
        if destination.exists():
            raise StageError(f"Refusing to overwrite staged archive: {component_id}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if component["stage_mode"] == "preserve":
            shutil.copyfile(cached, destination)
        else:
            _safe_extract_zip(cached, destination) if zipfile.is_zipfile(cached) else _safe_extract_tar(
                cached, destination
            )
        record = {
            "destination": component["destination"],
            "display_name": component.get("display_name", component_id),
            "id": component_id,
            "kind": "source-archive",
            "selected_url": selected_url,
            "sha256": actual_sha256,
            "source_urls": component["urls"],
            "stage_mode": component["stage_mode"],
            "version": component.get("version"),
        }
        if source_coverage is not None:
            record["verified_source_archive_coverage"] = source_coverage
        self.records.append(record)

    def _stage_project(self) -> None:
        if not SHA1_RE.fullmatch(self.project_commit):
            raise StageError("Project commit must be a full lowercase 40-character commit")
        _assert_plain_directory(self.project_repository, "Project repository")
        resolved = _run_git(
            self.project_repository,
            ["rev-parse", f"{self.project_commit}^{{commit}}"],
            allow_file=True,
        ).strip()
        if resolved != self.project_commit:
            raise StageError("Project repository does not contain the exact requested commit")
        project = self.manifest["project"]
        destination = self.stage_root.joinpath(*PurePosixPath(project["destination"]).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _export_git_tree(self.project_repository, self.project_commit, destination)
        _scan_private_paths(destination)
        gitlinks = _list_gitlinks(self.project_repository, self.project_commit)
        if gitlinks:
            raise StageError(
                "Project snapshot contains gitlinks; add explicit project submodule acquisition "
                f"before release: {sorted(gitlinks)}"
            )
        self.records.append(
            {
                "commit": self.project_commit,
                "destination": project["destination"],
                "display_name": project.get("display_name", project["id"]),
                "id": project["id"],
                "kind": "local-git-commit-export",
                "source_url": project["public_url"],
            }
        )

    def _verify_pin_evidence(self) -> None:
        for item in self.manifest.get("pin_evidence", []):
            component = self.components[item["component"]]
            path = self.stage_root.joinpath(
                *PurePosixPath(component["destination"]).parts,
                *PurePosixPath(item["path"]).parts,
            )
            if not path.is_file() or path.is_symlink():
                raise StageError(f"Pin evidence file is missing: {item['component']}:{item['path']}")
            text = path.read_text(encoding="utf-8")
            missing = [literal for literal in item["required_literals"] if literal not in text]
            if missing:
                raise StageError(
                    f"Dependency pin evidence drift in {item['component']}:{item['path']}: "
                    f"{missing}"
                )

    def _stage_dynamic_archives(self) -> None:
        for rule in self.manifest.get("dynamic_archive_rules", []):
            component = self.components[rule["component"]]
            component_root = self.stage_root.joinpath(
                *PurePosixPath(component["destination"]).parts
            )
            links = _scan_cmake_links(component_root, rule["source_glob"], rule)
            excluded = rule.get("excluded_variables", {})
            unknown_exclusions = sorted(set(excluded) - set(links))
            if unknown_exclusions:
                raise StageError(
                    f"Dynamic archive exclusion drift in {rule['id']}: {unknown_exclusions}"
                )
            active = {name: value for name, value in links.items() if name not in excluded}
            actual_unhashed = sorted(name for name, value in active.items() if value["md5"] is None)
            expected_unhashed = sorted(rule.get("known_unhashed_variables", []))
            if actual_unhashed != expected_unhashed:
                raise StageError(
                    f"Dynamic archive hash inventory drift in {rule['id']}: expected "
                    f"{expected_unhashed}, found {actual_unhashed}"
                )
            lock = _load_external_lock(
                self.external_lock_path,
                component["commit"],
                require_release_provenance=rule.get(
                    "require_release_asset_provenance", False
                ),
                expected_exclusions=excluded,
                payload=self.external_lock_payload,
            )
            unknown_locks = sorted(set(lock) - set(active))
            if unknown_locks:
                raise StageError(f"External archive lock has unknown variables: {unknown_locks}")
            all_active_archives_locked = bool(active) and set(lock) == set(active)
            missing_locks = [name for name in actual_unhashed if name not in lock]
            if rule.get("require_sha256_lock_for_unhashed") and missing_locks:
                details = {
                    name: [url for url in active[name]["urls"] if url.startswith("https://")]
                    for name in missing_locks
                }
                raise StageError(
                    "MeshLab external archives lack upstream hashes and need an explicit "
                    f"SHA-256 lock: {json.dumps(details, sort_keys=True)}"
                )
            output_root = self.stage_root.joinpath(*PurePosixPath(rule["destination"]).parts)
            output_root.mkdir(parents=True, exist_ok=False)
            for variable, item in sorted(active.items()):
                https_urls = [url for url in item["urls"] if url.startswith("https://")]
                if not https_urls:
                    raise StageError(f"No HTTPS source URL for MeshLab variable {variable}")
                lock_entry = lock.get(variable)
                sha256 = lock_entry["sha256"] if lock_entry else None
                if lock_entry:
                    if lock_entry["url"] not in https_urls:
                        raise StageError(f"External lock URL drift for {variable}")
                    if "upstream_md5" in lock_entry and lock_entry["upstream_md5"] != item["md5"]:
                        raise StageError(f"External lock upstream MD5 drift for {variable}")
                    if "cmake_path" in lock_entry and lock_entry["cmake_path"] != item["cmake_path"]:
                        raise StageError(f"External lock CMake source drift for {variable}")
                    https_urls = [lock_entry["url"]]
                fixture_file: Path | None = None
                if self.fixture_root is not None:
                    relative = (
                        lock_entry.get("fixture_file")
                        if lock_entry
                        else f"archives/{variable.casefold()}"
                    )
                    relative = _safe_relative(relative, f"fixture archive for {variable}")
                    fixture_file = self.fixture_root.joinpath(*PurePosixPath(relative).parts)
                cached, selected_url, actual_sha256 = _download_to_cache(
                    f"{rule['id']}-{variable.casefold()}",
                    https_urls,
                    self.cache_root,
                    allowed_suffixes=self.allowed_suffixes,
                    sha256=sha256,
                    md5=item["md5"],
                    expected_size=lock_entry.get("byte_size") if lock_entry else None,
                    offline=self.offline,
                    fixture_file=fixture_file,
                )
                if rule.get("validate_archive_members", False):
                    _validate_archive_members(cached)
                if lock_entry is not None:
                    _verify_declared_nonexecuted_archive_member(cached, lock_entry)
                    _verify_required_source_archive_members(cached, lock_entry)
                extension = _archive_extension(selected_url)
                output = output_root / f"{variable.casefold()}{extension}"
                if output.exists():
                    raise StageError(f"Duplicate dynamic archive output: {output.name}")
                shutil.copyfile(cached, output)
                record = {
                        "cmake_path": item["cmake_path"],
                        "cmake_variable": variable,
                        "destination": output.relative_to(self.stage_root).as_posix(),
                        "id": f"{rule['id']}-{variable.casefold()}",
                        "kind": "meshlab-external-build-input-archive",
                        "selected_url": selected_url,
                        "sha256": actual_sha256,
                        "source_urls": item["urls"],
                        "upstream_md5": item["md5"],
                        "verification": "sha256-lock" if sha256 else "upstream-cmake-md5",
                    }
                if lock_entry:
                    record["locked_byte_size"] = lock_entry.get("byte_size")
                    if lock_entry.get("provenance") is not None:
                        record["release_asset_provenance"] = lock_entry["provenance"]
                self.records.append(record)
            self.records.append(
                {
                    "excluded_variables": excluded,
                    "id": f"{rule['id']}-platform-exclusions",
                    "kind": "dynamic-archive-scan-metadata",
                    "source_component": rule["component"],
                }
            )
            gap_id = self._dynamic_release_gap_ids.get(rule["id"])
            if gap_id is not None and all_active_archives_locked:
                if self.external_lock_path is None:
                    raise StageError("A complete dynamic archive lock has no source file")
                if self.external_lock_sha256 is None:
                    raise StageError("A complete dynamic archive lock has no bound SHA-256")
                locked_variables = sorted(active)
                self.resolved_constraints.append(
                    {
                        "archive_count": len(locked_variables),
                        "external_archive_lock_sha256": self.external_lock_sha256,
                        "id": gap_id,
                        "locked_variables": locked_variables,
                        "resolution": DYNAMIC_ARCHIVE_LOCK_RESOLUTION,
                        "rule_id": rule["id"],
                    }
                )

    def stage(self) -> list[dict]:
        self._stage_project()
        for component_id, component in list(self.components.items()):
            if component_id in self._child_components:
                continue
            if component["kind"] == "git":
                self._stage_git_component(component)
        self._verify_pin_evidence()
        # Resolve every CMake-discovered build input, including all missing
        # strong-hash locks, before starting very large archive downloads such
        # as Qt.  An incomplete external inventory therefore fails early.
        self._stage_dynamic_archives()
        for component_id, component in list(self.components.items()):
            if component_id in self._child_components:
                continue
            if component["kind"] == "archive":
                self._stage_archive_component(component)
        return sorted(self.records, key=lambda item: (item.get("destination", ""), item["id"]))


def _write_source_manifest(root: Path) -> Path:
    manifest_path = root / "SOURCE_MANIFEST_SHA256.txt"
    rows: list[str] = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix().casefold()):
        if path == manifest_path:
            continue
        if path.is_symlink():
            raise StageError(f"Staged source contains a link: {path.relative_to(root)}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        _safe_relative(relative, "source manifest path")
        if relative.casefold() in seen:
            raise StageError(f"Case-insensitive duplicate staged path: {relative}")
        seen.add(relative.casefold())
        rows.append(f"{_hash_file(path).upper()}  {relative}")
    manifest_path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    return manifest_path


def _parse_source_manifest(payload: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in payload.splitlines():
        digest, separator, relative = line.partition("  ")
        if separator != "  " or not re.fullmatch(r"[0-9A-F]{64}", digest):
            raise StageError("Generated source manifest has invalid syntax")
        _safe_relative(relative, "generated source manifest path")
        folded = relative.casefold()
        if folded in result:
            raise StageError(f"Generated source manifest duplicates {relative}")
        result[folded] = digest
    return result


def _create_deterministic_zip(root: Path, archive: Path, archive_root_name: str) -> None:
    _safe_relative(archive_root_name, "archive root name")
    with zipfile.ZipFile(
        archive,
        mode="x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as package:
        for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix().casefold()):
            if path.is_symlink():
                raise StageError(f"Cannot archive a staged link: {path.relative_to(root)}")
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            archive_name = f"{archive_root_name}/{relative}"
            info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            executable = path.stat().st_mode & 0o111
            info.external_attr = ((0o100755 if executable else 0o100644) << 16)
            with path.open("rb") as source, package.open(info, "w", force_zip64=True) as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def _verify_output_zip(archive: Path, root_name: str) -> None:
    prefix = f"{root_name}/"
    with zipfile.ZipFile(archive) as package:
        names = [item.filename for item in package.infolist() if not item.is_dir()]
        if not names or any(not name.startswith(prefix) for name in names):
            raise StageError("Output archive has an unexpected root")
        for name in names:
            _archive_member_parts(name)
        manifest_name = f"{prefix}SOURCE_MANIFEST_SHA256.txt"
        if manifest_name not in names:
            raise StageError("Output archive lacks SOURCE_MANIFEST_SHA256.txt")
        expected = _parse_source_manifest(package.read(manifest_name).decode("utf-8"))
        actual_names = {
            name[len(prefix) :].casefold(): name
            for name in names
            if name != manifest_name
        }
        if len(actual_names) != len(names) - 1:
            raise StageError("Output archive has duplicate case-insensitive file names")
        if set(actual_names) != set(expected):
            raise StageError("Output archive contents do not match source manifest")
        for relative, name in actual_names.items():
            digest_object = hashlib.sha256()
            with package.open(name, "r") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest_object.update(block)
            digest = digest_object.hexdigest().upper()
            if digest != expected[relative]:
                raise StageError(f"Output archive hash mismatch: {name}")


def _verified_temporary_path(parent: Path, leaf_prefix: str) -> Path:
    _assert_plain_directory(parent, "Output parent")
    candidate = parent / f".{leaf_prefix}.staging-{uuid.uuid4().hex}"
    if candidate.exists() or candidate.parent.resolve() != parent.resolve():
        raise StageError("Cannot allocate a verified staging path")
    return candidate


def _copy_verified_file(
    source: Path,
    output: Path,
    expected_sha256: str,
    label: str,
) -> None:
    if not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(
        expected_sha256
    ):
        raise StageError(f"{label} has an invalid expected SHA-256")
    output_created = False
    try:
        with source.open("rb") as source_stream:
            with output.open("xb") as output_stream:
                output_created = True
                shutil.copyfileobj(source_stream, output_stream, length=1024 * 1024)
        actual_sha256 = _hash_file(output)
    except OSError as exc:
        if output_created:
            output.unlink(missing_ok=True)
        raise StageError(f"Cannot copy {label}: {exc}") from exc
    except Exception:
        if output_created:
            output.unlink(missing_ok=True)
        raise
    if actual_sha256 != expected_sha256:
        output.unlink(missing_ok=True)
        raise StageError(f"{label} changed after verification")


def stage_bundle(args: argparse.Namespace) -> tuple[Path, Path]:
    manifest_argument = Path(os.path.abspath(os.fspath(args.manifest)))
    if not manifest_argument.is_file() or _is_link_like(manifest_argument):
        raise StageError("Component manifest is missing or linked")
    manifest_path = manifest_argument.resolve()
    rebuild_component: dict | None = None
    rebuild_evidence: dict | None = None
    rebuild_files: list[tuple[Path, str, str]] = []
    if args.validate_manifest_only:
        manifest = _json_load(manifest_path)
        components = validate_component_manifest(manifest)
        policy = manifest.get("pytetwild_rebuild_policy")
        if policy is not None:
            template = manifest_path.parent.joinpath(
                *PurePosixPath(policy["template"]).parts
            ).resolve()
            component = components[policy["component"]]
            _validate_blocked_rebuild_template(template, component["commit"])
        print(
            f"Component manifest valid: {manifest['bundle_id']} "
            f"({manifest['bundle_status']})"
        )
        return Path(), Path()

    project_repository = Path(args.project_repository).resolve()
    project_commit = args.project_commit
    fixture_root = Path(args.fixture_root).resolve() if args.fixture_root else None
    manifest, external_lock, release_input_evidence = _verify_release_input_project_bindings(
        manifest_path,
        project_repository,
        project_commit,
        external_lock_argument=args.external_archive_lock,
    )
    components = validate_component_manifest(manifest)
    rebuild_template_evidence = release_input_evidence.get(
        "pytetwild_rebuild_template"
    )
    rebuild_component, rebuild_evidence, rebuild_files = _prepare_pytetwild_rebuild(
        manifest,
        manifest_path,
        args,
        project_repository=project_repository,
        project_commit=project_commit,
        rebuild_template_payload=(
            rebuild_template_evidence["payload"]
            if rebuild_template_evidence is not None
            else None
        ),
    )
    if rebuild_component is not None:
        if rebuild_component["id"] in components:
            raise StageError("PyTetWild rebuild nanobind component ID collides")
        components[rebuild_component["id"]] = rebuild_component

    destination = Path(args.destination).resolve()
    cache_root = Path(args.cache).resolve()
    archive = Path(args.archive).resolve() if args.archive else Path(f"{destination}.zip")
    if destination.exists():
        raise StageError(f"Refusing to overwrite existing destination: {destination}")
    if archive.exists():
        raise StageError(f"Refusing to overwrite existing archive: {archive}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    _assert_plain_directory(cache_root, "Cache root")
    if fixture_root is not None:
        _assert_plain_directory(fixture_root, "Fixture root")
    if destination == archive or _is_relative_to(cache_root, destination) or _is_relative_to(
        destination, cache_root
    ):
        raise StageError("Destination, archive, and cache paths must be distinct and non-nested")
    if _is_relative_to(destination, project_repository) or _is_relative_to(
        cache_root, project_repository
    ):
        raise StageError("Destination and cache must not be inside the project repository")

    temporary_stage = _verified_temporary_path(destination.parent, destination.name)
    temporary_archive = _verified_temporary_path(archive.parent, archive.name)
    temporary_stage.mkdir()
    destination_moved = False
    archive_published = False
    try:
        external_lock_evidence = release_input_evidence.get(
            "external_archive_lock"
        )
        stager = _Stager(
            manifest,
            dict(components),
            temporary_stage,
            cache_root,
            project_repository,
            project_commit,
            external_lock_path=external_lock,
            external_lock_payload=(
                external_lock_evidence["payload"]
                if external_lock_evidence is not None
                else None
            ),
            external_lock_sha256=(
                external_lock_evidence["sha256"]
                if external_lock_evidence is not None
                else None
            ),
            offline=args.offline,
            fixture_root=fixture_root,
        )
        records = stager.stage()
        for source, relative, expected_sha256 in rebuild_files:
            relative = _safe_relative(relative, "PyTetWild rebuild evidence destination")
            output = temporary_stage.joinpath(*PurePosixPath(relative).parts)
            if output.exists():
                raise StageError(f"Duplicate PyTetWild rebuild evidence: {relative}")
            output.parent.mkdir(parents=True, exist_ok=True)
            _copy_verified_file(
                source,
                output,
                expected_sha256,
                f"PyTetWild rebuild evidence {relative}",
            )
        verified_evidence = list(stager.resolved_constraints)
        if rebuild_evidence is not None:
            verified_evidence.append(rebuild_evidence)
        bundle_status, unresolved_gaps, resolved_constraints = _evaluate_release_state(
            manifest,
            verified_evidence,
        )
        provenance = {
            "bundle_id": manifest["bundle_id"],
            "bundle_status": bundle_status,
            "component_manifest_sha256": release_input_evidence[
                "component_manifest"
            ]["sha256"],
            "components": records,
            "deterministic_metadata": True,
            "known_gaps": unresolved_gaps,
            "schema_version": 1,
            "tool_version": TOOL_VERSION,
        }
        if external_lock is not None:
            provenance["external_archive_lock_sha256"] = release_input_evidence[
                "external_archive_lock"
            ]["sha256"]
        if resolved_constraints:
            provenance["resolved_constraints"] = resolved_constraints
        _write_json(temporary_stage / "COMPONENT_SOURCES.json", provenance)
        _write_source_manifest(temporary_stage)
        _create_deterministic_zip(temporary_stage, temporary_archive, destination.name)
        _verify_output_zip(temporary_archive, destination.name)
        archive_sha256 = _hash_file(temporary_archive)
        if destination.exists() or archive.exists():
            raise StageError("Output appeared during staging; refusing to overwrite it")
        try:
            os.rename(temporary_stage, destination)
        except FileExistsError as exc:
            raise StageError(
                "Output destination appeared during publication; refusing to overwrite it"
            ) from exc
        except OSError as exc:
            raise StageError(f"Cannot publish staged source directory: {exc}") from exc
        destination_moved = True
        try:
            os.link(temporary_archive, archive)
        except FileExistsError as exc:
            raise StageError(
                "Output archive appeared during publication; refusing to overwrite it"
            ) from exc
        except OSError as exc:
            raise StageError(f"Cannot publish source archive atomically: {exc}") from exc
        archive_published = True
        if _hash_file(archive) != archive_sha256:
            raise StageError("Published source archive changed during atomic publication")
        temporary_archive.unlink()
        print(f"Corresponding-source bundle staged ({bundle_status}): {destination}")
        print(f"Verified archive: {archive}")
        print(f"Archive SHA-256: {archive_sha256.upper()}")
        return destination, archive
    except Exception:
        if archive_published and archive.exists():
            archive.unlink()
        if destination_moved and destination.exists():
            shutil.rmtree(destination)
        raise
    finally:
        if temporary_stage.exists():
            shutil.rmtree(temporary_stage)
        temporary_archive.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(Path(__file__).with_name("corresponding_source_components.json")),
    )
    parser.add_argument("--destination")
    parser.add_argument("--cache")
    parser.add_argument("--project-repository")
    parser.add_argument("--project-commit")
    parser.add_argument("--archive")
    parser.add_argument("--external-archive-lock")
    parser.add_argument("--pytetwild-rebuild-lock")
    parser.add_argument("--pytetwild-wheel")
    parser.add_argument("--pytetwild-raw-wheel")
    parser.add_argument("--pytetwild-audit-logs")
    parser.add_argument("--pytetwild-build-recipe")
    parser.add_argument("--pytetwild-build-requirements")
    parser.add_argument("--pytetwild-source-patch")
    parser.add_argument("--pytetwild-build-attestation")
    parser.add_argument("--application-requirements-lock")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--fixture-root")
    parser.add_argument("--validate-manifest-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.validate_manifest_only:
        missing = [
            name
            for name in ("destination", "cache", "project_repository", "project_commit")
            if not getattr(args, name)
        ]
        if missing:
            parser.error(f"staging requires: {', '.join('--' + name.replace('_', '-') for name in missing)}")
    try:
        stage_bundle(args)
    except StageError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
