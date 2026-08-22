from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "tooling" / "pytetwild_static_closure.json"
ASSET_ROOT = REPO_ROOT / "source" / "fixed_app" / "licenses" / "pytetwild-closure"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


EXPECTED_COMPONENT_IDS = {
    "eigen",
    "fmt",
    "ftetwild",
    "geogram",
    "geogram-amgcl",
    "geogram-libmeshb",
    "geogram-poissonrecon",
    "geogram-rply",
    "geogram-stb-image",
    "geogram-stb-image-write",
    "geogram-xatlas",
    "geogram-zlib",
    "jdumas-json",
    "libigl",
    "libigl-predicates",
    "nanobind",
    "nanobind-robin-map",
    "onetbb",
    "pytetwild",
    "spdlog",
}

EXPECTED_SOURCE_ARCHIVES = {
    "pytetwild-source": (
        "eea46df87ef58e861956b7a710f42ab58eaa02a0",
        721021,
        "f68d4d76be195697df153dc4e5f86f47cd55c3807b7053b1863f36dcf7db8484",
    ),
    "ftetwild-source": (
        "d7d99bb4387a07895b9adce058dc7305f6b6e5ab",
        1940353,
        "e2a782e5711b8f890b55123d355d533405c34d5319035268e6f7f99b35a2c922",
    ),
    "nanobind-source": (
        "2a61ad2494d09fecb2e13322c1383342c299900d",
        1044209,
        "97f9ab5bc8c87112da7c5a578f510944b1b20afbf924c7007462a8c4a8ab7fd9",
    ),
    "nanobind-robin-map-source": (
        "4ec1bf19c6a96125ea22062f38c2cf5b958e448e",
        87395,
        "78c97483a8993866074f06b25fd288cdb7b8ebd6c61c2f0c43b0e324fd56ce10",
    ),
    "fmt-source": (
        "40626af88bd7df9a5fb80be7b25ac85b122d6c21",
        760785,
        "3fb8c43dd1d1dd422b20d6c9836a77fa44f9b48cde6dc1adccda7600f09a0446",
    ),
    "spdlog-source": (
        "6fa36017cfd5731d617e1a934f0e5ea9c4445b13",
        355882,
        "433f18fabe071c5c2ef17eb6676991f95dd9bfb48d138528218f452f73ada1cc",
    ),
    "libigl-source": (
        "40e7900ccbd767f1f360e0eb10f0f1a6432e0993",
        2112284,
        "37bb228c083260acaea36fd7ec07305639f17e09f669dbc07a36c0ad078ad750",
    ),
    "libigl-predicates-source": (
        "decb7bc1260e689cbe008109e3cc5d3a5a433aea",
        25544,
        "8d3d43a509fb0652b03a0ccfb23b60e56459dad3068e25ef137752bd245bea1f",
    ),
    "geogram-source": (
        "fc3eb9bf44d2ee29686592e3ef5f5f4daeda27f8",
        7174459,
        "7c600f7ef8fcb727b000531069925d23e611f703ef827c3447a71092a25247ca",
    ),
    "geogram-amgcl-source": (
        "ab57038d68ee372ed5df280631051b91f17ed2d1",
        3311450,
        "54354071a42a28b77b0353aa9f206067b29e38795f31d8005e8467848f0a9bd6",
    ),
    "geogram-libmeshb-source": (
        "952a157c9d516b28cc6c69cd1550c3e48d4792f9",
        1225156,
        "9fc2278af2122bad6b1f6105590702fb00fecfebe98be5b25fbba4c8c43ffada",
    ),
    "geogram-rply-source": (
        "4296cc91b5c8c26d4e7d7aac0cee2b194ffc5800",
        35208,
        "1a204b399fe4a1d6067033e4a5d6a4494936be4d7bc009737b859277c7b4aa94",
    ),
    "onetbb-source": (
        "06ce6212da6710f4bb2d20a1904b018aa44069bf",
        5022789,
        "905f0efbaeddd4d3280d4add1e0ef19bf2f1379612d86706a2f22b55d2e9e163",
    ),
    "jdumas-json-source": (
        "0901d33bf6e7dfe6f70fd9d142c8f5c6695c6c5b",
        145834,
        "c116a4ea81a105a7f54a9b2e52c8f836ae3e3b69b8746c26d5a0193e328838a8",
    ),
    "eigen-source": (
        "3147391d946bb4b6c68edd901f2add6ac1f31f8c",
        2705005,
        "8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72",
    ),
}

EXPECTED_LICENSE_ASSETS = {
    "pytetwild-license": (17096, "9343f5b1b62ea515a5c68112bdb62ad94ce8316e8c5c0f382e5b6a47ee26128e"),
    "ftetwild-mpl2": (17099, "cde215e5b42363eb28ca2462c4558ff4807b38f383c537624c31e44657ac58f4"),
    "nanobind-license": (1547, "33f4e77f926740b304c36d1e5e7a9ad3f68e5c942497e2f40a8f47d8d1d1a780"),
    "nanobind-robin-map-license": (1102, "11f2c685ba565a31aef1219f63a7a8845602c97bff70016b9e3278dfe51a2ec5"),
    "fmt-license": (1458, "25b5db04aa6070c12ac518b91cbd0a59725c050ecb091456e6ebc3d3eeb369cf"),
    "spdlog-license": (1354, "4ccecab18d1ff0b61174fe3d6c430541625d3ddb865b0d5887db296f883c76e7"),
    "libigl-mpl2": (17099, "cde215e5b42363eb28ca2462c4558ff4807b38f383c537624c31e44657ac58f4"),
    "libigl-gpl": (35821, "0b383d5a63da644f628d99c33976ea6487ed89aaa59f0b3257992deac1171e6b"),
    "libigl-predicates-readme": (1086, "98284fda28d07def43bf31da9be805a5237409d8cb8a1df786059bbbc7922518"),
    "libigl-predicates-source-notice": (176294, "50e4d231025285b3dc78100c0512822994a83661974bec6d801af8d8d27f3963"),
    "geogram-license": (1666, "beddcf06f4e095e083af3778c758687be1192be17285a3e6c845b448719ff48d"),
    "onetbb-license": (11558, "1eb85fc97224598dad1852b5d6483bbcf0aa8608790dcc657a5a2a761ae9c8c6"),
    "jdumas-json-license": (1097, "574bffc80b747c87ea7f900182c4970cccb2be247fd9fedf0fe4640ca439960d"),
    "eigen-apache": (11362, "03379001a7b12a2ec997a25554247d985270b353c10d5bafee9ac8d6519820b7"),
    "eigen-bsd": (1517, "51928dce36213c5333ba3172e847d735d4c6e9b7ff2722a326c49067155b82eb"),
    "eigen-gpl": (35147, "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903"),
    "eigen-lgpl": (26530, "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551"),
    "eigen-minpack": (2193, "c87b7f8ee88f6195e91743820c00354833583aef091b72e2d4a49c8e28e798a0"),
    "eigen-mpl2": (16726, "fab3dd6bdab226f1c08630b1dd917e11fcb4ec5e1e020e2c16f83a0a13863e85"),
    "eigen-readme": (779, "c83230b770f17ef1386ea1fd3681271dd98aa93646bdbfb5bff3a1b7050fff9d"),
    "geogram-amgcl-license": (1145, "73cbcf5dbcc124d36385e77001f9955b43b0bc249ddfc4d1450b71f6adba0dfa"),
    "geogram-libmeshb-license": (1106, "4d4a3de3231b2bd3ae5b6b31300e39cf3b832e77e664d65b7be4f29cdb6a81eb"),
    "geogram-rply-license": (1091, "8bac777ee5ec18b8dab40d98c4e476a228ee7227eb51dd9d1a6796cd6b8bffa1"),
    "geogram-zlib-license": (1024, "18dbd37f0ab175c37877e9053ff870a7de2809a3e9b9673b2696aa5009264638"),
    "geogram-stb-image-notice": (292720, "2d264ec3e6ce404fc2d0cfff4476c982eb3edf5a61122b03884fdef7bacd9deb"),
    "geogram-stb-image-write-notice": (61498, "35bab2b424e6722fd51fa6cfc2c57b0f6dd97a4a1a6d4eb730a4bb22ef5e819f"),
    "geogram-poissonrecon-license": (1680, "dc1695ab9fe836cfa9698a1ab7918119f5388c452c398f3c22fae824c5cad831"),
    "geogram-xatlas-header-notice": (9875, "4f9c57b11e44a4c1cb69a0843ec2ec115454fee9580815798f449df885273997"),
    "geogram-xatlas-source-notices": (323351, "dd12d1927d7ac2a01544ace616e5e70cf61e82e79a35cfb40c74be4ec85b53ce"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class PyTetWildStaticClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_manifest_has_the_complete_conservative_component_set(self) -> None:
        components = self.manifest["components"]
        self.assertEqual(set(components), EXPECTED_COMPONENT_IDS)

        used_sources: set[str] = set()
        used_assets: set[str] = set()
        for component_id, component in components.items():
            self.assertTrue(component["name"], component_id)
            self.assertTrue(component["version"], component_id)
            self.assertTrue(component["license_expression"], component_id)
            self.assertTrue(component["source_archive_ids"], component_id)
            self.assertTrue(component["license_asset_ids"], component_id)
            self.assertTrue(component["inclusion_basis"], component_id)
            used_sources.update(component["source_archive_ids"])
            used_assets.update(component["license_asset_ids"])
            for dependency in component.get("dependencies", []):
                self.assertIn(dependency, components, (component_id, dependency))

        self.assertEqual(used_sources, set(self.manifest["source_archives"]))
        self.assertEqual(used_assets, set(self.manifest["license_assets"]))

    def test_source_archive_identities_are_fixed(self) -> None:
        archives = self.manifest["source_archives"]
        self.assertEqual(set(archives), set(EXPECTED_SOURCE_ARCHIVES))
        filenames: set[str] = set()
        for archive_id, expected in EXPECTED_SOURCE_ARCHIVES.items():
            revision, size, digest = expected
            archive = archives[archive_id]
            self.assertEqual(archive["revision"], revision, archive_id)
            self.assertEqual(archive["bytes"], size, archive_id)
            self.assertEqual(archive["sha256"], digest, archive_id)
            self.assertRegex(archive["sha256"], SHA256_RE)
            self.assertTrue(archive["source_url"].startswith("https://"), archive_id)
            self.assertNotIn(archive["filename"], filenames, archive_id)
            filenames.add(archive["filename"])

        recipe = self.manifest["build_binding"]["source_archive_recipe"]
        self.assertEqual(recipe["tool"], "PortableGit")
        self.assertEqual(recipe["tool_version"], "2.55.0.windows.5")
        self.assertEqual(recipe["arguments"], ["archive", "--format=zip"])

    def test_license_assets_are_byte_exact_and_confined(self) -> None:
        assets = self.manifest["license_assets"]
        self.assertEqual(set(assets), set(EXPECTED_LICENSE_ASSETS))
        resolved_root = ASSET_ROOT.resolve()
        seen_paths: set[Path] = set()
        for asset_id, (expected_size, expected_digest) in EXPECTED_LICENSE_ASSETS.items():
            asset = assets[asset_id]
            relative = Path(asset["path"])
            self.assertFalse(relative.is_absolute(), asset_id)
            candidate = (REPO_ROOT / relative).resolve()
            self.assertTrue(candidate.is_relative_to(resolved_root), asset_id)
            self.assertNotIn(candidate, seen_paths, asset_id)
            seen_paths.add(candidate)
            self.assertTrue(candidate.is_file(), asset_id)
            self.assertEqual(asset["bytes"], expected_size, asset_id)
            self.assertEqual(candidate.stat().st_size, expected_size, asset_id)
            self.assertEqual(asset["sha256"], expected_digest, asset_id)
            self.assertEqual(_sha256(candidate), expected_digest, asset_id)

    def test_recipe_and_binary_identity_are_fail_closed(self) -> None:
        build = self.manifest["build_binding"]
        recipe = REPO_ROOT / build["recipe_path"]
        self.assertTrue(recipe.is_file())
        self.assertEqual(recipe.stat().st_size, build["recipe_bytes"])
        self.assertEqual(_sha256(recipe), build["recipe_sha256"])
        recipe_text = recipe.read_text(encoding="utf-8-sig")
        self.assertIn("'-DEIGEN_MPL2_ONLY=ON'", recipe_text)

        historical = build["historical_audited_package"]
        self.assertEqual(historical["disposition"], "excluded-historical-audit-only")
        self.assertEqual(historical["pyd_bytes"], 5897728)
        self.assertEqual(
            historical["pyd_sha256"],
            "ac801b37e298ee83be35f41193d384f64ef4b5064006e0019a209edff48495de",
        )

        self._assert_release_gate_is_consistent(self.manifest)
        unsafe = copy.deepcopy(self.manifest)
        unsafe["release_gate"]["status"] = "release-approved"
        unsafe["release_gate"]["release_eligible"] = True
        with self.assertRaises(AssertionError):
            self._assert_release_gate_is_consistent(unsafe)

    def test_eigen_route_and_unproven_geogram_objects_are_explicit(self) -> None:
        components = self.manifest["components"]
        eigen = components["eigen"]
        self.assertEqual(eigen["license_expression"], "MPL-2.0")
        self.assertIn("EIGEN_MPL2_ONLY=ON", eigen["license_route"])
        self.assertEqual(len(eigen["license_asset_ids"]), 7)

        for component_id in ("geogram-poissonrecon", "geogram-xatlas"):
            self.assertIn("no exact final-link map", components[component_id]["inclusion_basis"])

    def _assert_release_gate_is_consistent(self, manifest: dict) -> None:
        gate = manifest["release_gate"]
        controlled = manifest["build_binding"]["controlled_rebuild"]
        unresolved = [item for item in gate["blockers"] if not item["resolved"]]
        if gate["release_eligible"]:
            self.assertEqual(gate["status"], "release-approved")
            self.assertFalse(unresolved)
            self.assertEqual(controlled["status"], "approved")
            self.assertRegex(controlled["wheel_sha256"], SHA256_RE)
            self.assertRegex(controlled["pyd_sha256"], SHA256_RE)
            return

        self.assertEqual(gate["status"], "blocked")
        self.assertTrue(unresolved)
        self.assertEqual(controlled["status"], "blocked-awaiting-build")
        self.assertIsNone(controlled["wheel_sha256"])
        self.assertIsNone(controlled["pyd_sha256"])


if __name__ == "__main__":
    unittest.main()
