"""Runtime fixes for the packaged ChromaMatter application.

The original application was distributed without source files.  This module is
loaded before the recovered application package and replaces only the small,
well-tested hot paths that caused the reported regressions.
"""

from __future__ import annotations

from collections import OrderedDict
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import weakref
from zipfile import ZipFile

import numpy as np

import slicer_safety
import smooth_paint

import spectrum_mapper as spectrum_mapper_package
from spectrum_mapper import (
    engine,
    filament_materials,
    gui,
    mixer,
    models,
    paint,
    paint_gui,
    parts,
    renderer,
    workflow,
)


# Public version is user-pinned.  Bug fixes and beta features must not advance
# this string until the user explicitly requests a version change.
HOTFIX_VERSION = "0.8beta"
spectrum_mapper_package.__version__ = HOTFIX_VERSION
engine.__version__ = HOTFIX_VERSION
gui.__version__ = HOTFIX_VERSION
_APP_DISPLAY_NAME = getattr(
    spectrum_mapper_package,
    "APP_DISPLAY_NAME",
    spectrum_mapper_package.APP_NAME,
)
_RELEASE_REVISION = getattr(spectrum_mapper_package, "RELEASE_REVISION", "")
gui.APP_TITLE = f"{_APP_DISPLAY_NAME} {HOTFIX_VERSION}" + (
    f" ({_RELEASE_REVISION})" if _RELEASE_REVISION else ""
)
_STATE_NAMES = tuple(engine.STATE_NAMES)
_PAINT_CODE_TO_STATE = {code: index for index, code in enumerate(engine.PAINT_CODES)}
_SYSTEM_PRINT_SETTINGS_ID = "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)"
_GENERIC_PLA_FILAMENT_SETTINGS_ID = "Generic PLA"
_GENERIC_FILAMENT_SETTINGS_IDS = {
    "Generic PLA",
    "Generic ABS",
    "Generic PETG",
}


# Snapmaker Orca 2.3.5 does not display an arbitrary percentage directly.  It
# first turns the requested percentage into a printable A/B layer cadence (the
# minority gets one layer and the majority is rounded to an integer count), and
# then feeds that effective ratio to the shared FilamentMixer model.  Using the
# same rule here keeps this preview and Orca's Prepare view in agreement.
_original_mix_rgb8 = mixer.mix_rgb8


def _orca_effective_mix_ratio(requested_ratio_b: float) -> float:
    """Backward-compatible alias for the shared cadence calculation."""

    return mixer.orca_effective_mix_ratio(requested_ratio_b)


def _mix_rgb8_orca_fixed(first, second, ratio=0.5):
    return _original_mix_rgb8(first, second, _orca_effective_mix_ratio(ratio))


mixer.mix_rgb8 = _mix_rgb8_orca_fixed
try:
    mixer._mix_ratio_grid.cache_clear()
except AttributeError:
    pass


def _normalize_palette_hex(palette: object) -> list[str]:
    values, _ = mixer.build_palette_rgb(
        list(palette.physical_hex),
        list(palette.mix_hex_overrides),
        list(palette.mix_ratios_b),
        list(palette.secondary_mix_ratios_b),
    )
    count = mixer.coerce_palette_state_count(
        getattr(palette, "palette_state_count", 16)
    )
    if getattr(palette, "color_mode", None) == models.COLOR_MODE_FLAT_FOUR:
        count = 4
    return [mixer.normalize_hex(value) for value in values[:count]]


def _paint_code_state(code: str) -> int:
    """Return the largest-area printable state stored in an Orca paint code."""
    simple = _PAINT_CODE_TO_STATE.get(code)
    if simple is not None:
        return int(simple)
    return int(smooth_paint.decode_paint_color(code).dominant_state())


def _portable_object_xml(
    data: bytes,
    palette_hex: list[str],
    paint_trees: dict[int, smooth_paint.PaintNode] | None = None,
    state_names: tuple[str, ...] | list[str] | None = None,
) -> bytes:
    """Add standard 3MF materials while retaining Orca's paint_color data."""
    material_lines = [b'  <basematerials id="2">']
    names = tuple(state_names) if state_names is not None else _STATE_NAMES
    for name, color in zip(names, palette_hex, strict=True):
        safe_name = (
            name.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        rgba = f"{mixer.normalize_hex(color)}FF"
        material_lines.append(
            f'   <base name="{safe_name}" displaycolor="{rgba}"/>'.encode("utf-8")
        )
    material_lines.append(b"  </basematerials>")
    block = b"\n".join(material_lines) + b"\n"

    if b'<basematerials id="2">' in data:
        data, replaced = re.subn(
            rb'  <basematerials id="2">.*?</basematerials>\r?\n?',
            block,
            data,
            count=1,
            flags=re.DOTALL,
        )
        if replaced != 1:
            raise ValueError("Existing 3MF base materials could not be updated")
    else:
        marker = b" <resources>\n"
        if marker not in data:
            raise ValueError("3MF object XML does not contain a resources section")
        data = data.replace(marker, marker + block, 1)

    triangle_pattern = re.compile(rb'<triangle\b([^>]*?)\s+paint_color="([^"]+)"\s*/>')

    trees = paint_trees or {}
    triangle_index = -1

    def add_standard_material(match: re.Match[bytes]) -> bytes:
        nonlocal triangle_index
        triangle_index += 1
        attributes, paint_code = match.groups()
        tree = trees.get(triangle_index)
        if tree is not None:
            paint_code = smooth_paint.encode_paint_color(tree).encode("ascii")
        try:
            state = _paint_code_state(paint_code.decode("ascii"))
        except (smooth_paint.PaintColorCodecError, UnicodeDecodeError) as exc:
            raise ValueError(f"Unknown Full Spectrum paint code: {paint_code!r}") from exc
        # The recovered writer may already have portable attributes from an
        # earlier pass.  Rebuild them so p1 follows the adaptive tree's
        # dominant state while paint_color retains every subtriangle.
        attributes = re.sub(rb'\s+(?:pid|p1)="[^"]*"', b"", attributes)
        return (
            b"<triangle"
            + attributes
            + f' pid="2" p1="{state}" paint_color="'.encode("ascii")
            + paint_code
            + b'"/>'
        )

    updated, count = triangle_pattern.subn(add_standard_material, data)
    if count == 0 and b"<triangle" in data and b" pid=" not in data:
        raise ValueError("3MF triangles could not be assigned portable materials")
    return updated


def _portable_project_settings(data: bytes) -> bytes:
    """Supply the minimum U1 identity for safer accidental project opening."""
    try:
        settings = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return data
    if not isinstance(settings, dict):
        return data
    settings["printer_model"] = "Snapmaker U1"
    settings["printer_variant"] = "0.4"
    settings["printer_settings_id"] = "Snapmaker U1 (0.4 nozzle)"
    settings.setdefault("nozzle_diameter", ["0.4", "0.4", "0.4", "0.4"])
    settings["print_settings_id"] = _SYSTEM_PRINT_SETTINGS_ID
    settings["layer_height"] = "0.08"
    settings["initial_layer_print_height"] = "0.2"
    settings["adaptive_layer_height"] = "0"
    # F1-F4 are four colours of one polymer.  Preserve an exact Generic
    # PLA/ABS/PETG profile written by the engine; sanitize legacy branded or
    # mixed profile lists to the backward-compatible PLA default.
    profiles = settings.get("filament_settings_id")
    if not (
        isinstance(profiles, list)
        and len(profiles) == 4
        and len(set(profiles)) == 1
        and profiles[0] in _GENERIC_FILAMENT_SETTINGS_IDS
    ):
        settings["filament_settings_id"] = [_GENERIC_PLA_FILAMENT_SETTINGS_ID] * 4
    # Support depends on the model and must stay editable in Orca.  Absence is
    # intentional: neither the project nor an object-level override may force
    # it on or off.
    settings.pop("enable_support", None)
    # A grouped Cycle definition (``outer,inner``) must remain eligible for
    # Orca's grouped-perimeter splitter.  A support/current tool (0) combined
    # with purge-to-support, or any other purge-to-print override, makes Orca
    # mark the layer as overridden and can let a raw virtual ID escape as T4+.
    # Pin support roles to the unique lightest *physical* U1 tool and disable
    # all three override paths.  This does not enable support itself.
    if slicer_safety._has_grouped_cycle_definition(settings):
        colors = settings.get("filament_colour")
        extremes = engine._surface_shell_extreme_slots(
            colors if isinstance(colors, list) else None
        )
        if extremes is not None:
            support_filament = str(extremes[1] + 1)
            settings["support_filament"] = support_filament
            settings["support_interface_filament"] = support_filament
            settings["flush_into_infill"] = "0"
            settings["flush_into_support"] = "0"
            settings["flush_into_objects"] = "0"
    settings["tripo_spectrum_mapper_hotfix"] = HOTFIX_VERSION
    return json.dumps(settings, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _portable_palette_metadata(data: bytes, palette_hex: list[str]) -> bytes:
    try:
        metadata = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return data
    states = metadata.get("states") if isinstance(metadata, dict) else None
    if isinstance(states, list):
        for index, state in enumerate(states[: len(palette_hex)]):
            if isinstance(state, dict):
                state["display_rgb"] = mixer.normalize_hex(palette_hex[index])
    if isinstance(metadata, dict):
        metadata["snapmaker_orca_display_model"] = (
            "physical-F1-F4-only"
            if metadata.get("palette_mode") == models.COLOR_MODE_FLAT_FOUR
            else "2.3.5-layer-cadence"
        )
        metadata["hotfix_version"] = HOTFIX_VERSION
    return json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")


def _rewrite_3mf_portably(
    path: Path,
    palette_hex: list[str],
    paint_trees: dict[int, smooth_paint.PaintNode] | None = None,
    state_names: tuple[str, ...] | list[str] | None = None,
) -> None:
    path = Path(path)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.portable-", suffix=path.suffix, dir=path.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with ZipFile(path, "r") as source, ZipFile(temporary, "w", allowZip64=True) as target:
            for info in source.infolist():
                payload = source.read(info.filename)
                if info.filename == "3D/Objects/object_1.model":
                    payload = _portable_object_xml(
                        payload, palette_hex, paint_trees, state_names
                    )
                elif info.filename == "Metadata/model_settings.config":
                    support = slicer_safety.sanitize_model_settings_support(
                        payload, mode="remove"
                    )
                    unsafe = [
                        item
                        for item in support.diagnostics
                        if item.severity in ("warning", "error")
                    ]
                    if unsafe:
                        messages = "; ".join(item.message for item in unsafe)
                        raise ValueError(
                            f"model_settings.config support safety check failed: {messages}"
                        )
                    payload = support.data
                elif info.filename == "Metadata/project_settings.config":
                    payload = _portable_project_settings(payload)
                elif info.filename == "Metadata/full_spectrum_palette.json":
                    payload = _portable_palette_metadata(payload, palette_hex)
                target.writestr(info, payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _inspect_mixed_definition_recipes(path: Path) -> dict[str, object]:
    """Read the printable ratios that survived the portable archive rewrite.

    Full Spectrum's authoritative physical recipe is the project setting, not
    the display palette.  Inspecting the finished archive catches a wrapper
    that accidentally restores the UI ratios after core export has applied an
    output-only calibration.
    """

    with ZipFile(Path(path)) as archive:
        project = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
        palette_metadata = json.loads(
            archive.read("Metadata/full_spectrum_palette.json").decode("utf-8")
        )
    definitions = project.get("mixed_filament_definitions", "")
    palette_mode = (
        palette_metadata.get("palette_mode", models.COLOR_MODE_FULL_SPECTRUM)
        if isinstance(palette_metadata, dict)
        else models.COLOR_MODE_FULL_SPECTRUM
    )
    if not isinstance(definitions, str):
        raise ValueError("mixed_filament_definitions is missing")
    if not definitions:
        if palette_mode != models.COLOR_MODE_FLAT_FOUR:
            raise ValueError("mixed_filament_definitions is missing")
        return {
            "palette_mode": models.COLOR_MODE_FLAT_FOUR,
            "mixed_definition_string": "",
            "mixed_definition_pairs": [],
            "mixed_definition_stable_ids": [],
            "requested_output_mix_ratios_b_percent": [],
            "effective_output_mix_ratios_b_percent": [],
            "mixed_definition_active_rows": 0,
            "mixed_definition_manual_patterns": [],
            "mixed_definition_cycle_rows": 0,
            "mixed_definition_cycle_rows_valid": True,
            "surface_shell_metadata": None,
            "unsafe_grouped_cycle_detected": False,
        }

    pairs: list[list[int]] = []
    requested: list[int] = []
    stable_ids: list[int] = []
    manual_patterns: list[str | None] = []
    cycle_rows_valid: list[bool] = []
    for raw_row in definitions.split(";"):
        fields = raw_row.split(",")
        if len(fields) < 5:
            raise ValueError("mixed_filament_definitions contains a short row")
        try:
            enabled = int(fields[2]) == 1 and int(fields[3]) == 1
            left = int(fields[0])
            right = int(fields[1])
            ratio_b = int(fields[4])
        except ValueError as exc:
            raise ValueError(
                "mixed_filament_definitions contains a non-integer recipe"
            ) from exc
        if not enabled:
            continue
        if not (1 <= left <= 4 and 1 <= right <= 4 and 0 <= ratio_b <= 100):
            raise ValueError("mixed_filament_definitions recipe is out of range")
        stable_tokens = [value for value in fields[9:] if re.fullmatch(r"u\d+", value)]
        if len(stable_tokens) != 1:
            raise ValueError("mixed_filament_definitions has no unique stable ID")
        stable_id = int(stable_tokens[0][1:])
        pattern: str | None = None
        if "cm1" in fields:
            cycle_index = fields.index("cm1")
            pattern = ",".join(fields[cycle_index + 1 :])
            groups = pattern.split(",") if pattern else []
            pattern_valid = bool(
                len(groups) == 2
                and all(group and set(group) <= set("1234") for group in groups)
            )
            cycle_valid = bool(
                left == 1
                and right == 2
                and len(fields) > 8
                and fields[8] == "m2"
                and pattern_valid
            )
        else:
            cycle_valid = False
        pairs.append([left, right])
        requested.append(ratio_b)
        stable_ids.append(stable_id)
        manual_patterns.append(pattern)
        cycle_rows_valid.append(cycle_valid)

    effective = [
        round(100.0 * _orca_effective_mix_ratio(value / 100.0), 3)
        for value in requested
    ]
    surface_shell_metadata = palette_metadata.get("surface_shell")
    unsafe_grouped_cycle_detected = bool(
        surface_shell_metadata is not None
        or any(pattern is not None for pattern in manual_patterns)
    )
    return {
        "mixed_definition_string": definitions,
        "mixed_definition_pairs": pairs,
        "mixed_definition_stable_ids": stable_ids,
        "requested_output_mix_ratios_b_percent": requested,
        "effective_output_mix_ratios_b_percent": effective,
        "mixed_definition_active_rows": len(requested),
        "mixed_definition_manual_patterns": manual_patterns,
        "mixed_definition_cycle_rows": sum(
            pattern is not None for pattern in manual_patterns
        ),
        "mixed_definition_cycle_rows_valid": all(
            valid
            for valid, pattern in zip(
                cycle_rows_valid, manual_patterns, strict=True
            )
            if pattern is not None
        ),
        "surface_shell_metadata": surface_shell_metadata,
        "unsafe_grouped_cycle_detected": unsafe_grouped_cycle_detected,
        "palette_mode": palette_mode,
    }


def _safety_diagnostic_records(
    diagnostics: tuple[slicer_safety.SafetyDiagnostic, ...],
) -> list[dict[str, str | None]]:
    return [
        {
            "code": item.code,
            "severity": item.severity,
            "message": item.message,
            "key": item.key,
            "value": item.value,
        }
        for item in diagnostics
    ]


def _inspect_portable_materials(
    path: Path,
    expected_faces: int | None = None,
    expected_filament_profile: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "portable_basematerials": False,
        "portable_material_faces": 0,
        "portable_material_state_counts": [0] * mixer.PALETTE_STATE_COUNT,
        "paint_color_state_counts": [0] * mixer.PALETTE_STATE_COUNT,
        "paint_color_leaf_area_counts": [0.0] * mixer.PALETTE_STATE_COUNT,
        "snapmaker_u1_metadata": False,
        "snapmaker_u1_print_settings": False,
        "snapmaker_u1_layer_height_008": False,
        "snapmaker_u1_transition_settings": False,
        "full_spectrum_stable_cadence_settings": False,
        "generic_pla_filament_settings": False,
        "generic_material_filament_settings": False,
        "project_support_disabled": False,
        "support_override_disabled": False,
        "support_safety_diagnostics": [],
        "project_settings_line_width_safe": False,
        "project_settings_diagnostics": [],
        "project_settings_diagnostic_messages": [],
        "project_settings_error_count": 0,
        "project_settings_warning_count": 0,
        "surface_shell_project_settings_exact": False,
        "surface_shell_project_settings_absent": False,
        "surface_shell_grouped_cycle": False,
        "surface_shell_support_tools_physical": False,
        "surface_shell_support_uses_lightest_physical": False,
        "surface_shell_purge_to_print_disabled": False,
        "surface_shell_tool_override_safe": False,
        "unsafe_grouped_cycle_detected": False,
        "hotfix_version": HOTFIX_VERSION,
    }
    with ZipFile(path, "r") as archive:
        model = archive.read("3D/Objects/object_1.model")
        material_count = model.count(b"<base ")
        result["portable_palette_state_count"] = material_count
        result["portable_basematerials"] = (
            material_count in (4, *mixer.SUPPORTED_PALETTE_STATE_COUNTS)
            and b'<basematerials id="2">' in model
        )
        material_colors = [
            value.decode("ascii")[:7].upper()
            for value in re.findall(rb'<base\b[^>]*\sdisplaycolor="(#[0-9A-Fa-f]{8})"', model)
        ]
        result["portable_material_colors"] = material_colors
        p1_values = re.findall(rb'\spid="2"\sp1="([0-9]+)"', model)
        counts = np.bincount(
            np.asarray([int(value) for value in p1_values], dtype=np.int16),
            minlength=mixer.PALETTE_STATE_COUNT,
        )[: mixer.PALETTE_STATE_COUNT]
        result["portable_material_faces"] = int(len(p1_values))
        result["portable_material_state_counts"] = counts.astype(int).tolist()

        paint_values = re.findall(rb'\spaint_color="([^"]+)"', model)
        paint_counts = np.zeros(mixer.PALETTE_STATE_COUNT, dtype=np.int64)
        paint_leaf_areas = np.zeros(mixer.PALETTE_STATE_COUNT, dtype=np.float64)
        unknown_codes: list[str] = []
        adaptive_faces = 0
        for raw in paint_values:
            code = raw.decode("ascii", errors="replace")
            simple_state = _PAINT_CODE_TO_STATE.get(code)
            if simple_state is not None:
                paint_counts[simple_state] += 1
                paint_leaf_areas[simple_state] += 1.0
            else:
                try:
                    tree = smooth_paint.decode_paint_color(code)
                except smooth_paint.PaintColorCodecError:
                    unknown_codes.append(code)
                    continue
                if not tree.is_leaf:
                    adaptive_faces += 1
                state = tree.dominant_state()
                paint_counts[state] += 1
                paint_leaf_areas += np.asarray(tree.state_areas(), dtype=np.float64)
        result["paint_color_state_counts"] = paint_counts.astype(int).tolist()
        result["paint_color_leaf_area_counts"] = paint_leaf_areas.round(8).tolist()
        result["unknown_paint_codes"] = sorted(set(unknown_codes))
        result["adaptive_paint_faces"] = int(adaptive_faces)

        model_settings = archive.read("Metadata/model_settings.config")
        support_check = slicer_safety.sanitize_model_settings_support(
            model_settings, mode="remove"
        )
        support_records = _safety_diagnostic_records(support_check.diagnostics)
        support_codes = {item.code for item in support_check.diagnostics}
        result["support_safety_diagnostics"] = support_records
        result["support_override_disabled"] = (
            not support_check.changed
            and not support_check.has_errors
            and "support_override_unrecognized" not in support_codes
        )

        project_settings = archive.read("Metadata/project_settings.config")
        project_diagnostics = slicer_safety.diagnose_project_settings(
            project_settings
        )
        try:
            decoded_settings = json.loads(project_settings.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded_settings = {}
        settings = decoded_settings if isinstance(decoded_settings, dict) else {}
        result["snapmaker_u1_metadata"] = (
            settings.get("printer_model") == "Snapmaker U1"
            and settings.get("printer_variant") == "0.4"
        )
        result["snapmaker_u1_print_settings"] = (
            settings.get("print_settings_id") == _SYSTEM_PRINT_SETTINGS_ID
        )
        result["snapmaker_u1_layer_height_008"] = (
            str(settings.get("layer_height", "")) == "0.08"
            and str(settings.get("initial_layer_print_height", "")) == "0.2"
            and str(settings.get("adaptive_layer_height", "")) == "0"
        )
        result["snapmaker_u1_transition_settings"] = all(
            str(settings.get(key, "")) == expected
            for key, expected in engine.SNAPMAKER_U1_008_TRANSITION_SETTINGS.items()
        )
        result["full_spectrum_stable_cadence_settings"] = all(
            str(settings.get(key, "")) == expected
            for key, expected in engine.FULL_SPECTRUM_STABLE_CADENCE_SETTINGS.items()
        )
        result["generic_pla_filament_settings"] = (
            settings.get("filament_settings_id")
            == [_GENERIC_PLA_FILAMENT_SETTINGS_ID] * 4
        )
        profiles = settings.get("filament_settings_id")
        result["generic_material_filament_settings"] = bool(
            isinstance(profiles, list)
            and len(profiles) == 4
            and len(set(profiles)) == 1
            and profiles[0] in _GENERIC_FILAMENT_SETTINGS_IDS
            and (
                expected_filament_profile is None
                or profiles == [expected_filament_profile] * 4
            )
        )
        result["project_support_disabled"] = "enable_support" not in settings
        shell_settings = {
            "wall_loops": "2",
            "wall_generator": "classic",
            "outer_wall_line_width": "0.42",
            "inner_wall_line_width": "0.42",
        }
        result["surface_shell_project_settings_exact"] = all(
            settings.get(key) == value for key, value in shell_settings.items()
        )
        result["surface_shell_project_settings_absent"] = all(
            key not in settings for key in shell_settings
        )

        grouped_cycle = slicer_safety._has_grouped_cycle_definition(settings)
        colors = settings.get("filament_colour")
        extremes = engine._surface_shell_extreme_slots(
            colors if isinstance(colors, list) else None
        )
        expected_support = None if extremes is None else str(extremes[1] + 1)
        result["surface_shell_grouped_cycle"] = grouped_cycle
        result["unsafe_grouped_cycle_detected"] = bool(grouped_cycle)
        result["surface_shell_support_tools_physical"] = (
            not grouped_cycle
            or all(
                slicer_safety._physical_tool_id(settings.get(key)) is not None
                for key in (
                    "support_filament",
                    "support_interface_filament",
                )
            )
        )
        result["surface_shell_support_uses_lightest_physical"] = (
            not grouped_cycle
            or (
                expected_support is not None
                and settings.get("support_filament") == expected_support
                and settings.get("support_interface_filament")
                == expected_support
            )
        )
        result["surface_shell_purge_to_print_disabled"] = (
            not grouped_cycle
            or all(
                settings.get(key) == "0"
                for key in (
                    "flush_into_infill",
                    "flush_into_support",
                    "flush_into_objects",
                )
            )
        )
        result["surface_shell_tool_override_safe"] = bool(
            result["surface_shell_support_tools_physical"]
            and result["surface_shell_purge_to_print_disabled"]
        )

        project_records = _safety_diagnostic_records(project_diagnostics)
        result["project_settings_diagnostics"] = project_records
        result["project_settings_diagnostic_messages"] = list(
            slicer_safety.format_diagnostics(project_diagnostics)
        )
        result["project_settings_error_count"] = sum(
            item.severity == "error" for item in project_diagnostics
        )
        result["project_settings_warning_count"] = sum(
            item.severity == "warning" for item in project_diagnostics
        )
        result["project_settings_line_width_safe"] = not project_diagnostics
        result["slicer_safe_project_defaults"] = (
            not bool(result["unsafe_grouped_cycle_detected"])
            and all(
            bool(result[key])
            for key in (
                "snapmaker_u1_metadata",
                "snapmaker_u1_print_settings",
                "snapmaker_u1_layer_height_008",
                "snapmaker_u1_transition_settings",
                "full_spectrum_stable_cadence_settings",
                "generic_material_filament_settings",
                "project_support_disabled",
                "support_override_disabled",
                "project_settings_line_width_safe",
                "surface_shell_tool_override_safe",
                "surface_shell_support_uses_lightest_physical",
            )
            )
        )

    if expected_faces is not None:
        result["portable_material_faces_match"] = int(len(p1_values)) == int(expected_faces)
        result["paint_color_faces_match"] = int(len(paint_values)) == int(expected_faces)
        result["portable_and_orca_states_match"] = counts.tolist() == paint_counts.tolist()
    return result


_original_write_3mf_atomic = engine.write_3mf_atomic


def _final_black_free_metadata(
    path,
    prepared,
    colors,
    palette,
    part_palettes,
    print_uses_global_palette,
):
    """Inspect final Orca paint trees and count every face using a black mix."""

    layout = parts.validate_part_layout(prepared.final)
    settings = models.AppSettings(
        palette=palette,
        part_palettes=dict(part_palettes or {}),
    )
    resolved = (
        (palette,) * layout.part_count
        if print_uses_global_palette
        else parts.resolve_part_palette_settings(settings, prepared.final)
    )
    output_face_ids = np.concatenate(
        [
            np.flatnonzero(layout.face_part_ids == part_id)
            for part_id in range(layout.part_count)
        ]
    )
    with ZipFile(Path(path), "r") as archive:
        model = archive.read("3D/Objects/object_1.model")
    paint_values = re.findall(rb'\spaint_color="([^"]+)"', model)
    if len(paint_values) != len(output_face_ids):
        raise engine.EngineError(
            "black-free gradient validation could not align final paint faces"
        )

    part_records: list[dict[str, object]] = []
    remaining_by_part = [0] * layout.part_count
    leaf_area_by_part = [0.0] * layout.part_count
    for raw_code, face_id in zip(paint_values, output_face_ids, strict=True):
        part_id = int(layout.face_part_ids[int(face_id)])
        part_palette = resolved[part_id]
        if (
            part_palette.color_mode == models.COLOR_MODE_FLAT_FOUR
            or not part_palette.black_free_gradient_enabled
        ):
            continue
        forbidden = mixer.black_containing_mixed_states(
            part_palette.palette_state_count,
            part_palette.black_free_black_slot,
        )
        code = raw_code.decode("ascii")
        simple_state = _PAINT_CODE_TO_STATE.get(code)
        if simple_state is not None:
            state_areas = np.zeros(mixer.PALETTE_STATE_COUNT, dtype=np.float64)
            state_areas[int(simple_state)] = 1.0
        else:
            try:
                state_areas = np.asarray(
                    smooth_paint.decode_paint_color(code).state_areas(),
                    dtype=np.float64,
                )
            except smooth_paint.PaintColorCodecError as exc:
                raise engine.EngineError(
                    "black-free gradient validation found an invalid paint tree"
                ) from exc
        black_area = float(state_areas[list(forbidden)].sum())
        if black_area > 0.0:
            remaining_by_part[part_id] += 1
            leaf_area_by_part[part_id] += black_area

    for part_id, (part_key, part_palette) in enumerate(
        zip(layout.part_keys, resolved, strict=True)
    ):
        part_records.append(
            {
                "part_index": part_id,
                "part_key": part_key,
                "enabled": bool(
                    part_palette.black_free_gradient_enabled
                    and part_palette.color_mode
                    != models.COLOR_MODE_FLAT_FOUR
                ),
                "black_slot": int(part_palette.black_free_black_slot),
                "red_slot": int(part_palette.black_free_red_slot),
                "brown_slot": int(part_palette.black_free_brown_slot),
                "remaining_black_mix_faces": int(remaining_by_part[part_id]),
                "remaining_black_mix_leaf_area": float(
                    leaf_area_by_part[part_id]
                ),
            }
        )
    role_sets = {
        (
            int(item["black_slot"]),
            int(item["red_slot"]),
            int(item["brown_slot"]),
        )
        for item in part_records
    }
    common_roles = next(iter(role_sets)) if len(role_sets) == 1 else None
    return {
        "schema": "tripo-spectrum-mapper.black-free-gradient.v1",
        "slot_index_base": 0,
        "enabled": bool(any(item["enabled"] for item in part_records)),
        "black_slot": None if common_roles is None else common_roles[0],
        "red_slot": None if common_roles is None else common_roles[1],
        "brown_slot": None if common_roles is None else common_roles[2],
        "remapped_faces": int(colors.black_free_remapped_faces),
        "remaining_black_mix_faces": int(sum(remaining_by_part)),
        "remaining_black_mix_leaf_area": float(sum(leaf_area_by_part)),
        "parts": part_records,
    }


def _rewrite_black_free_palette_metadata(path, metadata):
    """Replace only the policy record after final adaptive paint is known."""

    path = Path(path)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.black-free-",
        suffix=path.suffix,
        dir=path.parent,
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with ZipFile(path, "r") as source, ZipFile(
            temporary, "w", allowZip64=True
        ) as target:
            for info in source.infolist():
                payload = source.read(info.filename)
                if info.filename == "Metadata/full_spectrum_palette.json":
                    decoded = json.loads(payload.decode("utf-8"))
                    decoded["black_free_gradient"] = metadata
                    payload = json.dumps(
                        decoded, ensure_ascii=False, indent=2
                    ).encode("utf-8")
                target.writestr(info, payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_3mf_atomic_fixed(
    destination,
    prepared,
    colors,
    height_mm,
    palette,
    part_palettes=None,
    print_uses_global_palette=False,
):
    palette = models.without_surface_shell_output(palette)
    flat_four = palette.color_mode == models.COLOR_MODE_FLAT_FOUR
    if part_palettes:
        part_palettes = {
            key: models.without_surface_shell_output(value)
            for key, value in part_palettes.items()
        }
    validation = _original_write_3mf_atomic(
        destination,
        prepared,
        colors,
        height_mm,
        palette,
        part_palettes,
        print_uses_global_palette,
    )
    palette_hex = _normalize_palette_hex(palette)
    state_names = mixer.palette_state_names(
        list(palette.mix_ratios_b),
        list(palette.secondary_mix_ratios_b),
    )[: (4 if flat_four else palette.palette_state_count)]
    # Adaptive paint trees retain their original state IDs.  In Flat 4 Colors
    # the core writer has already remapped every face to F1-F4, so serializing
    # an old mixed-state tree here would silently reintroduce state 5+.  A flat
    # export deliberately uses the remapped whole-face colour instead.
    paint_trees = (
        None
        if flat_four
        else getattr(prepared, "_hotfix_subtriangle_paint", None)
    )
    _rewrite_3mf_portably(
        Path(destination), palette_hex, paint_trees, state_names
    )
    black_free_metadata = _final_black_free_metadata(
        destination,
        prepared,
        colors,
        palette,
        part_palettes,
        print_uses_global_palette,
    )
    _rewrite_black_free_palette_metadata(destination, black_free_metadata)
    portable = _inspect_portable_materials(
        Path(destination),
        len(prepared.final.faces),
        filament_materials.generic_filament_profile(palette.material),
    )
    validation.update(portable)
    if flat_four:
        portable_counts = portable.get("portable_material_state_counts", [])
        paint_counts = portable.get("paint_color_state_counts", [])
        leaf_areas = portable.get("paint_color_leaf_area_counts", [])
        if (
            portable.get("portable_palette_state_count") != 4
            or any(int(value) for value in portable_counts[4:])
            or any(int(value) for value in paint_counts[4:])
            or any(float(value) > 1e-12 for value in leaf_areas[4:])
        ):
            raise engine.EngineError(
                "Flat 4 Colorsの最終3MFに混色stateが残っています"
            )
    validation.update(
        {
            "black_free_gradient_enabled": bool(
                black_free_metadata["enabled"]
            ),
            "black_free_black_slot": black_free_metadata["black_slot"],
            "black_free_red_slot": black_free_metadata["red_slot"],
            "black_free_brown_slot": black_free_metadata["brown_slot"],
            "black_free_remapped_faces": int(
                black_free_metadata["remapped_faces"]
            ),
            "remaining_black_mix_faces": int(
                black_free_metadata["remaining_black_mix_faces"]
            ),
            "remaining_black_mix_leaf_area": float(
                black_free_metadata["remaining_black_mix_leaf_area"]
            ),
            "black_free_gradient_parts": list(
                black_free_metadata["parts"]
            ),
        }
    )
    validation["portable_material_colors_match"] = (
        portable.get("portable_material_colors") == [value.upper() for value in palette_hex]
    )
    validation["bytes"] = Path(destination).stat().st_size
    digest = hashlib.sha256()
    with Path(destination).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    validation["sha256"] = digest.hexdigest()
    validation["mix_display_overrides_present"] = bool(
        not flat_four
        and any(value is not None for value in palette.mix_hex_overrides)
    )
    validation["snapmaker_orca_tested_version"] = "2.3.5"
    validation["snapmaker_orca_minimum_version"] = "2.3.3"
    validation["snapmaker_orca_import_mode"] = "open_as_project"
    # Keep display targets explicit and separate from the physical cadence.
    # The latter is read back from the final archive so a portable rewrite can
    # never silently erase output-only black calibration.
    validation["display_mix_ratios_b_percent"] = (
        [] if flat_four else [int(value) for value in palette.mix_ratios_b]
    )
    validation["display_secondary_mix_ratios_b_percent"] = (
        []
        if flat_four
        else [int(value) for value in palette.secondary_mix_ratios_b]
    )
    recipe_validation = _inspect_mixed_definition_recipes(Path(destination))
    validation.update(recipe_validation)
    unsafe_grouped_cycle_detected = bool(
        recipe_validation.get("unsafe_grouped_cycle_detected")
        or portable.get("unsafe_grouped_cycle_detected")
    )
    validation["unsafe_grouped_cycle_detected"] = (
        unsafe_grouped_cycle_detected
    )
    if unsafe_grouped_cycle_detected:
        raise engine.EngineError(
            "廃止済みGrouped Cycleを検出しました。"
            "Snapmaker Orcaアクセス違反対策のため出力を中止します"
        )
    requested_output = recipe_validation[
        "requested_output_mix_ratios_b_percent"
    ]
    effective_output = recipe_validation[
        "effective_output_mix_ratios_b_percent"
    ]
    expected_specs = (
        ()
        if flat_four
        else mixer.print_palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            getattr(palette, "output_mix_ratios_b", None),
        )[: palette.palette_state_count - 4]
    )
    surface_shell_enabled = bool(
        not flat_four
        and getattr(palette, "surface_shell_enabled", False)
        and models.SURFACE_SHELL_OUTPUT_ENABLED
    )
    expected_definitions = (
        ""
        if flat_four
        else engine.make_portable_mixed_definitions(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            palette.palette_state_count,
            getattr(palette, "output_mix_ratios_b", None),
            surface_shell_enabled,
            palette.physical_hex,
        )
    )
    validation["mixed_definitions_match_output_specs"] = (
        recipe_validation["mixed_definition_string"] == expected_definitions
        and requested_output == [ratio for _left, _right, ratio in expected_specs]
    )
    shell_metadata = recipe_validation.get("surface_shell_metadata")
    if surface_shell_enabled:
        shell_specs = engine.build_surface_shell_output_specs(
            palette.physical_hex,
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            getattr(palette, "output_mix_ratios_b", None),
        )[: palette.palette_state_count - 4]
        applied = sum(spec.applied for spec in shell_specs)
        passthrough = sum(spec.disposition == "passthrough" for spec in shell_specs)
        fallback = sum(spec.disposition == "fallback" for spec in shell_specs)
        validation["surface_shell_exact"] = bool(
            isinstance(shell_metadata, dict)
            and shell_metadata.get("schema")
            == "tripo-spectrum-mapper.surface-shell.v2"
            and shell_metadata.get("enabled") is True
            and shell_metadata.get("policy") == "dark-mixes-only"
            and int(shell_metadata.get("applied_rows", -1)) == applied
            and int(shell_metadata.get("eligible_rows", -1)) == applied
            and int(shell_metadata.get("passthrough_rows", -1)) == passthrough
            and int(shell_metadata.get("fallback_rows", -1)) == fallback
            and recipe_validation["mixed_definition_cycle_rows"] == applied
            and recipe_validation["mixed_definition_cycle_rows_valid"]
            and recipe_validation["mixed_definition_manual_patterns"]
            == [spec.manual_pattern if spec.applied else None for spec in shell_specs]
            and portable.get("surface_shell_project_settings_exact") is True
        )
        validation["surface_shell_applied_rows"] = applied
        validation["surface_shell_passthrough_rows"] = passthrough
        validation["surface_shell_fallback_rows"] = fallback
    else:
        validation["surface_shell_exact"] = bool(
            shell_metadata is None
            and recipe_validation["mixed_definition_cycle_rows"] == 0
            and portable.get("surface_shell_project_settings_absent") is True
        )
        validation["surface_shell_applied_rows"] = 0
        validation["surface_shell_passthrough_rows"] = 0
        validation["surface_shell_fallback_rows"] = 0
    validation["surface_shell_enabled"] = surface_shell_enabled
    validation["output_ratio_override_active"] = bool(
        not flat_four
        and getattr(palette, "output_mix_ratios_b", None) is not None
    )
    # Compatibility aliases retained for callers that show the original two
    # six-state blocks.  They now correctly describe *output* cadence.
    validation["effective_mix_ratios_b_percent"] = list(effective_output[:6])
    validation["secondary_effective_mix_ratios_b_percent"] = list(
        effective_output[6:12]
    )
    if validation["mix_display_overrides_present"]:
        validation["mix_display_override_warning"] = (
            "Orca stores mix ratios, not arbitrary display colors. "
            "Use the ratio-predicted colors for an exact Orca preview."
        )
    return validation


_original_validate_3mf = engine.validate_3mf


def _validate_3mf_fixed(
    path,
    expected_vertices,
    expected_faces,
    expected_physical,
    expected_definitions,
    expected_parts=1,
    expected_filament_profile="Generic PLA",
    trusted_multipart_source_face_limits=None,
    trusted_multipart_pre_qem_face_counts=None,
    trusted_multipart_warning_policies=None,
    trusted_multipart_export_records=None,
):
    validation = _original_validate_3mf(
        path,
        expected_vertices,
        expected_faces,
        expected_physical,
        expected_definitions,
        expected_parts,
        expected_filament_profile,
        trusted_multipart_source_face_limits,
        trusted_multipart_pre_qem_face_counts,
        trusted_multipart_warning_policies,
        trusted_multipart_export_records,
    )
    try:
        validation.update(
            _inspect_portable_materials(
                Path(path), expected_faces, expected_filament_profile
            )
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        validation.update(
            {
                "portable_basematerials": False,
                "portable_material_faces_match": False,
                "portable_and_orca_states_match": False,
                "snapmaker_u1_metadata": False,
                "snapmaker_u1_print_settings": False,
                "snapmaker_u1_layer_height_008": False,
                "snapmaker_u1_transition_settings": False,
                "full_spectrum_stable_cadence_settings": False,
                "generic_pla_filament_settings": False,
                "generic_material_filament_settings": False,
                "project_support_disabled": False,
                "support_override_disabled": False,
                "support_safety_diagnostics": [],
                "project_settings_line_width_safe": False,
                "slicer_safe_project_defaults": False,
                "project_settings_error_count": 1,
                "project_settings_warning_count": 0,
                "project_settings_diagnostics": [
                    {
                        "code": "project_settings_inspection_failed",
                        "severity": "error",
                        "message": f"3MF safety metadata could not be inspected: {exc}",
                        "key": None,
                        "value": None,
                    }
                ],
                "project_settings_diagnostic_messages": [
                    f"[ERROR] 3MF safety metadata could not be inspected: {exc}"
                ],
            }
        )
    return validation


_original_write_guide = workflow.write_guide


def _write_guide_fixed(path, model_path, height_mm, palette):
    _original_write_guide(path, model_path, height_mm, palette)
    guide_path = Path(path)
    current = guide_path.read_text(encoding="utf-8")
    current = current.replace(
        "Snapmaker Orca 2.3.5以降",
        "Snapmaker Orca 2.3.3以降（2.3.5で確認済み）",
    )
    current = current.replace(
        "1. Snapmaker Orca 2.3.3以降（2.3.5で確認済み）でU1の新規・空プロジェクトを作ります。",
        "1. Snapmaker Orca 2.3.3以降（2.3.5で確認済み）を起動します。",
    )
    current = current.replace(
        "この3MFは「プロジェクトを開く」ではなく「形状としてインポート」します。",
        "この3MFは必ず「プロジェクトとして開く / Open as project」で開きます。",
    )
    current = current.replace(
        "読み込み方法を聞かれたら「Import geometry / 形状を読み込む」を選びます。",
        "読み込み方法を聞かれたら「Open as project / プロジェクトとして開く」を選びます。",
    )
    if palette.color_mode == models.COLOR_MODE_FLAT_FOUR:
        warning = (
            "\n\n"
            "【Flat 4 Colors】\n"
            "----------------\n"
            "・この3MFはF1〜F4の物理4色だけを使用し、混色stateは0色です。\n"
            "・色IDと物理スロットを保つため、必ず『プロジェクトとして開く』を選びます。\n"
            "・公式 Snapmaker Orca 2.3.3以降を使用します（2.3.5で確認済み）。\n"
            "・通常層0.08 mm、初層0.20 mmです。\n"
            "・サポートは3MFで固定していません。モデルごとにOrca上で選択してください。\n"
        )
        guide_path.write_text(
            current.rstrip() + warning,
            encoding="utf-8",
            newline="\n",
        )
        return
    warning = (
        "\n\n"
        "【重要・Snapmaker Orcaで同じ色を表示するために】\n"
        "--------------------------------\n"
        "・公式 Snapmaker Orca 2.3.3以降を使用します（2.3.5で確認済み）。\n"
        "・この3MFは『形状としてインポート』せず、必ず『プロジェクトとして開く』を選びます。\n"
        "・形状として読み込むと混色定義が無視され、現在の別パレットで色が解釈されます。\n"
        "・本ファイルにはOrca用paint_colorと一般ビューア用標準3MF色材の両方を記録済みです。\n"
        "・本ソフトの混色表示はOrca 2.3.5で確認した印刷可能なレイヤー比率へ丸めてあります。\n"
        "・公式0.08 Extra Fineプロファイルを指定しています。通常層0.08 mm、初層0.20 mmです。\n"
        "・公式0.08プロファイルのリブ型プライムタワーとooze preventionを記録済みです。\n"
        "・通常の固定レイヤー混色を使用し、実験的なLocal Z／高度なDithering／Pointillismは無効です。\n"
        "・サポートは3MFで固定していません。モデルごとにOrca上で選択してください。\n"
    )
    if any(value is not None for value in palette.mix_hex_overrides):
        warning += (
            "・警告: 任意の混色表示HEXが使われています。Orcaに保存されるのは混色比率なので、\n"
            "  スライス表示は任意HEXと完全一致しない場合があります。\n"
        )
    if bool(
        getattr(palette, "surface_shell_enabled", False)
        and models.SURFACE_SHELL_OUTPUT_ENABLED
    ):
        shell_specs = engine.build_surface_shell_output_specs(
            palette.physical_hex,
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            getattr(palette, "output_mix_ratios_b", None),
        )[: palette.palette_state_count - 4]
        applied = sum(spec.applied for spec in shell_specs)
        fallback = len(shell_specs) - applied
        warning += (
            "・2ウォール表面混色が有効です。Classic wall、wall 2本、外壁／内壁0.42 mmを変更しないでください。\n"
            f"・表面Cycle適用 {applied}行、従来recipeへのfallback {fallback}行です。黒補正との併用を推奨します。\n"
            "・基準は縦側面の2ウォールです。top/bottom、infill、support、purge経路は同じ局所表面比を保証しません。\n"
        )
    else:
        warning += (
            "・黒混色の内壁Cycleは現在無効です（Snapmaker Orcaアクセス違反対策）。\n"
            "・実機黒補正のRatio出力は従来どおり保持されます。\n"
        )
    guide_path.write_text(current.rstrip() + warning, encoding="utf-8", newline="\n")


# Keep the names imported directly by workflow in sync with the engine patch.
engine.validate_3mf = _validate_3mf_fixed
engine.write_3mf_atomic = _write_3mf_atomic_fixed
workflow.write_3mf_atomic = _write_3mf_atomic_fixed
workflow.write_guide = _write_guide_fixed


# --- Painting correctness -------------------------------------------------

_original_set_overrides = paint.PaintSession._set_overrides


def _set_overrides_fixed(self, face_indices, values, label):
    """Do not report a paint operation when its visible color is unchanged."""
    if np.isscalar(values):
        state = int(values)
        indices = np.asarray(face_indices)
        if (
            0 <= state < mixer.PALETTE_STATE_COUNT
            and indices.ndim == 1
            and len(indices)
            and np.issubdtype(indices.dtype, np.integer)
        ):
            valid = (indices >= 0) & (indices < len(self.faces))
            if bool(np.all(valid)):
                existing = np.asarray(self.overrides)[indices]
                automatic = np.asarray(self.auto_indices)[indices]
                effective = np.where(existing >= 0, existing, automatic)
                indices = indices[effective != state]
                if len(indices) == 0:
                    return np.empty(0, dtype=np.int32)
                face_indices = indices
    return _original_set_overrides(self, face_indices, values, label)


paint.PaintSession._set_overrides = _set_overrides_fixed


_original_connected_fill_faces = paint.PaintSession.connected_fill_faces


def _connected_fill_faces_fixed(self, seed_face):
    """Run large connected fills in SciPy's compiled graph traversal."""
    seed = int(seed_face)
    face_count = len(self.faces)
    if seed < 0 or seed >= face_count:
        return _original_connected_fill_faces(self, seed_face)
    allowed_value = getattr(self, "allowed_face_mask", None)
    allowed = (
        np.ones(face_count, dtype=bool)
        if allowed_value is None
        else np.asarray(allowed_value, dtype=bool)
    )
    if allowed.shape != (face_count,) or not bool(allowed[seed]):
        return _original_connected_fill_faces(self, seed_face)
    if face_count < 20_000:
        return _original_connected_fill_faces(self, seed_face)
    try:
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import breadth_first_order

        labels = self.effective_indices()
        target = labels[seed]
        neighbors = np.asarray(self.neighbors, dtype=np.int32)
        sources = np.repeat(np.arange(face_count, dtype=np.int32), neighbors.shape[1])
        destinations = neighbors.reshape(-1)
        valid = destinations >= 0
        valid &= allowed[sources]
        valid &= labels[sources] == target
        safe_destinations = np.where(destinations >= 0, destinations, 0)
        valid &= allowed[safe_destinations]
        valid &= labels[safe_destinations] == target
        sources = sources[valid]
        destinations = destinations[valid]
        graph = csr_matrix(
            (np.ones(len(sources), dtype=np.uint8), (sources, destinations)),
            shape=(face_count, face_count),
        )
        selected = breadth_first_order(
            graph, seed, directed=False, return_predecessors=False
        )
        return np.asarray(selected, dtype=np.int32)
    except Exception:
        return _original_connected_fill_faces(self, seed_face)


paint.PaintSession.connected_fill_faces = _connected_fill_faces_fixed


_original_fill = paint.PaintSession.fill


def _fill_fixed(self, seed_face, state):
    seed = int(seed_face)
    requested = int(state)
    if (
        0 <= seed < len(self.faces)
        and 0 <= requested < mixer.PALETTE_STATE_COUNT
    ):
        if int(self.effective_indices()[seed]) == requested:
            return np.empty(0, dtype=np.int32)
    return _original_fill(self, seed_face, state)


paint.PaintSession.fill = _fill_fixed


def _face_at_fixed(self, x: int, y: int) -> int:
    """Permit edits while a color-only redraw is in flight.

    A camera change still waits for a matching pick map, preventing selection of
    the wrong face.  The original implementation rejected every click whenever
    any redraw (including color-only redraws) was pending.
    """
    mapping = self.target_mapping
    ids = self.face_ids
    if mapping is None or ids is None:
        return -1
    pick_camera = getattr(self, "_hotfix_pick_camera", None)
    if pick_camera != self.camera and bool(getattr(self, "_render_dirty", False)):
        return -1
    if pick_camera != self.camera and not bool(getattr(self, "_render_dirty", False)):
        self._hotfix_pick_camera = self.camera
    left, top, width, height, render_width, render_height = mapping
    if not (left <= x < left + width and top <= y < top + height):
        return -1
    rx = min(render_width - 1, max(0, int((x - left) * render_width / width)))
    ry = min(render_height - 1, max(0, int((y - top) * render_height / height)))
    face = int(ids[ry, rx])
    if face < 0:
        return -1
    level = getattr(self, "level", None)
    if level is None:
        return face
    part_ids = np.asarray(getattr(level, "face_part_ids", ()))
    active_part_id = int(getattr(self, "active_part_id", 0))
    if (
        part_ids.shape == (len(level.faces),)
        and int(part_ids[face]) != active_part_id
    ):
        return -1
    return face


paint_gui.PaintEditorWindow._face_at = _face_at_fixed


# --- Windows mouse modifier correction ----------------------------------

# Tk on Windows reports NumLock with the same low state bit (Mod1 / 0x0008)
# that the original editor treated as Alt.  With NumLock enabled, every normal
# left click therefore entered the 3D eyedropper branch and returned before a
# brush or fill could run.  Read the real Alt key from Win32 and normalize only
# that bit before handing the event to the original editor logic.
_original_editor_left_press = paint_gui.PaintEditorWindow._on_left_press


def _windows_alt_key_down() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.GetKeyState(0x12) & 0x8000)
    except (AttributeError, OSError):
        return False


def _normalized_left_press_state(
    state: int,
    *,
    windows: bool | None = None,
    alt_down: bool | None = None,
) -> int:
    normalized = int(state)
    is_windows = os.name == "nt" if windows is None else bool(windows)
    if not is_windows:
        return normalized
    pressed = (
        bool(normalized & 0x20000) or _windows_alt_key_down()
        if alt_down is None
        else bool(alt_down)
    )
    if pressed:
        return normalized | 0x0008
    return normalized & ~0x0008


class _MouseEventProxy:
    def __init__(self, event, state: int):
        self._event = event
        self.state = int(state)

    def __getattr__(self, name):
        return getattr(self._event, name)


def _on_left_press_fixed(self, event):
    state = _normalized_left_press_state(getattr(event, "state", 0))
    if state != int(getattr(event, "state", 0)):
        event = _MouseEventProxy(event, state)
    return _original_editor_left_press(self, event)


paint_gui.PaintEditorWindow._on_left_press = _on_left_press_fixed


_original_consume_snapshot = paint_gui.PaintEditorWindow._consume_snapshot


def _consume_snapshot_fixed(self, value):
    frame = value.get("frame") if isinstance(value, dict) else None
    if (
        frame is not None
        and frame.camera == self.camera
        and frame.face_ids is not None
    ):
        self._hotfix_pick_camera = frame.camera

    # Edit snapshots contain labels/overrides but no new pixels.  Drawing here
    # shows the old frame and then draws again after render completion.
    skip_stale_draw = frame is None and isinstance(value, dict)
    if not skip_stale_draw:
        return _original_consume_snapshot(self, value)

    had_override = "_draw_canvas" in self.__dict__
    previous = self.__dict__.get("_draw_canvas")
    self._draw_canvas = lambda: None
    try:
        return _original_consume_snapshot(self, value)
    finally:
        if had_override:
            self._draw_canvas = previous
        else:
            del self.__dict__["_draw_canvas"]


paint_gui.PaintEditorWindow._consume_snapshot = _consume_snapshot_fixed


def _request_render_fixed(self):
    self._render_after = None
    if self._job_running:
        self._pending_render = True
        return
    camera = self.camera
    need_face_ids = (
        self.face_ids is None
        or getattr(self, "_hotfix_pick_camera", None) != camera
    )

    def work():
        if self._renderer is None or self._display_colors is None:
            return None
        frame = self._renderer.render(
            self._display_colors,
            camera=camera,
            render_source=False,
            render_target=True,
            render_face_ids=need_face_ids,
        )
        if not need_face_ids:
            rotation_adapter = globals().get("_rotation_hotfix")
            restore_outline = getattr(
                rotation_adapter,
                "_restore_cached_active_part_outline",
                None,
            )
            if callable(restore_outline):
                frame = restore_outline(self, frame, camera, renderer)
        return camera, frame

    self._submit("render", work)


paint_gui.PaintEditorWindow._request_render = _request_render_fixed


def _worker_refresh_after_edit_fixed(self, message: str, changed: int):
    if self._session is None or self._auto_colors is None:
        raise RuntimeError("Color editor has not been initialized")
    overrides = np.asarray(self._session.overrides, dtype=np.int8)
    automatic = np.asarray(self._auto_colors.palette_indices, dtype=np.int8)
    previous = self._display_colors
    if previous is None or np.asarray(previous.palette_indices).shape != automatic.shape:
        refreshed = engine.apply_palette_overrides_parts(
            self.level,
            self.settings.geometry.height_mm,
            self.settings.palette,
            getattr(self.settings, "part_palettes", {}),
            self._auto_colors,
            overrides,
        )
    else:
        mask = overrides >= 0
        indices = automatic.copy()
        indices[mask] = overrides[mask]
        changed_faces = np.flatnonzero(indices != np.asarray(previous.palette_indices))

        # Large fills are faster through the original all-face vectorized path;
        # brushes and ordinary fills only recompute the affected face colours.
        if len(changed_faces) >= max(1, len(indices) // 4):
            refreshed = engine.apply_palette_overrides_parts(
                self.level,
                self.settings.geometry.height_mm,
                self.settings.palette,
                getattr(self.settings, "part_palettes", {}),
                self._auto_colors,
                overrides,
            )
        else:
            layout = parts.validate_part_layout(self.level)
            palette_settings = (
                self.settings
                if isinstance(self.settings, models.AppSettings)
                else models.AppSettings(
                    palette=self.settings.palette,
                    part_palettes=dict(
                        getattr(self.settings, "part_palettes", {})
                    ),
                )
            )
            palette_tables = parts.build_part_palette_rgb_tables(
                palette_settings, layout
            )
            target_rgb = np.asarray(previous.target_face_rgb).copy()
            delta_e = np.asarray(previous.delta_e).copy()
            if len(changed_faces):
                changed_states = indices[changed_faces]
                changed_parts = layout.face_part_ids[changed_faces]
                target_rgb[changed_faces] = palette_tables[
                    changed_parts, changed_states
                ]
                stored_tone_faces = getattr(
                    self._auto_colors, "tone_face_rgb", None
                )
                if stored_tone_faces is None:
                    tone_faces = np.asarray(
                        self._auto_colors.tone_vertex_rgb
                    )[self.level.faces[changed_faces]].mean(axis=1)
                else:
                    tone_faces = np.asarray(stored_tone_faces)[changed_faces]
                face_lab = engine.srgb_to_lab(tone_faces)
                target_lab = engine.srgb_to_lab(target_rgb[changed_faces])
                delta_e[changed_faces] = np.linalg.norm(
                    face_lab - target_lab, axis=1
                )

            counts = np.bincount(indices, minlength=mixer.PALETTE_STATE_COUNT)
            areas_mm2 = self.level.areas_unit * float(
                self.settings.geometry.height_mm
            ) ** 2
            area_by_state = np.bincount(
                indices, weights=areas_mm2, minlength=mixer.PALETTE_STATE_COUNT
            )
            fractions = area_by_state / max(float(area_by_state.sum()), 1e-12)
            refreshed = models.ColorResult(
                tone_vertex_rgb=self._auto_colors.tone_vertex_rgb,
                source_face_rgb=self._auto_colors.source_face_rgb,
                palette_indices=indices,
                target_face_rgb=target_rgb,
                delta_e=delta_e,
                smoothed_faces=self._auto_colors.smoothed_faces,
                palette_face_counts=counts,
                palette_area_fractions=fractions,
                pink_area_fraction=float(fractions[engine.PINK_STATES].sum()),
                manual_override_faces=int(np.count_nonzero(mask)),
                black_free_remapped_faces=int(
                    getattr(previous, "black_free_remapped_faces", 0)
                ),
                part_metrics=list(getattr(previous, "part_metrics", [])),
                tone_face_rgb=getattr(
                    self._auto_colors, "tone_face_rgb", None
                ),
                tone_face_rgb_flat=bool(
                    getattr(self._auto_colors, "tone_face_rgb_flat", False)
                ),
            )
    self._display_colors = refreshed
    if self._renderer is not None:
        self._renderer.invalidate_colors(source=False, target=True)
    return self._worker_snapshot(None, message, changed)


paint_gui.PaintEditorWindow._worker_refresh_after_edit = _worker_refresh_after_edit_fixed


# --- Rendering performance -----------------------------------------------

_original_orbit_camera_mvp = renderer._orbit_camera_mvp
_bounds_cache: OrderedDict[int, tuple[weakref.ReferenceType[np.ndarray], np.ndarray, np.ndarray]] = OrderedDict()


class _BoundsOnlyVertices:
    def __init__(self, minimum: np.ndarray, maximum: np.ndarray):
        self._minimum = minimum
        self._maximum = maximum

    def min(self, axis=0):
        if axis != 0:
            raise ValueError("Only axis=0 is supported")
        return self._minimum

    def max(self, axis=0):
        if axis != 0:
            raise ValueError("Only axis=0 is supported")
        return self._maximum


def _orbit_camera_mvp_fixed(vertices, size, camera):
    key = id(vertices)
    cached = _bounds_cache.get(key)
    if cached is None or cached[0]() is not vertices:
        minimum = np.asarray(vertices).min(axis=0)
        maximum = np.asarray(vertices).max(axis=0)
        cached = (weakref.ref(vertices), minimum, maximum)
        _bounds_cache[key] = cached
        while len(_bounds_cache) > 8:
            _bounds_cache.popitem(last=False)
    else:
        _bounds_cache.move_to_end(key)
    proxy = _BoundsOnlyVertices(cached[1], cached[2])
    return _original_orbit_camera_mvp(proxy, size, camera)


renderer._orbit_camera_mvp = _orbit_camera_mvp_fixed


_original_render_front_preview = renderer.render_front_preview
_original_render_front_preview_pair = getattr(
    renderer, "render_front_preview_pair", None
)
_preview_renderers: dict[
    int, tuple[weakref.ReferenceType[object], tuple[int, int], tuple[int, int, int], object]
] = {}


def _discard_preview_renderer(thread_id: int) -> None:
    cached = _preview_renderers.pop(int(thread_id), None)
    if cached is not None:
        try:
            cached[3].close()
        except Exception:
            pass


def _cached_preview_renderer(level, size, background):
    """Return the worker-thread renderer shared by single and paired previews."""

    thread_id = threading.get_ident()
    cached = _preview_renderers.get(thread_id)
    current = cached[0]() if cached is not None else None
    if (
        cached is None
        or current is not level
        or cached[1] != size
        or cached[2] != background
    ):
        _discard_preview_renderer(thread_id)
        interactive = renderer.InteractiveMeshRenderer(
            level, size=size, background=background
        )
        _preview_renderers[thread_id] = (
            weakref.ref(level),
            size,
            background,
            interactive,
        )
        return interactive
    return cached[3]


def _adaptive_preview_context(level):
    adaptive_context = _smooth_paint_hotfix.lookup_tree_context(level)
    adaptive_trees = None
    if adaptive_context is not None and adaptive_context[0]:
        adaptive_trees = adaptive_context[0]
    return adaptive_trees, getattr(level, "_hotfix_palette", None)


def _compose_adaptive_preview_target(image, level, adaptive_trees, face_ids, camera):
    adaptive_palette = getattr(level, "_hotfix_palette", None)
    if adaptive_trees is None or adaptive_palette is None:
        return image
    return _smooth_paint_hotfix.compose_target_image(
        image,
        level,
        adaptive_trees,
        camera=camera,
        face_ids=face_ids,
        palette=adaptive_palette,
        part_palette_rgb_tables=getattr(
            level, "_hotfix_part_palette_rgb_tables", None
        ),
        face_part_ids=getattr(level, "_hotfix_face_part_ids", None),
        renderer_module=renderer,
        mixer_module=mixer,
    )


def _preview_face_part_ids(level):
    face_count = len(np.asarray(level.faces))
    raw_part_ids = getattr(level, "face_part_ids", None)
    if raw_part_ids is None or np.asarray(raw_part_ids).size == 0:
        return np.zeros(face_count, dtype=np.int32)
    part_ids = np.asarray(raw_part_ids)
    if (
        part_ids.shape != (face_count,)
        or not np.issubdtype(part_ids.dtype, np.integer)
        or (len(part_ids) and int(part_ids.min()) < 0)
    ):
        raise renderer.RendererError(
            "face_part_ids must contain one non-negative integer per face"
        )
    return part_ids.astype(np.int32, copy=False)


def _render_front_preview_fixed(
    level,
    result,
    *,
    mode="target",
    size=(600, 740),
    background=(9, 10, 13),
    shaded=True,
):
    """Reuse the OpenGL context for the two preview panels and later updates."""
    thread_id = threading.get_ident()
    normalized_size = (int(size[0]), int(size[1]))
    normalized_background = tuple(int(value) for value in background)
    try:
        interactive = _cached_preview_renderer(
            level, normalized_size, normalized_background
        )

        render_source = mode == "source"
        render_target = mode == "target"
        if not render_source and not render_target:
            raise ValueError(f"Unknown preview mode: {mode!r}")
        adaptive_trees = None
        if render_target:
            adaptive_trees, _adaptive_palette = _adaptive_preview_context(level)
        frame = interactive.render(
            result,
            render_source=render_source,
            render_target=render_target,
            render_face_ids=adaptive_trees is not None,
            shaded=bool(shaded),
        )
        image = frame.source if render_source else frame.target
        if image is None:
            raise RuntimeError("The preview renderer returned no image")
        if render_target:
            image = _compose_adaptive_preview_target(
                image, level, adaptive_trees, frame.face_ids, frame.camera
            )
        return image
    except Exception:
        _discard_preview_renderer(thread_id)
        return _original_render_front_preview(
            level,
            result,
            mode=mode,
            size=normalized_size,
            background=normalized_background,
            shaded=shaded,
        )


def _render_front_preview_pair_fixed(
    level,
    result,
    *,
    size=(600, 740),
    background=(9, 10, 13),
    shaded=True,
    active_part_id=None,
    outline_color=(36, 224, 255),
    outline_thickness=2,
):
    """Render both comparison panels through the cached adaptive pipeline.

    The adaptive target is composed before the non-destructive part outline,
    so subdivided paint can neither cover the selection cue nor disappear when
    the main GUI switches from the legacy two-call path to this paired API.
    """

    if _original_render_front_preview_pair is None:
        raise renderer.RendererError("paired front preview is unavailable")

    normalized_size = (int(size[0]), int(size[1]))
    normalized_background = tuple(int(value) for value in background)
    selected_part = None if active_part_id is None else int(active_part_id)
    face_part_ids = None
    if selected_part is not None:
        face_part_ids = _preview_face_part_ids(level)
        if selected_part < 0 or not bool(np.any(face_part_ids == selected_part)):
            raise renderer.RendererError(
                f"unknown active part ID: {active_part_id}"
            )

    thread_id = threading.get_ident()
    try:
        interactive = _cached_preview_renderer(
            level, normalized_size, normalized_background
        )
        adaptive_trees, _adaptive_palette = _adaptive_preview_context(level)
        frame = interactive.render(
            result,
            render_source=True,
            render_target=True,
            render_face_ids=True,
            shaded=bool(shaded),
        )
        if frame.source is None or frame.target is None or frame.face_ids is None:
            raise RuntimeError("The paired preview renderer returned incomplete images")

        source = frame.source
        target = _compose_adaptive_preview_target(
            frame.target,
            level,
            adaptive_trees,
            frame.face_ids,
            frame.camera,
        )
        if selected_part is not None and face_part_ids is not None:
            outline_options = {
                "color": outline_color,
                "thickness": outline_thickness,
            }
            source = renderer.overlay_active_part_outline(
                source,
                frame.face_ids,
                face_part_ids,
                selected_part,
                **outline_options,
            )
            target = renderer.overlay_active_part_outline(
                target,
                frame.face_ids,
                face_part_ids,
                selected_part,
                **outline_options,
            )
        return renderer.FrontPreviewPair(
            source=source,
            target=target,
            face_ids=frame.face_ids,
        )
    except Exception:
        _discard_preview_renderer(thread_id)
        return _original_render_front_preview_pair(
            level,
            result,
            size=normalized_size,
            background=normalized_background,
            shaded=shaded,
            active_part_id=active_part_id,
            outline_color=outline_color,
            outline_thickness=outline_thickness,
        )


renderer.render_front_preview = _render_front_preview_fixed
renderer.render_front_preview_pair = _render_front_preview_pair_fixed
gui.render_front_preview = _render_front_preview_fixed
gui.render_front_preview_pair = _render_front_preview_pair_fixed
workflow.render_front_preview = _render_front_preview_fixed
workflow.render_front_preview_pair = _render_front_preview_pair_fixed


def _manual_reference_is_visible(instance) -> bool:
    """Read the optional ribbon reference toggle without breaking old builds."""

    variable = getattr(instance, "reference_visible_var", None)
    if variable is None:
        return True
    getter = getattr(variable, "get", None)
    try:
        return bool(getter()) if callable(getter) else bool(variable)
    except Exception:
        # A destroyed Tk variable should not make final cleanup draws fail.
        return True


def _cache_large_reference_for_draw(instance, original_draw, canvas_name, columns):
    source = getattr(instance, "reference_image", None)
    if source is None or source.width * source.height < 1_000_000:
        return original_draw(instance)
    canvas = getattr(instance, canvas_name)
    width_floor, height_floor = ((720, 420) if columns == 2 else (600, 360))
    width = max(width_floor, canvas.winfo_width())
    height = max(height_floor, canvas.winfo_height())
    margin = 14
    title_height = 34
    if columns == 2:
        layout_helper = getattr(paint_gui, "compute_manual_canvas_layout", None)
        layout = None
        if callable(layout_helper):
            try:
                layout = layout_helper(
                    width,
                    height,
                    _manual_reference_is_visible(instance),
                )
            except Exception:
                layout = None
        reference_panel = (
            layout.get("reference") if isinstance(layout, dict) else None
        )
        if (
            isinstance(reference_panel, (tuple, list))
            and len(reference_panel) >= 2
            and isinstance(layout, dict)
        ):
            panel_width = max(1, int(reference_panel[1]))
            panel_height = max(1, int(layout.get("panel_height", 300)))
        else:
            gap = 14
            panel_width = max(260, int((width - margin * 2 - gap) * 0.36))
            panel_height = max(300, height - margin * 2 - title_height)
    else:
        gap = 12
        panel_width = max(160, (width - margin * 2 - gap * 2) // 3)
        panel_height = max(240, height - margin * 2 - title_height)

    from PIL import Image, ImageOps

    key = (id(source), source.size, panel_width, panel_height)
    cache = getattr(instance, "_hotfix_reference_cache", None)
    if cache is None or cache[0] != key:
        contained = ImageOps.contain(
            source.convert("RGB"),
            (panel_width, panel_height),
            method=Image.Resampling.LANCZOS,
        )
        cache = (key, contained)
        instance._hotfix_reference_cache = cache
    instance.reference_image = cache[1]
    try:
        result = original_draw(instance)
    finally:
        instance.reference_image = source
    mapping = getattr(instance, "reference_mapping", None)
    if mapping is not None:
        instance.reference_mapping = (*mapping[:4], source.width, source.height)
    return result


_original_paint_draw_canvas = paint_gui.PaintEditorWindow._draw_canvas


def _paint_draw_canvas_fixed(self):
    if not _manual_reference_is_visible(self):
        # The ribbon editor normally gives the whole workspace to the 3D view.
        # Avoid resizing/caching a large source image that will not be drawn.
        result = _original_paint_draw_canvas(self)
    else:
        result = _cache_large_reference_for_draw(
            self, _original_paint_draw_canvas, "canvas", 2
        )
    # render_done is consumed directly by the original queue poller, so this is
    # the first safe main-thread point where the new ID image and camera match.
    if self.face_ids is not None and not bool(getattr(self, "_render_dirty", False)):
        self._hotfix_pick_camera = self.camera
    return result


paint_gui.PaintEditorWindow._draw_canvas = _paint_draw_canvas_fixed


_original_comparison_draw = gui.MapperApp._draw_comparison_canvas


def _comparison_draw_fixed(self):
    result = _cache_large_reference_for_draw(
        self, _original_comparison_draw, "preview_canvas", 3
    )
    canvas = self.preview_canvas
    width = max(600, canvas.winfo_width())
    height = max(360, canvas.winfo_height())
    margin, gap, title_height = 14, 12, 34
    panel_width = max(160, (width - margin * 2 - gap * 2) // 3)
    panel_height = max(240, height - margin * 2 - title_height)
    top = margin + title_height
    # Only the converted-color preview opens Manual Editing.  The Tripo source
    # preview is deliberately read-only so clicking it cannot imply that the
    # original OBJ itself is being painted.
    index = 2
    left = margin + index * (panel_width + gap)
    boxes = [(left, top, left + panel_width, top + panel_height)]
    self._hotfix_paint_panel_boxes = boxes

    if getattr(self, "prepared", None) is not None:
        for left, _top, right, bottom in boxes:
            canvas.create_rectangle(
                left + 8,
                bottom - 48,
                right - 8,
                bottom - 8,
                fill="#102A35",
                outline=gui.ACCENT,
                width=2,
                tags=("hotfix-paint-hint",),
            )
            canvas.create_text(
                (left + right) // 2,
                bottom - 28,
                text=self.i18n.text("preview.open_manual"),
                fill=gui.ACCENT,
                font=("Yu Gothic UI", 9, "bold"),
                width=max(80, panel_width - 24),
                tags=("hotfix-paint-hint",),
            )
    return result


gui.MapperApp._draw_comparison_canvas = _comparison_draw_fixed


_original_canvas_click = gui.MapperApp._on_canvas_click


def _canvas_click_fixed(self, event):
    for left, top, right, bottom in getattr(self, "_hotfix_paint_panel_boxes", []):
        if left <= event.x < right and top <= event.y < bottom:
            if getattr(self, "eyedropper_active", False):
                self._toggle_eyedropper()
            if getattr(self, "_hotfix_editor_open_pending", False):
                return None
            self._hotfix_editor_open_pending = True
            self.status_var.set(self.i18n.text("state.opening_manual"))

            def open_editor():
                self._hotfix_editor_open_pending = False
                self._open_paint_editor()

            self.root.after_idle(open_editor)
            return None
    return _original_canvas_click(self, event)


gui.MapperApp._on_canvas_click = _canvas_click_fixed


def _paint_panel_motion(self, event):
    inside = any(
        left <= event.x < right and top <= event.y < bottom
        for left, top, right, bottom in getattr(self, "_hotfix_paint_panel_boxes", [])
    )
    cursor = "hand2" if inside else ("crosshair" if self.eyedropper_active else "arrow")
    try:
        if self.preview_canvas.cget("cursor") != cursor:
            self.preview_canvas.configure(cursor=cursor)
    except Exception:
        pass


_original_launch_orca = gui.MapperApp._launch_orca


def _launch_orca_fixed(self):
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    official = program_files / "Snapmaker_Orca" / "snapmaker-orca.exe"
    if not official.exists():
        return _original_launch_orca(self)
    try:
        gui.subprocess.Popen([str(official)], cwd=str(official.parent))
        self.status_var.set(
            "Snapmaker Orca 2.3.5を起動しました。3MFはプロジェクトとして開いてください"
        )
    except OSError as exc:
        gui.messagebox.showerror(
            "Snapmaker Orcaを起動できません", str(exc), parent=self.root
        )


gui.MapperApp._launch_orca = _launch_orca_fixed


_original_app_init = gui.MapperApp.__init__


@functools.wraps(_original_app_init)
def _app_init_fixed(self, *args, **kwargs):
    _original_app_init(self, *args, **kwargs)
    try:
        root = getattr(self, "root", self)
        root.title(gui.APP_TITLE)
    except Exception:
        pass
    try:
        self._hotfix_paint_button = getattr(self, "manual_edit_button", None)
        self.preview_canvas.bind(
            "<Motion>", lambda event: _paint_panel_motion(self, event), add="+"
        )
        self.preview_canvas.bind(
            "<Leave>", lambda _event: self.preview_canvas.configure(cursor="arrow"), add="+"
        )
    except Exception:
        pass


gui.MapperApp.__init__ = _app_init_fixed


_original_editor_init = paint_gui.PaintEditorWindow.__init__


@functools.wraps(_original_editor_init)
def _editor_init_fixed(self, *args, **kwargs):
    _original_editor_init(self, *args, **kwargs)
    try:
        self._title_version = gui.APP_TITLE
        self.set_language(self.i18n.language)
    except Exception:
        pass


paint_gui.PaintEditorWindow.__init__ = _editor_init_fixed


# Install the two larger, independently tested adapters last so they wrap the
# correctness fixes above.  Rotation remains responsive while the adaptive
# brush retains exact picker data only for a settled camera.
import rotation_hotfix as _rotation_hotfix
import smooth_paint_hotfix as _smooth_paint_hotfix


_rotation_hotfix.apply_rotation_hotfix(paint_gui, renderer)
_smooth_paint_hotfix.apply_smooth_paint_hotfix(
    paint_gui,
    paint,
    renderer,
    mixer,
    engine,
)

# Keep adaptive sub-triangle paint resident on the same worker-owned OpenGL
# renderer.  CPU/PIL composition remains available as a safe fallback, but the
# normal path now preserves the exact painted detail while orbiting and avoids
# work proportional to every previous manual stroke on each Canvas redraw.
import adaptive_gpu_overlay as _adaptive_gpu_overlay


_adaptive_gpu_overlay.install_gpu_overlay(
    renderer,
    mixer,
    _smooth_paint_hotfix.lookup_tree_context,
)

# Replace the recovered allocating cursor last, after every input and Canvas
# wrapper is installed.  The adapter reuses one round/rectangular Canvas item
# and therefore stays cheap even during very dense pointer motion.
import brush_cursor_hotfix as _brush_cursor_hotfix


_brush_cursor_hotfix.apply_brush_cursor_hotfix(paint_gui)


def apply_hotfixes() -> str:
    """Public marker used by smoke tests and support diagnostics."""
    return HOTFIX_VERSION
