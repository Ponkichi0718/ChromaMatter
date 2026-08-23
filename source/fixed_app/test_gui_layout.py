from __future__ import annotations

import gc
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import (
    APP_DISPLAY_NAME,
    APP_NAME,
    APP_TAGLINE,
    EDITION_LABEL,
    RELEASE_REVISION,
    VERSION_PINNED_UNTIL_USER_REQUEST,
    __version__,
)
from spectrum_mapper.gui import APP_TITLE, MapperApp, _geometry_key
from spectrum_mapper.models import AppSettings
from test_manual_joints import _prepared_pair
from test_part_integration import two_part_prepared


class MainGuiLayoutTests(unittest.TestCase):
    def tearDown(self) -> None:
        # Tk variables participate in widget/callback reference cycles.  Make
        # their finalizers run on this UI thread before a later test starts a
        # worker; otherwise Python may first collect them inside that worker.
        gc.collect()

    def test_public_identity_and_version_are_user_pinned(self) -> None:
        self.assertEqual(APP_NAME, "ChromaMatter")
        self.assertEqual(APP_TAGLINE, "AI Model Print Studio")
        self.assertEqual(
            APP_DISPLAY_NAME,
            "ChromaMatter — AI Model Print Studio",
        )
        self.assertEqual(__version__, "0.8beta")
        self.assertEqual(RELEASE_REVISION, "r32")
        self.assertEqual(EDITION_LABEL, "AI Model Print Studio r32")
        self.assertEqual(
            APP_TITLE,
            "ChromaMatter — AI Model Print Studio 0.8beta (r32)",
        )
        self.assertTrue(VERSION_PINNED_UNTIL_USER_REQUEST)

    def test_missing_brand_asset_falls_back_to_text_title(self) -> None:
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
                patch(
                    "spectrum_mapper.gui.resource_path",
                    return_value=Path("C:/missing/obj_adjuster_icon.png"),
                ),
            ):
                app = MapperApp(root)
                root.update_idletasks()
                self.assertIsNone(app.brand_logo_image)
                self.assertIsNone(app.window_icon_image)
                self.assertIsNone(app.brand_logo_label)
                self.assertEqual(app.brand_title_label.cget("text"), "ChromaMatter")
                self.assertEqual(
                    app.brand_tagline_label.cget("text"),
                    "AI Model Print Studio",
                )
        finally:
            if app is not None:
                with patch.object(MapperApp, "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()

    def test_manual_solidify_waits_for_editor_commit_and_reuses_safe_action(
        self,
    ) -> None:
        app = MapperApp.__new__(MapperApp)
        events: list[str] = []

        class PendingEditor:
            after_close = None

            def close(self, *, after_close=None) -> None:
                events.append("close requested")
                self.after_close = after_close

        editor = PendingEditor()
        app.paint_editor = editor

        def safe_solidify() -> None:
            self.assertIsNone(app.paint_editor)
            events.append("safe solidify")

        app._solidify_parts_now = safe_solidify
        MapperApp._solidify_parts_from_paint_editor(app)

        self.assertEqual(events, ["close requested"])
        self.assertIs(app.paint_editor, editor)
        self.assertIsNotNone(editor.after_close)

        editor.after_close()
        self.assertEqual(events, ["close requested", "safe solidify"])
        self.assertIsNone(app.paint_editor)

    def test_manual_solidify_without_live_editor_uses_safe_action_directly(
        self,
    ) -> None:
        app = MapperApp.__new__(MapperApp)
        app.paint_editor = None
        safe_solidify = patch.object(app, "_solidify_parts_now")
        with safe_solidify as action:
            MapperApp._solidify_parts_from_paint_editor(app)
        action.assert_called_once_with()

    def test_combined_close_action_routes_from_boundary_diagnostics(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app.obj_path = Path("C:/models/parts.obj")
        app._solidify_parts_now = patch.object(
            MapperApp, "_solidify_parts_now"
        ).start()
        self.addCleanup(patch.stopall)
        app._repair_small_boundaries_and_solidify = patch.object(
            MapperApp, "_repair_small_boundaries_and_solidify"
        ).start()

        app.prepared = SimpleNamespace(
            assembly={"unmatched_boundary_loop_count": 0}
        )
        MapperApp._close_parts_safely(app)
        app._solidify_parts_now.assert_called_once_with()
        app._repair_small_boundaries_and_solidify.assert_not_called()

        app._solidify_parts_now.reset_mock()
        app.prepared = SimpleNamespace(
            assembly={"unmatched_boundary_loop_count": 2}
        )
        MapperApp._close_parts_safely(app)
        app._repair_small_boundaries_and_solidify.assert_called_once_with()
        app._solidify_parts_now.assert_not_called()

    def test_single_glb_without_tripo_parts_uses_generic_solidify_route(
        self,
    ) -> None:
        app = MapperApp.__new__(MapperApp)
        app.source_path = Path("C:/models/hi3d-single.glb")
        app.asset = object()
        app.prepared = SimpleNamespace(
            assembly={},
            topology={"watertight": False},
        )
        app.solidify_parts_var = Mock()
        app.repair_unmatched_boundaries_var = Mock()
        app._process_geometry = Mock(return_value=True)

        MapperApp._solidify_parts_now(app)

        app.solidify_parts_var.set.assert_called_once_with(True)
        app.repair_unmatched_boundaries_var.set.assert_called_once_with(False)
        app._process_geometry.assert_called_once_with(reuse_asset=True)

    def test_single_glb_closed_status_explains_uv_seam_weld(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app.i18n = Mock()
        app.i18n.text.return_value = "GLB seam status"
        app.assembly_status_var = Mock()
        app.prepared = SimpleNamespace(
            assembly={
                "single_mesh_generic": True,
                "all_parts_watertight": True,
            }
        )

        MapperApp._update_assembly_status(app)

        app.i18n.text.assert_called_once_with(
            "assembly.status_closed_single_glb"
        )
        app.assembly_status_var.set.assert_called_once_with("GLB seam status")

    def test_main_ribbon_preserves_controls_and_split_stays_off(self) -> None:
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
            with (
                patch.object(
                    MapperApp,
                    "_load_persistent_settings",
                    return_value=AppSettings(),
                ),
                patch("spectrum_mapper.gui.load_language", return_value="ja"),
                patch.object(MapperApp, "_save_persistent_settings"),
            ):
                app = MapperApp(root)
                root.update_idletasks()

                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)

                def publicly_managed(widget):
                    current = widget
                    while current is not root:
                        if (
                            not current.winfo_manager()
                            and current not in tab_widgets.values()
                        ):
                            return False
                        current = current.master
                    return True

                tab_widgets = app.main_ribbon_pages
                self.assertEqual(
                    tuple(tab_widgets),
                    ("filament", "output"),
                )
                self.assertEqual(
                    tuple(
                        app.main_ribbon_tab_buttons[name].cget("text")
                        for name in tab_widgets
                    ),
                    ("フィラメント設定", "出力設定"),
                )
                self.assertEqual(app.main_ribbon_body.winfo_manager(), "grid")

                # Laboratory implementations remain in source but neither the
                # gate nor any experimental group enters the public layout.
                self.assertEqual(
                    app.developer_features_enable_checkbutton.winfo_manager(),
                    "",
                )
                for group in (
                    app.black_free_gradient_group,
                    app.surface_shell_group,
                    app.color_depth_group,
                ):
                    self.assertEqual(group.winfo_manager(), "")
                app.color_depth_enabled_var.set(True)
                app.color_depth_outer_thickness_var.set(0.37)
                app.developer_features_enabled_var.set(True)
                app._on_developer_features_toggle()
                root.update_idletasks()
                self.assertEqual(app.surface_shell_group.winfo_manager(), "")
                self.assertEqual(app.color_depth_group.winfo_manager(), "")
                self.assertTrue(
                    app.developer_features_enable_checkbutton.instate(
                        ["disabled"]
                    )
                )
                sanitized = app._variables_to_settings()
                self.assertIsNotNone(sanitized)
                self.assertFalse(sanitized.color_depth.experimental_enabled)
                self.assertFalse(sanitized.geometry.auto_joints)

                app._toggle_main_ribbon()
                self.assertEqual(app.main_ribbon_body.winfo_manager(), "")
                app._on_main_ribbon_tab_clicked("output")
                self.assertEqual(app._main_ribbon_selected, "output")
                self.assertTrue(app._main_ribbon_expanded)
                self.assertEqual(app.main_ribbon_body.winfo_manager(), "grid")

                toolbar_text = []
                comboboxes = []
                for widget in descendants(root):
                    if isinstance(widget, ttk.Combobox):
                        comboboxes.append(widget)
                    try:
                        toolbar_text.append(str(widget.cget("text")))
                    except tk.TclError:
                        pass
                self.assertIn("ChromaMatter", toolbar_text)
                self.assertIn("AI Model Print Studio", toolbar_text)
                self.assertEqual(app.brand_title_label.cget("text"), "ChromaMatter")
                self.assertEqual(
                    app.brand_tagline_label.cget("text"),
                    "AI Model Print Studio",
                )
                self.assertIsNotNone(app.brand_logo_image)
                self.assertIsNotNone(app.window_icon_image)
                self.assertIsNotNone(app.brand_logo_label)
                self.assertTrue(app.brand_logo_label.cget("image"))
                self.assertFalse(
                    root.tk.getboolean(app.brand_logo_label.cget("takefocus"))
                )
                self.assertFalse(
                    root.tk.getboolean(app.brand_title_label.cget("takefocus"))
                )
                self.assertFalse(
                    root.tk.getboolean(app.brand_tagline_label.cget("takefocus"))
                )
                title_font = str(
                    ttk.Style(root).lookup("Title.TLabel", "font")
                )
                self.assertIn("16", title_font)
                self.assertIn("bold", title_font.lower())
                self.assertIn("マニュアル修正", toolbar_text)
                self.assertNotIn("Snapmaker Orca起動", toolbar_text)
                self.assertEqual(app.help_button.winfo_manager(), "")
                self.assertEqual(app.main_ribbon_help_button.winfo_manager(), "")
                self.assertEqual(app.language_label.cget("text"), "Language")
                self.assertGreaterEqual(len(comboboxes), 3)
                self.assertTrue(
                    all(
                        str(widget.cget("style")) == "HighContrast.TCombobox"
                        for widget in comboboxes
                    )
                )
                style = ttk.Style(root)
                self.assertEqual(
                    style.lookup(
                        "HighContrast.TCombobox", "foreground", ("readonly",)
                    ).lower(),
                    "#ffffff",
                )
                self.assertEqual(
                    style.lookup(
                        "HighContrast.TCombobox", "foreground", ("disabled",)
                    ).lower(),
                    "#d5dce5",
                )

                direct_buttons = tuple(app.physical_eyedropper_buttons)
                self.assertEqual(len(direct_buttons), 4)
                self.assertEqual(
                    tuple(button.cget("text") for button in direct_buttons),
                    ("画像から",) * 4,
                )
                self.assertEqual(
                    app.eyedropper_button.cget("text"), "混色候補用スポイト"
                )

                # A base-filament button directly arms one reference click;
                # the generic recipe eyedropper is not part of this path.
                app.reference_image = Image.new("RGB", (5, 5), (12, 34, 56))
                with patch.object(app, "_toggle_eyedropper") as generic_toggle:
                    direct_buttons[2].invoke()
                    generic_toggle.assert_not_called()
                self.assertTrue(app.eyedropper_active)
                self.assertEqual(app.physical_eyedropper_target, 2)
                app.reference_mapping = (10, 20, 50, 50, 5, 5)

                # An outside click keeps the requested base slot armed and
                # tells the user which slot is still waiting for a sample.
                app._on_canvas_click(SimpleNamespace(x=5, y=5))
                self.assertTrue(app.eyedropper_active)
                self.assertEqual(app.physical_eyedropper_target, 2)
                self.assertIn("F3", app.status_var.get())

                # Language changes preserve that pending target and localize
                # both the status and the stop control.
                app.set_language("en", persist=False)
                self.assertEqual(app.physical_eyedropper_target, 2)
                self.assertEqual(app.eyedropper_button.cget("text"), "Stop Eyedropper")
                self.assertIn("F3", app.status_var.get())
                app.set_language("ja", persist=False)
                app.reference_mapping = (10, 20, 50, 50, 5, 5)
                app._on_canvas_click(SimpleNamespace(x=35, y=45))
                self.assertEqual(app.physical_vars[2].get(), "#0C2238")
                self.assertTrue(app.enabled_vars[2].get())
                self.assertFalse(app.eyedropper_active)
                self.assertIsNone(app.physical_eyedropper_target)
                self.assertIn("F3", app.status_var.get())

                app.set_language("en", persist=False)
                self.assertEqual(app.language_label.cget("text"), "言語")
                self.assertEqual(
                    app.reprocess_geometry_button.cget("text"),
                    "Reprocess Geometry with These Settings",
                )
                self.assertEqual(
                    app.close_parts_safely_button.cget("text"),
                    "Solidify",
                )
                self.assertEqual(
                    tuple(button.cget("text") for button in direct_buttons),
                    ("From Image",) * 4,
                )
                self.assertEqual(
                    app.eyedropper_button.cget("text"), "Sample for Mix Recipes"
                )
                app.set_language("ja", persist=False)

                # Generic and direct sampling are mutually exclusive.  A new
                # OBJ selection cancels either mode before replacing inputs.
                direct_buttons[0].invoke()
                app._toggle_eyedropper()
                self.assertFalse(app.eyedropper_active)
                self.assertIsNone(app.physical_eyedropper_target)
                app._toggle_eyedropper()
                direct_buttons[1].invoke()
                self.assertEqual(app.physical_eyedropper_target, 1)
                app.solidify_parts_var.set(True)
                app.repair_unmatched_boundaries_var.set(True)
                app.auto_joints_var.set(True)
                with (
                    patch(
                        "spectrum_mapper.gui.filedialog.askopenfilename",
                        return_value="C:/synthetic/new.obj",
                    ),
                    patch.object(app, "_process_geometry") as process_geometry,
                ):
                    app._choose_obj()
                process_geometry.assert_called_once_with(reuse_asset=False)
                self.assertFalse(app.eyedropper_active)
                self.assertIsNone(app.physical_eyedropper_target)
                self.assertFalse(app.solidify_parts_var.get())
                self.assertFalse(app.repair_unmatched_boundaries_var.get())
                self.assertFalse(app.auto_joints_var.get())
                self.assertFalse(app.adjust_face_count_var.get())
                self.assertIn("原形状の面数を保持", app.face_count_status_var.get())

                target_text = "陰影を混色に反映（自動最適化）"
                optimizer_tabs: list[str] = []
                all_widget_text: list[str] = []
                for tab_name, tab in tab_widgets.items():
                    for widget in descendants(tab):
                        if not publicly_managed(widget):
                            continue
                        try:
                            text = str(widget.cget("text"))
                        except tk.TclError:
                            continue
                        all_widget_text.append(text)
                        if text == target_text:
                            optimizer_tabs.append(tab_name)

                # Global tone logic remains available to Manual Editing, but
                # the old main-screen Shading page is no longer exposed.
                self.assertEqual(optimizer_tabs, [])
                self.assertFalse(
                    any("平面2分割" in text for text in all_widget_text)
                )
                filament_text = "\n".join(
                    str(widget.cget("text"))
                    for widget in descendants(tab_widgets["filament"])
                    if "text" in widget.keys() and publicly_managed(widget)
                )
                self.assertIn("編集対象", filament_text)
                self.assertIn("パーツ名", filament_text)
                self.assertIn("選択パーツを自動提案", filament_text)
                self.assertIn("基本フィラメント4色", filament_text)
                self.assertIn("混色パレット", filament_text)
                self.assertIn("混色を含む色数", filament_text)
                self.assertIn("モデル読込後にパーツを表示", filament_text)
                self.assertNotIn("基本4色を初期値へ戻す", filament_text)
                self.assertNotIn(
                    "OBJの元のパーツ構成と配置は変えず",
                    filament_text,
                )
                self.assertNotIn("主混色", filament_text)
                self.assertNotIn("追加混色", filament_text)
                self.assertNotIn("黒なしグラデーション", filament_text)
                self.assertNotIn("開発者向け実験機能", filament_text)
                before_ratios = (
                    [variable.get() for variable in app.mix_ratio_vars],
                    [
                        variable.get()
                        for variable in app.secondary_mix_ratio_vars
                    ],
                )
                app.palette_state_count_var.set(32)
                app._layout_mix_family_cells()
                self.assertEqual(
                    app.mix_display_state_indices[:5],
                    (22, 4, 16, 10, 23),
                )
                self.assertEqual(
                    [
                        app.mix_state_number_labels[state].cget("text")
                        for state in app.mix_display_state_indices
                    ],
                    [f"{number:02d}" for number in range(1, 29)],
                )
                self.assertEqual(
                    (
                        [variable.get() for variable in app.mix_ratio_vars],
                        [
                            variable.get()
                            for variable in app.secondary_mix_ratio_vars
                        ],
                    ),
                    before_ratios,
                )
                self.assertIs(app.black_output_group.master, app.mixed_palette_group)
                self.assertEqual(app.black_output_group.cget("text"), "実機黒補正")
                self.assertEqual(
                    app.black_output_preset_button.grid_info()["sticky"],
                    "w",
                )
                self.assertEqual(
                    int(app.black_output_preset_button.cget("width")),
                    8,
                )
                assembly_text = "\n".join(
                    str(widget.cget("text"))
                    for widget in descendants(tab_widgets["output"])
                    if "text" in widget.keys() and publicly_managed(widget)
                )
                self.assertIn("出力高さ mm", assembly_text)
                self.assertNotIn("面数調整を適用", assembly_text)
                self.assertNotIn("元の面数へ戻す", assembly_text)
                self.assertIn("この設定で形状を再処理", assembly_text)
                self.assertFalse(hasattr(app, "apply_face_count_button"))
                self.assertFalse(hasattr(app, "restore_original_faces_button"))
                self.assertIn("元のパーツ構成と色を保って開きます", assembly_text)
                self.assertNotIn("Tripoのパーツ情報があるOBJ", assembly_text)
                self.assertNotIn("パーツ情報がないOBJは分割せず", assembly_text)
                self.assertLessEqual(
                    app.i18n.text("assembly.intro").count("\n"),
                    1,
                )
                self.assertIn("閉立体化", assembly_text)
                self.assertNotIn("問題を確認して閉じる", assembly_text)
                self.assertNotIn("開口境界を3Dで確認", assembly_text)
                self.assertNotIn("パーツを閉立体化", assembly_text)
                self.assertNotIn("微小な問題境界を修復して閉じる β", assembly_text)
                self.assertNotIn("安全な継ぎ目だけ", assembly_text)
                self.assertNotIn("手動ジョイントを解除", assembly_text)
                self.assertEqual(app.preview_canvas.grid_info()["row"], 0)

                # The single public reprocess action deliberately combines
                # face-count application with the ordinary geometry rebuild.
                # Hidden legacy state remains reversible if processing does
                # not start, while a successful click enables the target.
                app.adjust_face_count_var.set(False)
                app.obj_path = Path("C:/synthetic/model.obj")
                app.asset = SimpleNamespace(original_face_count=1234)
                with patch.object(
                    app,
                    "_process_geometry",
                    return_value=True,
                ) as process_geometry:
                    app.reprocess_geometry_button.invoke()
                process_geometry.assert_called_once_with(reuse_asset=True)
                self.assertTrue(app.adjust_face_count_var.get())

                # A stale UI variable or old project must not reactivate the
                # removed ordinary plane-split operation.
                app.split_enabled_var.set(True)
                migrated = app._variables_to_settings()
                self.assertIsNotNone(migrated)
                self.assertFalse(migrated.geometry.split_enabled)
        finally:
            if app is not None:
                with patch.object(MapperApp, "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()

    def test_main_ribbon_rename_preserves_stable_part_key(self) -> None:
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
            ):
                app = MapperApp(root)
                prepared = two_part_prepared()
                app.prepared = prepared
                original_keys = tuple(prepared.final.part_keys)
                selected_key = original_keys[1]

                app._refresh_part_selector()
                app._select_part_key(selected_key)
                self.assertEqual(str(app.main_part_name_entry.cget("state")), "normal")
                app.part_name_var.set("右腕テスト")
                app._rename_selected_part()

                self.assertEqual(tuple(prepared.final.part_keys), original_keys)
                self.assertEqual(tuple(prepared.preview.part_keys), original_keys)
                self.assertEqual(prepared.final.part_names[1], "右腕テスト")
                self.assertEqual(prepared.preview.part_names[1], "右腕テスト")
                self.assertEqual(app.settings.part_names[selected_key], "右腕テスト")
                self.assertIn("右腕テスト", app.part_target_var.get())
        finally:
            if app is not None:
                with patch.object(MapperApp, "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()

    def test_manual_joint_without_paint_blocks_stale_topology_project_save(self) -> None:
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
            ):
                app = MapperApp(root)
                prepared, _repair = _prepared_pair()
                current = app._variables_to_settings()
                self.assertIsNotNone(current)
                app.prepared = prepared
                app.prepared_key = _geometry_key(current.geometry)
                app.obj_path = prepared.source.path
                app.manual_overrides = None
                app.manual_joint_record = {
                    "model_height_mm": float(current.geometry.height_mm)
                }

                app.target_faces_var.set(int(current.geometry.target_faces) + 1000)
                with (
                    patch("spectrum_mapper.gui.messagebox.showwarning") as warning,
                    patch(
                        "spectrum_mapper.gui.filedialog.asksaveasfilename"
                    ) as save_dialog,
                ):
                    app._save_project()
                warning.assert_called_once()
                self.assertIn("形状設定", warning.call_args.args[0])
                save_dialog.assert_not_called()
        finally:
            if app is not None:
                with patch.object(MapperApp, "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()

    def test_open_mesh_auto_solidify_is_confirmed_before_3mf_save_dialog(self) -> None:
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
            ):
                app = MapperApp(root)
                prepared = two_part_prepared()
                current = app._variables_to_settings()
                self.assertIsNotNone(current)
                prepared.topology = {
                    "watertight": False,
                    "boundary_edges": 6,
                }
                prepared.assembly = {
                    "solidify_parts": False,
                    "unmatched_boundary_loop_count": 0,
                    "boundary_diagnostics": [],
                }
                prepared.source.has_explicit_parts = True
                app.prepared = prepared
                app.asset = prepared.source
                app.obj_path = prepared.source.path
                app.prepared_key = _geometry_key(current.geometry)

                with (
                    patch(
                        "spectrum_mapper.gui.messagebox.askyesno",
                        return_value=False,
                    ) as question,
                    patch(
                        "spectrum_mapper.gui.filedialog.asksaveasfilename"
                    ) as save_dialog,
                ):
                    app._export()

                question.assert_called_once()
                self.assertIn("未閉立体", question.call_args.args[0])
                save_dialog.assert_not_called()
        finally:
            if app is not None:
                with patch.object(MapperApp, "_save_persistent_settings"):
                    app._on_close()
            else:
                root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
