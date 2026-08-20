from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import MapperApp
from spectrum_mapper.i18n import Translator
from spectrum_mapper.mixer import black_output_ratio_preset, build_palette_rgb
from spectrum_mapper.models import AppSettings, MeshLevel, PaletteSettings
from spectrum_mapper.paint_gui import PaintEditorWindow, _copy_palette_settings


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class FakeCheckbutton:
    def __init__(self) -> None:
        self.states: list[str] = []

    def state(self, values) -> None:
        self.states = list(values)


class SurfaceShellGuiFailClosedTests(unittest.TestCase):
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
        app.surface_shell_enabled_var = FakeVar(False)
        app.surface_shell_summary_var = FakeVar("")
        app.surface_shell_enable_checkbutton = FakeCheckbutton()
        app.status_var = FakeVar("")
        app._refresh_part_tree = Mock()
        app._schedule_preview = Mock()
        app.paint_editor = None
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

    def test_toggle_is_always_rejected_and_preserves_black_ratio_and_display(self) -> None:
        output = black_output_ratio_preset(0)
        palette = PaletteSettings(output_mix_ratios_b=list(output))
        app = self._bare_app(palette)
        before = self._display_rgb(palette)

        app.surface_shell_enabled_var.set(True)
        app._on_surface_shell_toggle()

        self.assertFalse(app.surface_shell_enabled_var.get())
        self.assertFalse(app.settings.palette.surface_shell_enabled)
        self.assertEqual(app.settings.palette.output_mix_ratios_b, output)
        np.testing.assert_array_equal(self._display_rgb(app.settings.palette), before)
        self.assertEqual(app.surface_shell_enable_checkbutton.states, ["disabled"])
        self.assertIn("アクセス違反対策", app.surface_shell_summary_var.get())
        self.assertIn("現在無効", app.status_var.get())

    def test_custom_output_ratios_are_not_overwritten(self) -> None:
        custom = [50] * 28
        palette = PaletteSettings(output_mix_ratios_b=list(custom))
        app = self._bare_app(palette)
        app.surface_shell_enabled_var.set(True)

        app._on_surface_shell_toggle()

        self.assertEqual(app.settings.palette.output_mix_ratios_b, custom)
        self.assertFalse(app.settings.palette.surface_shell_enabled)

    def test_saved_mutated_mode_is_migrated_off_on_load(self) -> None:
        palette = PaletteSettings(
            output_mix_ratios_b=black_output_ratio_preset(0)
        )
        palette.surface_shell_enabled = True
        app = self._bare_app(palette)

        app._load_surface_shell_variables(palette)

        self.assertFalse(palette.surface_shell_enabled)
        self.assertFalse(app.surface_shell_enabled_var.get())
        self.assertIn("Ratio", app.surface_shell_summary_var.get())

    def test_active_part_inheritance_and_ratios_remain_unchanged(self) -> None:
        local = PaletteSettings()
        app = self._bare_app(local, active_part_key="coat")
        global_output = black_output_ratio_preset(0)
        app.settings.palette.output_mix_ratios_b = list(global_output)
        app.surface_shell_enabled_var.set(True)

        app._on_surface_shell_toggle()

        self.assertEqual(app.settings.palette.output_mix_ratios_b, global_output)
        self.assertIsNone(app.settings.part_palettes["coat"].output_mix_ratios_b)
        self.assertFalse(app.settings.part_palettes["coat"].surface_shell_enabled)

    def test_refresh_is_safe_for_minimal_fixture_without_surface_variable(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app.i18n = Translator("ja")
        app.status_var = FakeVar("")

        app._on_surface_shell_toggle()

        self.assertIn("現在無効", app.status_var.get())

    def test_refresh_forces_disabled_checkbox_and_summary(self) -> None:
        app = self._bare_app()
        app.surface_shell_enabled_var.set(True)

        app._refresh_surface_shell_widgets()

        self.assertFalse(app.surface_shell_enabled_var.get())
        self.assertEqual(app.surface_shell_enable_checkbutton.states, ["disabled"])
        self.assertIn("アクセス違反対策", app.surface_shell_summary_var.get())

    def test_palette_copy_cannot_reactivate_old_mode(self) -> None:
        palette = PaletteSettings(
            output_mix_ratios_b=black_output_ratio_preset(0)
        )
        palette.surface_shell_enabled = True

        gui_copy = MapperApp._copy_palette(palette)
        editor_copy = _copy_palette_settings(palette)

        self.assertFalse(gui_copy.surface_shell_enabled)
        self.assertFalse(editor_copy.surface_shell_enabled)
        self.assertEqual(gui_copy.output_mix_ratios_b, palette.output_mix_ratios_b)
        self.assertEqual(editor_copy.output_mix_ratios_b, palette.output_mix_ratios_b)

    def test_manual_editor_usage_summary_uses_ratio_not_shell_assumption(self) -> None:
        level = MeshLevel(
            vertices_unit=np.asarray(
                [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
            ),
            faces=np.asarray([[0, 1, 2]], dtype=np.int32),
            vertex_colors=np.full((3, 3), 0.5),
            areas_unit=np.asarray([0.5]),
            neighbors=None,
            face_part_ids=np.asarray([0], dtype=np.int16),
            part_names=("part",),
            part_keys=("part",),
        )
        palette = PaletteSettings(
            physical_hex=["#111111", "#FFFFFF", "#E32636", "#7A4A32"],
            output_mix_ratios_b=black_output_ratio_preset(0),
        )
        summary = FakeVar("")
        dummy = SimpleNamespace(
            palette_usage_summary_var=summary,
            _palette_usage_focus_enabled=True,
            effective_indices=np.asarray([5], dtype=np.int8),
            level=level,
            _palette_usage_focus_state=5,
            prepared=SimpleNamespace(),
            active_part_id=0,
            settings=SimpleNamespace(geometry=SimpleNamespace(height_mm=10.0)),
            state_names=tuple(f"state-{index + 1}" for index in range(32)),
            _active_palette=lambda: palette,
            _palette_usage_contribution_cache_key=None,
            _palette_usage_contribution_cache=None,
            i18n=Translator("ja"),
            part_names=("part",),
        )

        PaintEditorWindow._update_palette_usage_summary(dummy)

        self.assertIn("3MF出力recipe上の公称比率", summary.get())
        self.assertNotIn("2本同幅前提", summary.get())
        self.assertIn("F1 20.0% / F2 0.0% / F3 80.0%", summary.get())

    def test_disabled_wording_is_available_in_both_languages(self) -> None:
        ja = Translator("ja")
        en = Translator("en")
        self.assertEqual(
            ja.text("palette.surface_shell_unavailable_label"),
            "現在無効（Snapmaker Orcaアクセス違反対策）",
        )
        self.assertIn(
            "access-violation safeguard",
            en.text("palette.surface_shell_unavailable_label"),
        )
        self.assertIn("Ratio", en.text("palette.surface_shell_unavailable_summary"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
