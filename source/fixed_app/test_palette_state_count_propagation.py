from __future__ import annotations

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import AppSettings, PaletteSettings
from spectrum_mapper.gui import MapperApp
from spectrum_mapper.i18n import Translator
from spectrum_mapper.paint_gui import PaintEditorWindow
from spectrum_mapper.palette_state_count import (
    apply_palette_state_count_change,
    palette_with_state_count,
)


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


def make_palette(
    state_count: int,
    *,
    physical: list[str],
    enabled: list[bool] | None = None,
    ratio: int = 33,
) -> PaletteSettings:
    return PaletteSettings(
        palette_state_count=state_count,
        physical_hex=physical,
        enabled_states=(
            [True] * state_count if enabled is None else list(enabled)
        ),
        mix_ratios_b=[ratio + index for index in range(6)],
        secondary_mix_ratios_b=[100 - ratio - index for index in range(6)],
        output_mix_ratios_b=[20 + index for index in range(28)],
        black_free_gradient_enabled=True,
        black_free_black_slot=0,
        black_free_red_slot=2,
        black_free_brown_slot=3,
    )


class PaletteStateCountPropagationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.common = make_palette(
            16,
            physical=["#111111", "#F1F1F1", "#C03030", "#7A4A32"],
            enabled=[index % 3 != 1 for index in range(16)],
        )
        self.coat = make_palette(
            32,
            physical=["#101820", "#E8EEF8", "#315D89", "#42A5C6"],
            enabled=[index % 4 != 0 for index in range(32)],
            ratio=21,
        )
        self.boots = make_palette(
            24,
            physical=["#241B18", "#F5EADB", "#9C6B42", "#66504A"],
            enabled=[index % 5 != 2 for index in range(24)],
            ratio=27,
        )

    def test_common_change_propagates_to_every_existing_part_palette(self) -> None:
        settings = AppSettings(
            palette=self.common,
            part_palettes={"coat": self.coat, "boots": self.boots},
        )
        before_coat = settings.part_palettes["coat"]
        before_boots = settings.part_palettes["boots"]
        coat_identity = (
            list(before_coat.physical_hex),
            list(before_coat.mix_ratios_b),
            list(before_coat.secondary_mix_ratios_b),
            list(before_coat.output_mix_ratios_b or ()),
            before_coat.black_free_gradient_enabled,
            before_coat.black_free_black_slot,
            before_coat.black_free_red_slot,
            before_coat.black_free_brown_slot,
        )

        change = apply_palette_state_count_change(
            settings,
            24,
            target_part_key=None,
        )

        self.assertEqual(change.updated_part_palettes, 2)
        self.assertEqual(settings.palette.palette_state_count, 24)
        self.assertEqual(settings.part_palettes["coat"].palette_state_count, 24)
        self.assertEqual(settings.part_palettes["boots"].palette_state_count, 24)
        self.assertEqual(
            settings.part_palettes["coat"].enabled_states[24:],
            [False] * 8,
        )
        self.assertEqual(
            (
                settings.part_palettes["coat"].physical_hex,
                settings.part_palettes["coat"].mix_ratios_b,
                settings.part_palettes["coat"].secondary_mix_ratios_b,
                settings.part_palettes["coat"].output_mix_ratios_b,
                settings.part_palettes["coat"].black_free_gradient_enabled,
                settings.part_palettes["coat"].black_free_black_slot,
                settings.part_palettes["coat"].black_free_red_slot,
                settings.part_palettes["coat"].black_free_brown_slot,
            ),
            coat_identity,
        )
        self.assertIsNot(settings.part_palettes["coat"], before_coat)
        self.assertIsNot(settings.part_palettes["boots"], before_boots)

    def test_individual_change_is_isolated_and_can_create_one_local_palette(self) -> None:
        settings = AppSettings(
            palette=self.common,
            part_palettes={"coat": self.coat, "boots": self.boots},
        )
        before_common = AppSettings(palette=settings.palette).to_dict()["palette"]
        before_boots = settings.part_palettes["boots"]

        change = apply_palette_state_count_change(
            settings,
            16,
            target_part_key="coat",
        )

        self.assertEqual(change.target_part_key, "coat")
        self.assertEqual(settings.part_palettes["coat"].palette_state_count, 16)
        self.assertEqual(
            AppSettings(palette=settings.palette).to_dict()["palette"],
            before_common,
        )
        self.assertIs(settings.part_palettes["boots"], before_boots)

        inherited = AppSettings(palette=self.common)
        apply_palette_state_count_change(
            inherited,
            32,
            target_part_key="new-part",
        )
        self.assertEqual(inherited.palette.palette_state_count, 16)
        self.assertEqual(
            inherited.part_palettes["new-part"].palette_state_count,
            32,
        )
        self.assertIsNot(inherited.part_palettes["new-part"], inherited.palette)

    def test_project_load_keeps_different_saved_counts_until_user_changes_them(self) -> None:
        raw = AppSettings(
            palette=self.common,
            part_palettes={"coat": self.coat, "boots": self.boots},
        ).to_dict()

        loaded = AppSettings.from_dict(raw)

        self.assertEqual(loaded.palette.palette_state_count, 16)
        self.assertEqual(loaded.part_palettes["coat"].palette_state_count, 32)
        self.assertEqual(loaded.part_palettes["boots"].palette_state_count, 24)

    def test_16_to_32_round_trip_preserves_flags_in_shared_range(self) -> None:
        enabled = [index not in (1, 6, 11, 14) for index in range(32)]
        palette = make_palette(
            32,
            physical=["#111111", "#EEEEEE", "#CC3333", "#7A4A32"],
            enabled=enabled,
        )
        stable_first_sixteen = list(palette.enabled_states[:16])

        reduced = palette_with_state_count(palette, 16)
        restored = palette_with_state_count(reduced, 32)

        self.assertEqual(reduced.enabled_states[:16], stable_first_sixteen)
        self.assertEqual(reduced.enabled_states[16:], [False] * 16)
        self.assertEqual(restored.enabled_states[:16], stable_first_sixteen)
        self.assertEqual(restored.enabled_states[16:], [True] * 16)
        self.assertEqual(restored.physical_hex, palette.physical_hex)
        self.assertEqual(restored.mix_ratios_b, palette.mix_ratios_b)
        self.assertEqual(
            restored.secondary_mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
        self.assertEqual(restored.output_mix_ratios_b, palette.output_mix_ratios_b)
        self.assertTrue(restored.black_free_gradient_enabled)


class PaletteStateCountGuiWiringTests(unittest.TestCase):
    @staticmethod
    def _commit_fake_active_palette(app: MapperApp) -> None:
        target = (
            app.settings.palette
            if app.active_part_key is None
            else app.settings.part_palettes.get(
                app.active_part_key,
                app.settings.palette,
            )
        )
        resized = palette_with_state_count(
            target,
            int(app.palette_state_count_var.get()),
        )
        resized.enabled_states = [
            bool(variable.get()) for variable in app.enabled_vars
        ]
        if app.active_part_key is None:
            app.settings.palette = resized
        else:
            app.settings.part_palettes[app.active_part_key] = resized

    def test_main_common_combobox_event_propagates_and_syncs_manual_editor(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app.settings = AppSettings(
            palette=PaletteSettings(),
            part_palettes={
                "coat": PaletteSettings(),
                "boots": PaletteSettings(palette_state_count=32),
            },
        )
        app.active_part_key = None
        app.palette_state_count_var = FakeVar(24)
        app.enabled_vars = [FakeVar(value) for value in app.settings.palette.enabled_states]
        app._loading_palette_variables = False
        app._on_palette_changed = lambda: self._commit_fake_active_palette(app)
        app.part_recommendations = {"coat": object()}
        app.i18n = Translator("ja")
        app.status_var = FakeVar("")
        app._refresh_part_tree = Mock()
        app._schedule_preview = Mock()
        reapply = Mock()
        app.paint_editor = SimpleNamespace(reapply_shading_settings=reapply)

        app._on_palette_state_count_changed()

        self.assertEqual(app.settings.palette.palette_state_count, 24)
        self.assertEqual(app.settings.part_palettes["coat"].palette_state_count, 24)
        self.assertEqual(app.settings.part_palettes["boots"].palette_state_count, 24)
        self.assertEqual(app.part_recommendations, {})
        reapply.assert_called_once()
        self.assertIn("2件", app.status_var.get())

    def test_main_individual_combobox_event_does_not_touch_other_palettes(self) -> None:
        common = PaletteSettings()
        coat = PaletteSettings(palette_state_count=32)
        boots = PaletteSettings(palette_state_count=24)
        app = MapperApp.__new__(MapperApp)
        app.settings = AppSettings(
            palette=common,
            part_palettes={"coat": coat, "boots": boots},
        )
        app.active_part_key = "coat"
        app.palette_state_count_var = FakeVar(16)
        app.enabled_vars = [FakeVar(value) for value in coat.enabled_states]
        app._loading_palette_variables = False
        app._on_palette_changed = lambda: self._commit_fake_active_palette(app)
        app.part_recommendations = {}
        app.i18n = Translator("ja")
        app.status_var = FakeVar("")
        app._refresh_part_tree = Mock()
        app._schedule_preview = Mock()
        reapply = Mock()
        app.paint_editor = SimpleNamespace(reapply_palette_settings=reapply)

        app._on_palette_state_count_changed()

        self.assertEqual(app.settings.palette.palette_state_count, 16)
        self.assertEqual(app.settings.part_palettes["coat"].palette_state_count, 16)
        self.assertEqual(app.settings.part_palettes["boots"].palette_state_count, 24)
        self.assertIs(app.settings.part_palettes["boots"], boots)
        reapply.assert_called_once()

    def test_manual_editor_common_and_individual_paths_match_main_semantics(self) -> None:
        editor = PaintEditorWindow.__new__(PaintEditorWindow)
        editor.settings = AppSettings(
            palette=PaletteSettings(),
            part_palettes={"saved-other": PaletteSettings(palette_state_count=32)},
        )
        editor.part_keys = ("whole",)
        editor.active_part_id = 0
        editor.manual_palette_state_count_var = FakeVar(24)
        editor.paint_state_var = FakeVar(0)
        editor._refresh_palette_buttons = Mock()
        editor._queue_shading_reapply = Mock()
        editor.on_palette_settings_changed = Mock()
        editor.i18n = Translator("ja")

        editor._on_manual_palette_state_count_changed()

        self.assertEqual(editor.settings.palette.palette_state_count, 24)
        self.assertEqual(
            editor.settings.part_palettes["saved-other"].palette_state_count,
            24,
        )
        editor.on_palette_settings_changed.assert_called_once()
        self.assertIsNone(editor.on_palette_settings_changed.call_args.args[0])
        self.assertIn(
            "1件",
            editor._queue_shading_reapply.call_args.args[0],
        )

        coat = PaletteSettings(palette_state_count=32)
        boots = PaletteSettings(palette_state_count=24)
        editor.settings = AppSettings(
            palette=PaletteSettings(),
            part_palettes={"coat": coat, "boots": boots},
        )
        editor.part_keys = ("coat", "boots")
        editor.active_part_id = 0
        editor.manual_palette_state_count_var.set(16)
        editor.on_palette_settings_changed.reset_mock()

        editor._on_manual_palette_state_count_changed()

        self.assertEqual(editor.settings.part_palettes["coat"].palette_state_count, 16)
        self.assertEqual(editor.settings.part_palettes["boots"].palette_state_count, 24)
        self.assertIs(editor.settings.part_palettes["boots"], boots)
        self.assertEqual(
            editor.on_palette_settings_changed.call_args.args[0],
            "coat",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
