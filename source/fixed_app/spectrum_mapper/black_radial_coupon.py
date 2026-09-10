"""Purpose-built conventional-versus-radial black visibility coupon.

The coupon is intentionally isolated from normal model conversion.  It emits
three geometrically identical 0.10 mm Snapmaker U1 projects:

* ``conventional`` keeps ChromaMatter's weak-black Ratio cadence, so black
  appears as periodic Z layers;
* ``radial Classic`` and ``radial Arachne`` use only physical F1-F4 volumes.
  Every mixed cell has a black core and a partner-colour shell whose thickness
  is the experimental value; only the wall planner differs.

Both archives remain experimental and require an Orca filament/toolpath
preview before printing.  The production Radial MVP continues to use its
separate 0.20 mm contract.
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
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import engine, mixer
from .models import ColorResult, MeshLevel, ObjAsset, PaletteSettings, PreparedGeometry
from .radial_export import (
    RADIAL_PROCESS_PROFILE_BLACK_COUPON_ARACHNE_010,
    RADIAL_PROCESS_PROFILE_BLACK_COUPON_010,
    RadialExportPackage,
    RadialExportPart,
    validate_radial_3mf,
    write_radial_3mf_atomic,
)


BLACK_RADIAL_COUPON_SCHEMA = "chromamatter.black-radial-coupon.v1"
GEOMETRY_VERSION = "multi-surface-prism-v1"
PHYSICAL_HEX = ("#121212", "#F5F5F5", "#F4CF32", "#E8A071")
PHYSICAL_LABELS = ("Black", "White", "Yellow", "Skin")
LAYER_HEIGHT_MM = 0.10
INITIAL_LAYER_HEIGHT_MM = 0.20
CELL_LENGTH_MM = 6.0
CELL_GAP_MM = 0.8
LANE_GAP_MM = 2.5
MODEL_HEIGHT_MM = 15.0
LINE_WIDTH_MM = 0.42
RADIAL_THICKNESS_MM = (None, 1.05, 0.84, 0.63, 0.42, 0.21, 0.0)
EFFECTIVE_BLACK_FRACTIONS = (0.0, 0.05, 0.10, 1.0 / 7.0, 0.20, 0.25, 1.0)
STAGE_KEYS = (
    "partner_100",
    "black_05",
    "black_10",
    "black_14",
    "black_20",
    "black_25",
    "black_100",
)
STAGE_LABELS = (
    "Partner 100%",
    "Black 5%",
    "Black 10%",
    "Black 14.3%",
    "Black 20%",
    "Black 25%",
    "Black 100%",
)
LANE_PARTNER_SLOTS = (1, 2, 3)
SURFACE_IDS = (
    "vertical_front",
    "slope_30deg",
    "top_horizontal",
    "slope_60deg",
    "vertical_rear",
    "downward_horizontal",
    "downward_45deg",
)

_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PRODUCTION_NS = (
    "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
)
_CONVENTIONAL_STEM = "ChromaMatter_black_gradient_conventional_0p10"
_CONVENTIONAL_ARCHIVE_MEMBERS = frozenset(
    {
        "[Content_Types].xml",
        "_rels/.rels",
        "3D/3dmodel.model",
        "3D/_rels/3dmodel.model.rels",
        "3D/Objects/object_1.model",
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
        "Metadata/full_spectrum_palette.json",
        "Metadata/tripo_part_palettes.json",
        "Metadata/tripo_assembly.json",
        "Metadata/black_radial_coupon.json",
    }
)
_CONVENTIONAL_STATIC_MEMBERS = {
    "[Content_Types].xml": b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="application/octet-stream"/>
 <Default Extension="json" ContentType="application/json"/>
</Types>
''',
    "_rels/.rels": b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
''',
    "3D/_rels/3dmodel.model.rels": b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
''',
}

# Cross-section coordinates are (Y, Z).  Extrusion is along X.  Every cell
# therefore exposes vertical walls, shallow/steep slopes, a top, and two
# unsupported downward-facing probes while remaining one closed solid.
_CROSS_SECTION_YZ = np.asarray(
    [
        (0.0, 0.0),
        (0.0, 10.0),
        (8.6603, 15.0),
        (12.6603, 15.0),
        (15.5470, 10.0),
        (15.5470, 6.0),
        (12.5470, 6.0),
        (12.5470, 3.0),
        (10.5470, 1.0),
        (10.5470, 0.0),
    ],
    dtype=np.float64,
)


class BlackRadialCouponError(RuntimeError):
    """Raised when a coupon cannot be proven safe enough for slicing."""


@dataclass(frozen=True, slots=True)
class CouponStage:
    index: int
    key: str
    label: str
    effective_black_fraction: float
    radial_thickness_mm: float | None


@dataclass(frozen=True, slots=True)
class CouponMesh:
    vertices_mm: np.ndarray
    faces: np.ndarray
    face_part_ids: np.ndarray
    vertex_states: np.ndarray
    palette_indices: np.ndarray
    part_names: tuple[str, ...]
    part_keys: tuple[str, ...]
    part_face_counts: tuple[int, ...]
    part_vertex_counts: tuple[int, ...]
    part_state_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BlackRadialCouponBundle:
    folder: Path
    conventional_path: Path
    radial_path: Path
    radial_arachne_path: Path
    mapping_path: Path
    observation_path: Path
    layout_path: Path
    research_notes_path: Path
    readme_ja_path: Path
    readme_en_path: Path
    snapshot_path: Path
    conventional_validation_path: Path
    radial_validation_path: Path
    radial_arachne_validation_path: Path
    manifest_path: Path
    conventional_validation: Mapping[str, object]
    radial_validation: Mapping[str, object]
    radial_arachne_validation: Mapping[str, object]


def coupon_stages() -> tuple[CouponStage, ...]:
    return tuple(
        CouponStage(index, key, label, black, thickness)
        for index, (key, label, black, thickness) in enumerate(
            zip(
                STAGE_KEYS,
                STAGE_LABELS,
                EFFECTIVE_BLACK_FRACTIONS,
                RADIAL_THICKNESS_MM,
                strict=True,
            )
        )
    )


def _polygon_area(points: np.ndarray) -> float:
    points = np.asarray(points, dtype=np.float64)
    return 0.5 * float(
        np.sum(
            points[:, 0] * np.roll(points[:, 1], -1)
            - np.roll(points[:, 0], -1) * points[:, 1]
        )
    )


def _ccw_polygon(points: np.ndarray) -> np.ndarray:
    result = np.asarray(points, dtype=np.float64)
    if result.ndim != 2 or result.shape[1:] != (2,) or len(result) < 3:
        raise BlackRadialCouponError("Coupon cross-section is invalid")
    if _polygon_area(result) < 0.0:
        result = result[::-1].copy()
    if _polygon_area(result) <= 1.0e-9:
        raise BlackRadialCouponError("Coupon cross-section has no positive area")
    return result


def _cross2(left: np.ndarray, right: np.ndarray) -> float:
    return float(left[0] * right[1] - left[1] * right[0])


def _point_in_triangle(
    point: np.ndarray,
    first: np.ndarray,
    second: np.ndarray,
    third: np.ndarray,
    *,
    tolerance: float = 1.0e-10,
) -> bool:
    a = _cross2(second - first, point - first)
    b = _cross2(third - second, point - second)
    c = _cross2(first - third, point - third)
    return a >= -tolerance and b >= -tolerance and c >= -tolerance


def _triangulate_polygon(points: np.ndarray) -> np.ndarray:
    polygon = _ccw_polygon(points)
    remaining = list(range(len(polygon)))
    triangles: list[tuple[int, int, int]] = []
    guard = len(remaining) ** 2
    while len(remaining) > 3 and guard > 0:
        guard -= 1
        ear_found = False
        for position, current in enumerate(remaining):
            previous = remaining[position - 1]
            following = remaining[(position + 1) % len(remaining)]
            a, b, c = polygon[[previous, current, following]]
            if _cross2(b - a, c - b) <= 1.0e-10:
                continue
            if any(
                _point_in_triangle(polygon[candidate], a, b, c)
                for candidate in remaining
                if candidate not in {previous, current, following}
            ):
                continue
            triangles.append((previous, current, following))
            del remaining[position]
            ear_found = True
            break
        if not ear_found:
            break
    if len(remaining) == 3:
        triangles.append(tuple(remaining))
    if len(triangles) != len(polygon) - 2:
        raise BlackRadialCouponError("Coupon cross-section triangulation failed")
    return np.asarray(triangles, dtype=np.int32)


def _segments_intersect(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    d: np.ndarray,
) -> bool:
    def orient(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> float:
        return _cross2(q - p, r - p)

    values = (orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b))
    return values[0] * values[1] < -1.0e-10 and values[2] * values[3] < -1.0e-10


def _assert_simple_polygon(points: np.ndarray) -> None:
    count = len(points)
    for first in range(count):
        a = points[first]
        b = points[(first + 1) % count]
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count}:
                continue
            if first == 0 and second == count - 1:
                continue
            c = points[second]
            d = points[(second + 1) % count]
            if _segments_intersect(a, b, c, d):
                raise BlackRadialCouponError("Offset coupon shell self-intersects")


def _offset_polygon_inward(points: np.ndarray, distance_mm: float) -> np.ndarray:
    polygon = _ccw_polygon(points)
    distance = float(distance_mm)
    if not math.isfinite(distance) or distance <= 0.0:
        raise BlackRadialCouponError("Radial shell thickness must be positive")
    output: list[np.ndarray] = []
    for index in range(len(polygon)):
        previous = polygon[index - 1]
        current = polygon[index]
        following = polygon[(index + 1) % len(polygon)]
        previous_direction = current - previous
        next_direction = following - current
        previous_length = float(np.linalg.norm(previous_direction))
        next_length = float(np.linalg.norm(next_direction))
        if previous_length <= 1.0e-9 or next_length <= 1.0e-9:
            raise BlackRadialCouponError("Coupon polygon repeats a vertex")
        previous_normal = np.asarray(
            (-previous_direction[1], previous_direction[0]), dtype=np.float64
        ) / previous_length
        next_normal = np.asarray(
            (-next_direction[1], next_direction[0]), dtype=np.float64
        ) / next_length
        first_origin = previous + distance * previous_normal
        second_origin = current + distance * next_normal
        denominator = _cross2(previous_direction, next_direction)
        if abs(denominator) <= 1.0e-10:
            raise BlackRadialCouponError("Coupon polygon contains a parallel corner")
        parameter = _cross2(second_origin - first_origin, next_direction) / denominator
        output.append(first_origin + parameter * previous_direction)
    result = np.asarray(output, dtype=np.float64)
    _assert_simple_polygon(result)
    if _polygon_area(result) <= 1.0e-6:
        raise BlackRadialCouponError("Radial shell consumes the coupon core")
    return result


def _signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    triangles = np.asarray(vertices, dtype=np.float64)[np.asarray(faces, dtype=np.int64)]
    return float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )


def build_coupon_cell_mesh(
    x0_mm: float,
    x1_mm: float,
    y_offset_mm: float,
    *,
    inset_mm: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Build one outward, closed coupon prism or its exact inset core."""

    inset = float(inset_mm)
    if inset < 0.0 or not math.isfinite(inset):
        raise BlackRadialCouponError("Coupon inset must be finite and non-negative")
    if inset * 2.0 >= float(x1_mm) - float(x0_mm):
        raise BlackRadialCouponError("Coupon inset removes the X core")
    polygon = _ccw_polygon(_CROSS_SECTION_YZ)
    if inset > 0.0:
        polygon = _offset_polygon_inward(polygon, inset)
    polygon = polygon.copy()
    polygon[:, 0] += float(y_offset_mm)
    x0 = float(x0_mm) + inset
    x1 = float(x1_mm) - inset
    triangulation = _triangulate_polygon(polygon)
    count = len(polygon)
    vertices = np.vstack(
        (
            np.column_stack((np.full(count, x0), polygon)),
            np.column_stack((np.full(count, x1), polygon)),
        )
    ).astype(np.float64, copy=False)
    faces: list[tuple[int, int, int]] = []
    for first, second, third in triangulation:
        faces.append((int(third), int(second), int(first)))
        faces.append((count + int(first), count + int(second), count + int(third)))
    for index in range(count):
        following = (index + 1) % count
        faces.append((index, following, count + following))
        faces.append((index, count + following, count + index))
    result_faces = np.asarray(faces, dtype=np.int32)
    volume = _signed_volume(vertices, result_faces)
    if volume < 0.0:
        result_faces = result_faces[:, [0, 2, 1]]
        volume = -volume
    if volume <= 1.0e-9:
        raise BlackRadialCouponError("Coupon cell has no positive volume")
    return vertices, result_faces


def _hollow_shell_mesh(
    x0_mm: float,
    x1_mm: float,
    y_offset_mm: float,
    thickness_mm: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    outer_vertices, outer_faces = build_coupon_cell_mesh(
        x0_mm, x1_mm, y_offset_mm
    )
    core_vertices, core_faces = build_coupon_cell_mesh(
        x0_mm, x1_mm, y_offset_mm, inset_mm=thickness_mm
    )
    shell_vertices = np.vstack((outer_vertices, core_vertices))
    shell_faces = np.vstack(
        (
            outer_faces,
            core_faces[:, [0, 2, 1]] + len(outer_vertices),
        )
    ).astype(np.int32, copy=False)
    outer_volume = _signed_volume(outer_vertices, outer_faces)
    core_volume = _signed_volume(core_vertices, core_faces)
    shell_volume = _signed_volume(shell_vertices, shell_faces)
    if min(outer_volume, core_volume, shell_volume) <= 1.0e-9:
        raise BlackRadialCouponError("Coupon shell/core volume is not positive")
    if not math.isclose(
        shell_volume + core_volume,
        outer_volume,
        rel_tol=0.0,
        abs_tol=max(1.0e-7, outer_volume * 1.0e-10),
    ):
        raise BlackRadialCouponError("Coupon shell/core volume is not conserved")
    return shell_vertices, shell_faces, core_vertices, core_faces


def _state_for_black_target(partner_slot: int, target_black_percent: int) -> int:
    if partner_slot not in LANE_PARTNER_SLOTS:
        raise BlackRadialCouponError("Coupon partner must be F2, F3, or F4")
    requested_partner = 100 - int(target_black_percent)
    matches = [
        index + 4
        for index, (left, right, ratio_b) in enumerate(mixer.palette_mix_specs())
        if left == 0 and right == partner_slot and int(ratio_b) == requested_partner
    ]
    if len(matches) != 1:
        raise BlackRadialCouponError(
            f"No stable palette state for F1+F{partner_slot + 1} "
            f"with target black {target_black_percent}%"
        )
    return matches[0]


def _conventional_state_indices(partner_slot: int) -> tuple[int, ...]:
    return (
        partner_slot,
        _state_for_black_target(partner_slot, 25),
        _state_for_black_target(partner_slot, 33),
        _state_for_black_target(partner_slot, 50),
        _state_for_black_target(partner_slot, 67),
        _state_for_black_target(partner_slot, 75),
        0,
    )


def _cell_origin(stage_index: int, lane_index: int) -> tuple[float, float, float]:
    x0 = stage_index * (CELL_LENGTH_MM + CELL_GAP_MM)
    y_step = float(np.ptp(_CROSS_SECTION_YZ[:, 0])) + LANE_GAP_MM
    y0 = lane_index * y_step
    return x0, x0 + CELL_LENGTH_MM, y0


def build_conventional_coupon() -> CouponMesh:
    """Build 21 independent watertight cells with stable paint state IDs."""

    vertices_out: list[np.ndarray] = []
    faces_out: list[np.ndarray] = []
    face_parts_out: list[np.ndarray] = []
    face_states_out: list[np.ndarray] = []
    vertex_states_out: list[np.ndarray] = []
    part_names: list[str] = []
    part_keys: list[str] = []
    part_face_counts: list[int] = []
    part_vertex_counts: list[int] = []
    part_state_indices: list[int] = []
    vertex_offset = 0
    part_id = 0
    for lane_index, partner_slot in enumerate(LANE_PARTNER_SLOTS):
        states = _conventional_state_indices(partner_slot)
        for stage, state in zip(coupon_stages(), states, strict=True):
            x0, x1, y0 = _cell_origin(stage.index, lane_index)
            vertices, faces = build_coupon_cell_mesh(x0, x1, y0)
            vertices_out.append(vertices)
            faces_out.append(faces + vertex_offset)
            face_parts_out.append(np.full(len(faces), part_id, dtype=np.int16))
            face_states_out.append(np.full(len(faces), state, dtype=np.int16))
            vertex_states_out.append(np.full(len(vertices), state, dtype=np.int16))
            label = PHYSICAL_LABELS[partner_slot]
            part_names.append(f"{label} - {stage.label}")
            part_keys.append(f"{label.lower()}_{stage.key}")
            part_face_counts.append(len(faces))
            part_vertex_counts.append(len(vertices))
            part_state_indices.append(state)
            vertex_offset += len(vertices)
            part_id += 1
    return CouponMesh(
        vertices_mm=np.vstack(vertices_out),
        faces=np.vstack(faces_out),
        face_part_ids=np.concatenate(face_parts_out),
        vertex_states=np.concatenate(vertex_states_out),
        palette_indices=np.concatenate(face_states_out),
        part_names=tuple(part_names),
        part_keys=tuple(part_keys),
        part_face_counts=tuple(part_face_counts),
        part_vertex_counts=tuple(part_vertex_counts),
        part_state_indices=tuple(part_state_indices),
    )


def _coupon_palette() -> PaletteSettings:
    return PaletteSettings(
        material="PLA",
        palette_state_count=32,
        physical_hex=list(PHYSICAL_HEX),
        enabled_states=[True] * mixer.PALETTE_STATE_COUNT,
        mix_ratios_b=[33] * len(mixer.PAIR_INDICES),
        secondary_mix_ratios_b=[67] * len(mixer.PAIR_INDICES),
        output_mix_ratios_b=mixer.black_output_ratio_preset(0),
    )


def _prepared_coupon(
    coupon: CouponMesh,
    palette: PaletteSettings,
) -> tuple[PreparedGeometry, ColorResult]:
    _hex, palette_rgb_values = mixer.build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    palette_rgb = np.asarray(palette_rgb_values[:32], dtype=np.float64)
    vertices_unit = coupon.vertices_mm / MODEL_HEIGHT_MM
    vertex_colors = palette_rgb[coupon.vertex_states]
    areas_unit = engine.triangle_areas(vertices_unit, coupon.faces)
    level = MeshLevel(
        vertices_unit=vertices_unit,
        faces=coupon.faces,
        vertex_colors=vertex_colors,
        areas_unit=areas_unit,
        neighbors=engine.face_neighbors(coupon.faces, len(vertices_unit)),
        face_part_ids=coupon.face_part_ids,
        part_names=coupon.part_names,
        part_keys=coupon.part_keys,
        face_provenance=np.zeros(len(coupon.faces), dtype=np.uint8),
    )
    source_hash = hashlib.sha256(
        coupon.vertices_mm.tobytes() + coupon.faces.tobytes()
    ).hexdigest()
    source = ObjAsset(
        path=Path("purpose_built_black_radial_coupon.obj"),
        sha256=source_hash,
        file_size=0,
        vertices=vertices_unit.copy(),
        colors=vertex_colors.copy(),
        faces=coupon.faces.copy(),
        original_vertex_count=len(coupon.vertices_mm),
        original_face_count=len(coupon.faces),
        warnings=[],
        part_names=coupon.part_names,
        part_keys=coupon.part_keys,
        face_part_ids=coupon.face_part_ids.copy(),
        part_face_counts=coupon.part_face_counts,
        part_vertex_counts=coupon.part_vertex_counts,
        part_marker_kind="black_radial_coupon",
        has_explicit_parts=True,
    )
    area = float(areas_unit.sum())
    volume = float(
        sum(
            _signed_volume(
                coupon.vertices_mm[
                    np.unique(coupon.faces[coupon.face_part_ids == part_id])
                ],
                _local_faces(
                    coupon.faces[coupon.face_part_ids == part_id]
                )[1],
            )
            for part_id in range(len(coupon.part_names))
        )
        / MODEL_HEIGHT_MM**3
    )
    prepared = PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(coupon.vertices_mm),
        clean_face_count=len(coupon.faces),
        removed_vertices=0,
        removed_faces=0,
        topology={
            "watertight": True,
            "part_count": len(coupon.part_names),
            "purpose_built_black_radial_coupon": True,
        },
        source_area_unit=area,
        source_volume_unit=volume,
        simplified_area_unit=area,
        simplified_volume_unit=volume,
        source_dimensions_unit=np.ptp(vertices_unit, axis=0),
        warnings=[],
        part_names=coupon.part_names,
        part_keys=coupon.part_keys,
        part_stats=[
            {
                "part_id": part_id,
                "part_key": coupon.part_keys[part_id],
                "part_name": coupon.part_names[part_id],
                "vertices": coupon.part_vertex_counts[part_id],
                "faces": coupon.part_face_counts[part_id],
            }
            for part_id in range(len(coupon.part_names))
        ],
        assembly={
            "solidify_parts": True,
            "all_parts_watertight": True,
            "repair_method": "purpose_built_watertight_coupon_primitives",
            "black_radial_coupon": {
                "schema": BLACK_RADIAL_COUPON_SCHEMA,
                "method": "conventional-z-ratio",
                "geometry_version": GEOMETRY_VERSION,
            },
        },
    )
    prepared._hotfix_subtriangle_paint = {}
    face_rgb = palette_rgb[coupon.palette_indices]
    counts = np.bincount(coupon.palette_indices, minlength=32)
    areas_mm2 = areas_unit * MODEL_HEIGHT_MM**2
    by_area = np.bincount(
        coupon.palette_indices,
        weights=areas_mm2,
        minlength=32,
    )
    fractions = by_area / max(float(by_area.sum()), 1.0e-12)
    colors = ColorResult(
        tone_vertex_rgb=vertex_colors,
        source_face_rgb=face_rgb.copy(),
        palette_indices=coupon.palette_indices.copy(),
        target_face_rgb=face_rgb.copy(),
        delta_e=np.zeros(len(coupon.faces), dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=0.0,
        manual_override_faces=0,
        part_metrics=[],
    )
    return prepared, colors


def _local_faces(faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    unique, inverse = np.unique(np.asarray(faces).reshape(-1), return_inverse=True)
    return unique, inverse.reshape((-1, 3)).astype(np.int32)


def _process_settings(wall_generator: str = "classic") -> dict[str, object]:
    generator = str(wall_generator).strip().lower()
    if generator not in {"classic", "arachne"}:
        raise BlackRadialCouponError(
            f"Unsupported coupon wall generator: {wall_generator!r}"
        )
    settings: dict[str, object] = {
        "print_settings_id": "0.10 Black-Radial Validation @Snapmaker U1 (0.4 nozzle)",
        "layer_height": "0.1",
        "initial_layer_print_height": "0.2",
        "adaptive_layer_height": "0",
        "wall_loops": "2",
        "wall_generator": generator,
        "detect_thin_wall": "0",
        "only_one_wall_top": "0",
        "interface_shells": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "sparse_infill_density": "100%",
        "top_shell_layers": "5",
        "top_shell_thickness": "0.5",
        "bottom_shell_layers": "5",
        "bottom_shell_thickness": "0.5",
        "enable_support": "0",
        "support_filament": "2",
        "support_interface_filament": "2",
        "enable_prime_tower": "1",
        "flush_into_infill": "0",
        "flush_into_support": "0",
        "flush_into_objects": "0",
        "flush_multiplier": "0",
        "flush_volumes_matrix": ["0"] * 16,
        "flush_volumes_vector": ["0"] * 4,
        "brim_type": "no_brim",
        "raft_layers": "0",
        "print_sequence": "by layer",
    }
    settings.update(engine.SNAPMAKER_U1_008_TRANSITION_SETTINGS)
    if generator == "arachne":
        settings.update(
            {
                "print_settings_id": (
                    "0.10 Black-Radial Arachne Validation "
                    "@Snapmaker U1 (0.4 nozzle)"
                ),
                "inner_wall_line_width": "0.45",
                "wall_distribution_count": "1",
                "min_bead_width": "85%",
                "initial_layer_min_bead_width": "85%",
                "min_feature_size": "25%",
                "wall_transition_length": "100%",
                "wall_transition_filter_deviation": "25%",
                "wall_transition_angle": "10",
            }
        )
    return settings


def _stage_records() -> list[dict[str, object]]:
    palette = _coupon_palette()
    print_specs = mixer.print_palette_mix_specs(
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
        palette.output_mix_ratios_b,
    )
    rows: list[dict[str, object]] = []
    for lane_index, partner_slot in enumerate(LANE_PARTNER_SLOTS):
        states = _conventional_state_indices(partner_slot)
        for stage, state in zip(coupon_stages(), states, strict=True):
            if 0 < stage.index < 6:
                left, right, output_b = print_specs[state - 4]
                if (left, right) != (0, partner_slot):
                    raise BlackRadialCouponError("Coupon state pair drifted")
                effective_partner = mixer.orca_effective_mix_ratio(output_b / 100.0)
                effective_black = 1.0 - effective_partner
                cycle_layers = max(1, round(1.0 / effective_black))
                cadence = f"1 black / {cycle_layers - 1} partner"
                black_band_spacing_mm = cycle_layers * LAYER_HEIGHT_MM
                requested_output_b = int(output_b)
            elif stage.index == 0:
                effective_black = 0.0
                cadence = "partner only"
                black_band_spacing_mm = None
                requested_output_b = 100
            else:
                effective_black = 1.0
                cadence = "black only"
                black_band_spacing_mm = LAYER_HEIGHT_MM
                requested_output_b = 0
            x0, x1, y0 = _cell_origin(stage.index, lane_index)
            rows.append(
                {
                    "lane_index": lane_index,
                    "lane": PHYSICAL_LABELS[partner_slot],
                    "partner_slot": partner_slot + 1,
                    "stage_index": stage.index,
                    "stage_key": stage.key,
                    "stage_label": stage.label,
                    "conventional_state_id": state + 1,
                    "requested_partner_percent": requested_output_b,
                    "effective_black_percent": round(effective_black * 100.0, 4),
                    "cadence": cadence,
                    "predicted_black_band_spacing_mm": black_band_spacing_mm,
                    "radial_shell_thickness_mm": stage.radial_thickness_mm,
                    "radial_shell_line_width_multiple": (
                        None
                        if stage.radial_thickness_mm is None
                        else round(stage.radial_thickness_mm / LINE_WIDTH_MM, 3)
                    ),
                    "cell_bounds_mm": [
                        round(x0, 4),
                        round(x1, 4),
                        round(y0, 4),
                        round(y0 + float(np.ptp(_CROSS_SECTION_YZ[:, 0])), 4),
                        0.0,
                        MODEL_HEIGHT_MM,
                    ],
                    "surface_ids": list(SURFACE_IDS),
                }
            )
    return rows


def _coupon_metadata(
    method: str,
    *,
    wall_generator: str = "classic",
) -> dict[str, object]:
    return {
        "schema": BLACK_RADIAL_COUPON_SCHEMA,
        "method": method,
        "geometry_version": GEOMETRY_VERSION,
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "calibrated": False,
        "physical_slots": [
            {"slot": index + 1, "label": label, "hex": color}
            for index, (label, color) in enumerate(
                zip(PHYSICAL_LABELS, PHYSICAL_HEX, strict=True)
            )
        ],
        "process": _process_settings(wall_generator),
        "dimensions_mm": [
            6 * (CELL_LENGTH_MM + CELL_GAP_MM) + CELL_LENGTH_MM,
            3 * float(np.ptp(_CROSS_SECTION_YZ[:, 0])) + 2 * LANE_GAP_MM,
            MODEL_HEIGHT_MM,
        ],
        "surfaces": list(SURFACE_IDS),
        "cells": _stage_records(),
        "radial_semantics": {
            "control_variable": "physical partner shell thickness",
            "pure_black_is_preserved": True,
            "mixed_black_is_core_only": True,
            "outer_surface_material": "partner physical filament",
            "thin_shell_probe_mm": 0.21,
            "practical_candidate_min_mm": 0.42,
            "wall_generator": str(wall_generator).strip().lower(),
        },
    }


def _rewrite_zip_members(
    path: Path,
    replacements: Mapping[str, bytes],
) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as destination:
            existing = set()
            for info in source.infolist():
                existing.add(info.filename)
                payload = replacements.get(info.filename, source.read(info.filename))
                destination.writestr(info, payload)
            for name, payload in replacements.items():
                if name not in existing:
                    destination.writestr(name, payload)
        with zipfile.ZipFile(temporary, "r") as reopened:
            if reopened.testzip() is not None:
                raise BlackRadialCouponError("Patched coupon 3MF has a CRC failure")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_conventional_3mf(path: Path) -> dict[str, object]:
    coupon = build_conventional_coupon()
    palette = _coupon_palette()
    prepared, colors = _prepared_coupon(coupon, palette)
    # The deterministic coupon uses the core archive contract, not the
    # runtime adapter's extra GUI metadata. Keep its strict reopen allowlist
    # identical whether or not an application hotfix was imported earlier.
    engine._CORE_WRITE_3MF_ATOMIC(
        path,
        prepared,
        colors,
        MODEL_HEIGHT_MM,
        palette,
        part_palettes=None,
        print_uses_global_palette=True,
    )
    with zipfile.ZipFile(path, "r") as archive:
        project = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
    project.update(_process_settings())
    metadata = _coupon_metadata("conventional-z-ratio")
    _rewrite_zip_members(
        path,
        {
            "Metadata/project_settings.config": json.dumps(
                project, ensure_ascii=False, indent=2
            ).encode("utf-8"),
            "Metadata/black_radial_coupon.json": json.dumps(
                metadata, ensure_ascii=False, indent=2
            ).encode("utf-8"),
        },
    )
    return validate_black_radial_coupon_3mf(path, method="conventional-z-ratio")


def build_radial_coupon(
    *,
    wall_generator: str = "classic",
) -> RadialExportPackage:
    """Build the physical-volume counterpart with exact core/shell contact."""

    generator = str(wall_generator).strip().lower()
    if generator not in {"classic", "arachne"}:
        raise BlackRadialCouponError(
            f"Unsupported coupon wall generator: {wall_generator!r}"
        )
    method = (
        "radial-physical-thickness-arachne"
        if generator == "arachne"
        else "radial-physical-thickness"
    )
    process_profile = (
        RADIAL_PROCESS_PROFILE_BLACK_COUPON_ARACHNE_010
        if generator == "arachne"
        else RADIAL_PROCESS_PROFILE_BLACK_COUPON_010
    )

    cores: list[RadialExportPart] = []
    shells: list[RadialExportPart] = []
    interface_records: list[dict[str, object]] = []
    for lane_index, partner_slot in enumerate(LANE_PARTNER_SLOTS):
        states = _conventional_state_indices(partner_slot)
        for stage, source_state in zip(coupon_stages(), states, strict=True):
            x0, x1, y0 = _cell_origin(stage.index, lane_index)
            lane = PHYSICAL_LABELS[partner_slot]
            common = {
                "lane": lane,
                "stage": stage.key,
                "cell_index": lane_index * len(STAGE_KEYS) + stage.index,
                "source_conventional_state": source_state + 1,
                "effective_black_percent": stage.effective_black_fraction * 100.0,
            }
            if stage.index == 0:
                vertices, faces = build_coupon_cell_mesh(x0, x1, y0)
                shells.append(
                    RadialExportPart(
                        name=f"{lane} - {stage.label}",
                        role="partner_outer_shell",
                        vertices_mm=vertices,
                        faces=faces,
                        extruder=partner_slot + 1,
                        source_state=source_state + 1,
                        metadata={**common, "pure_partner_control": True},
                    )
                )
                continue
            if stage.index == len(STAGE_KEYS) - 1:
                vertices, faces = build_coupon_cell_mesh(x0, x1, y0)
                cores.append(
                    RadialExportPart(
                        name=f"{lane} - {stage.label}",
                        role="pure_black_core",
                        vertices_mm=vertices,
                        faces=faces,
                        extruder=1,
                        source_state=1,
                        metadata={**common, "pure_black_control": True},
                    )
                )
                continue
            thickness = float(stage.radial_thickness_mm or 0.0)
            shell_vertices, shell_faces, core_vertices, core_faces = _hollow_shell_mesh(
                x0, x1, y0, thickness
            )
            cores.append(
                RadialExportPart(
                    name=f"{lane} {stage.label} - black core",
                    role="pure_black_core",
                    vertices_mm=core_vertices,
                    faces=core_faces,
                    extruder=1,
                    source_state=source_state + 1,
                    metadata={**common, "shell_thickness_mm": thickness},
                )
            )
            shells.append(
                RadialExportPart(
                    name=f"{lane} {stage.label} - partner shell",
                    role="partner_outer_shell",
                    vertices_mm=shell_vertices,
                    faces=shell_faces,
                    extruder=partner_slot + 1,
                    source_state=source_state + 1,
                    metadata={**common, "shell_thickness_mm": thickness},
                )
            )
            interface_records.append(
                {
                    "lane": lane,
                    "stage": stage.key,
                    "shell_thickness_mm": thickness,
                    "exact_coordinate_triangles": True,
                    "opposite_winding": True,
                    "gap_mm": 0.0,
                    "positive_overlap_mm3": 0.0,
                    "volume_conserved": True,
                }
            )
    metadata = _coupon_metadata(method, wall_generator=generator)
    metadata.update(
        {
            "physical_materials_only": True,
            "legacy_fullspectrum_ratios_used": False,
            "ratio_definitions": 0,
            "cycle_definitions": 0,
            "virtual_mix_definitions": 0,
            "painted_triangles": 0,
            "positive_overlap_mm3": 0.0,
            "gap_mm": 0.0,
            "shared_interface_partition_exact": True,
            "external_surface_coverage_exact": True,
            "unsafe_columns_outer_only_verified": True,
            "interfaces": interface_records,
        }
    )
    return RadialExportPackage(
        parts=tuple(cores + shells),
        physical_hex=PHYSICAL_HEX,
        black_extruder=1,
        metadata={"black_radial_coupon": metadata},
        layer_height_mm=LAYER_HEIGHT_MM,
        initial_layer_height_mm=INITIAL_LAYER_HEIGHT_MM,
        renderer="radial",
        process_profile=process_profile,
    )


def _write_radial_3mf(
    path: Path,
    *,
    wall_generator: str = "classic",
) -> dict[str, object]:
    generator = str(wall_generator).strip().lower()
    package = build_radial_coupon(wall_generator=generator)
    method = (
        "radial-physical-thickness-arachne"
        if generator == "arachne"
        else "radial-physical-thickness"
    )
    write_radial_3mf_atomic(
        path,
        package,
        title=f"black gradient radial thickness coupon 0.10 mm {generator}",
    )
    return validate_black_radial_coupon_3mf(
        path,
        method=method,
    )


def _read_project(archive: zipfile.ZipFile) -> dict[str, object]:
    return json.loads(
        archive.read("Metadata/project_settings.config").decode("utf-8")
    )


def _validate_process(
    project: Mapping[str, object],
    *,
    wall_generator: str = "classic",
) -> None:
    for key, expected in _process_settings(wall_generator).items():
        actual = project.get(key)
        if actual != expected:
            raise BlackRadialCouponError(
                f"Coupon process setting {key} drifted: {actual!r} != {expected!r}"
            )


def _validate_conventional_archive(
    path: Path,
    archive: zipfile.ZipFile,
    metadata: Mapping[str, object],
) -> dict[str, object]:
    member_names = archive.namelist()
    if len(member_names) != len(set(member_names)):
        raise BlackRadialCouponError(
            "Conventional coupon contains duplicate ZIP members"
        )
    names = set(member_names)
    missing = sorted(_CONVENTIONAL_ARCHIVE_MEMBERS - names)
    unexpected = sorted(names - _CONVENTIONAL_ARCHIVE_MEMBERS)
    if missing:
        raise BlackRadialCouponError(
            f"Conventional coupon archive is incomplete: {missing}"
        )
    if unexpected:
        raise BlackRadialCouponError(
            f"Conventional coupon has unvalidated archive members: {unexpected}"
        )
    for name, expected in _CONVENTIONAL_STATIC_MEMBERS.items():
        if archive.read(name) != expected:
            raise BlackRadialCouponError(
                f"Conventional archive relationship drifted: {name}"
            )
    expected_coupon_metadata = _coupon_metadata("conventional-z-ratio")
    if dict(metadata) != expected_coupon_metadata:
        raise BlackRadialCouponError(
            "Conventional coupon metadata differs from the deterministic plan"
        )
    project = _read_project(archive)
    _validate_process(project)
    if project.get("filament_colour") != list(PHYSICAL_HEX):
        raise BlackRadialCouponError("Conventional physical filament colours drifted")
    if project.get("filament_multi_colors") != list(PHYSICAL_HEX):
        raise BlackRadialCouponError(
            "Conventional physical multi-colour entries drifted"
        )
    definitions = str(project.get("mixed_filament_definitions", ""))
    if not definitions or "cm1" in definitions:
        raise BlackRadialCouponError("Conventional coupon must use Ratio definitions only")
    palette = _coupon_palette()
    expected_definitions = engine.make_portable_mixed_definitions(
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
        palette_state_count=palette.palette_state_count,
        output_mix_ratios_b=palette.output_mix_ratios_b,
    )
    if definitions != expected_definitions:
        raise BlackRadialCouponError(
            "Conventional coupon Ratio definitions are not canonical"
        )
    expected_project: dict[str, object] = {
        "print_settings_id": "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)",
        "printer_settings_id": "Snapmaker U1 (0.4 nozzle)",
        "printer_model": "Snapmaker U1",
        "printer_variant": "0.4",
        "nozzle_diameter": ["0.4"] * 4,
        "layer_height": "0.08",
        "initial_layer_print_height": "0.2",
        "adaptive_layer_height": "0",
        "filament_colour": list(PHYSICAL_HEX),
        "filament_multi_colors": list(PHYSICAL_HEX),
        "filament_colour_mode": ["0"] * 4,
        "filament_settings_id": [engine.generic_filament_profile("PLA")] * 4,
        "mixed_filament_definitions": expected_definitions,
        "mixed_filament_height_lower_bound": "0.04",
        "mixed_filament_height_upper_bound": "0.16",
        "chroma_matter_palette_mode": palette.color_mode,
    }
    expected_project.update(engine.FULL_SPECTRUM_STABLE_CADENCE_SETTINGS)
    expected_project.update(_process_settings())
    if set(project) != set(expected_project):
        raise BlackRadialCouponError(
            "Conventional project-setting allowlist drifted"
        )
    for key, expected in expected_project.items():
        if project.get(key) != expected:
            raise BlackRadialCouponError(
                f"Conventional project setting {key} drifted"
            )
    definition_rows = definitions.split(";")
    print_specs = mixer.print_palette_mix_specs(
        [33] * len(mixer.PAIR_INDICES),
        [67] * len(mixer.PAIR_INDICES),
        mixer.black_output_ratio_preset(0),
    )
    expected_cells = list(expected_coupon_metadata["cells"])
    if len(expected_cells) != 21:
        raise BlackRadialCouponError("Conventional coupon metadata needs 21 cells")
    object_root = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    if object_root.tag != f"{{{_CORE_NS}}}model":
        raise BlackRadialCouponError(
            "Conventional child root is not a 3MF model"
        )
    if object_root.attrib.get("unit") != "millimeter":
        raise BlackRadialCouponError("Conventional child-model unit drifted")
    expected_model_attributes = {
        "unit": "millimeter",
        "{http://www.w3.org/XML/1998/namespace}lang": "en-US",
        "requiredextensions": "p",
    }
    if object_root.attrib != expected_model_attributes:
        raise BlackRadialCouponError(
            "Conventional child-model contract drifted"
        )
    child_metadata = object_root.findall(f"{{{_CORE_NS}}}metadata")
    child_resources = object_root.findall(f"{{{_CORE_NS}}}resources")
    if (
        len(child_metadata) != 1
        or child_metadata[0].attrib != {"name": "BambuStudio:3mfVersion"}
        or (child_metadata[0].text or "") != "1"
        or len(child_resources) != 1
        or child_resources[0].attrib
        or list(object_root) != [child_metadata[0], child_resources[0]]
    ):
        raise BlackRadialCouponError(
            "Conventional child-model structure drifted"
        )
    objects = child_resources[0].findall(f"{{{_CORE_NS}}}object")
    if list(child_resources[0]) != objects:
        raise BlackRadialCouponError(
            "Conventional child resources contain an unknown element"
        )
    if len(objects) != 21:
        raise BlackRadialCouponError("Conventional coupon must contain 21 objects")
    observed_states: list[int] = []
    topology_ok = 0
    coupon = build_conventional_coupon()
    for part_index, (obj, cell) in enumerate(
        zip(objects, expected_cells, strict=True)
    ):
        if set(obj.attrib) != {
            "id",
            f"{{{_PRODUCTION_NS}}}UUID",
            "name",
            "type",
        }:
            raise BlackRadialCouponError(
                "A conventional mesh-object attribute drifted"
            )
        if int(obj.attrib.get("id", "0")) != part_index + 1:
            raise BlackRadialCouponError(
                "Conventional mesh-object IDs are not deterministic"
            )
        if obj.attrib.get("type") != "model":
            raise BlackRadialCouponError(
                "A conventional coupon object is not a printable model"
            )
        if obj.attrib.get("name") != coupon.part_names[part_index]:
            raise BlackRadialCouponError("Conventional coupon part names drifted")
        meshes = obj.findall(f"{{{_CORE_NS}}}mesh")
        if len(meshes) != 1 or list(obj) != meshes or meshes[0].attrib:
            raise BlackRadialCouponError(
                "A conventional object must contain exactly one mesh"
            )
        mesh = meshes[0]
        vertex_containers = mesh.findall(f"{{{_CORE_NS}}}vertices")
        triangle_containers = mesh.findall(f"{{{_CORE_NS}}}triangles")
        if (
            len(vertex_containers) != 1
            or len(triangle_containers) != 1
            or list(mesh) != [vertex_containers[0], triangle_containers[0]]
            or vertex_containers[0].attrib
            or triangle_containers[0].attrib
        ):
            raise BlackRadialCouponError(
                "A conventional mesh structure drifted"
            )
        vertex_elements = vertex_containers[0].findall(
            f"{{{_CORE_NS}}}vertex"
        )
        triangles = triangle_containers[0].findall(
            f"{{{_CORE_NS}}}triangle"
        )
        if (
            list(vertex_containers[0]) != vertex_elements
            or list(triangle_containers[0]) != triangles
        ):
            raise BlackRadialCouponError(
                "A conventional mesh container has an unknown element"
            )
        vertices = [
            [float(item.attrib[axis]) for axis in ("x", "y", "z")]
            for item in vertex_elements
        ]
        if any(
            set(item.attrib) != {"x", "y", "z"}
            for item in vertex_elements
        ):
            raise BlackRadialCouponError(
                "A conventional vertex attribute drifted"
            )
        if any(
            set(item.attrib) != {"v1", "v2", "v3", "paint_color"}
            for item in triangles
        ):
            raise BlackRadialCouponError(
                "A conventional triangle property drifted"
            )
        paint_codes = {item.attrib.get("paint_color", "") for item in triangles}
        if len(paint_codes) != 1:
            raise BlackRadialCouponError("A conventional cell is not uniformly painted")
        paint_code = next(iter(paint_codes)).upper()
        if paint_code not in engine.PAINT_CODES:
            raise BlackRadialCouponError("A conventional cell has an unknown paint state")
        state = engine.PAINT_CODES.index(paint_code) + 1
        deterministic_state = int(coupon.part_state_indices[part_index]) + 1
        if state != deterministic_state:
            raise BlackRadialCouponError("Conventional paint state order drifted")
        if state != int(cell["conventional_state_id"]):
            raise BlackRadialCouponError(
                "Conventional paint state disagrees with canonical coupon metadata"
            )
        observed_states.append(state)
        faces = np.asarray(
            [
                [int(item.attrib[key]) for key in ("v1", "v2", "v3")]
                for item in triangles
            ],
            dtype=np.int32,
        )
        selected_faces = np.flatnonzero(coupon.face_part_ids == part_index)
        source_faces = np.asarray(coupon.faces[selected_faces], dtype=np.int32)
        used_vertices = np.unique(source_faces.reshape(-1))
        expected_vertices = np.asarray(
            coupon.vertices_mm[used_vertices],
            dtype=np.float64,
        )
        expected_faces = np.searchsorted(used_vertices, source_faces).astype(np.int32)
        observed_vertices = np.asarray(vertices, dtype=np.float64)
        if observed_vertices.shape != expected_vertices.shape or not np.allclose(
            observed_vertices,
            expected_vertices,
            rtol=0.0,
            atol=1.0e-8,
        ):
            raise BlackRadialCouponError(
                "Serialized conventional coupon vertices drifted"
            )
        if not np.array_equal(faces, expected_faces):
            raise BlackRadialCouponError(
                "Serialized conventional coupon triangles drifted"
            )
        quality = engine.mesh_quality(
            np.asarray(vertices, dtype=np.float64),
            faces,
            check_self_intersections=True,
        )
        if not bool(
            quality.get("watertight")
            and quality.get("winding_consistent")
            and quality.get("positive_volume")
            and int(quality.get("body_count", 0) or 0) == 1
            and int(quality.get("degenerate_faces", -1)) == 0
            and int(quality.get("self_intersecting_faces", -1)) == 0
        ):
            raise BlackRadialCouponError("A conventional coupon cell is not a valid solid")
        topology_ok += 1
        if 5 <= state <= 32:
            left, right, ratio_b = print_specs[state - 5]
            row = definition_rows[state - 5].split(",")
            if len(row) < 10:
                raise BlackRadialCouponError("A conventional Ratio row is malformed")
            if [int(row[0]), int(row[1]), int(row[4])] != [
                left + 1,
                right + 1,
                int(ratio_b),
            ]:
                raise BlackRadialCouponError("Conventional Ratio recipe drifted")
    root_model = ET.fromstring(archive.read("3D/3dmodel.model"))
    if root_model.tag != f"{{{_CORE_NS}}}model":
        raise BlackRadialCouponError(
            "Conventional root element is not a 3MF model"
        )
    if root_model.attrib.get("unit") != "millimeter":
        raise BlackRadialCouponError("Conventional root-model unit drifted")
    if root_model.attrib != expected_model_attributes:
        raise BlackRadialCouponError("Conventional root-model contract drifted")
    production_uuid_key = f"{{{_PRODUCTION_NS}}}UUID"
    production_uuids: list[str] = []
    for model_root in (root_model, object_root):
        for element in model_root.iter():
            if production_uuid_key not in element.attrib:
                continue
            value = element.attrib[production_uuid_key]
            try:
                parsed = uuid.UUID(value)
            except (AttributeError, TypeError, ValueError) as exc:
                raise BlackRadialCouponError(
                    "A conventional Production UUID is malformed"
                ) from exc
            if str(parsed) != value:
                raise BlackRadialCouponError(
                    "A conventional Production UUID is not canonical lowercase text"
                )
            production_uuids.append(value)
    if not production_uuids or len(production_uuids) != len(set(production_uuids)):
        raise BlackRadialCouponError(
            "Conventional Production UUIDs are missing or duplicated"
        )
    root_metadata = root_model.findall(f"{{{_CORE_NS}}}metadata")
    if any(item.attrib != {"name": item.attrib.get("name", "")} for item in root_metadata):
        raise BlackRadialCouponError("Conventional root metadata attributes drifted")
    metadata_by_name = {
        item.attrib.get("name", ""): item.text or "" for item in root_metadata
    }
    if len(root_metadata) != 6 or len(metadata_by_name) != 6:
        raise BlackRadialCouponError("Conventional root metadata drifted")
    expected_root_metadata = {
        "Application": "BambuStudio-2.3.5",
        "BambuStudio:3mfVersion": "1",
        "Title": _CONVENTIONAL_STEM,
        "Description": "Full Spectrum 32 colors, height 15 mm",
    }
    if any(
        metadata_by_name.get(key) != value
        for key, value in expected_root_metadata.items()
    ) or set(metadata_by_name) != {
        *expected_root_metadata,
        "CreationDate",
        "ModificationDate",
    }:
        raise BlackRadialCouponError("Conventional root metadata values drifted")
    resources = root_model.findall(f"{{{_CORE_NS}}}resources")
    builds = root_model.findall(f"{{{_CORE_NS}}}build")
    if (
        len(resources) != 1
        or len(builds) != 1
        or resources[0].attrib
        or list(root_model) != root_metadata + [resources[0], builds[0]]
    ):
        raise BlackRadialCouponError("Conventional root structure drifted")
    parent_objects = resources[0].findall(f"{{{_CORE_NS}}}object")
    if len(parent_objects) != 1:
        raise BlackRadialCouponError("Conventional root object count drifted")
    parent = parent_objects[0]
    if set(parent.attrib) != {
        "id",
        f"{{{_PRODUCTION_NS}}}UUID",
        "type",
    } or parent.attrib.get("id") != "22" or parent.attrib.get("type") != "model":
        raise BlackRadialCouponError("Conventional root object drifted")
    component_containers = parent.findall(f"{{{_CORE_NS}}}components")
    if (
        len(component_containers) != 1
        or list(parent) != component_containers
        or component_containers[0].attrib
    ):
        raise BlackRadialCouponError(
            "Conventional root component structure drifted"
        )
    if set(builds[0].attrib) != {production_uuid_key}:
        raise BlackRadialCouponError("Conventional build attributes drifted")
    build_items = builds[0].findall(f"{{{_CORE_NS}}}item")
    expected_build_item_keys = {
        "objectid",
        f"{{{_PRODUCTION_NS}}}UUID",
        "transform",
        "printable",
    }
    if (
        len(build_items) != 1
        or list(builds[0]) != build_items
        or set(build_items[0].attrib) != expected_build_item_keys
        or build_items[0].attrib.get("objectid") != "22"
        or build_items[0].attrib.get("transform") != (
        "1 0 0 0 1 0 0 0 1 128 128 0"
        )
    ):
        raise BlackRadialCouponError("Conventional build transform drifted")
    if build_items[0].attrib.get("printable") != "1":
        raise BlackRadialCouponError("Conventional build item is not sliceable")
    components = component_containers[0].findall(f"{{{_CORE_NS}}}component")
    if list(component_containers[0]) != components:
        raise BlackRadialCouponError(
            "Conventional component container has an unknown element"
        )
    if len(components) != 21 or [
        int(item.attrib.get("objectid", "0")) for item in components
    ] != list(range(1, 22)):
        raise BlackRadialCouponError("Conventional component order drifted")
    if any(
        set(item.attrib)
        != {
            f"{{{_PRODUCTION_NS}}}path",
            "objectid",
            f"{{{_PRODUCTION_NS}}}UUID",
            "transform",
        }
        or item.attrib.get(f"{{{_PRODUCTION_NS}}}path")
        != "/3D/Objects/object_1.model"
        or item.attrib.get("transform")
        != "1 0 0 0 1 0 0 0 1 0 0 0"
        for item in components
    ):
        raise BlackRadialCouponError(
            "Conventional component target or transform drifted"
        )
    model_settings = ET.fromstring(
        archive.read("Metadata/model_settings.config")
    )
    if model_settings.tag != "config" or model_settings.attrib:
        raise BlackRadialCouponError("Conventional model-settings root drifted")
    config_objects = model_settings.findall("object")
    plates = model_settings.findall("plate")
    if (
        len(config_objects) != 1
        or len(plates) != 1
        or [item.tag for item in list(model_settings)] != ["object", "plate"]
    ):
        raise BlackRadialCouponError("Conventional model-settings structure drifted")
    config_object = config_objects[0]
    if config_object.attrib != {"id": "22"}:
        raise BlackRadialCouponError("Conventional model-settings object ID drifted")
    object_metadata = config_object.findall("metadata")
    object_keyed = [item for item in object_metadata if "key" in item.attrib]
    object_unkeyed = [item for item in object_metadata if "key" not in item.attrib]
    if (
        len(object_metadata) != 3
        or any(set(item.attrib) != {"key", "value"} for item in object_keyed)
        or {
            item.attrib["key"]: item.attrib["value"] for item in object_keyed
        }
        != {"name": _CONVENTIONAL_STEM, "extruder": "1"}
        or [item.attrib for item in object_unkeyed]
        != [{"face_count": str(len(coupon.faces))}]
    ):
        raise BlackRadialCouponError(
            "Conventional model-settings object metadata drifted"
        )
    configured_parts = config_object.findall("part")
    if len(configured_parts) != 21:
        raise BlackRadialCouponError("Conventional model-settings count drifted")
    for part_index, part in enumerate(configured_parts):
        if part.attrib != {
            "id": str(part_index + 1),
            "subtype": "normal_part",
        }:
            raise BlackRadialCouponError(
                "Conventional model-settings part ID or subtype drifted"
            )
        metadata_items = [
            item for item in part.findall("metadata") if "key" in item.attrib
        ]
        metadata_keys = [str(item.attrib["key"]) for item in metadata_items]
        expected_keys = {
            "name",
            "matrix",
            "source_file",
            "source_object_id",
            "source_volume_id",
            "source_offset_x",
            "source_offset_y",
            "source_offset_z",
            "extruder",
        }
        if (
            len(metadata_keys) != len(set(metadata_keys))
            or set(metadata_keys) != expected_keys
            or any(set(item.attrib) != {"key", "value"} for item in metadata_items)
            or len(part.findall("metadata")) != len(expected_keys)
        ):
            raise BlackRadialCouponError(
                "Conventional model-settings part allowlist drifted"
            )
        keyed = {
            str(item.attrib.get("key")): str(item.attrib.get("value", ""))
            for item in part.findall("metadata")
            if "key" in item.attrib
        }
        if keyed.get("extruder") != "1":
            raise BlackRadialCouponError(
                "Conventional painted part physical extruder drifted"
            )
        if keyed.get("name") != coupon.part_names[part_index]:
            raise BlackRadialCouponError(
                "Conventional model-settings part name drifted"
            )
        expected_static = {
            "matrix": "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1",
            "source_file": "purpose_built_black_radial_coupon.obj",
            "source_object_id": "0",
            "source_volume_id": str(part_index),
            "source_offset_x": "0",
            "source_offset_y": "0",
            "source_offset_z": "0",
        }
        for key, expected in expected_static.items():
            if keyed.get(key) != expected:
                raise BlackRadialCouponError(
                    f"Conventional model-settings {key} drifted"
                )
        mesh_stats = part.findall("mesh_stat")
        expected_mesh_stat = {
            "face_count": str(coupon.part_face_counts[part_index]),
            "edges_fixed": "0",
            "degenerate_facets": "0",
            "facets_removed": "0",
            "facets_reversed": "0",
            "backwards_edges": "0",
        }
        if (
            len(mesh_stats) != 1
            or mesh_stats[0].attrib != expected_mesh_stat
            or [item.tag for item in list(part)]
            != ["metadata"] * len(expected_keys) + ["mesh_stat"]
        ):
            raise BlackRadialCouponError(
                "Conventional model-settings mesh statistics drifted"
            )
    plate = plates[0]
    if plate.attrib:
        raise BlackRadialCouponError("Conventional plate attributes drifted")
    plate_metadata = plate.findall("metadata")
    if (
        len(plate_metadata) != 4
        or any(set(item.attrib) != {"key", "value"} for item in plate_metadata)
        or {item.attrib["key"]: item.attrib["value"] for item in plate_metadata}
        != {
            "plater_id": "1",
            "plater_name": "Full Spectrum 4 Filaments",
            "locked": "false",
            "filament_map_mode": "Auto For Flush",
        }
    ):
        raise BlackRadialCouponError("Conventional plate metadata drifted")
    instances = plate.findall("model_instance")
    if (
        len(instances) != 1
        or instances[0].attrib
        or [item.tag for item in list(plate)]
        != ["metadata"] * 4 + ["model_instance"]
    ):
        raise BlackRadialCouponError("Conventional model instance drifted")
    instance_metadata = instances[0].findall("metadata")
    if (
        len(instance_metadata) != 3
        or list(instances[0]) != instance_metadata
        or any(set(item.attrib) != {"key", "value"} for item in instance_metadata)
        or {item.attrib["key"]: item.attrib["value"] for item in instance_metadata}
        != {"object_id": "22", "instance_id": "0", "identify_id": "1"}
    ):
        raise BlackRadialCouponError(
            "Conventional model-instance metadata drifted"
        )
    return {
        "schema": BLACK_RADIAL_COUPON_SCHEMA,
        "method": "conventional-z-ratio",
        "valid": True,
        "zip_crc_ok": True,
        "parts": len(objects),
        "validated_solid_parts": topology_ok,
        "observed_state_ids": observed_states,
        "mixed_definition_rows": len(definition_rows),
        "ratio_only": True,
        "layer_height_mm": LAYER_HEIGHT_MM,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _read_radial_meshes(
    archive: zipfile.ZipFile,
) -> list[tuple[np.ndarray, np.ndarray]]:
    root = ET.fromstring(archive.read("3D/Objects/radial_parts.model"))
    objects = [element for element in root.iter() if element.tag.endswith("object")]
    meshes: list[tuple[np.ndarray, np.ndarray]] = []
    for obj in objects:
        vertices = np.asarray(
            [
                [float(item.attrib[axis]) for axis in ("x", "y", "z")]
                for item in obj.iter()
                if item.tag.endswith("vertex")
            ],
            dtype=np.float64,
        )
        faces = np.asarray(
            [
                [int(item.attrib[key]) for key in ("v1", "v2", "v3")]
                for item in obj.iter()
                if item.tag.endswith("triangle")
            ],
            dtype=np.int32,
        )
        meshes.append((vertices, faces))
    return meshes


def _coordinate_key(point: np.ndarray, *, tolerance: float = 1.0e-8) -> tuple[int, int, int]:
    values = np.rint(np.asarray(point, dtype=np.float64) / tolerance).astype(np.int64)
    return int(values[0]), int(values[1]), int(values[2])


def _oriented_triangle_key(
    vertices: np.ndarray,
    face: np.ndarray,
    *,
    reverse: bool = False,
) -> tuple[tuple[int, int, int], ...]:
    indices = [int(face[0]), int(face[1]), int(face[2])]
    if reverse:
        indices[1], indices[2] = indices[2], indices[1]
    points = tuple(_coordinate_key(vertices[index]) for index in indices)
    rotations = (
        points,
        (points[1], points[2], points[0]),
        (points[2], points[0], points[1]),
    )
    return min(rotations)


def _verify_coupon_radial_geometry(
    archive: zipfile.ZipFile,
    *,
    wall_generator: str,
) -> int:
    radial_metadata = json.loads(
        archive.read("Metadata/radial_shell_experimental.json").decode("utf-8")
    )
    part_metadata = radial_metadata.get("parts")
    if not isinstance(part_metadata, list):
        raise BlackRadialCouponError("Radial per-part metadata is missing")
    meshes = _read_radial_meshes(archive)
    expected = build_radial_coupon(wall_generator=wall_generator)
    if len(meshes) != len(expected.parts) or len(part_metadata) != len(meshes):
        raise BlackRadialCouponError("Radial coupon geometry part count drifted")

    by_cell: dict[int, dict[str, int]] = {}
    for index, ((vertices, faces), expected_part, item) in enumerate(
        zip(meshes, expected.parts, part_metadata, strict=True)
    ):
        if not isinstance(item, Mapping):
            raise BlackRadialCouponError("Radial per-part metadata is malformed")
        if item.get("role") != expected_part.role:
            raise BlackRadialCouponError("Radial coupon material role order drifted")
        if int(item.get("extruder", 0)) != int(expected_part.extruder):
            raise BlackRadialCouponError("Radial coupon physical tool order drifted")
        expected_vertices = np.asarray(expected_part.vertices_mm, dtype=np.float64)
        expected_faces = np.asarray(expected_part.faces, dtype=np.int32)
        if vertices.shape != expected_vertices.shape or not np.allclose(
            vertices,
            expected_vertices,
            rtol=0.0,
            atol=1.0e-8,
        ):
            raise BlackRadialCouponError(
                "Serialized radial coupon vertices differ from the proven geometry"
            )
        if not np.array_equal(faces, expected_faces):
            raise BlackRadialCouponError(
                "Serialized radial coupon triangles differ from the proven geometry"
            )
        item_details = item.get("metadata")
        if not isinstance(item_details, Mapping):
            raise BlackRadialCouponError("Radial coupon cell metadata is missing")
        cell_index = int(item_details.get("cell_index", -1))
        expected_cell_index = int(expected_part.metadata.get("cell_index", -2))
        if cell_index != expected_cell_index:
            raise BlackRadialCouponError("Radial coupon cell order drifted")
        stage_index = cell_index % len(STAGE_KEYS)
        if 1 <= stage_index <= len(STAGE_KEYS) - 2:
            roles = by_cell.setdefault(cell_index, {})
            if expected_part.role in roles:
                raise BlackRadialCouponError("A radial mixed cell repeats a role")
            roles[expected_part.role] = index

    if len(by_cell) != 15 or any(
        set(roles) != {"pure_black_core", "partner_outer_shell"}
        for roles in by_cell.values()
    ):
        raise BlackRadialCouponError(
            "Radial coupon does not contain 15 one-to-one core/shell pairs"
        )

    for roles in by_cell.values():
        core_vertices, core_faces = meshes[roles["pure_black_core"]]
        shell_vertices, shell_faces = meshes[roles["partner_outer_shell"]]
        shell_oriented = Counter(
            _oriented_triangle_key(shell_vertices, face) for face in shell_faces
        )
        reversed_core = Counter(
            _oriented_triangle_key(core_vertices, face, reverse=True)
            for face in core_faces
        )
        for key, count in reversed_core.items():
            if shell_oriented[key] != count:
                raise BlackRadialCouponError(
                    "A radial core/shell boundary is not exact and oppositely wound"
                )
    return len(by_cell)


def _validate_radial_archive(
    path: Path,
    archive: zipfile.ZipFile,
    metadata: Mapping[str, object],
    *,
    wall_generator: str = "classic",
) -> dict[str, object]:
    project = _read_project(archive)
    generator = str(wall_generator).strip().lower()
    _validate_process(project, wall_generator=generator)
    if project.get("mixed_filament_definitions") != "":
        raise BlackRadialCouponError("Radial coupon contains virtual mix definitions")
    expected_profile = (
        RADIAL_PROCESS_PROFILE_BLACK_COUPON_ARACHNE_010
        if generator == "arachne"
        else RADIAL_PROCESS_PROFILE_BLACK_COUPON_010
    )
    proof = validate_radial_3mf(
        path,
        expected_physical=PHYSICAL_HEX,
        expected_process_profile=expected_profile,
    )
    wrapper = metadata.get("black_radial_coupon")
    if not isinstance(wrapper, Mapping):
        raise BlackRadialCouponError("Radial coupon metadata is missing")
    if wrapper.get("physical_materials_only") is not True:
        raise BlackRadialCouponError("Radial coupon is not physical-material-only")
    if wrapper.get("legacy_fullspectrum_ratios_used") is not False:
        raise BlackRadialCouponError("Radial coupon unexpectedly uses Ratio output")
    interfaces = wrapper.get("interfaces")
    if not isinstance(interfaces, list) or len(interfaces) != 15:
        raise BlackRadialCouponError("Radial coupon needs 15 mixed core/shell interfaces")
    if any(
        item.get("exact_coordinate_triangles") is not True
        or item.get("opposite_winding") is not True
        or float(item.get("gap_mm", -1.0)) != 0.0
        or float(item.get("positive_overlap_mm3", -1.0)) != 0.0
        or item.get("volume_conserved") is not True
        for item in interfaces
    ):
        raise BlackRadialCouponError("Radial core/shell interface proof failed")
    verified_interfaces = _verify_coupon_radial_geometry(
        archive,
        wall_generator=generator,
    )
    return {
        "schema": BLACK_RADIAL_COUPON_SCHEMA,
        "method": (
            "radial-physical-thickness-arachne"
            if generator == "arachne"
            else "radial-physical-thickness"
        ),
        "wall_generator": generator,
        "valid": True,
        "zip_crc_ok": proof.zip_crc_ok,
        "parts": proof.parts,
        "vertices": proof.vertices,
        "faces": proof.faces,
        "physical_extruders": list(proof.physical_extruders),
        "physical_materials_only": proof.physical_materials_only,
        "mixed_definition_rows": 0,
        "painted_triangles": 0,
        "interfaces": verified_interfaces,
        "layer_height_mm": LAYER_HEIGHT_MM,
        "sha256": proof.sha256,
        "bytes": proof.bytes,
    }


def validate_black_radial_coupon_3mf(
    path: Path,
    *,
    method: str | None = None,
) -> dict[str, object]:
    path = Path(path)
    if not path.is_file():
        raise BlackRadialCouponError(f"Coupon 3MF does not exist: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise BlackRadialCouponError("Coupon 3MF has a ZIP CRC failure")
        if "Metadata/black_radial_coupon.json" in archive.namelist():
            metadata = json.loads(
                archive.read("Metadata/black_radial_coupon.json").decode("utf-8")
            )
        else:
            radial = json.loads(
                archive.read("Metadata/radial_shell_experimental.json").decode("utf-8")
            )
            metadata = radial.get("generator_metadata", {})
        detected = str(
            metadata.get("method")
            or (
                metadata.get("black_radial_coupon", {}).get("method")
                if isinstance(metadata.get("black_radial_coupon"), Mapping)
                else ""
            )
        )
        if method is not None and detected != method:
            raise BlackRadialCouponError(
                f"Coupon method differs: {detected!r} != {method!r}"
            )
        if detected == "conventional-z-ratio":
            return _validate_conventional_archive(path, archive, metadata)
        if detected == "radial-physical-thickness":
            return _validate_radial_archive(
                path,
                archive,
                metadata,
                wall_generator="classic",
            )
        if detected == "radial-physical-thickness-arachne":
            return _validate_radial_archive(
                path,
                archive,
                metadata,
                wall_generator="arachne",
            )
        raise BlackRadialCouponError(f"Unsupported coupon method: {detected!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _write_mapping(path: Path) -> None:
    rows = _stage_records()
    fieldnames = [
        "lane",
        "partner_slot",
        "stage_index",
        "stage_label",
        "conventional_state_id",
        "effective_black_percent",
        "cadence",
        "predicted_black_band_spacing_mm",
        "radial_shell_thickness_mm",
        "radial_shell_line_width_multiple",
        "cell_bounds_mm",
        "surface_ids",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(row[key], ensure_ascii=False)
                        if isinstance(row[key], list)
                        else row[key]
                    )
                    for key in fieldnames
                }
            )


def _write_observation_sheet(path: Path) -> None:
    fieldnames = [
        "lane",
        "stage_label",
        "surface",
        "conventional_black_band_score_0_to_5",
        "radial_black_band_score_0_to_5",
        "radial_arachne_black_band_score_0_to_5",
        "radial_shell_loss_yes_no",
        "radial_arachne_shell_loss_yes_no",
        "conventional_color_fidelity_0_to_5",
        "radial_color_fidelity_0_to_5",
        "radial_arachne_color_fidelity_0_to_5",
        "preferred_method",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in _stage_records():
            for surface in SURFACE_IDS:
                writer.writerow(
                    {
                        "lane": row["lane"],
                        "stage_label": row["stage_label"],
                        "surface": surface,
                        "conventional_black_band_score_0_to_5": "",
                        "radial_black_band_score_0_to_5": "",
                        "radial_arachne_black_band_score_0_to_5": "",
                        "radial_shell_loss_yes_no": "",
                        "radial_arachne_shell_loss_yes_no": "",
                        "conventional_color_fidelity_0_to_5": "",
                        "radial_color_fidelity_0_to_5": "",
                        "radial_arachne_color_fidelity_0_to_5": "",
                        "preferred_method": "",
                        "notes": "",
                    }
                )


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _hex_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def _write_layout_image(path: Path) -> None:
    image = Image.new("RGB", (1800, 1080), "#F3F5F7")
    draw = ImageDraw.Draw(image)
    title_font = _font(44, bold=True)
    header_font = _font(25, bold=True)
    body_font = _font(21)
    process_font = _font(16)
    small_font = _font(17)
    draw.text(
        (60, 38),
        "ChromaMatter black-band coupon | 0.10 mm | Warm set",
        fill="#111820",
        font=title_font,
    )
    draw.text(
        (60, 98),
        "Front to back: White / Yellow / Skin     Left to right: increasing black",
        fill="#40505E",
        font=body_font,
    )
    left, top = 210, 165
    cell_w, cell_h, gap = 205, 108, 13
    stages = coupon_stages()
    for stage in stages:
        x = left + stage.index * (cell_w + gap)
        draw.text(
            (x + 4, top - 38),
            stage.label,
            fill="#17212A",
            font=small_font,
        )
    for lane_index, partner_slot in enumerate(LANE_PARTNER_SLOTS):
        y = top + lane_index * 150
        lane = PHYSICAL_LABELS[partner_slot]
        draw.text((60, y + 37), lane, fill="#111820", font=header_font)
        partner_rgb = np.asarray(_hex_rgb(PHYSICAL_HEX[partner_slot]), dtype=np.float64)
        black_rgb = np.asarray(_hex_rgb(PHYSICAL_HEX[0]), dtype=np.float64)
        for stage in stages:
            x = left + stage.index * (cell_w + gap)
            fraction = stage.effective_black_fraction
            color = tuple(
                int(round(value))
                for value in ((1.0 - fraction) * partner_rgb + fraction * black_rgb)
            )
            draw.rounded_rectangle(
                (x, y, x + cell_w, y + cell_h),
                radius=12,
                fill=color,
                outline="#111820",
                width=3,
            )
            thickness = (
                "pure partner"
                if stage.radial_thickness_mm is None
                else "pure black"
                if stage.radial_thickness_mm == 0.0
                else f"shell {stage.radial_thickness_mm:.2f} mm"
            )
            text_fill = "#FFFFFF" if sum(color) < 310 else "#111820"
            draw.text(
                (x + 12, y + 43),
                thickness,
                fill=text_fill,
                font=small_font,
            )
    panel_top = 650
    draw.rounded_rectangle(
        (60, panel_top, 900, 1015),
        radius=18,
        fill="#FFFFFF",
        outline="#B8C3CC",
        width=2,
    )
    draw.text((90, panel_top + 24), "One cell cross-section", fill="#111820", font=header_font)
    polygon = _ccw_polygon(_CROSS_SECTION_YZ)
    scale = 19.0
    origin_x, origin_y = 130, 990
    points = [
        (origin_x + float(y) * scale, origin_y - float(z) * scale)
        for y, z in polygon
    ]
    draw.polygon(points, fill="#E8A071", outline="#111820")
    draw.line(points + [points[0]], fill="#111820", width=4)
    draw.text(
        (470, panel_top + 92),
        "Includes:\nvertical front/rear\n30 deg + 60 deg slopes\ntop horizontal\ndownward horizontal\ndownward 45 deg",
        fill="#26333E",
        font=body_font,
        spacing=9,
    )
    draw.rounded_rectangle(
        (935, panel_top, 1740, 1015),
        radius=18,
        fill="#101820",
        outline="#101820",
    )
    draw.text((970, panel_top + 25), "Fixed process", fill="#FFFFFF", font=header_font)
    draw.text(
        (970, panel_top + 82),
        "Normal layer: 0.10 mm\nInitial layer: 0.20 mm\n2 walls | Thin wall OFF\nClassic or Arachne\nOuter / inner: 0.42 / 0.45 mm\nTop/bottom: 5 layers\nInfill: 100%\nSupport / brim / raft: OFF\nPrime tower: ON",
        fill="#D9E5EE",
        font=process_font,
        spacing=4,
    )
    draw.text(
        (970, panel_top + 310),
        "0.21 mm: feature retention | 0.42 mm: one wall\n0.84 / 1.05 mm: two-wall and colour-loss probes",
        fill="#FFBE55",
        font=small_font,
        spacing=6,
    )
    image.save(path, format="PNG", optimize=True)


def _write_research_notes(path: Path) -> None:
    path.write_text(
        """# 黒を表面へ出さない方式の調査メモ

## 結論

従来のRatio混色はZ方向のレイヤー周期です。0.10 mmでは黒1層そのものが0.08 mm時より25%厚くなり、白・黄・肌色との高コントラストでは横筋が目立ちやすくなります。壁生成方式やウォール数だけを変えても、その黒レイヤーでは外壁自体が黒なので根本解決にはなりません。

今回のラジアル比較は、純黒セルを物理F1のまま残し、黒を含む中間色セルだけを「相手色の物理外皮＋純黒コア」に置き換えています。主変数はウォール数ではなく外皮ジオメトリ厚です。

## ClassicとArachneを2 wallで比較する理由

- U1の通常条件に近い2 wall・Thin wall OFFを3MFすべてへ明示し、方式以外の差を減らします。
- 0.21 mmは細部保持、0.42 mmは単壁、0.84 / 1.05 mmは二重壁の成立域を測るセルです。
- Classicは壁幅が予測しやすく、Arachneは狭部を可変幅で残せる可能性があります。
- Arachneの最小ビード85%は0.4 mmノズルで約0.34 mmです。0.21 mm形状が残っても、0.21 mmのまま押出される保証はありません。
- 外皮を厚くすると黒コアが見えにくくなる一方、色が相手色へ寄りやすくなります。このトレードオフを厚さスイープで実測します。

## Orca側で確認できた別候補

`mixed_filament_component_bias_enabled` と成分別surface offsetは、混色中の黒だけをXY方向へ内側に後退できます。純黒の物理F1には作用しません。ただし側面には有効でも、水平な天面中央を相手色で覆う保証はありません。Grouped Cycleは外壁を相手色に固定できますが、天面が最内壁色へ追従する制約があり、現行Snapmaker Orca 2.3.5では過去に仮想T4+漏出経路も観測したため今回の印刷候補には採用していません。

## G-codeで見る項目

1. 従来型はT0〜T3だけへ解決され、予測周期どおり黒層が現れるか。
2. ラジアル型は最初から物理F1〜F4だけで、仮想混色定義がないか。
3. ラジアル中間色のOuter wallで黒F1（G-codeではT0）が使われていないか。
4. 純黒controlではT0が維持されているか。
5. Classic/Arachneで0.21 / 0.42 mm外皮の連続性がどう変わるか。
6. 0.84 / 1.05 mmで二重壁が成立し、色が明るくなりすぎないか。

## 参照した一次資料

- Snapmaker Full Spectrum guide: https://www.snapmaker.com/blog/getting-started-with-full-spectrum-slicing/
- Orca wall generator: https://github.com/OrcaSlicer/OrcaSlicer/wiki/quality_settings_wall_generator
- Orca wall settings: https://github.com/OrcaSlicer/OrcaSlicer/wiki/strength_settings_walls
- Snapmaker Orca mixed-filament implementation: https://github.com/Snapmaker/OrcaSlicer/blob/V2.3.6/src/libslic3r/MixedFilament.hpp
- Component Bias slicing path: https://github.com/Snapmaker/OrcaSlicer/blob/V2.3.6/src/libslic3r/PrintObjectSlice.cpp
""",
        encoding="utf-8",
    )


def _write_guides(folder: Path) -> tuple[Path, Path]:
    ja = folder / "README_JA.md"
    en = folder / "README_EN.md"
    ja.write_text(
        """# 黒筋抑制 比較クーポン（0.10 mm）

この3つの3MFは、同じ21セルを「従来のZ方向Ratio混色」「Classic物理ラジアル」「Arachne物理ラジアル」で比較する実験用です。まだ実機校正済みではありません。必ずSnapmaker OrcaのFilament表示とToolpathを全層確認してから印刷してください。

## 配置

- 手前から White / Yellow / Skin の3レーンです（F1=Black、F2=White、F3=Yellow、F4=Skin）。
- 左から Partner 100%、Black 5%、10%、14.3%、20%、25%、Black 100%です。
- 各セルには垂直面、30°面、60°面、上面、下向き水平面、下向き45°面があります。

## 3ファイルの違い

- `ChromaMatter_black_gradient_conventional_0p10.3mf`: 黒い1層を周期的に入れる従来方式です。予測黒筋間隔は2.0 / 1.0 / 0.7 / 0.5 / 0.4 mmです。
- `ChromaMatter_black_gradient_radial_0p10.3mf`: 純黒はそのまま残し、中間色だけ黒コアを相手色外皮で覆います。外皮厚は1.05 / 0.84 / 0.63 / 0.42 / 0.21 mmです。
- `ChromaMatter_black_gradient_radial_arachne_0p10.3mf`: 同じ物理形状をArachneでスライスします。最小ビード85%、最小形状25%、外壁幅の変動を抑えるdistribution count 1を明示しています。

0.21 mmは細部保持、0.42 mmは単壁、0.84 / 1.05 mmは二重壁域の試験です。Arachneの85%最小ビードは約0.34 mmなので、0.21 mm形状が残っても同じ幅で押出されるとは限りません。

## 固定条件

通常層0.10 mm（初層0.20 mm）、2 walls、Thin wall OFF、外壁0.42 mm、内壁0.45 mm、上下5層、100% infill、support/brim/raft OFF、prime tower ONです。Classic/Arachne以外は同じです。比較中は自動修復・結合・向き変更をしないでください。

## 判定

同じ照明と距離で、各面について黒筋の有無、色の明るさ、境界の欠け、外皮消失、天面・下面の黒露出を記録します。最良の厚さは色ごとに異なる可能性があります。純黒セルが黒のままかも必ず確認してください。
""",
        encoding="utf-8",
    )
    en.write_text(
        """# Black-band suppression comparison coupon (0.10 mm)

These three experimental 3MF projects contain the same 21 cells and compare conventional Z-layer Ratio mixing, a Classic physical radial shell, and an Arachne physical radial shell. They are not machine-calibrated yet. Inspect every layer in Snapmaker Orca's Filament and Toolpath views before printing.

## Layout

- Front to back: White, Yellow, and Skin lanes (F1 Black, F2 White, F3 Yellow, F4 Skin).
- Left to right: Partner 100%, Black 5%, 10%, 14.3%, 20%, 25%, and Black 100%.
- Every cell includes vertical, 30-degree, 60-degree, top, downward horizontal, and downward 45-degree surfaces.

## Difference

- `ChromaMatter_black_gradient_conventional_0p10.3mf` periodically exposes one black Z layer. Predicted band spacing is 2.0 / 1.0 / 0.7 / 0.5 / 0.4 mm.
- `ChromaMatter_black_gradient_radial_0p10.3mf` preserves pure black, but covers mixed black cores with a physical partner-colour shell. Thicknesses are 1.05 / 0.84 / 0.63 / 0.42 / 0.21 mm.
- `ChromaMatter_black_gradient_radial_arachne_0p10.3mf` uses the same physical geometry with Arachne, an 85% minimum bead, 25% minimum feature, and wall distribution count 1.

The 0.21 mm shell probes feature retention, 0.42 mm probes a single wall, and 0.84 / 1.05 mm probe the two-wall range. Arachne's 85% bead floor is about 0.34 mm, so retaining a 0.21 mm feature does not mean extruding a true 0.21 mm line.

## Fixed process

0.10 mm normal layers (0.20 mm initial), two walls, thin-wall detection off, 0.42 mm outer and 0.45 mm inner widths, five top/bottom layers, 100% infill, no support/brim/raft, and a prime tower. Only Classic/Arachne differs. Do not auto-repair, merge, rotate, or change settings during the comparison.

## Record

Under the same lighting and distance, record black bands, brightness, boundary loss, shell disappearance, and black exposure on every surface. Confirm that the pure-black control remains black. The best shell thickness may differ by partner colour.
""",
        encoding="utf-8",
    )
    return ja, en


def create_black_radial_coupon_bundle(
    output_directory: Path,
    *,
    created_at: datetime | None = None,
) -> BlackRadialCouponBundle:
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    if any(output_directory.iterdir()):
        raise BlackRadialCouponError("Coupon output directory must be empty")
    conventional = output_directory / "ChromaMatter_black_gradient_conventional_0p10.3mf"
    radial = output_directory / "ChromaMatter_black_gradient_radial_0p10.3mf"
    radial_arachne = (
        output_directory
        / "ChromaMatter_black_gradient_radial_arachne_0p10.3mf"
    )
    mapping = output_directory / "coupon_map.csv"
    observation = output_directory / "observation_sheet.csv"
    layout = output_directory / "coupon_layout.png"
    research_notes = output_directory / "RESEARCH_NOTES_JA.md"
    snapshot = output_directory / "coupon_snapshot.json"
    conventional_validation_path = output_directory / "validation_conventional.json"
    radial_validation_path = output_directory / "validation_radial.json"
    radial_arachne_validation_path = (
        output_directory / "validation_radial_arachne.json"
    )
    manifest = output_directory / "bundle_manifest.json"

    conventional_validation = _write_conventional_3mf(conventional)
    radial_validation = _write_radial_3mf(radial)
    radial_arachne_validation = _write_radial_3mf(
        radial_arachne,
        wall_generator="arachne",
    )
    _write_mapping(mapping)
    _write_observation_sheet(observation)
    _write_layout_image(layout)
    _write_research_notes(research_notes)
    readme_ja, readme_en = _write_guides(output_directory)
    snapshot.write_text(
        json.dumps(
            {
                **_coupon_metadata("comparison-bundle"),
                "created_at": (created_at or datetime.now().astimezone()).isoformat(),
                "conventional_file": conventional.name,
                "radial_file": radial.name,
                "radial_arachne_file": radial_arachne.name,
                "wall_generators": ["classic", "arachne"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    conventional_validation_path.write_text(
        json.dumps(conventional_validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    radial_validation_path.write_text(
        json.dumps(radial_validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    radial_arachne_validation_path.write_text(
        json.dumps(radial_arachne_validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files = [
        conventional,
        radial,
        radial_arachne,
        mapping,
        observation,
        layout,
        research_notes,
        readme_ja,
        readme_en,
        snapshot,
        conventional_validation_path,
        radial_validation_path,
        radial_arachne_validation_path,
    ]
    manifest.write_text(
        json.dumps(
            {
                "schema": BLACK_RADIAL_COUPON_SCHEMA,
                "files": [
                    {
                        "name": item.name,
                        "bytes": item.stat().st_size,
                        "sha256": _sha256(item),
                    }
                    for item in files
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return BlackRadialCouponBundle(
        folder=output_directory,
        conventional_path=conventional,
        radial_path=radial,
        radial_arachne_path=radial_arachne,
        mapping_path=mapping,
        observation_path=observation,
        layout_path=layout,
        research_notes_path=research_notes,
        readme_ja_path=readme_ja,
        readme_en_path=readme_en,
        snapshot_path=snapshot,
        conventional_validation_path=conventional_validation_path,
        radial_validation_path=radial_validation_path,
        radial_arachne_validation_path=radial_arachne_validation_path,
        manifest_path=manifest,
        conventional_validation=conventional_validation,
        radial_validation=radial_validation,
        radial_arachne_validation=radial_arachne_validation,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create the 0.10 mm conventional/radial black-band coupon bundle."
    )
    parser.add_argument("output_directory", type=Path)
    arguments = parser.parse_args(argv)
    result = create_black_radial_coupon_bundle(arguments.output_directory)
    print(result.conventional_path)
    print(result.radial_path)
    print(result.radial_arachne_path)
    print(result.manifest_path)
    return 0


__all__ = [
    "BLACK_RADIAL_COUPON_SCHEMA",
    "BlackRadialCouponBundle",
    "BlackRadialCouponError",
    "CouponMesh",
    "CouponStage",
    "build_conventional_coupon",
    "build_coupon_cell_mesh",
    "build_radial_coupon",
    "coupon_stages",
    "create_black_radial_coupon_bundle",
    "main",
    "validate_black_radial_coupon_3mf",
]


if __name__ == "__main__":
    raise SystemExit(main())
