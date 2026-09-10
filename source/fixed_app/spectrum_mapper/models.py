from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .filament_materials import (
    DEFAULT_FILAMENT_MATERIAL,
    normalize_filament_material,
)
from .mixer import (
    DEFAULT_PALETTE_STATE_COUNT,
    PALETTE_STATE_COUNT,
    coerce_palette_state_count,
    normalize_hex,
    validate_black_free_slots,
    validate_output_mix_ratios_b,
)


ProgressCallback = Callable[[str, float, str], None]


COLOR_MODE_FULL_SPECTRUM = "full_spectrum"
COLOR_MODE_FLAT_FOUR = "flat_four"
# New sessions and headless conversions start with the direct four-filament
# workflow.  Keep ``PaletteSettings.color_mode`` on the legacy Full Spectrum
# value below so projects that predate the explicit colour-mode field retain
# their original meaning when they are loaded.
DEFAULT_NEW_COLOR_MODE = COLOR_MODE_FLAT_FOUR
SUPPORTED_COLOR_MODES = (
    COLOR_MODE_FULL_SPECTRUM,
    COLOR_MODE_FLAT_FOUR,
)


def normalize_color_mode(value: object) -> str:
    """Return one stable palette-assignment mode for project persistence."""

    normalized = str(value).strip().lower()
    if normalized not in SUPPORTED_COLOR_MODES:
        raise ValueError(
            "color_mode must be 'full_spectrum' or 'flat_four'"
        )
    return normalized


# Snapmaker Orca 2.3.5 can dereference a virtual mixed-state ID as a physical
# tool when a grouped Cycle recipe reaches slicing.  Keep the persisted field
# for backward-compatible project loading, but production output must remain
# on the proven Ratio path until Orca provides a safe grouped-wall contract.
SURFACE_SHELL_OUTPUT_ENABLED = False


@dataclass
class GeometrySettings:
    height_mm: float = 180.0
    target_faces: int = 450_000
    preview_faces: int = 80_000
    # Old projects and the CLI retain the established simplification path.
    # The GUI explicitly turns this off only when the user selects a new OBJ.
    adjust_face_count: bool = True
    up_axis: str = "Y"
    min_component_faces: int = 25
    mirror_x: bool = False
    preserve_parts: bool = True
    solidify_parts: bool = False
    # Joint position is user-selected in Manual Editing.  Keep the legacy
    # automatic generator available only when an older project explicitly
    # saved it as enabled; a new model must never start with it selected.
    auto_joints: bool = False
    joint_width_mm: float = 6.0
    joint_height_mm: float = 4.0
    joint_depth_mm: float = 6.0
    joint_clearance_mm: float = 0.25
    joint_min_seam_span_mm: float = 8.0
    split_enabled: bool = False
    split_axis: str = "Z"
    split_position_percent: float = 50.0
    split_target_part: int = 0
    export_individual_parts: bool = True
    repair_unmatched_boundaries: bool = False


@dataclass
class ToneSettings:
    black_point: float = 0.0
    white_point: float = 0.875
    gamma: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    pink_protection: bool = False
    pink_threshold: float = 0.03
    smoothing: bool = True
    smoothing_max_area_mm2: float = 0.04
    smoothing_delta_e_slack: float = 3.0
    # Experimental printable illustration shading.  These fields are kept in
    # ToneSettings so projects and exact-cache reloads reproduce the same
    # palette assignment without destructively rewriting source vertex colour.
    illustration_mode: str = "off"
    illustration_strength: float = 0.78
    illustration_bands: int = 4
    illustration_light: str = "front_left"
    # ``illustration_strength`` is the amount of the stylised result blended
    # over the source colour.  Keep the actual light controls independent:
    # intensity changes the brightness of each established light band, while
    # range changes how far the key light wraps around the model.
    illustration_light_intensity: float = 1.0
    illustration_light_range: float = 0.4
    # Experimental source-detail preservation.  Zero deliberately reproduces
    # all existing projects; non-zero values are currently enabled only by
    # controlled tests/internal settings until a reviewed UI is added.
    illustration_detail_strength: float = 0.0
    # Separate opt-in trial: constrain every lifted Strong-Cel band to a small
    # coherent area budget.  Zero is exact legacy/detail behavior; an enabled
    # value is the requested whole-model surface fraction (5-12 percent).
    illustration_selective_highlight_fraction: float = 0.0
    # Which geometric evidence may move the darker face beside an edge down
    # one existing printable band.  The default is the exact policy used by
    # the first selective-highlight implementation, so older project output
    # remains unchanged.
    illustration_contour_policy: str = "outer_crease_fold"

    def __post_init__(self) -> None:
        mode = str(self.illustration_mode).strip().lower()
        light = str(self.illustration_light).strip().lower()
        strength = float(self.illustration_strength)
        light_intensity = float(self.illustration_light_intensity)
        light_range = float(self.illustration_light_range)
        detail_strength = float(self.illustration_detail_strength)
        selective_fraction = float(
            self.illustration_selective_highlight_fraction
        )
        contour_policy = str(self.illustration_contour_policy).strip().lower()
        if mode not in {"off", "cel", "cel_strong", "noir"}:
            raise ValueError(f"unsupported illustration mode: {self.illustration_mode}")
        if light not in {
            "front_left",
            "top",
            "front_right",
            "left",
            "front",
            "right",
            "bottom_left",
            "bottom",
            "bottom_right",
        }:
            raise ValueError(
                f"unsupported illustration light: {self.illustration_light}"
            )
        if not bool(np.isfinite(strength)) or not 0.0 <= strength <= 1.0:
            raise ValueError("illustration strength must be in 0..1")
        if (
            not bool(np.isfinite(light_intensity))
            or not 0.0 <= light_intensity <= 1.5
        ):
            raise ValueError("illustration light intensity must be in 0..1.5")
        if not bool(np.isfinite(light_range)) or not 0.0 <= light_range <= 1.0:
            raise ValueError("illustration light range must be in 0..1")
        if (
            not bool(np.isfinite(detail_strength))
            or not 0.0 <= detail_strength <= 1.0
        ):
            raise ValueError("illustration detail strength must be in 0..1")
        if (
            not bool(np.isfinite(selective_fraction))
            or (
                selective_fraction != 0.0
                and not 0.05 <= selective_fraction <= 0.12
            )
        ):
            raise ValueError(
                "illustration selective highlight fraction must be 0 or in 0.05..0.12"
            )
        if contour_policy not in {
            "outer",
            "outer_crease",
            "outer_crease_fold",
        }:
            raise ValueError(
                "unsupported illustration contour policy: "
                f"{self.illustration_contour_policy}"
            )
        if (
            isinstance(self.illustration_bands, (bool, np.bool_))
            or int(self.illustration_bands) != self.illustration_bands
            or not 2 <= int(self.illustration_bands) <= 6
        ):
            raise ValueError("illustration bands must be an integer in 2..6")
        self.illustration_mode = mode
        self.illustration_strength = strength
        self.illustration_bands = int(self.illustration_bands)
        self.illustration_light = light
        self.illustration_light_intensity = light_intensity
        self.illustration_light_range = light_range
        self.illustration_detail_strength = detail_strength
        self.illustration_selective_highlight_fraction = selective_fraction
        self.illustration_contour_policy = contour_policy


@dataclass(frozen=True, slots=True)
class FilamentSnapshotRef:
    """Portable identity of one physical filament assigned to an F slot.

    A project must remain understandable when the optional filament database
    changes or is not installed.  For that reason this is a display snapshot,
    not only a database foreign key.  The 3MF uses the matching Generic
    PLA/ABS/PETG profile; these values document the intended real spool.
    """

    product_id: str
    brand: str
    series: str
    color_name: str
    matched_hex: str
    finish_class: str
    source: str
    material: str = DEFAULT_FILAMENT_MATERIAL
    source_url: str | None = None
    record_id: str | None = None
    measurement_id: str | None = None

    @classmethod
    def from_mapping(cls, value: object) -> "FilamentSnapshotRef | None":
        if not isinstance(value, dict):
            return None
        product_id = str(value.get("product_id", "")).strip()
        brand = str(value.get("brand", "")).strip()
        series = str(value.get("series", "")).strip()
        color_name = str(value.get("color_name", "")).strip()
        finish = str(value.get("finish_class", "")).strip()
        source = str(
            value.get("source", value.get("source_kind", ""))
        ).strip()
        def optional_text(name: str, maximum: int) -> str | None:
            raw = value.get(name)
            if raw is None:
                return None
            text = str(raw).strip()
            return text[:maximum] if text else None
        try:
            matched_hex = normalize_hex(
                str(value.get("matched_hex", value.get("hex", "")))
            )
        except ValueError:
            return None
        # Product ID is the stable identity.  Human-readable fields are kept
        # even when empty because some catalog rows legitimately omit series
        # or finish details.
        if not product_id:
            return None
        try:
            material = normalize_filament_material(
                value.get("material", DEFAULT_FILAMENT_MATERIAL)
            )
        except ValueError:
            return None
        return cls(
            product_id=product_id[:512],
            brand=brand[:240],
            series=series[:240],
            color_name=color_name[:240],
            matched_hex=matched_hex,
            finish_class=finish[:240],
            source=source[:80],
            material=material,
            source_url=optional_text("source_url", 2048),
            record_id=optional_text("record_id", 512),
            measurement_id=optional_text("measurement_id", 512),
        )

    @classmethod
    def from_product(cls, product: object) -> "FilamentSnapshotRef | None":
        """Build a snapshot from a DB product or candidate-match object."""

        def read(name: str, default: object = "") -> object:
            if isinstance(product, dict):
                return product.get(name, default)
            return getattr(product, name, default)

        product_id = str(read("product_id", "")).strip()
        record_id = str(read("record_id", "") or "").strip()
        measurement_id = str(read("measurement_id", "") or "").strip()
        # Nearest-match rows predate the product API.  Their linked catalog ID
        # is nevertheless the same stable identity used by FilamentProduct.
        if not product_id:
            if record_id:
                product_id = f"catalog:{record_id}"
            elif measurement_id:
                product_id = f"measurement:{measurement_id}"
        source = str(
            read("snapshot_source_kind", "") or read("source_kind", "")
        ).strip()
        return cls.from_mapping(
            {
                "product_id": product_id,
                "brand": read("brand", ""),
                "series": read("series", ""),
                "color_name": read("color_name", ""),
                "matched_hex": read("matched_hex", ""),
                "finish_class": read("finish_class", ""),
                "source": source,
                "material": read("material", DEFAULT_FILAMENT_MATERIAL),
                "source_url": read("source_url", None),
                "record_id": read("record_id", None),
                "measurement_id": read("measurement_id", None),
            }
        )

    @property
    def label(self) -> str:
        return " / ".join(
            value
            for value in (self.brand, self.series, self.color_name)
            if value
        ) or self.product_id


@dataclass
class PaletteSettings:
    # The U1 may mix four colours, but all four spools must use one polymer.
    # Projects written before this field existed migrate to PLA.
    material: str = DEFAULT_FILAMENT_MATERIAL
    palette_state_count: int = DEFAULT_PALETTE_STATE_COUNT
    physical_hex: list[str] = field(
        default_factory=lambda: ["#111111", "#FFFFFF", "#C0C0C0", "#FFCAE4"]
    )
    enabled_states: list[bool] = field(
        default_factory=lambda: [True] * PALETTE_STATE_COUNT
    )
    mix_hex_overrides: list[str | None] = field(default_factory=lambda: [None] * 6)
    mix_ratios_b: list[int] = field(default_factory=lambda: [33] * 6)
    secondary_mix_ratios_b: list[int] = field(
        default_factory=lambda: [67] * 6
    )
    # Optional print-only B percentages for all mixed states IDs 5..32.
    # Display RGB/Lab and stable paint IDs continue to use the two legacy
    # ratio fields above.  None preserves the established export path.
    output_mix_ratios_b: list[int] | None = None
    # Optional 32-colour snapshot used only for automatic state assignment.
    # The visible/output palette still comes from the current F1-F4 and mix
    # ratios.  This lets a user substitute real spools without making every
    # face jump to a different state ID; manual and adaptive paint already use
    # those stable IDs and therefore need no special migration.
    assignment_palette_hex: list[str] | None = None
    # Optional automatic-assignment policy.  Stable state IDs, printable
    # recipes, pure black and explicit manual paint remain unchanged.
    black_free_gradient_enabled: bool = False
    black_free_black_slot: int = 0
    black_free_red_slot: int = 2
    black_free_brown_slot: int = 3
    # Retained only for backward-compatible loading of short-lived experiment
    # projects.  __post_init__ migrates it to False while the unsafe grouped
    # Cycle serializer is production-disabled.
    surface_shell_enabled: bool = False
    # One portable product snapshot for each F1-F4 slot.  None means that the
    # colour was entered/picked/generated without selecting a catalog product.
    physical_filament_refs: list[FilamentSnapshotRef | None] = field(
        default_factory=lambda: [None] * 4
    )
    # Full Spectrum keeps the established mixed states.  Flat Four preserves
    # those recipes and stable IDs in the project, but automatic/manual output
    # is resolved through physical F1-F4 only.  This makes mode switching
    # reversible instead of destructively rewriting a user's palette.
    color_mode: str = COLOR_MODE_FULL_SPECTRUM

    def __post_init__(self) -> None:
        self.color_mode = normalize_color_mode(self.color_mode)
        self.material = normalize_filament_material(
            self.material, default=DEFAULT_FILAMENT_MATERIAL
        )
        if not isinstance(self.black_free_gradient_enabled, (bool, np.bool_)):
            raise ValueError("black_free_gradient_enabled must be a boolean")
        self.black_free_gradient_enabled = bool(
            self.black_free_gradient_enabled
        )
        (
            self.black_free_black_slot,
            self.black_free_red_slot,
            self.black_free_brown_slot,
        ) = validate_black_free_slots(
            self.black_free_black_slot,
            self.black_free_red_slot,
            self.black_free_brown_slot,
        )
        if not isinstance(self.surface_shell_enabled, (bool, np.bool_)):
            raise ValueError("surface_shell_enabled must be a boolean")
        self.surface_shell_enabled = bool(
            self.surface_shell_enabled and SURFACE_SHELL_OUTPUT_ENABLED
        )
        self.palette_state_count = coerce_palette_state_count(
            self.palette_state_count
        )
        # v1.7 and earlier stored ten booleans.  States 1..10 retain the exact
        # same meaning.  Added shades start disabled for an old project so
        # opening it cannot silently change existing automatic assignments;
        # the v1.8 UI offers one explicit switch to enable all of them.
        enabled = list(self.enabled_states)
        if len(enabled) == 10:
            enabled += [False] * (PALETTE_STATE_COUNT - 10)
        elif len(enabled) > PALETTE_STATE_COUNT:
            # Ignore states beyond this build's supported 32 IDs without
            # shifting any of the stable palette IDs that remain.
            enabled = enabled[:PALETTE_STATE_COUNT]
        elif len(enabled) < PALETTE_STATE_COUNT:
            enabled += [False] * (PALETTE_STATE_COUNT - len(enabled))
        # States outside the selected 16/24/32 export palette are retained in
        # the project but cannot participate in automatic assignment.
        for index in range(self.palette_state_count, PALETTE_STATE_COUNT):
            enabled[index] = False
        self.enabled_states = enabled

        output_ratios = validate_output_mix_ratios_b(
            self.output_mix_ratios_b
        )
        self.output_mix_ratios_b = (
            None if output_ratios is None else list(output_ratios)
        )

        if self.assignment_palette_hex is None:
            self.assignment_palette_hex = None
        else:
            try:
                assignment = list(self.assignment_palette_hex)
            except TypeError as exc:
                raise ValueError(
                    f"assignment_palette_hex must contain {PALETTE_STATE_COUNT} colours"
                ) from exc
            if len(assignment) != PALETTE_STATE_COUNT:
                raise ValueError(
                    f"assignment_palette_hex must contain {PALETTE_STATE_COUNT} colours"
                )
            if any(not isinstance(value, str) for value in assignment):
                raise ValueError(
                    "assignment_palette_hex values must be #RRGGBB strings"
                )
            self.assignment_palette_hex = [
                normalize_hex(value) for value in assignment
            ]

        raw_refs = list(self.physical_filament_refs or ())
        raw_refs = (raw_refs + [None] * 4)[:4]
        refs: list[FilamentSnapshotRef | None] = []
        for index, raw_ref in enumerate(raw_refs):
            if isinstance(raw_ref, FilamentSnapshotRef):
                ref = raw_ref
            else:
                ref = FilamentSnapshotRef.from_mapping(raw_ref)
            # A stale identity attached to a manually changed HEX would be
            # more dangerous than no identity.  Fail closed per slot without
            # making an otherwise valid older project unloadable.
            try:
                physical_hex = normalize_hex(self.physical_hex[index])
            except (IndexError, TypeError, ValueError):
                physical_hex = ""
            if ref is not None and (
                ref.matched_hex != physical_hex or ref.material != self.material
            ):
                ref = None
            refs.append(ref)
        self.physical_filament_refs = refs


RADIAL_CONVERSION_UNIFORM_STAGE_A = "uniform_stage_a"
RADIAL_CONVERSION_SELECTIVE_HYBRID = "selective_hybrid"
SUPPORTED_RADIAL_CONVERSION_MODES = (
    RADIAL_CONVERSION_UNIFORM_STAGE_A,
    RADIAL_CONVERSION_SELECTIVE_HYBRID,
)
RADIAL_SKIN_MODE_UNIFORM = "uniform"
RADIAL_SKIN_MODE_ADAPTIVE = "adaptive"
SUPPORTED_RADIAL_SKIN_MODES = (
    RADIAL_SKIN_MODE_UNIFORM,
    RADIAL_SKIN_MODE_ADAPTIVE,
)


@dataclass
class RadialSettings:
    """Settings for the separate, fail-closed radial-shell laboratory export.

    This does not modify the established Full Spectrum writer.  The first
    experimental implementation deliberately supports only one closed print
    part whose complete exterior is assigned to one black-containing mixed
    state.  Keeping its controls in a separate settings object makes that
    limitation explicit and lets later multi-state implementations extend the
    project format without reviving the unsafe grouped-Cycle experiment.
    """

    experimental_enabled: bool = False
    outer_skin_thickness_mm: float = 0.15
    layer_height_mm: float = 0.10
    minimum_lstar_delta: float = 35.0
    wall_generator: str = "classic"
    # Missing values in r20/Stage-A projects must remain the original,
    # full-exterior validation workflow.  Selective hybrid is therefore an
    # explicit string choice rather than an inference from the legacy
    # ``require_uniform_black_mix`` flag.
    conversion_mode: str = RADIAL_CONVERSION_UNIFORM_STAGE_A
    # Selective Hybrid keeps the established constant-depth shell unless the
    # user explicitly opts into the adaptive cel-band mapping.  Old projects
    # have no field and therefore migrate to ``uniform`` without changing
    # their output contract.
    skin_thickness_mode: str = RADIAL_SKIN_MODE_UNIFORM
    adaptive_skin_min_thickness_mm: float = 0.10
    adaptive_skin_max_thickness_mm: float = 0.30
    adaptive_skin_gamma: float = 1.0
    adaptive_skin_bands: int = 5
    require_uniform_black_mix: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.experimental_enabled, (bool, np.bool_)):
            raise ValueError("experimental_enabled must be a boolean")
        if isinstance(self.outer_skin_thickness_mm, (bool, np.bool_)) or not isinstance(
            self.outer_skin_thickness_mm,
            (int, float, np.integer, np.floating),
        ):
            raise ValueError("outer_skin_thickness_mm must be a finite number")
        thickness = float(self.outer_skin_thickness_mm)
        if not np.isfinite(thickness) or not 0.10 <= thickness <= 0.60:
            raise ValueError(
                "outer_skin_thickness_mm must be between 0.10 and 0.60 mm"
            )
        if isinstance(self.layer_height_mm, (bool, np.bool_)) or not isinstance(
            self.layer_height_mm,
            (int, float, np.integer, np.floating),
        ):
            raise ValueError("layer_height_mm must be a finite number")
        layer_height = float(self.layer_height_mm)
        # Stage A now targets the 0.10 mm validation profile.  Keep 0.20 mm
        # readable so existing r20 projects can still be opened explicitly.
        if not np.isfinite(layer_height) or layer_height not in (0.10, 0.20):
            raise ValueError(
                "layer_height_mm must be 0.10 or 0.20 mm for radial Stage A"
            )
        if isinstance(self.minimum_lstar_delta, (bool, np.bool_)) or not isinstance(
            self.minimum_lstar_delta,
            (int, float, np.integer, np.floating),
        ):
            raise ValueError("minimum_lstar_delta must be a finite number")
        minimum_lstar_delta = float(self.minimum_lstar_delta)
        if (
            not np.isfinite(minimum_lstar_delta)
            or not 0.0 <= minimum_lstar_delta <= 100.0
        ):
            raise ValueError("minimum_lstar_delta must be between 0 and 100")
        if not isinstance(self.wall_generator, str) or self.wall_generator not in {
            "classic",
            "arachne",
        }:
            raise ValueError("wall_generator must be 'classic' or 'arachne'")
        if (
            not isinstance(self.conversion_mode, str)
            or self.conversion_mode not in SUPPORTED_RADIAL_CONVERSION_MODES
        ):
            raise ValueError(
                "conversion_mode must be 'uniform_stage_a' or "
                "'selective_hybrid'"
            )
        if (
            not isinstance(self.skin_thickness_mode, str)
            or self.skin_thickness_mode not in SUPPORTED_RADIAL_SKIN_MODES
        ):
            raise ValueError(
                "skin_thickness_mode must be 'uniform' or 'adaptive'"
            )
        adaptive_values = (
            (
                "adaptive_skin_min_thickness_mm",
                self.adaptive_skin_min_thickness_mm,
            ),
            (
                "adaptive_skin_max_thickness_mm",
                self.adaptive_skin_max_thickness_mm,
            ),
            ("adaptive_skin_gamma", self.adaptive_skin_gamma),
        )
        checked_adaptive: dict[str, float] = {}
        for name, value in adaptive_values:
            if isinstance(value, (bool, np.bool_)) or not isinstance(
                value,
                (int, float, np.integer, np.floating),
            ):
                raise ValueError(f"{name} must be a finite number")
            checked = float(value)
            if not np.isfinite(checked):
                raise ValueError(f"{name} must be a finite number")
            checked_adaptive[name] = checked
        adaptive_min = checked_adaptive["adaptive_skin_min_thickness_mm"]
        adaptive_max = checked_adaptive["adaptive_skin_max_thickness_mm"]
        adaptive_gamma = checked_adaptive["adaptive_skin_gamma"]
        if not 0.10 <= adaptive_min <= 0.60:
            raise ValueError(
                "adaptive_skin_min_thickness_mm must be between 0.10 and 0.60 mm"
            )
        if not 0.10 <= adaptive_max <= 0.60:
            raise ValueError(
                "adaptive_skin_max_thickness_mm must be between 0.10 and 0.60 mm"
            )
        if adaptive_min >= adaptive_max:
            raise ValueError(
                "adaptive_skin_min_thickness_mm must be smaller than "
                "adaptive_skin_max_thickness_mm"
            )
        if not 0.25 <= adaptive_gamma <= 4.0:
            raise ValueError("adaptive_skin_gamma must be between 0.25 and 4.0")
        if isinstance(self.adaptive_skin_bands, (bool, np.bool_)) or not isinstance(
            self.adaptive_skin_bands,
            (int, np.integer),
        ):
            raise ValueError("adaptive_skin_bands must be an integer from 4 to 6")
        adaptive_bands = int(self.adaptive_skin_bands)
        if not 4 <= adaptive_bands <= 6:
            raise ValueError("adaptive_skin_bands must be an integer from 4 to 6")
        if not isinstance(self.require_uniform_black_mix, (bool, np.bool_)):
            raise ValueError("require_uniform_black_mix must be a boolean")
        self.experimental_enabled = bool(self.experimental_enabled)
        self.outer_skin_thickness_mm = thickness
        self.layer_height_mm = layer_height
        self.minimum_lstar_delta = minimum_lstar_delta
        self.adaptive_skin_min_thickness_mm = adaptive_min
        self.adaptive_skin_max_thickness_mm = adaptive_max
        self.adaptive_skin_gamma = adaptive_gamma
        self.adaptive_skin_bands = adaptive_bands
        self.require_uniform_black_mix = bool(self.require_uniform_black_mix)

    def skin_thickness_for_lstar(
        self,
        target_lstar: float,
        black_lstar: float,
        partner_lstar: float,
    ) -> float:
        """Map one target L* to the selected uniform/adaptive shell depth.

        Adaptive mode normalizes the target between the selected black and
        partner filaments, applies the user gamma, then snaps it to 4--6 cel
        bands.  The public UI shows this same deterministic mapping before the
        geometry workflow consumes it.
        """

        if self.skin_thickness_mode == RADIAL_SKIN_MODE_UNIFORM:
            return float(self.outer_skin_thickness_mm)
        values = (target_lstar, black_lstar, partner_lstar)
        if any(
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, float, np.integer, np.floating))
            or not np.isfinite(float(value))
            for value in values
        ):
            raise ValueError("target, black and partner L* must be finite numbers")
        target = float(target_lstar)
        black = float(black_lstar)
        partner = float(partner_lstar)
        if partner <= black + 1e-12:
            raise ValueError("partner L* must be greater than black L*")
        normalized = float(np.clip((target - black) / (partner - black), 0.0, 1.0))
        curved = normalized ** float(self.adaptive_skin_gamma)
        intervals = int(self.adaptive_skin_bands) - 1
        band_index = min(intervals, int(np.floor(curved * intervals + 0.5)))
        band_fraction = float(band_index) / float(intervals)
        return float(
            self.adaptive_skin_min_thickness_mm
            + (
                self.adaptive_skin_max_thickness_mm
                - self.adaptive_skin_min_thickness_mm
            )
            * band_fraction
        )


COLOR_DEPTH_UNCALIBRATED_POLICY = "uncalibrated-common-skin-slice-only"


@dataclass
class ColorDepthSettings:
    """Settings for the separate all-colour ColorDepth laboratory export.

    ColorDepth treats a FullSpectrum state as a *target-colour label* only.
    Legacy Ratio/Cycle percentages are never geometry inputs.  The current
    r21 laboratory policy places the brighter physical member of each mixed
    pair in a common-depth outer skin and the other member behind it.  It is
    intentionally uncalibrated and therefore remains SLICE ONLY.

    ``experimental_enabled`` is deliberately separate from the normal 3MF
    writer.  Persisting this flag records an explicit opt-in; merely opening
    an older r19/r20 project cannot enable the experimental path.
    """

    experimental_enabled: bool = False
    outer_thickness_mm: float = 0.15
    layer_height_mm: float = 0.20
    recipe_policy: str = COLOR_DEPTH_UNCALIBRATED_POLICY

    def __post_init__(self) -> None:
        if not isinstance(self.experimental_enabled, (bool, np.bool_)):
            raise ValueError("experimental_enabled must be a boolean")
        thickness = float(self.outer_thickness_mm)
        if not np.isfinite(thickness) or not 0.14 <= thickness <= 0.60:
            raise ValueError(
                "outer_thickness_mm must be between 0.14 and 0.60 mm"
            )
        layer_height = float(self.layer_height_mm)
        if not np.isfinite(layer_height) or layer_height != 0.20:
            raise ValueError(
                "layer_height_mm must be 0.20 mm for ColorDepth Lab"
            )
        policy = str(self.recipe_policy).strip()
        if policy != COLOR_DEPTH_UNCALIBRATED_POLICY:
            raise ValueError(
                "recipe_policy must explicitly select the uncalibrated "
                "common-skin SLICE ONLY policy"
            )
        self.experimental_enabled = bool(self.experimental_enabled)
        self.outer_thickness_mm = thickness
        self.layer_height_mm = layer_height
        self.recipe_policy = policy


def without_surface_shell_output(palette: PaletteSettings) -> PaletteSettings:
    """Return a fail-closed palette without mutating a caller-owned object.

    Normal Ratio palettes are returned unchanged so their serialized data and
    black-correction vector remain byte-for-byte identical.  The defensive
    copy only covers objects that were mutated after dataclass validation.
    """

    if not bool(getattr(palette, "surface_shell_enabled", False)):
        return palette
    safe = copy.deepcopy(palette)
    safe.surface_shell_enabled = False
    return safe


EXPORT_VALIDATION_LEVELS = ("high", "medium", "low", "ignore")


def normalize_export_validation_level(value: object) -> str:
    """Never turn malformed project/preferences data into relaxed validation."""

    return value if isinstance(value, str) and value in EXPORT_VALIDATION_LEVELS else "high"


@dataclass
class AppSettings:
    geometry: GeometrySettings = field(default_factory=GeometrySettings)
    tone: ToneSettings = field(default_factory=ToneSettings)
    palette: PaletteSettings = field(default_factory=PaletteSettings)
    # Retained only so r20 project files and internal radial regression tests
    # remain loadable.  r21's GUI does not expose this obsolete workflow.
    radial: RadialSettings = field(default_factory=RadialSettings)
    color_depth: ColorDepthSettings = field(default_factory=ColorDepthSettings)
    part_palettes: dict[str, PaletteSettings] = field(default_factory=dict)
    # User-facing names are keyed by the immutable part key.  Geometry,
    # painting, palettes and exports must continue to use ``part_keys`` for
    # identity so renaming a part can never detach its saved edits.
    part_names: dict[str, str] = field(default_factory=dict)
    # Manual-editor backgrounds are per source model rather than one global
    # preference.  The key is the source OBJ SHA-256 digest.
    manual_view_backgrounds: dict[str, str] = field(default_factory=dict)
    # Orbit direction is a global interaction preference.  Keep it outside the
    # per-model background table so every newly opened model feels consistent.
    manual_orbit_inverted: bool = False
    # Export-only policy: changing this must not invalidate prepared geometry.
    # Non-default policies require fresh GUI consent for every export.
    export_validation_level: str = "high"

    def __post_init__(self) -> None:
        self.export_validation_level = normalize_export_validation_level(
            self.export_validation_level
        )

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["export_validation_level"] = normalize_export_validation_level(
            self.export_validation_level
        )
        if result["export_validation_level"] == "high":
            result.pop("export_validation_level")
        # Keep a no-correction/no-shell project structurally identical to the
        # legacy settings JSON.  Optional output fields persist only when
        # active, so loading then saving an old project stays stable.
        tone = result.get("tone")
        if isinstance(tone, dict) and tone.get("illustration_mode") == "off":
            # Dormant controls do not affect output.  Omitting all illustration
            # keys keeps an ordinary project loadable by pre-filter releases;
            # this build restores the documented defaults on reload.
            for key in (
                "illustration_mode",
                "illustration_strength",
                "illustration_bands",
                "illustration_light",
                "illustration_light_intensity",
                "illustration_light_range",
                "illustration_detail_strength",
                "illustration_selective_highlight_fraction",
                "illustration_contour_policy",
            ):
                tone.pop(key, None)
        if isinstance(tone, dict) and not tone.get(
            "illustration_detail_strength", 0.0
        ):
            # Keep every existing Cel/Strong-Cel project structurally stable
            # until the explicitly gated detail layer is enabled.
            tone.pop("illustration_detail_strength", None)
        if isinstance(tone, dict) and not tone.get(
            "illustration_selective_highlight_fraction", 0.0
        ):
            tone.pop("illustration_selective_highlight_fraction", None)
        if isinstance(tone, dict) and tone.get(
            "illustration_contour_policy", "outer_crease_fold"
        ) == "outer_crease_fold":
            # This is the historical selective-highlight behavior.  Omit it
            # even while active so old project JSON keeps the same structure.
            tone.pop("illustration_contour_policy", None)
        palette = result.get("palette")
        if (
            isinstance(palette, dict)
            and palette.get("color_mode") == COLOR_MODE_FULL_SPECTRUM
        ):
            # Keep old project JSON structurally compatible when the new mode
            # has never been enabled.
            palette.pop("color_mode", None)
        if isinstance(palette, dict) and palette.get("output_mix_ratios_b") is None:
            palette.pop("output_mix_ratios_b", None)
        if isinstance(palette, dict) and palette.get("assignment_palette_hex") is None:
            palette.pop("assignment_palette_hex", None)
        if isinstance(palette, dict) and not palette.get("surface_shell_enabled"):
            palette.pop("surface_shell_enabled", None)
        part_palettes = result.get("part_palettes")
        if isinstance(part_palettes, dict):
            for part_palette in part_palettes.values():
                if (
                    isinstance(part_palette, dict)
                    and part_palette.get("color_mode")
                    == COLOR_MODE_FULL_SPECTRUM
                ):
                    part_palette.pop("color_mode", None)
                if (
                    isinstance(part_palette, dict)
                    and part_palette.get("output_mix_ratios_b") is None
                ):
                    part_palette.pop("output_mix_ratios_b", None)
                if (
                    isinstance(part_palette, dict)
                    and part_palette.get("assignment_palette_hex") is None
                ):
                    part_palette.pop("assignment_palette_hex", None)
                if isinstance(part_palette, dict) and not part_palette.get(
                    "surface_shell_enabled"
                ):
                    part_palette.pop("surface_shell_enabled", None)
        radial = result.get("radial")
        default_radial = asdict(RadialSettings())
        if isinstance(radial, dict) and radial == default_radial:
            result.pop("radial", None)
        color_depth = result.get("color_depth")
        default_color_depth = asdict(ColorDepthSettings())
        if (
            isinstance(color_depth, dict)
            and color_depth == default_color_depth
        ):
            result.pop("color_depth", None)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "AppSettings":
        raw_geometry = dict(value.get("geometry", {}))
        # Plane splitting was an experimental 2.0 option and is no longer a
        # normal import operation.  Do not let an old project silently cut a
        # newly opened model just because it persisted split_enabled=true.
        raw_geometry["split_enabled"] = False
        def migrated_palette(raw: object) -> PaletteSettings:
            data = dict(raw) if isinstance(raw, dict) else {}
            enabled = data.get("enabled_states")
            if "palette_state_count" not in data and isinstance(enabled, list):
                if len(enabled) in (24, 32):
                    data["palette_state_count"] = len(enabled)
            return PaletteSettings(**data)

        raw_part_palettes = value.get("part_palettes", {})
        part_palettes: dict[str, PaletteSettings] = {}
        if isinstance(raw_part_palettes, dict):
            for key, palette_value in raw_part_palettes.items():
                if isinstance(palette_value, dict):
                    part_palettes[str(key)] = migrated_palette(palette_value)
        raw_part_names = value.get("part_names", {})
        part_names: dict[str, str] = {}
        if isinstance(raw_part_names, dict):
            for key, name in raw_part_names.items():
                if not isinstance(key, str) or not isinstance(name, str):
                    continue
                clean_key = key.strip()
                clean_name = name.strip()
                if (
                    clean_key
                    and clean_name
                    and len(clean_name) <= 120
                    and not any(ord(char) < 32 or ord(char) == 127 for char in clean_name)
                ):
                    part_names[clean_key] = clean_name
        raw_backgrounds = value.get("manual_view_backgrounds", {})
        manual_view_backgrounds: dict[str, str] = {}
        allowed_backgrounds = {"auto", "dark", "light", "neutral"}
        if isinstance(raw_backgrounds, dict):
            for digest, mode in raw_backgrounds.items():
                if not isinstance(digest, str) or not isinstance(mode, str):
                    continue
                clean_digest = digest.strip().lower()
                clean_mode = mode.strip().lower()
                if (
                    len(clean_digest) == 64
                    and all(char in "0123456789abcdef" for char in clean_digest)
                    and clean_mode in allowed_backgrounds
                ):
                    manual_view_backgrounds[clean_digest] = clean_mode
        raw_orbit_inverted = value.get("manual_orbit_inverted", False)
        manual_orbit_inverted = (
            raw_orbit_inverted
            if isinstance(raw_orbit_inverted, bool)
            else False
        )
        return cls(
            geometry=GeometrySettings(**raw_geometry),
            tone=ToneSettings(**dict(value.get("tone", {}))),
            palette=migrated_palette(value.get("palette", {})),
            color_depth=ColorDepthSettings(
                **dict(value.get("color_depth", {}))
            ),
            radial=RadialSettings(**dict(value.get("radial", {}))),
            part_palettes=part_palettes,
            part_names=part_names,
            manual_view_backgrounds=manual_view_backgrounds,
            manual_orbit_inverted=manual_orbit_inverted,
            export_validation_level=normalize_export_validation_level(
                value.get("export_validation_level", "high")
            ),
        )


@dataclass
class ObjAsset:
    path: Path
    sha256: str
    file_size: int
    vertices: np.ndarray
    colors: np.ndarray
    faces: np.ndarray
    original_vertex_count: int
    original_face_count: int
    warnings: list[str]
    part_names: tuple[str, ...] = ()
    part_keys: tuple[str, ...] = ()
    face_part_ids: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.int16)
    )
    part_face_counts: tuple[int, ...] = ()
    part_vertex_counts: tuple[int, ...] = ()
    # ``part_names`` always contains at least one display name, including for
    # markerless OBJ files. Keep the source marker information separately so
    # geometry preparation can distinguish a real Tripo multipart export from
    # that synthetic single "whole OBJ" entry.
    part_marker_kind: str | None = None
    has_explicit_parts: bool = False
    # Conservative importer provenance used only to retain fail-closed feature
    # boundaries across a portable project round-trip.  Geometry code must
    # require a known schema and explicit booleans rather than infer trust from
    # a file extension or part names.
    import_metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class MeshLevel:
    vertices_unit: np.ndarray
    faces: np.ndarray
    vertex_colors: np.ndarray
    areas_unit: np.ndarray
    neighbors: np.ndarray | None
    face_part_ids: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.int16)
    )
    part_names: tuple[str, ...] = ()
    part_keys: tuple[str, ...] = ()
    # Per-final-face origin.  Zero is an original/exterior face; positive
    # values are closure surfaces generated while solidifying Tripo parts.
    # Keep this after the legacy fields so older positional constructors retain
    # their meaning. The array is empty after an untracked topology change.
    face_provenance: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.uint8)
    )


@dataclass
class PreparedGeometry:
    source: ObjAsset
    final: MeshLevel
    preview: MeshLevel
    clean_vertex_count: int
    clean_face_count: int
    removed_vertices: int
    removed_faces: int
    topology: dict[str, int | bool]
    source_area_unit: float
    source_volume_unit: float
    simplified_area_unit: float
    simplified_volume_unit: float
    source_dimensions_unit: np.ndarray
    warnings: list[str]
    part_names: tuple[str, ...] = ()
    part_keys: tuple[str, ...] = ()
    part_stats: list[dict[str, object]] = field(default_factory=list)
    assembly: dict[str, object] = field(default_factory=dict)


@dataclass
class ColorResult:
    tone_vertex_rgb: np.ndarray
    source_face_rgb: np.ndarray
    palette_indices: np.ndarray
    target_face_rgb: np.ndarray
    delta_e: np.ndarray
    smoothed_faces: int
    palette_face_counts: np.ndarray
    palette_area_fractions: np.ndarray
    pink_area_fraction: float
    manual_override_faces: int = 0
    black_free_remapped_faces: int = 0
    part_metrics: list[dict[str, object]] = field(default_factory=list)
    # Authoritative printable-face tone.  Older/synthetic results may omit it;
    # consumers then fall back to averaging ``tone_vertex_rgb``.
    tone_face_rgb: np.ndarray | None = None
    # True only when the tone pipeline intentionally made every triangle a
    # constant colour (currently Cel/Noir illustration modes).  Ordinary tone
    # keeps this false so adaptive shading may still use legitimate vertex
    # gradients inside a triangle.
    tone_face_rgb_flat: bool = False


@dataclass
class ExportResult:
    # ``None`` means an explicit individual-parts-only export.  This is used
    # when part palettes belong to different material families: no combined
    # 3MF may be written, but each independent print job is still valid.
    model_path: Path | None
    preview_path: Path
    report_path: Path
    guide_path: Path
    fallback_obj_path: Path | None
    validation: dict[str, object]
    part_model_paths: tuple[Path, ...] = ()
    individual_only: bool = False
