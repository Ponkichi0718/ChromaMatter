from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

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
    RADIAL_CONVERSION_SELECTIVE_HYBRID,
    RADIAL_SKIN_MODE_ADAPTIVE,
    RadialSettings,
    ToneSettings,
)
from spectrum_mapper.radial_workflow import (
    analyze_radial_partner_contrast,
    export_radial_bundle,
)
from spectrum_mapper.radial_export import (
    RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010,
    RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
    RADIAL_PROCESS_PROFILE_MVP_020,
)
from spectrum_mapper.radial_shell import RadialShellError
import spectrum_mapper.radial_workflow as radial_workflow_module


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


def _two_part_cubes() -> PreparedGeometry:
    left = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    right = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    left.apply_translation((-2.0, 0.0, 1.0))
    right.apply_translation((2.0, 0.0, 1.0))
    vertices = np.vstack((left.vertices, right.vertices)).astype(np.float64)
    left_faces = np.asarray(left.faces, dtype=np.int32)
    right_faces = np.asarray(right.faces, dtype=np.int32) + len(left.vertices)
    faces = np.vstack((left_faces, right_faces)).astype(np.int32)
    colors = np.tile(
        np.asarray((0.55, 0.10, 0.10), dtype=np.float64),
        (len(vertices), 1),
    )
    part_ids = np.concatenate(
        (
            np.zeros(len(left_faces), dtype=np.int16),
            np.ones(len(right_faces), dtype=np.int16),
        )
    )
    names = ("left", "right head")
    keys = ("part:left", "part:right")
    level = MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=colors,
        areas_unit=triangle_areas(vertices, faces),
        neighbors=None,
        face_part_ids=part_ids,
        part_names=names,
        part_keys=keys,
        face_provenance=np.zeros(len(faces), dtype=np.uint8),
    )
    source = ObjAsset(
        path=Path("two-cubes.obj"),
        sha256="b" * 64,
        file_size=1,
        vertices=vertices.copy(),
        colors=colors.copy(),
        faces=faces.copy(),
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=[],
        part_names=names,
        part_keys=keys,
        face_part_ids=part_ids.copy(),
        part_face_counts=(len(left_faces), len(right_faces)),
        part_vertex_counts=(len(left.vertices), len(right.vertices)),
        part_marker_kind="object",
        has_explicit_parts=True,
    )
    volume = signed_volume(vertices, faces)
    return PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(vertices),
        clean_face_count=len(faces),
        removed_vertices=0,
        removed_faces=0,
        topology=edge_topology(faces, len(vertices)),
        source_area_unit=float(level.areas_unit.sum()),
        source_volume_unit=volume,
        simplified_area_unit=float(level.areas_unit.sum()),
        simplified_volume_unit=volume,
        source_dimensions_unit=np.ptp(vertices, axis=0),
        warnings=[],
        part_names=names,
        part_keys=keys,
        part_stats=[{"id": 0}, {"id": 1}],
        assembly={"all_parts_watertight": True},
    )


class RadialWorkflowTests(unittest.TestCase):
    def test_adaptive_stage_b_rejects_per_part_mix_override_mismatch(self) -> None:
        first = PaletteSettings(
            physical_hex=["#111111", "#FFFFFF", "#FF0000", "#C08040"],
        )
        second = PaletteSettings(
            physical_hex=["#111111", "#FFFFFF", "#FF0000", "#C08040"],
        )
        second.mix_hex_overrides[0] = "#D0D0D0"
        with patch(
            "spectrum_mapper.radial_workflow.resolve_part_palette_settings",
            return_value=(first, second),
        ):
            with self.assertRaises(RadialShellError) as caught:
                radial_workflow_module._shared_stage_b_palette(
                    AppSettings(),
                    SimpleNamespace(),
                )
        self.assertEqual(caught.exception.code, "single_palette_required")

    def test_selected_part_selective_hybrid_uses_local_palette_and_manual_subset(
        self,
    ) -> None:
        prepared = _two_part_cubes()
        left_palette = PaletteSettings(
            physical_hex=["#111111", "#FFFFFF", "#FF0000", "#C08040"],
        )
        right_palette = PaletteSettings(
            physical_hex=["#080808", "#EEEEEE", "#CC2233", "#73452D"],
        )
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=6.0,
                adjust_face_count=False,
                min_component_faces=1,
            ),
            tone=ToneSettings(smoothing=False),
            palette=left_palette,
            part_palettes={
                "part:left": left_palette,
                "part:right": right_palette,
            },
            radial=RadialSettings(
                experimental_enabled=True,
                outer_skin_thickness_mm=0.15,
                layer_height_mm=0.10,
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
                skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
                adaptive_skin_min_thickness_mm=0.10,
                adaptive_skin_max_thickness_mm=0.30,
                adaptive_skin_gamma=1.0,
                adaptive_skin_bands=5,
                wall_generator="arachne",
            ),
        )
        labels = np.full(12, 4, dtype=np.int16)
        manual = np.full(len(prepared.final.faces), -1, dtype=np.int8)
        manual[12:] = 4
        captured: dict[str, object] = {}

        def apply_overrides(level, _height, _palette, _part_palettes, colors, values):
            captured["manual"] = np.asarray(values).copy()
            captured["override_level"] = level
            return colors

        def build(selected, _height, _states, _eligible, _black, _depth, **kwargs):
            captured["prepared"] = selected
            captured["state_skin_thickness_mm"] = dict(
                kwargs["state_skin_thickness_mm"]
            )
            plan = SimpleNamespace(
                radial_state_ids=(4,),
                conventional_state_ids=(),
                outer_skin_thickness_mm=0.15,
                state_outer_skin_thickness_mm=dict(
                    kwargs["state_skin_thickness_mm"]
                ),
                to_dict=lambda: {
                    "radial_state_ids": [4],
                    "conventional_state_ids": [],
                },
            )
            return SimpleNamespace(
                plan=plan,
                metadata={
                    "material_manifold": True,
                    "external_surface_coverage_exact": True,
                },
            )

        def package(hybrid, palette, **kwargs):
            captured["package_palette"] = palette
            captured["package_kwargs"] = dict(kwargs)
            return SimpleNamespace(hybrid=hybrid)

        def write(destination, _package, *, title):
            self.assertIn("Selective Hybrid", title)
            Path(destination).write_bytes(b"selected-stage-b")
            return SimpleNamespace(
                to_dict=lambda: {
                    "parts": 2,
                    "physical_extruders": [1, 2],
                    "static_validation_ok": True,
                    "physical_materials_only": False,
                }
            )

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "spectrum_mapper.radial_workflow.recolor_level_parts",
                    return_value=SimpleNamespace(palette_indices=labels),
                ),
                patch(
                    "spectrum_mapper.radial_workflow.apply_palette_overrides_parts",
                    side_effect=apply_overrides,
                ),
                patch(
                    "spectrum_mapper.radial_stage_b.build_selective_hybrid",
                    side_effect=build,
                ),
                patch(
                    "spectrum_mapper.radial_hybrid_export.package_from_selective_hybrid",
                    side_effect=package,
                ),
                patch(
                    "spectrum_mapper.radial_hybrid_export.write_hybrid_3mf_atomic",
                    side_effect=write,
                ),
            ):
                result = export_radial_bundle(
                    prepared,
                    settings,
                    Path(directory) / "right-head.3mf",
                    black_slot=0,
                    manual_overrides=manual,
                    part_key="part:right",
                )
            report = json.loads(
                result.report_path.read_text(encoding="utf-8-sig")
            )

        selected = captured["prepared"]
        self.assertEqual(selected.final.part_keys, ("part:right",))
        self.assertEqual(selected.final.part_names, ("right head",))
        self.assertEqual(len(selected.final.faces), 12)
        self.assertEqual(captured["override_level"].part_keys, ("part:right",))
        np.testing.assert_array_equal(
            captured["manual"],
            np.full(12, 4, dtype=np.int8),
        )
        self.assertIs(captured["package_palette"], right_palette)
        self.assertEqual(
            captured["package_kwargs"]["process_profile"],
            RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010,
        )
        self.assertEqual(
            captured["package_kwargs"]["layer_height_mm"],
            0.10,
        )
        self.assertEqual(set(captured["state_skin_thickness_mm"]), {4})
        self.assertEqual(report["source_part_count"], 1)
        self.assertEqual(report["source_assembly_part_count"], 2)
        self.assertEqual(report["selected_part_id"], 1)
        self.assertEqual(report["selected_part_key"], "part:right")
        self.assertEqual(report["selected_part_name"], "right head")
        self.assertEqual(report["physical_hex"], right_palette.physical_hex)
        self.assertEqual(report["skin_thickness_mode"], "adaptive")
        self.assertEqual(report["wall_generator"], "arachne")
        self.assertEqual(report["sparse_infill_density_percent"], 15)

    def test_whole_multipart_selective_hybrid_keeps_shared_palette_gate(self) -> None:
        prepared = _two_part_cubes()
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=6.0,
                adjust_face_count=False,
                min_component_faces=1,
            ),
            tone=ToneSettings(smoothing=False),
            palette=PaletteSettings(
                physical_hex=["#111111", "#FFFFFF", "#FF0000", "#C08040"],
            ),
            part_palettes={
                "part:right": PaletteSettings(
                    physical_hex=["#080808", "#EEEEEE", "#CC2233", "#73452D"],
                )
            },
            radial=RadialSettings(
                experimental_enabled=True,
                layer_height_mm=0.10,
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
                wall_generator="arachne",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "whole.3mf"
            with self.assertRaises(RadialShellError) as caught:
                export_radial_bundle(
                    prepared,
                    settings,
                    destination,
                    black_slot=0,
                )
            self.assertFalse(destination.exists())
        self.assertEqual(caught.exception.code, "single_palette_required")

    def test_radial_part_selection_and_manual_shape_are_fail_closed(self) -> None:
        prepared = _two_part_cubes()
        settings = AppSettings(
            radial=RadialSettings(
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
            )
        )
        cases = (
            ({"part_key": "missing"}, "part_key_not_found"),
            ({"part_id": 9}, "part_id_out_of_range"),
            (
                {"part_key": "part:left", "part_id": 0},
                "part_selection_conflict",
            ),
            (
                {
                    "part_key": "part:right",
                    "manual_overrides": np.full(12, -1, dtype=np.int8),
                },
                "invalid_manual_overrides",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "invalid.3mf"
            for kwargs, code in cases:
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises(RadialShellError) as caught:
                        export_radial_bundle(
                            prepared,
                            settings,
                            destination,
                            black_slot=0,
                            **kwargs,
                        )
                    self.assertEqual(caught.exception.code, code)
                    self.assertFalse(destination.exists())

    def test_selected_uniform_report_records_source_assembly_provenance(self) -> None:
        prepared = _two_part_cubes()
        right_palette = PaletteSettings(
            physical_hex=["#080808", "#EEEEEE", "#CC2233", "#73452D"],
            enabled_states=[index == 4 for index in range(32)],
        )
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=6.0,
                adjust_face_count=False,
                min_component_faces=1,
            ),
            tone=ToneSettings(smoothing=False),
            palette=PaletteSettings(
                physical_hex=["#111111", "#FFFFFF", "#FF0000", "#C08040"],
            ),
            part_palettes={"part:right": right_palette},
            radial=RadialSettings(
                experimental_enabled=True,
                outer_skin_thickness_mm=0.15,
                layer_height_mm=0.20,
            ),
        )
        labels = np.full(12, 4, dtype=np.int16)
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "spectrum_mapper.radial_workflow.recolor_level_parts",
                return_value=SimpleNamespace(palette_indices=labels),
            ):
                result = export_radial_bundle(
                    prepared,
                    settings,
                    Path(directory) / "right-uniform.3mf",
                    black_slot=0,
                    part_id=1,
                )
            report = json.loads(
                result.report_path.read_text(encoding="utf-8-sig")
            )

        self.assertEqual(report["source_part_count"], 1)
        self.assertEqual(report["source_assembly_part_count"], 2)
        self.assertEqual(report["selected_part_id"], 1)
        self.assertEqual(report["selected_part_key"], "part:right")
        self.assertEqual(report["selected_part_name"], "right head")
        self.assertEqual(report["source_part"], "right head")
        self.assertEqual(report["physical_hex"], right_palette.physical_hex)

    def test_selective_hybrid_routes_only_used_high_contrast_state(self) -> None:
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
            ),
            radial=RadialSettings(
                experimental_enabled=True,
                outer_skin_thickness_mm=0.15,
                layer_height_mm=0.10,
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
            ),
        )
        face_states = np.full(len(prepared.final.faces), 1, dtype=np.int16)
        face_states[:4] = 4
        plan = SimpleNamespace(
            radial_state_ids=(4,),
            conventional_state_ids=(1,),
            outer_skin_thickness_mm=0.15,
            state_outer_skin_thickness_mm={4: 0.15},
            to_dict=lambda: {
                "radial_state_ids": [4],
                "conventional_state_ids": [1],
            },
        )
        hybrid = SimpleNamespace(
            plan=plan,
            metadata={
                "material_manifold": True,
                "external_surface_coverage_exact": True,
            },
        )
        validation = SimpleNamespace(
            to_dict=lambda: {
                "parts": 2,
                "physical_extruders": [1, 2],
                "static_validation_ok": True,
                "physical_materials_only": False,
            }
        )

        def write(destination, package, *, title):
            self.assertEqual(package, "hybrid-package")
            self.assertIn("Selective Hybrid", title)
            Path(destination).write_bytes(b"test-stage-b")
            return validation

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "spectrum_mapper.radial_workflow.recolor_level_parts",
                    return_value=SimpleNamespace(palette_indices=face_states),
                ),
                patch(
                    "spectrum_mapper.radial_stage_b.build_selective_hybrid",
                    return_value=hybrid,
                ) as build,
                patch(
                    "spectrum_mapper.radial_hybrid_export.package_from_selective_hybrid",
                    return_value="hybrid-package",
                ) as package,
                patch(
                    "spectrum_mapper.radial_hybrid_export.write_hybrid_3mf_atomic",
                    side_effect=write,
                ),
            ):
                destination = Path(directory) / "selective-hybrid.3mf"
                result = export_radial_bundle(
                    prepared,
                    settings,
                    destination,
                    black_slot=0,
                )

            self.assertTrue(result.model_path.is_file())
            self.assertTrue(result.report_path.is_file())
            self.assertTrue(result.guide_path.is_file())
            self.assertEqual(result.validation["physical_materials_only"], False)
            self.assertEqual(result.layer_height_mm, 0.10)
            build.assert_called_once()
            self.assertEqual(build.call_args.args[3], {4: 2})
            self.assertEqual(build.call_args.args[4], 1)
            self.assertIsNone(
                build.call_args.kwargs["state_skin_thickness_mm"]
            )
            package.assert_called_once_with(
                hybrid,
                settings.palette,
                process_profile=RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
                layer_height_mm=0.10,
                initial_layer_height_mm=0.20,
            )
            report = json.loads(
                result.report_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual(
                report["conversion_mode"],
                RADIAL_CONVERSION_SELECTIVE_HYBRID,
            )
            self.assertEqual(report["selection"]["radial_state_ids"], [4])
            self.assertEqual(
                report["selection"]["conventional_state_ids"], [1]
            )
            guide = result.guide_path.read_text(encoding="utf-8-sig")
            self.assertIn("Selective Radial Hybrid Stage B", guide)
            self.assertIn("Pure black, low-delta-L", guide)
            self.assertIn("Sparse infill: 15%", guide)
            self.assertIn("SLICE ONLY", guide)

    def test_selective_hybrid_adaptive_mode_forwards_discrete_state_depths(self) -> None:
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
            ),
            radial=RadialSettings(
                experimental_enabled=True,
                outer_skin_thickness_mm=0.15,
                layer_height_mm=0.10,
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
                skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
                adaptive_skin_min_thickness_mm=0.10,
                adaptive_skin_max_thickness_mm=0.42,
                adaptive_skin_gamma=1.6,
                adaptive_skin_bands=6,
            ),
        )
        face_states = np.full(len(prepared.final.faces), 1, dtype=np.int16)
        face_states[:4] = 4
        face_states[4:8] = 10
        captured: dict[int, float] = {}

        def build(*args, **kwargs):
            captured.update(kwargs["state_skin_thickness_mm"])
            plan = SimpleNamespace(
                radial_state_ids=(4, 10),
                conventional_state_ids=(1,),
                outer_skin_thickness_mm=0.15,
                state_outer_skin_thickness_mm=dict(captured),
                to_dict=lambda: {
                    "radial_state_ids": [4, 10],
                    "conventional_state_ids": [1],
                    "state_outer_skin_thickness_mm": {
                        str(key): value for key, value in captured.items()
                    },
                },
            )
            return SimpleNamespace(
                plan=plan,
                metadata={
                    "material_manifold": True,
                    "external_surface_coverage_exact": True,
                },
            )

        def write(destination, _package, *, title):
            self.assertIn("Selective Hybrid", title)
            Path(destination).write_bytes(b"adaptive-stage-b")
            return SimpleNamespace(
                to_dict=lambda: {
                    "parts": 3,
                    "physical_extruders": [1, 2],
                    "static_validation_ok": True,
                    "physical_materials_only": False,
                }
            )

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "spectrum_mapper.radial_workflow.recolor_level_parts",
                    return_value=SimpleNamespace(palette_indices=face_states),
                ),
                patch(
                    "spectrum_mapper.radial_stage_b.build_selective_hybrid",
                    side_effect=build,
                ),
                patch(
                    "spectrum_mapper.radial_hybrid_export.package_from_selective_hybrid",
                    return_value="hybrid-package",
                ),
                patch(
                    "spectrum_mapper.radial_hybrid_export.write_hybrid_3mf_atomic",
                    side_effect=write,
                ),
            ):
                result = export_radial_bundle(
                    prepared,
                    settings,
                    Path(directory) / "adaptive-selective.3mf",
                    black_slot=0,
                )
            report = json.loads(
                result.report_path.read_text(encoding="utf-8-sig")
            )
            guide = result.guide_path.read_text(encoding="utf-8-sig")

        self.assertEqual(set(captured), {4, 10})
        self.assertGreater(captured[10], captured[4])
        self.assertTrue(
            all(
                0.10 <= value <= 0.42
                for value in captured.values()
            )
        )
        self.assertEqual(report["skin_thickness_mode"], "adaptive")
        self.assertEqual(
            report["adaptive_skin_thickness_schedule"]["band_count"],
            6,
        )
        self.assertAlmostEqual(
            report["adaptive_skin_thickness_schedule"][
                "maximum_thickness_mm"
            ],
            0.42,
        )
        self.assertAlmostEqual(
            report["adaptive_skin_thickness_schedule"]["gamma"],
            1.6,
        )
        self.assertIn("adaptive discrete depths", guide)

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
            self.assertEqual(
                result.process_profile,
                RADIAL_PROCESS_PROFILE_MVP_020,
            )
            self.assertEqual(result.wall_generator, "classic")
            report = json.loads(
                result.report_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual(report["minimum_lstar_delta"], 35.0)
            self.assertGreater(report["actual_lstar_delta"], 35.0)
            self.assertEqual(
                report["radial_partner_contrast"]["partner_extruder"],
                2,
            )
            self.assertTrue(
                report["radial_partner_contrast"]["qualifies"]
            )
            self.assertEqual(
                report["process_profile"],
                RADIAL_PROCESS_PROFILE_MVP_020,
            )
            self.assertEqual(report["wall_generator"], "classic")
            guide = result.guide_path.read_text(encoding="utf-8-sig")
            self.assertIn("Minimum CIELAB delta L*: 35.000", guide)
            self.assertIn("Actual CIELAB delta L*:", guide)
            self.assertIn("Partner slot: F2", guide)
            self.assertIn(
                f"Process profile: {RADIAL_PROCESS_PROFILE_MVP_020}",
                guide,
            )
            self.assertIn("Wall generator: classic", guide)
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

    def test_general_010_profile_follows_wall_generator(self) -> None:
        prepared = _uniform_cube()
        cases = (
            ("classic", RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010),
            ("arachne", RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010),
        )
        with tempfile.TemporaryDirectory() as directory:
            for wall_generator, expected_profile in cases:
                with self.subTest(wall_generator=wall_generator):
                    settings = AppSettings(
                        geometry=GeometrySettings(
                            height_mm=6.0,
                            adjust_face_count=False,
                            min_component_faces=1,
                        ),
                        tone=ToneSettings(smoothing=False),
                        palette=PaletteSettings(
                            physical_hex=[
                                "#111111",
                                "#FFFFFF",
                                "#FF0000",
                                "#C08040",
                            ],
                            enabled_states=[
                                index == 4 for index in range(32)
                            ],
                        ),
                        radial=RadialSettings(
                            outer_skin_thickness_mm=0.15,
                            layer_height_mm=0.10,
                            wall_generator=wall_generator,
                        ),
                    )
                    destination = (
                        Path(directory) / f"general-{wall_generator}.3mf"
                    )
                    result = export_radial_bundle(
                        prepared,
                        settings,
                        destination,
                        black_slot=0,
                    )

                    self.assertEqual(result.process_profile, expected_profile)
                    self.assertEqual(result.wall_generator, wall_generator)
                    self.assertEqual(result.layer_height_mm, 0.10)
                    report = json.loads(
                        result.report_path.read_text(encoding="utf-8-sig")
                    )
                    self.assertEqual(report["process_profile"], expected_profile)
                    self.assertEqual(
                        report["wall_generator"],
                        wall_generator,
                    )
                    self.assertEqual(report["layer_height_mm"], 0.10)
                    self.assertEqual(
                        report["sparse_infill_density_percent"],
                        15,
                    )
                    with zipfile.ZipFile(result.model_path) as archive:
                        metadata = json.loads(
                            archive.read(
                                "Metadata/radial_shell_experimental.json"
                            ).decode("utf-8")
                        )
                        project = json.loads(
                            archive.read(
                                "Metadata/project_settings.config"
                            ).decode("utf-8")
                        )
                    self.assertEqual(
                        metadata["process_profile"],
                        expected_profile,
                    )
                    self.assertEqual(project["layer_height"], "0.1")
                    self.assertEqual(
                        project["sparse_infill_density"],
                        "15%",
                    )
                    self.assertEqual(
                        project["wall_generator"],
                        wall_generator,
                    )

    def test_contrast_analysis_accepts_any_high_lightness_partner(self) -> None:
        settings = AppSettings(
            palette=PaletteSettings(
                physical_hex=["#111111", "#F2C94C", "#FF0000", "#C08040"],
            ),
            radial=RadialSettings(),
        )

        analysis = analyze_radial_partner_contrast(settings, black_slot=0)
        state = analysis.state(4)

        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(analysis.minimum_lstar_delta, 35.0)
        self.assertEqual(state.black_extruder, 1)
        self.assertEqual(state.partner_extruder, 2)
        self.assertGreater(state.lstar_delta, 35.0)
        self.assertTrue(state.qualifies)
        self.assertEqual(analysis.eligible_state_partners[4], 2)

    def test_future_minimum_lstar_delta_field_is_honoured(self) -> None:
        settings = AppSettings(
            palette=PaletteSettings(
                physical_hex=["#111111", "#FFFFFF", "#FF0000", "#C08040"],
            ),
            radial=RadialSettings(),
        )
        settings.radial.minimum_lstar_delta = 99.0

        analysis = analyze_radial_partner_contrast(settings, black_slot=0)
        state = analysis.state(4)

        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(analysis.minimum_lstar_delta, 99.0)
        self.assertFalse(state.qualifies)
        self.assertNotIn(4, analysis.eligible_state_partners)

    def test_legacy_020_arachne_combination_fails_before_writing(self) -> None:
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
                enabled_states=[index == 4 for index in range(32)],
            ),
            radial=RadialSettings(
                layer_height_mm=0.20,
                wall_generator="arachne",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "unsupported-020-arachne.3mf"
            with self.assertRaises(RadialShellError) as caught:
                export_radial_bundle(
                    prepared,
                    settings,
                    destination,
                    black_slot=0,
                )

            self.assertEqual(
                caught.exception.code,
                "unsupported_radial_process_combination",
            )
            self.assertFalse(destination.exists())

    def test_used_low_contrast_black_mix_fails_before_writing(self) -> None:
        prepared = _uniform_cube()
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=6.0,
                adjust_face_count=False,
                min_component_faces=1,
            ),
            tone=ToneSettings(smoothing=False),
            palette=PaletteSettings(
                physical_hex=["#111111", "#303030", "#FF0000", "#C08040"],
                enabled_states=[index == 4 for index in range(32)],
            ),
            radial=RadialSettings(),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "low-contrast.3mf"
            with self.assertRaises(RadialShellError) as caught:
                export_radial_bundle(
                    prepared,
                    settings,
                    destination,
                    black_slot=0,
                )

            self.assertEqual(caught.exception.code, "contrast_below_threshold")
            self.assertEqual(
                caught.exception.details["minimum_lstar_delta"],
                35.0,
            )
            self.assertLess(
                caught.exception.details["maximum_used_lstar_delta"],
                35.0,
            )
            self.assertFalse(destination.exists())
            self.assertFalse(
                destination.with_name(
                    destination.stem + "_radial_validation.json"
                ).exists()
            )
            self.assertFalse(
                destination.with_name(
                    destination.stem + "_SLICE_ONLY_guide.txt"
                ).exists()
            )

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
