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

from spectrum_mapper.gui import MapperApp
from spectrum_mapper.models import AppSettings, ToneSettings
from test_part_integration import two_part_prepared


class MainShadingBridgeTests(unittest.TestCase):
    def tearDown(self) -> None:
        gc.collect()

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
        finally:
            app.paint_editor = None
            self._close(root, app)

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
