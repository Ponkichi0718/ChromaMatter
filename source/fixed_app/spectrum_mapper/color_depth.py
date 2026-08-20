"""Physical-material cell partitioning for the ColorDepth Lab renderer.

ColorDepth Lab is intentionally separate from the legacy FullSpectrum
Ratio/Cycle renderer.  A target colour label resolves through a measured LUT
to an ordered physical recipe (visible outer material, backing material and,
optionally, a finite backing depth plus a core material).  No virtual mixed
filament state is emitted.

This module owns the fail-closed geometry boundary of the experiment.  It
does *not* guess a colour recipe and it does not approximate a recipe boundary
with tetrahedron centroids.  The caller must supply a conforming tetrahedral
cell complex whose cells do not straddle any material-changing depth
threshold.  Cells are then labelled with physical extruders 1..4 and merged
topologically into at most four exact-touch normal-part surfaces.

The separate owner/depth field builder may refine or split cells before this
module is called.  Keeping that producer behind this small array contract lets
the real-head prototype improve without weakening the archive validator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping, Sequence

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import trimesh

from .assembly import _edge_topology
from .volume_partition import (
    TET_LOCAL_FACES,
    _tetra_face_table,
    _tetra_volumes,
)


COLOR_DEPTH_SCHEMA = "tripo-spectrum-mapper.color-depth.cells.v1"
_GEOMETRY_EPSILON = 1e-14
_VOLUME_RELATIVE_TOLERANCE = 1e-9


class ColorDepthError(RuntimeError):
    """Stable diagnostic error for a rejected ColorDepth operation."""

    def __init__(
        self,
        code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(self.code)


def _raise(code: str, **details: object) -> None:
    raise ColorDepthError(code, details)


def _physical(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        _raise("invalid_physical_material", field=field_name, value=value)
    try:
        result = int(value)
    except (TypeError, ValueError):
        _raise("invalid_physical_material", field=field_name, value=value)
    if result < 1 or result > 4:
        _raise("invalid_physical_material", field=field_name, value=result)
    return result


@dataclass(frozen=True, slots=True)
class ColorDepthRecipe:
    """One explicit target-label to ordered physical-depth recipe.

    ``backing_depth_mm`` is measured inward from the end of the outer layer.
    When it is omitted, the backing material fills the remaining body.  When
    it is supplied, ``core_physical`` is required and fills all greater depth.

    ``calibrated`` and ``calibration_id`` record LUT provenance only.  The
    geometry engine accepts an uncalibrated recipe for a slice-only laboratory
    probe, but never manufactures one implicitly.
    """

    target_label: int
    outer_physical: int
    outer_thickness_mm: float
    backing_physical: int
    backing_depth_mm: float | None = None
    core_physical: int | None = None
    target_lab: tuple[float, float, float] | None = None
    calibrated: bool = False
    calibration_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.target_label, bool) or int(self.target_label) < 0:
            _raise("invalid_target_label", target_label=self.target_label)
        object.__setattr__(self, "target_label", int(self.target_label))
        object.__setattr__(
            self,
            "outer_physical",
            _physical(self.outer_physical, field_name="outer_physical"),
        )
        object.__setattr__(
            self,
            "backing_physical",
            _physical(self.backing_physical, field_name="backing_physical"),
        )
        thickness = float(self.outer_thickness_mm)
        if not math.isfinite(thickness) or thickness <= 0.0:
            _raise(
                "invalid_outer_thickness",
                outer_thickness_mm=self.outer_thickness_mm,
            )
        object.__setattr__(self, "outer_thickness_mm", thickness)

        if self.backing_depth_mm is None:
            if self.core_physical is not None:
                _raise("core_requires_finite_backing_depth")
        else:
            depth = float(self.backing_depth_mm)
            if not math.isfinite(depth) or depth <= 0.0:
                _raise(
                    "invalid_backing_depth",
                    backing_depth_mm=self.backing_depth_mm,
                )
            if self.core_physical is None:
                _raise("finite_backing_depth_requires_core")
            object.__setattr__(self, "backing_depth_mm", depth)
            object.__setattr__(
                self,
                "core_physical",
                _physical(self.core_physical, field_name="core_physical"),
            )

        if self.target_lab is not None:
            lab = tuple(float(value) for value in self.target_lab)
            if len(lab) != 3 or not all(math.isfinite(value) for value in lab):
                _raise("invalid_target_lab", target_lab=self.target_lab)
            object.__setattr__(self, "target_lab", lab)
        if self.calibrated and not str(self.calibration_id or "").strip():
            _raise("calibrated_recipe_requires_calibration_id")

    @property
    def material_thresholds_mm(self) -> tuple[float, ...]:
        values = [self.outer_thickness_mm]
        if self.backing_depth_mm is not None:
            values.append(self.outer_thickness_mm + self.backing_depth_mm)
        return tuple(values)

    def physical_at_depth(self, depth_mm: float) -> int:
        depth = float(depth_mm)
        if not math.isfinite(depth) or depth < 0.0:
            _raise("invalid_depth", depth_mm=depth_mm)
        if depth < self.outer_thickness_mm:
            return self.outer_physical
        if self.backing_depth_mm is None:
            return self.backing_physical
        if depth < self.outer_thickness_mm + self.backing_depth_mm:
            return self.backing_physical
        assert self.core_physical is not None
        return self.core_physical


@dataclass(frozen=True, slots=True)
class ColorDepthCellAssignment:
    """Physical material labels for an already conforming cell complex."""

    cell_materials: np.ndarray
    owner_labels: np.ndarray
    depth_bounds_mm: np.ndarray
    recipe_labels: tuple[int, ...]
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ColorDepthMaterialPart:
    """One physical material union, possibly with disconnected bodies."""

    name: str
    vertices_mm: np.ndarray
    faces: np.ndarray
    extruder: int
    role: str = "color_depth_physical_union"
    solid_infill: bool = True
    source_labels: tuple[int, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def physical_filament(self) -> int:
        return self.extruder


@dataclass(frozen=True, slots=True)
class ColorDepthCellResult:
    """Validated physical-material union surfaces from labelled cells."""

    parts: tuple[ColorDepthMaterialPart, ...]
    interfaces: tuple[Mapping[str, object], ...]
    source_volume_mm3: float
    output_volume_mm3: float
    cell_materials: np.ndarray
    metadata: Mapping[str, object]


def _immutable(values: np.ndarray, dtype: np.dtype) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype).copy()
    result.flags.writeable = False
    return result


def _validated_recipe_map(
    recipes: Mapping[int, ColorDepthRecipe],
) -> dict[int, ColorDepthRecipe]:
    result: dict[int, ColorDepthRecipe] = {}
    for raw_label, recipe in recipes.items():
        if isinstance(raw_label, bool):
            _raise("invalid_target_label", target_label=raw_label)
        label = int(raw_label)
        if not isinstance(recipe, ColorDepthRecipe):
            _raise("invalid_recipe", target_label=label)
        if recipe.target_label != label:
            _raise(
                "recipe_label_mismatch",
                mapping_label=label,
                recipe_label=recipe.target_label,
            )
        result[label] = recipe
    if not result:
        _raise("recipes_required")
    return result


def classify_color_depth_cells(
    owner_labels: np.ndarray,
    depth_bounds_mm: np.ndarray,
    recipes: Mapping[int, ColorDepthRecipe],
    *,
    boundary_tolerance_mm: float = 1e-9,
) -> ColorDepthCellAssignment:
    """Resolve pre-segmented cells to physical F1..F4 materials.

    A cell whose depth interval crosses a threshold that changes material is
    rejected.  The owner/depth producer must split that cell on the threshold
    surface and call this function again; midpoint labelling is forbidden.
    """

    labels_raw = np.asarray(owner_labels)
    bounds = np.asarray(depth_bounds_mm, dtype=np.float64)
    if labels_raw.ndim != 1 or not np.issubdtype(labels_raw.dtype, np.integer):
        _raise("invalid_owner_labels", shape=tuple(labels_raw.shape))
    labels = np.asarray(labels_raw, dtype=np.int32)
    if bounds.shape != (len(labels), 2):
        _raise(
            "invalid_depth_bounds",
            expected=(int(len(labels)), 2),
            actual=tuple(bounds.shape),
        )
    if (
        not np.isfinite(bounds).all()
        or np.any(bounds < 0.0)
        or np.any(bounds[:, 1] < bounds[:, 0])
    ):
        _raise("invalid_depth_bounds")
    tolerance = float(boundary_tolerance_mm)
    if not math.isfinite(tolerance) or tolerance < 0.0:
        _raise(
            "invalid_boundary_tolerance",
            boundary_tolerance_mm=boundary_tolerance_mm,
        )
    recipe_map = _validated_recipe_map(recipes)
    unknown = sorted(int(value) for value in set(labels) - set(recipe_map))
    if unknown:
        _raise("owner_recipe_missing", owner_labels=unknown)

    materials = np.empty(len(labels), dtype=np.int8)
    crossings: list[dict[str, object]] = []
    for cell_id, (label, bounds_row) in enumerate(
        zip(labels, bounds, strict=True)
    ):
        recipe = recipe_map[int(label)]
        low, high = map(float, bounds_row)
        midpoint = 0.5 * (low + high)
        material = recipe.physical_at_depth(midpoint)
        for threshold in recipe.material_thresholds_mm:
            if low + tolerance < threshold < high - tolerance:
                before = recipe.physical_at_depth(
                    max(0.0, threshold - max(tolerance, 1e-12))
                )
                after = recipe.physical_at_depth(
                    threshold + max(tolerance, 1e-12)
                )
                if before != after:
                    crossings.append(
                        {
                            "cell_id": int(cell_id),
                            "target_label": int(label),
                            "depth_min_mm": low,
                            "depth_max_mm": high,
                            "threshold_mm": float(threshold),
                            "outer_side_physical": int(before),
                            "inner_side_physical": int(after),
                        }
                    )
                    break
        materials[cell_id] = material
    if crossings:
        _raise(
            "unsplit_recipe_boundary",
            crossing_cell_count=int(len(crossings)),
            examples=crossings[:20],
        )

    return ColorDepthCellAssignment(
        cell_materials=_immutable(materials, np.int8),
        owner_labels=_immutable(labels, np.int32),
        depth_bounds_mm=_immutable(bounds, np.float64),
        recipe_labels=tuple(sorted(recipe_map)),
        metadata={
            "schema": COLOR_DEPTH_SCHEMA,
            "cell_count": int(len(labels)),
            "material_cell_counts": {
                str(int(material)): int(count)
                for material, count in zip(
                    *np.unique(materials, return_counts=True), strict=True
                )
            },
            "target_label_count": int(len(np.unique(labels))),
            "calibrated_recipe_count": int(
                sum(recipe.calibrated for recipe in recipe_map.values())
            ),
            "uncalibrated_recipe_labels": [
                int(label)
                for label, recipe in sorted(recipe_map.items())
                if not recipe.calibrated
            ],
            "centroid_approximation": False,
            "unsplit_threshold_crossings": 0,
        },
    )


def _validate_cell_complex(
    nodes_mm: np.ndarray,
    tetrahedra: np.ndarray,
    cell_materials: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    nodes = np.asarray(nodes_mm, dtype=np.float64)
    raw_tets = np.asarray(tetrahedra)
    raw_materials = np.asarray(cell_materials)
    if nodes.ndim != 2 or nodes.shape[1:] != (3,) or len(nodes) < 4:
        _raise("invalid_cell_nodes", shape=tuple(nodes.shape))
    if not np.isfinite(nodes).all():
        _raise("nonfinite_cell_nodes")
    if raw_tets.ndim != 2 or raw_tets.shape[1:] != (4,) or not len(raw_tets):
        _raise("invalid_tetrahedra", shape=tuple(raw_tets.shape))
    if not np.issubdtype(raw_tets.dtype, np.integer):
        _raise("noninteger_tetrahedra")
    tets = np.asarray(raw_tets, dtype=np.int32)
    if int(tets.min()) < 0 or int(tets.max()) >= len(nodes):
        _raise("tetrahedron_index_out_of_range")
    if np.any(np.diff(np.sort(tets, axis=1), axis=1) == 0):
        _raise("repeated_tetrahedron_vertex")
    if raw_materials.shape != (len(tets),) or not np.issubdtype(
        raw_materials.dtype, np.integer
    ):
        _raise(
            "invalid_cell_materials",
            expected=(int(len(tets)),),
            actual=tuple(raw_materials.shape),
        )
    materials = np.asarray(raw_materials, dtype=np.int8)
    invalid = sorted(
        int(value) for value in np.unique(materials) if not 1 <= int(value) <= 4
    )
    if invalid:
        _raise("invalid_cell_materials", values=invalid)
    volumes = _tetra_volumes(nodes, tets)
    total = float(volumes.sum())
    # TetGen can retain a tiny but strictly positive cell when the preserved
    # source contains a near-overlap segment (the real head has one 8.1e-13
    # mm3 cell).  Removing it would open the conforming complex, so reject only
    # values at a scale consistent with numerical zero.
    minimum = max(total * 1e-18, 1e-18)
    bad = np.flatnonzero(~np.isfinite(volumes) | (volumes <= minimum))
    if len(bad):
        _raise(
            "degenerate_tetrahedra",
            count=int(len(bad)),
            examples=[int(value) for value in bad[:20]],
        )
    return nodes.copy(), tets.copy(), materials.copy(), volumes


def _oriented_face_rows(
    nodes: np.ndarray,
    tetrahedra: np.ndarray,
    raw_faces: np.ndarray,
    rows: np.ndarray,
) -> np.ndarray:
    """Orient selected flattened tet faces outward, vectorized for head meshes."""

    selected = np.asarray(rows, dtype=np.int64)
    faces = np.asarray(raw_faces[selected], dtype=np.int32).copy()
    if not len(faces):
        return faces.reshape((-1, 3))
    owners = (selected // 4).astype(np.int64)
    opposite_local = (selected % 4).astype(np.int64)
    opposite_ids = tetrahedra[owners, opposite_local]
    first = nodes[faces[:, 0]]
    normals = np.cross(
        nodes[faces[:, 1]] - first,
        nodes[faces[:, 2]] - first,
    )
    inward = np.einsum(
        "ij,ij->i", normals, nodes[opposite_ids] - first
    ) > 0.0
    if np.any(inward):
        faces[inward, 1:3] = faces[inward, 2:0:-1]
    return faces


def _compact_surface(
    nodes: np.ndarray,
    faces: Sequence[np.ndarray] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    global_faces = np.asarray(faces, dtype=np.int32).reshape((-1, 3))
    used = np.unique(global_faces)
    remap = np.full(len(nodes), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    return (
        np.asarray(nodes[used], dtype=np.float64),
        remap[global_faces].astype(np.int32),
    )


def _signed_surface_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    triangles = vertices[faces]
    return float(
        np.einsum(
            "ij,ij->i",
            triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2]),
        ).sum()
        / 6.0
    )


def _face_connected_material_components(
    tetrahedra: np.ndarray,
    materials: np.ndarray,
    first_owners: np.ndarray,
    second_owners: np.ndarray,
    *,
    material: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return material cells and their face-connected component labels."""

    material_cells = np.flatnonzero(materials == int(material)).astype(
        np.int32
    )
    cell_remap = np.full(len(tetrahedra), -1, dtype=np.int32)
    cell_remap[material_cells] = np.arange(
        len(material_cells), dtype=np.int32
    )
    same = (materials[first_owners] == int(material)) & (
        materials[second_owners] == int(material)
    )
    first_local = cell_remap[first_owners[same]]
    second_local = cell_remap[second_owners[same]]
    graph = coo_matrix(
        (
            np.ones(2 * len(first_local), dtype=np.uint8),
            (
                np.concatenate((first_local, second_local)),
                np.concatenate((second_local, first_local)),
            ),
        ),
        shape=(len(material_cells), len(material_cells)),
    ).tocsr()
    component_count, local_components = connected_components(
        graph, directed=False, return_labels=True
    )
    global_components = np.full(len(tetrahedra), -1, dtype=np.int32)
    global_components[material_cells] = local_components
    return material_cells, global_components, int(component_count)


def audit_material_union_topology(
    nodes_mm: np.ndarray,
    tetrahedra: np.ndarray,
    cell_materials: np.ndarray,
) -> Mapping[str, object]:
    """Audit all physical unions without stopping at the first bad material.

    This lightweight report is the feedback contract for a future edge-fan
    regulariser.  It intentionally does not mutate labels or hide a defect.
    ``extract_material_union_surfaces`` remains the authoritative strict gate.
    """

    nodes, tets, materials, _volumes = _validate_cell_complex(
        nodes_mm, tetrahedra, cell_materials
    )
    raw_faces, order, starts, counts = _tetra_face_table(tets)
    nonmanifold_complex_faces = int(np.count_nonzero(counts > 2))
    external_rows = order[starts[counts == 1]]
    external_owners = (external_rows // 4).astype(np.int32)
    paired_starts = starts[counts == 2]
    first_rows = order[paired_starts]
    second_rows = order[paired_starts + 1]
    first_owners = (first_rows // 4).astype(np.int32)
    second_owners = (second_rows // 4).astype(np.int32)
    first_materials = materials[first_owners]
    second_materials = materials[second_owners]
    different = first_materials != second_materials

    per_material: dict[str, object] = {}
    for material in sorted(int(value) for value in np.unique(materials)):
        rows = np.concatenate(
            (
                external_rows[materials[external_owners] == material],
                first_rows[different & (first_materials == material)],
                second_rows[different & (second_materials == material)],
            )
        )
        faces = raw_faces[rows]
        topology = _edge_topology(faces, len(nodes))
        per_material[str(material)] = {
            "physical_material": int(material),
            "cells": int(np.count_nonzero(materials == material)),
            "faces": int(len(faces)),
            "topology": topology,
            "printable_closed_oriented_2_manifold": bool(
                topology["watertight"]
                and not int(topology["inconsistent_winding_edges"])
            ),
        }
    return {
        "schema": COLOR_DEPTH_SCHEMA,
        "cell_count": int(len(tets)),
        "source_cell_complex_nonmanifold_faces": nonmanifold_complex_faces,
        "materials": per_material,
        "all_material_unions_printable": bool(
            not nonmanifold_complex_faces
            and all(
                bool(item["printable_closed_oriented_2_manifold"])
                for item in per_material.values()
            )
        ),
    }


def audit_material_cell_components(
    nodes_mm: np.ndarray,
    tetrahedra: np.ndarray,
    cell_materials: np.ndarray,
) -> Mapping[str, object]:
    """Separate edge/point touching bodies from defects inside one cell body.

    Orca normal parts may contain multiple disconnected closed bodies, but
    welding bodies which touch only at an edge or point makes the combined
    triangle mesh nonmanifold.  This audit labels face-connected cells for
    each material and validates each body independently.  It is diagnostic;
    the exporter still blocks until *every* component is a 2-manifold.
    """

    nodes, tets, materials, _volumes = _validate_cell_complex(
        nodes_mm, tetrahedra, cell_materials
    )
    raw_faces, order, starts, counts = _tetra_face_table(tets)
    external_rows = order[starts[counts == 1]]
    external_owners = (external_rows // 4).astype(np.int32)
    paired_starts = starts[counts == 2]
    first_rows = order[paired_starts]
    second_rows = order[paired_starts + 1]
    first_owners = (first_rows // 4).astype(np.int32)
    second_owners = (second_rows // 4).astype(np.int32)
    first_materials = materials[first_owners]
    second_materials = materials[second_owners]
    different = first_materials != second_materials
    per_material: dict[str, object] = {}
    all_printable = True
    for material in sorted(int(value) for value in np.unique(materials)):
        (
            material_cells,
            global_components,
            component_count,
        ) = _face_connected_material_components(
            tets,
            materials,
            first_owners,
            second_owners,
            material=material,
        )
        surface_rows = np.concatenate(
            (
                external_rows[materials[external_owners] == material],
                first_rows[different & (first_materials == material)],
                second_rows[different & (second_materials == material)],
            )
        )
        surface_components = global_components[surface_rows // 4]
        bad_components: list[dict[str, object]] = []
        face_counts = np.bincount(
            surface_components, minlength=int(component_count)
        )
        for component_id in range(int(component_count)):
            faces = raw_faces[surface_rows[surface_components == component_id]]
            topology = _edge_topology(faces, len(nodes))
            if (
                not bool(topology["watertight"])
                or int(topology["inconsistent_winding_edges"])
            ):
                bad_components.append(
                    {
                        "component_id": int(component_id),
                        "faces": int(len(faces)),
                        "cells": int(
                            np.count_nonzero(
                                global_components[material_cells]
                                == component_id
                            )
                        ),
                        "topology": topology,
                    }
                )
        if bad_components:
            all_printable = False
        per_material[str(material)] = {
            "physical_material": int(material),
            "cells": int(len(material_cells)),
            "face_connected_components": int(component_count),
            "bad_components": int(len(bad_components)),
            "printable_components": int(component_count - len(bad_components)),
            "singleton_tetrahedron_components": int(
                np.count_nonzero(face_counts == 4)
            ),
            "largest_surface_faces": int(np.max(face_counts, initial=0)),
            "bad_component_details": bad_components,
        }
    return {
        "schema": COLOR_DEPTH_SCHEMA,
        "cell_count": int(len(tets)),
        "materials": per_material,
        "all_face_connected_material_bodies_printable": bool(all_printable),
    }


def extract_material_union_surfaces(
    nodes_mm: np.ndarray,
    tetrahedra: np.ndarray,
    cell_materials: np.ndarray,
    *,
    cell_owner_labels: np.ndarray | None = None,
    require_single_source_component: bool = True,
) -> ColorDepthCellResult:
    """Extract at most four closed physical unions from a conforming tet mesh."""

    nodes, tets, materials, tet_volumes = _validate_cell_complex(
        nodes_mm, tetrahedra, cell_materials
    )
    if cell_owner_labels is None:
        owners = np.full(len(tets), -1, dtype=np.int32)
    else:
        owner_raw = np.asarray(cell_owner_labels)
        if owner_raw.shape != (len(tets),) or not np.issubdtype(
            owner_raw.dtype, np.integer
        ):
            _raise("invalid_cell_owner_labels")
        owners = np.asarray(owner_raw, dtype=np.int32)

    # Do not build a Python dictionary with ~3.3 million entries for the real
    # head.  The shared volume-partition face table sorts canonical index
    # triples in contiguous arrays and keeps peak memory bounded.
    raw_faces, order, starts, counts = _tetra_face_table(tets)
    nonmanifold_starts = starts[counts > 2]
    if len(nonmanifold_starts):
        examples = np.sort(raw_faces[order[nonmanifold_starts[:20]]], axis=1)
        _raise(
            "nonmanifold_cell_complex",
            face_count=int(len(nonmanifold_starts)),
            examples=examples.astype(int).tolist(),
        )

    external_rows = order[starts[counts == 1]]
    external_owners = (external_rows // 4).astype(np.int32)
    paired_starts = starts[counts == 2]
    first_rows = order[paired_starts]
    second_rows = order[paired_starts + 1]
    first_owners = (first_rows // 4).astype(np.int32)
    second_owners = (second_rows // 4).astype(np.int32)

    # Face adjacency is the volumetric connectivity definition.  Use SciPy's
    # compiled graph traversal instead of a Python union loop over ~1.5M faces.
    adjacency_rows = np.concatenate((first_owners, second_owners))
    adjacency_columns = np.concatenate((second_owners, first_owners))
    adjacency = coo_matrix(
        (
            np.ones(len(adjacency_rows), dtype=np.uint8),
            (adjacency_rows, adjacency_columns),
        ),
        shape=(len(tets), len(tets)),
    ).tocsr()
    component_count = int(
        connected_components(
            adjacency, directed=False, return_labels=False
        )
    )
    if require_single_source_component and component_count != 1:
        _raise(
            "single_source_component_required",
            source_component_count=int(component_count),
        )

    first_materials = materials[first_owners]
    second_materials = materials[second_owners]
    different = first_materials != second_materials
    interface_first_rows = first_rows[different]
    interface_second_rows = second_rows[different]
    interface_first_materials = first_materials[different]
    interface_second_materials = second_materials[different]

    # Validate every two-sided physical interface once before compaction.
    oriented_first = _oriented_face_rows(
        nodes, tets, raw_faces, interface_first_rows
    )
    oriented_second = _oriented_face_rows(
        nodes, tets, raw_faces, interface_second_rows
    )
    first_points = nodes[oriented_first]
    second_points = nodes[oriented_second]
    first_normals = np.cross(
        first_points[:, 1] - first_points[:, 0],
        first_points[:, 2] - first_points[:, 0],
    )
    second_normals = np.cross(
        second_points[:, 1] - second_points[:, 0],
        second_points[:, 2] - second_points[:, 0],
    )
    orientation_failures = int(
        np.count_nonzero(
            np.einsum("ij,ij->i", first_normals, second_normals) >= 0.0
        )
    )
    if orientation_failures:
        _raise(
            "material_interface_orientation_mismatch",
            failures=orientation_failures,
        )

    source_volume = float(tet_volumes.sum())
    parts: list[ColorDepthMaterialPart] = []
    part_records: dict[str, object] = {}
    for material in sorted(int(value) for value in np.unique(materials)):
        material_external_rows = external_rows[
            materials[external_owners] == material
        ]
        material_first_rows = interface_first_rows[
            interface_first_materials == material
        ]
        material_second_rows = interface_second_rows[
            interface_second_materials == material
        ]
        material_rows = np.concatenate(
            (
                material_external_rows,
                material_first_rows,
                material_second_rows,
            )
        )
        (
            material_cells,
            global_components,
            component_count,
        ) = _face_connected_material_components(
            tets,
            materials,
            first_owners,
            second_owners,
            material=material,
        )
        row_components = global_components[material_rows // 4]
        component_vertices: list[np.ndarray] = []
        component_faces: list[np.ndarray] = []
        component_records: list[dict[str, object]] = []
        vertex_offset = 0
        signed_volume = 0.0
        for component_id in range(component_count):
            rows = material_rows[row_components == component_id]
            oriented = _oriented_face_rows(nodes, tets, raw_faces, rows)
            component_topology = _edge_topology(oriented, len(nodes))
            if (
                not bool(component_topology["watertight"])
                or int(component_topology["inconsistent_winding_edges"])
            ):
                _raise(
                    "material_component_not_closed_oriented",
                    physical_material=int(material),
                    component_id=int(component_id),
                    topology=component_topology,
                    cells=int(
                        np.count_nonzero(
                            global_components[material_cells] == component_id
                        )
                    ),
                    faces=int(len(oriented)),
                )
            compact_vertices, compact_faces = _compact_surface(nodes, oriented)
            component_volume = _signed_surface_volume(
                compact_vertices, compact_faces
            )
            component_expected = float(
                tet_volumes[
                    (materials == material)
                    & (global_components == component_id)
                ].sum()
            )
            component_error = abs(component_volume - component_expected)
            if (
                not math.isfinite(component_volume)
                or component_volume <= _GEOMETRY_EPSILON
                or component_error
                > _VOLUME_RELATIVE_TOLERANCE
                * max(component_expected, 1.0)
            ):
                _raise(
                    "material_component_volume_mismatch",
                    physical_material=int(material),
                    component_id=int(component_id),
                    signed_volume_mm3=component_volume,
                    expected_cell_volume_mm3=component_expected,
                    volume_error_mm3=component_error,
                )
            component_vertices.append(compact_vertices)
            component_faces.append(compact_faces + vertex_offset)
            vertex_offset += len(compact_vertices)
            signed_volume += component_volume
            component_records.append(
                {
                    "component_id": int(component_id),
                    "cells": int(
                        np.count_nonzero(
                            global_components[material_cells] == component_id
                        )
                    ),
                    "vertices": int(len(compact_vertices)),
                    "faces": int(len(compact_faces)),
                    "signed_volume_mm3": component_volume,
                    "expected_cell_volume_mm3": component_expected,
                    "topology": component_topology,
                }
            )
        vertices = np.vstack(component_vertices)
        faces = np.vstack(component_faces).astype(np.int32)
        topology = _edge_topology(faces, len(vertices))
        # Components which touch only at a geometric edge or point get
        # independent vertex indices.  This preserves four maximum physical
        # normal parts while keeping every indexed body a closed 2-manifold.
        duplicate_faces = 0
        expected_volume = float(tet_volumes[materials == material].sum())
        volume_error = abs(signed_volume - expected_volume)
        tolerance = _VOLUME_RELATIVE_TOLERANCE * max(expected_volume, 1.0)
        if (
            not bool(topology["watertight"])
            or int(topology["inconsistent_winding_edges"])
            or duplicate_faces
            or not math.isfinite(signed_volume)
            or signed_volume <= _GEOMETRY_EPSILON
            or volume_error > tolerance
        ):
            _raise(
                "material_union_not_closed_oriented",
                physical_material=int(material),
                topology=topology,
                duplicate_coordinate_faces=duplicate_faces,
                signed_volume_mm3=signed_volume,
                expected_cell_volume_mm3=expected_volume,
                volume_error_mm3=volume_error,
            )
        surface_components = int(component_count)
        source_labels = tuple(
            sorted(int(value) for value in np.unique(owners[materials == material]) if value >= 0)
        )
        record = {
            "physical_material": int(material),
            "cells": int(np.count_nonzero(materials == material)),
            "vertices": int(len(vertices)),
            "faces": int(len(faces)),
            "surface_components": surface_components,
            "signed_volume_mm3": signed_volume,
            "expected_cell_volume_mm3": expected_volume,
            "volume_error_mm3": volume_error,
            "topology": topology,
            "duplicate_coordinate_faces": 0,
            "source_labels": [int(value) for value in source_labels],
            "face_connected_component_records": component_records,
            "edge_or_point_touch_uses_disjoint_vertex_indices": True,
        }
        part_records[str(material)] = record
        parts.append(
            ColorDepthMaterialPart(
                name=f"ColorDepth physical F{material}",
                vertices_mm=_immutable(vertices, np.float64),
                faces=_immutable(faces, np.int32),
                extruder=int(material),
                source_labels=source_labels,
                metadata={
                    "schema": COLOR_DEPTH_SCHEMA,
                    "physical_material_only": True,
                    "sparse_infill_density_percent": 100,
                    "validation": record,
                },
            )
        )

    interface_records: list[Mapping[str, object]] = []
    interface_triangle_total = int(np.count_nonzero(different))
    low_materials = np.minimum(
        interface_first_materials, interface_second_materials
    ).astype(np.int8)
    high_materials = np.maximum(
        interface_first_materials, interface_second_materials
    ).astype(np.int8)
    pair_codes = low_materials.astype(np.int16) * 5 + high_materials
    for pair_code, pair_count in zip(
        *np.unique(pair_codes, return_counts=True), strict=True
    ):
        first_material = int(pair_code // 5)
        second_material = int(pair_code % 5)
        interface_records.append(
            {
                "name": f"F{first_material}__F{second_material}",
                "physical_materials": [first_material, second_material],
                "faces": int(pair_count),
                "exact_coordinate_triangles": True,
                "opposite_winding": True,
                "gap_mm": 0.0,
                "positive_overlap_mm3": 0.0,
            }
        )

    output_volume = float(
        sum(float(part.metadata["validation"]["signed_volume_mm3"]) for part in parts)
    )
    volume_error = abs(output_volume - source_volume)
    if volume_error > _VOLUME_RELATIVE_TOLERANCE * max(source_volume, 1.0):
        _raise(
            "material_volume_drift",
            source_volume_mm3=source_volume,
            output_volume_mm3=output_volume,
            absolute_error_mm3=volume_error,
        )
    output_face_count = sum(len(part.faces) for part in parts)
    expected_output_faces = len(external_rows) + 2 * interface_triangle_total
    if output_face_count != expected_output_faces:
        _raise(
            "material_face_accounting_failed",
            output_faces=int(output_face_count),
            expected_faces=int(expected_output_faces),
        )

    metadata = {
        "schema": COLOR_DEPTH_SCHEMA,
        "renderer": "ColorDepth Lab",
        "experimental": True,
        "slice_only": True,
        "print_allowed": False,
        "physical_materials_only": True,
        "ratio_definitions": 0,
        "cycle_definitions": 0,
        "virtual_mix_definitions": 0,
        "painted_triangles": 0,
        "cell_count": int(len(tets)),
        "source_component_count": int(component_count),
        "physical_part_count": int(len(parts)),
        "physical_materials": [int(part.extruder) for part in parts],
        "source_boundary_faces": int(len(external_rows)),
        "material_interface_faces": int(interface_triangle_total),
        "exact_touch_interfaces": int(len(interface_records)),
        "positive_overlap_mm3": 0.0,
        "gap_mm": 0.0,
        "source_volume_mm3": source_volume,
        "output_volume_mm3": output_volume,
        "volume_error_mm3": volume_error,
        "parts": part_records,
    }
    return ColorDepthCellResult(
        parts=tuple(parts),
        interfaces=tuple(interface_records),
        source_volume_mm3=source_volume,
        output_volume_mm3=output_volume,
        cell_materials=_immutable(materials, np.int8),
        metadata=metadata,
    )


def build_color_depth_materials(
    nodes_mm: np.ndarray,
    tetrahedra: np.ndarray,
    *,
    cell_owner_labels: np.ndarray,
    cell_depth_bounds_mm: np.ndarray,
    recipes: Mapping[int, ColorDepthRecipe],
    boundary_tolerance_mm: float = 1e-9,
) -> ColorDepthCellResult:
    """Classify conforming cells by recipe and extract physical unions."""

    assignment = classify_color_depth_cells(
        cell_owner_labels,
        cell_depth_bounds_mm,
        recipes,
        boundary_tolerance_mm=boundary_tolerance_mm,
    )
    result = extract_material_union_surfaces(
        nodes_mm,
        tetrahedra,
        assignment.cell_materials,
        cell_owner_labels=assignment.owner_labels,
    )
    combined_metadata = {
        **result.metadata,
        "recipes": {
            str(label): {
                "target_label": int(recipe.target_label),
                "outer_physical": int(recipe.outer_physical),
                "outer_thickness_mm": float(recipe.outer_thickness_mm),
                "backing_physical": int(recipe.backing_physical),
                "backing_depth_mm": (
                    None
                    if recipe.backing_depth_mm is None
                    else float(recipe.backing_depth_mm)
                ),
                "core_physical": (
                    None
                    if recipe.core_physical is None
                    else int(recipe.core_physical)
                ),
                "target_lab": recipe.target_lab,
                "calibrated": bool(recipe.calibrated),
                "calibration_id": recipe.calibration_id,
            }
            for label, recipe in sorted(_validated_recipe_map(recipes).items())
        },
        "cell_classification": assignment.metadata,
    }
    return ColorDepthCellResult(
        parts=result.parts,
        interfaces=result.interfaces,
        source_volume_mm3=result.source_volume_mm3,
        output_volume_mm3=result.output_volume_mm3,
        cell_materials=result.cell_materials,
        metadata=combined_metadata,
    )


__all__ = [
    "COLOR_DEPTH_SCHEMA",
    "ColorDepthCellAssignment",
    "ColorDepthCellResult",
    "ColorDepthError",
    "ColorDepthMaterialPart",
    "ColorDepthRecipe",
    "audit_material_union_topology",
    "audit_material_cell_components",
    "build_color_depth_materials",
    "classify_color_depth_cells",
    "extract_material_union_surfaces",
]
