from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import trimesh


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.assembly import AssemblyError, solidify_coincident_shells
import spectrum_mapper.engine as engine_module
from spectrum_mapper.engine import (
    EngineError,
    _orient_watertight_bodies_positive,
    edge_topology,
    prepare_geometry,
    recolor_level,
    triangle_areas,
    write_3mf_atomic,
)
from spectrum_mapper.generated_surface_color import (
    FACE_PROVENANCE_LOCAL_CAP,
    FACE_PROVENANCE_SOURCE,
    validate_face_provenance,
)
from spectrum_mapper.gltf_import import load_gltf_asset
from spectrum_mapper.models import (
    AppSettings,
    GeometrySettings,
    ObjAsset,
    PaletteSettings,
    ToneSettings,
)
from spectrum_mapper.project_bundle import (
    CURRENT_PROJECT_SCHEMA,
    inspect_project_path,
    save_project_bundle,
)
from spectrum_mapper.workflow import export_bundle
from test_gltf_import import _append, _base_document, _write_glb


def _tetrahedron() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    # Positive-volume outward winding.
    faces = np.asarray(
        [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        dtype=np.int32,
    )
    colors = np.asarray(
        [
            [0.10, 0.20, 0.30],
            [0.70, 0.10, 0.20],
            [0.20, 0.75, 0.15],
            [0.15, 0.25, 0.80],
        ],
        dtype=np.float64,
    )
    return vertices, faces, colors


def _face_soup(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    *,
    color_offsets: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    soup_vertices = np.asarray(vertices[faces], dtype=np.float64).reshape((-1, 3))
    soup_faces = np.arange(len(soup_vertices), dtype=np.int32).reshape((-1, 3))
    soup_colors = np.asarray(colors[faces], dtype=np.float64).reshape((-1, 3))
    if color_offsets:
        offsets = np.repeat(
            np.linspace(0.0, 0.03, len(faces), dtype=np.float64), 3
        )
        soup_colors = np.clip(soup_colors + offsets[:, None], 0.0, 1.0)
    return soup_vertices, soup_faces, soup_colors


def _write_uv_seamed_tetra_glb(root: Path) -> Path:
    vertices, faces, colors = _tetrahedron()
    soup_vertices, soup_faces, soup_colors = _face_soup(
        vertices, faces, colors, color_offsets=True
    )
    binary = bytearray()
    offsets = [
        _append(binary, soup_vertices.astype("<f4").tobytes()),
        _append(binary, soup_colors.astype("<f4").tobytes()),
        _append(binary, soup_faces.astype("<u2").reshape(-1).tobytes()),
    ]
    document = _base_document()
    document["nodes"] = [{"name": "Hi3D one primitive", "mesh": 0}]
    document["bufferViews"] = [
        {"buffer": 0, "byteOffset": offset, "byteLength": length}
        for offset, length in offsets
    ]
    document["accessors"] = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": len(soup_vertices),
            "type": "VEC3",
        },
        {
            "bufferView": 1,
            "componentType": 5126,
            "count": len(soup_colors),
            "type": "VEC3",
        },
        {
            "bufferView": 2,
            "componentType": 5123,
            "count": int(soup_faces.size),
            "type": "SCALAR",
        },
    ]
    document["meshes"] = [
        {
            "name": "UV-seamed solid",
            "primitives": [
                {
                    "attributes": {"POSITION": 0, "COLOR_0": 1},
                    "indices": 2,
                }
            ],
        }
    ]
    return _write_glb(root, document, bytes(binary))


def _face_soup_asset(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
) -> ObjAsset:
    soup_vertices, soup_faces, soup_colors = _face_soup(
        vertices, faces, colors
    )
    return ObjAsset(
        path=Path("synthetic_uv_seams.glb"),
        sha256="0" * 64,
        file_size=0,
        vertices=soup_vertices.astype(np.float32),
        colors=soup_colors.astype(np.float32),
        faces=soup_faces,
        original_vertex_count=len(soup_vertices),
        original_face_count=len(soup_faces),
        warnings=[],
        part_names=("Hi3D one primitive",),
        part_keys=("gltf:synthetic:single",),
        face_part_ids=np.zeros(len(soup_faces), dtype=np.int16),
        part_face_counts=(len(soup_faces),),
        part_vertex_counts=(len(soup_vertices),),
        has_explicit_parts=False,
    )


def _intersecting_closed_bodies_asset() -> ObjAsset:
    """One large box plus a tiny closed tetra crossing its outer surface."""

    box = trimesh.creation.box(extents=(100.0, 100.0, 100.0))
    box_vertices = np.asarray(box.vertices, dtype=np.float64)
    box_faces = np.asarray(box.faces, dtype=np.int32)
    # The production exception is area-based.  Subdivide the source surface
    # so the one intersected box triangle represents less than 1e-4 of the
    # total area, just like a dense generated GLB rather than a 12-face cube.
    for _ in range(5):
        box_vertices, box_faces = trimesh.remesh.subdivide(
            box_vertices, box_faces
        )
        box_faces = np.asarray(box_faces, dtype=np.int32)
    positive_x_faces = box_faces[
        np.all(box_vertices[box_faces, 0] == 50.0, axis=1)
    ]
    target_point = np.asarray([50.0, 7.3, 11.7])
    centroids = box_vertices[positive_x_faces].mean(axis=1)
    surface_center = centroids[
        np.argmin(np.linalg.norm(centroids - target_point, axis=1))
    ]
    tetra_vertices, tetra_faces, tetra_colors = _tetrahedron()
    tiny_scale = 0.05
    tiny_vertices = tetra_vertices * tiny_scale + np.asarray(
        [
            50.0 - tiny_scale * 0.25,
            surface_center[1] - tiny_scale * 0.25,
            surface_center[2] - tiny_scale * 0.25,
        ]
    )
    vertices = np.vstack((box_vertices, tiny_vertices))
    faces = np.vstack(
        (box_faces, tetra_faces + len(box_vertices))
    ).astype(np.int32)
    colors = np.vstack(
        (
            np.tile(np.asarray([[0.45, 0.50, 0.55]]), (len(box_vertices), 1)),
            tetra_colors,
        )
    )
    return _face_soup_asset(vertices, faces, colors)


def _dominant_surface_with_micro_junk_asset(
    *,
    include_positive_solid: bool = False,
    indexed_main: bool = False,
) -> ObjAsset:
    """Large exact-position surface plus ambiguous microscopic face debris."""

    main = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    main_vertices = np.asarray(main.vertices, dtype=np.float64)
    main_faces = np.asarray(main.faces, dtype=np.int32)
    main_colors = np.tile(
        np.asarray([[0.35, 0.45, 0.55]], dtype=np.float64),
        (len(main_vertices), 1),
    )
    if indexed_main:
        vertices = main_vertices.copy()
        faces = main_faces.copy()
        colors = main_colors.copy()
    else:
        vertices, faces, colors = _face_soup(
            main_vertices,
            main_faces,
            main_colors,
        )

    if include_positive_solid:
        solid_vertices, solid_faces, solid_colors = _tetrahedron()
        solid_vertices = solid_vertices * 0.001 + np.asarray([0.1, 0.1, 0.1])
        solid_vertices, solid_faces, solid_colors = _face_soup(
            solid_vertices,
            solid_faces,
            solid_colors,
        )
        solid_faces = solid_faces + len(vertices)
        vertices = np.vstack((vertices, solid_vertices))
        faces = np.vstack((faces, solid_faces)).astype(np.int32)
        colors = np.vstack((colors, solid_colors))
        junk_copy_count = 2
    else:
        # Three coincident copies make every geometric edge ambiguous.  They
        # are not allowed into the exact seam weld merely because they are tiny.
        junk_copy_count = 3

    junk_triangle = np.asarray(
        [[0.0, 0.0, 0.001], [0.001, 0.0, 0.001], [0.0, 0.001, 0.001]],
        dtype=np.float64,
    )
    junk_vertices = np.tile(junk_triangle, (junk_copy_count, 1))
    junk_faces = (
        np.arange(junk_copy_count * 3, dtype=np.int32).reshape((-1, 3))
        + len(vertices)
    )
    vertices = np.vstack((vertices, junk_vertices))
    faces = np.vstack((faces, junk_faces)).astype(np.int32)
    colors = np.vstack(
        (
            colors,
            np.tile(
                np.asarray([[0.2, 0.2, 0.2]], dtype=np.float64),
                (len(junk_vertices), 1),
            ),
        )
    )
    return ObjAsset(
        path=Path("synthetic_dominant_surface.glb"),
        sha256="0" * 64,
        file_size=0,
        vertices=vertices.astype(np.float32),
        colors=colors.astype(np.float32),
        faces=faces,
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=[],
        part_names=("one generated primitive",),
        part_keys=("gltf:synthetic:dominant",),
        face_part_ids=np.zeros(len(faces), dtype=np.int16),
        part_face_counts=(len(faces),),
        part_vertex_counts=(len(vertices),),
        has_explicit_parts=False,
    )


def _indexed_watertight_surface_asset() -> ObjAsset:
    main = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    vertices = np.asarray(main.vertices, dtype=np.float32)
    faces = np.asarray(main.faces, dtype=np.int32)
    colors = np.tile(
        np.asarray([[0.35, 0.45, 0.55]], dtype=np.float32),
        (len(vertices), 1),
    )
    return ObjAsset(
        path=Path("synthetic_indexed_watertight.glb"),
        sha256="2" * 64,
        file_size=0,
        vertices=vertices,
        colors=colors,
        faces=faces,
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=[],
        part_names=("one indexed primitive",),
        part_keys=("gltf:synthetic:indexed-watertight",),
        face_part_ids=np.zeros(len(faces), dtype=np.int16),
        part_face_counts=(len(faces),),
        part_vertex_counts=(len(vertices),),
        has_explicit_parts=False,
    )


def _dominant_surface_with_interior_coincident_edge_asset() -> ObjAsset:
    """Closed indexed surface whose exact-position collapse is non-manifold."""

    main = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    vertices = np.asarray(main.vertices, dtype=np.float64).copy()
    faces = np.asarray(main.faces, dtype=np.int32)
    edges = np.unique(
        np.sort(
            np.concatenate(
                (
                    faces[:, (0, 1)],
                    faces[:, (1, 2)],
                    faces[:, (2, 0)],
                ),
                axis=0,
            ),
            axis=1,
        ),
        axis=0,
    )
    first_edge = edges[0]
    second_edge = next(
        edge
        for edge in edges[::-1]
        if not set(edge).intersection(first_edge)
    )
    vertices[int(second_edge[0])] = vertices[int(first_edge[0])]
    vertices[int(second_edge[1])] = vertices[int(first_edge[1])]

    # The two coincident edges remain distinct, valid interior indexed edges.
    # Collapsing every exact-position vertex would instead create one false
    # incidence-four edge.  Three coincident micro triangles make the ordinary
    # seam path fail first so the conservative dominant-surface fallback runs.
    junk_triangle = np.asarray(
        [[0.0, 0.0, 0.001], [0.001, 0.0, 0.001], [0.0, 0.001, 0.001]],
        dtype=np.float64,
    )
    junk_vertices = np.tile(junk_triangle, (3, 1))
    junk_faces = (
        np.arange(9, dtype=np.int32).reshape((-1, 3)) + len(vertices)
    )
    vertices = np.vstack((vertices, junk_vertices))
    faces = np.vstack((faces, junk_faces)).astype(np.int32)
    colors = np.tile(
        np.asarray([[0.35, 0.45, 0.55]], dtype=np.float64),
        (len(vertices), 1),
    )
    return ObjAsset(
        path=Path("synthetic_interior_coincident_edge.glb"),
        sha256="1" * 64,
        file_size=0,
        vertices=vertices.astype(np.float32),
        colors=colors.astype(np.float32),
        faces=faces,
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=[],
        part_names=("one generated primitive",),
        part_keys=("gltf:synthetic:interior-coincident",),
        face_part_ids=np.zeros(len(faces), dtype=np.int16),
        part_face_counts=(len(faces),),
        part_vertex_counts=(len(vertices),),
        has_explicit_parts=False,
    )


def _dominant_surface_with_inverted_shells_asset(
    shell_count: int = 2,
) -> ObjAsset:
    """Large closed surface containing several distinct tiny inward shells."""

    main = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
    vertices = np.asarray(main.vertices, dtype=np.float64)
    faces = np.asarray(main.faces, dtype=np.int32)
    colors = np.tile(
        np.asarray([[0.35, 0.45, 0.55]], dtype=np.float64),
        (len(vertices), 1),
    )
    for shell_id in range(shell_count):
        shell_vertices, shell_faces, shell_colors = _tetrahedron()
        shell_vertices = shell_vertices * 0.0001 + np.asarray(
            [
                -0.2 + 0.04 * shell_id,
                -0.1 + 0.02 * (shell_id % 3),
                0.05 - 0.02 * (shell_id % 2),
            ],
            dtype=np.float64,
        )
        shell_faces = shell_faces[:, [0, 2, 1]] + len(vertices)
        vertices = np.vstack((vertices, shell_vertices))
        faces = np.vstack((faces, shell_faces)).astype(np.int32)
        colors = np.vstack((colors, shell_colors))
    return _face_soup_asset(vertices, faces, colors)


class CoincidentShellSolidificationTests(unittest.TestCase):
    def test_exact_uv_seams_close_without_adding_or_moving_triangles(self) -> None:
        vertices, faces, colors = _tetrahedron()
        soup_vertices, soup_faces, soup_colors = _face_soup(
            vertices, faces, colors, color_offsets=True
        )
        before_triangles = soup_vertices[soup_faces].copy()

        repaired_vertices, repaired_faces, repaired_colors, record = (
            solidify_coincident_shells(
                soup_vertices, soup_faces, soup_colors
            )
        )

        self.assertEqual(len(repaired_vertices), 4)
        self.assertEqual(len(repaired_faces), len(soup_faces))
        np.testing.assert_allclose(
            repaired_vertices[repaired_faces], before_triangles, atol=0.0
        )
        self.assertEqual(
            edge_topology(repaired_faces, len(repaired_vertices))["watertight"],
            True,
        )
        self.assertEqual(
            int(
                np.count_nonzero(
                    triangle_areas(repaired_vertices, repaired_faces)
                    <= 1.0e-16
                )
            ),
            0,
        )
        self.assertEqual(record["method"], "coincident_vertex_seam_weld")
        self.assertIs(record["boundary_pairing_proven"], True)
        self.assertEqual(record["source_faces"], record["output_faces"])
        self.assertTrue(record["face_order_preserved"])
        self.assertTrue(record["geometry_coordinates_preserved"])

        for vertex_id, point in enumerate(repaired_vertices):
            selected = np.all(soup_vertices == point, axis=1)
            np.testing.assert_allclose(
                repaired_colors[vertex_id], soup_colors[selected].mean(axis=0)
            )

    def test_a_real_hole_is_not_filled_with_an_invented_cap(self) -> None:
        vertices, faces, colors = _tetrahedron()
        soup_vertices, soup_faces, soup_colors = _face_soup(
            vertices, faces[:-1], colors
        )

        with self.assertRaisesRegex(AssemblyError, "actual opening|実際の開口"):
            solidify_coincident_shells(
                soup_vertices, soup_faces, soup_colors
            )

    def test_internal_partial_weld_leaves_real_hole_open_for_strict_repair(
        self,
    ) -> None:
        vertices, faces, colors = _tetrahedron()
        soup_vertices, soup_faces, soup_colors = _face_soup(
            vertices, faces[:-1], colors
        )

        repaired_vertices, repaired_faces, _colors, record = (
            solidify_coincident_shells(
                soup_vertices,
                soup_faces,
                soup_colors,
                allow_unmatched_boundary_edges=True,
            )
        )

        topology = edge_topology(repaired_faces, len(repaired_vertices))
        self.assertFalse(topology["watertight"])
        self.assertGreater(topology["boundary_edges"], 0)
        self.assertFalse(record["closed"])
        self.assertEqual(
            record["method"], "partial_coincident_vertex_seam_weld"
        )
        self.assertFalse(record["boundary_pairing_proven"])

    def test_already_watertight_input_is_an_identity_copy(self) -> None:
        vertices, faces, colors = _tetrahedron()

        repaired_vertices, repaired_faces, repaired_colors, record = (
            solidify_coincident_shells(vertices, faces, colors)
        )

        np.testing.assert_array_equal(repaired_vertices, vertices)
        np.testing.assert_array_equal(repaired_faces, faces)
        np.testing.assert_array_equal(repaired_colors, colors)
        self.assertTrue(record["identity"])
        self.assertEqual(record["merged_vertices"], 0)

    def test_only_paired_boundary_endpoints_are_merged(self) -> None:
        vertices, faces, colors = _tetrahedron()
        soup_vertices, soup_faces, soup_colors = _face_soup(
            vertices, faces, colors
        )

        # A second indexed solid touches the UV-seamed solid at one exact
        # position.  Its matching vertex is not a boundary endpoint and must
        # remain distinct; global position welding would join the two bodies.
        touching_vertices = -0.5 * vertices
        touching_faces = faces[:, [0, 2, 1]] + len(soup_vertices)
        combined_vertices = np.vstack((soup_vertices, touching_vertices))
        combined_faces = np.vstack((soup_faces, touching_faces)).astype(
            np.int32
        )
        combined_colors = np.vstack((soup_colors, colors[::-1]))

        repaired_vertices, repaired_faces, _repaired_colors, record = (
            solidify_coincident_shells(
                combined_vertices, combined_faces, combined_colors
            )
        )

        self.assertEqual(len(repaired_vertices), 8)
        self.assertEqual(record["body_count"], 2)
        self.assertEqual(
            record["unmerged_interior_coincident_vertex_excess"], 1
        )
        self.assertIs(record["boundary_pairing_proven"], True)
        self.assertTrue(
            edge_topology(repaired_faces, len(repaired_vertices))["watertight"]
        )

    def test_same_direction_or_three_way_boundary_pairing_is_rejected(
        self,
    ) -> None:
        triangle_vertices = np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float64,
        )
        triangle_colors = np.asarray(
            [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]],
            dtype=np.float64,
        )

        for copy_count, expected in ((2, "同方向"), (3, "曖昧")):
            with self.subTest(copy_count=copy_count):
                repeated_vertices = np.tile(
                    triangle_vertices, (copy_count, 1)
                )
                repeated_faces = (
                    np.arange(copy_count * 3, dtype=np.int32).reshape((-1, 3))
                )
                repeated_colors = np.tile(
                    triangle_colors, (copy_count, 1)
                )

                with self.assertRaisesRegex(AssemblyError, expected):
                    solidify_coincident_shells(
                        repeated_vertices, repeated_faces, repeated_colors
                    )


class GltfSingleMeshClosureWorkflowTests(unittest.TestCase):
    def test_single_glb_strictly_repairs_a_tiny_planar_hole_and_exports(
        self,
    ) -> None:
        vertices, faces, colors = _tetrahedron()
        asset = _face_soup_asset(vertices, faces[:-1], colors)
        settings = GeometrySettings(
            height_mm=1.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
        )

        prepared = prepare_geometry(asset, settings)

        self.assertTrue(prepared.topology["watertight"])
        self.assertEqual(len(prepared.final.faces), 4)
        self.assertEqual(
            prepared.assembly["repair_method"],
            "coincident_seam_weld_with_strict_planar_caps",
        )
        self.assertEqual(
            prepared.assembly["repaired_unmatched_boundary_count"], 1
        )
        repair = prepared.assembly["repair_records"][0]
        self.assertEqual(repair["local_boundary_repair_count"], 1)
        self.assertEqual(repair["added_faces"], 1)
        self.assertEqual(repair["output_faces"], 4)
        self.assertEqual(repair["final_face_count"], 4)
        self.assertGreaterEqual(prepared.removed_vertices, 0)
        self.assertEqual(prepared.removed_faces, 0)
        self.assertFalse(
            any("面を除去しました" in warning for warning in prepared.warnings)
        )
        np.testing.assert_array_equal(
            prepared.final.face_provenance,
            np.asarray(
                [
                    FACE_PROVENANCE_SOURCE,
                    FACE_PROVENANCE_SOURCE,
                    FACE_PROVENANCE_SOURCE,
                    FACE_PROVENANCE_LOCAL_CAP,
                ],
                dtype=np.uint8,
            ),
        )
        provenance = validate_face_provenance(prepared)
        self.assertTrue(provenance.valid)
        self.assertEqual(provenance.record["generated_face_count"], 1)

        palette = PaletteSettings()
        result = recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "tiny-planar-hole.3mf"
            validation = write_3mf_atomic(
                destination,
                prepared,
                result,
                settings.height_mm,
                palette,
            )
            self.assertTrue(destination.is_file())
            self.assertEqual(validation["validated_solid_parts"], 1)

    def test_tiny_hole_provenance_survives_prepared_snapshot_round_trip(
        self,
    ) -> None:
        vertices, faces, colors = _tetrahedron()
        settings = GeometrySettings(
            height_mm=1.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
        )
        geometry_key = (None, 1_000, "Y", 0, False, True, True)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "tiny-planar-hole.glb"
            source_payload = b"synthetic tiny planar hole GLB fixture"
            source.write_bytes(source_payload)
            asset = _face_soup_asset(vertices, faces[:-1], colors)
            asset.path = source
            asset.sha256 = hashlib.sha256(source_payload).hexdigest()
            asset.file_size = len(source_payload)
            prepared = prepare_geometry(asset, settings)

            saved = save_project_bundle(
                root / "tiny-planar-hole_project",
                source,
                {
                    "schema": CURRENT_PROJECT_SCHEMA,
                    "settings": {
                        "geometry": {},
                        "palette": {},
                        "tone": {},
                    },
                    "parts": [],
                },
                prepared_geometry=prepared,
                prepared_geometry_key=geometry_key,
            )
            loaded = inspect_project_path(saved.folder)
            restored = loaded.load_exact_prepared_geometry(
                expected_geometry_key=geometry_key
            ).prepared

        self.assertEqual(restored.removed_faces, 0)
        np.testing.assert_array_equal(
            restored.final.face_provenance,
            prepared.final.face_provenance,
        )
        restored_provenance = validate_face_provenance(restored)
        self.assertTrue(restored_provenance.valid)
        self.assertEqual(
            restored_provenance.record["generated_face_count"], 1
        )
        self.assertEqual(
            restored.assembly["repair_records"][0]["output_faces"], 4
        )

    def test_simplified_tiny_hole_repair_drops_stale_face_provenance(
        self,
    ) -> None:
        sphere = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
        vertices = np.asarray(sphere.vertices, dtype=np.float64)
        faces = np.asarray(sphere.faces, dtype=np.int32)
        colors = np.tile(
            np.asarray([[0.2, 0.3, 0.4]], dtype=np.float64),
            (len(vertices), 1),
        )
        asset = _face_soup_asset(vertices, faces[:-1], colors)

        prepared = prepare_geometry(
            asset,
            GeometrySettings(
                height_mm=10.0,
                target_faces=1_000,
                preview_faces=1_000,
                adjust_face_count=True,
                min_component_faces=0,
                solidify_parts=True,
                repair_unmatched_boundaries=True,
            ),
        )

        self.assertEqual(len(prepared.final.faces), 1_000)
        self.assertEqual(prepared.final.face_provenance.shape, (0,))
        provenance = validate_face_provenance(prepared)
        self.assertFalse(provenance.valid)
        self.assertEqual(
            provenance.reason, "topology_changed_after_strict_planar_caps"
        )

    def test_single_glb_does_not_cap_a_hole_larger_than_two_mm(self) -> None:
        vertices, faces, colors = _tetrahedron()
        asset = _face_soup_asset(vertices, faces[:-1], colors)

        with self.assertRaisesRegex(EngineError, "2.0 mm"):
            prepare_geometry(
                asset,
                GeometrySettings(
                    height_mm=20.0,
                    target_faces=1_000,
                    preview_faces=1_000,
                    adjust_face_count=False,
                    min_component_faces=0,
                    solidify_parts=True,
                    repair_unmatched_boundaries=True,
                ),
            )

    def test_removed_distant_island_cannot_shrink_tiny_cap_scale(self) -> None:
        body = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
        body_vertices = np.asarray(body.vertices, dtype=np.float64)
        body_faces = np.asarray(body.faces, dtype=np.int32)
        # Remove the two triangles of the +Y face.  Once the model is
        # normalized to 100 mm tall, this one-unit square opening is far over
        # the strict 2 mm local-cap limit.
        body_faces = body_faces[
            ~np.all(body_vertices[body_faces, 1] == 0.5, axis=1)
        ]
        island_vertices, island_faces, island_colors = _tetrahedron()
        island_vertices = island_vertices + np.asarray([0.0, 100.0, 0.0])
        vertices = np.vstack((body_vertices, island_vertices))
        faces = np.vstack(
            (body_faces, island_faces + len(body_vertices))
        ).astype(np.int32)
        colors = np.vstack(
            (
                np.tile(
                    np.asarray([[0.35, 0.45, 0.55]], dtype=np.float64),
                    (len(body_vertices), 1),
                ),
                island_colors,
            )
        )
        asset = _face_soup_asset(vertices, faces, colors)

        # The four-face tetra is intentionally below the cleanup threshold.
        # Measuring before that cleanup would use its remote Y=100 position,
        # misclassify the body's large opening as tiny, and cap it.
        with self.assertRaisesRegex(EngineError, "2.0 mm"):
            prepare_geometry(
                asset,
                GeometrySettings(
                    height_mm=100.0,
                    target_faces=1_000,
                    preview_faces=1_000,
                    adjust_face_count=False,
                    min_component_faces=5,
                    solidify_parts=True,
                    repair_unmatched_boundaries=True,
                ),
            )

    def test_removable_open_island_does_not_block_valid_main_body(
        self,
    ) -> None:
        main = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
        main_vertices = np.asarray(main.vertices, dtype=np.float64)
        main_faces = np.asarray(main.faces, dtype=np.int32)
        main_colors = np.tile(
            np.asarray([[0.35, 0.45, 0.55]], dtype=np.float64),
            (len(main_vertices), 1),
        )
        island_vertices, island_faces, island_colors = _tetrahedron()
        island_vertices = (
            island_vertices * 10.0 + np.asarray([0.0, 100.0, 0.0])
        )
        vertices = np.vstack((main_vertices, island_vertices))
        faces = np.vstack(
            (main_faces, island_faces[:-1] + len(main_vertices))
        ).astype(np.int32)
        colors = np.vstack((main_colors, island_colors))
        asset = _face_soup_asset(vertices, faces, colors)
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            min_component_faces=4,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
        )

        with (
            patch.object(
                engine_module,
                "_clean_part",
                wraps=engine_module._clean_part,
            ) as clean_part,
            patch.object(
                engine_module,
                "find_boundary_loops",
                wraps=engine_module.find_boundary_loops,
            ) as find_loops,
        ):
            prepared = prepare_geometry(asset, settings)

        self.assertEqual(clean_part.call_count, 1)
        self.assertEqual(find_loops.call_count, 0)
        self.assertEqual(prepared.removed_faces, 3)
        self.assertEqual(len(prepared.final.faces), len(main_faces))
        self.assertTrue(prepared.topology["watertight"])
        self.assertEqual(
            prepared.assembly["repair_method"],
            "coincident_seam_weld_with_component_cleanup",
        )
        repair = prepared.assembly["repair_records"][0]
        self.assertEqual(repair["local_boundary_repair_count"], 0)
        self.assertEqual(repair["added_faces"], 0)
        self.assertEqual(repair["final_face_count"], len(main_faces))
        self.assertEqual(
            prepared.assembly["cleaning_diagnostics"][0][
                "post_local_repair_faces"
            ],
            len(main_faces),
        )

        palette = PaletteSettings()
        result = recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "cleaned-main-body.3mf"
            validation = write_3mf_atomic(
                destination,
                prepared,
                result,
                settings.height_mm,
                palette,
            )
            self.assertTrue(destination.is_file())
            self.assertEqual(validation["validated_solid_parts"], 1)

    def test_precleaned_tiny_hole_keeps_exact_cap_provenance(self) -> None:
        main = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
        main_vertices = np.asarray(main.vertices, dtype=np.float64)
        main_faces = np.asarray(main.faces, dtype=np.int32)
        # Retain the ten-face main component but leave its +Y square open.
        # At one millimetre output height the opening remains inside the
        # strict two-millimetre cap limit.
        main_faces = main_faces[
            ~np.all(main_vertices[main_faces, 1] == 0.5, axis=1)
        ]
        main_colors = np.tile(
            np.asarray([[0.35, 0.45, 0.55]], dtype=np.float64),
            (len(main_vertices), 1),
        )
        island_vertices, island_faces, island_colors = _tetrahedron()
        island_vertices = (
            island_vertices * 0.01 + np.asarray([3.0, 0.0, 0.0])
        )
        vertices = np.vstack((main_vertices, island_vertices))
        faces = np.vstack(
            (main_faces, island_faces + len(main_vertices))
        ).astype(np.int32)
        colors = np.vstack((main_colors, island_colors))
        asset = _face_soup_asset(vertices, faces, colors)
        settings = GeometrySettings(
            height_mm=1.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            min_component_faces=5,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
        )

        with patch.object(
            engine_module,
            "_clean_part",
            wraps=engine_module._clean_part,
        ) as clean_part:
            prepared = prepare_geometry(asset, settings)

        self.assertEqual(clean_part.call_count, 1)
        self.assertEqual(prepared.removed_faces, len(island_faces))
        self.assertEqual(len(prepared.final.faces), 12)
        self.assertTrue(prepared.topology["watertight"])
        self.assertEqual(
            prepared.assembly["repair_method"],
            "coincident_seam_weld_with_strict_planar_caps",
        )
        repair = prepared.assembly["repair_records"][0]
        self.assertEqual(repair["local_boundary_repair_count"], 1)
        self.assertEqual(repair["added_faces"], 2)
        self.assertEqual(repair["final_face_count"], 12)
        np.testing.assert_array_equal(
            prepared.final.face_provenance,
            np.asarray(
                [FACE_PROVENANCE_SOURCE] * 10
                + [FACE_PROVENANCE_LOCAL_CAP] * 2,
                dtype=np.uint8,
            ),
        )
        provenance = validate_face_provenance(prepared)
        self.assertTrue(provenance.valid)
        self.assertEqual(provenance.record["generated_face_count"], 2)

    def test_dominant_surface_filter_removes_only_ambiguous_micro_junk(
        self,
    ) -> None:
        asset = _dominant_surface_with_micro_junk_asset()
        settings = GeometrySettings(
            height_mm=20.0,
            target_faces=2_000,
            preview_faces=2_000,
            adjust_face_count=False,
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
        )

        # The ordinary exact seam proof must fail first.  This proves the test
        # exercises the fallback instead of merely accepting the sphere.
        with self.assertRaises(AssemblyError):
            solidify_coincident_shells(
                asset.vertices,
                asset.faces,
                asset.colors,
                require_positive_volume=False,
                allow_unmatched_boundary_edges=True,
            )

        prepared = prepare_geometry(asset, settings)

        self.assertTrue(prepared.topology["watertight"])
        self.assertEqual(len(prepared.final.faces), 1_280)
        self.assertEqual(prepared.removed_faces, 3)
        self.assertEqual(
            prepared.assembly["repair_method"],
            "coincident_vertex_seam_weld",
        )
        repair = prepared.assembly["repair_records"][0]
        self.assertEqual(repair["method"], "coincident_vertex_seam_weld")
        self.assertTrue(repair["boundary_pairing_proven"])
        self.assertTrue(repair["face_count_preserved"])
        self.assertTrue(repair["geometry_coordinates_preserved"])
        self.assertTrue(repair["source_triangle_geometry_preserved"])
        filtered = repair["dominant_surface_filter"]
        self.assertEqual(
            filtered["schema"],
            "chromamatter.dominant-exact-position-surface.v1",
        )
        self.assertEqual(
            filtered["method"],
            "dominant_exact_position_surface_component_filter",
        )
        self.assertEqual(filtered["source_faces"], 1_283)
        self.assertEqual(filtered["output_faces"], 1_280)
        self.assertEqual(filtered["removed_faces"], 3)
        self.assertEqual(filtered["component_count"], 4)
        self.assertEqual(filtered["removed_component_count"], 3)
        self.assertTrue(filtered["dominant_selective_seam_closed"])
        self.assertIn(
            filtered["dominant_selective_seam_method"],
            {"already_watertight", "coincident_vertex_seam_weld"},
        )
        self.assertTrue(filtered["face_order_preserved"])
        self.assertTrue(filtered["geometry_coordinates_preserved"])
        self.assertTrue(filtered["vertex_colors_preserved"])
        self.assertTrue(
            all(
                item["classification"] == "open_micro_fragment"
                for item in filtered["removed_components"]
            )
        )
        self.assertEqual(
            prepared.assembly["dominant_surface_filter"],
            filtered,
        )
        np.testing.assert_array_equal(
            prepared.final.face_provenance,
            np.full(1_280, FACE_PROVENANCE_SOURCE, dtype=np.uint8),
        )
        provenance = validate_face_provenance(prepared)
        self.assertTrue(provenance.valid)

        palette = PaletteSettings()
        result = recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "dominant-surface-filtered.3mf"
            validation = write_3mf_atomic(
                destination,
                prepared,
                result,
                settings.height_mm,
                palette,
            )
            self.assertTrue(destination.is_file())
            self.assertEqual(validation["validated_solid_parts"], 1)

    @staticmethod
    def _bounded_intersection_quality(original):
        def bounded_intersection(*args, **kwargs):
            quality = original(*args, **kwargs)
            quality["self_intersecting_faces"] = 1
            quality["self_intersecting_area"] = 1.0e-6
            quality["self_intersecting_area_fraction"] = 5.0e-5
            quality["maximum_self_intersecting_face_area"] = 1.0e-6
            quality["self_intersecting_face_ids"] = [0]
            quality["self_intersecting_face_ids_complete"] = True
            return quality

        return bounded_intersection

    def test_indexed_watertight_dominant_filter_allows_bounded_warning(
        self,
    ) -> None:
        asset = _dominant_surface_with_micro_junk_asset(indexed_main=True)
        settings = GeometrySettings(
            height_mm=20.0,
            target_faces=2_000,
            preview_faces=2_000,
            adjust_face_count=False,
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
        )
        with self.assertRaises(AssemblyError):
            solidify_coincident_shells(
                asset.vertices,
                asset.faces,
                asset.colors,
                require_positive_volume=False,
                allow_unmatched_boundary_edges=True,
            )

        prepared = prepare_geometry(asset, settings)
        repair = prepared.assembly["repair_records"][0]
        filtered = repair["dominant_surface_filter"]
        self.assertEqual(repair["method"], "already_watertight")
        self.assertTrue(repair["identity"])
        self.assertEqual(filtered["removed_faces"], 3)
        self.assertEqual(filtered["dominant_selective_seam_method"], "already_watertight")
        self.assertEqual(filtered["output_faces"], repair["source_faces"])
        self.assertEqual(
            filtered["selective_seam_output_faces"],
            repair["output_faces"],
        )

        palette = PaletteSettings()
        colors = recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        original_mesh_quality = engine_module.mesh_quality
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine_module,
            "mesh_quality",
            side_effect=self._bounded_intersection_quality(
                original_mesh_quality
            ),
        ):
            destination = Path(temporary) / "identity-filter-warning.3mf"
            validation = write_3mf_atomic(
                destination,
                prepared,
                colors,
                settings.height_mm,
                palette,
            )
            self.assertTrue(destination.is_file())
            self.assertEqual(validation["self_intersection_warning_parts"], 1)
            self.assertEqual(
                validation["self_intersection_warning_policy"],
                "source_preserved_warning",
            )
            topology = validation["part_topologies"][0]
            self.assertTrue(
                topology["self_intersection_source_geometry_preserved"]
            )
            self.assertEqual(
                topology["self_intersection_policy"],
                "source_preserved_warning",
            )

    def test_indexed_dominant_warning_anchors_counts_to_serialized_geometry(
        self,
    ) -> None:
        asset = _dominant_surface_with_micro_junk_asset(indexed_main=True)
        settings = GeometrySettings(
            height_mm=20.0,
            target_faces=2_000,
            preview_faces=2_000,
            adjust_face_count=False,
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
        )
        prepared = prepare_geometry(asset, settings)
        repair = prepared.assembly["repair_records"][0]
        repair.update(
            {
                "source_vertices": 1,
                "output_vertices": 1,
                "source_faces": 1,
                "output_faces": 1,
                "final_vertex_count": 1,
                "final_face_count": 1,
            }
        )
        repair["final_validation"].update(
            {
                "source_vertices": 1,
                "output_vertices": 1,
                "source_faces": 1,
                "output_faces": 1,
            }
        )
        filtered = repair["dominant_surface_filter"]
        filtered.update(
            {
                "source_vertices": 2,
                "output_vertices": 1,
                "removed_vertices": 1,
                "source_faces": 2,
                "output_faces": 1,
                "removed_faces": 1,
                "component_count": 2,
                "kept_component_count": 1,
                "removed_component_count": 1,
                "selective_seam_output_vertices": 1,
                "selective_seam_output_faces": 1,
                "removed_components": [
                    dict(filtered["removed_components"][0])
                ],
            }
        )
        palette = PaletteSettings()
        colors = recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        original_mesh_quality = engine_module.mesh_quality
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine_module,
            "mesh_quality",
            side_effect=self._bounded_intersection_quality(
                original_mesh_quality
            ),
        ):
            destination = Path(temporary) / "identity-filter-invalid.3mf"
            with self.assertRaisesRegex(
                engine_module.EngineError,
                "policy=blocked",
            ):
                write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_indexed_dominant_source_warning_requires_preserved_geometry(
        self,
    ) -> None:
        settings = GeometrySettings(
            height_mm=20.0,
            target_faces=2_000,
            preview_faces=2_000,
            adjust_face_count=False,
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
        )
        original_mesh_quality = engine_module.mesh_quality
        for preserved_value in (False, None):
            with self.subTest(preserved_value=preserved_value):
                prepared = prepare_geometry(
                    _dominant_surface_with_micro_junk_asset(
                        indexed_main=True
                    ),
                    settings,
                )
                repair = prepared.assembly["repair_records"][0]
                if preserved_value is None:
                    repair.pop("source_triangle_geometry_preserved")
                else:
                    repair["source_triangle_geometry_preserved"] = (
                        preserved_value
                    )
                palette = PaletteSettings()
                colors = recolor_level(
                    prepared.final,
                    settings.height_mm,
                    ToneSettings(smoothing=False),
                    palette,
                )
                with tempfile.TemporaryDirectory() as temporary, patch.object(
                    engine_module,
                    "mesh_quality",
                    side_effect=self._bounded_intersection_quality(
                        original_mesh_quality
                    ),
                ):
                    destination = (
                        Path(temporary) / "identity-filter-no-ancestry.3mf"
                    )
                    with self.assertRaisesRegex(
                        engine_module.EngineError,
                        "policy=blocked",
                    ):
                        write_3mf_atomic(
                            destination,
                            prepared,
                            colors,
                            settings.height_mm,
                            palette,
                        )
                    self.assertFalse(destination.exists())

    def test_plain_already_watertight_record_does_not_gain_warning_policy(
        self,
    ) -> None:
        asset = _indexed_watertight_surface_asset()
        settings = GeometrySettings(
            height_mm=20.0,
            target_faces=2_000,
            preview_faces=2_000,
            adjust_face_count=False,
            min_component_faces=0,
            solidify_parts=True,
        )
        prepared = prepare_geometry(asset, settings)
        repair = prepared.assembly["repair_records"][0]
        self.assertEqual(repair["method"], "already_watertight")
        self.assertNotIn("dominant_surface_filter", repair)
        palette = PaletteSettings()
        colors = recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        original_mesh_quality = engine_module.mesh_quality
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine_module,
            "mesh_quality",
            side_effect=self._bounded_intersection_quality(
                original_mesh_quality
            ),
        ):
            destination = Path(temporary) / "plain-identity-blocked.3mf"
            with self.assertRaisesRegex(
                engine_module.EngineError,
                "policy=blocked",
            ):
                write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())

    def test_dominant_surface_filter_preserves_interior_coincident_edge(
        self,
    ) -> None:
        asset = _dominant_surface_with_interior_coincident_edge_asset()

        with self.assertRaises(AssemblyError):
            solidify_coincident_shells(
                asset.vertices,
                asset.faces,
                asset.colors,
                require_positive_volume=False,
                allow_unmatched_boundary_edges=True,
            )

        prepared = prepare_geometry(
            asset,
            GeometrySettings(
                height_mm=20.0,
                target_faces=2_000,
                preview_faces=2_000,
                adjust_face_count=False,
                min_component_faces=0,
                solidify_parts=True,
                repair_unmatched_boundaries=True,
            ),
        )

        self.assertTrue(prepared.topology["watertight"])
        self.assertEqual(len(prepared.final.faces), 1_280)
        self.assertEqual(prepared.removed_faces, 3)
        repair = prepared.assembly["repair_records"][0]
        filtered = repair["dominant_surface_filter"]
        self.assertFalse(filtered["dominant_exact_position_closed"])
        self.assertTrue(filtered["dominant_selective_seam_closed"])
        self.assertEqual(filtered["removed_faces"], 3)
        self.assertEqual(
            [
                item["classification"]
                for item in filtered["removed_components"]
            ],
            ["open_micro_fragment"] * 3,
        )

    def test_dominant_surface_filter_bounds_inverted_containment_work(
        self,
    ) -> None:
        asset = _dominant_surface_with_inverted_shells_asset()

        retained_vertices, retained_faces, retained_colors, record, seam = (
            engine_module._filter_conservative_dominant_exact_position_surface(
                asset.vertices,
                asset.faces,
                asset.colors,
            )
        )

        self.assertEqual(len(retained_faces), 5_120)
        self.assertEqual(record["removed_faces"], 8)
        self.assertEqual(record["internal_inverted_component_count"], 2)
        self.assertTrue(seam["closed"])
        self.assertLessEqual(
            record["containment_triangle_ray_test_upper_bound"],
            record["containment_triangle_ray_test_budget"],
        )
        self.assertEqual(len(retained_vertices), len(np.unique(retained_faces)))
        self.assertEqual(retained_colors.shape, retained_vertices.shape)

        with (
            patch.object(
                engine_module,
                "_DOMINANT_SURFACE_MAX_INVERTED_COMPONENTS",
                1,
            ),
            patch.object(
                engine_module,
                "_dominant_surface_contains_component",
                side_effect=AssertionError("containment ran before count guard"),
            ) as contains,
        ):
            with self.assertRaisesRegex(AssemblyError, "候補数が安全上限"):
                engine_module._filter_conservative_dominant_exact_position_surface(
                    asset.vertices,
                    asset.faces,
                    asset.colors,
                )
        contains.assert_not_called()

        with (
            patch.object(
                engine_module,
                "_DOMINANT_SURFACE_MAX_CONTAINMENT_TRIANGLE_RAY_TESTS",
                1,
            ),
            patch.object(
                engine_module,
                "_dominant_surface_contains_component",
                side_effect=AssertionError("containment ran before work guard"),
            ) as contains,
        ):
            with self.assertRaisesRegex(AssemblyError, "包含判定量が安全上限"):
                engine_module._filter_conservative_dominant_exact_position_surface(
                    asset.vertices,
                    asset.faces,
                    asset.colors,
                )
        contains.assert_not_called()

    def test_dominant_surface_filter_keeps_intentional_positive_solid(
        self,
    ) -> None:
        asset = _dominant_surface_with_micro_junk_asset(
            include_positive_solid=True,
        )

        # Same-direction micro debris makes the ordinary seam proof fail, but
        # the fallback must not discard a second closed positive-volume body.
        with self.assertRaises(AssemblyError):
            solidify_coincident_shells(
                asset.vertices,
                asset.faces,
                asset.colors,
                require_positive_volume=False,
                allow_unmatched_boundary_edges=True,
            )
        with self.assertRaisesRegex(
            EngineError,
            "正体積の独立表面",
        ):
            prepare_geometry(
                asset,
                GeometrySettings(
                    height_mm=20.0,
                    target_faces=2_000,
                    preview_faces=2_000,
                    adjust_face_count=False,
                    min_component_faces=0,
                    solidify_parts=True,
                    repair_unmatched_boundaries=True,
                ),
            )

    def test_large_glb_metadata_requires_reduction_on_every_processing_pass(
        self,
    ) -> None:
        vertices, faces, colors = _tetrahedron()
        asset = _face_soup_asset(vertices, faces, colors)
        asset.import_metadata = {
            "schema": "obj-adjuster.gltf-import.v1",
            "large_source_reduction_required": True,
            "source_triangle_workload": 5_000_000,
            "maximum_final_faces": 450_000,
        }

        for adjust, target in ((False, 450_000), (True, 450_001)):
            with self.subTest(adjust=adjust, target=target):
                with self.assertRaisesRegex(EngineError, "450,000"):
                    prepare_geometry(
                        asset,
                        GeometrySettings(
                            adjust_face_count=adjust,
                            target_faces=target,
                            preview_faces=1_000,
                            solidify_parts=True,
                        ),
                    )

        asset.import_metadata["maximum_final_faces"] = 900_000
        with self.assertRaisesRegex(EngineError, "450,000"):
            prepare_geometry(
                asset,
                GeometrySettings(
                    adjust_face_count=True,
                    target_faces=450_001,
                    preview_faces=1_000,
                    solidify_parts=True,
                ),
            )

    def test_live_large_source_guard_does_not_depend_on_extension(self) -> None:
        vertices, faces, colors = _tetrahedron()
        asset = _face_soup_asset(vertices, faces, colors)
        asset.import_metadata = {
            "schema": "obj-adjuster.gltf-import.v1",
            "large_source_reduction_required": False,
        }
        asset.path = Path("renamed_large_snapshot.obj")
        with (
            patch.object(engine_module, "_HARD_GLTF_NORMAL_SOURCE_FACE_LIMIT", 3),
            self.assertRaisesRegex(
                EngineError,
                "大規模モデル（入力 4 面）.*450,000",
            ),
        ):
            prepare_geometry(
                asset,
                GeometrySettings(
                    adjust_face_count=True,
                    target_faces=450_001,
                    preview_faces=1_000,
                    solidify_parts=True,
                ),
            )

    def test_disconnected_closed_bodies_are_oriented_outward_independently(
        self,
    ) -> None:
        first = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
        second = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
        second.apply_translation([4.0, 0.0, 0.0])
        vertices = np.vstack((first.vertices, second.vertices)).astype(np.float64)
        faces = np.vstack(
            (
                first.faces,
                second.faces[:, [0, 2, 1]] + len(first.vertices),
            )
        ).astype(np.int32)
        source_triangles = np.sort(faces, axis=1)

        oriented, record = _orient_watertight_bodies_positive(vertices, faces)

        np.testing.assert_array_equal(np.sort(oriented, axis=1), source_triangles)
        self.assertEqual(record["changed_face_winding_count"], len(second.faces))
        self.assertTrue(record["face_count_preserved"])
        result = trimesh.Trimesh(vertices=vertices, faces=oriented, process=False)
        bodies = list(result.split(only_watertight=False))
        self.assertEqual(len(bodies), 2)
        self.assertTrue(all(body.is_volume for body in bodies))
        self.assertTrue(all(float(body.volume) > 0.0 for body in bodies))

    def test_prepare_geometry_orients_mixed_closed_bodies_before_final_check(
        self,
    ) -> None:
        first = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
        second = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
        second.apply_translation([4.0, 0.0, 0.0])
        vertices = np.vstack((first.vertices, second.vertices)).astype(np.float64)
        faces = np.vstack(
            (
                first.faces,
                second.faces[:, [0, 2, 1]] + len(first.vertices),
            )
        ).astype(np.int32)
        colors = np.tile([[0.4, 0.5, 0.6]], (len(vertices), 1))
        asset = _face_soup_asset(vertices, faces, colors)

        prepared = prepare_geometry(
            asset,
            GeometrySettings(
                adjust_face_count=False,
                preview_faces=1_000,
                solidify_parts=True,
            ),
        )

        self.assertTrue(prepared.topology["watertight"])
        self.assertEqual(prepared.topology["inconsistent_winding_edges"], 0)
        self.assertGreater(
            prepared.assembly["repair_records"][0]["final_orientation"][
                "changed_face_winding_count"
            ],
            0,
        )

    def test_preclean_weld_defers_positive_volume_until_tiny_islands_are_removed(
        self,
    ) -> None:
        main = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
        main_vertices = np.asarray(main.vertices, dtype=np.float64)
        main_faces = np.asarray(main.faces, dtype=np.int32)
        tetra_vertices, tetra_faces, _tetra_colors = _tetrahedron()
        tiny_vertices = tetra_vertices * 0.01 + np.asarray([3.0, 0.0, 0.0])
        # A small source island may be closed but inward-wound.  Component
        # cleanup will remove it; rejecting it before that cleanup makes a
        # safe weld-first/QEM-second pipeline impossible on real Hi3D data.
        tiny_faces = tetra_faces[:, [0, 2, 1]] + len(main_vertices)
        vertices = np.vstack((main_vertices, tiny_vertices))
        faces = np.vstack((main_faces, tiny_faces)).astype(np.int32)
        colors = np.clip((vertices - vertices.min(axis=0)) / 4.0, 0.0, 1.0)
        asset = _face_soup_asset(vertices, faces, colors)

        prepared = prepare_geometry(
            asset,
            GeometrySettings(
                height_mm=50.0,
                target_faces=1_000,
                preview_faces=1_000,
                adjust_face_count=False,
                min_component_faces=5,
                solidify_parts=True,
            ),
        )

        self.assertEqual(prepared.removed_faces, 4)
        self.assertEqual(len(prepared.final.faces), len(main_faces))
        self.assertTrue(prepared.topology["watertight"])
        quality = trimesh.Trimesh(
            vertices=prepared.final.vertices_unit,
            faces=prepared.final.faces,
            process=False,
        )
        self.assertEqual(quality.body_count, 1)
        self.assertTrue(quality.is_volume)

    def test_one_glb_primitive_closes_as_one_part_and_writes_strict_3mf(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = load_gltf_asset(_write_uv_seamed_tetra_glb(root))

            self.assertFalse(asset.has_explicit_parts)
            self.assertEqual(len(asset.part_names), 1)
            self.assertFalse(
                edge_topology(asset.faces, len(asset.vertices))["watertight"]
            )

            settings = GeometrySettings(
                height_mm=20.0,
                target_faces=1_000,
                preview_faces=1_000,
                adjust_face_count=False,
                min_component_faces=0,
                solidify_parts=True,
            )
            prepared = prepare_geometry(asset, settings)

            self.assertTrue(prepared.topology["watertight"])
            self.assertEqual(len(prepared.final.faces), 4)
            self.assertEqual(len(prepared.final.part_names), 1)
            self.assertEqual(
                prepared.assembly["repair_method"],
                "coincident_vertex_seam_weld",
            )
            self.assertEqual(
                int(
                    np.count_nonzero(
                        prepared.final.areas_unit <= 1.0e-16
                    )
                ),
                0,
            )

            palette = PaletteSettings()
            result = recolor_level(
                prepared.final,
                settings.height_mm,
                ToneSettings(smoothing=False),
                palette,
            )
            destination = root / "single-logical-part.3mf"
            validation = write_3mf_atomic(
                destination,
                prepared,
                result,
                settings.height_mm,
                palette,
            )

            self.assertTrue(destination.is_file())
            self.assertEqual(validation["parts"], 1)
            self.assertEqual(validation["faces"], 4)
            self.assertEqual(validation["watertight_parts"], 1)
            self.assertEqual(validation["validated_solid_parts"], 1)
            self.assertEqual(
                validation["part_topologies"][0]["degenerate_faces"], 0
            )

    def test_seams_are_welded_before_optional_qem_decimation(self) -> None:
        vertices, faces, colors = _tetrahedron()
        asset = _face_soup_asset(vertices, faces, colors)

        def identity_clean(local_vertices, local_faces, local_colors, _minimum):
            local_topology = edge_topology(local_faces, len(local_vertices))
            return (
                np.asarray(local_vertices, dtype=np.float64).copy(),
                np.asarray(local_faces, dtype=np.int32).copy(),
                np.asarray(local_colors, dtype=np.float64).copy(),
                {
                    "orientation_method": "test_identity",
                    "orientation_fallback_used": False,
                    "component_filter_failed": False,
                    "component_filter_reverted": False,
                    "topology_before_orientation": local_topology,
                    "topology_after_orientation": local_topology,
                },
            )

        original_simplify = engine_module._simplify_mesh
        qem_input_watertight: list[bool] = []

        def checked_simplify(
            local_vertices,
            local_faces,
            local_colors,
            target,
            *args,
            **kwargs,
        ):
            closed = bool(
                edge_topology(local_faces, len(local_vertices))["watertight"]
            )
            qem_input_watertight.append(closed)
            if not closed:
                raise AssertionError(
                    "QEM received open UV seams before exact-coordinate weld"
                )
            return original_simplify(
                local_vertices,
                local_faces,
                local_colors,
                target,
                *args,
                **kwargs,
            )

        with patch(
            "spectrum_mapper.engine._clean_part", side_effect=identity_clean
        ), patch(
            "spectrum_mapper.engine._simplify_mesh",
            side_effect=checked_simplify,
        ):
            prepared = prepare_geometry(
                asset,
                GeometrySettings(
                    height_mm=50.0,
                    target_faces=1_000,
                    preview_faces=1_000,
                    adjust_face_count=True,
                    min_component_faces=0,
                    solidify_parts=True,
                ),
            )

        # If QEM runs on the open per-face soup first, opposite sides of each
        # seam move independently and an exact-coordinate weld can no longer
        # recover the original closed surface.
        self.assertTrue(qem_input_watertight)
        self.assertTrue(all(qem_input_watertight))
        self.assertEqual(len(prepared.final.faces), 4)
        self.assertTrue(prepared.topology["watertight"])
        quality = trimesh.Trimesh(
            vertices=prepared.final.vertices_unit,
            faces=prepared.final.faces,
            process=False,
        )
        self.assertEqual(quality.body_count, 1)
        self.assertTrue(quality.is_winding_consistent)
        self.assertTrue(quality.is_volume)
        self.assertEqual(
            int(
                np.count_nonzero(
                    prepared.final.areas_unit <= 1.0e-16
                )
            ),
            0,
        )

    def test_direct_writer_blocks_an_open_model_without_assembly_flags(
        self,
    ) -> None:
        vertices, faces, colors = _tetrahedron()
        open_asset = _face_soup_asset(vertices, faces[:-1], colors)
        settings = GeometrySettings(
            height_mm=20.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            min_component_faces=0,
            solidify_parts=False,
        )
        prepared = prepare_geometry(open_asset, settings)
        self.assertFalse(prepared.assembly)
        self.assertFalse(prepared.topology["watertight"])
        palette = PaletteSettings()
        result = recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "open-must-not-write.3mf"
            with self.assertRaisesRegex(
                engine_module.EngineError, "閉立体検証"
            ):
                write_3mf_atomic(
                    destination,
                    prepared,
                    result,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())


class BoundedSelfIntersectionPolicyTests(unittest.TestCase):
    @staticmethod
    def _prepare():
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            min_component_faces=0,
            solidify_parts=True,
        )
        prepared = prepare_geometry(
            _intersecting_closed_bodies_asset(), settings
        )
        palette = PaletteSettings()
        colors = recolor_level(
            prepared.final,
            settings.height_mm,
            ToneSettings(smoothing=False),
            palette,
        )
        return settings, prepared, palette, colors

    def test_small_source_preserved_intersection_is_warning_only(self) -> None:
        settings, prepared, palette, colors = self._prepare()
        repair = prepared.assembly["repair_records"][0]

        self.assertTrue(prepared.assembly["single_mesh_generic"])
        self.assertEqual(prepared.assembly["body_count"], 2)
        self.assertEqual(repair["body_count"], 2)
        self.assertEqual(repair["final_validation"]["body_count"], 2)
        self.assertTrue(repair["boundary_pairing_proven"])
        self.assertTrue(repair["source_triangle_geometry_preserved"])
        self.assertFalse(repair["simplification_applied"])

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "source-preserved-warning.3mf"
            validation = write_3mf_atomic(
                destination,
                prepared,
                colors,
                settings.height_mm,
                palette,
            )

            self.assertTrue(destination.is_file())
            self.assertEqual(validation["parts"], 1)
            self.assertEqual(validation["validated_solid_parts"], 1)
            self.assertEqual(validation["self_intersection_warning_parts"], 1)
            self.assertEqual(
                validation["self_intersection_warning_policy"],
                "source_preserved_warning",
            )
            self.assertGreater(
                validation["self_intersection_warning_faces"], 0
            )
            self.assertGreater(
                validation["self_intersection_warning_area"], 0.0
            )
            topology = validation["part_topologies"][0]
            self.assertEqual(topology["body_count"], 2)
            self.assertGreater(topology["self_intersecting_faces"], 0)
            self.assertLessEqual(
                topology["self_intersecting_area_fraction"], 1.0e-4
            )
            self.assertEqual(
                topology["self_intersection_policy"],
                "source_preserved_warning",
            )

    def test_same_bounded_intersection_is_warning_after_qem_provenance(
        self,
    ) -> None:
        settings, prepared, palette, colors = self._prepare()
        repair = prepared.assembly["repair_records"][0]
        # Model the provenance written after a QEM pass.  It must not be
        # described as source-preserved, but the same bounded intersection is
        # accepted as an explicit QEM warning after all hard solid checks pass.
        repair["simplification_applied"] = True
        repair["source_triangle_geometry_preserved"] = False

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "qem-bounded-warning.3mf"
            validation = write_3mf_atomic(
                destination,
                prepared,
                colors,
                settings.height_mm,
                palette,
            )
            self.assertTrue(destination.is_file())
            self.assertEqual(validation["validated_solid_parts"], 1)
            self.assertEqual(validation["self_intersection_warning_parts"], 1)
            self.assertEqual(
                validation["self_intersection_warning_policy"],
                "bounded_qem_warning",
            )
            topology = validation["part_topologies"][0]
            self.assertFalse(
                topology["self_intersection_source_geometry_preserved"]
            )
            self.assertEqual(
                topology["self_intersection_policy"],
                "bounded_qem_warning",
            )

            bundle = export_bundle(
                prepared,
                AppSettings(
                    geometry=settings,
                    tone=ToneSettings(smoothing=False),
                    palette=palette,
                ),
                Path(temporary) / "qem-warning-bundle.3mf",
                include_vertex_obj=False,
            )
            report = json.loads(
                bundle.report_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual(
                report["self_intersection_warning"]["policy"],
                "bounded_qem_warning",
            )
            self.assertTrue(
                report["self_intersection_warning"][
                    "orca_preview_required"
                ]
            )
            guide = bundle.guide_path.read_text(encoding="utf-8-sig")
            self.assertIn("【微小自己交差の確認】", guide)
            self.assertIn("スライスプレビュー", guide)

    def test_intersection_over_area_limit_remains_blocked(self) -> None:
        settings, prepared, palette, colors = self._prepare()
        original_mesh_quality = engine_module.mesh_quality

        def oversized_intersection(*args, **kwargs):
            quality = original_mesh_quality(*args, **kwargs)
            quality["self_intersecting_faces"] = 1
            quality["self_intersecting_area"] = 1.0
            quality["self_intersecting_area_fraction"] = 1.0e-3
            quality["maximum_self_intersecting_face_area"] = 1.0
            return quality

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine_module,
            "mesh_quality",
            side_effect=oversized_intersection,
        ):
            destination = Path(temporary) / "oversized-blocked.3mf"
            with self.assertRaisesRegex(
                engine_module.EngineError, "self_intersections=1"
            ):
                write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.height_mm,
                    palette,
                )
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
