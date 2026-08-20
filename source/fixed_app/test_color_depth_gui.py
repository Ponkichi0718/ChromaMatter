from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from spectrum_mapper.color_depth_workflow import ColorDepthWorkflowError
from spectrum_mapper.gui import MapperApp
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import AppSettings, ColorDepthSettings


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class ColorDepthGuiTests(unittest.TestCase):
    @staticmethod
    def _bare_app() -> MapperApp:
        app = MapperApp.__new__(MapperApp)
        app.root = object()
        app.i18n = Translator("ja")
        app.busy = False
        app._developer_features_enabled_committed = True
        app.paint_editor = None
        app.obj_path = Path("C:/models/multi-state-head.obj")
        app.prepared = SimpleNamespace()
        app.prepared_key = ("same",)
        app.asset = None
        app.active_part_key = "2:tripo_part_2"
        app.status_var = FakeVar("")
        app._validated_manual_overrides = Mock(return_value=(True, None))
        app._variables_to_settings = Mock(
            return_value=AppSettings(
                color_depth=ColorDepthSettings(experimental_enabled=True)
            )
        )
        app._submit_main = Mock(return_value=True)
        return app

    def test_hidden_developer_feature_blocks_both_routes_before_any_picker(self) -> None:
        app = self._bare_app()
        app._developer_features_enabled_committed = False
        app.paint_editor = Mock()
        with (
            patch("spectrum_mapper.gui.messagebox.showinfo") as info,
            patch("spectrum_mapper.gui.messagebox.askokcancel") as confirm,
            patch("spectrum_mapper.gui.filedialog.askopenfilename") as open_picker,
            patch("spectrum_mapper.gui.filedialog.asksaveasfilename") as save_picker,
        ):
            app._convert_color_depth_part_3mf()
            app._export_color_depth_experiment()
        self.assertEqual(info.call_count, 2)
        self.assertTrue(
            all("開発者" in call.args[0] for call in info.call_args_list)
        )
        confirm.assert_not_called()
        open_picker.assert_not_called()
        save_picker.assert_not_called()
        app.paint_editor.close.assert_not_called()
        app._variables_to_settings.assert_not_called()
        app._submit_main.assert_not_called()

    def test_uncalibrated_warning_must_be_accepted_before_file_picker(self) -> None:
        app = self._bare_app()
        with (
            patch("spectrum_mapper.gui._geometry_key", return_value=("same",)),
            patch(
                "spectrum_mapper.gui.messagebox.askokcancel",
                return_value=False,
            ) as confirmation,
            patch("spectrum_mapper.gui.filedialog.asksaveasfilename") as picker,
        ):
            app._export_color_depth_experiment()
        confirmation.assert_called_once()
        self.assertIn("SLICE ONLY", confirmation.call_args.args[1])
        self.assertIn("Ratio", confirmation.call_args.args[1])
        picker.assert_not_called()
        app._submit_main.assert_not_called()

    def test_export_uses_color_depth_facade_without_black_slot(self) -> None:
        app = self._bare_app()
        submitted = {}

        def capture(label, work, done, *, on_error=None):
            submitted.update(label=label, work=work, done=done, on_error=on_error)
            return True

        app._submit_main = capture
        with (
            patch("spectrum_mapper.gui._geometry_key", return_value=("same",)),
            patch("spectrum_mapper.gui.messagebox.askokcancel", return_value=True),
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                return_value="C:/out/head_ColorDepthLab_SLICE_ONLY.3mf",
            ) as picker,
            patch(
                "spectrum_mapper.gui.export_color_depth_bundle",
                return_value=SimpleNamespace(),
            ) as export,
        ):
            app._export_color_depth_experiment()
            submitted["work"]()
        self.assertIn("ColorDepthLab_SLICE_ONLY", picker.call_args.kwargs["initialfile"])
        export.assert_called_once()
        self.assertNotIn("black_slot", export.call_args.kwargs)
        self.assertEqual(export.call_args.kwargs["part_key"], "2:tripo_part_2")

    def test_builder_failure_is_localized_and_never_approximated(self) -> None:
        app = self._bare_app()
        submitted = {}

        def capture(_label, _work, _done, *, on_error=None):
            submitted["on_error"] = on_error
            return True

        app._submit_main = capture
        with (
            patch("spectrum_mapper.gui._geometry_key", return_value=("same",)),
            patch("spectrum_mapper.gui.messagebox.askokcancel", return_value=True),
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                return_value="C:/out/head.3mf",
            ),
            patch("spectrum_mapper.gui.messagebox.showerror") as error,
        ):
            app._export_color_depth_experiment()
            handled = submitted["on_error"](
                ColorDepthWorkflowError("geometry_builder_unavailable"),
                "trace",
            )
        self.assertTrue(handled)
        self.assertIn("ColorDepth", error.call_args.args[0])
        self.assertNotIn("geometry_builder_unavailable", error.call_args.args[1])

    def test_per_part_3mf_conversion_needs_no_obj_and_inspects_before_save(self) -> None:
        app = self._bare_app()
        app.obj_path = None
        app.prepared = None
        app._thread_progress = Mock()
        submissions = []

        def capture(label, work, done, *, on_error=None):
            submissions.append(
                SimpleNamespace(
                    label=label,
                    work=work,
                    done=done,
                    on_error=on_error,
                )
            )
            return True

        app._submit_main = capture
        imported = SimpleNamespace(
            physical_slot_order=(
                "#080808",
                "#F5F3EE",
                "#D92B32",
                "#B8753D",
            ),
            palette_state_count=24,
            print_mix_specs=(
                (1, 2),
                (1, 3),
                (1, 4),
                (2, 3),
                (2, 4),
                (3, 4),
            )
            * 3
            + ((1, 2), (1, 3)),
            metadata={"schema": "tripo-spectrum-mapper.palette.v1"},
        )
        result = SimpleNamespace(
            model_path=Path("C:/jobs/head_ColorDepthLab_SLICE_ONLY.3mf"),
            outer_thickness_mm=0.15,
            layer_height_mm=0.20,
            collapsed_target_groups=((4, 10),),
        )
        events = []

        def inspect(source):
            events.append(("inspect", source))
            return imported

        def confirm(*args, **kwargs):
            events.append(("confirm", args[1]))
            return True

        def save_as(*args, **kwargs):
            events.append(("save", kwargs["initialfile"]))
            return str(result.model_path)

        with (
            patch(
                "spectrum_mapper.gui.filedialog.askopenfilename",
                return_value="C:/jobs/head_part_2.3mf",
            ),
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                side_effect=save_as,
            ) as save_picker,
            patch(
                "spectrum_mapper.gui.messagebox.askokcancel",
                side_effect=confirm,
            ),
            patch(
                "spectrum_mapper.gui.inspect_color_depth_3mf",
                side_effect=inspect,
            ) as inspect_call,
            patch(
                "spectrum_mapper.gui.export_color_depth_from_3mf",
                return_value=result,
            ) as export,
        ):
            app._convert_color_depth_part_3mf()
            self.assertEqual(len(submissions), 1)
            inspected = submissions[0].work()
            submissions[0].done(inspected)
            self.assertEqual(len(submissions), 2)
            converted = submissions[1].work()

        self.assertIs(converted, result)
        inspect_call.assert_called_once_with(Path("C:/jobs/head_part_2.3mf"))
        self.assertEqual([event[0] for event in events], ["inspect", "confirm", "save"])
        confirmation = events[1][1]
        self.assertIn("F1: #080808", confirmation)
        self.assertIn("F4: #B8753D", confirmation)
        self.assertIn("state数: 24", confirmation)
        self.assertIn("混色state→物理ペア", confirmation)
        self.assertIn("F1+F2: S5, S11, S17, S23", confirmation)
        self.assertIn("F1+F3: S6, S12, S18, S24", confirmation)
        self.assertIn("0.15 mm", confirmation)
        self.assertIn("0.20 mm", confirmation)
        self.assertIn("Ratio", confirmation)
        self.assertIn("SLICE ONLY", confirmation)
        self.assertNotEqual(
            save_picker.call_args.kwargs["initialfile"], "head_part_2.3mf"
        )
        self.assertIn(
            "ColorDepthLab_SLICE_ONLY",
            save_picker.call_args.kwargs["initialfile"],
        )
        export.assert_called_once_with(
            Path("C:/jobs/head_part_2.3mf"),
            app._variables_to_settings.return_value,
            result.model_path,
            progress=app._thread_progress,
        )

    def test_per_part_3mf_conversion_requires_opt_in_before_source_picker(self) -> None:
        app = self._bare_app()
        app.obj_path = None
        app.prepared = None
        app._variables_to_settings.return_value = AppSettings(
            color_depth=ColorDepthSettings(experimental_enabled=False)
        )
        with (
            patch("spectrum_mapper.gui.messagebox.showinfo") as info,
            patch("spectrum_mapper.gui.filedialog.askopenfilename") as picker,
        ):
            app._convert_color_depth_part_3mf()
        info.assert_called_once()
        picker.assert_not_called()
        app._submit_main.assert_not_called()

    def test_per_part_3mf_conversion_never_overwrites_source(self) -> None:
        app = self._bare_app()
        app._thread_progress = Mock()
        submissions = []

        def capture(label, work, done, *, on_error=None):
            submissions.append(SimpleNamespace(work=work, done=done))
            return True

        app._submit_main = capture
        imported = SimpleNamespace(
            physical_slot_order=("#000000", "#FFFFFF", "#FF0000", "#804000"),
            palette_state_count=16,
            print_mix_specs=(
                (1, 2),
                (1, 3),
                (1, 4),
                (2, 3),
                (2, 4),
                (3, 4),
            )
            * 2,
            metadata={},
        )
        with (
            patch(
                "spectrum_mapper.gui.filedialog.askopenfilename",
                return_value="C:/jobs/source.3mf",
            ),
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                return_value="C:/jobs/source.3mf",
            ),
            patch("spectrum_mapper.gui.messagebox.askokcancel", return_value=True),
            patch(
                "spectrum_mapper.gui.inspect_color_depth_3mf",
                return_value=imported,
            ),
            patch("spectrum_mapper.gui.messagebox.showerror") as error,
            patch("spectrum_mapper.gui.export_color_depth_from_3mf") as export,
        ):
            app._convert_color_depth_part_3mf()
            submissions[0].done(submissions[0].work())
        self.assertEqual(len(submissions), 1)
        self.assertIn("上書き", error.call_args.args[1])
        export.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
