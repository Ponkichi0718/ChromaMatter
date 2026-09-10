"""Purpose-built blocky head for selective variable-skin validation.

The specimen is synthetic and intentionally simple.  It keeps three different
contracts on one closed surface:

* black + light-skin mixed states are eligible for the radial Stage-B path;
* black + brown-hair mixed states stay conventional because their L* contrast
  is below the provisional gate; and
* authored pure-black facial details stay conventional pure black.

Generated 3MF files are experimental, ``SLICE ONLY`` validation artifacts.
Nothing in this module promotes the radial path to a public print profile.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Mapping, Sequence
import uuid
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw

from . import engine, mixer
from .filament_database import srgb_hex_to_lab
from .models import ColorResult, MeshLevel, ObjAsset, PaletteSettings, PreparedGeometry
from .radial_export import (
    RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010,
    RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
)
from .radial_hybrid_export import (
    RadialHybridPackage,
    package_from_selective_hybrid,
    validate_hybrid_3mf,
    write_hybrid_3mf_atomic,
)
from .radial_stage_b import build_selective_hybrid
from .radial_thickness import (
    RadialThicknessSchedule,
    derive_radial_thickness_schedule,
)


HEAD_SCHEMA = "chromamatter.variable-skin-blocky-head.v1"
HEAD_PROCESS_POLICY_SCHEMA = "chromamatter.variable-skin-head-process-policy.v1"
HEAD_BUNDLE_SCHEMA = "chromamatter.variable-skin-head-validation-bundle.v1"
HEAD_GRID_X = 6
HEAD_GRID_Y = 4
HEAD_GRID_Z = 8
CELL_SIZE_MM = 4.5
PHYSICAL_HEX = ("#121212", "#F2B28C", "#5A321F", "#F5F1E8")
PHYSICAL_LABELS = ("F1 black", "F2 light skin", "F3 brown", "F4 off-white")
LAYER_HEIGHT_MM = 0.10
INITIAL_LAYER_HEIGHT_MM = 0.20
MINIMUM_SKIN_THICKNESS_MM = 0.10
MAXIMUM_SKIN_THICKNESS_MM = 0.42
SKIN_THICKNESS_BANDS = 5
# The reference OBJ must use ChromaMatter's vertex-colour contract without
# splitting a closed surface at every colour boundary.  Each source triangle
# therefore keeps its shared outer edge and receives a small planar inset.
# The exact categorical colour occupies (1 - 3t)^2 = 82.81% of that triangle;
# only the narrow edge strip interpolates through the shared boundary colour.
REFERENCE_OBJ_FACE_INSET_FRACTION = 0.03
REFERENCE_OBJ_EXACT_FACE_AREA_FRACTION = (
    1.0 - 3.0 * REFERENCE_OBJ_FACE_INSET_FRACTION
) ** 2
REFERENCE_OBJ_CHILD_FACES_PER_SOURCE_FACE = 7
BLACK_EXTRUDER = 1
SKIN_EXTRUDER = 2

CONVENTIONAL_FILE = "01_conventional_classic_0p10.3mf"
HYBRID_CONTROL_FILE = "02_selective_hybrid_classic_100pct_control.3mf"
HYBRID_CLASSIC_2_FILE = "03_selective_hybrid_classic_2wall_15pct_probe.3mf"
HYBRID_CLASSIC_3_FILE = "04_selective_hybrid_classic_3wall_15pct_candidate.3mf"
HYBRID_ARACHNE_3_FILE = "05_selective_hybrid_arachne_3wall_15pct_probe.3mf"

_CONVENTIONAL_REQUIRED_MEMBERS = frozenset(
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
        "Metadata/variable_skin_head_validation.json",
    }
)
_HYBRID_REQUIRED_MEMBERS = frozenset(
    {
        "[Content_Types].xml",
        "_rels/.rels",
        "3D/3dmodel.model",
        "3D/_rels/3dmodel.model.rels",
        "3D/Objects/radial_parts.model",
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
        "Metadata/radial_shell_experimental.json",
    }
)
_PART_BASE_METADATA_KEYS = frozenset(
    {
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
)
_PART_OVERRIDE_KEYS = frozenset({"wall_loops", "sparse_infill_density"})

# Physical states.
STATE_BLACK = 0
STATE_SKIN = 1
STATE_BROWN = 2
STATE_WHITE = 3

# F1 black + F2 skin: 5, 25, 50, 75 and 95 percent skin.  These states have
# a high display-HEX L* delta and are the variable radial candidates.
SKIN_RADIAL_STATES = (4, 22, 16, 23, 10)

# F1 black + F3 brown: 25, 33, 50 and 75 percent brown.  With the purpose-built
# palette the black/brown L* delta remains below 35, so these must stay on the
# conventional carrier even in Selective Hybrid mode.
HAIR_CONVENTIONAL_STATES = (24, 5, 17, 25)


class VariableSkinHeadError(RuntimeError):
    """Raised when the synthetic specimen loses a validation invariant."""


@dataclass(frozen=True, slots=True)
class BlockyHeadMesh:
    vertices_mm: np.ndarray
    faces: np.ndarray
    face_states: np.ndarray
    face_cells: tuple[tuple[int, int, int], ...]
    face_directions: tuple[tuple[int, int, int], ...]
    source_volume_mm3: float

    @property
    def height_mm(self) -> float:
        return float(np.ptp(self.vertices_mm[:, 2]))


@dataclass(frozen=True, slots=True)
class HeadVariantValidation:
    path: Path
    method: str
    sha256: str
    bytes: int
    parts: int
    vertices: int
    faces: int
    interface_pairs: int
    wall_generator: str
    core_wall_loops: int
    core_infill_percent: int
    static_validation_ok: bool = True
    slice_only: bool = True
    print_allowed: bool = False


@dataclass(frozen=True, slots=True)
class VariableSkinHeadBundle:
    folder: Path
    conventional_path: Path
    hybrid_control_path: Path
    hybrid_classic_2wall_path: Path
    hybrid_classic_3wall_path: Path
    hybrid_arachne_3wall_path: Path
    preview_path: Path
    mapping_path: Path
    observation_path: Path
    readme_ja_path: Path
    readme_en_path: Path
    manifest_path: Path
    archive_path: Path
    validations: tuple[HeadVariantValidation, ...]


_DIRECTIONS: tuple[
    tuple[tuple[int, int, int], tuple[tuple[int, int, int], ...]], ...
] = (
    ((-1, 0, 0), ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
    ((1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))),
    ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
    ((0, 1, 0), ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0))),
    ((0, 0, -1), ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))),
    ((0, 0, 1), ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
)


def _occupied_cells() -> set[tuple[int, int, int]]:
    # A deliberately convex Minecraft-like block head.  Keeping the source a
    # single rectangular voxel union removes concave feature contacts from the
    # experiment, so failures can be attributed to thickness/routing rather
    # than to decorative nose, ear or hair-tuft topology.
    return {
        (x, y, z)
        for x in range(HEAD_GRID_X)
        for y in range(HEAD_GRID_Y)
        for z in range(HEAD_GRID_Z)
    }


def _hair_state(x: int, direction: tuple[int, int, int], z: int) -> int:
    # Broad left-to-right cel bands.  Top-facing hair receives one extra step
    # of light while the back remains darker.
    if x == 0:
        level = 3
    elif x == 1:
        level = 2
    elif x <= 3:
        level = 1
    else:
        level = 0
    if direction == (0, 0, 1):
        level = min(3, level + 1)
    elif direction == (0, 1, 0):
        level = max(0, level - 1)
    if z >= HEAD_GRID_Z - 1 and level == 3:
        return STATE_BROWN
    return HAIR_CONVENTIONAL_STATES[level]


def _skin_state(x: int, direction: tuple[int, int, int], z: int) -> int:
    # The virtual key light is above/front-left.  X bands keep the expected
    # thickness ladder visible after slicing; the face normal shifts only one
    # cel step so side/top planes are still easy to compare.
    level = int(
        round(4.0 * (HEAD_GRID_X - 1 - x) / float(HEAD_GRID_X - 1))
    )
    if direction in {(-1, 0, 0), (0, 0, 1)}:
        level = min(4, level + 1)
    elif direction in {(1, 0, 0), (0, 1, 0), (0, 0, -1)}:
        level = max(0, level - 1)
    if z == 0:
        level = max(0, level - 1)
    return SKIN_RADIAL_STATES[level]


def _is_hair_surface(
    cell: tuple[int, int, int], direction: tuple[int, int, int]
) -> bool:
    x, y, z = cell
    if z >= HEAD_GRID_Z - 2:
        return True
    if direction == (0, 1, 0) and z >= 1:
        return True
    if direction in {(-1, 0, 0), (1, 0, 0)} and z >= HEAD_GRID_Z - 3:
        return True
    # A small sideburn keeps the hair/skin boundary visible on both sides.
    return (
        direction in {(-1, 0, 0), (1, 0, 0)}
        and y >= HEAD_GRID_Y - 1
        and z >= HEAD_GRID_Z - 4
    )


def _face_state(
    cell: tuple[int, int, int], direction: tuple[int, int, int]
) -> int:
    x, y, z = cell
    front = direction == (0, -1, 0)
    # Pixel-like eyes, eyebrows and mouth are authored pure black/white and
    # must never be converted merely because another black mix is radial.
    if front and y == 0:
        if z == 4 and x in {1, 4}:
            return STATE_WHITE
        if z == 4 and x in {2, 3}:
            return STATE_BLACK
        if z == 5 and x in {1, 2, 3, 4}:
            return STATE_BLACK
        if z == 2 and x in {2, 3}:
            return STATE_BLACK
    if _is_hair_surface(cell, direction):
        return _hair_state(x, direction, z)
    return _skin_state(x, direction, z)


def build_blocky_head_mesh() -> BlockyHeadMesh:
    """Return one watertight, outward-wound voxel-union head surface."""

    occupied = _occupied_cells()
    vertices: list[tuple[float, float, float]] = []
    vertex_ids: dict[tuple[int, int, int], int] = {}
    faces: list[tuple[int, int, int]] = []
    states: list[int] = []
    face_cells: list[tuple[int, int, int]] = []
    face_directions: list[tuple[int, int, int]] = []

    min_x = min(cell[0] for cell in occupied)
    max_x = max(cell[0] for cell in occupied) + 1
    min_y = min(cell[1] for cell in occupied)
    max_y = max(cell[1] for cell in occupied) + 1
    center_x = 0.5 * (min_x + max_x)
    center_y = 0.5 * (min_y + max_y)

    def vertex_id(point: tuple[int, int, int]) -> int:
        found = vertex_ids.get(point)
        if found is not None:
            return found
        index = len(vertices)
        vertex_ids[point] = index
        vertices.append(
            (
                (point[0] - center_x) * CELL_SIZE_MM,
                (point[1] - center_y) * CELL_SIZE_MM,
                point[2] * CELL_SIZE_MM,
            )
        )
        return index

    for cell in sorted(occupied):
        x, y, z = cell
        for direction, offsets in _DIRECTIONS:
            neighbor = (
                x + direction[0],
                y + direction[1],
                z + direction[2],
            )
            if neighbor in occupied:
                continue
            quad = [
                vertex_id((x + dx, y + dy, z + dz))
                for dx, dy, dz in offsets
            ]
            state = _face_state(cell, direction)
            faces.extend(((quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])))
            states.extend((state, state))
            face_cells.extend((cell, cell))
            face_directions.extend((direction, direction))

    vertex_array = np.asarray(vertices, dtype=np.float64)
    face_array = np.asarray(faces, dtype=np.int32)
    state_array = np.asarray(states, dtype=np.int16)
    topology = engine.edge_topology(face_array, len(vertex_array))
    if topology.get("boundary_edges") != 0 or topology.get("nonmanifold_edges") != 0:
        raise VariableSkinHeadError("Blocky head voxel union is not watertight")
    volume = float(engine.signed_volume(vertex_array, face_array))
    if not math.isfinite(volume) or volume <= 0.0:
        raise VariableSkinHeadError("Blocky head winding/volume is invalid")
    if len(state_array) != len(face_array):
        raise VariableSkinHeadError("Blocky head face-state count drifted")
    required = {
        STATE_BLACK,
        STATE_BROWN,
        STATE_WHITE,
        *SKIN_RADIAL_STATES,
        *HAIR_CONVENTIONAL_STATES,
    }
    missing = required - set(int(value) for value in state_array)
    if missing:
        raise VariableSkinHeadError(f"Blocky head is missing test states: {sorted(missing)}")
    return BlockyHeadMesh(
        vertices_mm=vertex_array,
        faces=face_array,
        face_states=state_array,
        face_cells=tuple(face_cells),
        face_directions=tuple(face_directions),
        source_volume_mm3=volume,
    )


def head_palette() -> PaletteSettings:
    enabled = [False] * mixer.PALETTE_STATE_COUNT
    for state in {
        STATE_BLACK,
        STATE_SKIN,
        STATE_BROWN,
        STATE_WHITE,
        *SKIN_RADIAL_STATES,
        *HAIR_CONVENTIONAL_STATES,
    }:
        enabled[int(state)] = True
    primary_ratios = [33] * len(mixer.PAIR_INDICES)
    secondary_ratios = [67] * len(mixer.PAIR_INDICES)
    # F1/F2 alone spans the complete five-band validation range through the
    # normal application mapping: 5/25/50/75/95% skin.  Hair pairs retain the
    # ordinary 33/50/67/25/75 choices.
    primary_ratios[0] = 5
    secondary_ratios[0] = 95
    return PaletteSettings(
        material="PLA",
        palette_state_count=32,
        physical_hex=list(PHYSICAL_HEX),
        enabled_states=enabled,
        mix_ratios_b=primary_ratios,
        secondary_mix_ratios_b=secondary_ratios,
        output_mix_ratios_b=mixer.black_output_ratio_preset(
            0,
            primary_ratios,
            secondary_ratios,
        ),
    )


def prepared_head(
    mesh: BlockyHeadMesh | None = None,
) -> tuple[PreparedGeometry, ColorResult, PaletteSettings]:
    """Adapt the synthetic surface to the ordinary ChromaMatter writer."""

    specimen = mesh or build_blocky_head_mesh()
    palette = head_palette()
    _palette_hex, palette_values = mixer.build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    palette_rgb = np.asarray(palette_values[:32], dtype=np.float64)
    height = specimen.height_mm
    vertices_unit = specimen.vertices_mm / height
    face_rgb = palette_rgb[specimen.face_states]
    vertex_rgb = np.zeros((len(vertices_unit), 3), dtype=np.float64)
    vertex_weight = np.zeros(len(vertices_unit), dtype=np.float64)
    for face, colour in zip(specimen.faces, face_rgb, strict=True):
        vertex_rgb[face] += colour
        vertex_weight[face] += 1.0
    if np.any(vertex_weight <= 0.0):
        raise VariableSkinHeadError("Blocky head contains an unused vertex")
    vertex_rgb /= vertex_weight[:, None]
    area_unit = engine.triangle_areas(vertices_unit, specimen.faces)
    face_parts = np.zeros(len(specimen.faces), dtype=np.int16)
    part_names = ("Original blocky cel head",)
    part_keys = ("original-blocky-cel-head",)
    level = MeshLevel(
        vertices_unit=vertices_unit,
        faces=specimen.faces,
        vertex_colors=vertex_rgb,
        areas_unit=area_unit,
        neighbors=engine.face_neighbors(specimen.faces, len(vertices_unit)),
        face_part_ids=face_parts,
        part_names=part_names,
        part_keys=part_keys,
        face_provenance=np.zeros(len(specimen.faces), dtype=np.uint8),
    )
    digest = hashlib.sha256(
        specimen.vertices_mm.tobytes()
        + specimen.faces.tobytes()
        + specimen.face_states.tobytes()
    ).hexdigest()
    source = ObjAsset(
        path=Path("original_blocky_left_lit_head.obj"),
        sha256=digest,
        file_size=0,
        vertices=vertices_unit.copy(),
        colors=vertex_rgb.copy(),
        faces=specimen.faces.copy(),
        original_vertex_count=len(vertices_unit),
        original_face_count=len(specimen.faces),
        warnings=[],
        part_names=part_names,
        part_keys=part_keys,
        face_part_ids=face_parts.copy(),
        part_face_counts=(len(specimen.faces),),
        part_vertex_counts=(len(vertices_unit),),
        part_marker_kind="synthetic_validation_head",
        has_explicit_parts=True,
        import_metadata={"schema": HEAD_SCHEMA, "rights": "original-synthetic"},
    )
    source_volume_unit = specimen.source_volume_mm3 / height**3
    topology = engine.edge_topology(specimen.faces, len(vertices_unit))
    prepared = PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(vertices_unit),
        clean_face_count=len(specimen.faces),
        removed_vertices=0,
        removed_faces=0,
        topology={**topology, "watertight": True},
        source_area_unit=float(area_unit.sum()),
        source_volume_unit=source_volume_unit,
        simplified_area_unit=float(area_unit.sum()),
        simplified_volume_unit=source_volume_unit,
        source_dimensions_unit=np.ptp(vertices_unit, axis=0),
        warnings=[],
        part_names=part_names,
        part_keys=part_keys,
        part_stats=[
            {
                "part_id": 0,
                "part_key": part_keys[0],
                "part_name": part_names[0],
                "vertices": len(vertices_unit),
                "faces": len(specimen.faces),
            }
        ],
        assembly={
            "solidify_parts": False,
            "all_parts_watertight": True,
            "schema": HEAD_SCHEMA,
        },
    )
    # Direct writer callers normally receive this cache from the GUI hotfix
    # layer.  The synthetic command-line specimen deliberately has no manual
    # sub-triangle paint, but still declares the empty trusted cache.
    prepared._hotfix_subtriangle_paint = {}
    counts = np.bincount(specimen.face_states, minlength=32)
    weighted = np.bincount(
        specimen.face_states,
        weights=area_unit,
        minlength=32,
    )
    fractions = weighted / float(weighted.sum())
    colours = ColorResult(
        tone_vertex_rgb=vertex_rgb,
        source_face_rgb=face_rgb,
        palette_indices=specimen.face_states.copy(),
        target_face_rgb=face_rgb.copy(),
        delta_e=np.zeros(len(specimen.faces), dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=0.0,
        tone_face_rgb=face_rgb.copy(),
        tone_face_rgb_flat=True,
    )
    return prepared, colours, palette


def head_thickness_schedule(
    palette: PaletteSettings | None = None,
) -> RadialThicknessSchedule:
    """Return the deterministic, uncalibrated F1/F2 thickness ladder."""

    return derive_radial_thickness_schedule(
        palette or head_palette(),
        black_slot=BLACK_EXTRUDER - 1,
        eligible_state_partners={state: SKIN_EXTRUDER for state in SKIN_RADIAL_STATES},
        minimum_thickness_mm=MINIMUM_SKIN_THICKNESS_MM,
        maximum_thickness_mm=MAXIMUM_SKIN_THICKNESS_MM,
        band_count=SKIN_THICKNESS_BANDS,
        basis="target_lstar",
    )


def _ratio_policy(palette: PaletteSettings | None = None) -> dict[str, object]:
    selected = palette or head_palette()
    return {
        "display_primary_ratios_b": [int(value) for value in selected.mix_ratios_b],
        "display_secondary_ratios_b": [
            int(value) for value in (selected.secondary_mix_ratios_b or ())
        ],
        "conventional_output_ratios_b": [
            int(value) for value in (selected.output_mix_ratios_b or ())
        ],
        "black_extruder": BLACK_EXTRUDER,
        "output_policy": "existing weak-black calibration",
    }


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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
            existing: set[str] = set()
            for info in source.infolist():
                if info.filename in existing:
                    raise VariableSkinHeadError("3MF contains a duplicate ZIP member")
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
                raise VariableSkinHeadError("Patched head 3MF has a ZIP CRC failure")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _conventional_process_settings() -> dict[str, object]:
    settings: dict[str, object] = {
        "print_settings_id": (
            "0.10 Variable-Skin Head Conventional Control "
            "@Snapmaker U1 (0.4 nozzle)"
        ),
        "layer_height": "0.1",
        "initial_layer_print_height": "0.2",
        "adaptive_layer_height": "0",
        "wall_loops": "3",
        "wall_generator": "classic",
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
        "support_filament": "4",
        "support_interface_filament": "4",
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
    return settings


def _conventional_metadata(
    mesh: BlockyHeadMesh,
    schedule: RadialThicknessSchedule,
) -> dict[str, object]:
    return {
        "schema": HEAD_PROCESS_POLICY_SCHEMA,
        "head_schema": HEAD_SCHEMA,
        "method": "conventional-full-spectrum-ratio-control",
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "verified_in_snapmaker_orca": False,
        "verified_on_u1": False,
        "layer_height_mm": LAYER_HEIGHT_MM,
        "initial_layer_height_mm": INITIAL_LAYER_HEIGHT_MM,
        "wall_generator": "classic",
        "wall_loops": 3,
        "sparse_infill_density_percent": 100,
        "palette": [
            {"extruder": index + 1, "label": label, "hex": color}
            for index, (label, color) in enumerate(
                zip(PHYSICAL_LABELS, PHYSICAL_HEX, strict=True)
            )
        ],
        "ratio_policy": _ratio_policy(head_palette()),
        "routing": {
            "skin_black_states": {
                str(state): "conventional-ratio" for state in SKIN_RADIAL_STATES
            },
            "hair_black_states": {
                str(state): "conventional-ratio"
                for state in HAIR_CONVENTIONAL_STATES
            },
            "pure_black_state": "preserved",
            "pure_brown_state": "preserved",
            "pure_white_state": "preserved",
        },
        "reference_variable_skin_schedule": schedule.to_dict(),
        "source": {
            "synthetic": True,
            "vertices": int(len(mesh.vertices_mm)),
            "faces": int(len(mesh.faces)),
            "volume_mm3": float(mesh.source_volume_mm3),
        },
    }


def _write_conventional_3mf(
    path: Path,
    mesh: BlockyHeadMesh,
    prepared: PreparedGeometry,
    colours: ColorResult,
    palette: PaletteSettings,
    schedule: RadialThicknessSchedule,
) -> HeadVariantValidation:
    engine.write_3mf_atomic(
        path,
        prepared,
        colours,
        mesh.height_mm,
        palette,
        part_palettes=None,
        print_uses_global_palette=True,
    )
    with zipfile.ZipFile(path, "r") as archive:
        project = json.loads(archive.read("Metadata/project_settings.config"))
    project.update(_conventional_process_settings())
    metadata = _conventional_metadata(mesh, schedule)
    _rewrite_zip_members(
        path,
        {
            "Metadata/project_settings.config": json.dumps(
                project, ensure_ascii=False, indent=2
            ).encode("utf-8"),
            "Metadata/variable_skin_head_validation.json": json.dumps(
                metadata, ensure_ascii=False, indent=2
            ).encode("utf-8"),
        },
    )
    return validate_variable_skin_head_3mf(path)


def _build_variable_stage_b(
    mesh: BlockyHeadMesh,
    prepared: PreparedGeometry,
    schedule: RadialThicknessSchedule,
) -> object:
    kwargs = {
        "prepared": prepared,
        "height_mm": mesh.height_mm,
        "face_state_ids": mesh.face_states,
        "eligible_state_partners": {
            state: SKIN_EXTRUDER for state in SKIN_RADIAL_STATES
        },
        "black_extruder": BLACK_EXTRUDER,
        # Scalar remains the compatibility/fallback value.  The Stage-B API
        # separately proves every mapped state when the variable schedule is
        # supplied below.
        "skin_thickness_mm": max(schedule.thickness_by_state.values()),
        "state_skin_thickness_mm": schedule.thickness_by_state,
    }
    try:
        result = build_selective_hybrid(**kwargs)
    except TypeError as exc:
        if "state_skin_thickness_mm" in str(exc):
            raise VariableSkinHeadError(
                "Variable-thickness Stage-B API is not available; refusing "
                "to silently emit a scalar-skin validation model"
            ) from exc
        raise
    actual_thicknesses = {
        int(state): float(value)
        for state, value in dict(
            getattr(result.plan, "state_outer_skin_thickness_mm", {})
        ).items()
    }
    if actual_thicknesses != {
        int(state): float(value)
        for state, value in schedule.thickness_by_state.items()
    }:
        raise VariableSkinHeadError(
            "Stage-B did not retain the per-state thickness proof"
        )
    return result


def _package_hybrid_result(
    result: object,
    palette: PaletteSettings,
    *,
    wall_generator: str,
) -> RadialHybridPackage:
    generator = str(wall_generator).strip().lower()
    if generator not in {"classic", "arachne"}:
        raise VariableSkinHeadError(f"Unsupported wall generator: {wall_generator!r}")
    plan = getattr(result, "plan", None)
    state_thickness = {
        str(state): float(value)
        for state, value in sorted(
            dict(getattr(plan, "state_outer_skin_thickness_mm", {})).items()
        )
    }
    metadata = {
        **dict(getattr(result, "metadata", {}) or {}),
        "variable_skin_head_schema": HEAD_SCHEMA,
        "state_outer_skin_thickness_mm": state_thickness,
        "radial_state_ids": [int(value) for value in getattr(plan, "radial_state_ids", ())],
        "conventional_state_ids": [
            int(value) for value in getattr(plan, "conventional_state_ids", ())
        ],
        "state_decisions": [
            item.to_dict() for item in getattr(plan, "state_decisions", ())
        ],
    }
    try:
        result = replace(result, metadata=metadata)
    except TypeError as exc:
        raise VariableSkinHeadError(
            "Stage-B result cannot carry the variable-thickness archive proof"
        ) from exc
    profile = (
        RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010
        if generator == "arachne"
        else RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010
    )
    package = package_from_selective_hybrid(
        result,
        palette,
        process_profile=profile,
        layer_height_mm=LAYER_HEIGHT_MM,
        initial_layer_height_mm=INITIAL_LAYER_HEIGHT_MM,
    )
    proof = {
        **dict(package.proof),
        "variable_skin_head_schema": HEAD_SCHEMA,
        "state_outer_skin_thickness_mm": state_thickness,
        "radial_state_ids": [
            int(value) for value in getattr(plan, "radial_state_ids", ())
        ],
        "conventional_state_ids": [
            int(value) for value in getattr(plan, "conventional_state_ids", ())
        ],
    }
    return replace(package, proof=proof)


def _build_hybrid_package(
    mesh: BlockyHeadMesh,
    prepared: PreparedGeometry,
    palette: PaletteSettings,
    schedule: RadialThicknessSchedule,
    *,
    wall_generator: str,
) -> RadialHybridPackage:
    """Compatibility helper used by focused tests and one-off callers."""

    result = _build_variable_stage_b(mesh, prepared, schedule)
    return _package_hybrid_result(
        result,
        palette,
        wall_generator=wall_generator,
    )


def _override_profile(
    *,
    variant_id: str,
    wall_generator: str,
    core_wall_loops: int,
    core_infill_percent: int,
) -> dict[str, object]:
    if wall_generator not in {"classic", "arachne"}:
        raise VariableSkinHeadError("Invalid validation wall generator")
    if core_wall_loops not in {2, 3}:
        raise VariableSkinHeadError("Validation core wall loops must be 2 or 3")
    if core_infill_percent not in {15, 100}:
        raise VariableSkinHeadError("Validation core infill must be 15 or 100")
    return {
        "id": str(variant_id),
        "wall_generator": wall_generator,
        "layer_height_mm": LAYER_HEIGHT_MM,
        "initial_layer_height_mm": INITIAL_LAYER_HEIGHT_MM,
        "partner_outer_shell": {
            "wall_loops": 1,
            "sparse_infill_density": "100%",
        },
        "core_and_carrier": {
            "wall_loops": int(core_wall_loops),
            "sparse_infill_density": f"{int(core_infill_percent)}%",
        },
        "global_object_settings_unchanged": True,
        "part_overrides_supersede_global_values": True,
        "recommendation": (
            "control-only"
            if core_infill_percent == 100
            else (
                "start-candidate"
                if core_wall_loops == 3
                else "material-and-time-probe-not-a-recommendation"
            )
        ),
    }


def _part_override_for(role: str, profile: Mapping[str, object]) -> dict[str, str]:
    key = "partner_outer_shell" if role == "partner_outer_shell" else "core_and_carrier"
    selected = profile.get(key)
    if not isinstance(selected, Mapping):
        raise VariableSkinHeadError("Validation override profile is malformed")
    return {
        "wall_loops": str(int(selected["wall_loops"])),
        "sparse_infill_density": str(selected["sparse_infill_density"]),
    }


def _patch_model_settings(
    source_bytes: bytes,
    base_hybrid_metadata: Mapping[str, object],
    profile: Mapping[str, object],
) -> tuple[bytes, list[dict[str, object]]]:
    try:
        root = ET.fromstring(source_bytes)
    except ET.ParseError as exc:
        raise VariableSkinHeadError("Hybrid model settings XML is malformed") from exc
    objects = root.findall("object")
    if len(objects) != 1:
        raise VariableSkinHeadError("Hybrid model settings must contain one object")
    parts = objects[0].findall("part")
    metadata_parts = base_hybrid_metadata.get("parts")
    if not isinstance(metadata_parts, list) or len(metadata_parts) != len(parts):
        raise VariableSkinHeadError("Hybrid role metadata/part count differs")
    policy_parts: list[dict[str, object]] = []
    for index, (part, part_meta) in enumerate(
        zip(parts, metadata_parts, strict=True)
    ):
        if not isinstance(part_meta, Mapping) or int(part_meta.get("index", -1)) != index:
            raise VariableSkinHeadError("Hybrid role metadata order drifted")
        if part.attrib != {"id": str(index + 1), "subtype": "normal_part"}:
            raise VariableSkinHeadError("Hybrid model-settings part ID drifted")
        role = str(part_meta.get("role", ""))
        if role not in {
            "partner_outer_shell",
            "pure_black_core",
            "conventional_painted_carrier",
        }:
            raise VariableSkinHeadError(f"Unexpected hybrid part role: {role!r}")
        keyed = [item for item in part.findall("metadata") if "key" in item.attrib]
        keys = [str(item.attrib["key"]) for item in keyed]
        if len(keys) != len(set(keys)) or set(keys) != _PART_BASE_METADATA_KEYS:
            raise VariableSkinHeadError("Base hybrid part metadata allowlist drifted")
        insert_at = next(
            (position for position, item in enumerate(list(part)) if item.tag == "mesh_stat"),
            len(list(part)),
        )
        override = _part_override_for(role, profile)
        for key in ("wall_loops", "sparse_infill_density"):
            node = ET.Element("metadata", {"key": key, "value": override[key]})
            part.insert(insert_at, node)
            insert_at += 1
        policy_parts.append(
            {
                "index": index,
                "part_id": index + 1,
                "name": str(part_meta.get("name", "")),
                "role": role,
                "base_role": str(part_meta.get("base_role", "")),
                "physical_extruder": int(part_meta.get("physical_extruder", 0)),
                **override,
            }
        )
    return (
        ET.tostring(root, encoding="utf-8", xml_declaration=True),
        policy_parts,
    )


def _hybrid_wrapper_metadata(
    *,
    base_hybrid_metadata: Mapping[str, object],
    base_model_settings_bytes: bytes,
    profile: Mapping[str, object],
    parts: Sequence[Mapping[str, object]],
    schedule: RadialThicknessSchedule,
) -> dict[str, object]:
    base_copy = json.loads(
        json.dumps(base_hybrid_metadata, ensure_ascii=False, allow_nan=False)
    )
    return {
        "schema": HEAD_PROCESS_POLICY_SCHEMA,
        "head_schema": HEAD_SCHEMA,
        "method": "selective-variable-skin-hybrid",
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "verified_in_snapmaker_orca": False,
        "verified_on_u1": False,
        "base_hybrid_metadata_sha256": hashlib.sha256(
            _canonical_json_bytes(base_copy)
        ).hexdigest().upper(),
        "base_hybrid_metadata": base_copy,
        "base_model_settings_sha256": hashlib.sha256(
            base_model_settings_bytes
        ).hexdigest().upper(),
        "override_profile": dict(profile),
        "parts": [dict(item) for item in parts],
        "ratio_policy": _ratio_policy(),
        "routing": {
            "skin_black_high_delta_l_states": {
                str(state): "radial-variable-physical-skin"
                for state in SKIN_RADIAL_STATES
            },
            "hair_black_low_delta_l_states": {
                str(state): "conventional-painted-carrier"
                for state in HAIR_CONVENTIONAL_STATES
            },
            "pure_black_state": "preserved-conventional",
            "pure_brown_state": "preserved-conventional",
            "pure_white_state": "preserved-conventional",
        },
        "thickness_schedule": schedule.to_dict(),
        "safety": {
            "full_solid_core": int(
                profile["core_and_carrier"]["sparse_infill_density"].rstrip("%")
            )
            == 100,
            "optical_backing_unverified": True,
            "part_override_round_trip_unverified": True,
            "requires_orca_preview": True,
            "requires_line_type_and_filament_inspection": True,
            "requires_physical_validation": True,
        },
    }


def _strip_part_overrides(model_settings: bytes) -> bytes:
    try:
        root = ET.fromstring(model_settings)
    except ET.ParseError as exc:
        raise VariableSkinHeadError("Patched model settings XML is malformed") from exc
    parts = root.findall("./object/part")
    if not parts:
        raise VariableSkinHeadError("Patched model settings has no parts")
    for part in parts:
        removed: list[str] = []
        for child in list(part):
            if child.tag == "metadata" and child.attrib.get("key") in _PART_OVERRIDE_KEYS:
                removed.append(str(child.attrib["key"]))
                part.remove(child)
        if sorted(removed) != sorted(_PART_OVERRIDE_KEYS):
            raise VariableSkinHeadError(
                "Patched model settings does not contain exactly two overrides per part"
            )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _sanitised_hybrid_archive(
    path: Path,
    wrapper: Mapping[str, object],
) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="chromamatter-head-sanitised-", suffix=".3mf"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as destination:
            for info in source.infolist():
                if info.filename == "Metadata/model_settings.config":
                    payload = _strip_part_overrides(source.read(info.filename))
                elif info.filename == "Metadata/radial_shell_experimental.json":
                    payload = json.dumps(
                        wrapper["base_hybrid_metadata"],
                        ensure_ascii=False,
                        indent=2,
                    ).encode("utf-8")
                else:
                    payload = source.read(info.filename)
                destination.writestr(info, payload)
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_hybrid_variant(
    path: Path,
    package: RadialHybridPackage,
    schedule: RadialThicknessSchedule,
    *,
    variant_id: str,
    wall_generator: str,
    core_wall_loops: int,
    core_infill_percent: int,
) -> HeadVariantValidation:
    path = Path(path).with_suffix(".3mf")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp.3mf")
    try:
        write_hybrid_3mf_atomic(
            temporary,
            package,
            title=f"SLICE ONLY - {variant_id}",
        )
        with zipfile.ZipFile(temporary, "r") as archive:
            base_model_settings = archive.read("Metadata/model_settings.config")
            base_hybrid_metadata = json.loads(
                archive.read("Metadata/radial_shell_experimental.json")
            )
        profile = _override_profile(
            variant_id=variant_id,
            wall_generator=wall_generator,
            core_wall_loops=core_wall_loops,
            core_infill_percent=core_infill_percent,
        )
        patched_settings, policy_parts = _patch_model_settings(
            base_model_settings,
            base_hybrid_metadata,
            profile,
        )
        wrapper = _hybrid_wrapper_metadata(
            base_hybrid_metadata=base_hybrid_metadata,
            # Digest the exact canonical XML that the dedicated validator
            # reconstructs by removing only the two opt-in override keys.
            base_model_settings_bytes=_strip_part_overrides(patched_settings),
            profile=profile,
            parts=policy_parts,
            schedule=schedule,
        )
        _rewrite_zip_members(
            temporary,
            {
                "Metadata/model_settings.config": patched_settings,
                "Metadata/radial_shell_experimental.json": json.dumps(
                    wrapper, ensure_ascii=False, indent=2
                ).encode("utf-8"),
            },
        )
        validate_variable_skin_head_3mf(temporary, expected_package=package)
        os.replace(temporary, path)
        return validate_variable_skin_head_3mf(path, expected_package=package)
    finally:
        temporary.unlink(missing_ok=True)


def _normal_archive_state_counts(archive: zipfile.ZipFile) -> tuple[int, int, dict[int, int]]:
    try:
        root = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    except ET.ParseError as exc:
        raise VariableSkinHeadError("Conventional head mesh XML is malformed") from exc
    code_to_state = {
        code: state for state, code in enumerate(engine.PAINT_CODES[:32])
    }
    total_vertices = 0
    total_faces = 0
    state_counts: dict[int, int] = {}
    mesh_objects = 0
    for obj in root.iter():
        if not obj.tag.endswith("object"):
            continue
        vertices = [
            [float(node.attrib[axis]) for axis in ("x", "y", "z")]
            for node in obj.iter()
            if node.tag.endswith("vertex")
        ]
        triangles = [node for node in obj.iter() if node.tag.endswith("triangle")]
        if not vertices and not triangles:
            continue
        mesh_objects += 1
        faces = np.asarray(
            [
                [int(node.attrib[key]) for key in ("v1", "v2", "v3")]
                for node in triangles
            ],
            dtype=np.int32,
        )
        vertex_array = np.asarray(vertices, dtype=np.float64)
        if not len(vertex_array) or not len(faces):
            raise VariableSkinHeadError("Conventional head contains an empty mesh")
        topology = engine.edge_topology(faces, len(vertex_array))
        if topology.get("boundary_edges") != 0 or topology.get("nonmanifold_edges") != 0:
            raise VariableSkinHeadError("Conventional head is not watertight")
        if float(engine.signed_volume(vertex_array, faces)) <= 0.0:
            raise VariableSkinHeadError("Conventional head has invalid winding/volume")
        total_vertices += len(vertex_array)
        total_faces += len(faces)
        for node in triangles:
            code = node.attrib.get("paint_color")
            if code not in code_to_state:
                raise VariableSkinHeadError("Conventional face paint is missing/unknown")
            state = code_to_state[code]
            state_counts[state] = state_counts.get(state, 0) + 1
    if mesh_objects != 1:
        raise VariableSkinHeadError("Conventional specimen must remain one mesh object")
    return total_vertices, total_faces, state_counts


def _validate_conventional_head(path: Path) -> HeadVariantValidation:
    mesh = build_blocky_head_mesh()
    palette = head_palette()
    schedule = head_thickness_schedule(palette)
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise VariableSkinHeadError("Conventional head has a ZIP CRC failure")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise VariableSkinHeadError("Conventional head has duplicate ZIP members")
        if set(names) != _CONVENTIONAL_REQUIRED_MEMBERS:
            raise VariableSkinHeadError(
                "Conventional head archive member allowlist drifted"
            )
        metadata = json.loads(
            archive.read("Metadata/variable_skin_head_validation.json")
        )
        if metadata != _conventional_metadata(mesh, schedule):
            raise VariableSkinHeadError("Conventional head validation metadata drifted")
        project = json.loads(archive.read("Metadata/project_settings.config"))
        expected_process = _conventional_process_settings()
        for key, expected in expected_process.items():
            if project.get(key) != expected:
                raise VariableSkinHeadError(
                    f"Conventional process setting {key} drifted"
                )
        vertices, faces, state_counts = _normal_archive_state_counts(archive)
    required_states = {
        STATE_BLACK,
        STATE_BROWN,
        STATE_WHITE,
        *SKIN_RADIAL_STATES,
        *HAIR_CONVENTIONAL_STATES,
    }
    if set(state_counts) != required_states or any(
        state_counts.get(state, 0) <= 0 for state in required_states
    ):
        raise VariableSkinHeadError("Conventional state routing/coverage drifted")
    definitions = engine.make_portable_mixed_definitions(
        list(palette.mix_ratios_b),
        (
            None
            if palette.secondary_mix_ratios_b is None
            else list(palette.secondary_mix_ratios_b)
        ),
        palette.palette_state_count,
        palette.output_mix_ratios_b,
        False,
        palette.physical_hex,
    )
    if project.get("mixed_filament_definitions") != definitions:
        raise VariableSkinHeadError("Conventional Full Spectrum definitions drifted")
    if project.get("filament_colour") != list(PHYSICAL_HEX):
        raise VariableSkinHeadError("Conventional physical filament colours drifted")
    return HeadVariantValidation(
        path=path,
        method="conventional-full-spectrum-ratio-control",
        sha256=_sha256_path(path),
        bytes=path.stat().st_size,
        parts=1,
        vertices=vertices,
        faces=faces,
        interface_pairs=0,
        wall_generator="classic",
        core_wall_loops=3,
        core_infill_percent=100,
    )


def _validate_hybrid_head(
    path: Path,
    *,
    expected_package: RadialHybridPackage | None = None,
) -> HeadVariantValidation:
    expected_wrapper_keys = {
        "schema",
        "head_schema",
        "method",
        "experimental",
        "slice_only",
        "print_allowed",
        "verified_in_snapmaker_orca",
        "verified_on_u1",
        "base_hybrid_metadata_sha256",
        "base_hybrid_metadata",
        "base_model_settings_sha256",
        "override_profile",
        "parts",
        "ratio_policy",
        "routing",
        "thickness_schedule",
        "safety",
    }
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise VariableSkinHeadError("Hybrid head has a ZIP CRC failure")
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != _HYBRID_REQUIRED_MEMBERS:
            raise VariableSkinHeadError("Hybrid head archive member allowlist drifted")
        wrapper = json.loads(
            archive.read("Metadata/radial_shell_experimental.json")
        )
        if not isinstance(wrapper, dict) or set(wrapper) != expected_wrapper_keys:
            raise VariableSkinHeadError("Hybrid head wrapper allowlist drifted")
        expected_static = {
            "schema": HEAD_PROCESS_POLICY_SCHEMA,
            "head_schema": HEAD_SCHEMA,
            "method": "selective-variable-skin-hybrid",
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "verified_in_snapmaker_orca": False,
            "verified_on_u1": False,
        }
        for key, expected in expected_static.items():
            if wrapper.get(key) != expected:
                raise VariableSkinHeadError(f"Hybrid head wrapper {key} drifted")
        base_metadata = wrapper.get("base_hybrid_metadata")
        if not isinstance(base_metadata, dict) or wrapper.get(
            "base_hybrid_metadata_sha256"
        ) != hashlib.sha256(_canonical_json_bytes(base_metadata)).hexdigest().upper():
            raise VariableSkinHeadError("Nested base hybrid metadata digest drifted")
        profile = wrapper.get("override_profile")
        policy_parts = wrapper.get("parts")
        if not isinstance(profile, dict) or not isinstance(policy_parts, list):
            raise VariableSkinHeadError("Hybrid override profile/parts are malformed")
        wall_generator = str(profile.get("wall_generator", ""))
        core_config = profile.get("core_and_carrier")
        partner_config = profile.get("partner_outer_shell")
        if not isinstance(core_config, dict) or not isinstance(partner_config, dict):
            raise VariableSkinHeadError("Hybrid role overrides are missing")
        core_wall_loops = int(core_config.get("wall_loops", -1))
        core_infill = int(str(core_config.get("sparse_infill_density", "-1%")).rstrip("%"))
        expected_profile = _override_profile(
            variant_id=str(profile.get("id", "")),
            wall_generator=wall_generator,
            core_wall_loops=core_wall_loops,
            core_infill_percent=core_infill,
        )
        if profile != expected_profile:
            raise VariableSkinHeadError("Hybrid override profile drifted")
        expected_process_profile = (
            RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010
            if wall_generator == "arachne"
            else RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010
        )
        if (
            base_metadata.get("process_profile") != expected_process_profile
            or float(base_metadata.get("layer_height_mm", -1.0)) != LAYER_HEIGHT_MM
            or float(base_metadata.get("initial_layer_height_mm", -1.0))
            != INITIAL_LAYER_HEIGHT_MM
            or tuple(base_metadata.get("physical_hex", ())) != PHYSICAL_HEX
        ):
            raise VariableSkinHeadError("Hybrid base process/palette drifted")
        if wrapper.get("thickness_schedule") != head_thickness_schedule().to_dict():
            raise VariableSkinHeadError("Hybrid per-state thickness schedule drifted")
        expected_routing = {
            "skin_black_high_delta_l_states": {
                str(state): "radial-variable-physical-skin"
                for state in SKIN_RADIAL_STATES
            },
            "hair_black_low_delta_l_states": {
                str(state): "conventional-painted-carrier"
                for state in HAIR_CONVENTIONAL_STATES
            },
            "pure_black_state": "preserved-conventional",
            "pure_brown_state": "preserved-conventional",
            "pure_white_state": "preserved-conventional",
        }
        if wrapper.get("routing") != expected_routing:
            raise VariableSkinHeadError("Hybrid state routing declaration drifted")
        if wrapper.get("ratio_policy") != _ratio_policy():
            raise VariableSkinHeadError("Hybrid display/output ratio policy drifted")
        expected_safety = {
            "full_solid_core": core_infill == 100,
            "optical_backing_unverified": True,
            "part_override_round_trip_unverified": True,
            "requires_orca_preview": True,
            "requires_line_type_and_filament_inspection": True,
            "requires_physical_validation": True,
        }
        if wrapper.get("safety") != expected_safety:
            raise VariableSkinHeadError("Hybrid validation-only safety gate drifted")
        source_settings = archive.read("Metadata/model_settings.config")
        stripped_settings = _strip_part_overrides(source_settings)
        if wrapper.get("base_model_settings_sha256") != hashlib.sha256(
            stripped_settings
        ).hexdigest().upper():
            raise VariableSkinHeadError("Hybrid base model-settings digest drifted")
        root = ET.fromstring(source_settings)
        parts = root.findall("./object/part")
        base_parts = base_metadata.get("parts")
        if (
            not isinstance(base_parts, list)
            or len(parts) != len(policy_parts)
            or len(parts) != len(base_parts)
        ):
            raise VariableSkinHeadError("Hybrid XML/policy/base part counts differ")
        painted_counts: dict[int, int] = {}
        for index, (part, policy_part, base_part) in enumerate(
            zip(parts, policy_parts, base_parts, strict=True)
        ):
            if not isinstance(policy_part, dict) or not isinstance(base_part, dict):
                raise VariableSkinHeadError("Hybrid per-part metadata is malformed")
            keyed_nodes = [node for node in part.findall("metadata") if "key" in node.attrib]
            if any(set(node.attrib) != {"key", "value"} for node in keyed_nodes):
                raise VariableSkinHeadError("Hybrid part metadata attributes drifted")
            keyed = {str(node.attrib["key"]): str(node.attrib["value"]) for node in keyed_nodes}
            if len(keyed) != len(keyed_nodes) or set(keyed) != (
                _PART_BASE_METADATA_KEYS | _PART_OVERRIDE_KEYS
            ):
                raise VariableSkinHeadError("Hybrid part metadata allowlist drifted")
            role = str(base_part.get("role", ""))
            expected_override = _part_override_for(role, profile)
            if any(keyed.get(key) != value for key, value in expected_override.items()):
                raise VariableSkinHeadError("Hybrid per-part slicer override drifted")
            expected_policy_part = {
                "index": index,
                "part_id": index + 1,
                "name": str(base_part.get("name", "")),
                "role": role,
                "base_role": str(base_part.get("base_role", "")),
                "physical_extruder": int(base_part.get("physical_extruder", 0)),
                **expected_override,
            }
            if policy_part != expected_policy_part:
                raise VariableSkinHeadError("Hybrid per-part policy drifted")
            state_counts = base_part.get("paint_state_counts")
            if not isinstance(state_counts, dict):
                raise VariableSkinHeadError("Hybrid paint-state counts are missing")
            for state, count in state_counts.items():
                key = int(state)
                painted_counts[key] = painted_counts.get(key, 0) + int(count)
        if any(painted_counts.get(state, 0) != 0 for state in SKIN_RADIAL_STATES):
            raise VariableSkinHeadError("A radial skin state leaked into paint output")
        for state in {
            STATE_BLACK,
            STATE_BROWN,
            STATE_WHITE,
            *HAIR_CONVENTIONAL_STATES,
        }:
            if painted_counts.get(state, 0) <= 0:
                raise VariableSkinHeadError(
                    "A pure or low-contrast conventional state was not preserved"
                )
        proof = base_metadata.get("material_manifold_proof")
        if not isinstance(proof, dict):
            raise VariableSkinHeadError("Hybrid material-manifold proof is missing")
        interface_pairs = int(proof.get("interface_triangle_pairs", 0))
        if interface_pairs <= 0:
            raise VariableSkinHeadError("Hybrid contains no exact material interface")
        if any(
            proof.get(key) is not True
            for key in (
                "material_manifold",
                "source_exterior_preserved_exactly",
                "shared_interface_partition_exact",
                "external_surface_coverage_exact",
            )
        ):
            raise VariableSkinHeadError("Hybrid exact-partition proof drifted")
        expected_thickness = {
            str(state): float(value)
            for state, value in sorted(head_thickness_schedule().thickness_by_state.items())
        }
        if proof.get("variable_skin_head_schema") != HEAD_SCHEMA or proof.get(
            "state_outer_skin_thickness_mm"
        ) != expected_thickness:
            raise VariableSkinHeadError("Hybrid geometry thickness proof drifted")
        if set(map(int, proof.get("radial_state_ids", ()))) != set(
            SKIN_RADIAL_STATES
        ):
            raise VariableSkinHeadError("Hybrid radial-state geometry proof drifted")
        conventional_states = set(map(int, proof.get("conventional_state_ids", ())))
        if not {
            STATE_BLACK,
            STATE_BROWN,
            STATE_WHITE,
            *HAIR_CONVENTIONAL_STATES,
        }.issubset(conventional_states) or conventional_states & set(
            SKIN_RADIAL_STATES
        ):
            raise VariableSkinHeadError("Hybrid conventional-state proof drifted")
    black_lstar = float(srgb_hex_to_lab(PHYSICAL_HEX[0])[0])
    skin_delta = abs(float(srgb_hex_to_lab(PHYSICAL_HEX[1])[0]) - black_lstar)
    hair_delta = abs(float(srgb_hex_to_lab(PHYSICAL_HEX[2])[0]) - black_lstar)
    if not skin_delta >= 35.0 or not hair_delta < 35.0:
        raise VariableSkinHeadError("Purpose-built high/low Delta-L routing drifted")
    sanitised = _sanitised_hybrid_archive(path, wrapper)
    try:
        base_validation = validate_hybrid_3mf(
            sanitised,
            expected_package=expected_package,
        )
    finally:
        sanitised.unlink(missing_ok=True)
    return HeadVariantValidation(
        path=path,
        method="selective-variable-skin-hybrid",
        sha256=_sha256_path(path),
        bytes=path.stat().st_size,
        parts=base_validation.parts,
        vertices=base_validation.vertices,
        faces=base_validation.faces,
        interface_pairs=interface_pairs,
        wall_generator=wall_generator,
        core_wall_loops=core_wall_loops,
        core_infill_percent=core_infill,
    )


def validate_variable_skin_head_3mf(
    path: Path,
    *,
    expected_package: RadialHybridPackage | None = None,
) -> HeadVariantValidation:
    """Reopen one specimen and validate only the declared wrapper contract."""

    path = Path(path)
    if not path.is_file():
        raise VariableSkinHeadError(f"Head specimen does not exist: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        names = set(archive.namelist())
    if "Metadata/variable_skin_head_validation.json" in names:
        if expected_package is not None:
            raise VariableSkinHeadError("Conventional specimen cannot trust a hybrid package")
        return _validate_conventional_head(path)
    if "Metadata/radial_shell_experimental.json" in names:
        return _validate_hybrid_head(path, expected_package=expected_package)
    raise VariableSkinHeadError("Unknown variable-skin head archive")


def _palette_hex_values(palette: PaletteSettings) -> tuple[str, ...]:
    values, _rgb = mixer.build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    return tuple(str(value).upper() for value in values[: palette.palette_state_count])


def _write_original_obj_mtl(
    obj_path: Path,
    mtl_path: Path,
    mesh: BlockyHeadMesh,
    palette: PaletteSettings,
) -> None:
    palette_hex = _palette_hex_values(palette)
    palette_rgb = np.asarray(
        [
            [int(value[offset : offset + 2], 16) / 255.0 for offset in (1, 3, 5)]
            for value in palette_hex
        ],
        dtype=np.float64,
    )
    # ChromaMatter's OBJ contract is vertex colour (``v X Y Z R G B``), not
    # material colour.  Keep the original shared vertices/edges so the OBJ is
    # still a closed indexed solid.  A planar inset inside each source triangle
    # carries its exact categorical colour over most of the area; the narrow
    # edge strip transitions through the incident-average colour required at
    # a shared vertex.  Duplicating every face corner would preserve flat face
    # colours but would turn the coupon into an open indexed triangle soup.
    face_rgb = palette_rgb[np.asarray(mesh.face_states, dtype=np.intp)]
    vertex_rgb = np.zeros((len(mesh.vertices_mm), 3), dtype=np.float64)
    vertex_weight = np.zeros(len(mesh.vertices_mm), dtype=np.float64)
    for face, colour in zip(mesh.faces, face_rgb, strict=True):
        vertex_rgb[face] += colour
        vertex_weight[face] += 1.0
    if np.any(vertex_weight <= 0.0):
        raise VariableSkinHeadError("Blocky head contains an unused OBJ vertex")
    vertex_rgb /= vertex_weight[:, None]
    obj_vertices = [tuple(map(float, value)) for value in mesh.vertices_mm]
    obj_colors = [tuple(map(float, value)) for value in vertex_rgb]
    obj_faces: list[tuple[int, int, int]] = []
    obj_states: list[int] = []
    inset = float(REFERENCE_OBJ_FACE_INSET_FRACTION)
    for face, raw_state in zip(mesh.faces, mesh.face_states, strict=True):
        state = int(raw_state)
        source_ids = tuple(int(value) for value in face)
        triangle = np.asarray(mesh.vertices_mm[list(source_ids)], dtype=np.float64)
        inset_points = np.asarray(
            [
                (1.0 - 2.0 * inset) * triangle[index]
                + inset * triangle[(index + 1) % 3]
                + inset * triangle[(index + 2) % 3]
                for index in range(3)
            ],
            dtype=np.float64,
        )
        inset_ids: list[int] = []
        exact_colour = tuple(map(float, palette_rgb[state]))
        for point in inset_points:
            inset_ids.append(len(obj_vertices))
            obj_vertices.append(tuple(map(float, point)))
            obj_colors.append(exact_colour)
        a, b, c = source_ids
        qa, qb, qc = inset_ids
        children = (
            (qa, qb, qc),
            (a, b, qb),
            (a, qb, qa),
            (b, c, qc),
            (b, qc, qb),
            (c, a, qa),
            (c, qa, qc),
        )
        obj_faces.extend(children)
        obj_states.extend([state] * len(children))
    obj_vertices_array = np.asarray(obj_vertices, dtype=np.float64)
    obj_faces_array = np.asarray(obj_faces, dtype=np.int32)
    obj_topology = engine.edge_topology(obj_faces_array, len(obj_vertices_array))
    if (
        int(obj_topology.get("boundary_edges", -1)) != 0
        or int(obj_topology.get("nonmanifold_edges", -1)) != 0
    ):
        raise VariableSkinHeadError("Reference OBJ inset subdivision is not watertight")
    if not math.isclose(
        float(engine.signed_volume(obj_vertices_array, obj_faces_array)),
        float(mesh.source_volume_mm3),
        rel_tol=1.0e-10,
        abs_tol=1.0e-8,
    ):
        raise VariableSkinHeadError("Reference OBJ inset subdivision changed the solid")
    used = sorted(set(int(value) for value in mesh.face_states))
    with mtl_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# ChromaMatter original synthetic left-lit blocky head\n")
        for state in used:
            value = palette_hex[state]
            rgb = [int(value[offset : offset + 2], 16) / 255.0 for offset in (1, 3, 5)]
            stream.write(f"\nnewmtl state_{state + 1:02d}\n")
            stream.write(f"Kd {rgb[0]:.8f} {rgb[1]:.8f} {rgb[2]:.8f}\n")
            stream.write("Ka 0 0 0\nKs 0 0 0\nillum 1\n")
    with obj_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Original synthetic model; no external model asset used.\n")
        stream.write(f"mtllib {mtl_path.name}\n")
        stream.write("o original_blocky_left_lit_head\n")
        stream.write(
            "# Planar inset vertex-colour carrier; surface shape and volume unchanged.\n"
        )
        for (x, y, z), (red, green, blue) in zip(
            obj_vertices,
            obj_colors,
            strict=True,
        ):
            stream.write(
                f"v {x:.9g} {y:.9g} {z:.9g} "
                f"{red:.9g} {green:.9g} {blue:.9g}\n"
            )
        active_state: int | None = None
        for face, raw_state in zip(obj_faces, obj_states, strict=True):
            state = int(raw_state)
            if state != active_state:
                stream.write(f"usemtl state_{state + 1:02d}\n")
                active_state = state
            stream.write(
                f"f {int(face[0]) + 1} {int(face[1]) + 1} {int(face[2]) + 1}\n"
            )


def _project_view(
    vertices: np.ndarray,
    *,
    view_from_object: Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    view = np.asarray(view_from_object, dtype=np.float64)
    view /= np.linalg.norm(view)
    world_up = np.asarray([0.0, 0.0, 1.0], dtype=np.float64)
    right = np.cross(world_up, view)
    if np.linalg.norm(right) <= 1.0e-9:
        right = np.asarray([1.0, 0.0, 0.0], dtype=np.float64)
    right /= np.linalg.norm(right)
    up = np.cross(view, right)
    up /= np.linalg.norm(up)
    projected = np.column_stack((vertices @ right, vertices @ up))
    depth = vertices @ view
    return projected, depth


def _draw_mesh_view(
    image: Image.Image,
    bounds: tuple[int, int, int, int],
    mesh: BlockyHeadMesh,
    palette_hex: Sequence[str],
    *,
    label: str,
    view_from_object: Sequence[float],
) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=18, fill="#111821", outline="#355066", width=2)
    draw.text((left + 18, top + 14), label, fill="#F5F1E8")
    projected, depth = _project_view(
        np.asarray(mesh.vertices_mm, dtype=np.float64),
        view_from_object=view_from_object,
    )
    minimum = projected.min(axis=0)
    maximum = projected.max(axis=0)
    span = np.maximum(maximum - minimum, 1.0e-9)
    available_width = right - left - 60
    available_height = bottom - top - 80
    scale = min(available_width / span[0], available_height / span[1])
    centre = 0.5 * (minimum + maximum)
    canvas_centre = np.asarray(
        [0.5 * (left + right), 0.5 * (top + 45 + bottom)], dtype=np.float64
    )
    screen = (projected - centre) * scale
    screen[:, 1] *= -1.0
    screen += canvas_centre
    order = sorted(
        range(len(mesh.faces)),
        key=lambda index: float(np.mean(depth[mesh.faces[index]])),
    )
    for face_index in order:
        points = [
            (float(screen[index, 0]), float(screen[index, 1]))
            for index in mesh.faces[face_index]
        ]
        state = int(mesh.face_states[face_index])
        draw.polygon(points, fill=palette_hex[state], outline="#20262D")


def _write_preview(
    path: Path,
    mesh: BlockyHeadMesh,
    palette: PaletteSettings,
) -> None:
    # Render at 2x and reduce once.  The source geometry, face order, colours,
    # font and resampling filter are all fixed, making this a stable QA image.
    image = Image.new("RGB", (2400, 1280), "#0B1016")
    palette_hex = _palette_hex_values(palette)
    _draw_mesh_view(
        image,
        (40, 70, 1180, 1160),
        mesh,
        palette_hex,
        label="FRONT / LEFT-LIT CEL BANDS",
        view_from_object=(0.0, -1.0, 0.0),
    )
    _draw_mesh_view(
        image,
        (1220, 70, 2360, 1160),
        mesh,
        palette_hex,
        label="ISOMETRIC / ORIGINAL SYNTHETIC HEAD",
        view_from_object=(-1.0, -1.0, 0.72),
    )
    draw = ImageDraw.Draw(image)
    x = 80
    for label, color in zip(PHYSICAL_LABELS, PHYSICAL_HEX, strict=True):
        draw.rectangle((x, 1190, x + 42, 1232), fill=color, outline="#DDE7EF")
        draw.text((x + 54, 1197), label, fill="#DDE7EF")
        x += 560
    reduced = image.resize((1200, 640), Image.Resampling.LANCZOS)
    reduced.save(path, format="PNG", optimize=False, compress_level=9)


def _mapping_rows(
    mesh: BlockyHeadMesh,
    palette: PaletteSettings,
    schedule: RadialThicknessSchedule,
) -> list[dict[str, object]]:
    palette_hex = _palette_hex_values(palette)
    display_specs = mixer.palette_mix_specs(
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    output_specs = mixer.print_palette_mix_specs(
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
        palette.output_mix_ratios_b,
    )
    counts = np.bincount(mesh.face_states, minlength=palette.palette_state_count)
    schedule_by_state = {item.state_id: item for item in schedule.states}
    lstar = [float(srgb_hex_to_lab(value)[0]) for value in PHYSICAL_HEX]
    rows: list[dict[str, object]] = []
    for state in sorted(set(int(value) for value in mesh.face_states)):
        if state < 4:
            pair = f"F{state + 1} pure"
            display_ratio_b: int | str = 100
            output_ratio_b: int | str = 100
            delta_l: float | str = 0.0
        else:
            left, right, display_ratio_b = display_specs[state - 4]
            output_left, output_right, output_ratio_b = output_specs[state - 4]
            if (left, right) != (output_left, output_right):
                raise VariableSkinHeadError("Display/output palette pair order drifted")
            pair = f"F{left + 1}+F{right + 1}"
            display_ratio_b = int(display_ratio_b)
            output_ratio_b = int(output_ratio_b)
            delta_l = round(abs(lstar[right] - lstar[left]), 4)
        if state in SKIN_RADIAL_STATES:
            routing = "radial-variable-physical-skin"
            item = schedule_by_state[state]
            thickness: float | str = round(float(item.thickness_mm), 4)
            band: int | str = int(item.band_index)
        elif state in HAIR_CONVENTIONAL_STATES:
            routing = "conventional-low-delta-l"
            thickness = ""
            band = ""
        elif state == STATE_BLACK:
            routing = "preserved-pure-black"
            thickness = ""
            band = ""
        elif state == STATE_WHITE:
            routing = "preserved-pure-white"
            thickness = ""
            band = ""
        else:
            routing = "other-pure-control"
            thickness = ""
            band = ""
        rows.append(
            {
                "state_id_internal": state,
                "state_id_display": state + 1,
                "preview_hex": palette_hex[state],
                "pair": pair,
                "display_ratio_b_or_pure_percent": display_ratio_b,
                "conventional_output_ratio_b_or_pure_percent": output_ratio_b,
                "physical_pair_delta_l": delta_l,
                "routing": routing,
                "schedule_basis": schedule.basis,
                "schedule_note": (
                    "normal target-L* mapping; F1/F2 ratios 5/25/50/75/95 "
                    "were authored so this coupon occupies all five bands"
                ),
                "adaptive_band_index": band,
                "partner_skin_thickness_mm": thickness,
                "source_face_count": int(counts[state]),
            }
        )
    return rows


def _write_mapping(
    path: Path,
    mesh: BlockyHeadMesh,
    palette: PaletteSettings,
    schedule: RadialThicknessSchedule,
) -> None:
    rows = _mapping_rows(mesh, palette, schedule)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_observation_sheet(path: Path) -> None:
    rows = [
        (CONVENTIONAL_FILE, "Conventional Ratio", "classic", 3, 100, "control"),
        (HYBRID_CONTROL_FILE, "Selective Hybrid", "classic", 3, 100, "solid control"),
        (HYBRID_CLASSIC_2_FILE, "Selective Hybrid", "classic", 2, 15, "time/material probe"),
        (HYBRID_CLASSIC_3_FILE, "Selective Hybrid", "classic", 3, 15, "start candidate"),
        (HYBRID_ARACHNE_3_FILE, "Selective Hybrid", "arachne", 3, 15, "wall-planner probe"),
    ]
    fieldnames = [
        "file",
        "method",
        "wall_generator",
        "core_carrier_wall_loops",
        "core_carrier_infill_percent",
        "purpose",
        "orca_load_pass",
        "per_part_overrides_visible",
        "slice_completed",
        "all_layers_checked",
        "partner_skin_continuous",
        "pure_black_details_preserved",
        "hair_remains_conventional",
        "top_bottom_surface_result",
        "estimated_time",
        "estimated_material_g",
        "physical_print_attempted",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for file_name, method, generator, walls, infill, purpose in rows:
            writer.writerow(
                {
                    "file": file_name,
                    "method": method,
                    "wall_generator": generator,
                    "core_carrier_wall_loops": walls,
                    "core_carrier_infill_percent": infill,
                    "purpose": purpose,
                }
            )


def _write_guides(
    readme_ja: Path,
    readme_en: Path,
    schedule: RadialThicknessSchedule,
) -> None:
    thicknesses = ", ".join(
        f"{value:.2f}" for value in sorted(set(schedule.thickness_by_state.values()))
    )
    ja = f"""# 可変外皮・ブロック頭部 検証バンドル

## 最初に

これは **未校正の SLICE ONLY 試験**です。Snapmaker Orcaでスライス結果を比較するための資料で、印刷可能性や色再現を保証しません。全ファイルは `print_allowed=false` です。この合成couponだけに限定した検証で、一般モデル向けproduction機能としては承認されていません。通常のChromaMatter出力、Stage A、公開既定値は変更していません。

モデルは外部作品を使わず、この検証のために作ったオリジナルのブロック頭部です。左上・正面寄りの光を想定し、肌、茶色い髪、純黒の顔ディテール、オフホワイトを一つの閉立体に配置しました。

## 比較する5ファイル

1. `{CONVENTIONAL_FILE}` — 従来のFull Spectrum Ratio、Classic、3壁、100%。
2. `{HYBRID_CONTROL_FILE}` — 選択式ハイブリッド、Classic、コア/キャリア3壁、100%対照。
3. `{HYBRID_CLASSIC_2_FILE}` — Classic、コア/キャリア2壁・15%。材料/時間を見る限界probeで、推奨値ではありません。
4. `{HYBRID_CLASSIC_3_FILE}` — Classic、コア/キャリア3壁・15%。**最初に見る候補**です。
5. `{HYBRID_ARACHNE_3_FILE}` — Arachne、コア/キャリア3壁・15%。薄い外皮の線幅化比較です。

すべて0.10 mm積層です。ハイブリッドではpartner外皮だけ1壁・100%、黒コアと従来色キャリアは各比較値をパート別overrideで指定しています。object/globalの100%値は残し、パート設定で上書きします。

## 色と可変外皮

- F1 `#121212` 純黒
- F2 `#F2B28C` 明るい肌色
- F3 `#5A321F` 茶色
- F4 `#F5F1E8` オフホワイト
- 肌色+黒（高いΔL*）だけをラジアル可変外皮へ送ります。
- 茶色い髪+黒（低いΔL*）は従来Ratioのままです。
- 純黒と純白は置き換えず保持します。

使用する5段階は `{thicknesses} mm`、範囲は **0.10–0.42 mm** です。暗い側0.10 mmは0.4 mmノズルに対する限界probeです。明るい側0.42 mmはおおむね1ライン相当の候補です。Arachneでも、実際の押出幅がモデル外皮厚と一致する保証はありません。Arachneは外皮形状を作る機能ではなく、作成済みの薄い形状を線幅へ割り当てる方法を変えるだけです。

この検証ではF1/F2の比率を5/25/50/75/95%に設定し、**アプリと同じ絶対target-L* mapping**で5帯すべてに自然に入るようにしています。coupon専用の順位remapは使っていません。したがって一般モデルが必ず5帯すべてを使うという意味ではありません。

## 協力テスト手順

1. まず各3MFを新しいSnapmaker Orcaで開き、警告とパート数を記録します。
2. オブジェクト/パート設定で、partner外皮が `1 wall / 100%`、コア/キャリアがファイル名どおりか確認します。
3. 印刷せずにスライスし、FilamentとLine Typeを全レイヤーで確認します。
4. 肌の5段階が連続しているか、純黒の目/眉/口が残るか、茶色い髪が従来混色のままか確認します。
5. 上面・下面ではwall数よりtop/bottom shellの影響が強いため、正面だけでなく水平面も確認します。
6. 所要時間、材料量、途切れ、黒の漏れを `observation_sheet.csv` に記録します。
7. 危険、不明、パート設定消失があれば印刷しないでください。実機印刷は別の明示的な承認後だけです。

`state_mapping.csv` は状態ID、ΔL*による経路、5段階の外皮厚を示します。表示色を決めるdisplay比率と、従来Ratio比較に入る黒実機補正後のoutput比率は別列です。`head_preview_front_isometric.png` は正面/斜視の照合画像です。3MFをOrcaで保存し直すとパートmetadataが正規化される可能性があるため、保存後ファイルを元ファイルと同一扱いしないでください。
"""
    en = f"""# Variable-Skin Blocky Head Validation Bundle

## Read this first

This is an **uncalibrated SLICE ONLY study** for comparing Snapmaker Orca previews. It does not guarantee printability or colour reproduction; every file declares `print_allowed=false`. It is limited to this synthetic coupon and is not approved as a production feature for general models. Normal ChromaMatter output, Stage A and public defaults are unchanged.

The model is an original synthetic blocky head made for this study, not a third-party character asset. A front-left key light creates skin and hair cel bands while authored pure-black face details and off-white controls remain on the same closed solid.

## Five files to compare

1. `{CONVENTIONAL_FILE}` — conventional Full Spectrum Ratio, Classic, 3 walls, 100%.
2. `{HYBRID_CONTROL_FILE}` — selective hybrid, Classic, 3 core/carrier walls, 100% control.
3. `{HYBRID_CLASSIC_2_FILE}` — Classic, 2 core/carrier walls and 15%; a material/time limit probe, **not a recommendation**.
4. `{HYBRID_CLASSIC_3_FILE}` — Classic, 3 core/carrier walls and 15%; the **starting candidate**.
5. `{HYBRID_ARACHNE_3_FILE}` — Arachne, 3 core/carrier walls and 15%; a thin-skin wall-planning probe.

All files use 0.10 mm layers. In the hybrids, partner shells use a per-part `1 wall / 100%` override. Black cores and conventional carriers use the wall/infill values named above. The object/global 100% value remains intact and the per-part setting is expected to supersede it.

## Colour and variable skin

- F1 `#121212` black
- F2 `#F2B28C` light skin
- F3 `#5A321F` brown
- F4 `#F5F1E8` off-white
- Only high-Delta-L* skin+black states take the variable radial path.
- Low-Delta-L* brown-hair+black states remain conventional Ratio paint.
- Authored pure black and pure white remain preserved.

The five used thicknesses are `{thicknesses} mm`, spanning **0.10–0.42 mm**. The dark-side 0.10 mm band is a limit probe for a 0.4 mm nozzle. The bright-side 0.42 mm band is approximately a one-line candidate. Arachne does **not** guarantee that actual extrusion width equals model skin thickness. It changes how an already-created thin shape is assigned to variable-width paths; it does not create the variable skin.

For this study, the F1/F2 ratios are authored as 5/25/50/75/95%. They naturally occupy all five bands through the **same absolute target-L* mapping used by the application**; there is no coupon-only rank remap. This does not imply that every general model will use all five bands.

## Volunteer test sequence

1. Open each 3MF in a current Snapmaker Orca and record warnings and part count.
2. In object/part settings, verify partner shells show `1 wall / 100%` and core/carrier settings match the filename.
3. Slice without printing; inspect both Filament and Line Type on every layer.
4. Check continuity of all five skin bands, preservation of pure-black eyes/brows/mouth, and conventional brown-hair routing.
5. Inspect horizontal top/bottom surfaces too; top/bottom shell settings can dominate there more than wall count.
6. Record time, material, discontinuities and black leakage in `observation_sheet.csv`.
7. Do not print if a setting disappears, geometry looks unsafe or results are unclear. Physical printing requires a separate explicit promotion.

`state_mapping.csv` lists state IDs, Delta-L* routing and adaptive thickness. Display ratios and black-compensated output ratios used by the conventional comparison are separate columns. `head_preview_front_isometric.png` provides front/isometric visual QA. Orca may normalize per-part metadata when resaving; do not treat a resaved project as byte-equivalent to the original study file.
"""
    readme_ja.write_text(ja, encoding="utf-8")
    readme_en.write_text(en, encoding="utf-8")


def _manifest_entry(path: Path, folder: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(folder).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_path(path),
    }


def _write_deterministic_archive(
    archive_path: Path,
    folder: Path,
    payloads: Sequence[Path],
) -> None:
    temporary = archive_path.with_name(
        f".{archive_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            for path in sorted(payloads, key=lambda value: value.name):
                info = zipfile.ZipInfo(
                    path.relative_to(folder).as_posix(),
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes(), compresslevel=9)
        with zipfile.ZipFile(temporary, "r") as reopened:
            if reopened.testzip() is not None:
                raise VariableSkinHeadError("Validation bundle ZIP has a CRC failure")
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)


def generate_variable_skin_head_bundle(
    output_directory: Path,
    *,
    progress: object | None = None,
) -> VariableSkinHeadBundle:
    """Generate the local-only head study in an explicit destination folder."""

    folder = Path(output_directory).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)

    def emit(phase: str, fraction: float, message: str) -> None:
        if callable(progress):
            progress(phase, float(fraction), message)

    emit("source", 0.02, "Building original synthetic blocky head")
    mesh = build_blocky_head_mesh()
    prepared, colours, palette = prepared_head(mesh)
    schedule = head_thickness_schedule(palette)
    expected = [
        MINIMUM_SKIN_THICKNESS_MM
        + (MAXIMUM_SKIN_THICKNESS_MM - MINIMUM_SKIN_THICKNESS_MM)
        * index
        / float(SKIN_THICKNESS_BANDS - 1)
        for index in range(SKIN_THICKNESS_BANDS)
    ]
    if not np.allclose(
        sorted(set(schedule.thickness_by_state.values())),
        expected,
        rtol=0.0,
        atol=1.0e-12,
    ):
        raise VariableSkinHeadError("Head schedule no longer occupies five bands")

    conventional = folder / CONVENTIONAL_FILE
    control = folder / HYBRID_CONTROL_FILE
    classic_2 = folder / HYBRID_CLASSIC_2_FILE
    classic_3 = folder / HYBRID_CLASSIC_3_FILE
    arachne_3 = folder / HYBRID_ARACHNE_3_FILE
    preview = folder / "head_preview_front_isometric.png"
    mapping = folder / "state_mapping.csv"
    observation = folder / "observation_sheet.csv"
    readme_ja = folder / "README_JA.md"
    readme_en = folder / "README_EN.md"
    obj = folder / "original_blocky_left_lit_head.obj"
    mtl = folder / "original_blocky_left_lit_head.mtl"
    manifest = folder / "manifest.json"
    archive_path = folder / "variable_skin_head_validation_bundle.zip"

    _write_original_obj_mtl(obj, mtl, mesh, palette)
    _write_preview(preview, mesh, palette)
    _write_mapping(mapping, mesh, palette, schedule)
    _write_observation_sheet(observation)
    _write_guides(readme_ja, readme_en, schedule)

    emit("conventional", 0.10, "Writing conventional 0.10 mm control")
    validations: list[HeadVariantValidation] = [
        _write_conventional_3mf(
            conventional,
            mesh,
            prepared,
            colours,
            palette,
            schedule,
        )
    ]

    emit("geometry", 0.24, "Building one exact variable-thickness Stage-B partition")
    result = _build_variable_stage_b(mesh, prepared, schedule)
    classic_package = _package_hybrid_result(
        result, palette, wall_generator="classic"
    )
    arachne_package = _package_hybrid_result(
        result, palette, wall_generator="arachne"
    )
    emit("hybrid", 0.55, "Writing Classic 100% control")
    validations.append(
        _write_hybrid_variant(
            control,
            classic_package,
            schedule,
            variant_id="classic-core3-solid100-control",
            wall_generator="classic",
            core_wall_loops=3,
            core_infill_percent=100,
        )
    )
    emit("hybrid", 0.66, "Writing Classic two-wall 15% probe")
    validations.append(
        _write_hybrid_variant(
            classic_2,
            classic_package,
            schedule,
            variant_id="classic-core2-sparse15-probe",
            wall_generator="classic",
            core_wall_loops=2,
            core_infill_percent=15,
        )
    )
    emit("hybrid", 0.77, "Writing Classic three-wall 15% candidate")
    validations.append(
        _write_hybrid_variant(
            classic_3,
            classic_package,
            schedule,
            variant_id="classic-core3-sparse15-candidate",
            wall_generator="classic",
            core_wall_loops=3,
            core_infill_percent=15,
        )
    )
    emit("hybrid", 0.88, "Writing Arachne three-wall 15% probe")
    validations.append(
        _write_hybrid_variant(
            arachne_3,
            arachne_package,
            schedule,
            variant_id="arachne-core3-sparse15-probe",
            wall_generator="arachne",
            core_wall_loops=3,
            core_infill_percent=15,
        )
    )

    payloads = [
        conventional,
        control,
        classic_2,
        classic_3,
        arachne_3,
        obj,
        mtl,
        preview,
        mapping,
        observation,
        readme_ja,
        readme_en,
    ]
    manifest_payload = {
        "schema": HEAD_BUNDLE_SCHEMA,
        "scope": "synthetic-coupon-only",
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "general_model_production_eligible": False,
        "source_model": "original synthetic blocky left-lit head",
        "palette": list(PHYSICAL_HEX),
        "layer_height_mm": LAYER_HEIGHT_MM,
        "thickness_schedule": schedule.to_dict(),
        "files": [_manifest_entry(path, folder) for path in payloads],
        "validations": [
            {
                "path": item.path.relative_to(folder).as_posix(),
                "method": item.method,
                "parts": item.parts,
                "vertices": item.vertices,
                "faces": item.faces,
                "interface_pairs": item.interface_pairs,
                "wall_generator": item.wall_generator,
                "core_wall_loops": item.core_wall_loops,
                "core_infill_percent": item.core_infill_percent,
                "sha256": item.sha256,
                "bytes": item.bytes,
                "static_validation_ok": item.static_validation_ok,
            }
            for item in validations
        ],
    }
    manifest.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_deterministic_archive(
        archive_path,
        folder,
        [*payloads, manifest],
    )
    emit("done", 1.0, "Variable-skin head validation bundle complete")
    return VariableSkinHeadBundle(
        folder=folder,
        conventional_path=conventional,
        hybrid_control_path=control,
        hybrid_classic_2wall_path=classic_2,
        hybrid_classic_3wall_path=classic_3,
        hybrid_arachne_3wall_path=arachne_3,
        preview_path=preview,
        mapping_path=mapping,
        observation_path=observation,
        readme_ja_path=readme_ja,
        readme_en_path=readme_en,
        manifest_path=manifest,
        archive_path=archive_path,
        validations=tuple(validations),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a local SLICE ONLY variable-skin head study."
    )
    parser.add_argument(
        "output_directory",
        type=Path,
        help="Explicit local output folder (required; no repository default).",
    )
    args = parser.parse_args(argv)
    result = generate_variable_skin_head_bundle(args.output_directory)
    print(result.archive_path)
    return 0


__all__ = [
    "BlockyHeadMesh",
    "CELL_SIZE_MM",
    "HAIR_CONVENTIONAL_STATES",
    "HEAD_BUNDLE_SCHEMA",
    "HEAD_PROCESS_POLICY_SCHEMA",
    "HEAD_SCHEMA",
    "HeadVariantValidation",
    "MAXIMUM_SKIN_THICKNESS_MM",
    "MINIMUM_SKIN_THICKNESS_MM",
    "PHYSICAL_HEX",
    "SKIN_RADIAL_STATES",
    "SKIN_THICKNESS_BANDS",
    "VariableSkinHeadBundle",
    "VariableSkinHeadError",
    "build_blocky_head_mesh",
    "generate_variable_skin_head_bundle",
    "head_palette",
    "head_thickness_schedule",
    "main",
    "prepared_head",
    "validate_variable_skin_head_3mf",
]


if __name__ == "__main__":
    raise SystemExit(main())
