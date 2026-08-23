from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.assembly import (
    AssemblyError,
    MULTIPART_INHERITED_SOURCE_WARNING,
    add_keyed_joint_for_seam,
    close_open_mesh,
    find_boundary_loops,
    mesh_is_watertight,
    multipart_self_intersection_limits,
    pair_matching_loops,
    repair_small_unmatched_boundaries,
    solidify_partitioned_parts,
    split_closed_mesh_with_joint,
    split_watertight_bodies,
    weld_matching_seams,
)


HEIGHT_MM = 100.0
DEFAULT_COLOR = np.asarray([0.25, 0.50, 0.75], dtype=np.float64)


def _box_mesh(
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
    *,
    open_side: str | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build an outward-wound box, optionally omitting one rectangular side."""
    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    vertices = np.asarray(
        [
            [x0, y0, z0],
            [x1, y0, z0],
            [x1, y1, z0],
            [x0, y1, z0],
            [x0, y0, z1],
            [x1, y0, z1],
            [x1, y1, z1],
            [x0, y1, z1],
        ],
        dtype=np.float64,
    )
    sides = {
        "zmin": ((0, 2, 1), (0, 3, 2)),
        "zmax": ((4, 5, 6), (4, 6, 7)),
        "ymin": ((0, 1, 5), (0, 5, 4)),
        "xmax": ((1, 2, 6), (1, 6, 5)),
        "ymax": ((2, 3, 7), (2, 7, 6)),
        "xmin": ((3, 0, 4), (3, 4, 7)),
    }
    if open_side is not None and open_side not in sides:
        raise ValueError(f"unknown box side: {open_side}")
    faces = np.asarray(
        [
            triangle
            for side, triangles in sides.items()
            if side != open_side
            for triangle in triangles
        ],
        dtype=np.int32,
    )
    colors = np.tile(DEFAULT_COLOR, (len(vertices), 1))
    return vertices, faces, colors


def _high_resolution_bipyramid(
    face_count: int = 39_838,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build a closed one-body mesh with a small cluster of tiny faces."""
    if face_count <= 0 or face_count % 2:
        raise ValueError("face_count must be a positive even number")
    ring_count = face_count // 2
    tiny_segment_count = min(200, ring_count - 1)
    tiny_arc = 1.0e-4
    widths = np.concatenate(
        (
            np.full(
                tiny_segment_count,
                tiny_arc / tiny_segment_count,
                dtype=np.float64,
            ),
            np.full(
                ring_count - tiny_segment_count,
                (2.0 * np.pi - tiny_arc)
                / (ring_count - tiny_segment_count),
                dtype=np.float64,
            ),
        )
    )
    angles = np.concatenate(
        (np.asarray([0.0], dtype=np.float64), np.cumsum(widths[:-1]))
    )
    ring = np.column_stack(
        (
            np.cos(angles),
            np.sin(angles),
            np.zeros(ring_count, dtype=np.float64),
        )
    )
    vertices = np.vstack(
        (
            np.asarray([[0.0, 0.0, 1.0], [0.0, 0.0, -1.0]]),
            ring,
        )
    )
    ring_ids = np.arange(ring_count, dtype=np.int32)
    next_ring_ids = (ring_ids + 1) % ring_count
    faces = np.empty((face_count, 3), dtype=np.int32)
    faces[0::2] = np.column_stack(
        (
            np.zeros(ring_count, dtype=np.int32),
            2 + ring_ids,
            2 + next_ring_ids,
        )
    )
    faces[1::2] = np.column_stack(
        (
            np.ones(ring_count, dtype=np.int32),
            2 + next_ring_ids,
            2 + ring_ids,
        )
    )
    colors = np.tile(DEFAULT_COLOR, (len(vertices), 1))
    return vertices, faces, colors


class _MockSelectedMesh:
    def __init__(self, selected: np.ndarray) -> None:
        self._selected = np.asarray(selected, dtype=bool)

    def face_selection_array(self) -> np.ndarray:
        return self._selected.copy()


class _MockMeshSet:
    def __init__(self, selected: np.ndarray) -> None:
        self._mesh = _MockSelectedMesh(selected)

    def add_mesh(self, *_args, **_kwargs) -> None:
        return None

    def apply_filter(self, *_args, **_kwargs) -> None:
        return None

    def current_mesh(self) -> _MockSelectedMesh:
        return self._mesh


def _matching_open_boxes() -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
]:
    # The two boxes occupy opposite sides of Z=0 and intentionally omit the
    # coincident faces on that plane.  Their four-edge openings form a seam.
    first = _box_mesh(
        (-0.20, -0.15, -0.20),
        (0.20, 0.15, 0.00),
        open_side="zmax",
    )
    second = _box_mesh(
        (-0.20, -0.15, 0.00),
        (0.20, 0.15, 0.20),
        open_side="zmin",
    )
    return first, second


def _assert_valid_colored_mesh(
    testcase: unittest.TestCase,
    mesh: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    vertices, faces, colors = mesh
    testcase.assertTrue(mesh_is_watertight(vertices, faces))
    testcase.assertEqual(vertices.ndim, 2)
    testcase.assertEqual(vertices.shape[1], 3)
    testcase.assertEqual(faces.ndim, 2)
    testcase.assertEqual(faces.shape[1], 3)
    testcase.assertEqual(colors.shape, (len(vertices), 3))
    testcase.assertTrue(np.isfinite(vertices).all())
    testcase.assertTrue(np.isfinite(colors).all())
    testcase.assertGreaterEqual(float(colors.min()), 0.0)
    testcase.assertLessEqual(float(colors.max()), 1.0)


class ExistingPartSeamTests(unittest.TestCase):
    def test_inherited_source_warning_uses_relative_bounded_limits(self) -> None:
        face_limit, area_limit = multipart_self_intersection_limits(
            39_838,
            MULTIPART_INHERITED_SOURCE_WARNING,
        )

        self.assertEqual(face_limit, 399)
        self.assertEqual(area_limit, 0.002)
        self.assertEqual(
            multipart_self_intersection_limits(
                10_000,
                MULTIPART_INHERITED_SOURCE_WARNING,
            ),
            (100, 0.002),
        )
        self.assertEqual(
            multipart_self_intersection_limits(
                10_001,
                MULTIPART_INHERITED_SOURCE_WARNING,
            ),
            (101, 0.002),
        )
        self.assertEqual(
            multipart_self_intersection_limits(
                650_000,
                MULTIPART_INHERITED_SOURCE_WARNING,
            ),
            (6_500, 0.002),
        )

    def test_inherited_source_warning_accepts_399_ids_but_rejects_400(
        self,
    ) -> None:
        closed = _high_resolution_bipyramid()
        source_face_limit = len(closed[1])

        selected = np.zeros(source_face_limit, dtype=bool)
        selected[:399] = True
        with patch(
            "spectrum_mapper.assembly.ml.MeshSet",
            return_value=_MockMeshSet(selected),
        ):
            _parts, record = solidify_partitioned_parts(
                [closed],
                [],
                height_mm=HEIGHT_MM,
                source_face_limits=(source_face_limit,),
                allow_bounded_source_self_intersections=True,
                bounded_self_intersection_policy=(
                    MULTIPART_INHERITED_SOURCE_WARNING
                ),
                source_triangle_ancestry_proven_parts=(True,),
            )

        part = record["parts"][0]
        self.assertEqual(part["self_intersections"], 399)
        self.assertEqual(part["self_intersection_face_limit"], 399)
        self.assertLess(
            part["self_intersecting_area_fraction"],
            part["self_intersection_area_fraction_limit"],
        )
        self.assertIs(part["self_intersection_source_faces_only"], True)
        self.assertIs(part["source_triangle_ancestry_proven"], True)
        self.assertIs(
            part["self_intersection_inherited_from_source"], True
        )
        self.assertEqual(
            part["self_intersection_policy"],
            MULTIPART_INHERITED_SOURCE_WARNING,
        )

        selected[399] = True
        with patch(
            "spectrum_mapper.assembly.ml.MeshSet",
            return_value=_MockMeshSet(selected),
        ), self.assertRaisesRegex(
            AssemblyError,
            "400 面 / 許容 399 面",
        ):
            solidify_partitioned_parts(
                [closed],
                [],
                height_mm=HEIGHT_MM,
                source_face_limits=(source_face_limit,),
                allow_bounded_source_self_intersections=True,
                bounded_self_intersection_policy=(
                    MULTIPART_INHERITED_SOURCE_WARNING
                ),
                source_triangle_ancestry_proven_parts=(True,),
            )

    def test_inherited_source_warning_requires_explicit_ancestry_proof(
        self,
    ) -> None:
        closed = _box_mesh(
            (-0.20, -0.15, -0.20),
            (0.20, 0.15, 0.20),
        )

        with self.assertRaisesRegex(AssemblyError, "入力由来三角形"):
            solidify_partitioned_parts(
                [closed],
                [],
                height_mm=HEIGHT_MM,
                source_face_limits=(len(closed[1]),),
                allow_bounded_source_self_intersections=True,
                bounded_self_intersection_policy=(
                    MULTIPART_INHERITED_SOURCE_WARNING
                ),
            )

        _parts, record = solidify_partitioned_parts(
            [closed],
            [],
            height_mm=HEIGHT_MM,
            source_face_limits=(len(closed[1]),),
            allow_bounded_source_self_intersections=True,
            bounded_self_intersection_policy=(
                MULTIPART_INHERITED_SOURCE_WARNING
            ),
            source_triangle_ancestry_proven_parts=(True,),
        )
        self.assertIs(
            record["parts"][0]["source_triangle_ancestry_proven"],
            True,
        )
        self.assertIs(
            record["parts"][0][
                "self_intersection_inherited_from_source"
            ],
            False,
        )
        self.assertEqual(
            record["parts"][0]["self_intersection_policy"],
            "strict_zero",
        )

    def test_inherited_source_ancestry_proof_count_must_match_parts(
        self,
    ) -> None:
        closed = _box_mesh(
            (-0.20, -0.15, -0.20),
            (0.20, 0.15, 0.20),
        )
        with self.assertRaisesRegex(AssemblyError, "パーツ数"):
            solidify_partitioned_parts(
                [closed],
                [],
                height_mm=HEIGHT_MM,
                source_triangle_ancestry_proven_parts=(True, False),
            )

    def test_matching_open_boxes_detect_and_pair_their_boundary_loops(self) -> None:
        first, second = _matching_open_boxes()

        first_loops = find_boundary_loops(0, first[0], first[1])
        second_loops = find_boundary_loops(1, second[0], second[1])

        self.assertEqual(len(first_loops), 1)
        self.assertEqual(len(second_loops), 1)
        for loop in (*first_loops, *second_loops):
            self.assertEqual(len(loop.vertex_ids), 4)
            np.testing.assert_allclose(loop.center_unit, [0.0, 0.0, 0.0])
            self.assertAlmostEqual(loop.perimeter_unit, 1.4)

        seams = pair_matching_loops(
            [*first_loops, *second_loops],
            height_mm=HEIGHT_MM,
            tolerance_mm=0.01,
        )

        self.assertEqual(len(seams), 1)
        seam = seams[0]
        self.assertEqual({seam.first.part_id, seam.second.part_id}, {0, 1})
        self.assertAlmostEqual(seam.match_rms_unit, 0.0)
        self.assertAlmostEqual(seam.match_max_unit, 0.0)

    def test_close_open_mesh_caps_the_boundary_and_is_watertight(self) -> None:
        first, _second = _matching_open_boxes()
        self.assertFalse(mesh_is_watertight(first[0], first[1]))

        vertices, faces, colors, record = close_open_mesh(*first)

        _assert_valid_colored_mesh(self, (vertices, faces, colors))
        self.assertFalse(record["before"]["watertight"])
        self.assertEqual(record["before"]["boundary_edges"], 4)
        self.assertTrue(record["after"]["watertight"])
        self.assertEqual(record["after"]["boundary_edges"], 0)
        self.assertGreaterEqual(record["added_faces"], 2)
        self.assertTrue(record["closed"])

    def test_matching_open_parts_weld_without_adding_faces(self) -> None:
        first, second = _matching_open_boxes()
        loops = [
            *find_boundary_loops(0, first[0], first[1]),
            *find_boundary_loops(1, second[0], second[1]),
        ]
        seams = pair_matching_loops(
            loops,
            height_mm=HEIGHT_MM,
            tolerance_mm=0.01,
        )

        vertices, faces, colors, record = weld_matching_seams(
            [first, second],
            seams,
            height_mm=HEIGHT_MM,
            tolerance_mm=0.01,
        )

        _assert_valid_colored_mesh(self, (vertices, faces, colors))
        self.assertEqual(len(faces), len(first[1]) + len(second[1]))
        self.assertEqual(record["method"], "matched_seam_weld")
        self.assertEqual(record["added_faces"], 0)
        self.assertEqual(record["merged_vertices"], 4)
        self.assertEqual(record["after"]["boundary_edges"], 0)

    def test_partitioned_parts_keep_count_and_share_one_interface(self) -> None:
        first, second = _matching_open_boxes()
        loops = [
            *find_boundary_loops(0, first[0], first[1]),
            *find_boundary_loops(1, second[0], second[1]),
        ]
        seams = pair_matching_loops(
            loops,
            height_mm=HEIGHT_MM,
            tolerance_mm=0.01,
        )

        parts, record = solidify_partitioned_parts(
            [first, second],
            seams,
            height_mm=HEIGHT_MM,
        )

        self.assertEqual(len(parts), 2)
        self.assertEqual(record["source_parts"], 2)
        self.assertEqual(record["output_parts"], 2)
        self.assertEqual(record["matched_seams"], 1)
        self.assertTrue(record["source_triangle_coordinates_preserved"])
        self.assertFalse(record["identity"])
        self.assertTrue(record["closed"])
        self.assertEqual(len(record["interfaces"]), 1)
        interface = record["interfaces"][0]
        self.assertEqual(interface["parts"], [0, 1])
        self.assertEqual(interface["boundary_vertices"], 4)
        self.assertEqual(interface["cap_faces"], 2)
        self.assertGreater(interface["safe_radius_mm"], 10.0)
        first_normal = np.asarray(
            interface["outward_normal_by_part"]["0"]
        )
        second_normal = np.asarray(
            interface["outward_normal_by_part"]["1"]
        )
        self.assertLess(float(np.dot(first_normal, second_normal)), -0.999)
        for source, part, part_record in zip(
            (first, second), parts, record["parts"], strict=True
        ):
            _assert_valid_colored_mesh(self, part)
            self.assertEqual(len(part[0]), len(source[0]))
            self.assertEqual(len(part[1]), len(source[1]) + 2)
            np.testing.assert_allclose(part[2], source[2])
            self.assertEqual(part_record["body_count"], 1)
            self.assertTrue(part_record["positive_volume"])
            self.assertEqual(part_record["degenerate_faces"], 0)
            self.assertEqual(part_record["self_intersections"], 0)

        cap_geometry = []
        for part_id, part in enumerate(parts):
            start, end = interface["cap_face_range_by_part"][str(part_id)]
            triangles = part[0][part[1][start:end]]
            canonical_triangles = sorted(
                tuple(sorted(tuple(point) for point in triangle))
                for triangle in triangles
            )
            cap_geometry.append(canonical_triangles)
        self.assertEqual(cap_geometry[0], cap_geometry[1])

    def test_near_matching_seam_disables_bounded_intersection_policy(
        self,
    ) -> None:
        first, second = _matching_open_boxes()
        shifted_vertices = second[0].copy()
        shifted_vertices[:, 2] += 1.0e-4  # 0.01 mm at the test height.
        second = (shifted_vertices, second[1], second[2])
        loops = [
            *find_boundary_loops(0, first[0], first[1]),
            *find_boundary_loops(1, second[0], second[1]),
        ]
        seams = pair_matching_loops(
            loops,
            height_mm=HEIGHT_MM,
            tolerance_mm=0.05,
        )

        _parts, record = solidify_partitioned_parts(
            [first, second],
            seams,
            height_mm=HEIGHT_MM,
            source_face_limits=(len(first[1]), len(second[1])),
            allow_bounded_source_self_intersections=True,
            bounded_self_intersection_policy=(
                "normalized_multipart_bounded_qem_warning"
            ),
        )

        self.assertFalse(record["source_triangle_coordinates_preserved"])
        self.assertFalse(
            record["interfaces"][0][
                "source_triangle_coordinates_preserved"
            ]
        )
        self.assertEqual(
            [
                value["self_intersection_source_face_limit"]
                for value in record["parts"]
            ],
            [0, 0],
        )

    def test_closed_partitioned_parts_are_identity_outputs(self) -> None:
        first = _box_mesh((-0.30, -0.10, -0.10), (-0.10, 0.10, 0.10))
        second = _box_mesh((0.10, -0.10, -0.10), (0.30, 0.10, 0.10))

        parts, record = solidify_partitioned_parts(
            [first, second],
            [],
            height_mm=HEIGHT_MM,
        )

        self.assertTrue(record["identity"])
        self.assertEqual(record["matched_seams"], 0)
        self.assertEqual(record["output_parts"], 2)
        for source, result in zip((first, second), parts, strict=True):
            for source_array, result_array in zip(
                source, result, strict=True
            ):
                np.testing.assert_array_equal(result_array, source_array)

    def test_unmatched_partition_boundary_is_rejected(self) -> None:
        first, _second = _matching_open_boxes()

        with self.assertRaisesRegex(AssemblyError, "一対一"):
            solidify_partitioned_parts(
                [first],
                [],
                height_mm=HEIGHT_MM,
            )

    def test_tiny_planar_unmatched_boundary_can_be_locally_capped(self) -> None:
        vertices, faces, colors = _matching_open_boxes()[0]
        mesh = (vertices * 0.01, faces, colors)
        loop = find_boundary_loops(0, mesh[0], mesh[1])[0]

        repaired, records = repair_small_unmatched_boundaries(
            [mesh],
            [loop],
            height_mm=HEIGHT_MM,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["method"], "strict_planar_local_cap")
        self.assertLess(records[0]["span_mm"], 2.0)
        self.assertGreater(records[0]["added_faces"], 0)
        _assert_valid_colored_mesh(self, repaired[0])
        np.testing.assert_array_equal(repaired[0][2], colors)

    def test_large_unmatched_boundary_is_not_locally_capped(self) -> None:
        mesh = _matching_open_boxes()[0]
        loop = find_boundary_loops(0, mesh[0], mesh[1])[0]

        with self.assertRaisesRegex(AssemblyError, "最大幅"):
            repair_small_unmatched_boundaries(
                [mesh],
                [loop],
                height_mm=HEIGHT_MM,
            )

    def test_warped_tiny_unmatched_boundary_is_not_locally_capped(self) -> None:
        vertices, faces, colors = _matching_open_boxes()[0]
        vertices = vertices * 0.01
        vertices[6, 2] += 0.001
        mesh = (vertices, faces, colors)
        loop = find_boundary_loops(0, mesh[0], mesh[1])[0]

        with self.assertRaisesRegex(AssemblyError, "平面性"):
            repair_small_unmatched_boundaries(
                [mesh],
                [loop],
                height_mm=HEIGHT_MM,
            )

    def test_strongly_warped_partition_seam_is_rejected(self) -> None:
        first, second = _matching_open_boxes()
        first = (first[0].copy(), first[1], first[2])
        second = (second[0].copy(), second[1], second[2])
        first[0][6, 2] = 0.05
        second[0][2, 2] = 0.05
        loops = [
            *find_boundary_loops(0, first[0], first[1]),
            *find_boundary_loops(1, second[0], second[1]),
        ]
        seams = pair_matching_loops(
            loops,
            height_mm=HEIGHT_MM,
            tolerance_mm=0.01,
        )

        with self.assertRaisesRegex(AssemblyError, "湾曲"):
            solidify_partitioned_parts(
                [first, second],
                seams,
                height_mm=HEIGHT_MM,
            )

    def test_disconnected_closed_bodies_become_independent_print_parts(self) -> None:
        first = _box_mesh((-0.30, -0.10, -0.10), (-0.10, 0.10, 0.10))
        second = _box_mesh((0.10, -0.10, -0.10), (0.30, 0.10, 0.10))
        second = (
            second[0],
            second[1],
            np.tile(np.asarray([0.9, 0.1, 0.2]), (len(second[0]), 1)),
        )
        combined = (
            np.vstack((first[0], second[0])),
            np.vstack((first[1], second[1] + len(first[0]))),
            np.vstack((first[2], second[2])),
        )

        bodies, record = split_watertight_bodies(combined)

        self.assertEqual(record["body_count"], 2)
        self.assertEqual(len(bodies), 2)
        for body in bodies:
            _assert_valid_colored_mesh(self, body)
        np.testing.assert_allclose(bodies[0][2], first[2])
        np.testing.assert_allclose(bodies[1][2], second[2])

    def test_keyed_male_and_female_parts_remain_watertight(self) -> None:
        first_open, second_open = _matching_open_boxes()
        loops = [
            *find_boundary_loops(0, first_open[0], first_open[1]),
            *find_boundary_loops(1, second_open[0], second_open[1]),
        ]
        seam = pair_matching_loops(
            loops,
            height_mm=HEIGHT_MM,
            tolerance_mm=0.01,
        )[0]
        first_closed = close_open_mesh(*first_open)[:3]
        second_closed = close_open_mesh(*second_open)[:3]

        first_result, second_result, record = add_keyed_joint_for_seam(
            first_closed,
            second_closed,
            seam,
            height_mm=HEIGHT_MM,
            requested_width_mm=8.0,
            requested_height_mm=5.0,
            depth_mm=4.0,
            clearance_mm=0.30,
        )

        _assert_valid_colored_mesh(self, first_result)
        _assert_valid_colored_mesh(self, second_result)
        self.assertEqual(record["shape"], "keyed_rectangle")
        self.assertEqual(set(record["parts"]), {0, 1})
        self.assertNotEqual(record["male_part"], record["female_part"])
        self.assertAlmostEqual(record["clearance_mm"], 0.30)
        self.assertAlmostEqual(record["depth_mm"], 4.0)
        self.assertGreater(record["available_radius_mm"], 2.5)


class PlaneSplitTests(unittest.TestCase):
    def test_plane_split_barycentrically_preserves_a_linear_gradient(self) -> None:
        vertices, faces, _colors = _box_mesh(
            (-0.20, -0.15, -0.25),
            (0.20, 0.15, 0.25),
        )
        gradient = (vertices[:, 0] + 0.20) / 0.40
        colors = np.column_stack(
            (gradient, 1.0 - gradient, np.full(len(vertices), 0.25))
        )

        negative, positive, _record = split_closed_mesh_with_joint(
            (vertices, faces, colors),
            height_mm=HEIGHT_MM,
            axis="Z",
            position_percent=50.0,
            add_joint=False,
            requested_width_mm=8.0,
            requested_height_mm=5.0,
            depth_mm=4.0,
            clearance_mm=0.25,
        )

        for result_vertices, _result_faces, result_colors in (
            negative,
            positive,
        ):
            expected = (result_vertices[:, 0] + 0.20) / 0.40
            np.testing.assert_allclose(
                result_colors[:, 0], expected, atol=1e-7
            )
            np.testing.assert_allclose(
                result_colors[:, 1], 1.0 - expected, atol=1e-7
            )

    def test_xyz_plane_splits_make_two_watertight_jointed_parts(self) -> None:
        source = _box_mesh(
            (-0.20, -0.15, -0.25),
            (0.20, 0.15, 0.25),
        )
        self.assertTrue(mesh_is_watertight(source[0], source[1]))

        for axis in ("X", "Y", "Z"):
            with self.subTest(axis=axis):
                negative, positive, record = split_closed_mesh_with_joint(
                    source,
                    height_mm=HEIGHT_MM,
                    axis=axis,
                    position_percent=50.0,
                    add_joint=True,
                    requested_width_mm=8.0,
                    requested_height_mm=5.0,
                    depth_mm=4.0,
                    clearance_mm=0.25,
                )

                _assert_valid_colored_mesh(self, negative)
                _assert_valid_colored_mesh(self, positive)
                self.assertEqual(record["type"], "plane_split")
                self.assertEqual(record["axis"], axis)
                self.assertEqual(record["position_percent"], 50.0)
                self.assertAlmostEqual(record["plane_mm"], 0.0)
                self.assertEqual(
                    record["result_faces"],
                    [len(negative[1]), len(positive[1])],
                )
                joint = record["joint"]
                self.assertIsNotNone(joint)
                self.assertEqual(joint["shape"], "keyed_rectangle")
                self.assertEqual(
                    {joint["male_side"], joint["female_side"]}, {"A", "B"}
                )
                self.assertAlmostEqual(joint["clearance_mm"], 0.25)

    def test_small_cross_section_reports_an_explicit_joint_error(self) -> None:
        thin_box = _box_mesh(
            (-0.20, -0.01, -0.01),
            (0.20, 0.01, 0.01),
        )

        with self.assertRaises(AssemblyError) as captured:
            split_closed_mesh_with_joint(
                thin_box,
                height_mm=HEIGHT_MM,
                axis="X",
                position_percent=50.0,
                add_joint=True,
                requested_width_mm=8.0,
                requested_height_mm=5.0,
                depth_mm=4.0,
                clearance_mm=0.25,
            )

        message = str(captured.exception)
        self.assertIn("余白", message)
        self.assertIn("mm", message)

    def test_out_of_range_plane_settings_are_rejected_explicitly(self) -> None:
        source = _box_mesh(
            (-0.20, -0.15, -0.25),
            (0.20, 0.15, 0.25),
        )
        for position in (4.99, 95.01):
            with self.subTest(position=position):
                with self.assertRaisesRegex(
                    AssemblyError,
                    "分割位置は5～95%で指定してください",
                ):
                    split_closed_mesh_with_joint(
                        source,
                        height_mm=HEIGHT_MM,
                        axis="Z",
                        position_percent=position,
                        add_joint=False,
                        requested_width_mm=8.0,
                        requested_height_mm=5.0,
                        depth_mm=4.0,
                        clearance_mm=0.25,
                    )

        with self.assertRaisesRegex(
            AssemblyError,
            "分割軸はX・Y・Zから選択してください",
        ):
            split_closed_mesh_with_joint(
                source,
                height_mm=HEIGHT_MM,
                axis="Q",
                position_percent=50.0,
                add_joint=False,
                requested_width_mm=8.0,
                requested_height_mm=5.0,
                depth_mm=4.0,
                clearance_mm=0.25,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
