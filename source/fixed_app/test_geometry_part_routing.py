from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import engine
from spectrum_mapper.models import AppSettings, GeometrySettings, ObjAsset


def _asset(
    *,
    vertices: np.ndarray,
    faces: np.ndarray,
    face_part_ids: np.ndarray,
    part_names: tuple[str, ...],
    marker_kind: str | None,
    explicit: bool,
) -> ObjAsset:
    colors = np.full((len(vertices), 3), 0.5, dtype=np.float32)
    part_face_counts = tuple(
        int(value)
        for value in np.bincount(
            face_part_ids, minlength=len(part_names)
        )
    )
    part_vertex_counts = tuple(
        int(len(np.unique(faces[face_part_ids == part_id])))
        for part_id in range(len(part_names))
    )
    return ObjAsset(
        path=Path("routing.obj"),
        sha256="0" * 64,
        file_size=1,
        vertices=np.asarray(vertices, dtype=np.float32),
        colors=colors,
        faces=np.asarray(faces, dtype=np.int32),
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=[],
        part_names=part_names,
        part_keys=tuple(
            f"{index}:{name}" for index, name in enumerate(part_names)
        ),
        face_part_ids=np.asarray(face_part_ids, dtype=np.int32),
        part_face_counts=part_face_counts,
        part_vertex_counts=part_vertex_counts,
        part_marker_kind=marker_kind,
        has_explicit_parts=explicit,
    )


def _open_multipart_asset() -> ObjAsset:
    return _asset(
        vertices=np.asarray(
            [
                [0, 0, 0],
                [1, 0, 0],
                [0, 1, 0],
                [2, 0, 0],
                [3, 0, 0],
                [2, 1, 0],
            ]
        ),
        faces=np.asarray([[0, 1, 2], [3, 4, 5]]),
        face_part_ids=np.asarray([0, 1]),
        part_names=("body", "arm"),
        marker_kind="o",
        explicit=True,
    )


def _watertight_multipart_asset() -> ObjAsset:
    tetra_faces = np.asarray(
        [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]],
        dtype=np.int32,
    )
    vertices = np.asarray(
        [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
            [3, 0, 0],
            [4, 0, 0],
            [3, 1, 0],
            [3, 0, 1],
        ]
    )
    return _asset(
        vertices=vertices,
        faces=np.vstack((tetra_faces, tetra_faces + 4)),
        face_part_ids=np.asarray([0] * 4 + [1] * 4),
        part_names=("body", "accessory"),
        marker_kind="g",
        explicit=True,
    )


def _matching_open_box_asset() -> ObjAsset:
    def open_box(
        z_min: float, z_max: float, omitted_side: str
    ) -> tuple[np.ndarray, np.ndarray]:
        vertices = np.asarray(
            [
                [-0.2, -0.15, z_min],
                [0.2, -0.15, z_min],
                [0.2, 0.15, z_min],
                [-0.2, 0.15, z_min],
                [-0.2, -0.15, z_max],
                [0.2, -0.15, z_max],
                [0.2, 0.15, z_max],
                [-0.2, 0.15, z_max],
            ],
            dtype=np.float64,
        )
        sides = {
            "zmin": ((0, 2, 1), (0, 3, 2)),
            "zmax": ((4, 5, 6), (4, 6, 7)),
            "ymin": ((0, 1, 5), (0, 5, 4)),
            "xmax": ((1, 2, 6), (1, 6, 5)),
            "ymax": ((2, 3, 7), (2, 7, 6)),
            "xmin": ((3, 0, 4), (3, 4, 7)),
        }
        faces = np.asarray(
            [
                triangle
                for side, triangles in sides.items()
                if side != omitted_side
                for triangle in triangles
            ],
            dtype=np.int32,
        )
        return vertices, faces

    lower_vertices, lower_faces = open_box(-0.2, 0.0, "zmax")
    upper_vertices, upper_faces = open_box(0.0, 0.2, "zmin")
    vertices = np.vstack((lower_vertices, upper_vertices))
    faces = np.vstack((lower_faces, upper_faces + len(lower_vertices)))
    return _asset(
        vertices=vertices,
        faces=faces,
        face_part_ids=np.asarray(
            [0] * len(lower_faces) + [1] * len(upper_faces),
            dtype=np.int32,
        ),
        part_names=("lower body", "upper body"),
        marker_kind="o",
        explicit=True,
    )


def _tiny_unmatched_hole_asset(*, global_height: float = 100.0) -> ObjAsset:
    tetra_faces = np.asarray(
        [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]],
        dtype=np.int32,
    )
    vertices = np.asarray(
        [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
            [10, 0, 0],
            [12, 0, 0],
            [10, 2, 0],
            [10, 0, global_height],
        ],
        dtype=np.float64,
    )
    # The first tetrahedron is missing only its bottom triangle.  The second
    # closed tetrahedron establishes model height so that the opening is about
    # 1.414 mm when global_height=100 and output height is 100 mm.
    asset = _asset(
        vertices=vertices,
        faces=np.vstack((tetra_faces[1:], tetra_faces + 4)),
        face_part_ids=np.asarray([0] * 3 + [1] * 4, dtype=np.int32),
        part_names=("tiny hole", "closed body"),
        marker_kind="o",
        explicit=True,
    )
    asset.colors[:4] = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)
    asset.colors[4:] = np.asarray([0.8, 0.7, 0.6], dtype=np.float32)
    return asset


def _single_tetra_asset(marker_kind: str | None) -> ObjAsset:
    return _asset(
        vertices=np.asarray(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
        ),
        faces=np.asarray(
            [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]]
        ),
        face_part_ids=np.zeros(4, dtype=np.int32),
        part_names=(("OBJ whole",) if marker_kind is None else ("named",)),
        marker_kind=marker_kind,
        explicit=False,
    )


def _nonmanifold_single_asset() -> ObjAsset:
    """Three coloured triangles sharing one edge."""

    asset = _asset(
        vertices=np.asarray(
            [
                [0, 0, 0],
                [1, 0, 0],
                [0, 1, 0],
                [0, -1, 0],
                [0, 0, 1],
            ],
            dtype=np.float64,
        ),
        faces=np.asarray(
            [[0, 1, 2], [1, 0, 3], [0, 1, 4]], dtype=np.int32
        ),
        face_part_ids=np.zeros(3, dtype=np.int32),
        part_names=("touching sheets",),
        marker_kind="o",
        explicit=False,
    )
    asset.colors[:] = np.asarray(
        [
            [0.1, 0.2, 0.3],
            [0.2, 0.3, 0.4],
            [0.3, 0.4, 0.5],
            [0.4, 0.5, 0.6],
            [0.5, 0.6, 0.7],
        ],
        dtype=np.float32,
    )
    return asset


class GeometryPartRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        # Deliberately retain old solidify/split flags: they must not turn a
        # markerless or single-marker OBJ into a generated multipart model.
        self.settings = GeometrySettings(
            target_faces=1_000,
            preview_faces=1_000,
            min_component_faces=0,
            preserve_parts=True,
            solidify_parts=True,
            split_enabled=True,
        )

    def test_explicit_open_multipart_routes_to_partition_reconstruction(self) -> None:
        sentinel = object()
        asset = _open_multipart_asset()
        with patch.object(
            engine, "_prepare_geometry_parts", return_value=sentinel
        ) as routed:
            result = engine.prepare_geometry(asset, self.settings)

        self.assertIs(result, sentinel)
        routed.assert_called_once_with(asset, self.settings, None)

    def test_explicit_watertight_multipart_uses_the_same_part_preserving_route(self) -> None:
        sentinel = object()
        asset = _watertight_multipart_asset()
        with patch.object(
            engine, "_prepare_geometry_parts", return_value=sentinel
        ) as routed:
            result = engine.prepare_geometry(asset, self.settings)

        self.assertIs(result, sentinel)
        routed.assert_called_once_with(asset, self.settings, None)

    def test_geometry_defaults_to_raw_multipart_without_unmatched_repair(self) -> None:
        settings = GeometrySettings()

        self.assertFalse(settings.solidify_parts)
        self.assertFalse(settings.repair_unmatched_boundaries)

    def test_single_mesh_keeps_clean_face_count_when_adjustment_is_off(self) -> None:
        asset = _single_tetra_asset(None)
        settings = GeometrySettings(
            target_faces=1,
            preview_faces=1_000,
            min_component_faces=0,
            adjust_face_count=False,
        )

        with patch.object(
            engine, "_simplify_mesh", wraps=engine._simplify_mesh
        ) as simplify:
            result = engine.prepare_geometry(asset, settings)

        self.assertEqual(len(result.final.faces), result.clean_face_count)
        self.assertEqual(simplify.call_args_list[0].args[3], result.clean_face_count)

    def test_nonmanifold_cleaning_is_lossless_and_reports_source_winding(self) -> None:
        asset = _nonmanifold_single_asset()

        vertices, faces, colors, diagnostic = engine._clean_part(
            asset.vertices,
            asset.faces,
            asset.colors,
            min_component_faces=0,
        )

        # Fail-soft orientation must not trade an import exception for a
        # hidden face deletion, vertex remap, colour transfer, or face reorder.
        np.testing.assert_array_equal(vertices, asset.vertices)
        np.testing.assert_array_equal(faces, asset.faces)
        np.testing.assert_array_equal(colors, asset.colors)
        self.assertEqual(len(faces), asset.original_face_count)
        self.assertTrue(diagnostic["orientation_fallback_used"])
        self.assertEqual(
            diagnostic["orientation_method"], "source_winding_preserved"
        )
        self.assertTrue(diagnostic["orientation_face_count_preserved"])
        self.assertEqual(
            diagnostic["topology_before_orientation"]["nonmanifold_edges"],
            1,
        )
        json.dumps(diagnostic, ensure_ascii=False)

    def test_single_mesh_nonmanifold_orientation_no_longer_aborts_import(self) -> None:
        asset = _nonmanifold_single_asset()
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            up_axis="Z",
            min_component_faces=0,
        )

        result = engine.prepare_geometry(asset, settings)

        self.assertEqual(len(result.final.faces), len(asset.faces))
        self.assertEqual(result.final.part_names, asset.part_names)
        self.assertEqual(result.final.part_keys, asset.part_keys)
        np.testing.assert_array_equal(
            result.final.vertex_colors, asset.colors
        )
        self.assertEqual(result.topology["nonmanifold_edges"], 1)
        self.assertIn("cleaning_diagnostics", result.assembly)
        diagnostic = result.assembly["cleaning_diagnostics"][0]
        self.assertEqual(
            diagnostic["orientation_method"], "source_winding_preserved"
        )
        self.assertTrue(any("面順序" in value for value in result.warnings))
        json.dumps(result.assembly, ensure_ascii=False)

    def test_tiny_named_part_is_not_deleted_by_component_threshold(self) -> None:
        vertices = np.asarray(
            [[0, 0, 0], [1, 0, 0], [0, 1, 1]], dtype=np.float64
        )
        faces = np.asarray([[0, 1, 2]], dtype=np.int32)
        colors = np.asarray(
            [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]],
            dtype=np.float64,
        )

        clean_vertices, clean_faces, clean_colors, diagnostic = (
            engine._clean_part(
                vertices, faces, colors, min_component_faces=25
            )
        )

        self.assertEqual(len(clean_faces), 1)
        np.testing.assert_array_equal(clean_vertices, vertices)
        np.testing.assert_array_equal(clean_colors, colors)
        self.assertTrue(diagnostic["component_filter_reverted"])
        self.assertEqual(diagnostic["removed_faces"], 0)

    def test_component_cleanup_preserves_coincident_vertices_with_distinct_rgb(self) -> None:
        vertices = np.asarray(
            [
                [0, 0, 0],
                [0, 0, 0],
                [1, 0, 0],
                [0, 1, 0],
                [5, 0, 0],
                [6, 0, 0],
                [5, 1, 0],
            ],
            dtype=np.float64,
        )
        faces = np.asarray(
            [[0, 2, 3], [1, 3, 2], [4, 5, 6]], dtype=np.int32
        )
        colors = np.asarray(
            [
                [0.99123, 0.01234, 0.12345],
                [0.01111, 0.22222, 0.98765],
                [0.1234, 0.3456, 0.5678],
                [0.9, 0.8, 0.7],
                [0.1, 0.2, 0.3],
                [0.4, 0.5, 0.6],
                [0.7, 0.8, 0.9],
            ],
            dtype=np.float64,
        )

        clean_vertices, clean_faces, clean_colors, diagnostic = (
            engine._clean_part(
                vertices, faces, colors, min_component_faces=2
            )
        )

        # The one-face island is removed, but the retained coincident vertices
        # must not be merged by a coordinate-only RGB transfer.  Their source
        # precision and the surviving face sequence both remain exact.
        np.testing.assert_array_equal(clean_vertices, vertices[:4])
        np.testing.assert_array_equal(clean_faces, faces[:2])
        np.testing.assert_array_equal(clean_colors, colors[:4])
        self.assertEqual(diagnostic["removed_faces"], 1)
        self.assertEqual(diagnostic["removed_vertices"], 3)

    def test_unexpected_orientation_failure_is_not_hidden_as_fallback(self) -> None:
        asset = _single_tetra_asset(None)

        with patch.object(
            engine.ml.MeshSet,
            "apply_filter",
            side_effect=MemoryError("simulated allocation failure"),
        ):
            with self.assertRaisesRegex(MemoryError, "allocation"):
                engine._clean_part(
                    asset.vertices,
                    asset.faces,
                    asset.colors,
                    min_component_faces=0,
                )

    def test_pymeshlab_orientability_rejection_uses_lossless_fallback(self) -> None:
        asset = _single_tetra_asset(None)

        with patch.object(
            engine.ml.MeshSet,
            "apply_filter",
            side_effect=engine.ml.PyMeshLabException(
                "simulated orientability rejection"
            ),
        ):
            vertices, faces, colors, diagnostic = engine._clean_part(
                asset.vertices,
                asset.faces,
                asset.colors,
                min_component_faces=0,
            )

        np.testing.assert_array_equal(vertices, asset.vertices)
        np.testing.assert_array_equal(faces, asset.faces)
        np.testing.assert_array_equal(colors, asset.colors)
        self.assertTrue(diagnostic["orientation_fallback_used"])
        self.assertIn(
            "orientability rejection",
            diagnostic["direct_orientation_error"],
        )

    def test_multipart_allocator_uses_clean_total_when_adjustment_is_off(self) -> None:
        asset = _watertight_multipart_asset()
        settings = GeometrySettings(
            target_faces=1,
            preview_faces=1_000,
            min_component_faces=0,
            adjust_face_count=False,
            solidify_parts=False,
        )

        with patch.object(
            engine,
            "_allocate_part_targets",
            wraps=engine._allocate_part_targets,
        ) as allocate:
            result = engine.prepare_geometry(asset, settings)

        self.assertEqual(len(result.final.faces), result.clean_face_count)
        self.assertEqual(allocate.call_args.args[1], result.clean_face_count)

    def test_multipart_nonmanifold_part_does_not_block_valid_part(self) -> None:
        bad = _nonmanifold_single_asset()
        tetra_vertices = np.asarray(
            [[3, 0, 0], [4, 0, 0], [3, 1, 0], [3, 0, 1]],
            dtype=np.float64,
        )
        tetra_faces = np.asarray(
            [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]],
            dtype=np.int32,
        )
        vertices = np.vstack((bad.vertices, tetra_vertices))
        faces = np.vstack((bad.faces, tetra_faces + len(bad.vertices)))
        asset = _asset(
            vertices=vertices,
            faces=faces,
            face_part_ids=np.asarray([0] * 3 + [1] * 4, dtype=np.int32),
            part_names=("touching sheets", "closed body"),
            marker_kind="o",
            explicit=True,
        )
        asset.colors[: len(bad.colors)] = bad.colors
        asset.colors[len(bad.colors) :] = np.asarray(
            [0.8, 0.7, 0.6], dtype=np.float32
        )
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            adjust_face_count=False,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=False,
        )

        result = engine.prepare_geometry(asset, settings)

        self.assertEqual(result.final.part_names, asset.part_names)
        self.assertEqual(result.final.part_keys, asset.part_keys)
        self.assertEqual(
            [
                int(np.count_nonzero(result.final.face_part_ids == part_id))
                for part_id in range(2)
            ],
            [3, 4],
        )
        self.assertEqual(len(result.final.faces), len(asset.faces))
        diagnostics = result.assembly["cleaning_diagnostics"]
        self.assertEqual(len(diagnostics), 2)
        self.assertTrue(diagnostics[0]["orientation_fallback_used"])
        self.assertFalse(diagnostics[1]["orientation_fallback_used"])
        self.assertEqual(diagnostics[0]["part_name"], "touching sheets")
        self.assertEqual(diagnostics[1]["part_name"], "closed body")
        self.assertTrue(
            all(item["orientation_face_count_preserved"] for item in diagnostics)
        )
        json.dumps(result.assembly, ensure_ascii=False)

    def test_explicit_watertight_parts_respect_raw_flag_and_keep_names(self) -> None:
        asset = _watertight_multipart_asset()
        settings = GeometrySettings(
            target_faces=1_000,
            preview_faces=1_000,
            min_component_faces=0,
            preserve_parts=False,
            solidify_parts=False,
            split_enabled=False,
        )

        result = engine.prepare_geometry(asset, settings)

        self.assertEqual(result.final.part_names, ("body", "accessory"))
        self.assertEqual(result.final.part_keys, ("0:body", "1:accessory"))
        self.assertEqual(set(result.final.face_part_ids.tolist()), {0, 1})
        self.assertFalse(result.assembly["solidify_parts"])
        self.assertEqual(result.assembly["repair_method"], "none")
        self.assertTrue(result.assembly["all_parts_watertight"])
        self.assertEqual(result.assembly["boundary_diagnostics"], [])

    def test_raw_open_multipart_returns_diagnostics_and_preserves_colours(self) -> None:
        asset = _tiny_unmatched_hole_asset()
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=False,
        )

        result = engine.prepare_geometry(asset, settings)

        self.assertFalse(result.topology["watertight"])
        self.assertEqual(result.final.part_names, asset.part_names)
        self.assertEqual(result.final.part_keys, asset.part_keys)
        self.assertEqual(set(result.final.face_part_ids.tolist()), {0, 1})
        self.assertFalse(result.assembly["solidify_parts"])
        self.assertEqual(result.assembly["unmatched_boundary_loop_count"], 1)
        self.assertEqual(
            result.assembly["repaired_unmatched_boundary_count"], 0
        )
        self.assertEqual(result.assembly["matched_boundary_face_ids"], [])
        self.assertEqual(len(result.assembly["boundary_diagnostics"]), 1)
        diagnostic = result.assembly["boundary_diagnostics"][0]
        self.assertEqual(diagnostic["part_name"], "tiny hole")
        self.assertFalse(diagnostic["matched"])
        self.assertFalse(diagnostic["repair_applied"])
        self.assertLess(diagnostic["span_mm"], 2.0)
        self.assertEqual(
            diagnostic["adjacent_final_face_ids"],
            result.assembly["unmatched_boundary_face_ids"],
        )
        self.assertTrue(diagnostic["adjacent_final_face_ids"])
        for face_id in diagnostic["adjacent_final_face_ids"]:
            self.assertGreaterEqual(face_id, 0)
            self.assertLess(face_id, len(result.final.faces))
        for part_id, expected in enumerate(
            ([0.1, 0.2, 0.3], [0.8, 0.7, 0.6])
        ):
            faces = result.final.faces[result.final.face_part_ids == part_id]
            used = np.unique(faces)
            np.testing.assert_allclose(
                result.final.vertex_colors[used],
                np.tile(np.asarray(expected), (len(used), 1)),
                atol=1.0 / 255.0 + 1e-6,
            )
        # Everything stored in assembly metadata must survive direct JSON
        # export to Metadata/tripo_assembly.json.
        json.dumps(result.assembly, ensure_ascii=False)

    def test_unmatched_boundary_still_stops_when_repair_is_disabled(self) -> None:
        asset = _tiny_unmatched_hole_asset()
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=False,
            auto_joints=False,
        )

        with self.assertRaisesRegex(engine.EngineError, "対応相手"):
            engine.prepare_geometry(asset, settings)

    def test_opt_in_repairs_only_tiny_planar_unmatched_boundary(self) -> None:
        asset = _tiny_unmatched_hole_asset()
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
            auto_joints=False,
        )

        result = engine.prepare_geometry(asset, settings)

        self.assertTrue(result.topology["watertight"])
        self.assertTrue(result.assembly["solidify_parts"])
        self.assertEqual(result.assembly["unmatched_boundary_loop_count"], 1)
        self.assertEqual(
            result.assembly["repaired_unmatched_boundary_count"], 1
        )
        self.assertTrue(result.assembly["unmatched_boundary_face_ids"])
        diagnostic = result.assembly["boundary_diagnostics"][0]
        self.assertFalse(diagnostic["matched"])
        self.assertTrue(diagnostic["repair_applied"])
        self.assertEqual(
            diagnostic["repair_method"], "strict_planar_local_cap"
        )
        local_record = result.assembly["repair_records"][0]
        self.assertEqual(
            local_record["method"],
            "strict_planar_unmatched_boundary_caps",
        )
        self.assertEqual(local_record["repaired_loop_count"], 1)
        self.assertTrue(
            any("局所修復" in warning for warning in result.warnings)
        )
        json.dumps(result.assembly, ensure_ascii=False)

    def test_opt_in_rejects_large_unmatched_boundary(self) -> None:
        asset = _tiny_unmatched_hole_asset(global_height=1.0)
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            up_axis="Z",
            min_component_faces=0,
            solidify_parts=True,
            repair_unmatched_boundaries=True,
            auto_joints=False,
        )

        with self.assertRaisesRegex(engine.EngineError, "最大幅"):
            engine.prepare_geometry(asset, settings)

    def test_open_partition_keeps_both_source_parts_after_solidification(self) -> None:
        asset = _matching_open_box_asset()
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            up_axis="Z",
            min_component_faces=0,
            preserve_parts=True,
            solidify_parts=True,
            # Automatic placement is a legacy opt-in.  New user workflows
            # keep it off so the joint position is selected in Manual Editing.
            auto_joints=True,
            split_enabled=False,
        )

        result = engine.prepare_geometry(asset, settings)

        self.assertEqual(result.final.part_names, asset.part_names)
        self.assertEqual(result.final.part_keys, asset.part_keys)
        self.assertEqual(result.part_names, asset.part_names)
        self.assertEqual(result.part_keys, asset.part_keys)
        self.assertEqual(len(result.part_stats), 2)
        self.assertEqual(set(result.final.face_part_ids.tolist()), {0, 1})
        self.assertEqual(
            result.assembly["repair_method"], "partitioned_shared_caps"
        )
        self.assertEqual(len(result.assembly["joint_records"]), 1)
        self.assertTrue(
            any("組立ジョイント" in warning for warning in result.warnings)
        )
        self.assertNotEqual(
            result.assembly["repair_method"], "matched_seam_weld"
        )
        self.assertFalse(
            any(key.startswith("assembly:welded") for key in result.part_keys)
        )
        self.assertEqual(result.assembly["unmatched_boundary_loop_count"], 0)
        self.assertEqual(result.assembly["unmatched_boundary_face_ids"], [])
        self.assertEqual(len(result.assembly["boundary_diagnostics"]), 2)
        self.assertTrue(
            all(
                record["matched"]
                for record in result.assembly["boundary_diagnostics"]
            )
        )
        self.assertTrue(result.assembly["matched_boundary_face_ids"])
        for face_id in result.assembly["matched_boundary_face_ids"]:
            self.assertGreaterEqual(face_id, 0)
            self.assertLess(face_id, len(result.final.faces))
        json.dumps(result.assembly, ensure_ascii=False)

        for part_id in range(2):
            part_faces_global = result.final.faces[
                result.final.face_part_ids == part_id
            ]
            used_vertices, inverse = np.unique(
                part_faces_global.reshape(-1), return_inverse=True
            )
            part_faces = inverse.reshape((-1, 3)).astype(np.int32)
            topology = engine.edge_topology(part_faces, len(used_vertices))
            self.assertTrue(topology["watertight"], topology)
            self.assertEqual(topology["boundary_edges"], 0)
            self.assertEqual(topology["nonmanifold_edges"], 0)

    def test_explicit_multipart_ignores_direct_legacy_plane_split_setting(self) -> None:
        asset = _matching_open_box_asset()
        settings = GeometrySettings(
            height_mm=100.0,
            target_faces=1_000,
            preview_faces=1_000,
            up_axis="Z",
            min_component_faces=0,
            preserve_parts=True,
            solidify_parts=True,
            split_enabled=True,
            split_axis="X",
            split_position_percent=25.0,
            split_target_part=0,
        )

        result = engine.prepare_geometry(asset, settings)

        self.assertEqual(result.final.part_names, asset.part_names)
        self.assertEqual(result.final.part_keys, asset.part_keys)
        self.assertEqual(len(result.part_stats), 2)
        self.assertEqual(set(result.final.face_part_ids.tolist()), {0, 1})
        self.assertEqual(
            result.assembly["repair_method"], "partitioned_shared_caps"
        )
        self.assertFalse(
            any(bool(stats.get("generated_by_split")) for stats in result.part_stats)
        )
        self.assertFalse(
            any("/cut:" in key for key in result.final.part_keys)
        )

    def test_markerless_and_single_markers_keep_the_legacy_single_mesh_path(self) -> None:
        for marker_kind in (None, "o", "g"):
            with self.subTest(marker_kind=marker_kind):
                asset = _single_tetra_asset(marker_kind)
                with patch.object(engine, "_prepare_geometry_parts") as routed:
                    result = engine.prepare_geometry(asset, self.settings)

                routed.assert_not_called()
                self.assertEqual(len(result.final.part_names), 1)
                self.assertEqual(result.final.face_part_ids.tolist(), [0] * 4)
                self.assertEqual(result.assembly, {})
                self.assertTrue(result.topology["watertight"])

    def test_old_saved_plane_split_flag_is_migrated_off(self) -> None:
        settings = AppSettings.from_dict(
            {
                "geometry": {
                    "split_enabled": True,
                    "split_axis": "X",
                    "split_position_percent": 37.5,
                    "auto_joints": True,
                }
            }
        )

        self.assertFalse(settings.geometry.split_enabled)
        self.assertEqual(settings.geometry.split_axis, "X")
        self.assertEqual(settings.geometry.split_position_percent, 37.5)
        self.assertTrue(settings.geometry.auto_joints)


if __name__ == "__main__":
    unittest.main(verbosity=2)
