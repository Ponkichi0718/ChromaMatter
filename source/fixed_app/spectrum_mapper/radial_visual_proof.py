"""Independent visual proof set for conventional shades versus radial depth.

This module is deliberately separate from the adaptive ColorDepth partitioner.
It builds two small analytical fixtures:

* a conventional five-band LOOK ONLY reference whose surface preview visibly
  progresses from physical white to physical black; and
* five disjoint box coupons whose physical F2 shell thickness progresses from
  0.10 mm to 0.42 mm around an F1 core.

The radial fixture is not expected to show a five-shade surface preview.  Every
outer surface is F2 by construction.  Its proof is the sliced middle-layer
cross-section, where the five shell thicknesses must be visible around the F1
cores.  Keeping that distinction explicit prevents a physical-volume proof
from being confused with an on-screen colour rendering.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import engine, mixer
from .models import (
    ColorResult,
    GeometrySettings,
    MeshLevel,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
)
from .radial_export import (
    RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
    RadialExportPackage,
    RadialExportPart,
    validate_radial_3mf,
    write_radial_3mf_atomic,
)


SCHEMA = "chromamatter.radial-visual-proof.v1"
GEOMETRY_VERSION = "five-analytical-box-columns-v1"
REFERENCE_FILENAME = "00_REFERENCE_LOOK_ONLY_visible_cel_bands.3mf"
RADIAL_FILENAME = "06_RADIAL_SECTION_5BAND.3mf"
OBJ_IMPORT_FILENAME = "07_ChromaMatter_import_test_head.obj"
OBJ_IMPORT_MTL_FILENAME = "07_ChromaMatter_import_test_head.mtl"
OBJ_IMPORT_COMPARISON_FILENAME = "obj_chromamatter_import_comparison.png"
OBJ_IMPORT_VALIDATION_FILENAME = "obj_import_validation.json"
MAPPING_CSV_FILENAME = "radial_visual_proof_mapping.csv"
MAPPING_PNG_FILENAME = "radial_visual_proof_mapping.png"
README_JA_FILENAME = "README_JA.md"
README_EN_FILENAME = "README_EN.md"
MANIFEST_FILENAME = "SHA256SUMS.txt"
REFERENCE_VALIDATION_FILENAME = "reference_validation.json"
RADIAL_VALIDATION_FILENAME = "radial_validation.json"

PHYSICAL_HEX = ("#121212", "#F5F5F5", "#808080", "#D0D0D0")
PHYSICAL_LABELS = ("F1 Black", "F2 White", "F3 Unused", "F4 Unused")
SHELL_THICKNESSES_MM = (0.10, 0.18, 0.26, 0.34, 0.42)
REFERENCE_STATE_INDICES = (1, 23, 16, 22, 0)
REFERENCE_WHITE_PERCENT = (100, 75, 50, 25, 0)
COLUMN_SIZE_XY_MM = 8.0
COLUMN_HEIGHT_MM = 12.0
COLUMN_GAP_MM = 2.0
INSPECT_Z_MM = 6.0
LAYER_HEIGHT_MM = 0.10
INITIAL_LAYER_HEIGHT_MM = 0.20


class RadialVisualProofError(RuntimeError):
    """Raised when a visual-proof artifact cannot be proven valid."""


@dataclass(frozen=True, slots=True)
class RadialVisualProofBundle:
    folder: Path
    reference_path: Path
    radial_path: Path
    obj_import_path: Path
    obj_import_mtl_path: Path
    obj_import_comparison_path: Path
    obj_import_validation_path: Path
    mapping_csv_path: Path
    mapping_png_path: Path
    readme_ja_path: Path
    readme_en_path: Path
    reference_validation_path: Path
    radial_validation_path: Path
    manifest_path: Path
    reference_validation: Mapping[str, object]
    radial_validation: Mapping[str, object]
    obj_import_validation: Mapping[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    triangles = np.asarray(vertices, dtype=np.float64)[
        np.asarray(faces, dtype=np.int64)
    ]
    return float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )


def _edge_topology(faces: np.ndarray) -> dict[str, object]:
    faces = np.asarray(faces, dtype=np.int64)
    directed = np.vstack(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])
    )
    undirected = np.sort(directed, axis=1)
    _unique, inverse, counts = np.unique(
        undirected, axis=0, return_inverse=True, return_counts=True
    )
    direction = np.where(directed[:, 0] < directed[:, 1], 1, -1)
    direction_sum = np.bincount(inverse, weights=direction)
    boundary = int(np.count_nonzero(counts == 1))
    nonmanifold = int(np.count_nonzero(counts > 2))
    winding_consistent = bool(
        boundary == 0
        and nonmanifold == 0
        and np.all(direction_sum == 0)
    )
    return {
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "winding_consistent": winding_consistent,
    }


def build_box_mesh(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return one closed, outward-oriented rectangular prism."""

    coordinates = tuple(float(value) for value in (x0, x1, y0, y1, z0, z1))
    if not all(math.isfinite(value) for value in coordinates):
        raise RadialVisualProofError("Box coordinates must be finite")
    x0, x1, y0, y1, z0, z1 = coordinates
    if not (x1 > x0 and y1 > y0 and z1 > z0):
        raise RadialVisualProofError("Box extents must be positive")
    vertices = np.asarray(
        [
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y1, z0),
            (x0, y1, z0),
            (x0, y0, z1),
            (x1, y0, z1),
            (x1, y1, z1),
            (x0, y1, z1),
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            (0, 2, 1),
            (0, 3, 2),
            (4, 5, 6),
            (4, 6, 7),
            (0, 1, 5),
            (0, 5, 4),
            (3, 7, 6),
            (3, 6, 2),
            (0, 4, 7),
            (0, 7, 3),
            (1, 2, 6),
            (1, 6, 5),
        ],
        dtype=np.int32,
    )
    volume = _signed_volume(vertices, faces)
    expected = (x1 - x0) * (y1 - y0) * (z1 - z0)
    if not math.isclose(volume, expected, rel_tol=0.0, abs_tol=1.0e-10):
        raise RadialVisualProofError("Analytical box volume or winding drifted")
    topology = _edge_topology(faces)
    if topology != {
        "boundary_edges": 0,
        "nonmanifold_edges": 0,
        "winding_consistent": True,
    }:
        raise RadialVisualProofError("Analytical box is not a closed solid")
    return vertices, faces


def build_box_shell_and_core(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
    thickness_mm: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build a closed F2 shell and exactly touching closed F1 core."""

    thickness = float(thickness_mm)
    if not math.isfinite(thickness) or thickness <= 0.0:
        raise RadialVisualProofError("Shell thickness must be finite and positive")
    if 2.0 * thickness >= min(x1 - x0, y1 - y0, z1 - z0):
        raise RadialVisualProofError("Shell thickness consumes the analytical core")
    outer_vertices, outer_faces = build_box_mesh(x0, x1, y0, y1, z0, z1)
    core_vertices, core_faces = build_box_mesh(
        x0 + thickness,
        x1 - thickness,
        y0 + thickness,
        y1 - thickness,
        z0 + thickness,
        z1 - thickness,
    )
    shell_vertices = np.vstack((outer_vertices, core_vertices))
    shell_faces = np.vstack(
        (outer_faces, core_faces[:, [0, 2, 1]] + len(outer_vertices))
    ).astype(np.int32, copy=False)
    outer_volume = _signed_volume(outer_vertices, outer_faces)
    core_volume = _signed_volume(core_vertices, core_faces)
    shell_volume = _signed_volume(shell_vertices, shell_faces)
    tolerance = max(1.0e-10, outer_volume * 1.0e-12)
    if min(core_volume, shell_volume) <= 0.0:
        raise RadialVisualProofError("Shell or core has no positive volume")
    if not math.isclose(
        shell_volume + core_volume,
        outer_volume,
        rel_tol=0.0,
        abs_tol=tolerance,
    ):
        raise RadialVisualProofError("Analytical shell/core volume is not conserved")
    for name, faces in (("shell", shell_faces), ("core", core_faces)):
        topology = _edge_topology(faces)
        if topology != {
            "boundary_edges": 0,
            "nonmanifold_edges": 0,
            "winding_consistent": True,
        }:
            raise RadialVisualProofError(f"Analytical {name} is not watertight")
    return shell_vertices, shell_faces, core_vertices, core_faces


def _column_x0(index: int) -> float:
    return float(index) * (COLUMN_SIZE_XY_MM + COLUMN_GAP_MM)


def _interface_distance_stats(
    core_vertices: np.ndarray,
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
) -> dict[str, float]:
    points = np.asarray(core_vertices, dtype=np.float64)
    distances = np.min(
        np.column_stack(
            (
                points[:, 0] - x0,
                x1 - points[:, 0],
                points[:, 1] - y0,
                y1 - points[:, 1],
                points[:, 2] - z0,
                z1 - points[:, 2],
            )
        ),
        axis=1,
    )
    return {
        "minimum_mm": float(np.min(distances)),
        "maximum_mm": float(np.max(distances)),
        "mean_mm": float(np.mean(distances)),
    }


def build_radial_section_package() -> tuple[RadialExportPackage, list[dict[str, object]]]:
    """Return the exact five-column physical F2-shell/F1-core fixture."""

    cores: list[RadialExportPart] = []
    shells: list[RadialExportPart] = []
    proof_rows: list[dict[str, object]] = []
    for index, thickness in enumerate(SHELL_THICKNESSES_MM):
        x0 = _column_x0(index)
        x1 = x0 + COLUMN_SIZE_XY_MM
        y0 = 0.0
        y1 = COLUMN_SIZE_XY_MM
        z0 = 0.0
        z1 = COLUMN_HEIGHT_MM
        shell_vertices, shell_faces, core_vertices, core_faces = (
            build_box_shell_and_core(x0, x1, y0, y1, z0, z1, thickness)
        )
        interface = _interface_distance_stats(
            core_vertices,
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1,
            z0=z0,
            z1=z1,
        )
        if not all(
            math.isclose(value, thickness, rel_tol=0.0, abs_tol=1.0e-12)
            for value in interface.values()
        ):
            raise RadialVisualProofError("Core interface distance drifted")
        core_volume = _signed_volume(core_vertices, core_faces)
        shell_volume = _signed_volume(shell_vertices, shell_faces)
        outer_volume = COLUMN_SIZE_XY_MM**2 * COLUMN_HEIGHT_MM
        metadata = {
            "proof_schema": SCHEMA,
            "band": index + 1,
            "shell_thickness_mm": thickness,
            "inspect_z_mm": INSPECT_Z_MM,
            "geometry_version": GEOMETRY_VERSION,
        }
        cores.append(
            RadialExportPart(
                name=f"Band {index + 1} - F1 core - {thickness:.2f} mm shell",
                role="pure_black_core",
                vertices_mm=core_vertices,
                faces=core_faces,
                extruder=1,
                source_state=REFERENCE_STATE_INDICES[index] + 1,
                metadata=metadata,
            )
        )
        shells.append(
            RadialExportPart(
                name=f"Band {index + 1} - F2 shell - {thickness:.2f} mm",
                role="partner_outer_shell",
                vertices_mm=shell_vertices,
                faces=shell_faces,
                extruder=2,
                source_state=REFERENCE_STATE_INDICES[index] + 1,
                metadata=metadata,
            )
        )
        proof_rows.append(
            {
                "band": index + 1,
                "shell_thickness_mm": thickness,
                "x0_mm": x0,
                "x1_mm": x1,
                "y0_mm": y0,
                "y1_mm": y1,
                "z0_mm": z0,
                "z1_mm": z1,
                "outer_volume_mm3": outer_volume,
                "shell_volume_mm3": shell_volume,
                "core_volume_mm3": core_volume,
                "volume_residual_mm3": outer_volume - shell_volume - core_volume,
                "interface_distance_min_mm": interface["minimum_mm"],
                "interface_distance_max_mm": interface["maximum_mm"],
                "shell_topology": _edge_topology(shell_faces),
                "core_topology": _edge_topology(core_faces),
            }
        )
    metadata = {
        "radial_visual_proof": {
            "schema": SCHEMA,
            "geometry_version": GEOMETRY_VERSION,
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "physical_materials_only": True,
            "proof_method": "sliced-middle-layer-cross-section",
            "inspect_z_mm": INSPECT_Z_MM,
            "normal_surface_expected": "F2 only",
            "column_size_mm": [COLUMN_SIZE_XY_MM, COLUMN_SIZE_XY_MM, COLUMN_HEIGHT_MM],
            "column_gap_mm": COLUMN_GAP_MM,
            "shell_thicknesses_mm": list(SHELL_THICKNESSES_MM),
            "positive_overlap_mm3": 0.0,
            "gap_mm": 0.0,
            "shared_interface_partition_exact": True,
            "external_surface_coverage_exact": True,
            "adaptive_partition_used": False,
        }
    }
    package = RadialExportPackage(
        parts=tuple(cores + shells),
        physical_hex=PHYSICAL_HEX,
        black_extruder=1,
        metadata=metadata,
        layer_height_mm=LAYER_HEIGHT_MM,
        initial_layer_height_mm=INITIAL_LAYER_HEIGHT_MM,
        renderer="radial",
        process_profile=RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
    )
    return package, proof_rows


def _reference_palette() -> PaletteSettings:
    return PaletteSettings(
        material="PLA",
        palette_state_count=32,
        physical_hex=list(PHYSICAL_HEX),
        enabled_states=[True] * mixer.PALETTE_STATE_COUNT,
        mix_ratios_b=[33] * len(mixer.PAIR_INDICES),
        secondary_mix_ratios_b=[67] * len(mixer.PAIR_INDICES),
        output_mix_ratios_b=None,
    )


def _local_faces(faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    unique, inverse = np.unique(np.asarray(faces).reshape(-1), return_inverse=True)
    return unique, inverse.reshape((-1, 3)).astype(np.int32)


def _prepare_reference() -> tuple[PreparedGeometry, ColorResult, PaletteSettings]:
    palette = _reference_palette()
    _hex, palette_rgb_values = mixer.build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    palette_rgb = np.asarray(palette_rgb_values[:32], dtype=np.float64)
    vertices_parts: list[np.ndarray] = []
    faces_parts: list[np.ndarray] = []
    face_part_ids: list[np.ndarray] = []
    face_states: list[np.ndarray] = []
    vertex_states: list[np.ndarray] = []
    part_names: list[str] = []
    part_keys: list[str] = []
    part_face_counts: list[int] = []
    part_vertex_counts: list[int] = []
    offset = 0
    for index, (state, white_percent) in enumerate(
        zip(REFERENCE_STATE_INDICES, REFERENCE_WHITE_PERCENT, strict=True)
    ):
        x0 = _column_x0(index)
        vertices, faces = build_box_mesh(
            x0,
            x0 + COLUMN_SIZE_XY_MM,
            0.0,
            COLUMN_SIZE_XY_MM,
            0.0,
            COLUMN_HEIGHT_MM,
        )
        vertices_parts.append(vertices)
        faces_parts.append(faces + offset)
        face_part_ids.append(np.full(len(faces), index, dtype=np.int16))
        face_states.append(np.full(len(faces), state, dtype=np.int16))
        vertex_states.append(np.full(len(vertices), state, dtype=np.int16))
        part_names.append(
            f"LOOK ONLY Band {index + 1} - White {white_percent}%"
        )
        part_keys.append(f"look_only_band_{index + 1}")
        part_face_counts.append(len(faces))
        part_vertex_counts.append(len(vertices))
        offset += len(vertices)
    vertices_mm = np.vstack(vertices_parts)
    faces = np.vstack(faces_parts)
    part_ids = np.concatenate(face_part_ids)
    palette_indices = np.concatenate(face_states)
    vertex_state_indices = np.concatenate(vertex_states)
    height_mm = COLUMN_HEIGHT_MM
    vertices_unit = vertices_mm / height_mm
    vertex_colors = palette_rgb[vertex_state_indices]
    areas_unit = engine.triangle_areas(vertices_unit, faces)
    part_names_tuple = tuple(part_names)
    part_keys_tuple = tuple(part_keys)
    level = MeshLevel(
        vertices_unit=vertices_unit,
        faces=faces,
        vertex_colors=vertex_colors,
        areas_unit=areas_unit,
        neighbors=engine.face_neighbors(faces, len(vertices_unit)),
        face_part_ids=part_ids,
        part_names=part_names_tuple,
        part_keys=part_keys_tuple,
        face_provenance=np.zeros(len(faces), dtype=np.uint8),
    )
    source_hash = hashlib.sha256(
        vertices_mm.tobytes() + faces.tobytes()
    ).hexdigest()
    source = ObjAsset(
        path=Path("radial_visual_proof_look_only.obj"),
        sha256=source_hash,
        file_size=0,
        vertices=vertices_unit.copy(),
        colors=vertex_colors.copy(),
        faces=faces.copy(),
        original_vertex_count=len(vertices_mm),
        original_face_count=len(faces),
        warnings=[],
        part_names=part_names_tuple,
        part_keys=part_keys_tuple,
        face_part_ids=part_ids.copy(),
        part_face_counts=tuple(part_face_counts),
        part_vertex_counts=tuple(part_vertex_counts),
        part_marker_kind="radial_visual_proof_look_only",
        has_explicit_parts=True,
    )
    area = float(areas_unit.sum())
    volume = float(
        sum(
            _signed_volume(
                vertices_mm[
                    np.unique(faces[part_ids == part_id])
                ],
                _local_faces(faces[part_ids == part_id])[1],
            )
            for part_id in range(len(part_names))
        )
        / height_mm**3
    )
    prepared = PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(vertices_mm),
        clean_face_count=len(faces),
        removed_vertices=0,
        removed_faces=0,
        topology={
            "watertight": True,
            "part_count": len(part_names),
            "radial_visual_proof": True,
            "look_only": True,
        },
        source_area_unit=area,
        source_volume_unit=volume,
        simplified_area_unit=area,
        simplified_volume_unit=volume,
        source_dimensions_unit=np.ptp(vertices_unit, axis=0),
        warnings=[],
        part_names=part_names_tuple,
        part_keys=part_keys_tuple,
        part_stats=[
            {
                "part_id": part_id,
                "part_key": part_keys[part_id],
                "part_name": part_names[part_id],
                "vertices": part_vertex_counts[part_id],
                "faces": part_face_counts[part_id],
            }
            for part_id in range(len(part_names))
        ],
        assembly={
            "solidify_parts": True,
            "all_parts_watertight": True,
            "repair_method": "purpose_built_analytical_box_primitives",
            "radial_visual_proof": {
                "schema": SCHEMA,
                "look_only": True,
                "radial_geometry": False,
            },
        },
    )
    prepared._hotfix_subtriangle_paint = {}
    face_rgb = palette_rgb[palette_indices]
    counts = np.bincount(palette_indices, minlength=32)
    areas_mm2 = areas_unit * height_mm**2
    by_area = np.bincount(palette_indices, weights=areas_mm2, minlength=32)
    fractions = by_area / max(float(by_area.sum()), 1.0e-12)
    colors = ColorResult(
        tone_vertex_rgb=vertex_colors,
        source_face_rgb=face_rgb.copy(),
        palette_indices=palette_indices.copy(),
        target_face_rgb=face_rgb.copy(),
        delta_e=np.zeros(len(faces), dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=0.0,
        manual_override_faces=0,
        part_metrics=[],
    )
    return prepared, colors, palette


def _rewrite_zip_members(path: Path, replacements: Mapping[str, bytes]) -> None:
    temporary = Path(path).with_name(f".{Path(path).name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as destination:
            existing: set[str] = set()
            for info in source.infolist():
                existing.add(info.filename)
                destination.writestr(
                    info,
                    replacements.get(info.filename, source.read(info.filename)),
                )
            for name, payload in replacements.items():
                if name not in existing:
                    destination.writestr(name, payload)
        with zipfile.ZipFile(temporary, "r") as reopened:
            if reopened.testzip() is not None:
                raise RadialVisualProofError("Patched reference 3MF has a CRC failure")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_reference_3mf(path: Path) -> dict[str, object]:
    prepared, colors, palette = _prepare_reference()
    base_validation = engine.write_3mf_atomic(
        path,
        prepared,
        colors,
        COLUMN_HEIGHT_MM,
        palette,
        part_palettes=None,
        print_uses_global_palette=True,
    )
    with zipfile.ZipFile(path, "r") as archive:
        project = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
    project.update(
        {
            "print_settings_id": "0.10 LOOK ONLY Visual Reference @Snapmaker U1",
            "layer_height": "0.1",
            "initial_layer_print_height": "0.2",
            "adaptive_layer_height": "0",
            "enable_support": "0",
            "raft_layers": "0",
        }
    )
    metadata = {
        "schema": SCHEMA,
        "geometry_version": GEOMETRY_VERSION,
        "artifact": "visual-reference",
        "look_only": True,
        "radial_geometry": False,
        "send_to_printer": False,
        "layer_height_mm": LAYER_HEIGHT_MM,
        "states_zero_based": list(REFERENCE_STATE_INDICES),
        "states_one_based": [value + 1 for value in REFERENCE_STATE_INDICES],
        "white_percent": list(REFERENCE_WHITE_PERCENT),
        "explanation": (
            "This archive only makes the five intended cel-shade bands visible. "
            "It does not prove radial shell geometry."
        ),
    }
    _rewrite_zip_members(
        path,
        {
            "Metadata/project_settings.config": json.dumps(
                project, ensure_ascii=False, indent=2
            ).encode("utf-8"),
            "Metadata/radial_visual_proof.json": json.dumps(
                metadata, ensure_ascii=False, indent=2
            ).encode("utf-8"),
        },
    )
    return validate_reference_3mf(path, base_validation=base_validation)


def validate_reference_3mf(
    path: Path,
    *,
    base_validation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    path = Path(path)
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise RadialVisualProofError("Reference 3MF has a ZIP CRC failure")
        names = set(archive.namelist())
        required = {
            "3D/Objects/object_1.model",
            "Metadata/project_settings.config",
            "Metadata/radial_visual_proof.json",
        }
        missing = sorted(required - names)
        if missing:
            raise RadialVisualProofError(
                f"Reference 3MF is missing members: {missing}"
            )
        metadata = json.loads(
            archive.read("Metadata/radial_visual_proof.json").decode("utf-8")
        )
        project = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
        model = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    if metadata.get("schema") != SCHEMA or metadata.get("look_only") is not True:
        raise RadialVisualProofError("Reference LOOK ONLY marker is missing")
    if metadata.get("radial_geometry") is not False:
        raise RadialVisualProofError("Reference is incorrectly marked radial")
    if metadata.get("send_to_printer") is not False:
        raise RadialVisualProofError("Reference is incorrectly print-enabled")
    if project.get("layer_height") != "0.1":
        raise RadialVisualProofError("Reference layer height is not 0.10 mm")
    if metadata.get("states_zero_based") != list(REFERENCE_STATE_INDICES):
        raise RadialVisualProofError("Reference state order drifted")
    local = lambda tag: tag.split("}")[-1]
    triangles = [item for item in model.iter() if local(item.tag) == "triangle"]
    if len(triangles) != len(REFERENCE_STATE_INDICES) * 12:
        raise RadialVisualProofError("Reference triangle count drifted")
    painted = [item.attrib.get("paint_color") for item in triangles]
    if any(value is None for value in painted):
        raise RadialVisualProofError("Reference contains an unpainted triangle")
    expected_counts = {
        str(engine.PAINT_CODES[state]): 12 for state in REFERENCE_STATE_INDICES
    }
    actual_counts: dict[str, int] = {}
    for value in painted:
        actual_counts[str(value)] = actual_counts.get(str(value), 0) + 1
    if actual_counts != expected_counts:
        raise RadialVisualProofError(
            f"Reference paint states drifted: {actual_counts} != {expected_counts}"
        )
    result = {
        "schema": SCHEMA,
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "zip_crc_ok": True,
        "look_only": True,
        "radial_geometry": False,
        "layer_height_mm": LAYER_HEIGHT_MM,
        "parts": len(REFERENCE_STATE_INDICES),
        "faces": len(triangles),
        "paint_counts": actual_counts,
        "states_zero_based": list(REFERENCE_STATE_INDICES),
    }
    if base_validation is not None:
        result["engine_prepatch_validation"] = dict(base_validation)
    return result


def _srgb_channel_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _rgb_l_star(rgb: Sequence[float]) -> float:
    channels = np.asarray(rgb, dtype=np.float64).reshape(3)
    if float(np.max(channels)) > 1.0:
        channels = channels / 255.0
    linear = np.asarray([_srgb_channel_to_linear(float(value)) for value in channels])
    y = float(np.dot(linear, np.asarray((0.2126, 0.7152, 0.0722))))
    yn = 1.0
    delta = 6.0 / 29.0
    ratio = y / yn
    f = ratio ** (1.0 / 3.0) if ratio > delta**3 else ratio / (3 * delta**2) + 4.0 / 29.0
    return 116.0 * f - 16.0


def _reference_display_rows(proof_rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    palette = _reference_palette()
    palette_hex, palette_rgb_values = mixer.build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    rows: list[dict[str, object]] = []
    previous_l: float | None = None
    for index, proof in enumerate(proof_rows):
        state = REFERENCE_STATE_INDICES[index]
        l_star = _rgb_l_star(palette_rgb_values[state])
        rows.append(
            {
                "band": index + 1,
                "reference_state_zero_based": state,
                "reference_state_one_based": state + 1,
                "display_hex": str(palette_hex[state]).upper(),
                "display_l_star": l_star,
                "delta_l_star_from_previous": (
                    "" if previous_l is None else l_star - previous_l
                ),
                "reference_white_percent": REFERENCE_WHITE_PERCENT[index],
                "reference_black_percent": 100 - REFERENCE_WHITE_PERCENT[index],
                "radial_outer_material": "F2 White",
                "radial_core_material": "F1 Black",
                "shell_thickness_mm": proof["shell_thickness_mm"],
                "column_x0_mm": proof["x0_mm"],
                "column_x1_mm": proof["x1_mm"],
                "column_gap_mm": COLUMN_GAP_MM,
                "inspect_z_mm": INSPECT_Z_MM,
                "normal_surface_preview": "F2 only (expected)",
                "radial_proof_view": "Sliced middle-layer cross-section",
            }
        )
        previous_l = l_star
    return rows


def _write_mapping_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        raise RadialVisualProofError("Mapping CSV needs at least one row")
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/meiryob.ttc" if bold else "C:/Windows/Fonts/meiryo.ttc",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _write_mapping_png(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    image = Image.new("RGB", (1600, 920), "#F5F7FA")
    draw = ImageDraw.Draw(image)
    title_font = _load_font(42, bold=True)
    heading_font = _load_font(30, bold=True)
    body_font = _load_font(24)
    small_font = _load_font(20)
    draw.text((50, 32), "ChromaMatter Radial Visual Proof", fill="#111827", font=title_font)
    draw.text(
        (50, 92),
        "LEFT: visible LOOK ONLY target   |   RIGHT: physical shell proof at Z ~= 6 mm",
        fill="#374151",
        font=body_font,
    )
    draw.rounded_rectangle((40, 150, 760, 820), radius=22, fill="white", outline="#CBD5E1", width=3)
    draw.rounded_rectangle((800, 150, 1560, 820), radius=22, fill="white", outline="#CBD5E1", width=3)
    draw.text((75, 180), "00_REFERENCE_LOOK_ONLY", fill="#0F172A", font=heading_font)
    draw.text((835, 180), "06_RADIAL_SECTION_5BAND", fill="#0F172A", font=heading_font)
    draw.text((75, 225), "Surface shades are intentionally visible.", fill="#475569", font=small_font)
    draw.text((835, 225), "Normal surface is F2 white only (correct).", fill="#475569", font=small_font)
    draw.text((835, 255), "Slice, then inspect a middle layer in Filament/Line Type.", fill="#475569", font=small_font)
    bar_x0 = 100
    bar_y0 = 320
    bar_width = 110
    bar_gap = 18
    for index, row in enumerate(rows):
        x0 = bar_x0 + index * (bar_width + bar_gap)
        color = str(row["display_hex"])
        draw.rectangle((x0, bar_y0, x0 + bar_width, 610), fill=color, outline="#111827", width=2)
        draw.text((x0 + 8, 625), f"Band {index + 1}", fill="#111827", font=small_font)
        draw.text((x0 + 8, 655), f"L* {float(row['display_l_star']):.1f}", fill="#334155", font=small_font)
        draw.text((x0 + 8, 685), f"W {int(row['reference_white_percent'])}%", fill="#334155", font=small_font)
        draw.text((x0 + 8, 715), f"State {int(row['reference_state_one_based'])}", fill="#334155", font=small_font)
    section_x0 = 860
    section_y0 = 350
    outer_px = 116
    section_gap = 22
    for index, row in enumerate(rows):
        x0 = section_x0 + index * (outer_px + section_gap)
        thickness = float(row["shell_thickness_mm"])
        # Minimum 3 px is only a diagram aid.  Exact geometry is in the 3MF.
        shell_px = max(3, int(round(thickness / COLUMN_SIZE_XY_MM * outer_px)))
        draw.rectangle(
            (x0, section_y0, x0 + outer_px, section_y0 + outer_px),
            fill="#F5F5F5",
            outline="#64748B",
            width=2,
        )
        draw.rectangle(
            (
                x0 + shell_px,
                section_y0 + shell_px,
                x0 + outer_px - shell_px,
                section_y0 + outer_px - shell_px,
            ),
            fill="#121212",
        )
        draw.text((x0 + 5, section_y0 + 140), f"Band {index + 1}", fill="#111827", font=small_font)
        draw.text((x0 + 5, section_y0 + 170), f"{thickness:.2f} mm", fill="#0F766E", font=small_font)
    draw.text((835, 600), "F2 shell", fill="#475569", font=body_font)
    draw.rectangle((960, 598, 1000, 628), fill="#F5F5F5", outline="#64748B")
    draw.text((1060, 600), "F1 core", fill="#475569", font=body_font)
    draw.rectangle((1170, 598, 1210, 628), fill="#121212", outline="#64748B")
    draw.text(
        (835, 665),
        "0.10 / 0.18 mm may disappear or be widened by a 0.4 mm nozzle.",
        fill="#B45309",
        font=body_font,
    )
    draw.text(
        (835, 710),
        "That slicer behavior is a result to record, not a geometry failure.",
        fill="#B45309",
        font=small_font,
    )
    image.save(path, format="PNG", optimize=True)


def _rgb_to_hex(rgb: Sequence[float]) -> str:
    values = np.asarray(rgb, dtype=np.float64).reshape(3)
    if float(np.max(values)) <= 1.0 + 1.0e-12:
        values = values * 255.0
    values = np.clip(np.rint(values), 0.0, 255.0).astype(np.uint8)
    return "#" + "".join(f"{int(value):02X}" for value in values)


def _project_mesh_for_panel(
    vertices: np.ndarray,
    bounds: tuple[int, int, int, int],
    *,
    view_from_object: Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(vertices, dtype=np.float64)
    view = np.asarray(view_from_object, dtype=np.float64)
    view /= np.linalg.norm(view)
    world_up = np.asarray((0.0, 0.0, 1.0), dtype=np.float64)
    right = np.cross(world_up, view)
    if np.linalg.norm(right) <= 1.0e-9:
        right = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
    right /= np.linalg.norm(right)
    up = np.cross(view, right)
    up /= np.linalg.norm(up)
    projected = np.column_stack((points @ right, points @ up))
    depth = points @ view
    minimum = projected.min(axis=0)
    maximum = projected.max(axis=0)
    span = np.maximum(maximum - minimum, 1.0e-9)
    left, top, right_edge, bottom = bounds
    scale = min((right_edge - left - 70) / span[0], (bottom - top - 100) / span[1])
    centre = 0.5 * (minimum + maximum)
    canvas_centre = np.asarray(
        (0.5 * (left + right_edge), 0.5 * (top + 60 + bottom)),
        dtype=np.float64,
    )
    screen = (projected - centre) * scale
    screen[:, 1] *= -1.0
    screen += canvas_centre
    return screen, depth


def _draw_coloured_mesh_panel(
    image: Image.Image,
    bounds: tuple[int, int, int, int],
    *,
    vertices: np.ndarray,
    faces: np.ndarray,
    face_rgb: np.ndarray,
    label: str,
    draw_triangle_outlines: bool,
) -> None:
    draw = ImageDraw.Draw(image)
    heading_font = _load_font(27, bold=True)
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=22, fill="#111821", outline="#355066", width=3)
    draw.text((left + 24, top + 18), label, fill="#F5F1E8", font=heading_font)
    screen, depth = _project_mesh_for_panel(
        vertices,
        bounds,
        view_from_object=(0.0, -1.0, 0.0),
    )
    faces_array = np.asarray(faces, dtype=np.int64)
    colors = np.asarray(face_rgb, dtype=np.float64)
    order = sorted(
        range(len(faces_array)),
        key=lambda index: float(np.mean(depth[faces_array[index]])),
    )
    for face_index in order:
        polygon = [
            (float(screen[vertex, 0]), float(screen[vertex, 1]))
            for vertex in faces_array[face_index]
        ]
        draw.polygon(
            polygon,
            fill=_rgb_to_hex(colors[face_index]),
            outline="#20262D" if draw_triangle_outlines else None,
        )


def _write_obj_import_comparison(
    path: Path,
    *,
    source_mesh: object,
    source_face_rgb: np.ndarray,
    loaded: ObjAsset,
    loaded_face_rgb: np.ndarray,
    exact_area_fraction: float,
) -> None:
    image = Image.new("RGB", (1600, 900), "#0B1016")
    draw = ImageDraw.Draw(image)
    title_font = _load_font(38, bold=True)
    body_font = _load_font(23)
    draw.text(
        (45, 25),
        "ChromaMatter OBJ Import Comparison",
        fill="#F8FAFC",
        font=title_font,
    )
    draw.text(
        (45, 78),
        "Left: authored face states   |   Right: reloaded XYZRGB OBJ",
        fill="#CBD5E1",
        font=body_font,
    )
    _draw_coloured_mesh_panel(
        image,
        (35, 125, 785, 790),
        vertices=np.asarray(getattr(source_mesh, "vertices_mm"), dtype=np.float64),
        faces=np.asarray(getattr(source_mesh, "faces"), dtype=np.int32),
        face_rgb=source_face_rgb,
        label="SOURCE: exact cel face states",
        draw_triangle_outlines=True,
    )
    _draw_coloured_mesh_panel(
        image,
        (815, 125, 1565, 790),
        vertices=np.asarray(loaded.vertices, dtype=np.float64),
        faces=np.asarray(loaded.faces, dtype=np.int32),
        face_rgb=loaded_face_rgb,
        label="CHROMAMATTER RELOAD: planar-inset XYZRGB",
        draw_triangle_outlines=False,
    )
    draw.text(
        (45, 820),
        (
            f"Exact categorical-colour carrier area: {exact_area_fraction * 100.0:.2f}%   "
            "|   narrow edge strips preserve one closed indexed solid"
        ),
        fill="#9FE5CF",
        font=body_font,
    )
    image.save(path, format="PNG", optimize=True)


def _validate_all_obj_vertices_are_xyzrgb(path: Path) -> dict[str, int | bool]:
    vertex_rows = 0
    malformed = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.startswith("v "):
            continue
        vertex_rows += 1
        fields = line.split()
        if len(fields) != 7:
            malformed += 1
            continue
        try:
            values = [float(value) for value in fields[1:]]
        except ValueError:
            malformed += 1
            continue
        if not all(math.isfinite(value) for value in values):
            malformed += 1
    if vertex_rows <= 0 or malformed:
        raise RadialVisualProofError(
            f"OBJ XYZRGB vertex contract failed: rows={vertex_rows}, malformed={malformed}"
        )
    return {
        "vertex_rows": vertex_rows,
        "malformed_vertex_rows": malformed,
        "all_vertices_xyzrgb": True,
    }


def _write_obj_import_artifacts(
    folder: Path,
) -> tuple[Path, Path, Path, Path, dict[str, object]]:
    # This call is intentional: the OBJ proof must exercise the exact current
    # planar-inset writer used by the synthetic head coupon, not a second copy.
    from . import variable_skin_head_coupon as head_coupon

    folder = Path(folder)
    obj_path = folder / OBJ_IMPORT_FILENAME
    mtl_path = folder / OBJ_IMPORT_MTL_FILENAME
    comparison_path = folder / OBJ_IMPORT_COMPARISON_FILENAME
    validation_path = folder / OBJ_IMPORT_VALIDATION_FILENAME
    mesh = head_coupon.build_blocky_head_mesh()
    palette = head_coupon.head_palette()
    head_coupon._write_original_obj_mtl(obj_path, mtl_path, mesh, palette)
    xyzrgb = _validate_all_obj_vertices_are_xyzrgb(obj_path)
    loaded = engine.load_vertex_color_obj(obj_path)
    topology = engine.edge_topology(loaded.faces, len(loaded.vertices))
    boundary = int(topology.get("boundary_edges", -1))
    nonmanifold = int(topology.get("nonmanifold_edges", -1))
    if boundary != 0 or nonmanifold != 0:
        raise RadialVisualProofError(
            f"Reloaded OBJ is not closed: boundary={boundary}, nonmanifold={nonmanifold}"
        )
    source_volume = float(mesh.source_volume_mm3)
    loaded_volume = float(engine.signed_volume(loaded.vertices, loaded.faces))
    if not math.isclose(
        source_volume,
        loaded_volume,
        rel_tol=1.0e-10,
        abs_tol=1.0e-8,
    ):
        raise RadialVisualProofError("Reloaded OBJ volume differs from the source head")
    _hex, palette_rgb_values = mixer.build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    palette_rgb = np.asarray(palette_rgb_values, dtype=np.float64)
    loaded_face_rgb = engine.face_rgb_from_vertex_colors(
        loaded.colors,
        loaded.faces,
    )
    exact_palette_face = np.any(
        np.all(
            np.isclose(
                loaded_face_rgb[:, None, :],
                palette_rgb[None, :, :],
                atol=1.0e-7,
                rtol=0.0,
            ),
            axis=2,
        ),
        axis=1,
    )
    face_areas = engine.triangle_areas(loaded.vertices, loaded.faces)
    exact_area_fraction = float(
        face_areas[exact_palette_face].sum() / face_areas.sum()
    )
    minimum_exact = float(head_coupon.REFERENCE_OBJ_EXACT_FACE_AREA_FRACTION)
    if exact_area_fraction < minimum_exact - 1.0e-8:
        raise RadialVisualProofError(
            "Reloaded OBJ lost too much exact categorical face-colour area"
        )
    required_states = {
        int(head_coupon.STATE_BLACK),
        int(head_coupon.STATE_BROWN),
        int(head_coupon.STATE_WHITE),
        *(int(value) for value in head_coupon.SKIN_RADIAL_STATES),
    }
    missing_states = [
        state
        for state in sorted(required_states)
        if not np.any(
            np.all(
                np.isclose(
                    loaded_face_rgb,
                    palette_rgb[state],
                    atol=1.0e-7,
                    rtol=0.0,
                ),
                axis=1,
            )
        )
    ]
    if missing_states:
        raise RadialVisualProofError(
            f"Reloaded OBJ is missing exact carrier states: {missing_states}"
        )
    prepared = engine.prepare_geometry(
        loaded,
        GeometrySettings(
            height_mm=COLUMN_HEIGHT_MM * 3.0,
            adjust_face_count=False,
            up_axis="Z",
            min_component_faces=0,
        ),
    )
    prepared_watertight = bool(prepared.topology.get("watertight"))
    prepared_boundary = int(prepared.topology.get("boundary_edges", -1))
    prepared_nonmanifold = int(prepared.topology.get("nonmanifold_edges", -1))
    if not prepared_watertight or prepared_boundary != 0 or prepared_nonmanifold != 0:
        raise RadialVisualProofError("ChromaMatter prepare_geometry did not preserve the OBJ solid")
    source_face_rgb = palette_rgb[np.asarray(mesh.face_states, dtype=np.intp)]
    _write_obj_import_comparison(
        comparison_path,
        source_mesh=mesh,
        source_face_rgb=source_face_rgb,
        loaded=loaded,
        loaded_face_rgb=loaded_face_rgb,
        exact_area_fraction=exact_area_fraction,
    )
    mtl_text = mtl_path.read_text(encoding="utf-8")
    material_count = sum(
        1 for line in mtl_text.splitlines() if line.startswith("newmtl ")
    )
    validation: dict[str, object] = {
        "schema": SCHEMA,
        "artifact": "chromamatter-obj-import-test",
        "separate_from_3mf_proof": True,
        "writer": "variable_skin_head_coupon._write_original_obj_mtl",
        "obj": obj_path.name,
        "mtl": mtl_path.name,
        "comparison_png": comparison_path.name,
        "obj_sha256": _sha256(obj_path),
        "mtl_sha256": _sha256(mtl_path),
        "all_vertices_xyzrgb": xyzrgb["all_vertices_xyzrgb"],
        "vertex_rows": xyzrgb["vertex_rows"],
        "faces": len(loaded.faces),
        "material_count": material_count,
        "load_vertex_color_obj": "pass",
        "prepare_geometry": "pass",
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "watertight": boundary == 0 and nonmanifold == 0,
        "source_volume_mm3": source_volume,
        "loaded_volume_mm3": loaded_volume,
        "volume_residual_mm3": loaded_volume - source_volume,
        "exact_face_colour_area_fraction": exact_area_fraction,
        "minimum_exact_face_colour_area_fraction": minimum_exact,
        "exact_required_states_zero_based": sorted(required_states),
        "prepare_watertight": prepared_watertight,
        "prepare_boundary_edges": prepared_boundary,
        "prepare_nonmanifold_edges": prepared_nonmanifold,
        "prepared_vertices": len(prepared.final.vertices_unit),
        "prepared_faces": len(prepared.final.faces),
    }
    _write_json(validation_path, validation)
    return obj_path, mtl_path, comparison_path, validation_path, validation


def _readme_ja() -> str:
    return f"""# ChromaMatter ラジアル可視化・断面検証セット

このフォルダーは、旧INVALID bundleを上書きせずに作った独立検証セットです。通常モデル用のadaptive partitionは使用せず、数式で定義した直方体だけから生成しています。

## 2つの3MFは目的が違います

### `{REFERENCE_FILENAME}`

- **見た目だけを比較する LOOK ONLY 参照**です。
- 左から右へ、白100% → 75% → 50% → 25% → 黒100%の5段階を表面に表示します。
- これは「目標とするセル陰影が見えるか」を確認する資料です。
- **ラジアル形状の証明ではなく、プリンターへ送らないでください。**

### `{RADIAL_FILENAME}`

- 8 × 8 × 12 mmの閉じたcolumnを2 mm間隔で5本並べています。
- 全columnはF2白のwatertight shellとF1黒のwatertight coreから成ります。
- shell厚は左から **0.10 / 0.18 / 0.26 / 0.34 / 0.42 mm** です。
- 通常の外観で表面がすべてF2白に見えるのは**正しい状態**です。ラジアルの証明は表面色ではなく断面です。

## Snapmaker Orcaでの確認手順

1. `{RADIAL_FILENAME}` を「プロジェクトとして開く / Open as project」で開きます。
2. 設定を自動修復・結合・置換せず、0.10 mm設定のままスライスします。
3. Previewで **Filament** または **Line Type** を選びます。
4. 天面・底面を避け、**Z ≈ {INSPECT_Z_MM:.1f} mm** の中間レイヤーへ移動します。
5. 各columnで、F1黒coreの周囲をF2白shellが囲み、左から右へshellが厚くなることを確認します。
6. 0.10 mmと0.18 mmが消える・太く補正される場合、その挙動をスクリーンショットとOrca versionとともに記録してください。

## ChromaMatter OBJ読込テスト（3MF proofとは別）

`{OBJ_IMPORT_FILENAME}` と `{OBJ_IMPORT_MTL_FILENAME}` は、ChromaMatterのOBJ読込だけを確認する独立テストです。3MFのラジアル厚を証明するファイルではありません。

1. ChromaMatterで `{OBJ_IMPORT_FILENAME}` を開きます。
2. エラーなく読み込まれ、ブロック状の頭部と5段階のセル陰影が表示されることを確認します。
3. `{OBJ_IMPORT_COMPARISON_FILENAME}` の左（元のface state）と右（ChromaMatterが再読込したXYZRGB OBJ）を比較します。

OBJの全頂点は `v X Y Z R G B` です。修正版planar-inset writerにより、閉じたindexed solidを維持したまま、面積の大部分が正確なカテゴリ色になります。生成時に `load_vertex_color_obj` → `prepare_geometry`、watertight、boundary/non-manifold、volume、exact face-colour areaを再検証しています。

**旧INVALID folderに残っている3MFは使用しないでください。** このCORRECTED folderの2つの3MFと、別目的のOBJ読込テストだけを使用してください。

## 0.4 mm nozzleに関する重要事項

0.10 mmと0.18 mmは0.4 mm nozzleの一般的な線幅より細いため、Orcaが削除または拡幅する可能性があります。これは今回確認したいスライサー挙動です。3MF内の解析形状は指定厚さで、volume conservation、boundary edge 0、non-manifold edge 0、正の体積、interface distanceを生成時に再検証しています。

`{MAPPING_PNG_FILENAME}` は見方の図、`{MAPPING_CSV_FILENAME}` はstate・L*・厚さ・位置の対応表です。どちらも3MFの代わりではありません。

全ファイルは実験用 / SLICE ONLYです。実機投入はまだ行わないでください。
"""


def _readme_en() -> str:
    return f"""# ChromaMatter radial visual and section proof set

This is a new independent proof set. It does not overwrite the old INVALID bundle and does not use the adaptive production partitioner; all geometry is analytical box geometry.

## The two 3MF files have different jobs

### `{REFERENCE_FILENAME}`

- This is a **LOOK ONLY visual reference**.
- Its surfaces visibly progress from 100% white to 75%, 50%, 25%, and 100% black.
- Use it to judge whether the intended five cel-shade bands are visible.
- It is **not proof of radial geometry and must not be sent to the printer.**

### `{RADIAL_FILENAME}`

- Five closed 8 x 8 x 12 mm columns are arranged with 2 mm gaps.
- Every column is an F2-white watertight shell around an F1-black watertight core.
- Shell thickness progresses through **0.10 / 0.18 / 0.26 / 0.34 / 0.42 mm**.
- Seeing F2 only on every normal outer surface is **expected and correct**. Radial proof comes from a sliced cross-section, not from the normal surface preview.

## Snapmaker Orca inspection

1. Open `{RADIAL_FILENAME}` with **Open as project**.
2. Do not auto-repair, merge, or substitute settings. Slice at the recorded 0.10 mm layer height.
3. In Preview, select **Filament** or **Line Type**.
4. Avoid the top and bottom skins and move to a middle layer near **Z ~= {INSPECT_Z_MM:.1f} mm**.
5. Confirm that each F1-black core is surrounded by an F2-white shell and that the shell becomes thicker from left to right.
6. If the 0.10 or 0.18 mm shell disappears or is widened, record that behavior with a screenshot and the Orca version.

## ChromaMatter OBJ import test (separate from the 3MF proof)

`{OBJ_IMPORT_FILENAME}` and `{OBJ_IMPORT_MTL_FILENAME}` test ChromaMatter's OBJ import only. They do not prove radial shell thickness.

1. Open `{OBJ_IMPORT_FILENAME}` in ChromaMatter.
2. Confirm that it loads without an error and shows the blocky head with five cel-shade levels.
3. Compare the authored face states on the left of `{OBJ_IMPORT_COMPARISON_FILENAME}` with the reloaded XYZRGB OBJ on the right.

Every OBJ vertex uses `v X Y Z R G B`. The corrected planar-inset writer preserves one closed indexed solid while keeping exact categorical colour over most of each source face. Generation re-runs `load_vertex_color_obj` -> `prepare_geometry` and verifies watertightness, boundary/non-manifold edges, volume, and exact face-colour area.

**Do not use any 3MF left in the old INVALID folder.** Use only the two 3MF files in this CORRECTED folder; the OBJ is a separate import test.

## Important 0.4 mm nozzle note

The 0.10 and 0.18 mm shells are narrower than a common 0.4 mm-nozzle line width. Orca may remove or widen them. That slicer behavior is a test result, not automatically a source-geometry failure. Generation rechecks the analytical thickness, volume conservation, zero boundary edges, zero non-manifold edges, positive volume, and interface distance.

`{MAPPING_PNG_FILENAME}` explains the two views. `{MAPPING_CSV_FILENAME}` maps state, L*, thickness, and position. Neither replaces inspection of the sliced 3MF.

All artifacts remain experimental / SLICE ONLY. Do not send them to the printer yet.
"""


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_manifest(folder: Path, files: Sequence[Path]) -> Path:
    manifest = Path(folder) / MANIFEST_FILENAME
    lines = [f"{_sha256(path)} *{path.name}" for path in sorted(files, key=lambda item: item.name)]
    manifest.write_text("\n".join(lines) + "\n", encoding="ascii")
    return manifest


def validate_manifest(folder: Path) -> dict[str, object]:
    folder = Path(folder)
    manifest = folder / MANIFEST_FILENAME
    records: list[dict[str, object]] = []
    for line in manifest.read_text(encoding="ascii").splitlines():
        digest, marker_name = line.split(" ", 1)
        if not marker_name.startswith("*"):
            raise RadialVisualProofError("Manifest record is malformed")
        name = marker_name[1:]
        path = folder / name
        actual = _sha256(path)
        if actual != digest:
            raise RadialVisualProofError(f"Manifest mismatch: {name}")
        records.append({"name": name, "sha256": actual, "bytes": path.stat().st_size})
    expected = sorted(
        path.name for path in folder.iterdir() if path.is_file() and path.name != MANIFEST_FILENAME
    )
    actual_names = sorted(str(record["name"]) for record in records)
    if expected != actual_names:
        raise RadialVisualProofError(
            f"Manifest file set drifted: {actual_names} != {expected}"
        )
    return {"records": records, "count": len(records), "ok": True}


def generate_radial_visual_proof_bundle(output_folder: Path) -> RadialVisualProofBundle:
    folder = Path(output_folder)
    folder.mkdir(parents=True, exist_ok=False)
    reference_path = folder / REFERENCE_FILENAME
    radial_path = folder / RADIAL_FILENAME
    mapping_csv_path = folder / MAPPING_CSV_FILENAME
    mapping_png_path = folder / MAPPING_PNG_FILENAME
    readme_ja_path = folder / README_JA_FILENAME
    readme_en_path = folder / README_EN_FILENAME
    reference_validation_path = folder / REFERENCE_VALIDATION_FILENAME
    radial_validation_path = folder / RADIAL_VALIDATION_FILENAME
    (
        obj_import_path,
        obj_import_mtl_path,
        obj_import_comparison_path,
        obj_import_validation_path,
        obj_import_validation,
    ) = _write_obj_import_artifacts(folder)

    reference_validation = _write_reference_3mf(reference_path)
    package, proof_rows = build_radial_section_package()
    radial_written = write_radial_3mf_atomic(
        radial_path,
        package,
        title="radial visual proof five shell thickness bands 0.10 mm",
    )
    radial_reopened = validate_radial_3mf(
        radial_path,
        expected_parts=10,
        expected_physical=PHYSICAL_HEX,
        expected_extruders=(1, 1, 1, 1, 1, 2, 2, 2, 2, 2),
        expected_process_profile=RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
    )
    if radial_written.sha256 != radial_reopened.sha256:
        raise RadialVisualProofError("Radial writer and reopen hash differ")
    radial_validation: dict[str, object] = {
        "schema": SCHEMA,
        "geometry_version": GEOMETRY_VERSION,
        "path": str(radial_path),
        "sha256": radial_reopened.sha256,
        "bytes": radial_reopened.bytes,
        "parts": radial_reopened.parts,
        "vertices": radial_reopened.vertices,
        "faces": radial_reopened.faces,
        "physical_extruders": list(radial_reopened.physical_extruders),
        "zip_crc_ok": radial_reopened.zip_crc_ok,
        "slice_only": radial_reopened.slice_only,
        "print_allowed": radial_reopened.print_allowed,
        "physical_materials_only": radial_reopened.physical_materials_only,
        "static_validation_ok": radial_reopened.static_validation_ok,
        "adaptive_partition_used": False,
        "normal_surface_expected": "F2 only",
        "proof_view": "sliced middle-layer cross-section",
        "inspect_z_mm": INSPECT_Z_MM,
        "columns": proof_rows,
    }
    mapping_rows = _reference_display_rows(proof_rows)
    _write_mapping_csv(mapping_csv_path, mapping_rows)
    _write_mapping_png(mapping_png_path, mapping_rows)
    readme_ja_path.write_text(_readme_ja(), encoding="utf-8")
    readme_en_path.write_text(_readme_en(), encoding="utf-8")
    _write_json(reference_validation_path, reference_validation)
    _write_json(radial_validation_path, radial_validation)
    files = [
        reference_path,
        radial_path,
        mapping_csv_path,
        mapping_png_path,
        readme_ja_path,
        readme_en_path,
        reference_validation_path,
        radial_validation_path,
        obj_import_path,
        obj_import_mtl_path,
        obj_import_comparison_path,
        obj_import_validation_path,
    ]
    manifest_path = _write_manifest(folder, files)
    validate_manifest(folder)
    return RadialVisualProofBundle(
        folder=folder,
        reference_path=reference_path,
        radial_path=radial_path,
        obj_import_path=obj_import_path,
        obj_import_mtl_path=obj_import_mtl_path,
        obj_import_comparison_path=obj_import_comparison_path,
        obj_import_validation_path=obj_import_validation_path,
        mapping_csv_path=mapping_csv_path,
        mapping_png_path=mapping_png_path,
        readme_ja_path=readme_ja_path,
        readme_en_path=readme_en_path,
        reference_validation_path=reference_validation_path,
        radial_validation_path=radial_validation_path,
        manifest_path=manifest_path,
        reference_validation=reference_validation,
        radial_validation=radial_validation,
        obj_import_validation=obj_import_validation,
    )


def augment_radial_visual_proof_bundle(folder: Path) -> dict[str, object]:
    """Add the verified OBJ-import fixture to an existing corrected proof set."""

    folder = Path(folder)
    if not folder.is_dir():
        raise RadialVisualProofError(f"Corrected proof folder does not exist: {folder}")
    required = (folder / REFERENCE_FILENAME, folder / RADIAL_FILENAME)
    if not all(path.is_file() for path in required):
        raise RadialVisualProofError("Existing proof folder is missing one of its two 3MF files")
    validate_reference_3mf(folder / REFERENCE_FILENAME)
    validate_radial_3mf(
        folder / RADIAL_FILENAME,
        expected_parts=10,
        expected_physical=PHYSICAL_HEX,
        expected_extruders=(1, 1, 1, 1, 1, 2, 2, 2, 2, 2),
        expected_process_profile=RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
    )
    _obj, _mtl, _comparison, _validation_path, validation = (
        _write_obj_import_artifacts(folder)
    )
    (folder / README_JA_FILENAME).write_text(_readme_ja(), encoding="utf-8")
    (folder / README_EN_FILENAME).write_text(_readme_en(), encoding="utf-8")
    files = sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file() and path.name != MANIFEST_FILENAME
        ),
        key=lambda path: path.name,
    )
    _write_manifest(folder, files)
    validate_manifest(folder)
    return validation


def _default_output_folder() -> Path:
    desktop = Path.home() / "Desktop"
    base = desktop / "ChromaMatter-Radial-Visual-Proof-CORRECTED-20260901"
    if not base.exists():
        return base
    for index in range(2, 1000):
        candidate = base.with_name(f"{base.name}-{index}")
        if not candidate.exists():
            return candidate
    raise RadialVisualProofError("No unused corrected Desktop output name remains")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output if args.output is not None else _default_output_folder()
    bundle = generate_radial_visual_proof_bundle(output)
    print(bundle.folder)
    print(f"reference_sha256={bundle.reference_validation['sha256']}")
    print(f"radial_sha256={bundle.radial_validation['sha256']}")
    print(f"obj_sha256={bundle.obj_import_validation['obj_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COLUMN_GAP_MM",
    "COLUMN_HEIGHT_MM",
    "COLUMN_SIZE_XY_MM",
    "GEOMETRY_VERSION",
    "INSPECT_Z_MM",
    "LAYER_HEIGHT_MM",
    "PHYSICAL_HEX",
    "OBJ_IMPORT_COMPARISON_FILENAME",
    "OBJ_IMPORT_FILENAME",
    "OBJ_IMPORT_MTL_FILENAME",
    "RADIAL_FILENAME",
    "REFERENCE_FILENAME",
    "REFERENCE_STATE_INDICES",
    "REFERENCE_WHITE_PERCENT",
    "RadialVisualProofBundle",
    "RadialVisualProofError",
    "SHELL_THICKNESSES_MM",
    "build_box_mesh",
    "build_box_shell_and_core",
    "build_radial_section_package",
    "augment_radial_visual_proof_bundle",
    "generate_radial_visual_proof_bundle",
    "validate_manifest",
    "validate_reference_3mf",
]
