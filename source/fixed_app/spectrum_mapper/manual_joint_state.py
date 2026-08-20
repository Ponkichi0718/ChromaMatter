from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .models import MeshLevel


class ManualJointStateError(RuntimeError):
    """Paint state cannot be transferred across a joint topology change."""


def remap_manual_overrides(
    before: MeshLevel,
    after: MeshLevel,
    overrides: np.ndarray,
) -> np.ndarray:
    """Transfer sparse face overrides to the nearest old face in each part.

    A boolean joint retriangulates its two parts, so face indices cannot be
    reused.  Looking up every new centroid against *all* old centroids avoids
    spreading a sparse painted patch across the whole part: the nearest old
    face decides whether the new face remains automatic (``-1``) or inherits
    an explicit palette state.
    """

    source = np.asarray(overrides, dtype=np.int8)
    if source.shape != (len(before.faces),):
        raise ManualJointStateError("ジョイント前の手修正面数が一致しません")
    before_part_ids = np.asarray(before.face_part_ids)
    after_part_ids = np.asarray(after.face_part_ids)
    if before_part_ids.shape != (len(before.faces),) or after_part_ids.shape != (
        len(after.faces),
    ):
        raise ManualJointStateError("ジョイント前後のパーツ面情報が不正です")
    before_keys = tuple(before.part_keys)
    after_keys = tuple(after.part_keys)
    if not before_keys or before_keys != after_keys:
        raise ManualJointStateError("ジョイント前後でパーツ構成が変わっています")

    before_vertices = np.asarray(before.vertices_unit, dtype=np.float64)
    after_vertices = np.asarray(after.vertices_unit, dtype=np.float64)
    before_faces = np.asarray(before.faces, dtype=np.int64)
    after_faces = np.asarray(after.faces, dtype=np.int64)
    result = np.full(len(after_faces), -1, dtype=np.int8)
    for part_id in range(len(before_keys)):
        old_ids = np.flatnonzero(before_part_ids == part_id)
        new_ids = np.flatnonzero(after_part_ids == part_id)
        if len(old_ids) == 0 or len(new_ids) == 0:
            raise ManualJointStateError(
                f"パーツ{part_id + 1}の面をジョイント前後で対応できません"
            )
        old_centroids = before_vertices[before_faces[old_ids]].mean(axis=1)
        new_centroids = after_vertices[after_faces[new_ids]].mean(axis=1)
        if not np.isfinite(old_centroids).all() or not np.isfinite(
            new_centroids
        ).all():
            raise ManualJointStateError("ジョイント前後の面中心に不正値があります")
        nearest = cKDTree(old_centroids).query(new_centroids, workers=-1)[1]
        result[new_ids] = source[old_ids[np.asarray(nearest, dtype=np.int64)]]
    return result


__all__ = ["ManualJointStateError", "remap_manual_overrides"]
