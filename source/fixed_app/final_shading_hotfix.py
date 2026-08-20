"""Generate Orca adaptive paint on the final export topology.

This module is intentionally independent from the recovered r7 package.  It is
installed *after* ``spectrum_mapper_hotfix`` and wraps only the palette-override
and 3MF-writer entry points.  The important ordering is therefore::

    solidify/remesh -> recolor -> protect manual paint -> adaptive shading -> 3MF

The r7 editor already knows how to write an Orca-compatible subdivision tree,
but it only creates one after the user presses the explicit auto-shading button.
It also stores those trees on a PreparedGeometry instance, so a later topology
change discards them.  r8 treats automatic shading as an export product: it is
recomputed from the final vertices and tone colours, while valid editor trees
always take precedence.

Recovered from the r8 Python 3.13 code object and retained as a source-level
hotfix so builds do not depend on recovered bytecode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import copy
import functools
import hashlib
import importlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from zipfile import ZipFile

import numpy as np


HOTFIX_VERSION = "r8-export-adaptive-1"
TREE_ATTRIBUTE = "_hotfix_subtriangle_paint"
TREE_TOPOLOGY_ATTRIBUTE = "_r8_tree_topology_fingerprint"
AUTO_CACHE_ATTRIBUTE = "_r8_export_adaptive_cache"
MANUAL_MASK_ATTRIBUTE = "_r8_manual_override_mask"
LAST_EXPORT_ATTRIBUTE = "_r8_last_export_adaptive"

QUALITY_PRESETS: dict[str, dict[str, int | float]] = {
    "fast": {
        "min_edge_mm": 0.60,
        "max_depth": 1,
        "max_adaptive_faces": 20_000,
        "max_total_leaves": 80_000,
        "min_variation_delta_e": 5.0,
        "batch_faces": 8192,
    },
    "standard": {
        "min_edge_mm": 0.30,
        "max_depth": 2,
        "max_adaptive_faces": 75_000,
        "max_total_leaves": 600_000,
        "min_variation_delta_e": 2.0,
        "batch_faces": 4096,
    },
    "high": {
        "min_edge_mm": 0.18,
        "max_depth": 3,
        "max_adaptive_faces": 100_000,
        "max_total_leaves": 800_000,
        "min_variation_delta_e": 1.0,
        "batch_faces": 2048,
    },
}


@dataclass(frozen=True)
class ExportAdaptiveConfig:
    """Headless export defaults.

    ``boundary_only`` deliberately defaults to false.  Restricting the pass to
    existing root-state boundaries leaves broad same-state shading regions as
    visible triangles, which is the regression this hotfix addresses.
    """

    enabled: bool = True
    quality: str = "standard"
    dither_strength: float = 0.5
    boundary_only: bool = False

    @classmethod
    def from_value(cls, value: object) -> "ExportAdaptiveConfig":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            known = {key: value[key] for key in asdict(cls()) if key in value}
            return cls(**known)
        raise TypeError("export adaptive configuration must be a mapping")


@dataclass
class ExportAdaptiveResult:
    topology_fingerprint: str
    input_fingerprint: str
    existing_trees: dict[int, Any]
    auto_trees: dict[int, Any]
    merged_trees: dict[int, Any]
    manual_protected_faces: int
    existing_protected_faces: int
    candidate_faces: int
    selected_faces: int
    adaptive_faces: int
    total_leaves: int
    budget_limited: bool
    cache_hit: bool
    warnings: list[str]

    def validation_dict(self, dominant_changed: int) -> dict[str, object]:
        return {
            "version": HOTFIX_VERSION,
            "topology_fingerprint": self.topology_fingerprint,
            "input_fingerprint": self.input_fingerprint,
            "existing_tree_faces": len(self.existing_trees),
            "automatic_tree_faces": len(self.auto_trees),
            "merged_tree_faces": len(self.merged_trees),
            "manual_protected_faces": self.manual_protected_faces,
            "existing_protected_faces": self.existing_protected_faces,
            "candidate_faces": self.candidate_faces,
            "selected_faces": self.selected_faces,
            "adaptive_faces": self.adaptive_faces,
            "total_leaves": self.total_leaves,
            "budget_limited": self.budget_limited,
            "cache_hit": self.cache_hit,
            "dominant_root_changes": int(dominant_changed),
            "warnings": list(self.warnings),
        }


def _update_array_hash(digest: Any, value: object) -> None:
    array = np.ascontiguousarray(np.asarray(value))
    digest.update(str(array.dtype).encode("ascii", "replace"))
    digest.update(repr(tuple(int(v) for v in array.shape)).encode("ascii"))
    digest.update(memoryview(array).cast("B"))


def topology_fingerprint(level: object) -> str:
    """Fingerprint face identity/order, not merely the number of faces."""

    faces = np.asarray(getattr(level, "faces"))
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("final faces must be an Fx3 array")
    vertices = np.asarray(getattr(level, "vertices_unit"))
    digest = hashlib.sha256()
    digest.update(b"tripo-r8-topology-v1\0")
    digest.update(int(len(vertices)).to_bytes(8, "little", signed=False))
    _update_array_hash(digest, faces.astype(np.int64, copy=False))
    return digest.hexdigest().upper()


def _tree_fingerprint(trees: Mapping[int, Any], smooth_paint_module: object) -> str:
    digest = hashlib.sha256()
    digest.update(b"tripo-r8-trees-v1\0")
    encode = getattr(smooth_paint_module, "encode_paint_color")
    for face, node in sorted(trees.items()):
        digest.update(int(face).to_bytes(8, "little", signed=False))
        digest.update(str(encode(node)).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest().upper()


def _input_fingerprint(
    level: object,
    colors: object,
    palette_rgb: np.ndarray,
    manual_mask: np.ndarray,
    existing_trees: Mapping[int, Any],
    config: ExportAdaptiveConfig,
    smooth_paint_module: object,
) -> str:
    digest = hashlib.sha256()
    digest.update(b"tripo-r8-export-input-v1\0")
    digest.update(topology_fingerprint(level).encode("ascii"))
    _update_array_hash(digest, getattr(colors, "tone_vertex_rgb"))
    _update_array_hash(digest, getattr(colors, "palette_indices"))
    _update_array_hash(digest, palette_rgb)
    _update_array_hash(digest, manual_mask.astype(np.uint8, copy=False))
    digest.update(_tree_fingerprint(existing_trees, smooth_paint_module).encode("ascii"))
    digest.update(json.dumps(asdict(config), sort_keys=True).encode("utf-8"))
    return digest.hexdigest().upper()


def _manual_mask(colors: object, face_count: int) -> tuple[np.ndarray, list[str]]:
    raw = getattr(colors, MANUAL_MASK_ATTRIBUTE, None)
    warnings: list[str] = []
    if raw is not None:
        mask = np.asarray(raw, dtype=bool).reshape(-1)
        if len(mask) == face_count:
            return mask.copy(), warnings
        warnings.append("manual override mask length did not match final topology")

    manual_count = int(getattr(colors, "manual_override_faces", 0) or 0)
    if manual_count > 0:
        warnings.append(
            "manual override indices were unavailable; automatic shading was "
            "conservatively skipped"
        )
        return np.ones(face_count, dtype=bool), warnings
    return np.zeros(face_count, dtype=bool), warnings


def _valid_existing_trees(
    prepared: object,
    face_count: int,
    current_topology: str,
    smooth_paint_module: object,
) -> tuple[dict[int, Any], list[str]]:
    raw = getattr(prepared, TREE_ATTRIBUTE, None)
    if not isinstance(raw, Mapping) or not raw:
        setattr(prepared, TREE_TOPOLOGY_ATTRIBUTE, current_topology)
        return {}, []

    warnings: list[str] = []
    recorded = getattr(prepared, TREE_TOPOLOGY_ATTRIBUTE, None)
    if recorded is not None and str(recorded) != current_topology:
        warnings.append("ignored adaptive trees tied to an older topology")
        return {}, warnings

    encode = getattr(smooth_paint_module, "encode_paint_color")
    valid: dict[int, Any] = {}
    for raw_face, node in raw.items():
        try:
            face = int(raw_face)
            if not 0 <= face < face_count:
                raise IndexError(face)
            encode(node)
        except (IndexError, TypeError, ValueError):
            warnings.append(f"ignored invalid adaptive tree root {raw_face!r}")
            continue
        valid[face] = node

    setattr(prepared, TREE_TOPOLOGY_ATTRIBUTE, current_topology)
    return valid, warnings


def remap_existing_trees_to_part(
    prepared: object,
    part_prepared: object,
    source_face_ids: object,
    smooth_paint_module: object,
) -> int:
    """Copy valid global editor trees to an extracted part's local face IDs."""

    source_ids = np.asarray(source_face_ids, dtype=np.int64).reshape(-1)
    local_face_count = len(np.asarray(getattr(part_prepared.final, "faces")))
    if len(source_ids) != local_face_count:
        raise ValueError("part source-face map does not match local face count")
    full_count = len(np.asarray(getattr(prepared.final, "faces")))
    existing, _warnings = _valid_existing_trees(
        prepared,
        full_count,
        topology_fingerprint(prepared.final),
        smooth_paint_module,
    )
    local = {
        local_face: existing[int(global_face)]
        for local_face, global_face in enumerate(source_ids)
        if int(global_face) in existing
    }
    if local:
        setattr(part_prepared, TREE_ATTRIBUTE, local)
    setattr(
        part_prepared,
        TREE_TOPOLOGY_ATTRIBUTE,
        topology_fingerprint(part_prepared.final),
    )
    return len(local)


def _state_boundary_mask(faces: np.ndarray, states: np.ndarray) -> np.ndarray:
    """Return roots touching a differently coloured adjacent root."""

    result = np.zeros(len(faces), dtype=bool)
    first: dict[tuple[int, int], int] = {}
    for face_id, triangle in enumerate(np.asarray(faces, dtype=np.int64)):
        for a, b in (
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ):
            edge = (int(min(a, b)), int(max(a, b)))
            other = first.pop(edge, None)
            if other is None:
                first[edge] = face_id
            elif int(states[other]) != int(states[face_id]):
                result[other] = True
                result[face_id] = True
    return result


def _auto_options(
    auto_shading_module: object,
    height_mm: float,
    enabled_states: object,
    config: ExportAdaptiveConfig,
) -> object:
    preset = QUALITY_PRESETS.get(str(config.quality), QUALITY_PRESETS["standard"])
    strength = float(np.clip(float(config.dither_strength), 0.0, 1.0))
    return getattr(auto_shading_module, "AutoShadingOptions")(
        units_to_mm=max(float(height_mm), 1.0e-9),
        min_edge_mm=float(preset["min_edge_mm"]),
        max_depth=int(preset["max_depth"]),
        max_adaptive_faces=int(preset["max_adaptive_faces"]),
        max_total_leaves=int(preset["max_total_leaves"]),
        min_variation_delta_e=float(preset["min_variation_delta_e"]),
        dither=strength > 0.0,
        dither_strength=strength,
        dither_seed=0,
        batch_faces=int(preset["batch_faces"]),
        enabled_states=tuple(bool(value) for value in enabled_states),
    )


def validate_palette_slot_alignment(
    colors: object,
    palette_rgb: object,
    *,
    tolerance: float = 3.0 / 255.0,
) -> float:
    """Verify that the writer palette describes ColorResult state slots.

    ``workflow.export_bundle`` passes its effective print palette to the
    writer: the global palette for a forced combined job, and the resolved
    part palette for an individual job.  ``part_palettes`` is metadata at that
    point and must not replace this argument.  This guard turns any accidental
    mismatch into the writer's safe fallback instead of generating wrong
    subdivision colours.
    """

    states = np.asarray(getattr(colors, "palette_indices"), dtype=np.int64).reshape(-1)
    target = np.asarray(getattr(colors, "target_face_rgb"), dtype=np.float64)
    rgb = np.asarray(palette_rgb, dtype=np.float64)
    if target.shape != (len(states), 3):
        raise ValueError("target face RGB does not match final face count")
    if len(states) and (int(np.min(states)) < 0 or int(np.max(states)) >= len(rgb)):
        raise ValueError("palette indices exceed the effective writer palette")
    error = float(np.max(np.abs(target - rgb[states]))) if len(states) else 0.0
    if error > float(tolerance):
        raise ValueError(
            "effective writer palette does not match ColorResult state slots "
            f"(maximum RGB error {error:.6f})"
        )
    return error


def generate_export_adaptive(
    prepared: object,
    colors: object,
    height_mm: float,
    palette: object,
    *,
    palette_rgb: object,
    auto_shading_module: object,
    smooth_paint_module: object,
    config: ExportAdaptiveConfig | Mapping[str, object] | None = None,
) -> ExportAdaptiveResult:
    """Generate and merge trees without mutating existing editor data."""

    level = getattr(prepared, "final")
    faces = np.asarray(getattr(level, "faces"))
    face_count = len(faces)
    topology = topology_fingerprint(level)
    settings = ExportAdaptiveConfig.from_value(
        config
        if config is not None
        else getattr(prepared, "_r8_export_adaptive_config", None)
    )

    rgb = np.asarray(palette_rgb, dtype=np.float64)
    states = np.asarray(getattr(colors, "palette_indices"), dtype=np.int16).reshape(-1)
    if len(states) != face_count:
        raise ValueError("palette indices do not match the final face count")
    validate_palette_slot_alignment(colors, rgb)

    manual, warnings = _manual_mask(colors, face_count)
    existing, tree_warnings = _valid_existing_trees(
        prepared,
        face_count,
        topology,
        smooth_paint_module,
    )
    warnings.extend(tree_warnings)

    allowed = ~manual
    if existing:
        allowed[
            np.fromiter(existing, dtype=np.intp, count=len(existing))
        ] = False
    if settings.boundary_only:
        allowed &= _state_boundary_mask(faces, states)

    # Faces generated only to close/split a solid are intentionally hidden in
    # the assembled print.  Keep adaptive shading off those faces so an
    # invisible cap does not acquire avoidable colour changes.  Import lazily:
    # r8 must remain usable with older source trees that do not yet provide the
    # generated-surface policy module.
    unconstrained_allowed = allowed.copy()
    try:
        from spectrum_mapper.generated_surface_color import (
            constrain_adaptive_allowed_mask,
        )

        allowed = np.asarray(
            constrain_adaptive_allowed_mask(prepared, allowed), dtype=bool
        ).reshape(-1)
        if len(allowed) != face_count:
            raise ValueError("generated-surface allowed mask has wrong length")
    except ImportError:
        allowed = unconstrained_allowed

    fingerprint = _input_fingerprint(
        level,
        colors,
        rgb,
        manual,
        existing,
        settings,
        smooth_paint_module,
    )
    if not np.array_equal(allowed, unconstrained_allowed):
        # The original r8 fingerprint must stay byte-for-byte compatible when
        # no generated-face restriction is active.  Only extend it when this
        # integration materially changes the candidate mask; otherwise a cache
        # created before a provenance update could be reused incorrectly.
        digest = hashlib.sha256()
        digest.update(b"tripo-r8-generated-allowed-v1\0")
        digest.update(fingerprint.encode("ascii"))
        _update_array_hash(digest, allowed.astype(np.uint8, copy=False))
        fingerprint = digest.hexdigest().upper()
    cache = getattr(prepared, AUTO_CACHE_ATTRIBUTE, None)
    cache_hit = bool(
        isinstance(cache, Mapping)
        and cache.get("fingerprint") == fingerprint
        and cache.get("topology_fingerprint") == topology
        and isinstance(cache.get("trees"), Mapping)
    )

    if cache_hit:
        cached_trees = {int(key): value for key, value in cache["trees"].items()}
        # The fingerprint normally prevents an older eligibility mask from
        # hitting this cache.  Filter again at the consumption boundary as a
        # fail-safe so malformed or externally restored cache data can never
        # re-enable adaptive colour on a protected hidden face.
        auto_trees = {
            face: node
            for face, node in cached_trees.items()
            if 0 <= face < face_count and bool(allowed[face])
        }
        stats = dict(cache.get("stats", {}))
        if len(auto_trees) != len(cached_trees):
            warnings.append(
                "discarded adaptive cache entries outside the current allowed mask"
            )
            stats["selected_faces"] = len(auto_trees)
            stats["adaptive_faces"] = len(auto_trees)
    elif settings.enabled and bool(np.any(allowed)):
        options = _auto_options(
            auto_shading_module,
            height_mm,
            getattr(palette, "enabled_states"),
            settings,
        )
        generated = getattr(auto_shading_module, "generate_auto_shading")(
            faces,
            np.asarray(getattr(level, "vertices_unit")),
            np.asarray(getattr(colors, "tone_vertex_rgb")),
            states,
            rgb,
            options=options,
            face_mask=allowed,
        )
        auto_trees = {
            int(face): node
            for face, node in generated.trees.items()
            if 0 <= int(face) < face_count and bool(allowed[int(face)])
        }
        stats = {
            "candidate_faces": int(generated.candidate_faces),
            "selected_faces": int(generated.selected_faces),
            "adaptive_faces": int(generated.adaptive_faces),
            "total_leaves": int(generated.total_leaves),
            "budget_limited": bool(generated.budget_limited),
        }
        setattr(
            prepared,
            AUTO_CACHE_ATTRIBUTE,
            {
                "fingerprint": fingerprint,
                "topology_fingerprint": topology,
                "trees": dict(auto_trees),
                "stats": dict(stats),
            },
        )
    else:
        auto_trees = {}
        stats = {
            "candidate_faces": 0,
            "selected_faces": 0,
            "adaptive_faces": 0,
            "total_leaves": 0,
            "budget_limited": False,
        }

    merged = dict(auto_trees)
    merged.update(existing)
    return ExportAdaptiveResult(
        topology_fingerprint=topology,
        input_fingerprint=fingerprint,
        existing_trees=existing,
        auto_trees=auto_trees,
        merged_trees=merged,
        manual_protected_faces=int(np.count_nonzero(manual)),
        existing_protected_faces=len(existing),
        candidate_faces=int(stats.get("candidate_faces", 0)),
        selected_faces=int(stats.get("selected_faces", 0)),
        adaptive_faces=int(stats.get("adaptive_faces", len(auto_trees))),
        total_leaves=int(stats.get("total_leaves", 0)),
        budget_limited=bool(stats.get("budget_limited", False)),
        cache_hit=cache_hit,
        warnings=warnings,
    )


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    linear = np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )
    xyz = linear @ np.asarray(
        (
            (0.4124564, 0.3575761, 0.1804375),
            (0.2126729, 0.7151522, 0.0721750),
            (0.0193339, 0.1191920, 0.9503041),
        ),
        dtype=np.float64,
    ).T
    xyz /= np.asarray((0.95047, 1.0, 1.08883), dtype=np.float64)
    delta = 0.20689655172413793
    transformed = np.where(
        xyz > delta**3,
        np.cbrt(xyz),
        xyz / (3.0 * delta**2) + 0.13793103448275862,
    )
    return np.stack(
        (
            116.0 * transformed[..., 1] - 16.0,
            500.0 * (transformed[..., 0] - transformed[..., 1]),
            200.0 * (transformed[..., 1] - transformed[..., 2]),
        ),
        axis=-1,
    )


def apply_dominant_roots(
    colors: object,
    level: object,
    trees: Mapping[int, Any],
    palette_rgb: object,
) -> tuple[object, int]:
    """Return a shallow ColorResult copy whose root states match its trees."""

    result = copy.copy(colors)
    states = np.asarray(
        getattr(colors, "palette_indices"), dtype=np.int16
    ).copy()
    rgb = np.asarray(palette_rgb, dtype=np.float64)
    changed = 0
    for face, node in trees.items():
        root = int(node.dominant_state())
        if not 0 <= int(face) < len(states):
            raise IndexError(f"adaptive tree root is outside final topology: {face}")
        if not 0 <= root < len(rgb):
            raise ValueError(f"adaptive tree has an invalid dominant state: {root}")
        changed += int(int(states[int(face)]) != root)
        states[int(face)] = root

    result.palette_indices = states.astype(
        np.asarray(getattr(colors, "palette_indices")).dtype,
        copy=False,
    )
    target = np.asarray(
        getattr(colors, "target_face_rgb"), dtype=np.float64
    ).copy()
    if target.shape == (len(states), 3):
        target[:] = rgb[states]
        result.target_face_rgb = target

    state_count = max(
        len(rgb),
        len(np.asarray(getattr(colors, "palette_face_counts"))),
    )
    result.palette_face_counts = np.bincount(
        states, minlength=state_count
    ).astype(np.int64)
    areas = np.asarray(getattr(level, "areas_unit"), dtype=np.float64).reshape(-1)
    if len(areas) == len(states):
        weighted = np.bincount(states, weights=areas, minlength=state_count)
        total = float(np.sum(weighted))
        result.palette_area_fractions = weighted / total if total > 0.0 else weighted

    source = np.asarray(getattr(colors, "source_face_rgb"), dtype=np.float64)
    if source.shape == target.shape:
        result.delta_e = np.linalg.norm(
            _srgb_to_lab(source) - _srgb_to_lab(target), axis=1
        )
    return result, changed


def _sync_color_result(destination: object, source: object) -> None:
    for name in (
        "palette_indices",
        "target_face_rgb",
        "delta_e",
        "palette_face_counts",
        "palette_area_fractions",
    ):
        if hasattr(source, name):
            setattr(destination, name, getattr(source, name))


def _stamp_manual_mask(
    result: object,
    manual_overrides: object,
    face_count: int,
) -> object:
    if manual_overrides is None:
        mask = np.zeros(face_count, dtype=bool)
    else:
        raw = np.asarray(manual_overrides).reshape(-1)
        if len(raw) != face_count:
            mask = np.ones(face_count, dtype=bool)
        else:
            mask = raw >= 0
    setattr(result, MANUAL_MASK_ATTRIBUTE, np.asarray(mask, dtype=bool))
    return result


def _calibration_chart_disables_adaptive(prepared: object) -> bool:
    """Return true only for the purpose-built uniform calibration chart."""

    assembly = getattr(prepared, "assembly", None)
    if not isinstance(assembly, Mapping):
        return False
    topology = getattr(prepared, "topology", None)
    if not isinstance(topology, Mapping):
        return False
    chart = assembly.get("calibration_chart")
    return bool(
        isinstance(chart, Mapping)
        and chart.get("schema") == "obj-adjuster.palette-calibration.v1"
        and chart.get("adaptive_paint") is False
        and chart.get("all_swatch_faces_uniform") is True
        and topology.get("purpose_built_calibration") is True
    )


def inspect_3mf_paint(
    path: str | Path,
    smooth_paint_module: object | None = None,
) -> dict[str, object]:
    """Small, dependency-light diagnostic used by the r8 regression tests."""

    if smooth_paint_module is None:
        smooth_paint_module = importlib.import_module("smooth_paint")
    decode = getattr(smooth_paint_module, "decode_paint_color")
    with ZipFile(Path(path), "r") as archive:
        payload = archive.read("3D/Objects/object_1.model")
    triangles = re.findall(b"<triangle\\b([^>]*)/>", payload)
    adaptive = 0
    invalid = 0
    root_mismatches = 0
    codes: list[str] = []
    for attributes in triangles:
        paint_match = re.search(b'\\bpaint_color="([0-9A-Fa-f]+)"', attributes)
        if paint_match is None:
            invalid += 1
            continue
        code = paint_match.group(1).decode("ascii")
        codes.append(code)
        try:
            tree = decode(code)
        except Exception:
            invalid += 1
            continue
        adaptive += int(not bool(tree.is_leaf))
        root_match = re.search(b'\\bp1="(\\d+)"', attributes)
        if root_match is None:
            continue
        root_mismatches += int(
            int(root_match.group(1)) != int(tree.dominant_state())
        )
    return {
        "faces": len(triangles),
        "paint_color_faces": len(codes),
        "adaptive_paint_faces": adaptive,
        "invalid_paint_faces": invalid,
        "dominant_root_mismatches": root_mismatches,
        "maximum_code_length": max((len(code) for code in codes), default=0),
    }


_INSTALLED = False


def install_export_adaptive_hotfix() -> bool:
    """Install the r8 export wrapper once; return true on first installation."""

    global _INSTALLED
    if _INSTALLED:
        return False

    engine = importlib.import_module("spectrum_mapper.engine")
    workflow = importlib.import_module("spectrum_mapper.workflow")
    mixer = importlib.import_module("spectrum_mapper.mixer")
    auto_shading_module = importlib.import_module("auto_shading")
    smooth_paint_module = importlib.import_module("smooth_paint")
    smooth_hotfix = importlib.import_module("smooth_paint_hotfix")

    original_apply = engine.apply_palette_overrides
    original_apply_parts = engine.apply_palette_overrides_parts
    original_writer = workflow.write_3mf_atomic
    original_extract_part = getattr(workflow, "_extract_prepared_part", None)

    @functools.wraps(original_apply)
    def apply_palette_overrides_r8(
        level,
        height_mm,
        palette,
        colors,
        manual_overrides,
        *,
        remap_out_of_range=True,
    ):
        # ``apply_palette_overrides_parts`` has already remapped each part
        # against its own 16/24/32-state palette, then deliberately disables
        # the global remap on this inner call.  Keep that keyword contract when
        # stamping the r8 manual-protection mask; otherwise Manual Editing
        # fails during initialization before it can display the first frame.
        result = original_apply(
            level,
            height_mm,
            palette,
            colors,
            manual_overrides,
            remap_out_of_range=remap_out_of_range,
        )
        return _stamp_manual_mask(result, manual_overrides, len(level.faces))

    @functools.wraps(original_apply_parts)
    def apply_palette_overrides_parts_r8(
        level, height_mm, palette, part_palettes, colors, manual_overrides
    ):
        result = original_apply_parts(
            level,
            height_mm,
            palette,
            part_palettes,
            colors,
            manual_overrides,
        )
        return _stamp_manual_mask(result, manual_overrides, len(level.faces))

    @functools.wraps(original_writer)
    def write_3mf_atomic_r8(
        destination,
        prepared,
        colors,
        height_mm,
        palette,
        part_palettes=None,
        print_uses_global_palette=False,
    ):
        # A physical palette chart must keep one uniform, independently
        # measurable coupon per state. Adaptive sub-triangle shading would
        # turn the reference into a gradient. This metadata gate is narrow so
        # normal model exports retain their established automatic shading.
        if _calibration_chart_disables_adaptive(prepared):
            validation = original_writer(
                destination,
                prepared,
                colors,
                height_mm,
                palette,
                part_palettes,
                print_uses_global_palette,
            )
            details = {
                "version": HOTFIX_VERSION,
                "status": "disabled_calibration",
                "topology_fingerprint": topology_fingerprint(prepared.final),
                "input_fingerprint": "",
                "existing_tree_faces": 0,
                "automatic_tree_faces": 0,
                "merged_tree_faces": 0,
                "manual_protected_faces": 0,
                "existing_protected_faces": 0,
                "candidate_faces": 0,
                "selected_faces": 0,
                "adaptive_faces": 0,
                "total_leaves": 0,
                "budget_limited": False,
                "cache_hit": False,
                "dominant_root_changes": 0,
                "warnings": [],
                "palette_mode": "calibration_uniform_states",
            }
            setattr(prepared, LAST_EXPORT_ATTRIBUTE, details)
            if isinstance(validation, dict):
                validation["r8_export_adaptive"] = details
            return validation
        try:
            rgb = np.asarray(
                smooth_hotfix._palette_rgb(palette, mixer), dtype=np.float64
            )
            adaptive = generate_export_adaptive(
                prepared,
                colors,
                height_mm,
                palette,
                palette_rgb=rgb,
                auto_shading_module=auto_shading_module,
                smooth_paint_module=smooth_paint_module,
            )
            export_colors, dominant_changed = apply_dominant_roots(
                colors,
                prepared.final,
                adaptive.merged_trees,
                rgb,
            )
        except Exception as exc:
            validation = original_writer(
                destination,
                prepared,
                colors,
                height_mm,
                palette,
                part_palettes,
                print_uses_global_palette,
            )
            if isinstance(validation, dict):
                validation["r8_export_adaptive"] = {
                    "version": HOTFIX_VERSION,
                    "status": "safe_fallback",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            return validation

        sentinel = object()
        previous = getattr(prepared, TREE_ATTRIBUTE, sentinel)
        setattr(prepared, TREE_ATTRIBUTE, adaptive.merged_trees)
        try:
            validation = original_writer(
                destination,
                prepared,
                export_colors,
                height_mm,
                palette,
                part_palettes,
                print_uses_global_palette,
            )
        finally:
            if previous is sentinel:
                delattr(prepared, TREE_ATTRIBUTE)
            else:
                setattr(prepared, TREE_ATTRIBUTE, previous)

        _sync_color_result(colors, export_colors)
        details = adaptive.validation_dict(dominant_changed)
        details["status"] = "generated" if adaptive.auto_trees else "preserved"
        details["palette_mode"] = (
            "global_forced"
            if bool(print_uses_global_palette)
            else "effective_or_individual"
        )
        setattr(prepared, LAST_EXPORT_ATTRIBUTE, details)
        if isinstance(validation, dict):
            validation["r8_export_adaptive"] = details
        return validation

    if callable(original_extract_part):

        @functools.wraps(original_extract_part)
        def extract_prepared_part_r8(prepared, part_id):
            part_prepared, source_face_ids = original_extract_part(prepared, part_id)
            remap_existing_trees_to_part(
                prepared,
                part_prepared,
                source_face_ids,
                smooth_paint_module,
            )
            return part_prepared, source_face_ids

    else:
        extract_prepared_part_r8 = None

    engine.apply_palette_overrides = apply_palette_overrides_r8
    workflow.apply_palette_overrides = apply_palette_overrides_r8
    engine.apply_palette_overrides_parts = apply_palette_overrides_parts_r8
    workflow.apply_palette_overrides_parts = apply_palette_overrides_parts_r8
    engine.write_3mf_atomic = write_3mf_atomic_r8
    workflow.write_3mf_atomic = write_3mf_atomic_r8
    if extract_prepared_part_r8 is not None:
        workflow._extract_prepared_part = extract_prepared_part_r8

    register = getattr(smooth_hotfix, "_register_level", None)
    if callable(register) and not getattr(register, "_r8_wrapped", False):

        @functools.wraps(register)
        def register_level_r8(prepared):
            store = register(prepared)
            current = topology_fingerprint(prepared.final)
            recorded = getattr(prepared, TREE_TOPOLOGY_ATTRIBUTE, None)
            if not store or recorded is None:
                setattr(prepared, TREE_TOPOLOGY_ATTRIBUTE, current)
            return store

        register_level_r8._r8_wrapped = True
        smooth_hotfix._register_level = register_level_r8

    _INSTALLED = True
    return True
