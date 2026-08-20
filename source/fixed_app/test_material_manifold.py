from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.material_manifold import (
    MaterialManifoldError,
    _group_canonical_index_faces,
    manifoldize_labeled_tetrahedra,
)


# Deterministic reduced star from a Delaunay complex.  F1 has two distinct
# abstract edge objects with coincident endpoints.  One affected coordinate
# face is an F1/F2 interface; the old per-material subdivision split only its
# F1 occurrence and left unmatched internal triangles.  The reduced fixture
# is intentionally small enough to run in every unit-test pass.
_PARALLEL_EDGE_NODES = np.asarray(
    (
        (0.1320865903122387, 1.017759222456577, 0.7489803271159333),
        (-0.39866432329710383, -1.2381691388360434, 0.12178762345167685),
        (0.777006587394325, 0.813855751798287, 0.29533780458552417),
        (0.27094793967972364, 0.10505880672792227, 1.7441011736621255),
        (1.080995131352679, 0.0009617442553492209, -0.5532791329289272),
        (1.8422510964245986, 1.1380210454551176, -0.1551274098382652),
        (-0.5573292683715843, -0.20761446344795234, -0.8168955621916346),
        (-1.0831150854194438, 1.2212912116794543, -0.4928998664206916),
        (0.4620610511031984, -0.1731074458879487, -1.1041584114493725),
        (0.13747307776454668, 1.3046410151573953, -1.7614209997017378),
        (0.6642351095835891, 0.848328549441543, -0.00368182029426228),
        (-0.7402272380397719, -1.0615238780294096, 0.2572953905757468),
    ),
    dtype=np.float64,
)
_PARALLEL_EDGE_TETS = np.asarray(
    (
        (6, 10, 4, 1),
        (6, 10, 4, 8),
        (6, 10, 11, 0),
        (6, 10, 7, 0),
        (6, 10, 8, 9),
        (6, 10, 7, 9),
        (2, 4, 3, 1),
        (2, 10, 4, 1),
        (2, 3, 0, 1),
        (2, 11, 0, 1),
        (2, 10, 11, 0),
        (5, 2, 10, 0),
        (5, 2, 10, 4),
    ),
    dtype=np.int32,
)
_PARALLEL_EDGE_MATERIALS = np.asarray(
    (1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2), dtype=np.int8
)


def _coordinate_key(points: np.ndarray) -> bytes:
    values = np.asarray(points, dtype="<f8").copy()
    values[values == 0.0] = 0.0
    order = np.lexsort((values[:, 2], values[:, 1], values[:, 0]))
    return values[order].tobytes()


class SharedMaterialManifoldTests(unittest.TestCase):
    def test_parallel_split_propagates_to_internal_counterpart(self) -> None:
        result = manifoldize_labeled_tetrahedra(
            _PARALLEL_EDGE_NODES,
            _PARALLEL_EDGE_TETS,
            _PARALLEL_EDGE_MATERIALS,
        )

        shared = result.metadata["shared_subdivision"]
        self.assertEqual(shared["initial_parallel_abstract_edge_objects"], 2)
        self.assertEqual(shared["shared_split_abstract_edge_objects"], 3)
        self.assertEqual(shared["propagated_counterpart_edge_objects"], 1)
        self.assertTrue(
            shared["coordinate_face_counterparts_receive_identical_partition"]
        )
        accounting = result.metadata["coordinate_triangle_accounting"]
        self.assertEqual(accounting["internal_exact_pairs"], 8)
        self.assertEqual(accounting["multiplicity_gt2"], 0)
        self.assertEqual(accounting["counterpart_partition_mismatches"], 0)
        self.assertEqual(accounting["internal_opposite_winding_failures"], 0)
        self.assertTrue(accounting["external_surface_coverage_exact"])
        self.assertEqual(
            accounting["output_registry"],
            "source_face_group_plus_uint9_subdivision",
        )
        self.assertEqual(accounting["float_bytes_dictionary_entries"], 0)
        self.assertEqual(shared["source_face_registry"], "packed_uint64")
        self.assertAlmostEqual(
            result.source_volume_mm3, result.output_volume_mm3, places=12
        )
        self.assertTrue(result.metadata["all_closed_oriented_2_manifold"])

        occurrences: dict[bytes, list[tuple[int, np.ndarray]]] = {}
        for part in result.parts:
            for face in part.faces:
                points = part.vertices_mm[face]
                occurrences.setdefault(_coordinate_key(points), []).append(
                    (part.extruder, points)
                )
        self.assertLessEqual(max(map(len, occurrences.values())), 2)
        internal = [values for values in occurrences.values() if len(values) == 2]
        self.assertEqual(len(internal), 8)
        for first, second in internal:
            self.assertNotEqual(first[0], second[0])
            first_normal = np.cross(
                first[1][1] - first[1][0], first[1][2] - first[1][0]
            )
            second_normal = np.cross(
                second[1][1] - second[1][0], second[1][2] - second[1][0]
            )
            self.assertLess(float(np.dot(first_normal, second_normal)), 0.0)

    def test_simple_two_material_interface_remains_backward_compatible(self) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (1.0, 1.0, 1.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(((0, 1, 2, 3), (1, 2, 3, 4)), dtype=np.int32)
        result = manifoldize_labeled_tetrahedra(
            nodes, tets, np.asarray((1, 3), dtype=np.int8)
        )

        self.assertEqual([part.extruder for part in result.parts], [1, 3])
        self.assertEqual([len(part.faces) for part in result.parts], [4, 4])
        self.assertEqual(result.interfaces[0]["faces"], 1)
        self.assertEqual(
            result.metadata["coordinate_triangle_accounting"][
                "internal_exact_pairs"
            ],
            1,
        )

    def test_coordinate_face_multiplicity_over_two_fails_closed(self) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, -1.0),
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 2.0),
            ),
            dtype=np.float64,
        )
        # Three separately indexed tetrahedra expose the same coordinate face.
        # Indexed cell-face incidence is valid, so the global coordinate-face
        # registry itself must reject geometric multiplicity three.
        tets = np.asarray(
            ((0, 1, 2, 3), (4, 6, 5, 7), (8, 9, 10, 11)), dtype=np.int32
        )
        with self.assertRaises(MaterialManifoldError) as caught:
            manifoldize_labeled_tetrahedra(
                nodes, tets, np.asarray((1, 2, 3), dtype=np.int8)
            )
        self.assertEqual(
            caught.exception.code,
            "coordinate_face_multiplicity_exceeds_two",
        )

    def test_two_separately_indexed_coincident_faces_fail_closed(self) -> None:
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, -1.0),
            ),
            dtype=np.float64,
        )
        tets = np.asarray(((0, 1, 2, 3), (4, 6, 5, 7)), dtype=np.int32)
        with self.assertRaises(MaterialManifoldError) as caught:
            manifoldize_labeled_tetrahedra(
                nodes, tets, np.asarray((1, 2), dtype=np.int8)
            )
        self.assertEqual(
            caught.exception.code,
            "coincident_coordinate_face_not_shared_cell_face",
        )

    def test_large_node_ids_use_structured_exact_face_key_fallback(self) -> None:
        faces = np.asarray(
            (
                (0, 2**22, 2**22 + 1),
                (2**22 + 1, 0, 2**22),
                (1, 2**22, 2**22 + 1),
            ),
            dtype=np.int32,
        )
        order, starts, counts, mode, bits = _group_canonical_index_faces(
            np.sort(faces, axis=1)
        )
        self.assertEqual(mode, "structured_int32")
        self.assertGreater(3 * bits, 64)
        self.assertEqual(sorted(map(int, counts)), [1, 2])
        self.assertEqual(len(order), 3)
        self.assertEqual(len(starts), 2)

    def test_tiny_positive_conforming_cell_is_not_discarded(self) -> None:
        scale = 1e-7
        nodes = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (10.0, 0.0, 0.0),
                (10.0 + scale, 0.0, 0.0),
                (10.0, scale, 0.0),
                (10.0, 0.0, scale),
            ),
            dtype=np.float64,
        )
        result = manifoldize_labeled_tetrahedra(
            nodes,
            np.asarray(((0, 1, 2, 3), (4, 5, 6, 7)), dtype=np.int32),
            np.asarray((1, 1), dtype=np.int8),
        )
        self.assertGreater(result.source_volume_mm3, 0.0)
        self.assertEqual(result.parts[0].metadata["cell_count"], 2)
        self.assertAlmostEqual(result.source_volume_mm3, 1.0 / 6.0, places=15)
        self.assertAlmostEqual(result.source_volume_mm3, result.output_volume_mm3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
