#!/usr/bin/env python3
"""Build a privacy-minimized ledger from generic radial run artifacts.

The generic radial launcher writes ``*_PRECHECK.json``, ``*_RUN.json``, and
``*_FAILED.json`` files.  This standalone tool groups those files into
attempts, derives deterministic geometry/correctness keys, and stores only an
allowlisted summary.  Source paths, model/part names, raw source hashes,
tracebacks, and free-form exception text are never copied into the ledger.

The ledger is descriptive, not predictive.  Its cross-model structural key is
only a deterministic complexity bucket for review and statistics.  It never
authorizes a run.  Every proposed next attempt keeps the strict-zero
self-intersection requirement, the 2,000,000-cell cap, and the 0.05 mm error
limit unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


LEDGER_SCHEMA = "chromamatter.tooling.radial-attempt-ledger.v1"
CORRECTNESS_SCHEMA = "chromamatter.tooling.radial-correctness-key.v1"
GEOMETRY_SCHEMA = "chromamatter.tooling.radial-geometry-fingerprint.v1"
LAUNCHER_SCHEMA_RE = re.compile(
    r"^chromamatter\.tooling\.generic-radial-launcher\.v[1-9][0-9]*$"
)
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:+-]{1,128}$")
UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
ARTIFACT_SUFFIXES = {
    "PRECHECK": "_PRECHECK.json",
    "RUN": "_RUN.json",
    "FAILED": "_FAILED.json",
}
EXPECTED_STATUSES = {
    "PRECHECK": {"preflight_passed"},
    "RUN": {"running", "passed", "failed"},
    "FAILED": {"failed"},
}
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024

# These values are part of the ledger schema and must not be inferred from a
# failed run.  A recorded run may be stricter, but never looser.
SAFETY_CONTRACT: dict[str, object] = {
    "policy": "immutable_fail_closed",
    "required_self_intersecting_faces": 0,
    "maximum_partition_cells": 2_000_000,
    "maximum_error_mm": 0.05,
    "error_scope": [
        "surface_fidelity",
        "partition_sampled_overdepth",
    ],
}
LEDGER_POLICY: dict[str, object] = {
    "contains_private_paths_or_names": False,
    "automatic_retry_allowed": False,
    "structural_fingerprint_use": "review_and_statistics_only",
}

REQUIRED_BEFORE_RUN = [
    "actual_selected_surface_self_intersections_equals_zero",
    "predicted_and_actual_partition_cells_at_or_below_2000000",
    "maximum_surface_and_partition_error_at_or_below_0.05_mm",
]
PROHIBITED_CHANGES = [
    "do_not_allow_self_intersections",
    "do_not_raise_partition_cell_cap",
    "do_not_raise_error_limit",
]
RECOMMENDATION_ACTIONS = {
    "repeat_current_strict_preflight",
    "probe_safer_selected_part_reduction",
    "review_lower_transition_schedule",
    "return_to_clean_surface_before_reduction",
    "inspect_preflight_tetgen_topology_disagreement",
    "probe_simpler_geometry_with_same_depth_proof",
    "review_safer_geometry_before_interface_preflight",
    "diagnose_output_without_new_geometry_run",
    "review_configuration_then_preflight",
    "manual_diagnosis_only",
}
FORBIDDEN_LEDGER_KEYS = {
    "path",
    "input",
    "output",
    "output_root",
    "destination",
    "model_name",
    "source_name",
    "part_name",
    "part_key",
    "source_sha256",
    "traceback",
    "message",
    "exception_type",
}

SAFE_CONFIGURATION_FIELDS: dict[str, tuple[str, ...]] = {
    "geometry": (
        "height_mm",
        "target_faces",
        "target_faces_scope",
        "adjust_face_count",
        "preview_faces",
        "preserve_parts",
        "solidify_parts",
    ),
    "tone": (
        "black_point",
        "white_point",
        "gamma",
        "contrast",
        "saturation",
    ),
    "radial": (
        "conversion_mode",
        "skin_thickness_mode",
        "wall_generator",
        "layer_height_mm",
        "process_profile",
        "sparse_infill_density_percent",
        "minimum_lstar_delta",
        "adaptive_min_thickness_mm",
        "adaptive_max_thickness_mm",
        "adaptive_gamma",
        "adaptive_bands",
        "outer_skin_thickness_mm",
    ),
    "strict_preflight_gate": (
        "minimum_active_bands",
        "minimum_inter_band_thresholds",
        "minimum_faces_per_active_band",
    ),
}

SAFE_FAILURE_NUMERIC_FIELDS = {
    "threshold_mm",
    "requested_threshold_mm",
    "allowed_overdepth_mm",
    "maximum_error_mm",
    "maximum_overdepth_mm",
    "maximum_sampled_overdepth_mm",
    "max_total_sampled_overdepth_mm",
    "max_vertex_sampled_overdepth_mm",
    "max_interior_sampled_overdepth_mm",
    "predicted_capacity",
    "exact_capacity",
    "legacy_worst_case_capacity",
    "input_cells",
    "output_cells",
    "noncrossing_cells",
    "crossing_cells",
    "three_edge_crossing_cells",
    "four_edge_crossing_cells",
    "maximum",
    "maximum_cells",
    "cell_count",
    "tetrahedra",
    "violating_triangles",
    "violating_parent_cells",
    "seed_edges",
    "boundary_seed_edges",
    "refinement_round",
    "refinement_rounds",
    "refinement_passes",
    "stagnation_diameter_pass",
    "parent_cells",
    "unresolved_children",
    "maximum_child_parent_diameter_ratio",
    "maximum_allowed_child_parent_diameter_ratio",
    "boundary_edges",
    "nonmanifold_edges",
    "inconsistent_winding_edges",
    "degenerate_faces",
    "self_intersecting_faces",
    "body_count",
}

SAFE_FALLBACK_SUMMARY_NUMERIC_FIELDS = {
    "local_refinement_rounds",
    "total_rounds",
    "interface_refinement_rounds",
    "ordinary_interface_refinement_rounds",
    "stagnation_fallback_refinement_rounds",
    "fallback_rounds",
    "partner_refinement_rounds",
    "maximum_total_local_refinement_rounds",
    "maximum_interface_refinement_rounds",
}
SAFE_STAGNATION_POLICY_FIELDS = {
    "use_full_diameter_fallback",
    "hard_stop",
    "repeated_signature",
    "structural_diagnostics_match",
    "structural_counts_and_roles_are_diagnostic_only",
    "same_spatial_lineage",
    "spatial_lineage_overlap_fraction",
    "poor_contraction",
    "previous_used_fallback",
    "current_maximum_overdepth_mm",
    "previous_maximum_overdepth_mm",
    "overdepth_contraction_ratio",
    "maximum_poor_contraction_ratio",
    "minimum_overdepth_reduction_fraction",
    "maximum_violating_parent_cells",
}
SAFE_REFINEMENT_BUDGET_ROUTE_FIELDS = {
    "allowed",
    "use_full_diameter_fallback",
    "policy_requested_full_diameter_fallback",
    "exhausted_interface_budget_replacement",
    "ordinary_interface_rounds",
    "stagnation_fallback_rounds",
    "partner_rounds",
    "total_rounds",
    "maximum_ordinary_interface_rounds",
    "maximum_stagnation_fallback_rounds",
    "maximum_partner_rounds",
    "maximum_total_rounds",
}
SAFE_REFINEMENT_CAUSES = {"interface", "partner"}


def _safe_prefixed_failure_fields(
    details: object,
) -> dict[str, object]:
    if not isinstance(details, Mapping):
        return {}
    result: dict[str, object] = {}

    def copy_known(
        prefix: str,
        source: object,
        fields: set[str],
    ) -> None:
        if not isinstance(source, Mapping):
            return
        for field in sorted(fields):
            value = source.get(field)
            if isinstance(value, bool):
                result[f"{prefix}.{field}"] = value
                continue
            number = _finite_number(value)
            if number is not None:
                result[f"{prefix}.{field}"] = number

    copy_known(
        "fallback_summary",
        details,
        SAFE_FALLBACK_SUMMARY_NUMERIC_FIELDS,
    )
    copy_known(
        "stagnation_policy",
        details.get("stagnation_policy"),
        SAFE_STAGNATION_POLICY_FIELDS,
    )
    copy_known(
        "refinement_budget_route",
        details.get("refinement_budget_route"),
        SAFE_REFINEMENT_BUDGET_ROUTE_FIELDS,
    )
    cause = _safe_token(details.get("refinement_cause"))
    if cause in SAFE_REFINEMENT_CAUSES:
        result["fallback_summary.refinement_cause"] = cause
    return result


SAFE_PREFIXED_FAILURE_FIELDS = (
    {f"fallback_summary.{field}" for field in SAFE_FALLBACK_SUMMARY_NUMERIC_FIELDS}
    | {"fallback_summary.refinement_cause"}
    | {
        f"stagnation_policy.{field}"
        for field in SAFE_STAGNATION_POLICY_FIELDS
    }
    | {
        f"refinement_budget_route.{field}"
        for field in SAFE_REFINEMENT_BUDGET_ROUTE_FIELDS
    }
)

CAPACITY_CODES = {
    "variable_partition_cell_limit_exceeded",
    "partition_cell_limit_exceeded",
    "tetrahedral_cell_limit_exceeded",
}
SELF_INTERSECTION_CODES = {
    "selected_part_self_intersection_unverified",
    "selected_part_self_intersection_check_failed",
    "selected_part_self_intersection_detected",
}
TOPOLOGY_CODES = {
    "selected_part_topology_gate_failed",
    "tetgen_exact_boundary_failed",
    "tetgen_surface_boundary_mismatch",
}
STAGNATION_CODE_PREFIXES = (
    "adaptive_interface_stagnation_",
    "adaptive_stagnation_",
)
KNOWN_FAILURE_CODES = (
    CAPACITY_CODES
    | SELF_INTERSECTION_CODES
    | TOPOLOGY_CODES
    | {
        "no_used_contrast_eligible_black_mix",
        "insufficient_active_adaptive_bands",
        "insufficient_inter_band_thresholds",
        "hybrid_conventional_surface_required",
        "selected_part_not_found",
        "selected_part_ambiguous",
        "localized_threshold_interface_too_deep",
        "adaptive_partner_cell_too_deep",
        "required_argument_missing",
        "input_model_not_found",
        "output_exists",
        "invalid_integer_limit",
        "unexpected_sparse_infill_profile",
        "four_physical_colors_required",
        "invalid_physical_color",
        "exactly_one_part_selector_required",
        "hybrid_3mf_validation_failed",
        "radial_3mf_validation_failed",
        "archive_reopen_validation_failed",
    }
)
SAFE_FAILURE_PHASES = {
    "preflight",
    "preallocation",
    "postallocation",
    "tetrahedralization",
    "interface_refinement",
    "partner_refinement",
    "partition_validation",
    "package_write",
    "archive_reopen",
}


class LedgerError(RuntimeError):
    """Stable fail-closed ledger diagnostic."""


def _is_known_failure_code(code: object) -> bool:
    return isinstance(code, str) and (
        code in KNOWN_FAILURE_CODES
        or code.startswith(STAGNATION_CODE_PREFIXES)
    )


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LedgerError("duplicate_json_key")
        result[key] = value
    return result


def _canonical_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LedgerError("value_is_not_canonical_json") from exc
    return text.encode("utf-8")


def _canonical_sha256(value: object, *, domain: str) -> str:
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    digest.update(b"\0")
    digest.update(_canonical_bytes(value))
    return digest.hexdigest()


def _reference_digest(value: object, *, domain: str) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    digest.update(b"\0")
    digest.update(value.encode("utf-8", errors="strict"))
    return digest.hexdigest()


def _safe_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if SAFE_TOKEN_RE.fullmatch(text) else None


def _finite_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(converted):
        return None
    return value


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return int(value)


def _safe_known_value(value: object) -> object | None:
    if isinstance(value, bool):
        return value
    number = _finite_number(value)
    if number is not None:
        return number
    token = _safe_token(value)
    if token is not None:
        return token
    return None


def _artifact_kind(path: Path) -> tuple[str, str] | None:
    for kind, suffix in ARTIFACT_SUFFIXES.items():
        if path.name.endswith(suffix):
            return kind, path.name[: -len(suffix)]
    return None


def _read_artifact(path: Path, kind: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise LedgerError("artifact_must_be_regular_file")
    size = path.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise LedgerError("artifact_size_out_of_bounds")
    raw = path.read_bytes()
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LedgerError("artifact_is_not_utf8_json") from exc
    if not isinstance(payload, dict):
        raise LedgerError("artifact_root_must_be_object")
    schema = payload.get("schema")
    status = payload.get("status")
    if not isinstance(schema, str) or not LAUNCHER_SCHEMA_RE.fullmatch(schema):
        raise LedgerError("unsupported_launcher_artifact_schema")
    if status not in EXPECTED_STATUSES[kind]:
        raise LedgerError(f"unexpected_{kind.lower()}_status")
    return {
        "kind": kind,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "payload": payload,
    }


def collect_artifact_groups(
    sources: Sequence[str | os.PathLike[str]],
) -> list[dict[str, dict[str, object]]]:
    """Collect launcher artifact triplets without retaining their paths."""

    candidates: list[Path] = []
    for raw_source in sources:
        source = Path(raw_source)
        if source.is_symlink():
            raise LedgerError("artifact_source_symlink_rejected")
        if source.is_file():
            if _artifact_kind(source) is None:
                raise LedgerError("unrecognized_artifact_filename")
            candidates.append(source)
        elif source.is_dir():
            candidates.extend(
                path
                for path in source.rglob("*.json")
                if _artifact_kind(path) is not None
            )
        else:
            raise LedgerError("artifact_source_not_found")
    if not candidates:
        raise LedgerError("no_radial_artifacts_found")

    grouped: dict[tuple[str, str], dict[str, dict[str, object]]] = {}
    for path in sorted(set(candidates), key=lambda value: str(value).casefold()):
        if path.is_symlink():
            raise LedgerError("artifact_symlink_rejected")
        matched = _artifact_kind(path)
        if matched is None:
            continue
        kind, prefix = matched
        group_key = (str(path.parent.resolve()), prefix)
        artifact = _read_artifact(path, kind)
        group = grouped.setdefault(group_key, {})
        previous = group.get(kind)
        if previous is not None and previous["sha256"] != artifact["sha256"]:
            raise LedgerError("conflicting_duplicate_artifact")
        group[kind] = artifact
    return [grouped[key] for key in sorted(grouped)]


def _artifact_event(artifact: Mapping[str, object]) -> dict[str, object]:
    payload = artifact["payload"]
    assert isinstance(payload, dict)
    kind = str(artifact["kind"])
    timestamp_field = {
        "PRECHECK": "created_utc",
        "RUN": "completed_utc" if payload.get("status") == "passed" else "started_utc",
        "FAILED": "failed_utc",
    }[kind]
    event: dict[str, object] = {
        "kind": kind,
        "artifact_schema": str(payload["schema"]),
        "status": str(payload["status"]),
        "artifact_sha256": str(artifact["sha256"]),
    }
    timestamp = payload.get(timestamp_field)
    if isinstance(timestamp, str) and UTC_RE.fullmatch(timestamp):
        event["artifact_utc"] = timestamp
    return event


def _precheck_from_artifacts(
    artifacts: Mapping[str, Mapping[str, object]],
) -> dict[str, object] | None:
    direct: dict[str, object] | None = None
    embedded: dict[str, object] | None = None
    if "PRECHECK" in artifacts:
        value = artifacts["PRECHECK"]["payload"]
        if isinstance(value, dict):
            direct = value
    if "RUN" in artifacts:
        run_payload = artifacts["RUN"]["payload"]
        if isinstance(run_payload, dict) and isinstance(
            run_payload.get("precheck"), dict
        ):
            embedded = run_payload["precheck"]
    if direct is not None and embedded is not None:
        if _canonical_bytes(direct) != _canonical_bytes(embedded):
            raise LedgerError("run_precheck_conflicts_with_precheck_artifact")
    return direct or embedded


def _failure_from_artifacts(
    artifacts: Mapping[str, Mapping[str, object]],
) -> dict[str, object] | None:
    failed_payload: dict[str, object] | None = None
    run_failure: dict[str, object] | None = None
    if "FAILED" in artifacts:
        value = artifacts["FAILED"]["payload"]
        if isinstance(value, dict):
            failed_payload = value
    if "RUN" in artifacts:
        value = artifacts["RUN"]["payload"]
        if isinstance(value, dict) and value.get("status") == "failed":
            run_failure = value
    if failed_payload is not None and run_failure is not None:
        if _canonical_bytes(failed_payload.get("error")) != _canonical_bytes(
            run_failure.get("error")
        ):
            raise LedgerError("run_failure_conflicts_with_failed_artifact")
    return failed_payload or run_failure


def _safe_configuration(precheck: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(precheck, Mapping):
        return {}
    raw = precheck.get("configuration")
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, object] = {}
    physical = raw.get("physical_hex")
    if isinstance(physical, list) and len(physical) == 4:
        normalized = [
            item.upper()
            for item in physical
            if isinstance(item, str) and HEX_RE.fullmatch(item)
        ]
        if len(normalized) == 4:
            result["physical_hex"] = normalized
    for key in ("black_slot_zero_based", "black_extruder"):
        value = _nonnegative_int(raw.get(key))
        if value is not None:
            result[key] = value
    selector_kind = None
    selector_value = None
    if isinstance(raw.get("part_key"), str) and raw.get("part_key"):
        selector_kind = "part_key"
        selector_value = raw.get("part_key")
    elif isinstance(raw.get("part_name"), str) and raw.get("part_name"):
        selector_kind = "part_name"
        selector_value = raw.get("part_name")
    if selector_value is not None:
        result["part_selector"] = {
            "kind": selector_kind,
            "digest": _reference_digest(
                selector_value, domain="radial-part-selector-v1"
            ),
        }
    for section, fields in SAFE_CONFIGURATION_FIELDS.items():
        raw_section = raw.get(section)
        if not isinstance(raw_section, Mapping):
            continue
        safe_section: dict[str, object] = {}
        for field in fields:
            value = _safe_known_value(raw_section.get(field))
            if value is not None:
                safe_section[field] = value
        if safe_section:
            result[section] = safe_section
    return result


def _topology_summary(precheck: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(precheck, Mapping):
        return {}
    topology = precheck.get("topology")
    if not isinstance(topology, Mapping):
        return {}
    solid = topology.get("solid_quality")
    edge = topology.get("edge_topology")
    gate = topology.get("self_intersection_gate")
    solid_map = solid if isinstance(solid, Mapping) else {}
    edge_map = edge if isinstance(edge, Mapping) else {}
    gate_map = gate if isinstance(gate, Mapping) else {}
    fields = (
        "boundary_edges",
        "nonmanifold_edges",
        "inconsistent_winding_edges",
        "degenerate_faces",
        "body_count",
        "self_intersecting_faces",
        "watertight",
        "winding_consistent",
        "positive_volume",
    )
    result: dict[str, object] = {}
    for field in fields:
        value = solid_map.get(field, edge_map.get(field))
        safe = _safe_known_value(value)
        if safe is not None:
            result[field] = safe
    strict_zero = (
        gate_map.get("strict_zero_verified") is True
        and gate_map.get("check_completed") is True
        and _nonnegative_int(gate_map.get("self_intersecting_faces")) == 0
    )
    result["strict_zero_self_intersection_verified"] = strict_zero
    policy = _safe_token(gate_map.get("policy"))
    if policy is not None:
        result["self_intersection_policy"] = policy
    return result


def _count_summary(precheck: Mapping[str, object] | None) -> dict[str, int]:
    if not isinstance(precheck, Mapping):
        return {}
    source = precheck.get("source")
    selection = precheck.get("selection")
    source_map = source if isinstance(source, Mapping) else {}
    selection_map = selection if isinstance(selection, Mapping) else {}
    result: dict[str, int] = {}
    for field in (
        "source_vertices",
        "source_faces",
        "source_part_count",
        "prepared_vertices",
        "prepared_faces",
    ):
        value = _nonnegative_int(source_map.get(field))
        if value is not None:
            result[field] = value
    for field in (
        "selected_vertices",
        "selected_faces",
        "source_face_id_count",
    ):
        value = _nonnegative_int(selection_map.get(field))
        if value is not None:
            result[field] = value
    return result


def _preparation_summary(precheck: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(precheck, Mapping):
        return {}
    provenance = precheck.get("preparation_provenance")
    if not isinstance(provenance, Mapping):
        return {}
    generated = provenance.get("generated_surface_provenance")
    generated_map = generated if isinstance(generated, Mapping) else {}
    multipart = provenance.get("multipart_qem")
    multipart_map = multipart if isinstance(multipart, Mapping) else {}
    selected_stats = provenance.get("selected_part_stats")
    stats_map = selected_stats if isinstance(selected_stats, Mapping) else {}
    result: dict[str, object] = {}
    topology_sha = generated_map.get("topology_sha256")
    if isinstance(topology_sha, str) and SHA256_RE.fullmatch(topology_sha):
        result["prepared_topology_digest"] = _reference_digest(
            topology_sha.lower(), domain="prepared-topology-reference-v1"
        )
    for field in (
        "includes_topology_edits",
        "generated_face_count",
        "face_count",
        "vertex_count",
    ):
        value = _safe_known_value(generated_map.get(field))
        if value is not None:
            result[field] = value
    for field in (
        "simplification_applied",
        "source_triangle_geometry_preserved",
        "source_triangle_ancestry_proven",
        "qem_max_output_ratio_numerator",
        "qem_max_output_ratio_denominator",
    ):
        value = multipart_map.get(field, stats_map.get(field))
        safe = _safe_known_value(value)
        if safe is not None:
            result[field] = safe
    for field in (
        "pre_qem_face_count",
        "post_qem_source_face_count",
        "final_faces",
        "final_vertices",
    ):
        value = _nonnegative_int(stats_map.get(field))
        if value is not None:
            result[field] = value
    return result


def _selector_digest(
    precheck: Mapping[str, object] | None,
    safe_configuration: Mapping[str, object],
) -> tuple[str | None, str | None]:
    selector = safe_configuration.get("part_selector")
    if isinstance(selector, Mapping):
        kind = selector.get("kind")
        digest = selector.get("digest")
        if isinstance(kind, str) and isinstance(digest, str):
            return kind, digest
    if isinstance(precheck, Mapping):
        selection = precheck.get("selection")
        if isinstance(selection, Mapping):
            for field in ("part_key", "part_name"):
                value = selection.get(field)
                if isinstance(value, str) and value:
                    return field, _reference_digest(
                        value, domain="radial-part-selector-v1"
                    )
            part_id = _nonnegative_int(selection.get("part_id"))
            if part_id is not None:
                return "part_id", _reference_digest(
                    str(part_id), domain="radial-part-selector-v1"
                )
    return None, None


def _power_two_bucket(value: int | None) -> str:
    if value is None or value <= 0:
        return "unknown"
    exponent = value.bit_length() - 1
    return f"2^{exponent}..2^{exponent + 1}-1"


def _schedule_class(precheck: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(precheck, Mapping):
        return {}
    schedule = precheck.get("adaptive_schedule")
    if not isinstance(schedule, Mapping):
        return {}
    gate = schedule.get("strict_gate")
    if not isinstance(gate, Mapping):
        return {}
    result: dict[str, object] = {}
    for field in (
        "active_band_count",
        "inter_band_threshold_count",
        "partition_outer_depth_boundary_count",
        "minimum_faces_per_active_band",
    ):
        value = _nonnegative_int(gate.get(field))
        if value is not None:
            result[field] = value
    return result


def derive_geometry_fingerprint(
    precheck: Mapping[str, object] | None,
    safe_configuration: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Derive exact and coarse structural geometry identities.

    The exact key contains domain-separated digests of private identifiers;
    the raw identifiers are not retained.  The structural key deliberately
    excludes source and part identity.  It is suitable only for grouping
    similar complexity records, never for authorizing a retry.
    """

    configuration = dict(safe_configuration or _safe_configuration(precheck))
    counts = _count_summary(precheck)
    topology = _topology_summary(precheck)
    preparation = _preparation_summary(precheck)
    selector_kind, selector_digest = _selector_digest(
        precheck, configuration
    )
    source_digest = None
    if isinstance(precheck, Mapping):
        source = precheck.get("source")
        if isinstance(source, Mapping):
            raw_sha = source.get("sha256")
            if isinstance(raw_sha, str) and SHA256_RE.fullmatch(raw_sha):
                source_digest = _reference_digest(
                    raw_sha.lower(), domain="radial-source-reference-v1"
                )
    evidence = {
        "source_identity_digest": source_digest,
        "part_selector_kind": selector_kind,
        "part_selector_digest": selector_digest,
        "counts": counts,
        "topology": topology,
        "preparation": preparation,
    }
    missing: list[str] = []
    if source_digest is None:
        missing.append("source_sha256")
    if selector_digest is None:
        missing.append("part_selector")
    for field in ("selected_vertices", "selected_faces"):
        if not counts.get(field):
            missing.append(field)
    if topology.get("strict_zero_self_intersection_verified") is not True:
        missing.append("strict_zero_self_intersection_proof")
    required_solid = {
        "boundary_edges": 0,
        "nonmanifold_edges": 0,
        "inconsistent_winding_edges": 0,
        "degenerate_faces": 0,
        "body_count": 1,
        "watertight": True,
        "winding_consistent": True,
        "positive_volume": True,
    }
    if any(topology.get(key) != value for key, value in required_solid.items()):
        missing.append("closed_positive_single_body_topology_proof")

    structural_payload = {
        "schema": GEOMETRY_SCHEMA,
        "selected_face_bucket": _power_two_bucket(counts.get("selected_faces")),
        "selected_vertex_bucket": _power_two_bucket(
            counts.get("selected_vertices")
        ),
        "prepared_face_bucket": _power_two_bucket(counts.get("prepared_faces")),
        "source_part_count": counts.get("source_part_count"),
        "simplification_applied": preparation.get("simplification_applied"),
        "topology_class": {
            key: topology.get(key)
            for key in (
                "body_count",
                "watertight",
                "winding_consistent",
                "positive_volume",
                "strict_zero_self_intersection_verified",
            )
        },
        "adaptive_schedule_class": _schedule_class(precheck),
    }
    exact_payload = {"schema": GEOMETRY_SCHEMA, "evidence": evidence}
    return {
        "schema": GEOMETRY_SCHEMA,
        "sha256": _canonical_sha256(
            exact_payload, domain="radial-geometry-fingerprint-v1"
        ),
        "structural_sha256": _canonical_sha256(
            structural_payload, domain="radial-geometry-structure-v1"
        ),
        "complete": not missing,
        "missing_evidence": sorted(set(missing)),
        "evidence": evidence,
        "structural_basis": structural_payload,
        "structural_use": "review_and_statistics_only",
    }


def _configuration_completeness(
    configuration: Mapping[str, object],
) -> list[str]:
    missing: list[str] = []
    physical = configuration.get("physical_hex")
    if not isinstance(physical, list) or len(physical) != 4:
        missing.append("four_physical_hex_values")
    if configuration.get("black_extruder") not in (1, 2, 3, 4):
        missing.append("black_extruder")
    for section in ("geometry", "tone", "radial", "strict_preflight_gate"):
        if not isinstance(configuration.get(section), Mapping):
            missing.append(section)
    radial = configuration.get("radial")
    if isinstance(radial, Mapping):
        for field in (
            "conversion_mode",
            "skin_thickness_mode",
            "wall_generator",
            "layer_height_mm",
            "sparse_infill_density_percent",
            "minimum_lstar_delta",
            "adaptive_min_thickness_mm",
            "adaptive_max_thickness_mm",
            "adaptive_gamma",
            "adaptive_bands",
        ):
            if field not in radial:
                missing.append(f"radial.{field}")
    return missing


def derive_correctness_key(
    precheck: Mapping[str, object] | None,
    geometry: Mapping[str, object],
    configuration: Mapping[str, object],
    *,
    fallback_launcher_schema: str | None = None,
) -> dict[str, object]:
    launcher_schema = None
    if isinstance(precheck, Mapping):
        raw_schema = precheck.get("schema")
        if isinstance(raw_schema, str) and LAUNCHER_SCHEMA_RE.fullmatch(raw_schema):
            launcher_schema = raw_schema
    if launcher_schema is None and isinstance(fallback_launcher_schema, str):
        if LAUNCHER_SCHEMA_RE.fullmatch(fallback_launcher_schema):
            launcher_schema = fallback_launcher_schema
    missing = _configuration_completeness(configuration)
    if launcher_schema is None:
        missing.append("launcher_schema")
    if geometry.get("complete") is not True:
        missing.extend(
            f"geometry.{item}"
            for item in geometry.get("missing_evidence", [])
            if isinstance(item, str)
        )
    payload = {
        "schema": CORRECTNESS_SCHEMA,
        "launcher_schema": launcher_schema,
        "geometry_sha256": geometry.get("sha256"),
        "configuration": configuration,
        "safety_contract": SAFETY_CONTRACT,
    }
    return {
        "schema": CORRECTNESS_SCHEMA,
        "sha256": _canonical_sha256(
            payload, domain="radial-correctness-key-v1"
        ),
        "complete": not missing,
        "missing_evidence": sorted(set(missing)),
        "launcher_schema": launcher_schema,
    }


def _safe_failure_evidence(details: object) -> dict[str, object]:
    result: dict[str, object] = _safe_prefixed_failure_fields(details)
    ambiguous: set[str] = set()

    def record(key: str, value: object) -> None:
        if key in ambiguous:
            return
        if key in result and result[key] != value:
            result.pop(key, None)
            ambiguous.add(key)
            return
        result[key] = value

    def visit(value: object, depth: int) -> None:
        if depth > 5 or not isinstance(value, Mapping):
            return
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip()
            if key == "phase":
                token = _safe_token(item)
                if token in SAFE_FAILURE_PHASES:
                    record(key, token)
            elif key in SAFE_FAILURE_NUMERIC_FIELDS:
                safe = _safe_known_value(item)
                if isinstance(safe, (bool, int, float)):
                    record(key, safe)
            if isinstance(item, Mapping):
                visit(item, depth + 1)

    visit(details, 0)
    return dict(sorted(result.items()))


def _failure_value(
    evidence: Mapping[str, object], field: str
) -> object | None:
    exact = evidence.get(field)
    if exact is not None:
        return exact
    matches = [
        value for key, value in evidence.items() if key.endswith("." + field)
    ]
    return matches[0] if len(matches) == 1 else None


def _classify_failure(
    failure_payload: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if not isinstance(failure_payload, Mapping):
        return None
    error = failure_payload.get("error")
    error_map = error if isinstance(error, Mapping) else {}
    raw_code = _safe_token(error_map.get("code"))
    classification_code = raw_code or "unclassified_error"
    code = (
        classification_code
        if _is_known_failure_code(classification_code)
        else "unclassified_error"
    )
    evidence = _safe_failure_evidence(error_map.get("details"))
    lowered = classification_code.lower()
    if classification_code.startswith(STAGNATION_CODE_PREFIXES):
        stage, category = "interface_refinement", "stagnation"
    elif classification_code in CAPACITY_CODES or "cell_limit" in lowered:
        stage, category = "exact_partition", "cell_capacity"
    elif (
        classification_code in SELF_INTERSECTION_CODES
        or "self_intersection" in lowered
    ):
        stage, category = "preflight_geometry", "self_intersection"
    elif classification_code in TOPOLOGY_CODES or "tetgen" in lowered:
        stage, category = "tetrahedralization", "surface_or_tetgen_topology"
    elif (
        "overdepth" in lowered
        or "interface_too_deep" in lowered
        or "partner_cell_too_deep" in lowered
    ):
        stage, category = "exact_partition", "depth_proof"
    elif "preflight" in lowered or classification_code in {
        "no_used_contrast_eligible_black_mix",
        "insufficient_active_adaptive_bands",
        "insufficient_inter_band_thresholds",
        "hybrid_conventional_surface_required",
        "selected_part_not_found",
        "selected_part_ambiguous",
    }:
        stage, category = "preflight", "configuration_or_band_gate"
    elif "3mf" in lowered or "archive" in lowered or "validation" in lowered:
        stage, category = "package_validation", "output_validation"
    elif "write" in lowered or "export" in lowered:
        stage, category = "export", "output_write"
    else:
        stage, category = "unknown", "manual_diagnosis_required"
    result = {
        "code": code,
        "stage": stage,
        "category": category,
        "evidence": evidence,
    }
    if raw_code is not None and not _is_known_failure_code(raw_code):
        result["unclassified_code_digest"] = _reference_digest(
            raw_code, domain="radial-unclassified-error-code-v1"
        )
    return result


def _recommendation(
    action: str,
    reason: str,
    *,
    parameters: Mapping[str, object] | None = None,
    priority: int = 1,
) -> dict[str, object]:
    return {
        "priority": int(priority),
        "action": action,
        "reason": reason,
        "parameters": dict(parameters or {}),
        "next_mode": "preflight_only",
        "automatic_run_allowed": False,
        "safety_contract": dict(SAFETY_CONTRACT),
        "required_before_run": list(REQUIRED_BEFORE_RUN),
        "prohibited_changes": list(PROHIBITED_CHANGES),
    }


def _recommend_next_attempts(
    failure: Mapping[str, object] | None,
    geometry: Mapping[str, object],
) -> list[dict[str, object]]:
    if not isinstance(failure, Mapping):
        return []
    topology = geometry.get("evidence", {})
    topology_map = topology if isinstance(topology, Mapping) else {}
    topology_summary = topology_map.get("topology", {})
    strict_zero = (
        isinstance(topology_summary, Mapping)
        and topology_summary.get("strict_zero_self_intersection_verified") is True
    )
    if not strict_zero:
        return [
            _recommendation(
                "repeat_current_strict_preflight",
                (
                    "The recorded geometry lacks current actual strict-zero "
                    "self-intersection proof."
                ),
                parameters={
                    "discard_legacy_run_authority": True,
                    "require_actual_selected_post_reduction_check": True,
                },
            )
        ]

    category = str(failure.get("category", ""))
    code = str(failure.get("code", ""))
    evidence = failure.get("evidence", {})
    evidence_map = evidence if isinstance(evidence, Mapping) else {}
    recommendations: list[dict[str, object]] = []
    if category == "cell_capacity":
        exact = _finite_number(_failure_value(evidence_map, "exact_capacity"))
        if exact is None:
            exact = _finite_number(
                _failure_value(evidence_map, "predicted_capacity")
            )
        reported_max = _finite_number(_failure_value(evidence_map, "maximum"))
        budget = int(SAFETY_CONTRACT["maximum_partition_cells"])
        if reported_max is not None and 0 < float(reported_max) <= budget:
            budget = int(reported_max)
        counts = topology_map.get("counts", {})
        selected_faces = (
            _nonnegative_int(counts.get("selected_faces"))
            if isinstance(counts, Mapping)
            else None
        )
        parameters: dict[str, object] = {
            "restart_from_clean_source_geometry": True,
            "cell_budget": budget,
            "screening_margin": 0.80,
            "face_target_is_only_a_preflight_screen": True,
        }
        if (
            selected_faces is not None
            and selected_faces > 4
            and exact is not None
            and float(exact) > float(budget)
        ):
            candidate = math.floor(
                selected_faces * (float(budget) / float(exact)) * 0.80
            )
            if 4 <= candidate < selected_faces:
                parameters["candidate_selected_part_face_upper_bound"] = candidate
                parameters["recorded_selected_faces"] = selected_faces
                parameters["recorded_capacity"] = int(exact)
        recommendations.append(
            _recommendation(
                "probe_safer_selected_part_reduction",
                (
                    "Reduce complexity from clean source geometry; the face "
                    "estimate is a screen, not a capacity guarantee."
                ),
                parameters=parameters,
            )
        )
        schedule = geometry.get("structural_basis", {})
        schedule_class = (
            schedule.get("adaptive_schedule_class", {})
            if isinstance(schedule, Mapping)
            else {}
        )
        active = (
            _nonnegative_int(schedule_class.get("active_band_count"))
            if isinstance(schedule_class, Mapping)
            else None
        )
        if active is not None and active > 2:
            recommendations.append(
                _recommendation(
                    "review_lower_transition_schedule",
                    (
                        "A lower-complexity schedule may be tested only if the "
                        "changed thickness design is acceptable."
                    ),
                    parameters={
                        "recorded_active_bands": active,
                        "minimum_active_bands": 2,
                        "minimum_inter_band_thresholds": 1,
                        "changes_requested_output": True,
                    },
                    priority=2,
                )
            )
    elif category == "self_intersection":
        recommendations.append(
            _recommendation(
                "return_to_clean_surface_before_reduction",
                (
                    "The selected surface cannot enter TetGen until strict-zero "
                    "self-intersection is proven."
                ),
                parameters={
                    "failed_code": code,
                    "automatic_repair_allowed": False,
                },
            )
        )
    elif category == "surface_or_tetgen_topology":
        recommendations.append(
            _recommendation(
                "inspect_preflight_tetgen_topology_disagreement",
                (
                    "Strict preflight and TetGen disagree; diagnose the exact "
                    "selected bytes before changing geometry."
                ),
                parameters={
                    "failed_code": code,
                    "rerun_unchanged_allowed": False,
                },
            )
        )
    elif category == "depth_proof":
        recommendations.append(
            _recommendation(
                "probe_simpler_geometry_with_same_depth_proof",
                (
                    "Keep the 0.05 mm proof unchanged and test a cleaner, "
                    "lower-complexity source representation."
                ),
                parameters={"failed_code": code, "keep_depth_limit_mm": 0.05},
            )
        )
    elif category == "stagnation":
        recommendations.append(
            _recommendation(
                "review_safer_geometry_before_interface_preflight",
                (
                    "Interface refinement stopped without certified "
                    "contraction; review a cleaner or conservatively reduced "
                    "selected surface before another strict preflight."
                ),
                parameters={
                    "failed_code": code,
                    "restart_from_clean_source_geometry": True,
                    "rerun_unchanged_allowed": False,
                    "keep_interface_error_limit_mm": 0.05,
                    "require_new_strict_preflight": True,
                },
            )
        )
    elif category in {"output_validation", "output_write"}:
        recommendations.append(
            _recommendation(
                "diagnose_output_without_new_geometry_run",
                (
                    "Preserve the failed output evidence and inspect the "
                    "writer/validator stage before another heavy run."
                ),
                parameters={"failed_code": code},
            )
        )
    elif category == "configuration_or_band_gate":
        recommendations.append(
            _recommendation(
                "review_configuration_then_preflight",
                (
                    "The requested palette or band schedule did not satisfy "
                    "the explicit preflight contract."
                ),
                parameters={
                    "failed_code": code,
                    "changes_require_owner_review": True,
                },
            )
        )
    else:
        recommendations.append(
            _recommendation(
                "manual_diagnosis_only",
                (
                    "The failure is not in the conservative allowlist; do not "
                    "guess or auto-run."
                ),
                parameters={"failed_code": code},
            )
        )
    return recommendations


def _attempt_outcome(
    artifacts: Mapping[str, Mapping[str, object]],
    failure: Mapping[str, object] | None,
) -> str:
    if failure is not None:
        return "failed"
    run = artifacts.get("RUN")
    if run is not None:
        payload = run.get("payload")
        if isinstance(payload, Mapping):
            status = payload.get("status")
            if status == "passed":
                return "passed"
            if status == "running":
                return "running"
    if "PRECHECK" in artifacts:
        return "preflight_passed"
    return "incomplete"


def build_attempt_record(
    artifacts: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    if not artifacts:
        raise LedgerError("empty_artifact_group")
    precheck = _precheck_from_artifacts(artifacts)
    failure_payload = _failure_from_artifacts(artifacts)
    if failure_payload is not None and "RUN" in artifacts:
        run_payload = artifacts["RUN"].get("payload")
        if isinstance(run_payload, Mapping) and run_payload.get("status") == "passed":
            raise LedgerError("passed_run_conflicts_with_failure_artifact")
    events = [
        _artifact_event(artifacts[kind])
        for kind in ("PRECHECK", "RUN", "FAILED")
        if kind in artifacts
    ]
    fallback_schema = str(events[0]["artifact_schema"]) if events else None
    configuration = _safe_configuration(precheck)
    geometry = derive_geometry_fingerprint(precheck, configuration)
    correctness = derive_correctness_key(
        precheck,
        geometry,
        configuration,
        fallback_launcher_schema=fallback_schema,
    )
    failure = _classify_failure(failure_payload)
    recommendations = _recommend_next_attempts(failure, geometry)
    artifact_set_sha256 = _canonical_sha256(
        {event["kind"]: event["artifact_sha256"] for event in events},
        domain="radial-artifact-set-v1",
    )
    identity_anchor_sha256 = (
        _canonical_sha256(
            precheck,
            domain="radial-attempt-precheck-anchor-v1",
        )
        if precheck is not None
        else artifact_set_sha256
    )
    attempt_id = _canonical_sha256(
        {
            "correctness_sha256": correctness["sha256"],
            "identity_anchor_sha256": identity_anchor_sha256,
        },
        domain="radial-attempt-id-v1",
    )
    reported_limit = None
    if isinstance(failure, Mapping):
        evidence = failure.get("evidence")
        if isinstance(evidence, Mapping):
            reported_limit = _finite_number(
                _failure_value(evidence, "maximum")
            )
    limit_consistent = (
        None
        if reported_limit is None
        else float(reported_limit)
        <= float(SAFETY_CONTRACT["maximum_partition_cells"])
    )
    return {
        "attempt_id": attempt_id,
        "identity_anchor_sha256": identity_anchor_sha256,
        "artifact_set_sha256": artifact_set_sha256,
        "events": events,
        "outcome": _attempt_outcome(artifacts, failure),
        "configuration": configuration,
        "geometry_fingerprint": geometry,
        "correctness_key": correctness,
        "safety_assessment": {
            "strict_zero_self_intersection_verified": geometry["evidence"][
                "topology"
            ].get("strict_zero_self_intersection_verified")
            is True,
            "reported_cell_limit_consistent": limit_consistent,
            "automatic_retry_allowed": False,
            "safety_contract": dict(SAFETY_CONTRACT),
        },
        "failure": failure,
        "recommendations": recommendations,
    }


def _indexes(attempts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    correctness: defaultdict[str, list[str]] = defaultdict(list)
    geometry: defaultdict[str, list[str]] = defaultdict(list)
    structural: defaultdict[str, list[str]] = defaultdict(list)
    for attempt in attempts:
        attempt_id = str(attempt["attempt_id"])
        key = attempt.get("correctness_key")
        if isinstance(key, Mapping) and isinstance(key.get("sha256"), str):
            correctness[str(key["sha256"])].append(attempt_id)
        fingerprint = attempt.get("geometry_fingerprint")
        if isinstance(fingerprint, Mapping):
            for field, target in (
                ("sha256", geometry),
                ("structural_sha256", structural),
            ):
                value = fingerprint.get(field)
                if isinstance(value, str):
                    target[value].append(attempt_id)
    return {
        "by_correctness_key": {
            key: sorted(value) for key, value in sorted(correctness.items())
        },
        "by_geometry_fingerprint": {
            key: sorted(value) for key, value in sorted(geometry.items())
        },
        "by_structural_fingerprint": {
            key: sorted(value) for key, value in sorted(structural.items())
        },
    }


def _statistics(attempts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    outcomes = Counter(str(attempt.get("outcome", "unknown")) for attempt in attempts)
    categories: Counter[str] = Counter()
    stages: Counter[str] = Counter()
    complete_keys = 0
    correctness_keys: set[str] = set()
    geometry_keys: set[str] = set()
    structural_keys: Counter[str] = Counter()
    for attempt in attempts:
        failure = attempt.get("failure")
        if isinstance(failure, Mapping):
            categories[str(failure.get("category", "unknown"))] += 1
            stages[str(failure.get("stage", "unknown"))] += 1
        key = attempt.get("correctness_key")
        if isinstance(key, Mapping):
            if key.get("complete") is True:
                complete_keys += 1
            if isinstance(key.get("sha256"), str):
                correctness_keys.add(str(key["sha256"]))
        fingerprint = attempt.get("geometry_fingerprint")
        if isinstance(fingerprint, Mapping):
            exact = fingerprint.get("sha256")
            structural = fingerprint.get("structural_sha256")
            if isinstance(exact, str):
                geometry_keys.add(exact)
            if isinstance(structural, str):
                structural_keys[structural] += 1
    return {
        "attempt_count": len(attempts),
        "complete_correctness_key_count": complete_keys,
        "unique_correctness_key_count": len(correctness_keys),
        "unique_geometry_fingerprint_count": len(geometry_keys),
        "unique_structural_fingerprint_count": len(structural_keys),
        "repeated_structural_fingerprint_count": sum(
            1 for count in structural_keys.values() if count > 1
        ),
        "outcomes": dict(sorted(outcomes.items())),
        "failure_categories": dict(sorted(categories.items())),
        "failure_stages": dict(sorted(stages.items())),
    }


def new_ledger() -> dict[str, object]:
    return {
        "schema": LEDGER_SCHEMA,
        "safety_contract": dict(SAFETY_CONTRACT),
        "policy": dict(LEDGER_POLICY),
        "attempts": [],
        "indexes": {
            "by_correctness_key": {},
            "by_geometry_fingerprint": {},
            "by_structural_fingerprint": {},
        },
        "statistics": {
            "attempt_count": 0,
            "complete_correctness_key_count": 0,
            "unique_correctness_key_count": 0,
            "unique_geometry_fingerprint_count": 0,
            "unique_structural_fingerprint_count": 0,
            "repeated_structural_fingerprint_count": 0,
            "outcomes": {},
            "failure_categories": {},
            "failure_stages": {},
        },
    }


def _assert_privacy_minimized(value: object) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).casefold()
            if key in FORBIDDEN_LEDGER_KEYS:
                raise LedgerError("ledger_contains_forbidden_private_field")
            _assert_privacy_minimized(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_privacy_minimized(item)
        return
    if isinstance(value, str):
        lowered = value.casefold()
        if (
            re.search(r"[a-z]:[\\/]", value, flags=re.IGNORECASE)
            or value.startswith("\\\\")
            or lowered.startswith("/users/")
            or lowered.startswith("/home/")
        ):
            raise LedgerError("ledger_contains_private_path")


def _validate_ledger(ledger: object) -> dict[str, object]:
    if not isinstance(ledger, dict):
        raise LedgerError("ledger_root_must_be_object")
    if ledger.get("schema") != LEDGER_SCHEMA:
        raise LedgerError("unsupported_ledger_schema")
    if ledger.get("safety_contract") != SAFETY_CONTRACT:
        raise LedgerError("ledger_safety_contract_changed")
    if ledger.get("policy") != LEDGER_POLICY:
        raise LedgerError("ledger_policy_changed")
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise LedgerError("ledger_attempts_must_be_array")
    seen: set[str] = set()
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise LedgerError("ledger_attempt_must_be_object")
        _assert_privacy_minimized(attempt)
        attempt_id = attempt.get("attempt_id")
        if not isinstance(attempt_id, str) or not SHA256_RE.fullmatch(attempt_id):
            raise LedgerError("invalid_attempt_id")
        if attempt_id in seen:
            raise LedgerError("duplicate_attempt_id")
        seen.add(attempt_id)
        if attempt.get("outcome") not in {
            "failed",
            "passed",
            "running",
            "preflight_passed",
            "incomplete",
        }:
            raise LedgerError("invalid_attempt_outcome")
        artifact_set_sha256 = attempt.get("artifact_set_sha256")
        if not isinstance(artifact_set_sha256, str) or not SHA256_RE.fullmatch(
            artifact_set_sha256
        ):
            raise LedgerError("invalid_artifact_set_sha256")
        identity_anchor_sha256 = attempt.get("identity_anchor_sha256")
        if not isinstance(
            identity_anchor_sha256, str
        ) or not SHA256_RE.fullmatch(identity_anchor_sha256):
            raise LedgerError("invalid_identity_anchor_sha256")
        events = attempt.get("events")
        if not isinstance(events, list) or not events:
            raise LedgerError("attempt_events_must_be_nonempty_array")
        event_digests: dict[str, str] = {}
        for event in events:
            if not isinstance(event, Mapping):
                raise LedgerError("invalid_artifact_event")
            kind = event.get("kind")
            digest = event.get("artifact_sha256")
            if kind not in ARTIFACT_SUFFIXES or not isinstance(digest, str):
                raise LedgerError("invalid_artifact_event")
            if not SHA256_RE.fullmatch(digest) or kind in event_digests:
                raise LedgerError("invalid_artifact_event")
            event_digests[str(kind)] = digest
        expected_artifact_set = _canonical_sha256(
            event_digests, domain="radial-artifact-set-v1"
        )
        if expected_artifact_set != artifact_set_sha256:
            raise LedgerError("artifact_set_digest_mismatch")
        fingerprint = attempt.get("geometry_fingerprint")
        if not isinstance(fingerprint, Mapping):
            raise LedgerError("invalid_geometry_fingerprint")
        evidence = fingerprint.get("evidence")
        structural_basis = fingerprint.get("structural_basis")
        if not isinstance(evidence, Mapping) or not isinstance(
            structural_basis, Mapping
        ):
            raise LedgerError("invalid_geometry_fingerprint")
        expected_geometry_sha = _canonical_sha256(
            {"schema": GEOMETRY_SCHEMA, "evidence": evidence},
            domain="radial-geometry-fingerprint-v1",
        )
        expected_structural_sha = _canonical_sha256(
            structural_basis,
            domain="radial-geometry-structure-v1",
        )
        if fingerprint.get("sha256") != expected_geometry_sha:
            raise LedgerError("geometry_fingerprint_digest_mismatch")
        if fingerprint.get("structural_sha256") != expected_structural_sha:
            raise LedgerError("structural_fingerprint_digest_mismatch")
        if fingerprint.get("structural_use") != "review_and_statistics_only":
            raise LedgerError("structural_fingerprint_use_changed")
        correctness = attempt.get("correctness_key")
        if (
            not isinstance(correctness, Mapping)
            or not isinstance(correctness.get("sha256"), str)
            or not SHA256_RE.fullmatch(str(correctness.get("sha256")))
        ):
            raise LedgerError("invalid_correctness_key")
        expected_correctness_sha = _canonical_sha256(
            {
                "schema": CORRECTNESS_SCHEMA,
                "launcher_schema": correctness.get("launcher_schema"),
                "geometry_sha256": fingerprint.get("sha256"),
                "configuration": attempt.get("configuration"),
                "safety_contract": SAFETY_CONTRACT,
            },
            domain="radial-correctness-key-v1",
        )
        if correctness.get("sha256") != expected_correctness_sha:
            raise LedgerError("correctness_key_digest_mismatch")
        expected_attempt_id = _canonical_sha256(
            {
                "correctness_sha256": correctness["sha256"],
                "identity_anchor_sha256": identity_anchor_sha256,
            },
            domain="radial-attempt-id-v1",
        )
        if expected_attempt_id != attempt_id:
            raise LedgerError("attempt_id_digest_mismatch")
        assessment = attempt.get("safety_assessment")
        if not isinstance(assessment, Mapping) or assessment.get(
            "safety_contract"
        ) != SAFETY_CONTRACT:
            raise LedgerError("attempt_safety_contract_changed")
        if assessment.get("automatic_retry_allowed") is not False:
            raise LedgerError("automatic_retry_must_remain_disabled")
        failure = attempt.get("failure")
        if failure is not None:
            if not isinstance(failure, Mapping):
                raise LedgerError("invalid_failure_record")
            code = failure.get("code")
            if not _is_known_failure_code(code) and code != "unclassified_error":
                raise LedgerError("failure_code_not_allowlisted")
            evidence = failure.get("evidence")
            if not isinstance(evidence, Mapping):
                raise LedgerError("invalid_failure_evidence")
            allowed_evidence = (
                SAFE_FAILURE_NUMERIC_FIELDS
                | SAFE_PREFIXED_FAILURE_FIELDS
                | {"phase"}
            )
            if any(key not in allowed_evidence for key in evidence):
                raise LedgerError("failure_evidence_field_not_allowlisted")
        for recommendation in attempt.get("recommendations", []):
            if not isinstance(recommendation, Mapping):
                raise LedgerError("invalid_recommendation")
            if recommendation.get("automatic_run_allowed") is not False:
                raise LedgerError("automatic_retry_must_remain_disabled")
            if recommendation.get("safety_contract") != SAFETY_CONTRACT:
                raise LedgerError("recommendation_safety_contract_changed")
            if recommendation.get("action") not in RECOMMENDATION_ACTIONS:
                raise LedgerError("recommendation_action_not_allowlisted")
            if recommendation.get("next_mode") != "preflight_only":
                raise LedgerError("recommendation_must_be_preflight_only")
            if recommendation.get("required_before_run") != REQUIRED_BEFORE_RUN:
                raise LedgerError("recommendation_run_requirements_changed")
            if recommendation.get("prohibited_changes") != PROHIBITED_CHANGES:
                raise LedgerError("recommendation_prohibitions_changed")
        expected_recommendations = _recommend_next_attempts(
            failure if isinstance(failure, Mapping) else None,
            fingerprint,
        )
        if _canonical_bytes(attempt.get("recommendations")) != _canonical_bytes(
            expected_recommendations
        ):
            raise LedgerError("recommendations_do_not_match_failure_evidence")
    expected_indexes = _indexes(attempts)
    if ledger.get("indexes") != expected_indexes:
        raise LedgerError("ledger_indexes_do_not_match_attempts")
    expected_statistics = _statistics(attempts)
    if ledger.get("statistics") != expected_statistics:
        raise LedgerError("ledger_statistics_do_not_match_attempts")
    return ledger


def _merge_attempt_progress(
    existing: Mapping[str, object],
    incoming: Mapping[str, object],
) -> dict[str, object]:
    if _canonical_bytes(existing) == _canonical_bytes(incoming):
        return dict(existing)
    for field in (
        "attempt_id",
        "identity_anchor_sha256",
        "configuration",
        "geometry_fingerprint",
        "correctness_key",
    ):
        if _canonical_bytes(existing.get(field)) != _canonical_bytes(
            incoming.get(field)
        ):
            raise LedgerError("attempt_progress_identity_conflict")
    old_outcome = str(existing.get("outcome"))
    new_outcome = str(incoming.get("outcome"))
    terminal = {"passed", "failed"}
    if old_outcome in terminal and new_outcome in terminal:
        raise LedgerError("attempt_terminal_outcome_conflict")
    ranks = {
        "incomplete": 0,
        "preflight_passed": 1,
        "running": 2,
        "passed": 3,
        "failed": 3,
    }
    old_rank = ranks.get(old_outcome, -1)
    new_rank = ranks.get(new_outcome, -1)
    if new_rank > old_rank:
        return dict(incoming)
    if old_rank > new_rank:
        return dict(existing)
    raise LedgerError("ambiguous_same_stage_attempt_progress")


def merge_attempts(
    ledger: Mapping[str, object] | None,
    attempts: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    base = new_ledger() if ledger is None else _validate_ledger(dict(ledger))
    merged: dict[str, dict[str, object]] = {
        str(item["attempt_id"]): dict(item)
        for item in base.get("attempts", [])
        if isinstance(item, Mapping)
    }
    for raw_attempt in attempts:
        attempt = dict(raw_attempt)
        attempt_id = attempt.get("attempt_id")
        if not isinstance(attempt_id, str) or not SHA256_RE.fullmatch(attempt_id):
            raise LedgerError("invalid_attempt_id")
        existing = merged.get(attempt_id)
        merged[attempt_id] = (
            attempt
            if existing is None
            else _merge_attempt_progress(existing, attempt)
        )
    ordered = [merged[key] for key in sorted(merged)]
    result = new_ledger()
    result["attempts"] = ordered
    result["indexes"] = _indexes(ordered)
    result["statistics"] = _statistics(ordered)
    return _validate_ledger(result)


def load_ledger(path: str | os.PathLike[str]) -> dict[str, object]:
    ledger_path = Path(path)
    if ledger_path.is_symlink():
        raise LedgerError("ledger_symlink_rejected")
    if not ledger_path.exists():
        return new_ledger()
    if not ledger_path.is_file() or ledger_path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise LedgerError("ledger_file_invalid")
    try:
        payload = json.loads(
            ledger_path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LedgerError("ledger_is_not_utf8_json") from exc
    return _validate_ledger(payload)


def write_ledger_atomic(
    path: str | os.PathLike[str], ledger: Mapping[str, object]
) -> None:
    payload = _validate_ledger(dict(ledger))
    ledger_path = Path(path)
    if ledger_path.is_symlink():
        raise LedgerError("ledger_symlink_rejected")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=ledger_path.name + ".",
        suffix=".tmp",
        dir=str(ledger_path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                + b"\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, ledger_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def ingest(
    ledger_path: str | os.PathLike[str],
    sources: Sequence[str | os.PathLike[str]],
) -> dict[str, object]:
    groups = collect_artifact_groups(sources)
    attempts = [build_attempt_record(group) for group in groups]
    ledger = merge_attempts(load_ledger(ledger_path), attempts)
    write_ledger_atomic(ledger_path, ledger)
    return ledger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser(
        "ingest", help="merge launcher artifacts into a ledger"
    )
    ingest_parser.add_argument("--ledger", required=True)
    ingest_parser.add_argument("sources", nargs="+")
    validate_parser = subparsers.add_parser(
        "validate", help="validate a ledger and print its safe statistics"
    )
    validate_parser.add_argument("--ledger", required=True)
    summary_parser = subparsers.add_parser(
        "summary", help="print safe cross-model failure statistics"
    )
    summary_parser.add_argument("--ledger", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            ledger = ingest(args.ledger, args.sources)
            output = {
                "schema": LEDGER_SCHEMA,
                "status": "ledger_updated",
                "statistics": ledger["statistics"],
            }
        else:
            ledger = load_ledger(args.ledger)
            output = {
                "schema": LEDGER_SCHEMA,
                "status": "ledger_valid" if args.command == "validate" else "summary",
                "statistics": ledger["statistics"],
            }
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except LedgerError as exc:
        print(
            json.dumps(
                {
                    "schema": LEDGER_SCHEMA,
                    "status": "failed",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
