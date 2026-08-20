from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.help_center import (  # noqa: E402
    HELP_ACTION_LABEL_KEYS,
    HELP_ACTION_IDS,
    HELP_TOPIC_IDS,
    HELP_TOPICS,
    HelpCenterWindow,
    compute_help_center_layout,
    get_help_center,
    help_topic_spec,
    validate_help_content,
)
from spectrum_mapper.i18n import CATALOG, Translator  # noqa: E402


class _Translator:
    def __init__(self, prefix: str = "T") -> None:
        self.prefix = prefix
        self.keys: list[str] = []

    def text(self, key: str, /, **values: object) -> str:
        self.keys.append(key)
        rendered = f"{self.prefix}:{key}"
        return rendered.format(**values) if values else rendered


def _geometry_rect(geometry: str) -> tuple[int, int, int, int]:
    size, x_text, y_text = geometry.split("+", 2)
    width_text, height_text = size.split("x", 1)
    return int(x_text), int(y_text), int(width_text), int(height_text)


class HelpContentTests(unittest.TestCase):
    def test_six_topics_use_only_central_translation_keys(self) -> None:
        self.assertEqual(tuple(topic.topic_id for topic in HELP_TOPICS), HELP_TOPIC_IDS)
        self.assertEqual(len(HELP_TOPICS), 6)
        for topic in HELP_TOPICS:
            with self.subTest(topic=topic.topic_id):
                self.assertTrue(topic.title_key.startswith("help_center."))
                self.assertGreaterEqual(len(topic.step_keys), 3)
                self.assertLessEqual(len(topic.step_keys), 5)
                self.assertTrue(
                    all(key.startswith("help_center.") for key in topic.step_keys)
                )
                self.assertTrue(set(topic.action_ids).issubset(HELP_ACTION_IDS))

        validate_help_content()

    def test_topic_lookup_is_explicit(self) -> None:
        self.assertEqual(help_topic_spec("manual_editing").topic_id, "manual_editing")
        with self.assertRaisesRegex(ValueError, "unknown help topic"):
            help_topic_spec("not-a-topic")

    def test_content_validation_rejects_long_and_unknown_action_topics(self) -> None:
        too_long = replace(
            HELP_TOPICS[0],
            step_keys=tuple(f"help_center.test.step{i}" for i in range(6)),
        )
        with self.assertRaisesRegex(ValueError, "between three and five"):
            validate_help_content((too_long,) + HELP_TOPICS[1:])

        unknown_action = replace(HELP_TOPICS[0], action_ids=("launch_missile",))
        with self.assertRaisesRegex(ValueError, "unknown action"):
            validate_help_content((unknown_action,) + HELP_TOPICS[1:])

    def test_layout_is_clamped_to_every_screen_size(self) -> None:
        for screen_width, screen_height in (
            (1920, 1080),
            (800, 600),
            (400, 450),
            (1, 1),
            (None, "invalid"),
        ):
            with self.subTest(screen=(screen_width, screen_height)):
                geometry, minimum = compute_help_center_layout(
                    screen_width, screen_height
                )
                x, y, width, height = _geometry_rect(geometry)
                width_limit = max(1, int(screen_width or 1)) if screen_width != "invalid" else 1
                height_limit = max(1, int(screen_height or 1)) if screen_height != "invalid" else 1
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertLessEqual(x + width, width_limit)
                self.assertLessEqual(y + height, height_limit)
                self.assertLessEqual(minimum[0], width)
                self.assertLessEqual(minimum[1], height)

    def test_normal_layout_is_centered_and_compact(self) -> None:
        geometry, minimum = compute_help_center_layout(1920, 1080)
        self.assertEqual(geometry, "960x720+480+180")
        self.assertEqual(minimum, (680, 480))

    def test_every_help_key_is_bilingual_and_steps_stay_short(self) -> None:
        shell_keys = (
            "toolbar.help",
            "help_center.title",
            "help_center.navigation",
            "help_center.steps",
            "help_center.close",
        )
        topic_keys = tuple(
            key
            for topic in HELP_TOPICS
            for key in (topic.title_key, *topic.step_keys)
        )
        keys = shell_keys + tuple(HELP_ACTION_LABEL_KEYS.values()) + topic_keys
        self.assertEqual(len(keys), len(set(keys)))
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(key, CATALOG)
                self.assertTrue(CATALOG[key]["ja"])
                self.assertTrue(CATALOG[key]["en"])
        for topic in HELP_TOPICS:
            for key in topic.step_keys:
                for language in ("ja", "en"):
                    copy = Translator(language).text(key)
                    with self.subTest(key=key, language=language):
                        self.assertNotIn("\n", copy)
                        self.assertLessEqual(len(copy), 125)


class HelpCenterWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        self.root.withdraw()

    def tearDown(self) -> None:
        root = getattr(self, "root", None)
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass

    def test_factory_reuses_one_nonmodal_toplevel(self) -> None:
        first = get_help_center(self.root, _Translator("JA"))
        original_window = first.window
        second = get_help_center(self.root, _Translator("EN"))

        self.assertIs(first, second)
        self.assertIs(second.window, original_window)
        self.assertIsNotNone(original_window)
        assert original_window is not None
        self.assertEqual(original_window.state(), "withdrawn")
        self.assertEqual(original_window.wm_transient(), "")
        self.assertIsNone(original_window.grab_current())
        self.assertEqual(original_window.title(), "EN:help_center.title")

    def test_navigation_show_hide_escape_and_close_preserve_window(self) -> None:
        center = get_help_center(self.root, _Translator())
        original_window = center.window
        center.show("manual_editing")
        self.root.update()

        self.assertEqual(center.current_topic_id, "manual_editing")
        self.assertTrue(center.is_visible)
        self.assertEqual(center.topic_tree.selection(), ("manual_editing",))
        self.assertIn(
            "help_center.topic.manual_editing.title",
            center.topic_title_label.cget("text"),
        )

        center.close()
        self.root.update()
        self.assertFalse(center.is_visible)
        self.assertIs(center.window, original_window)

        center.show("export_3mf")
        self.root.update()
        assert center.window is not None
        center.window.event_generate("<Escape>")
        self.root.update()
        self.assertFalse(center.is_visible)
        self.assertIs(center.window, original_window)

    def test_only_available_actions_for_current_topic_are_shown(self) -> None:
        calls: list[str] = []
        center = get_help_center(
            self.root,
            _Translator(),
            actions={
                "open_obj": lambda: calls.append("open_obj"),
                "open_manual": lambda: calls.append("open_manual"),
            },
        )

        center.navigate("first_steps")
        self.assertEqual(center.action_buttons["open_obj"].winfo_manager(), "grid")
        self.assertEqual(
            center.action_buttons["select_filament"].winfo_manager(), ""
        )
        center.action_buttons["open_obj"].invoke()

        center.navigate("manual_editing")
        self.assertEqual(center.action_buttons["open_obj"].winfo_manager(), "")
        self.assertEqual(center.action_buttons["open_manual"].winfo_manager(), "grid")
        center.action_buttons["open_manual"].invoke()

        center.navigate("troubleshooting")
        self.assertTrue(
            all(button.winfo_manager() == "" for button in center.action_buttons.values())
        )
        self.assertEqual(calls, ["open_obj", "open_manual"])

    def test_actions_and_language_can_be_updated_on_reused_window(self) -> None:
        center = get_help_center(self.root, _Translator("JA"))
        center.navigate("export_3mf")
        self.assertEqual(center.action_buttons["export"].winfo_manager(), "")

        calls: list[str] = []
        reused = get_help_center(
            self.root,
            _Translator("EN"),
            actions={"export": lambda: calls.append("export")},
        )
        self.assertIs(reused, center)
        self.assertEqual(center.action_buttons["export"].winfo_manager(), "grid")
        self.assertTrue(center.topic_title_label.cget("text").startswith("EN:"))
        center.action_buttons["export"].invoke()
        self.assertEqual(calls, ["export"])

    def test_destroy_is_idempotent_and_factory_can_create_a_fresh_instance(self) -> None:
        first = get_help_center(self.root, _Translator())
        first.destroy()
        first.destroy()
        self.assertIsNone(first.window)

        second = get_help_center(self.root, _Translator())
        self.assertIsNot(second, first)
        self.assertIsNotNone(second.window)

    def test_invalid_integration_inputs_fail_early(self) -> None:
        with self.assertRaisesRegex(TypeError, "translator"):
            get_help_center(self.root, object())

        center = get_help_center(self.root, _Translator())
        with self.assertRaisesRegex(ValueError, "unknown help action"):
            center.set_actions({"unknown": lambda: None})
        with self.assertRaisesRegex(TypeError, "must be callable"):
            center.set_actions({"open_obj": 123})  # type: ignore[dict-item]


if __name__ == "__main__":
    unittest.main()
