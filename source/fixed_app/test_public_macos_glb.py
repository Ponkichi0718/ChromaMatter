from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np
import trimesh


FIXED_APP = Path(__file__).resolve().parent
REPOSITORY = FIXED_APP.parents[1]
SAMPLES = REPOSITORY / "samples"
WORKFLOW = REPOSITORY / ".github" / "workflows" / "macos-arm64-alpha.yml"
sys.path.insert(0, str(REPOSITORY))
sys.path.insert(0, str(FIXED_APP))

from samples.generate_macos_alpha_test_glb import (  # noqa: E402
    EXPECTED_SHA256,
    OUTPUT_FILENAME,
    build_glb_bytes,
    main as generate_main,
)
from spectrum_mapper.engine import edge_topology  # noqa: E402
from spectrum_mapper.gltf_import import (  # noqa: E402
    inspect_gltf_asset,
    load_gltf_asset,
)


def _decode_glb(payload: bytes) -> tuple[dict[str, object], bytes]:
    magic, version, declared_length = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(payload):
        raise AssertionError("invalid GLB 2.0 header")
    json_length, json_type = struct.unpack_from("<II", payload, 12)
    json_start = 20
    json_end = json_start + json_length
    binary_length, binary_type = struct.unpack_from("<II", payload, json_end)
    binary_start = json_end + 8
    binary_end = binary_start + binary_length
    if json_type != 0x4E4F534A or binary_type != 0x004E4942:
        raise AssertionError("expected one JSON chunk followed by one BIN chunk")
    if binary_end != len(payload):
        raise AssertionError("unexpected trailing GLB data")
    document = json.loads(payload[json_start:json_end].decode("ascii"))
    return document, payload[binary_start:binary_end]


class PublicMacOSGLBTests(unittest.TestCase):
    def test_bytes_are_small_and_deterministic(self) -> None:
        first = build_glb_bytes()
        second = build_glb_bytes()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1524)
        self.assertEqual(hashlib.sha256(first).hexdigest(), EXPECTED_SHA256)

    def test_document_is_static_embedded_vertex_colour_triangles_only(self) -> None:
        document, binary = _decode_glb(build_glb_bytes())
        self.assertEqual(document["asset"], {"version": "2.0"})
        self.assertNotIn("generator", document["asset"])
        for forbidden in (
            "animations",
            "cameras",
            "extensions",
            "extras",
            "images",
            "materials",
            "skins",
            "textures",
        ):
            self.assertNotIn(forbidden, document)
        self.assertEqual(document["buffers"], [{"byteLength": 800}])
        self.assertNotIn("uri", json.dumps(document, sort_keys=True))
        self.assertEqual(len(binary), 800)

        primitive = document["meshes"][0]["primitives"][0]
        self.assertEqual(primitive["mode"], 4)
        self.assertEqual(
            primitive["attributes"], {"COLOR_0": 1, "POSITION": 0}
        )
        self.assertEqual(primitive["indices"], 2)
        position, colour, indices = document["accessors"]
        self.assertEqual(
            (position["componentType"], position["count"], position["type"]),
            (5126, 32, "VEC3"),
        )
        self.assertEqual(
            (
                colour["componentType"],
                colour["count"],
                colour["type"],
                colour["normalized"],
            ),
            (5121, 32, "VEC4", True),
        )
        self.assertEqual(
            (indices["componentType"], indices["count"], indices["type"]),
            (5123, 144, "SCALAR"),
        )

    def test_existing_loader_sees_four_colours_and_watertight_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / OUTPUT_FILENAME
            path.write_bytes(build_glb_bytes())
            plan = inspect_gltf_asset(path)
            self.assertEqual(plan.triangle_count, 48)
            self.assertEqual(plan.vertex_count_upper_bound, 32)
            asset = load_gltf_asset(path, vertex_color_policy="multiply")

        self.assertEqual(asset.vertices.shape, (32, 3))
        self.assertEqual(asset.faces.shape, (48, 3))
        self.assertEqual(asset.colors.shape, (32, 3))
        observed = {
            tuple(row)
            for row in np.rint(np.clip(asset.colors, 0.0, 1.0) * 255.0)
            .astype(np.uint8)
            .tolist()
        }
        self.assertEqual(
            observed,
            {(255, 0, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)},
        )

        topology = edge_topology(asset.faces, len(asset.vertices))
        self.assertTrue(topology["watertight"])
        self.assertEqual(topology["boundary_edges"], 0)
        self.assertEqual(topology["nonmanifold_edges"], 0)
        mesh = trimesh.Trimesh(
            vertices=asset.vertices,
            faces=asset.faces,
            process=False,
        )
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_winding_consistent)
        self.assertTrue(mesh.is_volume)
        bodies = list(mesh.split(only_watertight=False))
        self.assertEqual(len(bodies), 4)
        self.assertTrue(all(body.is_volume and body.volume > 0.0 for body in bodies))

    def test_cli_writes_only_the_requested_glb(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / OUTPUT_FILENAME
            self.assertEqual(generate_main(["--output", str(output)]), 0)
            self.assertEqual(output.read_bytes(), build_glb_bytes())
            self.assertEqual(
                [path.name for path in output.parent.iterdir()],
                [OUTPUT_FILENAME],
            )

    def test_fixture_is_generated_only_during_staging_with_cc0_notice(self) -> None:
        self.assertFalse((SAMPLES / OUTPUT_FILENAME).exists())
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python samples/generate_macos_alpha_test_glb.py", workflow)
        self.assertIn(
            '--output "$stage/ChromaMatter-Public-Four-Color-Test.glb"',
            workflow,
        )
        self.assertIn("README_PUBLIC_TEST_MODEL.md", workflow)
        self.assertIn("LICENSE_PUBLIC_TEST_MODEL_CC0.txt", workflow)
        self.assertIn("PUBLIC_TEST_MODEL_SHA256.txt", workflow)
        self.assertIn("shasum -a 256 -c PUBLIC_TEST_MODEL_SHA256.txt", workflow)

        license_text = (SAMPLES / "LICENSE.txt").read_text(encoding="utf-8")
        readme = (SAMPLES / "MACOS_ALPHA_TEST_MODEL_README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("CC0 1.0 Universal", license_text)
        self.assertIn(OUTPUT_FILENAME, license_text)
        self.assertIn(EXPECTED_SHA256, readme)
        self.assertIn("no AI service", readme)
        self.assertIn("AI service", readme)


if __name__ == "__main__":
    unittest.main()
