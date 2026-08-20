from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

import numpy as np
import trimesh
from scipy.spatial import cKDTree
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from . import assembly as _assembly
from .engine import face_neighbors_partial, signed_volume, triangle_areas
from .models import MeshLevel, PreparedGeometry
from .paint import mesh_fingerprint
from .parts import PartPaletteError, validate_part_layout


class ManualJointError(RuntimeError):
    """A requested joint cannot be created without damaging print geometry."""


ManualJointAvailabilityCode = Literal[
    "ready",
    "needs_multiple_parts",
    "needs_solidify",
    "beta_no_planar_shared_interface",
    "automatic_joint_conflict",
    "already_jointed",
    "freehand_split_unsupported",
    "invalid_metadata",
]

MANUAL_JOINT_WORKFLOW_KEYS = (
    "joint.workflow.solidify",
    "joint.workflow.reopen_manual",
    "joint.workflow.select_male",
    "joint.workflow.hide_other",
    "joint.workflow.select_tool",
    "joint.workflow.click_generated_plane",
)


@dataclass(frozen=True)
class ManualJointAvailability:
    """Structured, local-only guidance for the beta joint workflow.

    Geometry remains untouched.  ``message_key`` and ``next_step_key`` are
    ready for :class:`~spectrum_mapper.i18n.Translator`, letting the manual
    editor explain why placement is unavailable before the user clicks a face.
    """

    code: ManualJointAvailabilityCode
    available: bool
    message_key: str
    next_step_key: str | None
    interface_count: int = 0
    eligible_part_ids: tuple[int, ...] = ()
    technical_detail: str = ""
    workflow_keys: tuple[str, ...] = MANUAL_JOINT_WORKFLOW_KEYS

    @property
    def message_values(self) -> dict[str, object]:
        """Formatting values accepted by the status message's i18n template."""

        return {"interfaces": int(self.interface_count)}


@dataclass(frozen=True)
class ManualJointSettings:
    """Exact keyed-rectangle dimensions in print millimetres."""

    width_mm: float = 6.0
    height_mm: float = 4.0
    depth_mm: float = 6.0
    clearance_mm: float = 0.25
    boundary_safety_mm: float = 0.25
    wall_safety_mm: float = 0.50

    def validated(self) -> "ManualJointSettings":
        values = (
            self.width_mm,
            self.height_mm,
            self.depth_mm,
            self.clearance_mm,
            self.boundary_safety_mm,
            self.wall_safety_mm,
        )
        if not np.isfinite(values).all():
            raise ManualJointError("ジョイント寸法に有限でない値があります")
        if self.width_mm < 1.0 or self.height_mm < 1.0:
            raise ManualJointError("ジョイントの幅と高さは1.0 mm以上にしてください")
        if self.depth_mm < 1.0:
            raise ManualJointError("ジョイントの突き出し深さは1.0 mm以上にしてください")
        if not 0.05 <= self.clearance_mm <= 1.50:
            raise ManualJointError("クリアランスは0.05～1.50 mmで指定してください")
        if self.boundary_safety_mm < 0.0 or self.wall_safety_mm < 0.0:
            raise ManualJointError("安全余白は0以上にしてください")
        return self


@dataclass(frozen=True)
class ManualJointInterface:
    interface_index: int
    seam_id: int
    first_part_id: int
    second_part_id: int
    first_cap_face_ids: tuple[int, ...]
    second_cap_face_ids: tuple[int, ...]


@dataclass(frozen=True)
class ManualJointTarget:
    interface_index: int
    seam_id: int
    male_part_id: int
    female_part_id: int
    male_face_id: int
    female_face_id: int
    center_unit: tuple[float, float, float]
    axis_u: tuple[float, float, float]
    axis_v: tuple[float, float, float]
    male_outward: tuple[float, float, float]
    female_outward: tuple[float, float, float]
    boundary_margin_mm: float
    male_cap_face_ids: tuple[int, ...]
    female_cap_face_ids: tuple[int, ...]


@dataclass(frozen=True)
class ManualJointResult:
    """An undoable geometry transaction.

    ``before`` and the caller's input are unchanged.  Install ``after`` to
    accept the operation, or restore ``before`` to undo it.
    """

    before: PreparedGeometry
    after: PreparedGeometry
    target: ManualJointTarget
    record: dict[str, object]


def _unit_vector(value: object, label: str) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float64)
    if vector.shape != (3,) or not np.isfinite(vector).all():
        raise ManualJointError(f"{label}が不正です")
    length = float(np.linalg.norm(vector))
    if length <= 1e-9:
        raise ManualJointError(f"{label}の長さがありません")
    return vector / length


def _repair_interfaces(prepared: PreparedGeometry) -> list[Mapping[str, object]]:
    try:
        assembly = dict(prepared.assembly or {})
    except (TypeError, ValueError) as exc:
        raise ManualJointError("閉立体化記録が不正です") from exc
    if assembly.get("joint_records") or assembly.get("manual_joint_records"):
        raise ManualJointError(
            "既にジョイント加工済みの形状では共有面の面番号を保証できません"
        )
    if bool(assembly.get("manual_part_assignment")):
        raise ManualJointError(
            "フリーハンド分割後は元の共有面対応が変わるため、先にジョイントを設定してください"
        )
    records = assembly.get("repair_records", [])
    if not isinstance(records, list):
        raise ManualJointError("閉立体化記録が不正です")
    interfaces: list[Mapping[str, object]] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if str(record.get("method", "")) != "partitioned_shared_caps":
            continue
        raw = record.get("interfaces", [])
        if isinstance(raw, list):
            interfaces.extend(value for value in raw if isinstance(value, Mapping))
    if not interfaces:
        if not bool(assembly.get("solidify_parts")):
            raise ManualJointError(
                "手動ジョイントに使える自動生成済みの平面共有面がありません。"
                "先にマニュアル修正上部の［パーツを閉立体化］を実行し、"
                "完了後にマニュアル修正を開き直してください"
            )
        raise ManualJointError(
            "閉立体化後も対応する自動生成済みの平面共有面がありません。"
            "この形状は現在のジョイントβ版では非対応です"
        )
    return interfaces


def _part_face_ids(level: MeshLevel) -> tuple[np.ndarray, ...]:
    try:
        layout = validate_part_layout(level)
    except PartPaletteError as exc:
        raise ManualJointError(f"パーツ構成が不正です: {exc}") from exc
    return tuple(
        np.flatnonzero(layout.face_part_ids == part_id).astype(np.int64)
        for part_id in range(layout.part_count)
    )


def _face_range(
    interface: Mapping[str, object], part_id: int, part_faces: np.ndarray
) -> tuple[int, int, tuple[int, ...]]:
    ranges = interface.get("cap_face_range_by_part")
    if not isinstance(ranges, Mapping):
        raise ManualJointError("共有面の面範囲記録がありません")
    raw_range = ranges.get(str(part_id))
    if not isinstance(raw_range, (list, tuple)) or len(raw_range) != 2:
        raise ManualJointError("対象パーツの共有面範囲が不正です")
    try:
        start, end = int(raw_range[0]), int(raw_range[1])
    except (TypeError, ValueError) as exc:
        raise ManualJointError("対象パーツの共有面範囲が整数ではありません") from exc
    if start < 0 or end <= start or end > len(part_faces):
        raise ManualJointError("対象パーツの共有面範囲が現在の形状と一致しません")
    return start, end, tuple(int(value) for value in part_faces[start:end])


def list_manual_joint_interfaces(
    prepared: PreparedGeometry,
) -> tuple[ManualJointInterface, ...]:
    """List selectable paired cap faces in current global face numbering."""

    part_faces = _part_face_ids(prepared.final)
    result: list[ManualJointInterface] = []
    for interface_index, interface in enumerate(_repair_interfaces(prepared)):
        raw_parts = interface.get("parts")
        if not isinstance(raw_parts, (list, tuple)) or len(raw_parts) != 2:
            raise ManualJointError("共有面の相手パーツ記録が不正です")
        first, second = int(raw_parts[0]), int(raw_parts[1])
        if first == second or not (0 <= first < len(part_faces)) or not (
            0 <= second < len(part_faces)
        ):
            raise ManualJointError("共有面のパーツ番号が不正です")
        _fs, _fe, first_ids = _face_range(interface, first, part_faces[first])
        _ss, _se, second_ids = _face_range(interface, second, part_faces[second])
        if len(first_ids) != len(second_ids):
            raise ManualJointError("共有面の左右で三角形数が一致しません")
        result.append(
            ManualJointInterface(
                interface_index=interface_index,
                seam_id=int(interface.get("seam_id", interface_index)),
                first_part_id=first,
                second_part_id=second,
                first_cap_face_ids=first_ids,
                second_cap_face_ids=second_ids,
            )
        )
    return tuple(result)


def assess_manual_joint_availability(
    prepared: PreparedGeometry,
) -> ManualJointAvailability:
    """Explain whether the current geometry can accept a manual joint.

    The current beta deliberately supports only a planar paired interface that
    this application generated while solidifying two matching open boundaries.
    An arbitrary exterior triangle, a curved volume-partition interface, or an
    already-watertight model does not provide the correspondence needed to cut
    the female socket safely.  This probe converts those distinctions into
    stable codes instead of exposing an opaque backend exception to the UI.
    """

    try:
        layout = validate_part_layout(prepared.final)
    except (AttributeError, PartPaletteError, TypeError, ValueError) as exc:
        return ManualJointAvailability(
            code="invalid_metadata",
            available=False,
            message_key="joint.availability.invalid_metadata",
            next_step_key="joint.workflow.reprocess",
            technical_detail=str(exc),
        )
    if layout.part_count < 2:
        return ManualJointAvailability(
            code="needs_multiple_parts",
            available=False,
            message_key="joint.availability.needs_multiple_parts",
            next_step_key=None,
        )

    try:
        assembly = dict(prepared.assembly or {})
    except (TypeError, ValueError) as exc:
        return ManualJointAvailability(
            code="invalid_metadata",
            available=False,
            message_key="joint.availability.invalid_metadata",
            next_step_key="joint.workflow.reprocess",
            technical_detail=f"assembly metadata is not a mapping: {exc}",
        )
    automatic_records = assembly.get("joint_records", [])
    manual_records = assembly.get("manual_joint_records", [])
    if automatic_records and not manual_records:
        return ManualJointAvailability(
            code="automatic_joint_conflict",
            available=False,
            message_key="joint.availability.automatic_joint_conflict",
            next_step_key="joint.workflow.disable_auto_joint",
        )
    if automatic_records or manual_records:
        return ManualJointAvailability(
            code="already_jointed",
            available=False,
            message_key="joint.availability.already_jointed",
            next_step_key="joint.workflow.undo_existing_joint",
        )
    if bool(assembly.get("manual_part_assignment")):
        return ManualJointAvailability(
            code="freehand_split_unsupported",
            available=False,
            message_key="joint.availability.freehand_split_unsupported",
            next_step_key="joint.workflow.reprocess_before_split",
        )

    if not bool(assembly.get("solidify_parts")) or not bool(
        assembly.get("all_parts_watertight")
    ):
        return ManualJointAvailability(
            code="needs_solidify",
            available=False,
            message_key="joint.availability.needs_solidify",
            next_step_key="joint.workflow.solidify",
        )

    records = assembly.get("repair_records", [])
    if not isinstance(records, list):
        return ManualJointAvailability(
            code="invalid_metadata",
            available=False,
            message_key="joint.availability.invalid_metadata",
            next_step_key="joint.workflow.reprocess",
            technical_detail="repair_records is not a list",
        )
    matching_records: list[Mapping[str, object]] = []
    for record in records:
        if not isinstance(record, Mapping):
            return ManualJointAvailability(
                code="invalid_metadata",
                available=False,
                message_key="joint.availability.invalid_metadata",
                next_step_key="joint.workflow.reprocess",
                technical_detail="repair_records contains a non-mapping entry",
            )
        if str(record.get("method", "")) == "partitioned_shared_caps":
            matching_records.append(record)

    # A closed model with no paired generated caps is valid print geometry, but
    # it is intentionally outside the current beta joint contract.  This is a
    # capability boundary, not a request to repair the model again.
    if not matching_records:
        return ManualJointAvailability(
            code="beta_no_planar_shared_interface",
            available=False,
            message_key="joint.availability.beta_no_planar_shared_interface",
            next_step_key=None,
        )
    for record in matching_records:
        interfaces = record.get("interfaces", [])
        if not isinstance(interfaces, list):
            return ManualJointAvailability(
                code="invalid_metadata",
                available=False,
                message_key="joint.availability.invalid_metadata",
                next_step_key="joint.workflow.reprocess",
                technical_detail="partitioned_shared_caps interfaces is not a list",
            )
        if any(not isinstance(interface, Mapping) for interface in interfaces):
            return ManualJointAvailability(
                code="invalid_metadata",
                available=False,
                message_key="joint.availability.invalid_metadata",
                next_step_key="joint.workflow.reprocess",
                technical_detail="interfaces contains a non-mapping entry",
            )
    if not any(record.get("interfaces") for record in matching_records):
        return ManualJointAvailability(
            code="beta_no_planar_shared_interface",
            available=False,
            message_key="joint.availability.beta_no_planar_shared_interface",
            next_step_key=None,
        )

    try:
        interfaces = list_manual_joint_interfaces(prepared)
    except ManualJointError as exc:
        return ManualJointAvailability(
            code="invalid_metadata",
            available=False,
            message_key="joint.availability.invalid_metadata",
            next_step_key="joint.workflow.reprocess",
            technical_detail=str(exc),
        )
    if not interfaces:
        return ManualJointAvailability(
            code="beta_no_planar_shared_interface",
            available=False,
            message_key="joint.availability.beta_no_planar_shared_interface",
            next_step_key=None,
        )
    eligible_parts = sorted(
        {
            part_id
            for interface in interfaces
            for part_id in (interface.first_part_id, interface.second_part_id)
        }
    )
    return ManualJointAvailability(
        code="ready",
        available=True,
        message_key="joint.availability.ready",
        next_step_key="joint.workflow.select_male",
        interface_count=len(interfaces),
        eligible_part_ids=tuple(eligible_parts),
    )


def _triangle_contains_point(
    triangle: np.ndarray, point: np.ndarray, *, tolerance_unit: float
) -> bool:
    try:
        barycentric = trimesh.triangles.points_to_barycentric(
            np.asarray(triangle, dtype=np.float64)[None, :, :],
            np.asarray(point, dtype=np.float64)[None, :],
        )[0]
    except Exception:
        return False
    return bool(
        np.isfinite(barycentric).all()
        and float(barycentric.min()) >= -tolerance_unit
        and float(barycentric.max()) <= 1.0 + tolerance_unit
    )


def _interface_polygon(
    level: MeshLevel,
    cap_face_ids: Sequence[int],
    origin: np.ndarray,
    axis_u: np.ndarray,
    axis_v: np.ndarray,
):
    polygons = []
    for face_id in cap_face_ids:
        triangle = np.asarray(level.vertices_unit)[
            np.asarray(level.faces)[int(face_id)]
        ]
        coordinates = np.column_stack(
            ((triangle - origin) @ axis_u, (triangle - origin) @ axis_v)
        )
        polygon = Polygon(coordinates)
        if polygon.is_valid and polygon.area > 1e-14:
            polygons.append(polygon)
    if not polygons:
        raise ManualJointError("共有面を平面領域として復元できません")
    result = unary_union(polygons)
    if result.is_empty or not result.is_valid:
        raise ManualJointError("共有面の平面領域が不正です")
    return result


def resolve_manual_joint_target(
    prepared: PreparedGeometry,
    *,
    male_face_id: int,
    center_unit: Sequence[float],
    height_mm: float,
    settings: ManualJointSettings | None = None,
) -> ManualJointTarget:
    """Resolve a clicked generated cap to its opposing part and face.

    The face ID is the current final-level global face ID.  ``center_unit`` is
    the renderer/model coordinate before multiplication by ``height_mm``.
    """

    settings = (settings or ManualJointSettings()).validated()
    level = prepared.final
    height_mm = float(height_mm)
    if not np.isfinite(height_mm) or height_mm <= 0.0:
        raise ManualJointError("造形高さが不正です")
    center = np.asarray(center_unit, dtype=np.float64)
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ManualJointError("雄ジョイント中心が不正です")
    face_id = int(male_face_id)
    if face_id < 0 or face_id >= len(level.faces):
        raise ManualJointError("選択面番号が範囲外です")

    part_faces = _part_face_ids(level)
    face_part_ids = np.asarray(level.face_part_ids, dtype=np.int64)
    male_part = int(face_part_ids[face_id])
    interfaces = _repair_interfaces(prepared)
    matches: list[tuple[int, Mapping[str, object], int, int, tuple[int, ...], tuple[int, ...], int]] = []
    for interface_index, interface in enumerate(interfaces):
        raw_parts = interface.get("parts")
        if not isinstance(raw_parts, (list, tuple)) or len(raw_parts) != 2:
            continue
        first, second = int(raw_parts[0]), int(raw_parts[1])
        if male_part not in (first, second):
            continue
        female_part = second if male_part == first else first
        male_start, _male_end, male_cap = _face_range(
            interface, male_part, part_faces[male_part]
        )
        _female_start, _female_end, female_cap = _face_range(
            interface, female_part, part_faces[female_part]
        )
        try:
            relative = male_cap.index(face_id)
        except ValueError:
            continue
        matches.append(
            (
                interface_index,
                interface,
                male_part,
                female_part,
                male_cap,
                female_cap,
                relative,
            )
        )
    if len(matches) != 1:
        if not matches:
            raise ManualJointError(
                "選択面は自動生成された平面の対向接合面ではありません。"
                "雄側を編集パーツにし、相手を透明または非表示にして、"
                "閉立体化で追加された平面をクリックしてください"
            )
        raise ManualJointError("選択面が複数の共有面記録に重複しています")
    (
        interface_index,
        interface,
        male_part,
        female_part,
        male_cap,
        female_cap,
        relative,
    ) = matches[0]

    normals = interface.get("outward_normal_by_part")
    if not isinstance(normals, Mapping):
        raise ManualJointError("共有面の外向き法線記録がありません")
    male_outward = _unit_vector(normals.get(str(male_part)), "雄側法線")
    female_outward = _unit_vector(normals.get(str(female_part)), "雌側法線")
    if float(np.dot(male_outward, female_outward)) > -0.99:
        raise ManualJointError("対向接合面の法線が反対向きではありません")
    axis_u = _unit_vector(interface.get("axis_u"), "共有面U軸")
    axis_u -= male_outward * float(np.dot(axis_u, male_outward))
    axis_u = _unit_vector(axis_u, "共有面U軸")
    axis_v = np.cross(male_outward, axis_u)
    axis_v = _unit_vector(axis_v, "共有面V軸")

    male_triangle = np.asarray(level.vertices_unit)[
        np.asarray(level.faces)[face_id]
    ]
    plane_origin = male_triangle.mean(axis=0)
    plane_distance = float(np.dot(center - plane_origin, male_outward))
    if abs(plane_distance) * height_mm > 0.10:
        raise ManualJointError("指定中心が選択した接合面上にありません")
    projected = center - male_outward * plane_distance
    if not _triangle_contains_point(
        male_triangle,
        projected,
        tolerance_unit=0.02 / max(height_mm, 1e-9),
    ):
        raise ManualJointError("指定中心が選択した三角形の外側です")

    polygon = _interface_polygon(
        level, male_cap, plane_origin, axis_u, axis_v
    )
    point_uv = Point(
        float(np.dot(projected - plane_origin, axis_u)),
        float(np.dot(projected - plane_origin, axis_v)),
    )
    if not polygon.covers(point_uv):
        raise ManualJointError("指定中心が共有接合面の外側です")
    boundary_margin_mm = float(point_uv.distance(polygon.boundary)) * height_mm
    required_margin = (
        0.5
        * float(
            np.hypot(
                settings.width_mm + 2.0 * settings.clearance_mm,
                settings.height_mm + 2.0 * settings.clearance_mm,
            )
        )
        + settings.boundary_safety_mm
    )
    if boundary_margin_mm < required_margin:
        raise ManualJointError(
            "指定位置は共有面の端に近すぎます: "
            f"必要 {required_margin:.2f} mm / 実際 {boundary_margin_mm:.2f} mm"
        )

    expected_female_face = int(female_cap[relative])
    female_triangle = np.asarray(level.vertices_unit)[
        np.asarray(level.faces)[expected_female_face]
    ]
    distances = cKDTree(female_triangle).query(male_triangle, workers=-1)[0]
    if float(distances.max(initial=0.0)) * height_mm > 0.05:
        candidates = np.asarray(female_cap, dtype=np.int64)
        centroids = np.asarray(level.vertices_unit)[
            np.asarray(level.faces)[candidates]
        ].mean(axis=1)
        nearest = int(np.argmin(np.linalg.norm(centroids - projected, axis=1)))
        expected_female_face = int(candidates[nearest])
        female_triangle = np.asarray(level.vertices_unit)[
            np.asarray(level.faces)[expected_female_face]
        ]
        distances = cKDTree(female_triangle).query(male_triangle, workers=-1)[0]
        if float(distances.max(initial=0.0)) * height_mm > 0.05:
            raise ManualJointError("選択面に一致する相手側三角形を特定できません")

    return ManualJointTarget(
        interface_index=int(interface_index),
        seam_id=int(interface.get("seam_id", interface_index)),
        male_part_id=int(male_part),
        female_part_id=int(female_part),
        male_face_id=face_id,
        female_face_id=expected_female_face,
        center_unit=tuple(float(value) for value in projected),
        axis_u=tuple(float(value) for value in axis_u),
        axis_v=tuple(float(value) for value in axis_v),
        male_outward=tuple(float(value) for value in male_outward),
        female_outward=tuple(float(value) for value in female_outward),
        boundary_margin_mm=float(boundary_margin_mm),
        male_cap_face_ids=tuple(male_cap),
        female_cap_face_ids=tuple(female_cap),
    )


def _extract_part_meshes(
    level: MeshLevel,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    parts: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for selected in _part_face_ids(level):
        if not len(selected):
            raise ManualJointError("面のないパーツがあります")
        faces_global = np.asarray(level.faces, dtype=np.int64)[selected]
        used = np.unique(faces_global.reshape(-1))
        faces_local = np.searchsorted(used, faces_global).astype(np.int32)
        parts.append(
            (
                np.asarray(level.vertices_unit, dtype=np.float64)[used].copy(),
                faces_local,
                np.asarray(level.vertex_colors, dtype=np.float64)[used].copy(),
            )
        )
    return parts


def _ray_exit_distance(
    mesh: trimesh.Trimesh, origin: np.ndarray, direction: np.ndarray
) -> float:
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    edge1 = triangles[:, 1] - triangles[:, 0]
    edge2 = triangles[:, 2] - triangles[:, 0]
    direction = _unit_vector(direction, "肉厚確認方向")
    pvec = np.cross(np.broadcast_to(direction, edge2.shape), edge2)
    determinant = np.einsum("ij,ij->i", edge1, pvec)
    valid = np.abs(determinant) > 1e-12
    inverse = np.zeros_like(determinant)
    inverse[valid] = 1.0 / determinant[valid]
    tvec = np.asarray(origin, dtype=np.float64) - triangles[:, 0]
    u = np.einsum("ij,ij->i", tvec, pvec) * inverse
    qvec = np.cross(tvec, edge1)
    v = qvec @ direction * inverse
    distance = np.einsum("ij,ij->i", edge2, qvec) * inverse
    hits = valid & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1.0 + 1e-9)
    hits &= distance > 1e-5
    values = distance[hits]
    return float(values.min(initial=np.inf))


_FOOTPRINT_SAMPLE_FRACTIONS = (
    (0.0, 0.0),
    (-0.5, -0.5),
    (-0.5, 0.5),
    (0.5, -0.5),
    (0.5, 0.5),
    (-0.5, 0.0),
    (0.5, 0.0),
    (0.0, -0.5),
    (0.0, 0.5),
)


def _polygon_components(geometry: object) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry] if not geometry.is_empty else []
    components: list[Polygon] = []
    for child in getattr(geometry, "geoms", ()):
        components.extend(_polygon_components(child))
    return components


def _cap_footprint_diagnostics(
    level: MeshLevel,
    cap_face_ids: Sequence[int],
    *,
    center_mm: np.ndarray,
    axis_u: np.ndarray,
    axis_v: np.ndarray,
    outward: np.ndarray,
    width_mm: float,
    height_mm: float,
    model_height_mm: float,
) -> dict[str, object]:
    """Measure the real cap under a requested rectangular footprint.

    The repair metadata supplies a nominal frame, but triangulated generated
    caps can have small local relief.  Project every intersecting cap triangle
    into the requested rectangle and retain its linear height equation.  This
    lets the joint cross the *whole* footprint instead of touching one high
    triangle or edge.
    """

    half_width = 0.5 * float(width_mm)
    half_height = 0.5 * float(height_mm)
    footprint = Polygon(
        [
            (-half_width, -half_height),
            (half_width, -half_height),
            (half_width, half_height),
            (-half_width, half_height),
        ]
    )
    footprint_area = float(footprint.area)
    patches: list[tuple[Polygon, np.ndarray]] = []
    covered_polygons: list[Polygon] = []
    weighted_offset = 0.0
    weighted_area = 0.0
    minimum_offset = np.inf
    maximum_offset = -np.inf
    vertices = np.asarray(level.vertices_unit, dtype=np.float64)
    faces = np.asarray(level.faces, dtype=np.int64)
    for face_id in cap_face_ids:
        triangle_mm = vertices[faces[int(face_id)]] * model_height_mm
        relative = triangle_mm - center_mm
        uv = np.column_stack((relative @ axis_u, relative @ axis_v))
        if (
            float(np.max(uv[:, 0])) < -half_width
            or float(np.min(uv[:, 0])) > half_width
            or float(np.max(uv[:, 1])) < -half_height
            or float(np.min(uv[:, 1])) > half_height
        ):
            continue
        triangle_polygon = Polygon(uv)
        if not triangle_polygon.is_valid or triangle_polygon.area <= 1e-10:
            continue
        clipped = triangle_polygon.intersection(footprint)
        components = [
            component
            for component in _polygon_components(clipped)
            if component.is_valid and component.area > 1e-10
        ]
        if not components:
            continue
        offsets = relative @ outward
        matrix = np.column_stack((uv, np.ones(3, dtype=np.float64)))
        try:
            coefficients = np.linalg.solve(matrix, offsets)
        except np.linalg.LinAlgError:
            continue
        for component in components:
            patches.append((component, coefficients))
            covered_polygons.append(component)
            coordinates = [np.asarray(component.exterior.coords, dtype=np.float64)]
            coordinates.extend(
                np.asarray(ring.coords, dtype=np.float64)
                for ring in component.interiors
            )
            for ring in coordinates:
                values = (
                    ring[:, 0] * coefficients[0]
                    + ring[:, 1] * coefficients[1]
                    + coefficients[2]
                )
                minimum_offset = min(minimum_offset, float(values.min()))
                maximum_offset = max(maximum_offset, float(values.max()))
            centroid = component.centroid
            centroid_offset = (
                float(centroid.x) * coefficients[0]
                + float(centroid.y) * coefficients[1]
                + coefficients[2]
            )
            area = float(component.area)
            weighted_offset += area * float(centroid_offset)
            weighted_area += area

    if not covered_polygons or not np.isfinite(minimum_offset):
        raise ManualJointError("指定範囲の下に共有面を確認できません")
    covered = unary_union(covered_polygons)
    covered_area = float(covered.intersection(footprint).area)
    coverage_ratio = covered_area / max(footprint_area, 1e-12)
    if coverage_ratio < 0.995:
        raise ManualJointError(
            "矩形ジョイントの接触面全体が共有面に収まりません: "
            f"被覆率 {coverage_ratio * 100.0:.1f}%"
        )

    sample_offsets: list[float] = []
    sample_tolerance = max(width_mm, height_mm, 1.0) * 1e-8
    for fraction_u, fraction_v in _FOOTPRINT_SAMPLE_FRACTIONS:
        u = fraction_u * width_mm
        v = fraction_v * height_mm
        point = Point(float(u), float(v))
        candidates: list[float] = []
        for polygon, coefficients in patches:
            if polygon.covers(point) or polygon.distance(point) <= sample_tolerance:
                candidates.append(
                    float(u * coefficients[0] + v * coefficients[1] + coefficients[2])
                )
        if not candidates:
            raise ManualJointError("矩形ジョイントの接触面に未被覆点があります")
        # Adjacent triangles share an identical edge in a valid cap.  Averaging
        # their numerical values avoids face-order dependent replay output.
        sample_offsets.append(float(np.mean(candidates)))

    return {
        "footprint_area_mm2": footprint_area,
        "footprint_covered_area_mm2": covered_area,
        "footprint_coverage_ratio": float(coverage_ratio),
        "cap_offset_min_mm": float(minimum_offset),
        "cap_offset_max_mm": float(maximum_offset),
        "cap_offset_mean_mm": float(weighted_offset / max(weighted_area, 1e-12)),
        "cap_relief_mm": float(maximum_offset - minimum_offset),
        "sample_offsets_mm": tuple(sample_offsets),
    }


def _joint_overlap_diagnostics(
    source_mesh: trimesh.Trimesh,
    tool_mesh: trimesh.Trimesh,
    union_mesh: trimesh.Trimesh,
    *,
    footprint_area_mm2: float,
    embed_mm: float,
    base_embed_mm: float,
) -> dict[str, object]:
    """Validate male contact using volume balance, without another boolean."""

    source_volume = abs(float(source_mesh.volume))
    tool_volume = abs(float(tool_mesh.volume))
    union_volume = abs(float(union_mesh.volume))
    values = (source_volume, tool_volume, union_volume, footprint_area_mm2, embed_mm)
    if not np.isfinite(values).all() or footprint_area_mm2 <= 0.0 or embed_mm <= 0.0:
        raise ManualJointError("ジョイント接触体積を検証できません")
    numerical_tolerance = max(1e-5, (source_volume + tool_volume) * 1e-9)
    overlap_volume = source_volume + tool_volume - union_volume
    if overlap_volume < -numerical_tolerance:
        raise ManualJointError("ジョイント接触体積の計算結果が不正です")
    overlap_volume = max(0.0, float(overlap_volume))
    effective_contact_depth = overlap_volume / footprint_area_mm2
    minimum_contact_depth = min(0.50, max(0.25, base_embed_mm * 0.50))
    minimum_overlap_volume = footprint_area_mm2 * minimum_contact_depth
    overlap_ratio = overlap_volume / max(footprint_area_mm2 * embed_mm, 1e-12)
    contact_safety_ratio = overlap_volume / max(minimum_overlap_volume, 1e-12)
    if overlap_volume + numerical_tolerance < minimum_overlap_volume:
        raise ManualJointError(
            "雄ジョイントの本体への接触が不足しています: "
            f"有効埋込み {effective_contact_depth:.3f} mm / "
            f"必要 {minimum_contact_depth:.3f} mm"
        )
    return {
        "source_volume_mm3": source_volume,
        "tool_volume_mm3": tool_volume,
        "union_volume_mm3": union_volume,
        "overlap_volume_mm3": overlap_volume,
        "minimum_overlap_volume_mm3": float(minimum_overlap_volume),
        "effective_contact_depth_mm": float(effective_contact_depth),
        "minimum_contact_depth_mm": float(minimum_contact_depth),
        "overlap_ratio": float(overlap_ratio),
        "contact_safety_ratio": float(contact_safety_ratio),
        "contact_validation": "passed_volume_balance",
    }


def _minimum_wall_depth(
    mesh: trimesh.Trimesh,
    center_mm: np.ndarray,
    axis_u: np.ndarray,
    axis_v: np.ndarray,
    inward: np.ndarray,
    width_mm: float,
    height_mm: float,
    surface_offsets_mm: Sequence[float] | None = None,
) -> float:
    values: list[float] = []
    offsets = (
        tuple(float(value) for value in surface_offsets_mm)
        if surface_offsets_mm is not None
        else (0.0,) * len(_FOOTPRINT_SAMPLE_FRACTIONS)
    )
    if len(offsets) != len(_FOOTPRINT_SAMPLE_FRACTIONS) or not np.isfinite(offsets).all():
        raise ManualJointError("共有面の局所高さを検証できません")
    for (fraction_u, fraction_v), surface_offset in zip(
        _FOOTPRINT_SAMPLE_FRACTIONS, offsets, strict=True
    ):
        point = (
            center_mm
            + axis_u * (fraction_u * width_mm)
            + axis_v * (fraction_v * height_mm)
            - inward * surface_offset
            + inward * 1e-4
        )
        values.append(_ray_exit_distance(mesh, point, inward))
    return float(min(values, default=np.inf))


def _validate_result_mesh(
    mesh: trimesh.Trimesh,
    source: tuple[np.ndarray, np.ndarray, np.ndarray],
    *,
    height_mm: float,
    part_id: int,
) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray], dict[str, object]]:
    mesh.fix_normals(multibody=True)
    if not mesh.is_watertight or not mesh.is_volume:
        raise ManualJointError(f"パーツ{part_id + 1}が閉じた正体積になりませんでした")
    if len(mesh.split(only_watertight=False)) != 1:
        raise ManualJointError(f"パーツ{part_id + 1}が複数立体へ分離しました")
    vertices_unit = np.asarray(mesh.vertices, dtype=np.float64) / height_mm
    faces = np.asarray(mesh.faces, dtype=np.int32)
    try:
        checked_faces, validation = _assembly._strict_mesh_record(
            vertices_unit,
            faces,
            part_id=part_id,
        )
    except _assembly.AssemblyError as exc:
        raise ManualJointError(str(exc)) from exc
    topology = dict(validation["topology"])
    if (
        not bool(topology.get("watertight"))
        or int(topology.get("boundary_edges", -1)) != 0
        or int(topology.get("nonmanifold_edges", -1)) != 0
        or not bool(validation.get("positive_volume"))
    ):
        raise ManualJointError(f"パーツ{part_id + 1}の厳格形状検査に失敗しました")
    try:
        colors = _assembly._transfer_vertex_colors(
            source[0],
            source[2],
            vertices_unit,
            source[1],
        )
    except _assembly.AssemblyError as exc:
        raise ManualJointError(str(exc)) from exc
    return (
        vertices_unit,
        checked_faces,
        colors,
    ), {
        **validation,
        "topology": topology,
    }


def _combine_parts(
    parts: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
    names: tuple[str, ...],
    keys: tuple[str, ...],
) -> MeshLevel:
    vertices: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    colors: list[np.ndarray] = []
    part_ids: list[np.ndarray] = []
    offset = 0
    for part_id, (part_vertices, part_faces, part_colors) in enumerate(parts):
        vertices.append(np.asarray(part_vertices, dtype=np.float64))
        faces.append(np.asarray(part_faces, dtype=np.int32) + offset)
        colors.append(np.asarray(part_colors, dtype=np.float64))
        part_ids.append(np.full(len(part_faces), part_id, dtype=np.int16))
        offset += len(part_vertices)
    combined_vertices = np.vstack(vertices)
    combined_faces = np.vstack(faces).astype(np.int32)
    combined_colors = np.vstack(colors)
    return MeshLevel(
        vertices_unit=combined_vertices,
        faces=combined_faces,
        vertex_colors=combined_colors,
        areas_unit=triangle_areas(combined_vertices, combined_faces),
        neighbors=face_neighbors_partial(combined_faces, len(combined_vertices)),
        face_part_ids=np.concatenate(part_ids),
        part_names=names,
        part_keys=keys,
    )


def apply_manual_joint(
    prepared: PreparedGeometry,
    target: ManualJointTarget,
    *,
    height_mm: float,
    settings: ManualJointSettings | None = None,
) -> ManualJointResult:
    """Apply one exact rectangular male/female joint as a non-mutating transaction."""

    settings = (settings or ManualJointSettings()).validated()
    height_mm = float(height_mm)
    if not np.isfinite(height_mm) or height_mm <= 0.0:
        raise ManualJointError("造形高さは0より大きい有限値で指定してください")
    interfaces = list_manual_joint_interfaces(prepared)
    if not 0 <= target.interface_index < len(interfaces):
        raise ManualJointError("共有面番号が現在の形状と一致しません")
    current = resolve_manual_joint_target(
        prepared,
        male_face_id=target.male_face_id,
        center_unit=target.center_unit,
        height_mm=height_mm,
        settings=settings,
    )
    if current != target:
        raise ManualJointError("選択後に共有面または対象パーツが変わりました")

    parts = _extract_part_meshes(prepared.final)
    male_source = parts[target.male_part_id]
    female_source = parts[target.female_part_id]
    try:
        male_volume = _assembly._as_volume_mesh(*male_source[:2], height_mm)
        female_volume = _assembly._as_volume_mesh(*female_source[:2], height_mm)
    except _assembly.AssemblyError as exc:
        raise ManualJointError(str(exc)) from exc

    center_mm = np.asarray(target.center_unit, dtype=np.float64) * height_mm
    axis_u = _unit_vector(target.axis_u, "ジョイントU軸")
    axis_v = _unit_vector(target.axis_v, "ジョイントV軸")
    male_outward = _unit_vector(target.male_outward, "雄側外向き")
    female_outward = _unit_vector(target.female_outward, "雌側外向き")
    male_inside = -male_outward
    female_inside = -female_outward
    if float(np.dot(male_outward, female_inside)) < 0.99:
        raise ManualJointError("雄の突き出し方向と雌の掘り込み方向が一致しません")

    cap_diagnostics = _cap_footprint_diagnostics(
        prepared.final,
        target.male_cap_face_ids,
        center_mm=center_mm,
        axis_u=axis_u,
        axis_v=axis_v,
        outward=male_outward,
        width_mm=settings.width_mm,
        height_mm=settings.height_mm,
        model_height_mm=height_mm,
    )
    socket_cap_diagnostics = _cap_footprint_diagnostics(
        prepared.final,
        target.male_cap_face_ids,
        center_mm=center_mm,
        axis_u=axis_u,
        axis_v=axis_v,
        outward=male_outward,
        width_mm=settings.width_mm + 2.0 * settings.clearance_mm,
        height_mm=settings.height_mm + 2.0 * settings.clearance_mm,
        model_height_mm=height_mm,
    )
    minimum_cap_offset = float(cap_diagnostics["cap_offset_min_mm"])
    maximum_cap_offset = float(cap_diagnostics["cap_offset_max_mm"])
    cap_relief = float(cap_diagnostics["cap_relief_mm"])
    base_embed = min(1.0, settings.depth_mm * 0.25)
    relief_guard = 0.05 if cap_relief > 0.02 else 0.0
    embed_compensation = max(0.0, -minimum_cap_offset)
    embed = base_embed + embed_compensation + relief_guard
    maximum_male_penetration = embed + max(0.0, maximum_cap_offset)
    socket_depth = settings.depth_mm + max(0.35, settings.clearance_mm)
    socket_minimum_cap_offset = float(
        socket_cap_diagnostics["cap_offset_min_mm"]
    )
    socket_maximum_cap_offset = float(
        socket_cap_diagnostics["cap_offset_max_mm"]
    )
    socket_cap_relief = float(socket_cap_diagnostics["cap_relief_mm"])
    socket_required_depth = socket_depth + socket_cap_relief
    male_surface_offsets = tuple(
        float(value) for value in cap_diagnostics["sample_offsets_mm"]
    )
    female_surface_offsets = tuple(
        -float(value) for value in socket_cap_diagnostics["sample_offsets_mm"]
    )
    male_wall = _minimum_wall_depth(
        male_volume,
        center_mm,
        axis_u,
        axis_v,
        male_inside,
        settings.width_mm,
        settings.height_mm,
        male_surface_offsets,
    )
    female_wall = _minimum_wall_depth(
        female_volume,
        center_mm,
        axis_u,
        axis_v,
        female_inside,
        settings.width_mm + 2.0 * settings.clearance_mm,
        settings.height_mm + 2.0 * settings.clearance_mm,
        female_surface_offsets,
    )
    if male_wall < maximum_male_penetration + settings.wall_safety_mm:
        raise ManualJointError(
            f"雄側の肉厚が不足しています: {male_wall:.2f} mm"
        )
    if female_wall < socket_required_depth + settings.wall_safety_mm:
        raise ManualJointError(
            f"雌側の肉厚が不足しています: {female_wall:.2f} mm"
        )

    male_start = -embed
    male_end = settings.depth_mm + max(0.0, maximum_cap_offset)
    male_extent = male_end - male_start
    male_center = center_mm + male_outward * ((male_start + male_end) * 0.5)
    male_tool = _assembly._keyed_box(
        male_center,
        axis_u,
        axis_v,
        male_outward,
        settings.width_mm,
        settings.height_mm,
        male_extent,
    )
    socket_start = min(0.0, socket_minimum_cap_offset) - 1.0
    socket_end = socket_depth + max(0.0, socket_maximum_cap_offset)
    socket_extent = socket_end - socket_start
    socket_center = center_mm + female_inside * ((socket_start + socket_end) * 0.5)
    socket_tool = _assembly._keyed_box(
        socket_center,
        axis_u,
        axis_v,
        female_inside,
        settings.width_mm + 2.0 * settings.clearance_mm,
        settings.height_mm + 2.0 * settings.clearance_mm,
        socket_extent,
    )
    try:
        male_boolean = trimesh.boolean.union(
            [male_volume, male_tool], engine="manifold"
        )
        female_boolean = trimesh.boolean.difference(
            [female_volume, socket_tool], engine="manifold"
        )
    except Exception as exc:  # pragma: no cover - backend messages vary
        raise ManualJointError(f"手動ジョイントの立体演算に失敗しました: {exc}") from exc
    if not isinstance(male_boolean, trimesh.Trimesh) or not isinstance(
        female_boolean, trimesh.Trimesh
    ):
        raise ManualJointError("手動ジョイントの立体演算結果がメッシュではありません")

    contact_diagnostics = _joint_overlap_diagnostics(
        male_volume,
        male_tool,
        male_boolean,
        footprint_area_mm2=float(cap_diagnostics["footprint_area_mm2"]),
        embed_mm=float(embed),
        base_embed_mm=float(base_embed),
    )

    male_result, male_validation = _validate_result_mesh(
        male_boolean,
        male_source,
        height_mm=height_mm,
        part_id=target.male_part_id,
    )
    female_result, female_validation = _validate_result_mesh(
        female_boolean,
        female_source,
        height_mm=height_mm,
        part_id=target.female_part_id,
    )
    parts[target.male_part_id] = male_result
    parts[target.female_part_id] = female_result
    names = tuple(prepared.final.part_names)
    keys = tuple(prepared.final.part_keys)
    final_level = _combine_parts(parts, names, keys)
    topology = _assembly._edge_topology(final_level.faces, len(final_level.vertices_unit))
    if (
        not bool(topology["watertight"])
        or int(topology["boundary_edges"]) != 0
        or int(topology["nonmanifold_edges"]) != 0
    ):
        raise ManualJointError("統合後のパーツ構造が閉立体ではありません")

    record: dict[str, object] = {
        "type": "manual_keyed_joint",
        "shape": "keyed_rectangle",
        "positioning": "user_selected_surface_point",
        "interface_index": int(target.interface_index),
        "seam_id": int(target.seam_id),
        "parts": [int(target.male_part_id), int(target.female_part_id)],
        "male_part": int(target.male_part_id),
        "female_part": int(target.female_part_id),
        "male_part_name": names[target.male_part_id],
        "female_part_name": names[target.female_part_id],
        "male_part_key": keys[target.male_part_id],
        "female_part_key": keys[target.female_part_id],
        "male_face_id_before": int(target.male_face_id),
        "female_face_id_before": int(target.female_face_id),
        "center_unit": np.asarray(target.center_unit, dtype=np.float64).tolist(),
        "center_mm": (np.asarray(target.center_unit) * height_mm).round(6).tolist(),
        "model_height_mm": float(height_mm),
        "width_mm": float(settings.width_mm),
        "height_mm": float(settings.height_mm),
        "depth_mm": float(settings.depth_mm),
        "clearance_mm": float(settings.clearance_mm),
        "boundary_safety_mm": float(settings.boundary_safety_mm),
        "wall_safety_mm": float(settings.wall_safety_mm),
        "boundary_margin_mm": float(target.boundary_margin_mm),
        "embed_mm": float(embed),
        "adaptive_embed_mm": float(embed),
        "base_embed_mm": float(base_embed),
        "embed_compensation_mm": float(embed_compensation),
        "embed_relief_guard_mm": float(relief_guard),
        "male_tool_start_mm": float(male_start),
        "male_tool_end_mm": float(male_end),
        "socket_tool_start_mm": float(socket_start),
        "socket_tool_end_mm": float(socket_end),
        "male_wall_mm": float(male_wall),
        "female_wall_mm": float(female_wall),
        **{
            key: value
            for key, value in cap_diagnostics.items()
            if key != "sample_offsets_mm"
        },
        "socket_cap_offset_min_mm": socket_minimum_cap_offset,
        "socket_cap_offset_max_mm": socket_maximum_cap_offset,
        "socket_cap_relief_mm": socket_cap_relief,
        "socket_footprint_coverage_ratio": float(
            socket_cap_diagnostics["footprint_coverage_ratio"]
        ),
        **contact_diagnostics,
        "contact_diagnostics": dict(contact_diagnostics),
        "male_validation": male_validation,
        "female_validation": female_validation,
        "preserved_part_names": True,
        "preserved_part_placement": True,
        "source_unchanged": True,
        "base_mesh_fingerprint": mesh_fingerprint(prepared.final),
    }

    after = deepcopy(prepared)
    after.final = final_level
    after.preview = MeshLevel(
        vertices_unit=final_level.vertices_unit.copy(),
        faces=final_level.faces.copy(),
        vertex_colors=final_level.vertex_colors.copy(),
        areas_unit=final_level.areas_unit.copy(),
        neighbors=(
            None
            if final_level.neighbors is None
            else final_level.neighbors.copy()
        ),
        face_part_ids=final_level.face_part_ids.copy(),
        part_names=names,
        part_keys=keys,
    )
    after.part_names = names
    after.part_keys = keys
    after.topology = dict(topology)
    after.simplified_area_unit = float(final_level.areas_unit.sum())
    after.simplified_volume_unit = float(
        sum(signed_volume(*part[:2]) for part in parts)
    )
    after.warnings = list(after.warnings) + [
        "手動指定した四角ジョイント1組を安全検証後に生成しました"
    ]
    updated_stats: list[dict[str, object]] = []
    for part_id, part in enumerate(parts):
        value = (
            dict(after.part_stats[part_id])
            if part_id < len(after.part_stats)
            else {}
        )
        value.update(
            {
                "id": int(part_id),
                "key": keys[part_id],
                "name": names[part_id],
                "final_vertices": int(len(part[0])),
                "final_faces": int(len(part[1])),
                "preview_vertices": int(len(part[0])),
                "preview_faces": int(len(part[1])),
                "manual_joint_modified": bool(
                    part_id in (target.male_part_id, target.female_part_id)
                ),
            }
        )
        updated_stats.append(value)
    after.part_stats = updated_stats
    metadata = dict(after.assembly or {})
    manual_records = list(metadata.get("manual_joint_records", []))
    manual_records.append(record)
    metadata["manual_joint_records"] = manual_records
    joint_records = list(metadata.get("joint_records", []))
    joint_records.append(record)
    metadata["joint_records"] = joint_records
    metadata["manual_joint_topology_changed"] = True
    metadata["all_parts_watertight"] = True
    after.assembly = metadata
    return ManualJointResult(
        before=prepared,
        after=after,
        target=target,
        record=record,
    )


def create_manual_joint(
    prepared: PreparedGeometry,
    *,
    male_face_id: int,
    center_unit: Sequence[float],
    height_mm: float,
    settings: ManualJointSettings | None = None,
) -> ManualJointResult:
    """Resolve a click and create its matching male/female joint atomically."""

    settings = (settings or ManualJointSettings()).validated()
    target = resolve_manual_joint_target(
        prepared,
        male_face_id=male_face_id,
        center_unit=center_unit,
        height_mm=height_mm,
        settings=settings,
    )
    return apply_manual_joint(
        prepared,
        target,
        height_mm=height_mm,
        settings=settings,
    )


def replay_manual_joint(
    prepared: PreparedGeometry,
    record: Mapping[str, object],
    *,
    height_mm: float,
) -> ManualJointResult:
    """Safely replay one saved joint on the exact unmodified base mesh."""

    if not isinstance(record, Mapping):
        raise ManualJointError("保存ジョイント記録が辞書ではありません")
    if str(record.get("type", "")) != "manual_keyed_joint" or str(
        record.get("shape", "")
    ) != "keyed_rectangle":
        raise ManualJointError("保存ジョイント記録の種類が未対応です")
    expected_fingerprint = str(record.get("base_mesh_fingerprint", ""))
    if (
        not expected_fingerprint
        or mesh_fingerprint(prepared.final) != expected_fingerprint
    ):
        raise ManualJointError(
            "保存ジョイントは別の形状に属しているため再適用できません"
        )
    try:
        recorded_height = float(record["model_height_mm"])
        center = np.asarray(record["center_unit"], dtype=np.float64)
        male_face_id = int(record["male_face_id_before"])
        settings = ManualJointSettings(
            width_mm=float(record["width_mm"]),
            height_mm=float(record["height_mm"]),
            depth_mm=float(record["depth_mm"]),
            clearance_mm=float(record["clearance_mm"]),
            boundary_safety_mm=float(
                record.get("boundary_safety_mm", 0.25)
            ),
            wall_safety_mm=float(record.get("wall_safety_mm", 0.50)),
        ).validated()
    except (KeyError, TypeError, ValueError) as exc:
        raise ManualJointError(
            f"保存ジョイント記録の寸法または位置が不正です: {exc}"
        ) from exc
    if (
        not np.isfinite(recorded_height)
        or not np.isfinite(height_mm)
        or not np.isclose(recorded_height, float(height_mm), rtol=0.0, atol=1e-6)
    ):
        raise ManualJointError(
            "保存時と現在の造形高さが異なるためジョイントを再適用できません"
        )
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ManualJointError("保存ジョイント記録の中心座標が不正です")
    result = create_manual_joint(
        prepared,
        male_face_id=male_face_id,
        center_unit=center,
        height_mm=height_mm,
        settings=settings,
    )
    for key, actual in (
        ("male_part", result.target.male_part_id),
        ("female_part", result.target.female_part_id),
        ("female_face_id_before", result.target.female_face_id),
    ):
        try:
            expected = int(record[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ManualJointError(f"保存ジョイント記録の{key}が不正です") from exc
        if expected != int(actual):
            raise ManualJointError(
                "保存ジョイントの相手パーツまたは対向面が現在の形状と一致しません"
            )
    keys = tuple(prepared.final.part_keys)
    if (
        str(record.get("male_part_key", ""))
        != keys[result.target.male_part_id]
        or str(record.get("female_part_key", ""))
        != keys[result.target.female_part_id]
    ):
        raise ManualJointError("保存ジョイントのパーツ識別子が一致しません")
    return result


__all__ = [
    "MANUAL_JOINT_WORKFLOW_KEYS",
    "ManualJointAvailability",
    "ManualJointAvailabilityCode",
    "ManualJointError",
    "ManualJointInterface",
    "ManualJointResult",
    "ManualJointSettings",
    "ManualJointTarget",
    "apply_manual_joint",
    "assess_manual_joint_availability",
    "create_manual_joint",
    "list_manual_joint_interfaces",
    "replay_manual_joint",
    "resolve_manual_joint_target",
]
