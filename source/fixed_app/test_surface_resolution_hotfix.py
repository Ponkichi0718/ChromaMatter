from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

import surface_resolution_hotfix as hotfix
from spectrum_mapper.generated_surface_color import derive_part_face_provenance


class SurfaceResolutionHotfixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.upper_vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        self.lower_vertices = self.upper_vertices.copy()
        self.lower_vertices[3, 2] = -1.0
        self.upper_faces = np.asarray(
            ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
            dtype=np.int32,
        )
        self.lower_faces = np.asarray(
            ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)),
            dtype=np.int32,
        )
        self.upper_colors = np.tile(
            np.asarray(((0.8, 0.2, 0.1),), dtype=np.float64), (4, 1)
        )
        self.lower_colors = np.tile(
            np.asarray(((0.1, 0.2, 0.8),), dtype=np.float64), (4, 1)
        )
        self.source_meshes = [
            (
                self.upper_vertices,
                np.vstack((self.upper_faces, self.upper_faces[:2])),
                self.upper_colors,
            ),
            (
                self.lower_vertices,
                np.vstack((self.lower_faces, self.lower_faces[:2])),
                self.lower_colors,
            ),
        ]
        self.solid_meshes = [
            (self.upper_vertices, self.upper_faces, self.upper_colors),
            (self.lower_vertices, self.lower_faces, self.lower_colors),
        ]

    @staticmethod
    def _repair_record() -> dict[str, object]:
        # Face 2 touches the edge selected by this symmetric fixture.  It must
        # therefore become two generated children (final face IDs 2 and 3).
        return {
            "method": "recursive_volume_partition",
            "parts": [
                {"part_id": 0, "generated_face_ranges": [[2, 3]]},
                {"part_id": 1, "generated_face_ranges": [[2, 3]]},
            ],
        }

    def _fixed_solidifier(self, record: dict[str, object]):
        outputs = self.solid_meshes

        def original(meshes, seams, height_mm, progress=None):
            del meshes, seams, height_mm, progress
            return outputs, record

        return hotfix._make_fixed_solidifier(
            original, SimpleNamespace(), SimpleNamespace()
        )

    def test_exact_target_keeps_interface_and_propagates_parent_provenance(self) -> None:
        record = self._repair_record()
        refined, updated = self._fixed_solidifier(record)(
            self.source_meshes, None, 1.0
        )

        self.assertEqual([len(mesh[1]) for mesh in refined], [6, 6])
        resolution = updated["surface_resolution"]
        self.assertTrue(resolution["applied"])
        self.assertEqual(resolution["effective_target_faces"], 12)
        self.assertEqual(resolution["after_faces"], 12)
        self.assertTrue(resolution["interfaces_unchanged"])
        self.assertTrue(resolution["interfaces_bitwise_unchanged"])
        self.assertTrue(resolution["face_provenance_propagated"])
        self.assertEqual(
            [part["generated_face_ranges"] for part in updated["parts"]],
            [[[2, 4]], [[2, 4]]],
        )

        origins, diagnostic = derive_part_face_provenance(
            (6, 6), (updated,), topology_changed=False
        )
        self.assertEqual(diagnostic["status"], "fresh")
        self.assertEqual(
            [np.flatnonzero(values).tolist() for values in origins],
            [[2, 3], [2, 3]],
        )

    def test_refinement_failure_rolls_back_to_bit_identical_base(self) -> None:
        record = self._repair_record()
        refined, updated = self._fixed_solidifier(record)(
            self.source_meshes[:1], None, 1.0
        )

        for actual, expected in zip(refined, self.solid_meshes, strict=True):
            for actual_array, expected_array in zip(actual, expected, strict=True):
                np.testing.assert_array_equal(actual_array, expected_array)
        resolution = updated["surface_resolution"]
        self.assertTrue(resolution["rolled_back"])
        self.assertFalse(resolution["face_provenance_propagated"])
        self.assertEqual(
            [part["generated_face_ranges"] for part in updated["parts"]],
            [[[2, 3]], [[2, 3]]],
        )

    def test_prepare_refresh_installs_a_fresh_topology_record(self) -> None:
        level = SimpleNamespace(
            vertices_unit=np.asarray(
                ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                 (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
                dtype=np.float64,
            ),
            faces=np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int32),
            face_provenance=np.asarray((0, 3), dtype=np.uint8),
        )
        resolution = {
            "face_provenance_propagated": True,
            "rolled_back": False,
        }
        prepared = SimpleNamespace(
            final=level,
            assembly={"repair": {"surface_resolution": resolution}},
        )
        wrapped = hotfix._make_provenance_refresh_prepare_geometry(
            lambda *args, **kwargs: prepared
        )

        self.assertIs(wrapped(), prepared)
        self.assertEqual(
            prepared.assembly["generated_surface_provenance"]["status"],
            "fresh",
        )
        self.assertEqual(
            resolution["face_provenance_install"]["reason"],
            "installed_after_surface_refinement",
        )

    def test_scoped_quality_omits_none_limit_for_legacy_callable(self) -> None:
        calls: list[bool] = []

        def legacy_quality(
            vertices,
            faces,
            *,
            check_self_intersections=False,
        ):
            del vertices, faces
            calls.append(bool(check_self_intersections))
            return {"self_intersecting_faces": 0}

        wrapped = hotfix._make_scoped_mesh_quality(legacy_quality)
        result = wrapped(
            self.upper_vertices,
            self.upper_faces,
            check_self_intersections=True,
        )

        self.assertEqual(result, {"self_intersecting_faces": 0})
        self.assertEqual(calls, [True])

    def test_scoped_quality_forwards_explicit_face_id_limit(self) -> None:
        calls: list[tuple[bool, int | None]] = []

        def current_quality(
            vertices,
            faces,
            *,
            check_self_intersections=False,
            self_intersection_face_id_limit=None,
        ):
            del vertices, faces
            calls.append(
                (
                    bool(check_self_intersections),
                    self_intersection_face_id_limit,
                )
            )
            return {"self_intersecting_faces": 0}

        wrapped = hotfix._make_scoped_mesh_quality(current_quality)
        result = wrapped(
            self.upper_vertices,
            self.upper_faces,
            check_self_intersections=True,
            self_intersection_face_id_limit=399,
        )

        self.assertEqual(result, {"self_intersecting_faces": 0})
        self.assertEqual(calls, [(True, 399)])

    def test_install_is_idempotent_for_every_wrapper(self) -> None:
        prepared = SimpleNamespace(final=None, assembly={})

        def base_solid(*args, **kwargs):
            return [], {}

        def base_prepare(*args, **kwargs):
            return prepared

        def base_quality(*args, **kwargs):
            return {"self_intersecting_faces": 0}

        def base_writer(*args, **kwargs):
            return {}

        volume = SimpleNamespace(solidify_complex_partitions=base_solid)
        engine = SimpleNamespace(
            prepare_geometry=base_prepare,
            mesh_quality=base_quality,
            write_3mf_atomic=base_writer,
        )
        workflow = SimpleNamespace(
            mesh_quality=base_quality,
            write_3mf_atomic=base_writer,
        )

        first = hotfix.apply_surface_resolution_hotfix(
            volume, engine, SimpleNamespace(), workflow
        )
        identities = (
            id(volume.solidify_complex_partitions),
            id(engine.prepare_geometry),
            id(engine.mesh_quality),
            id(engine.write_3mf_atomic),
        )
        second = hotfix.apply_surface_resolution_hotfix(
            volume, engine, SimpleNamespace(), workflow
        )

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(
            identities,
            (
                id(volume.solidify_complex_partitions),
                id(engine.prepare_geometry),
                id(engine.mesh_quality),
                id(engine.write_3mf_atomic),
            ),
        )
        self.assertTrue(
            first["provenance_prepare_scope"]["engine_changed"]
        )
        self.assertFalse(
            second["provenance_prepare_scope"]["engine_changed"]
        )


if __name__ == "__main__":
    unittest.main()
