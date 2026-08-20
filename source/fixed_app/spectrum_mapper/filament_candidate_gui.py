from __future__ import annotations

import queue
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from .mixer import normalize_hex


PHYSICAL_NAMES = ("F1", "F2", "F3", "F4")
_NEUTRAL_SWATCH = "#303846"
_FINISH_TRANSLATION_KEYS = {
    "カーボン繊維": "filament_candidates.finish.carbon_fiber",
    "ガラス繊維": "filament_candidates.finish.glass_fiber",
    "シルク/メタリック/光沢": "filament_candidates.finish.silk_metallic_glossy",
    "マット": "filament_candidates.finish.matte",
    "マーブル/ストーン": "filament_candidates.finish.marble_stone",
    "木質": "filament_candidates.finish.wood",
    "標準/不透明": "filament_candidates.finish.standard_opaque",
    "発泡/LW": "filament_candidates.finish.foaming_lw",
    "蓄光": "filament_candidates.finish.glow",
    "透明/半透明": "filament_candidates.finish.transparent",
}


@dataclass(frozen=True, slots=True)
class _OwnedProductMatch:
    """Candidate-row adapter for one product from the owned inventory."""

    product_id: str
    brand: str
    series: str
    color_name: str
    matched_hex: str
    delta_e_2000: float
    score: float
    finish_class: str
    source_kind: str
    source_url: str | None = None
    record_id: str | None = None
    measurement_id: str | None = None
    material: str = "PLA"


def _match_value(match: object, name: str, default: object = "") -> object:
    """Read a matcher result without coupling the UI to its implementation."""

    if isinstance(match, dict):
        return match.get(name, default)
    return getattr(match, name, default)


class FilamentCandidateWindow:
    """Independent F1-F4 product-color candidate tool window.

    Database work is kept off Tk's event thread and the only mutation this
    surface can make is an explicitly confirmed update of one existing
    ``physical_vars`` entry.  Consequently a missing or damaged optional
    database cannot block the OBJ conversion/editor workflow.
    """

    CANDIDATES_PER_SLOT = 3

    def __init__(self, app: Any, *, matcher: object | None = None) -> None:
        self.app = app
        self.root: tk.Misc = app.root
        self.i18n = app.i18n
        self._matcher = matcher
        self._search_generation = 0
        self._search_after_id: str | None = None
        self._poll_after_id: str | None = None
        self._closed = False
        self._filters_loaded = False
        self._database_available: bool | None = None
        self._database_reason = ""
        self._brand_filter: str | None = None
        self._finish_filter: str | None = None
        self._available_brands: tuple[str, ...] = ()
        self._available_finishes: tuple[str, ...] = ()
        self._finish_display_to_value: dict[str, str | None] = {}
        self._all_products: tuple[object, ...] = ()
        self._product_by_id: dict[str, object] = {}
        self._owned_product_ids: set[str] = set()
        self._owned_inventory: object | None = None
        self._inventory_unresolved_ids: tuple[str, ...] = ()
        self._inventory_stale_ids: tuple[str, ...] = ()
        self._inventory_loaded = False
        self._inventory_item_to_product_id: dict[str, str] = {}
        self._inventory_item_to_brand: dict[str, str] = {}
        self._inventory_brand_to_product_ids: dict[str, tuple[str, ...]] = {}
        self._inventory_brand_to_products: dict[str, tuple[object, ...]] = {}
        self._inventory_tree_signature: tuple[object, ...] | None = None
        self._auto_in_progress = False
        self._auto_watch_after_id: str | None = None
        self._last_results: tuple[tuple[object, ...], ...] = (
            (),
            (),
            (),
            (),
        )
        self._result_target_hexes: tuple[str, ...] | None = None
        self._result_queue: queue.Queue[tuple[str, int, object]] = queue.Queue()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="filament-candidates",
        )

        self.window = tk.Toplevel(self.root)
        self.window.withdraw()
        self.window.configure(bg="#10141B")
        # Product names become unreadably short when the manufacturer tree and
        # four candidate cards share the former 1180 px default.  Prefer the
        # wider working layout while still fitting smaller displays.
        screen_width = max(900, int(self.window.winfo_screenwidth()))
        screen_height = max(620, int(self.window.winfo_screenheight()))
        initial_width = min(1500, max(1000, screen_width - 80))
        initial_height = min(900, max(680, screen_height - 120))
        initial_x = max(0, (screen_width - initial_width) // 2)
        initial_y = max(0, (screen_height - initial_height) // 2)
        self.window.geometry(
            f"{initial_width}x{initial_height}+{initial_x}+{initial_y}"
        )
        self.window.minsize(900, 620)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)

        self.brand_var = tk.StringVar()
        self.finish_var = tk.StringVar()
        self.prefer_measured_var = tk.BooleanVar(value=True)
        self.candidate_scope_var = tk.StringVar(value="all")
        self.inventory_count_var = tk.StringVar()
        self.auto_target_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self._build_ui()
        self.window.bind("<MouseWheel>", self._on_mouse_wheel, add="+")

        self._color_trace_tokens: list[tuple[tk.Variable, str]] = []
        for variable in self.app.physical_vars:
            token = variable.trace_add("write", self._on_target_color_changed)
            self._color_trace_tokens.append((variable, token))

        self.set_language()
        self._poll_after_id = self.window.after(80, self._poll_results)

    def _build_ui(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)

        header = ttk.Frame(self.window, style="Panel.TFrame", padding=(14, 10))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(
            header,
            style="Panel.TLabel",
            font=("Yu Gothic UI", 15, "bold"),
        )
        self.title_label.grid(row=0, column=0, sticky="w")
        self.beta_label = tk.Label(
            header,
            text="BETA",
            bg="#B65A17",
            fg="#FFFFFF",
            font=("Yu Gothic UI", 9, "bold"),
            padx=9,
            pady=2,
        )
        self.beta_label.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.intro_label = ttk.Label(
            header,
            style="PanelMuted.TLabel",
            justify="left",
        )
        self.intro_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

        controls = ttk.Frame(self.window, style="Panel2.TFrame", padding=(12, 8))
        controls.grid(row=1, column=0, sticky="ew", padx=10, pady=(8, 4))
        controls.columnconfigure(6, weight=1)
        self.brand_label = ttk.Label(controls, style="Panel2.TLabel")
        self.brand_label.grid(row=0, column=0, sticky="w")
        self.brand_combo = ttk.Combobox(
            controls,
            textvariable=self.brand_var,
            state="readonly",
            width=20,
            style="HighContrast.TCombobox",
        )
        self.brand_combo.grid(row=0, column=1, sticky="w", padx=(5, 14))
        self.brand_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)
        self.finish_label = ttk.Label(controls, style="Panel2.TLabel")
        self.finish_label.grid(row=0, column=2, sticky="w")
        self.finish_combo = ttk.Combobox(
            controls,
            textvariable=self.finish_var,
            state="readonly",
            width=17,
            style="HighContrast.TCombobox",
        )
        self.finish_combo.grid(row=0, column=3, sticky="w", padx=(5, 14))
        self.finish_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)
        self.prefer_measured_check = ttk.Checkbutton(
            controls,
            variable=self.prefer_measured_var,
            command=self._on_filter_changed,
            style="Panel2.TCheckbutton",
        )
        self.prefer_measured_check.grid(row=0, column=4, sticky="w", padx=(0, 14))
        self.refresh_button = ttk.Button(
            controls,
            command=lambda: self._schedule_search(delay_ms=0),
            style="Accent.TButton",
        )
        self.refresh_button.grid(row=0, column=5, sticky="w")
        self.status_label = ttk.Label(
            controls,
            textvariable=self.status_var,
            style="Panel2Muted.TLabel",
            anchor="e",
            justify="right",
            wraplength=430,
        )
        self.status_label.grid(row=0, column=6, sticky="ew", padx=(12, 0))

        self.scope_label = ttk.Label(controls, style="Panel2.TLabel")
        self.scope_label.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.scope_all_radio = ttk.Radiobutton(
            controls,
            variable=self.candidate_scope_var,
            value="all",
            command=self._on_candidate_scope_changed,
            style="Panel2.TRadiobutton",
        )
        self.scope_all_radio.grid(
            row=1, column=1, sticky="w", padx=(5, 12), pady=(8, 0)
        )
        self.scope_owned_radio = ttk.Radiobutton(
            controls,
            variable=self.candidate_scope_var,
            value="owned",
            command=self._on_candidate_scope_changed,
            style="Panel2.TRadiobutton",
        )
        self.scope_owned_radio.grid(
            row=1, column=2, sticky="w", padx=(0, 12), pady=(8, 0)
        )
        self.auto_target_label = ttk.Label(
            controls,
            textvariable=self.auto_target_var,
            style="Panel2.TLabel",
            anchor="e",
        )
        self.auto_target_label.grid(
            row=1, column=3, columnspan=2, sticky="e", padx=(8, 8), pady=(8, 0)
        )
        self.auto_owned_button = ttk.Button(
            controls,
            command=self._auto_build_from_owned,
            style="Accent.TButton",
        )
        self.auto_owned_button.grid(
            row=1, column=5, columnspan=2, sticky="e", pady=(8, 0)
        )

        self.body_paned = ttk.Panedwindow(self.window, orient="horizontal")
        self.body_paned.grid(row=2, column=0, sticky="nsew", padx=10, pady=4)

        inventory = ttk.LabelFrame(
            self.body_paned,
            style="TLabelframe",
            padding=(8, 6),
        )
        inventory.columnconfigure(0, weight=1)
        inventory.rowconfigure(2, weight=1)
        self.inventory_frame = inventory
        self.inventory_help_label = ttk.Label(
            inventory,
            style="PanelMuted.TLabel",
            justify="left",
            wraplength=315,
        )
        self.inventory_help_label.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.inventory_count_label = ttk.Label(
            inventory,
            textvariable=self.inventory_count_var,
            style="Panel.TLabel",
            font=("Yu Gothic UI", 10, "bold"),
        )
        self.inventory_count_label.grid(row=1, column=0, sticky="w", pady=(0, 5))
        tree_host = ttk.Frame(inventory, style="Panel.TFrame")
        tree_host.grid(row=2, column=0, sticky="nsew")
        tree_host.columnconfigure(0, weight=1)
        tree_host.rowconfigure(0, weight=1)
        self.inventory_tree = ttk.Treeview(
            tree_host,
            columns=("owned", "hex", "finish"),
            show=("tree", "headings"),
            selectmode="browse",
            height=15,
        )
        self.inventory_tree.column("#0", width=230, minwidth=150, anchor="w")
        self.inventory_tree.column("owned", width=55, minwidth=50, anchor="center")
        self.inventory_tree.column("hex", width=82, minwidth=75, anchor="w")
        self.inventory_tree.column("finish", width=120, minwidth=90, anchor="w")
        self.inventory_tree.grid(row=0, column=0, sticky="nsew")
        inventory_scrollbar = ttk.Scrollbar(
            tree_host,
            orient="vertical",
            command=self.inventory_tree.yview,
        )
        inventory_scrollbar.grid(row=0, column=1, sticky="ns")
        self.inventory_tree.configure(yscrollcommand=inventory_scrollbar.set)
        self.inventory_tree.bind("<Double-1>", self._toggle_inventory_event)
        self.inventory_tree.bind("<space>", self._toggle_inventory_event)
        self.inventory_tree.bind("<<TreeviewOpen>>", self._on_inventory_tree_open)
        self.inventory_tree.bind(
            "<<TreeviewSelect>>", self._on_inventory_selection_changed
        )
        inventory_actions = ttk.Frame(inventory, style="Panel.TFrame")
        inventory_actions.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        inventory_actions.columnconfigure(0, weight=1)
        inventory_actions.columnconfigure(1, weight=1)
        self.inventory_add_button = ttk.Button(
            inventory_actions,
            command=lambda: self._set_inventory_selection_owned(True),
        )
        self.inventory_add_button.grid(
            row=0, column=0, sticky="ew", padx=(0, 2)
        )
        self.inventory_remove_button = ttk.Button(
            inventory_actions,
            command=lambda: self._set_inventory_selection_owned(False),
        )
        self.inventory_remove_button.grid(
            row=0, column=1, sticky="ew", padx=(2, 0)
        )
        slot_actions = ttk.Frame(inventory, style="Panel.TFrame")
        slot_actions.grid(row=4, column=0, sticky="ew", pady=(5, 0))
        for index in range(4):
            slot_actions.columnconfigure(index, weight=1)
        self.inventory_slot_buttons: list[ttk.Button] = []
        for index, slot in enumerate(PHYSICAL_NAMES):
            button = ttk.Button(
                slot_actions,
                command=lambda i=index: self._set_selected_product_to_slot(i),
                state="disabled",
            )
            button.grid(
                row=0,
                column=index,
                sticky="ew",
                padx=(0 if index == 0 else 2, 0 if index == 3 else 2),
            )
            self.inventory_slot_buttons.append(button)
        self.body_paned.add(inventory, weight=0)

        body_outer = ttk.Frame(self.body_paned, style="Panel.TFrame")
        body_outer.columnconfigure(0, weight=1)
        body_outer.rowconfigure(0, weight=1)
        self.body_canvas = tk.Canvas(
            body_outer,
            bg="#171D27",
            highlightthickness=0,
            borderwidth=0,
        )
        self.body_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            body_outer,
            orient="vertical",
            command=self.body_canvas.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.body_canvas.configure(yscrollcommand=scrollbar.set)
        self.cards_host = ttk.Frame(
            self.body_canvas,
            style="Panel.TFrame",
            padding=(4, 2),
        )
        self.cards_host.columnconfigure(0, weight=1)
        self._cards_window_id = self.body_canvas.create_window(
            (0, 0),
            anchor="nw",
            window=self.cards_host,
        )
        self.cards_host.bind("<Configure>", self._on_cards_configure)
        self.body_canvas.bind("<Configure>", self._on_canvas_configure)
        self.body_paned.add(body_outer, weight=1)

        self.slot_frames: list[ttk.LabelFrame] = []
        self.current_swatches: list[tk.Label] = []
        self.current_labels: list[ttk.Label] = []
        self.heading_labels: list[dict[str, ttk.Label]] = []
        self.candidate_rows: list[list[dict[str, object]]] = []
        for slot_index, slot_name in enumerate(PHYSICAL_NAMES):
            card = ttk.LabelFrame(
                self.cards_host,
                text=slot_name,
                padding=(9, 6),
            )
            card.grid(row=slot_index, column=0, sticky="ew", pady=3)
            card.columnconfigure(1, weight=1)
            self.slot_frames.append(card)

            current_swatch = tk.Label(
                card,
                width=4,
                height=1,
                bg=_NEUTRAL_SWATCH,
                relief="flat",
            )
            current_swatch.grid(row=0, column=0, sticky="w", padx=(0, 7), pady=(0, 4))
            self.current_swatches.append(current_swatch)
            current_label = ttk.Label(
                card,
                style="Panel.TLabel",
                font=("Consolas", 10, "bold"),
            )
            current_label.grid(row=0, column=1, columnspan=6, sticky="w", pady=(0, 4))
            self.current_labels.append(current_label)

            headings = {
                "product": ttk.Label(card, style="PanelMuted.TLabel"),
                "hex": ttk.Label(card, style="PanelMuted.TLabel"),
                "delta": ttk.Label(card, style="PanelMuted.TLabel"),
                "finish": ttk.Label(card, style="PanelMuted.TLabel"),
                "source": ttk.Label(card, style="PanelMuted.TLabel"),
            }
            ttk.Label(card, text="", style="PanelMuted.TLabel", width=4).grid(
                row=1, column=0
            )
            headings["product"].grid(row=1, column=1, sticky="w")
            headings["hex"].grid(row=1, column=2, sticky="w", padx=5)
            headings["delta"].grid(row=1, column=3, sticky="w", padx=5)
            headings["finish"].grid(row=1, column=4, sticky="w", padx=5)
            headings["source"].grid(row=1, column=5, sticky="w", padx=5)
            self.heading_labels.append(headings)

            slot_rows: list[dict[str, object]] = []
            for candidate_index in range(self.CANDIDATES_PER_SLOT):
                row_number = candidate_index + 2
                swatch = tk.Label(
                    card,
                    width=4,
                    height=1,
                    bg=_NEUTRAL_SWATCH,
                    relief="flat",
                )
                swatch.grid(row=row_number, column=0, padx=(0, 7), pady=2)
                product = ttk.Label(
                    card,
                    text="—",
                    style="Panel.TLabel",
                    justify="left",
                    wraplength=410,
                )
                product.grid(row=row_number, column=1, sticky="w", pady=2)
                candidate_hex = ttk.Label(
                    card,
                    text="—",
                    style="Panel.TLabel",
                    font=("Consolas", 9, "bold"),
                )
                candidate_hex.grid(row=row_number, column=2, sticky="w", padx=5)
                delta = ttk.Label(card, text="—", style="Panel.TLabel", width=7)
                delta.grid(row=row_number, column=3, sticky="w", padx=5)
                finish = ttk.Label(
                    card,
                    text="—",
                    style="Panel.TLabel",
                    width=18,
                    anchor="w",
                )
                finish.grid(row=row_number, column=4, sticky="w", padx=5)
                source = ttk.Label(
                    card,
                    text="—",
                    style="Panel.TLabel",
                    width=9,
                    anchor="w",
                )
                source.grid(row=row_number, column=5, sticky="w", padx=5)
                apply_button = ttk.Button(card, state="disabled", width=14)
                apply_button.grid(row=row_number, column=6, sticky="e", padx=(8, 0), pady=2)
                slot_rows.append(
                    {
                        "swatch": swatch,
                        "product": product,
                        "hex": candidate_hex,
                        "delta": delta,
                        "finish": finish,
                        "source": source,
                        "apply": apply_button,
                    }
                )
            self.candidate_rows.append(slot_rows)

        footer = ttk.Frame(self.window, style="Panel.TFrame", padding=(12, 7))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.notice_label = ttk.Label(
            footer,
            foreground="#FFBF69",
            background="#171D27",
            justify="left",
            wraplength=900,
        )
        self.notice_label.grid(row=0, column=0, sticky="w")
        self.move_hint_label = ttk.Label(footer, style="PanelMuted.TLabel")
        self.move_hint_label.grid(row=1, column=0, sticky="w", pady=(3, 0))

    def show(self) -> None:
        if self._closed:
            return
        self.window.deiconify()
        self.window.lift()
        self._refresh_current_colors()
        self._refresh_auto_target()
        self._schedule_search(delay_ms=0)

    def hide(self) -> None:
        if self._closed:
            return
        self.window.withdraw()

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._search_after_id is not None:
            try:
                self.window.after_cancel(self._search_after_id)
            except tk.TclError:
                pass
            self._search_after_id = None
        if self._poll_after_id is not None:
            try:
                self.window.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
            self._poll_after_id = None
        if self._auto_watch_after_id is not None:
            try:
                self.window.after_cancel(self._auto_watch_after_id)
            except tk.TclError:
                pass
            self._auto_watch_after_id = None
        for variable, token in self._color_trace_tokens:
            try:
                variable.trace_remove("write", token)
            except tk.TclError:
                pass
        self._color_trace_tokens.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def set_language(self) -> None:
        if self._closed:
            return
        tr = self.i18n.text
        self.window.title(tr("filament_candidates.title"))
        self.title_label.configure(text=tr("filament_candidates.title"))
        self.intro_label.configure(text=tr("filament_candidates.intro"))
        self.brand_label.configure(text=tr("filament_candidates.brand"))
        self.finish_label.configure(text=tr("filament_candidates.finish"))
        self.scope_label.configure(text=tr("filament_candidates.mode"))
        self.scope_all_radio.configure(text=tr("filament_candidates.mode_all"))
        self.scope_owned_radio.configure(text=tr("filament_candidates.mode_owned"))
        self.auto_owned_button.configure(text=tr("filament_candidates.auto_owned"))
        self.prefer_measured_check.configure(
            text=tr("filament_candidates.prefer_measured")
        )
        self.refresh_button.configure(text=tr("filament_candidates.refresh"))
        self.notice_label.configure(text=tr("filament_candidates.notice"))
        self.move_hint_label.configure(text=tr("filament_candidates.move_hint"))
        self.inventory_frame.configure(text=tr("filament_candidates.inventory"))
        self.inventory_help_label.configure(
            text=tr("filament_candidates.inventory_help")
        )
        self.inventory_tree.heading(
            "#0", text=tr("filament_candidates.inventory_product")
        )
        self.inventory_tree.heading(
            "owned", text=tr("filament_candidates.inventory_owned")
        )
        self.inventory_tree.heading("hex", text=tr("filament_candidates.hex"))
        self.inventory_tree.heading(
            "finish", text=tr("filament_candidates.finish")
        )
        self.inventory_add_button.configure(
            text=tr("filament_candidates.inventory_add")
        )
        self.inventory_remove_button.configure(
            text=tr("filament_candidates.inventory_remove")
        )
        for index, button in enumerate(self.inventory_slot_buttons):
            button.configure(
                text=tr(
                    "filament_candidates.set_slot", slot=PHYSICAL_NAMES[index]
                )
            )
        self._refresh_filter_values()
        for slot_index, slot_name in enumerate(PHYSICAL_NAMES):
            self.slot_frames[slot_index].configure(text=slot_name)
            headings = self.heading_labels[slot_index]
            headings["product"].configure(text=tr("filament_candidates.product"))
            headings["hex"].configure(text=tr("filament_candidates.hex"))
            headings["delta"].configure(text=tr("filament_candidates.delta"))
            headings["finish"].configure(text=tr("filament_candidates.finish"))
            headings["source"].configure(text=tr("filament_candidates.source"))
        self._refresh_current_colors()
        self._refresh_auto_target()
        self._render_inventory_tree()
        self._render_results(self._last_results)
        if self._database_available is False:
            self._set_unavailable_status(self._database_reason)

    def _on_cards_configure(self, _event: tk.Event | None = None) -> None:
        self.body_canvas.configure(scrollregion=self.body_canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.body_canvas.itemconfigure(self._cards_window_id, width=max(1, event.width))

    def _on_mouse_wheel(self, event: tk.Event) -> str | None:
        """Scroll candidates only while the pointer is over the body area."""

        try:
            if self.window.state() in {"withdrawn", "iconic"}:
                return None
            widget = self.window.winfo_containing(event.x_root, event.y_root)
        except (AttributeError, tk.TclError):
            return None
        current = widget
        inside_body = False
        while current is not None:
            if current is self.body_canvas or current is self.cards_host:
                inside_body = True
                break
            if current is self.window:
                break
            current = getattr(current, "master", None)
        delta = int(getattr(event, "delta", 0))
        if not inside_body or delta == 0:
            return None
        notches = max(1, abs(delta) // 120)
        self.body_canvas.yview_scroll(
            (-notches if delta > 0 else notches),
            "units",
        )
        return "break"

    def _on_filter_changed(self, _event: tk.Event | None = None) -> None:
        all_label = self.i18n.text("filament_candidates.all")
        brand = self.brand_var.get().strip()
        finish_display = self.finish_var.get().strip()
        self._brand_filter = None if not brand or brand == all_label else brand
        self._finish_filter = self._finish_display_to_value.get(
            finish_display,
            None if not finish_display or finish_display == all_label else finish_display,
        )
        self._schedule_search(delay_ms=0)

    def _on_candidate_scope_changed(self) -> None:
        if self.candidate_scope_var.get() not in {"all", "owned"}:
            self.candidate_scope_var.set("all")
        self._schedule_search(delay_ms=0)

    def _active_target_name(self) -> str:
        key = getattr(self.app, "active_part_key", None)
        prepared = getattr(self.app, "prepared", None)
        if key is None or prepared is None:
            return self.i18n.text("filament_candidates.auto_common")
        try:
            part_id = prepared.final.part_keys.index(key)
            return str(prepared.final.part_names[part_id])
        except (AttributeError, IndexError, ValueError):
            return str(key)

    def _active_material(self) -> str:
        try:
            palette = self.app._active_palette_for_controls()
            return str(palette.material)
        except (AttributeError, TypeError, ValueError):
            return "PLA"

    def _refresh_auto_target(self) -> None:
        self.auto_target_var.set(
            self.i18n.text(
                "filament_candidates.auto_target",
                target=f"{self._active_target_name()} [{self._active_material()}]",
            )
        )

    def _on_target_color_changed(self, *_args: object) -> None:
        if self._closed:
            return
        self._refresh_current_colors()
        self._refresh_auto_target()
        try:
            visible = self.window.state() != "withdrawn"
        except tk.TclError:
            visible = False
        if visible:
            self._schedule_search(delay_ms=350)

    def _refresh_current_colors(self) -> None:
        for index, variable in enumerate(self.app.physical_vars):
            raw = str(variable.get()).strip().upper()
            try:
                color = normalize_hex(raw)
            except ValueError:
                color = raw or "—"
                swatch = _NEUTRAL_SWATCH
            else:
                swatch = color
            self.current_swatches[index].configure(bg=swatch)
            identity = ""
            get_ref = getattr(self.app, "_active_physical_filament_ref", None)
            ref = get_ref(index) if callable(get_ref) else None
            if ref is not None:
                label = str(getattr(ref, "label", "")).strip()
                finish = str(getattr(ref, "finish_class", "")).strip()
                source = str(getattr(ref, "source", "")).strip()
                product_id = str(getattr(ref, "product_id", "")).strip()
                details = " / ".join(
                    value
                    for value in (
                        label,
                        self._finish_display(finish) if finish else "",
                        source,
                        product_id,
                    )
                    if value
                )
                if details:
                    identity = f"  |  {details}"
            self.current_labels[index].configure(
                text=(
                    self.i18n.text("filament_candidates.current", color=color)
                    + identity
                )
            )

    @staticmethod
    def _product_id(product: object) -> str:
        return str(_match_value(product, "product_id", "")).strip()

    @staticmethod
    def _product_hex(product: object) -> str:
        try:
            return normalize_hex(str(_match_value(product, "matched_hex", "")))
        except ValueError:
            return _NEUTRAL_SWATCH

    @staticmethod
    def _product_tree_label(product: object) -> str:
        series = str(_match_value(product, "series", "")).strip()
        name = str(_match_value(product, "color_name", "")).strip()
        return " / ".join(value for value in (series, name) if value) or "—"

    def _inventory_revision(self) -> tuple[tuple[str, str], ...]:
        products = (
            tuple(getattr(self._owned_inventory, "products", ()))
            if self._owned_inventory is not None
            else tuple(
                self._product_by_id[product_id]
                for product_id in sorted(self._owned_product_ids)
                if product_id in self._product_by_id
            )
        )
        return tuple(
            sorted(
                (
                    self._product_id(product),
                    self._product_hex(product),
                )
                for product in products
                if self._product_id(product)
            )
        )

    def _update_inventory_products(
        self,
        products: tuple[object, ...],
        inventory: object | None,
    ) -> None:
        current_products = {
            self._product_id(product): product
            for product in products
            if self._product_id(product)
        }
        if inventory is not None:
            for product in tuple(getattr(inventory, "products", ())):
                if str(_match_value(product, "material", "PLA")) != self._active_material():
                    continue
                product_id = self._product_id(product)
                if product_id and product_id not in current_products:
                    current_products[product_id] = product
            self._owned_inventory = inventory
            self._owned_product_ids = {
                str(value)
                for value in tuple(getattr(inventory, "product_ids", ()))
                if str(value)
            }
            self._inventory_stale_ids = tuple(
                str(value)
                for value in tuple(getattr(inventory, "stale_product_ids", ()))
            )
            self._inventory_unresolved_ids = tuple(
                str(value)
                for value in tuple(getattr(inventory, "unresolved_product_ids", ()))
            )
            self._inventory_loaded = True
        self._product_by_id = current_products
        self._all_products = tuple(
            sorted(
                current_products.values(),
                key=lambda product: (
                    str(_match_value(product, "brand", "")).casefold(),
                    str(_match_value(product, "series", "")).casefold(),
                    str(_match_value(product, "color_name", "")).casefold(),
                    self._product_id(product),
                ),
            )
        )
        self._render_inventory_tree()

    def _render_inventory_tree(self) -> None:
        tree = getattr(self, "inventory_tree", None)
        if tree is None:
            return
        selected_product_id = None
        selected_brand = None
        selection = tree.selection()
        if selection:
            selected_product_id = self._inventory_item_to_product_id.get(selection[0])
            selected_brand = self._inventory_item_to_brand.get(selection[0])
        grouped: dict[str, list[object]] = {}
        for product in self._all_products:
            brand = str(_match_value(product, "brand", "")).strip() or "—"
            grouped.setdefault(brand, []).append(product)
        signature = (
            self.i18n.language,
            tuple(
                (
                    self._product_id(product),
                    self._product_hex(product),
                    str(_match_value(product, "finish_class", "")),
                    self._product_id(product) in self._inventory_stale_ids,
                )
                for product in self._all_products
            ),
            tuple(self._inventory_unresolved_ids),
        )
        if signature == self._inventory_tree_signature:
            self._refresh_inventory_marks()
            return

        expanded_brands = {
            brand
            for item, brand in self._inventory_item_to_brand.items()
            if item in tree.get_children("") and bool(tree.item(item, "open"))
        }
        tree.delete(*tree.get_children(""))
        self._inventory_item_to_product_id.clear()
        self._inventory_item_to_brand.clear()
        self._inventory_brand_to_product_ids.clear()
        self._inventory_brand_to_products.clear()
        self._inventory_tree_signature = signature
        restore_item = None
        for brand_index, brand in enumerate(
            sorted(grouped, key=lambda value: (value.casefold(), value))
        ):
            brand_products = tuple(grouped[brand])
            product_ids = tuple(
                self._product_id(product)
                for product in brand_products
                if self._product_id(product)
            )
            owned_count = sum(
                product_id in self._owned_product_ids for product_id in product_ids
            )
            mark = "☑" if product_ids and owned_count == len(product_ids) else (
                "◩" if owned_count else "☐"
            )
            brand_item = f"brand:{brand_index}"
            tree.insert(
                "",
                "end",
                iid=brand_item,
                text=f"{brand} ({len(product_ids)})",
                values=(mark, "", ""),
                open=brand in expanded_brands,
            )
            self._inventory_item_to_brand[brand_item] = brand
            self._inventory_brand_to_product_ids[brand] = product_ids
            self._inventory_brand_to_products[brand] = brand_products
            if selected_brand == brand and selected_product_id is None:
                restore_item = brand_item
            tree.insert(brand_item, "end", iid=f"dummy:{brand_index}", text="")
            if brand in expanded_brands or (
                selected_product_id is not None
                and selected_product_id in product_ids
            ):
                tree.item(brand_item, open=True)
                self._populate_inventory_brand(brand_item)
                if selected_product_id is not None:
                    restore_item = next(
                        (
                            item
                            for item, product_id in self._inventory_item_to_product_id.items()
                            if product_id == selected_product_id
                        ),
                        restore_item,
                    )

        if self._inventory_unresolved_ids:
            brand = self.i18n.text(
                "filament_candidates.inventory_unresolved",
                count=len(self._inventory_unresolved_ids),
            )
            unresolved_item = "unresolved"
            tree.insert(
                "",
                "end",
                iid=unresolved_item,
                text=brand,
                values=("!", "", ""),
                open=True,
            )
            self._inventory_item_to_brand[unresolved_item] = brand
            self._inventory_brand_to_product_ids[brand] = tuple(
                self._inventory_unresolved_ids
            )
            for index, product_id in enumerate(self._inventory_unresolved_ids):
                item = f"unresolved:{index}"
                tree.insert(
                    unresolved_item,
                    "end",
                    iid=item,
                    text=product_id,
                    values=("!", "", ""),
                )
                self._inventory_item_to_product_id[item] = product_id
                self._inventory_item_to_brand[item] = brand

        if restore_item is not None and tree.exists(restore_item):
            tree.selection_set(restore_item)
            tree.see(restore_item)
        self.inventory_count_var.set(
            self.i18n.text(
                "filament_candidates.inventory_count",
                count=len(self._owned_product_ids),
            )
        )
        self._on_inventory_selection_changed()

    def _populate_inventory_brand(self, brand_item: str) -> None:
        brand = self._inventory_item_to_brand.get(brand_item)
        if brand is None:
            return
        children = self.inventory_tree.get_children(brand_item)
        if children and not all(str(item).startswith("dummy:") for item in children):
            return
        for item in children:
            self.inventory_tree.delete(item)
        brand_products = self._inventory_brand_to_products.get(brand, ())
        brand_index = str(brand_item).split(":", 1)[-1]
        for product_index, product in enumerate(brand_products):
            product_id = self._product_id(product)
            if not product_id:
                continue
            item = f"product:{brand_index}:{product_index}"
            stale = product_id in self._inventory_stale_ids
            label = self._product_tree_label(product)
            if stale:
                label += "  [saved]"
            self.inventory_tree.insert(
                brand_item,
                "end",
                iid=item,
                text=label,
                values=(
                    "☑" if product_id in self._owned_product_ids else "☐",
                    self._product_hex(product),
                    self._finish_display(
                        str(_match_value(product, "finish_class", ""))
                    ),
                ),
            )
            self._inventory_item_to_product_id[item] = product_id
            self._inventory_item_to_brand[item] = brand

    def _on_inventory_tree_open(self, _event: tk.Event | None = None) -> None:
        item = self.inventory_tree.focus()
        if item:
            self._populate_inventory_brand(item)

    def _refresh_inventory_marks(self) -> None:
        for brand_item in self.inventory_tree.get_children(""):
            if str(brand_item) == "unresolved":
                continue
            brand = self._inventory_item_to_brand.get(brand_item)
            if brand is None:
                continue
            product_ids = self._inventory_brand_to_product_ids.get(brand, ())
            owned_count = sum(
                product_id in self._owned_product_ids for product_id in product_ids
            )
            mark = "☑" if product_ids and owned_count == len(product_ids) else (
                "◩" if owned_count else "☐"
            )
            values = list(self.inventory_tree.item(brand_item, "values"))
            if values:
                values[0] = mark
                self.inventory_tree.item(brand_item, values=values)
        for item, product_id in self._inventory_item_to_product_id.items():
            if not self.inventory_tree.exists(item):
                continue
            values = list(self.inventory_tree.item(item, "values"))
            if values:
                values[0] = "☑" if product_id in self._owned_product_ids else "☐"
                self.inventory_tree.item(item, values=values)
        self.inventory_count_var.set(
            self.i18n.text(
                "filament_candidates.inventory_count",
                count=len(self._owned_product_ids),
            )
        )
        self._on_inventory_selection_changed()

    def _selected_inventory_item(self) -> str | None:
        selection = self.inventory_tree.selection()
        return selection[0] if selection else None

    def _on_inventory_selection_changed(
        self, _event: tk.Event | None = None
    ) -> None:
        item = self._selected_inventory_item()
        is_product = bool(
            item
            and self._inventory_item_to_product_id.get(item) in self._product_by_id
        )
        state = "normal" if is_product else "disabled"
        for button in self.inventory_slot_buttons:
            button.configure(state=state)

    def _toggle_inventory_event(self, event: tk.Event | None = None) -> str:
        item = self._selected_inventory_item()
        if event is not None and hasattr(event, "y"):
            row = self.inventory_tree.identify_row(int(event.y))
            if row:
                item = row
                self.inventory_tree.selection_set(row)
        if item is None:
            return "break"
        product_id = self._inventory_item_to_product_id.get(item)
        brand = self._inventory_item_to_brand.get(item)
        if product_id is not None:
            self._set_inventory_ids_owned(
                (product_id,), product_id not in self._owned_product_ids
            )
        elif brand is not None:
            product_ids = self._inventory_brand_to_product_ids.get(brand, ())
            make_owned = not all(
                value in self._owned_product_ids for value in product_ids
            )
            self._set_inventory_ids_owned(product_ids, make_owned)
        return "break"

    def _set_inventory_selection_owned(self, owned: bool) -> None:
        item = self._selected_inventory_item()
        if item is None:
            return
        product_id = self._inventory_item_to_product_id.get(item)
        if product_id is not None:
            product_ids = (product_id,)
        else:
            brand = self._inventory_item_to_brand.get(item)
            product_ids = self._inventory_brand_to_product_ids.get(brand or "", ())
        self._set_inventory_ids_owned(product_ids, owned)

    def _set_inventory_ids_owned(
        self, product_ids: tuple[str, ...], owned: bool
    ) -> None:
        product_ids = tuple(str(value) for value in product_ids if str(value))
        previous_owned_product_ids = set(self._owned_product_ids)
        previous_inventory = self._owned_inventory
        previous_unresolved_ids = self._inventory_unresolved_ids
        previous_stale_ids = self._inventory_stale_ids
        if owned:
            self._owned_product_ids.update(product_ids)
        else:
            self._owned_product_ids.difference_update(product_ids)
        unresolved_ids = set(self._inventory_unresolved_ids)
        if owned:
            unresolved_ids.update(
                product_id
                for product_id in product_ids
                if product_id not in self._product_by_id
            )
        else:
            unresolved_ids.difference_update(product_ids)
        self._inventory_unresolved_ids = tuple(
            sorted(unresolved_ids, key=lambda value: (value.casefold(), value))
        )
        selected_products = tuple(
            self._product_by_id[product_id]
            for product_id in sorted(self._owned_product_ids)
            if product_id in self._product_by_id
        )
        try:
            from .owned_filaments import (
                OwnedFilamentInventory,
                save_owned_filament_inventory,
            )

            inventory = OwnedFilamentInventory(
                products=selected_products,
                stale_product_ids=tuple(
                    product_id
                    for product_id in self._inventory_stale_ids
                    if product_id in self._owned_product_ids
                ),
                unresolved_product_ids=self._inventory_unresolved_ids,
            )
            save_owned_filament_inventory(inventory)
            self._owned_inventory = inventory
            self._inventory_stale_ids = tuple(
                getattr(inventory, "stale_product_ids", ())
            )
            self.status_var.set(
                self.i18n.text(
                    "filament_candidates.inventory_saved",
                    count=len(selected_products),
                )
            )
        except Exception as exc:
            # Saving is the commit point.  Keep the visible checks, the
            # in-memory inventory used by automatic selection, and its
            # revision on the last successfully persisted snapshot.
            self._owned_product_ids = previous_owned_product_ids
            self._owned_inventory = previous_inventory
            self._inventory_unresolved_ids = previous_unresolved_ids
            self._inventory_stale_ids = previous_stale_ids
            self.status_var.set(
                self.i18n.text(
                    "filament_candidates.inventory_save_error", reason=str(exc)
                )
            )
            self._render_inventory_tree()
            return
        self._render_inventory_tree()
        self._schedule_search(delay_ms=0)

    def _set_selected_product_to_slot(self, slot_index: int) -> None:
        item = self._selected_inventory_item()
        product_id = self._inventory_item_to_product_id.get(item or "")
        product = self._product_by_id.get(product_id or "")
        if product is None:
            messagebox.showinfo(
                self.i18n.text("filament_candidates.inventory"),
                self.i18n.text("filament_candidates.select_product"),
                parent=self.window,
            )
            return
        if not 0 <= slot_index < len(self.app.physical_vars):
            return
        if product_id not in self._owned_product_ids:
            self._set_inventory_ids_owned((str(product_id),), True)
        color = self._product_hex(product)
        if color == _NEUTRAL_SWATCH:
            return
        assign_product = getattr(
            self.app, "_set_physical_filament_product", None
        )
        if not callable(assign_product):
            self.app.physical_vars[slot_index].set(color)
            self.app.enabled_vars[slot_index].set(True)
        elif not assign_product(slot_index, product):
            if hasattr(product, "material") or self._active_material() != "PLA":
                return
            # Legacy injected PLA-only candidate without a stable product ID.
            self.app.physical_vars[slot_index].set(color)
            self.app.enabled_vars[slot_index].set(True)
        self.app.status_var.set(
            self.i18n.text(
                "filament_candidates.applied",
                slot=PHYSICAL_NAMES[slot_index],
                color=color,
                brand=str(_match_value(product, "brand", "")),
                name=str(_match_value(product, "color_name", "")),
            )
        )

    def _auto_build_from_owned(self) -> None:
        if self._auto_in_progress:
            return
        if getattr(self.app, "prepared", None) is None:
            messagebox.showinfo(
                self.i18n.text("filament_candidates.auto_owned"),
                self.i18n.text("filament_candidates.auto_no_obj"),
                parent=self.window,
            )
            return
        if self._inventory_unresolved_ids:
            messagebox.showwarning(
                self.i18n.text("filament_candidates.auto_owned"),
                self.i18n.text(
                    "filament_candidates.auto_missing",
                    count=len(self._inventory_unresolved_ids),
                ),
                parent=self.window,
            )
            return
        material = self._active_material()
        inventory = self._owned_inventory
        if inventory is not None:
            all_owned_products = tuple(
                product
                for product in getattr(inventory, "products", ())
                if str(_match_value(product, "material", "PLA")) == material
            )
            recommendable_for_material = getattr(
                inventory, "recommendable_for_material", None
            )
            products = (
                tuple(recommendable_for_material(material))
                if callable(recommendable_for_material)
                else ()
            )
            if not products:
                products = all_owned_products
        else:
            all_owned_products = tuple(
                self._product_by_id[product_id]
                for product_id in sorted(self._owned_product_ids)
                if product_id in self._product_by_id
                and str(
                    _match_value(self._product_by_id[product_id], "material", "PLA")
                ) == material
            )
            unique_by_hex = {
                self._product_hex(product): product
                for product in all_owned_products
            }
            products = tuple(unique_by_hex.values())
        if len(all_owned_products) < 4:
            messagebox.showwarning(
                self.i18n.text("filament_candidates.auto_owned"),
                self.i18n.text(
                    "filament_candidates.auto_need_four",
                    count=len(all_owned_products),
                ),
                parent=self.window,
            )
            return
        distinct_color_count = len(
            {self._product_hex(product) for product in all_owned_products}
        )
        if distinct_color_count == 1:
            messagebox.showwarning(
                self.i18n.text("filament_candidates.auto_owned"),
                self.i18n.text("filament_candidates.auto_same_color"),
                parent=self.window,
            )
            return
        if len(products) < 4:
            messagebox.showwarning(
                self.i18n.text("filament_candidates.auto_owned"),
                self.i18n.text(
                    "filament_candidates.auto_need_distinct",
                    count=distinct_color_count,
                ),
                parent=self.window,
            )
            return
        if self._inventory_stale_ids and not messagebox.askyesno(
            self.i18n.text("filament_candidates.auto_stale_title"),
            self.i18n.text(
                "filament_candidates.auto_stale",
                count=len(self._inventory_stale_ids),
            ),
            parent=self.window,
        ):
            return
        configure = getattr(self.app, "_configure_from_owned_filaments", None)
        if not callable(configure):
            self.status_var.set(
                self.i18n.text(
                    "filament_candidates.error",
                    reason="owned-filament optimizer is unavailable",
                )
            )
            return
        self._auto_in_progress = True
        self.auto_owned_button.configure(state="disabled")
        self.status_var.set(self.i18n.text("filament_candidates.auto_running"))
        started = bool(
            configure(
                all_owned_products,
                inventory_revision=self._inventory_revision(),
                dialog_parent=self.window,
                on_finished=self._auto_build_finished,
            )
        )
        if not started:
            self._auto_build_finished(False)

    def _auto_build_finished(self, _applied: bool = False) -> None:
        if self._closed:
            return
        self._auto_in_progress = False
        self.auto_owned_button.configure(state="normal")
        self._refresh_auto_target()

    def _schedule_search(self, *, delay_ms: int) -> None:
        if self._closed:
            return
        # Invalidate immediately, before the debounce expires.  Otherwise a
        # part/palette switch could leave an Apply button for results computed
        # from the previous F color briefly active.
        self._search_generation += 1
        self._result_target_hexes = None
        self._last_results = ((), (), (), ())
        self._render_results(self._last_results)
        for rows in self.candidate_rows:
            rows[0]["product"].configure(
                text=self.i18n.text("filament_candidates.searching")
            )
        self.status_var.set(self.i18n.text("filament_candidates.searching"))
        self.refresh_button.state(["disabled"])
        if self._search_after_id is not None:
            try:
                self.window.after_cancel(self._search_after_id)
            except tk.TclError:
                pass
        self._search_after_id = self.window.after(
            max(0, int(delay_ms)),
            self._start_search,
        )

    def _start_search(self) -> None:
        self._search_after_id = None
        if self._closed:
            return
        try:
            target_hexes = tuple(
                normalize_hex(variable.get()) for variable in self.app.physical_vars
            )
        except ValueError as exc:
            self.status_var.set(
                self.i18n.text("filament_candidates.error", reason=str(exc))
            )
            return
        self._search_generation += 1
        generation = self._search_generation
        snapshot = (
            target_hexes,
            self._active_material(),
            self._brand_filter,
            self._finish_filter,
            bool(self.prefer_measured_var.get()),
            self.candidate_scope_var.get(),
            self._owned_inventory,
        )
        self.status_var.set(self.i18n.text("filament_candidates.searching"))
        self.refresh_button.state(["disabled"])
        self._executor.submit(self._search_worker, generation, snapshot)

    def _create_matcher(self) -> object:
        from .filament_database import (
            FilamentMatcher,
            resolve_filament_database_path,
        )

        return FilamentMatcher(resolve_filament_database_path())

    def _search_worker(
        self,
        generation: int,
        snapshot: tuple[
            tuple[str, ...],
            str,
            str | None,
            str | None,
            bool,
            str,
            object | None,
        ],
    ) -> None:
        matcher = self._matcher
        if matcher is None:
            try:
                matcher = self._create_matcher()
                self._matcher = matcher
            except Exception as exc:
                self._result_queue.put(("unavailable", generation, str(exc)))
                return
        try:
            (
                target_hexes,
                material,
                brand,
                finish,
                prefer_measured,
                candidate_scope,
                inventory_snapshot,
            ) = snapshot
            if not bool(getattr(matcher, "is_available", False)):
                reason = str(
                    getattr(matcher, "error_message", "")
                    or "database is unavailable"
                )
                inventory = inventory_snapshot
                try:
                    from .owned_filaments import load_owned_filament_inventory

                    inventory = load_owned_filament_inventory(
                        prefer_measured=prefer_measured
                    )
                except Exception:
                    pass
                products = tuple(
                    product
                    for product in tuple(getattr(inventory, "products", ()))
                    if str(_match_value(product, "material", "PLA")) == material
                )
                brands = tuple(
                    sorted(
                        {
                            str(_match_value(product, "brand", ""))
                            for product in products
                            if str(_match_value(product, "brand", ""))
                        },
                        key=lambda value: (value.casefold(), value),
                    )
                )
                finishes = tuple(
                    sorted(
                        {
                            str(_match_value(product, "finish_class", ""))
                            for product in products
                            if str(_match_value(product, "finish_class", ""))
                        },
                        key=lambda value: (value.casefold(), value),
                    )
                )
                results = (
                    tuple(
                        self._rank_owned_products(
                            target,
                            products,
                            material=material,
                            brand=brand,
                            finish=finish,
                            stale_product_ids=tuple(
                                getattr(inventory, "stale_product_ids", ())
                            ),
                        )
                        for target in target_hexes
                    )
                    if candidate_scope == "owned"
                    else ((), (), (), ())
                )
                self._result_queue.put(
                    (
                        "snapshot_done",
                        generation,
                        (
                            results,
                            brands,
                            finishes,
                            target_hexes,
                            products,
                            inventory,
                            reason,
                            candidate_scope,
                        ),
                    )
                )
                return
            try:
                brands = tuple(matcher.available_brands(material=material))
                finishes = tuple(
                    matcher.available_finish_classes(material=material)
                )
            except TypeError:
                # Compatibility for injected beta/test matchers predating the
                # material keyword.  Their records are PLA-only by contract.
                if material != "PLA":
                    raise
                brands = tuple(matcher.available_brands())
                finishes = tuple(matcher.available_finish_classes())
            repository = getattr(matcher, "repository", None)
            products: tuple[object, ...] = ()
            inventory = inventory_snapshot
            inventory_error = ""
            if repository is not None and hasattr(repository, "list_products"):
                try:
                    products = tuple(
                        repository.list_products(
                            prefer_measured=prefer_measured,
                            material=material,
                        )
                    )
                except TypeError:
                    if material != "PLA":
                        raise
                    products = tuple(
                        repository.list_products(
                            prefer_measured=prefer_measured
                        )
                    )
                try:
                    from .owned_filaments import load_owned_filament_inventory

                    inventory = load_owned_filament_inventory(
                        repository=repository,
                        prefer_measured=prefer_measured,
                    )
                except Exception as exc:
                    inventory_error = str(exc)
            if candidate_scope == "owned":
                owned_products = tuple(
                    product
                    for product in getattr(inventory, "products", ())
                    if str(_match_value(product, "material", "PLA")) == material
                ) if inventory is not None else ()
                results = tuple(
                    self._rank_owned_products(
                        target,
                        owned_products,
                        material=material,
                        brand=brand,
                        finish=finish,
                        stale_product_ids=tuple(
                            getattr(inventory, "stale_product_ids", ())
                        ),
                    )
                    for target in target_hexes
                )
            else:
                results = tuple(
                    tuple(
                        self._find_material_matches(
                            matcher,
                            target=target,
                            brand=brand,
                            finish=finish,
                            prefer_measured=prefer_measured,
                            material=material,
                        )
                    )
                    for target in target_hexes
                )
            self._result_queue.put(
                (
                    "done",
                    generation,
                    (
                        results,
                        brands,
                        finishes,
                        target_hexes,
                        products,
                        inventory,
                        inventory_error,
                        candidate_scope,
                    ),
                )
            )
        except Exception as exc:
            self._result_queue.put(("error", generation, str(exc)))

    def _find_material_matches(
        self,
        matcher: object,
        *,
        target: str,
        brand: str | None,
        finish: str | None,
        prefer_measured: bool,
        material: str,
    ) -> tuple[object, ...]:
        keywords = {
            "target_hex": target,
            "limit": self.CANDIDATES_PER_SLOT,
            "brands": None if brand is None else (brand,),
            "finish_classes": None if finish is None else (finish,),
            "prefer_measured": prefer_measured,
        }
        try:
            return tuple(matcher.find_matches(**keywords, material=material))
        except TypeError:
            if material != "PLA":
                raise
            return tuple(matcher.find_matches(**keywords))

    def _rank_owned_products(
        self,
        target_hex: str,
        products: tuple[object, ...],
        *,
        material: str,
        brand: str | None,
        finish: str | None,
        stale_product_ids: tuple[str, ...] = (),
    ) -> tuple[_OwnedProductMatch, ...]:
        from .filament_database import ciede2000, srgb_hex_to_lab

        target_lab = srgb_hex_to_lab(target_hex)
        stale_ids = set(stale_product_ids)
        matches: list[_OwnedProductMatch] = []
        for product in products:
            if str(_match_value(product, "material", "PLA")) != material:
                continue
            product_brand = str(_match_value(product, "brand", ""))
            product_finish = str(_match_value(product, "finish_class", ""))
            if brand is not None and product_brand.casefold() != brand.casefold():
                continue
            if finish is not None and product_finish.casefold() != finish.casefold():
                continue
            matched_hex = self._product_hex(product)
            if matched_hex == _NEUTRAL_SWATCH:
                continue
            delta = ciede2000(target_lab, srgb_hex_to_lab(matched_hex))
            try:
                penalty = float(_match_value(product, "finish_penalty", 0.0))
            except (TypeError, ValueError):
                penalty = 0.0
            matches.append(
                _OwnedProductMatch(
                    product_id=self._product_id(product),
                    brand=product_brand,
                    series=str(_match_value(product, "series", "")),
                    color_name=str(_match_value(product, "color_name", "")),
                    matched_hex=matched_hex,
                    delta_e_2000=float(delta),
                    score=float(delta + max(0.0, penalty)),
                    finish_class=product_finish,
                    source_kind=(
                        "snapshot"
                        if self._product_id(product) in stale_ids
                        else str(_match_value(product, "source_kind", "catalog"))
                    ),
                    source_url=_match_value(product, "source_url", None),
                    record_id=_match_value(product, "record_id", None),
                    measurement_id=_match_value(product, "measurement_id", None),
                    material=str(_match_value(product, "material", "PLA")),
                )
            )
        matches.sort(
            key=lambda match: (
                match.score,
                match.delta_e_2000,
                match.brand.casefold(),
                match.series.casefold(),
                match.color_name.casefold(),
                match.product_id,
            )
        )
        return tuple(matches[: self.CANDIDATES_PER_SLOT])

    def _poll_results(self) -> None:
        self._poll_after_id = None
        if self._closed:
            return
        try:
            while True:
                kind, generation, payload = self._result_queue.get_nowait()
                if generation != self._search_generation:
                    continue
                self.refresh_button.state(["!disabled"])
                if kind in {"done", "snapshot_done"}:
                    (
                        results,
                        brands,
                        finishes,
                        target_hexes,
                        products,
                        inventory,
                        inventory_error,
                        candidate_scope,
                    ) = payload
                    self._set_database_available(kind == "done")
                    if kind == "snapshot_done":
                        self._database_reason = str(inventory_error)
                    self._update_filter_values(brands, finishes)
                    self._update_inventory_products(tuple(products), inventory)
                    self._last_results = tuple(results)
                    self._result_target_hexes = tuple(target_hexes)
                    self._render_results(self._last_results)
                    if kind == "snapshot_done":
                        self.status_var.set(
                            self.i18n.text("filament_candidates.snapshot_only")
                            + (
                                "\n"
                                + self.i18n.text(
                                    "filament_candidates.reason",
                                    reason=inventory_error,
                                )
                                if inventory_error
                                else ""
                            )
                        )
                    elif inventory_error:
                        self.status_var.set(
                            self.i18n.text(
                                "filament_candidates.inventory_save_error",
                                reason=inventory_error,
                            )
                        )
                    elif candidate_scope == "owned" and not any(results):
                        self.status_var.set(
                            self.i18n.text("filament_candidates.inventory_empty")
                        )
                    else:
                        self.status_var.set("")
                elif kind == "unavailable":
                    self._set_database_available(False)
                    if isinstance(payload, tuple) and len(payload) == 2:
                        reason, inventory = payload
                    else:
                        reason, inventory = payload, None
                    self._database_reason = str(reason)
                    if inventory is not None:
                        self._update_inventory_products((), inventory)
                    self._result_target_hexes = None
                    self._last_results = ((), (), (), ())
                    self._render_results(self._last_results)
                    self._set_unavailable_status(self._database_reason)
                else:
                    self._set_database_available(True)
                    self._result_target_hexes = None
                    self.status_var.set(
                        self.i18n.text(
                            "filament_candidates.error",
                            reason=str(payload),
                        )
                    )
        except queue.Empty:
            pass
        try:
            self._poll_after_id = self.window.after(80, self._poll_results)
        except tk.TclError:
            self._poll_after_id = None

    def _set_database_available(self, available: bool) -> None:
        self._database_available = bool(available)
        if available:
            self._database_reason = ""
        combo_state = "readonly" if available else "disabled"
        self.brand_combo.configure(state=combo_state)
        self.finish_combo.configure(state=combo_state)
        self.prefer_measured_check.configure(
            state="normal" if available else "disabled"
        )
        if not available:
            self.status_var.set(self.i18n.text("filament_candidates.unavailable"))

    def _set_unavailable_status(self, reason: str) -> None:
        message = self.i18n.text("filament_candidates.unavailable")
        if reason:
            message += "\n" + self.i18n.text(
                "filament_candidates.reason", reason=reason
            )
        self.status_var.set(message)

    def _update_filter_values(
        self,
        brands: tuple[str, ...],
        finishes: tuple[str, ...],
    ) -> None:
        self._available_brands = tuple(brands)
        self._available_finishes = tuple(finishes)
        self._refresh_filter_values()
        self._filters_loaded = True

    def _finish_display(self, finish: str) -> str:
        key = _FINISH_TRANSLATION_KEYS.get(str(finish))
        return self.i18n.text(key) if key is not None else str(finish)

    def _refresh_filter_values(self) -> None:
        all_label = self.i18n.text("filament_candidates.all")
        finish_displays = tuple(
            self._finish_display(value) for value in self._available_finishes
        )
        self._finish_display_to_value = {
            all_label: None,
            **dict(zip(finish_displays, self._available_finishes, strict=True)),
        }
        self.brand_combo.configure(values=(all_label, *self._available_brands))
        self.finish_combo.configure(values=(all_label, *finish_displays))
        self.brand_var.set(self._brand_filter or all_label)
        self.finish_var.set(
            self._finish_display(self._finish_filter)
            if self._finish_filter is not None
            else all_label
        )

    def _source_label(self, match: object) -> str:
        kind = str(_match_value(match, "source_kind", "catalog")).lower()
        if kind == "measured":
            key = "filament_candidates.source_measured"
        elif kind == "snapshot":
            key = "filament_candidates.source_snapshot"
        else:
            key = "filament_candidates.source_catalog"
        return self.i18n.text(key)

    def _render_results(
        self,
        results: tuple[tuple[object, ...], ...],
    ) -> None:
        for slot_index, rows in enumerate(self.candidate_rows):
            matches = results[slot_index] if slot_index < len(results) else ()
            for candidate_index, widgets in enumerate(rows):
                button = widgets["apply"]
                if candidate_index >= len(matches):
                    widgets["swatch"].configure(bg=_NEUTRAL_SWATCH)
                    widgets["product"].configure(
                        text=(
                            self.i18n.text("filament_candidates.none")
                            if candidate_index == 0 and not matches
                            else "—"
                        )
                    )
                    for key in ("hex", "delta", "finish", "source"):
                        widgets[key].configure(text="—")
                    button.configure(
                        text=self.i18n.text("filament_candidates.apply"),
                        state="disabled",
                        command=lambda: None,
                    )
                    continue
                match = matches[candidate_index]
                matched_hex = str(
                    _match_value(match, "matched_hex", _NEUTRAL_SWATCH)
                ).upper()
                try:
                    matched_hex = normalize_hex(matched_hex)
                except ValueError:
                    matched_hex = _NEUTRAL_SWATCH
                brand = str(_match_value(match, "brand", ""))
                series = str(_match_value(match, "series", ""))
                name = str(_match_value(match, "color_name", ""))
                product = " / ".join(
                    value for value in (brand, series, name) if value
                )
                delta = float(_match_value(match, "delta_e_2000", 0.0))
                finish = str(_match_value(match, "finish_class", "")) or "—"
                widgets["swatch"].configure(bg=matched_hex)
                widgets["product"].configure(text=product or "—")
                widgets["hex"].configure(text=matched_hex)
                widgets["delta"].configure(text=f"{delta:.2f}")
                widgets["finish"].configure(text=self._finish_display(finish))
                widgets["source"].configure(text=self._source_label(match))
                button.configure(
                    text=self.i18n.text("filament_candidates.apply"),
                    state="normal",
                    command=lambda i=slot_index, candidate=match: self._confirm_apply(
                        i, candidate
                    ),
                )

    def _confirm_apply(self, slot_index: int, match: object) -> None:
        if not 0 <= slot_index < len(self.app.physical_vars):
            return
        try:
            candidate_hex = normalize_hex(
                str(_match_value(match, "matched_hex", ""))
            )
            current_hex = normalize_hex(self.app.physical_vars[slot_index].get())
        except ValueError:
            return
        result_targets = self._result_target_hexes
        if (
            result_targets is None
            or slot_index >= len(result_targets)
            or current_hex != result_targets[slot_index]
            or slot_index >= len(self._last_results)
            or match not in self._last_results[slot_index]
        ):
            # The F color or filter changed after this row was rendered.  Do
            # not show a misleading confirmation based on stale ΔE values.
            self._schedule_search(delay_ms=0)
            return
        brand = str(_match_value(match, "brand", ""))
        series = str(_match_value(match, "series", ""))
        name = str(_match_value(match, "color_name", ""))
        delta = float(_match_value(match, "delta_e_2000", 0.0))
        if not messagebox.askyesno(
            self.i18n.text("filament_candidates.confirm_title"),
            self.i18n.text(
                "filament_candidates.confirm_message",
                slot=PHYSICAL_NAMES[slot_index],
                current=current_hex,
                candidate=candidate_hex,
                brand=brand,
                series=series,
                name=name,
                delta=delta,
                source=self._source_label(match),
            ),
            parent=self.window,
        ):
            return
        assign_product = getattr(
            self.app, "_set_physical_filament_product", None
        )
        if not callable(assign_product):
            self.app.physical_vars[slot_index].set(candidate_hex)
            self.app.enabled_vars[slot_index].set(True)
        elif not assign_product(slot_index, match):
            if hasattr(match, "material") or self._active_material() != "PLA":
                return
            # Legacy PLA-only matcher rows have no material/product identity.
            self.app.physical_vars[slot_index].set(candidate_hex)
            self.app.enabled_vars[slot_index].set(True)
        self.app.status_var.set(
            self.i18n.text(
                "filament_candidates.applied",
                slot=PHYSICAL_NAMES[slot_index],
                color=candidate_hex,
                brand=brand,
                name=name,
            )
        )


__all__ = ["FilamentCandidateWindow"]
