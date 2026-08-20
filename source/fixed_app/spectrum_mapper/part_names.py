from __future__ import annotations

from collections.abc import Mapping
import re

from .models import PreparedGeometry


MAX_PART_NAME_LENGTH = 120
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class PartNameError(ValueError):
    """Raised when a user-facing part name is missing or ambiguous."""


def normalize_part_name(value: object) -> str:
    """Return a safe display/export name without changing its language.

    Names may contain Japanese text, spaces and normal punctuation.  Control
    characters are rejected because they make the selector ambiguous and can
    produce invalid 3MF metadata.  Filename-specific characters are allowed;
    individual-part export already replaces them in the generated filename.
    """

    name = str(value).strip()
    if not name:
        raise PartNameError("パーツ名を入力してください。")
    if _CONTROL_CHARACTERS.search(name):
        raise PartNameError("パーツ名に改行や制御文字は使用できません。")
    if len(name) > MAX_PART_NAME_LENGTH:
        raise PartNameError(
            f"パーツ名は {MAX_PART_NAME_LENGTH} 文字以内で入力してください。"
        )
    return name


def validate_unique_part_name(
    value: object,
    existing_names: tuple[str, ...] | list[str],
    *,
    current_index: int | None = None,
) -> str:
    """Normalize ``value`` and reject duplicate selector labels.

    Matching uses ``casefold`` so names that differ only by ASCII case cannot
    become indistinguishable in the editor or exported manifests.
    """

    name = normalize_part_name(value)
    folded = name.casefold()
    for index, existing in enumerate(existing_names):
        if current_index is not None and index == current_index:
            continue
        if str(existing).strip().casefold() == folded:
            raise PartNameError(f"同じパーツ名が既にあります: {name}")
    return name


def _replace_prepared_names(
    prepared: PreparedGeometry,
    names_by_key: Mapping[str, str],
) -> None:
    """Replace display metadata atomically after all names were validated."""

    for level in (prepared.final, prepared.preview):
        keys = tuple(level.part_keys)
        names = list(level.part_names)
        if len(names) != len(keys):
            raise PartNameError("パーツ名とパーツIDの数が一致していません。")
        for index, key in enumerate(keys):
            if key in names_by_key:
                names[index] = names_by_key[key]
        level.part_names = tuple(names)

    prepared.part_names = tuple(prepared.final.part_names)
    final_keys = tuple(prepared.final.part_keys)
    key_to_index = {key: index for index, key in enumerate(final_keys)}
    for stat in prepared.part_stats:
        stat_key = str(stat.get("key", ""))
        if stat_key in names_by_key:
            stat["name"] = names_by_key[stat_key]
            continue
        try:
            stat_index = int(stat.get("id", -1))
        except (TypeError, ValueError):
            continue
        if 0 <= stat_index < len(final_keys):
            key = final_keys[stat_index]
            if key in names_by_key:
                stat["name"] = names_by_key[key]

    # Joint history keeps keys/indices as identity; refresh any descriptive
    # name fields so reports do not retain stale labels.
    assembly = dict(prepared.assembly or {})
    for record_key in ("manual_joint_records", "joint_records"):
        records = assembly.get(record_key)
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            for side in ("male", "female"):
                key = str(record.get(f"{side}_part_key", ""))
                if not key:
                    try:
                        part_id = int(record.get(f"{side}_part_id", -1))
                    except (TypeError, ValueError):
                        part_id = -1
                    if 0 <= part_id < len(final_keys):
                        key = final_keys[part_id]
                if key in names_by_key:
                    record[f"{side}_part_name"] = names_by_key[key]
    prepared.assembly = assembly


def rename_prepared_part(
    prepared: PreparedGeometry,
    part_key: str,
    value: object,
) -> str:
    """Rename one part while preserving its immutable key and all face IDs."""

    keys = tuple(prepared.final.part_keys)
    try:
        part_index = keys.index(str(part_key))
    except ValueError as exc:
        raise PartNameError("選択したパーツが現在のモデルにありません。") from exc
    name = validate_unique_part_name(
        value,
        list(prepared.final.part_names),
        current_index=part_index,
    )
    _replace_prepared_names(prepared, {keys[part_index]: name})
    return name


def collect_part_name_overrides(prepared: PreparedGeometry) -> dict[str, str]:
    """Return the current display names keyed only by stable part IDs."""

    keys = tuple(prepared.final.part_keys)
    names = tuple(prepared.final.part_names)
    if len(keys) != len(names):
        raise PartNameError("パーツ名とパーツIDの数が一致していません。")
    return {
        str(key): normalize_part_name(name)
        for key, name in zip(keys, names, strict=True)
    }


def apply_part_name_overrides(
    prepared: PreparedGeometry,
    overrides: Mapping[str, object] | None,
) -> dict[str, str]:
    """Apply known-key names and return the valid active-model subset.

    Unknown keys are deliberately ignored.  They can belong to a previous OBJ
    saved in the same settings file and must never be reassigned by index.
    """

    if not overrides:
        return {}
    active_keys = tuple(prepared.final.part_keys)
    requested: list[tuple[str, str]] = []
    proposed_names = list(prepared.final.part_names)
    for part_index, key in enumerate(active_keys):
        if key not in overrides:
            continue
        name = normalize_part_name(overrides[key])
        proposed_names[part_index] = name
        requested.append((key, name))
    folded = [name.casefold() for name in proposed_names]
    if len(set(folded)) != len(folded):
        raise PartNameError("保存されたパーツ名に重複があります。")
    _replace_prepared_names(prepared, dict(requested))
    return dict(requested)


__all__ = [
    "MAX_PART_NAME_LENGTH",
    "PartNameError",
    "apply_part_name_overrides",
    "collect_part_name_overrides",
    "normalize_part_name",
    "rename_prepared_part",
    "validate_unique_part_name",
]
