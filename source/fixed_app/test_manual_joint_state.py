from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.engine import face_neighbors_partial, triangle_areas
from spectrum_mapper.manual_joint_state import (
    ManualJointStateError,
    remap_manual_overrides,
)
from spectrum_mapper.models import MeshLevel


def _level(vertices, faces, part_ids, keys=("a", "b")) -> MeshLevel:
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int32)
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=np.full((len(vertices), 3), 0.5),
        areas_unit=triangle_areas(vertices, faces),
        neighbors=face_neighbors_partial(faces, len(vertices)),
        face_part_ids=np.asarray(part_ids, dtype=np.int16),
        part_names=tuple(key.upper() for key in keys),
        part_keys=tuple(keys),
    )


class ManualJointStateTests(unittest.TestCase):
    def test_sparse_override_is_not_spread_to_distant_new_faces(self) -> None:
        before = _level(
            [
                [0, 0, 0], [1, 0, 0], [0, 1, 0],
                [10, 0, 0], [11, 0, 0], [10, 1, 0],
                [20, 0, 0], [21, 0, 0], [20, 1, 0],
            ],
            [[0, 1, 2], [3, 4, 5], [6, 7, 8]],
            [0, 0, 1],
        )
        after = _level(
            [
                [0, 0, 0], [1, 0, 0], [0, 1, 0],
                [9.9, 0, 0], [10.9, 0, 0], [9.9, 1, 0],
                [20, 0, 0], [21, 0, 0], [20, 1, 0],
            ],
            [[0, 1, 2], [3, 4, 5], [6, 7, 8]],
            [0, 0, 1],
        )
        result = remap_manual_overrides(
            before, after, np.asarray([7, -1, 3], dtype=np.int8)
        )
        self.assertEqual(result.tolist(), [7, -1, 3])

    def test_part_key_change_is_rejected(self) -> None:
        before = _level(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            [[0, 1, 2]],
            [0],
            keys=("a",),
        )
        after = _level(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            [[0, 1, 2]],
            [0],
            keys=("changed",),
        )
        with self.assertRaises(ManualJointStateError):
            remap_manual_overrides(before, after, np.asarray([-1], dtype=np.int8))


if __name__ == "__main__":
    unittest.main()
