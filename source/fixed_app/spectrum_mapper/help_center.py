from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk
from typing import Protocol

from .ui_fonts import ui_font


class TextTranslator(Protocol):
    """Small translation surface required by :class:`HelpCenterWindow`."""

    def text(self, key: str, /, **values: object) -> str: ...


HelpCallback = Callable[[], object]

HELP_TOPIC_IDS = (
    "first_steps",
    "parts_palette",
    "auto_mapping",
    "manual_editing",
    "export_3mf",
    "troubleshooting",
)

HELP_ACTION_IDS = (
    "open_obj",
    "select_filament",
    "open_manual",
    "export",
)

HELP_ACTION_LABEL_KEYS: Mapping[str, str] = {
    "open_obj": "help_center.action.open_obj",
    "select_filament": "help_center.action.select_filament",
    "open_manual": "help_center.action.open_manual",
    "export": "help_center.action.export",
}


@dataclass(frozen=True, slots=True)
class HelpTopicSpec:
    """Pure help content definition.

    Only translation keys live here.  User-facing wording remains in the
    application's central i18n catalog and can be revised independently of
    the window implementation.
    """

    topic_id: str
    title_key: str
    step_keys: tuple[str, ...]
    action_ids: tuple[str, ...] = ()


HELP_TOPICS = (
    HelpTopicSpec(
        topic_id="first_steps",
        title_key="help_center.topic.first_steps.title",
        step_keys=(
            "help_center.topic.first_steps.step1",
            "help_center.topic.first_steps.step2",
            "help_center.topic.first_steps.step3",
            "help_center.topic.first_steps.step4",
        ),
        action_ids=("open_obj", "select_filament"),
    ),
    HelpTopicSpec(
        topic_id="parts_palette",
        title_key="help_center.topic.parts_palette.title",
        step_keys=(
            "help_center.topic.parts_palette.step1",
            "help_center.topic.parts_palette.step2",
            "help_center.topic.parts_palette.step3",
            "help_center.topic.parts_palette.step4",
        ),
        action_ids=("select_filament",),
    ),
    HelpTopicSpec(
        topic_id="auto_mapping",
        title_key="help_center.topic.auto_mapping.title",
        step_keys=(
            "help_center.topic.auto_mapping.step1",
            "help_center.topic.auto_mapping.step2",
            "help_center.topic.auto_mapping.step3",
            "help_center.topic.auto_mapping.step4",
        ),
    ),
    HelpTopicSpec(
        topic_id="manual_editing",
        title_key="help_center.topic.manual_editing.title",
        step_keys=(
            "help_center.topic.manual_editing.step1",
            "help_center.topic.manual_editing.step2",
            "help_center.topic.manual_editing.step3",
            "help_center.topic.manual_editing.step4_guard",
            "help_center.topic.manual_editing.step4",
        ),
        action_ids=("open_manual",),
    ),
    HelpTopicSpec(
        topic_id="export_3mf",
        title_key="help_center.topic.export_3mf.title",
        step_keys=(
            "help_center.topic.export_3mf.step1",
            "help_center.topic.export_3mf.step2",
            "help_center.topic.export_3mf.step3",
            "help_center.topic.export_3mf.step4",
        ),
        action_ids=("export",),
    ),
    HelpTopicSpec(
        topic_id="troubleshooting",
        title_key="help_center.topic.troubleshooting.title",
        step_keys=(
            "help_center.topic.troubleshooting.step1",
            "help_center.topic.troubleshooting.step2",
            "help_center.topic.troubleshooting.step3",
            "help_center.topic.troubleshooting.step4",
        ),
    ),
)

_HELP_TOPICS_BY_ID = {topic.topic_id: topic for topic in HELP_TOPICS}


def validate_help_content(
    topics: tuple[HelpTopicSpec, ...] = HELP_TOPICS,
) -> None:
    """Validate the pure content specification without creating Tk widgets."""

    topic_ids = tuple(topic.topic_id for topic in topics)
    if topic_ids != HELP_TOPIC_IDS:
        raise ValueError("help topics must use the canonical six-topic order")
    if len(set(topic_ids)) != len(topic_ids):
        raise ValueError("help topic identifiers must be unique")

    known_actions = set(HELP_ACTION_IDS)
    for topic in topics:
        if not topic.title_key.startswith("help_center."):
            raise ValueError(f"invalid title translation key for {topic.topic_id}")
        if not 3 <= len(topic.step_keys) <= 5:
            raise ValueError(
                f"{topic.topic_id} must contain between three and five steps"
            )
        if len(set(topic.step_keys)) != len(topic.step_keys):
            raise ValueError(f"duplicate step key in {topic.topic_id}")
        if any(not key.startswith("help_center.") for key in topic.step_keys):
            raise ValueError(f"invalid step translation key in {topic.topic_id}")
        if len(set(topic.action_ids)) != len(topic.action_ids):
            raise ValueError(f"duplicate action in {topic.topic_id}")
        unknown_actions = set(topic.action_ids) - known_actions
        if unknown_actions:
            raise ValueError(
                f"unknown action(s) in {topic.topic_id}: "
                + ", ".join(sorted(unknown_actions))
            )


def help_topic_spec(topic_id: object) -> HelpTopicSpec:
    """Return one topic or raise a clear error for an integration mistake."""

    normalized = str(topic_id).strip()
    try:
        return _HELP_TOPICS_BY_ID[normalized]
    except KeyError as exc:
        raise ValueError(f"unknown help topic: {normalized!r}") from exc


def compute_help_center_layout(
    screen_width: object,
    screen_height: object,
) -> tuple[str, tuple[int, int]]:
    """Return a centered, screen-clamped geometry and a safe minimum size."""

    try:
        width_limit = max(1, int(screen_width))
    except (TypeError, ValueError, OverflowError):
        width_limit = 1
    try:
        height_limit = max(1, int(screen_height))
    except (TypeError, ValueError, OverflowError):
        height_limit = 1

    horizontal_margin = min(32, max(0, width_limit // 20))
    vertical_margin = min(28, max(0, height_limit // 24))
    width = max(1, min(960, width_limit - 2 * horizontal_margin))
    height = max(1, min(720, height_limit - 2 * vertical_margin))
    x = max(0, min(width_limit - width, (width_limit - width) // 2))
    y = max(0, min(height_limit - height, (height_limit - height) // 2))
    minimum = (min(680, width), min(480, height))
    return f"{width}x{height}+{x}+{y}", minimum


validate_help_content()


class HelpCenterWindow:
    """Reusable, non-modal application help window.

    Use :func:`get_help_center` rather than constructing this class repeatedly.
    Closing the window only withdraws it, so the same Toplevel and current
    topic are retained for the next request.
    """

    _PARENT_ATTRIBUTE = "_spectrum_mapper_help_center"

    def __init__(
        self,
        parent: tk.Misc,
        translator: TextTranslator,
        *,
        actions: Mapping[str, HelpCallback | None] | None = None,
    ) -> None:
        self.parent = parent
        self.translator = self._validate_translator(translator)
        self._actions: dict[str, HelpCallback] = {}
        self._current_topic_id = HELP_TOPIC_IDS[0]

        self.window: tk.Toplevel | None = None
        self.topic_tree: ttk.Treeview | None = None
        self.navigation_label: ttk.Label | None = None
        self.topic_title_label: ttk.Label | None = None
        self.steps_label: ttk.Label | None = None
        self.close_button: ttk.Button | None = None
        self.content_frame: ttk.Frame | None = None
        self.step_labels: list[ttk.Label] = []
        self.action_buttons: dict[str, ttk.Button] = {}

        self.set_actions(actions or {})
        self._build_window()

    @staticmethod
    def _validate_translator(translator: TextTranslator) -> TextTranslator:
        if not callable(getattr(translator, "text", None)):
            raise TypeError("translator must provide text(key, **values)")
        return translator

    @property
    def current_topic_id(self) -> str:
        return self._current_topic_id

    @property
    def is_visible(self) -> bool:
        window = self.window
        if window is None:
            return False
        try:
            return bool(window.winfo_exists()) and window.state() != "withdrawn"
        except tk.TclError:
            return False

    def _text(self, key: str, **values: object) -> str:
        return str(self.translator.text(key, **values))

    def _build_window(self) -> None:
        if self.window is not None:
            try:
                if self.window.winfo_exists():
                    return
            except tk.TclError:
                pass

        try:
            if not self.parent.winfo_exists():
                raise RuntimeError("cannot create help window after parent destruction")
        except tk.TclError as exc:
            raise RuntimeError(
                "cannot create help window after parent destruction"
            ) from exc

        window = tk.Toplevel(self.parent)
        self.window = window
        # Register here as well as in the public factory so a window recreated
        # after an external Tk destroy cannot be duplicated by a later lookup.
        setattr(self.parent, self._PARENT_ATTRIBUTE, self)
        window.withdraw()
        geometry, minimum = compute_help_center_layout(
            window.winfo_screenwidth(), window.winfo_screenheight()
        )
        window.geometry(geometry)
        window.minsize(*minimum)
        window.resizable(True, True)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", self._on_escape, add="+")
        window.bind("<Destroy>", self._on_window_destroyed, add="+")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        body = ttk.Frame(window, padding=12)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(2, weight=1)
        body.rowconfigure(1, weight=1)

        self.navigation_label = ttk.Label(
            body,
            font=ui_font(10, "bold"),
        )
        self.navigation_label.grid(row=0, column=0, sticky="w", padx=(0, 14))

        self.topic_tree = ttk.Treeview(
            body,
            show="tree",
            selectmode="browse",
            columns=(),
            height=len(HELP_TOPICS),
        )
        self.topic_tree.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        self.topic_tree.column("#0", width=205, minwidth=145, stretch=True)
        self.topic_tree.bind("<<TreeviewSelect>>", self._on_topic_selected)
        for topic in HELP_TOPICS:
            self.topic_tree.insert("", "end", iid=topic.topic_id, text=topic.topic_id)

        separator = ttk.Separator(body, orient="vertical")
        separator.grid(row=0, column=1, rowspan=2, sticky="nsw")

        self.content_frame = ttk.Frame(body, padding=(18, 0, 0, 0))
        self.content_frame.grid(row=0, column=2, rowspan=2, sticky="nsew")
        self.content_frame.columnconfigure(0, weight=1)
        self.content_frame.bind("<Configure>", self._on_content_configure, add="+")

        self.topic_title_label = ttk.Label(
            self.content_frame,
            font=ui_font(16, "bold"),
            anchor="w",
        )
        self.topic_title_label.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        self.steps_label = ttk.Label(
            self.content_frame,
            font=ui_font(10, "bold"),
            anchor="w",
        )
        self.steps_label.grid(row=1, column=0, sticky="new")

        steps_frame = ttk.Frame(self.content_frame)
        steps_frame.grid(row=2, column=0, sticky="new", pady=(7, 0))
        steps_frame.columnconfigure(0, weight=1)
        self.step_labels = []
        for index in range(5):
            label = ttk.Label(
                steps_frame,
                anchor="nw",
                justify="left",
                wraplength=520,
            )
            label.grid(row=index, column=0, sticky="ew", pady=(0, 10))
            label.grid_remove()
            self.step_labels.append(label)

        actions_frame = ttk.Frame(self.content_frame)
        actions_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        for column in range(2):
            actions_frame.columnconfigure(column, weight=1)
        self.action_buttons = {}
        for index, action_id in enumerate(HELP_ACTION_IDS):
            button = ttk.Button(
                actions_frame,
                command=lambda selected=action_id: self._invoke_action(selected),
            )
            button.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0 if index % 2 == 0 else 5, 5 if index % 2 == 0 else 0),
                pady=(0, 6),
            )
            button.grid_remove()
            self.action_buttons[action_id] = button

        footer = ttk.Frame(window, padding=(12, 0, 12, 12))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.close_button = ttk.Button(footer, command=self.close)
        self.close_button.grid(row=0, column=1, sticky="e")

        self.refresh_text()
        self.navigate(self._current_topic_id)

    def set_translator(self, translator: TextTranslator) -> None:
        self.translator = self._validate_translator(translator)
        self.refresh_text()

    def set_actions(
        self,
        actions: Mapping[str, HelpCallback | None],
    ) -> None:
        unknown = set(actions) - set(HELP_ACTION_IDS)
        if unknown:
            raise ValueError("unknown help action(s): " + ", ".join(sorted(unknown)))
        invalid = [
            action_id
            for action_id, callback in actions.items()
            if callback is not None and not callable(callback)
        ]
        if invalid:
            raise TypeError("help action callbacks must be callable: " + ", ".join(invalid))
        self._actions = {
            action_id: callback
            for action_id, callback in actions.items()
            if callback is not None
        }
        if self.window is not None:
            self._render_topic()

    def refresh_text(self) -> None:
        window = self.window
        if window is None:
            return
        try:
            if not window.winfo_exists():
                return
            window.title(self._text("help_center.title"))
            if self.navigation_label is not None:
                self.navigation_label.configure(
                    text=self._text("help_center.navigation")
                )
            if self.steps_label is not None:
                self.steps_label.configure(text=self._text("help_center.steps"))
            if self.close_button is not None:
                self.close_button.configure(text=self._text("help_center.close"))
            if self.topic_tree is not None:
                for topic in HELP_TOPICS:
                    self.topic_tree.item(
                        topic.topic_id,
                        text=self._text(topic.title_key),
                    )
            for action_id, button in self.action_buttons.items():
                button.configure(text=self._text(HELP_ACTION_LABEL_KEYS[action_id]))
            self._render_topic()
        except tk.TclError:
            return

    def show(self, topic_id: object | None = None) -> None:
        self._build_window()
        if topic_id is not None:
            self.navigate(topic_id)
        else:
            self.navigate(self._current_topic_id)
        window = self.window
        if window is None:
            return
        try:
            window.deiconify()
            window.lift()
            if self.topic_tree is not None:
                self.topic_tree.focus_set()
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
        """Handle window-manager close without discarding window state."""

        self.hide()

    def destroy(self) -> None:
        """Permanently destroy this Toplevel; safe to call repeatedly."""

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

    def navigate(self, topic_id: object) -> None:
        topic = help_topic_spec(topic_id)
        self._current_topic_id = topic.topic_id
        tree = self.topic_tree
        if tree is not None:
            try:
                tree.selection_set(topic.topic_id)
                tree.focus(topic.topic_id)
                tree.see(topic.topic_id)
            except tk.TclError:
                pass
        self._render_topic()

    def _render_topic(self) -> None:
        if self.window is None:
            return
        topic = help_topic_spec(self._current_topic_id)
        try:
            if self.topic_title_label is not None:
                self.topic_title_label.configure(text=self._text(topic.title_key))

            for index, label in enumerate(self.step_labels):
                if index < len(topic.step_keys):
                    label.configure(
                        text=f"{index + 1}. {self._text(topic.step_keys[index])}"
                    )
                    label.grid()
                else:
                    label.grid_remove()

            required_actions = set(topic.action_ids)
            for action_id, button in self.action_buttons.items():
                if action_id in required_actions and action_id in self._actions:
                    button.configure(state="normal")
                    button.grid()
                else:
                    button.grid_remove()
        except tk.TclError:
            return

    def _invoke_action(self, action_id: str) -> None:
        callback = self._actions.get(action_id)
        if callback is not None:
            callback()

    def _on_topic_selected(self, _event: tk.Event[tk.Misc]) -> None:
        tree = self.topic_tree
        if tree is None:
            return
        try:
            selected = tree.selection()
        except tk.TclError:
            return
        if selected and selected[0] != self._current_topic_id:
            self.navigate(selected[0])

    def _on_content_configure(self, event: tk.Event[tk.Misc]) -> None:
        wraplength = max(180, int(event.width) - 28)
        for label in self.step_labels:
            try:
                label.configure(wraplength=wraplength)
            except tk.TclError:
                return

    def _on_escape(self, _event: tk.Event[tk.Misc]) -> str:
        self.hide()
        return "break"

    def _on_window_destroyed(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self.window:
            return
        self.window = None
        self._clear_widget_references()
        self._detach_from_parent()

    def _clear_widget_references(self) -> None:
        self.topic_tree = None
        self.navigation_label = None
        self.topic_title_label = None
        self.steps_label = None
        self.close_button = None
        self.content_frame = None
        self.step_labels = []
        self.action_buttons = {}

    def _detach_from_parent(self) -> None:
        try:
            if getattr(self.parent, self._PARENT_ATTRIBUTE, None) is self:
                delattr(self.parent, self._PARENT_ATTRIBUTE)
        except (AttributeError, tk.TclError):
            pass


def get_help_center(
    parent: tk.Misc,
    translator: TextTranslator,
    *,
    actions: Mapping[str, HelpCallback | None] | None = None,
) -> HelpCenterWindow:
    """Return the single reusable Help Center associated with ``parent``."""

    existing = getattr(parent, HelpCenterWindow._PARENT_ATTRIBUTE, None)
    if isinstance(existing, HelpCenterWindow):
        existing.set_translator(translator)
        if actions is not None:
            existing.set_actions(actions)
        existing._build_window()
        return existing

    center = HelpCenterWindow(parent, translator, actions=actions)
    setattr(parent, HelpCenterWindow._PARENT_ATTRIBUTE, center)
    return center


__all__ = [
    "HELP_ACTION_IDS",
    "HELP_ACTION_LABEL_KEYS",
    "HELP_TOPIC_IDS",
    "HELP_TOPICS",
    "HelpCenterWindow",
    "HelpTopicSpec",
    "TextTranslator",
    "compute_help_center_layout",
    "get_help_center",
    "help_topic_spec",
    "validate_help_content",
]
