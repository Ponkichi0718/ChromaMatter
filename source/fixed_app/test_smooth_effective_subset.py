from __future__ import annotations

import unittest

import numpy as np

# Match the release entrypoint's adapter order before importing the smooth
# helper under test.
import spectrum_mapper_hotfix  # noqa: F401
import smooth_paint_hotfix
from spectrum_mapper.models import MeshLevel
from spectrum_mapper.paint import PaintSession


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


class SmoothEffectiveSubsetTests(unittest.TestCase):
    def test_candidate_mapping_keeps_face_state_pairs_exact(self) -> None:
        session = _session()
        # Dict insertion order is also the adaptive processing order.  Use a
        # deliberately non-sorted candidate set to guard the face/state zip.
        candidates = {9: [2], 0: [0, 1], 4: [3], 11: [4], 1: [5]}

        faces, states = smooth_paint_hotfix._effective_states_for_face_mapping(
            session,
            candidates,
        )

        self.assertEqual(faces.tolist(), list(candidates))
        np.testing.assert_array_equal(
            states,
            session.effective_indices()[faces],
        )

    def test_stroke_geometry_reuses_validated_int32_faces_without_upcast(self) -> None:
        session = _session(face_count=64)

        faces, vertices = smooth_paint_hotfix._stroke_geometry_arrays(
            session,
            session.level,
        )

        self.assertIs(faces, session.faces)
        self.assertIs(vertices, session.vertices)
        self.assertEqual(faces.dtype, np.dtype(np.int32))
        self.assertTrue(np.shares_memory(faces, session.faces))
        self.assertTrue(np.shares_memory(vertices, session.vertices))

        # int32 and the old int64 temporary address the same root geometry;
        # retaining int32 changes allocation cost, not projection semantics.
        root = 17
        legacy_faces = np.asarray(session.level.faces, dtype=np.int64)
        np.testing.assert_array_equal(
            vertices[faces[root]],
            np.asarray(session.level.vertices_unit, dtype=np.float64)[
                legacy_faces[root]
            ],
        )


if __name__ == "__main__":
    unittest.main()
