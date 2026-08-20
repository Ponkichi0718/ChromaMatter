from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sqlite3
import unittest


FIXED_APP = Path(__file__).resolve().parent
REPO_ROOT = FIXED_APP.parents[1]
DATABASE = (
    FIXED_APP
    / "resources"
    / "filament_db"
    / "filament_color_database_2026-08.sqlite"
)
README = (
    FIXED_APP
    / "resources"
    / "filament_db"
    / "filament_color_database_README.md"
)
ATTRIBUTION = FIXED_APP / "resources" / "filament_db" / "ATTRIBUTION.md"
UPDATER = REPO_ROOT / "tooling" / "update_budget_filament_library.py"

EXPECTED_DATABASE_SHA256 = "d04bd3b6f2a7d336e3ad4bcc5646b166ae2cfd8b94c991b9205aa449148c0e8c"
EXPECTED_MATERIAL_COUNTS = {"ABS": 268, "PETG": 652, "PLA": 2577}
EXPECTED_BUDGET_COUNTS = {
    ("cc3d", "ABS"): 3,
    ("cc3d", "PETG"): 11,
    ("cc3d", "PLA"): 27,
    ("geeetech", "ABS"): 17,
    ("geeetech", "PETG"): 12,
    ("geeetech", "PLA"): 50,
    ("kingroon", "ABS"): 10,
    ("kingroon", "PETG"): 21,
    ("kingroon", "PLA"): 37,
    ("tinmorry", "ABS"): 4,
    ("tinmorry", "PETG"): 74,
    ("tinmorry", "PLA"): 46,
}
QUALIFIED_BRANDS = {"CC3D", "Geeetech", "Kingroon", "TINMORRY"}


class BudgetFilamentLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.connection = sqlite3.connect(
            f"file:{DATABASE.as_posix()}?mode=ro",
            uri=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.connection.close()

    def test_database_hash_and_integrity_are_release_locked(self) -> None:
        self.assertEqual(
            hashlib.sha256(DATABASE.read_bytes()).hexdigest(),
            EXPECTED_DATABASE_SHA256,
        )
        self.assertEqual(
            self.connection.execute("PRAGMA quick_check").fetchone()[0],
            "ok",
        )

    def test_catalog_contains_only_normalized_supported_materials(self) -> None:
        counts = dict(
            self.connection.execute(
                "SELECT material, COUNT(*) FROM catalog_colors GROUP BY material"
            )
        )
        self.assertEqual(counts, EXPECTED_MATERIAL_COUNTS)
        self.assertEqual(sum(counts.values()), 3497)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(DISTINCT brand) FROM catalog_colors"
            ).fetchone()[0],
            19,
        )

    def test_each_qualified_budget_brand_has_all_three_materials(self) -> None:
        counts = dict(
            self.connection.execute(
                """
                SELECT brand_slug || ':' || material, COUNT(*)
                  FROM catalog_colors
                 WHERE brand_slug IN ('geeetech', 'cc3d', 'kingroon', 'tinmorry')
              GROUP BY brand_slug, material
                """
            )
        )
        expected = {
            f"{brand}:{material}": count
            for (brand, material), count in EXPECTED_BUDGET_COUNTS.items()
        }
        self.assertEqual(counts, expected)
        self.assertEqual(sum(counts.values()), 312)

    def test_budget_colors_come_from_pinned_ofd_not_amazon_images(self) -> None:
        invalid = self.connection.execute(
            """
            SELECT record_id, reference_hex, catalog_source_url
              FROM catalog_colors
             WHERE brand_slug IN ('geeetech', 'cc3d', 'kingroon', 'tinmorry')
               AND (
                    reference_hex NOT GLOB '#[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]'
                    OR catalog_source_url NOT LIKE '%dataset-v2026.08.16%'
                    OR LOWER(catalog_source_url) LIKE '%amazon%'
               )
            """
        ).fetchall()
        self.assertEqual(invalid, [])
        self.assertEqual(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM catalog_colors
                 WHERE brand_slug IN ('geeetech', 'cc3d', 'kingroon', 'tinmorry')
                   AND record_id = 'ofd:' || variant_id
                """
            ).fetchone()[0],
            312,
        )

    def test_amazon_evidence_qualifies_manufacturers_not_catalog_rows(self) -> None:
        rows = self.connection.execute(
            """
            SELECT brand, material, asin, product_url, rating, review_count,
                   retrieved_date, acceptance_rule, evidence_scope, notes
              FROM amazon_jp_evidence
          ORDER BY brand, material, asin
            """
        ).fetchall()
        self.assertEqual(len(rows), 14)
        self.assertEqual({row[0] for row in rows}, QUALIFIED_BRANDS)
        for (
            _brand,
            material,
            asin,
            url,
            rating,
            review_count,
            date,
            rule,
            scope,
            notes,
        ) in rows:
            with self.subTest(asin=asin):
                self.assertIn(material, EXPECTED_MATERIAL_COUNTS)
                self.assertRegex(asin, r"^[A-Z0-9]{10}$")
                self.assertEqual(url, f"https://www.amazon.co.jp/dp/{asin}")
                self.assertGreaterEqual(rating, 4.0)
                self.assertGreaterEqual(review_count, 20)
                self.assertEqual(date, "2026-08-19")
                self.assertIn("AND", rule)
                self.assertEqual(scope, "manufacturer qualification only")
                self.assertIn("does not mean", notes)

    def test_amazonbasics_is_not_admitted_without_current_jp_evidence(self) -> None:
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM catalog_colors WHERE brand_slug = 'amazonbasics'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM amazon_jp_evidence WHERE brand = 'AmazonBasics'"
            ).fetchone()[0],
            0,
        )

    def test_meta_and_docs_state_boundaries_and_reproducibility(self) -> None:
        meta = dict(self.connection.execute("SELECT key, value FROM meta"))
        self.assertEqual(meta["catalog_materials"], "PLA,ABS,PETG")
        self.assertEqual(meta["catalog_color_count"], "3497")
        self.assertEqual(meta["budget_catalog_color_count"], "312")
        self.assertEqual(meta["budget_ofd_version"], "v2026.08.16")
        self.assertEqual(meta["amazon_jp_evidence_count"], "14")
        self.assertIn("Manufacturer qualification", meta["amazon_jp_evidence_note"])

        combined = README.read_text(encoding="utf-8") + ATTRIBUTION.read_text(
            encoding="utf-8"
        )
        for expected in (
            "PLA (default), ABS, PETG",
            "manufacturer qualification only",
            "rating >= 4.0 AND review_count >= 20",
            "not separately for every colour or SKU",
            "No Amazon image was used",
            "AmazonBasics was excluded",
            "81b06c646ef310fe7911cb230f96094e78bdeb43",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, combined)

        updater = UPDATER.read_text(encoding="utf-8")
        self.assertIn("BASE_DATABASE_SHA256", updater)
        self.assertIn("dataset-v2026.08.16", updater)
        self.assertIn("expected 1080", updater)
        for slug in ("geeetech", "cc3d", "kingroon", "tinmorry"):
            self.assertIn(f'"{slug}"', updater)


if __name__ == "__main__":
    unittest.main()
