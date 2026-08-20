from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.engine import face_neighbors_partial, triangle_areas
from spectrum_mapper.joint_projection import (
    JointProjectionError,
    canvas_point_on_face,
    project_face_to_render,
)
from spectrum_mapper.models import MeshLevel
from spectrum_mapper.renderer import CameraState


def _level() -> MeshLevel:
    vertices = np.asarray(
        [
            [-0.30, 0.0, -0.25],
            [0.30, 0.0, -0.25],
            [0.00, 0.0, 0.35],
            [-0.05, 0.30, 0.00],
        ],
        dtype=np.float64,
    )
    faces = np.asarray([[0, 1, 2], [0, 3, 1]], dtype=np.int32)
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=np.full((len(vertices), 3), 0.5, dtype=np.float64),
        areas_unit=triangle_areas(vertices, faces),
        neighbors=face_neighbors_partial(faces, len(vertices)),
        face_part_ids=np.zeros(len(faces), dtype=np.int16),
        part_names=("part",),
        part_keys=("0:part",),
    )


class JointProjectionTests(unittest.TestCase):
    def test_projected_centroid_round_trips_to_model_surface(self) -> None:
        level = _level()
        camera = CameraState(yaw_degrees=18.0, pitch_degrees=-9.0, zoom=1.3)
        size = (760, 760)
        projected = project_face_to_render(
            level, 0, camera=camera, render_size=size
        )
        screen_centroid = projected.mean(axis=0)
        mapping = (40, 25, 760, 760, 760, 760)
        actual = canvas_point_on_face(
            level,
            0,
            (screen_centroid[0] + 40, screen_centroid[1] + 25),
            mapping,
            camera=camera,
        )
        expected = level.vertices_unit[level.faces[0]].mean(axis=0)
        np.testing.assert_allclose(actual, expected, atol=1e-7)

    def test_resized_canvas_mapping_keeps_same_surface_point(self) -> None:
        level = _level()
        camera = CameraState(yaw_degrees=-25.0, pitch_degrees=12.0, zoom=0.9)
        projected = project_face_to_render(
            level, 0, camera=camera, render_size=(760, 760)
        )
        weights = np.asarray((0.2, 0.3, 0.5))
        render_point = weights @ projected
        mapping = (300, 80, 380, 380, 760, 760)
        canvas_point = (
            mapping[0] + render_point[0] * mapping[2] / mapping[4],
            mapping[1] + render_point[1] * mapping[3] / mapping[5],
        )
        actual = canvas_point_on_face(
            level, 0, canvas_point, mapping, camera=camera
        )
        expected = weights @ level.vertices_unit[level.faces[0]]
        np.testing.assert_allclose(actual, expected, atol=1e-7)

    def test_canvas_point_outside_mapping_is_rejected(self) -> None:
        with self.assertRaises(JointProjectionError):
            canvas_point_on_face(
                _level(),
                0,
                (0, 0),
                (10, 10, 100, 100, 760, 760),
                camera=CameraState(),
            )


if __name__ == "__main__":
    unittest.main()
