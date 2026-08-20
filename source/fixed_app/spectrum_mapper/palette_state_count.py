from __future__ import annotations

import copy
from dataclasses import dataclass, fields

from .mixer import PALETTE_STATE_COUNT, coerce_palette_state_count
from .models import AppSettings, PaletteSettings


@dataclass(frozen=True)
class PaletteStateCountChange:
    """Result of one explicit palette-size change from the UI.

    ``updated_part_palettes`` counts only saved, explicit part palettes.  Parts
    which inherit the common palette follow it automatically and therefore do
    not need a new local palette entry.
    """

    palette: PaletteSettings
    state_count: int
    target_part_key: str | None
    updated_part_palettes: int


def palette_with_state_count(
    palette: PaletteSettings,
    state_count: int,
) -> PaletteSettings:
    """Return an independent palette resized by an explicit user action.

    Existing enabled flags inside both the old and new ranges are retained.
    Newly exposed states are enabled, matching the established 16/24/32
    combobox behaviour.  States outside the selected range are disabled as
    required by :class:`PaletteSettings`; physical colours, ratios, output
    recipes, black-free settings and stable state IDs are otherwise copied.
    """

    count = coerce_palette_state_count(state_count)
    previous = coerce_palette_state_count(palette.palette_state_count)
    enabled = list(palette.enabled_states)
    if len(enabled) < PALETTE_STATE_COUNT:
        enabled += [False] * (PALETTE_STATE_COUNT - len(enabled))
    else:
        enabled = enabled[:PALETTE_STATE_COUNT]
    for index in range(PALETTE_STATE_COUNT):
        if index >= count:
            enabled[index] = False
        elif index >= previous:
            enabled[index] = True

    # Build from all current dataclass fields so future palette options are
    # preserved automatically.  deepcopy prevents later list edits in one
    # part palette from leaking into another palette.
    values = {
        item.name: copy.deepcopy(getattr(palette, item.name))
        for item in fields(PaletteSettings)
        if item.init
    }
    values["palette_state_count"] = count
    values["enabled_states"] = enabled
    return PaletteSettings(**values)


def apply_palette_state_count_change(
    settings: AppSettings,
    state_count: int,
    *,
    target_part_key: str | None,
) -> PaletteStateCountChange:
    """Apply one explicit 16/24/32 selection to common or one part.

    Selecting the common target updates the common palette and every *existing*
    explicit part palette.  It deliberately does not create redundant local
    palettes for inheriting parts.  Selecting a part changes only that part,
    creating a local copy from the common palette when necessary.

    This function is intentionally called only from user change handlers.  It
    must not be used while loading a project or merely switching edit targets.
    """

    count = coerce_palette_state_count(state_count)
    if target_part_key is None:
        settings.palette = palette_with_state_count(settings.palette, count)
        for key, palette in tuple(settings.part_palettes.items()):
            settings.part_palettes[key] = palette_with_state_count(
                palette,
                count,
            )
        return PaletteStateCountChange(
            palette=settings.palette,
            state_count=count,
            target_part_key=None,
            updated_part_palettes=len(settings.part_palettes),
        )

    key = str(target_part_key)
    current = settings.part_palettes.get(key, settings.palette)
    settings.part_palettes[key] = palette_with_state_count(current, count)
    return PaletteStateCountChange(
        palette=settings.part_palettes[key],
        state_count=count,
        target_part_key=key,
        updated_part_palettes=1,
    )
