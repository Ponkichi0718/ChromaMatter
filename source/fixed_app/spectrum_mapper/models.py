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

    def __post_init__(self) -> None:
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

    outer_skin_thickness_mm: float = 0.15
    layer_height_mm: float = 0.20
    require_uniform_black_mix: bool = True

    def __post_init__(self) -> None:
        thickness = float(self.outer_skin_thickness_mm)
        if not np.isfinite(thickness) or not 0.14 <= thickness <= 0.60:
            raise ValueError(
                "outer_skin_thickness_mm must be between 0.14 and 0.60 mm"
            )
        layer_height = float(self.layer_height_mm)
        # The dedicated experimental archive and its static validator are
        # intentionally calibrated to one fixed pitch.  Accepting another
        # value here would make the report/guide disagree with the 0.20 mm
        # project actually written by radial_export.
        if not np.isfinite(layer_height) or layer_height != 0.20:
            raise ValueError(
                "layer_height_mm must be 0.20 mm for the radial MVP"
            )
        if not isinstance(self.require_uniform_black_mix, (bool, np.bool_)):
            raise ValueError("require_uniform_black_mix must be a boolean")
        self.outer_skin_thickness_mm = thickness
        self.layer_height_mm = layer_height
        self.require_uniform_black_mix = bool(self.require_uniform_black_mix)


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

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        # Keep a no-correction/no-shell project structurally identical to the
        # legacy settings JSON.  Optional output fields persist only when
        # active, so loading then saving an old project stays stable.
        palette = result.get("palette")
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
