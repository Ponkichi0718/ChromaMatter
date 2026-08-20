from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .engine import (
    apply_palette_overrides_parts,
    emit,
    recolor_level_parts,
)
from .mixer import normalize_hex, palette_mix_specs
from .models import AppSettings, PreparedGeometry, ProgressCallback
from .parts import resolve_part_palette_settings, validate_part_layout
from .radial_export import (
    package_from_radial_shell,
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


def _eligible_state_partners(
    settings: AppSettings,
    black_slot: int,
) -> dict[int, int]:
    if not 0 <= int(black_slot) < 4:
        raise RadialShellError(
            "invalid_black_slot",
            {"black_slot": int(black_slot)},
        )
    palette = settings.palette
    result: dict[int, int] = {}
    for offset, (left, right, _ratio_b) in enumerate(
        palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
    ):
        state_id = 4 + offset
        if state_id >= int(palette.palette_state_count):
            break
        if black_slot not in (left, right):
            continue
        partner = right if left == black_slot else left
        result[state_id] = int(partner) + 1
    return result


def _guide_text(
    result,
    *,
    black_slot: int,
    layer_height_mm: float,
) -> str:
    return (
        "ChromaMatter legacy r20 Radial Lab / SLICE ONLY\n"
        "============================================\n\n"
        "This 3MF is a separate experimental output. It does not use Ratio, "
        "Cycle, triangle paint, or virtual mixed tools.\n"
        f"Black slot: F{black_slot + 1}\n"
        f"Partner-colour skin: {result.skin_thickness_mm:.3f} mm\n"
        f"Layer height: fixed {layer_height_mm:.2f} mm\n\n"
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


def export_radial_bundle(
    prepared: PreparedGeometry,
    settings: AppSettings,
    destination: Path,
    *,
    black_slot: int,
    manual_overrides: np.ndarray | None = None,
    progress: ProgressCallback | None = None,
) -> RadialBundleResult:
    """Generate the separate fail-closed radial laboratory bundle."""

    destination = Path(destination).with_suffix(".3mf")
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
    _require_unique_darkest_black_slot(
        palette.physical_hex,
        int(black_slot),
    )
    local_settings = AppSettings(
        geometry=settings.geometry,
        tone=settings.tone,
        palette=palette,
        radial=settings.radial,
    )
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

    eligible = _eligible_state_partners(local_settings, int(black_slot))
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
    package = package_from_radial_shell(
        shell,
        palette.physical_hex,
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
        "source_part": str(
            prepared.final.part_names[0]
            if prepared.final.part_names
            else layout.part_keys[0]
        ),
        "black_extruder": int(black_slot) + 1,
        "physical_hex": list(palette.physical_hex),
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
    )


__all__ = ["RadialBundleResult", "export_radial_bundle"]
