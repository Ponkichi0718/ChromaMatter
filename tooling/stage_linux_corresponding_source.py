#!/usr/bin/env python3
"""Materialize a hash-locked Linux corresponding-source stage.

No network access is performed.  Every source archive or Git bundle must be
present in a caller-provided cache and must exactly match both the generated
corresponding-source manifest and a separately reviewed payload recipe.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from typing import Any, Sequence
import unicodedata


MODULE_PATH = Path(__file__).with_name("generate_linux_compliance_evidence.py")
SPEC = importlib.util.spec_from_file_location("chromamatter_linux_evidence", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import environment failure
    raise RuntimeError("Cannot load Linux compliance evidence helpers")
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)

TEMPLATE_NAMES = (
    "BUILD_FROM_SOURCE_EN.md",
    "BUILD_FROM_SOURCE_JA.md",
    "RELINKING_EN.md",
    "RELINKING_JA.md",
)
RESERVED_STAGE_FILES = {
    "SOURCE_PAYLOADS.json",
    "CORRESPONDING_SOURCE_MANIFEST.json",
    "SOURCE_STAGE_FILE_MANIFEST.json",
    *TEMPLATE_NAMES,
}
IDENTITY_KEYS = (
    "source_commit",
    "inventory_sha256",
    "lock_sha256",
    "catalog_sha256",
    "closure_contract_sha256",
)


class StageError(RuntimeError):
    pass


def _portable_key(value: str) -> tuple[str, ...]:
    return tuple(
        unicodedata.normalize("NFC", part).casefold() for part in PurePosixPath(value).parts
    )


def _validate_cache_filename(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in (".", "..")
        or "/" in value
        or "\\" in value
        or Path(value).name != value
    ):
        raise StageError("Linux source cache filename is unsafe")
    return value


def _source_identity(record: dict[str, Any]) -> dict[str, str]:
    kind = record.get("identity_kind")
    identity = {
        "identity_kind": kind,
        "source_url": record.get("source_url"),
    }
    if kind == "archive-sha256":
        digest = record.get("source_sha256")
        if not isinstance(digest, str) or not evidence.SHA256_RE.fullmatch(digest):
            raise StageError(f"Source archive identity is not fixed: {record.get('source_id')}")
        identity["source_sha256"] = digest
        identity["payload_format"] = "source-archive"
    elif kind == "git-commit":
        commit = record.get("source_commit")
        if not isinstance(commit, str) or not evidence.COMMIT_RE.fullmatch(commit):
            raise StageError(f"Git source identity is not fixed: {record.get('source_id')}")
        identity["source_commit"] = commit
        identity["payload_format"] = "git-bundle"
    else:
        raise StageError(f"Unsupported source identity kind: {record.get('source_id')}")
    if not isinstance(identity["source_url"], str) or not identity["source_url"].startswith("https://"):
        raise StageError(f"Source URL is not fixed: {record.get('source_id')}")
    return identity


def expected_sources(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    if manifest.get("schema") != "chromamatter.linux-corresponding-source-manifest.v1":
        raise StageError("Linux corresponding-source manifest schema is unsupported")
    if manifest.get("status") != "complete" or manifest.get("known_gaps") != []:
        raise StageError("Linux corresponding-source manifest is candidate-only")
    if manifest.get("stage_required") is not True or manifest.get("stage_status") != "not-staged":
        raise StageError("Linux corresponding-source manifest stage contract is invalid")
    for key in IDENTITY_KEYS:
        pattern = evidence.COMMIT_RE if key == "source_commit" else evidence.SHA256_RE
        if not pattern.fullmatch(str(manifest.get(key, ""))):
            raise StageError(f"Linux source manifest has no exact identity: {key}")
    records = manifest.get("component_sources")
    if not isinstance(records, list) or not records:
        raise StageError("Linux source manifest has no component sources")
    expected: dict[str, dict[str, str]] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("required_for_corresponding_source") is not True:
            raise StageError("Linux source record is malformed or optional")
        source_id = record.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in expected:
            raise StageError(f"Duplicate or invalid Linux source id: {source_id!r}")
        expected[source_id] = _source_identity(record)
    return expected


def validate_recipe(
    manifest: dict[str, Any], recipe: dict[str, Any]
) -> list[dict[str, Any]]:
    expected = expected_sources(manifest)
    if recipe.get("schema") != "chromamatter.linux-source-payload-recipe.v1":
        raise StageError("Linux source payload recipe schema is unsupported")
    if recipe.get("status") != "complete-recipe-reviewed":
        raise StageError("Linux source payload recipe has not been marked reviewed")
    for key in IDENTITY_KEYS:
        if recipe.get(key) != manifest.get(key):
            raise StageError(f"Linux source recipe/manifest identity mismatch: {key}")
    payloads = recipe.get("payloads")
    if not isinstance(payloads, list) or not payloads:
        raise StageError("Linux source payload recipe has no payloads")
    seen_ids: set[str] = set()
    cache_keys: dict[str, str] = {}
    stage_keys: dict[tuple[str, ...], str] = {
        _portable_key(name): name for name in RESERVED_STAGE_FILES
    }
    normalized: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            raise StageError("Linux source payload entry must be an object")
        source_id = payload.get("source_id")
        if not isinstance(source_id, str) or source_id not in expected or source_id in seen_ids:
            raise StageError(f"Unknown or duplicate Linux source payload: {source_id!r}")
        seen_ids.add(source_id)
        identity = payload.get("source_identity")
        if identity != expected[source_id]:
            raise StageError(f"Linux source payload identity mismatch: {source_id}")
        cache_filename = _validate_cache_filename(payload.get("cache_filename"))
        cache_key = unicodedata.normalize("NFC", cache_filename).casefold()
        if cache_key in cache_keys:
            raise StageError(
                f"Colliding Linux source cache filenames: {cache_keys[cache_key]!r} / {cache_filename!r}"
            )
        cache_keys[cache_key] = cache_filename
        stage_path = evidence.safe_relative_path(payload.get("stage_path"), "Linux source stage path")
        stage_key = _portable_key(stage_path)
        for existing_key, existing_path in stage_keys.items():
            common = min(len(stage_key), len(existing_key))
            if stage_key[:common] == existing_key[:common]:
                raise StageError(
                    f"Colliding Linux source stage paths: {existing_path!r} / {stage_path!r}"
                )
        stage_keys[stage_key] = stage_path
        digest = payload.get("sha256")
        if not isinstance(digest, str) or not evidence.SHA256_RE.fullmatch(digest):
            raise StageError(f"Linux source payload has no SHA-256: {source_id}")
        if identity["payload_format"] == "source-archive" and digest != identity["source_sha256"]:
            raise StageError(f"Linux source archive hash is not its audited source hash: {source_id}")
        normalized.append(
            {
                "source_id": source_id,
                "source_identity": identity,
                "cache_filename": cache_filename,
                "stage_path": stage_path,
                "sha256": digest,
            }
        )
    if seen_ids != set(expected):
        raise StageError(
            "Linux source payload coverage mismatch; "
            f"missing={sorted(set(expected) - seen_ids)}, extra={sorted(seen_ids - set(expected))}"
        )
    return sorted(normalized, key=lambda row: _portable_key(row["stage_path"]))


def _run_git(command: Sequence[str], label: str) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StageError(f"{label} could not run") from exc
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip().splitlines()
        raise StageError(f"{label} failed" + (f": {details[-1]}" if details else ""))
    return completed.stdout


def verify_git_bundle(path: Path, commit: str) -> None:
    git = shutil.which("git")
    if git is None:
        raise StageError("git is required to verify source bundle payloads")
    heads = _run_git([git, "bundle", "list-heads", str(path)], "Git bundle head listing")
    if not any(line.split(maxsplit=1)[0] == commit for line in heads.splitlines() if line):
        raise StageError("Git bundle does not advertise the required commit")
    with tempfile.TemporaryDirectory(prefix="chromamatter-linux-source-verify-") as directory:
        repository = Path(directory) / "verify.git"
        _run_git([git, "init", "--bare", str(repository)], "Git bundle verifier init")
        _run_git([git, "-C", str(repository), "bundle", "verify", str(path)], "Git bundle structural audit")
        _run_git([git, "-C", str(repository), "fetch", "--no-tags", str(path), commit], "Git bundle commit import")
        observed = _run_git(
            [git, "-C", str(repository), "rev-parse", "FETCH_HEAD^{commit}"],
            "Git bundle commit audit",
        ).strip()
        if observed != commit:
            raise StageError("Git bundle imported commit does not match required commit")
        _run_git(
            [git, "-C", str(repository), "fsck", "--strict", "--no-reflogs", commit],
            "Git bundle object audit",
        )


def _tree_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: _portable_key(item.relative_to(root).as_posix())):
        relative = path.relative_to(root).as_posix()
        # SOURCE_PAYLOADS.json records the hash of this file manifest.  Exclude
        # both metadata files from the covered tree to avoid a hash cycle; the
        # release/archive audits bind both files independently.
        if relative in {"SOURCE_STAGE_FILE_MANIFEST.json", "SOURCE_PAYLOADS.json"}:
            continue
        if path.is_symlink():
            raise StageError(f"Source stage contains a symlink: {relative}")
        rows.append(
            {"path": relative, "size": path.stat().st_size, "sha256": evidence.sha256_file(path)}
        )
    return rows


def materialize(
    manifest: dict[str, Any],
    recipe: dict[str, Any],
    source_cache: Path,
    output_directory: Path,
) -> None:
    payloads = validate_recipe(manifest, recipe)
    if output_directory.exists():
        raise StageError("Linux source stage output directory already exists")
    if not source_cache.is_dir() or source_cache.is_symlink():
        raise StageError("Linux source cache must be a real directory")
    verified: list[tuple[dict[str, Any], Path]] = []
    for payload in payloads:
        source = source_cache / payload["cache_filename"]
        if not source.is_file() or source.is_symlink():
            raise StageError(f"Linux source cache payload is missing or unsafe: {source.name}")
        if evidence.sha256_file(source) != payload["sha256"]:
            raise StageError(f"Linux source cache SHA-256 mismatch: {source.name}")
        identity = payload["source_identity"]
        if identity["payload_format"] == "git-bundle":
            verify_git_bundle(source, identity["source_commit"])
        verified.append((payload, source))

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_directory.name}.", dir=output_directory.parent))
    try:
        for payload, source in verified:
            destination = temporary / PurePosixPath(payload["stage_path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if evidence.sha256_file(destination) != payload["sha256"]:
                raise StageError(f"Linux source payload changed while staging: {source.name}")
        staged_manifest = dict(manifest)
        staged_manifest["stage_status"] = "staged-verified"
        evidence.write_json(temporary / "CORRESPONDING_SOURCE_MANIFEST.json", staged_manifest)
        for name in TEMPLATE_NAMES:
            source = evidence.TEMPLATE_ROOT / name
            if not source.is_file() or source.is_symlink():
                raise StageError(f"Canonical Linux source instruction is missing: {name}")
            evidence.write_text(temporary / name, source.read_text(encoding="utf-8"))
        file_manifest = {
            "schema": "chromamatter.linux-source-stage-file-manifest.v1",
            **{key: manifest[key] for key in IDENTITY_KEYS},
            "files": _tree_manifest(temporary),
        }
        evidence.write_json(temporary / "SOURCE_STAGE_FILE_MANIFEST.json", file_manifest)
        stage_manifest_sha256 = evidence.sha256_file(
            temporary / "SOURCE_STAGE_FILE_MANIFEST.json"
        )
        evidence.write_json(
            temporary / "SOURCE_PAYLOADS.json",
            {
                "schema": "chromamatter.linux-corresponding-source-payloads.v1",
                "source_commit": manifest["source_commit"],
                "inventory_sha256": manifest["inventory_sha256"],
                "lock_sha256": manifest["lock_sha256"],
                "catalog_sha256": manifest["catalog_sha256"],
                "closure_contract_sha256": manifest[
                    "closure_contract_sha256"
                ],
                "source_stage_manifest_sha256": stage_manifest_sha256,
                "status": "staged-verified",
                "payloads": payloads,
            },
        )
        validate_stage(temporary)
        os.replace(temporary, output_directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def validate_stage(stage: Path) -> dict[str, Any]:
    if not stage.is_dir() or stage.is_symlink():
        raise StageError("Linux source stage must be a real directory")
    for name in TEMPLATE_NAMES:
        canonical = evidence.TEMPLATE_ROOT / name
        staged = stage / name
        if (
            not canonical.is_file()
            or canonical.is_symlink()
            or not staged.is_file()
            or staged.is_symlink()
            or staged.read_bytes() != canonical.read_bytes()
        ):
            raise StageError(f"Linux source-stage instruction is missing or modified: {name}")
    manifest = evidence.read_json(stage / "CORRESPONDING_SOURCE_MANIFEST.json")
    payloads = evidence.read_json(stage / "SOURCE_PAYLOADS.json")
    files = evidence.read_json(stage / "SOURCE_STAGE_FILE_MANIFEST.json")
    if manifest.get("status") != "complete" or manifest.get("stage_status") != "staged-verified":
        raise StageError("Linux source stage manifest is not complete and verified")
    if payloads.get("schema") != "chromamatter.linux-corresponding-source-payloads.v1" or payloads.get("status") != "staged-verified":
        raise StageError("Linux source payload evidence is invalid")
    if files.get("schema") != "chromamatter.linux-source-stage-file-manifest.v1":
        raise StageError("Linux source stage file manifest schema is invalid")
    for key in IDENTITY_KEYS:
        values = {manifest.get(key), payloads.get(key), files.get(key)}
        if len(values) != 1:
            raise StageError(f"Linux source stage identity mismatch: {key}")
    stage_manifest_sha256 = evidence.sha256_file(
        stage / "SOURCE_STAGE_FILE_MANIFEST.json"
    )
    if payloads.get("source_stage_manifest_sha256") != stage_manifest_sha256:
        raise StageError("Linux source payload evidence does not bind the stage manifest")
    expected_rows = files.get("files")
    if not isinstance(expected_rows, list) or not expected_rows:
        raise StageError("Linux source stage file manifest is empty")
    expected = {row.get("path"): row for row in expected_rows if isinstance(row, dict)}
    actual_rows = _tree_manifest(stage)
    actual = {row["path"]: row for row in actual_rows}
    if expected != actual:
        raise StageError("Linux source stage file manifest does not match staged bytes")
    listed_payloads = payloads.get("payloads")
    if not isinstance(listed_payloads, list) or not listed_payloads:
        raise StageError("Linux source stage has no verified payload list")
    for payload in listed_payloads:
        path = stage / PurePosixPath(payload["stage_path"])
        if not path.is_file() or path.is_symlink() or evidence.sha256_file(path) != payload["sha256"]:
            raise StageError(f"Linux source stage payload mismatch: {payload.get('source_id')}")
    return {
        "source_commit": manifest["source_commit"],
        "inventory_sha256": manifest["inventory_sha256"],
        "lock_sha256": manifest["lock_sha256"],
        "catalog_sha256": manifest["catalog_sha256"],
        "closure_contract_sha256": manifest["closure_contract_sha256"],
        "source_stage_manifest_sha256": stage_manifest_sha256,
        "file_count": len(actual),
    }


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--source-cache", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    try:
        manifest = evidence.read_json(arguments.manifest.resolve(strict=True))
        recipe = evidence.read_json(arguments.recipe.resolve(strict=True))
        materialize(manifest, recipe, arguments.source_cache, arguments.output_directory)
    except (evidence.EvidenceError, StageError, OSError) as exc:
        print(f"Linux corresponding-source stage refused: {exc}", file=os.sys.stderr)
        return 3
    print(f"Linux corresponding-source stage written: {arguments.output_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
