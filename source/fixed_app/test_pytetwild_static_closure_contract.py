from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tooling.pytetwild_static_closure_contract import (
    ContractError,
    HISTORICAL_PYTETWILD_PYD_SHA256,
    HISTORICAL_PYTETWILD_WHEEL_SHA256,
    RECIPE_REPOSITORY_PATH,
    load_pytetwild_static_closure_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "tooling" / "pytetwild_static_closure.json"
APPLICATION_LOCK_PATH = REPO_ROOT / "source" / "fixed_app" / "requirements-build.lock"


class PyTetWildStaticClosureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def _fixture(self, temporary: str) -> Path:
        root = Path(temporary)
        (root / "tooling").mkdir(parents=True)
        (root / "source" / "fixed_app").mkdir(parents=True)
        shutil.copy2(MANIFEST_PATH, root / "tooling" / MANIFEST_PATH.name)
        frozen_recipe = root / RECIPE_REPOSITORY_PATH
        frozen_recipe.parent.mkdir(parents=True)
        shutil.copy2(REPO_ROOT / RECIPE_REPOSITORY_PATH, frozen_recipe)
        shutil.copy2(
            APPLICATION_LOCK_PATH,
            root / "source" / "fixed_app" / "requirements-build.lock",
        )
        shutil.copytree(
            REPO_ROOT / "source" / "fixed_app" / "licenses" / "pytetwild-closure",
            root / "source" / "fixed_app" / "licenses" / "pytetwild-closure",
        )
        return root

    def _write_manifest(self, root: Path, manifest: dict) -> None:
        (root / "tooling" / "pytetwild_static_closure.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _approved_manifest(self) -> tuple[dict, str, str]:
        manifest = copy.deepcopy(self.manifest)
        wheel_sha256 = "1" * 64
        pyd_sha256 = "2" * 64
        manifest["release_gate"]["status"] = "release-approved"
        manifest["release_gate"]["release_eligible"] = True
        for blocker in manifest["release_gate"]["blockers"]:
            blocker["resolved"] = True
        controlled = manifest["build_binding"]["controlled_rebuild"]
        controlled["status"] = "approved"
        controlled["wheel_sha256"] = wheel_sha256
        controlled["pyd_sha256"] = pyd_sha256
        return manifest, wheel_sha256, pyd_sha256

    def _write_pytetwild_lock(self, root: Path, wheel_sha256: str) -> None:
        (root / "source" / "fixed_app" / "requirements-build.lock").write_text(
            "# exact controlled test lock\n"
            "pytetwild==0.3.0 \\\n"
            f"    --hash=sha256:{wheel_sha256}\n",
            encoding="utf-8",
        )

    def test_current_approved_manifest_binds_controlled_identities(self) -> None:
        contract = load_pytetwild_static_closure_contract()
        self.assertTrue(contract.manifest_claims_release_eligible)
        self.assertTrue(contract.release_eligible)
        self.assertFalse(contract.release_issues)
        self.assertEqual(
            contract.controlled_wheel_sha256,
            "e3b11ac058266d277b0f83448c6023d5da98e731d0d016e461dbce4ebdfd613d",
        )
        self.assertEqual(
            contract.controlled_pyd_sha256,
            "26a091b53279407014899c046691958c9df07e22703576da6a45d68a9be22430",
        )
        self.assertEqual(len(contract.components), 20)
        self.assertEqual(len(contract.source_archives), 15)
        self.assertEqual(len(contract.license_assets), 29)
        self.assertEqual(
            contract.packaged_pyd_path,
            "_internal/pytetwild/PyfTetWildWrapper.pyd",
        )
        self.assertEqual(
            set(contract.packaged_license_paths), set(contract.license_assets)
        )
        self.assertTrue(
            all(
                path.startswith("_internal/licenses/pytetwild-closure/")
                for path in contract.packaged_license_paths.values()
            )
        )

    def test_schema_rejects_unknown_top_level_and_duplicate_json_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            manifest = copy.deepcopy(self.manifest)
            manifest["unexpected"] = True
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ContractError, "manifest members differ"):
                load_pytetwild_static_closure_contract(repository_root=root)

            payload = MANIFEST_PATH.read_text(encoding="utf-8").replace(
                '  "schema_version": 1,',
                '  "schema_version": 1,\n  "schema_version": 1,',
                1,
            )
            (root / "tooling" / MANIFEST_PATH.name).write_text(
                payload, encoding="utf-8"
            )
            with self.assertRaisesRegex(ContractError, "Duplicate JSON member"):
                load_pytetwild_static_closure_contract(repository_root=root)

    def test_recipe_bytes_and_hash_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            recipe = root / RECIPE_REPOSITORY_PATH
            with recipe.open("ab") as stream:
                stream.write(b"\n")
            with self.assertRaisesRegex(ContractError, "recipe byte count changed"):
                load_pytetwild_static_closure_contract(repository_root=root)

    def test_approved_recipe_keeps_attested_historical_identity(self) -> None:
        self.assertEqual(
            self.manifest["build_binding"]["recipe_path"],
            "tooling/recipes/BUILD_PYTETWILD_WINDOWS_20260823.ps1",
        )
        self.assertEqual(self.manifest["build_binding"]["recipe_bytes"], 82572)
        self.assertEqual(
            self.manifest["build_binding"]["recipe_sha256"],
            "d00cc6cdbc61abeaa040dfc81a3dfe7086ac0027685d798ac70f46e14e4360c8",
        )
        load_pytetwild_static_closure_contract(repository_root=REPO_ROOT)

    def test_developer_recipe_cannot_replace_attested_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            developer = root / "tooling" / "BUILD_PYTETWILD_WINDOWS.ps1"
            developer.write_text("# independent developer recipe\n", encoding="utf-8")
            load_pytetwild_static_closure_contract(repository_root=root)
            redirected = copy.deepcopy(self.manifest)
            redirected["build_binding"]["recipe_path"] = (
                "tooling/BUILD_PYTETWILD_WINDOWS.ps1"
            )
            self._write_manifest(root, redirected)
            with self.assertRaisesRegex(ContractError, "recipe_path must be"):
                load_pytetwild_static_closure_contract(repository_root=root)

    def test_same_size_frozen_recipe_tamper_fails_hash_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            recipe = root / RECIPE_REPOSITORY_PATH
            original = recipe.read_bytes()
            recipe.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaisesRegex(ContractError, "recipe SHA-256 changed"):
                load_pytetwild_static_closure_contract(repository_root=root)

    def test_unknown_component_references_fail_closed(self) -> None:
        for field, unknown, expected_message in (
            ("source_archive_ids", "missing-source", "unknown source archives"),
            ("license_asset_ids", "missing-license", "unknown licence assets"),
            ("dependencies", "missing-component", "invalid dependencies"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = self._fixture(temporary)
                manifest = copy.deepcopy(self.manifest)
                manifest["components"]["pytetwild"].setdefault(field, []).append(
                    unknown
                )
                self._write_manifest(root, manifest)
                with self.assertRaisesRegex(ContractError, expected_message):
                    load_pytetwild_static_closure_contract(repository_root=root)

    def test_source_archive_and_complete_component_sets_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            manifest = copy.deepcopy(self.manifest)
            manifest["source_archives"]["pytetwild-source"]["sha256"] = "A" * 64
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ContractError, "lowercase SHA-256"):
                load_pytetwild_static_closure_contract(repository_root=root)

        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            manifest = copy.deepcopy(self.manifest)
            del manifest["components"]["geogram-xatlas"]
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ContractError, "complete conservative static closure"):
                load_pytetwild_static_closure_contract(repository_root=root)

    def test_license_assets_are_confined_and_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            manifest = copy.deepcopy(self.manifest)
            manifest["license_assets"]["pytetwild-license"]["path"] = (
                "source/fixed_app/licenses/../requirements-build.lock"
            )
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ContractError, "canonical relative path"):
                load_pytetwild_static_closure_contract(repository_root=root)

        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            asset = (
                root
                / "source"
                / "fixed_app"
                / "licenses"
                / "pytetwild-closure"
                / "fmt"
                / "LICENSE"
            )
            with asset.open("ab") as stream:
                stream.write(b"x")
            with self.assertRaisesRegex(ContractError, "byte count changed"):
                load_pytetwild_static_closure_contract(repository_root=root)

    def test_release_gate_and_historical_identity_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            manifest = copy.deepcopy(self.manifest)
            manifest["release_gate"]["blockers"][0]["resolved"] = False
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ContractError, "all-resolved"):
                load_pytetwild_static_closure_contract(repository_root=root)

        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            manifest = copy.deepcopy(self.manifest)
            manifest["build_binding"]["historical_audited_package"][
                "disposition"
            ] = "approved"
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ContractError, "disposition changed"):
                load_pytetwild_static_closure_contract(repository_root=root)

    def test_release_approved_contract_binds_exact_application_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            manifest, wheel_sha256, pyd_sha256 = self._approved_manifest()
            self._write_manifest(root, manifest)
            self._write_pytetwild_lock(root, wheel_sha256)
            contract = load_pytetwild_static_closure_contract(repository_root=root)
            self.assertTrue(contract.manifest_claims_release_eligible)
            self.assertTrue(contract.release_eligible)
            self.assertFalse(contract.release_issues)
            self.assertEqual(contract.controlled_wheel_sha256, wheel_sha256)
            self.assertEqual(contract.controlled_pyd_sha256, pyd_sha256)
            self.assertEqual(contract.application_wheel_sha256, wheel_sha256)

    def test_mismatched_application_lock_revokes_effective_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(temporary)
            manifest, _wheel_sha256, _pyd_sha256 = self._approved_manifest()
            self._write_manifest(root, manifest)
            self._write_pytetwild_lock(root, "3" * 64)
            contract = load_pytetwild_static_closure_contract(repository_root=root)
            self.assertTrue(contract.manifest_claims_release_eligible)
            self.assertFalse(contract.release_eligible)
            self.assertEqual(
                contract.release_issue_codes,
                ("application-lock-not-bound-to-controlled-wheel",),
            )

    def test_controlled_identities_cannot_reuse_historical_bytes(self) -> None:
        for field, historical, message in (
            (
                "wheel_sha256",
                HISTORICAL_PYTETWILD_WHEEL_SHA256,
                "excluded historical wheel",
            ),
            (
                "pyd_sha256",
                HISTORICAL_PYTETWILD_PYD_SHA256,
                "excluded historical PYD",
            ),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = self._fixture(temporary)
                manifest, wheel_sha256, _pyd_sha256 = self._approved_manifest()
                manifest["build_binding"]["controlled_rebuild"][field] = historical
                self._write_manifest(root, manifest)
                self._write_pytetwild_lock(
                    root,
                    historical if field == "wheel_sha256" else wheel_sha256,
                )
                with self.assertRaisesRegex(ContractError, message):
                    load_pytetwild_static_closure_contract(repository_root=root)


if __name__ == "__main__":
    unittest.main()
