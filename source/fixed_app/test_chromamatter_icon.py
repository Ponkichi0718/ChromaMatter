from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


FIXED_APP = Path(__file__).resolve().parent
REPO_ROOT = FIXED_APP.parents[1]
ASSET_DIR = FIXED_APP / "assets"
PNG_PATH = ASSET_DIR / "obj_adjuster_icon.png"
ICO_PATH = ASSET_DIR / "obj_adjuster_icon.ico"
PROVENANCE_PATH = ASSET_DIR / "chromamatter_icon_PROVENANCE.md"
EXPECTED_PNG_SHA256 = (
    "BDDD06B090F25FFEAE20F393A86A8E65B297923D2F8A1FE8461CF93A9B3AEA3B"
)
EXPECTED_ICO_SHA256 = (
    "EC7324CA3B19134ED31FA34870DD89DD12913FF5275EA06A2D7419CD60B1C5B0"
)
EXPECTED_ICO_SIZES = {
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load_icon_tooling():
    path = REPO_ROOT / "tooling" / "generate_public_icon.py"
    spec = importlib.util.spec_from_file_location("generate_public_icon", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not import icon tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChromaMatterIconAssetTests(unittest.TestCase):
    def test_png_is_exact_reviewed_asset_with_transparent_outer_corners(self):
        self.assertEqual(_sha256(PNG_PATH), EXPECTED_PNG_SHA256)
        with Image.open(PNG_PATH) as image:
            rgba = image.convert("RGBA")
            self.assertEqual(rgba.size, (1024, 1024))
            self.assertEqual(rgba.mode, "RGBA")
            alpha = rgba.getchannel("A")
            for point in ((0, 0), (1023, 0), (0, 1023), (1023, 1023)):
                with self.subTest(point=point):
                    self.assertEqual(alpha.getpixel(point), 0)

            # The light chest, highlights, and lettering inside the rounded
            # tile must not be mistaken for the connected outside matte.
            opaque_light_pixels = sum(
                1
                for red, green, blue, pixel_alpha in rgba.getdata()
                if pixel_alpha == 255 and min(red, green, blue) > 230
            )
            self.assertGreater(opaque_light_pixels, 2_000)
            self.assertEqual(alpha.getpixel((512, 660)), 255)

    def test_ico_contains_all_explicit_windows_frames(self):
        self.assertEqual(_sha256(ICO_PATH), EXPECTED_ICO_SHA256)
        with Image.open(ICO_PATH) as image:
            self.assertEqual(image.format, "ICO")
            self.assertEqual(image.ico.sizes(), EXPECTED_ICO_SIZES)
            for size in EXPECTED_ICO_SIZES:
                with self.subTest(size=size):
                    frame = image.ico.getimage(size).convert("RGBA")
                    self.assertEqual(frame.size, size)
                    self.assertEqual(frame.getpixel((0, 0))[3], 0)

    def test_tooling_rejects_an_unselected_source_image(self):
        tooling = _load_icon_tooling()
        with tempfile.TemporaryDirectory() as temporary:
            wrong_source = Path(temporary) / "wrong.png"
            Image.new("RGB", (8, 8), "white").save(wrong_source)
            with self.assertRaisesRegex(ValueError, "not the selected"):
                tooling.prepare_icon(wrong_source)

    def test_provenance_pins_source_and_generated_hashes(self):
        provenance = PROVENANCE_PATH.read_text(encoding="utf-8")
        tooling = _load_icon_tooling()
        self.assertIn(tooling.SOURCE_SHA256, provenance)
        self.assertIn(EXPECTED_PNG_SHA256, provenance)
        self.assertIn(EXPECTED_ICO_SHA256, provenance)
        self.assertIn("creator-authorized for the approved source-only release", provenance)
        self.assertIn("ZENITH DYNAMICS CORP.", provenance)
        self.assertIn("not an independent trademark search", provenance)


class ChromaMatterTkIconTests(unittest.TestCase):
    def test_tk_loads_toolbar_and_window_sizes_from_runtime_png(self):
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")

        sys.path.insert(0, str(FIXED_APP))
        try:
            from spectrum_mapper.gui import MapperApp
        finally:
            sys.path.pop(0)

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        try:
            app = MapperApp.__new__(MapperApp)
            app.root = root
            with patch(
                "spectrum_mapper.gui.resource_path",
                return_value=PNG_PATH,
            ):
                app._load_brand_assets()
            self.assertIsNotNone(app.brand_logo_image)
            self.assertIsNotNone(app.window_icon_image)
            self.assertEqual(app.brand_logo_image.width(), 32)
            self.assertEqual(app.brand_logo_image.height(), 32)
            self.assertEqual(app.window_icon_image.width(), 64)
            self.assertEqual(app.window_icon_image.height(), 64)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
