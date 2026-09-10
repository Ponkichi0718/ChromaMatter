"""Explicit, geometry-only export acceptance; never archive authorization.

HIGH retains the historical solid/provenance contract. Relaxed modes are an
owner-selected handoff to a slicer, not a repair and not a printability claim.
The selected policy must come from the caller, never from imported metadata.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np


LEVELS = ("high", "medium", "low", "ignore")
SCHEMA = "chromamatter.export-validation.v1"


def require_level(value: object) -> str:
    if not isinstance(value, str) or value not in LEVELS:
        raise ValueError("Unknown export validation level; use high, medium, low or ignore")
    return value


def policy_metadata(level: str) -> dict[str, object]:
    level = require_level(level)
    return {
        "schema": SCHEMA,
        "level": level,
        "self_intersections_checked": level == "high",
        "orca_preview_required": level != "high",
        "not_recommended": level == "ignore",
    }


def validate_mesh_arrays(vertices: object, faces: object) -> None:
    """Reject data which cannot safely be serialized, in every policy.

    Check before narrowing indices or invoking native mesh code. In particular,
    a negative index must not become valid through numpy's negative indexing.
    Repeated/collinear triangles remain measurable geometry defects, not an
    index or byte-format exception, and may be passed only by explicit IGNORE.
    """
    points = np.asarray(vertices)
    triangles = np.asarray(faces)
    if points.ndim != 2 or points.shape[1:] != (3,) or not len(points):
        raise ValueError("3MF vertices must be a non-empty Nx3 array")
    if not np.issubdtype(points.dtype, np.number) or np.iscomplexobj(points):
        raise ValueError("3MF coordinates must be real finite numbers")
    if not np.isfinite(points).all():
        raise ValueError("3MF coordinates must be finite")
    if triangles.ndim != 2 or triangles.shape[1:] != (3,) or not len(triangles):
        raise ValueError("3MF triangles must be a non-empty Nx3 array")
    if not np.issubdtype(triangles.dtype, np.integer):
        raise ValueError("3MF triangle indices must be integers")
    if int(triangles.min()) < 0 or int(triangles.max()) >= len(points):
        raise ValueError("3MF triangle index is outside the vertex array")
    if int(triangles.max()) > np.iinfo(np.int32).max:
        raise ValueError("3MF triangle index exceeds the supported range")


def accepts_topology(level: str, quality: Mapping[str, object], *, strict_valid: bool) -> bool:
    level = require_level(level)
    if level == "high":
        return strict_valid
    if level == "ignore":
        return True
    if not (
        int(quality.get("nonmanifold_edges", -1)) == 0
        and quality.get("winding_consistent") is True
        and int(quality.get("degenerate_faces", -1)) == 0
        and int(quality.get("body_count", 0)) >= 1
    ):
        return False
    if level == "medium":
        return bool(quality.get("watertight") and quality.get("positive_volume"))
    return True


def topology_issue_codes(quality: Mapping[str, object]) -> list[str]:
    """Raw findings, independent of whether the selected policy accepts them."""
    result: list[str] = []
    if int(quality.get("boundary_edges", 0)) > 0:
        result.append("open_boundaries")
    if int(quality.get("nonmanifold_edges", 0)) > 0:
        result.append("nonmanifold_edges")
    if not quality.get("winding_consistent"):
        result.append("inconsistent_winding")
    if not quality.get("positive_volume"):
        result.append("not_a_positive_closed_volume")
    if int(quality.get("degenerate_faces", 0)) > 0:
        result.append("degenerate_faces")
    count = int(quality.get("body_count", 0))
    if count != 1:
        result.append("multiple_bodies" if count > 1 else "no_bodies")
    intersections = int(quality.get("self_intersecting_faces", -1))
    if intersections < 0:
        result.append("self_intersections_not_checked")
    elif intersections > 0:
        result.append("self_intersections")
    return result
