from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.i18n import CATALOG, Translator  # noqa: E402
from spectrum_mapper.legal_notice import (  # noqa: E402
    DEFAULT_LEGAL_NOTICE_RESOURCES,
    LEGAL_NOTICE_TEXT_KEYS,
    LegalNoticeResources,
    compute_legal_notice_layout,
    get_legal_notice,
)


def _geometry_rect(geometry: str) -> tuple[int, int, int, int]:
    size, x_text, y_text = geometry.split("+", 2)
    width_text, height_text = size.split("x", 1)
    return int(x_text), int(y_text), int(width_text), int(height_text)


class LegalNoticeContentTests(unittest.TestCase):
    def test_default_notice_identifies_app_tetgen_source_and_local_directory(self) -> None:
        resources = DEFAULT_LEGAL_NOTICE_RESOURCES
        self.assertEqual(resources.application_license, "GPL-3.0-or-later")
        self.assertEqual(resources.tetgen_license, "AGPL-3.0-or-later")
        self.assertEqual(
            resources.source_url,
            "https://github.com/Ponkichi0718/ChromaMatter",
        )
        self.assertEqual(resources.local_document_locations, ("licenses/",))
        resources.validated()

    def test_release_audit_can_replace_every_release_specific_value(self) -> None:
        resources = LegalNoticeResources(
            copyright_notice="Copyright test",
            application_license="APP-LICENSE",
            tetgen_license="TETGEN-LICENSE",
            source_url="https://example.invalid/source",
            local_document_locations=("NOTICE-A.txt", "NOTICE-B.txt"),
        )
        self.assertIs(resources.validated(), resources)
        with self.assertRaisesRegex(ValueError, "blank"):
            LegalNoticeResources(
                copyright_notice="Copyright test",
                application_license="APP-LICENSE",
                tetgen_license="TETGEN-LICENSE",
                source_url="",
                local_document_locations=("licenses/",),
            ).validated()

    def test_every_visible_notice_key_is_bilingual(self) -> None:
        keys = ("toolbar.licenses", *LEGAL_NOTICE_TEXT_KEYS)
        self.assertEqual(len(keys), len(set(keys)))
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(key, CATALOG)
                self.assertTrue(Translator("ja").text(key))
                self.assertTrue(Translator("en").text(key))

        for language in ("ja", "en"):
            translated = Translator(language)
            rendered = "\n".join(
                (
                    translated.text(
                        "legal_notice.application", license="GPL-3.0-or-later"
                    ),
                    translated.text("legal_notice.no_warranty"),
                    translated.text("legal_notice.rights"),
                    translated.text(
                        "legal_notice.third_party",
                        tetgen_license="AGPL-3.0-or-later",
                    ),
                    translated.text(
                        "legal_notice.source_url",
                        source_url="https://example.invalid/source",
                    ),
                )
            )
            with self.subTest(language=language):
                self.assertIn("GPL-3.0-or-later", rendered)
                self.assertIn("AGPL-3.0-or-later", rendered)
                self.assertIn("https://example.invalid/source", rendered)

    def test_layout_is_centered_normally_and_clamped_on_small_screens(self) -> None:
        geometry, minimum = compute_legal_notice_layout(1920, 1080)
        self.assertEqual(geometry, "760x560+580+260")
        self.assertEqual(minimum, (600, 420))

        for screen_width, screen_height in (
            (800, 600),
            (400, 450),
            (1, 1),
            (None, "invalid"),
        ):
            with self.subTest(screen=(screen_width, screen_height)):
                geometry, minimum = compute_legal_notice_layout(
                    screen_width, screen_height
                )
                x, y, width, height = _geometry_rect(geometry)
                width_limit = (
                    max(1, int(screen_width or 1))
                    if screen_width != "invalid"
                    else 1
                )
                height_limit = (
                    max(1, int(screen_height or 1))
                    if screen_height != "invalid"
                    else 1
                )
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + width, width_limit)
                self.assertLessEqual(y + height, height_limit)
                self.assertLessEqual(minimum[0], width)
                self.assertLessEqual(minimum[1], height)


class LegalNoticeGuiIntegrationSourceTests(unittest.TestCase):
    def test_public_toolbar_exposes_legal_notice_without_restoring_help(self) -> None:
        gui_source = (
            Path(__file__).resolve().parent / "spectrum_mapper" / "gui.py"
        ).read_text(encoding="utf-8")
        build_ui = gui_source.split("    def _build_ui", 1)[1].split(
            "    def _on_language_selected", 1
        )[0]

        self.assertIn("self.legal_notice_button = ttk.Button(", build_ui)
        self.assertIn("command=self._show_legal_notice", build_ui)
        self.assertIn(
            "self.legal_notice_button.grid(row=0, column=6",
            build_ui,
        )
        self.assertIn("self.help_button = ttk.Button(", build_ui)
        self.assertNotIn("self.help_button.grid(", build_ui)

    def test_language_switch_and_app_shutdown_own_the_notice_lifecycle(self) -> None:
        gui_source = (
            Path(__file__).resolve().parent / "spectrum_mapper" / "gui.py"
        ).read_text(encoding="utf-8")
        set_language = gui_source.split("    def set_language", 1)[1].split(
            "    def _refresh_project_load_menu_labels", 1
        )[0]
        finish_close = gui_source.split("    def _finish_close", 1)[1].split(
            "\n\ndef launch_app", 1
        )[0]

        self.assertIn('text=self.i18n.text("toolbar.licenses")', set_language)
        self.assertIn("self.legal_notice_window.set_translator", set_language)
        self.assertIn("self.legal_notice_window.destroy()", finish_close)


class LegalNoticeRealTkTests(unittest.TestCase):
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

    def test_factory_reuses_nonmodal_window_and_language_updates_live(self) -> None:
        notice = get_legal_notice(self.root, Translator("ja"))
        original_window = notice.window
        notice.show()
        self.root.update()

        self.assertTrue(notice.is_visible)
        self.assertIsNone(original_window.grab_current())
        self.assertEqual(original_window.title(), "ライセンスとソース")
        self.assertIn("無保証", notice.warranty_label.cget("text"))

        reused = get_legal_notice(self.root, Translator("en"))
        self.assertIs(reused, notice)
        self.assertIs(reused.window, original_window)
        self.assertEqual(original_window.title(), "Licenses & Source")
        self.assertIn("NO WARRANTY", notice.warranty_label.cget("text"))

    def test_release_values_render_and_escape_only_hides_the_window(self) -> None:
        resources = LegalNoticeResources(
            copyright_notice="Copyright exact-build",
            application_license="APP-LICENSE",
            tetgen_license="TETGEN-LICENSE",
            source_url="https://example.invalid/exact-source",
            local_document_locations=("A.txt", "B/"),
        )
        notice = get_legal_notice(
            self.root,
            Translator("en"),
            resources=resources,
        )
        original_window = notice.window
        notice.show()
        self.root.update()

        self.assertEqual(notice.copyright_label.cget("text"), "Copyright exact-build")
        self.assertIn("APP-LICENSE", notice.application_label.cget("text"))
        self.assertIn("TETGEN-LICENSE", notice.third_party_label.cget("text"))
        self.assertIn(
            "https://example.invalid/exact-source",
            notice.source_url_label.cget("text"),
        )
        self.assertIn("A.txt, B/", notice.local_documents_label.cget("text"))

        # A real key event is delivered to the focused child; the Toplevel
        # binding then handles it through the widget's bind tags.
        notice.close_button.focus_force()
        self.root.update()
        notice.close_button.event_generate("<Escape>")
        self.root.update()
        self.assertFalse(notice.is_visible)
        self.assertIs(notice.window, original_window)

    def test_invalid_integration_inputs_fail_early(self) -> None:
        with self.assertRaisesRegex(TypeError, "translator"):
            get_legal_notice(self.root, object())


if __name__ == "__main__":
    unittest.main()
