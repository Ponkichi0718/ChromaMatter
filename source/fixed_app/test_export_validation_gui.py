from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from spectrum_mapper.gui import (
    MapperApp,
    _fresh_settings_for_new_obj,
    _geometry_key,
    _persistent_preferences_from_mapping,
    _persistent_preferences_payload,
    _project_settings_from_mapping,
)
from spectrum_mapper.i18n import CATALOG, Translator
from spectrum_mapper.models import (
    AppSettings, EXPORT_VALIDATION_LEVELS, normalize_export_validation_level,
)


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def export_app(level="high", *, language="en", watertight=False):
    app = MapperApp.__new__(MapperApp)
    app.root = object()
    app.i18n = Translator(language)
    app.settings = AppSettings(export_validation_level=level)
    app.source_path = Path("model.glb")
    app.paint_editor = None
    app.prepared = SimpleNamespace(
        topology={"watertight": watertight}, final=object(),
        assembly={"single_mesh_generic": True, "solidify_parts": True},
    )
    app.prepared_key = _geometry_key(app.settings.geometry)
    app.status_var = FakeVar("")
    app.include_obj_var = FakeVar(False)
    app.reference_path = None
    app._block_export_for_pending_physical_palettes = Mock(return_value=False)
    app._variables_to_settings = Mock(return_value=app.settings)
    app._start_export_auto_solidification = Mock()
    app._validated_manual_overrides = Mock(return_value=(True, None))
    app._confirm_black_free_manual_overrides = Mock(return_value=True)
    app._submit_main = Mock()
    app._thread_progress = Mock()
    return app


class ExportValidationSettingsTests(unittest.TestCase):
    def test_defaults_and_malformed_data_fail_safe(self):
        self.assertEqual(AppSettings().export_validation_level, "high")
        self.assertNotIn("export_validation_level", AppSettings().to_dict())
        for invalid in (None, True, False, 0, 1, [], {}, "", "LOW", " low ", "none"):
            with self.subTest(invalid=invalid):
                self.assertEqual(normalize_export_validation_level(invalid), "high")
                self.assertEqual(AppSettings(export_validation_level=invalid).export_validation_level, "high")
                self.assertEqual(AppSettings.from_dict({"export_validation_level": invalid}).export_validation_level, "high")
                settings = AppSettings()
                settings.export_validation_level = invalid
                self.assertNotIn("export_validation_level", settings.to_dict())

    def test_project_preferences_and_new_model_retain_level_without_geometry_change(self):
        baseline = _geometry_key(AppSettings().geometry)
        for level in EXPORT_VALIDATION_LEVELS:
            with self.subTest(level=level):
                settings = AppSettings(export_validation_level=level)
                document = json.loads(json.dumps({
                    "schema": "obj-adjuster.project.v13", "settings": settings.to_dict(),
                }))
                restored = _project_settings_from_mapping(document)
                preferences = _persistent_preferences_payload(settings)
                self.assertEqual(preferences["export_validation_level"], level)
                for candidate in (
                    restored, _persistent_preferences_from_mapping(preferences),
                    _fresh_settings_for_new_obj(settings),
                ):
                    self.assertEqual(candidate.export_validation_level, level)
                    self.assertEqual(_geometry_key(candidate.geometry), baseline)

    def test_loaded_policy_is_not_export_consent(self):
        for level in ("medium", "low", "ignore"):
            app = export_app(level)
            with patch("spectrum_mapper.gui.messagebox.askyesno", return_value=True) as confirm:
                self.assertTrue(app._confirm_export_validation_level(app.settings))
                self.assertTrue(app._confirm_export_validation_level(app.settings))
            self.assertEqual(confirm.call_count, 2)
            self.assertEqual(confirm.call_args.kwargs["default"], "no")
            self.assertEqual(confirm.call_args.kwargs["icon"], "warning")

    def test_high_needs_no_relaxed_policy_confirmation(self):
        app = export_app("high")
        with patch("spectrum_mapper.gui.messagebox.askyesno") as confirm:
            self.assertTrue(app._confirm_export_validation_level(app.settings))
        confirm.assert_not_called()

    def test_selector_preserves_id_when_language_changes(self):
        app = export_app("ignore", language="ja")
        app.export_validation_level_var = FakeVar("")
        app.export_validation_label = Mock()
        app.export_validation_combo = Mock()
        app._save_persistent_settings = Mock()
        app._refresh_export_validation_widgets()
        self.assertEqual(app.export_validation_level_var.get(), "形状の不具合を無視（非推奨）")
        self.assertEqual(app._selected_export_validation_level(), "ignore")
        app.i18n = Translator("en")
        app._refresh_export_validation_widgets()
        self.assertEqual(app.export_validation_level_var.get(), "Ignore defects (not recommended)")
        self.assertEqual(app._selected_export_validation_level(), "ignore")
        app.export_validation_level_var.set("Low")
        app._on_export_validation_changed()
        self.assertEqual(app.settings.export_validation_level, "low")
        app._save_persistent_settings.assert_called_once_with()
        app.export_validation_level_var.set("damaged")
        self.assertEqual(app._selected_export_validation_level(), "high")

    def test_new_catalog_copy_is_bilingual_and_short_without_help_paragraphs(self):
        keys = [key for key in CATALOG if key.startswith("export.validation.")]
        self.assertTrue(keys)
        self.assertFalse(any("help" in key for key in keys))
        for key in keys:
            for language in ("en", "ja"):
                self.assertTrue(CATALOG[key][language])
            self.assertFalse(any("\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff" for char in CATALOG[key]["en"]))
        for language in ("en", "ja"):
            app = export_app("ignore", language=language)
            with patch("spectrum_mapper.gui.messagebox.askyesno", return_value=False) as confirm:
                self.assertFalse(app._confirm_export_validation_level(app.settings))
            body = confirm.call_args.args[1]
            self.assertLess(len(body), 260)
            self.assertIn("Orca", body)
            self.assertIn("非推奨" if language == "ja" else "not recommended", body)


class ExportValidationFlowTests(unittest.TestCase):
    def invoke_export(self, app, *, confirmation=True, destination="result.3mf"):
        with (
            patch("spectrum_mapper.gui.plan_palette_groups", return_value=SimpleNamespace(requires_separate_jobs=False)),
            patch("spectrum_mapper.gui.filedialog.asksaveasfilename", return_value=destination) as save,
            patch("spectrum_mapper.gui.messagebox.askyesno", return_value=confirmation) as confirm,
        ):
            app._export()
        return save, confirm

    def test_high_and_medium_still_require_solidify_before_destination(self):
        for level in ("high", "medium"):
            with self.subTest(level=level):
                app = export_app(level)
                save, confirm = self.invoke_export(app)
                app._start_export_auto_solidification.assert_called_once_with(app.settings)
                app._submit_main.assert_not_called()
                save.assert_not_called()
                confirm.assert_not_called()

    def test_low_and_ignore_reach_export_without_auto_solidify(self):
        for level in ("low", "ignore"):
            with self.subTest(level=level):
                app = export_app(level)
                save, confirm = self.invoke_export(app)
                app._start_export_auto_solidification.assert_not_called()
                save.assert_called_once()
                confirm.assert_called_once()
                app._submit_main.assert_called_once()
                work = app._submit_main.call_args.args[1]
                with patch("spectrum_mapper.gui.export_bundle") as export:
                    work()
                self.assertEqual(export.call_args.args[1].export_validation_level, level)

    def test_non_high_refusal_or_destination_cancel_produces_no_worker(self):
        for level in ("medium", "low", "ignore"):
            app = export_app(level, watertight=True)
            self.invoke_export(app, confirmation=False)
            app._submit_main.assert_not_called()
            self.assertIn("cancel", app.status_var.get().lower())
            app = export_app(level, watertight=True)
            _save, confirm = self.invoke_export(app, destination="")
            confirm.assert_not_called()
            app._submit_main.assert_not_called()

    def test_palette_pending_guard_precedes_every_level(self):
        for level in EXPORT_VALIDATION_LEVELS:
            app = export_app(level)
            app._block_export_for_pending_physical_palettes.return_value = True
            save, confirm = self.invoke_export(app)
            save.assert_not_called()
            confirm.assert_not_called()
            app._variables_to_settings.assert_not_called()
            app._submit_main.assert_not_called()

    def test_relaxed_completion_and_individual_completion_never_claim_closed(self):
        for language in ("en", "ja"):
            for individual_only in (False, True):
                for level in ("medium", "low", "ignore"):
                    with self.subTest(language=language, individual=individual_only, level=level):
                        app = export_app(level, language=language, watertight=True)
                        self.invoke_export(app)
                        done = app._submit_main.call_args.args[2]
                        result = SimpleNamespace(
                            part_model_paths=[Path("parts/head.3mf")],
                            individual_only=individual_only, model_path=Path("result.3mf"),
                            validation={
                                "geometry_validation_level": level,
                                "geometry_warnings": ["boundary_edges"],
                                "geometry_warning_parts": 1,
                                "geometry_issues_ignored": True,
                                "valid_solids": False,
                                "self_intersection_warning_parts": 1,
                            },
                        )
                        with patch("spectrum_mapper.gui.messagebox.askyesno", return_value=False) as dialog:
                            done(result)
                        title, body = dialog.call_args.args[:2]
                        self.assertIn("Orca", body)
                        self.assertIn("要確認" if language == "ja" else "Review Required", title)
                        self.assertNotIn("閉立体", body)
                        self.assertNotIn("closed", body.lower())
                        self.assertNotIn("all mandatory", body.lower())
                        self.assertNotIn("boundary_edges", body)
                        self.assertIn("Orca", app.status_var.get())

    def test_strict_completion_keeps_existing_bounded_warning(self):
        app = export_app("high", watertight=True)
        self.invoke_export(app)
        done = app._submit_main.call_args.args[2]
        result = SimpleNamespace(
            part_model_paths=[], individual_only=False, model_path=Path("result.3mf"),
            validation={"valid_solids": True, "self_intersection_warning_parts": 1},
        )
        with patch("spectrum_mapper.gui.messagebox.askyesno", return_value=False) as dialog:
            done(result)
        self.assertIn("bounded minor self-intersections", dialog.call_args.args[1])


class ExportValidationTkTests(unittest.TestCase):
    def test_real_output_selector_round_trip_and_language_change(self):
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        app = None
        try:
            with (
                patch.object(MapperApp, "_load_persistent_settings", return_value=AppSettings()),
                patch("spectrum_mapper.gui.load_language", return_value="ja"),
                patch.object(MapperApp, "_save_persistent_settings") as save,
            ):
                app = MapperApp(root)
                self.assertEqual(str(app.export_validation_combo.cget("state")), "readonly")
                self.assertEqual(tuple(app.export_validation_combo.cget("values")), (
                    "高", "中", "低", "形状の不具合を無視（非推奨）",
                ))
                self.assertFalse(hasattr(app, "export_validation_help_var"))
                self.assertTrue(app.export_validation_combo.bind("<<ComboboxSelected>>"))
                baseline = _geometry_key(app.settings.geometry)
                for level in EXPORT_VALIDATION_LEVELS:
                    app.export_validation_level_var.set(app.i18n.text(f"export.validation.{level}"))
                    app._on_export_validation_changed()
                    settings = app._variables_to_settings(show_error=True)
                    self.assertIsNotNone(settings)
                    self.assertEqual(settings.export_validation_level, level)
                    self.assertEqual(_geometry_key(settings.geometry), baseline)
                self.assertEqual(save.call_count, len(EXPORT_VALIDATION_LEVELS))
                app.i18n = Translator("en")
                app._refresh_export_validation_widgets()
                self.assertEqual(app.export_validation_level_var.get(), "Ignore defects (not recommended)")
                self.assertEqual(app._variables_to_settings().export_validation_level, "ignore")
        finally:
            if app is not None:
                with patch.object(MapperApp, "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
