from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class ManualShortcut:
    """One discoverable keyboard action in the manual editor.

    ``action`` is intentionally UI-toolkit independent.  The paint window can
    map it to an editor method while this module owns Tk key spelling, help
    order, and the text-input safety guard.
    """

    action: str
    key_label: str
    sequences: tuple[str, ...]
    label_key: str
    group: str


@dataclass(frozen=True, slots=True)
class InstalledShortcutBinding:
    sequence: str
    function_id: str | None


MANUAL_SHORTCUTS: tuple[ManualShortcut, ...] = (
    ManualShortcut(
        "undo",
        "Ctrl+Z",
        ("<Control-z>",),
        "paint.shortcut.undo",
        "history",
    ),
    ManualShortcut(
        "redo",
        "Ctrl+Y / Ctrl+Shift+Z",
        ("<Control-y>", "<Control-Shift-Z>"),
        "paint.shortcut.redo",
        "history",
    ),
    ManualShortcut(
        "tool_orbit",
        "R",
        ("<KeyPress-r>",),
        "paint.shortcut.orbit",
        "tools",
    ),
    ManualShortcut(
        "tool_brush",
        "B",
        ("<KeyPress-b>",),
        "paint.shortcut.brush",
        "tools",
    ),
    ManualShortcut(
        "tool_airbrush",
        "A",
        ("<KeyPress-a>",),
        "paint.shortcut.airbrush",
        "tools",
    ),
    ManualShortcut(
        "tool_eyedropper",
        "C",
        ("<KeyPress-c>",),
        "paint.shortcut.eyedropper",
        "tools",
    ),
    ManualShortcut(
        "tool_smudge",
        "M",
        ("<KeyPress-m>",),
        "paint.shortcut.smudge",
        "tools",
    ),
    ManualShortcut(
        "tool_fill",
        "F",
        ("<KeyPress-f>",),
        "paint.shortcut.fill",
        "tools",
    ),
    ManualShortcut(
        "tool_smooth",
        "S",
        ("<KeyPress-s>",),
        "paint.shortcut.smooth",
        "tools",
    ),
    ManualShortcut(
        "tool_restore",
        "E",
        ("<KeyPress-e>",),
        "paint.shortcut.restore",
        "tools",
    ),
    ManualShortcut(
        "tool_split",
        "L",
        ("<KeyPress-l>",),
        "paint.shortcut.split",
        "tools",
    ),
    ManualShortcut(
        "tool_joint",
        "J",
        ("<KeyPress-j>",),
        "paint.shortcut.joint",
        "tools",
    ),
    ManualShortcut(
        "part_visible",
        "V",
        ("<KeyPress-v>",),
        "paint.shortcut.part_visible",
        "parts",
    ),
    ManualShortcut(
        "part_transparent",
        "T",
        ("<KeyPress-t>",),
        "paint.shortcut.part_transparent",
        "parts",
    ),
    ManualShortcut(
        "part_hidden",
        "H",
        ("<KeyPress-h>",),
        "paint.shortcut.part_hidden",
        "parts",
    ),
    ManualShortcut(
        "toggle_reference",
        "I",
        ("<KeyPress-i>",),
        "paint.shortcut.toggle_reference",
        "view",
    ),
    ManualShortcut(
        "toggle_palette",
        "P",
        ("<KeyPress-p>",),
        "paint.shortcut.toggle_palette",
        "view",
    ),
    ManualShortcut(
        "toggle_ribbon",
        "Ctrl+F1",
        ("<Control-F1>",),
        "paint.shortcut.toggle_ribbon",
        "view",
    ),
    ManualShortcut(
        "toggle_fullscreen",
        "F11",
        ("<F11>",),
        "paint.shortcut.toggle_fullscreen",
        "view",
    ),
    ManualShortcut(
        "show_shortcuts",
        "F1",
        ("<F1>",),
        "paint.shortcut.show_help",
        "help",
    ),
)


SHORTCUT_BY_ACTION = {
    shortcut.action: shortcut for shortcut in MANUAL_SHORTCUTS
}

# Split/joint remain in the recovered source for the future dedicated engine,
# but are deliberately absent from the public manual-paint surface.  Keeping a
# separate public tuple lets old project code still resolve those action names
# without advertising or binding them in the release UI.
PUBLIC_MANUAL_SHORTCUTS: tuple[ManualShortcut, ...] = tuple(
    shortcut
    for shortcut in MANUAL_SHORTCUTS
    if shortcut.action not in {"tool_split", "tool_joint"}
)


TOOL_ACTIONS = {
    "tool_orbit": "orbit",
    "tool_brush": "brush",
    "tool_airbrush": "airbrush",
    "tool_eyedropper": "eyedropper",
    "tool_smudge": "smudge",
    "tool_fill": "fill",
    "tool_smooth": "smooth",
    "tool_restore": "erase",
    "tool_split": "lasso",
    "tool_joint": "joint",
}


PART_VISIBILITY_ACTIONS = {
    "part_visible": "visible",
    "part_transparent": "transparent",
    "part_hidden": "hidden",
}


def shortcut_help_rows(
    shortcuts: Iterable[ManualShortcut] = PUBLIC_MANUAL_SHORTCUTS,
) -> tuple[tuple[str, str, str], ...]:
    """Return ``(key label, i18n label key, group)`` rows in UI order."""

    return tuple(
        (shortcut.key_label, shortcut.label_key, shortcut.group)
        for shortcut in shortcuts
    )


_TEXT_INPUT_CLASS_SUFFIXES = ("entry", "text", "spinbox", "combobox")


def is_text_input_widget(widget: object | None) -> bool:
    """Whether ordinary typing should stay inside *widget*.

    Tk and ttk use different widget class names (for example ``Entry`` and
    ``TEntry``).  Suffix matching also covers safe subclasses such as
    ``ScrolledText`` without importing tkinter, which keeps this helper usable
    in headless unit tests.
    """

    if widget is None:
        return False
    class_name = ""
    winfo_class = getattr(widget, "winfo_class", None)
    if callable(winfo_class):
        try:
            class_name = str(winfo_class())
        except Exception:
            class_name = ""
    if not class_name:
        class_name = type(widget).__name__
    normalized = class_name.strip().lower()
    return normalized.endswith(_TEXT_INPUT_CLASS_SUFFIXES)


def event_targets_text_input(event: object | None) -> bool:
    """Check the actual focused widget, falling back to ``event.widget``."""

    if event is None:
        return False
    event_widget = getattr(event, "widget", None)
    focus_widget = None
    focus_get = getattr(event_widget, "focus_get", None)
    if callable(focus_get):
        try:
            focus_widget = focus_get()
        except Exception:
            focus_widget = None
    return is_text_input_widget(focus_widget or event_widget)


def dispatch_manual_shortcut(
    action: str,
    event: object,
    handler: Callable[[str, object], object],
) -> str | None:
    """Safely dispatch one shortcut and stop Tk propagation when handled.

    Returning ``False`` from *handler* explicitly leaves the event unhandled.
    Any other result means the action was accepted and yields Tk's ``break``.
    """

    if action not in SHORTCUT_BY_ACTION:
        raise KeyError(f"Unknown manual-editor shortcut action: {action}")
    if event_targets_text_input(event):
        return None
    if handler(action, event) is False:
        return None
    return "break"


def install_manual_shortcuts(
    bind_target: object,
    handler: Callable[[str, object], object],
    *,
    add: str = "+",
) -> tuple[InstalledShortcutBinding, ...]:
    """Install every manual-editor shortcut on a Tk-compatible bind target."""

    bind = getattr(bind_target, "bind", None)
    if not callable(bind):
        raise TypeError("bind_target must provide a callable bind method")

    installed: list[InstalledShortcutBinding] = []
    for shortcut in PUBLIC_MANUAL_SHORTCUTS:
        for sequence in shortcut.sequences:
            action = shortcut.action

            def callback(event: object, *, _action: str = action) -> str | None:
                return dispatch_manual_shortcut(_action, event, handler)

            function_id = bind(sequence, callback, add=add)
            installed.append(
                InstalledShortcutBinding(
                    sequence=sequence,
                    function_id=(
                        None if function_id is None else str(function_id)
                    ),
                )
            )
    return tuple(installed)
