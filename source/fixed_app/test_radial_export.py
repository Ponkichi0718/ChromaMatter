from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import numpy as np

from spectrum_mapper.radial_export import (
    COLOR_DEPTH_EXPORT_SCHEMA,
    RADIAL_SCHEMA,
    RadialExportError,
    RadialExportPackage,
    RadialExportPart,
    package_from_radial_shell,
    package_from_color_depth,
    validate_radial_3mf,
    write_radial_3mf_atomic,
)


CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PHYSICAL = ("#080808", "#F5F3EE", "#D92B32", "#B8753D")


def _box(
    name: str,
    role: str,
    extruder: int,
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
    *,
    solid_infill: bool = True,
) -> RadialExportPart:
    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    vertices = np.asarray(
        [
            [x0, y0, z0],
            [x1, y0, z0],
            [x1, y1, z0],
            [x0, y1, z0],
            [x0, y0, z1],
            [x1, y0, z1],
            [x1, y1, z1],
            [x0, y1, z1],
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            [0, 2, 1],
            [0, 3, 2],
            [4, 5, 6],
            [4, 6, 7],
            [0, 1, 5],
            [0, 5, 4],
            [1, 2, 6],
            [1, 6, 5],
            [2, 3, 7],
            [2, 7, 6],
            [3, 0, 4],
            [3, 4, 7],
        ],
        dtype=np.int32,
    )
    return RadialExportPart(
        name=name,
        role=role,
        vertices_mm=vertices,
        faces=faces,
        extruder=extruder,
        solid_infill=solid_infill,
        metadata={"probe": np.asarray([1, 2], dtype=np.int32)},
    )


def _package(*, black_extruder: int = 1) -> RadialExportPackage:
    # Exact boundary contact at x=1 is allowed; interiors are disjoint.  The
    # geometry generator owns stronger interface/volume-conservation checks.
    core = _box(
        "physical black core",
        "pure_black_core",
        black_extruder,
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
    )
    shell = _box(
        "physical red shell",
        "partner_outer_shell",
        3,
        (1.0, 0.0, 0.0),
        (2.0, 1.0, 1.0),
    )
    return RadialExportPackage(
        parts=(core, shell),
        physical_hex=PHYSICAL,
        black_extruder=black_extruder,
        metadata={"skin_thickness_mm": np.float64(0.3770796327)},
    )


class RadialExportTests(unittest.TestCase):
    def test_color_depth_round_trip_uses_generic_physical_unions(self) -> None:
        first = _box(
            "ColorDepth F1", "pure_black_core", 1,
            (0.0, 0.0, 0.0), (1.0, 1.0, 1.0),
        )
        third = _box(
            "ColorDepth F3", "partner_outer_shell", 3,
            (1.0, 0.0, 0.0), (2.0, 1.0, 1.0),
        )
        result = SimpleNamespace(
            parts=(first, third),
            interfaces=(
                {
                    "physical_materials": [1, 3],
                    "exact_coordinate_triangles": True,
                    "opposite_winding": True,
                    "gap_mm": 0.0,
                    "positive_overlap_mm3": 0.0,
                },
            ),
            source_volume_mm3=2.0,
            output_volume_mm3=2.0,
            metadata={
                "physical_materials_only": True,
                "ratio_definitions": 0,
                "cycle_definitions": 0,
                "virtual_mix_definitions": 0,
                "painted_triangles": 0,
                "positive_overlap_mm3": 0.0,
                "gap_mm": 0.0,
                "shared_interface_partition_exact": True,
                "external_surface_coverage_exact": True,
                "unsafe_columns_outer_only_verified": True,
            },
        )
        package = package_from_color_depth(result, PHYSICAL)
        self.assertEqual(package.renderer, "color_depth")
        self.assertEqual(
            [part.role for part in package.parts],
            ["color_depth_physical_union"] * 2,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "color_depth_probe.3mf"
            written = write_radial_3mf_atomic(path, package)
            self.assertEqual(written.physical_extruders, (1, 3))
            with zipfile.ZipFile(path) as archive:
                metadata = json.loads(
                    archive.read("Metadata/radial_shell_experimental.json")
                )
            self.assertEqual(metadata["schema"], COLOR_DEPTH_EXPORT_SCHEMA)
            self.assertEqual(metadata["renderer"], "ColorDepth Lab")
            self.assertIsNone(metadata["black_extruder"])
            self.assertTrue(written.static_validation_ok)

    def test_round_trip_is_one_physical_print_object_and_slice_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "radial_probe.3mf"
            result = write_radial_3mf_atomic(path, _package())
            self.assertEqual(result.path, path)
            self.assertEqual(result.parts, 2)
            self.assertEqual(result.physical_extruders, (1, 3))
            self.assertTrue(result.static_validation_ok)
            self.assertTrue(result.slice_only)
            self.assertFalse(result.print_allowed)
            self.assertEqual(result.to_dict()["physical_extruders"], [1, 3])

            reopened = validate_radial_3mf(
                path,
                expected_parts=2,
                expected_physical=PHYSICAL,
                expected_extruders=(1, 3),
            )
            self.assertEqual(reopened.sha256, result.sha256)
            with zipfile.ZipFile(path) as archive:
                root = ET.fromstring(archive.read("3D/3dmodel.model"))
                build_items = root.findall(
                    f"{{{CORE_NS}}}build/{{{CORE_NS}}}item"
                )
                self.assertEqual(len(build_items), 1)
                parent = root.findall(
                    f"{{{CORE_NS}}}resources/{{{CORE_NS}}}object"
                )
                self.assertEqual(len(parent), 1)
                self.assertEqual(
                    len(
                        parent[0].findall(
                            f"{{{CORE_NS}}}components/{{{CORE_NS}}}component"
                        )
                    ),
                    2,
                )
                mesh_xml = archive.read("3D/Objects/radial_parts.model")
                self.assertNotIn(b"paint_color", mesh_xml)
                model_settings = ET.fromstring(
                    archive.read("Metadata/model_settings.config")
                )
                parts = model_settings.findall("object/part")
                self.assertEqual(
                    [
                        next(
                            item.attrib["value"]
                            for item in part.findall("metadata")
                            if item.attrib.get("key") == "extruder"
                        )
                        for part in parts
                    ],
                    ["1", "3"],
                )
                project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
                self.assertEqual(project["mixed_filament_definitions"], "")
                self.assertEqual(project["sparse_infill_density"], "100%")
                self.assertEqual(project["enable_support"], "0")
                self.assertEqual(project["enable_prime_tower"], "1")
                self.assertEqual(project["brim_type"], "no_brim")
                self.assertEqual(project["raft_layers"], "0")
                self.assertEqual(project["flush_multiplier"], "0")
                self.assertTrue(
                    all(value == "0" for value in project["flush_volumes_matrix"])
                )
                metadata = json.loads(
                    archive.read("Metadata/radial_shell_experimental.json")
                )
                self.assertEqual(metadata["schema"], RADIAL_SCHEMA)
                self.assertTrue(metadata["slice_only"])
                self.assertFalse(metadata["print_allowed"])
                self.assertTrue(metadata["safety"]["prime_tower_enabled"])
                self.assertFalse(metadata["safety"]["support_enabled"])
                self.assertFalse(
                    metadata["safety"]["flush_to_model_enabled"]
                )
                self.assertEqual(
                    [part["role"] for part in metadata["parts"]],
                    ["pure_black_core", "partner_outer_shell"],
                )

    def test_adapter_accepts_geometry_builder_contract(self) -> None:
        core = _box(
            "core",
            "pure_black_core",
            1,
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 1.0),
        )
        shell = _box(
            "shell",
            "partner_outer_shell",
            3,
            (1.0, 0.0, 0.0),
            (2.0, 1.0, 1.0),
        )
        raw_parts = tuple(
            SimpleNamespace(
                name=part.name,
                role=part.role,
                vertices_mm=part.vertices_mm,
                faces=part.faces,
                extruder=part.extruder,
                solid_infill=True,
                metadata={},
            )
            for part in (core, shell)
        )
        result = SimpleNamespace(
            parts=raw_parts,
            skin_thickness_mm=0.3770796327,
            partner_extruder=3,
            black_extruder=1,
            eligible_state_id=12,
            eligible_area_fraction=0.25,
            source_volume_mm3=2.0,
            output_volume_mm3=2.0,
            interfaces=(
                {
                    "exact_coordinate_triangles": True,
                    "opposite_winding": True,
                    "gap_mm": 0.0,
                    "positive_overlap_mm3": 0.0,
                },
            ),
            metadata={
                "builder": "probe",
                "source_exterior_preserved_exactly": True,
                "positive_overlap_mm3": 0.0,
                "gap_mm": 0.0,
            },
        )
        package = package_from_radial_shell(result, PHYSICAL)
        self.assertEqual(package.black_extruder, 1)
        self.assertEqual([part.extruder for part in package.parts], [1, 3])
        self.assertEqual(package.metadata["skin_thickness_mm"], 0.3770796327)

    def test_rejects_virtual_tool_and_does_not_leave_destination(self) -> None:
        package = _package()
        bad = RadialExportPackage(
            parts=(
                package.parts[0],
                RadialExportPart(
                    name=package.parts[1].name,
                    role=package.parts[1].role,
                    vertices_mm=package.parts[1].vertices_mm,
                    faces=package.parts[1].faces,
                    extruder=5,
                ),
            ),
            physical_hex=PHYSICAL,
            black_extruder=1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "must_not_exist.3mf"
            with self.assertRaisesRegex(RadialExportError, "physical extruder"):
                write_radial_3mf_atomic(path, bad)
            self.assertFalse(path.exists())

    def test_rejects_wrong_black_assignment_and_part_order(self) -> None:
        package = _package()
        wrong_black = RadialExportPackage(
            parts=package.parts,
            physical_hex=PHYSICAL,
            black_extruder=2,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RadialExportError, "black extruder"):
                write_radial_3mf_atomic(Path(directory) / "bad.3mf", wrong_black)

        wrong_order = RadialExportPackage(
            parts=tuple(reversed(package.parts)),
            physical_hex=PHYSICAL,
            black_extruder=1,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RadialExportError, "ordered black core"):
                write_radial_3mf_atomic(Path(directory) / "bad.3mf", wrong_order)

    def test_rejects_open_or_non_solid_part(self) -> None:
        package = _package()
        open_core = RadialExportPart(
            name="open core",
            role="pure_black_core",
            vertices_mm=package.parts[0].vertices_mm,
            faces=package.parts[0].faces[:-1],
            extruder=1,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RadialExportError, "closed oriented"):
                write_radial_3mf_atomic(
                    Path(directory) / "open.3mf",
                    RadialExportPackage(
                        parts=(open_core, package.parts[1]),
                        physical_hex=PHYSICAL,
                        black_extruder=1,
                    ),
                )

        non_solid_shell = _box(
            "non-solid shell",
            "partner_outer_shell",
            3,
            (1.0, 0.0, 0.0),
            (2.0, 1.0, 1.0),
            solid_infill=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RadialExportError, "is not solid"):
                write_radial_3mf_atomic(
                    Path(directory) / "not_solid.3mf",
                    RadialExportPackage(
                        parts=(package.parts[0], non_solid_shell),
                        physical_hex=PHYSICAL,
                        black_extruder=1,
                    ),
                )

    def test_validator_rejects_tampered_support_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            source = directory_path / "source.3mf"
            tampered = directory_path / "tampered.3mf"
            write_radial_3mf_atomic(source, _package())
            with zipfile.ZipFile(source) as archive:
                members = {
                    name: archive.read(name) for name in archive.namelist()
                }
            project = json.loads(
                members["Metadata/project_settings.config"].decode("utf-8")
            )
            project["enable_support"] = "1"
            members["Metadata/project_settings.config"] = json.dumps(
                project, ensure_ascii=False, indent=2
            ).encode("utf-8")
            with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in members.items():
                    archive.writestr(name, data)
            with self.assertRaisesRegex(RadialExportError, "enable_support"):
                validate_radial_3mf(tampered)

    def test_validator_rejects_disabled_prime_tower(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            source = directory_path / "source.3mf"
            tampered = directory_path / "tampered.3mf"
            write_radial_3mf_atomic(source, _package())
            with zipfile.ZipFile(source) as archive:
                members = {
                    name: archive.read(name) for name in archive.namelist()
                }
            project = json.loads(
                members["Metadata/project_settings.config"].decode("utf-8")
            )
            project["enable_prime_tower"] = "0"
            members["Metadata/project_settings.config"] = json.dumps(
                project, ensure_ascii=False, indent=2
            ).encode("utf-8")
            with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in members.items():
                    archive.writestr(name, data)
            with self.assertRaisesRegex(RadialExportError, "enable_prime_tower"):
                validate_radial_3mf(tampered)


if __name__ == "__main__":
    unittest.main()
