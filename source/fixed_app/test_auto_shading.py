from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import auto_shading
import smooth_paint


BLACK_WHITE = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))


def one_triangle() -> tuple[np.ndarray, np.ndarray]:
    vertices = np.asarray(((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)))
    faces = np.asarray(((0, 1, 2),), dtype=np.int32)
    return faces, vertices


class AutoShadingTests(unittest.TestCase):
    def test_palette_boundary_crosses_inside_root_triangle(self) -> None:
        faces, vertices = one_triangle()
        tone = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)))
        result = auto_shading.generate_auto_shading(
            faces,
            vertices,
            tone,
            np.asarray((1,), dtype=np.int8),
            BLACK_WHITE,
            options=auto_shading.AutoShadingOptions(
                min_edge_mm=0.25,
                max_depth=2,
                max_adaptive_faces=10,
                max_total_leaves=100,
            ),
        )

        self.assertEqual(result.adaptive_faces, 1)
        tree = result.trees[0]
        self.assertFalse(tree.is_leaf)
        self.assertLessEqual(tree.max_depth(), 2)
        leaves = list(smooth_paint.iter_leaf_triangles(tree, vertices))
        self.assertEqual({leaf.state for leaf in leaves}, {0, 1})
        # The source mesh is untouched: only the Orca annotation is adaptive.
        self.assertEqual(faces.shape, (1, 3))
        self.assertGreater(len(smooth_paint.encode_paint_color(tree)), 1)

    def test_uniform_face_collapses_and_is_not_stored(self) -> None:
        faces, vertices = one_triangle()
        tone = np.full((3, 3), 0.2, dtype=np.float64)
        result = auto_shading.generate_auto_shading(
            faces,
            vertices,
            tone,
            np.asarray((0,), dtype=np.int8),
            BLACK_WHITE,
            options=auto_shading.AutoShadingOptions(min_edge_mm=0.1, max_depth=3),
        )

        self.assertEqual(result.candidate_faces, 0)
        self.assertEqual(result.trees, {})
        self.assertEqual(result.total_leaves, 0)

    def test_flat_face_tone_does_not_restore_vertex_approximation_gradient(self) -> None:
        faces, vertices = one_triangle()
        # Shared-vertex illustration previews can contain a smooth
        # approximation even though the printable triangle is one flat band.
        approximate_vertices = np.asarray(
            ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)),
            dtype=np.float64,
        )
        result = auto_shading.generate_auto_shading(
            faces,
            vertices,
            approximate_vertices,
            np.asarray((0,), dtype=np.int8),
            BLACK_WHITE,
            options=auto_shading.AutoShadingOptions(
                min_edge_mm=0.1,
                max_depth=3,
                dither=True,
                dither_strength=1.0,
                min_variation_delta_e=0.1,
            ),
            tone_face_rgb=np.asarray(((0.2, 0.2, 0.2),)),
        )

        self.assertEqual(result.candidate_faces, 0)
        self.assertEqual(result.trees, {})

    def test_flat_face_tone_count_must_match_faces(self) -> None:
        faces, vertices = one_triangle()
        with self.assertRaisesRegex(
            auto_shading.AutoShadingError, "tone_face_rgb count"
        ):
            auto_shading.generate_auto_shading(
                faces,
                vertices,
                np.zeros((3, 3), dtype=np.float64),
                np.asarray((0,), dtype=np.int8),
                BLACK_WHITE,
                tone_face_rgb=np.zeros((2, 3), dtype=np.float64),
            )

    def test_uniform_subtrees_collapse_bottom_up(self) -> None:
        uniform = auto_shading._tree_from_leaf_states(
            np.zeros(16, dtype=np.int8),
            2,
        )
        self.assertTrue(uniform.is_leaf)
        self.assertEqual(uniform.state, 0)

        grouped = auto_shading._tree_from_leaf_states(
            np.asarray((0, 0, 0, 0) + (1,) * 12, dtype=np.int8),
            2,
        )
        self.assertFalse(grouped.is_leaf)
        self.assertEqual(grouped.max_depth(), 1)
        self.assertEqual(grouped.leaf_count(), 4)

    def test_two_colour_dither_is_deterministic(self) -> None:
        faces, vertices = one_triangle()
        tone = np.asarray(((0.20, 0.20, 0.20), (0.80, 0.80, 0.80), (0.45, 0.45, 0.45)))
        options = auto_shading.AutoShadingOptions(
            min_edge_mm=0.1,
            max_depth=3,
            dither=True,
            dither_seed=314159,
            min_variation_delta_e=0.1,
        )
        first = auto_shading.generate_auto_shading(
            faces, vertices, tone, np.asarray((0,), dtype=np.int8), BLACK_WHITE, options=options
        )
        second = auto_shading.generate_auto_shading(
            faces, vertices, tone, np.asarray((0,), dtype=np.int8), BLACK_WHITE, options=options
        )

        self.assertEqual(first.adaptive_faces, 1)
        self.assertEqual(
            smooth_paint.encode_paint_color(first.trees[0]),
            smooth_paint.encode_paint_color(second.trees[0]),
        )
        self.assertLessEqual(first.trees[0].max_depth(), 3)

    def test_dither_strength_zero_matches_nearest_colour_and_one_is_compatible(self) -> None:
        faces, vertices = one_triangle()
        tone = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.4, 0.4, 0.4)))
        common = dict(
            min_edge_mm=0.1,
            max_depth=3,
            dither_seed=2718,
            min_variation_delta_e=0.1,
        )
        nearest = auto_shading.generate_auto_shading(
            faces,
            vertices,
            tone,
            np.asarray((0,), dtype=np.int8),
            BLACK_WHITE,
            options=auto_shading.AutoShadingOptions(dither=False, **common),
        )
        zero = auto_shading.generate_auto_shading(
            faces,
            vertices,
            tone,
            np.asarray((0,), dtype=np.int8),
            BLACK_WHITE,
            options=auto_shading.AutoShadingOptions(
                dither=True,
                dither_strength=0.0,
                **common,
            ),
        )
        legacy_default = auto_shading.generate_auto_shading(
            faces,
            vertices,
            tone,
            np.asarray((0,), dtype=np.int8),
            BLACK_WHITE,
            options=auto_shading.AutoShadingOptions(dither=True, **common),
        )
        explicit_one = auto_shading.generate_auto_shading(
            faces,
            vertices,
            tone,
            np.asarray((0,), dtype=np.int8),
            BLACK_WHITE,
            options=auto_shading.AutoShadingOptions(
                dither=True,
                dither_strength=1.0,
                **common,
            ),
        )

        nearest_codes = {
            face: smooth_paint.encode_paint_color(node)
            for face, node in nearest.trees.items()
        }
        zero_codes = {
            face: smooth_paint.encode_paint_color(node)
            for face, node in zero.trees.items()
        }
        legacy_codes = {
            face: smooth_paint.encode_paint_color(node)
            for face, node in legacy_default.trees.items()
        }
        one_codes = {
            face: smooth_paint.encode_paint_color(node)
            for face, node in explicit_one.trees.items()
        }
        self.assertEqual(zero_codes, nearest_codes)
        self.assertEqual(one_codes, legacy_codes)

    def test_dither_strength_increases_second_colour_area_monotonically(self) -> None:
        face_count = 16
        faces = np.tile(np.asarray(((0, 1, 2),), dtype=np.int32), (face_count, 1))
        vertices = np.asarray(((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)))
        # Every point remains nearer black, but the continuous variation gives
        # full dither a reproducible opportunity to use white spatially.
        tone = np.asarray(((0.12, 0.12, 0.12), (0.45, 0.45, 0.45), (0.28, 0.28, 0.28)))

        def white_area(strength: float) -> tuple[float, dict[int, str]]:
            result = auto_shading.generate_auto_shading(
                faces,
                vertices,
                tone,
                np.zeros(face_count, dtype=np.int8),
                BLACK_WHITE,
                options=auto_shading.AutoShadingOptions(
                    min_edge_mm=0.1,
                    max_depth=3,
                    dither=True,
                    dither_strength=strength,
                    dither_seed=99,
                    min_variation_delta_e=0.1,
                ),
            )
            codes = {
                face: smooth_paint.encode_paint_color(node)
                for face, node in result.trees.items()
            }
            area = sum(node.state_areas()[1] for node in result.trees.values())
            return area, codes

        zero_area, _zero_codes = white_area(0.0)
        half_area, half_codes = white_area(0.5)
        full_area, full_codes = white_area(1.0)
        repeated_half_area, repeated_half_codes = white_area(0.5)

        self.assertEqual(zero_area, 0.0)
        self.assertGreater(half_area, zero_area)
        self.assertGreater(full_area, half_area)
        self.assertEqual(repeated_half_area, half_area)
        self.assertEqual(repeated_half_codes, half_codes)
        self.assertNotEqual(full_codes, half_codes)

    def test_dither_strength_is_validated(self) -> None:
        faces, vertices = one_triangle()
        tone = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.5, 0.5)))
        for invalid in (-0.01, 1.01, np.nan, np.inf):
            with self.subTest(strength=invalid):
                with self.assertRaises(auto_shading.AutoShadingError):
                    auto_shading.generate_auto_shading(
                        faces,
                        vertices,
                        tone,
                        np.asarray((0,), dtype=np.int8),
                        BLACK_WHITE,
                        options=auto_shading.AutoShadingOptions(
                            dither=True,
                            dither_strength=invalid,
                        ),
                    )

    def test_physical_minimum_edge_skips_tiny_face(self) -> None:
        faces, vertices = one_triangle()
        vertices *= 0.01
        tone = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)))
        result = auto_shading.generate_auto_shading(
            faces,
            vertices,
            tone,
            np.asarray((0,), dtype=np.int8),
            BLACK_WHITE,
            options=auto_shading.AutoShadingOptions(min_edge_mm=0.1),
        )
        self.assertEqual(result.adaptive_faces, 0)
        self.assertEqual(result.skipped_small_faces, 1)

    def test_face_and_leaf_budgets_are_hard_limits(self) -> None:
        face_count = 20
        base_vertices = np.asarray(((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0)))
        vertices = np.concatenate(
            [base_vertices + np.asarray((index * 5.0, 0.0, 0.0)) for index in range(face_count)]
        )
        faces = np.arange(face_count * 3, dtype=np.int32).reshape(face_count, 3)
        tone = np.tile(
            np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0))),
            (face_count, 1),
        )
        result = auto_shading.generate_auto_shading(
            faces,
            vertices,
            tone,
            np.zeros(face_count, dtype=np.int8),
            BLACK_WHITE,
            options=auto_shading.AutoShadingOptions(
                min_edge_mm=0.1,
                max_depth=3,
                max_adaptive_faces=3,
                max_total_leaves=8,
            ),
        )

        self.assertTrue(result.budget_limited)
        self.assertLessEqual(result.selected_faces, 3)
        self.assertLessEqual(result.reserved_leaves, 8)
        self.assertLessEqual(result.total_leaves, 8)
        self.assertLessEqual(result.adaptive_faces, 2)

    def test_scope_mask_and_enabled_palette_states_are_respected(self) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (2.0, 0.0, 0.0),
                (0.0, 2.0, 0.0),
                (3.0, 0.0, 0.0),
                (5.0, 0.0, 0.0),
                (3.0, 2.0, 0.0),
            )
        )
        faces = np.asarray(((0, 1, 2), (3, 4, 5)), dtype=np.int32)
        tone = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 1.0, 1.0),
                (0.6, 0.6, 0.6),
                (0.0, 0.0, 0.0),
                (1.0, 1.0, 1.0),
                (0.6, 0.6, 0.6),
            )
        )
        palette = np.asarray(((0.0, 0.0, 0.0), (0.5, 0.5, 0.5), (1.0, 1.0, 1.0)))
        result = auto_shading.generate_auto_shading(
            faces,
            vertices,
            tone,
            np.asarray((0, 0), dtype=np.int8),
            palette,
            face_mask=np.asarray((False, True)),
            options=auto_shading.AutoShadingOptions(
                min_edge_mm=0.2,
                max_depth=2,
                enabled_states=(True, False, True),
            ),
        )

        self.assertNotIn(0, result.trees)
        self.assertIn(1, result.trees)
        states = {leaf.state for leaf in smooth_paint.iter_leaf_triangles(result.trees[1], vertices[faces[1]])}
        self.assertEqual(states, {0, 2})

    def test_input_arrays_are_not_mutated(self) -> None:
        faces, vertices = one_triangle()
        tone = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.5, 0.5)))
        states = np.asarray((0,), dtype=np.int8)
        snapshots = (faces.copy(), vertices.copy(), tone.copy(), states.copy(), BLACK_WHITE.copy())
        auto_shading.generate_auto_shading(
            faces, vertices, tone, states, BLACK_WHITE, options=auto_shading.AutoShadingOptions()
        )
        for actual, expected in zip((faces, vertices, tone, states, BLACK_WHITE), snapshots):
            np.testing.assert_array_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
