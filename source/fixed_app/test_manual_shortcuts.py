from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.manual_shortcuts import (  # noqa: E402
    MANUAL_SHORTCUTS,
    PART_VISIBILITY_ACTIONS,
    PUBLIC_MANUAL_SHORTCUTS,
    SHORTCUT_BY_ACTION,
    TOOL_ACTIONS,
    dispatch_manual_shortcut,
    event_targets_text_input,
    install_manual_shortcuts,
    is_text_input_widget,
    shortcut_help_rows,
)
from spectrum_mapper.i18n import Translator  # noqa: E402


class _Widget:
    def __init__(self, class_name: str, focus: object | None = None) -> None:
        self.class_name = class_name
        self.focus = focus

    def winfo_class(self) -> str:
        return self.class_name

    def focus_get(self) -> object | None:
        return self.focus


class _BindTarget:
    def __init__(self) -> None:
        self.callbacks: dict[str, object] = {}
        self.add_values: list[str] = []

    def bind(self, sequence: str, callback, *, add: str = "") -> str:
        self.callbacks[sequence] = callback
        self.add_values.append(add)
        return f"binding-{len(self.callbacks)}"


class ManualShortcutDefinitionTests(unittest.TestCase):
    def test_shortcut_actions_and_sequences_are_unique(self) -> None:
        actions = [shortcut.action for shortcut in MANUAL_SHORTCUTS]
        sequences = [
            sequence
            for shortcut in MANUAL_SHORTCUTS
            for sequence in shortcut.sequences
        ]
        self.assertEqual(len(actions), len(set(actions)))
        self.assertEqual(len(sequences), len(set(sequences)))
        self.assertEqual(set(actions), set(SHORTCUT_BY_ACTION))

    def test_expected_tools_visibility_and_history_keys_are_exposed(self) -> None:
        self.assertEqual(
            TOOL_ACTIONS,
            {
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
            },
        )
        self.assertEqual(
            PART_VISIBILITY_ACTIONS,
            {
                "part_visible": "visible",
                "part_transparent": "transparent",
                "part_hidden": "hidden",
            },
        )
        self.assertEqual(SHORTCUT_BY_ACTION["undo"].key_label, "Ctrl+Z")
        self.assertIn(
            "<Control-Shift-Z>", SHORTCUT_BY_ACTION["redo"].sequences
        )
        self.assertEqual(
            SHORTCUT_BY_ACTION["toggle_reference"].sequences,
            ("<KeyPress-i>",),
        )
        self.assertEqual(
            SHORTCUT_BY_ACTION["toggle_palette"].sequences,
            ("<KeyPress-p>",),
        )
        self.assertEqual(
            SHORTCUT_BY_ACTION["toggle_ribbon"].sequences,
            ("<Control-F1>",),
        )
        self.assertEqual(
            SHORTCUT_BY_ACTION["toggle_fullscreen"].sequences,
            ("<F11>",),
        )
        self.assertEqual(SHORTCUT_BY_ACTION["show_shortcuts"].sequences, ("<F1>",))

    def test_help_rows_retain_discoverable_order_and_i18n_keys(self) -> None:
        rows = shortcut_help_rows()
        self.assertEqual(len(rows), len(PUBLIC_MANUAL_SHORTCUTS))
        self.assertNotIn("paint.shortcut.split", {label for _, label, _ in rows})
        self.assertNotIn("paint.shortcut.joint", {label for _, label, _ in rows})
        self.assertTrue(
            all("decal" not in shortcut.action for shortcut in PUBLIC_MANUAL_SHORTCUTS)
        )
        self.assertEqual(rows[0], ("Ctrl+Z", "paint.shortcut.undo", "history"))
        self.assertEqual(rows[-1], ("F1", "paint.shortcut.show_help", "help"))
        self.assertEqual(
            rows[-5:-1],
            (
                ("I", "paint.shortcut.toggle_reference", "view"),
                ("P", "paint.shortcut.toggle_palette", "view"),
                ("Ctrl+F1", "paint.shortcut.toggle_ribbon", "view"),
                ("F11", "paint.shortcut.toggle_fullscreen", "view"),
            ),
        )
        self.assertTrue(all(label.startswith("paint.shortcut.") for _, label, _ in rows))

    def test_ribbon_and_layout_labels_are_localized(self) -> None:
        expected = {
            "paint.ribbon_home": ("ホーム", "Home"),
            "paint.ribbon_brush": ("ブラシ・色", "Brush & Color"),
            "paint.ribbon_shading": ("陰影", "Shading"),
            "paint.ribbon_parts": ("パーツ", "Parts"),
            "paint.ribbon_shape": ("分割・ジョイント", "Split & Joint"),
            "paint.ribbon_view": ("表示", "View"),
            "paint.ribbon_expand": ("リボンを展開", "Expand Ribbon"),
            "paint.ribbon_collapse": ("リボンを収納", "Collapse Ribbon"),
            "paint.reference_show": ("元画像を表示", "Show Reference"),
            "paint.reference_hide": ("元画像を収納", "Hide Reference"),
            "paint.palette_show": ("ブラシ・色を表示", "Show Brush & Color"),
            "paint.palette_hide": ("ブラシ・色を収納", "Hide Brush & Color"),
            "paint.fullscreen_enter": ("全画面 F11", "Full Screen F11"),
            "paint.fullscreen_exit": ("全画面を終了 Esc", "Exit Full Screen Esc"),
            "paint.orbit_inverted": (
                "右ドラッグ回転を反転",
                "Invert Right-drag Orbit",
            ),
            "paint.floating_palette_title": ("ブラシ・色", "Brush & Color"),
            "paint.floating_palette_hint": (
                "見出しをドラッグして移動",
                "Drag the header to move",
            ),
            "paint.quick_help": ("? 操作ガイド F1", "? Controls F1"),
        }
        japanese = Translator("ja")
        english = Translator("en")
        for key, (ja_text, en_text) in expected.items():
            with self.subTest(key=key):
                self.assertEqual(japanese.text(key), ja_text)
                self.assertEqual(english.text(key), en_text)

        for action in (
            "toggle_reference",
            "toggle_palette",
            "toggle_ribbon",
            "toggle_fullscreen",
        ):
            key = SHORTCUT_BY_ACTION[action].label_key
            self.assertTrue(japanese.text(key))
            self.assertTrue(english.text(key))


class ManualShortcutFocusGuardTests(unittest.TestCase):
    def test_entry_text_spinbox_and_combobox_variants_are_guarded(self) -> None:
        for class_name in (
            "Entry",
            "TEntry",
            "Text",
            "ScrolledText",
            "Spinbox",
            "TSpinbox",
            "TCombobox",
        ):
            with self.subTest(class_name=class_name):
                self.assertTrue(is_text_input_widget(_Widget(class_name)))
        for class_name in ("Canvas", "TButton", "Toplevel", "TFrame"):
            with self.subTest(class_name=class_name):
                self.assertFalse(is_text_input_widget(_Widget(class_name)))

    def test_focused_input_takes_precedence_over_event_widget(self) -> None:
        entry = _Widget("TEntry")
        canvas = _Widget("Canvas", focus=entry)
        self.assertTrue(
            event_targets_text_input(SimpleNamespace(widget=canvas))
        )

    def test_dispatch_does_not_consume_input_editing_shortcuts(self) -> None:
        calls: list[str] = []
        event = SimpleNamespace(widget=_Widget("TEntry"))
        result = dispatch_manual_shortcut(
            "undo", event, lambda action, _event: calls.append(action)
        )
        self.assertIsNone(result)
        self.assertEqual(calls, [])

    def test_dispatch_consumes_handled_canvas_action_only(self) -> None:
        event = SimpleNamespace(widget=_Widget("Canvas"))
        calls: list[str] = []
        self.assertEqual(
            dispatch_manual_shortcut(
                "tool_brush", event, lambda action, _event: calls.append(action)
            ),
            "break",
        )
        self.assertEqual(calls, ["tool_brush"])
        self.assertIsNone(
            dispatch_manual_shortcut("part_hidden", event, lambda *_args: False)
        )

    def test_unknown_action_fails_loudly(self) -> None:
        with self.assertRaises(KeyError):
            dispatch_manual_shortcut(
                "typo", SimpleNamespace(widget=_Widget("Canvas")), lambda *_: None
            )


class ManualShortcutInstallationTests(unittest.TestCase):
    def test_installer_binds_every_sequence_additively(self) -> None:
        target = _BindTarget()
        calls: list[str] = []
        installed = install_manual_shortcuts(
            target, lambda action, _event: calls.append(action)
        )
        sequence_count = sum(
            len(item.sequences) for item in PUBLIC_MANUAL_SHORTCUTS
        )
        self.assertEqual(len(installed), sequence_count)
        self.assertEqual(len(target.callbacks), sequence_count)
        self.assertEqual(target.add_values, ["+"] * sequence_count)

        result = target.callbacks["<KeyPress-t>"](
            SimpleNamespace(widget=_Widget("Canvas"))
        )
        self.assertEqual(result, "break")
        self.assertEqual(calls, ["part_transparent"])


if __name__ == "__main__":
    unittest.main()
