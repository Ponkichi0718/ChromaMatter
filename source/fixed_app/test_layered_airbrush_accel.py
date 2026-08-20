from __future__ import annotations

from pathlib import Path
import sys
import time
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import smooth_paint as smooth
from spectrum_mapper.paint_tools import airbrush_state_layers


TRIANGLE = np.asarray(((-50.0, -40.0), (60.0, -35.0), (-10.0, 70.0)))


def apply_sequential(
    node: smooth.PaintNode,
    triangle: np.ndarray,
    segments: np.ndarray,
    radii: np.ndarray,
    layers: tuple[tuple[float, int], ...],
    *,
    projector: smooth.Projector | None = None,
    max_depth: int = smooth.MAX_DEPTH,
    min_edge_pixels: float = 1.0,
    boundary_rule: smooth.BoundaryRule = "center",
) -> None:
    for radius_fraction, state in layers:
        smooth.apply_variable_capsule_segments(
            node,
            triangle,
            segments,
            radii * radius_fraction,
            state,
            projector=projector,
            max_depth=max_depth,
            min_edge_pixels=min_edge_pixels,
            boundary_rule=boundary_rule,
        )


def assert_same_tree(
    test: unittest.TestCase,
    expected: smooth.PaintNode,
    actual: smooth.PaintNode,
) -> None:
    test.assertEqual(expected, actual)
    test.assertEqual(
        smooth.encode_paint_color(expected),
        smooth.encode_paint_color(actual),
    )


def random_midpoint_tree(
    rng: np.random.Generator,
    depth: int = 0,
) -> smooth.PaintNode:
    state = int(rng.integers(0, smooth.STATE_COUNT))
    if depth >= 3 or rng.random() < 0.57:
        return smooth.PaintNode(state)
    return smooth.PaintNode.branch(
        tuple(random_midpoint_tree(rng, depth + 1) for _ in range(4)),
        split_sides=3,
    ).collapse()


class LayeredAirbrushEquivalenceTests(unittest.TestCase):
    def test_random_midpoint_trees_match_sequential_encoded_output(self) -> None:
        rng = np.random.default_rng(0xA17B5A7E)
        rules: tuple[smooth.BoundaryRule, ...] = (
            "center",
            "inside",
            "intersect",
        )
        for trial in range(180):
            triangle = rng.uniform(-100.0, 100.0, size=(3, 2))
            segment_count = int(rng.integers(0, 9))
            segments = rng.uniform(-130.0, 130.0, size=(segment_count, 2, 2))
            if segment_count and trial % 5 == 0:
                segments[0, 1] = segments[0, 0]
            radii = rng.uniform(0.0, 30.0, size=segment_count)
            if segment_count and trial % 7 == 0:
                radii[0] = 0.0

            count = int(rng.integers(1, 10))
            radius_fractions = np.sort(rng.uniform(0.0, 1.2, size=count))[::-1]
            layers = tuple(
                (float(fraction), int(rng.integers(0, smooth.STATE_COUNT)))
                for fraction in radius_fractions
            )
            initial = random_midpoint_tree(rng)
            expected = initial.clone()
            actual = initial.clone()
            max_depth = int(rng.integers(0, smooth.MAX_DEPTH + 1))
            min_edge = float(rng.choice((0.0, 0.25, 1.0, 3.5, 20.0)))
            rule = rules[trial % len(rules)]
            apply_sequential(
                expected,
                triangle,
                segments,
                radii,
                layers,
                max_depth=max_depth,
                min_edge_pixels=min_edge,
                boundary_rule=rule,
            )
            smooth.apply_layered_variable_capsule_segments(
                actual,
                triangle,
                segments,
                radii,
                layers,
                max_depth=max_depth,
                min_edge_pixels=min_edge,
                boundary_rule=rule,
            )
            with self.subTest(trial=trial, rule=rule, max_depth=max_depth):
                assert_same_tree(self, expected, actual)

    def test_pressure_time_quantized_layers_and_projector_match(self) -> None:
        rng = np.random.default_rng(0xDAB51A7E)
        triangle_3d = np.asarray(
            ((-1.0, -1.0, 3.0), (1.2, -0.8, 4.0), (-0.3, 1.4, 5.0))
        )

        def projector(points: np.ndarray) -> np.ndarray:
            return points[:, :2] * np.asarray((42.0, 35.0)) + np.asarray((7.0, -4.0))

        for trial in range(36):
            palette = rng.uniform(0.0, 1.0, size=(32, 3))
            layers = airbrush_state_layers(
                int(rng.integers(0, 32)),
                int(rng.integers(0, 32)),
                palette,
                np.ones(32, dtype=np.bool_),
                strength=float(rng.uniform(0.05, 1.0)),
                pressure=float(rng.uniform(0.03, 1.0)),
                dab_count=int(rng.integers(1, 45)),
                layer_count=int(rng.integers(2, 18)),
            )
            segments = rng.uniform(-55.0, 55.0, size=(4, 2, 2))
            radii = rng.uniform(1.0, 15.0, size=4)
            initial = random_midpoint_tree(rng)
            expected = initial.clone()
            actual = initial.clone()
            apply_sequential(
                expected,
                triangle_3d,
                segments,
                radii,
                layers,
                projector=projector,
                max_depth=4,
                min_edge_pixels=0.5,
            )
            smooth.apply_layered_variable_capsule_segments(
                actual,
                triangle_3d,
                segments,
                radii,
                layers,
                projector=projector,
                max_depth=4,
                min_edge_pixels=0.5,
            )
            with self.subTest(trial=trial, layers=len(layers)):
                assert_same_tree(self, expected, actual)

    def test_legacy_orca_branches_and_non_nested_order_use_exact_fallback(self) -> None:
        segments = np.asarray(
            (((-30.0, -2.0), (28.0, 11.0)), ((0.0, 30.0), (0.0, 30.0)))
        )
        radii = np.asarray((13.0, 8.0))
        nested = ((0.96, 2), (0.71, 7), (0.43, 11), (0.09, 17))
        non_nested = ((0.25, 5), (0.82, 9), (0.12, 3))
        trees = (
            smooth.PaintNode.branch(
                (smooth.PaintNode(1), smooth.PaintNode(5)),
                split_sides=1,
                special_side=2,
            ),
            smooth.PaintNode.branch(
                (smooth.PaintNode(1), smooth.PaintNode(5), smooth.PaintNode(9)),
                split_sides=2,
                special_side=1,
            ),
            random_midpoint_tree(np.random.default_rng(10)),
        )
        for tree_index, initial in enumerate(trees):
            for layers in (nested, non_nested):
                for rule in ("center", "inside", "intersect"):
                    expected = initial.clone()
                    actual = initial.clone()
                    apply_sequential(
                        expected,
                        TRIANGLE,
                        segments,
                        radii,
                        layers,
                        max_depth=6,
                        min_edge_pixels=0.0,
                        boundary_rule=rule,
                    )
                    smooth.apply_layered_variable_capsule_segments(
                        actual,
                        TRIANGLE,
                        segments,
                        radii,
                        layers,
                        max_depth=6,
                        min_edge_pixels=0.0,
                        boundary_rule=rule,
                    )
                    with self.subTest(
                        tree=tree_index,
                        nested=layers is nested,
                        rule=rule,
                    ):
                        assert_same_tree(self, expected, actual)

    def test_empty_layers_and_segments_are_noops(self) -> None:
        segments = np.asarray((((0.0, 0.0), (5.0, 2.0)),))
        for layers, selected_segments, radii in (
            ((), segments, np.asarray((3.0,))),
            (((0.9, 3),), np.empty((0, 2, 2)), np.empty(0)),
        ):
            node = random_midpoint_tree(np.random.default_rng(42))
            before = node.clone()
            result = smooth.apply_layered_variable_capsule_segments(
                node,
                TRIANGLE,
                selected_segments,
                radii,
                layers,
            )
            self.assertFalse(result.changed)
            self.assertEqual(result.visited_nodes, 0)
            assert_same_tree(self, before, node)


class LayeredAirbrushBenchmarkTests(unittest.TestCase):
    def test_nine_bands_have_a_meaningful_speedup(self) -> None:
        points = np.stack(
            (
                np.linspace(-42.0, 35.0, 8),
                7.0 * np.sin(np.linspace(0.0, 3.0 * np.pi, 8)),
            ),
            axis=1,
        )
        segments = np.stack((points[:-1], points[1:]), axis=1)
        radii = np.linspace(15.0, 8.0, len(segments))
        layers = tuple(
            (float(fraction), state)
            for fraction, state in zip(
                np.linspace(0.96, 0.08, 9),
                range(2, 11),
                strict=True,
            )
        )

        def sequential() -> smooth.PaintNode:
            node = smooth.PaintNode(0)
            apply_sequential(
                node,
                TRIANGLE,
                segments,
                radii,
                layers,
                max_depth=4,
                min_edge_pixels=0.0,
            )
            return node

        def fused() -> smooth.PaintNode:
            node = smooth.PaintNode(0)
            smooth.apply_layered_variable_capsule_segments(
                node,
                TRIANGLE,
                segments,
                radii,
                layers,
                max_depth=4,
                min_edge_pixels=0.0,
            )
            return node

        assert_same_tree(self, sequential(), fused())
        sequential()
        fused()

        measurements: dict[str, list[float]] = {"sequential": [], "fused": []}
        for name, function in (("sequential", sequential), ("fused", fused)):
            for _ in range(3):
                started = time.perf_counter()
                function()
                measurements[name].append(time.perf_counter() - started)
        sequential_elapsed = min(measurements["sequential"])
        fused_elapsed = min(measurements["fused"])
        speedup = sequential_elapsed / fused_elapsed
        print(
            f"layered airbrush 9-band speedup: {speedup:.2f}x "
            f"({sequential_elapsed:.4f}s -> {fused_elapsed:.4f}s)"
        )
        self.assertLess(
            fused_elapsed,
            sequential_elapsed * 0.65,
            "layer fusion did not provide a meaningful speedup",
        )


if __name__ == "__main__":
    unittest.main()
