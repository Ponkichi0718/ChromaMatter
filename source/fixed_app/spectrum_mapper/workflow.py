from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from .engine import (
    INDIVIDUAL_SHARED_INTERFACE_SCHEMA,
    _trusted_part_pre_qem_face_counts,
    _trusted_part_source_face_limits,
    _trusted_part_warning_policies,
    apply_palette_overrides,
    apply_palette_overrides_parts,
    edge_topology,
    emit,
    face_neighbors_partial,
    make_report,
    recolor_level,
    recolor_level_parts,
    signed_volume,
    triangle_areas,
    write_3mf_atomic,
    write_guide,
    write_vertex_color_obj,
)
from .generated_surface_color import (
    FACE_PROVENANCE_LOCAL_CAP,
    FACE_PROVENANCE_PLANAR_CAP,
    FACE_PROVENANCE_SOURCE,
    attach_generated_surface_export_context,
    make_face_provenance_record,
    optimize_generated_hidden_colors,
    validate_face_provenance,
)
from .filament_materials import generic_filament_profile
from .models import (
    AppSettings,
    ExportResult,
    MeshLevel,
    PaletteSettings,
    PreparedGeometry,
    ProgressCallback,
)
from .mixer import black_output_ratio_preset
from .parts import plan_palette_groups, resolve_part_palette_settings


def _safe_part_filename(value: str, index: int) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value)).strip(" ._")
    if not cleaned:
        cleaned = f"part_{index + 1}"
    return f"{index + 1:02d}_{cleaned[:80]}"


def _extract_level_part(
    level: MeshLevel,
    part_id: int,
    source_part_vertex_counts: tuple[int, ...] | None = None,
) -> tuple[MeshLevel, np.ndarray, np.ndarray]:
    face_part_ids = np.asarray(level.face_part_ids)
    selected = np.flatnonzero(face_part_ids == int(part_id))
    if not len(selected):
        raise ValueError(f"空のパーツは出力できません: {part_id + 1}")
    source_faces = np.asarray(level.faces[selected], dtype=np.int32)
    used = np.unique(source_faces.reshape(-1))
    local_faces = np.searchsorted(used, source_faces).astype(np.int32)
    source_vertex_id_map = np.empty(0, dtype=np.int64)
    if (
        source_part_vertex_counts is not None
        and len(source_part_vertex_counts) == len(level.part_keys)
        and all(
            _is_plain_int(value) and int(value) >= 0
            for value in source_part_vertex_counts
        )
        and sum(int(value) for value in source_part_vertex_counts)
        == len(level.vertices_unit)
    ):
        source_vertex_count = int(source_part_vertex_counts[part_id])
        source_vertex_offset = sum(
            int(value) for value in source_part_vertex_counts[:part_id]
        )
        source_vertex_stop = source_vertex_offset + source_vertex_count
        if bool(
            source_vertex_count > 0
            and np.all(used >= source_vertex_offset)
            and np.all(used < source_vertex_stop)
        ):
            source_vertex_id_map = np.full(
                source_vertex_count,
                -1,
                dtype=np.int64,
            )
            source_vertex_id_map[used - source_vertex_offset] = np.arange(
                len(used),
                dtype=np.int64,
            )
    vertices = np.asarray(level.vertices_unit[used], dtype=np.float64).copy()
    minimum = vertices.min(axis=0)
    maximum = vertices.max(axis=0)
    vertices[:, 0] -= (minimum[0] + maximum[0]) * 0.5
    vertices[:, 1] -= (minimum[1] + maximum[1]) * 0.5
    vertices[:, 2] -= minimum[2]
    colors = np.asarray(level.vertex_colors[used], dtype=np.float64)
    source_provenance = np.asarray(level.face_provenance)
    face_provenance = (
        source_provenance[selected].astype(np.uint8, copy=True)
        if source_provenance.shape == (len(level.faces),)
        else np.empty(0, dtype=np.uint8)
    )
    name = level.part_names[part_id]
    key = level.part_keys[part_id]
    return (
        MeshLevel(
            vertices_unit=vertices,
            faces=local_faces,
            vertex_colors=colors,
            areas_unit=triangle_areas(vertices, local_faces),
            neighbors=face_neighbors_partial(local_faces, len(vertices)),
            face_part_ids=np.zeros(len(local_faces), dtype=np.int16),
            face_provenance=face_provenance,
            part_names=(name,),
            part_keys=(key,),
        ),
        selected,
        source_vertex_id_map,
    )


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _part_vertex_counts_for_level(
    prepared: PreparedGeometry,
    level: MeshLevel,
    stats_key: str,
) -> tuple[int, ...] | None:
    stats = prepared.part_stats
    if not (
        isinstance(stats, list)
        and len(stats) == len(level.part_keys)
        and all(isinstance(value, Mapping) for value in stats)
    ):
        return None
    values = tuple(value.get(stats_key) for value in stats)
    if not (
        all(_is_plain_int(value) and int(value) >= 0 for value in values)
        and sum(int(value) for value in values) == len(level.vertices_unit)
    ):
        return None
    return tuple(int(value) for value in values)


def _project_normalization_summary(
    parent_summary: Mapping[str, object],
    record: Mapping[str, object],
    stats: Mapping[str, object],
) -> dict[str, object]:
    """Rebuild the additive normalization summary for one selected part."""

    result = copy.deepcopy(dict(parent_summary))
    result.update(
        {
            "attempted_parts": 1,
            "applied_parts": 1,
            "rejected_parts": 0,
        }
    )
    for key in (
        "source_vertices",
        "output_vertices",
        "exact_coordinate_vertex_merges",
        "collapsed_only_source_vertices",
        "input_unreferenced_vertices",
        "sector_split_vertices",
        "net_vertex_reduction",
        "removed_collapsed_faces",
    ):
        value = record.get(key)
        if _is_plain_int(value):
            result[key] = int(value)
    for summary_key, stats_key in (
        ("component_cleanup_removed_vertices", "component_cleanup_removed_vertices"),
        ("component_cleanup_removed_faces", "component_cleanup_removed_faces"),
    ):
        value = stats.get(stats_key)
        if _is_plain_int(value):
            result[summary_key] = int(value)
    return result


def _project_individual_part_provenance(
    prepared: PreparedGeometry,
    part_id: int,
    stats: Mapping[str, object],
    source_vertex_id_map: np.ndarray,
) -> tuple[dict[str, object], str]:
    """Project a complete live multipart proof to one local part.

    An individual 3MF renumbers its only object to part ``0``.  The proof
    records produced during preparation are indexed by the parent assembly,
    so merely nesting the parent metadata makes every part after the first
    fail closed.  This routine performs a narrow, atomic projection of the
    live in-memory proof.

    Shared interfaces are represented by the engine's dedicated one-sided
    projection schema.  The original two source part IDs remain recorded, but
    only the selected side's cap range and boundary vertex IDs are rebased to
    the child object's local ID space.  Any incomplete parent proof disables
    the whole projection so the normal strict-zero validator remains in force.
    """

    parent = prepared.assembly or {}
    parent_count = len(prepared.final.part_keys)
    if not (
        isinstance(parent, Mapping)
        and parent_count > 0
        and 0 <= int(part_id) < parent_count
    ):
        return {}, "invalid_parent_layout"

    provenance_value = parent.get("multipart_self_intersection_provenance")
    normalization_value = parent.get("multipart_topology_normalization")
    summary_value = parent.get("multipart_topology_normalization_summary")
    repair_value = parent.get("repair_records")
    if not (
        isinstance(provenance_value, Mapping)
        and isinstance(normalization_value, list)
        and isinstance(summary_value, Mapping)
        and isinstance(repair_value, list)
    ):
        return {}, "parent_proof_missing"

    provenance = copy.deepcopy(dict(provenance_value))
    parts_value = provenance.get("parts")
    if not (
        provenance.get("eligible") is True
        and provenance.get("part_count") == parent_count
        and provenance.get("joint_topology_changed") is False
        and isinstance(parts_value, list)
        and len(parts_value) == parent_count
        and all(isinstance(value, Mapping) for value in parts_value)
        and all(
            value.get("part_id") == index
            and value.get("record_valid") is True
            for index, value in enumerate(parts_value)
        )
    ):
        return {}, "parent_multipart_proof_incomplete"

    policies = {str(value.get("warning_policy", "")) for value in parts_value}
    expected_parent_policy = (
        next(iter(policies))
        if len(policies) == 1
        else "normalized_multipart_part_specific_warning"
    )
    expected_parent_simplification = any(
        value.get("qem_warning_eligible") is True for value in parts_value
    )
    expected_parent_geometry_preserved = all(
        value.get("source_triangle_geometry_preserved") is True
        for value in parts_value
    )
    expected_parent_ancestry = all(
        value.get("source_triangle_ancestry_proven") is True
        for value in parts_value
    )
    if not (
        policies
        and "" not in policies
        and provenance.get("warning_policy") == expected_parent_policy
        and provenance.get("simplification_applied")
        is expected_parent_simplification
        and provenance.get("source_triangle_geometry_preserved")
        is expected_parent_geometry_preserved
        and provenance.get("source_triangle_ancestry_proven")
        is expected_parent_ancestry
    ):
        return {}, "parent_multipart_aggregate_mismatch"

    if not (
        len(normalization_value) == parent_count
        and all(isinstance(value, Mapping) for value in normalization_value)
        and all(
            value.get("part_id") == index
            and value.get("status") == "applied"
            for index, value in enumerate(normalization_value)
        )
        and summary_value.get("eligible") is True
        and summary_value.get("attempted_parts") == parent_count
        and summary_value.get("applied_parts") == parent_count
        and summary_value.get("rejected_parts") == 0
    ):
        return {}, "parent_normalization_proof_incomplete"

    face_part_ids = np.asarray(prepared.final.face_part_ids)
    live_face_provenance = np.asarray(prepared.final.face_provenance)
    trusted_source_limits = _trusted_part_source_face_limits(
        prepared,
        face_part_ids,
        parent_count,
    )
    trusted_pre_qem_counts = _trusted_part_pre_qem_face_counts(
        prepared,
        trusted_source_limits,
        parent_count,
    )
    trusted_warning_policies = _trusted_part_warning_policies(
        prepared,
        trusted_source_limits,
        trusted_pre_qem_counts,
        parent_count,
    )
    if (
        trusted_source_limits is None
        or trusted_pre_qem_counts is None
        or trusted_warning_policies is None
        or face_part_ids.shape != (len(prepared.final.faces),)
        or live_face_provenance.shape != (len(prepared.final.faces),)
    ):
        return {}, "parent_live_provenance_incomplete"

    parent_face_counts = tuple(
        int(np.count_nonzero(face_part_ids == index))
        for index in range(parent_count)
    )
    parent_vertex_counts: list[int] = []
    if not (
        isinstance(prepared.part_stats, list)
        and len(prepared.part_stats) == parent_count
        and all(isinstance(value, Mapping) for value in prepared.part_stats)
    ):
        return {}, "parent_vertex_layout_incomplete"
    for index, part_stats in enumerate(prepared.part_stats):
        final_vertices = part_stats.get("final_vertices")
        if not (
            _is_plain_int(final_vertices)
            and int(final_vertices) > 0
            and part_stats.get("id") == index
        ):
            return {}, "parent_vertex_layout_incomplete"
        parent_vertex_counts.append(int(final_vertices))
    if sum(parent_vertex_counts) != len(prepared.final.vertices_unit):
        return {}, "parent_vertex_layout_incomplete"

    parent_vertex_offsets = np.cumsum(
        np.asarray([0, *parent_vertex_counts], dtype=np.int64)
    )
    final_faces = np.asarray(prepared.final.faces, dtype=np.int64)
    if final_faces.shape != (len(prepared.final.faces), 3):
        return {}, "parent_vertex_layout_incomplete"
    parent_referenced_vertex_ids: list[set[int]] = []
    for index in range(parent_count):
        local_faces = final_faces[face_part_ids == index]
        if (
            not len(local_faces)
            or int(local_faces.min()) < int(parent_vertex_offsets[index])
            or int(local_faces.max())
            >= int(parent_vertex_offsets[index + 1])
        ):
            return {}, "parent_vertex_layout_incomplete"
        parent_referenced_vertex_ids.append(
            set(
                (
                    local_faces.reshape(-1) - parent_vertex_offsets[index]
                ).astype(int).tolist()
            )
        )

    source_vertex_id_map = np.asarray(source_vertex_id_map, dtype=np.int64)
    if source_vertex_id_map.shape != (parent_vertex_counts[part_id],):
        return {}, "selected_vertex_rebase_unavailable"

    for index, part_record in enumerate(parts_value):
        if not (
            part_record.get("part_key") == prepared.final.part_keys[index]
            and part_record.get("pre_qem_face_count")
            == trusted_pre_qem_counts[index]
            and part_record.get("post_qem_source_face_count")
            == trusted_source_limits[index]
            and part_record.get("source_face_limit")
            == trusted_source_limits[index]
            and part_record.get("final_face_count") == parent_face_counts[index]
            and part_record.get("warning_policy")
            == trusted_warning_policies[index]
        ):
            return {}, "parent_live_provenance_mismatch"

    if not all(isinstance(value, Mapping) for value in repair_value):
        return {}, "parent_repair_proof_malformed"
    repair_records = [copy.deepcopy(dict(value)) for value in repair_value]
    if any(
        str(value.get("method", ""))
        not in {
            "strict_planar_unmatched_boundary_caps",
            "partitioned_shared_caps",
            "already_watertight",
        }
        for value in repair_records
    ):
        return {}, "parent_repair_method_unsupported"

    solid_records = [
        value
        for value in repair_records
        if value.get("method")
        in {"partitioned_shared_caps", "already_watertight"}
    ]
    local_records = [
        value
        for value in repair_records
        if value.get("method") == "strict_planar_unmatched_boundary_caps"
    ]
    if len(solid_records) != 1 or len(local_records) > 1:
        return {}, "parent_repair_proof_incomplete"
    solid = solid_records[0]
    solid_method = str(solid.get("method", ""))
    interfaces_value = solid.get("interfaces")
    interfaces = (
        [copy.deepcopy(dict(value)) for value in interfaces_value]
        if isinstance(interfaces_value, list)
        and all(isinstance(value, Mapping) for value in interfaces_value)
        else []
    )
    strict_parts = solid.get("parts")
    if not (
        interfaces_value == interfaces
        and solid_method in {"partitioned_shared_caps", "already_watertight"}
        and solid.get("matched_seams") == len(interfaces)
        and solid.get("source_triangle_coordinates_preserved") is True
        and solid.get("source_parts") == parent_count
        and solid.get("output_parts") == parent_count
        and isinstance(strict_parts, list)
        and len(strict_parts) == parent_count
        and all(isinstance(value, Mapping) for value in strict_parts)
        and all(
            value.get("part_id") == index
            for index, value in enumerate(strict_parts)
        )
    ):
        return {}, "parent_solid_proof_incomplete"
    if solid_method == "already_watertight" and interfaces:
        return {}, "parent_solid_proof_incomplete"

    for index, (strict_part, part_record) in enumerate(
        zip(strict_parts, parts_value, strict=True)
    ):
        strict_ids = strict_part.get("self_intersecting_face_ids")
        if not (
            _is_plain_int(strict_part.get("added_faces"))
            and int(strict_part["added_faces"]) >= 0
            and strict_part.get("self_intersection_source_face_limit")
            == trusted_source_limits[index]
            and strict_part.get("self_intersections")
            == part_record.get("self_intersecting_faces")
            and isinstance(strict_ids, list)
            and strict_ids == part_record.get("self_intersecting_face_ids")
            and strict_part.get("self_intersection_face_limit")
            == part_record.get("self_intersection_face_limit")
            and strict_part.get("self_intersection_area_fraction_limit")
            == part_record.get("self_intersection_area_fraction_limit")
            and strict_part.get("self_intersection_warning")
            is part_record.get("self_intersection_warning")
            and strict_part.get("self_intersection_policy")
            == (
                trusted_warning_policies[index]
                if part_record.get("self_intersection_warning") is True
                else "strict_zero"
            )
            and strict_part.get("source_triangle_ancestry_proven")
            is part_record.get("source_triangle_ancestry_proven")
            and strict_part.get("self_intersection_inherited_from_source")
            is part_record.get("self_intersection_inherited_from_source")
        ):
            return {}, "parent_strict_part_mismatch"

    selected_loops: list[dict[str, object]] = []
    local_cap_ids: list[list[int]] = [[] for _ in range(parent_count)]
    for local_record in local_records:
        loops = local_record.get("loops")
        if not (
            isinstance(loops, list)
            and all(isinstance(value, Mapping) for value in loops)
            and local_record.get("repaired_loop_count") == len(loops)
        ):
            return {}, "parent_local_cap_proof_incomplete"
        for loop in loops:
            loop_part_id = loop.get("part_id")
            added_faces = loop.get("added_faces")
            cap_face_ids = loop.get("cap_face_ids")
            if not (
                _is_plain_int(loop_part_id)
                and 0 <= int(loop_part_id) < parent_count
                and _is_plain_int(added_faces)
                and int(added_faces) > 0
                and isinstance(cap_face_ids, list)
                and len(cap_face_ids) == int(added_faces)
                and all(_is_plain_int(value) for value in cap_face_ids)
                and cap_face_ids
                == list(
                    range(
                        int(cap_face_ids[0]),
                        int(cap_face_ids[0]) + int(added_faces),
                    )
                )
                and loop.get("method") == "strict_planar_local_cap"
                and loop.get("closed_loop") is True
            ):
                return {}, "parent_local_cap_proof_incomplete"
            local_cap_ids[int(loop_part_id)].extend(
                int(value) for value in cap_face_ids
            )
            if int(loop_part_id) == int(part_id):
                projected_loop = copy.deepcopy(dict(loop))
                projected_loop["part_id"] = 0
                selected_loops.append(projected_loop)

    shared_cap_ids: list[list[int]] = [[] for _ in range(parent_count)]
    projected_interfaces: list[dict[str, object]] = []
    for interface in interfaces:
        interface_parts = interface.get("parts")
        cap_faces = interface.get("cap_faces")
        boundary_vertices = interface.get("boundary_vertices")
        ranges = interface.get("cap_face_range_by_part")
        boundary_ids_by_part = interface.get("boundary_vertex_ids_by_part")
        if not (
            solid_method == "partitioned_shared_caps"
            and isinstance(interface_parts, list)
            and len(interface_parts) == 2
            and all(
                _is_plain_int(value) and 0 <= int(value) < parent_count
                for value in interface_parts
            )
            and len(set(int(value) for value in interface_parts)) == 2
            and _is_plain_int(cap_faces)
            and int(cap_faces) > 0
            and _is_plain_int(boundary_vertices)
            and int(boundary_vertices) >= 3
            and isinstance(ranges, Mapping)
            and set(ranges) == {str(int(value)) for value in interface_parts}
            and isinstance(boundary_ids_by_part, Mapping)
            and set(boundary_ids_by_part)
            == {str(int(value)) for value in interface_parts}
            and interface.get("source_triangle_coordinates_preserved") is True
        ):
            return {}, "parent_shared_interface_incomplete"

        projected_range: list[int] | None = None
        projected_boundary_ids: list[int] | None = None
        for source_part_id_value in interface_parts:
            source_part_id = int(source_part_id_value)
            range_value = ranges[str(source_part_id)]
            boundary_ids = boundary_ids_by_part[str(source_part_id)]
            if not (
                isinstance(range_value, list)
                and len(range_value) == 2
                and all(_is_plain_int(value) for value in range_value)
                and 0 <= int(range_value[0]) < int(range_value[1])
                <= parent_face_counts[source_part_id]
                and int(range_value[1]) - int(range_value[0])
                == int(cap_faces)
                and isinstance(boundary_ids, list)
                and len(boundary_ids) == int(boundary_vertices)
                and all(_is_plain_int(value) for value in boundary_ids)
                and len(boundary_ids) == len(set(int(value) for value in boundary_ids))
                and all(
                    0 <= int(value) < parent_vertex_counts[source_part_id]
                    for value in boundary_ids
                )
                and all(
                    int(value) in parent_referenced_vertex_ids[source_part_id]
                    for value in boundary_ids
                )
            ):
                return {}, "parent_shared_interface_incomplete"
            shared_cap_ids[source_part_id].extend(
                range(int(range_value[0]), int(range_value[1]))
            )
            if source_part_id == int(part_id):
                mapped_boundary_ids = [
                    int(source_vertex_id_map[int(value)]) for value in boundary_ids
                ]
                if (
                    any(value < 0 for value in mapped_boundary_ids)
                    or len(mapped_boundary_ids) != len(set(mapped_boundary_ids))
                ):
                    return {}, "selected_boundary_vertex_rebase_failed"
                projected_range = [int(range_value[0]), int(range_value[1])]
                projected_boundary_ids = mapped_boundary_ids

        if int(part_id) in interface_parts:
            if projected_range is None or projected_boundary_ids is None:
                return {}, "selected_shared_interface_incomplete"
            projected_interface = copy.deepcopy(interface)
            projected_interface["individual_projection_schema"] = (
                INDIVIDUAL_SHARED_INTERFACE_SCHEMA
            )
            projected_interface["parts"] = [0]
            projected_interface["source_interface_parts"] = [
                int(value) for value in interface_parts
            ]
            projected_interface["source_part_index"] = int(part_id)
            projected_interface["source_part_key"] = str(
                prepared.final.part_keys[part_id]
            )
            projected_interface["cap_face_range_by_part"] = {
                "0": projected_range
            }
            projected_interface["boundary_vertex_ids_by_part"] = {
                "0": projected_boundary_ids
            }
            outward_by_part = interface.get("outward_normal_by_part")
            if outward_by_part is not None:
                if not (
                    isinstance(outward_by_part, Mapping)
                    and set(outward_by_part)
                    == {str(int(value)) for value in interface_parts}
                ):
                    return {}, "parent_shared_interface_incomplete"
                projected_interface["outward_normal_by_part"] = {
                    "0": copy.deepcopy(outward_by_part[str(part_id)])
                }
            projected_interfaces.append(projected_interface)

    for index in range(parent_count):
        local_provenance = live_face_provenance[face_part_ids == index]
        local_ids = local_cap_ids[index]
        shared_ids = shared_cap_ids[index]
        generated_ids = local_ids + shared_ids
        unique_generated_ids = sorted(set(generated_ids))
        expected_generated_ids = list(
            range(trusted_source_limits[index], parent_face_counts[index])
        )
        if not (
            len(generated_ids) == len(unique_generated_ids)
            and unique_generated_ids == expected_generated_ids
            and int(strict_parts[index]["added_faces"]) == len(shared_ids)
            and np.all(
                local_provenance[: trusted_source_limits[index]]
                == FACE_PROVENANCE_SOURCE
            )
            and all(
                int(local_provenance[value]) == int(FACE_PROVENANCE_LOCAL_CAP)
                for value in local_ids
            )
            and all(
                int(local_provenance[value]) == int(FACE_PROVENANCE_PLANAR_CAP)
                for value in shared_ids
            )
        ):
            return {}, "parent_generated_suffix_mismatch"

    selected_part = copy.deepcopy(dict(parts_value[part_id]))
    selected_part["part_id"] = 0
    for key in (
        "export_coordinate_space",
        "export_vertex_count",
        "export_geometry_sha256",
        "self_intersecting_area_mm2",
        "inherited_source_self_intersecting_area_mm2",
        "self_intersection_source_faces_only",
        "self_intersection_policy",
        "record_valid",
    ):
        selected_part.pop(key, None)
    provenance.pop("export_coordinate_space", None)
    provenance.pop("export_revalidated", None)
    provenance["part_count"] = 1
    provenance["parts"] = [selected_part]
    provenance["warning_policy"] = selected_part.get("warning_policy")
    provenance["simplification_applied"] = bool(
        selected_part.get("qem_warning_eligible") is True
    )
    provenance["source_triangle_geometry_preserved"] = bool(
        selected_part.get("source_triangle_geometry_preserved") is True
    )
    provenance["source_triangle_ancestry_proven"] = bool(
        selected_part.get("source_triangle_ancestry_proven") is True
    )

    normalization_record = copy.deepcopy(dict(normalization_value[part_id]))
    normalization_record["part_id"] = 0
    projected_repairs: list[dict[str, object]] = []
    if selected_loops:
        local_record = copy.deepcopy(local_records[0])
        local_record["loops"] = selected_loops
        local_record["repaired_loop_count"] = len(selected_loops)
        projected_repairs.append(local_record)
    projected_solid = copy.deepcopy(solid)
    projected_strict = copy.deepcopy(dict(strict_parts[part_id]))
    projected_strict["part_id"] = 0
    projected_solid["parts"] = [projected_strict]
    projected_solid["source_parts"] = 1
    projected_solid["output_parts"] = 1
    projected_solid["interfaces"] = projected_interfaces
    projected_solid["matched_seams"] = len(projected_interfaces)
    projected_repairs.append(projected_solid)

    projected = {
        "multipart_self_intersection_provenance": provenance,
        "multipart_topology_normalization": [normalization_record],
        "multipart_topology_normalization_summary": (
            _project_normalization_summary(
                summary_value,
                normalization_record,
                stats,
            )
        ),
        "repair_records": projected_repairs,
    }
    source_stats = parent.get("source_part_stats")
    if (
        isinstance(source_stats, list)
        and len(source_stats) == parent_count
        and all(isinstance(value, Mapping) for value in source_stats)
    ):
        selected_source_stats = copy.deepcopy(dict(source_stats[part_id]))
        if "id" in selected_source_stats:
            selected_source_stats["id"] = 0
        projected["source_part_stats"] = [selected_source_stats]
    return projected, "projected"


def _extract_prepared_part(
    prepared: PreparedGeometry,
    part_id: int,
) -> tuple[PreparedGeometry, np.ndarray]:
    parent_provenance = validate_face_provenance(prepared)
    final, source_face_ids, source_vertex_id_map = _extract_level_part(
        prepared.final,
        part_id,
        _part_vertex_counts_for_level(prepared, prepared.final, "final_vertices"),
    )
    preview, _preview_face_ids, _preview_vertex_id_map = _extract_level_part(
        prepared.preview,
        part_id,
        _part_vertex_counts_for_level(
            prepared,
            prepared.preview,
            "preview_vertices",
        ),
    )
    if not parent_provenance.valid:
        final.face_provenance = np.empty(0, dtype=np.uint8)
    topology = edge_topology(final.faces, len(final.vertices_unit))
    stats = (
        [copy.deepcopy(dict(prepared.part_stats[part_id]))]
        if part_id < len(prepared.part_stats)
        else []
    )
    if stats:
        stats[0]["id"] = 0
    part_provenance_record = make_face_provenance_record(
        final,
        status="fresh" if parent_provenance.valid else "unavailable",
        reason="ok" if parent_provenance.valid else parent_provenance.reason,
        includes_topology_edits=bool(
            parent_provenance.record.get("includes_topology_edits", False)
        ),
    )
    projected_provenance, projection_status = (
        _project_individual_part_provenance(
            prepared,
            part_id,
            stats[0],
            source_vertex_id_map,
        )
        if stats
        else ({}, "part_stats_missing")
    )
    result = PreparedGeometry(
        source=prepared.source,
        final=final,
        preview=preview,
        clean_vertex_count=len(final.vertices_unit),
        clean_face_count=len(final.faces),
        removed_vertices=0,
        removed_faces=0,
        topology=topology,
        source_area_unit=float(final.areas_unit.sum()),
        source_volume_unit=signed_volume(final.vertices_unit, final.faces),
        simplified_area_unit=float(final.areas_unit.sum()),
        simplified_volume_unit=signed_volume(final.vertices_unit, final.faces),
        source_dimensions_unit=np.ptp(final.vertices_unit, axis=0),
        warnings=list(prepared.warnings),
        part_names=final.part_names,
        part_keys=final.part_keys,
        part_stats=stats,
        assembly={
            **projected_provenance,
            "individual_part_export": True,
            "source_part_index": int(part_id),
            "source_parent_part_count": int(len(prepared.final.part_keys)),
            "source_part_key": final.part_keys[0],
            "all_parts_watertight": bool(topology["watertight"]),
            "parent_assembly": copy.deepcopy(prepared.assembly or {}),
            "multipart_provenance_projection": {
                "status": projection_status,
                "source_part_index": int(part_id),
            },
            "generated_surface_provenance": part_provenance_record,
        },
    )
    tree_store = getattr(prepared, "_hotfix_subtriangle_paint", None)
    if isinstance(tree_store, Mapping):
        local_trees: dict[int, object] = {}
        for face_id, tree in tree_store.items():
            try:
                source_face_id = int(face_id)
            except (TypeError, ValueError):
                continue
            position = int(np.searchsorted(source_face_ids, source_face_id))
            if (
                0 <= position < len(source_face_ids)
                and int(source_face_ids[position]) == source_face_id
            ):
                local_trees[position] = tree
        if local_trees:
            result._hotfix_subtriangle_paint = local_trees
    return result, source_face_ids


def optimize_generated_surface_export(
    prepared: PreparedGeometry,
    colors,
    height_mm: float,
    manual_overrides: np.ndarray | None,
):
    """Apply safe hidden-surface colour reduction and publish r8 context."""

    result = optimize_generated_hidden_colors(
        prepared,
        colors,
        height_mm,
        manual_overrides=manual_overrides,
    )
    attach_generated_surface_export_context(prepared, result)
    return result.colors


def _part_export_palette_with_global_output_policy(
    global_palette: PaletteSettings,
    local_palette: PaletteSettings,
) -> PaletteSettings:
    """Apply global output-only policy without replacing a part's own colours.

    Physical colours, display ratios, enabled states and filament product
    references remain local to the part.  An explicit local output-ratio list
    wins; otherwise the global black-output correction is inherited.  Surface
    shell output is enabled when either scope requests it.

    Return the original object when no value changes.  Besides avoiding an
    unnecessary copy, this keeps the legacy OFF/None export path identical.
    """

    output_ratios = local_palette.output_mix_ratios_b
    if output_ratios is None and global_palette.output_mix_ratios_b is not None:
        global_output = list(global_palette.output_mix_ratios_b)
        output_ratios = global_output
        # The GUI's weak-black correction is a semantic preset, not an
        # arbitrary replacement for every part's display recipe.  Recover its
        # selected F1-F4 slot and rebuild it against this part's own primary
        # and secondary ratios so non-black mixes remain local to the part.
        for slot_index in range(4):
            if global_output == black_output_ratio_preset(
                slot_index,
                global_palette.mix_ratios_b,
                global_palette.secondary_mix_ratios_b,
            ):
                output_ratios = black_output_ratio_preset(
                    slot_index,
                    local_palette.mix_ratios_b,
                    local_palette.secondary_mix_ratios_b,
                )
                break
    surface_shell_enabled = bool(
        local_palette.surface_shell_enabled
        or global_palette.surface_shell_enabled
    )
    if (
        output_ratios is local_palette.output_mix_ratios_b
        and surface_shell_enabled == bool(local_palette.surface_shell_enabled)
    ):
        return local_palette

    result = copy.deepcopy(local_palette)
    result.output_mix_ratios_b = (
        None if output_ratios is None else list(output_ratios)
    )
    result.surface_shell_enabled = surface_shell_enabled
    return result


def _write_individual_part_models(
    prepared: PreparedGeometry,
    settings: AppSettings,
    destination: Path,
    manual_overrides: np.ndarray | None,
    progress: ProgressCallback | None,
) -> tuple[Path, ...]:
    palettes = tuple(
        _part_export_palette_with_global_output_policy(
            settings.palette,
            local_palette,
        )
        for local_palette in resolve_part_palette_settings(
            settings, prepared.final
        )
    )
    base_output_dir = destination.with_suffix("").with_name(
        destination.stem + "_parts"
    )
    output_dir = base_output_dir
    suffix = 2
    while output_dir.exists():
        output_dir = base_output_dir.with_name(f"{base_output_dir.name}_{suffix}")
        suffix += 1
    staging_dir = output_dir.with_name(
        f".{output_dir.name}.{uuid.uuid4().hex}.tmp"
    )
    staging_dir.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    manifest_parts: list[dict[str, object]] = []
    part_count = len(prepared.final.part_keys)
    try:
        for part_id, (name, key, palette) in enumerate(
            zip(
                prepared.final.part_names,
                prepared.final.part_keys,
                palettes,
                strict=True,
            )
        ):
            emit(
                progress,
                "part_3mf",
                0.66 + 0.16 * part_id / max(part_count, 1),
                f"パーツ別3MF {part_id + 1}/{part_count}: {name}",
            )
            part_prepared, source_face_ids = _extract_prepared_part(
                prepared, part_id
            )
            part_colors = recolor_level(
                part_prepared.final,
                settings.geometry.height_mm,
                settings.tone,
                palette,
            )
            part_manual_overrides = None
            if manual_overrides is not None:
                part_manual_overrides = np.asarray(manual_overrides)[source_face_ids]
                part_colors = apply_palette_overrides(
                    part_prepared.final,
                    settings.geometry.height_mm,
                    palette,
                    part_colors,
                    part_manual_overrides,
                )
            part_colors = optimize_generated_surface_export(
                part_prepared,
                part_colors,
                settings.geometry.height_mm,
                part_manual_overrides,
            )
            part_path = staging_dir / (
                _safe_part_filename(name, part_id) + "_FullSpectrum.3mf"
            )
            validation = write_3mf_atomic(
                part_path,
                part_prepared,
                part_colors,
                settings.geometry.height_mm,
                palette,
                {},
                False,
            )
            paths.append(part_path)
            manifest_parts.append(
                {
                    "index": int(part_id),
                    "name": name,
                    "key": key,
                    "file": part_path.name,
                    "faces": int(len(part_prepared.final.faces)),
                    "watertight": bool(part_prepared.topology["watertight"]),
                    "sha256": validation.get("sha256"),
                    "physical_filaments": list(palette.physical_hex),
                    "material": palette.material,
                    "physical_filament_refs": AppSettings(
                        palette=palette
                    ).to_dict()["palette"]["physical_filament_refs"],
                }
            )
        manifest = {
            "schema": "tripo-spectrum-mapper.part-exports.v1",
            "source_assembly": str(destination.name),
            "layer_height_mm": 0.08,
            "initial_layer_height_mm": 0.2,
            "support_fixed": False,
            "parts": manifest_parts,
        }
        (staging_dir / "パーツ別3MF_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8-sig",
        )
        staging_dir.replace(output_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return tuple(output_dir / path.name for path in paths)


def _write_individual_only_guide(
    path: Path,
    destination: Path,
    prepared: PreparedGeometry,
    settings: AppSettings,
    part_model_paths: tuple[Path, ...],
) -> None:
    palettes = tuple(
        _part_export_palette_with_global_output_policy(settings.palette, palette)
        for palette in resolve_part_palette_settings(settings, prepared.final)
    )
    rows = "\n".join(
        f"- {model_path.name}: {palette.material} / "
        f"{generic_filament_profile(palette.material)}"
        for model_path, palette in zip(part_model_paths, palettes, strict=True)
    )
    text = f"""ChromaMatter パーツ別3MFの読み込み方
============================================

指定した出力名: {destination.name}

パーツごとに素材が異なるため、複数素材を混在させた統合3MFは作成していません。
次の各ファイルは、同一素材4本だけを使用する独立した印刷ジョブです。

{rows}

1. 使用するパーツ3MFをSnapmaker Orcaで「Open as project / プロジェクトとして開く」で開きます。
2. 3MF内のGenericプロファイルは仮設定です。同じ素材の実スプール用プロファイルへF1～F4を差し替えます。
3. 1つの印刷ジョブにPLA／ABS／PETGを混在させないでください。
4. 通常層0.08 mmを確認し、サポートはモデルごとに設定します。
5. ABSは登録色・実測・色域が少ないため、実機比較チャートで確認し、Snapmaker U1ではTop Coverを使用してください。

ABS／PETGの色予測はβ機能です。実フィラメントの銘柄・ロット・光沢・不透明度で結果が変わります。
"""
    path.write_text(text, encoding="utf-8-sig")


def export_bundle(
    prepared: PreparedGeometry,
    settings: AppSettings,
    destination: Path,
    reference_path: Path | None = None,
    include_vertex_obj: bool = True,
    progress: ProgressCallback | None = None,
    manual_overrides: np.ndarray | None = None,
    force_common_palette: bool = False,
    individual_only: bool = False,
) -> ExportResult:
    """Create the 3MF and all human-readable sidecars for one conversion."""

    destination = Path(destination).with_suffix(".3mf")
    if individual_only and destination.exists():
        raise ValueError(
            "パーツ別のみ出力では既存の統合3MFと同じ名前を使用できません。"
            "古い統合3MFを誤って印刷しないよう、別の出力名を選んでください。"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    stem = destination.with_suffix("")
    preview_path = stem.with_name(stem.name + "_preview.png")
    report_path = stem.with_name(stem.name + "_validation.json")
    guide_path = stem.with_name(stem.name + "_使い方.txt")
    fallback_obj_path = (
        stem.with_name(stem.name + "_vertexcolor.obj") if include_vertex_obj else None
    )

    grouping = plan_palette_groups(settings, prepared.final)
    resolved_materials = {
        palette.material
        for palette in resolve_part_palette_settings(settings, prepared.final)
    }
    if len(resolved_materials) > 1 and force_common_palette:
        raise ValueError(
            "異素材のパーツ設定を全体共通素材へ強制統合できません。"
            "各パーツを素材別の独立3MFとして出力してください。"
        )
    if force_common_palette and individual_only:
        raise ValueError("全体共通3MFとパーツ別のみ出力は同時に指定できません")
    if individual_only and not grouping.requires_separate_jobs:
        raise ValueError("パーツ別のみ出力は複数の基本4色構成がある場合に使用します")
    if grouping.requires_separate_jobs and not (force_common_palette or individual_only):
        if len(resolved_materials) > 1:
            raise ValueError(
                "PLA/ABS/PETGを1つの3MF印刷ジョブへ混在できません。"
                "全体共通素材で出力するか、パーツ別3MFを使用してください。"
            )
        raise ValueError(
            "パーツごとの物理4色が異なるため、U1の1回印刷用3MFにはできません。"
            "全体共通4色で出力するか、パーツ設定を揃えてください。"
        )
    if grouping.one_job or individual_only:
        effective_part_palettes = settings.part_palettes
        print_palette = (
            settings.palette
            if individual_only
            else resolve_part_palette_settings(settings, prepared.final)[0]
        )
    else:
        effective_part_palettes = {}
        print_palette = settings.palette

    emit(progress, "color", 0.04, "最終メッシュへ色を割り当てています")
    final_colors = recolor_level_parts(
        prepared.final,
        settings.geometry.height_mm,
        settings.tone,
        settings.palette,
        effective_part_palettes,
    )
    if manual_overrides is not None:
        final_colors = apply_palette_overrides_parts(
            prepared.final,
            settings.geometry.height_mm,
            settings.palette,
            effective_part_palettes,
            final_colors,
            manual_overrides,
        )
    final_colors = optimize_generated_surface_export(
        prepared,
        final_colors,
        settings.geometry.height_mm,
        manual_overrides,
    )
    if individual_only:
        validation: dict[str, object] = {
            "valid": True,
            "combined_model_written": False,
            "individual_only": True,
            "materials": sorted(resolved_materials),
        }
    else:
        emit(progress, "3mf", 0.16, "Snapmaker Orca用3MFを書き出しています")
        validation = write_3mf_atomic(
            destination,
            prepared,
            final_colors,
            settings.geometry.height_mm,
            print_palette,
            settings.part_palettes,
            bool(grouping.requires_separate_jobs and force_common_palette),
        )

    part_model_paths: tuple[Path, ...] = ()
    if (
        (individual_only or bool(settings.geometry.export_individual_parts))
        and len(prepared.final.part_keys) > 1
    ):
        part_model_paths = _write_individual_part_models(
            prepared,
            settings,
            destination,
            manual_overrides,
            progress,
        )
        validation["individual_part_models"] = [
            str(path) for path in part_model_paths
        ]

    if fallback_obj_path is not None:
        emit(progress, "obj", 0.76, "予備の頂点カラーOBJを書き出しています")
        write_vertex_color_obj(
            fallback_obj_path,
            prepared,
            final_colors,
            settings.geometry.height_mm,
        )

    emit(progress, "report", 0.86, "検証レポートを作成しています")
    report = make_report(
        prepared,
        final_colors,
        settings.geometry.height_mm,
        settings.tone,
        print_palette,
        validation,
    )
    self_intersection_warning = {
        "parts": int(
            validation.get("self_intersection_warning_parts", 0) or 0
        ),
        "policy": str(
            validation.get(
                "self_intersection_warning_policy", "strict_zero"
            )
        ),
        "policies": list(
            validation.get("self_intersection_warning_policies", []) or []
        ),
        "faces": int(
            validation.get("self_intersection_warning_faces", 0) or 0
        ),
        "area_mm2": float(
            validation.get("self_intersection_warning_area", 0.0) or 0.0
        ),
        "maximum_area_fraction": float(
            validation.get(
                "self_intersection_warning_max_area_fraction", 0.0
            )
            or 0.0
        ),
        "orca_preview_required": bool(
            validation.get("self_intersection_warning_parts", 0)
        ),
    }
    report["self_intersection_warning"] = self_intersection_warning
    report["reference_image"] = str(reference_path) if reference_path else None
    report["parts"] = {
        "count": len(prepared.final.part_keys),
        "required_palette_groups": len(grouping.groups),
        "one_print_job_compatible": grouping.one_job,
        "forced_common_palette_for_print": bool(
            grouping.requires_separate_jobs and force_common_palette
        ),
        "part_metrics": final_colors.part_metrics,
        "individual_model_paths": [str(path) for path in part_model_paths],
        "individual_only": bool(individual_only),
    }
    report["assembly"] = dict(prepared.assembly or {})
    report["print_profile"] = {
        "id": "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)",
        "layer_height_mm": 0.08,
        "initial_layer_height_mm": 0.2,
        "support_fixed": False,
        "filament_material": None if individual_only else print_palette.material,
        "individual_part_materials": sorted(resolved_materials),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig"
    )
    if individual_only:
        _write_individual_only_guide(
            guide_path,
            destination,
            prepared,
            settings,
            part_model_paths,
        )
    else:
        write_guide(
            guide_path,
            destination,
            settings.geometry.height_mm,
            print_palette,
        )
        if self_intersection_warning["orca_preview_required"]:
            with guide_path.open("a", encoding="utf-8") as guide:
                guide.write(
                    "\n\n【微小自己交差の確認】\n"
                    "----------------------\n"
                    "閉立体・面向き・正体積・縮退面の必須検証は合格しています。\n"
                    f"検証上限内の自己交差: "
                    f"{self_intersection_warning['parts']}パーツ / "
                    f"{self_intersection_warning['faces']}面 / "
                    f"合計面積 {self_intersection_warning['area_mm2']:.6g} mm²\n"
                    f"判定: {self_intersection_warning['policy']}\n"
                    "Snapmaker Orcaで必ずプロジェクトとして開き、"
                    "スライスプレビューに欠落・異常な面・意図しない内部線が"
                    "ないことを確認してから印刷してください。\n"
                )
    if grouping.requires_separate_jobs and force_common_palette:
        with guide_path.open("a", encoding="utf-8") as guide:
            guide.write(
                "\nパーツ別基本色について\n"
                "----------------------\n"
                f"元の調整には {len(grouping.groups)} 種類の基本4色構成があります。\n"
                "U1の物理4スロット制約に合わせ、この印刷用3MFの色割当は"
                "全体共通4色へ統合しました。\n"
                "パーツ別構成そのものは Metadata/tripo_part_palettes.json "
                "へ保持しています。\n"
            )
    if part_model_paths:
        with guide_path.open("a", encoding="utf-8") as guide:
            guide.write(
                "\nパーツ別3MF\n"
                "-----------\n"
                f"{part_model_paths[0].parent.name} フォルダーへ "
                f"{len(part_model_paths)} ファイルを保存しました。\n"
                "各ファイルはそのパーツ用の基本4色を持つ独立した印刷ジョブです。\n"
            )

    emit(progress, "preview", 0.91, "比較プレビューを書き出しています")
    try:
        from PIL import Image, ImageDraw

        from .renderer import render_three_column_comparison

        if final_colors.manual_override_faces:
            # Paint edits belong to the final topology. Rendering that same
            # topology keeps the saved comparison image faithful to the 3MF.
            preview_level = prepared.final
            preview_colors = final_colors
        else:
            preview_level = prepared.preview
            preview_colors = recolor_level_parts(
                prepared.preview,
                settings.geometry.height_mm,
                settings.tone,
                settings.palette,
                effective_part_palettes,
            )
        reference: Path | Image.Image
        if reference_path:
            reference = reference_path
        else:
            reference = Image.new("RGB", (720, 900), (9, 10, 13))
            ImageDraw.Draw(reference).text(
                (reference.width // 2, reference.height // 2),
                "参照画像なし",
                fill=(220, 224, 232),
                anchor="mm",
            )
        image = render_three_column_comparison(
            reference,
            preview_level,
            preview_colors,
            panel_size=(480, 600),
        )
        image.save(preview_path)
    except Exception as exc:
        # The printable 3MF remains useful even on machines where OpenGL preview
        # creation is unavailable. Record this visibly instead of hiding it.
        report["preview_warning"] = str(exc)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig"
        )
        preview_path = Path("")

    emit(progress, "done", 1.0, "出力が完了しました")
    return ExportResult(
        model_path=None if individual_only else destination,
        preview_path=preview_path,
        report_path=report_path,
        guide_path=guide_path,
        fallback_obj_path=fallback_obj_path,
        validation=validation,
        part_model_paths=part_model_paths,
        individual_only=bool(individual_only),
    )
