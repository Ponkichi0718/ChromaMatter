from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import engine, mixer
from .filament_materials import generic_filament_profile, normalize_filament_material
from .models import ColorResult, MeshLevel, ObjAsset, PaletteSettings, PreparedGeometry


CALIBRATION_SCHEMA = "obj-adjuster.palette-calibration.v1"
VALIDATION_SCHEMA = "obj-adjuster.palette-calibration-validation.v1"
BASE_STATE = 1  # zero based: F2 is the common backing, whatever its color
GRID_COLUMNS = 5
GRID_ROWS = len(mixer.PAIR_INDICES) + 1  # six mixed families + F1-F4
BASE_WIDTH_MM = 62.0
BASE_HEIGHT_MM = 0.44  # first layer 0.20 + three normal 0.08 mm layers
SWATCH_SIZE_MM = 10.0
SWATCH_GAP_MM = 2.0
SWATCH_LOW_MM = 2.0
SWATCH_HIGH_MM = 6.0
MODEL_HEIGHT_MM = BASE_HEIGHT_MM + SWATCH_HIGH_MM


@dataclass(frozen=True, slots=True)
class CalibrationChartMesh:
    vertices_mm: np.ndarray
    faces: np.ndarray
    face_part_ids: np.ndarray
    palette_indices: np.ndarray
    vertex_states: np.ndarray
    part_names: tuple[str, ...]
    part_keys: tuple[str, ...]
    part_face_counts: tuple[int, ...]
    part_vertex_counts: tuple[int, ...]
    part_state_indices: tuple[int, ...]
    state_count: int
    row_count: int
    base_depth_mm: float


@dataclass(frozen=True, slots=True)
class CalibrationBundleResult:
    folder: Path
    model_path: Path
    mapping_path: Path
    legend_path: Path
    guide_path: Path
    snapshot_path: Path
    validation_path: Path
    manifest_path: Path
    state_count: int
    target_label: str
    validation: Mapping[str, object]


def _copy_palette(palette: PaletteSettings) -> PaletteSettings:
    """Freeze mutable GUI settings before a background export starts."""

    return PaletteSettings(
        material=palette.material,
        palette_state_count=int(palette.palette_state_count),
        color_mode=palette.color_mode,
        physical_hex=list(palette.physical_hex),
        enabled_states=list(palette.enabled_states),
        mix_hex_overrides=list(palette.mix_hex_overrides),
        mix_ratios_b=list(palette.mix_ratios_b),
        secondary_mix_ratios_b=list(palette.secondary_mix_ratios_b),
        output_mix_ratios_b=(
            None
            if palette.output_mix_ratios_b is None
            else list(palette.output_mix_ratios_b)
        ),
        assignment_palette_hex=(
            None
            if palette.assignment_palette_hex is None
            else list(palette.assignment_palette_hex)
        ),
        black_free_gradient_enabled=bool(
            palette.black_free_gradient_enabled
        ),
        black_free_black_slot=int(palette.black_free_black_slot),
        black_free_red_slot=int(palette.black_free_red_slot),
        black_free_brown_slot=int(palette.black_free_brown_slot),
        surface_shell_enabled=bool(
            getattr(palette, "surface_shell_enabled", False)
        ),
        physical_filament_refs=list(palette.physical_filament_refs),
    )


def _smallest_cadence(effective_b: float) -> tuple[int, int]:
    if effective_b <= 0.0:
        return 1, 0
    if effective_b >= 1.0:
        return 0, 1
    for denominator in range(2, 65):
        layers_b = round(effective_b * denominator)
        if math.isclose(
            effective_b * denominator,
            layers_b,
            rel_tol=0.0,
            abs_tol=1.0e-10,
        ):
            return denominator - int(layers_b), int(layers_b)
    raise ValueError(f"cannot represent effective mix cadence: {effective_b}")


def _recipe_palette_hex(
    physical_hex: Sequence[str],
    mix_specs: Sequence[tuple[int, int, int]],
) -> list[str]:
    """Predict palette HEX values from one explicit set of A/B recipes."""

    physical = [mixer.hex_to_rgb8(value) for value in physical_hex]
    mixed = [
        mixer.mix_rgb8(
            physical[left],
            physical[right],
            mixer.orca_effective_mix_ratio(ratio_b / 100.0),
        )
        for left, right, ratio_b in mix_specs
    ]
    return [mixer.rgb8_to_hex(value) for value in physical + mixed]


def palette_calibration_rows(
    palette: PaletteSettings,
) -> list[dict[str, object]]:
    """Return stable recipe rows for every state in the selected palette.

    Disabled states are deliberately retained: a physical chart is the tool
    used to decide whether one of those states should be enabled later.
    """

    snapshot = _copy_palette(palette)
    state_count = mixer.coerce_palette_state_count(snapshot.palette_state_count)
    display_hex, _display_rgb = mixer.build_palette_rgb(
        snapshot.physical_hex,
        snapshot.mix_hex_overrides,
        snapshot.mix_ratios_b,
        snapshot.secondary_mix_ratios_b,
    )
    state_names = mixer.palette_state_names(
        snapshot.mix_ratios_b,
        snapshot.secondary_mix_ratios_b,
    )[:state_count]
    display_specs = mixer.palette_mix_specs(
        snapshot.mix_ratios_b,
        snapshot.secondary_mix_ratios_b,
    )[: state_count - 4]
    output_specs = mixer.print_palette_mix_specs(
        snapshot.mix_ratios_b,
        snapshot.secondary_mix_ratios_b,
        snapshot.output_mix_ratios_b,
    )[: state_count - 4]
    surface_shell_enabled = bool(snapshot.surface_shell_enabled)
    shell_specs = (
        engine.build_surface_shell_output_specs(
            snapshot.physical_hex,
            snapshot.mix_ratios_b,
            snapshot.secondary_mix_ratios_b,
            snapshot.output_mix_ratios_b,
        )[: state_count - 4]
        if surface_shell_enabled
        else ()
    )
    if [item[:2] for item in display_specs] != [item[:2] for item in output_specs]:
        raise AssertionError("display and output recipes must retain stable filament pairs")
    display_recipe_hex = _recipe_palette_hex(
        snapshot.physical_hex,
        display_specs,
    )
    output_recipe_hex = _recipe_palette_hex(
        snapshot.physical_hex,
        output_specs,
    )
    refs = list(snapshot.physical_filament_refs)
    rows: list[dict[str, object]] = []
    for state_index in range(state_count):
        common: dict[str, object] = {
            "state": state_index + 1,
            "name": state_names[state_index],
            "enabled_for_assignment": bool(snapshot.enabled_states[state_index]),
            "ui_display_hex": mixer.normalize_hex(display_hex[state_index]),
            "display_target_hex": mixer.normalize_hex(display_hex[state_index]),
            "display_recipe_predicted_hex": mixer.normalize_hex(
                display_recipe_hex[state_index]
            ),
            "print_ratio_predicted_hex": mixer.normalize_hex(
                output_recipe_hex[state_index]
            ),
            "output_ratio_predicted_hex": mixer.normalize_hex(
                output_recipe_hex[state_index]
            ),
            "surface_shell_enabled": surface_shell_enabled,
        }
        if state_index < 4:
            ref = refs[state_index]
            single_shares = [0.0] * 4
            single_shares[state_index] = 100.0
            rows.append(
                {
                    **common,
                    "filament_a": f"F{state_index + 1}",
                    "filament_b": "",
                    "filament_a_product": ref.label if ref is not None else "",
                    "filament_b_product": "",
                    "display_target_a_percent": 100.0,
                    "display_target_b_percent": 0.0,
                    "requested_output_a_percent": 100.0,
                    "requested_output_b_percent": 0.0,
                    "effective_orca_a_percent": 100.0,
                    "effective_orca_b_percent": 0.0,
                    "orca_cadence_a_layers": 1,
                    "orca_cadence_b_layers": 0,
                    "orca_cadence": "single",
                    "output_ratio_override_active": False,
                    "requested_a_percent": 100.0,
                    "requested_b_percent": 0.0,
                    "effective_a_percent": 100.0,
                    "effective_b_percent": 0.0,
                    "cadence_a_layers": 1,
                    "cadence_b_layers": 0,
                    "cadence": "single",
                    "output_architecture": "single-physical",
                    "surface_shell_applied": False,
                    "surface_shell_outer_filament": "",
                    "surface_shell_inner_pattern": "",
                    "surface_shell_manual_pattern": "",
                    "surface_shell_fallback_reason": "",
                    "physical_share_basis": "single-physical",
                    **{
                        f"output_total_f{slot + 1}_percent": single_shares[slot]
                        for slot in range(4)
                    },
                }
            )
            continue
        left, right, display_target_b = display_specs[state_index - 4]
        output_left, output_right, requested_output_b = output_specs[state_index - 4]
        if (left, right) != (output_left, output_right):
            raise AssertionError("output recipe changed a stable filament pair")
        effective_b = mixer.orca_effective_mix_ratio(
            float(requested_output_b) / 100.0
        )
        layers_a, layers_b = _smallest_cadence(effective_b)
        left_ref = refs[left]
        right_ref = refs[right]
        shell = shell_specs[state_index - 4] if shell_specs else None
        physical_shares = np.zeros(4, dtype=np.float64)
        if shell is not None and shell.applied:
            physical_shares[shell.outer_filament - 1] += 0.5
            inner_tokens = [int(value) for value in shell.inner_pattern or ""]
            for token in inner_tokens:
                physical_shares[token - 1] += 0.5 / len(inner_tokens)
            physical_share_basis = "two-equal-vertical-walls"
        else:
            physical_shares[left] = 1.0 - effective_b
            physical_shares[right] = effective_b
            physical_share_basis = "legacy-layer-cycle"
        rows.append(
            {
                **common,
                "filament_a": f"F{left + 1}",
                "filament_b": f"F{right + 1}",
                "filament_a_product": left_ref.label if left_ref is not None else "",
                "filament_b_product": right_ref.label if right_ref is not None else "",
                "display_target_a_percent": float(100 - int(display_target_b)),
                "display_target_b_percent": float(display_target_b),
                "requested_output_a_percent": float(
                    100 - int(requested_output_b)
                ),
                "requested_output_b_percent": float(requested_output_b),
                "effective_orca_a_percent": round(100.0 * (1.0 - effective_b), 3),
                "effective_orca_b_percent": round(100.0 * effective_b, 3),
                "orca_cadence_a_layers": layers_a,
                "orca_cadence_b_layers": layers_b,
                "orca_cadence": f"A{layers_a}:B{layers_b}",
                "output_ratio_override_active": int(display_target_b)
                != int(requested_output_b),
                # Compatibility aliases.  Since r16 these always describe the
                # requested/effective *output* recipe, never the display target.
                "requested_a_percent": float(100 - int(requested_output_b)),
                "requested_b_percent": float(requested_output_b),
                "effective_a_percent": round(100.0 * (1.0 - effective_b), 3),
                "effective_b_percent": round(100.0 * effective_b, 3),
                "cadence_a_layers": layers_a,
                "cadence_b_layers": layers_b,
                "cadence": f"A{layers_a}:B{layers_b}",
                "output_architecture": (
                    shell.architecture
                    if shell is not None and shell.applied
                    else "legacy-layer-cycle"
                ),
                "surface_shell_applied": bool(
                    shell is not None and shell.applied
                ),
                "surface_shell_outer_filament": (
                    ""
                    if shell is None or shell.outer_filament is None
                    else f"F{shell.outer_filament}"
                ),
                "surface_shell_inner_pattern": (
                    "" if shell is None else (shell.inner_pattern or "")
                ),
                "surface_shell_manual_pattern": (
                    "" if shell is None else (shell.manual_pattern or "")
                ),
                "surface_shell_fallback_reason": (
                    "" if shell is None else (shell.fallback_reason or "")
                ),
                "physical_share_basis": physical_share_basis,
                **{
                    f"output_total_f{slot + 1}_percent": round(
                        100.0 * float(physical_shares[slot]), 3
                    )
                    for slot in range(4)
                },
            }
        )
    return rows


def palette_family_display_rows(
    palette: PaletteSettings,
) -> list[dict[str, object]]:
    """Return calibration rows in the compact public presentation order.

    Canonical palette state IDs are a project/paint/3MF compatibility contract,
    so they must never be renumbered merely to make the UI easier to scan.  The
    public chart instead gets a separate sequential ``chart_number`` for mixed
    rows only.  Pair families come first, with each family's ratios ordered
    from filament A to filament B.  Physical rows follow and use their stable
    F1-F4 labels without consuming a public display number.

    Every returned row retains its original ``state`` value.  This explicit
    presentation mapping lets old projects keep exactly the same recipe while
    the on-screen strip, printed coupon positions, legend, and CSV read as
    smooth pair-family gradients.
    """

    canonical = palette_calibration_rows(palette)
    by_state_index = {
        int(row["state"]) - 1: row for row in canonical
    }
    display_state_indices = mixer.palette_family_display_state_indices(
        palette.palette_state_count,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    ordered = [by_state_index[index] for index in display_state_indices]
    mixed = [row for row in ordered if str(row["filament_b"])]
    physical = [row for row in ordered if not str(row["filament_b"])]
    presented: list[dict[str, object]] = []
    for chart_number, row in enumerate(mixed, start=1):
        pair = f'{row["filament_a"]}+{row["filament_b"]}'
        ratio = (
            f'{float(row["display_target_a_percent"]):g}/'
            f'{float(row["display_target_b_percent"]):g}%'
        )
        presented.append(
            {
                **row,
                "chart_number": chart_number,
                "display_label": f"{chart_number:02d}",
                "f_pair": pair,
                "fixed_ratio": ratio,
            }
        )
    for row in physical:
        filament = str(row["filament_a"])
        presented.append(
            {
                **row,
                "chart_number": None,
                "display_label": filament,
                "f_pair": filament,
                "fixed_ratio": "100%",
            }
        )
    return presented


def _palette_family_grid_positions(
    rows: Sequence[Mapping[str, object]],
) -> list[tuple[int, int]]:
    """Map presentation rows to the same family strips used on screen."""

    pair_rows = {
        f"F{left + 1}+F{right + 1}": index
        for index, (left, right) in enumerate(mixer.PAIR_INDICES)
    }
    next_column = [0] * GRID_ROWS
    positions: list[tuple[int, int]] = []
    for row in rows:
        chart_number = row.get("chart_number")
        if chart_number is None:
            grid_row = GRID_ROWS - 1
        else:
            try:
                grid_row = pair_rows[str(row["f_pair"])]
            except KeyError as exc:
                raise ValueError("unknown calibration-chart pair family") from exc
        grid_column = next_column[grid_row]
        if grid_column >= GRID_COLUMNS:
            raise ValueError("calibration-chart family exceeds grid width")
        positions.append((grid_row, grid_column))
        next_column[grid_row] += 1
    if len(positions) != len(rows) or any(
        next_column[index] == 0 for index in range(GRID_ROWS)
    ):
        raise ValueError("calibration-chart family grid is incomplete")
    return positions


def _append_mesh(
    vertices_out: list[np.ndarray],
    faces_out: list[np.ndarray],
    face_parts_out: list[np.ndarray],
    face_states_out: list[np.ndarray],
    vertex_states_out: list[np.ndarray],
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    part_id: int,
    state: int,
) -> tuple[int, int]:
    offset = sum(len(item) for item in vertices_out)
    vertices_out.append(np.asarray(vertices, dtype=np.float64))
    faces_out.append(np.asarray(faces, dtype=np.int32) + offset)
    face_parts_out.append(np.full(len(faces), part_id, dtype=np.int16))
    face_states_out.append(np.full(len(faces), state, dtype=np.int8))
    vertex_states_out.append(np.full(len(vertices), state, dtype=np.int8))
    return len(vertices), len(faces)


def _extruded_convex_polygon(
    outline_xy: Sequence[tuple[float, float]],
    z0: float,
    z1: float,
) -> tuple[np.ndarray, np.ndarray]:
    outline = np.asarray(outline_xy, dtype=np.float64)
    if outline.ndim != 2 or outline.shape[1] != 2 or len(outline) < 3:
        raise ValueError("calibration base outline is invalid")
    n = len(outline)
    vertices = np.column_stack(
        (
            np.vstack((outline, outline)),
            np.concatenate((np.full(n, z0), np.full(n, z1))),
        )
    )
    faces: list[tuple[int, int, int]] = []
    for index in range(1, n - 1):
        faces.append((0, index + 1, index))
        faces.append((n, n + index, n + index + 1))
    for index in range(n):
        following = (index + 1) % n
        faces.append((index, following, n + following))
        faces.append((index, n + following, n + index))
    return vertices, np.asarray(faces, dtype=np.int32)


def _wedge(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> tuple[np.ndarray, np.ndarray]:
    z0 = BASE_HEIGHT_MM
    low = BASE_HEIGHT_MM + SWATCH_LOW_MM
    high = BASE_HEIGHT_MM + SWATCH_HIGH_MM
    vertices = np.asarray(
        (
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y1, z0),
            (x0, y1, z0),
            (x0, y0, low),
            (x1, y0, low),
            (x1, y1, high),
            (x0, y1, high),
        ),
        dtype=np.float64,
    )
    faces = np.asarray(
        (
            (0, 2, 1),
            (0, 3, 2),
            (0, 1, 5),
            (0, 5, 4),
            (1, 2, 6),
            (1, 6, 5),
            (2, 3, 7),
            (2, 7, 6),
            (3, 0, 4),
            (3, 4, 7),
            (4, 5, 6),
            (4, 6, 7),
        ),
        dtype=np.int32,
    )
    return vertices, faces


def build_calibration_chart_mesh(
    palette: PaletteSettings,
) -> CalibrationChartMesh:
    snapshot = _copy_palette(palette)
    state_count = mixer.coerce_palette_state_count(snapshot.palette_state_count)
    row_count = GRID_ROWS
    pitch = SWATCH_SIZE_MM + SWATCH_GAP_MM
    # Two millimetres below the last coupon and six above the first one leave
    # room for the orientation chamfer without changing the regular grid.
    base_depth = float(
        row_count * SWATCH_SIZE_MM
        + max(0, row_count - 1) * SWATCH_GAP_MM
        + 8.0
    )
    half_depth = base_depth / 2.0

    vertices_out: list[np.ndarray] = []
    faces_out: list[np.ndarray] = []
    face_parts_out: list[np.ndarray] = []
    face_states_out: list[np.ndarray] = []
    vertex_states_out: list[np.ndarray] = []
    part_names: list[str] = []
    part_keys: list[str] = []
    part_face_counts: list[int] = []
    part_vertex_counts: list[int] = []
    part_state_indices: list[int] = []

    half_width = BASE_WIDTH_MM / 2.0
    base_outline = (
        (-half_width, -half_depth),
        (half_width, -half_depth),
        (half_width, half_depth),
        (-half_width + 4.0, half_depth),
        (-half_width, half_depth - 4.0),
    )
    base_vertices, base_faces = _extruded_convex_polygon(
        base_outline, 0.0, BASE_HEIGHT_MM
    )
    vertices, faces = _append_mesh(
        vertices_out,
        faces_out,
        face_parts_out,
        face_states_out,
        vertex_states_out,
        base_vertices,
        base_faces,
        part_id=0,
        state=BASE_STATE,
    )
    part_names.append("BASE_F2_orientation_chamfer_NW")
    part_keys.append("calibration-base-f2")
    part_vertex_counts.append(vertices)
    part_face_counts.append(faces)
    part_state_indices.append(BASE_STATE)

    display_rows = palette_family_display_rows(snapshot)
    display_positions = _palette_family_grid_positions(display_rows)
    top_center_y = half_depth - 6.0 - SWATCH_SIZE_MM / 2.0
    left_center_x = -BASE_WIDTH_MM / 2.0 + 2.0 + SWATCH_SIZE_MM / 2.0
    for display_position, (row, grid_position) in enumerate(
        zip(display_rows, display_positions, strict=True)
    ):
        # The chart object list, XY grid, legend, CSV and guide all use this
        # same presentation row.  The paint code still stores the unchanged
        # canonical palette state ID carried by ``row["state"]``.
        state_index = int(row["state"]) - 1
        grid_row, grid_column = grid_position
        center_x = left_center_x + pitch * grid_column
        center_y = top_center_y - pitch * grid_row
        half = SWATCH_SIZE_MM / 2.0
        swatch_vertices, swatch_faces = _wedge(
            center_x - half,
            center_x + half,
            center_y - half,
            center_y + half,
        )
        part_id = display_position + 1
        vertices, faces = _append_mesh(
            vertices_out,
            faces_out,
            face_parts_out,
            face_states_out,
            vertex_states_out,
            swatch_vertices,
            swatch_faces,
            part_id=part_id,
            state=state_index,
        )
        safe_name = str(row["name"]).replace("+", "_").replace("%", "pct")
        chart_number = row["chart_number"]
        chart_label = (
            str(row["display_label"])
            if chart_number is not None
            else str(row["filament_a"])
        )
        part_names.append(
            f"{chart_label}_{safe_name}__S{state_index + 1:02d}"
        )
        part_keys.append(f"calibration-state-{state_index + 1:02d}")
        part_vertex_counts.append(vertices)
        part_face_counts.append(faces)
        part_state_indices.append(state_index)

    return CalibrationChartMesh(
        vertices_mm=np.vstack(vertices_out),
        faces=np.vstack(faces_out),
        face_part_ids=np.concatenate(face_parts_out),
        palette_indices=np.concatenate(face_states_out),
        vertex_states=np.concatenate(vertex_states_out),
        part_names=tuple(part_names),
        part_keys=tuple(part_keys),
        part_face_counts=tuple(part_face_counts),
        part_vertex_counts=tuple(part_vertex_counts),
        part_state_indices=tuple(part_state_indices),
        state_count=state_count,
        row_count=row_count,
        base_depth_mm=base_depth,
    )


def _prepared_chart(
    chart: CalibrationChartMesh,
    palette: PaletteSettings,
) -> tuple[PreparedGeometry, ColorResult]:
    display_rows = palette_family_display_rows(palette)
    _hex, palette_rgb = mixer.build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    palette_rgb = np.asarray(palette_rgb[: chart.state_count], dtype=np.float64)
    vertices_unit = chart.vertices_mm / MODEL_HEIGHT_MM
    vertex_colors = palette_rgb[chart.vertex_states]
    areas_unit = engine.triangle_areas(vertices_unit, chart.faces)
    level = MeshLevel(
        vertices_unit=vertices_unit,
        faces=chart.faces,
        vertex_colors=vertex_colors,
        areas_unit=areas_unit,
        neighbors=engine.face_neighbors(chart.faces, len(vertices_unit)),
        face_part_ids=chart.face_part_ids,
        part_names=chart.part_names,
        part_keys=chart.part_keys,
        face_provenance=np.zeros(len(chart.faces), dtype=np.uint8),
    )
    source_hash = hashlib.sha256(
        chart.vertices_mm.tobytes() + chart.faces.tobytes()
    ).hexdigest()
    source = ObjAsset(
        path=Path("purpose_built_palette_calibration.obj"),
        sha256=source_hash,
        file_size=0,
        vertices=vertices_unit.copy(),
        colors=vertex_colors.copy(),
        faces=chart.faces.copy(),
        original_vertex_count=len(chart.vertices_mm),
        original_face_count=len(chart.faces),
        warnings=[],
        part_names=chart.part_names,
        part_keys=chart.part_keys,
        face_part_ids=chart.face_part_ids.copy(),
        part_face_counts=chart.part_face_counts,
        part_vertex_counts=chart.part_vertex_counts,
        part_marker_kind="calibration",
        has_explicit_parts=True,
    )
    area = float(areas_unit.sum())
    volume = float(engine.signed_volume(vertices_unit, chart.faces))
    prepared = PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(chart.vertices_mm),
        clean_face_count=len(chart.faces),
        removed_vertices=0,
        removed_faces=0,
        topology={
            "watertight": True,
            "part_count": len(chart.part_names),
            "purpose_built_calibration": True,
        },
        source_area_unit=area,
        source_volume_unit=volume,
        simplified_area_unit=area,
        simplified_volume_unit=volume,
        source_dimensions_unit=np.ptp(vertices_unit, axis=0),
        warnings=[],
        part_names=chart.part_names,
        part_keys=chart.part_keys,
        part_stats=[
            {
                "part_id": part_id,
                "part_key": chart.part_keys[part_id],
                "part_name": chart.part_names[part_id],
                "vertices": chart.part_vertex_counts[part_id],
                "faces": chart.part_face_counts[part_id],
            }
            for part_id in range(len(chart.part_names))
        ],
        assembly={
            "solidify_parts": True,
            "all_parts_watertight": True,
            "repair_method": "purpose_built_watertight_calibration_primitives",
            "calibration_chart": {
                "schema": CALIBRATION_SCHEMA,
                "state_count": chart.state_count,
                "grid_columns": GRID_COLUMNS,
                "grid_rows": chart.row_count,
                "screen_order": "left-to-right, top-to-bottom",
                "screen_state_ids": [
                    int(row["state"]) for row in display_rows
                ],
                "chart_object_state_ids": [
                    int(value) + 1
                    for value in chart.part_state_indices[1:]
                ],
                "screen_chart_numbers": [
                    (
                        None
                        if row["chart_number"] is None
                        else int(row["chart_number"])
                    )
                    for row in display_rows
                ],
                "screen_display_labels": [
                    str(row["display_label"]) for row in display_rows
                ],
                "canonical_state_ids_unchanged": True,
                "orientation_marker": "north-west base corner chamfer",
                "base_state": BASE_STATE + 1,
                "base_height_mm": BASE_HEIGHT_MM,
                "swatch_size_mm": SWATCH_SIZE_MM,
                "swatch_low_height_above_base_mm": SWATCH_LOW_MM,
                "swatch_high_height_above_base_mm": SWATCH_HIGH_MM,
                "adaptive_paint": False,
                "all_swatch_faces_uniform": True,
            },
        },
    )
    # Keep the tree store explicitly empty.  The normal exporter recognizes
    # the calibration metadata above and bypasses adaptive shading entirely;
    # do not also mark every chart face as a manual edit because that would
    # hide a regression in the dedicated calibration bypass.
    prepared._hotfix_subtriangle_paint = {}

    face_rgb = palette_rgb[chart.palette_indices]
    areas_mm2 = areas_unit * MODEL_HEIGHT_MM**2
    counts = np.bincount(chart.palette_indices, minlength=chart.state_count)
    by_area = np.bincount(
        chart.palette_indices,
        weights=areas_mm2,
        minlength=chart.state_count,
    )
    fractions = by_area / max(float(by_area.sum()), 1.0e-12)
    colors = ColorResult(
        tone_vertex_rgb=vertex_colors,
        source_face_rgb=face_rgb.copy(),
        palette_indices=chart.palette_indices.copy(),
        target_face_rgb=face_rgb.copy(),
        delta_e=np.zeros(len(chart.faces), dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=0.0,
        manual_override_faces=0,
        part_metrics=[],
    )
    return prepared, colors


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _inspect_3mf(
    path: Path,
    chart: CalibrationChartMesh,
    palette: PaletteSettings,
    writer_validation: Mapping[str, object],
) -> dict[str, object]:
    display_rows = palette_family_display_rows(palette)
    expected_screen_state_ids = [
        int(row["state"]) for row in display_rows
    ]
    code_to_state = {
        code.upper(): index for index, code in enumerate(engine.PAINT_CODES)
    }
    expected_hex, _rgb = mixer.build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    expected_hex = [
        mixer.normalize_hex(value) for value in expected_hex[: chart.state_count]
    ]
    expected_names = list(
        mixer.palette_state_names(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )[: chart.state_count]
    )
    expected_definitions = engine.make_portable_mixed_definitions(
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
        chart.state_count,
        palette.output_mix_ratios_b,
        palette.surface_shell_enabled,
        palette.physical_hex,
    )
    expected_shell_specs = (
        engine.build_surface_shell_output_specs(
            palette.physical_hex,
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            palette.output_mix_ratios_b,
        )[: chart.state_count - 4]
        if palette.surface_shell_enabled
        else ()
    )
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        object_root = ET.fromstring(archive.read("3D/Objects/object_1.model"))
        root_model = ET.fromstring(archive.read("3D/3dmodel.model"))
        palette_meta = json.loads(
            archive.read("Metadata/full_spectrum_palette.json").decode("utf-8")
        )
        assembly_meta = json.loads(
            archive.read("Metadata/tripo_assembly.json").decode("utf-8")
        )
        project = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )

    base_material_id = -1
    base_rows: list[dict[str, str]] = []
    for element in object_root.iter():
        if _local_name(element.tag) == "basematerials":
            base_material_id = int(element.attrib.get("id", "-1"))
            base_rows = [
                {
                    "name": child.attrib.get("name", ""),
                    "displaycolor": child.attrib.get("displaycolor", "").upper(),
                }
                for child in element
                if _local_name(child.tag) == "base"
            ]

    objects = [
        element
        for element in object_root.iter()
        if _local_name(element.tag) == "object"
    ]
    per_object: list[dict[str, object]] = []
    all_states: list[int] = []
    all_p1: list[int] = []
    all_pid: list[int] = []
    non_leaf_codes: list[str] = []
    p2_or_p3 = False
    for object_index, obj in enumerate(objects):
        triangles = [
            item for item in obj.iter() if _local_name(item.tag) == "triangle"
        ]
        states: list[int] = []
        for triangle in triangles:
            code = triangle.attrib.get("paint_color", "").upper()
            if code not in code_to_state:
                non_leaf_codes.append(code)
                continue
            states.append(code_to_state[code])
            all_p1.append(int(triangle.attrib.get("p1", "-1")))
            all_pid.append(int(triangle.attrib.get("pid", "-1")))
            p2_or_p3 = p2_or_p3 or "p2" in triangle.attrib or "p3" in triangle.attrib
        expected_state = int(chart.part_state_indices[object_index])
        display_row = None if object_index == 0 else display_rows[object_index - 1]
        per_object.append(
            {
                "object_index": object_index,
                "screen_position": (
                    None if display_row is None else object_index
                ),
                "chart_number": (
                    None if display_row is None else display_row["chart_number"]
                ),
                "display_label": (
                    "BASE" if display_row is None else display_row["display_label"]
                ),
                "name": obj.attrib.get("name", ""),
                "faces": len(triangles),
                "expected_state": expected_state + 1,
                "states": sorted({state + 1 for state in states}),
                "uniform_expected_state": len(states) == len(triangles)
                and set(states) == {expected_state},
                "expected_faces": int(chart.part_face_counts[object_index]),
                "face_count_exact": len(triangles)
                == int(chart.part_face_counts[object_index]),
            }
        )
        all_states.extend(states)

    metadata_states = palette_meta.get("states", [])
    component_ids = [
        int(element.attrib["objectid"])
        for element in root_model.iter()
        if _local_name(element.tag) == "component"
    ]
    parent_id = len(chart.part_names) + 1
    build_ids = [
        int(element.attrib["objectid"])
        for element in root_model.iter()
        if _local_name(element.tag) == "item"
    ]
    swatch_states = [
        item["states"][0]
        for item in per_object[1:]
        if bool(item["uniform_expected_state"]) and len(item["states"]) == 1
    ]
    calibration_metadata = assembly_meta.get("calibration_chart", {})
    expected_filament_refs = [
        asdict(ref) if ref is not None else None
        for ref in palette.physical_filament_refs
    ]
    adaptive_details = writer_validation.get("r8_export_adaptive", {})
    adaptive_bypass_exact = bool(
        isinstance(adaptive_details, Mapping)
        and adaptive_details.get("status") == "disabled_calibration"
        and int(adaptive_details.get("automatic_tree_faces", -1)) == 0
        and int(adaptive_details.get("merged_tree_faces", -1)) == 0
        and int(adaptive_details.get("adaptive_faces", -1)) == 0
    )
    shell_metadata = palette_meta.get("surface_shell")
    shell_project_keys = {
        "wall_loops": "2",
        "wall_generator": "classic",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.42",
    }
    if palette.surface_shell_enabled:
        shell_recipes = (
            shell_metadata.get("recipes", [])
            if isinstance(shell_metadata, Mapping)
            else []
        )
        surface_shell_exact = bool(
            isinstance(shell_metadata, Mapping)
            and shell_metadata.get("schema")
            == "tripo-spectrum-mapper.surface-shell.v2"
            and shell_metadata.get("enabled") is True
            and shell_metadata.get("policy") == "dark-mixes-only"
            and int(shell_metadata.get("applied_rows", -1))
            == sum(spec.applied for spec in expected_shell_specs)
            and int(shell_metadata.get("eligible_rows", -1))
            == sum(spec.disposition == "eligible" for spec in expected_shell_specs)
            and int(shell_metadata.get("passthrough_rows", -1))
            == sum(spec.disposition == "passthrough" for spec in expected_shell_specs)
            and int(shell_metadata.get("fallback_rows", -1))
            == sum(spec.disposition == "fallback" for spec in expected_shell_specs)
            and [item.get("manual_pattern") for item in shell_recipes]
            == [spec.manual_pattern for spec in expected_shell_specs]
            and all(project.get(key) == value for key, value in shell_project_keys.items())
        )
    else:
        surface_shell_exact = shell_metadata is None and all(
            key not in project for key in shell_project_keys
        )
    report: dict[str, object] = {
        "schema": VALIDATION_SCHEMA,
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": engine.sha256_file(path),
        "zip_crc_ok": bad_member is None,
        "object_count": len(objects),
        "expected_object_count": len(chart.part_names),
        "all_objects_uniform": all(
            bool(item["uniform_expected_state"]) for item in per_object
        ),
        "all_swatch_objects_uniform": all(
            bool(item["uniform_expected_state"]) for item in per_object[1:]
        ),
        "part_face_counts_exact": all(
            bool(item["face_count_exact"]) for item in per_object
        ),
        "part_names_exact": [str(item["name"]) for item in per_object]
        == list(chart.part_names),
        "swatch_states_exact": swatch_states
        == expected_screen_state_ids,
        "chart_object_order_exact": [
            int(value) + 1 for value in chart.part_state_indices[1:]
        ]
        == expected_screen_state_ids,
        "paint_colors_are_leaf_codes": not non_leaf_codes,
        "unknown_or_adaptive_paint_codes": sorted(set(non_leaf_codes)),
        "portable_p1_matches_paint_color": all_p1 == all_states,
        "portable_pid_matches_basematerials": bool(all_pid)
        and set(all_pid) == {base_material_id},
        "p2_p3_absent": not p2_or_p3,
        "portable_basematerials_exact": [
            row["displaycolor"][:7] for row in base_rows
        ]
        == [value.upper() for value in expected_hex],
        "portable_basematerial_names_exact": [row["name"] for row in base_rows]
        == expected_names,
        "palette_state_count": palette_meta.get("palette_state_count"),
        "palette_state_names_exact": [item.get("name") for item in metadata_states]
        == expected_names,
        "palette_state_hex_exact": [
            str(item.get("display_rgb", "")).upper() for item in metadata_states
        ]
        == [value.upper() for value in expected_hex],
        "physical_slot_order": palette_meta.get("physical_slot_order"),
        "physical_filament_refs": palette_meta.get("physical_filament_refs"),
        "physical_filament_refs_exact": palette_meta.get(
            "physical_filament_refs"
        )
        == expected_filament_refs,
        "enabled_states_exact": [
            bool(item.get("enabled_for_assignment")) for item in metadata_states
        ]
        == [
            bool(value)
            for value in palette.enabled_states[: chart.state_count]
        ],
        "mix_ratios_b_percent": palette_meta.get("mix_ratios_b_percent"),
        "secondary_mix_ratios_b_percent": palette_meta.get(
            "secondary_mix_ratios_b_percent"
        ),
        "output_mix_ratios_b_percent": palette_meta.get(
            "output_mix_ratios_b_percent"
        ),
        "print_mix_specs": palette_meta.get("print_mix_specs"),
        "mixed_definitions_exact": project.get("mixed_filament_definitions")
        == expected_definitions,
        "surface_shell_enabled": bool(palette.surface_shell_enabled),
        "surface_shell_metadata": shell_metadata,
        "surface_shell_exact": surface_shell_exact,
        "surface_shell_applied_rows": (
            0
            if not isinstance(shell_metadata, Mapping)
            else int(shell_metadata.get("applied_rows", 0))
        ),
        "surface_shell_passthrough_rows": (
            0
            if not isinstance(shell_metadata, Mapping)
            else int(shell_metadata.get("passthrough_rows", 0))
        ),
        "surface_shell_fallback_rows": (
            0
            if not isinstance(shell_metadata, Mapping)
            else int(shell_metadata.get("fallback_rows", 0))
        ),
        "component_object_ids_exact": component_ids
        == list(range(1, len(chart.part_names) + 1)),
        "build_parent_object_exact": build_ids == [parent_id],
        "layer_height_mm": project.get("layer_height"),
        "initial_layer_height_mm": project.get("initial_layer_print_height"),
        "dimensions_mm": np.ptp(chart.vertices_mm, axis=0).round(6).tolist(),
        "calibration_metadata": calibration_metadata,
        "calibration_metadata_exact": bool(
            isinstance(calibration_metadata, Mapping)
            and calibration_metadata.get("schema") == CALIBRATION_SCHEMA
            and calibration_metadata.get("state_count") == chart.state_count
            and calibration_metadata.get("grid_columns") == GRID_COLUMNS
            and calibration_metadata.get("grid_rows") == chart.row_count
            and calibration_metadata.get("screen_state_ids")
            == expected_screen_state_ids
            and calibration_metadata.get("chart_object_state_ids")
            == expected_screen_state_ids
            and calibration_metadata.get("screen_chart_numbers")
            == [
                row["chart_number"]
                for row in display_rows
            ]
            and calibration_metadata.get("screen_display_labels")
            == [
                str(row["display_label"])
                for row in display_rows
            ]
            and calibration_metadata.get("canonical_state_ids_unchanged")
            is True
            and calibration_metadata.get("adaptive_paint") is False
            and calibration_metadata.get("all_swatch_faces_uniform") is True
        ),
        "adaptive_bypass_exact": adaptive_bypass_exact,
        "per_object": per_object,
        "writer_validation": dict(writer_validation),
    }
    writer_valid = (
        bool(writer_validation.get("zip_crc_ok"))
        and int(writer_validation.get("validated_solid_parts", 0))
        == len(chart.part_names)
        and int(writer_validation.get("adaptive_paint_faces", 0) or 0) == 0
        and adaptive_bypass_exact
    )
    required = (
        "zip_crc_ok",
        "all_objects_uniform",
        "all_swatch_objects_uniform",
        "part_face_counts_exact",
        "part_names_exact",
        "swatch_states_exact",
        "chart_object_order_exact",
        "paint_colors_are_leaf_codes",
        "portable_p1_matches_paint_color",
        "portable_pid_matches_basematerials",
        "p2_p3_absent",
        "portable_basematerials_exact",
        "portable_basematerial_names_exact",
        "palette_state_names_exact",
        "palette_state_hex_exact",
        "physical_filament_refs_exact",
        "enabled_states_exact",
        "mixed_definitions_exact",
        "surface_shell_exact",
        "component_object_ids_exact",
        "build_parent_object_exact",
        "calibration_metadata_exact",
        "adaptive_bypass_exact",
    )
    report["valid"] = (
        writer_valid
        and all(bool(report[name]) for name in required)
        and report["object_count"] == len(chart.part_names)
        and report["palette_state_count"] == chart.state_count
        and report["physical_slot_order"]
        == [mixer.normalize_hex(value) for value in palette.physical_hex]
        and report["mix_ratios_b_percent"]
        == [int(value) for value in palette.mix_ratios_b]
        and report["secondary_mix_ratios_b_percent"]
        == [int(value) for value in palette.secondary_mix_ratios_b]
        and report["output_mix_ratios_b_percent"]
        == (
            None
            if palette.output_mix_ratios_b is None
            else [int(value) for value in palette.output_mix_ratios_b]
        )
        and report["print_mix_specs"]
        == (
            None
            if palette.output_mix_ratios_b is None
            else [
                {
                    "physical_a": int(left + 1),
                    "physical_b": int(right + 1),
                    "ratio_b_percent": int(ratio_b),
                }
                for left, right, ratio_b in mixer.print_palette_mix_specs(
                    palette.mix_ratios_b,
                    palette.secondary_mix_ratios_b,
                    palette.output_mix_ratios_b,
                )[: chart.state_count - 4]
            ]
        )
        and str(report["layer_height_mm"]) == "0.08"
        and str(report["initial_layer_height_mm"]) == "0.2"
        and report["dimensions_mm"]
        == [BASE_WIDTH_MM, chart.base_depth_mm, MODEL_HEIGHT_MM]
    )
    return report


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        Path(
            "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
            if bold
            else "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
        ),
        Path("/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("C:/Windows/Fonts/meiryob.ttc")
        if bold
        else Path("C:/Windows/Fonts/meiryo.ttc"),
        Path("C:/Windows/Fonts/YuGothB.ttc")
        if bold
        else Path("C:/Windows/Fonts/YuGothR.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf")
        if bold
        else Path("C:/Windows/Fonts/arial.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _text_color(hex_value: str) -> tuple[int, int, int]:
    normalized = mixer.normalize_hex(hex_value)
    rgb = np.asarray(
        [int(normalized[index : index + 2], 16) for index in (1, 3, 5)],
        dtype=np.float64,
    )
    luminance = float(np.dot(rgb, (0.2126, 0.7152, 0.0722)))
    return (16, 16, 16) if luminance >= 145.0 else (255, 255, 255)


def _write_legend(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    palette: PaletteSettings,
    *,
    language: str,
) -> None:
    positions = _palette_family_grid_positions(rows)
    row_count = GRID_ROWS
    top = 222
    cell_height = 248
    gap_y = 16
    title_font = _font(42, bold=True)
    subtitle_font = _font(23)
    number_font = _font(34, bold=True)
    recipe_font = _font(20, bold=True)
    detail_font = _font(17)
    if language == "en":
        title = f"Current {len(rows)}-State Physical Calibration Chart"
        orientation = "Align the north-west chamfer; read left to right, top to bottom."
        prediction_note = "HEX colors are predictions, not physical measurements."
        mapping_note = "Display No. / F pair / fixed ratio (physical colors use F1-F4 labels)."
    else:
        title = f"現行{len(rows)}色 実機カラーチャート対応表"
        orientation = "北西（左上）の切欠きを合わせ、左→右・上→下に読みます。"
        prediction_note = "表示HEXは予測値で、実測値ではありません。"
        mapping_note = "表示番号 / Fペア / 固定比率（物理4色はF1～F4表記）"

    # Size the four columns from the actual localized strings.  Fixed-width
    # cards clipped long effective-ratio/status lines in the first prototype,
    # making adjacent states look merged in the saved legend.
    def detail_lines(row: Mapping[str, object]) -> tuple[str, str, str, str]:
        enabled = bool(row["enabled_for_assignment"])
        if row["filament_b"]:
            if language == "en":
                display_target = (
                    f'Display target A/B {float(row["display_target_a_percent"]):g}/'
                    f'{float(row["display_target_b_percent"]):g}%'
                )
                requested_output = (
                    f'Output request A/B {float(row["requested_output_a_percent"]):g}/'
                    f'{float(row["requested_output_b_percent"]):g}%'
                )
                effective_output = (
                    f'Orca effective A/B {float(row["effective_orca_a_percent"]):g}/'
                    f'{float(row["effective_orca_b_percent"]):g}%  '
                    f'{row["orca_cadence"]}'
                )
            else:
                display_target = (
                    f'表示目標 A/B={float(row["display_target_a_percent"]):g}/'
                    f'{float(row["display_target_b_percent"]):g}%'
                )
                requested_output = (
                    f'出力指定 A/B={float(row["requested_output_a_percent"]):g}/'
                    f'{float(row["requested_output_b_percent"]):g}%'
                )
                effective_output = (
                    f'Orca実効 A/B={float(row["effective_orca_a_percent"]):g}/'
                    f'{float(row["effective_orca_b_percent"]):g}%  '
                    f'{row["orca_cadence"]}'
                )
            if bool(row.get("surface_shell_applied")):
                pattern = str(row.get("surface_shell_manual_pattern", ""))
                if len(pattern) > 24:
                    pattern = pattern[:21] + "..."
                effective_output = (
                    f"Surface Cycle {pattern}"
                    if language == "en"
                    else f"表面Cycle {pattern}"
                )
            elif bool(row.get("surface_shell_enabled")):
                reason = str(row.get("surface_shell_fallback_reason", ""))
                effective_output = (
                    f"Legacy fallback: {reason}"
                    if language == "en"
                    else f"従来recipeへfallback: {reason}"
                )
        else:
            display_target = (
                "Single physical filament"
                if language == "en"
                else "物理フィラメント単色"
            )
            requested_output = (
                f'Material: {row["filament_a"]}'
                if language == "en"
                else f'材料: {row["filament_a"]}'
            )
            effective_output = (
                "Output recipe unchanged"
                if language == "en"
                else "出力recipe変更なし"
            )
        if language == "en":
            status = f'Automatic assignment: {"enabled" if enabled else "disabled"}'
        else:
            status = f'自動割当: {"有効" if enabled else "無効"}'
        return display_target, requested_output, effective_output, status

    measuring_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    text_widths: list[int] = []
    for row in rows:
        text_widths.append(
            measuring_draw.textbbox(
                (0, 0),
                f'{row["f_pair"]}  {row["fixed_ratio"]}',
                font=recipe_font,
            )[2]
        )
        text_widths.extend(
            measuring_draw.textbbox((0, 0), line, font=detail_font)[2]
            for line in detail_lines(row)
        )
    margin_x = 42
    gap_x = 18
    cell_width = max(290, max(text_widths, default=0) + 30)
    width = max(
        1300,
        2 * margin_x
        + GRID_COLUMNS * cell_width
        + (GRID_COLUMNS - 1) * gap_x,
    )
    height = top + row_count * cell_height + max(0, row_count - 1) * gap_y + 50
    image = Image.new("RGB", (width, height), "#F4F2ED")
    draw = ImageDraw.Draw(image)
    draw.text((52, 34), title, fill="#1C1C1C", font=title_font)
    draw.text((52, 94), orientation, fill="#3F3F3F", font=subtitle_font)
    draw.text((52, 126), prediction_note, fill="#3F3F3F", font=subtitle_font)
    physical_line = "    ".join(
        f"F{index + 1} {mixer.normalize_hex(value)}"
        for index, value in enumerate(palette.physical_hex)
    )
    draw.text((52, 156), mapping_note, fill="#3F3F3F", font=subtitle_font)
    draw.text((52, 188), physical_line, fill="#3F3F3F", font=subtitle_font)

    for row, (grid_row, grid_column) in zip(rows, positions, strict=True):
        x0 = margin_x + grid_column * (cell_width + gap_x)
        y0 = top + grid_row * (cell_height + gap_y)
        x1, y1 = x0 + cell_width, y0 + cell_height
        display = str(row["ui_display_hex"])
        enabled = bool(row["enabled_for_assignment"])
        border = "#C8C4BC" if enabled else "#9D7B58"
        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=14,
            fill="#FFFFFF",
            outline=border,
            width=3 if not enabled else 2,
        )
        draw.rounded_rectangle(
            (x0 + 8, y0 + 8, x1 - 8, y0 + 76),
            radius=10,
            fill=display,
        )
        foreground = _text_color(display)
        draw.text(
            (x0 + 20, y0 + 18),
            str(row["display_label"]),
            fill=foreground,
            font=number_font,
        )
        draw.text(
            (x1 - 20, y0 + 31),
            display,
            fill=foreground,
            font=detail_font,
            anchor="ra",
        )
        draw.text(
            (x0 + 14, y0 + 86),
            f'{row["f_pair"]}  {row["fixed_ratio"]}',
            fill="#171717",
            font=recipe_font,
        )
        display_target, requested_output, effective_output, status = detail_lines(row)
        draw.text((x0 + 14, y0 + 119), display_target, fill="#474747", font=detail_font)
        draw.text(
            (x0 + 14, y0 + 147), requested_output,
            fill="#474747",
            font=detail_font,
        )
        draw.text(
            (x0 + 14, y0 + 175), effective_output,
            fill="#474747",
            font=detail_font,
        )
        draw.text(
            (x0 + 14, y0 + 203), status,
            fill="#474747",
            font=detail_font,
        )
    image.save(path, format="PNG", optimize=True)


def _write_mapping_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> None:
    fields = (
        "chart_number",
        "display_label",
        "f_pair",
        "fixed_ratio",
        "state",
        "name",
        "enabled_for_assignment",
        "filament_a",
        "filament_b",
        "filament_a_product",
        "filament_b_product",
        "display_target_a_percent",
        "display_target_b_percent",
        "display_target_hex",
        "display_recipe_predicted_hex",
        "requested_output_a_percent",
        "requested_output_b_percent",
        "output_ratio_predicted_hex",
        "effective_orca_a_percent",
        "effective_orca_b_percent",
        "orca_cadence_a_layers",
        "orca_cadence_b_layers",
        "orca_cadence",
        "output_architecture",
        "surface_shell_enabled",
        "surface_shell_applied",
        "surface_shell_outer_filament",
        "surface_shell_inner_pattern",
        "surface_shell_manual_pattern",
        "surface_shell_fallback_reason",
        "physical_share_basis",
        "output_total_f1_percent",
        "output_total_f2_percent",
        "output_total_f3_percent",
        "output_total_f4_percent",
        "output_ratio_override_active",
        "requested_a_percent",
        "requested_b_percent",
        "effective_a_percent",
        "effective_b_percent",
        "cadence_a_layers",
        "cadence_b_layers",
        "cadence",
        "ui_display_hex",
        "print_ratio_predicted_hex",
        "measured_slope_hex",
        "measured_slope_L",
        "measured_slope_a",
        "measured_slope_b",
        "side_appearance_notes",
        "notes",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **dict(row),
                    "measured_slope_hex": "",
                    "measured_slope_L": "",
                    "measured_slope_a": "",
                    "measured_slope_b": "",
                    "side_appearance_notes": "",
                    "notes": "",
                }
            )


def _filament_lines(palette: PaletteSettings) -> list[str]:
    result: list[str] = []
    for index, (color, ref) in enumerate(
        zip(palette.physical_hex, palette.physical_filament_refs, strict=True)
    ):
        identity = ref.label if ref is not None else "unassigned"
        result.append(f"F{index + 1}: {mixer.normalize_hex(color)} / {identity}")
    return result


def _write_guide(
    path: Path,
    model_name: str,
    palette: PaletteSettings,
    rows: Sequence[Mapping[str, object]],
    *,
    language: str,
    target_label: str,
) -> None:
    material = normalize_filament_material(palette.material)
    filament_profile = generic_filament_profile(material)
    colors = "\n".join(f"- {line}" for line in _filament_lines(palette))
    override_warning = any(value is not None for value in palette.mix_hex_overrides)
    output_override = palette.output_mix_ratios_b is not None
    surface_shell = bool(getattr(palette, "surface_shell_enabled", False))
    shell_specs = (
        engine.build_surface_shell_output_specs(
            palette.physical_hex,
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            palette.output_mix_ratios_b,
        )[: len(rows) - 4]
        if surface_shell
        else ()
    )
    shell_applied = sum(spec.applied for spec in shell_specs)
    shell_passthrough = sum(
        spec.disposition == "passthrough" for spec in shell_specs
    )
    shell_fallback = sum(spec.disposition == "fallback" for spec in shell_specs)
    if language == "en":
        material_note = {
            "ABS": (
                "\n- **ABS beta:** The registered/measured ABS gamut is smaller than PLA. "
                "Missing target colours are approximated using ABS only; PLA/PETG is never "
                "used as fallback. Use this physical chart to verify the result. A Top Cover "
                "is required for ABS printing on Snapmaker U1."
            ),
            "PETG": (
                "\n- **PETG beta:** Colour prediction is not yet physically calibrated for "
                "every spool and lot. Use this physical chart before a production print; "
                "PLA/ABS is never used as fallback."
            ),
        }.get(material, "")
        warning = (
            "\n- One or more primary mixed-state display HEX overrides are present. "
            "Orca prints layer ratios, not arbitrary display colors; compare the "
            "`print_ratio_predicted_hex` and measured columns in the CSV."
            if override_warning
            else ""
        )
        output_note = (
            "\n- An output-only ratio profile is active. The app preview, target "
            "colours, state IDs, and assignments stay unchanged, while this 3MF "
            "uses the requested output ratios and Orca layer cadences recorded in "
            "the legend/CSV. The single-filament state for whichever F1-F4 slot "
            "is selected as black remains unchanged. "
            "Orca's own preview may therefore look different from the app preview. "
            "Treat this profile as printer, spool/lot, filament-profile, and print-"
            "condition specific."
            if output_override
            else ""
        )
        shell_note = (
            "\n- Two-wall surface-shell output is active. This project fixes "
            "Classic walls to exactly two equal 0.42 mm perimeters. Representable mixed "
            "Only black-containing states use a fixed partner-colour outer "
            "wall and a darkest/partner inner Cycle (the recommended "
            "F1-black order produces the 2,12 / 3,13 / 4,14 family). Keep "
            "the wall generator, wall count, and both wall widths "
            "unchanged when comparing this chart with a production model. "
            f"This chart applies Cycle to {shell_applied} rows, intentionally "
            f"passes {shell_passthrough} non-black rows through unchanged, "
            f"and has {shell_fallback} safety-fallback rows. Black "
            "correction is recommended. "
            "The target mix is nominal for the two vertical walls; top/bottom "
            "surfaces, infill, supports, purge paths, and optical filament "
            "behaviour remain slicer/printer dependent."
            if surface_shell
            else ""
        )
        text = f"""# Full Spectrum Physical Palette Calibration

Model: `{model_name}`  
Palette target: `{target_label}`  
States: {len(rows)}

This bundle is a fixed snapshot of the selected palette. Display target colours are predictions, not measurements of the installed spools. The legend and CSV explicitly list **Display No. / F pair / fixed ratio**, while retaining the canonical internal state ID as provenance. The display target ratio/colour stays separate from the requested output ratio and effective Orca cadence.

## F1-F4 snapshot

{colors}

## Print

1. Open the 3MF with **Open as project** in Snapmaker Orca. Do not import it as geometry.
2. Keep the F1-F4 order above and confirm all {len(rows)} states remain in Slice Preview.
3. The 3MF contains {filament_profile} placeholders. Select the real {material} spool profiles and use the same temperature, speed, cooling, and 0.08 mm normal layer height as the production model. Do not mix material families in one print job.
4. Put the north-west chamfer at the upper-left. The 3MF object list, printed grid, PNG and CSV all follow the on-screen Mixed Palette order: numbered pair-family mixes first, followed by the unnumbered F1-F4 physical colors.
5. Compare the center of each sloped face under fixed lighting. Side walls may reveal the alternating-layer cadence.

## Record

Record slope-center HEX or Lab in `palette_mapping.csv`. A colorimeter is best; for photographs use fixed exposure and white balance with a grey card. Record brand, lot, and print conditions.

## Limits

- A 50/50 layer share is not 50% perceived lightness. Opaque black can dominate.
- The F2 base is a controlled backing and may affect translucent filament.
- The coupons have no embossed numbers; identify them with the chamfer and grid.
- Editing or recording this CSV does not automatically import or apply a measured LUT.{material_note}{output_note}{shell_note}{warning}
"""
    else:
        material_note = {
            "ABS": (
                "\n- **ABS β:** PLAより登録色・実測・色域が少ないため、目的色が無い場合は"
                "ABS内だけで近似します。PLA／PETGでは補完しません。この実機比較チャートで"
                "確認してください。Snapmaker U1でABSを印刷するにはTop Coverが必要です。"
            ),
            "PETG": (
                "\n- **PETG β:** 全スプール／ロットの色を実機校正済みではありません。"
                "本番前にこの実機比較チャートで確認してください。PLA／ABSでは補完しません。"
            ),
        }.get(material, "")
        warning = (
            "\n- 主混色の表示HEX上書きがあります。Orcaが印刷するのは任意HEXではなく層比率です。CSVの `print_ratio_predicted_hex` と実測欄も比較してください。"
            if override_warning
            else ""
        )
        output_note = (
            "\n- 出力専用比率profileが有効です。アプリの表示目標色、state ID、色割り当ては変えず、この3MFだけが凡例／CSVに記録した出力指定比率とOrca積層周期を使います。F1～F4のうち黒として選択したスロットの単色stateは変更しません。そのためOrca側のpreviewはアプリ表示と異なる場合があります。この補正はプリンター、スプール／ロット、filament profile、造形条件ごとに扱ってください。"
            if output_override
            else ""
        )
        shell_note = (
            "\n- 黒混色限定の2ウォール表面混色が有効です。このprojectはClassic wall、"
            "wall 2本、外壁／内壁とも0.42 mmを固定します。黒を含むstateだけを"
            "相手色の固定外壁＋最暗色／相手色の内壁Cycleで出力します。"
            "推奨するF1=黒の配置では2,12／3,13／4,14系になります。"
            "比較チャートと本番モデルではwall generator、wall本数、"
            "外壁／内壁幅を変更しないでください。比率が成立する基準は縦側面の"
            f"2ウォールです。このchartはCycle適用{shell_applied}行、非黒の従来recipe維持"
            f"{shell_passthrough}行、安全fallback {shell_fallback}行です。黒補正との併用を推奨します。"
            "top/bottom、infill、support、purge経路と材料の光学"
            "特性はスライサー／実機条件に依存します。"
            if surface_shell
            else ""
        )
        text = f"""# Full Spectrum 実機パレット比較チャート

3MF: `{model_name}`  
対象パレット: `{target_label}`  
状態数: {len(rows)}色

これは選択中パレットの固定スナップショットです。画面の表示目標色は予測値で、装填したスプールの実測値ではありません。凡例とCSVには **表示番号 / Fペア / 固定比率** を明記し、互換性のため内部state IDも由来情報として保持します。表示目標の比率／色、出力指定比率、Orca実効積層周期は分けて記録します。

## F1～F4の記録

{colors}

## 印刷

1. Snapmaker Orcaで3MFを **「プロジェクトとして開く / Open as project」** で開きます。「形状としてインポート」は選びません。
2. 上記F1～F4の順番を維持し、スライス表示に{len(rows)}状態が残っていることを確認します。
3. 3MF内の{filament_profile}は仮設定です。実際の{material}スプール用プロファイルを選び、本番モデルと同じ温度・速度・冷却・通常層0.08 mmに揃えます。1つの印刷ジョブに異素材を混在させないでください。
4. 北西（左上）の切欠きを左上に置きます。3MFのオブジェクト一覧、造形グリッド、PNG、CSVはすべて画面の「混色パレット」と同じ並びです。番号付き混色をFペア順で読んだ後、番号なしの物理色F1～F4を確認します。
5. 固定照明で各傾斜面中央を共通の比較面にします。側面では交互積層の縞も確認できます。

## 記録

`palette_mapping.csv` に傾斜面中央のHEXまたはLabを記録します。測色計が最良です。写真の場合はグレーカードを添え、露出とホワイトバランスを固定してください。銘柄・ロット・印刷条件も記録します。

## 注意

- 50/50は知覚上の明るさ50%ではありません。不透明な黒は半分以下でも強く見える場合があります。
- 全スウォッチ下のF2台座は比較条件を揃える裏地で、半透明材料では見え方へ影響します。
- スウォッチに番号刻印はありません。左上の切欠きと配置表で識別します。
- CSVを編集・記録しても、実測LUTとして自動読込み・自動適用はされません。{material_note}{output_note}{shell_note}{warning}
"""
    path.write_text(text, encoding="utf-8", newline="\n")


def _safe_target_label(value: object, language: str) -> str:
    text = re.sub(r"[\x00-\x1F\x7F]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip().replace("`", "'")
    if text:
        return text[:160]
    return "Common palette" if language == "en" else "全体共通パレット"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def create_palette_calibration_bundle(
    output_directory: Path,
    palette: PaletteSettings,
    *,
    language: str = "ja",
    target_label: str = "",
    created_at: datetime | None = None,
) -> CalibrationBundleResult:
    """Create one complete bundle in a new, already-reserved directory."""

    output_directory = Path(output_directory)
    if not output_directory.is_dir():
        raise ValueError("calibration output directory must already exist")
    if any(output_directory.iterdir()):
        raise ValueError("calibration output directory must be empty")
    snapshot = _copy_palette(palette)
    language = "en" if str(language).lower().startswith("en") else "ja"
    label = _safe_target_label(target_label, language)
    timestamp = created_at or datetime.now().astimezone()
    canonical_rows = palette_calibration_rows(snapshot)
    rows = palette_family_display_rows(snapshot)
    chart = build_calibration_chart_mesh(snapshot)
    prepared, colors = _prepared_chart(chart, snapshot)

    stem = f"FullSpectrum_palette_calibration_{chart.state_count}colors"
    model_path = output_directory / f"{stem}.3mf"
    mapping_path = output_directory / "palette_mapping.csv"
    legend_path = output_directory / "palette_legend.png"
    guide_path = output_directory / ("README_EN.md" if language == "en" else "README_JA.md")
    snapshot_path = output_directory / "palette_snapshot.json"
    validation_path = output_directory / "validation.json"
    manifest_path = output_directory / "bundle_manifest.json"

    writer_validation = engine.write_3mf_atomic(
        model_path,
        prepared,
        colors,
        MODEL_HEIGHT_MM,
        snapshot,
        part_palettes=None,
        print_uses_global_palette=True,
    )
    validation = _inspect_3mf(
        model_path,
        chart,
        snapshot,
        writer_validation,
    )
    if not bool(validation.get("valid")):
        raise RuntimeError(
            "generated calibration 3MF failed validation: "
            + json.dumps(validation, ensure_ascii=False)
        )

    _write_mapping_csv(mapping_path, rows)
    _write_legend(legend_path, rows, snapshot, language=language)
    _write_guide(
        guide_path,
        model_path.name,
        snapshot,
        rows,
        language=language,
        target_label=label,
    )
    palette_snapshot = {
        "schema": CALIBRATION_SCHEMA,
        "created_at": timestamp.isoformat(),
        "target_label": label,
        "language": language,
        "palette": asdict(snapshot),
        # ``states`` retains the canonical ID-indexed contract used by older
        # tooling.  ``chart_rows`` is the human-facing family-major mapping.
        "states": canonical_rows,
        "chart_rows": rows,
        "chart": {
            "state_count": chart.state_count,
            "rows": chart.row_count,
            "columns": GRID_COLUMNS,
            "object_state_ids": [
                int(value) + 1 for value in chart.part_state_indices[1:]
            ],
            "display_numbers": [row["chart_number"] for row in rows],
            "display_labels": [str(row["display_label"]) for row in rows],
            "dimensions_mm": [
                BASE_WIDTH_MM,
                chart.base_depth_mm,
                MODEL_HEIGHT_MM,
            ],
            "measurement_face": "slope_center",
            "orientation_marker": "north-west chamfer",
        },
    }
    snapshot_path.write_text(
        json.dumps(palette_snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    manifest_files = (
        model_path,
        mapping_path,
        legend_path,
        guide_path,
        snapshot_path,
        validation_path,
    )
    manifest = {
        "schema": "obj-adjuster.palette-calibration-bundle.v1",
        "created_at": timestamp.isoformat(),
        "target_label": label,
        "state_count": chart.state_count,
        "presentation_order": [
            {
                "position": position,
                "chart_number": row["chart_number"],
                "display_label": str(row["display_label"]),
                "state": int(row["state"]),
                "f_pair": str(row["f_pair"]),
                "fixed_ratio": str(row["fixed_ratio"]),
            }
            for position, row in enumerate(rows, start=1)
        ],
        "files": [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in manifest_files
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    return CalibrationBundleResult(
        folder=output_directory,
        model_path=model_path,
        mapping_path=mapping_path,
        legend_path=legend_path,
        guide_path=guide_path,
        snapshot_path=snapshot_path,
        validation_path=validation_path,
        manifest_path=manifest_path,
        state_count=chart.state_count,
        target_label=label,
        validation=validation,
    )


def generate_palette_calibration_bundle(
    parent_directory: Path,
    palette: PaletteSettings,
    *,
    language: str = "ja",
    target_label: str = "",
    created_at: datetime | None = None,
) -> CalibrationBundleResult:
    """Atomically publish a uniquely named calibration bundle folder."""

    parent = Path(parent_directory).resolve()
    if not parent.is_dir():
        raise ValueError(f"calibration parent directory does not exist: {parent}")
    timestamp = created_at or datetime.now().astimezone()
    state_count = mixer.coerce_palette_state_count(palette.palette_state_count)
    base_name = (
        f"FullSpectrum_palette_calibration_{state_count}colors_"
        f"{timestamp.strftime('%Y%m%d-%H%M%S')}"
    )
    final = parent / base_name
    suffix = 2
    while final.exists():
        final = parent / f"{base_name}-{suffix}"
        suffix += 1
    staging = parent / f".{base_name}.{uuid.uuid4().hex}.tmp"
    staging.mkdir(exist_ok=False)
    try:
        staged = create_palette_calibration_bundle(
            staging,
            palette,
            language=language,
            target_label=target_label,
            created_at=timestamp,
        )
        os.replace(staging, final)
        return CalibrationBundleResult(
            folder=final,
            model_path=final / staged.model_path.name,
            mapping_path=final / staged.mapping_path.name,
            legend_path=final / staged.legend_path.name,
            guide_path=final / staged.guide_path.name,
            snapshot_path=final / staged.snapshot_path.name,
            validation_path=final / staged.validation_path.name,
            manifest_path=final / staged.manifest_path.name,
            state_count=staged.state_count,
            target_label=staged.target_label,
            validation=staged.validation,
        )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
