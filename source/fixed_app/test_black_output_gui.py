from __future__ import annotations

import gc
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import MapperApp, _mix_optimizer_settings_key
from spectrum_mapper.i18n import Translator
from spectrum_mapper.mixer import black_output_ratio_preset, build_palette_rgb
from spectrum_mapper.models import AppSettings, PaletteSettings


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class BlackOutputGuiLogicTests(unittest.TestCase):
    @staticmethod
    def _bare_app(
        palette: PaletteSettings | None = None,
        *,
        active_part_key: str | None = None,
    ) -> MapperApp:
        palette = palette or PaletteSettings(
            palette_state_count=32,
            physical_hex=["#111111", "#F5F5F5", "#E32636", "#7A4A32"],
            enabled_states=[True] * 32,
            mix_ratios_b=[33] * 6,
            secondary_mix_ratios_b=[67] * 6,
        )
        app = MapperApp.__new__(MapperApp)
        app.root = object()
        app.i18n = Translator("ja")
        app.settings = AppSettings(
            palette=palette if active_part_key is None else PaletteSettings(),
            part_palettes=(
                {} if active_part_key is None else {active_part_key: palette}
            ),
        )
        app.active_part_key = active_part_key
        app._loading_palette_variables = False
        app.busy = False
        app.palette_state_count_var = FakeVar(palette.palette_state_count)
        app.physical_vars = [FakeVar(value) for value in palette.physical_hex]
        app.enabled_vars = [FakeVar(value) for value in palette.enabled_states]
        app.mix_ratio_vars = [FakeVar(value) for value in palette.mix_ratios_b]
        app.secondary_mix_ratio_vars = [
            FakeVar(value) for value in palette.secondary_mix_ratios_b
        ]
        app.black_output_enabled_var = FakeVar(
            palette.output_mix_ratios_b is not None
        )
        app.black_output_slot_var = FakeVar(
            f"F{MapperApp._infer_black_output_slot(palette) + 1}"
        )
        app.black_output_summary_var = FakeVar("")
        app.black_output_warning_var = FakeVar("")
        app.status_var = FakeVar("")
        app._refresh_part_tree = Mock()
        app._schedule_preview = Mock()
        return app

    @staticmethod
    def _display_rgb(palette: PaletteSettings) -> np.ndarray:
        values, _ = build_palette_rgb(
            palette.physical_hex,
            palette.mix_hex_overrides,
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
        return np.asarray(values)

    def test_enable_uses_darkest_slot_and_does_not_change_display_palette(self) -> None:
        palette = PaletteSettings(
            palette_state_count=32,
            physical_hex=["#F0F0F0", "#E32636", "#08090A", "#7A4A32"],
            enabled_states=[True] * 32,
        )
        app = self._bare_app(palette)
        before = self._display_rgb(palette)

        app.black_output_enabled_var.set(True)
        app._on_black_output_toggle()

        self.assertEqual(app.black_output_slot_var.get(), "F3")
        self.assertEqual(
            app.settings.palette.output_mix_ratios_b,
            black_output_ratio_preset(
                2,
                palette.mix_ratios_b,
                palette.secondary_mix_ratios_b,
            ),
        )
        np.testing.assert_array_equal(before, self._display_rgb(app.settings.palette))
        app._schedule_preview.assert_not_called()
        self.assertIn("5 / 10 / 14 / 20 / 25", app.black_output_summary_var.get())
        self.assertIn("F3単色", app.black_output_warning_var.get())

    def test_apply_selected_slot_then_disable_restores_legacy_output(self) -> None:
        app = self._bare_app()
        app.black_output_enabled_var.set(True)
        app.black_output_slot_var.set("F4")
        app._apply_black_output_preset()
        self.assertEqual(
            app.settings.palette.output_mix_ratios_b,
            black_output_ratio_preset(
                3,
                app.settings.palette.mix_ratios_b,
                app.settings.palette.secondary_mix_ratios_b,
            ),
        )

        app.black_output_enabled_var.set(False)
        app._on_black_output_toggle()
        self.assertIsNone(app.settings.palette.output_mix_ratios_b)
        self.assertIn("補正OFF", app.black_output_summary_var.get())
        self.assertEqual(app.black_output_warning_var.get(), "")
        app._schedule_preview.assert_not_called()

    def test_active_part_gets_its_own_persisted_output_recipe(self) -> None:
        local = PaletteSettings(
            palette_state_count=32,
            physical_hex=["#EEEEEE", "#D02030", "#704020", "#050505"],
            enabled_states=[True] * 32,
        )
        app = self._bare_app(local, active_part_key="coat")

        app.black_output_enabled_var.set(True)
        app._on_black_output_toggle()

        self.assertIsNone(app.settings.palette.output_mix_ratios_b)
        self.assertEqual(app.black_output_slot_var.get(), "F4")
        self.assertIsNotNone(
            app.settings.part_palettes["coat"].output_mix_ratios_b
        )
        restored = AppSettings.from_dict(app.settings.to_dict())
        self.assertEqual(
            restored.part_palettes["coat"].output_mix_ratios_b,
            app.settings.part_palettes["coat"].output_mix_ratios_b,
        )
        copied = app._copy_palette(app.settings.part_palettes["coat"])
        self.assertEqual(
            copied.output_mix_ratios_b,
            app.settings.part_palettes["coat"].output_mix_ratios_b,
        )
        self.assertIsNot(
            copied.output_mix_ratios_b,
            app.settings.part_palettes["coat"].output_mix_ratios_b,
        )

    def test_busy_toggle_is_reverted_without_changing_settings(self) -> None:
        app = self._bare_app()
        app.busy = True
        app.black_output_enabled_var.set(True)

        with patch("spectrum_mapper.gui.messagebox.showinfo") as info:
            app._on_black_output_toggle()

        self.assertFalse(app.black_output_enabled_var.get())
        self.assertIsNone(app.settings.palette.output_mix_ratios_b)
        info.assert_called_once()
        app._schedule_preview.assert_not_called()

    def test_open_manual_editor_snapshot_updates_without_recolour(self) -> None:
        app = self._bare_app()
        reapply = Mock()
        update_usage = Mock()
        app.paint_editor = SimpleNamespace(
            settings=AppSettings(),
            reapply_palette_settings=reapply,
            _palette_usage_contribution_cache_key=object(),
            _update_palette_usage_summary=update_usage,
        )

        app.black_output_enabled_var.set(True)
        app._on_black_output_toggle()

        self.assertEqual(
            app.paint_editor.settings.palette.output_mix_ratios_b,
            app.settings.palette.output_mix_ratios_b,
        )
        self.assertIsNone(
            app.paint_editor._palette_usage_contribution_cache_key
        )
        update_usage.assert_called_once()
        reapply.assert_not_called()
        app._schedule_preview.assert_not_called()

    def test_loading_saved_preset_recovers_selected_black_slot(self) -> None:
        palette = PaletteSettings(
            physical_hex=["#101010", "#202020", "#303030", "#404040"],
        )
        palette.output_mix_ratios_b = black_output_ratio_preset(
            2, palette.mix_ratios_b, palette.secondary_mix_ratios_b
        )
        app = self._bare_app(palette)

        app._load_black_output_variables(palette)

        self.assertTrue(app.black_output_enabled_var.get())
        self.assertEqual(app.black_output_slot_var.get(), "F3")

    def test_gui_preset_tracks_later_target_ratio_edits(self) -> None:
        palette = PaletteSettings()
        palette.output_mix_ratios_b = black_output_ratio_preset(
            0, palette.mix_ratios_b, palette.secondary_mix_ratios_b
        )
        app = self._bare_app(palette)
        app.mix_ratio_vars[0].set(41)

        edited = app._palette_from_variables()

        expected_primary = list(palette.mix_ratios_b)
        expected_primary[0] = 41
        self.assertEqual(
            edited.output_mix_ratios_b,
            black_output_ratio_preset(
                0, expected_primary, palette.secondary_mix_ratios_b
            ),
        )

    def test_settings_identity_includes_global_and_part_output_recipe(self) -> None:
        global_palette = PaletteSettings()
        local_palette = PaletteSettings()
        settings = AppSettings(
            palette=global_palette,
            part_palettes={"coat": local_palette},
        )
        baseline = _mix_optimizer_settings_key(settings)

        global_palette.output_mix_ratios_b = black_output_ratio_preset(0)
        global_changed = _mix_optimizer_settings_key(settings)
        self.assertNotEqual(global_changed, baseline)

        local_palette.output_mix_ratios_b = black_output_ratio_preset(1)
        self.assertNotEqual(
            _mix_optimizer_settings_key(settings), global_changed
        )

    def test_project_save_uses_v11_and_persists_active_output_recipe(self) -> None:
        app = self._bare_app()
        app.paint_editor = None
        app.manual_joint_record = None
        app.pending_manual_joint_record = None
        app.manual_part_partition = None
        app.pending_manual_part_partition = None
        app.manual_overrides = None
        app.manual_fingerprint = None
        app.pending_manual_payload = None
        app.prepared = None
        app.obj_path = None
        app.reference_path = None
        app._variables_to_settings = Mock(return_value=app.settings)
        app._validated_manual_overrides = Mock(return_value=(True, None))
        app.black_output_enabled_var.set(True)
        app._on_black_output_toggle()

        payload = app._project_payload_for_save(app.settings, None)

        self.assertEqual(payload["schema"], "obj-adjuster.project.v13")
        self.assertEqual(
            payload["settings"]["palette"]["output_mix_ratios_b"],
            app.settings.palette.output_mix_ratios_b,
        )


class BlackOutputLiveLanguageTests(unittest.TestCase):
    def tearDown(self) -> None:
        gc.collect()

    def test_controls_and_dynamic_summary_switch_to_english(self) -> None:
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
                    "実機黒補正",
                    app.black_output_enable_checkbutton.cget("text"),
                )
                app.black_output_enabled_var.set(True)
                app._on_black_output_toggle()
                app.set_language("en", persist=False)
                root.update_idletasks()
                self.assertIn(
                    "Physical black correction",
                    app.black_output_enable_checkbutton.cget("text"),
                )
                self.assertEqual(
                    app.black_output_preset_button.cget("text"),
                    "Reduce",
                )
                self.assertIn(
                    "Target/display black", app.black_output_summary_var.get()
                )
                self.assertIn("stays pure black", app.black_output_warning_var.get())
        finally:
            if app is not None:
                with patch.object(MapperApp, "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
