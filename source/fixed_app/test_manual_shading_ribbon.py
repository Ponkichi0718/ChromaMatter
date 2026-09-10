from __future__ import annotations

from collections import deque
import inspect
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest import mock

import numpy as np

from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import (
    AppSettings,
    MeshLevel,
    PaletteSettings,
    PreparedGeometry,
    ToneSettings,
)
from spectrum_mapper.paint_gui import PaintEditorWindow
import spectrum_mapper.paint_gui as paint_gui


class _Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _AfterWindow:
    def __init__(self) -> None:
        self.callbacks: dict[str, object] = {}
        self.cancelled: list[str] = []
        self.serial = 0

    def after(self, _milliseconds: int, callback):
        self.serial += 1
        identifier = f"after-{self.serial}"
        self.callbacks[identifier] = callback
        return identifier

    def after_cancel(self, identifier: str) -> None:
        self.cancelled.append(identifier)
        self.callbacks.pop(identifier, None)


def _prepared() -> PreparedGeometry:
    vertices = np.asarray(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        dtype=np.float32,
    )
    faces = np.asarray(((0, 1, 2),), dtype=np.int32)
    colors = np.asarray(
        ((0.2, 0.2, 0.2), (0.8, 0.8, 0.8), (0.5, 0.5, 0.5)),
        dtype=np.float32,
    )
    level = MeshLevel(
        vertices,
        faces,
        colors,
        np.asarray((0.5,), dtype=np.float32),
        None,
        face_part_ids=np.asarray((0,), dtype=np.int16),
        part_names=("demo part",),
        part_keys=("demo-key",),
    )
    return PreparedGeometry(
        source=SimpleNamespace(sha256=""),
        final=level,
        preview=level,
        clean_vertex_count=3,
        clean_face_count=1,
        removed_vertices=0,
        removed_faces=0,
        topology={},
        source_area_unit=0.5,
        source_volume_unit=0.0,
        simplified_area_unit=0.5,
        simplified_volume_unit=0.0,
        source_dimensions_unit=np.asarray((1.0, 1.0, 0.0)),
        warnings=[],
        part_names=level.part_names,
        part_keys=level.part_keys,
    )


def _tone_editor(callback):
    tone = ToneSettings()
    editor = object.__new__(PaintEditorWindow)
    editor.window = _AfterWindow()
    editor.i18n = Translator("ja")
    editor.status_var = _Variable("")
    editor._closing = False
    editor._close_requested = False
    editor._syncing_tone_controls = False
    editor._tone_change_after = None
    editor._tone_callback_revision = 0
    editor.on_tone_settings_changed = callback
    editor.tone_black_point_var = _Variable(tone.black_point)
    editor.tone_white_point_var = _Variable(tone.white_point)
    editor.tone_gamma_var = _Variable(tone.gamma)
    editor.tone_contrast_var = _Variable(tone.contrast)
    editor.tone_saturation_var = _Variable(tone.saturation)
    editor.tone_pink_protection_var = _Variable(tone.pink_protection)
    editor.tone_pink_threshold_var = _Variable(tone.pink_threshold)
    editor.tone_smoothing_var = _Variable(tone.smoothing)
    editor.tone_smoothing_area_var = _Variable(
        tone.smoothing_max_area_mm2
    )
    editor.tone_smoothing_slack_var = _Variable(
        tone.smoothing_delta_e_slack
    )
    editor.illustration_mode_var = _Variable(tone.illustration_mode)
    editor.illustration_strength_var = _Variable(
        tone.illustration_strength * 100.0
    )
    editor.illustration_bands_var = _Variable(tone.illustration_bands)
    editor.illustration_light_var = _Variable(tone.illustration_light)
    editor.illustration_light_intensity_var = _Variable(
        tone.illustration_light_intensity * 100.0
    )
    editor.illustration_light_range_var = _Variable(
        tone.illustration_light_range * 100.0
    )
    editor.illustration_selective_highlight_var = _Variable(
        tone.illustration_selective_highlight_fraction * 100.0
    )
    editor.illustration_contour_policy_var = _Variable(
        tone.illustration_contour_policy
    )
    return editor


class ManualShadingRibbonTests(unittest.TestCase):
    def test_constructor_exposes_granular_shading_callbacks(self) -> None:
        parameters = inspect.signature(PaintEditorWindow.__init__).parameters
        self.assertIn("on_tone_settings_changed", parameters)
        self.assertIn("on_mix_optimization_requested", parameters)
        self.assertIn("on_mix_optimization_undo_requested", parameters)
        self.assertIn("on_tone_reset_requested", parameters)
        self.assertIn("on_cel_palette_recommend_requested", parameters)

    def test_tone_controls_debounce_to_latest_complete_snapshot(self) -> None:
        received: list[ToneSettings] = []
        editor = _tone_editor(received.append)

        editor.tone_gamma_var.set(1.18)
        editor._on_editor_tone_control_changed()
        first = editor._tone_change_after
        editor.tone_gamma_var.set(1.42)
        editor.tone_saturation_var.set(0.76)
        editor.illustration_mode_var.set("noir")
        editor.illustration_strength_var.set(91.0)
        editor.illustration_bands_var.set(3)
        editor.illustration_light_var.set("bottom_right")
        editor.illustration_light_intensity_var.set(65.0)
        editor.illustration_light_range_var.set(75.0)
        editor.illustration_selective_highlight_var.set(5.0)
        editor.illustration_contour_policy_var.set("outer")
        editor._on_editor_tone_control_changed()
        second = editor._tone_change_after

        self.assertNotEqual(first, second)
        self.assertEqual(editor.window.cancelled, [first])
        callback = editor.window.callbacks[second]
        callback()

        self.assertEqual(len(received), 1)
        self.assertAlmostEqual(received[0].gamma, 1.42)
        self.assertAlmostEqual(received[0].saturation, 0.76)
        self.assertEqual(received[0].illustration_mode, "noir")
        self.assertAlmostEqual(received[0].illustration_strength, 0.91)
        self.assertEqual(received[0].illustration_bands, 3)
        self.assertEqual(received[0].illustration_light, "bottom_right")
        self.assertAlmostEqual(received[0].illustration_light_intensity, 0.65)
        self.assertAlmostEqual(received[0].illustration_light_range, 0.75)
        self.assertAlmostEqual(
            received[0].illustration_selective_highlight_fraction, 0.05
        )
        self.assertEqual(received[0].illustration_contour_policy, "outer")
        self.assertIsNone(editor._tone_change_after)

    def test_pending_illustration_change_is_flushed_before_close(self) -> None:
        received: list[ToneSettings] = []
        editor = _tone_editor(received.append)
        editor.illustration_mode_var.set("cel")
        editor.illustration_bands_var.set(2)
        editor._on_editor_tone_control_changed()
        pending = editor._tone_change_after

        self.assertIsNotNone(pending)
        self.assertTrue(editor._flush_pending_tone_change())
        self.assertIn(pending, editor.window.cancelled)
        self.assertIsNone(editor._tone_change_after)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].illustration_mode, "cel")
        self.assertEqual(received[0].illustration_bands, 2)

    def test_cel_palette_request_flushes_pending_tone_first(self) -> None:
        events: list[str] = []
        editor = _tone_editor(lambda _tone: events.append("tone"))
        editor.on_cel_palette_recommend_requested = lambda: events.append(
            "recommend"
        )
        editor.illustration_mode_var.set("cel_strong")
        editor._on_editor_tone_control_changed()

        editor._request_cel_palette_recommendation()

        self.assertEqual(events, ["tone", "recommend"])
        self.assertIsNone(editor._tone_change_after)

    def test_parent_approved_tone_and_part_palette_are_reapplied(self) -> None:
        editor = _tone_editor(None)
        editor.settings = AppSettings()
        editor.part_keys = ("part-a", "part-b")
        editor._refresh_palette_buttons = mock.Mock()
        editor._queue_shading_reapply = mock.Mock()

        tone = ToneSettings(
            black_point=0.12,
            white_point=0.91,
            gamma=1.24,
            contrast=1.16,
            saturation=0.82,
            pink_protection=True,
            pink_threshold=0.08,
            smoothing=False,
            smoothing_max_area_mm2=0.09,
            smoothing_delta_e_slack=4.5,
            illustration_mode="cel",
            illustration_strength=0.66,
            illustration_bands=5,
            illustration_light="front",
            illustration_light_intensity=0.65,
            illustration_light_range=0.75,
            illustration_selective_highlight_fraction=0.08,
            illustration_contour_policy="outer_crease",
        )
        editor.reapply_tone_settings(tone)
        self.assertEqual(editor.settings.tone, tone)
        self.assertAlmostEqual(editor.tone_gamma_var.get(), 1.24)
        self.assertEqual(editor.illustration_mode_var.get(), "cel")
        self.assertAlmostEqual(editor.illustration_strength_var.get(), 66.0)
        self.assertEqual(editor.illustration_bands_var.get(), 5)
        self.assertEqual(editor.illustration_light_var.get(), "front")
        self.assertAlmostEqual(
            editor.illustration_light_intensity_var.get(), 65.0
        )
        self.assertAlmostEqual(editor.illustration_light_range_var.get(), 75.0)
        self.assertAlmostEqual(
            editor.illustration_selective_highlight_var.get(), 8.0
        )
        self.assertEqual(
            editor.illustration_contour_policy_var.get(), "outer_crease"
        )

        palette = PaletteSettings(mix_ratios_b=[11, 22, 33, 44, 55, 66])
        editor.reapply_palette_settings("part-b", palette)
        stored = editor.settings.part_palettes["part-b"]
        self.assertEqual(stored.mix_ratios_b, [11, 22, 33, 44, 55, 66])
        palette.mix_ratios_b[0] = 99
        self.assertEqual(stored.mix_ratios_b[0], 11)
        self.assertEqual(editor._queue_shading_reapply.call_count, 2)

    def test_reapply_worker_updates_automatic_colors_without_notifying_override(self) -> None:
        editor = _tone_editor(None)
        editor.settings = AppSettings()
        editor.level = _prepared().final
        editor.part_keys = ("demo-key",)
        editor.active_part_id = 0
        editor.view_theme_mode = "auto"
        editor._closing = False
        editor._close_requested = False
        editor._shading_reapply_revision = 0
        editor._queued_actions = deque()
        editor._commit_active_stroke = lambda: None
        submitted = []
        editor._submit = lambda kind, function: submitted.append((kind, function))

        class Session:
            def __init__(self):
                self.overrides = np.asarray((7,), dtype=np.int8)
                self.auto_indices = np.asarray((0,), dtype=np.int8)

            def set_auto_indices(self, values):
                self.auto_indices = np.asarray(values, dtype=np.int8).copy()

        editor._session = Session()
        editor._renderer = None
        editor._worker_snapshot = lambda _frame, message: {
            "overrides": editor._session.overrides.copy(),
            "message": message,
        }
        colors = SimpleNamespace(
            palette_indices=np.asarray((3,), dtype=np.int8)
        )
        display = SimpleNamespace(
            target_face_rgb=np.asarray(((0.3, 0.4, 0.5),), dtype=np.float32)
        )
        appearance = SimpleNamespace(
            background=(0.0, 0.0, 0.0),
            active_part_accent=(1.0, 1.0, 1.0),
        )

        with (
            mock.patch.object(paint_gui, "recolor_level_parts", return_value=colors),
            mock.patch.object(
                paint_gui,
                "apply_palette_overrides_parts",
                return_value=display,
            ),
            mock.patch.object(
                paint_gui,
                "resolve_view_appearance",
                return_value=appearance,
            ),
        ):
            editor.reapply_tone_settings(ToneSettings(gamma=1.3))
            self.assertEqual(len(submitted), 1)
            kind, work = submitted[0]
            self.assertEqual(kind, "shading_reapply")
            snapshot = work()

        self.assertEqual(int(editor._session.auto_indices[0]), 3)
        self.assertEqual(int(editor._session.overrides[0]), 7)
        self.assertTrue(snapshot["_suppress_override_notification"])
        self.assertTrue(snapshot["shading_reapplied"])

    def test_shading_page_has_illustration_group_and_keeps_public_host(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        editor = None
        try:
            cel_recommendations: list[str] = []
            with mock.patch.object(PaintEditorWindow, "_submit", return_value=None):
                editor = PaintEditorWindow(
                    root,
                    _prepared(),
                    AppSettings(),
                    None,
                    None,
                    lambda _values: None,
                    on_tone_settings_changed=lambda _tone: None,
                    on_mix_optimization_requested=lambda _part: None,
                    on_mix_optimization_undo_requested=lambda _part: None,
                    on_tone_reset_requested=lambda: None,
                    on_cel_palette_recommend_requested=(
                        lambda: cel_recommendations.append("requested")
                    ),
                )

            def descendant_texts(widget: tk.Misc) -> set[str]:
                result: set[str] = set()
                pending = list(widget.winfo_children())
                while pending:
                    child = pending.pop()
                    pending.extend(child.winfo_children())
                    try:
                        text = str(child.cget("text"))
                    except tk.TclError:
                        continue
                    if text:
                        result.add(text)
                return result

            texts = descendant_texts(editor.ribbon_pages["shading"])
            self.assertEqual(
                editor._shading_section_selected, "illustration"
            )
            self.assertEqual(
                {
                    name: button.cget("text")
                    for name, button in editor.shading_section_buttons.items()
                },
                {
                    "global": "全体",
                    "illustration": "2D彩色",
                    "mix": "混色",
                    "local": "面内補正",
                },
            )
            self.assertEqual(
                {
                    name: frame.winfo_manager()
                    for name, frame in editor.shading_section_frames.items()
                },
                {
                    "global": "",
                    "illustration": "grid",
                    "mix": "",
                    "local": "",
                },
            )
            self.assertEqual(
                int(editor.auto_shading_host.grid_info()["row"]), 1
            )
            root.update_idletasks()
            self.assertLessEqual(
                editor.ribbon_pages["shading"].winfo_reqheight(), 260
            )
            self.assertIn("1  全体の陰影・色調", texts)
            self.assertIn("試験  2D彩色フィルター", texts)
            self.assertIn("セル彩色", texts)
            self.assertIn("セル彩色（強調）", texts)
            self.assertIn("陰影モノクロ", texts)
            self.assertIn("彩色効果", texts)
            self.assertIn("階調", texts)
            self.assertIn("光源方向（正面図）", texts)
            self.assertIn("光の強さ", texts)
            self.assertIn("光の範囲", texts)
            self.assertIn("ハイライト範囲", texts)
            self.assertIn("標準", texts)
            self.assertIn("5%（推奨）", texts)
            self.assertIn("輪郭として暗くする面", texts)
            self.assertIn("外周のみ", texts)
            self.assertIn("外周＋明確な稜線", texts)
            self.assertIn(
                "外周＋稜線＋確実な折れ目（推奨・現状）", texts
            )
            self.assertIn(
                "線を描く設定ではありません。選んだ形状付近の面を"
                "既存の暗い印刷色へ割り当てます。ハイライト5～12%で"
                "使用します。",
                texts,
            )
            self.assertEqual(
                editor.illustration_palette_recommend_button.winfo_manager(),
                "",
            )
            highlight_buttons = (
                editor.illustration_selective_highlight_standard_button,
                editor.illustration_selective_highlight_5_button,
                editor.illustration_selective_highlight_8_button,
                editor.illustration_selective_highlight_12_button,
            )
            self.assertTrue(
                all(
                    str(button.cget("state")) == "disabled"
                    for button in highlight_buttons
                )
            )
            editor.illustration_mode_var.set("cel_strong")
            editor._on_editor_tone_control_changed()
            root.update_idletasks()
            self.assertTrue(
                all(
                    str(button.cget("state")) == "normal"
                    for button in highlight_buttons
                )
            )
            contour_buttons = (
                editor.illustration_contour_outer_button,
                editor.illustration_contour_outer_crease_button,
                editor.illustration_contour_outer_crease_fold_button,
            )
            self.assertTrue(
                all(
                    str(button.cget("state")) == "disabled"
                    for button in contour_buttons
                )
            )
            editor.illustration_selective_highlight_5_button.invoke()
            self.assertAlmostEqual(
                editor.illustration_selective_highlight_var.get(), 5.0
            )
            self.assertTrue(
                all(
                    str(button.cget("state")) == "normal"
                    for button in contour_buttons
                )
            )
            editor.illustration_contour_outer_crease_button.invoke()
            self.assertEqual(
                editor.illustration_contour_policy_var.get(),
                "outer_crease",
            )
            editor.illustration_selective_highlight_standard_button.invoke()
            self.assertTrue(
                all(
                    str(button.cget("state")) == "disabled"
                    for button in contour_buttons
                )
            )
            self.assertEqual(
                editor.illustration_contour_policy_var.get(),
                "outer_crease",
            )
            self.assertEqual(
                editor.illustration_palette_recommend_button.winfo_manager(),
                "grid",
            )
            self.assertEqual(
                editor.illustration_palette_recommend_button.cget("text"),
                "強調セル向け4色を提案",
            )
            editor.illustration_palette_recommend_button.invoke()
            self.assertEqual(cel_recommendations, ["requested"])
            self.assertTrue(
                {"↖", "↑", "↗", "←", "◎", "→", "↙", "↓", "↘"}
                <= texts
            )
            expected_light_buttons = {
                "illustration_light_left_button": "front_left",
                "illustration_light_top_button": "top",
                "illustration_light_right_button": "front_right",
                "illustration_light_side_left_button": "left",
                "illustration_light_front_button": "front",
                "illustration_light_side_right_button": "right",
                "illustration_light_bottom_left_button": "bottom_left",
                "illustration_light_bottom_button": "bottom",
                "illustration_light_bottom_right_button": "bottom_right",
            }
            for attribute, expected_value in expected_light_buttons.items():
                button = getattr(editor, attribute)
                self.assertTrue(root.tk.getboolean(button.cget("takefocus")))
                self.assertGreaterEqual(button.winfo_reqwidth(), 28)
                self.assertGreaterEqual(button.winfo_reqheight(), 24)
                self.assertEqual(str(button.cget("selectcolor")), "#17344A")
                button.invoke()
                self.assertEqual(editor.illustration_light_var.get(), expected_value)
            self.assertIn("2  混色比率を陰影に合わせる", texts)
            self.assertIn("3  面内グラデーション補正", texts)
            self.assertTrue(editor.auto_shading_host.winfo_exists())
            self.assertEqual(len(editor.tone_scale_widgets), 5)
            self.assertEqual(
                float(editor.shading_global_title_label.cget("wraplength")), 140.0
            )
            tone_details = editor.shading_section_frames["global"].grid_slaves(
                row=2, column=0
            )[0]
            self.assertEqual(int(tone_details.grid_info()["columnspan"]), 7)
            self.assertEqual(
                sorted(
                    int(child.grid_info()["row"])
                    for child in tone_details.winfo_children()
                    if child.winfo_class() == "TCheckbutton"
                ),
                [0, 2],
            )
            self.assertEqual(
                str(editor.mix_optimization_button.cget("state")), "normal"
            )
            editor.set_language("en")
            root.update_idletasks()
            texts = descendant_texts(editor.ribbon_pages["shading"])
            self.assertEqual(
                {
                    name: button.cget("text")
                    for name, button in editor.shading_section_buttons.items()
                },
                {
                    "global": "Tone",
                    "illustration": "2D Color",
                    "mix": "Mixes",
                    "local": "In-face",
                },
            )
            self.assertIn("Light Direction (Front View)", texts)
            self.assertIn("Light Strength", texts)
            self.assertIn("Light Range", texts)
            self.assertIn("Highlight Area", texts)
            self.assertIn("5% (Recommended)", texts)
            self.assertIn("Faces Darkened as Contours", texts)
            self.assertIn("Silhouette Only", texts)
            self.assertIn("Silhouette + Sharp Edges", texts)
            self.assertIn(
                "Silhouette + Edges + Confirmed Folds "
                "(Recommended / Current)",
                texts,
            )
            self.assertIn(
                "This does not draw lines. It assigns faces near the selected "
                "geometry to an existing darker print color. Use with a 5-12% "
                "Highlight Area.",
                texts,
            )
            self.assertEqual(
                editor.illustration_palette_recommend_button.cget("text"),
                "Suggest 4 Colors for Cel",
            )
            illustration_frame = editor.shading_illustration_title_label.master
            for label in (
                editor.shading_illustration_title_label,
                editor.illustration_light_label,
            ):
                self.assertEqual(float(label.cget("wraplength")), 140.0)
            self.assertLessEqual(illustration_frame.winfo_reqwidth(), 1080)
            self.assertLessEqual(
                editor.ribbon_pages["shading"].winfo_reqwidth(), 1080
            )

            # Sub-pages reuse the original frames rather than recreating
            # their controls.  Values and the chosen sub-page therefore
            # survive page changes, live language changes, and ribbon folding.
            editor.tone_gamma_var.set(1.42)
            editor.illustration_strength_var.set(63.0)
            frame_ids = {
                name: str(frame)
                for name, frame in editor.shading_section_frames.items()
            }
            auto_shading_host_id = str(editor.auto_shading_host)
            for selected in ("global", "mix", "local", "illustration"):
                editor._select_shading_section(selected)
                root.update_idletasks()
                self.assertEqual(
                    [
                        name
                        for name, frame in editor.shading_section_frames.items()
                        if frame.winfo_manager() == "grid"
                    ],
                    [selected],
                )
                self.assertLessEqual(
                    editor.ribbon_pages["shading"].winfo_reqheight(), 300
                )
                section_geometry = [
                    (
                        child.winfo_class(),
                        child.winfo_reqwidth(),
                        child.winfo_reqheight(),
                        child.grid_info(),
                    )
                    for child in editor.shading_section_frames[
                        selected
                    ].winfo_children()
                ]
                self.assertLessEqual(
                    editor.ribbon_pages["shading"].winfo_reqwidth(),
                    1080,
                    msg=(
                        f"section={selected}, backend="
                        f"{root.tk.call('tk', 'windowingsystem')}, "
                        f"child requests={section_geometry}"
                    ),
                )
            self.assertAlmostEqual(editor.tone_gamma_var.get(), 1.42)
            self.assertAlmostEqual(
                editor.illustration_strength_var.get(), 63.0
            )
            self.assertEqual(
                {
                    name: str(frame)
                    for name, frame in editor.shading_section_frames.items()
                },
                frame_ids,
            )
            self.assertEqual(
                str(editor.auto_shading_host), auto_shading_host_id
            )
            editor._select_ribbon("shading")
            editor._select_shading_section("mix")
            editor._toggle_ribbon()
            self.assertFalse(editor._ribbon_expanded)
            editor.set_language("ja")
            editor._toggle_ribbon()
            root.update_idletasks()
            self.assertTrue(editor._ribbon_expanded)
            self.assertEqual(editor._ribbon_selected, "shading")
            self.assertEqual(editor._shading_section_selected, "mix")
            self.assertEqual(
                [
                    name
                    for name, frame in editor.shading_section_frames.items()
                    if frame.winfo_manager() == "grid"
                ],
                ["mix"],
            )
            self.assertEqual(
                editor.shading_section_buttons["mix"].cget("text"), "混色"
            )
        finally:
            if editor is not None:
                # This structure-only test mocks _submit(), so it cannot use
                # the asynchronous production close path.  Stop and remove
                # every callback owned by its private Tk interpreter before
                # destroying that interpreter; otherwise a later live-Tk test
                # can receive the orphaned worker-poll command.
                editor._closing = True
                try:
                    root.update_idletasks()
                    for after_id in root.tk.call("after", "info"):
                        root.after_cancel(after_id)
                except tk.TclError:
                    pass
                editor._executor.shutdown(wait=False, cancel_futures=True)
                try:
                    editor.window.destroy()
                except tk.TclError:
                    pass
            root.destroy()


if __name__ == "__main__":
    unittest.main()
