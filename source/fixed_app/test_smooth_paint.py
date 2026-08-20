from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import smooth_paint as smooth


def triangle_area(vertices: np.ndarray) -> float:
    triangle = np.asarray(vertices, dtype=np.float64)
    first = triangle[1, :2] - triangle[0, :2]
    second = triangle[2, :2] - triangle[0, :2]
    return abs(float(first[0] * second[1] - first[1] * second[0])) * 0.5


class PaintNodeTests(unittest.TestCase):
    def test_clone_is_deep_and_collapse_is_sparse(self) -> None:
        root = smooth.PaintNode(2)
        self.assertTrue(root.split_four())
        root.children[3].make_leaf(3)

        copied = root.clone()
        copied.children[3].make_leaf(2)
        copied.collapse()

        self.assertTrue(copied.is_leaf)
        self.assertEqual(copied.state, 2)
        self.assertFalse(root.is_leaf)
        self.assertEqual(root.children[3].state, 3)

    def test_dominant_state_uses_leaf_area_and_stable_tie_break(self) -> None:
        root = smooth.PaintNode.branch(
            (smooth.PaintNode(4), smooth.PaintNode(4), smooth.PaintNode(7)),
            split_sides=2,
            special_side=1,
        )
        # Orca's split-two child areas are 1/4, 1/4, and 1/2.
        self.assertEqual(root.state_areas()[4], 0.5)
        self.assertEqual(root.state_areas()[7], 0.5)
        self.assertEqual(root.dominant_state(), 4)

    def test_depth_limit_is_six(self) -> None:
        root = smooth.PaintNode(0)
        cursor = root
        for _ in range(smooth.MAX_DEPTH):
            cursor.split_four()
            cursor = cursor.children[0]
        root.validate()
        cursor.split_four()
        with self.assertRaises(smooth.SmoothPaintError):
            root.validate()


class TriangleSubdivisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.triangle = np.asarray(((0.0, 0.0), (4.0, 0.0), (0.0, 4.0)))

    def test_split_four_uses_official_child_order(self) -> None:
        children = smooth.subdivide_triangle(self.triangle)
        expected = (
            ((0.0, 0.0), (2.0, 0.0), (0.0, 2.0)),
            ((2.0, 0.0), (4.0, 0.0), (2.0, 2.0)),
            ((2.0, 2.0), (0.0, 4.0), (0.0, 2.0)),
            ((2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
        )
        for actual, wanted in zip(children, expected, strict=True):
            np.testing.assert_allclose(actual, wanted)

    def test_all_orca_split_layouts_preserve_area(self) -> None:
        source_area = triangle_area(self.triangle)
        expected_fractions = {
            1: (0.5, 0.5),
            2: (0.25, 0.25, 0.5),
            3: (0.25, 0.25, 0.25, 0.25),
        }
        for split_sides, fractions in expected_fractions.items():
            special_sides = (0,) if split_sides == 3 else (0, 1, 2)
            for special_side in special_sides:
                children = smooth.subdivide_triangle(
                    self.triangle,
                    split_sides=split_sides,
                    special_side=special_side,
                )
                actual = tuple(triangle_area(child) / source_area for child in children)
                np.testing.assert_allclose(actual, fractions)
                self.assertAlmostEqual(sum(actual), 1.0)

    def test_leaf_enumeration_matches_tree_areas_and_paths(self) -> None:
        root = smooth.PaintNode(0)
        root.split_four()
        root.children[1].split_four()
        root.children[1].children[2].make_leaf(8)

        leaves = list(smooth.iter_leaf_triangles(root, self.triangle))
        self.assertEqual(len(leaves), 7)
        self.assertEqual({leaf.depth for leaf in leaves}, {1, 2})
        self.assertIn((1, 2), {leaf.path for leaf in leaves})
        self.assertAlmostEqual(sum(leaf.area_fraction for leaf in leaves), 1.0)
        for leaf in leaves:
            self.assertAlmostEqual(
                triangle_area(leaf.vertices) / triangle_area(self.triangle),
                leaf.area_fraction,
            )


class CapsuleGeometryTests(unittest.TestCase):
    def test_triangle_capsule_classification(self) -> None:
        inside = np.asarray(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)))
        partial = np.asarray(((0.0, 0.0), (5.0, 0.0), (0.0, 5.0)))
        outside = np.asarray(((20.0, 20.0), (21.0, 20.0), (20.0, 21.0)))
        start = np.asarray((1.0, 1.0))
        end = np.asarray((3.0, 1.0))

        self.assertEqual(
            smooth.triangle_capsule_relation(inside, start, end, 2.0),
            smooth.CapsuleRelation.INSIDE,
        )
        self.assertEqual(
            smooth.triangle_capsule_relation(partial, start, end, 1.0),
            smooth.CapsuleRelation.PARTIAL,
        )
        self.assertEqual(
            smooth.triangle_capsule_relation(outside, start, end, 2.0),
            smooth.CapsuleRelation.OUTSIDE,
        )

    def test_capsule_paints_a_smooth_mixed_tree(self) -> None:
        triangle = np.asarray(((-10.0, -10.0), (10.0, -10.0), (0.0, 10.0)))
        root = smooth.PaintNode(0)
        result = smooth.apply_capsule(
            root,
            triangle,
            np.asarray((0.0, 0.0)),
            np.asarray((0.0, 0.0)),
            3.0,
            6,
            max_depth=6,
            min_edge_pixels=0.0,
        )

        self.assertTrue(result.changed)
        self.assertGreater(result.split_nodes, 0)
        self.assertLessEqual(root.max_depth(), smooth.MAX_DEPTH)
        self.assertGreater(root.state_areas()[6], 0.0)
        self.assertGreater(root.state_areas()[0], 0.0)
        expected_fraction = math.pi * 3.0**2 / triangle_area(triangle)
        self.assertAlmostEqual(root.state_areas()[6], expected_fraction, delta=0.025)

    def test_continuous_segment_is_not_reduced_to_one_face_seed(self) -> None:
        triangle = np.asarray(((-2.0, -5.0), (22.0, -5.0), (-2.0, 15.0)))
        point_tree = smooth.PaintNode(0)
        stroke_tree = smooth.PaintNode(0)
        smooth.apply_capsule(
            point_tree,
            triangle,
            np.asarray((2.0, 2.0)),
            np.asarray((2.0, 2.0)),
            1.5,
            1,
            max_depth=6,
            min_edge_pixels=0.0,
        )
        smooth.apply_capsule(
            stroke_tree,
            triangle,
            np.asarray((2.0, 2.0)),
            np.asarray((14.0, 2.0)),
            1.5,
            1,
            max_depth=6,
            min_edge_pixels=0.0,
        )
        self.assertGreater(stroke_tree.state_areas()[1], point_tree.state_areas()[1] * 2.0)

    def test_projector_is_used_for_model_space_triangle(self) -> None:
        triangle_3d = np.asarray(((0.0, 0.0, 4.0), (1.0, 0.0, 4.0), (0.0, 1.0, 4.0)))
        root = smooth.PaintNode(2)

        def projector(points: np.ndarray) -> np.ndarray:
            return points[:, :2] * 100.0

        result = smooth.apply_capsule(
            root,
            triangle_3d,
            np.asarray((50.0, 50.0)),
            np.asarray((50.0, 50.0)),
            80.0,
            9,
            projector=projector,
        )
        self.assertTrue(result.changed)
        self.assertTrue(root.is_leaf)
        self.assertEqual(root.state, 9)

    def test_outside_capsule_is_a_noop(self) -> None:
        triangle = np.asarray(((0.0, 0.0), (2.0, 0.0), (0.0, 2.0)))
        root = smooth.PaintNode(5)
        before = smooth.encode_paint_color(root)
        result = smooth.apply_capsule(
            root,
            triangle,
            np.asarray((50.0, 50.0)),
            np.asarray((60.0, 50.0)),
            2.0,
            1,
        )
        self.assertFalse(result.changed)
        self.assertEqual(smooth.encode_paint_color(root), before)


class MarkerGeometryTests(unittest.TestCase):
    def test_marker_nib_dimensions_angle_and_direction_following(self) -> None:
        horizontal = smooth.marker_stroke_polygon(
            np.asarray((0.0, 0.0)),
            np.asarray((0.0, 0.0)),
            8.0,
            thickness=2.0,
            angle_degrees=0.0,
        )
        np.testing.assert_allclose(horizontal.min(axis=0), (-4.0, -1.0), atol=1.0e-12)
        np.testing.assert_allclose(horizontal.max(axis=0), (4.0, 1.0), atol=1.0e-12)

        vertical = smooth.marker_stroke_polygon(
            np.asarray((0.0, 0.0)),
            np.asarray((0.0, 0.0)),
            8.0,
            thickness=2.0,
            angle_degrees=90.0,
        )
        np.testing.assert_allclose(vertical.min(axis=0), (-1.0, -4.0), atol=1.0e-12)
        np.testing.assert_allclose(vertical.max(axis=0), (1.0, 4.0), atol=1.0e-12)

        following = smooth.marker_stroke_polygon(
            np.asarray((0.0, 0.0)),
            np.asarray((10.0, 0.0)),
            8.0,
            thickness=2.0,
        )
        # The whole segment is swept, with half the nib thickness extending
        # past each endpoint and the long nib dimension across the stroke.
        np.testing.assert_allclose(following.min(axis=0), (-1.0, -4.0), atol=1.0e-12)
        np.testing.assert_allclose(following.max(axis=0), (11.0, 4.0), atol=1.0e-12)

    def test_triangle_marker_classification(self) -> None:
        start = np.asarray((0.0, 0.0))
        end = np.asarray((10.0, 0.0))
        inside = np.asarray(((2.0, -1.0), (3.0, -1.0), (2.0, 1.0)))
        partial = np.asarray(((9.0, 3.0), (13.0, 3.0), (9.0, 7.0)))
        outside = np.asarray(((20.0, 20.0), (21.0, 20.0), (20.0, 21.0)))

        self.assertEqual(
            smooth.triangle_marker_relation(inside, start, end, 8.0, thickness=2.0),
            smooth.StrokeRelation.INSIDE,
        )
        self.assertEqual(
            smooth.triangle_marker_relation(partial, start, end, 8.0, thickness=2.0),
            smooth.StrokeRelation.PARTIAL,
        )
        self.assertEqual(
            smooth.triangle_marker_relation(outside, start, end, 8.0, thickness=2.0),
            smooth.StrokeRelation.OUTSIDE,
        )

    def test_continuous_marker_segment_covers_more_than_one_nib_stamp(self) -> None:
        triangle = np.asarray(((-40.0, -40.0), (40.0, -40.0), (0.0, 40.0)))
        point_tree = smooth.PaintNode(0)
        stroke_tree = smooth.PaintNode(0)
        smooth.apply_marker(
            point_tree,
            triangle,
            np.asarray((-10.0, 0.0)),
            np.asarray((-10.0, 0.0)),
            8.0,
            5,
            thickness=2.0,
            max_depth=6,
            min_edge_pixels=0.0,
        )
        result = smooth.apply_marker(
            stroke_tree,
            triangle,
            np.asarray((-10.0, 0.0)),
            np.asarray((10.0, 0.0)),
            8.0,
            5,
            thickness=2.0,
            max_depth=6,
            min_edge_pixels=0.0,
        )

        self.assertTrue(result.changed)
        self.assertGreater(result.split_nodes, 0)
        self.assertGreater(stroke_tree.state_areas()[5], point_tree.state_areas()[5] * 5.0)
        self.assertLessEqual(result.visited_nodes, sum(4**depth for depth in range(7)))

    def test_marker_crosses_screen_edge_and_roundtrips_orca_codec(self) -> None:
        triangle = np.asarray(((-4.0, -4.0), (4.0, -4.0), (0.0, 4.0)))
        root = smooth.PaintNode(1)
        result = smooth.apply_marker(
            root,
            triangle,
            np.asarray((-8.0, 0.0)),
            np.asarray((2.0, 0.0)),
            4.0,
            7,
            thickness=1.0,
            max_depth=6,
            min_edge_pixels=0.0,
        )

        self.assertTrue(result.changed)
        self.assertGreater(root.state_areas()[7], 0.0)
        self.assertGreater(root.state_areas()[1], 0.0)
        encoded = smooth.encode_paint_color(root)
        self.assertEqual(smooth.encode_paint_color(smooth.decode_paint_color(encoded)), encoded)

    def test_marker_validates_dimensions_and_angle(self) -> None:
        point = np.asarray((0.0, 0.0))
        for invalid_width in (0.0, -1.0, math.inf, math.nan):
            with self.subTest(width=invalid_width):
                with self.assertRaises(smooth.SmoothPaintError):
                    smooth.marker_stroke_polygon(point, point, invalid_width)
        with self.assertRaises(smooth.SmoothPaintError):
            smooth.marker_stroke_polygon(point, point, 4.0, thickness=0.0)
        with self.assertRaises(smooth.SmoothPaintError):
            smooth.marker_stroke_polygon(point, point, 4.0, angle_degrees=math.nan)


class PaintColorCodecTests(unittest.TestCase):
    CODES = ("4", "8", "0C", "1C", "2C", "3C", "4C", "5C", "6C", "7C")

    def test_all_full_spectrum_leaf_codes(self) -> None:
        actual = tuple(smooth.encode_paint_color(smooth.PaintNode(state)) for state in range(10))
        self.assertEqual(actual, self.CODES)
        for state, code in enumerate(self.CODES):
            self.assertEqual(smooth.decode_paint_color(code).state, state)

    def test_official_child_and_hex_reverse_order(self) -> None:
        root = smooth.PaintNode.branch(
            tuple(smooth.PaintNode(state) for state in range(4)),
            split_sides=3,
        )
        # Independent expansion of Orca's node, reversed-child DFS, and final
        # hexadecimal reversal gives this exact vector.
        self.assertEqual(smooth.encode_paint_color(root), "480C1C3")
        decoded = smooth.decode_paint_color("480C1C3")
        self.assertEqual(tuple(child.state for child in decoded.children), (0, 1, 2, 3))

    def test_decode_reencode_preserves_all_official_split_shapes(self) -> None:
        samples = (
            smooth.PaintNode.branch(
                (smooth.PaintNode(1), smooth.PaintNode(8)),
                split_sides=1,
                special_side=2,
            ),
            smooth.PaintNode.branch(
                (smooth.PaintNode(9), smooth.PaintNode(3), smooth.PaintNode(5)),
                split_sides=2,
                special_side=1,
            ),
            smooth.PaintNode.branch(
                (
                    smooth.PaintNode(0),
                    smooth.PaintNode.branch(
                        tuple(smooth.PaintNode(state) for state in (2, 3, 4, 5)),
                        split_sides=3,
                    ),
                    smooth.PaintNode(8),
                    smooth.PaintNode(9),
                ),
                split_sides=3,
            ),
        )
        for root in samples:
            encoded = smooth.encode_paint_color(root)
            decoded = smooth.decode_paint_color(encoded)
            self.assertEqual(smooth.encode_paint_color(decoded), encoded)
            self.assertEqual(smooth.reencode_paint_color(encoded.lower()), encoded)

    def test_codec_rejects_invalid_or_non_full_spectrum_data(self) -> None:
        for invalid in ("", "xyz", "3", "0", "43"):
            with self.subTest(value=invalid):
                with self.assertRaises(smooth.PaintColorCodecError):
                    smooth.decode_paint_color(invalid)

    def test_codec_rejects_tree_deeper_than_six(self) -> None:
        root = smooth.PaintNode(0)
        cursor = root
        for _ in range(7):
            cursor.split_four()
            cursor = cursor.children[0]
        with self.assertRaises(smooth.SmoothPaintError):
            smooth.encode_paint_color(root)


if __name__ == "__main__":
    unittest.main()
