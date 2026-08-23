from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from spectrum_mapper.gui import MapperApp
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import AppSettings


def _app(
    *,
    language: str = "ja",
    source: str = "model.glb",
    boundary_edges: int = 12,
    unmatched: int = 0,
    diagnostics: bool = True,
) -> MapperApp:
    app = MapperApp.__new__(MapperApp)
    app.root = object()
    app.i18n = Translator(language)
    app.source_path = Path(source)
    app.prepared = SimpleNamespace(
        topology={"watertight": False, "boundary_edges": boundary_edges},
        source=SimpleNamespace(
            has_explicit_parts=False,
            part_names=("model",),
            faces=(0,),
            face_part_ids=(0,),
        ),
        assembly={
            "solidify_parts": False,
            "unmatched_boundary_loop_count": unmatched,
            "boundary_diagnostics": ([{"matched": False}] if diagnostics else []),
        },
    )
    app.solidify_parts_var = Mock()
    app.solidify_parts_var.get.return_value = False
    app.repair_unmatched_boundaries_var = Mock()
    app.repair_unmatched_boundaries_var.get.return_value = False
    app.status_var = Mock()
    app._process_geometry = Mock(return_value=True)
    app._show_boundary_diagnostics = Mock()
    return app


class ExportAutoSolidificationTests(unittest.TestCase):
    def test_japanese_confirmation_starts_safe_reprocess_and_resumes_export(self) -> None:
        app = _app(language="ja")
        settings = AppSettings()

        with patch(
            "spectrum_mapper.gui.messagebox.askyesno", return_value=True
        ) as confirm:
            started = app._start_export_auto_solidification(settings)

        self.assertTrue(started)
        title, message = confirm.call_args.args[:2]
        self.assertIn("自動閉立体化", title)
        self.assertIn("実際の穴", message)
        app.solidify_parts_var.set.assert_called_once_with(True)
        app.repair_unmatched_boundaries_var.set.assert_called_once_with(False)
        app._process_geometry.assert_called_once()
        call = app._process_geometry.call_args
        self.assertTrue(call.kwargs["reuse_asset"])
        resume = call.kwargs["after_done"]
        self.assertIs(resume.__self__, app)
        self.assertIs(resume.__func__, MapperApp._export)

    def test_english_confirmation_declares_success_gated_export(self) -> None:
        app = _app(language="en")
        settings = AppSettings()

        with patch(
            "spectrum_mapper.gui.messagebox.askyesno", return_value=False
        ) as confirm:
            started = app._start_export_auto_solidification(settings)

        self.assertFalse(started)
        title, message = confirm.call_args.args[:2]
        self.assertIn("Automatically Solidify", title)
        self.assertIn("resume 3MF export after it succeeds", message)
        self.assertIn("will not automatically cap", message)
        app._process_geometry.assert_not_called()
        app.solidify_parts_var.set.assert_not_called()
        app.repair_unmatched_boundaries_var.set.assert_not_called()

    def test_unmatched_real_holes_are_not_capped_automatically(self) -> None:
        app = _app(unmatched=2, boundary_edges=18)
        settings = AppSettings()

        with patch(
            "spectrum_mapper.gui.messagebox.askyesno", return_value=False
        ) as recovery:
            started = app._start_export_auto_solidification(settings)

        self.assertFalse(started)
        self.assertIn("実際の開口", recovery.call_args.args[0])
        self.assertIn("自動閉立体化では塞ぎません", recovery.call_args.args[1])
        app._process_geometry.assert_not_called()
        app.solidify_parts_var.set.assert_not_called()
        app.repair_unmatched_boundaries_var.set.assert_not_called()

    def test_failed_to_start_restores_existing_geometry_flags(self) -> None:
        app = _app()
        app.solidify_parts_var.get.return_value = False
        app.repair_unmatched_boundaries_var.get.return_value = True
        app._process_geometry.return_value = False
        settings = AppSettings()

        with patch(
            "spectrum_mapper.gui.messagebox.askyesno", return_value=True
        ):
            started = app._start_export_auto_solidification(settings)

        self.assertFalse(started)
        self.assertEqual(
            app.solidify_parts_var.set.call_args_list[-1].args,
            (False,),
        )
        self.assertEqual(
            app.repair_unmatched_boundaries_var.set.call_args_list[-1].args,
            (True,),
        )

    def test_worker_failure_restores_existing_geometry_flags(self) -> None:
        app = _app()
        app.solidify_parts_var.get.return_value = False
        app.repair_unmatched_boundaries_var.get.return_value = True
        settings = AppSettings()

        with patch(
            "spectrum_mapper.gui.messagebox.askyesno", return_value=True
        ):
            started = app._start_export_auto_solidification(settings)

        self.assertTrue(started)
        restore = app._process_geometry.call_args.kwargs["after_failed"]
        restore()
        self.assertEqual(
            app.solidify_parts_var.set.call_args_list[-1].args,
            (False,),
        )
        self.assertEqual(
            app.repair_unmatched_boundaries_var.set.call_args_list[-1].args,
            (True,),
        )

    def test_single_part_obj_is_not_guessed_or_reprocessed(self) -> None:
        app = _app(source="model.obj", diagnostics=False)
        settings = AppSettings()

        with patch(
            "spectrum_mapper.gui.messagebox.showerror"
        ) as stopped:
            started = app._start_export_auto_solidification(settings)

        self.assertFalse(started)
        self.assertIn("自動閉立体化できません", stopped.call_args.args[0])
        self.assertIn("推測で穴を塞ぎません", stopped.call_args.args[1])
        app._process_geometry.assert_not_called()
        app.repair_unmatched_boundaries_var.set.assert_not_called()

    def test_already_attempted_open_mesh_fails_closed_without_retry(self) -> None:
        app = _app(language="en")
        settings = AppSettings()
        settings.geometry.solidify_parts = True

        with patch(
            "spectrum_mapper.gui.messagebox.askyesno", return_value=False
        ) as recovery:
            started = app._start_export_auto_solidification(settings)

        self.assertFalse(started)
        self.assertIn("Solidification Incomplete", recovery.call_args.args[0])
        app._process_geometry.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
