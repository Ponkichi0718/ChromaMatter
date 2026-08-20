from __future__ import annotations

import gc
from pathlib import Path
import queue
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import MapperApp
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import AppSettings, PaletteSettings


class CalibrationChartGuiTests(unittest.TestCase):
    def tearDown(self) -> None:
        gc.collect()

    @staticmethod
    def _bare_app(*, language: str = "ja") -> MapperApp:
        app = MapperApp.__new__(MapperApp)
        app.root = object()
        app.i18n = Translator(language)
        app.settings = AppSettings()
        app.active_part_key = None
        app.prepared = None
        app.busy = False
        app.status_var = SimpleNamespace(set=Mock())
        app._thread_progress = Mock()
        return app

    def test_export_snapshots_current_palette_without_an_obj(self) -> None:
        app = self._bare_app()
        current = PaletteSettings(
            palette_state_count=32,
            physical_hex=["#121212", "#EFEFEF", "#D02030", "#704020"],
            enabled_states=[True] * 32,
            mix_ratios_b=[21, 32, 43, 54, 65, 76],
            secondary_mix_ratios_b=[79, 68, 57, 46, 35, 24],
        )
        app._palette_from_variables = Mock(return_value=current)
        submitted: dict[str, object] = {}

        def capture_submit(label, work, done, *, on_error=None):
            submitted.update(
                label=label,
                work=work,
                done=done,
                on_error=on_error,
            )
            return True

        app._submit_main = capture_submit
        result = SimpleNamespace(
            folder=Path("C:/charts/generated"),
            state_count=32,
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "spectrum_mapper.gui.filedialog.askdirectory",
                return_value=temporary,
            ) as folder_dialog,
            patch(
                "spectrum_mapper.gui.generate_palette_calibration_bundle",
                return_value=result,
            ) as generate,
        ):
            app._export_palette_calibration_chart()
            self.assertIn("work", submitted)
            # Prove that the worker owns a frozen snapshot, not GUI-owned lists.
            current.physical_hex[0] = "#FFFFFF"
            current.mix_ratios_b[0] = 99
            self.assertIs(submitted["work"](), result)

        folder_dialog.assert_called_once()
        args, kwargs = generate.call_args
        self.assertEqual(args[0], Path(temporary).resolve())
        snapshot = args[1]
        self.assertIsNot(snapshot, current)
        self.assertEqual(snapshot.physical_hex[0], "#121212")
        self.assertEqual(snapshot.mix_ratios_b[0], 21)
        self.assertEqual(snapshot.palette_state_count, 32)
        self.assertEqual(kwargs["language"], "ja")
        self.assertEqual(kwargs["target_label"], "全体共通")
        self.assertFalse(hasattr(app, "obj_path"))

    def test_selected_part_name_is_used_as_snapshot_target(self) -> None:
        app = self._bare_app(language="en")
        app.active_part_key = "part-key-b"
        app.prepared = SimpleNamespace(
            final=SimpleNamespace(
                part_keys=("part-key-a", "part-key-b"),
                part_names=("Body", "Cape"),
            )
        )
        self.assertEqual(app._calibration_target_label(), "Cape")

        app.prepared = None
        app.settings.part_names["part-key-b"] = "Saved Cape"
        self.assertEqual(app._calibration_target_label(), "Saved Cape")

    def test_busy_state_is_rejected_before_folder_picker(self) -> None:
        app = self._bare_app(language="en")
        app.busy = True
        app._palette_from_variables = Mock()
        app._submit_main = Mock()
        with (
            patch("spectrum_mapper.gui.messagebox.showinfo") as info,
            patch("spectrum_mapper.gui.filedialog.askdirectory") as folder_dialog,
        ):
            app._export_palette_calibration_chart()
        folder_dialog.assert_not_called()
        app._palette_from_variables.assert_not_called()
        app._submit_main.assert_not_called()
        self.assertEqual(info.call_args.args[0], "Processing")

    def test_invalid_palette_stops_before_folder_picker(self) -> None:
        app = self._bare_app()
        app._palette_from_variables = Mock(side_effect=ValueError("bad ratio"))
        app._submit_main = Mock()
        with (
            patch("spectrum_mapper.gui.messagebox.showerror") as error,
            patch("spectrum_mapper.gui.filedialog.askdirectory") as folder_dialog,
        ):
            app._export_palette_calibration_chart()
        folder_dialog.assert_not_called()
        app._submit_main.assert_not_called()
        self.assertEqual(error.call_args.args[0], "実機比較チャートを生成できません")
        self.assertIn("bad ratio", error.call_args.args[1])

    def test_cancelled_folder_picker_does_not_submit(self) -> None:
        app = self._bare_app()
        app._palette_from_variables = Mock(return_value=PaletteSettings())
        app._submit_main = Mock()
        with patch(
            "spectrum_mapper.gui.filedialog.askdirectory", return_value=""
        ):
            app._export_palette_calibration_chart()
        app._submit_main.assert_not_called()

    def test_worker_failure_uses_localized_error_handler(self) -> None:
        app = self._bare_app(language="en")
        app._palette_from_variables = Mock(return_value=PaletteSettings())
        submitted: dict[str, object] = {}

        def capture_submit(label, work, done, *, on_error=None):
            submitted.update(on_error=on_error)
            return True

        app._submit_main = capture_submit
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "spectrum_mapper.gui.filedialog.askdirectory",
                return_value=temporary,
            ),
            patch("spectrum_mapper.gui.messagebox.showerror") as error,
        ):
            app._export_palette_calibration_chart()
            handled = submitted["on_error"](RuntimeError("disk full"), "trace")
        self.assertTrue(handled)
        self.assertEqual(
            error.call_args.args[0],
            "Could Not Create Physical Comparison Chart",
        )
        self.assertIn("disk full", error.call_args.args[1])

    def test_success_dialog_can_open_generated_folder(self) -> None:
        app = self._bare_app(language="en")
        app._palette_from_variables = Mock(return_value=PaletteSettings())
        submitted: dict[str, object] = {}

        def capture_submit(label, work, done, *, on_error=None):
            submitted.update(done=done)
            return True

        app._submit_main = capture_submit
        result = SimpleNamespace(folder=Path("C:/charts/bundle"), state_count=16)
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "spectrum_mapper.gui.filedialog.askdirectory",
                return_value=temporary,
            ),
            patch(
                "spectrum_mapper.gui.messagebox.askyesno", return_value=True
            ) as question,
            patch("spectrum_mapper.gui.os.startfile", create=True) as startfile,
        ):
            app._export_palette_calibration_chart()
            submitted["done"](result)
        self.assertEqual(
            question.call_args.args[0], "Physical Comparison Chart Created"
        )
        self.assertIn("16-state", question.call_args.args[1])
        startfile.assert_called_once_with(result.folder)

    def test_main_worker_disables_both_export_actions(self) -> None:
        app = self._bare_app()
        app.progress = {}
        app.export_button = SimpleNamespace(state=Mock())
        app.calibration_chart_button = SimpleNamespace(state=Mock())
        app.main_executor = SimpleNamespace(submit=Mock())
        accepted = app._submit_main("working", Mock(), Mock())
        self.assertTrue(accepted)
        app.export_button.state.assert_called_once_with(["disabled"])
        app.calibration_chart_button.state.assert_called_once_with(["disabled"])

    def test_poll_restores_both_export_actions_after_success(self) -> None:
        app = self._bare_app()
        app.busy = True
        app.progress = {}
        app.export_button = SimpleNamespace(state=Mock())
        app.calibration_chart_button = SimpleNamespace(state=Mock())
        app.work_queue = queue.Queue()
        app.app_closing = True
        done = Mock()
        value = object()
        app.work_queue.put(("main_done", (done, value)))
        app._poll_queue()
        self.assertFalse(app.busy)
        app.export_button.state.assert_called_once_with(["!disabled"])
        app.calibration_chart_button.state.assert_called_once_with(["!disabled"])
        done.assert_called_once_with(value)


class CalibrationChartLiveLanguageTests(unittest.TestCase):
    def test_chart_controls_switch_between_japanese_and_english(self) -> None:
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        app = None
        try:
            with (
                patch.object(
                    MapperApp,
                    "_load_persistent_settings",
                    return_value=AppSettings(),
                ),
                patch("spectrum_mapper.gui.load_language", return_value="ja"),
                patch.object(MapperApp, "_save_persistent_settings"),
                patch("spectrum_mapper.gui.save_language"),
            ):
                app = MapperApp(root)
                root.update_idletasks()
                self.assertIn(
                    "実機比較チャート",
                    app.calibration_chart_button.cget("text"),
                )
                app.set_language("en")
                root.update_idletasks()
                self.assertEqual(
                    app.calibration_chart_button.cget("text"),
                    "Generate Physical Comparison Chart…",
                )
                self.assertIn(
                    "No OBJ is required",
                    app.calibration_chart_help_label.cget("text"),
                )
        finally:
            if app is not None:
                with patch.object(MapperApp, "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
