"""Safe export colour handling for generated closure surfaces.

Solidification creates mating/internal faces which are not visible after the
parts are assembled.  Their transferred vertex colours can nevertheless turn
into many Full Spectrum states and unnecessary filament changes.  This module
keeps generated-face identity separate from geometry, validates that identity
against the current topology, preserves an exterior guard band, and collapses
only untouched hidden faces at export time.

The public helpers intentionally do not depend on the 3MF writer or the r8
adaptive-shading implementation.  A later shading pass can AND its own allowed
mask with :attr:`GeneratedSurfaceColorResult.adaptive_allowed_mask`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import heapq
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np

from .mixer import PALETTE_STATE_COUNT, palette_mix_specs
from .models import ColorResult, MeshLevel, PreparedGeometry


FACE_PROVENANCE_SOURCE = np.uint8(0)
FACE_PROVENANCE_PLANAR_CAP = np.uint8(1)
FACE_PROVENANCE_LOCAL_CAP = np.uint8(2)
FACE_PROVENANCE_VOLUME_INTERFACE = np.uint8(3)
KNOWN_FACE_PROVENANCE = frozenset(
    {
        int(FACE_PROVENANCE_SOURCE),
        int(FACE_PROVENANCE_PLANAR_CAP),
        int(FACE_PROVENANCE_LOCAL_CAP),
        int(FACE_PROVENANCE_VOLUME_INTERFACE),
    }
)
PROVENANCE_SCHEMA = "obj-adjuster.generated-face-provenance.v1"
EXPORT_SCHEMA = "obj-adjuster.generated-hidden-colour.v1"

# r8/future adaptive-shading bridges should read this mask and combine it with
# their own manual/tree eligibility masks.  False means that automatic
# subtriangle shading must not be generated on that root face.
ADAPTIVE_ALLOWED_MASK_ATTRIBUTE = "_generated_surface_adaptive_allowed_mask"
EXPORT_DIAGNOSTICS_ATTRIBUTE = "_generated_surface_color_diagnostics"

_PINK_STATES = np.asarray(
    [3]
    + [
        4 + index
        for index, (left, right, _ratio) in enumerate(palette_mix_specs())
        if 3 in (left, right)
    ],
    dtype=np.int64,
)


@dataclass(frozen=True)
class ProvenanceValidation:
    valid: bool
    reason: str
    record: dict[str, object]


@dataclass(frozen=True)
class GeneratedSurfaceMasks:
    generated: np.ndarray
    guard: np.ndarray
    hidden: np.ndarray
    valid: bool
    diagnostic: dict[str, object]


@dataclass(frozen=True)
class GeneratedSurfaceColorResult:
    colors: ColorResult
    masks: GeneratedSurfaceMasks
    adaptive_allowed_mask: np.ndarray
    collapsed_mask: np.ndarray
    diagnostic: dict[str, object]


def face_topology_fingerprint(level: MeshLevel) -> str:
    """Return a stable topology-only digest for provenance freshness checks."""

    faces = np.ascontiguousarray(np.asarray(level.faces), dtype="<i4")
    digest = hashlib.sha256()
    digest.update(np.asarray([len(level.vertices_unit), len(faces)], dtype="<i8").tobytes())
    digest.update(faces.tobytes())
    return digest.hexdigest()


def encode_face_ranges(face_ids: Iterable[int]) -> list[list[int]]:
    """Encode sorted face IDs as compact half-open ranges."""

    values = np.unique(np.fromiter((int(value) for value in face_ids), dtype=np.int64))
    if not len(values):
        return []
    ranges: list[list[int]] = []
    start = previous = int(values[0])
    for value_raw in values[1:]:
        value = int(value_raw)
        if value != previous + 1:
            ranges.append([start, previous + 1])
            start = value
        previous = value
    ranges.append([start, previous + 1])
    return ranges


def decode_face_ranges(
    ranges: object,
    *,
    face_count: int,
) -> np.ndarray:
    """Decode validated half-open ranges into unique local face IDs."""

    if not isinstance(ranges, Sequence) or isinstance(ranges, (str, bytes)):
        raise ValueError("face ranges must be a sequence")
    chunks: list[np.ndarray] = []
    previous_end = 0
    for index, value in enumerate(ranges):
        if (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
            or len(value) != 2
        ):
            raise ValueError(f"face range {index} is not [start, end]")
        start, end = int(value[0]), int(value[1])
        if start < 0 or end <= start or end > int(face_count):
            raise ValueError(f"face range {index} is outside 0..{face_count}")
        if chunks and start < previous_end:
            raise ValueError("face ranges overlap or are not sorted")
        chunks.append(np.arange(start, end, dtype=np.int64))
        previous_end = end
    return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.int64)


def derive_part_face_provenance(
    part_face_counts: Sequence[int],
    repair_records: object,
    *,
    topology_changed: bool = False,
) -> tuple[tuple[np.ndarray, ...] | None, dict[str, object]]:
    """Build local provenance arrays from solidification repair metadata.

    Any malformed/stale record invalidates the complete result.  A partial
    mask is more dangerous than skipping the colour optimisation entirely.
    """

    counts = tuple(int(value) for value in part_face_counts)
    if not counts or any(value < 0 for value in counts):
        return None, {"status": "unavailable", "reason": "invalid_part_face_counts"}
    if topology_changed:
        return None, {"status": "stale", "reason": "topology_changed_after_repair"}
    if not isinstance(repair_records, Sequence) or isinstance(
        repair_records, (str, bytes)
    ):
        return None, {"status": "unavailable", "reason": "repair_records_missing"}

    origins = [np.zeros(value, dtype=np.uint8) for value in counts]
    marked_records = 0
    has_volume_rebuild = any(
        isinstance(value, Mapping)
        and str(value.get("method", "")) == "recursive_volume_partition"
        for value in repair_records
    )

    def mark(part_id: int, face_ids: np.ndarray, code: np.uint8, label: str) -> None:
        nonlocal marked_records
        if not 0 <= int(part_id) < len(origins):
            raise ValueError(f"{label}: invalid part {part_id}")
        ids = np.asarray(face_ids, dtype=np.int64).reshape(-1)
        if len(ids) and (int(ids.min()) < 0 or int(ids.max()) >= counts[int(part_id)]):
            raise ValueError(f"{label}: face ID outside part {part_id}")
        if len(ids) != len(np.unique(ids)):
            raise ValueError(f"{label}: duplicate face IDs")
        previous = origins[int(part_id)][ids]
        if np.any((previous != FACE_PROVENANCE_SOURCE) & (previous != code)):
            raise ValueError(f"{label}: conflicting provenance")
        origins[int(part_id)][ids] = code
        if len(ids):
            marked_records += 1

    try:
        for record_index, record_value in enumerate(repair_records):
            if not isinstance(record_value, Mapping):
                raise ValueError(f"repair record {record_index} is not a mapping")
            record = dict(record_value)
            method = str(record.get("method", ""))

            loops = record.get("loops")
            # A recursive volume fallback replaces every input face.  Local
            # cap IDs from the pre-volume mesh are then stale; only the final
            # negative marker ranges are safe to retain.
            if (
                method == "strict_planar_unmatched_boundary_caps"
                and not has_volume_rebuild
            ):
                if not isinstance(loops, Sequence) or isinstance(loops, (str, bytes)):
                    raise ValueError("local-cap loop records are missing")
                for loop_index, loop_value in enumerate(loops):
                    if not isinstance(loop_value, Mapping):
                        raise ValueError(f"local-cap loop {loop_index} is invalid")
                    loop = dict(loop_value)
                    ids = np.asarray(loop.get("cap_face_ids", []), dtype=np.int64)
                    mark(
                        int(loop["part_id"]),
                        ids,
                        FACE_PROVENANCE_LOCAL_CAP,
                        f"local-cap loop {loop_index}",
                    )

            if method == "partitioned_shared_caps" and not has_volume_rebuild:
                interfaces = record.get("interfaces", [])
                if not isinstance(interfaces, Sequence) or isinstance(
                    interfaces, (str, bytes)
                ):
                    raise ValueError("planar interface records are missing")
                for interface_index, interface_value in enumerate(interfaces):
                    if not isinstance(interface_value, Mapping):
                        raise ValueError(f"interface {interface_index} is invalid")
                    ranges = interface_value.get("cap_face_range_by_part")
                    if not isinstance(ranges, Mapping):
                        raise ValueError(f"interface {interface_index} has no face ranges")
                    for part_key, range_value in ranges.items():
                        part_id = int(part_key)
                        ids = decode_face_ranges(
                            [range_value], face_count=counts[part_id]
                        )
                        mark(
                            part_id,
                            ids,
                            FACE_PROVENANCE_PLANAR_CAP,
                            f"interface {interface_index}",
                        )

            if method == "recursive_volume_partition":
                parts = record.get("parts", [])
                if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes)):
                    raise ValueError("volume partition part records are missing")
                for part_index, part_value in enumerate(parts):
                    if not isinstance(part_value, Mapping):
                        raise ValueError(f"volume part {part_index} is invalid")
                    part = dict(part_value)
                    part_id = int(part.get("part_id", part_index))
                    ids = decode_face_ranges(
                        part.get("generated_face_ranges", []),
                        face_count=counts[part_id],
                    )
                    mark(
                        part_id,
                        ids,
                        FACE_PROVENANCE_VOLUME_INTERFACE,
                        f"volume part {part_index}",
                    )
    except (IndexError, KeyError, TypeError, ValueError, OverflowError) as exc:
        return None, {
            "status": "unavailable",
            "reason": "invalid_repair_provenance",
            "detail": str(exc),
        }

    generated = int(
        sum(np.count_nonzero(value != FACE_PROVENANCE_SOURCE) for value in origins)
    )
    return tuple(origins), {
        "status": "fresh",
        "reason": "ok",
        "generated_faces": generated,
        "marked_records": int(marked_records),
        "volume_rebuild_superseded_earlier_face_ids": bool(
            has_volume_rebuild
        ),
    }


def make_face_provenance_record(
    level: MeshLevel,
    *,
    status: str = "fresh",
    reason: str = "ok",
    includes_topology_edits: bool = False,
) -> dict[str, object]:
    """Create the metadata record used to reject stale provenance arrays."""

    provenance = np.asarray(level.face_provenance)
    fresh = str(status) == "fresh" and provenance.shape == (len(level.faces),)
    counts: dict[str, int] = {}
    if fresh:
        unique, values = np.unique(provenance, return_counts=True)
        counts = {str(int(key)): int(value) for key, value in zip(unique, values, strict=True)}
    return {
        "schema": PROVENANCE_SCHEMA,
        "status": "fresh" if fresh else str(status),
        "reason": str(reason) if not fresh else "ok",
        "face_count": int(len(level.faces)),
        "vertex_count": int(len(level.vertices_unit)),
        "topology_sha256": face_topology_fingerprint(level),
        "includes_topology_edits": bool(includes_topology_edits),
        "generated_face_count": (
            int(np.count_nonzero(provenance != FACE_PROVENANCE_SOURCE)) if fresh else 0
        ),
        "origin_counts": counts,
    }


def propagate_face_provenance(
    parent_provenance: object,
    child_parent_face_ids: object,
) -> np.ndarray:
    """Copy origin codes from parent faces to refined child faces.

    Surface refiners must provide one exact parent face ID for every output
    face.  Unknown IDs (including ``-1``) raise instead of silently treating a
    newly created face as exterior.  Linear subdivision can therefore preserve
    closure provenance without geometry heuristics.
    """

    parent = np.asarray(parent_provenance)
    mapping = np.asarray(child_parent_face_ids)
    if parent.ndim != 1 or not np.issubdtype(parent.dtype, np.integer):
        raise ValueError("parent provenance must be a one-dimensional integer array")
    if mapping.ndim != 1 or not np.issubdtype(mapping.dtype, np.integer):
        raise ValueError("child-parent face map must be a one-dimensional integer array")
    if any(int(value) not in KNOWN_FACE_PROVENANCE for value in np.unique(parent)):
        raise ValueError("parent provenance contains an unknown origin code")
    mapping = mapping.astype(np.int64, copy=False)
    if len(mapping) and (
        int(mapping.min()) < 0 or int(mapping.max()) >= len(parent)
    ):
        raise ValueError("child-parent face map references an unknown parent")
    return parent[mapping].astype(np.uint8, copy=True)


def install_face_provenance(
    prepared: PreparedGeometry,
    provenance: object,
    *,
    includes_topology_edits: bool = False,
) -> dict[str, object]:
    """Install a verified final-face mask and refresh its topology record."""

    values = np.asarray(provenance)
    if values.shape != (len(prepared.final.faces),):
        raise ValueError("provenance does not match the final face count")
    if not np.issubdtype(values.dtype, np.integer):
        raise ValueError("provenance must use integer origin codes")
    if any(int(value) not in KNOWN_FACE_PROVENANCE for value in np.unique(values)):
        raise ValueError("provenance contains an unknown origin code")
    prepared.final.face_provenance = values.astype(np.uint8, copy=True)
    record = make_face_provenance_record(
        prepared.final,
        includes_topology_edits=includes_topology_edits,
    )
    assembly = dict(prepared.assembly or {})
    assembly["generated_surface_provenance"] = record
    prepared.assembly = assembly
    return record


def validate_face_provenance(prepared: PreparedGeometry) -> ProvenanceValidation:
    """Validate the final-level provenance and return a fail-closed reason."""

    assembly = prepared.assembly if isinstance(prepared.assembly, Mapping) else {}
    record_value = assembly.get("generated_surface_provenance")
    if not isinstance(record_value, Mapping):
        return ProvenanceValidation(False, "missing_provenance_record", {})
    record = dict(record_value)
    if record.get("schema") != PROVENANCE_SCHEMA:
        return ProvenanceValidation(False, "unsupported_provenance_schema", record)
    if record.get("status") != "fresh":
        return ProvenanceValidation(
            False, str(record.get("reason", "provenance_not_fresh")), record
        )
    if (
        assembly.get("manual_joint_topology_changed")
        or assembly.get("joint_records")
        or assembly.get("manual_joint_records")
    ) and not bool(record.get("includes_topology_edits")):
        return ProvenanceValidation(False, "joint_topology_not_covered", record)
    level = prepared.final
    provenance = np.asarray(level.face_provenance)
    if provenance.shape != (len(level.faces),):
        return ProvenanceValidation(False, "provenance_face_count_mismatch", record)
    if not np.issubdtype(provenance.dtype, np.integer):
        return ProvenanceValidation(False, "provenance_dtype_invalid", record)
    if any(int(value) not in KNOWN_FACE_PROVENANCE for value in np.unique(provenance)):
        return ProvenanceValidation(False, "unknown_face_provenance", record)
    if int(record.get("face_count", -1)) != len(level.faces):
        return ProvenanceValidation(False, "record_face_count_mismatch", record)
    if int(record.get("vertex_count", -1)) != len(level.vertices_unit):
        return ProvenanceValidation(False, "record_vertex_count_mismatch", record)
    if record.get("topology_sha256") != face_topology_fingerprint(level):
        return ProvenanceValidation(False, "topology_fingerprint_mismatch", record)
    if int(record.get("generated_face_count", -1)) != int(
        np.count_nonzero(provenance != FACE_PROVENANCE_SOURCE)
    ):
        return ProvenanceValidation(False, "generated_face_count_mismatch", record)
    return ProvenanceValidation(True, "ok", record)


def _face_neighbors(level: MeshLevel) -> np.ndarray:
    raw = np.asarray(level.neighbors) if level.neighbors is not None else np.empty(0)
    if raw.shape == (len(level.faces), 3) and np.issubdtype(raw.dtype, np.integer):
        neighbors = raw.astype(np.int64, copy=False)
        if not len(neighbors) or (
            int(neighbors.min(initial=-1)) >= -1
            and int(neighbors.max(initial=-1)) < len(level.faces)
        ):
            return neighbors

    faces = np.asarray(level.faces, dtype=np.int64)
    result = np.full((len(faces), 3), -1, dtype=np.int64)
    if not len(faces):
        return result
    edges = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    face_ids = np.tile(np.arange(len(faces), dtype=np.int64), 3)
    slots = np.repeat(np.arange(3, dtype=np.int8), len(faces))
    edges.sort(axis=1)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges = edges[order]
    face_ids = face_ids[order]
    slots = slots[order]
    starts = np.r_[0, 1 + np.flatnonzero(np.any(edges[1:] != edges[:-1], axis=1))]
    ends = np.r_[starts[1:], len(edges)]
    for start, end in zip(starts, ends, strict=True):
        if end - start != 2:
            continue
        left, right = int(face_ids[start]), int(face_ids[start + 1])
        if left == right:
            continue
        result[left, int(slots[start])] = right
        result[right, int(slots[start + 1])] = left
    return result


def build_generated_surface_masks(
    prepared: PreparedGeometry,
    height_mm: float,
    *,
    guard_width_mm: float = 0.8,
    minimum_guard_rings: int = 1,
) -> GeneratedSurfaceMasks:
    """Classify fresh generated faces as exterior guard or hidden interior."""

    face_count = len(prepared.final.faces)
    empty = np.zeros(face_count, dtype=bool)
    validation = validate_face_provenance(prepared)
    if not validation.valid:
        return GeneratedSurfaceMasks(
            generated=empty.copy(),
            guard=empty.copy(),
            hidden=empty.copy(),
            valid=False,
            diagnostic={
                "schema": EXPORT_SCHEMA,
                "status": "skipped",
                "reason": validation.reason,
            },
        )
    if not np.isfinite(height_mm) or float(height_mm) <= 0.0:
        return GeneratedSurfaceMasks(
            generated=empty.copy(),
            guard=empty.copy(),
            hidden=empty.copy(),
            valid=False,
            diagnostic={
                "schema": EXPORT_SCHEMA,
                "status": "skipped",
                "reason": "invalid_height_mm",
            },
        )

    level = prepared.final
    generated = np.asarray(level.face_provenance) != FACE_PROVENANCE_SOURCE
    if not np.any(generated):
        return GeneratedSurfaceMasks(
            generated=generated,
            guard=empty.copy(),
            hidden=empty.copy(),
            valid=True,
            diagnostic={
                "schema": EXPORT_SCHEMA,
                "status": "no_generated_faces",
                "reason": "ok",
                "generated_faces": 0,
                "guard_faces": 0,
                "hidden_faces": 0,
            },
        )

    neighbors = _face_neighbors(level)
    part_ids = np.asarray(level.face_part_ids)
    if part_ids.shape != (face_count,):
        part_ids = np.zeros(face_count, dtype=np.int64)
    else:
        part_ids = part_ids.astype(np.int64, copy=False)
    valid_neighbor = neighbors >= 0
    neighbor_generated = np.zeros(neighbors.shape, dtype=bool)
    same_part = np.zeros(neighbors.shape, dtype=bool)
    neighbor_generated[valid_neighbor] = generated[neighbors[valid_neighbor]]
    owner_parts = np.broadcast_to(part_ids[:, None], neighbors.shape)
    same_part[valid_neighbor] = (
        owner_parts[valid_neighbor] == part_ids[neighbors[valid_neighbor]]
    )
    exterior_neighbor = valid_neighbor & same_part & ~neighbor_generated
    seeds = generated & np.any(exterior_neighbor, axis=1)

    guard = seeds.copy()
    frontier = seeds.copy()
    for _ in range(max(0, int(minimum_guard_rings))):
        expanded = np.zeros(face_count, dtype=bool)
        for slot in range(3):
            selected = frontier & (neighbors[:, slot] >= 0)
            candidate = neighbors[selected, slot]
            candidate = candidate[
                generated[candidate] & (part_ids[candidate] == part_ids[selected])
            ]
            expanded[candidate] = True
        expanded &= ~guard
        guard |= expanded
        frontier = expanded
        if not np.any(frontier):
            break

    width = max(0.0, float(guard_width_mm))
    if width > 0.0 and np.any(seeds):
        centroids = (
            np.asarray(level.vertices_unit, dtype=np.float64)[
                np.asarray(level.faces, dtype=np.int64)
            ].mean(axis=1)
            * float(height_mm)
        )
        distances = np.full(face_count, np.inf, dtype=np.float64)
        seed_ids = np.flatnonzero(seeds)
        distances[seed_ids] = 0.0
        queue: list[tuple[float, int]] = [(0.0, int(value)) for value in seed_ids]
        heapq.heapify(queue)
        while queue:
            distance, face_id = heapq.heappop(queue)
            if distance != float(distances[face_id]) or distance > width:
                continue
            for neighbor_raw in neighbors[face_id]:
                neighbor = int(neighbor_raw)
                if (
                    neighbor < 0
                    or not generated[neighbor]
                    or part_ids[neighbor] != part_ids[face_id]
                ):
                    continue
                candidate_distance = distance + float(
                    np.linalg.norm(centroids[neighbor] - centroids[face_id])
                )
                if candidate_distance <= width and candidate_distance < distances[neighbor]:
                    distances[neighbor] = candidate_distance
                    heapq.heappush(queue, (candidate_distance, neighbor))
        guard |= generated & (distances <= width)

    hidden = generated & ~guard
    return GeneratedSurfaceMasks(
        generated=generated,
        guard=guard,
        hidden=hidden,
        valid=True,
        diagnostic={
            "schema": EXPORT_SCHEMA,
            "status": "ready",
            "reason": "ok",
            "generated_faces": int(np.count_nonzero(generated)),
            "guard_faces": int(np.count_nonzero(guard)),
            "hidden_faces": int(np.count_nonzero(hidden)),
            "boundary_seed_faces": int(np.count_nonzero(seeds)),
            "guard_width_mm": width,
            "minimum_guard_rings": int(max(0, minimum_guard_rings)),
        },
    )


def _protection_mask(value: object, face_count: int) -> np.ndarray:
    if value is None:
        return np.zeros(face_count, dtype=bool)
    raw = np.asarray(value)
    if raw.shape != (face_count,):
        return np.zeros(face_count, dtype=bool)
    if raw.dtype == np.bool_:
        return raw.astype(bool, copy=True)
    if np.issubdtype(raw.dtype, np.integer):
        return raw >= 0
    return np.zeros(face_count, dtype=bool)


def existing_tree_face_mask(prepared: PreparedGeometry) -> np.ndarray:
    """Return root faces carrying an explicit adaptive/manual paint tree."""

    result = np.zeros(len(prepared.final.faces), dtype=bool)
    store = getattr(prepared, "_hotfix_subtriangle_paint", None)
    if not isinstance(store, Mapping):
        return result
    for value in store:
        try:
            face_id = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= face_id < len(result):
            result[face_id] = True
    return result


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float64)
    linear = np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )
    # Keep this matrix identical to engine.srgb_to_lab.  Written explicitly
    # here to avoid a circular dependency from the public helper into engine.
    xyz = linear @ np.asarray(
        [
            [0.4124564, 0.2126729, 0.0193339],
            [0.3575761, 0.7151522, 0.1191920],
            [0.1804375, 0.0721750, 0.9503041],
        ]
    )
    xyz /= np.asarray([0.95047, 1.0, 1.08883])
    delta = 6.0 / 29.0
    f = np.where(
        xyz > delta**3,
        np.cbrt(xyz),
        xyz / (3.0 * delta**2) + 4.0 / 29.0,
    )
    return np.column_stack(
        (
            116.0 * f[:, 1] - 16.0,
            500.0 * (f[:, 0] - f[:, 1]),
            200.0 * (f[:, 1] - f[:, 2]),
        )
    )


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    if not len(values):
        return 0.0
    order = np.argsort(values)
    sorted_values = values[order]
    cumulative = np.cumsum(weights[order])
    target = float(quantile) * max(float(cumulative[-1]), 1e-12)
    return float(sorted_values[min(int(np.searchsorted(cumulative, target)), len(values) - 1)])


def _representative_states(
    level: MeshLevel,
    indices: np.ndarray,
    generated: np.ndarray,
    tree_mask: np.ndarray,
    height_mm: float,
) -> dict[int, int]:
    neighbors = _face_neighbors(level)
    faces = np.asarray(level.faces, dtype=np.int64)
    vertices_mm = np.asarray(level.vertices_unit, dtype=np.float64) * float(height_mm)
    part_ids = np.asarray(level.face_part_ids)
    if part_ids.shape != (len(faces),):
        part_ids = np.zeros(len(faces), dtype=np.int64)
    else:
        part_ids = part_ids.astype(np.int64, copy=False)
    edge_vertices = (
        faces[:, [0, 1]],
        faces[:, [1, 2]],
        faces[:, [2, 0]],
    )
    weights_by_part: dict[int, np.ndarray] = {}
    for slot, edge in enumerate(edge_vertices):
        neighbor = neighbors[:, slot]
        valid = generated & (neighbor >= 0)
        if not np.any(valid):
            continue
        selected = np.flatnonzero(valid)
        other = neighbor[selected]
        keep = (
            ~generated[other]
            & ~tree_mask[other]
            & (part_ids[selected] == part_ids[other])
        )
        selected = selected[keep]
        other = other[keep]
        if not len(selected):
            continue
        lengths = np.linalg.norm(
            vertices_mm[edge[selected, 1]] - vertices_mm[edge[selected, 0]],
            axis=1,
        )
        for part_id in np.unique(part_ids[selected]):
            local = part_ids[selected] == part_id
            weights = weights_by_part.setdefault(
                int(part_id), np.zeros(PALETTE_STATE_COUNT, dtype=np.float64)
            )
            weights += np.bincount(
                indices[other[local]],
                weights=lengths[local],
                minlength=PALETTE_STATE_COUNT,
            )[:PALETTE_STATE_COUNT]

    result: dict[int, int] = {}
    areas = np.asarray(level.areas_unit, dtype=np.float64) * float(height_mm) ** 2
    for part_id in np.unique(part_ids[generated]):
        part = int(part_id)
        weights = weights_by_part.get(part)
        if weights is not None and float(weights.sum()) > 0.0:
            result[part] = int(np.argmax(weights))
            continue
        exterior = (part_ids == part) & ~generated & ~tree_mask
        if not np.any(exterior):
            exterior = (part_ids == part) & ~tree_mask
        if not np.any(exterior):
            exterior = part_ids == part
        fallback = np.bincount(
            indices[exterior],
            weights=areas[exterior],
            minlength=PALETTE_STATE_COUNT,
        )[:PALETTE_STATE_COUNT]
        result[part] = int(np.argmax(fallback)) if float(fallback.sum()) > 0.0 else 0
    return result


def optimize_generated_hidden_colors(
    prepared: PreparedGeometry,
    colors: ColorResult,
    height_mm: float,
    *,
    manual_overrides: object = None,
    guard_width_mm: float = 0.8,
    minimum_guard_rings: int = 1,
) -> GeneratedSurfaceColorResult:
    """Collapse untouched hidden generated faces to one state per part.

    Geometry, face order, guard faces, explicit manual assignments, and
    existing adaptive paint trees remain untouched.  Invalid or stale
    provenance returns the original colour object with a diagnostic.
    """

    level = prepared.final
    face_count = len(level.faces)
    masks = build_generated_surface_masks(
        prepared,
        height_mm,
        guard_width_mm=guard_width_mm,
        minimum_guard_rings=minimum_guard_rings,
    )
    allowed = np.ones(face_count, dtype=bool)
    collapsed = np.zeros(face_count, dtype=bool)
    indices_raw = np.asarray(colors.palette_indices)
    target_raw = np.asarray(colors.target_face_rgb)
    tone_vertex = np.asarray(colors.tone_vertex_rgb)
    if (
        not masks.valid
        or indices_raw.shape != (face_count,)
        or target_raw.shape != (face_count, 3)
        or tone_vertex.shape != (len(level.vertices_unit), 3)
    ):
        diagnostic = dict(masks.diagnostic)
        if masks.valid:
            diagnostic.update(status="skipped", reason="invalid_color_result")
        return GeneratedSurfaceColorResult(colors, masks, allowed, collapsed, diagnostic)

    manual_mask = _protection_mask(manual_overrides, face_count)
    tree_mask = existing_tree_face_mask(prepared)
    eligible = masks.hidden & ~manual_mask & ~tree_mask
    if not np.any(eligible):
        diagnostic = {
            **masks.diagnostic,
            "status": "no_eligible_hidden_faces",
            "collapsed_faces": 0,
            "manual_protected_faces": int(np.count_nonzero(masks.hidden & manual_mask)),
            "tree_protected_faces": int(np.count_nonzero(masks.hidden & tree_mask)),
            "representative_states": [],
        }
        return GeneratedSurfaceColorResult(colors, masks, allowed, collapsed, diagnostic)

    indices = indices_raw.astype(np.int64, copy=True)
    target = target_raw.astype(np.float64, copy=True)
    part_ids = np.asarray(level.face_part_ids)
    if part_ids.shape != (face_count,):
        part_ids = np.zeros(face_count, dtype=np.int64)
    else:
        part_ids = part_ids.astype(np.int64, copy=False)
    representative = _representative_states(
        level, indices, masks.generated, tree_mask, float(height_mm)
    )
    representative_records: list[dict[str, int]] = []
    for part_id, state in sorted(representative.items()):
        selected = eligible & (part_ids == int(part_id))
        if not np.any(selected):
            continue
        state_faces = (part_ids == int(part_id)) & (indices == int(state))
        if not np.any(state_faces):
            # The representative is always derived from a current part face;
            # this guard keeps a malformed colour result fail-closed.
            continue
        state_rgb = target[np.flatnonzero(state_faces)[0]]
        indices[selected] = int(state)
        target[selected] = state_rgb
        collapsed |= selected
        representative_records.append(
            {
                "part_id": int(part_id),
                "state": int(state),
                "collapsed_faces": int(np.count_nonzero(selected)),
            }
        )

    allowed[collapsed] = False
    tone_face_rgb = tone_vertex[np.asarray(level.faces, dtype=np.int64)].mean(axis=1)
    delta_e = np.linalg.norm(_srgb_to_lab(tone_face_rgb) - _srgb_to_lab(target), axis=1)
    areas = np.asarray(level.areas_unit, dtype=np.float64) * float(height_mm) ** 2
    counts = np.bincount(indices, minlength=PALETTE_STATE_COUNT)[:PALETTE_STATE_COUNT]
    area_by_state = np.bincount(
        indices, weights=areas, minlength=PALETTE_STATE_COUNT
    )[:PALETTE_STATE_COUNT]
    fractions = area_by_state / max(float(area_by_state.sum()), 1e-12)

    metrics: list[dict[str, Any]] = []
    previous_by_part = {
        int(value.get("part_id", -1)): dict(value)
        for value in colors.part_metrics
        if isinstance(value, Mapping)
    }
    total_area = max(float(areas.sum()), 1e-12)
    for part_id in np.unique(part_ids):
        selected = part_ids == int(part_id)
        if not np.any(selected):
            continue
        weights = areas[selected]
        local_delta = delta_e[selected]
        metric = previous_by_part.get(int(part_id), {})
        metric.update(
            {
                "part_id": int(part_id),
                "face_count": int(np.count_nonzero(selected)),
                "surface_area_fraction": float(weights.sum() / total_area),
                "area_weighted_delta_e76_mean": float(
                    np.average(local_delta, weights=weights)
                ),
                "area_weighted_delta_e76_p90": _weighted_quantile(
                    local_delta, weights, 0.90
                ),
            }
        )
        metrics.append(metric)

    optimized = replace(
        colors,
        palette_indices=indices.astype(indices_raw.dtype, copy=False),
        target_face_rgb=target,
        delta_e=delta_e,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=float(fractions[_PINK_STATES].sum()),
        part_metrics=metrics,
    )
    diagnostic = {
        **masks.diagnostic,
        "status": "collapsed",
        "collapsed_faces": int(np.count_nonzero(collapsed)),
        "manual_protected_faces": int(np.count_nonzero(masks.hidden & manual_mask)),
        "tree_protected_faces": int(np.count_nonzero(masks.hidden & tree_mask)),
        "representative_states": representative_records,
    }
    return GeneratedSurfaceColorResult(
        optimized, masks, allowed, collapsed, diagnostic
    )


def attach_generated_surface_export_context(
    prepared: PreparedGeometry,
    result: GeneratedSurfaceColorResult,
) -> None:
    """Publish diagnostics and the adaptive eligibility mask on PreparedGeometry."""

    setattr(
        prepared,
        ADAPTIVE_ALLOWED_MASK_ATTRIBUTE,
        np.asarray(result.adaptive_allowed_mask, dtype=bool).copy(),
    )
    setattr(prepared, EXPORT_DIAGNOSTICS_ATTRIBUTE, dict(result.diagnostic))


def constrain_adaptive_allowed_mask(
    prepared: PreparedGeometry,
    allowed_mask: object,
) -> np.ndarray:
    """AND an adaptive-shading eligibility mask with hidden-face protection.

    This is the stable integration point for ``final_shading_hotfix``.  A
    missing or stale context leaves the caller's mask unchanged; a malformed
    stored mask raises so a packaging/integration error cannot re-enable
    generated hidden faces silently.
    """

    allowed = np.asarray(allowed_mask)
    face_count = len(prepared.final.faces)
    if allowed.shape != (face_count,) or allowed.dtype != np.bool_:
        raise ValueError("adaptive allowed mask must be bool[final_face_count]")
    generated_allowed = getattr(
        prepared, ADAPTIVE_ALLOWED_MASK_ATTRIBUTE, None
    )
    if generated_allowed is None:
        return allowed.copy()
    generated_allowed = np.asarray(generated_allowed)
    if (
        generated_allowed.shape != (face_count,)
        or generated_allowed.dtype != np.bool_
    ):
        raise ValueError("stored generated-surface allowed mask is stale")
    return allowed & generated_allowed


__all__ = [
    "ADAPTIVE_ALLOWED_MASK_ATTRIBUTE",
    "EXPORT_DIAGNOSTICS_ATTRIBUTE",
    "EXPORT_SCHEMA",
    "FACE_PROVENANCE_LOCAL_CAP",
    "FACE_PROVENANCE_PLANAR_CAP",
    "FACE_PROVENANCE_SOURCE",
    "FACE_PROVENANCE_VOLUME_INTERFACE",
    "GeneratedSurfaceColorResult",
    "GeneratedSurfaceMasks",
    "ProvenanceValidation",
    "attach_generated_surface_export_context",
    "build_generated_surface_masks",
    "constrain_adaptive_allowed_mask",
    "decode_face_ranges",
    "derive_part_face_provenance",
    "encode_face_ranges",
    "existing_tree_face_mask",
    "face_topology_fingerprint",
    "install_face_provenance",
    "make_face_provenance_record",
    "optimize_generated_hidden_colors",
    "propagate_face_provenance",
    "validate_face_provenance",
]
