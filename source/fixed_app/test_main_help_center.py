from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import AppSettings  # noqa: E402


class MainHelpCenterIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        self.root.withdraw()

        from spectrum_mapper.gui import MapperApp

        self._persistent = patch.object(
            MapperApp,
            "_load_persistent_settings",
            return_value=AppSettings(),
        )
        self._save_settings = patch.object(
            MapperApp,
            "_save_persistent_settings",
        )
        self._language = patch("spectrum_mapper.gui.load_language", return_value="ja")
        self._save_language = patch("spectrum_mapper.gui.save_language")
        for active_patch in (
            self._persistent,
            self._save_settings,
            self._language,
            self._save_language,
        ):
            active_patch.start()
            self.addCleanup(active_patch.stop)
        self.app = MapperApp(self.root)
        self.root.update_idletasks()

    def tearDown(self) -> None:
        app = getattr(self, "app", None)
        if app is not None:
            try:
                app._on_close()
            except Exception:
                pass
        root = getattr(self, "root", None)
        if root is not None:
            try:
                if root.winfo_exists():
                    root.destroy()
            except Exception:
                pass

    def test_public_help_entries_are_hidden_while_source_remains_callable(self) -> None:
        app = self.app
        self.assertEqual(app.help_button.cget("text"), "使い方")
        self.assertEqual(app.help_button.winfo_manager(), "")
        self.assertEqual(app.main_ribbon_help_button.winfo_manager(), "")
        self.assertEqual(self.root.bind("<F1>"), "")

        first = app._show_help_center("first_steps")
        window = first.window
        second = app._show_help_center("first_steps")
        self.root.update_idletasks()

        self.assertIs(second, first)
        self.assertIs(first.window, window)
        self.assertEqual(first.current_topic_id, "first_steps")
        self.assertIsNone(first.window.grab_current())

    def test_context_help_tracks_the_current_ribbon_tab(self) -> None:
        app = self.app
        self.assertEqual(app.main_ribbon_help_button.cget("text"), "?")

        app._main_ribbon_selected = "filament"
        app._show_context_help()
        self.assertEqual(app.help_center.current_topic_id, "parts_palette")

        app._main_ribbon_selected = "output"
        app._show_context_help()
        self.assertEqual(app.help_center.current_topic_id, "export_3mf")

    def test_help_actions_use_existing_guarded_commands(self) -> None:
        app = self.app
        center = app._show_help_center("first_steps")

        app._main_ribbon_selected = "output"
        app._main_ribbon_expanded = False
        center.navigate("parts_palette")
        center.action_buttons["select_filament"].invoke()
        self.assertEqual(app._main_ribbon_selected, "filament")
        self.assertTrue(app._main_ribbon_expanded)

        with patch("spectrum_mapper.gui.messagebox.showinfo") as showinfo:
            center.navigate("manual_editing")
            center.action_buttons["open_manual"].invoke()
            center.navigate("export_3mf")
            center.action_buttons["export"].invoke()
        self.assertEqual(showinfo.call_count, 2)

        with patch(
            "spectrum_mapper.gui.filedialog.askopenfilename",
            return_value="",
        ) as ask_open:
            center.navigate("first_steps")
            center.action_buttons["open_obj"].invoke()
        ask_open.assert_called_once()

    def test_language_switch_refreshes_toolbar_and_live_help(self) -> None:
        app = self.app
        center = app._show_help_center("auto_mapping")
        original_window = center.window

        app.set_language("en", persist=False)
        self.root.update_idletasks()
        self.assertEqual(app.help_button.cget("text"), "Help")
        self.assertIs(app.help_center.window, original_window)
        self.assertEqual(app.help_center.window.title(), "Help Center")
        self.assertEqual(
            app.help_center.topic_title_label.cget("text"),
            "Automatic Mapping & Black-Free Gradient",
        )

        app.set_language("ja", persist=False)
        self.root.update_idletasks()
        self.assertEqual(app.help_button.cget("text"), "使い方")
        self.assertEqual(app.help_center.window.title(), "使い方・ヘルプ")

    def test_application_close_destroys_help_toplevel(self) -> None:
        app = self.app
        center = app._show_help_center("first_steps")
        self.assertIsNotNone(center.window)

        app._on_close()
        self.app = None

        self.assertIsNone(center.window)
        self.assertIsNone(app.help_center)


if __name__ == "__main__":
    unittest.main(verbosity=2)
