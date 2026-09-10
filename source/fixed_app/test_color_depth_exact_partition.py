from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import time
from typing import Mapping
import unittest
from unittest.mock import patch

import numpy as np
import trimesh


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.color_depth import ColorDepthRecipe
from spectrum_mapper.color_depth_exact_partition import (
    COLOR_DEPTH_EXACT_PARTITION_SCHEMA,
    ColorDepthExactPartitionError,
    build_conforming_color_depth_partition,
)
import spectrum_mapper.color_depth_exact_partition as exact_partition_module
from spectrum_mapper.color_depth_head_geometry import (
    ColorDepthSourceSurface,
    build_color_depth_result_from_partition,
    prepare_color_depth_source,
)
from test_color_depth_head_geometry import _request


def _volume(nodes: np.ndarray, tets: np.ndarray) -> float:
    points = np.asarray(nodes, dtype=np.float64)[np.asarray(tets, dtype=np.int32)]
    six = np.einsum(
        "ij,ij->i",
        points[:, 1] - points[:, 0],
        np.cross(points[:, 2] - points[:, 0], points[:, 3] - points[:, 0]),
    )
    return float(np.abs(six).sum() / 6.0)


class ColorDepthExactPartitionTests(unittest.TestCase):
    def test_small_cube_exact_provider_e2e_and_outer_only_fallback(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        partition = build_conforming_color_depth_partition(
            source, request.recipes
        )

        self.assertEqual(
            partition.metadata["schema"], COLOR_DEPTH_EXACT_PARTITION_SCHEMA
        )
        self.assertTrue(partition.threshold_interface_conforming)
        self.assertTrue(partition.shared_interface_partition_exact)
        self.assertTrue(partition.metadata["direct_threshold_child_join_verified"])
        self.assertTrue(partition.metadata["visible_exterior_triangle_sets_exact"])
        self.assertTrue(partition.metadata["visible_owner_labels_exact"])
        self.assertTrue(partition.metadata["visible_outer_physical_exact"])
        self.assertNotIn("variable_outer_thickness", partition.metadata)
        self.assertEqual(partition.metadata["cell_complex_faces_incidence_gt2"], 0)
        self.assertGreater(
            partition.metadata["hidden_threshold_visibility"][
                "hidden_threshold_cells"
            ],
            0,
        )
        self.assertGreater(partition.metadata["interface_triangles"], 0)
        self.assertLessEqual(
            partition.max_safe_threshold_error_mm,
            partition.max_safe_threshold_error_limit_mm + 1e-12,
        )
        self.assertAlmostEqual(
            _volume(partition.nodes_mm, partition.tetrahedra), 480.0, places=8
        )
        exterior_labels = partition.cell_owner_labels[
            partition.exterior_owner_cells
        ]
        self.assertTrue(
            np.array_equal(
                exterior_labels,
                source.face_target_labels[partition.exterior_source_face_ids],
            )
        )
        self.assertTrue(
            np.all(partition.cell_materials[partition.exterior_owner_cells] == 3)
        )
        unsafe = partition.unsafe_outer_only_cells
        self.assertTrue(np.all(partition.cell_materials[unsafe] == 3))
        self.assertEqual(
            set(map(int, np.unique(partition.cell_materials))) - {1, 2, 3, 4},
            set(),
        )

    def test_conflicting_visible_labels_are_face_coned_and_preserved(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        labels = source.face_target_labels.copy()
        labels[::7] = 5
        source = replace(source, face_target_labels=labels)
        recipes = dict(request.recipes)
        recipes[5] = ColorDepthRecipe(
            target_label=5,
            outer_physical=2,
            outer_thickness_mm=0.15,
            backing_physical=4,
        )

        partition = build_conforming_color_depth_partition(source, recipes)

        self.assertGreater(
            partition.metadata["conflicting_boundary_face_cones"][
                "conflicting_boundary_tetrahedra"
            ],
            0,
        )
        self.assertTrue(
            np.array_equal(
                partition.cell_owner_labels[partition.exterior_owner_cells],
                labels[partition.exterior_source_face_ids],
            )
        )
        expected_outer = np.where(
            labels[partition.exterior_source_face_ids] == 5, 2, 3
        )
        self.assertTrue(
            np.array_equal(
                partition.cell_materials[partition.exterior_owner_cells],
                expected_outer,
            )
        )
        self.assertAlmostEqual(
            _volume(partition.nodes_mm, partition.tetrahedra), 480.0, places=8
        )

    def test_distinct_owner_thicknesses_use_global_conforming_bands(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        centers = source.vertices_mm[source.faces].mean(axis=1)
        labels = np.full(len(source.faces), 4, dtype=np.int16)
        labels[centers[:, 0] > 4.99] = 5
        source = replace(source, face_target_labels=labels)
        recipes = {
            4: ColorDepthRecipe(
                target_label=4,
                outer_physical=3,
                outer_thickness_mm=1.0,
                backing_physical=1,
            ),
            5: ColorDepthRecipe(
                target_label=5,
                outer_physical=2,
                outer_thickness_mm=1.5,
                backing_physical=1,
            ),
        }

        partition = build_conforming_color_depth_partition(source, recipes)
        result = build_color_depth_result_from_partition(
            source,
            recipes,
            partition,
        )

        self.assertTrue(partition.metadata["variable_outer_thickness"])
        self.assertEqual(partition.metadata["threshold_pass_count"], 2)
        self.assertEqual(
            partition.metadata["unique_thresholds_mm"],
            [1.0, 1.5],
        )
        self.assertEqual(
            partition.metadata["thresholds_mm_by_label"],
            {"4": 1.0, "5": 1.5},
        )
        self.assertTrue(partition.threshold_interface_conforming)
        self.assertTrue(partition.shared_interface_partition_exact)
        self.assertAlmostEqual(
            _volume(partition.nodes_mm, partition.tetrahedra),
            480.0,
            places=8,
        )
        exterior_labels = partition.cell_owner_labels[
            partition.exterior_owner_cells
        ]
        expected_outer = np.where(exterior_labels == 5, 2, 3)
        self.assertTrue(
            np.array_equal(
                partition.cell_materials[partition.exterior_owner_cells],
                expected_outer,
            )
        )
        for label in (4, 5):
            safe_label = (
                (partition.cell_owner_labels == label)
                & ~partition.unsafe_outer_only_cells
            )
            self.assertIn(
                1,
                set(map(int, np.unique(partition.cell_materials[safe_label]))),
                msg=f"label {label} has no safe backing material",
            )
        for record in partition.metadata["threshold_passes"]:
            self.assertFalse(record["added_node_depths_exact_affine"])
            self.assertTrue(
                record["added_node_depths_recomputed_from_source_surface"]
            )
            self.assertEqual(
                record["threshold_tetrahedralization"],
                "boundary_vertex_fan",
            )
            self.assertEqual(
                record[
                    "maximum_side_fan_centroid_depth_interpolation_error_mm"
                ],
                0.0,
            )
            self.assertGreater(
                record["material_changing_threshold_triangles"],
                0,
            )
        self.assertEqual(result.metadata["gap_mm"], 0.0)
        self.assertEqual(result.metadata["positive_overlap_mm3"], 0.0)
        self.assertEqual(
            result.metadata["coordinate_triangle_accounting"][
                "internal_opposite_winding_failures"
            ],
            0,
        )
        self.assertTrue(result.metadata["external_surface_coverage_exact"])
        self.assertTrue(result.metadata["shared_interface_partition_exact"])

    def test_variable_band_order_is_deterministic_and_near_duplicates_fail(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        centers = source.vertices_mm[source.faces].mean(axis=1)
        labels = np.full(len(source.faces), 4, dtype=np.int16)
        labels[centers[:, 0] > 4.99] = 5
        source = replace(source, face_target_labels=labels)
        first = ColorDepthRecipe(4, 3, 1.0, 1)
        second = ColorDepthRecipe(5, 2, 1.5, 1)

        forward = build_conforming_color_depth_partition(
            source,
            {4: first, 5: second},
        )
        reverse = build_conforming_color_depth_partition(
            source,
            {5: second, 4: first},
        )

        self.assertTrue(np.array_equal(forward.nodes_mm, reverse.nodes_mm))
        self.assertTrue(np.array_equal(forward.tetrahedra, reverse.tetrahedra))
        self.assertTrue(
            np.array_equal(forward.cell_materials, reverse.cell_materials)
        )
        self.assertTrue(
            np.array_equal(
                forward.unsafe_outer_only_cells,
                reverse.unsafe_outer_only_cells,
            )
        )

        too_close = ColorDepthRecipe(5, 2, 1.0 + 5e-8, 1)
        with self.assertRaises(ColorDepthExactPartitionError) as caught:
            build_conforming_color_depth_partition(
                source,
                {4: first, 5: too_close},
            )
        self.assertEqual(
            caught.exception.code,
            "outer_thickness_bands_too_close",
        )

    def test_variable_output_node_depth_is_recomputed_from_source_surface(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        centers = source.vertices_mm[source.faces].mean(axis=1)
        labels = np.full(len(source.faces), 4, dtype=np.int16)
        labels[centers[:, 0] > 4.99] = 5
        source = replace(source, face_target_labels=labels)
        recipes = {
            4: ColorDepthRecipe(4, 3, 1.0, 1),
            5: ColorDepthRecipe(5, 2, 1.5, 1),
        }
        maximum_errors: list[float] = []
        original = exact_partition_module._build_threshold_partition

        def capture(**kwargs):
            partition, node_depth = original(**kwargs)
            true_depth, _closest = exact_partition_module._closest_source(
                kwargs["source_mesh"],
                partition.nodes_mm,
                chunk_size=kwargs["chunk_size"],
            )
            maximum_errors.append(
                float(np.max(np.abs(true_depth - node_depth), initial=0.0))
            )
            return partition, node_depth

        with patch.object(
            exact_partition_module,
            "_build_threshold_partition",
            side_effect=capture,
        ):
            build_conforming_color_depth_partition(source, recipes)
        self.assertEqual(len(maximum_errors), 2)
        self.assertLessEqual(max(maximum_errors), 1e-12)

    def test_boundary_vertex_fan_capacity_matches_all_sign_topologies(self) -> None:
        tet = np.arange(4, dtype=np.int32)
        for positive_mask in range(1, 15):
            scalar = np.asarray(
                [
                    1.0 if positive_mask & (1 << index) else -1.0
                    for index in range(4)
                ],
                dtype=np.float64,
            )
            crossing_registry: dict[int, int] = {}
            interface_ids: list[int] = []
            for edge in tet[exact_partition_module._TET_EDGES]:
                first, second = map(int, edge)
                if scalar[first] * scalar[second] >= 0.0:
                    continue
                low, high = sorted((first, second))
                node_id = 4 + len(crossing_registry)
                crossing_registry[(low << 32) | high] = node_id
                interface_ids.append(node_id)
            crossing_edge_count = len(interface_ids)
            emitted = 0
            for side in (-1, 1):
                polygons = []
                for local_face in exact_partition_module._TET_FACES:
                    polygon = exact_partition_module._clip_face(
                        tet[local_face],
                        scalar,
                        crossing_registry,
                        negative=side < 0,
                    )
                    if len(polygon) >= 3:
                        polygons.append(polygon)
                polygons.append(interface_ids)
                used = np.unique(
                    np.asarray(
                        [value for polygon in polygons for value in polygon],
                        dtype=np.int32,
                    )
                )
                anchor = int(np.min(used))
                emitted += sum(
                    len(exact_partition_module._fan(polygon))
                    for polygon in polygons
                    if anchor not in polygon
                )
            expected = 2 * crossing_edge_count - 2
            with self.subTest(positive_mask=positive_mask):
                self.assertIn(crossing_edge_count, (3, 4))
                self.assertEqual(emitted, expected)
                self.assertEqual(
                    exact_partition_module._boundary_vertex_fan_capacity(
                        0,
                        np.asarray([crossing_edge_count], dtype=np.int32),
                    ),
                    expected,
                )

    def test_exact_fan_capacity_succeeds_below_legacy_worst_case(self) -> None:
        counts = np.asarray([3, 4], dtype=np.int32)
        exact = 1 + 4 + 6
        legacy = 1 + 16 * len(counts)
        limit = (exact + legacy) // 2

        self.assertLess(exact, limit)
        self.assertLess(limit, legacy)
        with patch.object(
            exact_partition_module,
            "_MAX_VARIABLE_PARTITION_CELLS",
            limit,
        ):
            self.assertEqual(
                exact_partition_module._boundary_vertex_fan_capacity(1, counts),
                exact,
            )

    def test_exact_fan_capacity_minus_one_fails_with_precise_details(self) -> None:
        counts = np.asarray([3, 4], dtype=np.int32)
        exact = 1 + 4 + 6
        legacy = 1 + 16 * len(counts)
        with patch.object(
            exact_partition_module,
            "_MAX_VARIABLE_PARTITION_CELLS",
            exact - 1,
        ):
            with self.assertRaises(ColorDepthExactPartitionError) as caught:
                exact_partition_module._boundary_vertex_fan_capacity(1, counts)
        self.assertEqual(
            caught.exception.code,
            "variable_partition_cell_limit_exceeded",
        )
        self.assertEqual(
            caught.exception.details,
            {
                "phase": "preallocation",
                "predicted_capacity": exact,
                "exact_capacity": exact,
                "legacy_worst_case_capacity": legacy,
                "input_cells": 3,
                "noncrossing_cells": 1,
                "crossing_cells": 2,
                "three_edge_crossing_cells": 1,
                "four_edge_crossing_cells": 1,
                "maximum": exact - 1,
            },
        )

    def test_adaptive_refinement_budget_allows_seventh_interface_then_partner(
        self,
    ) -> None:
        self.assertEqual(
            exact_partition_module._ADAPTIVE_INTERFACE_REFINEMENT_PASSES,
            7,
        )
        self.assertEqual(
            exact_partition_module._ADAPTIVE_PARTNER_REFINEMENT_PASSES,
            2,
        )
        self.assertEqual(
            exact_partition_module._ADAPTIVE_TOTAL_REFINEMENT_PASSES,
            8,
        )
        self.assertGreaterEqual(
            exact_partition_module._ADAPTIVE_TOTAL_REFINEMENT_PASSES,
            exact_partition_module._ADAPTIVE_INTERFACE_REFINEMENT_PASSES + 1,
        )
        self.assertEqual(
            exact_partition_module._DEFAULT_INTERFACE_ERROR_LIMIT_MM,
            0.05,
        )
        self.assertEqual(
            exact_partition_module._MAX_VARIABLE_PARTITION_CELLS,
            2_000_000,
        )

    def test_adaptive_edge_root_uses_true_distance_not_affine_depth(self) -> None:
        # A chord through a unit sphere has a concave true distance profile.
        # Linear interpolation of the exact endpoint distances puts the
        # nominal 0.25 mm interface at a point whose true depth is about
        # 0.441 mm.  The adaptive root must instead return the shallow side of
        # the first authoritative crossing.
        nodes = np.asarray(((1.0, 0.0, 0.0), (0.0, 0.5, 0.0)))

        def sphere_depth(_mesh, points, *, chunk_size):
            del _mesh, chunk_size
            values = 1.0 - np.linalg.norm(points, axis=1)
            return values, np.zeros(len(points), dtype=np.int32)

        node_depth, _faces = sphere_depth(None, nodes, chunk_size=10)
        affine = nodes[0] + 0.5 * (nodes[1] - nodes[0])
        self.assertGreater(
            float(sphere_depth(None, affine[None, :], chunk_size=10)[0][0]),
            0.40,
        )
        with patch.object(
            exact_partition_module,
            "_closest_source",
            side_effect=sphere_depth,
        ):
            roots, root_depth, record = (
                exact_partition_module._adaptive_true_distance_edge_roots(
                    source_mesh=None,
                    nodes=nodes,
                    node_depth=node_depth,
                    node_scalar=node_depth - 0.25,
                    unique_edges=np.asarray(((0, 1),), dtype=np.int32),
                    threshold_mm=0.25,
                    error_limit_mm=0.05,
                    chunk_size=10,
                )
            )

        self.assertEqual(
            record["method"],
            "outer_first_true_distance_lipschitz_bracket",
        )
        self.assertLessEqual(float(root_depth[0]), 0.25)
        self.assertGreater(float(root_depth[0]), 0.249)
        self.assertLessEqual(float(record["maximum_march_step_mm"]), 0.10)
        self.assertLessEqual(
            float(record["maximum_root_underdepth_mm"]),
            float(record["maximum_final_bracket_length_mm"]) + 1e-12,
        )
        self.assertTrue(np.isfinite(roots).all())

    def test_adaptive_edge_root_selects_outer_first_nonmonotone_crossing(self) -> None:
        # Distance to two point features is non-monotone along this edge.  A
        # conventional endpoint bisection starts at x=0.5 (another zero) and
        # converges to the later x=0.6 crossing.  The Lipschitz march must find
        # the outer-first x=0.1 crossing instead.
        nodes = np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))

        def two_feature_depth(_mesh, points, *, chunk_size):
            del _mesh, chunk_size
            x = np.asarray(points, dtype=np.float64)[:, 0]
            values = np.minimum(np.abs(x), np.abs(x - 0.5))
            return values, np.zeros(len(points), dtype=np.int32)

        node_depth, _faces = two_feature_depth(None, nodes, chunk_size=10)
        with patch.object(
            exact_partition_module,
            "_closest_source",
            side_effect=two_feature_depth,
        ):
            roots, root_depth, record = (
                exact_partition_module._adaptive_true_distance_edge_roots(
                    source_mesh=None,
                    nodes=nodes,
                    node_depth=node_depth,
                    node_scalar=node_depth - 0.10,
                    unique_edges=np.asarray(((0, 1),), dtype=np.int32),
                    threshold_mm=0.10,
                    error_limit_mm=0.05,
                    chunk_size=10,
                )
            )

        self.assertLess(float(roots[0, 0]), 0.11)
        self.assertGreater(float(roots[0, 0]), 0.099)
        self.assertLessEqual(float(root_depth[0]), 0.10)
        self.assertGreaterEqual(int(record["march_samples"]), 1)

    def test_adaptive_edge_root_uses_certified_deep_bound_near_endpoint(
        self,
    ) -> None:
        # With a root much closer to the shallow endpoint than eight
        # bisection intervals, the shallow bracket point never moves and would
        # produce a zero edge fraction/sliver child.  The returned deep bound
        # is nonzero and its overdepth is no larger than the final bracket.
        nodes = np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
        threshold = 1e-6

        def linear_depth(_mesh, points, *, chunk_size):
            del _mesh, chunk_size
            values = np.asarray(points, dtype=np.float64)[:, 0]
            return values, np.zeros(len(points), dtype=np.int32)

        node_depth, _faces = linear_depth(None, nodes, chunk_size=10)
        with patch.object(
            exact_partition_module,
            "_closest_source",
            side_effect=linear_depth,
        ):
            roots, root_depth, record = (
                exact_partition_module._adaptive_true_distance_edge_roots(
                    source_mesh=None,
                    nodes=nodes,
                    node_depth=node_depth,
                    node_scalar=node_depth - threshold,
                    unique_edges=np.asarray(((0, 1),), dtype=np.int32),
                    threshold_mm=threshold,
                    error_limit_mm=0.05,
                    chunk_size=10,
                )
            )

        self.assertEqual(record["deep_bound_substituted_edges"], 1)
        self.assertEqual(
            record["zero_fraction_policy"],
            "certified_shallow_lipschitz_nudge",
        )
        self.assertLessEqual(
            float(record["maximum_deep_bound_nudge_mm"]),
            float(record["maximum_deep_bound_nudge_limit_mm"]) + 1e-12,
        )
        self.assertGreater(float(roots[0, 0]), 0.0)
        self.assertGreaterEqual(float(root_depth[0]), threshold)
        self.assertLessEqual(
            float(root_depth[0]) - threshold,
            float(record["maximum_final_bracket_length_mm"]) + 1e-12,
        )

    def test_forced_local_interface_refinement_preserves_faces_and_volume(
        self,
    ) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(((0, 1, 2, 3),), dtype=np.int32)
        boundary_faces, boundary_cells = (
            exact_partition_module._oriented_boundary_faces(nodes, tets)
        )
        source_mesh = trimesh.Trimesh(
            vertices=nodes,
            faces=boundary_faces,
            process=False,
        )
        labels = np.full(len(boundary_faces), 4, dtype=np.int32)
        parents = np.arange(len(boundary_faces), dtype=np.int32)

        (
            refined_nodes,
            refined_tets,
            refined_faces,
            _refined_cells,
            refined_labels,
            refined_parents,
            refined_depth,
            record,
            output_parents,
        ) = exact_partition_module._insert_hidden_threshold_centroids(
            source_mesh=source_mesh,
            nodes=nodes,
            tets=tets,
            boundary_faces=boundary_faces,
            boundary_cells=boundary_cells,
            boundary_labels=labels,
            boundary_parent_faces=parents,
            threshold_mm=0.05,
            chunk_size=100,
            scan_local_hidden=True,
            return_parent_cells=True,
            candidate_cell_mask=np.asarray((True,), dtype=bool),
            node_depth_mm=np.zeros(len(nodes), dtype=np.float64),
            force_candidate_refinement=True,
        )

        self.assertEqual(record["mode"], "forced_local_interface_refinement")
        self.assertEqual(record["forced_candidate_refinement_cells"], 1)
        self.assertEqual(record["added_centroid_nodes"], 1)
        self.assertEqual(refined_nodes.shape, (5, 3))
        self.assertEqual(refined_tets.shape, (4, 4))
        self.assertTrue(np.array_equal(output_parents, np.zeros(4, dtype=np.int32)))
        self.assertAlmostEqual(_volume(refined_nodes, refined_tets), 1.0 / 6.0)
        self.assertGreater(float(refined_depth[-1]), 0.0)
        self.assertTrue(np.array_equal(np.sort(refined_labels), np.sort(labels)))
        self.assertTrue(np.array_equal(np.sort(refined_parents), np.sort(parents)))
        self.assertTrue(
            np.array_equal(
                np.sort(refined_faces, axis=1)[
                    np.lexsort(tuple(np.sort(refined_faces, axis=1).T[::-1]))
                ],
                np.sort(boundary_faces, axis=1)[
                    np.lexsort(tuple(np.sort(boundary_faces, axis=1).T[::-1]))
                ],
            )
        )

        with patch.object(
            exact_partition_module,
            "_MAX_VARIABLE_PARTITION_CELLS",
            3,
        ):
            with self.assertRaises(ColorDepthExactPartitionError) as caught:
                exact_partition_module._insert_hidden_threshold_centroids(
                    source_mesh=source_mesh,
                    nodes=nodes,
                    tets=tets,
                    boundary_faces=boundary_faces,
                    boundary_cells=boundary_cells,
                    boundary_labels=labels,
                    boundary_parent_faces=parents,
                    threshold_mm=0.05,
                    chunk_size=100,
                    scan_local_hidden=True,
                    return_parent_cells=True,
                    candidate_cell_mask=np.asarray((True,), dtype=bool),
                    node_depth_mm=np.zeros(len(nodes), dtype=np.float64),
                    force_candidate_refinement=True,
                )
        self.assertEqual(
            caught.exception.code,
            "variable_partition_cell_limit_exceeded",
        )
        self.assertEqual(
            caught.exception.details["phase"],
            "adaptive_interface_local_refinement_preallocation",
        )

    def test_adaptive_interface_edge_star_bisection_is_conforming(self) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, -1.0),
                (0.0, 0.0, 1.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (-1.0, 0.0, 0.0),
                (0.0, -1.0, 0.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(
            (
                (0, 1, 2, 3),
                (0, 1, 3, 4),
                (0, 1, 4, 5),
                (0, 1, 5, 2),
            ),
            dtype=np.int32,
        )
        signed = exact_partition_module._signed_six(nodes, tets)
        reverse = signed < 0.0
        tets[reverse, 1:3] = tets[reverse, 2:0:-1]
        boundary_faces, boundary_cells = (
            exact_partition_module._oriented_boundary_faces(nodes, tets)
        )
        source_mesh = trimesh.Trimesh(
            vertices=nodes,
            faces=boundary_faces,
            process=False,
        )
        labels = np.full(len(boundary_faces), 4, dtype=np.int32)
        parents = np.arange(len(boundary_faces), dtype=np.int32)
        source_volume = _volume(nodes, tets)

        (
            refined_nodes,
            refined_tets,
            refined_faces,
            _refined_cells,
            refined_labels,
            refined_parents,
            refined_depth,
            record,
            output_parents,
        ) = exact_partition_module._bisect_internal_edge_stars(
            source_mesh=source_mesh,
            nodes=nodes,
            tets=tets,
            boundary_faces=boundary_faces,
            boundary_cells=boundary_cells,
            boundary_labels=labels,
            boundary_parent_faces=parents,
            node_depth_mm=np.zeros(len(nodes), dtype=np.float64),
            seed_edges=np.asarray(((0, 1),), dtype=np.int32),
            threshold_mm=0.14,
            chunk_size=100,
        )

        self.assertEqual(
            record["mode"],
            "adaptive_interface_internal_edge_star_bisection",
        )
        self.assertEqual(record["seed_edges"], 1)
        self.assertEqual(record["incident_tetrahedron_splits"], 4)
        self.assertEqual(refined_nodes.shape, (7, 3))
        self.assertEqual(refined_tets.shape, (8, 4))
        self.assertTrue(np.all(exact_partition_module._signed_six(
            refined_nodes, refined_tets
        ) > 0.0))
        self.assertAlmostEqual(_volume(refined_nodes, refined_tets), source_volume)
        self.assertGreater(float(refined_depth[-1]), 0.0)
        self.assertTrue(
            np.array_equal(
                np.sort(np.bincount(output_parents, minlength=4)),
                np.full(4, 2, dtype=np.int64),
            )
        )
        self.assertTrue(np.array_equal(np.sort(refined_labels), np.sort(labels)))
        self.assertTrue(np.array_equal(np.sort(refined_parents), np.sort(parents)))
        old_keys = np.sort(boundary_faces, axis=1)
        new_keys = np.sort(refined_faces, axis=1)
        self.assertEqual(
            {tuple(map(int, row)) for row in old_keys},
            {tuple(map(int, row)) for row in new_keys},
        )

    def test_adaptive_interface_stagnation_policy_fallback_and_hard_stop(
        self,
    ) -> None:
        common = {
            "cause": "interface",
            "violating_triangles": 8,
            "violating_parent_cells": 4,
            "three_edge_parent_cells": 0,
            "four_edge_parent_cells": 4,
            "violating_sample_roles": {
                "edge_midpoint_01": 4,
                "edge_midpoint_02": 8,
                "edge_midpoint_12": 4,
                "face_centroid": 8,
            },
            "unique_seed_edges": 2,
            "violating_origin_cells": np.asarray(
                (101, 102, 103, 104), dtype=np.int32
            ),
        }
        initial = exact_partition_module._adaptive_interface_stagnation_policy(
            maximum_overdepth_mm=0.20,
            completed_records=[],
            **common,
        )
        previous = {
            "cause": "interface",
            "trigger_maximum_overdepth_mm": 0.20,
            "trigger_signature": initial["signature"],
            "stagnation_full_diameter_fallback": False,
        }
        fallback = exact_partition_module._adaptive_interface_stagnation_policy(
            maximum_overdepth_mm=0.19,
            completed_records=[previous],
            **common,
        )

        self.assertTrue(fallback["use_full_diameter_fallback"])
        self.assertFalse(fallback["hard_stop"])
        self.assertTrue(fallback["repeated_signature"])
        self.assertTrue(fallback["poor_contraction"])
        self.assertAlmostEqual(fallback["overdepth_contraction_ratio"], 0.95)

        descendant_locality = (
            exact_partition_module._adaptive_interface_stagnation_policy(
                maximum_overdepth_mm=0.19,
                completed_records=[previous],
                **{
                    **common,
                    "violating_origin_cells": np.asarray(
                        (101, 102), dtype=np.int32
                    ),
                },
            )
        )
        self.assertTrue(descendant_locality["repeated_signature"])
        self.assertTrue(descendant_locality["same_spatial_lineage"])
        self.assertEqual(
            descendant_locality["spatial_lineage_overlap_fraction"], 1.0
        )

        count_oscillation = (
            exact_partition_module._adaptive_interface_stagnation_policy(
                maximum_overdepth_mm=0.19,
                completed_records=[previous],
                **{
                    **common,
                    "violating_triangles": 56,
                    "violating_parent_cells": 4,
                    "four_edge_parent_cells": 4,
                    "violating_sample_roles": {
                        "edge_midpoint_01": 2,
                        "edge_midpoint_02": 4,
                        "edge_midpoint_12": 2,
                        "face_centroid": 3,
                    },
                    "unique_seed_edges": 3,
                    "violating_origin_cells": np.asarray(
                        (101, 102), dtype=np.int32
                    ),
                },
            )
        )
        self.assertTrue(count_oscillation["same_spatial_lineage"])
        self.assertFalse(
            count_oscillation["structural_diagnostics_match"]
        )
        self.assertTrue(count_oscillation["use_full_diameter_fallback"])
        self.assertEqual(
            count_oscillation["reason"],
            "same_lineage_four_edge_family_poor_contraction",
        )

        previous["stagnation_full_diameter_fallback"] = True
        hard_stop = exact_partition_module._adaptive_interface_stagnation_policy(
            maximum_overdepth_mm=0.19,
            completed_records=[previous],
            **common,
        )
        self.assertFalse(hard_stop["use_full_diameter_fallback"])
        self.assertTrue(hard_stop["hard_stop"])
        self.assertEqual(
            hard_stop["reason"], "post_fallback_overdepth_stagnation"
        )

        different_location = (
            exact_partition_module._adaptive_interface_stagnation_policy(
                maximum_overdepth_mm=0.19,
                completed_records=[previous],
                **{
                    **common,
                    "violating_origin_cells": np.asarray(
                        (201, 202, 203, 204), dtype=np.int32
                    ),
                },
            )
        )
        self.assertFalse(different_location["repeated_signature"])
        self.assertFalse(different_location["use_full_diameter_fallback"])
        self.assertFalse(different_location["hard_stop"])
        self.assertEqual(
            different_location["reason"], "spatial_lineage_not_repeated"
        )

        for three_edge, four_edge in ((1, 3), (4, 0)):
            not_four_edge_family = (
                exact_partition_module._adaptive_interface_stagnation_policy(
                    maximum_overdepth_mm=0.19,
                    completed_records=[previous],
                    **{
                        **common,
                        "three_edge_parent_cells": three_edge,
                        "four_edge_parent_cells": four_edge,
                    },
                )
            )
            self.assertFalse(
                not_four_edge_family["use_full_diameter_fallback"]
            )
            self.assertFalse(not_four_edge_family["hard_stop"])
            self.assertEqual(
                not_four_edge_family["reason"], "not_four_edge_only"
            )

        contracted = exact_partition_module._adaptive_interface_stagnation_policy(
            maximum_overdepth_mm=0.17,
            completed_records=[previous],
            **common,
        )
        self.assertFalse(contracted["use_full_diameter_fallback"])
        self.assertFalse(contracted["hard_stop"])
        self.assertEqual(contracted["reason"], "overdepth_contracted")

    def test_main_loop_stagnation_routing_uses_lineage_and_history(
        self,
    ) -> None:
        request = _request()
        base_source = prepare_color_depth_source(request)
        face_centers = base_source.vertices_mm[base_source.faces].mean(axis=1)
        labels = np.full(len(base_source.faces), 4, dtype=np.int16)
        labels[face_centers[:, 0] > 4.99] = 5
        source = replace(base_source, face_target_labels=labels)
        adaptive = {
            "radial_stage_b": True,
            "adaptive_outer_skin": True,
        }
        recipes = {
            4: ColorDepthRecipe(4, 3, 1.0, 1, metadata=adaptive),
            5: ColorDepthRecipe(5, 2, 1.5, 1, metadata=adaptive),
        }

        for same_lineage in (True, False):
            with self.subTest(same_lineage=same_lineage):
                state: dict[str, object] = {
                    "build_calls": 0,
                    "ordinary_calls": 0,
                }

                def refinement_request(
                    kwargs: Mapping[str, object],
                    parent: int,
                    overdepth: float,
                ) -> exact_partition_module._AdaptiveInterfaceRefinementRequired:
                    cells = np.asarray(kwargs["tets"], dtype=np.int32)
                    edge = np.sort(cells[int(parent), :2])[None, :]
                    return exact_partition_module._AdaptiveInterfaceRefinementRequired(
                        threshold_mm=float(kwargs["threshold_mm"]),
                        maximum_overdepth_mm=float(overdepth),
                        maximum_vertex_overdepth_mm=0.0,
                        maximum_interior_overdepth_mm=float(overdepth),
                        parent_cells=np.asarray((parent,), dtype=np.int32),
                        violating_triangles=1,
                        three_edge_parent_cells=0,
                        four_edge_parent_cells=1,
                        violating_sample_roles={
                            "edge_midpoint_01": 1,
                            "face_centroid": 1,
                        },
                        maximum_sample_roles={"face_centroid": 1},
                        maximum_overdepth_by_sample_role_mm={
                            "face_centroid": float(overdepth)
                        },
                        refinement_edges=edge,
                        refinement_edge_record={"unique_seed_edges": 1},
                    )

                def fake_build(**kwargs: object) -> None:
                    state["build_calls"] = int(state["build_calls"]) + 1
                    if int(state["build_calls"]) == 1:
                        raise refinement_request(kwargs, 0, 0.20)
                    key = (
                        "same_parent"
                        if same_lineage
                        else "different_parent"
                    )
                    raise refinement_request(kwargs, int(state[key]), 0.19)

                def fake_ordinary(**kwargs: object) -> tuple[object, ...]:
                    state["ordinary_calls"] = int(state["ordinary_calls"]) + 1
                    if int(state["ordinary_calls"]) > 1:
                        raise ColorDepthExactPartitionError(
                            "mock_second_ordinary_refinement"
                        )
                    cells = np.asarray(kwargs["tets"], dtype=np.int32)
                    order = np.roll(np.arange(len(cells), dtype=np.int32), 1)
                    inverse = np.empty(len(order), dtype=np.int32)
                    inverse[order] = np.arange(len(order), dtype=np.int32)
                    state["same_parent"] = int(inverse[0])
                    state["different_parent"] = int(inverse[1])
                    boundary_cells = np.asarray(
                        kwargs["boundary_cells"], dtype=np.int32
                    )
                    return (
                        np.asarray(kwargs["nodes"], dtype=np.float64),
                        cells[order],
                        np.asarray(kwargs["boundary_faces"], dtype=np.int32),
                        inverse[boundary_cells],
                        np.asarray(kwargs["boundary_labels"], dtype=np.int32),
                        np.asarray(
                            kwargs["boundary_parent_faces"], dtype=np.int32
                        ),
                        np.asarray(kwargs["node_depth_mm"], dtype=np.float64),
                        {
                            "mode": "mock_ordinary_refinement",
                            "added_midpoint_nodes": 0,
                        },
                        order,
                    )

                def fake_fallback(**_kwargs: object) -> None:
                    raise ColorDepthExactPartitionError(
                        "mock_full_diameter_fallback"
                    )

                with patch.object(
                    exact_partition_module,
                    "_build_threshold_partition",
                    side_effect=fake_build,
                ), patch.object(
                    exact_partition_module,
                    "_bisect_internal_edge_stars",
                    side_effect=fake_ordinary,
                ) as ordinary_mock, patch.object(
                    exact_partition_module,
                    "_refine_stagnant_four_edge_parent_diameters",
                    side_effect=fake_fallback,
                ) as fallback_mock:
                    with self.assertRaises(
                        ColorDepthExactPartitionError
                    ) as caught:
                        build_conforming_color_depth_partition(source, recipes)

                expected_code = (
                    "mock_full_diameter_fallback"
                    if same_lineage
                    else "mock_second_ordinary_refinement"
                )
                self.assertEqual(caught.exception.code, expected_code)
                self.assertEqual(
                    len(
                        caught.exception.details[
                            "completed_local_refinement_rounds"
                        ]
                    ),
                    1,
                )
                policy = caught.exception.details["stagnation_policy"]
                self.assertEqual(
                    bool(policy["use_full_diameter_fallback"]),
                    same_lineage,
                )
                self.assertEqual(fallback_mock.call_count, int(same_lineage))
                self.assertEqual(
                    ordinary_mock.call_count,
                    1 if same_lineage else 2,
                )
                completed = caught.exception.details[
                    "completed_local_refinement_rounds"
                ][0]
                origin_ids = completed["trigger_signature"][
                    "spatial_lineage"
                ]["origin_cell_ids"]
                self.assertEqual(origin_ids, [0])

    def test_adaptive_refinement_budget_route_reserves_total_round_for_fallback(
        self,
    ) -> None:
        fallback_policy = {"use_full_diameter_fallback": True}
        exhausted_interface = (
            exact_partition_module._adaptive_refinement_budget_route(
                adaptive_stage_b=True,
                cause="interface",
                ordinary_interface_rounds=7,
                partner_rounds=0,
                stagnation_fallback_rounds=0,
                total_rounds=7,
                stagnation_policy=fallback_policy,
            )
        )
        self.assertTrue(exhausted_interface["allowed"])
        self.assertTrue(
            exhausted_interface["use_full_diameter_fallback"]
        )
        self.assertTrue(
            exhausted_interface["exhausted_interface_budget_replacement"]
        )
        self.assertEqual(
            exhausted_interface["reason"],
            "exhausted_interface_budget_stagnation_fallback",
        )

        total_exhausted = (
            exact_partition_module._adaptive_refinement_budget_route(
                adaptive_stage_b=True,
                cause="interface",
                ordinary_interface_rounds=7,
                partner_rounds=1,
                stagnation_fallback_rounds=0,
                total_rounds=8,
                stagnation_policy=fallback_policy,
            )
        )
        self.assertFalse(total_exhausted["allowed"])
        self.assertFalse(
            total_exhausted["use_full_diameter_fallback"]
        )
        self.assertEqual(
            total_exhausted["reason"],
            "total_refinement_budget_exhausted",
        )

        partner_exhausted = (
            exact_partition_module._adaptive_refinement_budget_route(
                adaptive_stage_b=True,
                cause="partner",
                ordinary_interface_rounds=0,
                partner_rounds=2,
                stagnation_fallback_rounds=0,
                total_rounds=2,
                stagnation_policy=fallback_policy,
            )
        )
        self.assertFalse(partner_exhausted["allowed"])
        self.assertFalse(
            partner_exhausted["use_full_diameter_fallback"]
        )
        self.assertEqual(
            partner_exhausted["reason"],
            "partner_refinement_budget_exhausted",
        )

    def test_main_loop_uses_exhausted_interface_round_as_bounded_fallback(
        self,
    ) -> None:
        request = _request()
        base_source = prepare_color_depth_source(request)
        face_centers = base_source.vertices_mm[base_source.faces].mean(axis=1)
        labels = np.full(len(base_source.faces), 4, dtype=np.int16)
        labels[face_centers[:, 0] > 4.99] = 5
        source = replace(base_source, face_target_labels=labels)
        adaptive = {
            "radial_stage_b": True,
            "adaptive_outer_skin": True,
        }
        recipes = {
            4: ColorDepthRecipe(4, 3, 1.0, 1, metadata=adaptive),
            5: ColorDepthRecipe(5, 2, 1.5, 1, metadata=adaptive),
        }
        overdepths = (2.0, 1.0, 0.5, 0.25, 0.125, 0.0625, 0.055, 0.054, 0.053)
        state = {"build_calls": 0}

        def fake_build(**kwargs: object) -> None:
            call = int(state["build_calls"])
            state["build_calls"] = call + 1
            cells = np.asarray(kwargs["tets"], dtype=np.int32)
            edge = np.sort(cells[0, :2])[None, :]
            overdepth = float(overdepths[call])
            raise exact_partition_module._AdaptiveInterfaceRefinementRequired(
                threshold_mm=float(kwargs["threshold_mm"]),
                maximum_overdepth_mm=overdepth,
                maximum_vertex_overdepth_mm=0.0,
                maximum_interior_overdepth_mm=overdepth,
                parent_cells=np.asarray((0,), dtype=np.int32),
                violating_triangles=1,
                three_edge_parent_cells=0,
                four_edge_parent_cells=1,
                violating_sample_roles={
                    "edge_midpoint_01": 1,
                    "face_centroid": 1,
                },
                maximum_sample_roles={"face_centroid": 1},
                maximum_overdepth_by_sample_role_mm={
                    "face_centroid": overdepth
                },
                refinement_edges=edge,
                refinement_edge_record={"unique_seed_edges": 1},
            )

        def identity_refinement(**kwargs: object) -> tuple[object, ...]:
            cells = np.asarray(kwargs["tets"], dtype=np.int32)
            return (
                np.asarray(kwargs["nodes"], dtype=np.float64),
                cells,
                np.asarray(kwargs["boundary_faces"], dtype=np.int32),
                np.asarray(kwargs["boundary_cells"], dtype=np.int32),
                np.asarray(kwargs["boundary_labels"], dtype=np.int32),
                np.asarray(kwargs["boundary_parent_faces"], dtype=np.int32),
                np.asarray(kwargs["node_depth_mm"], dtype=np.float64),
                {
                    "mode": "mock_bounded_refinement",
                    "added_midpoint_nodes": 0,
                },
                np.arange(len(cells), dtype=np.int32),
            )

        with patch.object(
            exact_partition_module,
            "_build_threshold_partition",
            side_effect=fake_build,
        ), patch.object(
            exact_partition_module,
            "_bisect_internal_edge_stars",
            side_effect=identity_refinement,
        ) as ordinary_mock, patch.object(
            exact_partition_module,
            "_refine_stagnant_four_edge_parent_diameters",
            side_effect=identity_refinement,
        ) as fallback_mock:
            with self.assertRaises(ColorDepthExactPartitionError) as caught:
                build_conforming_color_depth_partition(source, recipes)

        self.assertEqual(
            caught.exception.code,
            "adaptive_interface_stagnation_not_contracted",
        )
        self.assertEqual(ordinary_mock.call_count, 7)
        self.assertEqual(fallback_mock.call_count, 1)
        self.assertEqual(state["build_calls"], 9)
        details = caught.exception.details
        self.assertEqual(details["ordinary_interface_refinement_rounds"], 7)
        self.assertEqual(details["stagnation_fallback_refinement_rounds"], 1)
        self.assertEqual(details["fallback_rounds"], 1)
        self.assertEqual(details["partner_refinement_rounds"], 0)
        self.assertEqual(details["total_rounds"], 8)
        completed = details["completed_local_refinement_rounds"]
        self.assertEqual(len(completed), 8)
        self.assertTrue(
            all(
                not record["stagnation_full_diameter_fallback"]
                for record in completed[:7]
            )
        )
        fallback_record = completed[7]
        self.assertTrue(
            fallback_record["stagnation_full_diameter_fallback"]
        )
        self.assertEqual(fallback_record["cause_round"], 1)
        self.assertEqual(
            fallback_record["cause_round_kind"], "stagnation_fallback"
        )
        self.assertEqual(fallback_record["ordinary_interface_rounds_after"], 7)
        self.assertEqual(fallback_record["stagnation_fallback_rounds_after"], 1)
        self.assertEqual(fallback_record["partner_rounds_after"], 0)
        self.assertEqual(fallback_record["total_rounds_after"], 8)
        route = fallback_record["refinement_budget_route"]
        self.assertTrue(route["exhausted_interface_budget_replacement"])
        self.assertEqual(
            route["reason"],
            "exhausted_interface_budget_stagnation_fallback",
        )
        self.assertTrue(details["stagnation_policy"]["hard_stop"])
        self.assertEqual(
            details["refinement_budget_route"]["reason"],
            "total_refinement_budget_exhausted",
        )

    def test_stagnation_full_diameter_refinement_measures_contraction(
        self,
    ) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(((0, 1, 2, 3),), dtype=np.int32)
        boundary_faces, boundary_cells = (
            exact_partition_module._oriented_boundary_faces(nodes, tets)
        )
        source_mesh = trimesh.Trimesh(
            vertices=nodes,
            faces=boundary_faces,
            process=False,
        )
        labels = np.full(len(boundary_faces), 4, dtype=np.int32)
        parents = np.arange(len(boundary_faces), dtype=np.int32)
        refine_stagnant = getattr(
            exact_partition_module,
            "_refine_stagnant_four_edge_parent_diameters",
        )

        (
            refined_nodes,
            refined_tets,
            refined_faces,
            _refined_cells,
            refined_labels,
            refined_parents,
            _refined_depth,
            record,
            output_parents,
        ) = refine_stagnant(
            source_mesh=source_mesh,
            nodes=nodes,
            tets=tets,
            boundary_faces=boundary_faces,
            boundary_cells=boundary_cells,
            boundary_labels=labels,
            boundary_parent_faces=parents,
            node_depth_mm=np.zeros(len(nodes), dtype=np.float64),
            parent_cells=np.asarray((0,), dtype=np.int32),
            threshold_mm=0.14,
            chunk_size=100,
        )

        self.assertEqual(
            record["mode"],
            "adaptive_interface_stagnation_full_diameter_refinement",
        )
        self.assertTrue(record["diameter_contraction_verified"])
        self.assertLessEqual(
            record["maximum_child_parent_diameter_ratio"],
            exact_partition_module._ADAPTIVE_STAGNATION_MAX_CHILD_DIAMETER_RATIO,
        )
        self.assertGreaterEqual(record["diameter_refinement_passes"], 1)
        self.assertTrue(np.all(output_parents == 0))
        self.assertTrue(
            np.all(
                exact_partition_module._signed_six(
                    refined_nodes, refined_tets
                )
                > 0.0
            )
        )
        self.assertAlmostEqual(_volume(refined_nodes, refined_tets), 1.0 / 6.0)
        self.assertEqual(set(refined_labels), set(labels))
        self.assertEqual(set(refined_parents), set(parents))
        self.assertGreaterEqual(len(refined_faces), len(boundary_faces))

        with patch.object(
            exact_partition_module,
            "_MAX_VARIABLE_PARTITION_CELLS",
            7,
        ):
            with self.assertRaises(ColorDepthExactPartitionError) as caught:
                refine_stagnant(
                    source_mesh=source_mesh,
                    nodes=nodes,
                    tets=tets,
                    boundary_faces=boundary_faces,
                    boundary_cells=boundary_cells,
                    boundary_labels=labels,
                    boundary_parent_faces=parents,
                    node_depth_mm=np.zeros(len(nodes), dtype=np.float64),
                    parent_cells=np.asarray((0,), dtype=np.int32),
                    threshold_mm=0.14,
                    chunk_size=100,
                )
        self.assertEqual(
            caught.exception.code, "variable_partition_cell_limit_exceeded"
        )
        self.assertEqual(caught.exception.details["maximum"], 7)
        self.assertEqual(caught.exception.details["stagnation_diameter_pass"], 1)
        self.assertEqual(
            caught.exception.details["completed_stagnation_diameter_passes"],
            [],
        )

        with patch.object(
            exact_partition_module,
            "_ADAPTIVE_STAGNATION_MAX_CHILD_DIAMETER_RATIO",
            0.10,
        ), patch.object(
            exact_partition_module,
            "_ADAPTIVE_STAGNATION_DIAMETER_REFINEMENT_PASSES",
            1,
        ):
            with self.assertRaises(ColorDepthExactPartitionError) as caught:
                refine_stagnant(
                    source_mesh=source_mesh,
                    nodes=nodes,
                    tets=tets,
                    boundary_faces=boundary_faces,
                    boundary_cells=boundary_cells,
                    boundary_labels=labels,
                    boundary_parent_faces=parents,
                    node_depth_mm=np.zeros(len(nodes), dtype=np.float64),
                    parent_cells=np.asarray((0,), dtype=np.int32),
                    threshold_mm=0.14,
                    chunk_size=100,
                )
        self.assertEqual(
            caught.exception.code,
            "adaptive_interface_stagnation_diameter_not_contracted",
        )
        self.assertGreater(
            caught.exception.details["maximum_child_parent_diameter_ratio"],
            0.10,
        )

    def test_adaptive_interface_sample_maps_to_opposite_same_sign_edge(
        self,
    ) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(((0, 1, 2, 3),), dtype=np.int32)
        scalar = np.asarray((-1.0, 1.0, 1.0, 1.0), dtype=np.float64)
        unique_edges = np.asarray(
            ((0, 1), (0, 2), (0, 3)), dtype=np.int32
        )
        refinement_edges, record = (
            exact_partition_module._adaptive_interface_refinement_edges(
                nodes=nodes,
                tets=tets,
                scalar=scalar,
                interface_triangles=np.asarray(((4, 5, 6),), dtype=np.int32),
                interface_parent=np.asarray((0,), dtype=np.int32),
                base_node_count=4,
                unique_edges=unique_edges,
                violating_triangle_ids=np.asarray((0,), dtype=np.int32),
                violating_sample_mask=np.asarray(
                    ((False, False, False, True, False, False, False),),
                    dtype=bool,
                ),
            )
        )

        self.assertTrue(
            np.array_equal(
                refinement_edges,
                np.asarray(((1, 2),), dtype=np.int32),
            )
        )
        self.assertEqual(record["opposite_same_sign_face_edges"], 1)
        self.assertEqual(record["unique_seed_edges"], 1)

    def test_adaptive_four_edge_refinement_uses_both_sign_edges_and_centroid(
        self,
    ) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(((0, 1, 2, 3),), dtype=np.int32)
        scalar = np.asarray((-1.0, -1.0, 1.0, 1.0), dtype=np.float64)
        crossing_edges = np.asarray(
            ((0, 2), (0, 3), (1, 2), (1, 3)), dtype=np.int32
        )

        refinement_edges, record = (
            exact_partition_module._adaptive_interface_refinement_edges(
                nodes=nodes,
                tets=tets,
                scalar=scalar,
                interface_triangles=np.asarray(((4, 7, 5),), dtype=np.int32),
                interface_parent=np.asarray((0,), dtype=np.int32),
                base_node_count=4,
                unique_edges=crossing_edges,
                violating_triangle_ids=np.asarray((0,), dtype=np.int32),
                violating_sample_mask=np.asarray(
                    ((False, False, False, True, False, False, True),),
                    dtype=bool,
                ),
            )
        )

        self.assertTrue(
            np.array_equal(
                refinement_edges,
                np.asarray(((0, 1), (2, 3)), dtype=np.int32),
            )
        )
        self.assertEqual(record["two_two_diagonal_fallback_events"], 1)
        self.assertEqual(record["two_two_diagonal_fallback_edges"], 2)
        self.assertEqual(record["face_centroid_refinement_events"], 1)
        self.assertEqual(record["face_centroid_fallback_edges"], 2)
        self.assertEqual(record["raw_edge_requests"], 4)
        self.assertEqual(record["unique_seed_edges"], 2)
        self.assertEqual(record["seed_edge_examples"], [[0, 1], [2, 3]])
        self.assertTrue(record["seed_edge_examples_complete"])

    def test_adaptive_partner_children_map_to_input_parent_edges(self) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 3.0, 0.0),
                (0.0, 0.0, 2.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(((0, 1, 2, 3),), dtype=np.int32)
        scalar = np.asarray((-1.0, 1.0, 1.0, 1.0), dtype=np.float64)
        unique_edges = np.asarray(
            ((0, 1), (0, 2), (0, 3)), dtype=np.int32
        )
        output_tets = np.asarray(
            (
                (1, 2, 4, 5),
                (0, 4, 5, 6),
                (0, 4, 5, 7),
            ),
            dtype=np.int32,
        )

        refinement_edges, parents, record = (
            exact_partition_module._adaptive_partner_refinement_edges(
                nodes=nodes,
                tets=tets,
                scalar=scalar,
                output_tets=output_tets,
                output_parents=np.asarray((0, 0, 0), dtype=np.int32),
                base_node_count=4,
                output_node_count=8,
                unique_edges=unique_edges,
                violating_output_cell_ids=np.asarray(
                    (0, 1, 2), dtype=np.int64
                ),
                violating_sample_role_ids=np.asarray(
                    (4, 4, 10), dtype=np.int64
                ),
            )
        )

        self.assertTrue(
            np.array_equal(
                refinement_edges,
                np.asarray(((1, 2), (2, 3)), dtype=np.int32),
            )
        )
        self.assertTrue(np.array_equal(parents, np.asarray((0,), dtype=np.int32)))
        self.assertEqual(record["violating_output_children"], 3)
        self.assertEqual(record["unique_input_parent_cells"], 1)
        self.assertEqual(record["exact_child_parent_edges"], 1)
        self.assertEqual(
            record["generated_child_edge_longest_parent_fallbacks"], 1
        )
        self.assertEqual(
            record["face_or_cell_centroid_longest_parent_fallbacks"], 1
        )
        self.assertEqual(record["generated_nonroot_child_node_references"], 1)
        self.assertEqual(record["provisional_generated_nodes_used_as_seeds"], 0)
        self.assertTrue(np.all(refinement_edges < 4))

    def test_adaptive_partner_vertex_violation_fails_closed(self) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        with self.assertRaises(ColorDepthExactPartitionError) as caught:
            exact_partition_module._adaptive_partner_refinement_edges(
                nodes=nodes,
                tets=np.asarray(((0, 1, 2, 3),), dtype=np.int32),
                scalar=np.asarray((-1.0, 1.0, 1.0, 1.0)),
                output_tets=np.asarray(((0, 4, 5, 6),), dtype=np.int32),
                output_parents=np.asarray((0,), dtype=np.int32),
                base_node_count=4,
                output_node_count=7,
                unique_edges=np.asarray(
                    ((0, 1), (0, 2), (0, 3)), dtype=np.int32
                ),
                violating_output_cell_ids=np.asarray((0,), dtype=np.int64),
                violating_sample_role_ids=np.asarray((0,), dtype=np.int64),
            )
        self.assertEqual(
            caught.exception.code,
            "adaptive_partner_vertex_violation_has_no_refinement_edge",
        )

    def test_adaptive_interface_boundary_edge_inherits_face_provenance(
        self,
    ) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(((0, 1, 2, 3),), dtype=np.int32)
        boundary_faces, boundary_cells = (
            exact_partition_module._oriented_boundary_faces(nodes, tets)
        )
        source_mesh = trimesh.Trimesh(
            vertices=nodes,
            faces=boundary_faces,
            process=False,
        )
        labels = np.arange(4, 4 + len(boundary_faces), dtype=np.int32)
        parents = np.arange(20, 20 + len(boundary_faces), dtype=np.int32)

        (
            refined_nodes,
            refined_tets,
            refined_faces,
            _refined_cells,
            refined_labels,
            refined_parents,
            refined_depth,
            record,
            _output_parents,
        ) = exact_partition_module._bisect_internal_edge_stars(
            source_mesh=source_mesh,
            nodes=nodes,
            tets=tets,
            boundary_faces=boundary_faces,
            boundary_cells=boundary_cells,
            boundary_labels=labels,
            boundary_parent_faces=parents,
            node_depth_mm=np.zeros(len(nodes), dtype=np.float64),
            seed_edges=np.asarray(((0, 1),), dtype=np.int32),
            threshold_mm=0.14,
            chunk_size=100,
        )

        self.assertEqual(refined_nodes.shape, (5, 3))
        self.assertEqual(refined_tets.shape, (2, 4))
        self.assertEqual(refined_faces.shape, (6, 3))
        self.assertEqual(record["boundary_seed_edges"], 1)
        self.assertEqual(record["source_boundary_faces_subdivided"], 2)
        self.assertEqual(float(refined_depth[-1]), 0.0)
        for source_face, source_label, source_parent in zip(
            boundary_faces, labels, parents, strict=True
        ):
            contains_edge = 0 in source_face and 1 in source_face
            expected_count = 2 if contains_edge else 1
            inherited = (
                (refined_labels == source_label)
                & (refined_parents == source_parent)
            )
            self.assertEqual(int(np.count_nonzero(inherited)), expected_count)

    def test_adaptive_interface_all_tetrahedron_edges_split_conformingly(
        self,
    ) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (2.0, 0.0, 0.0),
                (0.0, 2.0, 0.0),
                (0.0, 0.0, 2.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(((0, 1, 2, 3),), dtype=np.int32)
        boundary_faces, boundary_cells = (
            exact_partition_module._oriented_boundary_faces(nodes, tets)
        )
        source_mesh = trimesh.Trimesh(
            vertices=nodes,
            faces=boundary_faces,
            process=False,
        )
        labels = np.arange(4, 4 + len(boundary_faces), dtype=np.int32)
        parents = np.arange(20, 20 + len(boundary_faces), dtype=np.int32)
        source_volume = _volume(nodes, tets)

        (
            refined_nodes,
            refined_tets,
            refined_faces,
            _refined_cells,
            refined_labels,
            refined_parents,
            refined_depth,
            record,
            output_parents,
        ) = exact_partition_module._bisect_internal_edge_stars(
            source_mesh=source_mesh,
            nodes=nodes,
            tets=tets,
            boundary_faces=boundary_faces,
            boundary_cells=boundary_cells,
            boundary_labels=labels,
            boundary_parent_faces=parents,
            node_depth_mm=np.zeros(len(nodes), dtype=np.float64),
            seed_edges=np.asarray(
                ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                dtype=np.int32,
            ),
            threshold_mm=0.14,
            chunk_size=100,
        )

        self.assertEqual(record["seed_edges"], 6)
        self.assertEqual(record["boundary_seed_edges"], 6)
        self.assertEqual(record["incident_tetrahedron_splits"], 7)
        self.assertEqual(refined_nodes.shape, (10, 3))
        self.assertEqual(refined_tets.shape, (8, 4))
        self.assertEqual(refined_faces.shape, (16, 3))
        self.assertTrue(
            np.all(
                exact_partition_module._signed_six(
                    refined_nodes, refined_tets
                )
                > 0.0
            )
        )
        self.assertAlmostEqual(
            _volume(refined_nodes, refined_tets), source_volume
        )
        self.assertTrue(np.array_equal(output_parents, np.zeros(8, dtype=np.int32)))
        self.assertTrue(np.array_equal(refined_depth[4:], np.zeros(6)))
        for source_label, source_parent in zip(labels, parents, strict=True):
            inherited = (
                (refined_labels == source_label)
                & (refined_parents == source_parent)
            )
            self.assertEqual(int(np.count_nonzero(inherited)), 4)

        all_faces = np.concatenate(
            (
                refined_tets[:, (0, 1, 2)],
                refined_tets[:, (0, 3, 1)],
                refined_tets[:, (1, 3, 2)],
                refined_tets[:, (0, 2, 3)],
            ),
            axis=0,
        )
        canonical = np.sort(all_faces, axis=1)
        _keys, incidence = np.unique(canonical, axis=0, return_counts=True)
        self.assertTrue(np.all((incidence == 1) | (incidence == 2)))
        self.assertEqual(int(np.count_nonzero(incidence == 1)), 16)
        self.assertEqual(int(np.count_nonzero(incidence == 2)), 8)
        boundary_keys = {
            tuple(map(int, row)) for row in np.sort(refined_faces, axis=1)
        }
        incidence_one_keys = {
            tuple(map(int, row))
            for row, count in zip(_keys, incidence, strict=True)
            if int(count) == 1
        }
        self.assertEqual(boundary_keys, incidence_one_keys)

    def test_variable_band_without_safe_backing_fails_closed(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        labels = np.full(len(source.faces), 4, dtype=np.int16)
        labels[0] = 5
        source = replace(source, face_target_labels=labels)
        recipes = {
            4: ColorDepthRecipe(4, 3, 0.10, 1),
            5: ColorDepthRecipe(5, 2, 0.42, 1),
        }
        with self.assertRaises(ColorDepthExactPartitionError) as caught:
            build_conforming_color_depth_partition(source, recipes)
        self.assertEqual(
            caught.exception.code,
            "variable_threshold_material_visibility_missing",
        )
        self.assertEqual(caught.exception.details["safe_backing_cells"], 0)

    def test_adaptive_stage_b_refuses_deep_unsafe_partner_columns(self) -> None:
        # Regression for the original 2 x 2 x 2, 4.5 mm-cell validation
        # head: the former outer-only fallback silently made more than 98% of
        # this 729 mm3 solid partner material.  Adaptive Stage B must localise
        # the column within tolerance or stop; it may never emit that deep
        # partner volume.
        box = trimesh.creation.box(extents=(9.0, 9.0, 9.0))
        vertices, faces = trimesh.remesh.subdivide(
            np.asarray(box.vertices, dtype=np.float64),
            np.asarray(box.faces, dtype=np.int32),
        )
        centers = vertices[faces].mean(axis=1)
        labels = np.where(centers[:, 0] < 0.0, 4, 10).astype(np.int16)
        self.assertEqual(len(faces), 48)
        source = ColorDepthSourceSurface(
            vertices_mm=vertices,
            faces=faces,
            face_target_labels=labels,
            height_mm=9.0,
            source_name="adaptive-unsafe-column-regression",
            source_sha256="a" * 64,
            source_volume_mm3=729.0,
            metadata={"fixture": "2x2x2 4.5 mm convex box"},
        )
        adaptive = {
            "radial_stage_b": True,
            "adaptive_outer_skin": True,
        }
        recipes = {
            4: ColorDepthRecipe(4, 2, 0.10, 1, metadata=adaptive),
            10: ColorDepthRecipe(10, 2, 0.42, 1, metadata=adaptive),
        }
        try:
            partition = build_conforming_color_depth_partition(source, recipes)
        except ColorDepthExactPartitionError as caught:
            self.assertIn(
                caught.code,
                {
                    "localized_threshold_interface_too_deep",
                    "adaptive_partner_cell_too_deep",
                    "adaptive_interface_stagnation_not_contracted",
                    "adaptive_interface_stagnation_diameter_not_contracted",
                },
            )
            return

        # Local refinement may now resolve this deliberately coarse fixture.
        # Success is acceptable only when the same independent 7/15-point
        # proof gates certify the repaired interface and complete partner cells.
        self.assertAlmostEqual(
            _volume(partition.nodes_mm, partition.tetrahedra),
            source.source_volume_mm3,
            places=8,
        )
        self.assertTrue(partition.threshold_interface_conforming)
        self.assertTrue(partition.shared_interface_partition_exact)
        self.assertGreater(
            sum(
                int(record["adaptive_interface_local_refinement"]["round_count"])
                for record in partition.metadata["threshold_passes"]
            ),
            0,
        )
        for record in partition.metadata["threshold_passes"]:
            self.assertLessEqual(
                float(
                    record[
                        "maximum_material_changing_interface_overdepth_mm"
                    ]
                ),
                float(record["interface_error_limit_mm"]) + 1e-12,
            )
            self.assertLessEqual(
                float(record["maximum_partner_cell_sample_depth_mm"]),
                float(record["threshold_mm"])
                + float(record["interface_error_limit_mm"])
                + 1e-12,
            )

    def test_six_discrete_adaptive_bands_preserve_sampled_depth_proofs(self) -> None:
        # Six separated, well-resolved curved coupons keep every state region
        # wider than its requested skin.  A checkerboard painted onto the
        # coarse cube is intentionally not a valid visibility fixture: some
        # owner columns are thinner than one band and must fail closed.
        components: list[trimesh.Trimesh] = []
        labels: list[int] = []
        for index in range(6):
            component = trimesh.creation.icosphere(subdivisions=1, radius=3.0)
            component.apply_translation((8.0 * index, 0.0, 0.0))
            components.append(component)
            labels.extend([4 + index] * len(component.faces))
        coupon = trimesh.util.concatenate(components)
        source = ColorDepthSourceSurface(
            vertices_mm=np.asarray(coupon.vertices, dtype=np.float64),
            faces=np.asarray(coupon.faces, dtype=np.int32),
            face_target_labels=np.asarray(labels, dtype=np.int16),
            height_mm=6.0,
            source_name="six-band-curved-coupon",
            source_sha256="6" * 64,
            source_volume_mm3=float(sum(item.volume for item in components)),
            metadata={"fixture": "six separated curved coupons"},
        )
        adaptive = {
            "radial_stage_b": True,
            "adaptive_outer_skin": True,
        }
        recipes = {
            label: ColorDepthRecipe(
                target_label=label,
                outer_physical=2 + (label % 3),
                # Validation-head range: six global bands from 0.10 through
                # 0.42 mm, including the thin 0.4-nozzle/Arachne experiment.
                outer_thickness_mm=0.10 + 0.064 * (label - 4),
                backing_physical=1,
                metadata=adaptive,
            )
            for label in range(4, 10)
        }

        started = time.perf_counter()
        partition = build_conforming_color_depth_partition(source, recipes)
        elapsed = time.perf_counter() - started
        result = build_color_depth_result_from_partition(
            source,
            recipes,
            partition,
        )

        self.assertEqual(partition.metadata["threshold_pass_count"], 6)
        self.assertEqual(len(partition.metadata["unique_thresholds_mm"]), 6)
        self.assertTrue(partition.metadata["adaptive_stage_b_partner_depth_guard"])
        self.assertTrue(partition.threshold_interface_conforming)
        self.assertTrue(partition.shared_interface_partition_exact)
        self.assertEqual(result.metadata["gap_mm"], 0.0)
        self.assertEqual(result.metadata["positive_overlap_mm3"], 0.0)
        self.assertEqual(
            result.metadata["coordinate_triangle_accounting"][
                "internal_opposite_winding_failures"
            ],
            0,
        )
        self.assertAlmostEqual(
            _volume(partition.nodes_mm, partition.tetrahedra),
            source.source_volume_mm3,
            places=7,
        )
        for label in range(4, 10):
            safe_owner = (
                (partition.cell_owner_labels == label)
                & ~partition.unsafe_outer_only_cells
            )
            materials = set(
                map(int, np.unique(partition.cell_materials[safe_owner]))
            )
            self.assertIn(recipes[label].outer_physical, materials)
            self.assertIn(recipes[label].backing_physical, materials)
        for record in partition.metadata["threshold_passes"]:
            self.assertGreater(
                record["material_changing_threshold_triangles"],
                0,
            )
            self.assertTrue(record["adaptive_partner_depth_samples_verified"])
            self.assertEqual(record["adaptive_partner_proof_samples_per_cell"], 15)
            self.assertEqual(
                record["adaptive_interface_proof_samples_per_triangle"],
                7,
            )
            self.assertEqual(
                record["adaptive_edge_root"]["method"],
                "outer_first_true_distance_lipschitz_bracket",
            )
            self.assertEqual(
                record["adaptive_edge_root"]["application"],
                "conservative_positive_nodal_scalar_elevation",
            )
            self.assertFalse(
                record["adaptive_edge_root"][
                    "direct_nonplanar_root_points_used"
                ]
            )
            self.assertTrue(
                record["adaptive_edge_root"][
                    "shared_piecewise_affine_level_set_preserved"
                ]
            )
            self.assertLessEqual(
                record["maximum_material_changing_interface_vertex_overdepth_mm"],
                1e-12,
            )
            self.assertLessEqual(
                record["maximum_partner_cell_sample_depth_mm"],
                float(record["threshold_mm"])
                + float(record["interface_error_limit_mm"])
                + 1e-12,
            )
        self.assertLess(len(partition.tetrahedra), 100_000)
        self.assertLess(elapsed, 30.0)

    def test_small_cube_safe_threshold_keeps_a_physical_backing_region(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        recipe = ColorDepthRecipe(
            target_label=4,
            outer_physical=3,
            outer_thickness_mm=1.0,
            backing_physical=1,
        )
        partition = build_conforming_color_depth_partition(source, {4: recipe})

        self.assertEqual(set(map(int, np.unique(partition.cell_materials))), {1, 3})
        self.assertGreater(
            partition.metadata["material_changing_threshold_triangles"], 0
        )
        self.assertEqual(
            partition.metadata["unsafe_material_changing_threshold_triangles"],
            0,
        )
        self.assertTrue(
            np.all(
                partition.cell_materials[partition.unsafe_outer_only_cells] == 3
            )
        )
        self.assertLessEqual(
            partition.metadata["maximum_material_changing_interface_error_mm"],
            0.05 + 1e-12,
        )

    def test_no_hidden_backing_is_valid_when_threshold_exceeds_inradius(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        recipe = ColorDepthRecipe(
            target_label=4,
            outer_physical=3,
            outer_thickness_mm=3.1,
            backing_physical=1,
        )
        partition = build_conforming_color_depth_partition(source, {4: recipe})
        self.assertEqual(
            partition.metadata["hidden_threshold_visibility"][
                "hidden_threshold_cells"
            ],
            0,
        )
        self.assertEqual(partition.metadata["crossing_input_cells"], 0)
        self.assertTrue(np.all(partition.cell_materials == 3))

    def test_recipe_contracts_fail_closed(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        finite = ColorDepthRecipe(
            target_label=4,
            outer_physical=3,
            outer_thickness_mm=0.15,
            backing_physical=1,
            backing_depth_mm=0.25,
            core_physical=2,
        )
        with self.assertRaises(ColorDepthExactPartitionError) as caught:
            build_conforming_color_depth_partition(source, {4: finite})
        self.assertEqual(caught.exception.code, "finite_backing_depth_not_yet_supported")

        with self.assertRaises(ColorDepthExactPartitionError) as caught:
            build_conforming_color_depth_partition(
                source, request.recipes, interface_error_limit_mm=0.051
            )
        self.assertEqual(caught.exception.code, "invalid_interface_error_limit")

    def test_malformed_public_source_fails_before_native_tetgen(self) -> None:
        request = _request()
        source = prepare_color_depth_source(request)
        invalid_faces = source.faces.copy()
        invalid_faces[0, 0] = len(source.vertices_mm)
        malformed = replace(source, faces=invalid_faces)
        with self.assertRaises(ColorDepthExactPartitionError) as caught:
            build_conforming_color_depth_partition(malformed, request.recipes)
        self.assertEqual(caught.exception.code, "source_face_index_out_of_range")


if __name__ == "__main__":
    unittest.main(verbosity=2)
