from __future__ import annotations

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
    edge_topology,
    prepare_geometry,
    recolor_level,
    triangle_areas,
    write_3mf_atomic,
)
from spectrum_mapper.gltf_import import load_gltf_asset
from spectrum_mapper.models import (
    AppSettings,
    GeometrySettings,
    ObjAsset,
    PaletteSettings,
    ToneSettings,
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
