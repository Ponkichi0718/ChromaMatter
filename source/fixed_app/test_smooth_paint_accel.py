from __future__ import annotations

from pathlib import Path
import sys
import time
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import smooth_paint as smooth


TRIANGLE = np.asarray(((-50.0, -40.0), (60.0, -35.0), (-10.0, 70.0)))


def initial_tree(index: int) -> smooth.PaintNode:
    """Return non-collapsible leaf and official Orca branch variants."""

    mode = index % 5
    if mode == 0:
        return smooth.PaintNode(index % smooth.STATE_COUNT)
    if mode == 1:
        return smooth.PaintNode.branch(
            (smooth.PaintNode(0), smooth.PaintNode(3)),
            split_sides=1,
            special_side=index % 3,
        )
    if mode == 2:
        return smooth.PaintNode.branch(
            (smooth.PaintNode(1), smooth.PaintNode(4), smooth.PaintNode(7)),
            split_sides=2,
            special_side=index % 3,
        )
    if mode == 3:
        return smooth.PaintNode.branch(
            tuple(smooth.PaintNode(state) for state in (0, 2, 5, 8)),
            split_sides=3,
        )
    nested = smooth.PaintNode.branch(
        tuple(smooth.PaintNode(state) for state in (1, 3, 6, 9)),
        split_sides=3,
    )
    return smooth.PaintNode.branch(
        (nested, smooth.PaintNode(4)),
        split_sides=1,
        special_side=2,
    )


def assert_same_tree(test: unittest.TestCase, first: smooth.PaintNode, second: smooth.PaintNode) -> None:
    test.assertEqual(first, second)
    test.assertEqual(
        smooth.encode_paint_color(first),
        smooth.encode_paint_color(second),
    )


class SegmentBatchEquivalenceTests(unittest.TestCase):
    def test_random_round_segments_exactly_match_sequential_center_paint(self) -> None:
        rng = np.random.default_rng(0xC0FFEE)
        for trial in range(16):
            count = int(rng.integers(1, 9))
            segments = rng.uniform(-80.0, 80.0, size=(count, 2, 2))
            if trial % 3 == 0:
                segments[0, 1] = segments[0, 0]
            state = int(rng.integers(0, smooth.STATE_COUNT))
            radius = float(rng.uniform(0.0, 12.0))
            max_depth = int(rng.integers(2, 6))
            min_edge = float(rng.choice((0.0, 0.75, 2.0)))
            sequential = initial_tree(trial)
            batched = sequential.clone()

            for segment in segments:
                smooth.apply_capsule(
                    sequential,
                    TRIANGLE,
                    segment[0],
                    segment[1],
                    radius,
                    state,
                    max_depth=max_depth,
                    min_edge_pixels=min_edge,
                    boundary_rule="center",
                )
            smooth.apply_capsule_segments(
                batched,
                TRIANGLE,
                segments,
                radius,
                state,
                max_depth=max_depth,
                min_edge_pixels=min_edge,
                boundary_rule="center",
            )
            with self.subTest(trial=trial):
                assert_same_tree(self, sequential, batched)

    def test_random_marker_segments_exactly_match_both_angle_modes(self) -> None:
        rng = np.random.default_rng(0xBADC0DE)
        for angle_degrees in (None, 37.0):
            for trial in range(10):
                count = int(rng.integers(1, 8))
                segments = rng.uniform(-75.0, 75.0, size=(count, 2, 2))
                if trial % 4 == 0:
                    segments[0, 1] = segments[0, 0]
                state = int(rng.integers(0, smooth.STATE_COUNT))
                width = float(rng.uniform(1.0, 18.0))
                thickness = float(rng.uniform(0.5, 6.0))
                max_depth = int(rng.integers(2, 6))
                min_edge = float(rng.choice((0.0, 0.75, 2.0)))
                sequential = initial_tree(trial + 1)
                batched = sequential.clone()

                for segment in segments:
                    smooth.apply_marker(
                        sequential,
                        TRIANGLE,
                        segment[0],
                        segment[1],
                        width,
                        state,
                        thickness=thickness,
                        angle_degrees=angle_degrees,
                        max_depth=max_depth,
                        min_edge_pixels=min_edge,
                        boundary_rule="center",
                    )
                smooth.apply_marker_segments(
                    batched,
                    TRIANGLE,
                    segments,
                    width,
                    state,
                    thickness=thickness,
                    angle_degrees=angle_degrees,
                    max_depth=max_depth,
                    min_edge_pixels=min_edge,
                    boundary_rule="center",
                )
                with self.subTest(angle_degrees=angle_degrees, trial=trial):
                    assert_same_tree(self, sequential, batched)

    def test_all_boundary_rules_and_depth_extremes_match(self) -> None:
        segments = np.asarray(
            (
                ((-24.0, -8.0), (-5.0, 3.0)),
                ((-5.0, 3.0), (18.0, 9.0)),
                ((29.0, 22.0), (29.0, 22.0)),
            )
        )
        for boundary_rule in ("center", "inside", "intersect"):
            for max_depth in (0, smooth.MAX_DEPTH):
                for brush in ("round", "marker"):
                    sequential = initial_tree(max_depth + 2)
                    batched = sequential.clone()
                    if brush == "round":
                        for segment in segments:
                            smooth.apply_capsule(
                                sequential,
                                TRIANGLE,
                                segment[0],
                                segment[1],
                                5.5,
                                6,
                                max_depth=max_depth,
                                min_edge_pixels=0.0,
                                boundary_rule=boundary_rule,
                            )
                        smooth.apply_capsule_segments(
                            batched,
                            TRIANGLE,
                            segments,
                            5.5,
                            6,
                            max_depth=max_depth,
                            min_edge_pixels=0.0,
                            boundary_rule=boundary_rule,
                        )
                    else:
                        for segment in segments:
                            smooth.apply_marker(
                                sequential,
                                TRIANGLE,
                                segment[0],
                                segment[1],
                                9.0,
                                6,
                                thickness=2.5,
                                angle_degrees=21.0,
                                max_depth=max_depth,
                                min_edge_pixels=0.0,
                                boundary_rule=boundary_rule,
                            )
                        smooth.apply_marker_segments(
                            batched,
                            TRIANGLE,
                            segments,
                            9.0,
                            6,
                            thickness=2.5,
                            angle_degrees=21.0,
                            max_depth=max_depth,
                            min_edge_pixels=0.0,
                            boundary_rule=boundary_rule,
                        )
                    with self.subTest(
                        boundary_rule=boundary_rule,
                        max_depth=max_depth,
                        brush=brush,
                    ):
                        assert_same_tree(self, sequential, batched)

    def test_every_existing_orca_branch_shape_matches(self) -> None:
        segments = np.asarray(
            (((-18.0, -2.0), (12.0, 5.0)), ((12.0, 5.0), (25.0, 11.0)))
        )
        for initial_index in (1, 2, 3, 4):
            for brush in ("round", "marker"):
                sequential = initial_tree(initial_index)
                batched = sequential.clone()
                if brush == "round":
                    for segment in segments:
                        smooth.apply_capsule(
                            sequential,
                            TRIANGLE,
                            segment[0],
                            segment[1],
                            4.0,
                            9,
                            max_depth=4,
                            min_edge_pixels=0.5,
                        )
                    smooth.apply_capsule_segments(
                        batched,
                        TRIANGLE,
                        segments,
                        4.0,
                        9,
                        max_depth=4,
                        min_edge_pixels=0.5,
                    )
                else:
                    for segment in segments:
                        smooth.apply_marker(
                            sequential,
                            TRIANGLE,
                            segment[0],
                            segment[1],
                            8.0,
                            9,
                            thickness=2.0,
                            max_depth=4,
                            min_edge_pixels=0.5,
                        )
                    smooth.apply_marker_segments(
                        batched,
                        TRIANGLE,
                        segments,
                        8.0,
                        9,
                        thickness=2.0,
                        max_depth=4,
                        min_edge_pixels=0.5,
                    )
                with self.subTest(initial_index=initial_index, brush=brush):
                    assert_same_tree(self, sequential, batched)

    def test_projector_path_matches_for_round_and_marker(self) -> None:
        triangle_3d = np.asarray(
            ((-1.0, -1.0, 3.0), (1.2, -0.8, 4.0), (-0.3, 1.4, 5.0))
        )

        def projector(points: np.ndarray) -> np.ndarray:
            return points[:, :2] * np.asarray((42.0, 35.0)) + np.asarray((7.0, -4.0))

        segments = np.asarray(
            (((-22.0, -10.0), (2.0, 4.0)), ((2.0, 4.0), (29.0, 15.0)))
        )
        for brush in ("round", "marker"):
            sequential = initial_tree(2)
            batched = sequential.clone()
            if brush == "round":
                for segment in segments:
                    smooth.apply_capsule(
                        sequential,
                        triangle_3d,
                        segment[0],
                        segment[1],
                        4.5,
                        8,
                        projector=projector,
                        max_depth=5,
                        min_edge_pixels=0.0,
                    )
                smooth.apply_capsule_segments(
                    batched,
                    triangle_3d,
                    segments,
                    4.5,
                    8,
                    projector=projector,
                    max_depth=5,
                    min_edge_pixels=0.0,
                )
            else:
                for segment in segments:
                    smooth.apply_marker(
                        sequential,
                        triangle_3d,
                        segment[0],
                        segment[1],
                        8.0,
                        8,
                        thickness=2.0,
                        angle_degrees=33.0,
                        projector=projector,
                        max_depth=5,
                        min_edge_pixels=0.0,
                    )
                smooth.apply_marker_segments(
                    batched,
                    triangle_3d,
                    segments,
                    8.0,
                    8,
                    thickness=2.0,
                    angle_degrees=33.0,
                    projector=projector,
                    max_depth=5,
                    min_edge_pixels=0.0,
                )
            with self.subTest(brush=brush):
                assert_same_tree(self, sequential, batched)

    def test_empty_batch_is_a_valid_noop(self) -> None:
        empty = np.empty((0, 2, 2), dtype=np.float64)
        for brush in ("round", "marker"):
            root = initial_tree(4)
            before = root.clone()
            if brush == "round":
                result = smooth.apply_capsule_segments(root, TRIANGLE, empty, 3.0, 7)
            else:
                result = smooth.apply_marker_segments(
                    root,
                    TRIANGLE,
                    empty,
                    7.0,
                    7,
                    thickness=2.0,
                )
            with self.subTest(brush=brush):
                self.assertFalse(result.changed)
                self.assertEqual(result.visited_nodes, 0)
                assert_same_tree(self, root, before)

    def test_batch_rejects_bad_segment_arrays(self) -> None:
        invalid_arrays = (
            np.zeros((2, 2), dtype=np.float64),
            np.zeros((2, 3, 2), dtype=np.float64),
            np.asarray((((0.0, 0.0), (np.nan, 1.0)),)),
        )
        for segments in invalid_arrays:
            for brush in ("round", "marker"):
                with self.subTest(shape=segments.shape, brush=brush):
                    with self.assertRaises(smooth.SmoothPaintError):
                        if brush == "round":
                            smooth.apply_capsule_segments(
                                smooth.PaintNode(0), TRIANGLE, segments, 2.0, 1
                            )
                        else:
                            smooth.apply_marker_segments(
                                smooth.PaintNode(0), TRIANGLE, segments, 5.0, 1
                            )


class SegmentBatchBenchmarkTests(unittest.TestCase):
    @staticmethod
    def _best_elapsed(function: object, repeats: int = 3) -> float:
        samples: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            function()  # type: ignore[operator]
            samples.append(time.perf_counter() - started)
        return min(samples)

    def test_adjacent_segment_batches_have_an_effective_speedup(self) -> None:
        triangle = np.asarray(((-100.0, -80.0), (100.0, -80.0), (0.0, 100.0)))
        x_values = np.linspace(-65.0, 65.0, 65)
        points = np.column_stack((x_values, 8.0 * np.sin(x_values / 18.0)))
        segments = np.stack((points[:-1], points[1:]), axis=1)

        for brush in ("round", "marker"):
            def sequential() -> smooth.PaintNode:
                root = smooth.PaintNode(0)
                for segment in segments:
                    if brush == "round":
                        smooth.apply_capsule(
                            root,
                            triangle,
                            segment[0],
                            segment[1],
                            5.0,
                            4,
                            max_depth=5,
                            min_edge_pixels=0.0,
                        )
                    else:
                        smooth.apply_marker(
                            root,
                            triangle,
                            segment[0],
                            segment[1],
                            10.0,
                            4,
                            thickness=3.0,
                            max_depth=5,
                            min_edge_pixels=0.0,
                        )
                return root

            def batched() -> smooth.PaintNode:
                root = smooth.PaintNode(0)
                if brush == "round":
                    smooth.apply_capsule_segments(
                        root,
                        triangle,
                        segments,
                        5.0,
                        4,
                        max_depth=5,
                        min_edge_pixels=0.0,
                    )
                else:
                    smooth.apply_marker_segments(
                        root,
                        triangle,
                        segments,
                        10.0,
                        4,
                        thickness=3.0,
                        max_depth=5,
                        min_edge_pixels=0.0,
                    )
                return root

            assert_same_tree(self, sequential(), batched())
            sequential()
            batched()
            sequential_elapsed = self._best_elapsed(sequential)
            batched_elapsed = self._best_elapsed(batched)
            speedup = sequential_elapsed / batched_elapsed
            print(
                f"smooth-paint {brush} 64-segment speedup: {speedup:.2f}x "
                f"({sequential_elapsed:.4f}s -> {batched_elapsed:.4f}s)"
            )
            with self.subTest(brush=brush):
                self.assertLess(
                    batched_elapsed,
                    sequential_elapsed * 0.90,
                    f"{brush} batching did not provide a measurable speedup",
                )


if __name__ == "__main__":
    unittest.main()
