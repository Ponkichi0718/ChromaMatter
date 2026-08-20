"""Explicit recipe planning for the experimental ColorDepth renderer.

The legacy FullSpectrum palette remains useful as a stable target-colour ID
and as a declaration of which two physical spools participate in a target.
Its layer percentages are deliberately *not* an input to ColorDepth.  This
module converts used zero-based palette labels into ordered physical-depth
recipes and records every target that collapses to the same provisional
recipe until a measured per-target LUT is available.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

import numpy as np

from .color_depth import ColorDepthError, ColorDepthRecipe
from .mixer import PHYSICAL_STATE_COUNT, normalize_hex, palette_mix_specs


COLOR_DEPTH_RECIPE_PLAN_SCHEMA = (
    "tripo-spectrum-mapper.color-depth.recipe-plan.experimental.v1"
)


def _raise(code: str, **details: object) -> None:
    raise ColorDepthError(code, details)


def relative_srgb_luminance(value: str) -> float:
    """Return WCAG relative luminance for one physical filament swatch."""

    text = normalize_hex(value)
    channels = np.asarray(
        [int(text[index : index + 2], 16) / 255.0 for index in (1, 3, 5)],
        dtype=np.float64,
    )
    linear = np.where(
        channels <= 0.04045,
        channels / 12.92,
        ((channels + 0.055) / 1.055) ** 2.4,
    )
    return float(
        0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    )


@dataclass(frozen=True, slots=True)
class ColorDepthRecipePlan:
    """A complete explicit plan for the target labels present in one mesh."""

    recipes: Mapping[int, ColorDepthRecipe]
    target_labels: tuple[int, ...]
    collapsed_target_groups: tuple[tuple[int, ...], ...]
    physical_hex: tuple[str, str, str, str]
    outer_thickness_mm: float
    calibrated: bool
    metadata: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": COLOR_DEPTH_RECIPE_PLAN_SCHEMA,
            "target_label_base": 0,
            "target_labels": list(self.target_labels),
            "physical_hex": list(self.physical_hex),
            "outer_thickness_mm": float(self.outer_thickness_mm),
            "calibrated": bool(self.calibrated),
            "legacy_mix_percentages_used": False,
            "recipes": {
                str(label): {
                    "target_label": int(recipe.target_label),
                    "outer_physical": int(recipe.outer_physical),
                    "outer_thickness_mm": float(recipe.outer_thickness_mm),
                    "backing_physical": int(recipe.backing_physical),
                    "backing_depth_mm": recipe.backing_depth_mm,
                    "core_physical": recipe.core_physical,
                    "calibrated": bool(recipe.calibrated),
                    "calibration_id": recipe.calibration_id,
                    "metadata": dict(recipe.metadata),
                }
                for label, recipe in sorted(self.recipes.items())
            },
            "collapsed_target_groups": [
                list(group) for group in self.collapsed_target_groups
            ],
            "metadata": dict(self.metadata),
        }


def build_uncalibrated_common_skin_recipes(
    palette: object,
    target_labels: Sequence[int],
    *,
    outer_thickness_mm: float = 0.15,
) -> ColorDepthRecipePlan:
    """Build the first fail-closed all-colour ColorDepth laboratory plan.

    Pure labels remain their physical material.  A mixed label uses the
    brighter physical member outside and the other member as an unlimited
    backing.  The old percentage is ignored completely.  Repeated shades of
    one physical pair therefore collapse and are reported explicitly rather
    than pretending that the provisional renderer can reproduce them.
    """

    thickness = float(outer_thickness_mm)
    if not math.isfinite(thickness) or thickness <= 0.0:
        _raise("invalid_outer_thickness", outer_thickness_mm=outer_thickness_mm)

    try:
        raw_hex = tuple(normalize_hex(value) for value in palette.physical_hex)
        state_count = int(palette.palette_state_count)
        mix_specs = palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        _raise("invalid_palette_for_color_depth", error=str(exc))
    if len(raw_hex) != PHYSICAL_STATE_COUNT:
        _raise("four_physical_filaments_required", count=len(raw_hex))
    if state_count not in (16, 24, 32):
        _raise("invalid_palette_state_count", palette_state_count=state_count)

    labels: list[int] = []
    for raw_label in target_labels:
        if isinstance(raw_label, (bool, np.bool_)):
            _raise("invalid_target_label", target_label=raw_label)
        label = int(raw_label)
        if label < 0 or label >= state_count:
            _raise(
                "target_label_out_of_range",
                target_label=label,
                palette_state_count=state_count,
            )
        labels.append(label)
    labels = sorted(set(labels))
    if not labels:
        _raise("target_labels_required")

    luminance = tuple(relative_srgb_luminance(value) for value in raw_hex)
    recipes: dict[int, ColorDepthRecipe] = {}
    signature_groups: dict[tuple[int, float, int], list[int]] = {}
    ignored_legacy_ratios: dict[int, int] = {}
    for label in labels:
        if label < PHYSICAL_STATE_COUNT:
            outer = backing = label + 1
            pair_zero_based = (label, label)
            legacy_ratio = None
            source_kind = "pure-physical"
        else:
            mixed_index = label - PHYSICAL_STATE_COUNT
            if mixed_index >= len(mix_specs):
                _raise("mixed_target_has_no_pair", target_label=label)
            left, right, legacy_ratio = mix_specs[mixed_index]
            delta = luminance[left] - luminance[right]
            if abs(delta) <= 1e-12:
                _raise(
                    "provisional_outer_material_ambiguous",
                    target_label=label,
                    physical_pair=(left + 1, right + 1),
                )
            outer_zero = left if delta > 0.0 else right
            backing_zero = right if outer_zero == left else left
            outer, backing = outer_zero + 1, backing_zero + 1
            pair_zero_based = (left, right)
            ignored_legacy_ratios[label] = int(legacy_ratio)
            source_kind = "mixed-target-pair-only"

        recipe = ColorDepthRecipe(
            target_label=label,
            outer_physical=outer,
            outer_thickness_mm=thickness,
            backing_physical=backing,
            calibrated=False,
            metadata={
                "provisional": True,
                "source_kind": source_kind,
                "legacy_physical_pair": [
                    int(pair_zero_based[0]) + 1,
                    int(pair_zero_based[1]) + 1,
                ],
                "legacy_ratio_ignored": legacy_ratio is not None,
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
        if len(group) > 1 and any(label >= PHYSICAL_STATE_COUNT for label in group)
    )
    return ColorDepthRecipePlan(
        recipes=recipes,
        target_labels=tuple(labels),
        collapsed_target_groups=collapsed,
        physical_hex=raw_hex,  # type: ignore[arg-type]
        outer_thickness_mm=thickness,
        calibrated=False,
        metadata={
            "experimental": True,
            "slice_only": True,
            "print_allowed": False,
            "legacy_mix_percentages_used": False,
            "ignored_legacy_ratios_by_target": ignored_legacy_ratios,
            "recipe_policy": "common-skin-provisional-v1",
            "target_shades_collapsed": bool(collapsed),
            "calibration_required_for_colour_accuracy": True,
        },
    )


__all__ = [
    "COLOR_DEPTH_RECIPE_PLAN_SCHEMA",
    "ColorDepthRecipePlan",
    "build_uncalibrated_common_skin_recipes",
    "relative_srgb_luminance",
]
