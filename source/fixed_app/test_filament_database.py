from __future__ import annotations

import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.filament_database import (
    DATABASE_FILENAME,
    FilamentMatcher,
    FilamentRepository,
    ciede2000,
    normalize_hex,
    resolve_filament_database_path,
    srgb_hex_to_lab,
)


RESOURCE_DB = (
    Path(__file__).resolve().parent
    / "resources"
    / "filament_db"
    / DATABASE_FILENAME
)
EXPECTED_SHA256 = "d04bd3b6f2a7d336e3ad4bcc5646b166ae2cfd8b94c991b9205aa449148c0e8c"


class FilamentColorMathTests(unittest.TestCase):
    def test_hex_normalization_is_strict(self) -> None:
        self.assertEqual(normalize_hex("e32636"), "#E32636")
        self.assertEqual(normalize_hex(" #f5f5f5 "), "#F5F5F5")
        for invalid in ("#FFF", "#GG0000", "1234567", "", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_hex(invalid)  # type: ignore[arg-type]

    def test_srgb_d65_black_and_white(self) -> None:
        black = srgb_hex_to_lab("#000000")
        white = srgb_hex_to_lab("#FFFFFF")
        self.assertAlmostEqual(black[0], 0.0, places=10)
        self.assertAlmostEqual(black[1], 0.0, places=10)
        self.assertAlmostEqual(black[2], 0.0, places=10)
        self.assertAlmostEqual(white[0], 100.0, places=4)
        self.assertAlmostEqual(white[1], 0.0, places=3)
        self.assertAlmostEqual(white[2], 0.0, places=3)

    def test_published_ciede2000_reference_pairs(self) -> None:
        # Sharma, Wu and Dalal supplementary test data, first four pairs.
        cases = (
            ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
            ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
            ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
            ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
        )
        for first, second, expected in cases:
            with self.subTest(expected=expected):
                self.assertAlmostEqual(ciede2000(first, second), expected, places=4)
                self.assertAlmostEqual(ciede2000(second, first), expected, places=4)

    def test_identical_colours_have_zero_delta(self) -> None:
        lab = srgb_hex_to_lab("#3867D6")
        self.assertEqual(ciede2000(lab, lab), 0.0)


class FilamentRepositoryTests(unittest.TestCase):
    def test_bundled_database_hash_schema_and_counts(self) -> None:
        self.assertEqual(resolve_filament_database_path(), RESOURCE_DB)
        digest = hashlib.sha256(RESOURCE_DB.read_bytes()).hexdigest()
        self.assertEqual(digest, EXPECTED_SHA256)

        repository = FilamentRepository()
        self.assertEqual(repository.catalog_count, 3497)
        self.assertEqual(repository.measured_count, 41)
        self.assertEqual(repository.meta["color_space"], "sRGB D65 -> CIELAB D65")
        self.assertEqual(repository.meta["distance_metric"], "CIEDE2000")

    def test_connection_is_read_only_and_creates_no_sidecars(self) -> None:
        repository = FilamentRepository()
        with closing(repository._connect()) as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE forbidden_write(value TEXT)")
        self.assertFalse(RESOURCE_DB.with_name(RESOURCE_DB.name + "-wal").exists())
        self.assertFalse(RESOURCE_DB.with_name(RESOURCE_DB.name + "-shm").exists())

    def test_missing_database_disables_only_the_matcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.sqlite"
            matcher = FilamentMatcher(missing)
            self.assertFalse(matcher.is_available)
            self.assertIn("見つかりません", matcher.error_message or "")
            self.assertEqual(matcher.find_matches("#E32636"), ())
            self.assertEqual(matcher.available_brands(), ())

    def test_corrupt_and_wrong_schema_databases_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corrupt = root / "corrupt.sqlite"
            corrupt.write_bytes(b"not a sqlite database")
            corrupt_matcher = FilamentMatcher(corrupt)
            self.assertFalse(corrupt_matcher.is_available)
            self.assertEqual(corrupt_matcher.find_matches("#FFFFFF"), ())

            wrong_schema = root / "wrong-schema.sqlite"
            with closing(sqlite3.connect(wrong_schema)) as connection:
                connection.execute("CREATE TABLE catalog_colors(record_id TEXT)")
                connection.commit()
            schema_matcher = FilamentMatcher(wrong_schema)
            self.assertFalse(schema_matcher.is_available)
            self.assertIn("必須テーブル", schema_matcher.error_message or "")


class FilamentMatcherRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matcher = FilamentMatcher()
        if not cls.matcher.is_available:
            raise AssertionError(cls.matcher.error_message)

    def test_filters_can_be_enumerated(self) -> None:
        brands = self.matcher.available_brands()
        finishes = self.matcher.available_finish_classes()
        self.assertEqual(len(brands), 19)
        self.assertIn("Snapmaker", brands)
        self.assertIn("標準/不透明", finishes)
        self.assertIn("マット", finishes)

    def test_red_reference_candidates_are_preserved(self) -> None:
        matches = self.matcher.find_matches("#E32636", limit=10)
        lookup = {(match.brand, match.series, match.color_name): match for match in matches}
        hatchbox = lookup[("Hatchbox", "PLA", "Red Filament")]
        sunlu = lookup[("SUNLU", "Upgrade PLA", "Red")]
        self.assertAlmostEqual(hatchbox.delta_e_2000, 1.665, delta=0.002)
        self.assertAlmostEqual(sunlu.delta_e_2000, 1.665, delta=0.002)

    def test_equal_white_hex_has_exact_zero_distance(self) -> None:
        matches = self.matcher.find_matches("#F5F5F5", limit=10)
        exact = [match for match in matches if match.matched_hex == "#F5F5F5"]
        self.assertTrue(exact)
        self.assertEqual(exact[0].delta_e_2000, 0.0)

    def test_brand_and_finish_filters_and_finish_penalty(self) -> None:
        matches = self.matcher.find_matches(
            "#E32636",
            limit=20,
            brands=("Eryone",),
            finish_classes=("マット",),
        )
        self.assertTrue(matches)
        self.assertTrue(all(match.brand == "Eryone" for match in matches))
        self.assertTrue(all(match.finish_class == "マット" for match in matches))
        for match in matches:
            self.assertAlmostEqual(
                match.score,
                match.delta_e_2000 + match.finish_penalty,
                places=12,
            )

    def test_measured_preference_replaces_linked_catalog_row(self) -> None:
        record_id = "ofd:02eaa799-16a4-5a41-a641-980f31312c69"
        measured_first = self.matcher.find_matches(
            "#C13A3D", limit=10_000, brands=("Bambu Lab",), prefer_measured=True
        )
        catalog_first = self.matcher.find_matches(
            "#C13A3D", limit=10_000, brands=("Bambu Lab",), prefer_measured=False
        )
        measured_product = [match for match in measured_first if match.record_id == record_id]
        catalog_product = [match for match in catalog_first if match.record_id == record_id]
        self.assertEqual(len(measured_product), 1)
        self.assertEqual(measured_product[0].source_kind, "measured")
        self.assertEqual(measured_product[0].measurement_id, "measured:001")
        self.assertEqual(len(catalog_product), 1)
        self.assertEqual(catalog_product[0].source_kind, "catalog")
        self.assertIsNone(catalog_product[0].measurement_id)

    def test_unlinked_measured_finish_uses_finish_class_penalty(self) -> None:
        matches = self.matcher.find_matches("#B59578", limit=10_000)
        wood = [
            match
            for match in matches
            if match.measurement_id == "measured:039"
        ]
        self.assertEqual(len(wood), 1)
        self.assertEqual(wood[0].source_kind, "measured")
        self.assertEqual(wood[0].finish_class, "木質")
        self.assertEqual(wood[0].matched_hex, "#B59578")
        self.assertEqual(wood[0].delta_e_2000, 0.0)
        self.assertEqual(wood[0].finish_penalty, 4.0)
        self.assertEqual(wood[0].score, 4.0)

    def test_all_results_remove_exact_display_duplicates(self) -> None:
        matches = self.matcher.find_matches("#778899", limit=10_000)
        keys = [
            (
                match.brand.casefold(),
                match.series.casefold(),
                match.color_name.casefold(),
                match.matched_hex,
            )
            for match in matches
        ]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
