from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import MeshLevel  # noqa: E402
from spectrum_mapper.paint import PaintError, PaintSession  # noqa: E402


def _level() -> MeshLevel:
    vertices = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ),
        dtype=np.float64,
    )
    faces = np.asarray(((0, 1, 2), (1, 3, 2)), dtype=np.int32)
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=np.full((4, 3), 0.5, dtype=np.float64),
        areas_unit=np.full(2, 0.5, dtype=np.float64),
        neighbors=None,
    )


class PlannedStateCommitTests(unittest.TestCase):
    def test_batch_is_one_undo_command_and_drops_effective_noops(self) -> None:
        session = PaintSession(
            _level(), 100.0, np.asarray((1, 2), dtype=np.int8)
        )

        changed = session.apply_planned_states(
            np.asarray((0, 1), dtype=np.int32),
            np.asarray((1, 7), dtype=np.int8),
            "一括修正",
        )

        np.testing.assert_array_equal(changed, (1,))
        np.testing.assert_array_equal(session.overrides, (-1, 7))
        self.assertEqual(session.undo_depth, 1)
        command = session.undo()
        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.label, "一括修正")
        np.testing.assert_array_equal(session.overrides, (-1, -1))

    def test_manual_paint_and_disallowed_faces_are_protected_by_default(self) -> None:
        session = PaintSession(
            _level(), 100.0, np.asarray((1, 2), dtype=np.int8)
        )
        session.overrides[0] = 5
        session.set_allowed_faces(np.asarray((True, False)))

        changed = session.apply_planned_states(
            np.asarray((0, 1), dtype=np.int32),
            np.asarray((8, 9), dtype=np.int8),
            "一括色変更",
        )

        self.assertEqual(len(changed), 0)
        np.testing.assert_array_equal(session.overrides, (5, -1))
        self.assertEqual(session.undo_depth, 0)

    def test_manual_protection_can_be_explicitly_disabled(self) -> None:
        session = PaintSession(
            _level(), 100.0, np.asarray((1, 2), dtype=np.int8)
        )
        session.overrides[0] = 5

        changed = session.apply_planned_states(
            np.asarray((0,), dtype=np.int32),
            np.asarray((8,), dtype=np.int8),
            "一括色変更",
            protect_manual=False,
        )

        np.testing.assert_array_equal(changed, (0,))
        self.assertEqual(int(session.overrides[0]), 8)

    def test_invalid_or_ambiguous_plan_fails_closed(self) -> None:
        session = PaintSession(
            _level(), 100.0, np.asarray((1, 2), dtype=np.int8)
        )
        with self.assertRaises(PaintError):
            session.apply_planned_states(
                np.asarray((0, 0), dtype=np.int32),
                np.asarray((3, 4), dtype=np.int8),
                "重複",
            )
        with self.assertRaises(PaintError):
            session.apply_planned_states(
                np.asarray((0,), dtype=np.int32),
                np.asarray((99,), dtype=np.int16),
                "範囲外",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
