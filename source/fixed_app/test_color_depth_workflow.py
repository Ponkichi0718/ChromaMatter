from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import trimesh

from spectrum_mapper.color_depth import (
    ColorDepthCellResult,
    ColorDepthMaterialPart,
)
from spectrum_mapper.color_depth_workflow import (
    ColorDepthWorkflowError,
    export_color_depth_bundle,
    export_color_depth_from_3mf,
    inspect_color_depth_3mf,
)
from spectrum_mapper.engine import edge_topology, signed_volume, triangle_areas
from spectrum_mapper.gui import _project_settings_from_mapping
from spectrum_mapper.models import (
    AppSettings,
    ColorDepthSettings,
    GeometrySettings,
    MeshLevel,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
    ToneSettings,
)
from test_radial_workflow import _uniform_cube
from test_color_depth_3mf_input import (
    PHYSICAL as IMPORTED_PHYSICAL,
    STATE_PAIRS as IMPORTED_STATE_PAIRS,
    _palette_metadata as _import_palette_metadata,
    _valid_members as _valid_import_members,
    _write_archive as _write_import_archive,
)


def _one_physical_union() -> ColorDepthCellResult:
    mesh = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int32)
    volume = float(mesh.volume)
    part = ColorDepthMaterialPart(
        name="ColorDepth physical F3",
        vertices_mm=vertices,
        faces=faces,
        extruder=3,
        source_labels=(5, 11),
        metadata={"physical_material_only": True},
    )
    return ColorDepthCellResult(
        parts=(part,),
        interfaces=(),
        source_volume_mm3=volume,
        output_volume_mm3=volume,
        cell_materials=np.asarray([3], dtype=np.int8),
        metadata={
            "renderer": "ColorDepth Lab",
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
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


def _settings(*, enabled: bool) -> AppSettings:
    return AppSettings(
        geometry=GeometrySettings(
            height_mm=6.0,
            adjust_face_count=False,
            min_component_faces=1,
        ),
        tone=ToneSettings(smoothing=False),
        palette=PaletteSettings(
            palette_state_count=24,
            physical_hex=["#111111", "#F5F5F5", "#E32636", "#7A4A32"],
        ),
        color_depth=ColorDepthSettings(
            experimental_enabled=enabled,
            outer_thickness_mm=0.15,
        ),
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
    names = ("left", "right")
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


class ColorDepthSettingsTests(unittest.TestCase):
    def test_default_is_not_opted_in_and_is_omitted(self) -> None:
        settings = AppSettings()
        self.assertFalse(settings.color_depth.experimental_enabled)
        self.assertNotIn("color_depth", settings.to_dict())

    def test_explicit_opt_in_round_trips_without_enabling_old_projects(self) -> None:
        encoded = _settings(enabled=True).to_dict()
        self.assertTrue(encoded["color_depth"]["experimental_enabled"])
        restored = AppSettings.from_dict(encoded)
        self.assertTrue(restored.color_depth.experimental_enabled)
        self.assertFalse(AppSettings.from_dict({}).color_depth.experimental_enabled)

    def test_fixed_layer_and_explicit_policy_are_enforced(self) -> None:
        with self.assertRaises(ValueError):
            ColorDepthSettings(layer_height_mm=0.08)
        with self.assertRaises(ValueError):
            ColorDepthSettings(recipe_policy="legacy-ratio")

    def test_public_project_loading_sanitizes_hidden_color_depth_opt_in(self) -> None:
        raw_settings = _settings(enabled=True).to_dict()
        for schema in (
            "obj-adjuster.project.v9",
            "obj-adjuster.project.v10",
            "obj-adjuster.project.v11",
            "obj-adjuster.project.v12-unknown",
            None,
        ):
            payload = {"settings": raw_settings}
            if schema is not None:
                payload["schema"] = schema
            with self.subTest(schema=payload.get("schema")):
                restored = _project_settings_from_mapping(payload)
                self.assertFalse(restored.color_depth.experimental_enabled)


class ColorDepthWorkflowTests(unittest.TestCase):
    def test_3mf_inspection_uses_embedded_palette_as_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = _write_import_archive(
                Path(directory) / "ordinary-part.3mf",
                _valid_import_members(),
            )
            imported = inspect_color_depth_3mf(source)

        self.assertEqual(imported.physical_slot_order, IMPORTED_PHYSICAL)
        self.assertEqual(imported.print_mix_specs, ((1, 2), (1, 3)))
        self.assertEqual(imported.palette_state_count, 6)
        self.assertEqual(
            {
                index + 4: pair
                for index, pair in enumerate(imported.print_mix_specs)
            },
            IMPORTED_STATE_PAIRS,
        )
        np.testing.assert_array_equal(
            imported.face_target_labels,
            [0, 1, 4, 5],
        )

    def test_3mf_source_destination_alias_fails_before_builder(self) -> None:
        builder_called = False

        def builder(_request):
            nonlocal builder_called
            builder_called = True
            return _one_physical_union()

        with tempfile.TemporaryDirectory() as directory:
            source = _write_import_archive(
                Path(directory) / "must-survive.3mf",
                _valid_import_members(),
            )
            original = source.read_bytes()
            with (
                patch(
                    "spectrum_mapper.color_depth_workflow.inspect_color_depth_3mf"
                ) as inspect,
                self.assertRaises(ColorDepthWorkflowError) as captured,
            ):
                export_color_depth_from_3mf(
                    source,
                    _settings(enabled=True),
                    source,
                    geometry_builder=builder,
                )

            self.assertEqual(captured.exception.code, "source_destination_same")
            inspect.assert_not_called()
            self.assertFalse(builder_called)
            self.assertEqual(source.read_bytes(), original)

    def test_3mf_opt_in_and_layer_guards_run_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "need-not-be-read.3mf"
            destination = Path(directory) / "output.3mf"
            invalid_layer = _settings(enabled=True)
            invalid_layer.color_depth.layer_height_mm = 0.08
            cases = (
                (_settings(enabled=False), "experimental_opt_in_required"),
                (invalid_layer, "fixed_layer_height_required"),
            )
            for settings, code in cases:
                with self.subTest(code=code):
                    with (
                        patch(
                            "spectrum_mapper.color_depth_workflow.inspect_color_depth_3mf"
                        ) as inspect,
                        self.assertRaises(ColorDepthWorkflowError) as captured,
                    ):
                        export_color_depth_from_3mf(
                            source,
                            settings,
                            destination,
                            geometry_builder=lambda _request: _one_physical_union(),
                        )
                    self.assertEqual(captured.exception.code, code)
                    inspect.assert_not_called()
                    self.assertFalse(destination.exists())

    def test_3mf_facade_builds_direct_source_request_from_pair_identity(self) -> None:
        palette = json.loads(_import_palette_metadata())
        # These intentionally contradictory legacy percentages remain source
        # documentation only.  Recipe identity comes solely from F-pairs.
        palette["print_mix_specs"][0]["ratio_b_percent"] = 1
        palette["print_mix_specs"][1]["ratio_b_percent"] = 99
        captured: dict[str, object] = {}

        def builder(request):
            captured["request"] = request
            return _one_physical_union()

        with tempfile.TemporaryDirectory() as directory:
            source = _write_import_archive(
                Path(directory) / "embedded-pairs.3mf",
                _valid_import_members(
                    palette=json.dumps(palette).encode("utf-8")
                ),
            )
            destination = Path(directory) / "color-depth-output.3mf"
            settings = _settings(enabled=True)
            # Deliberately differs from the archive: embedded F1--F4 own this
            # import path unless an explicit expected contract is supplied.
            self.assertNotEqual(
                tuple(settings.palette.physical_hex),
                IMPORTED_PHYSICAL,
            )
            with patch(
                "spectrum_mapper.color_depth_workflow.write_radial_3mf_atomic",
                return_value={"static_validation_ok": True},
            ) as writer:
                result = export_color_depth_from_3mf(
                    source,
                    settings,
                    destination,
                    geometry_builder=builder,
                )

            request = captured["request"]
            self.assertIsNone(request.prepared)
            self.assertIsNotNone(request.source_surface)
            self.assertEqual(request.height_mm, 10.0)
            np.testing.assert_array_equal(
                request.face_target_labels,
                [0, 1, 4, 5],
            )
            np.testing.assert_array_equal(
                request.source_surface.face_target_labels,
                request.face_target_labels,
            )
            self.assertEqual(
                request.recipe_plan.physical_hex,
                IMPORTED_PHYSICAL,
            )
            self.assertFalse(
                request.recipe_plan.metadata["legacy_mix_percentages_used"]
            )
            self.assertEqual(
                (
                    request.recipes[4].outer_physical,
                    request.recipes[4].backing_physical,
                ),
                (2, 1),
            )
            self.assertEqual(
                (
                    request.recipes[5].outer_physical,
                    request.recipes[5].backing_physical,
                ),
                (3, 1),
            )
            self.assertTrue(request.recipes[4].metadata["legacy_ratio_ignored"])
            self.assertTrue(request.recipes[5].metadata["legacy_ratio_ignored"])
            self.assertEqual(
                request.recipes[4].metadata["embedded_physical_pair"],
                [1, 2],
            )
            self.assertEqual(
                request.recipes[5].metadata["embedded_physical_pair"],
                [1, 3],
            )
            package = writer.call_args.args[1]
            self.assertEqual(package.physical_hex, IMPORTED_PHYSICAL)
            self.assertEqual(result.model_path, destination)
            self.assertEqual(result.target_labels, (0, 1, 4, 5))
            self.assertEqual(result.validation, {"static_validation_ok": True})
            self.assertTrue(result.report_path.is_file())
            self.assertTrue(result.guide_path.is_file())

    def test_3mf_builder_failure_leaves_no_destination_or_sidecars(self) -> None:
        class BuilderProbeError(RuntimeError):
            pass

        captured: dict[str, object] = {}

        def builder(request):
            captured["request"] = request
            raise BuilderProbeError("deliberate builder stop")

        with tempfile.TemporaryDirectory() as directory:
            source = _write_import_archive(
                Path(directory) / "builder-source.3mf",
                _valid_import_members(),
            )
            destination = Path(directory) / "must-not-exist.3mf"
            with (
                patch(
                    "spectrum_mapper.color_depth_workflow.write_radial_3mf_atomic"
                ) as writer,
                self.assertRaises(BuilderProbeError),
            ):
                export_color_depth_from_3mf(
                    source,
                    _settings(enabled=True),
                    destination,
                    geometry_builder=builder,
                )

            request = captured["request"]
            self.assertIsNone(request.prepared)
            self.assertIsNotNone(request.source_surface)
            writer.assert_not_called()
            self.assertFalse(destination.exists())
            self.assertFalse(
                destination.with_name(
                    destination.stem + "_color_depth_validation.json"
                ).exists()
            )
            self.assertFalse(
                destination.with_name(
                    destination.stem + "_SLICE_ONLY_guide.txt"
                ).exists()
            )

    def test_3mf_facade_real_writer_reopens_and_reports_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = _write_import_archive(
                Path(directory) / "round-trip-source.3mf",
                _valid_import_members(),
            )
            destination = Path(directory) / "round-trip-output.3mf"
            result = export_color_depth_from_3mf(
                source,
                _settings(enabled=True),
                destination,
                geometry_builder=lambda _request: _one_physical_union(),
            )

            self.assertTrue(result.model_path.is_file())
            self.assertTrue(result.validation["static_validation_ok"])
            self.assertEqual(result.validation["physical_extruders"], [3])
            report = json.loads(
                result.report_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual(report["source_kind"], "ordinary-per-part-3mf")
            self.assertEqual(
                report["source_archive"]["name"],
                source.name,
            )
            self.assertNotIn("path", report["source_archive"])
            self.assertEqual(
                report["source_palette"]["physical_slot_order"],
                list(IMPORTED_PHYSICAL),
            )
            self.assertEqual(
                report["source_palette"]["state_pairs"],
                {"4": [1, 2], "5": [1, 3]},
            )
            self.assertEqual(
                report["source_canonicalization"]["policy"],
                "xy-bbox-center-and-min-z",
            )
            self.assertEqual(
                np.asarray(
                    report["source_transform"]["composed_3mf_matrix"]
                ).shape,
                (4, 4),
            )
            with zipfile.ZipFile(result.model_path, "r") as archive:
                self.assertIsNone(archive.testzip())
                output_metadata = json.loads(
                    archive.read("Metadata/radial_shell_experimental.json")
                )
            self.assertEqual(output_metadata["renderer"], "ColorDepth Lab")
            self.assertTrue(output_metadata["slice_only"])
            self.assertFalse(output_metadata["print_allowed"])

    def test_active_part_uses_its_own_physical_palette_and_manual_subset(self) -> None:
        prepared = _two_part_cubes()
        settings = _settings(enabled=True)
        settings.part_palettes = {
            "part:left": PaletteSettings(
                palette_state_count=24,
                physical_hex=["#111111", "#F5F5F5", "#E32636", "#7A4A32"],
            ),
            "part:right": PaletteSettings(
                palette_state_count=24,
                physical_hex=["#080808", "#EEEEEE", "#CC2233", "#73452D"],
            ),
        }
        labels = np.full(12, 5, dtype=np.int16)
        manual = np.full(len(prepared.final.faces), -1, dtype=np.int8)
        manual[12:] = 5
        captured: dict[str, object] = {}

        def builder(request):
            captured["request"] = request
            return _one_physical_union()

        def apply_overrides(level, _height, _palette, _part_palettes, colors, values):
            captured["manual"] = np.asarray(values).copy()
            self.assertEqual(level.part_keys, ("part:right",))
            return colors

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "right-color-depth.3mf"
            with (
                patch(
                    "spectrum_mapper.color_depth_workflow.recolor_level_parts",
                    return_value=SimpleNamespace(palette_indices=labels),
                ),
                patch(
                    "spectrum_mapper.color_depth_workflow.apply_palette_overrides_parts",
                    side_effect=apply_overrides,
                ),
            ):
                result = export_color_depth_bundle(
                    prepared,
                    settings,
                    destination,
                    manual_overrides=manual,
                    geometry_builder=builder,
                    part_key="part:right",
                )
                report = json.loads(
                    result.report_path.read_text(encoding="utf-8-sig")
                )

        request = captured["request"]
        self.assertEqual(request.prepared.final.part_keys, ("part:right",))
        self.assertEqual(len(request.prepared.final.faces), 12)
        np.testing.assert_array_equal(captured["manual"], np.full(12, 5, dtype=np.int8))
        self.assertEqual(report["source_assembly_part_count"], 2)
        self.assertEqual(report["source_part_count"], 1)
        self.assertEqual(report["selected_part_id"], 1)
        self.assertEqual(report["selected_part_key"], "part:right")
        self.assertEqual(
            report["physical_hex"],
            ["#080808", "#EEEEEE", "#CC2233", "#73452D"],
        )

    def test_whole_multipart_keeps_shared_physical_palette_gate(self) -> None:
        prepared = _two_part_cubes()
        settings = _settings(enabled=True)
        settings.part_palettes = {
            "part:right": PaletteSettings(
                palette_state_count=24,
                physical_hex=["#080808", "#EEEEEE", "#CC2233", "#73452D"],
            )
        }
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ColorDepthWorkflowError) as captured:
                export_color_depth_bundle(
                    prepared,
                    settings,
                    Path(directory) / "whole.3mf",
                    geometry_builder=lambda _request: _one_physical_union(),
                )
        self.assertEqual(captured.exception.code, "shared_physical_filaments_required")

    def test_part_selection_is_fail_closed(self) -> None:
        prepared = _two_part_cubes()
        settings = _settings(enabled=True)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "invalid.3mf"
            for kwargs, code in (
                ({"part_key": "missing"}, "part_key_not_found"),
                ({"part_id": 9}, "part_id_out_of_range"),
                (
                    {"part_key": "part:left", "part_id": 0},
                    "part_selection_conflict",
                ),
            ):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises(ColorDepthWorkflowError) as captured:
                        export_color_depth_bundle(
                            prepared,
                            settings,
                            destination,
                            geometry_builder=lambda _request: _one_physical_union(),
                            **kwargs,
                        )
                    self.assertEqual(captured.exception.code, code)

    def test_multi_state_head_labels_use_pair_only_and_ignore_old_ratio(self) -> None:
        prepared = _uniform_cube()
        labels = np.resize(np.asarray([5, 11], dtype=np.int16), len(prepared.final.faces))
        captured = {}

        def builder(request):
            captured["request"] = request
            return _one_physical_union()

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "head-color-depth.3mf"
            with patch(
                "spectrum_mapper.color_depth_workflow.recolor_level_parts",
                return_value=SimpleNamespace(palette_indices=labels),
            ):
                result = export_color_depth_bundle(
                    prepared,
                    _settings(enabled=True),
                    destination,
                    geometry_builder=builder,
                )

            request = captured["request"]
            self.assertEqual(tuple(np.unique(request.face_target_labels)), (5, 11))
            self.assertEqual(request.recipe_plan.collapsed_target_groups, ((5, 11),))
            self.assertEqual(
                (request.recipes[5].outer_physical, request.recipes[5].backing_physical),
                (3, 1),
            )
            self.assertEqual(
                (request.recipes[11].outer_physical, request.recipes[11].backing_physical),
                (3, 1),
            )
            self.assertTrue(result.model_path.is_file())
            report = json.loads(result.report_path.read_text(encoding="utf-8-sig"))
            self.assertFalse(report["legacy_fullspectrum_ratios_used"])
            self.assertFalse(report["print_allowed"])
            self.assertFalse(report["calibrated"])
            self.assertEqual(report["collapsed_target_groups"], [[5, 11]])
            with zipfile.ZipFile(result.model_path, "r") as archive:
                metadata = json.loads(
                    archive.read("Metadata/radial_shell_experimental.json")
                )
            self.assertEqual(metadata["renderer"], "ColorDepth Lab")
            generator = metadata["generator_metadata"]
            self.assertEqual(generator["ratio_definitions"], 0)
            self.assertEqual(generator["cycle_definitions"], 0)
            self.assertEqual(generator["virtual_mix_definitions"], 0)

    def test_opt_in_is_required_before_builder_or_file_write(self) -> None:
        prepared = _uniform_cube()
        builder_called = False

        def builder(_request):
            nonlocal builder_called
            builder_called = True
            return _one_physical_union()

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "must-not-exist.3mf"
            with self.assertRaises(ColorDepthWorkflowError) as captured:
                export_color_depth_bundle(
                    prepared,
                    _settings(enabled=False),
                    destination,
                    geometry_builder=builder,
                )
            self.assertEqual(captured.exception.code, "experimental_opt_in_required")
            self.assertFalse(builder_called)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
