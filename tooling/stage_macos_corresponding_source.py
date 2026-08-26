#!/usr/bin/env python3
"""Fail-closed preflight for a macOS corresponding-source stage.

The current macOS plan deliberately has unresolved native closure and relink
gaps.  This command therefore refuses to create an output directory.  It is
the safety boundary for a later materializer: only a mechanically complete
coverage report *and* an explicitly complete stage recipe may pass.

It never downloads sources and never converts a candidate report into a
coverage-complete one.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence
import unicodedata

import audit_macos_source_coverage as coverage


class StageError(RuntimeError):
    pass


def _portable_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _portable_stage_key(value: str) -> tuple[str, ...]:
    return tuple(_portable_key(part) for part in PurePosixPath(value).parts)


def _validate_cache_filename(value) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in (".", "..")
        or "/" in value
        or "\\" in value
        or Path(value).name != value
    ):
        raise StageError("source stage cache filename is unsafe")
    return value


def _expected_source_identities(report):
    if report.get("schema") != coverage.REPORT_SCHEMA:
        raise StageError("coverage report schema is unsupported")
    gate = report.get("engineering_gate")
    if (
        not isinstance(gate, dict)
        or gate.get("engineering_gate_passed") is not True
        or gate.get("status") != "coverage-complete"
        or gate.get("blockers") != []
        or gate.get("legal_conclusion") is not False
    ):
        blockers = gate.get("blockers", []) if isinstance(gate, dict) else []
        raise StageError("coverage is candidate-only: " + ", ".join(map(str, blockers)))

    expected = {}

    def add(records, prefix, id_field):
        if not isinstance(records, list):
            raise StageError(f"coverage report {prefix} source records are invalid")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get(id_field), str):
                raise StageError(f"coverage report {prefix} source record is invalid")
            source_id = f"{prefix}:{record[id_field]}"
            if source_id in expected:
                raise StageError(f"duplicate coverage source id: {source_id}")
            source_url = record.get("source_url")
            identity_kind = record.get("identity_kind")
            if not isinstance(source_url, str) or not source_url.startswith("https://"):
                raise StageError(f"coverage source URL is not fixed: {source_id}")
            identity = {
                "identity_kind": identity_kind,
                "source_url": source_url,
            }
            if identity_kind == "archive-sha256":
                digest = record.get("source_sha256")
                if not isinstance(digest, str) or not coverage.SHA256_RE.fullmatch(digest):
                    raise StageError(f"coverage source archive is not fixed: {source_id}")
                identity["source_sha256"] = digest
                identity["payload_format"] = "source-archive"
            elif identity_kind in ("git-commit", "audit-source-commit"):
                commit = record.get("source_commit")
                if not isinstance(commit, str) or not coverage.COMMIT_RE.fullmatch(commit):
                    raise StageError(f"coverage git source is not fixed: {source_id}")
                identity["source_commit"] = commit
                identity["payload_format"] = "git-bundle"
            else:
                raise StageError(f"coverage source identity kind is unsupported: {source_id}")
            expected[source_id] = identity

    add(report.get("source_records"), "distribution", "distribution")
    add(report.get("fixed_native_source_materials"), "native", "id")
    if not expected:
        raise StageError("coverage report has no fixed source identities")
    return expected


def require_stageable(report, plan):
    expected = _expected_source_identities(report)
    policy = plan.get("stage_policy")
    if not isinstance(policy, dict) or policy.get("status") != "complete-recipe-reviewed":
        raise StageError("the source staging recipe is not complete and reviewed")
    payloads = policy.get("payloads")
    if not isinstance(payloads, list) or not payloads:
        raise StageError("the reviewed source staging recipe has no payloads")
    required_ids = set(expected)
    covered_ids: set[str] = set()
    cache_names: dict[str, str] = {}
    stage_paths: dict[tuple[str, ...], str] = {
        _portable_stage_key("MACOS_SOURCE_COVERAGE_REPORT.json"): "MACOS_SOURCE_COVERAGE_REPORT.json",
        _portable_stage_key("SOURCE_PAYLOADS.json"): "SOURCE_PAYLOADS.json",
    }
    normalized = []
    for payload in payloads:
        if not isinstance(payload, dict):
            raise StageError("source stage payload entries must be objects")
        cache_filename = _validate_cache_filename(payload.get("cache_filename"))
        cache_key = _portable_key(cache_filename)
        if cache_key in cache_names:
            raise StageError(
                "colliding source cache filenames: "
                f"{cache_names[cache_key]!r} and {cache_filename!r}"
            )
        cache_names[cache_key] = cache_filename
        stage_path = coverage._safe_posix_path(payload.get("stage_path"), "source stage path")
        stage_key = _portable_stage_key(stage_path)
        digest = payload.get("sha256")
        source_id = payload.get("source_id")
        source_identity = payload.get("source_identity")
        if not isinstance(digest, str) or not coverage.SHA256_RE.fullmatch(digest):
            raise StageError(f"source stage payload has no SHA-256: {stage_path}")
        if not isinstance(source_id, str) or source_id not in expected:
            raise StageError(f"source stage payload has an unknown source id: {stage_path}")
        if source_id in covered_ids:
            raise StageError(f"duplicate source stage payload for: {source_id}")
        if not isinstance(source_identity, dict) or source_identity != expected[source_id]:
            raise StageError(
                f"source stage payload is not bound to the audited identity: {source_id}"
            )
        if source_identity["identity_kind"] == "archive-sha256" and digest != source_identity[
            "source_sha256"
        ]:
            raise StageError(f"source archive payload SHA-256 is not its audited SHA: {source_id}")
        for existing_key, existing_path in stage_paths.items():
            common = min(len(stage_key), len(existing_key))
            if stage_key[:common] == existing_key[:common]:
                raise StageError(
                    f"colliding source stage paths: {existing_path!r} and {stage_path!r}"
                )
        stage_paths[stage_key] = stage_path
        covered_ids.add(source_id)
        normalized.append(
            {
                "cache_filename": cache_filename,
                "sha256": digest,
                "source_id": source_id,
                "source_identity": source_identity,
                "stage_path": stage_path,
            }
        )
    if covered_ids != required_ids:
        raise StageError(
            "source stage recipe coverage mismatch; "
            f"missing={sorted(required_ids - covered_ids)}, "
            f"extra={sorted(covered_ids - required_ids)}"
        )
    return sorted(normalized, key=lambda item: item["stage_path"])


def _git_output(command, *, label: str) -> str:
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
        message = (completed.stderr or completed.stdout).strip().splitlines()
        suffix = f": {message[-1]}" if message else ""
        raise StageError(f"{label} failed{suffix}")
    return completed.stdout


def _verify_git_bundle(path: Path, expected_commit: str) -> None:
    git = shutil.which("git")
    if git is None:
        raise StageError("git is required to verify a git-bundle source payload")
    heads = _git_output([git, "bundle", "list-heads", str(path)], label="git bundle head audit")
    if not any(line.split(maxsplit=1)[0] == expected_commit for line in heads.splitlines() if line):
        raise StageError("git bundle does not advertise the audited source commit")
    with tempfile.TemporaryDirectory(prefix="chromamatter-source-bundle-verify-") as directory:
        repository = Path(directory) / "verify.git"
        _git_output([git, "init", "--bare", str(repository)], label="git bundle verifier init")
        _git_output(
            [git, "-C", str(repository), "bundle", "verify", str(path)],
            label="git bundle structural audit",
        )
        _git_output(
            [git, "-C", str(repository), "fetch", "--no-tags", str(path), expected_commit],
            label="git bundle commit import",
        )
        observed = _git_output(
            [git, "-C", str(repository), "rev-parse", "FETCH_HEAD^{commit}"],
            label="git bundle commit audit",
        ).strip()
        if observed != expected_commit:
            raise StageError("git bundle commit does not match the audited source commit")
        _git_output(
            [git, "-C", str(repository), "fsck", "--strict", "--no-reflogs", expected_commit],
            label="git bundle object audit",
        )


def materialize(report, plan, source_cache: Path, output_directory: Path) -> None:
    payloads = require_stageable(report, plan)
    if output_directory.exists():
        raise StageError("output directory already exists")
    if not source_cache.is_dir():
        raise StageError("source cache is not a directory")
    coverage.reject_output_overlap(
        output_directory,
        output_label="source stage output directory",
        inputs=[("source cache", source_cache)],
    )

    verified_sources = []
    for payload in payloads:
        source = source_cache / payload["cache_filename"]
        if not source.is_file() or source.is_symlink():
            raise StageError(f"source cache payload is missing or unsafe: {source.name}")
        if coverage.sha256_file(source) != payload["sha256"]:
            raise StageError(f"source cache SHA-256 mismatch: {source.name}")
        identity = payload["source_identity"]
        if identity["payload_format"] == "git-bundle":
            _verify_git_bundle(source, identity["source_commit"])
        verified_sources.append((payload, source))

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}.", dir=output_directory.parent)
    )
    try:
        for payload, source in verified_sources:
            destination = temporary / PurePosixPath(payload["stage_path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if coverage.sha256_file(destination) != payload["sha256"]:
                raise StageError(f"staged source SHA-256 changed while copying: {source.name}")
        coverage.write_json(temporary / "MACOS_SOURCE_COVERAGE_REPORT.json", report)
        coverage.write_json(
            temporary / "SOURCE_PAYLOADS.json",
            {
                "payloads": payloads,
                "schema": "chromamatter.macos-corresponding-source-payloads.v1",
            },
        )
        os.replace(temporary, output_directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--source-cache", required=True, type=Path)
    parser.add_argument("--lock", type=Path, default=coverage.DEFAULT_LOCK)
    parser.add_argument("--catalog", type=Path, default=coverage.DEFAULT_CATALOG)
    parser.add_argument("--plan", type=Path, default=coverage.DEFAULT_PLAN)
    parser.add_argument("--wheel", action="append", type=Path, default=[])
    parser.add_argument("--audit-report", type=Path)
    return parser.parse_args(argv)


def _validate_cli_paths(arguments) -> None:
    inputs = [
        ("inventory input", arguments.inventory),
        ("lock input", arguments.lock),
        ("catalog input", arguments.catalog),
        ("plan input", arguments.plan),
        ("source cache", arguments.source_cache),
        *((f"wheel input {index}", path) for index, path in enumerate(arguments.wheel, 1)),
    ]
    coverage.reject_output_overlap(
        arguments.output_directory,
        output_label="source stage output directory",
        inputs=inputs,
    )
    if arguments.audit_report is not None:
        coverage.reject_output_overlap(
            arguments.audit_report,
            output_label="coverage audit report output",
            inputs=[*inputs, ("source stage output directory", arguments.output_directory)],
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    try:
        _validate_cli_paths(arguments)
        if arguments.output_directory.exists():
            raise StageError("output directory already exists")
        inventory = coverage.read_json(arguments.inventory)
        plan = coverage.read_json(arguments.plan)
        catalog = coverage.read_json(arguments.catalog)
        locked = coverage.parse_lock(arguments.lock)
        report = coverage.audit(
            inventory=inventory,
            inventory_sha256=coverage.sha256_file(arguments.inventory),
            locked=locked,
            lock_sha256=coverage.sha256_file(arguments.lock),
            catalog=catalog,
            catalog_sha256=coverage.sha256_file(arguments.catalog),
            plan=plan,
            plan_sha256=coverage.sha256_file(arguments.plan),
            source_commit=arguments.source_commit,
            wheel_paths=arguments.wheel,
        )
        if arguments.audit_report is not None:
            coverage.write_json(arguments.audit_report, report)
        materialize(report, plan, arguments.source_cache, arguments.output_directory)
    except (coverage.CoverageError, StageError, OSError) as exc:
        print(f"macOS source stage refused: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
