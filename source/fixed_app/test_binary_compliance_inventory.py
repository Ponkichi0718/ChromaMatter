from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


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
PYTETWILD_STATIC_CLOSURE = json.loads(
    (REPO_ROOT / "tooling" / "pytetwild_static_closure.json").read_text(
        encoding="utf-8"
    )
)
APACHE_LICENSE = REPO_ROOT / "licenses" / "LICENSE_RESVG_APACHE_2.0.txt"
PYMESHLAB_IDENTITIES = json.loads(
    (REPO_ROOT / "tooling" / "pymeshlab_audited_native_identities.json").read_text(
        encoding="utf-8"
    )
)
QT_STATIC_COMPONENTS = json.loads(
    (REPO_ROOT / "tooling" / "qt_static_components.json").read_text(
        encoding="utf-8"
    )
)
COMPONENT_LICENSE_FILES = (
    "LICENSE_APP.txt",
    "LICENSE_CPYTHON_BZIP2.txt",
    "LICENSE_CPYTHON_EXPAT.txt",
    "LICENSE_CPYTHON_LIBMPDEC.txt",
    "LICENSE_CPYTHON_XZ.txt",
    "LICENSE_LIB3MF.txt",
    "LICENSE_LIB3MF_CPP_BASE64.txt",
    "LICENSE_LIB3MF_FAST_FLOAT.txt",
    "LICENSE_LIB3MF_LIBZIP.txt",
    "LICENSE_LIB3MF_ZLIB.txt",
    "LICENSE_LLVM_3_6_2.txt",
    "LICENSE_MESA_12_0_RC2.html",
    "LICENSE_GLEW_2_2_0.txt",
    "LICENSE_LIBE57FORMAT_3_1_1.md",
    "LICENSE_LIBSPATIALINDEX_2_1_0.txt",
    "LICENSE_MUPARSER_2_3_5.txt",
    "LICENSE_QT_ANGLE.txt",
    "LICENSE_QT_LGPL_3_0.txt",
    "LICENSE_U3D.txt",
    "LICENSE_U3D_IJG_JPEG.txt",
    "LICENSE_U3D_LIBPNG.txt",
    "LICENSE_U3D_NICK_BOBIC_QUATERNION.txt",
    "LICENSE_U3D_WCMATCH.txt",
    "LICENSE_U3D_ZLIB.txt",
    "NOTICE_MESA_LLVM.txt",
    "NOTICE_QT.txt",
    "NOTICE_SQLITE_PUBLIC_DOMAIN.txt",
    "NOTICE_U3D_ADDITIONAL.txt",
    "NOTICE_U3D_FNVHASH.txt",
    "NOTICE_U3D_GRAPHICS_GEMS_IV.txt",
    "NOTICE_U3D_SHEWCHUK_PREDICATES.txt",
    "NOTICE_XERCES_C_3_2_4.txt",
    "GPL-3.0.txt",
    "LGPL-2.1.txt",
    "LGPL-3.0.txt",
    "LICENSE_RESVG_APACHE_2.0.txt",
)

WHEEL_LICENSE_FILES = (
    ("numpy", "numpy-2.5.1.dist-info/licenses/LICENSE.txt", "numpy/LICENSE.txt"),
    ("scipy", "scipy-1.18.0.dist-info/LICENSE.txt", "scipy/LICENSE.txt"),
    ("pillow", "pillow-11.2.1.dist-info/licenses/LICENSE", "pillow/LICENSE"),
    ("pyinstaller", "pyinstaller-6.20.0.dist-info/licenses/COPYING.txt", "pyinstaller/COPYING.txt"),
    ("pymeshlab", "pymeshlab-2025.7.post1.dist-info/licenses/LICENSE", "pymeshlab/LICENSE"),
    ("pytetwild", "pytetwild-0.3.0.dist-info/licenses/LICENSE", "pytetwild/LICENSE"),
    ("tetgen", "tetgen-0.8.3.dist-info/licenses/LICENSE", "tetgen/LICENSE"),
    ("tetgen", "tetgen-0.8.3.dist-info/licenses/src/tetgen-license", "tetgen/tetgen-license"),
    ("shapely", "shapely-2.1.2.dist-info/licenses/LICENSE.txt", "shapely/LICENSE.txt"),
    ("shapely", "shapely-2.1.2.dist-info/licenses/LICENSE_GEOS", "shapely/LICENSE_GEOS"),
    ("msvc-runtime", "msvc_runtime-14.44.35112.dist-info/licenses/LICENSE", "msvc-runtime/LICENSE"),
    ("manifold3d", "manifold3d-3.5.2.dist-info/licenses/LICENSE", "manifold3d/LICENSE"),
    ("mapbox-earcut", "mapbox_earcut-2.0.0.dist-info/licenses/LICENSE.md", "mapbox-earcut/LICENSE.md"),
    ("rtree", "rtree-1.4.1.dist-info/licenses/LICENSE.txt", "rtree/LICENSE.txt"),
    ("moderngl", "moderngl-5.12.0.dist-info/LICENSE", "moderngl/LICENSE"),
    ("glcontext", "glcontext-3.0.0.dist-info/LICENSE", "glcontext/LICENSE"),
    ("trimesh", "trimesh-5.0.0.dist-info/licenses/LICENSE.md", "trimesh/LICENSE.md"),
)


class BinaryComplianceInventoryTests(unittest.TestCase):
    maxDiff = None

    def _fixture(self, root: Path, *, unknown_native: bool = False) -> None:
        internal = root / "_internal"
        dist_info = internal / "trimesh-5.0.0.dist-info"
        dist_info.mkdir(parents=True)
        (root / "ChromaMatter.exe").write_bytes(b"synthetic-app\0")
        (internal / "trimesh_native.pyd").write_bytes(b"synthetic-extension\0")
        (internal / "plain-data.bin").write_bytes(b"plain-data\n")
        if unknown_native:
            (internal / "mystery.dll").write_bytes(b"unmapped-native\0")
        (dist_info / "METADATA").write_text(
            "\n".join(
                (
                    "Metadata-Version: 2.4",
                    "Name: trimesh",
                    "Version: 5.0.0",
                    "License-Expression: MIT",
                    "Project-URL: Source, https://github.com/mikedh/trimesh",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (dist_info / "RECORD").write_text(
            "\n".join(
                (
                    "trimesh_native.pyd,,",
                    "trimesh-5.0.0.dist-info/METADATA,,",
                    "trimesh-5.0.0.dist-info/RECORD,,",
                    "",
                )
            ),
            encoding="utf-8",
        )
        self._install_base_license_assets(root)

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

    @staticmethod
    def _distribution_file(distribution: str, relative: str) -> Path:
        path = Path(
            importlib.metadata.distribution(distribution).locate_file(relative)
        ).resolve()
        if not path.is_file():
            raise AssertionError(f"Missing test distribution asset: {path}")
        return path

    def _install_base_license_assets(self, root: Path) -> None:
        destination = root / "_internal" / "licenses"
        destination.mkdir(parents=True, exist_ok=True)
        for filename in ("LICENSE_APP.txt",):
            (destination / filename).write_bytes(
                (REPO_ROOT / "licenses" / filename).read_bytes()
            )
        for distribution, relative, target in WHEEL_LICENSE_FILES:
            if distribution not in {"pyinstaller", "trimesh"}:
                continue
            output = destination / Path(target)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(
                self._distribution_file(distribution, relative).read_bytes()
            )

    def _install_component_license_assets(self, root: Path) -> None:
        destination = root / "_internal" / "licenses"
        destination.mkdir(parents=True, exist_ok=True)
        for filename in COMPONENT_LICENSE_FILES:
            (destination / filename).write_bytes(
                (REPO_ROOT / "licenses" / filename).read_bytes()
            )
        for distribution, relative, target in WHEEL_LICENSE_FILES:
            output = destination / Path(target)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(
                self._distribution_file(distribution, relative).read_bytes()
            )
        cpython = destination / "cpython"
        cpython.mkdir(exist_ok=True)
        (cpython / "LICENSE.txt").write_bytes(
            (Path(sys.base_prefix) / "LICENSE.txt").read_bytes()
        )
        tcl_tk = destination / "tcl-tk"
        tcl_tk.mkdir(exist_ok=True)
        (tcl_tk / "license.terms").write_bytes(
            (
                Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms"
            ).read_bytes()
        )

    def _install_qt_static_license_assets(self, root: Path) -> None:
        for source_relative in QT_STATIC_COMPONENTS["license_assets"]:
            destination_relative = "_internal/" + source_relative.removeprefix(
                "source/fixed_app/"
            )
            destination = root / Path(destination_relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((REPO_ROOT / source_relative).read_bytes())

    def _install_exact_audited_pymeshlab_natives(self, root: Path) -> None:
        records = PYMESHLAB_IDENTITIES["identities"] + QT_STATIC_COMPONENTS["files"]
        for record in records:
            relative = Path(record["path"])
            package_relative = relative.relative_to("_internal")
            source = self._distribution_file("pymeshlab", package_relative.as_posix())
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())

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
            trimesh = rows["_internal/trimesh_native.pyd"]
            self.assertEqual(trimesh["package_owners"], ["trimesh"])
            self.assertEqual(trimesh["components"], ["trimesh"])
            self.assertEqual(trimesh["mapping_basis"], "dist-info-record")
            component_by_id = {
                item["id"]: item for item in component_map["components"]
            }
            self.assertNotIn("resvg", component_by_id)
            self.assertFalse(
                any(
                    component_id.startswith("resvg-rust:")
                    for component_id in component_by_id
                )
            )
            for component_id, component in component_by_id.items():
                self.assertTrue(component["license_assets"], component_id)
                self.assertEqual(
                    set(component["license_assets"]),
                    set(component["license_asset_sha256"]),
                    component_id,
                )
            self.assertEqual(
                component_by_id["chromamatter"]["license_assets"],
                ["_internal/licenses/LICENSE_APP.txt"],
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
            library_by_ref = {
                item["bom-ref"]: item
                for item in sbom["components"]
                if item["type"] == "library"
            }
            self.assertEqual(
                library_by_ref["component:trimesh"]["licenses"],
                [{"expression": "MIT"}],
            )
            self.assertEqual(
                sbom["metadata"]["component"]["licenses"],
                [{"expression": "GPL-3.0-or-later"}],
            )
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

    def test_historical_pytetwild_wrapper_fails_approved_closure_gate(self) -> None:
        from tooling import generate_binary_compliance_inventory as inventory

        contract = inventory.PYTETWILD_STATIC_CLOSURE_CONTRACT
        item = inventory.ScannedFile(
            path=contract.packaged_pyd_path,
            size=5_897_728,
            sha256=inventory.HISTORICAL_PYTETWILD_PYD_SHA256,
            file_type="python-extension",
        )

        violations = inventory._pytetwild_static_closure_violations([item])
        components, basis, system_provenance = inventory.explicit_native_mapping(
            item
        )

        self.assertEqual(
            violations,
            ["historical-wrapper-forbidden", "wrapper-sha256-mismatch"],
        )
        self.assertEqual(components, ["pytetwild"])
        self.assertEqual(basis, "unapproved-pytetwild-static-closure")
        self.assertEqual(system_provenance, "")

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package)
            self._install_component_license_assets(package)
            for record in PYTETWILD_STATIC_CLOSURE["license_assets"].values():
                source = REPO_ROOT / record["path"]
                relative = Path(record["path"]).relative_to("source/fixed_app")
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            packaged_wrapper = package / Path(contract.packaged_pyd_path)
            packaged_wrapper.parent.mkdir(parents=True, exist_ok=True)
            packaged_wrapper.write_bytes(
                b"MZ\x00synthetic-unapproved-pytetwild-wrapper"
            )
            destination = base / "report"
            result = self._run(package, destination)

            self.assertEqual(result.returncode, 2, result.stderr)
            component_map = json.loads(
                (destination / "BINARY_COMPONENT_MAP.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(component_map["validation"]["passed"])
            self.assertIn(
                "wrapper-sha256-mismatch",
                component_map["validation"][
                    "pytetwild_static_closure_violations"
                ],
            )
            self.assertTrue((destination / "SBOM.cdx.json").is_file())

    def test_approved_exact_wrapper_maps_the_complete_static_closure(self) -> None:
        from tooling import generate_binary_compliance_inventory as inventory

        controlled_sha256 = "3" * 64
        approved = replace(
            inventory.PYTETWILD_STATIC_CLOSURE_CONTRACT,
            release_eligible=True,
            controlled_pyd_sha256=controlled_sha256,
        )
        item = inventory.ScannedFile(
            path=approved.packaged_pyd_path,
            size=123,
            sha256=controlled_sha256,
            file_type="python-extension",
        )
        with patch.object(
            inventory, "PYTETWILD_STATIC_CLOSURE_CONTRACT", approved
        ):
            components, basis, system_provenance = (
                inventory.explicit_native_mapping(item)
            )
            rejected, rejected_basis, _ = inventory.explicit_native_mapping(
                replace(item, sha256="4" * 64)
            )

        self.assertEqual(components, list(approved.static_component_ids))
        self.assertEqual(basis, "controlled-pytetwild-static-closure")
        self.assertEqual(system_provenance, "")
        self.assertEqual(rejected, ["pytetwild"])
        self.assertEqual(
            rejected_basis, "unapproved-pytetwild-static-closure"
        )
        for filename in (
            "msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll",
            "concrt140-a4c2229bdc2a2a630acdc095b4d86008.dll",
        ):
            with self.subTest(controlled_runtime=filename):
                runtime_item = inventory.ScannedFile(
                    path=f"_internal/pytetwild.libs/{filename}",
                    size=1,
                    sha256="5" * 64,
                    file_type="native-library",
                )
                runtime_components, runtime_basis, runtime_provenance = (
                    inventory.explicit_native_mapping(runtime_item)
                )
                self.assertEqual(
                    runtime_components,
                    ["pytetwild", "msvc-14.44.35211"],
                )
                self.assertEqual(runtime_basis, "wheel-repair-runtime")
                self.assertEqual(runtime_provenance, "")

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
            self._install_component_license_assets(package)
            self._install_qt_static_license_assets(package)
            for filename in (
                "_bz2.pyd",
                "_lzma.pyd",
                "_decimal.pyd",
                "pyexpat.pyd",
                "_elementtree.pyd",
            ):
                (package / "_internal" / filename).write_bytes(b"synthetic-cpython")
            self._install_exact_audited_pymeshlab_natives(package)
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
            self.assertEqual(licenses["cpython-bzip2"], "bzip2-1.0.6")
            self.assertEqual(
                licenses["cpython-liblzma"],
                "LicenseRef-XZ-Utils-Public-Domain",
            )
            self.assertEqual(licenses["cpython-expat"], "MIT")
            self.assertEqual(licenses["cpython-libmpdec"], "BSD-2-Clause")
            self.assertEqual(licenses["lib3mf-zlib"], "Zlib")
            self.assertEqual(licenses["lib3mf-libzip"], "BSD-3-Clause")
            self.assertEqual(licenses["lib3mf-cpp-base64"], "Zlib")
            self.assertEqual(licenses["lib3mf-fast-float"], "MIT")
            self.assertEqual(licenses["u3d-zlib"], "Zlib")
            self.assertEqual(licenses["u3d-libpng"], "Libpng")
            self.assertEqual(licenses["u3d-ijg-jpeg"], "IJG")
            self.assertEqual(
                licenses["u3d-fnvhash"],
                "LicenseRef-FNV-Public-Domain",
            )
            self.assertEqual(
                licenses["u3d-shewchuk-predicates"],
                "LicenseRef-Shewchuk-Public-Domain",
            )
            self.assertEqual(
                licenses["u3d-wcmatch"],
                "LicenseRef-WCMATCH-Freeware",
            )
            self.assertEqual(
                licenses["u3d-graphics-gems-iv"],
                "Apache-2.0 AND LicenseRef-Graphics-Gems-Unrestricted",
            )
            self.assertEqual(
                licenses["u3d-nick-bobic-quaternion"],
                "Apache-2.0 AND Zlib",
            )
            self.assertEqual(licenses["llvm-mesa"], "NCSA")
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
            component_by_id = {
                component["id"]: component
                for component in component_map["components"]
            }
            self.assertEqual(
                component_by_id["lib3mf-cpp-base64"]["version"],
                "V2.rc.08",
            )
            self.assertEqual(
                component_by_id["lib3mf-cpp-base64"]["source"],
                "https://github.com/ReneNyffenegger/cpp-base64/tree/V2.rc.08",
            )
            self.assertEqual(
                component_by_id["lib3mf-fast-float"]["version"],
                "6.0.0",
            )
            self.assertEqual(
                component_by_id["lib3mf-libzip"]["source"],
                "https://github.com/nih-at/libzip/tree/v1.10.1",
            )
            for component in component_map["components"]:
                assets = component.get("license_assets", [])
                self.assertTrue(assets, component["id"])
                expected_hashes = component.get("license_asset_sha256", {})
                self.assertEqual(set(expected_hashes), set(assets), component["id"])
                for asset in assets:
                    with self.subTest(component=component["id"], asset=asset):
                        self.assertEqual(rows[asset]["sha256"], expected_hashes[asset])
            self.assertTrue(
                {"embree", "onetbb-pymeshlab"}.issubset(
                    rows["_internal/pymeshlab/tbb12.dll"]["components"]
                ),
                rows["_internal/pymeshlab/tbb12.dll"]["components"],
            )
            expected_native_components = {
                "_internal/_bz2.pyd": {"cpython", "cpython-bzip2"},
                "_internal/_lzma.pyd": {"cpython", "cpython-liblzma"},
                "_internal/_decimal.pyd": {"cpython", "cpython-libmpdec"},
                "_internal/pyexpat.pyd": {"cpython", "cpython-expat"},
                "_internal/_elementtree.pyd": {"cpython", "cpython-expat"},
                "_internal/pymeshlab/libEGL.dll": {
                    "qt",
                    "qt-angle-core",
                    "qt-angle-khronos",
                },
                "_internal/pymeshlab/opengl32sw.dll": {
                    "qt",
                    "mesa-llvmpipe",
                    "llvm-mesa",
                },
                "_internal/pymeshlab/IFXCore.dll": {
                    "u3d",
                    "u3d-zlib",
                    "u3d-libpng",
                    "u3d-ijg-jpeg",
                    "u3d-fnvhash",
                    "u3d-shewchuk-predicates",
                    "u3d-wcmatch",
                    "u3d-graphics-gems-iv",
                    "u3d-nick-bobic-quaternion",
                },
                "_internal/pymeshlab/IFXExporting.dll": {"u3d"},
                "_internal/pymeshlab/lib3mf.dll": {
                    "lib3mf",
                    "lib3mf-cpp-base64",
                    "lib3mf-fast-float",
                    "lib3mf-zlib",
                    "lib3mf-libzip",
                },
                "_internal/pymeshlab/lib/plugins/io_3mf.dll": {"lib3mf"},
            }
            for path, expected in expected_native_components.items():
                with self.subTest(path=path):
                    self.assertTrue(
                        expected.issubset(rows[path]["components"]),
                        rows[path]["components"],
                    )

            sbom = json.loads(
                (destination / "SBOM.cdx.json").read_text(encoding="utf-8")
            )
            sbom_refs = {
                component["bom-ref"] for component in sbom["components"]
            }
            self.assertIn("component:pyinstaller", sbom_refs)
            for component_id in (
                "lib3mf-cpp-base64",
                "lib3mf-fast-float",
                "u3d-fnvhash",
                "u3d-shewchuk-predicates",
                "u3d-wcmatch",
                "u3d-graphics-gems-iv",
                "u3d-nick-bobic-quaternion",
            ):
                with self.subTest(sbom_component=component_id):
                    self.assertIn(f"component:{component_id}", sbom_refs)

    def test_used_component_without_required_license_asset_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package)
            self._install_component_license_assets(package)
            for filename in ("LICENSE_QT_LGPL_3_0.txt", "NOTICE_QT.txt"):
                (package / "_internal" / "licenses" / filename).unlink()
            pymeshlab = package / "_internal" / "pymeshlab"
            pymeshlab.mkdir()
            (pymeshlab / "Qt5Core.dll").write_bytes(b"synthetic-qt")

            destination = base / "report"
            result = self._run(package, destination)

            self.assertEqual(result.returncode, 2)
            self.assertIn("Missing component license assets", result.stderr)
            component_map = json.loads(
                (destination / "BINARY_COMPONENT_MAP.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(component_map["validation"]["passed"])
            self.assertEqual(
                component_map["validation"]["missing_component_license_assets"],
                [
                    {
                        "component": "qt",
                        "path": "_internal/licenses/LICENSE_QT_LGPL_3_0.txt",
                    },
                    {
                        "component": "qt",
                        "path": "_internal/licenses/NOTICE_QT.txt",
                    },
                ],
            )

    def test_tampered_component_license_asset_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package)
            self._install_component_license_assets(package)
            pymeshlab = package / "_internal" / "pymeshlab"
            pymeshlab.mkdir()
            (pymeshlab / "Qt5Core.dll").write_bytes(b"synthetic-qt")
            notice = package / "_internal" / "licenses" / "NOTICE_QT.txt"
            notice.write_text("not the reviewed notice\n", encoding="utf-8")

            destination = base / "report"
            result = self._run(package, destination)

            self.assertEqual(result.returncode, 2)
            self.assertIn("Invalid component license assets", result.stderr)
            component_map = json.loads(
                (destination / "BINARY_COMPONENT_MAP.json").read_text(
                    encoding="utf-8"
                )
            )
            issues = component_map["validation"][
                "invalid_component_license_assets"
            ]
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]["component"], "qt")
            self.assertEqual(issues[0]["path"], "_internal/licenses/NOTICE_QT.txt")
            self.assertEqual(issues[0]["reason"], "sha256-mismatch")
            self.assertRegex(issues[0]["expected_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(issues[0]["actual_sha256"], r"^[0-9a-f]{64}$")

    def test_dynamic_component_without_curated_assets_fails_and_uses_named_license(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / "package"
            package.mkdir()
            self._fixture(package)
            internal = package / "_internal"
            (internal / "human_native.pyd").write_bytes(b"synthetic-human")
            (internal / "noassertion_native.pyd").write_bytes(
                b"synthetic-noassertion"
            )
            dist_info = internal / "human_package-1.0.dist-info"
            dist_info.mkdir()
            (dist_info / "METADATA").write_text(
                "\n".join(
                    (
                        "Metadata-Version: 2.4",
                        "Name: human-package",
                        "Version: 1.0",
                        "Classifier: License :: Custom human wording",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            noassertion_dist_info = internal / "noassertion_package-1.0.dist-info"
            noassertion_dist_info.mkdir()
            (noassertion_dist_info / "METADATA").write_text(
                "\n".join(
                    (
                        "Metadata-Version: 2.4",
                        "Name: noassertion-package",
                        "Version: 1.0",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            (noassertion_dist_info / "RECORD").write_text(
                "\n".join(
                    (
                        "noassertion_native.pyd,,",
                        "noassertion_package-1.0.dist-info/METADATA,,",
                        "noassertion_package-1.0.dist-info/RECORD,,",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            (dist_info / "RECORD").write_text(
                "\n".join(
                    (
                        "human_native.pyd,,",
                        "human_package-1.0.dist-info/METADATA,,",
                        "human_package-1.0.dist-info/RECORD,,",
                        "",
                    )
                ),
                encoding="utf-8",
            )

            destination = base / "report"
            result = self._run(package, destination)

            self.assertEqual(result.returncode, 2)
            self.assertIn("no-license-assets-declared", result.stderr)
            component_map = json.loads(
                (destination / "BINARY_COMPONENT_MAP.json").read_text(
                    encoding="utf-8"
                )
            )
            dynamic = next(
                item
                for item in component_map["components"]
                if item["id"] == "pypi:human-package@1.0"
            )
            self.assertEqual(dynamic["license_assets"], [])
            self.assertEqual(dynamic["license_asset_sha256"], {})
            self.assertIn(
                {
                    "component": "pypi:human-package@1.0",
                    "path": "",
                    "reason": "no-license-assets-declared",
                    "expected_sha256": "",
                    "actual_sha256": "",
                },
                component_map["validation"]["invalid_component_license_assets"],
            )
            sbom = json.loads(
                (destination / "SBOM.cdx.json").read_text(encoding="utf-8")
            )
            dynamic_sbom = next(
                item
                for item in sbom["components"]
                if item.get("bom-ref") == "component:pypi:human-package@1.0"
            )
            self.assertEqual(
                dynamic_sbom["licenses"],
                [{"license": {"name": "Custom human wording"}}],
            )
            noassertion_sbom = next(
                item
                for item in sbom["components"]
                if item.get("bom-ref")
                == "component:pypi:noassertion-package@1.0"
            )
            self.assertEqual(
                noassertion_sbom["licenses"],
                [{"license": {"name": "NOASSERTION"}}],
            )

    def test_component_schema_requires_nonempty_asset_and_hash_declarations(
        self,
    ) -> None:
        schema = json.loads(
            (REPO_ROOT / "licenses" / "BINARY_COMPONENT_MAP.schema.json").read_text(
                encoding="utf-8"
            )
        )
        component_schema = schema["properties"]["components"]["items"]
        self.assertTrue(
            {"license_assets", "license_asset_sha256"}.issubset(
                component_schema["required"]
            )
        )
        self.assertEqual(
            component_schema["properties"]["license_assets"]["minItems"], 1
        )
        self.assertEqual(
            component_schema["properties"]["license_asset_sha256"][
                "minProperties"
            ],
            1,
        )
        validation_schema = schema["properties"]["validation"]
        self.assertIn(
            "pytetwild_static_closure_violations",
            validation_schema["required"],
        )
        self.assertEqual(
            validation_schema["properties"][
                "pytetwild_static_closure_violations"
            ]["maxItems"],
            0,
        )

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
        for filename in COMPONENT_LICENSE_FILES:
            with self.subTest(filename=filename):
                self.assertIn(f'"{filename}"', spec)
                if filename != "LICENSE_APP.txt":
                    self.assertIn(f"_internal/licenses/{filename}", index)
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
