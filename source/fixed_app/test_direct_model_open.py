from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import cli
from spectrum_mapper.gltf_import import GltfImportPlan
from spectrum_mapper.gui import MapperApp, launch_app
from spectrum_mapper.models import AppSettings


class Variable:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


def direct_open_app() -> MapperApp:
    app = MapperApp.__new__(MapperApp)
    app.paint_editor = None
    app.busy = False
    app.root = object()
    app.i18n = SimpleNamespace(
        text=lambda key, **_kwargs: key,
        dialog_detail_text=str,
    )
    app.settings = AppSettings()
    app.active_part_key = None
    app._auto_recommend_after_geometry = False
    app._project_obj_recovery_pending = False
    app._cancel_eyedropper = Mock()
    app._note_mix_input_change = Mock()
    app._sync_tone_variables = Mock()
    app._load_palette_variables = Mock()
    app._refresh_palette_widgets = Mock()
    app._clear_all_physical_palette_pending = Mock()
    app._clear_automatic_palette_provenance = Mock()
    app._clear_mix_optimization_undo = Mock()
    app._update_face_count_status = Mock()
    app._process_geometry = Mock(return_value=True)
    app.manual_overrides = np.asarray([3], dtype=np.int8)
    app.manual_fingerprint = "old"
    app.pending_manual_payload = {"paint": "pending"}
    app.manual_part_partition = {"parts": "old"}
    app.pending_manual_part_partition = {"parts": "pending"}
    app.manual_joint_record = {"joint": "old"}
    app.pending_manual_joint_record = {"joint": "pending"}
    app.part_recommendations = {"old-part": object()}
    app.part_target_var = Variable("old-part")
    app.part_name_var = Variable("Old model")
    app.main_active_part_var = Variable("old-part")
    app.recommendation_var = Variable("old recommendation")
    app.solidify_parts_var = Variable(True)
    app.repair_unmatched_boundaries_var = Variable(True)
    app.auto_joints_var = Variable(True)
    app.adjust_face_count_var = Variable(False)
    app.target_faces_var = Variable(450_000)
    app._open_boundary_diagnostics_on_paint = True
    app._manual_high_face_warning_key = ("old",)
    app.obj_path = None
    app.obj_name_var = Variable("OBJ: old.obj")
    return app


def large_plan(*, supported: bool = True) -> GltfImportPlan:
    return GltfImportPlan(
        vertex_count_upper_bound=2_500_000,
        triangle_count=5_100_000 if supported else 5_300_000,
        mesh_node_count=3,
        primitive_instance_count=3,
        primitive_modes=(4, 4, 4),
    )


class DirectModelOpenTests(unittest.TestCase):
    def test_launch_app_forwards_direct_model_contract_to_mapper(self) -> None:
        root = Mock()
        with (
            patch("spectrum_mapper.gui.tk.Tk", return_value=root),
            patch("spectrum_mapper.gui.MapperApp") as mapper,
        ):
            result = launch_app(
                initial_model=Path("synthetic.glb"),
                confirm_large_model=True,
            )

        self.assertEqual(result, 0)
        mapper.assert_called_once_with(
            root,
            smoke_test=False,
            initial_project=None,
            initial_model=Path("synthetic.glb"),
            confirm_large_model=True,
        )
        root.mainloop.assert_called_once_with()

    def test_cli_dispatches_model_and_explicit_large_confirmation(self) -> None:
        with patch("spectrum_mapper.gui.launch_app", return_value=0) as launch:
            result = cli.main(
                [
                    "--model",
                    "synthetic.glb",
                    "--confirm-large-model",
                ]
            )

        self.assertEqual(result, 0)
        launch.assert_called_once_with(
            smoke_test=False,
            initial_project=None,
            initial_model=Path("synthetic.glb"),
            confirm_large_model=True,
        )

    def test_confirmation_flag_requires_direct_model(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            cli.main(["--confirm-large-model"])
        self.assertEqual(raised.exception.code, 2)

    def test_self_test_and_direct_model_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            cli.main(["--self-test", "--model", "model.glb"])
        self.assertEqual(raised.exception.code, 2)

    def test_project_and_direct_model_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            cli.main(["--project", "project.json", "--model", "model.glb"])
        self.assertEqual(raised.exception.code, 2)

    def test_direct_large_glb_without_flag_keeps_confirmation_dialog(self) -> None:
        app = direct_open_app()
        with (
            patch("spectrum_mapper.gui.inspect_gltf_asset", return_value=large_plan()),
            patch("spectrum_mapper.gui.messagebox.askyesno", return_value=False) as confirm,
        ):
            MapperApp._choose_obj(app, Path("large.glb"))

        confirm.assert_called_once()
        app._process_geometry.assert_not_called()
        self.assertIsNone(app.obj_path)

    def test_explicit_flag_admits_only_supported_reduced_route(self) -> None:
        app = direct_open_app()
        plan = large_plan()
        with (
            patch("spectrum_mapper.gui.inspect_gltf_asset", return_value=plan),
            patch("spectrum_mapper.gui.messagebox.askyesno") as confirm,
            patch("spectrum_mapper.gui.filedialog.askopenfilename") as picker,
        ):
            MapperApp._choose_obj(
                app,
                Path("large.glb"),
                confirm_large_model=True,
            )

        confirm.assert_not_called()
        picker.assert_not_called()
        self.assertEqual(app.obj_path, Path("large.glb"))
        self.assertIs(app._large_glb_import_plan, plan)
        self.assertEqual(app._large_glb_import_path, Path("large.glb"))
        self.assertTrue(app.adjust_face_count_var.get())
        self.assertEqual(app.target_faces_var.get(), 450_000)
        self.assertFalse(app.solidify_parts_var.get())
        self.assertFalse(app.repair_unmatched_boundaries_var.get())
        self.assertFalse(app.auto_joints_var.get())
        app._process_geometry.assert_called_once_with(reuse_asset=False)

    def test_explicit_flag_never_bypasses_unsupported_plan(self) -> None:
        app = direct_open_app()
        with (
            patch(
                "spectrum_mapper.gui.inspect_gltf_asset",
                return_value=large_plan(supported=False),
            ),
            patch("spectrum_mapper.gui.messagebox.showerror") as error,
            patch("spectrum_mapper.gui.messagebox.askyesno") as confirm,
        ):
            MapperApp._choose_obj(
                app,
                Path("unsupported.glb"),
                confirm_large_model=True,
            )

        error.assert_called_once()
        confirm.assert_not_called()
        app._process_geometry.assert_not_called()
        self.assertIsNone(app.obj_path)


if __name__ == "__main__":
    unittest.main()
