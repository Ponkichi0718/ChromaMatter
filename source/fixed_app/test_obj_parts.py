from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.engine import load_vertex_color_obj


REAL_OBJ_ENV = "TRIPO_SPECTRUM_REAL_PARTS_OBJ"


def _vertex(x: float, y: float, z: float, r: float = 0.2) -> str:
    return f"v {x} {y} {z} {r} 0.3 0.4"


@contextmanager
def _temporary_obj(source: str):
    with tempfile.TemporaryDirectory(prefix="tripo-parts-test-") as directory:
        path = Path(directory) / "parts.obj"
        path.write_text(
            textwrap.dedent(source).strip() + "\n",
            encoding="utf-8",
            newline="\n",
        )
        yield path


class ObjPartRecognitionTests(unittest.TestCase):
    def assert_part_contract(self, asset) -> None:
        part_count = len(asset.part_names)
        self.assertGreaterEqual(part_count, 1)
        self.assertEqual(len(asset.part_keys), part_count)
        self.assertEqual(len(asset.part_face_counts), part_count)
        self.assertEqual(len(asset.part_vertex_counts), part_count)
        self.assertEqual(asset.face_part_ids.shape, (len(asset.faces),))
        self.assertTrue(np.issubdtype(asset.face_part_ids.dtype, np.integer))
        self.assertGreaterEqual(int(asset.face_part_ids.min()), 0)
        self.assertLess(int(asset.face_part_ids.max()), part_count)
        np.testing.assert_array_equal(
            np.bincount(asset.face_part_ids, minlength=part_count),
            np.asarray(asset.part_face_counts, dtype=np.int64),
        )
        self.assertEqual(sum(asset.part_face_counts), len(asset.faces))

    def test_object_markers_take_priority_over_groups(self) -> None:
        source = f"""
            g ignored_before_first_object
            o body shell
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(0, 1, 0)}
            f 1 2 3
            g ignored_inside_body
            {_vertex(0, 0, 1)}
            f 1 3 4
            o accessory
            {_vertex(2, 0, 0)}
            {_vertex(3, 0, 0)}
            {_vertex(2, 1, 0)}
            f 5 6 7
        """
        with _temporary_obj(source) as path:
            asset = load_vertex_color_obj(path)

        self.assertEqual(asset.part_names, ("body shell", "accessory"))
        self.assertEqual(asset.part_keys, ("0:body shell", "1:accessory"))
        self.assertEqual(asset.part_face_counts, (2, 1))
        np.testing.assert_array_equal(asset.face_part_ids, [0, 0, 1])
        self.assertEqual(asset.part_marker_kind, "o")
        self.assertTrue(asset.has_explicit_parts)
        self.assert_part_contract(asset)

    def test_groups_are_used_when_no_object_marker_exists(self) -> None:
        source = f"""
            g main body
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(0, 1, 0)}
            f 1 2 3
            g trim
            {_vertex(0, 0, 1)}
            {_vertex(1, 0, 1)}
            {_vertex(0, 1, 1)}
            f 4 5 6
        """
        with _temporary_obj(source) as path:
            asset = load_vertex_color_obj(path)

        self.assertEqual(asset.part_names, ("main body", "trim"))
        self.assertEqual(asset.part_keys, ("0:main body", "1:trim"))
        np.testing.assert_array_equal(asset.face_part_ids, [0, 1])
        self.assertEqual(asset.part_marker_kind, "g")
        self.assertTrue(asset.has_explicit_parts)
        self.assert_part_contract(asset)

    def test_markerless_obj_is_one_stable_part(self) -> None:
        source = f"""
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(0, 1, 0)}
            {_vertex(0, 0, 1)}
            f 1 2 3
            f 1 4 2
        """
        with _temporary_obj(source) as path:
            first = load_vertex_color_obj(path)
            second = load_vertex_color_obj(path)

        self.assertEqual(len(first.part_names), 1)
        self.assertEqual(first.part_names, second.part_names)
        self.assertEqual(first.part_keys, second.part_keys)
        self.assertEqual(first.part_keys, (f"0:{first.part_names[0]}",))
        self.assertEqual(first.part_face_counts, (2,))
        np.testing.assert_array_equal(first.face_part_ids, [0, 0])
        self.assertIsNone(first.part_marker_kind)
        self.assertFalse(first.has_explicit_parts)
        self.assert_part_contract(first)

    def test_one_object_marker_is_a_named_single_model_not_multipart(self) -> None:
        source = f"""
            o named whole
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(0, 1, 0)}
            f 1 2 3
        """
        with _temporary_obj(source) as path:
            asset = load_vertex_color_obj(path)

        self.assertEqual(asset.part_names, ("named whole",))
        self.assertEqual(asset.part_marker_kind, "o")
        self.assertFalse(asset.has_explicit_parts)
        self.assert_part_contract(asset)

    def test_one_global_object_does_not_hide_multiple_face_groups(self) -> None:
        source = f"""
            o global object
            g body
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(0, 1, 0)}
            f 1 2 3
            g accessory
            {_vertex(0, 0, 1)}
            {_vertex(1, 0, 1)}
            {_vertex(0, 1, 1)}
            f 4 5 6
        """
        with _temporary_obj(source) as path:
            asset = load_vertex_color_obj(path)

        self.assertEqual(asset.part_names, ("body", "accessory"))
        self.assertEqual(asset.part_marker_kind, "g")
        self.assertTrue(asset.has_explicit_parts)
        np.testing.assert_array_equal(asset.face_part_ids, [0, 1])
        self.assert_part_contract(asset)

    def test_one_group_marker_is_a_named_single_model_not_multipart(self) -> None:
        source = f"""
            g named whole
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(0, 1, 0)}
            f 1 2 3
        """
        with _temporary_obj(source) as path:
            asset = load_vertex_color_obj(path)

        self.assertEqual(asset.part_names, ("named whole",))
        self.assertEqual(asset.part_marker_kind, "g")
        self.assertFalse(asset.has_explicit_parts)
        self.assert_part_contract(asset)

    def test_ngon_fan_triangulation_keeps_the_source_part(self) -> None:
        source = f"""
            o pentagon
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(2, 1, 0)}
            {_vertex(1, 2, 0)}
            {_vertex(0, 1, 0)}
            f 1 2 3 4 5
        """
        with _temporary_obj(source) as path:
            asset = load_vertex_color_obj(path)

        np.testing.assert_array_equal(
            asset.faces,
            [[0, 1, 2], [0, 2, 3], [0, 3, 4]],
        )
        np.testing.assert_array_equal(asset.face_part_ids, [0, 0, 0])
        self.assertEqual(asset.part_face_counts, (3,))
        self.assert_part_contract(asset)

    def test_negative_indices_are_resolved_at_the_face_line(self) -> None:
        source = f"""
            o negative
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(1, 1, 0)}
            {_vertex(0, 1, 0)}
            f -4 -3 -2 -1
        """
        with _temporary_obj(source) as path:
            asset = load_vertex_color_obj(path)

        np.testing.assert_array_equal(
            asset.faces,
            [[0, 1, 2], [0, 2, 3]],
        )
        np.testing.assert_array_equal(asset.face_part_ids, [0, 0])
        self.assert_part_contract(asset)

    def test_empty_markers_are_pruned_and_duplicate_names_get_stable_keys(self) -> None:
        source = f"""
            o empty_before
            o duplicate
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(0, 1, 0)}
            f 1 2 3
            o empty_between
            o duplicate
            {_vertex(0, 0, 1)}
            {_vertex(1, 0, 1)}
            {_vertex(0, 1, 1)}
            f 4 5 6
            o empty_after
        """
        with _temporary_obj(source) as path:
            first = load_vertex_color_obj(path)
            second = load_vertex_color_obj(path)

        self.assertEqual(first.part_names, ("duplicate", "duplicate"))
        self.assertEqual(first.part_keys, ("0:duplicate", "1:duplicate"))
        self.assertEqual(first.part_keys, second.part_keys)
        self.assertEqual(first.part_face_counts, (1, 1))
        self.assertEqual(first.part_vertex_counts, (3, 3))
        np.testing.assert_array_equal(first.face_part_ids, [0, 1])
        self.assertEqual(first.part_marker_kind, "o")
        self.assertTrue(first.has_explicit_parts)
        self.assert_part_contract(first)

    def test_face_part_ids_match_fan_expansion_and_compact_part_order(self) -> None:
        source = f"""
            o first
            {_vertex(0, 0, 0)}
            {_vertex(1, 0, 0)}
            {_vertex(1, 1, 0)}
            {_vertex(0, 1, 0)}
            f 1 2 3 4
            o empty
            o second
            {_vertex(0, 0, 1)}
            {_vertex(1, 0, 1)}
            {_vertex(0, 1, 1)}
            f 5 6 7
        """
        with _temporary_obj(source) as path:
            asset = load_vertex_color_obj(path)

        self.assertEqual(asset.part_names, ("first", "second"))
        self.assertEqual(asset.part_face_counts, (2, 1))
        np.testing.assert_array_equal(asset.face_part_ids, [0, 0, 1])
        self.assertEqual(asset.part_marker_kind, "o")
        self.assertTrue(asset.has_explicit_parts)
        self.assert_part_contract(asset)


class OptionalPrivateMultipartRecognitionTests(unittest.TestCase):
    def test_user_supplied_multipart_obj(self) -> None:
        configured = os.environ.get(REAL_OBJ_ENV)
        if not configured:
            self.skipTest(
                f"set {REAL_OBJ_ENV} to run a private multipart OBJ check"
            )
        path = Path(configured).expanduser()
        if not path.is_file():
            self.fail(f"{REAL_OBJ_ENV} does not point to a file")

        asset = load_vertex_color_obj(path)

        self.assertEqual(asset.part_marker_kind, "o")
        self.assertTrue(asset.has_explicit_parts)
        self.assertGreaterEqual(len(asset.part_names), 2)
        self.assertEqual(len(asset.face_part_ids), len(asset.faces))
        self.assertEqual(sum(asset.part_face_counts), len(asset.faces))
        np.testing.assert_array_equal(
            np.bincount(
                asset.face_part_ids,
                minlength=len(asset.part_names),
            ),
            np.asarray(asset.part_face_counts, dtype=np.int64),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
