from __future__ import annotations

import gc
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import MapperApp, _mix_optimizer_settings_key
from spectrum_mapper.filament_recommender import recommend_basic_filaments
from spectrum_mapper.models import (
    AppSettings,
    COLOR_MODE_FULL_SPECTRUM,
    PaletteSettings,
    ToneSettings,
)
from test_part_integration import two_part_prepared


class MainShadingBridgeTests(unittest.TestCase):
    def tearDown(self) -> None:
        gc.collect()

    def test_contour_policy_is_part_of_mix_optimizer_cache_identity(self) -> None:
        outer = AppSettings(
            tone=ToneSettings(illustration_contour_policy="outer")
        )
        folds = AppSettings(
            tone=ToneSettings(
                illustration_contour_policy="outer_crease_fold"
            )
        )
        self.assertNotEqual(
            _mix_optimizer_settings_key(outer),
            _mix_optimizer_settings_key(folds),
        )

    def _app(self):
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        with (
            patch.object(
                MapperApp, "_load_persistent_settings", return_value=AppSettings()
            ),
            patch("spectrum_mapper.gui.load_language", return_value="ja"),
            patch.object(MapperApp, "_save_persistent_settings"),
        ):
            app = MapperApp(root)
        return root, app

    def _close(self, root, app) -> None:
        with patch.object(MapperApp, "_save_persistent_settings"):
            app._on_close()
        try:
            root.update_idletasks()
        except Exception:
            pass

    def test_manual_tone_callback_updates_parent_variables_and_round_trip(self) -> None:
        root, app = self._app()
        try:
            editor = SimpleNamespace(
                reapply_tone_settings=Mock(),
                mix_optimization_undo_button=None,
            )
            app.paint_editor = editor
            tone = ToneSettings(
                black_point=0.08,
                white_point=0.91,
                gamma=1.24,
                contrast=1.31,
                saturation=0.82,
                pink_protection=True,
                pink_threshold=0.07,
                smoothing=False,
                smoothing_max_area_mm2=0.09,
                smoothing_delta_e_slack=4.5,
                illustration_mode="noir",
                illustration_strength=0.88,
                illustration_bands=3,
                illustration_light="front_right",
                illustration_light_intensity=0.65,
                illustration_light_range=0.75,
                illustration_selective_highlight_fraction=0.08,
                illustration_contour_policy="outer",
            )

            app._on_editor_tone_settings_changed(tone)

            editor.reapply_tone_settings.assert_called_once()
            self.assertAlmostEqual(app.gamma_var.get(), 1.24)
            self.assertAlmostEqual(app.settings.tone.contrast, 1.31)
            round_trip = app._variables_to_settings(show_error=False)
            self.assertIsNotNone(round_trip)
            self.assertAlmostEqual(round_trip.tone.black_point, 0.08)
            self.assertAlmostEqual(round_trip.tone.white_point, 0.91)
            self.assertFalse(round_trip.tone.smoothing)
            self.assertEqual(round_trip.tone.illustration_mode, "noir")
            self.assertAlmostEqual(
                round_trip.tone.illustration_strength, 0.88
            )
            self.assertEqual(round_trip.tone.illustration_bands, 3)
            self.assertEqual(
                round_trip.tone.illustration_light, "front_right"
            )
            self.assertAlmostEqual(
                round_trip.tone.illustration_light_intensity, 0.65
            )
            self.assertAlmostEqual(
                round_trip.tone.illustration_light_range, 0.75
            )
            self.assertAlmostEqual(
                round_trip.tone.illustration_selective_highlight_fraction,
                0.08,
            )
            self.assertEqual(
                round_trip.tone.illustration_contour_policy,
                "outer",
            )
        finally:
            app.paint_editor = None
            self._close(root, app)

    def test_strong_cel_palette_request_keeps_manual_palette_when_declined(self) -> None:
        root, app = self._app()
        try:
            editor = SimpleNamespace(window=root, status_var=Mock())
            app.paint_editor = editor
            app.settings.tone = ToneSettings(illustration_mode="cel_strong")
            before = app._copy_palette(app.settings.palette)
            with (
                patch.object(
                    app, "_automatic_palette_can_follow_mode", return_value=False
                ),
                patch("spectrum_mapper.gui.messagebox.askyesno", return_value=False) as confirm,
                patch.object(app, "_recommend_all_parts") as recommend,
            ):
                app._on_editor_cel_palette_recommend_requested()

            confirm.assert_called_once()
            recommend.assert_not_called()
            self.assertEqual(app.settings.palette, before)
            self.assertEqual(
                app.status_var.get(),
                app.i18n.text("tone.illustration_recommend_kept"),
            )
        finally:
            app.paint_editor = None
            self._close(root, app)

    def test_strong_cel_palette_request_can_replace_manual_palette_after_confirmation(self) -> None:
        root, app = self._app()
        try:
            app.paint_editor = SimpleNamespace(window=root, status_var=Mock())
            app.settings.tone = ToneSettings(illustration_mode="cel_strong")
            with (
                patch.object(
                    app, "_automatic_palette_can_follow_mode", return_value=False
                ),
                patch("spectrum_mapper.gui.messagebox.askyesno", return_value=True),
                patch.object(app, "_recommend_all_parts") as recommend,
            ):
                app._on_editor_cel_palette_recommend_requested()

            recommend.assert_called_once_with(automatic=False)
        finally:
            app.paint_editor = None
            self._close(root, app)

    def test_strong_cel_palette_request_refreshes_untouched_auto_palette_without_prompt(self) -> None:
        root, app = self._app()
        try:
            app.paint_editor = SimpleNamespace(window=root, status_var=Mock())
            app.settings.tone = ToneSettings(illustration_mode="cel_strong")
            app._pending_physical_palette_targets = set()
            with (
                patch.object(
                    app, "_automatic_palette_can_follow_mode", return_value=True
                ),
                patch("spectrum_mapper.gui.messagebox.askyesno") as confirm,
                patch.object(app, "_recommend_all_parts") as recommend,
            ):
                app._on_editor_cel_palette_recommend_requested()

            confirm.assert_not_called()
            recommend.assert_called_once_with(automatic=True)
        finally:
            app.paint_editor = None
            self._close(root, app)

    def test_strong_cel_reproposal_preserves_custom_full_spectrum_recipes(
        self,
    ) -> None:
        samples = np.asarray(
            (
                (0.04, 0.04, 0.04),
                (0.94, 0.94, 0.94),
                (0.36, 0.45, 0.56),
                (0.70, 0.42, 0.28),
            ),
            dtype=np.float64,
        )
        recommendation = recommend_basic_filaments(
            samples,
            np.ones(4, dtype=np.float64),
            required_physical_rgb=samples,
            include_mixed_states=True,
            alternative_count=0,
            max_candidates=None,
        )
        existing = PaletteSettings(
            palette_state_count=32,
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            physical_hex=["#010203", "#F0F1F2", "#A06040", "#304050"],
            enabled_states=[bool(index % 3) for index in range(32)],
            mix_hex_overrides=[
                "#101112",
                None,
                "#202122",
                None,
                "#303132",
                None,
            ],
            mix_ratios_b=[21, 27, 35, 43, 58, 72],
            secondary_mix_ratios_b=[79, 73, 65, 57, 42, 28],
            output_mix_ratios_b=[17 + index for index in range(28)],
        )

        updated = MapperApp._palette_from_recommendation(
            recommendation,
            palette_state_count=32,
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            existing_palette=existing,
            preserve_existing_recipes=True,
        )

        self.assertNotEqual(updated.physical_hex, existing.physical_hex)
        self.assertEqual(updated.enabled_states, existing.enabled_states)
        self.assertEqual(
            updated.mix_hex_overrides, existing.mix_hex_overrides
        )
        self.assertEqual(updated.mix_ratios_b, existing.mix_ratios_b)
        self.assertEqual(
            updated.secondary_mix_ratios_b,
            existing.secondary_mix_ratios_b,
        )
        self.assertEqual(
            updated.output_mix_ratios_b,
            existing.output_mix_ratios_b,
        )

    def test_main_preview_passes_selected_part_to_outline_pair_renderer(self) -> None:
        root, app = self._app()
        try:
            prepared = two_part_prepared()
            selected_key = prepared.preview.part_keys[1]
            app.prepared = prepared
            app.active_part_key = selected_key
            app.preview_after_id = None
            blank = Image.new("RGB", (12, 12), (0, 0, 0))
            pair = SimpleNamespace(
                source=blank,
                target=blank.copy(),
                face_ids=np.full((12, 12), -1, dtype=np.int32),
            )

            def submit_now(function):
                future = Future()
                function()
                future.set_result(None)
                return future

            with (
                patch.object(app.preview_executor, "submit", side_effect=submit_now),
                patch(
                    "spectrum_mapper.gui.render_front_preview_pair",
                    return_value=pair,
                ) as render_pair,
            ):
                app._start_preview_job()

            self.assertEqual(render_pair.call_args.kwargs["active_part_id"], 1)
            kind, payload = app.work_queue.get_nowait()
            self.assertEqual(kind, "preview_done")
            self.assertEqual(payload[1], selected_key)
        finally:
            self._close(root, app)

    def test_manual_mix_request_uses_the_editors_explicit_part(self) -> None:
        root, app = self._app()
        try:
            prepared = two_part_prepared()
            part_key = prepared.final.part_keys[1]
            app.prepared = prepared
            editor = SimpleNamespace(
                window=root,
                reapply_palette_settings=Mock(),
                mix_optimization_undo_button=None,
            )
            app.paint_editor = editor
            with (
                patch.object(app, "_select_part_key") as select_part,
                patch.object(app, "_optimize_mix_ratios") as optimize,
            ):
                app._on_editor_mix_optimization_requested(part_key)

            select_part.assert_called_once_with(part_key)
            self.assertIs(optimize.call_args.kwargs["dialog_parent"], root)
            callback = optimize.call_args.kwargs["on_applied"]
            callback(part_key, app.settings.palette)
            editor.reapply_palette_settings.assert_called_once()
        finally:
            app.paint_editor = None
            self._close(root, app)


if __name__ == "__main__":
    unittest.main()
