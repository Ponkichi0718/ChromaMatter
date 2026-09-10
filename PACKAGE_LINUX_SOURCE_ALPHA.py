#!/usr/bin/env python3
"""Create and fresh-extract audit the public Linux source-backed alpha.

This artifact contains the exact reviewed Git source, not third-party wheels or
a frozen application directory.  Dependencies are fetched by the installer
from their package index under the hash-pinned Linux lock.
Cross-host source candidates require explicit opt-in and do not assert Linux
runtime, native-library, graphical, or frozen-distribution verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


SCHEMA = "chromamatter.linux-source-alpha-release.v1"
ARCHIVE_ROOT = "ChromaMatter-0.9-Linux-Source-Alpha1"
REQUIRED_EXECUTABLES = (
    "INSTALL_LINUX_SOURCE_ALPHA.sh",
    "RUN_LINUX_SOURCE_ALPHA.sh",
)
FORBIDDEN_SUFFIXES = (
    ".exe", ".dll", ".pyd", ".whl", ".so", ".dylib", ".pyc", ".3mf", ".gcode",
    ".glb", ".gltf",
)
RELEASE_METADATA = "SOURCE_ALPHA_RELEASE.json"
LOCK_RELATIVE = "source/fixed_app/requirements-build-linux-x86_64.lock"
DEMO_DOCUMENTS = {
    "README_EN.md", "README_JA.md", "NOTICE_EN.md", "NOTICE_JA.md",
    "DEMO_DATA_MANIFEST.json",
}


class PackageError(RuntimeError):
    pass


def _run(command: list[str], *, cwd: Path, label: str) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise PackageError(f"{label} failed: {detail}")
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest().upper()


def _safe_member(name: str) -> PurePosixPath:
    canonical = name[:-1] if name.endswith("/") else name
    parts = canonical.split("/")
    if (
        not canonical or "\\" in name or ":" in name
        or any(ord(character) < 32 for character in name)
        or any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts)
        or any(part.casefold() == ".git" for part in parts)
    ):
        raise PackageError(f"unsafe archive member path: {name!r}")
    path = PurePosixPath(canonical)
    if path.parts[0] != ARCHIVE_ROOT:
        raise PackageError(f"archive member escaped the fixed root: {name!r}")
    return path


def _git_mode(repository: Path, source_commit: str, relative: str) -> int:
    output = _run(
        ["git", "ls-tree", source_commit, "--", relative],
        cwd=repository,
        label=f"Git mode lookup for {relative}",
    )
    if not output:
        raise PackageError(f"required source path is not tracked: {relative}")
    mode = output.split(maxsplit=1)[0]
    if mode != "100755":
        raise PackageError(f"{relative} must be tracked executable (100755), found {mode}")
    return 0o755


def _source_members(
    package: tarfile.TarFile, *, git_archive: bool = False,
) -> dict[str, dict[str, object]]:
    """Validate before extraction and record exact Git/archive payload bytes."""
    records: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    for member in package.getmembers():
        path = _safe_member(member.name)
        canonical = path.as_posix().casefold()
        if canonical in seen:
            raise PackageError(f"duplicate archive member: {member.name}")
        seen.add(canonical)
        if not member.isfile() and not member.isdir():
            raise PackageError(f"source alpha must contain only regular files/directories: {member.name}")
        expected_mode = 0o755 if member.isdir() or member.mode & 0o111 else 0o644
        if not git_archive and member.mode != expected_mode:
            raise PackageError(f"noncanonical archive permission bits: {member.name}")
        if member.isdir():
            continue
        relative = path.relative_to(ARCHIVE_ROOT).as_posix()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise PackageError(f"forbidden binary/private payload: {member.name}")
        if "DemoData" in path.parts and path.name not in DEMO_DOCUMENTS:
            raise PackageError(f"source candidate must not bundle DemoData payloads: {member.name}")
        if member.mode & 0o7000:
            raise PackageError(f"unsafe archive permission bits: {member.name}")
        stream = package.extractfile(member)
        if stream is None:
            raise PackageError(f"unreadable source member: {member.name}")
        with stream:
            payload = stream.read()
        records[relative] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest().upper(),
            # Git tracks only executable/non-executable regular-file modes.
            "mode": expected_mode,
        }
    if not records:
        raise PackageError("source archive is empty")
    return records


def _write_deterministic_tar_xz(
    stage_root: Path, archive: Path, epoch: int,
    source_files: dict[str, dict[str, object]],
) -> None:
    uncompressed = archive.with_suffix("")
    if uncompressed.exists():
        raise PackageError(f"temporary tar path already exists: {uncompressed}")
    try:
        with tarfile.open(uncompressed, "w", format=tarfile.PAX_FORMAT) as output:
            for path in sorted(stage_root.rglob("*"), key=lambda value: value.relative_to(stage_root).as_posix()):
                relative = path.relative_to(stage_root.parent).as_posix()
                _safe_member(relative)
                if path.is_symlink() or not (path.is_file() or path.is_dir()):
                    raise PackageError(f"unexpected source staging entry: {relative}")
                info = output.gettarinfo(str(path), arcname=relative)
                inside = path.relative_to(stage_root).as_posix()
                if path.is_file():
                    if inside == RELEASE_METADATA:
                        info.mode = 0o644
                    elif inside in source_files:
                        info.mode = int(source_files[inside]["mode"])
                    else:
                        raise PackageError(f"unexpected staged source file: {inside}")
                else:
                    info.mode = 0o755
                info.uid = 0
                info.gid = 0
                info.uname = "root"
                info.gname = "root"
                info.mtime = epoch
                info.pax_headers = {}
                if path.is_file():
                    with path.open("rb") as handle:
                        output.addfile(info, handle)
                else:
                    output.addfile(info)
        with uncompressed.open("rb") as source, lzma.open(
            archive,
            "wb",
            format=lzma.FORMAT_XZ,
            preset=9 | lzma.PRESET_EXTREME,
        ) as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
    finally:
        uncompressed.unlink(missing_ok=True)


def _audit_archive(
    archive: Path, source_commit: str, lock_sha256: str,
    source_files: dict[str, dict[str, object]], *, cross_host: bool = False,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="chromamatter-linux-source-audit-") as directory:
        extraction = Path(directory)
        with tarfile.open(archive, "r:xz") as package:
            archive_files = _source_members(package)
            if RELEASE_METADATA not in archive_files:
                raise PackageError("source release metadata is missing")
            del archive_files[RELEASE_METADATA]
            if archive_files != source_files:
                raise PackageError("archive source paths, bytes or Git executable modes differ")
            package.extractall(extraction, filter="data")

        root = extraction / ARCHIVE_ROOT
        release_path = root / RELEASE_METADATA
        release = json.loads(release_path.read_text(encoding="utf-8"))
        if release.get("schema") != SCHEMA or release.get("source_commit") != source_commit:
            raise PackageError("release metadata is not bound to the expected source commit")
        if release.get("requirements_lock_sha256") != lock_sha256:
            raise PackageError("release metadata lock SHA-256 mismatch")
        if _sha256(root / LOCK_RELATIVE) != lock_sha256:
            raise PackageError("fresh-extracted requirements lock SHA-256 mismatch")
        if release.get("source_files") != source_files:
            raise PackageError("release source manifest differs from the exact Git archive")
        verification_mode = "cross-host-static" if cross_host else "linux-host-source-audit"
        if (
            release.get("verification_mode") != verification_mode
            or release.get("linux_native_runtime_validation") != "pending-target-host"
            or release.get("frozen_binary_distribution_approved") is not False
        ):
            raise PackageError("release metadata misrepresents the verification scope")
        extracted_files = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*") if path.is_file()
        }
        if extracted_files != set(source_files) | {RELEASE_METADATA}:
            raise PackageError("fresh-extracted source path set differs from Git")
        for relative, record in source_files.items():
            path = root / relative
            if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
                raise PackageError(f"fresh-extracted source SHA-256/size mismatch: {relative}")
        for relative in REQUIRED_EXECUTABLES:
            path = root / relative
            if source_files.get(relative, {}).get("mode") != 0o755 or not path.is_file():
                raise PackageError(f"archive launcher lacks the exact Git executable mode: {relative}")
            if not cross_host and not os.access(path, os.X_OK):
                raise PackageError(f"fresh-extracted launcher is not executable: {relative}")
            if not cross_host:
                _run(["bash", "-n", str(path)], cwd=root, label=f"shell syntax for {relative}")
        if (root / ".git").exists():
            raise PackageError("source archive unexpectedly contains .git")
        file_count = sum(1 for path in root.rglob("*") if path.is_file())
        return {
            "archive": archive.name,
            "archive_sha256": _sha256(archive),
            "archive_size": archive.stat().st_size,
            "file_count": file_count,
            "fresh_extract": "passed",
            "requirements_lock_sha256": lock_sha256,
            "schema": "chromamatter.linux-source-alpha-archive-audit.v1",
            "source_commit": source_commit,
            "verification_mode": verification_mode,
            "shell_syntax": "not-run-cross-host" if cross_host else "passed",
            "linux_native_runtime_validation": "pending-target-host",
            "frozen_binary_distribution_approved": False,
            "source_file_hashes_and_modes": "passed",
        }


def package(
    repository: Path, archive: Path, audit_path: Path, source_commit: str, *,
    cross_host_source_candidate: bool = False,
) -> dict[str, object]:
    if sys.platform != "linux" and not cross_host_source_candidate:
        raise PackageError("run this packager on Linux so executable modes are preserved")
    repository = repository.resolve()
    archive = archive.resolve()
    audit_path = audit_path.resolve()
    if archive == audit_path:
        raise PackageError("archive and audit outputs must be different files")
    if archive.exists() or audit_path.exists():
        raise PackageError("archive and audit outputs must not already exist")
    observed = _run(["git", "rev-parse", "HEAD"], cwd=repository, label="Git HEAD")
    if observed != source_commit or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise PackageError(f"source commit is not the exact checkout HEAD: {observed}")
    _run(["git", "diff", "--quiet", "--ignore-submodules", "HEAD", "--"], cwd=repository, label="tracked worktree audit")
    _run(["git", "diff", "--cached", "--quiet", "HEAD", "--"], cwd=repository, label="index audit")
    for relative in REQUIRED_EXECUTABLES:
        _git_mode(repository, source_commit, relative)

    epoch_text = _run(["git", "show", "-s", "--format=%ct", source_commit], cwd=repository, label="commit epoch")
    epoch = int(epoch_text)
    archive.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chromamatter-linux-source-stage-") as directory:
        temporary = Path(directory)
        git_tar = temporary / "source.tar"
        _run(
            ["git", "archive", "--format=tar", f"--prefix={ARCHIVE_ROOT}/", "-o", str(git_tar), source_commit],
            cwd=repository,
            label="Git source archive",
        )
        with tarfile.open(git_tar, "r") as source:
            source_files = _source_members(source, git_archive=True)
            if RELEASE_METADATA in source_files:
                raise PackageError("Git source must not contain generated release metadata")
            if LOCK_RELATIVE not in source_files:
                raise PackageError("Git source is missing the Linux requirements lock")
            for relative in REQUIRED_EXECUTABLES:
                if source_files.get(relative, {}).get("mode") != 0o755:
                    raise PackageError(f"Git archive launcher is not executable: {relative}")
            lock_sha256 = str(source_files[LOCK_RELATIVE]["sha256"])
            source.extractall(temporary, filter="data")
        stage_root = temporary / ARCHIVE_ROOT
        release = {
            "application": "ChromaMatter",
            "display_version": "0.9",
            "distribution_model": "source-backed; third-party wheels downloaded during local setup",
            "requirements_lock_sha256": lock_sha256,
            "schema": SCHEMA,
            "source_commit": source_commit,
            "source_date_epoch": epoch,
            "supported_platform": "Ubuntu 22.04+ x86_64",
            "source_files": source_files,
            "verification_mode": "cross-host-static" if cross_host_source_candidate else "linux-host-source-audit",
            "linux_native_runtime_validation": "pending-target-host",
            "frozen_binary_distribution_approved": False,
        }
        (stage_root / RELEASE_METADATA).write_text(
            json.dumps(release, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.chmod(stage_root / RELEASE_METADATA, 0o644)
        _write_deterministic_tar_xz(stage_root, archive, epoch, source_files)

    audit = _audit_archive(
        archive, source_commit, lock_sha256, source_files,
        cross_host=cross_host_source_candidate,
    )
    audit_path.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--cross-host-source-candidate", action="store_true",
        help="Allow source-only assembly on another OS; Linux setup/native/UI validation remains pending.",
    )
    arguments = parser.parse_args()
    try:
        result = package(
            arguments.repository,
            arguments.archive,
            arguments.audit,
            arguments.source_commit,
            cross_host_source_candidate=arguments.cross_host_source_candidate,
        )
    except (PackageError, OSError, ValueError, tarfile.TarError, lzma.LZMAError, json.JSONDecodeError) as exc:
        print(f"Linux source alpha packaging refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
