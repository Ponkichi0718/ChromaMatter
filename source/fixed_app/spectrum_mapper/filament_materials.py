from __future__ import annotations

"""Shared single-material contract for Full Spectrum jobs."""

MATERIAL_PLA = "PLA"
MATERIAL_ABS = "ABS"
MATERIAL_PETG = "PETG"
SUPPORTED_FILAMENT_MATERIALS = (MATERIAL_PLA, MATERIAL_ABS, MATERIAL_PETG)
DEFAULT_FILAMENT_MATERIAL = MATERIAL_PLA


def normalize_filament_material(value: object, *, default: str | None = None) -> str:
    text = str(value or "").strip().upper()
    if not text and default is not None:
        text = str(default).strip().upper()
    if text not in SUPPORTED_FILAMENT_MATERIALS:
        raise ValueError("filament material must be PLA, ABS, or PETG")
    return text


def generic_filament_profile(material: object) -> str:
    """Return the exact Snapmaker Orca 2.3.5 generic profile name."""

    return f"Generic {normalize_filament_material(material)}"


__all__ = [
    "DEFAULT_FILAMENT_MATERIAL",
    "MATERIAL_ABS",
    "MATERIAL_PETG",
    "MATERIAL_PLA",
    "SUPPORTED_FILAMENT_MATERIALS",
    "generic_filament_profile",
    "normalize_filament_material",
]
