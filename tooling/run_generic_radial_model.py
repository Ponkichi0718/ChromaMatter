#!/usr/bin/env python3
"""Fail-closed launcher for one selected part of an arbitrary OBJ/GLB.

This is intentionally a tooling-only adapter around the production generic
APIs.  It does not contain Ninja/model-specific geometry logic and it does not
weaken any Radial Stage-B or 3MF validation gate.  The default action is a
read-only geometry/colour preflight; ``--run`` is required before TetGen and
the expensive exact partition are allowed to start.

``--target-faces`` is the target for *whole-assembly* ``prepare_geometry`` and
is only applied when ``--adjust-face-count`` is present.  A selected-part QEM
target would be a different operation and is deliberately not approximated by
this launcher.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXED_APP = REPO_ROOT / "source" / "fixed_app"
if str(FIXED_APP) not in sys.path:
    sys.path.insert(0, str(FIXED_APP))

from spectrum_mapper.engine import (  # noqa: E402
    load_vertex_color_model,
    mesh_quality,
    prepare_geometry,
    recolor_level_parts,
)
from spectrum_mapper.mixer import normalize_hex  # noqa: E402
from spectrum_mapper.models import (  # noqa: E402
    AppSettings,
    GeometrySettings,
    PaletteSettings,
    RADIAL_CONVERSION_SELECTIVE_HYBRID,
    RADIAL_SKIN_MODE_ADAPTIVE,
    RadialSettings,
    ToneSettings,
)
from spectrum_mapper.parts import validate_part_layout  # noqa: E402
from spectrum_mapper.radial_thickness import (  # noqa: E402
    derive_radial_thickness_schedule,
)
from spectrum_mapper.radial_export import (  # noqa: E402
    radial_process_profile_sparse_infill_percent,
)
from spectrum_mapper.radial_workflow import (  # noqa: E402
    _radial_process_profile,
    analyze_radial_partner_contrast,
    export_radial_bundle,
)
from spectrum_mapper.workflow import _extract_prepared_part  # noqa: E402


SCHEMA = "chromamatter.tooling.generic-radial-launcher.v3"
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class PreflightError(RuntimeError):
    """Stable tooling diagnostic raised before an expensive export."""

    def __init__(self, code: str, details: dict[str, object] | None = None):
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(self.code)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    return value


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2))


def _slug(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip("-._")
    return text[:96] or "part"


def _normalize_palette(values: Sequence[str]) -> tuple[str, str, str, str]:
    if len(values) != 4:
        raise PreflightError(
            "four_physical_colors_required", {"actual": len(values)}
        )
    normalized: list[str] = []
    for index, raw in enumerate(values):
        text = str(raw).strip()
        if not HEX_RE.fullmatch(text):
            raise PreflightError(
                "invalid_physical_color",
                {"slot": index + 1, "value": raw, "format": "#RRGGBB"},
            )
        normalized.append(normalize_hex(text))
    return tuple(normalized)  # type: ignore[return-value]


def _settings_from_args(args: argparse.Namespace) -> AppSettings:
    palette = PaletteSettings(physical_hex=list(_normalize_palette(args.palette)))
    geometry = GeometrySettings(
        height_mm=float(args.height_mm),
        target_faces=int(args.target_faces),
        preview_faces=int(args.preview_faces),
        adjust_face_count=bool(args.adjust_face_count),
        preserve_parts=True,
        solidify_parts=False,
    )
    tone = ToneSettings(
        black_point=float(args.black_point),
        white_point=float(args.white_point),
        gamma=float(args.tone_gamma),
        contrast=float(args.contrast),
        saturation=float(args.saturation),
    )
    radial = RadialSettings(
        experimental_enabled=True,
        outer_skin_thickness_mm=float(args.outer_skin_thickness),
        layer_height_mm=0.10,
        minimum_lstar_delta=float(args.minimum_lstar_delta),
        wall_generator="arachne",
        conversion_mode=RADIAL_CONVERSION_SELECTIVE_HYBRID,
        skin_thickness_mode=RADIAL_SKIN_MODE_ADAPTIVE,
        adaptive_skin_min_thickness_mm=float(args.adaptive_min),
        adaptive_skin_max_thickness_mm=float(args.adaptive_max),
        adaptive_skin_gamma=float(args.adaptive_gamma),
        adaptive_skin_bands=int(args.bands),
        require_uniform_black_mix=False,
    )
    return AppSettings(
        geometry=geometry,
        tone=tone,
        palette=palette,
        radial=radial,
    )


def _configuration_summary(
    args: argparse.Namespace, settings: AppSettings
) -> dict[str, object]:
    process_profile = _radial_process_profile(settings)
    sparse_infill = radial_process_profile_sparse_infill_percent(
        process_profile
    )
    if int(sparse_infill) != 15:
        raise PreflightError(
            "unexpected_sparse_infill_profile",
            {
                "process_profile": process_profile,
                "actual_percent": sparse_infill,
                "required_percent": 15,
            },
        )
    return {
        "input": str(Path(args.input).resolve()) if args.input else None,
        "part_key": args.part_key,
        "part_name": args.part_name,
        "physical_hex": list(settings.palette.physical_hex),
        "black_slot_zero_based": int(args.black_slot) - 1,
        "black_extruder": int(args.black_slot),
        "geometry": {
            "height_mm": float(settings.geometry.height_mm),
            "target_faces": int(settings.geometry.target_faces),
            "target_faces_scope": "whole_prepared_assembly",
            "adjust_face_count": bool(settings.geometry.adjust_face_count),
            "preview_faces": int(settings.geometry.preview_faces),
            "preserve_parts": True,
            "solidify_parts": False,
        },
        "tone": {
            "black_point": float(settings.tone.black_point),
            "white_point": float(settings.tone.white_point),
            "gamma": float(settings.tone.gamma),
            "contrast": float(settings.tone.contrast),
            "saturation": float(settings.tone.saturation),
        },
        "radial": {
            "conversion_mode": settings.radial.conversion_mode,
            "skin_thickness_mode": settings.radial.skin_thickness_mode,
            "wall_generator": settings.radial.wall_generator,
            "layer_height_mm": float(settings.radial.layer_height_mm),
            "process_profile": process_profile,
            "sparse_infill_density_percent": int(sparse_infill),
            "minimum_lstar_delta": float(
                settings.radial.minimum_lstar_delta
            ),
            "adaptive_min_thickness_mm": float(
                settings.radial.adaptive_skin_min_thickness_mm
            ),
            "adaptive_max_thickness_mm": float(
                settings.radial.adaptive_skin_max_thickness_mm
            ),
            "adaptive_gamma": float(settings.radial.adaptive_skin_gamma),
            "adaptive_bands": int(settings.radial.adaptive_skin_bands),
        },
        "strict_preflight_gate": {
            "minimum_active_bands": int(args.minimum_active_bands),
            "minimum_inter_band_thresholds": int(
                args.minimum_inter_band_thresholds
            ),
            "minimum_faces_per_active_band": int(
                args.minimum_faces_per_active_band
            ),
        },
        "output_root": (
            str(Path(args.output_root).resolve()) if args.output_root else None
        ),
    }


def _available_parts(prepared: object) -> list[dict[str, object]]:
    level = prepared.final
    layout = validate_part_layout(level)
    names = tuple(level.part_names)
    result: list[dict[str, object]] = []
    for part_id, key in enumerate(layout.part_keys):
        raw_name = names[part_id] if part_id < len(names) else ""
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        result.append(
            {
                "part_id": int(part_id),
                "part_key": str(key),
                "part_name": name or str(key),
                "faces": int(np.count_nonzero(layout.face_part_ids == part_id)),
            }
        )
    return result


def _resolve_part(
    prepared: object,
    *,
    part_key: str | None,
    part_name: str | None,
) -> dict[str, object]:
    parts = _available_parts(prepared)
    if bool(part_key) == bool(part_name):
        raise PreflightError(
            "exactly_one_part_selector_required",
            {"part_key": part_key, "part_name": part_name},
        )
    if part_key:
        matches = [item for item in parts if item["part_key"] == part_key]
        selector = {"part_key": part_key}
    else:
        matches = [item for item in parts if item["part_name"] == part_name]
        selector = {"part_name": part_name}
    if not matches:
        raise PreflightError(
            "selected_part_not_found",
            {**selector, "available_parts": parts},
        )
    if len(matches) != 1:
        raise PreflightError(
            "selected_part_ambiguous",
            {**selector, "matches": matches},
        )
    return matches[0]


def _strict_self_intersection_gate(
    quality: dict[str, object],
) -> dict[str, object]:
    """Require a completed actual check with exactly zero selected faces."""

    raw_count = quality.get("self_intersecting_faces")
    if (
        isinstance(raw_count, (bool, np.bool_))
        or not isinstance(raw_count, (int, np.integer))
        or int(raw_count) < 0
    ):
        raise PreflightError(
            "selected_part_self_intersection_unverified",
            {
                "reason": "unknown_self_intersection_count",
                "self_intersecting_faces": raw_count,
                "required": 0,
            },
        )
    count = int(raw_count)
    if count > 0:
        raise PreflightError(
            "selected_part_self_intersection_detected",
            {
                "self_intersecting_faces": count,
                "self_intersecting_area": quality.get(
                    "self_intersecting_area"
                ),
                "self_intersecting_area_fraction": quality.get(
                    "self_intersecting_area_fraction"
                ),
                "self_intersecting_face_ids": quality.get(
                    "self_intersecting_face_ids"
                ),
                "self_intersecting_face_ids_complete": quality.get(
                    "self_intersecting_face_ids_complete"
                ),
                "required": 0,
            },
        )

    complete = quality.get("self_intersecting_face_ids_complete")
    raw_ids = quality.get("self_intersecting_face_ids")
    metrics = {
        "self_intersecting_area": quality.get("self_intersecting_area"),
        "self_intersecting_area_fraction": quality.get(
            "self_intersecting_area_fraction"
        ),
        "maximum_self_intersecting_face_area": quality.get(
            "maximum_self_intersecting_face_area"
        ),
    }
    finite_zero_metrics = all(
        not isinstance(value, (bool, np.bool_))
        and isinstance(value, (int, float, np.integer, np.floating))
        and np.isfinite(float(value))
        and float(value) == 0.0
        for value in metrics.values()
    )
    if (
        complete is not True
        or not isinstance(raw_ids, list)
        or raw_ids
        or not finite_zero_metrics
    ):
        raise PreflightError(
            "selected_part_self_intersection_unverified",
            {
                "reason": "self_intersection_check_incomplete",
                "self_intersecting_faces": count,
                "self_intersecting_face_ids": raw_ids,
                "self_intersecting_face_ids_complete": complete,
                **metrics,
                "required": 0,
            },
        )
    return {
        "policy": "actual_selected_post_qem_strict_zero",
        "check_requested": True,
        "check_completed": True,
        "self_intersecting_faces": 0,
        **metrics,
        "self_intersecting_face_ids": [],
        "self_intersecting_face_ids_complete": True,
        "strict_zero_verified": True,
        "run_allowed": True,
    }


def _check_topology(selected: object) -> dict[str, object]:
    topology = dict(selected.topology)
    try:
        quality = mesh_quality(
            selected.final.vertices_unit,
            selected.final.faces,
            check_self_intersections=True,
        )
    except Exception as exc:
        raise PreflightError(
            "selected_part_self_intersection_check_failed",
            {
                "exception_type": type(exc).__name__,
                "error": str(exc),
            },
        ) from exc
    self_intersection_gate = _strict_self_intersection_gate(quality)
    failures: dict[str, object] = {}
    expected_zero = (
        "boundary_edges",
        "nonmanifold_edges",
        "inconsistent_winding_edges",
        "degenerate_faces",
    )
    for field in expected_zero:
        value = int(quality.get(field, topology.get(field, -1)))
        if value != 0:
            failures[field] = value
    for field in ("watertight", "winding_consistent", "positive_volume"):
        if not bool(quality.get(field, False)):
            failures[field] = quality.get(field)
    if int(quality.get("body_count", 0)) != 1:
        failures["body_count"] = quality.get("body_count")
    if failures:
        raise PreflightError(
            "selected_part_topology_gate_failed",
            {"failures": failures, "topology": topology, "quality": quality},
        )
    return {
        "edge_topology": topology,
        "solid_quality": quality,
        "self_intersection_gate": self_intersection_gate,
    }


def _qem_provenance_warnings(
    multipart: dict[str, object],
    selected_record: dict[str, object],
) -> list[dict[str, object]]:
    """Describe non-authoritative QEM ancestry records without trusting them."""

    geometry_preserved = selected_record.get(
        "source_triangle_geometry_preserved",
        multipart.get("source_triangle_geometry_preserved"),
    )
    ancestry_proven = selected_record.get(
        "source_triangle_ancestry_proven",
        multipart.get("source_triangle_ancestry_proven"),
    )
    checks = (
        (
            "record_valid",
            selected_record.get("record_valid"),
            "selected_qem_record_not_valid",
            "Selected-part QEM provenance record is false or unavailable.",
        ),
        (
            "source_triangle_geometry_preserved",
            geometry_preserved,
            "selected_source_triangle_geometry_not_preserved",
            "Selected post-QEM geometry is not proven identical to source triangles.",
        ),
        (
            "source_triangle_ancestry_proven",
            ancestry_proven,
            "selected_source_triangle_ancestry_not_proven",
            "Selected post-QEM triangle ancestry is false or unavailable.",
        ),
    )
    return [
        {
            "severity": "warning",
            "code": code,
            "field": field,
            "actual": value,
            "message": message,
            "run_authority": (
                "actual_selected_post_qem_self_intersection_strict_zero"
            ),
        }
        for field, value, code, message in checks
        if value is not True
    ]


def _preparation_provenance(
    prepared: object, selected_part_id: int
) -> dict[str, object]:
    """Publish the bounded-QEM facts relevant to the selected part."""

    assembly = dict(prepared.assembly or {})
    stats = (
        dict(prepared.part_stats[selected_part_id])
        if 0 <= selected_part_id < len(prepared.part_stats)
        else {}
    )
    multipart = dict(
        assembly.get("multipart_self_intersection_provenance") or {}
    )
    part_records = multipart.get("parts")
    selected_record: dict[str, object] = {}
    if isinstance(part_records, list):
        selected_record = next(
            (
                dict(item)
                for item in part_records
                if isinstance(item, dict)
                and int(item.get("part_id", -1)) == int(selected_part_id)
            ),
            {},
        )
    raw_face_provenance = np.asarray(prepared.final.face_provenance)
    provenance_counts: dict[str, int] = {}
    if raw_face_provenance.shape == (len(prepared.final.faces),):
        values, counts = np.unique(raw_face_provenance, return_counts=True)
        provenance_counts = {
            str(int(value)): int(count)
            for value, count in zip(values, counts, strict=True)
        }
    qem_warnings = _qem_provenance_warnings(multipart, selected_record)
    return {
        "selected_part_stats": stats,
        "generated_surface_provenance": dict(
            assembly.get("generated_surface_provenance") or {}
        ),
        "face_provenance_origin_counts": provenance_counts,
        "multipart_qem": {
            "simplification_applied": multipart.get(
                "simplification_applied"
            ),
            "warning_policy": multipart.get("warning_policy"),
            "source_triangle_geometry_preserved": multipart.get(
                "source_triangle_geometry_preserved"
            ),
            "source_triangle_ancestry_proven": multipart.get(
                "source_triangle_ancestry_proven"
            ),
            "qem_max_output_ratio_numerator": multipart.get(
                "qem_max_output_ratio_numerator"
            ),
            "qem_max_output_ratio_denominator": multipart.get(
                "qem_max_output_ratio_denominator"
            ),
            "selected_part_record": selected_record,
            "warnings": qem_warnings,
            "warnings_are_advisory_only": True,
            "run_authority": (
                "actual_selected_post_qem_self_intersection_strict_zero"
            ),
        },
    }


def _gate_active_bands(
    face_counts_by_thickness: dict[float, int],
    *,
    minimum_active_bands: int,
    minimum_inter_band_thresholds: int,
    minimum_faces_per_active_band: int,
) -> dict[str, object]:
    active = sorted(
        float(value)
        for value, count in face_counts_by_thickness.items()
        if int(count) >= int(minimum_faces_per_active_band)
    )
    thin = {
        f"{float(value):.9f}": int(count)
        for value, count in sorted(face_counts_by_thickness.items())
        if int(count) < int(minimum_faces_per_active_band)
    }
    # A schedule with N physical depth bands has N-1 inter-band transitions.
    # The exact partition also evaluates the N absolute outer-depth boundaries;
    # both counts are published so callers cannot confuse the two meanings.
    transitions = max(0, len(active) - 1)
    details = {
        "active_thicknesses_mm": active,
        "active_band_count": len(active),
        "inter_band_threshold_count": transitions,
        "partition_outer_depth_boundary_count": len(active),
        "minimum_faces_per_active_band": int(minimum_faces_per_active_band),
        "underpopulated_thicknesses": thin,
    }
    if len(active) < int(minimum_active_bands):
        raise PreflightError(
            "insufficient_active_adaptive_bands",
            {
                **details,
                "required_active_bands": int(minimum_active_bands),
            },
        )
    if transitions < int(minimum_inter_band_thresholds):
        raise PreflightError(
            "insufficient_inter_band_thresholds",
            {
                **details,
                "required_inter_band_thresholds": int(
                    minimum_inter_band_thresholds
                ),
            },
        )
    return details


def _preflight(
    args: argparse.Namespace, settings: AppSettings
) -> tuple[object, dict[str, object]]:
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise PreflightError("input_model_not_found", {"input": input_path})

    asset = load_vertex_color_model(input_path)
    prepared = prepare_geometry(asset, settings.geometry)
    parts = _available_parts(prepared)
    part = _resolve_part(
        prepared,
        part_key=args.part_key,
        part_name=args.part_name,
    )
    selected, source_face_ids = _extract_prepared_part(
        prepared, int(part["part_id"])
    )
    topology = _check_topology(selected)

    colors = recolor_level_parts(
        selected.final,
        settings.geometry.height_mm,
        settings.tone,
        settings.palette,
        {},
    )
    states = np.asarray(colors.palette_indices, dtype=np.int16)
    state_counts = Counter(int(value) for value in states.tolist())
    used_state_ids = set(state_counts)
    black_slot = int(args.black_slot) - 1
    contrast = analyze_radial_partner_contrast(settings, black_slot)
    eligible = {
        int(state_id): int(partner)
        for state_id, partner in contrast.eligible_state_partners.items()
        if int(state_id) in used_state_ids
    }
    if not eligible:
        raise PreflightError(
            "no_used_contrast_eligible_black_mix",
            {
                "used_state_ids": sorted(used_state_ids),
                "contrast_states": [item.to_dict() for item in contrast.states],
            },
        )

    schedule = derive_radial_thickness_schedule(
        settings.palette,
        black_slot=black_slot,
        eligible_state_partners=eligible,
        minimum_thickness_mm=settings.radial.adaptive_skin_min_thickness_mm,
        maximum_thickness_mm=settings.radial.adaptive_skin_max_thickness_mm,
        band_count=settings.radial.adaptive_skin_bands,
        gamma=settings.radial.adaptive_skin_gamma,
        basis="target_lstar",
    )
    thickness_by_state = schedule.thickness_by_state
    counts_by_thickness: dict[float, int] = {}
    for state_id, thickness in thickness_by_state.items():
        canonical = round(float(thickness), 9)
        counts_by_thickness[canonical] = (
            counts_by_thickness.get(canonical, 0) + state_counts[state_id]
        )
    active_gate = _gate_active_bands(
        counts_by_thickness,
        minimum_active_bands=args.minimum_active_bands,
        minimum_inter_band_thresholds=args.minimum_inter_band_thresholds,
        minimum_faces_per_active_band=args.minimum_faces_per_active_band,
    )
    conventional_faces = int(
        sum(count for state, count in state_counts.items() if state not in eligible)
    )
    if conventional_faces <= 0:
        raise PreflightError(
            "hybrid_conventional_surface_required",
            {"eligible_state_ids": sorted(eligible), "state_counts": state_counts},
        )
    preparation_provenance = _preparation_provenance(
        prepared, int(part["part_id"])
    )
    multipart_qem = preparation_provenance.get("multipart_qem", {})
    qem_warnings = (
        list(multipart_qem.get("warnings", []))
        if isinstance(multipart_qem, dict)
        and isinstance(multipart_qem.get("warnings"), list)
        else []
    )

    report: dict[str, object] = {
        "schema": SCHEMA,
        "status": "preflight_passed",
        "created_utc": _utc_now(),
        "configuration": _configuration_summary(args, settings),
        "source": {
            "path": input_path,
            "sha256": str(asset.sha256),
            "bytes": int(asset.file_size),
            "source_vertices": int(len(asset.vertices)),
            "source_faces": int(len(asset.faces)),
            "source_part_count": int(len(asset.part_keys)),
            "prepared_vertices": int(len(prepared.final.vertices_unit)),
            "prepared_faces": int(len(prepared.final.faces)),
            "prepared_parts": parts,
            "warnings": list(prepared.warnings),
        },
        "selection": {
            **part,
            "selected_vertices": int(len(selected.final.vertices_unit)),
            "selected_faces": int(len(selected.final.faces)),
            "source_face_id_count": int(len(source_face_ids)),
        },
        "preparation_provenance": preparation_provenance,
        "preflight_warnings": qem_warnings,
        "topology": topology,
        "palette": {
            "source": "explicit_cli",
            "physical_hex": list(settings.palette.physical_hex),
            "black_extruder": int(args.black_slot),
            "used_state_face_counts": {
                str(state_id): int(count)
                for state_id, count in sorted(state_counts.items())
            },
            "eligible_used_state_partners": {
                str(state_id): int(partner)
                for state_id, partner in sorted(eligible.items())
            },
            "contrast_states": [item.to_dict() for item in contrast.states],
            "conventional_face_count": conventional_faces,
        },
        "adaptive_schedule": {
            **schedule.to_dict(),
            "eligible_face_count_by_state": {
                str(state_id): int(state_counts[state_id])
                for state_id in sorted(eligible)
            },
            "face_count_by_thickness_mm": {
                f"{float(thickness):.9f}": int(count)
                for thickness, count in sorted(counts_by_thickness.items())
            },
            "strict_gate": active_gate,
        },
    }
    return prepared, report


def _progress(phase: str, fraction: float, message: str) -> None:
    print(
        json.dumps(
            {
                "event": "progress",
                "phase": str(phase),
                "fraction": float(fraction),
                "message": str(message),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def _error_payload(exc: BaseException) -> dict[str, object]:
    return {
        "exception_type": type(exc).__name__,
        "code": str(getattr(exc, "code", type(exc).__name__)),
        "details": _jsonable(getattr(exc, "details", {})),
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }


def _self_check() -> dict[str, object]:
    palette = _normalize_palette(
        ["#111111", "#F5F5F5", "#2453C7", "#00A6C7"]
    )
    passed = _gate_active_bands(
        {0.1: 11, 0.166666667: 1264, 0.233333333: 2088},
        minimum_active_bands=2,
        minimum_inter_band_thresholds=2,
        minimum_faces_per_active_band=5,
    )
    two_band_passed = _gate_active_bands(
        {0.166666667: 1264, 0.233333333: 2088},
        minimum_active_bands=2,
        minimum_inter_band_thresholds=1,
        minimum_faces_per_active_band=5,
    )
    rejected = False
    try:
        _gate_active_bands(
            {0.1: 10, 0.2: 10},
            minimum_active_bands=2,
            minimum_inter_band_thresholds=2,
            minimum_faces_per_active_band=5,
        )
    except PreflightError as exc:
        rejected = exc.code == "insufficient_inter_band_thresholds"
    if not rejected:
        raise AssertionError("two-band/two-transition fail-closed check failed")

    tetra_vertices = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
        dtype=np.float64,
    )
    tetra_faces = np.asarray(
        ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
        dtype=np.int32,
    )
    actual_quality = mesh_quality(
        tetra_vertices,
        tetra_faces,
        check_self_intersections=True,
    )
    actual_gate = _strict_self_intersection_gate(actual_quality)

    verified_zero = {
        "self_intersecting_faces": 0,
        "self_intersecting_area": 0.0,
        "self_intersecting_area_fraction": 0.0,
        "maximum_self_intersecting_face_area": 0.0,
        "self_intersecting_face_ids": [],
        "self_intersecting_face_ids_complete": True,
    }
    rejection_cases = (
        (
            "unknown",
            {**verified_zero, "self_intersecting_faces": -1},
            "selected_part_self_intersection_unverified",
        ),
        (
            "unchecked",
            {
                **verified_zero,
                "self_intersecting_face_ids_complete": False,
            },
            "selected_part_self_intersection_unverified",
        ),
        (
            "positive",
            {
                **verified_zero,
                "self_intersecting_faces": 2,
                "self_intersecting_area": 0.25,
                "self_intersecting_area_fraction": 0.1,
                "maximum_self_intersecting_face_area": 0.15,
                "self_intersecting_face_ids": [1, 2],
            },
            "selected_part_self_intersection_detected",
        ),
    )
    self_intersection_rejections: dict[str, str] = {}
    for name, quality, expected_code in rejection_cases:
        try:
            _strict_self_intersection_gate(quality)
        except PreflightError as exc:
            if exc.code != expected_code:
                raise AssertionError(
                    f"{name} self-intersection gate used {exc.code}"
                ) from exc
            self_intersection_rejections[name] = exc.code
        else:
            raise AssertionError(
                f"{name} self-intersection gate did not fail closed"
            )

    qem_warnings = _qem_provenance_warnings(
        {
            "source_triangle_geometry_preserved": False,
            "source_triangle_ancestry_proven": False,
        },
        {
            "record_valid": False,
            "source_triangle_geometry_preserved": False,
            "source_triangle_ancestry_proven": False,
        },
    )
    warning_codes = {str(item["code"]) for item in qem_warnings}
    expected_warning_codes = {
        "selected_qem_record_not_valid",
        "selected_source_triangle_geometry_not_preserved",
        "selected_source_triangle_ancestry_not_proven",
    }
    if warning_codes != expected_warning_codes:
        raise AssertionError("QEM provenance warnings are incomplete")
    return {
        "schema": SCHEMA,
        "status": "self_check_passed",
        "palette": palette,
        "gate": passed,
        "two_band_one_transition_gate": two_band_passed,
        "two_band_case_rejected": rejected,
        "actual_self_intersection_gate": actual_gate,
        "self_intersection_fail_closed_cases": self_intersection_rejections,
        "qem_provenance_warning_codes": sorted(warning_codes),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--input", help="source OBJ/GLB path")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--part-key")
    selection.add_argument("--part-name")
    parser.add_argument(
        "--palette",
        nargs=4,
        metavar=("F1", "F2", "F3", "F4"),
        help="four explicit physical #RRGGBB values",
    )
    parser.add_argument(
        "--black-slot",
        type=int,
        choices=(1, 2, 3, 4),
        help="one-based physical black slot",
    )
    parser.add_argument("--output-root")
    parser.add_argument("--height-mm", type=float, default=150.0)
    parser.add_argument("--target-faces", type=int, default=450_000)
    parser.add_argument("--preview-faces", type=int, default=80_000)
    parser.add_argument("--adjust-face-count", action="store_true")
    parser.add_argument("--bands", type=int, choices=(4, 5, 6), default=4)
    parser.add_argument("--adaptive-min", type=float, default=0.10)
    parser.add_argument("--adaptive-max", type=float, default=0.30)
    parser.add_argument("--adaptive-gamma", type=float, default=1.5)
    parser.add_argument("--outer-skin-thickness", type=float, default=0.15)
    parser.add_argument("--minimum-lstar-delta", type=float, default=35.0)
    parser.add_argument("--black-point", type=float, default=0.75)
    parser.add_argument("--white-point", type=float, default=0.875)
    parser.add_argument("--tone-gamma", type=float, default=1.2)
    parser.add_argument("--contrast", type=float, default=0.6)
    parser.add_argument("--saturation", type=float, default=1.0)
    parser.add_argument("--minimum-active-bands", type=int, default=2)
    parser.add_argument(
        "--minimum-inter-band-thresholds", type=int, default=2
    )
    parser.add_argument("--minimum-faces-per-active-band", type=int, default=5)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _validate_cli(args: argparse.Namespace) -> None:
    missing = [
        name
        for name, value in (
            ("--input", args.input),
            ("--part-key/--part-name", args.part_key or args.part_name),
            ("--palette", args.palette),
            ("--black-slot", args.black_slot),
            ("--output-root", args.output_root),
        )
        if value is None
    ]
    if missing:
        raise PreflightError("required_argument_missing", {"arguments": missing})
    integer_minima = {
        "target_faces": (args.target_faces, 4),
        "preview_faces": (args.preview_faces, 4),
        "minimum_active_bands": (args.minimum_active_bands, 2),
        "minimum_inter_band_thresholds": (
            args.minimum_inter_band_thresholds,
            1,
        ),
        "minimum_faces_per_active_band": (
            args.minimum_faces_per_active_band,
            1,
        ),
    }
    invalid = {
        name: int(value)
        for name, (value, minimum) in integer_minima.items()
        if int(value) < int(minimum)
    }
    if invalid:
        raise PreflightError("invalid_integer_limit", invalid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.self_check:
        _print_json(_self_check())
        return 0

    output_root: Path | None = None
    run_path: Path | None = None
    failed_path: Path | None = None
    try:
        _validate_cli(args)
        settings = _settings_from_args(args)
        config = _configuration_summary(args, settings)
        if args.dry_run:
            _print_json(
                {
                    "schema": SCHEMA,
                    "status": "dry_run",
                    "note": "configuration only; model was not loaded",
                    "configuration": config,
                }
            )
            return 0

        output_root = Path(args.output_root).resolve()
        selected_label = args.part_name or args.part_key or "part"
        job_slug = f"{_slug(Path(args.input).stem)}_{_slug(selected_label)}"
        precheck_path = output_root / f"{job_slug}_PRECHECK.json"
        run_path = output_root / f"{job_slug}_RUN.json"
        failed_path = output_root / f"{job_slug}_FAILED.json"
        destination = output_root / f"{job_slug}_radial.3mf"
        guarded = [precheck_path]
        if args.run:
            guarded.extend((run_path, failed_path, destination))
        existing = [path for path in guarded if path.exists()]
        if existing and not args.overwrite:
            raise PreflightError(
                "output_exists",
                {"paths": existing, "hint": "choose a new output root"},
            )

        prepared, preflight = _preflight(args, settings)
        _atomic_json(precheck_path, preflight)
        _print_json(preflight)
        if not args.run:
            return 0

        running = {
            "schema": SCHEMA,
            "status": "running",
            "started_utc": _utc_now(),
            "destination": destination,
            "precheck": preflight,
        }
        _atomic_json(run_path, running)
        result = export_radial_bundle(
            prepared,
            settings,
            destination,
            black_slot=int(args.black_slot) - 1,
            part_key=str(preflight["selection"]["part_key"]),
            progress=_progress,
        )
        completed = {
            **running,
            "status": "passed",
            "completed_utc": _utc_now(),
            "result": {
                "model_path": result.model_path,
                "report_path": result.report_path,
                "guide_path": result.guide_path,
                "process_profile": result.process_profile,
                "wall_generator": result.wall_generator,
                "skin_thickness_mm": result.skin_thickness_mm,
                "layer_height_mm": result.layer_height_mm,
                "validation": result.validation,
            },
        }
        _atomic_json(run_path, completed)
        _print_json(completed)
        return 0
    except BaseException as exc:
        failure = {
            "schema": SCHEMA,
            "status": "failed",
            "failed_utc": _utc_now(),
            "error": _error_payload(exc),
        }
        if (
            run_path is not None
            and args.run
            and (args.overwrite or not run_path.exists())
        ):
            _atomic_json(run_path, failure)
        if (
            failed_path is not None
            and (args.overwrite or not failed_path.exists())
        ):
            _atomic_json(failed_path, failure)
        _print_json(failure)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
