from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import MapperApp
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import AppSettings, RadialSettings
from spectrum_mapper.radial_shell import RadialShellError


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class RadialSettingsTests(unittest.TestCase):
    def test_default_is_omitted_but_custom_value_round_trips(self) -> None:
        self.assertNotIn("radial", AppSettings().to_dict())
        settings = AppSettings(
            radial=RadialSettings(outer_skin_thickness_mm=0.23)
        )
        encoded = settings.to_dict()
        self.assertAlmostEqual(
            encoded["radial"]["outer_skin_thickness_mm"], 0.23
        )
        restored = AppSettings.from_dict(encoded)
        self.assertAlmostEqual(
            restored.radial.outer_skin_thickness_mm, 0.23
        )

    def test_invalid_thickness_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RadialSettings(outer_skin_thickness_mm=0.10)

    def test_mvp_rejects_layer_height_not_written_by_archive(self) -> None:
        for layer_height in (0.08, 0.12, 0.16):
            with self.subTest(layer_height=layer_height):
                with self.assertRaises(ValueError):
                    RadialSettings(layer_height_mm=layer_height)


class RadialGuiTests(unittest.TestCase):
    @staticmethod
    def _bare_app() -> MapperApp:
        app = MapperApp.__new__(MapperApp)
        app.root = object()
        app.i18n = Translator("ja")
        app.busy = False
        app._developer_features_enabled_committed = True
        app.paint_editor = None
        app.obj_path = Path("C:/models/sample.obj")
        app.prepared = SimpleNamespace()
        app.prepared_key = ("same",)
        app.status_var = FakeVar("")
        app._geometry_key = None
        app._black_output_slot_index = Mock(return_value=0)
        app._validated_manual_overrides = Mock(return_value=(True, None))
        app._variables_to_settings = Mock(return_value=AppSettings())
        app._submit_main = Mock(return_value=True)
        return app

    def test_hidden_developer_feature_blocks_before_editor_and_picker(self) -> None:
        app = self._bare_app()
        app._developer_features_enabled_committed = False
        app.paint_editor = Mock()
        with (
            patch("spectrum_mapper.gui.messagebox.showinfo") as info,
            patch("spectrum_mapper.gui.filedialog.asksaveasfilename") as picker,
        ):
            app._export_radial_experiment()
        self.assertIn("開発者", info.call_args.args[0])
        app.paint_editor.close.assert_not_called()
        picker.assert_not_called()
        app._variables_to_settings.assert_not_called()
        app._submit_main.assert_not_called()

    def test_busy_rejects_before_file_picker(self) -> None:
        app = self._bare_app()
        app.busy = True
        with (
            patch("spectrum_mapper.gui.messagebox.showinfo") as info,
            patch("spectrum_mapper.gui.filedialog.asksaveasfilename") as picker,
        ):
            app._export_radial_experiment()
        picker.assert_not_called()
        self.assertIn("処理中", info.call_args.args[0])

    def test_cancel_does_not_submit(self) -> None:
        app = self._bare_app()
        with (
            patch("spectrum_mapper.gui._geometry_key", return_value=("same",)),
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                return_value="",
            ),
        ):
            app._export_radial_experiment()
        app._submit_main.assert_not_called()

    def test_error_handler_is_localized_and_fail_closed(self) -> None:
        app = self._bare_app()
        submitted: dict[str, object] = {}

        def capture(label, work, done, *, on_error=None):
            submitted.update(on_error=on_error)
            return True

        app._submit_main = capture
        with (
            patch("spectrum_mapper.gui._geometry_key", return_value=("same",)),
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                return_value="C:/out/radial.3mf",
            ),
            patch("spectrum_mapper.gui.messagebox.showerror") as error,
        ):
            app._export_radial_experiment()
            handled = submitted["on_error"](
                RuntimeError("multi-state exterior"), "trace"
            )
        self.assertTrue(handled)
        self.assertEqual(
            error.call_args.args[0],
            "ラジアル実験3MFを生成できません",
        )
        self.assertIn("multi-state exterior", error.call_args.args[1])

    def test_radial_error_code_has_concrete_japanese_and_english_action(self) -> None:
        for language, expected in (("ja", "F3"), ("en", "F3")):
            with self.subTest(language=language):
                app = self._bare_app()
                app.i18n = Translator(language)
                submitted: dict[str, object] = {}

                def capture(label, work, done, *, on_error=None):
                    submitted.update(on_error=on_error)
                    return True

                app._submit_main = capture
                with (
                    patch(
                        "spectrum_mapper.gui._geometry_key",
                        return_value=("same",),
                    ),
                    patch(
                        "spectrum_mapper.gui.filedialog.asksaveasfilename",
                        return_value="C:/out/radial.3mf",
                    ),
                    patch("spectrum_mapper.gui.messagebox.showerror") as error,
                ):
                    app._export_radial_experiment()
                    handled = submitted["on_error"](
                        RadialShellError(
                            "selected_black_not_darkest",
                            {"black_slot": 2, "darkest_slot": 0},
                        ),
                        "trace",
                    )
                message = error.call_args.args[1]
                self.assertTrue(handled)
                self.assertIn(expected, message)
                self.assertIn("F1", message)
                self.assertNotIn("selected_black_not_darkest", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
