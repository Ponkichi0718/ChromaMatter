from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import smooth_paint_hotfix
from spectrum_mapper import mixer
from spectrum_mapper.engine import (
    apply_palette_overrides,
    recolor_level,
    recolor_level_parts,
)
from spectrum_mapper.gui import MapperApp
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import AppSettings, MeshLevel, PaletteSettings, ToneSettings
from spectrum_mapper.parts import palette_identity, print_palette_identity
from smooth_paint import PaintNode


# Exact base colors visible in the reported r31 screenshot before F2 was
# replaced by vivid green.
SCREENSHOT_BASE = ["#121212", "#BCBFC2", "#818184", "#EB3B41"]
SCREENSHOT_REPLACEMENT = ["#121212", "#00FF40", "#818184", "#EB3B41"]
IDENTITY_TONE = ToneSettings(white_point=1.0, smoothing=False)


def rgb(value: str) -> np.ndarray:
    return mixer.hex_to_rgb8(value).astype(np.float64) / 255.0


def palette_snapshot(palette: PaletteSettings) -> list[str]:
    colors, _rgb = mixer.build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    return list(colors)


def level_for_face_colors(
    colors: list[np.ndarray],
    *,
    part_keys: tuple[str, ...] = (),
    face_part_ids: np.ndarray | None = None,
) -> MeshLevel:
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    vertex_colors: list[np.ndarray] = []
    for face_index, color in enumerate(colors):
        start = len(vertices)
        x = float(face_index * 2)
        vertices.extend(([x, 0.0, 0.0], [x + 1.0, 0.0, 0.0], [x, 1.0, 0.0]))
        faces.append([start, start + 1, start + 2])
        vertex_colors.extend((color, color, color))
    count = len(faces)
    return MeshLevel(
        vertices_unit=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int32),
        vertex_colors=np.asarray(vertex_colors, dtype=np.float64),
        areas_unit=np.full(count, 0.5, dtype=np.float64),
        neighbors=None,
        face_part_ids=(
            np.asarray(face_part_ids, dtype=np.int16)
            if face_part_ids is not None
            else np.empty(0, dtype=np.int16)
        ),
        part_names=tuple(f"Part {index + 1}" for index in range(len(part_keys))),
        part_keys=part_keys,
    )


def locked_replacement(count: int = 32) -> tuple[PaletteSettings, PaletteSettings]:
    enabled = [True] * count
    baseline = PaletteSettings(
        palette_state_count=count,
        physical_hex=list(SCREENSHOT_BASE),
        enabled_states=enabled,
    )
    replacement = PaletteSettings(
        palette_state_count=count,
        physical_hex=list(SCREENSHOT_REPLACEMENT),
        enabled_states=enabled,
        assignment_palette_hex=palette_snapshot(baseline),
    )
    return baseline, replacement


class ManualPaletteEngineTests(unittest.TestCase):
    def test_screenshot_f2_green_keeps_ids_but_changes_the_converted_preview(self) -> None:
        level = level_for_face_colors([rgb(SCREENSHOT_BASE[1])])
        for count in mixer.SUPPORTED_PALETTE_STATE_COUNTS:
            with self.subTest(count=count):
                baseline, locked = locked_replacement(count)
                unlocked = PaletteSettings(
                    palette_state_count=count,
                    physical_hex=list(SCREENSHOT_REPLACEMENT),
                    enabled_states=[True] * count,
                )
                before = recolor_level(level, 100.0, IDENTITY_TONE, baseline)
                ordinary_recompute = recolor_level(
                    level, 100.0, IDENTITY_TONE, unlocked
                )
                applied = recolor_level(level, 100.0, IDENTITY_TONE, locked)

                self.assertEqual(int(before.palette_indices[0]), 1)
                self.assertNotEqual(int(ordinary_recompute.palette_indices[0]), 1)
                np.testing.assert_array_equal(
                    applied.palette_indices, before.palette_indices
                )
                np.testing.assert_allclose(
                    applied.target_face_rgb[0], rgb("#00FF40"), atol=1e-12
                )
                self.assertFalse(
                    np.allclose(
                        ordinary_recompute.target_face_rgb[0],
                        applied.target_face_rgb[0],
                    )
                )

    def test_global_lock_changes_only_inheriting_parts(self) -> None:
        baseline, locked = locked_replacement(32)
        local = PaletteSettings(
            palette_state_count=32,
            physical_hex=["#101820", "#2266CC", "#D0D8E0", "#7A30C0"],
            enabled_states=[True] * 32,
        )
        level = level_for_face_colors(
            [rgb(SCREENSHOT_BASE[1]), rgb(local.physical_hex[1])],
            part_keys=("body", "accent"),
            face_part_ids=np.asarray([0, 1], dtype=np.int16),
        )
        before = recolor_level_parts(
            level, 100.0, IDENTITY_TONE, baseline, {"accent": local}
        )
        applied = recolor_level_parts(
            level, 100.0, IDENTITY_TONE, locked, {"accent": local}
        )

        np.testing.assert_array_equal(applied.palette_indices, before.palette_indices)
        self.assertFalse(
            np.allclose(applied.target_face_rgb[0], before.target_face_rgb[0])
        )
        np.testing.assert_allclose(
            applied.target_face_rgb[1], before.target_face_rgb[1]
        )

    def test_manual_override_and_black_correction_keep_state_ids(self) -> None:
        baseline, locked = locked_replacement(32)
        for palette in (baseline, locked):
            palette.black_free_gradient_enabled = True
            palette.black_free_black_slot = 0
            palette.black_free_red_slot = 3
            palette.black_free_brown_slot = 2
        mixed_hex = palette_snapshot(baseline)[4]
        level = level_for_face_colors([rgb(mixed_hex), rgb("#818184")])
        before = recolor_level(level, 100.0, IDENTITY_TONE, baseline)
        applied = recolor_level(level, 100.0, IDENTITY_TONE, locked)
        np.testing.assert_array_equal(applied.palette_indices, before.palette_indices)
        self.assertEqual(
            applied.black_free_remapped_faces, before.black_free_remapped_faces
        )

        overrides = np.asarray([-1, 1], dtype=np.int8)
        original_overrides = overrides.copy()
        painted = apply_palette_overrides(
            level, 100.0, locked, applied, overrides
        )
        np.testing.assert_array_equal(overrides, original_overrides)
        self.assertEqual(int(painted.palette_indices[1]), 1)
        np.testing.assert_allclose(painted.target_face_rgb[1], rgb("#00FF40"))
        self.assertEqual(painted.manual_override_faces, 1)


class ManualPalettePersistenceTests(unittest.TestCase):
    def test_assignment_snapshot_round_trips_for_global_and_part_palettes(self) -> None:
        _baseline, locked = locked_replacement(24)
        settings = AppSettings(
            palette=locked,
            part_palettes={"accent": MapperApp._copy_palette(locked)},
        )
        encoded = json.loads(json.dumps(settings.to_dict()))
        restored = AppSettings.from_dict(encoded)

        self.assertEqual(
            restored.palette.assignment_palette_hex,
            locked.assignment_palette_hex,
        )
        self.assertEqual(
            restored.part_palettes["accent"].assignment_palette_hex,
            locked.assignment_palette_hex,
        )
        self.assertNotEqual(
            palette_identity(restored.palette),
            palette_identity(PaletteSettings(
                palette_state_count=24,
                physical_hex=list(SCREENSHOT_REPLACEMENT),
                enabled_states=[True] * 24,
            )),
        )
        self.assertEqual(
            print_palette_identity(restored.palette),
            print_palette_identity(PaletteSettings(
                palette_state_count=24,
                physical_hex=list(SCREENSHOT_REPLACEMENT),
                enabled_states=[True] * 24,
            )),
        )

    def test_none_is_omitted_and_invalid_snapshots_fail_closed(self) -> None:
        payload = AppSettings().to_dict()
        self.assertNotIn("assignment_palette_hex", payload["palette"])
        with self.assertRaisesRegex(ValueError, "32 colours"):
            PaletteSettings(assignment_palette_hex=["#000000"] * 31)
        with self.assertRaisesRegex(ValueError, "#RRGGBB"):
            PaletteSettings(assignment_palette_hex=[0] * 32)  # type: ignore[list-item]

    def test_automatic_recommendation_starts_a_fresh_unlocked_assignment(self) -> None:
        recommendation = SimpleNamespace(
            physical_hex=("#E32B35", "#F2F1ED", "#2255CC", "#161616"),
            primary_ratio_b_percent=31,
            secondary_ratio_b_percent=69,
            candidates=(),
        )
        palette = MapperApp._palette_from_recommendation(
            recommendation, 32, material="PLA"
        )
        self.assertIsNone(palette.assignment_palette_hex)


class ManualPaletteAdaptiveTests(unittest.TestCase):
    def test_gpu_palette_refresh_preserves_adaptive_tree_state_ids(self) -> None:
        baseline, locked = locked_replacement(32)
        level = level_for_face_colors(
            [rgb(SCREENSHOT_BASE[1]), rgb("#818184")],
            part_keys=("body",),
            face_part_ids=np.asarray([0, 0], dtype=np.int16),
        )
        tree = PaintNode.branch([PaintNode(1)] * 4)
        level._hotfix_tree_store = {0: tree}
        settings = AppSettings(palette=baseline)
        smooth_paint_hotfix._configure_gpu_palette_routing(settings, level)
        stored = level._hotfix_tree_store

        settings.palette = locked
        smooth_paint_hotfix._configure_gpu_palette_routing(settings, level)

        self.assertIs(level._hotfix_tree_store, stored)
        self.assertIs(level._hotfix_tree_store[0], tree)
        self.assertEqual([child.state for child in tree.children or ()], [1] * 4)
        self.assertEqual(
            list(level._hotfix_palette.physical_hex),
            list(SCREENSHOT_REPLACEMENT),
        )


class ManualPaletteGuiTests(unittest.TestCase):
    def _app(self):
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        with (
            patch.object(MapperApp, "_load_persistent_settings", return_value=AppSettings()),
            patch("spectrum_mapper.gui.load_language", return_value="ja"),
            patch.object(MapperApp, "_save_persistent_settings"),
        ):
            app = MapperApp(root)
        return root, app

    def _close(self, root, app) -> None:
        app.paint_editor = None
        with patch.object(MapperApp, "_save_persistent_settings"):
            app._on_close()
        try:
            root.update_idletasks()
        except Exception:
            pass

    def test_apply_button_is_visible_and_bilingual(self) -> None:
        root, app = self._app()
        try:
            button = app.apply_physical_palette_button
            self.assertEqual(button.winfo_manager(), "grid")
            self.assertEqual(int(button.grid_info()["row"]), 6)
            self.assertEqual(
                button.cget("text"),
                Translator("ja").text("palette.apply_physical"),
            )
            app.set_language("en", persist=False)
            self.assertEqual(
                button.cget("text"),
                Translator("en").text("palette.apply_physical"),
            )
        finally:
            self._close(root, app)

    def test_edit_waits_for_button_then_reapplies_without_losing_manual_state(self) -> None:
        root, app = self._app()
        try:
            app.settings.palette = PaletteSettings(
                palette_state_count=32,
                physical_hex=list(SCREENSHOT_BASE),
                enabled_states=[True] * 32,
            )
            app._load_palette_variables(app.settings.palette)
            manual = np.asarray([-1, 7, -1, 1], dtype=np.int8)
            app.manual_overrides = manual.copy()
            adaptive_tree = {2: PaintNode(7)}
            editor = SimpleNamespace(
                settings=AppSettings(),
                reapply_palette_settings=Mock(),
                mix_optimization_undo_button=None,
                _hotfix_tree_store=adaptive_tree,
            )
            app.paint_editor = editor
            app.last_mix_ratios = [33] * 6
            app.last_mix_target_key = None
            app._schedule_preview = Mock()

            app.physical_vars[1].set("#00FF40")

            app._schedule_preview.assert_not_called()
            self.assertEqual(app._pending_physical_palette_targets, {None})
            self.assertIsNotNone(app.settings.palette.assignment_palette_hex)
            self.assertIsNone(app.last_mix_ratios)
            np.testing.assert_array_equal(app.manual_overrides, manual)
            self.assertIs(editor._hotfix_tree_store, adaptive_tree)

            app.apply_physical_palette_button.invoke()

            app._schedule_preview.assert_called_once_with(immediate=True)
            self.assertEqual(app._pending_physical_palette_targets, set())
            editor.reapply_palette_settings.assert_called_once()
            applied_key, applied_palette = editor.reapply_palette_settings.call_args.args
            self.assertIsNone(applied_key)
            self.assertEqual(applied_palette.physical_hex[1], "#00FF40")
            self.assertIsNotNone(applied_palette.assignment_palette_hex)
            np.testing.assert_array_equal(app.manual_overrides, manual)
            self.assertEqual(editor._hotfix_tree_store[2].state, 7)
        finally:
            self._close(root, app)

    def test_part_apply_clears_only_that_target(self) -> None:
        root, app = self._app()
        try:
            app.settings.part_names["arm"] = "Arm"
            app.settings.part_palettes["arm"] = PaletteSettings(
                palette_state_count=32,
                physical_hex=list(SCREENSHOT_BASE),
                enabled_states=[True] * 32,
            )
            app._mark_physical_palette_pending(None)
            app.active_part_key = "arm"
            app._load_palette_variables(app.settings.part_palettes["arm"])
            app._schedule_preview = Mock()

            app.physical_vars[1].set("#00FF40")
            self.assertEqual(
                app._pending_physical_palette_targets, {None, "arm"}
            )
            app._apply_physical_palette_to_conversion()

            self.assertEqual(app._pending_physical_palette_targets, {None})
            app._schedule_preview.assert_called_once_with(immediate=True)
        finally:
            self._close(root, app)

    def test_export_is_blocked_before_solidify_or_save_while_palette_is_pending(self) -> None:
        root, app = self._app()
        try:
            app._mark_physical_palette_pending(None)
            app._mark_physical_palette_pending("arm")
            app.settings.part_names["arm"] = "Arm"
            with (
                patch("spectrum_mapper.gui.messagebox.showwarning") as warning,
                patch.object(app, "_start_export_auto_solidification") as solidify,
                patch("spectrum_mapper.gui.filedialog.asksaveasfilename") as save,
            ):
                app._export()

            warning.assert_called_once()
            self.assertIn("Arm", warning.call_args.args[1])
            self.assertIn(
                Translator("ja").text("parts.common"),
                warning.call_args.args[1],
            )
            solidify.assert_not_called()
            save.assert_not_called()
        finally:
            self._close(root, app)

    def test_project_load_clears_stale_pending_targets(self) -> None:
        root, app = self._app()
        try:
            app._pending_physical_palette_targets.update({None, "arm"})
            app._apply_project_payload(
                {},
                AppSettings(),
                reference_path=None,
                reference_image=None,
                ignored_features=(),
            )
            self.assertEqual(app._pending_physical_palette_targets, set())
        finally:
            self._close(root, app)

    def test_removed_or_copied_part_palettes_leave_no_orphan_pending_target(self) -> None:
        root, app = self._app()
        try:
            app.settings.part_palettes["arm"] = PaletteSettings()
            app.active_part_key = "arm"
            app._load_palette_variables(app.settings.part_palettes["arm"])
            app._pending_physical_palette_targets.add("arm")
            app._refresh_palette_widgets = Mock()
            app._refresh_part_tree = Mock()
            app._clear_selected_part_palette()
            self.assertNotIn("arm", app._pending_physical_palette_targets)

            app.active_part_key = None
            app.prepared = SimpleNamespace(
                final=SimpleNamespace(part_keys=("arm", "leg"))
            )
            app._pending_physical_palette_targets.update(
                {None, "arm", "leg"}
            )
            app._schedule_preview = Mock()
            app._copy_palette_to_all_parts()
            self.assertEqual(app._pending_physical_palette_targets, set())
            app._schedule_preview.assert_called_once_with(immediate=True)
        finally:
            self._close(root, app)

    def test_new_preview_request_invalidates_debounced_stale_callback(self) -> None:
        root, app = self._app()
        try:
            app.prepared = SimpleNamespace()
            app.preview_generation = 10
            callbacks: list[object] = []

            def capture_after(_delay, callback):
                callbacks.append(callback)
                return f"preview-{len(callbacks)}"

            with (
                patch.object(root, "after", side_effect=capture_after),
                patch.object(root, "after_cancel"),
            ):
                app._schedule_preview(immediate=True)
                app._schedule_preview(immediate=True)
            self.assertEqual(app.preview_generation, 12)
            first = callbacks[0]
            assert callable(first)
            first()
            self.assertEqual(app.preview_generation, 12)
            self.assertEqual(app.preview_after_id, "preview-2")
        finally:
            self._close(root, app)


if __name__ == "__main__":
    unittest.main()
