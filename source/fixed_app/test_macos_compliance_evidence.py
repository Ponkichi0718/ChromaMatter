from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tooling" / "generate_macos_compliance_evidence.py"
CATALOG = REPO_ROOT / "tooling" / "macos_compliance_components.json"
LOCK = REPO_ROOT / "source" / "fixed_app" / "requirements-build-macos-arm64.lock"
EVIDENCE = REPO_ROOT / "licenses" / "macos"
SPEC = importlib.util.spec_from_file_location("macos_compliance_evidence", TOOL)
assert SPEC is not None and SPEC.loader is not None
evidence_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence_tool)


def _inventory(*, version: str = "0.17.5", dependency: str = "/usr/lib/libSystem.B.dylib") -> dict:
    return {
        "schema": "chromamatter.macos-app-inventory",
        "schema_version": 1,
        "purpose": "test fixture; not release evidence",
        "bundle": {
            "name": "ChromaMatter-macOS-Alpha.app",
            "info_plist_path": "Contents/Info.plist",
            "identity": {
                "CFBundleExecutable": "ChromaMatter",
                "CFBundleIdentifier": "io.github.ponkichi0718.chromamatter.alpha",
            },
        },
        "counts": {
            "regular_files": 2,
            "symlinks": 0,
            "mach_o_files": 1,
            "packaged_distributions": 1,
        },
        "code_signing": {
            "verify_ok": True,
            "ad_hoc": True,
            "identity_authority_count": 0,
        },
        "regular_files": [
            {
                "path": "Contents/MacOS/ChromaMatter",
                "size": 12,
                "sha256": "a" * 64,
                "mach_o": {
                    "architectures": ["arm64"],
                    "dependencies": [dependency],
                    "file_description": "Mach-O 64-bit executable arm64",
                },
            },
            {
                "path": "Contents/Frameworks/altgraph-0.17.5.dist-info/licenses/LICENSE",
                "size": 10,
                "sha256": "b" * 64,
            },
        ],
        "symlinks": [],
        "packaged_distributions": [
            {
                "name": "altgraph",
                "canonical_name": "altgraph",
                "version": version,
                "dist_info_path": "Contents/Frameworks/altgraph-0.17.5.dist-info",
                "metadata": {},
                "wheel": {"tag": "py2.py3-none-any"},
                "record": {
                    "available": True,
                    "path": "Contents/Frameworks/altgraph-0.17.5.dist-info/RECORD",
                    "size": 10,
                    "sha256": "c" * 64,
                    "entry_count": 1,
                    "invalid_or_absolute_row_count": 0,
                    "entries": [],
                },
                "license_files": [
                    {
                        "path": "Contents/Frameworks/altgraph-0.17.5.dist-info/licenses/LICENSE",
                        "size": 10,
                        "sha256": "b" * 64,
                    }
                ],
                "direct_url_metadata_present": False,
                "provenance_scope": "packaged metadata",
            }
        ],
    }


class MacOSComplianceEvidenceTests(unittest.TestCase):
    def _write_inventory(self, root: Path, payload: dict) -> Path:
        path = root / "inventory.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_catalog_exactly_covers_hash_locked_requirements(self) -> None:
        locked = evidence_tool._parse_lock(LOCK)
        catalog = evidence_tool._read_json(CATALOG)
        normalized = evidence_tool._validate_catalog(catalog, locked)
        self.assertEqual(set(locked), set(normalized))
        self.assertEqual(len(locked), 23)
        self.assertEqual(normalized["tetgen"]["license_declared"], "MIT AND AGPL-3.0-or-later")
        self.assertEqual(
            normalized["shapely"]["license_declared"],
            "BSD-3-Clause AND LGPL-2.1-or-later",
        )

    def test_generator_binds_inventory_without_granting_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inventory = self._write_inventory(root, _inventory())
            output = root / "evidence"
            payloads = evidence_tool.generate_evidence(
                inventory,
                "1" * 40,
                "2026-08-26T00:00:00Z",
            )
            evidence_tool.write_evidence(output, payloads)

            approval = json.loads((output / "DISTRIBUTION_APPROVAL.json").read_text(encoding="utf-8"))
            component_map = json.loads((output / "BINARY_COMPONENT_MAP.json").read_text(encoding="utf-8"))
            sbom = json.loads((output / "SBOM.spdx.json").read_text(encoding="utf-8"))
            sources = json.loads(
                (output / "CORRESPONDING_SOURCE_MANIFEST.json").read_text(encoding="utf-8")
            )

            self.assertEqual(approval["status"], "blocked")
            self.assertFalse(approval["automatic_approval_permitted"])
            self.assertEqual(component_map["status"], "review-required")
            self.assertTrue(component_map["validation"]["mechanically_consistent"])
            self.assertEqual(component_map["native_files"][0]["owner"], "chromamatter")
            self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
            self.assertEqual(sources["status"], "candidate-only")
            self.assertEqual(sources["component_sources"][0]["source_sha256"], "c87b395dd12fabde9c99573a9749d67da8d29ef9de0125c7f536699b4a9bc9e7")
            self.assertIn("BLOCKED", (output / "MACOS_ALPHA_SOURCE_OFFER_STATUS.txt").read_text(encoding="utf-8"))

    def test_generator_fails_on_packaged_version_not_in_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inventory = self._write_inventory(root, _inventory(version="0.17.4"))
            with self.assertRaisesRegex(evidence_tool.EvidenceError, "does not match lock"):
                evidence_tool.generate_evidence(
                    inventory,
                    "1" * 40,
                    "2026-08-26T00:00:00Z",
                )

    def test_non_relocatable_dependency_blocks_component_map(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inventory = self._write_inventory(
                root,
                _inventory(dependency="/opt/unapproved/libexample.dylib"),
            )
            payloads = evidence_tool.generate_evidence(
                inventory,
                "1" * 40,
                "2026-08-26T00:00:00Z",
            )
            component_map = payloads["BINARY_COMPONENT_MAP.json"]
            self.assertEqual(component_map["status"], "blocked")
            self.assertTrue(
                any(
                    issue.startswith("non-relocatable-dependency:")
                    for issue in component_map["validation"]["issues"]
                )
            )

    def test_checked_in_evidence_is_real_candidate_but_fail_closed(self) -> None:
        evidence_tool.validate_generated_evidence(EVIDENCE)
        approval = json.loads((EVIDENCE / "DISTRIBUTION_APPROVAL.json").read_text(encoding="utf-8"))
        component_map = json.loads((EVIDENCE / "BINARY_COMPONENT_MAP.json").read_text(encoding="utf-8"))
        sbom = json.loads((EVIDENCE / "SBOM.spdx.json").read_text(encoding="utf-8"))
        sources = json.loads(
            (EVIDENCE / "CORRESPONDING_SOURCE_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(approval["status"], "blocked")
        self.assertRegex(approval["source_commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(approval["inventory_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(component_map["status"], "review-required")
        self.assertTrue(component_map["validation"]["mechanically_consistent"])
        self.assertEqual(
            component_map["counts"]["mach_o_files"],
            len(component_map["native_files"]),
        )
        self.assertNotIn("files", sbom)
        self.assertEqual(sources["status"], "candidate-only")
        self.assertGreater(len(sources["known_gaps"]), 0)

        ids = [row["SPDXID"] for row in sbom["packages"]]
        self.assertEqual(len(ids), len(set(ids)))
        valid_ids = set(ids) | {"SPDXRef-DOCUMENT"}
        for relation in sbom["relationships"]:
            self.assertIn(relation["spdxElementId"], valid_ids)
            self.assertIn(relation["relatedSpdxElement"], valid_ids)


if __name__ == "__main__":
    unittest.main()
