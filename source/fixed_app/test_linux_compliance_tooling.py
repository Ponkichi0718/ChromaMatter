from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]
TOOLING = REPOSITORY / "tooling"
LOCK = Path(__file__).resolve().parent / "requirements-build-linux-x86_64.lock"
CATALOG = TOOLING / "linux_compliance_components.json"
CLOSURE_CONTRACT = TOOLING / "linux_native_closure_contract.json"
LINUX_SPEC = Path(__file__).resolve().parent / "TripoSpectrumMapper_linux_x86_64.spec"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, TOOLING / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load("linux_compliance_test_evidence", "generate_linux_compliance_evidence.py")
stage_tool = _load("linux_compliance_test_stage", "stage_linux_corresponding_source.py")
approval_tool = _load("linux_compliance_test_approval", "approve_linux_distribution.py")


def _elf_x86_64() -> bytes:
    header = bytearray(20)
    header[:4] = b"\x7fELF"
    header[4] = 2
    header[5] = 1
    header[6] = 1
    header[18:20] = (62).to_bytes(2, "little")
    return bytes(header) + b"test-linux-elf"


def _audit_text(elf_count: int = 1) -> str:
    return "\n".join(
        (
            "ChromaMatter Linux x86_64 technical-build audit",
            "Application directory: ChromaMatter-Linux-Alpha",
            "In-app display version: 0.9",
            "Build-host glibc: 2.35",
            "Dependency-wheel glibc floor: 2.35",
            f"ELF files checked: {elf_count}",
            "ELF architecture: x86_64 only",
            "Unresolved ELF dependencies: none",
            "Build-host absolute path leakage: none found",
            "Symlink confinement: passed",
            "Private model/toolpath payloads: none",
            "pip direct_url.json files: none",
            "Public or tester distribution approved: no",
            "",
        )
    )


def _make_synthetic_app(root: Path) -> tuple[Path, Path]:
    locked = evidence.parse_lock(LOCK)
    catalog = evidence.read_json(CATALOG)
    components, _ = evidence.validate_catalog(catalog, locked)
    excluded = {evidence.canonical_name(name) for name in catalog["intentionally_not_packaged"]}
    app = root / evidence.APP_DIRECTORY_NAME
    app.mkdir()
    executable = app / evidence.APP_EXECUTABLE
    executable.write_bytes(_elf_x86_64())
    executable.chmod(0o755)
    native_fixture_paths: list[Path] = []
    for owner in evidence.EXPECTED_NATIVE_CLOSURE_OWNERS:
        kind, name = owner.split(":", 1)
        if owner == "python-distribution:pyinstaller":
            continue
        if kind == "python-distribution":
            native_fixture_paths.append(
                app / Path(components[name]["path_prefixes"][0]) / "closure_fixture.so"
            )
        elif name == "cpython-3.13.14-linux-runtime":
            native_fixture_paths.append(
                app / "_internal" / "python3.13" / "closure_fixture.so"
            )
        elif name == "tcl-tk-9.0.4-linux-runtime":
            native_fixture_paths.append(app / "_internal" / "libtcl9.0.so")
        elif name == "bundled-linux-system-library-closure":
            native_fixture_paths.append(app / "_internal" / "libclosure_fixture.so.1")
        else:  # pragma: no cover - exact owner contract guards this branch
            raise AssertionError(f"No synthetic native fixture path for {owner}")
    for path in native_fixture_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_elf_x86_64() + path.as_posix().encode("utf-8"))
    for name in sorted(set(components) - excluded):
        version = components[name]["version"]
        dist_info = app / "_internal" / f"{name}-{version}.dist-info"
        dist_info.mkdir(parents=True)
        (dist_info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
            encoding="utf-8",
        )
        (dist_info / "RECORD").write_text("", encoding="utf-8")
        licence = app / "_internal" / "licenses" / "wheels" / name / "LICENSE"
        licence.parent.mkdir(parents=True, exist_ok=True)
        licence.write_text(f"test licence for {name}\n", encoding="utf-8")
    for required in catalog["required_application_license_globs"]:
        path = app / Path(required)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"test {path.name}\n", encoding="utf-8")
    audit = root / "LINUX_ALPHA_APP_AUDIT.txt"
    audit.write_text(
        _audit_text(len(evidence.EXPECTED_NATIVE_CLOSURE_OWNERS)),
        encoding="utf-8",
    )
    return app, audit


class LinuxComplianceCatalogTests(unittest.TestCase):
    def test_linux_spec_explicitly_excludes_macos_release_notices(self) -> None:
        text = LINUX_SPEC.read_text(encoding="utf-8")
        self.assertIn("MACOS_RELEASE_ONLY_DOCUMENTS", text)
        self.assertIn('"MACOS_ALPHA_COMPLIANCE_NOTICE_EN.txt"', text)
        self.assertIn('"MACOS_ALPHA_COMPLIANCE_NOTICE_JA.txt"', text)
        self.assertIn(
            "WINDOWS_RELEASE_ONLY_DOCUMENTS | MACOS_RELEASE_ONLY_DOCUMENTS",
            text,
        )

    def test_catalog_exactly_covers_linux_lock_and_critical_licences(self) -> None:
        locked = evidence.parse_lock(LOCK)
        catalog = evidence.read_json(CATALOG)
        components, groups = evidence.validate_catalog(catalog, locked)
        self.assertEqual(len(locked), 22)
        self.assertEqual(set(locked), set(components))
        self.assertEqual(
            components["tetgen"]["license_declared"],
            "MIT AND AGPL-3.0-or-later",
        )
        self.assertEqual(
            components["shapely"]["license_declared"],
            "BSD-3-Clause AND LGPL-2.1-or-later",
        )
        self.assertTrue(any(group["id"].startswith("tcl-tk-") for group in groups))
        self.assertTrue(
            any(group["id"] == "bundled-linux-system-library-closure" for group in groups)
        )

    def test_current_catalog_is_honestly_blocked_pending_native_closure(self) -> None:
        catalog = evidence.read_json(CATALOG)
        blocked = [
            name
            for name, row in catalog["distributions"].items()
            if str(row["native_closure_status"]).startswith("blocked-")
        ]
        self.assertIn("pymeshlab", blocked)
        self.assertIn("pytetwild", blocked)
        self.assertIn("shapely", blocked)
        self.assertGreaterEqual(len(blocked), 7)

    def test_native_closure_contract_exactly_covers_16_blocked_owners(self) -> None:
        locked = evidence.parse_lock(LOCK)
        catalog = evidence.read_json(CATALOG)
        components, groups = evidence.validate_catalog(catalog, locked)
        contract = evidence.read_json(CLOSURE_CONTRACT)
        records = evidence.validate_closure_contract(contract, components, groups)
        self.assertEqual(
            set(records), set(evidence.EXPECTED_NATIVE_CLOSURE_OWNERS)
        )
        self.assertEqual(len(records), 16)
        self.assertEqual(contract["contract_status"], "blocked-unverified")
        self.assertTrue(
            all(
                row["verification_status"] == "blocked-unverified"
                and row["proof"] is None
                for row in records.values()
            )
        )

    def test_catalog_status_string_cannot_bypass_closure_contract(self) -> None:
        locked = evidence.parse_lock(LOCK)
        catalog = evidence.read_json(CATALOG)
        catalog["distributions"]["tetgen"]["native_closure_status"] = "complete"
        components, groups = evidence.validate_catalog(catalog, locked)
        contract = evidence.read_json(CLOSURE_CONTRACT)
        with self.assertRaisesRegex(
            evidence.EvidenceError, "declared status differs from catalog"
        ):
            evidence.validate_closure_contract(contract, components, groups)


class LinuxEvidenceGenerationTests(unittest.TestCase):
    def _collect(self, root: Path):
        app, audit = _make_synthetic_app(root)
        locked = evidence.parse_lock(LOCK)
        catalog = evidence.read_json(CATALOG)
        closure_contract = evidence.read_json(CLOSURE_CONTRACT)
        components, groups = evidence.validate_catalog(catalog, locked)
        inventory = evidence.collect_inventory(app, audit, catalog, components, locked)
        payloads = evidence.generate_payloads(
            inventory,
            "1" * 40,
            "2026-08-27T00:00:00Z",
            catalog,
            components,
            groups,
            locked,
            evidence.sha256_file(LOCK),
            evidence.sha256_file(CATALOG),
            closure_contract,
            evidence.sha256_json_payload(closure_contract),
            TOOLING,
        )
        return app, audit, inventory, payloads

    def test_generator_writes_component_map_spdx_and_blocked_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, inventory, payloads = self._collect(root)
            output = root / "evidence"
            evidence.write_evidence(output, payloads)
            evidence.validate_generated_evidence(output)

            component_map = json.loads(
                (output / "BINARY_COMPONENT_MAP.json").read_text(encoding="utf-8")
            )
            sbom = json.loads((output / "SBOM.spdx.json").read_text(encoding="utf-8"))
            sources = json.loads(
                (output / "CORRESPONDING_SOURCE_MANIFEST.json").read_text(encoding="utf-8")
            )
            approval = json.loads(
                (output / "DISTRIBUTION_APPROVAL.json").read_text(encoding="utf-8")
            )
            self.assertEqual(inventory["licence_validation"]["status"], "passed")
            self.assertEqual(component_map["status"], "blocked")
            self.assertEqual(len(component_map["native_closure_proofs"]), 16)
            self.assertTrue(
                any(
                    row["owner"] == "python-distribution:pyinstaller"
                    for row in component_map["native_files"]
                )
            )
            self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
            self.assertEqual(sources["status"], "candidate-only")
            self.assertGreater(len(sources["known_gaps"]), 0)
            self.assertEqual(approval["status"], "blocked")
            self.assertFalse(approval["automatic_approval_permitted"])

            (output / "RELINKING_EN.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(
                evidence.EvidenceError, "template was modified"
            ):
                evidence.validate_generated_evidence(output)

    def test_missing_native_owner_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app, audit = _make_synthetic_app(root)
            (app / "_internal" / "glcontext" / "closure_fixture.so").unlink()
            audit.write_text(_audit_text(15), encoding="utf-8")
            locked = evidence.parse_lock(LOCK)
            catalog = evidence.read_json(CATALOG)
            contract = evidence.read_json(CLOSURE_CONTRACT)
            components, groups = evidence.validate_catalog(catalog, locked)
            inventory = evidence.collect_inventory(
                app, audit, catalog, components, locked
            )
            with self.assertRaisesRegex(
                evidence.EvidenceError, "native-closure owner set changed"
            ):
                evidence.generate_payloads(
                    inventory,
                    "1" * 40,
                    "2026-08-27T00:00:00Z",
                    catalog,
                    components,
                    groups,
                    locked,
                    evidence.sha256_file(LOCK),
                    evidence.sha256_file(CATALOG),
                    contract,
                    evidence.sha256_json_payload(contract),
                    TOOLING,
                )

    def test_component_status_string_alone_cannot_clear_blocked_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, _, payloads = self._collect(root)
            output = root / "evidence"
            evidence.write_evidence(output, payloads)
            component_map = evidence.read_json(
                output / "BINARY_COMPONENT_MAP.json"
            )
            component_map["status"] = "complete"
            evidence.write_json(output / "BINARY_COMPONENT_MAP.json", component_map)
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "cannot be complete while native closures are unverified",
            ):
                evidence.validate_generated_evidence(output)

    def test_verified_closure_with_missing_evidence_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app, audit = _make_synthetic_app(root)
            locked = evidence.parse_lock(LOCK)
            catalog = evidence.read_json(CATALOG)
            contract = evidence.read_json(CLOSURE_CONTRACT)
            components, groups = evidence.validate_catalog(catalog, locked)
            inventory = evidence.collect_inventory(
                app, audit, catalog, components, locked
            )
            owner = "python-distribution:pyinstaller"
            native_files = []
            for row in inventory["regular_files"]:
                if row["elf"] is None:
                    continue
                observed_owner, _ = evidence._native_owner(
                    row["path"], components, groups
                )
                if observed_owner == owner:
                    native_files.append(
                        {
                            key: row[key]
                            for key in ("path", "size", "sha256", "mode")
                        }
                    )
            missing = root / "proofs" / "missing-functional-validation.json"
            native_file_set_sha256 = hashlib.sha256(
                json.dumps(
                    native_files,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            proof_files = {}
            for label in evidence.REQUIRED_CLOSURE_EVIDENCE_FILES:
                path = root / "proofs" / f"{label}.json"
                if label != "functional_validation":
                    path.parent.mkdir(parents=True, exist_ok=True)
                    evidence.write_json(
                        path,
                        {
                            "schema": evidence.CLOSURE_EVIDENCE_SCHEMAS[label],
                            "owner": owner,
                            "status": "verified",
                            "native_file_set_sha256": native_file_set_sha256,
                            "evidence": ["synthetic test evidence"],
                        },
                    )
                    digest = evidence.sha256_file(path)
                else:
                    path = missing
                    digest = "f" * 64
                proof_files[label] = {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": digest,
                }
            record = contract["owners"][owner]
            record["verification_status"] = "verified"
            record["proof"] = {
                "schema": "chromamatter.linux-native-closure-proof.v1",
                "owner": owner,
                "locked_wheel_sha256": locked["pyinstaller"]["wheel_sha256"],
                "native_files": native_files,
                "additional_sources": [],
                "evidence_files": proof_files,
            }
            with self.assertRaisesRegex(
                evidence.EvidenceError, "evidence file is missing or unsafe"
            ):
                evidence.generate_payloads(
                    inventory,
                    "1" * 40,
                    "2026-08-27T00:00:00Z",
                    catalog,
                    components,
                    groups,
                    locked,
                    evidence.sha256_file(LOCK),
                    evidence.sha256_file(CATALOG),
                    contract,
                    evidence.sha256_json_payload(contract),
                    root,
                )

    def test_missing_wheel_licence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app, audit = _make_synthetic_app(root)
            missing = app / "_internal" / "licenses" / "wheels" / "tetgen" / "LICENSE"
            missing.unlink()
            locked = evidence.parse_lock(LOCK)
            catalog = evidence.read_json(CATALOG)
            components, _ = evidence.validate_catalog(catalog, locked)
            with self.assertRaisesRegex(evidence.EvidenceError, "no wheel licence payload"):
                evidence.collect_inventory(app, audit, catalog, components, locked)

    def test_platform_evidence_or_model_payload_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app, audit = _make_synthetic_app(root)
            forbidden = app / "_internal" / "licenses" / "MACOS_ALPHA_NOTICE.txt"
            forbidden.write_text("must not ship\n", encoding="utf-8")
            locked = evidence.parse_lock(LOCK)
            catalog = evidence.read_json(CATALOG)
            components, _ = evidence.validate_catalog(catalog, locked)
            with self.assertRaisesRegex(evidence.EvidenceError, "Forbidden Linux package"):
                evidence.collect_inventory(app, audit, catalog, components, locked)


def _complete_manifest(identity: dict[str, str], payload_sha256: str) -> dict:
    return {
        "schema": "chromamatter.linux-corresponding-source-manifest.v1",
        "status": "complete",
        **identity,
        "known_gaps": [],
        "stage_required": True,
        "stage_status": "not-staged",
        "component_sources": [
            {
                "source_id": "source:test",
                "name": "test-source",
                "version": "1",
                "license_declared": "MIT",
                "identity_kind": "archive-sha256",
                "source_url": "https://example.invalid/test-source.tar.gz",
                "source_sha256": payload_sha256,
                "source_commit": None,
                "required_for_corresponding_source": True,
            }
        ],
    }


def _stage_one_source(root: Path, identity: dict[str, str]) -> Path:
    payload = root / "cache" / "test-source.tar.gz"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(TEST_SOURCE_BYTES)
    digest = evidence.sha256_file(payload)
    manifest = _complete_manifest(identity, digest)
    recipe = {
        "schema": "chromamatter.linux-source-payload-recipe.v1",
        "status": "complete-recipe-reviewed",
        **identity,
        "payloads": [
            {
                "source_id": "source:test",
                "source_identity": {
                    "identity_kind": "archive-sha256",
                    "source_url": "https://example.invalid/test-source.tar.gz",
                    "source_sha256": digest,
                    "payload_format": "source-archive",
                },
                "cache_filename": payload.name,
                "stage_path": "sources/test-source.tar.gz",
                "sha256": digest,
            }
        ],
    }
    stage = root / "source-stage"
    stage_tool.materialize(manifest, recipe, payload.parent, stage)
    stage_tool.validate_stage(stage)
    return stage


TEST_SOURCE_BYTES = b"test corresponding source payload\n"
TEST_SOURCE_SHA256 = hashlib.sha256(TEST_SOURCE_BYTES).hexdigest()


class LinuxCorrespondingSourceStageTests(unittest.TestCase):
    def test_candidate_manifest_cannot_be_staged(self) -> None:
        manifest = _complete_manifest(
            {
                "source_commit": "1" * 40,
                "inventory_sha256": "2" * 64,
                "lock_sha256": "3" * 64,
                "catalog_sha256": "4" * 64,
                "closure_contract_sha256": "5" * 64,
            },
            "5" * 64,
        )
        manifest["status"] = "candidate-only"
        manifest["known_gaps"] = ["missing-source"]
        with self.assertRaisesRegex(stage_tool.StageError, "candidate-only"):
            stage_tool.expected_sources(manifest)

    def test_complete_recipe_materializes_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = {
                "source_commit": "1" * 40,
                "inventory_sha256": "2" * 64,
                "lock_sha256": "3" * 64,
                "catalog_sha256": "4" * 64,
                "closure_contract_sha256": "5" * 64,
            }
            stage = _stage_one_source(root, identity)
            summary = stage_tool.validate_stage(stage)
            self.assertRegex(summary["source_stage_manifest_sha256"], r"^[0-9a-f]{64}$")
            (stage / "sources" / "test-source.tar.gz").write_bytes(b"tampered")
            with self.assertRaisesRegex(stage_tool.StageError, "does not match staged bytes"):
                stage_tool.validate_stage(stage)


def _write_minimal_complete_evidence(root: Path, identity_base: dict[str, str]) -> tuple[Path, dict[str, str]]:
    output = root / "evidence"
    output.mkdir()
    inventory = {
        "schema": "chromamatter.linux-app-inventory.v1",
        "licence_validation": {"status": "passed"},
    }
    evidence.write_json(output / "LINUX_APP_INVENTORY.json", inventory)
    closure_contract = evidence.read_json(CLOSURE_CONTRACT)
    for owner, record in closure_contract["owners"].items():
        record["verification_status"] = "verified"
        record["proof"] = {"owner": owner}
    closure_contract["contract_status"] = "verified"
    evidence.write_json(
        output / "LINUX_NATIVE_CLOSURE_CONTRACT.json", closure_contract
    )
    identity = {
        **identity_base,
        "inventory_sha256": evidence.sha256_file(output / "LINUX_APP_INVENTORY.json"),
        "closure_contract_sha256": evidence.sha256_file(
            output / "LINUX_NATIVE_CLOSURE_CONTRACT.json"
        ),
    }
    evidence.write_json(
        output / "BINARY_COMPONENT_MAP.json",
        {
            "schema": "chromamatter.linux-binary-component-map.v1",
            "status": "complete",
            **identity,
            "native_closure_contract": {
                "schema": closure_contract["schema"],
                "contract_status": "verified",
                "expected_owner_count": 16,
                "expected_owners": list(evidence.EXPECTED_NATIVE_CLOSURE_OWNERS),
                "sha256": identity["closure_contract_sha256"],
            },
            "native_closure_proofs": [
                {
                    "owner": owner,
                    "verification_status": "verified",
                    "effective_closure_status": "verified-rebuild",
                    "proof_bound": True,
                }
                for owner in evidence.EXPECTED_NATIVE_CLOSURE_OWNERS
            ],
            "validation": {
                "mechanically_consistent": True,
                "issues": [],
                "native_closure_gaps": [],
            },
        },
    )
    evidence.write_json(
        output / "SBOM.spdx.json",
        {"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT"},
    )
    evidence.write_json(
        output / "CORRESPONDING_SOURCE_MANIFEST.json",
        _complete_manifest(identity, TEST_SOURCE_SHA256),
    )
    evidence.write_json(
        output / "DISTRIBUTION_APPROVAL.json",
        {
            "schema": "chromamatter.linux-distribution-approval.v1",
            "status": "blocked",
            **identity,
            "automatic_approval_permitted": False,
        },
    )
    for source_name, output_name in evidence.TEMPLATE_OUTPUTS.items():
        (output / output_name).write_bytes(
            (evidence.TEMPLATE_ROOT / source_name).read_bytes()
        )
    evidence.validate_generated_evidence(output)
    return output, identity


class LinuxDistributionApprovalTests(unittest.TestCase):
    def test_final_gate_binds_archive_source_stage_and_owner_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_dir, identity = _write_minimal_complete_evidence(
                root,
                {
                    "source_commit": "1" * 40,
                    "lock_sha256": "3" * 64,
                    "catalog_sha256": "4" * 64,
                },
            )
            stage = _stage_one_source(root / "stage-work", identity)
            stage_summary = stage_tool.validate_stage(stage)
            evidence_hashes = {
                name: evidence.sha256_file(evidence_dir / name)
                for name in evidence.REQUIRED_OUTPUTS
            }
            evidence_hashes.update(
                {
                    "SOURCE_PAYLOADS.json": evidence.sha256_file(
                        stage / "SOURCE_PAYLOADS.json"
                    ),
                    "SOURCE_STAGE_FILE_MANIFEST.json": evidence.sha256_file(
                        stage / "SOURCE_STAGE_FILE_MANIFEST.json"
                    ),
                }
            )
            archive_audit = root / "LINUX_RELEASE_ARCHIVE_AUDIT.json"
            archive_payload = {
                "schema": "chromamatter.linux-release-archive-audit.v1",
                "status": "verified-candidate",
                **identity,
                "archive_sha256": "a" * 64,
                "archive_size": 1234,
                "root_name": approval_tool.RELEASE_ARCHIVE_ROOT_NAME,
                "fresh_extract_parity": True,
                "symlink_parity": True,
                "mode_parity": True,
                "hash_parity": True,
                "path_safety_verified": True,
                "candidate_approval_status": "blocked",
                "distribution_ready": False,
                "source_stage_manifest_sha256": stage_summary[
                    "source_stage_manifest_sha256"
                ],
                "evidence_hashes": evidence_hashes,
            }
            evidence.write_json(archive_audit, archive_payload)
            owner = root / "OWNER_DECISION.json"
            evidence.write_json(
                owner,
                {
                    "schema": "chromamatter.linux-owner-distribution-decision.v1",
                    "decision": "approved",
                    "scope": "linux-x86_64-technical-alpha",
                    **identity,
                    "archive_sha256": archive_payload["archive_sha256"],
                    "archive_audit_sha256": evidence.sha256_file(archive_audit),
                    "source_stage_manifest_sha256": stage_summary[
                        "source_stage_manifest_sha256"
                    ],
                    "acknowledgements": {
                        key: True for key in approval_tool.REQUIRED_ACKNOWLEDGEMENTS
                    },
                },
            )
            result = approval_tool.approve(evidence_dir, stage, archive_audit, owner)
            self.assertEqual(result["status"], "approved")
            self.assertTrue(result["distribution_ready"])
            self.assertEqual(result["archive_sha256"], "a" * 64)

            archive_payload["mode_parity"] = False
            evidence.write_json(archive_audit, archive_payload)
            with self.assertRaisesRegex(approval_tool.ApprovalError, "mode_parity"):
                approval_tool.approve(evidence_dir, stage, archive_audit, owner)


if __name__ == "__main__":
    unittest.main()
