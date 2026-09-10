from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


FIXED_APP = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXED_APP))

from spectrum_mapper import ui_fonts


class _FakeFont:
    def __init__(self, family: str, widths: dict[str, int]) -> None:
        self.family = family
        self.widths = widths

    def actual(self, option: str) -> str:
        if option != "family":
            raise AssertionError(option)
        return self.family

    def measure(self, _text: str) -> int:
        return int(self.widths.get(self.family, 0))


class UiFontTests(unittest.TestCase):
    def test_linux_selects_a_font_that_measures_japanese(self) -> None:
        widths = {"gothic": 64, "mincho": 61, "fixed": 0}

        def factory(*, root, family, size):
            self.assertIs(root, sentinel)
            self.assertEqual(size, 12)
            return _FakeFont(str(family), widths)

        sentinel = object()
        with (
            patch.object(ui_fonts, "_resolved_family", "gothic"),
            patch.object(
                ui_fonts.tkfont,
                "families",
                return_value=("fixed", "mincho", "gothic"),
            ),
            patch.object(ui_fonts.tkfont, "Font", side_effect=factory),
            patch.object(
                ui_fonts,
                "resolve_linux_pillow_japanese_font",
                return_value=Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            ),
        ):
            probe = ui_fonts.resolve_ui_font(
                sentinel, platform_name="linux"
            )
            self.assertEqual(probe.family, "gothic")
            self.assertEqual(probe.japanese_width, 64)
            self.assertIn("NotoSansCJK-Regular.ttc", str(probe.pillow_font_path))
            self.assertEqual(ui_fonts.ui_font(10, "bold"), ("gothic", 10, "bold"))

    def test_linux_fails_instead_of_accepting_blank_japanese(self) -> None:
        with (
            patch.object(ui_fonts, "_resolved_family", "gothic"),
            patch.object(
                ui_fonts.tkfont, "families", return_value=("fixed",)
            ),
            patch.object(
                ui_fonts.tkfont,
                "Font",
                # A missing glyph can still be measured as a positive-width
                # tofu box.  ``fixed`` must remain ineligible regardless.
                return_value=_FakeFont("fixed", {"fixed": 80}),
            ),
        ):
            with self.assertRaisesRegex(
                ui_fonts.LinuxJapaneseFontUnavailable,
                "xfonts-intl-japanese",
            ):
                ui_fonts.resolve_ui_font(object(), platform_name="linux")

    def test_linux_rejects_tk_font_when_pillow_noto_is_missing(self) -> None:
        with (
            patch.object(ui_fonts, "_resolved_family", "gothic"),
            patch.object(
                ui_fonts.tkfont, "families", return_value=("gothic",)
            ),
            patch.object(
                ui_fonts.tkfont,
                "Font",
                return_value=_FakeFont("gothic", {"gothic": 80}),
            ),
            patch.object(
                ui_fonts,
                "resolve_linux_pillow_japanese_font",
                return_value=None,
            ),
        ):
            with self.assertRaisesRegex(
                ui_fonts.LinuxJapaneseFontUnavailable,
                "fonts-noto-cjk",
            ):
                ui_fonts.resolve_ui_font(object(), platform_name="linux")

    def test_platform_defaults_remain_native(self) -> None:
        self.assertEqual(ui_fonts._font_candidates("win32")[0], "Yu Gothic UI")
        self.assertEqual(ui_fonts._font_candidates("darwin")[0], "Hiragino Sans")
        self.assertEqual(
            ui_fonts._font_candidates("linux")[0], "Noto Sans CJK JP"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
