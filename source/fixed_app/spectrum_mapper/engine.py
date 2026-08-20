from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import tempfile
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pymeshlab as ml
import trimesh
from scipy.spatial import cKDTree

from . import APP_DISPLAY_NAME, __version__
from .assembly import (
    AssemblyError,
    BoundaryLoop,
    SeamPair,
    add_keyed_joints,
    find_boundary_loops,
    pair_matching_loops,
    repair_small_unmatched_boundaries,
    solidify_coincident_shells,
    solidify_partitioned_parts,
)
from .generated_surface_color import (
    EXPORT_DIAGNOSTICS_ATTRIBUTE,
    derive_part_face_provenance,
    make_face_provenance_record,
)
from .mixer import (
    PAIR_INDICES,
    PALETTE_STATE_COUNT,
    black_containing_mixed_states,
    black_free_replacement_states,
    black_output_ratio_preset,
    build_palette_rgb,
    coerce_palette_state_count,
    normalize_hex,
    orca_effective_mix_ratio,
    palette_mix_specs,
    palette_state_names,
    print_palette_mix_specs,
    validate_black_free_slots,
)
from .models import (
    AppSettings,
    ColorResult,
    GeometrySettings,
    MeshLevel,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
    ProgressCallback,
    SURFACE_SHELL_OUTPUT_ENABLED,
    ToneSettings,
    without_surface_shell_output,
)
from .filament_materials import generic_filament_profile, normalize_filament_material
from .parts import (
    build_part_palette_rgb_tables,
    plan_palette_groups,
    resolve_part_palette_settings,
    validate_part_layout,
)
from .volume_partition import (
    VolumePartitionError,
    solidify_complex_partitions,
)


def _paint_code_for_state(state: int) -> str:
    """Return Orca's canonical leaf code for a zero-based palette state."""

    extruder = int(state) + 1
    if extruder < 3:
        return f"{extruder << 2:X}"
    nibbles = [0xC]
    extension = extruder - 3
    while extension >= 15:
        nibbles.append(0xF)
        extension -= 15
    nibbles.append(extension)
    return "".join(f"{value:X}" for value in reversed(nibbles))


PAINT_CODES = tuple(
    _paint_code_for_state(state) for state in range(PALETTE_STATE_COUNT)
)
STATE_NAMES = palette_state_names()
_F4_STATES = [3] + [
    4 + index
    for index, (left, right, _ratio) in enumerate(
        palette_mix_specs()
    )
    if 3 in (left, right)
]
PINK_STATES = np.asarray(_F4_STATES, dtype=np.int8)
NEUTRAL_STATES = np.asarray(
    [state for state in range(PALETTE_STATE_COUNT) if state not in _F4_STATES],
    dtype=np.int8,
)


class EngineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SurfaceShellOutputSpec:
    """One stable mixed-state recipe for the experimental two-wall mode.

    Physical filament IDs are one-based, matching Orca's project format.
    ``manual_pattern`` is ``outer,inner``.  A false ``applied`` value means
    this row retained its legacy Ratio recipe; ``disposition`` distinguishes
    an intentional non-dark pass-through from an unrepresentable dark row.
    """

    state_id: int
    source_a: int
    source_b: int
    requested_ratio_b_percent: int
    effective_ratio_b_numerator: int
    effective_ratio_b_denominator: int
    darkest_filament: int | None
    lightest_filament: int | None
    architecture: str
    disposition: str
    applied: bool
    outer_filament: int | None
    inner_pattern: str | None
    manual_pattern: str | None
    fallback_reason: str | None = None

    @property
    def effective_ratio_b(self) -> Fraction:
        return Fraction(
            self.effective_ratio_b_numerator,
            self.effective_ratio_b_denominator,
        )


def _relative_srgb_luminance(value: str) -> float:
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
    return float(0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2])


def _surface_shell_extreme_slots(
    physical_hex: Sequence[str] | None,
) -> tuple[int, int] | None:
    """Return unique zero-based darkest/lightest slots or fail closed."""

    if physical_hex is None or len(physical_hex) != 4:
        return None
    try:
        luminances = tuple(_relative_srgb_luminance(value) for value in physical_hex)
    except (AttributeError, TypeError, ValueError):
        return None
    darkest_value = min(luminances)
    lightest_value = max(luminances)
    tolerance = 1e-12
    darkest = [
        index
        for index, value in enumerate(luminances)
        if abs(value - darkest_value) <= tolerance
    ]
    lightest = [
        index
        for index, value in enumerate(luminances)
        if abs(value - lightest_value) <= tolerance
    ]
    if (
        len(darkest) != 1
        or len(lightest) != 1
        or darkest[0] == lightest[0]
    ):
        return None
    return darkest[0], lightest[0]


def _canonical_balanced_pattern(
    first_filament: int,
    second_filament: int,
    second_share: Fraction,
) -> str:
    """Encode an exact, evenly spaced circular two-filament cadence."""

    share = min(Fraction(1, 1), max(Fraction(0, 1), second_share))
    if share <= 0:
        return str(first_filament)
    if share >= 1:
        return str(second_filament)
    count_second = share.numerator
    cycle = share.denominator
    tokens: list[str] = []
    for position in range(cycle):
        before = (position * count_second) // cycle
        after = ((position + 1) * count_second) // cycle
        filament = second_filament if after > before else first_filament
        tokens.append(str(filament))
    # The cadence repeats, so rotation has no physical effect.  A canonical
    # minimum makes exported 3MFs and regression tests deterministic and gives
    # the important 50/50 F1/F2 core the readable literal ``12``.
    rotations = [tokens[index:] + tokens[:index] for index in range(cycle)]
    return "".join(min(rotations))


def build_surface_shell_output_specs(
    physical_hex: Sequence[str] | None,
    mix_ratios_b: Sequence[int],
    secondary_mix_ratios_b: Sequence[int] | None = None,
    output_mix_ratios_b: Sequence[int] | None = None,
) -> tuple[SurfaceShellOutputSpec, ...]:
    """Build dark-only two-wall recipes while retaining calibrated black.

    Every applied row assumes two equal-width Classic walls.  Only mixed rows
    containing the uniquely darkest spool are changed: the non-dark partner
    is fixed on the outer wall and the calibrated dark share is moved into a
    darkest/partner inner cadence.  Pure physical colours are outside this
    table, and non-dark mixed rows intentionally retain their byte-identical
    legacy Ratio definition.  Unrepresentable or ambiguous dark rows also
    fail closed to legacy mode.
    """

    print_specs = print_palette_mix_specs(
        mix_ratios_b,
        secondary_mix_ratios_b,
        output_mix_ratios_b,
    )
    extremes = _surface_shell_extreme_slots(physical_hex)
    darkest = None if extremes is None else extremes[0]
    lightest = None if extremes is None else extremes[1]
    result: list[SurfaceShellOutputSpec] = []
    for state_id, (left, right, requested_b) in enumerate(print_specs, start=5):
        effective_b = Fraction(
            orca_effective_mix_ratio(float(requested_b) / 100.0)
        ).limit_denominator(100)
        fallback_reason: str | None = None
        architecture = "legacy-ratio"
        disposition = "passthrough"
        outer: int | None = None
        inner: str | None = None

        if extremes is None:
            disposition = "fallback"
            fallback_reason = "ambiguous-darkest-or-lightest-filament"
        elif darkest in (left, right):
            architecture = "dark-partner-core"
            disposition = "eligible"
            dark_share = effective_b if right == darkest else 1 - effective_b
            if dark_share > Fraction(1, 2):
                disposition = "fallback"
                fallback_reason = "dark-share-exceeds-two-wall-shell-capacity"
            else:
                partner = right if left == darkest else left
                outer = partner + 1
                inner = _canonical_balanced_pattern(
                    partner + 1,
                    darkest + 1,
                    2 * dark_share,
                )
        else:
            # This mode exists specifically to hide black from the external
            # side wall.  Re-encoding unrelated pairs as grouped Cycle rows
            # changes no black behaviour, makes Orca previews less familiar,
            # and increases the surface area exposed to grouped-pattern bugs.
            fallback_reason = "non-dark-pair-preserves-legacy-ratio"

        applied = disposition == "eligible" and outer is not None and inner is not None
        manual_pattern = f"{outer},{inner}" if applied else None
        result.append(
            SurfaceShellOutputSpec(
                state_id=state_id,
                source_a=left + 1,
                source_b=right + 1,
                requested_ratio_b_percent=int(requested_b),
                effective_ratio_b_numerator=effective_b.numerator,
                effective_ratio_b_denominator=effective_b.denominator,
                darkest_filament=None if darkest is None else darkest + 1,
                lightest_filament=None if lightest is None else lightest + 1,
                architecture=architecture,
                disposition=disposition,
                applied=applied,
                outer_filament=outer,
                inner_pattern=inner,
                manual_pattern=manual_pattern,
                fallback_reason=fallback_reason,
            )
        )
    return tuple(result)


def _require_exact_black_output_preset_for_surface_shell(
    physical_hex: Sequence[str] | None,
    mix_ratios_b: Sequence[int],
    secondary_mix_ratios_b: Sequence[int] | None,
    output_mix_ratios_b: Sequence[int] | None,
) -> int:
    """Return the darkest slot or reject an unsafe/custom shell recipe."""

    extremes = _surface_shell_extreme_slots(physical_hex)
    if extremes is None:
        raise EngineError(
            "黒混色の内壁化には、F1～F4内で一意な最暗色と最明色が必要です"
        )
    darkest = extremes[0]
    if output_mix_ratios_b is None:
        raise EngineError(
            "黒混色の内壁化には、先に実機黒補正（Weak Black 5-25%）を適用してください"
        )
    try:
        actual = tuple(int(value) for value in output_mix_ratios_b)
        expected = tuple(
            black_output_ratio_preset(
                darkest,
                mix_ratios_b,
                secondary_mix_ratios_b,
            )
        )
    except (TypeError, ValueError) as exc:
        raise EngineError(
            "黒混色の内壁化ではcustom出力比率を使用できません"
        ) from exc
    if actual != expected:
        raise EngineError(
            "黒混色の内壁化では、現在の最暗色に対する実機黒補正presetと完全一致する出力比率が必要です"
        )
    return darkest


def make_portable_mixed_definitions(
    mix_ratios_b: list[int],
    secondary_mix_ratios_b: list[int] | None = None,
    palette_state_count: int = 16,
    output_mix_ratios_b: list[int] | tuple[int, ...] | None = None,
    surface_shell_enabled: bool = False,
    physical_hex: Sequence[str] | None = None,
) -> str:
    """Build stable custom rows plus six deleted auto-row tombstones."""

    # Fail closed even for direct callers that bypass PaletteSettings.  The
    # legacy Ratio string is deliberately generated by the unchanged branch.
    surface_shell_enabled = bool(
        surface_shell_enabled and SURFACE_SHELL_OUTPUT_ENABLED
    )

    if len(mix_ratios_b) != 6:
        raise EngineError("混色比率は6組必要です")
    ratios = [int(value) for value in mix_ratios_b]
    if any(value < 0 or value > 100 for value in ratios):
        raise EngineError("混色比率は0～100%で指定してください")
    rows: list[str] = []
    count = coerce_palette_state_count(palette_state_count)
    try:
        specs = print_palette_mix_specs(
            ratios,
            secondary_mix_ratios_b,
            output_mix_ratios_b,
        )[: count - 4]
    except ValueError as exc:
        raise EngineError(str(exc)) from exc
    shell_specs: tuple[SurfaceShellOutputSpec, ...] = ()
    if surface_shell_enabled:
        _require_exact_black_output_preset_for_surface_shell(
            physical_hex,
            ratios,
            secondary_mix_ratios_b,
            output_mix_ratios_b,
        )
        shell_specs = build_surface_shell_output_specs(
            physical_hex,
            ratios,
            secondary_mix_ratios_b,
            output_mix_ratios_b,
        )[: count - 4]
    for stable_id, (left, right, ratio_b) in enumerate(specs, start=1):
        shell = shell_specs[stable_id - 1] if shell_specs else None
        if shell is not None and shell.applied:
            # Cycle-pattern invariant in Snapmaker Orca 2.3.5: component A/B
            # must be physical F1/F2.  Pattern tokens 3/4 are then unambiguous
            # direct physical IDs.  m2/cm1 match MixedFilamentDialog's Cycle
            # result exactly and keep the row editable without semantic drift.
            rows.append(
                f"1,2,1,1,{ratio_b},0,g,w,m2,z0,xa0,xb0,d0,o0,u{stable_id},cm1,{shell.manual_pattern}"
            )
        else:
            rows.append(
                f"{left + 1},{right + 1},1,1,{ratio_b},0,g,w,m2,z0,xa0,xb0,d0,o0,u{stable_id}"
            )
    for stable_id, (left, right) in enumerate(PAIR_INDICES, start=len(specs) + 1):
        rows.append(
            f"{left + 1},{right + 1},0,0,50,0,g,w,m2,z0,xa0,xb0,d1,o1,u{stable_id}"
        )
    return ";".join(rows)


PORTABLE_MIXED_DEFINITIONS = make_portable_mixed_definitions(
    [33] * len(PAIR_INDICES), [67] * len(PAIR_INDICES)
)


def emit(callback: ProgressCallback | None, phase: str, fraction: float, message: str) -> None:
    if callback is not None:
        callback(phase, max(0.0, min(1.0, fraction)), message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _obj_index(token: bytes, vertices_seen: int) -> int:
    head = token.split(b"/", 1)[0]
    if not head:
        raise EngineError("OBJ面に空の頂点番号があります")
    value = int(head)
    if value == 0:
        raise EngineError("OBJの頂点番号0は無効です")
    return vertices_seen + value if value < 0 else value - 1


def load_vertex_color_obj(path: Path, progress: ProgressCallback | None = None) -> ObjAsset:
    path = Path(path)
    if not path.is_file():
        raise EngineError(f"OBJが見つかりません: {path}")
    file_size = path.stat().st_size
    warnings: list[str] = []
    vertex_count = 0
    triangle_count = 0
    colored_vertices = 0
    uv_count = 0
    material_refs = 0
    object_markers = 0
    group_markers = 0
    current_object_marker = -1
    current_group_marker = -1
    object_face_markers: set[int] = set()
    group_face_markers: set[int] = set()

    emit(progress, "scan", 0.0, "OBJ構造を確認しています")
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, start=1):
            if raw.startswith(b"v "):
                vertex_count += 1
                if len(raw.split()) >= 7:
                    colored_vertices += 1
            elif raw.startswith(b"f "):
                count = len(raw.split()) - 1
                if count < 3:
                    raise EngineError(f"OBJ {line_no}行目: 面の頂点が3未満です")
                triangle_count += count - 2
                object_face_markers.add(current_object_marker)
                group_face_markers.add(current_group_marker)
            elif raw.startswith(b"vt "):
                uv_count += 1
            elif raw.startswith(b"mtllib "):
                material_refs += 1
            elif raw.startswith(b"o "):
                object_markers += 1
                current_object_marker = object_markers - 1
            elif raw.startswith(b"g "):
                group_markers += 1
                current_group_marker = group_markers - 1
            if line_no % 200_000 == 0:
                emit(progress, "scan", min(0.25, stream.tell() / max(file_size, 1) * 0.25), f"OBJ構造確認: {line_no:,}行")

    if vertex_count == 0 or triangle_count == 0:
        raise EngineError("OBJに頂点または面がありません")
    if colored_vertices != vertex_count:
        detail = f"頂点色あり {colored_vertices:,} / 全頂点 {vertex_count:,}"
        if colored_vertices == 0 and (uv_count or material_refs):
            detail += "。この初版はUVテクスチャOBJではなく、Tripoの頂点色OBJに対応しています"
        raise EngineError(detail)

    vertices = np.empty((vertex_count, 3), dtype=np.float32)
    colors = np.empty((vertex_count, 3), dtype=np.float32)
    faces = np.empty((triangle_count, 3), dtype=np.int32)
    face_part_ids = np.empty(triangle_count, dtype=np.int32)
    vi = 0
    fi = 0
    # Prefer the marker type which actually partitions faces. A common OBJ
    # layout has one global ``o`` followed by several ``g`` sections; treating
    # that single object declaration as a multipart boundary would discard the
    # real group partition. When both kinds partition faces, object markers
    # retain the historical priority.
    if len(object_face_markers) > 1:
        marker_prefix = b"o "
    elif len(group_face_markers) > 1:
        marker_prefix = b"g "
    elif object_markers:
        marker_prefix = b"o "
    elif group_markers:
        marker_prefix = b"g "
    else:
        marker_prefix = None
    part_names: list[str] = []
    part_vertex_counts: list[int] = []
    current_part = -1

    def add_part(raw_name: bytes | None = None) -> int:
        name = (
            raw_name.decode("utf-8", errors="replace").strip()
            if raw_name is not None
            else "OBJ全体"
        )
        if not name:
            name = f"part_{len(part_names)}"
        part_names.append(name)
        part_vertex_counts.append(0)
        return len(part_names) - 1

    def ensure_part() -> int:
        nonlocal current_part
        if current_part < 0:
            current_part = add_part(None)
        return current_part

    if marker_prefix is None:
        current_part = add_part(None)
    emit(progress, "parse", 0.25, f"OBJ読込: {vertex_count:,}頂点 / {triangle_count:,}三角形")
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, start=1):
            if marker_prefix is not None and raw.startswith(marker_prefix):
                current_part = add_part(raw[len(marker_prefix) :].strip())
            elif raw.startswith(b"v "):
                part_id = ensure_part()
                values = raw.split()
                try:
                    vertices[vi] = [float(values[1]), float(values[2]), float(values[3])]
                    colors[vi] = [float(values[4]), float(values[5]), float(values[6])]
                except (ValueError, IndexError) as exc:
                    raise EngineError(f"OBJ {line_no}行目: 頂点XYZRGBを読めません") from exc
                part_vertex_counts[part_id] += 1
                vi += 1
            elif raw.startswith(b"f "):
                part_id = ensure_part()
                tokens = raw.split()[1:]
                try:
                    indices = [_obj_index(token, vi) for token in tokens]
                except ValueError as exc:
                    raise EngineError(f"OBJ {line_no}行目: 面番号を読めません") from exc
                for offset in range(1, len(indices) - 1):
                    faces[fi] = [indices[0], indices[offset], indices[offset + 1]]
                    face_part_ids[fi] = part_id
                    fi += 1
            if line_no % 200_000 == 0:
                emit(progress, "parse", 0.25 + min(0.65, stream.tell() / max(file_size, 1) * 0.65), f"OBJ読込: {line_no:,}行")

    if vi != vertex_count or fi != triangle_count:
        raise EngineError(f"OBJ件数が途中で変化しました: 頂点 {vi}/{vertex_count}, 面 {fi}/{triangle_count}")
    if int(faces.min()) < 0 or int(faces.max()) >= vertex_count:
        raise EngineError("OBJ面が存在しない頂点を参照しています")
    if not np.all(np.isfinite(vertices)) or not np.all(np.isfinite(colors)):
        raise EngineError("OBJにNaNまたは無限大があります")
    part_face_counts_array = np.bincount(
        face_part_ids, minlength=len(part_names)
    ).astype(np.int64)
    nonempty_parts = np.flatnonzero(part_face_counts_array > 0)
    if len(nonempty_parts) != len(part_names):
        remap = np.full(len(part_names), -1, dtype=np.int32)
        remap[nonempty_parts] = np.arange(len(nonempty_parts), dtype=np.int32)
        face_part_ids = remap[face_part_ids]
        part_names = [part_names[int(index)] for index in nonempty_parts]
        part_vertex_counts = [
            part_vertex_counts[int(index)] for index in nonempty_parts
        ]
        part_face_counts_array = part_face_counts_array[nonempty_parts]
    part_keys = tuple(
        f"{index}:{name}" for index, name in enumerate(part_names)
    )
    color_max = float(colors.max())
    if color_max > 1.0005:
        if color_max <= 255.0005:
            colors /= 255.0
            warnings.append("頂点色を0-255から0-1へ正規化しました")
        else:
            raise EngineError(f"頂点色の最大値が異常です: {color_max:g}")
    colors = np.clip(colors, 0.0, 1.0)
    if uv_count:
        warnings.append(f"UV {uv_count:,}件は頂点色変換では使用しません")
    if material_refs:
        warnings.append("MTL参照は頂点色変換では使用しません")
    if len(part_names) > 1:
        warnings.append(
            f"OBJの明示パーツを {len(part_names)} 個認識しました"
        )
    if color_max < 0.4:
        warnings.append("頂点色が全体に暗いモデルです。白点を下げて調整してください")
    emit(progress, "parse", 1.0, "OBJ読込完了")
    return ObjAsset(
        path=path,
        sha256=sha256_file(path),
        file_size=file_size,
        vertices=vertices,
        colors=colors,
        faces=faces,
        original_vertex_count=vertex_count,
        original_face_count=triangle_count,
        warnings=warnings,
        part_names=tuple(part_names),
        part_keys=part_keys,
        face_part_ids=face_part_ids,
        part_face_counts=tuple(int(value) for value in part_face_counts_array),
        part_vertex_counts=tuple(int(value) for value in part_vertex_counts),
        part_marker_kind=(
            marker_prefix.decode("ascii").strip()
            if marker_prefix is not None
            else None
        ),
        has_explicit_parts=bool(
            marker_prefix is not None and len(part_names) > 1
        ),
    )


def load_vertex_color_model(
    path: Path,
    progress: ProgressCallback | None = None,
) -> ObjAsset:
    """Load a supported coloured model without making the caller dispatch it.

    OBJ retains the established parser.  GLB/glTF is handled by the static
    glTF importer, which bakes node transforms and rendered base colour to the
    same :class:`ObjAsset` contract used by the rest of the application.
    """

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".obj":
        return load_vertex_color_obj(path, progress)
    if suffix in {".glb", ".gltf"}:
        from .gltf_import import GltfImportError, load_gltf_asset

        try:
            return load_gltf_asset(path, progress)
        except GltfImportError as exc:
            raise EngineError(f"GLB/glTFを読み込めません: {exc}") from exc
    raise EngineError(
        f"未対応のモデル形式です: {suffix or '(拡張子なし)'}。"
        "頂点カラーOBJまたは静的GLB/glTFを選択してください"
    )


def triangle_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    tri = vertices[faces]
    return 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)


def signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    tri = vertices[faces]
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)


def edge_topology(faces: np.ndarray, vertex_count: int) -> dict[str, int | bool]:
    directed = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])).astype(np.int64)
    lo = np.minimum(directed[:, 0], directed[:, 1])
    hi = np.maximum(directed[:, 0], directed[:, 1])
    key = lo * np.int64(vertex_count) + hi
    direction = np.where(directed[:, 0] == lo, 1, -1).astype(np.int8)
    order = np.argsort(key)
    key = key[order]
    direction = direction[order]
    _, start, counts = np.unique(key, return_index=True, return_counts=True)
    paired = counts == 2
    inconsistent = int(np.count_nonzero(direction[start[paired]] == direction[start[paired] + 1]))
    boundary = int(np.count_nonzero(counts == 1))
    nonmanifold = int(np.count_nonzero(counts > 2))
    return {
        "unique_edges": int(len(counts)),
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "inconsistent_winding_edges": inconsistent,
        "watertight": boundary == 0 and nonmanifold == 0,
    }


def mesh_quality(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    check_self_intersections: bool = False,
) -> dict[str, int | bool | float | str]:
    """Return slicer-relevant solid checks for one intended print part."""

    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int32)
    result: dict[str, int | bool] = dict(edge_topology(faces, len(vertices)))
    repeated = (
        (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 2] == faces[:, 0])
    )
    areas = triangle_areas(vertices, faces)
    result["face_count"] = int(len(faces))
    result["surface_area"] = float(areas.sum())
    result["degenerate_faces"] = int(
        np.count_nonzero(repeated | ~np.isfinite(areas) | (areas <= 1e-16))
    )
    volume = trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        process=False,
    )
    result["winding_consistent"] = bool(volume.is_winding_consistent)
    result["positive_volume"] = bool(volume.is_volume)
    result["body_count"] = int(
        len(volume.split(only_watertight=False)) if len(faces) else 0
    )
    result["self_intersecting_faces"] = -1
    result["self_intersecting_area"] = -1.0
    result["self_intersecting_area_fraction"] = -1.0
    result["maximum_self_intersecting_face_area"] = -1.0
    if check_self_intersections:
        mesh_set = ml.MeshSet()
        mesh_set.add_mesh(
            ml.Mesh(vertex_matrix=vertices, face_matrix=faces),
            "3MF validation part",
        )
        try:
            mesh_set.apply_filter(
                "compute_selection_by_self_intersections_per_face"
            )
        except Exception as exc:
            raise EngineError(
                f"自己交差検査を実行できません: {exc}"
            ) from exc
        selected = np.asarray(
            mesh_set.current_mesh().face_selection_array(), dtype=bool
        )
        selected_count = int(np.count_nonzero(selected))
        selected_area = float(areas[selected].sum()) if selected_count else 0.0
        total_area = float(areas.sum())
        result["self_intersecting_faces"] = selected_count
        result["self_intersecting_area"] = selected_area
        result["self_intersecting_area_fraction"] = (
            selected_area / total_area if total_area > 0.0 else -1.0
        )
        result["maximum_self_intersecting_face_area"] = (
            float(areas[selected].max(initial=0.0)) if selected_count else 0.0
        )
    return result


def face_neighbors(faces: np.ndarray, vertex_count: int) -> np.ndarray | None:
    directed = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])).astype(np.int64)
    face_ids = np.tile(np.arange(len(faces), dtype=np.int32), 3)
    lo = np.minimum(directed[:, 0], directed[:, 1])
    hi = np.maximum(directed[:, 0], directed[:, 1])
    key = lo * np.int64(vertex_count) + hi
    order = np.argsort(key)
    key = key[order]
    face_ids = face_ids[order]
    _, start, counts = np.unique(key, return_index=True, return_counts=True)
    if not np.all(counts == 2):
        return None
    left = face_ids[start]
    right = face_ids[start + 1]
    source = np.concatenate((left, right))
    target = np.concatenate((right, left))
    by_source = np.argsort(source)
    expected = np.repeat(np.arange(len(faces)), 3)
    if not np.array_equal(source[by_source], expected):
        return None
    return target[by_source].reshape(len(faces), 3)


def face_neighbors_partial(
    faces: np.ndarray,
    vertex_count: int,
) -> np.ndarray:
    """Return three edge-neighbor slots, using -1 at open boundaries."""

    faces = np.asarray(faces, dtype=np.int32)
    neighbors = np.full((len(faces), 3), -1, dtype=np.int32)
    if not len(faces):
        return neighbors
    directed = np.vstack(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])
    ).astype(np.int64)
    face_ids = np.tile(np.arange(len(faces), dtype=np.int32), 3)
    edge_slots = np.repeat(np.arange(3, dtype=np.int8), len(faces))
    lo = np.minimum(directed[:, 0], directed[:, 1])
    hi = np.maximum(directed[:, 0], directed[:, 1])
    keys = lo * np.int64(vertex_count) + hi
    order = np.argsort(keys)
    keys = keys[order]
    face_ids = face_ids[order]
    edge_slots = edge_slots[order]
    _, starts, counts = np.unique(keys, return_index=True, return_counts=True)
    for start in starts[counts == 2]:
        left = int(face_ids[start])
        right = int(face_ids[start + 1])
        if left == right:
            continue
        neighbors[left, int(edge_slots[start])] = right
        neighbors[right, int(edge_slots[start + 1])] = left
    return neighbors


def _orient_unit(vertices: np.ndarray, faces: np.ndarray, up_axis: str, mirror_x: bool) -> tuple[np.ndarray, np.ndarray]:
    axis = up_axis.upper()
    if axis == "Y":
        result = np.column_stack((vertices[:, 0], -vertices[:, 2], vertices[:, 1]))
    elif axis == "Z":
        result = vertices.copy()
    elif axis == "X":
        result = np.column_stack((vertices[:, 1], -vertices[:, 2], vertices[:, 0]))
    else:
        raise EngineError(f"未対応の上方向です: {up_axis}")
    if mirror_x:
        result[:, 0] *= -1.0
    height = float(np.ptp(result[:, 2]))
    if height <= 1e-12:
        raise EngineError("モデル高さが0です。上方向を変更してください")
    result = result.astype(np.float64) / height
    minimum = result.min(axis=0)
    maximum = result.max(axis=0)
    result[:, 0] -= (minimum[0] + maximum[0]) * 0.5
    result[:, 1] -= (minimum[1] + maximum[1]) * 0.5
    result[:, 2] -= minimum[2]
    faces = faces.copy()
    if signed_volume(result, faces) < 0.0:
        faces[:, [1, 2]] = faces[:, [2, 1]]
    return result, faces


def _mesh_from_set(mesh_set: ml.MeshSet) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mesh = mesh_set.current_mesh()
    vertices = np.asarray(mesh.vertex_matrix(), dtype=np.float64)
    faces = np.asarray(mesh.face_matrix(), dtype=np.int32)
    rgba = np.asarray(mesh.vertex_color_matrix(), dtype=np.float64)
    if rgba.shape[0] != len(vertices) or rgba.shape[1] < 3:
        raise EngineError("形状処理中に頂点色が失われました")
    return vertices, faces, np.clip(rgba[:, :3], 0.0, 1.0)


def _simplify_mesh(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    target_faces: int,
    *,
    preserve_boundary: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    if target_faces >= len(faces):
        return vertices.copy(), faces.copy()
    rgba = np.column_stack((colors, np.ones(len(colors), dtype=np.float64)))
    mesh_set = ml.MeshSet()
    mesh_set.add_mesh(ml.Mesh(vertex_matrix=vertices, face_matrix=faces, v_color_matrix=rgba), "source")
    mesh_set.apply_filter(
        "meshing_decimation_quadric_edge_collapse",
        targetfacenum=max(4, int(target_faces)),
        preserveboundary=bool(preserve_boundary),
        boundaryweight=10.0 if preserve_boundary else 1.0,
        preservetopology=True,
        preservenormal=True,
        autoclean=True,
    )
    mesh = mesh_set.current_mesh()
    return np.asarray(mesh.vertex_matrix(), dtype=np.float64), np.asarray(mesh.face_matrix(), dtype=np.int32)


def _transfer_colors(
    source_vertices: np.ndarray,
    source_colors: np.ndarray,
    new_vertices: np.ndarray,
    *,
    aligned_color_hints: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    if len(source_vertices) == len(new_vertices) and np.array_equal(source_vertices, new_vertices):
        return source_colors.copy(), {"mean": 0.0, "p99": 0.0, "max": 0.0}

    if aligned_color_hints is not None:
        hints = np.asarray(aligned_color_hints, dtype=np.float64)
        if hints.shape != (len(new_vertices), 3):
            raise EngineError("形状処理中の頂点色対応が不正です")

        # MeshLab's component cleanup preserves surviving vertices as an
        # order-preserving subsequence, but exposes their aligned RGB through
        # 8-bit channels.  Use those channels only to distinguish coincident
        # source vertices, then restore the original full-precision RGB.  A
        # coordinate-only nearest-neighbour lookup would collapse colour seams
        # whenever two retained vertices share a position but not a colour.
        source_rgb8 = np.floor(
            np.clip(np.asarray(source_colors, dtype=np.float64), 0.0, 1.0)
            * 255.0
            + 1.0e-9
        ).astype(np.uint8)
        hint_rgb8 = np.rint(np.clip(hints, 0.0, 1.0) * 255.0).astype(
            np.uint8
        )
        source = np.asarray(source_vertices, dtype=np.float64)
        target = np.asarray(new_vertices, dtype=np.float64)
        mapping = np.empty(len(target), dtype=np.intp)
        source_index = 0
        ordered_match = True
        for target_index in range(len(target)):
            while source_index < len(source):
                if np.array_equal(source[source_index], target[target_index]) and np.array_equal(
                    source_rgb8[source_index], hint_rgb8[target_index]
                ):
                    mapping[target_index] = source_index
                    source_index += 1
                    break
                source_index += 1
            else:
                ordered_match = False
                break
        if ordered_match:
            return source_colors[mapping].copy(), {
                "mean": 0.0,
                "p99": 0.0,
                "max": 0.0,
            }

    tree = cKDTree(source_vertices, compact_nodes=True, balanced_tree=True)
    distances, indices = tree.query(new_vertices, k=1, workers=-1)
    if aligned_color_hints is not None and len(new_vertices):
        # Defensive fallback for a future MeshLab build that reorders vertices.
        # Resolve only ambiguous exact-position matches with its aligned 8-bit
        # colour; ordinary geometry-changing transfers retain the established
        # nearest-neighbour behaviour.
        selected_rgb8 = source_rgb8[np.asarray(indices, dtype=np.intp)]
        mismatched = np.flatnonzero(np.any(selected_rgb8 != hint_rgb8, axis=1))
        for target_index in mismatched:
            candidates = tree.query_ball_point(new_vertices[target_index], r=0.0)
            if not candidates:
                continue
            candidate_ids = np.asarray(candidates, dtype=np.intp)
            differences = np.sum(
                np.abs(
                    source_rgb8[candidate_ids].astype(np.int16)
                    - hint_rgb8[target_index].astype(np.int16)
                ),
                axis=1,
            )
            indices[target_index] = candidate_ids[int(np.argmin(differences))]
    return source_colors[indices], {
        "mean": float(distances.mean()),
        "p99": float(np.quantile(distances, 0.99)),
        "max": float(distances.max()),
    }


def _center_and_floor(vertices: np.ndarray) -> np.ndarray:
    result = vertices.copy()
    minimum = result.min(axis=0)
    maximum = result.max(axis=0)
    result[:, 0] -= (minimum[0] + maximum[0]) * 0.5
    result[:, 1] -= (minimum[1] + maximum[1]) * 0.5
    result[:, 2] -= minimum[2]
    return result


def _compact_part_mesh(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    used = np.unique(np.asarray(faces, dtype=np.int32).reshape(-1))
    local_faces = np.searchsorted(used, faces).astype(np.int32)
    return vertices[used], local_faces, colors[used]


def _allocate_part_targets(counts: np.ndarray, requested_total: int) -> np.ndarray:
    counts = np.asarray(counts, dtype=np.int64)
    if counts.ndim != 1 or not len(counts) or np.any(counts <= 0):
        raise EngineError("パーツ別面数が不正です")
    total = min(int(requested_total), int(counts.sum()))
    lower = np.minimum(counts, 4)
    if total < int(lower.sum()):
        raise EngineError("指定面数がパーツ数に対して少なすぎます")
    capacity = counts - lower
    remaining = total - int(lower.sum())
    raw_extra = remaining * counts.astype(np.float64) / max(
        float(counts.sum()), 1.0
    )
    extra = np.minimum(capacity, np.floor(raw_extra).astype(np.int64))
    targets = lower + extra
    left = total - int(targets.sum())
    while left > 0:
        candidates = np.flatnonzero(targets < counts)
        if not len(candidates):
            break
        scores = raw_extra[candidates] - extra[candidates]
        order = candidates[
            np.lexsort((candidates, -scores))
        ]
        take = min(left, len(order))
        selected = order[:take]
        targets[selected] += 1
        extra[selected] += 1
        left -= take
    return targets.astype(np.int64)


def _combine_part_meshes(
    meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    vertices: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    colors: list[np.ndarray] = []
    face_parts: list[np.ndarray] = []
    vertex_offset = 0
    for part_id, (part_vertices, part_faces, part_colors) in enumerate(meshes):
        vertices.append(np.asarray(part_vertices, dtype=np.float64))
        faces.append(np.asarray(part_faces, dtype=np.int32) + vertex_offset)
        colors.append(np.asarray(part_colors, dtype=np.float64))
        face_parts.append(
            np.full(len(part_faces), part_id, dtype=np.int16)
        )
        vertex_offset += len(part_vertices)
    return (
        np.vstack(vertices),
        np.vstack(faces),
        np.vstack(colors),
        np.concatenate(face_parts),
    )


def _boundary_loop_key(loop: BoundaryLoop) -> tuple[int, int]:
    return int(loop.part_id), int(loop.loop_id)


def _build_boundary_diagnostics(
    loops: Iterable[BoundaryLoop],
    seams: Iterable[SeamPair],
    source_meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    final_meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    *,
    part_names: list[str],
    part_keys: list[str],
    height_mm: float,
    local_repair_records: Iterable[dict[str, object]] = (),
) -> tuple[list[dict[str, object]], list[int], list[int]]:
    """Describe simplified open loops using face IDs from the final mesh.

    Planar cap construction preserves source face order, while optional boolean
    joint work may rebuild it.  The fast path therefore uses the preserved
    prefix and the fallback maps only boundary-adjacent face centres to their
    nearest final face in the same part.
    """

    loop_list = list(loops)
    seam_list = list(seams)
    matched_by_key: dict[tuple[int, int], tuple[SeamPair, BoundaryLoop]] = {}
    for seam in seam_list:
        matched_by_key[_boundary_loop_key(seam.first)] = (seam, seam.second)
        matched_by_key[_boundary_loop_key(seam.second)] = (seam, seam.first)
    repair_by_key = {
        (int(record.get("part_id", -1)), int(record.get("loop_id", -1))): record
        for record in local_repair_records
    }
    face_offsets = np.cumsum(
        np.asarray(
            [0, *[len(mesh[1]) for mesh in final_meshes]],
            dtype=np.int64,
        )
    )
    loops_by_part: dict[int, list[BoundaryLoop]] = {}
    for loop in loop_list:
        loops_by_part.setdefault(int(loop.part_id), []).append(loop)

    final_local_face_ids: dict[tuple[int, int], list[int]] = {}
    mapping_methods: dict[int, str] = {}
    for part_id, part_loops in loops_by_part.items():
        if not 0 <= part_id < len(source_meshes) or part_id >= len(final_meshes):
            continue
        source_vertices = np.asarray(source_meshes[part_id][0], dtype=np.float64)
        source_faces = np.asarray(source_meshes[part_id][1], dtype=np.int32)
        final_vertices = np.asarray(final_meshes[part_id][0], dtype=np.float64)
        final_faces = np.asarray(final_meshes[part_id][1], dtype=np.int32)
        source_face_ids = np.unique(
            np.concatenate(
                [
                    np.asarray(loop.adjacent_face_ids, dtype=np.int64)
                    for loop in part_loops
                    if len(loop.adjacent_face_ids)
                ]
            )
        )
        if not len(source_face_ids):
            for loop in part_loops:
                final_local_face_ids[_boundary_loop_key(loop)] = []
            mapping_methods[part_id] = "none"
            continue
        prefix_preserved = (
            len(final_faces) >= len(source_faces)
            and np.array_equal(final_faces[: len(source_faces)], source_faces)
        )
        if prefix_preserved:
            mapped = source_face_ids.astype(np.int64)
            mapping_methods[part_id] = "preserved_face_prefix"
        else:
            source_centers = source_vertices[
                source_faces[source_face_ids]
            ].mean(axis=1)
            final_centers = final_vertices[final_faces].mean(axis=1)
            mapped = np.asarray(
                cKDTree(final_centers, compact_nodes=True, balanced_tree=True)
                .query(source_centers, k=1, workers=-1)[1],
                dtype=np.int64,
            )
            mapping_methods[part_id] = "nearest_final_face_center"
        mapped_by_source = {
            int(source_id): int(final_id)
            for source_id, final_id in zip(
                source_face_ids, mapped, strict=True
            )
        }
        for loop in part_loops:
            final_local_face_ids[_boundary_loop_key(loop)] = sorted(
                {
                    mapped_by_source[int(source_id)]
                    for source_id in np.asarray(
                        loop.adjacent_face_ids, dtype=np.int64
                    )
                }
            )

    diagnostics: list[dict[str, object]] = []
    matched_face_ids: set[int] = set()
    unmatched_face_ids: set[int] = set()
    for loop in sorted(
        loop_list, key=lambda value: (int(value.part_id), int(value.loop_id))
    ):
        key = _boundary_loop_key(loop)
        part_id = int(loop.part_id)
        matched_info = matched_by_key.get(key)
        repaired = repair_by_key.get(key)
        local_face_ids = final_local_face_ids.get(key, [])
        global_face_ids = [
            int(face_offsets[part_id] + face_id)
            for face_id in local_face_ids
        ]
        if matched_info is None:
            unmatched_face_ids.update(global_face_ids)
            seam_id: int | None = None
            paired_part_id: int | None = None
            paired_loop_id: int | None = None
        else:
            matched_face_ids.update(global_face_ids)
            seam, paired_loop = matched_info
            seam_id = int(seam.seam_id)
            paired_part_id = int(paired_loop.part_id)
            paired_loop_id = int(paired_loop.loop_id)
        diagnostics.append(
            {
                "part_id": part_id,
                "part_name": (
                    str(part_names[part_id])
                    if 0 <= part_id < len(part_names)
                    else f"part_{part_id}"
                ),
                "part_key": (
                    str(part_keys[part_id])
                    if 0 <= part_id < len(part_keys)
                    else str(part_id)
                ),
                "loop_id": int(loop.loop_id),
                "matched": matched_info is not None,
                "seam_id": seam_id,
                "paired_part_id": paired_part_id,
                "paired_loop_id": paired_loop_id,
                "boundary_vertex_count": int(len(loop.vertex_ids)),
                "center_unit": np.asarray(loop.center_unit, dtype=np.float64)
                .round(9)
                .tolist(),
                "center_mm": (
                    np.asarray(loop.center_unit, dtype=np.float64)
                    * float(height_mm)
                )
                .round(6)
                .tolist(),
                "span_mm": float(loop.span_unit) * float(height_mm),
                "perimeter_mm": float(loop.perimeter_unit)
                * float(height_mm),
                "adjacent_final_face_ids": global_face_ids,
                "face_mapping_method": mapping_methods.get(part_id, "none"),
                "repair_applied": repaired is not None,
                "repair_method": (
                    str(repaired.get("method", "")) if repaired else None
                ),
            }
        )
    return diagnostics, sorted(matched_face_ids), sorted(unmatched_face_ids)


def _clean_part(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    min_component_faces: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Clean one part while retaining malformed components and their colours.

    MeshLab rejects coherent orientation when any face has a non-2-manifold
    neighbourhood.  Generated OBJ files commonly contain a mostly valid shell
    plus a few touching sheets.  The historical all-or-nothing call therefore
    made the complete model impossible to open.

    The fast path remains unchanged.  On rejection, the orientation fallback
    preserves the already-cleaned mesh's winding and face order.  Optional
    component cleanup may still remove configured tiny islands.  The returned
    JSON-safe record makes the decision explicit.  Explicit OBJ parts pass
    through this helper independently, so one malformed part cannot prevent
    the other parts from being oriented normally.
    """

    source_vertices = np.asarray(vertices, dtype=np.float64)
    source_faces = np.asarray(faces, dtype=np.int32)
    source_colors = np.asarray(colors, dtype=np.float64)

    def mesh_set_for(
        local_vertices: np.ndarray,
        local_faces: np.ndarray,
        local_colors: np.ndarray,
        name: str,
    ) -> ml.MeshSet:
        local_rgba = np.column_stack(
            (
                np.asarray(local_colors, dtype=np.float64),
                np.ones(len(local_colors), dtype=np.float64),
            )
        )
        result = ml.MeshSet()
        result.add_mesh(
            ml.Mesh(
                vertex_matrix=np.asarray(local_vertices, dtype=np.float64),
                face_matrix=np.asarray(local_faces, dtype=np.int32),
                v_color_matrix=local_rgba,
            ),
            name,
        )
        return result

    def detail(exc: BaseException) -> str:
        return " ".join(str(exc).split())[:500]

    diagnostic: dict[str, object] = {
        "schema": "obj-adjuster.geometry-cleaning.v1",
        "source_vertices": int(len(source_vertices)),
        "source_faces": int(len(source_faces)),
        "minimum_component_faces": int(min_component_faces),
        "component_filter_failed": False,
        "component_filter_reverted": False,
        "orientation_method": "coherent",
        "orientation_fallback_used": False,
        "orientation_face_count_preserved": True,
        "components": [],
    }

    if min_component_faces > 0:
        mesh_set = mesh_set_for(
            source_vertices, source_faces, source_colors, "Tripo part"
        )
        try:
            mesh_set.apply_filter(
                "meshing_remove_connected_component_by_face_number",
                mincomponentsize=int(min_component_faces),
                removeunref=True,
            )
        except ml.PyMeshLabException as exc:
            # Decorative-island removal is optional.  A failure must not make
            # the original named part unreadable.
            diagnostic["component_filter_failed"] = True
            diagnostic["component_filter_error"] = detail(exc)
            mesh_set = mesh_set_for(
                source_vertices, source_faces, source_colors, "Tripo part"
            )
        clean_vertices, clean_faces, meshlab_colors = _mesh_from_set(mesh_set)
        clean_colors = meshlab_colors
    else:
        # This is the common new-OBJ path.  Bypass MeshLab completely until
        # topology is known to be orientable so source face order and RGB stay
        # bit-for-bit stable in the non-manifold fallback.
        clean_vertices = source_vertices.copy()
        clean_faces = source_faces.copy()
        clean_colors = source_colors.copy()
    if not len(clean_faces):
        # Preserve a named part even if all of its islands are below the
        # configured removal threshold.
        diagnostic["component_filter_reverted"] = True
        clean_vertices = source_vertices.copy()
        clean_faces = source_faces.copy()
        clean_colors = source_colors.copy()
    else:
        # PyMeshLab exposes vertex colours through an 8-bit channel and would
        # otherwise quantize the source RGB values merely by passing through
        # cleanup.  Geometry cleanup does not synthesize positions here, so a
        # nearest source-vertex transfer restores the original colour samples.
        clean_colors, _clean_color_transfer = _transfer_colors(
            source_vertices,
            source_colors,
            clean_vertices,
            aligned_color_hints=clean_colors,
        )

    diagnostic["clean_vertices_before_orientation"] = int(
        len(clean_vertices)
    )
    diagnostic["clean_faces_before_orientation"] = int(len(clean_faces))
    diagnostic["removed_vertices"] = int(
        len(source_vertices) - len(clean_vertices)
    )
    diagnostic["removed_faces"] = int(len(source_faces) - len(clean_faces))
    before_topology = edge_topology(clean_faces, len(clean_vertices))
    diagnostic["topology_before_orientation"] = before_topology

    if int(before_topology["nonmanifold_edges"]) == 0:
        oriented_set = mesh_set_for(
            clean_vertices, clean_faces, clean_colors, "Tripo part"
        )
        try:
            oriented_set.apply_filter("meshing_re_orient_faces_coherently")
            oriented = _mesh_from_set(oriented_set)
        except ml.PyMeshLabException as exc:
            orientation_error = detail(exc)
        else:
            # Unexpected data loss is an engine invariant violation, not an
            # orientability fallback.  Propagate it instead of hiding it.
            if len(oriented[1]) != len(clean_faces):
                raise EngineError("coherent orientation changed the face count")
            oriented_colors, _oriented_color_transfer = _transfer_colors(
                clean_vertices,
                clean_colors,
                oriented[0],
                aligned_color_hints=oriented[2],
            )
            oriented = (oriented[0], oriented[1], oriented_colors)
            diagnostic["clean_vertices"] = int(len(oriented[0]))
            diagnostic["clean_faces"] = int(len(oriented[1]))
            diagnostic["topology_after_orientation"] = edge_topology(
                oriented[1], len(oriented[0])
            )
            return (*oriented, diagnostic)
    else:
        # This is a deterministic rejection condition for MeshLab's coherent
        # orientation filter.  Do not split or remove its faces: retaining the
        # source face order also preserves manual-paint and part-ID mapping.
        orientation_error = (
            "coherent orientation requires a 2-manifold; "
            f"nonmanifold_edges={before_topology['nonmanifold_edges']}"
        )

    diagnostic["orientation_fallback_used"] = True
    diagnostic["direct_orientation_error"] = orientation_error
    diagnostic["orientation_method"] = "source_winding_preserved"
    diagnostic["clean_vertices"] = int(len(clean_vertices))
    diagnostic["clean_faces"] = int(len(clean_faces))
    diagnostic["orientation_face_count_preserved"] = True
    diagnostic["topology_after_orientation"] = before_topology
    diagnostic["components"] = [
        {
            "id": 0,
            "source_vertices": int(len(clean_vertices)),
            "source_faces": int(len(clean_faces)),
            "vertices_after_orientation": int(len(clean_vertices)),
            "faces_after_orientation": int(len(clean_faces)),
            "orientation": "source_winding_preserved",
            "orientation_error": orientation_error,
            "face_count_preserved": True,
            "topology_before_orientation": before_topology,
            "topology_after_orientation": before_topology,
        }
    ]
    return (
        clean_vertices.copy(),
        clean_faces.copy(),
        clean_colors.copy(),
        diagnostic,
    )


def _prepare_geometry_parts(
    asset: ObjAsset,
    settings: GeometrySettings,
    progress: ProgressCallback | None,
) -> PreparedGeometry:
    warnings = list(asset.warnings)
    # Explicit multipart routing and closed-solid reconstruction are separate
    # choices.  The normal import path keeps Tripo's lightweight coloured
    # patches available for inspection; only an explicit setting may create
    # printable closed bodies.
    solidify_parts = bool(settings.solidify_parts)
    part_count = len(asset.part_names)
    output_part_names = list(asset.part_names)
    output_part_keys = list(asset.part_keys)
    emit(
        progress,
        "clean",
        0.02,
        f"{part_count}パーツを保持して形状を整理しています",
    )
    oriented_vertices, oriented_faces = _orient_unit(
        asset.vertices.astype(np.float64),
        asset.faces,
        settings.up_axis,
        settings.mirror_x,
    )
    clean_meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    cleaning_diagnostics: list[dict[str, object]] = []
    boundary_loops = []
    part_stats: list[dict[str, object]] = []
    for part_id, (part_name, part_key) in enumerate(
        zip(asset.part_names, asset.part_keys, strict=True)
    ):
        source_face_ids = np.flatnonzero(asset.face_part_ids == part_id)
        source_faces = oriented_faces[source_face_ids]
        part_vertices, part_faces, part_colors = _compact_part_mesh(
            oriented_vertices, source_faces, asset.colors
        )
        source_volume = signed_volume(part_vertices, part_faces)
        (
            clean_vertices,
            clean_faces,
            clean_colors,
            cleaning_diagnostic,
        ) = _clean_part(
            part_vertices,
            part_faces,
            part_colors,
            settings.min_component_faces,
        )
        cleaning_diagnostic["part_id"] = int(part_id)
        cleaning_diagnostic["part_key"] = str(part_key)
        cleaning_diagnostic["part_name"] = str(part_name)
        cleaning_diagnostics.append(cleaning_diagnostic)
        if bool(cleaning_diagnostic.get("component_filter_failed")):
            warnings.append(
                f"{part_name}: 微小成分の整理に失敗したため元形状を保持しました"
            )
        if bool(cleaning_diagnostic.get("component_filter_reverted")):
            warnings.append(
                f"{part_name}: パーツ全体が消えるため微小成分の除去を取り消しました"
            )
        if bool(cleaning_diagnostic.get("orientation_fallback_used")):
            topology_before = cleaning_diagnostic.get(
                "topology_before_orientation", {}
            )
            nonmanifold_edges = (
                int(topology_before.get("nonmanifold_edges", 0))
                if isinstance(topology_before, dict)
                else 0
            )
            warnings.append(
                f"{part_name}: 非多様体形状の面向き補正を安全に省略し、"
                f"整理後の{len(clean_faces):,}面・面順序・頂点色を保持しました"
                f"（非多様体辺 {nonmanifold_edges:,}）"
            )
        clean_volume = signed_volume(clean_vertices, clean_faces)
        if (
            cleaning_diagnostic.get("orientation_method")
            != "source_winding_preserved"
            and source_volume * clean_volume < 0.0
        ):
            clean_faces[:, [1, 2]] = clean_faces[:, [2, 1]]
        clean_meshes.append((clean_vertices, clean_faces, clean_colors))
        part_loops = find_boundary_loops(
            part_id, clean_vertices, clean_faces
        )
        boundary_loops.extend(part_loops)
        part_stats.append(
            {
                "id": part_id,
                "key": part_key,
                "name": part_name,
                "source_vertices": int(len(part_vertices)),
                "source_faces": int(len(part_faces)),
                "clean_vertices": int(len(clean_vertices)),
                "clean_faces": int(len(clean_faces)),
                "removed_vertices": int(len(part_vertices) - len(clean_vertices)),
                "removed_faces": int(len(part_faces) - len(clean_faces)),
                "open_boundary_loops": int(len(part_loops)),
                "open_boundary_edges": int(
                    sum(len(loop.vertex_ids) for loop in part_loops)
                ),
                "cleaning_orientation_method": str(
                    cleaning_diagnostic.get("orientation_method", "unknown")
                ),
                "cleaning_orientation_fallback": bool(
                    cleaning_diagnostic.get("orientation_fallback_used")
                ),
            }
        )
        emit(
            progress,
            "clean",
            0.04 + 0.14 * (part_id + 1) / part_count,
            f"パーツ {part_id + 1}/{part_count}: {part_name}",
        )

    source_clean_part_count = len(clean_meshes)
    source_clean_vertex_count = int(
        sum(len(mesh[0]) for mesh in clean_meshes)
    )
    source_clean_face_count = int(sum(len(mesh[1]) for mesh in clean_meshes))
    removed_vertices = max(
        0, asset.original_vertex_count - source_clean_vertex_count
    )
    removed_faces = max(0, asset.original_face_count - source_clean_face_count)
    if removed_faces:
        warnings.append(f"微小な孤立形状など {removed_faces:,}面を除去しました")
    source_minimum = np.min(
        np.vstack([mesh[0].min(axis=0) for mesh in clean_meshes]), axis=0
    )
    source_maximum = np.max(
        np.vstack([mesh[0].max(axis=0) for mesh in clean_meshes]), axis=0
    )
    source_dimensions = source_maximum - source_minimum
    source_area = float(
        sum(triangle_areas(mesh[0], mesh[1]).sum() for mesh in clean_meshes)
    )
    source_volume = float(
        sum(signed_volume(mesh[0], mesh[1]) for mesh in clean_meshes)
    )

    source_part_stats = [dict(stats) for stats in part_stats]
    repair_records: list[dict[str, object]] = []
    local_boundary_repair_records: list[dict[str, object]] = []
    repair_method = "none"
    reconstructed_bodies: dict[str, object] = {}
    joint_records: list[dict[str, object]] = []

    # Prepare each source partition before closing it.  Face-count adjustment
    # is opt-in for a newly opened OBJ; when it is disabled the cleaned source
    # topology is copied without decimation.  In either mode, keeping the open
    # boundary fixed is essential so both sides still describe the same Tripo
    # seam when the shared interface is generated below.
    clean_vertices_all, clean_faces_all, _clean_colors_all, _clean_face_parts = (
        _combine_part_meshes(clean_meshes)
    )
    clean_vertex_count = len(clean_vertices_all)
    clean_face_count = len(clean_faces_all)
    clean_counts = np.asarray(
        [len(mesh[1]) for mesh in clean_meshes], dtype=np.int64
    )
    final_target = (
        min(int(settings.target_faces), clean_face_count)
        if bool(settings.adjust_face_count)
        else clean_face_count
    )
    targets = _allocate_part_targets(clean_counts, final_target)
    simplified_open_meshes: list[
        tuple[np.ndarray, np.ndarray, np.ndarray]
    ] = []
    transfer_p99_mm: list[float] = []
    for part_id, ((vertices, faces, colors), target) in enumerate(
        zip(clean_meshes, targets, strict=True)
    ):
        message = (
            f"パーツ {part_id + 1}/{part_count}の面数を調整: "
            f"{len(faces):,} → {int(target):,}面"
            if settings.adjust_face_count
            else (
                f"パーツ {part_id + 1}/{part_count}の元面数を保持: "
                f"{len(faces):,}面"
            )
        )
        emit(
            progress,
            "simplify",
            0.18 + 0.30 * part_id / part_count,
            message,
        )
        simplified_vertices, simplified_faces = _simplify_mesh(
            vertices,
            faces,
            colors,
            int(target),
            preserve_boundary=True,
        )
        simplified_colors, transfer = _transfer_colors(
            vertices, colors, simplified_vertices
        )
        if signed_volume(vertices, faces) * signed_volume(
            simplified_vertices, simplified_faces
        ) < 0.0:
            simplified_faces[:, [1, 2]] = simplified_faces[:, [2, 1]]
        simplified_open_meshes.append(
            (simplified_vertices, simplified_faces, simplified_colors)
        )
        transfer_p99_mm.append(
            float(transfer["p99"]) * float(settings.height_mm)
        )
        part_stats[part_id]["target_faces"] = int(target)

    simplified_boundary_loops = []
    for part_id, (vertices, faces, _colors) in enumerate(
        simplified_open_meshes
    ):
        simplified_boundary_loops.extend(
            find_boundary_loops(part_id, vertices, faces)
        )
    seams = pair_matching_loops(
        simplified_boundary_loops,
        height_mm=settings.height_mm,
    )
    matched_loop_keys = {
        _boundary_loop_key(loop)
        for seam in seams
        for loop in (seam.first, seam.second)
    }
    unmatched_boundary_loops = [
        loop
        for loop in simplified_boundary_loops
        if _boundary_loop_key(loop) not in matched_loop_keys
    ]
    if simplified_boundary_loops:
        warnings.append(
            f"開いた切断境界を {len(simplified_boundary_loops)} 個検出し、"
            f"相手パーツとの継ぎ目を {len(seams)} 組認識しました"
        )
    final_meshes = simplified_open_meshes
    if solidify_parts:
        emit(
            progress,
            "solidify",
            0.50,
            "Tripoのパーツ数を保ったまま、各パーツを閉立体化しています",
        )
        if simplified_boundary_loops:
            unmatched_loops = len(unmatched_boundary_loops)
            if unmatched_loops and not bool(
                settings.repair_unmatched_boundaries
            ):
                raise EngineError(
                    "開いた境界のうち "
                    f"{unmatched_loops} 個は対応相手を特定できませんでした。"
                    "誤った蓋で色や腕などを変形させないため、自動修復を停止しました。"
                    "元OBJのパーツ境界を確認してください"
                )
            if unmatched_loops:
                try:
                    (
                        final_meshes,
                        local_boundary_repair_records,
                    ) = repair_small_unmatched_boundaries(
                        final_meshes,
                        unmatched_boundary_loops,
                        height_mm=settings.height_mm,
                        maximum_span_mm=2.0,
                        maximum_planarity_mm=0.02,
                    )
                except AssemblyError as exc:
                    raise EngineError(
                        "対応相手のない境界を安全な局所穴として修復できませんでした。"
                        "最大幅2.0 mm以下かつ厳格に平面な境界だけを修復します。\n"
                        f"詳細: {exc}"
                    ) from exc
                repair_records.append(
                    {
                        "method": "strict_planar_unmatched_boundary_caps",
                        "maximum_span_mm": 2.0,
                        "maximum_planarity_mm": 0.02,
                        "repaired_loop_count": int(
                            len(local_boundary_repair_records)
                        ),
                        "loops": local_boundary_repair_records,
                    }
                )
                warnings.append(
                    "対応相手のない微小で平面的な境界を "
                    f"{len(local_boundary_repair_records)} 個だけ局所修復しました"
                )
            try:
                final_meshes, repair = solidify_partitioned_parts(
                    final_meshes,
                    seams,
                    height_mm=settings.height_mm,
                )
            except AssemblyError as planar_exc:
                warnings.append(
                    "継ぎ目が強く曲がっているため、"
                    "品質を保つ曲面体積分割へ自動切替しました"
                )
                try:
                    final_meshes, repair = solidify_complex_partitions(
                        final_meshes,
                        seams,
                        height_mm=settings.height_mm,
                        progress=progress,
                    )
                except VolumePartitionError as volume_exc:
                    raise EngineError(
                        "Tripoパーツを個別の閉立体へ再構成できません。\n"
                        f"共有面方式: {planar_exc}\n"
                        f"曲面体積方式: {volume_exc}"
                    ) from volume_exc
            repair_method = str(repair.get("method", "partitioned_shared_caps"))
            repair_record = dict(repair)
            repair_records.append(repair_record)
            repair_parts = repair.get("parts", [])
            for part_id, body_mesh in enumerate(final_meshes):
                part_repair = (
                    repair_parts[part_id]
                    if isinstance(repair_parts, list)
                    and part_id < len(repair_parts)
                    and isinstance(repair_parts[part_id], dict)
                    else {}
                )
                part_stats[part_id]["repair_added_faces"] = int(
                    part_repair.get(
                        "added_faces",
                        len(body_mesh[1]) - len(simplified_open_meshes[part_id][1]),
                    )
                )
                part_stats[part_id]["watertight_after_repair"] = True
                part_stats[part_id]["repair_method"] = repair_method
            warnings.append(
                f"Tripoの元パーツ {source_clean_part_count} 個を保持し、"
                f"{len(seams)} 組の共有境界でそれぞれ閉立体化しました"
            )
            if (
                bool(settings.auto_joints)
                and seams
                and repair_method == "partitioned_shared_caps"
            ):
                emit(
                    progress,
                    "joints",
                    0.55,
                    "安全な継ぎ目に組立ジョイントを生成しています",
                )
                final_meshes, joint_records, joint_warnings = add_keyed_joints(
                    final_meshes,
                    seams,
                    height_mm=settings.height_mm,
                    width_mm=settings.joint_width_mm,
                    key_height_mm=settings.joint_height_mm,
                    depth_mm=settings.joint_depth_mm,
                    clearance_mm=settings.joint_clearance_mm,
                    minimum_span_mm=settings.joint_min_seam_span_mm,
                )
                warnings.extend(joint_warnings)
                if joint_records:
                    warnings.append(
                        f"安全検証に合格した組立ジョイントを "
                        f"{len(joint_records)} 組生成しました"
                    )
            elif bool(settings.auto_joints) and seams:
                warnings.append(
                    "強く曲がった共有面ではジョイント位置を"
                    "安全に保証できないため、自動生成を省略しました"
                )
        else:
            open_parts: list[int] = []
            for part_id, (vertices, faces, _colors) in enumerate(final_meshes):
                part_topology = edge_topology(faces, len(vertices))
                if not bool(part_topology["watertight"]):
                    open_parts.append(part_id)
                repair_records.append(
                    {
                        "part_id": int(part_id),
                        "part_key": output_part_keys[part_id],
                        "method": "already_watertight",
                        "added_faces": 0,
                        "before": part_topology,
                        "after": part_topology,
                        "closed": bool(part_topology["watertight"]),
                    }
                )
                part_stats[part_id]["repair_added_faces"] = 0
                part_stats[part_id]["watertight_after_repair"] = bool(
                    part_topology["watertight"]
                )
            if open_parts:
                labels = ", ".join(str(index + 1) for index in open_parts)
                raise EngineError(
                    "閉じていないパーツを安全に再構成できませんでした: "
                    f"{labels}"
                )
            repair_method = "already_watertight"

    (
        boundary_diagnostics,
        matched_boundary_face_ids,
        unmatched_boundary_face_ids,
    ) = _build_boundary_diagnostics(
        simplified_boundary_loops,
        seams,
        simplified_open_meshes,
        final_meshes,
        part_names=output_part_names,
        part_keys=output_part_keys,
        height_mm=settings.height_mm,
        local_repair_records=local_boundary_repair_records,
    )

    part_count = len(final_meshes)
    for part_id, (vertices, faces, _colors) in enumerate(final_meshes):
        part_stats[part_id]["final_vertices"] = int(len(vertices))
        part_stats[part_id]["final_faces"] = int(len(faces))

    provenance_parts, provenance_diagnostic = derive_part_face_provenance(
        [len(mesh[1]) for mesh in final_meshes],
        repair_records,
        # Joint booleans rebuild face topology. Until a joint implementation
        # emits a fresh ancestry mask, pre-joint cap ranges are unsafe.
        topology_changed=bool(joint_records),
    )
    final_face_provenance = (
        np.concatenate(provenance_parts).astype(np.uint8, copy=False)
        if provenance_parts is not None
        else np.empty(0, dtype=np.uint8)
    )

    # Tripo's original seams define the source parts.  A normal import never
    # creates an arbitrary flat two-way cut; source part identity is the only
    # automatic partitioning signal.
    split_record: dict[str, object] | None = None

    final_vertices, final_faces, final_colors, final_face_parts = (
        _combine_part_meshes(final_meshes)
    )
    final_vertices = _center_and_floor(final_vertices)
    final_areas = triangle_areas(final_vertices, final_faces)
    topology = edge_topology(final_faces, len(final_vertices))
    if not topology["watertight"]:
        warnings.append(
            (
                "閉じていないパーツが残っています: "
                f"境界 {topology['boundary_edges']}, "
                f"非多様体 {topology['nonmanifold_edges']}"
            )
        )
    if transfer_p99_mm and max(transfer_p99_mm) > 0.5:
        warnings.append(
            (
                "パーツ内の頂点色転送距離p99が最大 "
                f"{max(transfer_p99_mm):.3f} mmです。面数を増やすと改善できます"
            )
        )
    final_level = MeshLevel(
        vertices_unit=final_vertices,
        faces=final_faces,
        vertex_colors=final_colors,
        areas_unit=final_areas,
        neighbors=face_neighbors_partial(final_faces, len(final_vertices)),
        face_part_ids=final_face_parts,
        face_provenance=final_face_provenance,
        part_names=tuple(output_part_names),
        part_keys=tuple(output_part_keys),
    )
    provenance_record = make_face_provenance_record(
        final_level,
        status=str(provenance_diagnostic.get("status", "unavailable")),
        reason=str(provenance_diagnostic.get("reason", "unknown")),
        includes_topology_edits=False,
    )

    preview_total = min(int(settings.preview_faces), len(final_faces))
    preview_targets = _allocate_part_targets(
        np.asarray([len(mesh[1]) for mesh in final_meshes], dtype=np.int64),
        preview_total,
    )
    preview_meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for part_id, ((vertices, faces, colors), target) in enumerate(
        zip(final_meshes, preview_targets, strict=True)
    ):
        emit(
            progress,
            "preview",
            0.62 + 0.24 * part_id / part_count,
            f"プレビュー {part_id + 1}/{part_count}: {int(target):,}面",
        )
        if int(target) < len(faces):
            try:
                preview_vertices, preview_faces = _simplify_mesh(
                    vertices,
                    faces,
                    colors,
                    int(target),
                    preserve_boundary=not solidify_parts,
                )
                preview_colors, _ = _transfer_colors(
                    vertices, colors, preview_vertices
                )
            except Exception as exc:
                warnings.append(
                    f"{output_part_names[part_id]}のプレビュー軽量化を省略しました: {exc}"
                )
                preview_vertices, preview_faces, preview_colors = (
                    vertices.copy(),
                    faces.copy(),
                    colors.copy(),
                )
        else:
            preview_vertices, preview_faces, preview_colors = (
                vertices.copy(),
                faces.copy(),
                colors.copy(),
            )
        preview_meshes.append(
            (preview_vertices, preview_faces, preview_colors)
        )
        part_stats[part_id]["preview_vertices"] = int(len(preview_vertices))
        part_stats[part_id]["preview_faces"] = int(len(preview_faces))

    (
        preview_vertices,
        preview_faces,
        preview_colors,
        preview_face_parts,
    ) = _combine_part_meshes(preview_meshes)
    preview_vertices = _center_and_floor(preview_vertices)
    preview_level = MeshLevel(
        vertices_unit=preview_vertices,
        faces=preview_faces,
        vertex_colors=preview_colors,
        areas_unit=triangle_areas(preview_vertices, preview_faces),
        neighbors=face_neighbors_partial(preview_faces, len(preview_vertices)),
        face_part_ids=preview_face_parts,
        part_names=tuple(output_part_names),
        part_keys=tuple(output_part_keys),
    )
    emit(progress, "done", 1.0, f"{part_count}パーツの準備完了")
    return PreparedGeometry(
        source=asset,
        final=final_level,
        preview=preview_level,
        clean_vertex_count=clean_vertex_count,
        clean_face_count=clean_face_count,
        removed_vertices=removed_vertices,
        removed_faces=removed_faces,
        topology=topology,
        source_area_unit=source_area,
        source_volume_unit=source_volume,
        simplified_area_unit=float(final_areas.sum()),
        simplified_volume_unit=signed_volume(final_vertices, final_faces),
        source_dimensions_unit=source_dimensions,
        warnings=warnings,
        part_names=tuple(output_part_names),
        part_keys=tuple(output_part_keys),
        part_stats=part_stats,
        assembly={
            "solidify_parts": solidify_parts,
            "repair_method": repair_method,
            "open_boundary_loop_count": int(len(boundary_loops)),
            "simplified_boundary_loop_count": int(
                len(simplified_boundary_loops)
            ),
            "matched_seam_count": int(len(seams)),
            "boundary_diagnostics": boundary_diagnostics,
            "matched_boundary_face_ids": matched_boundary_face_ids,
            "unmatched_boundary_face_ids": unmatched_boundary_face_ids,
            "unmatched_boundary_loop_count": int(
                len(unmatched_boundary_loops)
            ),
            "repaired_unmatched_boundary_count": int(
                len(local_boundary_repair_records)
            ),
            "repair_unmatched_boundaries": bool(
                settings.repair_unmatched_boundaries
            ),
            "repair_records": repair_records,
            "generated_surface_provenance": provenance_record,
            "joint_records": joint_records,
            "split_record": split_record,
            "source_clean_parts": int(source_clean_part_count),
            "cleaning_diagnostics": cleaning_diagnostics,
            "source_part_stats": source_part_stats,
            "reconstructed_bodies": reconstructed_bodies,
            "all_parts_watertight": bool(topology["watertight"]),
        },
    )


def prepare_geometry(
    asset: ObjAsset,
    settings: GeometrySettings,
    progress: ProgressCallback | None = None,
) -> PreparedGeometry:
    if settings.height_mm <= 0:
        raise EngineError("出力高さは0より大きくしてください")
    if bool(settings.adjust_face_count) and settings.target_faces < 1_000:
        raise EngineError("最終面数は1,000以上にしてください")
    # Only a source OBJ with two or more face-bearing ``o``/``g`` sections is
    # a real multipart asset. Markerless files and files with one decorative
    # marker must keep the established single-mesh path even when an older
    # settings file still contains solidify/split flags.
    if (
        bool(asset.has_explicit_parts)
        and len(asset.part_names) > 1
        and len(asset.face_part_ids) == len(asset.faces)
    ):
        return _prepare_geometry_parts(asset, settings, progress)
    warnings = list(asset.warnings)
    generic_repair_record: dict[str, object] | None = None
    working_vertices = asset.vertices.astype(np.float64)
    working_faces = np.asarray(asset.faces, dtype=np.int32)
    working_colors = asset.colors.astype(np.float64)
    is_gltf_single_mesh = asset.path.suffix.lower() in {".glb", ".gltf"}
    if is_gltf_single_mesh and bool(settings.solidify_parts):
        # Weld texture/material seams before component cleanup and QEM.  Once
        # an open seam has been decimated its two sides no longer share the same
        # samples, so a safe exact-coordinate repair would no longer be
        # possible.  This transaction does not add, remove, or reorder faces.
        emit(
            progress,
            "solidify",
            0.01,
            "GLBの同一座標テクスチャ継ぎ目を安全検証しています",
        )
        try:
            (
                working_vertices,
                working_faces,
                working_colors,
                generic_repair_record,
            ) = solidify_coincident_shells(
                working_vertices,
                working_faces,
                working_colors,
                # Raw Hi3D assets can contain tiny inward-wound closed islands.
                # Component cleanup removes those and coherent orientation fixes
                # the survivors.  The strict post-clean/QEM call below still
                # requires every remaining body to have positive volume.
                require_positive_volume=False,
            )
        except AssemblyError as exc:
            raise EngineError(
                "単一GLBを安全な閉立体へ正規化できませんでした。"
                "実際の欠損面は自動で大きく塞がず、元メッシュを保持します。\n"
                f"詳細: {exc}"
            ) from exc
        merged = int(generic_repair_record.get("merged_vertices", 0) or 0)
        if merged:
            warnings.append(
                "GLBのUV/テクスチャ継ぎ目で分離していた同一座標頂点を "
                f"{merged:,} 個統合しました（元の面数・面順・形状を保持）"
            )
    emit(progress, "clean", 0.02, "微小部品と面向きを整理しています")
    (
        clean_vertices,
        clean_faces,
        clean_colors,
        cleaning_diagnostic,
    ) = _clean_part(
        working_vertices,
        working_faces,
        working_colors,
        settings.min_component_faces,
    )
    cleaning_diagnostic["part_id"] = 0
    cleaning_diagnostic["part_key"] = (
        str(asset.part_keys[0]) if asset.part_keys else "0:OBJ全体"
    )
    cleaning_diagnostic["part_name"] = (
        str(asset.part_names[0]) if asset.part_names else "OBJ全体"
    )
    if bool(cleaning_diagnostic.get("component_filter_failed")):
        warnings.append("微小成分の整理に失敗したため元形状を保持しました")
    if bool(cleaning_diagnostic.get("component_filter_reverted")):
        warnings.append(
            "モデル全体が消えるため微小成分の除去を取り消しました"
        )
    if bool(cleaning_diagnostic.get("orientation_fallback_used")):
        topology_before = cleaning_diagnostic.get(
            "topology_before_orientation", {}
        )
        nonmanifold_edges = (
            int(topology_before.get("nonmanifold_edges", 0))
            if isinstance(topology_before, dict)
            else 0
        )
        warnings.append(
            "非多様体形状の面向き補正を安全に省略し、"
            f"整理後の{len(clean_faces):,}面・面順序・頂点色を保持しました"
            f"（非多様体辺 {nonmanifold_edges:,}）"
        )
    removed_vertices = asset.original_vertex_count - len(clean_vertices)
    removed_faces = asset.original_face_count - len(clean_faces)
    if removed_faces:
        warnings.append(f"微小な孤立形状など {removed_faces:,}面を除去しました")
    unit_vertices, clean_faces = _orient_unit(
        clean_vertices, clean_faces, settings.up_axis, settings.mirror_x
    )
    source_dimensions = np.ptp(unit_vertices, axis=0)
    source_areas = triangle_areas(unit_vertices, clean_faces)
    source_area = float(source_areas.sum())
    source_volume = signed_volume(unit_vertices, clean_faces)

    target = (
        min(int(settings.target_faces), len(clean_faces))
        if bool(settings.adjust_face_count)
        else len(clean_faces)
    )
    message = (
        f"形状の面数を {len(clean_faces):,} → {target:,} 面へ調整しています"
        if settings.adjust_face_count
        else f"元形状の {len(clean_faces):,} 面を保持しています"
    )
    emit(progress, "simplify", 0.22, message)
    final_vertices, final_faces = _simplify_mesh(unit_vertices, clean_faces, clean_colors, target)
    final_colors, transfer_stats = _transfer_colors(unit_vertices, clean_colors, final_vertices)
    final_vertices = _center_and_floor(final_vertices)
    if signed_volume(final_vertices, final_faces) < 0.0:
        final_faces[:, [1, 2]] = final_faces[:, [2, 1]]
    if generic_repair_record is not None:
        # Cleanup and optional face-count adjustment run after the seam weld.
        # Re-validate the exact final mesh so a later QEM/library regression can
        # never turn an accepted repair into an open 3MF.  Watertight input is
        # an identity path here; no second colour merge is performed.
        try:
            (
                final_vertices,
                final_faces,
                final_colors,
                final_validation_record,
            ) = solidify_coincident_shells(
                final_vertices,
                final_faces,
                final_colors,
            )
        except AssemblyError as exc:
            raise EngineError(
                "単一GLBの閉立体化後検証に失敗したため、元メッシュへ戻します。\n"
                f"詳細: {exc}"
            ) from exc
        generic_repair_record["final_validation"] = final_validation_record
        simplification_applied = bool(int(target) < int(len(clean_faces)))
        generic_repair_record["simplification_applied"] = simplification_applied
        generic_repair_record["source_triangle_geometry_preserved"] = bool(
            not simplification_applied
        )
        generic_repair_record["final_face_count"] = int(len(final_faces))
        generic_repair_record["final_vertex_count"] = int(len(final_vertices))
        for validation_key in (
            "body_count",
            "minimum_body_volume_unit3",
            "maximum_body_volume_unit3",
            "positive_volume_validated",
        ):
            if validation_key in final_validation_record:
                generic_repair_record[validation_key] = final_validation_record[
                    validation_key
                ]
    emit(progress, "validate", 0.62, "最終メッシュの閉じ方を検証しています")
    topology = edge_topology(final_faces, len(final_vertices))
    if not topology["watertight"]:
        warnings.append(
            f"閉じていない形状です: 境界 {topology['boundary_edges']}, 非多様体 {topology['nonmanifold_edges']}"
        )
    if topology["inconsistent_winding_edges"]:
        warnings.append(f"面向き不整合が {topology['inconsistent_winding_edges']} 辺残っています")
    if transfer_stats["p99"] * settings.height_mm > 0.5:
        warnings.append(
            f"頂点色転送距離p99が {transfer_stats['p99'] * settings.height_mm:.3f} mmです。面数を増やすと改善できます"
        )
    final_areas = triangle_areas(final_vertices, final_faces)
    final_level = MeshLevel(
        vertices_unit=final_vertices,
        faces=final_faces,
        vertex_colors=final_colors,
        areas_unit=final_areas,
        neighbors=face_neighbors(final_faces, len(final_vertices)),
        face_part_ids=np.zeros(len(final_faces), dtype=np.int16),
        part_names=(
            tuple(asset.part_names)
            if len(asset.part_names) == 1
            else ("OBJ全体",)
        ),
        part_keys=(
            tuple(asset.part_keys)
            if len(asset.part_keys) == 1
            else ("0:OBJ全体",)
        ),
        face_provenance=(
            np.zeros(len(final_faces), dtype=np.uint8)
            if generic_repair_record is not None
            else np.empty(0, dtype=np.uint8)
        ),
    )

    preview_target = min(int(settings.preview_faces), len(final_faces))
    emit(progress, "preview", 0.74, f"プレビュー用 {preview_target:,} 面を準備しています")
    if preview_target < len(final_faces):
        try:
            preview_vertices, preview_faces = _simplify_mesh(
                final_vertices, final_faces, final_colors, preview_target
            )
            preview_colors, _ = _transfer_colors(final_vertices, final_colors, preview_vertices)
            preview_vertices = _center_and_floor(preview_vertices)
        except Exception as exc:
            warnings.append(f"プレビュー軽量化を省略しました: {exc}")
            preview_vertices, preview_faces, preview_colors = (
                final_vertices.copy(),
                final_faces.copy(),
                final_colors.copy(),
            )
    else:
        preview_vertices, preview_faces, preview_colors = (
            final_vertices.copy(),
            final_faces.copy(),
            final_colors.copy(),
        )
    preview_level = MeshLevel(
        vertices_unit=preview_vertices,
        faces=preview_faces,
        vertex_colors=preview_colors,
        areas_unit=triangle_areas(preview_vertices, preview_faces),
        neighbors=face_neighbors(preview_faces, len(preview_vertices)),
        face_part_ids=np.zeros(len(preview_faces), dtype=np.int16),
        part_names=final_level.part_names,
        part_keys=final_level.part_keys,
    )
    emit(progress, "done", 1.0, "メッシュ準備完了")
    cleaning_assembly = (
        {"cleaning_diagnostics": [cleaning_diagnostic]}
        if bool(cleaning_diagnostic.get("orientation_fallback_used"))
        or bool(cleaning_diagnostic.get("component_filter_failed"))
        or bool(cleaning_diagnostic.get("component_filter_reverted"))
        else {}
    )
    if generic_repair_record is not None:
        provenance_record = make_face_provenance_record(
            final_level,
            status="fresh",
            reason="coincident_seam_weld_preserved_face_order",
            includes_topology_edits=False,
        )
        cleaning_assembly.update(
            {
                "solidify_parts": bool(settings.solidify_parts),
                "single_mesh_generic": True,
                "auto_texture_seam_weld": False,
                "repair_method": str(
                    generic_repair_record.get("method", "already_watertight")
                ),
                "repair_records": [generic_repair_record],
                "source_clean_parts": 1,
                "body_count": int(
                    generic_repair_record.get("body_count", 1) or 1
                ),
                "generated_surface_provenance": provenance_record,
                "all_parts_watertight": bool(topology["watertight"]),
            }
        )
    return PreparedGeometry(
        source=asset,
        final=final_level,
        preview=preview_level,
        clean_vertex_count=len(clean_vertices),
        clean_face_count=len(clean_faces),
        removed_vertices=removed_vertices,
        removed_faces=removed_faces,
        topology=topology,
        source_area_unit=source_area,
        source_volume_unit=source_volume,
        simplified_area_unit=float(final_areas.sum()),
        simplified_volume_unit=signed_volume(final_vertices, final_faces),
        source_dimensions_unit=source_dimensions,
        warnings=warnings,
        part_names=final_level.part_names,
        part_keys=final_level.part_keys,
        part_stats=[
            {
                "id": 0,
                "key": final_level.part_keys[0],
                "name": final_level.part_names[0],
                "source_vertices": int(asset.original_vertex_count),
                "source_faces": int(asset.original_face_count),
                "clean_vertices": int(len(clean_vertices)),
                "clean_faces": int(len(clean_faces)),
                "final_vertices": int(len(final_vertices)),
                "final_faces": int(len(final_faces)),
                "preview_vertices": int(len(preview_vertices)),
                "preview_faces": int(len(preview_faces)),
                "cleaning_orientation_method": str(
                    cleaning_diagnostic.get("orientation_method", "unknown")
                ),
                "cleaning_orientation_fallback": bool(
                    cleaning_diagnostic.get("orientation_fallback_used")
                ),
            }
        ],
        assembly=cleaning_assembly,
    )


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float64)
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    xyz = linear @ np.asarray(
        [
            [0.4124564, 0.2126729, 0.0193339],
            [0.3575761, 0.7151522, 0.1191920],
            [0.1804375, 0.0721750, 0.9503041],
        ]
    )
    xyz /= np.asarray([0.95047, 1.0, 1.08883])
    delta = 6.0 / 29.0
    f = np.where(xyz > delta**3, np.cbrt(xyz), xyz / (3.0 * delta**2) + 4.0 / 29.0)
    return np.column_stack(
        (116.0 * f[:, 1] - 16.0, 500.0 * (f[:, 0] - f[:, 1]), 200.0 * (f[:, 1] - f[:, 2]))
    )


def lab_to_srgb(lab: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[:, 0] + 16.0) / 116.0
    fx = fy + lab[:, 1] / 500.0
    fz = fy - lab[:, 2] / 200.0
    delta = 6.0 / 29.0

    def inverse(value: np.ndarray) -> np.ndarray:
        return np.where(value > delta, value**3, 3.0 * delta**2 * (value - 4.0 / 29.0))

    xyz = np.column_stack((inverse(fx), inverse(fy), inverse(fz)))
    xyz *= np.asarray([0.95047, 1.0, 1.08883])
    linear = xyz @ np.asarray(
        [
            [3.2404542, -0.9692660, 0.0556434],
            [-1.5371385, 1.8760108, -0.2040259],
            [-0.4985314, 0.0415560, 1.0572252],
        ]
    )
    return np.where(
        linear <= 0.0031308,
        12.92 * linear,
        1.055 * np.power(np.maximum(linear, 0.0), 1.0 / 2.4) - 0.055,
    )


def apply_tone(colors: np.ndarray, settings: ToneSettings) -> np.ndarray:
    if settings.white_point <= settings.black_point + 0.005:
        raise EngineError("白点は黒点より十分大きくしてください")
    rgb = np.clip(
        (np.asarray(colors, dtype=np.float64) - settings.black_point)
        / (settings.white_point - settings.black_point),
        0.0,
        1.0,
    )
    gamma = max(0.05, float(settings.gamma))
    rgb = np.power(rgb, 1.0 / gamma)
    rgb = np.clip((rgb - 0.5) * float(settings.contrast) + 0.5, 0.0, 1.0)
    if abs(settings.saturation - 1.0) > 1e-9:
        lab = srgb_to_lab(rgb)
        lab[:, 1:3] *= float(settings.saturation)
        rgb = np.clip(lab_to_srgb(lab), 0.0, 1.0)
    return rgb


def _smooth_labels(
    indices: np.ndarray,
    face_lab: np.ndarray,
    palette_lab: np.ndarray,
    areas_mm2: np.ndarray,
    neighbors: np.ndarray | None,
    settings: ToneSettings,
) -> tuple[np.ndarray, int]:
    if not settings.smoothing or neighbors is None:
        return indices, 0
    result = indices.copy()
    total_changed = 0
    protected_family = np.zeros(len(palette_lab), dtype=bool)
    if settings.pink_protection:
        protected_family[PINK_STATES] = True
    for _ in range(2):
        valid_neighbors = neighbors >= 0
        nearby = np.full(neighbors.shape, -1, dtype=np.int16)
        nearby[valid_neighbors] = result[neighbors[valid_neighbors]]
        a, b, c = nearby[:, 0], nearby[:, 1], nearby[:, 2]
        majority = np.where(
            (a >= 0) & (a == b),
            a,
            np.where(
                (a >= 0) & (a == c),
                a,
                np.where((b >= 0) & (b == c), b, -1),
            ),
        )
        all_three = (a >= 0) & (a == b) & (b == c)
        valid = majority >= 0
        same_family = np.ones(len(result), dtype=bool)
        if settings.pink_protection:
            same_family[valid] = (
                protected_family[result[valid]]
                == protected_family[majority[valid]]
            )
        current_error = np.linalg.norm(face_lab - palette_lab[result], axis=1)
        alternative_error = np.full(len(result), np.inf)
        alternative_error[valid] = np.linalg.norm(face_lab[valid] - palette_lab[majority[valid]], axis=1)
        change = (
            valid
            & same_family
            & (majority != result)
            & (
                all_three
                | (
                    (areas_mm2 < settings.smoothing_max_area_mm2)
                    & (alternative_error <= current_error + settings.smoothing_delta_e_slack)
                )
            )
        )
        changed = int(np.count_nonzero(change))
        if not changed:
            break
        result[change] = majority[change]
        total_changed += changed
    return result, total_changed


def _apply_black_free_gradient(
    indices: np.ndarray,
    face_lab: np.ndarray,
    palette_lab: np.ndarray,
    palette: PaletteSettings,
) -> tuple[np.ndarray, int]:
    """Replace automatic black-mix labels with the nearest red-brown label."""

    if not palette.black_free_gradient_enabled:
        return indices, 0
    try:
        black_slot, red_slot, brown_slot = validate_black_free_slots(
            palette.black_free_black_slot,
            palette.black_free_red_slot,
            palette.black_free_brown_slot,
        )
    except ValueError as exc:
        raise EngineError(str(exc)) from exc
    forbidden = black_containing_mixed_states(
        palette.palette_state_count,
        black_slot,
    )
    candidates = np.asarray(
        black_free_replacement_states(
            palette.palette_state_count,
            red_slot,
            brown_slot,
            palette.enabled_states,
        ),
        dtype=np.int8,
    )
    if not len(candidates):
        raise EngineError(
            "黒混色なしグラデーションには赤・茶または赤+茶の"
            "自動配色候補を1色以上有効にしてください"
        )
    selected = np.flatnonzero(np.isin(indices, forbidden))
    if not len(selected):
        return indices, 0
    result = indices.astype(np.int8, copy=True)
    candidate_lab = palette_lab[candidates]
    for start in range(0, len(selected), 25_000):
        chunk = selected[start : start + 25_000]
        delta = face_lab[chunk, None, :] - candidate_lab[None, :, :]
        nearest = np.argmin(np.sum(delta * delta, axis=2), axis=1)
        result[chunk] = candidates[nearest]
    return result, int(len(selected))


def recolor_level(
    level: MeshLevel,
    height_mm: float,
    tone: ToneSettings,
    palette: PaletteSettings,
) -> ColorResult:
    if len(palette.enabled_states) != PALETTE_STATE_COUNT:
        raise EngineError(
            f"パレット有効状態は{PALETTE_STATE_COUNT}個必要です"
        )
    palette_hex, palette_rgb = build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    del palette_hex
    enabled = np.asarray(palette.enabled_states, dtype=bool)
    neutral_candidates = NEUTRAL_STATES[enabled[NEUTRAL_STATES]]
    pink_candidates = PINK_STATES[enabled[PINK_STATES]]
    if len(neutral_candidates) == 0:
        raise EngineError("通常色パレットを1色以上有効にしてください")
    if tone.pink_protection and len(pink_candidates) == 0:
        raise EngineError("F4系保護にはF4を含むパレットを1色以上有効にしてください")

    tone_vertex = apply_tone(level.vertex_colors, tone)
    source_face_rgb = level.vertex_colors[level.faces].mean(axis=1)
    tone_face_rgb = tone_vertex[level.faces].mean(axis=1)
    face_lab = srgb_to_lab(tone_face_rgb)
    palette_lab = srgb_to_lab(palette_rgb)
    indices = np.empty(len(level.faces), dtype=np.int8)
    if tone.pink_protection:
        pink_score = tone_face_rgb[:, 0] - 0.5 * (tone_face_rgb[:, 1] + tone_face_rgb[:, 2])
        pink_mask = pink_score > tone.pink_threshold
        groups: Iterable[tuple[np.ndarray, np.ndarray]] = (
            (~pink_mask, neutral_candidates),
            (pink_mask, pink_candidates),
        )
    else:
        all_candidates = np.flatnonzero(enabled).astype(np.int8)
        groups = ((np.ones(len(level.faces), dtype=bool), all_candidates),)
    for mask, candidates in groups:
        if not np.any(mask):
            continue
        sample_indices = np.flatnonzero(mask)
        candidate_lab = palette_lab[candidates]
        # A 450k-face model and 16 colours would otherwise allocate roughly
        # 385 MiB for one float64 distance tensor.  Chunking keeps peak memory
        # bounded while producing the exact same nearest-colour assignment.
        for start in range(0, len(sample_indices), 25_000):
            chunk_indices = sample_indices[start : start + 25_000]
            delta = (
                face_lab[chunk_indices, None, :]
                - candidate_lab[None, :, :]
            )
            nearest = np.argmin(np.sum(delta * delta, axis=2), axis=1)
            indices[chunk_indices] = candidates[nearest]
    areas_mm2 = level.areas_unit * float(height_mm) ** 2
    indices, smoothed = _smooth_labels(
        indices, face_lab, palette_lab, areas_mm2, level.neighbors, tone
    )
    indices, black_free_remapped = _apply_black_free_gradient(
        indices,
        face_lab,
        palette_lab,
        palette,
    )
    target_rgb = palette_rgb[indices]
    delta_e = np.linalg.norm(face_lab - palette_lab[indices], axis=1)
    counts = np.bincount(indices, minlength=PALETTE_STATE_COUNT)
    area_by_state = np.bincount(
        indices, weights=areas_mm2, minlength=PALETTE_STATE_COUNT
    )
    fractions = area_by_state / max(float(area_by_state.sum()), 1e-12)
    return ColorResult(
        tone_vertex_rgb=tone_vertex,
        source_face_rgb=source_face_rgb,
        palette_indices=indices,
        target_face_rgb=target_rgb,
        delta_e=delta_e,
        smoothed_faces=smoothed,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=float(fractions[PINK_STATES].sum()),
        black_free_remapped_faces=black_free_remapped,
    )


def _local_part_neighbors(
    neighbors: np.ndarray | None,
    selected_faces: np.ndarray,
    face_count: int,
) -> np.ndarray | None:
    if neighbors is None:
        return None
    raw = np.asarray(neighbors)
    if raw.shape != (face_count, 3):
        return None
    lookup = np.full(face_count, -1, dtype=np.int32)
    lookup[selected_faces] = np.arange(len(selected_faces), dtype=np.int32)
    chosen = raw[selected_faces]
    result = np.full(chosen.shape, -1, dtype=np.int32)
    valid = (chosen >= 0) & (chosen < face_count)
    result[valid] = lookup[chosen[valid]]
    return result


def recolor_level_parts(
    level: MeshLevel,
    height_mm: float,
    tone: ToneSettings,
    palette: PaletteSettings,
    part_palettes: dict[str, PaletteSettings] | None,
) -> ColorResult:
    """Assign local 0..15 states using the palette resolved for each OBJ part."""

    if not part_palettes:
        return recolor_level(level, height_mm, tone, palette)
    settings = AppSettings(
        tone=tone,
        palette=palette,
        part_palettes=dict(part_palettes),
    )
    layout = validate_part_layout(level)
    palettes = resolve_part_palette_settings(settings, layout)
    palette_tables = build_part_palette_rgb_tables(settings, layout)
    tone_vertex = apply_tone(level.vertex_colors, tone)
    source_face_rgb = level.vertex_colors[level.faces].mean(axis=1)
    tone_face_rgb = tone_vertex[level.faces].mean(axis=1)
    face_lab = srgb_to_lab(tone_face_rgb)
    areas_mm2 = level.areas_unit * float(height_mm) ** 2
    indices = np.empty(len(level.faces), dtype=np.int8)
    target_rgb = np.empty((len(level.faces), 3), dtype=np.float64)
    delta_e = np.empty(len(level.faces), dtype=np.float64)
    total_smoothed = 0
    total_black_free_remapped = 0
    part_metrics: list[dict[str, object]] = []

    for part_id, (part_key, part_palette) in enumerate(
        zip(layout.part_keys, palettes, strict=True)
    ):
        selected = np.flatnonzero(layout.face_part_ids == part_id)
        if not len(selected):
            continue
        enabled = np.asarray(part_palette.enabled_states, dtype=bool)
        if enabled.shape != (PALETTE_STATE_COUNT,):
            raise EngineError(
                f"{part_key}: パレット有効状態は{PALETTE_STATE_COUNT}個必要です"
            )
        neutral_candidates = NEUTRAL_STATES[enabled[NEUTRAL_STATES]]
        pink_candidates = PINK_STATES[enabled[PINK_STATES]]
        if not len(neutral_candidates):
            raise EngineError(f"{part_key}: 通常色を1色以上有効にしてください")
        if tone.pink_protection and not len(pink_candidates):
            raise EngineError(
                f"{part_key}: F4系保護にはF4系を1色以上有効にしてください"
            )
        local_lab = face_lab[selected]
        local_rgb = tone_face_rgb[selected]
        palette_lab = srgb_to_lab(palette_tables[part_id])
        local_indices = np.empty(len(selected), dtype=np.int8)
        if tone.pink_protection:
            pink_score = local_rgb[:, 0] - 0.5 * (
                local_rgb[:, 1] + local_rgb[:, 2]
            )
            groups: Iterable[tuple[np.ndarray, np.ndarray]] = (
                (pink_score <= tone.pink_threshold, neutral_candidates),
                (pink_score > tone.pink_threshold, pink_candidates),
            )
        else:
            groups = (
                (
                    np.ones(len(selected), dtype=bool),
                    np.flatnonzero(enabled).astype(np.int8),
                ),
            )
        for mask, candidates in groups:
            sample_indices = np.flatnonzero(mask)
            if not len(sample_indices):
                continue
            candidate_lab = palette_lab[candidates]
            for start in range(0, len(sample_indices), 25_000):
                chunk = sample_indices[start : start + 25_000]
                differences = (
                    local_lab[chunk, None, :] - candidate_lab[None, :, :]
                )
                nearest = np.argmin(
                    np.sum(differences * differences, axis=2), axis=1
                )
                local_indices[chunk] = candidates[nearest]
        local_neighbors = _local_part_neighbors(
            level.neighbors, selected, len(level.faces)
        )
        local_indices, smoothed = _smooth_labels(
            local_indices,
            local_lab,
            palette_lab,
            areas_mm2[selected],
            local_neighbors,
            tone,
        )
        local_indices, black_free_remapped = _apply_black_free_gradient(
            local_indices,
            local_lab,
            palette_lab,
            part_palette,
        )
        total_smoothed += smoothed
        total_black_free_remapped += black_free_remapped
        local_delta = np.linalg.norm(
            local_lab - palette_lab[local_indices], axis=1
        )
        indices[selected] = local_indices
        target_rgb[selected] = palette_tables[part_id, local_indices]
        delta_e[selected] = local_delta
        weights = areas_mm2[selected]
        part_metrics.append(
            {
                "part_id": part_id,
                "part_key": part_key,
                "face_count": int(len(selected)),
                "surface_area_fraction": float(
                    weights.sum() / max(float(areas_mm2.sum()), 1e-12)
                ),
                "area_weighted_delta_e76_mean": float(
                    np.average(local_delta, weights=weights)
                ),
                "area_weighted_delta_e76_p90": weighted_quantile(
                    local_delta, weights, 0.90
                ),
                "black_free_remapped_faces": black_free_remapped,
            }
        )

    counts = np.bincount(indices, minlength=PALETTE_STATE_COUNT)
    area_by_state = np.bincount(
        indices, weights=areas_mm2, minlength=PALETTE_STATE_COUNT
    )
    fractions = area_by_state / max(float(area_by_state.sum()), 1e-12)
    return ColorResult(
        tone_vertex_rgb=tone_vertex,
        source_face_rgb=source_face_rgb,
        palette_indices=indices,
        target_face_rgb=target_rgb,
        delta_e=delta_e,
        smoothed_faces=total_smoothed,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=float(fractions[PINK_STATES].sum()),
        black_free_remapped_faces=total_black_free_remapped,
        part_metrics=part_metrics,
    )


def apply_palette_overrides(
    level: MeshLevel,
    height_mm: float,
    palette: PaletteSettings,
    colors: ColorResult,
    manual_overrides: np.ndarray,
    *,
    remap_out_of_range: bool = True,
) -> ColorResult:
    """Overlay sparse manual face states on an automatic colour result.

    ``manual_overrides`` uses ``-1`` for the current automatic assignment and
    ``0..15`` for an explicit Full Spectrum palette state. Explicit assignments
    remain valid even when that state is disabled for *automatic* assignment.
    """

    overrides = np.asarray(manual_overrides)
    face_count = len(level.faces)
    if overrides.ndim != 1 or len(overrides) != face_count:
        raise EngineError(
            f"手修正データの面数が一致しません: {overrides.shape} / ({face_count},)"
        )
    if not np.issubdtype(overrides.dtype, np.integer):
        raise EngineError("手修正データは整数配列で指定してください")
    if len(overrides) and (
        int(overrides.min()) < -1
        or int(overrides.max()) >= PALETTE_STATE_COUNT
    ):
        raise EngineError(
            f"手修正の色番号は -1 または 0～{PALETTE_STATE_COUNT - 1} "
            "である必要があります"
        )
    overrides = overrides.astype(np.int8, copy=False)
    _palette_hex, palette_rgb = build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    if remap_out_of_range:
        too_high = overrides >= palette.palette_state_count
        if np.any(too_high):
            overrides = overrides.copy()
            source_states = np.unique(overrides[too_high])
            candidates = palette_rgb[: palette.palette_state_count]
            for source_state in source_states:
                delta = candidates - palette_rgb[int(source_state)]
                replacement = int(np.argmin(np.sum(delta * delta, axis=1)))
                overrides[overrides == source_state] = replacement
    automatic = np.asarray(colors.palette_indices)
    if automatic.shape != (face_count,):
        raise EngineError("自動色結果の面数が最終メッシュと一致しません")
    if np.asarray(colors.tone_vertex_rgb).shape != (len(level.vertices_unit), 3):
        raise EngineError("色調整後の頂点色数が最終メッシュと一致しません")

    mask = overrides >= 0
    indices = automatic.astype(np.int8, copy=True)
    indices[mask] = overrides[mask]
    tone_face_rgb = np.asarray(colors.tone_vertex_rgb)[level.faces].mean(axis=1)
    face_lab = srgb_to_lab(tone_face_rgb)
    palette_lab = srgb_to_lab(palette_rgb)
    target_rgb = palette_rgb[indices]
    delta_e = np.linalg.norm(face_lab - palette_lab[indices], axis=1)
    areas_mm2 = level.areas_unit * float(height_mm) ** 2
    counts = np.bincount(indices, minlength=PALETTE_STATE_COUNT)
    area_by_state = np.bincount(
        indices, weights=areas_mm2, minlength=PALETTE_STATE_COUNT
    )
    fractions = area_by_state / max(float(area_by_state.sum()), 1e-12)
    return ColorResult(
        tone_vertex_rgb=colors.tone_vertex_rgb,
        source_face_rgb=colors.source_face_rgb,
        palette_indices=indices,
        target_face_rgb=target_rgb,
        delta_e=delta_e,
        smoothed_faces=colors.smoothed_faces,
        palette_face_counts=counts,
        palette_area_fractions=fractions,
        pink_area_fraction=float(fractions[PINK_STATES].sum()),
        manual_override_faces=int(np.count_nonzero(mask)),
        black_free_remapped_faces=colors.black_free_remapped_faces,
    )


def apply_palette_overrides_parts(
    level: MeshLevel,
    height_mm: float,
    palette: PaletteSettings,
    part_palettes: dict[str, PaletteSettings] | None,
    colors: ColorResult,
    manual_overrides: np.ndarray,
) -> ColorResult:
    """Apply local state IDs and resolve their display colour per OBJ part."""

    settings = AppSettings(
        palette=palette,
        part_palettes=dict(part_palettes or {}),
    )
    layout = validate_part_layout(level)
    resolved_palettes = resolve_part_palette_settings(settings, layout)
    safe_overrides = np.asarray(manual_overrides).copy()
    if (
        safe_overrides.shape == (len(level.faces),)
        and np.issubdtype(safe_overrides.dtype, np.integer)
    ):
        for part_id, part_palette in enumerate(resolved_palettes):
            selected = (
                (layout.face_part_ids == part_id)
                & (safe_overrides >= part_palette.palette_state_count)
            )
            if not np.any(selected):
                continue
            _hex, part_rgb = build_palette_rgb(
                part_palette.physical_hex,
                part_palette.mix_hex_overrides,
                part_palette.mix_ratios_b,
                part_palette.secondary_mix_ratios_b,
            )
            candidates = part_rgb[: part_palette.palette_state_count]
            for source_state in np.unique(safe_overrides[selected]):
                if int(source_state) < 0 or int(source_state) >= PALETTE_STATE_COUNT:
                    continue
                delta = candidates - part_rgb[int(source_state)]
                replacement = int(np.argmin(np.sum(delta * delta, axis=1)))
                safe_overrides[selected & (safe_overrides == source_state)] = replacement

    result = apply_palette_overrides(
        level,
        height_mm,
        palette,
        colors,
        safe_overrides,
        remap_out_of_range=False,
    )
    if not part_palettes:
        return result
    tables = build_part_palette_rgb_tables(settings, layout)
    indices = np.asarray(result.palette_indices, dtype=np.int8)
    target_rgb = tables[layout.face_part_ids, indices]
    face_lab = srgb_to_lab(
        np.asarray(result.tone_vertex_rgb)[level.faces].mean(axis=1)
    )
    target_lab = srgb_to_lab(target_rgb)
    delta_e = np.linalg.norm(face_lab - target_lab, axis=1)
    areas_mm2 = level.areas_unit * float(height_mm) ** 2
    part_metrics: list[dict[str, object]] = []
    for part_id, part_key in enumerate(layout.part_keys):
        selected = np.flatnonzero(layout.face_part_ids == part_id)
        if not len(selected):
            continue
        weights = areas_mm2[selected]
        local_delta = delta_e[selected]
        part_metrics.append(
            {
                "part_id": part_id,
                "part_key": part_key,
                "face_count": int(len(selected)),
                "surface_area_fraction": float(
                    weights.sum() / max(float(areas_mm2.sum()), 1e-12)
                ),
                "area_weighted_delta_e76_mean": float(
                    np.average(local_delta, weights=weights)
                ),
                "area_weighted_delta_e76_p90": weighted_quantile(
                    local_delta, weights, 0.90
                ),
            }
        )
    return ColorResult(
        tone_vertex_rgb=result.tone_vertex_rgb,
        source_face_rgb=result.source_face_rgb,
        palette_indices=result.palette_indices,
        target_face_rgb=target_rgb,
        delta_e=delta_e,
        smoothed_faces=result.smoothed_faces,
        palette_face_counts=result.palette_face_counts,
        palette_area_fractions=result.palette_area_fractions,
        pink_area_fraction=result.pink_area_fraction,
        manual_override_faces=result.manual_override_faces,
        black_free_remapped_faces=result.black_free_remapped_faces,
        part_metrics=part_metrics,
    )


def _make_root_model(
    title: str,
    description: str,
    part_count: int = 1,
) -> bytes:
    if part_count < 1:
        raise EngineError("3MFには1個以上のパーツが必要です")
    today = date.today().isoformat()
    parent_id = part_count + 1
    components = "\n".join(
        (
            '    <component p:path="/3D/Objects/object_1.model" '
            f'objectid="{object_id}" '
            f'p:UUID="00010000-b206-40ff-9872-{object_id:012d}" '
            'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
        )
        for object_id in range(1, part_count + 1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
 <metadata name="Application">BambuStudio-2.3.5</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="CreationDate">{today}</metadata>
 <metadata name="ModificationDate">{today}</metadata>
 <metadata name="Title">{html.escape(title)}</metadata>
 <metadata name="Description">{html.escape(description)}</metadata>
 <resources>
  <object id="{parent_id}" p:UUID="00000001-61cb-4c03-9d28-80fed5dfa1dc" type="model">
   <components>
{components}
   </components>
  </object>
 </resources>
 <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">
  <item objectid="{parent_id}" p:UUID="00000002-b1ec-4553-aec9-835e5b724bb4" transform="1 0 0 0 1 0 0 0 1 128 128 0" printable="1"/>
 </build>
</model>
'''.encode("utf-8")


def _make_model_settings(
    name: str,
    face_count: int,
    removed_faces: int,
    part_names: tuple[str, ...] | list[str] | None = None,
    part_face_counts: tuple[int, ...] | list[int] | None = None,
    source_file: str | None = None,
) -> bytes:
    safe_name = html.escape(name)
    # Never write a host path into the portable 3MF.  The source basename is
    # enough for traceability and preserves .glb/.gltf instead of pretending
    # every import came from OBJ.
    safe_source_file = html.escape(
        Path(source_file).name if source_file else f"{name}.obj"
    )
    names = tuple(part_names or (name,))
    counts = tuple(int(value) for value in (part_face_counts or (face_count,)))
    if len(names) != len(counts) or not names:
        raise EngineError("3MFパーツ名と面数が一致しません")
    parent_id = len(names) + 1
    removed_by_part = [0] * len(names)
    if removed_faces > 0 and face_count > 0:
        allocated = 0
        for index, count in enumerate(counts[:-1]):
            value = int(round(removed_faces * count / face_count))
            removed_by_part[index] = value
            allocated += value
        removed_by_part[-1] = max(0, int(removed_faces) - allocated)
    part_blocks: list[str] = []
    for index, (part_name, count, part_removed) in enumerate(
        zip(names, counts, removed_by_part, strict=True), start=1
    ):
        safe_part_name = html.escape(part_name)
        part_blocks.append(
            f'''    <part id="{index}" subtype="normal_part">
      <metadata key="name" value="{safe_part_name}"/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_file" value="{safe_source_file}"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="{index - 1}"/>
      <metadata key="source_offset_x" value="0"/>
      <metadata key="source_offset_y" value="0"/>
      <metadata key="source_offset_z" value="0"/>
      <metadata key="extruder" value="1"/>
      <mesh_stat face_count="{count}" edges_fixed="0" degenerate_facets="0" facets_removed="{part_removed}" facets_reversed="0" backwards_edges="0"/>
    </part>'''
        )
    parts_xml = "\n".join(part_blocks)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="{parent_id}">
    <metadata key="name" value="{safe_name}"/>
    <metadata key="extruder" value="1"/>
    <metadata face_count="{face_count}"/>
{parts_xml}
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value="Full Spectrum 4 Filaments"/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <model_instance>
      <metadata key="object_id" value="{parent_id}"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="1"/>
    </model_instance>
  </plate>
</config>
'''.encode("utf-8")


def _make_project_settings(palette: PaletteSettings) -> bytes:
    physical = [normalize_hex(value) for value in palette.physical_hex]
    surface_shell_enabled = bool(
        palette.surface_shell_enabled and SURFACE_SHELL_OUTPUT_ENABLED
    )
    definitions = make_portable_mixed_definitions(
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
        palette.palette_state_count,
        palette.output_mix_ratios_b,
        surface_shell_enabled,
        physical,
    )
    config = {
        "print_settings_id": "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)",
        "printer_settings_id": "Snapmaker U1 (0.4 nozzle)",
        "printer_model": "Snapmaker U1",
        "printer_variant": "0.4",
        "nozzle_diameter": ["0.4", "0.4", "0.4", "0.4"],
        "layer_height": "0.08",
        "initial_layer_print_height": "0.2",
        "adaptive_layer_height": "0",
        "filament_colour": physical,
        "filament_multi_colors": physical,
        "filament_colour_mode": ["0", "0", "0", "0"],
        "filament_settings_id": [generic_filament_profile(palette.material)] * 4,
        "mixed_filament_definitions": definitions,
        "mixed_filament_gradient_mode": "0",
        "mixed_filament_height_lower_bound": "0.04",
        "mixed_filament_height_upper_bound": "0.16",
        "mixed_filament_advanced_dithering": "0",
        "mixed_filament_pointillism_pixel_size": "0",
        "mixed_filament_pointillism_line_gap": "0",
        "mixed_filament_component_bias_enabled": "0",
        "mixed_filament_surface_indentation": "0",
    }
    if surface_shell_enabled:
        # The shell math is exactly two equal path widths.  Do not inherit an
        # Arachne/0.42+0.45 profile whose unequal paths would change the
        # calibrated physical share and make `...,12` no longer mean 25%.
        #
        # Snapmaker Orca's U1 preset normally leaves both support tools at
        # "current" (0) and enables flush-into-support.  That makes support a
        # wiping override.  Orca 2.3.5 disables grouped-perimeter splitting
        # whenever any wiping override exists, so the virtual mixed-state ID
        # may escape as an impossible T4+ command.  Pin shell-mode support to
        # the brightest *physical* tool and keep every purge-to-print override
        # disabled while this grouped-wall representation is active.
        # Support generation itself remains user-controlled in Orca.
        extremes = _surface_shell_extreme_slots(physical)
        support_filament = (extremes[1] + 1) if extremes is not None else 2
        config.update(
            {
                "wall_loops": "2",
                "wall_generator": "classic",
                "outer_wall_line_width": "0.42",
                "inner_wall_line_width": "0.42",
                "support_filament": str(support_filament),
                "support_interface_filament": str(support_filament),
                "flush_into_infill": "0",
                "flush_into_support": "0",
                "flush_into_objects": "0",
            }
        )
    return json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")


def _write_object_xml(
    archive: zipfile.ZipFile,
    vertices_mm: np.ndarray,
    faces: np.ndarray,
    palette_indices: np.ndarray,
    face_part_ids: np.ndarray | None = None,
    part_names: tuple[str, ...] | list[str] | None = None,
) -> None:
    if face_part_ids is None or len(face_part_ids) == 0:
        face_part_ids = np.zeros(len(faces), dtype=np.int16)
    face_part_ids = np.asarray(face_part_ids)
    if face_part_ids.shape != (len(faces),):
        raise EngineError("3MFの面パーツID数が面数と一致しません")
    if len(face_part_ids) and int(face_part_ids.min()) < 0:
        raise EngineError("3MFの面パーツIDに負数があります")
    part_count = int(face_part_ids.max()) + 1 if len(face_part_ids) else 1
    names = tuple(part_names or ("OBJ全体",))
    if len(names) != part_count:
        raise EngineError(
            f"3MFパーツ名数が面パーツIDと一致しません: {len(names)}/{part_count}"
        )
    palette_indices = np.asarray(palette_indices)
    if palette_indices.shape != (len(faces),):
        raise EngineError("3MFの色状態数が面数と一致しません")
    with archive.open("3D/Objects/object_1.model", "w", force_zip64=True) as raw:
        out = io.BufferedWriter(raw, buffer_size=1024 * 1024)
        out.write(b'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources>
''')
        for part_id, part_name in enumerate(names):
            selected_faces = np.flatnonzero(face_part_ids == part_id)
            if not len(selected_faces):
                raise EngineError(f"空の3MFパーツがあります: {part_name}")
            source_faces = np.asarray(faces[selected_faces], dtype=np.int32)
            used_vertices = np.unique(source_faces.reshape(-1))
            local_faces = np.searchsorted(used_vertices, source_faces)
            local_vertices = np.asarray(vertices_mm[used_vertices])
            safe_part_name = html.escape(part_name)
            out.write(
                (
                    f'  <object id="{part_id + 1}" '
                    f'p:UUID="00010000-81cb-4c03-9d28-{part_id + 1:012d}" '
                    f'name="{safe_part_name}" type="model">\n'
                    '   <mesh>\n'
                ).encode("utf-8")
            )
            out.write(b'''    <vertices>
''')
            for x, y, z in local_vertices:
                out.write(
                    f'     <vertex x="{x:.9g}" y="{y:.9g}" z="{z:.9g}"/>\n'.encode(
                        "ascii"
                    )
                )
            out.write(b"    </vertices>\n    <triangles>\n")
            for (a, b, c), state in zip(
                local_faces,
                palette_indices[selected_faces],
                strict=True,
            ):
                out.write(
                    f'     <triangle v1="{a}" v2="{b}" v3="{c}" paint_color="{PAINT_CODES[int(state)]}"/>\n'.encode(
                        "ascii"
                    )
                )
            out.write(b'''    </triangles>
   </mesh>
  </object>
''')
        out.write(b''' </resources>
</model>
''')
        out.flush()


def write_3mf_atomic(
    destination: Path,
    prepared: PreparedGeometry,
    colors: ColorResult,
    height_mm: float,
    palette: PaletteSettings,
    part_palettes: dict[str, PaletteSettings] | None = None,
    print_uses_global_palette: bool = False,
) -> dict[str, object]:
    # PaletteSettings normally migrates the retired field on load.  These
    # guards also cover callers that mutate dataclass instances afterwards.
    palette = without_surface_shell_output(palette)
    if part_palettes:
        part_palettes = {
            key: without_surface_shell_output(value)
            for key, value in part_palettes.items()
        }
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    name = destination.stem
    layout = validate_part_layout(prepared.final)
    face_part_ids = layout.face_part_ids
    part_count = layout.part_count
    part_names = tuple(prepared.final.part_names)
    if len(part_names) != part_count:
        part_names = tuple(
            name if part_count == 1 else f"part_{index + 1}"
            for index in range(part_count)
        )
    part_face_counts = tuple(
        int(np.count_nonzero(face_part_ids == part_id))
        for part_id in range(part_count)
    )
    palette_settings = AppSettings(
        palette=palette,
        part_palettes=dict(part_palettes or {}),
    )
    resolved_palettes = (
        (palette,) * layout.part_count
        if print_uses_global_palette
        else resolve_part_palette_settings(palette_settings, prepared.final)
    )
    final_indices = np.asarray(colors.palette_indices)
    black_free_parts: list[dict[str, object]] = []
    remaining_black_mix_faces = 0
    for part_id, (part_key, part_palette) in enumerate(
        zip(layout.part_keys, resolved_palettes, strict=True)
    ):
        selected = layout.face_part_ids == part_id
        remaining = 0
        if part_palette.black_free_gradient_enabled:
            forbidden = black_containing_mixed_states(
                part_palette.palette_state_count,
                part_palette.black_free_black_slot,
            )
            remaining = int(
                np.count_nonzero(selected & np.isin(final_indices, forbidden))
            )
        remaining_black_mix_faces += remaining
        black_free_parts.append(
            {
                "part_index": part_id,
                "part_key": part_key,
                "enabled": bool(part_palette.black_free_gradient_enabled),
                "black_slot": int(part_palette.black_free_black_slot),
                "red_slot": int(part_palette.black_free_red_slot),
                "brown_slot": int(part_palette.black_free_brown_slot),
                "remaining_black_mix_faces": remaining,
            }
        )
    black_free_role_sets = {
        (
            int(item["black_slot"]),
            int(item["red_slot"]),
            int(item["brown_slot"]),
        )
        for item in black_free_parts
    }
    common_black_free_roles = (
        next(iter(black_free_role_sets))
        if len(black_free_role_sets) == 1
        else None
    )
    black_free_metadata = {
        "schema": "tripo-spectrum-mapper.black-free-gradient.v1",
        "slot_index_base": 0,
        "enabled": bool(
            any(bool(item["enabled"]) for item in black_free_parts)
        ),
        "black_slot": (
            None if common_black_free_roles is None else common_black_free_roles[0]
        ),
        "red_slot": (
            None if common_black_free_roles is None else common_black_free_roles[1]
        ),
        "brown_slot": (
            None if common_black_free_roles is None else common_black_free_roles[2]
        ),
        "remapped_faces": int(colors.black_free_remapped_faces),
        "remaining_black_mix_faces": int(remaining_black_mix_faces),
        "parts": black_free_parts,
    }
    grouping = plan_palette_groups(palette_settings, prepared.final)
    resolved_materials = {
        value.material
        for value in resolve_part_palette_settings(
            palette_settings, prepared.final
        )
    }
    if len(resolved_materials) > 1:
        raise EngineError(
            "PLA/ABS/PETG part palettes cannot be combined into one 3MF; "
            "write independent part projects"
        )
    if grouping.requires_separate_jobs and not print_uses_global_palette:
        raise EngineError(
            "different part palettes cannot share one 3MF print job; "
            "write independent part projects or explicitly use one global palette"
        )
    part_palette_metadata = {
        "schema": "tripo-spectrum-mapper.part-palettes.v1",
        "u1_physical_slot_limit": 4,
        "one_print_job_compatible": bool(
            grouping.one_job or print_uses_global_palette
        ),
        "stored_part_palettes_one_job_compatible": grouping.one_job,
        "print_assignment_mode": (
            "global-common-4" if print_uses_global_palette else "part-palettes"
        ),
        "required_palette_groups": len(grouping.groups),
        "global_palette": palette_settings.to_dict()["palette"],
        "parts": [
            {
                "index": index,
                "key": key,
                "name": part_names[index],
                "face_count": part_face_counts[index],
                "uses_individual_palette": key in palette_settings.part_palettes,
                "palette": AppSettings(
                    palette=resolved,
                ).to_dict()["palette"],
                "palette_group": grouping.part_group_ids[index],
            }
            for index, (key, resolved) in enumerate(
                zip(
                    layout.part_keys,
                    resolve_part_palette_settings(
                        palette_settings, prepared.final
                    ),
                    strict=True,
                )
            )
        ],
    }
    assembly_metadata = {
        "schema": "tripo-spectrum-mapper.assembly.v1",
        "coordinates": "normalized source coordinates before final centering",
        "height_mm": float(height_mm),
        "part_count": int(part_count),
        **dict(prepared.assembly or {}),
    }
    export_diagnostic = getattr(
        prepared, EXPORT_DIAGNOSTICS_ATTRIBUTE, None
    )
    if isinstance(export_diagnostic, dict):
        assembly_metadata["generated_surface_color_export"] = dict(
            export_diagnostic
        )
    palette_hex, _ = build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    definitions = make_portable_mixed_definitions(
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
        palette.palette_state_count,
        palette.output_mix_ratios_b,
        palette.surface_shell_enabled,
        palette.physical_hex,
    )
    state_names = palette_state_names(
        palette.mix_ratios_b, palette.secondary_mix_ratios_b
    )
    face_counts = np.zeros(PALETTE_STATE_COUNT, dtype=np.int64)
    area_fractions = np.zeros(PALETTE_STATE_COUNT, dtype=np.float64)
    source_counts = np.asarray(colors.palette_face_counts).reshape(-1)
    source_fractions = np.asarray(colors.palette_area_fractions).reshape(-1)
    face_counts[: min(len(source_counts), PALETTE_STATE_COUNT)] = source_counts[
        :PALETTE_STATE_COUNT
    ]
    area_fractions[: min(len(source_fractions), PALETTE_STATE_COUNT)] = (
        source_fractions[:PALETTE_STATE_COUNT]
    )
    palette_metadata = {
        "schema": "tripo-spectrum-mapper.palette.v1",
        "filament_material": palette.material,
        "generic_filament_profile": generic_filament_profile(palette.material),
        "physical_slot_order": [normalize_hex(value) for value in palette.physical_hex],
        "physical_filament_refs": AppSettings(
            palette=palette
        ).to_dict()["palette"]["physical_filament_refs"],
        "palette_state_count": int(palette.palette_state_count),
        "mixing_mode": "compatible 16-state base plus appended gradient mixes",
        "black_free_gradient": black_free_metadata,
        "mix_ratios_b_percent": [int(value) for value in palette.mix_ratios_b],
        "secondary_mix_ratios_b_percent": [
            int(value) for value in palette.secondary_mix_ratios_b
        ],
        "paint_codes": list(PAINT_CODES[: palette.palette_state_count]),
        "states": [
            {
                "state": index + 1,
                "name": state_names[index],
                "display_rgb": palette_hex[index],
                "enabled_for_assignment": bool(palette.enabled_states[index]),
                "face_count": int(face_counts[index]),
                "surface_area_fraction": float(area_fractions[index]),
            }
            for index in range(palette.palette_state_count)
        ],
    }
    if palette.output_mix_ratios_b is not None:
        palette_metadata["output_mix_ratios_b_percent"] = [
            int(value) for value in palette.output_mix_ratios_b
        ]
        palette_metadata["print_mix_specs"] = [
            {
                "physical_a": left + 1,
                "physical_b": right + 1,
                "ratio_b_percent": ratio,
            }
            for left, right, ratio in print_palette_mix_specs(
                palette.mix_ratios_b,
                palette.secondary_mix_ratios_b,
                palette.output_mix_ratios_b,
            )[: palette.palette_state_count - 4]
        ]
    if palette.surface_shell_enabled and SURFACE_SHELL_OUTPUT_ENABLED:
        shell_specs = build_surface_shell_output_specs(
            palette.physical_hex,
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            palette.output_mix_ratios_b,
        )[: palette.palette_state_count - 4]
        palette_metadata["surface_shell"] = {
            "schema": "tripo-spectrum-mapper.surface-shell.v2",
            "enabled": True,
            "policy": "dark-mixes-only",
            "assumptions": {
                "wall_count": 2,
                "wall_generator": "classic",
                "outer_wall_line_width_mm": 0.42,
                "inner_wall_line_width_mm": 0.42,
                "scope": "side-wall perimeters; top and bottom surfaces are not equivalent local-normal shells",
            },
            "darkest_physical": shell_specs[0].darkest_filament if shell_specs else None,
            "lightest_physical": shell_specs[0].lightest_filament if shell_specs else None,
            "applied_rows": sum(spec.applied for spec in shell_specs),
            "eligible_rows": sum(
                spec.disposition == "eligible" for spec in shell_specs
            ),
            "passthrough_rows": sum(
                spec.disposition == "passthrough" for spec in shell_specs
            ),
            "fallback_rows": sum(
                spec.disposition == "fallback" for spec in shell_specs
            ),
            "recipes": [
                {
                    "state": spec.state_id,
                    "source_pair": [spec.source_a, spec.source_b],
                    "requested_ratio_b_percent": spec.requested_ratio_b_percent,
                    "effective_ratio_b": [
                        spec.effective_ratio_b_numerator,
                        spec.effective_ratio_b_denominator,
                    ],
                    "architecture": spec.architecture,
                    "disposition": spec.disposition,
                    "applied": spec.applied,
                    "outer_physical": spec.outer_filament,
                    "inner_pattern": spec.inner_pattern,
                    "manual_pattern": spec.manual_pattern,
                    "fallback_reason": spec.fallback_reason,
                }
                for spec in shell_specs
            ],
        }
    content_types = b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="application/octet-stream"/>
 <Default Extension="json" ContentType="application/json"/>
</Types>
'''
    root_rels = b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
'''
    model_rels = b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
'''
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr(
                "3D/3dmodel.model",
                _make_root_model(
                    name,
                    f"Full Spectrum {palette.palette_state_count} colors, height {height_mm:g} mm",
                    part_count,
                ),
            )
            archive.writestr("3D/_rels/3dmodel.model.rels", model_rels)
            _write_object_xml(
                archive,
                prepared.final.vertices_unit * float(height_mm),
                prepared.final.faces,
                colors.palette_indices,
                face_part_ids,
                part_names,
            )
            archive.writestr(
                "Metadata/model_settings.config",
                _make_model_settings(
                    name,
                    len(prepared.final.faces),
                    prepared.removed_faces,
                    part_names,
                    part_face_counts,
                    source_file=prepared.source.path.name,
                ),
            )
            archive.writestr("Metadata/project_settings.config", _make_project_settings(palette))
            archive.writestr(
                "Metadata/full_spectrum_palette.json",
                json.dumps(palette_metadata, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            archive.writestr(
                "Metadata/tripo_part_palettes.json",
                json.dumps(
                    part_palette_metadata,
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
            )
            archive.writestr(
                "Metadata/tripo_assembly.json",
                json.dumps(
                    assembly_metadata,
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
            )
        validation = validate_3mf(
            temporary,
            expected_vertices=len(prepared.final.vertices_unit),
            expected_faces=len(prepared.final.faces),
            expected_physical=[normalize_hex(value) for value in palette.physical_hex],
            expected_definitions=definitions,
            expected_parts=part_count,
            expected_filament_profile=generic_filament_profile(palette.material),
        )
        os.replace(temporary, destination)
        validation["bytes"] = destination.stat().st_size
        validation["sha256"] = sha256_file(destination)
        validation.update(
            {
                "black_free_gradient_enabled": bool(
                    black_free_metadata["enabled"]
                ),
                "black_free_black_slot": black_free_metadata["black_slot"],
                "black_free_red_slot": black_free_metadata["red_slot"],
                "black_free_brown_slot": black_free_metadata["brown_slot"],
                "black_free_remapped_faces": int(
                    black_free_metadata["remapped_faces"]
                ),
                "remaining_black_mix_faces": int(
                    black_free_metadata["remaining_black_mix_faces"]
                ),
                "black_free_gradient_parts": list(
                    black_free_metadata["parts"]
                ),
            }
        )
        if isinstance(export_diagnostic, dict):
            validation["generated_surface_color_export"] = dict(
                export_diagnostic
            )
        return validation
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_3mf(
    path: Path,
    expected_vertices: int,
    expected_faces: int,
    expected_physical: list[str],
    expected_definitions: str,
    expected_parts: int = 1,
    expected_filament_profile: str = "Generic PLA",
) -> dict[str, object]:
    import xml.etree.ElementTree as ET

    required = {
        "[Content_Types].xml",
        "_rels/.rels",
        "3D/3dmodel.model",
        "3D/_rels/3dmodel.model.rels",
        "3D/Objects/object_1.model",
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
        "Metadata/full_spectrum_palette.json",
        "Metadata/tripo_part_palettes.json",
        "Metadata/tripo_assembly.json",
    }
    vertices = 0
    faces = 0
    mesh_objects = 0
    object_topologies: list[dict[str, int | bool | float | str]] = []
    paints: Counter[str] = Counter()
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        missing = sorted(required - names)
        bad_member = archive.testzip()
        root = archive.read("3D/3dmodel.model").decode("utf-8")
        model_settings = archive.read("Metadata/model_settings.config").decode(
            "utf-8"
        )
        project = json.loads(archive.read("Metadata/project_settings.config").decode("utf-8"))
        part_palette_metadata = json.loads(
            archive.read("Metadata/tripo_part_palettes.json").decode("utf-8")
        )
        assembly_metadata = json.loads(
            archive.read("Metadata/tripo_assembly.json").decode("utf-8")
        )
        palette_metadata = json.loads(
            archive.read("Metadata/full_spectrum_palette.json").decode("utf-8")
        )
        # Every mesh object emitted by this writer is a printable 3MF
        # ``type=model`` object.  Topology validation must therefore never be
        # conditional on a GUI/assembly flag: CLI and direct writer callers
        # must not be able to serialize an open or invalid print solid.
        require_watertight = True
        object_vertices: list[list[float]] | None = None
        object_faces: list[list[int]] | None = None
        with archive.open("3D/Objects/object_1.model") as stream:
            for event, element in ET.iterparse(
                stream, events=("start", "end")
            ):
                tag = element.tag.rsplit("}", 1)[-1]
                if event == "start" and tag == "object":
                    object_vertices = []
                    object_faces = []
                elif event == "end" and tag == "object":
                    mesh_objects += 1
                    if object_vertices is not None and object_faces is not None:
                        object_topologies.append(
                            mesh_quality(
                                np.asarray(object_vertices, dtype=np.float64),
                                np.asarray(object_faces, dtype=np.int32),
                                check_self_intersections=require_watertight,
                            )
                        )
                    object_vertices = None
                    object_faces = None
                elif event == "end" and tag == "vertex":
                    vertices += 1
                    if object_vertices is not None:
                        object_vertices.append(
                            [
                                float(element.attrib["x"]),
                                float(element.attrib["y"]),
                                float(element.attrib["z"]),
                            ]
                        )
                elif event == "end" and tag == "triangle":
                    faces += 1
                    paints[element.attrib.get("paint_color", "")] += 1
                    if object_faces is not None:
                        object_faces.append(
                            [
                                int(element.attrib["v1"]),
                                int(element.attrib["v2"]),
                                int(element.attrib["v3"]),
                            ]
                        )
                if event == "end":
                    element.clear()
    errors = []
    if missing:
        errors.append(f"不足member={missing}")
    if bad_member:
        errors.append(f"CRC異常={bad_member}")
    if vertices != expected_vertices or faces != expected_faces:
        errors.append(f"件数={vertices}/{faces}")
    component_count = root.count("<component ")
    settings_part_count = model_settings.count("<part ")
    if (
        mesh_objects != expected_parts
        or component_count != expected_parts
        or settings_part_count != expected_parts
    ):
        errors.append(
            "パーツ数="
            f"mesh {mesh_objects}, component {component_count}, "
            f"settings {settings_part_count}, expected {expected_parts}"
        )
    if "" in paints or not set(paints).issubset(PAINT_CODES):
        errors.append(f"paint_color={dict(paints)}")
    if '<metadata name="Application">BambuStudio-2.3.5</metadata>' not in root:
        errors.append("Application metadata")
    if project.get("filament_colour") != expected_physical:
        errors.append("物理色")
    if project.get("filament_settings_id") != [expected_filament_profile] * 4:
        errors.append("フィラメント素材プロファイル")
    if project.get("print_settings_id") != (
        "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)"
    ):
        errors.append("0.08 mmプロファイル")
    if (
        str(project.get("layer_height", "")) != "0.08"
        or str(project.get("initial_layer_print_height", "")) != "0.2"
        or str(project.get("adaptive_layer_height", "")) != "0"
    ):
        errors.append("積層ピッチ設定")
    if "enable_support" in project or 'key="enable_support"' in model_settings:
        errors.append("サポート固定設定")
    single_mesh_generic = bool(assembly_metadata.get("single_mesh_generic"))
    repair_records_value = assembly_metadata.get("repair_records", [])
    generic_repair_record = next(
        (
            dict(value)
            for value in repair_records_value
            if isinstance(value, dict)
            and str(value.get("method", ""))
            == "coincident_vertex_seam_weld"
        ),
        {},
    ) if isinstance(repair_records_value, list) else {}
    final_validation_value = generic_repair_record.get("final_validation", {})
    final_validation = (
        dict(final_validation_value)
        if isinstance(final_validation_value, dict)
        else {}
    )
    generic_seam_warning_eligible = bool(
        single_mesh_generic
        and generic_repair_record.get("boundary_pairing_proven") is True
        and generic_repair_record.get("geometry_coordinates_preserved") is True
        and generic_repair_record.get("face_count_preserved") is True
        and final_validation.get("positive_volume_validated") is True
        and final_validation.get("closed") is True
    )
    simplification_applied = bool(
        generic_repair_record.get("simplification_applied")
    )
    source_geometry_preserved = bool(
        generic_seam_warning_eligible
        and not simplification_applied
        and generic_repair_record.get("source_triangle_geometry_preserved")
        is True
    )
    expected_generic_body_count = int(
        assembly_metadata.get("body_count", 0) or 0
    )
    self_intersection_warning_parts = 0
    for topology_record in object_topologies:
        face_count = int(topology_record.get("face_count", 0) or 0)
        intersecting_faces = int(
            topology_record.get("self_intersecting_faces", -1) or 0
        )
        area_fraction = float(
            topology_record.get("self_intersecting_area_fraction", -1.0)
        )
        face_fraction = (
            float(intersecting_faces) / float(face_count)
            if face_count > 0 and intersecting_faces >= 0
            else -1.0
        )
        face_limit = max(100, (face_count + 9_999) // 10_000)
        warning_allowed = bool(
            generic_seam_warning_eligible
            and intersecting_faces > 0
            and intersecting_faces <= face_limit
            and 0.0 <= area_fraction <= 1.0e-4
        )
        topology_record["self_intersection_face_limit"] = int(face_limit)
        topology_record["self_intersection_area_fraction_limit"] = 1.0e-4
        topology_record["self_intersecting_face_fraction"] = face_fraction
        topology_record["self_intersection_source_geometry_preserved"] = bool(
            source_geometry_preserved
        )
        topology_record["self_intersection_warning"] = warning_allowed
        if intersecting_faces == 0:
            topology_record["self_intersection_policy"] = "strict_zero"
        elif warning_allowed:
            topology_record["self_intersection_policy"] = (
                "bounded_qem_warning"
                if simplification_applied
                else "source_preserved_warning"
            )
            self_intersection_warning_parts += 1
        else:
            topology_record["self_intersection_policy"] = "blocked"

    def body_count_is_valid(value: dict[str, int | bool | float | str]) -> bool:
        body_count = int(value.get("body_count", 0) or 0)
        if single_mesh_generic:
            return bool(
                body_count >= 1
                and expected_generic_body_count >= 1
                and body_count == expected_generic_body_count
            )
        return body_count == 1

    def self_intersections_are_valid(
        value: dict[str, int | bool | float | str],
    ) -> bool:
        return bool(
            int(value.get("self_intersecting_faces", -1)) == 0
            or value.get("self_intersection_warning") is True
        )

    def solid_topology_is_valid(
        value: dict[str, int | bool | float | str],
    ) -> bool:
        return bool(
            value.get("watertight")
            and value.get("winding_consistent")
            and value.get("positive_volume")
            and body_count_is_valid(value)
            and int(value.get("degenerate_faces", -1)) == 0
            and self_intersections_are_valid(value)
        )

    valid_solids = all(
        solid_topology_is_valid(value) for value in object_topologies
    )
    if len(object_topologies) != expected_parts:
        errors.append(
            f"閉立体数={len(object_topologies)}/{expected_parts}"
        )
    elif require_watertight and not valid_solids:
        invalid_summaries: list[str] = []
        for index, value in enumerate(object_topologies, start=1):
            if solid_topology_is_valid(value):
                continue
            invalid_summaries.append(
                f"object {index}: boundary={int(value.get('boundary_edges', -1))}, "
                f"nonmanifold={int(value.get('nonmanifold_edges', -1))}, "
                f"winding={bool(value.get('winding_consistent'))}, "
                f"positive={bool(value.get('positive_volume'))}, "
                f"bodies={int(value.get('body_count', -1))}, "
                f"degenerate={int(value.get('degenerate_faces', -1))}, "
                f"self_intersections={int(value.get('self_intersecting_faces', -1))}, "
                f"policy={value.get('self_intersection_policy', 'blocked')}"
            )
        errors.append("閉立体検証=" + "; ".join(invalid_summaries))
    if assembly_metadata.get("schema") != (
        "tripo-spectrum-mapper.assembly.v1"
    ):
        errors.append("組立メタデータ")
    definitions = project.get("mixed_filament_definitions", "")
    if definitions != expected_definitions:
        errors.append("混色定義")
    shell_metadata = palette_metadata.get("surface_shell")
    cycle_rows = [row for row in definitions.split(";") if ",cm1," in row]
    shell_settings = {
        "wall_loops": "2",
        "wall_generator": "classic",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.42",
    }
    unsafe_grouped_cycle_detected = bool(
        shell_metadata is not None or cycle_rows
    )
    if unsafe_grouped_cycle_detected:
        errors.append(
            "廃止済みGrouped Cycle（Snapmaker Orcaアクセス違反の恐れ）"
        )
    elif cycle_rows or any(key in project for key in shell_settings):
        errors.append("2ウォール表面混色metadata")
    if errors:
        raise EngineError("3MF検証失敗: " + ", ".join(errors))
    black_free_metadata = palette_metadata.get("black_free_gradient")
    if not isinstance(black_free_metadata, dict):
        black_free_metadata = {}
    black_free_black_slot = black_free_metadata.get("black_slot", 0)
    black_free_red_slot = black_free_metadata.get("red_slot", 2)
    black_free_brown_slot = black_free_metadata.get("brown_slot", 3)
    warning_topologies = [
        value
        for value in object_topologies
        if value.get("self_intersection_warning") is True
    ]
    warning_policies = sorted(
        {
            str(value.get("self_intersection_policy", ""))
            for value in warning_topologies
            if value.get("self_intersection_policy")
        }
    )
    warning_policy = (
        "strict_zero"
        if not warning_policies
        else warning_policies[0]
        if len(warning_policies) == 1
        else "mixed_warning"
    )
    return {
        "zip_crc_ok": True,
        "entries": len(names),
        "vertices": vertices,
        "faces": faces,
        "parts": mesh_objects,
        "components": component_count,
        "watertight_parts": int(
            sum(bool(value.get("watertight")) for value in object_topologies)
        ),
        "validated_solid_parts": int(
            sum(solid_topology_is_valid(value) for value in object_topologies)
        ),
        "self_intersection_warning_parts": int(
            self_intersection_warning_parts
        ),
        "self_intersection_warning_policy": warning_policy,
        "self_intersection_warning_policies": warning_policies,
        "self_intersection_warning_faces": int(
            sum(
                int(value.get("self_intersecting_faces", 0) or 0)
                for value in warning_topologies
            )
        ),
        "self_intersection_warning_area": float(
            sum(
                float(value.get("self_intersecting_area", 0.0) or 0.0)
                for value in warning_topologies
            )
        ),
        "self_intersection_warning_max_area_fraction": float(
            max(
                (
                    float(
                        value.get(
                            "self_intersecting_area_fraction", 0.0
                        )
                        or 0.0
                    )
                    for value in warning_topologies
                ),
                default=0.0,
            )
        ),
        "part_topologies": object_topologies,
        "layer_height_mm": 0.08,
        "initial_layer_height_mm": 0.2,
        "support_fixed": False,
        "palette_groups": int(
            part_palette_metadata.get("required_palette_groups", 1)
        ),
        "one_print_job_compatible": bool(
            part_palette_metadata.get("one_print_job_compatible", True)
        ),
        "paint_counts": dict(paints),
        "physical_filaments": len(expected_physical),
        "mixed_definition_rows": len(definitions.split(";")),
        "surface_shell_enabled": shell_metadata is not None,
        "surface_shell_cycle_rows": len(cycle_rows),
        "surface_shell_applied_rows": (
            0
            if not isinstance(shell_metadata, dict)
            else int(shell_metadata.get("applied_rows", 0))
        ),
        "surface_shell_passthrough_rows": (
            0
            if not isinstance(shell_metadata, dict)
            else int(shell_metadata.get("passthrough_rows", 0))
        ),
        "surface_shell_fallback_rows": (
            0
            if not isinstance(shell_metadata, dict)
            else int(shell_metadata.get("fallback_rows", 0))
        ),
        "unsafe_grouped_cycle_detected": unsafe_grouped_cycle_detected,
        "black_free_gradient_enabled": bool(
            black_free_metadata.get("enabled", False)
        ),
        "black_free_black_slot": (
            None if black_free_black_slot is None else int(black_free_black_slot)
        ),
        "black_free_red_slot": (
            None if black_free_red_slot is None else int(black_free_red_slot)
        ),
        "black_free_brown_slot": (
            None if black_free_brown_slot is None else int(black_free_brown_slot)
        ),
        "black_free_remapped_faces": int(
            black_free_metadata.get("remapped_faces", 0)
        ),
        "remaining_black_mix_faces": int(
            black_free_metadata.get("remaining_black_mix_faces", 0)
        ),
        "remaining_black_mix_leaf_area": float(
            black_free_metadata.get("remaining_black_mix_leaf_area", 0.0)
        ),
        "black_free_gradient_parts": list(
            black_free_metadata.get("parts", [])
        ),
    }


def write_vertex_color_obj(
    path: Path,
    prepared: PreparedGeometry,
    colors: ColorResult,
    height_mm: float,
) -> None:
    vertices = prepared.final.vertices_unit * float(height_mm)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as out:
        out.write("# ChromaMatter tone-adjusted vertex-color OBJ\n")
        for (x, y, z), (r, g, b) in zip(vertices, colors.tone_vertex_rgb, strict=True):
            out.write(f"v {x:.7g} {y:.7g} {z:.7g} {r:.6f} {g:.6f} {b:.6f}\n")
        layout = validate_part_layout(prepared.final)
        names = tuple(prepared.final.part_names)
        if len(names) != layout.part_count:
            names = tuple(
                "Tripo_Spectrum_Mapper"
                if layout.part_count == 1
                else f"part_{index + 1}"
                for index in range(layout.part_count)
            )
        for part_id, part_name in enumerate(names):
            safe_name = re.sub(
                r"[^A-Za-z0-9_.-]+", "_", part_name.strip()
            ).strip("_") or f"part_{part_id + 1}"
            out.write(f"o {safe_name}\n")
            out.write("s 1\n")
            for a, b, c in prepared.final.faces[
                layout.face_part_ids == part_id
            ] + 1:
                out.write(f"f {a} {b} {c}\n")


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights)
    return float(values[np.searchsorted(cumulative, q * cumulative[-1], side="left")])


def make_report(
    prepared: PreparedGeometry,
    colors: ColorResult,
    height_mm: float,
    tone: ToneSettings,
    palette: PaletteSettings,
    validation: dict[str, object],
) -> dict[str, object]:
    palette_hex, _ = build_palette_rgb(
        palette.physical_hex,
        palette.mix_hex_overrides,
        palette.mix_ratios_b,
        palette.secondary_mix_ratios_b,
    )
    output_recipe_metadata: dict[str, object] = {}
    if palette.output_mix_ratios_b is not None:
        output_recipe_metadata = {
            "output_mix_ratios_b_percent": [
                int(value) for value in palette.output_mix_ratios_b
            ],
            "print_mix_specs": [
                {
                    "physical_a": left + 1,
                    "physical_b": right + 1,
                    "ratio_b_percent": ratio,
                }
                for left, right, ratio in print_palette_mix_specs(
                    palette.mix_ratios_b,
                    palette.secondary_mix_ratios_b,
                    palette.output_mix_ratios_b,
                )[: palette.palette_state_count - 4]
            ],
        }
    areas_mm2 = prepared.final.areas_unit * float(height_mm) ** 2
    source_area = prepared.source_area_unit * float(height_mm) ** 2
    target_area = prepared.simplified_area_unit * float(height_mm) ** 2
    source_volume = prepared.source_volume_unit * float(height_mm) ** 3
    target_volume = prepared.simplified_volume_unit * float(height_mm) ** 3
    dimensions = np.ptp(prepared.final.vertices_unit, axis=0) * float(height_mm)
    return {
        "application": f"{APP_DISPLAY_NAME} {__version__}",
        "source": {
            "path": str(prepared.source.path),
            "sha256": prepared.source.sha256,
            "bytes": prepared.source.file_size,
            "vertices": prepared.source.original_vertex_count,
            "faces": prepared.source.original_face_count,
        },
        "repair": {
            "removed_vertices": prepared.removed_vertices,
            "removed_faces": prepared.removed_faces,
            "clean_vertices": prepared.clean_vertex_count,
            "clean_faces": prepared.clean_face_count,
            "warnings": prepared.warnings,
        },
        "geometry": {
            "height_mm": height_mm,
            "dimensions_xyz_mm": dimensions.round(6).tolist(),
            "vertices": int(len(prepared.final.vertices_unit)),
            "faces": int(len(prepared.final.faces)),
            "source_area_mm2": source_area,
            "simplified_area_mm2": target_area,
            "area_ratio_percent": 100.0 * target_area / max(source_area, 1e-12),
            "source_volume_mm3": source_volume,
            "simplified_volume_mm3": target_volume,
            "volume_ratio_percent": 100.0 * target_volume / max(source_volume, 1e-12),
            "topology": prepared.topology,
        },
        "tone": {
            "black_point": tone.black_point,
            "white_point": tone.white_point,
            "gamma": tone.gamma,
            "contrast": tone.contrast,
            "saturation": tone.saturation,
            "pink_protection": tone.pink_protection,
            "pink_threshold": tone.pink_threshold,
            "smoothing": tone.smoothing,
            "smoothed_faces": colors.smoothed_faces,
        },
        "color": {
            "physical_hex": [normalize_hex(value) for value in palette.physical_hex],
            "physical_filament_refs": AppSettings(
                palette=palette
            ).to_dict()["palette"]["physical_filament_refs"],
            "palette_hex": palette_hex,
            "mix_ratios_b_percent": [int(value) for value in palette.mix_ratios_b],
            "secondary_mix_ratios_b_percent": [
                int(value) for value in palette.secondary_mix_ratios_b
            ],
            "expanded_mix_specs": [
                {
                    "physical_a": left + 1,
                    "physical_b": right + 1,
                    "ratio_b_percent": ratio,
                }
                for left, right, ratio in palette_mix_specs(
                    palette.mix_ratios_b,
                    palette.secondary_mix_ratios_b,
                )
            ],
            **output_recipe_metadata,
            "enabled_states": palette.enabled_states,
            "manual_override_faces": int(colors.manual_override_faces),
            "black_free_gradient_enabled": bool(
                validation.get(
                    "black_free_gradient_enabled",
                    palette.black_free_gradient_enabled,
                )
            ),
            "black_free_black_slot": validation.get(
                "black_free_black_slot", palette.black_free_black_slot
            ),
            "black_free_red_slot": validation.get(
                "black_free_red_slot", palette.black_free_red_slot
            ),
            "black_free_brown_slot": validation.get(
                "black_free_brown_slot", palette.black_free_brown_slot
            ),
            "black_free_remapped_faces": int(
                colors.black_free_remapped_faces
            ),
            "remaining_black_mix_faces": int(
                validation.get("remaining_black_mix_faces", 0)
            ),
            "face_counts": colors.palette_face_counts.astype(int).tolist(),
            "surface_area_fractions": colors.palette_area_fractions.tolist(),
            "pink_family_surface_fraction": colors.pink_area_fraction,
            "area_weighted_delta_e76_mean": float(np.average(colors.delta_e, weights=areas_mm2)),
            "area_weighted_delta_e76_p90": weighted_quantile(colors.delta_e, areas_mm2, 0.90),
            "area_weighted_delta_e76_p99": weighted_quantile(colors.delta_e, areas_mm2, 0.99),
        },
        "package_validation": validation,
    }


def write_guide(path: Path, model_path: Path, height_mm: float, palette: PaletteSettings) -> None:
    material = normalize_filament_material(palette.material)
    filament_profile = generic_filament_profile(material)
    physical = [normalize_hex(value) for value in palette.physical_hex]
    slot_lines: list[str] = []
    for index, color in enumerate(physical):
        ref = palette.physical_filament_refs[index]
        if ref is None:
            slot_lines.append(f"   F{index + 1} {color}")
            continue
        slot_lines.append(
            f"   F{index + 1} {color}  {ref.label} "
            f"[finish={ref.finish_class or '-'}; source={ref.source or '-'}; "
            f"product_id={ref.product_id}]"
        )
    physical_slot_lines = "\n".join(slot_lines)
    if palette.output_mix_ratios_b is None:
        guide_specs = print_palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            None,
        )
        ratio_lines = "\n".join(
            f"   ID {index + 5}: F{left + 1}+F{right + 1} "
            f"（F{right + 1} {ratio}% / F{left + 1} {100 - ratio}%）"
            for index, (left, right, ratio) in enumerate(guide_specs)
        )
        output_recipe_note = ""
    else:
        display_specs = palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
        )[: palette.palette_state_count - 4]
        guide_specs = print_palette_mix_specs(
            palette.mix_ratios_b,
            palette.secondary_mix_ratios_b,
            palette.output_mix_ratios_b,
        )[: palette.palette_state_count - 4]
        detailed_lines: list[str] = []
        for index, (display_spec, output_spec) in enumerate(
            zip(display_specs, guide_specs, strict=True)
        ):
            left, right, display_b = display_spec
            output_left, output_right, output_b = output_spec
            if (left, right) != (output_left, output_right):
                raise EngineError("print output recipe changed a stable filament pair")
            effective_b = orca_effective_mix_ratio(float(output_b) / 100.0)
            cadence = Fraction(effective_b).limit_denominator(100)
            layers_b = cadence.numerator
            layers_a = cadence.denominator - cadence.numerator
            detailed_lines.append(
                f"   ID {index + 5}: F{left + 1}+F{right + 1} "
                f"目標/画面 B{display_b}% → 実機出力 B{output_b}% → "
                f"Orca実効 B{effective_b * 100.0:.3g}% "
                f"(A{layers_a}:B{layers_b})"
            )
        ratio_lines = "\n".join(detailed_lines)
        output_recipe_note = (
            "\n   実機出力比率だけを補正しています。アプリ内の表示色、色判定、"
            "手動ペイントのstate ID、3MFのpaint_colorは変更しません。\n"
            "   純色ID 1〜4（F1〜F4単色）は補正対象外です。"
        )
    text = f"""ChromaMatter 出力の読み込み方
==========================================

対象: {model_path.name}

1. Snapmaker Orca 2.3.5以降を起動します。
2. この3MFは「Open as project / プロジェクトとして開く」で開きます。
3. 読み込み方法を聞かれても「Import geometry / 形状として読み込み」は選びません。
   形状読み込みではFull Spectrumの混色定義が反映されません。
4. 物理フィラメント順を確認します。
{physical_slot_lines}
5. 3MF内の{filament_profile}は仮設定です。実際の{material}スプールに合うプロファイルを各スロットで選び直し、1つの印刷ジョブに異素材を混在させないでください。
6. Full Spectrum混色に次の{len(guide_specs)}色があることを確認します。
{ratio_lines}
{output_recipe_note}
7. 公式「0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)」が選択され、通常層0.08 mmになっていることを確認します。
8. サポートはモデルごとにSnapmaker Orca側で選択し、スライスプレビューで色ID 1〜{PALETTE_STATE_COUNT}を確認してから保存・印刷します。

出力高さ: {height_mm:g} mm

注意: Full Spectrumはノズル内で溶融混合せず、薄いレイヤー切替で中間色に見せます。
実フィラメントの光沢と不透明度は画面RGBから正確に予測できないため、本番前に4本すべての色見本を試し刷りしてください。
{('ABS β: PLAより登録色・実測・色域が少ないため、目的色が無い場合はABS内だけで近似します。PLA/PETGでは補完しません。比較チャートで確認し、Snapmaker U1ではTop Coverを使用してください。' if material == 'ABS' else 'PETG β: 全スプール／ロットの色を実機校正済みではありません。比較チャートで確認してください。PLA/ABSでは補完しません。' if material == 'PETG' else '')}
"""
    path.write_text(text, encoding="utf-8-sig")
