from __future__ import annotations

import base64
import binascii
import hashlib
import struct
import zlib
from collections import deque
from dataclasses import dataclass
from typing import Mapping

import numpy as np

from .mixer import PALETTE_STATE_COUNT
from .models import MeshLevel
from .paint_tools import (
    accumulated_airbrush_deposit,
    airbrush_radius_scale,
    CreaseEdgeData,
    PaintToolError,
    SurfaceRegion,
    deterministic_thresholds,
    enabled_state_ids,
    multi_seed_surface_region,
    plan_smudge,
    soft_falloff,
    surface_region as plan_surface_region,
    validate_strength,
)


PAINT_ENCODING = "zlib+base64-int8-v1"


class PaintError(ValueError):
    """Raised when a paint operation or saved paint payload is invalid."""


@dataclass(frozen=True)
class PaintCommand:
    """One reversible edit, stored sparsely by final-mesh face index."""

    indices: np.ndarray
    before: np.ndarray
    after: np.ndarray
    label: str

    @property
    def face_count(self) -> int:
        return int(len(self.indices))


def _validate_faces(faces: np.ndarray, vertex_count: int | None = None) -> np.ndarray:
    source = np.asarray(faces)
    if source.ndim != 2 or source.shape[1] != 3:
        raise PaintError("faces は Mx3 の三角形配列である必要があります")
    if not np.issubdtype(source.dtype, np.integer):
        raise PaintError("faces のインデックスは整数である必要があります")
    if len(source):
        if int(source.min()) < 0:
            raise PaintError("faces に負の頂点インデックスがあります")
        if int(source.max()) > np.iinfo(np.int32).max:
            raise PaintError("faces の頂点インデックスが大きすぎます")
        if vertex_count is not None and int(source.max()) >= int(vertex_count):
            raise PaintError("faces に頂点数を超えるインデックスがあります")
    return source.astype(np.int32, copy=False)


def build_partial_face_neighbors(
    faces: np.ndarray,
    vertex_count: int | None = None,
) -> np.ndarray:
    """Return three edge-neighbours per face, using -1 at unsafe edges.

    Unlike ``engine.face_neighbors``, this remains useful for open meshes.
    Boundary edges and non-manifold edges are deliberately not crossed.
    """

    triangles = _validate_faces(faces, vertex_count)
    face_count = len(triangles)
    result = np.full((face_count, 3), -1, dtype=np.int32)
    if face_count == 0:
        return result

    edges = np.concatenate(
        (triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]),
        axis=0,
    ).astype(np.int64, copy=False)
    face_ids = np.tile(np.arange(face_count, dtype=np.int32), 3)
    edge_slots = np.repeat(np.arange(3, dtype=np.int8), face_count)
    low = np.minimum(edges[:, 0], edges[:, 1])
    high = np.maximum(edges[:, 0], edges[:, 1])

    # Pair keys do not depend on a caller-provided vertex count and therefore
    # cannot collide when a mesh uses sparse vertex indices.
    order = np.lexsort((high, low))
    low = low[order]
    high = high[order]
    face_ids = face_ids[order]
    edge_slots = edge_slots[order]
    starts = np.r_[0, np.flatnonzero((low[1:] != low[:-1]) | (high[1:] != high[:-1])) + 1]
    ends = np.r_[starts[1:], len(low)]
    pair_starts = starts[(ends - starts) == 2]
    left_faces = face_ids[pair_starts]
    right_faces = face_ids[pair_starts + 1]
    # A degenerate triangle can list the same undirected edge twice.
    useful = left_faces != right_faces
    pair_starts = pair_starts[useful]
    left_faces = left_faces[useful]
    right_faces = right_faces[useful]
    result[left_faces, edge_slots[pair_starts]] = right_faces
    result[right_faces, edge_slots[pair_starts + 1]] = left_faces
    return result


def mesh_fingerprint(level: MeshLevel) -> str:
    """Return a stable identity for the exact face topology being painted."""

    vertices = np.ascontiguousarray(np.asarray(level.vertices_unit, dtype="<f8"))
    faces = np.ascontiguousarray(_validate_faces(level.faces, len(vertices)), dtype="<i4")
    digest = hashlib.sha256()
    digest.update(b"TripoSpectrumMapper.paint-mesh.v1\0")
    digest.update(struct.pack("<QQ", len(vertices), len(faces)))
    digest.update(memoryview(vertices).cast("B"))
    digest.update(memoryview(faces).cast("B"))
    return digest.hexdigest()


def exact_face_paint_identity(
    before: MeshLevel,
    after: MeshLevel,
    *,
    chunk_faces: int = 65_536,
) -> bool:
    """Prove that face-indexed paint has exactly the same roots in two levels.

    A safe texture-seam weld may replace duplicated vertex *indices* while
    leaving every ordered triangle at the same coordinates.  The ordinary mesh
    fingerprint intentionally rejects that change, so this narrower proof is
    used only by the explicit single-GLB repair path.  It deliberately checks
    the byte representation of each ordered triangle in bounded chunks: no
    nearest-face tolerance, reordering, or floating-point rounding is accepted.

    Part ownership is part of the paint identity as well.  Matching geometry
    with different ``face_part_ids`` or ``part_keys`` is therefore rejected.
    """

    try:
        before_faces = _validate_faces(before.faces, len(before.vertices_unit))
        after_faces = _validate_faces(after.faces, len(after.vertices_unit))
        before_vertices = np.asarray(before.vertices_unit)
        after_vertices = np.asarray(after.vertices_unit)
        before_part_ids = np.asarray(before.face_part_ids)
        after_part_ids = np.asarray(after.face_part_ids)
        step = int(chunk_faces)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False

    if step < 1:
        raise ValueError("chunk_faces must be positive")
    if before_faces.shape != after_faces.shape:
        return False
    face_count = len(before_faces)
    if before_part_ids.shape != (face_count,) or after_part_ids.shape != (
        face_count,
    ):
        return False
    if not np.issubdtype(before_part_ids.dtype, np.integer) or not np.issubdtype(
        after_part_ids.dtype, np.integer
    ):
        return False
    if not np.array_equal(before_part_ids, after_part_ids):
        return False
    if tuple(before.part_keys) != tuple(after.part_keys):
        return False
    if (
        before_vertices.ndim != 2
        or after_vertices.ndim != 2
        or before_vertices.shape[1:] != (3,)
        or after_vertices.shape[1:] != (3,)
        or before_vertices.dtype != after_vertices.dtype
    ):
        return False

    for start in range(0, face_count, step):
        stop = min(start + step, face_count)
        before_triangles = np.ascontiguousarray(
            before_vertices[before_faces[start:stop]]
        )
        after_triangles = np.ascontiguousarray(
            after_vertices[after_faces[start:stop]]
        )
        if before_triangles.shape != after_triangles.shape:
            return False
        if not np.array_equal(
            before_triangles.view(np.uint8),
            after_triangles.view(np.uint8),
        ):
            return False
    return True


def _validate_overrides(overrides: np.ndarray, face_count: int | None = None) -> np.ndarray:
    source = np.asarray(overrides)
    if source.ndim != 1:
        raise PaintError("手修正データは1次元配列である必要があります")
    if face_count is not None and len(source) != int(face_count):
        raise PaintError(
            f"手修正データの面数が一致しません: {len(source):,} / {int(face_count):,}"
        )
    if not np.issubdtype(source.dtype, np.integer):
        raise PaintError("手修正データは整数である必要があります")
    if len(source) and (
        int(source.min()) < -1 or int(source.max()) >= PALETTE_STATE_COUNT
    ):
        raise PaintError(
            f"手修正の色番号は -1 または 0～{PALETTE_STATE_COUNT - 1} "
            "である必要があります"
        )
    return source.astype(np.int8, copy=False)


def encode_manual_overrides(
    overrides: np.ndarray,
    fingerprint: str,
) -> dict[str, object]:
    """Encode overrides compactly for embedding in one project JSON file."""

    values = np.ascontiguousarray(_validate_overrides(overrides), dtype=np.int8)
    compressed = zlib.compress(values.tobytes(), level=9)
    return {
        "encoding": PAINT_ENCODING,
        "face_count": int(len(values)),
        "modified_face_count": int(np.count_nonzero(values >= 0)),
        "mesh_fingerprint": str(fingerprint),
        "data": base64.b64encode(compressed).decode("ascii"),
    }


def decode_manual_overrides(
    payload: Mapping[str, object],
    *,
    expected_face_count: int | None = None,
    expected_fingerprint: str | None = None,
) -> np.ndarray:
    """Decode and strictly validate a project-embedded override array."""

    if payload.get("encoding") != PAINT_ENCODING:
        raise PaintError("未対応の手修正データ形式です")
    try:
        face_count = int(payload["face_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PaintError("手修正データに正しい面数がありません") from exc
    if face_count < 0:
        raise PaintError("手修正データの面数が不正です")
    if expected_face_count is not None and face_count != int(expected_face_count):
        raise PaintError(
            f"手修正データの面数が現在のモデルと一致しません: "
            f"{face_count:,} / {int(expected_face_count):,}"
        )
    fingerprint = payload.get("mesh_fingerprint")
    if expected_fingerprint is not None and fingerprint != expected_fingerprint:
        raise PaintError("形状が変わっているため、保存された色修正を適用できません")
    encoded = payload.get("data")
    if not isinstance(encoded, str):
        raise PaintError("手修正データ本体がありません")
    try:
        compressed = base64.b64decode(encoded.encode("ascii"), validate=True)
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, face_count + 1)
        raw += decompressor.flush()
    except (ValueError, UnicodeEncodeError, binascii.Error, zlib.error) as exc:
        raise PaintError("手修正データが破損しています") from exc
    if decompressor.unconsumed_tail or decompressor.unused_data or len(raw) != face_count:
        raise PaintError("手修正データの展開後サイズが面数と一致しません")
    result = np.frombuffer(raw, dtype=np.int8).copy()
    return _validate_overrides(result, face_count)


class PaintSession:
    """Non-UI editing state for final-mesh Full Spectrum face colours."""

    def __init__(
        self,
        level: MeshLevel,
        height_mm: float,
        auto_indices: np.ndarray,
        *,
        overrides: np.ndarray | None = None,
        max_history: int = 64,
        max_history_faces: int = 2_000_000,
    ) -> None:
        self.level = level
        self.vertices = np.asarray(level.vertices_unit, dtype=np.float64)
        self.faces = _validate_faces(level.faces, len(self.vertices))
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3:
            raise PaintError("vertices_unit は Nx3 配列である必要があります")
        if not np.all(np.isfinite(self.vertices)):
            raise PaintError("モデル頂点にNaNまたは無限値があります")
        self.height_mm = float(height_mm)
        if not np.isfinite(self.height_mm) or self.height_mm <= 0.0:
            raise PaintError("出力高さは0より大きくしてください")
        self.max_history = max(1, int(max_history))
        self.max_history_faces = max(1, int(max_history_faces))
        self.allowed_face_mask = np.ones(len(self.faces), dtype=bool)

        self.neighbors = build_partial_face_neighbors(self.faces, len(self.vertices))
        triangles = self.vertices[self.faces]
        self.centroids_unit = triangles.mean(axis=1)
        raw_normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        lengths = np.linalg.norm(raw_normals, axis=1)
        self.normal_valid = lengths > 1e-12
        self.normals = np.zeros_like(raw_normals)
        self.normals[self.normal_valid] = raw_normals[self.normal_valid] / lengths[self.normal_valid, None]
        neighbor_vertices = np.where(self.neighbors >= 0, self.neighbors, 0)
        self.edge_costs_unit = np.linalg.norm(
            self.centroids_unit[neighbor_vertices] - self.centroids_unit[:, None, :],
            axis=2,
        )
        self.edge_costs_unit[self.neighbors < 0] = np.inf

        self.auto_indices = np.empty(len(self.faces), dtype=np.int8)
        self.set_auto_indices(auto_indices)
        if overrides is None:
            self.overrides = np.full(len(self.faces), -1, dtype=np.int8)
        else:
            self.overrides = _validate_overrides(overrides, len(self.faces)).copy()

        self._undo: list[PaintCommand] = []
        self._redo: list[PaintCommand] = []
        self._undo_face_total = 0
        self._stroke_before: dict[int, int] | None = None
        self._stroke_label = "ブラシ"
        # Airbrush pigment is fractional until it crosses a deterministic
        # discrete-state threshold. Sparse storage exists only during an active
        # press/release group and scales with touched faces, not total mesh size.
        # Entries are (target, source, accumulated dose).
        self._airbrush_residual: dict[int, tuple[int, int, float]] = {}
        self._smudge_carried_state: int | None = None
        self.fingerprint = mesh_fingerprint(level)

    @property
    def modified_face_count(self) -> int:
        return int(np.count_nonzero(self.overrides >= 0))

    @property
    def can_undo(self) -> bool:
        return bool(self._undo or self._stroke_before)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    def set_height_mm(self, value: float) -> None:
        height = float(value)
        if not np.isfinite(height) or height <= 0.0:
            raise PaintError("出力高さは0より大きくしてください")
        self.height_mm = height
        self._airbrush_residual.clear()

    def set_auto_indices(self, indices: np.ndarray) -> None:
        values = np.asarray(indices)
        if values.ndim != 1 or len(values) != len(self.faces):
            raise PaintError("自動色の面数がモデルと一致しません")
        if not np.issubdtype(values.dtype, np.integer):
            raise PaintError("自動色は整数配列である必要があります")
        if len(values) and (
            int(values.min()) < 0 or int(values.max()) >= PALETTE_STATE_COUNT
        ):
            raise PaintError(
                f"自動色番号は0～{PALETTE_STATE_COUNT - 1}である必要があります"
            )
        self.auto_indices = values.astype(np.int8, copy=True)
        if hasattr(self, "_airbrush_residual"):
            self._airbrush_residual.clear()

    def set_allowed_faces(self, mask: np.ndarray | None) -> None:
        if mask is None:
            self.allowed_face_mask = np.ones(len(self.faces), dtype=bool)
            self._airbrush_residual.clear()
            return
        values = np.asarray(mask)
        if values.shape != (len(self.faces),):
            raise PaintError("編集可能面マスクの面数がモデルと一致しません")
        self.allowed_face_mask = values.astype(bool, copy=True)
        self._airbrush_residual.clear()

    def _visible_mask(
        self,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None,
    ) -> np.ndarray | None:
        """Validate a transient renderer visibility mask without storing it."""

        if visible_face_mask is None:
            return None
        visible = np.asarray(visible_face_mask, dtype=bool)
        if visible.shape != (len(self.faces),):
            raise PaintError("可視面マスクの面数がモデルと一致しません")
        return visible

    def effective_indices(self) -> np.ndarray:
        return np.where(self.overrides >= 0, self.overrides, self.auto_indices).astype(
            np.int8, copy=False
        )

    def effective_indices_for_faces(
        self,
        face_indices: np.ndarray | list[int] | tuple[int, ...],
    ) -> np.ndarray:
        """Return effective states for only the requested faces.

        Interactive tools normally touch a small screen-space region.  Avoid
        materialising an array for every face in a large model when the caller
        will immediately discard all but that region.  Order and duplicates
        are preserved so the result can be paired directly with the input.
        """

        indices = np.asarray(face_indices)
        if indices.ndim != 1 or not np.issubdtype(indices.dtype, np.integer):
            raise PaintError("対象面は1次元の整数配列で指定してください")
        if len(indices) == 0:
            return np.empty(0, dtype=np.int8)
        if int(indices.min()) < 0 or int(indices.max()) >= len(self.faces):
            raise PaintError("対象面に範囲外のインデックスがあります")
        selected = indices.astype(np.intp, copy=False)
        manual = self.overrides[selected]
        return np.where(
            manual >= 0,
            manual,
            self.auto_indices[selected],
        ).astype(np.int8, copy=False)

    def begin_stroke(self, label: str = "ブラシ") -> None:
        if self._stroke_before is not None:
            raise PaintError("前のブラシ操作がまだ終了していません")
        self._stroke_before = {}
        self._stroke_label = str(label)
        self._airbrush_residual.clear()
        self._smudge_carried_state = None

    def end_stroke(self) -> int:
        self._airbrush_residual.clear()
        self._smudge_carried_state = None
        if self._stroke_before is None:
            return 0
        original = self._stroke_before
        label = self._stroke_label
        self._stroke_before = None
        if not original:
            return 0
        indices = np.fromiter(sorted(original), dtype=np.int32)
        before = np.asarray([original[int(index)] for index in indices], dtype=np.int8)
        after = self.overrides[indices].copy()
        changed = before != after
        if not np.any(changed):
            return 0
        command = PaintCommand(indices[changed], before[changed], after[changed], label)
        self._push_command(command)
        return command.face_count

    def cancel_stroke(self) -> int:
        self._airbrush_residual.clear()
        self._smudge_carried_state = None
        if self._stroke_before is None:
            return 0
        original = self._stroke_before
        self._stroke_before = None
        if not original:
            return 0
        indices = np.fromiter(original.keys(), dtype=np.int32)
        self.overrides[indices] = np.asarray(
            [original[int(index)] for index in indices], dtype=np.int8
        )
        return int(len(indices))

    def _push_command(self, command: PaintCommand) -> None:
        if command.face_count == 0:
            return
        self._undo.append(command)
        self._undo_face_total += command.face_count
        self._redo.clear()
        while (
            len(self._undo) > 1
            and (
                len(self._undo) > self.max_history
                or self._undo_face_total > self.max_history_faces
            )
        ):
            removed = self._undo.pop(0)
            self._undo_face_total -= removed.face_count

    def _set_overrides(
        self,
        face_indices: np.ndarray,
        values: int | np.ndarray,
        label: str,
    ) -> np.ndarray:
        indices = np.asarray(face_indices)
        if indices.ndim != 1 or not np.issubdtype(indices.dtype, np.integer):
            raise PaintError("対象面は1次元の整数配列で指定してください")
        if len(indices) == 0:
            return np.empty(0, dtype=np.int32)
        if int(indices.min()) < 0 or int(indices.max()) >= len(self.faces):
            raise PaintError("対象面に範囲外のインデックスがあります")
        allowed = self.allowed_face_mask[indices]
        if not np.isscalar(values):
            source_values = np.asarray(values)
            if source_values.ndim == 1 and len(source_values) == len(indices):
                values = source_values[allowed]
        indices = indices[allowed]
        if len(indices) == 0:
            return np.empty(0, dtype=np.int32)
        face_indices = indices
        indices = np.unique(indices.astype(np.int32, copy=False))
        if np.isscalar(values):
            scalar = int(values)
            if scalar < -1 or scalar >= PALETTE_STATE_COUNT:
                raise PaintError(
                    f"変更後の色番号は -1 または 0～{PALETTE_STATE_COUNT - 1} "
                    "である必要があります"
                )
            after = np.full(len(indices), scalar, dtype=np.int8)
        else:
            source = np.asarray(values)
            if source.ndim != 1 or len(source) != len(face_indices):
                raise PaintError("対象面と変更後の色数が一致しません")
            if not np.issubdtype(source.dtype, np.integer):
                raise PaintError("変更後の色は整数で指定してください")
            # Non-scalar callers currently pass unique indices. Handle a sorted
            # unique input explicitly so state-to-face correspondence is clear.
            original_indices = np.asarray(face_indices, dtype=np.int32)
            if len(np.unique(original_indices)) != len(original_indices):
                raise PaintError("面ごとに色を指定する場合、対象面を重複させないでください")
            if len(source) and (
                int(source.min()) < -1 or int(source.max()) >= PALETTE_STATE_COUNT
            ):
                raise PaintError(
                    f"変更後の色番号は -1 または 0～{PALETTE_STATE_COUNT - 1} "
                    "である必要があります"
                )
            order = np.argsort(original_indices)
            after = source.astype(np.int8, copy=False)[order]
        if len(after) and (
            int(after.min()) < -1 or int(after.max()) >= PALETTE_STATE_COUNT
        ):
            raise PaintError(
                f"変更後の色番号は -1 または 0～{PALETTE_STATE_COUNT - 1} "
                "である必要があります"
            )

        before = self.overrides[indices].copy()
        changed = before != after
        if not np.any(changed):
            return np.empty(0, dtype=np.int32)
        indices = indices[changed]
        before = before[changed]
        after = after[changed]
        for face in indices:
            self._airbrush_residual.pop(int(face), None)
        if self._stroke_before is not None:
            for face, previous in zip(indices, before, strict=True):
                self._stroke_before.setdefault(int(face), int(previous))
            self.overrides[indices] = after
        else:
            self.overrides[indices] = after
            self._push_command(PaintCommand(indices, before, after.copy(), str(label)))
        return indices

    @staticmethod
    def _validate_state(state: int) -> int:
        value = int(state)
        if value < 0 or value >= PALETTE_STATE_COUNT:
            raise PaintError(
                f"塗る色番号は0～{PALETTE_STATE_COUNT - 1}で指定してください"
            )
        return value

    @staticmethod
    def _minimum_normal_dot(
        protect_sharp_edges: bool,
        max_angle_degrees: float,
    ) -> float | None:
        if not bool(protect_sharp_edges):
            return None
        angle = float(max_angle_degrees)
        if not np.isfinite(angle) or angle <= 0.0 or angle > 180.0:
            raise PaintError("稜線保護角度は0より大きく180以下にしてください")
        return float(np.cos(np.deg2rad(angle)))

    def surface_region(
        self,
        seed_face: int,
        radius_mm: float,
        *,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> SurfaceRegion:
        """Return a part- and crease-bounded geodesic brush footprint."""

        minimum_dot = self._minimum_normal_dot(
            protect_sharp_edges, max_angle_degrees
        )
        visible = self._visible_mask(visible_face_mask)
        try:
            return plan_surface_region(
                seed_face,
                radius_mm,
                self.neighbors,
                self.edge_costs_unit,
                distance_scale=self.height_mm,
                allowed_faces=self.allowed_face_mask,
                traversal_mask=visible,
                face_normals=self.normals,
                normal_valid=self.normal_valid,
                minimum_normal_dot=minimum_dot,
            )
        except PaintToolError as exc:
            raise PaintError(str(exc)) from exc

    def stroke_surface_region(
        self,
        seed_faces: np.ndarray | list[int] | tuple[int, ...],
        radius_mm: float,
        *,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> SurfaceRegion:
        """Return one nearest-dab region for a complete sampled stroke path."""

        minimum_dot = self._minimum_normal_dot(
            protect_sharp_edges, max_angle_degrees
        )
        visible = self._visible_mask(visible_face_mask)
        try:
            return multi_seed_surface_region(
                seed_faces,
                radius_mm,
                self.neighbors,
                self.edge_costs_unit,
                distance_scale=self.height_mm,
                allowed_faces=self.allowed_face_mask,
                traversal_mask=visible,
                face_normals=self.normals,
                normal_valid=self.normal_valid,
                minimum_normal_dot=minimum_dot,
            )
        except PaintToolError as exc:
            raise PaintError(str(exc)) from exc

    def sample_painted_state(
        self,
        face_index: int,
        *,
        adaptive_state: int | None = None,
    ) -> int:
        """Sample the currently assigned/painted state for a 3D eyedropper.

        Manual face paint always wins.  A renderer that resolves an adaptive
        sub-face leaf can supply that exact state; otherwise the automatic
        face-level assignment is returned.  Raw OBJ vertex colour is never
        sampled here.
        """

        face = int(face_index)
        if face < 0 or face >= len(self.faces):
            raise PaintError("スポイト位置がモデル範囲外です")
        manual = int(self.overrides[face])
        if manual >= 0:
            return manual
        if adaptive_state is not None:
            return self._validate_state(adaptive_state)
        return int(self.auto_indices[face])

    def crease_edges(
        self,
        max_angle_degrees: float = 45.0,
        *,
        include_boundaries: bool = True,
        respect_allowed_faces: bool = True,
    ) -> CreaseEdgeData:
        """Return fold/boundary segments suitable for an on-canvas overlay."""

        minimum_dot = self._minimum_normal_dot(True, max_angle_degrees)
        face_count = len(self.faces)
        face_ids = np.arange(face_count, dtype=np.int32)
        face_allowed = (
            self.allowed_face_mask
            if respect_allowed_faces
            else np.ones(face_count, dtype=bool)
        )
        edge_slots = ((0, 1), (1, 2), (2, 0))
        vertex_chunks: list[np.ndarray] = []
        face_chunks: list[np.ndarray] = []
        angle_chunks: list[np.ndarray] = []
        boundary_chunks: list[np.ndarray] = []
        # Process one local edge slot at a time.  This avoids constructing a
        # 3M x 2 edge table (~48 MiB at two million faces) merely to retain the
        # comparatively small set of actual crease lines.
        for slot, (first_vertex, second_vertex) in enumerate(edge_slots):
            neighbor_ids = self.neighbors[:, slot]
            neighbor_safe = np.where(neighbor_ids >= 0, neighbor_ids, 0)
            neighbor_allowed = neighbor_ids >= 0
            if respect_allowed_faces:
                neighbor_allowed &= self.allowed_face_mask[neighbor_safe]
            internal = (
                face_allowed
                & neighbor_allowed
                & (face_ids < neighbor_ids)
            )
            internal_faces = np.flatnonzero(internal).astype(np.int32, copy=False)
            if len(internal_faces):
                other_faces = neighbor_ids[internal_faces]
                valid = (
                    self.normal_valid[internal_faces]
                    & self.normal_valid[other_faces]
                )
                dots = np.ones(len(internal_faces), dtype=np.float64)
                dots[valid] = np.einsum(
                    "ij,ij->i",
                    self.normals[internal_faces[valid]],
                    self.normals[other_faces[valid]],
                )
                keep = valid & (dots < float(minimum_dot))
                crease_faces = internal_faces[keep]
                crease_other = other_faces[keep]
                if len(crease_faces):
                    vertex_chunks.append(
                        self.faces[crease_faces][
                            :, (first_vertex, second_vertex)
                        ].astype(np.int32, copy=False)
                    )
                    face_chunks.append(
                        np.column_stack((crease_faces, crease_other)).astype(
                            np.int32, copy=False
                        )
                    )
                    angle_chunks.append(
                        np.rad2deg(np.arccos(np.clip(dots[keep], -1.0, 1.0))).astype(
                            np.float32, copy=False
                        )
                    )
                    boundary_chunks.append(np.zeros(len(crease_faces), dtype=bool))
            if include_boundaries:
                # Topological boundaries and the active-part perimeter.
                boundary = face_allowed & (
                    (neighbor_ids < 0)
                    | ((neighbor_ids >= 0) & ~neighbor_allowed)
                )
                boundary_faces = np.flatnonzero(boundary).astype(
                    np.int32, copy=False
                )
                if len(boundary_faces):
                    vertex_chunks.append(
                        self.faces[boundary_faces][
                            :, (first_vertex, second_vertex)
                        ].astype(np.int32, copy=False)
                    )
                    face_chunks.append(
                        np.column_stack(
                            (
                                boundary_faces,
                                np.full(len(boundary_faces), -1, dtype=np.int32),
                            )
                        )
                    )
                    angle_chunks.append(
                        np.full(len(boundary_faces), 180.0, dtype=np.float32)
                    )
                    boundary_chunks.append(np.ones(len(boundary_faces), dtype=bool))

        selected_vertex_pairs = (
            np.concatenate(vertex_chunks, axis=0)
            if vertex_chunks
            else np.empty((0, 2), dtype=np.int32)
        )
        pairs = (
            np.concatenate(face_chunks, axis=0)
            if face_chunks
            else np.empty((0, 2), dtype=np.int32)
        )
        angles = (
            np.concatenate(angle_chunks)
            if angle_chunks
            else np.empty(0, dtype=np.float32)
        )
        boundary_mask = (
            np.concatenate(boundary_chunks)
            if boundary_chunks
            else np.empty(0, dtype=bool)
        )
        segments = self.vertices[selected_vertex_pairs]
        return CreaseEdgeData(
            vertex_pairs=selected_vertex_pairs,
            face_pairs=pairs,
            segments_unit=segments,
            angles_degrees=angles,
            boundary_mask=boundary_mask,
        )

    def airbrush_stroke(
        self,
        seed_faces: np.ndarray | list[int] | tuple[int, ...],
        state: int,
        radius_mm: float,
        strength: float,
        *,
        pressure: float = 1.0,
        dab_count: int = 1,
        enabled_states: np.ndarray | list[bool] | list[int] | None = None,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> np.ndarray:
        """Deposit a soft discrete-state airbrush stroke as one undoable edit.

        Overlapping/duplicate dabs use their maximum falloff, so denser pointer
        event delivery cannot make a stroke darker.  Fractional pigment is
        retained only while an explicit ``begin_stroke``/``end_stroke`` group
        is active; a released/standalone stroke never leaves hidden state that
        Undo or project serialization cannot reproduce.
        """

        standalone = self._stroke_before is None
        if standalone:
            self._airbrush_residual.clear()
        try:
            return self._airbrush_stroke_impl(
                seed_faces,
                state,
                radius_mm,
                strength,
                pressure=pressure,
                dab_count=dab_count,
                enabled_states=enabled_states,
                protect_sharp_edges=protect_sharp_edges,
                max_angle_degrees=max_angle_degrees,
                visible_face_mask=visible_face_mask,
            )
        finally:
            if standalone:
                self._airbrush_residual.clear()

    def _airbrush_stroke_impl(
        self,
        seed_faces: np.ndarray | list[int] | tuple[int, ...],
        state: int,
        radius_mm: float,
        strength: float,
        *,
        pressure: float,
        dab_count: int,
        enabled_states: np.ndarray | list[bool] | list[int] | None,
        protect_sharp_edges: bool,
        max_angle_degrees: float,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None,
    ) -> np.ndarray:

        target = self._validate_state(state)
        try:
            amount = validate_strength(strength)
            pen_pressure = validate_strength(pressure, "pressure")
            active = enabled_state_ids(enabled_states, PALETTE_STATE_COUNT)
        except PaintToolError as exc:
            raise PaintError(str(exc)) from exc
        if target not in set(int(value) for value in active):
            raise PaintError("エアブラシの色は有効な印刷色から選んでください")
        if amount == 0.0 or pen_pressure == 0.0:
            return np.empty(0, dtype=np.int32)
        deposits_per_press = int(dab_count)
        if deposits_per_press < 1:
            raise PaintError("dab_count must be positive")
        effective_radius = float(radius_mm) * airbrush_radius_scale(pen_pressure)
        region = self.stroke_surface_region(
            seed_faces,
            effective_radius,
            protect_sharp_edges=protect_sharp_edges,
            max_angle_degrees=max_angle_degrees,
            visible_face_mask=visible_face_mask,
        )
        if len(region.faces) == 0:
            return np.empty(0, dtype=np.int32)
        deposits = accumulated_airbrush_deposit(
            soft_falloff(region.distances_mm, effective_radius),
            amount,
            pen_pressure,
            deposits_per_press,
        )
        current = self.effective_indices_for_faces(region.faces)
        useful = current != target
        faces = region.faces[useful]
        sources = current[useful]
        deposits = deposits[useful]
        if len(faces) == 0:
            return np.empty(0, dtype=np.int32)
        thresholds = deterministic_thresholds(faces, sources, target)
        totals = np.empty(len(faces), dtype=np.float32)
        for position, (face, source, deposit) in enumerate(
            zip(faces, sources, deposits, strict=True)
        ):
            face_id = int(face)
            source_id = int(source)
            previous = self._airbrush_residual.get(face_id)
            residual = (
                float(previous[2])
                if previous is not None
                and previous[0] == target
                and previous[1] == source_id
                else 0.0
            )
            totals[position] = residual + float(deposit)
        reached = totals + 1e-7 >= thresholds
        for face, source, total, did_reach in zip(
            faces, sources, totals, reached, strict=True
        ):
            face_id = int(face)
            if bool(did_reach):
                self._airbrush_residual.pop(face_id, None)
            else:
                self._airbrush_residual[face_id] = (
                    target,
                    int(source),
                    float(total),
                )
        if not np.any(reached):
            return np.empty(0, dtype=np.int32)
        planned_faces = faces[reached]
        planned = np.full(len(planned_faces), target, dtype=np.int8)
        return self.apply_planned_states(
            planned_faces,
            planned,
            "エアブラシ",
            protect_manual=False,
        )

    def airbrush(
        self,
        seed_face: int,
        state: int,
        radius_mm: float,
        strength: float,
        *,
        pressure: float = 1.0,
        dab_count: int = 1,
        enabled_states: np.ndarray | list[bool] | list[int] | None = None,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> np.ndarray:
        """Convenience wrapper for one airbrush dab."""

        return self.airbrush_stroke(
            np.asarray((seed_face,), dtype=np.int32),
            state,
            radius_mm,
            strength,
            pressure=pressure,
            dab_count=dab_count,
            enabled_states=enabled_states,
            protect_sharp_edges=protect_sharp_edges,
            max_angle_degrees=max_angle_degrees,
            visible_face_mask=visible_face_mask,
        )

    def smudge(
        self,
        seed_face: int,
        radius_mm: float,
        strength: float,
        *,
        pressure: float = 1.0,
        enabled_states: np.ndarray | list[bool] | list[int] | None = None,
        palette_rgb: np.ndarray,
        source_state: int | None = None,
        source_face: int | None = None,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> np.ndarray:
        """Carry the previous-dab colour forward and quantise enabled states.

        During an explicit stroke group, the first dab picks up its current
        colour and subsequent dabs transport that same source along the ordered
        stroke.  Callers may instead provide ``source_state`` or ``source_face``
        explicitly; the two options are mutually exclusive.
        """

        if source_state is not None and source_face is not None:
            raise PaintError("なじませ元は色または面のどちらか一方で指定してください")
        current_indices = self.effective_indices()
        seed = int(seed_face)
        if seed < 0 or seed >= len(self.faces):
            raise PaintError("クリックした面がモデル範囲外です")
        visible = self._visible_mask(visible_face_mask)
        if (
            not bool(self.allowed_face_mask[seed])
            or (visible is not None and not bool(visible[seed]))
        ):
            return np.empty(0, dtype=np.int32)
        if source_state is not None:
            carried_state = self._validate_state(source_state)
        elif source_face is not None:
            carried_state = self.sample_painted_state(source_face)
        elif self._stroke_before is not None and self._smudge_carried_state is not None:
            carried_state = int(self._smudge_carried_state)
        else:
            carried_state = int(current_indices[seed])
        if self._stroke_before is not None and (
            self._smudge_carried_state is None
            or source_state is not None
            or source_face is not None
        ):
            self._smudge_carried_state = carried_state

        region = self.surface_region(
            seed,
            radius_mm,
            protect_sharp_edges=protect_sharp_edges,
            max_angle_degrees=max_angle_degrees,
            visible_face_mask=visible,
        )
        if len(region.faces) == 0:
            return np.empty(0, dtype=np.int32)
        minimum_dot = self._minimum_normal_dot(
            protect_sharp_edges, max_angle_degrees
        )
        neighbor_ids = self.neighbors[region.faces]
        crossable = neighbor_ids >= 0
        safe_ids = np.where(crossable, neighbor_ids, 0)
        crossable &= self.allowed_face_mask[safe_ids]
        if visible is not None:
            crossable &= visible[safe_ids]
        if minimum_dot is not None:
            left = np.repeat(region.faces[:, None], 3, axis=1)
            valid = (
                crossable
                & self.normal_valid[left]
                & self.normal_valid[safe_ids]
            )
            dots = np.ones(crossable.shape, dtype=np.float64)
            dots[valid] = np.einsum(
                "ij,ij->i",
                self.normals[left[valid]],
                self.normals[safe_ids[valid]],
            )
            crossable &= ~valid | (dots >= minimum_dot)
        try:
            plan = plan_smudge(
                region,
                current_indices,
                self.neighbors,
                palette_rgb,
                enabled_states,
                strength,
                pressure=pressure,
                radius_mm=radius_mm,
                allowed_faces=self.allowed_face_mask,
                edge_crossable=crossable,
                source_state=carried_state,
            )
        except PaintToolError as exc:
            raise PaintError(str(exc)) from exc
        if len(plan.faces) == 0:
            return np.empty(0, dtype=np.int32)
        return self.apply_planned_states(
            plan.faces,
            plan.states,
            "こすってなじませる",
            protect_manual=False,
        )

    def smudge_stroke(
        self,
        seed_faces: np.ndarray | list[int] | tuple[int, ...],
        radius_mm: float,
        strength: float,
        *,
        pressure: float = 1.0,
        enabled_states: np.ndarray | list[bool] | list[int] | None = None,
        palette_rgb: np.ndarray,
        source_state: int | None = None,
        source_face: int | None = None,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> np.ndarray:
        """Apply an ordered directional smudge path as one Undo command."""

        seeds = np.asarray(seed_faces)
        if seeds.ndim != 1:
            raise PaintError("なじませ線は1次元の面番号列で指定してください")
        if len(seeds) == 0:
            return np.empty(0, dtype=np.int32)
        if not np.issubdtype(seeds.dtype, np.integer):
            raise PaintError("なじませ線は1次元の面番号列で指定してください")
        if int(seeds.min()) < 0 or int(seeds.max()) >= len(self.faces):
            raise PaintError("なじませ線にモデル範囲外の面があります")
        # Consecutive duplicates are pointer-density noise, but revisiting a
        # face later in the path is meaningful and remains ordered.
        keep = np.r_[True, seeds[1:] != seeds[:-1]]
        ordered = seeds[keep].astype(np.int32, copy=False)
        visible = self._visible_mask(visible_face_mask)
        eligible = self.allowed_face_mask[ordered]
        if visible is not None:
            eligible &= visible[ordered]
        ordered = ordered[eligible]
        if len(ordered) == 0:
            return np.empty(0, dtype=np.int32)
        owns_stroke = self._stroke_before is None
        undo_before = len(self._undo)
        if owns_stroke:
            self.begin_stroke("こすってなじませる")
        try:
            for position, seed in enumerate(ordered):
                self.smudge(
                    int(seed),
                    radius_mm,
                    strength,
                    pressure=pressure,
                    enabled_states=enabled_states,
                    palette_rgb=palette_rgb,
                    source_state=(source_state if position == 0 else None),
                    source_face=(source_face if position == 0 else None),
                    protect_sharp_edges=protect_sharp_edges,
                    max_angle_degrees=max_angle_degrees,
                    visible_face_mask=visible,
                )
            if not owns_stroke:
                # The outer caller owns final history grouping.
                return np.asarray(sorted(self._stroke_before or ()), dtype=np.int32)
            self.end_stroke()
        except Exception:
            if owns_stroke:
                self.cancel_stroke()
            raise
        if len(self._undo) > undo_before:
            return self._undo[-1].indices.copy()
        return np.empty(0, dtype=np.int32)

    def brush_faces(
        self,
        seed_face: int,
        radius_mm: float,
        *,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> np.ndarray:
        return self.surface_region(
            seed_face,
            radius_mm,
            protect_sharp_edges=protect_sharp_edges,
            max_angle_degrees=max_angle_degrees,
            visible_face_mask=visible_face_mask,
        ).faces

    def paint_brush(
        self,
        seed_face: int,
        state: int,
        radius_mm: float,
        *,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> np.ndarray:
        faces = self.brush_faces(
            seed_face,
            radius_mm,
            protect_sharp_edges=protect_sharp_edges,
            max_angle_degrees=max_angle_degrees,
            visible_face_mask=visible_face_mask,
        )
        return self._set_overrides(faces, self._validate_state(state), "ブラシ")

    def erase_brush(
        self,
        seed_face: int,
        radius_mm: float,
        *,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> np.ndarray:
        faces = self.brush_faces(
            seed_face,
            radius_mm,
            protect_sharp_edges=protect_sharp_edges,
            max_angle_degrees=max_angle_degrees,
            visible_face_mask=visible_face_mask,
        )
        return self._set_overrides(faces, -1, "自動色へ戻す")

    def _fill_connectivity_labels(
        self,
        connectivity_state_map: np.ndarray | None = None,
    ) -> np.ndarray:
        """Return the labels used only to decide where Fill may traverse.

        Manual overrides retain their canonical Full Spectrum state IDs.  A
        display mode may nevertheless show several of those IDs as the same
        printable colour.  ``connectivity_state_map`` lets that mode compare
        the displayed states without rewriting the saved overrides or the
        automatic assignment.  The returned labels are never committed.
        """

        labels = self.effective_indices()
        if connectivity_state_map is None:
            return labels
        mapping = np.asarray(connectivity_state_map)
        if (
            mapping.shape != (PALETTE_STATE_COUNT,)
            or not np.issubdtype(mapping.dtype, np.integer)
        ):
            raise PaintError(
                f"塗りつぶし表示色マップは{PALETTE_STATE_COUNT}個の整数で指定してください"
            )
        if len(mapping) and (
            int(mapping.min()) < 0
            or int(mapping.max()) >= PALETTE_STATE_COUNT
        ):
            raise PaintError(
                f"塗りつぶし表示色マップは0～{PALETTE_STATE_COUNT - 1}で指定してください"
            )
        return mapping[labels].astype(np.int8, copy=False)

    def connected_fill_faces(
        self,
        seed_face: int,
        *,
        connectivity_state_map: np.ndarray | None = None,
        connectivity_face_labels: np.ndarray | None = None,
    ) -> np.ndarray:
        seed = int(seed_face)
        if seed < 0 or seed >= len(self.faces):
            raise PaintError("クリックした面がモデル範囲外です")
        if not bool(self.allowed_face_mask[seed]):
            return np.empty(0, dtype=np.int32)
        if connectivity_face_labels is None:
            labels = PaintSession._fill_connectivity_labels(
                self,
                connectivity_state_map,
            )
        else:
            labels = np.asarray(connectivity_face_labels)
            if (
                labels.shape != (len(self.faces),)
                or not np.issubdtype(labels.dtype, np.integer)
            ):
                raise PaintError(
                    "塗りつぶし接続ラベルは各面につき1個の整数で指定してください"
                )
            if len(labels) and (
                int(labels.min()) < -1
                or int(labels.max()) >= PALETTE_STATE_COUNT
            ):
                raise PaintError(
                    f"塗りつぶし接続ラベルは-1～{PALETTE_STATE_COUNT - 1}で指定してください"
                )
        target = int(labels[seed])
        if target < 0:
            return np.empty(0, dtype=np.int32)
        visited = np.zeros(len(self.faces), dtype=bool)
        visited[seed] = True
        pending: deque[int] = deque((seed,))
        selected: list[int] = []
        while pending:
            face = pending.popleft()
            selected.append(face)
            for neighbor_value in self.neighbors[face]:
                neighbor = int(neighbor_value)
                if (
                    neighbor < 0
                    or visited[neighbor]
                    or not bool(self.allowed_face_mask[neighbor])
                    or int(labels[neighbor]) != target
                ):
                    continue
                visited[neighbor] = True
                pending.append(neighbor)
        return np.asarray(selected, dtype=np.int32)

    def fill(
        self,
        seed_face: int,
        state: int,
        *,
        connectivity_state_map: np.ndarray | None = None,
        connectivity_face_labels: np.ndarray | None = None,
    ) -> np.ndarray:
        if (
            connectivity_state_map is None
            and connectivity_face_labels is None
        ):
            faces = self.connected_fill_faces(seed_face)
        else:
            faces = self.connected_fill_faces(
                seed_face,
                connectivity_state_map=connectivity_state_map,
                connectivity_face_labels=connectivity_face_labels,
            )
        requested = self._validate_state(state)
        if connectivity_face_labels is not None and len(faces):
            # Existing target-colour faces are traversal bridges, not edits.
            # Preserve their automatic provenance and any adaptive sub-face
            # detail; commit only faces whose currently visible colour changes.
            visible = PaintSession._fill_connectivity_labels(
                self,
                connectivity_state_map,
            )
            faces = faces[visible[faces] != requested]
        return self._set_overrides(faces, requested, "塗りつぶし")

    def smooth_boundary(
        self,
        seed_face: int,
        radius_mm: float,
        *,
        iterations: int = 2,
        protect_sharp_edges: bool = True,
        max_angle_degrees: float = 45.0,
        visible_face_mask: np.ndarray | list[bool] | tuple[bool, ...] | None = None,
    ) -> np.ndarray:
        passes = int(iterations)
        if passes < 1 or passes > 20:
            raise PaintError("境界ならし回数は1～20で指定してください")
        region = self.brush_faces(
            seed_face,
            radius_mm,
            protect_sharp_edges=protect_sharp_edges,
            max_angle_degrees=max_angle_degrees,
            visible_face_mask=visible_face_mask,
        )
        visible = self._visible_mask(visible_face_mask)
        original = self.effective_indices()
        labels = original.copy()
        for _ in range(passes):
            neighbor_ids = self.neighbors[region]
            neighbor_labels = np.full(neighbor_ids.shape, -1, dtype=np.int8)
            valid = neighbor_ids >= 0
            safe_ids = np.where(valid, neighbor_ids, 0)
            valid &= self.allowed_face_mask[safe_ids]
            if visible is not None:
                valid &= visible[safe_ids]
            neighbor_labels[valid] = labels[neighbor_ids[valid]]
            first, second, third = (
                neighbor_labels[:, 0],
                neighbor_labels[:, 1],
                neighbor_labels[:, 2],
            )
            majority = np.where(
                (first >= 0) & (first == second),
                first,
                np.where(
                    (first >= 0) & (first == third),
                    first,
                    np.where((second >= 0) & (second == third), second, -1),
                ),
            )
            change = (majority >= 0) & (majority != labels[region])
            if not np.any(change):
                break
            next_labels = labels.copy()
            next_labels[region[change]] = majority[change]
            labels = next_labels
        changed = region[labels[region] != original[region]]
        if not len(changed):
            return np.empty(0, dtype=np.int32)
        return self._set_overrides(changed, labels[changed], "境界ならし")

    def apply_planned_states(
        self,
        face_indices: np.ndarray,
        planned_states: np.ndarray,
        label: str,
        *,
        protect_manual: bool = True,
    ) -> np.ndarray:
        """Apply one validated, reversible batch produced by a planning tool.

        Colour-refinement tools calculate their proposal without mutating the
        session.  This method is the sole commit boundary: it validates the
        face/state correspondence, honours the active part mask, optionally
        protects existing manual paint, drops effective no-ops, and records
        every remaining change as *one* undo command.

        ``planned_states`` must contain one palette state for each entry in
        ``face_indices``.  Duplicate face IDs are rejected because accepting
        them would make the intended final state ambiguous.
        """

        indices = np.asarray(face_indices)
        states = np.asarray(planned_states)
        if indices.ndim != 1 or not np.issubdtype(indices.dtype, np.integer):
            raise PaintError("補正対象面は1次元の整数配列で指定してください")
        if states.ndim != 1 or len(states) != len(indices):
            raise PaintError("補正対象面と補正後の色数が一致しません")
        if not np.issubdtype(states.dtype, np.integer):
            raise PaintError("補正後の色は整数で指定してください")
        if not isinstance(protect_manual, (bool, np.bool_)):
            raise PaintError("手修正保護は真偽値で指定してください")
        if len(indices) == 0:
            return np.empty(0, dtype=np.int32)
        if int(indices.min()) < 0 or int(indices.max()) >= len(self.faces):
            raise PaintError("補正対象面に範囲外のインデックスがあります")
        if len(np.unique(indices)) != len(indices):
            raise PaintError("補正対象面を重複させないでください")
        if int(states.min()) < 0 or int(states.max()) >= PALETTE_STATE_COUNT:
            raise PaintError(
                f"補正後の色番号は0～{PALETTE_STATE_COUNT - 1}で指定してください"
            )

        indices = indices.astype(np.int32, copy=False)
        states = states.astype(np.int8, copy=False)
        keep = self.allowed_face_mask[indices]
        if bool(protect_manual):
            keep &= self.overrides[indices] < 0
        # Do not turn an unchanged automatic assignment into a manual
        # override.  This keeps project payloads small and makes later palette
        # changes behave exactly as before on untouched faces.
        keep &= self.effective_indices()[indices] != states
        if not np.any(keep):
            return np.empty(0, dtype=np.int32)
        return self._set_overrides(indices[keep], states[keep], str(label))

    def clear_overrides(self) -> np.ndarray:
        self._airbrush_residual.clear()
        faces = np.flatnonzero(self.overrides >= 0).astype(np.int32)
        return self._set_overrides(faces, -1, "全修正を解除")

    def undo(self) -> PaintCommand | None:
        self._airbrush_residual.clear()
        if self._stroke_before is not None:
            self.end_stroke()
        if not self._undo:
            return None
        command = self._undo.pop()
        self._undo_face_total -= command.face_count
        self.overrides[command.indices] = command.before
        self._redo.append(command)
        return command

    def redo(self) -> PaintCommand | None:
        self._airbrush_residual.clear()
        if self._stroke_before is not None:
            self.end_stroke()
        if not self._redo:
            return None
        command = self._redo.pop()
        self.overrides[command.indices] = command.after
        self._undo.append(command)
        self._undo_face_total += command.face_count
        return command

    def serialize_overrides(self) -> dict[str, object]:
        return encode_manual_overrides(self.overrides, self.fingerprint)

    def restore_overrides(self, payload: Mapping[str, object]) -> int:
        values = decode_manual_overrides(
            payload,
            expected_face_count=len(self.faces),
            expected_fingerprint=self.fingerprint,
        )
        self.overrides = values
        self._undo.clear()
        self._redo.clear()
        self._undo_face_total = 0
        self._stroke_before = None
        self._airbrush_residual.clear()
        return self.modified_face_count
