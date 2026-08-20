from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import unittest


FIXED_APP = Path(__file__).resolve().parent
REPO_ROOT = FIXED_APP.parents[1]
RESOURCE_ROOT = FIXED_APP / "resources" / "filament_db"
RESOURCE_FILENAMES = (
    "filament_color_database_2026-08.sqlite",
    "filament_color_database_README.md",
    "ATTRIBUTION.md",
    "LICENSE_OPEN_FILAMENT_DATABASE.txt",
    "LICENSE_CC_BY_4.0.txt",
)
PERSONAL_WINDOWS_PATH = re.compile(rb"[A-Za-z]:[\\/]+Users[\\/]", re.IGNORECASE)


class FilamentDatabasePackagingTests(unittest.TestCase):
    def test_complete_attributed_resource_set_is_present(self) -> None:
        for filename in RESOURCE_FILENAMES:
            path = RESOURCE_ROOT / filename
            with self.subTest(filename=filename):
                self.assertTrue(path.is_file(), path)
                self.assertGreater(path.stat().st_size, 0)

        mit = (RESOURCE_ROOT / RESOURCE_FILENAMES[3]).read_text(encoding="utf-8")
        self.assertIn("Copyright © 2025 OpenFilamentCollective", mit)
        self.assertIn("Permission is hereby granted", mit)

        cc_by = (RESOURCE_ROOT / RESOURCE_FILENAMES[4]).read_text(encoding="utf-8")
        self.assertIn("Creative Commons Attribution 4.0 International", cc_by)
        self.assertIn("Section 8 -- Interpretation.", cc_by)

    def test_attribution_identifies_sources_scope_changes_and_date(self) -> None:
        attribution = (RESOURCE_ROOT / "ATTRIBUTION.md").read_text(encoding="utf-8")
        for expected in (
            "OpenFilamentCollective",
            "v2026.07.31",
            "v2026.08.16",
            "Amazon.co.jp manufacturer qualification",
            "manufacturer qualification only",
            "rating at least 4.0",
            "FilamentColors.xyz",
            "41 physical measured PLA swatches",
            "CC BY 4.0",
            "measured_swatches.source_url",
            "calculated Lab",
            "2026-08-07",
            "2026-08-19",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, attribution)

    def test_database_is_readable_and_contains_attributed_measurements(self) -> None:
        database = RESOURCE_ROOT / RESOURCE_FILENAMES[0]
        connection = sqlite3.connect(
            f"file:{database.as_posix()}?mode=ro",
            uri=True,
        )
        try:
            self.assertEqual(
                connection.execute("PRAGMA quick_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM measured_swatches").fetchone()[0],
                41,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM measured_swatches "
                    "WHERE source_url IS NULL OR TRIM(source_url) = ''"
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_resources_do_not_embed_personal_absolute_paths(self) -> None:
        private_user_token = b"pd" + b"cko"
        for filename in RESOURCE_FILENAMES:
            payload = (RESOURCE_ROOT / filename).read_bytes()
            with self.subTest(filename=filename):
                self.assertIsNone(PERSONAL_WINDOWS_PATH.search(payload))
                self.assertNotIn(private_user_token, payload.lower())

    def test_pyinstaller_spec_bundles_every_resource_at_runtime_path(self) -> None:
        spec = (FIXED_APP / "TripoSpectrumMapper_fixed.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn('"resources/filament_db"', spec)
        self.assertIn('"spectrum_mapper.filament_database"', spec)
        self.assertIn('"spectrum_mapper.filament_candidate_gui"', spec)
        self.assertIn('"spectrum_mapper.owned_filaments"', spec)
        for filename in RESOURCE_FILENAMES:
            with self.subTest(filename=filename):
                self.assertIn(f'"{filename}"', spec)

    def test_build_release_and_public_stage_verify_resources(self) -> None:
        build = (REPO_ROOT / "BUILD_AND_TEST.ps1").read_text(encoding="utf-8")
        package_path = (
            REPO_ROOT / "tooling" / "package_obj_adjuster_0_8beta.ps1"
        )
        package = (
            package_path.read_text(encoding="utf-8")
            if package_path.is_file()
            else None
        )
        stage = (REPO_ROOT / "tooling" / "stage_public_source.ps1").read_text(
            encoding="utf-8"
        )
        audit = (REPO_ROOT / "tooling" / "audit_public_tree.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("_internal\\resources\\filament_db", build)
        if package is not None:
            # The legacy private packager is deliberately absent from an
            # audited public-source stage.  Check it only in a development
            # tree where the historical script still exists.
            self.assertIn("_internal\\resources\\filament_db", package)
            self.assertIn("Assert-NoPersonalUserPath", package)
        self.assertIn(
            'Copy-PublicDirectory -RelativePath "source/fixed_app/resources/filament_db"',
            stage,
        )
        self.assertIn('".sqlite"', audit)
        for filename in RESOURCE_FILENAMES:
            with self.subTest(filename=filename):
                self.assertIn(f'"{filename}"', build)
                if package is not None:
                    self.assertIn(f'"{filename}"', package)

    def test_user_documentation_states_beta_candidate_boundaries(self) -> None:
        japanese = (FIXED_APP / "README_fixed_ja.md").read_text(encoding="utf-8")
        english = (FIXED_APP / "README_fixed_en.md").read_text(encoding="utf-8")
        for expected in (
            "フィラメント候補β",
            "最大3候補",
            "ΔE00",
            "実測値",
            "在庫",
            "手持ち4色",
            "owned_filaments.json",
            "近似探索",
        ):
            with self.subTest(language="ja", expected=expected):
                self.assertIn(expected, japanese)
        for expected in (
            "Filament candidates beta",
            "up to three",
            "Delta E 00",
            "measured versus catalog",
            "stock",
            "Automatic four-colour selection",
            "owned_filaments.json",
            "approximate beta search",
        ):
            with self.subTest(language="en", expected=expected):
                self.assertIn(expected, english)


if __name__ == "__main__":
    unittest.main()
