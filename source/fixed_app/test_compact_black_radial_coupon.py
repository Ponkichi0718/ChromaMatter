from __future__ import annotations

import hashlib
import importlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

from spectrum_mapper import engine
from spectrum_mapper.compact_black_radial_coupon import (
    APEX_XY_MM,
    BAND_Z_MM,
    BASE_SIZE_MM,
    COMPACT_COUPON_SCHEMA,
    IDENTIFIER_LAYER_HEIGHT_MM,
    MODEL_HEIGHT_MM,
    RADIAL_THICKNESS_MM,
    TOP_CAP_THICKNESS_MM,
    TOP_SIZE_MM,
    CompactBlackRadialCouponError,
    _write_conventional_3mf,
    _equal_normal_core_bounds,
    _expected_outer_volume,
    _identifier_tiles,
    _shell_and_core_meshes,
    build_compact_conventional_coupon,
    build_compact_radial_coupon,
    compact_stages,
    create_compact_black_radial_coupon_bundle,
    validate_compact_black_radial_coupon_3mf,
)
from spectrum_mapper.radial_export import (
    RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_ARACHNE_010,
    RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_010,
    RadialExportError,
    validate_radial_3mf,
)


def _rewrite_archive(
    source: Path,
    destination: Path,
    replacements: dict[str, bytes],
) -> None:
    with zipfile.ZipFile(source, "r") as original, zipfile.ZipFile(
        destination, "w", zipfile.ZIP_DEFLATED
    ) as modified:
        for info in original.infolist():
            modified.writestr(
                info,
                replacements.get(info.filename, original.read(info.filename)),
            )


class CompactBlackRadialCouponTests(unittest.TestCase):
    def test_conventional_project_is_stable_after_runtime_hotfix_import(self) -> None:
        importlib.import_module("spectrum_mapper_hotfix")
        self.assertIsNot(engine.write_3mf_atomic, engine._CORE_WRITE_3MF_ATOMIC)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conventional.3mf"
            _write_conventional_3mf(path)
            with zipfile.ZipFile(path) as archive:
                project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
        self.assertNotIn("tripo_spectrum_mapper_hotfix", project)

    def test_geometry_is_large_corner_frustum_with_exact_cadence_bands(self) -> None:
        self.assertEqual(
            BAND_Z_MM,
            (0.0, 3.0, 9.0, 12.0, 16.2, 19.2, 22.8),
        )
        stages = compact_stages()
        np.testing.assert_allclose(
            [stage.z1_mm - stage.z0_mm for stage in stages],
            [3.0, 6.0, 3.0, 4.2, 3.0, 3.6],
            rtol=0.0,
            atol=1.0e-12,
        )
        self.assertEqual(
            [stage.conventional_state_index + 1 for stage in stages],
            [2, 24, 11, 17, 5, 23],
        )
        self.assertEqual(
            [stage.radial_thickness_mm for stage in stages],
            [None, 0.42, 0.30, 0.21, 0.15, 0.10],
        )
        coupon = build_compact_conventional_coupon()
        self.assertGreater(len(coupon.part_names), 6)
        np.testing.assert_allclose(
            np.ptp(coupon.vertices_mm, axis=0),
            [BASE_SIZE_MM, BASE_SIZE_MM, MODEL_HEIGHT_MM],
            rtol=0.0,
            atol=1.0e-9,
        )
        top = coupon.vertices_mm[
            np.isclose(coupon.vertices_mm[:, 2], MODEL_HEIGHT_MM)
        ]
        self.assertEqual(top.shape, (4, 3))
        np.testing.assert_allclose(np.ptp(top[:, :2], axis=0), [TOP_SIZE_MM] * 2)
        np.testing.assert_allclose(np.min(top[:, :2], axis=0), APEX_XY_MM)
        self.assertEqual(APEX_XY_MM, (0.0, 0.0))
        for z_mm in BAND_Z_MM:
            section = coupon.vertices_mm[np.isclose(coupon.vertices_mm[:, 2], z_mm)]
            self.assertTrue(np.any(np.isclose(section[:, 0], 0.0)))
            self.assertTrue(np.any(np.isclose(section[:, 1], 0.0)))
        volume = 0.0
        for part_id in range(len(coupon.part_names)):
            faces = coupon.faces[coupon.face_part_ids == part_id]
            used, inverse = np.unique(faces.reshape(-1), return_inverse=True)
            local = inverse.reshape((-1, 3))
            triangles = coupon.vertices_mm[used][local]
            volume += float(
                np.einsum(
                    "ij,ij->i",
                    triangles[:, 0],
                    np.cross(triangles[:, 1], triangles[:, 2]),
                ).sum()
                / 6.0
            )
        self.assertAlmostEqual(
            volume,
            _expected_outer_volume(),
            places=7,
        )

    def test_equal_normal_insets_keep_every_mixed_core_positive(self) -> None:
        for stage in compact_stages()[1:]:
            thickness = float(stage.radial_thickness_mm)
            for z_mm in (stage.z0_mm, stage.z1_mm):
                x_min, x_max, y_min, y_max = _equal_normal_core_bounds(
                    z_mm, thickness
                )
                self.assertGreater(x_max - x_min, 0.0)
                self.assertGreater(y_max - y_min, 0.0)
            shell_vertices, shell_faces, core_vertices, core_faces = (
                _shell_and_core_meshes(
                    stage.z0_mm,
                    stage.z1_mm,
                    thickness,
                    top_cap_mm=(
                        TOP_CAP_THICKNESS_MM
                        if stage.index == len(compact_stages()) - 1
                        else 0.0
                    ),
                )
            )
            for vertices, faces in (
                (shell_vertices, shell_faces),
                (core_vertices, core_faces),
            ):
                quality = engine.mesh_quality(
                    vertices,
                    faces,
                    check_self_intersections=True,
                )
                self.assertTrue(quality["watertight"])
                self.assertTrue(quality["winding_consistent"])
                self.assertTrue(quality["positive_volume"])
                self.assertEqual(quality["degenerate_faces"], 0)
                self.assertEqual(quality["self_intersecting_faces"], 0)

    def test_radial_profiles_use_only_physical_black_and_white(self) -> None:
        classic = build_compact_radial_coupon()
        self.assertEqual(
            classic.process_profile,
            RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_010,
        )
        self.assertGreater(len(classic.parts), 12)
        self.assertEqual(set(part.extruder for part in classic.parts), {1, 2})
        self.assertEqual(
            classic.metadata["compact_black_radial_coupon"]["schema"],
            COMPACT_COUPON_SCHEMA,
        )
        semantics = classic.metadata["compact_black_radial_coupon"][
            "radial_semantics"
        ]
        self.assertTrue(semantics["pure_white_base_above_identifier"])
        self.assertTrue(semantics["bottom_identifier_black_exception"])
        self.assertNotIn("pure_white_base", semantics)
        first_part_metadata = next(
            part.metadata
            for part in classic.parts
            if part.metadata.get("stage_index") == 1
            and part.role == "pure_black_core"
        )
        self.assertIn("reference_conventional_black_percent", first_part_metadata)
        self.assertIsNone(first_part_metadata["radial_effective_black_percent"])
        self.assertFalse(first_part_metadata["calibrated"])
        self.assertNotIn("effective_black_percent", first_part_metadata)
        arachne = build_compact_radial_coupon(wall_generator="arachne")
        self.assertEqual(
            arachne.process_profile,
            RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_ARACHNE_010,
        )

    def test_bottom_identifiers_read_normally_from_finished_underside(self) -> None:
        expected = {
            "Z": ("11111", "00011", "00111", "01110", "11100", "11000", "11111"),
            "C": ("11111", "11000", "11000", "11000", "11000", "11000", "11111"),
            "A": ("01110", "11011", "11011", "11111", "11011", "11011", "11011"),
        }
        for code, rows in expected.items():
            black_tiles = [tile for tile in _identifier_tiles(code) if tile.color == "black"]
            for row, text in enumerate(rows):
                y = 27.0 - 2.0 * row
                for column, value in enumerate(text):
                    # Finished underside view has screen-right == model -X.
                    x = 25.0 - 2.0 * column
                    observed = any(
                        tile.bounds_xy_mm[0] < x < tile.bounds_xy_mm[1]
                        and tile.bounds_xy_mm[2] < y < tile.bounds_xy_mm[3]
                        for tile in black_tiles
                    )
                    self.assertEqual(observed, value == "1", (code, row, column))
            total_volume = sum(
                abs(np.linalg.det(np.eye(3)))
                * (tile.bounds_xy_mm[1] - tile.bounds_xy_mm[0])
                * (tile.bounds_xy_mm[3] - tile.bounds_xy_mm[2])
                * IDENTIFIER_LAYER_HEIGHT_MM
                for tile in _identifier_tiles(code)
            )
            self.assertAlmostEqual(total_volume, BASE_SIZE_MM**2 * 0.20)

    def test_final_radial_band_has_full_white_horizontal_top_cap(self) -> None:
        for generator in ("classic", "arachne"):
            package = build_compact_radial_coupon(wall_generator=generator)
            top_shell = next(
                part
                for part in package.parts
                if part.metadata.get("full_horizontal_top_cap") is True
            )
            self.assertEqual(top_shell.extruder, 2)
            vertices = np.asarray(top_shell.vertices_mm, dtype=np.float64)
            faces = np.asarray(top_shell.faces, dtype=np.int32)
            on_top = np.all(
                np.isclose(vertices[faces, 2], MODEL_HEIGHT_MM), axis=1
            )
            top_triangles = vertices[faces[on_top]]
            top_area = float(
                0.5
                * np.linalg.norm(
                    np.cross(
                        top_triangles[:, 1] - top_triangles[:, 0],
                        top_triangles[:, 2] - top_triangles[:, 0],
                    ),
                    axis=1,
                ).sum()
            )
            self.assertAlmostEqual(top_area, TOP_SIZE_MM**2, places=8)
            black_top = max(
                float(np.max(np.asarray(part.vertices_mm)[:, 2]))
                for part in package.parts
                if part.extruder == 1
                and part.metadata.get("stage_index") == len(compact_stages()) - 1
            )
            self.assertAlmostEqual(
                black_top,
                MODEL_HEIGHT_MM - TOP_CAP_THICKNESS_MM,
                places=9,
            )

    def test_bundle_round_trip_uses_actual_compact_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = create_compact_black_radial_coupon_bundle(Path(directory) / "bundle")
            conventional = validate_compact_black_radial_coupon_3mf(
                bundle.conventional_path, method="compact-conventional-z-ratio"
            )
            classic = validate_compact_black_radial_coupon_3mf(
                bundle.radial_path,
                method="large-frustum-radial-physical-thickness",
            )
            arachne = validate_compact_black_radial_coupon_3mf(
                bundle.radial_arachne_path,
                method="large-frustum-radial-physical-thickness-arachne",
            )
            self.assertGreater(conventional["parts"], 6)
            self.assertEqual(set(conventional["observed_state_ids"]), {1, 2, 5, 11, 17, 23, 24})
            self.assertEqual(conventional["bottom_identifier"], "Z")
            self.assertGreater(classic["parts"], 12)
            self.assertEqual(classic["bottom_identifier"], "C")
            self.assertEqual(arachne["bottom_identifier"], "A")
            self.assertEqual(classic["top_cap_mm"], 0.10)
            self.assertFalse(classic["intentional_black_top_window"])
            self.assertEqual(classic["wall_loops"], 1)
            self.assertTrue(classic["detect_thin_wall"])
            self.assertEqual(arachne["wall_generator"], "arachne")
            self.assertFalse(arachne["detect_thin_wall"])
            with zipfile.ZipFile(bundle.radial_path) as archive:
                classic_project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
                classic_metadata = json.loads(
                    archive.read("Metadata/radial_shell_experimental.json")
                )
            with zipfile.ZipFile(bundle.radial_arachne_path) as archive:
                arachne_project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
                arachne_metadata = json.loads(
                    archive.read("Metadata/radial_shell_experimental.json")
                )
            for metadata in (classic_metadata, arachne_metadata):
                self.assertEqual(
                    metadata["safety"]["sparse_infill_density_percent"],
                    15,
                )
                self.assertTrue(
                    all(
                        part["closed_physical_volume"]
                        for part in metadata["parts"]
                    )
                )
                self.assertTrue(
                    all("solid_infill" not in part for part in metadata["parts"])
                )
            self.assertEqual(classic_project["wall_loops"], "1")
            self.assertEqual(classic_project["detect_thin_wall"], "1")
            self.assertEqual(classic_project["sparse_infill_density"], "15%")
            self.assertEqual(arachne_project["wall_loops"], "1")
            self.assertEqual(arachne_project["detect_thin_wall"], "0")
            self.assertEqual(arachne_project["sparse_infill_density"], "15%")
            self.assertEqual(arachne_project["min_feature_size"], "20%")
            self.assertEqual(arachne_project["min_bead_width"], "25%")
            self.assertEqual(arachne_project["initial_layer_min_bead_width"], "85%")
            validate_radial_3mf(
                bundle.radial_path,
                expected_process_profile=RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_010,
            )
            validate_radial_3mf(
                bundle.radial_arachne_path,
                expected_process_profile=(
                    RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_ARACHNE_010
                ),
            )

    def test_conventional_rejects_f3_paint_or_shifted_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = create_compact_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(bundle.conventional_path) as archive:
                child = ET.fromstring(archive.read("3D/Objects/object_1.model"))
            first_triangle = next(
                item for item in child.iter() if item.tag.endswith("triangle")
            )
            first_triangle.attrib["paint_color"] = engine.PAINT_CODES[2]
            painted = Path(directory) / "f3_paint.3mf"
            _rewrite_archive(
                bundle.conventional_path,
                painted,
                {
                    "3D/Objects/object_1.model": ET.tostring(
                        child, encoding="utf-8", xml_declaration=True
                    )
                },
            )
            with self.assertRaises(CompactBlackRadialCouponError):
                validate_compact_black_radial_coupon_3mf(painted)

            with zipfile.ZipFile(bundle.conventional_path) as archive:
                child = ET.fromstring(archive.read("3D/Objects/object_1.model"))
            first_vertex = next(
                item for item in child.iter() if item.tag.endswith("vertex")
            )
            first_vertex.attrib["x"] = str(float(first_vertex.attrib["x"]) + 0.05)
            shifted = Path(directory) / "shifted.3mf"
            _rewrite_archive(
                bundle.conventional_path,
                shifted,
                {
                    "3D/Objects/object_1.model": ET.tostring(
                        child, encoding="utf-8", xml_declaration=True
                    )
                },
            )
            with self.assertRaisesRegex(CompactBlackRadialCouponError, "vertices"):
                validate_compact_black_radial_coupon_3mf(shifted)

    def test_conventional_rejects_relationship_byte_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = create_compact_black_radial_coupon_bundle(Path(directory) / "bundle")
            tampered = Path(directory) / "rels_drift.3mf"
            with zipfile.ZipFile(bundle.conventional_path) as archive:
                relationships = archive.read("_rels/.rels")
            _rewrite_archive(
                bundle.conventional_path,
                tampered,
                {"_rels/.rels": relationships.replace(b'rel-1', b'rel-x')},
            )
            with self.assertRaisesRegex(
                CompactBlackRadialCouponError, "relationship drifted"
            ):
                validate_compact_black_radial_coupon_3mf(tampered)

    def test_radial_rejects_part_metadata_and_aggressive_setting_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = create_compact_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(bundle.radial_path) as archive:
                metadata = json.loads(
                    archive.read("Metadata/radial_shell_experimental.json")
                )
            metadata["parts"][0]["source_state"] = 2
            tampered = Path(directory) / "part_metadata.3mf"
            _rewrite_archive(
                bundle.radial_path,
                tampered,
                {
                    "Metadata/radial_shell_experimental.json": json.dumps(
                        metadata, ensure_ascii=False, indent=2
                    ).encode("utf-8")
                },
            )
            with self.assertRaises(CompactBlackRadialCouponError):
                validate_compact_black_radial_coupon_3mf(tampered)

            with zipfile.ZipFile(bundle.radial_arachne_path) as archive:
                project = json.loads(archive.read("Metadata/project_settings.config"))
            project["min_bead_width"] = "85%"
            drifted = Path(directory) / "bead_drift.3mf"
            _rewrite_archive(
                bundle.radial_arachne_path,
                drifted,
                {
                    "Metadata/project_settings.config": json.dumps(
                        project, ensure_ascii=False, indent=2
                    ).encode("utf-8")
                },
            )
            with self.assertRaises((RadialExportError, CompactBlackRadialCouponError)):
                validate_compact_black_radial_coupon_3mf(drifted)

    def test_radial_rejects_horizontal_top_cap_geometry_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = create_compact_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(bundle.radial_path) as archive:
                metadata = json.loads(
                    archive.read("Metadata/radial_shell_experimental.json")
                )
                root = ET.fromstring(
                    archive.read("3D/Objects/radial_parts.model")
                )
            cap_index = next(
                index
                for index, part in enumerate(metadata["parts"])
                if part.get("metadata", {}).get("full_horizontal_top_cap") is True
            )
            objects = [item for item in root.iter() if item.tag.endswith("object")]
            cap_vertices = [
                item
                for item in objects[cap_index].iter()
                if item.tag.endswith("vertex")
                and np.isclose(float(item.attrib["z"]), MODEL_HEIGHT_MM)
            ]
            self.assertTrue(cap_vertices)
            cap_vertices[0].attrib["z"] = str(MODEL_HEIGHT_MM - 0.05)
            tampered = Path(directory) / "top_cap_geometry_drift.3mf"
            _rewrite_archive(
                bundle.radial_path,
                tampered,
                {
                    "3D/Objects/radial_parts.model": ET.tostring(
                        root, encoding="utf-8", xml_declaration=True
                    )
                },
            )
            with self.assertRaises(
                (RadialExportError, CompactBlackRadialCouponError)
            ):
                validate_compact_black_radial_coupon_3mf(tampered)

    def test_manifest_hashes_every_payload_and_readme_has_limit_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = create_compact_black_radial_coupon_bundle(Path(directory) / "bundle")
            manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], COMPACT_COUPON_SCHEMA)
            self.assertFalse(manifest["print_allowed"])
            for item in manifest["files"]:
                path = bundle.folder / item["name"]
                self.assertEqual(path.stat().st_size, item["bytes"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
            readme_ja = bundle.readme_ja_path.read_text(encoding="utf-8")
            readme_en = bundle.readme_en_path.read_text(encoding="utf-8")
            self.assertIn("0.10 mm外皮は限界セル", readme_ja)
            self.assertIn("Line Width", readme_ja)
            self.assertIn("光学的な黒率は未校正", readme_ja)
            self.assertIn("約34倍", readme_ja)
            self.assertIn("個別にスライス", readme_ja)
            self.assertIn("every layer", readme_en)
            self.assertIn("not a claim", readme_en)
            self.assertIn("not calibrated claims", readme_en)
            self.assertIn("roughly 34 times", readme_en)
            self.assertIn("Slice each 3MF separately", readme_en)


if __name__ == "__main__":
    unittest.main()
