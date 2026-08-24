from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import smooth_paint
import smooth_paint_hotfix
from spectrum_mapper.mixer import build_palette_rgb
from spectrum_mapper.models import (
    AppSettings,
    COLOR_MODE_FLAT_FOUR,
    COLOR_MODE_FULL_SPECTRUM,
    PaletteSettings,
)
from spectrum_mapper.paint_gui import (
    PaintEditorWindow,
    _effective_paint_state,
)


class _Var:
    def __init__(self, value) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class _Combo:
    def __init__(self) -> None:
        self.state = None

    def configure(self, **kwargs) -> None:
        self.state = kwargs.get("state", self.state)


def _flat_palette() -> PaletteSettings:
    return PaletteSettings(
        color_mode=COLOR_MODE_FLAT_FOUR,
        palette_state_count=32,
        physical_hex=["#101010", "#F0F0F0", "#D62D32", "#704830"],
        enabled_states=[True] * 32,
    )


def _palette_rgb(palette: PaletteSettings) -> np.ndarray:
    _hex, rgb = build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    return np.asarray(rgb, dtype=np.float64)


class FlatManualPaintStateTests(unittest.TestCase):
    def test_mixed_selection_maps_to_nearest_physical_without_mutation(self) -> None:
        palette = _flat_palette()
        rgb = _palette_rgb(palette)
        raw_enabled = list(palette.enabled_states)
        raw_overrides = list(palette.mix_hex_overrides)
        expected = int(
            np.argmin(np.sum((rgb[:4] - rgb[4]) ** 2, axis=1))
        )

        self.assertEqual(
            _effective_paint_state(palette, 4, palette_rgb=rgb), expected
        )
        self.assertEqual(palette.enabled_states, raw_enabled)
        self.assertEqual(palette.mix_hex_overrides, raw_overrides)

    def test_eyedropper_maps_visible_mixed_state_but_keeps_saved_override(self) -> None:
        palette = _flat_palette()
        rgb = _palette_rgb(palette)
        raw_override = np.asarray([4], dtype=np.int8)
        session = SimpleNamespace(
            overrides=raw_override,
            sample_painted_state=lambda _face, adaptive_state=None: (
                4 if adaptive_state is None else adaptive_state
            ),
        )
        editor = PaintEditorWindow.__new__(PaintEditorWindow)
        editor.effective_indices = np.asarray([4], dtype=np.int8)
        editor._session = session
        editor._adaptive_state_at = lambda _face, _event: None
        editor._active_palette = lambda: palette
        editor.palette_rgb = rgb
        editor.paint_state_var = _Var(0)
        editor.status_var = _Var("")
        editor.i18n = SimpleNamespace(
            text=lambda key, **values: f"{key}:{values}"
        )
        editor.state_names = tuple(f"state {index}" for index in range(32))
        editor._update_selected_palette_label = lambda: None

        self.assertTrue(editor._sample_current_3d_state(0))
        self.assertLess(int(editor.paint_state_var.get()), 4)
        np.testing.assert_array_equal(session.overrides, raw_override)

    def test_brush_airbrush_and_fill_capture_only_physical_states(self) -> None:
        palette = _flat_palette()
        calls: dict[str, object] = {}

        class Session:
            def begin_stroke(self, _label):
                return None

            def paint_brush(self, _seed, state, _radius, **_kwargs):
                calls["brush"] = int(state)

            def end_stroke(self):
                return 1

            def cancel_stroke(self):
                raise AssertionError("stroke unexpectedly cancelled")

            def airbrush_stroke(
                self, _seeds, state, _radius, _strength, **kwargs
            ):
                calls["airbrush"] = int(state)
                calls["airbrush_enabled"] = np.asarray(
                    kwargs["enabled_states"], dtype=bool
                ).copy()
                return np.asarray([0], dtype=np.int32)

            def fill(self, _seed, state):
                calls["fill"] = int(state)
                return np.asarray([0], dtype=np.int32)

            def smudge_stroke(self, _seeds, _radius, _strength, **kwargs):
                calls["smudge_enabled"] = np.asarray(
                    kwargs["enabled_states"], dtype=bool
                ).copy()
                return np.asarray([0], dtype=np.int32)

        editor = PaintEditorWindow.__new__(PaintEditorWindow)
        editor.paint_state_var = _Var(4)
        editor.brush_radius_var = _Var(1.0)
        editor.edge_guard_var = _Var(False)
        editor.edge_angle_var = _Var(45.0)
        editor.airbrush_strength_var = _Var(50.0)
        editor.smudge_strength_var = _Var(50.0)
        editor.palette_rgb = _palette_rgb(palette)
        editor._active_palette = lambda: palette
        editor._visible_face_mask_for_stroke = lambda: None
        editor._session = Session()
        editor._worker_refresh_after_edit = lambda *_args: None
        editor._submit = lambda _kind, work: work()
        editor.i18n = SimpleNamespace(text=lambda key, **_values: key)
        editor._drag_mode = None
        editor._stroke_faces = []
        editor._stroke_pressures = []
        editor._airbrush_started_at = None

        editor._queue_stroke([0], erase=False)
        editor._queue_airbrush([0])
        editor._queue_smudge([0])
        editor._queue_fill(0)

        self.assertLess(int(calls["brush"]), 4)
        self.assertLess(int(calls["airbrush"]), 4)
        self.assertLess(int(calls["fill"]), 4)
        enabled = np.asarray(calls["airbrush_enabled"], dtype=bool)
        self.assertTrue(np.all(enabled[:4]))
        self.assertFalse(np.any(enabled[4:]))
        smudge_enabled = np.asarray(calls["smudge_enabled"], dtype=bool)
        self.assertTrue(np.all(smudge_enabled[:4]))
        self.assertFalse(np.any(smudge_enabled[4:]))

    def test_flat_state_count_control_shows_four_without_changing_storage(self) -> None:
        palette = _flat_palette()
        combo = _Combo()
        editor = PaintEditorWindow.__new__(PaintEditorWindow)
        editor._active_palette = lambda: palette
        editor.manual_palette_state_count_var = _Var(32)
        editor.manual_palette_state_count_combo = combo
        editor.paint_state_var = _Var(9)
        editor.palette_buttons = [_Combo() for _state in range(32)]
        editor._layout_manual_palette_buttons = lambda _palette: None
        editor._update_selected_palette_label = lambda: None

        editor._refresh_palette_buttons()

        self.assertEqual(editor.manual_palette_state_count_var.get(), 4)
        self.assertEqual(combo.state, "disabled")
        self.assertEqual(palette.palette_state_count, 32)
        self.assertEqual(editor.paint_state_var.get(), 0)


class FlatAdaptivePaintRoutingTests(unittest.TestCase):
    def test_capture_helpers_filter_new_states_without_mutating_palette(self) -> None:
        palette = _flat_palette()
        rgb = _palette_rgb(palette)
        original_enabled = list(palette.enabled_states)

        mapped = smooth_paint_hotfix._effective_manual_state(palette, 4, rgb)
        enabled = smooth_paint_hotfix._effective_enabled_state_mask(palette)

        self.assertLess(mapped, 4)
        self.assertTrue(np.all(enabled[:4]))
        self.assertFalse(np.any(enabled[4:]))
        self.assertEqual(palette.enabled_states, original_enabled)

    def test_flat_gpu_routing_maps_old_tree_ids_and_restores_full_view(self) -> None:
        palette = _flat_palette()
        settings = AppSettings(palette=palette)
        level = SimpleNamespace(
            faces=np.asarray(((0, 1, 2),), dtype=np.int32),
            part_keys=("body",),
            face_part_ids=np.asarray((0,), dtype=np.int16),
        )
        tree = smooth_paint.PaintNode(4)
        level._hotfix_tree_store = {0: tree}
        raw_rgb = _palette_rgb(palette)
        mapping = smooth_paint_hotfix._flat_four_state_map(raw_rgb)

        smooth_paint_hotfix._configure_gpu_palette_routing(settings, level)

        routed = level._hotfix_part_palette_rgb_tables[0]
        np.testing.assert_allclose(routed, raw_rgb[mapping], atol=1.0e-6)
        self.assertIs(level._hotfix_tree_store[0], tree)
        self.assertEqual(tree.state, 4)
        self.assertEqual(palette.palette_state_count, 32)

        palette.color_mode = COLOR_MODE_FULL_SPECTRUM
        smooth_paint_hotfix._configure_gpu_palette_routing(settings, level)
        self.assertIsNone(level._hotfix_part_palette_rgb_tables)
        self.assertIs(level._hotfix_tree_store[0], tree)
        self.assertEqual(tree.state, 4)


if __name__ == "__main__":
    unittest.main()
