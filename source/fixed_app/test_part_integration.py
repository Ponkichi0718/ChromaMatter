from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import engine
from spectrum_mapper.models import (
    ColorResult,
    MeshLevel,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
    ToneSettings,
)
from spectrum_mapper.paint import PaintSession

# Import the runtime adapter deliberately.  Besides testing the base writer
# retained by the adapter, this lets the final test exercise the same public
# writer that the packaged application calls.
import spectrum_mapper_hotfix as hotfix


CORE_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
PRODUCTION_NS = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
PART_NAMES = ("Skin & Body", "Cape <Blue>")
PART_KEYS = ("0:skin", "1:cape")
HEIGHT_MM = 10.0


def hex_rgb(value: str) -> np.ndarray:
    text = value.removeprefix("#")
    return np.asarray(
        [int(text[index : index + 2], 16) for index in (0, 2, 4)],
        dtype=np.float64,
    ) / 255.0


def palette_pair() -> tuple[PaletteSettings, PaletteSettings]:
    only_first = [True] + [False] * 31
    global_palette = PaletteSettings(
        physical_hex=["#FF2010", "#FFF0E0", "#301008", "#F09090"],
        enabled_states=only_first,
    )
    cape_palette = PaletteSettings(
        physical_hex=["#1020FF", "#FFF000", "#10D070", "#A040F0"],
        enabled_states=only_first,
    )
    return global_palette, cape_palette


def disconnected_two_part_level() -> MeshLevel:
    vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [4.0, 2.0, 0.0],
            [5.0, 2.0, 0.0],
            [4.0, 3.0, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int32)
    vertex_colors = np.full((6, 3), 0.45, dtype=np.float64)
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=vertex_colors,
        areas_unit=np.asarray([0.5, 0.5], dtype=np.float64),
        neighbors=np.full((2, 3), -1, dtype=np.int32),
        face_part_ids=np.asarray([0, 1], dtype=np.int32),
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
    )


def connected_two_part_level() -> MeshLevel:
    vertices = np.asarray(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
        dtype=np.float64,
    )
    faces = np.asarray([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=np.full((4, 3), 0.5, dtype=np.float64),
        areas_unit=np.asarray([0.5, 0.5], dtype=np.float64),
        neighbors=None,
        face_part_ids=np.asarray([0, 1], dtype=np.int32),
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
    )


def two_part_prepared() -> PreparedGeometry:
    level = disconnected_two_part_level()
    source = ObjAsset(
        path=Path("two-parts.obj"),
        sha256="0" * 64,
        file_size=1,
        vertices=level.vertices_unit.copy(),
        colors=level.vertex_colors.copy(),
        faces=level.faces.copy(),
        original_vertex_count=len(level.vertices_unit),
        original_face_count=len(level.faces),
        warnings=[],
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
        face_part_ids=level.face_part_ids.copy(),
        part_face_counts=(1, 1),
        part_vertex_counts=(3, 3),
    )
    return PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(level.vertices_unit),
        clean_face_count=len(level.faces),
        removed_vertices=0,
        removed_faces=0,
        topology={},
        source_area_unit=1.0,
        source_volume_unit=0.0,
        simplified_area_unit=1.0,
        simplified_volume_unit=0.0,
        source_dimensions_unit=np.ptp(level.vertices_unit, axis=0),
        warnings=[],
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
    )


def two_part_colors() -> ColorResult:
    level = disconnected_two_part_level()
    counts = np.zeros(32, dtype=np.int64)
    counts[0] = 2
    fractions = np.zeros(32, dtype=np.float64)
    fractions[0] = 1.0
    return ColorResult(
        tone_vertex_rgb=level.vertex_colors.copy(),
        source_face_rgb=level.vertex_colors[level.faces].mean(axis=1),
        palette_indices=np.asarray([0, 0], dtype=np.int8),
        target_face_rgb=np.zeros((2, 3), dtype=np.float64),
        delta_e=np.zeros(2, dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=0.0,
    )


def two_closed_part_prepared() -> PreparedGeometry:
    tetra_vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    tetra_faces = np.asarray(
        [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        dtype=np.int32,
    )
    vertices = np.vstack(
        (tetra_vertices, tetra_vertices + np.asarray([4.0, 2.0, 0.0]))
    )
    faces = np.vstack((tetra_faces, tetra_faces + 4)).astype(np.int32)
    part_ids = np.repeat(np.arange(2, dtype=np.int32), 4)
    vertex_colors = np.full((8, 3), 0.45, dtype=np.float64)
    level = MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=vertex_colors,
        areas_unit=engine.triangle_areas(vertices, faces),
        neighbors=engine.face_neighbors(faces, len(vertices)),
        face_part_ids=part_ids,
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
        face_provenance=np.zeros(8, dtype=np.uint8),
    )
    source = ObjAsset(
        path=Path("two-closed-parts.obj"),
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
        face_part_ids=part_ids.copy(),
        part_face_counts=(4, 4),
        part_vertex_counts=(4, 4),
        has_explicit_parts=True,
    )
    area = float(level.areas_unit.sum())
    return PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(vertices),
        clean_face_count=len(faces),
        removed_vertices=0,
        removed_faces=0,
        topology={
            "watertight": True,
            "boundary_edges": 0,
            "nonmanifold_edges": 0,
            "inconsistent_winding_edges": 0,
        },
        source_area_unit=area,
        source_volume_unit=1.0 / 3.0,
        simplified_area_unit=area,
        simplified_volume_unit=1.0 / 3.0,
        source_dimensions_unit=np.ptp(vertices, axis=0),
        warnings=[],
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
        assembly={
            "solidify_parts": True,
            "all_parts_watertight": True,
        },
    )


def two_closed_part_colors() -> ColorResult:
    prepared = two_closed_part_prepared()
    counts = np.zeros(32, dtype=np.int64)
    counts[0] = len(prepared.final.faces)
    fractions = np.zeros(32, dtype=np.float64)
    fractions[0] = 1.0
    return ColorResult(
        tone_vertex_rgb=prepared.final.vertex_colors.copy(),
        source_face_rgb=prepared.final.vertex_colors[
            prepared.final.faces
        ].mean(axis=1),
        palette_indices=np.zeros(len(prepared.final.faces), dtype=np.int8),
        target_face_rgb=np.zeros((len(prepared.final.faces), 3)),
        delta_e=np.zeros(len(prepared.final.faces)),
        smoothed_faces=0,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=0.0,
    )


class PartColourPipelineIntegrationTests(unittest.TestCase):
    def test_recolor_resolves_the_same_local_state_to_each_part_rgb(self) -> None:
        level = disconnected_two_part_level()
        global_palette, cape_palette = palette_pair()

        result = engine.recolor_level_parts(
            level,
            HEIGHT_MM,
            ToneSettings(smoothing=False),
            global_palette,
            {PART_KEYS[1]: cape_palette},
        )

        np.testing.assert_array_equal(result.palette_indices, [0, 0])
        np.testing.assert_allclose(
            result.target_face_rgb,
            [
                hex_rgb(global_palette.physical_hex[0]),
                hex_rgb(cape_palette.physical_hex[0]),
            ],
        )
        self.assertEqual(
            [item["part_key"] for item in result.part_metrics], list(PART_KEYS)
        )

    def test_manual_override_state_is_resolved_inside_each_part_palette(self) -> None:
        level = disconnected_two_part_level()
        global_palette, cape_palette = palette_pair()
        automatic = engine.recolor_level_parts(
            level,
            HEIGHT_MM,
            ToneSettings(smoothing=False),
            global_palette,
            {PART_KEYS[1]: cape_palette},
        )

        result = engine.apply_palette_overrides_parts(
            level,
            HEIGHT_MM,
            global_palette,
            {PART_KEYS[1]: cape_palette},
            automatic,
            np.asarray([1, 1], dtype=np.int8),
        )

        np.testing.assert_array_equal(result.palette_indices, [1, 1])
        np.testing.assert_allclose(
            result.target_face_rgb,
            [
                hex_rgb(global_palette.physical_hex[1]),
                hex_rgb(cape_palette.physical_hex[1]),
            ],
        )
        self.assertEqual(result.manual_override_faces, 2)

    def test_reducing_palette_size_remaps_high_manual_ids_per_part(self) -> None:
        level = disconnected_two_part_level()
        global_palette, cape_palette = palette_pair()
        global_palette.palette_state_count = 16
        cape_palette.palette_state_count = 24
        automatic = engine.recolor_level_parts(
            level,
            HEIGHT_MM,
            ToneSettings(smoothing=False),
            global_palette,
            {PART_KEYS[1]: cape_palette},
        )

        result = engine.apply_palette_overrides_parts(
            level,
            HEIGHT_MM,
            global_palette,
            {PART_KEYS[1]: cape_palette},
            automatic,
            np.asarray([31, 31], dtype=np.int8),
        )

        self.assertLess(int(result.palette_indices[0]), 16)
        self.assertLess(int(result.palette_indices[1]), 24)
        self.assertEqual(result.manual_override_faces, 2)


class PartPaintScopeIntegrationTests(unittest.TestCase):
    def test_allowed_face_mask_limits_brush_and_fill_to_selected_part(self) -> None:
        level = connected_two_part_level()
        selected_part = level.face_part_ids == 0

        brush = PaintSession(
            level,
            HEIGHT_MM,
            np.asarray([0, 0], dtype=np.int8),
        )
        brush.set_allowed_faces(selected_part)
        brush_changed = brush.paint_brush(
            0,
            3,
            radius_mm=100.0,
            protect_sharp_edges=False,
        )

        np.testing.assert_array_equal(brush_changed, [0])
        np.testing.assert_array_equal(brush.overrides, [3, -1])

        fill = PaintSession(
            level,
            HEIGHT_MM,
            np.asarray([0, 0], dtype=np.int8),
        )
        fill.set_allowed_faces(selected_part)
        fill_changed = fill.fill(0, 4)

        np.testing.assert_array_equal(fill_changed, [0])
        np.testing.assert_array_equal(fill.overrides, [4, -1])

        # Starting on a hidden/disallowed part must also be a no-op.
        blocked = fill.paint_brush(
            1,
            5,
            radius_mm=0.0,
            protect_sharp_edges=False,
        )
        self.assertEqual(len(blocked), 0)
        np.testing.assert_array_equal(fill.overrides, [4, -1])


class Multipart3mfIntegrationTests(unittest.TestCase):
    def _assert_multipart_archive(
        self,
        destination: Path,
        validation: dict[str, object],
        global_palette: PaletteSettings,
        cape_palette: PaletteSettings,
    ) -> None:
        self.assertEqual(validation["parts"], 2)
        self.assertEqual(validation["components"], 2)
        self.assertEqual(validation["palette_groups"], 2)
        self.assertTrue(validation["one_print_job_compatible"])

        with ZipFile(destination) as archive:
            object_xml = ET.fromstring(
                archive.read("3D/Objects/object_1.model")
            )
            root_xml = ET.fromstring(archive.read("3D/3dmodel.model"))
            settings_xml = ET.fromstring(
                archive.read("Metadata/model_settings.config")
            )
            palette_metadata = json.loads(
                archive.read("Metadata/tripo_part_palettes.json").decode(
                    "utf-8"
                )
            )

        mesh_objects = object_xml.findall(f".//{CORE_NS}object")
        self.assertEqual(len(mesh_objects), 2)
        self.assertEqual(
            [item.attrib["name"] for item in mesh_objects], list(PART_NAMES)
        )
        expected_vertices = (
            np.asarray(
                [
                    [0, 0, 0],
                    [10, 0, 0],
                    [0, 10, 0],
                    [0, 0, 10],
                ],
                dtype=np.float64,
            ),
            np.asarray(
                [
                    [40, 20, 0],
                    [50, 20, 0],
                    [40, 30, 0],
                    [40, 20, 10],
                ],
                dtype=np.float64,
            ),
        )
        for part_index, (mesh_object, expected) in enumerate(
            zip(mesh_objects, expected_vertices, strict=True)
        ):
            with self.subTest(part_coordinates=part_index):
                vertices = np.asarray(
                    [
                        [
                            float(vertex.attrib[axis])
                            for axis in ("x", "y", "z")
                        ]
                        for vertex in mesh_object.findall(
                            f".//{CORE_NS}vertex"
                        )
                    ]
                )
                np.testing.assert_allclose(vertices, expected)
                self.assertEqual(
                    len(mesh_object.findall(f".//{CORE_NS}triangle")), 4
                )

        components = root_xml.findall(f".//{CORE_NS}component")
        self.assertEqual(len(components), 2)
        self.assertEqual(
            [item.attrib["objectid"] for item in components], ["1", "2"]
        )
        self.assertTrue(
            all(
                item.attrib["transform"]
                == "1 0 0 0 1 0 0 0 1 0 0 0"
                for item in components
            )
        )
        self.assertTrue(
            all(
                item.attrib[f"{PRODUCTION_NS}path"]
                == "/3D/Objects/object_1.model"
                for item in components
            )
        )

        settings_parts = settings_xml.findall(".//part")
        self.assertEqual(len(settings_parts), 2)
        settings_names = []
        for part in settings_parts:
            name_node = part.find("./metadata[@key='name']")
            self.assertIsNotNone(name_node)
            settings_names.append(name_node.attrib["value"])
        self.assertEqual(settings_names, list(PART_NAMES))

        self.assertEqual(
            palette_metadata["schema"],
            "tripo-spectrum-mapper.part-palettes.v1",
        )
        self.assertEqual(palette_metadata["required_palette_groups"], 2)
        self.assertFalse(
            palette_metadata["stored_part_palettes_one_job_compatible"]
        )
        self.assertTrue(palette_metadata["one_print_job_compatible"])
        self.assertEqual(
            palette_metadata["print_assignment_mode"], "global-common-4"
        )
        self.assertEqual(
            [part["key"] for part in palette_metadata["parts"]],
            list(PART_KEYS),
        )
        self.assertEqual(
            [part["name"] for part in palette_metadata["parts"]],
            list(PART_NAMES),
        )
        self.assertEqual(
            [part["face_count"] for part in palette_metadata["parts"]],
            [4, 4],
        )
        self.assertEqual(
            [part["palette_group"] for part in palette_metadata["parts"]],
            [0, 1],
        )
        self.assertEqual(
            [part["uses_individual_palette"] for part in palette_metadata["parts"]],
            [False, True],
        )
        self.assertEqual(
            palette_metadata["parts"][0]["palette"]["physical_hex"],
            global_palette.physical_hex,
        )
        self.assertEqual(
            palette_metadata["parts"][1]["palette"]["physical_hex"],
            cape_palette.physical_hex,
        )

    def _write(
        self,
        writer,
        destination: Path,
    ) -> tuple[dict[str, object], PaletteSettings, PaletteSettings]:
        global_palette, cape_palette = palette_pair()
        validation = writer(
            destination,
            two_closed_part_prepared(),
            two_closed_part_colors(),
            HEIGHT_MM,
            global_palette,
            {PART_KEYS[1]: cape_palette},
            True,
        )
        return validation, global_palette, cape_palette

    def test_writer_rejects_different_part_palettes_without_explicit_common_mode(
        self,
    ) -> None:
        global_palette, cape_palette = palette_pair()
        for writer in (
            hotfix._original_write_3mf_atomic,
            engine.write_3mf_atomic,
        ):
            with self.subTest(writer=writer.__name__), tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / "invalid-multipart.3mf"
                with self.assertRaisesRegex(
                    engine.EngineError,
                    "different part palettes cannot share one 3MF",
                ):
                    writer(
                        destination,
                        two_part_prepared(),
                        two_part_colors(),
                        HEIGHT_MM,
                        global_palette,
                        {PART_KEYS[1]: cape_palette},
                        False,
                    )
                self.assertFalse(destination.exists())

    def test_base_writer_preserves_two_parts_and_palette_group_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "multipart-base.3mf"
            validation, global_palette, cape_palette = self._write(
                hotfix._original_write_3mf_atomic,
                destination,
            )

            self._assert_multipart_archive(
                destination,
                validation,
                global_palette,
                cape_palette,
            )

    def test_public_writer_after_hotfix_keeps_multipart_structure(self) -> None:
        self.assertIs(engine.write_3mf_atomic, hotfix._write_3mf_atomic_fixed)
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "multipart-hotfix.3mf"
            validation, global_palette, cape_palette = self._write(
                engine.write_3mf_atomic,
                destination,
            )

            self._assert_multipart_archive(
                destination,
                validation,
                global_palette,
                cape_palette,
            )
            self.assertTrue(validation["portable_basematerials"])
            self.assertTrue(validation["portable_material_faces_match"])
            self.assertTrue(validation["portable_and_orca_states_match"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
