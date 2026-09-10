"""Deterministic discrete thickness schedules for selective radial Stage B.

This module deliberately does not change application settings or the normal
Full Spectrum writer.  It converts existing black/partner palette states into
an explicit, at-most-six-band thickness map which callers may opt into when
building selective radial geometry.  The mapping is an uncalibrated laboratory
heuristic; physical calibration remains a separate requirement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral
from typing import Mapping

import numpy as np

from .filament_database import srgb_hex_to_lab
from .mixer import build_palette_rgb, palette_mix_specs


RADIAL_THICKNESS_SCHEDULE_SCHEMA = (
    "tripo-spectrum-mapper.radial-thickness-schedule.experimental.v1"
)


class RadialThicknessError(ValueError):
    """Stable fail-closed diagnostic for an invalid thickness schedule."""

    def __init__(
        self,
        code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(self.code)


def _raise(code: str, **details: object) -> None:
    raise RadialThicknessError(code, details)


@dataclass(frozen=True, slots=True)
class RadialThicknessState:
    state_id: int
    partner_extruder: int
    ratio_b_percent: int
    partner_fraction: float
    target_lstar: float
    normalized_lightness: float
    mapping_fraction: float
    curved_fraction: float
    band_index: int
    thickness_mm: float

    def to_dict(self) -> dict[str, object]:
        return {
            "state_id": int(self.state_id),
            "partner_extruder": int(self.partner_extruder),
            "ratio_b_percent": int(self.ratio_b_percent),
            "partner_fraction": float(self.partner_fraction),
            "target_lstar": float(self.target_lstar),
            "normalized_lightness": float(self.normalized_lightness),
            "mapping_fraction": float(self.mapping_fraction),
            "curved_fraction": float(self.curved_fraction),
            "band_index": int(self.band_index),
            "thickness_mm": float(self.thickness_mm),
        }


@dataclass(frozen=True, slots=True)
class RadialThicknessSchedule:
    basis: str
    minimum_thickness_mm: float
    maximum_thickness_mm: float
    band_count: int
    gamma: float
    black_extruder: int
    black_lstar: float
    states: tuple[RadialThicknessState, ...]

    @property
    def thickness_by_state(self) -> dict[int, float]:
        return {
            int(item.state_id): float(item.thickness_mm)
            for item in self.states
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RADIAL_THICKNESS_SCHEDULE_SCHEMA,
            "experimental": True,
            "calibrated": False,
            "basis": self.basis,
            "minimum_thickness_mm": float(self.minimum_thickness_mm),
            "maximum_thickness_mm": float(self.maximum_thickness_mm),
            "band_count": int(self.band_count),
            "gamma": float(self.gamma),
            "black_extruder": int(self.black_extruder),
            "black_lstar": float(self.black_lstar),
            "thickness_by_state": {
                str(state): float(thickness)
                for state, thickness in sorted(self.thickness_by_state.items())
            },
            "states": [item.to_dict() for item in self.states],
        }


def _finite_thickness(value: object, *, field: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        _raise("invalid_thickness", field=field, value=value)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RadialThicknessError(
            "invalid_thickness", {"field": field, "value": value}
        ) from exc
    if not math.isfinite(result) or result <= 0.0:
        _raise("invalid_thickness", field=field, value=value)
    return result


def derive_radial_thickness_schedule(
    palette: object,
    *,
    black_slot: int,
    eligible_state_partners: Mapping[int, int],
    minimum_thickness_mm: float,
    maximum_thickness_mm: float,
    band_count: int = 5,
    gamma: float = 1.0,
    basis: str = "target_lstar",
    target_lstar_by_state: Mapping[int, float] | None = None,
) -> RadialThicknessSchedule:
    """Quantize black/partner states into four-to-six physical depth bands.

    ``basis='mix_ratio'`` maps the partner percentage directly.  The default
    ``basis='target_lstar'`` first converts the palette state's displayed sRGB
    mixture to CIELAB L* (or uses an explicit target-L* override) and then
    normalizes that target between physical black and its partner.  Both paths
    are deterministic and intentionally uncalibrated.  ``gamma`` is applied
    before band quantization using the same formula as
    :meth:`RadialSettings.skin_thickness_for_lstar`, so UI preview and export
    cannot silently select different depth bands.
    """

    if (
        isinstance(black_slot, (bool, np.bool_))
        or not isinstance(black_slot, Integral)
        or not 0 <= int(black_slot) < 4
    ):
        _raise("invalid_black_slot", black_slot=black_slot)
    selected = int(black_slot)
    minimum = _finite_thickness(
        minimum_thickness_mm,
        field="minimum_thickness_mm",
    )
    maximum = _finite_thickness(
        maximum_thickness_mm,
        field="maximum_thickness_mm",
    )
    if maximum + 1e-12 < minimum:
        _raise(
            "thickness_range_reversed",
            minimum_thickness_mm=minimum,
            maximum_thickness_mm=maximum,
        )
    if (
        isinstance(band_count, (bool, np.bool_))
        or not isinstance(band_count, Integral)
        or not 4 <= int(band_count) <= 6
    ):
        _raise("invalid_band_count", band_count=band_count, allowed=[4, 5, 6])
    bands = int(band_count)
    if isinstance(gamma, (bool, np.bool_)):
        _raise("invalid_gamma", gamma=gamma)
    try:
        gamma_value = float(gamma)
    except (TypeError, ValueError) as exc:
        raise RadialThicknessError(
            "invalid_gamma", {"gamma": gamma}
        ) from exc
    if not math.isfinite(gamma_value) or not 0.25 <= gamma_value <= 4.0:
        _raise("invalid_gamma", gamma=gamma, allowed=[0.25, 4.0])
    if basis not in {"mix_ratio", "target_lstar"}:
        _raise("invalid_thickness_basis", basis=basis)

    try:
        physical_hex = tuple(str(value) for value in palette.physical_hex)
        palette_state_count = int(palette.palette_state_count)
        specs = palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
        palette_hex, _palette_rgb = build_palette_rgb(
            list(physical_hex),
            list(palette.mix_hex_overrides),
            list(palette.mix_ratios_b),
            list(palette.secondary_mix_ratios_b),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RadialThicknessError(
            "invalid_palette", {"error": str(exc)}
        ) from exc
    if len(physical_hex) != 4:
        _raise("invalid_palette", physical_color_count=len(physical_hex))
    physical_lstar = tuple(
        float(srgb_hex_to_lab(value)[0]) for value in physical_hex
    )
    black_lstar = physical_lstar[selected]

    normalized_eligible: dict[int, int] = {}
    for raw_state, raw_partner in eligible_state_partners.items():
        if (
            isinstance(raw_state, (bool, np.bool_))
            or not isinstance(raw_state, Integral)
            or not 4 <= int(raw_state) < palette_state_count
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
        normalized_eligible[int(raw_state)] = int(raw_partner)
    if not normalized_eligible:
        _raise("eligible_states_required")

    target_overrides: dict[int, object] = {}
    for raw_state, raw_target in (target_lstar_by_state or {}).items():
        if (
            isinstance(raw_state, (bool, np.bool_))
            or not isinstance(raw_state, Integral)
        ):
            _raise("invalid_target_lstar_state", state_id=raw_state)
        target_overrides[int(raw_state)] = raw_target
    unknown_targets = sorted(set(target_overrides) - set(normalized_eligible))
    if unknown_targets:
        _raise("target_lstar_state_not_eligible", state_ids=unknown_targets)

    states: list[RadialThicknessState] = []
    for state_id, partner_extruder in sorted(normalized_eligible.items()):
        offset = state_id - 4
        if not 0 <= offset < len(specs):
            _raise("eligible_state_has_no_mix_spec", state_id=state_id)
        left, right, ratio_b = specs[offset]
        if selected not in (left, right):
            _raise("eligible_state_is_not_black_mix", state_id=state_id)
        partner = right if left == selected else left
        if partner_extruder != partner + 1:
            _raise(
                "eligible_partner_mismatch",
                state_id=state_id,
                expected_partner_extruder=partner + 1,
                actual_partner_extruder=partner_extruder,
            )
        partner_fraction = (
            float(ratio_b) / 100.0
            if right == partner
            else (100.0 - float(ratio_b)) / 100.0
        )
        computed_target_lstar = float(srgb_hex_to_lab(palette_hex[state_id])[0])
        explicit_target = state_id in target_overrides
        raw_target = target_overrides.get(state_id, computed_target_lstar)
        if isinstance(raw_target, (bool, np.bool_)):
            _raise("invalid_target_lstar", state_id=state_id, value=raw_target)
        try:
            target_lstar = float(raw_target)
        except (TypeError, ValueError) as exc:
            raise RadialThicknessError(
                "invalid_target_lstar",
                {"state_id": state_id, "value": raw_target},
            ) from exc
        if not math.isfinite(target_lstar):
            _raise("invalid_target_lstar", state_id=state_id, value=raw_target)
        if explicit_target:
            if not 0.0 <= target_lstar <= 100.0:
                _raise(
                    "invalid_target_lstar",
                    state_id=state_id,
                    value=raw_target,
                )
        else:
            # The standard Lab conversion of exact sRGB white may land a few
            # ULPs above 100 (for example 100.000003866...).  Computed display
            # colours may absorb that numerical roundoff, while explicit user
            # targets retain the strict public [0, 100] contract.
            if not -1e-5 <= target_lstar <= 100.0 + 1e-5:
                _raise(
                    "invalid_target_lstar",
                    state_id=state_id,
                    value=raw_target,
                )
            target_lstar = min(100.0, max(0.0, target_lstar))
        partner_lstar = physical_lstar[partner]
        lstar_span = partner_lstar - black_lstar
        if lstar_span <= 1e-12:
            _raise(
                "partner_not_lighter_than_black",
                state_id=state_id,
                black_lstar=black_lstar,
                partner_lstar=partner_lstar,
            )
        # RadialSettings.skin_thickness_for_lstar intentionally clips rather
        # than rejects an empirical/overridden display colour just outside
        # the physical endpoints.  Keep the export schedule bit-for-bit on
        # that public preview contract.
        lightness_fraction = min(
            1.0,
            max(0.0, (target_lstar - black_lstar) / lstar_span),
        )
        normalized = (
            partner_fraction if basis == "mix_ratio" else lightness_fraction
        )
        curved = normalized**gamma_value
        band_index = int(math.floor(curved * (bands - 1) + 0.5))
        band_index = max(0, min(bands - 1, band_index))
        thickness = (
            maximum
            if abs(maximum - minimum) <= 1e-12
            else minimum
            + (maximum - minimum) * band_index / float(bands - 1)
        )
        states.append(
            RadialThicknessState(
                state_id=state_id,
                partner_extruder=partner_extruder,
                ratio_b_percent=int(ratio_b),
                partner_fraction=partner_fraction,
                target_lstar=target_lstar,
                normalized_lightness=lightness_fraction,
                mapping_fraction=normalized,
                curved_fraction=curved,
                band_index=band_index,
                thickness_mm=float(thickness),
            )
        )

    return RadialThicknessSchedule(
        basis=basis,
        minimum_thickness_mm=minimum,
        maximum_thickness_mm=maximum,
        band_count=bands,
        gamma=gamma_value,
        black_extruder=selected + 1,
        black_lstar=black_lstar,
        states=tuple(states),
    )


__all__ = [
    "RADIAL_THICKNESS_SCHEDULE_SCHEMA",
    "RadialThicknessError",
    "RadialThicknessSchedule",
    "RadialThicknessState",
    "derive_radial_thickness_schedule",
]
