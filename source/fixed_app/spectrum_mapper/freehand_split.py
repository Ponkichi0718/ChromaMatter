from __future__ import annotations

import base64
import binascii
from collections import deque
import copy
from dataclasses import dataclass
import zlib
from typing import Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw

from .models import AppSettings, MeshLevel, PreparedGeometry
from .paint import build_partial_face_neighbors, mesh_fingerprint
from .parts import validate_part_layout


PARTITION_ENCODING = "zlib+base64-int32-v1"


class FreehandSplitError(ValueError):
    """Raised when a freehand selection cannot become a safe print part."""

    def __init__(
        self,
        message: str,
        translation_key: str | None = None,
        **translation_values: object,
    ) -> None:
        super().__init__(message)
        self.translation_key = translation_key
        self.translation_values = dict(translation_values)

    def localized(self, translator: object) -> str:
        """Return a localized UI message while keeping Japanese CLI errors."""

        if self.translation_key is None:
            return str(self)
        text = getattr(translator, "text", None)
        if not callable(text):
            return str(self)
        return str(text(self.translation_key, **self.translation_values))


@dataclass(frozen=True, slots=True)
class LassoSplitPlan:
    source_part_id: int
    source_part_name: str
    source_part_key: str
    selected_faces: np.ndarray
    selected_components: tuple[int, ...]
    selected_visible_pixels: int
    selected_visible_coverage: float
    remaining_faces: int
    new_part_name: str
    new_part_key: str
    mesh_fingerprint: str


def canvas_polygon_to_render(
    mapping: tuple[int, int, int, int, int, int],
    canvas_points: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """Map displayed-canvas points to the renderer's face-ID pixel space."""

    left, top, display_width, display_height, render_width, render_height = (
        int(value) for value in mapping
    )
    if min(display_width, display_height, render_width, render_height) < 1:
        raise FreehandSplitError(
            "3D表示の座標変換範囲が不正です",
            "separate.error.invalid_mapping",
        )
    result = tuple(
        (
            (float(x) - left) * render_width / display_width,
            (float(y) - top) * render_height / display_height,
        )
        for x, y in canvas_points
    )
    if len(result) < 3:
        raise FreehandSplitError(
            "フリーハンド領域は3点以上で囲んでください",
            "separate.error.too_few_points",
        )
    return result


def inherit_explicit_part_palette(
    settings: AppSettings, source_part_key: str, new_part_key: str
) -> bool:
    """Copy an explicit source palette so a split can never change real RGB."""

    source = str(source_part_key)
    target = str(new_part_key)
    if target in settings.part_palettes:
        return False
    palette = settings.part_palettes.get(source)
    if palette is None:
        return False
    settings.part_palettes[target] = copy.deepcopy(palette)
    return True


def _part_names(level: MeshLevel, part_count: int) -> tuple[str, ...]:
    names = tuple(level.part_names)
    if len(names) == part_count:
        return names
    return tuple(
        "OBJ全体" if part_count == 1 else f"part_{index + 1}"
        for index in range(part_count)
    )


def _next_lasso_identity(
    names: Sequence[str], keys: Sequence[str], source_part_id: int
) -> tuple[str, str]:
    parent_name = str(names[source_part_id])
    parent_key = str(keys[source_part_id])
    serial = 1
    while True:
        key = f"{parent_key}/cut:lasso-{serial}"
        if key not in keys:
            return f"{parent_name}_freehand_{serial}", key
        serial += 1


def _polygon_mask(
    shape: tuple[int, int], polygon: Sequence[tuple[float, float]]
) -> np.ndarray:
    height, width = (int(shape[0]), int(shape[1]))
    if height < 1 or width < 1:
        raise FreehandSplitError(
            "面ID画像の大きさが不正です",
            "separate.error.invalid_face_map_size",
        )
    points = tuple((float(x), float(y)) for x, y in polygon)
    if len(points) < 3:
        raise FreehandSplitError(
            "フリーハンド領域は3点以上で囲んでください",
            "separate.error.too_few_points",
        )
    if not all(np.isfinite(value) for point in points for value in point):
        raise FreehandSplitError(
            "フリーハンド領域に不正な座標があります",
            "separate.error.invalid_coordinates",
        )
    area_twice = abs(
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
    )
    if area_twice < 4.0:
        raise FreehandSplitError(
            "フリーハンド領域が小さすぎます",
            "separate.error.region_too_small",
        )
    image = Image.new("1", (width, height), 0)
    ImageDraw.Draw(image).polygon(points, fill=1)
    return np.asarray(image, dtype=bool)


def _component_labels(
    faces: np.ndarray, part_ids: np.ndarray, source_part_id: int
) -> tuple[np.ndarray, int]:
    neighbors = build_partial_face_neighbors(faces)
    active = part_ids == int(source_part_id)
    labels = np.full(len(faces), -1, dtype=np.int32)
    component_count = 0
    for seed_value in np.flatnonzero(active):
        seed = int(seed_value)
        if labels[seed] >= 0:
            continue
        labels[seed] = component_count
        pending: deque[int] = deque((seed,))
        while pending:
            face = pending.popleft()
            for neighbor_value in neighbors[face]:
                neighbor = int(neighbor_value)
                if (
                    neighbor >= 0
                    and active[neighbor]
                    and labels[neighbor] < 0
                ):
                    labels[neighbor] = component_count
                    pending.append(neighbor)
        component_count += 1
    return labels, component_count


def _closed_face_subset(faces: np.ndarray, selected: np.ndarray) -> bool:
    triangles = np.asarray(faces[selected], dtype=np.int64)
    if not len(triangles):
        return False
    edges = np.concatenate(
        (
            triangles[:, [0, 1]],
            triangles[:, [1, 2]],
            triangles[:, [2, 0]],
        ),
        axis=0,
    )
    edges.sort(axis=1)
    _unique, counts = np.unique(edges, axis=0, return_counts=True)
    return bool(len(counts) and np.all(counts == 2))


def plan_lasso_component_split(
    level: MeshLevel,
    face_id_map: np.ndarray,
    polygon: Sequence[tuple[float, float]],
    source_part_id: int,
    *,
    minimum_visible_coverage: float = 0.55,
    minimum_selected_pixels: int = 3,
) -> LassoSplitPlan:
    """Plan a colour-preserving split of whole closed shells under a lasso.

    The GPU face-ID image supplies exact visible-face hits.  Hits are expanded
    only to complete edge-connected shells belonging to the active part.  This
    makes the hidden back side part of the selection while refusing a cut that
    would silently turn either output into an open surface.
    """

    layout = validate_part_layout(level)
    part_id = int(source_part_id)
    if part_id < 0 or part_id >= layout.part_count:
        raise FreehandSplitError(
            "分割元パーツが範囲外です",
            "separate.error.source_out_of_range",
        )
    coverage_limit = float(minimum_visible_coverage)
    if not 0.0 < coverage_limit <= 1.0:
        raise FreehandSplitError("可視範囲率は0より大きく1以下にしてください")
    minimum_pixels = max(1, int(minimum_selected_pixels))

    face_ids = np.asarray(face_id_map)
    if face_ids.ndim != 2 or not np.issubdtype(face_ids.dtype, np.integer):
        raise FreehandSplitError(
            "面ID画像は2次元の整数配列で指定してください",
            "separate.error.invalid_face_map",
        )
    mask = _polygon_mask(face_ids.shape, polygon)
    valid = (face_ids >= 0) & (face_ids < layout.face_count)
    if not np.any(valid & mask):
        raise FreehandSplitError(
            "囲んだ範囲にモデルの面がありません",
            "separate.error.no_surface",
        )

    visible_faces = face_ids[valid].astype(np.int64, copy=False)
    active_visible = layout.face_part_ids[visible_faces] == part_id
    visible_faces = visible_faces[active_visible]
    selected_valid = valid & mask
    selected_faces_pixels = face_ids[selected_valid].astype(np.int64, copy=False)
    selected_faces_pixels = selected_faces_pixels[
        layout.face_part_ids[selected_faces_pixels] == part_id
    ]
    if not len(selected_faces_pixels):
        raise FreehandSplitError(
            "囲んだ範囲に現在の編集パーツがありません。編集パーツを確認してください",
            "separate.error.no_active_part",
        )

    labels, component_count = _component_labels(
        np.asarray(level.faces), layout.face_part_ids, part_id
    )
    if component_count < 2:
        raise FreehandSplitError(
            "現在のパーツは1つにつながっています。第一版のフリーハンド分割は、"
            "浮遊している独立形状を閉じたまま切り出す場合に使用できます",
            "separate.error.connected_shell",
        )

    visible_components = labels[visible_faces]
    selected_components = labels[selected_faces_pixels]
    total_pixels = np.bincount(
        visible_components, minlength=component_count
    ).astype(np.int64, copy=False)
    inside_pixels = np.bincount(
        selected_components, minlength=component_count
    ).astype(np.int64, copy=False)
    coverage = np.divide(
        inside_pixels,
        np.maximum(total_pixels, 1),
        dtype=np.float64,
    )
    candidates = np.flatnonzero(
        (inside_pixels >= minimum_pixels)
        & (coverage >= coverage_limit)
    ).astype(np.int32, copy=False)
    if not len(candidates):
        best = int(np.argmax(coverage))
        raise FreehandSplitError(
            "独立形状を十分に囲めませんでした。"
            f"最も近い形状の囲み率は {coverage[best] * 100.0:.1f}% です。"
            "対象の輪郭より少し外側を一周してください",
            "separate.error.insufficient_coverage",
            coverage=float(coverage[best] * 100.0),
        )

    selected = np.flatnonzero(np.isin(labels, candidates)).astype(
        np.int32, copy=False
    )
    source_faces = np.flatnonzero(layout.face_part_ids == part_id)
    if len(selected) >= len(source_faces):
        raise FreehandSplitError(
            "編集パーツ全体が選ばれました。分けたい独立形状だけを囲んでください",
            "separate.error.whole_part",
        )
    remaining = np.setdiff1d(source_faces, selected, assume_unique=True)
    if not _closed_face_subset(np.asarray(level.faces), selected):
        raise FreehandSplitError(
            "選択形状が閉じていないため、安全な印刷パーツへ分離できません",
            "separate.error.selected_open",
        )
    if not _closed_face_subset(np.asarray(level.faces), remaining):
        raise FreehandSplitError(
            "分割後の残り形状が閉じないため、安全のため分割を中止しました",
            "separate.error.remaining_open",
        )

    names = _part_names(level, layout.part_count)
    new_name, new_key = _next_lasso_identity(
        names, layout.part_keys, part_id
    )
    selected_component_values = tuple(int(value) for value in candidates)
    selected_pixel_count = int(inside_pixels[candidates].sum())
    candidate_total = int(total_pixels[candidates].sum())
    return LassoSplitPlan(
        source_part_id=part_id,
        source_part_name=names[part_id],
        source_part_key=layout.part_keys[part_id],
        selected_faces=selected,
        selected_components=selected_component_values,
        selected_visible_pixels=selected_pixel_count,
        selected_visible_coverage=(
            selected_pixel_count / max(candidate_total, 1)
        ),
        remaining_faces=int(len(remaining)),
        new_part_name=new_name,
        new_part_key=new_key,
        mesh_fingerprint=mesh_fingerprint(level),
    )


def apply_lasso_split(level: MeshLevel, plan: LassoSplitPlan) -> MeshLevel:
    """Return a level with only its per-face part assignment changed."""

    if mesh_fingerprint(level) != plan.mesh_fingerprint:
        raise FreehandSplitError(
            "ラッソ選択後に形状が変わったため分割できません",
            "separate.error.mesh_changed",
        )
    layout = validate_part_layout(level)
    if plan.source_part_id >= layout.part_count:
        raise FreehandSplitError(
            "分割元パーツがなくなりました",
            "separate.error.source_missing",
        )
    if layout.part_keys[plan.source_part_id] != plan.source_part_key:
        raise FreehandSplitError(
            "分割元パーツが選択時と一致しません",
            "separate.error.source_changed",
        )
    selected = np.asarray(plan.selected_faces)
    if (
        selected.ndim != 1
        or not np.issubdtype(selected.dtype, np.integer)
        or not len(selected)
        or int(selected.min()) < 0
        or int(selected.max()) >= layout.face_count
    ):
        raise FreehandSplitError(
            "分割対象面が不正です",
            "separate.error.invalid_faces",
        )
    selected = np.unique(selected.astype(np.int32, copy=False))
    if np.any(layout.face_part_ids[selected] != plan.source_part_id):
        raise FreehandSplitError(
            "分割対象面が別パーツへ変更されています",
            "separate.error.faces_changed",
        )

    new_part_id = layout.part_count
    new_ids = layout.face_part_ids.astype(np.int32, copy=True)
    new_ids[selected] = new_part_id
    names = _part_names(level, layout.part_count) + (plan.new_part_name,)
    keys = layout.part_keys + (plan.new_part_key,)
    return MeshLevel(
        vertices_unit=level.vertices_unit,
        faces=level.faces,
        vertex_colors=level.vertex_colors,
        areas_unit=level.areas_unit,
        neighbors=level.neighbors,
        face_part_ids=new_ids,
        face_provenance=np.asarray(level.face_provenance).copy(),
        part_names=names,
        part_keys=keys,
    )


def apply_level_partition_to_prepared(
    prepared: PreparedGeometry,
    level: MeshLevel,
    *,
    record: Mapping[str, object] | None = None,
) -> None:
    """Install a part-only level change without changing paint face indices."""

    if mesh_fingerprint(prepared.final) != mesh_fingerprint(level):
        raise FreehandSplitError("パーツ割当の形状が現在のモデルと一致しません")
    layout = validate_part_layout(level)
    prepared.final = level
    # The preview topology cannot express a final-mesh lasso assignment.
    # Reusing the exact final level is intentional: it keeps individual 3MF
    # extraction and subsequent colour previews aligned to the same face IDs.
    prepared.preview = MeshLevel(
        vertices_unit=level.vertices_unit,
        faces=level.faces,
        vertex_colors=level.vertex_colors,
        areas_unit=level.areas_unit,
        neighbors=level.neighbors,
        face_part_ids=np.asarray(level.face_part_ids).copy(),
        face_provenance=np.asarray(level.face_provenance).copy(),
        part_names=tuple(level.part_names),
        part_keys=tuple(level.part_keys),
    )
    prepared.part_names = tuple(level.part_names)
    prepared.part_keys = tuple(level.part_keys)
    previous_stats = list(prepared.part_stats)
    stats: list[dict[str, object]] = []
    for part_id, (name, key) in enumerate(
        zip(level.part_names, level.part_keys, strict=True)
    ):
        selected = np.flatnonzero(layout.face_part_ids == part_id)
        used_vertices = np.unique(np.asarray(level.faces)[selected].reshape(-1))
        value = (
            dict(previous_stats[part_id])
            if part_id < len(previous_stats)
            else {}
        )
        value.update(
            {
                "id": int(part_id),
                "key": key,
                "name": name,
                "final_vertices": int(len(used_vertices)),
                "final_faces": int(len(selected)),
                "preview_vertices": int(len(used_vertices)),
                "preview_faces": int(len(selected)),
                "manual_lasso_part": bool(part_id >= len(previous_stats)),
            }
        )
        stats.append(value)
    prepared.part_stats = stats
    assembly = dict(prepared.assembly or {})
    history = list(assembly.get("manual_lasso_splits", []))
    if record is not None:
        history.append(dict(record))
    assembly["manual_lasso_splits"] = history
    assembly["manual_part_assignment"] = True
    assembly["all_parts_watertight"] = True
    prepared.assembly = assembly


def encode_manual_part_partition(
    level: MeshLevel, fingerprint: str | None = None
) -> dict[str, object]:
    layout = validate_part_layout(level)
    ids = np.ascontiguousarray(layout.face_part_ids, dtype="<i4")
    compressed = zlib.compress(ids.tobytes(), level=9)
    names = _part_names(level, layout.part_count)
    return {
        "encoding": PARTITION_ENCODING,
        "face_count": int(layout.face_count),
        "part_count": int(layout.part_count),
        "mesh_fingerprint": fingerprint or mesh_fingerprint(level),
        "part_names": list(names),
        "part_keys": list(layout.part_keys),
        "data": base64.b64encode(compressed).decode("ascii"),
    }


def decode_manual_part_partition(
    level: MeshLevel,
    payload: Mapping[str, object],
    *,
    expected_fingerprint: str | None = None,
) -> MeshLevel:
    if payload.get("encoding") != PARTITION_ENCODING:
        raise FreehandSplitError("未対応の手動パーツ割当形式です")
    fingerprint = expected_fingerprint or mesh_fingerprint(level)
    if payload.get("mesh_fingerprint") != fingerprint:
        raise FreehandSplitError("形状が変わっているため手動パーツ分割を復元できません")
    try:
        face_count = int(payload["face_count"])
        part_count = int(payload["part_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FreehandSplitError("手動パーツ割当の個数が不正です") from exc
    if face_count != len(level.faces) or part_count < 2:
        raise FreehandSplitError("手動パーツ割当が現在の面数と一致しません")
    names_value = payload.get("part_names")
    keys_value = payload.get("part_keys")
    if not isinstance(names_value, list) or not isinstance(keys_value, list):
        raise FreehandSplitError("手動パーツ割当に名前またはキーがありません")
    names = tuple(str(value).strip() for value in names_value)
    keys = tuple(str(value).strip() for value in keys_value)
    if (
        len(names) != part_count
        or len(keys) != part_count
        or any(not value for value in names)
        or any(not value for value in keys)
        or len(set(keys)) != part_count
    ):
        raise FreehandSplitError("手動パーツ割当の名前またはキーが不正です")
    encoded = payload.get("data")
    if not isinstance(encoded, str):
        raise FreehandSplitError("手動パーツ割当データがありません")
    expected_bytes = face_count * 4
    try:
        compressed = base64.b64decode(encoded.encode("ascii"), validate=True)
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, expected_bytes + 1)
        raw += decompressor.flush()
    except (ValueError, UnicodeEncodeError, binascii.Error, zlib.error) as exc:
        raise FreehandSplitError("手動パーツ割当データが破損しています") from exc
    if (
        decompressor.unconsumed_tail
        or decompressor.unused_data
        or len(raw) != expected_bytes
    ):
        raise FreehandSplitError("手動パーツ割当の展開後サイズが一致しません")
    ids = np.frombuffer(raw, dtype="<i4").astype(np.int32, copy=True)
    if (
        len(ids) != face_count
        or int(ids.min(initial=0)) < 0
        or int(ids.max(initial=0)) >= part_count
        or np.any(np.bincount(ids, minlength=part_count) == 0)
    ):
        raise FreehandSplitError("手動パーツ割当に空または範囲外のパーツがあります")
    return MeshLevel(
        vertices_unit=level.vertices_unit,
        faces=level.faces,
        vertex_colors=level.vertex_colors,
        areas_unit=level.areas_unit,
        neighbors=level.neighbors,
        face_part_ids=ids,
        face_provenance=np.asarray(level.face_provenance).copy(),
        part_names=names,
        part_keys=keys,
    )


__all__ = [
    "FreehandSplitError",
    "LassoSplitPlan",
    "PARTITION_ENCODING",
    "apply_lasso_split",
    "apply_level_partition_to_prepared",
    "canvas_polygon_to_render",
    "decode_manual_part_partition",
    "encode_manual_part_partition",
    "inherit_explicit_part_palette",
    "plan_lasso_component_split",
]
