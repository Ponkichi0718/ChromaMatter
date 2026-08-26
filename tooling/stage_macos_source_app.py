#!/usr/bin/env python3
"""Stage and audit the Finder-launchable macOS source-backed alpha app.

This is intentionally not the frozen prebuilt application.  The bundle carries
only ChromaMatter source, non-executable application data, notices, and a small
shell wrapper which opens the existing source-alpha launcher in Terminal.  The
Python interpreter and every third-party dependency are installed from the
existing hash-locked launcher on the tester's own Mac.

The separate prebuilt-app source/build/relink gate is not consulted or changed
by this tool.  Conversely, this tool rejects Mach-O, ELF, PE, wheel, virtual-
environment, and native-library payloads so it cannot be used to smuggle a
prebuilt runtime around that gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import stat
import struct
import subprocess
import sys
import tempfile


SCHEMA = "chromamatter.macos-source-backed-app.v1"
APP_NAME = "ChromaMatter Source Alpha.app"
EXECUTABLE_NAME = "ChromaMatterSourceAlpha"
SOURCE_DIRECTORY = "ChromaMatterSource"
SOURCE_LAUNCHER = "START_MACOS_SOURCE_ALPHA.command"
MANIFEST_NAME = "SOURCE_BACKED_APP_MANIFEST.json"
NOTICE_NAME = "SOURCE_BACKED_ALPHA_NOTICE.txt"
ICON_NAME = "AppIcon.icns"

EXPECTED_PLIST = {
    "CFBundleDisplayName": "ChromaMatter Source Alpha",
    "CFBundleExecutable": EXECUTABLE_NAME,
    "CFBundleIdentifier": "io.github.ponkichi0718.chromamatter.source-alpha",
    "CFBundleName": "ChromaMatter Source Alpha",
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": "0.8.0",
    "CFBundleVersion": "800",
    "LSMinimumSystemVersion": "15.0",
}

FORBIDDEN_SUFFIXES = {
    ".a",
    ".app",
    ".bundle",
    ".class",
    ".dll",
    ".dylib",
    ".elf",
    ".exe",
    ".framework",
    ".jar",
    ".o",
    ".obj",
    ".pkg",
    ".pyc",
    ".pyd",
    ".so",
    ".whl",
}
FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "site-packages",
}
MACH_O_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}
EXECUTABLE_MAGICS = MACH_O_MAGICS | {b"\x7fELF"}

ROOT_DOCUMENTS = {
    "FEATURES_EN.md",
    "FEATURES_JA.md",
    "LICENSE",
    "PRIVACY.md",
    "PROVENANCE.md",
    "README_EN.md",
    "README_JA.md",
    "SECURITY.md",
}
SAMPLE_FILES = {
    "samples/LICENSE.txt",
    "samples/MACOS_ALPHA_TEST_MODEL_README.md",
    "samples/generate_macos_alpha_test_glb.py",
}
FIXED_APP_FILES = {
    "source/fixed_app/README_fixed_en.md",
    "source/fixed_app/README_fixed_ja.md",
    "source/fixed_app/THIRD_PARTY_VOLUME_LICENSES_JA.md",
    "source/fixed_app/VERSION_POLICY.md",
    "source/fixed_app/orca_paint_vectors.json",
    "source/fixed_app/requirements-runtime-macos-arm64.lock",
}
FIXED_APP_PREFIXES = (
    "source/fixed_app/assets/",
    "source/fixed_app/licenses/",
    "source/fixed_app/resources/",
    "source/fixed_app/spectrum_mapper/",
)


class SourceAppError(RuntimeError):
    """A fail-closed source-backed app staging or audit error."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    candidate = PurePosixPath(value)
    if (
        not value
        or candidate.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise SourceAppError(f"Unsafe source path: {value!r}")
    return candidate


def _git_output(repository: Path, arguments: list[str]) -> bytes:
    completed = subprocess.run(
        ["git", "-C", os.fspath(repository), *arguments],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SourceAppError(f"Git source query failed: {detail}")
    return completed.stdout


def _git_head(repository: Path) -> str:
    try:
        value = _git_output(
            repository,
            ["rev-parse", "--verify", "HEAD^{commit}"],
        ).decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SourceAppError("Git returned a non-ASCII HEAD object ID") from exc
    if len(value) != 40:
        raise SourceAppError("Git HEAD is not an exact 40-character commit ID")
    return value.casefold()


def _git_tracked_files(
    repository: Path,
    source_commit: str,
) -> dict[str, tuple[str, str]]:
    raw = _git_output(
        repository,
        ["ls-tree", "-r", "-z", source_commit],
    )
    try:
        values = raw.decode("utf-8").split("\0")
    except UnicodeDecodeError as exc:
        raise SourceAppError("Git returned a non-UTF-8 source path") from exc
    tracked: dict[str, tuple[str, str]] = {}
    for value in values:
        if not value:
            continue
        try:
            metadata, relative = value.split("\t", 1)
            mode, object_type, object_id = metadata.split(" ", 2)
        except ValueError as exc:
            raise SourceAppError("Git returned a malformed source-tree record") from exc
        _safe_relative(relative)
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise SourceAppError(
                f"Unsupported Git object in source-backed app input: {relative}"
            )
        tracked[relative] = (mode, object_id)
    if not tracked:
        raise SourceAppError("Git returned an empty source tree")
    return tracked


def _selected_source_paths(
    repository: Path,
    source_commit: str,
) -> tuple[tuple[str, str, str], ...]:
    tracked = _git_tracked_files(repository, source_commit)
    selected: list[str] = []
    for relative in sorted(tracked):
        if relative in ROOT_DOCUMENTS or relative in SAMPLE_FILES:
            selected.append(relative)
            continue
        if relative == SOURCE_LAUNCHER or relative in FIXED_APP_FILES:
            selected.append(relative)
            continue
        if relative.startswith("licenses/"):
            selected.append(relative)
            continue
        if relative.startswith(FIXED_APP_PREFIXES):
            selected.append(relative)
            continue
        if (
            relative.startswith("source/fixed_app/")
            and "/" not in relative[len("source/fixed_app/") :]
            and relative.endswith(".py")
            and not PurePosixPath(relative).name.startswith("test_")
        ):
            selected.append(relative)

    required = {
        SOURCE_LAUNCHER,
        "source/fixed_app/TripoSpectrumMapper_fixed.py",
        "source/fixed_app/spectrum_mapper/cli.py",
        "source/fixed_app/assets/obj_adjuster_icon.png",
        "source/fixed_app/requirements-runtime-macos-arm64.lock",
        "samples/generate_macos_alpha_test_glb.py",
        "LICENSE",
    }
    missing = sorted(required.difference(selected))
    if missing:
        raise SourceAppError(f"Required source-backed app files are missing: {missing}")
    return tuple(
        (relative, *tracked[relative])
        for relative in sorted(set(selected))
    )


def _git_blob(repository: Path, object_id: str) -> bytes:
    if len(object_id) != 40:
        raise SourceAppError("Git source blob has an invalid object ID")
    return _git_output(repository, ["cat-file", "blob", object_id])


def _is_windows_pe(path: Path, prefix: bytes) -> bool:
    if prefix[:2] != b"MZ":
        return False
    try:
        with path.open("rb") as handle:
            handle.seek(0x3C)
            raw_offset = handle.read(4)
            if len(raw_offset) != 4:
                return False
            offset = struct.unpack("<I", raw_offset)[0]
            if offset < 0x40 or offset > path.stat().st_size - 4:
                return False
            handle.seek(offset)
            return handle.read(4) == b"PE\0\0"
    except OSError as exc:
        raise SourceAppError(f"Cannot inspect executable signature: {path}") from exc


def _reject_runtime_payload(path: Path, relative: str) -> None:
    pure = _safe_relative(relative)
    folded_parts = {part.casefold() for part in pure.parts}
    forbidden_parts = folded_parts.intersection(FORBIDDEN_PARTS)
    if forbidden_parts:
        raise SourceAppError(
            f"Forbidden runtime/cache directory in source app: {relative}"
        )
    if pure.suffix.casefold() in FORBIDDEN_SUFFIXES:
        raise SourceAppError(f"Forbidden native/runtime file in source app: {relative}")
    try:
        with path.open("rb") as handle:
            prefix = handle.read(4)
    except OSError as exc:
        raise SourceAppError(f"Cannot inspect source app payload: {relative}") from exc
    if prefix in EXECUTABLE_MAGICS:
        raise SourceAppError(f"Executable binary signature in source app: {relative}")
    if _is_windows_pe(path, prefix):
        raise SourceAppError(f"Windows executable signature in source app: {relative}")


def _write_git_blob(
    destination: Path,
    relative: str,
    data: bytes,
    mode: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    _reject_runtime_payload(destination, relative)
    if destination.suffix == ".command" or mode == "100755":
        destination.chmod(0o755)
    else:
        destination.chmod(0o644)


def _make_icon(source_png: Path, destination: Path) -> None:
    data = source_png.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise SourceAppError("The ChromaMatter icon is not a valid PNG")
    width, height = struct.unpack(">II", data[16:24])
    if (width, height) != (1024, 1024):
        raise SourceAppError(
            f"The source-backed app icon must be 1024x1024, got {width}x{height}"
        )
    element = b"ic10" + struct.pack(">I", len(data) + 8) + data
    payload = b"icns" + struct.pack(">I", len(element) + 8) + element
    destination.write_bytes(payload)
    destination.chmod(0o644)


def _wrapper_text() -> str:
    return """#!/bin/bash
# Finder entry point for ChromaMatter Source Alpha.
# It opens the reviewed hash-locked source launcher in Terminal so first-run
# installation and self-test progress remain visible to the tester.
set -eu

CONTENTS_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
SOURCE_ROOT="$CONTENTS_DIR/Resources/ChromaMatterSource"
SOURCE_LAUNCHER="$SOURCE_ROOT/START_MACOS_SOURCE_ALPHA.command"

if [[ ! -f "$SOURCE_LAUNCHER" || -L "$SOURCE_LAUNCHER" ]]; then
    /usr/bin/logger -t ChromaMatterSourceAlpha \
        "Source launcher is missing or unsafe: $SOURCE_LAUNCHER"
    exit 1
fi

# Shell/CI callers receive the exact source launcher result and output. Finder
# supplies no arguments, so only a normal Finder launch opens Terminal.
if (($#)); then
    exec "$SOURCE_LAUNCHER" "$@"
fi

# Do not use sudo, alter quarantine attributes, disable Gatekeeper, or execute
# a bundled runtime here.  Terminal runs the source launcher's visible,
# hash-locked setup on this Mac.
exec /usr/bin/open -a Terminal "$SOURCE_LAUNCHER"
"""


def _notice_text(source_commit: str) -> str:
    return f"""ChromaMatter Source-backed App Alpha

Source commit: {source_commit}
Displayed product version: 0.8beta
Supported test host: Apple Silicon / macOS 15 or newer

This Finder-launchable .app is a convenience wrapper around
START_MACOS_SOURCE_ALPHA.command. It is NOT the frozen prebuilt ChromaMatter
application and it contains no Python runtime, virtual environment, wheel,
third-party native library, or packaged Mach-O executable.

On first launch the app opens Terminal. The source launcher may download the
verified official Python 3.13.14 installer and exact hash-locked dependencies,
install them into the current user's Application Support directory, run the
native/render self-test, and then start ChromaMatter from source. Keep Terminal
open while setup is running.

This route does not bypass Gatekeeper and does not satisfy, weaken, or replace
the separate 153-file prebuilt-app source/build/relink approval gate. The app
is not Developer ID signed or Apple-notarized. Use only the documented Finder
Open / Privacy & Security approval flow; never disable macOS security globally.
"""


def _plist_bytes() -> bytes:
    payload: dict[str, object] = {
        **EXPECTED_PLIST,
        "CFBundleDevelopmentRegion": "en",
        "CFBundleGetInfoString": "ChromaMatter 0.8beta source-backed alpha",
        "CFBundleIconFile": ICON_NAME,
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "LSArchitecturePriority": ["arm64"],
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "ChromaMatter contributors; GPL-3.0-or-later",
        "NSRequiresAquaSystemAppearance": False,
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)


def _manifest_records(app_bundle: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(app_bundle.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise SourceAppError(f"Symlink is forbidden in source app: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SourceAppError(f"Special file is forbidden in source app: {path}")
        relative = path.relative_to(app_bundle).as_posix()
        if relative == f"Contents/Resources/{MANIFEST_NAME}":
            continue
        _reject_runtime_payload(path, relative)
        records.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return records


def _write_manifest(app_bundle: Path, source_commit: str) -> None:
    manifest = {
        "schema": SCHEMA,
        "app_name": APP_NAME,
        "source_commit": source_commit,
        "source_backed": True,
        "bundled_python_runtime": False,
        "bundled_third_party_runtime_binaries": False,
        "prebuilt_app_distribution_gate_bypassed": False,
        "first_launch_opens_terminal": True,
        "records": _manifest_records(app_bundle),
    }
    destination = app_bundle / "Contents" / "Resources" / MANIFEST_NAME
    destination.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    destination.chmod(0o644)


def stage(repository: Path, output: Path, source_commit: str) -> None:
    repository = repository.resolve()
    output = output.absolute()
    if output.name != APP_NAME or output.suffix.casefold() != ".app":
        raise SourceAppError(f"Output app must be named exactly {APP_NAME!r}")
    if not repository.is_dir() or not (repository / ".git").exists():
        raise SourceAppError("Repository root must be an existing Git worktree")
    if not source_commit or len(source_commit) != 40:
        raise SourceAppError("Source commit must be an exact 40-character Git object ID")
    try:
        int(source_commit, 16)
    except ValueError as exc:
        raise SourceAppError("Source commit must contain hexadecimal characters") from exc
    source_commit = source_commit.casefold()
    head = _git_head(repository)
    if source_commit != head:
        raise SourceAppError(
            f"Source commit must equal repository HEAD: requested={source_commit}, HEAD={head}"
        )
    if output.exists() or output.is_symlink():
        raise SourceAppError(f"Refusing to replace an existing app bundle: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".chromamatter-source-app-", dir=output.parent) as raw:
        temporary_app = Path(raw) / APP_NAME
        contents = temporary_app / "Contents"
        macos = contents / "MacOS"
        resources = contents / "Resources"
        source_root = resources / SOURCE_DIRECTORY
        macos.mkdir(parents=True)
        source_root.mkdir(parents=True)

        (contents / "Info.plist").write_bytes(_plist_bytes())
        (contents / "Info.plist").chmod(0o644)

        wrapper = macos / EXECUTABLE_NAME
        wrapper.write_text(_wrapper_text(), encoding="utf-8", newline="\n")
        wrapper.chmod(0o755)

        for relative, mode, object_id in _selected_source_paths(
            repository,
            source_commit,
        ):
            destination = source_root.joinpath(*PurePosixPath(relative).parts)
            _write_git_blob(
                destination,
                relative,
                _git_blob(repository, object_id),
                mode,
            )

        notice = resources / NOTICE_NAME
        notice.write_text(_notice_text(source_commit), encoding="utf-8", newline="\n")
        notice.chmod(0o644)
        _make_icon(
            source_root
            / "source"
            / "fixed_app"
            / "assets"
            / "obj_adjuster_icon.png",
            resources / ICON_NAME,
        )
        _write_manifest(temporary_app, source_commit)
        audit(temporary_app)
        temporary_app.rename(output)


def audit(app_bundle: Path) -> dict[str, object]:
    if app_bundle.is_symlink():
        raise SourceAppError("Input source app bundle must not be a symlink")
    app_bundle = app_bundle.resolve()
    if app_bundle.name != APP_NAME or not app_bundle.is_dir():
        raise SourceAppError(f"Input app must be named exactly {APP_NAME!r}")
    contents = app_bundle / "Contents"
    wrapper = contents / "MacOS" / EXECUTABLE_NAME
    resources = contents / "Resources"
    launcher = resources / SOURCE_DIRECTORY / SOURCE_LAUNCHER
    notice = resources / NOTICE_NAME
    manifest_path = resources / MANIFEST_NAME
    plist_path = contents / "Info.plist"

    for path in (wrapper, launcher, notice, manifest_path, plist_path):
        if path.is_symlink() or not path.is_file():
            raise SourceAppError(f"Required source app file is missing or unsafe: {path}")
    if os.name != "nt":
        for path in (wrapper, launcher):
            if not (path.stat().st_mode & stat.S_IXUSR):
                raise SourceAppError(f"Source app launcher is not executable: {path}")

    try:
        plist = plistlib.loads(plist_path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise SourceAppError("Cannot parse source app Info.plist") from exc
    for key, expected in EXPECTED_PLIST.items():
        if plist.get(key) != expected:
            raise SourceAppError(
                f"Source app Info.plist mismatch for {key}: {plist.get(key)!r}"
            )

    wrapper_text = wrapper.read_text(encoding="utf-8")
    if "exec /usr/bin/open -a Terminal" not in wrapper_text:
        raise SourceAppError("Source app wrapper does not open the launcher in Terminal")
    if 'exec "$SOURCE_LAUNCHER" "$@"' not in wrapper_text:
        raise SourceAppError("Source app wrapper does not forward CLI arguments")
    for forbidden in ("sudo ", "spctl ", "xattr ", "installer -pkg", "codesign "):
        if forbidden in wrapper_text:
            raise SourceAppError(f"Forbidden security/install command in app wrapper: {forbidden}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceAppError("Cannot parse source-backed app manifest") from exc
    if manifest.get("schema") != SCHEMA or manifest.get("app_name") != APP_NAME:
        raise SourceAppError("Source-backed app manifest identity is invalid")
    expected_flags = {
        "source_backed": True,
        "bundled_python_runtime": False,
        "bundled_third_party_runtime_binaries": False,
        "prebuilt_app_distribution_gate_bypassed": False,
        "first_launch_opens_terminal": True,
    }
    for key, expected in expected_flags.items():
        if manifest.get(key) is not expected:
            raise SourceAppError(f"Source-backed app manifest flag is invalid: {key}")
    source_commit = manifest.get("source_commit")
    if not isinstance(source_commit, str) or len(source_commit) != 40:
        raise SourceAppError("Source-backed app manifest has no exact source commit")

    raw_records = manifest.get("records")
    if not isinstance(raw_records, list):
        raise SourceAppError("Source-backed app manifest records are invalid")
    expected_records: dict[str, tuple[int, str]] = {}
    for item in raw_records:
        if not isinstance(item, dict):
            raise SourceAppError("Source-backed app manifest record is invalid")
        relative = item.get("path")
        size = item.get("bytes")
        sha256 = item.get("sha256")
        if (
            not isinstance(relative, str)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or relative in expected_records
        ):
            raise SourceAppError("Source-backed app manifest record fields are invalid")
        _safe_relative(relative)
        expected_records[relative] = (size, sha256)

    actual_records = {
        item["path"]: (item["bytes"], item["sha256"])
        for item in _manifest_records(app_bundle)
    }
    if expected_records != actual_records:
        missing = sorted(set(expected_records).difference(actual_records))
        extra = sorted(set(actual_records).difference(expected_records))
        changed = sorted(
            path
            for path in set(expected_records).intersection(actual_records)
            if expected_records[path] != actual_records[path]
        )
        raise SourceAppError(
            "Source-backed app manifest mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    return {
        "schema": SCHEMA,
        "app": os.fspath(app_bundle),
        "source_commit": source_commit,
        "file_count": len(actual_records) + 1,
        "native_runtime_binary_count": 0,
        "status": "source-backed-app-audit-passed",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    stage_parser = subparsers.add_parser("stage", help="stage a fresh source app")
    stage_parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    stage_parser.add_argument("--output", type=Path, required=True)
    stage_parser.add_argument("--source-commit", required=True)

    audit_parser = subparsers.add_parser("audit", help="audit an existing source app")
    audit_parser.add_argument("--app-bundle", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.operation == "stage":
            stage(arguments.repository_root, arguments.output, arguments.source_commit)
            result = audit(arguments.output)
        else:
            result = audit(arguments.app_bundle)
    except SourceAppError as exc:
        print(f"macOS source-backed app error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
