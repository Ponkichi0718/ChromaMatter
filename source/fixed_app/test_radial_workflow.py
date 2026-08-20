from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import numpy as np
import trimesh


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.engine import edge_topology, signed_volume, triangle_areas
from spectrum_mapper.models import (
    AppSettings,
    GeometrySettings,
    MeshLevel,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
    RadialSettings,
    ToneSettings,
)
from spectrum_mapper.radial_workflow import export_radial_bundle
from spectrum_mapper.radial_shell import RadialShellError


def _uniform_cube() -> PreparedGeometry:
    mesh = trimesh.creation.box(extents=(10.0, 8.0, 6.0))
    vertices_mm = np.asarray(mesh.vertices, dtype=np.float64)
    vertices_unit = vertices_mm / 6.0
    faces = np.asarray(mesh.faces, dtype=np.int32)
    colours = np.tile(
        np.asarray((0.55, 0.10, 0.10), dtype=np.float64),
        (len(vertices_mm), 1),
    )
    areas_mm2 = triangle_areas(vertices_mm, faces)
    areas_unit = areas_mm2 / 36.0
    part_ids = np.zeros(len(faces), dtype=np.int16)
    names = ("uniform cube",)
    keys = ("uniform-cube",)
    level = MeshLevel(
        vertices_unit=vertices_unit,
        faces=faces,
        vertex_colors=colours,
        areas_unit=areas_unit,
        neighbors=None,
        face_part_ids=part_ids,
        part_names=names,
        part_keys=keys,
        face_provenance=np.zeros(len(faces), dtype=np.uint8),
    )
    source = ObjAsset(
        path=Path("uniform-cube.obj"),
        sha256="a" * 64,
        file_size=1,
        vertices=vertices_unit.copy(),
        colors=colours.copy(),
        faces=faces.copy(),
        original_vertex_count=len(vertices_mm),
        original_face_count=len(faces),
        warnings=[],
        part_names=names,
        part_keys=keys,
        face_part_ids=part_ids.copy(),
        part_face_counts=(len(faces),),
        part_vertex_counts=(len(vertices_mm),),
        part_marker_kind="object",
        has_explicit_parts=True,
    )
    source_volume = signed_volume(vertices_unit, faces)
    return PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(vertices_mm),
        clean_face_count=len(faces),
        removed_vertices=0,
        removed_faces=0,
        topology=edge_topology(faces, len(vertices_mm)),
        source_area_unit=float(areas_unit.sum()),
        source_volume_unit=source_volume,
        simplified_area_unit=float(areas_unit.sum()),
        simplified_volume_unit=source_volume,
        source_dimensions_unit=np.ptp(vertices_unit, axis=0),
        warnings=[],
        part_names=names,
        part_keys=keys,
        part_stats=[{"id": 0}],
        assembly={"all_parts_watertight": True},
    )


class RadialWorkflowTests(unittest.TestCase):
    def test_uniform_automatic_state_exports_physical_only_project(self) -> None:
        prepared = _uniform_cube()
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=6.0,
                adjust_face_count=False,
                min_component_faces=1,
            ),
            tone=ToneSettings(smoothing=False),
            palette=PaletteSettings(
                physical_hex=["#111111", "#FFFFFF", "#FF0000", "#C08040"],
                enabled_states=[
                    index == 4 for index in range(32)
                ],
            ),
            radial=RadialSettings(
                outer_skin_thickness_mm=0.15,
                layer_height_mm=0.20,
                require_uniform_black_mix=True,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "uniform-radial.3mf"
            result = export_radial_bundle(
                prepared,
                settings,
                destination,
                black_slot=0,
            )

            self.assertTrue(result.model_path.is_file())
            self.assertTrue(result.report_path.is_file())
            self.assertTrue(result.guide_path.is_file())
            self.assertEqual(result.validation["parts"], 2)
            self.assertEqual(
                result.validation["physical_extruders"], [1, 2]
            )
            self.assertTrue(result.validation["static_validation_ok"])
            with zipfile.ZipFile(result.model_path) as archive:
                metadata = json.loads(
                    archive.read(
                        "Metadata/radial_shell_experimental.json"
                    ).decode("utf-8")
                )
                project = json.loads(
                    archive.read("Metadata/project_settings.config").decode(
                        "utf-8"
                    )
                )
                model_settings = archive.read(
                    "Metadata/model_settings.config"
                ).decode("utf-8")

            self.assertEqual(metadata["normal_part_count"], 2)
            self.assertEqual(metadata["black_extruder"], 1)
            self.assertEqual(
                [part["role"] for part in metadata["parts"]],
                ["pure_black_core", "partner_outer_shell"],
            )
            generator = metadata["generator_metadata"]
            # Automatic recolouring (not a manual paint override) must have
            # selected zero-based state 4, stable/UI state ID 5.
            self.assertEqual(generator["source_state_id"], 4)
            self.assertEqual(generator["ratio_definitions"], 0)
            self.assertEqual(generator["cycle_definitions"], 0)
            self.assertEqual(generator["painted_triangles"], 0)
            self.assertTrue(generator["source_exterior_preserved_exactly"])
            self.assertEqual(generator["positive_overlap_mm3"], 0.0)
            self.assertEqual(generator["gap_mm"], 0.0)
            self.assertAlmostEqual(
                generator["source_volume_mm3"],
                generator["output_volume_mm3"],
                places=9,
            )
            self.assertEqual(project["mixed_filament_definitions"], "")
            self.assertEqual(project["sparse_infill_density"], "100%")
            self.assertEqual(project["wall_generator"], "classic")
            self.assertEqual(project["detect_thin_wall"], "1")
            self.assertEqual(project["enable_support"], "0")
            self.assertEqual(project["brim_type"], "no_brim")
            self.assertEqual(project["flush_multiplier"], "0")
            self.assertEqual(model_settings.count('subtype="normal_part"'), 2)
            self.assertNotIn("paint_color", model_settings)

    def test_selected_non_darkest_slot_fails_before_writing(self) -> None:
        prepared = _uniform_cube()
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=6.0,
                adjust_face_count=False,
                min_component_faces=1,
            ),
            tone=ToneSettings(smoothing=False),
            palette=PaletteSettings(
                physical_hex=["#111111", "#FFFFFF", "#FF0000", "#C08040"],
                enabled_states=[index == 5 for index in range(32)],
            ),
            radial=RadialSettings(),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "wrong-black.3mf"
            with self.assertRaises(RadialShellError) as caught:
                export_radial_bundle(
                    prepared,
                    settings,
                    destination,
                    black_slot=2,
                )
            self.assertEqual(caught.exception.code, "selected_black_not_darkest")
            self.assertFalse(destination.exists())

    def test_tied_darkest_slots_fail_before_writing(self) -> None:
        prepared = _uniform_cube()
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=6.0,
                adjust_face_count=False,
                min_component_faces=1,
            ),
            tone=ToneSettings(smoothing=False),
            palette=PaletteSettings(
                physical_hex=["#111111", "#111111", "#FF0000", "#C08040"],
                enabled_states=[index == 4 for index in range(32)],
            ),
            radial=RadialSettings(),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "tied-black.3mf"
            with self.assertRaises(RadialShellError) as caught:
                export_radial_bundle(
                    prepared,
                    settings,
                    destination,
                    black_slot=0,
                )
            self.assertEqual(
                caught.exception.code,
                "unique_darkest_black_required",
            )
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
