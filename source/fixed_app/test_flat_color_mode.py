from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import mixer
from spectrum_mapper.engine import apply_palette_overrides, recolor_level
from spectrum_mapper.gui import MapperApp, _project_settings_from_mapping
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import (
    AppSettings,
    COLOR_MODE_FLAT_FOUR,
    COLOR_MODE_FULL_SPECTRUM,
    MeshLevel,
    PaletteSettings,
    ToneSettings,
)
from spectrum_mapper.paint_gui import _effective_paint_enabled_states
from spectrum_mapper.parts import palette_identity, print_palette_identity


class _FakeVar:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


def _one_face_level(rgb: np.ndarray) -> MeshLevel:
    return MeshLevel(
        vertices_unit=np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float64,
        ),
        faces=np.asarray([[0, 1, 2]], dtype=np.int32),
        vertex_colors=np.repeat(np.asarray(rgb, dtype=np.float64)[None, :], 3, axis=0),
        areas_unit=np.asarray([0.5], dtype=np.float64),
        neighbors=None,
    )


def _mode_switch_app(
    common: PaletteSettings,
    part_palettes: dict[str, PaletteSettings],
) -> MapperApp:
    app = MapperApp.__new__(MapperApp)
    app.settings = AppSettings(
        palette=common,
        part_palettes=part_palettes,
    )
    app.active_part_key = None
    app.busy = False
    app.color_mode_var = _FakeVar(COLOR_MODE_FULL_SPECTRUM)
    app.part_recommendations = {}
    app.i18n = Translator("ja")
    app.status_var = _FakeVar("")
    app.paint_editor = None
    app.prepared = SimpleNamespace(
        final=SimpleNamespace(part_keys=list(part_palettes))
    )
    app.source_path = Path("C:/models/mode-history.glb")
    app._automatic_palette_model_token = None
    app._automatic_palette_signatures = {}
    app._commit_active_palette = Mock(return_value=common)
    app._refresh_color_mode_widgets = Mock()
    app._refresh_part_tree = Mock()
    app._note_mix_input_change = Mock()
    app._schedule_preview = Mock()
    app._draw_comparison_canvas = Mock()
    app._save_persistent_settings = Mock()
    app._recommend_all_parts = Mock()
    return app


class FlatColorModeModelTests(unittest.TestCase):
    def test_full_is_legacy_default_and_flat_round_trips(self) -> None:
        legacy = AppSettings().to_dict()
        self.assertNotIn("color_mode", legacy["palette"])
        self.assertEqual(
            AppSettings.from_dict(json.loads(json.dumps(legacy))).palette.color_mode,
            COLOR_MODE_FULL_SPECTRUM,
        )

        settings = AppSettings(
            palette=PaletteSettings(color_mode=COLOR_MODE_FLAT_FOUR),
            part_palettes={
                "body": PaletteSettings(color_mode=COLOR_MODE_FLAT_FOUR)
            },
        )
        payload = json.loads(json.dumps(settings.to_dict()))
        self.assertEqual(payload["palette"]["color_mode"], COLOR_MODE_FLAT_FOUR)
        self.assertEqual(
            payload["part_palettes"]["body"]["color_mode"],
            COLOR_MODE_FLAT_FOUR,
        )
        restored = AppSettings.from_dict(payload)
        self.assertEqual(restored.palette.color_mode, COLOR_MODE_FLAT_FOUR)
        self.assertEqual(
            restored.part_palettes["body"].color_mode,
            COLOR_MODE_FLAT_FOUR,
        )

    def test_invalid_mode_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            PaletteSettings(color_mode="automatic-magic")

    def test_project_boundary_makes_the_public_mode_global(self) -> None:
        settings = AppSettings(
            palette=PaletteSettings(color_mode=COLOR_MODE_FLAT_FOUR),
            part_palettes={
                "body": PaletteSettings(color_mode=COLOR_MODE_FULL_SPECTRUM)
            },
        )
        loaded = _project_settings_from_mapping(
            {
                "schema": "obj-adjuster.project.v13",
                "settings": settings.to_dict(),
            }
        )
        self.assertEqual(loaded.palette.color_mode, COLOR_MODE_FLAT_FOUR)
        self.assertEqual(
            loaded.part_palettes["body"].color_mode,
            COLOR_MODE_FLAT_FOUR,
        )

    def test_flat_print_identity_ignores_dormant_mix_recipes(self) -> None:
        first = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            palette_state_count=32,
            mix_ratios_b=[12, 23, 34, 45, 56, 67],
            secondary_mix_ratios_b=[78, 67, 56, 45, 34, 23],
            output_mix_ratios_b=list(range(5, 33)),
        )
        second = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            palette_state_count=16,
            mix_ratios_b=[88, 77, 66, 55, 44, 33],
            secondary_mix_ratios_b=[22, 33, 44, 55, 66, 77],
        )
        self.assertNotEqual(palette_identity(first), palette_identity(second))
        self.assertEqual(print_palette_identity(first), print_palette_identity(second))


class FlatColorModeEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.physical = ["#101010", "#F0F0F0", "#D62D32", "#704830"]
        _hex, palette_rgb = mixer.build_palette_rgb(
            self.physical,
            [None] * 6,
            [33] * 6,
            [67] * 6,
        )
        self.mixed_rgb = palette_rgb[4]
        self.level = _one_face_level(self.mixed_rgb)
        self.tone = ToneSettings(white_point=1.0, smoothing=False)

    def test_automatic_assignment_uses_only_f1_to_f4(self) -> None:
        full = PaletteSettings(
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            physical_hex=list(self.physical),
        )
        flat = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(self.physical),
        )
        full_result = recolor_level(self.level, 100.0, self.tone, full)
        flat_result = recolor_level(self.level, 100.0, self.tone, flat)

        self.assertEqual(int(full_result.palette_indices[0]), 4)
        self.assertLess(int(flat_result.palette_indices[0]), 4)
        self.assertEqual(int(flat_result.palette_face_counts[4:].sum()), 0)

    def test_mixed_manual_id_is_remapped_without_destroying_saved_edit(self) -> None:
        flat = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(self.physical),
        )
        full = PaletteSettings(
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            physical_hex=list(self.physical),
        )
        automatic = recolor_level(self.level, 100.0, self.tone, flat)
        overrides = np.asarray([4], dtype=np.int8)
        original = overrides.copy()

        flat_painted = apply_palette_overrides(
            self.level, 100.0, flat, automatic, overrides
        )
        full_painted = apply_palette_overrides(
            self.level, 100.0, full, automatic, overrides
        )

        np.testing.assert_array_equal(overrides, original)
        self.assertLess(int(flat_painted.palette_indices[0]), 4)
        self.assertEqual(int(full_painted.palette_indices[0]), 4)

    def test_manual_editor_candidate_mask_is_non_destructive(self) -> None:
        enabled = [True] * 32
        palette = PaletteSettings(
            palette_state_count=32,
            color_mode=COLOR_MODE_FLAT_FOUR,
            enabled_states=enabled,
        )
        effective = _effective_paint_enabled_states(palette)
        self.assertTrue(np.all(effective[:4]))
        self.assertFalse(np.any(effective[4:]))
        self.assertEqual(palette.enabled_states, enabled)


class FlatColorModeGuiTests(unittest.TestCase):
    def test_basic_auto_flat_mode_replaces_only_physical_filaments(self) -> None:
        enabled = [False] * 4 + [index % 2 == 0 for index in range(28)]
        mix_overrides = ["#123456", None, "#345678", None, None, "#56789A"]
        primary = [12, 23, 34, 45, 56, 67]
        secondary = [78, 69, 58, 47, 36, 25]
        output = [20 + index for index in range(28)]
        assignment = [f"#{index:02X}{index:02X}{index:02X}" for index in range(32)]
        existing = PaletteSettings(
            palette_state_count=32,
            color_mode=COLOR_MODE_FLAT_FOUR,
            enabled_states=enabled,
            mix_hex_overrides=mix_overrides,
            mix_ratios_b=primary,
            secondary_mix_ratios_b=secondary,
            output_mix_ratios_b=output,
            assignment_palette_hex=assignment,
        )
        physical_hex = ("#AA1111", "#11AA11", "#1111AA", "#F0F0F0")
        candidates = tuple(
            SimpleNamespace(
                product_id=f"product-{index}",
                brand="Test",
                series="PLA",
                color_name=f"Color {index}",
                matched_hex=color,
                finish_class="標準/不透明",
                source_kind="catalog",
                material="PLA",
                source_url=None,
                record_id=f"record-{index}",
                measurement_id=None,
            )
            for index, color in enumerate(physical_hex, start=1)
        )
        recommendation = SimpleNamespace(
            physical_hex=physical_hex,
            primary_ratio_b_percent=91,
            secondary_ratio_b_percent=9,
            candidates=candidates,
        )

        palette = MapperApp._palette_from_recommendation(
            recommendation,
            16,
            color_mode=COLOR_MODE_FLAT_FOUR,
            existing_palette=existing,
        )

        self.assertEqual(palette.color_mode, COLOR_MODE_FLAT_FOUR)
        self.assertEqual(palette.palette_state_count, 32)
        self.assertEqual(palette.physical_hex, list(physical_hex))
        self.assertEqual(palette.enabled_states[:4], [True] * 4)
        self.assertEqual(palette.enabled_states[4:], enabled[4:])
        self.assertEqual(palette.mix_hex_overrides, mix_overrides)
        self.assertEqual(palette.mix_ratios_b, primary)
        self.assertEqual(palette.secondary_mix_ratios_b, secondary)
        self.assertEqual(palette.output_mix_ratios_b, output)
        self.assertIsNone(palette.assignment_palette_hex)
        self.assertEqual(
            [ref.product_id if ref is not None else None for ref in palette.physical_filament_refs],
            [f"product-{index}" for index in range(1, 5)],
        )

    def test_flat_mode_keeps_the_mixed_recipe_panel_closed(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app.settings = AppSettings(
            palette=PaletteSettings(color_mode=COLOR_MODE_FLAT_FOUR)
        )
        app.color_mode_var = _FakeVar(COLOR_MODE_FLAT_FOUR)
        app.recipe_panel_visible_var = _FakeVar(True)
        app.i18n = Translator("ja")
        app.root = object()

        app._set_recipe_panel_visible(True)
        self.assertFalse(app.recipe_panel_visible_var.get())

        with patch("spectrum_mapper.gui.messagebox.showinfo") as showinfo:
            app._apply_selected_recipe()
        showinfo.assert_called_once()
        self.assertIn("4色", showinfo.call_args.args[0])

    def test_mode_switch_updates_every_part_and_preserves_full_recipes(self) -> None:
        common_assignment = ["#102030"] * 32
        part_assignment = ["#405060"] * 32
        common = PaletteSettings(
            mix_ratios_b=[11, 22, 33, 44, 55, 66],
            mix_hex_overrides=["#123456", None, None, None, None, None],
            assignment_palette_hex=common_assignment,
        )
        part = PaletteSettings(
            mix_ratios_b=[66, 55, 44, 33, 22, 11],
            output_mix_ratios_b=list(range(10, 38)),
            assignment_palette_hex=part_assignment,
        )
        app = MapperApp.__new__(MapperApp)
        app.settings = AppSettings(palette=common, part_palettes={"body": part})
        app.active_part_key = None
        app.busy = False
        app.color_mode_var = _FakeVar(COLOR_MODE_FULL_SPECTRUM)
        app.part_recommendations = {"body": object()}
        app.i18n = Translator("ja")
        app.status_var = _FakeVar("")
        app.paint_editor = SimpleNamespace(reapply_shading_settings=Mock())
        def commit_with_legacy_override_clear():
            common.mix_hex_overrides = [None] * 6
            return common

        app._commit_active_palette = Mock(side_effect=commit_with_legacy_override_clear)
        app._note_mix_input_change = Mock()
        app._refresh_color_mode_widgets = Mock()
        app._refresh_part_tree = Mock()
        app._schedule_preview = Mock()
        app._draw_comparison_canvas = Mock()
        app._save_persistent_settings = Mock()

        common_recipes = (list(common.mix_ratios_b), list(common.mix_hex_overrides))
        part_recipes = (list(part.mix_ratios_b), list(part.output_mix_ratios_b or ()))
        app._change_color_mode(COLOR_MODE_FLAT_FOUR)

        self.assertEqual(app.settings.palette.color_mode, COLOR_MODE_FLAT_FOUR)
        self.assertEqual(
            app.settings.part_palettes["body"].color_mode,
            COLOR_MODE_FLAT_FOUR,
        )
        self.assertEqual(
            (common.mix_ratios_b, common.mix_hex_overrides), common_recipes
        )
        self.assertEqual(
            (part.mix_ratios_b, part.output_mix_ratios_b), part_recipes
        )
        self.assertEqual(common.assignment_palette_hex, common_assignment)
        self.assertEqual(part.assignment_palette_hex, part_assignment)
        self.assertEqual(app.part_recommendations, {})
        app.paint_editor.reapply_shading_settings.assert_called_once()
        self.assertIn("フラット", app.status_var.get())

    def test_untouched_new_model_auto_palette_is_recomputed_for_flat(self) -> None:
        common = PaletteSettings(
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            physical_hex=["#101010", "#00FF40", "#818184", "#EB3B41"],
        )
        part = MapperApp._copy_palette(common)
        app = _mode_switch_app(common, {"body": part})
        app._record_automatic_palette_provenance((None, "body"))
        # Reprocessing the same source replaces PreparedGeometry.  That must
        # not revive the mode that happened to be active at file-open time.
        app.prepared = SimpleNamespace(
            final=SimpleNamespace(part_keys=["body"])
        )

        self.assertTrue(app._automatic_palette_can_follow_mode())
        app._change_color_mode(COLOR_MODE_FLAT_FOUR)

        app._recommend_all_parts.assert_called_once_with(automatic=True)
        self.assertEqual(app.settings.palette.color_mode, COLOR_MODE_FLAT_FOUR)
        self.assertEqual(
            app.settings.part_palettes["body"].color_mode,
            COLOR_MODE_FLAT_FOUR,
        )

    def test_manual_filament_edit_is_not_overwritten_on_mode_switch(self) -> None:
        common = PaletteSettings(
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            physical_hex=["#101010", "#00FF40", "#818184", "#EB3B41"],
        )
        part = MapperApp._copy_palette(common)
        app = _mode_switch_app(common, {"body": part})
        app._record_automatic_palette_provenance((None, "body"))
        common.physical_hex[1] = "#BCBFC2"

        self.assertFalse(app._automatic_palette_can_follow_mode())
        app._change_color_mode(COLOR_MODE_FLAT_FOUR)

        app._recommend_all_parts.assert_not_called()
        self.assertEqual(app.settings.palette.physical_hex[1], "#BCBFC2")

    def test_mode_switch_without_part_palettes_still_refreshes_output(self) -> None:
        common = PaletteSettings(color_mode=COLOR_MODE_FULL_SPECTRUM)
        app = _mode_switch_app(common, {})

        app._change_color_mode(COLOR_MODE_FLAT_FOUR)

        self.assertEqual(app.settings.palette.color_mode, COLOR_MODE_FLAT_FOUR)
        app._schedule_preview.assert_called_once_with(immediate=True)
        app._save_persistent_settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
