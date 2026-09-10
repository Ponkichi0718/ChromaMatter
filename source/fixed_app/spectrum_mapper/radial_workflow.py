from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .engine import (
    apply_palette_overrides_parts,
    emit,
    recolor_level_parts,
)
from .filament_database import srgb_hex_to_lab
from .mixer import normalize_hex, palette_mix_specs
from .models import (
    AppSettings,
    PreparedGeometry,
    ProgressCallback,
    RADIAL_CONVERSION_SELECTIVE_HYBRID,
    RADIAL_CONVERSION_UNIFORM_STAGE_A,
    RADIAL_SKIN_MODE_ADAPTIVE,
)
from .parts import resolve_part_palette_settings, validate_part_layout
from .radial_export import (
    RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010,
    RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
    RADIAL_PROCESS_PROFILE_MVP_020,
    package_from_radial_shell,
    radial_process_profile_sparse_infill_percent,
    write_radial_3mf_atomic,
)
from .radial_shell import RadialShellError, build_radial_shell_from_level


@dataclass(frozen=True)
class RadialBundleResult:
    model_path: Path
    report_path: Path
    guide_path: Path
    validation: dict[str, object]
    skin_thickness_mm: float
    layer_height_mm: float
    process_profile: str
    wall_generator: str


@dataclass(frozen=True, slots=True)
class RadialPartnerContrast:
    """CIELAB lightness gate for one zero-based black-mix palette state."""

    state_id: int
    black_extruder: int
    partner_extruder: int
    black_lstar: float
    partner_lstar: float
    lstar_delta: float
    qualifies: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "state_id": int(self.state_id),
            "black_extruder": int(self.black_extruder),
            "partner_extruder": int(self.partner_extruder),
            "black_lstar": float(self.black_lstar),
            "partner_lstar": float(self.partner_lstar),
            "lstar_delta": float(self.lstar_delta),
            "qualifies": bool(self.qualifies),
        }


@dataclass(frozen=True, slots=True)
class RadialContrastAnalysis:
    """All black-containing palette states after the radial contrast gate."""

    black_extruder: int
    black_lstar: float
    minimum_lstar_delta: float
    states: tuple[RadialPartnerContrast, ...]

    @property
    def eligible_state_partners(self) -> dict[int, int]:
        """Return the Stage-A mapping for contrast-qualified states only."""

        return {
            int(item.state_id): int(item.partner_extruder)
            for item in self.states
            if item.qualifies
        }

    def state(self, state_id: int) -> RadialPartnerContrast | None:
        """Return one analysed state without exposing mutable lookup state."""

        target = int(state_id)
        return next((item for item in self.states if item.state_id == target), None)


def _relative_srgb_luminance(value: str) -> float:
    """Return WCAG relative luminance for one validated physical colour."""

    text = normalize_hex(value)
    channels = np.asarray(
        [int(text[index : index + 2], 16) / 255.0 for index in (1, 3, 5)],
        dtype=np.float64,
    )
    linear = np.where(
        channels <= 0.04045,
        channels / 12.92,
        ((channels + 0.055) / 1.055) ** 2.4,
    )
    return float(
        0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    )


def _require_unique_darkest_black_slot(
    physical_hex: list[str] | tuple[str, ...],
    black_slot: int,
) -> None:
    """Fail closed unless ``black_slot`` is the one darkest physical spool."""

    selected = int(black_slot)
    if not 0 <= selected < 4:
        raise RadialShellError(
            "invalid_black_slot",
            {"black_slot": selected},
        )
    if len(physical_hex) != 4:
        raise RadialShellError(
            "invalid_physical_colors",
            {"physical_color_count": int(len(physical_hex))},
        )
    try:
        luminances = tuple(
            _relative_srgb_luminance(value) for value in physical_hex
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RadialShellError(
            "invalid_physical_colors",
            {"error": str(exc)},
        ) from exc

    darkest_value = min(luminances)
    tolerance = 1e-12
    darkest = tuple(
        index
        for index, value in enumerate(luminances)
        if abs(value - darkest_value) <= tolerance
    )
    if len(darkest) != 1:
        raise RadialShellError(
            "unique_darkest_black_required",
            {"darkest_slots": darkest},
        )
    if selected != darkest[0]:
        raise RadialShellError(
            "selected_black_not_darkest",
            {"black_slot": selected, "darkest_slot": darkest[0]},
        )


def analyze_radial_partner_contrast(
    settings: AppSettings,
    black_slot: int,
) -> RadialContrastAnalysis:
    """Analyse black-mix states using a provisional CIELAB L* threshold.

    State IDs remain zero-based palette IDs while physical extruders are
    reported as F1..F4-compatible one-based values.  The optional
    ``RadialSettings.minimum_lstar_delta`` field is read when a newer settings
    object supplies it; older projects deliberately retain the 35.0 default.
    """

    selected = int(black_slot)
    if not 0 <= selected < 4:
        raise RadialShellError(
            "invalid_black_slot",
            {"black_slot": selected},
        )
    palette = settings.palette
    physical_hex = tuple(palette.physical_hex)
    _require_unique_darkest_black_slot(physical_hex, selected)
    raw_threshold = getattr(settings.radial, "minimum_lstar_delta", 35.0)
    if isinstance(raw_threshold, (bool, np.bool_)):
        raise RadialShellError(
            "invalid_minimum_lstar_delta",
            {"minimum_lstar_delta": raw_threshold},
        )
    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError) as exc:
        raise RadialShellError(
            "invalid_minimum_lstar_delta",
            {"minimum_lstar_delta": raw_threshold},
        ) from exc
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 100.0:
        raise RadialShellError(
            "invalid_minimum_lstar_delta",
            {"minimum_lstar_delta": threshold},
        )
    try:
        lstar = tuple(float(srgb_hex_to_lab(value)[0]) for value in physical_hex)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RadialShellError(
            "invalid_physical_colors",
            {"error": str(exc)},
        ) from exc

    black_lstar = lstar[selected]
    states: list[RadialPartnerContrast] = []
    for offset, (left, right, _ratio_b) in enumerate(
        palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
    ):
        state_id = 4 + offset
        if state_id >= int(palette.palette_state_count):
            break
        if selected not in (left, right):
            continue
        partner = right if left == selected else left
        partner_lstar = lstar[int(partner)]
        delta = abs(partner_lstar - black_lstar)
        states.append(
            RadialPartnerContrast(
                state_id=int(state_id),
                black_extruder=selected + 1,
                partner_extruder=int(partner) + 1,
                black_lstar=black_lstar,
                partner_lstar=partner_lstar,
                lstar_delta=delta,
                qualifies=delta + 1e-12 >= threshold,
            )
        )
    return RadialContrastAnalysis(
        black_extruder=selected + 1,
        black_lstar=black_lstar,
        minimum_lstar_delta=threshold,
        states=tuple(states),
    )


def _eligible_state_partners(
    settings: AppSettings,
    black_slot: int,
) -> dict[int, int]:
    return analyze_radial_partner_contrast(
        settings,
        black_slot,
    ).eligible_state_partners


def _radial_process_profile(settings: AppSettings) -> str:
    """Resolve only explicitly validated general-model process profiles."""

    layer_height = float(settings.radial.layer_height_mm)
    wall_generator = str(getattr(settings.radial, "wall_generator", "classic"))
    if abs(layer_height - 0.10) <= 1e-12:
        if wall_generator == "classic":
            return RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010
        if wall_generator == "arachne":
            return RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010
    if abs(layer_height - 0.20) <= 1e-12 and wall_generator == "classic":
        return RADIAL_PROCESS_PROFILE_MVP_020
    raise RadialShellError(
        "unsupported_radial_process_combination",
        {
            "layer_height_mm": layer_height,
            "wall_generator": wall_generator,
        },
    )


def _guide_text(
    result,
    *,
    black_slot: int,
    layer_height_mm: float,
    contrast: RadialPartnerContrast,
    minimum_lstar_delta: float,
    process_profile: str,
    wall_generator: str,
) -> str:
    return (
        "ChromaMatter Radial Stage A / SLICE ONLY\n"
        "=========================================\n\n"
        "This 3MF is a separate experimental output. It does not use Ratio, "
        "Cycle, triangle paint, or virtual mixed tools.\n"
        f"Black slot: F{black_slot + 1}\n"
        f"Partner slot: F{contrast.partner_extruder}\n"
        f"Partner-colour skin: {result.skin_thickness_mm:.3f} mm\n"
        f"Layer height: fixed {layer_height_mm:.2f} mm\n\n"
        f"Process profile: {process_profile}\n"
        f"Wall generator: {wall_generator}\n"
        "Sparse infill: "
        f"{radial_process_profile_sparse_infill_percent(process_profile)}%\n\n"
        "Black/partner lightness gate\n"
        "----------------------------\n"
        f"Minimum CIELAB delta L*: {minimum_lstar_delta:.3f}\n"
        f"Actual CIELAB delta L*: {contrast.lstar_delta:.3f}\n"
        f"Black F{contrast.black_extruder} L*: {contrast.black_lstar:.3f}\n"
        f"Partner F{contrast.partner_extruder} L*: "
        f"{contrast.partner_lstar:.3f}\n\n"
        "Snapmaker Orca\n"
        "---------------\n"
        "1. Open the 3MF as a project.\n"
        "2. Slice it, but do not send it to the printer yet.\n"
        "3. Inspect every layer in Filament view. The outside path must use "
        "only the partner physical filament, with pure black entirely inside.\n"
        "4. Stop if Orca reports a path conflict, invalid tool, access violation, "
        "missing shell, gap, or exposed black exterior.\n\n"
        "Initial implementation limits\n"
        "-----------------------------\n"
        "One watertight, positive-volume print part; the complete exterior must "
        "use one black-containing mixed state. Multi-state and partial-paint "
        "models are rejected instead of approximated.\n"
    )


def _stage_b_palette_signature(palette: object) -> tuple[object, ...]:
    """Return only the palette fields that define serialized paint states.

    Selective Stage B may combine several source parts, but one Snapmaker
    project has one F1-F4 table and one Ratio definition table.  Per-part
    automatic-assignment hints may differ; the physical/output recipes may
    not.
    """

    try:
        physical = tuple(normalize_hex(value) for value in palette.physical_hex)
        overrides = tuple(
            None if value is None else normalize_hex(str(value))
            for value in palette.mix_hex_overrides
        )
        secondary = tuple(int(value) for value in palette.secondary_mix_ratios_b)
        output_raw = palette.output_mix_ratios_b
        return (
            str(palette.material),
            int(palette.palette_state_count),
            physical,
            overrides,
            tuple(int(value) for value in palette.mix_ratios_b),
            secondary,
            None
            if output_raw is None
            else tuple(int(value) for value in output_raw),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RadialShellError(
            "single_palette_required",
            {"error": str(exc)},
        ) from exc


def _shared_stage_b_palette(
    settings: AppSettings,
    layout,
):
    """Resolve one archive-compatible palette for all Stage-B source parts."""

    resolved = resolve_part_palette_settings(settings, layout)
    if not resolved:
        raise RadialShellError(
            "single_palette_required",
            {"palette_count": 0},
        )
    first = resolved[0]
    signature = _stage_b_palette_signature(first)
    if any(_stage_b_palette_signature(value) != signature for value in resolved[1:]):
        raise RadialShellError(
            "single_palette_required",
            {"palette_count": int(len(resolved))},
        )
    return first


def _stage_b_guide_text(
    result,
    *,
    black_slot: int,
    layer_height_mm: float,
    minimum_lstar_delta: float,
    process_profile: str,
    wall_generator: str,
) -> str:
    radial_states = ", ".join(
        str(int(value) + 1) for value in result.plan.radial_state_ids
    )
    conventional_states = ", ".join(
        str(int(value) + 1) for value in result.plan.conventional_state_ids
    )
    state_depths = dict(result.plan.state_outer_skin_thickness_mm)
    depth_values = tuple(sorted(set(map(float, state_depths.values()))))
    if len(depth_values) > 1:
        depth_summary = (
            "Partner-colour skin: adaptive discrete depths\n"
            + "".join(
                f"  palette state {int(state_id) + 1}: {float(depth):.3f} mm\n"
                for state_id, depth in sorted(state_depths.items())
            )
        )
    else:
        displayed_depth = (
            float(depth_values[0])
            if depth_values
            else float(result.plan.outer_skin_thickness_mm)
        )
        depth_summary = (
            f"Partner-colour skin: {displayed_depth:.3f} mm\n"
        )
    return (
        "ChromaMatter Selective Radial Hybrid Stage B / SLICE ONLY\n"
        "=========================================================\n\n"
        "This is an experimental slicer-validation project.  It combines "
        "physical partner-colour skins only for selected high-lightness-"
        "difference black mixes with the established triangle-paint method "
        "for all other exterior regions.\n\n"
        f"Black slot: F{black_slot + 1}\n"
        f"{depth_summary}"
        f"Minimum CIELAB delta L*: {minimum_lstar_delta:.3f}\n"
        f"Radial palette state IDs: {radial_states or 'none'}\n"
        f"Conventional palette state IDs: {conventional_states or 'none'}\n"
        f"Layer height: fixed {layer_height_mm:.2f} mm\n"
        f"Process profile: {process_profile}\n"
        f"Wall generator: {wall_generator}\n"
        "Sparse infill: "
        f"{radial_process_profile_sparse_infill_percent(process_profile)}%\n\n"
        "Required Snapmaker Orca inspection\n"
        "-----------------------------------\n"
        "1. Open this 3MF as a project and slice it.\n"
        "2. Do not send it to the printer yet.\n"
        "3. Inspect every layer in Filament view. High-delta-L black mixes "
        "must show the partner filament on the outside and pure black behind "
        "it. Pure black, low-delta-L black mixes, and non-black states must "
        "retain their ordinary triangle-paint assignment.\n"
        "4. Inspect every transition between both methods. Stop if you see a "
        "gap, overlap, missing wall, exposed black streak, virtual tool on an "
        "internal interface, or a path conflict.\n"
        "5. This file remains SLICE ONLY until its all-layer Orca preview and "
        "a physical calibration print are accepted.\n"
    )


def _export_selective_hybrid_bundle(
    prepared: PreparedGeometry,
    settings: AppSettings,
    destination: Path,
    *,
    black_slot: int,
    manual_overrides: np.ndarray | None,
    progress: ProgressCallback | None,
    source_assembly_part_count: int,
    selected_part_id: int | None,
    selected_part_key: str | None,
    selected_part_name: str | None,
) -> RadialBundleResult:
    """Generate Stage B without changing the Stage-A or normal writers."""

    # Local imports keep the established Stage-A module graph independent of
    # optional Stage-B geometry and archive code until the user explicitly
    # selects this mode.
    from .radial_hybrid_export import (
        RadialHybridExportError,
        package_from_selective_hybrid,
        write_hybrid_3mf_atomic,
    )
    from .radial_stage_b import RadialStageBError, build_selective_hybrid
    from .radial_thickness import (
        RadialThicknessError,
        derive_radial_thickness_schedule,
    )

    layout = validate_part_layout(prepared.final)
    if not bool(prepared.topology.get("watertight")):
        raise RadialShellError(
            "watertight_mesh_required",
            {"topology": dict(prepared.topology)},
        )
    palette = _shared_stage_b_palette(settings, layout)
    local_settings = AppSettings(
        geometry=settings.geometry,
        tone=settings.tone,
        palette=palette,
        radial=settings.radial,
    )
    contrast_analysis = analyze_radial_partner_contrast(
        local_settings,
        int(black_slot),
    )
    process_profile = _radial_process_profile(local_settings)
    emit(
        progress,
        "radial_hybrid_color",
        0.04,
        "Selective hybrid: checking eligible colour regions",
    )
    colors = recolor_level_parts(
        prepared.final,
        settings.geometry.height_mm,
        settings.tone,
        settings.palette,
        settings.part_palettes,
    )
    if manual_overrides is not None:
        colors = apply_palette_overrides_parts(
            prepared.final,
            settings.geometry.height_mm,
            settings.palette,
            settings.part_palettes,
            colors,
            manual_overrides,
        )
    face_state_ids = np.asarray(colors.palette_indices, dtype=np.int16)
    used_state_ids = {
        int(value) for value in np.unique(face_state_ids)
    }
    eligible = {
        state_id: partner
        for state_id, partner in contrast_analysis.eligible_state_partners.items()
        if state_id in used_state_ids
    }
    if not eligible:
        used_black = tuple(
            item
            for item in contrast_analysis.states
            if item.state_id in used_state_ids
        )
        details: dict[str, object] = {
            "black_extruder": int(black_slot) + 1,
            "minimum_lstar_delta": float(
                contrast_analysis.minimum_lstar_delta
            ),
            "used_state_ids": sorted(used_state_ids),
        }
        if used_black:
            details["maximum_used_lstar_delta"] = float(
                max(item.lstar_delta for item in used_black)
            )
            details["used_black_mix_states"] = [
                item.to_dict() for item in used_black
            ]
            raise RadialShellError("contrast_below_threshold", details)
        raise RadialShellError("no_eligible_surface", details)

    thickness_schedule = None
    state_skin_thickness_mm = None
    if (
        str(getattr(settings.radial, "skin_thickness_mode", "uniform"))
        == RADIAL_SKIN_MODE_ADAPTIVE
    ):
        try:
            thickness_schedule = derive_radial_thickness_schedule(
                palette,
                black_slot=int(black_slot),
                eligible_state_partners=eligible,
                minimum_thickness_mm=float(
                    settings.radial.adaptive_skin_min_thickness_mm
                ),
                maximum_thickness_mm=float(
                    settings.radial.adaptive_skin_max_thickness_mm
                ),
                band_count=int(settings.radial.adaptive_skin_bands),
                gamma=float(settings.radial.adaptive_skin_gamma),
                basis="target_lstar",
            )
            state_skin_thickness_mm = thickness_schedule.thickness_by_state
        except RadialThicknessError as exc:
            raise RadialShellError(exc.code, exc.details) from exc

    emit(
        progress,
        "radial_hybrid_geometry",
        0.12,
        "Selective hybrid: building exact-touch skin and carrier regions",
    )
    try:
        hybrid = build_selective_hybrid(
            prepared,
            float(settings.geometry.height_mm),
            face_state_ids,
            eligible,
            int(black_slot) + 1,
            float(settings.radial.outer_skin_thickness_mm),
            progress=progress,
            state_skin_thickness_mm=state_skin_thickness_mm,
        )
        package = package_from_selective_hybrid(
            hybrid,
            palette,
            process_profile=process_profile,
            layer_height_mm=float(settings.radial.layer_height_mm),
            initial_layer_height_mm=0.20,
        )
        emit(
            progress,
            "radial_hybrid_3mf",
            0.78,
            "Selective hybrid: writing and reopening the SLICE ONLY 3MF",
        )
        validation_value = write_hybrid_3mf_atomic(
            destination,
            package,
            title=f"{destination.stem} [SLICE ONLY / Selective Hybrid]",
        )
    except RadialStageBError as exc:
        raise RadialShellError(exc.code, exc.details) from exc
    except RadialHybridExportError as exc:
        raise RadialShellError(
            "hybrid_3mf_validation_failed",
            {"error": str(exc)},
        ) from exc

    validation = (
        validation_value.to_dict()
        if hasattr(validation_value, "to_dict")
        else dict(validation_value)
    )
    report_path = destination.with_name(
        destination.stem + "_radial_validation.json"
    )
    guide_path = destination.with_name(
        destination.stem + "_SLICE_ONLY_guide.txt"
    )
    used_contrasts = [
        item.to_dict()
        for item in contrast_analysis.states
        if item.state_id in used_state_ids
    ]
    report = {
        "schema": "obj-adjuster.radial-lab.selective-hybrid.v1",
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "conversion_mode": RADIAL_CONVERSION_SELECTIVE_HYBRID,
        "source_model_sha256": str(prepared.source.sha256),
        "source_part_count": int(layout.part_count),
        "source_assembly_part_count": int(source_assembly_part_count),
        "selected_part_id": selected_part_id,
        "selected_part_key": selected_part_key,
        "selected_part_name": selected_part_name,
        "black_extruder": int(black_slot) + 1,
        "physical_hex": list(palette.physical_hex),
        "minimum_lstar_delta": float(
            contrast_analysis.minimum_lstar_delta
        ),
        "used_black_mix_contrasts": used_contrasts,
        "process_profile": process_profile,
        "wall_generator": str(settings.radial.wall_generator),
        "sparse_infill_density_percent": (
            radial_process_profile_sparse_infill_percent(process_profile)
        ),
        "skin_thickness_mm": float(hybrid.plan.outer_skin_thickness_mm),
        "skin_thickness_mode": str(
            getattr(settings.radial, "skin_thickness_mode", "uniform")
        ),
        "adaptive_skin_thickness_schedule": (
            None
            if thickness_schedule is None
            else thickness_schedule.to_dict()
        ),
        "layer_height_mm": float(settings.radial.layer_height_mm),
        "selection": hybrid.plan.to_dict(),
        "geometry": dict(hybrid.metadata),
        "archive_validation": validation,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    guide_path.write_text(
        _stage_b_guide_text(
            hybrid,
            black_slot=int(black_slot),
            layer_height_mm=float(settings.radial.layer_height_mm),
            minimum_lstar_delta=float(
                contrast_analysis.minimum_lstar_delta
            ),
            process_profile=process_profile,
            wall_generator=str(settings.radial.wall_generator),
        ),
        encoding="utf-8-sig",
    )
    emit(
        progress,
        "radial_hybrid_done",
        1.0,
        "Selective hybrid SLICE ONLY 3MF saved",
    )
    return RadialBundleResult(
        model_path=destination,
        report_path=report_path,
        guide_path=guide_path,
        validation=validation,
        skin_thickness_mm=float(hybrid.plan.outer_skin_thickness_mm),
        layer_height_mm=float(settings.radial.layer_height_mm),
        process_profile=process_profile,
        wall_generator=str(settings.radial.wall_generator),
    )


def export_radial_bundle(
    prepared: PreparedGeometry,
    settings: AppSettings,
    destination: Path,
    *,
    black_slot: int,
    manual_overrides: np.ndarray | None = None,
    progress: ProgressCallback | None = None,
    part_key: str | None = None,
    part_id: int | None = None,
) -> RadialBundleResult:
    """Generate the separate fail-closed radial laboratory bundle."""

    destination = Path(destination).with_suffix(".3mf")

    # A multipart project can use a different F1-F4 palette for every print
    # part.  One radial archive cannot safely reinterpret those independent
    # physical tables as a single job.  When the caller explicitly chooses a
    # part, isolate it before conversion-mode dispatch so both Stage A and the
    # selective/adaptive Stage B path operate on exactly that part and its own
    # palette.  With no selection, retain the established whole-model
    # behaviour (including its fail-closed shared-palette/single-part gates).
    source_prepared = prepared
    source_layout = validate_part_layout(source_prepared.final)
    source_part_keys = tuple(str(value) for value in source_layout.part_keys)
    source_assembly_part_count = int(source_layout.part_count)
    selected_part_key: str | None = None
    selected_part_id: int | None = None
    selected_part_name: str | None = None
    if part_key is not None and part_id is not None:
        raise RadialShellError(
            "part_selection_conflict",
            {"part_key": part_key, "part_id": part_id},
        )
    if part_key is not None:
        selected_part_key = str(part_key)
        try:
            selected_part_id = source_part_keys.index(selected_part_key)
        except ValueError as exc:
            raise RadialShellError(
                "part_key_not_found",
                {
                    "part_key": selected_part_key,
                    "available_part_keys": source_part_keys,
                },
            ) from exc
    elif part_id is not None:
        try:
            selected_part_id = int(part_id)
        except (TypeError, ValueError) as exc:
            raise RadialShellError(
                "part_id_out_of_range",
                {
                    "part_id": part_id,
                    "part_count": source_assembly_part_count,
                },
            ) from exc
        if not 0 <= selected_part_id < source_assembly_part_count:
            raise RadialShellError(
                "part_id_out_of_range",
                {
                    "part_id": selected_part_id,
                    "part_count": source_assembly_part_count,
                },
            )
        selected_part_key = source_part_keys[selected_part_id]
    if selected_part_id is not None:
        source_part_names = tuple(source_prepared.final.part_names)
        raw_part_name = (
            source_part_names[selected_part_id]
            if selected_part_id < len(source_part_names)
            else None
        )
        selected_part_name = (
            raw_part_name.strip()
            if isinstance(raw_part_name, str) and raw_part_name.strip()
            else selected_part_key
        )

        # Local import avoids coupling the normal FullSpectrum workflow to
        # radial code during module initialisation.
        from .workflow import _extract_prepared_part

        prepared, source_face_ids = _extract_prepared_part(
            source_prepared,
            selected_part_id,
        )
        if manual_overrides is not None:
            raw_overrides = np.asarray(manual_overrides)
            expected_shape = (len(source_prepared.final.faces),)
            if raw_overrides.shape != expected_shape:
                raise RadialShellError(
                    "invalid_manual_overrides",
                    {
                        "expected_faces": int(expected_shape[0]),
                        "actual_shape": tuple(raw_overrides.shape),
                    },
                )
            manual_overrides = np.ascontiguousarray(
                raw_overrides[source_face_ids]
            )

    conversion_mode = str(
        getattr(
            settings.radial,
            "conversion_mode",
            RADIAL_CONVERSION_UNIFORM_STAGE_A,
        )
    )
    if conversion_mode == RADIAL_CONVERSION_SELECTIVE_HYBRID:
        return _export_selective_hybrid_bundle(
            prepared,
            settings,
            destination,
            black_slot=int(black_slot),
            manual_overrides=manual_overrides,
            progress=progress,
            source_assembly_part_count=source_assembly_part_count,
            selected_part_id=selected_part_id,
            selected_part_key=selected_part_key,
            selected_part_name=selected_part_name,
        )
    if conversion_mode != RADIAL_CONVERSION_UNIFORM_STAGE_A:
        raise RadialShellError(
            "invalid_conversion_mode",
            {"conversion_mode": conversion_mode},
        )
    layout = validate_part_layout(prepared.final)
    if layout.part_count != 1:
        raise RadialShellError(
            "single_part_required",
            {"part_count": int(layout.part_count)},
        )
    if not bool(prepared.topology.get("watertight")):
        raise RadialShellError(
            "watertight_mesh_required",
            {"topology": dict(prepared.topology)},
        )

    resolved = resolve_part_palette_settings(settings, layout)
    if len(resolved) != 1:
        raise RadialShellError(
            "single_palette_required",
            {"palette_count": int(len(resolved))},
        )
    palette = resolved[0]
    local_settings = AppSettings(
        geometry=settings.geometry,
        tone=settings.tone,
        palette=palette,
        radial=settings.radial,
    )
    contrast_analysis = analyze_radial_partner_contrast(
        local_settings,
        int(black_slot),
    )
    process_profile = _radial_process_profile(local_settings)
    emit(progress, "radial_color", 0.04, "ラジアル外皮の対象色を確認しています")
    colors = recolor_level_parts(
        prepared.final,
        settings.geometry.height_mm,
        settings.tone,
        palette,
        {},
    )
    if manual_overrides is not None:
        colors = apply_palette_overrides_parts(
            prepared.final,
            settings.geometry.height_mm,
            palette,
            {},
            colors,
            manual_overrides,
        )

    used_state_ids = {
        int(value)
        for value in np.unique(
            np.asarray(colors.palette_indices, dtype=np.int16)
        )
    }
    used_black_contrasts = tuple(
        item
        for item in contrast_analysis.states
        if item.state_id in used_state_ids
    )
    if used_black_contrasts and not any(
        item.qualifies for item in used_black_contrasts
    ):
        raise RadialShellError(
            "contrast_below_threshold",
            {
                "black_extruder": int(black_slot) + 1,
                "minimum_lstar_delta": float(
                    contrast_analysis.minimum_lstar_delta
                ),
                "maximum_used_lstar_delta": float(
                    max(item.lstar_delta for item in used_black_contrasts)
                ),
                "used_black_mix_states": [
                    item.to_dict() for item in used_black_contrasts
                ],
            },
        )

    eligible = contrast_analysis.eligible_state_partners
    emit(progress, "radial_geometry", 0.12, "閉じた外皮と純黒内部を生成しています")
    shell = build_radial_shell_from_level(
        prepared.final,
        height_mm=float(settings.geometry.height_mm),
        face_state_ids=np.asarray(colors.palette_indices, dtype=np.int16),
        eligible_state_partners=eligible,
        black_extruder=int(black_slot) + 1,
        skin_thickness_mm=float(settings.radial.outer_skin_thickness_mm),
        minimum_eligible_area_fraction=1.0,
    )
    source_state_id = int(shell.metadata.get("source_state_id", -1))
    selected_contrast = contrast_analysis.state(source_state_id)
    if selected_contrast is None or not selected_contrast.qualifies:
        raise RadialShellError(
            "contrast_analysis_mismatch",
            {
                "source_state_id": source_state_id,
                "minimum_lstar_delta": float(
                    contrast_analysis.minimum_lstar_delta
                ),
            },
        )
    package = package_from_radial_shell(
        shell,
        palette.physical_hex,
        process_profile=process_profile,
        layer_height_mm=float(settings.radial.layer_height_mm),
        initial_layer_height_mm=0.20,
    )
    emit(progress, "radial_3mf", 0.72, "物理F1〜F4だけの実験3MFを書き出しています")
    validation_value = write_radial_3mf_atomic(
        destination,
        package,
        title=f"{destination.stem} [SLICE ONLY / Radial Lab]",
    )
    validation = (
        validation_value.to_dict()
        if hasattr(validation_value, "to_dict")
        else dict(validation_value)
    )
    report_path = destination.with_name(
        destination.stem + "_radial_validation.json"
    )
    guide_path = destination.with_name(
        destination.stem + "_SLICE_ONLY_guide.txt"
    )
    report = {
        "schema": "obj-adjuster.radial-lab.bundle.v1",
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "source_obj_sha256": str(prepared.source.sha256),
        "source_part_count": int(layout.part_count),
        "source_assembly_part_count": int(source_assembly_part_count),
        "selected_part_id": selected_part_id,
        "selected_part_key": selected_part_key,
        "selected_part_name": selected_part_name,
        "source_part": str(
            prepared.final.part_names[0]
            if prepared.final.part_names
            else layout.part_keys[0]
        ),
        "black_extruder": int(black_slot) + 1,
        "physical_hex": list(palette.physical_hex),
        "minimum_lstar_delta": float(
            contrast_analysis.minimum_lstar_delta
        ),
        "actual_lstar_delta": float(selected_contrast.lstar_delta),
        "radial_partner_contrast": selected_contrast.to_dict(),
        "process_profile": process_profile,
        "wall_generator": str(
            getattr(settings.radial, "wall_generator", "classic")
        ),
        "sparse_infill_density_percent": (
            radial_process_profile_sparse_infill_percent(process_profile)
        ),
        "skin_thickness_mm": float(shell.skin_thickness_mm),
        "layer_height_mm": float(settings.radial.layer_height_mm),
        "geometry": dict(shell.metadata),
        "archive_validation": validation,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    guide_path.write_text(
        _guide_text(
            shell,
            black_slot=int(black_slot),
            layer_height_mm=float(settings.radial.layer_height_mm),
            contrast=selected_contrast,
            minimum_lstar_delta=float(
                contrast_analysis.minimum_lstar_delta
            ),
            process_profile=process_profile,
            wall_generator=str(
                getattr(settings.radial, "wall_generator", "classic")
            ),
        ),
        encoding="utf-8-sig",
    )
    emit(progress, "radial_done", 1.0, "ラジアル実験3MFを保存しました")
    return RadialBundleResult(
        model_path=destination,
        report_path=report_path,
        guide_path=guide_path,
        validation=validation,
        skin_thickness_mm=float(shell.skin_thickness_mm),
        layer_height_mm=float(settings.radial.layer_height_mm),
        process_profile=process_profile,
        wall_generator=str(
            getattr(settings.radial, "wall_generator", "classic")
        ),
    )


__all__ = [
    "RadialBundleResult",
    "RadialContrastAnalysis",
    "RadialPartnerContrast",
    "analyze_radial_partner_contrast",
    "export_radial_bundle",
]
