"""Prepare the user-selected ChromaMatter artwork for Windows and Tk.

The source image is deliberately not stored in the public repository. Pass
the exact user-supplied PNG with ``--source``. Its hash is pinned so an
unrelated image cannot silently replace the approved artwork.

Only the light background connected to the four outside corners is removed.
Light details inside the rounded app tile remain opaque. All resizing uses
Pillow's high-quality LANCZOS filter, and ICO frames are supplied explicitly
instead of asking an operating system to scale a single frame at runtime.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps


SOURCE_SHA256 = "CEB0A34A314D50DBA6B7AA5105C0007D5AE7C4BBE404D636EADB84ED6DB740EC"
CANVAS_SIZE = 1024
BACKGROUND_MINIMUM = 180
FULLY_TRANSPARENT_MINIMUM = 250
ICON_SIZES = (
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
)
HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = HERE.parent / "source" / "fixed_app" / "assets"
PNG_NAME = "obj_adjuster_icon.png"
ICO_NAME = "obj_adjuster_icon.ico"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _border_connected_background(source: Image.Image) -> Image.Image:
    """Return the bright region connected to the four canvas corners."""

    red, green, blue = source.convert("RGB").split()
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    candidates = minimum.point(
        lambda value: 255 if value >= BACKGROUND_MINIMUM else 0,
        mode="L",
    )

    # A rounded-square icon separates the outside matte into at most four
    # corner components. Flooding each corner prevents similarly bright
    # lettering and highlights inside the dark tile from being selected.
    connected = candidates.copy()
    width, height = connected.size
    for seed in (
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
    ):
        if connected.getpixel(seed) == 255:
            ImageDraw.floodfill(connected, seed, 128, thresh=0)
    return connected.point(
        lambda value: 255 if value == 128 else 0,
        mode="L",
    )


def remove_connected_white_matte(source: Image.Image) -> Image.Image:
    """Remove only the outside white matte and recover antialiased edges."""

    rgba = ImageOps.exif_transpose(source).convert("RGBA")
    connected = _border_connected_background(rgba)
    rgb_bytes = rgba.convert("RGB").tobytes()
    connected_bytes = connected.tobytes()
    output = bytearray(len(connected_bytes) * 4)
    transition = FULLY_TRANSPARENT_MINIMUM - BACKGROUND_MINIMUM

    for pixel_index, is_background in enumerate(connected_bytes):
        source_offset = pixel_index * 3
        output_offset = pixel_index * 4
        red = rgb_bytes[source_offset]
        green = rgb_bytes[source_offset + 1]
        blue = rgb_bytes[source_offset + 2]

        if not is_background:
            alpha = 255
        else:
            minimum = min(red, green, blue)
            if minimum >= FULLY_TRANSPARENT_MINIMUM:
                alpha = 0
            else:
                alpha = round(
                    255
                    * (FULLY_TRANSPARENT_MINIMUM - minimum)
                    / transition
                )
                alpha = max(0, min(255, alpha))

        if is_background and alpha < 255:
            # The selected component is outside the artwork. Its RGB is the
            # original white matte blended with an edge shadow, not authored
            # interior detail. Store a neutral dark RGB under the graduated
            # alpha so later downsampling cannot reveal a white fringe on the
            # application's dark toolbar.
            red = green = blue = 0

        output[output_offset : output_offset + 4] = bytes(
            (red, green, blue, alpha)
        )

    return Image.frombytes("RGBA", rgba.size, bytes(output))


def prepare_icon(source_path: Path) -> Image.Image:
    actual_hash = sha256_file(source_path)
    if actual_hash != SOURCE_SHA256:
        raise ValueError(
            "The icon source is not the selected user-supplied PNG: "
            f"expected {SOURCE_SHA256}, got {actual_hash}"
        )

    with Image.open(source_path) as source:
        prepared = remove_connected_white_matte(source)
    return prepared.resize(
        (CANVAS_SIZE, CANVAS_SIZE),
        Image.Resampling.LANCZOS,
        reducing_gap=3.0,
    )


def write_icon_assets(source_path: Path, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    icon = prepare_icon(source_path)
    png_path = output_dir / PNG_NAME
    ico_path = output_dir / ICO_NAME

    icon.save(png_path, format="PNG", optimize=True)
    frames = [
        icon.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)
        for size in ICON_SIZES
    ]
    for frame in frames:
        width, height = frame.size
        for corner in (
            (0, 0),
            (width - 1, 0),
            (0, height - 1),
            (width - 1, height - 1),
        ):
            frame.putpixel(corner, (0, 0, 0, 0))
    frames[-1].save(
        ico_path,
        format="ICO",
        sizes=ICON_SIZES,
        append_images=frames[:-1],
    )
    return png_path, ico_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create the selected ChromaMatter PNG and Windows ICO assets."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Exact user-supplied 1254 px PNG (verified by SHA-256).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Destination asset directory.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    png_path, ico_path = write_icon_assets(
        args.source.resolve(),
        args.output_dir.resolve(),
    )
    print(f"PNG {sha256_file(png_path)}  {png_path}")
    print(f"ICO {sha256_file(ico_path)}  {ico_path}")


if __name__ == "__main__":
    main()
