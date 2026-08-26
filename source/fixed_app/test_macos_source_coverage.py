import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLING = ROOT / "tooling"
if str(TOOLING) not in sys.path:
    sys.path.insert(0, str(TOOLING))

import audit_macos_source_coverage as coverage
import stage_macos_corresponding_source as source_stage


PLAN_PATH = TOOLING / "macos_source_coverage_plan.json"
CATALOG_PATH = TOOLING / "macos_compliance_components.json"
LOCK_PATH = Path(__file__).with_name("requirements-build-macos-arm64.lock")
TEST_COMMIT = "a" * 40
TEST_SHA = "b" * 64


class MacOSSourceCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.locked = coverage.parse_lock(LOCK_PATH)

    def _inventory(self, paths):
        absent = {
            coverage.canonical_name(item["distribution"])
            for item in self.plan["intentionally_not_packaged"]
        }
        packaged = [
            {
                "canonical_name": name,
                "version": fact["version"],
            }
            for name, fact in sorted(self.locked.items())
            if name not in absent
        ]
        regular = [
            {
                "mach_o": {
                    "architectures": ["arm64"],
                    "dependencies": ["/usr/lib/libSystem.B.dylib"],
                },
                "path": path,
                "sha256": TEST_SHA,
                "size": 32,
            }
            for path in paths
        ]
        return {
            "schema": "chromamatter.macos-app-inventory",
            "schema_version": 1,
            "packaged_distributions": packaged,
            "regular_files": regular,
        }

    def _audit(self, inventory, plan=None):
        return coverage.audit(
            inventory=inventory,
            inventory_sha256=TEST_SHA,
            locked=self.locked,
            lock_sha256=TEST_SHA,
            catalog=self.catalog,
            catalog_sha256=TEST_SHA,
            plan=self.plan if plan is None else plan,
            plan_sha256=TEST_SHA,
            source_commit=TEST_COMMIT,
            wheel_paths=(),
        )

    def _stage_report(self, source_records=None, native_records=None):
        return {
            "engineering_gate": {
                "blockers": [],
                "engineering_gate_passed": True,
                "legal_conclusion": False,
                "status": "coverage-complete",
            },
            "fixed_native_source_materials": native_records or [],
            "schema": coverage.REPORT_SCHEMA,
            "source_records": source_records or [],
        }

    def _archive_record(self, name, digest):
        return {
            "distribution": name,
            "identity_kind": "archive-sha256",
            "source_sha256": digest,
            "source_url": f"https://example.invalid/{name}.tar.gz",
        }

    def _archive_payload(self, name, digest, *, cache_filename=None, stage_path=None):
        return {
            "cache_filename": cache_filename or f"{name}.tar.gz",
            "sha256": digest,
            "source_id": f"distribution:{name}",
            "source_identity": {
                "identity_kind": "archive-sha256",
                "payload_format": "source-archive",
                "source_sha256": digest,
                "source_url": f"https://example.invalid/{name}.tar.gz",
            },
            "stage_path": stage_path or f"Sources/{name}.tar.gz",
        }

    @staticmethod
    def _complete_stage_plan(payloads):
        return {
            "stage_policy": {
                "payloads": payloads,
                "status": "complete-recipe-reviewed",
            }
        }

    def test_every_declared_native_group_maps_uniquely(self):
        paths = [group["path_prefixes"][0] for group in self.plan["native_groups"]]
        report = self._audit(self._inventory(paths))
        facts = report["mach_o_coverage"]
        self.assertEqual(len(paths), facts["mapped_count"])
        self.assertEqual([], facts["unmatched_paths"])
        self.assertEqual([], facts["ambiguous_paths"])
        self.assertFalse(report["engineering_gate"]["engineering_gate_passed"])

    def test_unmapped_native_path_fails_closed(self):
        report = self._audit(self._inventory(["Contents/Frameworks/unknown/libmystery.dylib"]))
        self.assertEqual(
            ["Contents/Frameworks/unknown/libmystery.dylib"],
            report["mach_o_coverage"]["unmatched_paths"],
        )
        self.assertIn("unmapped-native-paths", report["engineering_gate"]["blockers"])

    def test_overlapping_native_path_fails_closed(self):
        plan = copy.deepcopy(self.plan)
        duplicate = copy.deepcopy(plan["native_groups"][0])
        duplicate["id"] = "overlap-probe"
        plan["native_groups"].append(duplicate)
        path = plan["native_groups"][0]["path_prefixes"][0]
        report = self._audit(self._inventory([path]), plan)
        self.assertEqual(1, len(report["mach_o_coverage"]["ambiguous_paths"]))
        self.assertIn("ambiguous-native-paths", report["engineering_gate"]["blockers"])

    def test_declared_release_status_cannot_override_evidence(self):
        plan = copy.deepcopy(self.plan)
        plan["declared_status"] = "release-approved"
        path = plan["native_groups"][0]["path_prefixes"][0]
        report = self._audit(self._inventory([path]), plan)
        gate = report["engineering_gate"]
        self.assertEqual("release-approved", gate["plan_declared_status_ignored"])
        self.assertEqual("candidate-only", gate["status"])
        self.assertFalse(gate["engineering_gate_passed"])
        self.assertFalse(gate["legal_conclusion"])

    def test_catalog_must_cover_every_locked_distribution(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["distributions"].pop("tetgen")
        with self.assertRaises(coverage.CoverageError):
            coverage.validate_catalog(catalog, self.locked)

    def test_wheel_filename_and_hash_are_fail_closed(self):
        expected = next(
            item for item in self.plan["wheel_artifacts"] if item["distribution"] == "pytetwild"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / expected["filename"]
            path.write_bytes(b"not the locked wheel")
            with self.assertRaises(coverage.CoverageError):
                coverage.inspect_wheel(path, expected, [])

    def test_macho_lc_id_and_current_version_are_parsed(self):
        name = b"@rpath/libexample.3.dylib\0"
        command_size = (24 + len(name) + 7) & ~7
        command = struct.pack(
            "<IIIIII",
            coverage.LC_ID_DYLIB,
            command_size,
            24,
            0,
            (3 << 16) | (7 << 8) | 9,
            (3 << 16),
        ) + name
        command += b"\0" * (command_size - len(command))
        header = struct.pack(
            "<IiiIIIII",
            0xFEEDFACF,
            0x0100000C,
            0,
            6,
            1,
            len(command),
            0,
            0,
        )
        fact = coverage.macho_load_identity(header + command)
        self.assertEqual("@rpath/libexample.3.dylib", fact["lc_id_dylib"]["name"])
        self.assertEqual("3.7.9", fact["lc_id_dylib"]["current_version"])
        self.assertEqual("3.0.0", fact["lc_id_dylib"]["compatibility_version"])

    def test_required_wheel_inspection_absence_is_a_blocker(self):
        path = self.plan["native_groups"][0]["path_prefixes"][0]
        report = self._audit(self._inventory([path]))
        self.assertEqual(["pymeshlab", "pytetwild"], report["wheel_inspection"]["missing_required"])
        self.assertIn(
            "required-wheel-inspections-missing", report["engineering_gate"]["blockers"]
        )

    def test_source_stager_refuses_candidate_without_creating_output(self):
        path = self.plan["native_groups"][0]["path_prefixes"][0]
        report = self._audit(self._inventory([path]))
        with self.assertRaises(source_stage.StageError):
            source_stage.require_stageable(report, self.plan)

    def test_audit_output_cannot_replace_an_input(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory_path = Path(directory) / "inventory.json"
            inventory_path.write_text("{}\n", encoding="utf-8")
            original = inventory_path.read_bytes()
            exit_code = coverage.main(
                [
                    "--inventory",
                    str(inventory_path),
                    "--source-commit",
                    TEST_COMMIT,
                    "--output",
                    str(inventory_path),
                ]
            )
            self.assertEqual(2, exit_code)
            self.assertEqual(original, inventory_path.read_bytes())

    def test_candidate_stage_rejects_nested_audit_report_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "corresponding-source"
            inventory_path = root / "inventory.json"
            inventory_path.write_text(
                json.dumps(self._inventory([self.plan["native_groups"][0]["path_prefixes"][0]])),
                encoding="utf-8",
            )
            exit_code = source_stage.main(
                [
                    "--inventory",
                    str(inventory_path),
                    "--source-commit",
                    TEST_COMMIT,
                    "--source-cache",
                    str(root / "cache"),
                    "--output-directory",
                    str(output),
                    "--audit-report",
                    str(output / "audit.json"),
                ]
            )
            self.assertEqual(3, exit_code)
            self.assertFalse(output.exists())

    def test_stage_payload_must_match_audited_source_identity(self):
        record = self._archive_record("example", TEST_SHA)
        payload = self._archive_payload("example", TEST_SHA)
        payload["source_identity"]["source_url"] = "https://example.invalid/unrelated.tar.gz"
        with self.assertRaises(source_stage.StageError):
            source_stage.require_stageable(
                self._stage_report([record]), self._complete_stage_plan([payload])
            )

    def test_archive_payload_sha_must_be_the_audited_source_sha(self):
        record = self._archive_record("example", TEST_SHA)
        payload = self._archive_payload("example", TEST_SHA)
        payload["sha256"] = "c" * 64
        with self.assertRaises(source_stage.StageError):
            source_stage.require_stageable(
                self._stage_report([record]), self._complete_stage_plan([payload])
            )

    def test_casefolded_cache_filename_collision_is_rejected(self):
        first = self._archive_record("first", TEST_SHA)
        second = self._archive_record("second", "c" * 64)
        payloads = [
            self._archive_payload("first", TEST_SHA, cache_filename="Source.tar"),
            self._archive_payload("second", "c" * 64, cache_filename="source.TAR"),
        ]
        with self.assertRaises(source_stage.StageError):
            source_stage.require_stageable(
                self._stage_report([first, second]), self._complete_stage_plan(payloads)
            )

    def test_unicode_normalized_stage_path_collision_is_rejected(self):
        first = self._archive_record("first", TEST_SHA)
        second = self._archive_record("second", "c" * 64)
        payloads = [
            self._archive_payload("first", TEST_SHA, stage_path="Sources/caf\u00e9.tar"),
            self._archive_payload("second", "c" * 64, stage_path="sources/cafe\u0301.tar"),
        ]
        with self.assertRaises(source_stage.StageError):
            source_stage.require_stageable(
                self._stage_report([first, second]), self._complete_stage_plan(payloads)
            )

    def test_archive_stage_materializes_only_hash_bound_source(self):
        data = b"exact source archive bytes"
        digest = hashlib.sha256(data).hexdigest()
        record = self._archive_record("example", digest)
        payload = self._archive_payload("example", digest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            (cache / payload["cache_filename"]).write_bytes(data)
            output = root / "stage"
            source_stage.materialize(
                self._stage_report([record]),
                self._complete_stage_plan([payload]),
                cache,
                output,
            )
            self.assertEqual(data, (output / payload["stage_path"]).read_bytes())
            manifest = json.loads((output / "SOURCE_PAYLOADS.json").read_text(encoding="utf-8"))
            self.assertEqual(f"distribution:example", manifest["payloads"][0]["source_id"])

    def test_arbitrary_file_cannot_satisfy_git_commit_source(self):
        if shutil.which("git") is None:
            self.skipTest("git is unavailable")
        data = b"not a git bundle"
        digest = hashlib.sha256(data).hexdigest()
        record = {
            "distribution": "example",
            "identity_kind": "git-commit",
            "source_commit": TEST_COMMIT,
            "source_url": "https://example.invalid/example.git",
        }
        payload = {
            "cache_filename": "example.bundle",
            "sha256": digest,
            "source_id": "distribution:example",
            "source_identity": {
                "identity_kind": "git-commit",
                "payload_format": "git-bundle",
                "source_commit": TEST_COMMIT,
                "source_url": "https://example.invalid/example.git",
            },
            "stage_path": "Sources/example.bundle",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            (cache / payload["cache_filename"]).write_bytes(data)
            output = root / "stage"
            with self.assertRaises(source_stage.StageError):
                source_stage.materialize(
                    self._stage_report([record]),
                    self._complete_stage_plan([payload]),
                    cache,
                    output,
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
