from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import queue
import re
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.i18n import (
    CATALOG,
    Translator,
    load_language,
    save_language,
)
from spectrum_mapper.models import AppSettings


class TranslationCatalogTests(unittest.TestCase):
    def test_high_contrast_cel_palette_help_explains_safe_cool_proposal(self) -> None:
        japanese = Translator("ja")
        english = Translator("en")

        self.assertIn("4色", japanese.text("tone.illustration_recommend"))
        self.assertIn(
            "広い暗色・低彩度の素材",
            japanese.text("tone.illustration_recommend_help"),
        )
        self.assertIn("4 Colors", english.text("tone.illustration_recommend"))
        self.assertIn(
            "broad, dark low-chroma material",
            english.text("tone.illustration_recommend_help"),
        )

    def test_every_catalog_entry_has_japanese_and_english(self) -> None:
        self.assertGreaterEqual(len(CATALOG), 100)
        for key, translations in CATALOG.items():
            with self.subTest(key=key):
                self.assertTrue(translations.get("ja"))
                self.assertTrue(translations.get("en"))

    def test_known_text_can_switch_both_directions(self) -> None:
        translator = Translator("ja")
        self.assertEqual(translator.text("toolbar.open_obj"), "OBJ / GLBを開く")
        translator.set_language("en")
        self.assertEqual(translator.text("toolbar.open_obj"), "Open OBJ / GLB")
        self.assertEqual(
            translator.translate_known("OBJ / GLBを開く"), "Open OBJ / GLB"
        )
        translator.set_language("ja")
        self.assertEqual(
            translator.translate_known("Open OBJ / GLB"), "OBJ / GLBを開く"
        )

    def test_radial_stage_a_copy_switches_language_and_states_limits(self) -> None:
        translator = Translator("ja")
        self.assertIn(
            "Stage A",
            translator.text("radial.mode.uniform_stage_a"),
        )
        self.assertIn("黒コア", translator.text("radial.black_slot"))
        self.assertIn("ΔL*", translator.text("radial.contrast_threshold"))
        self.assertIn("0.10 mm", translator.text("radial.help"))
        self.assertIn("SLICE ONLY", translator.text("radial.help"))
        self.assertIn("外面100%", translator.text("radial.help"))
        self.assertIn("純黒面", translator.text("radial.pure_black_excluded"))

        translator.set_language("en")
        self.assertIn(
            "Stage A",
            translator.text("radial.mode.uniform_stage_a"),
        )
        self.assertIn("Black-core", translator.text("radial.black_slot"))
        self.assertIn("ΔL*", translator.text("radial.contrast_threshold"))
        self.assertIn("0.10 mm", translator.text("radial.help"))
        self.assertIn("SLICE ONLY", translator.text("radial.help"))
        self.assertIn("entire exterior", translator.text("radial.help"))
        self.assertIn("Pure-black", translator.text("radial.pure_black_excluded"))

    def test_radial_selective_hybrid_copy_is_explicit_in_both_languages(self) -> None:
        translator = Translator("ja")
        self.assertIn("選択式ハイブリッド", translator.text("radial.mode.selective_hybrid"))
        self.assertIn("CIELAB", translator.text("radial.help_hybrid"))
        self.assertIn("純黒面", translator.text("radial.help_hybrid"))
        self.assertIn("通常方式を維持", translator.text("radial.help_hybrid"))
        self.assertIn("SLICE ONLY", translator.text("radial.help_hybrid"))

        translator.set_language("en")
        self.assertIn("Selective hybrid", translator.text("radial.mode.selective_hybrid"))
        self.assertIn("CIELAB", translator.text("radial.help_hybrid"))
        self.assertIn("Pure-black", translator.text("radial.help_hybrid"))
        self.assertIn("conventional method", translator.text("radial.help_hybrid"))
        self.assertIn("SLICE ONLY", translator.text("radial.help_hybrid"))

    def test_radial_adaptive_skin_copy_and_values_are_localized(self) -> None:
        translator = Translator("ja")
        self.assertIn("一定厚", translator.text("radial.skin_mode.uniform"))
        self.assertIn("適応厚", translator.text("radial.skin_mode.adaptive"))
        japanese_help = translator.text("radial.help_hybrid_adaptive")
        self.assertIn("target L*", japanese_help)
        self.assertIn("4〜6段階", japanese_help)
        self.assertIn("SLICE ONLY", japanese_help)
        message = translator.text(
            "radial.confirm_message_hybrid_adaptive",
            target=translator.text(
                "radial.target_selected_part", name="Head"
            ),
            black="F1",
            threshold=35.0,
            minimum=0.10,
            maximum=0.30,
            gamma=1.25,
            bands=5,
            layer=0.10,
            wall="classic",
            mapping="target L*=50.0 → 0.20 mm",
            summary="F1+F2 ΔL*=90.0",
        )
        self.assertIn("0.10〜0.30", message)
        self.assertIn("5段階", message)
        self.assertIn("target L*=50.0", message)

        translator.set_language("en")
        self.assertIn("Uniform", translator.text("radial.skin_mode.uniform"))
        self.assertIn("Adaptive", translator.text("radial.skin_mode.adaptive"))
        english_help = translator.text("radial.help_hybrid_adaptive")
        self.assertIn("target L*", english_help)
        self.assertIn("4–6", english_help)
        self.assertIn("SLICE ONLY", english_help)

    def test_radial_stage_a_dynamic_copy_has_required_values(self) -> None:
        for language in ("ja", "en"):
            with self.subTest(language=language):
                translator = Translator(language)
                pair = translator.text(
                    "radial.summary_pair",
                    black="F1",
                    partner="F2",
                    delta=72.4,
                    decision=translator.text("radial.summary_target"),
                )
                confirmation = translator.text(
                    "radial.confirm_message",
                    target=translator.text("radial.target_whole_model"),
                    black="F1",
                    threshold=35.0,
                    thickness=0.15,
                    layer=0.10,
                    wall="classic",
                )
                contrast_error = translator.text(
                    "radial.reason.contrast_below_threshold",
                    maximum=22.5,
                    threshold=35.0,
                )
                process_error = translator.text(
                    "radial.reason.unsupported_process",
                    layer=0.20,
                    wall="arachne",
                )
                hybrid_confirmation = translator.text(
                    "radial.confirm_message_hybrid",
                    target=translator.text(
                        "radial.target_selected_part", name="Head"
                    ),
                    black="F1",
                    threshold=35.0,
                    thickness=0.15,
                    layer=0.10,
                    wall="classic",
                    summary="F1+F2 target",
                )

                self.assertIn("F1", pair)
                self.assertIn("F2", pair)
                self.assertIn("72.4", pair)
                self.assertIn("35.0", confirmation)
                self.assertIn("0.15", confirmation)
                self.assertIn("0.10", confirmation)
                self.assertIn("classic", confirmation)
                self.assertIn("22.5", contrast_error)
                self.assertIn("35.0", contrast_error)
                self.assertIn("0.20", process_error)
                self.assertIn("arachne", process_error)
                self.assertIn("F1+F2 target", hybrid_confirmation)
                self.assertIn("SLICE ONLY", hybrid_confirmation)
                self.assertIn("Head", hybrid_confirmation)

    def test_radial_export_target_copy_distinguishes_whole_and_selected(self) -> None:
        for language, whole_token, selected_token, action_token in (
            ("ja", "モデル全体", "選択パーツ", "1パーツを選んで"),
            ("en", "whole model", "selected part", "Select one part"),
        ):
            with self.subTest(language=language):
                translator = Translator(language)
                whole_button = translator.text("radial.export_hybrid")
                selected_target = translator.text(
                    "radial.target_selected_part", name="Head"
                )
                selected_button = translator.text(
                    "radial.export_hybrid_selected",
                    target=selected_target,
                )
                palette_action = translator.text(
                    "radial.reason.single_palette_required"
                )

                self.assertIn(whole_token, whole_button)
                self.assertIn(selected_token, selected_button)
                self.assertIn("Head", selected_button)
                self.assertIn(action_token, palette_action)

    def test_manual_editing_name_is_exact_in_both_languages(self) -> None:
        translator = Translator("ja")
        self.assertEqual(translator.text("toolbar.open_paint"), "マニュアル修正")
        self.assertEqual(translator.text("paint.title"), "マニュアル修正")
        translator.set_language("en")
        self.assertEqual(translator.text("toolbar.open_paint"), "Manual Editing")
        self.assertEqual(translator.text("paint.title"), "Manual Editing")

    def test_preview_uses_ai_model_color_name_in_both_languages(self) -> None:
        translator = Translator("ja")
        self.assertEqual(translator.text("preview.source"), "AIモデル色")
        self.assertEqual(
            translator.text("preview.columns"),
            "元画像  ｜  AIモデル色  ｜  Full Spectrum変換色",
        )
        translator.set_language("en")
        self.assertEqual(translator.text("preview.source"), "AI Model Color")
        self.assertEqual(
            translator.text("preview.columns"),
            "Reference  |  AI Model Color  |  Full Spectrum Color",
        )

    def test_freehand_feature_keys_are_ready_for_geometry_ui(self) -> None:
        translator = Translator("en")
        self.assertEqual(
            translator.text("separate.freehand"), "Freehand Separation"
        )
        self.assertIn(
            "preserving its colors",
            translator.text("separate.floating_help"),
        )
        self.assertEqual(
            translator.text("separate.finish"),
            "Create Part from Enclosed Region",
        )
        self.assertIn("preserving color", translator.text("separate.help"))
        confirmation = translator.text(
            "separate.confirm_message",
            source="Cape",
            faces=1234,
            new_name="Pendant",
            coverage=98.5,
        )
        self.assertIn("1,234 faces", confirmation)
        self.assertIn("98.5%", confirmation)

    def test_freehand_errors_are_localized_without_changing_cli_text(self) -> None:
        from spectrum_mapper.freehand_split import FreehandSplitError

        error = FreehandSplitError(
            "フリーハンド領域は3点以上で囲んでください",
            "separate.error.too_few_points",
        )
        self.assertIn("3点以上", str(error))
        self.assertEqual(
            error.localized(Translator("en")),
            "Draw at least three points to enclose the region.",
        )

    def test_progress_fallback_is_localized_at_display_time(self) -> None:
        english = Translator("en")
        self.assertEqual(
            english.progress_text("scan", "OBJ構造確認: 12,345行"),
            "Checking model structure…",
        )
        self.assertEqual(
            english.progress_text("parse", "GLB/glTF読込完了"),
            "Loading model…",
        )
        self.assertEqual(
            english.progress_text("scan", "Checking source structure: 10"),
            "Checking source structure: 10",
        )

        japanese = Translator("ja")
        self.assertEqual(
            japanese.progress_text(
                "color_depth_geometry", "ColorDepth physical partition"
            ),
            "ColorDepth形状を生成しています…",
        )
        self.assertEqual(
            japanese.progress_text("preview", "プレビュー 2/4: 8,000面"),
            "プレビュー 2/4: 8,000面",
        )
        self.assertEqual(
            english.progress_text("unknown", "未登録の処理"),
            "Processing…",
        )

    def test_unknown_worker_status_does_not_leak_japanese_into_english(self) -> None:
        english = Translator("en")
        self.assertEqual(english.status_text("未登録の更新"), "Updated")
        self.assertEqual(
            english.status_text(
                "未登録のエラー", fallback_key="state.error_reason"
            ),
            "Review the error details",
        )

    def test_dialog_detail_preserves_original_japanese_for_japanese_ui(self) -> None:
        detail = ValueError("高さは正数で指定してください")

        self.assertEqual(
            Translator("ja").dialog_detail_text(detail),
            "高さは正数で指定してください",
        )

    def test_dialog_detail_replaces_unknown_japanese_for_english_ui(self) -> None:
        english = Translator("en")
        reason = english.dialog_detail_text(ValueError("高さが不正です"))
        traceback_detail = english.dialog_detail_text(
            "Traceback (most recent call last):\nValueError: 高さが不正です",
            fallback_key="dialog.technical_details_unavailable",
        )

        self.assertEqual(reason, "Review the error details")
        self.assertEqual(
            traceback_detail,
            "Additional technical details are unavailable in English.",
        )
        self.assertNotRegex(reason + traceback_detail, r"[ぁ-んァ-ヶ一-龯]")

    def test_dialog_detail_keeps_english_and_translates_known_catalog_copy(self) -> None:
        english = Translator("en")

        self.assertEqual(
            english.dialog_detail_text("The selected file is not valid."),
            "The selected file is not valid.",
        )
        self.assertEqual(
            english.dialog_detail_text(CATALOG["state.error_reason"]["ja"]),
            CATALOG["state.error_reason"]["en"],
        )

    def test_critical_completion_and_warning_copy_is_english(self) -> None:
        english = Translator("en")
        critical_keys = (
            "export.done_title",
            "export.done_status",
            "export.done_status_warning",
            "export.done_instructions",
            "export.self_intersection_warning",
            "export.part_palette_conflict.title",
            "export.part_palette_conflict.message",
            "paint.cleanup_warning.title",
            "paint.cleanup_warning.message",
            "paint.auto_shading_error_title",
            "dialog.processing_failed.title",
            "dialog.processing_failed.message",
        )
        for key in critical_keys:
            with self.subTest(key=key):
                self.assertNotRegex(CATALOG[key]["en"], r"[ぁ-んァ-ヶ一-龯]")

    def test_recommendation_and_reference_sample_copy_is_english(self) -> None:
        english = Translator("en")
        rendered = (
            english.text("parts.print_one_job"),
            english.text("parts.print_multiple_groups", count=2),
            english.text("parts.settings_invalid", reason="Invalid palette"),
            english.text("parts.editing_target", target="Arm"),
            english.text("parts.whole_model"),
            english.text(
                "palette.recommendation_summary",
                names="Black / White / Red / Blue",
                mean=4.2,
                coverage=87.0,
                confidence=91.0,
                material_metric="Material PLA",
                reference_note="Reference matched",
            ),
            english.text(
                "palette.recommendation_status_parts_common",
                count=3,
            ),
            english.text("palette.recommendation_status_count", count=1),
            english.text("palette.recommendation_status_automatic_suffix"),
            english.text("palette.reference_none"),
            english.text("palette.reference_low_confidence"),
            english.text("palette.reference_foreground_used"),
            english.text("palette.reference_selected_not_visible", iou=42.0),
            english.text(
                "palette.reference_matched",
                matched=2,
                requested=3,
                iou=78.0,
                mirrored=english.text("palette.reference_mirrored_suffix"),
            ),
            english.text("palette.reference_weak", iou=25.0),
            english.text("palette.reference_unsupported_part"),
            english.text(
                "recipe.direct_match",
                slot="F2",
                delta=3.5,
                quality=english.text("recipe.close"),
            ),
            english.text(
                "paint.reference_best_mix",
                a="F1",
                b="F4",
                ratio_a=50,
                ratio_b=50,
                predicted="#804020",
                delta=2.5,
            ),
            english.text(
                "paint.reference_sample_result",
                sample="#804020",
                state=7,
                name="F1+F4",
                delta=2.5,
                recipe="Best theoretical mix",
            ),
        )
        for text in rendered:
            with self.subTest(text=text):
                self.assertNotRegex(text, r"[ぁ-んァ-ヶ一-龯]")
                self.assertNotRegex(text, r"\{[^{}]+\}")

    def test_progress_queue_uses_the_current_interface_language(self) -> None:
        from spectrum_mapper.gui import MapperApp

        class Variable:
            value = ""

            def set(self, value):
                self.value = str(value)

        app = MapperApp.__new__(MapperApp)
        app.poll_after_id = "pending"
        app.work_queue = queue.Queue()
        app.work_queue.put(
            ("progress", ("3mf", 0.4, "Snapmaker Orca用3MFを書き出しています"))
        )
        app.progress = {}
        app.status_var = Variable()
        app.i18n = Translator("en")
        app.app_closing = True

        app._poll_queue()

        self.assertEqual(app.progress["value"], 40.0)
        self.assertEqual(
            app.status_var.value,
            "Writing the Snapmaker Orca 3MF…",
        )

    def test_public_dialogs_have_no_literal_japanese_copy(self) -> None:
        root = Path(__file__).resolve().parent
        for relative_path in (
            "spectrum_mapper/gui.py",
            "spectrum_mapper/paint_gui.py",
            "spectrum_mapper/filament_candidate_gui.py",
            "smooth_paint_hotfix.py",
            "spectrum_mapper_hotfix.py",
        ):
            path = root / relative_path
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                function_owner = (
                    node.func.value.id
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    else None
                )
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and function_owner
                    in {"messagebox", "filedialog", "colorchooser"}
                ):
                    continue
                literals = [
                    value.value
                    for value in ast.walk(node)
                    if isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and re.search(r"[ぁ-んァ-ヶ一-龯]", value.value)
                ]
                self.assertEqual(
                    literals,
                    [],
                    f"{relative_path}:{node.lineno} has untranslated dialog copy",
                )

    def test_public_status_results_have_no_literal_japanese_copy(self) -> None:
        root = Path(__file__).resolve().parent
        for relative_path in (
            "spectrum_mapper/gui.py",
            "spectrum_mapper/paint_gui.py",
            "smooth_paint_hotfix.py",
        ):
            path = root / relative_path
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                function_name = None
                if isinstance(node, ast.Call) and isinstance(
                    node.func, ast.Attribute
                ):
                    function_name = node.func.attr
                if function_name == "set":
                    owner = node.func.value
                    if not (
                        isinstance(owner, ast.Attribute)
                        and owner.attr.endswith("status_var")
                    ):
                        continue
                elif function_name not in {
                    "_worker_snapshot",
                    "_worker_refresh_after_edit",
                    "auto_shading_snapshot",
                }:
                    continue
                literals = [
                    value.value
                    for value in ast.walk(node)
                    if isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and re.search(r"[ぁ-んァ-ヶ一-龯]", value.value)
                ]
                self.assertEqual(
                    literals,
                    [],
                    f"{relative_path}:{node.lineno} has untranslated status copy",
                )

    def test_public_ui_text_sinks_reject_variable_mediated_japanese(self) -> None:
        root = Path(__file__).resolve().parent
        japanese_pattern = re.compile(r"[ぁ-んァ-ヶ一-龯]")
        for relative_path in (
            "spectrum_mapper/gui.py",
            "spectrum_mapper/paint_gui.py",
            "smooth_paint_hotfix.py",
        ):
            path = root / relative_path
            tree = ast.parse(path.read_text(encoding="utf-8"))
            scopes = [
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            for scope in scopes:
                japanese_names: dict[str, int] = {}
                for node in ast.walk(scope):
                    if not isinstance(
                        node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)
                    ):
                        continue
                    value = node.value
                    if not any(
                        isinstance(literal, ast.Constant)
                        and isinstance(literal.value, str)
                        and japanese_pattern.search(literal.value)
                        for literal in ast.walk(value)
                    ):
                        continue
                    targets = (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                    for target in targets:
                        if isinstance(target, ast.Name):
                            japanese_names[target.id] = node.lineno

                for node in ast.walk(scope):
                    if not (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                    ):
                        continue
                    owner = node.func.value
                    values: list[ast.AST] = []
                    if (
                        node.func.attr == "set"
                        and isinstance(owner, ast.Attribute)
                        and owner.attr.endswith("_var")
                    ):
                        values.extend(node.args)
                    elif node.func.attr in {"configure", "config"}:
                        values.extend(
                            keyword.value
                            for keyword in node.keywords
                            if keyword.arg == "text"
                        )
                    if not values:
                        continue
                    direct_literals = [
                        literal.value
                        for value in values
                        for literal in ast.walk(value)
                        if isinstance(literal, ast.Constant)
                        and isinstance(literal.value, str)
                        and japanese_pattern.search(literal.value)
                    ]
                    referenced_names = {
                        value.id
                        for expression in values
                        for value in ast.walk(expression)
                        if isinstance(value, ast.Name)
                    }
                    indirect = sorted(referenced_names & japanese_names.keys())
                    self.assertEqual(
                        direct_literals,
                        [],
                        f"{relative_path}:{node.lineno} has untranslated UI copy",
                    )
                    self.assertEqual(
                        indirect,
                        [],
                        (
                            f"{relative_path}:{node.lineno} uses Japanese variables "
                            + ", ".join(
                                f"{name}@{japanese_names[name]}" for name in indirect
                            )
                        ),
                    )


class LanguagePreferenceTests(unittest.TestCase):
    def test_saved_language_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ui_preferences.json"
            save_language("en", path)
            self.assertEqual(load_language(path), "en")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["language"], "en")

    def test_environment_overrides_saved_language(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ui_preferences.json"
            save_language("ja", path)
            with patch.dict(os.environ, {"TRIPO_SPECTRUM_LANGUAGE": "en-US"}):
                self.assertEqual(load_language(path), "en")

    def test_first_run_uses_os_locale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.json"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("spectrum_mapper.i18n.locale.getlocale", return_value=("ja_JP", "UTF-8")),
            ):
                self.assertEqual(load_language(missing), "ja")
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("spectrum_mapper.i18n.locale.getlocale", return_value=("de_DE", "UTF-8")),
            ):
                self.assertEqual(load_language(missing), "en")


class LiveGuiLanguageTests(unittest.TestCase):
    def test_main_ui_switches_without_rebuilding_or_losing_values(self) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        app = None
        try:
            from spectrum_mapper.gui import MapperApp

            with (
                patch.object(
                    MapperApp,
                    "_load_persistent_settings",
                    return_value=AppSettings(),
                ),
                patch("spectrum_mapper.gui.load_language", return_value="ja"),
                patch("spectrum_mapper.gui.save_language") as save_mock,
                patch.object(MapperApp, "_save_persistent_settings"),
            ):
                app = MapperApp(root)
                root.update_idletasks()
                original_entry = app.physical_vars[0].get()

                app.set_language("en")
                root.update_idletasks()
                self.assertEqual(app.language_var.get(), "English")
                self.assertEqual(app.export_button.cget("text"), "Export 3MF")
                self.assertEqual(app.manual_edit_button.cget("text"), "Manual Editing")
                self.assertEqual(app.physical_vars[0].get(), original_entry)
                save_mock.assert_called_with("en")

                self.assertEqual(
                    tuple(
                        app.main_ribbon_tab_buttons[name].cget("text")
                        for name in ("filament",)
                    ),
                    ("Filament Settings",),
                )
                self.assertEqual(app.output_settings_button.cget("text"), "Output Settings")
                self.assertEqual(app.output_settings_window.title(), "Output Settings")
                self.assertEqual(app.close_parts_safely_button.cget("text"), "Solidify")
                self.assertEqual(
                    app.extended_palette_checkbutton.cget("text"),
                    "Use the shown mixes for automatic mapping",
                )
                self.assertEqual(app.language_label.cget("text"), "言語")
                self.assertEqual(
                    app.developer_features_enable_checkbutton.cget("text"),
                    "Show Developer Experimental Features",
                )
                self.assertEqual(app.part_target_var.get(), "Common to All")

                app.set_language("ja", persist=False)
                root.update_idletasks()
                self.assertEqual(app.export_button.cget("text"), "3MFを書き出す")
                self.assertEqual(app.manual_edit_button.cget("text"), "マニュアル修正")
                self.assertEqual(app.output_settings_button.cget("text"), "出力設定")
                self.assertEqual(app.output_settings_window.title(), "出力設定")
                self.assertEqual(
                    app.extended_palette_checkbutton.cget("text"),
                    "表示中の混色を自動割当に使う",
                )
                self.assertEqual(app.language_label.cget("text"), "Language")
                self.assertEqual(
                    app.developer_features_enable_checkbutton.cget("text"),
                    "開発者向け実験機能を表示",
                )
                self.assertEqual(app.part_target_var.get(), "全体共通")
        finally:
            if app is not None:
                with patch.object(type(app), "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()

    @staticmethod
    def _descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from LiveGuiLanguageTests._descendants(child)


if __name__ == "__main__":
    unittest.main(verbosity=2)
