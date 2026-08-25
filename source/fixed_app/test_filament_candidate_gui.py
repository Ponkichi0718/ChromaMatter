from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.filament_candidate_gui import FilamentCandidateWindow
from spectrum_mapper.filament_database import FilamentProduct
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import (
    AppSettings,
    COLOR_MODE_FLAT_FOUR,
    COLOR_MODE_FULL_SPECTRUM,
    PaletteSettings,
)
from spectrum_mapper.owned_filaments import OwnedFilamentInventory


@dataclass(frozen=True)
class _Match:
    brand: str
    series: str
    color_name: str
    matched_hex: str
    delta_e_2000: float
    finish_class: str
    source_kind: str


class _Matcher:
    is_available = True
    error_message = None

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def available_brands(self):
        return ("Brand A", "Brand B")

    def available_finish_classes(self):
        return ("マット", "標準/不透明")

    def find_matches(self, target_hex, **kwargs):
        self.calls.append({"target_hex": target_hex, **kwargs})
        return tuple(
            _Match(
                brand=f"Brand {index + 1}",
                series="PLA Series",
                color_name=f"Color {index + 1}",
                matched_hex=("#112233", "#445566", "#778899")[index],
                delta_e_2000=1.25 + index,
                finish_class=(
                    "標準/不透明",
                    "マット",
                    "シルク/メタリック/光沢",
                )[index],
                source_kind="measured" if index == 0 else "catalog",
            )
            for index in range(int(kwargs["limit"]))
        )


class _UnavailableMatcher:
    is_available = False
    error_message = "test database is missing"

    def available_brands(self):
        raise AssertionError("unavailable matcher must not be queried")

    def available_finish_classes(self):
        raise AssertionError("unavailable matcher must not be queried")


def _products() -> tuple[FilamentProduct, ...]:
    values = (
        ("a-red", "Brand A", "Basic", "Red", "#E32B35", "標準/不透明"),
        ("a-white", "Brand A", "Basic", "White", "#F2F1ED", "標準/不透明"),
        ("b-blue", "Brand B", "PLA", "Blue", "#2255CC", "マット"),
        ("b-black", "Brand B", "PLA", "Black", "#161616", "標準/不透明"),
        ("b-yellow", "Brand B", "PLA", "Yellow", "#F1C52D", "標準/不透明"),
    )
    return tuple(
        FilamentProduct(
            product_id=product_id,
            brand=brand,
            series=series,
            color_name=name,
            matched_hex=color,
            finish_class=finish,
            source_kind="catalog",
            source_url=None,
            record_id=product_id,
            measurement_id=None,
            finish_penalty=0.0,
            catalog_status="active",
            data_confidence="medium",
        )
        for product_id, brand, series, name, color, finish in values
    )


class _ProductRepository:
    def __init__(self, products: tuple[FilamentProduct, ...]) -> None:
        self.products = products

    def list_products(self, *, prefer_measured=True):
        return self.products


class _ProductMatcher(_Matcher):
    def __init__(self, products: tuple[FilamentProduct, ...]) -> None:
        super().__init__()
        self.repository = _ProductRepository(products)

    def available_brands(self):
        return ("Brand A", "Brand B")


def _wait_for(root, predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    root.update()
    return bool(predicate())


class FilamentCandidateTranslationTests(unittest.TestCase):
    def test_beta_warning_and_actions_are_bilingual(self) -> None:
        translator = Translator("ja")
        self.assertEqual(
            translator.text("filament_candidates.button"),
            "フィラメント候補 β",
        )
        self.assertEqual(
            translator.text("filament_candidates.prefer_measured"),
            "同一製品は実測値を使用",
        )
        self.assertIn("在庫ありを保証しません", translator.text("filament_candidates.notice"))
        translator.set_language("en")
        self.assertEqual(
            translator.text("filament_candidates.button"),
            "Filament Candidates β",
        )
        self.assertEqual(
            translator.text("filament_candidates.prefer_measured"),
            "Use measured value for same product",
        )
        self.assertEqual(
            translator.text("filament_candidates.set_slot", slot="F4"),
            "Assign to F4",
        )
        self.assertIn("stock are not guaranteed", translator.text("filament_candidates.notice"))


class FilamentCandidateWindowTests(unittest.TestCase):
    def _create_app(self):
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        from spectrum_mapper.gui import MapperApp

        with (
            patch.object(MapperApp, "_load_persistent_settings", return_value=AppSettings()),
            patch("spectrum_mapper.gui.load_language", return_value="ja"),
            patch.object(MapperApp, "_save_persistent_settings"),
        ):
            app = MapperApp(root)
        return root, app

    def _close_app(self, root, app) -> None:
        from spectrum_mapper.gui import MapperApp

        if app is not None:
            with patch.object(MapperApp, "_save_persistent_settings"):
                app._on_close()
        else:
            root.destroy()

    def test_independent_window_shows_exactly_three_candidates_per_f_color(self) -> None:
        root, app = self._create_app()
        matcher = _Matcher()
        try:
            window = FilamentCandidateWindow(app, matcher=matcher)
            app.filament_candidate_window = window
            app.filament_candidate_button.invoke()
            self.assertTrue(
                _wait_for(
                    root,
                    lambda: len(matcher.calls) >= 4
                    and window._result_target_hexes is not None,
                ),
                "candidate search did not complete",
            )
            self.assertIs(window.window.master, root)
            self.assertEqual(window.window.wm_transient(), "")
            self.assertIsNone(window.window.grab_current())
            self.assertEqual(len(window.candidate_rows), 4)
            self.assertTrue(all(len(rows) == 3 for rows in window.candidate_rows))
            self.assertEqual(
                window.candidate_rows[0][0]["product"].cget("text"),
                "Brand 1 / PLA Series / Color 1",
            )
            self.assertEqual(
                window.candidate_rows[0][0]["source"].cget("text"),
                "実測",
            )
            self.assertEqual(
                tuple(window.brand_combo.cget("values")),
                ("すべて", "Brand A", "Brand B"),
            )
            self.assertEqual(
                tuple(window.finish_combo.cget("values")),
                ("すべて", "マット", "標準/不透明"),
            )
            self.assertIn("在庫ありを保証しません", window.notice_label.cget("text"))

            with (
                patch.object(
                    window.window,
                    "winfo_containing",
                    return_value=window.cards_host,
                ),
                patch.object(window.body_canvas, "yview_scroll") as scroll,
            ):
                result = window._on_mouse_wheel(
                    SimpleNamespace(x_root=300, y_root=400, delta=-120)
                )
            self.assertEqual(result, "break")
            scroll.assert_called_once_with(1, "units")

            # A palette/part change invalidates old ΔE rows immediately,
            # including during the search debounce interval.
            stale_match = window._last_results[0][0]
            app.physical_vars[0].set("#010203")
            self.assertEqual(
                str(window.candidate_rows[0][0]["apply"].cget("state")),
                "disabled",
            )
            with patch(
                "spectrum_mapper.filament_candidate_gui.messagebox.askyesno"
            ) as stale_confirm:
                window._confirm_apply(0, stale_match)
            stale_confirm.assert_not_called()
            self.assertEqual(app.physical_vars[0].get(), "#010203")
            calls_before_refresh = len(matcher.calls)
            self.assertTrue(
                _wait_for(
                    root,
                    lambda: len(matcher.calls) >= calls_before_refresh + 4
                    and window._result_target_hexes is not None
                    and window._result_target_hexes[0] == "#010203",
                )
            )

            calls_before_filter = len(matcher.calls)
            window.brand_var.set("Brand B")
            window._on_filter_changed()
            self.assertTrue(
                _wait_for(
                    root,
                    lambda: len(matcher.calls) >= calls_before_filter + 4
                    and window._result_target_hexes is not None,
                )
            )
            self.assertEqual(matcher.calls[-1]["brands"], ("Brand B",))

            match = window._last_results[1][0]
            original = app.physical_vars[1].get()
            with patch(
                "spectrum_mapper.filament_candidate_gui.messagebox.askyesno",
                return_value=False,
            ):
                window._confirm_apply(1, match)
            self.assertEqual(app.physical_vars[1].get(), original)
            with patch(
                "spectrum_mapper.filament_candidate_gui.messagebox.askyesno",
                return_value=True,
            ) as confirm:
                window._confirm_apply(1, match)
            confirm.assert_called_once()
            self.assertEqual(app.physical_vars[1].get(), "#112233")
            self.assertTrue(app.enabled_vars[1].get())
            self.assertTrue(
                _wait_for(
                    root,
                    lambda: window._result_target_hexes is not None
                    and window._result_target_hexes[1] == "#112233",
                )
            )

            app.set_language("en", persist=False)
            root.update_idletasks()
            self.assertEqual(window.window.title(), "Filament Candidates β")
            self.assertEqual(
                window.candidate_rows[0][0]["source"].cget("text"),
                "Measured",
            )
            self.assertEqual(
                window.candidate_rows[0][0]["finish"].cget("text"),
                "Standard / Opaque",
            )
            self.assertEqual(
                tuple(window.finish_combo.cget("values")),
                ("All", "Matte", "Standard / Opaque"),
            )
            self.assertEqual(window.brand_var.get(), "Brand B")
            calls_before_finish = len(matcher.calls)
            window.finish_var.set("Matte")
            window._on_filter_changed()
            self.assertTrue(
                _wait_for(
                    root,
                    lambda: len(matcher.calls) >= calls_before_finish + 4
                    and window._result_target_hexes is not None,
                )
            )
            self.assertEqual(matcher.calls[-1]["finish_classes"], ("マット",))
        finally:
            self._close_app(root, app)

    def test_f_slot_actions_fit_in_japanese_and_english_at_minimum_size(self) -> None:
        root, app = self._create_app()
        try:
            window = FilamentCandidateWindow(app, matcher=_ProductMatcher(_products()))
            app.filament_candidate_window = window
            window.show()
            self.assertTrue(
                _wait_for(root, lambda: bool(window.inventory_tree.get_children("")))
            )
            window.window.geometry("900x620")
            root.update_idletasks()

            for language, expected in (
                ("ja", tuple(f"選択製品をF{index}へ" for index in range(1, 5))),
                ("en", tuple(f"Assign to F{index}" for index in range(1, 5))),
            ):
                app.set_language(language, persist=False)
                root.update_idletasks()
                labels = tuple(
                    str(button.cget("text"))
                    for button in window.inventory_slot_buttons
                )
                self.assertEqual(labels, expected)
                self.assertTrue(
                    all(
                        button.winfo_width() >= button.winfo_reqwidth()
                        for button in window.inventory_slot_buttons
                    ),
                    f"{language} F-slot action label is clipped at 900x620",
                )
        finally:
            self._close_app(root, app)

    def test_missing_database_disables_only_candidate_controls(self) -> None:
        root, app = self._create_app()
        try:
            window = FilamentCandidateWindow(app, matcher=_UnavailableMatcher())
            app.filament_candidate_window = window
            window.show()
            self.assertTrue(
                _wait_for(
                    root,
                    lambda: "test database is missing" in window.status_var.get(),
                )
            )
            self.assertEqual(str(window.brand_combo.cget("state")), "disabled")
            self.assertEqual(str(window.finish_combo.cget("state")), "disabled")
            self.assertTrue(
                all(
                    str(row["apply"].cget("state")) == "disabled"
                    for rows in window.candidate_rows
                    for row in rows
                )
            )
            # The optional database does not disable or mutate the core app.
            self.assertEqual(str(app.physical_swatch_buttons[0].cget("state")), "normal")
            self.assertIsNotNone(app._variables_to_settings(show_error=False))
            app.set_language("en", persist=False)
            self.assertIn(
                "database is unavailable",
                window.status_var.get(),
            )
            self.assertIn("test database is missing", window.status_var.get())
        finally:
            self._close_app(root, app)

    def test_owned_inventory_is_grouped_persisted_and_can_set_an_f_slot(self) -> None:
        root, app = self._create_app()
        products = _products()
        matcher = _ProductMatcher(products)
        stored = {"inventory": OwnedFilamentInventory()}

        def load_inventory(**_kwargs):
            return stored["inventory"]

        def save_inventory(inventory, *_args, **_kwargs):
            stored["inventory"] = inventory
            return Path("owned_filaments.json")

        try:
            with (
                patch(
                    "spectrum_mapper.owned_filaments.load_owned_filament_inventory",
                    side_effect=load_inventory,
                ),
                patch(
                    "spectrum_mapper.owned_filaments.save_owned_filament_inventory",
                    side_effect=save_inventory,
                ),
            ):
                window = FilamentCandidateWindow(app, matcher=matcher)
                app.filament_candidate_window = window
                window.show()
                self.assertTrue(
                    _wait_for(root, lambda: len(window._all_products) == len(products))
                )

                # Only manufacturer rows (plus lazy placeholders) exist until
                # the user expands one; thousands of product rows are not
                # recreated after every color edit.
                brand_items = window.inventory_tree.get_children("")
                self.assertEqual(len(brand_items), 2)
                brand_a = next(
                    item
                    for item in brand_items
                    if window._inventory_item_to_brand[item] == "Brand A"
                )
                self.assertEqual(
                    tuple(window._inventory_brand_to_product_ids["Brand A"]),
                    ("a-red", "a-white"),
                )
                window.inventory_tree.selection_set(brand_a)
                window._set_inventory_selection_owned(True)
                self.assertEqual(
                    set(stored["inventory"].product_ids),
                    {"a-red", "a-white"},
                )

                window.inventory_tree.item(brand_a, open=True)
                window._populate_inventory_brand(brand_a)
                product_item = next(
                    item
                    for item, product_id in window._inventory_item_to_product_id.items()
                    if product_id == "a-red"
                )
                window.inventory_tree.selection_set(product_item)
                window._on_inventory_selection_changed()
                window._set_selected_product_to_slot(0)
                self.assertEqual(app.physical_vars[0].get(), "#E32B35")
                selected_ref = app.settings.palette.physical_filament_refs[0]
                self.assertIsNotNone(selected_ref)
                self.assertEqual(selected_ref.product_id, "a-red")
                self.assertIn("Brand A", window.current_labels[0].cget("text"))

                window.candidate_scope_var.set("owned")
                window._on_candidate_scope_changed()
                self.assertTrue(
                    _wait_for(
                        root,
                        lambda: window._result_target_hexes is not None
                        and window.candidate_scope_var.get() == "owned",
                    )
                )
                self.assertTrue(
                    all(
                        match.brand == "Brand A"
                        for matches in window._last_results
                        for match in matches
                    )
                )
        finally:
            self._close_app(root, app)

    def test_flat_product_assignment_refreshes_global_and_part_without_pending(self) -> None:
        root, app = self._create_app()
        products = _products()[:2]
        mix_overrides = ["#123456", None, "#345678", None, None, "#56789A"]
        primary = [12, 23, 34, 45, 56, 67]
        secondary = [78, 69, 58, 47, 36, 25]
        assignment = [f"#{index:02X}{index:02X}{index:02X}" for index in range(32)]

        def flat_palette() -> PaletteSettings:
            return PaletteSettings(
                palette_state_count=32,
                color_mode=COLOR_MODE_FLAT_FOUR,
                enabled_states=[False] * 4 + [True] * 28,
                mix_hex_overrides=mix_overrides,
                mix_ratios_b=primary,
                secondary_mix_ratios_b=secondary,
                assignment_palette_hex=assignment,
            )

        try:
            app.settings.palette = flat_palette()
            app._load_palette_variables(app.settings.palette)
            app._schedule_preview = Mock()
            editor = SimpleNamespace(
                settings=None,
                reapply_palette_settings=Mock(),
            )
            app.paint_editor = editor

            self.assertTrue(app._set_physical_filament_product(0, products[0]))
            global_palette = app.settings.palette
            self.assertEqual(global_palette.physical_hex[0], products[0].matched_hex)
            self.assertTrue(global_palette.enabled_states[0])
            self.assertIsNone(global_palette.assignment_palette_hex)
            self.assertEqual(global_palette.mix_hex_overrides, mix_overrides)
            self.assertEqual(global_palette.mix_ratios_b, primary)
            self.assertEqual(global_palette.secondary_mix_ratios_b, secondary)
            self.assertEqual(app._pending_physical_palette_targets, set())
            app._schedule_preview.assert_called_once_with(immediate=True)
            self.assertIsNone(editor.reapply_palette_settings.call_args.args[0])

            app.settings.part_names["arm"] = "Arm"
            app.settings.part_palettes["arm"] = flat_palette()
            app.active_part_key = "arm"
            app._load_palette_variables(app.settings.part_palettes["arm"])
            app._schedule_preview.reset_mock()
            editor.reapply_palette_settings.reset_mock()

            self.assertTrue(app._set_physical_filament_product(1, products[1]))
            part_palette = app.settings.part_palettes["arm"]
            self.assertEqual(part_palette.physical_hex[1], products[1].matched_hex)
            self.assertTrue(part_palette.enabled_states[1])
            self.assertIsNone(part_palette.assignment_palette_hex)
            self.assertEqual(part_palette.mix_hex_overrides, mix_overrides)
            self.assertEqual(app._pending_physical_palette_targets, set())
            app._schedule_preview.assert_called_once_with(immediate=True)
            self.assertEqual(editor.reapply_palette_settings.call_args.args[0], "arm")
        finally:
            app.paint_editor = None
            self._close_app(root, app)

    def test_full_product_assignment_keeps_snapshot_pending_until_apply(self) -> None:
        root, app = self._create_app()
        product = _products()[0]
        try:
            previous = app._copy_palette(app.settings.palette)
            expected_snapshot = app._palette_state_hex_snapshot(previous)
            app._schedule_preview = Mock()

            self.assertTrue(app._set_physical_filament_product(0, product))

            palette = app.settings.palette
            self.assertEqual(palette.physical_hex[0], product.matched_hex)
            self.assertEqual(palette.assignment_palette_hex, expected_snapshot)
            self.assertEqual(app._pending_physical_palette_targets, {None})
            app._schedule_preview.assert_not_called()
        finally:
            self._close_app(root, app)

    def test_flat_basic_recommendation_reassigns_global_without_losing_dormant_mixes(self) -> None:
        root, app = self._create_app()
        products = _products()[:4]
        enabled = [False] * 4 + [index % 2 == 0 for index in range(28)]
        mix_overrides = ["#123456", None, "#345678", None, None, "#56789A"]
        primary = [12, 23, 34, 45, 56, 67]
        secondary = [78, 69, 58, 47, 36, 25]
        output = [20 + index for index in range(28)]
        recommendation = SimpleNamespace(
            physical_hex=("#E32B35", "#F2F1ED", "#2255CC", "#161616"),
            primary_ratio_b_percent=33,
            secondary_ratio_b_percent=67,
            candidates=products,
            mean_delta_e76=4.5,
            coverage_fraction=0.9,
            confidence=0.85,
        )

        try:
            app.settings.palette = PaletteSettings(
                palette_state_count=32,
                color_mode=COLOR_MODE_FLAT_FOUR,
                enabled_states=enabled,
                mix_hex_overrides=mix_overrides,
                mix_ratios_b=primary,
                secondary_mix_ratios_b=secondary,
                output_mix_ratios_b=output,
                assignment_palette_hex=["#101010"] * 32,
            )
            app._load_palette_variables(app.settings.palette)
            app._mark_physical_palette_pending(None)
            app.prepared = SimpleNamespace(
                final=SimpleNamespace(
                    vertex_colors=np.asarray(
                        [[0.9, 0.1, 0.1], [0.8, 0.2, 0.1], [0.7, 0.1, 0.2]],
                        dtype=np.float64,
                    ),
                    faces=np.asarray([[0, 1, 2]], dtype=np.int64),
                    areas_unit=np.asarray([1.0], dtype=np.float64),
                    face_part_ids=np.asarray([0], dtype=np.int64),
                    part_keys=["part-0"],
                    part_names=["Head"],
                ),
                preview=SimpleNamespace(),
            )
            app.prepared_key = ("basic-flat-test",)
            editor = SimpleNamespace(reapply_shading_settings=Mock())
            app.paint_editor = editor

            def run_synchronously(_label, function, done, **_kwargs):
                done(function())
                return True

            with (
                patch(
                    "spectrum_mapper.filament_database.FilamentRepository.list_products",
                    return_value=products,
                ),
                patch(
                    "spectrum_mapper.gui.recommend_basic_filaments",
                    return_value=recommendation,
                ) as recommend,
                patch.object(app, "_submit_main", side_effect=run_synchronously),
                patch.object(app, "_schedule_preview") as schedule_preview,
            ):
                app._recommend_part_ids((), whole_model=True)

            recommend.assert_called_once()
            self.assertFalse(recommend.call_args.kwargs["include_mixed_states"])
            palette = app.settings.palette
            self.assertEqual(palette.color_mode, COLOR_MODE_FLAT_FOUR)
            self.assertEqual(palette.physical_hex, list(recommendation.physical_hex))
            self.assertEqual(palette.enabled_states[:4], [True] * 4)
            self.assertEqual(palette.enabled_states[4:], enabled[4:])
            self.assertEqual(palette.mix_hex_overrides, mix_overrides)
            self.assertEqual(palette.mix_ratios_b, primary)
            self.assertEqual(palette.secondary_mix_ratios_b, secondary)
            self.assertEqual(palette.output_mix_ratios_b, output)
            self.assertIsNone(palette.assignment_palette_hex)
            self.assertEqual(app._pending_physical_palette_targets, set())
            schedule_preview.assert_called_once_with(immediate=True)
            editor.reapply_shading_settings.assert_called_once_with(
                app.settings,
                message=app.status_var.get(),
            )
        finally:
            app.paint_editor = None
            self._close_app(root, app)

    def test_direct_flat_and_full_then_flat_choose_same_global_and_part_filaments(self) -> None:
        root, app = self._create_app()
        products = _products()
        full_candidates = products[:4]
        flat_candidates = (products[3], products[1], products[0], products[4])

        def recommendation(candidates):
            return SimpleNamespace(
                physical_hex=tuple(item.matched_hex for item in candidates),
                primary_ratio_b_percent=33,
                secondary_ratio_b_percent=67,
                candidates=candidates,
                mean_delta_e76=4.5,
                coverage_fraction=0.9,
                confidence=0.85,
            )

        full_recommendation = recommendation(full_candidates)
        flat_recommendation = recommendation(flat_candidates)

        try:
            app.prepared = SimpleNamespace(
                final=SimpleNamespace(
                    vertex_colors=np.asarray(
                        [[0.9, 0.1, 0.1], [0.8, 0.2, 0.1], [0.7, 0.1, 0.2]],
                        dtype=np.float64,
                    ),
                    faces=np.asarray([[0, 1, 2]], dtype=np.int64),
                    areas_unit=np.asarray([1.0], dtype=np.float64),
                    face_part_ids=np.asarray([0], dtype=np.int64),
                    part_keys=["body"],
                    part_names=["Body"],
                ),
                preview=SimpleNamespace(),
            )
            app.prepared_key = ("mode-history-test",)
            app.source_path = Path("C:/models/mode-history.glb")

            def run_synchronously(_label, function, done, **_kwargs):
                done(function())
                return True

            def recommend_for_mode(*_args, **kwargs):
                return (
                    full_recommendation
                    if kwargs["include_mixed_states"]
                    else flat_recommendation
                )

            with (
                patch(
                    "spectrum_mapper.filament_database.FilamentRepository.list_products",
                    return_value=products,
                ),
                patch(
                    "spectrum_mapper.gui.recommend_basic_filaments",
                    side_effect=recommend_for_mode,
                ) as recommend,
                patch.object(app, "_submit_main", side_effect=run_synchronously),
                patch.object(app, "_schedule_preview"),
                patch.object(app, "_save_persistent_settings"),
            ):
                app.settings.palette = PaletteSettings(
                    color_mode=COLOR_MODE_FLAT_FOUR
                )
                app.settings.part_palettes = {}
                app._load_palette_variables(app.settings.palette)
                app._clear_automatic_palette_provenance()
                app._recommend_all_parts(automatic=True)
                direct_global = tuple(app.settings.palette.physical_hex)
                direct_part = tuple(
                    app.settings.part_palettes["body"].physical_hex
                )

                app.settings.palette = PaletteSettings(
                    color_mode=COLOR_MODE_FULL_SPECTRUM
                )
                app.settings.part_palettes = {}
                app._load_palette_variables(app.settings.palette)
                app._clear_automatic_palette_provenance()
                app._recommend_all_parts(automatic=True)
                self.assertEqual(
                    tuple(app.settings.palette.physical_hex),
                    tuple(full_recommendation.physical_hex),
                )

                app._change_color_mode(COLOR_MODE_FLAT_FOUR)

            self.assertEqual(tuple(app.settings.palette.physical_hex), direct_global)
            self.assertEqual(
                tuple(app.settings.part_palettes["body"].physical_hex),
                direct_part,
            )
            self.assertEqual(recommend.call_count, 6)
            self.assertEqual(
                [
                    call.kwargs["include_mixed_states"]
                    for call in recommend.call_args_list
                ],
                [False, False, True, True, False, False],
            )
        finally:
            self._close_app(root, app)

    def test_owned_auto_action_names_target_and_prevents_double_start(self) -> None:
        root, app = self._create_app()
        products = _products()[:4]
        try:
            window = FilamentCandidateWindow(app, matcher=_ProductMatcher(products))
            app.filament_candidate_window = window
            window._update_inventory_products(
                products,
                OwnedFilamentInventory(products=products),
            )
            app.prepared = SimpleNamespace(
                final=SimpleNamespace(
                    part_keys=["part-0"],
                    part_names=["Head"],
                )
            )
            app.active_part_key = "part-0"
            window._refresh_auto_target()
            self.assertIn("Head", window.auto_target_var.get())

            captured: dict[str, object] = {}

            def configure(owned_products, **kwargs):
                captured["products"] = tuple(owned_products)
                captured.update(kwargs)
                return True

            app._configure_from_owned_filaments = configure
            window._auto_build_from_owned()
            self.assertTrue(window._auto_in_progress)
            self.assertEqual(str(window.auto_owned_button.cget("state")), "disabled")
            self.assertEqual(len(captured["products"]), 4)
            window._auto_build_from_owned()
            self.assertEqual(len(captured["products"]), 4)
            captured["on_finished"](True)
            self.assertFalse(window._auto_in_progress)
            self.assertEqual(str(window.auto_owned_button.cget("state")), "normal")
        finally:
            self._close_app(root, app)

    def test_saved_owned_snapshots_remain_usable_when_database_is_missing(self) -> None:
        root, app = self._create_app()
        products = _products()[:4]
        inventory = OwnedFilamentInventory(
            products=products,
            stale_product_ids=tuple(product.product_id for product in products),
        )
        try:
            with patch(
                "spectrum_mapper.owned_filaments.load_owned_filament_inventory",
                return_value=inventory,
            ):
                window = FilamentCandidateWindow(app, matcher=_UnavailableMatcher())
                app.filament_candidate_window = window
                window.candidate_scope_var.set("owned")
                window.show()
                self.assertTrue(
                    _wait_for(
                        root,
                        lambda: window._result_target_hexes is not None
                        and any(window._last_results),
                    )
                )
                self.assertEqual(str(window.brand_combo.cget("state")), "disabled")
                self.assertIn("保存済み", window.status_var.get())
                self.assertEqual(
                    window.candidate_rows[0][0]["source"].cget("text"),
                    "保存情報",
                )
                self.assertEqual(len(window._owned_product_ids), 4)
        finally:
            self._close_app(root, app)

    def test_unresolved_inventory_ids_survive_unrelated_edits_until_removed(self) -> None:
        root, app = self._create_app()
        products = _products()[:2]
        saved: list[OwnedFilamentInventory] = []
        try:
            window = FilamentCandidateWindow(app, matcher=_ProductMatcher(products))
            app.filament_candidate_window = window
            window._update_inventory_products(
                products,
                OwnedFilamentInventory(
                    products=(products[0],),
                    unresolved_product_ids=("legacy-missing-id",),
                ),
            )
            with patch(
                "spectrum_mapper.owned_filaments.save_owned_filament_inventory",
                side_effect=lambda inventory: saved.append(inventory)
                or Path("owned_filaments.json"),
            ):
                window._set_inventory_ids_owned((products[1].product_id,), True)
                self.assertEqual(
                    saved[-1].unresolved_product_ids,
                    ("legacy-missing-id",),
                )
                window._set_inventory_ids_owned(("legacy-missing-id",), False)
                self.assertEqual(saved[-1].unresolved_product_ids, ())
        finally:
            self._close_app(root, app)

    def test_owned_inventory_save_failure_rolls_back_memory_and_visible_count(self) -> None:
        root, app = self._create_app()
        products = _products()[:2]
        initial_inventory = OwnedFilamentInventory(
            products=(products[0],),
            stale_product_ids=(products[0].product_id,),
            unresolved_product_ids=("legacy-missing-id",),
        )
        try:
            window = FilamentCandidateWindow(app, matcher=_ProductMatcher(products))
            app.filament_candidate_window = window
            window._update_inventory_products(products, initial_inventory)
            previous_revision = window._inventory_revision()

            with patch(
                "spectrum_mapper.owned_filaments.save_owned_filament_inventory",
                side_effect=OSError("disk full"),
            ):
                window._set_inventory_ids_owned((products[1].product_id,), True)

            self.assertEqual(
                window._owned_product_ids,
                {products[0].product_id},
            )
            self.assertIs(window._owned_inventory, initial_inventory)
            self.assertEqual(
                window._inventory_unresolved_ids,
                ("legacy-missing-id",),
            )
            self.assertEqual(
                window._inventory_stale_ids,
                (products[0].product_id,),
            )
            self.assertEqual(window._inventory_revision(), previous_revision)
            self.assertIn("disk full", window.status_var.get())
            self.assertIn("1", window.inventory_count_var.get())
        finally:
            self._close_app(root, app)

    def test_owned_auto_configuration_commits_four_colors_and_twelve_ratios_once(self) -> None:
        root, app = self._create_app()
        products = _products()[:4]
        original_palette = list(app.settings.palette.physical_hex)
        try:
            app.prepared = SimpleNamespace(
                final=SimpleNamespace(
                    vertex_colors=np.asarray(
                        [[0.9, 0.1, 0.1], [0.8, 0.2, 0.1], [0.7, 0.1, 0.2]],
                        dtype=np.float64,
                    ),
                    faces=np.asarray([[0, 1, 2]], dtype=np.int64),
                    areas_unit=np.asarray([1.0], dtype=np.float64),
                    face_part_ids=np.asarray([0], dtype=np.int64),
                    part_keys=["part-0"],
                    part_names=["Head"],
                ),
                preview=SimpleNamespace(),
            )
            app.prepared_key = ("owned-test",)
            app.pink_protection_var.set(True)
            app.pink_threshold_var.set(0.10)
            result = SimpleNamespace(
                palette_state_count=16,
                physical_hex=("#E32B35", "#F2F1ED", "#2255CC", "#161616"),
                mix_ratios_b=(21, 32, 43, 54, 65, 76),
                secondary_mix_ratios_b=(79, 68, 57, 46, 35, 24),
                candidates=products,
                before_mean_delta_e76=15.0,
                mean_delta_e76=7.5,
                improvement_percent=50.0,
                ignored_duplicate_color_product_ids=(),
                special_finish_products=(),
            )
            callbacks: list[bool] = []

            def run_synchronously(_label, function, done, **_kwargs):
                done(function())
                return True

            with (
                patch(
                    "spectrum_mapper.owned_filaments.recommend_from_owned_filaments",
                    return_value=result,
                ) as recommend,
                patch.object(app, "_submit_main", side_effect=run_synchronously),
                patch.object(app, "_schedule_preview"),
                patch.object(app, "_optimize_mix_ratios") as old_optimizer,
            ):
                started = app._configure_from_owned_filaments(
                    products,
                    inventory_revision=tuple(
                        (product.product_id, product.matched_hex)
                        for product in products
                    ),
                    on_finished=callbacks.append,
                )
            self.assertTrue(started)
            recommend.assert_called_once()
            pink_mask = recommend.call_args.kwargs["pink_protection_mask"]
            self.assertEqual(pink_mask.dtype, np.bool_)
            self.assertEqual(pink_mask.tolist(), [True])
            old_optimizer.assert_not_called()
            self.assertEqual(callbacks, [True])
            self.assertNotEqual(app.settings.palette.physical_hex, original_palette)
            self.assertEqual(
                app.settings.palette.physical_hex,
                list(result.physical_hex),
            )
            self.assertEqual(app.settings.palette.mix_ratios_b, list(result.mix_ratios_b))
            self.assertEqual(
                app.settings.palette.secondary_mix_ratios_b,
                list(result.secondary_mix_ratios_b),
            )
            self.assertEqual(
                [
                    ref.product_id if ref is not None else None
                    for ref in app.settings.palette.physical_filament_refs
                ],
                [product.product_id for product in products],
            )
            self.assertEqual(
                [variable.get() for variable in app.physical_vars],
                list(result.physical_hex),
            )
            self.assertIn("F1:", app.recommendation_var.get())
            self.assertIn("F4:", app.recommendation_var.get())
            self.assertIn("product_id=a-red", app.recommendation_var.get())
        finally:
            self._close_app(root, app)

    def test_owned_auto_flat_mode_activates_f1_f4_and_preserves_dormant_mixes(self) -> None:
        root, app = self._create_app()
        products = _products()[:4]
        enabled = [False] * 4 + [index % 3 == 0 for index in range(28)]
        mix_overrides = ["#102030", None, "#405060", None, None, "#708090"]
        primary_ratios = [12, 23, 34, 45, 56, 67]
        secondary_ratios = [78, 69, 58, 47, 36, 25]
        output_ratios = [20 + index for index in range(28)]
        assignment_palette = [f"#{index:02X}{index:02X}{index:02X}" for index in range(32)]
        original = PaletteSettings(
            palette_state_count=32,
            color_mode=COLOR_MODE_FLAT_FOUR,
            enabled_states=enabled,
            mix_hex_overrides=mix_overrides,
            mix_ratios_b=primary_ratios,
            secondary_mix_ratios_b=secondary_ratios,
            output_mix_ratios_b=output_ratios,
            assignment_palette_hex=assignment_palette,
        )
        try:
            app.settings.palette = original
            app._load_palette_variables(original)
            app._mark_physical_palette_pending(None)
            editor = SimpleNamespace(
                settings=None,
                reapply_palette_settings=Mock(),
            )
            app.paint_editor = editor
            app.prepared = SimpleNamespace(
                final=SimpleNamespace(
                    vertex_colors=np.asarray(
                        [[0.9, 0.1, 0.1], [0.8, 0.2, 0.1], [0.7, 0.1, 0.2]],
                        dtype=np.float64,
                    ),
                    faces=np.asarray([[0, 1, 2]], dtype=np.int64),
                    areas_unit=np.asarray([1.0], dtype=np.float64),
                    face_part_ids=np.asarray([0], dtype=np.int64),
                    part_keys=["part-0"],
                    part_names=["Head"],
                ),
                preview=SimpleNamespace(),
            )
            app.prepared_key = ("owned-flat-test",)
            result = SimpleNamespace(
                palette_state_count=32,
                physical_hex=("#E32B35", "#F2F1ED", "#2255CC", "#161616"),
                # Flat mode must not overwrite these dormant Full Spectrum recipes.
                mix_ratios_b=(91, 82, 73, 64, 55, 46),
                secondary_mix_ratios_b=(19, 28, 37, 46, 55, 64),
                candidates=products,
                before_mean_delta_e76=15.0,
                mean_delta_e76=7.5,
                improvement_percent=50.0,
                ignored_duplicate_color_product_ids=(),
                special_finish_products=(),
            )

            def run_synchronously(_label, function, done, **_kwargs):
                done(function())
                return True

            with (
                patch(
                    "spectrum_mapper.owned_filaments.recommend_from_owned_filaments",
                    return_value=result,
                ) as recommend,
                patch.object(app, "_submit_main", side_effect=run_synchronously),
                patch.object(app, "_schedule_preview") as schedule_preview,
            ):
                started = app._configure_from_owned_filaments(
                    products,
                    inventory_revision=tuple(
                        (product.product_id, product.matched_hex)
                        for product in products
                    ),
                )

            self.assertTrue(started)
            recommend.assert_called_once()
            self.assertFalse(recommend.call_args.kwargs["include_mixed_states"])
            palette = app.settings.palette
            self.assertEqual(palette.color_mode, COLOR_MODE_FLAT_FOUR)
            self.assertEqual(palette.physical_hex, list(result.physical_hex))
            self.assertEqual(palette.enabled_states[:4], [True] * 4)
            self.assertEqual(palette.enabled_states[4:], enabled[4:])
            self.assertEqual(palette.mix_hex_overrides, mix_overrides)
            self.assertEqual(palette.mix_ratios_b, primary_ratios)
            self.assertEqual(palette.secondary_mix_ratios_b, secondary_ratios)
            self.assertEqual(palette.output_mix_ratios_b, output_ratios)
            self.assertIsNone(palette.assignment_palette_hex)
            self.assertEqual(app._pending_physical_palette_targets, set())
            schedule_preview.assert_called_once_with(immediate=True)
            editor.reapply_palette_settings.assert_called_once()
            self.assertIsNone(editor.reapply_palette_settings.call_args.args[0])
        finally:
            app.paint_editor = None
            self._close_app(root, app)

    def test_owned_auto_common_uses_only_faces_without_part_palettes(self) -> None:
        root, app = self._create_app()
        products = _products()[:4]
        try:
            app.prepared = SimpleNamespace(
                final=SimpleNamespace(
                    vertex_colors=np.asarray(
                        [
                            [0.9, 0.1, 0.1],
                            [0.8, 0.2, 0.1],
                            [0.7, 0.1, 0.2],
                            [0.1, 0.1, 0.9],
                            [0.1, 0.2, 0.8],
                            [0.2, 0.1, 0.7],
                        ],
                        dtype=np.float64,
                    ),
                    faces=np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int64),
                    areas_unit=np.asarray([1.0, 9.0], dtype=np.float64),
                    face_part_ids=np.asarray([0, 1], dtype=np.int64),
                    part_keys=["part-0", "part-1"],
                    part_names=["Common Head", "Local Body"],
                ),
                preview=SimpleNamespace(),
            )
            app.prepared_key = ("owned-common-scope",)
            app.active_part_key = None
            app.settings.part_palettes["part-1"] = PaletteSettings(
                physical_hex=["#101010", "#202020", "#303030", "#404040"]
            )
            result = SimpleNamespace(
                palette_state_count=16,
                physical_hex=("#E32B35", "#F2F1ED", "#2255CC", "#161616"),
                mix_ratios_b=(21, 32, 43, 54, 65, 76),
                secondary_mix_ratios_b=(79, 68, 57, 46, 35, 24),
                candidates=products,
                before_mean_delta_e76=15.0,
                mean_delta_e76=7.5,
                improvement_percent=50.0,
                ignored_duplicate_color_product_ids=(),
                special_finish_products=(),
            )

            def run_synchronously(_label, function, done, **_kwargs):
                done(function())
                return True

            with (
                patch(
                    "spectrum_mapper.owned_filaments.recommend_from_owned_filaments",
                    return_value=result,
                ) as recommend,
                patch.object(app, "_submit_main", side_effect=run_synchronously),
                patch.object(app, "_schedule_preview"),
            ):
                started = app._configure_from_owned_filaments(
                    products,
                    inventory_revision=tuple(
                        (product.product_id, product.matched_hex)
                        for product in products
                    ),
                )

            self.assertTrue(started)
            recommend.assert_called_once()
            object_rgb, object_weights = recommend.call_args.args[:2]
            self.assertEqual(object_rgb.shape, (1, 3))
            np.testing.assert_allclose(object_weights, np.asarray([1.0]))
            self.assertGreater(float(object_rgb[0, 0]), 0.8)
            self.assertLess(float(object_rgb[0, 2]), 0.2)
            self.assertEqual(
                app.settings.part_palettes["part-1"].physical_hex,
                ["#101010", "#202020", "#303030", "#404040"],
            )
        finally:
            self._close_app(root, app)

    def test_owned_auto_common_reports_when_all_faces_use_part_palettes(self) -> None:
        root, app = self._create_app()
        products = _products()[:4]
        try:
            app.prepared = SimpleNamespace(
                final=SimpleNamespace(
                    faces=np.asarray([[0, 1, 2]], dtype=np.int64),
                    face_part_ids=np.asarray([0], dtype=np.int64),
                    part_keys=["part-0"],
                    part_names=["Local Head"],
                ),
                preview=SimpleNamespace(),
            )
            app.active_part_key = None
            app.settings.part_palettes["part-0"] = PaletteSettings()
            with (
                patch(
                    "spectrum_mapper.gui.messagebox.showwarning"
                ) as warning,
                patch.object(app, "_submit_main") as submit,
            ):
                started = app._configure_from_owned_filaments(
                    products,
                    inventory_revision=(),
                )
            self.assertFalse(started)
            submit.assert_not_called()
            warning.assert_called_once()
            self.assertIn("実際に反映される面がありません", warning.call_args.args[1])
        finally:
            self._close_app(root, app)

    def test_owned_auto_manual_or_paint_tree_requires_confirmation_before_work(self) -> None:
        root, app = self._create_app()
        products = _products()[:4]
        try:
            app.prepared = SimpleNamespace(
                final=SimpleNamespace(
                    faces=np.asarray([[0, 1, 2]], dtype=np.int64),
                    face_part_ids=np.asarray([0], dtype=np.int64),
                    part_keys=["part-0"],
                    part_names=["Head"],
                ),
                preview=SimpleNamespace(),
            )
            app.active_part_key = None
            original_palette = app.settings.to_dict()["palette"]

            for manual, trees in (
                (np.asarray([2], dtype=np.int8), {}),
                (None, {0: object()}),
            ):
                app.prepared._hotfix_subtriangle_paint = trees
                with (
                    patch.object(
                        app,
                        "_validated_manual_overrides",
                        return_value=(True, manual),
                    ),
                    patch(
                        "spectrum_mapper.gui.messagebox.askyesno",
                        return_value=False,
                    ) as confirm,
                    patch.object(app, "_reference_samples_for_recommendation") as reference,
                    patch.object(app, "_submit_main") as submit,
                ):
                    started = app._configure_from_owned_filaments(
                        products,
                        inventory_revision=(),
                    )
                self.assertFalse(started)
                confirm.assert_called_once()
                self.assertIn("F1〜F4", confirm.call_args.args[1])
                reference.assert_not_called()
                submit.assert_not_called()
                self.assertEqual(
                    app.settings.to_dict()["palette"],
                    original_palette,
                )
        finally:
            self._close_app(root, app)

    def test_app_shutdown_destroys_window_and_candidate_executor(self) -> None:
        root, app = self._create_app()
        window = FilamentCandidateWindow(app, matcher=_Matcher())
        app.filament_candidate_window = window
        self._close_app(root, app)
        self.assertTrue(window._closed)
        self.assertTrue(window._executor._shutdown)
        self.assertIsNone(app.filament_candidate_window)


if __name__ == "__main__":
    unittest.main(verbosity=2)
