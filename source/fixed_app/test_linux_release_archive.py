from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import unittest


FIXED_APP = Path(__file__).resolve().parent
REPOSITORY = FIXED_APP.parents[1]
sys.path.insert(0, str(REPOSITORY))

import PACKAGE_LINUX_RELEASE as release  # noqa: E402


SOURCE_COMMIT = "a" * 40
LOCK_SHA256 = "b" * 64
CATALOG_SHA256 = "c" * 64
SOURCE_DATE_EPOCH = 1_700_000_000


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_evidence(root: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    evidence = root / "evidence"
    evidence.mkdir()
    inventory = evidence / "LINUX_APP_INVENTORY.json"
    _write_json(
        inventory,
        {
            "schema": release.INVENTORY_SCHEMA,
            "root_name": release.APP_DIRECTORY_NAME,
            "regular_files": [],
            "symlinks": [],
        },
    )
    inventory_sha256 = _sha256(inventory)
    closure_contract = evidence / "LINUX_NATIVE_CLOSURE_CONTRACT.json"
    _write_json(
        closure_contract,
        {
            "schema": release.CLOSURE_CONTRACT_SCHEMA,
            "scope": "linux-x86_64-technical-alpha",
            "contract_status": "verified",
            "expected_owner_count": 16,
            "owners": {},
        },
    )
    identity = {
        "source_commit": SOURCE_COMMIT,
        "inventory_sha256": inventory_sha256,
        "lock_sha256": LOCK_SHA256,
        "catalog_sha256": CATALOG_SHA256,
        "closure_contract_sha256": _sha256(closure_contract),
    }

    _write_json(
        evidence / "BINARY_COMPONENT_MAP.json",
        {
            "schema": release.COMPONENT_MAP_SCHEMA,
            "status": "review-required",
            **identity,
        },
    )
    _write_json(
        evidence / "CORRESPONDING_SOURCE_MANIFEST.json",
        {
            "schema": release.SOURCE_MANIFEST_SCHEMA,
            "status": "candidate",
            **identity,
        },
    )
    _write_json(
        evidence / "DISTRIBUTION_APPROVAL.json",
        {
            "schema": release.APPROVAL_SCHEMA,
            "status": "blocked",
            "automatic_approval_permitted": False,
            **identity,
        },
    )
    _write_json(
        evidence / "SBOM.spdx.json",
        {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "documentNamespace": (
                "https://github.com/Ponkichi0718/ChromaMatter/spdx/linux-alpha/"
                f"{SOURCE_COMMIT}/{inventory_sha256}"
            ),
            "packages": [],
        },
    )
    for name in release.REQUIRED_EVIDENCE:
        path = evidence / name
        if not path.exists():
            path.write_text(f"review evidence: {name}\n", encoding="utf-8")

    source_stage_manifest = root / "source-stage" / "SOURCE_STAGE_FILE_MANIFEST.json"
    _write_json(
        source_stage_manifest,
        {
            "schema": release.SOURCE_STAGE_FILE_MANIFEST_SCHEMA,
            "status": "complete",
            **identity,
            "files": [],
        },
    )
    source_payloads = root / "source-stage" / "SOURCE_PAYLOADS.json"
    _write_json(
        source_payloads,
        {
            "schema": release.SOURCE_PAYLOADS_SCHEMA,
            "status": "staged-verified",
            **identity,
            "source_stage_manifest_sha256": _sha256(source_stage_manifest),
            "payloads": [],
        },
    )
    return evidence, source_payloads, source_stage_manifest, identity


def _make_app(root: Path) -> Path:
    app = root / release.APP_DIRECTORY_NAME
    app.mkdir(mode=0o755)
    executable = app / release.APP_EXECUTABLE_NAME
    executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    data = app / "data.txt"
    data.write_text("payload\n", encoding="utf-8")
    data.chmod(0o644)
    nested = app / "nested"
    nested.mkdir(mode=0o755)
    nested_file = nested / "read-only.txt"
    nested_file.write_text("read only\n", encoding="utf-8")
    nested_file.chmod(0o444)
    if os.name == "posix":
        os.symlink("data.txt", app / "data-link")
    return app


class LinuxReleaseArchiveContractTests(unittest.TestCase):
    def test_required_evidence_is_explicit_and_approval_stays_external(self) -> None:
        self.assertIn("DISTRIBUTION_APPROVAL.json", release.REQUIRED_EVIDENCE)
        self.assertIn(
            "LINUX_NATIVE_CLOSURE_CONTRACT.json", release.REQUIRED_EVIDENCE
        )
        self.assertNotIn("DISTRIBUTION_APPROVAL.json", release.ARCHIVED_EVIDENCE)
        self.assertIn("SOURCE_PAYLOADS.json", release.ARCHIVED_EVIDENCE)
        self.assertIn("SOURCE_STAGE_FILE_MANIFEST.json", release.ARCHIVED_EVIDENCE)
        self.assertEqual(
            release.AUDIT_SCHEMA,
            "chromamatter.linux-release-archive-audit.v1",
        )

    def test_readme_and_launcher_are_beginner_facing_and_non_mutating(self) -> None:
        readme = release._render_readme(SOURCE_COMMIT)
        launcher = release._render_launcher()
        self.assertIn("Ubuntu 22.04 x86_64", readme)
        self.assertIn("tar -xJf", readme)
        self.assertIn("./START_CHROMAMATTER.sh", readme)
        self.assertIn("separate asset", readme)
        self.assertIn(release.FONT_INSTALL_COMMAND, readme)
        self.assertIn(release.FONT_INSTALL_COMMAND, launcher)
        self.assertIn("dpkg-query", launcher)
        self.assertIn('[[ -n "${DISPLAY:-}" ]]', launcher)
        self.assertIn('exec "$APP" "$@"', launcher)
        self.assertNotIn("sudo apt-get update\n", launcher)
        self.assertNotIn("apt-get install -y\n", launcher)
        for package in release.FONT_PACKAGES:
            with self.subTest(package=package):
                self.assertIn(package, launcher)

    def test_evidence_gate_rejects_a_missing_required_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            evidence, payloads, stage_manifest, _ = _make_evidence(root)
            (evidence / "SBOM.spdx.json").unlink()
            with self.assertRaisesRegex(release.ReleaseArchiveError, "SBOM.spdx.json"):
                release._validate_evidence(
                    evidence, payloads, stage_manifest, SOURCE_COMMIT
                )

    def test_evidence_gate_rejects_cross_document_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            evidence, payloads, stage_manifest, _ = _make_evidence(root)
            component = evidence / "BINARY_COMPONENT_MAP.json"
            payload = json.loads(component.read_text(encoding="utf-8"))
            payload["lock_sha256"] = "d" * 64
            _write_json(component, payload)
            with self.assertRaisesRegex(release.ReleaseArchiveError, "identity mismatch"):
                release._validate_evidence(
                    evidence, payloads, stage_manifest, SOURCE_COMMIT
                )

    def test_evidence_gate_rejects_unbound_source_stage_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            evidence, payloads, stage_manifest, _ = _make_evidence(root)
            stage_payload = json.loads(stage_manifest.read_text(encoding="utf-8"))
            stage_payload["files"] = [{"path": "unexpected"}]
            _write_json(stage_manifest, stage_payload)
            with self.assertRaisesRegex(
                release.ReleaseArchiveError, "does not bind SOURCE_STAGE"
            ):
                release._validate_evidence(
                    evidence, payloads, stage_manifest, SOURCE_COMMIT
                )

    def test_lexical_symlink_validation_rejects_escape_and_absolute_target(self) -> None:
        with self.assertRaisesRegex(release.ReleaseArchiveError, "escapes"):
            release._lexically_resolve_link(Path("a"), "../../outside")
        with self.assertRaisesRegex(release.ReleaseArchiveError, "Unsafe"):
            release._lexically_resolve_link(Path("a"), "/outside")

    def test_archive_parser_rejects_parent_traversal_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "malicious.tar.xz"
            with tarfile.open(archive, "w:xz", format=tarfile.PAX_FORMAT) as handle:
                outer = tarfile.TarInfo(release.ARCHIVE_ROOT_NAME)
                outer.type = tarfile.DIRTYPE
                outer.mode = 0o755
                outer.uid = outer.gid = 0
                outer.mtime = SOURCE_DATE_EPOCH
                handle.addfile(outer)
                bad = tarfile.TarInfo(
                    f"{release.ARCHIVE_ROOT_NAME}/../outside.txt"
                )
                bad.mode = 0o644
                bad.uid = bad.gid = 0
                bad.mtime = SOURCE_DATE_EPOCH
                body = b"outside"
                bad.size = len(body)
                handle.addfile(bad, io.BytesIO(body))
            manifest = {
                "root_mode": "0755",
                "entries": [],
                "tree_sha256": "unused",
            }
            with self.assertRaisesRegex(release.ReleaseArchiveError, "Unsafe"):
                release._inspect_archive(
                    archive,
                    manifest,
                    release.ARCHIVE_ROOT_NAME,
                    SOURCE_DATE_EPOCH,
                )


@unittest.skipUnless(
    sys.platform.startswith("linux")
    and platform.machine().casefold() == "x86_64"
    and shutil.which("tar") is not None,
    "requires Linux x86_64 and GNU tar",
)
class LinuxReleaseArchiveIntegrationTests(unittest.TestCase):
    def test_candidate_round_trip_preserves_hashes_modes_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            app = _make_app(root)
            evidence, payloads, stage_manifest, identity = _make_evidence(root)
            archive = root / "ChromaMatter-Linux-x86_64-Alpha.tar.xz"
            audit_path = root / release.ARCHIVE_AUDIT_NAME

            audit = release.create_candidate(
                app_dir=app,
                evidence_dir=evidence,
                source_payloads_manifest=payloads,
                source_stage_file_manifest=stage_manifest,
                archive=archive,
                audit=audit_path,
                source_date_epoch=SOURCE_DATE_EPOCH,
                expected_source_commit=SOURCE_COMMIT,
            )
            self.assertTrue(archive.is_file())
            self.assertTrue(audit_path.is_file())
            self.assertEqual(audit["status"], "verified-candidate")
            self.assertFalse(audit["distribution_ready"])
            self.assertTrue(audit["fresh_extract_parity"])
            self.assertTrue(audit["mode_parity"])
            self.assertTrue(audit["symlink_parity"])
            self.assertEqual(audit["source_commit"], identity["source_commit"])
            self.assertGreaterEqual(audit["fresh_extract"]["counts"]["symlink"], 1)

            verified = release.verify_candidate(
                archive=archive, audit_path=audit_path
            )
            self.assertEqual(verified["archive_sha256"], _sha256(archive))

            with tarfile.open(archive, "r:xz") as handle:
                members = {member.name.rstrip("/"): member for member in handle}
            launcher = members[
                f"{release.ARCHIVE_ROOT_NAME}/START_CHROMAMATTER.sh"
            ]
            read_only = members[
                f"{release.ARCHIVE_ROOT_NAME}/{release.APP_DIRECTORY_NAME}/nested/read-only.txt"
            ]
            link = members[
                f"{release.ARCHIVE_ROOT_NAME}/{release.APP_DIRECTORY_NAME}/data-link"
            ]
            self.assertEqual(launcher.mode & 0o7777, 0o755)
            self.assertEqual(read_only.mode & 0o7777, 0o444)
            self.assertTrue(link.issym())
            self.assertEqual(link.linkname, "data.txt")
            self.assertNotIn(
                f"{release.ARCHIVE_ROOT_NAME}/compliance/DISTRIBUTION_APPROVAL.json",
                members,
            )

            approved = {
                "schema": release.APPROVAL_SCHEMA,
                "status": "approved",
                **identity,
                "archive_sha256": _sha256(archive),
                "archive_audit_sha256": _sha256(audit_path),
                "source_stage_manifest_sha256": _sha256(stage_manifest),
                "owner_approval": {
                    "approved": True,
                    "decision_record_schema": (
                        "chromamatter.linux-owner-distribution-decision.v1"
                    ),
                    "acknowledgements": {"test-contract": True},
                },
            }
            approval_path = root / "DISTRIBUTION_APPROVAL.approved.json"
            _write_json(approval_path, approved)
            publication = release.verify_publish(
                archive=archive,
                audit_path=audit_path,
                approval_path=approval_path,
            )
            self.assertEqual(publication["status"], "approved-for-bound-artifacts")

    def test_candidate_creation_refuses_to_overwrite_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            app = _make_app(root)
            evidence, payloads, stage_manifest, _ = _make_evidence(root)
            archive = root / "candidate.tar.xz"
            archive.write_bytes(b"already here")
            with self.assertRaisesRegex(release.ReleaseArchiveError, "overwrite"):
                release.create_candidate(
                    app_dir=app,
                    evidence_dir=evidence,
                    source_payloads_manifest=payloads,
                    source_stage_file_manifest=stage_manifest,
                    archive=archive,
                    audit=root / release.ARCHIVE_AUDIT_NAME,
                    source_date_epoch=SOURCE_DATE_EPOCH,
                    expected_source_commit=SOURCE_COMMIT,
                )


if __name__ == "__main__":
    unittest.main()
