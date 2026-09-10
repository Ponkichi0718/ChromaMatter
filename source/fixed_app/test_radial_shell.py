from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np
import trimesh


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import MeshLevel
from spectrum_mapper.radial_shell import (
    DEFAULT_SKIN_THICKNESS_MM,
    RadialShellError,
    analyze_radial_surface_assignments,
    build_radial_shell,
    build_radial_shell_from_level,
)


STATE = 5
PARTNER = 3
BLACK = 1


def _box() -> tuple[np.ndarray, np.ndarray]:
    mesh = trimesh.creation.box(extents=(10.0, 8.0, 6.0))
    return (
        np.asarray(mesh.vertices, dtype=np.float64),
        np.asarray(mesh.faces, dtype=np.int32),
    )


def _coordinate_keys(
    vertices: np.ndarray, faces: np.ndarray
) -> set[tuple[tuple[float, float, float], ...]]:
    return {
        tuple(sorted(tuple(map(float, vertices[index])) for index in face))
        for face in faces
    }


def _volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    triangles = vertices[faces]
    return float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )


class RadialShellTests(unittest.TestCase):
    def _build(self, vertices: np.ndarray, faces: np.ndarray, **changes):
        parameters = {
            "face_part_ids": np.zeros(len(faces), dtype=np.int16),
            "face_state_ids": np.full(len(faces), STATE, dtype=np.int16),
            "eligible_state_partners": {STATE: PARTNER},
            "black_extruder": BLACK,
        }
        parameters.update(changes)
        return build_radial_shell(vertices, faces, **parameters)

    def test_box_builds_exact_touch_physical_shell_and_core(self) -> None:
        vertices, faces = _box()
        vertices_before = vertices.copy()
        faces_before = faces.copy()

        result = self._build(vertices, faces)

        self.assertTrue(np.array_equal(vertices, vertices_before))
        self.assertTrue(np.array_equal(faces, faces_before))
        self.assertEqual(
            [part.role for part in result.parts],
            ["pure_black_core", "partner_outer_shell"],
        )
        self.assertEqual([part.extruder for part in result.parts], [1, 3])
        self.assertTrue(all(part.solid_infill for part in result.parts))
        self.assertTrue(result.metadata["closed_physical_volumes"])
        self.assertNotIn("solid_infill_percent", result.metadata)
        self.assertTrue(
            all(part.metadata["closed_physical_volume"] for part in result.parts)
        )
        self.assertTrue(
            all(
                "sparse_infill_density_percent" not in part.metadata
                for part in result.parts
            )
        )
        self.assertEqual(result.skin_thickness_mm, 0.15)
        self.assertAlmostEqual(
            result.source_volume_mm3, result.output_volume_mm3, places=9
        )
        self.assertEqual(
            result.metadata["ratio_definitions"], 0
        )
        self.assertEqual(result.metadata["cycle_definitions"], 0)
        self.assertEqual(result.metadata["painted_triangles"], 0)
        interface = result.interfaces[0]
        self.assertTrue(interface["exact_coordinate_triangles"])
        self.assertTrue(interface["opposite_winding"])
        self.assertEqual(interface["gap_mm"], 0.0)
        self.assertEqual(interface["positive_overlap_mm3"], 0.0)

        core, shell = result.parts
        self.assertTrue(
            trimesh.Trimesh(
                vertices=core.vertices_mm, faces=core.faces, process=False
            ).is_volume
        )
        self.assertTrue(
            trimesh.Trimesh(
                vertices=shell.vertices_mm, faces=shell.faces, process=False
            ).is_volume
        )
        self.assertAlmostEqual(
            _volume(core.vertices_mm, core.faces)
            + _volume(shell.vertices_mm, shell.faces),
            480.0,
            places=9,
        )

    def test_source_exterior_is_preserved_exactly(self) -> None:
        vertices, faces = _box()
        result = self._build(vertices, faces)
        shell = result.parts[1]
        source_keys = _coordinate_keys(vertices, faces)
        shell_keys = _coordinate_keys(shell.vertices_mm, shell.faces)

        self.assertTrue(source_keys.issubset(shell_keys))
        self.assertEqual(len(source_keys), len(faces))
        self.assertTrue(
            result.metadata["source_exterior_preserved_exactly"]
        )

    def test_rounded_closed_mesh_builds(self) -> None:
        rounded = trimesh.creation.icosphere(subdivisions=1, radius=5.0)
        result = self._build(
            np.asarray(rounded.vertices, dtype=np.float64),
            np.asarray(rounded.faces, dtype=np.int32),
        )

        self.assertEqual(len(result.parts), 2)
        self.assertAlmostEqual(
            result.source_volume_mm3, result.output_volume_mm3, places=8
        )
        self.assertLessEqual(
            result.interfaces[0]["sampled_depth_max_mm"], 0.18
        )

    def test_stage_b_analysis_retains_multiple_state_assignments(self) -> None:
        vertices, faces = _box()
        states = np.full(len(faces), 5, dtype=np.int16)
        states[len(faces) // 2 :] = 6
        analysis = analyze_radial_surface_assignments(
            vertices,
            faces,
            states,
            {5: 3, 6: 2},
        )

        self.assertEqual(
            [(item.state_id, item.partner_extruder) for item in analysis.assignments],
            [(5, 3), (6, 2)],
        )
        self.assertAlmostEqual(analysis.eligible_area_fraction, 1.0)
        with self.assertRaises(RadialShellError) as caught:
            self._build(
                vertices,
                faces,
                face_state_ids=states,
                eligible_state_partners={5: 3, 6: 2},
            )
        self.assertEqual(
            caught.exception.code,
            "multiple_eligible_states_not_supported",
        )

    def test_partial_surface_fails_closed(self) -> None:
        vertices, faces = _box()
        states = np.full(len(faces), STATE, dtype=np.int16)
        states[0] = 2

        with self.assertRaises(RadialShellError) as caught:
            self._build(vertices, faces, face_state_ids=states)

        self.assertEqual(caught.exception.code, "eligible_coverage_too_low")

    def test_open_mesh_fails_closed(self) -> None:
        vertices, faces = _box()

        with self.assertRaises(RadialShellError) as caught:
            self._build(vertices, faces[:-2])

        self.assertEqual(
            caught.exception.code, "closed_positive_single_body_required"
        )

    def test_multipart_fails_closed(self) -> None:
        vertices, faces = _box()
        parts = np.zeros(len(faces), dtype=np.int16)
        parts[-1] = 1

        with self.assertRaises(RadialShellError) as caught:
            self._build(vertices, faces, face_part_ids=parts)

        self.assertEqual(caught.exception.code, "single_part_required")

    def test_generated_closure_surface_fails_closed(self) -> None:
        vertices, faces = _box()
        provenance = np.zeros(len(faces), dtype=np.uint8)
        provenance[-1] = 1

        with self.assertRaises(RadialShellError) as caught:
            self._build(
                vertices,
                faces,
                face_provenance=provenance,
            )

        self.assertEqual(
            caught.exception.code, "generated_surface_not_supported"
        )

    def test_thickness_consuming_core_fails_closed(self) -> None:
        vertices, faces = _box()

        with self.assertRaises(RadialShellError) as caught:
            self._build(vertices, faces, skin_thickness_mm=3.1)

        self.assertEqual(caught.exception.code, "skin_consumes_core")

    def test_default_thickness_and_level_scaling(self) -> None:
        vertices, faces = _box()
        vertices_unit = vertices / 6.0
        level = MeshLevel(
            vertices_unit=vertices_unit,
            faces=faces,
            vertex_colors=np.zeros((len(vertices), 3), dtype=np.float64),
            areas_unit=np.zeros(len(faces), dtype=np.float64),
            neighbors=None,
            face_part_ids=np.zeros(len(faces), dtype=np.int16),
            part_names=("box",),
            part_keys=("box",),
        )

        result = build_radial_shell_from_level(
            level,
            height_mm=6.0,
            face_state_ids=np.full(len(faces), STATE, dtype=np.int16),
            eligible_state_partners={STATE: PARTNER},
            black_extruder=BLACK,
        )

        self.assertEqual(
            result.skin_thickness_mm, DEFAULT_SKIN_THICKNESS_MM
        )
        self.assertAlmostEqual(result.source_volume_mm3, 480.0)

    def test_result_arrays_are_read_only(self) -> None:
        vertices, faces = _box()
        result = self._build(vertices, faces)

        self.assertFalse(result.parts[0].vertices_mm.flags.writeable)
        self.assertFalse(result.parts[0].faces.flags.writeable)
        with self.assertRaises(ValueError):
            result.parts[0].vertices_mm[0, 0] = 42.0

    def test_bad_physical_tools_fail_closed(self) -> None:
        vertices, faces = _box()
        with self.assertRaises(RadialShellError) as caught:
            self._build(vertices, faces, black_extruder=5)
        self.assertEqual(caught.exception.code, "invalid_black_extruder")

        with self.assertRaises(RadialShellError) as caught:
            self._build(
                vertices,
                faces,
                black_extruder=3,
                eligible_state_partners={STATE: 3},
            )
        self.assertEqual(caught.exception.code, "partner_equals_black")


if __name__ == "__main__":
    unittest.main()
