from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import spectrum_mapper_hotfix as hotfix
from final_shading_hotfix import generate_export_adaptive
from spectrum_mapper import cli, engine
from spectrum_mapper.generated_surface_color import (
    attach_generated_surface_export_context,
    build_generated_surface_masks,
    optimize_generated_hidden_colors,
)
from spectrum_mapper.gui import MapperApp, _geometry_key
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import (
    AppSettings,
    GeometrySettings,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
)
from test_generated_surface_color import _fixture as generated_surface_fixture
from test_hotfix import tiny_closed_color_result, tiny_closed_prepared


def _grid_asset(subdivisions: int = 36) -> ObjAsset:
    """Create enough real triangles to exercise MeshLab decimation."""

    values = np.linspace(-1.0, 1.0, subdivisions + 1)
    vertices = np.asarray(
        [
            (x, y, 0.03 * np.sin(3.0 * x) * np.cos(2.0 * y))
            for y in values
            for x in values
        ],
        dtype=np.float64,
    )
    faces: list[tuple[int, int, int]] = []
    stride = subdivisions + 1
    for row in range(subdivisions):
        for column in range(subdivisions):
            lower_left = row * stride + column
            lower_right = lower_left + 1
            upper_left = lower_left + stride
            upper_right = upper_left + 1
            faces.extend(
                (
                    (lower_left, lower_right, upper_right),
                    (lower_left, upper_right, upper_left),
                )
            )
    face_array = np.asarray(faces, dtype=np.int32)
    span = np.maximum(np.ptp(vertices, axis=0), 1.0e-9)
    colors = np.clip((vertices - vertices.min(axis=0)) / span, 0.0, 1.0)
    return ObjAsset(
        path=Path("deferred-face-count.obj"),
        sha256="A" * 64,
        file_size=1,
        vertices=vertices,
        colors=colors,
        faces=face_array,
        original_vertex_count=len(vertices),
        original_face_count=len(face_array),
        warnings=[],
        part_names=("whole",),
        part_keys=("0:whole",),
        face_part_ids=np.zeros(len(face_array), dtype=np.int16),
        part_face_counts=(len(face_array),),
        part_vertex_counts=(len(vertices),),
        has_explicit_parts=False,
    )


def _tiny_prepared() -> PreparedGeometry:
    return tiny_closed_prepared()


class ReleaseRegressionTests(unittest.TestCase):
    def test_16_24_32_3mf_all_select_generic_pla(self) -> None:
        prepared = _tiny_prepared()
        colors = tiny_closed_color_result()
        with tempfile.TemporaryDirectory() as folder:
            for count in (16, 24, 32):
                with self.subTest(count=count):
                    palette = PaletteSettings(
                        palette_state_count=count,
                        enabled_states=[True] * count,
                    )
                    destination = Path(folder) / f"palette-{count}.3mf"
                    validation = hotfix._write_3mf_atomic_fixed(
                        destination,
                        prepared,
                        colors,
                        100.0,
                        palette,
                    )
                    with ZipFile(destination) as archive:
                        project = json.loads(
                            archive.read(
                                "Metadata/project_settings.config"
                            ).decode("utf-8")
                        )
                        model = archive.read("3D/Objects/object_1.model")
                    self.assertEqual(
                        project["filament_settings_id"], ["Generic PLA"] * 4
                    )
                    self.assertEqual(model.count(b"<base "), count)
                    self.assertEqual(
                        validation["portable_palette_state_count"], count
                    )
                    self.assertTrue(validation["generic_pla_filament_settings"])

    def test_deferred_adjustment_keeps_final_raw_but_preview_light(self) -> None:
        asset = _grid_asset()
        preserved = engine.prepare_geometry(
            asset,
            GeometrySettings(
                height_mm=100.0,
                target_faces=1_000,
                preview_faces=1_000,
                adjust_face_count=False,
                up_axis="Z",
                min_component_faces=0,
            ),
        )

        self.assertEqual(preserved.clean_face_count, len(asset.faces))
        self.assertEqual(len(preserved.final.faces), preserved.clean_face_count)
        self.assertLess(len(preserved.preview.faces), len(preserved.final.faces))
        self.assertLessEqual(len(preserved.preview.faces), 1_000)

        adjusted = engine.prepare_geometry(
            asset,
            GeometrySettings(
                height_mm=100.0,
                target_faces=1_000,
                preview_faces=1_000,
                adjust_face_count=True,
                up_axis="Z",
                min_component_faces=0,
            ),
        )
        self.assertEqual(adjusted.clean_face_count, len(asset.faces))
        self.assertLess(len(adjusted.final.faces), adjusted.clean_face_count)
        self.assertLessEqual(len(adjusted.final.faces), 1_000)

    def test_cli_forces_explicit_face_adjustment_even_if_settings_disable_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            settings_path = Path(folder) / "settings.json"
            settings = AppSettings()
            settings.geometry.adjust_face_count = False
            settings_path.write_text(
                json.dumps(settings.to_dict()), encoding="utf-8"
            )
            args = SimpleNamespace(
                height=100.0,
                faces=1_000,
                preview_faces=1_000,
                up_axis="Z",
                mirror=False,
                settings=str(settings_path),
                obj=str(Path(folder) / "input.obj"),
                output=str(Path(folder) / "output.3mf"),
                reference=None,
                no_fallback_obj=True,
            )
            fake_asset = object()
            fake_prepared = object()
            fake_export = SimpleNamespace(
                model_path=Path(args.output),
                report_path=Path(folder) / "report.json",
            )
            with (
                patch(
                    "spectrum_mapper.engine.load_vertex_color_obj",
                    return_value=fake_asset,
                ),
                patch(
                    "spectrum_mapper.engine.prepare_geometry",
                    return_value=fake_prepared,
                ) as prepare,
                patch(
                    "spectrum_mapper.workflow.export_bundle",
                    return_value=fake_export,
                ),
            ):
                self.assertEqual(cli.convert(args), 0)

        geometry = prepare.call_args.args[1]
        self.assertTrue(geometry.adjust_face_count)
        self.assertTrue(geometry.solidify_parts)

    def test_high_face_warning_acceptance_opens_manual_editor_once(self) -> None:
        app = MapperApp.__new__(MapperApp)
        settings = AppSettings()
        settings.geometry.adjust_face_count = False
        app.prepared = SimpleNamespace(final=SimpleNamespace(faces=range(500_000)))
        app.obj_path = Path("synthetic.obj")
        app.prepared_key = _geometry_key(settings.geometry)
        app._variables_to_settings = lambda **_kwargs: settings
        app._manual_high_face_warning_key = None
        app.i18n = Translator("ja")
        app.root = object()
        app.paint_editor = None
        app.reference_image = None
        app.manual_overrides = None
        app.settings = settings
        app._open_boundary_diagnostics_on_paint = False
        app._set_mix_optimization_undo_enabled = lambda _enabled: None
        app.active_part_key = None
        for name in (
            "_on_manual_orbit_direction_changed",
            "_solidify_parts_from_paint_editor",
            "_on_editor_tone_settings_changed",
            "_on_editor_palette_settings_changed",
            "_on_editor_mix_optimization_requested",
            "_on_editor_mix_optimization_undo_requested",
            "_on_editor_tone_reset_requested",
        ):
            setattr(app, name, lambda *_args, **_kwargs: None)
        fake_editor = SimpleNamespace(maximize=lambda: None)

        with (
            patch("spectrum_mapper.gui.messagebox.askyesno", return_value=True) as confirm,
            patch(
                "spectrum_mapper.gui.PaintEditorWindow",
                return_value=fake_editor,
            ) as constructor,
        ):
            MapperApp._open_paint_editor(app)

        confirm.assert_called_once()
        constructor.assert_called_once()
        self.assertIs(app.paint_editor, fake_editor)
        self.assertEqual(
            app._manual_high_face_warning_key,
            (id(app.prepared), app.prepared_key),
        )

    def test_hidden_generated_faces_have_no_final_adaptive_roots_and_json_is_safe(self) -> None:
        prepared, colors = generated_surface_fixture()
        masks = build_generated_surface_masks(prepared, 10.0)
        optimized = optimize_generated_hidden_colors(prepared, colors, 10.0)
        attach_generated_surface_export_context(prepared, optimized)
        collapsed = np.flatnonzero(optimized.collapsed_mask)
        self.assertGreater(len(collapsed), 0)

        # The release metadata is written with json.dumps during 3MF export.
        # Keep this explicit because numpy scalars/arrays can otherwise leak
        # into assembly diagnostics without being caught by unit-level masks.
        json.dumps(prepared.assembly)

        palette_rgb = np.linspace(0.0, 1.0, 32 * 3).reshape((32, 3))
        states = np.asarray(optimized.colors.palette_indices, dtype=np.int64)
        optimized.colors.target_face_rgb = palette_rgb[states]

        class FakeOptions:
            def __init__(self, **values):
                self.__dict__.update(values)

        class FakeAutoShading:
            AutoShadingOptions = FakeOptions

            @staticmethod
            def generate_auto_shading(
                _faces,
                _vertices,
                _tone_rgb,
                _states,
                _palette_rgb,
                *,
                options,
                face_mask,
            ):
                del options
                selected = np.flatnonzero(face_mask)
                return SimpleNamespace(
                    trees={int(face): f"tree-{int(face)}" for face in selected},
                    candidate_faces=len(selected),
                    selected_faces=len(selected),
                    adaptive_faces=len(selected),
                    total_leaves=len(selected) * 4,
                    budget_limited=False,
                )

        fake_smooth = SimpleNamespace(encode_paint_color=lambda node: str(node))
        result = generate_export_adaptive(
            prepared,
            optimized.colors,
            10.0,
            PaletteSettings(
                palette_state_count=32,
                enabled_states=[True] * 32,
            ),
            palette_rgb=palette_rgb,
            auto_shading_module=FakeAutoShading,
            smooth_paint_module=fake_smooth,
        )
        hidden_adaptive_roots = set(int(value) for value in collapsed) & set(
            result.merged_trees
        )
        self.assertEqual(hidden_adaptive_roots, set())
        self.assertTrue(np.all(~masks.guard[collapsed]))

    def test_public_runtime_version_is_0_9(self) -> None:
        import spectrum_mapper
        from spectrum_mapper import gui

        self.assertEqual(spectrum_mapper.__version__, "0.9")
        self.assertEqual(hotfix.HOTFIX_VERSION, "0.9")
        self.assertEqual(spectrum_mapper.APP_NAME, "ChromaMatter")
        self.assertEqual(
            spectrum_mapper.APP_DISPLAY_NAME,
            "ChromaMatter — AI Model Print Studio",
        )
        self.assertEqual(spectrum_mapper.EDITION_LABEL, "AI Model Print Studio r33")
        self.assertEqual(
            gui.APP_TITLE,
            "ChromaMatter — AI Model Print Studio 0.9 (r33)",
        )


if __name__ == "__main__":
    unittest.main()
