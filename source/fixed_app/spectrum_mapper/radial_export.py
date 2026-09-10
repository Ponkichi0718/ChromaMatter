"""Strict experimental 3MF writer for physical radial-shell volumes.

This module deliberately does not reuse :func:`engine.write_3mf_atomic`.
That writer represents colour with triangle paint states and currently assigns
extruder 1 to every normal part.  A radial shell is different: geometry owns
the material, every part must select one of the four physical U1 tools, and
every physical region must remain a closed positive-volume mesh.  Keeping this
boundary separate also makes the
initial output impossible to mistake for a print-approved production file.

The geometry builder lives in ``radial_shell.py``.  This module only accepts
its already disjoint, exact-touch volumes and serializes them as components of
one ModelObject / one PrintObject.  No mixed-material recipe or triangle paint
is written.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import math
import os
import uuid
import zipfile
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree as ET

import numpy as np


RADIAL_SCHEMA = "tripo-spectrum-mapper.radial-shell.experimental.v1"
COLOR_DEPTH_EXPORT_SCHEMA = (
    "tripo-spectrum-mapper.color-depth.export.experimental.v1"
)
RADIAL_PROCESS_PROFILE_MVP_020 = "radial-mvp-0p20"
RADIAL_PROCESS_PROFILE_BLACK_COUPON_010 = "black-radial-coupon-0p10"
RADIAL_PROCESS_PROFILE_BLACK_COUPON_ARACHNE_010 = (
    "black-radial-coupon-arachne-0p10"
)
RADIAL_PROCESS_PROFILE_COMPACT_BLACK_COUPON_010 = (
    "compact-black-radial-coupon-0p10"
)
RADIAL_PROCESS_PROFILE_COMPACT_BLACK_COUPON_ARACHNE_010 = (
    "compact-black-radial-coupon-arachne-0p10"
)
RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_010 = (
    "large-frustum-black-radial-coupon-0p10"
)
RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_ARACHNE_010 = (
    "large-frustum-black-radial-coupon-arachne-0p10"
)
RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010 = "radial-general-classic-0p10"
RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010 = "radial-general-arachne-0p10"
_BLACK_RADIAL_COUPON_SCHEMA = "chromamatter.black-radial-coupon.v1"
_COMPACT_BLACK_RADIAL_COUPON_SCHEMA = (
    "chromamatter.compact-black-radial-pyramid.v1"
)
_LARGE_FRUSTUM_BLACK_RADIAL_COUPON_SCHEMA = (
    "chromamatter.large-black-radial-frustum.v1"
)
_PROCESS_PROFILES = {
    RADIAL_PROCESS_PROFILE_MVP_020: {
        "layer_height_mm": 0.20,
        "initial_layer_height_mm": 0.20,
        "print_settings_id": "0.20 Standard @Snapmaker U1 (0.4 nozzle)",
        "top_shell_layers": "3",
        "top_shell_thickness": "0.6",
        "bottom_shell_layers": "3",
        "bottom_shell_thickness": "0.6",
        "wall_loops": "1",
        "wall_generator": "classic",
        "detect_thin_wall": "1",
        "only_one_wall_top": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.42",
    },
    # This profile is deliberately coupon-only.  It does not relax the
    # production Radial MVP contract: callers must explicitly opt in, the
    # archive remains SLICE ONLY, and the validator re-opens the exact process
    # marker together with the 0.10 mm setting.
    RADIAL_PROCESS_PROFILE_BLACK_COUPON_010: {
        "layer_height_mm": 0.10,
        "initial_layer_height_mm": 0.20,
        "print_settings_id": "0.10 Black-Radial Validation @Snapmaker U1 (0.4 nozzle)",
        "top_shell_layers": "5",
        "top_shell_thickness": "0.5",
        "bottom_shell_layers": "5",
        "bottom_shell_thickness": "0.5",
        "wall_loops": "2",
        "wall_generator": "classic",
        "detect_thin_wall": "0",
        "only_one_wall_top": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "coupon_method": "radial-physical-thickness",
    },
    # Same physical geometry as the Classic coupon.  Only the wall planner is
    # changed so a single print can show whether Arachne keeps the 0.21/0.42 mm
    # partner skin continuous.  The 85% bead floor is Snapmaker/Orca's safe
    # 0.4 mm-nozzle baseline; it deliberately does not promise a true 0.21 mm
    # extrusion line.
    RADIAL_PROCESS_PROFILE_BLACK_COUPON_ARACHNE_010: {
        "layer_height_mm": 0.10,
        "initial_layer_height_mm": 0.20,
        "print_settings_id": (
            "0.10 Black-Radial Arachne Validation @Snapmaker U1 (0.4 nozzle)"
        ),
        "top_shell_layers": "5",
        "top_shell_thickness": "0.5",
        "bottom_shell_layers": "5",
        "bottom_shell_thickness": "0.5",
        "wall_loops": "2",
        "wall_generator": "arachne",
        "detect_thin_wall": "0",
        "only_one_wall_top": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "wall_distribution_count": "1",
        "min_bead_width": "85%",
        "initial_layer_min_bead_width": "85%",
        "min_feature_size": "25%",
        "wall_transition_length": "100%",
        "wall_transition_filter_deviation": "25%",
        "wall_transition_angle": "10",
        "coupon_method": "radial-physical-thickness-arachne",
    },
    # Small, fast white/black-only pyramid used to compare real radial shells.
    # These settings are intentionally coupon-only and do not change the MVP
    # or the broad three-colour coupon.  The aggressive Arachne bead values are
    # outside Snapmaker's stock U1 profile and therefore remain SLICE ONLY.
    RADIAL_PROCESS_PROFILE_COMPACT_BLACK_COUPON_010: {
        "layer_height_mm": 0.10,
        "initial_layer_height_mm": 0.20,
        "print_settings_id": (
            "0.10 Compact Black-Radial Classic Probe @Snapmaker U1 (0.4 nozzle)"
        ),
        "top_shell_layers": "2",
        "top_shell_thickness": "0.2",
        "bottom_shell_layers": "2",
        "bottom_shell_thickness": "0.2",
        "wall_loops": "1",
        "wall_generator": "classic",
        "detect_thin_wall": "1",
        "only_one_wall_top": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "coupon_method": "compact-radial-physical-thickness",
        "coupon_metadata_key": "compact_black_radial_coupon",
        "coupon_schema": _COMPACT_BLACK_RADIAL_COUPON_SCHEMA,
        "coupon_geometry_version": "off-centre-pyramid-bands-v1",
    },
    RADIAL_PROCESS_PROFILE_COMPACT_BLACK_COUPON_ARACHNE_010: {
        "layer_height_mm": 0.10,
        "initial_layer_height_mm": 0.20,
        "print_settings_id": (
            "0.10 Compact Black-Radial Arachne Probe @Snapmaker U1 (0.4 nozzle)"
        ),
        "top_shell_layers": "2",
        "top_shell_thickness": "0.2",
        "bottom_shell_layers": "2",
        "bottom_shell_thickness": "0.2",
        "wall_loops": "1",
        "wall_generator": "arachne",
        "detect_thin_wall": "0",
        "only_one_wall_top": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "wall_distribution_count": "1",
        "min_bead_width": "25%",
        "initial_layer_min_bead_width": "85%",
        "min_feature_size": "20%",
        "wall_transition_length": "100%",
        "wall_transition_filter_deviation": "25%",
        "wall_transition_angle": "10",
        "coupon_method": "compact-radial-physical-thickness-arachne",
        "coupon_metadata_key": "compact_black_radial_coupon",
        "coupon_schema": _COMPACT_BLACK_RADIAL_COUPON_SCHEMA,
        "coupon_geometry_version": "off-centre-pyramid-bands-v1",
    },
    # Three-times-linear corner frustum with an exact first-layer Z/C/A tag
    # and a horizontal 0.10 mm top-cap probe.  These profiles intentionally
    # inherit the compact coupon's aggressive wall settings while keeping a
    # separate schema and process marker, so old compact-v2 evidence remains
    # independently identifiable and cannot validate the larger v3 geometry.
    RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_010: {
        "layer_height_mm": 0.10,
        "initial_layer_height_mm": 0.20,
        "print_settings_id": (
            "0.10 Large Frustum Black-Radial Classic Probe "
            "@Snapmaker U1 (0.4 nozzle)"
        ),
        "top_shell_layers": "2",
        "top_shell_thickness": "0.2",
        "bottom_shell_layers": "2",
        "bottom_shell_thickness": "0.2",
        "wall_loops": "1",
        "wall_generator": "classic",
        "detect_thin_wall": "1",
        "only_one_wall_top": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        # The physical regions must stay closed, but closure does not require
        # a solid sparse core.  Match the general radial policy so the black
        # core is not silently forced to 100% infill.
        "sparse_infill_density": "15%",
        "coupon_method": "large-frustum-radial-physical-thickness",
        "coupon_metadata_key": "compact_black_radial_coupon",
        "coupon_schema": _LARGE_FRUSTUM_BLACK_RADIAL_COUPON_SCHEMA,
        "coupon_geometry_version": "corner-frustum-bottom-id-top-cap-v1",
    },
    RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_ARACHNE_010: {
        "layer_height_mm": 0.10,
        "initial_layer_height_mm": 0.20,
        "print_settings_id": (
            "0.10 Large Frustum Black-Radial Arachne Probe "
            "@Snapmaker U1 (0.4 nozzle)"
        ),
        "top_shell_layers": "2",
        "top_shell_thickness": "0.2",
        "bottom_shell_layers": "2",
        "bottom_shell_thickness": "0.2",
        "wall_loops": "1",
        "wall_generator": "arachne",
        "detect_thin_wall": "0",
        "only_one_wall_top": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "wall_distribution_count": "1",
        "min_bead_width": "25%",
        "initial_layer_min_bead_width": "85%",
        "min_feature_size": "20%",
        "wall_transition_length": "100%",
        "wall_transition_filter_deviation": "25%",
        "wall_transition_angle": "10",
        # Arachne changes perimeter planning only; use the same ordinary
        # sparse-core policy as the Classic and general radial profiles.
        "sparse_infill_density": "15%",
        "coupon_method": "large-frustum-radial-physical-thickness-arachne",
        "coupon_metadata_key": "compact_black_radial_coupon",
        "coupon_schema": _LARGE_FRUSTUM_BLACK_RADIAL_COUPON_SCHEMA,
        "coupon_geometry_version": "corner-frustum-bottom-id-top-cap-v1",
    },
    # General-model profiles intentionally share the validated one-wall
    # settings used by the large frustum probe, without its coupon metadata
    # gate.  They remain SLICE ONLY through the common radial archive contract.
    RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010: {
        "layer_height_mm": 0.10,
        "initial_layer_height_mm": 0.20,
        "print_settings_id": (
            "0.10 General Radial Classic @Snapmaker U1 (0.4 nozzle)"
        ),
        "top_shell_layers": "2",
        "top_shell_thickness": "0.2",
        "bottom_shell_layers": "2",
        "bottom_shell_thickness": "0.2",
        "wall_loops": "1",
        "wall_generator": "classic",
        "detect_thin_wall": "1",
        "only_one_wall_top": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        # General models use an ordinary conservative sparse core.  Closed
        # physical regions, perimeters and top/bottom shells remain mandatory.
        "sparse_infill_density": "15%",
    },
    RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010: {
        "layer_height_mm": 0.10,
        "initial_layer_height_mm": 0.20,
        "print_settings_id": (
            "0.10 General Radial Arachne @Snapmaker U1 (0.4 nozzle)"
        ),
        "top_shell_layers": "2",
        "top_shell_thickness": "0.2",
        "bottom_shell_layers": "2",
        "bottom_shell_thickness": "0.2",
        "wall_loops": "1",
        "wall_generator": "arachne",
        "detect_thin_wall": "0",
        "only_one_wall_top": "0",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "wall_distribution_count": "1",
        "min_bead_width": "25%",
        "initial_layer_min_bead_width": "85%",
        "min_feature_size": "20%",
        "wall_transition_length": "100%",
        "wall_transition_filter_deviation": "25%",
        "wall_transition_angle": "10",
        # Match the Classic general-model profile: Arachne changes perimeter
        # planning, not the normal sparse-infill policy.
        "sparse_infill_density": "15%",
    },
}
_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PRODUCTION_NS = (
    "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
)
_ALLOWED_ROLES = frozenset(
    {
        "pure_black_core",
        "partner_outer_shell",
        # Reserved physical-only roles for the later three-zone/cap builder.
        "light_core",
        "physical_cap",
        "color_depth_physical_union",
    }
)
_ROLE_ALIASES = {
    "inner_dark": "pure_black_core",
    "outer_skin": "partner_outer_shell",
    "core": "light_core",
}
_REQUIRED_ARCHIVE_MEMBERS = frozenset(
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
_COMMON_TRANSITION_SETTINGS = {
    "enable_prime_tower": "1",
    "prime_tower_width": "30",
    "prime_volume": "18",
    "prime_tower_brim_width": "5",
    "wipe_tower_filament": "0",
    "wipe_tower_no_sparse_layers": "0",
    "wipe_tower_wall_type": "rib",
    "wipe_tower_extra_rib_length": "8",
    "wipe_tower_extra_spacing": "120%",
    "wipe_tower_cone_angle": "15",
    "ooze_prevention": "1",
    "standby_temperature_delta": "-150",
}


class RadialExportError(RuntimeError):
    """Raised when physical radial geometry cannot be exported safely."""


@dataclass(frozen=True, slots=True)
class RadialExportPart:
    """One positive-volume physical material region in millimetres."""

    name: str
    role: str
    vertices_mm: np.ndarray
    faces: np.ndarray
    extruder: int
    # Legacy API name.  This flag is a closed physical-volume assertion, not
    # a request for 100% slicer infill; sparse density belongs to the process
    # profile and is validated independently.
    solid_infill: bool = True
    source_state: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def physical_extruder(self) -> int:
        """Compatibility alias used by early radial-shell prototypes."""

        return self.extruder


@dataclass(frozen=True, slots=True)
class RadialExportPackage:
    """Validated input contract for one experimental radial 3MF."""

    parts: tuple[RadialExportPart, ...]
    physical_hex: tuple[str, str, str, str]
    black_extruder: int
    metadata: Mapping[str, object] = field(default_factory=dict)
    layer_height_mm: float = 0.20
    initial_layer_height_mm: float = 0.20
    renderer: str = "radial"
    process_profile: str = RADIAL_PROCESS_PROFILE_MVP_020


@dataclass(frozen=True, slots=True)
class RadialExportValidation:
    """Archive-level proof returned by the dedicated writer."""

    path: Path
    sha256: str
    bytes: int
    parts: int
    vertices: int
    faces: int
    physical_extruders: tuple[int, ...]
    zip_crc_ok: bool
    slice_only: bool
    print_allowed: bool
    physical_materials_only: bool
    static_validation_ok: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "bytes": self.bytes,
            "parts": self.parts,
            "vertices": self.vertices,
            "faces": self.faces,
            "physical_extruders": list(self.physical_extruders),
            "zip_crc_ok": self.zip_crc_ok,
            "slice_only": self.slice_only,
            "print_allowed": self.print_allowed,
            "physical_materials_only": self.physical_materials_only,
            "static_validation_ok": self.static_validation_ok,
        }


@dataclass(frozen=True, slots=True)
class _CheckedPart:
    part: RadialExportPart
    vertices: np.ndarray
    faces: np.ndarray
    signed_volume_mm3: float


def _normalise_hex(value: object) -> str:
    text = str(value).strip().upper()
    if len(text) != 7 or not text.startswith("#"):
        raise RadialExportError(f"Invalid physical filament colour: {value!r}")
    try:
        int(text[1:], 16)
    except ValueError as exc:
        raise RadialExportError(
            f"Invalid physical filament colour: {value!r}"
        ) from exc
    return text


def radial_process_profile_sparse_infill_percent(profile_name: str) -> int:
    """Return the fail-closed sparse-infill policy for a radial profile."""

    name = str(profile_name).strip()
    profile = _PROCESS_PROFILES.get(name)
    if profile is None:
        raise RadialExportError(f"Unsupported radial process profile: {name!r}")
    value = str(profile.get("sparse_infill_density", "100%")).strip()
    if not value.endswith("%"):
        raise RadialExportError(
            f"Radial process profile {name!r} has invalid sparse infill"
        )
    try:
        percent = int(value[:-1])
    except ValueError as exc:
        raise RadialExportError(
            f"Radial process profile {name!r} has invalid sparse infill"
        ) from exc
    if not 0 <= percent <= 100 or value != f"{percent}%":
        raise RadialExportError(
            f"Radial process profile {name!r} has invalid sparse infill"
        )
    return percent


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RadialExportError("Experimental metadata contains NaN/Inf")
        return value
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    raise RadialExportError(
        f"Experimental metadata is not JSON serialisable: {type(value).__name__}"
    )


def _validate_process_profile_metadata(
    metadata: object,
    profile_name: str,
) -> None:
    """Keep special validation profiles from escaping their narrow fixture."""

    profile = _PROCESS_PROFILES[profile_name]
    coupon_method = profile.get("coupon_method")
    if coupon_method is None:
        return
    if not isinstance(metadata, Mapping):
        raise RadialExportError(
            f"Radial process profile {profile_name!r} needs coupon metadata"
        )
    metadata_key = str(profile.get("coupon_metadata_key", "black_radial_coupon"))
    wrapper = metadata.get(metadata_key)
    if not isinstance(wrapper, Mapping):
        raise RadialExportError(
            f"Radial process profile {profile_name!r} is coupon-only"
        )
    required = {
        "schema": str(profile.get("coupon_schema", _BLACK_RADIAL_COUPON_SCHEMA)),
        "method": str(coupon_method),
        "geometry_version": str(
            profile.get("coupon_geometry_version", "multi-surface-prism-v1")
        ),
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "physical_materials_only": True,
    }
    for key, expected in required.items():
        if wrapper.get(key) != expected:
            raise RadialExportError(
                f"Coupon-only radial profile metadata {key} drifted: "
                f"{wrapper.get(key)!r} != {expected!r}"
            )


def _canonical_role(value: object) -> str:
    role = str(value).strip()
    role = _ROLE_ALIASES.get(role, role)
    if role not in _ALLOWED_ROLES:
        raise RadialExportError(f"Unsupported radial material role: {value!r}")
    return role


def _edge_topology(faces: np.ndarray) -> tuple[int, int, bool]:
    directed = np.vstack(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])
    )
    undirected = np.sort(directed, axis=1)
    unique, inverse, counts = np.unique(
        undirected, axis=0, return_inverse=True, return_counts=True
    )
    del unique
    boundary = int(np.count_nonzero(counts == 1))
    nonmanifold = int(np.count_nonzero(counts > 2))
    direction = np.where(directed[:, 0] < directed[:, 1], 1, -1)
    direction_sum = np.bincount(inverse, weights=direction)
    winding_consistent = bool(
        not boundary
        and not nonmanifold
        and np.all(direction_sum == 0)
    )
    return boundary, nonmanifold, winding_consistent


def _check_part(part: RadialExportPart, index: int) -> _CheckedPart:
    name = str(part.name).strip()
    if not name:
        raise RadialExportError(f"Radial part {index + 1} has no name")
    role = _canonical_role(part.role)
    if isinstance(part.extruder, bool):
        raise RadialExportError(f"Radial part {name!r} has an invalid extruder")
    extruder = int(part.extruder)
    if not 1 <= extruder <= 4:
        raise RadialExportError(
            f"Radial part {name!r} must use physical extruder 1..4"
        )
    if not bool(part.solid_infill):
        raise RadialExportError(
            f"Radial part {name!r} is not a closed physical volume; the "
            "experimental writer requires every material region to be closed"
        )

    vertices = np.asarray(part.vertices_mm, dtype=np.float64)
    faces = np.asarray(part.faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1:] != (3,) or len(vertices) < 4:
        raise RadialExportError(f"Radial part {name!r} has invalid vertices")
    if faces.ndim != 2 or faces.shape[1:] != (3,) or len(faces) < 4:
        raise RadialExportError(f"Radial part {name!r} has invalid triangles")
    if not np.isfinite(vertices).all():
        raise RadialExportError(f"Radial part {name!r} contains NaN/Inf")
    if int(faces.min()) < 0 or int(faces.max()) >= len(vertices):
        raise RadialExportError(f"Radial part {name!r} has an invalid face index")
    if np.any(
        (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 2] == faces[:, 0])
    ):
        raise RadialExportError(f"Radial part {name!r} has a degenerate index face")
    triangles = vertices[faces]
    double_area = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    )
    if np.any(double_area <= 1e-14):
        raise RadialExportError(f"Radial part {name!r} has a zero-area face")
    canonical_faces = np.sort(faces, axis=1)
    if len(np.unique(canonical_faces, axis=0)) != len(faces):
        raise RadialExportError(f"Radial part {name!r} repeats a triangle")
    boundary, nonmanifold, winding = _edge_topology(faces)
    if boundary or nonmanifold or not winding:
        raise RadialExportError(
            f"Radial part {name!r} is not a closed oriented 2-manifold "
            f"(boundary={boundary}, nonmanifold={nonmanifold}, winding={winding})"
        )
    signed_volume = float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )
    if not math.isfinite(signed_volume) or signed_volume <= 1e-12:
        raise RadialExportError(
            f"Radial part {name!r} is not an outward positive-volume mesh"
        )
    # Normalise aliases once so archive metadata cannot drift from validation.
    checked = RadialExportPart(
        name=name,
        role=role,
        vertices_mm=vertices,
        faces=faces.astype(np.int32, copy=False),
        extruder=extruder,
        solid_infill=True,
        source_state=(
            None if part.source_state is None else int(part.source_state)
        ),
        metadata=_json_safe(part.metadata),
    )
    return _CheckedPart(checked, vertices, checked.faces, signed_volume)


def _check_package(package: RadialExportPackage) -> tuple[_CheckedPart, ...]:
    if not package.parts:
        raise RadialExportError("A radial export needs at least one physical part")
    physical = tuple(_normalise_hex(value) for value in package.physical_hex)
    if len(physical) != 4:
        raise RadialExportError("Snapmaker U1 radial output requires four colours")
    if isinstance(package.black_extruder, bool):
        raise RadialExportError("The black extruder must be a physical tool 1..4")
    black = int(package.black_extruder)
    if not 1 <= black <= 4:
        raise RadialExportError("The black extruder must be a physical tool 1..4")
    for height, label in (
        (package.layer_height_mm, "layer height"),
        (package.initial_layer_height_mm, "initial layer height"),
    ):
        if not math.isfinite(float(height)) or float(height) <= 0:
            raise RadialExportError(f"Invalid {label}: {height!r}")
    profile_name = str(package.process_profile).strip()
    profile = _PROCESS_PROFILES.get(profile_name)
    if profile is None:
        raise RadialExportError(
            f"Unsupported radial process profile: {package.process_profile!r}"
        )
    for actual, key, label in (
        (package.layer_height_mm, "layer_height_mm", "layer height"),
        (
            package.initial_layer_height_mm,
            "initial_layer_height_mm",
            "initial layer height",
        ),
    ):
        if abs(float(actual) - float(profile[key])) > 1e-9:
            raise RadialExportError(
                f"Radial process profile {profile_name!r} requires "
                f"{label} {float(profile[key]):.2f} mm"
            )
    safe_metadata = _json_safe(package.metadata)
    _validate_process_profile_metadata(safe_metadata, profile_name)
    renderer = str(package.renderer).strip().lower()
    if renderer not in {"radial", "color_depth"}:
        raise RadialExportError(f"Unsupported physical renderer: {package.renderer!r}")
    checked = tuple(_check_part(part, index) for index, part in enumerate(package.parts))
    if renderer == "color_depth":
        if len(checked) > 4:
            raise RadialExportError(
                "ColorDepth output may contain at most four physical unions"
            )
        if any(
            item.part.role != "color_depth_physical_union"
            for item in checked
        ):
            raise RadialExportError(
                "Every ColorDepth part must be a color_depth_physical_union"
            )
        if len({item.part.extruder for item in checked}) != len(checked):
            raise RadialExportError(
                "ColorDepth output must contain at most one union per physical tool"
            )
        return checked
    black_parts = [item for item in checked if item.part.role == "pure_black_core"]
    outer_parts = [
        item for item in checked if item.part.role == "partner_outer_shell"
    ]
    if not black_parts or not outer_parts:
        raise RadialExportError(
            "The MVP archive requires both pure_black_core and partner_outer_shell"
        )
    if any(item.part.extruder != black for item in black_parts):
        raise RadialExportError(
            "Every pure_black_core must use the declared physical black extruder"
        )
    if any(item.part.extruder == black for item in outer_parts):
        raise RadialExportError(
            "A partner_outer_shell cannot use the physical black extruder"
        )
    last_black = max(
        index
        for index, item in enumerate(checked)
        if item.part.role == "pure_black_core"
    )
    first_outer = min(
        index
        for index, item in enumerate(checked)
        if item.part.role == "partner_outer_shell"
    )
    if last_black >= first_outer:
        raise RadialExportError(
            "Physical parts must be ordered black core first and partner outer shell last"
        )
    return checked


def package_from_color_depth(
    result: object,
    physical_hex: Sequence[str],
) -> RadialExportPackage:
    """Adapt a validated ColorDepth cell result to the physical 3MF writer."""

    raw_parts = tuple(getattr(result, "parts", ()))
    if not raw_parts or len(raw_parts) > 4:
        raise RadialExportError(
            "ColorDepth requires one to four physical material unions"
        )
    parts: list[RadialExportPart] = []
    for raw in sorted(raw_parts, key=lambda item: int(getattr(item, "extruder"))):
        extruder = int(getattr(raw, "extruder"))
        parts.append(
            RadialExportPart(
                name=str(getattr(raw, "name", f"ColorDepth physical F{extruder}")),
                role="color_depth_physical_union",
                vertices_mm=np.asarray(getattr(raw, "vertices_mm"), dtype=np.float64),
                faces=np.asarray(getattr(raw, "faces"), dtype=np.int32),
                extruder=extruder,
                solid_infill=bool(getattr(raw, "solid_infill", True)),
                metadata=getattr(raw, "metadata", {}) or {},
            )
        )
    metadata = dict(getattr(result, "metadata", {}) or {})
    interfaces = tuple(getattr(result, "interfaces", ()))
    source_volume = float(getattr(result, "source_volume_mm3", float("nan")))
    output_volume = float(getattr(result, "output_volume_mm3", float("nan")))
    if (
        not math.isfinite(source_volume)
        or source_volume <= 0.0
        or not math.isfinite(output_volume)
        or output_volume <= 0.0
        or abs(output_volume - source_volume)
        > 1e-8 * max(source_volume, 1.0)
    ):
        raise RadialExportError("ColorDepth material regions do not conserve volume")
    if metadata.get("physical_materials_only") is not True:
        raise RadialExportError("ColorDepth result is not physical-material-only")
    if metadata.get("shared_interface_partition_exact") is not True:
        raise RadialExportError(
            "ColorDepth result has no shared material-interface partition proof"
        )
    if metadata.get("external_surface_coverage_exact") is not True:
        raise RadialExportError(
            "ColorDepth result has no exact source-exterior coverage proof"
        )
    if metadata.get("unsafe_columns_outer_only_verified") is not True:
        raise RadialExportError(
            "ColorDepth result has no unsafe-column outer-only proof"
        )
    for key in ("ratio_definitions", "cycle_definitions", "virtual_mix_definitions", "painted_triangles"):
        if int(metadata.get(key, -1)) != 0:
            raise RadialExportError(f"ColorDepth result contains forbidden {key}")
    if float(metadata.get("positive_overlap_mm3", float("inf"))) != 0.0:
        raise RadialExportError("ColorDepth material regions overlap")
    if float(metadata.get("gap_mm", float("inf"))) != 0.0:
        raise RadialExportError("ColorDepth material regions contain a gap")
    if not interfaces and len(parts) > 1:
        raise RadialExportError("ColorDepth result has no exact interface proof")
    for record in interfaces:
        if not isinstance(record, Mapping) or (
            record.get("exact_coordinate_triangles") is not True
            or record.get("opposite_winding") is not True
            or float(record.get("gap_mm", float("inf"))) != 0.0
            or float(record.get("positive_overlap_mm3", float("inf"))) != 0.0
        ):
            raise RadialExportError("A ColorDepth interface is not exact-touch")
    metadata = {
        **metadata,
        "renderer": "ColorDepth Lab",
        "source_volume_mm3": source_volume,
        "output_volume_mm3": output_volume,
        "interfaces": list(interfaces),
        "legacy_fullspectrum_ratios_used": False,
    }
    physical = tuple(_normalise_hex(value) for value in physical_hex)
    if len(physical) != 4:
        raise RadialExportError("Exactly four physical colours are required")
    return RadialExportPackage(
        parts=tuple(parts),
        physical_hex=physical,  # type: ignore[arg-type]
        # Retained only for the common archive dataclass; ColorDepth validation
        # does not assign a special role to this physical slot.
        black_extruder=1,
        metadata=metadata,
        renderer="color_depth",
    )


def package_from_radial_shell(
    result: object,
    physical_hex: Sequence[str],
    *,
    geometry_scale_mm: float = 1.0,
    process_profile: str = RADIAL_PROCESS_PROFILE_MVP_020,
    layer_height_mm: float = 0.20,
    initial_layer_height_mm: float = 0.20,
) -> RadialExportPackage:
    """Adapt the geometry builder result without importing its implementation."""

    scale = float(geometry_scale_mm)
    if not math.isfinite(scale) or scale <= 0:
        raise RadialExportError(
            f"Invalid radial geometry scale: {geometry_scale_mm!r}"
        )
    raw_parts = tuple(getattr(result, "parts", ()))
    if not raw_parts:
        raise RadialExportError("The radial shell result contains no parts")
    parts: list[RadialExportPart] = []
    for raw in raw_parts:
        extruder = getattr(raw, "extruder", None)
        if extruder is None:
            extruder = getattr(raw, "physical_filament", None)
        if extruder is None:
            extruder = getattr(raw, "physical_extruder", None)
        if extruder is None:
            raise RadialExportError(
                f"Radial part {getattr(raw, 'name', '')!r} has no physical extruder"
            )
        source_state = getattr(raw, "source_state", None)
        if source_state is None:
            source_state = getattr(raw, "source_state_id", None)
        parts.append(
            RadialExportPart(
                name=str(getattr(raw, "name", "")),
                role=str(getattr(raw, "role", "")),
                vertices_mm=(
                    np.asarray(getattr(raw, "vertices_mm"), dtype=np.float64)
                    * scale
                ),
                faces=np.asarray(getattr(raw, "faces")),
                extruder=int(extruder),
                solid_infill=bool(getattr(raw, "solid_infill", True)),
                source_state=source_state,
                metadata=getattr(raw, "metadata", {}) or {},
            )
        )
    black = getattr(result, "black_extruder", None)
    if black is None:
        black = getattr(result, "darkest_filament", None)
    if black is None:
        black_parts = [part.extruder for part in parts if _ROLE_ALIASES.get(part.role, part.role) == "pure_black_core"]
        if not black_parts:
            raise RadialExportError("The radial shell result does not declare black")
        black = black_parts[0]
    metadata: dict[str, object] = dict(getattr(result, "metadata", {}) or {})
    metadata.setdefault("adapter_geometry_scale", scale)
    diagnostics = getattr(result, "diagnostics", None)
    if isinstance(diagnostics, Mapping):
        metadata.setdefault("diagnostics", dict(diagnostics))
    interfaces = getattr(result, "interfaces", None)
    if interfaces is not None:
        metadata.setdefault("interfaces", list(interfaces))
    for attribute in (
        "skin_thickness_mm",
        "partner_extruder",
        "eligible_state_id",
        "eligible_area_fraction",
        "source_fingerprint",
        "source_volume_mm3",
        "output_volume_mm3",
    ):
        if hasattr(result, attribute):
            metadata.setdefault(attribute, getattr(result, attribute))
    physical = tuple(_normalise_hex(value) for value in physical_hex)
    if len(physical) != 4:
        raise RadialExportError("Exactly four physical colours are required")
    source_volume = getattr(result, "source_volume_mm3", None)
    output_volume = getattr(result, "output_volume_mm3", None)
    if source_volume is not None and output_volume is not None:
        source_value = float(source_volume) * scale**3
        output_value = float(output_volume) * scale**3
        tolerance = max(1e-8, abs(source_value) * 1e-8)
        if not (
            math.isfinite(source_value)
            and source_value > 0
            and math.isfinite(output_value)
            and output_value > 0
            and abs(output_value - source_value) <= tolerance
        ):
            raise RadialExportError(
                "The radial shell result does not conserve source volume"
            )
        metadata["source_volume_mm3"] = source_value
        metadata["output_volume_mm3"] = output_value
    if metadata.get("source_exterior_preserved_exactly") is not True:
        raise RadialExportError(
            "The radial shell result did not preserve the source exterior"
        )
    if float(metadata.get("positive_overlap_mm3", float("inf"))) != 0.0:
        raise RadialExportError("The radial shell result has positive overlap")
    if float(metadata.get("gap_mm", float("inf"))) != 0.0:
        raise RadialExportError("The radial shell result has an interface gap")
    interface_records = metadata.get("interfaces")
    if not isinstance(interface_records, list) or not interface_records:
        raise RadialExportError("The radial shell result has no interface proof")
    for record in interface_records:
        if not isinstance(record, Mapping):
            raise RadialExportError("A radial interface proof is invalid")
        if (
            record.get("exact_coordinate_triangles") is not True
            or record.get("opposite_winding") is not True
            or float(record.get("gap_mm", float("inf"))) != 0.0
            or float(record.get("positive_overlap_mm3", float("inf"))) != 0.0
        ):
            raise RadialExportError("A radial interface is not exact-touch")
    return RadialExportPackage(
        parts=tuple(parts),
        physical_hex=physical,  # type: ignore[arg-type]
        black_extruder=int(black),
        metadata=metadata,
        layer_height_mm=float(layer_height_mm),
        initial_layer_height_mm=float(initial_layer_height_mm),
        process_profile=str(process_profile),
    )


def _content_types() -> bytes:
    return b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="application/octet-stream"/>
 <Default Extension="json" ContentType="application/json"/>
</Types>
'''


def _root_relationships() -> bytes:
    return b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
'''


def _model_relationships() -> bytes:
    return b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/Objects/radial_parts.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
'''


def _root_model(title: str, description: str, part_count: int) -> bytes:
    parent_id = part_count + 1
    components = "\n".join(
        (
            '    <component p:path="/3D/Objects/radial_parts.model" '
            f'objectid="{part_id}" '
            f'p:UUID="10000000-b206-40ff-9872-{part_id:012d}" '
            'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
        )
        for part_id in range(1, part_count + 1)
    )
    today = date.today().isoformat()
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="{_CORE_NS}" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="{_PRODUCTION_NS}" requiredextensions="p">
 <metadata name="Application">BambuStudio-2.3.5</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="CreationDate">{today}</metadata>
 <metadata name="ModificationDate">{today}</metadata>
 <metadata name="Title">{html.escape(title)}</metadata>
 <metadata name="Description">{html.escape(description)}</metadata>
 <resources>
  <object id="{parent_id}" p:UUID="10000001-61cb-4c03-9d28-80fed5dfa1dc" type="model">
   <components>
{components}
   </components>
  </object>
 </resources>
 <build p:UUID="10000002-22b5-4d84-8835-1976022ea369">
  <item objectid="{parent_id}" p:UUID="10000003-b1ec-4553-aec9-835e5b724bb4" transform="1 0 0 0 1 0 0 0 1 128 128 0" printable="1"/>
 </build>
</model>
'''.encode("utf-8")


def _write_parts_model(
    archive: zipfile.ZipFile,
    parts: tuple[_CheckedPart, ...],
) -> None:
    """Stream high-density child meshes instead of duplicating them in RAM."""

    with archive.open(
        "3D/Objects/radial_parts.model", "w", force_zip64=True
    ) as raw:
        out = io.BufferedWriter(raw, buffer_size=1024 * 1024)
        out.write(
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<model unit="millimeter" xml:lang="en-US" xmlns="{_CORE_NS}" '
                'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
                f'xmlns:p="{_PRODUCTION_NS}" requiredextensions="p">\n'
                ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
                ' <resources>\n'
            ).encode("utf-8")
        )
        for part_id, item in enumerate(parts, start=1):
            safe_name = html.escape(item.part.name)
            out.write(
                (
                    f'  <object id="{part_id}" '
                    f'p:UUID="10010000-81cb-4c03-9d28-{part_id:012d}" '
                    f'name="{safe_name}" type="model">\n'
                    '   <mesh>\n    <vertices>\n'
                ).encode("utf-8")
            )
            for x, y, z in item.vertices:
                # Preserve each binary64 coordinate exactly across XML
                # serialization.  A 12-significant-digit representation can
                # collapse legitimate thin Stage-B tetrahedra at model-scale
                # offsets and make the re-opened material partition invalid.
                out.write(
                    f'     <vertex x="{x:.17g}" y="{y:.17g}" z="{z:.17g}"/>\n'.encode(
                        "ascii"
                    )
                )
            out.write(b"    </vertices>\n    <triangles>\n")
            # Material is intentionally assigned only at normal-part level.
            # No paint_color attribute is emitted, so virtual states cannot leak.
            for a, b, c in item.faces:
                out.write(
                    f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>\n'.encode(
                        "ascii"
                    )
                )
            out.write(b"    </triangles>\n   </mesh>\n  </object>\n")
        out.write(b" </resources>\n</model>\n")
        out.flush()


def _profile_object_settings(profile_name: str) -> dict[str, str]:
    profile = _PROCESS_PROFILES[str(profile_name).strip()]
    settings = {
        "wall_loops": str(profile["wall_loops"]),
        "wall_generator": str(profile["wall_generator"]),
        "detect_thin_wall": str(profile["detect_thin_wall"]),
        "only_one_wall_top": str(profile["only_one_wall_top"]),
        "interface_shells": "0",
        "sparse_infill_density": (
            f"{radial_process_profile_sparse_infill_percent(profile_name)}%"
        ),
    }
    for key in (
        "wall_distribution_count",
        "min_bead_width",
        "initial_layer_min_bead_width",
        "min_feature_size",
        "wall_transition_length",
        "wall_transition_filter_deviation",
        "wall_transition_angle",
    ):
        if key in profile:
            settings[key] = str(profile[key])
    return settings


def _model_settings(
    title: str,
    parts: tuple[_CheckedPart, ...],
    package: RadialExportPackage,
) -> bytes:
    parent_id = len(parts) + 1
    object_settings = _profile_object_settings(str(package.process_profile))
    outer = next(
        (
            item.part.extruder
            for item in parts
            if item.part.role == "partner_outer_shell"
        ),
        parts[0].part.extruder,
    )
    blocks: list[str] = []
    for part_id, item in enumerate(parts, start=1):
        part = item.part
        blocks.append(
            f'''    <part id="{part_id}" subtype="normal_part">
      <metadata key="name" value="{html.escape(part.name)}"/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_file" value="radial_shell.obj"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="{part_id - 1}"/>
      <metadata key="source_offset_x" value="0"/>
      <metadata key="source_offset_y" value="0"/>
      <metadata key="source_offset_z" value="0"/>
      <metadata key="extruder" value="{part.extruder}"/>
      <mesh_stat face_count="{len(item.faces)}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>'''
        )
    object_setting_xml = "\n".join(
        f'    <metadata key="{html.escape(key)}" value="{html.escape(value)}"/>'
        for key, value in object_settings.items()
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="{parent_id}">
    <metadata key="name" value="{html.escape(title)}"/>
    <metadata key="extruder" value="{outer}"/>
{object_setting_xml}
    <metadata face_count="{sum(len(item.faces) for item in parts)}"/>
{chr(10).join(blocks)}
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value="SLICE ONLY - experimental physical radial shell"/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <model_instance>
      <metadata key="object_id" value="{parent_id}"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="1"/>
    </model_instance>
  </plate>
</config>
'''.encode("utf-8")


def _project_settings_values(
    profile_name: str,
    physical_hex: Sequence[str],
) -> dict[str, object]:
    profile = _PROCESS_PROFILES[str(profile_name).strip()]
    physical = [_normalise_hex(value) for value in physical_hex]
    bright = max(
        range(4),
        key=lambda index: sum(
            int(physical[index][offset : offset + 2], 16)
            for offset in (1, 3, 5)
        ),
    ) + 1
    return {
        "print_settings_id": str(profile["print_settings_id"]),
        "printer_settings_id": "Snapmaker U1 (0.4 nozzle)",
        "printer_model": "Snapmaker U1",
        "printer_variant": "0.4",
        "nozzle_diameter": ["0.4"] * 4,
        "layer_height": f"{float(profile['layer_height_mm']):g}",
        "initial_layer_print_height": (
            f"{float(profile['initial_layer_height_mm']):g}"
        ),
        "adaptive_layer_height": "0",
        "filament_colour": physical,
        "filament_multi_colors": physical,
        "filament_colour_mode": ["0"] * 4,
        "filament_settings_id": ["Generic PLA"] * 4,
        "mixed_filament_definitions": "",
        "mmu_segmented_region_max_width": "0",
        "mmu_segmented_region_interlocking_depth": "0",
        "interlocking_beam": "0",
        "interface_shells": "0",
        **_profile_object_settings(str(profile_name)),
        "line_width": str(profile["line_width"]),
        "outer_wall_line_width": str(profile["outer_wall_line_width"]),
        "inner_wall_line_width": str(profile["inner_wall_line_width"]),
        "top_shell_layers": str(profile["top_shell_layers"]),
        "top_shell_thickness": str(profile["top_shell_thickness"]),
        "bottom_shell_layers": str(profile["bottom_shell_layers"]),
        "bottom_shell_thickness": str(profile["bottom_shell_thickness"]),
        "enable_support": "0",
        "support_filament": str(bright),
        "support_interface_filament": str(bright),
        "flush_into_infill": "0",
        "flush_into_support": "0",
        "flush_into_objects": "0",
        "flush_multiplier": "0",
        "flush_volumes_matrix": ["0"] * 16,
        "flush_volumes_vector": ["0"] * 4,
        # The shell and core use different physical tools on the same layer.
        # Keep a real prime tower even for the initial SLICE ONLY archive so
        # Orca's preview exercises the same per-layer tool-change path that a
        # later explicitly promoted print would use.  Purging into the model,
        # support, or other objects remains forbidden below.
        **_COMMON_TRANSITION_SETTINGS,
        "brim_type": "no_brim",
        "raft_layers": "0",
        "print_sequence": "by layer",
        "xy_contour_compensation": "0",
        "xy_hole_compensation": "0",
    }


def _project_settings(package: RadialExportPackage) -> bytes:
    config = _project_settings_values(
        str(package.process_profile),
        package.physical_hex,
    )
    return json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")


def _experimental_metadata(
    package: RadialExportPackage,
    parts: tuple[_CheckedPart, ...],
) -> bytes:
    color_depth = str(package.renderer).strip().lower() == "color_depth"
    sparse_infill_percent = radial_process_profile_sparse_infill_percent(
        str(package.process_profile)
    )
    payload = {
        "schema": (
            COLOR_DEPTH_EXPORT_SCHEMA if color_depth else RADIAL_SCHEMA
        ),
        "renderer": "ColorDepth Lab" if color_depth else "Radial Lab",
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "physical_materials_only": True,
        "single_print_object": True,
        "normal_part_count": len(parts),
        "process_profile": str(package.process_profile),
        "layer_height_mm": float(package.layer_height_mm),
        "initial_layer_height_mm": float(package.initial_layer_height_mm),
        "black_extruder": (
            None if color_depth else int(package.black_extruder)
        ),
        "physical_hex": [_normalise_hex(value) for value in package.physical_hex],
        "safety": {
            "support_enabled": False,
            "flush_to_model_enabled": False,
            "prime_tower_enabled": True,
            "prime_tower_reason": "physical core/skin tool changes on each layer",
            "sparse_infill_density_percent": sparse_infill_percent,
            "closed_physical_volumes": True,
            "requires_orca_preview": True,
            "requires_explicit_print_ready_promotion": True,
        },
        "parts": [
            {
                "index": index,
                "name": item.part.name,
                "role": item.part.role,
                "extruder": item.part.extruder,
                "closed_physical_volume": bool(item.part.solid_infill),
                "source_state": item.part.source_state,
                "vertices": len(item.vertices),
                "faces": len(item.faces),
                "signed_volume_mm3": item.signed_volume_mm3,
                "metadata": _json_safe(item.part.metadata),
            }
            for index, item in enumerate(parts)
        ],
        "generator_metadata": _json_safe(package.metadata),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def write_radial_3mf_atomic(
    destination: Path,
    package: RadialExportPackage,
    *,
    title: str | None = None,
) -> RadialExportValidation:
    """Write and re-open a slice-only physical radial-shell 3MF atomically."""

    checked = _check_package(package)
    destination = Path(destination).with_suffix(".3mf")
    destination.parent.mkdir(parents=True, exist_ok=True)
    safe_title = str(title or destination.stem).strip() or "radial_shell"
    color_depth = str(package.renderer).strip().lower() == "color_depth"
    archive_title = f"SLICE ONLY - {safe_title}"
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            archive.writestr("[Content_Types].xml", _content_types())
            archive.writestr("_rels/.rels", _root_relationships())
            archive.writestr(
                "3D/3dmodel.model",
                _root_model(
                    archive_title,
                    (
                        "Experimental ColorDepth physical unions; preview required"
                        if color_depth
                        else "Experimental physical radial shell; preview required"
                    ),
                    len(checked),
                ),
            )
            archive.writestr(
                "3D/_rels/3dmodel.model.rels", _model_relationships()
            )
            _write_parts_model(archive, checked)
            archive.writestr(
                "Metadata/model_settings.config",
                _model_settings(archive_title, checked, package),
            )
            archive.writestr(
                "Metadata/project_settings.config", _project_settings(package)
            )
            archive.writestr(
                "Metadata/radial_shell_experimental.json",
                _experimental_metadata(package, checked),
            )
        validation = validate_radial_3mf(
            temporary,
            expected_parts=len(checked),
            expected_physical=package.physical_hex,
            expected_extruders=tuple(item.part.extruder for item in checked),
            expected_process_profile=str(package.process_profile),
        )
        os.replace(temporary, destination)
        return replace(
            validation,
            path=destination,
            sha256=_sha256(destination),
            bytes=destination.stat().st_size,
        )
    finally:
        if temporary.exists():
            temporary.unlink()


def _metadata_values(element: ET.Element) -> dict[str, str]:
    return {
        str(item.attrib.get("key")): str(item.attrib.get("value", ""))
        for item in element.findall("metadata")
        if "key" in item.attrib
    }


def _strict_metadata_values(
    element: ET.Element,
    expected_keys: set[str],
    *,
    context: str,
    allow_unkeyed: bool = False,
) -> dict[str, str]:
    all_items = element.findall("metadata")
    unkeyed = [item for item in all_items if "key" not in item.attrib]
    if unkeyed and not allow_unkeyed:
        raise RadialExportError(f"{context} contains unkeyed metadata")
    items = [item for item in all_items if "key" in item.attrib]
    keys = [str(item.attrib.get("key", "")) for item in items]
    if len(keys) != len(set(keys)):
        raise RadialExportError(f"{context} repeats a metadata override")
    if set(keys) != set(expected_keys):
        unexpected = sorted(set(keys) - set(expected_keys))
        missing = sorted(set(expected_keys) - set(keys))
        raise RadialExportError(
            f"{context} metadata allowlist drifted "
            f"(unexpected={unexpected}, missing={missing})"
        )
    return {
        str(item.attrib["key"]): str(item.attrib.get("value", ""))
        for item in items
    }


def _all_zero(value: object) -> bool:
    if isinstance(value, list):
        return all(str(item) in {"0", "0.0"} for item in value)
    return str(value) in {"0", "0.0"}


def validate_radial_3mf(
    path: Path,
    *,
    expected_parts: int | None = None,
    expected_physical: Sequence[str] | None = None,
    expected_extruders: Sequence[int] | None = None,
    expected_process_profile: str | None = None,
) -> RadialExportValidation:
    """Fail closed if an archive is not a physical, slice-only radial 3MF."""

    path = Path(path)
    if not path.is_file():
        raise RadialExportError(f"Radial 3MF does not exist: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise RadialExportError("The radial 3MF has a ZIP CRC failure")
        member_names = archive.namelist()
        if len(member_names) != len(set(member_names)):
            raise RadialExportError("The radial 3MF contains duplicate ZIP members")
        names = set(member_names)
        missing = sorted(_REQUIRED_ARCHIVE_MEMBERS - names)
        if missing:
            raise RadialExportError(
                f"The radial 3MF is missing archive members: {missing}"
            )
        unexpected = sorted(names - _REQUIRED_ARCHIVE_MEMBERS)
        if unexpected:
            raise RadialExportError(
                f"The radial 3MF contains unvalidated archive members: {unexpected}"
            )
        exact_static_members = {
            "[Content_Types].xml": _content_types(),
            "_rels/.rels": _root_relationships(),
            "3D/_rels/3dmodel.model.rels": _model_relationships(),
        }
        for name, expected in exact_static_members.items():
            if archive.read(name) != expected:
                raise RadialExportError(f"Radial archive relationship drifted: {name}")
        root = ET.fromstring(archive.read("3D/3dmodel.model"))
        parts_root = ET.fromstring(
            archive.read("3D/Objects/radial_parts.model")
        )
        settings_root = ET.fromstring(
            archive.read("Metadata/model_settings.config")
        )
        project = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
        metadata = json.loads(
            archive.read("Metadata/radial_shell_experimental.json").decode(
                "utf-8"
            )
        )

        if root.attrib.get("unit") != "millimeter":
            raise RadialExportError("The radial root model unit drifted")
        if parts_root.attrib.get("unit") != "millimeter":
            raise RadialExportError("The radial child model unit drifted")
        expected_model_attributes = {
            "unit": "millimeter",
            "{http://www.w3.org/XML/1998/namespace}lang": "en-US",
            "requiredextensions": "p",
        }
        if root.tag != f"{{{_CORE_NS}}}model":
            raise RadialExportError("The radial root element is not a 3MF model")
        if parts_root.tag != f"{{{_CORE_NS}}}model":
            raise RadialExportError("The radial child element is not a 3MF model")
        if root.attrib != expected_model_attributes:
            raise RadialExportError("The radial root model contract drifted")
        if parts_root.attrib != expected_model_attributes:
            raise RadialExportError("The radial child model contract drifted")
        production_uuid_key = f"{{{_PRODUCTION_NS}}}UUID"
        production_uuids: list[str] = []
        for model_root in (root, parts_root):
            for element in model_root.iter():
                if production_uuid_key not in element.attrib:
                    continue
                value = element.attrib[production_uuid_key]
                try:
                    parsed = uuid.UUID(value)
                except (AttributeError, TypeError, ValueError) as exc:
                    raise RadialExportError(
                        "A radial Production UUID is malformed"
                    ) from exc
                if str(parsed) != value:
                    raise RadialExportError(
                        "A radial Production UUID is not canonical lowercase text"
                    )
                production_uuids.append(value)
        if not production_uuids or len(production_uuids) != len(set(production_uuids)):
            raise RadialExportError(
                "Radial Production UUIDs are missing or duplicated"
            )

        root_metadata = root.findall(f"{{{_CORE_NS}}}metadata")
        child_metadata = parts_root.findall(f"{{{_CORE_NS}}}metadata")
        if (
            len(root_metadata) != 6
            or any(set(item.attrib) != {"name"} for item in root_metadata)
            or len(child_metadata) != 1
            or child_metadata[0].attrib != {"name": "BambuStudio:3mfVersion"}
            or (child_metadata[0].text or "") != "1"
        ):
            raise RadialExportError("Radial model metadata structure drifted")

        items = root.findall(f"{{{_CORE_NS}}}build/{{{_CORE_NS}}}item")
        if len(items) != 1 or items[0].attrib.get("printable") != "1":
            raise RadialExportError(
                "The radial archive must have one sliceable build item"
            )
        expected_item_keys = {
            "objectid",
            f"{{{_PRODUCTION_NS}}}UUID",
            "transform",
            "printable",
        }
        if set(items[0].attrib) != expected_item_keys:
            raise RadialExportError("The radial build-item attributes drifted")
        if items[0].attrib.get("transform") != (
            "1 0 0 0 1 0 0 0 1 128 128 0"
        ):
            raise RadialExportError("The radial build transform drifted")
        parent_objects = root.findall(
            f"{{{_CORE_NS}}}resources/{{{_CORE_NS}}}object"
        )
        if len(parent_objects) != 1:
            raise RadialExportError("The radial archive must have one root object")
        if set(parent_objects[0].attrib) != {
            "id",
            f"{{{_PRODUCTION_NS}}}UUID",
            "type",
        }:
            raise RadialExportError("The radial root-object attributes drifted")
        if parent_objects[0].attrib.get("type") != "model":
            raise RadialExportError("The radial root object is not a model")
        component_containers = parent_objects[0].findall(
            f"{{{_CORE_NS}}}components"
        )
        if (
            len(component_containers) != 1
            or list(parent_objects[0]) != component_containers
            or component_containers[0].attrib
        ):
            raise RadialExportError("Radial root component structure drifted")
        components = component_containers[0].findall(
            f"{{{_CORE_NS}}}component"
        )
        if list(component_containers[0]) != components:
            raise RadialExportError(
                "Radial component container has an unknown element"
            )
        objects = parts_root.findall(
            f"{{{_CORE_NS}}}resources/{{{_CORE_NS}}}object"
        )
        parent_resources = root.findall(f"{{{_CORE_NS}}}resources")
        child_resources = parts_root.findall(f"{{{_CORE_NS}}}resources")
        builds = root.findall(f"{{{_CORE_NS}}}build")
        if (
            len(parent_resources) != 1
            or parent_resources[0].attrib
            or list(parent_resources[0]) != parent_objects
            or len(child_resources) != 1
            or child_resources[0].attrib
            or list(child_resources[0]) != objects
            or len(builds) != 1
            or set(builds[0].attrib) != {production_uuid_key}
            or list(builds[0]) != items
            or list(root) != root_metadata + [parent_resources[0], builds[0]]
            or list(parts_root) != child_metadata + [child_resources[0]]
        ):
            raise RadialExportError("Radial resource structure drifted")
        part_count = len(objects)
        if not part_count or len(components) != part_count:
            raise RadialExportError("Root component and physical part counts differ")
        parent_id = part_count + 1
        if int(parent_objects[0].attrib.get("id", "0")) != parent_id:
            raise RadialExportError("The radial root object ID drifted")
        if int(items[0].attrib.get("objectid", "0")) != parent_id:
            raise RadialExportError("The radial build item targets the wrong object")
        for expected_id, component in enumerate(components, start=1):
            if set(component.attrib) != {
                f"{{{_PRODUCTION_NS}}}path",
                "objectid",
                f"{{{_PRODUCTION_NS}}}UUID",
                "transform",
            }:
                raise RadialExportError("A radial component attribute drifted")
            if int(component.attrib.get("objectid", "0")) != expected_id:
                raise RadialExportError(
                    "Radial component order no longer matches clipping priority"
                )
            if component.attrib.get(f"{{{_PRODUCTION_NS}}}path") != (
                "/3D/Objects/radial_parts.model"
            ):
                raise RadialExportError("A radial component targets another model")
            if component.attrib.get("transform") != (
                "1 0 0 0 1 0 0 0 1 0 0 0"
            ):
                raise RadialExportError("A radial component transform drifted")
        if expected_parts is not None and part_count != int(expected_parts):
            raise RadialExportError(
                f"Expected {expected_parts} radial parts, found {part_count}"
            )
        if [int(obj.attrib["id"]) for obj in objects] != list(
            range(1, part_count + 1)
        ):
            raise RadialExportError("Physical object IDs are not contiguous")
        for obj in objects:
            if set(obj.attrib) != {
                "id",
                f"{{{_PRODUCTION_NS}}}UUID",
                "name",
                "type",
            }:
                raise RadialExportError("A radial physical object attribute drifted")
            if obj.attrib.get("type") != "model":
                raise RadialExportError("A radial physical object is not a model")

        total_vertices = 0
        total_faces = 0
        parsed_meshes: list[tuple[np.ndarray, np.ndarray]] = []
        for obj in objects:
            meshes = obj.findall(f"{{{_CORE_NS}}}mesh")
            if len(meshes) != 1 or list(obj) != meshes or meshes[0].attrib:
                raise RadialExportError(
                    "A radial physical object must contain exactly one mesh"
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
                raise RadialExportError("A radial mesh structure drifted")
            vertices = vertex_containers[0].findall(f"{{{_CORE_NS}}}vertex")
            triangles = triangle_containers[0].findall(f"{{{_CORE_NS}}}triangle")
            if (
                list(vertex_containers[0]) != vertices
                or list(triangle_containers[0]) != triangles
            ):
                raise RadialExportError(
                    "A radial mesh container has an unknown element"
                )
            if not vertices or not triangles:
                raise RadialExportError("A radial physical object is empty")
            if any(set(vertex.attrib) != {"x", "y", "z"} for vertex in vertices):
                raise RadialExportError("A radial vertex attribute drifted")
            try:
                vertex_array = np.asarray(
                    [
                        [float(vertex.attrib[axis]) for axis in ("x", "y", "z")]
                        for vertex in vertices
                    ],
                    dtype=np.float64,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RadialExportError(
                    "A radial physical object has invalid coordinates"
                ) from exc
            if not np.isfinite(vertex_array).all():
                raise RadialExportError(
                    "A radial physical object contains NaN/Inf coordinates"
                )
            face_rows: list[list[int]] = []
            for triangle in triangles:
                if set(triangle.attrib) != {"v1", "v2", "v3"}:
                    raise RadialExportError(
                        "Triangle paint or an unknown face property is forbidden "
                        "in physical radial output"
                    )
                try:
                    indices = [
                        int(triangle.attrib[key]) for key in ("v1", "v2", "v3")
                    ]
                except (KeyError, TypeError, ValueError) as exc:
                    raise RadialExportError(
                        "A radial triangle index is malformed"
                    ) from exc
                if min(indices) < 0 or max(indices) >= len(vertices):
                    raise RadialExportError("A radial triangle index is invalid")
                face_rows.append(indices)
            face_array = np.asarray(face_rows, dtype=np.int32)
            parsed_meshes.append((vertex_array, face_array))
            total_vertices += len(vertices)
            total_faces += len(triangles)

        config_objects = settings_root.findall("object")
        if len(config_objects) != 1:
            raise RadialExportError("Model settings must describe one PrintObject")
        if int(config_objects[0].attrib.get("id", "0")) != parent_id:
            raise RadialExportError("Model settings target the wrong PrintObject")
        config_parts = config_objects[0].findall("part")
        if len(config_parts) != part_count:
            raise RadialExportError("Model settings normal-part count is wrong")
        if [int(part.attrib.get("id", "0")) for part in config_parts] != list(
            range(1, part_count + 1)
        ):
            raise RadialExportError(
                "Model-settings part order no longer matches clipping priority"
            )
        extruders: list[int] = []
        part_config_values: list[dict[str, str]] = []
        part_metadata_keys = {
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
        for part_index, part in enumerate(config_parts):
            if part.attrib.get("subtype") != "normal_part":
                raise RadialExportError("Every radial volume must be normal_part")
            if set(part.attrib) != {"id", "subtype"}:
                raise RadialExportError("A radial normal-part attribute drifted")
            values = _strict_metadata_values(
                part,
                part_metadata_keys,
                context=f"Radial normal part {part_index + 1}",
            )
            expected_static = {
                "matrix": "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1",
                "source_file": "radial_shell.obj",
                "source_object_id": "0",
                "source_volume_id": str(part_index),
                "source_offset_x": "0",
                "source_offset_y": "0",
                "source_offset_z": "0",
            }
            for key, expected in expected_static.items():
                if values.get(key) != expected:
                    raise RadialExportError(
                        f"Unsafe radial normal-part setting {key}: "
                        f"{values.get(key)!r}"
                    )
            extruder = int(values.get("extruder", "0"))
            if not 1 <= extruder <= 4:
                raise RadialExportError("A radial part references a nonphysical tool")
            extruders.append(extruder)
            part_config_values.append(values)
            mesh_stats = part.findall("mesh_stat")
            if len(mesh_stats) != 1 or set(mesh_stats[0].attrib) != {
                "face_count",
                "edges_fixed",
                "degenerate_facets",
                "facets_removed",
                "facets_reversed",
                "backwards_edges",
            }:
                raise RadialExportError("A radial mesh_stat record drifted")
            expected_mesh_stat = {
                "face_count": str(len(parsed_meshes[part_index][1])),
                "edges_fixed": "0",
                "degenerate_facets": "0",
                "facets_removed": "0",
                "facets_reversed": "0",
                "backwards_edges": "0",
            }
            if mesh_stats[0].attrib != expected_mesh_stat:
                raise RadialExportError("A radial mesh_stat value drifted")
        if expected_extruders is not None and tuple(extruders) != tuple(
            int(value) for value in expected_extruders
        ):
            raise RadialExportError("Normal-part extruder assignments drifted")
        plates = settings_root.findall("plate")
        if len(plates) != 1:
            raise RadialExportError("Model settings must describe one plate")
        plate_values = _strict_metadata_values(
            plates[0],
            {"plater_id", "plater_name", "locked", "filament_map_mode"},
            context="Radial plate",
        )
        expected_plate_values = {
            "plater_id": "1",
            "plater_name": "SLICE ONLY - experimental physical radial shell",
            "locked": "false",
            "filament_map_mode": "Auto For Flush",
        }
        if plate_values != expected_plate_values:
            raise RadialExportError("Radial plate settings drifted")
        instances = plates[0].findall("model_instance")
        if len(instances) != 1:
            raise RadialExportError("Radial plate instance count drifted")
        instance_values = _strict_metadata_values(
            instances[0],
            {"object_id", "instance_id", "identify_id"},
            context="Radial model instance",
        )
        if instance_values != {
            "object_id": str(parent_id),
            "instance_id": "0",
            "identify_id": "1",
        }:
            raise RadialExportError("Radial plate instance metadata drifted")
        direct_tags = [child.tag for child in settings_root]
        if direct_tags != ["object", "plate"]:
            raise RadialExportError("Model-settings root structure drifted")

        process_profile = str(
            metadata.get("process_profile", RADIAL_PROCESS_PROFILE_MVP_020)
        )
        if (
            expected_process_profile is not None
            and process_profile != str(expected_process_profile)
        ):
            raise RadialExportError(
                "The radial archive process profile differs from the requested one"
            )
        profile = _PROCESS_PROFILES.get(process_profile)
        if profile is None:
            raise RadialExportError("The radial process profile is unsupported")
        _validate_process_profile_metadata(
            metadata.get("generator_metadata"),
            process_profile,
        )
        if not isinstance(project, Mapping):
            raise RadialExportError("The radial project settings are malformed")
        try:
            physical = tuple(
                _normalise_hex(value)
                for value in project.get("filament_colour", [])
            )
        except (TypeError, RadialExportError) as exc:
            raise RadialExportError(
                "The archive physical filament colours are malformed"
            ) from exc
        if len(physical) != 4:
            raise RadialExportError("The archive does not contain four physical tools")
        if expected_physical is not None and physical != tuple(
            _normalise_hex(value) for value in expected_physical
        ):
            raise RadialExportError("Physical filament colours drifted")
        expected_project = _project_settings_values(process_profile, physical)
        if set(project) != set(expected_project):
            raise RadialExportError(
                "Radial project-setting allowlist drifted "
                f"(unexpected={sorted(set(project) - set(expected_project))}, "
                f"missing={sorted(set(expected_project) - set(project))})"
            )
        for key, expected in expected_project.items():
            if project.get(key) != expected:
                raise RadialExportError(
                    f"Unsafe radial project setting {key}: "
                    f"{project.get(key)!r} != {expected!r}"
                )
        expected_object_settings = _profile_object_settings(process_profile)
        object_values = _strict_metadata_values(
            config_objects[0],
            {"name", "extruder", *expected_object_settings},
            context="Radial PrintObject",
            allow_unkeyed=True,
        )
        object_stats = [
            item
            for item in config_objects[0].findall("metadata")
            if "key" not in item.attrib
        ]
        if len(object_stats) != 1 or object_stats[0].attrib != {
            "face_count": str(total_faces)
        }:
            raise RadialExportError("Radial PrintObject face metadata drifted")
        for key, expected in expected_object_settings.items():
            if object_values.get(key) != expected:
                raise RadialExportError(
                    f"Unsafe radial object override {key}: "
                    f"{object_values.get(key)!r}"
                )
        schema = metadata.get("schema")
        if schema not in {RADIAL_SCHEMA, COLOR_DEPTH_EXPORT_SCHEMA}:
            raise RadialExportError("The radial experimental schema is missing")
        color_depth = schema == COLOR_DEPTH_EXPORT_SCHEMA
        expected_renderer = "ColorDepth Lab" if color_depth else "Radial Lab"
        if metadata.get("renderer") != expected_renderer:
            raise RadialExportError("The physical renderer metadata drifted")
        if metadata.get("experimental") is not True:
            raise RadialExportError("The radial experimental gate is missing")
        if metadata.get("slice_only") is not True:
            raise RadialExportError("The radial archive is not marked slice-only")
        if metadata.get("print_allowed") is not False:
            raise RadialExportError("The radial archive is incorrectly print-enabled")
        if metadata.get("physical_materials_only") is not True:
            raise RadialExportError("The radial archive is not physical-only")
        metadata_layer_height = float(
            metadata.get("layer_height_mm", float("nan"))
        )
        if not math.isfinite(metadata_layer_height) or abs(
            metadata_layer_height - float(profile["layer_height_mm"])
        ) > 1e-9:
            raise RadialExportError("Radial layer metadata and process profile differ")
        metadata_initial_height = float(
            metadata.get("initial_layer_height_mm", float("nan"))
        )
        if not math.isfinite(metadata_initial_height) or abs(
            metadata_initial_height
            - float(profile["initial_layer_height_mm"])
        ) > 1e-9:
            raise RadialExportError(
                "Radial initial-layer metadata and process profile differ"
            )
        safety = metadata.get("safety")
        if not isinstance(safety, Mapping):
            raise RadialExportError("The radial safety metadata is missing")
        if safety.get("prime_tower_enabled") is not True:
            raise RadialExportError("The radial prime-tower safety gate is missing")
        if safety.get("support_enabled") is not False:
            raise RadialExportError("The radial support safety gate drifted")
        if safety.get("flush_to_model_enabled") is not False:
            raise RadialExportError("The radial flush safety gate drifted")
        expected_sparse_infill = radial_process_profile_sparse_infill_percent(
            process_profile
        )
        if int(safety.get("sparse_infill_density_percent", -1)) != (
            expected_sparse_infill
        ):
            raise RadialExportError(
                "The radial sparse-infill safety metadata drifted"
            )
        if safety.get("closed_physical_volumes") is not True:
            raise RadialExportError(
                "The radial closed-volume safety gate is missing"
            )
        if int(metadata.get("normal_part_count", -1)) != part_count:
            raise RadialExportError("Experimental part metadata drifted")
        meta_parts = metadata.get("parts")
        if not isinstance(meta_parts, list) or len(meta_parts) != part_count:
            raise RadialExportError("Experimental per-part metadata drifted")
        if not all(isinstance(item, Mapping) for item in meta_parts):
            raise RadialExportError("Experimental per-part metadata is malformed")
        if [int(item.get("index", -1)) for item in meta_parts] != list(
            range(part_count)
        ):
            raise RadialExportError(
                "Experimental metadata order no longer matches clipping priority"
            )
        if [int(item.get("extruder", 0)) for item in meta_parts] != extruders:
            raise RadialExportError("Material metadata and normal parts disagree")
        if [str(item.get("name", "")) for item in meta_parts] != [
            values["name"] for values in part_config_values
        ]:
            raise RadialExportError("Part names and model settings disagree")
        for index, ((vertices, faces), item, extruder) in enumerate(
            zip(parsed_meshes, meta_parts, extruders, strict=True)
        ):
            checked = _check_part(
                RadialExportPart(
                    name=str(item.get("name", f"archive part {index + 1}")),
                    role=str(item.get("role", "")),
                    vertices_mm=vertices,
                    faces=faces,
                    extruder=extruder,
                    solid_infill=(
                        item.get("closed_physical_volume") is True
                    ),
                    source_state=item.get("source_state"),
                    metadata=(
                        item.get("metadata", {})
                        if isinstance(item.get("metadata", {}), Mapping)
                        else {}
                    ),
                ),
                index,
            )
            if int(item.get("vertices", -1)) != len(vertices):
                raise RadialExportError("Archive vertex count and metadata differ")
            if int(item.get("faces", -1)) != len(faces):
                raise RadialExportError("Archive face count and metadata differ")
            recorded_volume = float(item.get("signed_volume_mm3", float("nan")))
            if not math.isfinite(recorded_volume) or not math.isclose(
                recorded_volume,
                checked.signed_volume_mm3,
                rel_tol=1.0e-9,
                abs_tol=1.0e-8,
            ):
                raise RadialExportError("Archive volume and metadata differ")
            if profile.get("coupon_method") is not None:
                # Coupon meshes are intentionally tiny.  Re-run the expensive
                # self-intersection check on the serialized bytes instead of
                # trusting the pre-write NumPy arrays.
                from . import engine as _engine

                quality = _engine.mesh_quality(
                    vertices,
                    faces,
                    check_self_intersections=True,
                )
                if int(quality.get("self_intersecting_faces", -1)) != 0:
                    raise RadialExportError(
                        "A serialized coupon volume self-intersects"
                    )
        if color_depth:
            if any(
                item.get("role") != "color_depth_physical_union"
                for item in meta_parts
            ):
                raise RadialExportError(
                    "A ColorDepth archive contains a legacy radial role"
                )
            if len(meta_parts) > 4 or len(set(extruders)) != len(extruders):
                raise RadialExportError(
                    "ColorDepth must contain at most one union per physical tool"
                )
            generator = metadata.get("generator_metadata")
            if not isinstance(generator, Mapping):
                raise RadialExportError("ColorDepth generator metadata is missing")
            if generator.get("physical_materials_only") is not True:
                raise RadialExportError("ColorDepth is not physical-material-only")
            if generator.get("legacy_fullspectrum_ratios_used") is not False:
                raise RadialExportError("ColorDepth unexpectedly uses legacy ratios")
            if float(generator.get("positive_overlap_mm3", float("inf"))) != 0.0:
                raise RadialExportError("ColorDepth material regions overlap")
            if float(generator.get("gap_mm", float("inf"))) != 0.0:
                raise RadialExportError("ColorDepth material regions contain a gap")
            if generator.get("shared_interface_partition_exact") is not True:
                raise RadialExportError(
                    "ColorDepth shared interface proof is missing"
                )
            if generator.get("external_surface_coverage_exact") is not True:
                raise RadialExportError(
                    "ColorDepth source-exterior coverage proof is missing"
                )
            if generator.get("unsafe_columns_outer_only_verified") is not True:
                raise RadialExportError(
                    "ColorDepth unsafe-column fallback proof is missing"
                )
        else:
            black_extruder = int(metadata.get("black_extruder", 0))
            black_indices = [
                index
                for index, item in enumerate(meta_parts)
                if item.get("role") == "pure_black_core"
            ]
            outer_indices = [
                index
                for index, item in enumerate(meta_parts)
                if item.get("role") == "partner_outer_shell"
            ]
            if not black_indices:
                raise RadialExportError("The archive has no declared pure-black core")
            if not outer_indices:
                raise RadialExportError("The archive has no declared partner shell")
            if any(extruders[index] != black_extruder for index in black_indices):
                raise RadialExportError("A pure-black core uses the wrong physical tool")
            if any(extruders[index] == black_extruder for index in outer_indices):
                raise RadialExportError("A partner shell incorrectly uses physical black")
            if max(black_indices) >= min(outer_indices):
                raise RadialExportError("Radial clipping priority no longer favours the shell")
        if not all(
            item.get("closed_physical_volume") is True for item in meta_parts
        ):
            raise RadialExportError(
                "A radial region is not declared as a closed physical volume"
            )

    return RadialExportValidation(
        path=path,
        sha256=_sha256(path),
        bytes=path.stat().st_size,
        parts=part_count,
        vertices=total_vertices,
        faces=total_faces,
        physical_extruders=tuple(extruders),
        zip_crc_ok=True,
        slice_only=True,
        print_allowed=False,
        physical_materials_only=True,
        static_validation_ok=True,
    )


__all__ = [
    "COLOR_DEPTH_EXPORT_SCHEMA",
    "RADIAL_SCHEMA",
    "RADIAL_PROCESS_PROFILE_BLACK_COUPON_ARACHNE_010",
    "RADIAL_PROCESS_PROFILE_BLACK_COUPON_010",
    "RADIAL_PROCESS_PROFILE_COMPACT_BLACK_COUPON_ARACHNE_010",
    "RADIAL_PROCESS_PROFILE_COMPACT_BLACK_COUPON_010",
    "RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010",
    "RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010",
    "RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_ARACHNE_010",
    "RADIAL_PROCESS_PROFILE_LARGE_FRUSTUM_BLACK_COUPON_010",
    "RADIAL_PROCESS_PROFILE_MVP_020",
    "RadialExportError",
    "RadialExportPackage",
    "RadialExportPart",
    "RadialExportValidation",
    "package_from_radial_shell",
    "radial_process_profile_sparse_infill_percent",
    "package_from_color_depth",
    "validate_radial_3mf",
    "write_radial_3mf_atomic",
]
