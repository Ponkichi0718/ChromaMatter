from __future__ import annotations

import hashlib
import importlib.metadata
import io
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import numpy as np
from PIL import Image

from spectrum_mapper.decal_image import (
    DEFAULT_DECAL_LIMITS,
    DecalImage,
    DecalImageError,
    DecalLimits,
    load_decal_bytes,
    load_decal_image,
)


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]


def png_bytes(image: Image.Image, **save_options: object) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", **save_options)
    return stream.getvalue()


def svg_bytes(body: str, *, width: int = 32, height: int = 20) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">{body}</svg>'
    ).encode("utf-8")


class DecalImageValueTests(unittest.TestCase):
    def test_value_owns_normalizes_and_freezes_rgba(self) -> None:
        source = np.zeros((2, 3, 4), dtype=np.int16)
        source[0, 0] = (1, 2, 3, 4)
        decal = DecalImage(source, "PNG")
        source[0, 0] = 255

        self.assertEqual(decal.source_kind, "png")
        self.assertEqual(decal.source_format, "PNG")
        self.assertEqual((decal.width, decal.height), (3, 2))
        self.assertEqual(decal.rgba.dtype, np.uint8)
        self.assertTrue(decal.rgba.flags.c_contiguous)
        self.assertFalse(decal.rgba.flags.writeable)
        self.assertEqual(decal.rgba[0, 0].tolist(), [1, 2, 3, 4])
        self.assertRegex(decal.sha256, r"^[0-9a-f]{64}$")
        writable = decal.copy_rgba()
        self.assertTrue(writable.flags.writeable)

    def test_value_rejects_invalid_shape_kind_and_digest(self) -> None:
        with self.assertRaises(ValueError):
            DecalImage(np.zeros((2, 3, 3), dtype=np.uint8), "png")
        with self.assertRaises(ValueError):
            DecalImage(np.zeros((2, 3, 4), dtype=np.uint8), "jpeg")
        with self.assertRaises(ValueError):
            DecalImage(np.zeros((2, 3, 4), dtype=np.uint8), "png", "bad")


class PngDecalTests(unittest.TestCase):
    def assert_code(self, expected: str, callable_, *args, **kwargs) -> DecalImageError:
        with self.assertRaises(DecalImageError) as raised:
            callable_(*args, **kwargs)
        self.assertEqual(raised.exception.code, expected)
        return raised.exception

    def test_path_load_normalizes_rgba_and_keeps_source_identity(self) -> None:
        image = Image.new("RGBA", (3, 2), (10, 20, 30, 255))
        image.putpixel((1, 0), (40, 50, 60, 64))
        payload = png_bytes(image)
        with tempfile.TemporaryDirectory(prefix="obj-adjuster-decal-") as temp:
            path = Path(temp) / "sample.PNG"
            path.write_bytes(payload)
            decal = load_decal_image(path)

        self.assertEqual(decal.source_kind, "png")
        self.assertEqual(decal.source_path, path)
        self.assertEqual(decal.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual((decal.width, decal.height), (3, 2))
        self.assertEqual(decal.rgba[0, 1].tolist(), [40, 50, 60, 64])
        self.assertTrue(decal.has_transparency)

    def test_palette_transparency_and_rgb_are_normalized(self) -> None:
        palette = Image.new("P", (2, 1))
        palette.putpalette([255, 0, 0, 0, 255, 0] + [0] * (256 * 3 - 6))
        palette.putdata([0, 1])
        palette.info["transparency"] = 1
        decal = load_decal_bytes(png_bytes(palette), filename="palette.png")
        self.assertEqual(decal.rgba[0, 0].tolist(), [255, 0, 0, 255])
        self.assertEqual(decal.rgba[0, 1].tolist(), [0, 255, 0, 0])

        rgb = load_decal_bytes(
            png_bytes(Image.new("RGB", (1, 1), (5, 6, 7))), filename="rgb.png"
        )
        self.assertEqual(rgb.rgba[0, 0].tolist(), [5, 6, 7, 255])

    def test_wrong_magic_corrupt_and_unsupported_suffix_fail_closed(self) -> None:
        self.assert_code(
            "content_mismatch", load_decal_bytes, b"not png", filename="wrong.png"
        )
        self.assert_code(
            "unsupported_file_type",
            load_decal_bytes,
            png_bytes(Image.new("RGB", (1, 1))),
            filename="wrong.jpg",
        )

    def test_animated_png_is_rejected(self) -> None:
        first = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
        second = Image.new("RGBA", (2, 2), (0, 0, 255, 255))
        payload = png_bytes(
            first, save_all=True, append_images=[second], duration=100, loop=0
        )
        self.assert_code(
            "animated_png_unsupported",
            load_decal_bytes,
            payload,
            filename="animated.png",
        )

    def test_file_dimension_and_pixel_limits_precede_decode_work(self) -> None:
        tiny = DecalLimits(max_file_bytes=10, max_width=4, max_height=4, max_pixels=8)
        self.assert_code(
            "file_too_large", load_decal_bytes, b"x" * 11, filename="large.png", limits=tiny
        )
        payload = png_bytes(Image.new("RGBA", (3, 3)))
        room = DecalLimits(max_file_bytes=1024, max_width=4, max_height=4, max_pixels=8)
        self.assert_code(
            "pixel_limit_exceeded",
            load_decal_bytes,
            payload,
            filename="pixels.png",
            limits=room,
        )

    def test_path_read_is_bounded_even_if_file_grows_after_stat(self) -> None:
        limits = DecalLimits(max_file_bytes=10)
        opened = mock.MagicMock()
        opened.__enter__.return_value.read.return_value = b"x" * 11
        with (
            mock.patch.object(Path, "stat", return_value=mock.Mock(st_size=1)),
            mock.patch.object(Path, "is_file", return_value=True),
            mock.patch.object(Path, "open", return_value=opened),
        ):
            self.assert_code(
                "file_too_large",
                load_decal_image,
                Path("changed.png"),
                limits=limits,
            )
        opened.__enter__.return_value.read.assert_called_once_with(11)

    def test_buffer_size_is_checked_before_copy_and_invalid_types_fail(self) -> None:
        limits = DecalLimits(max_file_bytes=4)
        self.assert_code(
            "file_too_large",
            load_decal_bytes,
            memoryview(b"12345"),
            filename="large.png",
            limits=limits,
        )
        self.assert_code(
            "invalid_payload", load_decal_bytes, "not bytes", filename="bad.png"
        )


class SvgDecalTests(unittest.TestCase):
    def assert_code(self, expected: str, payload: bytes, **kwargs) -> DecalImageError:
        with self.assertRaises(DecalImageError) as raised:
            load_decal_bytes(payload, filename="sample.svg", **kwargs)
        self.assertEqual(raised.exception.code, expected)
        return raised.exception

    def test_real_resvg_file_smoke_renders_path_transform_and_alpha(self) -> None:
        payload = svg_bytes(
            '<rect width="32" height="20" fill="#102030"/>'
            '<path d="M2 2h8v8H2z" fill="#ff0000"/>'
            '<g transform="translate(12 2)">'
            '<circle cx="4" cy="4" r="4" fill="#00ff00" fill-opacity="0.5"/>'
            "</g>"
        )
        with tempfile.TemporaryDirectory(prefix="obj-adjuster-svg-") as temp:
            path = Path(temp) / "safe.svg"
            path.write_bytes(payload)
            decal = load_decal_image(path)

        self.assertEqual(decal.source_kind, "svg")
        self.assertEqual((decal.width, decal.height), (32, 20))
        self.assertEqual(decal.rgba[5, 5].tolist(), [255, 0, 0, 255])
        # Alpha-compositing over the dark rectangle must be rendered by resvg,
        # not approximated by a custom path parser.
        green = decal.rgba[6, 16]
        self.assertGreater(int(green[1]), int(green[0]))
        self.assertEqual(int(green[3]), 255)

    def test_svg_can_be_rasterized_to_an_explicit_bounded_size(self) -> None:
        payload = svg_bytes('<rect width="32" height="20" fill="#336699"/>')
        decal = load_decal_bytes(
            payload, filename="resized.svg", svg_raster_size=(64, 10)
        )
        self.assertEqual((decal.width, decal.height), (64, 10))
        self.assertEqual(decal.rgba[5, 30].tolist(), [51, 102, 153, 255])

    def test_invalid_svg_size_and_natural_dimensions_are_rejected(self) -> None:
        payload = svg_bytes('<rect width="32" height="20"/>')
        self.assert_code(
            "invalid_svg_raster_size", payload, svg_raster_size=(True, 20)
        )
        limits = DecalLimits(max_width=16, max_height=16, max_pixels=256)
        self.assert_code("dimensions_too_large", payload, limits=limits)

    def test_doctype_entity_processing_instruction_and_utf16_are_rejected(self) -> None:
        cases = (
            b'<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>',
            b'<!DOCTYPE svg [<!ENTITY x "x">]><svg xmlns="http://www.w3.org/2000/svg"/>',
            b'<?xml version="1.0"?><?target x?><svg xmlns="http://www.w3.org/2000/svg"/>',
        )
        for payload in cases:
            with self.subTest(payload=payload[:30]):
                self.assert_code("svg_unsafe_xml", payload)
        self.assert_code(
            "svg_encoding_unsupported",
            '<svg xmlns="http://www.w3.org/2000/svg"/>'.encode("utf-16"),
        )

    def test_active_or_resource_bearing_elements_fail_closed(self) -> None:
        cases = {
            "svg_active_content": (
                "<script/>",
                "<foreignObject/>",
                "<style>rect{fill:red}</style>",
                '<text x="0" y="10">unsafe font dependency</text>',
                "<filter/>",
            ),
            "svg_external_reference": (
                '<image href="other.png"/>',
                '<use href="#shape"/>',
                '<a href="https://example.invalid"><path d="M0 0"/></a>',
            ),
        }
        for expected, bodies in cases.items():
            for body in bodies:
                with self.subTest(expected=expected, body=body):
                    self.assert_code(expected, svg_bytes(body))

    def test_event_style_href_and_url_attributes_fail_closed(self) -> None:
        cases = (
            '<rect width="1" height="1" onclick="alert(1)"/>',
            '<rect width="1" height="1" style="fill:red"/>',
            '<rect width="1" height="1" fill="url(#gradient)"/>',
            '<path d="M0 0" href="file:///secret"/>',
        )
        for body in cases:
            with self.subTest(body=body):
                error = self.assert_code(
                    "svg_active_content" if "onclick" in body or "style=" in body else "svg_external_reference",
                    svg_bytes(body),
                )
                self.assertTrue(str(error))

    def test_foreign_namespaces_are_rejected_even_without_href(self) -> None:
        payload = (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="urn:external" '
            'width="10" height="10"><rect x:payload="1" width="1" height="1"/></svg>'
        ).encode()
        self.assert_code("svg_external_reference", payload)

    def test_node_depth_attribute_and_path_limits_are_enforced(self) -> None:
        nodes = DecalLimits(max_svg_nodes=2)
        self.assert_code("svg_node_limit", svg_bytes("<g><rect/></g>"), limits=nodes)
        depth = DecalLimits(max_svg_depth=2)
        self.assert_code("svg_depth_limit", svg_bytes("<g><g/></g>"), limits=depth)
        attributes = DecalLimits(max_svg_attributes=2)
        self.assert_code(
            "svg_attribute_limit",
            b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1" viewBox="0 0 1 1"/>',
            limits=attributes,
        )
        paths = DecalLimits(max_svg_path_characters=5)
        self.assert_code("svg_path_limit", svg_bytes('<path d="M0 0h10v10"/>'), limits=paths)

        # Two vector nodes repainting a 10 x 10 canvas cost 200 units.  Keep
        # this limit independently configurable from node/file size so a
        # high-resolution overlap bomb is rejected before native rendering.
        work = DecalLimits(max_svg_render_work=199)
        self.assert_code(
            "svg_render_work_limit",
            svg_bytes('<rect width="10" height="10"/>', width=10, height=10),
            limits=work,
        )

    def test_malformed_and_non_svg_xml_are_rejected(self) -> None:
        self.assert_code("invalid_svg", b"<svg>")
        self.assert_code("invalid_svg_root", b"<html/>")


class DecalPackagingTests(unittest.TestCase):
    def test_resvg_is_pinned_for_source_and_excluded_from_frozen_runtime(self) -> None:
        requirements = (HERE / "requirements-build.txt").read_text(encoding="utf-8")
        spec = (HERE / "TripoSpectrumMapper_fixed.spec").read_text(encoding="utf-8")
        self.assertIn("resvg==0.2.0", requirements)
        self.assertEqual(importlib.metadata.version("resvg"), "0.2.0")
        distribution = importlib.metadata.distribution("resvg")
        for relative in (
            "resvg-0.2.0.dist-info/licenses/LICENSE.txt",
            "resvg-0.2.0.dist-info/sboms/resvg.cyclonedx.json",
        ):
            with self.subTest(relative=relative):
                self.assertTrue(distribution.locate_file(relative).is_file())
        self.assertNotIn('copy_metadata("resvg")', spec)
        self.assertNotIn('f"{RESVG_DIST_INFO}/direct_url.json"', spec)
        self.assertIn("def is_private_install_origin_metadata(entry):", spec)
        self.assertIn('.endswith("/direct_url.json")', spec)
        self.assertIn("and not is_private_install_origin_metadata(entry)", spec)
        self.assertIn("def is_source_only_resvg_metadata(entry):", spec)
        self.assertIn('destination == "resvg-0.2.0.dist-info"', spec)
        self.assertIn("and not is_source_only_resvg_metadata(entry)", spec)
        self.assertIn('"spectrum_mapper.decal_image"', spec)
        self.assertIn('excludes=["resvg", "resvg._resvg"]', spec)
        self.assertIn("LICENSE_RESVG_APACHE_2.0.txt", spec)
        for excluded_runtime_input in (
            'RESVG_DIST_INFO = "resvg-0.2.0.dist-info"',
            'f"{RESVG_DIST_INFO}/METADATA"',
            'f"{RESVG_DIST_INFO}/WHEEL"',
            "resvg.cyclonedx.json",
            "LICENSE_RESVG_PY.txt",
            "LICENSE_RESVG_MIT.txt",
        ):
            with self.subTest(excluded_runtime_input=excluded_runtime_input):
                self.assertNotIn(excluded_runtime_input, spec)

    def test_privacy_safe_metadata_subset_still_exposes_version(self) -> None:
        installed = importlib.metadata.distribution("resvg")
        dist_info = "resvg-0.2.0.dist-info"
        relative_files = (
            "METADATA",
            "WHEEL",
            "licenses/LICENSE.txt",
            "sboms/resvg.cyclonedx.json",
        )
        with tempfile.TemporaryDirectory(prefix="obj-adjuster-resvg-meta-") as temp:
            root = Path(temp)
            for relative in relative_files:
                destination = root / dist_info / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = installed.locate_file(f"{dist_info}/{relative}")
                destination.write_bytes(source.read_bytes())
            matches = [
                item
                for item in importlib.metadata.distributions(path=[str(root)])
                if item.metadata.get("Name") == "resvg"
            ]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].version, "0.2.0")
            self.assertFalse((root / dist_info / "direct_url.json").exists())

    def test_resvg_source_attribution_is_public_but_runtime_is_excluded(self) -> None:
        notice = (PROJECT / "licenses" / "THIRD_PARTY_LICENSES.txt").read_text(
            encoding="utf-8"
        )
        for filename in (
            "LICENSE_RESVG_PY.txt",
            "LICENSE_RESVG_MIT.txt",
            "LICENSE_RESVG_APACHE_2.0.txt",
        ):
            with self.subTest(filename=filename):
                self.assertTrue((PROJECT / "licenses" / filename).is_file())
        self.assertIn("resvg-py 0.2.0", notice)
        self.assertIn("resvg/usvg Rust dependency closure", notice)
        self.assertIn("Source-only development dependency", notice)
        self.assertIn(
            "intentionally excluded from the public r32 frozen application",
            notice,
        )
        self.assertNotIn("80-component", notice)

    def test_security_limits_are_stric_release_constants(self) -> None:
        self.assertEqual(DEFAULT_DECAL_LIMITS.max_file_bytes, 8 * 1024 * 1024)
        self.assertEqual(DEFAULT_DECAL_LIMITS.max_width, 4096)
        self.assertEqual(DEFAULT_DECAL_LIMITS.max_height, 4096)
        self.assertEqual(DEFAULT_DECAL_LIMITS.max_pixels, 16 * 1024 * 1024)
        self.assertEqual(DEFAULT_DECAL_LIMITS.max_svg_nodes, 10_000)
        self.assertEqual(DEFAULT_DECAL_LIMITS.max_svg_depth, 64)
        self.assertEqual(
            DEFAULT_DECAL_LIMITS.max_svg_render_work, 512 * 1024 * 1024
        )


if __name__ == "__main__":
    unittest.main()
