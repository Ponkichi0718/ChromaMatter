from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageTk

from . import APP_DISPLAY_NAME, APP_NAME, APP_TAGLINE, RELEASE_REVISION, __version__
from .calibration_chart import generate_palette_calibration_bundle
from .engine import (
    EngineError,
    apply_palette_overrides,
    apply_palette_overrides_parts,
    apply_tone,
    load_vertex_color_model,
    prepare_geometry,
    recolor_level,
    recolor_level_parts,
)
from .mixer import (
    NEUTRAL_PALETTE_STATES,
    PAIR_INDICES,
    PALETTE_STATE_COUNT,
    SUPPORTED_PALETTE_STATE_COUNTS,
    PINK_PALETTE_STATES,
    MixRecipeCandidate,
    black_containing_mixed_states,
    black_free_replacement_states,
    black_output_ratio_preset,
    build_palette_rgb,
    find_best_mix_recipes,
    normalize_hex,
    optimize_global_mix_ratios,
    palette_family_display_state_indices,
    palette_mix_specs,
    print_palette_mix_specs,
    resource_path,
    rgb8_to_hex,
    validate_black_free_slots,
)
from .filament_recommender import (
    CATEGORY_PRIMARY,
    FilamentCandidate,
    FilamentRecommendation,
    map_catalog_to_curated_basics,
    recommend_basic_filaments,
)
from .filament_materials import (
    MATERIAL_ABS,
    MATERIAL_PETG,
    MATERIAL_PLA,
    SUPPORTED_FILAMENT_MATERIALS,
    normalize_filament_material,
)
from .filament_candidate_gui import FilamentCandidateWindow
from .manual_joints import ManualJointError, replay_manual_joint
from .manual_joint_state import ManualJointStateError, remap_manual_overrides
from .models import (
    AppSettings,
    ColorDepthSettings,
    FilamentSnapshotRef,
    GeometrySettings,
    PaletteSettings,
    PreparedGeometry,
    RadialSettings,
    ToneSettings,
)
from .i18n import (
    LANGUAGE_DISPLAY_NAMES,
    TkLocalizer,
    Translator,
    language_from_display_name,
    load_language,
    save_language,
)
from .help_center import HelpCenterWindow, get_help_center
from .palette_state_count import apply_palette_state_count_change
from .project_bundle import (
    ProjectBundleError,
    ProjectLoadResult,
    ProjectLoadState,
    inspect_project_path,
    save_project_bundle_in_parent,
)
from .parts import (
    plan_palette_groups,
    resolve_palette_for_part_key,
    resolve_part_palette_settings,
)
from .paint import decode_manual_overrides, encode_manual_overrides, mesh_fingerprint
from .part_names import (
    PartNameError,
    apply_part_name_overrides,
    collect_part_name_overrides,
    rename_prepared_part,
)
from .freehand_split import (
    apply_level_partition_to_prepared,
    decode_manual_part_partition,
    encode_manual_part_partition,
    inherit_explicit_part_palette,
)
from .generated_surface_color import existing_tree_face_mask
from .paint_gui import PaintEditorWindow
from .reference_parts import (
    ReferencePartMatch,
    extract_corner_foreground,
    match_reference_to_parts,
)
from .renderer import RendererError, render_front_preview, render_front_preview_pair
from .color_depth import ColorDepthError
from .color_depth_workflow import (
    ColorDepthWorkflowError,
    export_color_depth_bundle,
)
from .radial_shell import RadialShellError
from .radial_workflow import export_radial_bundle
from .workflow import export_bundle


APP_TITLE = f"{APP_DISPLAY_NAME} {__version__} ({RELEASE_REVISION})"
PHYSICAL_NAMES = ("F1", "F2", "F3", "F4")
MATERIAL_GAMUT_WARNING_MEAN_DELTA_E76 = 18.0
SHORT_NAMES = PHYSICAL_NAMES
PAIR_NAMES = tuple(f"{SHORT_NAMES[a]}+{SHORT_NAMES[b]}" for a, b in PAIR_INDICES)
BG = "#10141B"
PANEL = "#171D27"
PANEL_2 = "#202836"
TEXT = "#E8EDF5"
MUTED = "#9AA8BA"
ACCENT = "#56C7FF"
SUCCESS = "#62D59A"
WARNING = "#FFBF69"


def inspect_color_depth_3mf(source_path: Path):
    """Load the optional per-part facade only when the user invokes it."""

    from .color_depth_workflow import inspect_color_depth_3mf as inspect

    return inspect(source_path)


def export_color_depth_from_3mf(
    source_path: Path,
    settings: AppSettings,
    destination: Path,
    *,
    progress=None,
):
    """Keep app start-up independent from the experimental importer."""

    from .color_depth_workflow import export_color_depth_from_3mf as export

    return export(
        source_path,
        settings,
        destination,
        progress=progress,
    )


_RADIAL_ERROR_REASON_KEYS = {
    "invalid_black_slot": "radial.reason.invalid_black_slot",
    "invalid_physical_colors": "radial.reason.invalid_physical_colors",
    "unique_darkest_black_required": "radial.reason.unique_darkest_black_required",
    "selected_black_not_darkest": "radial.reason.selected_black_not_darkest",
    "single_part_required": "radial.reason.single_part_required",
    "single_palette_required": "radial.reason.single_palette_required",
    "watertight_mesh_required": "radial.reason.closed_mesh_required",
    "closed_positive_single_body_required": "radial.reason.closed_mesh_required",
    "input_self_intersection": "radial.reason.closed_mesh_required",
    "self_intersection_check_failed": "radial.reason.closed_mesh_required",
    "generated_surface_not_supported": "radial.reason.generated_surface_not_supported",
    "no_eligible_surface": "radial.reason.uniform_black_mix_required",
    "multiple_eligible_states_not_supported": "radial.reason.uniform_black_mix_required",
    "eligible_coverage_too_low": "radial.reason.uniform_black_mix_required",
    "partial_surface_not_supported": "radial.reason.uniform_black_mix_required",
    "partner_equals_black": "radial.reason.uniform_black_mix_required",
    "invalid_state_partner_mapping": "radial.reason.uniform_black_mix_required",
    "invalid_skin_thickness": "radial.reason.skin_thickness_failed",
    "skin_consumes_core": "radial.reason.skin_thickness_failed",
    "offset_resolution_not_supported": "radial.reason.skin_thickness_failed",
    "offset_fidelity_failed": "radial.reason.skin_thickness_failed",
    "tetrahedralization_failed": "radial.reason.geometry_generation_failed",
    "tetrahedral_volume_drift": "radial.reason.geometry_generation_failed",
    "radial_interface_failed": "radial.reason.geometry_generation_failed",
    "unexpected_partition_boundaries": "radial.reason.geometry_generation_failed",
    "source_exterior_not_preserved": "radial.reason.geometry_generation_failed",
    "shared_interface_mismatch": "radial.reason.geometry_generation_failed",
    "partition_volume_drift": "radial.reason.geometry_generation_failed",
}


_COLOR_DEPTH_ERROR_REASON_KEYS = {
    "experimental_opt_in_required": "color_depth.reason.opt_in_required",
    "unsupported_recipe_policy": "color_depth.reason.recipe_policy",
    "fixed_layer_height_required": "color_depth.reason.fixed_layer",
    "watertight_mesh_required": "color_depth.reason.closed_mesh",
    "palette_required": "color_depth.reason.palette",
    "shared_physical_filaments_required": "color_depth.reason.shared_palette",
    "shared_target_state_table_required": "color_depth.reason.shared_palette",
    "invalid_face_target_labels": "color_depth.reason.geometry",
    "geometry_builder_unavailable": "color_depth.reason.builder_unavailable",
    "geometry_builder_dependency_missing": "color_depth.reason.builder_unavailable",
    "invalid_outer_thickness": "color_depth.reason.thickness",
    "provisional_outer_material_ambiguous": "color_depth.reason.ambiguous_outer",
    "target_label_out_of_range": "color_depth.reason.palette",
    "mixed_target_has_no_pair": "color_depth.reason.palette",
    "invalid_palette_for_color_depth": "color_depth.reason.palette",
}


def _color_depth_error_reason(i18n: Translator, exc: Exception) -> str:
    """Turn ColorDepth's stable fail-closed codes into actionable text."""

    if not isinstance(exc, (ColorDepthWorkflowError, ColorDepthError)):
        return str(exc)
    details = exc.details
    key = _COLOR_DEPTH_ERROR_REASON_KEYS.get(
        exc.code,
        "color_depth.reason.geometry",
    )
    return i18n.text(
        key,
        part_index=details.get("part_index", "?"),
        dependency=details.get("dependency", "?"),
    )


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    """Compare an existing source with a possibly-new destination safely."""

    try:
        return os.path.samefile(left, right)
    except OSError:
        left_key = os.path.normcase(os.path.abspath(os.fspath(left)))
        right_key = os.path.normcase(os.path.abspath(os.fspath(right)))
        return left_key == right_key


def _radial_error_reason(i18n: Translator, exc: Exception) -> str:
    """Turn stable radial error codes into concrete localized next steps."""

    if not isinstance(exc, RadialShellError):
        return str(exc)
    details = exc.details

    def filament(key: str) -> str:
        try:
            index = int(details[key])
        except (KeyError, TypeError, ValueError):
            return "?"
        return f"F{index + 1}" if 0 <= index < 4 else "?"

    try:
        slots = ", ".join(
            f"F{int(index) + 1}" for index in details.get("darkest_slots", ())
        )
    except (TypeError, ValueError):
        slots = "?"
    key = _RADIAL_ERROR_REASON_KEYS.get(
        exc.code,
        "radial.reason.geometry_rejected",
    )
    return i18n.text(
        key,
        selected=filament("black_slot"),
        darkest=filament("darkest_slot"),
        slots=slots or "?",
        part_count=details.get("part_count", "?"),
    )

def _configuration_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "TripoSpectrumMapper"


_PREFERENCES_SCHEMA = "obj-adjuster.preferences.v5-developer-features"
_PROJECT_SCHEMA = "obj-adjuster.project.v12"
_COLOR_DEPTH_TRUSTED_PROJECT_SCHEMAS = {
    "obj-adjuster.project.v10",
    "obj-adjuster.project.v11",
    _PROJECT_SCHEMA,
}


def _developer_features_enabled_from_mapping(value: object) -> bool:
    """Load the global developer-UI gate without trusting legacy coercions.

    The gate is deliberately not part of :class:`AppSettings`: projects must
    never be able to reveal or authorize laboratory controls.  Only an exact
    JSON boolean from the current preferences schema is accepted, so old or
    hand-edited values such as ``1`` and ``"true"`` fail closed.
    """

    raw = dict(value) if isinstance(value, dict) else {}
    if str(raw.get("schema", "")) != _PREFERENCES_SCHEMA:
        return False
    return raw.get("developer_features_enabled") is True


def _persistent_preferences_from_mapping(value: object) -> AppSettings:
    """Load only settings that are safe to carry to another OBJ.

    Older builds stored the last model's tone and full filament palette in
    ``settings.json``.  Those values can make the next OBJ look unrelated to
    its vertex colours, so deliberately ignore them.  The selected number of
    output states is a quality preference rather than a colour choice and is
    therefore retained, including migration from the old nested palette.
    """

    raw = dict(value) if isinstance(value, dict) else {}
    raw_palette = raw.get("palette", {})
    legacy_palette = raw_palette if isinstance(raw_palette, dict) else {}
    count_value = raw.get(
        "palette_state_count",
        legacy_palette.get("palette_state_count", 16),
    )
    try:
        palette_state_count = int(count_value)
    except (TypeError, ValueError):
        palette_state_count = 16
    if palette_state_count not in SUPPORTED_PALETTE_STATE_COUNTS:
        palette_state_count = 16
    return _sanitize_public_settings(AppSettings.from_dict(
        {
            "geometry": raw.get("geometry", {}),
            "color_depth": raw.get("color_depth", {}),
            "radial": raw.get("radial", {}),
            "palette": {"palette_state_count": palette_state_count},
            "manual_orbit_inverted": raw.get(
                "manual_orbit_inverted", False
            ),
        }
    ))


def _persistent_preferences_payload(
    settings: AppSettings,
    *,
    developer_features_enabled: bool = False,
) -> dict[str, object]:
    """Serialize global preferences without model-dependent colour data."""

    return {
        "schema": _PREFERENCES_SCHEMA,
        "developer_features_enabled": developer_features_enabled is True,
        "geometry": settings.to_dict()["geometry"],
        "color_depth": {
            "experimental_enabled": bool(
                settings.color_depth.experimental_enabled
            ),
            "outer_thickness_mm": float(
                settings.color_depth.outer_thickness_mm
            ),
            "layer_height_mm": float(settings.color_depth.layer_height_mm),
            "recipe_policy": str(settings.color_depth.recipe_policy),
        },
        # Preserve r20's hidden settings during migration even though its GUI
        # control has been replaced by ColorDepth Lab in r21.
        "radial": {
            "outer_skin_thickness_mm": float(
                settings.radial.outer_skin_thickness_mm
            ),
            "layer_height_mm": float(settings.radial.layer_height_mm),
            "require_uniform_black_mix": bool(
                settings.radial.require_uniform_black_mix
            ),
        },
        "palette_state_count": int(settings.palette.palette_state_count),
        "manual_orbit_inverted": bool(settings.manual_orbit_inverted),
    }


def _enforce_black_free_gradient_developer_gate(
    settings: AppSettings,
    developer_features_enabled: bool = False,
) -> int:
    """Disable the laboratory black-free policy unless explicitly allowed.

    The permission lives in global preferences, never in a project.  Returning
    the number of changed palettes makes the developer-toggle path easy to
    report and test without coupling this safety rule to Tk.
    """

    if developer_features_enabled is True:
        return 0
    changed = 0
    for palette in (settings.palette, *settings.part_palettes.values()):
        if bool(getattr(palette, "black_free_gradient_enabled", False)):
            palette.black_free_gradient_enabled = False
            changed += 1
    return changed


def _sanitize_public_settings(settings: AppSettings) -> AppSettings:
    """Fail closed for research/split/joint settings hidden in the public UI.

    Old preferences and projects may contain explicit opt-ins from earlier
    developer builds.  Once their controls are removed, leaving those values
    active would make an invisible option affect output.  Retain every core
    implementation/callback, but normalize the public session to its safe
    reachable feature set.  Output-only black correction remains untouched.
    """

    settings.color_depth.experimental_enabled = False
    settings.geometry.auto_joints = False
    settings.geometry.split_enabled = False
    for palette in (settings.palette, *settings.part_palettes.values()):
        palette.black_free_gradient_enabled = False
        palette.surface_shell_enabled = False
    return settings


def _project_settings_from_mapping(
    value: object,
    *,
    developer_features_enabled: bool = False,
) -> AppSettings:
    """Load project settings with an explicit ColorDepth opt-in gate.

    v9 and earlier never had a user-visible all-colour ColorDepth consent.
    Even if a hand-edited legacy JSON happens to contain similarly named
    fields, loading it must not silently enable an uncalibrated export path.
    v10 and later are trusted ColorDepth opt-ins.  v12 adds the explicit
    PLA/ABS/PETG material field; missing material in v11 and earlier is PLA.
    """

    data = dict(value) if isinstance(value, dict) else {}
    settings_data = data.get("settings", data)
    settings = AppSettings.from_dict(
        dict(settings_data) if isinstance(settings_data, dict) else {}
    )
    schema = str(data.get("schema", ""))
    if schema not in _COLOR_DEPTH_TRUSTED_PROJECT_SCHEMAS:
        settings.color_depth.experimental_enabled = False
    # Black-Free Gradient is a laboratory policy.  Even a valid project
    # can restore it only while the global developer gate is already enabled;
    # a project itself can never reveal or authorize the hidden feature.
    if schema != _PROJECT_SCHEMA or developer_features_enabled is not True:
        _enforce_black_free_gradient_developer_gate(settings, False)
    return _sanitize_public_settings(settings)


def _fresh_settings_for_new_obj(settings: AppSettings) -> AppSettings:
    """Reset per-model colour state while retaining global preferences."""

    return _sanitize_public_settings(AppSettings(
        geometry=GeometrySettings(**settings.to_dict()["geometry"]),
        tone=ToneSettings(),
        palette=PaletteSettings(
            material=settings.palette.material,
            palette_state_count=settings.palette.palette_state_count
        ),
        color_depth=ColorDepthSettings(
            # ColorDepth is a retained research implementation without a
            # public entry point.  A stale preference must not silently make
            # a newly opened OBJ use the experimental writer.
            experimental_enabled=False,
            outer_thickness_mm=settings.color_depth.outer_thickness_mm,
            layer_height_mm=settings.color_depth.layer_height_mm,
            recipe_policy=settings.color_depth.recipe_policy,
        ),
        radial=RadialSettings(
            outer_skin_thickness_mm=(
                settings.radial.outer_skin_thickness_mm
            ),
            layer_height_mm=settings.radial.layer_height_mm,
            require_uniform_black_mix=(
                settings.radial.require_uniform_black_mix
            ),
        ),
        part_palettes={},
        part_names={},
        # Background choices are keyed by an OBJ digest and therefore cannot
        # leak from one model to another.  Keep them for reopening the same
        # model during the current application session.
        manual_view_backgrounds=dict(settings.manual_view_backgrounds),
        manual_orbit_inverted=settings.manual_orbit_inverted,
    ))


def _geometry_key(settings: GeometrySettings) -> tuple[object, ...]:
    return (
        int(settings.target_faces) if settings.adjust_face_count else None,
        int(settings.preview_faces),
        settings.up_axis.upper(),
        int(settings.min_component_faces),
        bool(settings.mirror_x),
        bool(settings.preserve_parts),
        bool(settings.solidify_parts),
        bool(settings.repair_unmatched_boundaries),
        bool(settings.auto_joints),
        float(settings.joint_width_mm),
        float(settings.joint_height_mm),
        float(settings.joint_depth_mm),
        float(settings.joint_clearance_mm),
        float(settings.joint_min_seam_span_mm),
        bool(settings.split_enabled),
        settings.split_axis.upper(),
        float(settings.split_position_percent),
        int(settings.split_target_part),
    )


def _paint_topology_key(settings: GeometrySettings) -> tuple[object, ...]:
    """Geometry fields that can change final face indices used by paint data."""

    return (
        int(settings.target_faces) if settings.adjust_face_count else None,
        settings.up_axis.upper(),
        int(settings.min_component_faces),
        bool(settings.mirror_x),
        bool(settings.preserve_parts),
        bool(settings.solidify_parts),
        bool(settings.repair_unmatched_boundaries),
        bool(settings.auto_joints),
        float(settings.joint_width_mm),
        float(settings.joint_height_mm),
        float(settings.joint_depth_mm),
        float(settings.joint_clearance_mm),
        float(settings.joint_min_seam_span_mm),
        bool(settings.split_enabled),
        settings.split_axis.upper(),
        float(settings.split_position_percent),
        int(settings.split_target_part),
    )


def _prepared_paint_topology_key(
    prepared_key: tuple[object, ...] | None,
) -> tuple[object, ...] | None:
    if prepared_key is None or len(prepared_key) < 2:
        return None
    return prepared_key[:1] + prepared_key[2:]


def _is_explicit_single_glb_seam_weld_transition(
    source_path: Path | None,
    before: PreparedGeometry | None,
    after: PreparedGeometry | None,
    before_key: tuple[object, ...] | None,
    after_key: tuple[object, ...] | None,
) -> bool:
    """Recognize only the explicit, face-preserving single-GLB repair path."""

    if (
        source_path is None
        or source_path.suffix.lower() not in {".glb", ".gltf"}
        or before is None
        or after is None
    ):
        return False
    before_paint_key = _prepared_paint_topology_key(before_key)
    after_paint_key = _prepared_paint_topology_key(after_key)
    solidify_index = 5
    if (
        before_paint_key is None
        or after_paint_key is None
        or len(before_paint_key) != len(after_paint_key)
        or len(before_paint_key) <= solidify_index
        or bool(before_paint_key[solidify_index])
        or not bool(after_paint_key[solidify_index])
        or before_paint_key[:solidify_index]
        != after_paint_key[:solidify_index]
        or before_paint_key[solidify_index + 1 :]
        != after_paint_key[solidify_index + 1 :]
    ):
        return False
    before_source = getattr(before, "source", None)
    after_source = getattr(after, "source", None)
    if (
        before_source is None
        or after_source is None
        or str(getattr(before_source, "sha256", ""))
        != str(getattr(after_source, "sha256", ""))
    ):
        return False
    before_assembly = dict(before.assembly or {})
    after_assembly = dict(after.assembly or {})
    if bool(before_assembly.get("solidify_parts")):
        return False
    if not (
        bool(after_assembly.get("solidify_parts"))
        and bool(after_assembly.get("single_mesh_generic"))
        and after_assembly.get("repair_method")
        == "coincident_vertex_seam_weld"
    ):
        return False
    records = after_assembly.get("repair_records")
    if not isinstance(records, (list, tuple)) or len(records) != 1:
        return False
    record = records[0]
    return bool(
        isinstance(record, dict)
        and record.get("method") == "coincident_vertex_seam_weld"
        and record.get("source_triangle_geometry_preserved") is True
        and record.get("simplification_applied") is False
    )


def _mix_optimizer_settings_key(settings: AppSettings) -> tuple[object, ...]:
    geometry = settings.geometry
    tone = settings.tone
    palette = settings.palette
    return (
        float(geometry.height_mm),
        int(geometry.target_faces) if geometry.adjust_face_count else None,
        int(geometry.preview_faces),
        geometry.up_axis.upper(),
        int(geometry.min_component_faces),
        bool(geometry.mirror_x),
        bool(geometry.preserve_parts),
        bool(geometry.solidify_parts),
        bool(geometry.repair_unmatched_boundaries),
        bool(geometry.auto_joints),
        float(geometry.joint_width_mm),
        float(geometry.joint_height_mm),
        float(geometry.joint_depth_mm),
        float(geometry.joint_clearance_mm),
        float(geometry.joint_min_seam_span_mm),
        bool(geometry.split_enabled),
        geometry.split_axis.upper(),
        float(geometry.split_position_percent),
        int(geometry.split_target_part),
        float(tone.black_point),
        float(tone.white_point),
        float(tone.gamma),
        float(tone.contrast),
        float(tone.saturation),
        bool(tone.pink_protection),
        float(tone.pink_threshold),
        bool(tone.smoothing),
        float(tone.smoothing_max_area_mm2),
        float(tone.smoothing_delta_e_slack),
        palette.material,
        tuple(str(value).upper() for value in palette.physical_hex),
        tuple(bool(value) for value in palette.enabled_states),
        tuple(int(value) for value in palette.mix_ratios_b),
        tuple(int(value) for value in palette.secondary_mix_ratios_b),
        (
            None
            if palette.output_mix_ratios_b is None
            else tuple(int(value) for value in palette.output_mix_ratios_b)
        ),
        bool(getattr(palette, "surface_shell_enabled", False)),
        bool(getattr(palette, "black_free_gradient_enabled", False)),
        int(getattr(palette, "black_free_black_slot", 0)),
        int(getattr(palette, "black_free_red_slot", 2)),
        int(getattr(palette, "black_free_brown_slot", 3)),
        tuple(
            (
                key,
                value.material,
                tuple(value.physical_hex),
                tuple(value.enabled_states),
                tuple(value.mix_ratios_b),
                tuple(value.secondary_mix_ratios_b),
                (
                    None
                    if value.output_mix_ratios_b is None
                    else tuple(
                        int(ratio) for ratio in value.output_mix_ratios_b
                    )
                ),
                bool(getattr(value, "surface_shell_enabled", False)),
                bool(getattr(value, "black_free_gradient_enabled", False)),
                int(getattr(value, "black_free_black_slot", 0)),
                int(getattr(value, "black_free_red_slot", 2)),
                int(getattr(value, "black_free_brown_slot", 3)),
            )
            for key, value in sorted(settings.part_palettes.items())
        ),
    )


def _manual_overrides_signature(
    overrides: np.ndarray | None,
) -> tuple[tuple[int, ...], str, bytes] | None:
    if overrides is None:
        return None
    values = np.ascontiguousarray(np.asarray(overrides))
    digest = hashlib.blake2b(values.tobytes(), digest_size=16).digest()
    return tuple(int(value) for value in values.shape), values.dtype.str, digest


def _enabled_manual_mix_states(
    overrides: np.ndarray | None,
    enabled_states: list[bool] | tuple[bool, ...],
) -> tuple[int, ...]:
    if overrides is None or len(enabled_states) != PALETTE_STATE_COUNT:
        return ()
    values = np.asarray(overrides)
    if values.ndim != 1:
        return ()
    return tuple(
        state
        for state in range(4, 10)
        if bool(enabled_states[state]) and bool(np.any(values == state))
    )


def _mix_optimization_preflight(
    settings: AppSettings,
) -> tuple[str, str] | None:
    enabled = tuple(bool(value) for value in settings.palette.enabled_states)
    if len(enabled) != PALETTE_STATE_COUNT:
        return (
            "パレット設定を確認してください",
            f"パレット有効状態は{PALETTE_STATE_COUNT}個必要です。",
        )
    if not any(enabled[4:10]):
        return "混色が無効です", "最適化する混色を少なくとも1色有効にしてください。"
    if not any(enabled[state] for state in NEUTRAL_PALETTE_STATES):
        return "通常色が必要です", "通常色パレットを少なくとも1色有効にしてください。"
    if settings.tone.pink_protection and not any(
        enabled[state] for state in PINK_PALETTE_STATES
    ):
        return (
            "F4系の色が必要です",
            "F4系保護を使う場合は、F4を含むパレットを少なくとも1色有効にしてください。",
        )
    return None


class MapperApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        smoke_test: bool = False,
        initial_project: Path | None = None,
    ) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1540x920")
        self.root.minsize(1180, 740)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.i18n = Translator(load_language())
        self.localizer = TkLocalizer(self.i18n)
        self.settings = _sanitize_public_settings(
            self._load_persistent_settings()
        )
        # r25 keeps laboratory implementations in source, but the public
        # application has no developer entrance.  Never restore a stale global
        # preference into an invisible active mode.
        self._developer_features_enabled_committed = False
        _enforce_black_free_gradient_developer_gate(self.settings, False)
        self.source_path: Path | None = None
        self.reference_path: Path | None = None
        self.reference_image: Image.Image | None = None
        self.asset = None
        self.prepared = None
        self.prepared_key: tuple[object, ...] | None = None
        self.preview_colors = None
        self.source_render: Image.Image | None = None
        self.target_render: Image.Image | None = None
        self.manual_overrides: np.ndarray | None = None
        self.manual_fingerprint: str | None = None
        self.pending_manual_payload: dict[str, object] | None = None
        self.manual_part_partition: dict[str, object] | None = None
        self.pending_manual_part_partition: dict[str, object] | None = None
        self.manual_joint_record: dict[str, object] | None = None
        self.pending_manual_joint_record: dict[str, object] | None = None
        self.paint_editor: PaintEditorWindow | None = None
        self.filament_candidate_window: FilamentCandidateWindow | None = None
        self.help_center: HelpCenterWindow | None = None
        self._open_boundary_diagnostics_on_paint = False
        self._manual_high_face_warning_key: tuple[object, ...] | None = None
        self.app_closing = False
        self.sample_rgb: tuple[int, int, int] | None = None
        self.recipes: list[MixRecipeCandidate] = []
        self.active_part_key: str | None = None
        self.part_label_to_key: dict[str, str | None] = {
            self.i18n.text("parts.common"): None
        }
        self.part_recommendations: dict[str, FilamentRecommendation] = {}
        self._loading_palette_variables = False
        self._auto_recommend_after_geometry = False
        # A project whose source model moved can be opened before the user
        # locates the mesh again.  The next explicit model selection then
        # restores that project instead of starting a new model.
        self._project_obj_recovery_pending = False
        self.last_mix_ratios: list[int] | None = None
        self.last_mix_target_key: str | None = None
        self._mix_input_generation = 0
        self._applying_mix_result = False
        self.eyedropper_active = False
        self.physical_eyedropper_target: int | None = None
        self.reference_mapping: tuple[int, int, int, int, int, int] | None = None
        self.canvas_images: list[ImageTk.PhotoImage] = []

        self.work_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.main_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="geometry")
        self.preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
        self.preview_future: Future | None = None
        self.preview_generation = 0
        self.preview_after_id: str | None = None
        self.canvas_after_id: str | None = None
        self.busy = False

        self._configure_style()
        self._load_brand_assets()
        self._create_variables()
        self._build_ui()
        self.localizer.capture(self.root)
        self.localizer.apply()
        # "Language" also appears as the English translation of the ordinary
        # language-label key, so generic text capture cannot disambiguate the
        # intentional opposite-language affordance on first construction.
        self.language_label.configure(
            text=self.i18n.text("toolbar.language_opposite")
        )
        self._settings_to_variables()
        self._attach_traces()
        self._refresh_palette_widgets(schedule_preview=False)
        self._draw_comparison_canvas()
        self.poll_after_id: str | None = self.root.after(80, self._poll_queue)
        if smoke_test:
            self.root.withdraw()
            self.root.after(700, self._on_close)
        elif initial_project is not None:
            self.root.after(180, lambda: self._load_project_path(initial_project))

    @property
    def source_path(self) -> Path | None:
        """Generic model path with the historical ``obj_path`` kept as alias."""

        return getattr(self, "obj_path", None)

    @source_path.setter
    def source_path(self, value: Path | str | None) -> None:
        self.obj_path = None if value is None else Path(value)

    def _source_display_text(self, path: Path | None = None) -> str:
        selected = self.source_path if path is None else Path(path)
        if selected is None:
            return self.i18n.text("state.obj_none")
        return self.i18n.text("state.source_selected", name=selected.name)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, font=("Yu Gothic UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel2.TFrame", background=PANEL_2)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Panel2.TLabel", background=PANEL_2, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Panel2Muted.TLabel", background=PANEL_2, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Yu Gothic UI", 16, "bold"))
        style.configure(
            "BrandTagline.TLabel",
            background=BG,
            foreground=MUTED,
            font=("Yu Gothic UI", 8),
        )
        style.configure("Accent.TButton", background="#1479A8", foreground="white", padding=(14, 8))
        style.map("Accent.TButton", background=[("active", "#198FC5"), ("disabled", "#34404D")])
        style.configure("Export.TButton", background="#1F9D68", foreground="white", padding=(18, 10), font=("Yu Gothic UI", 11, "bold"))
        style.map("Export.TButton", background=[("active", "#27B779"), ("disabled", "#34404D")])
        style.configure("TButton", background=PANEL_2, foreground=TEXT, padding=(9, 6))
        style.map("TButton", background=[("active", "#2A3748")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_2, foreground=MUTED, padding=(14, 8))
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", TEXT)])
        style.configure("TLabelframe", background=PANEL, foreground=TEXT, bordercolor="#334055")
        style.configure("TLabelframe.Label", background=PANEL, foreground=TEXT, font=("Yu Gothic UI", 10, "bold"))
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("Panel2.TCheckbutton", background=PANEL_2, foreground=TEXT)
        style.map("Panel2.TCheckbutton", background=[("active", PANEL_2)])
        style.configure("Panel2.TRadiobutton", background=PANEL_2, foreground=TEXT)
        style.map(
            "Panel2.TRadiobutton",
            background=[("active", PANEL_2)],
            foreground=[("disabled", MUTED), ("!disabled", TEXT)],
        )
        style.configure("TEntry", fieldbackground="#0E131A", foreground=TEXT, insertcolor=TEXT)
        # Keep every readonly dropdown legible on the dark UI.  Windows themes
        # otherwise replace the field with a pale/disabled-looking surface and
        # low-contrast text, which was especially visible in the language and
        # up-axis selectors.
        combo_bg = "#182638"
        combo_focus_bg = "#203A54"
        combo_disabled_bg = "#273341"
        combo_text = "#FFFFFF"
        combo_disabled_text = "#D5DCE5"
        style.configure(
            "HighContrast.TCombobox",
            fieldbackground=combo_bg,
            background=combo_bg,
            foreground=combo_text,
            arrowcolor=combo_text,
            bordercolor="#6C839F",
            lightcolor="#6C839F",
            darkcolor="#6C839F",
            selectbackground="#1B668A",
            selectforeground=combo_text,
            padding=(5, 3),
        )
        style.map(
            "HighContrast.TCombobox",
            fieldbackground=[
                ("disabled", combo_disabled_bg),
                ("focus", combo_focus_bg),
                ("readonly", combo_bg),
            ],
            background=[
                ("disabled", combo_disabled_bg),
                ("focus", combo_focus_bg),
                ("readonly", combo_bg),
            ],
            foreground=[
                ("disabled", combo_disabled_text),
                ("readonly", combo_text),
            ],
            arrowcolor=[
                ("disabled", combo_disabled_text),
                ("readonly", combo_text),
            ],
            bordercolor=[("focus", ACCENT), ("readonly", "#6C839F")],
            selectbackground=[("readonly", "#1B668A")],
            selectforeground=[("readonly", combo_text)],
        )
        # The dropdown list itself is a classic Tk Listbox on Windows and is
        # not controlled by ttk style maps.
        self.root.option_add("*TCombobox*Listbox.background", combo_bg)
        self.root.option_add("*TCombobox*Listbox.foreground", combo_text)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#1B668A")
        self.root.option_add("*TCombobox*Listbox.selectForeground", combo_text)
        style.configure(
            "TSpinbox",
            fieldbackground="#0E131A",
            foreground=TEXT,
            insertcolor=TEXT,
            arrowcolor=TEXT,
        )
        style.configure("Treeview", background="#10161F", fieldbackground="#10161F", foreground=TEXT, rowheight=27)
        style.configure("Treeview.Heading", background=PANEL_2, foreground=TEXT)
        style.map("Treeview", background=[("selected", "#1B668A")])
        style.configure("Horizontal.TProgressbar", troughcolor="#222B38", background=ACCENT)

    def _load_brand_assets(self) -> None:
        """Load the established app mark for the title bar and main toolbar.

        The PNG is bundled beside the offline mixer model in frozen builds.
        Keep the PhotoImage objects on the application instance so Tk cannot
        collect them while the window is alive.  A missing/corrupt resource is
        deliberately non-fatal: the toolbar falls back to its text title.
        """

        self.brand_logo_image: ImageTk.PhotoImage | None = None
        self.window_icon_image: ImageTk.PhotoImage | None = None
        try:
            with Image.open(resource_path("assets/obj_adjuster_icon.png")) as image:
                source = ImageOps.exif_transpose(image).convert("RGBA")
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                toolbar_icon = ImageOps.contain(
                    source,
                    (32, 32),
                    method=resampling,
                )
                window_icon = ImageOps.contain(
                    source,
                    (64, 64),
                    method=resampling,
                )
            self.brand_logo_image = ImageTk.PhotoImage(
                toolbar_icon,
                master=self.root,
            )
            self.window_icon_image = ImageTk.PhotoImage(
                window_icon,
                master=self.root,
            )
        except (OSError, ValueError, tk.TclError):
            return

        try:
            self.root.iconphoto(True, self.window_icon_image)
        except tk.TclError:
            # Some window managers do not accept iconphoto.  The same loaded
            # mark can still be shown safely in the toolbar.
            self.window_icon_image = None

    def _create_variables(self) -> None:
        tr = self.i18n.text
        self.language_var = tk.StringVar(
            value=LANGUAGE_DISPLAY_NAMES[self.i18n.language]
        )
        self.physical_vars = [tk.StringVar() for _ in range(4)]
        self.material_var = tk.StringVar(value=MATERIAL_PLA)
        self.enabled_vars = [tk.BooleanVar() for _ in range(PALETTE_STATE_COUNT)]
        self.palette_state_count_var = tk.IntVar(value=16)
        self.extended_palette_var = tk.BooleanVar(value=True)
        self.mix_ratio_vars = [tk.IntVar() for _ in range(6)]
        self.secondary_mix_ratio_vars = [tk.IntVar() for _ in range(6)]
        self.black_free_gradient_enabled_var = tk.BooleanVar(value=False)
        self.black_free_black_slot_var = tk.StringVar(value=PHYSICAL_NAMES[0])
        self.black_free_red_slot_var = tk.StringVar(value=PHYSICAL_NAMES[2])
        self.black_free_brown_slot_var = tk.StringVar(value=PHYSICAL_NAMES[3])
        self.black_free_gradient_summary_var = tk.StringVar(
            value=tr("palette.black_free_off_summary")
        )
        self.black_output_enabled_var = tk.BooleanVar(value=False)
        self.black_output_slot_var = tk.StringVar(value=PHYSICAL_NAMES[0])
        self.black_output_summary_var = tk.StringVar(
            value=tr("palette.black_output_off_summary")
        )
        self.black_output_warning_var = tk.StringVar(value="")
        self.surface_shell_enabled_var = tk.BooleanVar(value=False)
        self.surface_shell_summary_var = tk.StringVar(
            value=tr("palette.surface_shell_unavailable_summary")
        )
        self.developer_features_enabled_var = tk.BooleanVar(
            value=self._developer_features_enabled_committed
        )
        self.color_depth_enabled_var = tk.BooleanVar(value=False)
        self.color_depth_outer_thickness_var = tk.DoubleVar(value=0.15)
        # Compatibility alias for headless r20 GUI tests/hotfixes.  The r21
        # visible control and export path use the ColorDepth name exclusively.
        self.radial_skin_thickness_var = self.color_depth_outer_thickness_var
        self.height_var = tk.DoubleVar()
        self.target_faces_var = tk.IntVar()
        self.preview_faces_var = tk.IntVar()
        self.adjust_face_count_var = tk.BooleanVar(value=True)
        self.face_count_status_var = tk.StringVar()
        self.up_axis_var = tk.StringVar()
        self.min_component_var = tk.IntVar()
        self.mirror_var = tk.BooleanVar()
        self.preserve_parts_var = tk.BooleanVar(value=True)
        self.solidify_parts_var = tk.BooleanVar(value=False)
        self.repair_unmatched_boundaries_var = tk.BooleanVar(value=False)
        self.auto_joints_var = tk.BooleanVar(value=False)
        self.joint_width_var = tk.DoubleVar(value=6.0)
        self.joint_height_var = tk.DoubleVar(value=4.0)
        self.joint_depth_var = tk.DoubleVar(value=6.0)
        self.joint_clearance_var = tk.DoubleVar(value=0.25)
        self.joint_min_span_var = tk.DoubleVar(value=8.0)
        self.split_enabled_var = tk.BooleanVar(value=False)
        self.split_axis_var = tk.StringVar(value="Z")
        self.split_position_var = tk.DoubleVar(value=50.0)
        self.split_target_part_var = tk.IntVar(value=1)
        self.export_individual_parts_var = tk.BooleanVar(value=True)
        self.black_point_var = tk.DoubleVar()
        self.white_point_var = tk.DoubleVar()
        self.gamma_var = tk.DoubleVar()
        self.contrast_var = tk.DoubleVar()
        self.saturation_var = tk.DoubleVar()
        self.pink_protection_var = tk.BooleanVar()
        self.pink_threshold_var = tk.DoubleVar()
        self.smoothing_var = tk.BooleanVar()
        self.smoothing_area_var = tk.DoubleVar()
        self.smoothing_slack_var = tk.DoubleVar()
        self.include_obj_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value=tr("state.select_inputs"))
        self.obj_name_var = tk.StringVar(value=tr("state.obj_none"))
        self.ref_name_var = tk.StringVar(value=tr("state.reference_none"))
        self.sample_hex_var = tk.StringVar(value=tr("state.not_sampled"))
        self.part_target_var = tk.StringVar(value=tr("parts.common"))
        self.part_name_var = tk.StringVar(value="")
        self.main_active_part_var = tk.StringVar(value="")
        self.recipe_panel_visible_var = tk.BooleanVar(value=False)
        self.part_status_var = tk.StringVar(
            value=tr("state.parts_hint")
        )
        self.assembly_status_var = tk.StringVar(
            value=tr("assembly.status_no_model")
        )
        self.recommendation_var = tk.StringVar(
            value=tr("state.recommend_hint")
        )

    def _build_ui(self) -> None:
        self.toolbar = ttk.Frame(self.root, padding=(12, 10))
        toolbar = self.toolbar
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(9, weight=1)
        self.brand_identity_frame = ttk.Frame(toolbar, takefocus=False)
        self.brand_identity_frame.grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 18),
        )
        self.brand_logo_label: ttk.Label | None = None
        if self.brand_logo_image is not None:
            self.brand_logo_label = ttk.Label(
                self.brand_identity_frame,
                image=self.brand_logo_image,
                takefocus=False,
            )
            self.brand_logo_label.grid(row=0, column=0, padx=(0, 8))
        self.brand_title_label = ttk.Label(
            self.brand_identity_frame,
            text=APP_NAME,
            style="Title.TLabel",
            takefocus=False,
        )
        self.brand_title_label.grid(row=0, column=1, sticky="sw")
        self.brand_tagline_label = ttk.Label(
            self.brand_identity_frame,
            text=APP_TAGLINE,
            style="BrandTagline.TLabel",
            takefocus=False,
        )
        self.brand_tagline_label.grid(row=1, column=1, sticky="nw")
        if self.brand_logo_label is not None:
            self.brand_logo_label.grid_configure(rowspan=2)
        self.open_source_button = ttk.Button(
            toolbar,
            text=self.i18n.text("toolbar.open_obj"),
            command=self._choose_obj,
            style="Accent.TButton",
        )
        self.open_source_button.grid(row=0, column=1, padx=3)
        ttk.Button(toolbar, text="元画像を開く", command=self._choose_reference).grid(row=0, column=2, padx=3)
        ttk.Button(toolbar, text="プロジェクト保存", command=self._save_project).grid(row=0, column=3, padx=3)
        self.project_load_button = ttk.Menubutton(
            toolbar,
            text=self.i18n.text("toolbar.load_project"),
        )
        self.project_load_menu = tk.Menu(
            self.project_load_button,
            tearoff=False,
            background=PANEL_2,
            foreground=TEXT,
            activebackground=ACCENT,
            activeforeground="white",
        )
        self.project_load_menu.add_command(
            label=self.i18n.text("project.menu_open_folder"),
            command=self._load_project,
        )
        self.project_load_menu.add_separator()
        self.project_load_menu.add_command(
            label=self.i18n.text("project.menu_open_legacy_json"),
            command=self._load_legacy_project,
        )
        self.project_load_button.configure(menu=self.project_load_menu)
        self.project_load_button.grid(row=0, column=4, padx=3)
        self.manual_edit_button = ttk.Button(
            toolbar,
            text="マニュアル修正",
            command=self._open_paint_editor,
            style="Accent.TButton",
        )
        self.manual_edit_button.grid(row=0, column=5, padx=(12, 3))
        self.help_button = ttk.Button(
            toolbar,
            text=self.i18n.text("toolbar.help"),
            command=lambda: self._show_help_center("first_steps"),
        )
        # Help Center remains available in source for internal builds.  The
        # public toolbar intentionally exposes only the primary workflow.
        self.language_label = ttk.Label(
            toolbar,
            text=self.i18n.text("toolbar.language_opposite"),
            style="Muted.TLabel",
        )
        self.language_label.grid(
            row=0, column=7, sticky="e", padx=(4, 4)
        )
        self.language_selector = ttk.Combobox(
            toolbar,
            textvariable=self.language_var,
            values=tuple(LANGUAGE_DISPLAY_NAMES.values()),
            state="readonly",
            width=9,
            style="HighContrast.TCombobox",
        )
        self.language_selector.grid(row=0, column=8, sticky="e")
        self.language_selector.bind(
            "<<ComboboxSelected>>", self._on_language_selected
        )
        ttk.Label(toolbar, textvariable=self.obj_name_var, style="Muted.TLabel").grid(row=0, column=9, sticky="e", padx=8)

        self.main_ribbon = ttk.Frame(self.root, style="Panel.TFrame")
        self.main_ribbon.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 7))
        self._build_controls(self.main_ribbon)

        self.preview_frame = ttk.Frame(self.root)
        self.preview_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self._build_preview(self.preview_frame)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        self.footer = ttk.Frame(self.root, padding=(12, 8))
        footer = self.footer
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100, length=180)
        self.progress.grid(row=0, column=0, padx=(0, 12))
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        self.export_button = ttk.Button(footer, text="3MFを書き出す", command=self._export, style="Export.TButton")
        self.export_button.grid(row=0, column=2, padx=(12, 0))

    def _on_language_selected(self, _event=None) -> None:
        self.set_language(language_from_display_name(self.language_var.get()))

    def set_language(self, language: str, *, persist: bool = True) -> None:
        """Switch every registered UI surface without recreating live widgets."""

        runtime_variables = (
            self.status_var,
            self.obj_name_var,
            self.ref_name_var,
            self.sample_hex_var,
            self.part_status_var,
            self.recommendation_var,
            self.assembly_status_var,
        )
        previous_values = tuple(variable.get() for variable in runtime_variables)
        self.i18n.set_language(language)
        self.language_var.set(LANGUAGE_DISPLAY_NAMES[self.i18n.language])
        self.localizer.apply()
        self._refresh_project_load_menu_labels()
        self.open_source_button.configure(
            text=self.i18n.text("toolbar.open_obj")
        )
        self.language_label.configure(
            text=self.i18n.text("toolbar.language_opposite")
        )
        self._refresh_main_ribbon_labels()
        self._set_recipe_panel_visible(self.recipe_panel_visible_var.get())
        for variable, previous in zip(
            runtime_variables, previous_values, strict=True
        ):
            variable.set(self.i18n.translate_known(previous))
        if self.source_path is not None:
            self.obj_name_var.set(self._source_display_text())
        self.eyedropper_button.configure(
            text=self.i18n.text(
                "palette.eyedropper_stop"
                if self.eyedropper_active
                else "palette.eyedropper_start"
            )
        )
        for index, button in enumerate(
            getattr(self, "physical_eyedropper_buttons", ())
        ):
            button.configure(
                text=self.i18n.text(
                    "palette.set_base_short"
                )
            )
        direct_target = getattr(self, "physical_eyedropper_target", None)
        if self.eyedropper_active and direct_target is not None:
            self.status_var.set(
                self.i18n.text(
                    "palette.pick_base_status",
                    slot=PHYSICAL_NAMES[int(direct_target)],
                )
            )
        self._refresh_part_selector()
        self._sync_main_active_part_label()
        self._update_assembly_status()
        self._draw_comparison_canvas()
        if self.paint_editor is not None:
            try:
                self.paint_editor.set_language(self.i18n.language)
            except (AttributeError, tk.TclError):
                pass
        if self.filament_candidate_window is not None:
            try:
                self.filament_candidate_window.set_language()
            except (AttributeError, tk.TclError):
                pass
        if self.help_center is not None:
            try:
                self.help_center.set_translator(self.i18n)
            except (AttributeError, tk.TclError):
                pass
        if persist:
            try:
                save_language(self.i18n.language)
            except OSError:
                # A read-only profile must not make the UI switch fail.
                pass

    def _refresh_project_load_menu_labels(self) -> None:
        """Keep the native project menu synchronized with live language."""

        button = getattr(self, "project_load_button", None)
        menu = getattr(self, "project_load_menu", None)
        if button is not None:
            button.configure(text=self.i18n.text("toolbar.load_project"))
        if menu is not None:
            menu.entryconfigure(
                0, label=self.i18n.text("project.menu_open_folder")
            )
            menu.entryconfigure(
                2, label=self.i18n.text("project.menu_open_legacy_json")
            )

    def tr(self, key: str, /, **values: object) -> str:
        """Public translation hook for feature tabs added by later versions."""

        return self.i18n.text(key, **values)

    def _build_controls(self, parent: ttk.Frame) -> None:
        """Build the two-page, collapsible main ribbon.

        Stateful widgets keep their established public attributes.  Only their
        parents and grid positions change, so palette traces, hotfix adapters,
        project persistence, and export behavior continue to use the same
        control objects as before.
        """

        parent.columnconfigure(0, weight=1)
        self._main_ribbon_selected = "filament"
        self._main_ribbon_expanded = True

        self.main_ribbon_tab_bar = tk.Frame(
            parent,
            bg="#111722",
            padx=8,
            pady=3,
            highlightthickness=1,
            highlightbackground="#2B394B",
        )
        self.main_ribbon_tab_bar.grid(row=0, column=0, sticky="ew")
        self.main_ribbon_tab_bar.columnconfigure(2, weight=1)
        self.main_ribbon_tab_buttons: dict[str, tk.Button] = {}
        for column, page_name in enumerate(("filament", "output")):
            button = tk.Button(
                self.main_ribbon_tab_bar,
                command=lambda name=page_name: self._on_main_ribbon_tab_clicked(name),
                bg="#111722",
                fg=MUTED,
                activebackground="#24445C",
                activeforeground="#FFFFFF",
                relief=tk.FLAT,
                bd=0,
                padx=19,
                pady=6,
                font=("Yu Gothic UI", 10, "bold"),
                cursor="hand2",
            )
            button.grid(row=0, column=column, padx=1)
            self.main_ribbon_tab_buttons[page_name] = button

        self.main_ribbon_help_button = ttk.Button(
            self.main_ribbon_tab_bar,
            text="?",
            width=3,
            command=self._show_context_help,
            takefocus=True,
        )

        self.main_ribbon_toggle_button = ttk.Button(
            self.main_ribbon_tab_bar,
            command=self._toggle_main_ribbon,
            width=18,
        )
        self.main_ribbon_toggle_button.grid(
            row=0, column=3, padx=(8, 0), sticky="e"
        )

        self.main_ribbon_body = ttk.Frame(
            parent,
            style="Panel.TFrame",
            padding=(8, 7),
        )
        self.main_ribbon_body.grid(row=1, column=0, sticky="ew")
        self.main_ribbon_body.columnconfigure(0, weight=1)
        self.main_ribbon_pages: dict[str, ttk.Frame] = {}
        for name in ("filament", "output"):
            page = ttk.Frame(self.main_ribbon_body, style="Panel.TFrame")
            page.grid(row=0, column=0, sticky="ew")
            page.grid_remove()
            self.main_ribbon_pages[name] = page

        filament_page = self.main_ribbon_pages["filament"]
        self.filament_settings_page = filament_page
        filament_page.columnconfigure(0, weight=4, minsize=350)
        filament_page.columnconfigure(1, weight=7, minsize=650)
        parts_group = ttk.LabelFrame(
            filament_page,
            text=self.i18n.text("main.group_parts"),
            padding=(8, 6),
        )
        parts_group.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        palette_group = ttk.Frame(filament_page, style="Panel.TFrame")
        palette_group.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self._build_parts_tab(parts_group)
        self._build_palette_tab(palette_group)

        output_page = self.main_ribbon_pages["output"]
        self.output_settings_page = output_page
        output_page.columnconfigure(0, weight=4, minsize=380)
        output_page.columnconfigure(1, weight=7, minsize=620)
        geometry_group = ttk.LabelFrame(
            output_page,
            text=self.i18n.text("main.group_geometry"),
            padding=(10, 7),
        )
        geometry_group.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        assembly_group = ttk.LabelFrame(
            output_page,
            text=self.i18n.text("main.group_assembly"),
            padding=(10, 7),
        )
        assembly_group.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self._build_geometry_tab(geometry_group)
        self._build_assembly_tab(assembly_group)

        # Tone controls now belong to Manual Editing.  The optimizer logic is
        # intentionally retained in MapperApp, and several legacy code paths
        # update this button's state before that editor exists.  Keep one
        # un-managed compatibility button so those paths remain safe without
        # exposing the old Shading tab on the main screen.
        self._tone_compatibility_host = ttk.Frame(parent)
        self.undo_mix_button = ttk.Button(
            self._tone_compatibility_host,
            text=self.i18n.text("tone.undo_optimize"),
            command=self._undo_mix_optimization,
            state="disabled",
        )

        self._refresh_main_ribbon_labels()
        self._apply_main_ribbon_state()

    def _main_ribbon_label(self, page_name: str) -> str:
        key = {
            "filament": "main.ribbon_filament",
            "output": "main.ribbon_output",
        }.get(page_name)
        return self.i18n.text(key) if key is not None else page_name

    def _refresh_main_ribbon_labels(self) -> None:
        buttons = getattr(self, "main_ribbon_tab_buttons", {})
        for name, button in buttons.items():
            button.configure(text=self._main_ribbon_label(name))
        material = getattr(self, "material_var", None)
        if material is not None:
            self._refresh_material_mode_buttons(material.get())
        warning_button = getattr(self, "filament_job_warning_button", None)
        if warning_button is not None:
            warning_button.configure(text=self.i18n.text("main.filament_job_help"))
        extended_palette = getattr(self, "extended_palette_checkbutton", None)
        if extended_palette is not None:
            extended_palette.configure(text=self.i18n.text("palette.extended_short"))
        state_count_label = getattr(self, "palette_state_count_label", None)
        if state_count_label is not None:
            state_count_label.configure(text=self.i18n.text("palette.state_count"))
        reprocess_geometry = getattr(self, "reprocess_geometry_button", None)
        if reprocess_geometry is not None:
            reprocess_geometry.configure(text=self.i18n.text("geometry.reprocess"))
        close_parts = getattr(self, "close_parts_safely_button", None)
        if close_parts is not None:
            close_parts.configure(
                text=self.i18n.text("assembly.close_safely")
            )
        if hasattr(self, "face_count_status_var"):
            self._update_face_count_status()
        candidate_button = getattr(self, "filament_candidate_button", None)
        if candidate_button is not None:
            candidate_button.configure(
                text=self.i18n.text("filament_candidates.button")
            )
        calibration_button = getattr(self, "calibration_chart_button", None)
        if calibration_button is not None:
            calibration_button.configure(
                text=self.i18n.text("palette.calibration_export")
            )
        calibration_help = getattr(self, "calibration_chart_help_label", None)
        if calibration_help is not None:
            calibration_help.configure(
                text=self.i18n.text("palette.calibration_help")
            )
        black_free_group = getattr(self, "black_free_gradient_group", None)
        if black_free_group is not None:
            black_free_group.configure(
                text=self.i18n.text("palette.black_free_group")
            )
        black_free_enable = getattr(
            self, "black_free_gradient_enable_checkbutton", None
        )
        if black_free_enable is not None:
            black_free_enable.configure(
                text=self.i18n.text("palette.black_free_enable")
            )
        for attribute, key in (
            ("black_free_black_slot_label", "palette.black_free_black_slot"),
            ("black_free_red_slot_label", "palette.black_free_red_slot"),
            ("black_free_brown_slot_label", "palette.black_free_brown_slot"),
        ):
            label = getattr(self, attribute, None)
            if label is not None:
                label.configure(text=self.i18n.text(key))
        black_free_help = getattr(self, "black_free_gradient_help_label", None)
        if black_free_help is not None:
            black_free_help.configure(
                text=self.i18n.text("palette.black_free_help")
            )
        self._refresh_black_free_gradient_widgets()
        black_output_group = getattr(self, "black_output_group", None)
        if black_output_group is not None:
            black_output_group.configure(
                text=self.i18n.text("palette.black_output_group")
            )
        black_output_enable = getattr(
            self, "black_output_enable_checkbutton", None
        )
        if black_output_enable is not None:
            black_output_enable.configure(
                text=self.i18n.text("palette.black_output_enable")
            )
        black_output_slot_label = getattr(
            self, "black_output_slot_label", None
        )
        if black_output_slot_label is not None:
            black_output_slot_label.configure(
                text=self.i18n.text("palette.black_output_slot")
            )
        black_output_preset = getattr(
            self, "black_output_preset_button", None
        )
        if black_output_preset is not None:
            black_output_preset.configure(
                text=self.i18n.text("palette.black_output_preset")
            )
        self._refresh_black_output_widgets()
        surface_shell_group = getattr(self, "surface_shell_group", None)
        if surface_shell_group is not None:
            surface_shell_group.configure(
                text=self.i18n.text("palette.surface_shell_unavailable_group")
            )
        surface_shell_enable = getattr(
            self, "surface_shell_enable_checkbutton", None
        )
        if surface_shell_enable is not None:
            surface_shell_enable.configure(
                text=self.i18n.text("palette.surface_shell_unavailable_label")
            )
        surface_shell_help = getattr(self, "surface_shell_help_label", None)
        if surface_shell_help is not None:
            surface_shell_help.configure(
                text=self.i18n.text("palette.surface_shell_unavailable_help")
            )
        self._refresh_surface_shell_widgets()
        developer_features = getattr(
            self, "developer_features_enable_checkbutton", None
        )
        if developer_features is not None:
            developer_features.configure(
                text=self.i18n.text("developer_features.show")
            )
        color_depth_group = getattr(self, "color_depth_group", None)
        if color_depth_group is not None:
            color_depth_group.configure(
                text=self.i18n.text("color_depth.group")
            )
        color_depth_enable = getattr(
            self, "color_depth_enable_checkbutton", None
        )
        if color_depth_enable is not None:
            color_depth_enable.configure(
                text=self.i18n.text("color_depth.enable")
            )
        color_depth_thickness_label = getattr(
            self, "color_depth_thickness_label", None
        )
        if color_depth_thickness_label is not None:
            color_depth_thickness_label.configure(
                text=self.i18n.text("color_depth.outer_thickness")
            )
        color_depth_button = getattr(
            self, "color_depth_export_button", None
        )
        if color_depth_button is not None:
            color_depth_button.configure(
                text=self.i18n.text("color_depth.export")
            )
        color_depth_part_3mf_button = getattr(
            self, "color_depth_part_3mf_button", None
        )
        if color_depth_part_3mf_button is not None:
            color_depth_part_3mf_button.configure(
                text=self.i18n.text("color_depth.convert_part_3mf")
            )
        color_depth_help = getattr(self, "color_depth_help_label", None)
        if color_depth_help is not None:
            color_depth_help.configure(
                text=self.i18n.text("color_depth.help")
            )
        self._refresh_developer_feature_visibility()
        self._refresh_color_depth_widgets()
        toggle = getattr(self, "main_ribbon_toggle_button", None)
        if toggle is not None:
            toggle.configure(
                text=self.i18n.text(
                    "main.ribbon_collapse"
                    if self._main_ribbon_expanded
                    else "main.ribbon_expand"
                )
            )

    def _apply_main_ribbon_state(self) -> None:
        for name, page in self.main_ribbon_pages.items():
            if self._main_ribbon_expanded and name == self._main_ribbon_selected:
                page.grid()
            else:
                page.grid_remove()
        if self._main_ribbon_expanded:
            self.main_ribbon_body.grid()
        else:
            self.main_ribbon_body.grid_remove()
        for name, button in self.main_ribbon_tab_buttons.items():
            selected = name == self._main_ribbon_selected
            button.configure(
                bg="#1B668A" if selected else "#111722",
                fg="#FFFFFF" if selected else MUTED,
            )
        self._refresh_main_ribbon_labels()

    def _on_main_ribbon_tab_clicked(self, page_name: str) -> None:
        if page_name not in self.main_ribbon_pages:
            return
        if page_name == self._main_ribbon_selected and self._main_ribbon_expanded:
            self._main_ribbon_expanded = False
        else:
            self._main_ribbon_selected = page_name
            self._main_ribbon_expanded = True
        self._apply_main_ribbon_state()

    def _toggle_main_ribbon(self) -> None:
        self._main_ribbon_expanded = not self._main_ribbon_expanded
        self._apply_main_ribbon_state()

    def _help_actions(self) -> dict[str, object]:
        """Return Help Center actions backed by the existing guarded flows."""

        return {
            "open_obj": self._choose_obj,
            "select_filament": self._show_filament_settings,
            "open_manual": self._open_paint_editor,
            "export": self._export,
        }

    def _show_help_center(self, topic_id: str = "first_steps") -> HelpCenterWindow:
        """Show the application's single non-modal Help Center."""

        self.help_center = get_help_center(
            self.root,
            self.i18n,
            actions=self._help_actions(),
        )
        self.help_center.show(topic_id)
        return self.help_center

    def _on_help_shortcut(self, _event=None) -> str:
        self._show_help_center("first_steps")
        return "break"

    def _show_context_help(self) -> None:
        topic_id = (
            "parts_palette"
            if self._main_ribbon_selected == "filament"
            else "export_3mf"
        )
        self._show_help_center(topic_id)

    def _show_filament_settings(self) -> None:
        self._main_ribbon_selected = "filament"
        self._main_ribbon_expanded = True
        self._apply_main_ribbon_state()

    def _build_parts_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(0, weight=3, minsize=305)
        tab.columnconfigure(1, weight=2, minsize=205)

        selection = ttk.Frame(tab, style="Panel.TFrame")
        selection.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        selection.columnconfigure(0, weight=1)
        self.part_tree = ttk.Treeview(
            selection,
            columns=("faces", "palette", "filaments"),
            show="tree headings",
            height=4,
            selectmode="browse",
        )
        self.part_tree.heading("#0", text="パーツ")
        self.part_tree.heading("faces", text="面数")
        self.part_tree.heading("palette", text="設定")
        self.part_tree.heading("filaments", text="基本4色")
        self.part_tree.column("#0", width=105, minwidth=80, anchor="w")
        self.part_tree.column("faces", width=55, minwidth=45, anchor="e")
        self.part_tree.column("palette", width=48, minwidth=42, anchor="center")
        self.part_tree.column("filaments", width=130, minwidth=90, anchor="w")
        self.part_tree.grid(row=0, column=0, sticky="nsew")
        self.part_tree.bind("<<TreeviewSelect>>", self._on_part_tree_selected)

        target = ttk.Frame(selection, style="Panel.TFrame")
        target.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        target.columnconfigure(1, weight=1)
        ttk.Label(target, text="編集対象", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 7)
        )
        self.part_selector = ttk.Combobox(
            target,
            textvariable=self.part_target_var,
            values=(self.i18n.text("parts.common"),),
            state="readonly",
            style="HighContrast.TCombobox",
        )
        self.part_selector.grid(row=0, column=1, sticky="ew")
        self.part_selector.bind("<<ComboboxSelected>>", self._on_part_selected)
        ttk.Label(
            target,
            text=self.i18n.text("paint.part_name"),
            style="Panel.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=(0, 7), pady=(5, 0))
        self.main_part_name_entry = ttk.Entry(
            target,
            textvariable=self.part_name_var,
            state="disabled",
        )
        self.main_part_name_entry.grid(
            row=1, column=1, sticky="ew", pady=(5, 0)
        )
        self.main_part_name_entry.bind(
            "<Return>", lambda _event: self._rename_selected_part()
        )
        self.main_part_rename_button = ttk.Button(
            target,
            text=self.i18n.text("paint.rename_part"),
            command=self._rename_selected_part,
            state="disabled",
        )
        self.main_part_rename_button.grid(
            row=1, column=2, padx=(5, 0), pady=(5, 0)
        )

        guidance = ttk.Frame(tab, style="Panel.TFrame")
        guidance.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        guidance.columnconfigure(0, weight=1)
        ttk.Label(
            guidance,
            textvariable=self.part_status_var,
            style="PanelMuted.TLabel",
            wraplength=225,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))

        actions = ttk.Frame(guidance, style="Panel.TFrame")
        actions.grid(row=1, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(
            actions,
            text="選択パーツを自動提案",
            command=self._recommend_selected_part,
            style="Accent.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=2)
        ttk.Button(
            actions,
            text="全パーツを自動提案",
            command=self._recommend_all_parts,
            style="Accent.TButton",
        ).grid(row=0, column=1, sticky="ew", padx=(2, 0), pady=2)
        ttk.Button(
            actions,
            text="現在の4色を全パーツへコピー",
            command=self._copy_palette_to_all_parts,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(
            actions,
            text="選択パーツを全体共通設定へ戻す",
            command=self._clear_selected_part_palette,
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
        self.recommendation_label = ttk.Label(
            guidance,
            textvariable=self.recommendation_var,
            style="Panel.TLabel",
            wraplength=225,
            justify="left",
        )
        self.filament_job_warning_button = ttk.Button(
            guidance,
            text=self.i18n.text("main.filament_job_help"),
            command=self._show_filament_job_warning,
        )

    def _show_filament_job_warning(self) -> None:
        messagebox.showinfo(
            self.i18n.text("tab.parts"),
            self.i18n.text("parts.u1_warning"),
            parent=self.root,
        )

    def _build_palette_tab(self, tab: ttk.Frame) -> None:
        # Keep the base-filament chooser narrow and give the family strips the
        # space they need.  The previous equal-height laboratory stacks made
        # this ribbon consume most of the preview on a 1080p display.
        tab.columnconfigure(0, weight=0, minsize=330)
        tab.columnconfigure(1, weight=1, minsize=520)

        physical = ttk.LabelFrame(
            tab,
            text=self.i18n.text("palette.base_group"),
            padding=(6, 4),
        )
        physical.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        physical.columnconfigure(3, weight=1)

        material_bar = ttk.Frame(physical, style="Panel.TFrame")
        material_bar.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 4))
        self.material_buttons: dict[str, ttk.Button] = {}
        material_labels = {
            MATERIAL_PLA: self.i18n.text("palette.material_pla"),
            MATERIAL_ABS: self.i18n.text("palette.material_abs"),
            MATERIAL_PETG: self.i18n.text("palette.material_petg"),
        }
        for column, material in enumerate(SUPPORTED_FILAMENT_MATERIALS):
            button = ttk.Button(
                material_bar,
                text=material_labels[material],
                command=lambda value=material: self._change_material_mode(value),
            )
            button.grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 2, 0 if column == 2 else 2),
            )
            material_bar.columnconfigure(column, weight=1)
            self.material_buttons[material] = button

        sample = ttk.Frame(physical, style="Panel.TFrame")
        sample.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(0, 3))
        sample.columnconfigure(2, weight=1)
        self.eyedropper_button = ttk.Button(
            sample,
            text=self.i18n.text("palette.eyedropper_start"),
            command=self._toggle_eyedropper,
            style="Accent.TButton",
        )
        self.eyedropper_button.grid(row=0, column=0, padx=(0, 8))
        self.sample_swatch = tk.Label(sample, width=4, height=2, bg="#303846", relief="flat")
        self.sample_swatch.grid(row=0, column=1, padx=(0, 8))
        ttk.Label(sample, textvariable=self.sample_hex_var, style="Panel.TLabel", font=("Consolas", 11, "bold")).grid(row=0, column=2, sticky="w")
        self.recipe_toggle_button = ttk.Button(
            sample,
            text=self.i18n.text("main.recipe_show"),
            command=self._toggle_recipe_panel,
        )
        self.recipe_toggle_button.grid(row=0, column=3, padx=(8, 0), sticky="e")
        self.eyedropper_hint_label = ttk.Label(
            sample,
            text=self.i18n.text("palette.eyedropper_hint"),
            style="PanelMuted.TLabel",
            wraplength=320,
        )
        self.physical_swatch_buttons: list[tk.Button] = []
        self.physical_eyedropper_buttons: list[ttk.Button] = []
        for index, name in enumerate(PHYSICAL_NAMES):
            row = index + 2
            ttk.Checkbutton(physical, variable=self.enabled_vars[index]).grid(row=row, column=0, padx=(0, 4))
            button = tk.Button(
                physical,
                width=3,
                height=1,
                relief="flat",
                command=lambda i=index: self._choose_physical_color(i),
            )
            button.grid(row=row, column=1, padx=(0, 5), pady=1)
            self.physical_swatch_buttons.append(button)
            ttk.Label(physical, text=name, style="Panel.TLabel", width=4).grid(row=row, column=2, sticky="w")
            entry = ttk.Entry(physical, textvariable=self.physical_vars[index], width=9)
            entry.grid(row=row, column=3, sticky="w", padx=3)
            eyedropper_button = ttk.Button(
                physical,
                text=self.i18n.text(
                    "palette.set_base_short"
                ),
                command=lambda i=index: self._start_physical_eyedropper(i),
                style="Accent.TButton",
            )
            eyedropper_button.grid(row=row, column=4, padx=(2, 0))
            self.physical_eyedropper_buttons.append(eyedropper_button)
        # The reset implementation remains available for settings migration and
        # internal recovery, but the public Filament page must not offer a
        # one-click action that can replace the model-derived four colours.
        self.filament_candidate_button = ttk.Button(
            physical,
            text=self.i18n.text("filament_candidates.button"),
            command=self._open_filament_candidates,
            style="Accent.TButton",
        )
        self.filament_candidate_button.grid(
            row=7,
            column=0,
            columnspan=5,
            sticky="ew",
            pady=(5, 0),
        )

        mixed = ttk.LabelFrame(
            tab, text=self.i18n.text("palette.mix_group"), padding=(7, 4)
        )
        self.mixed_palette_group = mixed
        mixed.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        mixed.columnconfigure(1, weight=1)
        selector = ttk.Frame(mixed, style="Panel.TFrame")
        selector.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 3))
        self.palette_state_count_label = ttk.Label(
            selector,
            text=self.i18n.text("palette.state_count"),
            style="Panel.TLabel",
        )
        self.palette_state_count_label.grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.palette_state_count_combo = ttk.Combobox(
            selector,
            textvariable=self.palette_state_count_var,
            values=SUPPORTED_PALETTE_STATE_COUNTS,
            state="readonly",
            width=7,
            style="HighContrast.TCombobox",
        )
        self.palette_state_count_combo.grid(row=0, column=1, sticky="w")
        self.palette_state_count_combo.bind(
            "<<ComboboxSelected>>", self._on_palette_state_count_changed
        )
        # Ratios remain part of the canonical project/3MF model, but are no
        # longer editable in the public UI.  Each pair is presented as one
        # left-to-right gradient strip, with a separate display number mapped
        # back to its unchanged internal state ID.
        self.mix_family_frames: list[ttk.Frame] = []
        self.mix_state_cells: dict[int, ttk.Frame] = {}
        self.mix_state_swatch_labels: dict[int, tk.Label] = {}
        self.mix_state_number_labels: dict[int, tk.Label] = {}
        canonical_specs = palette_mix_specs()
        for pair_index, pair_name in enumerate(PAIR_NAMES):
            row = pair_index + 1
            ttk.Label(
                mixed,
                text=pair_name,
                style="Panel.TLabel",
                width=7,
            ).grid(row=row, column=0, sticky="w", padx=(0, 4), pady=1)
            family = ttk.Frame(mixed, style="Panel.TFrame")
            family.grid(row=row, column=1, sticky="w", pady=1)
            self.mix_family_frames.append(family)
            expected_pair = PAIR_INDICES[pair_index]
            for mixed_offset, (left, right, _ratio) in enumerate(canonical_specs):
                if (left, right) != expected_pair:
                    continue
                state_index = mixed_offset + 4
                cell = ttk.Frame(family, style="Panel.TFrame")
                enabled = ttk.Checkbutton(
                    cell,
                    variable=self.enabled_vars[state_index],
                )
                enabled.grid(row=0, column=0, padx=(0, 1))
                swatch = tk.Label(
                    cell,
                    text="",
                    width=3,
                    bg="#303846",
                    fg="#FFFFFF",
                    relief="flat",
                    font=("Yu Gothic UI", 8, "bold"),
                )
                swatch.grid(row=0, column=1, ipady=3)
                self.mix_state_cells[state_index] = cell
                self.mix_state_swatch_labels[state_index] = swatch
                self.mix_state_number_labels[state_index] = swatch
        self.mix_swatch_labels = [
            self.mix_state_swatch_labels[state] for state in range(4, 10)
        ]
        self.secondary_mix_swatch_labels = [
            self.mix_state_swatch_labels[state] for state in range(10, 16)
        ]
        self.additional_mix_swatch_labels = [
            self.mix_state_swatch_labels[state] for state in range(16, 32)
        ]
        self.extended_palette_checkbutton = ttk.Checkbutton(
            mixed,
            text=self.i18n.text("palette.extended_short"),
            variable=self.extended_palette_var,
            command=self._on_extended_palette_changed,
        )
        self.extended_palette_checkbutton.grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(3, 0)
        )

        self.calibration_chart_button = ttk.Button(
            mixed,
            text=self.i18n.text("palette.calibration_export"),
            command=self._export_palette_calibration_chart,
            style="Accent.TButton",
        )
        self.calibration_chart_button.grid(
            row=8,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(4, 0),
        )
        self.calibration_chart_help_label = ttk.Label(
            mixed,
            text=self.i18n.text("palette.calibration_help"),
            style="PanelMuted.TLabel",
            justify="left",
            wraplength=430,
        )
        self._layout_mix_family_cells()

        # The research widgets still exist for source-level compatibility, but
        # live under an unmanaged host so they cannot consume public layout.
        self._experimental_palette_host = ttk.Frame(tab, style="Panel.TFrame")

        self.black_free_gradient_group = ttk.LabelFrame(
            self._experimental_palette_host,
            text=self.i18n.text("palette.black_free_group"),
            padding=(8, 6),
        )
        self.black_free_gradient_group.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(7, 0),
        )
        self.black_free_gradient_group.columnconfigure(0, weight=1)
        self.black_free_gradient_enable_checkbutton = ttk.Checkbutton(
            self.black_free_gradient_group,
            text=self.i18n.text("palette.black_free_enable"),
            variable=self.black_free_gradient_enabled_var,
            command=self._on_black_free_gradient_toggle,
        )
        self.black_free_gradient_enable_checkbutton.grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )

        slot_widgets = (
            (
                "black_free_black_slot_label",
                "black_free_black_slot_combo",
                "palette.black_free_black_slot",
                self.black_free_black_slot_var,
            ),
            (
                "black_free_red_slot_label",
                "black_free_red_slot_combo",
                "palette.black_free_red_slot",
                self.black_free_red_slot_var,
            ),
            (
                "black_free_brown_slot_label",
                "black_free_brown_slot_combo",
                "palette.black_free_brown_slot",
                self.black_free_brown_slot_var,
            ),
        )
        for offset, (label_name, combo_name, label_key, variable) in enumerate(
            slot_widgets
        ):
            label = ttk.Label(
                self.black_free_gradient_group,
                text=self.i18n.text(label_key),
                style="Panel.TLabel",
            )
            label.grid(row=0, column=1 + offset * 2, sticky="e")
            setattr(self, label_name, label)
            combo = ttk.Combobox(
                self.black_free_gradient_group,
                textvariable=variable,
                values=PHYSICAL_NAMES,
                state="disabled",
                width=5,
                style="HighContrast.TCombobox",
            )
            combo.grid(
                row=0,
                column=2 + offset * 2,
                sticky="w",
                padx=(5, 9 if offset < 2 else 0),
            )
            combo.bind(
                "<<ComboboxSelected>>", self._on_black_free_gradient_slot_changed
            )
            setattr(self, combo_name, combo)
        self.black_free_gradient_summary_label = ttk.Label(
            self.black_free_gradient_group,
            textvariable=self.black_free_gradient_summary_var,
            style="Panel.TLabel",
            justify="left",
            wraplength=850,
        )
        self.black_free_gradient_summary_label.grid(
            row=1, column=0, columnspan=7, sticky="w", pady=(5, 0)
        )
        self.black_free_gradient_help_label = ttk.Label(
            self.black_free_gradient_group,
            text=self.i18n.text("palette.black_free_help"),
            style="PanelMuted.TLabel",
            justify="left",
            wraplength=850,
        )
        self.black_free_gradient_help_label.grid(
            row=2, column=0, columnspan=7, sticky="w", pady=(2, 0)
        )

        self.black_output_group = ttk.LabelFrame(
            mixed,
            text=self.i18n.text("palette.black_output_group"),
            padding=(6, 3),
        )
        self.black_output_group.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(4, 0),
        )
        self.black_output_enable_checkbutton = ttk.Checkbutton(
            self.black_output_group,
            text=self.i18n.text("palette.black_output_enable"),
            variable=self.black_output_enabled_var,
            command=self._on_black_output_toggle,
        )
        self.black_output_enable_checkbutton.grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 2)
        )
        self.black_output_slot_label = ttk.Label(
            self.black_output_group,
            text=self.i18n.text("palette.black_output_slot"),
            style="Panel.TLabel",
        )
        self.black_output_slot_label.grid(row=1, column=0, sticky="w")
        self.black_output_slot_combo = ttk.Combobox(
            self.black_output_group,
            textvariable=self.black_output_slot_var,
            values=PHYSICAL_NAMES,
            state="disabled",
            width=5,
            style="HighContrast.TCombobox",
        )
        self.black_output_slot_combo.grid(
            row=1, column=1, sticky="w", padx=(5, 8)
        )
        self.black_output_slot_combo.bind(
            "<<ComboboxSelected>>", self._on_black_output_slot_changed
        )
        self.black_output_preset_button = ttk.Button(
            self.black_output_group,
            text=self.i18n.text("palette.black_output_preset"),
            command=self._apply_black_output_preset,
            state="disabled",
            width=8,
        )
        self.black_output_group.columnconfigure(2, weight=1)
        self.black_output_preset_button.grid(
            row=1, column=2, sticky="w"
        )
        self.black_output_summary_label = ttk.Label(
            self.black_output_group,
            textvariable=self.black_output_summary_var,
            style="Panel.TLabel",
            justify="left",
            wraplength=850,
        )
        self.black_output_warning_label = ttk.Label(
            self.black_output_group,
            textvariable=self.black_output_warning_var,
            style="PanelMuted.TLabel",
            justify="left",
            wraplength=850,
        )

        self.developer_features_enable_checkbutton = ttk.Checkbutton(
            self._experimental_palette_host,
            text=self.i18n.text("developer_features.show"),
            variable=self.developer_features_enabled_var,
            command=self._on_developer_features_toggle,
        )

        self.surface_shell_group = ttk.LabelFrame(
            self._experimental_palette_host,
            text=self.i18n.text("palette.surface_shell_unavailable_group"),
            padding=(8, 6),
        )
        self.surface_shell_group.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(7, 0),
        )
        self.surface_shell_group.columnconfigure(0, weight=1)
        self.surface_shell_enable_checkbutton = ttk.Checkbutton(
            self.surface_shell_group,
            text=self.i18n.text("palette.surface_shell_unavailable_label"),
            variable=self.surface_shell_enabled_var,
            command=self._on_surface_shell_toggle,
        )
        self.surface_shell_enable_checkbutton.grid(
            row=0, column=0, sticky="w"
        )
        self.surface_shell_enable_checkbutton.state(["disabled"])
        self.surface_shell_summary_label = ttk.Label(
            self.surface_shell_group,
            textvariable=self.surface_shell_summary_var,
            style="Panel.TLabel",
            justify="left",
            wraplength=850,
        )
        self.surface_shell_summary_label.grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )
        self.surface_shell_help_label = ttk.Label(
            self.surface_shell_group,
            text=self.i18n.text("palette.surface_shell_unavailable_help"),
            style="PanelMuted.TLabel",
            justify="left",
            wraplength=850,
        )
        self.surface_shell_help_label.grid(
            row=2, column=0, sticky="w", pady=(2, 0)
        )

        self.color_depth_group = ttk.LabelFrame(
            self._experimental_palette_host,
            text=self.i18n.text("color_depth.group"),
            padding=(8, 6),
        )
        self.color_depth_group.grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(7, 0),
        )
        self.color_depth_group.columnconfigure(3, weight=1)
        self.color_depth_enable_checkbutton = ttk.Checkbutton(
            self.color_depth_group,
            text=self.i18n.text("color_depth.enable"),
            variable=self.color_depth_enabled_var,
            command=self._on_color_depth_toggle,
        )
        self.color_depth_enable_checkbutton.grid(
            row=0, column=0, columnspan=5, sticky="w"
        )
        self.color_depth_thickness_label = ttk.Label(
            self.color_depth_group,
            text=self.i18n.text("color_depth.outer_thickness"),
            style="Panel.TLabel",
        )
        self.color_depth_thickness_label.grid(row=1, column=0, sticky="w")
        self.color_depth_thickness_spinbox = ttk.Spinbox(
            self.color_depth_group,
            from_=0.14,
            to=0.60,
            increment=0.01,
            width=7,
            textvariable=self.color_depth_outer_thickness_var,
        )
        self.color_depth_thickness_spinbox.grid(
            row=1, column=1, sticky="w", padx=(6, 3)
        )
        ttk.Label(
            self.color_depth_group,
            text="mm",
            style="Panel.TLabel",
        ).grid(row=1, column=2, sticky="w")
        self.color_depth_export_button = ttk.Button(
            self.color_depth_group,
            text=self.i18n.text("color_depth.export"),
            command=self._export_color_depth_experiment,
            style="Accent.TButton",
        )
        self.color_depth_export_button.grid(
            row=1, column=4, sticky="e", padx=(10, 0)
        )
        self.color_depth_part_3mf_button = ttk.Button(
            self.color_depth_group,
            text=self.i18n.text("color_depth.convert_part_3mf"),
            command=self._convert_color_depth_part_3mf,
        )
        self.color_depth_part_3mf_button.grid(
            row=2, column=4, sticky="e", padx=(10, 0), pady=(5, 0)
        )
        self.color_depth_help_label = ttk.Label(
            self.color_depth_group,
            text=self.i18n.text("color_depth.help"),
            style="PanelMuted.TLabel",
            justify="left",
            wraplength=850,
        )
        self.color_depth_help_label.grid(
            row=3, column=0, columnspan=5, sticky="w", pady=(5, 0)
        )
        self._refresh_developer_feature_visibility()
        self._refresh_color_depth_widgets()

    def _layout_mix_family_cells(self) -> None:
        """Lay out mixed states with the chart's single shared order map."""

        cells = getattr(self, "mix_state_cells", {})
        if not cells:
            return
        try:
            count = int(self.palette_state_count_var.get())
            primary_ratios = [
                int(variable.get()) for variable in self.mix_ratio_vars
            ]
            secondary_ratios = [
                int(variable.get())
                for variable in self.secondary_mix_ratio_vars
            ]
            specs = palette_mix_specs(primary_ratios, secondary_ratios)
            display_state_indices = palette_family_display_state_indices(
                count,
                primary_ratios,
                secondary_ratios,
            )
        except (AttributeError, TypeError, ValueError, tk.TclError):
            return
        for cell in cells.values():
            cell.grid_remove()
        # The helper appends F1-F4 for the calibration bundle.  This panel
        # displays only the numbered mixed states, grouped by their already
        # family-major sequence.
        mixed_state_indices = display_state_indices[: count - 4]
        chart_number = 1
        arranged: list[int] = []
        for pair_index, pair in enumerate(PAIR_INDICES):
            family_states = [
                state_index
                for state_index in mixed_state_indices
                if specs[state_index - 4][:2] == pair
            ]
            family = self.mix_family_frames[pair_index]
            for column, state_index in enumerate(family_states):
                cell = cells[state_index]
                cell.grid(
                    in_=family,
                    row=0,
                    column=column,
                    padx=(0, 3 if column + 1 < len(family_states) else 0),
                )
                self.mix_state_number_labels[state_index].configure(
                    text=f"{chart_number:02d}"
                )
                arranged.append(state_index)
                chart_number += 1
        self.mix_display_state_indices = tuple(arranged)

    def _add_scale(self, parent: ttk.Frame, row: int, label: str, variable: tk.DoubleVar, start: float, end: float, resolution: float) -> None:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w")
        scale = tk.Scale(
            parent,
            from_=start,
            to=end,
            resolution=resolution,
            orient=tk.HORIZONTAL,
            variable=variable,
            command=lambda _value: self._on_tone_changed(),
            bg=PANEL,
            fg=TEXT,
            troughcolor="#303A49",
            activebackground=ACCENT,
            highlightthickness=0,
            length=235,
        )
        scale.grid(row=row, column=1, sticky="ew", pady=3)

    def _build_tone_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(1, weight=1)
        ttk.Label(
            tab,
            text=f"モデル上の陰影を最大{PALETTE_STATE_COUNT}色へ割り当てる前に調整します。",
            style="PanelMuted.TLabel",
            wraplength=340,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self._add_scale(tab, 1, "黒点", self.black_point_var, 0.0, 0.50, 0.005)
        self._add_scale(tab, 2, "白点", self.white_point_var, 0.40, 1.00, 0.005)
        self._add_scale(tab, 3, "ガンマ", self.gamma_var, 0.50, 2.00, 0.02)
        self._add_scale(tab, 4, "コントラスト", self.contrast_var, 0.50, 2.00, 0.02)
        self._add_scale(tab, 5, "彩度", self.saturation_var, 0.00, 2.00, 0.02)
        ttk.Separator(tab).grid(row=6, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Checkbutton(tab, text="赤みの強い領域をF4系で保護（任意）", variable=self.pink_protection_var, command=self._on_tone_changed).grid(row=7, column=0, columnspan=2, sticky="w")
        self._add_scale(tab, 8, "F4系保護の判定", self.pink_threshold_var, 0.0, 0.25, 0.005)
        ttk.Checkbutton(tab, text="微小な色飛びを近傍へ統合", variable=self.smoothing_var, command=self._on_tone_changed).grid(row=9, column=0, columnspan=2, sticky="w", pady=(9, 0))
        self._add_scale(tab, 10, "統合面積 mm²", self.smoothing_area_var, 0.0, 0.20, 0.005)
        self._add_scale(tab, 11, "許容 ΔE", self.smoothing_slack_var, 0.0, 10.0, 0.25)
        ttk.Separator(tab).grid(row=12, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Label(
            tab,
            text="現在の基本4色を使い、モデルの陰影に合う混色比率を求めます。",
            style="PanelMuted.TLabel",
            wraplength=340,
            justify="left",
        ).grid(row=13, column=0, columnspan=2, sticky="w", pady=(0, 7))
        ttk.Button(
            tab,
            text="陰影を混色に反映（自動最適化）",
            command=self._optimize_mix_ratios,
            style="Accent.TButton",
        ).grid(row=14, column=0, columnspan=2, sticky="ew")
        self.undo_mix_button = ttk.Button(
            tab,
            text="直前の混色最適化を元に戻す",
            command=self._undo_mix_optimization,
            state="disabled",
        )
        self.undo_mix_button.grid(
            row=15, column=0, columnspan=2, sticky="ew", pady=(5, 0)
        )
        ttk.Button(tab, text="陰影設定を初期値へ戻す", command=self._reset_tone).grid(row=16, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _build_geometry_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(1, weight=1)
        fields = (
            ("出力高さ mm", self.height_var),
            ("最終面数", self.target_faces_var),
            ("プレビュー面数", self.preview_faces_var),
            ("微小部品の下限面数", self.min_component_var),
        )
        for row, (label, variable) in enumerate(fields):
            ttk.Label(tab, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=5)
            entry = ttk.Entry(tab, textvariable=variable, width=15)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=5)
            if variable is self.target_faces_var:
                self.target_faces_entry = entry
        ttk.Label(tab, text="Tripoの上方向", style="Panel.TLabel").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Combobox(
            tab,
            textvariable=self.up_axis_var,
            values=("X", "Y", "Z"),
            state="readonly",
            width=8,
            style="HighContrast.TCombobox",
        ).grid(row=4, column=1, sticky="w", padx=(8, 0))
        ttk.Checkbutton(tab, text="左右を反転", variable=self.mirror_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(tab, text="予備の頂点カラーOBJも保存", variable=self.include_obj_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=6)
        self.reprocess_geometry_button = ttk.Button(
            tab,
            text=self.i18n.text("geometry.reprocess"),
            command=self._apply_face_count_adjustment,
            style="Accent.TButton",
        )
        self.reprocess_geometry_button.grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        ttk.Label(
            tab,
            textvariable=self.face_count_status_var,
            style="PanelMuted.TLabel",
            wraplength=340,
            justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(6, 4))
        ttk.Label(
            tab,
            text=self.i18n.text("geometry.reprocess_help"),
            style="PanelMuted.TLabel",
            wraplength=340,
            justify="left",
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _build_assembly_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(0, weight=1)
        ttk.Label(
            tab,
            text=self.i18n.text("assembly.intro"),
            style="PanelMuted.TLabel",
            wraplength=640,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        ttk.Label(
            tab,
            textvariable=self.assembly_status_var,
            foreground=SUCCESS,
            background=PANEL,
            wraplength=640,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=2)

        actions = ttk.Frame(tab, style="Panel.TFrame")
        actions.grid(row=2, column=0, sticky="ew", pady=(5, 2))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(
            actions,
            text=self.i18n.text("assembly.keep_raw"),
            command=self._keep_original_parts_open,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3), pady=2)
        self.close_parts_safely_button = ttk.Button(
            actions,
            text=self.i18n.text("assembly.close_safely"),
            command=self._close_parts_safely,
            style="Accent.TButton",
        )
        self.close_parts_safely_button.grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Checkbutton(
            tab,
            text=self.i18n.text("assembly.individual_3mf"),
            variable=self.export_individual_parts_var,
        ).grid(row=3, column=0, sticky="w", pady=(4, 2))
        ttk.Label(
            tab,
            text=self.i18n.text("assembly.layer_height"),
            foreground=SUCCESS,
            background=PANEL,
            wraplength=640,
            justify="left",
        ).grid(row=4, column=0, sticky="w", pady=(4, 2))
        ttk.Label(
            tab,
            text=self.i18n.text("assembly.processing_help"),
            style="PanelMuted.TLabel",
            wraplength=640,
            justify="left",
        ).grid(row=5, column=0, sticky="w", pady=(2, 0))

    def _build_preview(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(parent, bg="#090C11", highlightthickness=0, cursor="arrow")
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self._on_canvas_configure)
        self.preview_canvas.bind("<Button-1>", self._on_canvas_click)

        recipe = ttk.LabelFrame(parent, text="スポイト色の再現候補（公式混色モデルによる予測）", padding=8)
        self.recipe_panel = recipe
        recipe.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        recipe.columnconfigure(0, weight=1)
        self.recipe_tree = ttk.Treeview(recipe, columns=("pair", "ratio", "predicted", "error", "judge"), show="headings", height=5)
        headings = (("pair", "使用色"), ("ratio", "比率 A : B"), ("predicted", "予測色"), ("error", "ΔE76"), ("judge", "目安"))
        widths = {"pair": 190, "ratio": 120, "predicted": 100, "error": 75, "judge": 100}
        for key, title in headings:
            self.recipe_tree.heading(key, text=title)
            self.recipe_tree.column(key, width=widths[key], anchor="center")
        self.recipe_tree.grid(row=0, column=0, sticky="ew")
        self.recipe_tree.bind("<Double-1>", lambda _event: self._apply_selected_recipe())
        actions = ttk.Frame(recipe)
        actions.grid(row=0, column=1, sticky="ns", padx=(9, 0))
        ttk.Button(actions, text="選択レシピを\n混色スロットへ反映", command=self._apply_selected_recipe, style="Accent.TButton").pack(fill="x")
        self.direct_match_label = ttk.Label(actions, text="基本色の近似: 未取得", style="Muted.TLabel", wraplength=210, justify="left")
        self.direct_match_label.pack(fill="x", pady=(10, 0))
        recipe.grid_remove()

    def _set_recipe_panel_visible(self, visible: bool) -> None:
        variable = getattr(self, "recipe_panel_visible_var", None)
        if variable is not None:
            variable.set(bool(visible))
        panel = getattr(self, "recipe_panel", None)
        if panel is not None:
            if visible:
                panel.grid()
            else:
                panel.grid_remove()
        button = getattr(self, "recipe_toggle_button", None)
        if button is not None:
            button.configure(
                text=self.i18n.text(
                    "main.recipe_hide" if visible else "main.recipe_show"
                )
            )

    def _toggle_recipe_panel(self) -> None:
        variable = getattr(self, "recipe_panel_visible_var", None)
        self._set_recipe_panel_visible(not bool(variable.get()) if variable else True)

    def _attach_traces(self) -> None:
        for variable in self.physical_vars:
            variable.trace_add("write", lambda *_args: self._on_palette_changed())
        for variable in self.mix_ratio_vars:
            variable.trace_add("write", lambda *_args: self._on_palette_changed())
        for variable in self.secondary_mix_ratio_vars:
            variable.trace_add("write", lambda *_args: self._on_palette_changed())
        for variable in self.enabled_vars:
            variable.trace_add("write", lambda *_args: self._on_palette_changed())
        self.height_var.trace_add("write", lambda *_args: self._on_height_changed())
        for variable in (
            self.target_faces_var,
            self.preview_faces_var,
            self.up_axis_var,
            self.min_component_var,
            self.mirror_var,
            self.preserve_parts_var,
            self.solidify_parts_var,
            self.repair_unmatched_boundaries_var,
            self.auto_joints_var,
            self.joint_width_var,
            self.joint_height_var,
            self.joint_depth_var,
            self.joint_clearance_var,
            self.joint_min_span_var,
            self.split_enabled_var,
            self.split_axis_var,
            self.split_position_var,
            self.split_target_part_var,
        ):
            variable.trace_add(
                "write", lambda *_args: self._note_mix_input_change()
            )

    @staticmethod
    def _darkest_physical_slot(physical_hex: list[str] | tuple[str, ...]) -> int:
        """Return the darkest F1-F4 slot using relative sRGB luminance."""

        if len(physical_hex) != 4:
            return 0

        def luminance(value: str) -> float:
            normalized = normalize_hex(value)
            channels = [
                int(normalized[index : index + 2], 16) / 255.0
                for index in (1, 3, 5)
            ]
            linear = [
                channel / 12.92
                if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4
                for channel in channels
            ]
            return (
                0.2126 * linear[0]
                + 0.7152 * linear[1]
                + 0.0722 * linear[2]
            )

        try:
            return min(range(4), key=lambda index: luminance(physical_hex[index]))
        except (TypeError, ValueError):
            return 0

    def _black_output_slot_index(self) -> int:
        try:
            return PHYSICAL_NAMES.index(str(self.black_output_slot_var.get()))
        except (AttributeError, ValueError):
            try:
                physical = [variable.get() for variable in self.physical_vars]
            except (AttributeError, tk.TclError):
                physical = list(self.settings.palette.physical_hex)
            return self._darkest_physical_slot(physical)

    @classmethod
    def _infer_black_output_slot(cls, palette: PaletteSettings) -> int:
        """Recover the selected slot from a saved output recipe when possible."""

        output = palette.output_mix_ratios_b
        darkest = cls._darkest_physical_slot(palette.physical_hex)
        if output is None:
            return darkest
        for slot_index in range(4):
            if list(output) == black_output_ratio_preset(
                slot_index,
                palette.mix_ratios_b,
                palette.secondary_mix_ratios_b,
            ):
                return slot_index

        display = palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
        differences = [
            abs(int(output_ratio) - int(display_ratio))
            for (_left, _right, display_ratio), output_ratio in zip(
                display, output, strict=True
            )
        ]
        scores = [
            sum(
                difference
                for (left, right, _ratio), difference in zip(
                    display, differences, strict=True
                )
                if slot_index in (left, right)
            )
            for slot_index in range(4)
        ]
        return max(range(4), key=lambda index: (scores[index], index == darkest))

    @staticmethod
    def _strict_black_output_preset_slot(
        palette: PaletteSettings,
    ) -> int | None:
        """Return the uniquely matching Weak Black preset slot.

        Surface-shell output depends on the calibrated black-share contract,
        not merely on the presence of an arbitrary output-ratio list.  Keep
        this check deliberately stricter than ``_infer_black_output_slot``:
        future/custom recipes must be preserved, but they cannot silently opt
        into the experimental black-inner-wall architecture.
        """

        output = palette.output_mix_ratios_b
        if output is None:
            return None
        try:
            normalized = list(output)
            matches = [
                slot_index
                for slot_index in range(4)
                if normalized
                == black_output_ratio_preset(
                    slot_index,
                    palette.mix_ratios_b,
                    palette.secondary_mix_ratios_b,
                )
            ]
        except (TypeError, ValueError):
            return None
        return matches[0] if len(matches) == 1 else None

    def _surface_shell_dependency(
        self, palette: PaletteSettings
    ) -> tuple[int | None, str | None]:
        """Resolve the effective black preset required by surface-shell mode.

        Separate part jobs inherit the common black preset when they have no
        explicit local output recipe.  An explicit custom local recipe still
        wins for printing and therefore blocks surface-shell mode rather than
        being overwritten.  The selected black slot must also be the darkest
        physical slot because the core shell recipe uses that same invariant.
        """

        slot = self._strict_black_output_preset_slot(palette)
        if slot is None and palette.output_mix_ratios_b is not None:
            return None, "custom"

        if slot is None and getattr(self, "active_part_key", None) is not None:
            common = self.settings.palette
            slot = self._strict_black_output_preset_slot(common)
            if slot is None and common.output_mix_ratios_b is not None:
                return None, "custom"

        if slot is None:
            return None, "required"
        if slot != self._darkest_physical_slot(palette.physical_hex):
            return None, "slot_mismatch"
        return slot, None

    def _active_palette_for_controls(self) -> PaletteSettings:
        if self.active_part_key is None:
            return self.settings.palette
        return resolve_palette_for_part_key(self.settings, self.active_part_key)

    def _black_free_slot_indices(self) -> tuple[int, int, int]:
        """Return the three selected physical roles after strict validation."""

        try:
            slots = tuple(
                PHYSICAL_NAMES.index(str(variable.get()))
                for variable in (
                    self.black_free_black_slot_var,
                    self.black_free_red_slot_var,
                    self.black_free_brown_slot_var,
                )
            )
            return validate_black_free_slots(*slots)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(
                self.i18n.text("palette.black_free_distinct_message")
            ) from exc

    def _validate_black_free_gradient_controls(self) -> tuple[int, int, int]:
        """Validate role selection and the enabled replacement candidate set."""

        black_slot, red_slot, brown_slot = self._black_free_slot_indices()
        if bool(self.black_free_gradient_enabled_var.get()):
            replacements = black_free_replacement_states(
                int(self.palette_state_count_var.get()),
                red_slot,
                brown_slot,
                [bool(variable.get()) for variable in self.enabled_vars],
            )
            if not replacements:
                raise ValueError(
                    self.i18n.text("palette.black_free_no_candidate_message")
                )
        return black_slot, red_slot, brown_slot

    @staticmethod
    def _saved_black_free_slots(palette: PaletteSettings) -> tuple[int, int, int]:
        try:
            return validate_black_free_slots(
                int(getattr(palette, "black_free_black_slot", 0)),
                int(getattr(palette, "black_free_red_slot", 2)),
                int(getattr(palette, "black_free_brown_slot", 3)),
            )
        except (TypeError, ValueError):
            # PaletteSettings rejects invalid persisted values.  This fallback
            # only protects a partially mocked GUI test or a mutated object.
            return 0, 2, 3

    def _load_black_free_gradient_variables(
        self, palette: PaletteSettings
    ) -> None:
        enabled_var = getattr(self, "black_free_gradient_enabled_var", None)
        if enabled_var is None:
            return
        developer_enabled = self._developer_features_are_enabled()
        if not developer_enabled:
            palette.black_free_gradient_enabled = False
        black_slot, red_slot, brown_slot = self._saved_black_free_slots(palette)
        self._loading_palette_variables = True
        try:
            enabled_var.set(
                developer_enabled
                and bool(getattr(palette, "black_free_gradient_enabled", False))
            )
            self.black_free_black_slot_var.set(PHYSICAL_NAMES[black_slot])
            self.black_free_red_slot_var.set(PHYSICAL_NAMES[red_slot])
            self.black_free_brown_slot_var.set(PHYSICAL_NAMES[brown_slot])
        finally:
            self._loading_palette_variables = False
        self._refresh_black_free_gradient_widgets(palette)

    def _active_black_free_manual_override_count(
        self, palette: PaletteSettings
    ) -> int:
        """Count explicit black-mix paint for the currently edited target."""

        if not bool(getattr(palette, "black_free_gradient_enabled", False)):
            return 0
        prepared = getattr(self, "prepared", None)
        overrides = getattr(self, "manual_overrides", None)
        if prepared is None or overrides is None:
            return 0
        values = np.asarray(overrides)
        level = prepared.final
        if values.shape != (len(level.faces),):
            return 0
        black_slot, _red_slot, _brown_slot = self._saved_black_free_slots(palette)
        mixed_states = black_containing_mixed_states(
            int(palette.palette_state_count), black_slot
        )
        if not mixed_states:
            return 0
        selected = np.isin(values, np.asarray(mixed_states, dtype=values.dtype))
        face_part_ids = np.asarray(level.face_part_ids)
        if self.active_part_key is None:
            common_part_ids = [
                part_id
                for part_id, key in enumerate(level.part_keys)
                if key not in self.settings.part_palettes
            ]
            selected &= np.isin(face_part_ids, np.asarray(common_part_ids))
        else:
            try:
                part_id = level.part_keys.index(self.active_part_key)
            except ValueError:
                return 0
            selected &= face_part_ids == part_id
        return int(np.count_nonzero(selected))

    def _black_free_manual_override_counts(
        self,
        settings: AppSettings,
        manual_overrides: np.ndarray | None,
        *,
        force_common_palette: bool,
    ) -> tuple[int, int]:
        """Return affected explicit faces and parts for the pending export."""

        prepared = getattr(self, "prepared", None)
        if prepared is None or manual_overrides is None:
            return 0, 0
        values = np.asarray(manual_overrides)
        level = prepared.final
        if values.shape != (len(level.faces),):
            return 0, 0
        face_part_ids = np.asarray(level.face_part_ids)
        affected_faces = 0
        affected_parts = 0
        for part_id, part_key in enumerate(level.part_keys):
            palettes = [
                settings.palette
                if force_common_palette
                else resolve_palette_for_part_key(settings, part_key)
            ]
            # A forced-common main 3MF can be accompanied by independent part
            # 3MFs that retain each part's palette.  Warn when either actual
            # output can preserve a manually painted black-containing mix.
            if force_common_palette and bool(
                settings.geometry.export_individual_parts
            ):
                palettes.append(resolve_palette_for_part_key(settings, part_key))
            mixed_states: set[int] = set()
            for palette in palettes:
                if not bool(
                    getattr(palette, "black_free_gradient_enabled", False)
                ):
                    continue
                black_slot, _red_slot, _brown_slot = self._saved_black_free_slots(
                    palette
                )
                mixed_states.update(
                    black_containing_mixed_states(
                        int(palette.palette_state_count), black_slot
                    )
                )
            if not mixed_states:
                continue
            selected = (face_part_ids == part_id) & np.isin(
                values,
                np.asarray(sorted(mixed_states), dtype=values.dtype),
            )
            count = int(np.count_nonzero(selected))
            if count:
                affected_faces += count
                affected_parts += 1
        return affected_faces, affected_parts

    def _confirm_black_free_manual_overrides(
        self,
        settings: AppSettings,
        manual_overrides: np.ndarray | None,
        *,
        force_common_palette: bool,
    ) -> bool:
        faces, parts = self._black_free_manual_override_counts(
            settings,
            manual_overrides,
            force_common_palette=force_common_palette,
        )
        if faces == 0:
            return True
        proceed = messagebox.askyesno(
            self.i18n.text("palette.black_free_manual_warning_title"),
            self.i18n.text(
                "palette.black_free_manual_warning_message",
                faces=faces,
                parts=parts,
            ),
            parent=self.root,
        )
        if not proceed:
            self.status_var.set(
                self.i18n.text("palette.black_free_manual_warning_cancelled")
            )
        return bool(proceed)

    def _refresh_black_free_gradient_widgets(
        self, palette: PaletteSettings | None = None
    ) -> None:
        enabled_var = getattr(self, "black_free_gradient_enabled_var", None)
        if enabled_var is None:
            return
        try:
            enabled = bool(enabled_var.get())
        except (AttributeError, tk.TclError):
            enabled = False
        developer_enabled = self._developer_features_are_enabled()
        if not developer_enabled:
            enabled = False
            try:
                enabled_var.set(False)
            except (AttributeError, tk.TclError):
                pass
        busy = bool(getattr(self, "busy", False))
        checkbutton = getattr(
            self, "black_free_gradient_enable_checkbutton", None
        )
        if checkbutton is not None:
            checkbutton.state(
                ["disabled"]
                if busy or not developer_enabled
                else ["!disabled"]
            )
        for name in (
            "black_free_black_slot_label",
            "black_free_red_slot_label",
            "black_free_brown_slot_label",
            "black_free_gradient_summary_label",
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                if enabled:
                    widget.grid()
                else:
                    widget.grid_remove()
        for name in (
            "black_free_black_slot_combo",
            "black_free_red_slot_combo",
            "black_free_brown_slot_combo",
        ):
            combo = getattr(self, name, None)
            if combo is not None:
                if enabled:
                    combo.grid()
                else:
                    combo.grid_remove()
                combo.configure(
                    state="readonly" if enabled and not busy else "disabled"
                )

        summary_var = getattr(self, "black_free_gradient_summary_var", None)
        if summary_var is None:
            return
        palette = palette or self._active_palette_for_controls()
        if not enabled:
            summary_var.set(self.i18n.text("palette.black_free_off_summary"))
            return
        try:
            black_slot, red_slot, brown_slot = self._black_free_slot_indices()
        except ValueError:
            black_slot, red_slot, brown_slot = self._saved_black_free_slots(palette)
        physical = list(palette.physical_hex)
        try:
            replacement_count = len(
                black_free_replacement_states(
                    int(palette.palette_state_count),
                    red_slot,
                    brown_slot,
                    palette.enabled_states,
                )
            )
        except (TypeError, ValueError):
            replacement_count = 0
        manual_count = self._active_black_free_manual_override_count(palette)
        summary_var.set(
            self.i18n.text(
                "palette.black_free_on_summary",
                black=PHYSICAL_NAMES[black_slot],
                black_hex=physical[black_slot],
                red=PHYSICAL_NAMES[red_slot],
                red_hex=physical[red_slot],
                brown=PHYSICAL_NAMES[brown_slot],
                brown_hex=physical[brown_slot],
                candidates=replacement_count,
                manual=manual_count,
            )
        )

    def _black_free_gradient_busy_rejected(self) -> bool:
        if not bool(getattr(self, "busy", False)):
            return False
        self._load_black_free_gradient_variables(
            self._active_palette_for_controls()
        )
        messagebox.showinfo(
            self.i18n.text("dialog.busy.title"),
            self.i18n.text("dialog.busy.message"),
            parent=self.root,
        )
        return True

    def _apply_black_free_gradient_change(self) -> None:
        if not self._developer_features_are_enabled():
            _enforce_black_free_gradient_developer_gate(self.settings, False)
            enabled_var = getattr(
                self,
                "black_free_gradient_enabled_var",
                None,
            )
            if enabled_var is not None:
                try:
                    enabled_var.set(False)
                except (AttributeError, tk.TclError):
                    pass
            self._load_black_free_gradient_variables(
                self._active_palette_for_controls()
            )
            return
        if self._loading_palette_variables or self._black_free_gradient_busy_rejected():
            return
        previous = self._active_palette_for_controls()
        try:
            black_slot, red_slot, brown_slot = (
                self._validate_black_free_gradient_controls()
            )
            palette = self._commit_active_palette()
        except (ValueError, tk.TclError) as exc:
            self._load_black_free_gradient_variables(previous)
            messagebox.showerror(
                self.i18n.text("palette.black_free_invalid_title"),
                str(exc),
                parent=self.root,
            )
            return

        if self.active_part_key is not None:
            self.part_recommendations.pop(self.active_part_key, None)
        self._note_mix_input_change()
        self._refresh_palette_widgets(schedule_preview=False)
        self._refresh_black_free_gradient_widgets(palette)
        self._refresh_part_tree()
        manual_count = self._active_black_free_manual_override_count(palette)
        enabled = bool(getattr(palette, "black_free_gradient_enabled", False))
        status = self.i18n.text(
            (
                "palette.black_free_enabled_status"
                if enabled
                else "palette.black_free_disabled_status"
            ),
            manual=manual_count,
            black=PHYSICAL_NAMES[black_slot],
            red=PHYSICAL_NAMES[red_slot],
            brown=PHYSICAL_NAMES[brown_slot],
        )
        editor = getattr(self, "paint_editor", None)
        reapply = getattr(editor, "reapply_palette_settings", None)
        if callable(reapply):
            reapply(self.active_part_key, palette, message=status)
        self._schedule_preview(immediate=True)
        self.status_var.set(status)

    def _on_black_free_gradient_toggle(self) -> None:
        self._apply_black_free_gradient_change()

    def _on_black_free_gradient_slot_changed(self, _event=None) -> None:
        self._apply_black_free_gradient_change()

    def _assign_active_palette(self, palette: PaletteSettings) -> None:
        if not self._developer_features_are_enabled():
            palette.black_free_gradient_enabled = False
        if self.active_part_key is None:
            self.settings.palette = palette
        else:
            self.settings.part_palettes[self.active_part_key] = palette
        _enforce_black_free_gradient_developer_gate(
            self.settings,
            self._developer_features_are_enabled(),
        )
        # Manual Editing owns a snapshot of AppSettings.  Keep its export and
        # filament-usage data current, but deliberately avoid
        # reapply_palette_settings(): output-only correction must not enqueue
        # a recolour or alter the viewport.
        editor = getattr(self, "paint_editor", None)
        editor_settings = getattr(editor, "settings", None)
        if isinstance(editor_settings, AppSettings):
            copied = self._copy_palette(palette)
            if self.active_part_key is None:
                editor_settings.palette = copied
            else:
                editor_settings.part_palettes[self.active_part_key] = copied
            if hasattr(editor, "_palette_usage_contribution_cache_key"):
                editor._palette_usage_contribution_cache_key = None
            update_usage = getattr(editor, "_update_palette_usage_summary", None)
            if callable(update_usage):
                try:
                    update_usage()
                except (AttributeError, tk.TclError, ValueError):
                    pass

    def _load_black_output_variables(self, palette: PaletteSettings) -> None:
        self._loading_palette_variables = True
        try:
            self.black_output_enabled_var.set(
                palette.output_mix_ratios_b is not None
            )
            self.black_output_slot_var.set(
                PHYSICAL_NAMES[self._infer_black_output_slot(palette)]
            )
        finally:
            self._loading_palette_variables = False
        self._refresh_black_output_widgets(palette)

    def _load_surface_shell_variables(self, palette: PaletteSettings) -> None:
        # Migrate every saved experimental project to the safe Ratio path.
        palette.surface_shell_enabled = False
        self._loading_palette_variables = True
        try:
            enabled_var = getattr(self, "surface_shell_enabled_var", None)
            if enabled_var is not None:
                enabled_var.set(False)
        finally:
            self._loading_palette_variables = False
        self._refresh_surface_shell_widgets(palette)

    def _refresh_surface_shell_widgets(
        self, palette: PaletteSettings | None = None
    ) -> None:
        enabled_var = getattr(self, "surface_shell_enabled_var", None)
        if enabled_var is None:
            return
        try:
            enabled_var.set(False)
        except (AttributeError, tk.TclError):
            pass
        if palette is not None:
            palette.surface_shell_enabled = False
        checkbutton = getattr(
            self, "surface_shell_enable_checkbutton", None
        )
        if checkbutton is not None:
            checkbutton.state(["disabled"])
        summary_var = getattr(self, "surface_shell_summary_var", None)
        if summary_var is None:
            return
        summary_var.set(
            self.i18n.text("palette.surface_shell_unavailable_summary")
        )

    def _surface_shell_busy_rejected(self) -> bool:
        if not bool(getattr(self, "busy", False)):
            return False
        self._load_surface_shell_variables(
            self._active_palette_for_controls()
        )
        messagebox.showinfo(
            self.i18n.text("dialog.busy.title"),
            self.i18n.text("dialog.busy.message"),
            parent=self.root,
        )
        return True

    def _on_surface_shell_toggle(self) -> None:
        enabled_var = getattr(self, "surface_shell_enabled_var", None)
        if enabled_var is not None:
            try:
                enabled_var.set(False)
            except (AttributeError, tk.TclError):
                pass
        try:
            palette = self._active_palette_for_controls()
        except AttributeError:
            palette = None
        if palette is not None:
            palette.surface_shell_enabled = False
        self._refresh_surface_shell_widgets(palette)
        status_var = getattr(self, "status_var", None)
        if status_var is not None:
            status_var.set(
                self.i18n.text("palette.surface_shell_unavailable_status")
            )

    def _developer_features_are_enabled(self) -> bool:
        """Return the committed global UI gate, never a project setting."""

        return getattr(
            self, "_developer_features_enabled_committed", False
        ) is True

    def _refresh_developer_feature_visibility(self) -> None:
        # r25 public UI has no experimental entrance.  Widgets and callbacks
        # remain constructed for source compatibility, but are never managed.
        for name in (
            "black_free_gradient_group",
            "surface_shell_group",
            "color_depth_group",
            "radial_group",
        ):
            group = getattr(self, name, None)
            if group is None:
                continue
            group.grid_remove()
        checkbutton = getattr(
            self, "developer_features_enable_checkbutton", None
        )
        if checkbutton is not None:
            checkbutton.grid_remove()
            checkbutton.state(["disabled"])

    def _on_developer_features_toggle(self) -> None:
        variable = getattr(self, "developer_features_enabled_var", None)
        if variable is None:
            return
        if bool(getattr(self, "busy", False)):
            try:
                variable.set(self._developer_features_are_enabled())
            except (AttributeError, tk.TclError):
                pass
            self._refresh_developer_feature_visibility()
            return
        try:
            requested = variable.get()
        except (AttributeError, tk.TclError):
            requested = False
        # Tk BooleanVar returns bool, but keep the committed permission strict
        # so direct non-UI assignments cannot use truthy strings or integers.
        enabled = requested is True
        self._developer_features_enabled_committed = enabled
        if requested is not enabled:
            try:
                variable.set(enabled)
            except (AttributeError, tk.TclError):
                pass
        disabled_black_free = 0
        if not enabled:
            disabled_black_free = _enforce_black_free_gradient_developer_gate(
                self.settings,
                False,
            )
            black_free_var = getattr(
                self,
                "black_free_gradient_enabled_var",
                None,
            )
            if black_free_var is not None:
                try:
                    black_free_var.set(False)
                except (AttributeError, tk.TclError):
                    pass
            try:
                active_palette = self._active_palette_for_controls()
            except (AttributeError, KeyError):
                active_palette = self.settings.palette
            self._load_black_free_gradient_variables(active_palette)
            editor = getattr(self, "paint_editor", None)
            reapply = getattr(editor, "reapply_shading_settings", None)
            if callable(reapply):
                reapply(
                    self.settings,
                    message=self.i18n.text(
                        "palette.black_free_developer_disabled_status",
                        palettes=disabled_black_free,
                    ),
                )
            note_change = getattr(self, "_note_mix_input_change", None)
            if callable(note_change):
                note_change()
            refresh_palette = getattr(self, "_refresh_palette_widgets", None)
            if callable(refresh_palette):
                refresh_palette(schedule_preview=False)
            refresh_parts = getattr(self, "_refresh_part_tree", None)
            if callable(refresh_parts):
                refresh_parts()
            schedule_preview = getattr(self, "_schedule_preview", None)
            if callable(schedule_preview):
                schedule_preview(immediate=True)
        self._refresh_developer_feature_visibility()
        self._save_persistent_settings()
        status_var = getattr(self, "status_var", None)
        if status_var is not None:
            if not enabled and disabled_black_free:
                status_var.set(
                    self.i18n.text(
                        "palette.black_free_developer_disabled_status",
                        palettes=disabled_black_free,
                    )
                )
            else:
                status_var.set(
                    self.i18n.text(
                        "developer_features.enabled_status"
                        if enabled
                        else "developer_features.disabled_status"
                    )
                )

    def _require_developer_features(self) -> bool:
        if self._developer_features_are_enabled():
            return True
        messagebox.showinfo(
            self.i18n.text("developer_features.required_title"),
            self.i18n.text("developer_features.required_message"),
            parent=self.root,
        )
        return False

    def _refresh_color_depth_widgets(self) -> None:
        enabled_var = getattr(self, "color_depth_enabled_var", None)
        if enabled_var is None:
            return
        try:
            enabled = bool(enabled_var.get())
        except (AttributeError, tk.TclError):
            enabled = False
        busy = bool(getattr(self, "busy", False))
        checkbutton = getattr(
            self, "color_depth_enable_checkbutton", None
        )
        if checkbutton is not None:
            checkbutton.state(["disabled"] if busy else ["!disabled"])
        spinbox = getattr(self, "color_depth_thickness_spinbox", None)
        if spinbox is not None:
            spinbox.state(
                ["!disabled"] if enabled and not busy else ["disabled"]
            )
        button = getattr(self, "color_depth_export_button", None)
        if button is not None:
            button.state(
                ["!disabled"] if enabled and not busy else ["disabled"]
            )
        part_3mf_button = getattr(
            self, "color_depth_part_3mf_button", None
        )
        if part_3mf_button is not None:
            part_3mf_button.state(
                ["!disabled"] if enabled and not busy else ["disabled"]
            )

    def _on_color_depth_toggle(self) -> None:
        if bool(getattr(self, "busy", False)):
            try:
                self.color_depth_enabled_var.set(
                    self.settings.color_depth.experimental_enabled
                )
            except (AttributeError, tk.TclError):
                pass
            self._refresh_color_depth_widgets()
            return
        try:
            enabled = bool(self.color_depth_enabled_var.get())
        except (AttributeError, tk.TclError):
            enabled = False
        self.settings.color_depth.experimental_enabled = enabled
        self._refresh_color_depth_widgets()
        status_var = getattr(self, "status_var", None)
        if status_var is not None:
            status_var.set(
                self.i18n.text(
                    "color_depth.enabled_status"
                    if enabled
                    else "color_depth.disabled_status"
                )
            )

    @staticmethod
    def _black_shares(
        specs: tuple[tuple[int, int, int], ...], slot_index: int
    ) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    int(ratio_b) if right == slot_index else 100 - int(ratio_b)
                    for left, right, ratio_b in specs
                    if slot_index in (left, right)
                }
            )
        )

    def _refresh_black_output_widgets(
        self, palette: PaletteSettings | None = None
    ) -> None:
        enabled_var = getattr(self, "black_output_enabled_var", None)
        if enabled_var is None:
            return
        try:
            enabled = bool(enabled_var.get())
        except (AttributeError, tk.TclError):
            enabled = False
        busy = bool(getattr(self, "busy", False))
        checkbutton = getattr(self, "black_output_enable_checkbutton", None)
        if checkbutton is not None:
            checkbutton.state(["disabled"] if busy else ["!disabled"])
        combo = getattr(self, "black_output_slot_combo", None)
        if combo is not None:
            combo.configure(
                state="readonly" if enabled and not busy else "disabled"
            )
        preset = getattr(self, "black_output_preset_button", None)
        if preset is not None:
            preset.configure(state="normal" if enabled and not busy else "disabled")

        summary_var = getattr(self, "black_output_summary_var", None)
        warning_var = getattr(self, "black_output_warning_var", None)
        if summary_var is None or warning_var is None:
            return
        palette = palette or self._active_palette_for_controls()
        if not enabled:
            summary_var.set(self.i18n.text("palette.black_output_off_summary"))
            warning_var.set("")
            self._refresh_surface_shell_widgets(palette)
            return
        slot_index = self._black_output_slot_index()
        display_specs = palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
        print_specs = print_palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            palette.output_mix_ratios_b,
        )
        target = " / ".join(
            str(value) for value in self._black_shares(display_specs, slot_index)
        )
        output = " / ".join(
            str(value) for value in self._black_shares(print_specs, slot_index)
        )
        slot = PHYSICAL_NAMES[slot_index]
        summary_var.set(
            self.i18n.text(
                "palette.black_output_summary", target=target, output=output
            )
        )
        warning_var.set(
            self.i18n.text(
                "palette.black_output_pure_warning",
                state=slot_index + 1,
                slot=slot,
            )
        )
        self._refresh_surface_shell_widgets(palette)

    def _black_output_busy_rejected(self) -> bool:
        if not bool(getattr(self, "busy", False)):
            return False
        self._load_black_output_variables(self._active_palette_for_controls())
        messagebox.showinfo(
            self.i18n.text("dialog.busy.title"),
            self.i18n.text("dialog.busy.message"),
            parent=self.root,
        )
        return True

    def _on_black_output_toggle(self) -> None:
        if self._loading_palette_variables or self._black_output_busy_rejected():
            return
        if bool(self.black_output_enabled_var.get()):
            try:
                physical = [variable.get() for variable in self.physical_vars]
            except (AttributeError, tk.TclError):
                physical = list(self._active_palette_for_controls().physical_hex)
            slot_index = self._darkest_physical_slot(physical)
            self.black_output_slot_var.set(PHYSICAL_NAMES[slot_index])
            self._apply_black_output_preset()
            return
        surface_shell_var = getattr(self, "surface_shell_enabled_var", None)
        shell_was_enabled = bool(
            getattr(
                self._active_palette_for_controls(),
                "surface_shell_enabled",
                False,
            )
        )
        if surface_shell_var is not None:
            try:
                shell_was_enabled = bool(surface_shell_var.get())
            except (AttributeError, tk.TclError):
                pass
        # The shell recipe is defined only for the calibrated Weak Black
        # output.  Turning that calibration off atomically disables the
        # dependent Cycle mode as well.
        if surface_shell_var is not None:
            surface_shell_var.set(False)
        try:
            palette = self._palette_from_variables()
        except (ValueError, tk.TclError):
            self._load_black_output_variables(self._active_palette_for_controls())
            return
        palette.output_mix_ratios_b = None
        palette.surface_shell_enabled = False
        self._assign_active_palette(palette)
        self._refresh_black_output_widgets(palette)
        self._refresh_surface_shell_widgets(palette)
        self._refresh_part_tree()
        self.status_var.set(
            self.i18n.text(
                "palette.black_output_disabled_shell_too"
                if shell_was_enabled
                else "palette.black_output_disabled"
            )
        )

    def _on_black_output_slot_changed(self, _event=None) -> None:
        if self._loading_palette_variables or not bool(
            self.black_output_enabled_var.get()
        ):
            return
        self._apply_black_output_preset()

    def _apply_black_output_preset(self) -> None:
        if self._loading_palette_variables or self._black_output_busy_rejected():
            return
        self.black_output_enabled_var.set(True)
        try:
            palette = self._palette_from_variables()
            slot_index = self._black_output_slot_index()
            palette.output_mix_ratios_b = black_output_ratio_preset(
                slot_index,
                palette.mix_ratios_b,
                palette.secondary_mix_ratios_b,
            )
        except (ValueError, tk.TclError):
            self._load_black_output_variables(self._active_palette_for_controls())
            return
        self._assign_active_palette(palette)
        self._refresh_black_output_widgets(palette)
        self._refresh_surface_shell_widgets(palette)
        self._refresh_part_tree()
        self.status_var.set(
            self.i18n.text(
                "palette.black_output_applied", slot=PHYSICAL_NAMES[slot_index]
            )
        )

    @staticmethod
    def _copy_palette(palette: PaletteSettings) -> PaletteSettings:
        return PaletteSettings(
            material=palette.material,
            palette_state_count=palette.palette_state_count,
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
            surface_shell_enabled=False,
            black_free_gradient_enabled=bool(
                getattr(palette, "black_free_gradient_enabled", False)
            ),
            black_free_black_slot=int(
                getattr(palette, "black_free_black_slot", 0)
            ),
            black_free_red_slot=int(
                getattr(palette, "black_free_red_slot", 2)
            ),
            black_free_brown_slot=int(
                getattr(palette, "black_free_brown_slot", 3)
            ),
            physical_filament_refs=list(palette.physical_filament_refs),
        )

    def _palette_from_variables(self) -> PaletteSettings:
        physical = [normalize_hex(variable.get()) for variable in self.physical_vars]
        ratios = [int(variable.get()) for variable in self.mix_ratio_vars]
        secondary_ratios = [
            int(variable.get()) for variable in self.secondary_mix_ratio_vars
        ]
        if any(value < 0 or value > 100 for value in ratios + secondary_ratios):
            raise ValueError("混色比率は0～100%です")
        previous = self.settings.palette
        if self.active_part_key is not None:
            previous = resolve_palette_for_part_key(
                self.settings, self.active_part_key
            )
        black_free_enabled_var = getattr(
            self, "black_free_gradient_enabled_var", None
        )
        if black_free_enabled_var is None:
            black_free_enabled = (
                self._developer_features_are_enabled()
                and bool(
                    getattr(previous, "black_free_gradient_enabled", False)
                )
            )
            black_free_black_slot, black_free_red_slot, black_free_brown_slot = (
                self._saved_black_free_slots(previous)
            )
        else:
            black_free_enabled = (
                self._developer_features_are_enabled()
                and bool(black_free_enabled_var.get())
            )
            (
                black_free_black_slot,
                black_free_red_slot,
                black_free_brown_slot,
            ) = self._validate_black_free_gradient_controls()
        refs = [
            ref if ref is not None and ref.matched_hex == physical[index] else None
            for index, ref in enumerate(previous.physical_filament_refs)
        ]
        output_ratios: list[int] | None = None
        if bool(self.black_output_enabled_var.get()):
            previous_output = previous.output_mix_ratios_b
            if previous_output is None:
                slot_index = self._black_output_slot_index()
                output_ratios = black_output_ratio_preset(
                    slot_index, ratios, secondary_ratios
                )
            else:
                slot_index = self._black_output_slot_index()
                previous_preset = black_output_ratio_preset(
                    slot_index,
                    previous.mix_ratios_b,
                    previous.secondary_mix_ratios_b,
                )
                # Keep a GUI-managed preset synchronized when the user edits
                # the target/display ratios.  A non-preset list may be a
                # future or externally calibrated custom recipe, so preserve
                # it byte-for-byte instead of silently normalizing it.
                output_ratios = (
                    black_output_ratio_preset(
                        slot_index, ratios, secondary_ratios
                    )
                    if list(previous_output) == previous_preset
                    else list(previous_output)
                )
        return PaletteSettings(
            material=previous.material,
            palette_state_count=int(self.palette_state_count_var.get()),
            physical_hex=physical,
            enabled_states=[bool(variable.get()) for variable in self.enabled_vars],
            mix_hex_overrides=[None] * 6,
            mix_ratios_b=ratios,
            secondary_mix_ratios_b=secondary_ratios,
            output_mix_ratios_b=output_ratios,
            surface_shell_enabled=False,
            black_free_gradient_enabled=black_free_enabled,
            black_free_black_slot=black_free_black_slot,
            black_free_red_slot=black_free_red_slot,
            black_free_brown_slot=black_free_brown_slot,
            physical_filament_refs=refs,
        )

    def _active_physical_filament_ref(
        self, slot_index: int
    ) -> FilamentSnapshotRef | None:
        """Return the saved product identity for the active F slot, if any."""

        if not 0 <= int(slot_index) < 4:
            return None
        palette = self.settings.palette
        if self.active_part_key is not None:
            palette = resolve_palette_for_part_key(
                self.settings, self.active_part_key
            )
        try:
            ref = palette.physical_filament_refs[int(slot_index)]
            color = normalize_hex(self.physical_vars[int(slot_index)].get())
        except (IndexError, TypeError, ValueError, tk.TclError):
            return None
        return ref if ref is not None and ref.matched_hex == color else None

    def _set_physical_filament_product(
        self, slot_index: int, product: object
    ) -> bool:
        """Assign a product snapshot and HEX to one active physical slot."""

        if not 0 <= int(slot_index) < 4:
            return False
        ref = FilamentSnapshotRef.from_product(product)
        if ref is None:
            return False
        if self.active_part_key is None:
            palette = self.settings.palette
        else:
            # A slot selected while a part is active must become a local
            # palette; mutating the inherited common palette would change
            # every other part unexpectedly.
            palette = self.settings.part_palettes.get(self.active_part_key)
            if palette is None:
                palette = self._copy_palette(
                    resolve_palette_for_part_key(
                        self.settings, self.active_part_key
                    )
                )
                self.settings.part_palettes[self.active_part_key] = palette
        if ref.material != palette.material:
            messagebox.showwarning(
                self.i18n.text("palette.material_mismatch_title"),
                self.i18n.text(
                    "palette.material_mismatch",
                    palette=palette.material,
                    product=ref.material,
                ),
                parent=self.root,
            )
            return False
        palette.physical_hex[int(slot_index)] = ref.matched_hex
        palette.physical_filament_refs[int(slot_index)] = ref
        self.physical_vars[int(slot_index)].set(ref.matched_hex)
        self.enabled_vars[int(slot_index)].set(True)
        # Tk normally commits through the variable trace.  Calling this once
        # explicitly also makes the helper deterministic for isolated tests.
        self._commit_active_palette()
        return True

    def _load_palette_variables(self, palette: PaletteSettings) -> None:
        self._loading_palette_variables = True
        try:
            material_var = getattr(self, "material_var", None)
            if material_var is not None:
                material_var.set(palette.material)
            for variable, value in zip(
                self.physical_vars, palette.physical_hex, strict=True
            ):
                variable.set(value)
            for variable, value in zip(
                self.enabled_vars, palette.enabled_states, strict=True
            ):
                variable.set(value)
            self.extended_palette_var.set(
                all(palette.enabled_states[10 : palette.palette_state_count])
            )
            self.palette_state_count_var.set(palette.palette_state_count)
            for variable, value in zip(
                self.mix_ratio_vars, palette.mix_ratios_b, strict=True
            ):
                variable.set(value)
            for variable, value in zip(
                self.secondary_mix_ratio_vars,
                palette.secondary_mix_ratios_b,
                strict=True,
            ):
                variable.set(value)
            output_enabled = palette.output_mix_ratios_b is not None
            self.black_output_enabled_var.set(output_enabled)
            slot_index = self._infer_black_output_slot(palette)
            self.black_output_slot_var.set(PHYSICAL_NAMES[slot_index])
            black_free_enabled_var = getattr(
                self, "black_free_gradient_enabled_var", None
            )
            if black_free_enabled_var is not None:
                black_slot, red_slot, brown_slot = self._saved_black_free_slots(
                    palette
                )
                black_free_enabled_var.set(
                    bool(
                        getattr(
                            palette, "black_free_gradient_enabled", False
                        )
                    )
                )
                self.black_free_black_slot_var.set(PHYSICAL_NAMES[black_slot])
                self.black_free_red_slot_var.set(PHYSICAL_NAMES[red_slot])
                self.black_free_brown_slot_var.set(PHYSICAL_NAMES[brown_slot])
            surface_shell_var = getattr(
                self, "surface_shell_enabled_var", None
            )
            if surface_shell_var is not None:
                surface_shell_var.set(
                    bool(getattr(palette, "surface_shell_enabled", False))
                )
        finally:
            self._loading_palette_variables = False
        self._refresh_black_free_gradient_widgets(palette)
        self._refresh_black_output_widgets(palette)
        self._refresh_surface_shell_widgets(palette)
        self._refresh_material_mode_buttons(palette.material)

    def _refresh_material_mode_buttons(self, material: str) -> None:
        selected = normalize_filament_material(material)
        labels = {
            MATERIAL_PLA: self.i18n.text("palette.material_pla"),
            MATERIAL_ABS: self.i18n.text("palette.material_abs"),
            MATERIAL_PETG: self.i18n.text("palette.material_petg"),
        }
        for value, button in getattr(self, "material_buttons", {}).items():
            button.configure(
                text=labels[value],
                style="Accent.TButton" if value == selected else "TButton",
                state="disabled" if bool(getattr(self, "busy", False)) else "normal",
            )

    def _commit_active_palette(self) -> PaletteSettings:
        palette = self._palette_from_variables()
        if self.active_part_key is None:
            self.settings.palette = palette
        else:
            self.settings.part_palettes[self.active_part_key] = palette
        return palette

    def _settings_to_variables(self) -> None:
        s = _sanitize_public_settings(self.settings)
        self.active_part_key = None
        self.part_target_var.set(self.i18n.text("parts.common"))
        self._load_palette_variables(s.palette)
        self.height_var.set(s.geometry.height_mm)
        self.target_faces_var.set(s.geometry.target_faces)
        self.preview_faces_var.set(s.geometry.preview_faces)
        self.adjust_face_count_var.set(s.geometry.adjust_face_count)
        self.up_axis_var.set(s.geometry.up_axis)
        self.min_component_var.set(s.geometry.min_component_faces)
        self.mirror_var.set(s.geometry.mirror_x)
        self.preserve_parts_var.set(True)
        self.solidify_parts_var.set(s.geometry.solidify_parts)
        self.repair_unmatched_boundaries_var.set(
            s.geometry.repair_unmatched_boundaries
        )
        self.auto_joints_var.set(False)
        self.joint_width_var.set(s.geometry.joint_width_mm)
        self.joint_height_var.set(s.geometry.joint_height_mm)
        self.joint_depth_var.set(s.geometry.joint_depth_mm)
        self.joint_clearance_var.set(s.geometry.joint_clearance_mm)
        self.joint_min_span_var.set(s.geometry.joint_min_seam_span_mm)
        self.split_enabled_var.set(False)
        self.split_axis_var.set(s.geometry.split_axis)
        self.split_position_var.set(s.geometry.split_position_percent)
        self.split_target_part_var.set(s.geometry.split_target_part + 1)
        self.export_individual_parts_var.set(
            s.geometry.export_individual_parts
        )
        self.black_point_var.set(s.tone.black_point)
        self.white_point_var.set(s.tone.white_point)
        self.gamma_var.set(s.tone.gamma)
        self.contrast_var.set(s.tone.contrast)
        self.saturation_var.set(s.tone.saturation)
        self.pink_protection_var.set(s.tone.pink_protection)
        self.pink_threshold_var.set(s.tone.pink_threshold)
        self.smoothing_var.set(s.tone.smoothing)
        self.smoothing_area_var.set(s.tone.smoothing_max_area_mm2)
        self.smoothing_slack_var.set(s.tone.smoothing_delta_e_slack)
        self.color_depth_enabled_var.set(False)
        self.color_depth_outer_thickness_var.set(
            s.color_depth.outer_thickness_mm
        )
        self._refresh_color_depth_widgets()
        self._refresh_material_mode_buttons(self._active_palette_for_controls().material)
        self._update_face_count_status()

    def _variables_to_settings(self, *, show_error: bool = False) -> AppSettings | None:
        try:
            edited_palette = self._palette_from_variables()
            geometry = GeometrySettings(
                height_mm=float(self.height_var.get()),
                target_faces=int(self.target_faces_var.get()),
                preview_faces=int(self.preview_faces_var.get()),
                adjust_face_count=bool(self.adjust_face_count_var.get()),
                up_axis=self.up_axis_var.get(),
                min_component_faces=int(self.min_component_var.get()),
                mirror_x=bool(self.mirror_var.get()),
                preserve_parts=True,
                solidify_parts=bool(self.solidify_parts_var.get()),
                repair_unmatched_boundaries=bool(
                    self.repair_unmatched_boundaries_var.get()
                ),
                # Hidden experimental assembly controls are deliberately
                # fail-closed on every public settings commit.
                auto_joints=False,
                joint_width_mm=float(self.joint_width_var.get()),
                joint_height_mm=float(self.joint_height_var.get()),
                joint_depth_mm=float(self.joint_depth_var.get()),
                joint_clearance_mm=float(self.joint_clearance_var.get()),
                joint_min_seam_span_mm=float(self.joint_min_span_var.get()),
                split_enabled=False,
                split_axis=self.split_axis_var.get(),
                split_position_percent=float(self.split_position_var.get()),
                split_target_part=max(
                    0, int(self.split_target_part_var.get()) - 1
                ),
                export_individual_parts=bool(
                    self.export_individual_parts_var.get()
                ),
            )
            if (
                geometry.height_mm <= 0
                or geometry.preview_faces < 1_000
                or (
                    geometry.adjust_face_count
                    and geometry.target_faces < 1_000
                )
            ):
                raise ValueError("高さは正数、面数は1,000以上で指定してください")
            if (
                geometry.joint_width_mm <= 0
                or geometry.joint_height_mm <= 0
                or geometry.joint_depth_mm <= 0
                or not 0.05 <= geometry.joint_clearance_mm <= 1.5
                or geometry.joint_min_seam_span_mm <= 0
            ):
                raise ValueError(
                    "ジョイント寸法は正数、クリアランスは0.05～1.5 mmで指定してください"
                )
            if self.manual_joint_record is not None:
                try:
                    joint_height = float(
                        self.manual_joint_record["model_height_mm"]
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "手動ジョイントの造形高さ記録が不正です"
                    ) from exc
                if not np.isclose(
                    geometry.height_mm,
                    joint_height,
                    rtol=0.0,
                    atol=1e-6,
                ):
                    raise ValueError(
                        "手動ジョイントは出力高さ "
                        f"{joint_height:g} mm で生成されています。"
                        "高さを戻すか、［パーツ処理］で手動ジョイントを解除して"
                        "再処理してから配置し直してください"
                    )
            if geometry.split_axis.upper() not in {"X", "Y", "Z"}:
                raise ValueError("分割軸はX・Y・Zから選択してください")
            if not 5.0 <= geometry.split_position_percent <= 95.0:
                raise ValueError("分割位置は5～95%で指定してください")
            tone = ToneSettings(
                black_point=float(self.black_point_var.get()),
                white_point=float(self.white_point_var.get()),
                gamma=float(self.gamma_var.get()),
                contrast=float(self.contrast_var.get()),
                saturation=float(self.saturation_var.get()),
                pink_protection=bool(self.pink_protection_var.get()),
                pink_threshold=float(self.pink_threshold_var.get()),
                smoothing=bool(self.smoothing_var.get()),
                smoothing_max_area_mm2=float(self.smoothing_area_var.get()),
                smoothing_delta_e_slack=float(self.smoothing_slack_var.get()),
            )
            if tone.white_point <= tone.black_point + 0.005:
                raise ValueError("白点は黒点より十分大きくしてください")
            radial = RadialSettings(
                outer_skin_thickness_mm=float(
                    self.radial_skin_thickness_var.get()
                ),
                # The laboratory writer intentionally fixes the first model
                # format to 0.20 mm.  This removes Z-cadence from the radial
                # colour experiment and keeps the Orca preview reproducible.
                layer_height_mm=0.20,
                require_uniform_black_mix=True,
            )
            color_depth = ColorDepthSettings(
                experimental_enabled=False,
                outer_thickness_mm=float(
                    self.color_depth_outer_thickness_var.get()
                ),
                layer_height_mm=0.20,
            )
            part_palettes = {
                key: self._copy_palette(value)
                for key, value in self.settings.part_palettes.items()
            }
            if self.active_part_key is None:
                global_palette = edited_palette
            else:
                global_palette = self._copy_palette(self.settings.palette)
                part_palettes[self.active_part_key] = edited_palette
            self.settings = AppSettings(
                geometry=geometry,
                tone=tone,
                palette=global_palette,
                color_depth=color_depth,
                radial=radial,
                part_palettes=part_palettes,
                part_names=dict(self.settings.part_names),
                manual_view_backgrounds=dict(
                    self.settings.manual_view_backgrounds
                ),
                manual_orbit_inverted=self.settings.manual_orbit_inverted,
            )
            _enforce_black_free_gradient_developer_gate(
                self.settings,
                self._developer_features_are_enabled(),
            )
            return _sanitize_public_settings(self.settings)
        except (ValueError, tk.TclError) as exc:
            if show_error:
                messagebox.showerror(
                    self.i18n.text("dialog.settings.title"),
                    str(exc),
                    parent=self.root,
                )
            return None

    def _load_persistent_settings(self) -> AppSettings:
        self._loaded_developer_features_enabled = False
        path = _configuration_dir() / "settings.json"
        try:
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                self._loaded_developer_features_enabled = (
                    _developer_features_enabled_from_mapping(payload)
                )
                return _persistent_preferences_from_mapping(payload)
        except Exception:
            pass
        return AppSettings()

    def _save_persistent_settings(self) -> None:
        settings = self._variables_to_settings(show_error=False)
        if settings is None:
            return
        path = _configuration_dir() / "settings.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            persistent = _persistent_preferences_payload(
                settings,
                developer_features_enabled=(
                    self._developer_features_are_enabled()
                ),
            )
            path.write_text(
                json.dumps(persistent, ensure_ascii=False, indent=2),
                encoding="utf-8-sig",
            )
        except OSError:
            pass

    def _on_manual_orbit_direction_changed(self, inverted: bool) -> None:
        """Persist the manual editor's global orbit-direction preference."""

        self.settings.manual_orbit_inverted = bool(inverted)
        self._save_persistent_settings()

    def _validated_manual_overrides(
        self,
        *,
        make_copy: bool = False,
        show_error: bool = True,
    ) -> tuple[bool, np.ndarray | None]:
        """Return paint data only when it belongs to the exact current mesh."""

        if self.manual_overrides is None or not np.any(self.manual_overrides >= 0):
            return True, None
        if self.prepared is None:
            message = "色修正に対応する処理済みメッシュがありません。"
        elif len(self.manual_overrides) != len(self.prepared.final.faces):
            message = "色修正の面数が現在のメッシュと一致しません。"
        else:
            current_fingerprint = mesh_fingerprint(self.prepared.final)
            if self.manual_fingerprint != current_fingerprint:
                message = "色修正が別の形状に属しているため、安全に適用できません。"
            else:
                values = np.asarray(self.manual_overrides, dtype=np.int8)
                return True, values.copy() if make_copy else values
        if show_error:
            messagebox.showerror("色修正を適用できません", message, parent=self.root)
        return False, None

    def _choose_obj(self) -> None:
        if self.paint_editor is not None:
            self.paint_editor.close(after_close=self._choose_obj)
            return
        if self.busy:
            messagebox.showinfo(
                self.i18n.text("dialog.busy.title"),
                self.i18n.text("dialog.busy.open_obj"),
                parent=self.root,
            )
            return
        value = filedialog.askopenfilename(
            parent=self.root,
            title=self.i18n.text("filedialog.open_obj"),
            filetypes=(
                (self.i18n.text("filedialog.model"), "*.obj *.glb"),
                ("Wavefront OBJ", "*.obj"),
                ("Binary glTF (GLB)", "*.glb"),
                (self.i18n.text("filedialog.all"), "*.*"),
            ),
        )
        if not value:
            return
        selected_source = Path(value)
        if selected_source.suffix.lower() not in {".obj", ".glb"}:
            messagebox.showerror(
                self.i18n.text("dialog.source_format.title"),
                self.i18n.text("dialog.source_format.message"),
                parent=self.root,
            )
            return
        self._cancel_eyedropper()
        self._note_mix_input_change()
        restoring_project_obj = bool(self._project_obj_recovery_pending)
        if restoring_project_obj:
            # Keep the project-owned tone, global/per-part palettes, names and
            # fingerprint-protected pending edits.  Geometry options must also
            # stay untouched so the saved face topology can be reconstructed.
            self.active_part_key = None
            self._auto_recommend_after_geometry = False
            self.source_path = selected_source
            self.obj_name_var.set(self._source_display_text())
            self._update_face_count_status()

            def finish_project_obj_recovery() -> None:
                self._project_obj_recovery_pending = False

            self._process_geometry(
                reuse_asset=False,
                after_done=finish_project_obj_recovery,
            )
            return
        # A new source starts from its own vertex colours.  Keep only the
        # user-selected 16/24/32 quality level and non-colour preferences;
        # never carry the previous model's black point or filaments forward.
        self.settings = _fresh_settings_for_new_obj(self.settings)
        self.active_part_key = None
        self._sync_tone_variables(self.settings.tone)
        self._load_palette_variables(self.settings.palette)
        self._refresh_palette_widgets(schedule_preview=False)
        self.manual_overrides = None
        self.manual_fingerprint = None
        self.pending_manual_payload = None
        self.manual_part_partition = None
        self.pending_manual_part_partition = None
        self.manual_joint_record = None
        self.pending_manual_joint_record = None
        self.part_recommendations.clear()
        self._clear_mix_optimization_undo()
        self.part_target_var.set(self.i18n.text("parts.common"))
        self.part_name_var.set("")
        self.main_active_part_var.set("")
        self.recommendation_var.set(self.i18n.text("state.recommend_hint"))
        self._auto_recommend_after_geometry = True
        # A newly selected multipart model must always become editable first.
        # Closing/capping is an explicit later action under Part Processing.
        self.solidify_parts_var.set(False)
        self.repair_unmatched_boundaries_var.set(False)
        self.auto_joints_var.set(False)
        self._open_boundary_diagnostics_on_paint = False
        # A newly selected source starts at full clean resolution.  Projects
        # loaded through _load_project_path keep their saved legacy/default
        # face-adjustment setting instead.
        self.adjust_face_count_var.set(False)
        self._manual_high_face_warning_key = None
        self.source_path = selected_source
        self.obj_name_var.set(self._source_display_text())
        self._update_face_count_status()
        self._process_geometry(reuse_asset=False)

    def _choose_reference(self) -> None:
        value = filedialog.askopenfilename(
            parent=self.root,
            title=self.i18n.text("filedialog.open_reference"),
            filetypes=(
                (
                    self.i18n.text("filedialog.image"),
                    "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff",
                ),
                (self.i18n.text("filedialog.all"), "*.*"),
            ),
        )
        if not value:
            return
        try:
            with Image.open(value) as opened:
                self.reference_image = ImageOps.exif_transpose(opened).convert("RGBA")
        except Exception as exc:
            messagebox.showerror(
                self.i18n.text("dialog.open_image_error"),
                str(exc),
                parent=self.root,
            )
            return
        self.reference_path = Path(value)
        self._note_mix_input_change()
        self.ref_name_var.set(f"元画像: {self.reference_path.name}")
        self._draw_comparison_canvas()
        self.status_var.set("元画像を読み込みました。スポイトを開始できます")
        if (
            self.prepared is not None
            and (
                self.manual_overrides is None
                or not bool(np.any(self.manual_overrides >= 0))
            )
        ):
            # The new-OBJ callback already waits for geometry and will include
            # this just-loaded reference image.  Avoid computing the same
            # recommendation twice on a large mesh.
            if self._auto_recommend_after_geometry:
                return
            generation = self._mix_input_generation

            def recommend_when_idle() -> None:
                if generation != self._mix_input_generation:
                    return
                if self.busy:
                    self.root.after(120, recommend_when_idle)
                    return
                self._recommend_all_parts(automatic=True)

            self.root.after(80, recommend_when_idle)

    def _reprocess_geometry(self) -> bool:
        if self.source_path is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.open"),
                parent=self.root,
            )
            return False
        if self.paint_editor is not None:
            self.paint_editor.close(
                after_close=lambda: self._process_geometry(
                    reuse_asset=self.asset is not None
                )
            )
            return True
        return self._process_geometry(reuse_asset=self.asset is not None)

    def _update_face_count_status(self) -> None:
        """Show whether final geometry is full-resolution or adjusted."""

        enabled = bool(self.adjust_face_count_var.get())
        if self.prepared is not None:
            source_faces = int(self.prepared.source.original_face_count)
            clean_faces = int(self.prepared.clean_face_count)
            final_faces = int(len(self.prepared.final.faces))
            key = (
                "geometry.face_status_adjusted"
                if enabled
                else "geometry.face_status_preserved"
            )
            self.face_count_status_var.set(
                self.i18n.text(
                    key,
                    source=source_faces,
                    clean=clean_faces,
                    final=final_faces,
                )
            )
            return
        if self.asset is not None:
            self.face_count_status_var.set(
                self.i18n.text(
                    "geometry.face_status_source",
                    source=int(self.asset.original_face_count),
                )
            )
            return
        self.face_count_status_var.set(
            self.i18n.text(
                "geometry.face_status_waiting_adjusted"
                if enabled
                else "geometry.face_status_waiting_preserved"
            )
        )

    def _set_face_count_mode_and_reprocess(self, enabled: bool) -> None:
        if self.paint_editor is not None:
            self.paint_editor.close(
                after_close=lambda: self._set_face_count_mode_and_reprocess(
                    enabled
                )
            )
            return
        previous_variable = bool(self.adjust_face_count_var.get())
        prepared_mode = (
            bool(self.prepared_key[0] is not None)
            if self.prepared is not None and self.prepared_key
            else previous_variable
        )
        self.adjust_face_count_var.set(enabled)
        self._note_mix_input_change()
        self._manual_high_face_warning_key = None
        self._update_face_count_status()
        if self.source_path is None:
            self._reprocess_geometry()
            return
        started = self._process_geometry(reuse_asset=self.asset is not None)
        if not started:
            # A declined manual-paint/topology confirmation must leave the UI
            # describing the geometry that is still on screen.
            self.adjust_face_count_var.set(prepared_mode)
            self._update_face_count_status()

    def _apply_face_count_adjustment(self) -> None:
        self._set_face_count_mode_and_reprocess(True)

    def _restore_original_face_count(self) -> None:
        """Disable final-mesh reduction and rebuild from the loaded OBJ."""

        self._set_face_count_mode_and_reprocess(False)

    def _update_assembly_status(self) -> None:
        if self.prepared is None:
            self.assembly_status_var.set(
                self.i18n.text("assembly.status_no_model")
            )
            return
        assembly = dict(self.prepared.assembly or {})
        if not assembly:
            self.assembly_status_var.set(
                self.i18n.text("assembly.status_single_model")
            )
            return
        loops = int(assembly.get("open_boundary_loop_count", 0) or 0)
        seams = int(assembly.get("matched_seam_count", 0) or 0)
        unmatched = int(
            assembly.get("unmatched_boundary_loop_count", 0) or 0
        )
        if bool(assembly.get("all_parts_watertight")) and bool(
            assembly.get("single_mesh_generic")
        ):
            self.assembly_status_var.set(
                self.i18n.text("assembly.status_closed_single_glb")
            )
        elif bool(assembly.get("all_parts_watertight")):
            repaired_value = assembly.get(
                "repaired_unmatched_boundary_count"
            )
            if repaired_value is None:
                records = assembly.get("boundary_diagnostics", [])
                repaired_value = sum(
                    bool(item.get("repair_applied"))
                    for item in records
                    if isinstance(item, dict)
                ) if isinstance(records, (list, tuple)) else 0
            repaired = int(repaired_value or 0)
            self.assembly_status_var.set(
                self.i18n.text(
                    "assembly.status_closed",
                    parts=len(self.prepared.final.part_keys),
                    repaired=repaired,
                )
            )
        else:
            self.assembly_status_var.set(
                self.i18n.text(
                    "assembly.status_open",
                    parts=len(self.prepared.final.part_keys),
                    loops=loops,
                    seams=seams,
                    unmatched=unmatched,
                )
            )

    def _keep_original_parts_open(self) -> None:
        if self.source_path is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.open"),
                parent=self.root,
            )
            return
        already_open = (
            self.prepared is not None
            and not bool(dict(self.prepared.assembly or {}).get("solidify_parts"))
        )
        self.solidify_parts_var.set(False)
        self.repair_unmatched_boundaries_var.set(False)
        if already_open:
            self._update_assembly_status()
            self.status_var.set(
                self.i18n.text("assembly.raw_already_active")
            )
            return
        self._process_geometry(reuse_asset=self.asset is not None)

    def _show_boundary_diagnostics(self) -> None:
        if self.prepared is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.process"),
                parent=self.root,
            )
            return
        records = dict(self.prepared.assembly or {}).get(
            "boundary_diagnostics", []
        )
        if not isinstance(records, (list, tuple)) or not records:
            messagebox.showinfo(
                self.i18n.text("assembly.diagnostics_title"),
                self.i18n.text("assembly.no_open_boundaries"),
                parent=self.root,
            )
            return
        self._open_boundary_diagnostics_on_paint = True
        self._open_paint_editor()

    def _solidify_parts_from_paint_editor(self) -> None:
        """Commit Manual Editing first, then use the main safe close flow.

        ``PaintEditorWindow.close`` drains every accepted edit before running
        its ``after_close`` callback.  Keeping this adapter in ``MapperApp``
        means the editor button cannot bypass the same validation, boundary
        diagnostics, recovery, and geometry processing used by the Part
        Processing tab.
        """
        editor = self.paint_editor
        if editor is None:
            self._solidify_parts_now()
            return

        def continue_after_editor_close() -> None:
            # ``on_closed`` normally clears this reference first.  Clear it
            # here as well so the solidification action can never mistake the
            # already-closed editor for a live window and queue a second close.
            if self.paint_editor is editor:
                self.paint_editor = None
            self._solidify_parts_now()

        editor.close(after_close=continue_after_editor_close)

    def _close_parts_safely(self) -> None:
        """Use one public action for closed-solid and small-hole recovery.

        The detailed diagnostics and both original processing callbacks stay
        available internally.  The public action first inspects the prepared
        assembly: a model without unmatched boundary loops takes the ordinary
        solidify path, while a model with small open boundaries takes the
        existing confirm-and-repair path.  This removes a distinction users
        previously had to understand before they could act safely.
        """

        if self.prepared is None or self.source_path is None:
            self._solidify_parts_now()
            return
        assembly = dict(self.prepared.assembly or {})
        unmatched = int(
            assembly.get("unmatched_boundary_loop_count", 0) or 0
        )
        if unmatched > 0:
            self._repair_small_boundaries_and_solidify()
            return
        self._solidify_parts_now()

    def _solidify_parts_now(self) -> None:
        if self.prepared is None or self.source_path is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.process"),
                parent=self.root,
            )
            return
        assembly = dict(self.prepared.assembly or {})
        if not assembly and self.source_path.suffix.lower() not in {
            ".glb",
            ".gltf",
        }:
            messagebox.showinfo(
                self.i18n.text("assembly.solidify_title"),
                self.i18n.text("assembly.single_model_unchanged"),
                parent=self.root,
            )
            return
        if bool(assembly.get("all_parts_watertight")) or bool(
            self.prepared.topology.get("watertight")
        ):
            self.status_var.set(self.i18n.text("assembly.already_closed"))
            return
        unmatched = int(
            assembly.get("unmatched_boundary_loop_count", 0) or 0
        )
        if unmatched:
            messagebox.showwarning(
                self.i18n.text("assembly.solidify_stopped_title"),
                self.i18n.text(
                    "assembly.solidify_stopped_unmatched",
                    count=unmatched,
                ),
                parent=self.root,
            )
            self._show_boundary_diagnostics()
            return
        self.solidify_parts_var.set(True)
        self.repair_unmatched_boundaries_var.set(False)
        self._process_geometry(reuse_asset=True)

    def _repair_small_boundaries_and_solidify(self) -> None:
        if self.prepared is None or self.source_path is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.process"),
                parent=self.root,
            )
            return
        assembly = dict(self.prepared.assembly or {})
        unmatched = int(
            assembly.get("unmatched_boundary_loop_count", 0) or 0
        )
        if unmatched <= 0:
            self._solidify_parts_now()
            return
        records = assembly.get("boundary_diagnostics", [])
        problem_records = [
            item
            for item in records
            if isinstance(item, dict) and not bool(item.get("matched"))
        ] if isinstance(records, (list, tuple)) else []
        largest = max(
            (float(item.get("span_mm", 0.0) or 0.0) for item in problem_records),
            default=0.0,
        )
        if not messagebox.askyesno(
            self.i18n.text("assembly.repair_confirm_title"),
            self.i18n.text(
                "assembly.repair_confirm",
                count=unmatched,
                largest=largest,
            ),
            parent=self.root,
        ):
            return
        self.solidify_parts_var.set(True)
        self.repair_unmatched_boundaries_var.set(True)
        self._process_geometry(reuse_asset=True)

    def _clear_manual_joint_and_reprocess(self) -> None:
        if self.manual_joint_record is None and self.pending_manual_joint_record is None:
            messagebox.showinfo(
                self.i18n.text("assembly.clear_manual_joint"),
                self.i18n.text("assembly.no_manual_joint"),
                parent=self.root,
            )
            return
        if self.paint_editor is not None:
            self.paint_editor.close(after_close=self._clear_manual_joint_and_reprocess)
            return
        if not messagebox.askyesno(
            self.i18n.text("assembly.clear_manual_joint"),
            self.i18n.text("assembly.clear_manual_joint_confirm"),
            parent=self.root,
        ):
            return
        self.manual_joint_record = None
        self.pending_manual_joint_record = None
        self.manual_overrides = None
        self.manual_fingerprint = None
        self.manual_part_partition = None
        self.pending_manual_part_partition = None
        self.pending_manual_payload = None
        self._process_geometry(reuse_asset=self.asset is not None)

    def _process_geometry(self, *, reuse_asset: bool, after_done=None) -> bool:
        if self.paint_editor is not None:
            self.paint_editor.close(
                after_close=lambda: self._process_geometry(
                    reuse_asset=reuse_asset,
                    after_done=after_done,
                )
            )
            return True
        settings = self._variables_to_settings(show_error=True)
        if settings is None or self.source_path is None:
            return False
        previous_prepared = self.prepared
        previous_prepared_key = self.prepared_key
        previous_manual_partition = self.manual_part_partition
        previous_manual_joint = self.manual_joint_record
        joint_payload = (
            self.pending_manual_joint_record
            if self.pending_manual_joint_record is not None
            else previous_manual_joint
        )
        previous_adaptive_store = getattr(
            previous_prepared, "_hotfix_subtriangle_paint", None
        )
        has_manual_paint = bool(
            (
                self.manual_overrides is not None
                and bool(np.any(self.manual_overrides >= 0))
            )
            or (isinstance(previous_adaptive_store, dict) and previous_adaptive_store)
        )
        has_manual_structure = bool(
            self.manual_part_partition
            or self.pending_manual_part_partition
            or self.manual_joint_record
            or self.pending_manual_joint_record
        )
        topology_changed = (
            self.prepared is not None
            and _prepared_paint_topology_key(self.prepared_key)
            != _paint_topology_key(settings.geometry)
        )
        if (has_manual_paint or has_manual_structure) and topology_changed:
            if not messagebox.askyesno(
                "手修正を確認",
                "閉立体化・最終面数・上方向・微小部品・左右反転などで形状を変更します。"
                "パーツ構成が同じ場合はブラシ修正を最も近い面へ引き継ぎますが、"
                "形状によっては解除または確認修正が必要です。\n\n再処理しますか？",
                parent=self.root,
            ):
                self.status_var.set("形状再処理をキャンセルしました。手修正は保持されています")
                return False

        def work():
            asset = (
                self.asset
                if reuse_asset and self.asset is not None
                else load_vertex_color_model(
                    self.source_path,
                    self._thread_progress,
                )
            )
            prepared = prepare_geometry(asset, settings.geometry, self._thread_progress)
            restored_joint = None
            joint_error = None
            if joint_payload is not None:
                try:
                    replayed = replay_manual_joint(
                        prepared,
                        joint_payload,
                        height_mm=float(settings.geometry.height_mm),
                    )
                    prepared = replayed.after
                    restored_joint = dict(replayed.record)
                except ManualJointError as exc:
                    joint_error = str(exc)
            return (
                asset,
                prepared,
                _geometry_key(settings.geometry),
                restored_joint,
                joint_error,
            )

        def done(value) -> None:
            previous_overrides = self.manual_overrides
            previous_fingerprint = self.manual_fingerprint
            (
                self.asset,
                self.prepared,
                self.prepared_key,
                restored_joint,
                joint_error,
            ) = value
            self.manual_joint_record = (
                dict(restored_joint)
                if isinstance(restored_joint, dict)
                else None
            )
            self.pending_manual_joint_record = None
            if joint_error:
                messagebox.showwarning(
                    "手動ジョイントを復元できません",
                    "保存されたジョイントは現在の形状へ安全に再生成できないため、"
                    f"ジョイントなしで開きます。\n\n{joint_error}",
                    parent=self.root,
                )
            self._note_mix_input_change()
            current_fingerprint = mesh_fingerprint(self.prepared.final)
            partition_restored = False
            partition_payload = (
                self.pending_manual_part_partition
                if self.pending_manual_part_partition is not None
                else previous_manual_partition
            )
            if partition_payload is not None:
                try:
                    partitioned_level = decode_manual_part_partition(
                        self.prepared.final,
                        partition_payload,
                        expected_fingerprint=current_fingerprint,
                    )
                    apply_level_partition_to_prepared(
                        self.prepared,
                        partitioned_level,
                    )
                    self.manual_part_partition = encode_manual_part_partition(
                        self.prepared.final,
                        current_fingerprint,
                    )
                    partition_restored = True
                except Exception as exc:
                    self.manual_part_partition = None
                    messagebox.showwarning(
                        "フリーハンド分割を復元できません",
                        f"形状が保存時と異なるため、元のパーツ構成で開きます。\n\n{exc}",
                        parent=self.root,
                    )
                finally:
                    self.pending_manual_part_partition = None
            else:
                self.manual_part_partition = None
            try:
                apply_part_name_overrides(
                    self.prepared,
                    self.settings.part_names,
                )
            except PartNameError as exc:
                # Geometry remains usable even if a hand-edited project JSON
                # contains an invalid or duplicate display name.
                self.settings.part_names = {}
                messagebox.showwarning(
                    self.i18n.text("paint.part_rename_title"),
                    str(exc),
                    parent=self.root,
                )
            restored = False
            paint_remapped = False
            paint_carried_exact = False
            adaptive_trees_carried = 0
            exact_seam_paint_identity = False
            if _is_explicit_single_glb_seam_weld_transition(
                self.source_path,
                previous_prepared,
                self.prepared,
                previous_prepared_key,
                self.prepared_key,
            ):
                try:
                    from smooth_paint_hotfix import (
                        carry_adaptive_trees_if_face_identity_exact,
                    )

                    (
                        exact_seam_paint_identity,
                        adaptive_trees_carried,
                    ) = carry_adaptive_trees_if_face_identity_exact(
                        previous_prepared,
                        self.prepared,
                    )
                except (ImportError, AttributeError, TypeError, ValueError):
                    # Exact carry is an optional preservation optimization.  A
                    # missing/corrupt adaptive store must never make the newly
                    # repaired geometry unusable; root overrides fall through
                    # to the established nearest-face remap below.
                    exact_seam_paint_identity = False
                    adaptive_trees_carried = 0
            if self.pending_manual_payload is not None:
                try:
                    self.manual_overrides = decode_manual_overrides(
                        self.pending_manual_payload,
                        expected_face_count=len(self.prepared.final.faces),
                        expected_fingerprint=current_fingerprint,
                    )
                    restored = True
                except Exception as exc:
                    self.manual_overrides = None
                    messagebox.showwarning(
                        "手修正を復元できません",
                        f"形状が保存時と異なるため、自動変換色で開きます。\n\n{exc}",
                        parent=self.root,
                    )
                finally:
                    self.pending_manual_payload = None
            elif (
                exact_seam_paint_identity
                and previous_overrides is not None
                and len(previous_overrides) == len(self.prepared.final.faces)
            ):
                # Vertex indices and the mesh fingerprint change when duplicate
                # UV-seam vertices are welded.  The ordered triangles and part
                # assignment were proved byte-exact above, so face-indexed root
                # paint can be retained without an approximate remap.
                self.manual_overrides = np.asarray(
                    previous_overrides, dtype=np.int8
                ).copy()
                restored = True
                paint_carried_exact = True
            elif (
                previous_overrides is not None
                and previous_fingerprint == current_fingerprint
                and len(previous_overrides) == len(self.prepared.final.faces)
            ):
                self.manual_overrides = previous_overrides
                restored = True
            elif previous_overrides is not None and previous_prepared is not None:
                try:
                    self.manual_overrides = remap_manual_overrides(
                        previous_prepared.final,
                        self.prepared.final,
                        previous_overrides,
                    )
                    restored = True
                    paint_remapped = True
                except ManualJointStateError:
                    self.manual_overrides = None
            else:
                self.manual_overrides = None
            self.manual_fingerprint = current_fingerprint
            self._refresh_black_free_gradient_widgets()
            self._manual_high_face_warning_key = None
            self._update_face_count_status()
            self._refresh_part_selector()
            part_count = len(self.prepared.final.part_keys)
            new_part_keys = tuple(self.prepared.final.part_keys)
            stale_palette_keys = sorted(
                key
                for key in self.settings.part_palettes
                if key not in set(new_part_keys)
            )
            assembly = dict(self.prepared.assembly or {})
            joint_records = assembly.get("joint_records", [])
            joint_count = (
                len(joint_records)
                if isinstance(joint_records, (list, tuple))
                else 0
            )
            self._update_assembly_status()
            self.status_var.set(
                f"形状準備完了: {len(self.prepared.final.faces):,}面 / "
                f"印刷パーツ {part_count}個 / 閉じた印刷立体={self.prepared.topology['watertight']}"
                + (f" / 組立ジョイント {joint_count}組" if joint_count else "")
                + (" / 手動ジョイントを復元" if restored_joint else "")
                + (f" / 手修正 {int(np.count_nonzero(self.manual_overrides >= 0)):,}面を復元" if restored and self.manual_overrides is not None else "")
                + ("（面順・形状一致で完全引継ぎ）" if paint_carried_exact else "")
                + ("（近傍面へ引継ぎ・要確認）" if paint_remapped else "")
                + (f" / 適応ブラシ {adaptive_trees_carried:,}面を完全引継ぎ" if adaptive_trees_carried else "")
                + (" / フリーハンド分割を復元" if partition_restored else "")
            )
            if stale_palette_keys:
                messagebox.showwarning(
                    "現在のパーツにない基本4色設定",
                    f"以前のパーツ用の基本4色設定 {len(stale_palette_keys)} 件は、"
                    "現在のモデルのパーツへ自動流用していません。\n\n"
                    "［パーツ］タブの［全パーツを自動提案］で"
                    "各パーツの基本4色を更新できます。"
                    "旧設定はプロジェク内に保持されます。",
                    parent=self.root,
                )
            self._schedule_preview(immediate=True)
            if self._auto_recommend_after_geometry:
                expected_obj_path = self.source_path
                self.root.after(
                    80,
                    lambda: self._run_new_obj_auto_recommendation(
                        expected_obj_path
                    ),
                )
            if after_done is not None:
                after_done()

        def failed(exc: Exception, _details: str) -> bool:
            if previous_prepared is not None and self.prepared_key:
                self.adjust_face_count_var.set(
                    bool(self.prepared_key[0] is not None)
                )
                self._update_face_count_status()
            if not bool(settings.geometry.solidify_parts) or previous_prepared is None:
                return False
            previous_assembly = dict(previous_prepared.assembly or {})
            self.solidify_parts_var.set(
                bool(previous_assembly.get("solidify_parts", False))
            )
            self.repair_unmatched_boundaries_var.set(False)
            self._update_assembly_status()
            self.status_var.set(
                self.i18n.text("assembly.solidify_failed_kept_raw")
            )
            inspect_now = messagebox.askyesno(
                self.i18n.text("assembly.solidify_stopped_title"),
                self.i18n.text(
                    "assembly.solidify_failed_detail", error=str(exc)
                ),
                parent=self.root,
            )
            if inspect_now and previous_assembly.get("boundary_diagnostics"):
                self._open_boundary_diagnostics_on_paint = True
                self.root.after(20, self._open_paint_editor)
            return True

        return self._submit_main(
            "モデルを解析・形状準備しています",
            work,
            done,
            on_error=failed,
        )

    @staticmethod
    def _copy_tone_settings(tone: ToneSettings) -> ToneSettings:
        return ToneSettings(
            black_point=float(tone.black_point),
            white_point=float(tone.white_point),
            gamma=float(tone.gamma),
            contrast=float(tone.contrast),
            saturation=float(tone.saturation),
            pink_protection=bool(tone.pink_protection),
            pink_threshold=float(tone.pink_threshold),
            smoothing=bool(tone.smoothing),
            smoothing_max_area_mm2=float(tone.smoothing_max_area_mm2),
            smoothing_delta_e_slack=float(tone.smoothing_delta_e_slack),
        )

    def _sync_tone_variables(self, tone: ToneSettings) -> ToneSettings:
        copied = self._copy_tone_settings(tone)
        if copied.white_point <= copied.black_point + 0.005:
            raise ValueError(self.i18n.text("paint.shading_invalid_points"))
        self.black_point_var.set(copied.black_point)
        self.white_point_var.set(copied.white_point)
        self.gamma_var.set(copied.gamma)
        self.contrast_var.set(copied.contrast)
        self.saturation_var.set(copied.saturation)
        self.pink_protection_var.set(copied.pink_protection)
        self.pink_threshold_var.set(copied.pink_threshold)
        self.smoothing_var.set(copied.smoothing)
        self.smoothing_area_var.set(copied.smoothing_max_area_mm2)
        self.smoothing_slack_var.set(copied.smoothing_delta_e_slack)
        self.settings.tone = copied
        return copied

    def _on_editor_tone_settings_changed(self, tone: ToneSettings) -> None:
        copied = self._sync_tone_variables(tone)
        self._note_mix_input_change()
        editor = self.paint_editor
        if editor is not None:
            editor.reapply_tone_settings(copied)
        self.status_var.set(self.i18n.text("paint.shading_tone_applied"))

    def _on_editor_tone_reset_requested(self) -> None:
        self._on_editor_tone_settings_changed(ToneSettings())

    def _on_editor_palette_settings_changed(
        self, part_key: str | None, palette: PaletteSettings
    ) -> None:
        copied = self._copy_palette(palette)
        if part_key is None:
            self.settings.palette = copied
            change = apply_palette_state_count_change(
                self.settings,
                copied.palette_state_count,
                target_part_key=None,
            )
            copied = change.palette
            status = self.i18n.text(
                "palette.state_count_common_applied",
                count=change.state_count,
                parts=change.updated_part_palettes,
            )
        else:
            self.settings.part_palettes[part_key] = copied
            status = self.i18n.text(
                "palette.state_count_part_applied",
                count=copied.palette_state_count,
            )
        _enforce_black_free_gradient_developer_gate(
            self.settings,
            self._developer_features_are_enabled(),
        )
        copied = (
            self.settings.palette
            if part_key is None
            else self.settings.part_palettes[part_key]
        )
        if part_key == self.active_part_key:
            self._load_palette_variables(copied)
            self._refresh_palette_widgets(schedule_preview=False)
        self._note_mix_input_change()
        self._refresh_part_tree()
        self.status_var.set(status)

    def _on_editor_mix_optimization_requested(
        self, part_key: str | None
    ) -> None:
        if part_key is not None:
            if self.prepared is None or part_key not in self.prepared.final.part_keys:
                return
            self._select_part_key(part_key)

        editor = self.paint_editor
        dialog_parent = editor.window if editor is not None else self.root

        def applied(target_key: str | None, palette: PaletteSettings) -> None:
            current_editor = self.paint_editor
            if current_editor is not None:
                current_editor.reapply_palette_settings(target_key, palette)

        self._optimize_mix_ratios(
            on_applied=applied,
            dialog_parent=dialog_parent,
        )

    def _on_editor_mix_optimization_undo_requested(
        self, part_key: str | None
    ) -> None:
        if self.last_mix_ratios is None or self.last_mix_target_key != part_key:
            editor = self.paint_editor
            if editor is not None:
                editor.status_var.set(
                    self.i18n.text("paint.shading_undo_target_changed")
                )
            return
        if part_key is not None and part_key != self.active_part_key:
            self._select_part_key(part_key)

        def applied(target_key: str | None, palette: PaletteSettings) -> None:
            editor = self.paint_editor
            if editor is not None:
                editor.reapply_palette_settings(target_key, palette)

        self._undo_mix_optimization(on_applied=applied)

    def _open_paint_editor(self) -> None:
        if self.prepared is None or self.source_path is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.process"),
                parent=self.root,
            )
            return
        settings = self._variables_to_settings(show_error=True)
        if settings is None:
            return
        if self.prepared_key != _geometry_key(settings.geometry):
            self._process_geometry(reuse_asset=self.asset is not None, after_done=self._open_paint_editor)
            return
        high_face_warning_key = (id(self.prepared), self.prepared_key)
        if (
            not settings.geometry.adjust_face_count
            and len(self.prepared.final.faces) >= 500_000
            and self._manual_high_face_warning_key != high_face_warning_key
        ):
            if not messagebox.askyesno(
                self.i18n.text("geometry.manual_high_faces_title"),
                self.i18n.text(
                    "geometry.manual_high_faces_warning",
                    count=len(self.prepared.final.faces),
                ),
                parent=self.root,
            ):
                return
            self._manual_high_face_warning_key = high_face_warning_key
        if self.paint_editor is not None:
            try:
                if self.paint_editor.window.winfo_exists():
                    self.paint_editor.window.lift()
                    self.paint_editor.window.focus_force()
                    return
            except tk.TclError:
                self.paint_editor = None

        prepared_holder: list[PreparedGeometry] = [self.prepared]

        def changed(values: np.ndarray) -> None:
            if self.prepared is not prepared_holder[0]:
                self.status_var.set("形状が変わったため、旧メッシュの色修正を破棄しました")
                return
            self.manual_overrides = np.asarray(values, dtype=np.int8).copy()
            self.manual_fingerprint = mesh_fingerprint(
                prepared_holder[0].final
            )
            self._note_mix_input_change()
            count = int(np.count_nonzero(self.manual_overrides >= 0))
            self._refresh_black_free_gradient_widgets()
            self.status_var.set(f"色修正を保持中: {count:,}面")

        def parts_changed() -> None:
            if self.prepared is not prepared_holder[0]:
                return
            self.settings.part_names.update(
                collect_part_name_overrides(self.prepared)
            )
            for key in self.prepared.final.part_keys:
                if key in self.settings.part_palettes or "/cut:" not in key:
                    continue
                parent_key = key.rsplit("/cut:", 1)[0]
                inherit_explicit_part_palette(
                    self.settings,
                    parent_key,
                    key,
                )
            self.manual_part_partition = encode_manual_part_partition(
                self.prepared.final,
                mesh_fingerprint(self.prepared.final),
            )
            self._note_mix_input_change()
            self._refresh_part_selector()
            self.status_var.set(
                f"フリーハンド分割を保持中: "
                f"印刷パーツ {len(self.prepared.final.part_keys)}個"
            )

        def geometry_changed(
            prepared: PreparedGeometry,
            overrides: np.ndarray,
            record: dict[str, object] | None,
        ) -> None:
            self.prepared = prepared
            prepared_holder[0] = prepared
            self.manual_overrides = np.asarray(
                overrides, dtype=np.int8
            ).copy()
            self.manual_fingerprint = mesh_fingerprint(prepared.final)
            self.manual_joint_record = (
                None if record is None else dict(record)
            )
            self.pending_manual_joint_record = None
            self.settings.part_names.update(
                collect_part_name_overrides(prepared)
            )
            self.preview_colors = None
            self.source_render = None
            self.target_render = None
            self._note_mix_input_change()
            self._refresh_part_selector()
            self._refresh_black_free_gradient_widgets()
            count = int(np.count_nonzero(self.manual_overrides >= 0))
            self.status_var.set(
                (
                    "手動ジョイントを保持中"
                    if self.manual_joint_record is not None
                    else "ジョイント生成前の形状を復元"
                )
                + f" / 手修正 {count:,}面"
            )

        def part_name_changed(part_key: str, name: str) -> None:
            if self.prepared is not prepared_holder[0]:
                return
            self.settings.part_names[str(part_key)] = str(name)
            self._refresh_part_selector()
            self.status_var.set(
                self.i18n.text("paint.part_renamed", name=str(name))
            )

        def view_background_changed(model_key: str, mode: str) -> None:
            if self.prepared is not prepared_holder[0]:
                return
            self.settings.manual_view_backgrounds[str(model_key)] = str(mode)

        def closed() -> None:
            self.paint_editor = None
            if not self.app_closing:
                self._schedule_preview(immediate=True)

        try:
            show_boundary_diagnostics = bool(
                self._open_boundary_diagnostics_on_paint
            )
            self.paint_editor = PaintEditorWindow(
                self.root,
                self.prepared,
                settings,
                self.reference_image,
                self.manual_overrides,
                changed,
                closed,
                on_parts_changed=parts_changed,
                on_geometry_changed=geometry_changed,
                language=self.i18n.language,
                show_boundary_diagnostics=show_boundary_diagnostics,
                on_part_name_changed=part_name_changed,
                on_view_background_changed=view_background_changed,
                on_orbit_direction_changed=(
                    self._on_manual_orbit_direction_changed
                ),
                on_solidify_requested=self._solidify_parts_from_paint_editor,
                on_tone_settings_changed=self._on_editor_tone_settings_changed,
                on_palette_settings_changed=(
                    self._on_editor_palette_settings_changed
                ),
                on_mix_optimization_requested=(
                    self._on_editor_mix_optimization_requested
                ),
                on_mix_optimization_undo_requested=(
                    self._on_editor_mix_optimization_undo_requested
                ),
                on_tone_reset_requested=self._on_editor_tone_reset_requested,
            )
            self._set_mix_optimization_undo_enabled(
                getattr(self, "last_mix_ratios", None) is not None
                and getattr(self, "last_mix_target_key", None)
                == getattr(self, "active_part_key", None)
            )
            # Manual Editing is a full workspace now.  Start maximized while
            # keeping the normal Windows title bar; F11 remains available for
            # a temporary borderless view.
            maximize_editor = getattr(self.paint_editor, "maximize", None)
            if callable(maximize_editor):
                maximize_editor()
            active_part_key = getattr(self, "active_part_key", None)
            if active_part_key is not None:
                select_part = getattr(self.paint_editor, "select_part_by_key", None)
                if callable(select_part):
                    select_part(active_part_key)
            self._open_boundary_diagnostics_on_paint = False
        except Exception as exc:
            self.paint_editor = None
            self._open_boundary_diagnostics_on_paint = False
            messagebox.showerror(
                self.i18n.text("dialog.open_paint_error"),
                str(exc),
                parent=self.root,
            )

    def _thread_progress(self, phase: str, fraction: float, message: str) -> None:
        self.work_queue.put(("progress", (phase, fraction, message)))

    def _submit_main(self, label: str, function, done, *, on_error=None) -> bool:
        if self.busy:
            messagebox.showinfo(
                self.i18n.text("dialog.busy.title"),
                self.i18n.text("dialog.busy.message"),
                parent=self.root,
            )
            return False
        self.busy = True
        self.progress["value"] = 0
        self.status_var.set(label)
        self.export_button.state(["disabled"])
        calibration_button = getattr(self, "calibration_chart_button", None)
        if calibration_button is not None:
            calibration_button.state(["disabled"])
        color_depth_button = getattr(
            self, "color_depth_export_button", None
        )
        if color_depth_button is not None:
            color_depth_button.state(["disabled"])
        self._refresh_black_free_gradient_widgets()
        self._refresh_black_output_widgets()
        self._refresh_surface_shell_widgets()
        self._refresh_developer_feature_visibility()
        self._refresh_color_depth_widgets()

        def runner() -> None:
            try:
                self.work_queue.put(("main_done", (done, function(), on_error)))
            except Exception as exc:
                self.work_queue.put(
                    (
                        "main_error",
                        (exc, traceback.format_exc(), on_error),
                    )
                )

        self.main_executor.submit(runner)
        return True

    def _poll_queue(self) -> None:
        self.poll_after_id = None
        try:
            while True:
                kind, payload = self.work_queue.get_nowait()
                if kind == "progress":
                    _phase, fraction, message = payload
                    self.progress["value"] = float(fraction) * 100.0
                    self.status_var.set(str(message))
                elif kind == "main_done":
                    if len(payload) == 3:
                        done, value, on_error = payload
                    else:  # Backward-compatible with already queued/test payloads.
                        done, value = payload
                        on_error = None
                    self.busy = False
                    self.progress["value"] = 100
                    self.export_button.state(["!disabled"])
                    calibration_button = getattr(
                        self, "calibration_chart_button", None
                    )
                    if calibration_button is not None:
                        calibration_button.state(["!disabled"])
                    self._refresh_color_depth_widgets()
                    self._refresh_black_free_gradient_widgets()
                    self._refresh_black_output_widgets()
                    self._refresh_surface_shell_widgets()
                    self._refresh_developer_feature_visibility()
                    self._refresh_material_mode_buttons(
                        self._active_palette_for_controls().material
                    )
                    try:
                        done(value)
                    except Exception as exc:
                        details = traceback.format_exc()
                        self.progress["value"] = 0
                        self.status_var.set(f"エラー: {exc}")
                        handled = False
                        if callable(on_error):
                            try:
                                handled = bool(on_error(exc, details))
                            except Exception:
                                handled = False
                        if not handled:
                            messagebox.showerror(
                                "処理できませんでした",
                                f"{exc}\n\n詳細は下記です。\n{details[-1800:]}",
                                parent=self.root,
                            )
                elif kind == "main_error":
                    if len(payload) == 3:
                        exc, details, on_error = payload
                    else:  # Backward-compatible with queued work from tests/hotfixes.
                        exc, details = payload
                        on_error = None
                    self.busy = False
                    self.progress["value"] = 0
                    self.export_button.state(["!disabled"])
                    calibration_button = getattr(
                        self, "calibration_chart_button", None
                    )
                    if calibration_button is not None:
                        calibration_button.state(["!disabled"])
                    self._refresh_color_depth_widgets()
                    self._refresh_black_free_gradient_widgets()
                    self._refresh_black_output_widgets()
                    self._refresh_surface_shell_widgets()
                    self._refresh_developer_feature_visibility()
                    self._refresh_material_mode_buttons(
                        self._active_palette_for_controls().material
                    )
                    self.status_var.set(f"エラー: {exc}")
                    handled = False
                    if callable(on_error):
                        try:
                            handled = bool(on_error(exc, details))
                        except Exception:
                            handled = False
                    if not handled:
                        messagebox.showerror("処理できませんでした", f"{exc}\n\n詳細は下記です。\n{details[-1800:]}", parent=self.root)
                elif kind == "preview_done":
                    if len(payload) == 6:
                        generation, selection_key, colors, source, target, mean = payload
                    else:
                        generation, colors, source, target, mean = payload
                        selection_key = self.active_part_key
                    if (
                        generation == self.preview_generation
                        and selection_key == self.active_part_key
                    ):
                        self.preview_colors = colors
                        self.source_render = source
                        self.target_render = target
                        self._draw_comparison_canvas()
                        suffix = (
                            f" / 手修正 {colors.manual_override_faces:,}面"
                            if colors.manual_override_faces
                            else ""
                        )
                        self.status_var.set(
                            f"プレビュー更新: 平均ΔE76 {mean:.1f} / "
                            f"F4系 {colors.pink_area_fraction * 100:.2f}%{suffix}"
                        )
                elif kind == "preview_error":
                    if len(payload) == 3:
                        generation, selection_key, exc = payload
                    else:
                        generation, exc = payload
                        selection_key = self.active_part_key
                    if (
                        generation == self.preview_generation
                        and selection_key == self.active_part_key
                    ):
                        self.status_var.set(f"プレビューを作成できません: {exc}")
        except queue.Empty:
            pass
        if not self.app_closing and self.root.winfo_exists():
            self.poll_after_id = self.root.after(80, self._poll_queue)

    def _on_palette_changed(self) -> None:
        if self._loading_palette_variables:
            return
        black_free_enabled_var = getattr(
            self, "black_free_gradient_enabled_var", None
        )
        if black_free_enabled_var is not None and bool(
            black_free_enabled_var.get()
        ):
            try:
                self._validate_black_free_gradient_controls()
            except (ValueError, tk.TclError) as exc:
                self._load_palette_variables(self._active_palette_for_controls())
                messagebox.showerror(
                    self.i18n.text("palette.black_free_invalid_title"),
                    str(exc),
                    parent=self.root,
                )
                return
        try:
            self._commit_active_palette()
            if self.active_part_key is not None:
                self.part_recommendations.pop(self.active_part_key, None)
        except (ValueError, tk.TclError):
            pass
        self._note_mix_input_change()
        self._refresh_palette_widgets(schedule_preview=False)
        self._refresh_black_free_gradient_widgets()
        self._refresh_black_output_widgets()
        self._refresh_surface_shell_widgets()
        self._refresh_part_tree()
        if self.sample_rgb is not None:
            self._update_recipe_candidates()
        self._schedule_preview(immediate=True)

    def _on_extended_palette_changed(self) -> None:
        enabled = bool(self.extended_palette_var.get())
        count = int(self.palette_state_count_var.get())
        self._loading_palette_variables = True
        try:
            for index, variable in enumerate(self.enabled_vars[10:], start=10):
                variable.set(enabled if index < count else False)
        finally:
            self._loading_palette_variables = False
        self._on_palette_changed()
        self.status_var.set(
            f"{PALETTE_STATE_COUNT}色の滑らかパレットを有効にしました"
            if enabled
            else (
                f"追加{PALETTE_STATE_COUNT - 10}色を無効にし、"
                "従来10色で割り当てます"
            )
        )

    def _on_palette_state_count_changed(self, _event=None) -> None:
        if self._loading_palette_variables:
            return
        count = int(self.palette_state_count_var.get())
        previous = int(getattr(self.settings.palette, "palette_state_count", 16))
        if self.active_part_key is not None:
            previous = resolve_palette_for_part_key(
                self.settings, self.active_part_key
            ).palette_state_count
        self._loading_palette_variables = True
        try:
            for index, variable in enumerate(self.enabled_vars):
                if index >= count:
                    variable.set(False)
                elif index >= previous:
                    variable.set(True)
        finally:
            self._loading_palette_variables = False
        self._on_palette_changed()
        change = apply_palette_state_count_change(
            self.settings,
            count,
            target_part_key=self.active_part_key,
        )
        if self.active_part_key is None:
            self.part_recommendations.clear()
            status = self.i18n.text(
                "palette.state_count_common_applied",
                count=change.state_count,
                parts=change.updated_part_palettes,
            )
        else:
            status = self.i18n.text(
                "palette.state_count_part_applied",
                count=change.state_count,
            )
        editor = getattr(self, "paint_editor", None)
        if editor is not None:
            if self.active_part_key is None:
                reapply = getattr(editor, "reapply_shading_settings", None)
                if callable(reapply):
                    reapply(self.settings, message=status)
            else:
                reapply = getattr(editor, "reapply_palette_settings", None)
                if callable(reapply):
                    reapply(
                        self.active_part_key,
                        change.palette,
                        message=status,
                    )
        self._refresh_part_tree()
        self._schedule_preview(immediate=True)
        self.status_var.set(status)

    def _on_tone_changed(self) -> None:
        self._note_mix_input_change()
        self._schedule_preview()

    def _on_height_changed(self) -> None:
        self._note_mix_input_change()
        if self.manual_joint_record is not None:
            try:
                current = float(self.height_var.get())
                created = float(self.manual_joint_record["model_height_mm"])
            except (KeyError, TypeError, ValueError, tk.TclError):
                current = created = 0.0
            if not np.isclose(current, created, rtol=0.0, atol=1e-6):
                self.status_var.set(
                    "手動ジョイントの寸法を維持するには、出力高さを戻すか"
                    "［パーツ処理］でジョイントを解除して配置し直してください"
                )
                return
        self._schedule_preview()

    def _clear_mix_optimization_undo(self) -> None:
        self.last_mix_ratios = None
        self.last_mix_target_key = None
        self._set_mix_optimization_undo_enabled(False)

    def _set_mix_optimization_undo_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        button = getattr(self, "undo_mix_button", None)
        if button is not None:
            button.configure(state=state)
        editor = getattr(self, "paint_editor", None)
        editor_button = (
            getattr(editor, "mix_optimization_undo_button", None)
            if editor is not None
            else None
        )
        if editor_button is not None:
            editor_button.configure(state=state)

    def _note_mix_input_change(self) -> None:
        if self._applying_mix_result:
            return
        self._mix_input_generation += 1
        self._clear_mix_optimization_undo()

    def _mix_optimization_snapshot(
        self,
        settings: AppSettings,
    ) -> tuple[object, ...]:
        return (
            self._mix_input_generation,
            id(self.prepared),
            str(self.source_path) if self.source_path is not None else None,
            self.prepared_key,
            id(self.paint_editor) if self.paint_editor is not None else None,
            _mix_optimizer_settings_key(settings),
            self.manual_fingerprint,
            _manual_overrides_signature(self.manual_overrides),
        )

    def _refresh_palette_widgets(self, *, schedule_preview: bool) -> None:
        try:
            physical = [normalize_hex(variable.get()) for variable in self.physical_vars]
            ratios = [int(variable.get()) for variable in self.mix_ratio_vars]
            secondary_ratios = [
                int(variable.get())
                for variable in self.secondary_mix_ratio_vars
            ]
            palette_hex, _ = build_palette_rgb(
                physical, [None] * 6, ratios, secondary_ratios
            )
        except (ValueError, tk.TclError):
            return
        for button, color in zip(self.physical_swatch_buttons, palette_hex[:4], strict=True):
            button.configure(bg=color, activebackground=color)
        def readable_text(color: str) -> str:
            value = normalize_hex(color)
            red, green, blue = (
                int(value[index : index + 2], 16) for index in (1, 3, 5)
            )
            luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
            return "#111111" if luminance >= 145.0 else "#FFFFFF"

        for label, color in zip(
            self.mix_swatch_labels, palette_hex[4:10], strict=True
        ):
            label.configure(bg=color, fg=readable_text(color))
        count = int(self.palette_state_count_var.get())
        for offset, (label, color) in enumerate(
            zip(
                self.additional_mix_swatch_labels,
                palette_hex[16:32],
                strict=True,
            )
        ):
            state = 16 + offset
            if state < count:
                label.grid()
                label.configure(bg=color, fg=readable_text(color))
            else:
                label.grid_remove()
        for label, color in zip(
            self.secondary_mix_swatch_labels,
            palette_hex[10:16],
            strict=True,
        ):
            label.configure(bg=color, fg=readable_text(color))
        self._layout_mix_family_cells()
        if schedule_preview:
            self._schedule_preview()

    def _refresh_part_selector(self) -> None:
        common_label = self.i18n.text("parts.common")
        labels = [common_label]
        self.part_label_to_key = {common_label: None}
        if self.prepared is not None:
            for index, (name, key) in enumerate(
                zip(
                    self.prepared.final.part_names,
                    self.prepared.final.part_keys,
                    strict=True,
                ),
                start=1,
            ):
                label = f"{index}: {name}"
                labels.append(label)
                self.part_label_to_key[label] = key
        self.part_selector.configure(values=tuple(labels))
        valid_keys = set(self.part_label_to_key.values())
        if self.active_part_key not in valid_keys:
            self.active_part_key = None
        selected_label = next(
            (
                label
                for label, key in self.part_label_to_key.items()
                if key == self.active_part_key
            ),
            common_label,
        )
        self.part_target_var.set(selected_label)
        self._sync_main_part_name_controls()
        self._sync_main_active_part_label()
        self._refresh_part_tree()

    def _sync_main_part_name_controls(self) -> None:
        entry = getattr(self, "main_part_name_entry", None)
        button = getattr(self, "main_part_rename_button", None)
        variable = getattr(self, "part_name_var", None)
        if entry is None or button is None or variable is None:
            return
        enabled = False
        name = ""
        if self.prepared is not None and self.active_part_key is not None:
            try:
                part_id = self.prepared.final.part_keys.index(self.active_part_key)
                name = str(self.prepared.final.part_names[part_id])
                enabled = True
            except (ValueError, IndexError):
                pass
        variable.set(name)
        entry.configure(state="normal" if enabled else "disabled")
        button.configure(state="normal" if enabled else "disabled")

    def _sync_main_active_part_label(self) -> None:
        variable = getattr(self, "main_active_part_var", None)
        if variable is None:
            return
        if self.prepared is None or self.active_part_key is None:
            variable.set("")
            return
        try:
            part_id = self.prepared.final.part_keys.index(self.active_part_key)
            name = str(self.prepared.final.part_names[part_id])
        except (ValueError, IndexError):
            variable.set("")
            return
        variable.set(f"{self.i18n.text('main.active_outline_help')}: {name}")

    def _rename_selected_part(self) -> None:
        """Rename only display/export metadata, retaining the immutable key."""

        if self.prepared is None or self.active_part_key is None:
            messagebox.showinfo(
                self.i18n.text("paint.part_rename_title"),
                (
                    self.i18n.text("main.select_part_to_rename")
                ),
                parent=self.root,
            )
            return
        try:
            name = rename_prepared_part(
                self.prepared,
                self.active_part_key,
                self.part_name_var.get(),
            )
        except PartNameError as exc:
            messagebox.showerror(
                self.i18n.text("paint.part_rename_title"),
                str(exc),
                parent=self.root,
            )
            return
        self.settings.part_names[str(self.active_part_key)] = name
        self._refresh_part_selector()
        self.status_var.set(self.i18n.text("paint.part_renamed", name=name))

    def _refresh_part_tree(self) -> None:
        if not hasattr(self, "part_tree"):
            return
        self.part_tree.delete(*self.part_tree.get_children())
        global_hex = " ".join(self.settings.palette.physical_hex)
        total_faces = (
            len(self.prepared.final.faces) if self.prepared is not None else 0
        )
        self.part_tree.insert(
            "",
            "end",
            iid="__global__",
            text=self.i18n.text("parts.common"),
            values=(
                f"{total_faces:,}" if total_faces else "-",
                self.i18n.text("parts.common_short"),
                global_hex,
            ),
        )
        if self.prepared is None:
            self.part_status_var.set(
                self.i18n.text("state.parts_detected_hint")
            )
            return
        face_part_ids = np.asarray(self.prepared.final.face_part_ids)
        for part_id, (name, key) in enumerate(
            zip(
                self.prepared.final.part_names,
                self.prepared.final.part_keys,
                strict=True,
            )
        ):
            palette = resolve_palette_for_part_key(self.settings, key)
            individual = key in self.settings.part_palettes
            self.part_tree.insert(
                "",
                "end",
                iid=f"part:{part_id}",
                text=name,
                values=(
                    f"{int(np.count_nonzero(face_part_ids == part_id)):,}",
                    self.i18n.text(
                        "parts.individual_short"
                        if individual
                        else "parts.common_short"
                    ),
                    " ".join(palette.physical_hex),
                ),
            )
        try:
            plan = plan_palette_groups(self.settings, self.prepared.final)
            print_text = (
                "全パーツが同じ物理4色なので、1回の印刷ジョブにできます。"
                if plan.one_job
                else (
                    f"物理4色の構成が{len(plan.groups)}グループあります。"
                    "このまま1回の印刷ジョブにはできません。"
                )
            )
        except ValueError as exc:
            print_text = f"パーツ設定を確認してください: {exc}"
        if self.active_part_key is None:
            target_text = self.i18n.text("parts.common")
        else:
            try:
                part_id = self.prepared.final.part_keys.index(self.active_part_key)
                target_text = self.prepared.final.part_names[part_id]
            except (ValueError, IndexError):
                target_text = self.active_part_key
        target_text = (
            f"{target_text} is being edited"
            if self.i18n.language == "en"
            else f"{target_text} を編集中"
        )
        self.part_status_var.set(f"{target_text}\n{print_text}")
        iid = "__global__"
        if self.active_part_key is not None:
            try:
                iid = f"part:{self.prepared.final.part_keys.index(self.active_part_key)}"
            except ValueError:
                iid = "__global__"
        if self.part_tree.exists(iid):
            self.part_tree.selection_set(iid)

    def _select_part_key(self, part_key: str | None) -> None:
        if part_key == self.active_part_key:
            return
        try:
            self._commit_active_palette()
        except (ValueError, tk.TclError):
            messagebox.showerror(
                "色設定を確認してください",
                "現在の基本色または混色比率が不正なため、パーツを切り替えられません。",
                parent=self.root,
            )
            return
        self.active_part_key = part_key
        palette = (
            self.settings.palette
            if part_key is None
            else resolve_palette_for_part_key(self.settings, part_key)
        )
        self._load_palette_variables(palette)
        selected_label = next(
            (
                label
                for label, key in self.part_label_to_key.items()
                if key == part_key
            ),
            self.i18n.text("parts.common"),
        )
        self.part_target_var.set(selected_label)
        self._sync_main_part_name_controls()
        self._sync_main_active_part_label()
        self._refresh_palette_widgets(schedule_preview=True)
        self._refresh_part_tree()
        if self.filament_candidate_window is not None:
            try:
                self.filament_candidate_window._refresh_auto_target()
            except (AttributeError, tk.TclError):
                pass
        if self.sample_rgb is not None:
            self._update_recipe_candidates()

    def _on_part_selected(self, _event=None) -> None:
        self._select_part_key(
            self.part_label_to_key.get(self.part_target_var.get())
        )

    def _on_part_tree_selected(self, _event=None) -> None:
        selection = self.part_tree.selection()
        if not selection:
            return
        iid = selection[0]
        if iid == "__global__":
            self._select_part_key(None)
            return
        if self.prepared is None or not iid.startswith("part:"):
            return
        try:
            part_id = int(iid.split(":", 1)[1])
            key = self.prepared.final.part_keys[part_id]
        except (ValueError, IndexError):
            return
        self._select_part_key(key)

    def _copy_palette_to_all_parts(self) -> None:
        if self.prepared is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.open"),
                parent=self.root,
            )
            return
        try:
            palette = self._commit_active_palette()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("色設定を確認してください", str(exc), parent=self.root)
            return
        for key in self.prepared.final.part_keys:
            self.settings.part_palettes[key] = self._copy_palette(palette)
        self._refresh_part_tree()
        self._schedule_preview(immediate=True)
        self.status_var.set("現在の基本4色と混色比率を全パーツへコピーしました")

    def _clear_selected_part_palette(self) -> None:
        if self.active_part_key is None:
            self.status_var.set("全体共通設定は解除できません")
            return
        key = self.active_part_key
        self.settings.part_palettes.pop(key, None)
        self._load_palette_variables(self.settings.palette)
        self._refresh_palette_widgets(schedule_preview=True)
        self._refresh_part_tree()
        self.status_var.set(f"{key} を全体共通の基本4色へ戻しました")

    def _reference_samples_for_recommendation(
        self,
    ) -> tuple[np.ndarray | None, float, str]:
        if self.reference_image is None:
            return None, 0.0, "元画像なし: 読み込んだモデルの色だけで判定"
        image = self.reference_image.copy()
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        extraction = extract_corner_foreground(image)
        samples = extraction.rgb[extraction.mask]
        if len(samples) < 64:
            samples = extraction.rgb.reshape(-1, 3)
            confidence = 0.08
            note = "前景が小さいため低信頼の画像全体色を補助ヒントとして使用"
        else:
            confidence = 0.20
            note = "元画像の背景除外色を全体の補助ヒントとして使用"
        if len(samples) > 20_000:
            step = int(np.ceil(len(samples) / 20_000))
            samples = samples[::step]
        return samples, confidence, note

    @staticmethod
    def _palette_from_recommendation(
        recommendation: FilamentRecommendation,
        palette_state_count: int = 16,
        *,
        material: str = "PLA",
        surface_shell_enabled: bool = False,
        black_free_gradient_enabled: bool = False,
        black_free_black_slot: int = 0,
        black_free_red_slot: int = 2,
        black_free_brown_slot: int = 3,
    ) -> PaletteSettings:
        candidates = tuple(getattr(recommendation, "candidates", ()))
        refs = [FilamentSnapshotRef.from_product(item) for item in candidates[:4]]
        refs.extend([None] * (4 - len(refs)))
        return PaletteSettings(
            material=material,
            palette_state_count=palette_state_count,
            physical_hex=list(recommendation.physical_hex),
            enabled_states=[True] * PALETTE_STATE_COUNT,
            mix_hex_overrides=[None] * 6,
            mix_ratios_b=[recommendation.primary_ratio_b_percent] * 6,
            secondary_mix_ratios_b=[
                recommendation.secondary_ratio_b_percent
            ] * 6,
            surface_shell_enabled=False,
            black_free_gradient_enabled=black_free_gradient_enabled,
            black_free_black_slot=black_free_black_slot,
            black_free_red_slot=black_free_red_slot,
            black_free_brown_slot=black_free_brown_slot,
            physical_filament_refs=refs,
        )

    def _recommend_part_ids(
        self,
        part_ids: tuple[int, ...],
        *,
        whole_model: bool = False,
        automatic: bool = False,
    ) -> None:
        if self.prepared is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.open"),
                parent=self.root,
            )
            return
        settings = self._variables_to_settings(show_error=True)
        if settings is None:
            return
        prepared = self.prepared
        all_part_ids = tuple(range(len(prepared.final.part_keys)))
        include_global = whole_model or tuple(part_ids) == all_part_ids
        requested_part_ids = tuple(part_ids)
        active_part_at_request = self.active_part_key
        input_snapshot = (
            self._mix_optimization_snapshot(settings),
            active_part_at_request,
            requested_part_ids,
            bool(whole_model),
        )
        reference_image = (
            self.reference_image.copy()
            if self.reference_image is not None
            else None
        )
        global_reference_rgb: np.ndarray | None = None
        global_reference_confidence = 0.0
        global_reference_note = "元画像なし: 読み込んだモデルの色だけで判定"
        if include_global:
            (
                global_reference_rgb,
                global_reference_confidence,
                global_reference_note,
            ) = (
                self._reference_samples_for_recommendation()
            )

        def work():
            tone_vertices = apply_tone(
                prepared.final.vertex_colors, settings.tone
            )
            face_rgb = tone_vertices[prepared.final.faces].mean(axis=1)
            face_part_ids = np.asarray(prepared.final.face_part_ids)
            results: dict[str, FilamentRecommendation] = {}
            catalogs: dict[str, tuple[FilamentCandidate, ...]] = {}
            catalog_unique_counts: dict[str, int] = {}

            def catalog_for(material: str) -> tuple[FilamentCandidate, ...]:
                selected_material = normalize_filament_material(material)
                cached = catalogs.get(selected_material)
                if cached is not None:
                    return cached
                try:
                    from .filament_database import FilamentRepository

                    products = FilamentRepository().list_products(
                        material=selected_material
                    )
                except Exception:
                    if selected_material == MATERIAL_PLA:
                        # Preserve the established offline PLA workflow.  ABS
                        # and PETG never borrow PLA candidates.
                        from .filament_recommender import DEFAULT_CURATED_CATALOG

                        cached = tuple(DEFAULT_CURATED_CATALOG)
                        catalogs[selected_material] = cached
                        catalog_unique_counts[selected_material] = len(
                            {candidate.hex_color for candidate in cached}
                        )
                        return cached
                    raise ValueError(
                        self.i18n.text(
                            "palette.material_catalog_unavailable",
                            material=selected_material,
                        )
                    )
                preferred = tuple(
                    product
                    for product in products
                    if str(product.finish_class) in {"標準/不透明", "マット"}
                )
                usable = preferred if len({p.matched_hex for p in preferred}) >= 4 else products
                unique_count = len({product.matched_hex for product in usable})
                if unique_count < 4:
                    raise ValueError(
                        self.i18n.text(
                            "palette.material_need_four",
                            material=selected_material,
                            count=unique_count,
                        )
                    )
                product_catalog = tuple(
                    FilamentCandidate(
                        id=product.product_id,
                        label=product.label,
                        hex_color=product.matched_hex,
                        category=CATEGORY_PRIMARY,
                        material=product.material,
                        brand=product.brand,
                        series=product.series,
                        color_name=product.color_name,
                        finish_class=product.finish_class,
                        source_kind=product.source_kind,
                        source_url=product.source_url,
                        record_id=product.record_id,
                        measurement_id=product.measurement_id,
                    )
                    for product in usable
                )
                cached = map_catalog_to_curated_basics(product_catalog)
                catalogs[selected_material] = cached
                catalog_unique_counts[selected_material] = unique_count
                return cached
            reference_match: ReferencePartMatch | None = None
            reference_by_part = {}
            used_reference_part_ids: set[int] = set()
            if reference_image is not None and not whole_model:
                reference_match = match_reference_to_parts(
                    prepared.preview,
                    reference_image,
                )
                reference_by_part = reference_match.samples_by_part_id
            if whole_model:
                selections = (("__global__", np.arange(len(face_rgb))),)
            else:
                part_selections = tuple(
                    (
                        prepared.final.part_keys[part_id],
                        np.flatnonzero(face_part_ids == part_id),
                    )
                    for part_id in part_ids
                )
                selections = (
                    (("__global__", np.arange(len(face_rgb))),)
                    + part_selections
                    if include_global
                    else part_selections
                )
            for key, selected in selections:
                local_palette = (
                    settings.palette
                    if key == "__global__"
                    else resolve_palette_for_part_key(settings, key)
                )
                part_reference_rgb = global_reference_rgb
                part_reference_confidence = global_reference_confidence
                if key != "__global__":
                    part_id = int(face_part_ids[selected[0]]) if len(selected) else -1
                    part_reference = reference_by_part.get(part_id)
                    if part_reference is None or part_reference.sample_count == 0:
                        part_reference_rgb = None
                        part_reference_confidence = 0.0
                    else:
                        part_reference_rgb = part_reference.rgb_samples
                        part_reference_confidence = part_reference.confidence
                        used_reference_part_ids.add(part_id)
                results[key] = recommend_basic_filaments(
                    face_rgb[selected],
                    prepared.final.areas_unit[selected],
                    reference_rgb=part_reference_rgb,
                    reference_confidence=part_reference_confidence,
                    catalog=catalog_for(local_palette.material),
                    palette_state_count=local_palette.palette_state_count,
                )
            return (
                results,
                reference_match,
                tuple(sorted(used_reference_part_ids)),
                catalog_unique_counts,
            )

        def done(
            payload: tuple[
                dict[str, FilamentRecommendation],
                ReferencePartMatch | None,
                tuple[int, ...],
                dict[str, int],
            ]
        ) -> None:
            (
                results,
                reference_match,
                used_reference_part_ids,
                catalog_unique_counts,
            ) = payload
            current_settings = self._variables_to_settings(show_error=False)
            current_snapshot = (
                self._mix_optimization_snapshot(current_settings),
                self.active_part_key,
                requested_part_ids,
                bool(whole_model),
            ) if current_settings is not None else None
            if current_snapshot != input_snapshot:
                self.status_var.set(
                    "判定中にモデル・元画像・設定または選択パーツが変わったため、古い提案を破棄しました"
                )
                return
            for key, recommendation in results.items():
                current_palette = (
                    self.settings.palette
                    if key == "__global__"
                    else resolve_palette_for_part_key(self.settings, key)
                )
                palette = self._palette_from_recommendation(
                    recommendation,
                    current_palette.palette_state_count,
                    material=current_palette.material,
                    surface_shell_enabled=False,
                    black_free_gradient_enabled=bool(
                        getattr(
                            current_palette,
                            "black_free_gradient_enabled",
                            False,
                        )
                    ),
                    black_free_black_slot=int(
                        getattr(current_palette, "black_free_black_slot", 0)
                    ),
                    black_free_red_slot=int(
                        getattr(current_palette, "black_free_red_slot", 2)
                    ),
                    black_free_brown_slot=int(
                        getattr(current_palette, "black_free_brown_slot", 3)
                    ),
                )
                if key == "__global__":
                    self.settings.palette = palette
                else:
                    self.settings.part_palettes[key] = palette
                    self.part_recommendations[key] = recommendation
            if self.active_part_key is None:
                active_palette = self.settings.palette
                active_recommendation = results.get("__global__")
            else:
                active_palette = resolve_palette_for_part_key(
                    self.settings, self.active_part_key
                )
                active_recommendation = results.get(self.active_part_key)
            self._load_palette_variables(active_palette)
            self._refresh_palette_widgets(schedule_preview=True)
            self._refresh_part_tree()
            chosen = (
                active_recommendation
                or results.get("__global__")
                or next(iter(results.values()))
            )
            mean = float(chosen.mean_delta_e76)
            coverage = float(chosen.coverage_fraction)
            names = " / ".join(value.label for value in chosen.candidates)
            chosen_material = active_palette.material
            material_metric = self.i18n.text(
                "palette.material_result_metric",
                material=chosen_material,
                count=catalog_unique_counts.get(chosen_material, 0),
                delta=mean,
            )
            if (
                chosen is results.get("__global__")
                and global_reference_rgb is not None
            ):
                reference_note = global_reference_note
            elif reference_match is not None and reference_match.matched:
                mirrored_note = "・左右反転補正" if reference_match.mirrored else ""
                used_ids = set(used_reference_part_ids)
                requested_ids = set(requested_part_ids)
                matched_count = len(used_ids & requested_ids)
                if len(requested_part_ids) == 1 and matched_count == 0:
                    reference_note = (
                        "選択パーツは正面で確認できないため"
                        "読み込んだモデルの色だけで判定 "
                        f"(全体IoU {reference_match.selected_iou * 100:.0f}%)"
                    )
                else:
                    reference_note = (
                        f"元画像を3D正面へ対応: {matched_count}/"
                        f"{len(requested_part_ids)}パーツ / "
                        f"IoU {reference_match.selected_iou * 100:.0f}%"
                        f"{mirrored_note}"
                    )
            elif reference_match is not None:
                reference_note = (
                    "元画像との形状対応が弱いため"
                    "読み込んだモデルの色だけで判定 "
                    f"(IoU {reference_match.selected_iou * 100:.0f}%)"
                )
            elif reference_image is not None:
                reference_note = (
                    "元画像は未対応パーツのため"
                    "読み込んだモデルの色だけで判定"
                )
            else:
                reference_note = (
                    "元画像なし: 読み込んだモデルの色だけで判定"
                )
            self.recommendation_var.set(
                f"提案: {names}\n"
                f"平均ΔE {mean:.1f} / ΔE12以内 {coverage * 100:.0f}% / "
                f"信頼度 {chosen.confidence * 100:.0f}%\n"
                f"{material_metric}\n"
                f"{reference_note}"
            )
            self.status_var.set(
                (
                    f"{len(results) - 1}パーツと全体共通の提案を適用しました"
                    if "__global__" in results and len(results) > 1
                    else f"{len(results)}件の基本フィラメント提案を適用しました"
                )
                + ("（モデル読込時の自動判定）" if automatic else "")
            )
            if (
                chosen_material in {MATERIAL_ABS, MATERIAL_PETG}
                and float(chosen.mean_delta_e76)
                >= MATERIAL_GAMUT_WARNING_MEAN_DELTA_E76
            ):
                messagebox.showwarning(
                    self.i18n.text("palette.material_gamut_title"),
                    self.i18n.text(
                        "palette.material_gamut_warning",
                        material=chosen_material,
                        count=catalog_unique_counts.get(chosen_material, 0),
                        delta=float(chosen.mean_delta_e76),
                    ),
                    parent=self.root,
                )

        self._submit_main("基本フィラメント構成を判定しています", work, done)

    def _recommend_selected_part(self) -> None:
        if self.prepared is None:
            self._recommend_part_ids(())
            return
        if self.active_part_key is None:
            self._recommend_part_ids((), whole_model=True)
            return
        try:
            part_id = self.prepared.final.part_keys.index(self.active_part_key)
        except ValueError:
            return
        self._recommend_part_ids((part_id,))

    def _recommend_all_parts(self, automatic: bool = False) -> None:
        if self.prepared is None:
            self._recommend_part_ids(())
            return
        self._recommend_part_ids(
            tuple(range(len(self.prepared.final.part_keys))),
            automatic=automatic,
        )

    def _run_new_obj_auto_recommendation(
        self, expected_obj_path: Path | None
    ) -> None:
        """Apply a proposal only to the new OBJ that requested it.

        Project loading clears ``_auto_recommend_after_geometry`` before its
        geometry work begins.  Keeping that flag until this callback runs
        prevents a queued new-OBJ recommendation from overwriting the tone and
        palette restored from a project JSON.
        """

        if not self._auto_recommend_after_geometry:
            return
        if self.source_path != expected_obj_path or self.prepared is None:
            return
        if self.busy:
            self.root.after(
                120,
                lambda: self._run_new_obj_auto_recommendation(
                    expected_obj_path
                ),
            )
            return
        self._auto_recommend_after_geometry = False
        self._recommend_all_parts(automatic=True)

    def _choose_physical_color(self, index: int) -> None:
        try:
            initial = normalize_hex(self.physical_vars[index].get())
        except ValueError:
            initial = "#FFFFFF"
        _rgb, color = colorchooser.askcolor(color=initial, title=f"{PHYSICAL_NAMES[index]}フィラメントの表示色", parent=self.root)
        if color:
            self.physical_vars[index].set(color.upper())

    def _open_filament_candidates(self) -> None:
        """Open the optional product matcher without replacing the preview."""

        window = self.filament_candidate_window
        if window is None:
            try:
                window = FilamentCandidateWindow(self)
            except Exception as exc:
                messagebox.showerror(
                    self.i18n.text("filament_candidates.title"),
                    self.i18n.text(
                        "filament_candidates.error",
                        reason=str(exc),
                    ),
                    parent=self.root,
                )
                return
            self.filament_candidate_window = window
        window.show()

    def _change_material_mode(self, material: str) -> None:
        """Switch one global/part palette without reusing another polymer."""

        if bool(getattr(self, "busy", False)):
            messagebox.showinfo(
                self.i18n.text("dialog.busy.title"),
                self.i18n.text("dialog.busy.message"),
                parent=self.root,
            )
            return
        selected = normalize_filament_material(material)
        current = self._active_palette_for_controls()
        if current.material == selected:
            return
        if selected == MATERIAL_ABS:
            messagebox.showwarning(
                self.i18n.text("palette.abs_warning_title"),
                self.i18n.text("palette.abs_warning"),
                parent=self.root,
            )
        elif selected == MATERIAL_PETG:
            messagebox.showinfo(
                self.i18n.text("palette.material_beta_title"),
                self.i18n.text("palette.petg_warning"),
                parent=self.root,
            )

        painted = (
            int(np.count_nonzero(np.asarray(self.manual_overrides) >= 0))
            if self.manual_overrides is not None
            else 0
        )
        if not messagebox.askyesno(
            self.i18n.text("palette.material_change_title"),
            self.i18n.text(
                "palette.material_change_confirm",
                old=current.material,
                new=selected,
                painted=painted,
            ),
            parent=self.root,
        ):
            return

        replacement = self._copy_palette(current)
        replacement.material = selected
        replacement.physical_filament_refs = [None] * 4
        if self.prepared is None:
            replacement.physical_hex = list(
                PaletteSettings(material=selected).physical_hex
            )
        self._assign_active_palette(replacement)
        self._load_palette_variables(replacement)
        self._note_mix_input_change()
        self._refresh_part_tree()
        self._schedule_preview(immediate=True)
        candidate_window = self.filament_candidate_window
        if candidate_window is not None:
            candidate_window._schedule_search(delay_ms=0)
        if self.prepared is not None:
            if self.active_part_key is None:
                self._recommend_part_ids((), whole_model=True)
            else:
                self._recommend_selected_part()
        else:
            self.status_var.set(
                self.i18n.text(
                    "palette.material_changed_no_obj", material=selected
                )
            )

    def _configure_from_owned_filaments(
        self,
        owned_products: tuple[object, ...],
        *,
        inventory_revision: tuple[tuple[str, str], ...],
        dialog_parent=None,
        on_finished=None,
    ) -> bool:
        """Atomically apply one owned-product palette to the current target.

        The worker chooses ordered F1-F4 products and optimizes both the six
        primary and six additional mix ratios.  All 16/24/32 settings are
        committed together only if the model, target, tone, palette boundary,
        and owned-inventory revision are unchanged when the result returns.
        """

        dialog_parent = dialog_parent or self.root
        if self.prepared is None:
            messagebox.showinfo(
                self.i18n.text("filament_candidates.auto_owned"),
                self.i18n.text("filament_candidates.auto_no_obj"),
                parent=dialog_parent,
            )
            return False
        settings = self._variables_to_settings(show_error=True)
        if settings is None:
            return False
        products = tuple(owned_products)
        target_key = self.active_part_key
        prepared = self.prepared
        active_palette = (
            settings.palette
            if target_key is None
            else resolve_palette_for_part_key(settings, target_key)
        )
        if target_key is None:
            # A common-palette recommendation must only learn from faces that
            # will actually use that palette.  Parts with an explicit palette
            # (including a cut child inheriting its parent's explicit palette)
            # are unaffected by this operation and would otherwise skew the
            # four-colour choice.
            common_part_ids = np.asarray(
                [
                    part_id
                    for part_id, part_key in enumerate(
                        prepared.final.part_keys
                    )
                    if resolve_palette_for_part_key(settings, part_key)
                    is settings.palette
                ],
                dtype=np.int64,
            )
            selected_faces = np.flatnonzero(
                np.isin(
                    np.asarray(prepared.final.face_part_ids),
                    common_part_ids,
                )
            )
            target_name = self.i18n.text("filament_candidates.auto_common")
            target_part_id = None
        else:
            try:
                target_part_id = prepared.final.part_keys.index(target_key)
            except ValueError:
                return False
            selected_faces = np.flatnonzero(
                np.asarray(prepared.final.face_part_ids) == target_part_id
            )
            target_name = str(prepared.final.part_names[target_part_id])
        if len(selected_faces) == 0:
            messagebox.showwarning(
                self.i18n.text("filament_candidates.auto_owned"),
                self.i18n.text(
                    "filament_candidates.auto_no_target_faces",
                    target=target_name,
                ),
                parent=dialog_parent,
            )
            return False

        selected_faces = np.asarray(selected_faces, dtype=np.int64)
        face_count = len(prepared.final.faces)
        manual_mask = np.zeros(face_count, dtype=bool)
        valid_manual, manual_overrides = self._validated_manual_overrides(
            show_error=False,
        )
        if valid_manual and manual_overrides is not None:
            manual_mask = np.asarray(manual_overrides >= 0, dtype=bool)
        tree_mask = existing_tree_face_mask(prepared)
        selected_manual_count = int(
            np.count_nonzero(manual_mask[selected_faces])
        )
        selected_tree_count = int(np.count_nonzero(tree_mask[selected_faces]))
        selected_painted_count = int(
            np.count_nonzero(
                (manual_mask | tree_mask)[selected_faces]
            )
        )
        if selected_painted_count and not messagebox.askyesno(
            self.i18n.text("filament_candidates.auto_manual_title"),
            self.i18n.text(
                "filament_candidates.auto_manual_confirm",
                target=target_name,
                count=selected_painted_count,
                manual=selected_manual_count,
                trees=selected_tree_count,
            ),
            parent=dialog_parent,
        ):
            return False

        # Reference sampling is intentionally deferred until after the manual
        # colour confirmation so Cancel performs no recommendation work.
        if target_key is None:
            reference_rgb, reference_confidence, _note = (
                self._reference_samples_for_recommendation()
            )
            reference_image = None
        else:
            reference_rgb = None
            reference_confidence = 0.0
            reference_image = (
                self.reference_image.copy()
                if self.reference_image is not None
                else None
            )

        initial_snapshot = self._mix_optimization_snapshot(settings)
        requested_inventory_revision = tuple(inventory_revision)

        def work():
            from .owned_filaments import recommend_from_owned_filaments

            part_reference_rgb = reference_rgb
            part_reference_confidence = reference_confidence
            if reference_image is not None and target_part_id is not None:
                match = match_reference_to_parts(prepared.preview, reference_image)
                part_reference = match.samples_by_part_id.get(target_part_id)
                if part_reference is not None and part_reference.sample_count:
                    part_reference_rgb = part_reference.rgb_samples
                    part_reference_confidence = part_reference.confidence
            tone_vertices = apply_tone(
                prepared.final.vertex_colors,
                settings.tone,
            )
            face_rgb = tone_vertices[prepared.final.faces[selected_faces]].mean(axis=1)
            pink_mask = None
            if settings.tone.pink_protection:
                pink_score = face_rgb[:, 0] - 0.5 * (
                    face_rgb[:, 1] + face_rgb[:, 2]
                )
                pink_mask = pink_score > settings.tone.pink_threshold
            return recommend_from_owned_filaments(
                face_rgb,
                prepared.final.areas_unit[selected_faces],
                owned_products=products,
                material=active_palette.material,
                reference_rgb=part_reference_rgb,
                reference_confidence=part_reference_confidence,
                palette_state_count=active_palette.palette_state_count,
                initial_ratios_b=active_palette.mix_ratios_b,
                secondary_ratios_b=active_palette.secondary_mix_ratios_b,
                enabled_states=active_palette.enabled_states,
                pink_protection_mask=pink_mask,
            )

        def current_inventory_revision() -> tuple[tuple[str, str], ...]:
            window = self.filament_candidate_window
            revision = getattr(window, "_inventory_revision", None)
            if callable(revision):
                try:
                    return tuple(revision())
                except (AttributeError, tk.TclError, ValueError):
                    pass
            return requested_inventory_revision

        def finish(applied: bool) -> None:
            if callable(on_finished):
                on_finished(bool(applied))

        def done(result) -> None:
            current_settings = self._variables_to_settings(show_error=False)
            stale = (
                current_settings is None
                or self.active_part_key != target_key
                or self._mix_optimization_snapshot(current_settings)
                != initial_snapshot
                or current_inventory_revision() != requested_inventory_revision
            )
            if stale:
                message = self.i18n.text("filament_candidates.auto_discarded")
                self.status_var.set(message)
                if self.filament_candidate_window is not None:
                    self.filament_candidate_window.status_var.set(message)
                finish(False)
                return

            # One atomic palette replacement.  Variable traces are suppressed
            # while all four physical colours and all twelve ratios are loaded,
            # so no half-updated preview can be committed.
            palette = PaletteSettings(
                material=active_palette.material,
                palette_state_count=int(result.palette_state_count),
                physical_hex=list(result.physical_hex),
                enabled_states=list(active_palette.enabled_states),
                mix_hex_overrides=[None] * 6,
                mix_ratios_b=list(result.mix_ratios_b),
                secondary_mix_ratios_b=list(result.secondary_mix_ratios_b),
                output_mix_ratios_b=(
                    None
                    if active_palette.output_mix_ratios_b is None
                    else black_output_ratio_preset(
                        self._infer_black_output_slot(active_palette),
                        result.mix_ratios_b,
                        result.secondary_mix_ratios_b,
                    )
                ),
                surface_shell_enabled=False,
                black_free_gradient_enabled=bool(
                    getattr(active_palette, "black_free_gradient_enabled", False)
                ),
                black_free_black_slot=int(
                    getattr(active_palette, "black_free_black_slot", 0)
                ),
                black_free_red_slot=int(
                    getattr(active_palette, "black_free_red_slot", 2)
                ),
                black_free_brown_slot=int(
                    getattr(active_palette, "black_free_brown_slot", 3)
                ),
                physical_filament_refs=[
                    FilamentSnapshotRef.from_product(product)
                    for product in result.candidates
                ],
            )
            if target_key is None:
                self.settings.palette = palette
            else:
                self.settings.part_palettes[target_key] = palette
                self.part_recommendations.pop(target_key, None)
            self._load_palette_variables(palette)
            self._commit_active_palette()
            self._note_mix_input_change()
            self._refresh_palette_widgets(schedule_preview=False)
            self._refresh_part_tree()
            self._schedule_preview(immediate=True)

            product_names = "\n".join(
                (
                    f"{PHYSICAL_NAMES[index]}: {ref.label} / {ref.matched_hex}"
                    f" / finish={ref.finish_class or '-'}"
                    f" / source={ref.source or '-'}"
                    f" / product_id={ref.product_id}"
                )
                for index, product in enumerate(result.candidates)
                if (ref := FilamentSnapshotRef.from_product(product)) is not None
            )
            message = self.i18n.text(
                "filament_candidates.auto_result",
                target=target_name,
                products=product_names,
                before=float(result.before_mean_delta_e76),
                after=float(result.mean_delta_e76),
                improvement=float(result.improvement_percent),
            )
            self.status_var.set(message)
            self.recommendation_var.set(message)
            if self.filament_candidate_window is not None:
                self.filament_candidate_window.status_var.set(message)

            warnings: list[str] = []
            if tuple(result.ignored_duplicate_color_product_ids):
                warnings.append(
                    self.i18n.text(
                        "filament_candidates.auto_duplicate_colors"
                    )
                )
            special_products = tuple(result.special_finish_products)
            if special_products:
                warnings.append(
                    self.i18n.text(
                        "filament_candidates.auto_special_finish",
                        products="\n".join(
                            str(product.label) for product in special_products
                        ),
                    )
                )
            if warnings:
                messagebox.showwarning(
                    self.i18n.text(
                        "filament_candidates.auto_warning_title"
                    ),
                    "\n\n".join(warnings),
                    parent=dialog_parent,
                )
            finish(True)

        def on_error(_exc, _details) -> bool:
            finish(False)
            return False

        return self._submit_main(
            self.i18n.text("filament_candidates.auto_running"),
            work,
            done,
            on_error=on_error,
        )

    def _apply_sample_to_physical(self, index: int) -> None:
        if self.sample_rgb is None:
            messagebox.showinfo(
                self.i18n.text("dialog.no_sample.title"),
                self.i18n.text("dialog.no_sample.message"),
                parent=self.root,
            )
            return
        self.physical_vars[index].set(rgb8_to_hex(self.sample_rgb))
        self.enabled_vars[index].set(True)

    def _reset_physical_colors(self) -> None:
        defaults = PaletteSettings(
            material=self._active_palette_for_controls().material
        )
        for variable, value in zip(self.physical_vars, defaults.physical_hex, strict=True):
            variable.set(value)
        for variable, value in zip(self.mix_ratio_vars, defaults.mix_ratios_b, strict=True):
            variable.set(value)
        for variable, value in zip(
            self.secondary_mix_ratio_vars,
            defaults.secondary_mix_ratios_b,
            strict=True,
        ):
            variable.set(value)

    def _reset_tone(self) -> None:
        tone = ToneSettings()
        self.black_point_var.set(tone.black_point)
        self.white_point_var.set(tone.white_point)
        self.gamma_var.set(tone.gamma)
        self.contrast_var.set(tone.contrast)
        self.saturation_var.set(tone.saturation)
        self.pink_protection_var.set(tone.pink_protection)
        self.pink_threshold_var.set(tone.pink_threshold)
        self.smoothing_var.set(tone.smoothing)
        self.smoothing_area_var.set(tone.smoothing_max_area_mm2)
        self.smoothing_slack_var.set(tone.smoothing_delta_e_slack)
        self._on_tone_changed()

    def _optimize_mix_ratios(self, *, on_applied=None, dialog_parent=None) -> None:
        dialog_parent = dialog_parent or self.root
        if self.prepared is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.optimize"),
                parent=dialog_parent,
            )
            return
        settings = self._variables_to_settings(show_error=True)
        if settings is None:
            return
        target_key = self.active_part_key
        active_palette = (
            settings.palette
            if target_key is None
            else resolve_palette_for_part_key(settings, target_key)
        )
        preflight_settings = AppSettings(
            geometry=settings.geometry,
            tone=settings.tone,
            palette=active_palette,
        )
        preflight_error = _mix_optimization_preflight(preflight_settings)
        if preflight_error is not None:
            title, message = preflight_error
            messagebox.showinfo(title, message, parent=dialog_parent)
            return
        affected_manual_states = _enabled_manual_mix_states(
            self.manual_overrides,
            active_palette.enabled_states,
        )
        if affected_manual_states:
            if not messagebox.askyesno(
                "手修正の色も変化します",
                "混色比率を変えると、手修正で指定した混色番号は維持されますが、その実際の混色が変わります。\n\n最適化を続けますか？",
                parent=dialog_parent,
            ):
                return
        prepared = self.prepared
        input_snapshot = self._mix_optimization_snapshot(settings)
        if target_key is None:
            selected_faces = np.arange(len(prepared.final.faces))
            target_label = "モデル全体"
        else:
            part_id = prepared.final.part_keys.index(target_key)
            selected_faces = np.flatnonzero(
                np.asarray(prepared.final.face_part_ids) == part_id
            )
            target_label = prepared.final.part_names[part_id]

        def work():
            colors = recolor_level_parts(
                prepared.final,
                settings.geometry.height_mm,
                settings.tone,
                settings.palette,
                settings.part_palettes,
            )
            face_rgb = colors.tone_vertex_rgb[
                prepared.final.faces[selected_faces]
            ].mean(axis=1)
            pink_mask = None
            if settings.tone.pink_protection:
                pink_score = face_rgb[:, 0] - 0.5 * (
                    face_rgb[:, 1] + face_rgb[:, 2]
                )
                pink_mask = pink_score > settings.tone.pink_threshold
            return optimize_global_mix_ratios(
                face_rgb,
                active_palette.physical_hex,
                weights=prepared.final.areas_unit[selected_faces],
                initial_ratios_b=active_palette.mix_ratios_b,
                secondary_ratios_b=active_palette.secondary_mix_ratios_b,
                enabled_states=active_palette.enabled_states,
                pink_protection_mask=pink_mask,
            )

        def done(result) -> None:
            current_settings = self._variables_to_settings(show_error=False)
            if (
                current_settings is None
                or self.active_part_key != target_key
                or self._mix_optimization_snapshot(current_settings) != input_snapshot
            ):
                self._clear_mix_optimization_undo()
                self.status_var.set(
                    "最適化中に設定またはモデルが変わったため、結果を適用しませんでした"
                )
                messagebox.showinfo(
                    "最適化結果を適用しませんでした",
                    "最適化の途中で設定・モデル・手修正のいずれかが変更されました。現在の内容を保護するため、計算結果は破棄しました。必要であれば、もう一度自動最適化してください。",
                    parent=dialog_parent,
                )
                return
            previous = list(active_palette.mix_ratios_b)
            changed = previous != list(result.mix_ratios_b)
            if changed:
                self.last_mix_ratios = previous
                self.last_mix_target_key = target_key
                self._set_mix_optimization_undo_enabled(True)
            else:
                self._clear_mix_optimization_undo()
            self._applying_mix_result = True
            try:
                for variable, ratio in zip(
                    self.mix_ratio_vars, result.mix_ratios_b, strict=True
                ):
                    variable.set(int(ratio))
            finally:
                self._applying_mix_result = False
            updated_palette = self._commit_active_palette()
            if on_applied is not None:
                on_applied(target_key, self._copy_palette(updated_palette))
            if changed:
                self.status_var.set(
                    f"{target_label}の混色比率を最適化しました: "
                    f"平均ΔE76 {result.initial_weighted_mean_delta_e76:.2f} → "
                    f"{result.weighted_mean_delta_e76:.2f} "
                    f"（{result.improvement_percent:.1f}%改善）"
                )
            else:
                self.status_var.set(
                    "改善する混色比率が見つからなかったため、現在値を変更しませんでした"
                )
            self._schedule_preview(immediate=True)

        self._submit_main(f"{target_label}の陰影へ混色6色を最適化しています", work, done)

    def _undo_mix_optimization(self, *, on_applied=None) -> None:
        if self.last_mix_ratios is None:
            return
        ratios = list(self.last_mix_ratios)
        target_key = self.last_mix_target_key
        self.last_mix_ratios = None
        self.last_mix_target_key = None
        self._set_mix_optimization_undo_enabled(False)
        self._mix_input_generation += 1
        self._applying_mix_result = True
        try:
            for variable, ratio in zip(self.mix_ratio_vars, ratios, strict=True):
                variable.set(int(ratio))
        finally:
            self._applying_mix_result = False
        updated_palette = self._commit_active_palette()
        if on_applied is not None:
            on_applied(target_key, self._copy_palette(updated_palette))
        self.status_var.set("直前の自動最適化前の混色比率へ戻しました")
        self._schedule_preview(immediate=True)

    def _schedule_preview(self, *, immediate: bool = False) -> None:
        if self.prepared is None:
            return
        if self.preview_after_id:
            self.root.after_cancel(self.preview_after_id)
        self.preview_after_id = self.root.after(20 if immediate else 330, self._start_preview_job)

    def _start_preview_job(self) -> None:
        self.preview_after_id = None
        settings = self._variables_to_settings(show_error=False)
        if settings is None or self.prepared is None:
            return
        self.preview_generation += 1
        generation = self.preview_generation
        selection_key = self.active_part_key
        use_manual = (
            self.manual_overrides is not None
            and len(self.manual_overrides) == len(self.prepared.final.faces)
            and bool(np.any(self.manual_overrides >= 0))
        )
        level = self.prepared.final if use_manual else self.prepared.preview
        overrides = self.manual_overrides.copy() if use_manual else None
        active_part_id: int | None = None
        if selection_key is not None:
            try:
                active_part_id = level.part_keys.index(selection_key)
            except ValueError:
                active_part_id = None
        if self.preview_future and not self.preview_future.running():
            self.preview_future.cancel()

        def runner() -> None:
            try:
                colors = recolor_level_parts(
                    level,
                    settings.geometry.height_mm,
                    settings.tone,
                    settings.palette,
                    settings.part_palettes,
                )
                if overrides is not None:
                    colors = apply_palette_overrides_parts(
                        level,
                        settings.geometry.height_mm,
                        settings.palette,
                        settings.part_palettes,
                        colors,
                        overrides,
                    )
                pair = render_front_preview_pair(
                    level,
                    colors,
                    size=(560, 700),
                    background=(9, 12, 17),
                    active_part_id=active_part_id,
                )
                source = pair.source
                target = pair.target
                mean = float(np.average(colors.delta_e, weights=level.areas_unit))
                self.work_queue.put(
                    (
                        "preview_done",
                        (generation, selection_key, colors, source, target, mean),
                    )
                )
            except Exception as exc:
                self.work_queue.put(
                    ("preview_error", (generation, selection_key, exc))
                )

        self.preview_future = self.preview_executor.submit(runner)

    def _on_canvas_configure(self, _event=None) -> None:
        if self.canvas_after_id:
            self.root.after_cancel(self.canvas_after_id)
        self.canvas_after_id = self.root.after(80, self._draw_comparison_canvas)

    def _placeholder(self, size: tuple[int, int], text: str) -> Image.Image:
        image = Image.new("RGB", size, (9, 12, 17))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((12, 12, size[0] - 12, size[1] - 12), radius=12, outline=(43, 53, 68), width=2)
        draw.text((size[0] // 2, size[1] // 2), text, fill=(145, 157, 175), anchor="mm")
        return image

    def _draw_comparison_canvas(self) -> None:
        self.canvas_after_id = None
        canvas = self.preview_canvas
        width = max(600, canvas.winfo_width())
        height = max(360, canvas.winfo_height())
        margin = 14
        gap = 12
        title_height = 34
        panel_width = max(160, (width - margin * 2 - gap * 2) // 3)
        panel_height = max(240, height - margin * 2 - title_height)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#090C11", outline="")
        labels = (
            self.i18n.text("preview.reference"),
            self.i18n.text("preview.source"),
            self.i18n.text("preview.target"),
        )
        sources: list[Image.Image] = []
        sources.append(
            self.reference_image
            or self._placeholder(
                (panel_width, panel_height),
                self.i18n.text("preview.open_reference"),
            )
        )
        sources.append(
            self.source_render
            or self._placeholder(
                (panel_width, panel_height),
                self.i18n.text("preview.process_obj"),
            )
        )
        sources.append(
            self.target_render
            or self._placeholder(
                (panel_width, panel_height),
                self.i18n.text("preview.target_placeholder"),
            )
        )
        self.canvas_images.clear()
        self.reference_mapping = None
        for index, (label, source) in enumerate(zip(labels, sources, strict=True)):
            x = margin + index * (panel_width + gap)
            canvas.create_text(x + panel_width // 2, margin + title_height // 2, text=label, fill=TEXT, font=("Yu Gothic UI", 10, "bold"))
            top = margin + title_height
            contained = ImageOps.contain(source.convert("RGB"), (panel_width, panel_height), method=Image.Resampling.LANCZOS)
            px = x + (panel_width - contained.width) // 2
            py = top + (panel_height - contained.height) // 2
            photo = ImageTk.PhotoImage(contained)
            self.canvas_images.append(photo)
            canvas.create_image(px, py, image=photo, anchor="nw")
            canvas.create_rectangle(x, top, x + panel_width, top + panel_height, outline="#273242", width=1)
            if index == 0 and self.reference_image is not None:
                self.reference_mapping = (px, py, contained.width, contained.height, self.reference_image.width, self.reference_image.height)
                if self.eyedropper_active:
                    canvas.create_rectangle(px, py, px + contained.width, py + contained.height, outline=ACCENT, width=3)
        if self.eyedropper_active:
            canvas.create_text(
                width // 2,
                height - 18,
                text=self.i18n.text("preview.click_reference"),
                fill=ACCENT,
                font=("Yu Gothic UI", 10, "bold"),
            )

    def _toggle_eyedropper(self) -> None:
        if not self.eyedropper_active and self.reference_image is None:
            self._choose_reference()
            if self.reference_image is None:
                return
        if self.eyedropper_active:
            self.eyedropper_active = False
            self.physical_eyedropper_target = None
        else:
            self.eyedropper_active = True
            self.physical_eyedropper_target = None
        self._sync_eyedropper_controls()

    def _cancel_eyedropper(self) -> None:
        """Clear any pending generic or direct sample before inputs change."""

        self.eyedropper_active = False
        self.physical_eyedropper_target = None
        self._sync_eyedropper_controls()

    def _start_physical_eyedropper(self, index: int) -> None:
        """Arm a one-click reference pick that writes directly to F1-F4."""

        if not 0 <= int(index) < len(PHYSICAL_NAMES):
            raise IndexError("physical filament index is out of range")
        if self.reference_image is None:
            self._choose_reference()
            if self.reference_image is None:
                return
        self.physical_eyedropper_target = int(index)
        self.eyedropper_active = True
        self.status_var.set(
            self.i18n.text(
                "palette.pick_base_status", slot=PHYSICAL_NAMES[index]
            )
        )
        self._sync_eyedropper_controls()

    def _sync_eyedropper_controls(self) -> None:
        self.eyedropper_button.configure(
            text=self.i18n.text(
                "palette.eyedropper_stop"
                if self.eyedropper_active
                else "palette.eyedropper_start"
            )
        )
        self.preview_canvas.configure(cursor="crosshair" if self.eyedropper_active else "arrow")
        self._draw_comparison_canvas()

    def _on_canvas_click(self, event: tk.Event) -> None:
        if not self.eyedropper_active or self.reference_image is None or self.reference_mapping is None:
            return
        x, y, width, height, original_width, original_height = self.reference_mapping
        if not (x <= event.x < x + width and y <= event.y < y + height):
            target = self.physical_eyedropper_target
            self.status_var.set(
                self.i18n.text(
                    "palette.pick_reference_only"
                    if target is None
                    else "palette.pick_reference_for_slot",
                    **({} if target is None else {"slot": PHYSICAL_NAMES[target]}),
                )
            )
            return
        ox = min(original_width - 1, max(0, int((event.x - x) * original_width / width)))
        oy = min(original_height - 1, max(0, int((event.y - y) * original_height / height)))
        left, top = max(0, ox - 2), max(0, oy - 2)
        right, bottom = min(original_width, ox + 3), min(original_height, oy + 3)
        sample = np.asarray(
            self.reference_image.crop((left, top, right, bottom)).convert("RGB"),
            dtype=np.float64,
        ).reshape(-1, 3).mean(axis=0)
        self.sample_rgb = tuple(int(round(value)) for value in sample)
        sample_hex = rgb8_to_hex(self.sample_rgb)
        self.sample_hex_var.set(sample_hex)
        self.sample_swatch.configure(bg=sample_hex)
        self._update_recipe_candidates()
        target = self.physical_eyedropper_target
        if target is None:
            self._set_recipe_panel_visible(True)
            self.status_var.set(
                self.i18n.text(
                    "palette.sampled", x=ox, y=oy, color=sample_hex
                )
            )
            return
        self._apply_sample_to_physical(target)
        self.physical_eyedropper_target = None
        self.eyedropper_active = False
        self.status_var.set(
            self.i18n.text(
                "palette.base_applied",
                color=sample_hex,
                slot=PHYSICAL_NAMES[target],
            )
        )
        self._sync_eyedropper_controls()

    def _update_recipe_candidates(self) -> None:
        if self.sample_rgb is None:
            return
        try:
            physical = [normalize_hex(variable.get()) for variable in self.physical_vars]
            all_candidates = find_best_mix_recipes(self.sample_rgb, physical, top_n=606)
        except ValueError:
            return
        per_pair: dict[tuple[int, int], MixRecipeCandidate] = {}
        for candidate in all_candidates:
            if candidate.ratio_b_percent in (0, 100):
                continue
            key = (candidate.color_a_index, candidate.color_b_index)
            if key not in per_pair:
                per_pair[key] = candidate
        self.recipes = sorted(per_pair.values(), key=lambda value: value.delta_e76)
        self.recipe_tree.delete(*self.recipe_tree.get_children())
        for index, candidate in enumerate(self.recipes[:5]):
            quality = self._quality(candidate.delta_e76)
            self.recipe_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    f"{SHORT_NAMES[candidate.color_a_index]}+{SHORT_NAMES[candidate.color_b_index]}",
                    f"{candidate.ratio_a_percent} : {candidate.ratio_b_percent}",
                    candidate.predicted_hex,
                    f"{candidate.delta_e76:.2f}",
                    quality,
                ),
            )
        if self.recipes:
            self.recipe_tree.selection_set("0")
        endpoint_candidates = [candidate for candidate in all_candidates if candidate.ratio_b_percent in (0, 100)]
        direct = min(endpoint_candidates, key=lambda value: value.delta_e76)
        direct_index = direct.color_a_index if direct.ratio_b_percent == 0 else direct.color_b_index
        self.direct_match_label.configure(
            text=f"基本色の近似: {SHORT_NAMES[direct_index]}\nΔE76 {direct.delta_e76:.2f}（{self._quality(direct.delta_e76)}）"
        )

    def _quality(self, delta_e: float) -> str:
        if delta_e <= 3.0:
            return self.i18n.text("recipe.very_close")
        if delta_e <= 8.0:
            return self.i18n.text("recipe.close")
        if delta_e <= 15.0:
            return self.i18n.text("recipe.test_print")
        return self.i18n.text("recipe.difficult")

    def _apply_selected_recipe(self) -> None:
        selection = self.recipe_tree.selection()
        if not selection or not self.recipes:
            messagebox.showinfo(
                self.i18n.text("dialog.no_recipe.title"),
                self.i18n.text("dialog.no_sample.message"),
                parent=self.root,
            )
            return
        recipe = self.recipes[int(selection[0])]
        pair_index = PAIR_INDICES.index((recipe.color_a_index, recipe.color_b_index))
        self.mix_ratio_vars[pair_index].set(recipe.ratio_b_percent)
        self.enabled_vars[pair_index + 4].set(True)
        self.status_var.set(
            f"{PAIR_NAMES[pair_index]} を {recipe.ratio_a_percent}:{recipe.ratio_b_percent} に設定しました"
        )

    def _project_payload_for_save(
        self,
        settings: AppSettings,
        manual_overrides: np.ndarray | None,
    ) -> dict[str, object]:
        """Build the portable inner project mapping used by folder bundles."""

        data: dict[str, object] = {
            "schema": _PROJECT_SCHEMA,
            "settings": settings.to_dict(),
            "parts": [
                {
                    "key": key,
                    "name": name,
                    "uses_individual_palette": key in settings.part_palettes,
                }
                for name, key in zip(
                    self.prepared.final.part_names if self.prepared else (),
                    self.prepared.final.part_keys if self.prepared else (),
                    strict=True,
                )
            ],
        }
        if manual_overrides is not None and self.manual_fingerprint is not None:
            data["manual_paint"] = encode_manual_overrides(
                manual_overrides,
                self.manual_fingerprint,
            )
        elif self.pending_manual_payload is not None:
            data["manual_paint"] = dict(self.pending_manual_payload)
        return data

    def _save_project(self) -> None:
        if self.paint_editor is not None:
            self.paint_editor.close(after_close=self._save_project)
            return
        if self.busy:
            messagebox.showinfo(
                self.i18n.text("dialog.busy.title"),
                self.i18n.text("dialog.busy.message"),
                parent=self.root,
            )
            return
        settings = self._variables_to_settings(show_error=True)
        if settings is None:
            return
        _enforce_black_free_gradient_developer_gate(
            settings,
            self._developer_features_are_enabled(),
        )
        if self.source_path is None or self.prepared is None or self.prepared_key is None:
            messagebox.showinfo(
                self.i18n.text("project.source_required_title"),
                self.i18n.text("project.source_required_message"),
                parent=self.root,
            )
            return
        if tuple(self.prepared_key) != tuple(_geometry_key(settings.geometry)):
            messagebox.showwarning(
                self.i18n.text("project.geometry_outdated_title"),
                self.i18n.text("project.geometry_outdated_message"),
                parent=self.root,
            )
            return
        valid_paint, manual_overrides = self._validated_manual_overrides(
            make_copy=True
        )
        if not valid_paint:
            return
        value = filedialog.askdirectory(
            parent=self.root,
            title=self.i18n.text("project.save_choose_parent"),
            mustexist=True,
        )
        if not value:
            return
        data = self._project_payload_for_save(settings, manual_overrides)

        parent_folder = Path(value)
        source_obj = Path(self.source_path)
        prepared_geometry = self.prepared
        prepared_geometry_key = tuple(self.prepared_key)
        reference_image = (
            Path(self.reference_path) if self.reference_path is not None else None
        )

        def work():
            return save_project_bundle_in_parent(
                parent_folder,
                source_obj,
                data,
                prepared_geometry=prepared_geometry,
                prepared_geometry_key=prepared_geometry_key,
                reference_image=reference_image,
            )

        def done(result) -> None:
            self.status_var.set(
                self.i18n.text("project.saved", name=result.folder.name)
            )

        def failed(exc: Exception, _details: str) -> bool:
            messagebox.showerror(
                self.i18n.text("project.save_error"),
                str(exc),
                parent=self.root,
            )
            return True

        self._submit_main(
            self.i18n.text("project.save_working"),
            work,
            done,
            on_error=failed,
        )

    def _load_project(self) -> None:
        value = filedialog.askdirectory(
            parent=self.root,
            title=self.i18n.text("project.load_choose_folder"),
            mustexist=True,
        )
        if not value:
            return
        self._load_project_path(Path(value))

    def _load_legacy_project(self) -> None:
        value = filedialog.askopenfilename(
            parent=self.root,
            title=self.i18n.text("project.load_choose_legacy_json"),
            filetypes=(
                ("JSON", "*.json"),
                (self.i18n.text("filedialog.all"), "*.*"),
            ),
        )
        if not value:
            return
        self._load_project_path(Path(value))

    @staticmethod
    def _settings_with_saved_part_names(
        data: dict[str, object],
        settings: AppSettings,
    ) -> AppSettings:
        saved_parts = data.get("parts", [])
        if isinstance(saved_parts, list):
            for item in saved_parts:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key", "")).strip()
                name = str(item.get("name", "")).strip()
                if key and name:
                    settings.part_names.setdefault(key, name)
        return settings

    def _apply_project_payload(
        self,
        data: dict[str, object],
        settings: AppSettings,
        *,
        reference_path: Path | None,
        reference_image: Image.Image | None,
        ignored_features: tuple[str, ...],
    ) -> None:
        self.settings = settings
        self._auto_recommend_after_geometry = False
        self._project_obj_recovery_pending = False
        self.part_recommendations.clear()
        self._clear_mix_optimization_undo()
        self._settings_to_variables()
        self._refresh_palette_widgets(schedule_preview=False)
        self.manual_overrides = None
        self.manual_fingerprint = None
        self.manual_part_partition = None
        self.manual_joint_record = None
        manual_paint = data.get("manual_paint")
        self.pending_manual_payload = (
            manual_paint if isinstance(manual_paint, dict) else None
        )
        # Split/joint authoring was retired from the public workflow.  Never
        # replay old geometry-changing records invisibly.
        self.pending_manual_part_partition = None
        self.pending_manual_joint_record = None
        self.reference_image = reference_image
        self.reference_path = reference_path
        if reference_path is None:
            self.ref_name_var.set(self.i18n.text("state.reference_none"))
        else:
            self.ref_name_var.set(f"{self.i18n.text('toolbar.open_reference')}: {reference_path.name}")
        if ignored_features:
            messagebox.showwarning(
                self.i18n.text("project.ignored_legacy_title"),
                self.i18n.text("project.ignored_legacy_message"),
                parent=self.root,
            )

    def _clear_project_geometry(self) -> None:
        self.source_path = None
        self.obj_name_var.set(self.i18n.text("state.obj_none"))
        self.asset = None
        self.prepared = None
        self.prepared_key = None
        self.preview_colors = None
        self.source_render = None
        self.target_render = None
        self._manual_high_face_warning_key = None
        self._update_face_count_status()
        self._refresh_part_selector()
        self._draw_comparison_canvas()

    def _install_exact_project_snapshot(
        self,
        result: ProjectLoadResult,
        data: dict[str, object],
        settings: AppSettings,
        snapshot,
        manual_overrides: np.ndarray | None,
        current_fingerprint: str,
        part_name_error: str | None,
        *,
        reference_path: Path | None,
        reference_image: Image.Image | None,
    ) -> None:
        self._apply_project_payload(
            data,
            settings,
            reference_path=reference_path,
            reference_image=reference_image,
            ignored_features=result.ignored_features,
        )
        self.source_path = result.source_asset
        self.obj_name_var.set(self._source_display_text())
        self.asset = snapshot.prepared.source
        self.prepared = snapshot.prepared
        self.prepared_key = snapshot.geometry_key
        if part_name_error is not None:
            messagebox.showwarning(
                self.i18n.text("paint.part_rename_title"),
                part_name_error,
                parent=self.root,
            )
        self.manual_overrides = manual_overrides
        restored_faces = (
            int(np.count_nonzero(manual_overrides >= 0))
            if manual_overrides is not None
            else 0
        )
        self.pending_manual_payload = None
        self.manual_fingerprint = current_fingerprint
        self._note_mix_input_change()
        self._refresh_black_free_gradient_widgets()
        self._manual_high_face_warning_key = None
        self._update_face_count_status()
        self._refresh_part_selector()
        self._update_assembly_status()
        self.preview_colors = None
        self.source_render = None
        self.target_render = None
        self.status_var.set(
            self.i18n.text(
                "project.loaded_exact",
                name=result.bundle_folder.name if result.bundle_folder else result.project_json.name,
                faces=restored_faces,
            )
        )
        self._schedule_preview(immediate=True)

    def _load_project_path(self, path: Path) -> None:
        if self.paint_editor is not None:
            self.paint_editor.close(after_close=lambda: self._load_project_path(path))
            return
        if self.busy:
            messagebox.showinfo(
                "処理中です",
                "現在の処理が終わってからプロジェクトを読み込んでください。",
                parent=self.root,
            )
            return
        self._cancel_eyedropper()
        self._note_mix_input_change()
        developer_features_enabled = self._developer_features_are_enabled()

        def work():
            result = inspect_project_path(path)
            data = dict(result.project_data)
            loaded_settings = _project_settings_from_mapping(
                data,
                developer_features_enabled=developer_features_enabled,
            )
            loaded_settings = self._settings_with_saved_part_names(
                data, loaded_settings
            )
            reference_path = result.reference_image
            reference_image = None
            if reference_path is not None:
                with Image.open(reference_path) as opened:
                    reference_image = ImageOps.exif_transpose(opened).convert("RGBA")

            if result.prepared_geometry_snapshot is not None and result.source_ready:
                expected_key = tuple(_geometry_key(loaded_settings.geometry))
                snapshot = result.load_exact_prepared_geometry(
                    expected_geometry_key=expected_key
                )
                current_fingerprint = mesh_fingerprint(snapshot.prepared.final)
                result.verify_prepared_mesh_fingerprint(current_fingerprint)
                manual_payload = data.get("manual_paint")
                manual_overrides = None
                if isinstance(manual_payload, dict):
                    manual_overrides = decode_manual_overrides(
                        manual_payload,
                        expected_face_count=len(snapshot.prepared.final.faces),
                        expected_fingerprint=current_fingerprint,
                    )
                part_name_error = None
                try:
                    apply_part_name_overrides(
                        snapshot.prepared, loaded_settings.part_names
                    )
                except PartNameError as exc:
                    loaded_settings.part_names = {}
                    part_name_error = str(exc)
                return (
                    "exact",
                    result,
                    data,
                    loaded_settings,
                    reference_path,
                    reference_image,
                    snapshot,
                    manual_overrides,
                    current_fingerprint,
                    part_name_error,
                )
            return (
                "source",
                result,
                data,
                loaded_settings,
                reference_path,
                reference_image,
            )

        def done(validated_load) -> None:
            mode = validated_load[0]
            result = validated_load[1]
            data = validated_load[2]
            loaded_settings = validated_load[3]
            reference_path = validated_load[4]
            reference_image = validated_load[5]
            if mode == "exact":
                (
                    snapshot,
                    manual_overrides,
                    current_fingerprint,
                    part_name_error,
                ) = validated_load[6:]
                self._install_exact_project_snapshot(
                    result,
                    data,
                    loaded_settings,
                    snapshot,
                    manual_overrides,
                    current_fingerprint,
                    part_name_error,
                    reference_path=reference_path,
                    reference_image=reference_image,
                )
                return

            selected_source = result.source_asset if result.source_ready else None
            if result.state is ProjectLoadState.NEEDS_SOURCE_OBJ:
                replacement = filedialog.askopenfilename(
                    parent=self.root,
                    title=self.i18n.text(
                        "project.legacy_choose_obj",
                        name=result.legacy_source_name
                        or self.i18n.text("filedialog.model_short"),
                    ),
                    filetypes=(
                        (self.i18n.text("filedialog.model"), "*.obj *.glb"),
                        ("Wavefront OBJ", "*.obj"),
                        ("Binary glTF (GLB)", "*.glb"),
                        (self.i18n.text("filedialog.all"), "*.*"),
                    ),
                )
                selected_source = Path(replacement) if replacement else None
                if (
                    selected_source is not None
                    and selected_source.suffix.lower() not in {".obj", ".glb"}
                ):
                    messagebox.showerror(
                        self.i18n.text("dialog.source_format.title"),
                        self.i18n.text("dialog.source_format.message"),
                        parent=self.root,
                    )
                    selected_source = None

            self._apply_project_payload(
                data,
                loaded_settings,
                reference_path=reference_path,
                reference_image=reference_image,
                ignored_features=result.ignored_features,
            )
            if selected_source is not None:
                self.source_path = selected_source
                self.obj_name_var.set(self._source_display_text())
                self._process_geometry(reuse_asset=False)
            else:
                self._project_obj_recovery_pending = True
                self._clear_project_geometry()
                if self.pending_manual_payload is not None:
                    messagebox.showwarning(
                        self.i18n.text("project.legacy_pending_title"),
                        self.i18n.text("project.legacy_pending_message"),
                        parent=self.root,
                    )

        def failed(exc: Exception, _details: str) -> bool:
            messagebox.showerror(
                self.i18n.text("project.load_error"),
                str(exc),
                parent=self.root,
            )
            return True

        self._submit_main(
            self.i18n.text("project.restore_working"),
            work,
            done,
            on_error=failed,
        )

    def _calibration_target_label(self) -> str:
        """Return a stable user-facing label for the palette being exported."""

        key = self.active_part_key
        if key is None:
            return self.i18n.text("parts.common")
        if self.prepared is not None:
            try:
                part_id = self.prepared.final.part_keys.index(key)
                return str(self.prepared.final.part_names[part_id])
            except (AttributeError, IndexError, ValueError):
                pass
        saved_name = self.settings.part_names.get(key)
        return str(saved_name or key)

    def _export_palette_calibration_chart(self) -> None:
        """Generate a printable palette chart without requiring an OBJ."""

        # Check before showing a native folder picker.  ``_submit_main`` also
        # guards this boundary, but that later check would make a user choose a
        # destination only to be told that another operation is still running.
        if self.busy:
            messagebox.showinfo(
                self.i18n.text("dialog.busy.title"),
                self.i18n.text("dialog.busy.message"),
                parent=self.root,
            )
            return

        try:
            # Read only the active palette controls.  Chart generation must not
            # be blocked by an absent OBJ or by unrelated geometry/tone fields.
            # Copy before crossing the worker boundary so later Tk edits cannot
            # mutate the in-flight calibration snapshot.
            palette = self._copy_palette(self._palette_from_variables())
        except (ValueError, tk.TclError) as exc:
            reason = str(exc)
            self.status_var.set(
                self.i18n.text("state.calibration_error", reason=reason)
            )
            messagebox.showerror(
                self.i18n.text("dialog.calibration_error.title"),
                self.i18n.text(
                    "dialog.calibration_error.message", reason=reason
                ),
                parent=self.root,
            )
            return

        selected_folder = filedialog.askdirectory(
            parent=self.root,
            title=self.i18n.text("filedialog.save_calibration_folder"),
            mustexist=True,
        )
        if not selected_folder:
            return

        parent_directory = Path(selected_folder).resolve()
        language = str(self.i18n.language)
        target_label = self._calibration_target_label()
        running_text = self.i18n.text("state.calibration_exporting")

        def work():
            self._thread_progress("calibration", 0.02, running_text)
            result = generate_palette_calibration_bundle(
                parent_directory,
                palette,
                language=language,
                target_label=target_label,
            )
            self._thread_progress("calibration", 0.98, running_text)
            return result

        def done(result) -> None:
            folder = str(result.folder)
            self.status_var.set(
                self.i18n.text(
                    "state.calibration_done",
                    count=int(result.state_count),
                    folder=folder,
                )
            )
            open_folder = messagebox.askyesno(
                self.i18n.text("dialog.calibration_done.title"),
                self.i18n.text(
                    "dialog.calibration_done.message",
                    count=int(result.state_count),
                    folder=folder,
                ),
                parent=self.root,
            )
            if not open_folder:
                return
            try:
                os.startfile(result.folder)  # type: ignore[attr-defined]
            except (AttributeError, OSError) as exc:
                messagebox.showerror(
                    self.i18n.text("dialog.calibration_folder_error.title"),
                    self.i18n.text(
                        "dialog.calibration_folder_error.message",
                        reason=str(exc),
                    ),
                    parent=self.root,
                )

        def on_error(exc: Exception, _details: str) -> bool:
            reason = str(exc)
            self.status_var.set(
                self.i18n.text("state.calibration_error", reason=reason)
            )
            messagebox.showerror(
                self.i18n.text("dialog.calibration_error.title"),
                self.i18n.text(
                    "dialog.calibration_error.message", reason=reason
                ),
                parent=self.root,
            )
            return True

        self._submit_main(
            running_text,
            work,
            done,
            on_error=on_error,
        )

    def _convert_color_depth_part_3mf(self) -> None:
        """Convert one normal per-part 3MF without requiring an OBJ project."""

        if not self._require_developer_features():
            return
        if self.busy:
            messagebox.showinfo(
                self.i18n.text("dialog.busy.title"),
                self.i18n.text("dialog.busy.message"),
                parent=self.root,
            )
            return
        settings = self._variables_to_settings(show_error=True)
        if settings is None:
            return
        if not settings.color_depth.experimental_enabled:
            messagebox.showinfo(
                self.i18n.text("color_depth.error_title"),
                self.i18n.text("color_depth.reason.opt_in_required"),
                parent=self.root,
            )
            return

        value = filedialog.askopenfilename(
            parent=self.root,
            title=self.i18n.text("filedialog.open_color_depth_part_3mf"),
            filetypes=(("3MF", "*.3mf"),),
        )
        if not value:
            return
        source = Path(value)
        inspecting = self.i18n.text("color_depth.inspecting_part_3mf")

        def inspect_work():
            self._thread_progress(
                "color_depth_3mf_inspect", 0.02, inspecting
            )
            imported = inspect_color_depth_3mf(source)
            self._thread_progress(
                "color_depth_3mf_inspect", 0.98, inspecting
            )
            return imported

        def inspected(imported) -> None:
            physical = tuple(str(value) for value in imported.physical_slot_order)
            physical_slots = "\n".join(
                f"F{index}: {color}"
                for index, color in enumerate(physical, start=1)
            )
            states_by_pair: dict[tuple[int, int], list[int]] = {}
            for state_number, pair in enumerate(imported.print_mix_specs, start=5):
                physical_pair = (int(pair[0]), int(pair[1]))
                states_by_pair.setdefault(physical_pair, []).append(state_number)
            state_pairs = "\n".join(
                f"F{first}+F{second}: "
                + ", ".join(f"S{state}" for state in state_numbers)
                for (first, second), state_numbers in states_by_pair.items()
            )
            proceed = messagebox.askokcancel(
                self.i18n.text("color_depth.convert_confirm_title"),
                self.i18n.text(
                    "color_depth.convert_confirm_message",
                    physical_slots=physical_slots,
                    state_count=int(imported.palette_state_count),
                    state_pairs=state_pairs,
                    thickness=float(
                        settings.color_depth.outer_thickness_mm
                    ),
                    layer=float(settings.color_depth.layer_height_mm),
                ),
                parent=self.root,
            )
            if not proceed:
                return
            destination_value = filedialog.asksaveasfilename(
                parent=self.root,
                title=self.i18n.text(
                    "filedialog.save_converted_color_depth_3mf"
                ),
                initialdir=str(source.parent),
                initialfile=(
                    f"{source.stem}_ColorDepthLab_SLICE_ONLY.3mf"
                ),
                defaultextension=".3mf",
                filetypes=(("3MF", "*.3mf"),),
            )
            if not destination_value:
                return
            destination = Path(destination_value).with_suffix(".3mf")
            if _paths_refer_to_same_file(source, destination):
                messagebox.showerror(
                    self.i18n.text("color_depth.error_title"),
                    self.i18n.text(
                        "color_depth.reason.source_equals_destination"
                    ),
                    parent=self.root,
                )
                return

            running = self.i18n.text("color_depth.running")

            def convert_work():
                return export_color_depth_from_3mf(
                    source,
                    settings,
                    destination,
                    progress=self._thread_progress,
                )

            def converted(result) -> None:
                self.status_var.set(str(result.model_path))
                collapsed = sum(
                    len(group) for group in result.collapsed_target_groups
                )
                open_folder = messagebox.askyesno(
                    self.i18n.text("color_depth.done_title"),
                    self.i18n.text(
                        "color_depth.done_message",
                        path=str(result.model_path),
                        thickness=float(result.outer_thickness_mm),
                        layer=float(result.layer_height_mm),
                        collapsed=int(collapsed),
                    ),
                    parent=self.root,
                )
                if open_folder:
                    try:
                        os.startfile(result.model_path.parent)  # type: ignore[attr-defined]
                    except (AttributeError, OSError):
                        pass

            def convert_error(exc: Exception, _details: str) -> bool:
                reason = _color_depth_error_reason(self.i18n, exc)
                self.status_var.set(reason)
                messagebox.showerror(
                    self.i18n.text("color_depth.error_title"),
                    self.i18n.text(
                        "color_depth.error_message", reason=reason
                    ),
                    parent=self.root,
                )
                return True

            self._submit_main(
                running,
                convert_work,
                converted,
                on_error=convert_error,
            )

        def inspect_error(exc: Exception, _details: str) -> bool:
            reason = self.i18n.text(
                "color_depth.reason.invalid_part_3mf", reason=str(exc)
            )
            self.status_var.set(reason)
            messagebox.showerror(
                self.i18n.text("color_depth.error_title"),
                reason,
                parent=self.root,
            )
            return True

        self._submit_main(
            inspecting,
            inspect_work,
            inspected,
            on_error=inspect_error,
        )

    def _export_color_depth_experiment(self) -> None:
        """Export r21's all-state, physical-only ColorDepth laboratory 3MF."""

        if not self._require_developer_features():
            return
        if self.paint_editor is not None:
            self.paint_editor.close(
                after_close=self._export_color_depth_experiment
            )
            return
        if self.busy:
            messagebox.showinfo(
                self.i18n.text("dialog.busy.title"),
                self.i18n.text("dialog.busy.message"),
                parent=self.root,
            )
            return
        if self.prepared is None or self.source_path is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.process"),
                parent=self.root,
            )
            return
        settings = self._variables_to_settings(show_error=True)
        if settings is None:
            return
        if not settings.color_depth.experimental_enabled:
            messagebox.showinfo(
                self.i18n.text("color_depth.error_title"),
                self.i18n.text("color_depth.reason.opt_in_required"),
                parent=self.root,
            )
            return
        if self.prepared_key != _geometry_key(settings.geometry):
            self._process_geometry(
                reuse_asset=self.asset is not None,
                after_done=self._export_color_depth_experiment,
            )
            return
        valid_paint, manual_overrides = self._validated_manual_overrides(
            make_copy=True
        )
        if not valid_paint:
            return
        proceed = messagebox.askokcancel(
            self.i18n.text("color_depth.confirm_title"),
            self.i18n.text(
                "color_depth.confirm_message",
                thickness=float(settings.color_depth.outer_thickness_mm),
                layer=float(settings.color_depth.layer_height_mm),
            ),
            parent=self.root,
        )
        if not proceed:
            return
        value = filedialog.asksaveasfilename(
            parent=self.root,
            title=self.i18n.text("filedialog.save_color_depth_3mf"),
            initialfile=(
                f"{self.source_path.stem}_ColorDepthLab_SLICE_ONLY.3mf"
            ),
            defaultextension=".3mf",
            filetypes=(("3MF", "*.3mf"),),
        )
        if not value:
            return
        destination = Path(value)
        prepared = self.prepared
        selected_part_key = getattr(self, "active_part_key", None)
        running = self.i18n.text("color_depth.running")

        def work():
            return export_color_depth_bundle(
                prepared,
                settings,
                destination,
                manual_overrides=manual_overrides,
                progress=self._thread_progress,
                part_key=selected_part_key,
            )

        def done(result) -> None:
            self.status_var.set(str(result.model_path))
            collapsed = sum(
                len(group) for group in result.collapsed_target_groups
            )
            open_folder = messagebox.askyesno(
                self.i18n.text("color_depth.done_title"),
                self.i18n.text(
                    "color_depth.done_message",
                    path=str(result.model_path),
                    thickness=float(result.outer_thickness_mm),
                    layer=float(result.layer_height_mm),
                    collapsed=int(collapsed),
                ),
                parent=self.root,
            )
            if open_folder:
                try:
                    os.startfile(result.model_path.parent)  # type: ignore[attr-defined]
                except (AttributeError, OSError):
                    pass

        def on_error(exc: Exception, _details: str) -> bool:
            reason = _color_depth_error_reason(self.i18n, exc)
            self.status_var.set(reason)
            messagebox.showerror(
                self.i18n.text("color_depth.error_title"),
                self.i18n.text(
                    "color_depth.error_message", reason=reason
                ),
                parent=self.root,
            )
            return True

        self._submit_main(
            running,
            work,
            done,
            on_error=on_error,
        )

    def _export_radial_experiment(self) -> None:
        """Export the separate Cycle-free radial laboratory format."""

        if not self._require_developer_features():
            return
        if self.paint_editor is not None:
            self.paint_editor.close(after_close=self._export_radial_experiment)
            return
        if self.busy:
            messagebox.showinfo(
                self.i18n.text("dialog.busy.title"),
                self.i18n.text("dialog.busy.message"),
                parent=self.root,
            )
            return
        if self.prepared is None or self.source_path is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.process"),
                parent=self.root,
            )
            return
        settings = self._variables_to_settings(show_error=True)
        if settings is None:
            return
        if self.prepared_key != _geometry_key(settings.geometry):
            self._process_geometry(
                reuse_asset=self.asset is not None,
                after_done=self._export_radial_experiment,
            )
            return
        valid_paint, manual_overrides = self._validated_manual_overrides(
            make_copy=True
        )
        if not valid_paint:
            return
        value = filedialog.asksaveasfilename(
            parent=self.root,
            title=self.i18n.text("filedialog.save_radial_3mf"),
            initialfile=(
                f"{self.source_path.stem}_RadialLab_SLICE_ONLY.3mf"
            ),
            defaultextension=".3mf",
            filetypes=(("3MF", "*.3mf"),),
        )
        if not value:
            return
        destination = Path(value)
        prepared = self.prepared
        black_slot = self._black_output_slot_index()
        running = self.i18n.text("radial.running")

        def work():
            return export_radial_bundle(
                prepared,
                settings,
                destination,
                black_slot=black_slot,
                manual_overrides=manual_overrides,
                progress=self._thread_progress,
            )

        def done(result) -> None:
            self.status_var.set(str(result.model_path))
            open_folder = messagebox.askyesno(
                self.i18n.text("radial.done_title"),
                self.i18n.text(
                    "radial.done_message",
                    path=str(result.model_path),
                    thickness=float(result.skin_thickness_mm),
                    layer=float(result.layer_height_mm),
                ),
                parent=self.root,
            )
            if open_folder:
                try:
                    os.startfile(result.model_path.parent)  # type: ignore[attr-defined]
                except (AttributeError, OSError):
                    pass

        def on_error(exc: Exception, _details: str) -> bool:
            reason = _radial_error_reason(self.i18n, exc)
            self.status_var.set(reason)
            messagebox.showerror(
                self.i18n.text("radial.error_title"),
                self.i18n.text("radial.error_message", reason=reason),
                parent=self.root,
            )
            return True

        self._submit_main(
            running,
            work,
            done,
            on_error=on_error,
        )

    def _export(self) -> None:
        if self.paint_editor is not None:
            self.paint_editor.close(after_close=self._export)
            return
        if self.prepared is None or self.source_path is None:
            messagebox.showinfo(
                self.i18n.text("dialog.obj_required.title"),
                self.i18n.text("dialog.obj_required.process"),
                parent=self.root,
            )
            return
        settings = self._variables_to_settings(show_error=True)
        if settings is None:
            return
        if self.prepared_key != _geometry_key(settings.geometry):
            self._process_geometry(reuse_asset=self.asset is not None, after_done=self._export)
            return
        if not bool(self.prepared.topology.get("watertight")):
            assembly = dict(self.prepared.assembly or {})
            unmatched = int(
                assembly.get("unmatched_boundary_loop_count", 0) or 0
            )
            inspect_now = messagebox.askyesno(
                self.i18n.text("assembly.export_blocked_title"),
                self.i18n.text(
                    "assembly.export_blocked_open",
                    boundaries=int(
                        self.prepared.topology.get("boundary_edges", 0) or 0
                    ),
                    unmatched=unmatched,
                ),
                parent=self.root,
            )
            if inspect_now and assembly.get("boundary_diagnostics"):
                self._show_boundary_diagnostics()
            return
        grouping = plan_palette_groups(settings, self.prepared.final)
        force_common_palette = False
        individual_only = False
        if grouping.requires_separate_jobs:
            resolved_materials = {
                palette.material
                for palette in resolve_part_palette_settings(
                    settings, self.prepared.final
                )
            }
            if len(resolved_materials) > 1:
                individual_only = messagebox.askyesno(
                    self.i18n.text("export.cross_material_title"),
                    self.i18n.text(
                        "export.cross_material_body",
                        materials=" / ".join(sorted(resolved_materials)),
                    ),
                    parent=self.root,
                )
                if not individual_only:
                    self.status_var.set(
                        self.i18n.text("export.cross_material_cancelled")
                    )
                    return
            else:
                part_export_note = (
                    "\n\n同時に、生成した分割パーツごとの基本4色を使う"
                    "独立3MFも出力します。"
                    if settings.geometry.export_individual_parts
                    else ""
                )
                force_common_palette = messagebox.askyesno(
                    "パーツ別4色は1回で印刷できません",
                    f"現在は{len(grouping.groups)}種類の基本フィラメント構成があります。\n\n"
                    "Snapmaker U1へ同時装填できる物理フィラメントは4本なので、"
                    "異なる構成を1つのFull Spectrumジョブへ正しく記録できません。\n\n"
                    "モデルの印刷パーツ構造と個別設定メタデータは保持したまま、"
                    "印刷色だけ［全体共通］の4色へ統合して出力しますか？\n"
                    + part_export_note
                    + "\n［いいえ］では出力を中止し、調整プロジェクトの設定を保ちます。",
                    parent=self.root,
                )
                if not force_common_palette:
                    self.status_var.set(
                        "3MF出力を中止しました。印刷パーツ別設定は保持されています"
                    )
                    return
        valid_paint, manual_overrides = self._validated_manual_overrides(
            make_copy=True
        )
        if not valid_paint:
            return
        if not self._confirm_black_free_manual_overrides(
            settings,
            manual_overrides,
            force_common_palette=force_common_palette,
        ):
            return
        value = filedialog.asksaveasfilename(
            parent=self.root,
            title=self.i18n.text("filedialog.save_3mf"),
            initialfile=f"{self.source_path.stem}_FullSpectrum.3mf",
            defaultextension=".3mf",
            filetypes=(("3MF", "*.3mf"),),
        )
        if not value:
            return
        destination = Path(value)
        include_vertex_obj = bool(self.include_obj_var.get())
        prepared = self.prepared
        reference_path = self.reference_path

        def work():
            return export_bundle(
                prepared,
                settings,
                destination,
                reference_path,
                include_vertex_obj=include_vertex_obj,
                progress=self._thread_progress,
                manual_overrides=manual_overrides,
                force_common_palette=force_common_palette,
                individual_only=individual_only,
            )

        def done(result) -> None:
            individual_count = len(result.part_model_paths)
            if result.individual_only:
                self.status_var.set(
                    self.i18n.text(
                        "export.individual_only_status",
                        count=individual_count,
                    )
                )
            else:
                warning_parts = int(
                    result.validation.get(
                        "self_intersection_warning_parts", 0
                    )
                    or 0
                )
                status_key = (
                    "export.done_status_warning"
                    if warning_parts
                    else "export.done_status"
                )
                status_text = self.i18n.text(
                    status_key, name=result.model_path.name
                )
                if individual_count:
                    status_text += f" / part 3MF: {individual_count}"
                self.status_var.set(status_text)
            if result.individual_only:
                dialog_title = self.i18n.text(
                    "export.individual_only_done_title"
                )
                dialog_body = self.i18n.text(
                    "export.individual_only_done_body",
                    folder=result.part_model_paths[0].parent,
                    count=individual_count,
                )
            else:
                part_message = (
                    self.i18n.text(
                        "export.individual_models_note",
                        count=individual_count,
                    )
                    if result.part_model_paths
                    else ""
                )
                assembly = dict(prepared.assembly or {})
                if bool(assembly.get("single_mesh_generic")):
                    structure_message = self.i18n.text(
                        "export.single_glb_structure"
                    )
                elif bool(assembly.get("solidify_parts")):
                    structure_message = self.i18n.text(
                        "export.closed_structure"
                    )
                else:
                    structure_message = self.i18n.text(
                        "export.current_structure"
                    )
                palette_message = (
                    self.i18n.text("export.common_palette_note")
                    if force_common_palette
                    else ""
                )
                warning_parts = int(
                    result.validation.get(
                        "self_intersection_warning_parts", 0
                    )
                    or 0
                )
                warning_message = (
                    self.i18n.text(
                        "export.self_intersection_warning",
                        parts=warning_parts,
                        faces=int(
                            result.validation.get(
                                "self_intersection_warning_faces", 0
                            )
                            or 0
                        ),
                        area=float(
                            result.validation.get(
                                "self_intersection_warning_area", 0.0
                            )
                            or 0.0
                        ),
                    )
                    if warning_parts
                    else ""
                )
                dialog_title = self.i18n.text("export.done_title")
                dialog_body = (
                    f"{result.model_path}\n\n"
                    + palette_message
                    + structure_message
                    + part_message
                    + warning_message
                    + self.i18n.text("export.done_instructions")
                )
            answer = messagebox.askyesno(
                dialog_title,
                dialog_body,
                parent=self.root,
            )
            if answer:
                output_folder = (
                    result.part_model_paths[0].parent
                    if result.individual_only
                    else result.model_path.parent
                )
                os.startfile(output_folder)  # type: ignore[attr-defined]

        self._submit_main("3MFを書き出しています", work, done)

    def _launch_orca(self) -> None:
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Snapmaker_Orca" / "snapmaker-orca.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Snapmaker Orca" / "Snapmaker Orca.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Snapmaker Orca" / "Snapmaker Orca.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Snapmaker Orca" / "Snapmaker Orca.exe",
        ]
        for name in ("Snapmaker Orca.exe", "snapmaker-orca.exe", "Snapmaker_Orca.exe"):
            found = shutil.which(name)
            if found:
                candidates.insert(0, Path(found))
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            value = filedialog.askopenfilename(
                parent=self.root,
                title=self.i18n.text("filedialog.select_orca"),
                filetypes=(
                    (self.i18n.text("filedialog.executable"), "*.exe"),
                ),
            )
            if not value:
                return
            executable = Path(value)
        try:
            subprocess.Popen([str(executable)], cwd=str(executable.parent))
            self.status_var.set("Snapmaker Orcaを起動しました。3MFはプロジェクトとして開いてください")
        except OSError as exc:
            messagebox.showerror(
                self.i18n.text("dialog.launch_orca_error"),
                str(exc),
                parent=self.root,
            )

    def _on_close(self) -> None:
        if self.app_closing:
            return
        self.app_closing = True
        self._save_persistent_settings()
        if self.paint_editor is not None:
            self.paint_editor.close(after_close=self._finish_close)
            return
        self._finish_close()

    def _finish_close(self) -> None:
        if self.poll_after_id is not None:
            try:
                self.root.after_cancel(self.poll_after_id)
            except tk.TclError:
                pass
            self.poll_after_id = None
        if self.filament_candidate_window is not None:
            try:
                self.filament_candidate_window.destroy()
            except (AttributeError, tk.TclError):
                pass
            self.filament_candidate_window = None
        if self.help_center is not None:
            try:
                self.help_center.destroy()
            except (AttributeError, tk.TclError):
                pass
            self.help_center = None
        self.main_executor.shutdown(wait=False, cancel_futures=True)
        self.preview_executor.shutdown(wait=False, cancel_futures=True)
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def launch_app(*, smoke_test: bool = False, initial_project: Path | None = None) -> int:
    root = tk.Tk()
    MapperApp(root, smoke_test=smoke_test, initial_project=initial_project)
    root.mainloop()
    return 0


__all__ = ["MapperApp", "launch_app"]
