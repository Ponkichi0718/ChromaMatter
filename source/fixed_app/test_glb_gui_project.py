from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

import numpy as np

from spectrum_mapper.cli import _glb_import_smoke, build_parser, convert
from spectrum_mapper.engine import write_3mf_atomic
from spectrum_mapper.gui import MapperApp, _geometry_key
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import (
    AppSettings,
    ColorResult,
    GeometrySettings,
    PaletteSettings,
)
from spectrum_mapper.project_bundle import save_project_bundle_in_parent

from test_new_obj_defaults import bare_app, model_settings
from test_project_bundle import prepared_geometry
from test_project_bundle_gui import bare_load_app


class GlbGuiWorkflowTests(unittest.TestCase):
    def test_open_dialog_accepts_glb_and_keeps_obj_path_alias(self) -> None:
        app = bare_app(model_settings(state_count=24))
        app.i18n = Translator("ja")

        with patch(
            "spectrum_mapper.gui.filedialog.askopenfilename",
            return_value="C:/models/Hi3D robot.glb",
        ) as picker:
            MapperApp._choose_obj(app)

        self.assertEqual(app.source_path, Path("C:/models/Hi3D robot.glb"))
        self.assertEqual(app.obj_path, app.source_path)
        self.assertEqual(app.obj_name_var.get(), "モデル: Hi3D robot.glb")
        filetypes = picker.call_args.kwargs["filetypes"]
        self.assertIn("*.obj *.glb", tuple(pattern for _, pattern in filetypes))
        app._process_geometry.assert_called_once_with(reuse_asset=False)

    def test_open_dialog_rejects_unknown_suffix_before_resetting_model(self) -> None:
        app = bare_app(model_settings())
        app.i18n = Translator("en")
        old_settings = app.settings

        with (
            patch(
                "spectrum_mapper.gui.filedialog.askopenfilename",
                return_value="C:/models/not-a-model.fbx",
            ),
            patch("spectrum_mapper.gui.messagebox.showerror") as showerror,
        ):
            MapperApp._choose_obj(app)

        self.assertIs(app.settings, old_settings)
        self.assertIsNone(app.source_path)
        app._process_geometry.assert_not_called()
        showerror.assert_called_once()
        self.assertEqual(showerror.call_args.args[0], "Unsupported Model Format")

    def test_geometry_worker_dispatches_glb_through_generic_core_loader(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app.paint_editor = None
        app.source_path = Path("C:/models/robot.glb")
        app.asset = None
        app.prepared = None
        app.prepared_key = None
        app.manual_part_partition = None
        app.pending_manual_part_partition = None
        app.manual_joint_record = None
        app.pending_manual_joint_record = None
        app.manual_overrides = None
        app.settings = AppSettings()
        app._variables_to_settings = Mock(return_value=app.settings)
        captured: dict[str, object] = {}

        def capture_submit(label, work, done, *, on_error=None):
            captured.update(label=label, work=work, done=done, on_error=on_error)
            return True

        app._submit_main = capture_submit
        loaded_asset = object()
        prepared = object()
        with (
            patch(
                "spectrum_mapper.gui.load_vertex_color_model",
                return_value=loaded_asset,
            ) as loader,
            patch(
                "spectrum_mapper.gui.prepare_geometry",
                return_value=prepared,
            ) as prepare,
        ):
            self.assertTrue(MapperApp._process_geometry(app, reuse_asset=False))
            result = captured["work"]()

        loader.assert_called_once_with(app.source_path, app._thread_progress)
        prepare.assert_called_once_with(
            loaded_asset,
            app.settings.geometry,
            app._thread_progress,
        )
        self.assertIs(result[0], loaded_asset)
        self.assertIs(result[1], prepared)

    def test_exact_glb_project_restore_keeps_source_and_part_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "robot.glb"
            source.write_bytes(b"glTF" + (2).to_bytes(4, "little") + b"opaque")
            prepared = prepared_geometry(source)
            settings = AppSettings(
                geometry=GeometrySettings(
                    target_faces=450_000,
                    preview_faces=80_000,
                    adjust_face_count=False,
                    up_axis="Y",
                    min_component_faces=25,
                    preserve_parts=True,
                )
            )
            bundle = save_project_bundle_in_parent(
                root,
                source,
                {
                    "schema": "obj-adjuster.project.v12",
                    "settings": settings.to_dict(),
                    "parts": [
                        {
                            "key": "part:body",
                            "name": "body",
                            "uses_individual_palette": False,
                        }
                    ],
                },
                project_folder_name="glb_exact_project",
                prepared_geometry=prepared,
                prepared_geometry_key=_geometry_key(settings.geometry),
            )
            app = bare_load_app()
            with (
                patch("spectrum_mapper.gui.messagebox.showerror") as showerror,
                patch("spectrum_mapper.gui.messagebox.showwarning"),
            ):
                app._load_project_path(bundle.folder)

            showerror.assert_not_called()
            self.assertEqual(app.source_path, bundle.folder / "source.glb")
            self.assertEqual(app.obj_path, app.source_path)
            self.assertEqual(app.prepared.final.part_names, ("body",))
            self.assertEqual(app.prepared.final.part_keys, ("part:body",))
            app._process_geometry.assert_not_called()

    def test_model_messages_are_localized_and_explicit(self) -> None:
        ja = Translator("ja")
        en = Translator("en")
        self.assertEqual(ja.text("toolbar.open_obj"), "OBJ / GLBを開く")
        self.assertIn("OBJまたはGLB", ja.text("dialog.obj_required.process"))
        self.assertEqual(en.text("toolbar.open_obj"), "Open OBJ / GLB")
        format_message = en.text("dialog.source_format.message")
        self.assertIn("OBJ", format_message)
        self.assertIn("GLB", format_message)


class GlbCliDispatchTests(unittest.TestCase):
    def test_packaged_self_test_glb_fixture_bakes_embedded_png(self) -> None:
        ok, status = _glb_import_smoke()
        self.assertTrue(ok, status)

    def test_parser_keeps_convert_switch_and_accepts_model_path(self) -> None:
        args = build_parser().parse_args(
            ["--convert", "robot.glb", "--output", "robot.3mf"]
        )
        self.assertEqual(args.obj, "robot.glb")
        self.assertEqual(args.output, "robot.3mf")

    def test_convert_dispatches_glb_and_keeps_output_stem(self) -> None:
        args = build_parser().parse_args(
            ["--convert", "robot.glb", "--output", "robot.3mf"]
        )
        asset = object()
        prepared = object()
        result = SimpleNamespace(
            model_path=Path("robot.3mf"),
            report_path=Path("robot_report.json"),
        )
        with (
            patch(
                "spectrum_mapper.engine.load_vertex_color_model",
                return_value=asset,
            ) as loader,
            patch(
                "spectrum_mapper.engine.prepare_geometry",
                return_value=prepared,
            ),
            patch(
                "spectrum_mapper.workflow.export_bundle",
                return_value=result,
            ) as export,
        ):
            self.assertEqual(convert(args), 0)

        loader.assert_called_once_with(Path("robot.glb"), ANY)
        self.assertEqual(export.call_args.args[2], Path("robot.3mf"))

    def test_convert_rejects_unsupported_suffix_clearly(self) -> None:
        args = build_parser().parse_args(
            ["--convert", "robot.fbx", "--output", "robot.3mf"]
        )
        with self.assertRaisesRegex(SystemExit, "OBJ.*GLB"):
            convert(args)

    def test_3mf_model_settings_records_glb_basename_not_host_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private_source = root / "private folder" / "Hi3D robot.glb"
            private_source.parent.mkdir()
            private_source.write_bytes(b"opaque source identity")
            prepared = prepared_geometry(private_source)
            # This test verifies source-name privacy, not permissive open-mesh
            # output.  Use a valid outward-wound tetrahedron now that every
            # printable type=model object is topology-validated regardless of
            # its assembly flags.
            vertices = np.asarray(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            )
            faces = np.asarray(
                [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
                dtype=np.int32,
            )
            vertex_colors = np.asarray(
                [
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                    [1.0, 1.0, 1.0],
                ],
                dtype=np.float64,
            )
            areas = np.full(4, np.sqrt(3.0) / 2.0, dtype=np.float64)
            prepared.final.vertices_unit = vertices
            prepared.final.faces = faces
            prepared.final.vertex_colors = vertex_colors
            prepared.final.areas_unit = areas
            prepared.final.neighbors = None
            prepared.final.face_part_ids = np.zeros(4, dtype=np.int16)
            prepared.final.face_provenance = np.zeros(4, dtype=np.uint8)
            prepared.preview = prepared.final
            prepared.topology = {
                "watertight": True,
                "boundary_edges": 0,
                "nonmanifold_edges": 0,
                "inconsistent_winding_edges": 0,
            }
            prepared.assembly = {"all_parts_watertight": True}
            colors = ColorResult(
                tone_vertex_rgb=vertex_colors.copy(),
                source_face_rgb=np.tile(
                    np.asarray([[1.0, 0.0, 0.0]]), (4, 1)
                ),
                palette_indices=np.zeros(4, dtype=np.int16),
                target_face_rgb=np.tile(
                    np.asarray([[1.0, 0.0, 0.0]]), (4, 1)
                ),
                delta_e=np.zeros(4),
                smoothed_faces=0,
                palette_face_counts=np.asarray(
                    [4] + [0] * 15,
                    dtype=np.int64,
                ),
                palette_area_fractions=np.asarray(
                    [1.0] + [0.0] * 15,
                    dtype=np.float64,
                ),
                pink_area_fraction=0.0,
            )
            destination = root / "output.3mf"
            write_3mf_atomic(
                destination,
                prepared,
                colors,
                20.0,
                PaletteSettings(),
            )
            with zipfile.ZipFile(destination, "r") as archive:
                model_settings = archive.read(
                    "Metadata/model_settings.config"
                ).decode("utf-8")

        self.assertIn('key="source_file" value="Hi3D robot.glb"', model_settings)
        self.assertNotIn(str(private_source.parent), model_settings)
        self.assertNotIn("output.obj", model_settings)


if __name__ == "__main__":
    unittest.main()
