"""Large corner-frustum white/black coupon for radial-shell research.

The older black-band fixture intentionally covered several colours and many
surface orientations.  It is useful as a broad matrix, but too large for
frequent physical iteration.  This module builds one visually continuous,
corner-biased truncated pyramid instead.  Six exact-contact height bands
progress from a pure-white base through five black targets.  A 9 mm square
horizontal top keeps the final 0.10 mm white cap observable, and the first
0.20 mm layer carries an exact-partition black Z/C/A underside identifier.

Three slice-only 0.10 mm projects are emitted from the same outer geometry:

* conventional Z-cadence Ratio mixing;
* physical black cores with white shells, Classic walls;
* the same physical volumes with Arachne walls.

The Classic project deliberately enables thin-wall detection because all but
the 0.42 mm shell are below the nominal outer-wall width.  Arachne keeps thin
wall detection off and uses an explicit 20% minimum feature, 25% normal-layer
minimum bead, and 85% initial-layer minimum bead.  Therefore the 0.10 mm shell
is a retention probe, not a claim that Orca can extrude a true 0.10 mm line.
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

from . import engine, mixer
from .models import ColorResult, MeshLevel, ObjAsset, PaletteSettings, PreparedGeometry
from .radial_export import (
    RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_ARACHNE_010,
    RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_010,
    RadialExportPackage,
    RadialExportPart,
    validate_radial_3mf,
    write_radial_3mf_atomic,
)


COMPACT_COUPON_SCHEMA = "chromamatter.large-black-radial-frustum.v1"
RADIAL_GATE_SCHEMA = "chromamatter.black-radial-coupon.v1"
RADIAL_GATE_GEOMETRY_VERSION = "multi-surface-prism-v1"
GEOMETRY_VERSION = "corner-frustum-bottom-id-top-cap-v1"

PHYSICAL_HEX = ("#121212", "#F5F5F5", "#F5F5F5", "#F5F5F5")
PHYSICAL_LABELS = ("Black", "White", "Unused White", "Unused White")
BLACK_EXTRUDER = 1
WHITE_EXTRUDER = 2
LAYER_HEIGHT_MM = 0.10
INITIAL_LAYER_HEIGHT_MM = 0.20
BASE_SIZE_MM = 42.0
MODEL_HEIGHT_MM = 22.8
APEX_XY_MM = (0.0, 0.0)
TOP_SIZE_MM = 9.0
IDENTIFIER_LAYER_HEIGHT_MM = 0.20
TOP_CAP_THICKNESS_MM = 0.10
BAND_Z_MM = (0.0, 3.0, 9.0, 12.0, 16.2, 19.2, 22.8)
EFFECTIVE_BLACK_FRACTIONS = (0.0, 0.05, 0.10, 1.0 / 7.0, 0.20, 0.25)
RADIAL_THICKNESS_MM = (None, 0.42, 0.30, 0.21, 0.15, 0.10)
STAGE_KEYS = (
    "white_100",
    "black_05",
    "black_10",
    "black_14",
    "black_20",
    "black_25",
)
STAGE_LABELS = (
    "White 100%",
    "Black 5%",
    "Black 10%",
    "Black 14.3%",
    "Black 20%",
    "Black 25%",
)
CONVENTIONAL_STATE_INDICES = (1, 23, 10, 16, 4, 22)

_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PRODUCTION_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_COMPACT_METADATA_MEMBER = "Metadata/compact_black_radial_coupon.json"
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
        _COMPACT_METADATA_MEMBER,
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


class CompactBlackRadialCouponError(RuntimeError):
    """Raised when the compact fixture cannot be proven deterministic."""


@dataclass(frozen=True, slots=True)
class CompactStage:
    index: int
    key: str
    label: str
    z0_mm: float
    z1_mm: float
    effective_black_fraction: float
    radial_thickness_mm: float | None
    conventional_state_index: int


@dataclass(frozen=True, slots=True)
class IdentifierTile:
    index: int
    code: str
    color: str
    bounds_xy_mm: tuple[float, float, float, float]
    vertices_mm: np.ndarray
    faces: np.ndarray


@dataclass(frozen=True, slots=True)
class CompactPyramidMesh:
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
class CompactBlackRadialCouponBundle:
    folder: Path
    conventional_path: Path
    radial_path: Path
    radial_arachne_path: Path
    mapping_path: Path
    observation_path: Path
    readme_ja_path: Path
    readme_en_path: Path
    conventional_validation_path: Path
    radial_validation_path: Path
    radial_arachne_validation_path: Path
    manifest_path: Path
    conventional_validation: Mapping[str, object]
    radial_validation: Mapping[str, object]
    radial_arachne_validation: Mapping[str, object]


def compact_stages() -> tuple[CompactStage, ...]:
    return tuple(
        CompactStage(
            index=index,
            key=STAGE_KEYS[index],
            label=STAGE_LABELS[index],
            z0_mm=BAND_Z_MM[index],
            z1_mm=BAND_Z_MM[index + 1],
            effective_black_fraction=EFFECTIVE_BLACK_FRACTIONS[index],
            radial_thickness_mm=RADIAL_THICKNESS_MM[index],
            conventional_state_index=CONVENTIONAL_STATE_INDICES[index],
        )
        for index in range(len(STAGE_KEYS))
    )


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


def _edge_quality(faces: np.ndarray) -> tuple[int, int, bool]:
    faces = np.asarray(faces, dtype=np.int64)
    directed = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    undirected = np.sort(directed, axis=1)
    _unique, inverse, counts = np.unique(
        undirected, axis=0, return_inverse=True, return_counts=True
    )
    direction = np.where(directed[:, 0] < directed[:, 1], 1, -1)
    balance = np.bincount(inverse, weights=direction)
    boundary = int(np.count_nonzero(counts == 1))
    nonmanifold = int(np.count_nonzero(counts > 2))
    return boundary, nonmanifold, bool(
        boundary == 0 and nonmanifold == 0 and np.all(balance == 0)
    )


def _assert_solid(vertices: np.ndarray, faces: np.ndarray, label: str) -> None:
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1:] != (3,) or len(vertices) < 4:
        raise CompactBlackRadialCouponError(f"{label} has invalid vertices")
    if faces.ndim != 2 or faces.shape[1:] != (3,) or len(faces) < 4:
        raise CompactBlackRadialCouponError(f"{label} has invalid triangles")
    if not np.isfinite(vertices).all() or int(faces.min()) < 0 or int(faces.max()) >= len(vertices):
        raise CompactBlackRadialCouponError(f"{label} has invalid coordinates or indices")
    triangles = vertices[faces]
    doubled = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    )
    if np.any(doubled <= 1.0e-10):
        raise CompactBlackRadialCouponError(f"{label} contains a degenerate triangle")
    boundary, nonmanifold, winding = _edge_quality(faces)
    if boundary or nonmanifold or not winding:
        raise CompactBlackRadialCouponError(f"{label} is not a consistently wound solid")
    if _signed_volume(vertices, faces) <= 1.0e-9:
        raise CompactBlackRadialCouponError(f"{label} has no positive volume")


def _outer_bounds(z_mm: float) -> tuple[float, float, float, float]:
    z = float(z_mm)
    if not 0.0 <= z <= MODEL_HEIGHT_MM:
        raise CompactBlackRadialCouponError(f"Frustum Z is out of range: {z!r}")
    # Keep the exact 0.20 mm identifier layer rectangular.  Above it, the
    # X=max and Y=max faces taper linearly to the 9 x 9 mm horizontal top;
    # X=0 and Y=0 remain vertical throughout.
    if z <= IDENTIFIER_LAYER_HEIGHT_MM:
        return 0.0, BASE_SIZE_MM, 0.0, BASE_SIZE_MM
    t = (z - IDENTIFIER_LAYER_HEIGHT_MM) / (
        MODEL_HEIGHT_MM - IDENTIFIER_LAYER_HEIGHT_MM
    )
    x_min = t * APEX_XY_MM[0]
    x_max = (1.0 - t) * BASE_SIZE_MM + t * (
        APEX_XY_MM[0] + TOP_SIZE_MM
    )
    y_min = t * APEX_XY_MM[1]
    y_max = (1.0 - t) * BASE_SIZE_MM + t * (
        APEX_XY_MM[1] + TOP_SIZE_MM
    )
    return x_min, x_max, y_min, y_max


def _equal_normal_core_bounds(
    z_mm: float,
    thickness_mm: float,
) -> tuple[float, float, float, float]:
    """Offset all four frustum side planes by equal normal distance."""

    distance = float(thickness_mm)
    if not math.isfinite(distance) or distance <= 0.0:
        raise CompactBlackRadialCouponError("Shell thickness must be positive")
    x_min, x_max, y_min, y_max = _outer_bounds(z_mm)
    taper_height = MODEL_HEIGHT_MM - IDENTIFIER_LAYER_HEIGHT_MM
    x_min_slope = APEX_XY_MM[0] / taper_height
    x_max_slope = (
        BASE_SIZE_MM - APEX_XY_MM[0] - TOP_SIZE_MM
    ) / taper_height
    y_min_slope = APEX_XY_MM[1] / taper_height
    y_max_slope = (
        BASE_SIZE_MM - APEX_XY_MM[1] - TOP_SIZE_MM
    ) / taper_height
    result = (
        x_min + distance * math.sqrt(1.0 + x_min_slope**2),
        x_max - distance * math.sqrt(1.0 + x_max_slope**2),
        y_min + distance * math.sqrt(1.0 + y_min_slope**2),
        y_max - distance * math.sqrt(1.0 + y_max_slope**2),
    )
    if result[1] - result[0] <= 1.0e-6 or result[3] - result[2] <= 1.0e-6:
        raise CompactBlackRadialCouponError(
            f"Equal-normal {distance:g} mm shell consumes the core at Z={z_mm:g}"
        )
    return result


def _rectangle(bounds: Sequence[float], z_mm: float) -> np.ndarray:
    x_min, x_max, y_min, y_max = (float(value) for value in bounds)
    return np.asarray(
        (
            (x_min, y_min, z_mm),
            (x_max, y_min, z_mm),
            (x_max, y_max, z_mm),
            (x_min, y_max, z_mm),
        ),
        dtype=np.float64,
    )


_IDENTIFIER_PATTERNS = {
    "Z": (
        "11111",
        "00011",
        "00111",
        "01110",
        "11100",
        "11000",
        "11111",
    ),
    "C": (
        "11111",
        "11000",
        "11000",
        "11000",
        "11000",
        "11000",
        "11111",
    ),
    "A": (
        "01110",
        "11011",
        "11011",
        "11111",
        "11011",
        "11011",
        "11011",
    ),
}
_IDENTIFIER_X_BREAKS_MM = (0.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 42.0)
_IDENTIFIER_Y_BREAKS_MM = (
    0.0,
    14.0,
    16.0,
    18.0,
    20.0,
    22.0,
    24.0,
    26.0,
    28.0,
    42.0,
)


def _box_mesh(
    bounds_xy_mm: Sequence[float],
    z0_mm: float,
    z1_mm: float,
) -> tuple[np.ndarray, np.ndarray]:
    lower = _rectangle(bounds_xy_mm, z0_mm)
    upper = _rectangle(bounds_xy_mm, z1_mm)
    vertices = np.vstack((lower, upper))
    faces: list[tuple[int, int, int]] = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
    ]
    for index in range(4):
        following = (index + 1) % 4
        faces.extend(
            ((index, following, 4 + following), (index, 4 + following, 4 + index))
        )
    face_array = np.asarray(faces, dtype=np.int32)
    _assert_solid(vertices, face_array, "identifier tile")
    return vertices, face_array


def _identifier_tiles(code: str) -> tuple[IdentifierTile, ...]:
    """Partition the complete first layer into black glyph and white cells."""

    normalized = str(code).strip().upper()
    pattern = _IDENTIFIER_PATTERNS.get(normalized)
    if pattern is None:
        raise CompactBlackRadialCouponError(
            f"Unsupported bottom identifier: {code!r}"
        )
    nx = len(_IDENTIFIER_X_BREAKS_MM) - 1
    ny = len(_IDENTIFIER_Y_BREAKS_MM) - 1
    black = np.zeros((ny, nx), dtype=bool)
    # The centred five-by-seven bitmap lives at X=16..26, Y=14..28.  Rows are
    # written top-to-bottom while the geometry grid is bottom-to-top.
    for row, text in enumerate(pattern):
        if len(text) != 5 or set(text) - {"0", "1"}:
            raise CompactBlackRadialCouponError("Identifier bitmap is malformed")
        grid_y = 1 + (6 - row)
        for column, value in enumerate(text):
            # An observer looking at the underside faces +Z, which mirrors the
            # model's +X axis on screen.  Store the bitmap X-mirrored so Z/C/A
            # read normally after the finished coupon is flipped over.
            black[grid_y, 1 + (4 - column)] = value == "1"

    def merged_rectangles(mask_value: bool) -> list[tuple[float, float, float, float]]:
        used = np.zeros_like(black)
        rectangles: list[tuple[float, float, float, float]] = []
        for y_index in range(ny):
            for x_index in range(nx):
                if used[y_index, x_index] or bool(black[y_index, x_index]) != mask_value:
                    continue
                x_end = x_index + 1
                while (
                    x_end < nx
                    and not used[y_index, x_end]
                    and bool(black[y_index, x_end]) == mask_value
                ):
                    x_end += 1
                y_end = y_index + 1
                while y_end < ny and all(
                    not used[y_end, x]
                    and bool(black[y_end, x]) == mask_value
                    for x in range(x_index, x_end)
                ):
                    y_end += 1
                used[y_index:y_end, x_index:x_end] = True
                rectangles.append(
                    (
                        _IDENTIFIER_X_BREAKS_MM[x_index],
                        _IDENTIFIER_X_BREAKS_MM[x_end],
                        _IDENTIFIER_Y_BREAKS_MM[y_index],
                        _IDENTIFIER_Y_BREAKS_MM[y_end],
                    )
                )
        expected = black == mask_value
        if not np.array_equal(used, expected):
            raise CompactBlackRadialCouponError(
                "Identifier rectangle merge did not cover its grid"
            )
        return rectangles

    records: list[IdentifierTile] = []
    for color, mask_value in (("black", True), ("white", False)):
        for bounds in merged_rectangles(mask_value):
            vertices, faces = _box_mesh(
                bounds,
                0.0,
                IDENTIFIER_LAYER_HEIGHT_MM,
            )
            records.append(
                IdentifierTile(
                    index=len(records),
                    code=normalized,
                    color=color,
                    bounds_xy_mm=tuple(float(value) for value in bounds),
                    vertices_mm=vertices,
                    faces=faces,
                )
            )
    black_area = sum(
        (tile.bounds_xy_mm[1] - tile.bounds_xy_mm[0])
        * (tile.bounds_xy_mm[3] - tile.bounds_xy_mm[2])
        for tile in records
        if tile.color == "black"
    )
    total_area = sum(
        (tile.bounds_xy_mm[1] - tile.bounds_xy_mm[0])
        * (tile.bounds_xy_mm[3] - tile.bounds_xy_mm[2])
        for tile in records
    )
    if black_area <= 0.0 or not math.isclose(
        total_area, BASE_SIZE_MM**2, rel_tol=0.0, abs_tol=1.0e-9
    ):
        raise CompactBlackRadialCouponError(
            "Bottom identifier is not a complete black/white partition"
        )
    return tuple(records)


def _frustum_mesh(
    z0_mm: float,
    z1_mm: float,
    *,
    inset_mm: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    if not float(z1_mm) > float(z0_mm):
        raise CompactBlackRadialCouponError("A frustum band must have positive height")
    if inset_mm > 0.0:
        lower_bounds = _equal_normal_core_bounds(z0_mm, inset_mm)
        upper_bounds = _equal_normal_core_bounds(z1_mm, inset_mm)
    else:
        lower_bounds = _outer_bounds(z0_mm)
        upper_bounds = _outer_bounds(z1_mm)
    lower = _rectangle(lower_bounds, z0_mm)
    upper_width = float(upper_bounds[1] - upper_bounds[0])
    upper_depth = float(upper_bounds[3] - upper_bounds[2])
    if upper_width <= 1.0e-8 and upper_depth <= 1.0e-8:
        apex = np.asarray(
            ((upper_bounds[0], upper_bounds[2], z1_mm),), dtype=np.float64
        )
        vertices = np.vstack((lower, apex))
        faces = np.asarray(
            (
                (0, 2, 1),
                (0, 3, 2),
                (0, 1, 4),
                (1, 2, 4),
                (2, 3, 4),
                (3, 0, 4),
            ),
            dtype=np.int32,
        )
    else:
        upper = _rectangle(upper_bounds, z1_mm)
        vertices = np.vstack((lower, upper))
        faces_out: list[tuple[int, int, int]] = [
            (0, 2, 1),
            (0, 3, 2),
            (4, 5, 6),
            (4, 6, 7),
        ]
        for index in range(4):
            following = (index + 1) % 4
            faces_out.append((index, following, 4 + following))
            faces_out.append((index, 4 + following, 4 + index))
        faces = np.asarray(faces_out, dtype=np.int32)
    if _signed_volume(vertices, faces) < 0.0:
        faces = faces[:, [0, 2, 1]]
    _assert_solid(vertices, faces, "frustum band")
    return vertices, faces


def _shell_and_core_meshes(
    z0_mm: float,
    z1_mm: float,
    thickness_mm: float,
    *,
    top_cap_mm: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build a true shell and exact-contact inner core.

    ``top_cap_mm`` terminates the core below ``z1_mm`` and closes the cavity
    with a complete white ceiling.  It is used only for the final 0.10 mm
    probe so the horizontal top has no intentional black window.
    """

    cap = float(top_cap_mm)
    if not math.isfinite(cap) or cap < 0.0 or cap >= float(z1_mm) - float(z0_mm):
        raise CompactBlackRadialCouponError("Top-cap thickness is invalid")
    core_top_z = float(z1_mm) - cap

    outer_bottom = _rectangle(_outer_bounds(z0_mm), z0_mm)
    outer_top = _rectangle(_outer_bounds(z1_mm), z1_mm)
    inner_bottom = _rectangle(
        _equal_normal_core_bounds(z0_mm, thickness_mm), z0_mm
    )
    inner_top = _rectangle(
        _equal_normal_core_bounds(core_top_z, thickness_mm), core_top_z
    )
    shell_vertices = np.vstack((outer_bottom, outer_top, inner_bottom, inner_top))
    shell_faces: list[tuple[int, int, int]] = []
    for index in range(4):
        following = (index + 1) % 4
        # Outer side.
        shell_faces.extend(
            ((index, following, 4 + following), (index, 4 + following, 4 + index))
        )
        # Inner side, wound into the cavity.
        inner_i = 8 + index
        inner_j = 8 + following
        inner_top_i = 12 + index
        inner_top_j = 12 + following
        shell_faces.extend(
            ((inner_i, inner_top_j, inner_j), (inner_i, inner_top_i, inner_top_j))
        )
        # Bottom annulus.  The core opening is not covered.
        shell_faces.extend(
            (
                (index, inner_j, following),
                (index, inner_i, inner_j),
            )
        )
        if cap <= 0.0:
            # Ordinary band: an annulus exposes the core on the upper contact
            # plane, exactly as at the lower contact plane.
            shell_faces.extend(
                (
                    (4 + index, 4 + following, inner_top_j),
                    (4 + index, inner_top_j, inner_top_i),
                )
            )
    if cap > 0.0:
        # Full external top and the downward-facing cavity ceiling.  The
        # ceiling is the exact opposite of the black core's upper face.
        shell_faces.extend(((4, 5, 6), (4, 6, 7)))
        shell_faces.extend(((12, 14, 13), (12, 15, 14)))
    shell_faces_array = np.asarray(shell_faces, dtype=np.int32)
    if _signed_volume(shell_vertices, shell_faces_array) < 0.0:
        shell_faces_array = shell_faces_array[:, [0, 2, 1]]
    core_vertices, core_faces = _frustum_mesh(
        z0_mm, core_top_z, inset_mm=thickness_mm
    )
    _assert_solid(shell_vertices, shell_faces_array, "white radial shell")
    _assert_solid(core_vertices, core_faces, "black radial core")
    outer_vertices, outer_faces = _frustum_mesh(z0_mm, z1_mm)
    outer_volume = _signed_volume(outer_vertices, outer_faces)
    combined = _signed_volume(shell_vertices, shell_faces_array) + _signed_volume(
        core_vertices, core_faces
    )
    if not math.isclose(combined, outer_volume, rel_tol=0.0, abs_tol=1.0e-7):
        raise CompactBlackRadialCouponError("Radial shell/core volume is not conserved")
    # Each loop contributes two outer-side, two inner-side, and two bottom
    # triangles, plus two top-annulus triangles for uncapped bands.
    stride = 8 if cap <= 0.0 else 6
    shell_inner_faces = shell_faces_array[
        np.asarray([stride * edge + offset for edge in range(4) for offset in (2, 3)])
    ]
    core_side_faces = core_faces[4:]
    shell_by_key = _oriented_triangle_map(shell_vertices, shell_inner_faces)
    core_by_key = _oriented_triangle_map(core_vertices, core_side_faces)
    if set(shell_by_key) != set(core_by_key):
        raise CompactBlackRadialCouponError(
            "White shell and black core do not share the exact side interface"
        )
    if any(
        float(np.dot(shell_by_key[key], core_by_key[key])) > -0.999999
        for key in shell_by_key
    ):
        raise CompactBlackRadialCouponError(
            "White shell and black core interface is not oppositely wound"
        )
    if cap > 0.0:
        shell_ceiling = shell_faces_array[-2:]
        core_ceiling = core_faces[2:4]
        shell_top_map = _oriented_triangle_map(shell_vertices, shell_ceiling)
        core_top_map = _oriented_triangle_map(core_vertices, core_ceiling)
        if set(shell_top_map) != set(core_top_map) or any(
            float(np.dot(shell_top_map[key], core_top_map[key])) > -0.999999
            for key in shell_top_map
        ):
            raise CompactBlackRadialCouponError(
                "White top cap and black core do not share an exact interface"
            )
    return shell_vertices, shell_faces_array, core_vertices, core_faces


def _oriented_triangle_map(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> dict[tuple[tuple[float, float, float], ...], np.ndarray]:
    output: dict[tuple[tuple[float, float, float], ...], np.ndarray] = {}
    vertices = np.asarray(vertices, dtype=np.float64)
    for face in np.asarray(faces, dtype=np.int64):
        triangle = vertices[face]
        key = tuple(
            sorted(tuple(round(float(value), 10) for value in point) for point in triangle)
        )
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        length = float(np.linalg.norm(normal))
        if length <= 1.0e-12 or key in output:
            raise CompactBlackRadialCouponError(
                "A radial interface triangle is degenerate or duplicated"
            )
        output[key] = normal / length
    return output


def _expected_outer_volume() -> float:
    taper_height = MODEL_HEIGHT_MM - IDENTIFIER_LAYER_HEIGHT_MM
    taper_volume = (
        taper_height
        * (BASE_SIZE_MM**2 + BASE_SIZE_MM * TOP_SIZE_MM + TOP_SIZE_MM**2)
        / 3.0
    )
    return BASE_SIZE_MM**2 * IDENTIFIER_LAYER_HEIGHT_MM + taper_volume


def _assert_outer_band_partition(identifier_code: str = "Z") -> float:
    """Prove exact contacts and full tagged-frustum volume."""

    tiles = _identifier_tiles(identifier_code)
    upper_base = _frustum_mesh(IDENTIFIER_LAYER_HEIGHT_MM, BAND_Z_MM[1])
    meshes = [upper_base] + [
        _frustum_mesh(stage.z0_mm, stage.z1_mm)
        for stage in compact_stages()[1:]
    ]
    total_volume = sum(
        _signed_volume(tile.vertices_mm, tile.faces) for tile in tiles
    ) + sum(_signed_volume(vertices, faces) for vertices, faces in meshes)
    expected_volume = _expected_outer_volume()
    if not math.isclose(total_volume, expected_volume, rel_tol=0.0, abs_tol=1.0e-7):
        raise CompactBlackRadialCouponError(
            "Exact-contact bands do not conserve the full frustum volume"
        )
    tile_top_area = sum(
        (tile.bounds_xy_mm[1] - tile.bounds_xy_mm[0])
        * (tile.bounds_xy_mm[3] - tile.bounds_xy_mm[2])
        for tile in tiles
    )
    if not math.isclose(
        tile_top_area, BASE_SIZE_MM**2, rel_tol=0.0, abs_tol=1.0e-9
    ) or _outer_bounds(IDENTIFIER_LAYER_HEIGHT_MM) != (
        0.0,
        BASE_SIZE_MM,
        0.0,
        BASE_SIZE_MM,
    ):
        raise CompactBlackRadialCouponError(
            "Identifier tiles do not meet the upper frustum exactly"
        )
    for index in range(len(meshes) - 1):
        first_vertices, first_faces = meshes[index]
        second_vertices, second_faces = meshes[index + 1]
        first_map = _oriented_triangle_map(first_vertices, first_faces[2:4])
        second_map = _oriented_triangle_map(second_vertices, second_faces[:2])
        if set(first_map) != set(second_map) or any(
            float(np.dot(first_map[key], second_map[key])) > -0.999999
            for key in first_map
        ):
            raise CompactBlackRadialCouponError(
                f"Frustum bands {index + 1}/{index + 2} do not touch exactly"
            )
    return total_volume


def build_compact_conventional_coupon(
    *,
    identifier_code: str = "Z",
) -> CompactPyramidMesh:
    """Build exact-contact bands and a Z-tagged first layer."""

    vertices_out: list[np.ndarray] = []
    faces_out: list[np.ndarray] = []
    face_parts: list[np.ndarray] = []
    face_states: list[np.ndarray] = []
    vertex_states: list[np.ndarray] = []
    part_names: list[str] = []
    part_keys: list[str] = []
    part_face_counts: list[int] = []
    part_vertex_counts: list[int] = []
    offset = 0
    part_state_indices: list[int] = []

    def append_part(
        *,
        vertices: np.ndarray,
        faces: np.ndarray,
        state: int,
        name: str,
        key: str,
    ) -> None:
        nonlocal offset
        vertices_out.append(vertices)
        faces_out.append(faces + offset)
        face_parts.append(np.full(len(faces), len(part_names), dtype=np.int16))
        face_states.append(np.full(len(faces), state, dtype=np.int16))
        vertex_states.append(np.full(len(vertices), state, dtype=np.int16))
        part_names.append(name)
        part_keys.append(key)
        part_face_counts.append(len(faces))
        part_vertex_counts.append(len(vertices))
        part_state_indices.append(state)
        offset += len(vertices)

    for tile in _identifier_tiles(identifier_code):
        state = 0 if tile.color == "black" else 1
        append_part(
            vertices=tile.vertices_mm,
            faces=tile.faces,
            state=state,
            name=(
                f"Bottom {tile.code} identifier {tile.color} tile {tile.index + 1}"
            ),
            key=f"bottom_{tile.code.lower()}_{tile.color}_{tile.index + 1}",
        )
    base_vertices, base_faces = _frustum_mesh(
        IDENTIFIER_LAYER_HEIGHT_MM,
        BAND_Z_MM[1],
    )
    append_part(
        vertices=base_vertices,
        faces=base_faces,
        state=CONVENTIONAL_STATE_INDICES[0],
        name="Frustum band 1 upper - White 100%",
        key="white_100_upper",
    )
    for stage in compact_stages()[1:]:
        vertices, faces = _frustum_mesh(stage.z0_mm, stage.z1_mm)
        append_part(
            vertices=vertices,
            faces=faces,
            state=stage.conventional_state_index,
            name=f"Frustum band {stage.index + 1} - {stage.label}",
            key=stage.key,
        )
    _assert_outer_band_partition(identifier_code)
    return CompactPyramidMesh(
        vertices_mm=np.vstack(vertices_out),
        faces=np.vstack(faces_out),
        face_part_ids=np.concatenate(face_parts),
        vertex_states=np.concatenate(vertex_states),
        palette_indices=np.concatenate(face_states),
        part_names=tuple(part_names),
        part_keys=tuple(part_keys),
        part_face_counts=tuple(part_face_counts),
        part_vertex_counts=tuple(part_vertex_counts),
        part_state_indices=tuple(part_state_indices),
    )


def _coupon_palette() -> PaletteSettings:
    enabled = [False] * mixer.PALETTE_STATE_COUNT
    for state in {0, *CONVENTIONAL_STATE_INDICES}:
        enabled[state] = True
    return PaletteSettings(
        material="PLA",
        palette_state_count=32,
        physical_hex=list(PHYSICAL_HEX),
        enabled_states=enabled,
        mix_ratios_b=[33] * len(mixer.PAIR_INDICES),
        secondary_mix_ratios_b=[67] * len(mixer.PAIR_INDICES),
        output_mix_ratios_b=mixer.black_output_ratio_preset(0),
    )


def _local_faces(faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    unique, inverse = np.unique(np.asarray(faces).reshape(-1), return_inverse=True)
    return unique, inverse.reshape((-1, 3)).astype(np.int32)


def _prepared_coupon(
    coupon: CompactPyramidMesh,
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
        path=Path("purpose_built_large_black_radial_frustum.obj"),
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
        part_marker_kind="large_black_radial_frustum",
        has_explicit_parts=True,
    )
    area = float(areas_unit.sum())
    volume_mm3 = 0.0
    for part_id in range(len(coupon.part_names)):
        selected = coupon.faces[coupon.face_part_ids == part_id]
        used, local = _local_faces(selected)
        volume_mm3 += _signed_volume(coupon.vertices_mm[used], local)
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
            "purpose_built_large_black_radial_frustum": True,
        },
        source_area_unit=area,
        source_volume_unit=volume_mm3 / MODEL_HEIGHT_MM**3,
        simplified_area_unit=area,
        simplified_volume_unit=volume_mm3 / MODEL_HEIGHT_MM**3,
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
            "repair_method": "purpose_built_exact_contact_frustum_bands_and_tag",
            "compact_black_radial_coupon": {
                "schema": COMPACT_COUPON_SCHEMA,
                "method": "compact-conventional-z-ratio",
                "geometry_version": GEOMETRY_VERSION,
            },
        },
    )
    prepared._hotfix_subtriangle_paint = {}
    face_rgb = palette_rgb[coupon.palette_indices]
    counts = np.bincount(coupon.palette_indices, minlength=32)
    areas_mm2 = areas_unit * MODEL_HEIGHT_MM**2
    by_area = np.bincount(coupon.palette_indices, weights=areas_mm2, minlength=32)
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


def _process_settings(wall_generator: str) -> dict[str, object]:
    generator = str(wall_generator).strip().lower()
    if generator not in {"classic", "arachne"}:
        raise CompactBlackRadialCouponError(
            f"Unsupported compact coupon wall generator: {wall_generator!r}"
        )
    settings: dict[str, object] = {
        "print_settings_id": (
            "0.10 Large Frustum Black-Radial Classic Probe "
            "@Snapmaker U1 (0.4 nozzle)"
        ),
        "layer_height": "0.1",
        "initial_layer_print_height": "0.2",
        "adaptive_layer_height": "0",
        "wall_loops": "1",
        "wall_generator": generator,
        "detect_thin_wall": "1" if generator == "classic" else "0",
        "only_one_wall_top": "0",
        "interface_shells": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "sparse_infill_density": "15%",
        "top_shell_layers": "2",
        "top_shell_thickness": "0.2",
        "bottom_shell_layers": "2",
        "bottom_shell_thickness": "0.2",
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
                    "0.10 Large Frustum Black-Radial Arachne Probe "
                    "@Snapmaker U1 (0.4 nozzle)"
                ),
                "wall_distribution_count": "1",
                "min_bead_width": "25%",
                "initial_layer_min_bead_width": "85%",
                "min_feature_size": "20%",
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
    for stage in compact_stages():
        state = stage.conventional_state_index
        if stage.index > 0:
            left, right, partner_percent = print_specs[state - 4]
            if (left, right) != (0, 1):
                raise CompactBlackRadialCouponError(
                    "A compact mixed state is not the F1/F2 pair"
                )
            effective_black = 1.0 - mixer.orca_effective_mix_ratio(
                partner_percent / 100.0
            )
            cycle_layers = max(1, round(1.0 / effective_black))
            cadence = f"1 black / {cycle_layers - 1} white"
        else:
            partner_percent = 100
            effective_black = 0.0
            cycle_layers = 0
            cadence = "white only"
        rows.append(
            {
                "stage_index": stage.index,
                "stage_key": stage.key,
                "stage_label": stage.label,
                "z0_mm": stage.z0_mm,
                "z1_mm": stage.z1_mm,
                "height_mm": stage.z1_mm - stage.z0_mm,
                "conventional_state_id": state + 1,
                "requested_white_percent": int(partner_percent),
                "effective_black_percent": round(effective_black * 100.0, 4),
                "cadence": cadence,
                "cadence_layers": cycle_layers,
                "radial_shell_thickness_mm": stage.radial_thickness_mm,
                "radial_top_cap_mm": (
                    TOP_CAP_THICKNESS_MM
                    if stage.index == len(STAGE_KEYS) - 1
                    else 0.0
                ),
                "conventional_bottom_identifier": "Z",
                "radial_classic_bottom_identifier": "C",
                "radial_arachne_bottom_identifier": "A",
            }
        )
    return rows


def _coupon_metadata(
    method: str,
    *,
    wall_generator: str,
) -> dict[str, object]:
    generator = str(wall_generator).strip().lower()
    identifier_code = (
        "Z"
        if method == "compact-conventional-z-ratio"
        else ("A" if generator == "arachne" else "C")
    )
    bands = _stage_records()
    if method != "compact-conventional-z-ratio":
        for band in bands:
            band["reference_conventional_black_percent"] = band.pop(
                "effective_black_percent"
            )
            band["radial_effective_black_percent"] = None
            band["calibrated"] = False
    return {
        "schema": COMPACT_COUPON_SCHEMA,
        "method": method,
        "geometry_version": GEOMETRY_VERSION,
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "calibrated": False,
        "physical_materials_only": method != "compact-conventional-z-ratio",
        "physical_slots_used": [1, 2],
        "physical_slots": [
            {"slot": index + 1, "label": label, "hex": color}
            for index, (label, color) in enumerate(
                zip(PHYSICAL_LABELS, PHYSICAL_HEX, strict=True)
            )
        ],
        "dimensions_mm": [BASE_SIZE_MM, BASE_SIZE_MM, MODEL_HEIGHT_MM],
        "base_mm": [BASE_SIZE_MM, BASE_SIZE_MM],
        "top_face_mm": [TOP_SIZE_MM, TOP_SIZE_MM],
        "top_face_bounds_mm": [
            APEX_XY_MM[0],
            APEX_XY_MM[0] + TOP_SIZE_MM,
            APEX_XY_MM[1],
            APEX_XY_MM[1] + TOP_SIZE_MM,
            MODEL_HEIGHT_MM,
        ],
        "band_z_mm": list(BAND_Z_MM),
        "bands": bands,
        "bottom_identifier": {
            "code": identifier_code,
            "meaning": {
                "Z": "conventional Z-cadence Ratio",
                "C": "radial Classic",
                "A": "radial Arachne",
            }[identifier_code],
            "z_range_mm": [0.0, IDENTIFIER_LAYER_HEIGHT_MM],
            "black_extruder": BLACK_EXTRUDER,
            "white_extruder": WHITE_EXTRUDER,
            "exact_black_white_partition": True,
            "readable_from_finished_underside": True,
            "stored_x_mirrored": True,
        },
        "process": _process_settings(generator),
        "radial_semantics": {
            "control_variable": "equal-normal white shell thickness",
            "pure_white_base_above_identifier": True,
            "bottom_identifier_black_exception": True,
            "pure_black_apex": False,
            "mixed_black_is_core_only": True,
            "outer_surface_material": "physical white F2",
            "horizontal_top_cap_mm": TOP_CAP_THICKNESS_MM,
            "horizontal_top_surface_material": "physical white F2",
            "intentional_black_top_window": False,
            "shell_thickness_mm": [
                value for value in RADIAL_THICKNESS_MM if value not in {None, 0.0}
            ],
            "wall_generator": generator,
            "classic_sub_line_width_probe": generator == "classic",
            "arachne_min_feature_percent": 20 if generator == "arachne" else None,
            "arachne_min_bead_percent": 25 if generator == "arachne" else None,
            "arachne_min_bead_mm": 0.10 if generator == "arachne" else None,
        },
    }


def build_compact_radial_coupon(
    *,
    wall_generator: str = "classic",
) -> RadialExportPackage:
    """Build five black-core/white-shell bands and a C/A-tagged first layer."""

    generator = str(wall_generator).strip().lower()
    if generator not in {"classic", "arachne"}:
        raise CompactBlackRadialCouponError(
            f"Unsupported compact coupon wall generator: {wall_generator!r}"
        )
    method = (
        "large-frustum-radial-physical-thickness-arachne"
        if generator == "arachne"
        else "large-frustum-radial-physical-thickness"
    )
    profile = (
        RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_ARACHNE_010
        if generator == "arachne"
        else RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_010
    )
    cores: list[RadialExportPart] = []
    shells: list[RadialExportPart] = []
    interfaces: list[dict[str, object]] = []
    identifier_code = "A" if generator == "arachne" else "C"
    for tile in _identifier_tiles(identifier_code):
        target = cores if tile.color == "black" else shells
        target.append(
            RadialExportPart(
                name=(
                    f"Bottom {identifier_code} identifier {tile.color} "
                    f"tile {tile.index + 1}"
                ),
                role=(
                    "pure_black_core"
                    if tile.color == "black"
                    else "partner_outer_shell"
                ),
                vertices_mm=tile.vertices_mm,
                faces=tile.faces,
                extruder=(BLACK_EXTRUDER if tile.color == "black" else WHITE_EXTRUDER),
                source_state=(1 if tile.color == "black" else 2),
                metadata={
                    "identifier_code": identifier_code,
                    "identifier_tile_index": tile.index,
                    "identifier_color": tile.color,
                    "bounds_xy_mm": list(tile.bounds_xy_mm),
                    "z0_mm": 0.0,
                    "z1_mm": IDENTIFIER_LAYER_HEIGHT_MM,
                    "exact_partition": True,
                    "readable_from_finished_underside": True,
                },
            )
        )
    base_vertices, base_faces = _frustum_mesh(
        IDENTIFIER_LAYER_HEIGHT_MM,
        BAND_Z_MM[1],
    )
    shells.append(
        RadialExportPart(
            name="Frustum band 1 upper - pure white",
            role="partner_outer_shell",
            vertices_mm=base_vertices,
            faces=base_faces,
            extruder=WHITE_EXTRUDER,
            source_state=2,
            metadata={
                "stage_index": 0,
                "stage": STAGE_KEYS[0],
                "z0_mm": IDENTIFIER_LAYER_HEIGHT_MM,
                "z1_mm": BAND_Z_MM[1],
                "pure_white_control": True,
            },
        )
    )
    for stage in compact_stages()[1:]:
        common = {
            "stage_index": stage.index,
            "stage": stage.key,
            "z0_mm": stage.z0_mm,
            "z1_mm": stage.z1_mm,
            "reference_conventional_black_percent": (
                stage.effective_black_fraction * 100.0
            ),
            "radial_effective_black_percent": None,
            "calibrated": False,
            "source_conventional_state": stage.conventional_state_index + 1,
        }
        thickness = float(stage.radial_thickness_mm or 0.0)
        top_cap = (
            TOP_CAP_THICKNESS_MM
            if stage.index == len(STAGE_KEYS) - 1
            else 0.0
        )
        shell_vertices, shell_faces, core_vertices, core_faces = (
            _shell_and_core_meshes(
                stage.z0_mm,
                stage.z1_mm,
                thickness,
                top_cap_mm=top_cap,
            )
        )
        cores.append(
            RadialExportPart(
                name=f"{stage.label} - black core",
                role="pure_black_core",
                vertices_mm=core_vertices,
                faces=core_faces,
                extruder=BLACK_EXTRUDER,
                source_state=stage.conventional_state_index + 1,
                metadata={
                    **common,
                    "shell_thickness_mm": thickness,
                    "top_cap_mm": top_cap,
                },
            )
        )
        shells.append(
            RadialExportPart(
                name=f"{stage.label} - white shell",
                role="partner_outer_shell",
                vertices_mm=shell_vertices,
                faces=shell_faces,
                extruder=WHITE_EXTRUDER,
                source_state=stage.conventional_state_index + 1,
                metadata={
                    **common,
                    "shell_thickness_mm": thickness,
                    "top_cap_mm": top_cap,
                    "full_horizontal_top_cap": top_cap > 0.0,
                },
            )
        )
        interfaces.append(
            {
                "stage_index": stage.index,
                "stage": stage.key,
                "shell_thickness_mm": thickness,
                "offset_mode": "equal-normal-side-planes",
                "exact_coordinate_triangles": True,
                "opposite_winding": True,
                "gap_mm": 0.0,
                "positive_overlap_mm3": 0.0,
                "volume_conserved": True,
                "top_cap_mm": top_cap,
                "top_cap_interface_exact": top_cap > 0.0,
            }
        )
    total_part_volume = sum(
        _signed_volume(np.asarray(part.vertices_mm), np.asarray(part.faces))
        for part in cores + shells
    )
    expected_volume = _assert_outer_band_partition(identifier_code)
    if not math.isclose(
        total_part_volume, expected_volume, rel_tol=0.0, abs_tol=1.0e-7
    ):
        raise CompactBlackRadialCouponError(
            "Physical radial parts do not conserve the whole frustum volume"
        )
    coupon_metadata = _coupon_metadata(
        method,
        wall_generator=generator,
    )
    coupon_metadata.update(
        {
            "legacy_fullspectrum_ratios_used": False,
            "ratio_definitions": 0,
            "cycle_definitions": 0,
            "virtual_mix_definitions": 0,
            "painted_triangles": 0,
            "positive_overlap_mm3": 0.0,
            "gap_mm": 0.0,
            "shared_interface_partition_exact": True,
            "external_surface_coverage_exact": True,
            "interfaces": interfaces,
        }
    )
    return RadialExportPackage(
        parts=tuple(cores + shells),
        physical_hex=PHYSICAL_HEX,
        black_extruder=BLACK_EXTRUDER,
        metadata={"compact_black_radial_coupon": coupon_metadata},
        layer_height_mm=LAYER_HEIGHT_MM,
        initial_layer_height_mm=INITIAL_LAYER_HEIGHT_MM,
        renderer="radial",
        process_profile=profile,
    )


def _rewrite_zip_members(path: Path, replacements: Mapping[str, bytes]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as destination:
            seen: set[str] = set()
            for info in source.infolist():
                if info.filename in seen:
                    raise CompactBlackRadialCouponError(
                        "Cannot patch an archive with duplicate members"
                    )
                seen.add(info.filename)
                destination.writestr(
                    info,
                    replacements.get(info.filename, source.read(info.filename)),
                )
            for name, payload in replacements.items():
                if name not in seen:
                    destination.writestr(name, payload)
        with zipfile.ZipFile(temporary, "r") as reopened:
            if reopened.testzip() is not None:
                raise CompactBlackRadialCouponError(
                    "Patched compact coupon has a ZIP CRC failure"
                )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_conventional_3mf(path: Path) -> Mapping[str, object]:
    coupon = build_compact_conventional_coupon()
    palette = _coupon_palette()
    prepared, colors = _prepared_coupon(coupon, palette)
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
    project.update(_process_settings("classic"))
    metadata = _coupon_metadata(
        "compact-conventional-z-ratio",
        wall_generator="classic",
    )
    _rewrite_zip_members(
        path,
        {
            "Metadata/project_settings.config": json.dumps(
                project, ensure_ascii=False, indent=2
            ).encode("utf-8"),
            _COMPACT_METADATA_MEMBER: json.dumps(
                metadata, ensure_ascii=False, indent=2
            ).encode("utf-8"),
        },
    )
    return validate_compact_black_radial_coupon_3mf(
        path,
        method="compact-conventional-z-ratio",
    )


def _write_radial_3mf(
    path: Path,
    *,
    wall_generator: str,
) -> Mapping[str, object]:
    generator = str(wall_generator).strip().lower()
    package = build_compact_radial_coupon(wall_generator=generator)
    write_radial_3mf_atomic(
        path,
        package,
        title=f"large black radial frustum 0.10 mm {generator}",
    )
    method = (
        "large-frustum-radial-physical-thickness-arachne"
        if generator == "arachne"
        else "large-frustum-radial-physical-thickness"
    )
    return validate_compact_black_radial_coupon_3mf(path, method=method)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_project(archive: zipfile.ZipFile) -> dict[str, object]:
    value = json.loads(
        archive.read("Metadata/project_settings.config").decode("utf-8")
    )
    if not isinstance(value, dict):
        raise CompactBlackRadialCouponError("Project settings are not an object")
    return value


def _expected_conventional_project() -> dict[str, object]:
    palette = _coupon_palette()
    definitions = engine.make_portable_mixed_definitions(
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
        palette_state_count=palette.palette_state_count,
        output_mix_ratios_b=palette.output_mix_ratios_b,
    )
    expected: dict[str, object] = {
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
        "mixed_filament_definitions": definitions,
        "mixed_filament_height_lower_bound": "0.04",
        "mixed_filament_height_upper_bound": "0.16",
        "chroma_matter_palette_mode": palette.color_mode,
    }
    expected.update(engine.FULL_SPECTRUM_STABLE_CADENCE_SETTINGS)
    expected.update(_process_settings("classic"))
    return expected


def _mesh_from_object(obj: ET.Element) -> tuple[np.ndarray, np.ndarray, list[str]]:
    meshes = obj.findall(f"{{{_CORE_NS}}}mesh")
    if len(meshes) != 1 or list(obj) != meshes or meshes[0].attrib:
        raise CompactBlackRadialCouponError(
            "Each compact coupon object must contain exactly one mesh"
        )
    mesh = meshes[0]
    vertex_containers = mesh.findall(f"{{{_CORE_NS}}}vertices")
    triangle_containers = mesh.findall(f"{{{_CORE_NS}}}triangles")
    if (
        len(vertex_containers) != 1
        or len(triangle_containers) != 1
        or list(mesh) != [vertex_containers[0], triangle_containers[0]]
    ):
        raise CompactBlackRadialCouponError("Compact coupon mesh structure drifted")
    vertex_elements = list(vertex_containers[0])
    triangle_elements = list(triangle_containers[0])
    if any(
        item.tag != f"{{{_CORE_NS}}}vertex" or set(item.attrib) != {"x", "y", "z"}
        for item in vertex_elements
    ):
        raise CompactBlackRadialCouponError("Compact coupon vertex contract drifted")
    allowed_triangle_keys = {"v1", "v2", "v3", "paint_color"}
    for item in triangle_elements:
        if item.tag != f"{{{_CORE_NS}}}triangle" or not {
            "v1",
            "v2",
            "v3",
        }.issubset(item.attrib):
            raise CompactBlackRadialCouponError("Compact coupon triangle contract drifted")
        if set(item.attrib) not in ({"v1", "v2", "v3"}, allowed_triangle_keys):
            raise CompactBlackRadialCouponError("Compact coupon triangle property drifted")
    vertices = np.asarray(
        [
            [float(item.attrib[axis]) for axis in ("x", "y", "z")]
            for item in vertex_elements
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            [int(item.attrib[key]) for key in ("v1", "v2", "v3")]
            for item in triangle_elements
        ],
        dtype=np.int32,
    )
    paints = [item.attrib.get("paint_color", "") for item in triangle_elements]
    return vertices, faces, paints


def _validate_model_settings_parts(
    archive: zipfile.ZipFile,
    *,
    coupon: CompactPyramidMesh,
) -> None:
    root = ET.fromstring(archive.read("Metadata/model_settings.config"))
    if root.tag != "config" or root.attrib or [item.tag for item in root] != [
        "object",
        "plate",
    ]:
        raise CompactBlackRadialCouponError("Model-settings structure drifted")
    config_object, plate = list(root)
    expected_parent_id = str(len(coupon.part_names) + 1)
    if config_object.attrib != {"id": expected_parent_id}:
        raise CompactBlackRadialCouponError("Model-settings object ID drifted")
    object_metadata = config_object.findall("metadata")
    keyed = [item for item in object_metadata if "key" in item.attrib]
    unkeyed = [item for item in object_metadata if "key" not in item.attrib]
    keyed_values = {
        item.attrib.get("key", ""): item.attrib.get("value", "") for item in keyed
    }
    if (
        len(keyed) != 2
        or set(keyed_values) != {"name", "extruder"}
        or keyed_values.get("extruder") != "1"
        or len(unkeyed) != 1
        or unkeyed[0].attrib != {"face_count": str(len(coupon.faces))}
    ):
        raise CompactBlackRadialCouponError("Model-settings object metadata drifted")
    parts = config_object.findall("part")
    if len(parts) != len(coupon.part_names):
        raise CompactBlackRadialCouponError("Model-settings part count drifted")
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
    for index, part in enumerate(parts):
        if part.attrib != {"id": str(index + 1), "subtype": "normal_part"}:
            raise CompactBlackRadialCouponError("Model-settings part ID drifted")
        metadata_items = part.findall("metadata")
        if any(set(item.attrib) != {"key", "value"} for item in metadata_items):
            raise CompactBlackRadialCouponError("Model-settings metadata drifted")
        values = {item.attrib["key"]: item.attrib["value"] for item in metadata_items}
        if len(values) != len(metadata_items) or set(values) != expected_keys:
            raise CompactBlackRadialCouponError("Model-settings part allowlist drifted")
        expected_values = {
            "name": coupon.part_names[index],
            "matrix": "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1",
            "source_file": "purpose_built_large_black_radial_frustum.obj",
            "source_object_id": "0",
            "source_volume_id": str(index),
            "source_offset_x": "0",
            "source_offset_y": "0",
            "source_offset_z": "0",
            "extruder": "1",
        }
        if values != expected_values:
            raise CompactBlackRadialCouponError("Model-settings part values drifted")
        stats = part.findall("mesh_stat")
        if len(stats) != 1 or stats[0].attrib != {
            "face_count": str(coupon.part_face_counts[index]),
            "edges_fixed": "0",
            "degenerate_facets": "0",
            "facets_removed": "0",
            "facets_reversed": "0",
            "backwards_edges": "0",
        }:
            raise CompactBlackRadialCouponError("Model-settings mesh stats drifted")
        if [item.tag for item in part] != ["metadata"] * 9 + ["mesh_stat"]:
            raise CompactBlackRadialCouponError("Model-settings part order drifted")
    plate_metadata = plate.findall("metadata")
    if plate.attrib or {
        item.attrib.get("key", ""): item.attrib.get("value", "")
        for item in plate_metadata
    } != {
        "plater_id": "1",
        "plater_name": "Full Spectrum 4 Filaments",
        "locked": "false",
        "filament_map_mode": "Auto For Flush",
    }:
        raise CompactBlackRadialCouponError("Model-settings plate drifted")
    instances = plate.findall("model_instance")
    if len(instances) != 1:
        raise CompactBlackRadialCouponError("Model-settings instance drifted")
    instance_values = {
        item.attrib.get("key", ""): item.attrib.get("value", "")
        for item in instances[0].findall("metadata")
    }
    if instance_values != {
        "object_id": expected_parent_id,
        "instance_id": "0",
        "identify_id": "1",
    }:
        raise CompactBlackRadialCouponError("Model-settings instance metadata drifted")


def _validate_conventional_archive(
    path: Path,
    archive: zipfile.ZipFile,
    metadata: Mapping[str, object],
) -> dict[str, object]:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise CompactBlackRadialCouponError("Conventional coupon has duplicate members")
    if set(names) != _CONVENTIONAL_ARCHIVE_MEMBERS:
        raise CompactBlackRadialCouponError("Conventional coupon member allowlist drifted")
    for name, expected in _CONVENTIONAL_STATIC_MEMBERS.items():
        if archive.read(name) != expected:
            raise CompactBlackRadialCouponError(
                f"Conventional archive relationship drifted: {name}"
            )
    expected_metadata = _coupon_metadata(
        "compact-conventional-z-ratio", wall_generator="classic"
    )
    if dict(metadata) != expected_metadata:
        raise CompactBlackRadialCouponError("Conventional coupon metadata drifted")
    project = _read_project(archive)
    expected_project = _expected_conventional_project()
    if set(project) != set(expected_project) or any(
        project.get(key) != value for key, value in expected_project.items()
    ):
        raise CompactBlackRadialCouponError("Conventional project settings drifted")
    if project.get("filament_colour") != list(PHYSICAL_HEX):
        raise CompactBlackRadialCouponError("White/black filament colours drifted")
    coupon = build_compact_conventional_coupon()
    child = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    resources = child.findall(f"{{{_CORE_NS}}}resources")
    if child.tag != f"{{{_CORE_NS}}}model" or child.attrib.get("unit") != "millimeter":
        raise CompactBlackRadialCouponError("Conventional child model drifted")
    if len(resources) != 1:
        raise CompactBlackRadialCouponError("Conventional resources drifted")
    objects = resources[0].findall(f"{{{_CORE_NS}}}object")
    if len(objects) != len(coupon.part_names) or list(resources[0]) != objects:
        raise CompactBlackRadialCouponError(
            "Conventional frustum part count drifted"
        )
    observed_states: list[int] = []
    for index, obj in enumerate(objects):
        if obj.attrib.get("id") != str(index + 1) or obj.attrib.get("name") != coupon.part_names[index]:
            raise CompactBlackRadialCouponError("Conventional band identity drifted")
        vertices, faces, paints = _mesh_from_object(obj)
        selected = coupon.faces[coupon.face_part_ids == index]
        used, expected_faces = _local_faces(selected)
        expected_vertices = coupon.vertices_mm[used]
        if vertices.shape != expected_vertices.shape or not np.allclose(
            vertices, expected_vertices, rtol=0.0, atol=1.0e-8
        ):
            raise CompactBlackRadialCouponError("Conventional band vertices drifted")
        if not np.array_equal(faces, expected_faces):
            raise CompactBlackRadialCouponError("Conventional band faces drifted")
        _assert_solid(vertices, faces, f"conventional band {index + 1}")
        if len(set(paints)) != 1 or not paints[0]:
            raise CompactBlackRadialCouponError("Conventional band paint drifted")
        try:
            state = engine.PAINT_CODES.index(paints[0].upper())
        except ValueError as exc:
            raise CompactBlackRadialCouponError("Unknown conventional paint state") from exc
        if state != coupon.part_state_indices[index]:
            raise CompactBlackRadialCouponError("Conventional band state order drifted")
        observed_states.append(state + 1)
    _assert_outer_band_partition("Z")
    expected_observed = [value + 1 for value in coupon.part_state_indices]
    if observed_states != expected_observed:
        raise CompactBlackRadialCouponError("Conventional paint states drifted")
    if set(observed_states) != {1, 2, 5, 11, 17, 23, 24}:
        raise CompactBlackRadialCouponError("Conventional paint allowlist drifted")
    print_specs = mixer.print_palette_mix_specs(
        [33] * len(mixer.PAIR_INDICES),
        [67] * len(mixer.PAIR_INDICES),
        mixer.black_output_ratio_preset(0),
    )
    for state_id in [value + 1 for value in CONVENTIONAL_STATE_INDICES[1:]]:
        left, right, _ratio_b = print_specs[state_id - 5]
        if (left, right) != (0, 1):
            raise CompactBlackRadialCouponError(
                "A conventional mixed band uses F3/F4 instead of F1/F2"
            )
    root = ET.fromstring(archive.read("3D/3dmodel.model"))
    components = [item for item in root.iter() if item.tag.endswith("component")]
    if len(components) != len(coupon.part_names) or any(
        item.attrib.get("objectid") != str(index + 1)
        or item.attrib.get(f"{{{_PRODUCTION_NS}}}path") != "/3D/Objects/object_1.model"
        or item.attrib.get("transform") != "1 0 0 0 1 0 0 0 1 0 0 0"
        for index, item in enumerate(components)
    ):
        raise CompactBlackRadialCouponError("Conventional component contract drifted")
    build_items = [item for item in root.iter() if item.tag.endswith("item")]
    if len(build_items) != 1 or build_items[0].attrib.get("transform") != (
        "1 0 0 0 1 0 0 0 1 128 128 0"
    ):
        raise CompactBlackRadialCouponError("Conventional build transform drifted")
    _validate_model_settings_parts(archive, coupon=coupon)
    return {
        "schema": COMPACT_COUPON_SCHEMA,
        "method": "compact-conventional-z-ratio",
        "valid": True,
        "zip_crc_ok": True,
        "parts": len(coupon.part_names),
        "validated_solid_parts": len(coupon.part_names),
        "observed_state_ids": observed_states,
        "bottom_identifier": "Z",
        "bottom_identifier_readable_from_underside": True,
        "top_face_mm": [TOP_SIZE_MM, TOP_SIZE_MM],
        "top_surface_state_id": CONVENTIONAL_STATE_INDICES[-1] + 1,
        "physical_slots_used": [1, 2],
        "ratio_only": True,
        "layer_height_mm": LAYER_HEIGHT_MM,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _read_radial_meshes(archive: zipfile.ZipFile) -> list[tuple[np.ndarray, np.ndarray]]:
    root = ET.fromstring(archive.read("3D/Objects/radial_parts.model"))
    objects = [item for item in root.iter() if item.tag.endswith("object")]
    result: list[tuple[np.ndarray, np.ndarray]] = []
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
        result.append((vertices, faces))
    return result


def _validate_radial_archive(
    path: Path,
    archive: zipfile.ZipFile,
    *,
    wall_generator: str,
) -> dict[str, object]:
    generator = str(wall_generator).strip().lower()
    expected = build_compact_radial_coupon(wall_generator=generator)
    profile = (
        RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_ARACHNE_010
        if generator == "arachne"
        else RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_010
    )
    proof = validate_radial_3mf(
        path,
        expected_parts=len(expected.parts),
        expected_physical=PHYSICAL_HEX,
        expected_extruders=[part.extruder for part in expected.parts],
        expected_process_profile=profile,
    )
    radial_metadata = json.loads(
        archive.read("Metadata/radial_shell_experimental.json").decode("utf-8")
    )
    generator_metadata = radial_metadata.get("generator_metadata")
    expected_generator = expected.metadata
    if generator_metadata != expected_generator:
        raise CompactBlackRadialCouponError("Radial compact metadata drifted")
    meta_parts = radial_metadata.get("parts")
    if not isinstance(meta_parts, list) or len(meta_parts) != len(expected.parts):
        raise CompactBlackRadialCouponError("Radial compact part metadata drifted")
    for index, (observed, part) in enumerate(zip(meta_parts, expected.parts, strict=True)):
        if not isinstance(observed, Mapping):
            raise CompactBlackRadialCouponError("Radial part metadata is malformed")
        exact = {
            "index": index,
            "name": part.name,
            "role": part.role,
            "extruder": part.extruder,
            "closed_physical_volume": True,
            "source_state": part.source_state,
            "vertices": len(part.vertices_mm),
            "faces": len(part.faces),
            "metadata": part.metadata,
        }
        if any(observed.get(key) != value for key, value in exact.items()):
            raise CompactBlackRadialCouponError(
                f"Radial part identity drifted at part {index + 1}"
            )
        expected_volume = _signed_volume(
            np.asarray(part.vertices_mm), np.asarray(part.faces)
        )
        try:
            observed_volume = float(observed.get("signed_volume_mm3"))
        except (TypeError, ValueError) as exc:
            raise CompactBlackRadialCouponError(
                "Radial part volume metadata is malformed"
            ) from exc
        if not math.isclose(
            observed_volume, expected_volume, rel_tol=0.0, abs_tol=1.0e-8
        ):
            raise CompactBlackRadialCouponError("Radial part volume drifted")
    roles = [part.role for part in expected.parts]
    extruders = [part.extruder for part in expected.parts]
    if any(value not in {1, 2} for value in extruders):
        raise CompactBlackRadialCouponError("Radial physical-tool ordering drifted")
    radial_core_count = sum(
        part.metadata.get("stage_index") in range(1, len(STAGE_KEYS))
        and part.role == "pure_black_core"
        for part in expected.parts
    )
    radial_shell_count = sum(
        part.metadata.get("stage_index") in range(1, len(STAGE_KEYS))
        and part.role == "partner_outer_shell"
        for part in expected.parts
    )
    if radial_core_count != 5 or radial_shell_count != 5:
        raise CompactBlackRadialCouponError("Radial core/shell count drifted")
    wrapper = generator_metadata.get("compact_black_radial_coupon", {})
    if len(wrapper.get("interfaces", [])) != 5:
        raise CompactBlackRadialCouponError("Radial compact interface proof drifted")
    meshes = _read_radial_meshes(archive)
    if len(meshes) != len(expected.parts):
        raise CompactBlackRadialCouponError("Radial compact part count drifted")
    for index, ((vertices, faces), part) in enumerate(zip(meshes, expected.parts, strict=True)):
        expected_vertices = np.asarray(part.vertices_mm, dtype=np.float64)
        expected_faces = np.asarray(part.faces, dtype=np.int32)
        if vertices.shape != expected_vertices.shape or not np.allclose(
            vertices, expected_vertices, rtol=0.0, atol=1.0e-8
        ):
            raise CompactBlackRadialCouponError(
                f"Radial compact vertices drifted at part {index + 1}"
            )
        if not np.array_equal(faces, expected_faces):
            raise CompactBlackRadialCouponError(
                f"Radial compact faces drifted at part {index + 1}"
            )
        _assert_solid(vertices, faces, f"radial part {index + 1}")
    total_volume = sum(_signed_volume(vertices, faces) for vertices, faces in meshes)
    expected_volume = _expected_outer_volume()
    if not math.isclose(total_volume, expected_volume, rel_tol=0.0, abs_tol=1.0e-7):
        raise CompactBlackRadialCouponError("Radial archive volume drifted")
    settings_root = ET.fromstring(archive.read("Metadata/model_settings.config"))
    config_objects = settings_root.findall("object")
    if len(config_objects) != 1 or config_objects[0].attrib != {
        "id": str(len(expected.parts) + 1)
    }:
        raise CompactBlackRadialCouponError("Radial PrintObject ID drifted")
    object_values = {
        item.attrib.get("key", ""): item.attrib.get("value", "")
        for item in config_objects[0].findall("metadata")
        if "key" in item.attrib
    }
    expected_title = f"SLICE ONLY - large black radial frustum 0.10 mm {generator}"
    if object_values.get("name") != expected_title or object_values.get("extruder") != "2":
        raise CompactBlackRadialCouponError(
            "Radial PrintObject name or physical white extruder drifted"
        )
    project = _read_project(archive)
    for key, value in _process_settings(generator).items():
        if project.get(key) != value:
            raise CompactBlackRadialCouponError(
                f"Radial process setting {key} drifted"
            )
    return {
        "schema": COMPACT_COUPON_SCHEMA,
        "method": wrapper["method"],
        "valid": True,
        "zip_crc_ok": proof.zip_crc_ok,
        "parts": proof.parts,
        "validated_solid_parts": len(meshes),
        "interfaces": 5,
        "wall_generator": generator,
        "wall_loops": 1,
        "detect_thin_wall": generator == "classic",
        "physical_materials_only": True,
        "physical_slots_used": [1, 2],
        "bottom_identifier": "A" if generator == "arachne" else "C",
        "bottom_identifier_readable_from_underside": True,
        "top_face_mm": [TOP_SIZE_MM, TOP_SIZE_MM],
        "top_cap_mm": TOP_CAP_THICKNESS_MM,
        "intentional_black_top_window": False,
        "mixed_definition_rows": 0,
        "layer_height_mm": LAYER_HEIGHT_MM,
        "frustum_volume_mm3": expected_volume,
        "sha256": proof.sha256,
        "bytes": proof.bytes,
    }


def validate_compact_black_radial_coupon_3mf(
    path: Path,
    *,
    method: str | None = None,
) -> dict[str, object]:
    path = Path(path)
    if not path.is_file():
        raise CompactBlackRadialCouponError(f"Compact coupon does not exist: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise CompactBlackRadialCouponError("Compact coupon has a ZIP CRC failure")
        if _COMPACT_METADATA_MEMBER in archive.namelist():
            metadata = json.loads(
                archive.read(_COMPACT_METADATA_MEMBER).decode("utf-8")
            )
            detected = metadata.get("method")
            if method is not None and detected != method:
                raise CompactBlackRadialCouponError(
                    f"Compact coupon method differs: {detected!r} != {method!r}"
                )
            if detected != "compact-conventional-z-ratio":
                raise CompactBlackRadialCouponError(
                    f"Unsupported conventional compact method: {detected!r}"
                )
            return _validate_conventional_archive(path, archive, metadata)
        radial_metadata = json.loads(
            archive.read("Metadata/radial_shell_experimental.json").decode("utf-8")
        )
        wrapper = radial_metadata.get("generator_metadata", {}).get(
            "compact_black_radial_coupon", {}
        )
        detected = wrapper.get("method")
        if method is not None and detected != method:
            raise CompactBlackRadialCouponError(
                f"Compact coupon method differs: {detected!r} != {method!r}"
            )
        if detected == "large-frustum-radial-physical-thickness":
            return _validate_radial_archive(path, archive, wall_generator="classic")
        if detected == "large-frustum-radial-physical-thickness-arachne":
            return _validate_radial_archive(path, archive, wall_generator="arachne")
        raise CompactBlackRadialCouponError(
            f"Unsupported radial compact method: {detected!r}"
        )


def _write_mapping(path: Path) -> None:
    fieldnames = [
        "stage_index",
        "stage_key",
        "stage_label",
        "z0_mm",
        "z1_mm",
        "height_mm",
        "conventional_state_id",
        "requested_white_percent",
        "effective_black_percent",
        "cadence",
        "cadence_layers",
        "radial_shell_thickness_mm",
        "radial_top_cap_mm",
        "conventional_bottom_identifier",
        "radial_classic_bottom_identifier",
        "radial_arachne_bottom_identifier",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_stage_records())


def _write_observation_sheet(path: Path) -> None:
    fieldnames = [
        "stage_index",
        "stage_label",
        "z_range_mm",
        "shell_thickness_mm",
        "conventional_outer_black_band_score_0_to_5",
        "radial_classic_outer_black_band_score_0_to_5",
        "radial_arachne_outer_black_band_score_0_to_5",
        "classic_shell_continuous_yes_no",
        "arachne_shell_continuous_yes_no",
        "arachne_line_width_observed_mm",
        "horizontal_top_classic_fully_white_yes_no",
        "horizontal_top_arachne_fully_white_yes_no",
        "bottom_identifier_z_readable_yes_no",
        "bottom_identifier_c_readable_yes_no",
        "bottom_identifier_a_readable_yes_no",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for stage in compact_stages():
            writer.writerow(
                {
                    "stage_index": stage.index,
                    "stage_label": stage.label,
                    "z_range_mm": f"{stage.z0_mm:g}-{stage.z1_mm:g}",
                    "shell_thickness_mm": (
                        ""
                        if stage.radial_thickness_mm is None
                        else f"{stage.radial_thickness_mm:g}"
                    ),
                }
            )


def _readme_ja() -> str:
    return f"""# 大型・角寄せフラスタム 白黒ラジアル検証 v3

旧14 mm試験体より各軸を約3倍にした、底面{BASE_SIZE_MM:g} × {BASE_SIZE_MM:g} mm、高さ{MODEL_HEIGHT_MM:g} mmの1つの連続した切頭ピラミッドです。天面は角側 `(0, 0)` に寄せた {TOP_SIZE_MM:g} × {TOP_SIZE_MM:g} mmの水平面です。X=0面とY=0面は垂直、反対側2面は傾斜しています。

## 3つの3MF

- `ChromaMatter_black_gradient_frustum_v3_conventional_Z_0p10.3mf`: 従来のZ方向Ratio混色。底面記号 `Z`。
- `ChromaMatter_black_gradient_frustum_v3_radial_classic_C_0p10.3mf`: 黒core＋白外皮、Classic。底面記号 `C`。
- `ChromaMatter_black_gradient_frustum_v3_radial_arachne_A_0p10.3mf`: 同じ外形のArachne。底面記号 `A`。

全て通常層0.10 mm、初層0.20 mm、1 wall、100% infill、support/brim/raft OFF、prime tower ONです。プロセス設定は上下面2層／0.20 mmを要求しますが、ラジアル最終段の物理的な白い天面cap自体は下記の通り0.10 mmです。

この大型版の解析体積は約{_expected_outer_volume():,.1f} mm³で、旧14 mm角頂点版の約34倍です。印刷時間は3倍では済みません。3体を同時配置せず、まず各3MFを個別にスライスして、Orcaの見積時間と材料量を確認してください。

## 色帯と水平天面

下から、純白3.0 mm、黒5%を6.0 mm、黒10%を3.0 mm、14.3%を4.2 mm、20%を3.0 mm、25%を3.6 mmです。全て0.10 mm層とRatio周期の整数倍です。旧版の純黒頂点は廃止し、純黒の外面露出は底面識別記号だけに限定しました。

ラジアル外皮厚は順に `0.42 / 0.30 / 0.21 / 0.15 / 0.10 mm` です。厚さは4側面をequal-normalで内側へ移動した設計値です。

最終0.10 mm段では、黒coreを天面より{TOP_CAP_THICKNESS_MM:g} mm下で止め、{TOP_SIZE_MM:g} × {TOP_SIZE_MM:g} mmの水平天面全体を白F2で閉じています。意図的な黒窓はありません。Classic/Arachneで同じ物理形状を使い、水平0.10 mm capが保持・拡幅・欠損するかを比較します。

## 底面識別

初層0.20 mmは黒F1と白F2のexact partitionです。完成品を裏返して−Z側から見たとき正読になるよう、生成XYでは文字をX反転してあります。`Z=従来`、`C=Classic`、`A=Arachne`です。記号以外の評価外形・色帯・ラジアルcore/shellは同一です。

ラジアル側に付けた黒5～25%の名前は、従来Ratio帯との位置対応を示す参照名です。同等の見た目の濃度を再現する校正ではありません。ラジアルの光学的な黒率は未校正で、この試験が比較するのは白外皮の保持、欠損、拡幅、および黒coreの外面露出です。

## 重要：Arachne設定はU1標準外です

Arachneは `min_feature_size=20%`（0.08 mm）、通常層 `min_bead_width=25%`（0.10 mm）、初層のみ85%（約0.34 mm）です。0.10 mm外皮は限界セルです。形状が残るかを調べるprobeであり、0.10 mmの線幅で安全に造形できるという意味ではありません。

Classicは1 wall＋薄壁検出ONです。Arachneは1 wall＋薄壁検出OFFです。どちらも通常のU1推奨プロファイルではなく、実験専用／SLICE ONLYです。

## 必ず行う確認

1. Snapmaker Orcaで3MFを開き、自動修復・結合・回転をしない。
2. `Filament`表示を全層確認し、モデル本体にF1黒とF2白以外がないことを確認する。
3. `Line Width`表示を全層確認する。特に0.21 / 0.15 / 0.10 mm帯で、欠損、拡幅、黒coreの外面露出がないか確認する。
4. 天面は全面白であることを確認する。底面Z/C/A以外の外面へ黒が出た場合は記録する。
5. prime towerを消さず、purge into model/infill/supportを有効にしない。
6. 問題があれば印刷せず、スクリーンショットと`observation_sheet.csv`を残す。

この比較の目的は「従来Ratioの黒い横縞」と「物理白外皮で黒を内部へ隠す方式」を、垂直面・傾斜面・水平天面で比べることです。
"""


def _readme_en() -> str:
    return f"""# Large corner-frustum white/black radial coupon v3

This coupon is approximately three times the old 14 mm specimen in each linear dimension. It is one {BASE_SIZE_MM:g} x {BASE_SIZE_MM:g} x {MODEL_HEIGHT_MM:g} mm corner frustum with a horizontal {TOP_SIZE_MM:g} x {TOP_SIZE_MM:g} mm top at the `(0, 0)` corner. X=0 and Y=0 are vertical; the opposite two sides are sloped.

## Three 3MF projects

- `ChromaMatter_black_gradient_frustum_v3_conventional_Z_0p10.3mf`: conventional Z-cadence Ratio mixing; underside `Z`.
- `ChromaMatter_black_gradient_frustum_v3_radial_classic_C_0p10.3mf`: physical radial shell with Classic walls; underside `C`.
- `ChromaMatter_black_gradient_frustum_v3_radial_arachne_A_0p10.3mf`: the same radial geometry with Arachne walls; underside `A`.

All use 0.10 mm normal layers, a 0.20 mm initial layer, one wall, 100% infill, no support/brim/raft, and a real prime tower. The process requests two top/bottom layers / 0.20 mm, while the physical white top-cap volume in the final radial band is intentionally only 0.10 mm as described below.

The analytical volume of this large coupon is about {_expected_outer_volume():,.1f} mm3, roughly 34 times the old 14 mm corner-apex coupon. Print time will not be merely three times longer. Slice each 3MF separately first, rather than placing all three together, and review Orca's time and material estimates.

## Bands and horizontal top

Bottom to top: 3.0 mm pure white; 6.0 mm at 5% black; 3.0 mm at 10%; 4.2 mm at 14.3%; 3.0 mm at 20%; and 3.6 mm at 25%. Every band is an integer number of 0.10 mm layers and its Ratio cadence. The old pure-black apex was removed; intended external pure black is limited to the underside identifier.

The radial shell thicknesses are `0.42 / 0.30 / 0.21 / 0.15 / 0.10 mm`, using equal-normal offsets from all four side planes. In the final band the black core stops {TOP_CAP_THICKNESS_MM:g} mm below the top, so the complete {TOP_SIZE_MM:g} x {TOP_SIZE_MM:g} mm horizontal top is physical white F2. There is no intentional black top window. Classic and Arachne use identical physical volumes.

## Underside identifiers

The complete first 0.20 mm layer is an exact F1-black/F2-white partition. Its 5 x 7 bitmap is stored X-mirrored so it reads normally when the finished coupon is flipped and viewed from the underside: `Z=conventional`, `C=Classic`, `A=Arachne`.

The 5-25% names on the radial bands are positional references to the conventional Ratio bands. They are not calibrated claims of equivalent visual density. Radial optical black percentage is unknown; this coupon compares white-shell retention, loss or widening, and black-core exposure.

## Important: aggressive non-stock Arachne probe

Arachne uses a 20% minimum feature (0.08 mm), a 25% normal-layer minimum bead (0.10 mm), and an 85% initial-layer minimum bead (about 0.34 mm). The 0.10 mm shell is the limit cell. It tests retention; it is not a claim that a safe true 0.10 mm extrusion line will be produced.

Classic uses one wall with thin-wall detection on. Arachne uses one wall with thin-wall detection off. Neither is the stock U1 process. These projects remain experimental and SLICE ONLY.

## Mandatory Orca checks

1. Open each 3MF without repair, merge, rotation, or setting substitution.
2. Inspect every layer in `Filament`; the model body may use only physical F1 black and F2 white.
3. Inspect every layer in `Line Width`, especially the 0.21 / 0.15 / 0.10 mm bands. Record dropped shells, widening, or black-core exposure.
4. Confirm that the horizontal top is completely white. External black is intentional only in the underside Z/C/A identifier.
5. Keep the prime tower. Do not purge into the model, infill, or support.
6. If preview is unsafe, do not print; save screenshots and fill in `observation_sheet.csv`.

The goal is a same-envelope comparison between conventional black Z bands and a physical white shell on vertical, sloped, and horizontal top surfaces.
"""


def _manifest_entry(path: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def create_compact_black_radial_coupon_bundle(
    output_directory: Path,
) -> CompactBlackRadialCouponBundle:
    output_directory = Path(output_directory)
    if output_directory.exists() and any(output_directory.iterdir()):
        raise CompactBlackRadialCouponError("Compact coupon output must be empty")
    output_directory.mkdir(parents=True, exist_ok=True)

    conventional = output_directory / "ChromaMatter_black_gradient_frustum_v3_conventional_Z_0p10.3mf"
    radial = output_directory / "ChromaMatter_black_gradient_frustum_v3_radial_classic_C_0p10.3mf"
    radial_arachne = output_directory / "ChromaMatter_black_gradient_frustum_v3_radial_arachne_A_0p10.3mf"
    mapping = output_directory / "coupon_map.csv"
    observation = output_directory / "observation_sheet.csv"
    readme_ja = output_directory / "README_JA.md"
    readme_en = output_directory / "README_EN.md"
    conventional_validation_path = output_directory / "validation_conventional.json"
    radial_validation_path = output_directory / "validation_radial_classic.json"
    radial_arachne_validation_path = output_directory / "validation_radial_arachne.json"
    manifest = output_directory / "manifest.json"

    conventional_validation = _write_conventional_3mf(conventional)
    radial_validation = _write_radial_3mf(radial, wall_generator="classic")
    radial_arachne_validation = _write_radial_3mf(
        radial_arachne, wall_generator="arachne"
    )
    _write_mapping(mapping)
    _write_observation_sheet(observation)
    readme_ja.write_text(_readme_ja(), encoding="utf-8")
    readme_en.write_text(_readme_en(), encoding="utf-8")
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
    payloads = (
        conventional,
        radial,
        radial_arachne,
        mapping,
        observation,
        readme_ja,
        readme_en,
        conventional_validation_path,
        radial_validation_path,
        radial_arachne_validation_path,
    )
    manifest.write_text(
        json.dumps(
            {
                "schema": COMPACT_COUPON_SCHEMA,
                "experimental": True,
                "slice_only": True,
                "print_allowed": False,
                "files": [_manifest_entry(path) for path in payloads],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return CompactBlackRadialCouponBundle(
        folder=output_directory,
        conventional_path=conventional,
        radial_path=radial,
        radial_arachne_path=radial_arachne,
        mapping_path=mapping,
        observation_path=observation,
        readme_ja_path=readme_ja,
        readme_en_path=readme_en,
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
        description="Create the large v3 0.10 mm conventional/radial frustum bundle."
    )
    parser.add_argument("output_directory", type=Path)
    arguments = parser.parse_args(argv)
    bundle = create_compact_black_radial_coupon_bundle(arguments.output_directory)
    print(bundle.conventional_path)
    print(bundle.radial_path)
    print(bundle.radial_arachne_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "APEX_XY_MM",
    "BAND_Z_MM",
    "BASE_SIZE_MM",
    "COMPACT_COUPON_SCHEMA",
    "CompactBlackRadialCouponBundle",
    "CompactBlackRadialCouponError",
    "CompactPyramidMesh",
    "CompactStage",
    "MODEL_HEIGHT_MM",
    "RADIAL_THICKNESS_MM",
    "build_compact_conventional_coupon",
    "build_compact_radial_coupon",
    "compact_stages",
    "create_compact_black_radial_coupon_bundle",
    "validate_compact_black_radial_coupon_3mf",
]
