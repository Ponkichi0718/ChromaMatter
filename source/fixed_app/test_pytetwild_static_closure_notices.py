from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "tooling" / "pytetwild_static_closure.json"
NOTICE_PATHS = {
    "index": REPO_ROOT / "licenses" / "THIRD_PARTY_LICENSES.txt",
    "en": REPO_ROOT / "licenses" / "THIRD_PARTY_NOTICES_EN.txt",
    "ja": REPO_ROOT / "licenses" / "THIRD_PARTY_NOTICES_JA.txt",
}
PACKAGED_ASSET_ROOT = "_internal/licenses/pytetwild-closure/"
MATERIAL_FAMILY_TOKENS = {
    "pytetwild": "PyTetWild",
    "ftetwild": "fTetWild",
    "nanobind": "nanobind",
    "nanobind-robin-map": "Tessil robin-map",
    "fmt": "fmt",
    "spdlog": "spdlog",
    "libigl": "libigl",
    "libigl-predicates": "libigl predicates",
    "geogram": "Geogram",
    "onetbb": "oneTBB",
    "jdumas-json": "jdumas/json",
    "eigen": "Eigen",
    "geogram-amgcl": "AMGCL",
    "geogram-libmeshb": "libMeshb",
    "geogram-rply": "RPly",
    "geogram-zlib": "zlib",
    "geogram-stb-image": "stb_image",
    "geogram-stb-image-write": "stb_image_write",
    "geogram-poissonrecon": "PoissonRecon",
    "geogram-xatlas": "xatlas",
}


class PyTetWildStaticClosureNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.notices = {
            name: path.read_text(encoding="utf-8")
            for name, path in NOTICE_PATHS.items()
        }

    def test_notices_match_manifest_counts_paths_and_blocked_gate(self) -> None:
        components = self.manifest["components"]
        assets = self.manifest["license_assets"]
        gate = self.manifest["release_gate"]
        controlled = self.manifest["build_binding"]["controlled_rebuild"]

        self.assertEqual(len(components), 20)
        self.assertEqual(len(assets), 29)
        self.assertEqual(gate["status"], "blocked")
        self.assertFalse(gate["release_eligible"])
        self.assertIsNone(controlled["wheel_sha256"])
        self.assertIsNone(controlled["pyd_sha256"])

        packaged_paths = {
            asset_id: asset["path"].replace(
                "source/fixed_app/licenses/pytetwild-closure/",
                PACKAGED_ASSET_ROOT,
                1,
            )
            for asset_id, asset in assets.items()
        }
        self.assertEqual(len(packaged_paths), 29)
        self.assertTrue(
            all(path.startswith(PACKAGED_ASSET_ROOT) for path in packaged_paths.values())
        )

        exact_count_phrases = {
            "index": ("records 20 components", "requires all 29"),
            "en": ("contains 20 components", "requires all 29"),
            "ja": ("20コンポーネント", "29個すべて"),
        }
        for name, notice in self.notices.items():
            with self.subTest(notice=name):
                self.assertIn("release_gate.status=blocked", notice)
                self.assertIn("release_eligible=false", notice)
                self.assertIn(PACKAGED_ASSET_ROOT, notice)
                for phrase in exact_count_phrases[name]:
                    self.assertIn(phrase, notice)

    def test_every_manifest_component_family_and_license_expression_is_named(self) -> None:
        components = self.manifest["components"]
        self.assertEqual(set(MATERIAL_FAMILY_TOKENS), set(components))
        license_expressions = {
            component["license_expression"] for component in components.values()
        }

        for name, notice in self.notices.items():
            with self.subTest(notice=name):
                for token in MATERIAL_FAMILY_TOKENS.values():
                    self.assertIn(token, notice)
                for expression in license_expressions:
                    self.assertIn(expression, notice)

    def test_notices_do_not_approve_historical_or_current_binary(self) -> None:
        index = " ".join(self.notices["index"].split())
        english = " ".join(self.notices["en"].split())
        japanese = "".join(self.notices["ja"].split())

        self.assertIn("historical audit evidence only", index)
        self.assertIn("does not make any current Windows binary", index)
        self.assertIn("audit-only and excluded from release", english)
        self.assertIn("does not declare any current Windows", english)
        self.assertIn("監査専用で、公開承認", japanese)
        self.assertIn("現時点のWindowsバイナリを公開", japanese)

    def test_source_only_resvg_wording_is_preserved(self) -> None:
        index = self.notices["index"]
        self.assertIn(
            "Source-only development dependency for the hidden Decal beta implementation.",
            index,
        )
        self.assertIn(
            "It is intentionally excluded from the public r32 frozen application",
            index,
        )


if __name__ == "__main__":
    unittest.main()
