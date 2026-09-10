"""Fail-closed geometry boundary for a future selective radial hybrid.

Stage A can only convert a complete one-state exterior.  This module plans and
builds the next geometry step without changing either established writer:

* selected, high-CIELAB-lightness black mixes become a physical partner skin
  over the selected pure-black backing;
* every other target state remains on a pure-black carrier volume and regains
  its original exterior ``paint_color`` state by exact source-face provenance;
* material interfaces come from one conforming tetrahedral complex and remain
  exact-touch.

The result is deliberately not a 3MF.  A dedicated hybrid writer and Orca
round-trip validator are still required before these parts can be exposed as
an application export.  Returning typed, fully painted closed parts here keeps
that unverified archive boundary explicit instead of weakening the existing
Stage-A or normal Full Spectrum writers.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from numbers import Integral
from types import SimpleNamespace
from typing import Callable, Collection, Mapping

import numpy as np
import trimesh

from .color_depth import ColorDepthRecipe
from .color_depth_exact_partition import build_conforming_color_depth_partition
from .color_depth_head_geometry import (
    ColorDepthSourceSurface,
    ConformingColorDepthPartition,
    _validate_partition_arrays,
    _validate_visible_exterior,
    prepare_color_depth_source,
)
from .material_manifold import (
    MaterialManifoldResult,
    manifoldize_labeled_tetrahedra,
)
from .models import AppSettings
from .radial_workflow import (
    RadialContrastAnalysis,
    RadialPartnerContrast,
    analyze_radial_partner_contrast,
)


RADIAL_STAGE_B_SCHEMA = "tripo-spectrum-mapper.radial-stage-b.experimental.v1"
_ADAPTIVE_PARTNER_DEPTH_TOLERANCE_MM = 0.05
_ADAPTIVE_TET_FACES = np.asarray(
    ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)), dtype=np.int32
)
_ADAPTIVE_TET_EDGES = np.asarray(
    ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
    dtype=np.int32,
)


class RadialStageBError(RuntimeError):
    """Stable diagnostic for a rejected selective-radial operation."""

    def __init__(
        self,
        code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(self.code)


def _raise(code: str, **details: object) -> None:
    raise RadialStageBError(code, details)


def _immutable(values: np.ndarray, dtype: np.dtype) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype).copy()
    result.flags.writeable = False
    return result


def _state_fingerprint(states: np.ndarray) -> str:
    values = np.ascontiguousarray(states, dtype="<i2")
    return hashlib.sha256(values.tobytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class RadialStageBStateDecision:
    """One used target state's selected radial/conventional disposition."""

    state_id: int
    disposition: str
    reason: str
    black_extruder: int
    partner_extruder: int | None
    lstar_delta: float | None
    outer_physical: int
    backing_physical: int
    outer_skin_thickness_mm: float

    def to_dict(self) -> dict[str, object]:
        return {
            "state_id": int(self.state_id),
            "disposition": self.disposition,
            "reason": self.reason,
            "black_extruder": int(self.black_extruder),
            "partner_extruder": self.partner_extruder,
            "lstar_delta": self.lstar_delta,
            "outer_physical": int(self.outer_physical),
            "backing_physical": int(self.backing_physical),
            "outer_skin_thickness_mm": float(self.outer_skin_thickness_mm),
        }


@dataclass(frozen=True, slots=True)
class RadialStageBPlan:
    """Immutable selective-hybrid recipe plan for one source surface."""

    black_extruder: int
    black_lstar: float | None
    minimum_lstar_delta: float | None
    outer_skin_thickness_mm: float
    used_state_ids: tuple[int, ...]
    radial_state_ids: tuple[int, ...]
    conventional_state_ids: tuple[int, ...]
    state_outer_skin_thickness_mm: Mapping[int, float]
    state_decisions: tuple[RadialStageBStateDecision, ...]
    recipes: Mapping[int, ColorDepthRecipe]
    face_state_sha256: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def decision(self, state_id: int) -> RadialStageBStateDecision | None:
        target = int(state_id)
        return next(
            (item for item in self.state_decisions if item.state_id == target),
            None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RADIAL_STAGE_B_SCHEMA,
            "black_extruder": int(self.black_extruder),
            "black_lstar": (
                None if self.black_lstar is None else float(self.black_lstar)
            ),
            "minimum_lstar_delta": (
                None
                if self.minimum_lstar_delta is None
                else float(self.minimum_lstar_delta)
            ),
            "outer_skin_thickness_mm": float(self.outer_skin_thickness_mm),
            "used_state_ids": list(self.used_state_ids),
            "radial_state_ids": list(self.radial_state_ids),
            "conventional_state_ids": list(self.conventional_state_ids),
            "state_outer_skin_thickness_mm": {
                str(state_id): float(thickness)
                for state_id, thickness in sorted(
                    self.state_outer_skin_thickness_mm.items()
                )
            },
            "state_decisions": [item.to_dict() for item in self.state_decisions],
            "face_state_sha256": self.face_state_sha256,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RadialStageBPart:
    """One closed physical volume plus paint states for a hybrid writer."""

    name: str
    role: str
    physical_extruder: int
    vertices_mm: np.ndarray
    faces: np.ndarray
    paint_state_ids: np.ndarray
    source_face_ids: np.ndarray
    external_face_mask: np.ndarray
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RadialStageBResult:
    """Validated geometry result; intentionally has no archive path."""

    plan: RadialStageBPlan
    parts: tuple[RadialStageBPart, ...]
    interfaces: tuple[Mapping[str, object], ...]
    source_volume_mm3: float
    output_volume_mm3: float
    metadata: Mapping[str, object]


def _normalise_selected_states(
    selected_state_ids: Collection[int] | None,
) -> tuple[int, ...] | None:
    if selected_state_ids is None:
        return None
    values: list[int] = []
    for raw in selected_state_ids:
        if isinstance(raw, (bool, np.bool_)) or not isinstance(raw, Integral):
            _raise("invalid_selected_state", state_id=raw)
        value = int(raw)
        if value < 0:
            _raise("invalid_selected_state", state_id=value)
        values.append(value)
    return tuple(sorted(set(values)))


def _normalise_state_skin_thicknesses(
    values: Mapping[int, float] | None,
    *,
    selected_state_ids: Collection[int],
    default_thickness_mm: float,
) -> tuple[dict[int, float], float, bool]:
    """Resolve optional per-selected-state depths without adding seam bands.

    Conventional states have the same physical black on both sides, so their
    geometric threshold is semantically invisible.  In adaptive mode they use
    the minimum selected threshold, ensuring the global exact partition never
    gains a seventh, non-material-changing band merely because the legacy
    scalar fallback differs from the selected schedule.
    """

    selected = tuple(sorted(int(value) for value in selected_state_ids))
    resolved = {state_id: float(default_thickness_mm) for state_id in selected}
    if values is None:
        return resolved, float(default_thickness_mm), False
    supplied_states: set[int] = set()
    for raw_state, raw_thickness in values.items():
        if (
            isinstance(raw_state, (bool, np.bool_))
            or not isinstance(raw_state, Integral)
        ):
            _raise("invalid_state_skin_thickness_state", state_id=raw_state)
        state_id = int(raw_state)
        if state_id not in resolved:
            _raise(
                "state_skin_thickness_state_not_selected",
                state_id=state_id,
                selected_state_ids=list(selected),
            )
        supplied_states.add(state_id)
        if isinstance(raw_thickness, (bool, np.bool_)):
            _raise(
                "invalid_state_skin_thickness",
                state_id=state_id,
                value=raw_thickness,
            )
        try:
            thickness = float(raw_thickness)
        except (TypeError, ValueError) as exc:
            raise RadialStageBError(
                "invalid_state_skin_thickness",
                {"state_id": state_id, "value": raw_thickness},
            ) from exc
        if not math.isfinite(thickness) or not 0.10 <= thickness <= 0.60:
            _raise(
                "state_skin_thickness_out_of_range",
                state_id=state_id,
                value=raw_thickness,
                minimum_mm=0.10,
                maximum_mm=0.60,
            )
        resolved[state_id] = thickness
    missing_states = sorted(set(selected) - supplied_states)
    if missing_states:
        _raise(
            "state_skin_thickness_state_missing",
            state_ids=missing_states,
            selected_state_ids=list(selected),
        )
    unique = tuple(sorted(set(resolved.values())))
    if len(unique) > 6:
        _raise(
            "too_many_state_skin_thickness_bands",
            actual=len(unique),
            maximum=6,
            thicknesses_mm=list(unique),
        )
    too_close = [
        [float(first), float(second)]
        for first, second in zip(unique, unique[1:])
        if 0.0 < second - first <= 1e-7
    ]
    if too_close:
        _raise(
            "state_skin_thickness_bands_too_close",
            minimum_separation_mm=1e-7,
            pairs_mm=too_close,
        )
    canonical = min(unique) if unique else float(default_thickness_mm)
    return resolved, float(canonical), len(unique) > 1


def plan_radial_stage_b(
    settings: AppSettings,
    face_state_ids: np.ndarray,
    *,
    black_slot: int,
    selected_state_ids: Collection[int] | None = None,
    outer_skin_thickness_mm: float | None = None,
    state_skin_thickness_mm: Mapping[int, float] | None = None,
    require_hybrid_surface: bool = True,
) -> RadialStageBPlan:
    """Plan selected high-contrast states without changing other face states.

    ``selected_state_ids=None`` selects every *used* black-mix state which
    passes the configured L* gate.  An explicit collection is a strict user
    selection: unused, non-black, or below-threshold states are rejected.
    """

    raw_states = np.asarray(face_state_ids)
    if raw_states.ndim != 1 or not len(raw_states):
        _raise("face_states_required", shape=tuple(raw_states.shape))
    if not np.issubdtype(raw_states.dtype, np.integer):
        _raise("noninteger_face_states")
    minimum_state = int(raw_states.min())
    maximum_state = int(raw_states.max())
    if minimum_state < 0:
        _raise("negative_face_state", minimum=minimum_state)
    palette_count = int(settings.palette.palette_state_count)
    if maximum_state >= palette_count:
        _raise(
            "face_state_out_of_range",
            maximum=maximum_state,
            palette_state_count=palette_count,
        )
    states = np.asarray(raw_states, dtype=np.int16)
    if isinstance(outer_skin_thickness_mm, (bool, np.bool_)):
        _raise(
            "invalid_outer_skin_thickness",
            value=outer_skin_thickness_mm,
        )
    thickness = float(
        getattr(settings.radial, "outer_skin_thickness_mm", 0.15)
        if outer_skin_thickness_mm is None
        else outer_skin_thickness_mm
    )
    if not math.isfinite(thickness) or thickness <= 0.0:
        _raise("invalid_outer_skin_thickness", value=outer_skin_thickness_mm)

    contrast: RadialContrastAnalysis = analyze_radial_partner_contrast(
        settings,
        int(black_slot),
    )
    contrast_by_state: dict[int, RadialPartnerContrast] = {
        item.state_id: item for item in contrast.states
    }
    used = tuple(int(value) for value in np.unique(states))
    requested = _normalise_selected_states(selected_state_ids)
    qualifying_used = tuple(
        state_id
        for state_id in used
        if (
            state_id in contrast_by_state
            and contrast_by_state[state_id].qualifies
        )
    )
    if requested is None:
        selected = qualifying_used
    else:
        if not requested:
            _raise("radial_state_selection_required")
        unused = sorted(set(requested) - set(used))
        if unused:
            _raise("selected_state_not_used", state_ids=unused)
        nonblack = sorted(set(requested) - set(contrast_by_state))
        if nonblack:
            _raise("selected_state_not_black_mix", state_ids=nonblack)
        below = [
            contrast_by_state[state_id]
            for state_id in requested
            if not contrast_by_state[state_id].qualifies
        ]
        if below:
            _raise(
                "selected_state_contrast_below_threshold",
                minimum_lstar_delta=float(contrast.minimum_lstar_delta),
                states=[item.to_dict() for item in below],
            )
        selected = requested
    if not selected:
        _raise(
            "no_selected_eligible_state",
            minimum_lstar_delta=float(contrast.minimum_lstar_delta),
            used_state_ids=list(used),
        )
    conventional = tuple(sorted(set(used) - set(selected)))
    if require_hybrid_surface and not conventional:
        _raise(
            "hybrid_conventional_surface_required",
            radial_state_ids=list(selected),
        )

    state_thicknesses, conventional_threshold, variable_thickness = (
        _normalise_state_skin_thicknesses(
            state_skin_thickness_mm,
            selected_state_ids=selected,
            default_thickness_mm=thickness,
        )
    )

    black_extruder = int(black_slot) + 1
    recipes: dict[int, ColorDepthRecipe] = {}
    decisions: list[RadialStageBStateDecision] = []
    for state_id in used:
        item = contrast_by_state.get(state_id)
        if state_id in selected:
            assert item is not None and item.qualifies
            outer = int(item.partner_extruder)
            disposition = "radial"
            reason = "selected-high-lstar-black-mix"
            partner = outer
            delta = float(item.lstar_delta)
        else:
            # All passthrough target states share the black carrier.  Their
            # exact original paint state is restored only on source-exterior
            # faces after manifoldization; internal material faces stay black.
            outer = black_extruder
            disposition = "conventional"
            partner = None if item is None else int(item.partner_extruder)
            delta = None if item is None else float(item.lstar_delta)
            if state_id == int(black_slot):
                reason = "pure-black-preserved"
            elif item is not None and not item.qualifies:
                reason = "black-mix-below-lstar-threshold"
            elif item is not None:
                reason = "qualifying-state-not-selected"
            else:
                reason = "nonblack-or-pure-state-preserved"
        state_thickness = (
            state_thicknesses[state_id]
            if state_id in selected
            else conventional_threshold
        )
        recipes[state_id] = ColorDepthRecipe(
            target_label=state_id,
            outer_physical=outer,
            outer_thickness_mm=state_thickness,
            backing_physical=black_extruder,
            calibrated=False,
            metadata={
                "radial_stage_b": True,
                "disposition": disposition,
                "original_paint_state": state_id,
                "conventional_black_carrier": disposition == "conventional",
                "adaptive_outer_skin": bool(variable_thickness),
            },
        )
        decisions.append(
            RadialStageBStateDecision(
                state_id=state_id,
                disposition=disposition,
                reason=reason,
                black_extruder=black_extruder,
                partner_extruder=partner,
                lstar_delta=delta,
                outer_physical=outer,
                backing_physical=black_extruder,
                outer_skin_thickness_mm=state_thickness,
            )
        )

    return RadialStageBPlan(
        black_extruder=black_extruder,
        black_lstar=float(contrast.black_lstar),
        minimum_lstar_delta=float(contrast.minimum_lstar_delta),
        outer_skin_thickness_mm=thickness,
        used_state_ids=used,
        radial_state_ids=tuple(selected),
        conventional_state_ids=conventional,
        state_outer_skin_thickness_mm={
            state_id: float(state_thicknesses[state_id])
            for state_id in selected
        },
        state_decisions=tuple(decisions),
        recipes=recipes,
        face_state_sha256=_state_fingerprint(states),
        metadata={
            "schema": RADIAL_STAGE_B_SCHEMA,
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "writer_ready": False,
            "hybrid_writer_required": True,
            "normal_writer_unchanged": True,
            "stage_a_unchanged": True,
            "selection_mode": "automatic" if requested is None else "explicit",
            "legacy_paint_states_preserved_on_source_exterior": True,
            "nonexterior_carrier_faces_pure_black": True,
            "variable_outer_skin_thickness": bool(variable_thickness),
            "outer_skin_thickness_band_count": int(
                len(set(state_thicknesses.values()))
            ),
            "conventional_geometric_threshold_mm": float(
                conventional_threshold
            ),
        },
    )


def plan_radial_stage_b_from_eligible_partners(
    face_state_ids: np.ndarray,
    *,
    eligible_state_partners: Mapping[int, int],
    black_extruder: int,
    outer_skin_thickness_mm: float,
    state_skin_thickness_mm: Mapping[int, float] | None = None,
) -> RadialStageBPlan:
    """Plan from an already contrast-gated state-to-partner mapping.

    This is the narrow workflow adapter requested by the application layer.
    The caller has already run :func:`analyze_radial_partner_contrast`, so the
    mapping deliberately contains only user-selected, high-contrast states.
    Since the compact mapping does not retain the measured L* values, those
    optional report fields remain ``None``; the workflow must report its
    original contrast analysis alongside this geometry result.
    """

    raw_states = np.asarray(face_state_ids)
    if raw_states.ndim != 1 or not len(raw_states):
        _raise("face_states_required", shape=tuple(raw_states.shape))
    if not np.issubdtype(raw_states.dtype, np.integer):
        _raise("noninteger_face_states")
    minimum_state = int(raw_states.min())
    maximum_state = int(raw_states.max())
    if minimum_state < 0:
        _raise("negative_face_state", minimum=minimum_state)
    if maximum_state > np.iinfo(np.int16).max:
        _raise("face_state_out_of_range", maximum=maximum_state)
    states = np.asarray(raw_states, dtype=np.int16)

    if (
        isinstance(black_extruder, (bool, np.bool_))
        or not isinstance(black_extruder, Integral)
        or not 1 <= int(black_extruder) <= 4
    ):
        _raise("invalid_black_extruder", black_extruder=black_extruder)
    black = int(black_extruder)
    if isinstance(outer_skin_thickness_mm, (bool, np.bool_)):
        _raise(
            "invalid_outer_skin_thickness",
            value=outer_skin_thickness_mm,
        )
    try:
        thickness = float(outer_skin_thickness_mm)
    except (TypeError, ValueError) as exc:
        raise RadialStageBError(
            "invalid_outer_skin_thickness",
            {"value": outer_skin_thickness_mm},
        ) from exc
    if not math.isfinite(thickness) or thickness <= 0.0:
        _raise(
            "invalid_outer_skin_thickness",
            value=outer_skin_thickness_mm,
        )

    normalized: dict[int, int] = {}
    for raw_state, raw_partner in eligible_state_partners.items():
        if (
            isinstance(raw_state, (bool, np.bool_))
            or not isinstance(raw_state, Integral)
            or int(raw_state) < 4
        ):
            _raise("invalid_eligible_state", state_id=raw_state)
        if (
            isinstance(raw_partner, (bool, np.bool_))
            or not isinstance(raw_partner, Integral)
            or not 1 <= int(raw_partner) <= 4
        ):
            _raise(
                "invalid_partner_extruder",
                state_id=int(raw_state),
                partner_extruder=raw_partner,
            )
        state_id = int(raw_state)
        partner = int(raw_partner)
        if partner == black:
            _raise(
                "partner_matches_black_extruder",
                state_id=state_id,
                black_extruder=black,
            )
        normalized[state_id] = partner

    used = tuple(int(value) for value in np.unique(states))
    selected = tuple(state_id for state_id in used if state_id in normalized)
    if not selected:
        _raise(
            "no_selected_eligible_state",
            used_state_ids=list(used),
        )
    conventional = tuple(sorted(set(used) - set(selected)))
    if not conventional:
        _raise(
            "hybrid_conventional_surface_required",
            radial_state_ids=list(selected),
        )
    state_thicknesses, conventional_threshold, variable_thickness = (
        _normalise_state_skin_thicknesses(
            state_skin_thickness_mm,
            selected_state_ids=selected,
            default_thickness_mm=thickness,
        )
    )
    decisions: list[RadialStageBStateDecision] = []
    recipes: dict[int, ColorDepthRecipe] = {}
    for state_id in used:
        if state_id in normalized:
            disposition = "radial"
            reason = "prequalified-high-lstar-black-mix"
            partner: int | None = normalized[state_id]
            outer = partner
        else:
            disposition = "conventional"
            reason = (
                "pure-black-preserved"
                if state_id == black - 1
                else "not-prequalified-for-radial"
            )
            partner = None
            outer = black
        state_thickness = (
            state_thicknesses[state_id]
            if state_id in selected
            else conventional_threshold
        )
        recipes[state_id] = ColorDepthRecipe(
            target_label=state_id,
            outer_physical=int(outer),
            outer_thickness_mm=state_thickness,
            backing_physical=black,
            calibrated=False,
            metadata={
                "radial_stage_b": True,
                "disposition": disposition,
                "original_paint_state": state_id,
                "eligibility_prevalidated_by_workflow": True,
                "adaptive_outer_skin": bool(variable_thickness),
            },
        )
        decisions.append(
            RadialStageBStateDecision(
                state_id=state_id,
                disposition=disposition,
                reason=reason,
                black_extruder=black,
                partner_extruder=partner,
                lstar_delta=None,
                outer_physical=int(outer),
                backing_physical=black,
                outer_skin_thickness_mm=state_thickness,
            )
        )
    return RadialStageBPlan(
        black_extruder=black,
        black_lstar=None,
        minimum_lstar_delta=None,
        outer_skin_thickness_mm=thickness,
        used_state_ids=used,
        radial_state_ids=selected,
        conventional_state_ids=conventional,
        state_outer_skin_thickness_mm={
            state_id: float(state_thicknesses[state_id])
            for state_id in selected
        },
        state_decisions=tuple(decisions),
        recipes=recipes,
        face_state_sha256=_state_fingerprint(states),
        metadata={
            "schema": RADIAL_STAGE_B_SCHEMA,
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "writer_ready": False,
            "hybrid_writer_required": True,
            "normal_writer_unchanged": True,
            "stage_a_unchanged": True,
            "selection_mode": "prequalified-mapping",
            "contrast_values_available_in_plan": False,
            "contrast_report_owned_by_workflow": True,
            "legacy_paint_states_preserved_on_source_exterior": True,
            "nonexterior_faces_unpainted_physical": True,
            "variable_outer_skin_thickness": bool(variable_thickness),
            "outer_skin_thickness_band_count": int(
                len(set(state_thicknesses.values()))
            ),
            "conventional_geometric_threshold_mm": float(
                conventional_threshold
            ),
        },
    )


def _canonical_face_key(face: np.ndarray) -> tuple[int, int, int]:
    return tuple(sorted(int(value) for value in face))


def restore_stage_b_paint_states(
    source: ColorDepthSourceSurface,
    partition: ConformingColorDepthPartition,
    manifold: MaterialManifoldResult,
    plan: RadialStageBPlan,
) -> tuple[RadialStageBPart, ...]:
    """Restore original paint only where a material face is truly exterior."""

    source_states = np.asarray(source.face_target_labels, dtype=np.int16)
    if source_states.shape != (len(source.faces),):
        _raise("source_face_state_shape_mismatch")
    if _state_fingerprint(source_states) != plan.face_state_sha256:
        _raise("source_face_states_changed_after_plan")
    exterior = np.asarray(partition.exterior_faces, dtype=np.int32)
    exterior_parents = np.asarray(
        partition.exterior_source_face_ids, dtype=np.int32
    )
    if exterior.ndim != 2 or exterior.shape[1:] != (3,):
        _raise("invalid_partition_exterior_faces")
    if exterior_parents.shape != (len(exterior),):
        _raise("invalid_partition_exterior_provenance")
    if len(exterior_parents) and (
        int(exterior_parents.min()) < 0
        or int(exterior_parents.max()) >= len(source.faces)
    ):
        _raise("partition_exterior_source_face_out_of_range")
    exterior_by_key: dict[tuple[int, int, int], int] = {}
    for face, parent in zip(exterior, exterior_parents, strict=True):
        key = _canonical_face_key(face)
        if key in exterior_by_key:
            _raise("duplicate_partition_exterior_face", face=list(key))
        exterior_by_key[key] = int(parent)

    decisions = {item.state_id: item for item in plan.state_decisions}
    seen_exterior: set[tuple[int, int, int]] = set()
    results: list[RadialStageBPart] = []
    for raw_part in manifold.parts:
        extruder = int(raw_part.extruder)
        if extruder != plan.black_extruder and not any(
            item.disposition == "radial"
            and item.partner_extruder == extruder
            for item in plan.state_decisions
        ):
            _raise("unexpected_stage_b_material", extruder=extruder)
        source_faces = np.asarray(raw_part.source_faces, dtype=np.int32)
        output_sources = np.asarray(raw_part.output_face_source, dtype=np.int32)
        output_faces = np.asarray(raw_part.faces, dtype=np.int32)
        if source_faces.ndim != 2 or source_faces.shape[1:] != (3,):
            _raise("invalid_manifold_source_faces", extruder=extruder)
        if output_sources.shape != (len(output_faces),):
            _raise("invalid_manifold_output_face_source", extruder=extruder)
        if len(output_sources) and (
            int(output_sources.min()) < 0
            or int(output_sources.max()) >= len(source_faces)
        ):
            _raise("manifold_output_face_source_out_of_range", extruder=extruder)

        source_parent_ids = np.full(len(source_faces), -1, dtype=np.int32)
        referenced_source_rows = set(int(value) for value in output_sources)
        for index, face in enumerate(source_faces):
            key = _canonical_face_key(face)
            parent = exterior_by_key.get(key)
            if parent is None:
                continue
            if index not in referenced_source_rows:
                _raise(
                    "partition_exterior_source_not_emitted",
                    extruder=extruder,
                    face=list(key),
                )
            if key in seen_exterior:
                _raise("partition_exterior_owned_more_than_once", face=list(key))
            seen_exterior.add(key)
            source_parent_ids[index] = int(parent)

        output_parent_ids = source_parent_ids[output_sources]
        external = output_parent_ids >= 0
        # ``-1`` is the writer contract for an unpainted physical face.  Only
        # the carrier's true source exterior regains a legacy paint state;
        # material interfaces and every physical partner-shell face must stay
        # unpainted so the slicer cannot reinterpret an internal boundary as
        # another virtual colour.
        paint = np.full(len(output_faces), -1, dtype=np.int16)
        if extruder == plan.black_extruder:
            paint[external] = source_states[output_parent_ids[external]]
            exposed_selected = sorted(
                set(int(value) for value in paint[external])
                & set(plan.radial_state_ids)
            )
            if exposed_selected:
                _raise(
                    "eligible_surface_exposed_on_black_carrier",
                    state_ids=exposed_selected,
                )
            role = "conventional_painted_carrier"
        else:
            for parent in output_parent_ids[external]:
                state_id = int(source_states[int(parent)])
                decision = decisions.get(state_id)
                if (
                    decision is None
                    or decision.disposition != "radial"
                    or decision.partner_extruder != extruder
                ):
                    _raise(
                        "partner_shell_owns_nonselected_exterior",
                        extruder=extruder,
                        state_id=state_id,
                    )
            role = "partner_outer_shell"

        results.append(
            RadialStageBPart(
                name=(
                    "Stage B black carrier/core"
                    if extruder == plan.black_extruder
                    else f"Stage B F{extruder} partner shell"
                ),
                role=role,
                physical_extruder=extruder,
                vertices_mm=_immutable(raw_part.vertices_mm, np.float64),
                faces=_immutable(output_faces, np.int32),
                paint_state_ids=_immutable(paint, np.int16),
                source_face_ids=_immutable(output_parent_ids, np.int32),
                external_face_mask=_immutable(external, np.bool_),
                metadata={
                    **dict(raw_part.metadata),
                    "radial_stage_b_role": role,
                    "external_output_faces": int(np.count_nonzero(external)),
                    "internal_output_faces": int(np.count_nonzero(~external)),
                    "source_exterior_paint_restored": bool(
                        extruder == plan.black_extruder
                    ),
                    "source_exterior_is_physical_skin": bool(
                        extruder != plan.black_extruder
                    ),
                    "paint_state_contract": (
                        "-1=physical-or-internal; >=0=conventional-source-state"
                    ),
                },
            )
        )

    missing = sorted(set(exterior_by_key) - seen_exterior)
    if missing:
        _raise(
            "partition_exterior_not_owned",
            count=len(missing),
            examples=[list(value) for value in missing[:20]],
        )
    if not any(part.physical_extruder == plan.black_extruder for part in results):
        _raise("black_carrier_missing")
    expected_partners = {
        int(item.partner_extruder)
        for item in plan.state_decisions
        if item.disposition == "radial" and item.partner_extruder is not None
    }
    actual_partners = {
        part.physical_extruder
        for part in results
        if part.role == "partner_outer_shell"
    }
    if actual_partners != expected_partners:
        _raise(
            "partner_shell_set_mismatch",
            expected=sorted(expected_partners),
            actual=sorted(actual_partners),
        )
    return tuple(results)


def _verify_adaptive_partner_depth_independently(
    source: ColorDepthSourceSurface,
    plan: RadialStageBPlan,
    nodes: np.ndarray,
    tets: np.ndarray,
    owners: np.ndarray,
    materials: np.ndarray,
) -> Mapping[str, object]:
    """Recompute variable-skin partner depth without trusting provider metadata."""

    decisions = {item.state_id: item for item in plan.state_decisions}
    partner_cells = np.zeros(len(tets), dtype=bool)
    for state_id in plan.radial_state_ids:
        decision = decisions[int(state_id)]
        partner_cells |= (
            (owners == int(state_id))
            & (materials == int(decision.outer_physical))
        )
    partner_ids = np.flatnonzero(partner_cells)
    source_mesh = trimesh.Trimesh(
        vertices=np.asarray(source.vertices_mm, dtype=np.float64),
        faces=np.asarray(source.faces, dtype=np.int32),
        process=False,
    )
    maximum_sample_depth = 0.0
    sample_count = 0
    batch_cells = max(1, 20_000 // 15)
    for start in range(0, len(partner_ids), batch_cells):
        batch_ids = partner_ids[start : start + batch_cells]
        points = nodes[tets[batch_ids]]
        samples = np.concatenate(
            (
                points,
                0.5
                * (
                    points[:, _ADAPTIVE_TET_EDGES[:, 0]]
                    + points[:, _ADAPTIVE_TET_EDGES[:, 1]]
                ),
                points[:, _ADAPTIVE_TET_FACES].mean(axis=2),
                points.mean(axis=1, keepdims=True),
            ),
            axis=1,
        )
        try:
            _closest, distance, _faces = trimesh.proximity.closest_point(
                source_mesh,
                samples.reshape((-1, 3)),
            )
        except Exception as exc:
            _raise("adaptive_partner_depth_query_failed", error=str(exc))
        distance = np.asarray(distance, dtype=np.float64).reshape(
            (len(batch_ids), 15)
        )
        if not np.isfinite(distance).all():
            _raise("adaptive_partner_depth_query_nonfinite")
        sampled_maximum = distance.max(axis=1)
        requested = np.asarray(
            [
                float(plan.state_outer_skin_thickness_mm[int(owners[cell])])
                for cell in batch_ids
            ],
            dtype=np.float64,
        )
        overdepth = sampled_maximum - requested
        maximum_sample_depth = max(
            maximum_sample_depth,
            float(np.max(sampled_maximum, initial=0.0)),
        )
        sample_count += int(15 * len(batch_ids))
        if np.any(
            overdepth
            > float(_ADAPTIVE_PARTNER_DEPTH_TOLERANCE_MM) + 1e-12
        ):
            worst = int(np.argmax(overdepth))
            _raise(
                "adaptive_partner_cell_too_deep",
                target_label=int(owners[int(batch_ids[worst])]),
                threshold_mm=float(requested[worst]),
                sampled_depth_mm=float(sampled_maximum[worst]),
                overdepth_mm=float(overdepth[worst]),
                limit_mm=float(_ADAPTIVE_PARTNER_DEPTH_TOLERANCE_MM),
                proof_samples_per_cell=15,
                verifier="radial-stage-b-independent-source-distance",
            )
    return {
        "verifier": "radial-stage-b-independent-source-distance",
        "partner_cells": int(len(partner_ids)),
        "proof_samples_per_cell": 15,
        "true_distance_sample_count": int(sample_count),
        "maximum_partner_sample_depth_mm": float(maximum_sample_depth),
        "overdepth_tolerance_mm": float(
            _ADAPTIVE_PARTNER_DEPTH_TOLERANCE_MM
        ),
        "passed": True,
    }


def build_radial_stage_b_geometry(
    source: ColorDepthSourceSurface,
    plan: RadialStageBPlan,
    *,
    partition_provider: Callable[..., ConformingColorDepthPartition] | None = None,
    progress: Callable[..., object] | None = None,
) -> RadialStageBResult:
    """Build exact-touch hybrid parts while keeping archive export disabled."""

    source_states = np.asarray(source.face_target_labels, dtype=np.int16)
    if _state_fingerprint(source_states) != plan.face_state_sha256:
        _raise("source_face_states_changed_after_plan")
    provider = partition_provider or build_conforming_color_depth_partition
    adaptive_partner_depth_proof: Mapping[str, object] | None = None
    try:
        partition = provider(source, plan.recipes, progress=progress)
        nodes, tets, owners, _bounds, materials, unsafe = (
            _validate_partition_arrays(partition, plan.recipes)
        )
        if bool(plan.metadata.get("variable_outer_skin_thickness", False)):
            decisions = {item.state_id: item for item in plan.state_decisions}
            unsafe_partner_cells = np.zeros(len(tets), dtype=bool)
            for state_id in plan.radial_state_ids:
                decision = decisions[int(state_id)]
                unsafe_partner_cells |= (
                    (owners == int(state_id))
                    & unsafe
                    & (materials == int(decision.outer_physical))
                )
            if np.any(unsafe_partner_cells):
                _raise(
                    "adaptive_partner_unsafe_outer_cells",
                    cells=int(np.count_nonzero(unsafe_partner_cells)),
                    state_ids=[
                        int(value)
                        for value in np.unique(owners[unsafe_partner_cells])
                    ],
                )
            adaptive_partner_depth_proof = (
                _verify_adaptive_partner_depth_independently(
                    source,
                    plan,
                    nodes,
                    tets,
                    owners,
                    materials,
                )
            )
            if (
                partition.metadata.get(
                    "adaptive_partner_depth_samples_verified"
                )
                is not True
            ):
                _raise("adaptive_partner_depth_proof_required")
        visible = _validate_visible_exterior(
            source,
            partition,
            nodes,
            tets,
            owners,
            materials,
            plan.recipes,
        )
        manifold = manifoldize_labeled_tetrahedra(nodes, tets, materials)
    except RadialStageBError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", "stage_b_partition_validation_failed")
        details = dict(getattr(exc, "details", {}) or {})
        details.setdefault("error", str(exc))
        raise RadialStageBError(str(code), details) from exc
    if visible.get("external_surface_coverage_exact") is not True:
        _raise("source_exterior_coverage_proof_required")
    if partition.threshold_interface_conforming is not True:
        _raise("threshold_interface_not_conforming")
    if partition.shared_interface_partition_exact is not True:
        _raise("shared_interface_partition_proof_required")
    parts = restore_stage_b_paint_states(source, partition, manifold, plan)
    try:
        prepared_volume = float(source.source_volume_mm3)
        manifold_source_volume = float(manifold.source_volume_mm3)
        output_volume = float(manifold.output_volume_mm3)
    except (TypeError, ValueError) as exc:
        raise RadialStageBError(
            "invalid_stage_b_volume_proof",
            {"error": str(exc)},
        ) from exc
    if (
        not math.isfinite(prepared_volume)
        or not math.isfinite(manifold_source_volume)
        or not math.isfinite(output_volume)
        or prepared_volume <= 0.0
        or manifold_source_volume <= 0.0
        or output_volume <= 0.0
    ):
        _raise(
            "invalid_stage_b_volume_proof",
            prepared_source_volume_mm3=prepared_volume,
            partition_source_volume_mm3=manifold_source_volume,
            output_volume_mm3=output_volume,
        )
    partition_source_error = abs(manifold_source_volume - prepared_volume)
    volume_error = abs(output_volume - prepared_volume)
    tolerance = 1e-8 * max(prepared_volume, 1.0)
    if partition_source_error > tolerance or volume_error > tolerance:
        _raise(
            "stage_b_volume_mismatch",
            source_volume_mm3=prepared_volume,
            partition_source_volume_mm3=manifold_source_volume,
            output_volume_mm3=output_volume,
            partition_source_error_mm3=partition_source_error,
            volume_error_mm3=volume_error,
        )
    painted_exterior = int(
        sum(
            np.count_nonzero(part.external_face_mask)
            for part in parts
            if part.physical_extruder == plan.black_extruder
        )
    )
    material_metadata = dict(manifold.metadata or {})
    if material_metadata.get("external_surface_coverage_exact") is not True:
        _raise("material_manifold_exterior_proof_required")
    if material_metadata.get("shared_interface_partition_exact") is not True:
        _raise("material_manifold_interface_proof_required")
    try:
        gap_mm = float(material_metadata.get("gap_mm", math.inf))
    except (TypeError, ValueError):
        gap_mm = math.inf
    if not math.isfinite(gap_mm) or gap_mm != 0.0:
        _raise(
            "material_manifold_gap_detected",
            gap_mm=material_metadata.get("gap_mm"),
        )
    try:
        overlap_mm3 = float(
            material_metadata.get("positive_overlap_mm3", math.inf)
        )
    except (TypeError, ValueError):
        overlap_mm3 = math.inf
    if not math.isfinite(overlap_mm3) or overlap_mm3 != 0.0:
        _raise(
            "material_manifold_overlap_detected",
            positive_overlap_mm3=material_metadata.get(
                "positive_overlap_mm3"
            ),
        )
    return RadialStageBResult(
        plan=plan,
        parts=parts,
        interfaces=tuple(manifold.interfaces),
        source_volume_mm3=manifold_source_volume,
        output_volume_mm3=output_volume,
        metadata={
            "schema": RADIAL_STAGE_B_SCHEMA,
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "writer_ready": False,
            "hybrid_writer_required": True,
            "material_manifold": True,
            "source_exterior_preserved_exactly": True,
            "source_exterior_coverage_exact": True,
            "external_surface_coverage_exact": True,
            "shared_interface_partition_exact": True,
            "threshold_interface_conforming": True,
            "variable_outer_skin_thickness": bool(
                plan.metadata.get("variable_outer_skin_thickness", False)
            ),
            "state_outer_skin_thickness_mm": {
                str(state_id): float(thickness)
                for state_id, thickness in sorted(
                    plan.state_outer_skin_thickness_mm.items()
                )
            },
            **(
                {
                    "adaptive_partner_depth_proof": dict(
                        adaptive_partner_depth_proof
                    )
                }
                if adaptive_partner_depth_proof is not None
                else {}
            ),
            "gap_mm": 0.0,
            "positive_overlap_mm3": 0.0,
            "unsafe_outer_only_cells": int(np.count_nonzero(unsafe)),
            "painted_conventional_exterior_faces": painted_exterior,
            "nonexterior_carrier_faces_pure_black": True,
            "legacy_mix_definitions_required": True,
            "orca_hybrid_component_semantics_verified": False,
            "source_volume_mm3": manifold_source_volume,
            "output_volume_mm3": output_volume,
            "partition_source_error_mm3": partition_source_error,
            "volume_error_mm3": volume_error,
        },
    )


def build_selective_hybrid(
    prepared: object,
    height_mm: float,
    face_state_ids: np.ndarray,
    eligible_state_partners: Mapping[int, int],
    black_extruder: int,
    skin_thickness_mm: float,
    progress: Callable[..., object] | None = None,
    *,
    state_skin_thickness_mm: Mapping[int, float] | None = None,
) -> RadialStageBResult:
    """Application-facing Stage-B adapter with no change to existing writers."""

    plan = plan_radial_stage_b_from_eligible_partners(
        face_state_ids,
        eligible_state_partners=eligible_state_partners,
        black_extruder=black_extruder,
        outer_skin_thickness_mm=skin_thickness_mm,
        state_skin_thickness_mm=state_skin_thickness_mm,
    )
    supplied_source = (
        prepared if isinstance(prepared, ColorDepthSourceSurface) else None
    )
    request = SimpleNamespace(
        prepared=None if supplied_source is not None else prepared,
        source_surface=supplied_source,
        height_mm=height_mm,
        face_target_labels=np.asarray(face_state_ids),
        recipes=plan.recipes,
    )
    try:
        # Always pass through the canonical source validator.  A typed source
        # surface is a convenient transport, not permission to bypass the
        # watertight/winding/positive-volume and label checks.
        source = prepare_color_depth_source(request)
    except Exception as exc:
        code = getattr(exc, "code", "stage_b_source_preparation_failed")
        details = dict(getattr(exc, "details", {}) or {})
        details.setdefault("error", str(exc))
        raise RadialStageBError(str(code), details) from exc
    return build_radial_stage_b_geometry(source, plan, progress=progress)


def write_radial_stage_b_3mf(*_args: object, **_kwargs: object) -> None:
    """Keep the unvalidated mixed physical/paint archive boundary closed."""

    _raise(
        "hybrid_3mf_writer_not_implemented",
        required_validation=(
            "Snapmaker Orca component clipping, mixed-definition routing, "
            "serialized interface parity, and all-layer Filament inspection"
        ),
    )


__all__ = [
    "RADIAL_STAGE_B_SCHEMA",
    "RadialStageBError",
    "RadialStageBPart",
    "RadialStageBPlan",
    "RadialStageBResult",
    "RadialStageBStateDecision",
    "build_radial_stage_b_geometry",
    "build_selective_hybrid",
    "plan_radial_stage_b",
    "plan_radial_stage_b_from_eligible_partners",
    "restore_stage_b_paint_states",
    "write_radial_stage_b_3mf",
]
