from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import (
    MapperApp,
    _fresh_settings_for_new_obj,
    _persistent_preferences_from_mapping,
    _persistent_preferences_payload,
    _radial_conversion_mode_display,
    _radial_conversion_mode_from_display,
    _radial_skin_mode_display,
    _radial_skin_mode_from_display,
)
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import (
    AppSettings,
    PaletteSettings,
    RADIAL_CONVERSION_SELECTIVE_HYBRID,
    RADIAL_CONVERSION_UNIFORM_STAGE_A,
    RADIAL_SKIN_MODE_ADAPTIVE,
    RADIAL_SKIN_MODE_UNIFORM,
    RadialSettings,
)
from spectrum_mapper.radial_shell import RadialShellError


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class FakeWidget:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}
        self.states: list[object] = []

    def configure(self, **values: object) -> None:
        self.options.update(values)

    def state(self, values: object) -> None:
        self.states.append(values)


class RadialSettingsTests(unittest.TestCase):
    def test_default_is_omitted_but_custom_value_round_trips(self) -> None:
        self.assertNotIn("radial", AppSettings().to_dict())
        settings = AppSettings(
            radial=RadialSettings(
                experimental_enabled=True,
                outer_skin_thickness_mm=0.23,
                layer_height_mm=0.20,
                minimum_lstar_delta=42.5,
                wall_generator="arachne",
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
                skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
                adaptive_skin_min_thickness_mm=0.11,
                adaptive_skin_max_thickness_mm=0.34,
                adaptive_skin_gamma=1.6,
                adaptive_skin_bands=6,
                require_uniform_black_mix=False,
            )
        )
        encoded = settings.to_dict()
        self.assertTrue(encoded["radial"]["experimental_enabled"])
        self.assertAlmostEqual(
            encoded["radial"]["outer_skin_thickness_mm"], 0.23
        )
        self.assertAlmostEqual(encoded["radial"]["layer_height_mm"], 0.20)
        self.assertAlmostEqual(
            encoded["radial"]["minimum_lstar_delta"], 42.5
        )
        self.assertEqual(encoded["radial"]["wall_generator"], "arachne")
        self.assertEqual(
            encoded["radial"]["conversion_mode"],
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )
        self.assertFalse(encoded["radial"]["require_uniform_black_mix"])
        self.assertEqual(
            encoded["radial"]["skin_thickness_mode"],
            RADIAL_SKIN_MODE_ADAPTIVE,
        )
        restored = AppSettings.from_dict(encoded)
        self.assertTrue(restored.radial.experimental_enabled)
        self.assertAlmostEqual(
            restored.radial.outer_skin_thickness_mm, 0.23
        )
        self.assertAlmostEqual(restored.radial.layer_height_mm, 0.20)
        self.assertAlmostEqual(restored.radial.minimum_lstar_delta, 42.5)
        self.assertEqual(restored.radial.wall_generator, "arachne")
        self.assertEqual(
            restored.radial.conversion_mode,
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )
        self.assertFalse(restored.radial.require_uniform_black_mix)
        self.assertEqual(
            restored.radial.skin_thickness_mode,
            RADIAL_SKIN_MODE_ADAPTIVE,
        )
        self.assertAlmostEqual(
            restored.radial.adaptive_skin_min_thickness_mm, 0.11
        )
        self.assertAlmostEqual(
            restored.radial.adaptive_skin_max_thickness_mm, 0.34
        )
        self.assertAlmostEqual(restored.radial.adaptive_skin_gamma, 1.6)
        self.assertEqual(restored.radial.adaptive_skin_bands, 6)

    def test_stage_a_defaults_are_explicit_and_safe(self) -> None:
        settings = RadialSettings()

        self.assertFalse(settings.experimental_enabled)
        self.assertAlmostEqual(settings.outer_skin_thickness_mm, 0.15)
        self.assertAlmostEqual(settings.layer_height_mm, 0.10)
        self.assertAlmostEqual(settings.minimum_lstar_delta, 35.0)
        self.assertEqual(settings.wall_generator, "classic")
        self.assertEqual(
            settings.conversion_mode,
            RADIAL_CONVERSION_UNIFORM_STAGE_A,
        )
        self.assertTrue(settings.require_uniform_black_mix)
        self.assertEqual(settings.skin_thickness_mode, RADIAL_SKIN_MODE_UNIFORM)
        self.assertAlmostEqual(settings.adaptive_skin_min_thickness_mm, 0.10)
        self.assertAlmostEqual(settings.adaptive_skin_max_thickness_mm, 0.30)
        self.assertAlmostEqual(settings.adaptive_skin_gamma, 1.0)
        self.assertEqual(settings.adaptive_skin_bands, 5)

    def test_invalid_thickness_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RadialSettings(outer_skin_thickness_mm=0.09)

        self.assertAlmostEqual(
            RadialSettings(outer_skin_thickness_mm=0.10).outer_skin_thickness_mm,
            0.10,
        )

    def test_stage_a_accepts_new_pitch_and_legacy_r20_pitch(self) -> None:
        self.assertAlmostEqual(RadialSettings().layer_height_mm, 0.10)
        self.assertAlmostEqual(
            RadialSettings(layer_height_mm=0.20).layer_height_mm,
            0.20,
        )

    def test_legacy_r20_app_settings_load_disabled_with_new_safe_defaults(self) -> None:
        restored = AppSettings.from_dict(
            {
                "radial": {
                    "outer_skin_thickness_mm": 0.22,
                    "layer_height_mm": 0.20,
                    "require_uniform_black_mix": True,
                }
            }
        )

        self.assertFalse(restored.radial.experimental_enabled)
        self.assertAlmostEqual(restored.radial.outer_skin_thickness_mm, 0.22)
        self.assertAlmostEqual(restored.radial.layer_height_mm, 0.20)
        self.assertAlmostEqual(restored.radial.minimum_lstar_delta, 35.0)
        self.assertEqual(restored.radial.wall_generator, "classic")
        self.assertEqual(
            restored.radial.conversion_mode,
            RADIAL_CONVERSION_UNIFORM_STAGE_A,
        )
        self.assertTrue(restored.radial.require_uniform_black_mix)
        self.assertEqual(
            restored.radial.skin_thickness_mode,
            RADIAL_SKIN_MODE_UNIFORM,
        )

    def test_stage_a_rejects_unsupported_layer_height(self) -> None:
        for layer_height in (0.08, 0.12, 0.16):
            with self.subTest(layer_height=layer_height):
                with self.assertRaises(ValueError):
                    RadialSettings(layer_height_mm=layer_height)

    def test_stage_a_rejects_invalid_opt_in_and_uniform_flags(self) -> None:
        for field, value in (
            ("experimental_enabled", 1),
            ("experimental_enabled", "true"),
            ("require_uniform_black_mix", 1),
            ("require_uniform_black_mix", "true"),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    RadialSettings(**{field: value})

    def test_stage_a_rejects_invalid_numeric_values(self) -> None:
        invalid_values = (
            ("outer_skin_thickness_mm", True),
            ("outer_skin_thickness_mm", "0.15"),
            ("outer_skin_thickness_mm", float("nan")),
            ("outer_skin_thickness_mm", float("inf")),
            ("layer_height_mm", True),
            ("layer_height_mm", "0.10"),
            ("layer_height_mm", float("nan")),
            ("minimum_lstar_delta", True),
            ("minimum_lstar_delta", "35"),
            ("minimum_lstar_delta", -0.01),
            ("minimum_lstar_delta", 100.01),
            ("minimum_lstar_delta", float("nan")),
            ("minimum_lstar_delta", float("inf")),
        )
        for field, value in invalid_values:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    RadialSettings(**{field: value})

    def test_stage_a_rejects_unknown_or_nonstrict_wall_generator(self) -> None:
        for value in ("", "Classic", " classic", "adaptive", 1, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    RadialSettings(wall_generator=value)

    def test_conversion_mode_is_explicit_and_strict(self) -> None:
        self.assertEqual(
            RadialSettings(
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID
            ).conversion_mode,
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )
        for value in ("", "stage_b", "Selective_Hybrid", " selective_hybrid", 1, True, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    RadialSettings(conversion_mode=value)

    def test_adaptive_skin_settings_are_strict_and_bounded(self) -> None:
        valid = RadialSettings(
            skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
            adaptive_skin_min_thickness_mm=0.10,
            adaptive_skin_max_thickness_mm=0.60,
            adaptive_skin_gamma=4.0,
            adaptive_skin_bands=4,
        )
        self.assertEqual(valid.skin_thickness_mode, RADIAL_SKIN_MODE_ADAPTIVE)
        invalid = (
            ("skin_thickness_mode", "Adaptive"),
            ("adaptive_skin_min_thickness_mm", True),
            ("adaptive_skin_min_thickness_mm", 0.09),
            ("adaptive_skin_max_thickness_mm", float("nan")),
            ("adaptive_skin_gamma", "1.0"),
            ("adaptive_skin_gamma", 4.01),
            ("adaptive_skin_bands", True),
            ("adaptive_skin_bands", 3),
            ("adaptive_skin_bands", 7),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    RadialSettings(**{field: value})
        with self.assertRaises(ValueError):
            RadialSettings(
                adaptive_skin_min_thickness_mm=0.30,
                adaptive_skin_max_thickness_mm=0.30,
            )

    def test_target_lstar_maps_to_discrete_adaptive_depth(self) -> None:
        settings = RadialSettings(
            skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
            adaptive_skin_min_thickness_mm=0.10,
            adaptive_skin_max_thickness_mm=0.30,
            adaptive_skin_gamma=1.0,
            adaptive_skin_bands=5,
        )
        self.assertAlmostEqual(settings.skin_thickness_for_lstar(0, 0, 100), 0.10)
        self.assertAlmostEqual(settings.skin_thickness_for_lstar(50, 0, 100), 0.20)
        self.assertAlmostEqual(settings.skin_thickness_for_lstar(100, 0, 100), 0.30)
        gamma = RadialSettings(
            skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
            adaptive_skin_min_thickness_mm=0.10,
            adaptive_skin_max_thickness_mm=0.30,
            adaptive_skin_gamma=2.0,
            adaptive_skin_bands=5,
        )
        self.assertAlmostEqual(gamma.skin_thickness_for_lstar(50, 0, 100), 0.15)
        uniform = RadialSettings(outer_skin_thickness_mm=0.23)
        self.assertAlmostEqual(uniform.skin_thickness_for_lstar(50, 0, 100), 0.23)

    def test_legacy_false_uniform_flag_does_not_opt_into_hybrid(self) -> None:
        restored = AppSettings.from_dict(
            {"radial": {"require_uniform_black_mix": False}}
        )

        self.assertFalse(restored.radial.require_uniform_black_mix)
        self.assertEqual(
            restored.radial.conversion_mode,
            RADIAL_CONVERSION_UNIFORM_STAGE_A,
        )

    def test_conversion_mode_labels_switch_without_changing_persisted_id(self) -> None:
        translator = Translator("ja")
        japanese = _radial_conversion_mode_display(
            translator,
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )
        translator.set_language("en")
        self.assertEqual(
            _radial_conversion_mode_from_display(translator, japanese),
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )
        english = _radial_conversion_mode_display(
            translator,
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )
        self.assertIn("Selective hybrid", english)
        self.assertEqual(
            _radial_conversion_mode_from_display(translator, english),
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )

    def test_skin_mode_labels_switch_without_changing_persisted_id(self) -> None:
        translator = Translator("ja")
        japanese = _radial_skin_mode_display(
            translator, RADIAL_SKIN_MODE_ADAPTIVE
        )
        translator.set_language("en")
        self.assertEqual(
            _radial_skin_mode_from_display(translator, japanese),
            RADIAL_SKIN_MODE_ADAPTIVE,
        )
        english = _radial_skin_mode_display(
            translator, RADIAL_SKIN_MODE_ADAPTIVE
        )
        self.assertIn("Adaptive", english)

    def test_hybrid_choice_persists_but_new_model_requires_fresh_opt_in(self) -> None:
        settings = AppSettings(
            radial=RadialSettings(
                experimental_enabled=True,
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
                skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
                adaptive_skin_min_thickness_mm=0.12,
                adaptive_skin_max_thickness_mm=0.36,
                adaptive_skin_gamma=1.4,
                adaptive_skin_bands=6,
                require_uniform_black_mix=False,
            )
        )

        payload = _persistent_preferences_payload(settings)
        restored_preferences = _persistent_preferences_from_mapping(payload)
        fresh = _fresh_settings_for_new_obj(settings)

        self.assertEqual(
            payload["radial"]["conversion_mode"],
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )
        self.assertFalse(fresh.radial.experimental_enabled)
        self.assertEqual(
            restored_preferences.radial.conversion_mode,
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )
        self.assertEqual(
            fresh.radial.conversion_mode,
            RADIAL_CONVERSION_SELECTIVE_HYBRID,
        )
        self.assertEqual(
            fresh.radial.skin_thickness_mode, RADIAL_SKIN_MODE_ADAPTIVE
        )
        self.assertAlmostEqual(
            restored_preferences.radial.adaptive_skin_min_thickness_mm, 0.12
        )
        self.assertEqual(fresh.radial.adaptive_skin_bands, 6)


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
        app.active_part_key = None
        app.prepared_key = ("same",)
        app.status_var = FakeVar("")
        app._geometry_key = None
        app.radial_enabled_var = FakeVar(True)
        app.radial_conversion_mode_var = FakeVar(
            app.i18n.text("radial.mode.uniform_stage_a")
        )
        app.radial_black_slot_var = FakeVar("F1")
        app.radial_skin_thickness_var = FakeVar(0.15)
        app.radial_skin_mode_var = FakeVar(
            app.i18n.text("radial.skin_mode.uniform")
        )
        app.radial_adaptive_min_skin_var = FakeVar(0.10)
        app.radial_adaptive_max_skin_var = FakeVar(0.30)
        app.radial_adaptive_gamma_var = FakeVar(1.0)
        app.radial_adaptive_bands_var = FakeVar(5)
        app.radial_skin_mapping_summary_var = FakeVar(
            "S05 F1 67% + F2 33% / target L*=34.0 → 0.15 mm"
        )
        app.radial_min_lstar_delta_var = FakeVar(35.0)
        app.radial_wall_generator_var = FakeVar("classic")
        app.radial_contrast_summary_var = FakeVar(
            "F1/F2: ΔL*=82.1 (target)"
        )
        app._validated_manual_overrides = Mock(return_value=(True, None))
        app._variables_to_settings = Mock(
            return_value=AppSettings(
                radial=RadialSettings(experimental_enabled=True)
            )
        )
        app._submit_main = Mock(return_value=True)
        return app

    def test_explicit_opt_in_blocks_before_picker(self) -> None:
        app = self._bare_app()
        app._developer_features_enabled_committed = False
        app._variables_to_settings.return_value = AppSettings()
        with (
            patch("spectrum_mapper.gui.messagebox.showinfo") as info,
            patch("spectrum_mapper.gui.filedialog.asksaveasfilename") as picker,
        ):
            app._export_radial_experiment()
        self.assertIn("ラジアル", info.call_args.args[0])
        picker.assert_not_called()
        app._variables_to_settings.assert_called_once_with(show_error=True)
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
                "spectrum_mapper.gui.messagebox.askyesno",
                return_value=True,
            ),
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                return_value="",
            ),
        ):
            app._export_radial_experiment()
        app._submit_main.assert_not_called()

    def test_confirmation_cancel_does_not_open_file_picker(self) -> None:
        app = self._bare_app()
        with (
            patch("spectrum_mapper.gui._geometry_key", return_value=("same",)),
            patch(
                "spectrum_mapper.gui.messagebox.askyesno",
                return_value=False,
            ) as confirm,
            patch("spectrum_mapper.gui.filedialog.asksaveasfilename") as picker,
        ):
            app._export_radial_experiment()
        confirm.assert_called_once()
        picker.assert_not_called()
        app._submit_main.assert_not_called()

    def test_selected_part_changes_hybrid_button_to_explicit_part_target(self) -> None:
        app = self._bare_app()
        app.prepared = SimpleNamespace(
            final=SimpleNamespace(
                part_keys=("others-key", "head-key"),
                part_names=("Others", "Head"),
            )
        )
        app.active_part_key = "head-key"
        app.radial_conversion_mode_var.set(
            app.i18n.text("radial.mode.selective_hybrid")
        )
        app.radial_export_button = FakeWidget()
        app.radial_contrast_summary_var = None

        app._refresh_radial_widgets()

        selected_text = str(app.radial_export_button.options["text"])
        self.assertIn("選択パーツ", selected_text)
        self.assertIn("Head", selected_text)
        self.assertNotIn("モデル全体", selected_text)

        app.active_part_key = None
        app._refresh_radial_widgets()
        whole_text = str(app.radial_export_button.options["text"])
        self.assertIn("モデル全体", whole_text)
        self.assertNotIn("Head", whole_text)

    def test_selected_part_is_frozen_for_confirmation_and_worker(self) -> None:
        app = self._bare_app()
        app.prepared = SimpleNamespace(
            final=SimpleNamespace(
                part_keys=("others-key", "head-key"),
                part_names=("Others", "Head"),
            )
        )
        app.active_part_key = "head-key"
        app._variables_to_settings.return_value = AppSettings(
            radial=RadialSettings(
                experimental_enabled=True,
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
                wall_generator="arachne",
                require_uniform_black_mix=False,
            )
        )
        submitted: dict[str, object] = {}

        def capture(label, work, done, *, on_error=None):
            submitted.update(label=label, work=work, done=done, on_error=on_error)
            return True

        app._submit_main = capture
        with (
            patch("spectrum_mapper.gui._geometry_key", return_value=("same",)),
            patch(
                "spectrum_mapper.gui.messagebox.askyesno",
                return_value=True,
            ) as confirm,
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                return_value="C:/out/head-radial.3mf",
            ),
            patch("spectrum_mapper.gui.export_radial_bundle") as export,
        ):
            app._export_radial_experiment()
            confirmation = str(confirm.call_args.args[1])
            self.assertIn("選択パーツ", confirmation)
            self.assertIn("Head", confirmation)
            self.assertIn("arachne", confirmation)

            app.active_part_key = "others-key"
            submitted["work"]()

        export.assert_called_once()
        self.assertEqual(export.call_args.kwargs["part_key"], "head-key")

    def test_palette_switch_syncs_radial_black_only_for_unique_darkest_slot(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app._loading_palette_variables = False
        app.physical_vars = [FakeVar() for _ in range(4)]
        app.enabled_vars = [FakeVar() for _ in range(32)]
        app.extended_palette_var = FakeVar()
        app.palette_state_count_var = FakeVar()
        app.mix_ratio_vars = [FakeVar() for _ in range(6)]
        app.secondary_mix_ratio_vars = [FakeVar() for _ in range(6)]
        app.black_output_enabled_var = FakeVar()
        app.black_output_slot_var = FakeVar()
        app.radial_black_slot_var = FakeVar("F4")
        app._refresh_black_free_gradient_widgets = Mock()
        app._refresh_black_output_widgets = Mock()
        app._refresh_surface_shell_widgets = Mock()
        app._refresh_radial_widgets = Mock()
        app._refresh_material_mode_buttons = Mock()
        app._refresh_color_mode_widgets = Mock()

        head = PaletteSettings(
            physical_hex=["#BA8960", "#F5F5F5", "#121212", "#EFD00B"]
        )
        app._load_palette_variables(head)
        self.assertEqual(app.radial_black_slot_var.get(), "F3")

        tied = PaletteSettings(
            physical_hex=["#BA8960", "#F5F5F5", "#121212", "#121212"]
        )
        app.radial_black_slot_var.set("F2")
        app._load_palette_variables(tied)
        self.assertEqual(app.radial_black_slot_var.get(), "F2")

    def test_selective_hybrid_confirmation_states_preserved_regions(self) -> None:
        app = self._bare_app()
        app._variables_to_settings.return_value = AppSettings(
            radial=RadialSettings(
                experimental_enabled=True,
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
                require_uniform_black_mix=False,
            )
        )
        with (
            patch("spectrum_mapper.gui._geometry_key", return_value=("same",)),
            patch(
                "spectrum_mapper.gui.messagebox.askyesno",
                return_value=False,
            ) as confirm,
            patch("spectrum_mapper.gui.filedialog.asksaveasfilename") as picker,
        ):
            app._export_radial_experiment()

        title, message = confirm.call_args.args[:2]
        self.assertIn("選択式ハイブリッド", title)
        self.assertIn("純黒面", message)
        self.assertIn("通常方式を維持", message)
        self.assertIn("SLICE ONLY", message)
        picker.assert_not_called()
        app._submit_main.assert_not_called()

    def test_adaptive_hybrid_confirmation_shows_depth_mapping(self) -> None:
        app = self._bare_app()
        app._variables_to_settings.return_value = AppSettings(
            radial=RadialSettings(
                experimental_enabled=True,
                conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
                skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
                adaptive_skin_min_thickness_mm=0.11,
                adaptive_skin_max_thickness_mm=0.31,
                adaptive_skin_gamma=1.5,
                adaptive_skin_bands=5,
                require_uniform_black_mix=False,
            )
        )
        with (
            patch("spectrum_mapper.gui._geometry_key", return_value=("same",)),
            patch(
                "spectrum_mapper.gui.messagebox.askyesno", return_value=False
            ) as confirm,
            patch("spectrum_mapper.gui.filedialog.asksaveasfilename") as picker,
        ):
            app._export_radial_experiment()

        message = confirm.call_args.args[1]
        self.assertIn("target L*", message)
        self.assertIn("0.11", message)
        self.assertIn("0.31", message)
        self.assertIn("5段階", message)
        self.assertIn("SLICE ONLY", message)
        picker.assert_not_called()

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
                "spectrum_mapper.gui.messagebox.askyesno",
                return_value=True,
            ),
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
                        "spectrum_mapper.gui.messagebox.askyesno",
                        return_value=True,
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
