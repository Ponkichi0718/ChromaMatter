from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gltf_import import (
    GltfImportError,
    GltfImportPlan,
    _sample_image_linear,
    _sample_image_linear_chunk,
    inspect_gltf_asset,
    load_gltf_asset,
)


def _append(buffer: bytearray, payload: bytes, alignment: int = 4) -> tuple[int, int]:
    while len(buffer) % alignment:
        buffer.append(0)
    offset = len(buffer)
    buffer.extend(payload)
    return offset, len(payload)


def _png_bytes(pixels: np.ndarray) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(np.asarray(pixels, dtype=np.uint8)).save(stream, format="PNG")
    return stream.getvalue()


def _glb_bytes(document: dict[str, object], binary: bytes) -> bytes:
    document = json.loads(json.dumps(document))
    buffers = document.setdefault("buffers", [])
    if not buffers:
        buffers.append({"byteLength": len(binary)})
    else:
        buffers[0]["byteLength"] = len(binary)
    json_payload = json.dumps(
        document, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    json_payload += b" " * (-len(json_payload) % 4)
    binary_payload = binary + b"\0" * (-len(binary) % 4)
    chunks = [
        struct.pack("<II", len(json_payload), 0x4E4F534A) + json_payload,
        struct.pack("<II", len(binary_payload), 0x004E4942) + binary_payload,
    ]
    body = b"".join(chunks)
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def _write_glb(root: Path, document: dict[str, object], binary: bytes) -> Path:
    path = root / "synthetic.glb"
    path.write_bytes(_glb_bytes(document, binary))
    return path


def _base_document() -> dict[str, object]:
    return {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": []}],
        "bufferViews": [],
        "accessors": [],
    }


def _multipart_colour_document(
    *,
    categorical: bool,
    shared_texture: bool = True,
    dominant_count: int = 11,
    exploded_provenance: bool = True,
    known_segmentation_palette: bool = True,
) -> tuple[dict[str, object], bytes, np.ndarray]:
    binary = bytearray()
    positions = np.asarray(
        [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [2, 0, 0],
            [3, 0, 0],
            [2, 1, 0],
            [4, 0, 0],
            [5, 0, 0],
            [4, 1, 0],
            [6, 0, 0],
            [7, 0, 0],
            [6, 1, 0],
        ],
        dtype="<f4",
    )
    uv = np.zeros((len(positions), 2), dtype="<f4")
    if categorical:
        first_id, second_id = (
            ((31, 119, 180), (174, 199, 232))
            if known_segmentation_palette
            else ((220, 60, 80), (60, 180, 220))
        )
        first_colours = np.tile(
            np.asarray([*first_id, 255], dtype=np.uint8), (len(positions), 1)
        )
        second_colours = np.tile(
            np.asarray([*second_id, 255], dtype=np.uint8), (len(positions), 1)
        )
        first_colours[dominant_count:, :3] = 255
        second_colours[dominant_count:, :3] = 255
    else:
        first_colours = np.tile(
            np.asarray(
                [
                    [255, 0, 0, 255],
                    [0, 255, 0, 255],
                    [0, 0, 255, 255],
                ],
                dtype=np.uint8,
            ),
            (4, 1),
        )
        second_colours = np.tile(
            np.asarray(
                [
                    [255, 255, 0, 255],
                    [0, 255, 255, 255],
                    [255, 0, 255, 255],
                ],
                dtype=np.uint8,
            ),
            (4, 1),
        )
    texture_rgb = np.asarray([160, 80, 40], dtype=np.uint8)
    texture = _png_bytes(texture_rgb.reshape((1, 1, 3)))
    offsets = [
        _append(binary, positions.tobytes()),
        _append(binary, uv.tobytes()),
        _append(binary, first_colours.tobytes()),
        _append(binary, second_colours.tobytes()),
        _append(binary, texture),
    ]
    document = _base_document()
    document["asset"] = {
        "version": "2.0",
        "generator": "THREE.GLTFExporter r178",
    }
    document["scenes"] = [{"nodes": [0]}]
    document["nodes"] = [
        {
            "name": "world",
            "extras": {"name": "world"},
            "children": [1, 2],
        },
        {"name": "first", "mesh": 0},
        {"name": "second", "mesh": 1},
    ]
    if exploded_provenance:
        for node, direction in zip(
            document["nodes"][1:],
            ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)),
            strict=True,
        ):
            node["extras"] = {
                "name": node["name"],
                "_explodeOrigLocalPos": {
                    "x": 0.0,
                    "y": 0.0,
                    "z": 0.0,
                },
                "_explodeWorldDir": dict(
                    zip(("x", "y", "z"), direction, strict=True)
                ),
            }
    document["bufferViews"] = [
        {"buffer": 0, "byteOffset": offset, "byteLength": length}
        for offset, length in offsets
    ]
    document["accessors"] = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC3",
        },
        {
            "bufferView": 1,
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC2",
        },
        {
            "bufferView": 2,
            "componentType": 5121,
            "normalized": True,
            "count": len(positions),
            "type": "VEC4",
        },
        {
            "bufferView": 3,
            "componentType": 5121,
            "normalized": True,
            "count": len(positions),
            "type": "VEC4",
        },
    ]
    document["images"] = [{"bufferView": 4, "mimeType": "image/png"}]
    document["textures"] = (
        [{"source": 0}]
        if shared_texture
        else [{"source": 0}, {"source": 0}]
    )
    document["materials"] = [
        {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
        {
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0 if shared_texture else 1}
            }
        },
    ]
    document["meshes"] = [
        {
            "primitives": [
                {
                    "attributes": {
                        "POSITION": 0,
                        "TEXCOORD_0": 1,
                        "COLOR_0": colour_accessor,
                    },
                    "material": material_id,
                }
            ]
        }
        for colour_accessor, material_id in ((2, 0), (3, 1))
    ]
    return document, bytes(binary), texture_rgb


class GltfImportTests(unittest.TestCase):
    def test_json_preflight_counts_instanced_triangle_modes_without_bin(self) -> None:
        document = _base_document()
        document["scenes"] = [{"nodes": [0, 1]}]
        document["nodes"] = [{"mesh": 0}, {"mesh": 0}]
        document["accessors"] = [
            {"componentType": 5126, "count": 3, "type": "VEC3"},
            {"componentType": 5125, "count": 6, "type": "SCALAR"},
            {"componentType": 5126, "count": 4, "type": "VEC3"},
            {"componentType": 5125, "count": 5, "type": "SCALAR"},
            {"componentType": 5126, "count": 5, "type": "VEC3"},
            {"componentType": 5125, "count": 6, "type": "SCALAR"},
        ]
        document["meshes"] = [
            {
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "mode": 4},
                    {"attributes": {"POSITION": 2}, "indices": 3, "mode": 5},
                    {"attributes": {"POSITION": 4}, "indices": 5, "mode": 6},
                ]
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, b"")
            plan = inspect_gltf_asset(path)

        self.assertEqual(plan.vertex_count_upper_bound, 24)
        self.assertEqual(plan.triangle_count, 18)
        self.assertEqual(plan.mesh_node_count, 2)
        self.assertEqual(plan.primitive_instance_count, 6)
        self.assertEqual(plan.primitive_modes, (4, 5, 6, 4, 5, 6))
        self.assertFalse(plan.requires_reduced_mode)

    def test_large_scene_rejects_before_bin_or_texture_decode(self) -> None:
        document = _base_document()
        document["accessors"] = [
            {
                "componentType": 5126,
                "count": 1_500_000,
                "type": "VEC3",
            },
            {
                "componentType": 5125,
                "count": 12_000_003,
                "type": "SCALAR",
            },
        ]
        document["meshes"] = [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "mode": 4,
                    }
                ]
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, b"")
            plan = inspect_gltf_asset(path)
            self.assertEqual(plan.triangle_count, 4_000_001)
            self.assertTrue(plan.requires_reduced_mode)
            self.assertTrue(plan.supports_reduced_mode)
            with (
                patch(
                    "spectrum_mapper.gltf_import._read_document",
                    side_effect=AssertionError("BIN reader must not run"),
                ),
                self.assertRaisesRegex(GltfImportError, "大規模モデル"),
            ):
                load_gltf_asset(path)

    def test_reduced_admission_is_inclusive_at_five_million_faces(self) -> None:
        document = _base_document()
        document["accessors"] = [
            {
                "componentType": 5126,
                "count": 2_500_000,
                "type": "VEC3",
            },
            {
                "componentType": 5125,
                "count": 15_000_000,
                "type": "SCALAR",
            },
        ]
        document["meshes"] = [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "mode": 4,
                    }
                ]
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, b"")
            plan = inspect_gltf_asset(path)
        self.assertEqual(plan.triangle_count, 5_000_000)
        self.assertTrue(plan.requires_reduced_mode)
        self.assertTrue(plan.supports_reduced_mode)

        document["accessors"][1]["count"] = 15_000_003
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, b"")
            above = inspect_gltf_asset(path)
        self.assertEqual(above.triangle_count, 5_000_001)
        self.assertFalse(above.supports_reduced_mode)

    def test_chunked_texture_sampling_matches_single_chunk(self) -> None:
        image = np.asarray(
            [
                [[0, 32, 64, 255], [96, 128, 160, 128]],
                [[192, 224, 255, 64], [17, 51, 85, 0]],
            ],
            dtype=np.uint8,
        )
        uv = np.asarray(
            [
                [-0.25, 0.2],
                [0.1, 0.9],
                [0.5, 0.5],
                [1.1, -0.2],
                [2.4, 1.8],
            ],
            dtype=np.float64,
        )
        expected_rgb, expected_alpha = _sample_image_linear_chunk(
            image, uv, 10497, 33648, False
        )
        with patch(
            "spectrum_mapper.gltf_import._TEXTURE_SAMPLE_CHUNK_VERTICES", 2
        ):
            actual_rgb, actual_alpha = _sample_image_linear(
                image, uv, 10497, 33648, False
            )
        np.testing.assert_array_equal(actual_rgb, expected_rgb)
        np.testing.assert_array_equal(actual_alpha, expected_alpha)

    def test_explicit_reduced_admission_loads_and_records_hard_ceiling(self) -> None:
        document, binary, _texture_rgb = _multipart_colour_document(
            categorical=False
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, binary)
            plan = inspect_gltf_asset(path)
            self.assertGreater(plan.triangle_count, 1)
            mismatched_plan = GltfImportPlan(
                plan.vertex_count_upper_bound,
                plan.triangle_count + 1,
                plan.mesh_node_count,
                plan.primitive_instance_count,
                plan.primitive_modes,
            )
            with self.assertRaisesRegex(GltfImportError, "changed after"):
                load_gltf_asset(path, expected_plan=mismatched_plan)
            with (
                patch(
                    "spectrum_mapper.gltf_import._MAX_IMPORTED_FACES",
                    plan.triangle_count - 1,
                ),
                patch(
                    "spectrum_mapper.gltf_import._MAX_REDUCED_SOURCE_FACES",
                    plan.triangle_count,
                ),
            ):
                with self.assertRaisesRegex(GltfImportError, "大規模モデル"):
                    load_gltf_asset(path)
                asset = load_gltf_asset(
                    path,
                    allow_large_reduced_source=True,
                    expected_plan=plan,
                )
                expected_source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest().upper()

        self.assertEqual(asset.faces.dtype, np.int32)
        self.assertEqual(asset.sha256, expected_source_sha256)
        self.assertIs(
            asset.import_metadata["large_source_reduction_required"], True
        )
        self.assertEqual(
            asset.import_metadata["source_triangle_workload"],
            plan.triangle_count,
        )
        self.assertEqual(asset.import_metadata["maximum_final_faces"], 450_000)

    def test_auto_omits_segmentation_ids_and_policy_overrides_are_explicit(self) -> None:
        document, binary, texture_rgb = _multipart_colour_document(
            categorical=True
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, binary)
            automatic = load_gltf_asset(path)
            multiplied = load_gltf_asset(path, vertex_color_policy="multiply")
            ignored = load_gltf_asset(path, vertex_color_policy="ignore")

        expected_texture = np.broadcast_to(
            texture_rgb.astype(np.float64) / 255.0, automatic.colors.shape
        )
        np.testing.assert_allclose(automatic.colors, expected_texture, atol=2e-5)
        np.testing.assert_allclose(ignored.colors, automatic.colors, atol=2e-5)
        self.assertGreater(
            float(np.max(np.abs(multiplied.colors - automatic.colors))), 0.1
        )
        automatic_decision = next(
            warning
            for warning in automatic.warnings
            if "COLOR_0自動判定" in warning
        )
        self.assertIn("(index 0)", automatic_decision)
        self.assertIn("2 個", automatic_decision)
        self.assertIn("vertex_color_policy='multiply'", automatic_decision)
        self.assertFalse(
            any("glTF規格どおり線形色で合成" in warning for warning in automatic.warnings)
        )
        self.assertTrue(
            any("glTF規格どおり線形色で合成" in warning for warning in multiplied.warnings)
        )
        self.assertTrue(
            any("vertex_color_policy='ignore'" in warning for warning in ignored.warnings)
        )
        self.assertEqual(
            automatic.import_metadata["schema"],
            "obj-adjuster.gltf-import.v1",
        )
        self.assertIs(
            automatic.import_metadata["compatible_exploded_multipart"], True
        )
        self.assertIs(
            automatic.import_metadata["categorical_part_ids_detected"], True
        )
        self.assertIs(
            automatic.import_metadata["segmentation_vertex_colors_suppressed"],
            True,
        )

    def test_auto_preserves_standard_colours_outside_narrow_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, categorical, shared_texture, dominant_count in (
                ("varied", False, True, 11),
                ("separate-textures", True, False, 11),
                ("below-threshold", True, True, 10),
                ("uniform-tint", True, True, 12),
            ):
                with self.subTest(name=name):
                    document, binary, texture_rgb = _multipart_colour_document(
                        categorical=categorical,
                        shared_texture=shared_texture,
                        dominant_count=dominant_count,
                    )
                    path = root / f"{name}.glb"
                    path.write_bytes(_glb_bytes(document, binary))
                    automatic = load_gltf_asset(path)
                    multiplied = load_gltf_asset(
                        path, vertex_color_policy="multiply"
                    )
                    np.testing.assert_allclose(
                        automatic.colors, multiplied.colors, atol=2e-5
                    )
                    self.assertFalse(
                        any(
                            "COLOR_0自動判定" in warning
                            for warning in automatic.warnings
                        )
                    )
                    texture_only = np.broadcast_to(
                        texture_rgb.astype(np.float64) / 255.0,
                        automatic.colors.shape,
                    )
                    self.assertGreater(
                        float(np.max(np.abs(automatic.colors - texture_only))), 0.1
                    )

    def test_auto_preserves_authored_part_tints_without_exporter_provenance(self) -> None:
        document, binary, _texture_rgb = _multipart_colour_document(
            categorical=True,
            exploded_provenance=False,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, binary)
            automatic = load_gltf_asset(path)
            multiplied = load_gltf_asset(path, vertex_color_policy="multiply")
            ignored = load_gltf_asset(path, vertex_color_policy="ignore")

        np.testing.assert_allclose(automatic.colors, multiplied.colors, atol=2e-5)
        self.assertGreater(
            float(np.max(np.abs(automatic.colors - ignored.colors))), 0.1
        )
        self.assertFalse(
            any("COLOR_0自動判定" in warning for warning in automatic.warnings)
        )
        self.assertIs(
            automatic.import_metadata["compatible_exploded_multipart"], False
        )
        self.assertIs(
            automatic.import_metadata["categorical_part_ids_detected"], False
        )

    def test_auto_preserves_authored_tints_with_same_exporter_provenance(self) -> None:
        document, binary, _texture_rgb = _multipart_colour_document(
            categorical=True,
            known_segmentation_palette=False,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, binary)
            automatic = load_gltf_asset(path)
            multiplied = load_gltf_asset(path, vertex_color_policy="multiply")
            ignored = load_gltf_asset(path, vertex_color_policy="ignore")

        np.testing.assert_allclose(automatic.colors, multiplied.colors, atol=2e-5)
        self.assertGreater(
            float(np.max(np.abs(automatic.colors - ignored.colors))), 0.1
        )
        self.assertFalse(
            any("COLOR_0自動判定" in warning for warning in automatic.warnings)
        )
        self.assertIs(
            automatic.import_metadata["compatible_exploded_multipart"], True
        )
        self.assertIs(
            automatic.import_metadata["categorical_part_ids_detected"], False
        )

    def test_auto_requires_segmentation_ids_on_every_selected_primitive(self) -> None:
        document, binary, _texture_rgb = _multipart_colour_document(
            categorical=True
        )
        second = document["meshes"][1]["primitives"][0]["attributes"]
        del second["COLOR_0"]
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, binary)
            automatic = load_gltf_asset(path)
            multiplied = load_gltf_asset(path, vertex_color_policy="multiply")

        np.testing.assert_allclose(automatic.colors, multiplied.colors, atol=2e-5)
        self.assertFalse(
            any("COLOR_0自動判定" in warning for warning in automatic.warnings)
        )

    def test_invalid_vertex_colour_policy_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "vertex_color_policy"):
            load_gltf_asset(
                Path("unused.glb"), vertex_color_policy="guess"  # type: ignore[arg-type]
            )

    def test_sparse_normalized_colour_stride_transforms_and_stable_parts(self) -> None:
        binary = bytearray()
        positions = b"".join(
            struct.pack("<3fI", *position, 0xAABBCCDD)
            for position in ((0, 0, 0), (1, 0, 0), (0, 1, 0))
        )
        position_offset, position_length = _append(binary, positions)
        sparse_index_offset, sparse_index_length = _append(binary, bytes([0, 1, 2]))
        sparse_value_offset, sparse_value_length = _append(
            binary,
            bytes([255, 0, 0, 0, 255, 0, 0, 0, 255]),
        )
        face_offset, face_length = _append(
            binary, np.asarray([0, 1, 2], dtype="<u2").tobytes()
        )
        document = _base_document()
        document["scenes"] = [{"nodes": [0, 1]}]
        document["nodes"] = [
            {"name": "Robot", "mesh": 0, "translation": [1, 2, 3]},
            {"name": "Robot", "mesh": 0, "scale": [-1, 1, 1]},
        ]
        document["bufferViews"] = [
            {
                "buffer": 0,
                "byteOffset": position_offset,
                "byteLength": position_length,
                "byteStride": 16,
            },
            {
                "buffer": 0,
                "byteOffset": sparse_index_offset,
                "byteLength": sparse_index_length,
            },
            {
                "buffer": 0,
                "byteOffset": sparse_value_offset,
                "byteLength": sparse_value_length,
            },
            {
                "buffer": 0,
                "byteOffset": face_offset,
                "byteLength": face_length,
            },
        ]
        document["accessors"] = [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
            },
            {
                "componentType": 5121,
                "normalized": True,
                "count": 3,
                "type": "VEC3",
                "sparse": {
                    "count": 3,
                    "indices": {"bufferView": 1, "componentType": 5121},
                    "values": {"bufferView": 2},
                },
            },
            {
                "bufferView": 3,
                "componentType": 5123,
                "count": 3,
                "type": "SCALAR",
            },
        ]
        document["meshes"] = [
            {
                "name": "Mesh",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "COLOR_0": 1},
                        "indices": 2,
                    }
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_glb(Path(temporary), document, bytes(binary))
            first = load_gltf_asset(path)
            second = load_gltf_asset(path)

        self.assertEqual(first.part_names, ("Robot", "Robot (2)"))
        self.assertEqual(first.part_names, second.part_names)
        self.assertEqual(first.part_keys, second.part_keys)
        self.assertEqual(first.part_face_counts, (1, 1))
        self.assertEqual(first.part_vertex_counts, (3, 3))
        self.assertTrue(first.has_explicit_parts)
        np.testing.assert_array_equal(first.faces, [[0, 1, 2], [3, 5, 4]])
        np.testing.assert_allclose(first.vertices[0], [1, 2, 3], atol=1e-7)
        np.testing.assert_allclose(first.vertices[3:6, 0], [0, -1, 0], atol=1e-7)
        np.testing.assert_allclose(
            first.colors[:3], np.eye(3, dtype=np.float32), atol=1e-6
        )

    def test_base_colour_texture_top_left_factor_and_lazy_pbr_map(self) -> None:
        binary = bytearray()
        positions = np.asarray(
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype="<f4"
        )
        uv = np.asarray(
            [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]],
            dtype="<f4",
        )
        indices = np.asarray([0, 1, 2, 0, 2, 3], dtype="<u2")
        texture = _png_bytes(
            np.asarray(
                [
                    [[255, 0, 0], [0, 255, 0]],
                    [[0, 0, 255], [255, 255, 255]],
                ],
                dtype=np.uint8,
            )
        )
        offsets = [
            _append(binary, positions.tobytes()),
            _append(binary, uv.tobytes()),
            _append(binary, indices.tobytes()),
            _append(binary, texture),
        ]
        document = _base_document()
        document["bufferViews"] = [
            {"buffer": 0, "byteOffset": offset, "byteLength": length}
            for offset, length in offsets
        ]
        document["accessors"] = [
            {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 4, "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": 6, "type": "SCALAR"},
        ]
        document["images"] = [
            {"bufferView": 3, "mimeType": "image/png"},
            # The ignored PBR map is deliberately invalid. A lazy importer
            # must not decode it while baking printable baseColor.
            {"bufferView": 2, "mimeType": "image/png"},
        ]
        document["samplers"] = [
            {"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}
        ]
        document["textures"] = [
            {"source": 0, "sampler": 0},
            {"source": 1, "sampler": 0},
        ]
        document["materials"] = [
            {
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.5, 1, 1, 1],
                    "baseColorTexture": {"index": 0},
                    "metallicRoughnessTexture": {"index": 1},
                }
            }
        ]
        document["meshes"] = [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                        "indices": 2,
                        "material": 0,
                    }
                ]
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            asset = load_gltf_asset(
                _write_glb(Path(temporary), document, bytes(binary))
            )

        half_linear_srgb = 1.055 * (0.5 ** (1 / 2.4)) - 0.055
        expected = np.asarray(
            [
                [half_linear_srgb, 0, 0],
                [0, 1, 0],
                [half_linear_srgb, 1, 1],
                [0, 0, 1],
            ]
        )
        np.testing.assert_allclose(asset.colors, expected, atol=2e-5)
        self.assertTrue(any("sRGB頂点色" in item for item in asset.warnings))
        self.assertTrue(any("metallic-roughness" in item for item in asset.warnings))

    def test_linear_filter_decodes_srgb_before_interpolation(self) -> None:
        binary = bytearray()
        positions = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4")
        uv = np.asarray([[0.5, 0.5]] * 3, dtype="<f4")
        texture = _png_bytes(np.asarray([[[0, 0, 0], [255, 255, 255]]], dtype=np.uint8))
        offsets = [
            _append(binary, positions.tobytes()),
            _append(binary, uv.tobytes()),
            _append(binary, texture),
        ]
        document = _base_document()
        document["bufferViews"] = [
            {"buffer": 0, "byteOffset": offset, "byteLength": length}
            for offset, length in offsets
        ]
        document["accessors"] = [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"},
        ]
        document["images"] = [{"bufferView": 2, "mimeType": "image/png"}]
        document["samplers"] = [{"magFilter": 9729, "wrapS": 33071, "wrapT": 33071}]
        document["textures"] = [{"source": 0, "sampler": 0}]
        document["materials"] = [
            {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
        ]
        document["meshes"] = [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                        "material": 0,
                    }
                ]
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            asset = load_gltf_asset(
                _write_glb(Path(temporary), document, bytes(binary))
            )
        expected = 1.055 * (0.5 ** (1 / 2.4)) - 0.055
        np.testing.assert_allclose(asset.colors, expected, atol=2e-5)
        self.assertGreater(float(asset.colors[0, 0]), 0.7)

    def test_triangle_strip_and_fan_are_grouped_under_one_mesh_node(self) -> None:
        binary = bytearray()
        positions = np.asarray(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype="<f4"
        )
        indices = np.asarray([0, 1, 2, 3], dtype="<u2")
        offsets = [
            _append(binary, positions.tobytes()),
            _append(binary, indices.tobytes()),
        ]
        document = _base_document()
        document["nodes"] = [{"name": "one logical mesh", "mesh": 0}]
        document["bufferViews"] = [
            {"buffer": 0, "byteOffset": offset, "byteLength": length}
            for offset, length in offsets
        ]
        document["accessors"] = [
            {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 4, "type": "SCALAR"},
        ]
        document["meshes"] = [
            {
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "mode": 5},
                    {"attributes": {"POSITION": 0}, "indices": 1, "mode": 6},
                ]
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            asset = load_gltf_asset(
                _write_glb(Path(temporary), document, bytes(binary))
            )
        self.assertEqual(asset.part_names, ("one logical mesh",))
        self.assertEqual(asset.part_face_counts, (4,))
        np.testing.assert_array_equal(
            asset.faces,
            [[0, 1, 2], [2, 1, 3], [4, 5, 6], [4, 6, 7]],
        )

    def test_repeat_mirrored_repeat_and_clamp_wrap_texels(self) -> None:
        image = np.asarray([[[255, 0, 0], [0, 255, 0]]], dtype=np.uint8)
        uv = np.asarray([[1.25, 0.5], [-0.25, 0.5]], dtype=np.float64)
        repeat, _alpha = _sample_image_linear(image, uv, 10497, 10497, True)
        mirrored, _alpha = _sample_image_linear(image, uv, 33648, 10497, True)
        clamped, _alpha = _sample_image_linear(image, uv, 33071, 33071, True)
        np.testing.assert_allclose(repeat, [[1, 0, 0], [0, 1, 0]], atol=1e-12)
        np.testing.assert_allclose(mirrored, [[0, 1, 0], [1, 0, 0]], atol=1e-12)
        np.testing.assert_allclose(clamped, [[0, 1, 0], [1, 0, 0]], atol=1e-12)

    def test_embedded_gltf_data_uri_and_engine_dispatch(self) -> None:
        positions = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4")
        document = _base_document()
        document["buffers"] = [
            {
                "byteLength": positions.nbytes,
                "uri": "data:application/octet-stream;base64,"
                + base64.b64encode(positions.tobytes()).decode("ascii"),
            }
        ]
        document["bufferViews"] = [
            {"buffer": 0, "byteOffset": 0, "byteLength": positions.nbytes}
        ]
        document["accessors"] = [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}
        ]
        document["meshes"] = [{"primitives": [{"attributes": {"POSITION": 0}}]}]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "embedded.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")
            asset = load_gltf_asset(path)
        self.assertEqual(len(asset.faces), 1)
        np.testing.assert_allclose(asset.colors, 1.0)

    def test_external_uri_duplicate_key_and_unsupported_static_features_fail_closed(self) -> None:
        positions = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4")
        basic = _base_document()
        basic["bufferViews"] = [
            {"buffer": 0, "byteOffset": 0, "byteLength": positions.nbytes}
        ]
        basic["accessors"] = [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}
        ]
        basic["meshes"] = [{"primitives": [{"attributes": {"POSITION": 0}}]}]
        cases: list[tuple[str, dict[str, object], str]] = []
        external = json.loads(json.dumps(basic))
        external["buffers"] = [{"byteLength": positions.nbytes, "uri": "model.bin"}]
        cases.append(("external", external, "external URI"))
        external_image = json.loads(json.dumps(basic))
        external_image["images"] = [{"uri": "texture.png"}]
        cases.append(("external-image", external_image, "external URI"))
        animated = json.loads(json.dumps(basic))
        animated["animations"] = [{"channels": [], "samplers": []}]
        cases.append(("animation", animated, "Animated"))
        skinned = json.loads(json.dumps(basic))
        skinned["skins"] = [{}]
        cases.append(("skin", skinned, "Skinned"))
        draco = json.loads(json.dumps(basic))
        draco["meshes"][0]["primitives"][0]["extensions"] = {
            "KHR_draco_mesh_compression": {"bufferView": 0, "attributes": {}}
        }
        cases.append(("draco", draco, "Draco"))
        instanced = json.loads(json.dumps(basic))
        instanced["nodes"][0]["extensions"] = {
            "EXT_mesh_gpu_instancing": {"attributes": {}}
        }
        cases.append(("instancing", instanced, "instancing"))
        newer = json.loads(json.dumps(basic))
        newer["asset"]["minVersion"] = "2.1"
        cases.append(("newer-min-version", newer, "newer implementation"))
        world_overflow = json.loads(json.dumps(basic))
        world_overflow["scenes"] = [{"nodes": [0]}]
        world_overflow["nodes"] = [
            {"translation": [1e308, 0, 0], "children": [1]},
            {"translation": [1e308, 0, 0], "mesh": 0},
        ]
        cases.append(("world-overflow", world_overflow, "world transform"))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, document, expected in cases:
                with self.subTest(name=name):
                    path = root / f"{name}.glb"
                    path.write_bytes(_glb_bytes(document, positions.tobytes()))
                    with self.assertRaisesRegex(GltfImportError, expected):
                        load_gltf_asset(path)
            duplicate = root / "duplicate.gltf"
            duplicate.write_text(
                '{"asset":{"version":"2.0","version":"2.0"}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GltfImportError, "duplicate key"):
                load_gltf_asset(duplicate)
            deeply_nested = root / "deep.gltf"
            deeply_nested.write_text("[" * 10_000 + "]" * 10_000, encoding="utf-8")
            with self.assertRaisesRegex(GltfImportError, "nesting is too deep"):
                load_gltf_asset(deeply_nested)

    def test_image_mime_mismatch_fails_closed(self) -> None:
        binary = bytearray()
        positions = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4")
        uv = np.asarray([[0.5, 0.5]] * 3, dtype="<f4")
        png = _png_bytes(np.asarray([[[255, 0, 0]]], dtype=np.uint8))
        offsets = [
            _append(binary, positions.tobytes()),
            _append(binary, uv.tobytes()),
            _append(binary, png),
        ]
        document = _base_document()
        document["bufferViews"] = [
            {"buffer": 0, "byteOffset": offset, "byteLength": length}
            for offset, length in offsets
        ]
        document["accessors"] = [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"},
        ]
        document["images"] = [{"bufferView": 2, "mimeType": "image/jpeg"}]
        document["textures"] = [{"source": 0}]
        document["materials"] = [
            {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
        ]
        document["meshes"] = [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                        "material": 0,
                    }
                ]
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(GltfImportError, "declared.*contains"):
                load_gltf_asset(
                    _write_glb(Path(temporary), document, bytes(binary))
                )

            document["images"][0]["mimeType"] = "image/png"
            document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {
                "index": 0,
                "extensions": {
                    "KHR_texture_transform": {
                        "offset": [1.7e308, 0],
                        "scale": [1.7e308, 1],
                    }
                },
            }
            with self.assertRaisesRegex(GltfImportError, "coordinates overflow"):
                load_gltf_asset(
                    _write_glb(Path(temporary), document, bytes(binary))
                )

    def test_dispatch_wraps_import_error_for_application(self) -> None:
        from spectrum_mapper.engine import EngineError, load_vertex_color_model

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.glb"
            path.write_bytes(b"not glb")
            with self.assertRaisesRegex(EngineError, "GLB/glTFを読み込めません"):
                load_vertex_color_model(path)


if __name__ == "__main__":
    unittest.main()
