from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from spectrum_mapper import volume_partition as vp


def _tetra_surface(tag: str) -> vp._MarkedSurface:
    surface = vp._MarkedSurface(
        vertices=np.zeros((1, 3), dtype=np.float64),
        faces=np.empty((0, 3), dtype=np.int32),
        markers=np.empty(0, dtype=np.int32),
    )
    surface.test_tag = tag
    return surface


class CleanTetraComplexTests(unittest.TestCase):
    @staticmethod
    def _single_tetrahedron() -> tuple[np.ndarray, np.ndarray]:
        return (
            np.asarray(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            ),
            np.asarray([[0, 1, 2, 3]], dtype=np.int32),
        )

    def test_removes_one_tiny_boundary_pinch_tetrahedron(self) -> None:
        nodes = np.asarray(
            [
                [0.5118216247002567, 0.9504636963259353, 0.14415961271963373],
                [0.9486494471372439, 0.31183145201048545, 0.42332644897257565],
                [0.8277025938204418, 0.4091991363691613, 0.5495936876730595],
                [0.027559113243068367, 0.7535131086748066, 0.5381433132192782],
                [0.32973171649909216, 0.7884287034284043, 0.303194829291645],
                [0.4534978894806515, 0.13404169724716475, 0.40311298644712923],
            ],
            dtype=np.float64,
        )
        core_elements = np.asarray(
            [
                [4, 5, 0, 1],
                [4, 2, 0, 1],
                [4, 2, 5, 1],
                [4, 2, 0, 3],
                [4, 2, 5, 3],
            ],
            dtype=np.int32,
        )

        # The extra tetrahedron shares face (5, 0, 1) with the core and also
        # reuses boundary vertex 3.  Moving vertex 3 almost onto that face
        # makes the tetrahedron safely removable under the default 1e-5
        # volume limit while its reused edges create a real boundary pinch.
        first, second, third = nodes[[5, 0, 1]]
        plane_normal = np.cross(second - first, third - first)
        plane_normal /= np.linalg.norm(plane_normal)
        original = nodes[3].copy()
        projection = original - plane_normal * np.dot(
            original - first, plane_normal
        )
        nodes[3] = projection + 1e-6 * (original - projection)
        pinch = np.asarray([[5, 0, 1, 3]], dtype=np.int32)
        elements = np.vstack((core_elements, pinch))

        initial_boundary, _owners = vp._oriented_boundary_faces(nodes, elements)
        bad_edges, bad_counts, initial_defect = vp._boundary_edge_defects(
            initial_boundary
        )
        self.assertEqual(len(bad_edges), 2)
        np.testing.assert_array_equal(bad_counts, [4, 4])
        self.assertEqual(initial_defect, 4)

        cleaned_nodes, cleaned_elements, record = vp._clean_tetra_complex(
            nodes, elements
        )

        self.assertEqual(record["initial_nonmanifold_boundary_edges"], 2)
        self.assertEqual(record["removed_degenerate_or_disconnected"], 0)
        self.assertEqual(record["removed_boundary_pinch_tetrahedra"], 1)
        self.assertEqual(record["input_tetrahedra"], 6)
        self.assertEqual(record["output_tetrahedra"], 5)
        self.assertLess(record["removed_volume_fraction"], 1e-5)
        np.testing.assert_allclose(cleaned_nodes, nodes)
        self.assertEqual(
            {tuple(sorted(map(int, element))) for element in cleaned_elements},
            {tuple(sorted(map(int, element))) for element in core_elements},
        )
        final_boundary, _owners = vp._oriented_boundary_faces(
            cleaned_nodes, cleaned_elements
        )
        final_bad_edges, _counts, final_defect = vp._boundary_edge_defects(
            final_boundary
        )
        self.assertEqual(len(final_bad_edges), 0)
        self.assertEqual(final_defect, 0)
        component_count, _labels = vp._tetra_component_labels(cleaned_elements)
        self.assertEqual(component_count, 1)


    def test_rejects_duplicate_tetrahedra_before_they_hide_the_boundary(
        self,
    ) -> None:
        nodes, element = self._single_tetrahedron()
        duplicates = np.vstack((element, element))

        with self.assertRaisesRegex(vp.VolumePartitionError, "重複四面体"):
            vp._clean_tetra_complex(nodes, duplicates)

    def test_rejects_a_closed_tetra_complex_with_no_outer_boundary(self) -> None:
        nodes = np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
                [1.0, 1.0, 1.0],
            ],
            dtype=np.float64,
        )
        # The five tetrahedra are the boundary facets of a 4-simplex.  Every
        # triangular face has incidence two, so this is a closed complex but
        # not a bounded solid volume with an exterior surface.
        elements = np.asarray(
            [
                [1, 2, 3, 4],
                [0, 2, 3, 4],
                [0, 1, 3, 4],
                [0, 1, 2, 4],
                [0, 1, 2, 3],
            ],
            dtype=np.int32,
        )

        with self.assertRaisesRegex(vp.VolumePartitionError, "外側境界面"):
            vp._clean_tetra_complex(nodes, elements)

    def test_rejects_fractional_and_overflowing_indices_before_int32_cast(
        self,
    ) -> None:
        nodes, _element = self._single_tetrahedron()
        invalid = {
            "fractional": np.asarray([[0.5, 1.0, 2.0, 3.0]]),
            "int32 overflow": np.asarray(
                [[2**32, 1, 2, 3]], dtype=np.int64
            ),
        }

        for name, elements in invalid.items():
            with self.subTest(name=name):
                with self.assertRaises(vp.VolumePartitionError):
                    vp._clean_tetra_complex(nodes, elements)

    def test_rejects_nonfinite_removed_volume_fraction(self) -> None:
        nodes, elements = self._single_tetrahedron()

        with self.assertRaises(vp.VolumePartitionError):
            vp._clean_tetra_complex(
                nodes,
                elements,
                maximum_removed_volume_fraction=float("nan"),
            )

    def test_two_step_lookahead_crosses_a_single_removal_defect_plateau(
        self,
    ) -> None:
        nodes = np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
                [1.0, 1.0, 0.2],
                [0.2, 0.3, 1.4],
            ],
            dtype=np.float64,
        )
        elements = np.asarray(
            [
                [0, 1, 2, 3],
                [2, 3, 4, 5],
                [0, 1, 3, 5],
                [1, 2, 4, 5],
                [0, 3, 4, 5],
                [0, 1, 2, 4],
            ],
            dtype=np.int32,
        )
        boundary, _owners = vp._oriented_boundary_faces(nodes, elements)
        _bad, _counts, initial_defect = vp._boundary_edge_defects(boundary)
        self.assertEqual(initial_defect, 6)
        # No first deletion reduces the defect.  The cleaner therefore has
        # to validate and commit a two-deletion step before it can finish.
        for candidate in range(len(elements)):
            trial = np.delete(elements, candidate, axis=0)
            trial_boundary, _owners = vp._oriented_boundary_faces(nodes, trial)
            _bad, _counts, trial_defect = vp._boundary_edge_defects(
                trial_boundary
            )
            self.assertEqual(trial_defect, initial_defect)

        cleaned_nodes, cleaned_elements, record = vp._clean_tetra_complex(
            nodes,
            elements,
            maximum_removed_volume_fraction=0.5,
        )

        self.assertEqual(record["two_step_lookahead_repairs"], 1)
        self.assertEqual(record["removed_boundary_pinch_tetrahedra"], 3)
        final_boundary, _owners = vp._oriented_boundary_faces(
            cleaned_nodes, cleaned_elements
        )
        final_bad, _counts, final_defect = vp._boundary_edge_defects(
            final_boundary
        )
        self.assertEqual(len(final_bad), 0)
        self.assertEqual(final_defect, 0)
        component_count, _labels = vp._tetra_component_labels(cleaned_elements)
        self.assertEqual(component_count, 1)


class TetWildWorkingDirectoryTests(unittest.TestCase):
    @staticmethod
    def _single_tetrahedron() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        nodes, elements = CleanTetraComplexTests._single_tetrahedron()
        faces = elements[:, vp.TET_LOCAL_FACES].reshape(-1, 3)
        return nodes, elements, faces

    def test_temporary_artifact_is_removed_and_cwd_is_restored(self) -> None:
        nodes, elements, faces = self._single_tetrahedron()
        original_cwd = Path.cwd()
        observed: dict[str, Path] = {}

        def fake_tetrahedralize(*_args):
            observed["work"] = Path.cwd()
            observed["artifact"] = Path.cwd() / "__tracked_surface.stl"
            observed["artifact"].write_bytes(b"temporary fTetWild output")
            return nodes, elements

        wrapper = mock.Mock()
        wrapper.tetrahedralize_mesh.side_effect = fake_tetrahedralize

        with mock.patch.object(
            vp, "_load_tetwild_wrapper", return_value=wrapper
        ):
            clean_nodes, clean_elements, record = vp._tetwild_tetrahedralize(
                nodes, faces
            )

        self.assertEqual(Path.cwd(), original_cwd)
        self.assertNotEqual(observed["work"], original_cwd)
        self.assertFalse(observed["artifact"].exists())
        self.assertFalse(observed["work"].exists())
        np.testing.assert_allclose(clean_nodes, nodes)
        np.testing.assert_array_equal(clean_elements, elements)
        self.assertEqual(record["engine"], "fTetWild")

    def test_exception_removes_artifact_and_restores_cwd(self) -> None:
        nodes, _elements, faces = self._single_tetrahedron()
        original_cwd = Path.cwd()
        observed: dict[str, Path] = {}

        def fake_tetrahedralize(*_args):
            observed["work"] = Path.cwd()
            observed["artifact"] = Path.cwd() / "__tracked_surface.stl"
            observed["artifact"].write_bytes(b"temporary fTetWild output")
            raise RuntimeError("forced wrapper failure")

        wrapper = mock.Mock()
        wrapper.tetrahedralize_mesh.side_effect = fake_tetrahedralize

        with mock.patch.object(
            vp, "_load_tetwild_wrapper", return_value=wrapper
        ):
            with self.assertRaisesRegex(
                vp.VolumePartitionError, "forced wrapper failure"
            ):
                vp._tetwild_tetrahedralize(nodes, faces)

        self.assertEqual(Path.cwd(), original_cwd)
        self.assertNotEqual(observed["work"], original_cwd)
        self.assertFalse(observed["artifact"].exists())
        self.assertFalse(observed["work"].exists())


class RecursivePartitionBacktrackingTests(unittest.TestCase):
    def test_failed_first_subtree_is_discarded_before_next_candidate_commits(
        self,
    ) -> None:
        nodes = np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        elements = np.asarray([[0, 1, 2, 3]], dtype=np.int32)
        boundary_faces = elements[:, vp.TET_LOCAL_FACES].reshape(-1, 3)
        boundary_markers = np.asarray([0, 1, 2, 0], dtype=np.int32)
        tetra_volume = float(vp._tetra_volumes(nodes, elements).sum())

        solve_calls: list[tuple[tuple[int, ...], int]] = []
        token_context: dict[int, tuple[tuple[int, ...], int]] = {}

        def fake_solve(
            _nodes,
            _elements,
            _boundary_faces,
            _boundary_markers,
            *,
            leaf_label: int,
            active_labels: set[int],
        ):
            context = (tuple(sorted(active_labels)), int(leaf_label))
            solve_calls.append(context)
            # Candidate 0 at the root reaches this two-part subtree.  Both
            # of its child candidates fail, so the root must discard every
            # trial surface and record created for that branch.
            if active_labels == {1, 2}:
                raise vp.VolumePartitionError("forced failed subtree")
            token = len(token_context) + 1
            token_context[token] = context
            return np.full(len(_nodes), token, dtype=np.float64), {
                "context": context
            }

        def fake_extract(
            _nodes,
            _elements,
            _boundary_faces,
            _boundary_markers,
            scalar,
            *,
            interface_marker: int,
        ):
            context = token_context[int(scalar[0])]
            branch = f"{context[0]}:{context[1]}"
            return (
                _tetra_surface(f"negative:{branch}"),
                _tetra_surface(f"positive:{branch}"),
                {
                    "interface_nonmanifold_edges": 0,
                    "branch": branch,
                    "interface_marker_seen": int(interface_marker),
                },
            )

        def fake_validate(surface, *, part_id: int):
            return surface, {
                "part_id": int(part_id),
                "tag": surface.test_tag,
            }

        def fake_exact(_vertices, _faces, _markers, *, part_count: int):
            self.assertEqual(part_count, 3)
            return (
                nodes,
                elements,
                boundary_faces,
                boundary_markers,
                {"engine": "stub TetGen"},
            )

        sentinel_surface = _tetra_surface("preexisting")
        final_surfaces = {99: sentinel_surface}
        interface_records = [{"sentinel": "interface"}]
        generation_records = [{"sentinel": "generation"}]

        with (
            mock.patch.object(
                vp, "_solve_active_harmonic", side_effect=fake_solve
            ),
            mock.patch.object(
                vp, "_extract_binary_surface", side_effect=fake_extract
            ),
            mock.patch.object(vp, "_validate_surface", side_effect=fake_validate),
            mock.patch.object(
                vp, "_exact_tetrahedralize", side_effect=fake_exact
            ) as exact_mock,
            mock.patch.object(
                vp, "_mesh_volume", return_value=tetra_volume / 2.0
            ),
        ):
            vp._recursive_partition(
                _tetra_surface("root"),
                {0, 1, 2},
                [0, 1, 2],
                part_count=3,
                final_surfaces=final_surfaces,
                interface_records=interface_records,
                generation_records=generation_records,
                progress=None,
                depth=0,
                volume_data=(
                    nodes,
                    elements,
                    boundary_faces,
                    boundary_markers,
                ),
            )

        self.assertEqual(
            solve_calls,
            [
                ((0, 1, 2), 0),
                ((1, 2), 1),
                ((1, 2), 2),
                ((0, 1, 2), 1),
                ((0, 2), 0),
            ],
        )
        self.assertEqual(exact_mock.call_count, 2)
        self.assertIs(final_surfaces[99], sentinel_surface)
        self.assertEqual(set(final_surfaces), {0, 1, 2, 99})
        self.assertEqual(final_surfaces[1].test_tag, "negative:(0, 1, 2):1")
        self.assertEqual(final_surfaces[0].test_tag, "negative:(0, 2):0")
        self.assertEqual(final_surfaces[2].test_tag, "positive:(0, 2):0")
        self.assertNotIn(
            "negative:(0, 1, 2):0",
            [surface.test_tag for surface in final_surfaces.values()],
        )
        self.assertEqual(interface_records[0], {"sentinel": "interface"})
        self.assertEqual(
            [record["leaf_part"] for record in interface_records[1:]],
            [1, 0],
        )
        self.assertEqual(
            [record["branch"] for record in interface_records[1:]],
            ["(0, 1, 2):1", "(0, 2):0"],
        )
        self.assertEqual(generation_records[0], {"sentinel": "generation"})
        self.assertEqual(
            [record["leaf_part"] for record in generation_records[1:]],
            [1, 0],
        )


if __name__ == "__main__":
    unittest.main()
