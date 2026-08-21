from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

import numpy as np

from .mixer import (
    PALETTE_STATE_COUNT,
    build_palette_rgb,
    normalize_hex,
    validate_black_free_slots,
    validate_output_mix_ratios_b,
)
from .models import AppSettings, FilamentSnapshotRef, MeshLevel, PaletteSettings


DEFAULT_PART_KEY = "__whole_model__"

FilamentRefIdentity: TypeAlias = tuple[
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
] | None
PrintFilamentRefIdentity: TypeAlias = tuple[str, str] | None

PaletteIdentity: TypeAlias = tuple[
    str,
    int,
    tuple[str, ...],
    tuple[bool, ...],
    tuple[str | None, ...],
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...] | None,
    tuple[str, ...] | None,
    bool,
    int,
    int,
    int,
    bool,
    tuple[FilamentRefIdentity, ...],
]
PrintPaletteIdentity: TypeAlias = tuple[
    str,
    int,
    tuple[str, ...],
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...] | None,
    bool,
    tuple[PrintFilamentRefIdentity, ...],
]


class PartPaletteError(ValueError):
    """Raised when part metadata or a part-local palette is inconsistent."""


@dataclass(frozen=True, slots=True)
class PartLayout:
    """Validated part keys and the zero-based part index of every face."""

    part_keys: tuple[str, ...]
    face_part_ids: np.ndarray
    face_count: int

    @property
    def part_count(self) -> int:
        return len(self.part_keys)


@dataclass(frozen=True, slots=True)
class PaletteGroup:
    """Parts that can share one Full Spectrum print-palette definition."""

    group_id: int
    part_indices: tuple[int, ...]
    part_keys: tuple[str, ...]
    print_identity: PrintPaletteIdentity


@dataclass(frozen=True, slots=True)
class PaletteGroupingPlan:
    """A stable plan for one shared job or one job per palette group."""

    mode: Literal["one-job", "per-group"]
    groups: tuple[PaletteGroup, ...]
    part_group_ids: tuple[int, ...]

    @property
    def one_job(self) -> bool:
        return self.mode == "one-job"

    @property
    def requires_separate_jobs(self) -> bool:
        return self.mode == "per-group"


def validate_part_layout(level: MeshLevel) -> PartLayout:
    """Return deterministic part metadata without mutating ``level``.

    Old projects have no explicit part metadata.  They fall back to one whole-
    model part.  Explicit multiple part keys require a face-to-part array,
    because guessing that relationship could apply the wrong filaments.
    """

    try:
        faces = np.asarray(level.faces)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PartPaletteError("mesh faces are unavailable") from exc
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise PartPaletteError("mesh faces must have shape (face_count, 3)")
    face_count = int(faces.shape[0])

    try:
        raw_keys = tuple(level.part_keys)
    except (AttributeError, TypeError) as exc:
        raise PartPaletteError("part_keys must be a sequence of strings") from exc
    if any(not isinstance(key, str) or not key.strip() for key in raw_keys):
        raise PartPaletteError("part keys must be non-empty strings")
    if len(set(raw_keys)) != len(raw_keys):
        raise PartPaletteError("part keys must be unique")

    try:
        raw_ids = np.asarray(level.face_part_ids)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PartPaletteError("face_part_ids must be an integer array") from exc

    if raw_ids.size == 0:
        keys = raw_keys or (DEFAULT_PART_KEY,)
        if face_count and len(keys) > 1:
            raise PartPaletteError(
                "face_part_ids are required when more than one part key exists"
            )
        part_ids = np.zeros(face_count, dtype=np.int64)
    else:
        if raw_ids.ndim != 1 or raw_ids.shape[0] != face_count:
            raise PartPaletteError(
                "face_part_ids must have one entry for every mesh face"
            )
        if not np.issubdtype(raw_ids.dtype, np.integer):
            raise PartPaletteError("face_part_ids must contain integers")
        part_ids = raw_ids.astype(np.int64, copy=True)
        if np.any(part_ids < 0):
            raise PartPaletteError("face_part_ids cannot contain negative values")

        max_part_id = int(part_ids.max())
        if raw_keys:
            keys = raw_keys
            if max_part_id >= len(keys):
                raise PartPaletteError(
                    "face_part_ids reference a part outside part_keys"
                )
        else:
            keys = tuple(f"__part_{index}__" for index in range(max_part_id + 1))

    # The caller can safely retain a layout across pure mapping operations.
    part_ids.setflags(write=False)
    return PartLayout(keys, part_ids, face_count)


def _validate_ratios(values: object, label: str) -> tuple[int, ...]:
    try:
        sequence = tuple(values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise PartPaletteError(f"{label} must contain six integer ratios") from exc
    if len(sequence) != 6:
        raise PartPaletteError(f"{label} must contain six integer ratios")
    if any(
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, np.integer))
        or not 0 <= int(value) <= 100
        for value in sequence
    ):
        raise PartPaletteError(f"{label} ratios must be integers from 0 to 100")
    return tuple(int(value) for value in sequence)


def _canonical_palette(palette: PaletteSettings) -> PaletteIdentity:
    if not isinstance(palette, PaletteSettings):
        raise PartPaletteError("part palette values must be PaletteSettings")

    try:
        physical_values = tuple(palette.physical_hex)
    except TypeError as exc:
        raise PartPaletteError("physical_hex must contain four colours") from exc
    if len(physical_values) != 4 or any(
        not isinstance(value, str) for value in physical_values
    ):
        raise PartPaletteError("physical_hex must contain four #RRGGBB colours")
    try:
        physical = tuple(normalize_hex(value) for value in physical_values)
    except ValueError as exc:
        raise PartPaletteError(str(exc)) from exc

    try:
        enabled_values = tuple(palette.enabled_states)
    except TypeError as exc:
        raise PartPaletteError(
            f"enabled_states must contain {PALETTE_STATE_COUNT} booleans"
        ) from exc
    if len(enabled_values) != PALETTE_STATE_COUNT or any(
        not isinstance(value, (bool, np.bool_)) for value in enabled_values
    ):
        raise PartPaletteError(
            f"enabled_states must contain {PALETTE_STATE_COUNT} booleans"
        )
    enabled = tuple(bool(value) for value in enabled_values)

    try:
        override_values = tuple(palette.mix_hex_overrides)
    except TypeError as exc:
        raise PartPaletteError(
            "mix_hex_overrides must contain six optional colours"
        ) from exc
    if len(override_values) != 6:
        raise PartPaletteError("mix_hex_overrides must contain six optional colours")
    overrides: list[str | None] = []
    for value in override_values:
        if value is None or value == "":
            overrides.append(None)
        elif not isinstance(value, str):
            raise PartPaletteError("mix colour overrides must be #RRGGBB or None")
        else:
            try:
                overrides.append(normalize_hex(value))
            except ValueError as exc:
                raise PartPaletteError(str(exc)) from exc

    primary = _validate_ratios(palette.mix_ratios_b, "mix_ratios_b")
    secondary = _validate_ratios(
        palette.secondary_mix_ratios_b, "secondary_mix_ratios_b"
    )
    try:
        output = validate_output_mix_ratios_b(palette.output_mix_ratios_b)
    except ValueError as exc:
        raise PartPaletteError(str(exc)) from exc
    raw_assignment = getattr(palette, "assignment_palette_hex", None)
    if raw_assignment is None:
        assignment: tuple[str, ...] | None = None
    else:
        try:
            assignment_values = tuple(raw_assignment)
        except TypeError as exc:
            raise PartPaletteError(
                f"assignment_palette_hex must contain {PALETTE_STATE_COUNT} colours"
            ) from exc
        if len(assignment_values) != PALETTE_STATE_COUNT or any(
            not isinstance(value, str) for value in assignment_values
        ):
            raise PartPaletteError(
                f"assignment_palette_hex must contain {PALETTE_STATE_COUNT} colours"
            )
        try:
            assignment = tuple(normalize_hex(value) for value in assignment_values)
        except ValueError as exc:
            raise PartPaletteError(str(exc)) from exc
    if not isinstance(palette.black_free_gradient_enabled, (bool, np.bool_)):
        raise PartPaletteError(
            "black_free_gradient_enabled must be a boolean"
        )
    try:
        black_slot, red_slot, brown_slot = validate_black_free_slots(
            palette.black_free_black_slot,
            palette.black_free_red_slot,
            palette.black_free_brown_slot,
        )
    except ValueError as exc:
        raise PartPaletteError(str(exc)) from exc
    try:
        ref_values = tuple(palette.physical_filament_refs)
    except TypeError as exc:
        raise PartPaletteError(
            "physical_filament_refs must contain four product snapshots"
        ) from exc
    if len(ref_values) != 4:
        raise PartPaletteError(
            "physical_filament_refs must contain four product snapshots"
        )
    refs: list[FilamentRefIdentity] = []
    for index, ref in enumerate(ref_values):
        if ref is None:
            refs.append(None)
            continue
        if not isinstance(ref, FilamentSnapshotRef):
            raise PartPaletteError(
                "physical filament references must be product snapshots or None"
            )
        if ref.matched_hex != physical[index]:
            raise PartPaletteError(
                "physical filament snapshot HEX must match its F slot"
            )
        if ref.material != palette.material:
            raise PartPaletteError(
                "physical filament snapshot material must match its palette"
            )
        refs.append(
            (
                ref.product_id,
                ref.brand,
                ref.series,
                ref.color_name,
                ref.matched_hex,
                ref.finish_class,
                ref.source,
                ref.material,
            )
        )
    return (
        palette.material,
        int(palette.palette_state_count),
        physical,
        enabled,
        tuple(overrides),
        primary,
        secondary,
        output,
        assignment,
        bool(palette.black_free_gradient_enabled),
        black_slot,
        red_slot,
        brown_slot,
        bool(palette.surface_shell_enabled),
        tuple(refs),
    )


def palette_identity(palette: PaletteSettings) -> PaletteIdentity:
    """Return the complete normalized identity of a local palette.

    This identity includes assignment switches and preview-only mix colour
    overrides.  Use :func:`print_palette_identity` when deciding whether two
    parts can coexist in one Full Spectrum job.
    """

    return _canonical_palette(palette)


def palettes_are_identical(
    first: PaletteSettings, second: PaletteSettings
) -> bool:
    return palette_identity(first) == palette_identity(second)


def print_palette_identity(palette: PaletteSettings) -> PrintPaletteIdentity:
    """Return settings that define physical slots and printable mix states."""

    (
        material,
        count,
        physical,
        _enabled,
        _overrides,
        primary,
        secondary,
        output,
        _assignment,
        _black_free_enabled,
        _black_slot,
        _red_slot,
        _brown_slot,
        surface_shell_enabled,
        refs,
    ) = _canonical_palette(palette)
    # The stable product ID and finish define the physical spool for print
    # grouping.  Catalog wording, source kind and URLs are portable display
    # provenance and may legitimately change without requiring another job.
    print_refs: tuple[PrintFilamentRefIdentity, ...] = tuple(
        None if ref is None else (ref[0], ref[5])
        for ref in refs
    )
    return (
        material,
        count,
        physical,
        primary,
        secondary,
        output,
        surface_shell_enabled,
        print_refs,
    )


def palettes_are_print_compatible(
    first: PaletteSettings, second: PaletteSettings
) -> bool:
    """Whether two palettes can share one Orca Full Spectrum definition."""

    return print_palette_identity(first) == print_palette_identity(second)


def resolve_palette_for_part_key(
    settings: AppSettings, part_key: str
) -> PaletteSettings:
    """Resolve one exact part key, falling back to the global palette."""

    if not isinstance(settings, AppSettings):
        raise PartPaletteError("settings must be AppSettings")
    if not isinstance(part_key, str) or not part_key.strip():
        raise PartPaletteError("part key must be a non-empty string")
    if not isinstance(settings.part_palettes, Mapping):
        raise PartPaletteError("part_palettes must be a mapping")

    _canonical_palette(settings.palette)
    palette = settings.part_palettes.get(part_key)
    if palette is None and "/cut:" in part_key:
        # A generated A/B part inherits the palette of the part that was cut
        # until the user explicitly gives the new stable key its own palette.
        parent_key = part_key.split("/cut:", 1)[0]
        palette = settings.part_palettes.get(parent_key)
    if palette is None:
        palette = settings.palette
    _canonical_palette(palette)
    return palette


def resolve_part_palette_settings(
    settings: AppSettings, level: MeshLevel | PartLayout
) -> tuple[PaletteSettings, ...]:
    """Resolve one validated ``PaletteSettings`` object per stable part key."""

    layout = level if isinstance(level, PartLayout) else validate_part_layout(level)
    return tuple(
        resolve_palette_for_part_key(settings, key) for key in layout.part_keys
    )


def build_part_palette_rgb_tables(
    settings: AppSettings, level: MeshLevel | PartLayout
) -> np.ndarray:
    """Build a ``(part_count, 32, 3)`` RGB table in the 0..1 range."""

    layout = level if isinstance(level, PartLayout) else validate_part_layout(level)
    palettes = resolve_part_palette_settings(settings, layout)
    tables: list[np.ndarray] = []
    for key, palette in zip(layout.part_keys, palettes, strict=True):
        try:
            _hex_values, rgb = build_palette_rgb(
                list(palette.physical_hex),
                list(palette.mix_hex_overrides),
                list(palette.mix_ratios_b),
                list(palette.secondary_mix_ratios_b),
            )
        except ValueError as exc:
            raise PartPaletteError(f"invalid palette for part {key!r}: {exc}") from exc
        if rgb.shape != (PALETTE_STATE_COUNT, 3):
            raise PartPaletteError(
                f"palette for part {key!r} did not produce {PALETTE_STATE_COUNT} RGB states"
            )
        tables.append(np.asarray(rgb, dtype=np.float64))

    result = np.stack(tables, axis=0)
    if not np.all(np.isfinite(result)) or np.any(result < 0.0) or np.any(result > 1.0):
        raise PartPaletteError("palette RGB tables must stay in the 0..1 range")
    return np.ascontiguousarray(result)


def assignment_palette_rgb_table(palette: PaletteSettings) -> np.ndarray:
    """Return the RGB table used to choose automatic state IDs.

    ``assignment_palette_hex`` freezes only the choice of state.  The normal
    display table remains authoritative for preview and print output.
    """

    _canonical_palette(palette)
    assignment = getattr(palette, "assignment_palette_hex", None)
    if assignment is None:
        _hex_values, rgb = build_palette_rgb(
            list(palette.physical_hex),
            list(palette.mix_hex_overrides),
            list(palette.mix_ratios_b),
            list(palette.secondary_mix_ratios_b),
        )
        result = np.asarray(rgb, dtype=np.float64)
    else:
        result = np.asarray(
            [
                [int(value[index : index + 2], 16) for index in (1, 3, 5)]
                for value in assignment
            ],
            dtype=np.float64,
        ) / 255.0
    if result.shape != (PALETTE_STATE_COUNT, 3):
        raise PartPaletteError(
            f"assignment palette must produce {PALETTE_STATE_COUNT} RGB states"
        )
    if not np.all(np.isfinite(result)) or np.any(result < 0.0) or np.any(result > 1.0):
        raise PartPaletteError("assignment palette RGB must stay in the 0..1 range")
    return np.ascontiguousarray(result)


def build_part_assignment_palette_rgb_tables(
    settings: AppSettings, level: MeshLevel | PartLayout
) -> np.ndarray:
    """Build one automatic-assignment table per resolved model part."""

    layout = level if isinstance(level, PartLayout) else validate_part_layout(level)
    palettes = resolve_part_palette_settings(settings, layout)
    return np.ascontiguousarray(
        np.stack(
            [assignment_palette_rgb_table(palette) for palette in palettes],
            axis=0,
        )
    )


def _validated_local_states(
    local_state_ids: Sequence[int] | np.ndarray, face_count: int
) -> np.ndarray:
    try:
        states = np.asarray(local_state_ids)
    except (TypeError, ValueError) as exc:
        raise PartPaletteError("local state IDs must be an integer array") from exc
    if states.ndim != 1 or states.shape[0] != face_count:
        raise PartPaletteError("local state IDs must have one entry per face")
    if not np.issubdtype(states.dtype, np.integer):
        raise PartPaletteError("local state IDs must contain integers")
    result = states.astype(np.int64, copy=False)
    if np.any(result < 0) or np.any(result >= PALETTE_STATE_COUNT):
        raise PartPaletteError(
            f"local state IDs must be between 0 and {PALETTE_STATE_COUNT - 1}"
        )
    return result


def face_rgb_from_tables(
    level: MeshLevel | PartLayout,
    local_state_ids: Sequence[int] | np.ndarray,
    part_palette_rgb_tables: np.ndarray,
) -> np.ndarray:
    """Map each face's local 0-based state through its part's RGB table."""

    layout = level if isinstance(level, PartLayout) else validate_part_layout(level)
    states = _validated_local_states(local_state_ids, layout.face_count)
    try:
        tables = np.asarray(part_palette_rgb_tables, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise PartPaletteError("part palette RGB tables must be numeric") from exc
    expected_shape = (layout.part_count, PALETTE_STATE_COUNT, 3)
    if tables.shape != expected_shape:
        raise PartPaletteError(
            f"part palette RGB tables must have shape {expected_shape}"
        )
    if not np.all(np.isfinite(tables)) or np.any(tables < 0.0) or np.any(tables > 1.0):
        raise PartPaletteError("part palette RGB tables must stay in the 0..1 range")
    return np.ascontiguousarray(tables[layout.face_part_ids, states])


def face_rgb_from_local_states(
    settings: AppSettings,
    level: MeshLevel | PartLayout,
    local_state_ids: Sequence[int] | np.ndarray,
) -> np.ndarray:
    """Build per-part tables and return one RGB value for every mesh face."""

    layout = level if isinstance(level, PartLayout) else validate_part_layout(level)
    tables = build_part_palette_rgb_tables(settings, layout)
    return face_rgb_from_tables(layout, local_state_ids, tables)


def plan_palette_groups(
    settings: AppSettings, level: MeshLevel | PartLayout
) -> PaletteGroupingPlan:
    """Group parts in first-seen order by printable palette identity."""

    layout = level if isinstance(level, PartLayout) else validate_part_layout(level)
    palettes = resolve_part_palette_settings(settings, layout)
    identity_to_group: dict[PrintPaletteIdentity, int] = {}
    group_parts: list[list[int]] = []
    identities: list[PrintPaletteIdentity] = []
    part_group_ids: list[int] = []

    for part_index, palette in enumerate(palettes):
        identity = print_palette_identity(palette)
        group_id = identity_to_group.get(identity)
        if group_id is None:
            group_id = len(group_parts)
            identity_to_group[identity] = group_id
            identities.append(identity)
            group_parts.append([])
        group_parts[group_id].append(part_index)
        part_group_ids.append(group_id)

    groups = tuple(
        PaletteGroup(
            group_id=group_id,
            part_indices=tuple(indices),
            part_keys=tuple(layout.part_keys[index] for index in indices),
            print_identity=identities[group_id],
        )
        for group_id, indices in enumerate(group_parts)
    )
    mode: Literal["one-job", "per-group"] = (
        "one-job" if len(groups) == 1 else "per-group"
    )
    return PaletteGroupingPlan(mode, groups, tuple(part_group_ids))
