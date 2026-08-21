#!/usr/bin/env python3
"""Stage a fail-closed corresponding-source candidate for ChromaMatter.

The release component list is deliberately data driven.  Git sources are
exported from exact full commit IDs (never from a working tree), archive
downloads are checked before use, and gitlinks are recursively populated.
The generated bundle is still a *candidate*: publication approval belongs to
the binary/license audit, not to this acquisition utility.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


TOOL_VERSION = 1
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
    re.compile(rb"(?i)[a-z]:[\\/]+users[\\/]+[a-z0-9._-]+[\\/]"),
    re.compile(rb"(?i)/(?:home|users)/[a-z0-9._-]+/"),
)


class StageError(RuntimeError):
    """A validation or staging error that must fail the bundle closed."""


def _json_load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageError(f"Cannot read JSON {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise StageError(f"JSON root must be an object: {path.name}")
    return value


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise StageError(f"{label} must match {ID_RE.pattern!r}")
    return value


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise StageError(f"{label} must be a non-empty relative path")
    if "\\" in value or WINDOWS_DRIVE_RE.match(value) or value.startswith("/"):
        raise StageError(f"{label} is not a normalized POSIX relative path: {value!r}")
    path = PurePosixPath(value)
    if str(path) != value or any(part in ("", ".", "..") for part in path.parts):
        raise StageError(f"{label} is not a normalized POSIX relative path: {value!r}")
    for part in path.parts:
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


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _assert_plain_directory(path: Path, label: str) -> None:
    if not path.is_dir() or path.is_symlink():
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
        else:
            raise StageError(f"Unsupported component kind for {component_id}: {kind!r}")
        result[component_id] = component
    return result


def validate_component_manifest(manifest: dict) -> dict[str, dict]:
    if manifest.get("schema_version") != 1:
        raise StageError("Unsupported component manifest schema_version")
    _safe_id(manifest.get("bundle_id"), "bundle_id")
    if manifest.get("bundle_status") != "candidate-only-not-release-approved":
        raise StageError("bundle_status must remain candidate-only-not-release-approved")
    known_gaps = manifest.get("known_gaps", [])
    if not isinstance(known_gaps, list):
        raise StageError("known_gaps must be an array")
    gap_ids: set[str] = set()
    for index, gap in enumerate(known_gaps):
        if not isinstance(gap, dict):
            raise StageError(f"known_gaps[{index}] must be an object")
        gap_id = _safe_id(gap.get("id"), f"known_gaps[{index}].id")
        if gap_id in gap_ids or gap.get("status") != "unresolved":
            raise StageError(f"Invalid or duplicate unresolved gap: {gap_id}")
        if not isinstance(gap.get("reason"), str) or not gap["reason"]:
            raise StageError(f"known_gaps[{index}] needs a reason")
        gap_ids.add(gap_id)
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
        if any(
            destination.casefold() == item["destination"].casefold()
            or destination.casefold().startswith(f"{item['destination'].casefold()}/")
            or item["destination"].casefold().startswith(f"{destination.casefold()}/")
            for item in components.values()
        ):
            raise StageError("pytetwild_rebuild_policy nanobind destination collides")
        if rebuild_policy.get("required_for_staging") is not True:
            raise StageError("pytetwild_rebuild_policy must be required_for_staging")

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
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise StageError(f"dynamic_archive_rules[{index}] must be an object")
        rule_id = _safe_id(rule.get("id"), f"dynamic_archive_rules[{index}].id")
        if rule_id in rule_ids:
            raise StageError(f"Duplicate dynamic archive rule id: {rule_id}")
        rule_ids.add(rule_id)
        component_id = rule.get("component")
        if component_id not in components or components[component_id]["kind"] != "git":
            raise StageError(f"Dynamic archive rule {rule_id} has invalid component")
        _safe_relative(rule.get("source_glob"), f"dynamic rule {rule_id} source_glob")
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


def _archive_member_parts(name: str, strip_components: int = 0) -> tuple[str, ...] | None:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise StageError(f"Unsafe archive member name: {name!r}")
    while name.startswith("./"):
        name = name[2:]
    if not name or name.startswith("/") or WINDOWS_DRIVE_RE.match(name):
        raise StageError(f"Unsafe archive member name: {name!r}")
    raw_parts = PurePosixPath(name).parts
    if any(part in ("", ".", "..") for part in raw_parts):
        raise StageError(f"Archive traversal or non-normal path: {name!r}")
    if len(raw_parts) <= strip_components:
        return None
    parts = raw_parts[strip_components:]
    _safe_relative("/".join(parts), f"archive member {name!r}")
    return tuple(parts)


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
    seen: dict[str, str] = {}
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
            parts = _archive_member_parts(member.name, strip_components)
            if parts is None:
                continue
            folded = "/".join(parts).casefold()
            member_kind = "directory" if member.isdir() else "file"
            previous_kind = seen.get(folded)
            if previous_kind is not None:
                if previous_kind == "directory" and member_kind == "directory":
                    continue
                raise StageError(f"Duplicate case-insensitive archive member: {member.name!r}")
            seen[folded] = member_kind
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
    seen: dict[str, str] = {}
    count = 0
    total = 0
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            count += 1
            if count > MAX_ARCHIVE_MEMBERS:
                raise StageError("Archive has too many members")
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise StageError(f"Archive links are forbidden: {member.filename!r}")
            if member.flag_bits & 0x1:
                raise StageError(f"Encrypted archive member is forbidden: {member.filename!r}")
            parts = _archive_member_parts(member.filename, strip_components)
            if parts is None:
                continue
            folded = "/".join(parts).casefold()
            member_kind = "directory" if member.is_dir() else "file"
            previous_kind = seen.get(folded)
            if previous_kind is not None:
                if previous_kind == "directory" and member_kind == "directory":
                    continue
                raise StageError(
                    f"Duplicate case-insensitive archive member: {member.filename!r}"
                )
            seen[folded] = member_kind
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


def _validate_archive_members(archive: Path) -> None:
    seen: dict[str, str] = {}
    count = 0
    total = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                count += 1
                if count > MAX_ARCHIVE_MEMBERS:
                    raise StageError("Archive has too many members")
                mode = (member.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise StageError(f"Archive links are forbidden: {member.filename!r}")
                if member.flag_bits & 0x1:
                    raise StageError(
                        f"Encrypted archive member is forbidden: {member.filename!r}"
                    )
                parts = _archive_member_parts(member.filename)
                if parts is None:
                    continue
                folded = "/".join(parts).casefold()
                member_kind = "directory" if member.is_dir() else "file"
                previous_kind = seen.get(folded)
                if previous_kind is not None:
                    if previous_kind == "directory" and member_kind == "directory":
                        continue
                    raise StageError(
                        f"Duplicate case-insensitive archive member: {member.filename!r}"
                    )
                seen[folded] = member_kind
                total += member.file_size
                if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise StageError("Archive expands beyond the safety limit")
        return
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
                parts = _archive_member_parts(member.name)
                if parts is None:
                    continue
                folded = "/".join(parts).casefold()
                member_kind = "directory" if member.isdir() else "file"
                previous_kind = seen.get(folded)
                if previous_kind is not None:
                    if previous_kind == "directory" and member_kind == "directory":
                        continue
                    raise StageError(
                        f"Duplicate case-insensitive archive member: {member.name!r}"
                    )
                seen[folded] = member_kind
                total += member.size
                if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise StageError("Archive expands beyond the safety limit")
        return
    raise StageError(f"Unsupported or damaged source archive: {archive.name}")


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


def _load_external_lock(
    path: Path | None,
    expected_commit: str,
    *,
    require_release_provenance: bool = False,
) -> dict[str, dict]:
    if path is None:
        return {}
    lock = _json_load(path)
    if lock.get("schema_version") != 1 or lock.get("meshlab_commit") != expected_commit:
        raise StageError("External archive lock schema or MeshLab commit does not match")
    if require_release_provenance and lock.get("lock_status") != (
        "verified-official-release-assets"
    ):
        raise StageError("Production external archive lock is not verified")
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
        if require_release_provenance:
            if byte_size is None or not isinstance(provenance, dict):
                raise StageError(
                    f"External lock {variable} lacks official release provenance"
                )
            for field in ("github_asset_id", "github_release_id"):
                value = provenance.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise StageError(
                        f"External lock {variable} has invalid provenance {field}"
                    )
            for field in ("asset_created_at", "asset_updated_at"):
                value = provenance.get(field)
                if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
                    raise StageError(
                        f"External lock {variable} has invalid provenance {field}"
                    )
            for field in (
                "release_repository_url",
                "release_api_url",
                "asset_api_url",
                "resolved_download_url",
            ):
                _validate_https_url(
                    provenance.get(field), f"external lock {variable} provenance {field}"
                )
            for field in ("asset_name", "github_release_tag"):
                if not isinstance(provenance.get(field), str) or not provenance[field]:
                    raise StageError(
                        f"External lock {variable} has invalid provenance {field}"
                    )
            if provenance.get("sha256_method") != (
                "downloaded-official-github-release-asset"
            ):
                raise StageError(
                    f"External lock {variable} has an unapproved SHA-256 method"
                )
            source_name = Path(urllib.parse.urlsplit(entry["url"]).path).name
            resolved_name = Path(
                urllib.parse.urlsplit(provenance["resolved_download_url"]).path
            ).name
            if source_name != provenance["asset_name"] or resolved_name != source_name:
                raise StageError(
                    f"External lock {variable} asset name does not match its URLs"
                )
        fixture_file = entry.get("fixture_file")
        if fixture_file is not None:
            _safe_relative(fixture_file, f"external lock {variable} fixture_file")
        result[variable] = entry
    return result


def _require_exact_keys(value: dict, expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise StageError(
            f"{label} fields do not match the schema; missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


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
    if not path.is_file() or path.is_symlink():
        raise StageError(f"{label} input is missing or linked")
    if path.name != filename:
        raise StageError(f"{label} filename does not match the rebuild lock")
    actual = _hash_file(path)
    if actual != digest:
        raise StageError(f"{label} SHA-256 does not match the rebuild lock")
    return {"filename": filename, "sha256": actual}


def _hashed_python_requirements(path: Path) -> dict[str, tuple[str, set[str]]]:
    try:
        physical_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise StageError(f"Cannot read PyTetWild build requirements lock: {exc}") from exc
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
        raise StageError("PyTetWild build requirements lock ends in a continuation")
    result: dict[str, tuple[str, set[str]]] = {}
    for line in logical_lines:
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError as exc:
            raise StageError(f"Invalid PyTetWild build requirement: {exc}") from exc
        if not tokens:
            continue
        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+-]*)",
            tokens[0],
        )
        if match is None:
            raise StageError(
                f"PyTetWild build requirement is not an exact name==version pin: {tokens[0]}"
            )
        name = re.sub(r"[-_.]+", "-", match.group(1)).casefold()
        version = match.group(2)
        hashes = {
            token.removeprefix("--hash=sha256:")
            for token in tokens[1:]
            if token.startswith("--hash=sha256:")
        }
        if not hashes or any(not SHA256_RE.fullmatch(item) for item in hashes):
            raise StageError(f"PyTetWild build requirement lacks valid SHA-256: {name}")
        unexpected = [token for token in tokens[1:] if not token.startswith("--hash=sha256:")]
        if unexpected:
            raise StageError(f"Unsupported PyTetWild build requirement options: {unexpected}")
        if name in result:
            raise StageError(f"Duplicate PyTetWild build requirement: {name}")
        result[name] = (version, hashes)
    required = {
        "abi3audit",
        "build",
        "cibuildwheel",
        "cmake",
        "delvewheel",
        "nanobind",
        "ninja",
        "scikit-build-core",
    }
    missing = sorted(required - set(result))
    if missing:
        raise StageError(f"PyTetWild build requirements are incomplete: {missing}")
    return result


def _verify_pytetwild_wheel(path: Path, wheel_specification: dict) -> None:
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
        if not any(
            name.casefold().startswith("pytetwild.libs/")
            and Path(name).name.casefold().startswith("mpir-")
            and name.casefold().endswith(".dll")
            for name in names
        ):
            raise StageError("PyTetWild wheel lacks its repaired MPIR runtime DLL")


def _validate_blocked_rebuild_template(path: Path, expected_commit: str) -> None:
    template = _json_load(path)
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


def _prepare_pytetwild_rebuild(
    manifest: dict,
    manifest_path: Path,
    args: argparse.Namespace,
) -> tuple[dict | None, dict | None, list[tuple[Path, str]]]:
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
    _validate_blocked_rebuild_template(template_path, expected["commit"])

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
        "pytetwild_build_recipe": "--pytetwild-build-recipe",
        "pytetwild_build_requirements": "--pytetwild-build-requirements",
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
    lock_path = Path(lock_argument).resolve()
    if not lock_path.is_file() or lock_path.is_symlink():
        raise StageError("PyTetWild rebuild lock is missing or linked")
    lock = _json_load(lock_path)
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
    wheel_path = Path(args.pytetwild_wheel).resolve()
    wheel_evidence = _verify_bound_file(
        {"filename": wheel["filename"], "sha256": wheel["sha256"]},
        wheel_path,
        "wheel",
    )
    if wheel_evidence["sha256"] == lock["historical_wheel"]["sha256"]:
        raise StageError("Controlled rebuild must not reuse the provenance-unknown wheel")
    _verify_pytetwild_wheel(wheel_path, wheel)

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
    if not isinstance(nanobind["required_paths"], list) or not nanobind["required_paths"]:
        raise StageError("nanobind.required_paths must be a non-empty array")
    for relative in nanobind["required_paths"]:
        _safe_relative(relative, "nanobind required path")

    bound_inputs = {
        "build_recipe": Path(args.pytetwild_build_recipe).resolve(),
        "build_requirements_lock": Path(args.pytetwild_build_requirements).resolve(),
        "attestation": Path(args.pytetwild_build_attestation).resolve(),
        "release_binding": Path(args.application_requirements_lock).resolve(),
    }
    bound_evidence = {
        key: _verify_bound_file(lock[key], path, key)
        for key, path in bound_inputs.items()
    }
    requirements = _hashed_python_requirements(bound_inputs["build_requirements_lock"])
    if requirements["nanobind"][0] != version:
        raise StageError("nanobind version differs between rebuild lock and hashed requirements")
    environment = lock["environment"]
    environment_fields = {
        "python_version",
        "cibuildwheel_version",
        "runner_image",
        "compiler",
        "cmake_version",
        "ninja_version",
        "windows_sdk_version",
    }
    _require_exact_keys(environment, environment_fields, "environment")
    for field in environment_fields:
        if not isinstance(environment[field], str) or not environment[field].strip():
            raise StageError(f"PyTetWild rebuild environment {field} is not exact")
    for field, requirement_name in (
        ("cibuildwheel_version", "cibuildwheel"),
        ("cmake_version", "cmake"),
        ("ninja_version", "ninja"),
    ):
        if environment[field] != requirements[requirement_name][0]:
            raise StageError(f"PyTetWild environment {field} differs from the build lock")

    release_text = bound_inputs["release_binding"].read_text(encoding="utf-8")
    if not re.search(r"(?m)^pytetwild==0\.3\.0\s*\\?\s*$", release_text):
        raise StageError("Application requirements lock lacks pytetwild==0.3.0")
    if f"sha256:{wheel_evidence['sha256']}" not in release_text:
        raise StageError("Application requirements lock does not bind the rebuilt wheel")
    if f"sha256:{lock['historical_wheel']['sha256']}" in release_text:
        raise StageError("Application requirements lock still permits the historical wheel")

    component = {
        "id": "pytetwild-nanobind-rebuild",
        "display_name": f"nanobind {version} used by controlled PyTetWild rebuild",
        "version": version,
        "kind": "git",
        "url": nanobind["source_url"],
        "commit": nanobind["commit"],
        "destination": policy["nanobind_destination"],
        "required_paths": nanobind["required_paths"],
    }
    evidence = {
        "id": policy["known_gap_id"],
        "resolution": "verified-controlled-rebuild",
        "rebuild_lock_sha256": _hash_file(lock_path),
        "historical_wheel": lock["historical_wheel"],
        "wheel": wheel_evidence,
        "nanobind": {
            "version": version,
            "source_url": nanobind["source_url"],
            "commit": nanobind["commit"],
        },
        "environment": environment,
        "bound_evidence": bound_evidence,
    }
    files = [
        (lock_path, "build-evidence/pytetwild/pytetwild_rebuild.lock.json"),
        (bound_inputs["build_recipe"], f"build-evidence/pytetwild/{bound_evidence['build_recipe']['filename']}"),
        (bound_inputs["build_requirements_lock"], f"build-evidence/pytetwild/{bound_evidence['build_requirements_lock']['filename']}"),
        (bound_inputs["attestation"], f"build-evidence/pytetwild/{bound_evidence['attestation']['filename']}"),
    ]
    return component, evidence, files


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
        self.offline = offline
        self.fixture_root = fixture_root
        self.records: list[dict] = []
        self._staged_components: set[str] = set()
        self._relations = {
            (item["parent"], item["path"]): item["child"]
            for item in manifest.get("submodule_relations", [])
        }
        self._child_components = {item["child"] for item in manifest.get("submodule_relations", [])}
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
        if component.get("validate_archive_members", False):
            _validate_archive_members(cached)
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
        self.records.append(
            {
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
        )

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
            )
            unknown_locks = sorted(set(lock) - set(active))
            if unknown_locks:
                raise StageError(f"External archive lock has unknown variables: {unknown_locks}")
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


def stage_bundle(args: argparse.Namespace) -> tuple[Path, Path]:
    manifest_path = Path(args.manifest).resolve()
    manifest = _json_load(manifest_path)
    components = validate_component_manifest(manifest)
    rebuild_component: dict | None = None
    rebuild_evidence: dict | None = None
    rebuild_files: list[tuple[Path, str]] = []
    if args.validate_manifest_only:
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

    rebuild_component, rebuild_evidence, rebuild_files = _prepare_pytetwild_rebuild(
        manifest, manifest_path, args
    )
    if rebuild_component is not None:
        if rebuild_component["id"] in components:
            raise StageError("PyTetWild rebuild nanobind component ID collides")
        components[rebuild_component["id"]] = rebuild_component

    destination = Path(args.destination).resolve()
    cache_root = Path(args.cache).resolve()
    project_repository = Path(args.project_repository).resolve()
    archive = Path(args.archive).resolve() if args.archive else Path(f"{destination}.zip")
    external_lock = Path(args.external_archive_lock).resolve() if args.external_archive_lock else None
    if external_lock is None and manifest.get("default_external_archive_lock"):
        external_lock = manifest_path.parent.joinpath(
            *PurePosixPath(manifest["default_external_archive_lock"]).parts
        ).resolve()
        if not _is_relative_to(external_lock, manifest_path.parent.resolve()):
            raise StageError("Default external archive lock escaped the manifest directory")
    if external_lock is not None and (
        not external_lock.is_file() or external_lock.is_symlink()
    ):
        raise StageError("External archive lock is missing or linked")
    fixture_root = Path(args.fixture_root).resolve() if args.fixture_root else None
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
    try:
        stager = _Stager(
            manifest,
            dict(components),
            temporary_stage,
            cache_root,
            project_repository,
            args.project_commit,
            external_lock_path=external_lock,
            offline=args.offline,
            fixture_root=fixture_root,
        )
        records = stager.stage()
        for source, relative in rebuild_files:
            relative = _safe_relative(relative, "PyTetWild rebuild evidence destination")
            output = temporary_stage.joinpath(*PurePosixPath(relative).parts)
            if output.exists():
                raise StageError(f"Duplicate PyTetWild rebuild evidence: {relative}")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, output)
        provenance = {
            "bundle_id": manifest["bundle_id"],
            "bundle_status": manifest["bundle_status"],
            "component_manifest_sha256": _hash_file(manifest_path),
            "components": records,
            "deterministic_metadata": True,
            "known_gaps": [
                gap
                for gap in manifest.get("known_gaps", [])
                if rebuild_evidence is None or gap["id"] != rebuild_evidence["id"]
            ],
            "schema_version": 1,
            "tool_version": TOOL_VERSION,
        }
        if external_lock is not None:
            provenance["external_archive_lock_sha256"] = _hash_file(external_lock)
        if rebuild_evidence is not None:
            provenance["resolved_constraints"] = [rebuild_evidence]
        _write_json(temporary_stage / "COMPONENT_SOURCES.json", provenance)
        _write_source_manifest(temporary_stage)
        _create_deterministic_zip(temporary_stage, temporary_archive, destination.name)
        _verify_output_zip(temporary_archive, destination.name)
        if destination.exists() or archive.exists():
            raise StageError("Output appeared during staging; refusing to overwrite it")
        os.replace(temporary_stage, destination)
        destination_moved = True
        os.replace(temporary_archive, archive)
        print(f"Corresponding-source candidate staged: {destination}")
        print(f"Verified archive: {archive}")
        print(f"Archive SHA-256: {_hash_file(archive).upper()}")
        return destination, archive
    except Exception:
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
    parser.add_argument("--pytetwild-build-recipe")
    parser.add_argument("--pytetwild-build-requirements")
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
