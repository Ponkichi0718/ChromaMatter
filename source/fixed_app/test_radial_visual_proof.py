from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image

from spectrum_mapper.radial_visual_proof import (
    COLUMN_GAP_MM,
    COLUMN_HEIGHT_MM,
    COLUMN_SIZE_XY_MM,
    INSPECT_Z_MM,
    LAYER_HEIGHT_MM,
    OBJ_IMPORT_COMPARISON_FILENAME,
    OBJ_IMPORT_FILENAME,
    OBJ_IMPORT_MTL_FILENAME,
    PHYSICAL_HEX,
    RADIAL_FILENAME,
    REFERENCE_FILENAME,
    REFERENCE_STATE_INDICES,
    REFERENCE_WHITE_PERCENT,
    SHELL_THICKNESSES_MM,
    _edge_topology,
    _signed_volume,
    build_box_mesh,
    build_box_shell_and_core,
    build_radial_section_package,
    generate_radial_visual_proof_bundle,
    validate_manifest,
    validate_reference_3mf,
)
from spectrum_mapper.radial_export import (
    RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
    validate_radial_3mf,
)
from spectrum_mapper import engine


class RadialVisualProofGeometryTests(unittest.TestCase):
    def test_box_is_closed_positive_and_exact_volume(self) -> None:
        vertices, faces = build_box_mesh(2.0, 10.0, 3.0, 11.0, 4.0, 16.0)
        self.assertEqual(vertices.shape, (8, 3))
        self.assertEqual(faces.shape, (12, 3))
        self.assertEqual(
            _edge_topology(faces),
            {
                "boundary_edges": 0,
                "nonmanifold_edges": 0,
                "winding_consistent": True,
            },
        )
        self.assertAlmostEqual(_signed_volume(vertices, faces), 8.0 * 8.0 * 12.0)

    def test_each_shell_core_partition_is_closed_and_conserves_volume(self) -> None:
        outer_volume = COLUMN_SIZE_XY_MM**2 * COLUMN_HEIGHT_MM
        for thickness in SHELL_THICKNESSES_MM:
            with self.subTest(thickness=thickness):
                shell_v, shell_f, core_v, core_f = build_box_shell_and_core(
                    0.0,
                    COLUMN_SIZE_XY_MM,
                    0.0,
                    COLUMN_SIZE_XY_MM,
                    0.0,
                    COLUMN_HEIGHT_MM,
                    thickness,
                )
                self.assertEqual(
                    _edge_topology(shell_f),
                    {
                        "boundary_edges": 0,
                        "nonmanifold_edges": 0,
                        "winding_consistent": True,
                    },
                )
                self.assertEqual(
                    _edge_topology(core_f),
                    {
                        "boundary_edges": 0,
                        "nonmanifold_edges": 0,
                        "winding_consistent": True,
                    },
                )
                shell_volume = _signed_volume(shell_v, shell_f)
                core_volume = _signed_volume(core_v, core_f)
                self.assertGreater(shell_volume, 0.0)
                self.assertGreater(core_volume, 0.0)
                self.assertAlmostEqual(shell_volume + core_volume, outer_volume)
                distances = np.min(
                    np.column_stack(
                        (
                            core_v[:, 0],
                            COLUMN_SIZE_XY_MM - core_v[:, 0],
                            core_v[:, 1],
                            COLUMN_SIZE_XY_MM - core_v[:, 1],
                            core_v[:, 2],
                            COLUMN_HEIGHT_MM - core_v[:, 2],
                        )
                    ),
                    axis=1,
                )
                np.testing.assert_allclose(distances, thickness, atol=1.0e-12)

    def test_radial_package_has_exact_part_order_and_analytical_proofs(self) -> None:
        package, rows = build_radial_section_package()
        self.assertEqual(package.process_profile, RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010)
        self.assertEqual(package.physical_hex, PHYSICAL_HEX)
        self.assertEqual(package.layer_height_mm, LAYER_HEIGHT_MM)
        self.assertEqual(len(package.parts), 10)
        self.assertEqual([part.role for part in package.parts[:5]], ["pure_black_core"] * 5)
        self.assertEqual(
            [part.role for part in package.parts[5:]],
            ["partner_outer_shell"] * 5,
        )
        self.assertEqual([part.extruder for part in package.parts], [1] * 5 + [2] * 5)
        self.assertEqual(len(rows), 5)
        for index, (row, thickness) in enumerate(zip(rows, SHELL_THICKNESSES_MM, strict=True)):
            self.assertEqual(row["band"], index + 1)
            self.assertAlmostEqual(float(row["shell_thickness_mm"]), thickness)
            self.assertAlmostEqual(float(row["interface_distance_min_mm"]), thickness)
            self.assertAlmostEqual(float(row["interface_distance_max_mm"]), thickness)
            self.assertLess(abs(float(row["volume_residual_mm3"])), 1.0e-9)
            self.assertAlmostEqual(
                float(row["x0_mm"]),
                index * (COLUMN_SIZE_XY_MM + COLUMN_GAP_MM),
            )


class RadialVisualProofBundleTests(unittest.TestCase):
    def test_actual_radial_mesh_xml_proves_interfaces_without_metadata(self) -> None:
        """Lock the independent XML/mesh audit into the regression suite."""

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "proof"
            bundle = generate_radial_visual_proof_bundle(folder)
            with zipfile.ZipFile(bundle.radial_path, "r") as archive:
                xml = ET.fromstring(archive.read("3D/Objects/radial_parts.model"))

            def local_name(tag: str) -> str:
                return tag.split("}")[-1]

            meshes: list[tuple[np.ndarray, np.ndarray]] = []
            for object_element in xml.iter():
                if local_name(object_element.tag) != "object":
                    continue
                mesh_elements = [
                    child
                    for child in object_element
                    if local_name(child.tag) == "mesh"
                ]
                if not mesh_elements:
                    continue
                self.assertEqual(len(mesh_elements), 1)
                mesh_element = mesh_elements[0]
                vertices_parent = next(
                    child
                    for child in mesh_element
                    if local_name(child.tag) == "vertices"
                )
                triangles_parent = next(
                    child
                    for child in mesh_element
                    if local_name(child.tag) == "triangles"
                )
                vertices = np.asarray(
                    [
                        [
                            float(vertex.attrib[axis])
                            for axis in ("x", "y", "z")
                        ]
                        for vertex in vertices_parent
                        if local_name(vertex.tag) == "vertex"
                    ],
                    dtype=np.float64,
                )
                faces = np.asarray(
                    [
                        [
                            int(triangle.attrib[key])
                            for key in ("v1", "v2", "v3")
                        ]
                        for triangle in triangles_parent
                        if local_name(triangle.tag) == "triangle"
                    ],
                    dtype=np.int32,
                )
                meshes.append((vertices, faces))

            self.assertEqual(len(meshes), 10)
            cores = [item for item in meshes if item[0].shape == (8, 3) and item[1].shape == (12, 3)]
            shells = [item for item in meshes if item[0].shape == (16, 3) and item[1].shape == (24, 3)]
            self.assertEqual(len(cores), 5)
            self.assertEqual(len(shells), 5)
            self.assertEqual(len(cores) + len(shells), len(meshes))

            def centre_x(item: tuple[np.ndarray, np.ndarray]) -> float:
                vertices, _faces = item
                return float(0.5 * (vertices[:, 0].min() + vertices[:, 0].max()))

            cores_by_x = {round(centre_x(item), 9): item for item in cores}
            shells_by_x = {round(centre_x(item), 9): item for item in shells}
            self.assertEqual(sorted(cores_by_x), sorted(shells_by_x))
            self.assertEqual(len(cores_by_x), 5)

            def triangle_key(points: np.ndarray) -> tuple[tuple[float, float, float], ...]:
                return tuple(
                    sorted(
                        tuple(float(round(value, 9)) for value in point)
                        for point in points
                    )
                )

            measured_thicknesses: list[float] = []
            for band_index, centre in enumerate(sorted(cores_by_x)):
                core_vertices, core_faces = cores_by_x[centre]
                shell_vertices, shell_faces = shells_by_x[centre]
                for vertices, faces in (
                    (core_vertices, core_faces),
                    (shell_vertices, shell_faces),
                ):
                    self.assertEqual(
                        _edge_topology(faces),
                        {
                            "boundary_edges": 0,
                            "nonmanifold_edges": 0,
                            "winding_consistent": True,
                        },
                    )
                    self.assertGreater(_signed_volume(vertices, faces), 0.0)

                core_triangles = core_vertices[core_faces]
                shell_triangles = shell_vertices[shell_faces]
                core_by_triangle = {
                    triangle_key(triangle): triangle for triangle in core_triangles
                }
                shell_by_triangle = {
                    triangle_key(triangle): triangle for triangle in shell_triangles
                }
                shared_keys = set(core_by_triangle) & set(shell_by_triangle)
                self.assertEqual(len(shared_keys), 12)
                for key in shared_keys:
                    core_triangle = core_by_triangle[key]
                    shell_triangle = shell_by_triangle[key]
                    core_normal = np.cross(
                        core_triangle[1] - core_triangle[0],
                        core_triangle[2] - core_triangle[0],
                    )
                    shell_normal = np.cross(
                        shell_triangle[1] - shell_triangle[0],
                        shell_triangle[2] - shell_triangle[0],
                    )
                    np.testing.assert_allclose(
                        core_normal,
                        -shell_normal,
                        atol=1.0e-10,
                        rtol=0.0,
                    )

                total_volume = _signed_volume(core_vertices, core_faces) + _signed_volume(
                    shell_vertices,
                    shell_faces,
                )
                self.assertAlmostEqual(total_volume, 768.0, places=8)
                outer_minimum = shell_vertices.min(axis=0)
                outer_maximum = shell_vertices.max(axis=0)
                interface_distances = np.min(
                    np.column_stack(
                        (
                            core_vertices[:, 0] - outer_minimum[0],
                            outer_maximum[0] - core_vertices[:, 0],
                            core_vertices[:, 1] - outer_minimum[1],
                            outer_maximum[1] - core_vertices[:, 1],
                            core_vertices[:, 2] - outer_minimum[2],
                            outer_maximum[2] - core_vertices[:, 2],
                        )
                    ),
                    axis=1,
                )
                expected = SHELL_THICKNESSES_MM[band_index]
                np.testing.assert_allclose(
                    interface_distances,
                    expected,
                    atol=1.0e-10,
                    rtol=0.0,
                )
                measured_thicknesses.append(float(interface_distances.mean()))

            np.testing.assert_allclose(
                measured_thicknesses,
                SHELL_THICKNESSES_MM,
                atol=1.0e-10,
                rtol=0.0,
            )

    def test_bundle_is_self_describing_and_reopens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "proof"
            bundle = generate_radial_visual_proof_bundle(folder)
            self.assertEqual(bundle.reference_path.name, REFERENCE_FILENAME)
            self.assertEqual(bundle.radial_path.name, RADIAL_FILENAME)
            self.assertEqual(bundle.obj_import_path.name, OBJ_IMPORT_FILENAME)
            self.assertEqual(bundle.obj_import_mtl_path.name, OBJ_IMPORT_MTL_FILENAME)
            self.assertEqual(
                bundle.obj_import_comparison_path.name,
                OBJ_IMPORT_COMPARISON_FILENAME,
            )
            reference = validate_reference_3mf(bundle.reference_path)
            self.assertTrue(reference["look_only"])
            self.assertFalse(reference["radial_geometry"])
            self.assertEqual(reference["states_zero_based"], list(REFERENCE_STATE_INDICES))
            radial = validate_radial_3mf(
                bundle.radial_path,
                expected_parts=10,
                expected_physical=PHYSICAL_HEX,
                expected_extruders=(1, 1, 1, 1, 1, 2, 2, 2, 2, 2),
                expected_process_profile=RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
            )
            self.assertTrue(radial.static_validation_ok)
            self.assertTrue(radial.slice_only)
            self.assertFalse(radial.print_allowed)
            self.assertEqual(radial.physical_extruders, (1, 1, 1, 1, 1, 2, 2, 2, 2, 2))

            radial_json = json.loads(
                bundle.radial_validation_path.read_text(encoding="utf-8")
            )
            self.assertFalse(radial_json["adaptive_partition_used"])
            self.assertEqual(radial_json["normal_surface_expected"], "F2 only")
            self.assertAlmostEqual(radial_json["inspect_z_mm"], INSPECT_Z_MM)
            self.assertEqual(
                [column["shell_thickness_mm"] for column in radial_json["columns"]],
                list(SHELL_THICKNESSES_MM),
            )
            for column in radial_json["columns"]:
                self.assertEqual(column["shell_topology"]["boundary_edges"], 0)
                self.assertEqual(column["shell_topology"]["nonmanifold_edges"], 0)
                self.assertEqual(column["core_topology"]["boundary_edges"], 0)
                self.assertEqual(column["core_topology"]["nonmanifold_edges"], 0)

            with bundle.mapping_csv_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 5)
            self.assertEqual(
                [int(row["reference_white_percent"]) for row in rows],
                list(REFERENCE_WHITE_PERCENT),
            )
            self.assertEqual(
                [float(row["shell_thickness_mm"]) for row in rows],
                list(SHELL_THICKNESSES_MM),
            )
            with Image.open(bundle.mapping_png_path) as image:
                self.assertEqual(image.size, (1600, 920))
                self.assertEqual(image.mode, "RGB")
            with Image.open(bundle.obj_import_comparison_path) as image:
                self.assertEqual(image.size, (1600, 900))
                self.assertEqual(image.mode, "RGB")
            obj_vertex_lines = [
                line
                for line in bundle.obj_import_path.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.startswith("v ")
            ]
            self.assertGreater(len(obj_vertex_lines), 0)
            self.assertTrue(all(len(line.split()) == 7 for line in obj_vertex_lines))
            loaded_obj = engine.load_vertex_color_obj(bundle.obj_import_path)
            obj_topology = engine.edge_topology(
                loaded_obj.faces,
                len(loaded_obj.vertices),
            )
            self.assertEqual(obj_topology["boundary_edges"], 0)
            self.assertEqual(obj_topology["nonmanifold_edges"], 0)
            obj_validation = json.loads(
                bundle.obj_import_validation_path.read_text(encoding="utf-8")
            )
            self.assertTrue(obj_validation["all_vertices_xyzrgb"])
            self.assertEqual(obj_validation["load_vertex_color_obj"], "pass")
            self.assertEqual(obj_validation["prepare_geometry"], "pass")
            self.assertTrue(obj_validation["watertight"])
            self.assertTrue(obj_validation["prepare_watertight"])
            self.assertEqual(obj_validation["boundary_edges"], 0)
            self.assertEqual(obj_validation["nonmanifold_edges"], 0)
            self.assertGreaterEqual(
                obj_validation["exact_face_colour_area_fraction"],
                obj_validation["minimum_exact_face_colour_area_fraction"] - 1.0e-8,
            )
            ja = bundle.readme_ja_path.read_text(encoding="utf-8")
            en = bundle.readme_en_path.read_text(encoding="utf-8")
            for text in (ja, en):
                self.assertIn("LOOK ONLY", text)
                self.assertIn("F2", text)
                self.assertIn("F1", text)
                self.assertIn("0.10", text)
                self.assertIn("0.18", text)
                self.assertIn("0.42", text)
                self.assertIn("SLICE ONLY", text)
                self.assertIn(OBJ_IMPORT_FILENAME, text)
                self.assertIn("INVALID", text)
            manifest = validate_manifest(folder)
            self.assertTrue(manifest["ok"])
            self.assertEqual(manifest["count"], 12)

    def test_generator_refuses_to_overwrite_existing_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "proof"
            folder.mkdir()
            with self.assertRaises(FileExistsError):
                generate_radial_visual_proof_bundle(folder)


if __name__ == "__main__":
    unittest.main()
