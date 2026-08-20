"""Strict experimental 3MF writer for physical radial-shell volumes.

This module deliberately does not reuse :func:`engine.write_3mf_atomic`.
That writer represents colour with triangle paint states and currently assigns
extruder 1 to every normal part.  A radial shell is different: geometry owns
the material, every part must select one of the four physical U1 tools, and a
pure-black core must be solid.  Keeping this boundary separate also makes the
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
            f"Radial part {name!r} is not solid; the experimental writer "
            "requires every physical region to use 100% infill"
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
    if abs(float(package.layer_height_mm) - 0.20) > 1e-9:
        raise RadialExportError(
            "The first radial export format is calibrated only for 0.20 mm layers"
        )
    if abs(float(package.initial_layer_height_mm) - 0.20) > 1e-9:
        raise RadialExportError(
            "The first radial export format requires a 0.20 mm initial layer"
        )
    _json_safe(package.metadata)
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
                out.write(
                    f'     <vertex x="{x:.12g}" y="{y:.12g}" z="{z:.12g}"/>\n'.encode(
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


def _model_settings(
    title: str,
    parts: tuple[_CheckedPart, ...],
) -> bytes:
    parent_id = len(parts) + 1
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
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="{parent_id}">
    <metadata key="name" value="{html.escape(title)}"/>
    <metadata key="extruder" value="{outer}"/>
    <metadata key="wall_loops" value="1"/>
    <metadata key="wall_generator" value="classic"/>
    <metadata key="detect_thin_wall" value="1"/>
    <metadata key="interface_shells" value="0"/>
    <metadata key="sparse_infill_density" value="100%"/>
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


def _project_settings(package: RadialExportPackage) -> bytes:
    physical = [_normalise_hex(value) for value in package.physical_hex]
    bright = max(
        range(4),
        key=lambda index: sum(
            int(physical[index][offset : offset + 2], 16)
            for offset in (1, 3, 5)
        ),
    ) + 1
    config: dict[str, object] = {
        "print_settings_id": "0.20 Standard @Snapmaker U1 (0.4 nozzle)",
        "printer_settings_id": "Snapmaker U1 (0.4 nozzle)",
        "printer_model": "Snapmaker U1",
        "printer_variant": "0.4",
        "nozzle_diameter": ["0.4"] * 4,
        "layer_height": "0.2",
        "initial_layer_print_height": "0.2",
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
        "wall_loops": "1",
        "wall_generator": "classic",
        "detect_thin_wall": "1",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.42",
        "sparse_infill_density": "100%",
        "top_shell_layers": "3",
        "top_shell_thickness": "0.6",
        "bottom_shell_layers": "3",
        "bottom_shell_thickness": "0.6",
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
        "enable_prime_tower": "1",
        "brim_type": "no_brim",
        "raft_layers": "0",
        "print_sequence": "by layer",
        "xy_contour_compensation": "0",
        "xy_hole_compensation": "0",
    }
    return json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")


def _experimental_metadata(
    package: RadialExportPackage,
    parts: tuple[_CheckedPart, ...],
) -> bytes:
    color_depth = str(package.renderer).strip().lower() == "color_depth"
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
            "solid_infill_percent": 100,
            "requires_orca_preview": True,
            "requires_explicit_print_ready_promotion": True,
        },
        "parts": [
            {
                "index": index,
                "name": item.part.name,
                "role": item.part.role,
                "extruder": item.part.extruder,
                "solid_infill": item.part.solid_infill,
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
                _model_settings(archive_title, checked),
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
) -> RadialExportValidation:
    """Fail closed if an archive is not a physical, slice-only radial 3MF."""

    path = Path(path)
    if not path.is_file():
        raise RadialExportError(f"Radial 3MF does not exist: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise RadialExportError("The radial 3MF has a ZIP CRC failure")
        names = set(archive.namelist())
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

        items = root.findall(f"{{{_CORE_NS}}}build/{{{_CORE_NS}}}item")
        if len(items) != 1 or items[0].attrib.get("printable") != "1":
            raise RadialExportError(
                "The radial archive must have one sliceable build item"
            )
        parent_objects = root.findall(
            f"{{{_CORE_NS}}}resources/{{{_CORE_NS}}}object"
        )
        if len(parent_objects) != 1:
            raise RadialExportError("The radial archive must have one root object")
        components = parent_objects[0].findall(
            f"{{{_CORE_NS}}}components/{{{_CORE_NS}}}component"
        )
        objects = parts_root.findall(
            f"{{{_CORE_NS}}}resources/{{{_CORE_NS}}}object"
        )
        part_count = len(objects)
        if not part_count or len(components) != part_count:
            raise RadialExportError("Root component and physical part counts differ")
        if expected_parts is not None and part_count != int(expected_parts):
            raise RadialExportError(
                f"Expected {expected_parts} radial parts, found {part_count}"
            )
        if [int(obj.attrib["id"]) for obj in objects] != list(
            range(1, part_count + 1)
        ):
            raise RadialExportError("Physical object IDs are not contiguous")

        total_vertices = 0
        total_faces = 0
        for obj in objects:
            mesh = obj.find(f"{{{_CORE_NS}}}mesh")
            if mesh is None:
                raise RadialExportError("A radial physical object has no mesh")
            vertices = mesh.findall(
                f"{{{_CORE_NS}}}vertices/{{{_CORE_NS}}}vertex"
            )
            triangles = mesh.findall(
                f"{{{_CORE_NS}}}triangles/{{{_CORE_NS}}}triangle"
            )
            if not vertices or not triangles:
                raise RadialExportError("A radial physical object is empty")
            for triangle in triangles:
                if "paint_color" in triangle.attrib:
                    raise RadialExportError(
                        "Triangle paint is forbidden in physical radial output"
                    )
                indices = [
                    int(triangle.attrib[key]) for key in ("v1", "v2", "v3")
                ]
                if min(indices) < 0 or max(indices) >= len(vertices):
                    raise RadialExportError("A radial triangle index is invalid")
            total_vertices += len(vertices)
            total_faces += len(triangles)

        config_objects = settings_root.findall("object")
        if len(config_objects) != 1:
            raise RadialExportError("Model settings must describe one PrintObject")
        config_parts = config_objects[0].findall("part")
        if len(config_parts) != part_count:
            raise RadialExportError("Model settings normal-part count is wrong")
        extruders: list[int] = []
        for part in config_parts:
            if part.attrib.get("subtype") != "normal_part":
                raise RadialExportError("Every radial volume must be normal_part")
            values = _metadata_values(part)
            extruder = int(values.get("extruder", "0"))
            if not 1 <= extruder <= 4:
                raise RadialExportError("A radial part references a nonphysical tool")
            extruders.append(extruder)
        if expected_extruders is not None and tuple(extruders) != tuple(
            int(value) for value in expected_extruders
        ):
            raise RadialExportError("Normal-part extruder assignments drifted")

        required_project = {
            "layer_height": "0.2",
            "initial_layer_print_height": "0.2",
            "adaptive_layer_height": "0",
            "mixed_filament_definitions": "",
            "interface_shells": "0",
            "wall_loops": "1",
            "wall_generator": "classic",
            "detect_thin_wall": "1",
            "sparse_infill_density": "100%",
            "enable_support": "0",
            "enable_prime_tower": "1",
            "flush_into_infill": "0",
            "flush_into_support": "0",
            "flush_into_objects": "0",
            "flush_multiplier": "0",
            "brim_type": "no_brim",
            "raft_layers": "0",
        }
        for key, value in required_project.items():
            if project.get(key) != value:
                raise RadialExportError(
                    f"Unsafe radial project setting {key}: {project.get(key)!r}"
                )
        for key in ("flush_volumes_matrix", "flush_volumes_vector"):
            if not _all_zero(project.get(key)):
                raise RadialExportError(f"Unsafe radial project setting {key}")
        physical = tuple(
            _normalise_hex(value) for value in project.get("filament_colour", [])
        )
        if len(physical) != 4:
            raise RadialExportError("The archive does not contain four physical tools")
        if expected_physical is not None and physical != tuple(
            _normalise_hex(value) for value in expected_physical
        ):
            raise RadialExportError("Physical filament colours drifted")

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
        safety = metadata.get("safety")
        if not isinstance(safety, Mapping):
            raise RadialExportError("The radial safety metadata is missing")
        if safety.get("prime_tower_enabled") is not True:
            raise RadialExportError("The radial prime-tower safety gate is missing")
        if safety.get("support_enabled") is not False:
            raise RadialExportError("The radial support safety gate drifted")
        if safety.get("flush_to_model_enabled") is not False:
            raise RadialExportError("The radial flush safety gate drifted")
        if int(metadata.get("normal_part_count", -1)) != part_count:
            raise RadialExportError("Experimental part metadata drifted")
        meta_parts = metadata.get("parts")
        if not isinstance(meta_parts, list) or len(meta_parts) != part_count:
            raise RadialExportError("Experimental per-part metadata drifted")
        if [int(item.get("extruder", 0)) for item in meta_parts] != extruders:
            raise RadialExportError("Material metadata and normal parts disagree")
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
        if not all(item.get("solid_infill") is True for item in meta_parts):
            raise RadialExportError("A radial region is not declared solid")

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
    "RadialExportError",
    "RadialExportPackage",
    "RadialExportPart",
    "RadialExportValidation",
    "package_from_radial_shell",
    "package_from_color_depth",
    "validate_radial_3mf",
    "write_radial_3mf_atomic",
]
