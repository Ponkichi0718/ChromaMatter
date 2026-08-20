from __future__ import annotations

import unittest

import numpy as np

from spectrum_mapper.models import MeshLevel
from spectrum_mapper.paint import PaintError, PaintSession


def _session(face_count: int = 12) -> PaintSession:
    vertices = np.column_stack(
        (
            np.arange(face_count + 2, dtype=np.float64),
            np.zeros(face_count + 2, dtype=np.float64),
            np.arange(face_count + 2, dtype=np.float64) % 2,
        )
    )
    faces = np.column_stack(
        (
            np.arange(face_count, dtype=np.int32),
            np.arange(1, face_count + 1, dtype=np.int32),
            np.arange(2, face_count + 2, dtype=np.int32),
        )
    )
    level = MeshLevel(
        vertices,
        faces,
        np.full((len(vertices), 3), 0.5, dtype=np.float64),
        np.ones(face_count, dtype=np.float64),
        None,
    )
    automatic = (np.arange(face_count, dtype=np.int8) * 3) % 16
    overrides = np.full(face_count, -1, dtype=np.int8)
    overrides[[1, 4, 9]] = (7, 2, 15)
    return PaintSession(level, 100.0, automatic, overrides=overrides)


class EffectiveIndicesSubsetTests(unittest.TestCase):
    def test_matches_full_effective_states_and_preserves_order(self) -> None:
        session = _session()
        requested = np.asarray((9, 0, 4, 4, 11, 1), dtype=np.int64)

        selected = session.effective_indices_for_faces(requested)

        np.testing.assert_array_equal(selected, session.effective_indices()[requested])
        self.assertEqual(selected.dtype, np.int8)

    def test_empty_selection_is_supported(self) -> None:
        selected = _session().effective_indices_for_faces(
            np.empty(0, dtype=np.int32)
        )
        self.assertEqual(selected.shape, (0,))
        self.assertEqual(selected.dtype, np.int8)

    def test_rejects_non_integer_or_out_of_range_faces(self) -> None:
        session = _session()
        with self.assertRaises(PaintError):
            session.effective_indices_for_faces(np.asarray((1.0, 2.0)))
        with self.assertRaises(PaintError):
            session.effective_indices_for_faces(np.asarray((-1,), dtype=np.int32))
        with self.assertRaises(PaintError):
            session.effective_indices_for_faces(
                np.asarray((len(session.faces),), dtype=np.int32)
            )

if __name__ == "__main__":
    unittest.main()
