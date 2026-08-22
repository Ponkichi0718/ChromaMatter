from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import runpy
import tempfile
import unittest
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[2]
IDENTITIES = REPO_ROOT / "tooling" / "pymeshlab_audited_native_identities.json"
APPLICATION_LOCK = Path(__file__).resolve().parent / "requirements-build.lock"
INVENTORY_TOOL = REPO_ROOT / "tooling" / "generate_binary_compliance_inventory.py"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class PyMeshLabAuditedNativeIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(IDENTITIES.read_text(encoding="utf-8"))

    def test_manifest_is_canonical_and_bound_to_application_lock(self) -> None:
        self.assertEqual(self.payload["schema_version"], 1)
        distribution = self.payload["distribution"]
        self.assertEqual(distribution["name"], "pymeshlab")
        self.assertEqual(distribution["version"], "2025.7.post1")
        self.assertRegex(distribution["wheel_sha256"], SHA256)

        lock = APPLICATION_LOCK.read_text(encoding="utf-8")
        self.assertIn("pymeshlab==2025.7.post1", lock)
        self.assertIn(
            f"--hash=sha256:{distribution['wheel_sha256']}",
            lock,
        )

        identities = self.payload["identities"]
        self.assertTrue(identities)
        self.assertEqual(len(identities), 19)
        paths = [item["path"] for item in identities]
        self.assertEqual(paths, sorted(paths, key=lambda value: (value.casefold(), value)))
        self.assertEqual(len(paths), len({path.casefold() for path in paths}))
        for item in identities:
            with self.subTest(path=item["path"]):
                path = PurePosixPath(item["path"])
                self.assertEqual(path.parts[:2], ("_internal", "pymeshlab"))
                self.assertEqual(path.suffix.casefold(), ".dll")
                self.assertGreater(item["size"], 0)
                self.assertRegex(item["sha256"], SHA256)
                components = item["audited_components"]
                self.assertTrue(components)
                self.assertEqual(components, sorted(set(components)))

    def test_installed_locked_wheel_matches_every_audited_identity(self) -> None:
        try:
            distribution = importlib.metadata.distribution("pymeshlab")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("pymeshlab is not installed in this source-test runtime")
        self.assertEqual(distribution.version, self.payload["distribution"]["version"])

        for item in self.payload["identities"]:
            package_relative = PurePosixPath(item["path"]).relative_to("_internal")
            absolute = Path(distribution.locate_file(package_relative))
            with self.subTest(path=item["path"]):
                self.assertTrue(absolute.is_file(), absolute)
                self.assertEqual(absolute.stat().st_size, item["size"])
                self.assertEqual(_sha256(absolute), item["sha256"])

    def test_inventory_maps_audited_children_only_for_exact_identity(self) -> None:
        module = runpy.run_path(str(INVENTORY_TOOL), run_name="inventory_contract")
        scanned_file = module["ScannedFile"]
        mapper = module["explicit_native_mapping"]
        for item in self.payload["identities"]:
            exact = scanned_file(
                item["path"], item["size"], item["sha256"], "native-library"
            )
            components, basis, _system = mapper(exact)
            with self.subTest(path=item["path"], state="exact"):
                self.assertTrue(set(item["audited_components"]).issubset(components))
                self.assertIn("audited-native-identity", basis)

            tampered = scanned_file(
                item["path"], item["size"] + 1, "0" * 64, "native-library"
            )
            tampered_components, tampered_basis, _system = mapper(tampered)
            with self.subTest(path=item["path"], state="tampered"):
                self.assertFalse(
                    set(item["audited_components"]) - {"qt"}
                    & set(tampered_components)
                )
                self.assertNotIn("audited-native-identity", tampered_basis)

            relocated = scanned_file(
                f"_internal/pymeshlab/relocated/{PurePosixPath(item['path']).name}",
                item["size"],
                item["sha256"],
                "native-library",
            )
            relocated_components, relocated_basis, _system = mapper(relocated)
            with self.subTest(path=item["path"], state="relocated"):
                self.assertFalse(
                    set(item["audited_components"]) - {"qt"}
                    & set(relocated_components)
                )
                self.assertNotIn("audited-native-identity", relocated_basis)

    def test_inventory_reports_missing_and_mismatched_audited_identities(self) -> None:
        module = runpy.run_path(str(INVENTORY_TOOL), run_name="inventory_contract")
        first = self.payload["identities"][0]
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / "ChromaMatter.exe").write_bytes(b"fixture")
            native = package / Path(first["path"])
            native.parent.mkdir(parents=True)
            native.write_bytes(b"tampered-audited-native")
            _sbom, component_map = module["build_inventories"](package)

        validation = component_map["validation"]
        self.assertFalse(validation["passed"])
        self.assertEqual(len(validation["mismatched_audited_native_identities"]), 1)
        self.assertEqual(
            validation["mismatched_audited_native_identities"][0]["expected_path"],
            first["path"],
        )
        self.assertEqual(
            len(validation["missing_audited_native_identities"]),
            len(module["AUDITED_NATIVE_IDENTITIES"]) - 1,
        )


if __name__ == "__main__":
    unittest.main()
