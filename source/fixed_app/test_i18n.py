from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.i18n import (
    CATALOG,
    Translator,
    load_language,
    save_language,
)
from spectrum_mapper.models import AppSettings


class TranslationCatalogTests(unittest.TestCase):
    def test_every_catalog_entry_has_japanese_and_english(self) -> None:
        self.assertGreaterEqual(len(CATALOG), 100)
        for key, translations in CATALOG.items():
            with self.subTest(key=key):
                self.assertTrue(translations.get("ja"))
                self.assertTrue(translations.get("en"))

    def test_known_text_can_switch_both_directions(self) -> None:
        translator = Translator("ja")
        self.assertEqual(translator.text("toolbar.open_obj"), "OBJ / GLBを開く")
        translator.set_language("en")
        self.assertEqual(translator.text("toolbar.open_obj"), "Open OBJ / GLB")
        self.assertEqual(
            translator.translate_known("OBJ / GLBを開く"), "Open OBJ / GLB"
        )
        translator.set_language("ja")
        self.assertEqual(
            translator.translate_known("Open OBJ / GLB"), "OBJ / GLBを開く"
        )

    def test_manual_editing_name_is_exact_in_both_languages(self) -> None:
        translator = Translator("ja")
        self.assertEqual(translator.text("toolbar.open_paint"), "マニュアル修正")
        self.assertEqual(translator.text("paint.title"), "マニュアル修正")
        translator.set_language("en")
        self.assertEqual(translator.text("toolbar.open_paint"), "Manual Editing")
        self.assertEqual(translator.text("paint.title"), "Manual Editing")

    def test_freehand_feature_keys_are_ready_for_geometry_ui(self) -> None:
        translator = Translator("en")
        self.assertEqual(
            translator.text("separate.freehand"), "Freehand Separation"
        )
        self.assertIn(
            "preserving its colors",
            translator.text("separate.floating_help"),
        )
        self.assertEqual(
            translator.text("separate.finish"),
            "Create Part from Enclosed Region",
        )
        self.assertIn("preserving color", translator.text("separate.help"))
        confirmation = translator.text(
            "separate.confirm_message",
            source="Cape",
            faces=1234,
            new_name="Pendant",
            coverage=98.5,
        )
        self.assertIn("1,234 faces", confirmation)
        self.assertIn("98.5%", confirmation)

    def test_freehand_errors_are_localized_without_changing_cli_text(self) -> None:
        from spectrum_mapper.freehand_split import FreehandSplitError

        error = FreehandSplitError(
            "フリーハンド領域は3点以上で囲んでください",
            "separate.error.too_few_points",
        )
        self.assertIn("3点以上", str(error))
        self.assertEqual(
            error.localized(Translator("en")),
            "Draw at least three points to enclose the region.",
        )


class LanguagePreferenceTests(unittest.TestCase):
    def test_saved_language_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ui_preferences.json"
            save_language("en", path)
            self.assertEqual(load_language(path), "en")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["language"], "en")

    def test_environment_overrides_saved_language(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ui_preferences.json"
            save_language("ja", path)
            with patch.dict(os.environ, {"TRIPO_SPECTRUM_LANGUAGE": "en-US"}):
                self.assertEqual(load_language(path), "en")

    def test_first_run_uses_os_locale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.json"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("spectrum_mapper.i18n.locale.getlocale", return_value=("ja_JP", "UTF-8")),
            ):
                self.assertEqual(load_language(missing), "ja")
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("spectrum_mapper.i18n.locale.getlocale", return_value=("de_DE", "UTF-8")),
            ):
                self.assertEqual(load_language(missing), "en")


class LiveGuiLanguageTests(unittest.TestCase):
    def test_main_ui_switches_without_rebuilding_or_losing_values(self) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        app = None
        try:
            from spectrum_mapper.gui import MapperApp

            with (
                patch.object(
                    MapperApp,
                    "_load_persistent_settings",
                    return_value=AppSettings(),
                ),
                patch("spectrum_mapper.gui.load_language", return_value="ja"),
                patch("spectrum_mapper.gui.save_language") as save_mock,
                patch.object(MapperApp, "_save_persistent_settings"),
            ):
                app = MapperApp(root)
                root.update_idletasks()
                original_entry = app.physical_vars[0].get()

                app.set_language("en")
                root.update_idletasks()
                self.assertEqual(app.language_var.get(), "English")
                self.assertEqual(app.export_button.cget("text"), "Export 3MF")
                self.assertEqual(app.manual_edit_button.cget("text"), "Manual Editing")
                self.assertEqual(app.physical_vars[0].get(), original_entry)
                save_mock.assert_called_with("en")

                self.assertEqual(
                    tuple(
                        app.main_ribbon_tab_buttons[name].cget("text")
                        for name in ("filament", "output")
                    ),
                    ("Filament Settings", "Output Settings"),
                )
                self.assertEqual(
                    app.extended_palette_checkbutton.cget("text"),
                    "Use the shown mixes for automatic mapping",
                )
                self.assertEqual(app.language_label.cget("text"), "言語")
                self.assertEqual(
                    app.developer_features_enable_checkbutton.cget("text"),
                    "Show Developer Experimental Features",
                )
                self.assertEqual(app.part_target_var.get(), "Common to All")

                app.set_language("ja", persist=False)
                root.update_idletasks()
                self.assertEqual(app.export_button.cget("text"), "3MFを書き出す")
                self.assertEqual(app.manual_edit_button.cget("text"), "マニュアル修正")
                self.assertEqual(
                    app.extended_palette_checkbutton.cget("text"),
                    "表示中の混色を自動割当に使う",
                )
                self.assertEqual(app.language_label.cget("text"), "Language")
                self.assertEqual(
                    app.developer_features_enable_checkbutton.cget("text"),
                    "開発者向け実験機能を表示",
                )
                self.assertEqual(app.part_target_var.get(), "全体共通")
        finally:
            if app is not None:
                with patch.object(type(app), "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()

    @staticmethod
    def _descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from LiveGuiLanguageTests._descendants(child)


if __name__ == "__main__":
    unittest.main(verbosity=2)
