#!/usr/bin/env python3
"""Create and verify a fail-closed ChromaMatter Linux candidate archive.

The binary archive and the eventual owner approval deliberately use two
different phases.  This tool may create a *candidate* only after the generated
Linux compliance evidence and corresponding-source manifests agree.  The
candidate audit always says ``distribution_ready: false``.  A separately
generated owner approval sidecar must bind the final archive and audit hashes
before ``verify-publish`` will succeed.  Keeping that approval outside the
archive avoids a self-referential archive hash.

Only GNU tar is accepted.  A normal ZIP is not suitable because the Linux app
contains executable modes and symbolic links which common ZIP extractors do
not preserve reliably.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from typing import Any, Iterable, Sequence


AUDIT_SCHEMA = "chromamatter.linux-release-archive-audit.v1"
INVENTORY_SCHEMA = "chromamatter.linux-app-inventory.v1"
CLOSURE_CONTRACT_SCHEMA = "chromamatter.linux-native-closure-contract.v1"
COMPONENT_MAP_SCHEMA = "chromamatter.linux-binary-component-map.v1"
SOURCE_MANIFEST_SCHEMA = "chromamatter.linux-corresponding-source-manifest.v1"
APPROVAL_SCHEMA = "chromamatter.linux-distribution-approval.v1"
SOURCE_PAYLOADS_SCHEMA = "chromamatter.linux-corresponding-source-payloads.v1"
SOURCE_STAGE_FILE_MANIFEST_SCHEMA = (
    "chromamatter.linux-source-stage-file-manifest.v1"
)
ARCHIVE_ROOT_NAME = "ChromaMatter-Linux-x86_64-Alpha"
APP_DIRECTORY_NAME = "ChromaMatter-Linux-Alpha"
APP_EXECUTABLE_NAME = "ChromaMatter"
ARCHIVE_AUDIT_NAME = "LINUX_RELEASE_ARCHIVE_AUDIT.json"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ROOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")

REQUIRED_EVIDENCE = (
    "LINUX_APP_INVENTORY.json",
    "LINUX_NATIVE_CLOSURE_CONTRACT.json",
    "BINARY_COMPONENT_MAP.json",
    "SBOM.spdx.json",
    "CORRESPONDING_SOURCE_MANIFEST.json",
    "DISTRIBUTION_APPROVAL.json",
    "BUILD_FROM_SOURCE_EN.md",
    "BUILD_FROM_SOURCE_JA.md",
    "RELINKING_EN.md",
    "RELINKING_JA.md",
    "LINUX_ALPHA_SOURCE_OFFER_STATUS_EN.txt",
    "LINUX_ALPHA_SOURCE_OFFER_STATUS_JA.txt",
)
ARCHIVED_EVIDENCE = tuple(
    name for name in REQUIRED_EVIDENCE if name != "DISTRIBUTION_APPROVAL.json"
) + ("SOURCE_PAYLOADS.json", "SOURCE_STAGE_FILE_MANIFEST.json")
IDENTITY_FIELDS = (
    "source_commit",
    "inventory_sha256",
    "lock_sha256",
    "catalog_sha256",
    "closure_contract_sha256",
)
FONT_PACKAGES = (
    "fonts-noto-cjk",
    "xfonts-base",
    "xfonts-intl-japanese",
    "xfonts-intl-japanese-big",
)
FONT_INSTALL_COMMAND = (
    "sudo apt-get update && sudo apt-get install -y " + " ".join(FONT_PACKAGES)
)


class ReleaseArchiveError(RuntimeError):
    """Raised when a candidate cannot be created or verified safely."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseArchiveError(f"Cannot read {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseArchiveError(f"{label} must contain one JSON object: {path}")
    return payload


def _require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReleaseArchiveError(f"Missing {label}: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ReleaseArchiveError(f"{label} must be a non-symlink regular file: {path}")
    if metadata.st_size <= 0:
        raise ReleaseArchiveError(f"{label} is empty: {path}")


def _require_directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReleaseArchiveError(f"Missing {label}: {path}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise ReleaseArchiveError(f"{label} must be a non-symlink directory: {path}")
    return path.resolve(strict=True)


def _validated_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ReleaseArchiveError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _identity(payload: dict[str, Any], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    commit = payload.get("source_commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        raise ReleaseArchiveError(f"{label}.source_commit is invalid")
    result["source_commit"] = commit
    for field in IDENTITY_FIELDS[1:]:
        result[field] = _validated_sha(payload.get(field), f"{label}.{field}")
    return result


def _validate_schema(payload: dict[str, Any], expected: str, label: str) -> None:
    if payload.get("schema") != expected:
        raise ReleaseArchiveError(
            f"Unsupported {label} schema: {payload.get('schema')!r}; expected {expected!r}"
        )


def _validate_evidence(
    evidence_dir: Path,
    source_payloads_manifest: Path,
    source_stage_file_manifest: Path,
    expected_source_commit: str,
) -> dict[str, Any]:
    evidence_dir = _require_directory(evidence_dir, "Linux evidence directory")
    if not COMMIT_RE.fullmatch(expected_source_commit):
        raise ReleaseArchiveError(
            "--expected-source-commit must be exactly 40 lowercase hexadecimal characters"
        )

    paths: dict[str, Path] = {}
    for name in REQUIRED_EVIDENCE:
        path = evidence_dir / name
        _require_regular_file(path, f"required evidence {name}")
        paths[name] = path

    # ``resolve`` would hide a symlink at the caller-supplied path before the
    # lstat check.  ``abspath`` normalizes the spelling without dereferencing.
    source_payloads_manifest = Path(os.path.abspath(source_payloads_manifest))
    source_stage_file_manifest = Path(os.path.abspath(source_stage_file_manifest))
    _require_regular_file(source_payloads_manifest, "SOURCE_PAYLOADS.json")
    _require_regular_file(
        source_stage_file_manifest, "SOURCE_STAGE_FILE_MANIFEST.json"
    )
    paths["SOURCE_PAYLOADS.json"] = source_payloads_manifest
    paths["SOURCE_STAGE_FILE_MANIFEST.json"] = source_stage_file_manifest

    inventory = _read_json_object(paths["LINUX_APP_INVENTORY.json"], "app inventory")
    closure_contract = _read_json_object(
        paths["LINUX_NATIVE_CLOSURE_CONTRACT.json"], "native-closure contract"
    )
    component_map = _read_json_object(
        paths["BINARY_COMPONENT_MAP.json"], "binary component map"
    )
    sbom = _read_json_object(paths["SBOM.spdx.json"], "SPDX SBOM")
    source_manifest = _read_json_object(
        paths["CORRESPONDING_SOURCE_MANIFEST.json"], "corresponding-source manifest"
    )
    approval = _read_json_object(
        paths["DISTRIBUTION_APPROVAL.json"], "candidate distribution approval"
    )
    source_payloads = _read_json_object(
        source_payloads_manifest, "corresponding-source payload manifest"
    )
    source_stage_files = _read_json_object(
        source_stage_file_manifest, "source-stage file manifest"
    )

    _validate_schema(inventory, INVENTORY_SCHEMA, "app inventory")
    _validate_schema(
        closure_contract, CLOSURE_CONTRACT_SCHEMA, "native-closure contract"
    )
    _validate_schema(component_map, COMPONENT_MAP_SCHEMA, "binary component map")
    _validate_schema(
        source_manifest, SOURCE_MANIFEST_SCHEMA, "corresponding-source manifest"
    )
    _validate_schema(approval, APPROVAL_SCHEMA, "distribution approval")
    _validate_schema(
        source_payloads, SOURCE_PAYLOADS_SCHEMA, "corresponding-source payloads"
    )
    _validate_schema(
        source_stage_files,
        SOURCE_STAGE_FILE_MANIFEST_SCHEMA,
        "source-stage file manifest",
    )

    inventory_sha256 = _sha256_file(paths["LINUX_APP_INVENTORY.json"])
    identities = {
        "component map": _identity(component_map, "component map"),
        "source manifest": _identity(source_manifest, "source manifest"),
        "approval": _identity(approval, "approval"),
        "source payloads": _identity(source_payloads, "source payloads"),
    }
    canonical_identity = next(iter(identities.values()))
    for label, candidate in identities.items():
        if candidate != canonical_identity:
            raise ReleaseArchiveError(
                f"Evidence identity mismatch in {label}: {candidate!r} != {canonical_identity!r}"
            )
    for field in IDENTITY_FIELDS:
        if source_stage_files.get(field) != canonical_identity[field]:
            raise ReleaseArchiveError(
                f"Evidence identity mismatch in source-stage file manifest: {field}"
            )
    if canonical_identity["source_commit"] != expected_source_commit:
        raise ReleaseArchiveError(
            "Evidence source_commit does not match --expected-source-commit"
        )
    if canonical_identity["inventory_sha256"] != inventory_sha256:
        raise ReleaseArchiveError(
            "Evidence inventory_sha256 does not match LINUX_APP_INVENTORY.json bytes"
        )
    if canonical_identity["closure_contract_sha256"] != _sha256_file(
        paths["LINUX_NATIVE_CLOSURE_CONTRACT.json"]
    ):
        raise ReleaseArchiveError(
            "Evidence closure_contract_sha256 does not match native-closure contract bytes"
        )

    stage_manifest_sha256 = _sha256_file(source_stage_file_manifest)
    if (
        _validated_sha(
            source_payloads.get("source_stage_manifest_sha256"),
            "source payloads.source_stage_manifest_sha256",
        )
        != stage_manifest_sha256
    ):
        raise ReleaseArchiveError(
            "SOURCE_PAYLOADS.json does not bind SOURCE_STAGE_FILE_MANIFEST.json bytes"
        )

    if sbom.get("spdxVersion") != "SPDX-2.3" or sbom.get("SPDXID") != "SPDXRef-DOCUMENT":
        raise ReleaseArchiveError("SBOM.spdx.json is not an SPDX 2.3 document")
    namespace = sbom.get("documentNamespace")
    expected_suffix = f"/{expected_source_commit}/{inventory_sha256}"
    if not isinstance(namespace, str) or not namespace.endswith(expected_suffix):
        raise ReleaseArchiveError(
            "SBOM documentNamespace does not bind source_commit and inventory_sha256"
        )

    approval_status = approval.get("status")
    if approval_status != "blocked" or approval.get("automatic_approval_permitted") is not False:
        raise ReleaseArchiveError(
            "Candidate evidence must preserve the blocked, non-automatic approval boundary"
        )
    if source_payloads.get("status") != "staged-verified":
        raise ReleaseArchiveError("SOURCE_PAYLOADS.json is not staged-verified")

    evidence_hashes = {
        name: _sha256_file(path) for name, path in sorted(paths.items())
    }
    return {
        "identity": canonical_identity,
        "paths": paths,
        "evidence_hashes": evidence_hashes,
        "approval_status": approval_status,
        "source_stage_manifest_sha256": stage_manifest_sha256,
    }


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ReleaseArchiveError(f"Path escaped release root: {path}") from exc
    raw = relative.as_posix()
    normalized = unicodedata.normalize("NFC", raw)
    if raw != normalized:
        raise ReleaseArchiveError(f"Release path is not NFC-normalized: {raw!r}")
    pure = PurePosixPath(normalized)
    if (
        normalized in {"", "."}
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in normalized
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ReleaseArchiveError(f"Unsafe release-relative path: {raw!r}")
    return normalized


def _lexically_resolve_link(parent: PurePosixPath, target: str) -> PurePosixPath:
    if not target or "\\" in target or target.startswith("/"):
        raise ReleaseArchiveError(f"Unsafe symlink target: {target!r}")
    normalized = unicodedata.normalize("NFC", target)
    if target != normalized or any(
        ord(character) < 32 or ord(character) == 127 for character in target
    ):
        raise ReleaseArchiveError(f"Unsafe symlink target: {target!r}")
    parts: list[str] = list(parent.parts)
    for part in PurePosixPath(target).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ReleaseArchiveError(f"Symlink target escapes release root: {target!r}")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        return PurePosixPath(".")
    return PurePosixPath(*parts)


def _tree_entry(root: Path, path: Path, entry_type: str) -> dict[str, Any]:
    metadata = path.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & 0o7000:
        raise ReleaseArchiveError(
            f"setuid/setgid/sticky mode is not allowed: {_safe_relative_path(path, root)}"
        )
    fact: dict[str, Any] = {
        "path": _safe_relative_path(path, root),
        "type": entry_type,
        "mode": f"{mode:04o}",
    }
    if entry_type == "regular":
        if metadata.st_nlink != 1:
            raise ReleaseArchiveError(f"Hard-linked file is not allowed: {fact['path']}")
        fact["size"] = metadata.st_size
        fact["sha256"] = _sha256_file(path)
    elif entry_type == "symlink":
        raw_target = os.readlink(path)
        _lexically_resolve_link(PurePosixPath(fact["path"]).parent, raw_target)
        if not os.path.lexists(path):
            raise ReleaseArchiveError(f"Broken symlink: {fact['path']}")
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ReleaseArchiveError(f"Broken or cyclic symlink: {fact['path']}") from exc
        try:
            resolved.relative_to(root.resolve(strict=True))
        except ValueError as exc:
            raise ReleaseArchiveError(f"Symlink escapes release root: {fact['path']}") from exc
        fact["target"] = raw_target
    return fact


def _scan_tree(root: Path) -> dict[str, Any]:
    root = _require_directory(root, "release tree")
    root_mode = stat.S_IMODE(root.lstat().st_mode)
    if root_mode & 0o7000:
        raise ReleaseArchiveError("Release root has unsafe special mode bits")
    entries: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for directory, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        directory_path = Path(directory)
        directory_names.sort(key=lambda value: unicodedata.normalize("NFC", value))
        file_names.sort(key=lambda value: unicodedata.normalize("NFC", value))
        retained: list[str] = []
        for name in directory_names:
            candidate = directory_path / name
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                entries.append(_tree_entry(root, candidate, "symlink"))
            elif stat.S_ISDIR(metadata.st_mode):
                entries.append(_tree_entry(root, candidate, "directory"))
                retained.append(name)
            else:
                raise ReleaseArchiveError(
                    f"Unsupported directory entry: {_safe_relative_path(candidate, root)}"
                )
        directory_names[:] = retained

        for name in file_names:
            candidate = directory_path / name
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                entries.append(_tree_entry(root, candidate, "symlink"))
            elif stat.S_ISREG(metadata.st_mode):
                entries.append(_tree_entry(root, candidate, "regular"))
            else:
                raise ReleaseArchiveError(
                    f"Unsupported special file: {_safe_relative_path(candidate, root)}"
                )

    entries.sort(key=lambda item: str(item["path"]))
    for entry in entries:
        path = str(entry["path"])
        folded = path.casefold()
        previous = seen.get(folded)
        if previous is not None:
            raise ReleaseArchiveError(
                f"Duplicate or case-colliding release paths: {previous!r}, {path!r}"
            )
        seen[folded] = path

    manifest = {"root_mode": f"{root_mode:04o}", "entries": entries}
    encoded = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    manifest["tree_sha256"] = _sha256_bytes(encoded)
    return manifest


def _manifest_counts(manifest: dict[str, Any]) -> dict[str, int]:
    counts = {"regular": 0, "directory": 0, "symlink": 0}
    for entry in manifest["entries"]:
        counts[str(entry["type"])] += 1
    return counts


def _render_readme(source_commit: str) -> str:
    return f"""# ChromaMatter Linux x86_64 volunteer-test build

This archive is for volunteer testing on **Ubuntu 22.04 x86_64**. It is not a
Windows or macOS build. Source commit: `{source_commit}`.

## 1. Install the required fonts

ChromaMatter does not run `sudo` or install packages for you. Run this yourself:

```bash
{FONT_INSTALL_COMMAND}
```

All four packages are required for the Japanese Tk UI and generated preview
text. The launcher stops with the same command if anything is missing.

## 2. Extract with GNU tar

Use a Linux filesystem and preserve executable modes and symbolic links:

```bash
tar -xJf ChromaMatter-Linux-x86_64-Alpha.tar.xz
cd {ARCHIVE_ROOT_NAME}
```

Do not unpack this archive with a ZIP tool or copy the extracted application
through a filesystem that removes Linux permissions or symbolic links.

## 3. Start ChromaMatter

Start an X11/Wayland desktop session first. `DISPLAY` must be set. Then run:

```bash
./START_CHROMAMATTER.sh
```

The launcher checks Linux, x86_64, Ubuntu 22.04, the four font packages,
`DISPLAY`, and the internal executable. It never runs `sudo` or `apt`.

## Evidence and corresponding source

`compliance/` contains the component map, SPDX SBOM, inventory, relinking/build
instructions, and manifests that identify the separately distributed
corresponding-source payload. The source payload itself is a separate asset.

This candidate archive does not approve its own publication. A valid external
`DISTRIBUTION_APPROVAL.json` must bind the exact archive SHA-256, archive-audit
SHA-256, source commit, inventory SHA-256, and source-stage manifest SHA-256.
"""


def _render_launcher() -> str:
    packages = " ".join(FONT_PACKAGES)
    return f"""#!/usr/bin/env bash
set -euo pipefail

fail() {{
    printf 'ChromaMatter Linux startup check failed: %s\\n' "$1" >&2
    exit 1
}}

[[ "$(uname -s)" == "Linux" ]] || fail "Linux is required."
[[ "$(uname -m)" == "x86_64" ]] || fail "x86_64 is required."
[[ -r /etc/os-release ]] || fail "/etc/os-release is unavailable; Ubuntu 22.04 is required."

# /etc/os-release is OS-owned data. shellcheck disable=SC1091
. /etc/os-release
[[ "${{ID:-}}" == "ubuntu" && "${{VERSION_ID:-}}" == "22.04" ]] || \
    fail "Ubuntu 22.04 is required (found ${{PRETTY_NAME:-unknown}})."

command -v dpkg-query >/dev/null 2>&1 || fail "dpkg-query is required."
missing=()
for package in {packages}; do
    if ! dpkg-query -W -f='${{Status}}\\n' "$package" 2>/dev/null | \
        grep -qx 'install ok installed'; then
        missing+=("$package")
    fi
done
if (( ${{#missing[@]}} )); then
    printf 'Missing required font packages: %s\\n' "${{missing[*]}}" >&2
    printf 'Install them yourself with:\\n  {FONT_INSTALL_COMMAND}\\n' >&2
    exit 1
fi

[[ -n "${{DISPLAY:-}}" ]] || fail \
    "DISPLAY is empty. Start an X11/Wayland desktop (or WSLg) and try again."

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd -P)"
APP="$SCRIPT_DIR/{APP_DIRECTORY_NAME}/{APP_EXECUTABLE_NAME}"
[[ -f "$APP" && ! -L "$APP" ]] || fail "Internal ChromaMatter executable is missing."
[[ -x "$APP" ]] || fail "Internal ChromaMatter executable is not executable."

exec "$APP" "$@"
"""


def _stage_release(
    app_dir: Path,
    evidence: dict[str, Any],
    stage_parent: Path,
    root_name: str,
) -> Path:
    app_dir = _require_directory(app_dir, "Linux application directory")
    if app_dir.name != APP_DIRECTORY_NAME:
        raise ReleaseArchiveError(
            f"Linux application directory must be named {APP_DIRECTORY_NAME!r}"
        )
    executable = app_dir / APP_EXECUTABLE_NAME
    _require_regular_file(executable, "Linux application executable")
    if stat.S_IMODE(executable.lstat().st_mode) & 0o111 == 0:
        raise ReleaseArchiveError("Linux application executable has no execute bit")
    _scan_tree(app_dir)

    outer = stage_parent / root_name
    outer.mkdir(mode=0o755)
    shutil.copytree(
        app_dir,
        outer / APP_DIRECTORY_NAME,
        symlinks=True,
        copy_function=shutil.copy2,
    )

    compliance = outer / "compliance"
    compliance.mkdir(mode=0o755)
    compliance.chmod(0o755)
    paths: dict[str, Path] = evidence["paths"]
    for name in ARCHIVED_EVIDENCE:
        destination = compliance / name
        shutil.copyfile(paths[name], destination, follow_symlinks=False)
        destination.chmod(0o644)

    readme = outer / "README_LINUX.md"
    readme.write_text(
        _render_readme(evidence["identity"]["source_commit"]), encoding="utf-8"
    )
    readme.chmod(0o644)
    launcher = outer / "START_CHROMAMATTER.sh"
    launcher.write_text(_render_launcher(), encoding="utf-8", newline="\n")
    launcher.chmod(0o755)
    outer.chmod(0o755)
    return outer


def _require_linux_x86_64() -> None:
    if not sys.platform.startswith("linux") or os.name != "posix":
        raise ReleaseArchiveError("Linux candidate archives must be created on Linux")
    if platform.machine().casefold() != "x86_64":
        raise ReleaseArchiveError("Linux candidate archives must be created on x86_64")


def _gnu_tar(tar_binary: str) -> str:
    resolved = shutil.which(tar_binary)
    if not resolved:
        raise ReleaseArchiveError(f"GNU tar executable not found: {tar_binary}")
    completed = subprocess.run(
        [resolved, "--version"], check=False, capture_output=True, text=True
    )
    first_line = (completed.stdout or "").splitlines()[:1]
    if completed.returncode != 0 or not first_line or "GNU tar" not in first_line[0]:
        raise ReleaseArchiveError(f"GNU tar is required; got: {first_line!r}")
    return resolved


def _run(arguments: Sequence[str], label: str) -> None:
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C", "TZ": "UTC"})
    completed = subprocess.run(
        [str(value) for value in arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ReleaseArchiveError(
            f"{label} failed with exit {completed.returncode}: {detail}"
        )


def _member_relative(name: str, root_name: str) -> str:
    normalized = unicodedata.normalize("NFC", name.rstrip("/"))
    if name.rstrip("/") != normalized:
        raise ReleaseArchiveError(f"Archive member is not NFC-normalized: {name!r}")
    raw_parts = normalized.split("/")
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or "\\" in normalized
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ReleaseArchiveError(f"Unsafe archive member path: {name!r}")
    if pure.parts[0] != root_name:
        raise ReleaseArchiveError(f"Archive has an unexpected outer root: {name!r}")
    if len(pure.parts) == 1:
        return "."
    return PurePosixPath(*pure.parts[1:]).as_posix()


def _validate_archive_symlink_graph(
    facts: dict[str, dict[str, Any]], root_name: str
) -> None:
    symlink_paths = {
        path for path, fact in facts.items() if fact["type"] == "symlink"
    }
    for path in facts:
        for link in symlink_paths:
            if path != link and path.startswith(link + "/"):
                raise ReleaseArchiveError(
                    f"Archive member is nested below a symlink: {root_name}/{path}"
                )

    def resolve(path: str, chain: tuple[str, ...]) -> None:
        fact = facts.get(path)
        if fact is None:
            raise ReleaseArchiveError(f"Archive symlink target is absent: {path}")
        if fact["type"] != "symlink":
            return
        if path in chain:
            raise ReleaseArchiveError(f"Archive contains a symlink cycle: {path}")
        target = _lexically_resolve_link(PurePosixPath(path).parent, fact["target"])
        if target == PurePosixPath("."):
            return
        resolve(target.as_posix(), chain + (path,))

    for path in symlink_paths:
        resolve(path, ())


def _inspect_archive(
    archive: Path,
    expected_manifest: dict[str, Any],
    root_name: str,
    source_date_epoch: int,
) -> None:
    expected = {entry["path"]: entry for entry in expected_manifest["entries"]}
    observed: dict[str, dict[str, Any]] = {}
    folded: dict[str, str] = {}
    root_seen = False

    try:
        handle = tarfile.open(archive, mode="r:xz")
    except (OSError, tarfile.TarError) as exc:
        raise ReleaseArchiveError(f"Cannot open xz-compressed tar archive: {exc}") from exc
    with handle:
        members = handle.getmembers()
        for member in members:
            relative = _member_relative(member.name, root_name)
            key = relative.casefold()
            previous = folded.get(key)
            if previous is not None:
                raise ReleaseArchiveError(
                    f"Duplicate or case-colliding archive members: {previous!r}, {relative!r}"
                )
            folded[key] = relative
            if member.uid != 0 or member.gid != 0:
                raise ReleaseArchiveError(f"Archive owner is not numeric root: {member.name}")
            if int(member.mtime) != source_date_epoch:
                raise ReleaseArchiveError(f"Archive mtime is not canonical: {member.name}")
            mode = member.mode & 0o7777
            if mode & 0o7000:
                raise ReleaseArchiveError(f"Archive has unsafe special mode bits: {member.name}")

            if member.isdir():
                entry_type = "directory"
            elif member.isreg():
                entry_type = "regular"
            elif member.issym():
                entry_type = "symlink"
            elif member.islnk():
                raise ReleaseArchiveError(f"Archive hard link is forbidden: {member.name}")
            else:
                raise ReleaseArchiveError(f"Archive special entry is forbidden: {member.name}")

            if relative == ".":
                if entry_type != "directory" or f"{mode:04o}" != expected_manifest["root_mode"]:
                    raise ReleaseArchiveError("Archive outer-root type or mode is incorrect")
                root_seen = True
                continue

            fact: dict[str, Any] = {
                "path": relative,
                "type": entry_type,
                "mode": f"{mode:04o}",
            }
            if entry_type == "regular":
                extracted = handle.extractfile(member)
                if extracted is None:
                    raise ReleaseArchiveError(f"Cannot read archive member: {member.name}")
                digest = hashlib.sha256()
                size = 0
                with extracted:
                    for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                        size += len(chunk)
                        digest.update(chunk)
                fact.update({"size": size, "sha256": digest.hexdigest()})
            elif entry_type == "symlink":
                _lexically_resolve_link(PurePosixPath(relative).parent, member.linkname)
                fact["target"] = member.linkname
            observed[relative] = fact

    if not root_seen:
        raise ReleaseArchiveError("Archive does not contain its outer root directory")
    if observed != expected:
        missing = sorted(set(expected) - set(observed))[:10]
        extra = sorted(set(observed) - set(expected))[:10]
        changed = sorted(
            path for path in set(expected) & set(observed) if expected[path] != observed[path]
        )[:10]
        raise ReleaseArchiveError(
            f"Archive payload differs from manifest; missing={missing}, extra={extra}, changed={changed}"
        )
    _validate_archive_symlink_graph(observed, root_name)


def _extract_and_compare(
    archive: Path,
    expected_manifest: dict[str, Any],
    root_name: str,
    tar_binary: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="chromamatter-linux-fresh-extract-") as raw:
        extract_root = Path(raw)
        _run(
            (
                tar_binary,
                "--extract",
                "--xz",
                "--file",
                str(archive),
                "--directory",
                str(extract_root),
                "--no-same-owner",
                "--same-permissions",
            ),
            "GNU tar fresh extraction",
        )
        children = list(extract_root.iterdir())
        if len(children) != 1 or children[0].name != root_name:
            raise ReleaseArchiveError("Fresh extraction did not produce exactly one outer root")
        extracted_root = children[0]
        observed = _scan_tree(extracted_root)
        if observed != expected_manifest:
            raise ReleaseArchiveError("Fresh-extracted tree differs in path/mode/link/hash")

        launcher = extracted_root / "START_CHROMAMATTER.sh"
        _require_regular_file(launcher, "fresh-extracted launcher")
        if stat.S_IMODE(launcher.lstat().st_mode) != 0o755:
            raise ReleaseArchiveError("Fresh-extracted launcher mode is not 0755")
        app = extracted_root / APP_DIRECTORY_NAME / APP_EXECUTABLE_NAME
        _require_regular_file(app, "fresh-extracted application executable")
        if stat.S_IMODE(app.lstat().st_mode) & 0o111 == 0:
            raise ReleaseArchiveError("Fresh-extracted application lost its execute bit")

        counts = _manifest_counts(observed)
        return {
            "fresh_extract_parity": True,
            "symlink_parity": counts["symlink"]
            == _manifest_counts(expected_manifest)["symlink"],
            "mode_parity": True,
            "hash_parity": True,
            "path_safety_verified": True,
            "counts": counts,
            "extractor": "GNU tar --no-same-owner --same-permissions",
            "effective_uid": os.geteuid() if hasattr(os, "geteuid") else None,
        }


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
    except FileExistsError as exc:
        raise ReleaseArchiveError(f"Refusing to overwrite existing file: {path}") from exc


def create_candidate(
    *,
    app_dir: Path,
    evidence_dir: Path,
    source_payloads_manifest: Path,
    source_stage_file_manifest: Path,
    archive: Path,
    audit: Path,
    source_date_epoch: int,
    expected_source_commit: str,
    root_name: str = ARCHIVE_ROOT_NAME,
    tar_command: str = "tar",
) -> dict[str, Any]:
    _require_linux_x86_64()
    if not SAFE_ROOT_RE.fullmatch(root_name):
        raise ReleaseArchiveError(f"Unsafe archive outer-root name: {root_name!r}")
    if source_date_epoch < 0:
        raise ReleaseArchiveError("--source-date-epoch must be a non-negative integer")
    if archive.suffixes[-2:] != [".tar", ".xz"]:
        raise ReleaseArchiveError("Candidate archive must use the .tar.xz extension")

    archive = archive.resolve(strict=False)
    audit = audit.resolve(strict=False)
    if archive == audit:
        raise ReleaseArchiveError("Archive and audit paths must be different")
    if audit.name != ARCHIVE_AUDIT_NAME:
        raise ReleaseArchiveError(
            f"Candidate audit must be named exactly {ARCHIVE_AUDIT_NAME}"
        )
    if archive.exists() or audit.exists():
        raise ReleaseArchiveError("Refusing to overwrite an existing archive or audit")
    archive.parent.mkdir(parents=True, exist_ok=True)
    audit.parent.mkdir(parents=True, exist_ok=True)
    tar_binary = _gnu_tar(tar_command)
    evidence = _validate_evidence(
        evidence_dir,
        source_payloads_manifest,
        source_stage_file_manifest,
        expected_source_commit,
    )

    temporary_archive = archive.with_name(f".{archive.name}.incomplete-{os.getpid()}")
    if temporary_archive.exists():
        raise ReleaseArchiveError(f"Temporary archive already exists: {temporary_archive}")
    try:
        with tempfile.TemporaryDirectory(
            prefix=".chromamatter-linux-release-stage-", dir=archive.parent
        ) as raw_stage:
            outer = _stage_release(
                app_dir, evidence, Path(raw_stage), root_name
            )
            manifest = _scan_tree(outer)
            _run(
                (
                    tar_binary,
                    "--sort=name",
                    "--format=posix",
                    f"--mtime=@{source_date_epoch}",
                    "--owner=0",
                    "--group=0",
                    "--numeric-owner",
                    "--pax-option=delete=atime,delete=ctime",
                    "--create",
                    "--xz",
                    "--file",
                    str(temporary_archive),
                    "--directory",
                    str(outer.parent),
                    "--",
                    root_name,
                ),
                "GNU tar archive creation",
            )
            _inspect_archive(
                temporary_archive, manifest, root_name, source_date_epoch
            )
            fresh = _extract_and_compare(
                temporary_archive, manifest, root_name, tar_binary
            )
            archive_size = temporary_archive.stat().st_size
            archive_sha256 = _sha256_file(temporary_archive)

        identity = evidence["identity"]
        audit_payload: dict[str, Any] = {
            "schema": AUDIT_SCHEMA,
            "status": "verified-candidate",
            **identity,
            "source_stage_manifest_sha256": evidence[
                "source_stage_manifest_sha256"
            ],
            "archive_name": archive.name,
            "archive_sha256": archive_sha256,
            "archive_size": archive_size,
            "archive_format": "gnu-tar-posix+xz",
            "root_name": root_name,
            "source_date_epoch": source_date_epoch,
            "created_utc": dt.datetime.fromtimestamp(
                source_date_epoch, tz=dt.timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "payload_tree_sha256": manifest["tree_sha256"],
            "payload_manifest": {
                "root_mode": manifest["root_mode"],
                "entries": manifest["entries"],
            },
            "fresh_extract_parity": fresh["fresh_extract_parity"],
            "symlink_parity": fresh["symlink_parity"],
            "mode_parity": fresh["mode_parity"],
            "hash_parity": fresh["hash_parity"],
            "path_safety_verified": fresh["path_safety_verified"],
            "fresh_extract": fresh,
            "evidence_hashes": evidence["evidence_hashes"],
            "candidate_approval_status": evidence["approval_status"],
            "distribution_ready": False,
            "publication_gate": (
                "An external approved DISTRIBUTION_APPROVAL.json must bind this "
                "archive SHA-256, this audit file SHA-256, source_commit, "
                "inventory_sha256, and source_stage_manifest_sha256."
            ),
        }
        os.replace(temporary_archive, archive)
        try:
            _write_json_exclusive(audit, audit_payload)
        except Exception:
            archive.unlink(missing_ok=True)
            raise
        return audit_payload
    finally:
        temporary_archive.unlink(missing_ok=True)


def _validate_audit(path: Path) -> dict[str, Any]:
    _require_regular_file(path, "Linux release archive audit")
    audit = _read_json_object(path, "Linux release archive audit")
    _validate_schema(audit, AUDIT_SCHEMA, "Linux release archive audit")
    if audit.get("status") != "verified-candidate":
        raise ReleaseArchiveError("Archive audit status is not verified-candidate")
    if audit.get("distribution_ready") is not False:
        raise ReleaseArchiveError("Candidate archive audit must never self-approve distribution")
    _identity(audit, "archive audit")
    _validated_sha(audit.get("archive_sha256"), "archive audit.archive_sha256")
    _validated_sha(
        audit.get("source_stage_manifest_sha256"),
        "archive audit.source_stage_manifest_sha256",
    )
    if not isinstance(audit.get("archive_size"), int) or audit["archive_size"] <= 0:
        raise ReleaseArchiveError("Archive audit archive_size is invalid")
    if audit.get("archive_format") != "gnu-tar-posix+xz":
        raise ReleaseArchiveError("Archive audit format is invalid")
    if (
        not isinstance(audit.get("source_date_epoch"), int)
        or audit["source_date_epoch"] < 0
    ):
        raise ReleaseArchiveError("Archive audit source_date_epoch is invalid")
    evidence_hashes = audit.get("evidence_hashes")
    expected_evidence = set(REQUIRED_EVIDENCE) | {
        "SOURCE_PAYLOADS.json",
        "SOURCE_STAGE_FILE_MANIFEST.json",
    }
    if not isinstance(evidence_hashes, dict) or set(evidence_hashes) != expected_evidence:
        raise ReleaseArchiveError("Archive audit evidence_hashes has unexpected keys")
    for name, digest_value in evidence_hashes.items():
        _validated_sha(digest_value, f"archive audit.evidence_hashes[{name!r}]")
    if evidence_hashes["LINUX_APP_INVENTORY.json"] != audit["inventory_sha256"]:
        raise ReleaseArchiveError("Archive audit inventory evidence hash is inconsistent")
    if (
        evidence_hashes["SOURCE_STAGE_FILE_MANIFEST.json"]
        != audit["source_stage_manifest_sha256"]
    ):
        raise ReleaseArchiveError(
            "Archive audit source-stage manifest evidence hash is inconsistent"
        )
    payload = audit.get("payload_manifest")
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ReleaseArchiveError("Archive audit payload_manifest is malformed")
    manifest = {
        "root_mode": payload.get("root_mode"),
        "entries": payload["entries"],
    }
    if not isinstance(manifest["root_mode"], str) or not re.fullmatch(
        r"0[0-7]{3}", manifest["root_mode"]
    ):
        raise ReleaseArchiveError("Archive audit payload root mode is invalid")
    required_archived_paths = {
        f"compliance/{name}": evidence_hashes[name] for name in ARCHIVED_EVIDENCE
    }
    manifest_by_path: dict[str, dict[str, Any]] = {}
    folded_paths: set[str] = set()
    for index, entry in enumerate(manifest["entries"]):
        if not isinstance(entry, dict):
            raise ReleaseArchiveError(
                f"Archive audit payload entry {index} is not an object"
            )
        path_value = entry.get("path")
        if not isinstance(path_value, str):
            raise ReleaseArchiveError(
                f"Archive audit payload entry {index} has no path"
            )
        canonical = _member_relative(f"audit-root/{path_value}", "audit-root")
        if canonical != path_value:
            raise ReleaseArchiveError(
                f"Archive audit payload path is noncanonical: {path_value}"
            )
        folded = path_value.casefold()
        if folded in folded_paths:
            raise ReleaseArchiveError(
                f"Archive audit payload path collides: {path_value}"
            )
        folded_paths.add(folded)
        if entry.get("type") not in {"regular", "directory", "symlink"}:
            raise ReleaseArchiveError(
                f"Archive audit payload type is invalid: {path_value}"
            )
        if not isinstance(entry.get("mode"), str) or not re.fullmatch(
            r"0[0-7]{3}", entry["mode"]
        ):
            raise ReleaseArchiveError(
                f"Archive audit payload mode is invalid: {path_value}"
            )
        if entry["type"] == "regular":
            if not isinstance(entry.get("size"), int) or entry["size"] < 0:
                raise ReleaseArchiveError(
                    f"Archive audit payload size is invalid: {path_value}"
                )
            _validated_sha(entry.get("sha256"), f"payload {path_value} sha256")
        elif entry["type"] == "symlink":
            target = entry.get("target")
            if not isinstance(target, str):
                raise ReleaseArchiveError(
                    f"Archive audit symlink target is invalid: {path_value}"
                )
            _lexically_resolve_link(PurePosixPath(path_value).parent, target)
        manifest_by_path[path_value] = entry
    for path_value, expected_hash in required_archived_paths.items():
        entry = manifest_by_path.get(path_value)
        if (
            entry is None
            or entry.get("type") != "regular"
            or entry.get("sha256") != expected_hash
        ):
            raise ReleaseArchiveError(
                f"Archive audit does not bind archived evidence: {path_value}"
            )
    launcher_entry = manifest_by_path.get("START_CHROMAMATTER.sh")
    if (
        launcher_entry is None
        or launcher_entry.get("type") != "regular"
        or launcher_entry.get("mode") != "0755"
    ):
        raise ReleaseArchiveError("Archive audit does not bind a 0755 launcher")
    encoded = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = _sha256_bytes(encoded)
    if audit.get("payload_tree_sha256") != digest:
        raise ReleaseArchiveError("Archive audit payload_tree_sha256 is invalid")
    manifest["tree_sha256"] = digest
    audit["_validated_manifest"] = manifest
    return audit


def verify_candidate(
    *,
    archive: Path,
    audit_path: Path,
    tar_command: str = "tar",
) -> dict[str, Any]:
    _require_linux_x86_64()
    _require_regular_file(archive, "Linux candidate archive")
    audit = _validate_audit(audit_path)
    if archive.name != audit.get("archive_name"):
        raise ReleaseArchiveError("Archive filename does not match archive audit")
    if archive.stat().st_size != audit["archive_size"]:
        raise ReleaseArchiveError("Archive size does not match archive audit")
    if _sha256_file(archive) != audit["archive_sha256"]:
        raise ReleaseArchiveError("Archive SHA-256 does not match archive audit")
    tar_binary = _gnu_tar(tar_command)
    manifest = audit.pop("_validated_manifest")
    root_name = audit.get("root_name")
    if not isinstance(root_name, str) or not SAFE_ROOT_RE.fullmatch(root_name):
        raise ReleaseArchiveError("Archive audit root_name is invalid")
    _inspect_archive(
        archive, manifest, root_name, int(audit["source_date_epoch"])
    )
    fresh = _extract_and_compare(archive, manifest, root_name, tar_binary)
    for field in (
        "fresh_extract_parity",
        "symlink_parity",
        "mode_parity",
        "hash_parity",
        "path_safety_verified",
    ):
        if audit.get(field) is not True or fresh.get(field) is not True:
            raise ReleaseArchiveError(f"Archive verification field is not true: {field}")
    return audit


def verify_publish(
    *, archive: Path, audit_path: Path, approval_path: Path, tar_command: str = "tar"
) -> dict[str, Any]:
    audit = verify_candidate(
        archive=archive, audit_path=audit_path, tar_command=tar_command
    )
    _require_regular_file(approval_path, "external distribution approval")
    approval = _read_json_object(approval_path, "external distribution approval")
    _validate_schema(approval, APPROVAL_SCHEMA, "external distribution approval")
    if approval.get("status") != "approved":
        raise ReleaseArchiveError("External distribution approval is not approved")
    owner = approval.get("owner_approval")
    if not isinstance(owner, dict) or owner.get("approved") is not True:
        raise ReleaseArchiveError("External owner_approval.approved is not true")
    if owner.get("decision_record_schema") != (
        "chromamatter.linux-owner-distribution-decision.v1"
    ):
        raise ReleaseArchiveError("External owner decision record schema is invalid")
    acknowledgements = owner.get("acknowledgements")
    if not isinstance(acknowledgements, dict) or not acknowledgements:
        raise ReleaseArchiveError("External owner approval acknowledgements are missing")
    if any(value is not True for value in acknowledgements.values()):
        raise ReleaseArchiveError("External owner approval has an unaccepted acknowledgement")
    for field in IDENTITY_FIELDS:
        if approval.get(field) != audit.get(field):
            raise ReleaseArchiveError(f"External approval does not bind audit {field}")
    bindings = {
        "archive_sha256": audit["archive_sha256"],
        "archive_audit_sha256": _sha256_file(audit_path),
        "source_stage_manifest_sha256": audit["source_stage_manifest_sha256"],
    }
    for field, expected in bindings.items():
        if approval.get(field) != expected:
            raise ReleaseArchiveError(f"External approval does not bind {field}")
    return {
        "schema": "chromamatter.linux-publication-gate-result.v1",
        "status": "approved-for-bound-artifacts",
        "source_commit": audit["source_commit"],
        "inventory_sha256": audit["inventory_sha256"],
        **bindings,
    }


def _add_common_verification_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--tar-command", default="tar")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create-candidate", help="stage, archive, and fresh-extract a candidate"
    )
    create.add_argument("--app-dir", type=Path, required=True)
    create.add_argument("--evidence-dir", type=Path, required=True)
    create.add_argument("--source-payloads-manifest", type=Path, required=True)
    create.add_argument("--source-stage-file-manifest", type=Path, required=True)
    create.add_argument("--archive", type=Path, required=True)
    create.add_argument("--audit", type=Path, required=True)
    create.add_argument("--source-date-epoch", type=int, required=True)
    create.add_argument("--expected-source-commit", required=True)
    create.add_argument("--root-name", default=ARCHIVE_ROOT_NAME)
    create.add_argument("--tar-command", default="tar")

    verify = subparsers.add_parser(
        "verify-candidate", help="reinspect and fresh-extract an existing candidate"
    )
    _add_common_verification_arguments(verify)

    publish = subparsers.add_parser(
        "verify-publish", help="require an external approval bound to the candidate"
    )
    _add_common_verification_arguments(publish)
    publish.add_argument("--approval", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create-candidate":
            result = create_candidate(
                app_dir=args.app_dir,
                evidence_dir=args.evidence_dir,
                source_payloads_manifest=args.source_payloads_manifest,
                source_stage_file_manifest=args.source_stage_file_manifest,
                archive=args.archive,
                audit=args.audit,
                source_date_epoch=args.source_date_epoch,
                expected_source_commit=args.expected_source_commit,
                root_name=args.root_name,
                tar_command=args.tar_command,
            )
        elif args.command == "verify-candidate":
            result = verify_candidate(
                archive=args.archive,
                audit_path=args.audit,
                tar_command=args.tar_command,
            )
        else:
            result = verify_publish(
                archive=args.archive,
                audit_path=args.audit,
                approval_path=args.approval,
                tar_command=args.tar_command,
            )
    except ReleaseArchiveError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
