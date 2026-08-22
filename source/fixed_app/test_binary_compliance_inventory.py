from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tooling" / "generate_binary_compliance_inventory.py"
LOCK = REPO_ROOT / "source" / "fixed_app" / "requirements-build.lock"
REQUIREMENTS = (
    REPO_ROOT / "source" / "fixed_app" / "requirements-build.txt"
)
BOOTSTRAP = REPO_ROOT / "BOOTSTRAP_WINDOWS.ps1"
BUILD = REPO_ROOT / "BUILD_AND_TEST.ps1"
SPEC = REPO_ROOT / "source" / "fixed_app" / "TripoSpectrumMapper_fixed.spec"
THIRD_PARTY_INDEX = REPO_ROOT / "licenses" / "THIRD_PARTY_LICENSES.txt"
APACHE_LICENSE = REPO_ROOT / "licenses" / "LICENSE_RESVG_APACHE_2.0.txt"


class BinaryComplianceInventoryTests(unittest.TestCase):
    maxDiff = None

    def _fixture(self, root: Path, *, unknown_native: bool = False) -> None:
        internal = root / "_internal"
        dist_info = internal / "demo_package-1.2.3.dist-info"
        licenses = root / "licenses"
        dist_info.mkdir(parents=True)
        licenses.mkdir(parents=True)
        (root / "ChromaMatter.exe").write_bytes(b"synthetic-app\0")
        (internal / "demo_native.pyd").write_bytes(b"synthetic-extension\0")
        (internal / "api-ms-win-core-demo-l1-1-0.dll").write_bytes(
            b"synthetic-ucrt-forwarder\0"
        )
        (internal / "plain-data.bin").write_bytes(b"plain-data\n")
        if unknown_native:
            (internal / "mystery.dll").write_bytes(b"unmapped-native\0")
        (licenses / "LICENSE_APP.txt").write_text(
            "SPDX-License-Identifier: GPL-3.0-or-later\n",
            encoding="utf-8",
        )
        (dist_info / "METADATA").write_text(
            "\n".join(
                (
                    "Metadata-Version: 2.4",
                    "Name: demo-package",
                    "Version: 1.2.3",
                    "License-Expression: MIT",
                    "Project-URL: Source, https://example.invalid/demo-source",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (dist_info / "RECORD").write_text(
            "\n".join(
                (
                    "demo_native.pyd,,",
                    "demo_package-1.2.3.dist-info/METADATA,,",
                    "demo_package-1.2.3.dist-info/RECORD,,",
                    "",
                )
            ),
            encoding="utf-8",
        )

    def _run(self, root: Path, destination: Path) -> subprocess.CompletedProcess:
        destination.mkdir()
        return subprocess.run(
            (
                sys.executable,
                str(TOOL),
                "--package-root",
                str(root),
                "--sbom-output",
                str(destination / "SBOM.cdx.json"),
                "--component-map-output",
                str(destination / "BINARY_COMPONENT_MAP.json"),
            ),
            check=False,
            capture_output=True,
            text=True,
        )

    def test_fixture_is_complete_deterministic_and_path_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package)
            first = base / "first"
            second = base / "second"
            first_result = self._run(package, first)
            second_result = self._run(package, second)

            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            for filename in ("SBOM.cdx.json", "BINARY_COMPONENT_MAP.json"):
                first_bytes = (first / filename).read_bytes()
                second_bytes = (second / filename).read_bytes()
                self.assertEqual(first_bytes, second_bytes)
                self.assertNotIn(str(base).encode(), first_bytes)

            component_map = json.loads(
                (first / "BINARY_COMPONENT_MAP.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(component_map["validation"]["passed"])
            self.assertEqual(
                component_map["validation"]["unmapped_native_files"], []
            )
            self.assertEqual(
                component_map["validation"]["file_count"],
                len(component_map["files"]),
            )
            rows = {item["path"]: item for item in component_map["files"]}
            component_ids = {
                item["id"] for item in component_map["components"]
            }
            demo = rows["_internal/demo_native.pyd"]
            self.assertEqual(demo["package_owners"], ["pypi:demo-package@1.2.3"])
            self.assertEqual(demo["components"], ["pypi:demo-package@1.2.3"])
            self.assertEqual(demo["mapping_basis"], "dist-info-record")
            self.assertEqual(
                rows["_internal/api-ms-win-core-demo-l1-1-0.dll"][
                    "mapping_basis"
                ],
                "explicit-system-runtime-allowlist",
            )
            for path, row in rows.items():
                self.assertLessEqual(set(row["components"]), component_ids)
                self.assertEqual(
                    row["sha256"],
                    hashlib.sha256((package / Path(path)).read_bytes()).hexdigest(),
                )

            sbom = json.loads(
                (first / "SBOM.cdx.json").read_text(encoding="utf-8")
            )
            self.assertEqual(sbom["bomFormat"], "CycloneDX")
            self.assertEqual(sbom["specVersion"], "1.5")
            file_refs = {
                item["bom-ref"]
                for item in sbom["components"]
                if item["type"] == "file"
            }
            self.assertEqual(file_refs, {f"file:{path}" for path in rows})
            component_refs = {
                item["bom-ref"] for item in sbom["components"]
            } | {sbom["metadata"]["component"]["bom-ref"]}
            for dependency in sbom["dependencies"]:
                self.assertIn(dependency["ref"], component_refs)
                self.assertLessEqual(set(dependency["dependsOn"]), component_refs)

    def test_unmapped_native_file_writes_report_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package, unknown_native=True)
            destination = base / "report"
            result = self._run(package, destination)

            self.assertEqual(result.returncode, 2)
            self.assertIn("_internal/mystery.dll", result.stderr)
            component_map = json.loads(
                (destination / "BINARY_COMPONENT_MAP.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(component_map["validation"]["passed"])
            self.assertEqual(
                component_map["validation"]["unmapped_native_files"],
                ["_internal/mystery.dll"],
            )

    def test_frozen_entry_point_and_high_impact_native_licenses_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package)
            pymeshlab = package / "_internal" / "pymeshlab"
            shapely_libs = package / "_internal" / "shapely.libs"
            pymeshlab.mkdir()
            shapely_libs.mkdir()
            (pymeshlab / "Qt5Core.dll").write_bytes(b"synthetic-qt")
            (pymeshlab / "IFXCore.dll").write_bytes(b"synthetic-u3d")
            (pymeshlab / "tbb12.dll").write_bytes(b"synthetic-onetbb")
            (shapely_libs / "geos-c.dll").write_bytes(b"synthetic-geos")

            destination = base / "report"
            result = self._run(package, destination)
            self.assertEqual(result.returncode, 0, result.stderr)

            component_map = json.loads(
                (destination / "BINARY_COMPONENT_MAP.json").read_text(
                    encoding="utf-8"
                )
            )
            rows = {row["path"]: row for row in component_map["files"]}
            self.assertEqual(
                rows["ChromaMatter.exe"]["components"],
                ["chromamatter", "pyinstaller"],
            )
            self.assertEqual(
                rows["ChromaMatter.exe"]["mapping_basis"],
                "frozen-application-entry-point",
            )
            licenses = {
                component["id"]: component["license"]
                for component in component_map["components"]
            }
            self.assertEqual(licenses["qt"], "LGPL-3.0-only")
            self.assertEqual(licenses["geos"], "LGPL-2.1-or-later")
            self.assertEqual(licenses["u3d"], "Apache-2.0")
            self.assertEqual(licenses["onetbb-pymeshlab"], "Apache-2.0")
            self.assertEqual(
                licenses["pyinstaller"],
                "(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0",
            )
            one_tbb = next(
                component
                for component in component_map["components"]
                if component["id"] == "onetbb-pymeshlab"
            )
            self.assertEqual(one_tbb["version"], "2021.11.0")
            self.assertEqual(
                one_tbb["source"],
                "https://github.com/uxlfoundation/oneTBB/tree/v2021.11.0",
            )
            self.assertTrue(
                {"embree", "onetbb-pymeshlab"}.issubset(
                    rows["_internal/pymeshlab/tbb12.dll"]["components"]
                ),
                rows["_internal/pymeshlab/tbb12.dll"]["components"],
            )

            sbom = json.loads(
                (destination / "SBOM.cdx.json").read_text(encoding="utf-8")
            )
            sbom_refs = {
                component["bom-ref"] for component in sbom["components"]
            }
            self.assertIn("component:pyinstaller", sbom_refs)

    def test_spec_and_index_bundle_runtime_license_texts(self) -> None:
        spec = SPEC.read_text(encoding="utf-8")
        index = THIRD_PARTY_INDEX.read_text(encoding="utf-8")
        self.assertIn('Path(sys.base_prefix) / "LICENSE.txt"', spec)
        self.assertIn('"licenses/cpython"', spec)
        self.assertIn(
            '"pyinstaller-6.20.0.dist-info/licenses/COPYING.txt"', spec
        )
        self.assertIn("_internal/licenses/cpython/LICENSE.txt", index)
        self.assertIn("_internal/licenses/pyinstaller/COPYING.txt", index)
        apache = APACHE_LICENSE.read_text(encoding="utf-8")
        self.assertIn("Apache License", apache)
        self.assertIn("Version 2.0, January 2004", apache)
        self.assertIn("_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt", index)
        for component_notice in (
            "Qt ANGLE runtime",
            "Mesa llvmpipe runtime",
            "Intel Embree 4.3.3",
            "oneTBB 2021.11",
            "Xerces-C++ 3.2.4",
            "lib3mf 2.4.1",
            "GMP 5.0.1",
            "MPFR 3.0.0",
            "MPIR 3.0.0",
            "libE57Format 3.1.1",
            "GLEW 2.2.0",
            "lib3ds 1.3.0",
            "U3D 1.5.2",
            "muparser 2.3.5",
            "OpenSSL 3.0.21",
            "SQLite 3.50.4",
            "libffi runtime ABI 8",
            "zlib 1.3.1",
            "Microsoft Universal C Runtime 10.0.19041.1",
        ):
            with self.subTest(component_notice=component_notice):
                self.assertIn(component_notice, index)
        self.assertIn("Pillow 11.2.1\n  License expression: HPND", index)
        self.assertNotIn("NOASSERTION", index)

    def test_system_runtime_allowlist_is_limited_to_internal_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package)
            nested = package / "_internal" / "untrusted"
            nested.mkdir()
            (nested / "api-ms-win-core-fake-l1-1-0.dll").write_bytes(b"fake")
            destination = base / "report"

            result = self._run(package, destination)

            self.assertEqual(result.returncode, 2)
            component_map = json.loads(
                (destination / "BINARY_COMPONENT_MAP.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(
                "_internal/untrusted/api-ms-win-core-fake-l1-1-0.dll",
                component_map["validation"]["unmapped_native_files"],
            )

    def test_outputs_must_be_distinct_and_outside_package_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package)
            same_output = base / "same.json"
            same = subprocess.run(
                (
                    sys.executable,
                    str(TOOL),
                    "--package-root",
                    str(package),
                    "--sbom-output",
                    str(same_output),
                    "--component-map-output",
                    str(same_output),
                ),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(same.returncode, 0)
            self.assertFalse(same_output.exists())

            inside = subprocess.run(
                (
                    sys.executable,
                    str(TOOL),
                    "--package-root",
                    str(package),
                    "--sbom-output",
                    str(package / "SBOM.cdx.json"),
                    "--component-map-output",
                    str(base / "map.json"),
                ),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(inside.returncode, 0)
            self.assertFalse((package / "SBOM.cdx.json").exists())

    def test_reparse_directory_is_reported_and_never_traversed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package)
            outside = base / "outside"
            outside.mkdir()
            (outside / "hidden.dll").write_bytes(b"must-not-be-scanned")
            link = package / "_internal" / "linked-directory"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except OSError as error:
                if os.name != "nt":
                    self.skipTest(f"Directory symlink is unavailable: {error}")
                junction = subprocess.run(
                    ("cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if junction.returncode != 0:
                    self.skipTest(
                        "Neither a directory symlink nor a junction is available: "
                        f"{error}; {junction.stderr.strip()}"
                    )

            destination = base / "report"
            result = self._run(package, destination)
            self.assertEqual(result.returncode, 2)
            component_map = json.loads(
                (destination / "BINARY_COMPONENT_MAP.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                component_map["validation"]["reparse_points_not_traversed"],
                ["_internal/linked-directory"],
            )
            paths = {item["path"] for item in component_map["files"]}
            self.assertNotIn("_internal/linked-directory/hidden.dll", paths)

    def test_build_lock_covers_declared_requirements_and_build_tools(self) -> None:
        requirement_pattern = re.compile(
            r"^([A-Za-z0-9_.-]+)==([^\s]+)$", re.MULTILINE
        )
        lock_pattern = re.compile(
            r"^([A-Za-z0-9_.-]+)==([^\s]+) \\\n"
            r"    --hash=sha256:([0-9a-f]{64})$",
            re.MULTILINE,
        )
        declared = {
            (name.casefold().replace("_", "-"), version)
            for name, version in requirement_pattern.findall(
                REQUIREMENTS.read_text(encoding="utf-8")
            )
        }
        locked_rows = lock_pattern.findall(LOCK.read_text(encoding="utf-8"))
        locked = {
            (name.casefold().replace("_", "-"), version)
            for name, version, _sha256 in locked_rows
        }
        self.assertEqual(locked, declared | {("pip", "26.2.1"), ("wheel", "0.46.3")})
        self.assertEqual(len(locked_rows), len(locked))
        critical_hashes = {name.casefold(): sha256 for name, _version, sha256 in locked_rows}
        self.assertEqual(
            critical_hashes["pymeshlab"],
            "25eb2578dd6c4d1b2e0253fb3b4f8f7895e8bb4f3f1236832db0ab58e6a44998",
        )
        self.assertEqual(
            critical_hashes["tetgen"],
            "21982452c4c91d7fdd69101eaf18a3d3cb55c158571bcade04a83ed617305a28",
        )

    def test_windows_scripts_enforce_locked_runtime_and_inventory(self) -> None:
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        build = BUILD.read_text(encoding="utf-8")
        self.assertIn('$version -ne "3.13.14"', bootstrap)
        self.assertIn("--require-hashes", bootstrap)
        self.assertIn("--only-binary=:all:", bootstrap)
        self.assertIn("requirements-build.lock", bootstrap)
        self.assertNotIn("pip install --upgrade pip", bootstrap)
        self.assertIn('$pythonVersion -ne "3.13.14"', build)
        self.assertIn("generate_binary_compliance_inventory.py", build)
        self.assertIn("SBOM.cdx.json", build)
        self.assertIn("BINARY_COMPONENT_MAP.json", build)


if __name__ == "__main__":
    unittest.main()
