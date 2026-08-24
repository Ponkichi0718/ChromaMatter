from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from pathlib import Path

from . import APP_DISPLAY_NAME, APP_NAME, __version__


def _progress(phase: str, fraction: float, message: str) -> None:
    print(f"[{fraction * 100:5.1f}%] {phase}: {message}", flush=True)


def _is_frozen_public_build() -> bool:
    """Return whether this process is the public PyInstaller application."""

    return bool(
        getattr(sys, "frozen", False)
        and getattr(sys, "_MEIPASS", None)
    )


def _decal_runtime_smoke() -> dict[str, object]:
    """Check the public PNG path and the source-only SVG renderer contract."""

    import io
    import importlib.metadata

    import numpy as np
    import PIL.Image

    from .decal_image import load_decal_bytes

    frozen_public_build = _is_frozen_public_build()
    png_ok = False
    png_status = "not-run"
    try:
        png_stream = io.BytesIO()
        PIL.Image.new("RGBA", (3, 2), (240, 32, 48, 128)).save(
            png_stream,
            format="PNG",
        )
        png_decal = load_decal_bytes(
            png_stream.getvalue(),
            filename="packaged-self-test.png",
        )
        png_ok = bool(
            png_decal.source_format == "PNG"
            and png_decal.rgba.shape == (2, 3, 4)
            and int(png_decal.rgba[0, 0, 3]) == 128
        )
        png_status = "ok" if png_ok else "invalid output"
    except Exception as exc:
        png_status = f"error: {type(exc).__name__}: {exc}"

    if frozen_public_build:
        # Decal beta is intentionally inaccessible in public r32.  Its SVG
        # renderer and compiled Rust dependency graph therefore are not part
        # of the public executable.  Keep this an explicit non-applicable
        # result rather than presenting it as a failed feature check.
        svg_ok: bool | None = None
        svg_status = "not-packaged"
        svg_required = False
        resvg_status = "not-packaged"
    else:
        # Source/developer runs retain the complete Decal implementation and
        # must continue to prove the pinned resvg-backed SVG path.
        svg_ok = False
        svg_status = "not-run"
        svg_required = True
        resvg_status = "unavailable"
        try:
            resvg_status = importlib.metadata.version("resvg")
            svg_decal = load_decal_bytes(
                (
                    b'<svg xmlns="http://www.w3.org/2000/svg" width="4" '
                    b'height="3" viewBox="0 0 4 3"><path d="M0 0H4V3H0Z" '
                    b'fill="#2468ac" fill-opacity="0.5"/></svg>'
                ),
                filename="packaged-self-test.svg",
            )
            svg_ok = bool(
                svg_decal.source_format == "SVG"
                and svg_decal.rgba.shape == (3, 4, 4)
                and bool(np.any(svg_decal.rgba[:, :, 3] > 0))
                and bool(np.any(svg_decal.rgba[:, :, 3] < 255))
            )
            svg_status = "ok" if svg_ok else "invalid output"
        except Exception as exc:
            svg_status = f"error: {type(exc).__name__}: {exc}"

    loader_ok = bool(png_ok and (not svg_required or svg_ok))
    if loader_ok and frozen_public_build:
        loader_status = "ok; SVG/resvg not-packaged"
    elif loader_ok:
        loader_status = "ok"
    else:
        loader_status = f"PNG: {png_status}; SVG: {svg_status}"
    return {
        "resvg": resvg_status,
        "decal_png_smoke": png_ok,
        "decal_png_status": png_status,
        "decal_svg_smoke": svg_ok,
        "decal_svg_status": svg_status,
        "decal_svg_required": svg_required,
        "decal_loader_status": loader_status,
        "ok": loader_ok,
    }


def _glb_import_smoke() -> tuple[bool, str]:
    """Exercise the frozen GLB parser and embedded PNG colour-baking path."""

    import io
    import struct

    import numpy as np
    from PIL import Image

    from .engine import load_vertex_color_model

    def aligned(data: bytes, fill: bytes = b"\0") -> bytes:
        return data + fill * ((-len(data)) % 4)

    try:
        png_stream = io.BytesIO()
        Image.fromarray(
            np.asarray(
                [
                    [[255, 0, 0], [0, 255, 0]],
                    [[0, 0, 255], [255, 255, 0]],
                ],
                dtype=np.uint8,
            ),
            mode="RGB",
        ).save(png_stream, format="PNG")
        png = png_stream.getvalue()

        positions = np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype="<f4",
        ).tobytes()
        texcoords = np.asarray(
            [[0.25, 0.25], [0.75, 0.25], [0.25, 0.75]],
            dtype="<f4",
        ).tobytes()
        indices = np.asarray([0, 1, 2], dtype="<u2").tobytes()

        binary = bytearray()

        def append_view(payload: bytes) -> tuple[int, int]:
            while len(binary) % 4:
                binary.append(0)
            offset = len(binary)
            binary.extend(payload)
            return offset, len(payload)

        position_offset, position_length = append_view(positions)
        texcoord_offset, texcoord_length = append_view(texcoords)
        index_offset, index_length = append_view(indices)
        image_offset, image_length = append_view(png)
        declared_binary_length = len(binary)
        binary_chunk = aligned(bytes(binary))

        document = {
            "asset": {"version": "2.0", "generator": "ChromaMatter self-test"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"name": "textured triangle", "mesh": 0}],
            "meshes": [
                {
                    "primitives": [
                        {
                            "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                            "indices": 2,
                            "material": 0,
                        }
                    ]
                }
            ],
            "buffers": [{"byteLength": declared_binary_length}],
            "bufferViews": [
                {
                    "buffer": 0,
                    "byteOffset": position_offset,
                    "byteLength": position_length,
                    "target": 34962,
                },
                {
                    "buffer": 0,
                    "byteOffset": texcoord_offset,
                    "byteLength": texcoord_length,
                    "target": 34962,
                },
                {
                    "buffer": 0,
                    "byteOffset": index_offset,
                    "byteLength": index_length,
                    "target": 34963,
                },
                {
                    "buffer": 0,
                    "byteOffset": image_offset,
                    "byteLength": image_length,
                },
            ],
            "accessors": [
                {
                    "bufferView": 0,
                    "componentType": 5126,
                    "count": 3,
                    "type": "VEC3",
                    "min": [0.0, 0.0, 0.0],
                    "max": [1.0, 1.0, 0.0],
                },
                {
                    "bufferView": 1,
                    "componentType": 5126,
                    "count": 3,
                    "type": "VEC2",
                },
                {
                    "bufferView": 2,
                    "componentType": 5123,
                    "count": 3,
                    "type": "SCALAR",
                },
            ],
            "images": [{"bufferView": 3, "mimeType": "image/png"}],
            "samplers": [
                {
                    "magFilter": 9728,
                    "minFilter": 9728,
                    "wrapS": 33071,
                    "wrapT": 33071,
                }
            ],
            "textures": [{"sampler": 0, "source": 0}],
            "materials": [
                {
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                        "baseColorTexture": {"index": 0},
                    }
                }
            ],
        }
        json_chunk = aligned(
            json.dumps(document, separators=(",", ":")).encode("utf-8"),
            b" ",
        )
        total_length = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
        glb = b"".join(
            (
                struct.pack("<4sII", b"glTF", 2, total_length),
                struct.pack("<II", len(json_chunk), 0x4E4F534A),
                json_chunk,
                struct.pack("<II", len(binary_chunk), 0x004E4942),
                binary_chunk,
            )
        )
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory) / "packaged-texture-self-test.glb"
            path.write_bytes(glb)
            asset = load_vertex_color_model(path)
        expected = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        ok = bool(
            len(asset.vertices) == 3
            and len(asset.faces) == 1
            and asset.part_names == ("textured triangle",)
            and np.allclose(asset.colors, expected, rtol=0.0, atol=1.0 / 255.0)
        )
        return (
            ok,
            "ok"
            if ok
            else (
                "imported geometry or baked colours differ: "
                f"vertices={len(asset.vertices)}, faces={len(asset.faces)}, "
                f"parts={asset.part_names!r}, colours={asset.colors.tolist()!r}, "
                f"warnings={asset.warnings!r}"
            ),
        )
    except Exception as exc:
        return False, f"error: {type(exc).__name__}: {exc}"


def _radial_export_smoke() -> tuple[bool, str]:
    """Exercise the frozen radial native path through archive revalidation."""

    import numpy as np
    import trimesh

    from .radial_export import (
        package_from_radial_shell,
        validate_radial_3mf,
        write_radial_3mf_atomic,
    )
    from .radial_shell import build_radial_shell

    try:
        mesh = trimesh.creation.box(extents=(6.0, 6.0, 6.0))
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int32)
        shell = build_radial_shell(
            vertices,
            faces,
            face_state_ids=np.full(len(faces), 4, dtype=np.int16),
            eligible_state_partners={4: 2},
            black_extruder=1,
            skin_thickness_mm=0.15,
        )
        physical = ("#111111", "#F0F0F0", "#FF3030", "#B07030")
        package = package_from_radial_shell(shell, physical)
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory) / "radial-self-test.3mf"
            written = write_radial_3mf_atomic(
                path,
                package,
                title="Packaged radial self-test [SLICE ONLY]",
            )
            reopened = validate_radial_3mf(
                path,
                expected_parts=2,
                expected_physical=physical,
                expected_extruders=(1, 2),
            )
            ok = bool(
                path.is_file()
                and written.static_validation_ok
                and reopened.static_validation_ok
                and reopened.zip_crc_ok
                and reopened.parts == 2
                and reopened.physical_extruders == (1, 2)
                and reopened.slice_only
                and not reopened.print_allowed
                and reopened.physical_materials_only
            )
        return ok, "ok" if ok else "archive validation returned false"
    except Exception as exc:
        return False, f"error: {type(exc).__name__}: {exc}"


def _color_depth_export_smoke() -> tuple[bool, str]:
    """Exercise r21's exact physical-depth path through archive reopen.

    This deliberately starts from one small labelled source cube instead of
    manufacturing already-separated material boxes.  The release self-test
    therefore covers the frozen TetGen exact-partition provider, canonical
    shared material manifold extraction, physical-only writer, and independent
    archive reopen validation in one inexpensive path.
    """

    import numpy as np
    import trimesh

    from .color_depth_exact_partition import (
        COLOR_DEPTH_EXACT_PARTITION_SCHEMA,
        build_conforming_color_depth_partition,
    )
    from .color_depth_head_geometry import (
        ColorDepthSourceSurface,
        build_color_depth_result_from_partition,
    )
    from .color_depth_recipes import build_uncalibrated_common_skin_recipes
    from .models import PaletteSettings
    from .radial_export import (
        package_from_color_depth,
        validate_radial_3mf,
        write_radial_3mf_atomic,
    )

    try:
        physical = ("#111111", "#F5F5F5", "#E32636", "#7A4A32")
        palette = PaletteSettings(
            palette_state_count=16,
            physical_hex=list(physical),
        )
        plan = build_uncalibrated_common_skin_recipes(
            palette,
            # Both labels describe the legacy F1/F2 pair.  Their percentages
            # intentionally collapse to one ColorDepth recipe; only label 4
            # is painted on this smoke cube.
            (4, 10),
            outer_thickness_mm=0.15,
        )
        mesh = trimesh.creation.box(extents=(6.0, 6.0, 6.0))
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int32)
        source = ColorDepthSourceSurface(
            vertices_mm=vertices,
            faces=faces,
            face_target_labels=np.full(len(faces), 4, dtype=np.int32),
            height_mm=6.0,
            source_name="packaged-color-depth-cube",
            source_sha256="0" * 64,
            source_volume_mm3=float(mesh.volume),
            metadata={"legacy_mix_percentages_used": False},
        )
        partition = build_conforming_color_depth_partition(
            source, plan.recipes
        )
        result = build_color_depth_result_from_partition(
            source, plan.recipes, partition
        )
        package = package_from_color_depth(result, physical)
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory) / "color-depth-self-test.3mf"
            written = write_radial_3mf_atomic(
                path,
                package,
                title="Packaged exact ColorDepth self-test [SLICE ONLY]",
            )
            reopened = validate_radial_3mf(
                path,
                expected_parts=2,
                expected_physical=physical,
                expected_extruders=(1, 2),
            )
            ok = bool(
                path.is_file()
                and plan.metadata.get("legacy_mix_percentages_used") is False
                and plan.collapsed_target_groups == ((4, 10),)
                and partition.metadata.get("schema")
                == COLOR_DEPTH_EXACT_PARTITION_SCHEMA
                and partition.threshold_interface_conforming
                and partition.shared_interface_partition_exact
                and partition.metadata.get(
                    "direct_threshold_child_join_verified"
                )
                and partition.metadata.get(
                    "visible_exterior_triangle_sets_exact"
                )
                and result.metadata.get("all_closed_oriented_2_manifold")
                and result.metadata.get("shared_interface_partition_exact")
                and result.metadata.get("external_surface_coverage_exact")
                and len(result.interfaces) == 1
                and tuple(part.extruder for part in result.parts) == (1, 2)
                and written.static_validation_ok
                and reopened.static_validation_ok
                and reopened.zip_crc_ok
                and reopened.parts == 2
                and reopened.physical_extruders == (1, 2)
                and reopened.slice_only
                and not reopened.print_allowed
                and reopened.physical_materials_only
            )
        return ok, "ok" if ok else "archive or recipe validation returned false"
    except Exception as exc:
        return False, f"error: {type(exc).__name__}: {exc}"


def self_test() -> int:
    import importlib.metadata

    import manifold3d
    import mapbox_earcut
    import networkx
    import numpy as np
    import PIL
    import pymeshlab
    import rtree
    import scipy
    import shapely
    import tetgen
    import trimesh

    from .assembly import (
        find_boundary_loops,
        mesh_is_watertight,
        pair_matching_loops,
        split_closed_mesh_with_joint,
        weld_matching_seams,
    )
    from .calibration_chart import (
        build_calibration_chart_mesh,
        generate_palette_calibration_bundle,
        palette_calibration_rows,
    )
    from .mixer import (
        PALETTE_STATE_COUNT,
        black_output_ratio_preset,
        build_palette_rgb,
        find_best_mix_recipes,
    )
    from .models import PaletteSettings
    from .volume_partition import _load_tetwild_wrapper

    tetwild_wrapper = _load_tetwild_wrapper()

    def open_box(z0: float, z1: float, omitted: str):
        vertices = np.asarray(
            [
                [-0.2, -0.15, z0],
                [0.2, -0.15, z0],
                [0.2, 0.15, z0],
                [-0.2, 0.15, z0],
                [-0.2, -0.15, z1],
                [0.2, -0.15, z1],
                [0.2, 0.15, z1],
                [-0.2, 0.15, z1],
            ],
            dtype=np.float64,
        )
        sides = {
            "zmin": ((0, 2, 1), (0, 3, 2)),
            "zmax": ((4, 5, 6), (4, 6, 7)),
            "ymin": ((0, 1, 5), (0, 5, 4)),
            "xmax": ((1, 2, 6), (1, 6, 5)),
            "ymax": ((2, 3, 7), (2, 7, 6)),
            "xmin": ((3, 0, 4), (3, 4, 7)),
        }
        faces = np.asarray(
            [
                face
                for name, pair in sides.items()
                if name != omitted
                for face in pair
            ],
            dtype=np.int32,
        )
        colors = np.column_stack(
            (
                (vertices[:, 0] + 0.2) / 0.4,
                (vertices[:, 1] + 0.15) / 0.3,
                np.full(len(vertices), 0.4),
            )
        )
        return vertices, faces, colors

    first = open_box(-0.2, 0.0, "zmax")
    second = open_box(0.0, 0.2, "zmin")
    loops = [
        *find_boundary_loops(0, first[0], first[1]),
        *find_boundary_loops(1, second[0], second[1]),
    ]
    seams = pair_matching_loops(
        loops, height_mm=100.0, tolerance_mm=0.01
    )
    welded = weld_matching_seams(
        [first, second], seams, height_mm=100.0, tolerance_mm=0.01
    )[:3]
    split_a, split_b, split_record = split_closed_mesh_with_joint(
        welded,
        height_mm=100.0,
        axis="Z",
        position_percent=50.0,
        add_joint=True,
        requested_width_mm=8.0,
        requested_height_mm=5.0,
        depth_mm=4.0,
        clearance_mm=0.25,
        minimum_span_mm=6.0,
    )
    assembly_ok = (
        len(seams) == 1
        and mesh_is_watertight(welded[0], welded[1])
        and mesh_is_watertight(split_a[0], split_a[1])
        and mesh_is_watertight(split_b[0], split_b[1])
        and isinstance(split_record.get("joint"), dict)
    )

    palette_hex, _ = build_palette_rgb(
        ["#111111", "#FFFFFF", "#C0C0C0", "#FFCAE4"]
    )
    recipes = find_best_mix_recipes(
        (210, 205, 210), ["#111111", "#FFFFFF", "#C0C0C0", "#FFCAE4"]
    )
    calibration_palette = PaletteSettings(
        palette_state_count=16,
        output_mix_ratios_b=black_output_ratio_preset(0),
    )
    calibration_rows = palette_calibration_rows(calibration_palette)
    calibration_mesh = build_calibration_chart_mesh(calibration_palette)
    calibration_ok = (
        len(calibration_rows) == 16
        and [int(row["state"]) for row in calibration_rows] == list(range(1, 17))
        and calibration_mesh.state_count == 16
        and len(calibration_mesh.part_names) == 17
        and len(calibration_mesh.faces) == 16 + 12 * 16
        and int(calibration_rows[4]["display_target_b_percent"]) == 33
        and int(calibration_rows[4]["requested_output_b_percent"]) == 80
        and not bool(calibration_rows[4]["surface_shell_applied"])
    )
    calibration_export_ok = False
    calibration_export_status = "not-run"
    try:
        with tempfile.TemporaryDirectory() as raw_directory:
            calibration_result = generate_palette_calibration_bundle(
                Path(raw_directory),
                calibration_palette,
                language="en",
                target_label="packaged self-test",
            )
            adaptive = calibration_result.validation.get(
                "writer_validation", {}
            ).get("r8_export_adaptive", {})
            calibration_export_status = str(adaptive.get("status", ""))
            calibration_export_ok = bool(
                calibration_result.validation.get("valid")
                and calibration_result.model_path.is_file()
                and calibration_export_status == "disabled_calibration"
                and calibration_result.validation.get(
                    "output_mix_ratios_b_percent"
                )
                == calibration_palette.output_mix_ratios_b
                and calibration_result.validation.get("surface_shell_exact")
                and calibration_result.validation.get(
                    "surface_shell_applied_rows"
                )
                == 0
                and calibration_result.validation.get(
                    "writer_validation", {}
                ).get("mixed_definition_cycle_rows")
                == 0
                and not calibration_result.validation.get(
                    "writer_validation", {}
                ).get("unsafe_grouped_cycle_detected")
                and not calibration_result.validation.get(
                    "unknown_or_adaptive_paint_codes"
                )
            )
    except Exception as exc:
        calibration_export_status = f"error: {exc}"
    radial_export_ok, radial_export_status = _radial_export_smoke()
    color_depth_export_ok, color_depth_export_status = (
        _color_depth_export_smoke()
    )
    glb_import_ok, glb_import_status = _glb_import_smoke()
    decal_smoke = _decal_runtime_smoke()
    data = {
        "application": f"{APP_DISPLAY_NAME} {__version__}",
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "pillow": PIL.__version__,
        "resvg": decal_smoke["resvg"],
        "pymeshlab": getattr(pymeshlab, "__version__", "available"),
        "trimesh": trimesh.__version__,
        "manifold3d": importlib.metadata.version("manifold3d"),
        "shapely": shapely.__version__,
        "mapbox_earcut": importlib.metadata.version("mapbox-earcut"),
        "networkx": networkx.__version__,
        "rtree": rtree.__version__,
        "pytetwild": importlib.metadata.version("pytetwild"),
        "pytetwild_wrapper": bool(tetwild_wrapper),
        "tetgen": importlib.metadata.version("tetgen"),
        "palette_states": palette_hex,
        "mix_recipe_count": len(recipes),
        "assembly_smoke": assembly_ok,
        "calibration_chart_smoke": calibration_ok,
        "calibration_chart_export_smoke": calibration_export_ok,
        "calibration_chart_export_status": calibration_export_status,
        "radial_export_smoke": radial_export_ok,
        "radial_export_status": radial_export_status,
        "color_depth_export_smoke": color_depth_export_ok,
        "color_depth_export_status": color_depth_export_status,
        "glb_import_smoke": glb_import_ok,
        "glb_import_status": glb_import_status,
        "decal_png_smoke": decal_smoke["decal_png_smoke"],
        "decal_png_status": decal_smoke["decal_png_status"],
        "decal_svg_smoke": decal_smoke["decal_svg_smoke"],
        "decal_svg_status": decal_smoke["decal_svg_status"],
        "decal_svg_required": decal_smoke["decal_svg_required"],
        "decal_loader_status": decal_smoke["decal_loader_status"],
        "ok": (
            len(palette_hex) == PALETTE_STATE_COUNT
            and len(recipes) >= 1
            and assembly_ok
            and calibration_ok
            and calibration_export_ok
            and radial_export_ok
            and color_depth_export_ok
            and glb_import_ok
            and bool(decal_smoke["ok"])
            and bool(tetwild_wrapper)
            and bool(tetgen)
        ),
    }
    # ``--self-test`` is consumed by release automation and is often launched
    # with redirected stdout on Japanese Windows, where Python may select
    # CP932.  The public product name contains an em dash, so keep this machine
    # interface ASCII-safe instead of depending on the host console encoding.
    print(json.dumps(data, ensure_ascii=True, indent=2))
    return 0 if data["ok"] else 1


def convert(args: argparse.Namespace) -> int:
    from .engine import load_vertex_color_model, prepare_geometry
    from .gltf_import import LARGE_GLTF_REDUCTION_TARGET_FACES
    from .models import AppSettings
    from .workflow import export_bundle

    settings = AppSettings()
    settings.geometry.height_mm = args.height
    settings.geometry.target_faces = args.faces
    settings.geometry.preview_faces = min(args.preview_faces, args.faces)
    settings.geometry.up_axis = args.up_axis
    settings.geometry.mirror_x = args.mirror
    if args.settings:
        settings = AppSettings.from_dict(
            json.loads(Path(args.settings).read_text(encoding="utf-8-sig"))
        )
    settings.geometry.adjust_face_count = True
    # ``--convert`` promises a slicer-ready 3MF and has no interactive Part
    # Processing screen.  Keep GUI imports raw by default, but make the
    # headless conversion path request the same explicit safe solidification
    # that the GUI button performs.
    settings.geometry.solidify_parts = True
    settings.geometry.auto_joints = False
    source = Path(args.obj)
    if source.suffix.lower() not in {".obj", ".glb"}:
        raise SystemExit(
            "--convert の入力形式は頂点カラーOBJまたはGLBを指定してください"
        )
    asset = load_vertex_color_model(
        source,
        _progress,
        allow_large_reduced_source=bool(
            source.suffix.lower() == ".glb"
            and settings.geometry.adjust_face_count
            and settings.geometry.target_faces
            <= LARGE_GLTF_REDUCTION_TARGET_FACES
        ),
    )
    prepared = prepare_geometry(asset, settings.geometry, _progress)
    result = export_bundle(
        prepared,
        settings,
        Path(args.output),
        Path(args.reference) if args.reference else None,
        include_vertex_obj=not args.no_fallback_obj,
        progress=_progress,
    )
    print(f"3MF: {result.model_path}")
    print(f"report: {result.report_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="色付きOBJ / GLBをSnapmaker Full Spectrum用3MFへ変換します。",
    )
    parser.add_argument("--self-test", action="store_true", help="依存関係と混色モデルを確認")
    parser.add_argument("--ui-smoke", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--ui-smoke-language",
        choices=("ja", "en"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--project", metavar="JSON", help="保存済みプロジェクトを開いてGUIを起動")
    parser.add_argument(
        "--convert",
        dest="obj",  # command-line compatibility
        metavar="MODEL",
        help="GUIを使わずOBJ / GLBを変換",
    )
    parser.add_argument("--output", metavar="3MF")
    parser.add_argument("--reference", metavar="IMAGE")
    parser.add_argument("--settings", metavar="JSON")
    parser.add_argument("--height", type=float, default=180.0)
    parser.add_argument("--faces", type=int, default=450_000)
    parser.add_argument("--preview-faces", type=int, default=80_000)
    parser.add_argument("--up-axis", choices=("X", "Y", "Z"), default="Y")
    parser.add_argument("--mirror", action="store_true")
    parser.add_argument("--no-fallback-obj", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.ui_smoke_language is not None and not args.ui_smoke:
        parser.error("--ui-smoke-language requires --ui-smoke")
    if args.self_test:
        return self_test()
    if args.obj:
        if not args.output:
            raise SystemExit("--convert には --output が必要です")
        return convert(args)

    # i18n.load_language() already gives this environment variable highest
    # priority.  Set it only around GUI construction so packaged smoke tests
    # can explicitly exercise both languages without reading or overwriting a
    # user's saved language preference.
    language_variable = "TRIPO_SPECTRUM_LANGUAGE"
    previous_language = os.environ.get(language_variable)
    try:
        if args.ui_smoke_language is not None:
            os.environ[language_variable] = args.ui_smoke_language

        from .gui import launch_app

        return launch_app(
            smoke_test=args.ui_smoke,
            initial_project=Path(args.project) if args.project else None,
        )
    finally:
        if args.ui_smoke_language is not None:
            if previous_language is None:
                os.environ.pop(language_variable, None)
            else:
                os.environ[language_variable] = previous_language


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
