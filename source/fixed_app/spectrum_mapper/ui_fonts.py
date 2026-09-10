"""Cross-platform Tk font selection and Linux Japanese-glyph preflight."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from tkinter import font as tkfont
from typing import Any

from PIL import ImageFont


JAPANESE_FONT_PROBE_TEXT = "日本語表示"
LINUX_JAPANESE_FONT_PACKAGES = (
    "fonts-noto-cjk",
    "xfonts-base",
    "xfonts-intl-japanese",
    "xfonts-intl-japanese-big",
)
LINUX_JAPANESE_FONT_INSTALL_COMMAND = (
    "sudo apt-get update && sudo apt-get install -y "
    + " ".join(LINUX_JAPANESE_FONT_PACKAGES)
)


class LinuxJapaneseFontUnavailable(RuntimeError):
    """Raised instead of silently displaying blank Japanese labels on Linux."""


@dataclass(frozen=True, slots=True)
class UiFontProbe:
    family: str
    japanese_width: int
    pillow_font_path: str | None = None


def _platform_name(value: str | None = None) -> str:
    return str(sys.platform if value is None else value).strip().lower()


def _font_candidates(platform_name: str) -> tuple[str, ...]:
    if platform_name.startswith("linux"):
        # python-build-standalone's Tk 9 X11 runtime uses the traditional X
        # font families in a minimal Ubuntu/WSL installation.  The Japanese
        # xfonts packages provide both of these families.
        return ("Noto Sans CJK JP", "Noto Sans JP", "gothic", "mincho")
    if platform_name == "darwin":
        return ("Hiragino Sans", "Helvetica Neue", "Helvetica", "Arial")
    if platform_name.startswith("win"):
        return ("Yu Gothic UI", "Segoe UI", "Arial")
    return ("TkDefaultFont", "fixed")


_resolved_family = _font_candidates(_platform_name())[0]


def current_ui_font_family() -> str:
    return _resolved_family


def ui_font(size: int, *modifiers: str) -> tuple[object, ...]:
    """Return the currently resolved family in a Tk-compatible font tuple."""

    return (current_ui_font_family(), int(size), *modifiers)


def linux_pillow_font_candidates(*, bold: bool = False) -> tuple[Path, ...]:
    filename = "NotoSansCJK-Bold.ttc" if bold else "NotoSansCJK-Regular.ttc"
    jp_filename = "NotoSansJP-Bold.otf" if bold else "NotoSansJP-Regular.otf"
    return (
        Path("/usr/share/fonts/opentype/noto") / filename,
        Path("/usr/share/fonts/opentype/noto") / jp_filename,
        Path("/usr/share/fonts/truetype/noto") / filename,
        Path("/usr/share/fonts/google-noto-cjk") / filename,
    )


def resolve_linux_pillow_japanese_font(*, bold: bool = False) -> Path | None:
    """Return a system Noto font only after Pillow can rasterize Japanese."""

    for candidate in linux_pillow_font_candidates(bold=bold):
        if not candidate.is_file():
            continue
        try:
            font = ImageFont.truetype(str(candidate), size=24)
            if font.getmask(JAPANESE_FONT_PROBE_TEXT).getbbox() is not None:
                return candidate
        except (OSError, ValueError):
            continue
    return None


def resolve_ui_font(
    root: Any,
    *,
    platform_name: str | None = None,
) -> UiFontProbe:
    """Resolve a visible UI font and fail closed for missing Linux Japanese.

    The previous Linux build accepted a window that contained no Japanese
    glyphs.  Measuring a short Japanese sample catches that exact failure in
    both the interactive launch and packaged UI smoke.
    """

    global _resolved_family

    platform_value = _platform_name(platform_name)
    try:
        available = {
            str(value).casefold(): str(value)
            for value in tkfont.families(root)
        }
    except Exception:
        available = {}

    first_probe: UiFontProbe | None = None
    for requested in _font_candidates(platform_value):
        available_family = available.get(requested.casefold())
        if platform_value.startswith("linux") and available_family is None:
            # Asking Tk for a missing family silently falls back to ``fixed``.
            # That fallback produced the all-blank Japanese UI, and tofu glyphs
            # can still report a non-zero text width, so it is never accepted.
            continue
        family = available_family or requested
        try:
            probe_font = tkfont.Font(root=root, family=family, size=12)
            actual_family = str(probe_font.actual("family") or family)
            width = int(probe_font.measure(JAPANESE_FONT_PROBE_TEXT))
        except Exception:
            continue
        probe = UiFontProbe(actual_family, width)
        if first_probe is None:
            first_probe = probe
        if (
            not platform_value.startswith("linux")
            or (
                width > 0
                and actual_family.casefold() != "fixed"
                and actual_family.casefold() in available
            )
        ):
            pillow_font = (
                resolve_linux_pillow_japanese_font()
                if platform_value.startswith("linux")
                else None
            )
            if platform_value.startswith("linux") and pillow_font is None:
                break
            _resolved_family = actual_family
            return UiFontProbe(
                probe.family,
                probe.japanese_width,
                str(pillow_font) if pillow_font is not None else None,
            )

    if platform_value.startswith("linux"):
        raise LinuxJapaneseFontUnavailable(
            "Tk cannot render Japanese text on this Linux installation.\n\n"
            "Install the required fonts, then restart ChromaMatter:\n"
            f"{LINUX_JAPANESE_FONT_INSTALL_COMMAND}"
        )

    if first_probe is not None:
        _resolved_family = first_probe.family
        return first_probe
    return UiFontProbe(_resolved_family, 0)


__all__ = [
    "JAPANESE_FONT_PROBE_TEXT",
    "LINUX_JAPANESE_FONT_INSTALL_COMMAND",
    "LINUX_JAPANESE_FONT_PACKAGES",
    "LinuxJapaneseFontUnavailable",
    "UiFontProbe",
    "current_ui_font_family",
    "linux_pillow_font_candidates",
    "resolve_ui_font",
    "resolve_linux_pillow_japanese_font",
    "ui_font",
]
