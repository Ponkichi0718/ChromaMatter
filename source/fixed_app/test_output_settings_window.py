from __future__ import annotations

import gc
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from spectrum_mapper.gui import MapperApp, _geometry_key
from spectrum_mapper.models import AppSettings


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class OutputSettingsWindowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        self.root.withdraw()
        self.patches = (
            patch.object(MapperApp, "_load_persistent_settings", return_value=AppSettings()),
            patch("spectrum_mapper.gui.load_language", return_value="ja"),
            patch.object(MapperApp, "_save_persistent_settings"),
        )
        for item in self.patches:
            item.start()
        self.app = MapperApp(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.busy = False
            for timer in self.root.tk.call("after", "info"):
                self.root.after_cancel(timer)
            self.app._on_close()
        elif hasattr(self, "root"):
            self.root.destroy()
        for item in getattr(self, "patches", ()):
            item.stop()
        gc.collect()

    def test_eager_modeless_window_replaces_output_ribbon_page(self):
        app = self.app
        self.assertEqual(tuple(app.main_ribbon_pages), ("filament",))
        self.assertEqual(tuple(app.main_ribbon_tab_buttons), ("filament",))
        self.assertIsInstance(app.output_settings_window, tk.Toplevel)
        self.assertIs(app.output_settings_window.master, self.root)
        self.assertEqual(app.output_settings_window.state(), "withdrawn")
        self.assertIsNone(self.root.grab_current())
        window_path = str(app.output_settings_window)
        self.assertTrue(str(app.output_settings_page).startswith(window_path + "."))
        self.assertTrue(str(app.target_faces_entry).startswith(window_path + "."))
        self.assertTrue(str(app.export_validation_combo).startswith(window_path + "."))
        self.assertEqual(app.export_validation_level_var.get(), "高")
        self.assertEqual(app.radial_group.winfo_manager(), "")
        self.assertFalse(app.radial_enabled_var.get())

    def test_footer_actions_share_parent_and_required_order(self):
        app = self.app
        buttons = (app.output_settings_button, app.close_parts_safely_button, app.export_button)
        self.assertEqual(tuple(button.cget("text") for button in buttons), (
            "出力設定", "閉立体化", "3MFを書き出す",
        ))
        for column, button in zip((2, 3, 4), buttons):
            self.assertIs(button.master, app.footer)
            self.assertEqual(int(button.grid_info()["row"]), 0)
            self.assertEqual(int(button.grid_info()["column"]), column)
        solidify_buttons = [
            widget for widget in descendants(self.root)
            if isinstance(widget, ttk.Button) and widget.cget("text") == "閉立体化"
        ]
        self.assertEqual(solidify_buttons, [app.close_parts_safely_button])
        self.assertTrue(app.close_parts_safely_button.instate(["disabled"]))

    def test_reopen_preserves_pending_values_and_same_widget_instances(self):
        app = self.app
        self.root.state("normal")
        identities = tuple(map(id, (
            app.output_settings_window, app.output_settings_page,
            app.target_faces_entry, app.reprocess_geometry_button,
            app.export_validation_combo, app.close_parts_safely_button,
        )))
        original_geometry_key = _geometry_key(app.settings.geometry)
        app.height_var.set(217.3)
        app.target_faces_var.set(1_234_567)
        app.preview_faces_var.set(63_000)
        app.include_obj_var.set(False)
        app.export_individual_parts_var.set(False)
        app.export_validation_level_var.set("低")
        with patch.object(app, "_settings_to_variables") as reset:
            for _ in range(3):
                app._show_output_settings()
                self.root.update_idletasks()
                self.assertEqual(app.output_settings_window.state(), "normal")
                self.assertIsNone(self.root.grab_current())
                app._hide_output_settings()
                self.assertEqual(app.output_settings_window.state(), "withdrawn")
            reset.assert_not_called()
        self.assertEqual(identities, tuple(map(id, (
            app.output_settings_window, app.output_settings_page,
            app.target_faces_entry, app.reprocess_geometry_button,
            app.export_validation_combo, app.close_parts_safely_button,
        ))))
        self.assertEqual(app.height_var.get(), 217.3)
        self.assertEqual(app.target_faces_var.get(), 1_234_567)
        self.assertEqual(app.preview_faces_var.get(), 63_000)
        self.assertFalse(app.include_obj_var.get())
        self.assertFalse(app.export_individual_parts_var.get())
        self.assertEqual(app.export_validation_level_var.get(), "低")
        self.assertEqual(_geometry_key(app.settings.geometry), original_geometry_key)
        settings = app._variables_to_settings(show_error=True)
        self.assertEqual(settings.geometry.height_mm, 217.3)
        self.assertEqual(settings.geometry.target_faces, 1_234_567)
        self.assertEqual(settings.geometry.preview_faces, 63_000)
        self.assertFalse(settings.geometry.export_individual_parts)
        self.assertEqual(settings.export_validation_level, "low")

    def test_titlebar_close_escape_and_close_button_withdraw_without_destroying(self):
        app = self.app
        window = app.output_settings_window
        self.root.state("normal")
        for action in (
            lambda: window.tk.call(window.protocol("WM_DELETE_WINDOW")),
            lambda: window.event_generate("<Escape>"),
            lambda: app.output_settings_close_button.invoke(),
        ):
            app._show_output_settings()
            window.focus_force()
            self.root.update()
            action()
            self.root.update_idletasks()
            self.assertTrue(window.winfo_exists())
            self.assertEqual(window.state(), "withdrawn")
        self.assertTrue(window.bind("<Escape>"))
        self.assertIsNone(self.root.grab_current())

    def test_legacy_output_tab_request_opens_window_without_changing_ribbon(self):
        app = self.app
        self.root.state("normal")
        app._toggle_main_ribbon()
        before = (app._main_ribbon_selected, app._main_ribbon_expanded)
        app._on_main_ribbon_tab_clicked("output")
        self.assertEqual((app._main_ribbon_selected, app._main_ribbon_expanded), before)
        self.assertEqual(app.output_settings_window.state(), "normal")
        self.assertIsNone(self.root.grab_current())

    def test_language_switch_updates_both_surfaces_without_rebuilding(self):
        app = self.app
        window = app.output_settings_window
        combo = app.export_validation_combo
        app.settings.export_validation_level = "ignore"
        app._refresh_export_validation_widgets()
        app.height_var.set(210.5)
        for language, title, ignore in (
            ("en", "Output Settings", "Ignore defects (not recommended)"),
            ("ja", "出力設定", "形状の不具合を無視（非推奨）"),
        ):
            app.set_language(language, persist=False)
            app._show_output_settings()
            self.root.update_idletasks()
            self.assertIs(app.output_settings_window, window)
            self.assertIs(app.export_validation_combo, combo)
            self.assertEqual(window.title(), title)
            self.assertEqual(app.output_settings_button.cget("text"), title)
            self.assertEqual(app.export_validation_level_var.get(), ignore)
            self.assertEqual(app.height_var.get(), 210.5)
            self.assertEqual(app.radial_group.winfo_manager(), "")
            self.assertIsNone(self.root.grab_current())
            app._hide_output_settings()

    def test_busy_worker_hides_settings_and_blocks_actions_until_idle(self):
        app = self.app
        app.source_path = Path("synthetic.glb")
        app._refresh_output_actions()
        self.assertFalse(app.close_parts_safely_button.instate(["disabled"]))
        app._show_output_settings()
        with patch.object(app.main_executor, "submit"):
            self.assertTrue(app._submit_main("Working", lambda: None, lambda _value: None))
        self.assertTrue(app.busy)
        self.assertEqual(app.output_settings_window.state(), "withdrawn")
        self.assertTrue(app.output_settings_button.instate(["disabled"]))
        self.assertTrue(app.close_parts_safely_button.instate(["disabled"]))
        self.assertTrue(app.export_button.instate(["disabled"]))
        with patch("spectrum_mapper.gui.messagebox.showinfo"):
            app._show_output_settings()
        self.assertEqual(app.output_settings_window.state(), "withdrawn")
        with patch.object(app, "_close_parts_safely") as close:
            app._solidify_from_footer()
        close.assert_not_called()
        app.busy = False
        app._refresh_output_actions()
        self.assertFalse(app.output_settings_button.instate(["disabled"]))
        self.assertFalse(app.close_parts_safely_button.instate(["disabled"]))
        app.source_path = None
        app._refresh_output_actions()
        self.assertTrue(app.close_parts_safely_button.instate(["disabled"]))

    def _deliver_worker_message(self, kind, payload):
        """Drain the real UI queue once, without leaving a second timer poll."""
        app = self.app
        self.assertTrue(app.work_queue.empty())
        if app.poll_after_id is not None:
            self.root.after_cancel(app.poll_after_id)
            app.poll_after_id = None
        app.work_queue.put((kind, payload))
        try:
            app._poll_queue()
            self.assertTrue(app.work_queue.empty())
        finally:
            if app.poll_after_id is not None:
                self.root.after_cancel(app.poll_after_id)
                app.poll_after_id = None

    def test_queued_completion_refreshes_actions_after_installing_or_clearing_source(self):
        app = self.app
        self.assertIsNone(app.source_path)
        self.assertTrue(app.close_parts_safely_button.instate(["disabled"]))
        for source in (Path("synthetic.glb"), None):
            with self.subTest(source_exists=source is not None):
                done = Mock(side_effect=lambda value: setattr(app, "source_path", value))
                with patch.object(app.main_executor, "submit"):
                    self.assertTrue(app._submit_main("Loading", lambda: None, done))
                self._deliver_worker_message("main_done", (done, source, None))
                done.assert_called_once_with(source)
                self.assertFalse(app.busy)
                self.assertFalse(app.output_settings_button.instate(["disabled"]))
                self.assertEqual(app.close_parts_safely_button.instate(["disabled"]), source is None)
                self.assertFalse(app.export_button.instate(["disabled"]))

    def test_queued_completion_that_starts_another_worker_keeps_actions_locked(self):
        app = self.app
        app.source_path = Path("synthetic.glb")
        app._refresh_output_actions()
        self.root.state("normal")
        app._show_output_settings()
        self.root.update_idletasks()
        self.assertEqual(app.output_settings_window.state(), "normal")

        def start_next(_value):
            self.assertFalse(app.busy)
            self.assertTrue(app._submit_main("Next operation", lambda: None, lambda _result: None))
            app._show_output_settings()

        with patch.object(app.main_executor, "submit") as submit:
            self.assertTrue(app._submit_main("First operation", lambda: None, start_next))
            self._deliver_worker_message("main_done", (start_next, object(), None))
            self.assertEqual(submit.call_count, 2)
        self.assertTrue(app.busy)
        for button in (app.output_settings_button, app.close_parts_safely_button, app.export_button):
            self.assertTrue(button.instate(["disabled"]))
        self.assertEqual(app.output_settings_window.state(), "withdrawn")

    def test_queued_error_refreshes_after_recovery_installs_or_clears_source(self):
        app = self.app
        for source in (Path("recovered.glb"), None):
            with self.subTest(source_exists=source is not None):
                def recover(_exc, _details):
                    app.source_path = source
                    return True

                handler = Mock(side_effect=recover)
                problem = ValueError("synthetic failure")
                with patch.object(app.main_executor, "submit"):
                    self.assertTrue(app._submit_main("Loading", lambda: None, lambda _value: None, on_error=handler))
                with patch("spectrum_mapper.gui.messagebox.showerror") as dialog:
                    self._deliver_worker_message("main_error", (problem, "synthetic details", handler))
                handler.assert_called_once_with(problem, "synthetic details")
                dialog.assert_not_called()
                self.assertFalse(app.busy)
                self.assertFalse(app.output_settings_button.instate(["disabled"]))
                self.assertEqual(app.close_parts_safely_button.instate(["disabled"]), source is None)
                self.assertFalse(app.export_button.instate(["disabled"]))

    def test_failing_completion_refreshes_after_its_recovery_callback(self):
        app = self.app
        problem = ValueError("synthetic installation failure")
        done = Mock(side_effect=problem)

        def recover(_exc, _details):
            app.source_path = Path("recovered.glb")
            return True

        handler = Mock(side_effect=recover)
        with patch.object(app.main_executor, "submit"):
            self.assertTrue(app._submit_main("Loading", lambda: None, done, on_error=handler))
        with patch("spectrum_mapper.gui.messagebox.showerror") as dialog:
            self._deliver_worker_message("main_done", (done, None, handler))
        handler.assert_called_once()
        self.assertIs(handler.call_args.args[0], problem)
        dialog.assert_not_called()
        self.assertFalse(app.busy)
        self.assertFalse(app.output_settings_button.instate(["disabled"]))
        self.assertFalse(app.close_parts_safely_button.instate(["disabled"]))

    def test_footer_buttons_fit_supported_sizes_even_with_long_status(self):
        app = self.app
        self.root.state("normal")
        app.status_var.set("Very long processing status / " * 100)
        buttons = (app.output_settings_button, app.close_parts_safely_button, app.export_button)
        for language in ("ja", "en"):
            app.set_language(language, persist=False)
            for width, height in ((1180, 740), (1540, 920)):
                with self.subTest(language=language, width=width):
                    self.root.geometry(f"{width}x{height}+0+0")
                    self.root.update_idletasks()
                    client_width, client_height = self.root.winfo_width(), self.root.winfo_height()
                    previous_right = 0
                    for button in buttons:
                        left = button.winfo_rootx() - self.root.winfo_rootx()
                        top = button.winfo_rooty() - self.root.winfo_rooty()
                        right, bottom = left + button.winfo_width(), top + button.winfo_height()
                        self.assertGreaterEqual(left, previous_right)
                        self.assertGreaterEqual(top, 0)
                        self.assertLessEqual(right, client_width)
                        self.assertLessEqual(bottom, client_height)
                        self.assertGreater(button.winfo_width(), 40)
                        previous_right = right

    def test_output_window_reflows_and_scrolls_without_hiding_close_action(self):
        app = self.app
        self.root.state("normal")
        app._show_output_settings()
        window, canvas = app.output_settings_window, app.output_settings_canvas
        for language in ("ja", "en"):
            app.set_language(language, persist=False)
            for width, height, assembly_row, assembly_column in (
                (1080, 620, 0, 1), (640, 480, 1, 0),
            ):
                with self.subTest(language=language, width=width):
                    window.geometry(f"{width}x{height}+0+0")
                    self.root.update()
                    self.assertEqual(int(app.output_assembly_group.grid_info()["row"]), assembly_row)
                    self.assertEqual(int(app.output_assembly_group.grid_info()["column"]), assembly_column)
                    self.assertEqual(app.output_settings_page.winfo_width(), canvas.winfo_width())
                    canvas.yview_moveto(1.0)
                    self.root.update_idletasks()
                    close = app.output_settings_close_button
                    left = close.winfo_rootx() - window.winfo_rootx()
                    top = close.winfo_rooty() - window.winfo_rooty()
                    self.assertGreaterEqual(left, 0)
                    self.assertGreaterEqual(top, 0)
                    self.assertLessEqual(left + close.winfo_width(), window.winfo_width())
                    self.assertLessEqual(top + close.winfo_height(), window.winfo_height())
                    self.assertIsNone(self.root.grab_current())
                    self.assertEqual(app.radial_group.winfo_manager(), "")
                    if width == 640:
                        self.assertGreater(canvas.yview()[0], 0.0)


if __name__ == "__main__":
    unittest.main()
