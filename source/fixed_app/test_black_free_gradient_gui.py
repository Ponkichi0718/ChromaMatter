from __future__ import annotations

import gc
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np


from spectrum_mapper.gui import (
    MapperApp,
    _enforce_black_free_gradient_developer_gate,
    _fresh_settings_for_new_obj,
    _mix_optimizer_settings_key,
    _project_settings_from_mapping,
)
from spectrum_mapper.i18n import Translator
from spectrum_mapper.mixer import black_containing_mixed_states
from spectrum_mapper.models import AppSettings, ColorDepthSettings, PaletteSettings


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class BlackFreeGradientGuiLogicTests(unittest.TestCase):
    @staticmethod
    def _palette(*, enabled: bool = False) -> PaletteSettings:
        return PaletteSettings(
            palette_state_count=32,
            physical_hex=["#111111", "#F5F5F5", "#E32636", "#7A4A32"],
            enabled_states=[True] * 32,
            mix_ratios_b=[33] * 6,
            secondary_mix_ratios_b=[67] * 6,
            black_free_gradient_enabled=enabled,
            black_free_black_slot=0,
            black_free_red_slot=2,
            black_free_brown_slot=3,
        )

    @classmethod
    def _bare_app(
        cls,
        palette: PaletteSettings | None = None,
        *,
        active_part_key: str | None = None,
        inherited_part: bool = False,
    ) -> MapperApp:
        palette = palette or cls._palette()
        app = MapperApp.__new__(MapperApp)
        app.root = object()
        app.i18n = Translator("ja")
        if active_part_key is None:
            app.settings = AppSettings(palette=palette)
        elif inherited_part:
            app.settings = AppSettings(palette=palette)
        else:
            app.settings = AppSettings(
                palette=PaletteSettings(),
                part_palettes={active_part_key: palette},
            )
        app.active_part_key = active_part_key
        # Black-Free Gradient is exercised below as an explicitly revealed
        # developer feature.  Separate tests cover the normal-mode gate.
        app._developer_features_enabled_committed = True
        app._loading_palette_variables = False
        app.busy = False
        app.palette_state_count_var = FakeVar(palette.palette_state_count)
        app.physical_vars = [FakeVar(value) for value in palette.physical_hex]
        app.enabled_vars = [FakeVar(value) for value in palette.enabled_states]
        app.extended_palette_var = FakeVar(True)
        app.mix_ratio_vars = [FakeVar(value) for value in palette.mix_ratios_b]
        app.secondary_mix_ratio_vars = [
            FakeVar(value) for value in palette.secondary_mix_ratios_b
        ]
        app.black_free_gradient_enabled_var = FakeVar(
            palette.black_free_gradient_enabled
        )
        app.black_free_black_slot_var = FakeVar(
            f"F{palette.black_free_black_slot + 1}"
        )
        app.black_free_red_slot_var = FakeVar(
            f"F{palette.black_free_red_slot + 1}"
        )
        app.black_free_brown_slot_var = FakeVar(
            f"F{palette.black_free_brown_slot + 1}"
        )
        app.black_free_gradient_summary_var = FakeVar("")
        app.black_output_enabled_var = FakeVar(False)
        app.black_output_slot_var = FakeVar("F1")
        app.black_output_summary_var = FakeVar("")
        app.black_output_warning_var = FakeVar("")
        app.status_var = FakeVar("")
        app.part_recommendations = {}
        app.paint_editor = None
        app.prepared = None
        app.manual_overrides = None
        app._refresh_palette_widgets = Mock()
        app._refresh_part_tree = Mock()
        app._schedule_preview = Mock()
        app._note_mix_input_change = Mock()
        return app

    def test_toggle_commits_and_reapplies_manual_editor_before_preview(self) -> None:
        app = self._bare_app()
        reapply = Mock()
        app.paint_editor = SimpleNamespace(reapply_palette_settings=reapply)
        app.black_free_gradient_enabled_var.set(True)

        app._on_black_free_gradient_toggle()

        palette = app.settings.palette
        self.assertTrue(palette.black_free_gradient_enabled)
        self.assertEqual(
            (
                palette.black_free_black_slot,
                palette.black_free_red_slot,
                palette.black_free_brown_slot,
            ),
            (0, 2, 3),
        )
        app._note_mix_input_change.assert_called_once_with()
        app._refresh_part_tree.assert_called_once_with()
        reapply.assert_called_once()
        self.assertIsNone(reapply.call_args.args[0])
        self.assertIs(reapply.call_args.args[1], palette)
        app._schedule_preview.assert_called_once_with(immediate=True)
        self.assertIn("手塗り黒混色 0面", app.black_free_gradient_summary_var.get())
        self.assertIn("赤 F3〜茶 F4", app.status_var.get())

    def test_inherited_part_toggle_creates_local_palette_only(self) -> None:
        common = self._palette(enabled=False)
        app = self._bare_app(
            common,
            active_part_key="coat",
            inherited_part=True,
        )
        app.black_free_gradient_enabled_var.set(True)

        app._on_black_free_gradient_toggle()

        self.assertFalse(app.settings.palette.black_free_gradient_enabled)
        self.assertTrue(
            app.settings.part_palettes["coat"].black_free_gradient_enabled
        )

    def test_duplicate_roles_revert_without_committing_or_previewing(self) -> None:
        app = self._bare_app()
        app.black_free_gradient_enabled_var.set(True)
        app.black_free_red_slot_var.set("F1")

        with patch("spectrum_mapper.gui.messagebox.showerror") as error:
            app._on_black_free_gradient_toggle()

        self.assertFalse(app.settings.palette.black_free_gradient_enabled)
        self.assertFalse(app.black_free_gradient_enabled_var.get())
        self.assertEqual(app.black_free_red_slot_var.get(), "F3")
        error.assert_called_once()
        self.assertIn("異なるF1〜F4", error.call_args.args[1])
        app._note_mix_input_change.assert_not_called()
        app._schedule_preview.assert_not_called()

    def test_busy_toggle_reverts_without_changing_settings(self) -> None:
        app = self._bare_app()
        app.busy = True
        app.black_free_gradient_enabled_var.set(True)

        with patch("spectrum_mapper.gui.messagebox.showinfo") as info:
            app._on_black_free_gradient_toggle()

        self.assertFalse(app.settings.palette.black_free_gradient_enabled)
        self.assertFalse(app.black_free_gradient_enabled_var.get())
        info.assert_called_once()
        app._note_mix_input_change.assert_not_called()
        app._schedule_preview.assert_not_called()

    def test_zero_enabled_replacement_candidates_fail_closed(self) -> None:
        app = self._bare_app()
        app.black_free_gradient_enabled_var.set(True)
        for variable in app.enabled_vars:
            variable.set(False)

        with patch("spectrum_mapper.gui.messagebox.showerror") as error:
            app._on_black_free_gradient_toggle()

        self.assertFalse(app.settings.palette.black_free_gradient_enabled)
        self.assertFalse(app.black_free_gradient_enabled_var.get())
        self.assertIn("黒なし候補がありません", error.call_args.args[1])
        app._note_mix_input_change.assert_not_called()
        app._schedule_preview.assert_not_called()

    def test_disabling_last_candidate_while_on_reverts_palette_controls(self) -> None:
        app = self._bare_app(self._palette(enabled=True))
        for variable in app.enabled_vars:
            variable.set(False)

        with patch("spectrum_mapper.gui.messagebox.showerror") as error:
            app._on_palette_changed()

        self.assertTrue(app.settings.palette.black_free_gradient_enabled)
        self.assertTrue(all(variable.get() for variable in app.enabled_vars))
        self.assertIn("黒なし候補がありません", error.call_args.args[1])
        app._note_mix_input_change.assert_not_called()
        app._schedule_preview.assert_not_called()

    def test_copy_load_variables_recommendation_and_snapshot_keep_policy(self) -> None:
        palette = self._palette(enabled=True)
        app = self._bare_app(palette)

        copied = app._copy_palette(palette)
        self.assertTrue(copied.black_free_gradient_enabled)
        self.assertEqual(copied.black_free_black_slot, 0)
        self.assertEqual(copied.black_free_red_slot, 2)
        self.assertEqual(copied.black_free_brown_slot, 3)

        app._load_palette_variables(palette)
        from_variables = app._palette_from_variables()
        self.assertTrue(from_variables.black_free_gradient_enabled)
        self.assertEqual(from_variables.black_free_red_slot, 2)

        recommendation = SimpleNamespace(
            physical_hex=("#111111", "#F5F5F5", "#E32636", "#7A4A32"),
            primary_ratio_b_percent=35,
            secondary_ratio_b_percent=65,
        )
        recommended = app._palette_from_recommendation(
            recommendation,
            32,
            black_free_gradient_enabled=True,
            black_free_black_slot=0,
            black_free_red_slot=2,
            black_free_brown_slot=3,
        )
        self.assertTrue(recommended.black_free_gradient_enabled)

        baseline = _mix_optimizer_settings_key(AppSettings())
        changed = _mix_optimizer_settings_key(AppSettings(palette=palette))
        self.assertNotEqual(baseline, changed)
        local_settings = AppSettings(part_palettes={"coat": palette})
        self.assertNotEqual(
            _mix_optimizer_settings_key(local_settings),
            _mix_optimizer_settings_key(AppSettings(part_palettes={"coat": PaletteSettings()})),
        )

    def test_manual_warning_counts_mixed_states_but_not_pure_black(self) -> None:
        palette = self._palette(enabled=True)
        app = self._bare_app(palette)
        mixed = black_containing_mixed_states(32, 0)
        app.prepared = SimpleNamespace(
            final=SimpleNamespace(
                faces=np.zeros((4, 3), dtype=np.int32),
                face_part_ids=np.zeros(4, dtype=np.int8),
                part_keys=("body",),
            )
        )
        # Pure F1 state 0 is deliberately excluded from the warning.
        manual = np.asarray([mixed[0], 0, -1, mixed[-1]], dtype=np.int8)
        app.manual_overrides = manual
        app._refresh_black_free_gradient_widgets(palette)
        self.assertIn("手塗り黒混色 2面", app.black_free_gradient_summary_var.get())

        self.assertEqual(
            app._black_free_manual_override_counts(
                app.settings,
                manual,
                force_common_palette=False,
            ),
            (2, 1),
        )
        with patch(
            "spectrum_mapper.gui.messagebox.askyesno", return_value=False
        ) as ask:
            self.assertFalse(
                app._confirm_black_free_manual_overrides(
                    app.settings,
                    manual,
                    force_common_palette=False,
                )
            )
        self.assertIn("2 面", ask.call_args.args[1])
        self.assertIn("純黒のF単色", ask.call_args.args[1])
        self.assertIn("3MF出力を中止", app.status_var.get())

    def test_forced_common_warning_also_covers_individual_part_exports(self) -> None:
        common = self._palette(enabled=False)
        local = self._palette(enabled=True)
        app = self._bare_app(common)
        app.settings.part_palettes = {"coat": local}
        mixed = black_containing_mixed_states(32, 0)
        app.prepared = SimpleNamespace(
            final=SimpleNamespace(
                faces=np.zeros((2, 3), dtype=np.int32),
                face_part_ids=np.asarray([0, 1], dtype=np.int8),
                part_keys=("body", "coat"),
            )
        )
        manual = np.asarray([-1, mixed[0]], dtype=np.int8)

        # The forced-common main job has the mode disabled, but the additional
        # per-part 3MF retains coat's enabled palette and therefore still warns.
        self.assertEqual(
            app._black_free_manual_override_counts(
                app.settings,
                manual,
                force_common_palette=True,
            ),
            (1, 1),
        )
        app.settings.geometry.export_individual_parts = False
        self.assertEqual(
            app._black_free_manual_override_counts(
                app.settings,
                manual,
                force_common_palette=True,
            ),
            (0, 0),
        )

    def test_v10_migrates_off_and_v11_round_trips_on(self) -> None:
        injected = AppSettings(
            palette=self._palette(enabled=True),
            part_palettes={"coat": self._palette(enabled=True)},
            color_depth=ColorDepthSettings(experimental_enabled=True),
        )
        raw_v10 = {
            "schema": "obj-adjuster.project.v10",
            "settings": injected.to_dict(),
        }
        migrated = _project_settings_from_mapping(raw_v10)
        self.assertFalse(migrated.palette.black_free_gradient_enabled)
        self.assertFalse(
            migrated.part_palettes["coat"].black_free_gradient_enabled
        )
        # Public r25 keeps both research paths in source but always loads them
        # disabled because their controls are no longer reachable.
        self.assertFalse(migrated.color_depth.experimental_enabled)

        unknown = _project_settings_from_mapping(
            {
                "schema": "obj-adjuster.project.v12-unknown",
                "settings": injected.to_dict(),
            }
        )
        self.assertFalse(unknown.palette.black_free_gradient_enabled)
        self.assertFalse(
            unknown.part_palettes["coat"].black_free_gradient_enabled
        )
        self.assertFalse(unknown.color_depth.experimental_enabled)

        settings = AppSettings(
            palette=self._palette(enabled=True),
            color_depth=ColorDepthSettings(experimental_enabled=True),
        )
        restored = _project_settings_from_mapping(
            {
                "schema": "obj-adjuster.project.v11",
                "settings": settings.to_dict(),
            },
            developer_features_enabled=True,
        )
        self.assertFalse(restored.palette.black_free_gradient_enabled)
        self.assertFalse(restored.color_depth.experimental_enabled)

    def test_project_save_uses_v11_and_persists_policy(self) -> None:
        app = self._bare_app(self._palette(enabled=True))
        app.paint_editor = None
        app.manual_joint_record = None
        app.pending_manual_joint_record = None
        app.manual_part_partition = None
        app.pending_manual_part_partition = None
        app.manual_overrides = None
        app.manual_fingerprint = None
        app.pending_manual_payload = None
        app.obj_path = None
        app.reference_path = None
        app._variables_to_settings = Mock(return_value=app.settings)
        app._validated_manual_overrides = Mock(return_value=(True, None))

        payload = app._project_payload_for_save(app.settings, None)

        self.assertEqual(payload["schema"], "obj-adjuster.project.v12")
        self.assertTrue(
            payload["settings"]["palette"]["black_free_gradient_enabled"]
        )


class BlackFreeGradientDeveloperGateTests(unittest.TestCase):
    @staticmethod
    def _enabled_palette() -> PaletteSettings:
        return BlackFreeGradientGuiLogicTests._palette(enabled=True)

    def test_normal_mode_sanitizes_stale_v11_global_and_part_palettes(self) -> None:
        injected = AppSettings(
            palette=self._enabled_palette(),
            part_palettes={
                "coat": self._enabled_palette(),
                "boots": self._enabled_palette(),
            },
        )
        payload = {
            "schema": "obj-adjuster.project.v11",
            "settings": injected.to_dict(),
        }

        normal = _project_settings_from_mapping(payload)
        developer = _project_settings_from_mapping(
            payload,
            developer_features_enabled=True,
        )

        self.assertFalse(normal.palette.black_free_gradient_enabled)
        self.assertTrue(
            all(
                not palette.black_free_gradient_enabled
                for palette in normal.part_palettes.values()
            )
        )
        self.assertFalse(developer.palette.black_free_gradient_enabled)
        self.assertTrue(
            all(
                not palette.black_free_gradient_enabled
                for palette in developer.part_palettes.values()
            )
        )

    def test_gate_preserves_roles_but_disables_every_palette(self) -> None:
        settings = AppSettings(
            palette=self._enabled_palette(),
            part_palettes={"coat": self._enabled_palette()},
        )
        before_roles = (
            settings.palette.black_free_black_slot,
            settings.palette.black_free_red_slot,
            settings.palette.black_free_brown_slot,
        )

        changed = _enforce_black_free_gradient_developer_gate(settings)

        self.assertEqual(changed, 2)
        self.assertFalse(settings.palette.black_free_gradient_enabled)
        self.assertFalse(
            settings.part_palettes["coat"].black_free_gradient_enabled
        )
        self.assertEqual(
            (
                settings.palette.black_free_black_slot,
                settings.palette.black_free_red_slot,
                settings.palette.black_free_brown_slot,
            ),
            before_roles,
        )

    def test_turning_developer_mode_off_disables_all_and_reapplies_editor(self) -> None:
        app = BlackFreeGradientGuiLogicTests._bare_app(
            self._enabled_palette()
        )
        app.settings.part_palettes = {"coat": self._enabled_palette()}
        app.developer_features_enabled_var = FakeVar(False)
        app.black_free_gradient_enabled_var.set(True)
        app._refresh_developer_feature_visibility = Mock()
        app._load_black_free_gradient_variables = Mock()
        app._save_persistent_settings = Mock()
        reapply = Mock()
        app.paint_editor = SimpleNamespace(reapply_shading_settings=reapply)

        app._on_developer_features_toggle()

        self.assertFalse(app._developer_features_are_enabled())
        self.assertFalse(app.black_free_gradient_enabled_var.get())
        self.assertFalse(app.settings.palette.black_free_gradient_enabled)
        self.assertFalse(
            app.settings.part_palettes["coat"].black_free_gradient_enabled
        )
        reapply.assert_called_once()
        app._schedule_preview.assert_called_once_with(immediate=True)

    def test_hidden_manual_callback_cannot_reactivate_policy(self) -> None:
        app = BlackFreeGradientGuiLogicTests._bare_app(
            self._enabled_palette()
        )
        app._developer_features_enabled_committed = False
        app.active_part_key = "unrelated"
        app.settings.part_palettes = {"coat": self._enabled_palette()}

        app._on_editor_palette_settings_changed(
            "coat",
            self._enabled_palette(),
        )

        self.assertFalse(app.settings.palette.black_free_gradient_enabled)
        self.assertFalse(
            app.settings.part_palettes["coat"].black_free_gradient_enabled
        )

    def test_new_obj_and_normal_mode_project_save_remain_disabled(self) -> None:
        previous = AppSettings(
            palette=self._enabled_palette(),
            part_palettes={"old": self._enabled_palette()},
        )
        fresh = _fresh_settings_for_new_obj(previous)
        self.assertFalse(fresh.palette.black_free_gradient_enabled)
        self.assertEqual(fresh.part_palettes, {})

        app = BlackFreeGradientGuiLogicTests._bare_app(
            self._enabled_palette()
        )
        app._developer_features_enabled_committed = False
        app.paint_editor = None
        app.manual_joint_record = None
        app.pending_manual_joint_record = None
        app.manual_part_partition = None
        app.pending_manual_part_partition = None
        app.manual_overrides = None
        app.manual_fingerprint = None
        app.pending_manual_payload = None
        app.obj_path = None
        app.reference_path = None
        app._variables_to_settings = Mock(return_value=app.settings)
        app._validated_manual_overrides = Mock(return_value=(True, None))
        _enforce_black_free_gradient_developer_gate(
            app.settings,
            app._developer_features_are_enabled(),
        )
        payload = app._project_payload_for_save(app.settings, None)
        self.assertFalse(
            payload["settings"]["palette"][
                "black_free_gradient_enabled"
            ]
        )


class BlackFreeGradientLiveGuiTests(unittest.TestCase):
    def tearDown(self) -> None:
        gc.collect()

    def test_group_is_hidden_until_developer_mode_and_switches_language(self) -> None:
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
                self.assertEqual(app.black_free_gradient_group.winfo_manager(), "")
                self.assertFalse(app._developer_features_are_enabled())
                self.assertEqual(
                    str(app.black_free_black_slot_combo.cget("state")), "disabled"
                )
                self.assertEqual(
                    app.black_free_black_slot_combo.winfo_manager(), ""
                )
                self.assertEqual(
                    app.black_free_gradient_summary_label.winfo_manager(), ""
                )
                self.assertEqual(
                    app.black_free_gradient_enable_checkbutton.cget("text"),
                    "黒を含む混色を赤〜茶へ再割当",
                )

                # Even a direct call to the retained developer callback cannot
                # reinsert an experimental group into the public layout.
                app.developer_features_enabled_var.set(True)
                app._on_developer_features_toggle()
                root.update_idletasks()
                self.assertEqual(
                    app.black_free_gradient_group.winfo_manager(), ""
                )
                self.assertEqual(
                    app.developer_features_enable_checkbutton.winfo_manager(),
                    "",
                )
                app.set_language("en", persist=False)
                root.update_idletasks()
                self.assertEqual(
                    app.black_free_gradient_enable_checkbutton.cget("text"),
                    "Remap black-containing mixes toward red-brown",
                )
                self.assertEqual(
                    app.black_free_gradient_group.winfo_manager(), ""
                )
        finally:
            if app is not None:
                with patch.object(MapperApp, "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
