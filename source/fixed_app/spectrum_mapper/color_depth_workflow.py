"""Public workflow facade for r21's all-colour ColorDepth laboratory.

The GUI talks only to this module.  Exact tetrahedralisation/refinement is a
separate geometry concern and is loaded lazily through a small request
protocol, so the real-head builder can evolve without re-introducing the
obsolete r20 uniform-black assumptions into application settings or UI code.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

from .color_depth import ColorDepthCellResult, ColorDepthRecipe
from .color_depth_recipes import (
    ColorDepthRecipePlan,
    build_uncalibrated_common_skin_recipes,
    relative_srgb_luminance,
)
from .engine import apply_palette_overrides_parts, emit, recolor_level_parts
from .models import (
    AppSettings,
    COLOR_DEPTH_UNCALIBRATED_POLICY,
    PreparedGeometry,
    ProgressCallback,
)
from .mixer import palette_mix_specs
from .parts import resolve_part_palette_settings, validate_part_layout
from .radial_export import package_from_color_depth, write_radial_3mf_atomic


COLOR_DEPTH_BUNDLE_SCHEMA = (
    "tripo-spectrum-mapper.color-depth.bundle.experimental.v1"
)


class ColorDepthWorkflowError(RuntimeError):
    """Stable, localisable rejection from the high-level workflow."""

    def __init__(
        self,
        code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(self.code)


def _raise(code: str, **details: object) -> None:
    raise ColorDepthWorkflowError(code, details)


@dataclass(frozen=True, slots=True)
class ColorDepthGeometryRequest:
    """Complete input contract for an exact physical-material builder.

    ``face_target_labels`` are zero-based stable target-colour IDs.  They are
    not extruder IDs and their old Ratio percentages have no output meaning.
    A builder must return disjoint exact-touch physical unions in millimetres.
    """

    prepared: PreparedGeometry | None
    height_mm: float
    face_target_labels: np.ndarray
    recipes: Mapping[int, ColorDepthRecipe]
    recipe_plan: ColorDepthRecipePlan
    progress: ProgressCallback | None = None
    source_surface: object | None = None


@runtime_checkable
class ColorDepthGeometryBuilder(Protocol):
    def __call__(
        self,
        request: ColorDepthGeometryRequest,
    ) -> ColorDepthCellResult: ...


@dataclass(frozen=True, slots=True)
class ColorDepthBundleResult:
    model_path: Path
    report_path: Path
    guide_path: Path
    validation: Mapping[str, object]
    outer_thickness_mm: float
    layer_height_mm: float
    target_labels: tuple[int, ...]
    collapsed_target_groups: tuple[tuple[int, ...], ...]


_BUILDER_CANDIDATES = (
    ("spectrum_mapper.color_depth_head_geometry", "build_color_depth_head_materials"),
    ("spectrum_mapper.color_depth_geometry", "build_color_depth_head_materials"),
    ("spectrum_mapper.color_depth_geometry", "build_color_depth_geometry"),
    ("spectrum_mapper.color_depth_head_builder", "build_color_depth_head_materials"),
)


def _load_default_geometry_builder() -> ColorDepthGeometryBuilder:
    attempted: list[str] = []
    for module_name, attribute in _BUILDER_CANDIDATES:
        attempted.append(f"{module_name}:{attribute}")
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            # Propagate a missing dependency *inside* a present builder rather
            # than disguising it as an unavailable builder.
            if exc.name != module_name:
                _raise(
                    "geometry_builder_dependency_missing",
                    module=module_name,
                    dependency=exc.name,
                )
            continue
        function = getattr(module, attribute, None)
        if callable(function):
            return function
    _raise("geometry_builder_unavailable", attempted=attempted)


def _same_physical_filaments(palettes: tuple[object, ...]) -> tuple[str, ...]:
    if not palettes:
        _raise("palette_required")
    first = tuple(str(value).upper() for value in palettes[0].physical_hex)
    for index, palette in enumerate(palettes[1:], start=1):
        current = tuple(str(value).upper() for value in palette.physical_hex)
        if current != first:
            _raise(
                "shared_physical_filaments_required",
                part_index=index,
            )
    return first


def _guide_text(result: ColorDepthBundleResult) -> str:
    groups = (
        ", ".join(
            "/".join(str(label + 1) for label in group)
            for group in result.collapsed_target_groups
        )
        or "none"
    )
    return (
        "ChromaMatter legacy r21 / ColorDepth Lab / SLICE ONLY\n"
        "=========================================================\n\n"
        "This is an uncalibrated physical-depth experiment. FullSpectrum "
        "state IDs are target-colour labels only. Legacy Ratio/Cycle "
        "percentages are ignored and no virtual mixed tool is emitted.\n"
        f"Common outer depth: {result.outer_thickness_mm:.3f} mm\n"
        f"Layer height: fixed {result.layer_height_mm:.2f} mm\n"
        f"Collapsed target-label groups (shown one-based): {groups}\n\n"
        "Snapmaker Orca safety gate\n"
        "---------------------------\n"
        "1. Open as a project and slice only. Do not send it to the printer.\n"
        "2. Inspect every layer in Filament view. Only physical F1-F4 may "
        "appear; there must be no Ratio, Cycle, virtual tool, or paint tool.\n"
        "3. Stop for an access violation, path conflict, missing region, "
        "non-manifold warning, gap, overlap, or exposed backing where the "
        "outer material should be visible.\n\n"
        "Colour limitation\n"
        "-----------------\n"
        "This provisional common-skin policy cannot reproduce multiple shades "
        "of the same physical pair: those target labels collapse to one "
        "ordered material recipe. A measured per-target ColorDepth LUT is "
        "required before colour-accurate printing is allowed.\n"
    )


def inspect_color_depth_3mf(
    source_path: Path,
    *,
    expected_physical_slot_order: Sequence[str] | None = None,
    expected_state_pairs: Mapping[int, Sequence[int]] | None = None,
):
    """Read and validate one ordinary per-part FullSpectrum 3MF.

    Embedded F1--F4 and state-pair identities are authoritative unless the
    caller explicitly supplies an expected contract.  No Cycle/Ratio string,
    paint command, slicer setting, or toolpath content is executed.
    """

    from .color_depth_3mf_input import import_color_depth_3mf

    return import_color_depth_3mf(
        Path(source_path),
        expected_physical_slot_order=expected_physical_slot_order,
        expected_state_pairs=expected_state_pairs,
    )


def _embedded_pair_recipe_plan(
    imported: object,
    *,
    outer_thickness_mm: float,
) -> ColorDepthRecipePlan:
    """Create provisional recipes from pair identity, never source ratios."""

    physical = tuple(str(value).upper() for value in imported.physical_slot_order)
    if len(physical) != 4:
        _raise("four_physical_filaments_required", count=len(physical))
    state_count = int(imported.palette_state_count)
    pairs = tuple(
        (int(pair[0]), int(pair[1])) for pair in imported.print_mix_specs
    )
    if state_count < 4 or len(pairs) != state_count - 4:
        _raise(
            "embedded_state_pair_table_invalid",
            palette_state_count=state_count,
            pair_count=len(pairs),
        )
    labels = tuple(
        int(value)
        for value in np.unique(np.asarray(imported.face_target_labels))
    )
    if not labels or labels[0] < 0 or labels[-1] >= state_count:
        _raise(
            "embedded_target_label_out_of_range",
            target_labels=labels,
            palette_state_count=state_count,
        )
    thickness = float(outer_thickness_mm)
    luminance = tuple(relative_srgb_luminance(value) for value in physical)
    recipes: dict[int, ColorDepthRecipe] = {}
    signature_groups: dict[tuple[int, float, int], list[int]] = {}
    for label in labels:
        if label < 4:
            outer = backing = label + 1
            source_pair = (outer, outer)
            source_kind = "pure-physical"
        else:
            left, right = pairs[label - 4]
            if not (1 <= left <= 4 and 1 <= right <= 4 and left != right):
                _raise(
                    "embedded_state_pair_invalid",
                    target_label=label,
                    physical_pair=(left, right),
                )
            delta = luminance[left - 1] - luminance[right - 1]
            if abs(delta) <= 1e-12:
                _raise(
                    "provisional_outer_material_ambiguous",
                    target_label=label,
                    physical_pair=(left, right),
                )
            outer = left if delta > 0.0 else right
            backing = right if outer == left else left
            source_pair = (left, right)
            source_kind = "embedded-mixed-pair-only"
        recipe = ColorDepthRecipe(
            target_label=label,
            outer_physical=outer,
            outer_thickness_mm=thickness,
            backing_physical=backing,
            calibrated=False,
            metadata={
                "provisional": True,
                "source_kind": source_kind,
                "embedded_physical_pair": list(source_pair),
                "legacy_ratio_ignored": label >= 4,
                "selection_rule": (
                    "pure-material"
                    if outer == backing
                    else "higher-WCAG-luminance outside"
                ),
            },
        )
        recipes[label] = recipe
        signature_groups.setdefault((outer, thickness, backing), []).append(label)
    collapsed = tuple(
        tuple(group)
        for _signature, group in sorted(signature_groups.items())
        if len(group) > 1 and any(label >= 4 for label in group)
    )
    return ColorDepthRecipePlan(
        recipes=recipes,
        target_labels=labels,
        collapsed_target_groups=collapsed,
        physical_hex=physical,  # type: ignore[arg-type]
        outer_thickness_mm=thickness,
        calibrated=False,
        metadata={
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "recipe_policy": COLOR_DEPTH_UNCALIBRATED_POLICY,
            "recipe_source": "embedded-state-pair-identity",
            "legacy_mix_percentages_used": False,
            "legacy_cycle_values_used": False,
            "embedded_state_pairs": {
                str(index + 4): list(pair) for index, pair in enumerate(pairs)
            },
            "target_shades_collapsed": bool(collapsed),
            "calibration_required_for_colour_accuracy": True,
        },
    )


def _same_output_path(source: Path, destination: Path) -> bool:
    source_resolved = source.resolve()
    destination_resolved = destination.resolve()
    if str(source_resolved).casefold() == str(destination_resolved).casefold():
        return True
    if destination_resolved.exists():
        try:
            return source_resolved.samefile(destination_resolved)
        except OSError:
            return False
    return False


def export_color_depth_from_3mf(
    source_path: Path,
    settings: AppSettings,
    destination: Path,
    *,
    progress: ProgressCallback | None = None,
    geometry_builder: ColorDepthGeometryBuilder | None = None,
    expected_physical_slot_order: Sequence[str] | None = None,
    expected_state_pairs: Mapping[int, Sequence[int]] | None = None,
) -> ColorDepthBundleResult:
    """Convert one validated per-part 3MF through the exact ColorDepth path."""

    color_depth = settings.color_depth
    if not color_depth.experimental_enabled:
        _raise("experimental_opt_in_required")
    if color_depth.recipe_policy != COLOR_DEPTH_UNCALIBRATED_POLICY:
        _raise("unsupported_recipe_policy", policy=color_depth.recipe_policy)
    if float(color_depth.layer_height_mm) != 0.20:
        _raise("fixed_layer_height_required", layer_height_mm=color_depth.layer_height_mm)

    source = Path(source_path)
    destination = Path(destination).with_suffix(".3mf")
    if _same_output_path(source, destination):
        _raise("source_destination_same", source_name=source.name)

    emit(progress, "color_depth_3mf_inspect", 0.02, "Validate source part 3MF")
    imported = inspect_color_depth_3mf(
        source,
        expected_physical_slot_order=expected_physical_slot_order,
        expected_state_pairs=expected_state_pairs,
    )
    plan = _embedded_pair_recipe_plan(
        imported,
        outer_thickness_mm=float(color_depth.outer_thickness_mm),
    )

    from .color_depth_head_geometry import ColorDepthSourceSurface

    vertices = np.asarray(imported.vertices_mm, dtype=np.float64)
    height_mm = float(np.ptp(vertices[:, 2]))
    source_surface = ColorDepthSourceSurface(
        vertices_mm=imported.vertices_mm,
        faces=imported.faces,
        face_target_labels=imported.face_target_labels,
        height_mm=height_mm,
        source_name=imported.source_name,
        source_sha256=imported.source_sha256,
        source_volume_mm3=float(imported.source_volume_mm3),
        metadata={
            **dict(imported.metadata),
            "input_kind": "ordinary-per-part-3mf",
            "source_archive_name": imported.source_name,
            "source_archive_sha256": imported.source_sha256,
            "legacy_mix_percentages_used": False,
            "legacy_cycle_values_used": False,
        },
    )
    emit(progress, "color_depth_geometry", 0.12, "ColorDepth physical partition")
    builder = geometry_builder or _load_default_geometry_builder()
    request = ColorDepthGeometryRequest(
        prepared=None,
        height_mm=height_mm,
        face_target_labels=imported.face_target_labels,
        recipes=plan.recipes,
        recipe_plan=plan,
        progress=progress,
        source_surface=source_surface,
    )
    material_result = builder(request)
    package = package_from_color_depth(
        material_result,
        imported.physical_slot_order,
    )
    emit(progress, "color_depth_3mf", 0.76, "ColorDepth physical-only 3MF")
    validation_value = write_radial_3mf_atomic(
        destination,
        package,
        title=f"{destination.stem} [SLICE ONLY / ColorDepth Lab]",
    )
    validation = (
        validation_value.to_dict()
        if hasattr(validation_value, "to_dict")
        else dict(validation_value)
    )
    report_path = destination.with_name(
        destination.stem + "_color_depth_validation.json"
    )
    guide_path = destination.with_name(
        destination.stem + "_SLICE_ONLY_guide.txt"
    )
    report = {
        "schema": COLOR_DEPTH_BUNDLE_SCHEMA,
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "calibrated": False,
        "source_kind": "ordinary-per-part-3mf",
        "source_archive": dict(imported.metadata).get("source_archive", {}),
        "source_model": dict(imported.metadata).get("model", {}),
        "source_palette": dict(imported.metadata).get("palette", {}),
        "source_transform": dict(imported.metadata).get("transform", {}),
        "source_canonicalization": dict(imported.metadata).get(
            "canonicalization", {}
        ),
        "physical_hex": list(imported.physical_slot_order),
        "outer_thickness_mm": float(color_depth.outer_thickness_mm),
        "layer_height_mm": float(color_depth.layer_height_mm),
        "target_labels": list(plan.target_labels),
        "collapsed_target_groups": [
            list(group) for group in plan.collapsed_target_groups
        ],
        "legacy_fullspectrum_ratios_used": False,
        "legacy_cycle_values_used": False,
        "recipe_plan": plan.to_dict(),
        "geometry": dict(getattr(material_result, "metadata", {}) or {}),
        "archive_validation": validation,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    result = ColorDepthBundleResult(
        model_path=destination,
        report_path=report_path,
        guide_path=guide_path,
        validation=validation,
        outer_thickness_mm=float(color_depth.outer_thickness_mm),
        layer_height_mm=float(color_depth.layer_height_mm),
        target_labels=plan.target_labels,
        collapsed_target_groups=plan.collapsed_target_groups,
    )
    guide_path.write_text(_guide_text(result), encoding="utf-8-sig")
    emit(progress, "color_depth_done", 1.0, "ColorDepth SLICE ONLY 3MF saved")
    return result


def export_color_depth_bundle(
    prepared: PreparedGeometry,
    settings: AppSettings,
    destination: Path,
    *,
    manual_overrides: np.ndarray | None = None,
    progress: ProgressCallback | None = None,
    geometry_builder: ColorDepthGeometryBuilder | None = None,
    part_key: str | None = None,
    part_id: int | None = None,
) -> ColorDepthBundleResult:
    """Create one fail-closed, all-state, physical-only ColorDepth bundle."""

    color_depth = settings.color_depth
    if not color_depth.experimental_enabled:
        _raise("experimental_opt_in_required")
    if color_depth.recipe_policy != COLOR_DEPTH_UNCALIBRATED_POLICY:
        _raise("unsupported_recipe_policy", policy=color_depth.recipe_policy)
    if float(color_depth.layer_height_mm) != 0.20:
        _raise("fixed_layer_height_required", layer_height_mm=color_depth.layer_height_mm)

    # A multipart GUI project may intentionally use a different physical F1-F4
    # set for each print part.  In that case the active part is a complete,
    # independently sliceable ColorDepth job; forcing all palettes through one
    # physical archive would be both wrong and rejected by the writer.  Reuse
    # the established individual-part extraction path before any palette or
    # target-label work.  With no selection, preserve the original whole-model
    # contract and its shared-physical-filament gate.
    source_prepared = prepared
    source_part_keys = tuple(str(value) for value in prepared.final.part_keys)
    source_part_count = len(source_part_keys)
    selected_part_key: str | None = None
    selected_part_id: int | None = None
    if part_key is not None and part_id is not None:
        _raise("part_selection_conflict", part_key=part_key, part_id=part_id)
    if part_key is not None:
        selected_part_key = str(part_key)
        try:
            selected_part_id = source_part_keys.index(selected_part_key)
        except ValueError:
            _raise(
                "part_key_not_found",
                part_key=selected_part_key,
                available_part_keys=source_part_keys,
            )
    elif part_id is not None:
        try:
            selected_part_id = int(part_id)
        except (TypeError, ValueError):
            _raise("part_id_out_of_range", part_id=part_id, part_count=source_part_count)
        if not 0 <= selected_part_id < source_part_count:
            _raise(
                "part_id_out_of_range",
                part_id=selected_part_id,
                part_count=source_part_count,
            )
        selected_part_key = source_part_keys[selected_part_id]
    if selected_part_id is not None:
        # Local import avoids making the normal FullSpectrum workflow import
        # ColorDepth during module initialisation.
        from .workflow import _extract_prepared_part

        prepared, source_face_ids = _extract_prepared_part(
            source_prepared, selected_part_id
        )
        if manual_overrides is not None:
            raw_overrides = np.asarray(manual_overrides)
            if raw_overrides.shape != (len(source_prepared.final.faces),):
                _raise(
                    "invalid_manual_overrides",
                    expected_faces=len(source_prepared.final.faces),
                    actual_shape=tuple(raw_overrides.shape),
                )
            manual_overrides = np.ascontiguousarray(
                raw_overrides[source_face_ids]
            )
    if not bool(prepared.topology.get("watertight")):
        _raise("watertight_mesh_required", topology=dict(prepared.topology))

    layout = validate_part_layout(prepared.final)
    palettes = resolve_part_palette_settings(settings, layout)
    physical_hex = _same_physical_filaments(palettes)
    # The target-state definitions also have to be the same when several
    # connected source parts share one physical material partition.  This is
    # not a one-part/uniform-state restriction; it prevents one numerical
    # label from meaning two different physical pairs inside a single 3MF.
    first_palette = palettes[0]
    # Compare only stable state-to-pair identity.  Ratio values are expressly
    # excluded: ColorDepth ignores them, so a per-part legacy percentage must
    # never block or change the physical-depth output.
    first_signature = (
        int(first_palette.palette_state_count),
        tuple(
            (int(left), int(right))
            for left, right, _ratio in palette_mix_specs(
                first_palette.mix_ratios_b,
                first_palette.secondary_mix_ratios_b,
            )
        ),
    )
    for index, palette in enumerate(palettes[1:], start=1):
        signature = (
            int(palette.palette_state_count),
            tuple(
                (int(left), int(right))
                for left, right, _ratio in palette_mix_specs(
                    palette.mix_ratios_b,
                    palette.secondary_mix_ratios_b,
                )
            ),
        )
        if signature != first_signature:
            _raise("shared_target_state_table_required", part_index=index)

    emit(progress, "color_depth_labels", 0.04, "ColorDepth target labels")
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
    labels = np.asarray(colors.palette_indices, dtype=np.int16)
    if labels.shape != (len(prepared.final.faces),):
        _raise(
            "invalid_face_target_labels",
            expected_faces=len(prepared.final.faces),
            actual_shape=tuple(labels.shape),
        )
    target_labels = tuple(int(value) for value in np.unique(labels))
    plan = build_uncalibrated_common_skin_recipes(
        first_palette,
        target_labels,
        outer_thickness_mm=float(color_depth.outer_thickness_mm),
    )

    emit(progress, "color_depth_geometry", 0.12, "ColorDepth physical partition")
    builder = geometry_builder or _load_default_geometry_builder()
    request = ColorDepthGeometryRequest(
        prepared=prepared,
        height_mm=float(settings.geometry.height_mm),
        face_target_labels=np.ascontiguousarray(labels),
        recipes=plan.recipes,
        recipe_plan=plan,
        progress=progress,
    )
    material_result = builder(request)
    package = package_from_color_depth(material_result, physical_hex)

    destination = Path(destination).with_suffix(".3mf")
    emit(progress, "color_depth_3mf", 0.76, "ColorDepth physical-only 3MF")
    validation_value = write_radial_3mf_atomic(
        destination,
        package,
        title=f"{destination.stem} [SLICE ONLY / ColorDepth Lab]",
    )
    validation = (
        validation_value.to_dict()
        if hasattr(validation_value, "to_dict")
        else dict(validation_value)
    )
    report_path = destination.with_name(
        destination.stem + "_color_depth_validation.json"
    )
    guide_path = destination.with_name(
        destination.stem + "_SLICE_ONLY_guide.txt"
    )
    report = {
        "schema": COLOR_DEPTH_BUNDLE_SCHEMA,
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "calibrated": False,
        "recipe_policy": color_depth.recipe_policy,
        "legacy_fullspectrum_ratios_used": False,
        "source_obj_sha256": str(prepared.source.sha256),
        "source_part_count": int(layout.part_count),
        "source_assembly_part_count": int(source_part_count),
        "selected_part_id": selected_part_id,
        "selected_part_key": selected_part_key,
        "physical_hex": list(physical_hex),
        "outer_thickness_mm": float(color_depth.outer_thickness_mm),
        "layer_height_mm": float(color_depth.layer_height_mm),
        "target_labels": list(plan.target_labels),
        "collapsed_target_groups": [
            list(group) for group in plan.collapsed_target_groups
        ],
        "recipe_plan": plan.to_dict(),
        "geometry": dict(getattr(material_result, "metadata", {}) or {}),
        "archive_validation": validation,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    provisional = ColorDepthBundleResult(
        model_path=destination,
        report_path=report_path,
        guide_path=guide_path,
        validation=validation,
        outer_thickness_mm=float(color_depth.outer_thickness_mm),
        layer_height_mm=float(color_depth.layer_height_mm),
        target_labels=plan.target_labels,
        collapsed_target_groups=plan.collapsed_target_groups,
    )
    guide_path.write_text(_guide_text(provisional), encoding="utf-8-sig")
    emit(progress, "color_depth_done", 1.0, "ColorDepth SLICE ONLY 3MF saved")
    return provisional


__all__ = [
    "COLOR_DEPTH_BUNDLE_SCHEMA",
    "ColorDepthBundleResult",
    "ColorDepthGeometryBuilder",
    "ColorDepthGeometryRequest",
    "ColorDepthWorkflowError",
    "export_color_depth_bundle",
    "export_color_depth_from_3mf",
    "inspect_color_depth_3mf",
]
