#!/usr/bin/env python3
"""Generate the deterministic, rights-safe ChromaMatter four-colour GLB.

The model is built only from four elementary boxes.  It does not read an
image, model, network resource, user directory, or environment-specific input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct


OUTPUT_FILENAME = "ChromaMatter-Public-Four-Color-Test.glb"
EXPECTED_SHA256 = "1b6092448e62a93f5e29a9c6dda1265a7a2179c2eacd293f7d8f02d1f268c563"

_GLB_JSON_CHUNK = 0x4E4F534A
_GLB_BIN_CHUNK = 0x004E4942
_TRIANGLES = 4

_COLOURS = (
    (255, 0, 0, 255),
    (0, 0, 255, 255),
    (255, 255, 255, 255),
    (0, 0, 0, 255),
)
_CENTRES_XZ = ((-6.0, -6.0), (6.0, -6.0), (-6.0, 6.0), (6.0, 6.0))

# Outward winding for a Y-up box.  Each edge occurs exactly twice.
_BOX_TRIANGLES = (
    (0, 1, 2),
    (0, 2, 3),
    (4, 6, 5),
    (4, 7, 6),
    (0, 4, 5),
    (0, 5, 1),
    (1, 5, 6),
    (1, 6, 2),
    (3, 2, 6),
    (3, 6, 7),
    (0, 3, 7),
    (0, 7, 4),
)


def _box_vertices(center_x: float, center_z: float) -> tuple[tuple[float, ...], ...]:
    half = 4.0
    top = 8.0
    x0, x1 = center_x - half, center_x + half
    z0, z1 = center_z - half, center_z + half
    return (
        (x0, 0.0, z0),
        (x1, 0.0, z0),
        (x1, 0.0, z1),
        (x0, 0.0, z1),
        (x0, top, z0),
        (x1, top, z0),
        (x1, top, z1),
        (x0, top, z1),
    )


def _pad(payload: bytes, byte: bytes) -> bytes:
    return payload + byte * (-len(payload) % 4)


def build_glb_bytes() -> bytes:
    """Return the byte-identical public test GLB."""

    vertices: list[tuple[float, float, float]] = []
    colours: list[tuple[int, int, int, int]] = []
    indices: list[int] = []
    for box_index, ((center_x, center_z), colour) in enumerate(
        zip(_CENTRES_XZ, _COLOURS, strict=True)
    ):
        base = box_index * 8
        vertices.extend(_box_vertices(center_x, center_z))
        colours.extend((colour,) * 8)
        indices.extend(
            base + vertex
            for triangle in _BOX_TRIANGLES
            for vertex in triangle
        )

    positions = b"".join(struct.pack("<3f", *vertex) for vertex in vertices)
    colour_bytes = b"".join(bytes(colour) for colour in colours)
    index_bytes = struct.pack(f"<{len(indices)}H", *indices)
    binary = positions + colour_bytes + index_bytes

    position_offset = 0
    colour_offset = len(positions)
    index_offset = colour_offset + len(colour_bytes)
    document = {
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(vertices),
                "max": [10.0, 8.0, 10.0],
                "min": [-10.0, 0.0, -10.0],
                "type": "VEC3",
            },
            {
                "bufferView": 1,
                "componentType": 5121,
                "count": len(colours),
                "normalized": True,
                "type": "VEC4",
            },
            {
                "bufferView": 2,
                "componentType": 5123,
                "count": len(indices),
                "max": [len(vertices) - 1],
                "min": [0],
                "type": "SCALAR",
            },
        ],
        "asset": {"version": "2.0"},
        "bufferViews": [
            {
                "buffer": 0,
                "byteLength": len(positions),
                "byteOffset": position_offset,
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteLength": len(colour_bytes),
                "byteOffset": colour_offset,
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteLength": len(index_bytes),
                "byteOffset": index_offset,
                "target": 34963,
            },
        ],
        "buffers": [{"byteLength": len(binary)}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"COLOR_0": 1, "POSITION": 0},
                        "indices": 2,
                        "mode": _TRIANGLES,
                    }
                ]
            }
        ],
        "nodes": [{"mesh": 0}],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
    }
    json_payload = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    json_payload = _pad(json_payload, b" ")
    binary_payload = _pad(binary, b"\0")
    body = b"".join(
        (
            struct.pack("<II", len(json_payload), _GLB_JSON_CHUNK),
            json_payload,
            struct.pack("<II", len(binary_payload), _GLB_BIN_CHUNK),
            binary_payload,
        )
    )
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the CC0 ChromaMatter four-colour GLB test model."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    output = args.output.resolve()
    if output.suffix.casefold() != ".glb":
        parser.error("--output must end in .glb")
    payload = build_glb_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(
            "Generated bytes do not match the reviewed fixture identity: " + digest
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    print(
        f"wrote={output.name} bytes={len(payload)} sha256={digest} "
        "vertices=32 triangles=48 colours=4 bodies=4"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
