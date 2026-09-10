from __future__ import annotations

import importlib
import json
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

from spectrum_mapper import engine
from spectrum_mapper.black_radial_coupon import (
    BLACK_RADIAL_COUPON_SCHEMA,
    build_conventional_coupon,
    build_radial_coupon,
    coupon_stages,
    create_black_radial_coupon_bundle,
    validate_black_radial_coupon_3mf,
    BlackRadialCouponError,
    _write_conventional_3mf,
)
from spectrum_mapper.radial_export import (
    RADIAL_PROCESS_PROFILE_BLACK_COUPON_ARACHNE_010,
    RADIAL_PROCESS_PROFILE_BLACK_COUPON_010,
    RadialExportError,
    validate_radial_3mf,
)


def _rewrite_archive(
    source: Path,
    destination: Path,
    replacements: dict[str, bytes],
) -> None:
    with zipfile.ZipFile(source, "r") as original, zipfile.ZipFile(
        destination,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as modified:
        for info in original.infolist():
            modified.writestr(
                info,
                replacements.get(info.filename, original.read(info.filename)),
            )


class BlackRadialCouponTests(unittest.TestCase):
    def test_conventional_project_is_stable_after_runtime_hotfix_import(self) -> None:
        importlib.import_module("spectrum_mapper_hotfix")
        self.assertIsNot(engine.write_3mf_atomic, engine._CORE_WRITE_3MF_ATOMIC)
        with tempfile.TemporaryDirectory() as directory:
            path = (
                Path(directory) / "ChromaMatter_black_gradient_conventional_0p10.3mf"
            )
            validation = _write_conventional_3mf(path)
            with zipfile.ZipFile(path) as archive:
                project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
            self.assertTrue(validation["valid"])
            self.assertEqual(validation["validated_solid_parts"], 21)
            self.assertTrue(
                validate_black_radial_coupon_3mf(
                    path, method="conventional-z-ratio"
                )["valid"]
            )
        self.assertNotIn("tripo_spectrum_mapper_hotfix", project)

    def test_geometry_has_three_lanes_seven_cells_and_all_surface_probes(self) -> None:
        coupon = build_conventional_coupon()
        self.assertEqual(len(coupon.part_names), 21)
        self.assertEqual(len(coupon.part_keys), 21)
        self.assertEqual(coupon.face_part_ids.shape, (len(coupon.faces),))
        self.assertEqual(coupon.palette_indices.shape, (len(coupon.faces),))
        np.testing.assert_allclose(
            np.ptp(coupon.vertices_mm, axis=0),
            [46.8, 51.641, 15.0],
            rtol=0.0,
            atol=1.0e-6,
        )
        self.assertEqual(
            [value + 1 for value in coupon.part_state_indices[:7]],
            [2, 24, 11, 17, 5, 23, 1],
        )
        self.assertEqual(
            [value + 1 for value in coupon.part_state_indices[7:14]],
            [3, 26, 12, 18, 6, 25, 1],
        )
        self.assertEqual(
            [value + 1 for value in coupon.part_state_indices[14:]],
            [4, 28, 13, 19, 7, 27, 1],
        )

    def test_radial_package_keeps_black_cores_first_and_uses_coupon_profile(self) -> None:
        package = build_radial_coupon()
        self.assertEqual(package.layer_height_mm, 0.10)
        self.assertEqual(package.initial_layer_height_mm, 0.20)
        self.assertEqual(
            package.process_profile,
            RADIAL_PROCESS_PROFILE_BLACK_COUPON_010,
        )
        self.assertEqual(len(package.parts), 36)
        roles = [part.role for part in package.parts]
        self.assertEqual(roles[:18], ["pure_black_core"] * 18)
        self.assertEqual(roles[18:], ["partner_outer_shell"] * 18)
        self.assertTrue(all(part.extruder == 1 for part in package.parts[:18]))
        self.assertTrue(all(2 <= part.extruder <= 4 for part in package.parts[18:]))
        proof = package.metadata["black_radial_coupon"]
        self.assertEqual(proof["schema"], BLACK_RADIAL_COUPON_SCHEMA)
        self.assertEqual(len(proof["interfaces"]), 15)
        self.assertEqual(
            [stage.radial_thickness_mm for stage in coupon_stages()],
            [None, 1.05, 0.84, 0.63, 0.42, 0.21, 0.0],
        )
        arachne = build_radial_coupon(wall_generator="arachne")
        self.assertEqual(
            arachne.process_profile,
            RADIAL_PROCESS_PROFILE_BLACK_COUPON_ARACHNE_010,
        )
        self.assertEqual(
            arachne.metadata["black_radial_coupon"]["method"],
            "radial-physical-thickness-arachne",
        )

    def test_bundle_round_trip_validates_both_architectures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            conventional = validate_black_radial_coupon_3mf(
                result.conventional_path,
                method="conventional-z-ratio",
            )
            radial = validate_black_radial_coupon_3mf(
                result.radial_path,
                method="radial-physical-thickness",
            )
            radial_arachne = validate_black_radial_coupon_3mf(
                result.radial_arachne_path,
                method="radial-physical-thickness-arachne",
            )
            self.assertTrue(conventional["valid"])
            self.assertEqual(conventional["parts"], 21)
            self.assertEqual(conventional["validated_solid_parts"], 21)
            self.assertTrue(conventional["ratio_only"])
            self.assertTrue(radial["valid"])
            self.assertEqual(radial["parts"], 36)
            self.assertTrue(radial["physical_materials_only"])
            self.assertEqual(radial["mixed_definition_rows"], 0)
            self.assertEqual(radial["interfaces"], 15)
            self.assertTrue(radial_arachne["valid"])
            self.assertEqual(radial_arachne["wall_generator"], "arachne")
            self.assertEqual(radial_arachne["interfaces"], 15)
            with zipfile.ZipFile(result.conventional_path) as archive:
                project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
                coupon_metadata = json.loads(
                    archive.read("Metadata/black_radial_coupon.json")
                )
            self.assertEqual(project["layer_height"], "0.1")
            self.assertEqual(project["wall_generator"], "classic")
            self.assertEqual(project["wall_loops"], "2")
            self.assertEqual(project["detect_thin_wall"], "0")
            self.assertNotIn("base_writer_validation", coupon_metadata)
            self.assertTrue(result.manifest_path.is_file())
            self.assertTrue(result.mapping_path.is_file())
            self.assertTrue(result.observation_path.is_file())
            self.assertTrue(result.layout_path.is_file())
            self.assertTrue(result.research_notes_path.is_file())
            self.assertTrue(result.readme_ja_path.is_file())
            self.assertTrue(result.readme_en_path.is_file())
            self.assertTrue(result.radial_arachne_validation_path.is_file())

    def test_radial_reopen_rejects_degenerate_serialized_face(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.radial_path) as archive:
                root = ET.fromstring(archive.read("3D/Objects/radial_parts.model"))
            triangle = next(item for item in root.iter() if item.tag.endswith("triangle"))
            triangle.attrib["v2"] = triangle.attrib["v1"]
            tampered = Path(directory) / "degenerate.3mf"
            _rewrite_archive(
                result.radial_path,
                tampered,
                {
                    "3D/Objects/radial_parts.model": ET.tostring(
                        root,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                },
            )
            with self.assertRaises(RadialExportError):
                validate_radial_3mf(tampered)

    def test_radial_reopen_rejects_shifted_core_interface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.radial_path) as archive:
                root = ET.fromstring(archive.read("3D/Objects/radial_parts.model"))
            first_object = next(item for item in root.iter() if item.tag.endswith("object"))
            for vertex in first_object.iter():
                if vertex.tag.endswith("vertex"):
                    vertex.attrib["x"] = str(float(vertex.attrib["x"]) + 0.05)
            tampered = Path(directory) / "shifted.3mf"
            _rewrite_archive(
                result.radial_path,
                tampered,
                {
                    "3D/Objects/radial_parts.model": ET.tostring(
                        root,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                },
            )
            with self.assertRaises((RadialExportError, BlackRadialCouponError)):
                validate_black_radial_coupon_3mf(tampered)

    def test_radial_reopen_rejects_hidden_part_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.radial_path) as archive:
                root = ET.fromstring(archive.read("Metadata/model_settings.config"))
            first_part = root.find("object/part")
            self.assertIsNotNone(first_part)
            ET.SubElement(
                first_part,
                "metadata",
                {"key": "wall_loops", "value": "9"},
            )
            tampered = Path(directory) / "override.3mf"
            _rewrite_archive(
                result.radial_path,
                tampered,
                {
                    "Metadata/model_settings.config": ET.tostring(
                        root,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                },
            )
            with self.assertRaisesRegex(RadialExportError, "allowlist"):
                validate_radial_3mf(tampered)

    def test_conventional_reopen_rejects_disabled_used_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.conventional_path) as archive:
                project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
            rows = project["mixed_filament_definitions"].split(";")
            fields = rows[19].split(",")
            fields[2:4] = ["0", "0"]
            rows[19] = ",".join(fields)
            project["mixed_filament_definitions"] = ";".join(rows)
            tampered = Path(directory) / "disabled_ratio.3mf"
            _rewrite_archive(
                result.conventional_path,
                tampered,
                {
                    "Metadata/project_settings.config": json.dumps(
                        project,
                        ensure_ascii=False,
                        indent=2,
                    ).encode("utf-8")
                },
            )
            with self.assertRaisesRegex(
                BlackRadialCouponError,
                "not canonical",
            ):
                validate_black_radial_coupon_3mf(tampered)

    def test_conventional_reopen_rejects_physical_colour_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.conventional_path) as archive:
                project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
            project["filament_colour"] = ["#FF00FF"] * 4
            tampered = Path(directory) / "colour_drift.3mf"
            _rewrite_archive(
                result.conventional_path,
                tampered,
                {
                    "Metadata/project_settings.config": json.dumps(
                        project,
                        ensure_ascii=False,
                        indent=2,
                    ).encode("utf-8")
                },
            )
            with self.assertRaisesRegex(
                BlackRadialCouponError,
                "filament colours drifted",
            ):
                validate_black_radial_coupon_3mf(tampered)

    def test_conventional_reopen_rejects_translated_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.conventional_path) as archive:
                root = ET.fromstring(archive.read("3D/Objects/object_1.model"))
            first_object = next(item for item in root.iter() if item.tag.endswith("object"))
            for vertex in first_object.iter():
                if vertex.tag.endswith("vertex"):
                    vertex.attrib["x"] = str(float(vertex.attrib["x"]) + 0.05)
            tampered = Path(directory) / "translated_cell.3mf"
            _rewrite_archive(
                result.conventional_path,
                tampered,
                {
                    "3D/Objects/object_1.model": ET.tostring(
                        root,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                },
            )
            with self.assertRaisesRegex(
                BlackRadialCouponError,
                "vertices drifted",
            ):
                validate_black_radial_coupon_3mf(tampered)

    def test_conventional_reopen_rejects_component_transform_and_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.conventional_path) as archive:
                root = ET.fromstring(archive.read("3D/3dmodel.model"))
                settings = ET.fromstring(
                    archive.read("Metadata/model_settings.config")
                )
            component = next(
                item for item in root.iter() if item.tag.endswith("component")
            )
            component.attrib["transform"] = "1 0 0 0 1 0 0 0 1 1 0 0"
            transformed = Path(directory) / "component_transform.3mf"
            _rewrite_archive(
                result.conventional_path,
                transformed,
                {
                    "3D/3dmodel.model": ET.tostring(
                        root, encoding="utf-8", xml_declaration=True
                    )
                },
            )
            with self.assertRaisesRegex(BlackRadialCouponError, "transform"):
                validate_black_radial_coupon_3mf(transformed)

            config_object = settings.find("object")
            self.assertIsNotNone(config_object)
            ET.SubElement(
                config_object,
                "metadata",
                {"key": "wall_loops", "value": "9"},
            )
            overridden = Path(directory) / "object_override.3mf"
            _rewrite_archive(
                result.conventional_path,
                overridden,
                {
                    "Metadata/model_settings.config": ET.tostring(
                        settings, encoding="utf-8", xml_declaration=True
                    )
                },
            )
            with self.assertRaisesRegex(BlackRadialCouponError, "metadata"):
                validate_black_radial_coupon_3mf(overridden)

    def test_conventional_reopen_rejects_metadata_paint_collusion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.conventional_path) as archive:
                child = ET.fromstring(archive.read("3D/Objects/object_1.model"))
                metadata = json.loads(
                    archive.read("Metadata/black_radial_coupon.json")
                )
            first_object = next(
                item for item in child.iter() if item.tag.endswith("object")
            )
            for triangle in first_object.iter():
                if triangle.tag.endswith("triangle"):
                    triangle.attrib["paint_color"] = "3"
            metadata["cells"][0]["conventional_state_id"] = 3
            tampered = Path(directory) / "metadata_collusion.3mf"
            _rewrite_archive(
                result.conventional_path,
                tampered,
                {
                    "3D/Objects/object_1.model": ET.tostring(
                        child, encoding="utf-8", xml_declaration=True
                    ),
                    "Metadata/black_radial_coupon.json": json.dumps(
                        metadata, ensure_ascii=False, indent=2
                    ).encode("utf-8"),
                },
            )
            with self.assertRaisesRegex(BlackRadialCouponError, "deterministic"):
                validate_black_radial_coupon_3mf(tampered)

    def test_conventional_reopen_rejects_duplicate_and_unknown_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            duplicate = Path(directory) / "duplicate.3mf"
            duplicate.write_bytes(result.conventional_path.read_bytes())
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(duplicate, "a") as archive:
                    archive.writestr(
                        "Metadata/project_settings.config",
                        archive.read("Metadata/project_settings.config"),
                    )
            with self.assertRaisesRegex(BlackRadialCouponError, "duplicate"):
                validate_black_radial_coupon_3mf(duplicate)

            unknown = Path(directory) / "unknown.3mf"
            unknown.write_bytes(result.conventional_path.read_bytes())
            with zipfile.ZipFile(unknown, "a") as archive:
                archive.writestr("Metadata/unvalidated.txt", b"unexpected")
            with self.assertRaisesRegex(BlackRadialCouponError, "unvalidated"):
                validate_black_radial_coupon_3mf(unknown)

    def test_reopen_rejects_unknown_production_extension_and_bad_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.conventional_path) as archive:
                conventional_child = ET.fromstring(
                    archive.read("3D/Objects/object_1.model")
                )
            conventional_child.attrib["requiredextensions"] = "q"
            bad_extension = Path(directory) / "bad_extension.3mf"
            _rewrite_archive(
                result.conventional_path,
                bad_extension,
                {
                    "3D/Objects/object_1.model": ET.tostring(
                        conventional_child,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                },
            )
            with self.assertRaisesRegex(BlackRadialCouponError, "contract"):
                validate_black_radial_coupon_3mf(bad_extension)

            with zipfile.ZipFile(result.radial_path) as archive:
                radial_root = ET.fromstring(archive.read("3D/3dmodel.model"))
            uuid_key = next(
                key
                for item in radial_root.iter()
                for key in item.attrib
                if key.endswith("}UUID")
            )
            uuid_owner = next(
                item for item in radial_root.iter() if uuid_key in item.attrib
            )
            uuid_owner.attrib[uuid_key] = "NOT-A-UUID"
            bad_uuid = Path(directory) / "bad_uuid.3mf"
            _rewrite_archive(
                result.radial_path,
                bad_uuid,
                {
                    "3D/3dmodel.model": ET.tostring(
                        radial_root,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                },
            )
            with self.assertRaisesRegex(RadialExportError, "UUID"):
                validate_radial_3mf(bad_uuid)

    def test_reopen_rejects_schema_invalid_model_and_mesh_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.conventional_path) as archive:
                child = ET.fromstring(archive.read("3D/Objects/object_1.model"))
            first_object = next(
                item for item in child.iter() if item.tag.endswith("object")
            )
            namespace = child.tag.split("}", 1)[0] + "}"
            ET.SubElement(first_object, f"{namespace}components")
            invalid_mesh = Path(directory) / "mesh_and_components.3mf"
            _rewrite_archive(
                result.conventional_path,
                invalid_mesh,
                {
                    "3D/Objects/object_1.model": ET.tostring(
                        child, encoding="utf-8", xml_declaration=True
                    )
                },
            )
            with self.assertRaisesRegex(BlackRadialCouponError, "one mesh"):
                validate_black_radial_coupon_3mf(invalid_mesh)

            with zipfile.ZipFile(result.radial_path) as archive:
                radial_root = ET.fromstring(archive.read("3D/3dmodel.model"))
            radial_root.tag = f"{namespace}foo"
            invalid_root = Path(directory) / "invalid_root.3mf"
            _rewrite_archive(
                result.radial_path,
                invalid_root,
                {
                    "3D/3dmodel.model": ET.tostring(
                        radial_root, encoding="utf-8", xml_declaration=True
                    )
                },
            )
            with self.assertRaisesRegex(RadialExportError, "root element"):
                validate_radial_3mf(invalid_root)

    def test_radial_reopen_rejects_hidden_face_property(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_black_radial_coupon_bundle(Path(directory) / "bundle")
            with zipfile.ZipFile(result.radial_path) as archive:
                root = ET.fromstring(archive.read("3D/Objects/radial_parts.model"))
            triangle = next(item for item in root.iter() if item.tag.endswith("triangle"))
            triangle.attrib["paint_fuzzy_skin"] = "1"
            tampered = Path(directory) / "face_override.3mf"
            _rewrite_archive(
                result.radial_path,
                tampered,
                {
                    "3D/Objects/radial_parts.model": ET.tostring(
                        root,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                },
            )
            with self.assertRaisesRegex(RadialExportError, "face property"):
                validate_radial_3mf(tampered)


if __name__ == "__main__":
    unittest.main()
