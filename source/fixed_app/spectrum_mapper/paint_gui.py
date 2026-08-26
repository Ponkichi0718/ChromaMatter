from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import replace
import math
from pathlib import Path
import queue
import threading
import time
import traceback
from typing import Callable
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageTk

from . import renderer as renderer_module
from .calibration_chart import palette_family_display_rows
from .decal_image import DecalImage, DecalImageError, load_decal_image
from .decal_projection import (
    DecalBakePlan,
    DecalBakeResult,
    DecalPreview,
    DecalProjectionCancelled,
    DecalProjectionError,
    DecalStalePreviewError,
    DecalTransform,
    build_decal_preview,
    commit_decal_bake,
    composite_planned_decal_preview,
    decal_width_mm_to_pixels,
    plan_decal_bake,
    rasterize_decal_bake_plan,
    rasterize_existing_tree_states,
)
from .engine import (
    apply_palette_overrides_parts,
    recolor_level_parts,
    srgb_to_lab,
)
from .freehand_split import (
    FreehandSplitError,
    LassoSplitPlan,
    apply_lasso_split,
    apply_level_partition_to_prepared,
    canvas_polygon_to_render,
    inherit_explicit_part_palette,
    plan_lasso_component_split,
)
from .mixer import (
    PAIR_INDICES,
    PALETTE_STATE_COUNT,
    SUPPORTED_PALETTE_STATE_COUNTS,
    black_containing_mixed_states,
    build_palette_rgb,
    find_best_mix_recipes,
    palette_state_names,
    rgb8_to_hex,
)
from .joint_projection import JointProjectionError, canvas_point_on_face
from .manual_joint_state import remap_manual_overrides
from .manual_joints import (
    MANUAL_JOINT_WORKFLOW_KEYS,
    ManualJointError,
    ManualJointAvailability,
    ManualJointSettings,
    ManualJointTarget,
    apply_manual_joint,
    assess_manual_joint_availability,
    resolve_manual_joint_target,
)
from .manual_shortcuts import (
    PART_VISIBILITY_ACTIONS,
    TOOL_ACTIONS,
    install_manual_shortcuts,
    shortcut_help_rows,
)
from .models import (
    AppSettings,
    COLOR_MODE_FLAT_FOUR,
    PaletteSettings,
    PreparedGeometry,
    ToneSettings,
)
from .i18n import TkLocalizer, Translator
from .part_names import PartNameError, rename_prepared_part
from .paint import PaintSession
from .paint_tools import airbrush_hold_dab_count
from .palette_state_count import apply_palette_state_count_change
from .palette_usage import (
    analyze_palette_usage,
    estimate_base_filament_contributions,
    focus_palette_state,
    palette_state_base_weights,
)
from .parts import palette_identity, resolve_palette_for_part_key
from .renderer import (
    CameraState,
    InteractiveMeshRenderer,
    PART_HIDDEN,
    PART_TRANSPARENT,
    PART_VISIBLE,
    VIEW_THEME_VALUES,
    resolve_view_appearance,
)


BG = "#10141B"
PANEL = "#171D27"
PANEL_2 = "#202836"
TEXT = "#E8EDF5"
MUTED = "#9AA8BA"
ACCENT = "#56C7FF"
SUCCESS = "#62D59A"
WARNING = "#FFBF69"
RENDER_SIZE = (760, 760)
TONE_CALLBACK_DEBOUNCE_MS = 260
TOOL_RESTORE_DELAY_MS = 280
TOOL_RESTORE_VERIFY_DELAY_MS = 360
TOOL_RESTORE_RETRY_MS = 120
TOOL_RESTORE_MAX_RETRIES = 6

SHORT_NAMES = ("F1", "F2", "F3", "F4")
STATE_NAMES = palette_state_names()

PALETTE_TOOL_DESIRED_SIZE = (540, 760)
PALETTE_TOOL_MIN_SIZE = (420, 520)
PALETTE_TOOL_SCREEN_MARGIN = 80
PARTS_TOOL_DESIRED_SIZE = (470, 330)
PARTS_TOOL_MIN_SIZE = (430, 300)
# The operation guide is intentionally a slim reference strip.  It remains
# resizable, but its initial footprint no longer obscures the 3D workspace.
HELP_TOOL_DESIRED_SIZE = (360, 650)
HELP_TOOL_MIN_SIZE = (320, 420)
TOOL_WINDOW_OUTER_MARGIN = 20
TOOL_WINDOW_GAP = 20
# Tk ``geometry`` sizes only the client area.  Reserve the native Windows
# title bar/frame separately so stacked palettes neither overlap nor extend
# below a nominal 1920 x 1080 work area.
TOOL_WINDOW_CHROME_ALLOWANCE = 30
TOOL_WINDOW_STACK_GAP = 10
TOOL_WINDOW_EMERGENCY_MIN_SIZE = (320, 300)
MANUAL_ZOOM_MIN = 0.35
MANUAL_ZOOM_MAX = 24.0
MANUAL_ZOOM_STEP = 1.22


def compute_palette_tool_window_layout(
    screen_width: int,
    screen_height: int,
) -> tuple[str, tuple[int, int]]:
    """Fit the palette's initial size to the current display.

    The full 540 x 760 layout keeps all 32 colours and the usage summary
    readable on a normal display.  On a smaller display the window shrinks,
    while its scrollable body preserves access to every control.
    """

    screen_width = max(1, int(screen_width))
    screen_height = max(1, int(screen_height))
    desired_width, desired_height = PALETTE_TOOL_DESIRED_SIZE
    min_width, min_height = PALETTE_TOOL_MIN_SIZE
    width = min(desired_width, max(320, screen_width - PALETTE_TOOL_SCREEN_MARGIN))
    height = min(
        desired_height,
        max(360, screen_height - PALETTE_TOOL_SCREEN_MARGIN),
    )
    x = min(60, max(0, screen_width - width))
    # Once the client area has to shrink below the normal minimum, leave room
    # for the native title bar and the Windows taskbar as well.  Without this
    # final clamp an emergency-size palette can technically fit its Tk client
    # rectangle while its lower controls still end up behind OS chrome.
    vertical_chrome_margin = 50 if height < min_height else 0
    y = min(
        70,
        max(0, screen_height - height - vertical_chrome_margin),
    )
    effective_min = (min(min_width, width), min(min_height, height))
    return f"{width}x{height}+{x}+{y}", effective_min


def compute_manual_tool_window_layouts(
    screen_width: int,
    screen_height: int,
) -> dict[str, tuple[str, tuple[int, int]]]:
    """Place paint tools at the left and supporting panels at the right.

    The model stays readable between the two sides instead of being covered by
    a row of palettes near the centre.  Parts sits above the operation guide;
    those right-side windows never overlap.  On narrow displays both columns
    shrink and every rectangle remains inside the reported screen bounds.
    """

    screen_width = max(1, int(screen_width))
    screen_height = max(1, int(screen_height))
    margin = min(TOOL_WINDOW_OUTER_MARGIN, max(0, screen_width // 20))
    top = min(70, max(0, screen_height // 12))
    horizontal_gap = min(TOOL_WINDOW_GAP, max(0, screen_width // 20))
    usable_width = max(1, screen_width - margin * 2 - horizontal_gap)
    left_width = min(PALETTE_TOOL_DESIRED_SIZE[0], max(1, usable_width // 2))
    right_column_width = min(
        max(PARTS_TOOL_DESIRED_SIZE[0], HELP_TOOL_DESIRED_SIZE[0]),
        max(1, usable_width - left_width),
    )
    # Give both sides the same emergency share on narrow screens.  This avoids
    # a 540px paint palette swallowing the Parts panel at laptop resolutions.
    if usable_width >= 640:
        left_width = min(PALETTE_TOOL_DESIRED_SIZE[0], usable_width // 2)
        right_column_width = min(
            max(PARTS_TOOL_DESIRED_SIZE[0], HELP_TOOL_DESIRED_SIZE[0]),
            usable_width - left_width,
        )
    left_x = margin
    right_x = max(0, screen_width - margin - right_column_width)
    parts_width = min(PARTS_TOOL_DESIRED_SIZE[0], right_column_width)
    help_width = min(HELP_TOOL_DESIRED_SIZE[0], right_column_width)

    chrome_allowance = (
        TOOL_WINDOW_CHROME_ALLOWANCE if screen_height >= 300 else 0
    )
    available_height = max(
        1,
        screen_height - top - margin - chrome_allowance,
    )
    palette_height = min(PALETTE_TOOL_DESIRED_SIZE[1], available_height)
    vertical_gap = (
        TOOL_WINDOW_STACK_GAP if screen_height >= 100 else 0
    )
    stacked_height = max(
        1,
        screen_height
        - top
        - margin
        - chrome_allowance * 2
        - vertical_gap,
    )
    parts_height = min(
        PARTS_TOOL_DESIRED_SIZE[1],
        max(1, int(stacked_height * 0.36)),
    )
    help_height = max(1, stacked_height - parts_height)
    help_y = min(
        screen_height - help_height,
        top + parts_height + chrome_allowance + vertical_gap,
    )

    def layout(
        width: int,
        height: int,
        x: int,
        y: int,
        minimum: tuple[int, int],
    ) -> tuple[str, tuple[int, int]]:
        width = max(1, min(int(width), screen_width))
        height = max(1, min(int(height), screen_height))
        x = max(0, min(int(x), screen_width - width))
        y = max(0, min(int(y), screen_height - height))
        return (
            f"{width}x{height}+{x}+{y}",
            (min(minimum[0], width), min(minimum[1], height)),
        )

    return {
        "palette": layout(
            left_width,
            palette_height,
            left_x,
            top,
            PALETTE_TOOL_MIN_SIZE,
        ),
        "parts": layout(
            parts_width,
            parts_height,
            screen_width - margin - parts_width,
            top,
            PARTS_TOOL_MIN_SIZE,
        ),
        "help": layout(
            help_width,
            help_height,
            screen_width - margin - help_width,
            help_y,
            HELP_TOOL_MIN_SIZE,
        ),
    }


def _copy_palette_settings(palette: PaletteSettings) -> PaletteSettings:
    return PaletteSettings(
        material=palette.material,
        palette_state_count=palette.palette_state_count,
        color_mode=getattr(palette, "color_mode", "full_spectrum"),
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
        surface_shell_enabled=bool(
            getattr(palette, "surface_shell_enabled", False)
        ),
        physical_filament_refs=list(palette.physical_filament_refs),
    )


def _effective_paint_enabled_states(palette: PaletteSettings) -> np.ndarray:
    """Return paint candidates without mutating reversible palette settings."""

    enabled = np.asarray(palette.enabled_states, dtype=bool).copy()
    if getattr(palette, "color_mode", None) == COLOR_MODE_FLAT_FOUR:
        enabled[4:] = False
    return enabled


def _effective_paint_state_map(
    palette: PaletteSettings,
    *,
    palette_rgb: np.ndarray | None = None,
) -> np.ndarray:
    """Map canonical state IDs to the colours currently visible to Fill.

    Full Spectrum uses the identity map.  Flat 4 Colors uses the same
    non-destructive nearest-physical projection as its manual preview: legacy
    mixed IDs stay stored, while visually identical connected faces can be
    filled as one region.
    """

    mapping = np.arange(PALETTE_STATE_COUNT, dtype=np.int8)
    if getattr(palette, "color_mode", None) != COLOR_MODE_FLAT_FOUR:
        return mapping
    if palette_rgb is None:
        _palette_hex, palette_rgb = build_palette_rgb(
            palette.physical_hex,
            palette.mix_hex_overrides,
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
    colors = np.asarray(palette_rgb, dtype=np.float64)
    if colors.shape != (PALETTE_STATE_COUNT, 3) or not np.all(
        np.isfinite(colors)
    ):
        raise ValueError(
            f"Flat 4 Colors requires a {PALETTE_STATE_COUNT}x3 palette table"
        )
    delta = colors[4:, None, :] - colors[None, :4, :]
    mapping[4:] = np.argmin(np.sum(delta * delta, axis=2), axis=1)
    return mapping


def _effective_paint_state(
    palette: PaletteSettings,
    state: int,
    *,
    palette_rgb: np.ndarray | None = None,
) -> int:
    """Return the state a new manual edit may write in the active mode.

    Flat 4 Colors deliberately keeps old Full Spectrum overrides intact so a
    later mode switch can restore them.  New manual input, however, must use a
    physical F1-F4 state.  The nearest-colour rule matches the non-destructive
    remap used by :func:`engine.apply_palette_overrides` for Flat previews and
    export.
    """

    selected = int(state)
    if getattr(palette, "color_mode", None) != COLOR_MODE_FLAT_FOUR:
        return selected
    if 0 <= selected < 4:
        return selected
    if selected < 0 or selected >= PALETTE_STATE_COUNT:
        return 0
    try:
        return int(
            _effective_paint_state_map(
                palette,
                palette_rgb=palette_rgb,
            )[selected]
        )
    except ValueError:
        return 0


def _editor_palette_if_available(editor: object) -> PaletteSettings | None:
    """Resolve an editor palette while keeping lightweight legacy callers valid."""

    resolver = getattr(editor, "_active_palette", None)
    if callable(resolver):
        try:
            return resolver()
        except (AttributeError, IndexError, KeyError, ValueError):
            pass
    settings = getattr(editor, "settings", None)
    palette = getattr(settings, "palette", None)
    return palette if isinstance(palette, PaletteSettings) else None


def _is_manual_only_palette_state(
    palette: PaletteSettings,
    state: int,
) -> bool:
    """Whether a state remains paintable but is excluded from automation."""

    if not palette.enabled_states[state]:
        return True
    if not bool(getattr(palette, "black_free_gradient_enabled", False)):
        return False
    return int(state) in black_containing_mixed_states(
        palette.palette_state_count,
        int(getattr(palette, "black_free_black_slot", 0)),
    )


def _readable_text(rgb: np.ndarray) -> str:
    r, g, b = (float(value) for value in rgb)
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#0B0D11" if luminance > 0.58 else "#FFFFFF"


def overlay_visible_creases(
    image: Image.Image,
    face_ids: np.ndarray,
    face_normals: np.ndarray,
    angle_degrees: float,
) -> Image.Image:
    """Draw readable, image-space crease lines over the current 3D frame.

    A dark halo plus a pale-gold core stays visible on both black armour and
    light skin.  Only boundaries whose face normals differ by more than the
    requested angle are drawn, so dense triangulation does not become a wire
    mesh overlay.  The strict comparison matches the crease guard in the
    paint core at the threshold itself.
    """

    ids = np.asarray(face_ids)
    # Keep the shared per-face normal array zero-copy.  Large production
    # models can contain millions of faces while the current frame exposes
    # only a screen-sized subset of face pairs.
    normals = np.asarray(face_normals)
    if (
        ids.ndim != 2
        or ids.shape[::-1] != image.size
        or normals.ndim != 2
        or normals.shape[1:] != (3,)
        or len(normals) == 0
    ):
        return image
    threshold_dot = math.cos(math.radians(max(0.0, min(180.0, float(angle_degrees)))))
    core = np.zeros(ids.shape, dtype=bool)

    def mark_pairs(left: np.ndarray, right: np.ndarray, axis: str) -> None:
        valid = (
            (left >= 0)
            & (right >= 0)
            & (left < len(normals))
            & (right < len(normals))
            & (left != right)
        )
        if not np.any(valid):
            return
        # Normalize only normals referenced by visible boundary pixels.  This
        # avoids two full-mesh float64 arrays on every exact camera frame.
        left_vectors = np.asarray(normals[left[valid]], dtype=np.float64)
        right_vectors = np.asarray(normals[right[valid]], dtype=np.float64)
        denominators = np.linalg.norm(left_vectors, axis=1) * np.linalg.norm(
            right_vectors, axis=1
        )
        pair_valid = np.isfinite(denominators) & (denominators > 1e-12)
        pair_dots = np.ones(len(denominators), dtype=np.float64)
        pair_dots[pair_valid] = np.einsum(
            "ij,ij->i",
            left_vectors[pair_valid],
            right_vectors[pair_valid],
        ) / denominators[pair_valid]
        visible_crease = pair_valid & (pair_dots < threshold_dot - 1e-12)
        crease = np.zeros(left.shape, dtype=bool)
        crease[valid] = visible_crease
        if axis == "x":
            core[:, :-1] |= crease
            core[:, 1:] |= crease
        else:
            core[:-1, :] |= crease
            core[1:, :] |= crease

    if ids.shape[1] > 1:
        mark_pairs(ids[:, :-1], ids[:, 1:], "x")
    if ids.shape[0] > 1:
        mark_pairs(ids[:-1, :], ids[1:, :], "y")
    if not np.any(core):
        return image

    halo = core.copy()
    # Two dilation passes make the line survive down-sampling in the editor.
    for _unused in range(2):
        expanded = halo.copy()
        expanded[1:, :] |= halo[:-1, :]
        expanded[:-1, :] |= halo[1:, :]
        expanded[:, 1:] |= halo[:, :-1]
        expanded[:, :-1] |= halo[:, 1:]
        halo = expanded
    pixels = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
    pixels[halo] = np.asarray((13, 18, 25), dtype=np.uint8)
    pixels[core] = np.asarray((255, 220, 112), dtype=np.uint8)
    return Image.fromarray(pixels, mode="RGB")


def compute_manual_canvas_layout(
    width: int,
    height: int,
    reference_visible: bool,
) -> dict[str, object]:
    """Return the responsive reference/3D panel geometry.

    Keeping this calculation independent from Tk makes the important editing
    area contract easy to regression-test: with the reference drawer closed,
    the 3D view receives the whole workspace; when opened, the reference uses
    only the left 30 percent.
    """

    canvas_width = max(720, int(width))
    canvas_height = max(420, int(height))
    margin = 14
    gap = 14
    title_height = 34
    available_width = canvas_width - margin * 2
    panel_height = max(300, canvas_height - margin * 2 - title_height)
    reference: tuple[int, int] | None = None
    if reference_visible:
        usable_width = available_width - gap
        reference_width = max(240, int(usable_width * 0.30))
        target_width = max(420, usable_width - reference_width)
        reference = (margin, reference_width)
        target = (margin + reference_width + gap, target_width)
    else:
        target = (margin, max(420, available_width))
    return {
        "width": canvas_width,
        "height": canvas_height,
        "margin": margin,
        "title_height": title_height,
        "panel_height": panel_height,
        "reference": reference,
        "target": target,
    }


class PaintEditorWindow:
    """Final-mesh paint correction window.

    All geometry edits and ModernGL calls run on one worker thread.  The Tk
    thread only stores the latest rendered image and face-ID map.
    """

    def __init__(
        self,
        parent: tk.Tk,
        prepared: PreparedGeometry,
        settings: AppSettings,
        reference_image: Image.Image | None,
        initial_overrides: np.ndarray | None,
        on_overrides_changed: Callable[[np.ndarray], None],
        on_closed: Callable[[], None] | None = None,
        on_parts_changed: Callable[[], None] | None = None,
        on_geometry_changed: Callable[
            [PreparedGeometry, np.ndarray, dict[str, object] | None], None
        ]
        | None = None,
        language: str = "ja",
        show_boundary_diagnostics: bool = False,
        on_part_name_changed: Callable[[str, str], None] | None = None,
        on_view_background_changed: Callable[[str, str], None] | None = None,
        on_orbit_direction_changed: Callable[[bool], None] | None = None,
        on_solidify_requested: Callable[[], None] | None = None,
        on_tone_settings_changed: Callable[[ToneSettings], None] | None = None,
        on_palette_settings_changed: Callable[
            [str | None, PaletteSettings], None
        ]
        | None = None,
        on_mix_optimization_requested: Callable[[str | None], None] | None = None,
        on_mix_optimization_undo_requested: Callable[[str | None], None]
        | None = None,
        on_tone_reset_requested: Callable[[], None] | None = None,
    ) -> None:
        self.parent = parent
        self.prepared = prepared
        self.level = prepared.final
        self.settings = AppSettings.from_dict(settings.to_dict())
        self.part_keys = tuple(self.level.part_keys) or ("__whole_model__",)
        self.part_names = tuple(self.level.part_names) or ("OBJ全体",)
        self.active_part_id = 0
        self.part_labels = tuple(
            f"{index + 1}: {name}"
            for index, name in enumerate(self.part_names)
        )
        self.reference_image = reference_image.copy() if reference_image is not None else None
        self.initial_overrides = (
            np.asarray(initial_overrides, dtype=np.int8).copy()
            if initial_overrides is not None
            else None
        )
        self.on_overrides_changed = on_overrides_changed
        self.on_parts_changed = on_parts_changed
        self.on_geometry_changed = on_geometry_changed
        self.on_part_name_changed = on_part_name_changed
        self.on_view_background_changed = on_view_background_changed
        self.on_orbit_direction_changed = on_orbit_direction_changed
        self.on_solidify_requested = on_solidify_requested
        self.on_tone_settings_changed = on_tone_settings_changed
        self.on_palette_settings_changed = on_palette_settings_changed
        self.on_mix_optimization_requested = on_mix_optimization_requested
        self.on_mix_optimization_undo_requested = (
            on_mix_optimization_undo_requested
        )
        self.on_tone_reset_requested = on_tone_reset_requested
        self.on_closed = on_closed
        self.i18n = Translator(language)
        self.localizer = TkLocalizer(self.i18n)

        self.window = tk.Toplevel(parent)
        self.window.title(self.i18n.text("paint.title"))
        self.window.geometry("1480x900")
        self.window.minsize(1080, 700)
        self.window.resizable(True, True)
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self.tool_var = tk.StringVar(value="brush")
        self._last_tool_mode = "brush"
        self.paint_state_var = tk.IntVar(value=1)
        self.manual_palette_state_count_var = tk.IntVar(
            value=self.settings.palette.palette_state_count
        )
        self.brush_radius_var = tk.DoubleVar(value=1.5)
        self.airbrush_strength_var = tk.DoubleVar(value=35.0)
        self.smudge_strength_var = tk.DoubleVar(value=65.0)
        self.edge_guard_var = tk.BooleanVar(value=True)
        self.edge_angle_var = tk.DoubleVar(value=45.0)
        self.crease_overlay_var = tk.BooleanVar(value=False)
        self.zoom_status_var = tk.StringVar()
        self.smooth_passes_var = tk.IntVar(value=2)
        tone = self.settings.tone
        self.tone_black_point_var = tk.DoubleVar(value=tone.black_point)
        self.tone_white_point_var = tk.DoubleVar(value=tone.white_point)
        self.tone_gamma_var = tk.DoubleVar(value=tone.gamma)
        self.tone_contrast_var = tk.DoubleVar(value=tone.contrast)
        self.tone_saturation_var = tk.DoubleVar(value=tone.saturation)
        self.tone_pink_protection_var = tk.BooleanVar(
            value=tone.pink_protection
        )
        self.tone_pink_threshold_var = tk.DoubleVar(value=tone.pink_threshold)
        self.tone_smoothing_var = tk.BooleanVar(value=tone.smoothing)
        self.tone_smoothing_area_var = tk.DoubleVar(
            value=tone.smoothing_max_area_mm2
        )
        self.tone_smoothing_slack_var = tk.DoubleVar(
            value=tone.smoothing_delta_e_slack
        )
        self.illustration_mode_var = tk.StringVar(
            value=str(getattr(tone, "illustration_mode", "off"))
        )
        self.illustration_strength_var = tk.DoubleVar(
            value=100.0 * float(
                getattr(tone, "illustration_strength", 0.78)
            )
        )
        self.illustration_bands_var = tk.IntVar(
            value=int(getattr(tone, "illustration_bands", 4))
        )
        self.illustration_light_var = tk.StringVar(
            value=str(
                getattr(tone, "illustration_light", "front_left")
            )
        )
        self.mix_optimization_target_var = tk.StringVar()
        self._syncing_tone_controls = False
        self._tone_change_after: str | None = None
        self._tone_callback_revision = 0
        self._shading_reapply_revision = 0
        self.status_var = tk.StringVar(value=self.i18n.text("paint.initializing"))
        self.edit_count_var = tk.StringVar(
            value=self.i18n.text("paint.edit_count_zero")
        )
        self.sample_var = tk.StringVar(
            value=self.i18n.text(
                "paint.sample_initial", count=PALETTE_STATE_COUNT
            )
        )
        self.palette_name_var = tk.StringVar(
            value=self.i18n.text("paint.choose_color")
        )
        self.palette_usage_focus_var = tk.BooleanVar(value=False)
        self.palette_usage_summary_var = tk.StringVar(
            value=self.i18n.text("paint.palette_usage_off")
        )
        # These primitive values are read by the renderer's worker thread.
        # Never read a Tk variable there: Tcl objects are thread-affine.
        self._palette_usage_focus_enabled = False
        self._palette_usage_focus_state = int(self.paint_state_var.get())
        self._palette_usage_render_cache_key: tuple[object, ...] | None = None
        self._palette_usage_render_cache = None
        self._palette_usage_contribution_cache_key: tuple[object, ...] | None = None
        self._palette_usage_contribution_cache: tuple[float, ...] | None = None
        self.part_target_var = tk.StringVar(value=self.part_labels[0])
        self.part_name_var = tk.StringVar(value=self.part_names[0])
        self.active_part_summary_var = tk.StringVar()
        candidate_view_key = str(
            getattr(self.prepared.source, "sha256", "")
        ).strip().lower()
        self._model_view_key = (
            candidate_view_key
            if len(candidate_view_key) == 64
            and all(char in "0123456789abcdef" for char in candidate_view_key)
            else ""
        )
        stored_view_theme = self.settings.manual_view_backgrounds.get(
            self._model_view_key, "auto"
        )
        self.view_theme_mode = (
            stored_view_theme if stored_view_theme in VIEW_THEME_VALUES else "auto"
        )
        self.view_background_var = tk.StringVar()
        self.reference_visible_var = tk.BooleanVar(value=False)
        self.palette_visible_var = tk.BooleanVar(value=True)
        self.parts_tool_visible_var = tk.BooleanVar(value=True)
        self.help_tool_visible_var = tk.BooleanVar(value=True)
        self.orbit_inverted_var = tk.BooleanVar(
            value=bool(getattr(self.settings, "manual_orbit_inverted", False))
        )
        # Brush is the initial editing tool, so its controls must be the first
        # visible ribbon page as well.  Home now contains navigation/display.
        self._ribbon_selected = "brush"
        self._ribbon_expanded = True
        self._fullscreen = False
        self._palette_collapsed = False
        self._palette_place = (18, 18)
        self._palette_drag_origin: tuple[int, int, int, int] | None = None
        self._tool_restore_after: str | None = None
        self._tool_restore_verify_after: str | None = None
        self._initial_tool_windows_after: str | None = None
        self._tool_restore_attempts = 0
        self._view_appearance = resolve_view_appearance(self.view_theme_mode)
        self._part_visibility_modes = np.full(
            len(self.part_labels), PART_VISIBLE, dtype=np.uint8
        )
        self.part_visibility_var = tk.StringVar(
            value=self.i18n.text("paint.part_visible")
        )
        self.pick_transparent_var = tk.BooleanVar(value=False)
        self._pick_transparent_submitted = False
        self._matched_boundary_face_ids = np.empty(0, dtype=np.int32)
        self._unmatched_boundary_face_ids = np.empty(0, dtype=np.int32)
        self._load_boundary_diagnostics(prepared)
        self._diagnostic_enabled = bool(
            show_boundary_diagnostics
            and (
                len(self._matched_boundary_face_ids)
                or len(self._unmatched_boundary_face_ids)
            )
        )
        self.boundary_diagnostics_var = tk.BooleanVar(
            value=self._diagnostic_enabled
        )
        if self._diagnostic_enabled:
            detail = self._first_boundary_problem_detail()
            if detail:
                self.sample_var.set(detail)
        self.joint_width_var = tk.DoubleVar(
            value=float(self.settings.geometry.joint_width_mm)
        )
        self.joint_length_var = tk.DoubleVar(
            value=float(self.settings.geometry.joint_height_mm)
        )
        self.joint_depth_var = tk.DoubleVar(
            value=float(self.settings.geometry.joint_depth_mm)
        )
        self.joint_clearance_var = tk.DoubleVar(
            value=float(self.settings.geometry.joint_clearance_mm)
        )
        self.joint_availability_var = tk.StringVar()
        self._manual_joint_availability: ManualJointAvailability | None = None
        self._manual_joint_undo_state: tuple[
            PreparedGeometry,
            np.ndarray,
            dict[str, object] | None,
        ] | None = None
        raw_manual_records = dict(self.prepared.assembly or {}).get(
            "manual_joint_records", []
        )
        manual_records = (
            list(raw_manual_records)
            if isinstance(raw_manual_records, (list, tuple))
            else []
        )
        self._manual_joint_record = (
            dict(manual_records[-1]) if manual_records else None
        )

        self.camera = CameraState()
        self._update_zoom_status()
        self._render_pixels_per_unit: float | None = None
        self.target_image: Image.Image | None = None
        self.face_ids: np.ndarray | None = None
        # Decals are deliberately tied to one settled renderer face-ID frame.
        # The generation changes only when a new exact ID map is accepted; a
        # view gesture first marks any preview stale and keeps Apply disabled.
        model_height_mm = max(0.1, float(self.settings.geometry.height_mm))
        self.decal_source_var = tk.StringVar(
            value=self.i18n.text("decal.source_none")
        )
        self.decal_status_var = tk.StringVar(
            value=self.i18n.text("decal.ready")
        )
        self._decal_status_key: str | None = "decal.ready"
        self._decal_status_values: dict[str, object] = {}
        self.decal_mode_var = tk.StringVar(value="image")
        self.decal_x_var = tk.DoubleVar(value=50.0)
        self.decal_y_var = tk.DoubleVar(value=50.0)
        self.decal_width_mm_var = tk.DoubleVar(
            value=max(1.0, min(model_height_mm, model_height_mm * 0.20))
        )
        self.decal_rotation_var = tk.DoubleVar(value=0.0)
        self.decal_flip_x_var = tk.BooleanVar(value=False)
        self.decal_flip_y_var = tk.BooleanVar(value=False)
        self.decal_opacity_var = tk.DoubleVar(value=100.0)
        self.decal_overwrite_var = tk.BooleanVar(value=False)
        self._decal_image: DecalImage | None = None
        self._decal_source_path: Path | None = None
        self._decal_preview: DecalPreview | None = None
        self._decal_bake_plan: DecalBakePlan | None = None
        self._decal_planned_state_map: np.ndarray | None = None
        self._decal_base_state_map: np.ndarray | None = None
        self._decal_preview_palette_rgb: np.ndarray | None = None
        self._decal_preview_enabled_states: np.ndarray | None = None
        self._decal_preview_selected_state: int | None = None
        self._decal_preview_overwrite: bool | None = None
        self._decal_preview_camera: object | None = None
        self._decal_preview_generation: int | None = None
        self._decal_preview_stale = True
        self._decal_frame_generation = 0
        self._decal_last_exact_camera: object | None = None
        self._decal_request_serial = 0
        self._decal_cancel_event: threading.Event | None = None
        self._decal_preview_cancel_event: threading.Event | None = None
        self._decal_load_running = False
        self._decal_preview_running = False
        self._decal_preview_running_serial: int | None = None
        self._decal_preview_pending = False
        self._decal_preview_restart_after: str | None = None
        self._decal_apply_running = False
        self._decal_undo_available = False
        self._decal_last_command: object | None = None
        self._decal_auto_repreview = False
        self._decal_auto_repreview_after: str | None = None
        self._decal_syncing_controls = False
        self._visible_face_mask_cache_key: tuple[object, ...] | None = None
        self._visible_face_mask_cache: np.ndarray | None = None
        self._visible_face_mask_source: np.ndarray | None = None
        self.effective_indices: np.ndarray | None = None
        self.reference_mapping: tuple[int, int, int, int, int, int] | None = None
        self.target_mapping: tuple[int, int, int, int, int, int] | None = None
        self.canvas_images: list[ImageTk.PhotoImage] = []
        self._canvas_after: str | None = None
        self._render_after: str | None = None

        self._drag_mode: str | None = None
        self._drag_last = (0, 0)
        self._stroke_faces: list[int] = []
        self._stroke_pressures: list[float] = []
        self._stroke_last_xy = (0, 0)
        self._stroke_erase = False
        self._airbrush_started_at: float | None = None
        self._eyedropper_return_tool = "brush"
        self._crease_overlay_cache_key: tuple[object, ...] | None = None
        self._crease_overlay_cache: Image.Image | None = None
        self._lasso_points: list[tuple[int, int]] = []

        self._session: PaintSession | None = None
        self._renderer: InteractiveMeshRenderer | None = None
        self._auto_colors = None
        self._display_colors = None
        self._closing = False
        self._close_requested = False
        self._cleanup_warning: str | None = None
        self._after_close_callbacks: list[Callable[[], None]] = []
        self._job_running = False
        self._topology_change_pending = False
        self._pending_render = False
        self._render_dirty = True
        self._queued_actions: deque[tuple[str, Callable[[], object]]] = deque()
        self._work_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paint-editor")

        self._configure_style()
        self._build_ui()
        self.localizer.capture(self.window)
        self.localizer.apply()
        self._refresh_palette_buttons()
        self._draw_canvas()
        # Manual Editing is an independent workspace.  In particular, do not
        # take a global/local Tk grab here: a grabbed maximized Toplevel cannot
        # be minimized normally on Windows and also prevents its tool windows
        # from behaving like ordinary floating palettes.
        self.window.focus_set()
        self.window.after(30, self._poll_worker)
        self._submit("init", self._worker_initialize)

    def set_language(self, language: str) -> None:
        current_visibility = self._current_part_visibility_mode()
        self.i18n.set_language(language)
        title = self.i18n.text("paint.title")
        title_version = getattr(self, "_title_version", None)
        if title_version:
            title = f"{title} - {title_version}"
        self.window.title(title)
        self.localizer.apply()
        selector = getattr(self, "part_visibility_selector", None)
        if selector is not None:
            selector.configure(values=self._part_visibility_labels())
            self.part_visibility_var.set(
                self._part_visibility_label(current_visibility)
            )
        background_selector = getattr(self, "view_background_selector", None)
        if background_selector is not None:
            background_selector.configure(values=self._view_background_labels())
            self.view_background_var.set(
                self._view_background_label(self.view_theme_mode)
            )
        self._sync_active_part_identity(update_entry=False)
        self._sync_joint_guidance()
        self._update_selected_palette_label()
        if self._diagnostic_enabled:
            detail = self._first_boundary_problem_detail()
            if detail:
                self.sample_var.set(detail)
        self._refresh_shading_ribbon_text()
        self._refresh_tool_window_texts()
        self._update_zoom_status()
        self._refresh_workspace_controls()
        self._refresh_decal_language()
        self._draw_canvas()

    # ------------------------------------------------------------------
    # Decal beta: exact-frame UI/controller integration

    def _set_decal_status(self, key: str, **values: object) -> None:
        self._decal_status_key = str(key)
        self._decal_status_values = dict(values)
        self.decal_status_var.set(self.i18n.text(key, **values))

    def _set_decal_status_text(self, value: object) -> None:
        self._decal_status_key = None
        self._decal_status_values = {}
        self.decal_status_var.set(str(value))

    def _refresh_decal_language(self) -> None:
        image = getattr(self, "_decal_image", None)
        source_variable = getattr(self, "decal_source_var", None)
        if source_variable is not None:
            if image is None:
                source_variable.set(self.i18n.text("decal.source_none"))
            else:
                path = getattr(self, "_decal_source_path", None)
                name = path.name if isinstance(path, Path) else str(image.source_kind).upper()
                source_variable.set(
                    self.i18n.text(
                        "decal.source_loaded",
                        name=name,
                        width=int(image.width),
                        height=int(image.height),
                    )
                )
        mode = str(getattr(getattr(self, "decal_mode_var", None), "get", lambda: "image")())
        help_variable = getattr(self, "decal_mode_help_var", None)
        if help_variable is not None:
            help_variable.set(
                self.i18n.text(
                    "decal.selected_mode_help"
                    if mode == "selected"
                    else "decal.image_mode_help"
                )
            )
        status_key = getattr(self, "_decal_status_key", None)
        if status_key is not None:
            self.decal_status_var.set(
                self.i18n.text(
                    status_key,
                    **dict(getattr(self, "_decal_status_values", {})),
                )
            )
        self._refresh_decal_button_states()

    def _decal_exact_frame_available(self) -> bool:
        if bool(getattr(self, "_render_dirty", True)):
            return False
        if getattr(self, "_session", None) is None:
            return False
        ids = getattr(self, "face_ids", None)
        target = getattr(self, "target_image", None)
        if ids is None or target is None:
            return False
        values = np.asarray(ids)
        if values.ndim != 2 or not np.issubdtype(values.dtype, np.integer):
            return False
        if target.size != (int(values.shape[1]), int(values.shape[0])):
            return False
        pixels_per_unit = getattr(self, "_render_pixels_per_unit", None)
        try:
            if not math.isfinite(float(pixels_per_unit)) or float(pixels_per_unit) <= 0.0:
                return False
        except (TypeError, ValueError):
            return False
        pick_camera = getattr(self, "_hotfix_pick_camera", None)
        if pick_camera is not None and pick_camera != getattr(self, "camera", None):
            return False
        allowed = np.asarray(self._active_face_mask(), dtype=bool)
        visible = self._visible_face_mask_for_stroke()
        if visible is None or np.asarray(visible).shape != allowed.shape:
            return False
        return bool(np.any(allowed & np.asarray(visible, dtype=bool)))

    def _decal_exact_inputs(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not self._decal_exact_frame_available():
            raise DecalStalePreviewError(self.i18n.text("decal.view_wait"))
        ids = np.asarray(self.face_ids)
        allowed = np.asarray(self._active_face_mask(), dtype=bool)
        visible = self._visible_face_mask_for_stroke()
        if visible is None:
            raise DecalStalePreviewError(self.i18n.text("decal.view_wait"))
        visible_values = np.asarray(visible, dtype=bool)
        if not bool(np.any(allowed & visible_values)):
            raise DecalProjectionError(self.i18n.text("decal.no_visible_target"))
        return (
            np.ascontiguousarray(ids, dtype=np.int32).copy(),
            np.ascontiguousarray(allowed, dtype=bool).copy(),
            np.ascontiguousarray(visible_values, dtype=bool).copy(),
        )

    def _decal_transform(self, output_shape: tuple[int, int]) -> DecalTransform:
        try:
            x_percent = float(self.decal_x_var.get())
            y_percent = float(self.decal_y_var.get())
            width_mm = float(self.decal_width_mm_var.get())
            rotation = float(self.decal_rotation_var.get())
            opacity_percent = float(self.decal_opacity_var.get())
        except (TypeError, ValueError, tk.TclError) as exc:
            raise DecalProjectionError(self.i18n.text("decal.invalid_values")) from exc
        values = (x_percent, y_percent, width_mm, rotation, opacity_percent)
        if not all(math.isfinite(value) for value in values):
            raise DecalProjectionError(self.i18n.text("decal.invalid_values"))
        if width_mm <= 0.0:
            raise DecalProjectionError(self.i18n.text("decal.invalid_width"))
        height, width = (int(output_shape[0]), int(output_shape[1]))
        width_px = decal_width_mm_to_pixels(
            width_mm,
            float(self.settings.geometry.height_mm),
            float(self._render_pixels_per_unit),
        )
        mode = str(self.decal_mode_var.get())
        opacity = 1.0 if mode == "selected" else max(
            0.05, min(1.0, opacity_percent / 100.0)
        )
        return DecalTransform(
            center_xy=(width * x_percent / 100.0, height * y_percent / 100.0),
            width_px=width_px,
            rotation_degrees=rotation,
            flip_x=bool(self.decal_flip_x_var.get()),
            flip_y=bool(self.decal_flip_y_var.get()),
            opacity=opacity,
        )

    def _refresh_decal_button_states(self) -> None:
        loaded = getattr(self, "_decal_image", None) is not None
        loading = bool(getattr(self, "_decal_load_running", False))
        previewing = bool(getattr(self, "_decal_preview_running", False))
        applying = bool(getattr(self, "_decal_apply_running", False))
        busy = loading or previewing or applying
        exact = self._decal_exact_frame_available() if loaded and not applying else False
        planned = getattr(self, "_decal_planned_state_map", None)
        ready = bool(
            exact
            and isinstance(planned, np.ndarray)
            and bool(np.any(planned >= 0))
            and self._decal_preview_is_current()
        )
        states = (
            ("decal_import_button", "disabled" if applying or loading else "normal"),
            (
                "decal_preview_button",
                "normal" if loaded and exact and not busy else "disabled",
            ),
            (
                "decal_apply_button",
                "normal" if ready and not busy else "disabled",
            ),
            (
                "decal_cancel_button",
                "normal"
                if loaded
                and not applying
                and (
                    previewing
                    or getattr(self, "_decal_preview", None) is not None
                )
                else "disabled",
            ),
            (
                "decal_undo_button",
                "normal"
                if bool(getattr(self, "_decal_undo_available", False)) and not busy
                else "disabled",
            ),
        )
        for attribute, state in states:
            widget = getattr(self, attribute, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except (tk.TclError, AttributeError):
                    pass

    def _clear_decal_preview_artifacts(self) -> None:
        """Drop every object derived from one exact face-ID/palette frame."""

        self._decal_preview = None
        self._decal_bake_plan = None
        self._decal_planned_state_map = None
        self._decal_base_state_map = None
        self._decal_preview_palette_rgb = None
        self._decal_preview_enabled_states = None
        self._decal_preview_selected_state = None
        self._decal_preview_overwrite = None
        self._decal_preview_camera = None
        self._decal_preview_generation = None

    def _mark_decal_preview_stale(
        self,
        status_key: str = "decal.changed",
        *,
        view_change: bool = False,
    ) -> None:
        image = getattr(self, "_decal_image", None)
        had_preview = getattr(self, "_decal_preview", None) is not None
        if image is not None or had_preview or bool(
            getattr(self, "_decal_preview_running", False)
        ) or bool(getattr(self, "_decal_apply_running", False)):
            self._decal_request_serial = int(
                getattr(self, "_decal_request_serial", 0)
            ) + 1
        if view_change and (
            had_preview or bool(getattr(self, "_decal_preview_running", False))
        ):
            self._decal_auto_repreview = True
        elif not view_change:
            self._decal_auto_repreview = False
            pending = getattr(self, "_decal_auto_repreview_after", None)
            if pending is not None and hasattr(self, "window"):
                try:
                    self.window.after_cancel(pending)
                except (tk.TclError, ValueError):
                    pass
                self._decal_auto_repreview_after = None
        self._decal_preview_stale = True
        preview_cancel = getattr(self, "_decal_preview_cancel_event", None)
        if preview_cancel is not None:
            preview_cancel.set()
        # A preview and its bake plan are one immutable contract.  Never leave
        # a cached plan reachable after a transform, palette, part, paint, or
        # camera change; the placement guide itself is derived from controls.
        self._clear_decal_preview_artifacts()
        cancel_event = getattr(self, "_decal_cancel_event", None)
        if bool(getattr(self, "_decal_apply_running", False)) and cancel_event is not None:
            cancel_event.set()
        if image is not None and (had_preview or view_change):
            self._set_decal_status(status_key)
        self._refresh_decal_button_states()
        canvas = getattr(self, "canvas", None)
        if canvas is not None and (
            had_preview or str(getattr(self, "_ribbon_selected", "")) == "decal"
        ):
            try:
                self._draw_canvas()
            except tk.TclError:
                pass

    def _accept_decal_exact_frame(self, face_ids: object, camera: object) -> None:
        values = np.asarray(face_ids)
        if values.ndim != 2 or not np.issubdtype(values.dtype, np.integer):
            return
        self._decal_frame_generation = int(
            getattr(self, "_decal_frame_generation", 0)
        ) + 1
        self._decal_last_exact_camera = camera
        if getattr(self, "_decal_image", None) is not None and bool(
            getattr(self, "_decal_preview_stale", True)
        ):
            if bool(getattr(self, "_decal_auto_repreview", False)):
                self._set_decal_status("decal.previewing")
                if (
                    getattr(self, "_decal_auto_repreview_after", None) is None
                    and not bool(getattr(self, "_close_requested", False))
                    and hasattr(self, "window")
                ):
                    self._decal_auto_repreview_after = self.window.after_idle(
                        self._run_decal_auto_repreview
                    )
            else:
                self._set_decal_status("decal.view_settled")
        self._refresh_decal_button_states()

    def _run_decal_auto_repreview(self) -> None:
        self._decal_auto_repreview_after = None
        if not bool(getattr(self, "_decal_auto_repreview", False)):
            return
        if bool(getattr(self, "_close_requested", False)) or bool(
            getattr(self, "_decal_apply_running", False)
        ):
            return
        if not self._decal_exact_frame_available():
            return
        self._decal_auto_repreview = False
        self._preview_decal()

    def _on_decal_transform_trace(self, *_args: object) -> None:
        if bool(getattr(self, "_decal_syncing_controls", False)):
            return
        self._mark_decal_preview_stale("decal.changed")

    def _on_decal_transform_changed(self, _event: object = None) -> None:
        if bool(getattr(self, "_decal_syncing_controls", False)):
            return
        self._mark_decal_preview_stale("decal.changed")

    def _on_decal_mode_changed(self, *, mark_stale: bool = True) -> None:
        mode = str(self.decal_mode_var.get())
        selected = mode == "selected"
        self._decal_syncing_controls = True
        try:
            if selected:
                self.decal_opacity_var.set(100.0)
            scale = getattr(self, "decal_opacity_scale", None)
            if scale is not None:
                scale.configure(state="disabled" if selected else "normal")
        finally:
            self._decal_syncing_controls = False
        help_variable = getattr(self, "decal_mode_help_var", None)
        if help_variable is not None:
            help_variable.set(
                self.i18n.text(
                    "decal.selected_mode_help"
                    if selected
                    else "decal.image_mode_help"
                )
            )
        if mark_stale:
            self._mark_decal_preview_stale("decal.changed")

    def _on_decal_overwrite_changed(self) -> None:
        had_preview = getattr(self, "_decal_preview", None) is not None or bool(
            getattr(self, "_decal_preview_running", False)
        )
        self._mark_decal_preview_stale("decal.changed")
        if (
            had_preview
            and self._decal_exact_frame_available()
            and not bool(getattr(self, "_close_requested", False))
        ):
            self.window.after_idle(self._preview_decal)

    def _open_decal_image(self) -> None:
        if bool(getattr(self, "_decal_apply_running", False)):
            return
        value = filedialog.askopenfilename(
            parent=self.window,
            title=self.i18n.text("decal.import"),
            filetypes=(("PNG / SVG", "*.png *.svg"), ("PNG", "*.png"), ("SVG", "*.svg")),
        )
        if not value:
            return
        path = Path(value)
        self._decal_request_serial += 1
        serial = int(self._decal_request_serial)
        self._decal_load_running = True
        self._set_decal_status("decal.loading")
        self._refresh_decal_button_states()

        def work() -> dict[str, object]:
            try:
                loaded = load_decal_image(path)
            except Exception as exc:
                return {
                    "decal_load_error": exc,
                    "decal_serial": serial,
                    "decal_path": path,
                }
            return {
                "decal_loaded": loaded,
                "decal_serial": serial,
                "decal_path": path,
            }

        self._submit("decal_load", work)

    def _decal_load_error_reason(self, exc: object) -> str:
        code = str(getattr(exc, "code", ""))
        if not isinstance(exc, DecalImageError):
            return self.i18n.text("decal.error_generic", code=type(exc).__name__)
        file_codes = {"file_unreadable", "not_a_file", "empty_file"}
        unsupported_codes = {"unsupported_file_type", "content_mismatch"}
        limit_tokens = ("too_large", "limit", "dimensions", "pixel_limit")
        unsafe_svg_codes = {
            "svg_active_content",
            "svg_external_reference",
        }
        if code in file_codes:
            key = "decal.error_file"
        elif code in unsupported_codes:
            key = "decal.error_unsupported"
        elif code == "animated_png_unsupported":
            return self.i18n.text("decal.error_apng")
        elif code == "invalid_png":
            key = "decal.error_png"
        elif code in {"svg_renderer_unavailable", "svg_render_failed"}:
            key = "decal.error_svg_renderer"
        elif code in unsafe_svg_codes:
            key = "decal.error_svg_unsafe"
        elif any(token in code for token in limit_tokens):
            key = "decal.error_limit"
        elif code.startswith("invalid_svg") or code.startswith("svg_"):
            key = "decal.error_svg_invalid"
        else:
            key = "decal.error_generic"
        reason = self.i18n.text(key, code=code or "unknown")
        if code.startswith("svg_") or code.startswith("invalid_svg"):
            reason = f"{reason}\n\n{self.i18n.text('decal.svg_hint')}"
        return reason

    def _decal_projection_error_reason(self, exc: object) -> str:
        if isinstance(exc, DecalProjectionCancelled):
            return self.i18n.text("decal.cancelled")
        if isinstance(exc, DecalStalePreviewError):
            return self.i18n.text("decal.view_wait")
        if self.i18n.language == "ja":
            return str(exc)
        message = str(exc)
        if "選択色" in message:
            return self.i18n.text("decal.selected_disabled")
        if any(
            token in message
            for token in ("多すぎ", "上限", "予算", "大きすぎ", "細分化")
        ):
            return self.i18n.text("decal.projection_limit")
        return self.i18n.text("decal.projection_error")

    def _preview_decal(self) -> None:
        image = getattr(self, "_decal_image", None)
        if image is None or bool(getattr(self, "_decal_apply_running", False)):
            return
        if bool(getattr(self, "_decal_preview_running", False)):
            # One current job plus one latest-only intent. Repeated drag
            # releases never grow the editor's serial worker queue.
            self._decal_preview_pending = True
            self._set_decal_status("decal.previewing")
            return
        self._decal_auto_repreview = False
        pending_auto = getattr(self, "_decal_auto_repreview_after", None)
        if pending_auto is not None:
            try:
                self.window.after_cancel(pending_auto)
            except (tk.TclError, ValueError):
                pass
            self._decal_auto_repreview_after = None
        self._commit_active_stroke()
        try:
            ids, allowed, visible = self._decal_exact_inputs()
            transform = self._decal_transform(ids.shape)
            active_palette = self._active_palette()
            palette_rgb = np.asarray(self.palette_rgb, dtype=np.float64).copy()
            enabled = _effective_paint_enabled_states(active_palette)
            selected_state = _effective_paint_state(
                active_palette,
                int(self.paint_state_var.get()),
                palette_rgb=palette_rgb,
            )
            mode = str(self.decal_mode_var.get())
            if mode == "selected" and (
                selected_state < 0
                or selected_state >= len(enabled)
                or not bool(enabled[selected_state])
            ):
                raise DecalProjectionError(self.i18n.text("decal.selected_disabled"))
            store = getattr(self, "_hotfix_tree_store", None)
            if not isinstance(store, dict):
                raise DecalProjectionError(self.i18n.text("decal.adaptive_unavailable"))
        except (DecalProjectionError, ValueError, tk.TclError) as exc:
            reason = self._decal_projection_error_reason(exc)
            self._set_decal_status_text(reason)
            messagebox.showwarning(
                self.i18n.text("decal.preview_error_title"),
                self.i18n.text("decal.preview_error", reason=reason),
                parent=self.window,
            )
            self._refresh_decal_button_states()
            return
        self._mark_decal_preview_stale("decal.changed")
        self._decal_preview_running = True
        self._decal_preview_pending = False
        self._decal_request_serial += 1
        serial = int(self._decal_request_serial)
        self._decal_preview_running_serial = serial
        generation = int(self._decal_frame_generation)
        camera = self.camera
        level = self.level
        render_size = (int(ids.shape[1]), int(ids.shape[0]))
        overwrite = bool(self.decal_overwrite_var.get())
        cancel_event = threading.Event()
        self._decal_preview_cancel_event = cancel_event
        self._set_decal_status("decal.previewing")
        self._refresh_decal_button_states()

        def work() -> dict[str, object]:
            try:
                live_session = self._session
                if live_session is None:
                    raise DecalProjectionError(self.i18n.text("decal.view_wait"))
                if cancel_event.is_set():
                    raise DecalProjectionCancelled(
                        self.i18n.text("decal.cancelled")
                    )
                # PaintSession's topology caches are immutable after setup.
                # A shallow copy plus private copies of every mutable state
                # array gives planning one coherent snapshot without
                # rebuilding million-face adjacency on each drag release.
                session_snapshot = copy.copy(live_session)
                session_snapshot.auto_indices = np.asarray(
                    live_session.auto_indices, dtype=np.int8
                ).copy()
                session_snapshot.overrides = np.asarray(
                    live_session.overrides, dtype=np.int8
                ).copy()
                session_snapshot.allowed_face_mask = np.asarray(
                    allowed, dtype=bool
                ).copy()
                session_snapshot._stroke_before = None
                base_states = np.asarray(
                    session_snapshot.effective_indices(), dtype=np.int8
                ).copy()
                valid_ids = (ids >= 0) & (ids < len(allowed))
                snapshot_pixels = np.zeros(ids.shape, dtype=bool)
                if bool(np.any(valid_ids)):
                    picked_faces = ids[valid_ids]
                    snapshot_pixels[valid_ids] = (
                        allowed[picked_faces] & visible[picked_faces]
                    )
                visible_target_faces = set(
                    int(face) for face in np.unique(ids[snapshot_pixels])
                )
                tree_snapshot = {}
                for offset, (raw_face, node) in enumerate(tuple(store.items())):
                    if offset % 64 == 0 and cancel_event.is_set():
                        raise DecalProjectionCancelled(
                            self.i18n.text("decal.cancelled")
                        )
                    face = int(raw_face)
                    if face in visible_target_faces:
                        tree_snapshot[face] = node.clone()
                base_state_map = rasterize_existing_tree_states(
                    level,
                    tree_snapshot,
                    ids,
                    camera,
                    render_size,
                    base_states,
                    cancelled=cancel_event.is_set,
                )
                preview = build_decal_preview(
                    image,
                    transform,
                    ids,
                    allowed,
                    visible,
                    palette_rgb,
                    enabled,
                    mode=mode,
                    selected_state=selected_state if mode == "selected" else None,
                    frame_generation=generation,
                    base_face_states=base_states,
                    base_state_map=base_state_map,
                )
                plan = plan_decal_bake(
                    level,
                    session_snapshot,
                    preview,
                    camera,
                    render_size,
                    tree_snapshot,
                    protect_manual=not overwrite,
                    cancelled=cancel_event.is_set,
                )
                planned_state_map = rasterize_decal_bake_plan(
                    level,
                    preview,
                    plan,
                    camera,
                    render_size,
                    base_state_map=base_state_map,
                    base_face_states=base_states,
                    existing_trees=tree_snapshot,
                    changed_only=True,
                    cancelled=cancel_event.is_set,
                )
            except Exception as exc:
                return {
                    "decal_preview_error": exc,
                    "decal_serial": serial,
                }
            return {
                "decal_preview_result": preview,
                "decal_preview_plan": plan,
                "decal_planned_state_map": planned_state_map,
                "decal_base_state_map": base_state_map,
                "decal_palette_rgb": palette_rgb,
                "decal_enabled_states": enabled,
                "decal_selected_state": selected_state,
                "decal_preview_overwrite": overwrite,
                "decal_serial": serial,
                "decal_camera": camera,
                "decal_generation": generation,
            }

        self._submit("decal_preview", work)

    def _restart_pending_decal_preview(self) -> None:
        self._decal_preview_restart_after = None
        if not bool(getattr(self, "_decal_preview_pending", False)):
            return
        self._decal_preview_pending = False
        if bool(getattr(self, "_close_requested", False)):
            return
        if self._decal_exact_frame_available():
            self._preview_decal()

    def _schedule_pending_decal_preview(self) -> None:
        if not bool(getattr(self, "_decal_preview_pending", False)):
            return
        if getattr(self, "_decal_preview_restart_after", None) is not None:
            return
        if bool(getattr(self, "_close_requested", False)) or not hasattr(
            self, "window"
        ):
            self._decal_preview_pending = False
            return
        self._decal_preview_restart_after = self.window.after_idle(
            self._restart_pending_decal_preview
        )

    def _decal_preview_is_current(self) -> bool:
        preview = getattr(self, "_decal_preview", None)
        palette = getattr(self, "_decal_preview_palette_rgb", None)
        enabled = getattr(self, "_decal_preview_enabled_states", None)
        if (
            not isinstance(preview, DecalPreview)
            or not isinstance(getattr(self, "_decal_bake_plan", None), DecalBakePlan)
            or not isinstance(getattr(self, "_decal_planned_state_map", None), np.ndarray)
            or not isinstance(palette, np.ndarray)
            or not isinstance(enabled, np.ndarray)
            or bool(getattr(self, "_decal_preview_stale", True))
            or getattr(self, "_decal_preview_camera", None) != self.camera
            or getattr(self, "_decal_preview_generation", None)
            != getattr(self, "_decal_frame_generation", -1)
            or bool(getattr(self, "_decal_preview_overwrite", False))
            != bool(self.decal_overwrite_var.get())
            or str(preview.mode) != str(self.decal_mode_var.get())
            or not self._decal_exact_frame_available()
        ):
            return False
        try:
            if preview.transform != self._decal_transform(preview.state_map.shape):
                return False
            active_palette = self._active_palette()
            current_palette = np.asarray(self.palette_rgb, dtype=np.float64)
            current_enabled = _effective_paint_enabled_states(active_palette)
            current_state = _effective_paint_state(
                active_palette,
                int(self.paint_state_var.get()),
                palette_rgb=current_palette,
            )
        except (DecalProjectionError, TypeError, ValueError, tk.TclError):
            return False
        if preview.mode == "selected" and int(
            getattr(self, "_decal_preview_selected_state", -1)
        ) != current_state:
            return False
        return bool(
            np.array_equal(palette, current_palette)
            and np.array_equal(enabled, current_enabled)
        )

    def _apply_decal(self) -> None:
        if not self._decal_preview_is_current() or bool(
            getattr(self, "_decal_apply_running", False)
        ):
            self._mark_decal_preview_stale("decal.view_wait", view_change=True)
            return
        overwrite = bool(self.decal_overwrite_var.get())
        if overwrite and not messagebox.askyesno(
            self.i18n.text("decal.overwrite_title"),
            self.i18n.text("decal.overwrite_confirm"),
            parent=self.window,
        ):
            return
        store = getattr(self, "_hotfix_tree_store", None)
        if not isinstance(store, dict):
            messagebox.showwarning(
                self.i18n.text("decal.apply_error_title"),
                self.i18n.text("decal.adaptive_unavailable"),
                parent=self.window,
            )
            return
        if self._session is None or self.face_ids is None:
            self._mark_decal_preview_stale("decal.view_wait", view_change=True)
            return
        preview = self._decal_preview
        plan = self._decal_bake_plan
        if preview is None or not isinstance(plan, DecalBakePlan):
            self._mark_decal_preview_stale("decal.view_wait", view_change=True)
            return
        owner = getattr(self, "_hotfix_tree_owner", self.prepared)
        self._decal_cancel_event = None
        self._decal_apply_running = True
        self._set_decal_status("decal.applying")
        self.status_var.set(self.i18n.text("decal.applying"))
        self._refresh_decal_button_states()

        def work() -> dict[str, object]:
            try:
                if self._session is None:
                    raise DecalStalePreviewError(self.i18n.text("decal.view_wait"))
                result = commit_decal_bake(
                    self._session,
                    store,
                    owner,
                    plan,
                    label="デカール",
                    current_frame_generation=int(self._decal_frame_generation),
                    current_camera=self.camera,
                    render_dirty=bool(self._render_dirty),
                )
                message = self.i18n.text(
                    "decal.applied",
                    faces=len(result.changed_faces),
                    adaptive=int(result.adaptive_roots),
                    protected=int(plan.protected_faces),
                )
                if result.command is None:
                    message = self.i18n.text(
                        "decal.nothing_applied",
                        protected=int(plan.protected_faces),
                        disconnected=int(plan.disconnected_faces),
                    )
                snapshot = self._worker_refresh_after_edit(
                    message, len(result.changed_faces)
                )
                snapshot["decal_apply_result"] = result
                snapshot["decal_apply_plan"] = plan
                return snapshot
            except Exception as exc:
                return {"decal_apply_error": exc}

        self._submit("decal_apply", work)

    def _cancel_decal(self) -> None:
        preview_cancel = getattr(self, "_decal_preview_cancel_event", None)
        if bool(getattr(self, "_decal_preview_running", False)):
            if preview_cancel is not None:
                preview_cancel.set()
            self._decal_preview_pending = False
            self._set_decal_status("decal.cancelling")
            self._refresh_decal_button_states()
            return
        if bool(getattr(self, "_decal_apply_running", False)):
            # Commit is deliberately one short atomic history boundary.  It
            # cannot be partially cancelled; the resulting command is exposed
            # through the dedicated one-step Undo button instead.
            return
        self._decal_request_serial += 1
        self._decal_auto_repreview = False
        pending_auto = getattr(self, "_decal_auto_repreview_after", None)
        if pending_auto is not None:
            try:
                self.window.after_cancel(pending_auto)
            except (tk.TclError, ValueError):
                pass
            self._decal_auto_repreview_after = None
        self._decal_preview_pending = False
        pending_restart = getattr(self, "_decal_preview_restart_after", None)
        if pending_restart is not None:
            try:
                self.window.after_cancel(pending_restart)
            except (tk.TclError, ValueError):
                pass
            self._decal_preview_restart_after = None
        self._clear_decal_preview_artifacts()
        self._decal_preview_stale = True
        self._set_decal_status("decal.cancelled")
        self._refresh_decal_button_states()
        if hasattr(self, "canvas"):
            self._draw_canvas()

    def _undo_decal(self) -> None:
        expected = getattr(self, "_decal_last_command", None)
        if expected is None or self._session is None:
            self._decal_undo_available = False
            self._refresh_decal_button_states()
            return

        def work() -> dict[str, object]:
            if self._session is None:
                raise RuntimeError(self.i18n.text("decal.undo_unavailable"))
            history = getattr(self._session, "_undo", ())
            if not history or history[-1] is not expected:
                return {"decal_undo_unavailable": True}
            command = self._session.undo()
            changed = command.face_count if command else 0
            snapshot = self._worker_refresh_after_edit(
                self.i18n.text("paint.undo"), changed
            )
            snapshot["decal_undo_completed"] = True
            return snapshot

        self._submit("edit", work)

    def _target_image_with_decal_preview(
        self, image: Image.Image | None
    ) -> Image.Image | None:
        if image is None or not self._decal_preview_is_current():
            return image
        preview = self._decal_preview
        plan = getattr(self, "_decal_bake_plan", None)
        planned = getattr(self, "_decal_planned_state_map", None)
        base_states = getattr(self, "_decal_base_state_map", None)
        palette = getattr(self, "_decal_preview_palette_rgb", None)
        if (
            preview is None
            or not isinstance(plan, DecalBakePlan)
            or not isinstance(planned, np.ndarray)
            or not isinstance(base_states, np.ndarray)
            or not isinstance(palette, np.ndarray)
        ):
            return image
        try:
            return composite_planned_decal_preview(
                image,
                planned,
                preview.face_ids,
                plan,
                palette,
                base_state_map=base_states,
            )
        except DecalProjectionError:
            self._decal_preview_stale = True
            self._refresh_decal_button_states()
            return image

    def _consume_decal_payload(self, value: dict[str, object]) -> bool:
        """Consume decal-only worker payloads; return True to stop base handling."""

        if "decal_loaded" in value or "decal_load_error" in value:
            self._decal_load_running = False
            serial = int(value.get("decal_serial", -1))
            if serial != int(self._decal_request_serial):
                self._refresh_decal_button_states()
                return True
            error = value.get("decal_load_error")
            if error is not None:
                reason = self._decal_load_error_reason(error)
                self._set_decal_status_text(reason)
                messagebox.showwarning(
                    self.i18n.text("decal.loading_error_title"),
                    self.i18n.text("decal.loading_error", reason=reason),
                    parent=self.window,
                )
                self._refresh_decal_button_states()
                return True
            image = value.get("decal_loaded")
            path = value.get("decal_path")
            if not isinstance(image, DecalImage):
                self._refresh_decal_button_states()
                return True
            self._decal_image = image
            self._decal_source_path = path if isinstance(path, Path) else None
            self._clear_decal_preview_artifacts()
            self._decal_preview_stale = True
            self._refresh_decal_language()
            name = self._decal_source_path.name if self._decal_source_path else image.source_kind.upper()
            self._set_decal_status("decal.loaded", name=name)
            self._refresh_decal_button_states()
            return True

        if "decal_preview_result" in value or "decal_preview_error" in value:
            serial = int(value.get("decal_serial", -1))
            if serial != int(self._decal_request_serial):
                if getattr(self, "_decal_preview_running_serial", None) == serial:
                    self._decal_preview_running = False
                    self._decal_preview_running_serial = None
                    self._decal_preview_cancel_event = None
                self._refresh_decal_button_states()
                self._schedule_pending_decal_preview()
                return True
            if getattr(self, "_decal_preview_running_serial", None) == serial:
                self._decal_preview_running = False
                self._decal_preview_running_serial = None
                self._decal_preview_cancel_event = None
            error = value.get("decal_preview_error")
            if error is not None:
                reason = self._decal_projection_error_reason(error)
                self._clear_decal_preview_artifacts()
                self._decal_preview_stale = True
                self._set_decal_status_text(reason)
                if not isinstance(error, DecalProjectionCancelled):
                    messagebox.showwarning(
                        self.i18n.text("decal.preview_error_title"),
                        self.i18n.text("decal.preview_error", reason=reason),
                        parent=self.window,
                    )
                self._refresh_decal_button_states()
                return True
            preview = value.get("decal_preview_result")
            plan = value.get("decal_preview_plan")
            planned_state_map = value.get("decal_planned_state_map")
            base_state_map = value.get("decal_base_state_map")
            palette_rgb = value.get("decal_palette_rgb")
            enabled_states = value.get("decal_enabled_states")
            camera = value.get("decal_camera")
            generation = int(value.get("decal_generation", -1))
            if (
                not isinstance(preview, DecalPreview)
                or not isinstance(plan, DecalBakePlan)
                or not isinstance(planned_state_map, np.ndarray)
                or not isinstance(base_state_map, np.ndarray)
                or not isinstance(palette_rgb, np.ndarray)
                or not isinstance(enabled_states, np.ndarray)
                or planned_state_map.shape != preview.state_map.shape
                or base_state_map.shape != preview.state_map.shape
                or camera != self.camera
                or generation != int(self._decal_frame_generation)
                or not self._decal_exact_frame_available()
            ):
                self._clear_decal_preview_artifacts()
                self._decal_preview_stale = True
                self._set_decal_status("decal.view_wait")
                self._refresh_decal_button_states()
                return True
            if int(preview.metrics.eligible_pixels) <= 0:
                self._clear_decal_preview_artifacts()
                self._decal_preview_stale = True
                reason = self.i18n.text("decal.no_visible_target")
                self._set_decal_status_text(reason)
                messagebox.showwarning(
                    self.i18n.text("decal.preview_error_title"),
                    reason,
                    parent=self.window,
                )
                self._refresh_decal_button_states()
                return True
            self._decal_preview = preview
            self._decal_bake_plan = plan
            self._decal_planned_state_map = planned_state_map
            self._decal_base_state_map = base_state_map
            self._decal_preview_palette_rgb = palette_rgb
            self._decal_preview_enabled_states = enabled_states
            self._decal_preview_selected_state = int(
                value.get("decal_selected_state", -1)
            )
            self._decal_preview_overwrite = bool(
                value.get("decal_preview_overwrite", False)
            )
            self._decal_preview_camera = camera
            self._decal_preview_generation = generation
            self._decal_preview_stale = False
            planned_pixels = int(np.count_nonzero(planned_state_map >= 0))
            if planned_pixels:
                self._set_decal_status(
                    "decal.preview_done",
                    faces=len(plan.face_indices),
                    pixels=planned_pixels,
                    clipped=int(preview.metrics.clipped_pixels),
                    protected=int(plan.protected_faces),
                    disconnected=int(plan.disconnected_faces),
                )
            else:
                self._set_decal_status(
                    "decal.preview_nothing",
                    protected=int(plan.protected_faces),
                    disconnected=int(plan.disconnected_faces),
                )
            self._refresh_decal_button_states()
            self._draw_canvas()
            return True

        if "decal_apply_error" in value:
            self._decal_apply_running = False
            self._decal_cancel_event = None
            error = value.get("decal_apply_error")
            self._decal_preview_stale = True
            self._clear_decal_preview_artifacts()
            if isinstance(error, DecalProjectionCancelled):
                self._set_decal_status("decal.cancelled")
            else:
                reason = self._decal_projection_error_reason(error)
                self._set_decal_status_text(reason)
                messagebox.showwarning(
                    self.i18n.text("decal.apply_error_title"),
                    reason,
                    parent=self.window,
                )
            self._refresh_decal_button_states()
            self._draw_canvas()
            return True

        if "decal_undo_unavailable" in value:
            self._decal_undo_available = False
            self._decal_last_command = None
            self._set_decal_status("decal.undo_unavailable")
            self._refresh_decal_button_states()
            return True

        result = value.get("decal_apply_result")
        plan = value.get("decal_apply_plan")
        if isinstance(result, DecalBakeResult) and isinstance(plan, DecalBakePlan):
            self._decal_apply_running = False
            self._decal_cancel_event = None
            self._clear_decal_preview_artifacts()
            self._decal_preview_stale = True
            self._decal_last_command = result.command
            self._decal_undo_available = result.command is not None
            key = "decal.applied" if result.command is not None else "decal.nothing_applied"
            if key == "decal.applied":
                message = self.i18n.text(
                    key,
                    faces=len(result.changed_faces),
                    adaptive=int(result.adaptive_roots),
                    protected=int(plan.protected_faces),
                )
            else:
                message = self.i18n.text(
                    key,
                    protected=int(plan.protected_faces),
                    disconnected=int(plan.disconnected_faces),
                )
            if key == "decal.applied":
                self._set_decal_status(
                    key,
                    faces=len(result.changed_faces),
                    adaptive=int(result.adaptive_roots),
                    protected=int(plan.protected_faces),
                )
            else:
                self._set_decal_status(
                    key,
                    protected=int(plan.protected_faces),
                    disconnected=int(plan.disconnected_faces),
                )
            self._refresh_decal_button_states()
            return False

        if bool(value.get("decal_undo_completed")):
            self._decal_undo_available = False
            self._decal_last_command = None
            self._refresh_decal_button_states()
            return False
        return False

    def _shading_text(self, key: str, japanese: str, english: str) -> str:
        value = self.i18n.text(key)
        if value != key:
            return value
        return japanese if self.i18n.language == "ja" else english

    def _refresh_shading_ribbon_text(self) -> None:
        labels = (
            (
                "shading_global_title_label",
                "paint.shading_global_group",
                "1  全体の陰影・色調",
                "1  Global Shading & Tone",
            ),
            (
                "shading_illustration_title_label",
                "paint.shading_illustration_group",
                "試験  2D彩色フィルター",
                "Experimental  2D Colour Filter",
            ),
            (
                "shading_mix_title_label",
                "paint.shading_mix_group",
                "2  混色比率を陰影に合わせる",
                "2  Match Mix Ratios to Shading",
            ),
            (
                "shading_local_title_label",
                "paint.shading_local_group",
                "3  面内グラデーション補正",
                "3  In-face Gradient Correction",
            ),
        )
        for attribute, key, japanese, english in labels:
            widget = getattr(self, attribute, None)
            if widget is not None:
                widget.configure(
                    text=self._shading_text(key, japanese, english)
                )
        illustration_widgets = (
            ("illustration_mode_off_button", "tone.illustration_off"),
            ("illustration_mode_cel_button", "tone.illustration_cel"),
            ("illustration_mode_noir_button", "tone.illustration_noir"),
            ("illustration_strength_label", "tone.illustration_strength"),
            ("illustration_bands_label", "tone.illustration_bands"),
            ("illustration_light_label", "tone.illustration_light"),
            ("illustration_light_left_button", "tone.light_front_left"),
            ("illustration_light_front_button", "tone.light_front"),
            ("illustration_light_right_button", "tone.light_front_right"),
        )
        for attribute, key in illustration_widgets:
            widget = getattr(self, attribute, None)
            if widget is not None:
                widget.configure(text=self.i18n.text(key))
        self._sync_mix_optimization_target()

    def _sync_mix_optimization_target(self) -> None:
        variable = getattr(self, "mix_optimization_target_var", None)
        if variable is None or not self.part_names:
            return
        part_id = min(max(0, int(self.active_part_id)), len(self.part_names) - 1)
        name = self.part_names[part_id]
        label = self._shading_text(
            "paint.shading_mix_target",
            "対象: {name}",
            "Target: {name}",
        )
        try:
            variable.set(label.format(name=name))
        except (KeyError, ValueError):
            variable.set(f"{label} {name}")

    def _tone_settings_from_controls(self) -> ToneSettings:
        existing_tone = getattr(
            getattr(self, "settings", None), "tone", ToneSettings()
        )

        def illustration_value(
            variable_name: str,
            setting_name: str,
            default: object,
        ) -> object:
            variable = getattr(self, variable_name, None)
            if variable is not None:
                return variable.get()
            return getattr(existing_tone, setting_name, default)

        tone = ToneSettings(
            black_point=float(self.tone_black_point_var.get()),
            white_point=float(self.tone_white_point_var.get()),
            gamma=float(self.tone_gamma_var.get()),
            contrast=float(self.tone_contrast_var.get()),
            saturation=float(self.tone_saturation_var.get()),
            pink_protection=bool(self.tone_pink_protection_var.get()),
            pink_threshold=float(self.tone_pink_threshold_var.get()),
            smoothing=bool(self.tone_smoothing_var.get()),
            smoothing_max_area_mm2=float(
                self.tone_smoothing_area_var.get()
            ),
            smoothing_delta_e_slack=float(
                self.tone_smoothing_slack_var.get()
            ),
            illustration_mode=str(
                illustration_value(
                    "illustration_mode_var", "illustration_mode", "off"
                )
            ),
            illustration_strength=float(
                illustration_value(
                    "illustration_strength_var",
                    "illustration_strength",
                    0.78,
                )
            )
            / (
                100.0
                if getattr(self, "illustration_strength_var", None)
                is not None
                else 1.0
            ),
            illustration_bands=int(
                illustration_value(
                    "illustration_bands_var", "illustration_bands", 4
                )
            ),
            illustration_light=str(
                illustration_value(
                    "illustration_light_var",
                    "illustration_light",
                    "front_left",
                )
            ),
        )
        if tone.white_point <= tone.black_point + 0.005:
            raise ValueError(
                self._shading_text(
                    "paint.shading_invalid_points",
                    "白点は黒点より十分大きくしてください",
                    "White point must be sufficiently above black point",
                )
            )
        return tone

    def _set_tone_control_values(self, tone: ToneSettings) -> None:
        self._syncing_tone_controls = True
        try:
            self.tone_black_point_var.set(float(tone.black_point))
            self.tone_white_point_var.set(float(tone.white_point))
            self.tone_gamma_var.set(float(tone.gamma))
            self.tone_contrast_var.set(float(tone.contrast))
            self.tone_saturation_var.set(float(tone.saturation))
            self.tone_pink_protection_var.set(bool(tone.pink_protection))
            self.tone_pink_threshold_var.set(float(tone.pink_threshold))
            self.tone_smoothing_var.set(bool(tone.smoothing))
            self.tone_smoothing_area_var.set(
                float(tone.smoothing_max_area_mm2)
            )
            self.tone_smoothing_slack_var.set(
                float(tone.smoothing_delta_e_slack)
            )
            illustration_controls = (
                (
                    "illustration_mode_var",
                    str(getattr(tone, "illustration_mode", "off")),
                ),
                (
                    "illustration_strength_var",
                    100.0
                    * float(
                        getattr(tone, "illustration_strength", 0.78)
                    ),
                ),
                (
                    "illustration_bands_var",
                    int(getattr(tone, "illustration_bands", 4)),
                ),
                (
                    "illustration_light_var",
                    str(
                        getattr(tone, "illustration_light", "front_left")
                    ),
                ),
            )
            for attribute, value in illustration_controls:
                variable = getattr(self, attribute, None)
                if variable is not None:
                    variable.set(value)
        finally:
            self._syncing_tone_controls = False

    def _on_editor_tone_control_changed(self, _value: object = None) -> None:
        if self._syncing_tone_controls or self._closing or self._close_requested:
            return
        if self._tone_change_after is not None:
            try:
                self.window.after_cancel(self._tone_change_after)
            except tk.TclError:
                pass
        self._tone_callback_revision += 1
        revision = self._tone_callback_revision
        self._tone_change_after = self.window.after(
            TONE_CALLBACK_DEBOUNCE_MS,
            lambda: self._emit_debounced_tone_change(revision),
        )

    def _emit_debounced_tone_change(self, revision: int) -> None:
        if revision != self._tone_callback_revision:
            return
        self._tone_change_after = None
        if self._closing or self._close_requested:
            return
        try:
            tone = self._tone_settings_from_controls()
        except (ValueError, tk.TclError) as exc:
            self.status_var.set(str(exc))
            return
        callback = self.on_tone_settings_changed
        if callback is None:
            self.reapply_tone_settings(tone)
            return
        try:
            callback(replace(tone))
        except Exception as exc:
            self.status_var.set(str(exc))

    def _flush_pending_tone_change(self) -> bool:
        """Synchronously commit the visible tone controls before closing."""

        if self._tone_change_after is None:
            return True
        try:
            self.window.after_cancel(self._tone_change_after)
        except tk.TclError:
            pass
        self._tone_change_after = None
        # Any already-queued lambda now belongs to an older revision and must
        # not apply the same controls twice.
        self._tone_callback_revision += 1
        try:
            tone = self._tone_settings_from_controls()
            callback = self.on_tone_settings_changed
            if callback is None:
                self.reapply_tone_settings(tone)
            else:
                callback(replace(tone))
        except Exception as exc:
            self.status_var.set(str(exc))
            return False
        return True

    def _active_mix_optimization_key(self) -> str | None:
        if not self.part_keys:
            return None
        part_id = min(max(0, int(self.active_part_id)), len(self.part_keys) - 1)
        return str(self.part_keys[part_id])

    def _request_mix_optimization(self) -> None:
        callback = self.on_mix_optimization_requested
        if callback is None:
            self.status_var.set(
                self._shading_text(
                    "paint.shading_mix_unavailable",
                    "混色最適化は親画面から接続されていません",
                    "Mix optimization is not connected to the main window",
                )
            )
            return
        self._commit_active_stroke()
        try:
            callback(self._active_mix_optimization_key())
        except Exception as exc:
            self.status_var.set(str(exc))

    def _request_mix_optimization_undo(self) -> None:
        callback = self.on_mix_optimization_undo_requested
        if callback is None:
            return
        self._commit_active_stroke()
        try:
            callback(self._active_mix_optimization_key())
        except Exception as exc:
            self.status_var.set(str(exc))

    def _request_tone_reset(self) -> None:
        if self._tone_change_after is not None:
            try:
                self.window.after_cancel(self._tone_change_after)
            except tk.TclError:
                pass
            self._tone_change_after = None
        self._tone_callback_revision += 1
        if self.on_tone_reset_requested is not None:
            try:
                self.on_tone_reset_requested()
            except Exception as exc:
                self.status_var.set(str(exc))
            return
        tone = ToneSettings()
        if self.on_tone_settings_changed is not None:
            try:
                self.on_tone_settings_changed(replace(tone))
            except Exception as exc:
                self.status_var.set(str(exc))
            return
        self.reapply_tone_settings(tone)

    def reapply_tone_settings(
        self,
        tone: ToneSettings,
        *,
        message: str | None = None,
    ) -> None:
        """Apply a parent-approved tone snapshot and refresh the editor."""

        copied = replace(tone)
        self.settings.tone = copied
        self._set_tone_control_values(copied)
        self._queue_shading_reapply(
            message
            or self._shading_text(
                "paint.shading_tone_applied",
                "全体の陰影・色調を更新しました",
                "Updated global shading and tone",
            )
        )

    def reapply_palette_settings(
        self,
        part_key: str | None,
        palette: PaletteSettings,
        *,
        message: str | None = None,
    ) -> None:
        """Apply a parent-approved common/part palette and refresh the editor."""

        copied = _copy_palette_settings(palette)
        if part_key is None:
            self.settings.palette = copied
        else:
            clean_key = str(part_key)
            if clean_key not in self.part_keys:
                raise ValueError(f"Unknown part key: {clean_key}")
            self.settings.part_palettes[clean_key] = copied
        refresh_adaptive_routing = getattr(
            self, "_refresh_adaptive_palette_routing", None
        )
        if callable(refresh_adaptive_routing):
            refresh_adaptive_routing()
        self._refresh_palette_buttons()
        self._queue_shading_reapply(
            message
            or self._shading_text(
                "paint.shading_mix_applied",
                "混色比率を更新しました",
                "Updated mix ratios",
            )
        )

    def reapply_shading_settings(
        self,
        settings: AppSettings,
        *,
        message: str | None = None,
    ) -> None:
        """Apply only tone/palettes from a current parent settings snapshot."""

        copied = AppSettings.from_dict(settings.to_dict())
        self.settings.tone = copied.tone
        self.settings.palette = copied.palette
        self.settings.part_palettes = copied.part_palettes
        self._set_tone_control_values(self.settings.tone)
        refresh_adaptive_routing = getattr(
            self, "_refresh_adaptive_palette_routing", None
        )
        if callable(refresh_adaptive_routing):
            refresh_adaptive_routing()
        self._refresh_palette_buttons()
        self._queue_shading_reapply(
            message
            or self._shading_text(
                "paint.shading_settings_applied",
                "陰影と混色設定を更新しました",
                "Updated shading and mix settings",
            )
        )

    def _queue_shading_reapply(self, message: str) -> None:
        if self._closing or self._close_requested:
            return
        self._commit_active_stroke()
        # Enabled-state and palette changes alter both decal quantization and
        # the shade-correct preview.  Invalidate synchronously, before the
        # recolour worker starts, so Apply cannot use the old plan meanwhile.
        self._mark_decal_preview_stale("decal.changed")
        self._shading_reapply_revision += 1
        revision = self._shading_reapply_revision
        settings = AppSettings.from_dict(self.settings.to_dict())

        def work():
            if self._session is None:
                return None
            colors = recolor_level_parts(
                self.level,
                settings.geometry.height_mm,
                settings.tone,
                settings.palette,
                settings.part_palettes,
            )
            if revision != self._shading_reapply_revision:
                return None
            self._auto_colors = colors
            self._session.set_auto_indices(colors.palette_indices)
            self._display_colors = apply_palette_overrides_parts(
                self.level,
                settings.geometry.height_mm,
                settings.palette,
                settings.part_palettes,
                colors,
                self._session.overrides,
            )
            self._view_appearance = resolve_view_appearance(
                self.view_theme_mode,
                self._display_colors.target_face_rgb,
            )
            if self._renderer is not None:
                self._renderer.set_background(self._view_appearance.background)
                self._renderer.set_active_part(
                    self.active_part_id,
                    color=self._view_appearance.active_part_accent,
                )
            snapshot = self._worker_snapshot(None, message)
            snapshot["_suppress_override_notification"] = True
            snapshot["shading_reapplied"] = True
            return snapshot

        self._queued_actions = deque(
            (kind, action)
            for kind, action in self._queued_actions
            if kind != "shading_reapply"
        )
        self._submit("shading_reapply", work)

    def _view_background_labels(self) -> tuple[str, ...]:
        return tuple(
            self.i18n.text(f"paint.background_{mode}")
            for mode in VIEW_THEME_VALUES
        )

    def _view_background_label(self, mode: str) -> str:
        clean_mode = mode if mode in VIEW_THEME_VALUES else "auto"
        return self.i18n.text(f"paint.background_{clean_mode}")

    def _view_background_mode_from_label(self, label: str) -> str:
        labels = self._view_background_labels()
        try:
            return str(VIEW_THEME_VALUES[labels.index(label)])
        except ValueError:
            return "auto"

    def _active_part_face_count(self) -> int:
        part_ids = np.asarray(self.level.face_part_ids)
        if part_ids.shape != (len(self.level.faces),):
            return len(self.level.faces)
        return int(np.count_nonzero(part_ids == int(self.active_part_id)))

    def _sync_active_part_identity(self, *, update_entry: bool = True) -> None:
        if not self.part_names:
            return
        part_id = min(max(0, int(self.active_part_id)), len(self.part_names) - 1)
        name = self.part_names[part_id]
        self.active_part_summary_var.set(
            self.i18n.text(
                "paint.current_part_summary",
                index=part_id + 1,
                name=name,
                faces=self._active_part_face_count(),
            )
        )
        if update_entry:
            self.part_name_var.set(name)
        self._sync_mix_optimization_target()

    def _configure_style(self) -> None:
        style = ttk.Style(self.window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Paint.TFrame", background=BG)
        style.configure("PaintPanel.TFrame", background=PANEL)
        style.configure("Paint.TLabel", background=BG, foreground=TEXT)
        style.configure("PaintMuted.TLabel", background=BG, foreground=MUTED)
        style.configure("PaintPanel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("PaintPanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Paint.TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("Paint.TCheckbutton", background=[("active", PANEL)])
        style.configure("Paint.Tool.TRadiobutton", background=PANEL, foreground=TEXT, padding=(8, 5))
        style.map("Paint.Tool.TRadiobutton", background=[("active", PANEL_2), ("selected", "#1B668A")])
        style.configure("PaintAccent.TButton", background="#1479A8", foreground="white", padding=(10, 6))
        style.configure("PaintGood.TButton", background="#1F9D68", foreground="white", padding=(10, 6))
        # The editor can also be opened in isolation by tests and future
        # launchers, so define the same readable dropdown treatment here
        # instead of relying on the main window having configured ttk first.
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
            bordercolor="#88A6C7",
            lightcolor="#88A6C7",
            darkcolor="#88A6C7",
            selectbackground="#1B668A",
            selectforeground=combo_text,
            borderwidth=2,
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
            bordercolor=[("focus", ACCENT), ("readonly", "#88A6C7")],
            selectbackground=[("readonly", "#1B668A")],
            selectforeground=[("readonly", combo_text)],
        )
        self.window.option_add("*TCombobox*Listbox.background", combo_bg)
        self.window.option_add("*TCombobox*Listbox.foreground", combo_text)
        self.window.option_add("*TCombobox*Listbox.selectBackground", "#1B668A")
        self.window.option_add("*TCombobox*Listbox.selectForeground", combo_text)

    @staticmethod
    def _validated_diagnostic_face_ids(
        values: object, face_count: int
    ) -> np.ndarray:
        try:
            raw = np.asarray(values, dtype=np.int64).reshape(-1)
        except (TypeError, ValueError):
            return np.empty(0, dtype=np.int32)
        valid = raw[(raw >= 0) & (raw < int(face_count))]
        if not len(valid):
            return np.empty(0, dtype=np.int32)
        return np.unique(valid).astype(np.int32, copy=False)

    def _load_boundary_diagnostics(self, prepared: PreparedGeometry) -> None:
        if bool(prepared.topology.get("watertight")):
            self._matched_boundary_face_ids = np.empty(0, dtype=np.int32)
            self._unmatched_boundary_face_ids = np.empty(0, dtype=np.int32)
            return
        assembly = dict(prepared.assembly or {})
        face_count = len(prepared.final.faces)
        self._matched_boundary_face_ids = self._validated_diagnostic_face_ids(
            assembly.get("matched_boundary_face_ids", []), face_count
        )
        self._unmatched_boundary_face_ids = self._validated_diagnostic_face_ids(
            assembly.get("unmatched_boundary_face_ids", []), face_count
        )

    def _boundary_diagnostic_counts(self) -> tuple[int, int]:
        records = dict(self.prepared.assembly or {}).get(
            "boundary_diagnostics", []
        )
        if not isinstance(records, (list, tuple)):
            return 0, 0
        matched = sum(
            bool(item.get("matched"))
            for item in records
            if isinstance(item, dict)
        )
        unmatched = sum(
            not bool(item.get("matched"))
            for item in records
            if isinstance(item, dict)
        )
        return int(matched), int(unmatched)

    def _first_boundary_problem_detail(self) -> str | None:
        records = dict(self.prepared.assembly or {}).get(
            "boundary_diagnostics", []
        )
        if not isinstance(records, (list, tuple)):
            return None
        item = next(
            (
                value
                for value in records
                if isinstance(value, dict)
                and not bool(value.get("matched"))
            ),
            None,
        )
        if item is None:
            return None
        return self.i18n.text(
            "paint.boundary_problem_detail",
            part=str(item.get("part_name", "?")),
            span=float(item.get("span_mm", 0.0) or 0.0),
        )

    def _diagnostic_render_colors(self):
        result = self._display_colors
        if result is None:
            return result
        usage_enabled = bool(
            getattr(self, "_palette_usage_focus_enabled", False)
        )
        boundary_enabled = bool(self._diagnostic_enabled)
        if not usage_enabled and not boundary_enabled:
            return result
        cache_key = (
            id(result),
            id(result.target_face_rgb),
            id(result.palette_indices),
            len(result.target_face_rgb),
            usage_enabled,
            int(getattr(self, "_palette_usage_focus_state", 0)),
            int(getattr(self, "active_part_id", 0)),
            boundary_enabled,
            id(self._matched_boundary_face_ids),
            id(self._unmatched_boundary_face_ids),
        )
        if (
            cache_key
            == getattr(self, "_palette_usage_render_cache_key", None)
            and getattr(self, "_palette_usage_render_cache", None) is not None
        ):
            return self._palette_usage_render_cache
        focused = result
        if usage_enabled:
            focused = focus_palette_state(
                result,
                self.level,
                int(getattr(self, "_palette_usage_focus_state", 0)),
                part_id=int(getattr(self, "active_part_id", 0)),
            )
        if not boundary_enabled:
            self._palette_usage_render_cache_key = cache_key
            self._palette_usage_render_cache = focused
            return focused
        target = np.asarray(focused.target_face_rgb, dtype=np.float64).copy()
        if len(self._matched_boundary_face_ids):
            target[self._matched_boundary_face_ids] = (1.0, 0.64, 0.03)
        if len(self._unmatched_boundary_face_ids):
            target[self._unmatched_boundary_face_ids] = (1.0, 0.02, 0.08)
        focused = replace(focused, target_face_rgb=target)
        self._palette_usage_render_cache_key = cache_key
        self._palette_usage_render_cache = focused
        return focused

    def _on_boundary_diagnostics_changed(self) -> None:
        available = bool(
            len(self._matched_boundary_face_ids)
            or len(self._unmatched_boundary_face_ids)
        )
        self._diagnostic_enabled = bool(
            available and self.boundary_diagnostics_var.get()
        )
        self.boundary_diagnostics_var.set(self._diagnostic_enabled)
        if self._diagnostic_enabled:
            matched, unmatched = self._boundary_diagnostic_counts()
            self.status_var.set(
                self.i18n.text(
                    "paint.boundary_diagnostics_status",
                    matched=matched,
                    unmatched=unmatched,
                )
            )
            detail = self._first_boundary_problem_detail()
            if detail:
                self.sample_var.set(detail)
        elif not available:
            self.status_var.set(
                self.i18n.text("paint.boundary_diagnostics_none")
            )
        self._invalidate_palette_usage_render_cache()
        self._schedule_render(immediate=True)

    def _sync_boundary_diagnostic_controls(self) -> None:
        available = bool(
            len(self._matched_boundary_face_ids)
            or len(self._unmatched_boundary_face_ids)
        )
        if not available:
            self._diagnostic_enabled = False
            self.boundary_diagnostics_var.set(False)
        control = getattr(self, "boundary_diagnostics_check", None)
        if control is not None:
            control.configure(state="normal" if available else "disabled")

    def _build_legacy_ui(self) -> None:
        toolbar = ttk.Frame(self.window, style="PaintPanel.TFrame", padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(12, weight=1)
        tools = (
            ("回転", "orbit"),
            ("ブラシ", "brush"),
            ("塗りつぶし", "fill"),
            ("境界ならし", "smooth"),
            ("自動色へ戻す", "erase"),
        )
        for column, (label, value) in enumerate(tools):
            ttk.Radiobutton(
                toolbar,
                text=label,
                value=value,
                variable=self.tool_var,
                command=self._on_tool_changed,
                style="Paint.Tool.TRadiobutton",
            ).grid(row=0, column=column, padx=2)
        ttk.Radiobutton(
            toolbar,
            text=self.i18n.text("separate.freehand"),
            value="lasso",
            variable=self.tool_var,
            command=self._on_tool_changed,
            style="Paint.Tool.TRadiobutton",
        ).grid(row=1, column=0, columnspan=2, padx=2, pady=(5, 0), sticky="w")
        ttk.Radiobutton(
            toolbar,
            text=self.i18n.text("joint.place_tool"),
            value="joint",
            variable=self.tool_var,
            command=self._on_tool_changed,
            style="Paint.Tool.TRadiobutton",
        ).grid(row=1, column=2, columnspan=2, padx=2, pady=(5, 0), sticky="w")
        self.solidify_button = ttk.Button(
            toolbar,
            text=self.i18n.text("assembly.solidify_now"),
            command=self._request_solidify,
            state="normal" if self.on_solidify_requested is not None else "disabled",
        )
        self.solidify_button.grid(
            row=1, column=4, padx=(8, 2), pady=(5, 0), sticky="w"
        )
        self.shortcut_help_button = ttk.Button(
            toolbar,
            text=self.i18n.text("paint.shortcut_help_button"),
            command=self._show_shortcut_help,
        )
        self.shortcut_help_button.grid(
            row=1, column=5, padx=2, pady=(5, 0), sticky="w"
        )
        ttk.Label(
            toolbar,
            text=self.i18n.text("paint.double_click_hint"),
            style="PaintPanelMuted.TLabel",
        ).grid(row=1, column=6, columnspan=3, padx=(8, 0), pady=(5, 0), sticky="w")
        ttk.Separator(toolbar, orient=tk.VERTICAL).grid(row=0, column=5, sticky="ns", padx=8)
        ttk.Button(toolbar, text="元に戻す", command=self._undo).grid(row=0, column=6, padx=2)
        ttk.Button(toolbar, text="やり直す", command=self._redo).grid(row=0, column=7, padx=2)
        ttk.Button(toolbar, text="全修正を解除", command=self._clear_all).grid(row=0, column=8, padx=2)
        ttk.Button(toolbar, text="正面に戻す", command=self._reset_view).grid(row=0, column=9, padx=(10, 2))
        ttk.Label(toolbar, text="編集パーツ", style="PaintPanel.TLabel").grid(
            row=0, column=10, padx=(12, 4)
        )
        self.part_selector = ttk.Combobox(
            toolbar,
            textvariable=self.part_target_var,
            values=self.part_labels,
            state="readonly",
            width=21,
            style="HighContrast.TCombobox",
        )
        self.part_selector.grid(row=0, column=11, padx=(0, 8))
        self.part_selector.bind(
            "<<ComboboxSelected>>", self._on_editor_part_selected
        )
        ttk.Label(
            toolbar,
            text=self.i18n.text("paint.part_visibility"),
            style="PaintPanel.TLabel",
        ).grid(row=1, column=9, padx=(12, 4), pady=(5, 0), sticky="e")
        self.part_visibility_selector = ttk.Combobox(
            toolbar,
            textvariable=self.part_visibility_var,
            values=self._part_visibility_labels(),
            state="readonly" if len(self.part_labels) > 1 else "disabled",
            width=10,
            style="HighContrast.TCombobox",
        )
        self.part_visibility_selector.grid(
            row=1, column=10, columnspan=2, padx=(0, 8), pady=(5, 0), sticky="w"
        )
        self.part_visibility_selector.bind(
            "<<ComboboxSelected>>", self._on_part_visibility_selected
        )
        self.pick_transparent_check = ttk.Checkbutton(
            toolbar,
            text=self.i18n.text("paint.pick_transparent"),
            variable=self.pick_transparent_var,
            command=self._on_pick_transparent_changed,
            style="Paint.TCheckbutton",
            state="normal" if len(self.part_labels) > 1 else "disabled",
        )
        self.pick_transparent_check.grid(
            row=1, column=12, padx=(4, 8), pady=(5, 0), sticky="e"
        )
        ttk.Label(toolbar, textvariable=self.edit_count_var, style="PaintPanelMuted.TLabel").grid(
            row=0, column=12, sticky="e", padx=8
        )

        # Keep the active target unmistakable even on models with many small
        # parts.  Renaming changes only the display/export name; the immutable
        # part key remains the identity for paint, palettes and saved projects.
        active_strip = tk.Frame(
            toolbar,
            bg="#0C2B38",
            highlightbackground=ACCENT,
            highlightcolor=ACCENT,
            highlightthickness=2,
            padx=8,
            pady=5,
        )
        active_strip.grid(
            row=2,
            column=0,
            columnspan=13,
            sticky="ew",
            padx=2,
            pady=(7, 0),
        )
        active_strip.columnconfigure(1, weight=1)
        tk.Label(
            active_strip,
            text=self.i18n.text("paint.current_part"),
            bg="#0C2B38",
            fg="#9EEBFF",
            font=("Yu Gothic UI", 9, "bold"),
        ).grid(row=0, column=0, padx=(0, 8), sticky="w")
        tk.Label(
            active_strip,
            textvariable=self.active_part_summary_var,
            bg="#0C2B38",
            fg="#FFFFFF",
            font=("Yu Gothic UI", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=1, padx=(0, 12), sticky="ew")
        tk.Label(
            active_strip,
            text=self.i18n.text("paint.part_name"),
            bg="#0C2B38",
            fg="#DCEBF2",
        ).grid(row=0, column=2, padx=(0, 4), sticky="e")
        self.part_name_entry = tk.Entry(
            active_strip,
            textvariable=self.part_name_var,
            width=22,
            bg="#F7FAFD",
            fg="#101820",
            insertbackground="#101820",
            selectbackground="#1479A8",
            selectforeground="#FFFFFF",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#88A6C7",
            highlightcolor=ACCENT,
        )
        self.part_name_entry.grid(row=0, column=3, padx=(0, 4), ipady=4)
        self.part_name_entry.bind("<Return>", lambda _event: self._rename_active_part())
        ttk.Button(
            active_strip,
            text=self.i18n.text("paint.rename_part"),
            command=self._rename_active_part,
        ).grid(row=0, column=4, padx=(0, 14))
        tk.Label(
            active_strip,
            text=self.i18n.text("paint.view_background"),
            bg="#0C2B38",
            fg="#DCEBF2",
        ).grid(row=0, column=5, padx=(0, 4), sticky="e")
        self.view_background_var.set(
            self._view_background_label(self.view_theme_mode)
        )
        self.view_background_selector = ttk.Combobox(
            active_strip,
            textvariable=self.view_background_var,
            values=self._view_background_labels(),
            state="readonly",
            width=20,
            style="HighContrast.TCombobox",
        )
        self.view_background_selector.grid(row=0, column=6, padx=(0, 12))
        self.view_background_selector.bind(
            "<<ComboboxSelected>>", self._on_view_background_selected
        )
        tk.Label(
            active_strip,
            text=self.i18n.text("paint.active_outline_help"),
            bg="#0C2B38",
            fg="#9EEBFF",
        ).grid(row=0, column=7, sticky="e")
        self._sync_active_part_identity()

        options = ttk.Frame(self.window, style="PaintPanel.TFrame", padding=(10, 7))
        options.grid(row=1, column=0, sticky="ew", pady=(1, 0))
        ttk.Checkbutton(
            options,
            text="局所ツールを折り目で止める",
            variable=self.edge_guard_var,
            style="Paint.TCheckbutton",
        ).grid(row=0, column=0, padx=4)
        ttk.Label(options, text="許容角", style="PaintPanel.TLabel").grid(row=0, column=1, padx=(12, 2))
        ttk.Spinbox(options, from_=5, to=180, increment=5, width=6, textvariable=self.edge_angle_var).grid(
            row=0, column=2
        )
        ttk.Label(options, text="°", style="PaintPanelMuted.TLabel").grid(row=0, column=3, padx=(2, 12))
        self.boundary_diagnostics_check = ttk.Checkbutton(
            options,
            text=self.i18n.text("paint.boundary_diagnostics"),
            variable=self.boundary_diagnostics_var,
            command=self._on_boundary_diagnostics_changed,
            style="Paint.TCheckbutton",
            state=(
                "normal"
                if len(self._matched_boundary_face_ids)
                or len(self._unmatched_boundary_face_ids)
                else "disabled"
            ),
        )
        self.boundary_diagnostics_check.grid(
            row=1,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(5, 0),
        )

        self.joint_panel = ttk.Frame(
            self.window, style="PaintPanel.TFrame", padding=(10, 7)
        )
        self.joint_panel.grid(row=2, column=0, sticky="ew", pady=(1, 0))
        ttk.Label(
            self.joint_panel,
            text=self.i18n.text("joint.beta_label"),
            foreground=WARNING,
            background=PANEL,
        ).grid(row=0, column=0, padx=(0, 8), sticky="w")
        joint_fields = (
            ("joint.width", self.joint_width_var),
            ("joint.length", self.joint_length_var),
            ("joint.depth", self.joint_depth_var),
            ("joint.clearance", self.joint_clearance_var),
        )
        for index, (key, variable) in enumerate(joint_fields):
            column = 1 + index * 3
            ttk.Label(
                self.joint_panel,
                text=self.i18n.text(key),
                style="PaintPanel.TLabel",
            ).grid(row=0, column=column, padx=(5, 2), sticky="e")
            ttk.Spinbox(
                self.joint_panel,
                from_=0.05 if key == "joint.clearance" else 1.0,
                to=1.5 if key == "joint.clearance" else 40.0,
                increment=0.05 if key == "joint.clearance" else 0.5,
                width=6,
                textvariable=variable,
            ).grid(row=0, column=column + 1, sticky="w")
            ttk.Label(
                self.joint_panel, text="mm", style="PaintPanelMuted.TLabel"
            ).grid(row=0, column=column + 2, padx=(2, 5), sticky="w")
        self.joint_undo_button = ttk.Button(
            self.joint_panel,
            text=self.i18n.text("joint.undo"),
            command=self._undo_manual_joint,
            state="disabled",
        )
        self.joint_undo_button.grid(row=0, column=13, padx=(10, 4), sticky="e")
        ttk.Button(
            self.joint_panel,
            text=self.i18n.text("joint.how_to"),
            command=self._show_joint_guidance,
        ).grid(row=0, column=14, padx=(2, 0), sticky="e")
        ttk.Label(
            self.joint_panel,
            textvariable=self.joint_availability_var,
            foreground=WARNING,
            background=PANEL,
        ).grid(row=1, column=0, columnspan=15, sticky="w", pady=(5, 0))
        ttk.Label(
            self.joint_panel,
            text=self.i18n.text("joint.help"),
            style="PaintPanelMuted.TLabel",
        ).grid(row=2, column=0, columnspan=15, sticky="w", pady=(3, 0))
        self.joint_panel.columnconfigure(13, weight=1)
        self.joint_panel.grid_remove()
        self._sync_joint_guidance()

        palette = ttk.Frame(self.window, style="PaintPanel.TFrame", padding=(10, 7))
        palette.grid(row=3, column=0, sticky="ew", pady=(1, 0))
        ttk.Label(palette, text="塗る色", style="PaintPanel.TLabel").grid(
            row=0, column=0, rowspan=2, padx=(0, 8), sticky="w"
        )
        self.palette_buttons: list[tk.Radiobutton] = []
        columns = 17
        for state in range(PALETTE_STATE_COUNT):
            button = tk.Radiobutton(
                palette,
                text=str(state + 1),
                value=state,
                variable=self.paint_state_var,
                command=self._on_palette_state_selected,
                indicatoron=False,
                relief="flat",
                bd=1,
                width=3,
                padx=3,
                pady=3,
                selectcolor="#FFFFFF",
                highlightthickness=1,
                highlightbackground="#3A4658",
            )
            button.grid(
                row=state // columns,
                column=1 + state % columns,
                padx=1,
                pady=1,
                sticky="ew",
            )
            self.palette_buttons.append(button)
        ttk.Label(
            palette,
            textvariable=self.palette_name_var,
            style="PaintPanelMuted.TLabel",
        ).grid(row=2, column=0, columnspan=columns + 1, sticky="w", pady=(4, 0))

        self.canvas = tk.Canvas(self.window, bg="#090C11", highlightthickness=0)
        self.canvas.grid(row=4, column=0, sticky="nsew", padx=8, pady=8)
        self.window.rowconfigure(4, weight=1)
        self.window.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_left_press)
        self.canvas.bind("<Double-Button-1>", self._on_target_double_click)
        self.canvas.bind("<B1-Motion>", self._on_left_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<ButtonPress-3>", self._on_right_press)
        self.canvas.bind("<B3-Motion>", self._on_right_motion)
        self.canvas.bind("<ButtonRelease-3>", self._on_right_release)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Motion>", self._on_pointer_motion)
        self._install_shortcuts()

        footer = ttk.Frame(self.window, style="Paint.TFrame", padding=(10, 5))
        footer.grid(row=5, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="PaintMuted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(footer, textvariable=self.sample_var, style="PaintMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 0)
        )
        ttk.Button(footer, text="修正を保持して閉じる", command=self.close, style="PaintGood.TButton").grid(
            row=0, column=1, rowspan=2, padx=(10, 0)
        )

    def _build_ui(self) -> None:
        """Build the maximizable manual-editing workspace.

        Frequently used actions stay in a compact quick-access row.  The
        remaining controls live in one collapsible ribbon page at a time, while
        brush/nib/color selection is kept in a draggable palette over the 3D
        workspace.  No edit/session state is recreated when a page is changed.
        """

        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(3, weight=1)

        quick = ttk.Frame(
            self.window,
            style="PaintPanel.TFrame",
            padding=(10, 6),
        )
        quick.grid(row=0, column=0, sticky="ew")
        quick.columnconfigure(6, weight=1)
        ttk.Button(
            quick,
            text=f"{self.i18n.text('paint.undo')}  Ctrl+Z",
            command=self._undo,
        ).grid(row=0, column=0, padx=(0, 3))
        ttk.Button(
            quick,
            text=f"{self.i18n.text('paint.redo')}  Ctrl+Y",
            command=self._redo,
        ).grid(row=0, column=1, padx=3)
        ttk.Separator(quick, orient=tk.VERTICAL).grid(
            row=0, column=2, sticky="ns", padx=8
        )
        ttk.Label(
            quick,
            text=self.i18n.text("paint.edit_part"),
            style="PaintPanel.TLabel",
        ).grid(row=0, column=3, padx=(0, 4))
        self.quick_part_selector = ttk.Combobox(
            quick,
            textvariable=self.part_target_var,
            values=self.part_labels,
            state="readonly",
            width=24,
            style="HighContrast.TCombobox",
        )
        self.quick_part_selector.grid(row=0, column=4, padx=(0, 8))
        self.quick_part_selector.bind(
            "<<ComboboxSelected>>", self._on_editor_part_selected
        )
        ttk.Label(
            quick,
            textvariable=self.edit_count_var,
            style="PaintPanelMuted.TLabel",
        ).grid(row=0, column=5, padx=(0, 8))

        quick_actions = ttk.Frame(quick, style="PaintPanel.TFrame")
        quick_actions.grid(row=0, column=6, sticky="e")
        self.reference_toggle_button = ttk.Button(
            quick_actions,
            command=self._toggle_reference,
        )
        self.reference_toggle_button.grid(row=0, column=0, padx=2)
        self.palette_toggle_button = ttk.Button(
            quick_actions,
            command=self._toggle_palette,
        )
        self.palette_toggle_button.grid(row=0, column=1, padx=2)
        self.parts_tool_button = ttk.Button(
            quick_actions,
            command=self._toggle_parts_tool_window,
        )
        self.parts_tool_button.grid(row=0, column=2, padx=2)
        self.shortcut_help_button = ttk.Button(
            quick_actions,
            text=self.i18n.text("paint.quick_help"),
            command=self._show_shortcut_help,
        )
        self.shortcut_help_button.grid(row=0, column=3, padx=2)
        self.fullscreen_button = ttk.Button(
            quick_actions,
            command=self._toggle_fullscreen,
        )
        self.fullscreen_button.grid(row=0, column=4, padx=2)
        ttk.Button(
            quick_actions,
            text=self.i18n.text("paint.close"),
            command=self.close,
            style="PaintGood.TButton",
        ).grid(row=0, column=5, padx=(8, 0))

        ribbon = ttk.Frame(self.window, style="PaintPanel.TFrame")
        ribbon.grid(row=1, column=0, sticky="ew", pady=(1, 0))
        ribbon.columnconfigure(0, weight=1)
        tab_bar = tk.Frame(ribbon, bg="#111722", padx=8, pady=3)
        tab_bar.grid(row=0, column=0, sticky="ew")
        self.ribbon_tab_buttons: dict[str, tk.Button] = {}
        self._ribbon_tab_keys = {
            "home": "paint.ribbon_home",
            "brush": "paint.ribbon_brush",
            "shading": "paint.ribbon_shading",
        }
        for column, (name, key) in enumerate(self._ribbon_tab_keys.items()):
            button = tk.Button(
                tab_bar,
                text=self.i18n.text(key),
                command=lambda page=name: self._on_ribbon_tab_clicked(page),
                bg="#111722",
                fg=TEXT,
                activebackground="#24445C",
                activeforeground="#FFFFFF",
                relief=tk.FLAT,
                bd=0,
                padx=14,
                pady=5,
                font=("Yu Gothic UI", 9, "bold"),
                cursor="hand2",
            )
            button.grid(row=0, column=column, padx=1)
            self.ribbon_tab_buttons[name] = button
        ribbon_spacer_column = len(self._ribbon_tab_keys)
        tab_bar.columnconfigure(ribbon_spacer_column, weight=1)
        self.ribbon_toggle_button = ttk.Button(
            tab_bar,
            command=self._toggle_ribbon,
            width=18,
        )
        self.ribbon_toggle_button.grid(
            row=0,
            column=ribbon_spacer_column + 1,
            padx=(8, 0),
            sticky="e",
        )

        self.ribbon_body = ttk.Frame(
            ribbon,
            style="PaintPanel.TFrame",
            padding=(10, 7),
        )
        self.ribbon_body.grid(row=1, column=0, sticky="ew")
        self.ribbon_body.columnconfigure(0, weight=1)
        self.ribbon_pages: dict[str, ttk.Frame] = {}
        for name in self._ribbon_tab_keys:
            page = ttk.Frame(self.ribbon_body, style="PaintPanel.TFrame")
            page.grid(row=0, column=0, sticky="ew")
            page.grid_remove()
            self.ribbon_pages[name] = page

        home = self.ribbon_pages["home"]
        ttk.Radiobutton(
            home,
            text=self.i18n.text("paint.orbit") + "  R",
            value="orbit",
            variable=self.tool_var,
            command=lambda: self._on_tool_changed(ensure_ribbon=True),
            style="Paint.Tool.TRadiobutton",
        ).grid(row=0, column=0, padx=2, sticky="w")
        ttk.Separator(home, orient=tk.VERTICAL).grid(
            row=0, column=1, sticky="ns", padx=8
        )
        ttk.Label(
            home,
            text=self.i18n.text("paint.view_background"),
            style="PaintPanel.TLabel",
        ).grid(row=0, column=2, padx=(0, 4))
        self.view_background_var.set(
            self._view_background_label(self.view_theme_mode)
        )
        self.view_background_selector = ttk.Combobox(
            home,
            textvariable=self.view_background_var,
            values=self._view_background_labels(),
            state="readonly",
            width=21,
            style="HighContrast.TCombobox",
        )
        self.view_background_selector.grid(row=0, column=3, padx=(0, 12))
        self.view_background_selector.bind(
            "<<ComboboxSelected>>", self._on_view_background_selected
        )
        ttk.Checkbutton(
            home,
            text=self.i18n.text("paint.orbit_inverted"),
            variable=self.orbit_inverted_var,
            command=self._on_orbit_direction_changed,
            style="Paint.TCheckbutton",
        ).grid(row=0, column=4, padx=(0, 12))
        self.boundary_diagnostics_check = ttk.Checkbutton(
            self.ribbon_pages["brush"],
            text=self.i18n.text("paint.boundary_diagnostics"),
            variable=self.boundary_diagnostics_var,
            command=self._on_boundary_diagnostics_changed,
            style="Paint.TCheckbutton",
            state=(
                "normal"
                if len(self._matched_boundary_face_ids)
                or len(self._unmatched_boundary_face_ids)
                else "disabled"
            ),
        )
        self.boundary_diagnostics_check.grid(row=0, column=7, padx=(12, 0))
        self.view_reference_button = ttk.Button(
            home,
            text=self.i18n.text("paint.reference_show"),
            command=self._toggle_reference,
            state="normal" if self.reference_image is not None else "disabled",
        )
        self.view_reference_button.grid(row=0, column=6, padx=2)
        ttk.Button(
            home,
            text=self.i18n.text("paint.front"),
            command=self._reset_view,
        ).grid(row=0, column=7, padx=2)
        ttk.Separator(home, orient=tk.VERTICAL).grid(
            row=0, column=8, sticky="ns", padx=8
        )
        ttk.Label(
            home,
            text=self.i18n.text("paint.zoom"),
            style="PaintPanel.TLabel",
        ).grid(row=0, column=9, padx=(0, 3))
        ttk.Button(
            home,
            text="−",
            width=3,
            command=lambda: self._zoom_by(1.0 / MANUAL_ZOOM_STEP),
        ).grid(row=0, column=10, padx=1)
        ttk.Button(
            home,
            text="＋",
            width=3,
            command=lambda: self._zoom_by(MANUAL_ZOOM_STEP),
        ).grid(row=0, column=11, padx=1)
        ttk.Button(
            home,
            text="100%",
            command=lambda: self._set_zoom(1.0, immediate=True),
        ).grid(row=0, column=12, padx=(1, 4))
        ttk.Label(
            home,
            textvariable=self.zoom_status_var,
            style="PaintPanelMuted.TLabel",
            width=8,
            anchor="e",
        ).grid(row=0, column=13, padx=(0, 6))
        home.columnconfigure(14, weight=1)
        self.controls_hint_label = ttk.Label(
            home,
            text=self.i18n.text("paint.controls_hint"),
            style="PaintPanelMuted.TLabel",
        )
        self.controls_hint_label.grid(
            row=1,
            column=0,
            columnspan=15,
            sticky="w",
            pady=(6, 0),
        )

        brush = self.ribbon_pages["brush"]
        self.paint_options_frame = brush
        ttk.Checkbutton(
            brush,
            text=self.i18n.text("paint.edge_guard"),
            variable=self.edge_guard_var,
            style="Paint.TCheckbutton",
        ).grid(row=0, column=0, padx=(0, 8), sticky="w")
        ttk.Label(
            brush,
            text=self.i18n.text("paint.angle"),
            style="PaintPanel.TLabel",
        ).grid(row=0, column=1, padx=(4, 2))
        self.edge_angle_spinbox = ttk.Spinbox(
            brush,
            from_=5,
            to=180,
            increment=5,
            width=6,
            textvariable=self.edge_angle_var,
            command=self._on_crease_overlay_changed,
        )
        self.edge_angle_spinbox.grid(row=0, column=2)
        self.edge_angle_spinbox.bind(
            "<Return>", self._on_crease_overlay_changed, add="+"
        )
        self.edge_angle_spinbox.bind(
            "<FocusOut>", self._on_crease_overlay_changed, add="+"
        )
        ttk.Label(brush, text="°", style="PaintPanelMuted.TLabel").grid(
            row=0, column=3, padx=(2, 12)
        )
        ttk.Checkbutton(
            brush,
            text=self.i18n.text("paint.crease_overlay"),
            variable=self.crease_overlay_var,
            command=self._on_crease_overlay_changed,
            style="Paint.TCheckbutton",
        ).grid(row=0, column=4, padx=(0, 12), sticky="w")
        ttk.Label(
            brush,
            text=self.i18n.text("paint.front_visible_guard"),
            style="PaintPanelMuted.TLabel",
        ).grid(row=0, column=5, padx=(0, 12), sticky="w")
        brush.columnconfigure(6, weight=1)

        shading = self.ribbon_pages["shading"]
        shading.columnconfigure(0, weight=1)

        global_shading = ttk.Frame(shading, style="PaintPanel.TFrame")
        global_shading.grid(row=0, column=0, sticky="ew")
        global_shading.columnconfigure(6, weight=1)
        self.shading_global_title_label = tk.Label(
            global_shading,
            bg=PANEL,
            fg=ACCENT,
            font=("Yu Gothic UI", 9, "bold"),
            anchor="w",
        )
        self.shading_global_title_label.grid(
            row=0,
            column=0,
            rowspan=2,
            sticky="nw",
            padx=(0, 12),
            pady=(3, 0),
        )

        def add_tone_scale(
            parent: tk.Misc,
            column: int,
            key: str,
            variable: tk.Variable,
            minimum: float,
            maximum: float,
            resolution: float,
            *,
            length: int = 112,
        ) -> tk.Scale:
            field = ttk.Frame(parent, style="PaintPanel.TFrame")
            field.grid(row=0, column=column, sticky="w", padx=2)
            ttk.Label(
                field,
                text=self.i18n.text(key),
                style="PaintPanelMuted.TLabel",
            ).grid(row=0, column=0, sticky="w")
            scale = tk.Scale(
                field,
                from_=minimum,
                to=maximum,
                resolution=resolution,
                orient=tk.HORIZONTAL,
                variable=variable,
                command=self._on_editor_tone_control_changed,
                bg=PANEL,
                fg=TEXT,
                troughcolor="#303A49",
                activebackground=ACCENT,
                highlightthickness=0,
                length=length,
            )
            scale.grid(row=1, column=0, sticky="w")
            return scale

        self.tone_scale_widgets = (
            add_tone_scale(
                global_shading,
                1,
                "tone.black_point",
                self.tone_black_point_var,
                0.0,
                0.50,
                0.005,
            ),
            add_tone_scale(
                global_shading,
                2,
                "tone.white_point",
                self.tone_white_point_var,
                0.40,
                1.0,
                0.005,
            ),
            add_tone_scale(
                global_shading,
                3,
                "tone.gamma",
                self.tone_gamma_var,
                0.50,
                2.0,
                0.02,
            ),
            add_tone_scale(
                global_shading,
                4,
                "tone.contrast",
                self.tone_contrast_var,
                0.50,
                2.0,
                0.02,
            ),
            add_tone_scale(
                global_shading,
                5,
                "tone.saturation",
                self.tone_saturation_var,
                0.0,
                2.0,
                0.02,
            ),
        )
        ttk.Button(
            global_shading,
            text=self.i18n.text("tone.reset"),
            command=self._request_tone_reset,
        ).grid(row=0, column=6, sticky="e", padx=(10, 0), pady=(8, 0))

        tone_details = ttk.Frame(global_shading, style="PaintPanel.TFrame")
        tone_details.grid(
            row=1,
            column=1,
            columnspan=6,
            sticky="ew",
            pady=(2, 0),
        )
        tone_details.columnconfigure(7, weight=1)
        ttk.Checkbutton(
            tone_details,
            text=self.i18n.text("tone.protect_f4"),
            variable=self.tone_pink_protection_var,
            command=self._on_editor_tone_control_changed,
            style="Paint.TCheckbutton",
        ).grid(row=0, column=0, sticky="w")
        add_tone_scale(
            tone_details,
            1,
            "tone.f4_threshold",
            self.tone_pink_threshold_var,
            0.0,
            0.25,
            0.005,
            length=105,
        )
        ttk.Separator(tone_details, orient=tk.VERTICAL).grid(
            row=0, column=2, sticky="ns", padx=8
        )
        ttk.Checkbutton(
            tone_details,
            text=self.i18n.text("tone.smoothing"),
            variable=self.tone_smoothing_var,
            command=self._on_editor_tone_control_changed,
            style="Paint.TCheckbutton",
        ).grid(row=0, column=3, sticky="w")
        add_tone_scale(
            tone_details,
            4,
            "tone.smoothing_area",
            self.tone_smoothing_area_var,
            0.0,
            0.20,
            0.005,
            length=105,
        )
        add_tone_scale(
            tone_details,
            5,
            "tone.delta_e",
            self.tone_smoothing_slack_var,
            0.0,
            10.0,
            0.25,
            length=105,
        )

        ttk.Separator(shading, orient=tk.HORIZONTAL).grid(
            row=1, column=0, sticky="ew", pady=5
        )
        illustration_shading = ttk.Frame(
            shading, style="PaintPanel.TFrame"
        )
        illustration_shading.grid(row=2, column=0, sticky="ew")
        illustration_shading.columnconfigure(7, weight=1)
        self.shading_illustration_title_label = tk.Label(
            illustration_shading,
            bg=PANEL,
            fg=ACCENT,
            font=("Yu Gothic UI", 9, "bold"),
            anchor="w",
        )
        self.shading_illustration_title_label.grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        self.illustration_mode_off_button = ttk.Radiobutton(
            illustration_shading,
            variable=self.illustration_mode_var,
            value="off",
            command=self._on_editor_tone_control_changed,
            style="Paint.Tool.TRadiobutton",
        )
        self.illustration_mode_off_button.grid(row=0, column=1, padx=2)
        self.illustration_mode_cel_button = ttk.Radiobutton(
            illustration_shading,
            variable=self.illustration_mode_var,
            value="cel",
            command=self._on_editor_tone_control_changed,
            style="Paint.Tool.TRadiobutton",
        )
        self.illustration_mode_cel_button.grid(row=0, column=2, padx=2)
        self.illustration_mode_noir_button = ttk.Radiobutton(
            illustration_shading,
            variable=self.illustration_mode_var,
            value="noir",
            command=self._on_editor_tone_control_changed,
            style="Paint.Tool.TRadiobutton",
        )
        self.illustration_mode_noir_button.grid(row=0, column=3, padx=2)

        self.illustration_strength_label = ttk.Label(
            illustration_shading,
            style="PaintPanelMuted.TLabel",
        )
        self.illustration_strength_label.grid(
            row=0, column=4, padx=(12, 2), sticky="w"
        )
        tk.Scale(
            illustration_shading,
            from_=0,
            to=100,
            resolution=1,
            orient=tk.HORIZONTAL,
            variable=self.illustration_strength_var,
            command=self._on_editor_tone_control_changed,
            bg=PANEL,
            fg=TEXT,
            troughcolor="#303A49",
            activebackground=ACCENT,
            highlightthickness=0,
            length=105,
        ).grid(row=0, column=5, padx=2)
        self.illustration_bands_label = ttk.Label(
            illustration_shading,
            style="PaintPanelMuted.TLabel",
        )
        self.illustration_bands_label.grid(
            row=1, column=1, padx=(2, 2), pady=(3, 0), sticky="w"
        )
        tk.Scale(
            illustration_shading,
            from_=2,
            to=6,
            resolution=1,
            orient=tk.HORIZONTAL,
            variable=self.illustration_bands_var,
            command=self._on_editor_tone_control_changed,
            bg=PANEL,
            fg=TEXT,
            troughcolor="#303A49",
            activebackground=ACCENT,
            highlightthickness=0,
            length=80,
        ).grid(row=1, column=2, padx=2, pady=(3, 0))

        self.illustration_light_label = ttk.Label(
            illustration_shading,
            style="PaintPanelMuted.TLabel",
        )
        self.illustration_light_label.grid(
            row=1, column=3, padx=(12, 2), pady=(3, 0), sticky="w"
        )
        self.illustration_light_left_button = ttk.Radiobutton(
            illustration_shading,
            variable=self.illustration_light_var,
            value="front_left",
            command=self._on_editor_tone_control_changed,
            style="Paint.Tool.TRadiobutton",
        )
        self.illustration_light_left_button.grid(
            row=1, column=4, padx=2, pady=(3, 0)
        )
        self.illustration_light_front_button = ttk.Radiobutton(
            illustration_shading,
            variable=self.illustration_light_var,
            value="front",
            command=self._on_editor_tone_control_changed,
            style="Paint.Tool.TRadiobutton",
        )
        self.illustration_light_front_button.grid(
            row=1, column=5, padx=2, pady=(3, 0)
        )
        self.illustration_light_right_button = ttk.Radiobutton(
            illustration_shading,
            variable=self.illustration_light_var,
            value="front_right",
            command=self._on_editor_tone_control_changed,
            style="Paint.Tool.TRadiobutton",
        )
        self.illustration_light_right_button.grid(
            row=1, column=6, padx=2, pady=(3, 0)
        )

        ttk.Separator(shading, orient=tk.HORIZONTAL).grid(
            row=3, column=0, sticky="ew", pady=5
        )
        mix_shading = ttk.Frame(shading, style="PaintPanel.TFrame")
        mix_shading.grid(row=4, column=0, sticky="ew")
        mix_shading.columnconfigure(5, weight=1)
        self.shading_mix_title_label = tk.Label(
            mix_shading,
            bg=PANEL,
            fg=ACCENT,
            font=("Yu Gothic UI", 9, "bold"),
            anchor="w",
        )
        self.shading_mix_title_label.grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Label(
            mix_shading,
            textvariable=self.mix_optimization_target_var,
            style="PaintPanelMuted.TLabel",
        ).grid(row=0, column=1, sticky="w", padx=(0, 10))
        self.mix_optimization_button = ttk.Button(
            mix_shading,
            text=self.i18n.text("tone.optimize"),
            command=self._request_mix_optimization,
            style="PaintGood.TButton",
            state=(
                "normal"
                if self.on_mix_optimization_requested is not None
                else "disabled"
            ),
        )
        self.mix_optimization_button.grid(row=0, column=2, padx=3)
        self.mix_optimization_undo_button = ttk.Button(
            mix_shading,
            text=self.i18n.text("tone.undo_optimize"),
            command=self._request_mix_optimization_undo,
            state=(
                "normal"
                if self.on_mix_optimization_undo_requested is not None
                else "disabled"
            ),
        )
        self.mix_optimization_undo_button.grid(row=0, column=3, padx=3)
        ttk.Label(
            mix_shading,
            text=self.i18n.text("tone.optimize_help"),
            style="PaintPanelMuted.TLabel",
        ).grid(row=0, column=4, sticky="w", padx=(10, 0))

        ttk.Separator(shading, orient=tk.HORIZONTAL).grid(
            row=5, column=0, sticky="ew", pady=5
        )
        local_shading = ttk.Frame(shading, style="PaintPanel.TFrame")
        local_shading.grid(row=6, column=0, sticky="ew")
        local_shading.columnconfigure(1, weight=1)
        self.shading_local_title_label = tk.Label(
            local_shading,
            bg=PANEL,
            fg=ACCENT,
            font=("Yu Gothic UI", 9, "bold"),
            anchor="w",
        )
        self.shading_local_title_label.grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        # Public extension host.  smooth_paint_hotfix installs the existing
        # adaptive in-face controls here after the base editor is constructed.
        self.auto_shading_host = ttk.Frame(
            local_shading,
            style="PaintPanel.TFrame",
        )
        self.auto_shading_host.grid(row=0, column=1, sticky="ew")
        self._refresh_shading_ribbon_text()

        active_strip = tk.Frame(
            self.window,
            bg="#0C2B38",
            highlightbackground=ACCENT,
            highlightcolor=ACCENT,
            highlightthickness=1,
            padx=10,
            pady=4,
        )
        active_strip.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 0))
        active_strip.columnconfigure(1, weight=1)
        tk.Label(
            active_strip,
            text=self.i18n.text("paint.current_part"),
            bg="#0C2B38",
            fg="#9EEBFF",
            font=("Yu Gothic UI", 9, "bold"),
        ).grid(row=0, column=0, padx=(0, 8), sticky="w")
        tk.Label(
            active_strip,
            textvariable=self.active_part_summary_var,
            bg="#0C2B38",
            fg="#FFFFFF",
            font=("Yu Gothic UI", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="ew")
        tk.Label(
            active_strip,
            text=self.i18n.text("paint.active_outline_help"),
            bg="#0C2B38",
            fg="#9EEBFF",
        ).grid(row=0, column=2, padx=(12, 0), sticky="e")
        self._sync_active_part_identity()

        self.workspace = tk.Frame(self.window, bg="#090C11")
        self.workspace.grid(row=3, column=0, sticky="nsew", padx=8, pady=8)
        self.workspace.rowconfigure(0, weight=1)
        self.workspace.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self.workspace,
            bg="#090C11",
            highlightthickness=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_left_press)
        self.canvas.bind("<Double-Button-1>", self._on_target_double_click)
        self.canvas.bind("<B1-Motion>", self._on_left_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<ButtonPress-3>", self._on_right_press)
        self.canvas.bind("<B3-Motion>", self._on_right_motion)
        self.canvas.bind("<ButtonRelease-3>", self._on_right_release)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Motion>", self._on_pointer_motion)

        # These are real OS-level Toplevel palettes, not Canvas overlays.  They
        # are transient only for ownership (so minimizing Manual Editing hides
        # them); native title bars still allow movement outside the editor and
        # onto another monitor.
        self.palette_tool_window = tk.Toplevel(self.window)
        self.palette_tool_window.transient(self.window)
        self.palette_tool_window.title(
            self.i18n.text("paint.floating_palette_title")
        )
        self._initial_tool_window_layouts = compute_manual_tool_window_layouts(
            self.palette_tool_window.winfo_screenwidth(),
            self.palette_tool_window.winfo_screenheight(),
        )
        palette_geometry, palette_min_size = self._initial_tool_window_layouts[
            "palette"
        ]
        self.palette_tool_window.geometry(palette_geometry)
        self.palette_tool_window.minsize(*palette_min_size)
        self.palette_tool_window.resizable(True, True)
        self.palette_tool_window.configure(bg="#17202C")
        self.palette_tool_window.protocol("WM_DELETE_WINDOW", self._hide_palette)
        # Compatibility alias used by the brush hotfix and older tests.
        self.floating_palette = self.palette_tool_window
        palette_shell = tk.Frame(
            self.palette_tool_window,
            bg="#17202C",
            highlightbackground="#6F829A",
            highlightcolor=ACCENT,
            highlightthickness=1,
            bd=0,
        )
        palette_shell.pack(fill=tk.BOTH, expand=True)
        palette_header = tk.Frame(
            palette_shell,
            bg="#21435A",
            padx=8,
            pady=5,
        )
        palette_header.pack(fill=tk.X)
        self.palette_title_label = tk.Label(
            palette_header,
            text=self.i18n.text("paint.floating_palette_title"),
            bg="#21435A",
            fg="#FFFFFF",
            font=("Yu Gothic UI", 9, "bold"),
        )
        self.palette_title_label.pack(side=tk.LEFT)
        self.palette_drag_hint_label = tk.Label(
            palette_header,
            text=self.i18n.text("paint.tool_window_outside_hint"),
            bg="#21435A",
            fg="#BFD4E3",
        )
        self.palette_drag_hint_label.pack(side=tk.LEFT, padx=(8, 12))
        self.palette_collapse_button = tk.Button(
            palette_header,
            text="−",
            command=self._toggle_palette_collapsed,
            bg="#21435A",
            fg="#FFFFFF",
            activebackground="#2B5876",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            width=2,
        )
        self.palette_collapse_button.pack(side=tk.RIGHT)
        tk.Button(
            palette_header,
            text="×",
            command=self._hide_palette,
            bg="#21435A",
            fg="#FFFFFF",
            activebackground="#7A3040",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            width=2,
        ).pack(side=tk.RIGHT)
        palette_body = tk.Frame(palette_shell, bg=PANEL)
        self.palette_body = palette_body
        palette_body.pack(fill=tk.BOTH, expand=True)
        self.palette_scroll_canvas = tk.Canvas(
            palette_body,
            bg=PANEL,
            highlightthickness=0,
            bd=0,
        )
        self.palette_scroll_canvas.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True,
        )
        self.palette_scrollbar = ttk.Scrollbar(
            palette_body,
            orient=tk.VERTICAL,
            command=self.palette_scroll_canvas.yview,
        )
        self.palette_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.palette_scroll_canvas.configure(
            yscrollcommand=self.palette_scrollbar.set
        )
        self.floating_palette_content = ttk.Frame(
            self.palette_scroll_canvas,
            style="PaintPanel.TFrame",
            padding=(8, 7),
        )
        self._palette_scroll_window_id = self.palette_scroll_canvas.create_window(
            (0, 0),
            window=self.floating_palette_content,
            anchor="nw",
        )
        self.floating_palette_content.columnconfigure(0, weight=1)
        self.palette_manual_content = ttk.Frame(
            self.floating_palette_content,
            style="PaintPanel.TFrame",
        )
        self.palette_manual_content.grid(row=0, column=0, sticky="nsew")

        def sync_palette_scrollregion(_event=None) -> None:
            bounds = self.palette_scroll_canvas.bbox("all")
            if bounds is not None:
                self.palette_scroll_canvas.configure(scrollregion=bounds)

        def resize_palette_content(event) -> None:
            self.palette_scroll_canvas.itemconfigure(
                self._palette_scroll_window_id,
                width=max(1, int(event.width)),
            )
            summary_label = getattr(self, "palette_usage_summary_label", None)
            if summary_label is not None:
                summary_label.configure(
                    wraplength=max(280, int(event.width) - 28)
                )

        def scroll_palette(event) -> str | None:
            bounds = self.palette_scroll_canvas.bbox("all")
            if (
                bounds is None
                or bounds[3] - bounds[1]
                <= self.palette_scroll_canvas.winfo_height()
            ):
                return None
            self.palette_scroll_canvas.yview_scroll(
                -1 if int(event.delta) > 0 else 1,
                "units",
            )
            return "break"

        self.floating_palette_content.bind(
            "<Configure>", sync_palette_scrollregion
        )
        self.palette_scroll_canvas.bind(
            "<Configure>", resize_palette_content
        )
        self.palette_tool_window.bind(
            "<MouseWheel>", scroll_palette, add="+"
        )

        # The detached Brush & Color panel is the single home for anything
        # that changes paint.  The ribbon now contains guards/diagnostics only,
        # so choosing a tool never causes a surprising page switch.
        tool_grid = ttk.Frame(
            self.palette_manual_content,
            style="PaintPanel.TFrame",
        )
        tool_grid.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for column in range(4):
            tool_grid.columnconfigure(column, weight=1)
        paint_tool_groups = (
            (
                0,
                (
                    (self.i18n.text("paint.brush") + "  B", "brush"),
                    (self.i18n.text("paint.airbrush") + "  A", "airbrush"),
                    (self.i18n.text("paint.eyedropper_3d") + "  C", "eyedropper"),
                    (self.i18n.text("paint.smudge") + "  M", "smudge"),
                ),
            ),
            (
                1,
                (
                    (self.i18n.text("paint.fill") + "  F", "fill"),
                    (self.i18n.text("paint.smooth") + "  S", "smooth"),
                    (self.i18n.text("paint.erase") + "  E", "erase"),
                ),
            ),
        )
        self.paint_tool_buttons: dict[str, ttk.Radiobutton] = {}
        for tool_row, paint_tools in paint_tool_groups:
            for column, (label, value) in enumerate(paint_tools):
                button = ttk.Radiobutton(
                    tool_grid,
                    text=label,
                    value=value,
                    variable=self.tool_var,
                    command=self._on_tool_changed,
                    style="Paint.Tool.TRadiobutton",
                )
                button.grid(
                    row=tool_row,
                    column=column,
                    padx=2,
                    pady=2,
                    sticky="ew",
                )
                self.paint_tool_buttons[value] = button
        ttk.Button(
            tool_grid,
            text=self.i18n.text("paint.clear"),
            command=self._clear_all,
        ).grid(row=1, column=3, padx=2, pady=2, sticky="ew")

        radius_row = ttk.Frame(
            self.palette_manual_content,
            style="PaintPanel.TFrame",
        )
        radius_row.grid(row=1, column=0, sticky="ew")
        ttk.Label(
            radius_row,
            text=self.i18n.text("paint.brush_radius"),
            style="PaintPanel.TLabel",
        ).grid(row=0, column=0, sticky="w")
        tk.Scale(
            radius_row,
            from_=0.15,
            to=10.0,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            variable=self.brush_radius_var,
            bg=PANEL,
            fg=TEXT,
            troughcolor="#303A49",
            activebackground=ACCENT,
            highlightthickness=0,
            length=190,
        ).grid(row=0, column=1, padx=(6, 2))
        ttk.Label(radius_row, text="mm", style="PaintPanelMuted.TLabel").grid(
            row=0, column=2
        )
        self.brush_shape_host = ttk.Frame(
            self.palette_manual_content,
            style="PaintPanel.TFrame",
        )
        self.brush_shape_host.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        strength_row = ttk.Frame(
            self.palette_manual_content,
            style="PaintPanel.TFrame",
        )
        strength_row.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        strength_row.columnconfigure(1, weight=1)
        ttk.Label(
            strength_row,
            text=self.i18n.text("paint.airbrush_strength"),
            style="PaintPanelMuted.TLabel",
        ).grid(row=0, column=0, sticky="w")
        tk.Scale(
            strength_row,
            from_=5,
            to=100,
            resolution=5,
            orient=tk.HORIZONTAL,
            variable=self.airbrush_strength_var,
            bg=PANEL,
            fg=TEXT,
            troughcolor="#303A49",
            activebackground=ACCENT,
            highlightthickness=0,
            showvalue=True,
            length=150,
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Label(
            strength_row,
            text=self.i18n.text("paint.smudge_strength"),
            style="PaintPanelMuted.TLabel",
        ).grid(row=1, column=0, sticky="w")
        tk.Scale(
            strength_row,
            from_=5,
            to=100,
            resolution=5,
            orient=tk.HORIZONTAL,
            variable=self.smudge_strength_var,
            bg=PANEL,
            fg=TEXT,
            troughcolor="#303A49",
            activebackground=ACCENT,
            highlightthickness=0,
            showvalue=True,
            length=150,
        ).grid(row=1, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(
            strength_row,
            text=self.i18n.text("paint.smooth_passes"),
            style="PaintPanelMuted.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(3, 0))
        ttk.Spinbox(
            strength_row,
            from_=1,
            to=10,
            width=5,
            textvariable=self.smooth_passes_var,
        ).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(3, 0))

        palette_grid = ttk.Frame(
            self.palette_manual_content,
            style="PaintPanel.TFrame",
        )
        palette_grid.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.manual_palette_grid = palette_grid
        for column in range(6):
            palette_grid.columnconfigure(column, weight=1 if column else 0)
        ttk.Label(
            palette_grid,
            text=self.i18n.text("paint.paint_color"),
            style="PaintPanel.TLabel",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 3))
        self.manual_palette_state_count_combo = ttk.Combobox(
            palette_grid,
            textvariable=self.manual_palette_state_count_var,
            values=SUPPORTED_PALETTE_STATE_COUNTS,
            state="readonly",
            width=5,
            style="HighContrast.TCombobox",
        )
        self.manual_palette_state_count_combo.grid(
            row=0, column=4, columnspan=2, sticky="e", pady=(0, 3)
        )
        self.manual_palette_state_count_combo.bind(
            "<<ComboboxSelected>>", self._on_manual_palette_state_count_changed
        )
        self.palette_buttons: list[tk.Radiobutton] = []
        for state in range(PALETTE_STATE_COUNT):
            button = tk.Radiobutton(
                palette_grid,
                text=str(state + 1),
                value=state,
                variable=self.paint_state_var,
                command=self._update_selected_palette_label,
                indicatoron=False,
                relief=tk.FLAT,
                bd=1,
                width=4,
                padx=4,
                pady=4,
                selectcolor="#FFFFFF",
                highlightthickness=1,
                highlightbackground="#3A4658",
            )
            button.grid(
                row=1 + state // 4,
                column=state % 4,
                padx=2,
                pady=2,
                sticky="ew",
            )
            self.palette_buttons.append(button)
        self.manual_palette_physical_label = ttk.Label(
            palette_grid,
            text="F1–F4",
            style="PaintPanelMuted.TLabel",
            width=7,
        )
        self.manual_palette_family_labels: dict[str, ttk.Label] = {}
        for left, right in PAIR_INDICES:
            pair_name = f"F{left + 1}+F{right + 1}"
            self.manual_palette_family_labels[pair_name] = ttk.Label(
                palette_grid,
                text=pair_name,
                style="PaintPanelMuted.TLabel",
                width=7,
            )
        self.palette_name_label = ttk.Label(
            self.palette_manual_content,
            textvariable=self.palette_name_var,
            style="PaintPanelMuted.TLabel",
            wraplength=300,
        )
        self.palette_name_label.grid(row=10, column=0, sticky="w", pady=(5, 0))
        ttk.Separator(
            self.palette_manual_content,
            orient=tk.HORIZONTAL,
        ).grid(row=11, column=0, sticky="ew", pady=(8, 5))
        self.palette_usage_focus_check = ttk.Checkbutton(
            self.palette_manual_content,
            text=self.i18n.text("paint.palette_usage_focus"),
            variable=self.palette_usage_focus_var,
            command=self._on_palette_usage_focus_changed,
            style="Paint.TCheckbutton",
        )
        self.palette_usage_focus_check.grid(row=12, column=0, sticky="w")
        self.palette_usage_summary_label = ttk.Label(
            self.palette_manual_content,
            textvariable=self.palette_usage_summary_var,
            style="PaintPanelMuted.TLabel",
            wraplength=360,
            justify=tk.LEFT,
        )
        self.palette_usage_summary_label.grid(
            row=13,
            column=0,
            sticky="ew",
            pady=(4, 0),
        )
        self.palette_manual_content.columnconfigure(0, weight=1)
        self._build_parts_tool_window()
        self._build_help_tool_window()
        self.window.bind("<Unmap>", self._on_editor_unmapped, add="+")
        self.window.bind("<Map>", self._on_editor_mapped, add="+")
        self.window.bind("<Destroy>", self._on_editor_destroyed, add="+")
        self._initial_tool_windows_after = self.window.after_idle(
            self._show_initial_tool_windows
        )

        footer = ttk.Frame(self.window, style="Paint.TFrame", padding=(10, 4))
        footer.grid(row=4, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(
            footer,
            textvariable=self.status_var,
            style="PaintMuted.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            footer,
            textvariable=self.sample_var,
            style="PaintMuted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(1, 0))
        ttk.Label(
            footer,
            text=self.i18n.text("paint.ribbon_hint"),
            style="PaintMuted.TLabel",
        ).grid(row=0, column=1, rowspan=2, padx=(12, 0), sticky="e")

        self._install_shortcuts()
        self.window.bind("<Escape>", self._exit_fullscreen, add="+")
        self._select_ribbon("brush", ensure_expanded=False)
        self._refresh_workspace_controls()

    def _build_decal_ribbon(self, page: ttk.Frame) -> None:
        """Build the compact, in-ribbon Decal beta workspace."""

        page.columnconfigure(0, weight=1)
        source_row = ttk.Frame(page, style="PaintPanel.TFrame")
        source_row.grid(row=0, column=0, sticky="ew")
        source_row.columnconfigure(1, weight=1)

        self.decal_import_button = ttk.Button(
            source_row,
            text=self.i18n.text("decal.import"),
            command=self._open_decal_image,
            style="PaintGood.TButton",
        )
        self.decal_import_button.grid(row=0, column=0, padx=(0, 6), sticky="w")
        ttk.Label(
            source_row,
            textvariable=self.decal_source_var,
            style="PaintPanelMuted.TLabel",
            width=24,
            anchor="w",
        ).grid(row=0, column=1, padx=(0, 8), sticky="ew")
        ttk.Separator(source_row, orient=tk.VERTICAL).grid(
            row=0, column=2, sticky="ns", padx=7
        )
        ttk.Label(
            source_row,
            text=self.i18n.text("decal.mode"),
            style="PaintPanel.TLabel",
        ).grid(row=0, column=3, padx=(0, 3), sticky="w")
        ttk.Radiobutton(
            source_row,
            text=self.i18n.text("decal.mode_image"),
            value="image",
            variable=self.decal_mode_var,
            command=self._on_decal_mode_changed,
            style="Paint.Tool.TRadiobutton",
        ).grid(row=0, column=4, padx=2, sticky="w")
        ttk.Radiobutton(
            source_row,
            text=self.i18n.text("decal.mode_selected"),
            value="selected",
            variable=self.decal_mode_var,
            command=self._on_decal_mode_changed,
            style="Paint.Tool.TRadiobutton",
        ).grid(row=0, column=5, padx=2, sticky="w")

        # Keep the source/mode selector and the four commands in independent
        # rows.  In English the combined row exceeded the supported 1080 px
        # client width and could hide Apply/Cancel even though the canvas had
        # plenty of vertical room.
        action_row = ttk.Frame(page, style="PaintPanel.TFrame")
        action_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        action_row.columnconfigure(0, weight=1)
        ttk.Label(
            action_row,
            textvariable=self.decal_status_var,
            style="PaintPanelMuted.TLabel",
            anchor="w",
        ).grid(
            row=0,
            column=0,
            padx=(0, 8),
            sticky="ew",
        )

        actions = ttk.Frame(action_row, style="PaintPanel.TFrame")
        actions.grid(row=0, column=1, sticky="e")
        self.decal_preview_button = ttk.Button(
            actions,
            text=self.i18n.text("decal.preview"),
            command=self._preview_decal,
            state="disabled",
        )
        self.decal_preview_button.grid(row=0, column=0, padx=2)
        self.decal_apply_button = ttk.Button(
            actions,
            text=self.i18n.text("decal.apply"),
            command=self._apply_decal,
            style="PaintGood.TButton",
            state="disabled",
        )
        self.decal_apply_button.grid(row=0, column=1, padx=2)
        self.decal_cancel_button = ttk.Button(
            actions,
            text=self.i18n.text("decal.cancel"),
            command=self._cancel_decal,
            state="disabled",
        )
        self.decal_cancel_button.grid(row=0, column=2, padx=2)
        self.decal_undo_button = ttk.Button(
            actions,
            text=self.i18n.text("decal.undo"),
            command=self._undo_decal,
            state="disabled",
        )
        self.decal_undo_button.grid(row=0, column=3, padx=(2, 0))

        placement = ttk.Frame(page, style="PaintPanel.TFrame")
        placement.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        placement.columnconfigure(8, weight=1)

        def add_spin(
            column: int,
            key: str,
            variable: tk.Variable,
            minimum: float,
            maximum: float,
            increment: float,
        ) -> ttk.Spinbox:
            ttk.Label(
                placement,
                text=self.i18n.text(key),
                style="PaintPanelMuted.TLabel",
            ).grid(
                row=0,
                column=column * 2,
                padx=(8 if column else 0, 3),
                sticky="e",
            )
            spin = ttk.Spinbox(
                placement,
                from_=minimum,
                to=maximum,
                increment=increment,
                width=6,
                textvariable=variable,
            )
            spin.grid(row=0, column=column * 2 + 1, sticky="w")
            spin.bind("<Return>", self._on_decal_transform_changed, add="+")
            spin.bind("<FocusOut>", self._on_decal_transform_changed, add="+")
            return spin

        self.decal_x_spinbox = add_spin(
            0, "decal.x_unit", self.decal_x_var, -100.0, 200.0, 1.0
        )
        self.decal_y_spinbox = add_spin(
            1, "decal.y_unit", self.decal_y_var, -100.0, 200.0, 1.0
        )
        maximum_width = max(1.0, float(self.settings.geometry.height_mm) * 5.0)
        self.decal_width_spinbox = add_spin(
            2,
            "decal.size_unit",
            self.decal_width_mm_var,
            0.1,
            maximum_width,
            0.5,
        )
        self.decal_rotation_spinbox = add_spin(
            3,
            "decal.rotation_unit",
            self.decal_rotation_var,
            -360.0,
            360.0,
            1.0,
        )

        appearance = ttk.Frame(page, style="PaintPanel.TFrame")
        appearance.grid(row=3, column=0, sticky="ew", pady=(3, 0))
        appearance.columnconfigure(6, weight=1)
        ttk.Checkbutton(
            appearance,
            text=self.i18n.text("decal.flip_x"),
            variable=self.decal_flip_x_var,
            style="Paint.TCheckbutton",
        ).grid(row=0, column=0, padx=(0, 7), sticky="w")
        ttk.Checkbutton(
            appearance,
            text=self.i18n.text("decal.flip_y"),
            variable=self.decal_flip_y_var,
            style="Paint.TCheckbutton",
        ).grid(row=0, column=1, padx=(0, 7), sticky="w")
        ttk.Separator(appearance, orient=tk.VERTICAL).grid(
            row=0, column=2, sticky="ns", padx=7
        )
        ttk.Label(
            appearance,
            text=self.i18n.text("decal.opacity"),
            style="PaintPanelMuted.TLabel",
        ).grid(row=0, column=3, padx=(0, 2), sticky="e")
        self.decal_opacity_scale = tk.Scale(
            appearance,
            from_=5,
            to=100,
            resolution=1,
            orient=tk.HORIZONTAL,
            variable=self.decal_opacity_var,
            command=self._on_decal_transform_changed,
            bg=PANEL,
            fg=TEXT,
            troughcolor="#303A49",
            activebackground=ACCENT,
            highlightthickness=0,
            length=112,
            width=10,
            showvalue=True,
        )
        self.decal_opacity_scale.grid(
            row=0, column=4, padx=(0, 2), sticky="w"
        )
        ttk.Label(
            appearance,
            text=self.i18n.text("decal.opacity_image_only"),
            style="PaintPanelMuted.TLabel",
        ).grid(
            row=0, column=5, padx=(0, 4), sticky="w"
        )

        guidance = ttk.Frame(page, style="PaintPanel.TFrame")
        guidance.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        guidance.columnconfigure(1, weight=1)
        self.decal_overwrite_check = ttk.Checkbutton(
            guidance,
            text=self.i18n.text("decal.overwrite"),
            variable=self.decal_overwrite_var,
            command=self._on_decal_overwrite_changed,
            style="Paint.TCheckbutton",
        )
        self.decal_overwrite_check.grid(
            row=0, column=0, padx=(0, 5), sticky="w"
        )
        ttk.Label(
            guidance,
            text=self.i18n.text("decal.protect_help"),
            style="PaintPanelMuted.TLabel",
        ).grid(row=0, column=1, padx=(0, 10), sticky="w")
        self.decal_mode_help_var = tk.StringVar(
            value=self.i18n.text("decal.image_mode_help")
        )
        self.decal_mode_help_label = ttk.Label(
            guidance,
            textvariable=self.decal_mode_help_var,
            style="PaintPanelMuted.TLabel",
            anchor="w",
            justify=tk.LEFT,
            wraplength=980,
        )
        self.decal_mode_help_label.grid(
            row=1,
            column=0,
            columnspan=2,
            pady=(3, 0),
            sticky="ew",
        )
        self.decal_beta_help_label = ttk.Label(
            guidance,
            text=self.i18n.text("decal.beta_help"),
            foreground=WARNING,
            background=PANEL,
            anchor="w",
            justify=tk.LEFT,
            wraplength=980,
        )
        self.decal_beta_help_label.grid(
            row=2,
            column=0,
            columnspan=2,
            pady=(3, 0),
            sticky="ew",
        )

        # Text-entry changes and flips invalidate only the placement preview;
        # the exact renderer face map remains valid until the camera moves.
        for variable in (
            self.decal_x_var,
            self.decal_y_var,
            self.decal_width_mm_var,
            self.decal_rotation_var,
            self.decal_flip_x_var,
            self.decal_flip_y_var,
        ):
            variable.trace_add("write", self._on_decal_transform_trace)
        self._on_decal_mode_changed(mark_stale=False)

    def _build_parts_tool_window(self) -> None:
        """Create the modeless Parts palette as an ordinary OS window."""

        self.parts_tool_window = tk.Toplevel(self.window)
        self.parts_tool_window.transient(self.window)
        self.parts_tool_window.title(self.i18n.text("paint.parts_tool_title"))
        parts_geometry, parts_minimum = self._initial_tool_window_layouts["parts"]
        self.parts_tool_window.geometry(parts_geometry)
        self.parts_tool_window.minsize(*parts_minimum)
        self.parts_tool_window.resizable(True, True)
        self.parts_tool_window.configure(bg=PANEL)
        self.parts_tool_window.protocol(
            "WM_DELETE_WINDOW", self._hide_parts_tool_window
        )
        self.parts_tool_window.bind(
            "<Escape>", lambda _event: self._hide_parts_tool_window()
        )

        shell = ttk.Frame(
            self.parts_tool_window,
            style="PaintPanel.TFrame",
            padding=(12, 10),
        )
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(1, weight=1)
        self.parts_tool_title_label = ttk.Label(
            shell,
            text=self.i18n.text("paint.parts_tool_title"),
            style="PaintPanel.TLabel",
            font=("Yu Gothic UI", 11, "bold"),
        )
        self.parts_tool_title_label.grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.parts_tool_outside_hint_label = ttk.Label(
            shell,
            text=self.i18n.text("paint.tool_window_outside_hint"),
            style="PaintPanelMuted.TLabel",
        )
        self.parts_tool_outside_hint_label.grid(
            row=0, column=2, sticky="e", pady=(0, 8)
        )

        ttk.Label(
            shell,
            text=self.i18n.text("paint.edit_part"),
            style="PaintPanel.TLabel",
        ).grid(row=1, column=0, padx=(0, 6), sticky="w")
        self.part_selector = ttk.Combobox(
            shell,
            textvariable=self.part_target_var,
            values=self.part_labels,
            state="readonly",
            width=30,
            style="HighContrast.TCombobox",
        )
        self.part_selector.grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=2
        )
        self.part_selector.bind(
            "<<ComboboxSelected>>", self._on_editor_part_selected
        )

        ttk.Label(
            shell,
            text=self.i18n.text("paint.part_name"),
            style="PaintPanel.TLabel",
        ).grid(row=2, column=0, padx=(0, 6), sticky="w", pady=(5, 2))
        self.part_name_entry = tk.Entry(
            shell,
            textvariable=self.part_name_var,
            bg="#F7FAFD",
            fg="#101820",
            insertbackground="#101820",
            selectbackground="#1479A8",
            selectforeground="#FFFFFF",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#88A6C7",
            highlightcolor=ACCENT,
        )
        self.part_name_entry.grid(row=2, column=1, sticky="ew", pady=(5, 2), ipady=4)
        self.part_name_entry.bind(
            "<Return>", lambda _event: self._rename_active_part()
        )
        self.part_rename_button = ttk.Button(
            shell,
            text=self.i18n.text("paint.rename_part"),
            command=self._rename_active_part,
        )
        self.part_rename_button.grid(row=2, column=2, padx=(6, 0), pady=(5, 2))

        ttk.Separator(shell, orient=tk.HORIZONTAL).grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=8
        )
        ttk.Label(
            shell,
            text=self.i18n.text("paint.part_visibility"),
            style="PaintPanel.TLabel",
        ).grid(row=4, column=0, padx=(0, 6), sticky="w")
        self.part_visibility_selector = ttk.Combobox(
            shell,
            textvariable=self.part_visibility_var,
            values=self._part_visibility_labels(),
            state="readonly" if len(self.part_labels) > 1 else "disabled",
            width=14,
            style="HighContrast.TCombobox",
        )
        self.part_visibility_selector.grid(row=4, column=1, sticky="w")
        self.part_visibility_selector.bind(
            "<<ComboboxSelected>>", self._on_part_visibility_selected
        )
        self.pick_transparent_check = ttk.Checkbutton(
            shell,
            text=self.i18n.text("paint.pick_transparent"),
            variable=self.pick_transparent_var,
            command=self._on_pick_transparent_changed,
            style="Paint.TCheckbutton",
            state="normal" if len(self.part_labels) > 1 else "disabled",
        )
        self.pick_transparent_check.grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(7, 2)
        )

        bulk = ttk.Frame(shell, style="PaintPanel.TFrame")
        bulk.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        for column in range(3):
            bulk.columnconfigure(column, weight=1)
        self.parts_only_selected_button = ttk.Button(
            bulk,
            text=self.i18n.text("paint.only_selected_visible"),
            command=self.show_only_active_part,
        )
        self.parts_only_selected_button.grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        self.parts_others_transparent_button = ttk.Button(
            bulk,
            text=self.i18n.text("paint.only_selected_transparent"),
            command=self.make_other_parts_transparent,
        )
        self.parts_others_transparent_button.grid(
            row=0, column=1, sticky="ew", padx=3
        )
        self.parts_show_all_button = ttk.Button(
            bulk,
            text=self.i18n.text("paint.show_all_parts"),
            command=self.show_all_parts,
        )
        self.parts_show_all_button.grid(
            row=0, column=2, sticky="ew", padx=(3, 0)
        )
        self.parts_double_click_help_label = ttk.Label(
            shell,
            text=self.i18n.text("paint.double_click_help"),
            style="PaintPanelMuted.TLabel",
            wraplength=430,
        )
        self.parts_double_click_help_label.grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )
        self.parts_tool_window.withdraw()

    def _build_help_tool_window(self) -> None:
        """Create the nonmodal operation/shortcut guide."""

        self.help_tool_window = tk.Toplevel(self.window)
        self.help_tool_window.transient(self.window)
        self.help_tool_window.title(
            self.i18n.text("paint.shortcut_help_title")
        )
        help_geometry, help_minimum = self._initial_tool_window_layouts["help"]
        self.help_tool_window.geometry(help_geometry)
        self.help_tool_window.minsize(*help_minimum)
        self.help_tool_window.resizable(True, True)
        self.help_tool_window.configure(bg=PANEL)
        self.help_tool_window.protocol(
            "WM_DELETE_WINDOW", self._hide_help_tool_window
        )
        self.help_tool_window.bind(
            "<Escape>", lambda _event: self._hide_help_tool_window()
        )
        shell = ttk.Frame(
            self.help_tool_window,
            style="PaintPanel.TFrame",
            padding=(12, 10),
        )
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(4, weight=1)
        self.help_title_label = ttk.Label(
            shell,
            text=self.i18n.text("paint.shortcut_help_button"),
            style="PaintPanel.TLabel",
            font=("Yu Gothic UI", 11, "bold"),
        )
        self.help_title_label.grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.help_outside_hint_label = ttk.Label(
            shell,
            text=self.i18n.text("paint.tool_window_outside_hint"),
            style="PaintPanelMuted.TLabel",
        )
        self.help_outside_hint_label.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )
        self.help_intro_label = ttk.Label(
            shell,
            text=self.i18n.text("paint.shortcut_help_intro"),
            style="PaintPanelMuted.TLabel",
            wraplength=320,
        )
        self.help_intro_label.grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(7, 2)
        )
        self.help_controls_hint_label = ttk.Label(
            shell,
            text=self.i18n.text("paint.controls_hint"),
            style="PaintPanel.TLabel",
            wraplength=320,
        )
        self.help_controls_hint_label.grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(5, 8)
        )
        self.help_text = tk.Text(
            shell,
            bg="#0D1420",
            fg="#E8EDF2",
            insertbackground="#FFFFFF",
            selectbackground="#1B668A",
            selectforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=10,
            pady=8,
            wrap=tk.WORD,
            font=("Consolas", 9),
        )
        self.help_text.grid(
            row=4, column=0, columnspan=2, sticky="nsew", pady=(0, 7)
        )
        self.help_double_click_label = ttk.Label(
            shell,
            text=self.i18n.text("paint.double_click_help"),
            style="PaintPanelMuted.TLabel",
            wraplength=320,
        )
        self.help_double_click_label.grid(
            row=5, column=0, columnspan=2, sticky="w"
        )
        self._refresh_help_contents()
        self.help_tool_window.withdraw()

    def _on_ribbon_tab_clicked(self, name: str) -> None:
        if name == self._ribbon_selected and self._ribbon_expanded:
            self._ribbon_expanded = False
            self._apply_ribbon_state()
            return
        self._select_ribbon(name)

    def _select_ribbon(
        self,
        name: str,
        *,
        ensure_expanded: bool = True,
    ) -> None:
        if name not in getattr(self, "ribbon_pages", {}):
            return
        self._ribbon_selected = name
        if ensure_expanded:
            self._ribbon_expanded = True
        self._apply_ribbon_state()

    def _select_ribbon_for_tool(self, tool: str) -> None:
        page = {
            "orbit": "home",
            "brush": "brush",
            "airbrush": "brush",
            "eyedropper": "brush",
            "smudge": "brush",
            "fill": "brush",
            "smooth": "brush",
            "erase": "brush",
        }.get(str(tool))
        if page is not None:
            self._select_ribbon(page)

    def _apply_ribbon_state(self) -> None:
        body = getattr(self, "ribbon_body", None)
        pages = getattr(self, "ribbon_pages", {})
        if body is None:
            return
        if self._ribbon_expanded:
            body.grid()
            for name, page in pages.items():
                if name == self._ribbon_selected:
                    page.grid()
                else:
                    page.grid_remove()
        else:
            body.grid_remove()
        for name, button in getattr(self, "ribbon_tab_buttons", {}).items():
            selected = name == self._ribbon_selected
            button.configure(
                bg="#1B668A" if selected else "#111722",
                activebackground="#2C7FA5" if selected else "#24445C",
            )
        self._refresh_workspace_controls()

    def _toggle_ribbon(self) -> None:
        self._ribbon_expanded = not bool(self._ribbon_expanded)
        self._apply_ribbon_state()

    def _toggle_reference(self) -> None:
        if self.reference_image is None:
            self.reference_visible_var.set(False)
            self.status_var.set(self.i18n.text("paint.reference_unavailable"))
            self._refresh_workspace_controls()
            return
        visible = not bool(self.reference_visible_var.get())
        self.reference_visible_var.set(visible)
        self.status_var.set(
            self.i18n.text(
                "paint.reference_shown" if visible else "paint.reference_hidden"
            )
        )
        self._refresh_workspace_controls()
        self._draw_canvas()

    def _show_palette_tool_window(self) -> None:
        self.palette_visible_var.set(True)
        palette = getattr(self, "palette_tool_window", None)
        if palette is not None and palette.winfo_exists():
            palette.deiconify()
            palette.lift()
        self._refresh_workspace_controls()

    def _show_palette(self) -> None:
        self._show_palette_tool_window()

    def _hide_palette(self) -> None:
        palette = getattr(self, "palette_tool_window", None)
        if palette is not None and palette.winfo_exists():
            palette.withdraw()
        self.palette_visible_var.set(False)
        self._refresh_workspace_controls()

    def _toggle_palette(self) -> None:
        palette = getattr(self, "palette_tool_window", None)
        actually_open = False
        if palette is not None and palette.winfo_exists():
            try:
                actually_open = str(palette.state()) not in {
                    "withdrawn",
                    "iconic",
                }
            except tk.TclError:
                pass
        if actually_open:
            self._hide_palette()
        else:
            self._show_palette()

    def _toggle_palette_collapsed(self) -> None:
        content = getattr(self, "floating_palette_content", None)
        if content is None:
            return
        body = getattr(self, "palette_body", content)
        self._palette_collapsed = not bool(self._palette_collapsed)
        if self._palette_collapsed:
            body.pack_forget()
        else:
            body.pack(fill=tk.BOTH, expand=True)
        button = getattr(self, "palette_collapse_button", None)
        if button is not None:
            button.configure(text="＋" if self._palette_collapsed else "−")

    def _start_palette_drag(self, event: tk.Event) -> None:
        # Retained for extension compatibility.  The OS title bar is the
        # normal movement path and intentionally has no parent-window clamp.
        palette = getattr(self, "floating_palette", None)
        if palette is None:
            return
        x = int(palette.winfo_x())
        y = int(palette.winfo_y())
        self._palette_drag_origin = (int(event.x_root), int(event.y_root), x, y)

    def _drag_palette(self, event: tk.Event) -> None:
        origin = self._palette_drag_origin
        palette = getattr(self, "floating_palette", None)
        if origin is None or palette is None:
            return
        root_x, root_y, start_x, start_y = origin
        x = start_x + int(event.x_root) - root_x
        y = start_y + int(event.y_root) - root_y
        self._palette_place = (x, y)
        palette.geometry(f"{x:+d}{y:+d}")

    def _end_palette_drag(self, _event: tk.Event) -> None:
        self._palette_drag_origin = None

    def _show_parts_tool_window(self) -> None:
        window = getattr(self, "parts_tool_window", None)
        if window is None or not window.winfo_exists():
            return
        self.parts_tool_visible_var.set(True)
        self._sync_part_visibility_controls()
        self._sync_active_part_identity()
        window.deiconify()
        window.lift()
        self._refresh_workspace_controls()

    def _hide_parts_tool_window(self) -> None:
        window = getattr(self, "parts_tool_window", None)
        if window is not None and window.winfo_exists():
            window.withdraw()
        self.parts_tool_visible_var.set(False)
        self._refresh_workspace_controls()

    def _toggle_parts_tool_window(self) -> None:
        window = getattr(self, "parts_tool_window", None)
        actually_open = False
        if window is not None and window.winfo_exists():
            try:
                actually_open = str(window.state()) not in {
                    "withdrawn",
                    "iconic",
                }
            except tk.TclError:
                pass
        if actually_open:
            self._hide_parts_tool_window()
        else:
            self._show_parts_tool_window()

    def _hide_help_tool_window(self) -> None:
        window = getattr(self, "help_tool_window", None)
        if window is not None and window.winfo_exists():
            window.withdraw()
        self.help_tool_visible_var.set(False)
        self._refresh_workspace_controls()

    def _show_initial_tool_windows(self) -> None:
        """Open every initially requested palette after Tk finishes layout."""

        self._initial_tool_windows_after = None
        if self._closing or self._close_requested:
            return
        self._apply_desired_tool_window_visibility()

    def _on_editor_destroyed(self, event: tk.Event) -> None:
        """Cancel the initial idle callback when Tk tears down the editor."""

        if getattr(event, "widget", None) is not self.window:
            return
        after_id = self._initial_tool_windows_after
        self._initial_tool_windows_after = None
        if not after_id:
            return
        try:
            self.window.after_cancel(after_id)
        except tk.TclError:
            # Direct root destruction may already have removed Tcl's `after`
            # command.  Clearing the Python-side ID still makes repeated
            # Destroy/finalize paths harmless.
            pass

    def _tool_windows_with_desired_visibility(self):
        return (
            (
                getattr(self, "palette_tool_window", None),
                getattr(self, "palette_visible_var", None),
            ),
            (
                getattr(self, "parts_tool_window", None),
                getattr(self, "parts_tool_visible_var", None),
            ),
            (
                getattr(self, "help_tool_window", None),
                getattr(self, "help_tool_visible_var", None),
            ),
        )

    def _on_editor_unmapped(self, event: tk.Event) -> None:
        """Hide owned palettes without forgetting which ones were open."""

        if getattr(event, "widget", None) is not self.window:
            return
        for attribute in (
            "_tool_restore_after",
            "_tool_restore_verify_after",
        ):
            after_id = getattr(self, attribute, None)
            if after_id:
                try:
                    self.window.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attribute, None)
        self._tool_restore_attempts = 0
        if self._closing or self._close_requested:
            return
        for tool_window, desired_var in self._tool_windows_with_desired_visibility():
            if tool_window is None or desired_var is None:
                continue
            try:
                if bool(desired_var.get()) and tool_window.winfo_exists():
                    tool_window.withdraw()
            except tk.TclError:
                continue

    def _on_editor_mapped(self, event: tk.Event) -> None:
        """Restore only palettes that the user had explicitly left open."""

        if getattr(event, "widget", None) is not self.window:
            return
        if self._closing or self._close_requested:
            return
        restore_after = getattr(self, "_tool_restore_after", None)
        if restore_after:
            try:
                self.window.after_cancel(restore_after)
            except tk.TclError:
                pass
        verify_after = getattr(self, "_tool_restore_verify_after", None)
        if verify_after:
            try:
                self.window.after_cancel(verify_after)
            except tk.TclError:
                pass
            self._tool_restore_verify_after = None
        self._tool_restore_attempts = 0
        # Windows emits Map before ShowWindow(SW_RESTORE) has completed its
        # owner-window pass.  A short delay here is not enough: Windows can
        # hide/recreate an owned HWND again after the first deiconify.
        self._tool_restore_after = self.window.after(
            TOOL_RESTORE_DELAY_MS, self._restore_desired_tool_windows
        )

    def _restore_desired_tool_windows(self) -> None:
        self._tool_restore_after = None
        if self._closing or self._close_requested:
            return
        try:
            editor_state = str(self.window.state())
            if editor_state not in {"normal", "zoomed"}:
                self._tool_restore_attempts += 1
                if self._tool_restore_attempts <= TOOL_RESTORE_MAX_RETRIES:
                    self._tool_restore_after = self.window.after(
                        TOOL_RESTORE_RETRY_MS,
                        self._restore_desired_tool_windows,
                    )
                return
        except tk.TclError:
            return
        self._tool_restore_attempts = 0
        self._apply_desired_tool_window_visibility()
        # A second pass is intentional.  On Windows, the first pass can create
        # a fresh tool-window HWND that the tail end of SW_RESTORE hides again.
        self._tool_restore_verify_after = self.window.after(
            TOOL_RESTORE_VERIFY_DELAY_MS,
            self._verify_desired_tool_windows,
        )

    def _apply_desired_tool_window_visibility(self) -> None:
        for tool_window, desired_var in self._tool_windows_with_desired_visibility():
            if tool_window is None or desired_var is None:
                continue
            try:
                if bool(desired_var.get()) and tool_window.winfo_exists():
                    tool_window.deiconify()
                    tool_window.lift()
            except tk.TclError:
                continue
        self._sync_part_visibility_controls()
        self._refresh_workspace_controls()

    def _verify_desired_tool_windows(self) -> None:
        self._tool_restore_verify_after = None
        if self._closing or self._close_requested:
            return
        try:
            if str(self.window.state()) not in {"normal", "zoomed"}:
                return
        except tk.TclError:
            return
        self._apply_desired_tool_window_visibility()

    def _on_orbit_direction_changed(self) -> None:
        inverted = bool(self.orbit_inverted_var.get())
        self.settings.manual_orbit_inverted = inverted
        callback = self.on_orbit_direction_changed
        if callback is not None:
            callback(inverted)
        self.status_var.set(
            self.i18n.text(
                "paint.orbit_inverted_on"
                if inverted
                else "paint.orbit_inverted_off"
            )
        )

    def maximize(self) -> None:
        """Open as a normal maximized editor while retaining the title bar."""

        try:
            self.window.attributes("-fullscreen", False)
            self.window.state("zoomed")
        except tk.TclError:
            try:
                self.window.attributes("-zoomed", True)
            except tk.TclError:
                pass
        self._fullscreen = False
        self._refresh_workspace_controls()

    def _toggle_fullscreen(self) -> None:
        if self._fullscreen:
            self._exit_fullscreen()
            return
        try:
            self.window.attributes("-fullscreen", True)
            self._fullscreen = True
        except tk.TclError:
            self.maximize()
        self._refresh_workspace_controls()

    def _exit_fullscreen(self, _event: object | None = None) -> str | None:
        if not self._fullscreen:
            return None
        try:
            self.window.attributes("-fullscreen", False)
        except tk.TclError:
            pass
        self._fullscreen = False
        try:
            self.window.state("zoomed")
        except tk.TclError:
            pass
        self._refresh_workspace_controls()
        return "break"

    def _refresh_help_contents(self) -> None:
        text = getattr(self, "help_text", None)
        if text is None:
            return
        rows = shortcut_help_rows()
        widest = max((len(key) for key, _label, _group in rows), default=0)
        body = "\n".join(
            f"{key.ljust(widest)}   {self.i18n.text(label_key)}"
            for key, label_key, _group in rows
        )
        text.configure(state=tk.NORMAL)
        text.delete("1.0", tk.END)
        text.insert("1.0", body)
        text.configure(state=tk.DISABLED)

    def _refresh_tool_window_texts(self) -> None:
        palette = getattr(self, "palette_tool_window", None)
        if palette is not None and palette.winfo_exists():
            palette.title(self.i18n.text("paint.floating_palette_title"))
        parts = getattr(self, "parts_tool_window", None)
        if parts is not None and parts.winfo_exists():
            parts.title(self.i18n.text("paint.parts_tool_title"))
        help_window = getattr(self, "help_tool_window", None)
        if help_window is not None and help_window.winfo_exists():
            help_window.title(self.i18n.text("paint.shortcut_help_title"))
        labels = (
            ("palette_title_label", "paint.floating_palette_title"),
            ("palette_drag_hint_label", "paint.tool_window_outside_hint"),
            ("parts_tool_title_label", "paint.parts_tool_title"),
            ("parts_tool_outside_hint_label", "paint.tool_window_outside_hint"),
            ("parts_double_click_help_label", "paint.double_click_help"),
            ("help_title_label", "paint.shortcut_help_button"),
            ("help_outside_hint_label", "paint.tool_window_outside_hint"),
            ("help_intro_label", "paint.shortcut_help_intro"),
            ("help_controls_hint_label", "paint.controls_hint"),
            ("help_double_click_label", "paint.double_click_help"),
        )
        for attribute, key in labels:
            widget = getattr(self, attribute, None)
            if widget is not None:
                widget.configure(text=self.i18n.text(key))
        buttons = (
            ("part_rename_button", "paint.rename_part"),
            ("parts_only_selected_button", "paint.only_selected_visible"),
            (
                "parts_others_transparent_button",
                "paint.only_selected_transparent",
            ),
            ("parts_show_all_button", "paint.show_all_parts"),
        )
        for attribute, key in buttons:
            widget = getattr(self, attribute, None)
            if widget is not None:
                widget.configure(text=self.i18n.text(key))
        self._refresh_help_contents()

    def _refresh_workspace_controls(self) -> None:
        reference_visible = bool(
            self.reference_image is not None and self.reference_visible_var.get()
        )
        reference_key = (
            "paint.reference_hide" if reference_visible else "paint.reference_show"
        )
        reference_state = "normal" if self.reference_image is not None else "disabled"
        for attribute in ("reference_toggle_button", "view_reference_button"):
            button = getattr(self, attribute, None)
            if button is not None:
                button.configure(
                    text=self.i18n.text(reference_key),
                    state=reference_state,
                )
        palette_button = getattr(self, "palette_toggle_button", None)
        if palette_button is not None:
            palette_button.configure(
                text=self.i18n.text(
                    "paint.palette_hide"
                    if bool(self.palette_visible_var.get())
                    else "paint.palette_show"
                )
            )
        parts_button = getattr(self, "parts_tool_button", None)
        if parts_button is not None:
            parts_button.configure(text=self.i18n.text("paint.parts_tool_show"))
        ribbon_button = getattr(self, "ribbon_toggle_button", None)
        if ribbon_button is not None:
            ribbon_button.configure(
                text=self.i18n.text(
                    "paint.ribbon_collapse"
                    if self._ribbon_expanded
                    else "paint.ribbon_expand"
                )
                + "  Ctrl+F1"
            )
        fullscreen_button = getattr(self, "fullscreen_button", None)
        if fullscreen_button is not None:
            fullscreen_button.configure(
                text=self.i18n.text(
                    "paint.fullscreen_exit"
                    if self._fullscreen
                    else "paint.fullscreen_enter"
                )
            )
        help_button = getattr(self, "shortcut_help_button", None)
        if help_button is not None:
            help_button.configure(text=self.i18n.text("paint.quick_help"))
        for name, button in getattr(self, "ribbon_tab_buttons", {}).items():
            key = getattr(self, "_ribbon_tab_keys", {}).get(name)
            if key:
                button.configure(text=self.i18n.text(key))

    def _part_visibility_labels(self) -> tuple[str, str, str]:
        return (
            self.i18n.text("paint.part_visible"),
            self.i18n.text("paint.part_transparent"),
            self.i18n.text("paint.part_hidden"),
        )

    def _request_solidify(self) -> None:
        """Leave the editor cleanly, then reuse the main solidification flow."""

        if self._reject_during_topology_change():
            return
        callback = self.on_solidify_requested
        if callback is None:
            self.status_var.set(self.i18n.text("paint.solidify_unavailable"))
            return
        if not messagebox.askyesno(
            self.i18n.text("assembly.solidify_title"),
            self.i18n.text("paint.solidify_confirm"),
            parent=self.window,
        ):
            return
        self.status_var.set(self.i18n.text("paint.solidify_closing"))
        callback()

    def _install_shortcuts(self) -> None:
        self._shortcut_bindings = install_manual_shortcuts(
            self.window, self._dispatch_shortcut
        )

    def _dispatch_shortcut(self, action: str, _event: object) -> bool:
        """Translate the toolkit-independent shortcut action into editor work."""

        if self._close_requested or self._closing:
            return False
        if action == "show_shortcuts":
            self._show_shortcut_help()
            return True
        if action == "toggle_reference":
            self._toggle_reference()
            return True
        if action == "toggle_palette":
            self._toggle_palette()
            return True
        if action == "toggle_ribbon":
            self._toggle_ribbon()
            return True
        if action == "toggle_fullscreen":
            self._toggle_fullscreen()
            return True
        if self._reject_during_topology_change():
            return True
        if action == "undo":
            self._commit_active_stroke()
            self._undo()
            return True
        if action == "redo":
            self._commit_active_stroke()
            self._redo()
            return True
        tool = TOOL_ACTIONS.get(action)
        if tool is not None:
            # Split and manual-joint engines remain in source for development,
            # but the public manual editor deliberately exposes no entry point.
            if tool in ("lasso", "joint"):
                return False
            self._commit_active_stroke()
            self._lasso_points.clear()
            if hasattr(self, "canvas"):
                self.canvas.delete("split-lasso")
            self.tool_var.set(tool)
            self._on_tool_changed()
            self.status_var.set(
                self.i18n.text(
                    "paint.shortcut_tool_selected",
                    tool=self.i18n.text(
                        {
                            "orbit": "paint.orbit",
                            "brush": "paint.brush",
                            "airbrush": "paint.airbrush",
                            "eyedropper": "paint.eyedropper_3d",
                            "smudge": "paint.smudge",
                            "fill": "paint.fill",
                            "smooth": "paint.smooth",
                            "erase": "paint.erase",
                        }[tool]
                    ),
                )
            )
            return True
        visibility = PART_VISIBILITY_ACTIONS.get(action)
        if visibility is not None:
            mode = {
                "visible": PART_VISIBLE,
                "transparent": PART_TRANSPARENT,
                "hidden": PART_HIDDEN,
            }[visibility]
            self.set_part_display_mode(self.active_part_id, mode)
            return True
        return False

    def _show_shortcut_help(self) -> None:
        window = getattr(self, "help_tool_window", None)
        if window is None or not window.winfo_exists():
            return
        self.help_tool_visible_var.set(True)
        self._refresh_help_contents()
        window.deiconify()
        window.lift()
        self._refresh_workspace_controls()

    def _sync_joint_guidance(self) -> ManualJointAvailability:
        status = assess_manual_joint_availability(self.prepared)
        self._manual_joint_availability = status
        message = self.i18n.text(status.message_key, **status.message_values)
        availability_var = getattr(self, "joint_availability_var", None)
        if availability_var is not None:
            availability_var.set(message)
        return status

    def _show_joint_guidance(self) -> None:
        status = self._sync_joint_guidance()
        availability = self.i18n.text(
            status.message_key, **status.message_values
        )
        next_step = (
            "\n\n" + self.i18n.text(status.next_step_key)
            if status.next_step_key
            else ""
        )
        workflow = "\n".join(
            self.i18n.text(key) for key in MANUAL_JOINT_WORKFLOW_KEYS
        )
        messagebox.showinfo(
            self.i18n.text("joint.workflow.title"),
            availability
            + next_step
            + "\n\n"
            + self.i18n.text("joint.workflow.general_label")
            + "\n"
            + workflow,
            parent=self.window,
        )

    def _part_visibility_label(self, mode: int) -> str:
        labels = self._part_visibility_labels()
        value = int(mode)
        return labels[value] if PART_VISIBLE <= value <= PART_HIDDEN else labels[0]

    def _current_part_visibility_mode(self) -> int:
        modes = getattr(self, "_part_visibility_modes", None)
        part_id = int(getattr(self, "active_part_id", 0))
        if isinstance(modes, np.ndarray) and 0 <= part_id < len(modes):
            return int(modes[part_id])
        return PART_VISIBLE

    def _sync_part_visibility_controls(self) -> None:
        selector = getattr(self, "part_visibility_selector", None)
        check = getattr(self, "pick_transparent_check", None)
        enabled = (
            len(self.part_labels) > 1
            and not bool(getattr(self, "_topology_change_pending", False))
        )
        if selector is not None:
            selector.configure(
                values=self._part_visibility_labels(),
                state="readonly" if enabled else "disabled",
            )
        if check is not None:
            check.configure(state="normal" if enabled else "disabled")
        self.part_visibility_var.set(
            self._part_visibility_label(self._current_part_visibility_mode())
        )

    def _sync_part_selector_controls(self) -> None:
        state = (
            "disabled"
            if bool(getattr(self, "_topology_change_pending", False))
            else "readonly"
        )
        for attribute in ("part_selector", "quick_part_selector"):
            selector = getattr(self, attribute, None)
            if selector is not None:
                selector.configure(values=self.part_labels, state=state)

    def _set_topology_change_pending(self, pending: bool) -> None:
        """Block face-indexed UI actions while a joint swaps mesh topology."""

        self._topology_change_pending = bool(pending)
        self._sync_part_selector_controls()
        self._sync_part_visibility_controls()
        undo_button = getattr(self, "joint_undo_button", None)
        if undo_button is not None:
            undo_button.configure(
                state=(
                    "disabled"
                    if self._topology_change_pending
                    or self._manual_joint_undo_state is None
                    else "normal"
                )
            )

    def _reject_during_topology_change(self) -> bool:
        if not bool(getattr(self, "_topology_change_pending", False)):
            return False
        self.status_var.set(self.i18n.text("joint.wait"))
        return True

    def _face_visibility_modes(self) -> np.ndarray:
        """Expand the tiny per-part table to one byte per mesh face."""

        face_count = len(self.level.faces)
        face_part_ids = np.asarray(self.level.face_part_ids)
        modes = np.asarray(self._part_visibility_modes, dtype=np.uint8)
        if (
            face_part_ids.shape != (face_count,)
            or not np.issubdtype(face_part_ids.dtype, np.integer)
            or len(modes) == 0
        ):
            return np.zeros(face_count, dtype=np.uint8)
        safe_ids = face_part_ids.astype(np.int64, copy=False)
        valid = (safe_ids >= 0) & (safe_ids < len(modes))
        result = np.zeros(face_count, dtype=np.uint8)
        result[valid] = modes[safe_ids[valid]]
        return result

    def _invalidate_visibility_pick_map(self) -> None:
        # A visibility change alters occlusion even when the camera is
        # unchanged.  Force all renderer hotfixes to request a fresh face-ID
        # pass rather than retaining the previous camera's map.
        self.face_ids = None
        self._render_dirty = True
        self._hotfix_pick_camera = None
        self._rotation_hotfix_force_final = True
        self._hotfix_overlay_cache = None
        self._mark_decal_preview_stale("decal.view_wait", view_change=True)

    def _queue_visibility_update(self, message: str) -> None:
        face_modes = self._face_visibility_modes().copy()
        pick_transparent = bool(self.pick_transparent_var.get())
        self._invalidate_visibility_pick_map()

        def work():
            if self._renderer is None:
                return None
            self._renderer.set_face_visibility(
                face_modes,
                pick_transparent=pick_transparent,
            )
            return self._worker_snapshot(None, message)

        self._submit("visibility", work)

    def set_part_display_mode(self, part_id: int, mode: int) -> bool:
        """Set one part to visible, transparent, or hidden from the Tk thread."""

        if self._reject_during_topology_change():
            self._sync_part_visibility_controls()
            return False

        index = int(part_id)
        value = int(mode)
        if index < 0 or index >= len(self._part_visibility_modes):
            raise ValueError("part_id is outside the manual editor part table")
        if value not in (PART_VISIBLE, PART_TRANSPARENT, PART_HIDDEN):
            raise ValueError("part display mode must be visible, transparent, or hidden")
        if int(self._part_visibility_modes[index]) == value:
            return False
        self._commit_active_stroke()
        self._part_visibility_modes[index] = value
        if index == self.active_part_id:
            self.part_visibility_var.set(self._part_visibility_label(value))
        self._queue_visibility_update(
            self.i18n.text(
                "paint.visibility_changed",
                part=self.part_names[index],
                mode=self._part_visibility_label(value),
            )
        )
        return True

    def _set_bulk_part_display_modes(
        self,
        other_mode: int,
        *,
        action_key: str,
    ) -> bool:
        """Apply a multi-part visibility preset with one renderer update."""

        if self._reject_during_topology_change():
            self._sync_part_visibility_controls()
            return False
        value = int(other_mode)
        if value not in (PART_VISIBLE, PART_TRANSPARENT, PART_HIDDEN):
            raise ValueError("bulk part display mode is invalid")
        desired = np.full(
            len(self._part_visibility_modes), value, dtype=np.uint8
        )
        active = int(self.active_part_id)
        if 0 <= active < len(desired):
            desired[active] = PART_VISIBLE
        if np.array_equal(desired, self._part_visibility_modes):
            self._sync_part_visibility_controls()
            return False
        self._commit_active_stroke()
        self._part_visibility_modes[:] = desired
        self._sync_part_visibility_controls()
        self._queue_visibility_update(self.i18n.text(action_key))
        return True

    def show_only_active_part(self) -> bool:
        """Hide every part except the current editing target."""

        return self._set_bulk_part_display_modes(
            PART_HIDDEN,
            action_key="paint.only_selected_visible",
        )

    def make_other_parts_transparent(self) -> bool:
        """Keep the active part opaque and make every other part transparent."""

        return self._set_bulk_part_display_modes(
            PART_TRANSPARENT,
            action_key="paint.only_selected_transparent",
        )

    def show_all_parts(self) -> bool:
        """Restore every part to the normal visible mode."""

        if self._reject_during_topology_change():
            self._sync_part_visibility_controls()
            return False
        desired = np.full(
            len(self._part_visibility_modes), PART_VISIBLE, dtype=np.uint8
        )
        if np.array_equal(desired, self._part_visibility_modes):
            self._sync_part_visibility_controls()
            return False
        self._commit_active_stroke()
        self._part_visibility_modes[:] = desired
        self._sync_part_visibility_controls()
        self._queue_visibility_update(self.i18n.text("paint.show_all_parts"))
        return True

    def set_transparent_part_picking(self, enabled: bool) -> bool:
        """Choose whether transparent parts stop the face-ID picking pass."""

        if self._reject_during_topology_change():
            self.pick_transparent_var.set(bool(self._pick_transparent_submitted))
            return False

        requested = bool(enabled)
        if bool(self._pick_transparent_submitted) == requested:
            return False
        self._commit_active_stroke()
        self.pick_transparent_var.set(requested)
        self._pick_transparent_submitted = requested
        self._queue_visibility_update(
            self.i18n.text(
                "paint.transparent_pick_changed",
                state=(
                    self.i18n.text("paint.enabled")
                    if requested
                    else self.i18n.text("paint.disabled")
                ),
            )
        )
        return True

    def _on_part_visibility_selected(self, _event=None) -> None:
        try:
            mode = self._part_visibility_labels().index(
                self.part_visibility_var.get()
            )
        except ValueError:
            self._sync_part_visibility_controls()
            return
        self.set_part_display_mode(self.active_part_id, mode)

    def _on_pick_transparent_changed(self) -> None:
        # ttk toggles the BooleanVar before invoking command.  The public API
        # compares against the last submitted renderer policy, not the Var.
        self.set_transparent_part_picking(bool(self.pick_transparent_var.get()))

    def _joint_settings_from_controls(self) -> ManualJointSettings:
        try:
            return ManualJointSettings(
                width_mm=float(self.joint_width_var.get()),
                height_mm=float(self.joint_length_var.get()),
                depth_mm=float(self.joint_depth_var.get()),
                clearance_mm=float(self.joint_clearance_var.get()),
            ).validated()
        except (ValueError, tk.TclError) as exc:
            raise ManualJointError(f"ジョイント寸法を確認してください: {exc}") from exc

    def _queue_manual_joint_target(
        self,
        face_id: int,
        center_unit: tuple[float, float, float],
    ) -> None:
        if PaintEditorWindow._reject_during_topology_change(self):
            return
        self._commit_active_stroke()
        flush_pending = getattr(self, "_flush_pending_paint", None)
        if callable(flush_pending):
            flush_pending()
        assembly = dict(self.prepared.assembly or {})
        automatic_records = assembly.get("joint_records", [])
        manual_records = assembly.get("manual_joint_records", [])
        if automatic_records and not manual_records:
            messagebox.showwarning(
                self.i18n.text("joint.confirm_title"),
                self.i18n.text("joint.auto_conflict"),
                parent=self.window,
            )
            return
        try:
            joint_settings = self._joint_settings_from_controls()
        except ManualJointError as exc:
            messagebox.showerror(
                self.i18n.text("joint.confirm_title"), str(exc), parent=self.window
            )
            return
        prepared = self.prepared
        height_mm = float(self.settings.geometry.height_mm)

        def work():
            if prepared is not self.prepared:
                raise ManualJointError("選択後に形状が変わりました")
            target = resolve_manual_joint_target(
                prepared,
                male_face_id=int(face_id),
                center_unit=center_unit,
                height_mm=height_mm,
                settings=joint_settings,
            )
            return {
                "confirm_manual_joint": target,
                "manual_joint_settings": joint_settings,
            }

        self._set_topology_change_pending(True)
        self.status_var.set(self.i18n.text("joint.checking"))
        self.canvas.configure(cursor="watch")
        self._submit("joint_plan", work)

    def _confirm_manual_joint(
        self,
        target: ManualJointTarget,
        joint_settings: ManualJointSettings,
    ) -> None:
        try:
            male_name = self.part_names[target.male_part_id]
            female_name = self.part_names[target.female_part_id]
        except IndexError:
            self._set_topology_change_pending(False)
            messagebox.showerror(
                self.i18n.text("joint.confirm_title"),
                "ジョイント対象のパーツが現在の形状にありません",
                parent=self.window,
            )
            return
        detail_store = getattr(self.prepared, "_hotfix_subtriangle_paint", None)
        adaptive_note = (
            "\n\n" + self.i18n.text("joint.adaptive_flatten_warning")
            if isinstance(detail_store, dict) and detail_store
            else ""
        )
        if not messagebox.askyesno(
            self.i18n.text("joint.confirm_title"),
            self.i18n.text(
                "joint.confirm_message",
                male=male_name,
                female=female_name,
                width=joint_settings.width_mm,
                length=joint_settings.height_mm,
                depth=joint_settings.depth_mm,
                clearance=joint_settings.clearance_mm,
            )
            + adaptive_note,
            parent=self.window,
        ):
            self._set_topology_change_pending(False)
            self.status_var.set(self.i18n.text("joint.cancelled"))
            return
        self._apply_manual_joint_target(target, joint_settings)

    def _apply_manual_joint_target(
        self,
        target: ManualJointTarget,
        joint_settings: ManualJointSettings,
    ) -> None:
        previous_record = (
            None
            if self._manual_joint_record is None
            else dict(self._manual_joint_record)
        )
        pick_transparent = bool(self.pick_transparent_var.get())

        def work():
            if self._session is None:
                raise ManualJointError("マニュアル修正の準備中です")
            before_prepared = self.prepared
            before_overrides = self._session.overrides.copy()
            result = apply_manual_joint(
                before_prepared,
                target,
                height_mm=float(self.settings.geometry.height_mm),
                settings=joint_settings,
            )
            remapped = remap_manual_overrides(
                before_prepared.final,
                result.after.final,
                before_overrides,
            )
            # A boolean operation retriangulates both interface parts.  Exact
            # adaptive leaves no longer have the same root faces, so retain
            # their dominant states through ``remapped`` and start a clean
            # sub-face store for subsequent painting.
            result.after._hotfix_subtriangle_paint = {}
            result.after._hotfix_tree_revision = int(
                getattr(before_prepared, "_hotfix_tree_revision", 0)
            ) + 1
            snapshot = self._worker_install_prepared(
                result.after,
                remapped,
                self.i18n.text("joint.completed"),
                pick_transparent=pick_transparent,
                preserve_adaptive=False,
            )
            snapshot["geometry_changed"] = {
                "record": dict(result.record),
            }
            snapshot["joint_undo_state"] = (
                before_prepared,
                before_overrides,
                previous_record,
            )
            return snapshot

        self.status_var.set(self.i18n.text("joint.generating"))
        self.canvas.configure(cursor="watch")
        self._submit("manual_joint", work)

    def _undo_manual_joint(self) -> None:
        state = self._manual_joint_undo_state
        if state is None:
            return
        if PaintEditorWindow._reject_during_topology_change(self):
            return
        if not messagebox.askyesno(
            self.i18n.text("joint.undo_confirm_title"),
            self.i18n.text("joint.undo_confirm"),
            parent=self.window,
        ):
            return
        before_prepared, before_overrides, previous_record = state
        pick_transparent = bool(self.pick_transparent_var.get())

        def work():
            snapshot = self._worker_install_prepared(
                before_prepared,
                before_overrides.copy(),
                self.i18n.text("joint.undone"),
                pick_transparent=pick_transparent,
                preserve_adaptive=True,
            )
            snapshot["geometry_changed"] = {
                "record": (
                    None if previous_record is None else dict(previous_record)
                ),
            }
            snapshot["joint_undo_completed"] = True
            return snapshot

        self._set_topology_change_pending(True)
        self.status_var.set(self.i18n.text("joint.checking"))
        self.canvas.configure(cursor="watch")
        self._submit("manual_joint_undo", work)

    def _active_palette(self):
        key = self.part_keys[self.active_part_id]
        return resolve_palette_for_part_key(self.settings, key)

    def _active_face_mask(self) -> np.ndarray:
        part_ids = np.asarray(self.level.face_part_ids)
        if part_ids.shape != (len(self.level.faces),):
            return np.ones(len(self.level.faces), dtype=bool)
        return part_ids == self.active_part_id

    def _visible_face_mask_for_stroke(self) -> np.ndarray | None:
        """Return one cached front-visible traversal mask for the exact frame.

        The renderer's face-ID map is authoritative for occlusion.  Building
        this full-face mask lazily once per exact frame prevents a wide local
        tool from wrapping through a thin limb onto its hidden back side,
        without rebuilding the mask for every pointer dab.
        """

        ids = getattr(self, "face_ids", None)
        level = getattr(self, "level", None)
        faces = getattr(level, "faces", ())
        face_count = len(faces)
        render_dirty = bool(getattr(self, "_render_dirty", False))
        pick_camera = getattr(self, "_hotfix_pick_camera", None)
        camera = getattr(self, "camera", None)
        if (
            ids is None
            # A pending color-only redraw keeps the geometry and camera
            # unchanged, so its existing face-ID map remains authoritative.
            # A camera-changing redraw must fail closed until the matching
            # pick map arrives; this mirrors ``_face_at_fixed`` exactly.
            or (render_dirty and pick_camera != camera)
            or face_count <= 0
        ):
            return None
        values = np.asarray(ids)
        if values.ndim != 2 or not np.issubdtype(values.dtype, np.integer):
            return None
        key = (id(ids), values.shape, face_count)
        if (
            getattr(self, "_visible_face_mask_source", None) is ids
            and key == getattr(self, "_visible_face_mask_cache_key", None)
        ):
            return getattr(self, "_visible_face_mask_cache", None)
        visible = values[(values >= 0) & (values < face_count)]
        mask = np.zeros(face_count, dtype=bool)
        if len(visible):
            # Duplicate pixels are harmless; direct indexed assignment avoids
            # sorting a potentially multi-million-pixel ID buffer.
            mask[visible] = True
        self._visible_face_mask_cache_key = key
        self._visible_face_mask_cache = mask
        self._visible_face_mask_source = ids
        return mask

    def _rename_active_part(self) -> None:
        if self._reject_during_topology_change():
            return
        self._commit_active_stroke()
        part_id = int(self.active_part_id)
        if not 0 <= part_id < len(self.part_keys):
            return
        part_key = self.part_keys[part_id]
        try:
            name = rename_prepared_part(
                self.prepared,
                part_key,
                self.part_name_var.get(),
            )
        except PartNameError as exc:
            messagebox.showwarning(
                self.i18n.text("paint.part_rename_title"),
                str(exc),
                parent=self.window,
            )
            self.part_name_entry.focus_set()
            self.part_name_entry.selection_range(0, tk.END)
            return

        self.level = self.prepared.final
        self.part_names = tuple(self.level.part_names) or ("OBJ全体",)
        self.part_labels = tuple(
            f"{index + 1}: {part_name}"
            for index, part_name in enumerate(self.part_names)
        )
        self._sync_part_selector_controls()
        self.part_target_var.set(self.part_labels[part_id])
        self.settings.part_names[part_key] = name
        self._sync_active_part_identity()
        if self.on_part_name_changed is not None:
            self.on_part_name_changed(part_key, name)
        self.status_var.set(self.i18n.text("paint.part_renamed", name=name))

    def _on_view_background_selected(self, _event=None) -> None:
        mode = self._view_background_mode_from_label(
            self.view_background_var.get()
        )
        if mode == self.view_theme_mode:
            return
        self._commit_active_stroke()
        self.view_theme_mode = mode
        if self._model_view_key:
            self.settings.manual_view_backgrounds[self._model_view_key] = mode
        self.view_background_var.set(self._view_background_label(mode))
        if self._model_view_key and self.on_view_background_changed is not None:
            self.on_view_background_changed(self._model_view_key, mode)
        label = self._view_background_label(mode)

        def work():
            if self._session is None or self._display_colors is None:
                return None
            appearance = resolve_view_appearance(
                mode, self._display_colors.target_face_rgb
            )
            self._view_appearance = appearance
            if self._renderer is not None:
                self._renderer.set_background(appearance.background)
                self._renderer.set_active_part(
                    self.active_part_id,
                    color=appearance.active_part_accent,
                )
            return self._worker_snapshot(
                None,
                self.i18n.text("paint.background_changed", mode=label),
            )

        self._submit("view_background", work)

    def _on_editor_part_selected(self, _event=None) -> None:
        if self._reject_during_topology_change():
            self.part_target_var.set(self.part_labels[self.active_part_id])
            return
        try:
            part_id = self.part_labels.index(self.part_target_var.get())
        except ValueError:
            return
        if part_id == self.active_part_id:
            return
        self._commit_active_stroke()
        self.active_part_id = part_id
        count_variable = getattr(
            self, "manual_palette_state_count_var", None
        )
        if count_variable is not None:
            count_variable.set(self._active_palette().palette_state_count)
        # Selection is visual state, not a Parts-panel state.  Invalidate every
        # cached pick/outline product immediately so rotation hotfixes cannot
        # reuse a frame outlined for the previous part.  The actual renderer
        # call remains on its owning worker thread below.
        self._invalidate_visibility_pick_map()
        self._sync_part_visibility_controls()
        self._refresh_palette_buttons()
        self._sync_active_part_identity()
        part_name = self.part_names[part_id]
        selected_message = self.i18n.text(
            "paint.part_selected", part=part_name
        )

        def work():
            if self._session is None:
                return None
            self._session.set_allowed_faces(self._active_face_mask())
            if self._renderer is not None:
                self._renderer.set_active_part(
                    part_id,
                    color=self._view_appearance.active_part_accent,
                )
            return self._worker_snapshot(
                None, selected_message
            )

        self._submit("part", work)

    def select_part_by_key(self, part_key: str) -> None:
        """Select the same immutable part key used by the main workspace."""

        try:
            part_id = self.part_keys.index(str(part_key))
        except ValueError:
            raise ValueError(f"Unknown part key: {part_key}") from None
        label = self.part_labels[part_id]
        self.part_target_var.set(label)
        if part_id == self.active_part_id:
            self._sync_part_visibility_controls()
            self._refresh_palette_buttons()
            self._sync_active_part_identity()
            return
        self._on_editor_part_selected()

    def _refresh_palette_buttons(self) -> None:
        active_palette = self._active_palette()
        flat_mode = (
            getattr(active_palette, "color_mode", None)
            == COLOR_MODE_FLAT_FOUR
        )
        effective_count = 4 if flat_mode else active_palette.palette_state_count
        count_variable = getattr(
            self, "manual_palette_state_count_var", None
        )
        if count_variable is not None:
            # The control describes what can be painted *now*.  Keep the
            # stored Full Spectrum count untouched so switching back restores
            # the user's previous 16/24/32-colour setup.
            count_variable.set(effective_count)
        count_combo = getattr(self, "manual_palette_state_count_combo", None)
        if count_combo is not None:
            count_combo.configure(state="disabled" if flat_mode else "readonly")
        if int(self.paint_state_var.get()) >= effective_count:
            self.paint_state_var.set(0)
        palette_hex, palette_rgb = build_palette_rgb(
            active_palette.physical_hex,
            active_palette.mix_hex_overrides,
            active_palette.mix_ratios_b,
            active_palette.secondary_mix_ratios_b,
        )
        self.palette_rgb = palette_rgb
        self.state_names = palette_state_names(
            active_palette.mix_ratios_b,
            active_palette.secondary_mix_ratios_b,
        )
        for state, (button, color, rgb) in enumerate(
            zip(self.palette_buttons, palette_hex, palette_rgb, strict=True)
        ):
            foreground = _readable_text(rgb)
            button.configure(
                bg=color,
                activebackground=color,
                selectcolor=color,
                fg=foreground,
                activeforeground=foreground,
                disabledforeground="#6E7785",
            )
        self._layout_manual_palette_buttons(active_palette)
        self._update_selected_palette_label()

    def _layout_manual_palette_buttons(
        self,
        active_palette: PaletteSettings,
    ) -> None:
        """Mirror Filament Settings' family-major presentation without renumbering.

        Button values remain canonical palette state IDs.  Only their visual
        position and short label follow the shared calibration/main-palette
        presentation mapping, so an old project or an active paint selection
        cannot silently change recipe when this panel is rearranged.
        """

        for button in self.palette_buttons:
            button.grid_remove()
        physical_label = getattr(self, "manual_palette_physical_label", None)
        if physical_label is not None:
            physical_label.grid_remove()
        family_labels = getattr(self, "manual_palette_family_labels", {})
        for label in family_labels.values():
            label.grid_remove()

        rows = palette_family_display_rows(active_palette)
        if getattr(active_palette, "color_mode", None) == COLOR_MODE_FLAT_FOUR:
            rows = tuple(row for row in rows if row.get("chart_number") is None)
        physical_rows = [row for row in rows if row.get("chart_number") is None]
        if physical_rows and physical_label is not None:
            physical_label.grid(row=1, column=0, sticky="w", padx=(0, 4), pady=1)
        for column, row in enumerate(physical_rows, start=1):
            state = int(row["state"]) - 1
            if not 0 <= state < len(self.palette_buttons):
                continue
            button = self.palette_buttons[state]
            button.configure(text=str(row["display_label"]))
            button.grid(row=1, column=column, padx=2, pady=2, sticky="ew")

        mixed_by_pair: dict[str, list[dict[str, object]]] = {
            f"F{left + 1}+F{right + 1}": [] for left, right in PAIR_INDICES
        }
        for row in rows:
            if row.get("chart_number") is not None:
                mixed_by_pair.setdefault(str(row["f_pair"]), []).append(row)
        for pair_index, (pair_name, pair_rows) in enumerate(
            mixed_by_pair.items(), start=2
        ):
            if not pair_rows:
                continue
            label = family_labels.get(pair_name)
            if label is not None:
                label.grid(
                    row=pair_index,
                    column=0,
                    sticky="w",
                    padx=(0, 4),
                    pady=1,
                )
            for column, row in enumerate(pair_rows, start=1):
                state = int(row["state"]) - 1
                if not 0 <= state < len(self.palette_buttons):
                    continue
                display_label = str(row["display_label"])
                if _is_manual_only_palette_state(active_palette, state):
                    display_label += "*"
                button = self.palette_buttons[state]
                button.configure(text=display_label)
                button.grid(
                    row=pair_index,
                    column=column,
                    padx=2,
                    pady=2,
                    sticky="ew",
                )

    def _on_manual_palette_state_count_changed(self, _event=None) -> None:
        active_palette = self._active_palette()
        if getattr(active_palette, "color_mode", None) == COLOR_MODE_FLAT_FOUR:
            self.manual_palette_state_count_var.set(4)
            return
        count = int(self.manual_palette_state_count_var.get())
        part_key = self.part_keys[self.active_part_id]
        if len(self.part_keys) > 1 or part_key in self.settings.part_palettes:
            callback_key: str | None = part_key
        else:
            callback_key = None
        change = apply_palette_state_count_change(
            self.settings,
            count,
            target_part_key=callback_key,
        )
        palette = change.palette
        self._refresh_palette_buttons()
        callback = self.on_palette_settings_changed
        if callback is not None:
            callback(callback_key, _copy_palette_settings(palette))
        if callback_key is None:
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
        self._queue_shading_reapply(
            status
        )

    def _update_selected_palette_label(self) -> None:
        state = int(self.paint_state_var.get())
        state_changed = state != int(self._palette_usage_focus_state)
        self._palette_usage_focus_state = state
        if state_changed:
            self._invalidate_palette_usage_render_cache()
        names = getattr(self, "state_names", STATE_NAMES)
        active_palette = self._active_palette()
        if 0 <= state < len(names):
            suffix = (
                self.i18n.text("paint.manual_only_suffix")
                if _is_manual_only_palette_state(active_palette, state)
                else ""
            )
            self.palette_name_var.set(
                self.i18n.text(
                    "paint.selected_color",
                    state=state + 1,
                    name=names[state],
                    suffix=suffix,
                )
            )
        self._update_palette_usage_summary()
        mode_variable = getattr(self, "decal_mode_var", None)
        if (
            state_changed
            and mode_variable is not None
            and str(mode_variable.get()) == "selected"
        ):
            self._mark_decal_preview_stale("decal.changed")
        if (
            state_changed
            and bool(self._palette_usage_focus_enabled)
            and self._renderer is not None
            and not self._close_requested
        ):
            self._schedule_render(immediate=True)

    def _on_palette_state_selected(self) -> None:
        """Refresh paint selection and the optional read-only usage overlay."""

        self._update_selected_palette_label()

    def _invalidate_palette_usage_render_cache(self) -> None:
        self._palette_usage_render_cache_key = None
        self._palette_usage_render_cache = None

    def _on_palette_usage_focus_changed(self) -> None:
        self._palette_usage_focus_enabled = bool(
            self.palette_usage_focus_var.get()
        )
        self._palette_usage_focus_state = int(self.paint_state_var.get())
        self._invalidate_palette_usage_render_cache()
        self._update_palette_usage_summary()
        self.status_var.set(
            self.i18n.text(
                "paint.palette_usage_enabled"
                if self._palette_usage_focus_enabled
                else "paint.palette_usage_disabled"
            )
        )
        if self._renderer is not None and not self._close_requested:
            self._schedule_render(immediate=True)

    def _update_palette_usage_summary(self) -> None:
        variable = getattr(self, "palette_usage_summary_var", None)
        if variable is None:
            return
        if not bool(getattr(self, "_palette_usage_focus_enabled", False)):
            variable.set(self.i18n.text("paint.palette_usage_off"))
            return
        indices = getattr(self, "effective_indices", None)
        if not isinstance(indices, np.ndarray) or indices.shape != (
            len(self.level.faces),
        ):
            variable.set(self.i18n.text("paint.palette_usage_wait"))
            return
        state = int(self._palette_usage_focus_state)
        adaptive_store = getattr(self, "_hotfix_tree_store", None)
        if not isinstance(adaptive_store, dict):
            adaptive_store = getattr(
                self.prepared,
                "_hotfix_subtriangle_paint",
                None,
            )
        if not isinstance(adaptive_store, dict):
            adaptive_store = None
        adaptive_revision = int(
            getattr(
                getattr(self, "_hotfix_tree_owner", self.prepared),
                "_hotfix_tree_revision",
                0,
            )
        )
        try:
            usage = analyze_palette_usage(
                self.level,
                indices,
                state,
                self.settings.geometry.height_mm,
                part_id=self.active_part_id,
                adaptive_trees=adaptive_store,
            )
        except (TypeError, ValueError):
            variable.set(self.i18n.text("paint.palette_usage_wait"))
            return
        names = getattr(self, "state_names", STATE_NAMES)
        recipe = names[state] if 0 <= state < len(names) else f"State {state + 1}"
        active_palette = self._active_palette()
        try:
            selected_weights = palette_state_base_weights(
                state,
                active_palette.mix_ratios_b,
                active_palette.secondary_mix_ratios_b,
                active_palette.output_mix_ratios_b,
                surface_shell_enabled=bool(
                    getattr(active_palette, "surface_shell_enabled", False)
                ),
                physical_hex=active_palette.physical_hex,
            )
            selected_share = " + ".join(
                f"F{index + 1} {weight * 100.0:.0f}%"
                for index, weight in enumerate(selected_weights)
                if weight > 0.0
            )
            contribution_key = (
                id(indices),
                int(self.active_part_id),
                float(self.settings.geometry.height_mm),
                tuple(int(value) for value in active_palette.mix_ratios_b),
                tuple(
                    int(value)
                    for value in active_palette.secondary_mix_ratios_b
                ),
                (
                    None
                    if active_palette.output_mix_ratios_b is None
                    else tuple(
                        int(value)
                        for value in active_palette.output_mix_ratios_b
                    )
                ),
                bool(
                    getattr(
                        active_palette,
                        "surface_shell_enabled",
                        False,
                    )
                ),
                tuple(str(value) for value in active_palette.physical_hex),
                id(adaptive_store),
                adaptive_revision,
            )
            if contribution_key != self._palette_usage_contribution_cache_key:
                self._palette_usage_contribution_cache = (
                    estimate_base_filament_contributions(
                        self.level,
                        indices,
                        self.settings.geometry.height_mm,
                        active_palette.mix_ratios_b,
                        active_palette.secondary_mix_ratios_b,
                        active_palette.output_mix_ratios_b,
                        surface_shell_enabled=bool(
                            getattr(
                                active_palette,
                                "surface_shell_enabled",
                                False,
                            )
                        ),
                        physical_hex=active_palette.physical_hex,
                        part_id=self.active_part_id,
                        adaptive_trees=adaptive_store,
                    )
                )
                self._palette_usage_contribution_cache_key = contribution_key
            contributions = self._palette_usage_contribution_cache or (
                0.0,
                0.0,
                0.0,
                0.0,
            )
            base_estimate = " / ".join(
                f"F{index + 1} {weight * 100.0:.1f}%"
                for index, weight in enumerate(contributions)
            )
        except (TypeError, ValueError):
            selected_share = "-"
            base_estimate = "-"
        if usage.adaptive_root_count:
            mode_note = self.i18n.text(
                "paint.palette_usage_adaptive",
                roots=usage.selected_adaptive_root_count,
                selected_leaves=usage.selected_adaptive_leaf_count,
                total_roots=usage.adaptive_root_count,
                total_leaves=usage.adaptive_leaf_count,
            )
        else:
            mode_note = self.i18n.text("paint.palette_usage_face_level")
        part_name = (
            self.part_names[self.active_part_id]
            if 0 <= self.active_part_id < len(self.part_names)
            else "?"
        )
        variable.set(
            self.i18n.text(
                (
                    "paint.palette_usage_summary_shell"
                    if bool(
                        getattr(
                            active_palette,
                            "surface_shell_enabled",
                            False,
                        )
                    )
                    else "paint.palette_usage_summary"
                ),
                part=part_name,
                state=state + 1,
                recipe=recipe,
                faces=usage.face_count,
                face_percent=usage.face_fraction * 100.0,
                area=usage.area_mm2,
                area_percent=usage.area_fraction * 100.0,
                selected_share=selected_share,
                base_estimate=base_estimate,
                mode_note=mode_note,
            )
        )

    def _placeholder(self, size: tuple[int, int], text: str) -> Image.Image:
        image = Image.new("RGB", size, (9, 12, 17))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (10, 10, size[0] - 10, size[1] - 10), radius=12, outline=(44, 54, 68), width=2
        )
        draw.text((size[0] // 2, size[1] // 2), text, fill=(145, 157, 175), anchor="mm")
        return image

    def _target_image_with_crease_overlay(self) -> Image.Image | None:
        image = self.target_image
        face_ids = self.face_ids
        overlay_var = getattr(self, "crease_overlay_var", None)
        if (
            image is None
            or face_ids is None
            or overlay_var is None
            or not bool(overlay_var.get())
        ):
            return image
        angle = float(self.edge_angle_var.get())
        key = (id(image), id(face_ids), round(angle, 3))
        if key == self._crease_overlay_cache_key and self._crease_overlay_cache is not None:
            return self._crease_overlay_cache
        # PaintSession already owns normalized face normals for its edge
        # guards.  Reusing that immutable array avoids allocating a temporary
        # (face_count x 3 x 3) triangle tensor on the Tk thread for large OBJs.
        normals = getattr(getattr(self, "_session", None), "normals", None)
        if normals is None:
            return image
        result = overlay_visible_creases(image, face_ids, normals, angle)
        self._crease_overlay_cache_key = key
        self._crease_overlay_cache = result
        return result

    def _on_crease_overlay_changed(self, _event=None) -> None:
        try:
            angle = max(1.0, min(180.0, float(self.edge_angle_var.get())))
        except (TypeError, ValueError, tk.TclError):
            angle = 45.0
        self.edge_angle_var.set(angle)
        self._crease_overlay_cache_key = None
        self._crease_overlay_cache = None
        if hasattr(self, "canvas"):
            self._draw_canvas()
        state_key = "paint.crease_overlay_on" if bool(self.crease_overlay_var.get()) else "paint.crease_overlay_off"
        self.status_var.set(self.i18n.text(state_key, angle=angle))

    def _draw_canvas(self) -> None:
        self._canvas_after = None
        if not self.canvas.winfo_exists():
            return
        reference_var = getattr(self, "reference_visible_var", None)
        reference_visible = bool(
            self.reference_image is not None
            and (
                reference_var.get()
                if reference_var is not None
                else True
            )
        )
        layout = compute_manual_canvas_layout(
            self.canvas.winfo_width(),
            self.canvas.winfo_height(),
            reference_visible,
        )
        width = int(layout["width"])
        height = int(layout["height"])
        margin = int(layout["margin"])
        title_height = int(layout["title_height"])
        panel_height = int(layout["panel_height"])
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, width, height, fill="#090C11", outline="")
        panels: list[tuple[str, str, Image.Image, int, int]] = []
        reference_layout = layout["reference"]
        if reference_visible and reference_layout is not None:
            reference_x, reference_width = reference_layout
            panels.append(
                (
                    "reference",
                    self.i18n.text("paint.reference_panel"),
                    self.reference_image,
                    int(reference_x),
                    int(reference_width),
                )
            )
        target_x, target_width = layout["target"]
        panels.append(
                (
                    "target",
                    self.i18n.text("paint.target_panel"),
                    self._target_image_with_decal_preview(
                        self._target_image_with_crease_overlay()
                    )
                    or self._placeholder(
                    (int(target_width), panel_height),
                    self.i18n.text("paint.preparing_mesh"),
                ),
                int(target_x),
                int(target_width),
            )
        )
        self.canvas_images.clear()
        self.reference_mapping = None
        self.target_mapping = None
        for role, label, source, x, panel_width in panels:
            self.canvas.create_text(
                x + panel_width // 2,
                margin + title_height // 2,
                text=label,
                fill=TEXT,
                font=("Yu Gothic UI", 10, "bold"),
            )
            top = margin + title_height
            contained = ImageOps.contain(
                source.convert("RGB"), (panel_width, panel_height), method=Image.Resampling.LANCZOS
            )
            px = x + (panel_width - contained.width) // 2
            py = top + (panel_height - contained.height) // 2
            photo = ImageTk.PhotoImage(contained)
            self.canvas_images.append(photo)
            self.canvas.create_image(px, py, image=photo, anchor="nw")
            self.canvas.create_rectangle(
                x, top, x + panel_width, top + panel_height, outline="#273242", width=1
            )
            if role == "reference" and self.reference_image is not None:
                self.reference_mapping = (
                    px,
                    py,
                    contained.width,
                    contained.height,
                    self.reference_image.width,
                    self.reference_image.height,
                )
            elif role == "target" and self.target_image is not None:
                self.target_mapping = (
                    px,
                    py,
                    contained.width,
                    contained.height,
                    self.target_image.width,
                    self.target_image.height,
                )
        self._draw_boundary_diagnostic_markers()
        self._draw_decal_placement_guide()

    def _draw_decal_placement_guide(self) -> None:
        """Draw the editable decal footprint and centre over the 3D panel."""

        if str(getattr(self, "_ribbon_selected", "")) != "decal":
            return
        image = getattr(self, "_decal_image", None)
        mapping = getattr(self, "target_mapping", None)
        if image is None or mapping is None:
            return
        left, top, display_width, display_height, render_width, render_height = mapping
        if min(display_width, display_height, render_width, render_height) <= 0:
            return
        try:
            transform = self._decal_transform((render_height, render_width))
        except (DecalProjectionError, TypeError, ValueError, tk.TclError):
            return
        half_width = float(transform.width_px) * 0.5
        half_height = half_width * float(image.height) / max(1.0, float(image.width))
        radians = math.radians(float(transform.rotation_degrees) % 360.0)
        cosine, sine = math.cos(radians), math.sin(radians)
        scale_x = float(display_width) / float(render_width)
        scale_y = float(display_height) / float(render_height)
        center_x, center_y = transform.center_xy
        corners: list[float] = []
        for local_x, local_y in (
            (-half_width, -half_height),
            (half_width, -half_height),
            (half_width, half_height),
            (-half_width, half_height),
        ):
            dx = cosine * local_x - sine * local_y
            dy = sine * local_x + cosine * local_y
            corners.extend(
                (
                    float(left) + (center_x + dx) * scale_x,
                    float(top) + (center_y + dy) * scale_y,
                )
            )
        exact_preview = self._decal_preview_is_current()
        color = SUCCESS if exact_preview else WARNING
        dash_options = {} if exact_preview else {"dash": (6, 4)}
        self.canvas.create_polygon(
            *corners,
            fill="",
            outline=color,
            width=2,
            tags="decal-guide",
            **dash_options,
        )
        canvas_center_x = float(left) + center_x * scale_x
        canvas_center_y = float(top) + center_y * scale_y
        radius = 7
        self.canvas.create_oval(
            canvas_center_x - radius,
            canvas_center_y - radius,
            canvas_center_x + radius,
            canvas_center_y + radius,
            outline=color,
            width=2,
            tags="decal-guide",
        )
        self.canvas.create_line(
            canvas_center_x - radius - 4,
            canvas_center_y,
            canvas_center_x + radius + 4,
            canvas_center_y,
            fill=color,
            width=2,
            tags="decal-guide",
        )
        self.canvas.create_line(
            canvas_center_x,
            canvas_center_y - radius - 4,
            canvas_center_x,
            canvas_center_y + radius + 4,
            fill=color,
            width=2,
            tags="decal-guide",
        )

    def _draw_boundary_diagnostic_markers(self) -> None:
        if not self._diagnostic_enabled or self.target_mapping is None:
            return
        records = dict(self.prepared.assembly or {}).get(
            "boundary_diagnostics", []
        )
        if not isinstance(records, (list, tuple)) or not records:
            return
        left, top, width, height, render_width, render_height = (
            self.target_mapping
        )
        try:
            mvp, _state, _pixels_per_unit = renderer_module._orbit_camera_mvp(
                np.asarray(self.level.vertices_unit, dtype=np.float64),
                (int(render_width), int(render_height)),
                self.camera,
            )
        except Exception:
            return
        problem_number = 0
        for item in records:
            if not isinstance(item, dict):
                continue
            adjacent = self._validated_diagnostic_face_ids(
                item.get("adjacent_final_face_ids", []),
                len(self.level.faces),
            )
            if len(adjacent):
                center = np.asarray(self.level.vertices_unit, dtype=np.float64)[
                    np.asarray(self.level.faces, dtype=np.int64)[adjacent]
                ].mean(axis=(0, 1))
            else:
                try:
                    center = np.asarray(
                        item.get("center_unit"), dtype=np.float64
                    )
                except (TypeError, ValueError):
                    continue
            if center.shape != (3,) or not np.isfinite(center).all():
                continue
            clip = np.asarray(mvp, dtype=np.float64) @ np.append(center, 1.0)
            if not np.isfinite(clip).all() or abs(float(clip[3])) <= 1e-12:
                continue
            ndc = clip[:3] / clip[3]
            if not (-1.15 <= ndc[0] <= 1.15 and -1.15 <= ndc[1] <= 1.15):
                continue
            canvas_x = left + (float(ndc[0]) * 0.5 + 0.5) * width
            canvas_y = top + (0.5 - float(ndc[1]) * 0.5) * height
            matched = bool(item.get("matched"))
            if matched:
                radius = 5
                color = "#FFB000"
                line_width = 2
            else:
                problem_number += 1
                radius = 12
                color = "#FF1744"
                line_width = 3
            self.canvas.create_oval(
                canvas_x - radius,
                canvas_y - radius,
                canvas_x + radius,
                canvas_y + radius,
                outline=color,
                width=line_width,
            )
            self.canvas.create_line(
                canvas_x - radius - 4,
                canvas_y,
                canvas_x + radius + 4,
                canvas_y,
                fill=color,
                width=1,
            )
            self.canvas.create_line(
                canvas_x,
                canvas_y - radius - 4,
                canvas_x,
                canvas_y + radius + 4,
                fill=color,
                width=1,
            )
            if not matched:
                self.canvas.create_text(
                    canvas_x + radius + 5,
                    canvas_y - radius - 2,
                    text=f"!{problem_number}",
                    fill="#FFFFFF",
                    anchor="sw",
                    font=("Yu Gothic UI", 10, "bold"),
                )

    def _on_canvas_configure(self, _event=None) -> None:
        if self._canvas_after:
            self.window.after_cancel(self._canvas_after)
        self._canvas_after = self.window.after(70, self._draw_canvas)

    def _point_inside(self, event: tk.Event, mapping: tuple[int, int, int, int, int, int] | None) -> bool:
        if mapping is None:
            return False
        x, y, width, height, _ow, _oh = mapping
        return x <= event.x < x + width and y <= event.y < y + height

    def _face_at_any_part(self, x: int, y: int) -> int:
        """Return the visible face under the pointer without active-part filtering."""

        mapping = self.target_mapping
        ids = self.face_ids
        if self._render_dirty or mapping is None or ids is None:
            return -1
        left, top, width, height, render_width, render_height = mapping
        if not (left <= x < left + width and top <= y < top + height):
            return -1
        rx = min(render_width - 1, max(0, int((x - left) * render_width / width)))
        ry = min(render_height - 1, max(0, int((y - top) * render_height / height)))
        face = int(ids[ry, rx])
        if face < 0 or face >= len(self.level.faces):
            return -1
        return face

    def _face_at(self, x: int, y: int) -> int:
        face = self._face_at_any_part(x, y)
        if face < 0:
            return -1
        part_ids = np.asarray(self.level.face_part_ids)
        if (
            part_ids.shape == (len(self.level.faces),)
            and int(part_ids[face]) != self.active_part_id
        ):
            return -1
        return face

    def _on_target_double_click(self, event: tk.Event) -> str | None:
        """Switch the active edit part by double-clicking its rendered surface."""

        if str(getattr(self, "_ribbon_selected", "")) == "decal":
            return "break"
        if self._close_requested:
            return "break"
        if self._reject_during_topology_change():
            return "break"
        if not self._point_inside(event, self.target_mapping):
            return None
        face = self._face_at_any_part(event.x, event.y)
        if face < 0:
            self.status_var.set(self.i18n.text("paint.double_click_no_part"))
            return "break"
        part_ids = np.asarray(self.level.face_part_ids)
        if part_ids.shape == (len(self.level.faces),):
            part_id = int(part_ids[face])
        else:
            part_id = 0
        if not 0 <= part_id < len(self.part_labels):
            self.status_var.set(self.i18n.text("paint.double_click_no_part"))
            return "break"

        # A first click may have started a brush/lasso gesture.  Inactive parts
        # cannot be painted by the session mask, and cancelling here ensures a
        # double-click used for navigation never becomes a split operation.
        self._drag_mode = None
        self._stroke_faces.clear()
        self._lasso_points.clear()
        self.canvas.delete("split-lasso")
        if part_id == self.active_part_id:
            self.status_var.set(
                self.i18n.text(
                    "paint.double_click_already_active",
                    part=self.part_names[part_id],
                )
            )
            return "break"

        self.part_target_var.set(self.part_labels[part_id])
        self._on_editor_part_selected()
        self.status_var.set(
            self.i18n.text(
                "paint.double_click_selected",
                part=self.part_names[part_id],
            )
        )
        return "break"

    def _sample_reference(self, event: tk.Event) -> None:
        sampled = self._sample_reference_rgb(event)
        if sampled is None:
            return
        rgb8 = np.clip(np.rint(sampled * 255.0), 0, 255).astype(np.uint8)
        target_lab = srgb_to_lab((rgb8[None, :] / 255.0))[0]
        palette_lab = srgb_to_lab(self.palette_rgb)
        active_palette = self._active_palette()
        enabled = _effective_paint_enabled_states(active_palette)
        candidates = np.flatnonzero(enabled)
        if len(candidates) == 0:
            candidates = np.arange(
                4
                if getattr(active_palette, "color_mode", None)
                == COLOR_MODE_FLAT_FOUR
                else PALETTE_STATE_COUNT
            )
        distances = np.linalg.norm(palette_lab[candidates] - target_lab, axis=1)
        nearest = int(candidates[int(np.argmin(distances))])
        self.paint_state_var.set(nearest)
        update_label = getattr(self, "_update_selected_palette_label", None)
        if callable(update_label):
            update_label()

        try:
            if getattr(active_palette, "color_mode", None) == COLOR_MODE_FLAT_FOUR:
                raise LookupError("flat mode has no mixed recipe")
            recipes = find_best_mix_recipes(
                rgb8,
                active_palette.physical_hex,
                top_n=606,
            )
            mixed = next(
                (item for item in recipes if item.ratio_b_percent not in (0, 100)),
                recipes[0],
            )
            a = SHORT_NAMES[mixed.color_a_index]
            b = SHORT_NAMES[mixed.color_b_index]
            recipe_text = (
                f"理論上の最良混色 {a}:{b} = {mixed.ratio_a_percent}:{mixed.ratio_b_percent} "
                f"(予測 {mixed.predicted_hex}, ΔE {mixed.delta_e76:.2f})"
            )
        except Exception:
            recipe_text = ""
        self.sample_var.set(
            f"スポイト {rgb8_to_hex(rgb8)} → 現在の印刷色 {nearest + 1} "
            f"{self.state_names[nearest]} "
            f"(ΔE {float(distances.min()):.2f})。{recipe_text}"
        )
        self.status_var.set("元画像から塗る色を選びました")

    def _adaptive_state_at(self, face: int, event: tk.Event | None) -> int | None:
        """Resolve the visible adaptive leaf under *event*, when one exists."""

        mapping = getattr(self, "target_mapping", None)
        if event is None or mapping is None:
            return None
        store = getattr(self, "_hotfix_tree_store", None)
        if not isinstance(store, dict):
            prepared = getattr(self, "prepared", None)
            store = getattr(prepared, "_hotfix_subtriangle_paint", None)
        node = store.get(int(face)) if isinstance(store, dict) else None
        if node is None:
            return None
        try:
            import smooth_paint as adaptive_paint

            point = np.asarray(
                canvas_point_on_face(
                    self.level,
                    int(face),
                    (int(event.x), int(event.y)),
                    mapping,
                    camera=self.camera,
                ),
                dtype=np.float64,
            )
            root = np.asarray(self.level.vertices_unit, dtype=np.float64)[
                np.asarray(self.level.faces[int(face)], dtype=np.int64)
            ]

            def contains(triangle: np.ndarray) -> bool:
                a, b, c = np.asarray(triangle, dtype=np.float64)
                ab = b - a
                ac = c - a
                ap = point - a
                d00 = float(np.dot(ab, ab))
                d01 = float(np.dot(ab, ac))
                d11 = float(np.dot(ac, ac))
                d20 = float(np.dot(ap, ab))
                d21 = float(np.dot(ap, ac))
                denominator = d00 * d11 - d01 * d01
                if abs(denominator) <= 1e-18:
                    return False
                v = (d11 * d20 - d01 * d21) / denominator
                w = (d00 * d21 - d01 * d20) / denominator
                u = 1.0 - v - w
                return min(u, v, w) >= -1e-6

            for leaf in adaptive_paint.iter_leaf_triangles(node, root):
                if contains(leaf.vertices):
                    return int(leaf.state)
        except Exception:
            return None
        return None

    def _sample_current_3d_state(
        self,
        face: int,
        event: tk.Event | None = None,
    ) -> bool:
        """Select the state that is currently painted on the clicked face."""

        indices = self.effective_indices
        if indices is None or not 0 <= int(face) < len(indices):
            self.status_var.set(self.i18n.text("paint.eyedropper_wait"))
            return False
        adaptive_state = self._adaptive_state_at(int(face), event)
        session = getattr(self, "_session", None)
        sample = getattr(session, "sample_painted_state", None)
        if callable(sample):
            state = int(sample(int(face), adaptive_state=adaptive_state))
        else:
            state = int(indices[int(face)])
        active_palette = _editor_palette_if_available(self)
        if active_palette is not None:
            palette_rgb = getattr(self, "palette_rgb", None)
            state = _effective_paint_state(
                active_palette,
                state,
                palette_rgb=(
                    None
                    if palette_rgb is None
                    else np.asarray(palette_rgb, dtype=np.float64)
                ),
            )
        self.paint_state_var.set(state)
        self._update_selected_palette_label()
        names = getattr(self, "state_names", STATE_NAMES)
        name = names[state] if 0 <= state < len(names) else str(state + 1)
        self.status_var.set(
            self.i18n.text("paint.eyedropper_picked", state=state + 1, name=name)
        )
        return True

    def _event_pen_pressure(self, event: tk.Event) -> float:
        """Read optional Windows Ink pressure without requiring the hotfix."""

        bridge = getattr(self, "_hotfix_pen_pressure_bridge", None)
        pressure_for_event = getattr(bridge, "pressure_for_event", None)
        if callable(pressure_for_event):
            try:
                pressure = pressure_for_event(event)
                if pressure is not None and math.isfinite(float(pressure)):
                    return max(0.0, min(1.0, float(pressure)))
            except Exception:
                pass
        return 1.0

    def _place_decal_at_canvas_point(self, x: int, y: int) -> bool:
        mapping = getattr(self, "target_mapping", None)
        if mapping is None:
            return False
        left, top, width, height, _render_width, _render_height = mapping
        if width <= 0 or height <= 0:
            return False
        x_percent = (float(x) - float(left)) * 100.0 / float(width)
        y_percent = (float(y) - float(top)) * 100.0 / float(height)
        # A drag is clamped to the visible viewport. Spinboxes intentionally
        # retain a wider range so an image can also be parked partly off-canvas.
        x_percent = max(0.0, min(100.0, x_percent))
        y_percent = max(0.0, min(100.0, y_percent))
        self._decal_syncing_controls = True
        try:
            self.decal_x_var.set(round(x_percent, 2))
            self.decal_y_var.set(round(y_percent, 2))
        finally:
            self._decal_syncing_controls = False
        self._mark_decal_preview_stale("decal.changed")
        return True

    def _on_decal_left_press(self, event: tk.Event) -> bool:
        if str(getattr(self, "_ribbon_selected", "")) != "decal":
            return False
        if getattr(self, "_decal_image", None) is None:
            self._set_decal_status("decal.ready")
            return True
        if bool(getattr(self, "_decal_apply_running", False)):
            return True
        if not self._point_inside(event, self.target_mapping):
            self._set_decal_status("decal.view_wait")
            return True
        self._drag_mode = "decal"
        self._place_decal_at_canvas_point(event.x, event.y)
        return True

    def _on_left_press(self, event: tk.Event) -> None:
        if self._close_requested:
            return
        if PaintEditorWindow._reject_during_topology_change(self):
            return
        decal_handler = getattr(self, "_on_decal_left_press", None)
        if callable(decal_handler) and decal_handler(event):
            return
        tool = self.tool_var.get()
        if tool != "airbrush":
            self._airbrush_started_at = None
        if tool not in ("joint", "eyedropper") and self._point_inside(event, self.reference_mapping):
            self._sample_reference(event)
            return
        if tool == "lasso":
            if self._job_running:
                self.status_var.set("前の処理が終わるまでお待ちください")
                return
            if not self._point_inside(event, self.target_mapping):
                self.status_var.set(self.i18n.text("separate.draw_prompt"))
                return
            self._drag_mode = "lasso"
            self._lasso_points = [(event.x, event.y)]
            self.canvas.delete("split-lasso")
            self.status_var.set(self.i18n.text("separate.trace_prompt"))
            return
        face = self._face_at(event.x, event.y)
        if tool == "joint":
            availability = self._sync_joint_guidance()
            if not availability.available:
                self.status_var.set(
                    self.i18n.text(
                        availability.message_key,
                        **availability.message_values,
                    )
                )
                self._show_joint_guidance()
                return
            if face < 0 or self.target_mapping is None:
                self.status_var.set(self.i18n.text("joint.click_prompt"))
                return
            try:
                center_unit = canvas_point_on_face(
                    self.level,
                    face,
                    (event.x, event.y),
                    self.target_mapping,
                    camera=self.camera,
                )
            except JointProjectionError as exc:
                self.status_var.set(str(exc))
                return
            self._queue_manual_joint_target(face, center_unit)
            return
        if (event.state & 0x0008) and face >= 0:
            sampler = getattr(self, "_sample_current_3d_state", None)
            if callable(sampler):
                sampler(face, event)
            elif self.effective_indices is not None:
                state = int(self.effective_indices[face])
                active_palette = _editor_palette_if_available(self)
                if active_palette is not None:
                    state = _effective_paint_state(active_palette, state)
                self.paint_state_var.set(state)
                update_label = getattr(self, "_update_selected_palette_label", None)
                if callable(update_label):
                    update_label()
            return
        if tool == "orbit":
            self._drag_mode = "orbit"
            self._drag_last = (event.x, event.y)
            return
        if face < 0:
            self.status_var.set(
                self.i18n.text(
                    "paint.eyedropper_prompt"
                    if tool == "eyedropper"
                    else "paint.view_wait"
                )
            )
            return
        if tool == "eyedropper":
            if self._sample_current_3d_state(face, event):
                return_tool = self._eyedropper_return_tool
                if return_tool == "eyedropper":
                    return_tool = "brush"
                self.tool_var.set(return_tool)
                self._on_tool_changed()
            return
        if tool in ("brush", "erase"):
            self._drag_mode = "stroke"
            self._stroke_faces = [face]
            self._stroke_last_xy = (event.x, event.y)
            self._stroke_erase = tool == "erase" or bool(event.state & 0x0001)
            self.status_var.set("ブラシ線を入力中…マウスを離すと反映します")
            return
        if tool in ("airbrush", "smudge"):
            self._drag_mode = f"{tool}-stroke"
            if tool == "airbrush":
                self._airbrush_started_at = time.monotonic()
            self._stroke_faces = [face]
            self._stroke_pressures = [self._event_pen_pressure(event)]
            self._stroke_last_xy = (event.x, event.y)
            self._stroke_erase = False
            self.status_var.set(
                self.i18n.text(
                    "paint.airbrush_drawing"
                    if tool == "airbrush"
                    else "paint.smudge_drawing"
                )
            )
            return
        if tool == "fill":
            self._queue_fill(face)
        elif tool == "smooth":
            self._queue_smooth(face)

    def _on_left_motion(self, event: tk.Event) -> None:
        if PaintEditorWindow._reject_during_topology_change(self):
            return
        if self._drag_mode == "decal":
            self._place_decal_at_canvas_point(event.x, event.y)
        elif self._drag_mode == "orbit":
            self._orbit_to(event.x, event.y)
        elif self._drag_mode in ("stroke", "airbrush-stroke", "smudge-stroke"):
            if self._drag_mode in ("airbrush-stroke", "smudge-stroke"):
                self._stroke_pressures.append(self._event_pen_pressure(event))
            dx = event.x - self._stroke_last_xy[0]
            dy = event.y - self._stroke_last_xy[1]
            distance = math.hypot(dx, dy)
            if distance >= 2.0:
                spacing = max(1.5, min(4.0, self._brush_radius_pixels() * 0.45))
                steps = max(1, int(math.ceil(distance / spacing)))
                start_x, start_y = self._stroke_last_xy
                for step in range(1, steps + 1):
                    amount = step / steps
                    sample_x = int(round(start_x + dx * amount))
                    sample_y = int(round(start_y + dy * amount))
                    face = self._face_at(sample_x, sample_y)
                    if face >= 0 and (not self._stroke_faces or face != self._stroke_faces[-1]):
                        self._stroke_faces.append(face)
                self._stroke_last_xy = (event.x, event.y)
        elif self._drag_mode == "lasso":
            previous = self._lasso_points[-1]
            if math.hypot(event.x - previous[0], event.y - previous[1]) >= 2.0:
                self._lasso_points.append((event.x, event.y))
                flattened = [value for point in self._lasso_points for value in point]
                self.canvas.delete("split-lasso")
                self.canvas.create_line(
                    *flattened,
                    fill=WARNING,
                    width=3,
                    smooth=True,
                    tags="split-lasso",
                )

    def _commit_active_stroke(self) -> None:
        if self._drag_mode == "stroke" and self._stroke_faces:
            self._queue_stroke(self._stroke_faces.copy(), self._stroke_erase)
        elif self._drag_mode == "airbrush-stroke" and self._stroke_faces:
            pressure = max(getattr(self, "_stroke_pressures", ()), default=1.0)
            started_at = self._airbrush_started_at
            duration = (
                max(0.0, time.monotonic() - float(started_at))
                if started_at is not None
                else 0.0
            )
            self._queue_airbrush(
                self._stroke_faces.copy(),
                pressure=pressure,
                dab_count=airbrush_hold_dab_count(duration),
            )
        elif self._drag_mode == "smudge-stroke" and self._stroke_faces:
            pressure = max(getattr(self, "_stroke_pressures", ()), default=1.0)
            self._queue_smudge(self._stroke_faces.copy(), pressure=pressure)
        self._drag_mode = None
        self._airbrush_started_at = None
        self._stroke_faces.clear()
        pressures = getattr(self, "_stroke_pressures", None)
        if pressures is not None:
            pressures.clear()

    def _on_left_release(self, _event: tk.Event) -> None:
        if PaintEditorWindow._reject_during_topology_change(self):
            self._drag_mode = None
            self._airbrush_started_at = None
            self._stroke_faces.clear()
            pressures = getattr(self, "_stroke_pressures", None)
            if pressures is not None:
                pressures.clear()
            return
        if self._drag_mode == "decal":
            self._drag_mode = None
            if self._decal_exact_frame_available():
                self._preview_decal()
            return
        if self._drag_mode == "lasso":
            points = self._lasso_points.copy()
            self._drag_mode = None
            self._lasso_points.clear()
            self.canvas.delete("split-lasso")
            self._queue_lasso_plan(points)
            return
        self._commit_active_stroke()

    def _on_right_press(self, event: tk.Event) -> None:
        if self._close_requested:
            return
        self._drag_mode = "orbit"
        self._lasso_points.clear()
        self.canvas.delete("split-lasso")
        self._drag_last = (event.x, event.y)

    def _on_right_motion(self, event: tk.Event) -> None:
        if self._drag_mode == "orbit":
            self._orbit_to(event.x, event.y)

    def _on_right_release(self, _event: tk.Event) -> None:
        self._drag_mode = None

    def _orbit_to(self, x: int, y: int) -> None:
        dx = x - self._drag_last[0]
        dy = y - self._drag_last[1]
        self._drag_last = (x, y)
        orbit_var = getattr(self, "orbit_inverted_var", None)
        direction = -1.0 if orbit_var is not None and orbit_var.get() else 1.0
        self.camera = CameraState(
            yaw_degrees=self.camera.yaw_degrees + dx * 0.38 * direction,
            pitch_degrees=max(
                -79.0,
                min(
                    79.0,
                    self.camera.pitch_degrees - dy * 0.32 * direction,
                ),
            ),
            zoom=self.camera.zoom,
        )
        self._schedule_render()

    def _on_mousewheel(self, event: tk.Event) -> None:
        if self._close_requested:
            return
        factor = MANUAL_ZOOM_STEP if event.delta > 0 else 1.0 / MANUAL_ZOOM_STEP
        self._zoom_by(factor)

    def _on_pointer_motion(self, event: tk.Event) -> None:
        self.canvas.delete("paint-cursor")
        if self.tool_var.get() == "lasso":
            return
        if self.tool_var.get() not in (
            "brush",
            "airbrush",
            "smudge",
            "smooth",
            "erase",
        ):
            return
        if self._face_at(event.x, event.y) < 0 or self.target_mapping is None:
            return
        radius_px = self._brush_radius_pixels()
        self.canvas.create_oval(
            event.x - radius_px,
            event.y - radius_px,
            event.x + radius_px,
            event.y + radius_px,
            outline=ACCENT,
            width=2,
            tags="paint-cursor",
        )

    def _on_tool_changed(self, *, ensure_ribbon: bool = False) -> None:
        tool_variable = getattr(self, "tool_var", None)
        if tool_variable is None:
            return
        tool = tool_variable.get()
        previous_tool = getattr(self, "_last_tool_mode", None)
        if tool == "eyedropper" and previous_tool not in (None, "eyedropper"):
            self._eyedropper_return_tool = previous_tool
        self._last_tool_mode = tool
        if ensure_ribbon:
            self._select_ribbon_for_tool(tool)
        panel = getattr(self, "joint_panel", None)
        if panel is not None:
            if tool == "joint":
                panel.grid()
            else:
                panel.grid_remove()
        if hasattr(self, "canvas"):
            self.canvas.configure(
                cursor=(
                    "crosshair"
                    if tool in ("lasso", "joint", "eyedropper")
                    else "arrow"
                )
            )
        if tool == "eyedropper" and previous_tool != "eyedropper":
            self.status_var.set(self.i18n.text("paint.eyedropper_prompt"))
        elif tool == "airbrush" and previous_tool != "airbrush":
            self.status_var.set(self.i18n.text("paint.airbrush_prompt"))
        elif tool == "smudge" and previous_tool != "smudge":
            self.status_var.set(self.i18n.text("paint.smudge_prompt"))
        if tool == "joint" and previous_tool != "joint":
            availability = self._sync_joint_guidance()
            self.status_var.set(
                self.i18n.text(
                    (
                        "joint.click_prompt"
                        if availability.available
                        else availability.message_key
                    ),
                    **(
                        {}
                        if availability.available
                        else availability.message_values
                    ),
                )
            )

    def _queue_lasso_plan(self, canvas_points: list[tuple[int, int]]) -> None:
        mapping = self.target_mapping
        face_ids = self.face_ids
        if self._render_dirty or mapping is None or face_ids is None:
            self.status_var.set(self.i18n.text("separate.wait_for_view"))
            return
        try:
            render_points = canvas_polygon_to_render(mapping, canvas_points)
        except FreehandSplitError as exc:
            self.status_var.set(exc.localized(self.i18n))
            self._on_tool_changed()
            return
        level = self.level
        active_part_id = self.active_part_id
        captured_ids = np.asarray(face_ids, dtype=np.int32).copy()

        def work():
            plan = plan_lasso_component_split(
                level,
                captured_ids,
                render_points,
                active_part_id,
            )
            return {"confirm_lasso_split": plan}

        self.status_var.set(self.i18n.text("separate.checking"))
        self.canvas.configure(cursor="watch")
        self._submit("split_plan", work)

    def _confirm_lasso_split(self, plan: LassoSplitPlan) -> None:
        if not messagebox.askyesno(
            self.i18n.text("separate.confirm_title"),
            self.i18n.text(
                "separate.confirm_message",
                source=plan.source_part_name,
                faces=len(plan.selected_faces),
                new_name=plan.new_part_name,
                coverage=plan.selected_visible_coverage * 100.0,
            ),
            parent=self.window,
        ):
            self.status_var.set(self.i18n.text("separate.cancelled"))
            return

        pick_transparent = bool(self.pick_transparent_var.get())

        def work():
            if self._session is None:
                raise RuntimeError("色修正の準備中です")
            effective_before = self._session.effective_indices().copy()
            previous_overrides = self._session.overrides.copy()
            new_level = apply_lasso_split(self.level, plan)
            apply_level_partition_to_prepared(
                self.prepared,
                new_level,
                record={
                    "type": "screen_lasso_closed_component",
                    "source_part_id": int(plan.source_part_id),
                    "source_part_key": plan.source_part_key,
                    "new_part_id": int(len(new_level.part_keys) - 1),
                    "new_part_key": plan.new_part_key,
                    "new_part_name": plan.new_part_name,
                    "selected_faces": int(len(plan.selected_faces)),
                    "selected_components": list(plan.selected_components),
                    "visible_coverage": float(plan.selected_visible_coverage),
                    "preserved_face_order": True,
                },
            )
            self.level = new_level
            self.part_keys = tuple(new_level.part_keys)
            self.part_names = tuple(new_level.part_names)
            self.part_labels = tuple(
                f"{index + 1}: {name}"
                for index, name in enumerate(self.part_names)
            )
            self._part_visibility_modes = np.append(
                self._part_visibility_modes,
                np.asarray([PART_VISIBLE], dtype=np.uint8),
            ).astype(np.uint8, copy=False)
            inherit_explicit_part_palette(
                self.settings,
                plan.source_part_key,
                plan.new_part_key,
            )
            self._auto_colors = recolor_level_parts(
                self.level,
                self.settings.geometry.height_mm,
                self.settings.tone,
                self.settings.palette,
                self.settings.part_palettes,
            )
            new_auto = np.asarray(self._auto_colors.palette_indices, dtype=np.int8)
            preserve_auto = (previous_overrides < 0) & (new_auto != effective_before)
            previous_overrides[preserve_auto] = effective_before[preserve_auto]
            self._session.set_auto_indices(new_auto)
            self._session.overrides[:] = previous_overrides
            self._session.set_allowed_faces(self._active_face_mask())
            self._display_colors = apply_palette_overrides_parts(
                self.level,
                self.settings.geometry.height_mm,
                self.settings.palette,
                self.settings.part_palettes,
                self._auto_colors,
                self._session.overrides,
            )
            if self._renderer is not None:
                self._renderer.set_face_visibility(
                    self._face_visibility_modes(),
                    pick_transparent=pick_transparent,
                )
            snapshot = self._worker_snapshot(
                None,
                f"{plan.new_part_name} を追加しました",
                len(plan.selected_faces),
            )
            snapshot["part_structure"] = {
                "part_count": len(self.part_keys),
                "new_part_name": plan.new_part_name,
            }
            return snapshot

        self.status_var.set("色を保持したまま新しいパーツへ分離しています…")
        self.canvas.configure(cursor="watch")
        self._submit("part_split", work)

    def _brush_radius_pixels(self) -> float:
        if self.target_mapping is None or self._render_pixels_per_unit is None:
            return 3.0
        _left, _top, _width, display_height, _render_width, render_height = (
            self.target_mapping
        )
        radius_unit = float(self.brush_radius_var.get()) / max(
            float(self.settings.geometry.height_mm), 1e-6
        )
        display_scale = display_height / max(float(render_height), 1.0)
        return max(
            2.0,
            radius_unit * self._render_pixels_per_unit * display_scale,
        )

    def _reset_view(self) -> None:
        self.camera = CameraState()
        self._update_zoom_status()
        self._schedule_render(immediate=True)

    def _update_zoom_status(self) -> None:
        variable = getattr(self, "zoom_status_var", None)
        if variable is None:
            return
        zoom = float(getattr(getattr(self, "camera", None), "zoom", 1.0))
        variable.set(f"{zoom * 100.0:.0f}%")

    def _set_zoom(self, zoom: float, *, immediate: bool = False) -> None:
        clean = max(MANUAL_ZOOM_MIN, min(MANUAL_ZOOM_MAX, float(zoom)))
        if abs(clean - float(self.camera.zoom)) < 1e-9:
            self._update_zoom_status()
            return
        self.camera = replace(self.camera, zoom=clean)
        self._update_zoom_status()
        self._schedule_render(immediate=immediate)

    def _zoom_by(self, factor: float) -> None:
        self._set_zoom(float(self.camera.zoom) * float(factor))

    def _schedule_render(self, *, immediate: bool = False) -> None:
        if self._close_requested:
            return
        self._render_dirty = True
        self._mark_decal_preview_stale("decal.view_wait", view_change=True)
        if self._render_after:
            self.window.after_cancel(self._render_after)
        self._render_after = self.window.after(1 if immediate else 28, self._request_render)

    def _request_render(self) -> None:
        self._render_after = None
        if self._job_running:
            self._pending_render = True
            return
        camera = self.camera

        def work():
            if self._renderer is None or self._display_colors is None:
                return None
            self._renderer.set_palette_usage_focus(
                (
                    int(self._palette_usage_focus_state)
                    if self._palette_usage_focus_enabled
                    else None
                ),
                part_id=int(self.active_part_id),
            )
            frame = self._renderer.render(
                self._diagnostic_render_colors(),
                camera=camera,
                render_source=False,
                render_target=True,
                render_face_ids=True,
            )
            return camera, frame

        self._submit("render", work)

    def _worker_install_prepared(
        self,
        prepared: PreparedGeometry,
        overrides: np.ndarray,
        message: str,
        *,
        pick_transparent: bool,
        preserve_adaptive: bool,
    ) -> dict[str, object]:
        """Replace topology and recreate all worker-owned paint/GPU state."""

        values = np.asarray(overrides, dtype=np.int8)
        if values.shape != (len(prepared.final.faces),):
            raise ManualJointError("ジョイント後の手修正面数が一致しません")
        state_names = (
            "prepared",
            "level",
            "part_keys",
            "part_names",
            "part_labels",
            "active_part_id",
            "_part_visibility_modes",
            "initial_overrides",
            "target_image",
            "face_ids",
            "effective_indices",
            "_render_dirty",
            "_renderer",
            "_session",
            "_auto_colors",
            "_display_colors",
            "_view_appearance",
            "_hotfix_tree_store",
            "_hotfix_tree_owner",
            "_hotfix_overlay_cache",
            "_hotfix_pending_feedback",
            "_hotfix_active_feedback",
            "_hotfix_smooth_points",
            "_hotfix_smooth_capture",
            "_hotfix_pick_camera",
            "_rotation_hotfix_force_final",
        )
        old_state = {
            name: (hasattr(self, name), getattr(self, name, None))
            for name in state_names
        }
        old_renderer = self._renderer
        self._renderer = None

        try:
            self.prepared = prepared
            self.level = prepared.final
            self.part_keys = tuple(self.level.part_keys) or ("__whole_model__",)
            self.part_names = tuple(self.level.part_names) or ("OBJ全体",)
            self.part_labels = tuple(
                f"{index + 1}: {name}"
                for index, name in enumerate(self.part_names)
            )
            self.active_part_id = min(
                max(0, int(self.active_part_id)), len(self.part_labels) - 1
            )
            if len(self._part_visibility_modes) != len(self.part_labels):
                previous = np.asarray(self._part_visibility_modes, dtype=np.uint8)
                modes = np.full(len(self.part_labels), PART_VISIBLE, dtype=np.uint8)
                count = min(len(previous), len(modes))
                modes[:count] = previous[:count]
                self._part_visibility_modes = modes
            self.initial_overrides = values.copy()
            self.target_image = None
            self.face_ids = None
            self.effective_indices = None
            self._render_dirty = True

            # The adaptive-paint adapter registers renderer-level weak
            # contexts.  The old renderer and session stay alive until the new
            # renderer has produced its first exact frame, so any failure can
            # restore a completely usable editor.
            reset_context = getattr(self, "_reset_adaptive_geometry_context", None)
            if callable(reset_context):
                reset_context(prepared, preserve=bool(preserve_adaptive))
            snapshot = self._worker_initialize()
            new_renderer = self._renderer
            if new_renderer is None or self._display_colors is None:
                raise ManualJointError("ジョイント後の3D表示を再構築できません")
            face_modes = self._face_visibility_modes()
            new_renderer.set_face_visibility(
                face_modes,
                pick_transparent=bool(pick_transparent),
            )
            if bool(np.any(face_modes != PART_VISIBLE)):
                snapshot["frame"] = new_renderer.render(
                    self._diagnostic_render_colors(),
                    camera=self.camera,
                    render_source=False,
                    render_target=True,
                    render_face_ids=True,
                )
        except Exception:
            failed_renderer = self._renderer
            if failed_renderer is not None and failed_renderer is not old_renderer:
                try:
                    failed_renderer.close()
                except Exception:
                    pass
            for name, (existed, old_value) in old_state.items():
                if existed:
                    setattr(self, name, old_value)
                elif hasattr(self, name):
                    delattr(self, name)
            raise

        if old_renderer is not None and old_renderer is not self._renderer:
            try:
                old_renderer.close()
            except Exception:
                # The successfully rendered replacement remains authoritative;
                # an old-context cleanup warning must not roll topology back.
                pass
        snapshot["message"] = str(message)
        snapshot["topology_replaced"] = True
        return snapshot

    def _worker_initialize(self) -> dict[str, object]:
        self._auto_colors = recolor_level_parts(
            self.level,
            self.settings.geometry.height_mm,
            self.settings.tone,
            self.settings.palette,
            self.settings.part_palettes,
        )
        self._session = PaintSession(
            self.level,
            self.settings.geometry.height_mm,
            self._auto_colors.palette_indices,
            overrides=self.initial_overrides,
        )
        self._session.set_allowed_faces(self._active_face_mask())
        self._display_colors = apply_palette_overrides_parts(
            self.level,
            self.settings.geometry.height_mm,
            self.settings.palette,
            self.settings.part_palettes,
            self._auto_colors,
            self._session.overrides,
        )
        self._view_appearance = resolve_view_appearance(
            self.view_theme_mode,
            self._display_colors.target_face_rgb,
        )
        self._renderer = InteractiveMeshRenderer(
            self.level,
            size=RENDER_SIZE,
            background=self._view_appearance.background,
        )
        self._renderer.set_active_part(
            self.active_part_id,
            color=self._view_appearance.active_part_accent,
        )
        self._renderer.set_palette_usage_focus(
            (
                int(self._palette_usage_focus_state)
                if self._palette_usage_focus_enabled
                else None
            ),
            part_id=int(self.active_part_id),
        )
        frame = self._renderer.render(
            self._diagnostic_render_colors(),
            camera=self.camera,
            render_source=False,
            render_target=True,
            render_face_ids=True,
        )
        message = "色修正の準備ができました"
        if self._diagnostic_enabled:
            matched, unmatched = self._boundary_diagnostic_counts()
            message = self.i18n.text(
                "paint.boundary_diagnostics_status",
                matched=matched,
                unmatched=unmatched,
            )
        return self._worker_snapshot(frame, message)

    def _worker_snapshot(self, frame, message: str, changed: int = 0) -> dict[str, object]:
        if self._session is None:
            raise RuntimeError("色修正セッションがありません")
        return {
            "frame": frame,
            "overrides": self._session.overrides.copy(),
            "effective": self._session.effective_indices(),
            "modified": self._session.modified_face_count,
            "can_undo": self._session.can_undo,
            "can_redo": self._session.can_redo,
            "changed": int(changed),
            "message": message,
        }

    def _worker_refresh_after_edit(self, message: str, changed: int) -> dict[str, object]:
        if self._session is None or self._auto_colors is None:
            raise RuntimeError("色修正の準備が完了していません")
        self._display_colors = apply_palette_overrides_parts(
            self.level,
            self.settings.geometry.height_mm,
            self.settings.palette,
            self.settings.part_palettes,
            self._auto_colors,
            self._session.overrides,
        )
        # A single full render is requested on the Tk thread after the edit.
        # This keeps the image and face-ID map on exactly the same camera frame.
        return self._worker_snapshot(None, message, changed)

    def _queue_stroke(self, seeds: list[int], erase: bool) -> None:
        radius = float(self.brush_radius_var.get())
        protect = bool(self.edge_guard_var.get())
        angle = float(self.edge_angle_var.get())
        state = _effective_paint_state(
            self._active_palette(), int(self.paint_state_var.get())
        )
        ordered_seeds = [int(seed) for seed in seeds if seed >= 0]
        visible_mask = self._visible_face_mask_for_stroke()
        visibility = (
            {"visible_face_mask": visible_mask}
            if visible_mask is not None
            else {}
        )

        def work():
            if self._session is None:
                raise RuntimeError("色修正の準備中です")
            self._session.begin_stroke("自動色へ戻す" if erase else "ブラシ")
            try:
                for seed in ordered_seeds:
                    if erase:
                        self._session.erase_brush(
                            seed,
                            radius,
                            protect_sharp_edges=protect,
                            max_angle_degrees=angle,
                            **visibility,
                        )
                    else:
                        self._session.paint_brush(
                            seed,
                            state,
                            radius,
                            protect_sharp_edges=protect,
                            max_angle_degrees=angle,
                            **visibility,
                        )
                changed = self._session.end_stroke()
            except Exception:
                self._session.cancel_stroke()
                raise
            label = "自動色へ戻しました" if erase else f"色 {state + 1} でブラシ修正しました"
            return self._worker_refresh_after_edit(label, changed)

        self._submit("edit", work)

    def _queue_airbrush(
        self,
        seeds: list[int],
        *,
        pressure: float = 1.0,
        dab_count: int = 1,
    ) -> None:
        radius = float(self.brush_radius_var.get())
        strength = float(self.airbrush_strength_var.get()) / 100.0
        protect = bool(self.edge_guard_var.get())
        angle = float(self.edge_angle_var.get())
        active_palette = self._active_palette()
        state = _effective_paint_state(
            active_palette, int(self.paint_state_var.get())
        )
        enabled = _effective_paint_enabled_states(active_palette)
        # Disabled/mixed states stay intentionally available for manual paint.
        # Permit the explicitly selected target without widening the set of
        # incidental Airbrush candidates.
        if 0 <= state < len(enabled):
            enabled[state] = True
        unique_seeds = list(dict.fromkeys(int(seed) for seed in seeds if seed >= 0))
        visible_mask = self._visible_face_mask_for_stroke()
        visibility = (
            {"visible_face_mask": visible_mask}
            if visible_mask is not None
            else {}
        )

        def work():
            if self._session is None:
                raise RuntimeError(self.i18n.text("paint.preparing_mesh"))
            changed = self._session.airbrush_stroke(
                unique_seeds,
                state,
                radius,
                strength,
                pressure=pressure,
                dab_count=max(1, int(dab_count)),
                enabled_states=enabled,
                protect_sharp_edges=protect,
                max_angle_degrees=angle,
                **visibility,
            )
            return self._worker_refresh_after_edit(
                self.i18n.text("paint.airbrush_applied", count=len(changed)),
                len(changed),
            )

        self._submit("edit", work)

    def _queue_smudge(self, seeds: list[int], *, pressure: float = 1.0) -> None:
        radius = float(self.brush_radius_var.get())
        strength = float(self.smudge_strength_var.get()) / 100.0
        protect = bool(self.edge_guard_var.get())
        angle = float(self.edge_angle_var.get())
        enabled = _effective_paint_enabled_states(self._active_palette())
        palette_rgb = np.asarray(self.palette_rgb, dtype=np.float64).copy()
        # Preserve the ordered path, including later visits to the same face.
        # Back-and-forth motion carries colour directionally in the core.
        ordered_seeds = [int(seed) for seed in seeds if seed >= 0]
        visible_mask = self._visible_face_mask_for_stroke()
        visibility = (
            {"visible_face_mask": visible_mask}
            if visible_mask is not None
            else {}
        )

        def work():
            if self._session is None:
                raise RuntimeError(self.i18n.text("paint.preparing_mesh"))
            changed_faces = self._session.smudge_stroke(
                ordered_seeds,
                radius,
                strength,
                pressure=pressure,
                enabled_states=enabled,
                palette_rgb=palette_rgb,
                protect_sharp_edges=protect,
                max_angle_degrees=angle,
                **visibility,
            )
            return self._worker_refresh_after_edit(
                self.i18n.text("paint.smudge_applied", count=len(changed_faces)),
                len(changed_faces),
            )

        self._submit("edit", work)

    def _queue_fill(self, seed: int) -> None:
        active_palette = self._active_palette()
        state = _effective_paint_state(
            active_palette, int(self.paint_state_var.get())
        )
        connectivity_state_map = (
            _effective_paint_state_map(
                active_palette,
                palette_rgb=np.asarray(self.palette_rgb, dtype=np.float64),
            )
            if getattr(active_palette, "color_mode", None)
            == COLOR_MODE_FLAT_FOUR
            else None
        )
        fill_options = (
            {"connectivity_state_map": connectivity_state_map}
            if connectivity_state_map is not None
            else {}
        )

        def work():
            if self._session is None:
                raise RuntimeError("色修正の準備中です")
            changed = self._session.fill(
                seed,
                state,
                **fill_options,
            )
            return self._worker_refresh_after_edit(
                f"同じ色でつながった領域を色 {state + 1} へ変更しました", len(changed)
            )

        self._submit("edit", work)

    def _queue_smooth(self, seed: int) -> None:
        radius = float(self.brush_radius_var.get())
        protect = bool(self.edge_guard_var.get())
        angle = float(self.edge_angle_var.get())
        passes = int(self.smooth_passes_var.get())
        visible_mask = self._visible_face_mask_for_stroke()
        visibility = (
            {"visible_face_mask": visible_mask}
            if visible_mask is not None
            else {}
        )

        def work():
            if self._session is None:
                raise RuntimeError("色修正の準備中です")
            changed = self._session.smooth_boundary(
                seed,
                radius,
                iterations=passes,
                protect_sharp_edges=protect,
                max_angle_degrees=angle,
                **visibility,
            )
            return self._worker_refresh_after_edit(
                "三角形単位の突出・くぼみをならしました", len(changed)
            )

        self._submit("edit", work)

    def _undo(self) -> None:
        def work():
            if self._session is None:
                raise RuntimeError("色修正の準備中です")
            command = self._session.undo()
            changed = command.face_count if command else 0
            return self._worker_refresh_after_edit("1操作戻しました", changed)

        self._submit("edit", work)

    def _redo(self) -> None:
        def work():
            if self._session is None:
                raise RuntimeError("色修正の準備中です")
            command = self._session.redo()
            changed = command.face_count if command else 0
            return self._worker_refresh_after_edit("1操作やり直しました", changed)

        self._submit("edit", work)

    def _clear_all(self) -> None:
        if not messagebox.askyesno(
            "手修正を解除",
            "ブラシ・塗りつぶし・境界ならしによる修正をすべて解除しますか？\n自動変換色へ戻ります。",
            parent=self.window,
        ):
            return
        def work():
            if self._session is None:
                raise RuntimeError("色修正の準備中です")
            changed = self._session.clear_overrides()
            return self._worker_refresh_after_edit("すべて自動変換色へ戻しました", len(changed))

        self._submit("edit", work)

    def _submit(
        self,
        kind: str,
        function: Callable[[], object],
        *,
        accepted_before_close: bool = False,
    ) -> None:
        if bool(getattr(self, "_topology_change_pending", False)) and kind not in {
            "joint_plan",
            "manual_joint",
            "manual_joint_undo",
            "render",
            "close",
        }:
            self.status_var.set(self.i18n.text("joint.wait"))
            return
        if self._closing or (
            self._close_requested and kind != "close" and not accepted_before_close
        ):
            return
        if self._job_running:
            if kind == "render":
                self._pending_render = True
            else:
                self._queued_actions.append((kind, function))
                self.status_var.set("前の処理後に続けて反映します…")
            return
        self._job_running = True

        def runner() -> None:
            try:
                self._work_queue.put((kind + "_done", function()))
            except Exception as exc:
                self._work_queue.put(
                    ("job_error", (kind, exc, traceback.format_exc()))
                )

        self._executor.submit(runner)

    def _poll_worker(self) -> None:
        if self._closing:
            return
        try:
            while True:
                kind, payload = self._work_queue.get_nowait()
                self._job_running = False
                if kind == "job_error":
                    failed_kind, exc, details = payload
                    if failed_kind in {
                        "joint_plan",
                        "manual_joint",
                        "manual_joint_undo",
                    }:
                        self._set_topology_change_pending(False)
                    localized_error = (
                        exc.localized(self.i18n)
                        if isinstance(exc, FreehandSplitError)
                        else str(exc)
                    )
                    self.status_var.set(
                        self.i18n.text(
                            "paint.error_status", message=localized_error
                        )
                    )
                    if not self._close_requested:
                        if isinstance(exc, FreehandSplitError):
                            messagebox.showwarning(
                                self.i18n.text("separate.cannot_split"),
                                localized_error,
                                parent=self.window,
                            )
                        elif isinstance(exc, ManualJointError):
                            messagebox.showwarning(
                                self.i18n.text("joint.confirm_title"),
                                localized_error,
                                parent=self.window,
                            )
                        else:
                            messagebox.showerror(
                                self.i18n.text("dialog.paint_apply_error"),
                                f"{localized_error}\n\n{details[-1600:]}",
                                parent=self.window,
                            )
                    if failed_kind == "close":
                        self._finalize_close()
                        return
                    self._on_tool_changed()
                elif kind == "render_done":
                    rendered_camera, frame = payload if payload is not None else (None, None)
                    if frame is not None and rendered_camera == self.camera:
                        if frame.target is not None:
                            self.target_image = frame.target
                        if frame.face_ids is not None:
                            self.face_ids = frame.face_ids
                        self._render_pixels_per_unit = frame.pixels_per_unit
                        self._render_dirty = False
                        if frame.face_ids is not None:
                            self._accept_decal_exact_frame(
                                frame.face_ids, rendered_camera
                            )
                        self._draw_canvas()
                    elif not self._close_requested:
                        self._pending_render = True
                elif kind == "close_done":
                    snapshot = None
                    cleanup_warning = None
                    if isinstance(payload, dict) and "snapshot" in payload:
                        snapshot = payload.get("snapshot")
                        cleanup_warning = payload.get("cleanup_warning")
                    else:
                        snapshot = payload
                    if snapshot is not None:
                        self._consume_snapshot(snapshot)
                    if cleanup_warning:
                        self._cleanup_warning = str(cleanup_warning)
                        try:
                            messagebox.showwarning(
                                "3D表示の終了警告",
                                "色修正は保持しましたが、3D表示の終了処理で警告が発生しました。\n\n"
                                + self._cleanup_warning,
                                parent=self.window,
                            )
                        except tk.TclError:
                            pass
                    self._finalize_close()
                    return
                else:
                    self._consume_snapshot(payload)
                self._start_next_pending()
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.window.after(30, self._poll_worker)

    def _consume_snapshot(self, value: object) -> None:
        if not isinstance(value, dict):
            return
        if self._consume_decal_payload(value):
            return
        split_plan = value.get("confirm_lasso_split")
        if isinstance(split_plan, LassoSplitPlan):
            self._on_tool_changed()
            self._confirm_lasso_split(split_plan)
            return
        joint_target = value.get("confirm_manual_joint")
        joint_settings = value.get("manual_joint_settings")
        if isinstance(joint_target, ManualJointTarget) and isinstance(
            joint_settings, ManualJointSettings
        ):
            self._on_tool_changed()
            self._confirm_manual_joint(joint_target, joint_settings)
            return
        frame = value.get("frame")
        if frame is not None and frame.camera == self.camera:
            if frame.target is not None:
                self.target_image = frame.target
            if frame.face_ids is not None:
                self.face_ids = frame.face_ids
            self._render_pixels_per_unit = frame.pixels_per_unit
            self._render_dirty = False
            if frame.face_ids is not None:
                self._accept_decal_exact_frame(frame.face_ids, frame.camera)
        effective = value.get("effective")
        if isinstance(effective, np.ndarray):
            self.effective_indices = effective
            self._update_palette_usage_summary()
        overrides = value.get("overrides")
        geometry_changed = value.get("geometry_changed")
        if isinstance(geometry_changed, dict):
            self._set_topology_change_pending(False)
            record = geometry_changed.get("record")
            self._manual_joint_record = (
                dict(record) if isinstance(record, dict) else None
            )
            if isinstance(overrides, np.ndarray) and self.on_geometry_changed is not None:
                self.on_geometry_changed(
                    self.prepared,
                    np.asarray(overrides, dtype=np.int8).copy(),
                    (
                        None
                        if self._manual_joint_record is None
                        else dict(self._manual_joint_record)
                    ),
                )
        undo_state = value.get("joint_undo_state")
        if (
            isinstance(undo_state, tuple)
            and len(undo_state) == 3
            and isinstance(undo_state[0], PreparedGeometry)
            and isinstance(undo_state[1], np.ndarray)
        ):
            self._manual_joint_undo_state = undo_state
            joint_undo_button = getattr(self, "joint_undo_button", None)
            if joint_undo_button is not None:
                joint_undo_button.configure(state="normal")
        if bool(value.get("joint_undo_completed")):
            self._manual_joint_undo_state = None
            joint_undo_button = getattr(self, "joint_undo_button", None)
            if joint_undo_button is not None:
                joint_undo_button.configure(state="disabled")
        modified = int(value.get("modified", 0))
        self.edit_count_var.set(f"手修正 {modified:,}面")
        changed = int(value.get("changed", 0))
        if changed > 0 and not bool(value.get("decal_apply_result")):
            self._mark_decal_preview_stale("decal.changed")
        message = str(value.get("message", "更新しました"))
        self.status_var.set(f"{message}（{changed:,}面）" if changed else message)
        self._draw_canvas()
        if isinstance(overrides, np.ndarray) and not bool(
            value.get("_suppress_override_notification")
        ):
            self.on_overrides_changed(overrides)
        if value.get("part_structure") is not None:
            self._sync_part_selector_controls()
            self.part_target_var.set(self.part_labels[self.active_part_id])
            self._sync_active_part_identity()
            self._sync_part_visibility_controls()
            if frame is None:
                self._invalidate_visibility_pick_map()
            self._refresh_palette_buttons()
            if self.on_parts_changed is not None:
                self.on_parts_changed()
            self._sync_joint_guidance()
        elif bool(value.get("topology_replaced")):
            self._load_boundary_diagnostics(self.prepared)
            self._sync_boundary_diagnostic_controls()
            self._sync_part_selector_controls()
            self.part_target_var.set(self.part_labels[self.active_part_id])
            self._sync_active_part_identity()
            self._sync_part_visibility_controls()
            if frame is None:
                self._invalidate_visibility_pick_map()
            self._refresh_palette_buttons()
            self._sync_joint_guidance()
        elif isinstance(geometry_changed, dict):
            self._sync_joint_guidance()
        self._on_tool_changed()
        if frame is None and not self._close_requested:
            self._schedule_render(immediate=True)

    def _start_next_pending(self) -> None:
        if self._job_running or self._closing:
            return
        if self._queued_actions:
            kind, function = self._queued_actions.popleft()
            self._submit(kind, function, accepted_before_close=True)
            return
        if self._pending_render:
            self._pending_render = False
            self._request_render()

    def close(self, after_close: Callable[[], None] | None = None) -> None:
        if after_close is not None:
            self._after_close_callbacks.append(after_close)
        if self._closing or self._close_requested:
            return
        # WM_CLOSE can arrive before ButtonRelease. Commit that visible brush
        # gesture first so the queued close drains it like every other edit.
        self._commit_active_stroke()
        # Tone controls use a short debounce while dragging.  A quick click on
        # Cel/Noir followed immediately by Save & Close must not discard the
        # last visible selection when the pending callback is cancelled.
        if not self._flush_pending_tone_change():
            return
        decal_cancel = getattr(self, "_decal_cancel_event", None)
        if decal_cancel is not None:
            decal_cancel.set()
        decal_preview_cancel = getattr(self, "_decal_preview_cancel_event", None)
        if decal_preview_cancel is not None:
            decal_preview_cancel.set()
        self._decal_auto_repreview = False
        self._decal_preview_pending = False
        self._decal_request_serial = int(getattr(self, "_decal_request_serial", 0)) + 1
        self._clear_decal_preview_artifacts()
        self._decal_preview_stale = True
        self._close_requested = True
        self._pending_render = False
        self._drag_mode = None
        self.status_var.set("最後の色修正を確定して閉じています…")
        self.canvas.configure(cursor="watch")
        if self._render_after:
            try:
                self.window.after_cancel(self._render_after)
            except tk.TclError:
                pass
            self._render_after = None

        def work():
            snapshot = (
                self._worker_snapshot(None, "最後の色修正を確定しました")
                if self._session is not None
                else None
            )
            cleanup_warning = None
            try:
                if self._renderer is not None:
                    self._renderer.close()
            except Exception as exc:
                cleanup_warning = f"{type(exc).__name__}: {exc}"
            finally:
                self._renderer = None
            return {
                "snapshot": snapshot,
                "cleanup_warning": cleanup_warning,
            }

        # This cleanup is queued after every already accepted edit, so the
        # final parent notification cannot lose the last stroke.
        self._submit("close", work)

    def _finalize_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        for after_id in (
            self._render_after,
            self._canvas_after,
            self._tone_change_after,
            self._initial_tool_windows_after,
            self._tool_restore_after,
            self._tool_restore_verify_after,
            self._decal_auto_repreview_after,
            self._decal_preview_restart_after,
        ):
            if after_id:
                try:
                    self.window.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._tone_change_after = None
        self._initial_tool_windows_after = None
        self._tool_restore_after = None
        self._tool_restore_verify_after = None
        self._decal_auto_repreview_after = None
        self._decal_preview_restart_after = None
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        for attribute in (
            "palette_tool_window",
            "parts_tool_window",
            "help_tool_window",
        ):
            tool_window = getattr(self, attribute, None)
            if tool_window is not None:
                try:
                    if tool_window.winfo_exists():
                        tool_window.destroy()
                except tk.TclError:
                    pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        self._executor.shutdown(wait=False, cancel_futures=False)
        if self.on_closed is not None:
            self.on_closed()
        callbacks = self._after_close_callbacks[:]
        self._after_close_callbacks.clear()
        for callback in callbacks:
            callback()


__all__ = ["PaintEditorWindow"]
