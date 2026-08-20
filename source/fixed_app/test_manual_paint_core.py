from __future__ import annotations

from pathlib import Path
import sys
import unittest
import warnings

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import MeshLevel  # noqa: E402
from spectrum_mapper.paint import PaintError, PaintSession  # noqa: E402
from spectrum_mapper.paint_tools import (  # noqa: E402
    deterministic_thresholds,
    multi_seed_surface_region,
)


def _level(vertices: tuple[tuple[float, float, float], ...], faces: tuple[tuple[int, int, int], ...]) -> MeshLevel:
    points = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(faces, dtype=np.int32)
    return MeshLevel(
        vertices_unit=points,
        faces=triangles,
        vertex_colors=np.full((len(points), 3), 0.5, dtype=np.float64),
        areas_unit=np.full(len(triangles), 0.5, dtype=np.float64),
        neighbors=None,
    )


def flat_pair() -> MeshLevel:
    return _level(
        ((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
        ((0, 1, 2), (1, 3, 2)),
    )


def folded_pair() -> MeshLevel:
    # Faces share (0, 1). Their normals are +Z and +Y: a 90-degree fold.
    return _level(
        ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((0, 1, 2), (0, 3, 1)),
    )


def thin_folded_strip() -> MeshLevel:
    # A narrow three-face strip.  Face 1 represents the hidden turn around the
    # edge; without a per-frame visibility barrier, traversal from face 0 can
    # walk through it and reach the back face 2.
    return _level(
        (
            (0, 0, 0),
            (1, 0, 0),
            (0, 1, 0),
            (1, 1, 0.05),
            (2, 0, 0.10),
        ),
        ((0, 1, 2), (1, 3, 2), (1, 4, 3)),
    )


class SurfaceTraversalTests(unittest.TestCase):
    def test_crease_threshold_blocks_fold_and_open_threshold_crosses(self) -> None:
        session = PaintSession(folded_pair(), 100.0, np.asarray((0, 0), dtype=np.int8))

        blocked = session.surface_region(0, 200.0, max_angle_degrees=45.0)
        open_region = session.surface_region(0, 200.0, max_angle_degrees=100.0)

        np.testing.assert_array_equal(blocked.faces, (0,))
        np.testing.assert_array_equal(np.sort(open_region.faces), (0, 1))

    def test_active_part_mask_is_a_traversal_barrier(self) -> None:
        session = PaintSession(flat_pair(), 100.0, np.asarray((0, 0), dtype=np.int8))
        session.set_allowed_faces(np.asarray((True, False)))

        region = session.surface_region(
            0, 500.0, protect_sharp_edges=False
        )
        blocked_seed = session.surface_region(
            1, 500.0, protect_sharp_edges=False
        )

        np.testing.assert_array_equal(region.faces, (0,))
        self.assertEqual(len(blocked_seed.faces), 0)

    def test_crease_overlay_exposes_world_segments_and_boundaries(self) -> None:
        session = PaintSession(folded_pair(), 100.0, np.asarray((0, 0), dtype=np.int8))

        internal = session.crease_edges(45.0, include_boundaries=False)
        all_edges = session.crease_edges(45.0, include_boundaries=True)

        self.assertEqual(internal.vertex_pairs.shape, (1, 2))
        self.assertEqual(internal.segments_unit.shape, (1, 2, 3))
        self.assertAlmostEqual(float(internal.angles_degrees[0]), 90.0, places=4)
        self.assertFalse(bool(internal.boundary_mask[0]))
        self.assertEqual(len(all_edges.vertex_pairs), 5)
        self.assertEqual(int(np.count_nonzero(all_edges.boundary_mask)), 4)
        self.assertTrue(np.all(all_edges.face_pairs[all_edges.boundary_mask, 1] == -1))

    def test_multi_seed_region_deduplicates_event_density(self) -> None:
        session = PaintSession(flat_pair(), 100.0, np.asarray((0, 0), dtype=np.int8))
        options = dict(
            radius_mm=200.0,
            neighbors=session.neighbors,
            edge_costs_mm=session.edge_costs_unit,
            distance_scale=session.height_mm,
            allowed_faces=session.allowed_face_mask,
        )
        dense = multi_seed_surface_region((0, 0, 1, 1, 0), **options)
        sparse = multi_seed_surface_region((1, 0), **options)
        np.testing.assert_array_equal(dense.faces, sparse.faces)
        np.testing.assert_allclose(dense.distances_mm, sparse.distances_mm)

    def test_visible_mask_blocks_hidden_bridge_and_back_face(self) -> None:
        session = PaintSession(
            thin_folded_strip(), 100.0, np.asarray((0, 0, 0), dtype=np.int8)
        )
        visible_front = np.asarray((True, False, True))
        persistent_mask_before = session.allowed_face_mask.copy()

        guarded = session.surface_region(
            0,
            1000.0,
            protect_sharp_edges=False,
            visible_face_mask=visible_front,
        )
        legacy = session.surface_region(0, 1000.0, protect_sharp_edges=False)

        # Face 2 is itself marked visible, but it is unreachable because the
        # only surface path crosses hidden face 1.
        np.testing.assert_array_equal(guarded.faces, (0,))
        np.testing.assert_array_equal(np.sort(legacy.faces), (0, 1, 2))
        np.testing.assert_array_equal(
            session.allowed_face_mask, persistent_mask_before
        )

    def test_visible_mask_is_honoured_by_brush_airbrush_smudge_and_smooth(self) -> None:
        level = thin_folded_strip()
        visible_front = np.asarray((True, False, True))

        brush = PaintSession(level, 100.0, np.asarray((0, 0, 0), dtype=np.int8))
        changed = brush.paint_brush(
            0,
            4,
            1000.0,
            protect_sharp_edges=False,
            visible_face_mask=visible_front,
        )
        np.testing.assert_array_equal(changed, (0,))
        np.testing.assert_array_equal(brush.overrides, (4, -1, -1))
        erased = brush.erase_brush(
            0,
            1000.0,
            protect_sharp_edges=False,
            visible_face_mask=visible_front,
        )
        np.testing.assert_array_equal(erased, (0,))

        airbrush = PaintSession(level, 100.0, np.asarray((0, 0, 0), dtype=np.int8))
        enabled = np.zeros(32, dtype=bool)
        enabled[[0, 4]] = True
        sprayed = airbrush.airbrush_stroke(
            (0,),
            4,
            1000.0,
            1.0,
            enabled_states=enabled,
            protect_sharp_edges=False,
            visible_face_mask=visible_front,
        )
        np.testing.assert_array_equal(sprayed, (0,))
        np.testing.assert_array_equal(airbrush.overrides, (4, -1, -1))

        palette = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
        smudge = PaintSession(level, 100.0, np.asarray((0, 1, 1), dtype=np.int8))
        guarded_smudge = smudge.smudge_stroke(
            (0,),
            1000.0,
            1.0,
            palette_rgb=palette,
            enabled_states=(True, True),
            protect_sharp_edges=False,
            visible_face_mask=visible_front,
        )
        self.assertEqual(len(guarded_smudge), 0)
        np.testing.assert_array_equal(smudge.overrides, (-1, -1, -1))

        smooth = PaintSession(level, 100.0, np.asarray((0, 1, 1), dtype=np.int8))
        smoothed = smooth.smooth_boundary(
            0,
            1000.0,
            iterations=2,
            protect_sharp_edges=False,
            visible_face_mask=visible_front,
        )
        self.assertEqual(len(smoothed), 0)
        np.testing.assert_array_equal(smooth.overrides, (-1, -1, -1))

    def test_visible_mask_shape_is_validated(self) -> None:
        session = PaintSession(flat_pair(), 100.0, np.asarray((0, 0), dtype=np.int8))
        with self.assertRaises(PaintError):
            session.paint_brush(0, 1, 10.0, visible_face_mask=(True,))


class EyedropperTests(unittest.TestCase):
    def test_manual_then_adaptive_then_automatic_precedence(self) -> None:
        session = PaintSession(flat_pair(), 100.0, np.asarray((2, 3), dtype=np.int8))

        self.assertEqual(session.sample_painted_state(0), 2)
        self.assertEqual(session.sample_painted_state(0, adaptive_state=7), 7)
        session.overrides[0] = 9
        self.assertEqual(session.sample_painted_state(0, adaptive_state=7), 9)
        with self.assertRaises(PaintError):
            session.sample_painted_state(99)


class AirbrushTests(unittest.TestCase):
    def test_full_stroke_is_deterministic_density_independent_and_one_undo(self) -> None:
        first = PaintSession(flat_pair(), 100.0, np.asarray((0, 0), dtype=np.int8))
        second = PaintSession(flat_pair(), 100.0, np.asarray((0, 0), dtype=np.int8))
        enabled = np.zeros(32, dtype=bool)
        enabled[[0, 5]] = True

        changed_first = first.airbrush_stroke(
            (0, 0, 1, 0, 1), 5, 0.0, 1.0, enabled_states=enabled
        )
        changed_second = second.airbrush_stroke(
            (1, 0), 5, 0.0, 1.0, enabled_states=enabled
        )

        np.testing.assert_array_equal(changed_first, (0, 1))
        np.testing.assert_array_equal(changed_second, changed_first)
        np.testing.assert_array_equal(first.overrides, second.overrides)
        self.assertEqual(first.undo_depth, 1)
        first.undo()
        np.testing.assert_array_equal(first.overrides, (-1, -1))

    def test_fractional_pigment_is_only_retained_inside_one_active_stroke(self) -> None:
        session = PaintSession(
            _level(((0, 0, 0), (1, 0, 0), (0, 1, 0)), ((0, 1, 2),)),
            100.0,
            np.asarray((0,), dtype=np.int8),
        )
        enabled = np.zeros(32, dtype=bool)
        enabled[[0, 4]] = True
        threshold = float(
            deterministic_thresholds(
                np.asarray((0,), dtype=np.int32),
                np.asarray((0,), dtype=np.int8),
                4,
            )[0]
        )
        weak = threshold / 4.1

        # Released/standalone weak strokes are reproducible no-ops; they do not
        # change a later stroke through non-serialised hidden residue.
        for _ in range(20):
            self.assertEqual(
                len(session.airbrush(0, 4, 0.0, weak, enabled_states=enabled)), 0
            )
        fresh = PaintSession(session.level, 100.0, np.asarray((0,), dtype=np.int8))
        expected = fresh.airbrush(0, 4, 0.0, 0.25, enabled_states=enabled)
        actual = session.airbrush(0, 4, 0.0, 0.25, enabled_states=enabled)
        np.testing.assert_array_equal(actual, expected)

        # Multiple dabs in one explicit press/release group may accumulate, and
        # the visible result is still exactly one Undo command.
        grouped = PaintSession(session.level, 100.0, np.asarray((0,), dtype=np.int8))
        grouped.begin_stroke("エアブラシ")
        changed = np.empty(0, dtype=np.int32)
        for _ in range(5):
            changed = grouped.airbrush(0, 4, 0.0, weak, enabled_states=enabled)
            if len(changed):
                break
        committed = grouped.end_stroke()
        np.testing.assert_array_equal(changed, (0,))
        self.assertEqual(committed, 1)
        self.assertEqual(grouped.undo_depth, 1)
        grouped.undo()
        self.assertEqual(int(grouped.overrides[0]), -1)
        self.assertEqual(
            len(grouped.airbrush(0, 4, 0.0, weak, enabled_states=enabled)), 0
        )

    def test_disabled_target_and_invalid_pressure_fail_closed(self) -> None:
        session = PaintSession(flat_pair(), 100.0, np.asarray((0, 0), dtype=np.int8))
        enabled = np.zeros(32, dtype=bool)
        enabled[0] = True
        with self.assertRaises(PaintError):
            session.airbrush(0, 4, 1.0, 1.0, enabled_states=enabled)
        with self.assertRaises(PaintError):
            session.airbrush(0, 0, 1.0, 1.0, pressure=1.2)

    def test_integer_hash_has_no_overflow_warning_and_is_repeatable(self) -> None:
        faces = np.arange(1000, dtype=np.int32)
        states = np.arange(1000, dtype=np.int32) % 32
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            first = deterministic_thresholds(faces, states, 31)
            second = deterministic_thresholds(faces, states, 31)
        self.assertEqual(caught, [])
        np.testing.assert_array_equal(first, second)
        self.assertTrue(np.all((first > 0.0) & (first <= 1.0)))

    def test_five_percent_strength_has_nonzero_discrete_coverage(self) -> None:
        faces = np.arange(20_000, dtype=np.int32)
        states = np.zeros(len(faces), dtype=np.int8)
        thresholds = deterministic_thresholds(faces, states, 7)
        coverage = float(np.count_nonzero(thresholds <= 0.05)) / len(faces)
        self.assertGreater(coverage, 0.035)
        self.assertLess(coverage, 0.065)


class SmudgeTests(unittest.TestCase):
    def test_two_state_boundary_at_mid_strength_visibly_changes(self) -> None:
        session = PaintSession(flat_pair(), 100.0, np.asarray((0, 1), dtype=np.int8))
        palette = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))

        changed = session.smudge(
            0,
            200.0,
            0.45,
            palette_rgb=palette,
            enabled_states=np.asarray((True, True)),
            protect_sharp_edges=False,
        )

        np.testing.assert_array_equal(changed, (1,))
        self.assertEqual(int(session.overrides[1]), 0)
        self.assertEqual(session.undo_depth, 1)
        session.undo()
        np.testing.assert_array_equal(session.overrides, (-1, -1))

    def test_ordered_smudge_stroke_transports_first_dab_colour_forward(self) -> None:
        # A 3-face strip.  Starting on black and moving right carries black to
        # the white end; reversing the path carries white to the black end.
        level = _level(
            (
                (0, 0, 0), (1, 0, 0), (0, 1, 0),
                (1, 1, 0), (2, 0, 0),
            ),
            ((0, 1, 2), (1, 3, 2), (1, 4, 3)),
        )
        palette = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
        left_to_right = PaintSession(
            level, 100.0, np.asarray((0, 1, 1), dtype=np.int8)
        )
        right_to_left = PaintSession(
            level, 100.0, np.asarray((0, 0, 1), dtype=np.int8)
        )

        left_changed = left_to_right.smudge_stroke(
            (0, 1, 2),
            200.0,
            0.45,
            palette_rgb=palette,
            enabled_states=(True, True),
            protect_sharp_edges=False,
        )
        right_changed = right_to_left.smudge_stroke(
            (2, 1, 0),
            200.0,
            0.45,
            palette_rgb=palette,
            enabled_states=(True, True),
            protect_sharp_edges=False,
        )

        self.assertGreaterEqual(len(left_changed), 1)
        self.assertGreaterEqual(len(right_changed), 1)
        self.assertEqual(int(left_to_right.effective_indices()[2]), 0)
        self.assertEqual(int(right_to_left.effective_indices()[0]), 1)
        self.assertEqual(left_to_right.undo_depth, 1)
        self.assertEqual(right_to_left.undo_depth, 1)

    def test_smudge_never_emits_a_disabled_state_and_stroke_groups_undo(self) -> None:
        session = PaintSession(flat_pair(), 100.0, np.asarray((1, 2), dtype=np.int8))
        palette = np.asarray(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        )
        enabled = np.asarray((True, False, True))

        session.begin_stroke("こすってなじませる")
        session.smudge(
            0,
            200.0,
            1.0,
            palette_rgb=palette,
            enabled_states=enabled,
            protect_sharp_edges=False,
        )
        session.smudge(
            1,
            200.0,
            1.0,
            palette_rgb=palette,
            enabled_states=enabled,
            protect_sharp_edges=False,
        )
        changed = session.end_stroke()

        self.assertGreaterEqual(changed, 1)
        self.assertEqual(session.undo_depth, 1)
        active_overrides = session.overrides[session.overrides >= 0]
        self.assertTrue(set(int(value) for value in active_overrides) <= {0, 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
