"""Export policy survives the public writer chain without changing high defaults."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

import final_shading_hotfix as shading
import spectrum_mapper_hotfix as portable
import surface_resolution_hotfix as surface


class _ReachedWriter(Exception):
    pass


class ExportValidationAdapterTests(unittest.TestCase):
    def test_portable_writer_forwards_only_explicit_non_high_policy(self):
        for policy in ("high", "medium", "low", "ignore"):
            with self.subTest(policy=policy):
                writer = mock.Mock(side_effect=_ReachedWriter)
                with mock.patch.object(portable, "_original_write_3mf_atomic", writer):
                    with self.assertRaises(_ReachedWriter):
                        portable._write_3mf_atomic_fixed(
                            "unused.3mf", object(), object(), 10.0,
                            portable.models.PaletteSettings(),
                            export_validation_level=policy,
                        )
                self.assertEqual(writer.call_args.kwargs, self._kwargs(policy))

    def test_portable_validator_forwards_policy_without_metadata_inference(self):
        for policy in ("high", "medium", "low", "ignore"):
            with self.subTest(policy=policy):
                validator = mock.Mock(return_value={"checked": True})
                with (
                    mock.patch.object(portable, "_original_validate_3mf", validator),
                    mock.patch.object(portable, "_inspect_portable_materials", return_value={}),
                ):
                    result = portable._validate_3mf_fixed(
                        "unused.3mf", 4, 4, [], "definitions",
                        export_validation_level=policy,
                    )
                self.assertTrue(result["checked"])
                self.assertEqual(validator.call_args.kwargs, self._kwargs(policy))

    @staticmethod
    def _kwargs(policy):
        return {} if policy == "high" else {"export_validation_level": policy}

    def test_surface_relaxed_policy_does_not_claim_inherited_strict_si(self):
        for policy in ("medium", "low", "ignore"):
            with self.subTest(policy=policy):
                writer = mock.Mock(return_value={"self_intersections_checked": False})
                with mock.patch.object(surface, "_linear_export_context") as context:
                    result = surface._make_scoped_3mf_writer(writer)(
                        "unused.3mf", object(), object(), 10.0, object(),
                        export_validation_level=policy,
                    )
                context.assert_not_called()
                self.assertEqual(writer.call_args.kwargs, self._kwargs(policy))
                self.assertNotIn("inherited_self_intersection_parts", result)

    def test_surface_high_keeps_legacy_writer_signature_in_both_branches(self):
        for inherited in (False, True):
            with self.subTest(inherited=inherited):
                context = {
                    "remaining_face_counts": {4: 1},
                    "expected_part_faces": (4,), "inherited_calls": 0,
                } if inherited else None

                def legacy(destination, prepared, colors, height, palette, part_palettes=None, print_uses_global_palette=False):
                    if context is not None:
                        self.assertIs(surface._LINEAR_EXPORT_VALIDATION_CONTEXT.get(), context)
                        context["inherited_calls"] = 1
                        context["remaining_face_counts"][4] = 0
                    return {"legacy": True}

                with mock.patch.object(surface, "_linear_export_context", return_value=context):
                    result = surface._make_scoped_3mf_writer(legacy)(
                        "unused.3mf", object(), object(), 10.0, object(),
                        export_validation_level="high",
                    )
                self.assertTrue(result["legacy"])
                self.assertEqual(result.get("inherited_self_intersection_parts", 0), int(inherited))
                self.assertIsNone(surface._LINEAR_EXPORT_VALIDATION_CONTEXT.get())

    @staticmethod
    def _final_writer(writer):
        no_op = lambda *args, **kwargs: None
        workflow = SimpleNamespace(write_3mf_atomic=writer)
        modules = {
            "spectrum_mapper.engine": SimpleNamespace(apply_palette_overrides=no_op, apply_palette_overrides_parts=no_op),
            "spectrum_mapper.workflow": workflow,
            "spectrum_mapper.mixer": SimpleNamespace(),
            "auto_shading": SimpleNamespace(),
            "smooth_paint": SimpleNamespace(),
            "smooth_paint_hotfix": SimpleNamespace(_palette_rgb=lambda *args: np.zeros((32, 3))),
        }
        with (
            mock.patch.object(shading, "_INSTALLED", False),
            mock.patch.object(shading.importlib, "import_module", side_effect=lambda name: modules[name]),
        ):
            shading.install_export_adaptive_hotfix()
        return workflow.write_3mf_atomic

    def test_final_shading_forwards_policy_through_every_writer_branch(self):
        for branch in ("flat", "chart", "fallback", "adaptive"):
            for policy in ("high", "medium", "low", "ignore"):
                with self.subTest(branch=branch, policy=policy):
                    writer = mock.Mock(return_value={})
                    wrapped = self._final_writer(writer)
                    colors = object()
                    adaptive = SimpleNamespace(merged_trees={}, auto_trees={}, validation_dict=lambda changed: {})
                    with (
                        mock.patch.object(shading, "_calibration_chart_disables_adaptive", return_value=branch == "chart"),
                        mock.patch.object(shading, "topology_fingerprint", return_value="fixture"),
                        mock.patch.object(shading, "generate_export_adaptive", side_effect=ValueError("fixture") if branch == "fallback" else None, return_value=adaptive),
                        mock.patch.object(shading, "apply_dominant_roots", return_value=(colors, 0)),
                        mock.patch.object(shading, "_sync_color_result"),
                    ):
                        wrapped(
                            "unused.3mf", SimpleNamespace(final=object()), colors, 10.0,
                            SimpleNamespace(color_mode="flat_four" if branch == "flat" else "full_spectrum"),
                            export_validation_level=policy,
                        )
                    writer.assert_called_once()
                    self.assertEqual(writer.call_args.kwargs, self._kwargs(policy))

    def test_final_shading_high_accepts_a_legacy_writer(self):
        def legacy(destination, prepared, colors, height, palette, part_palettes=None, print_uses_global_palette=False):
            return {"legacy": True}

        result = self._final_writer(legacy)(
            "unused.3mf", object(), object(), 10.0,
            SimpleNamespace(color_mode="flat_four"),
        )
        self.assertEqual(result, {"legacy": True})

    def test_fresh_entrypoint_open_mesh_exports_only_at_selected_low_or_ignore(self):
        # Install the real portable -> Surface -> FinalShading chain in a fresh
        # process, so test discovery cannot choose the adapter import order.
        script = textwrap.dedent("""
            from dataclasses import replace
            import json
            from pathlib import Path
            import tempfile
            from zipfile import ZipFile
            import numpy as np
            import TripoSpectrumMapper_fixed
            from spectrum_mapper import engine, workflow
            from spectrum_mapper.models import PaletteSettings, ToneSettings
            from test_hotfix import tiny_closed_prepared
            import final_shading_hotfix

            def open_fixture():
                prepared = tiny_closed_prepared()
                old = prepared.final
                faces = old.faces[:3].copy()
                level = replace(old, faces=faces, areas_unit=engine.triangle_areas(old.vertices_unit, faces), neighbors=None,
                                face_part_ids=np.zeros(3, dtype=np.int16), face_provenance=np.zeros(3, dtype=np.uint8))
                prepared.final = prepared.preview = level
                prepared.clean_face_count = 3
                prepared.topology = {"watertight": False, "boundary_edges": 3, "nonmanifold_edges": 0, "inconsistent_winding_edges": 0}
                prepared.assembly = {"all_parts_watertight": False, "fixture_marker": "preserve"}
                return prepared

            records = []
            with tempfile.TemporaryDirectory() as directory:
                for mode in ("flat_four", "full_spectrum"):
                    palette = PaletteSettings(color_mode=mode, palette_state_count=32)
                    for policy in ("high", "medium", "low", "ignore"):
                        prepared = open_fixture()
                        colors = engine.recolor_level(prepared.final, 10.0, ToneSettings(), palette)
                        output = Path(directory) / f"{mode}-{policy}.3mf"
                        if policy in ("high", "medium"):
                            try:
                                workflow.write_3mf_atomic(output, prepared, colors, 10.0, palette, export_validation_level=policy)
                            except engine.EngineError:
                                assert not output.exists()
                            else:
                                raise AssertionError(f"Open fixture was unexpectedly accepted: {policy}")
                            continue
                        result = workflow.write_3mf_atomic(output, prepared, colors, 10.0, palette, export_validation_level=policy)
                        assert result["geometry_validation_level"] == policy, result
                        assert result["geometry_warning_parts"] >= 1, result
                        assert result["valid_solids"] is False, result
                        assert result["part_topologies"][0]["boundary_edges"] == 3, result
                        assert result["part_topologies"][0]["self_intersecting_faces"] == -1, result
                        assert result["portable_material_faces_match"] is True
                        assert result["portable_and_orca_states_match"] is True
                        assert result["slicer_safe_project_defaults"] is True
                        with ZipFile(output) as archive:
                            assert archive.testzip() is None
                            assembly = json.loads(archive.read("Metadata/tripo_assembly.json"))
                        assert assembly["fixture_marker"] == "preserve"
                        admission = assembly["export_validation"]
                        assert admission["schema"] == "chromamatter.export-validation.v1"
                        assert admission["level"] == policy
                        assert admission["self_intersections_checked"] is False
                        assert admission["orca_preview_required"] is True
                        assert admission["not_recommended"] is (policy == "ignore")
                        inspected = final_shading_hotfix.inspect_3mf_paint(output)
                        assert inspected["invalid_paint_faces"] == 0
                        assert inspected["dominant_root_mismatches"] == 0
                        if mode == "flat_four":
                            assert result["active_palette_state_count"] == 4
                            assert result["mixed_definition_active_rows"] == 0
                        else:
                            assert result["r8_export_adaptive"]["status"] in ("generated", "preserved"), result
                        records.append([mode, policy])
            print(json.dumps(records))
        """)
        app_directory = Path(__file__).resolve().parent
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(app_directory)
        result = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=app_directory,
            env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(len(records), 4)


if __name__ == "__main__":
    unittest.main()
