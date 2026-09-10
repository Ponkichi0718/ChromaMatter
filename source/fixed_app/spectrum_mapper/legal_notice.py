from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk
from typing import Protocol

from .ui_fonts import ui_font


class TextTranslator(Protocol):
    """Small translation surface required by :class:`LegalNoticeWindow`."""

    def text(self, key: str, /, **values: object) -> str: ...


@dataclass(frozen=True, slots=True)
class LegalNoticeResources:
    """Release-specific values shown by the legal notice.

    The exact corresponding-source archive and packaged document names can be
    finalized by the release audit without changing the window implementation.
    A caller may replace this immutable value through ``set_resources``.
    """

    copyright_notice: str
    application_license: str
    tetgen_license: str
    source_url: str
    local_document_locations: tuple[str, ...]

    def validated(self) -> "LegalNoticeResources":
        values = (
            self.copyright_notice,
            self.application_license,
            self.tetgen_license,
            self.source_url,
            *self.local_document_locations,
        )
        if not self.local_document_locations or any(
            not str(value).strip() for value in values
        ):
            raise ValueError("legal notice resources must not contain blank values")
        return self


DEFAULT_LEGAL_NOTICE_RESOURCES = LegalNoticeResources(
    copyright_notice="Copyright (c) 2026 ChromaMatter contributors",
    application_license="GPL-3.0-or-later",
    tetgen_license="AGPL-3.0-or-later",
    source_url="https://github.com/Ponkichi0718/ChromaMatter",
    # Keep this directory-level until the exact release document set is frozen.
    local_document_locations=("licenses/",),
).validated()


LEGAL_NOTICE_TEXT_KEYS = (
    "legal_notice.title",
    "legal_notice.application",
    "legal_notice.no_warranty",
    "legal_notice.rights",
    "legal_notice.third_party",
    "legal_notice.source_heading",
    "legal_notice.source_url",
    "legal_notice.local_documents",
    "legal_notice.governing_terms",
    "legal_notice.close",
)


def compute_legal_notice_layout(
    screen_width: object,
    screen_height: object,
) -> tuple[str, tuple[int, int]]:
    """Return centered geometry clamped to the available screen."""

    try:
        width_limit = max(1, int(screen_width))
    except (TypeError, ValueError, OverflowError):
        width_limit = 1
    try:
        height_limit = max(1, int(screen_height))
    except (TypeError, ValueError, OverflowError):
        height_limit = 1

    horizontal_margin = min(28, max(0, width_limit // 20))
    vertical_margin = min(24, max(0, height_limit // 24))
    width = max(1, min(760, width_limit - 2 * horizontal_margin))
    height = max(1, min(560, height_limit - 2 * vertical_margin))
    x = max(0, min(width_limit - width, (width_limit - width) // 2))
    y = max(0, min(height_limit - height, (height_limit - height) // 2))
    minimum = (min(600, width), min(420, height))
    return f"{width}x{height}+{x}+{y}", minimum


class LegalNoticeWindow:
    """Reusable non-modal window for the program's legal/source notice."""

    _PARENT_ATTRIBUTE = "_spectrum_mapper_legal_notice"

    def __init__(
        self,
        parent: tk.Misc,
        translator: TextTranslator,
        *,
        resources: LegalNoticeResources = DEFAULT_LEGAL_NOTICE_RESOURCES,
    ) -> None:
        self.parent = parent
        self.translator = self._validate_translator(translator)
        self.resources = resources.validated()

        self.window: tk.Toplevel | None = None
        self.heading_label: ttk.Label | None = None
        self.copyright_label: ttk.Label | None = None
        self.application_label: ttk.Label | None = None
        self.warranty_label: ttk.Label | None = None
        self.rights_label: ttk.Label | None = None
        self.third_party_label: ttk.Label | None = None
        self.source_heading_label: ttk.Label | None = None
        self.source_url_label: ttk.Label | None = None
        self.local_documents_label: ttk.Label | None = None
        self.governing_terms_label: ttk.Label | None = None
        self.close_button: ttk.Button | None = None
        self._wrapped_labels: list[ttk.Label] = []

        self._build_window()

    @staticmethod
    def _validate_translator(translator: TextTranslator) -> TextTranslator:
        if not callable(getattr(translator, "text", None)):
            raise TypeError("translator must provide text(key, **values)")
        return translator

    def _text(self, key: str, **values: object) -> str:
        return str(self.translator.text(key, **values))

    @property
    def is_visible(self) -> bool:
        window = self.window
        if window is None:
            return False
        try:
            return bool(window.winfo_exists()) and window.state() != "withdrawn"
        except tk.TclError:
            return False

    def _build_window(self) -> None:
        if self.window is not None:
            try:
                if self.window.winfo_exists():
                    return
            except tk.TclError:
                pass

        try:
            if not self.parent.winfo_exists():
                raise RuntimeError("cannot create legal notice after parent destruction")
        except tk.TclError as exc:
            raise RuntimeError(
                "cannot create legal notice after parent destruction"
            ) from exc

        window = tk.Toplevel(self.parent)
        self.window = window
        setattr(self.parent, self._PARENT_ATTRIBUTE, self)
        window.withdraw()
        geometry, minimum = compute_legal_notice_layout(
            window.winfo_screenwidth(), window.winfo_screenheight()
        )
        window.geometry(geometry)
        window.minsize(*minimum)
        window.resizable(True, True)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", self._on_escape, add="+")
        window.bind("<Destroy>", self._on_window_destroyed, add="+")
        window.bind("<Configure>", self._on_configure, add="+")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        body = ttk.Frame(window, padding=(20, 16))
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        self.heading_label = ttk.Label(
            body,
            text="ChromaMatter",
            font=ui_font(17, "bold"),
            anchor="w",
        )
        self.heading_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self.copyright_label = ttk.Label(body, anchor="w")
        self.copyright_label.grid(row=1, column=0, sticky="ew", pady=(0, 14))

        self.application_label = self._add_wrapped_label(body, 2)
        self.warranty_label = self._add_wrapped_label(
            body,
            3,
            font=ui_font(10, "bold"),
        )
        self.rights_label = self._add_wrapped_label(body, 4)
        self.third_party_label = self._add_wrapped_label(body, 5)

        ttk.Separator(body, orient="horizontal").grid(
            row=6, column=0, sticky="ew", pady=(12, 12)
        )
        self.source_heading_label = ttk.Label(
            body,
            font=ui_font(11, "bold"),
            anchor="w",
        )
        self.source_heading_label.grid(row=7, column=0, sticky="ew", pady=(0, 5))
        self.source_url_label = self._add_wrapped_label(body, 8)
        self.local_documents_label = self._add_wrapped_label(body, 9)
        self.governing_terms_label = self._add_wrapped_label(body, 10)

        footer = ttk.Frame(window, padding=(20, 0, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.close_button = ttk.Button(footer, command=self.close)
        self.close_button.grid(row=0, column=1, sticky="e")

        self.refresh_text()

    def _add_wrapped_label(
        self,
        parent: ttk.Frame,
        row: int,
        *,
        font: tuple[str, int, str] | None = None,
    ) -> ttk.Label:
        options: dict[str, object] = {
            "anchor": "nw",
            "justify": "left",
            "wraplength": 690,
        }
        if font is not None:
            options["font"] = font
        label = ttk.Label(parent, **options)
        label.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        self._wrapped_labels.append(label)
        return label

    def set_translator(self, translator: TextTranslator) -> None:
        self.translator = self._validate_translator(translator)
        self.refresh_text()

    def set_resources(self, resources: LegalNoticeResources) -> None:
        self.resources = resources.validated()
        self.refresh_text()

    def refresh_text(self) -> None:
        window = self.window
        if window is None:
            return
        resources = self.resources
        locations = ", ".join(resources.local_document_locations)
        try:
            if not window.winfo_exists():
                return
            window.title(self._text("legal_notice.title"))
            assert self.copyright_label is not None
            assert self.application_label is not None
            assert self.warranty_label is not None
            assert self.rights_label is not None
            assert self.third_party_label is not None
            assert self.source_heading_label is not None
            assert self.source_url_label is not None
            assert self.local_documents_label is not None
            assert self.governing_terms_label is not None
            assert self.close_button is not None
            self.copyright_label.configure(text=resources.copyright_notice)
            self.application_label.configure(
                text=self._text(
                    "legal_notice.application",
                    license=resources.application_license,
                )
            )
            self.warranty_label.configure(text=self._text("legal_notice.no_warranty"))
            self.rights_label.configure(text=self._text("legal_notice.rights"))
            self.third_party_label.configure(
                text=self._text(
                    "legal_notice.third_party",
                    tetgen_license=resources.tetgen_license,
                )
            )
            self.source_heading_label.configure(
                text=self._text("legal_notice.source_heading")
            )
            self.source_url_label.configure(
                text=self._text(
                    "legal_notice.source_url",
                    source_url=resources.source_url,
                )
            )
            self.local_documents_label.configure(
                text=self._text(
                    "legal_notice.local_documents",
                    locations=locations,
                )
            )
            self.governing_terms_label.configure(
                text=self._text("legal_notice.governing_terms")
            )
            self.close_button.configure(text=self._text("legal_notice.close"))
        except tk.TclError:
            return

    def show(self) -> None:
        self._build_window()
        self.refresh_text()
        window = self.window
        if window is None:
            return
        try:
            window.deiconify()
            window.lift()
            if self.close_button is not None:
                self.close_button.focus_set()
        except tk.TclError:
            return

    def hide(self) -> None:
        window = self.window
        if window is None:
            return
        try:
            if window.winfo_exists():
                window.withdraw()
        except tk.TclError:
            return

    def close(self) -> None:
        self.hide()

    def destroy(self) -> None:
        window = self.window
        self.window = None
        self._clear_widget_references()
        if window is not None:
            try:
                if window.winfo_exists():
                    window.destroy()
            except tk.TclError:
                pass
        self._detach_from_parent()

    def _on_escape(self, _event: object = None) -> str:
        self.close()
        return "break"

    def _on_configure(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self.window:
            return
        wraplength = max(220, int(event.width) - 48)
        for label in tuple(self._wrapped_labels):
            try:
                label.configure(wraplength=wraplength)
            except tk.TclError:
                pass

    def _on_window_destroyed(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self.window:
            return
        self.window = None
        self._clear_widget_references()
        self._detach_from_parent()

    def _clear_widget_references(self) -> None:
        self.heading_label = None
        self.copyright_label = None
        self.application_label = None
        self.warranty_label = None
        self.rights_label = None
        self.third_party_label = None
        self.source_heading_label = None
        self.source_url_label = None
        self.local_documents_label = None
        self.governing_terms_label = None
        self.close_button = None
        self._wrapped_labels = []

    def _detach_from_parent(self) -> None:
        try:
            if getattr(self.parent, self._PARENT_ATTRIBUTE, None) is self:
                delattr(self.parent, self._PARENT_ATTRIBUTE)
        except (AttributeError, tk.TclError):
            pass


def get_legal_notice(
    parent: tk.Misc,
    translator: TextTranslator,
    *,
    resources: LegalNoticeResources = DEFAULT_LEGAL_NOTICE_RESOURCES,
) -> LegalNoticeWindow:
    """Return the parent's one reusable legal notice window."""

    LegalNoticeWindow._validate_translator(translator)
    resources.validated()
    existing = getattr(parent, LegalNoticeWindow._PARENT_ATTRIBUTE, None)
    if isinstance(existing, LegalNoticeWindow) and existing.window is not None:
        try:
            if existing.window.winfo_exists():
                existing.set_translator(translator)
                existing.set_resources(resources)
                return existing
        except tk.TclError:
            pass
    return LegalNoticeWindow(parent, translator, resources=resources)


__all__ = [
    "DEFAULT_LEGAL_NOTICE_RESOURCES",
    "LEGAL_NOTICE_TEXT_KEYS",
    "LegalNoticeResources",
    "LegalNoticeWindow",
    "compute_legal_notice_layout",
    "get_legal_notice",
]
