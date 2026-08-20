"""Canonical geometry boundary for the experimental ColorDepth renderer.

The high-level workflow supplies a :class:`ColorDepthGeometryRequest`.  This
module deliberately does not know about laboratory ``.npz`` files, a specific
head model, or legacy FullSpectrum percentages.  It normalises the prepared
surface to millimetres and delegates the expensive work to an exact partition
provider behind a typed array contract.

An exact provider is responsible for TetGen boundary preservation, target
owner/depth construction, conforming material-threshold splits, and the
unsafe-column fallback.  The provider returns one shared tetrahedral complex;
this module independently checks its recipe/material assignment and visible
surface provenance before extracting physical F1..F4 unions.  A production
provider is loaded lazily so importing the GUI never starts TetGen or accepts a
scratch proof artifact by accident.

The current r21 laboratory remains SLICE ONLY.  Every omitted or incomplete
proof fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import math
from typing import TYPE_CHECKING, Callable, Mapping, Protocol, runtime_checkable

import numpy as np
import trimesh

from .color_depth import (
    COLOR_DEPTH_SCHEMA,
    ColorDepthCellResult,
    ColorDepthMaterialPart,
    ColorDepthRecipe,
)
from .material_manifold import manifoldize_labeled_tetrahedra

if TYPE_CHECKING:  # Avoid a runtime cycle with the workflow's lazy loader.
    from .color_depth_workflow import ColorDepthGeometryRequest


COLOR_DEPTH_GEOMETRY_SCHEMA = (
    "tripo-spectrum-mapper.color-depth.geometry.experimental.v1"
)
_DEFAULT_MAX_SAFE_THRESHOLD_ERROR_MM = 0.05
_EXTERIOR_DISTANCE_TOLERANCE_MM = 1e-7
_EXTERIOR_AREA_TOLERANCE_MM2 = 1e-8


class ColorDepthGeometryError(RuntimeError):
    """Stable diagnostic from the request/partition boundary."""

    def __init__(
        self,
        code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(self.code)


def _raise(code: str, **details: object) -> None:
    raise ColorDepthGeometryError(code, details)


def _immutable(values: np.ndarray, dtype: np.dtype) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype).copy()
    result.flags.writeable = False
    return result


@dataclass(frozen=True, slots=True)
class ColorDepthSourceSurface:
    """Validated visible source surface in millimetres.

    ``face_target_labels`` are zero-based target-colour identities.  They are
    never virtual extruders and carry no legacy Ratio/Cycle percentage.
    """

    vertices_mm: np.ndarray
    faces: np.ndarray
    face_target_labels: np.ndarray
    height_mm: float
    source_name: str
    source_sha256: str
    source_volume_mm3: float
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConformingColorDepthPartition:
    """Exact-provider output consumed by the canonical material builder.

    ``cell_depth_bounds_mm`` describe the already-split recipe interval of
    each cell.  They are not centroid samples.  A cell outside
    ``unsafe_outer_only_cells`` may not straddle a material-changing recipe
    threshold.  Unsafe cells must be explicitly labelled with their recipe's
    outer physical material.

    ``exterior_faces`` and ``exterior_source_face_ids`` provide the exact
    visible-boundary provenance.  Child triangles may subdivide a source
    triangle, but must cover every source triangle with identical orientation
    and area.
    """

    nodes_mm: np.ndarray
    tetrahedra: np.ndarray
    cell_owner_labels: np.ndarray
    cell_depth_bounds_mm: np.ndarray
    cell_materials: np.ndarray
    unsafe_outer_only_cells: np.ndarray
    exterior_faces: np.ndarray
    exterior_owner_cells: np.ndarray
    exterior_source_face_ids: np.ndarray
    threshold_interface_conforming: bool
    shared_interface_partition_exact: bool
    max_safe_threshold_error_mm: float
    max_safe_threshold_error_limit_mm: float = (
        _DEFAULT_MAX_SAFE_THRESHOLD_ERROR_MM
    )
    metadata: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class ColorDepthPartitionProvider(Protocol):
    """Expensive exact partition producer, kept separate from the GUI."""

    def __call__(
        self,
        surface: ColorDepthSourceSurface,
        recipes: Mapping[int, ColorDepthRecipe],
        *,
        progress: Callable[..., object] | None = None,
    ) -> ConformingColorDepthPartition: ...


@runtime_checkable
class ColorDepthMaterialSurfaceBuilder(Protocol):
    """Shared-manifold material-union extraction strategy.

    The default uses the strict canonical cell extractor.  Keeping this seam
    explicit lets the independently validated shared edge-sector
    manifoldizer be promoted without changing the GUI or exact provider
    contract.
    """

    def __call__(
        self,
        nodes_mm: np.ndarray,
        tetrahedra: np.ndarray,
        cell_materials: np.ndarray,
        *,
        cell_owner_labels: np.ndarray,
        require_single_source_component: bool,
    ) -> ColorDepthCellResult: ...


def _shared_material_surface_builder(
    nodes_mm: np.ndarray,
    tetrahedra: np.ndarray,
    cell_materials: np.ndarray,
    *,
    cell_owner_labels: np.ndarray,
    require_single_source_component: bool,
) -> ColorDepthCellResult:
    """Adapt the shared production manifoldizer to the ColorDepth core type."""

    del require_single_source_component
    result = manifoldize_labeled_tetrahedra(
        nodes_mm, tetrahedra, cell_materials
    )
    owners = np.asarray(cell_owner_labels, dtype=np.int32)
    materials = np.asarray(cell_materials, dtype=np.int8)
    parts = tuple(
        ColorDepthMaterialPart(
            name=f"ColorDepth physical F{part.extruder}",
            vertices_mm=part.vertices_mm,
            faces=part.faces,
            extruder=int(part.extruder),
            source_labels=tuple(
                sorted(
                    int(value)
                    for value in np.unique(
                        owners[materials == int(part.extruder)]
                    )
                    if int(value) >= 0
                )
            ),
            metadata=part.metadata,
        )
        for part in result.parts
    )
    return ColorDepthCellResult(
        parts=parts,
        interfaces=result.interfaces,
        source_volume_mm3=result.source_volume_mm3,
        output_volume_mm3=result.output_volume_mm3,
        cell_materials=result.cell_materials,
        metadata=result.metadata,
    )


_PROVIDER_CANDIDATES = (
    (
        "spectrum_mapper.color_depth_exact_partition",
        "build_conforming_color_depth_partition",
    ),
    (
        "spectrum_mapper.color_depth_tetgen_partition",
        "build_conforming_color_depth_partition",
    ),
)


def _load_default_partition_provider() -> ColorDepthPartitionProvider:
    attempted: list[str] = []
    for module_name, attribute in _PROVIDER_CANDIDATES:
        attempted.append(f"{module_name}:{attribute}")
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                _raise(
                    "partition_provider_dependency_missing",
                    module=module_name,
                    dependency=exc.name,
                )
            continue
        function = getattr(module, attribute, None)
        if callable(function):
            return function
    _raise("exact_partition_provider_unavailable", attempted=attempted)


def prepare_color_depth_source(
    request: "ColorDepthGeometryRequest | object",
) -> ColorDepthSourceSurface:
    """Normalise and validate the workflow request without doing heavy work."""

    try:
        height_mm = float(request.height_mm)
        labels_raw = np.asarray(request.face_target_labels)
        recipes = request.recipes
    except (AttributeError, TypeError, ValueError) as exc:
        _raise("invalid_geometry_request", error=str(exc))
    if not math.isfinite(height_mm) or height_mm <= 0.0:
        _raise("invalid_height_mm", height_mm=getattr(request, "height_mm", None))

    supplied = getattr(request, "source_surface", None)
    prepared = getattr(request, "prepared", None)
    if supplied is not None:
        if not isinstance(supplied, ColorDepthSourceSurface):
            _raise(
                "invalid_source_surface",
                type=type(supplied).__name__,
            )
        vertices_mm = np.asarray(supplied.vertices_mm, dtype=np.float64)
        faces_raw = np.asarray(supplied.faces)
        supplied_labels = np.asarray(supplied.face_target_labels)
        if labels_raw.shape != supplied_labels.shape or not np.array_equal(
            labels_raw, supplied_labels
        ):
            _raise("source_surface_label_mismatch")
        if not math.isclose(
            height_mm,
            float(supplied.height_mm),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            _raise(
                "source_surface_height_mismatch",
                request_height_mm=height_mm,
                source_height_mm=float(supplied.height_mm),
            )
        source_name = str(supplied.source_name)
        source_sha256 = str(supplied.source_sha256)
        source_metadata = dict(supplied.metadata or {})
        declared_volume = float(supplied.source_volume_mm3)
    else:
        if prepared is None:
            _raise("prepared_or_source_surface_required")
        try:
            level = prepared.final
            vertices_unit = np.asarray(level.vertices_unit, dtype=np.float64)
            faces_raw = np.asarray(level.faces)
        except (AttributeError, TypeError, ValueError) as exc:
            _raise("invalid_geometry_request", error=str(exc))
        vertices_mm = vertices_unit * height_mm
        source = getattr(prepared, "source", None)
        path = getattr(source, "path", "prepared-geometry")
        source_name = str(path)
        source_sha256 = str(getattr(source, "sha256", ""))
        source_metadata = {}
        declared_volume = float("nan")
    if (
        vertices_mm.ndim != 2
        or vertices_mm.shape[1:] != (3,)
        or len(vertices_mm) < 4
        or not np.isfinite(vertices_mm).all()
    ):
        _raise("invalid_source_vertices", shape=tuple(vertices_mm.shape))
    if (
        faces_raw.ndim != 2
        or faces_raw.shape[1:] != (3,)
        or not len(faces_raw)
        or not np.issubdtype(faces_raw.dtype, np.integer)
    ):
        _raise("invalid_source_faces", shape=tuple(faces_raw.shape))
    faces = np.asarray(faces_raw, dtype=np.int32)
    if int(faces.min()) < 0 or int(faces.max()) >= len(vertices_mm):
        _raise("source_face_index_out_of_range")
    if labels_raw.shape != (len(faces),) or not np.issubdtype(
        labels_raw.dtype, np.integer
    ):
        _raise(
            "invalid_face_target_labels",
            expected=(int(len(faces)),),
            actual=tuple(labels_raw.shape),
        )
    labels = np.asarray(labels_raw, dtype=np.int32)
    recipe_labels = {int(value) for value in recipes}
    missing = sorted(int(value) for value in set(labels.tolist()) - recipe_labels)
    if missing:
        _raise("source_recipe_missing", target_labels=missing)
    for label, recipe in recipes.items():
        if not isinstance(recipe, ColorDepthRecipe) or recipe.target_label != int(label):
            _raise("invalid_source_recipe", target_label=int(label))

    source_mesh = trimesh.Trimesh(
        vertices=vertices_mm,
        faces=faces,
        process=False,
    )
    if not source_mesh.is_watertight:
        _raise("watertight_source_required")
    if not source_mesh.is_winding_consistent:
        _raise("consistent_source_winding_required")
    source_volume = float(source_mesh.volume)
    if not source_mesh.is_volume or not math.isfinite(source_volume) or source_volume <= 0.0:
        _raise("positive_oriented_source_volume_required", volume_mm3=source_volume)
    if math.isfinite(declared_volume) and not math.isclose(
        source_volume,
        declared_volume,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        _raise(
            "source_surface_volume_mismatch",
            declared_volume_mm3=declared_volume,
            measured_volume_mm3=source_volume,
        )
    return ColorDepthSourceSurface(
        vertices_mm=_immutable(vertices_mm, np.float64),
        faces=_immutable(faces, np.int32),
        face_target_labels=_immutable(labels, np.int32),
        height_mm=height_mm,
        source_name=source_name,
        source_sha256=source_sha256,
        source_volume_mm3=source_volume,
        metadata={
            **source_metadata,
            "schema": COLOR_DEPTH_GEOMETRY_SCHEMA,
            "source_vertices": int(len(vertices_mm)),
            "source_faces": int(len(faces)),
            "target_labels": sorted(int(value) for value in np.unique(labels)),
            "legacy_mix_percentages_used": False,
        },
    )


def _validate_partition_arrays(
    partition: ConformingColorDepthPartition,
    recipes: Mapping[int, ColorDepthRecipe],
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    if not isinstance(partition, ConformingColorDepthPartition):
        _raise("invalid_partition_result", type=type(partition).__name__)
    nodes = np.asarray(partition.nodes_mm, dtype=np.float64)
    tets_raw = np.asarray(partition.tetrahedra)
    owners_raw = np.asarray(partition.cell_owner_labels)
    bounds = np.asarray(partition.cell_depth_bounds_mm, dtype=np.float64)
    materials_raw = np.asarray(partition.cell_materials)
    unsafe_raw = np.asarray(partition.unsafe_outer_only_cells)
    if (
        nodes.ndim != 2
        or nodes.shape[1:] != (3,)
        or len(nodes) < 4
        or not np.isfinite(nodes).all()
    ):
        _raise("invalid_partition_nodes", shape=tuple(nodes.shape))
    if (
        tets_raw.ndim != 2
        or tets_raw.shape[1:] != (4,)
        or not len(tets_raw)
        or not np.issubdtype(tets_raw.dtype, np.integer)
    ):
        _raise("invalid_partition_tetrahedra", shape=tuple(tets_raw.shape))
    tets = np.asarray(tets_raw, dtype=np.int32)
    if int(tets.min()) < 0 or int(tets.max()) >= len(nodes):
        _raise("partition_tetrahedron_index_out_of_range")
    cell_count = len(tets)
    if owners_raw.shape != (cell_count,) or not np.issubdtype(
        owners_raw.dtype, np.integer
    ):
        _raise("invalid_partition_owner_labels")
    owners = np.asarray(owners_raw, dtype=np.int32)
    missing = sorted(int(value) for value in set(owners.tolist()) - set(recipes))
    if missing:
        _raise("partition_owner_recipe_missing", target_labels=missing)
    if bounds.shape != (cell_count, 2) or not np.isfinite(bounds).all():
        _raise("invalid_partition_depth_bounds", shape=tuple(bounds.shape))
    if np.any(bounds < 0.0) or np.any(bounds[:, 1] < bounds[:, 0]):
        _raise("invalid_partition_depth_bounds")
    if materials_raw.shape != (cell_count,) or not np.issubdtype(
        materials_raw.dtype, np.integer
    ):
        _raise("invalid_partition_materials")
    materials = np.asarray(materials_raw, dtype=np.int8)
    invalid_materials = sorted(
        int(value) for value in np.unique(materials) if not 1 <= int(value) <= 4
    )
    if invalid_materials:
        _raise("nonphysical_partition_materials", values=invalid_materials)
    if unsafe_raw.shape != (cell_count,) or unsafe_raw.dtype.kind != "b":
        _raise("invalid_unsafe_outer_only_mask")
    unsafe = np.asarray(unsafe_raw, dtype=bool)
    if partition.threshold_interface_conforming is not True:
        _raise("threshold_interface_not_conforming")
    if partition.shared_interface_partition_exact is not True:
        _raise("shared_interface_partition_proof_required")
    error = float(partition.max_safe_threshold_error_mm)
    limit = float(partition.max_safe_threshold_error_limit_mm)
    if (
        not math.isfinite(error)
        or error < 0.0
        or not math.isfinite(limit)
        or limit <= 0.0
        or limit > _DEFAULT_MAX_SAFE_THRESHOLD_ERROR_MM + 1e-12
        or error > limit + 1e-12
    ):
        _raise(
            "safe_threshold_error_exceeded",
            maximum_error_mm=error,
            limit_mm=limit,
        )

    # Repeat the strict classifier semantics per recipe with NumPy masks.  The
    # real head has several million cells; calling ``physical_at_depth`` once
    # per cell would needlessly turn an already-proved artifact into another
    # hour-long Python loop.
    regular = ~unsafe
    regular_ids = np.flatnonzero(regular)
    for label in np.unique(owners[regular]):
        recipe = recipes[int(label)]
        label_ids = regular_ids[owners[regular_ids] == int(label)]
        label_bounds = bounds[label_ids]
        low = label_bounds[:, 0]
        high = label_bounds[:, 1]
        midpoint = 0.5 * (low + high)
        expected = np.full(len(label_ids), recipe.outer_physical, dtype=np.int8)
        expected[midpoint >= recipe.outer_thickness_mm] = recipe.backing_physical
        thresholds: list[tuple[float, int, int]] = [
            (
                float(recipe.outer_thickness_mm),
                int(recipe.outer_physical),
                int(recipe.backing_physical),
            )
        ]
        if recipe.backing_depth_mm is not None:
            assert recipe.core_physical is not None
            core_threshold = float(
                recipe.outer_thickness_mm + recipe.backing_depth_mm
            )
            expected[midpoint >= core_threshold] = recipe.core_physical
            thresholds.append(
                (
                    core_threshold,
                    int(recipe.backing_physical),
                    int(recipe.core_physical),
                )
            )
        for threshold, before, after in thresholds:
            if before == after:
                continue
            crossing = (low + 1e-9 < threshold) & (
                threshold < high - 1e-9
            )
            if np.any(crossing):
                examples = label_ids[np.flatnonzero(crossing)[:20]]
                _raise(
                    "unsplit_recipe_boundary",
                    crossing_cell_count=int(np.count_nonzero(crossing)),
                    target_label=int(label),
                    threshold_mm=float(threshold),
                    examples=[int(value) for value in examples],
                )
        mismatches = label_ids[materials[label_ids] != expected]
        if len(mismatches):
            _raise(
                "partition_material_recipe_mismatch",
                count=int(len(mismatches)),
                examples=[int(value) for value in mismatches[:20]],
            )
    if np.any(unsafe):
        unsafe_ids = np.flatnonzero(unsafe)
        expected_outer = np.asarray(
            [recipes[int(owners[index])].outer_physical for index in unsafe_ids],
            dtype=np.int8,
        )
        mismatches = unsafe_ids[materials[unsafe_ids] != expected_outer]
        if len(mismatches):
            _raise(
                "unsafe_column_contains_backing_material",
                count=int(len(mismatches)),
                examples=[int(value) for value in mismatches[:20]],
            )
    metadata = dict(partition.metadata or {})
    if metadata.get("legacy_mix_percentages_used") is True:
        _raise("legacy_mix_percentage_forbidden")
    if metadata.get("centroid_approximation") is True:
        _raise("centroid_depth_approximation_forbidden")
    return nodes, tets, owners, bounds, materials, unsafe


def _validate_visible_exterior(
    source: ColorDepthSourceSurface,
    partition: ConformingColorDepthPartition,
    nodes: np.ndarray,
    tets: np.ndarray,
    owners: np.ndarray,
    materials: np.ndarray,
    recipes: Mapping[int, ColorDepthRecipe],
) -> Mapping[str, object]:
    exterior_raw = np.asarray(partition.exterior_faces)
    exterior_cells_raw = np.asarray(partition.exterior_owner_cells)
    parents_raw = np.asarray(partition.exterior_source_face_ids)
    if (
        exterior_raw.ndim != 2
        or exterior_raw.shape[1:] != (3,)
        or not len(exterior_raw)
        or not np.issubdtype(exterior_raw.dtype, np.integer)
    ):
        _raise("invalid_partition_exterior_faces")
    exterior = np.asarray(exterior_raw, dtype=np.int32)
    if int(exterior.min()) < 0 or int(exterior.max()) >= len(nodes):
        _raise("partition_exterior_index_out_of_range")
    count = len(exterior)
    if exterior_cells_raw.shape != (count,) or not np.issubdtype(
        exterior_cells_raw.dtype, np.integer
    ):
        _raise("invalid_partition_exterior_owner_cells")
    exterior_cells = np.asarray(exterior_cells_raw, dtype=np.int32)
    if int(exterior_cells.min()) < 0 or int(exterior_cells.max()) >= len(tets):
        _raise("partition_exterior_owner_out_of_range")
    if parents_raw.shape != (count,) or not np.issubdtype(
        parents_raw.dtype, np.integer
    ):
        _raise("invalid_partition_exterior_source_faces")
    parents = np.asarray(parents_raw, dtype=np.int32)
    if int(parents.min()) < 0 or int(parents.max()) >= len(source.faces):
        _raise("partition_exterior_source_face_out_of_range")

    # Every declared exterior face must be a face of its declared owner cell.
    owner_tets = tets[exterior_cells]
    membership = np.sum(
        exterior[:, :, None] == owner_tets[:, None, :], axis=2
    )
    if np.any(membership != 1):
        _raise(
            "partition_exterior_not_owned_by_cell",
            failures=int(np.count_nonzero(np.any(membership != 1, axis=1))),
        )

    source_triangles = source.vertices_mm[source.faces[parents]]
    child_triangles = nodes[exterior]
    source_normals = np.cross(
        source_triangles[:, 1] - source_triangles[:, 0],
        source_triangles[:, 2] - source_triangles[:, 0],
    )
    child_normals = np.cross(
        child_triangles[:, 1] - child_triangles[:, 0],
        child_triangles[:, 2] - child_triangles[:, 0],
    )
    source_lengths = np.linalg.norm(source_normals, axis=1)
    child_lengths = np.linalg.norm(child_normals, axis=1)
    if np.any(source_lengths <= 1e-14) or np.any(child_lengths <= 1e-14):
        _raise("degenerate_exterior_triangle")
    normal_dot = np.einsum("ij,ij->i", source_normals, child_normals)
    normal_failures = int(np.count_nonzero(normal_dot <= 0.0))
    if normal_failures:
        _raise("exterior_winding_changed", failures=normal_failures)

    unit_normals = source_normals / source_lengths[:, None]
    plane_distance = np.abs(
        np.einsum(
            "nij,nj->ni",
            child_triangles - source_triangles[:, None, 0],
            unit_normals,
        )
    )
    maximum_plane_distance = float(np.max(plane_distance, initial=0.0))
    if maximum_plane_distance > _EXTERIOR_DISTANCE_TOLERANCE_MM:
        _raise(
            "exterior_left_source_surface",
            maximum_distance_mm=maximum_plane_distance,
        )

    repeated_sources = np.repeat(source_triangles, 3, axis=0)
    child_points = child_triangles.reshape((-1, 3))
    barycentric = trimesh.triangles.points_to_barycentric(
        repeated_sources, child_points
    ).reshape((-1, 3, 3))
    minimum_barycentric = float(np.min(barycentric, initial=0.0))
    maximum_barycentric = float(np.max(barycentric, initial=1.0))
    if minimum_barycentric < -1e-8 or maximum_barycentric > 1.0 + 1e-8:
        _raise(
            "exterior_child_outside_source_face",
            minimum_barycentric=minimum_barycentric,
            maximum_barycentric=maximum_barycentric,
        )

    child_area = 0.5 * child_lengths
    covered_area = np.bincount(
        parents, weights=child_area, minlength=len(source.faces)
    )
    source_all = source.vertices_mm[source.faces]
    source_area = 0.5 * np.linalg.norm(
        np.cross(
            source_all[:, 1] - source_all[:, 0],
            source_all[:, 2] - source_all[:, 0],
        ),
        axis=1,
    )
    area_error = np.abs(covered_area - source_area)
    maximum_area_error = float(np.max(area_error, initial=0.0))
    missing_source_faces = int(np.count_nonzero(covered_area == 0.0))
    if missing_source_faces or maximum_area_error > _EXTERIOR_AREA_TOLERANCE_MM2:
        _raise(
            "external_surface_coverage_inexact",
            missing_source_faces=missing_source_faces,
            maximum_area_error_mm2=maximum_area_error,
        )

    expected_labels = source.face_target_labels[parents]
    actual_labels = owners[exterior_cells]
    owner_failures = int(np.count_nonzero(actual_labels != expected_labels))
    if owner_failures:
        _raise("visible_target_owner_changed", failures=owner_failures)
    expected_outer = np.asarray(
        [recipes[int(label)].outer_physical for label in actual_labels],
        dtype=np.int8,
    )
    material_failures = int(
        np.count_nonzero(materials[exterior_cells] != expected_outer)
    )
    if material_failures:
        _raise("backing_material_exposed", failures=material_failures)
    return {
        "source_parent_faces": int(len(source.faces)),
        "exterior_child_faces": int(len(exterior)),
        "missing_source_faces": 0,
        "maximum_plane_distance_mm": maximum_plane_distance,
        "maximum_parent_area_error_mm2": maximum_area_error,
        "minimum_child_barycentric": minimum_barycentric,
        "maximum_child_barycentric": maximum_barycentric,
        "normal_direction_failures": 0,
        "owner_label_failures": 0,
        "outer_material_failures": 0,
        "external_surface_coverage_exact": True,
    }


def build_color_depth_result_from_partition(
    source: ColorDepthSourceSurface,
    recipes: Mapping[int, ColorDepthRecipe],
    partition: ConformingColorDepthPartition,
    *,
    material_surface_builder: ColorDepthMaterialSurfaceBuilder | None = None,
) -> ColorDepthCellResult:
    """Validate an exact partition and return physical material unions."""

    nodes, tets, owners, _bounds, materials, unsafe = _validate_partition_arrays(
        partition, recipes
    )
    exterior = _validate_visible_exterior(
        source, partition, nodes, tets, owners, materials, recipes
    )
    # The production manifoldizer uses one coordinate-face subdivision
    # registry across every physical material.  The older strict extractor is
    # retained as an explicit injectable test/diagnostic strategy only; it
    # cannot repair a multi-sector material edge while preserving a shared
    # counterpart partition.
    builder = material_surface_builder or _shared_material_surface_builder
    result = builder(
        nodes,
        tets,
        materials,
        cell_owner_labels=owners,
        require_single_source_component=False,
    )
    volume_error = abs(float(result.source_volume_mm3) - source.source_volume_mm3)
    if volume_error > 1e-8 * max(source.source_volume_mm3, 1.0):
        _raise(
            "partition_source_volume_mismatch",
            prepared_source_volume_mm3=source.source_volume_mm3,
            partition_volume_mm3=float(result.source_volume_mm3),
            absolute_error_mm3=volume_error,
        )
    metadata = {
        **dict(result.metadata),
        "schema": COLOR_DEPTH_GEOMETRY_SCHEMA,
        "cell_schema": COLOR_DEPTH_SCHEMA,
        "renderer": "ColorDepth Lab",
        "experimental": True,
        "uncalibrated": not all(recipe.calibrated for recipe in recipes.values()),
        "slice_only": True,
        "print_allowed": False,
        "physical_materials_only": True,
        "ratio_definitions": 0,
        "cycle_definitions": 0,
        "virtual_mix_definitions": 0,
        "painted_triangles": 0,
        "legacy_mix_percentages_used": False,
        "centroid_approximation": False,
        "shared_interface_partition_exact": True,
        "external_surface_coverage_exact": True,
        "unsafe_columns_outer_only_verified": True,
        "unsafe_outer_only_cells": int(np.count_nonzero(unsafe)),
        "threshold_interface_conforming": True,
        "maximum_safe_threshold_error_mm": float(
            partition.max_safe_threshold_error_mm
        ),
        "maximum_safe_threshold_error_limit_mm": float(
            partition.max_safe_threshold_error_limit_mm
        ),
        "visible_exterior": exterior,
        "partition": dict(partition.metadata or {}),
        "source": dict(source.metadata or {}),
        "source_volume_mm3": float(result.source_volume_mm3),
        "output_volume_mm3": float(result.output_volume_mm3),
        "volume_error_mm3": abs(
            float(result.output_volume_mm3) - float(result.source_volume_mm3)
        ),
        "positive_overlap_mm3": 0.0,
        "gap_mm": 0.0,
    }
    return ColorDepthCellResult(
        parts=result.parts,
        interfaces=result.interfaces,
        source_volume_mm3=result.source_volume_mm3,
        output_volume_mm3=result.output_volume_mm3,
        cell_materials=result.cell_materials,
        metadata=metadata,
    )


def build_color_depth_head_materials(
    request: "ColorDepthGeometryRequest | object",
    *,
    partition_provider: ColorDepthPartitionProvider | None = None,
    material_surface_builder: ColorDepthMaterialSurfaceBuilder | None = None,
) -> ColorDepthCellResult:
    """Canonical ``ColorDepthGeometryRequest -> ColorDepthCellResult`` entry.

    The historical function name is retained because it is already the GUI
    facade's first lazy-load candidate; the implementation itself is not
    head-specific.
    """

    source = prepare_color_depth_source(request)
    recipes = request.recipes
    provider = partition_provider or _load_default_partition_provider()
    partition = provider(
        source,
        recipes,
        progress=getattr(request, "progress", None),
    )
    return build_color_depth_result_from_partition(
        source,
        recipes,
        partition,
        material_surface_builder=material_surface_builder,
    )


# A descriptive alias for non-head callers and future documentation.
build_color_depth_geometry = build_color_depth_head_materials


__all__ = [
    "COLOR_DEPTH_GEOMETRY_SCHEMA",
    "ColorDepthGeometryError",
    "ColorDepthMaterialSurfaceBuilder",
    "ColorDepthPartitionProvider",
    "ColorDepthSourceSurface",
    "ConformingColorDepthPartition",
    "build_color_depth_geometry",
    "build_color_depth_head_materials",
    "build_color_depth_result_from_partition",
    "prepare_color_depth_source",
]
