from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "tooling" / "qt_static_components.json"
CORRESPONDING_SOURCE = REPO_ROOT / "tooling" / "corresponding_source_components.json"
INVENTORY_TOOL = REPO_ROOT / "tooling" / "generate_binary_compliance_inventory.py"

EXPECTED_FILES = {
    "_internal/pymeshlab/Qt5Core.dll": (
        6_023_664,
        "8d2ff4ce9096ddccc4f4cd62c2e41fc854cfd1b0d6e8d296645a7f5fd4ae565a",
        {
            "qt-doubleconversion",
            "qt-pcre2",
            "qt-pcre2-sljit",
            "qt-zlib",
            "qt-harfbuzz-legacy",
            "qt-tinycbor",
            "qt-md4",
            "qt-md5",
            "qt-sha1",
            "qt-sha3-endian",
            "qt-sha3-keccak",
            "qt-rfc6234",
            "qt-easing",
            "qt-qbig5codecs",
            "qt-qbkcodec",
            "qt-qeucjpcodec",
            "qt-qeuckrcodec",
            "qt-qjiscodec",
            "qt-qsjiscodec",
            "qt-qtsciicodec",
            "qt-unicode-ucd",
            "qt-unicode-cldr",
            "qt-public-suffix-list",
        },
    ),
    "_internal/pymeshlab/Qt5Gui.dll": (
        7_008_240,
        "5e7d2d41b8b92a880e83b8cc0ca173f5da61218604186196787ee1600956be1e",
        {
            "qt-freetype",
            "qt-freetype-zlib",
            "qt-freetype-bdf",
            "qt-freetype-pcf",
            "qt-grayraster",
            "qt-harfbuzz-ng",
            "qt-libpng",
            "qt-md4c",
            "qt-vulkan-memory-allocator",
            "qt-icc-srgb",
            "qt-aglfn",
            "qt-smooth-scaling",
            "qt-webgradients",
            "qt-xserverhelper",
            "qt-opengl-headers",
            "qt-opengles2-headers",
            "qt-vulkan-api-registry",
        },
    ),
    "_internal/pymeshlab/imageformats/qjpeg.dll": (
        421_360,
        "fb4e980cb5fafa8a4cd4239329aed93f7c32ed939c94b61fb2df657f3c6ad158",
        {"qt-libjpeg-turbo"},
    ),
    "_internal/pymeshlab/imageformats/qtiff.dll": (
        390_128,
        "825174429ced6b3dab18115dbc6c9da07bf5248c86ec1bd5c0dcaeca93b4c22d",
        {"qt-libtiff"},
    ),
    "_internal/pymeshlab/imageformats/qwebp.dll": (
        510_448,
        "6e37acd0d357871f92b7fde7206c904c734caa02f94544df646957df8c4987af",
        {"qt-libwebp"},
    ),
    "_internal/pymeshlab/libEGL.dll": (
        25_072,
        "32092de077fd57b6ef355705ec46c6d21f6d72fbe3d3a5dd628f2a29185a96fa",
        {"qt-angle-core", "qt-angle-khronos"},
    ),
    "_internal/pymeshlab/libGLESv2.dll": (
        3_385_328,
        "50fad5605b3d57627848b3b84a744dfb6a045609b8236b04124f2234676758d8",
        {
            "qt-angle-core",
            "qt-angle-arrayboundsclamper",
            "qt-angle-khronos",
            "qt-angle-systeminfo",
            "qt-angle-trace-event",
            "qt-angle-murmurhash",
            "qt-angle-chromium-base",
        },
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class QtStaticComponentsTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_exact_binary_mapping_is_closed_and_bidirectional(self) -> None:
        self.assertEqual(self.document["schema_version"], 1)
        files = {item["path"]: item for item in self.document["files"]}
        self.assertEqual(set(files), set(EXPECTED_FILES))

        components = {
            item["id"]: item for item in self.document["static_components"]
        }
        self.assertEqual(len(components), len(self.document["static_components"]))
        expected_ids = set().union(*(entry[2] for entry in EXPECTED_FILES.values()))
        self.assertEqual(set(components), expected_ids)
        self.assertEqual(len(expected_ids), 50)

        for path, (size, sha256, expected_components) in EXPECTED_FILES.items():
            record = files[path]
            self.assertEqual(record["size"], size)
            self.assertEqual(record["sha256"], sha256)
            self.assertEqual(record["pe_version"], "5.15.2.0")
            self.assertEqual(record["runtime_component_ids"][0], "qt")
            self.assertEqual(
                set(record["runtime_component_ids"][1:]), expected_components
            )

            reverse = {
                component_id
                for component_id, component in components.items()
                if path in component["runtime_files"]
            }
            self.assertEqual(reverse, expected_components)

        valid_files = set(EXPECTED_FILES)
        for component_id, component in components.items():
            self.assertEqual(component["id"], component_id)
            self.assertTrue(component["version"])
            self.assertTrue(component["version_basis"])
            self.assertTrue(component["license_expression"])
            self.assertTrue(component["license_assets"])
            self.assertTrue(set(component["runtime_files"]).issubset(valid_files))
            source = component["source"]
            self.assertEqual(source["archive_id"], "qt-5.15.2-corresponding-source")
            self.assertIn(source["module"], {"qtbase", "qtimageformats"})
            expected_prefix = (
                f"qt-everywhere-src-5.15.2/{source['module']}/"
            )
            self.assertTrue(
                source["corresponding_source_member_root"].startswith(
                    expected_prefix
                )
            )

    def test_license_assets_are_present_pinned_and_all_referenced(self) -> None:
        assets = self.document["license_assets"]
        self.assertEqual(len(assets), 51)
        referenced = {
            asset
            for component in self.document["static_components"]
            for asset in component["license_assets"]
        }
        self.assertEqual(referenced, set(assets))

        root_prefix = "source/fixed_app/licenses/qt-5.15.2/"
        for relative, record in assets.items():
            self.assertTrue(relative.startswith(root_prefix))
            self.assertTrue(record["byte_preserving"])
            self.assertRegex(record["sha256"], r"^[0-9a-f]{64}$")
            path = REPO_ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(path.stat().st_size, record["size"], relative)
            self.assertEqual(_sha256(path), record["sha256"], relative)

            upstream = record["upstream"]
            if "/qtbase/" in relative:
                suffix = relative.split("/qtbase/", 1)[1]
                self.assertEqual(
                    upstream["source_member"],
                    f"qtbase-everywhere-src-5.15.2/{suffix}",
                )
                self.assertEqual(
                    upstream["corresponding_source_member"],
                    f"qt-everywhere-src-5.15.2/qtbase/{suffix}",
                )
            elif "/qtimageformats/" in relative:
                suffix = relative.split("/qtimageformats/", 1)[1]
                self.assertEqual(
                    upstream["source_member"],
                    f"qtimageformats-everywhere-src-5.15.2/{suffix}",
                )
                self.assertEqual(
                    upstream["corresponding_source_member"],
                    f"qt-everywhere-src-5.15.2/qtimageformats/{suffix}",
                )
            else:
                self.assertEqual(
                    upstream["source_commit"],
                    "28b5bbb227d331c01e6ff9b2f8729732135aadc7",
                )

    def test_git_attributes_preserve_upstream_asset_bytes(self) -> None:
        attributes = REPO_ROOT / "source" / "fixed_app" / "licenses" / ".gitattributes"
        self.assertEqual(
            attributes.read_text(encoding="utf-8"),
            "# Preserve byte-for-byte copies of upstream license and notice files.\n"
            "* -text\n"
            "**/* -text\n",
        )
        representative_assets = (
            "source/fixed_app/licenses/qt-5.15.2/qtbase/src/3rdparty/angle/qt_attribution.json",
            "source/fixed_app/licenses/qt-5.15.2/qtbase/src/3rdparty/md4/qt_attribution.json",
            "source/fixed_app/licenses/qt-5.15.2/qtbase/src/3rdparty/pcre2/LICENCE",
        )
        for relative in representative_assets:
            filtered = subprocess.run(
                ["git", "hash-object", f"--path={relative}", relative],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            raw = subprocess.run(
                ["git", "hash-object", "--no-filters", relative],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(filtered, raw, relative)

    def test_existing_corresponding_source_archive_covers_qt_modules(self) -> None:
        spec = json.loads(CORRESPONDING_SOURCE.read_text(encoding="utf-8"))
        qt_entry = next(
            component
            for component in spec["components"]
            if component["id"] == "qt-5.15.2"
        )
        source_record = next(
            item
            for item in self.document["binary_provenance"]["source_archives"]
            if item["id"] == "qt-5.15.2-corresponding-source"
        )
        self.assertTrue(source_record["covers_all_qt_components"])
        self.assertEqual(set(source_record["modules"]), {"qtbase", "qtimageformats"})
        self.assertIn(source_record["url"], qt_entry["urls"])
        self.assertEqual(source_record["sha256"], qt_entry["sha256"])
        self.assertTrue(qt_entry["validate_archive_members"])

    def test_checked_out_pymeshlab_dlls_match_when_available(self) -> None:
        pymeshlab = REPO_ROOT / ".venv" / "Lib" / "site-packages" / "pymeshlab"
        if not pymeshlab.is_dir():
            self.skipTest("repository .venv PyMeshLab runtime is not available")
        for package_path, (size, sha256, _components) in EXPECTED_FILES.items():
            relative = package_path.removeprefix("_internal/pymeshlab/")
            runtime_file = pymeshlab / Path(relative)
            self.assertTrue(runtime_file.is_file(), relative)
            self.assertEqual(runtime_file.stat().st_size, size, relative)
            self.assertEqual(_sha256(runtime_file), sha256, relative)

    def test_extracted_official_sources_match_when_requested(self) -> None:
        roots = {
            "qtbase": os.environ.get("CHROMAMATTER_QTBASE_5_15_2_SOURCE_ROOT"),
            "qtimageformats": os.environ.get(
                "CHROMAMATTER_QTIMAGEFORMATS_5_15_2_SOURCE_ROOT"
            ),
        }
        if not all(roots.values()):
            self.skipTest("official extracted Qt source roots were not supplied")

        for relative, record in self.document["license_assets"].items():
            upstream = record["upstream"]
            archive_id = upstream["source_archive_id"]
            if archive_id == "chromium-base-license-28b5":
                continue
            module = "qtbase" if archive_id.startswith("qtbase-") else "qtimageformats"
            prefix = f"{module}-everywhere-src-5.15.2/"
            member = upstream["source_member"]
            self.assertTrue(member.startswith(prefix))
            source_path = Path(roots[module]) / member.removeprefix(prefix)
            self.assertTrue(source_path.is_file(), member)
            self.assertEqual(source_path.stat().st_size, record["size"], member)
            self.assertEqual(_sha256(source_path), record["sha256"], member)

    def test_inventory_registers_exact_qt_components_and_assets(self) -> None:
        module = runpy.run_path(str(INVENTORY_TOOL), run_name="qt_inventory_contract")
        registered = module["STATIC_COMPONENTS"]
        expected_components = {
            record["id"]: record for record in self.document["static_components"]
        }
        self.assertEqual(set(module["QT_STATIC_COMPONENTS"]), set(expected_components))
        self.assertNotIn("qt-angle", registered)
        self.assertEqual(len(module["AUDITED_NATIVE_IDENTITIES"]), 26)

        transformed_assets = {
            "_internal/" + source.removeprefix("source/fixed_app/"): record["sha256"]
            for source, record in self.document["license_assets"].items()
        }
        self.assertEqual(module["QT_LICENSE_ASSET_SHA256"], transformed_assets)
        for component_id, manifest_component in expected_components.items():
            with self.subTest(component=component_id):
                component = registered[component_id]
                self.assertEqual(component.name, manifest_component["name"])
                self.assertEqual(component.version, manifest_component["version"])
                self.assertEqual(
                    component.license, manifest_component["license_expression"]
                )
                expected_assets = tuple(
                    "_internal/" + asset.removeprefix("source/fixed_app/")
                    for asset in manifest_component["license_assets"]
                )
                self.assertEqual(component.license_assets, expected_assets)
                sbom_properties = module["_cyclonedx_component_properties"](
                    component
                )
                self.assertEqual(len(sbom_properties), 1)
                self.assertEqual(
                    json.loads(sbom_properties[0]["value"]),
                    {asset: transformed_assets[asset] for asset in expected_assets},
                )

    def test_inventory_qt_child_mapping_requires_exact_bytes(self) -> None:
        module = runpy.run_path(str(INVENTORY_TOOL), run_name="qt_inventory_contract")
        scanned_file = module["ScannedFile"]
        mapper = module["explicit_native_mapping"]
        for path, (size, sha256, expected_children) in EXPECTED_FILES.items():
            exact = scanned_file(path, size, sha256, "native-library")
            components, basis, _system = mapper(exact)
            with self.subTest(path=path, state="exact"):
                self.assertTrue(expected_children.issubset(components))
                self.assertIn("qt", components)
                self.assertIn("audited-native-identity", basis)

            tampered = scanned_file(path, size, "0" * 64, "native-library")
            tampered_components, tampered_basis, _system = mapper(tampered)
            with self.subTest(path=path, state="tampered"):
                self.assertFalse(expected_children & set(tampered_components))
                self.assertNotIn("audited-native-identity", tampered_basis)

            relocated = scanned_file(
                f"_internal/pymeshlab/relocated/{Path(path).name}",
                size,
                sha256,
                "native-library",
            )
            relocated_components, relocated_basis, _system = mapper(relocated)
            with self.subTest(path=path, state="relocated"):
                self.assertFalse(expected_children & set(relocated_components))
                self.assertNotIn("audited-native-identity", relocated_basis)


if __name__ == "__main__":
    unittest.main()
