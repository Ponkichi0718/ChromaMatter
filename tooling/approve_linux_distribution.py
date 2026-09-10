#!/usr/bin/env python3
"""Create an external Linux distribution-approval sidecar.

Approval is possible only after exact compliance evidence, a complete staged
corresponding-source tree, a symlink/mode-preserving fresh-extract archive
audit, and an explicit owner decision all agree byte-for-byte.  The approved
sidecar is intentionally external to the application archive to avoid a
self-referential archive hash.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Sequence


TOOLING = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, TOOLING / filename)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"Cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load("chromamatter_linux_evidence_approval", "generate_linux_compliance_evidence.py")
source_stage = _load("chromamatter_linux_source_stage_approval", "stage_linux_corresponding_source.py")

IDENTITY_KEYS = (
    "source_commit",
    "inventory_sha256",
    "lock_sha256",
    "catalog_sha256",
    "closure_contract_sha256",
)
RELEASE_ARCHIVE_ROOT_NAME = "ChromaMatter-Linux-x86_64-Alpha"
REQUIRED_EVIDENCE_HASHES = (
    *evidence.REQUIRED_OUTPUTS,
    "SOURCE_PAYLOADS.json",
    "SOURCE_STAGE_FILE_MANIFEST.json",
)
REQUIRED_ACKNOWLEDGEMENTS = (
    "technical_alpha_not_general_support",
    "unsigned_binary_disclosed",
    "ubuntu_22_04_x86_64_scope_disclosed",
    "corresponding_source_published_with_binary",
    "relinking_instructions_published_with_binary",
    "physical_u1_validation_limitations_disclosed",
)


class ApprovalError(RuntimeError):
    pass


def _read(path: Path) -> dict[str, Any]:
    try:
        return evidence.read_json(path)
    except evidence.EvidenceError as exc:
        raise ApprovalError(str(exc)) from exc


def _require_identity(payloads: list[tuple[str, dict[str, Any]]]) -> dict[str, str]:
    identity: dict[str, str] = {}
    for key in IDENTITY_KEYS:
        values = {payload.get(key) for _, payload in payloads}
        if len(values) != 1:
            details = {name: payload.get(key) for name, payload in payloads}
            raise ApprovalError(f"Linux approval identity mismatch for {key}: {details}")
        value = values.pop()
        pattern = evidence.COMMIT_RE if key == "source_commit" else evidence.SHA256_RE
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ApprovalError(f"Linux approval identity is malformed: {key}")
        identity[key] = value
    return identity


def approve(
    evidence_directory: Path,
    staged_sources: Path,
    archive_audit_path: Path,
    owner_decision_path: Path,
) -> dict[str, Any]:
    evidence.validate_generated_evidence(evidence_directory)
    inventory = _read(evidence_directory / "LINUX_APP_INVENTORY.json")
    component_map = _read(evidence_directory / "BINARY_COMPONENT_MAP.json")
    sbom = _read(evidence_directory / "SBOM.spdx.json")
    source_manifest = _read(evidence_directory / "CORRESPONDING_SOURCE_MANIFEST.json")
    candidate_approval = _read(evidence_directory / "DISTRIBUTION_APPROVAL.json")
    stage_summary = source_stage.validate_stage(staged_sources)
    staged_payloads = _read(staged_sources / "SOURCE_PAYLOADS.json")
    staged_source_manifest = _read(
        staged_sources / "CORRESPONDING_SOURCE_MANIFEST.json"
    )
    archive_audit = _read(archive_audit_path)
    owner = _read(owner_decision_path)

    if component_map.get("status") != "complete":
        raise ApprovalError("Linux component map is not complete")
    validation = component_map.get("validation")
    if (
        not isinstance(validation, dict)
        or validation.get("mechanically_consistent") is not True
        or validation.get("issues") != []
        or validation.get("native_closure_gaps") != []
    ):
        raise ApprovalError("Linux component map validation still has issues or native gaps")
    if source_manifest.get("status") != "complete" or source_manifest.get("known_gaps") != []:
        raise ApprovalError("Linux corresponding-source manifest is not complete")
    expected_staged_manifest = dict(source_manifest)
    expected_staged_manifest["stage_status"] = "staged-verified"
    if staged_source_manifest != expected_staged_manifest:
        raise ApprovalError(
            "Linux staged corresponding-source manifest differs from release evidence"
        )
    if inventory.get("licence_validation", {}).get("status") != "passed":
        raise ApprovalError("Linux packaged licence validation is not passed")
    if sbom.get("spdxVersion") != "SPDX-2.3":
        raise ApprovalError("Linux SBOM is not SPDX 2.3")
    if candidate_approval.get("status") != "blocked" or candidate_approval.get("automatic_approval_permitted") is not False:
        raise ApprovalError("Linux candidate approval did not preserve the blocked generator boundary")

    if archive_audit.get("schema") != "chromamatter.linux-release-archive-audit.v1":
        raise ApprovalError("Linux release archive audit schema is unsupported")
    required_archive_facts = {
        "status": "verified-candidate",
        "fresh_extract_parity": True,
        "symlink_parity": True,
        "mode_parity": True,
        "hash_parity": True,
        "path_safety_verified": True,
        "distribution_ready": False,
    }
    for key, expected in required_archive_facts.items():
        if archive_audit.get(key) != expected:
            raise ApprovalError(f"Linux release archive audit gate failed: {key}")
    if archive_audit.get("candidate_approval_status") != "blocked":
        raise ApprovalError("Linux archive was not created from a blocked candidate approval")
    archive_sha256 = archive_audit.get("archive_sha256")
    if not isinstance(archive_sha256, str) or not evidence.SHA256_RE.fullmatch(archive_sha256):
        raise ApprovalError("Linux archive audit has no exact archive SHA-256")
    if not isinstance(archive_audit.get("archive_size"), int) or archive_audit["archive_size"] <= 0:
        raise ApprovalError("Linux archive audit has no positive archive size")
    if archive_audit.get("root_name") != RELEASE_ARCHIVE_ROOT_NAME:
        raise ApprovalError("Linux archive audit has an unexpected application root")

    identity = _require_identity(
        [
            ("component_map", component_map),
            ("source_manifest", source_manifest),
            ("candidate_approval", candidate_approval),
            ("source_payloads", staged_payloads),
            ("archive_audit", archive_audit),
            ("owner_decision", owner),
        ]
    )
    if any(stage_summary.get(key) != identity[key] for key in IDENTITY_KEYS):
        raise ApprovalError("Linux staged source identity differs from release evidence")
    if archive_audit.get("source_stage_manifest_sha256") != stage_summary[
        "source_stage_manifest_sha256"
    ]:
        raise ApprovalError("Linux archive audit does not bind the exact source stage")

    evidence_hashes = archive_audit.get("evidence_hashes")
    if not isinstance(evidence_hashes, dict):
        raise ApprovalError("Linux archive audit has no evidence hash map")
    evidence_paths = {
        name: evidence_directory / name for name in evidence.REQUIRED_OUTPUTS
    }
    evidence_paths.update(
        {
        "SOURCE_PAYLOADS.json": staged_sources / "SOURCE_PAYLOADS.json",
        "SOURCE_STAGE_FILE_MANIFEST.json": staged_sources
        / "SOURCE_STAGE_FILE_MANIFEST.json",
        }
    )
    if set(evidence_hashes) != set(REQUIRED_EVIDENCE_HASHES):
        raise ApprovalError(
            "Linux archive audit evidence hash coverage mismatch; "
            f"missing={sorted(set(REQUIRED_EVIDENCE_HASHES) - set(evidence_hashes))}, "
            f"extra={sorted(set(evidence_hashes) - set(REQUIRED_EVIDENCE_HASHES))}"
        )
    for name, path in evidence_paths.items():
        expected = evidence_hashes.get(name)
        if not isinstance(expected, str) or not evidence.SHA256_RE.fullmatch(expected):
            raise ApprovalError(f"Linux archive audit evidence hash is invalid: {name}")
        if evidence.sha256_file(path) != expected:
            raise ApprovalError(f"Linux archive audit evidence hash mismatch: {name}")

    if owner.get("schema") != "chromamatter.linux-owner-distribution-decision.v1":
        raise ApprovalError("Linux owner decision schema is unsupported")
    if owner.get("decision") != "approved" or owner.get("scope") != "linux-x86_64-technical-alpha":
        raise ApprovalError("Linux owner decision is not an exact technical-alpha approval")
    archive_audit_sha256 = evidence.sha256_file(archive_audit_path)
    bindings = {
        "archive_sha256": archive_sha256,
        "archive_audit_sha256": archive_audit_sha256,
        "source_stage_manifest_sha256": stage_summary["source_stage_manifest_sha256"],
    }
    for key, expected in bindings.items():
        if owner.get(key) != expected:
            raise ApprovalError(f"Linux owner decision does not bind exact {key}")
    acknowledgements = owner.get("acknowledgements")
    if not isinstance(acknowledgements, dict):
        raise ApprovalError("Linux owner decision has no acknowledgements")
    missing_acknowledgements = [
        key for key in REQUIRED_ACKNOWLEDGEMENTS if acknowledgements.get(key) is not True
    ]
    if missing_acknowledgements:
        raise ApprovalError(
            "Linux owner decision is missing acknowledgements: "
            + ", ".join(missing_acknowledgements)
        )

    return {
        "schema": "chromamatter.linux-distribution-approval.v1",
        "status": "approved",
        **identity,
        "automatic_approval_permitted": False,
        "scope": "linux-x86_64-technical-alpha",
        "archive_sha256": archive_sha256,
        "archive_size": archive_audit["archive_size"],
        "archive_audit_sha256": archive_audit_sha256,
        "source_stage_manifest_sha256": stage_summary["source_stage_manifest_sha256"],
        "owner_decision_sha256": evidence.sha256_file(owner_decision_path),
        "evidence_hashes": evidence_hashes,
        "owner_approval": {
            "approved": True,
            "decision_record_schema": owner["schema"],
            "acknowledgements": acknowledgements,
        },
        "distribution_ready": True,
        "failure_contract": (
            "Approval applies only to the exact archive/source/evidence hashes in this sidecar. "
            "Any byte change requires a new archive audit and owner decision."
        ),
    }


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-directory", required=True, type=Path)
    parser.add_argument("--source-stage", required=True, type=Path)
    parser.add_argument("--archive-audit", required=True, type=Path)
    parser.add_argument("--owner-decision", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    try:
        if arguments.output.exists():
            raise ApprovalError("Linux approved sidecar output already exists")
        result = approve(
            arguments.evidence_directory,
            arguments.source_stage,
            arguments.archive_audit.resolve(strict=True),
            arguments.owner_decision.resolve(strict=True),
        )
        evidence.write_json(arguments.output, result)
    except (
        ApprovalError,
        evidence.EvidenceError,
        source_stage.StageError,
        source_stage.evidence.EvidenceError,
        OSError,
    ) as exc:
        print(f"Linux distribution approval refused: {exc}", file=os.sys.stderr)
        return 3
    print(f"Linux distribution approval written: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
