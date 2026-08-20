from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

# Load the same runtime adapter as the packaged application before importing
# workflow.  It installs the portable 3MF writer used by part exports.
import spectrum_mapper_hotfix as hotfix
from spectrum_mapper import engine, workflow
from spectrum_mapper.models import (
    AppSettings,
    FilamentSnapshotRef,
    GeometrySettings,
    MeshLevel,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
    ToneSettings,
)
from spectrum_mapper.mixer import black_output_ratio_preset
from spectrum_mapper.part_names import rename_prepared_part


CORE_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
PART_NAMES = ("Warm shell", "Cool cape")
PART_KEYS = ("0:warm-shell", "1:cool-cape")
PRINT_PROFILE_008 = "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)"
WARM_FILAMENTS = ["#201008", "#FFE8D0", "#C06020", "#FF5030"]
COOL_FILAMENTS = ["#081830", "#E8F8FF", "#2080D0", "#60E0C0"]


def _two_watertight_tetrahedra() -> PreparedGeometry:
    first_vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    second_vertices = first_vertices + np.asarray([3.0, 0.0, 0.0])
    vertices = np.vstack((first_vertices, second_vertices))

    tetra_faces = np.asarray(
        [
            [0, 2, 1],
            [0, 1, 3],
            [0, 3, 2],
            [1, 2, 3],
        ],
        dtype=np.int32,
    )
    faces = np.vstack((tetra_faces, tetra_faces + 4))
    face_part_ids = np.repeat(np.arange(2, dtype=np.int16), 4)
    vertex_colors = np.vstack(
        (
            np.tile(np.asarray([0.30, 0.12, 0.06]), (4, 1)),
            np.tile(np.asarray([0.05, 0.18, 0.38]), (4, 1)),
        )
    )
    areas = engine.triangle_areas(vertices, faces)
    topology = engine.edge_topology(faces, len(vertices))
    if not topology["watertight"]:
        raise AssertionError(f"invalid test fixture topology: {topology}")

    level = MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=vertex_colors,
        areas_unit=areas,
        neighbors=engine.face_neighbors_partial(faces, len(vertices)),
        face_part_ids=face_part_ids,
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
    )
    source = ObjAsset(
        path=Path("two-watertight-parts.obj"),
        sha256="0" * 64,
        file_size=1,
        vertices=vertices.copy(),
        colors=vertex_colors.copy(),
        faces=faces.copy(),
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=[],
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
        face_part_ids=face_part_ids.copy(),
        part_face_counts=(4, 4),
        part_vertex_counts=(4, 4),
    )
    volume = engine.signed_volume(vertices, faces)
    return PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(vertices),
        clean_face_count=len(faces),
        removed_vertices=0,
        removed_faces=0,
        topology=topology,
        source_area_unit=float(areas.sum()),
        source_volume_unit=volume,
        simplified_area_unit=float(areas.sum()),
        simplified_volume_unit=volume,
        source_dimensions_unit=np.ptp(vertices, axis=0),
        warnings=[],
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
        part_stats=[
            {"name": name, "watertight_after_repair": True}
            for name in PART_NAMES
        ],
        assembly={"solidify_parts": True, "all_parts_watertight": True},
    )


def _settings_with_distinct_part_filaments() -> AppSettings:
    warm_ref = FilamentSnapshotRef(
        product_id="catalog:warm-f1",
        brand="Warm Maker",
        series="PLA",
        color_name="Dark Brown",
        matched_hex=WARM_FILAMENTS[0],
        finish_class="Standard / Opaque",
        source="catalog",
    )
    cool_ref = FilamentSnapshotRef(
        product_id="catalog:cool-f1",
        brand="Cool Maker",
        series="PLA Matte",
        color_name="Navy",
        matched_hex=COOL_FILAMENTS[0],
        finish_class="Matte",
        source="measured",
    )
    warm = PaletteSettings(
        physical_hex=list(WARM_FILAMENTS),
        physical_filament_refs=[warm_ref, None, None, None],
    )
    cool = PaletteSettings(
        physical_hex=list(COOL_FILAMENTS),
        physical_filament_refs=[cool_ref, None, None, None],
    )
    return AppSettings(
        geometry=GeometrySettings(
            height_mm=20.0,
            preserve_parts=True,
            solidify_parts=True,
            export_individual_parts=True,
        ),
        tone=ToneSettings(smoothing=False),
        palette=warm,
        part_palettes={PART_KEYS[1]: cool},
    )


def _read_exported_mesh(archive: ZipFile) -> tuple[ET.Element, np.ndarray]:
    object_xml = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    mesh_objects = object_xml.findall(f".//{CORE_NS}object")
    if len(mesh_objects) != 1:
        raise AssertionError(f"expected one mesh object, got {len(mesh_objects)}")
    triangles = mesh_objects[0].findall(f".//{CORE_NS}triangle")
    faces = np.asarray(
        [
            [int(triangle.attrib[key]) for key in ("v1", "v2", "v3")]
            for triangle in triangles
        ],
        dtype=np.int32,
    )
    return object_xml, faces


class IndividualPart3mfExportTests(unittest.TestCase):
    def test_each_part_is_a_standalone_watertight_008_project_with_manifest(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _settings_with_distinct_part_filaments()
        expected_filaments = (WARM_FILAMENTS, COOL_FILAMENTS)

        self.assertIs(workflow.write_3mf_atomic, hotfix._write_3mf_atomic_fixed)
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "assembly.3mf"
            paths = workflow._write_individual_part_models(
                prepared,
                settings,
                destination,
                manual_overrides=None,
                progress=None,
            )

            self.assertEqual(len(paths), 2)
            self.assertNotEqual(expected_filaments[0], expected_filaments[1])
            for index, (path, physical_filaments) in enumerate(
                zip(paths, expected_filaments, strict=True)
            ):
                with self.subTest(part=index, path=path.name):
                    self.assertTrue(path.is_file())
                    with ZipFile(path) as archive:
                        self.assertIsNone(archive.testzip())
                        object_xml, faces = _read_exported_mesh(archive)
                        root_xml = ET.fromstring(archive.read("3D/3dmodel.model"))
                        model_settings = ET.fromstring(
                            archive.read("Metadata/model_settings.config")
                        )
                        project_settings = json.loads(
                            archive.read("Metadata/project_settings.config").decode(
                                "utf-8"
                            )
                        )
                        palette_metadata = json.loads(
                            archive.read(
                                "Metadata/full_spectrum_palette.json"
                            ).decode("utf-8")
                        )
                        part_palette_metadata = json.loads(
                            archive.read(
                                "Metadata/tripo_part_palettes.json"
                            ).decode("utf-8")
                        )

                    self.assertEqual(
                        len(object_xml.findall(f".//{CORE_NS}mesh")), 1
                    )
                    self.assertEqual(
                        len(root_xml.findall(f".//{CORE_NS}component")), 1
                    )
                    self.assertEqual(len(model_settings.findall(".//part")), 1)
                    self.assertEqual(len(faces), 4)
                    topology = engine.edge_topology(faces, 4)
                    self.assertTrue(topology["watertight"], topology)
                    self.assertEqual(topology["boundary_edges"], 0)
                    self.assertEqual(topology["nonmanifold_edges"], 0)
                    self.assertEqual(topology["inconsistent_winding_edges"], 0)

                    self.assertEqual(
                        project_settings["filament_colour"], physical_filaments
                    )
                    self.assertEqual(
                        project_settings["filament_multi_colors"],
                        physical_filaments,
                    )
                    self.assertEqual(len(project_settings["filament_colour"]), 4)
                    self.assertEqual(
                        project_settings["filament_settings_id"],
                        ["Generic PLA"] * 4,
                    )
                    expected_product_id = (
                        "catalog:warm-f1" if index == 0 else "catalog:cool-f1"
                    )
                    self.assertEqual(
                        palette_metadata["physical_filament_refs"][0]["product_id"],
                        expected_product_id,
                    )
                    self.assertEqual(
                        part_palette_metadata["global_palette"][
                            "physical_filament_refs"
                        ][0]["product_id"],
                        expected_product_id,
                    )
                    self.assertEqual(
                        project_settings["print_settings_id"], PRINT_PROFILE_008
                    )
                    self.assertEqual(project_settings["layer_height"], "0.08")
                    self.assertEqual(
                        project_settings["initial_layer_print_height"], "0.2"
                    )
                    self.assertEqual(
                        project_settings["adaptive_layer_height"], "0"
                    )
                    self.assertNotIn("surface_shell", palette_metadata)
                    self.assertNotIn("wall_loops", project_settings)
                    self.assertNotIn("wall_generator", project_settings)
                    self.assertNotIn("outer_wall_line_width", project_settings)
                    self.assertNotIn("inner_wall_line_width", project_settings)
                    self.assertNotIn(
                        ",cm1,",
                        project_settings["mixed_filament_definitions"],
                    )
                    self.assertNotIn("enable_support", project_settings)
                    self.assertFalse(
                        any(key.startswith("support_") for key in project_settings)
                    )
                    model_metadata_keys = {
                        metadata.attrib.get("key")
                        for metadata in model_settings.findall(".//metadata")
                    }
                    self.assertNotIn("enable_support", model_metadata_keys)

            manifest_path = paths[0].parent / "パーツ別3MF_manifest.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(
                manifest["schema"], "tripo-spectrum-mapper.part-exports.v1"
            )
            self.assertEqual(manifest["source_assembly"], destination.name)
            self.assertEqual(manifest["layer_height_mm"], 0.08)
            self.assertEqual(manifest["initial_layer_height_mm"], 0.2)
            self.assertIs(manifest["support_fixed"], False)
            self.assertEqual(len(manifest["parts"]), 2)

            for index, (record, path, physical_filaments) in enumerate(
                zip(manifest["parts"], paths, expected_filaments, strict=True)
            ):
                with self.subTest(manifest_part=index):
                    self.assertEqual(record["index"], index)
                    self.assertEqual(record["name"], PART_NAMES[index])
                    self.assertEqual(record["key"], PART_KEYS[index])
                    self.assertEqual(record["file"], path.name)
                    self.assertEqual(record["faces"], 4)
                    self.assertIs(record["watertight"], True)
                    self.assertEqual(
                        record["physical_filaments"], physical_filaments
                    )
                    self.assertEqual(
                        record["physical_filament_refs"][0]["product_id"],
                        (
                            "catalog:warm-f1"
                            if index == 0
                            else "catalog:cool-f1"
                        ),
                    )
                    self.assertEqual(
                        record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
                    )

    def test_global_black_ratio_is_inherited_while_shell_request_is_suppressed(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _settings_with_distinct_part_filaments()
        expected_output = black_output_ratio_preset(0)
        settings.palette.output_mix_ratios_b = list(expected_output)
        settings.palette.surface_shell_enabled = True
        expected_filaments = (WARM_FILAMENTS, COOL_FILAMENTS)

        with tempfile.TemporaryDirectory() as folder:
            paths = workflow._write_individual_part_models(
                prepared,
                settings,
                Path(folder) / "assembly.3mf",
                manual_overrides=None,
                progress=None,
            )

            self.assertEqual(len(paths), 2)
            for index, (path, physical_filaments) in enumerate(
                zip(paths, expected_filaments, strict=True)
            ):
                with self.subTest(part=index):
                    with ZipFile(path) as archive:
                        project_settings = json.loads(
                            archive.read("Metadata/project_settings.config").decode(
                                "utf-8"
                            )
                        )
                        palette_metadata = json.loads(
                            archive.read(
                                "Metadata/full_spectrum_palette.json"
                            ).decode("utf-8")
                        )

                    self.assertEqual(
                        project_settings["filament_colour"], physical_filaments
                    )
                    self.assertEqual(
                        palette_metadata["physical_slot_order"], physical_filaments
                    )
                    self.assertEqual(
                        palette_metadata["output_mix_ratios_b_percent"],
                        expected_output,
                    )
                    self.assertNotIn("surface_shell", palette_metadata)
                    for key in (
                        "wall_loops",
                        "wall_generator",
                        "outer_wall_line_width",
                        "inner_wall_line_width",
                        "support_filament",
                        "support_interface_filament",
                        "flush_into_infill",
                        "flush_into_support",
                        "flush_into_objects",
                    ):
                        self.assertNotIn(key, project_settings)
                    self.assertNotIn("enable_support", project_settings)
                    definitions = project_settings[
                        "mixed_filament_definitions"
                    ].split(";")
                    self.assertEqual(
                        sum(",cm1," in definition for definition in definitions),
                        0,
                    )

        # Export inheritance must not silently turn each saved local palette
        # into a copy of the global physical/display palette.
        self.assertEqual(
            settings.part_palettes[PART_KEYS[1]].physical_hex,
            COOL_FILAMENTS,
        )
        self.assertIsNone(
            settings.part_palettes[PART_KEYS[1]].output_mix_ratios_b
        )
        self.assertFalse(
            settings.part_palettes[PART_KEYS[1]].surface_shell_enabled
        )

    def test_explicit_local_output_ratios_take_priority_over_global_policy(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _settings_with_distinct_part_filaments()
        global_output = [75] * 28
        local_output = [80] * 28
        settings.palette.output_mix_ratios_b = list(global_output)
        settings.palette.surface_shell_enabled = True
        settings.part_palettes[PART_KEYS[1]].output_mix_ratios_b = list(
            local_output
        )

        with tempfile.TemporaryDirectory() as folder:
            paths = workflow._write_individual_part_models(
                prepared,
                settings,
                Path(folder) / "assembly.3mf",
                manual_overrides=None,
                progress=None,
            )
            exported = []
            for path in paths:
                with ZipFile(path) as archive:
                    metadata = json.loads(
                        archive.read(
                            "Metadata/full_spectrum_palette.json"
                        ).decode("utf-8")
                    )
                    project = json.loads(
                        archive.read(
                            "Metadata/project_settings.config"
                        ).decode("utf-8")
                    )
                exported.append((metadata, project))

        self.assertEqual(
            settings.part_palettes[PART_KEYS[1]].output_mix_ratios_b,
            local_output,
        )
        self.assertEqual(exported[0][0]["output_mix_ratios_b_percent"], global_output)
        self.assertEqual(exported[1][0]["output_mix_ratios_b_percent"], local_output)
        for metadata, project in exported:
            self.assertNotIn("surface_shell", metadata)
            self.assertNotIn(",cm1,", project["mixed_filament_definitions"])

    def test_inherited_black_preset_is_rebuilt_for_local_display_ratios(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _settings_with_distinct_part_filaments()
        settings.palette.output_mix_ratios_b = black_output_ratio_preset(
            0,
            settings.palette.mix_ratios_b,
            settings.palette.secondary_mix_ratios_b,
        )
        local = settings.part_palettes[PART_KEYS[1]]
        local.mix_ratios_b = [20, 30, 40, 45, 55, 60]
        local.secondary_mix_ratios_b = [80, 70, 60, 55, 45, 40]
        expected_local = black_output_ratio_preset(
            0,
            local.mix_ratios_b,
            local.secondary_mix_ratios_b,
        )

        with tempfile.TemporaryDirectory() as folder:
            paths = workflow._write_individual_part_models(
                prepared,
                settings,
                Path(folder) / "assembly.3mf",
                manual_overrides=None,
                progress=None,
            )
            with ZipFile(paths[1]) as archive:
                metadata = json.loads(
                    archive.read("Metadata/full_spectrum_palette.json").decode(
                        "utf-8"
                    )
                )

        self.assertEqual(
            metadata["output_mix_ratios_b_percent"],
            expected_local,
        )
        self.assertNotEqual(
            metadata["output_mix_ratios_b_percent"],
            settings.palette.output_mix_ratios_b,
        )
        self.assertEqual(local.mix_ratios_b, [20, 30, 40, 45, 55, 60])
        self.assertIsNone(local.output_mix_ratios_b)

    def test_local_surface_shell_request_exports_safe_local_ratio(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _settings_with_distinct_part_filaments()
        local = settings.part_palettes[PART_KEYS[1]]
        local.output_mix_ratios_b = black_output_ratio_preset(0)
        local.surface_shell_enabled = True
        self.assertFalse(settings.palette.surface_shell_enabled)
        self.assertIsNone(settings.palette.output_mix_ratios_b)

        with tempfile.TemporaryDirectory() as folder:
            paths = workflow._write_individual_part_models(
                prepared,
                settings,
                Path(folder) / "assembly.3mf",
                manual_overrides=None,
                progress=None,
            )
            rows = []
            for path in paths:
                with ZipFile(path) as archive:
                    project_settings = json.loads(
                        archive.read("Metadata/project_settings.config").decode(
                            "utf-8"
                        )
                    )
                    palette_metadata = json.loads(
                        archive.read(
                            "Metadata/full_spectrum_palette.json"
                        ).decode("utf-8")
                    )
                rows.append((project_settings, palette_metadata))

        global_project, global_metadata = rows[0]
        local_project, local_metadata = rows[1]
        self.assertNotIn("surface_shell", global_metadata)
        self.assertNotIn("wall_loops", global_project)
        self.assertNotIn(",cm1,", global_project["mixed_filament_definitions"])
        self.assertNotIn("surface_shell", local_metadata)
        self.assertNotIn("wall_loops", local_project)
        self.assertNotIn("wall_generator", local_project)
        self.assertEqual(
            local_metadata["output_mix_ratios_b_percent"],
            black_output_ratio_preset(0),
        )
        self.assertEqual(
            sum(
                ",cm1," in definition
                for definition in local_project[
                    "mixed_filament_definitions"
                ].split(";")
            ),
            0,
        )

    def test_renamed_part_is_used_by_individual_export_and_manifest(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _settings_with_distinct_part_filaments()
        rename_prepared_part(prepared, PART_KEYS[1], "青いマント")

        with tempfile.TemporaryDirectory() as folder:
            paths = workflow._write_individual_part_models(
                prepared,
                settings,
                Path(folder) / "assembly.3mf",
                manual_overrides=None,
                progress=None,
            )

            self.assertIn("青いマント", paths[1].name)
            manifest_path = next(paths[0].parent.glob("*_manifest.json"))
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual(manifest["parts"][1]["name"], "青いマント")
            self.assertEqual(manifest["parts"][1]["key"], PART_KEYS[1])
            self.assertEqual(
                manifest["parts"][1]["file"],
                paths[1].name,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
