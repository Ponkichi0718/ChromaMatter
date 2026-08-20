from __future__ import annotations

from typing import Sequence

import numpy as np

from . import renderer as renderer_module
from .models import MeshLevel


class JointProjectionError(RuntimeError):
    """The selected canvas pixel cannot be mapped safely onto its face."""


def project_face_to_render(
    level: MeshLevel,
    face_id: int,
    *,
    camera: object,
    render_size: tuple[int, int],
) -> np.ndarray:
    """Return one face's three vertices in top-left-origin render pixels."""

    width, height = (int(render_size[0]), int(render_size[1]))
    if width < 2 or height < 2:
        raise JointProjectionError("3D表示サイズが不正です")
    faces = np.asarray(level.faces)
    vertices = np.asarray(level.vertices_unit, dtype=np.float64)
    selected = int(face_id)
    if selected < 0 or selected >= len(faces):
        raise JointProjectionError("選択面番号が範囲外です")
    triangle = vertices[np.asarray(faces[selected], dtype=np.int64)]
    if triangle.shape != (3, 3) or not np.isfinite(triangle).all():
        raise JointProjectionError("選択面の頂点が不正です")

    # Resolve through the module at call time.  The rotation/pan adapter
    # replaces this function, and the colour and picker passes use that same
    # replacement.  A captured import would lose the current pan offset.
    mvp, _clean_camera, _pixels_per_unit = renderer_module._orbit_camera_mvp(
        vertices,
        (width, height),
        camera,
    )
    homogeneous = np.column_stack((triangle, np.ones(3, dtype=np.float64)))
    clip = homogeneous @ np.asarray(mvp, dtype=np.float64).T
    if np.any(~np.isfinite(clip)) or np.any(np.abs(clip[:, 3]) <= 1e-12):
        raise JointProjectionError("選択面を画面座標へ投影できません")
    ndc = clip[:, :3] / clip[:, 3, None]
    return np.column_stack(
        (
            (ndc[:, 0] + 1.0) * 0.5 * width,
            (1.0 - (ndc[:, 1] + 1.0) * 0.5) * height,
        )
    )


def _barycentric_2d(triangle: np.ndarray, point: np.ndarray) -> np.ndarray:
    a, b, c = np.asarray(triangle, dtype=np.float64)
    matrix = np.column_stack((a - c, b - c))
    determinant = float(np.linalg.det(matrix))
    if not np.isfinite(determinant) or abs(determinant) <= 1e-10:
        raise JointProjectionError("選択面が画面上で細すぎるため位置を決められません")
    first, second = np.linalg.solve(matrix, np.asarray(point, dtype=np.float64) - c)
    return np.asarray((first, second, 1.0 - first - second), dtype=np.float64)


def canvas_point_on_face(
    level: MeshLevel,
    face_id: int,
    canvas_xy: Sequence[float],
    mapping: Sequence[int],
    *,
    camera: object,
) -> tuple[float, float, float]:
    """Map a picked Canvas point back onto the exact selected triangle.

    ``mapping`` is the paint editor's ``target_mapping`` tuple.  The renderer
    is orthographic, so ordinary screen-space barycentric interpolation is
    exact.  A small raster-edge tolerance is accepted because the face-ID
    buffer reports whole pixels while the mouse position is continuous.
    """

    if len(mapping) != 6 or len(canvas_xy) != 2:
        raise JointProjectionError("3D表示の座標対応が不正です")
    left, top, shown_width, shown_height, render_width, render_height = (
        int(value) for value in mapping
    )
    if min(shown_width, shown_height, render_width, render_height) <= 0:
        raise JointProjectionError("3D表示サイズが不正です")
    canvas_x, canvas_y = (float(canvas_xy[0]), float(canvas_xy[1]))
    if not (
        left <= canvas_x < left + shown_width
        and top <= canvas_y < top + shown_height
    ):
        raise JointProjectionError("指定位置が3D表示の外側です")
    render_point = np.asarray(
        (
            (canvas_x - left) * render_width / shown_width,
            (canvas_y - top) * render_height / shown_height,
        ),
        dtype=np.float64,
    )
    projected = project_face_to_render(
        level,
        face_id,
        camera=camera,
        render_size=(render_width, render_height),
    )
    weights = _barycentric_2d(projected, render_point)
    if not np.isfinite(weights).all() or float(weights.min()) < -0.08:
        raise JointProjectionError("指定位置が選択面から外れています")
    weights = np.clip(weights, 0.0, 1.0)
    total = float(weights.sum())
    if total <= 1e-12:
        raise JointProjectionError("選択面上の位置を計算できません")
    weights /= total
    faces = np.asarray(level.faces, dtype=np.int64)
    vertices = np.asarray(level.vertices_unit, dtype=np.float64)
    point = weights @ vertices[faces[int(face_id)]]
    if point.shape != (3,) or not np.isfinite(point).all():
        raise JointProjectionError("選択面上の3D位置が不正です")
    return tuple(float(value) for value in point)


__all__ = [
    "JointProjectionError",
    "canvas_point_on_face",
    "project_face_to_render",
]
