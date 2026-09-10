from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import tempfile
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence
from xml.etree import ElementTree as ET

import numpy as np

from .engine import PAINT_CODES, make_portable_mixed_definitions
from .mixer import normalize_hex
from .radial_export import (
    RADIAL_PROCESS_PROFILE_MVP_020,
    RadialExportError,
    RadialExportPackage,
    RadialExportPart,
    RadialExportValidation,
    radial_process_profile_sparse_infill_percent,
    validate_radial_3mf,
    write_radial_3mf_atomic,
)


RADIAL_HYBRID_SCHEMA = "tripo-spectrum-mapper.radial-hybrid.experimental.v1"
_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
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
_PAINT_ATTRIBUTE_RE = re.compile(br' paint_color="[^"]+"')
_CANONICAL_JSON_SEPARATORS = (",", ":")


class RadialHybridExportError(RadialExportError):
    """Raised when a selective Stage-B archive cannot be proved safe."""


@dataclass(frozen=True, slots=True)
class RadialHybridPartPlan:
    """Paint/provenance attached to one closed material-manifold region."""

    name: str
    role: str
    base_role: str
    physical_extruder: int
    paint_state_ids: np.ndarray
    source_exterior_mask: np.ndarray
    source_state: int | None = None


@dataclass(frozen=True, slots=True)
class RadialHybridPackage:
    """One validated selective-radial carrier plan.

    Geometry remains owned by ``radial_package``.  Stage B changes only the
    source-exterior triangle paint carried by conventional regions and the
    ordinary Full Spectrum Ratio definitions.  Physical radial shell regions
    stay unpainted and remain assigned directly to F1-F4.
    """

    radial_package: RadialExportPackage
    parts: tuple[RadialHybridPartPlan, ...]
    mixed_filament_definitions: str
    palette_state_count: int
    proof: Mapping[str, object] = field(default_factory=dict)


def _safe_json(value: object) -> object:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise RadialHybridExportError(
            "Stage-B provenance is not finite JSON data"
        ) from exc


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=_CANONICAL_JSON_SEPARATORS,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _array_sha256(values: np.ndarray) -> str:
    array = np.ascontiguousarray(values)
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(b"|")
    digest.update(str(tuple(int(v) for v in array.shape)).encode("ascii"))
    digest.update(b"|")
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest().upper()


def _serialised_coordinate(value: object) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise RadialHybridExportError("Stage-B geometry contains NaN/Inf")
    # Match radial_export's binary64 round-trip precision exactly.  Fewer
    # significant digits can merge distinct vertices in thin tetrahedral
    # regions before the archive is written, invalidating an otherwise exact
    # material partition.
    return f"{number:.17g}"


def _triangle_key(
    vertices: np.ndarray,
    face: Sequence[int],
) -> tuple[tuple[str, str, str], ...]:
    points = [
        tuple(_serialised_coordinate(value) for value in vertices[int(index)])
        for index in face
    ]
    if len(set(points)) != 3:
        raise RadialHybridExportError(
            "A Stage-B face collapses after radial 3MF coordinate serialization"
        )
    return tuple(sorted(points))


def _triangle_parity(
    vertices: np.ndarray,
    face: Sequence[int],
) -> int:
    points = [
        tuple(_serialised_coordinate(value) for value in vertices[int(index)])
        for index in face
    ]
    ordered = sorted(points)
    permutation = [ordered.index(point) for point in points]
    inversions = sum(
        permutation[left] > permutation[right]
        for left in range(3)
        for right in range(left + 1, 3)
    )
    return inversions & 1


def _external_fingerprint(
    triangle_keys: Sequence[tuple[tuple[str, str, str], ...]],
) -> str:
    digest = hashlib.sha256()
    for key in sorted(triangle_keys):
        digest.update(repr(key).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest().upper()


def _analyse_exact_partition(
    geometries: Sequence[tuple[np.ndarray, np.ndarray]],
) -> tuple[tuple[np.ndarray, ...], int, str]:
    """Classify exact exterior/interfaces and reject gaps/duplicate overlap.

    A material-manifold internal triangle must occur in exactly two different
    closed parts with opposite winding.  A source-exterior triangle occurs
    exactly once.  Three owners, same-part duplicates, or equal winding fail
    closed.  This is the archive-level exact-touch proof; the builder's volume
    and source-exterior proofs remain separately mandatory.
    """

    owners: dict[
        tuple[tuple[str, str, str], ...],
        list[tuple[int, int, int]],
    ] = defaultdict(list)
    per_part_keys: list[list[tuple[tuple[str, str, str], ...]]] = []
    for part_index, (vertices, faces) in enumerate(geometries):
        local: list[tuple[tuple[str, str, str], ...]] = []
        for face_index, face in enumerate(faces):
            key = _triangle_key(vertices, face)
            local.append(key)
            owners[key].append(
                (part_index, face_index, _triangle_parity(vertices, face))
            )
        per_part_keys.append(local)

    exterior_masks = [
        np.zeros(len(faces), dtype=np.bool_) for _vertices, faces in geometries
    ]
    external_keys: list[tuple[tuple[str, str, str], ...]] = []
    interface_pairs = 0
    for key, records in owners.items():
        if len(records) == 1:
            part_index, face_index, _parity = records[0]
            exterior_masks[part_index][face_index] = True
            external_keys.append(key)
            continue
        if len(records) != 2:
            raise RadialHybridExportError(
                "A Stage-B triangle has more than two material owners"
            )
        first, second = records
        if first[0] == second[0]:
            raise RadialHybridExportError(
                "A Stage-B part contains a duplicate material-interface triangle"
            )
        if first[2] == second[2]:
            raise RadialHybridExportError(
                "A Stage-B material interface does not use opposite winding"
            )
        interface_pairs += 1
    return tuple(exterior_masks), interface_pairs, _external_fingerprint(external_keys)


def _signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    triangles = vertices[faces]
    return float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )


def _required_proof(result: object) -> dict[str, object]:
    metadata = getattr(result, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        raise RadialHybridExportError("Stage-B result metadata is malformed")
    required_true = (
        "material_manifold",
        "source_exterior_preserved_exactly",
        "shared_interface_partition_exact",
        "external_surface_coverage_exact",
    )
    for key in required_true:
        if metadata.get(key) is not True:
            raise RadialHybridExportError(
                f"Stage-B geometry proof is missing {key}"
            )
    for key in ("gap_mm", "positive_overlap_mm3"):
        try:
            actual = float(metadata.get(key, float("inf")))
        except (TypeError, ValueError) as exc:
            raise RadialHybridExportError(
                f"Stage-B geometry proof has invalid {key}"
            ) from exc
        if actual != 0.0:
            raise RadialHybridExportError(
                f"Stage-B material regions have nonzero {key}"
            )
    source = getattr(result, "source_volume_mm3", metadata.get("source_volume_mm3"))
    output = getattr(result, "output_volume_mm3", metadata.get("output_volume_mm3"))
    try:
        source_value = float(source)
        output_value = float(output)
    except (TypeError, ValueError) as exc:
        raise RadialHybridExportError(
            "Stage-B volume-conservation proof is malformed"
        ) from exc
    if (
        not math.isfinite(source_value)
        or source_value <= 0.0
        or not math.isfinite(output_value)
        or output_value <= 0.0
        or not math.isclose(
            output_value,
            source_value,
            rel_tol=1.0e-8,
            abs_tol=1.0e-8,
        )
    ):
        raise RadialHybridExportError(
            "Stage-B material regions do not conserve source volume"
        )
    return {
        "material_manifold": True,
        "source_exterior_preserved_exactly": True,
        "shared_interface_partition_exact": True,
        "external_surface_coverage_exact": True,
        "gap_mm": 0.0,
        "positive_overlap_mm3": 0.0,
        "source_volume_mm3": source_value,
        "output_volume_mm3": output_value,
    }


def package_from_selective_hybrid(
    result: object,
    palette: object,
    *,
    process_profile: str = RADIAL_PROCESS_PROFILE_MVP_020,
    layer_height_mm: float = 0.20,
    initial_layer_height_mm: float = 0.20,
) -> RadialHybridPackage:
    """Adapt a geometry-owned material manifold into Stage-B export data.

    ``result.parts`` uses the geometry-builder contract agreed for Stage B:
    ``physical_extruder``, ``source_exterior_mask`` and one
    ``paint_state_ids`` value per triangle.  Conventional carriers paint every
    source-exterior triangle, including physical states F1-F4.  Eligible
    partner shells remain unpainted so their physical thickness is preserved.
    """

    proof = _required_proof(result)
    raw_parts = tuple(getattr(result, "parts", ()))
    if not raw_parts:
        raise RadialHybridExportError("Stage-B result contains no material regions")
    raw_black_extruder = getattr(result, "black_extruder", None)
    if raw_black_extruder is None:
        plan = getattr(result, "plan", None)
        raw_black_extruder = getattr(plan, "black_extruder", None)
    try:
        black_extruder = int(raw_black_extruder)
    except (TypeError, ValueError) as exc:
        raise RadialHybridExportError(
            "Stage-B result does not declare a physical black extruder"
        ) from exc
    if not 1 <= black_extruder <= 4:
        raise RadialHybridExportError(
            "Stage-B black extruder must be one of physical F1-F4"
        )

    try:
        physical_hex = tuple(normalize_hex(value) for value in palette.physical_hex)
        palette_state_count = int(palette.palette_state_count)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RadialHybridExportError("Stage-B palette is malformed") from exc
    if len(physical_hex) != 4:
        raise RadialHybridExportError("Stage-B requires four physical colours")
    if not 4 <= palette_state_count <= len(PAINT_CODES):
        raise RadialHybridExportError("Stage-B palette state count is unsupported")
    try:
        definitions = make_portable_mixed_definitions(
            list(palette.mix_ratios_b),
            (
                None
                if palette.secondary_mix_ratios_b is None
                else list(palette.secondary_mix_ratios_b)
            ),
            palette_state_count,
            (
                None
                if palette.output_mix_ratios_b is None
                else list(palette.output_mix_ratios_b)
            ),
            False,
            physical_hex,
        )
    except Exception as exc:
        raise RadialHybridExportError(
            "Stage-B Full Spectrum Ratio definitions could not be generated"
        ) from exc
    if ",cm1," in definitions:
        raise RadialHybridExportError(
            "Grouped Cycle definitions are forbidden in selective Stage B"
        )

    staged: list[
        tuple[
            int,
            object,
            str,
            str,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
        ]
    ] = []
    for source_index, raw in enumerate(raw_parts):
        role = str(getattr(raw, "role", "")).strip()
        if role not in {
            "conventional_painted_carrier",
            "partner_outer_shell",
            "pure_black_core",
        }:
            raise RadialHybridExportError(
                f"Unsupported Stage-B material role: {role!r}"
            )
        try:
            extruder = int(getattr(raw, "physical_extruder"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise RadialHybridExportError(
                f"Stage-B part {source_index + 1} has no physical extruder"
            ) from exc
        if not 1 <= extruder <= 4:
            raise RadialHybridExportError(
                "Stage-B parts may reference only physical F1-F4"
            )
        vertices = np.asarray(getattr(raw, "vertices_mm"), dtype=np.float64)
        faces = np.asarray(getattr(raw, "faces"), dtype=np.int32)
        paint = np.asarray(getattr(raw, "paint_state_ids"), dtype=np.int16)
        raw_exterior = getattr(raw, "source_exterior_mask", None)
        if raw_exterior is None:
            raw_exterior = getattr(raw, "external_face_mask", None)
        if raw_exterior is None:
            raise RadialHybridExportError(
                "Stage-B part has no source-exterior face provenance"
            )
        exterior = np.asarray(raw_exterior, dtype=np.bool_)
        if vertices.ndim != 2 or vertices.shape[1:] != (3,):
            raise RadialHybridExportError("Stage-B part vertices are malformed")
        if faces.ndim != 2 or faces.shape[1:] != (3,):
            raise RadialHybridExportError("Stage-B part faces are malformed")
        if paint.shape != (len(faces),) or exterior.shape != (len(faces),):
            raise RadialHybridExportError(
                "Stage-B paint/exterior provenance does not match face count"
            )
        if len(paint) and (int(paint.min()) < -1 or int(paint.max()) >= palette_state_count):
            raise RadialHybridExportError(
                "Stage-B paint state is outside the active palette"
            )
        painted = paint >= 0
        if np.any(painted & ~exterior):
            raise RadialHybridExportError(
                "Stage-B triangle paint is allowed only on source exterior faces"
            )
        if role == "partner_outer_shell":
            if np.any(painted):
                raise RadialHybridExportError(
                    "Eligible radial partner shells must remain physically unpainted"
                )
            base_role = "partner_outer_shell"
            order = 2
        elif role == "pure_black_core":
            if extruder != black_extruder:
                raise RadialHybridExportError(
                    "A Stage-B pure-black core uses the wrong physical extruder"
                )
            if np.any(painted):
                raise RadialHybridExportError(
                    "An explicit Stage-B pure-black core must be internal/unpainted"
                )
            base_role = "pure_black_core"
            order = 0
        else:
            if not np.array_equal(painted, exterior):
                raise RadialHybridExportError(
                    "Every conventional carrier source-exterior face must be painted"
                )
            # A black, entirely internal conventional carrier is the physical
            # core required by the radial base archive.  Other carriers retain
            # a neutral allowed Stage-A role until hybrid metadata replaces it.
            if extruder == black_extruder and not np.any(exterior):
                base_role = "pure_black_core"
                order = 0
            else:
                base_role = "light_core"
                order = 1
        source_state = getattr(raw, "source_state", None)
        if source_state is None:
            source_state = getattr(raw, "source_state_id", None)
        staged.append(
            (
                order,
                raw,
                role,
                base_role,
                vertices,
                faces,
                paint,
                exterior,
            )
        )

    if not any(item[3] == "pure_black_core" for item in staged):
        black_carrier = next(
            (
                index
                for index, item in enumerate(staged)
                if item[2] == "conventional_painted_carrier"
                and int(getattr(item[1], "physical_extruder")) == black_extruder
            ),
            None,
        )
        if black_carrier is None:
            raise RadialHybridExportError(
                "Stage B has no black carrier for the trusted radial base"
            )
        item = staged[black_carrier]
        staged[black_carrier] = (
            0,
            item[1],
            item[2],
            "pure_black_core",
            item[4],
            item[5],
            item[6],
            item[7],
        )

    # Stage-A clipping priority is black/core and carriers first, partner
    # shells last.  Preserve source order inside each class for deterministic
    # interface and metadata IDs.
    staged.sort(key=lambda item: item[0])
    geometries = tuple((item[4], item[5]) for item in staged)
    derived_masks, interface_pairs, exterior_sha256 = _analyse_exact_partition(
        geometries
    )
    radial_parts: list[RadialExportPart] = []
    plans: list[RadialHybridPartPlan] = []
    volumes: list[float] = []
    for index, (item, derived) in enumerate(zip(staged, derived_masks, strict=True)):
        _order, raw, role, base_role, vertices, faces, paint, exterior = item
        if not np.array_equal(exterior, derived):
            raise RadialHybridExportError(
                f"Stage-B source-exterior provenance drifted for part {index + 1}"
            )
        volume = _signed_volume(vertices, faces)
        if not math.isfinite(volume) or volume <= 1.0e-12:
            raise RadialHybridExportError(
                "Every Stage-B material region must have positive signed volume"
            )
        volumes.append(volume)
        name = str(getattr(raw, "name", f"Stage B region {index + 1}")).strip()
        if not name:
            name = f"Stage B region {index + 1}"
        extruder = int(getattr(raw, "physical_extruder"))
        source_state = getattr(raw, "source_state", None)
        if source_state is None:
            source_state = getattr(raw, "source_state_id", None)
        radial_parts.append(
            RadialExportPart(
                name=name,
                role=base_role,
                vertices_mm=vertices,
                faces=faces,
                extruder=extruder,
                solid_infill=True,
                source_state=(None if source_state is None else int(source_state)),
                metadata={
                    "stage_b_role": role,
                    "closed_physical_volume": True,
                },
            )
        )
        paint_copy = np.array(paint, dtype=np.int16, copy=True)
        exterior_copy = np.array(exterior, dtype=np.bool_, copy=True)
        paint_copy.setflags(write=False)
        exterior_copy.setflags(write=False)
        plans.append(
            RadialHybridPartPlan(
                name=name,
                role=role,
                base_role=base_role,
                physical_extruder=extruder,
                paint_state_ids=paint_copy,
                source_exterior_mask=exterior_copy,
                source_state=(None if source_state is None else int(source_state)),
            )
        )

    if not any(plan.base_role == "pure_black_core" for plan in plans):
        raise RadialHybridExportError("Stage B has no internal pure-black core")
    if not any(plan.role == "partner_outer_shell" for plan in plans):
        raise RadialHybridExportError("Stage B has no eligible partner outer shell")
    if not any(np.any(plan.paint_state_ids >= 0) for plan in plans):
        raise RadialHybridExportError(
            "Stage B has no conventional painted carrier; use Stage A instead"
        )
    output_volume = float(sum(volumes))
    if not math.isclose(
        output_volume,
        float(proof["output_volume_mm3"]),
        rel_tol=1.0e-8,
        abs_tol=1.0e-8,
    ):
        raise RadialHybridExportError(
            "Stage-B part volumes do not match the builder output-volume proof"
        )
    proof = {
        **proof,
        "interface_triangle_pairs": int(interface_pairs),
        "source_exterior_sha256": exterior_sha256,
        "painted_source_exterior_only": True,
        "eligible_shells_physically_unpainted": True,
        "legacy_ratio_cycle_rows": 0,
    }
    radial_package = RadialExportPackage(
        parts=tuple(radial_parts),
        physical_hex=physical_hex,  # type: ignore[arg-type]
        black_extruder=black_extruder,
        metadata=proof,
        layer_height_mm=float(layer_height_mm),
        initial_layer_height_mm=float(initial_layer_height_mm),
        renderer="radial",
        process_profile=str(process_profile),
    )
    return RadialHybridPackage(
        radial_package=radial_package,
        parts=tuple(plans),
        mixed_filament_definitions=definitions,
        palette_state_count=palette_state_count,
        proof=_safe_json(proof),
    )


def _copy_member(
    source: zipfile.ZipFile,
    destination: zipfile.ZipFile,
    name: str,
) -> None:
    with source.open(name, "r") as incoming, destination.open(
        name, "w", force_zip64=True
    ) as outgoing:
        for block in iter(lambda: incoming.read(1024 * 1024), b""):
            outgoing.write(block)


def _write_painted_model(
    source: zipfile.ZipFile,
    destination: zipfile.ZipFile,
    plans: Sequence[RadialHybridPartPlan],
) -> None:
    name = "3D/Objects/radial_parts.model"
    part_index = -1
    face_index = 0
    with source.open(name, "r") as incoming, destination.open(
        name, "w", force_zip64=True
    ) as raw:
        outgoing = io.BufferedWriter(raw, buffer_size=1024 * 1024)
        for line in incoming:
            stripped = line.lstrip()
            if stripped.startswith(b"<object "):
                part_index += 1
                face_index = 0
            if stripped.startswith(b"<triangle "):
                if not 0 <= part_index < len(plans):
                    raise RadialHybridExportError(
                        "Radial base triangle occurs outside a known part"
                    )
                plan = plans[part_index]
                if face_index >= len(plan.paint_state_ids):
                    raise RadialHybridExportError(
                        "Radial base face count exceeds the Stage-B paint plan"
                    )
                state = int(plan.paint_state_ids[face_index])
                if state >= 0:
                    marker = b"/>"
                    if line.count(marker) != 1 or b"paint_color=" in line:
                        raise RadialHybridExportError(
                            "Radial base triangle format is not paint-safe"
                        )
                    line = line.replace(
                        marker,
                        f' paint_color="{PAINT_CODES[state]}"/>'.encode("ascii"),
                        1,
                    )
                face_index += 1
            outgoing.write(line)
        outgoing.flush()
    if part_index + 1 != len(plans):
        raise RadialHybridExportError("Radial base part count drifted")
    if plans and face_index != len(plans[-1].paint_state_ids):
        raise RadialHybridExportError("Radial base final face count drifted")


def _part_metadata(
    package: RadialHybridPackage,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, (part, radial_part) in enumerate(
        zip(package.parts, package.radial_package.parts, strict=True)
    ):
        states = Counter(
            int(value) for value in part.paint_state_ids if int(value) >= 0
        )
        vertices = np.asarray(radial_part.vertices_mm, dtype=np.float64)
        faces = np.asarray(radial_part.faces, dtype=np.int32)
        geometry_digest = hashlib.sha256()
        for vertex in vertices:
            geometry_digest.update(
                (" ".join(_serialised_coordinate(value) for value in vertex) + "\n").encode(
                    "ascii"
                )
            )
        geometry_digest.update(np.ascontiguousarray(faces).tobytes())
        result.append(
            {
                "index": index,
                "name": part.name,
                "role": part.role,
                "base_role": part.base_role,
                "physical_extruder": int(part.physical_extruder),
                "closed_physical_volume": True,
                "source_state": part.source_state,
                "vertices": int(len(vertices)),
                "faces": int(len(faces)),
                "source_exterior_faces": int(
                    np.count_nonzero(part.source_exterior_mask)
                ),
                "painted_faces": int(np.count_nonzero(part.paint_state_ids >= 0)),
                "paint_state_counts": {
                    str(state): int(count) for state, count in sorted(states.items())
                },
                "paint_plan_sha256": _array_sha256(part.paint_state_ids),
                "source_exterior_mask_sha256": _array_sha256(
                    part.source_exterior_mask
                ),
                "geometry_sha256": geometry_digest.hexdigest().upper(),
            }
        )
    return result


def _hybrid_metadata(
    package: RadialHybridPackage,
    base_metadata: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": RADIAL_HYBRID_SCHEMA,
        "renderer": "Selective Radial Hybrid Stage B",
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "physical_materials_only": False,
        "physical_extruders_only": True,
        "single_print_object": True,
        "normal_part_count": len(package.parts),
        "palette_state_count": int(package.palette_state_count),
        "process_profile": str(package.radial_package.process_profile),
        "layer_height_mm": float(package.radial_package.layer_height_mm),
        "initial_layer_height_mm": float(
            package.radial_package.initial_layer_height_mm
        ),
        "sparse_infill_density_percent": (
            radial_process_profile_sparse_infill_percent(
                str(package.radial_package.process_profile)
            )
        ),
        "black_extruder": int(package.radial_package.black_extruder),
        "physical_hex": [
            normalize_hex(value) for value in package.radial_package.physical_hex
        ],
        "mixed_filament_definitions_sha256": _sha256_bytes(
            package.mixed_filament_definitions.encode("utf-8")
        ),
        "grouped_cycle_rows": 0,
        "parts": _part_metadata(package),
        "material_manifold_proof": _safe_json(package.proof),
        "base_radial_metadata_sha256": _sha256_bytes(
            _canonical_json_bytes(base_metadata)
        ),
        "base_radial_metadata": _safe_json(base_metadata),
        "safety": {
            "support_enabled": False,
            "flush_to_model_enabled": False,
            "prime_tower_enabled": True,
            "closed_physical_volumes": True,
            "sparse_infill_density_percent": (
                radial_process_profile_sparse_infill_percent(
                    str(package.radial_package.process_profile)
                )
            ),
            "requires_orca_preview": True,
            "requires_explicit_print_ready_promotion": True,
        },
    }


def _strip_paint_model_bytes(value: bytes) -> bytes:
    return _PAINT_ATTRIBUTE_RE.sub(b"", value)


def _sanitised_base_archive(
    hybrid_path: Path,
    metadata: Mapping[str, object],
) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(suffix=".radial-base.3mf")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(hybrid_path, "r") as source, zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as destination:
            for name in source.namelist():
                if name == "3D/Objects/radial_parts.model":
                    destination.writestr(
                        name,
                        _strip_paint_model_bytes(source.read(name)),
                    )
                elif name == "Metadata/project_settings.config":
                    project = json.loads(source.read(name))
                    project["mixed_filament_definitions"] = ""
                    destination.writestr(
                        name,
                        json.dumps(project, ensure_ascii=False, indent=2).encode(
                            "utf-8"
                        ),
                    )
                elif name == "Metadata/radial_shell_experimental.json":
                    destination.writestr(
                        name,
                        json.dumps(
                            metadata["base_radial_metadata"],
                            ensure_ascii=False,
                            indent=2,
                        ).encode("utf-8"),
                    )
                else:
                    _copy_member(source, destination, name)
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _parse_hybrid_model(
    value: bytes,
    palette_state_count: int,
) -> tuple[
    tuple[tuple[np.ndarray, np.ndarray], ...],
    tuple[np.ndarray, ...],
]:
    try:
        root = ET.fromstring(value)
    except ET.ParseError as exc:
        raise RadialHybridExportError("Stage-B parts model XML is malformed") from exc
    objects = root.findall(f".//{{{_CORE_NS}}}resources/{{{_CORE_NS}}}object")
    geometries: list[tuple[np.ndarray, np.ndarray]] = []
    paints: list[np.ndarray] = []
    for expected_id, element in enumerate(objects, start=1):
        if int(element.attrib.get("id", 0)) != expected_id:
            raise RadialHybridExportError("Stage-B object IDs are not sequential")
        mesh = element.find(f"{{{_CORE_NS}}}mesh")
        if mesh is None:
            raise RadialHybridExportError("A Stage-B object has no mesh")
        vertices_node = mesh.find(f"{{{_CORE_NS}}}vertices")
        triangles_node = mesh.find(f"{{{_CORE_NS}}}triangles")
        if vertices_node is None or triangles_node is None:
            raise RadialHybridExportError("A Stage-B object mesh is incomplete")
        vertices = np.asarray(
            [
                [
                    float(vertex.attrib[key])
                    for key in ("x", "y", "z")
                ]
                for vertex in vertices_node
            ],
            dtype=np.float64,
        )
        faces: list[list[int]] = []
        states: list[int] = []
        code_to_state = {
            code: state
            for state, code in enumerate(PAINT_CODES[:palette_state_count])
        }
        for triangle in triangles_node:
            attributes = set(triangle.attrib)
            if attributes not in (
                {"v1", "v2", "v3"},
                {"v1", "v2", "v3", "paint_color"},
            ):
                raise RadialHybridExportError(
                    "A Stage-B triangle contains an unknown face property"
                )
            face = [int(triangle.attrib[key]) for key in ("v1", "v2", "v3")]
            if not face or min(face) < 0 or max(face) >= len(vertices):
                raise RadialHybridExportError("A Stage-B triangle index is invalid")
            faces.append(face)
            if "paint_color" not in triangle.attrib:
                states.append(-1)
            else:
                try:
                    states.append(code_to_state[triangle.attrib["paint_color"]])
                except KeyError as exc:
                    raise RadialHybridExportError(
                        "A Stage-B triangle uses an inactive paint state"
                    ) from exc
        geometries.append((vertices, np.asarray(faces, dtype=np.int32)))
        paints.append(np.asarray(states, dtype=np.int16))
    return tuple(geometries), tuple(paints)


def validate_hybrid_3mf(
    path: Path,
    *,
    expected_package: RadialHybridPackage | None = None,
    trusted_base_path: Path | None = None,
) -> RadialExportValidation:
    """Re-open and fail closed on any Stage-B structure or paint drift."""

    path = Path(path)
    if not path.is_file():
        raise RadialHybridExportError(f"Stage-B 3MF does not exist: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise RadialHybridExportError("Stage-B 3MF has a ZIP CRC failure")
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != _REQUIRED_ARCHIVE_MEMBERS:
            raise RadialHybridExportError(
                "Stage-B archive members differ from the strict allowlist"
            )
        try:
            project = json.loads(
                archive.read("Metadata/project_settings.config")
            )
            metadata = json.loads(
                archive.read("Metadata/radial_shell_experimental.json")
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RadialHybridExportError("Stage-B metadata is malformed") from exc
        if not isinstance(project, dict) or not isinstance(metadata, dict):
            raise RadialHybridExportError("Stage-B metadata roots are malformed")
        required_metadata_keys = {
            "schema",
            "renderer",
            "experimental",
            "slice_only",
            "print_allowed",
            "physical_materials_only",
            "physical_extruders_only",
            "single_print_object",
            "normal_part_count",
            "palette_state_count",
            "process_profile",
            "layer_height_mm",
            "initial_layer_height_mm",
            "sparse_infill_density_percent",
            "black_extruder",
            "physical_hex",
            "mixed_filament_definitions_sha256",
            "grouped_cycle_rows",
            "parts",
            "material_manifold_proof",
            "base_radial_metadata_sha256",
            "base_radial_metadata",
            "safety",
        }
        if set(metadata) != required_metadata_keys:
            raise RadialHybridExportError("Stage-B metadata allowlist drifted")
        expected_static = {
            "schema": RADIAL_HYBRID_SCHEMA,
            "renderer": "Selective Radial Hybrid Stage B",
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "physical_materials_only": False,
            "physical_extruders_only": True,
            "single_print_object": True,
            "grouped_cycle_rows": 0,
        }
        for key, expected in expected_static.items():
            if metadata.get(key) != expected:
                raise RadialHybridExportError(
                    f"Stage-B metadata {key} drifted"
                )
        process_profile = str(metadata.get("process_profile", ""))
        expected_sparse_infill = radial_process_profile_sparse_infill_percent(
            process_profile
        )
        if metadata.get("sparse_infill_density_percent") != expected_sparse_infill:
            raise RadialHybridExportError(
                "Stage-B sparse-infill metadata drifted"
            )
        safety = metadata.get("safety")
        if safety != {
            "support_enabled": False,
            "flush_to_model_enabled": False,
            "prime_tower_enabled": True,
            "closed_physical_volumes": True,
            "sparse_infill_density_percent": expected_sparse_infill,
            "requires_orca_preview": True,
            "requires_explicit_print_ready_promotion": True,
        }:
            raise RadialHybridExportError("Stage-B safety metadata drifted")
        proof = metadata.get("material_manifold_proof")
        if not isinstance(proof, dict):
            raise RadialHybridExportError("Stage-B material-manifold proof is missing")
        for key in (
            "material_manifold",
            "source_exterior_preserved_exactly",
            "shared_interface_partition_exact",
            "external_surface_coverage_exact",
            "painted_source_exterior_only",
            "eligible_shells_physically_unpainted",
        ):
            if proof.get(key) is not True:
                raise RadialHybridExportError(f"Stage-B proof {key} is missing")
        if float(proof.get("gap_mm", float("inf"))) != 0.0 or float(
            proof.get("positive_overlap_mm3", float("inf"))
        ) != 0.0:
            raise RadialHybridExportError("Stage-B proof contains a gap or overlap")
        base_metadata = metadata.get("base_radial_metadata")
        if not isinstance(base_metadata, dict):
            raise RadialHybridExportError("Stage-B base radial metadata is missing")
        if metadata.get("base_radial_metadata_sha256") != _sha256_bytes(
            _canonical_json_bytes(base_metadata)
        ):
            raise RadialHybridExportError("Stage-B base metadata digest drifted")

        definitions = project.get("mixed_filament_definitions")
        if not isinstance(definitions, str) or not definitions:
            raise RadialHybridExportError(
                "Stage-B project has no ordinary Full Spectrum definitions"
            )
        if ",cm1," in definitions:
            raise RadialHybridExportError(
                "Grouped Cycle definitions are forbidden in Stage B"
            )
        if metadata.get("mixed_filament_definitions_sha256") != _sha256_bytes(
            definitions.encode("utf-8")
        ):
            raise RadialHybridExportError("Stage-B mixed definitions drifted")
        if project.get("sparse_infill_density") != f"{expected_sparse_infill}%":
            raise RadialHybridExportError(
                "Stage-B project sparse infill drifted"
            )
        palette_state_count = int(metadata.get("palette_state_count", 0))
        if not 4 <= palette_state_count <= len(PAINT_CODES):
            raise RadialHybridExportError("Stage-B palette state count is invalid")
        geometries, paints = _parse_hybrid_model(
            archive.read("3D/Objects/radial_parts.model"),
            palette_state_count,
        )
        meta_parts = metadata.get("parts")
        if (
            not isinstance(meta_parts, list)
            or len(meta_parts) != len(geometries)
            or int(metadata.get("normal_part_count", -1)) != len(geometries)
        ):
            raise RadialHybridExportError("Stage-B part metadata count drifted")
        derived_masks, interface_pairs, exterior_sha256 = _analyse_exact_partition(
            geometries
        )
        if int(proof.get("interface_triangle_pairs", -1)) != interface_pairs:
            raise RadialHybridExportError("Stage-B interface-pair proof drifted")
        if proof.get("source_exterior_sha256") != exterior_sha256:
            raise RadialHybridExportError("Stage-B exterior fingerprint drifted")
        total_vertices = 0
        total_faces = 0
        extruders: list[int] = []
        for index, (part_meta, geometry, paint, exterior) in enumerate(
            zip(meta_parts, geometries, paints, derived_masks, strict=True)
        ):
            if not isinstance(part_meta, dict) or int(part_meta.get("index", -1)) != index:
                raise RadialHybridExportError("Stage-B part metadata order drifted")
            if part_meta.get("closed_physical_volume") is not True:
                raise RadialHybridExportError(
                    "A Stage-B material region is not declared closed"
                )
            vertices, faces = geometry
            total_vertices += len(vertices)
            total_faces += len(faces)
            if int(part_meta.get("vertices", -1)) != len(vertices) or int(
                part_meta.get("faces", -1)
            ) != len(faces):
                raise RadialHybridExportError("Stage-B mesh counts drifted")
            role = str(part_meta.get("role", ""))
            painted = paint >= 0
            if np.any(painted & ~exterior):
                raise RadialHybridExportError(
                    "Stage-B paint escaped onto a material interface"
                )
            if role == "conventional_painted_carrier":
                if not np.array_equal(painted, exterior):
                    raise RadialHybridExportError(
                        "A Stage-B carrier exterior is incompletely painted"
                    )
            elif role in {"partner_outer_shell", "pure_black_core"}:
                if np.any(painted):
                    raise RadialHybridExportError(
                        "A physical Stage-B radial region contains triangle paint"
                    )
            else:
                raise RadialHybridExportError("Stage-B part role drifted")
            states = Counter(int(value) for value in paint if int(value) >= 0)
            if part_meta.get("paint_state_counts") != {
                str(state): int(count) for state, count in sorted(states.items())
            }:
                raise RadialHybridExportError("Stage-B paint state counts drifted")
            if int(part_meta.get("source_exterior_faces", -1)) != int(
                np.count_nonzero(exterior)
            ) or int(part_meta.get("painted_faces", -1)) != int(
                np.count_nonzero(painted)
            ):
                raise RadialHybridExportError("Stage-B paint/exterior counts drifted")
            if part_meta.get("paint_plan_sha256") != _array_sha256(paint):
                raise RadialHybridExportError("Stage-B paint-plan digest drifted")
            if part_meta.get("source_exterior_mask_sha256") != _array_sha256(
                exterior
            ):
                raise RadialHybridExportError("Stage-B exterior-mask digest drifted")
            extruder = int(part_meta.get("physical_extruder", 0))
            if not 1 <= extruder <= 4:
                raise RadialHybridExportError("Stage-B part uses a virtual extruder")
            extruders.append(extruder)

    # Reconstruct the validated physical archive by removing only the Stage-B
    # paint/Ratio layer.  Existing radial validation then re-proves child
    # topology, F1-F4 assignments, profile allowlists and SLICE ONLY metadata.
    sanitised = _sanitised_base_archive(path, metadata)
    try:
        base_validation = validate_radial_3mf(
            sanitised,
            expected_parts=len(geometries),
            expected_physical=metadata["physical_hex"],
            expected_extruders=extruders,
            expected_process_profile=str(metadata["process_profile"]),
        )
    finally:
        sanitised.unlink(missing_ok=True)

    if trusted_base_path is not None:
        with zipfile.ZipFile(trusted_base_path, "r") as base, zipfile.ZipFile(
            path, "r"
        ) as hybrid:
            if set(base.namelist()) != set(hybrid.namelist()):
                raise RadialHybridExportError("Trusted radial base members drifted")
            for name in base.namelist():
                if name in {
                    "3D/Objects/radial_parts.model",
                    "Metadata/project_settings.config",
                    "Metadata/radial_shell_experimental.json",
                }:
                    continue
                if base.read(name) != hybrid.read(name):
                    raise RadialHybridExportError(
                        f"Stage-B changed a trusted radial member: {name}"
                    )
            if base.read("3D/Objects/radial_parts.model") != _strip_paint_model_bytes(
                hybrid.read("3D/Objects/radial_parts.model")
            ):
                raise RadialHybridExportError(
                    "Stage-B geometry differs from the trusted radial base"
                )
            base_project = json.loads(
                base.read("Metadata/project_settings.config")
            )
            hybrid_project = json.loads(
                hybrid.read("Metadata/project_settings.config")
            )
            hybrid_project["mixed_filament_definitions"] = ""
            if hybrid_project != base_project:
                raise RadialHybridExportError(
                    "Stage-B changed a project setting other than mixed definitions"
                )

    if expected_package is not None:
        expected_metadata = _hybrid_metadata(
            expected_package,
            metadata["base_radial_metadata"],
        )
        if metadata != expected_metadata:
            raise RadialHybridExportError(
                "Stage-B archive differs from the trusted in-memory package"
            )
        if definitions != expected_package.mixed_filament_definitions:
            raise RadialHybridExportError(
                "Stage-B definitions differ from the trusted palette"
            )
        for actual, expected in zip(
            paints,
            expected_package.parts,
            strict=True,
        ):
            if not np.array_equal(actual, expected.paint_state_ids):
                raise RadialHybridExportError(
                    "Stage-B paint differs from the trusted geometry provenance"
                )

    return RadialExportValidation(
        path=path,
        sha256=_sha256_path(path),
        bytes=path.stat().st_size,
        parts=base_validation.parts,
        vertices=total_vertices,
        faces=total_faces,
        physical_extruders=tuple(extruders),
        zip_crc_ok=True,
        slice_only=True,
        print_allowed=False,
        physical_materials_only=False,
        static_validation_ok=True,
    )


def write_hybrid_3mf_atomic(
    destination: Path,
    package: RadialHybridPackage,
    *,
    title: str | None = None,
) -> RadialExportValidation:
    """Generate a trusted radial base, add carriers, and re-open atomically."""

    destination = Path(destination).with_suffix(".3mf")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.hybrid.tmp"
    )
    with tempfile.TemporaryDirectory(prefix="chromamatter-stage-b-") as directory:
        base_path = Path(directory) / "validated_radial_base.3mf"
        write_radial_3mf_atomic(
            base_path,
            package.radial_package,
            title=title or destination.stem,
        )
        try:
            with zipfile.ZipFile(base_path, "r") as source:
                base_metadata = json.loads(
                    source.read("Metadata/radial_shell_experimental.json")
                )
                project = json.loads(
                    source.read("Metadata/project_settings.config")
                )
                project["mixed_filament_definitions"] = (
                    package.mixed_filament_definitions
                )
                metadata = _hybrid_metadata(package, base_metadata)
                with zipfile.ZipFile(
                    temporary,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                    allowZip64=True,
                ) as archive:
                    for name in source.namelist():
                        if name == "3D/Objects/radial_parts.model":
                            _write_painted_model(source, archive, package.parts)
                        elif name == "Metadata/project_settings.config":
                            archive.writestr(
                                name,
                                json.dumps(
                                    project,
                                    ensure_ascii=False,
                                    indent=2,
                                ).encode("utf-8"),
                            )
                        elif name == "Metadata/radial_shell_experimental.json":
                            archive.writestr(
                                name,
                                json.dumps(
                                    metadata,
                                    ensure_ascii=False,
                                    indent=2,
                                ).encode("utf-8"),
                            )
                        else:
                            _copy_member(source, archive, name)
            validation = validate_hybrid_3mf(
                temporary,
                expected_package=package,
                trusted_base_path=base_path,
            )
            os.replace(temporary, destination)
            return RadialExportValidation(
                path=destination,
                sha256=_sha256_path(destination),
                bytes=destination.stat().st_size,
                parts=validation.parts,
                vertices=validation.vertices,
                faces=validation.faces,
                physical_extruders=validation.physical_extruders,
                zip_crc_ok=True,
                slice_only=True,
                print_allowed=False,
                physical_materials_only=False,
                static_validation_ok=True,
            )
        finally:
            temporary.unlink(missing_ok=True)


__all__ = [
    "RADIAL_HYBRID_SCHEMA",
    "RadialHybridExportError",
    "RadialHybridPackage",
    "RadialHybridPartPlan",
    "package_from_selective_hybrid",
    "validate_hybrid_3mf",
    "write_hybrid_3mf_atomic",
]
