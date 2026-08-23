from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import engine, workflow
from spectrum_mapper.generated_surface_color import (
    FACE_PROVENANCE_PLANAR_CAP,
    make_face_provenance_record,
)
from spectrum_mapper.models import (
    AppSettings,
    GeometrySettings,
    ObjAsset,
    PaletteSettings,
    ToneSettings,
)
from spectrum_mapper.multipart_topology import (
    MultipartTopologyError,
    normalize_multipart_part,
)


_TETRA_FACES = np.asarray(
    ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
    dtype=np.int32,
)


def _oriented_tetra_faces(vertices: np.ndarray) -> np.ndarray:
    faces = _TETRA_FACES.copy()
    triangles = np.asarray(vertices, dtype=np.float64)[faces]
    volume = float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )
    if volume < 0.0:
        faces[:, [1, 2]] = faces[:, [2, 1]]
    return faces


def _colors(count: int) -> np.ndarray:
    values = np.linspace(0.1, 0.9, count, dtype=np.float64)
    return np.column_stack((values, values[::-1], np.full(count, 0.5)))


class MultipartTopologyNormalizerTests(unittest.TestCase):
    def test_cleanup_triangle_ancestry_accepts_exact_subset_and_winding(self) -> None:
        source_vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 0.0),
            ),
            dtype=np.float64,
        )
        source_faces = np.asarray(
            ((0, 1, 2), (4, 3, 1)), dtype=np.int32
        )
        candidate_vertices = source_vertices[[3, 1, 4]]
        candidate_faces = np.asarray(((2, 1, 0),), dtype=np.int32)

        self.assertTrue(
            engine._triangle_coordinate_multiset_is_subset(
                source_vertices,
                source_faces,
                candidate_vertices,
                candidate_faces,
            )
        )

    def test_cleanup_triangle_ancestry_rejects_new_or_duplicated_triangle(
        self,
    ) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        source_faces = np.asarray(((0, 1, 2),), dtype=np.int32)
        with_new_triangle = np.asarray(((0, 1, 3),), dtype=np.int32)
        with_duplicate = np.asarray(((0, 1, 2), (2, 1, 0)), dtype=np.int32)

        self.assertFalse(
            engine._triangle_coordinate_multiset_is_subset(
                vertices,
                source_faces,
                vertices,
                with_new_triangle,
            )
        )
        self.assertFalse(
            engine._triangle_coordinate_multiset_is_subset(
                vertices,
                source_faces,
                vertices,
                with_duplicate,
            )
        )

    def test_removes_only_exact_coordinate_collapsed_face(self) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 0.0),
            ),
            dtype=np.float64,
        )
        faces = np.vstack((_TETRA_FACES, np.asarray(((0, 4, 1),))))

        result = normalize_multipart_part(vertices, faces, _colors(len(vertices)))

        np.testing.assert_array_equal(
            result.output_face_source, np.arange(4, dtype=np.int32)
        )
        self.assertEqual(result.metadata["removed_collapsed_faces"], 1)
        self.assertEqual(result.metadata["noncollapsed_degenerate_faces"], 0)
        self.assertTrue(result.metadata["face_order_preserved"])
        self.assertTrue(result.metadata["geometry_coordinates_preserved"])
        self.assertEqual(len(result.faces), 4)
        self.assertTrue(result.metadata["after"]["watertight"])
        np.testing.assert_array_equal(
            result.vertices[result.faces], vertices[faces[:4]]
        )

    def test_collinear_distinct_coordinates_fail_closed(self) -> None:
        vertices = np.asarray(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0))
        )
        with self.assertRaises(MultipartTopologyError) as caught:
            normalize_multipart_part(
                vertices,
                np.asarray(((0, 1, 2),), dtype=np.int32),
                _colors(3),
            )
        self.assertEqual(caught.exception.code, "noncollapsed_degenerate_faces")

    def test_nearby_coordinates_are_not_merged(self) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 1.0e-12),
            ),
            dtype=np.float64,
        )
        faces = _TETRA_FACES.copy()
        faces[0, 0] = 4

        result = normalize_multipart_part(vertices, faces, _colors(len(vertices)))

        self.assertEqual(result.metadata["exact_coordinate_vertex_merges"], 0)
        self.assertEqual(result.metadata["removed_collapsed_faces"], 0)
        self.assertEqual(len(result.vertices), len(vertices))
        np.testing.assert_array_equal(
            result.vertices[result.faces], vertices[faces]
        )

    def test_exact_seam_color_merge_is_recorded(self) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 0.0),
            ),
            dtype=np.float64,
        )
        faces = _TETRA_FACES.copy()
        faces[0, 0] = 4

        result = normalize_multipart_part(
            vertices,
            faces,
            _colors(len(vertices)),
            allow_color_merge=True,
        )

        links = result.metadata["vertex_links"]
        self.assertGreater(links["changed_source_vertex_colors"], 0)
        self.assertGreater(links["maximum_vertex_color_adjustment"], 0.0)
        self.assertEqual(result.metadata["exact_coordinate_vertex_merges"], 1)
        self.assertEqual(result.metadata["sector_split_vertices"], 0)
        self.assertTrue(result.metadata["after"]["watertight"])

    def test_authored_vertex_color_seam_fails_closed_by_default(self) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 0.0),
            ),
            dtype=np.float64,
        )
        faces = _TETRA_FACES.copy()
        faces[0, 0] = 4

        with self.assertRaises(MultipartTopologyError) as caught:
            normalize_multipart_part(vertices, faces, _colors(len(vertices)))

        self.assertEqual(caught.exception.code, "authored_vertex_color_seam")
        self.assertGreater(
            caught.exception.details["maximum_vertex_color_adjustment"], 0.0
        )

    def test_collapsed_only_vertices_have_separate_accounting(self) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 0.0),
                (2.0, 2.0, 2.0),
            ),
            dtype=np.float64,
        )
        faces = np.vstack(
            (_TETRA_FACES, np.asarray(((0, 4, 5),), dtype=np.int32))
        )

        result = normalize_multipart_part(vertices, faces, _colors(len(vertices)))
        metadata = result.metadata

        self.assertEqual(metadata["collapsed_only_source_vertices"], 2)
        self.assertEqual(metadata["collapsed_only_exact_positions"], 1)
        self.assertEqual(metadata["exact_coordinate_vertex_merges"], 0)
        self.assertEqual(metadata["sector_split_vertices"], 0)
        self.assertEqual(metadata["input_unreferenced_vertices"], 0)
        self.assertEqual(metadata["net_vertex_reduction"], 2)
        self.assertEqual(
            metadata["net_vertex_reduction"],
            metadata["input_unreferenced_vertices"]
            + metadata["collapsed_only_source_vertices"]
            + metadata["exact_coordinate_vertex_merges"]
            - metadata["sector_split_vertices"],
        )

    def test_balanced_edge_sectors_split_into_closed_bodies(self) -> None:
        angle_20 = np.deg2rad(20.0)
        angle_220 = np.deg2rad(220.0)
        first = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, np.cos(angle_20), np.sin(angle_20)),
            )
        )
        second = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, -1.0, 0.0),
                (0.0, np.cos(angle_220), np.sin(angle_220)),
            )
        )
        vertices = np.vstack((first, second))
        first_faces = _oriented_tetra_faces(first)
        second_faces = _oriented_tetra_faces(second) + 4
        faces = np.vstack((first_faces, second_faces))

        result = normalize_multipart_part(vertices, faces, _colors(len(vertices)))

        edge = result.metadata["edge_pairing"]
        self.assertEqual(edge["high_incidence_geometric_edges"], 1)
        self.assertEqual(edge["maximum_geometric_edge_incidence"], 4)
        self.assertEqual(edge["smooth_sector_pairs"], 2)
        self.assertGreater(edge["minimum_unique_assignment_margin"], 0.0)
        self.assertEqual(result.metadata["removed_collapsed_faces"], 0)
        self.assertEqual(result.metadata["after"]["boundary_edges"], 0)
        self.assertEqual(result.metadata["after"]["nonmanifold_edges"], 0)
        self.assertEqual(
            result.metadata["after"]["inconsistent_winding_edges"], 0
        )
        np.testing.assert_array_equal(
            result.vertices[result.faces], vertices[faces]
        )

    def test_symmetric_sector_assignment_is_rejected_as_ambiguous(self) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, -1.0, 0.0),
                (0.0, 0.0, -1.0),
            )
        )
        faces = np.asarray(
            ((0, 1, 2), (1, 0, 3), (0, 1, 4), (1, 0, 5)),
            dtype=np.int32,
        )
        with self.assertRaises(MultipartTopologyError) as caught:
            normalize_multipart_part(vertices, faces, _colors(len(vertices)))
        self.assertEqual(
            caught.exception.code, "ambiguous_high_incidence_edge_sectors"
        )

    def test_near_symmetric_sector_assignment_is_rejected(self) -> None:
        vertices = np.asarray(
            ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1),
             (0, -1, 0), (0, 1.0e-10, -1)),
            dtype=np.float64,
        )
        faces = np.asarray(
            ((0, 1, 2), (1, 0, 3), (0, 1, 4), (1, 0, 5)),
            dtype=np.int32,
        )
        with self.assertRaises(MultipartTopologyError) as caught:
            normalize_multipart_part(vertices, faces, _colors(len(vertices)))
        self.assertEqual(
            caught.exception.code, "ambiguous_high_incidence_edge_sectors"
        )

    def test_unbalanced_high_incidence_edge_fails_closed(self) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, -1.0, 0.0),
                (0.0, 0.0, -1.0),
            )
        )
        faces = np.asarray(
            ((0, 1, 2), (0, 1, 3), (0, 1, 4), (1, 0, 5)),
            dtype=np.int32,
        )
        with self.assertRaises(MultipartTopologyError) as caught:
            normalize_multipart_part(vertices, faces, _colors(len(vertices)))
        self.assertEqual(caught.exception.code, "unbalanced_high_incidence_edge")

    def test_same_direction_two_sided_edge_fails_closed(self) -> None:
        vertices = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            )
        )
        faces = np.asarray(((0, 1, 2), (0, 1, 3)), dtype=np.int32)
        with self.assertRaises(MultipartTopologyError) as caught:
            normalize_multipart_part(vertices, faces, _colors(len(vertices)))
        self.assertEqual(
            caught.exception.code, "same_direction_two_sided_edges"
        )

    def test_excessive_edge_incidence_rejects_before_assignment(self) -> None:
        angles = np.linspace(0.0, 2.0 * np.pi, 18, endpoint=False)
        vertices = np.vstack(
            (
                np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))),
                np.column_stack(
                    (
                        np.zeros(len(angles)),
                        np.cos(angles),
                        np.sin(angles),
                    )
                ),
            )
        )
        faces = np.asarray(
            [
                (0, 1, index + 2)
                if index % 2 == 0
                else (1, 0, index + 2)
                for index in range(len(angles))
            ],
            dtype=np.int32,
        )
        with patch(
            "spectrum_mapper.multipart_topology.linear_sum_assignment",
            side_effect=AssertionError("assignment must remain uncalled"),
        ):
            with self.assertRaises(MultipartTopologyError) as caught:
                normalize_multipart_part(
                    vertices, faces, _colors(len(vertices))
                )
        self.assertEqual(
            caught.exception.code, "excessive_high_incidence_edge"
        )
        self.assertEqual(caught.exception.details["maximum_incidence"], 18)
        self.assertEqual(caught.exception.details["supported_maximum"], 16)

    def test_part_work_budget_rejects_before_large_work_arrays(self) -> None:
        vertices = np.asarray(
            ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
            dtype=np.float64,
        )
        with patch(
            "spectrum_mapper.multipart_topology._MAX_PART_FACE_COUNT", 3
        ), patch(
            "spectrum_mapper.multipart_topology.np.unique",
            side_effect=AssertionError("large work arrays must remain unbuilt"),
        ):
            with self.assertRaises(MultipartTopologyError) as caught:
                normalize_multipart_part(
                    vertices, _TETRA_FACES, _colors(len(vertices))
                )

        self.assertEqual(
            caught.exception.code, "normalization_work_budget_exceeded"
        )
        self.assertEqual(caught.exception.details["source_faces"], 4)
        self.assertEqual(caught.exception.details["maximum_faces"], 3)


class MultipartTopologyEngineIntegrationTests(unittest.TestCase):
    def test_object_xml_preserves_binary64_vertex_coordinates(self) -> None:
        vertices_mm = np.asarray(
            (
                (123.45678901234567, 1.234567890123456e-8, -0.0),
                (-450.1234567890123, 2.345678901234567e-7, 7.0),
                (0.33333333333333331, -8.765432109876543, 2.0),
                (9.876543210987654, 4.567890123456789e-6, -3.0),
            ),
            dtype=np.float64,
        )
        self.assertNotEqual(
            float(f"{vertices_mm[0, 0]:.9g}"), vertices_mm[0, 0]
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "precision.3mf"
            with zipfile.ZipFile(destination, "w") as archive:
                engine._write_object_xml(
                    archive,
                    vertices_mm,
                    _TETRA_FACES,
                    np.zeros(len(_TETRA_FACES), dtype=np.int16),
                )
            with zipfile.ZipFile(destination) as archive:
                root = ET.fromstring(
                    archive.read("3D/Objects/object_1.model")
                )
        parsed = np.asarray(
            [
                tuple(float(vertex.attrib[axis]) for axis in ("x", "y", "z"))
                for vertex in root.findall(".//{*}vertex")
            ],
            dtype=np.float64,
        )
        np.testing.assert_array_equal(parsed, vertices_mm)

    @staticmethod
    def _bounded_warning_fixture(
        *, qem: bool = False, compatible_import: bool = True
    ):
        if qem:
            first = np.asarray(
                (
                    (0, 0, 1),
                    (0, 0, -1),
                    (1, 0, 0),
                    (0, 1, 0),
                    (-1, 0, 0),
                    (0, -1, 0),
                ),
                dtype=np.float32,
            )
            first_faces = np.asarray(
                (
                    (0, 2, 3),
                    (0, 3, 4),
                    (0, 4, 5),
                    (0, 5, 2),
                    (1, 3, 2),
                    (1, 4, 3),
                    (1, 5, 4),
                    (1, 2, 5),
                ),
                dtype=np.int32,
            )
        else:
            first = np.asarray(
                ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
                dtype=np.float32,
            )
            first_faces = _TETRA_FACES
        vertices = np.vstack((first, first + (3, 0, 0)))
        faces = np.vstack((first_faces, first_faces + len(first)))
        faces_per_part = len(first_faces)
        asset = ObjAsset(
            path=Path("compatible-multipart.glb"),
            sha256="0" * 64,
            file_size=1,
            vertices=vertices,
            colors=np.asarray(_colors(len(vertices)), dtype=np.float32),
            faces=faces,
            original_vertex_count=len(vertices),
            original_face_count=len(faces),
            warnings=[],
            part_names=("first", "second"),
            part_keys=("gltf:first", "gltf:second"),
            face_part_ids=np.asarray(
                [0] * faces_per_part + [1] * faces_per_part,
                dtype=np.int32,
            ),
            part_face_counts=(faces_per_part, faces_per_part),
            part_vertex_counts=(len(first), len(first)),
            part_marker_kind="gltf_node",
            has_explicit_parts=True,
        )
        # The importer persists this narrow compatibility proof.  Setting it
        # explicitly keeps the synthetic fixture independent of GLB parsing.
        asset.import_metadata = {
            "schema": "obj-adjuster.gltf-import.v1",
            "compatible_exploded_multipart": compatible_import,
            "categorical_part_ids_detected": compatible_import,
            "segmentation_vertex_colors_suppressed": compatible_import,
        }
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000 if qem else 8,
            preview_faces=len(faces),
            adjust_face_count=qem,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=True,
        )
        if qem:
            def reduce_octahedron_to_tetrahedron(vertices, *_args, **_kwargs):
                vertices = np.asarray(vertices)
                selected = np.asarray(
                    (
                        np.argmax(vertices[:, 2]),
                        np.argmin(vertices[:, 2]),
                        np.argmax(vertices[:, 0]),
                        np.argmax(vertices[:, 1]),
                    ),
                    dtype=np.int32,
                )
                output_vertices = vertices[selected].copy()
                return output_vertices, _oriented_tetra_faces(output_vertices)

            # A real 8 -> 4 output reduction exercises the QEM route while
            # retaining a deterministic valid closed solid.
            with patch.object(
                engine,
                "_allocate_part_targets",
                return_value=np.asarray((4, 4), dtype=np.int64),
            ), patch.object(
                engine,
                "_simplify_mesh",
                side_effect=reduce_octahedron_to_tetrahedron,
            ):
                prepared = engine.prepare_geometry(asset, settings)
        else:
            prepared = engine.prepare_geometry(asset, settings)
        palette = PaletteSettings()
        colors = engine.recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        return settings, prepared, palette, colors

    @staticmethod
    def _bounded_warning_real_local_cap_fixture():
        # Part 0 is an open, small tetrahedron.  The real preparation path
        # closes its triangular hole with a local cap; part 1 is already a
        # strict solid.  Keeping the first tetra small makes the opening fall
        # below the public 2 mm local-repair bound at 100 mm output height.
        first = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (0.01, 0.0, 0.0),
                (0.0, 0.01, 0.0),
                (0.0, 0.0, 0.01),
            ),
            dtype=np.float32,
        )
        second = np.asarray(
            ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
            dtype=np.float32,
        ) + np.asarray((3, 0, 0), dtype=np.float32)
        vertices = np.vstack((first, second))
        first_faces = np.asarray(_TETRA_FACES[1:], dtype=np.int32)
        faces = np.vstack((first_faces, _TETRA_FACES + len(first)))
        asset = ObjAsset(
            path=Path("compatible-local-cap.glb"),
            sha256="0" * 64,
            file_size=1,
            vertices=vertices,
            colors=np.asarray(_colors(len(vertices)), dtype=np.float32),
            faces=faces,
            original_vertex_count=len(vertices),
            original_face_count=len(faces),
            warnings=[],
            part_names=("open", "closed"),
            part_keys=("gltf:open", "gltf:closed"),
            face_part_ids=np.asarray(
                [0] * len(first_faces) + [1] * len(_TETRA_FACES),
                dtype=np.int32,
            ),
            part_face_counts=(len(first_faces), len(_TETRA_FACES)),
            part_vertex_counts=(len(first), len(second)),
            part_marker_kind="gltf_node",
            has_explicit_parts=True,
        )
        asset.import_metadata = {
            "schema": "obj-adjuster.gltf-import.v1",
            "compatible_exploded_multipart": True,
            "categorical_part_ids_detected": True,
            "segmentation_vertex_colors_suppressed": True,
        }
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=len(faces),
            preview_faces=len(faces) + 1,
            adjust_face_count=False,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
        )
        prepared = engine.prepare_geometry(asset, settings)
        palette = PaletteSettings()
        colors = engine.recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        return settings, prepared, palette, colors

    @staticmethod
    def _bounded_warning_real_shared_cap_fixture():
        # Two public synthetic open tetrahedra share one triangular boundary.
        # The real preparation path closes both sides with coordinated planar
        # caps, which exercises one-sided individual-export projection without
        # relying on a private validation asset.
        first = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float32,
        )
        second = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, -1.0),
            ),
            dtype=np.float32,
        )
        open_faces = np.asarray(_TETRA_FACES[1:], dtype=np.int32)
        vertices = np.vstack((first, second))
        faces = np.vstack((open_faces, open_faces + len(first)))
        asset = ObjAsset(
            path=Path("compatible-shared-cap.glb"),
            sha256="0" * 64,
            file_size=1,
            vertices=vertices,
            colors=np.asarray(_colors(len(vertices)), dtype=np.float32),
            faces=faces,
            original_vertex_count=len(vertices),
            original_face_count=len(faces),
            warnings=[],
            part_names=("upper", "lower"),
            part_keys=("gltf:upper", "gltf:lower"),
            face_part_ids=np.asarray(
                [0] * len(open_faces) + [1] * len(open_faces),
                dtype=np.int32,
            ),
            part_face_counts=(len(open_faces), len(open_faces)),
            part_vertex_counts=(len(first), len(second)),
            part_marker_kind="gltf_node",
            has_explicit_parts=True,
        )
        asset.import_metadata = {
            "schema": "obj-adjuster.gltf-import.v1",
            "compatible_exploded_multipart": True,
            "categorical_part_ids_detected": True,
            "segmentation_vertex_colors_suppressed": True,
        }
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=len(faces),
            preview_faces=len(faces) + 2,
            adjust_face_count=False,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=True,
        )
        prepared = engine.prepare_geometry(asset, settings)
        palette = PaletteSettings()
        colors = engine.recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        return settings, prepared, palette, colors

    @staticmethod
    def _record_bounded_intersection(
        prepared,
        *,
        face_ids: list[int],
        source_face_limit: int = 4,
        final_face_count: int = 4,
        part_id: int = 0,
    ) -> None:
        provenance = prepared.assembly[
            "multipart_self_intersection_provenance"
        ]
        part = provenance["parts"][part_id]
        policy = part["warning_policy"]
        face_limit, area_fraction_limit = (
            engine.multipart_self_intersection_limits(
                source_face_limit,
                policy,
            )
        )
        area_unit2 = 1.0e-8
        area_fraction = (
            1.0e-3
            if policy == engine.MULTIPART_QEM_WARNING
            else 1.0e-6
        )
        inherited_source = bool(
            policy == engine.MULTIPART_INHERITED_SOURCE_WARNING
        )
        part.update(
            {
                "source_face_limit": source_face_limit,
                "final_face_count": final_face_count,
                "self_intersecting_face_ids": list(face_ids),
                "self_intersecting_faces": len(face_ids),
                "self_intersecting_area_unit2": area_unit2,
                "self_intersecting_area_fraction": area_fraction,
                "self_intersection_face_limit": face_limit,
                "self_intersection_area_fraction_limit": (
                    area_fraction_limit
                ),
                "self_intersection_warning": True,
                "source_triangle_ancestry_proven": inherited_source,
                "self_intersection_inherited_from_source": (
                    inherited_source
                ),
                "record_valid": True,
            }
        )
        strict = prepared.assembly["repair_records"][-1]["parts"][part_id]
        strict.update(
            {
                "self_intersection_source_face_limit": source_face_limit,
                "self_intersections": len(face_ids),
                "self_intersecting_face_ids": list(face_ids),
                "self_intersecting_area_unit2": area_unit2,
                "self_intersecting_area_fraction": area_fraction,
                "self_intersection_face_limit": face_limit,
                "self_intersection_area_fraction_limit": (
                    area_fraction_limit
                ),
                "self_intersection_source_faces_only": True,
                "source_triangle_ancestry_proven": inherited_source,
                "self_intersection_inherited_from_source": (
                    inherited_source
                ),
                "self_intersection_warning": True,
                "self_intersection_policy": policy,
            }
        )

    @staticmethod
    def _quality_with_intersection_on_every_object(
        face_ids: list[int],
        *,
        area_fraction: float = 1.0e-6,
    ):
        original = engine.mesh_quality

        def quality(*args, **kwargs):
            result = original(*args, **kwargs)
            result.update(
                {
                    "self_intersecting_faces": len(face_ids),
                    "self_intersecting_area": 1.0e-4,
                    "self_intersecting_area_fraction": area_fraction,
                    "maximum_self_intersecting_face_area": 1.0e-4,
                    "self_intersecting_face_ids": list(face_ids),
                    "self_intersecting_face_ids_complete": True,
                }
            )
            return result

        return quality

    @staticmethod
    def _quality_with_intersection(
        face_ids: list[int],
        *,
        area_fraction: float = 1.0e-6,
    ):
        original = engine.mesh_quality
        calls = 0

        def quality(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            # The writer now checks the exact export-space geometry before
            # serializing it, and validate_3mf independently recomputes the
            # same two part objects after reload.  Inject the finding into
            # part 0 of both passes.
            if calls % 2 == 0:
                result.update(
                    {
                        "self_intersecting_faces": len(face_ids),
                        "self_intersecting_area": 1.0e-4,
                        "self_intersecting_area_fraction": area_fraction,
                        "maximum_self_intersecting_face_area": 1.0e-4,
                        "self_intersecting_face_ids": list(face_ids),
                        "self_intersecting_face_ids_complete": True,
                    }
                )
            calls += 1
            return result

        return quality

    def _projected_shared_interface_fixture(self):
        settings, prepared, palette, _colors_result = (
            self._bounded_warning_real_local_cap_fixture()
        )
        projected, _source_face_ids = workflow._extract_prepared_part(
            prepared,
            0,
        )
        source_part_key = projected.final.part_keys[0]

        # Reuse the real closed tetrahedron produced by the local-cap path,
        # but truthfully identify its final face as a projected shared cap.
        # This keeps the test geometry real while avoiding any private asset.
        face_provenance = np.asarray(
            projected.final.face_provenance,
            dtype=np.uint8,
        ).copy()
        self.assertEqual(face_provenance.tolist(), [0, 0, 0, 2])
        face_provenance[-1] = FACE_PROVENANCE_PLANAR_CAP
        projected.final.face_provenance = face_provenance

        strict_part = copy.deepcopy(
            projected.assembly["repair_records"][-1]["parts"][0]
        )
        strict_part["added_faces"] = 1
        projected.assembly["repair_records"] = [
            {
                "method": "partitioned_shared_caps",
                "identity": False,
                "source_parts": 1,
                "output_parts": 1,
                "matched_seams": 1,
                "source_triangle_coordinates_preserved": True,
                "interfaces": [
                    {
                        "individual_projection_schema": (
                            engine.INDIVIDUAL_SHARED_INTERFACE_SCHEMA
                        ),
                        "parts": [0],
                        "source_interface_parts": [0, 1],
                        "source_part_index": 0,
                        "source_part_key": source_part_key,
                        "boundary_vertices": 3,
                        "cap_faces": 1,
                        "cap_face_range_by_part": {"0": [3, 4]},
                        "boundary_vertex_ids_by_part": {
                            "0": [0, 1, 2]
                        },
                        "source_triangle_coordinates_preserved": True,
                    }
                ],
                "parts": [strict_part],
                "closed": True,
            }
        ]
        projected.assembly.update(
            {
                "individual_part_export": True,
                "source_part_index": 0,
                "source_part_key": source_part_key,
                "source_parent_part_count": 2,
                "generated_surface_provenance": (
                    make_face_provenance_record(projected.final)
                ),
            }
        )
        self._record_bounded_intersection(
            projected,
            face_ids=[0],
            source_face_limit=3,
            final_face_count=4,
        )
        colors = engine.recolor_level(
            projected.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        return settings, projected, palette, colors

    def test_projected_shared_interface_warning_is_validated(self) -> None:
        settings, prepared, palette, colors = (
            self._projected_shared_interface_fixture()
        )
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection_on_every_object([0]),
        ):
            destination = Path(temporary) / "projected-shared-cap.3mf"
            validation = engine.write_3mf_atomic(
                destination,
                prepared,
                colors,
                settings.height_mm,
                palette,
            )
            with zipfile.ZipFile(destination) as archive:
                assembly = json.loads(
                    archive.read("Metadata/tripo_assembly.json").decode(
                        "utf-8"
                    )
                )

        interface = assembly["repair_records"][-1]["interfaces"][0]
        self.assertEqual(
            interface["individual_projection_schema"],
            engine.INDIVIDUAL_SHARED_INTERFACE_SCHEMA,
        )
        self.assertEqual(interface["parts"], [0])
        self.assertEqual(interface["source_interface_parts"], [0, 1])
        topology = validation["part_topologies"][0]
        self.assertTrue(
            topology["multipart_self_intersection_provenance_valid"]
        )
        self.assertEqual(
            topology["self_intersection_policy"],
            engine.MULTIPART_INHERITED_SOURCE_WARNING,
        )

    def test_projected_shared_interface_tampering_fails_closed(self) -> None:
        def interface(prepared):
            return prepared.assembly["repair_records"][-1]["interfaces"][0]

        mutations = {
            "wrong schema": lambda prepared: interface(prepared).__setitem__(
                "individual_projection_schema", "wrong-schema"
            ),
            "wrong source IDs": lambda prepared: interface(
                prepared
            ).__setitem__("source_interface_parts", [1, 1]),
            "wrong source key": lambda prepared: interface(
                prepared
            ).__setitem__("source_part_key", "gltf:wrong"),
            "wrong cap range": lambda prepared: interface(
                prepared
            ).__setitem__("cap_face_range_by_part", {"0": [2, 3]}),
            "wrong added faces": lambda prepared: prepared.assembly[
                "repair_records"
            ][-1]["parts"][0].__setitem__("added_faces", 0),
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label):
                settings, prepared, palette, colors = (
                    self._projected_shared_interface_fixture()
                )
                mutate(prepared)
                with tempfile.TemporaryDirectory() as temporary, patch.object(
                    engine,
                    "mesh_quality",
                    side_effect=(
                        self._quality_with_intersection_on_every_object([0])
                    ),
                ):
                    destination = Path(temporary) / "tampered.3mf"
                    with self.assertRaisesRegex(
                        engine.EngineError,
                        "self_intersections=1",
                    ):
                        engine.write_3mf_atomic(
                            destination,
                            prepared,
                            colors,
                            settings.height_mm,
                            palette,
                        )
                    self.assertFalse(destination.exists())

    def test_multipart_source_only_intersection_is_bounded_warning(self) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture()
        self._record_bounded_intersection(prepared, face_ids=[0])
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection([0]),
        ):
            destination = Path(temporary) / "multipart-source-warning.3mf"
            validation = engine.write_3mf_atomic(
                destination,
                prepared,
                colors,
                settings.height_mm,
                palette,
            )
        self.assertEqual(
            validation["self_intersection_warning_policy"],
            "normalized_multipart_inherited_source_warning",
        )
        self.assertTrue(
            validation["part_topologies"][0][
                "multipart_self_intersection_provenance_valid"
            ]
        )

    def test_individual_exports_rebase_live_multipart_warning_proof(self) -> None:
        settings, prepared, palette, _colors_result = (
            self._bounded_warning_fixture()
        )
        for part_id in range(2):
            self._record_bounded_intersection(
                prepared,
                face_ids=[0],
                part_id=part_id,
            )
        app_settings = AppSettings(
            geometry=settings,
            tone=ToneSettings(smoothing=False),
            palette=palette,
        )
        validations: list[dict[str, object]] = []
        write_part = workflow.write_3mf_atomic

        def capture_validation(*args, **kwargs):
            result = write_part(*args, **kwargs)
            validations.append(result)
            return result

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection_on_every_object([0]),
        ), patch.object(
            workflow,
            "write_3mf_atomic",
            side_effect=capture_validation,
        ):
            paths = workflow._write_individual_part_models(
                prepared,
                app_settings,
                Path(temporary) / "assembly.3mf",
                manual_overrides=None,
                progress=None,
            )
            self.assertEqual(len(paths), 2)
            self.assertEqual(len(validations), 2)
            for part_id, (path, validation) in enumerate(
                zip(paths, validations, strict=True)
            ):
                with self.subTest(part=part_id):
                    self.assertTrue(path.is_file())
                    extracted, _source_ids = workflow._extract_prepared_part(
                        prepared,
                        part_id,
                    )
                    self.assertEqual(extracted.part_stats[0]["id"], 0)
                    self.assertEqual(
                        extracted.assembly["source_parent_part_count"],
                        2,
                    )
                    self.assertEqual(
                        extracted.assembly[
                            "multipart_provenance_projection"
                        ]["status"],
                        "projected",
                    )
                    with zipfile.ZipFile(path) as archive:
                        assembly = json.loads(
                            archive.read(
                                "Metadata/tripo_assembly.json"
                            ).decode("utf-8")
                        )
                    provenance = assembly[
                        "multipart_self_intersection_provenance"
                    ]
                    self.assertEqual(provenance["part_count"], 1)
                    self.assertEqual(len(provenance["parts"]), 1)
                    self.assertEqual(provenance["parts"][0]["part_id"], 0)
                    self.assertEqual(
                        assembly["multipart_topology_normalization"][0][
                            "part_id"
                        ],
                        0,
                    )
                    self.assertEqual(
                        assembly[
                            "multipart_topology_normalization_summary"
                        ]["attempted_parts"],
                        1,
                    )
                    self.assertEqual(
                        assembly["repair_records"][-1]["parts"][0][
                            "part_id"
                        ],
                        0,
                    )
                    topology = validation["part_topologies"][0]
                    self.assertTrue(
                        topology[
                            "multipart_self_intersection_provenance_valid"
                        ]
                    )
                    self.assertEqual(
                        topology["self_intersection_policy"],
                        engine.MULTIPART_INHERITED_SOURCE_WARNING,
                    )

    def test_individual_projection_preserves_real_local_cap_ranges(self) -> None:
        settings, prepared, palette, _colors_result = (
            self._bounded_warning_real_local_cap_fixture()
        )
        app_settings = AppSettings(
            geometry=settings,
            tone=ToneSettings(smoothing=False),
            palette=palette,
        )
        first, _ = workflow._extract_prepared_part(prepared, 0)
        second, _ = workflow._extract_prepared_part(prepared, 1)
        self.assertEqual(
            first.assembly["multipart_provenance_projection"]["status"],
            "projected",
        )
        self.assertEqual(
            second.assembly["multipart_provenance_projection"]["status"],
            "projected",
        )
        first_local = first.assembly["repair_records"][0]
        self.assertEqual(
            first_local["method"],
            "strict_planar_unmatched_boundary_caps",
        )
        self.assertEqual(first_local["repaired_loop_count"], 1)
        self.assertEqual(first_local["loops"][0]["part_id"], 0)
        self.assertEqual(first_local["loops"][0]["cap_face_ids"], [3])
        self.assertEqual(
            [value["method"] for value in second.assembly["repair_records"]],
            ["partitioned_shared_caps"],
        )

        with tempfile.TemporaryDirectory() as temporary:
            paths = workflow._write_individual_part_models(
                prepared,
                app_settings,
                Path(temporary) / "local-cap.3mf",
                manual_overrides=None,
                progress=None,
            )
            self.assertEqual(len(paths), 2)
            self.assertTrue(all(path.is_file() for path in paths))

    def test_individual_warning_projection_fails_closed_on_parent_tamper(
        self,
    ) -> None:
        mutations = {
            "missing normalization": lambda prepared: prepared.assembly[
                "multipart_topology_normalization"
            ].pop(),
            "aggregate mismatch": lambda prepared: prepared.assembly[
                "multipart_self_intersection_provenance"
            ].__setitem__("warning_policy", "tampered"),
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label):
                settings, prepared, palette, _colors_result = (
                    self._bounded_warning_fixture()
                )
                for part_id in range(2):
                    self._record_bounded_intersection(
                        prepared,
                        face_ids=[0],
                        part_id=part_id,
                    )
                mutate(prepared)
                extracted, _ = workflow._extract_prepared_part(prepared, 0)
                self.assertNotEqual(
                    extracted.assembly[
                        "multipart_provenance_projection"
                    ]["status"],
                    "projected",
                )
                self.assertNotIn(
                    "multipart_self_intersection_provenance",
                    extracted.assembly,
                )
                app_settings = AppSettings(
                    geometry=settings,
                    tone=ToneSettings(smoothing=False),
                    palette=palette,
                )
                with tempfile.TemporaryDirectory() as temporary, patch.object(
                    engine,
                    "mesh_quality",
                    side_effect=(
                        self._quality_with_intersection_on_every_object([0])
                    ),
                ):
                    destination = Path(temporary) / "assembly.3mf"
                    with self.assertRaisesRegex(
                        engine.EngineError,
                        "self_intersections=1",
                    ):
                        workflow._write_individual_part_models(
                            prepared,
                            app_settings,
                            destination,
                            manual_overrides=None,
                            progress=None,
                        )
                    self.assertFalse(
                        destination.with_suffix("").with_name(
                            destination.stem + "_parts"
                        ).exists()
                    )

    def test_individual_projection_rebases_both_shared_cap_sides(self) -> None:
        settings, prepared, palette, _colors_result = (
            self._bounded_warning_real_shared_cap_fixture()
        )
        parent_interface = prepared.assembly["repair_records"][-1][
            "interfaces"
        ][0]
        self.assertEqual(parent_interface["parts"], [0, 1])

        # Insert one deliberately unreferenced vertex at the start of the
        # second parent part's vertex block.  Parent-local boundary IDs then
        # differ from the compact child IDs, proving that extraction uses the
        # returned old-to-new map instead of merely copying the numbers.
        second_vertex_offset = int(prepared.part_stats[0]["final_vertices"])
        prepared.final.vertices_unit = np.insert(
            prepared.final.vertices_unit,
            second_vertex_offset,
            prepared.final.vertices_unit[second_vertex_offset],
            axis=0,
        )
        prepared.final.vertex_colors = np.insert(
            prepared.final.vertex_colors,
            second_vertex_offset,
            prepared.final.vertex_colors[second_vertex_offset],
            axis=0,
        )
        second_faces = prepared.final.face_part_ids == 1
        prepared.final.faces[second_faces] += 1
        prepared.part_stats[1]["final_vertices"] += 1
        parent_interface["boundary_vertex_ids_by_part"]["1"] = [1, 2, 3]
        prepared.assembly["generated_surface_provenance"] = (
            make_face_provenance_record(prepared.final)
        )

        for source_part_id in range(2):
            with self.subTest(source_part=source_part_id):
                extracted, _ = workflow._extract_prepared_part(
                    prepared,
                    source_part_id,
                )
                self.assertEqual(
                    extracted.assembly["multipart_provenance_projection"][
                        "status"
                    ],
                    "projected",
                )
                self.assertEqual(
                    extracted.assembly["source_part_index"],
                    source_part_id,
                )
                self.assertEqual(
                    extracted.assembly["source_parent_part_count"],
                    2,
                )
                self.assertEqual(extracted.part_stats[0]["id"], 0)

                projected_solid = extracted.assembly["repair_records"][-1]
                self.assertEqual(
                    projected_solid["method"],
                    "partitioned_shared_caps",
                )
                self.assertEqual(projected_solid["source_parts"], 1)
                self.assertEqual(projected_solid["output_parts"], 1)
                self.assertEqual(projected_solid["matched_seams"], 1)
                self.assertEqual(projected_solid["parts"][0]["part_id"], 0)
                self.assertEqual(projected_solid["parts"][0]["added_faces"], 1)

                interface = projected_solid["interfaces"][0]
                source_key = prepared.final.part_keys[source_part_id]
                self.assertEqual(
                    interface["individual_projection_schema"],
                    engine.INDIVIDUAL_SHARED_INTERFACE_SCHEMA,
                )
                self.assertEqual(interface["parts"], [0])
                self.assertEqual(interface["source_interface_parts"], [0, 1])
                self.assertEqual(
                    interface["source_part_index"],
                    source_part_id,
                )
                self.assertEqual(interface["source_part_key"], source_key)
                self.assertEqual(
                    interface["cap_face_range_by_part"],
                    {"0": [3, 4]},
                )
                self.assertEqual(
                    interface["boundary_vertex_ids_by_part"],
                    {"0": [0, 1, 2]},
                )
                self.assertEqual(
                    set(interface["outward_normal_by_part"]),
                    {"0"},
                )
                self.assertEqual(
                    extracted.assembly[
                        "multipart_self_intersection_provenance"
                    ]["parts"][0]["part_key"],
                    source_key,
                )

        app_settings = AppSettings(
            geometry=settings,
            tone=ToneSettings(smoothing=False),
            palette=palette,
        )
        with tempfile.TemporaryDirectory() as temporary:
            paths = workflow._write_individual_part_models(
                prepared,
                app_settings,
                Path(temporary) / "shared-cap.3mf",
                manual_overrides=None,
                progress=None,
            )
            self.assertEqual(len(paths), 2)
            self.assertTrue(all(path.is_file() for path in paths))

    def test_individual_shared_cap_projection_fails_closed_on_parent_tamper(
        self,
    ) -> None:
        def solid(prepared):
            return prepared.assembly["repair_records"][-1]

        mutations = {
            "other-side range": lambda prepared: solid(prepared)["interfaces"][
                0
            ]["cap_face_range_by_part"].__setitem__("1", [2, 3]),
            "other-side boundary": lambda prepared: solid(prepared)[
                "interfaces"
            ][0]["boundary_vertex_ids_by_part"].__setitem__(
                "1", [0, 1, 99]
            ),
            "other-side strict count": lambda prepared: solid(prepared)[
                "parts"
            ][1].__setitem__("added_faces", 0),
            "live generated suffix": lambda prepared: prepared.final.face_provenance.__setitem__(
                -1,
                0,
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label):
                _settings, prepared, _palette, _colors_result = (
                    self._bounded_warning_real_shared_cap_fixture()
                )
                mutate(prepared)
                extracted, _ = workflow._extract_prepared_part(prepared, 0)
                self.assertNotEqual(
                    extracted.assembly[
                        "multipart_provenance_projection"
                    ]["status"],
                    "projected",
                )
                self.assertNotIn(
                    "multipart_self_intersection_provenance",
                    extracted.assembly,
                )
                self.assertNotIn("repair_records", extracted.assembly)

    def test_inherited_source_area_limit_is_forwarded_at_exact_boundary(
        self,
    ) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture()
        self._record_bounded_intersection(prepared, face_ids=[0])
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection(
                [0], area_fraction=0.002
            ),
        ):
            destination = Path(temporary) / "exact-area-boundary.3mf"
            validation = engine.write_3mf_atomic(
                destination,
                prepared,
                colors,
                settings.height_mm,
                palette,
            )
            with zipfile.ZipFile(destination) as archive:
                assembly = json.loads(
                    archive.read("Metadata/tripo_assembly.json").decode(
                        "utf-8"
                    )
                )

        exported_part = assembly[
            "multipart_self_intersection_provenance"
        ]["parts"][0]
        self.assertEqual(
            exported_part["self_intersecting_area_fraction"], 0.002
        )
        self.assertEqual(
            exported_part["self_intersection_area_fraction_limit"], 0.002
        )
        self.assertEqual(
            validation["part_topologies"][0][
                "self_intersecting_area_fraction"
            ],
            0.002,
        )
        self.assertTrue(
            validation["part_topologies"][0][
                "multipart_self_intersection_provenance_valid"
            ]
        )

    def test_inherited_source_area_above_exact_limit_fails_closed(
        self,
    ) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture()
        self._record_bounded_intersection(prepared, face_ids=[0])
        above_limit = float(
            np.nextafter(np.float64(0.002), np.float64(np.inf))
        )
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection(
                [0], area_fraction=above_limit
            ),
        ):
            destination = Path(temporary) / "above-area-boundary.3mf"
            with self.assertRaisesRegex(
                engine.EngineError,
                "安全な警告範囲",
            ):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_multipart_warning_requires_external_source_limit_anchor(
        self,
    ) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture()
        self._record_bounded_intersection(prepared, face_ids=[0])
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "anchored-warning.3mf"
            with patch.object(
                engine,
                "mesh_quality",
                side_effect=self._quality_with_intersection([0]),
            ):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            definitions = engine.make_portable_mixed_definitions(
                palette.mix_ratios_b,
                palette.secondary_mix_ratios_b,
                palette.palette_state_count,
                palette.output_mix_ratios_b,
                palette.surface_shell_enabled,
                palette.physical_hex,
            )
            with patch.object(
                engine,
                "mesh_quality",
                side_effect=self._quality_with_intersection([0]),
            ), self.assertRaisesRegex(
                engine.EngineError, "self_intersections=1"
            ):
                engine.validate_3mf(
                    destination,
                    expected_vertices=len(prepared.final.vertices_unit),
                    expected_faces=len(prepared.final.faces),
                    expected_physical=[
                        engine.normalize_hex(value)
                        for value in palette.physical_hex
                    ],
                    expected_definitions=definitions,
                    expected_parts=2,
                    expected_filament_profile=(
                        engine.generic_filament_profile(palette.material)
                    ),
                )

    def test_ineligible_multipart_skips_export_space_recheck(self) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture()
        prepared.assembly["multipart_self_intersection_provenance"][
            "eligible"
        ] = False
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "_trusted_multipart_export_self_intersection_records",
            side_effect=AssertionError("unexpected export-space recheck"),
        ):
            validation = engine.write_3mf_atomic(
                Path(temporary) / "ineligible-strict-zero.3mf",
                prepared,
                colors,
                settings.height_mm,
                palette,
            )
        self.assertEqual(
            validation["self_intersection_warning_policy"],
            "strict_zero",
        )

    def test_multipart_provenance_persists_suppressed_id_colour_proof(
        self,
    ) -> None:
        _settings, prepared, _palette, _colors_result = (
            self._bounded_warning_fixture()
        )
        provenance = prepared.assembly[
            "multipart_self_intersection_provenance"
        ]
        self.assertIs(
            provenance["segmentation_vertex_colors_suppressed"], True
        )

    def test_multipart_warning_rejects_missing_or_false_suppression_proof(
        self,
    ) -> None:
        for value in (None, False):
            with self.subTest(value=value):
                settings, prepared, palette, colors = (
                    self._bounded_warning_fixture()
                )
                self._record_bounded_intersection(prepared, face_ids=[0])
                provenance = prepared.assembly[
                    "multipart_self_intersection_provenance"
                ]
                if value is None:
                    provenance.pop(
                        "segmentation_vertex_colors_suppressed"
                    )
                else:
                    provenance[
                        "segmentation_vertex_colors_suppressed"
                    ] = value
                with tempfile.TemporaryDirectory() as temporary, patch.object(
                    engine,
                    "mesh_quality",
                    side_effect=self._quality_with_intersection([0]),
                ):
                    destination = Path(temporary) / "suppression-blocked.3mf"
                    with self.assertRaisesRegex(
                        engine.EngineError, "self_intersections=1"
                    ):
                        engine.write_3mf_atomic(
                            destination,
                            prepared,
                            colors,
                            settings.height_mm,
                            palette,
                        )
                    self.assertFalse(destination.exists())

    def test_multipart_qem_intersection_uses_separate_policy(self) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture(
            qem=True
        )
        provenance = prepared.assembly[
            "multipart_self_intersection_provenance"
        ]
        self.assertEqual(provenance["parts"][0]["pre_qem_face_count"], 8)
        self.assertEqual(
            provenance["parts"][0]["post_qem_source_face_count"], 4
        )
        self.assertIs(provenance["parts"][0]["qem_warning_eligible"], True)
        self._record_bounded_intersection(prepared, face_ids=[0])
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection(
                [0], area_fraction=1.0e-3
            ),
        ):
            validation = engine.write_3mf_atomic(
                Path(temporary) / "multipart-qem-warning.3mf",
                prepared,
                colors,
                settings.height_mm,
                palette,
            )
        self.assertEqual(
            validation["self_intersection_warning_policy"],
            "normalized_multipart_bounded_qem_warning",
        )
        self.assertFalse(
            validation["part_topologies"][0][
                "self_intersection_source_geometry_preserved"
            ]
        )
        self.assertEqual(
            validation["part_topologies"][0][
                "self_intersection_face_limit"
            ],
            8,
        )
        self.assertEqual(
            validation["part_topologies"][0][
                "self_intersection_area_fraction_limit"
            ],
            0.002,
        )

    def test_export_space_record_may_differ_from_safe_prep_record(
        self,
    ) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture(
            qem=True
        )
        # Preparation proved one source-face intersection in normalized
        # coordinates.  MeshLab may classify an additional near-contact
        # source face after centering and scaling to final millimetres.  Both
        # findings remain independently inside the same externally anchored
        # QEM policy; they must not be forced to have identical face IDs.
        self._record_bounded_intersection(prepared, face_ids=[0])
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection(
                [0, 1], area_fraction=1.0e-3
            ),
        ):
            destination = Path(temporary) / "export-space-warning.3mf"
            validation = engine.write_3mf_atomic(
                destination,
                prepared,
                colors,
                settings.height_mm,
                palette,
            )
            with zipfile.ZipFile(destination) as archive:
                assembly = json.loads(
                    archive.read("Metadata/tripo_assembly.json").decode(
                        "utf-8"
                    )
                )

        provenance = assembly["multipart_self_intersection_provenance"]
        self.assertIs(provenance["export_revalidated"], True)
        self.assertEqual(
            provenance["export_coordinate_space"],
            "final_centered_mm",
        )
        self.assertEqual(
            provenance["parts"][0]["self_intersecting_face_ids"],
            [0, 1],
        )
        self.assertEqual(
            assembly["repair_records"][-1]["parts"][0][
                "self_intersecting_face_ids"
            ],
            [0],
        )
        self.assertEqual(
            validation["part_topologies"][0]["self_intersecting_faces"],
            2,
        )
        self.assertEqual(
            validation["part_topologies"][0][
                "self_intersection_face_limit"
            ],
            8,
        )
        self.assertEqual(
            validation["part_topologies"][0][
                "self_intersection_area_fraction_limit"
            ],
            0.002,
        )

    def test_one_face_reduction_cannot_gain_qem_warning_budget(self) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture(
            qem=True
        )
        for stats in prepared.part_stats:
            stats["clean_faces"] = 5
            stats["pre_qem_face_count"] = 5
            stats["post_qem_source_face_count"] = 4
            stats["simplification_applied"] = True
            stats["qem_warning_eligible"] = False
        self.assertFalse(
            engine.multipart_qem_reduction_is_significant(39_838, 39_837)
        )
        self.assertTrue(
            engine.multipart_qem_reduction_is_significant(39_838, 8_892)
        )
        self._record_bounded_intersection(prepared, face_ids=[0])
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection(
                [0], area_fraction=1.0e-3
            ),
        ):
            destination = Path(temporary) / "one-face-qem-blocked.3mf"
            with self.assertRaisesRegex(
                engine.EngineError,
                "source_only=False|self_intersections=1",
            ):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_qem_archive_cannot_claim_source_geometry_preserved(self) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture(
            qem=True
        )
        self._record_bounded_intersection(prepared, face_ids=[0])
        prepared.assembly["multipart_self_intersection_provenance"][
            "parts"
        ][0]["source_triangle_geometry_preserved"] = True
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection(
                [0], area_fraction=1.0e-3
            ),
        ):
            destination = Path(temporary) / "qem-source-claim-blocked.3mf"
            with self.assertRaisesRegex(
                engine.EngineError, "self_intersections=1"
            ):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_qem_archive_pre_count_must_match_external_anchor(self) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture(
            qem=True
        )
        self._record_bounded_intersection(prepared, face_ids=[0])
        prepared.assembly["multipart_self_intersection_provenance"][
            "parts"
        ][0]["pre_qem_face_count"] = 16
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection(
                [0], area_fraction=1.0e-3
            ),
        ):
            destination = Path(temporary) / "qem-pre-count-blocked.3mf"
            with self.assertRaisesRegex(
                engine.EngineError, "self_intersections=1"
            ):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_meshlab_suffix_intersection_is_not_inherited_source(self) -> None:
        # Start from a closed cube, push one corner through the opposite face,
        # and place every face incident to that corner after the seven-face
        # source prefix.  The resulting indexed surface remains one valid
        # watertight body, while its suffix crosses a source-prefix triangle.
        vertices = np.asarray(
            (
                (-1.0, -1.0, -1.0),
                (-1.0, -1.0, 1.0),
                (-1.0, 1.0, -1.0),
                (-1.0, 1.0, 1.0),
                (1.0, -1.0, -1.0),
                (1.0, -1.0, 1.0),
                (1.0, 1.0, -1.0),
                (1.0, 1.0, -1.5),
            ),
            dtype=np.float64,
        )
        faces = np.asarray(
            (
                (1, 3, 0),
                (4, 1, 0),
                (0, 3, 2),
                (2, 4, 0),
                (5, 1, 4),
                (6, 4, 2),
                (6, 5, 4),
                (1, 7, 3),
                (5, 7, 1),
                (3, 7, 2),
                (2, 7, 6),
                (7, 5, 6),
            ),
            dtype=np.int32,
        )
        source_face_limit = 7
        observed: dict[str, object] = {}
        real_mesh_quality = engine.mesh_quality

        def capture_real_meshlab_result(*args, **kwargs):
            result = real_mesh_quality(*args, **kwargs)
            observed.update(result)
            return result

        # Widen only the numerical warning budget so that rejection cannot be
        # attributed to count or area.  MeshLab still performs the real
        # intersection selection used by the inherited-source range gate.
        with patch.object(
            engine,
            "multipart_self_intersection_limits",
            return_value=(100, 1.0),
        ), patch.object(
            engine,
            "mesh_quality",
            side_effect=capture_real_meshlab_result,
        ), self.assertRaisesRegex(
            engine.EngineError,
            "source_only=False",
        ):
            engine._trusted_multipart_export_self_intersection_records(
                vertices,
                faces,
                np.zeros(len(faces), dtype=np.int32),
                (source_face_limit,),
                (source_face_limit,),
                (engine.MULTIPART_INHERITED_SOURCE_WARNING,),
                height_mm=2.5,
                part_count=1,
            )

        self.assertIs(observed["watertight"], True)
        self.assertIs(observed["winding_consistent"], True)
        self.assertIs(observed["positive_volume"], True)
        self.assertEqual(observed["body_count"], 1)
        self.assertIs(
            observed["self_intersecting_face_ids_complete"], True
        )
        selected_ids = observed["self_intersecting_face_ids"]
        self.assertTrue(
            any(face_id < source_face_limit for face_id in selected_ids)
        )
        self.assertTrue(
            any(face_id >= source_face_limit for face_id in selected_ids)
        )

    def test_multipart_cap_face_cannot_be_relabelled_as_source(self) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture()
        self._record_bounded_intersection(prepared, face_ids=[3])
        # The coordinated metadata tamper inflates source_face_limit to four,
        # but repair provenance independently identifies face 3 as a cap.
        prepared.assembly["repair_records"].insert(
            0,
            {
                "method": "strict_planar_unmatched_boundary_caps",
                "loops": [{"part_id": 0, "cap_face_ids": [3]}],
            },
        )
        prepared.assembly["generated_surface_provenance"][
            "generated_face_count"
        ] = 1
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection([3]),
        ):
            destination = Path(temporary) / "cap-relabel-blocked.3mf"
            with self.assertRaisesRegex(engine.EngineError, "self_intersections=1"):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_real_local_cap_coordinated_metadata_relabel_is_blocked(
        self,
    ) -> None:
        settings, prepared, palette, colors = (
            self._bounded_warning_real_local_cap_fixture()
        )
        local_provenance = np.asarray(
            prepared.final.face_provenance
        )[prepared.final.face_part_ids == 0]
        self.assertEqual(local_provenance.tolist(), [0, 0, 0, 2])

        # Face 3 is a real cap according to the final in-memory provenance.
        # Coordinate all archive metadata to claim that it is source: remove
        # the local-cap record, zero the generated counts, and inflate both
        # self-intersection source limits.  The independent writer anchor must
        # still retain limit 3 and reject this archive-side relabel.
        prepared.assembly["repair_records"] = [
            value
            for value in prepared.assembly["repair_records"]
            if value.get("method")
            != "strict_planar_unmatched_boundary_caps"
        ]
        generated = prepared.assembly["generated_surface_provenance"]
        generated["generated_face_count"] = 0
        generated["origin_counts"] = {
            "0": int(len(prepared.final.faces))
        }
        self._record_bounded_intersection(
            prepared,
            face_ids=[3],
            source_face_limit=4,
            final_face_count=4,
        )
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection([3]),
        ):
            destination = Path(temporary) / "real-cap-relabel-blocked.3mf"
            with self.assertRaisesRegex(
                engine.EngineError,
                "source_only=False|self_intersections=1",
            ):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_multipart_recomputed_ids_must_match_stored_provenance(self) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture()
        self._record_bounded_intersection(prepared, face_ids=[1])
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(
                engine,
                "mesh_quality",
                side_effect=self._quality_with_intersection([0]),
            ),
            patch.object(
                engine,
                "_apply_export_self_intersection_records",
                return_value=None,
            ),
        ):
            destination = Path(temporary) / "id-tamper-blocked.3mf"
            with self.assertRaisesRegex(engine.EngineError, "self_intersections=1"):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_multipart_deleted_interface_ranges_cannot_relabel_cap(
        self,
    ) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture()
        self._record_bounded_intersection(prepared, face_ids=[3])
        solid = prepared.assembly["repair_records"][-1]
        solid.update(
            {
                "method": "partitioned_shared_caps",
                "identity": False,
                "matched_seams": 1,
                "interfaces": [
                    {
                        "parts": [0, 1],
                        "boundary_vertices": 3,
                        "cap_faces": 1,
                        # Coordinated tamper: delete both generated ranges,
                        # zero the prep counts, and retain the source limit.
                        "cap_face_range_by_part": {},
                        "boundary_vertex_ids_by_part": {
                            "0": [0, 1, 2],
                            "1": [0, 1, 2],
                        },
                        "source_triangle_coordinates_preserved": True,
                    }
                ],
            }
        )
        for value in solid["parts"]:
            value["added_faces"] = 0
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection([3]),
        ):
            destination = Path(temporary) / "deleted-cap-ranges-blocked.3mf"
            with self.assertRaisesRegex(engine.EngineError, "self_intersections=1"):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_multipart_malformed_provenance_fails_closed(self) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture()
        self._record_bounded_intersection(prepared, face_ids=[0])
        prepared.assembly["multipart_self_intersection_provenance"][
            "parts"
        ][0]["simplification_applied"] = []
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection([0]),
        ):
            destination = Path(temporary) / "malformed-blocked.3mf"
            with self.assertRaisesRegex(engine.EngineError, "self_intersections=1"):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_ordinary_multipart_gltf_does_not_gain_warning_exception(
        self,
    ) -> None:
        settings, prepared, palette, colors = self._bounded_warning_fixture(
            compatible_import=False
        )
        self.assertFalse(
            prepared.assembly["multipart_self_intersection_provenance"][
                "eligible"
            ]
        )
        self._record_bounded_intersection(prepared, face_ids=[0])
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine,
            "mesh_quality",
            side_effect=self._quality_with_intersection([0]),
        ):
            destination = Path(temporary) / "ordinary-gltf-blocked.3mf"
            with self.assertRaisesRegex(engine.EngineError, "self_intersections=1"):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_multipart_intersection_count_over_limit_is_blocked(self) -> None:
        settings, prepared, palette, _colors_result = (
            self._bounded_warning_fixture()
        )
        first_faces = np.asarray(prepared.final.faces[:4], dtype=np.int32)
        second_faces = np.asarray(prepared.final.faces[4:], dtype=np.int32)
        expanded_first = np.tile(first_faces, (49, 1))
        prepared.final.faces = np.vstack((expanded_first, second_faces))
        prepared.final.face_part_ids = np.asarray(
            [0] * len(expanded_first) + [1] * len(second_faces),
            dtype=np.int16,
        )
        prepared.final.areas_unit = engine.triangle_areas(
            prepared.final.vertices_unit, prepared.final.faces
        )
        prepared.final.neighbors = engine.face_neighbors_partial(
            prepared.final.faces, len(prepared.final.vertices_unit)
        )
        prepared.final.face_provenance = np.zeros(
            len(prepared.final.faces), dtype=np.uint8
        )
        generated = prepared.assembly["generated_surface_provenance"]
        generated["face_count"] = len(prepared.final.faces)
        generated["generated_face_count"] = 0
        face_ids = list(range(101))
        self._record_bounded_intersection(
            prepared,
            face_ids=face_ids,
            source_face_limit=len(expanded_first),
            final_face_count=len(expanded_first),
        )
        colors = engine.recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        original = engine.mesh_quality
        calls = 0

        def over_limit_quality(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            if calls == 0:
                result.update(
                    {
                        "watertight": True,
                        "winding_consistent": True,
                        "positive_volume": True,
                        "body_count": 1,
                        "degenerate_faces": 0,
                        "self_intersecting_faces": len(face_ids),
                        "self_intersecting_area": 1.0e-4,
                        "self_intersecting_area_fraction": 1.0e-6,
                        "maximum_self_intersecting_face_area": 1.0e-4,
                        "self_intersecting_face_ids": face_ids,
                        "self_intersecting_face_ids_complete": True,
                    }
                )
            calls += 1
            return result

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine, "mesh_quality", side_effect=over_limit_quality
        ):
            destination = Path(temporary) / "over-count-blocked.3mf"
            with self.assertRaisesRegex(
                engine.EngineError, "self_intersections=101"
            ):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_gltf_node_parts_normalize_before_cleaning(self) -> None:
        first = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 0.0),
            ),
            dtype=np.float32,
        )
        second = np.asarray(
            (
                (3.0, 0.0, 0.0),
                (4.0, 0.0, 0.0),
                (3.0, 1.0, 0.0),
                (3.0, 0.0, 1.0),
            ),
            dtype=np.float32,
        )
        vertices = np.vstack((first, second))
        first_faces = np.vstack(
            (_TETRA_FACES, np.asarray(((0, 4, 1),), dtype=np.int32))
        )
        faces = np.vstack((first_faces, _TETRA_FACES + len(first)))
        face_part_ids = np.asarray(
            [0] * len(first_faces) + [1] * len(_TETRA_FACES),
            dtype=np.int32,
        )
        asset = ObjAsset(
            path=Path("synthetic.glb"),
            sha256="0" * 64,
            file_size=1,
            vertices=vertices,
            colors=np.asarray(_colors(len(vertices)), dtype=np.float32),
            faces=faces,
            original_vertex_count=len(vertices),
            original_face_count=len(faces),
            warnings=[],
            part_names=("first", "second"),
            part_keys=("gltf:first", "gltf:second"),
            face_part_ids=face_part_ids,
            part_face_counts=(len(first_faces), len(_TETRA_FACES)),
            part_vertex_counts=(len(first), len(second)),
            part_marker_kind="gltf_node",
            has_explicit_parts=True,
        )
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=True,
        )

        result = engine.prepare_geometry(asset, settings)

        self.assertTrue(result.topology["watertight"])
        self.assertEqual(len(result.final.faces), 8)
        records = result.assembly["multipart_topology_normalization"]
        self.assertEqual(len(records), 2)
        self.assertEqual(
            [record["removed_collapsed_faces"] for record in records], [1, 0]
        )
        self.assertTrue(all(record["face_order_preserved"] for record in records))
        self.assertTrue(
            all(record["geometry_coordinates_preserved"] for record in records)
        )
        self.assertEqual(result.part_stats[0]["source_faces"], 5)
        self.assertEqual(result.part_stats[0]["normalized_faces"], 4)
        self.assertEqual(result.part_stats[0]["removed_faces"], 1)
        self.assertEqual(
            result.part_stats[0]["total_source_to_clean_face_delta"], 1
        )
        self.assertEqual(result.removed_faces, 1)
        summary = result.assembly[
            "multipart_topology_normalization_summary"
        ]
        self.assertEqual(summary["removed_collapsed_faces"], 1)
        self.assertEqual(summary["component_cleanup_removed_faces"], 0)
        json.dumps(records)
        json.dumps(summary)
        self.assertTrue(
            any("縮退すると証明" in warning for warning in result.warnings)
        )

    def test_ordinary_prep_keeps_raw_part_without_normalization(self) -> None:
        first = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float32,
        )
        second = first + np.asarray((3.0, 0.0, 0.0), dtype=np.float32)
        vertices = np.vstack((first, second))
        # Repeating a tetra face creates three odd high-incidence geometric
        # edges.  Normalization must reject transactionally, not consume it.
        first_faces = np.vstack((_TETRA_FACES, _TETRA_FACES[:1]))
        faces = np.vstack((first_faces, _TETRA_FACES + len(first)))
        asset = ObjAsset(
            path=Path("rejected.glb"),
            sha256="0" * 64,
            file_size=1,
            vertices=vertices,
            colors=np.asarray(_colors(len(vertices)), dtype=np.float32),
            faces=faces,
            original_vertex_count=len(vertices),
            original_face_count=len(faces),
            warnings=[],
            part_names=("first", "second"),
            part_keys=("gltf:first", "gltf:second"),
            face_part_ids=np.asarray(
                [0] * len(first_faces) + [1] * len(_TETRA_FACES),
                dtype=np.int32,
            ),
            part_face_counts=(len(first_faces), len(_TETRA_FACES)),
            part_vertex_counts=(len(first), len(second)),
            part_marker_kind="gltf_node",
            has_explicit_parts=True,
        )
        ordinary = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=False,
        )

        result = engine.prepare_geometry(asset, ordinary)

        self.assertEqual(result.assembly["multipart_topology_normalization"], [])
        self.assertEqual(
            result.part_stats[0]["normalization_status"], "not_applicable"
        )
        self.assertEqual(result.part_stats[0]["normalized_faces"], 5)
        np.testing.assert_array_equal(
            result.final.vertex_colors, asset.colors
        )
        json.dumps(result.assembly["multipart_topology_normalization"])

        strict = replace(ordinary, solidify_parts=True)
        with self.assertRaises(engine.EngineError) as caught:
            engine.prepare_geometry(asset, strict)
        self.assertIn("閉立体", str(caught.exception))
        self.assertIn("非多様体 3", str(caught.exception))

    def test_rejected_normalization_can_use_established_orientation(self) -> None:
        first = np.asarray(
            ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
            dtype=np.float32,
        )
        vertices = np.vstack((first, first + (3, 0, 0)))
        reversed_faces = _TETRA_FACES.copy()
        reversed_faces[0, [1, 2]] = reversed_faces[0, [2, 1]]
        faces = np.vstack((reversed_faces, _TETRA_FACES + 4))
        asset = ObjAsset(
            path=Path("reoriented.glb"), sha256="0" * 64, file_size=1,
            vertices=vertices, colors=np.ones((8, 3), dtype=np.float32),
            faces=faces, original_vertex_count=8, original_face_count=8,
            warnings=[], part_names=("a", "b"),
            part_keys=("gltf:a", "gltf:b"),
            face_part_ids=np.asarray([0] * 4 + [1] * 4, dtype=np.int32),
            part_face_counts=(4, 4), part_vertex_counts=(4, 4),
            part_marker_kind="gltf_node", has_explicit_parts=True,
        )
        settings = GeometrySettings(
            height_mm=100, target_faces=1000, preview_faces=1000,
            adjust_face_count=False, up_axis="Z", min_component_faces=0,
            solidify_parts=True,
        )

        result = engine.prepare_geometry(asset, settings)

        self.assertTrue(result.topology["watertight"])
        self.assertEqual(
            result.part_stats[0]["normalization_status"], "rejected"
        )

    def test_work_budget_rejection_falls_back_to_raw_parts(self) -> None:
        first = np.asarray(
            ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
            dtype=np.float32,
        )
        vertices = np.vstack((first, first + (3, 0, 0)))
        faces = np.vstack((_TETRA_FACES, _TETRA_FACES + 4))
        asset = ObjAsset(
            path=Path("budgeted.glb"), sha256="0" * 64, file_size=1,
            vertices=vertices, colors=np.ones((8, 3), dtype=np.float32),
            faces=faces, original_vertex_count=8, original_face_count=8,
            warnings=[], part_names=("a", "b"),
            part_keys=("gltf:a", "gltf:b"),
            face_part_ids=np.asarray([0] * 4 + [1] * 4, dtype=np.int32),
            part_face_counts=(4, 4), part_vertex_counts=(4, 4),
            part_marker_kind="gltf_node", has_explicit_parts=True,
        )
        settings = GeometrySettings(
            height_mm=100, target_faces=1000, preview_faces=1000,
            adjust_face_count=False, up_axis="Z", min_component_faces=0,
            solidify_parts=True,
        )

        with patch(
            "spectrum_mapper.multipart_topology._MAX_PART_FACE_COUNT", 3
        ):
            result = engine.prepare_geometry(asset, settings)

        self.assertTrue(result.topology["watertight"])
        records = result.assembly["multipart_topology_normalization"]
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["status"] == "rejected" for record in records))
        self.assertTrue(
            all(
                record["error_code"]
                == "normalization_work_budget_exceeded"
                for record in records
            )
        )
        self.assertTrue(
            all(
                stat["normalization_status"] == "rejected"
                for stat in result.part_stats
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
