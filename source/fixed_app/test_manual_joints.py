from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

import numpy as np
import trimesh
from scipy.spatial import cKDTree


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.assembly import (
    _edge_topology,
    find_boundary_loops,
    pair_matching_loops,
    solidify_partitioned_parts,
)
from spectrum_mapper.engine import face_neighbors_partial, signed_volume, triangle_areas
from spectrum_mapper.manual_joints import (
    ManualJointError,
    ManualJointSettings,
    _joint_overlap_diagnostics,
    apply_manual_joint,
    create_manual_joint,
    list_manual_joint_interfaces,
    replay_manual_joint,
    resolve_manual_joint_target,
)
from spectrum_mapper.paint import mesh_fingerprint
from spectrum_mapper.models import MeshLevel, ObjAsset, PreparedGeometry


HEIGHT_MM = 100.0
PART_NAMES = ("Lower Body", "Upper Body")
PART_KEYS = ("0:lower", "1:upper")


def _open_box(
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
    *,
    omit: str,
    color: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    vertices = np.asarray(
        [
            [x0, y0, z0],
            [x1, y0, z0],
            [x1, y1, z0],
            [x0, y1, z0],
            [x0, y0, z1],
            [x1, y0, z1],
            [x1, y1, z1],
            [x0, y1, z1],
        ],
        dtype=np.float64,
    )
    sides = {
        "zmin": ((0, 2, 1), (0, 3, 2)),
        "zmax": ((4, 5, 6), (4, 6, 7)),
        "ymin": ((0, 1, 5), (0, 5, 4)),
        "xmax": ((1, 2, 6), (1, 6, 5)),
        "ymax": ((2, 3, 7), (2, 7, 6)),
        "xmin": ((3, 0, 4), (3, 4, 7)),
    }
    faces = np.asarray(
        [
            triangle
            for side, triangles in sides.items()
            if side != omit
            for triangle in triangles
        ],
        dtype=np.int32,
    )
    colors = np.tile(np.asarray(color, dtype=np.float64), (len(vertices), 1))
    return vertices, faces, colors


def _combine(
    meshes: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    vertices = []
    faces = []
    colors = []
    part_ids = []
    offset = 0
    for part_id, mesh in enumerate(meshes):
        vertices.append(mesh[0])
        faces.append(mesh[1] + offset)
        colors.append(mesh[2])
        part_ids.append(np.full(len(mesh[1]), part_id, dtype=np.int16))
        offset += len(mesh[0])
    return (
        np.vstack(vertices),
        np.vstack(faces).astype(np.int32),
        np.vstack(colors),
        np.concatenate(part_ids),
    )


def _prepared_pair() -> tuple[PreparedGeometry, dict[str, object]]:
    first_open = _open_box(
        (-0.20, -0.15, -0.20),
        (0.20, 0.15, 0.00),
        omit="zmax",
        color=(0.15, 0.35, 0.85),
    )
    second_open = _open_box(
        (-0.20, -0.15, 0.00),
        (0.20, 0.15, 0.20),
        omit="zmin",
        color=(0.85, 0.35, 0.15),
    )
    loops = [
        *find_boundary_loops(0, first_open[0], first_open[1]),
        *find_boundary_loops(1, second_open[0], second_open[1]),
    ]
    seams = pair_matching_loops(loops, height_mm=HEIGHT_MM, tolerance_mm=0.01)
    closed, repair = solidify_partitioned_parts(
        [first_open, second_open], seams, height_mm=HEIGHT_MM
    )
    vertices, faces, colors, face_parts = _combine(closed)
    level = MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=colors,
        areas_unit=triangle_areas(vertices, faces),
        neighbors=face_neighbors_partial(faces, len(vertices)),
        face_part_ids=face_parts,
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
    )
    source = ObjAsset(
        path=Path("synthetic-two-part.obj"),
        sha256="0" * 64,
        file_size=1,
        vertices=vertices.copy(),
        colors=colors.copy(),
        faces=faces.copy(),
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=[],
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
        face_part_ids=face_parts.copy(),
        part_face_counts=tuple(len(mesh[1]) for mesh in closed),
        part_vertex_counts=tuple(len(mesh[0]) for mesh in closed),
        part_marker_kind="o",
        has_explicit_parts=True,
    )
    prepared = PreparedGeometry(
        source=source,
        final=level,
        preview=deepcopy(level),
        clean_vertex_count=len(vertices),
        clean_face_count=len(faces),
        removed_vertices=0,
        removed_faces=0,
        topology=_edge_topology(faces, len(vertices)),
        source_area_unit=float(level.areas_unit.sum()),
        source_volume_unit=float(sum(signed_volume(*mesh[:2]) for mesh in closed)),
        simplified_area_unit=float(level.areas_unit.sum()),
        simplified_volume_unit=float(sum(signed_volume(*mesh[:2]) for mesh in closed)),
        source_dimensions_unit=np.ptp(vertices, axis=0),
        warnings=[],
        part_names=PART_NAMES,
        part_keys=PART_KEYS,
        part_stats=[
            {"id": index, "key": PART_KEYS[index], "name": PART_NAMES[index]}
            for index in range(2)
        ],
        assembly={
            "solidify_parts": True,
            "repair_method": "partitioned_shared_caps",
            "repair_records": [repair],
            "joint_records": [],
            "all_parts_watertight": True,
        },
    )
    return prepared, repair


def _prepared_pair_with_small_cap_relief() -> PreparedGeometry:
    """Return two strict solids sharing a slightly non-planar generated cap."""

    prepared, _repair = _prepared_pair()
    vertices = prepared.final.vertices_unit.copy()
    interface = list_manual_joint_interfaces(prepared)[0]
    cap_vertex_ids = np.unique(
        prepared.final.faces[
            np.asarray(
                [
                    *interface.first_cap_face_ids,
                    *interface.second_cap_face_ids,
                ],
                dtype=np.int64,
            )
        ].reshape(-1)
    )
    for vertex_id in cap_vertex_ids:
        x, y = vertices[int(vertex_id), :2]
        # Matching vertices on both parts receive the same relief.  The shared
        # diagonal is high and the two off-diagonal corners are recessed, so a
        # centered footprint crosses more than one triangle plane.
        vertices[int(vertex_id), 2] = 0.0008 if x * y > 0.0 else -0.0016

    prepared.final.vertices_unit = vertices
    prepared.final.areas_unit = triangle_areas(vertices, prepared.final.faces)
    prepared.preview = deepcopy(prepared.final)
    prepared.source.vertices = vertices.copy()
    prepared.topology = _edge_topology(prepared.final.faces, len(vertices))
    prepared.source_dimensions_unit = np.ptp(vertices, axis=0)
    prepared.source_area_unit = float(prepared.final.areas_unit.sum())
    prepared.simplified_area_unit = prepared.source_area_unit
    prepared.source_volume_unit = float(
        sum(
            signed_volume(
                _part_mesh(prepared.final, part_id).vertices,
                _part_mesh(prepared.final, part_id).faces,
            )
            for part_id in range(2)
        )
    )
    prepared.simplified_volume_unit = prepared.source_volume_unit
    return prepared


def _part_mesh(level: MeshLevel, part_id: int) -> trimesh.Trimesh:
    selected = np.flatnonzero(np.asarray(level.face_part_ids) == part_id)
    faces = np.asarray(level.faces)[selected]
    used = np.unique(faces.reshape(-1))
    local = np.searchsorted(used, faces)
    return trimesh.Trimesh(
        vertices=np.asarray(level.vertices_unit)[used],
        faces=local,
        process=False,
    )


class ManualJointBackendTests(unittest.TestCase):
    def test_generated_cap_click_resolves_opposing_part_and_face(self) -> None:
        prepared, repair = _prepared_pair()
        interfaces = list_manual_joint_interfaces(prepared)
        self.assertEqual(len(interfaces), 1)
        interface = interfaces[0]
        self.assertEqual((interface.first_part_id, interface.second_part_id), (0, 1))
        self.assertEqual(len(interface.first_cap_face_ids), 2)
        male_face = interface.first_cap_face_ids[0]
        center = prepared.final.vertices_unit[
            prepared.final.faces[male_face]
        ].mean(axis=0)

        target = resolve_manual_joint_target(
            prepared,
            male_face_id=male_face,
            center_unit=center,
            height_mm=HEIGHT_MM,
            settings=ManualJointSettings(
                width_mm=8.0,
                height_mm=5.0,
                depth_mm=4.0,
                clearance_mm=0.30,
            ),
        )

        self.assertEqual(target.male_part_id, 0)
        self.assertEqual(target.female_part_id, 1)
        self.assertEqual(target.male_face_id, male_face)
        self.assertIn(target.female_face_id, interface.second_cap_face_ids)
        self.assertGreater(target.boundary_margin_mm, 5.0)
        male_triangle = prepared.final.vertices_unit[
            prepared.final.faces[target.male_face_id]
        ]
        female_triangle = prepared.final.vertices_unit[
            prepared.final.faces[target.female_face_id]
        ]
        self.assertLess(
            float(cKDTree(female_triangle).query(male_triangle)[0].max()),
            1e-9,
        )
        self.assertEqual(repair["interfaces"][0]["seam_id"], target.seam_id)

    def test_manual_rectangle_is_non_mutating_colored_and_strictly_solid(self) -> None:
        prepared, _repair = _prepared_pair()
        original_vertices = prepared.final.vertices_unit.copy()
        original_faces = prepared.final.faces.copy()
        original_colors = prepared.final.vertex_colors.copy()
        original_bounds = np.asarray(
            [original_vertices.min(axis=0), original_vertices.max(axis=0)]
        )
        interface = list_manual_joint_interfaces(prepared)[0]
        male_face = interface.first_cap_face_ids[0]
        center = prepared.final.vertices_unit[
            prepared.final.faces[male_face]
        ].mean(axis=0)
        settings = ManualJointSettings(
            width_mm=8.0,
            height_mm=5.0,
            depth_mm=4.0,
            clearance_mm=0.30,
        )

        result = create_manual_joint(
            prepared,
            male_face_id=male_face,
            center_unit=center,
            height_mm=HEIGHT_MM,
            settings=settings,
        )

        np.testing.assert_array_equal(prepared.final.vertices_unit, original_vertices)
        np.testing.assert_array_equal(prepared.final.faces, original_faces)
        np.testing.assert_array_equal(prepared.final.vertex_colors, original_colors)
        np.testing.assert_array_equal(result.before.final.faces, original_faces)
        self.assertIs(result.before, prepared)
        self.assertEqual(result.after.final.part_names, PART_NAMES)
        self.assertEqual(result.after.final.part_keys, PART_KEYS)
        self.assertEqual(result.after.part_names, PART_NAMES)
        self.assertEqual(result.after.part_keys, PART_KEYS)
        self.assertEqual(result.record["shape"], "keyed_rectangle")
        self.assertEqual(result.record["male_part"], 0)
        self.assertEqual(result.record["female_part"], 1)
        self.assertAlmostEqual(result.record["width_mm"], 8.0)
        self.assertAlmostEqual(result.record["height_mm"], 5.0)
        self.assertAlmostEqual(result.record["depth_mm"], 4.0)
        self.assertAlmostEqual(result.record["clearance_mm"], 0.30)
        self.assertTrue(result.record["preserved_part_names"])
        self.assertTrue(result.record["preserved_part_placement"])
        self.assertGreater(result.record["male_wall_mm"], 10.0)
        self.assertGreater(result.record["female_wall_mm"], 10.0)
        self.assertAlmostEqual(result.record["embed_mm"], 1.0, places=6)
        self.assertGreater(result.record["overlap_volume_mm3"], 20.0)
        self.assertGreaterEqual(result.record["contact_safety_ratio"], 1.0)
        self.assertEqual(
            result.record["contact_validation"],
            "passed_volume_balance",
        )
        self.assertGreaterEqual(result.record["footprint_coverage_ratio"], 0.995)

        after = result.after.final
        self.assertEqual(_edge_topology(after.faces, len(after.vertices_unit))["boundary_edges"], 0)
        self.assertEqual(_edge_topology(after.faces, len(after.vertices_unit))["nonmanifold_edges"], 0)
        for part_id in range(2):
            mesh = _part_mesh(after, part_id)
            mesh.fix_normals(multibody=True)
            self.assertTrue(mesh.is_watertight)
            self.assertTrue(mesh.is_volume)
            self.assertGreater(float(mesh.volume), 0.0)
            self.assertEqual(len(mesh.split(only_watertight=False)), 1)
        self.assertTrue(np.isfinite(after.vertex_colors).all())
        self.assertGreaterEqual(float(after.vertex_colors.min()), 0.0)
        self.assertLessEqual(float(after.vertex_colors.max()), 1.0)
        new_bounds = np.asarray(
            [after.vertices_unit.min(axis=0), after.vertices_unit.max(axis=0)]
        )
        np.testing.assert_allclose(new_bounds, original_bounds, atol=1e-8)
        self.assertEqual(len(result.after.assembly["manual_joint_records"]), 1)
        self.assertTrue(result.after.assembly["manual_joint_topology_changed"])
        self.assertTrue(result.after.assembly["all_parts_watertight"])

        with self.assertRaisesRegex(ManualJointError, "既にジョイント"):
            list_manual_joint_interfaces(result.after)

    def test_saved_record_replays_only_on_the_exact_base_mesh(self) -> None:
        prepared, _repair = _prepared_pair()
        interface = list_manual_joint_interfaces(prepared)[0]
        male_face = interface.first_cap_face_ids[0]
        center = prepared.final.vertices_unit[
            prepared.final.faces[male_face]
        ].mean(axis=0)
        created = create_manual_joint(
            prepared,
            male_face_id=male_face,
            center_unit=center,
            height_mm=HEIGHT_MM,
            settings=ManualJointSettings(
                width_mm=8.0,
                height_mm=5.0,
                depth_mm=4.0,
                clearance_mm=0.30,
            ),
        )

        replayed = replay_manual_joint(
            prepared,
            created.record,
            height_mm=HEIGHT_MM,
        )

        self.assertIs(replayed.before, prepared)
        self.assertEqual(
            created.record["center_unit"], replayed.record["center_unit"]
        )
        self.assertEqual(
            created.record["base_mesh_fingerprint"],
            mesh_fingerprint(prepared.final),
        )
        np.testing.assert_allclose(
            replayed.after.final.vertices_unit,
            created.after.final.vertices_unit,
            atol=1e-12,
        )
        np.testing.assert_array_equal(
            replayed.after.final.faces,
            created.after.final.faces,
        )

        different = deepcopy(prepared)
        different.final.vertices_unit = different.final.vertices_unit.copy()
        different.final.vertices_unit[0, 0] += 1e-4
        with self.assertRaisesRegex(ManualJointError, "別の形状"):
            replay_manual_joint(
                different,
                created.record,
                height_mm=HEIGHT_MM,
            )
        with self.assertRaisesRegex(ManualJointError, "造形高さ"):
            replay_manual_joint(
                prepared,
                created.record,
                height_mm=HEIGHT_MM * 0.5,
            )

    def test_invalid_surface_point_and_oversized_rectangle_are_rejected(self) -> None:
        prepared, _repair = _prepared_pair()
        interface = list_manual_joint_interfaces(prepared)[0]
        male_face = interface.first_cap_face_ids[0]
        center = prepared.final.vertices_unit[
            prepared.final.faces[male_face]
        ].mean(axis=0)
        exterior_face = next(
            face_id
            for face_id in np.flatnonzero(prepared.final.face_part_ids == 0)
            if face_id not in interface.first_cap_face_ids
        )
        with self.assertRaisesRegex(ManualJointError, "対向接合面"):
            resolve_manual_joint_target(
                prepared,
                male_face_id=int(exterior_face),
                center_unit=prepared.final.vertices_unit[
                    prepared.final.faces[exterior_face]
                ].mean(axis=0),
                height_mm=HEIGHT_MM,
            )
        with self.assertRaisesRegex(ManualJointError, "三角形の外側"):
            resolve_manual_joint_target(
                prepared,
                male_face_id=male_face,
                center_unit=center + np.asarray([1.0, 0.0, 0.0]),
                height_mm=HEIGHT_MM,
            )
        with self.assertRaisesRegex(ManualJointError, "端に近すぎ"):
            resolve_manual_joint_target(
                prepared,
                male_face_id=male_face,
                center_unit=center,
                height_mm=HEIGHT_MM,
                settings=ManualJointSettings(
                    width_mm=28.0,
                    height_mm=24.0,
                    depth_mm=4.0,
                    clearance_mm=0.30,
                ),
            )

    def test_curved_or_existing_joint_metadata_is_rejected(self) -> None:
        prepared, _repair = _prepared_pair()
        missing = deepcopy(prepared)
        missing.assembly["repair_records"] = []
        with self.assertRaisesRegex(ManualJointError, "平面共有面"):
            list_manual_joint_interfaces(missing)

        processed = deepcopy(prepared)
        processed.assembly["joint_records"] = [{"shape": "keyed_rectangle"}]
        with self.assertRaisesRegex(ManualJointError, "既にジョイント"):
            list_manual_joint_interfaces(processed)

    def test_stale_target_and_invalid_height_fail_closed(self) -> None:
        prepared, _repair = _prepared_pair()
        interface = list_manual_joint_interfaces(prepared)[0]
        male_face = interface.first_cap_face_ids[0]
        center = prepared.final.vertices_unit[
            prepared.final.faces[male_face]
        ].mean(axis=0)
        target = resolve_manual_joint_target(
            prepared,
            male_face_id=male_face,
            center_unit=center,
            height_mm=HEIGHT_MM,
        )
        with self.assertRaisesRegex(ManualJointError, "造形高さ"):
            apply_manual_joint(
                prepared,
                target,
                height_mm=0.0,
            )
        stale = deepcopy(prepared)
        stale.assembly["joint_records"] = [{"manual": False}]
        with self.assertRaisesRegex(ManualJointError, "既にジョイント"):
            apply_manual_joint(
                stale,
                target,
                height_mm=HEIGHT_MM,
            )

    def test_small_cap_relief_increases_embed_and_replays_deterministically(self) -> None:
        prepared = _prepared_pair_with_small_cap_relief()
        self.assertTrue(prepared.topology["watertight"])
        self.assertEqual(prepared.topology["boundary_edges"], 0)
        self.assertEqual(prepared.topology["nonmanifold_edges"], 0)
        interface = list_manual_joint_interfaces(prepared)[0]
        male_face = interface.first_cap_face_ids[0]
        settings = ManualJointSettings(
            width_mm=16.0,
            height_mm=10.0,
            depth_mm=4.0,
            clearance_mm=0.30,
        )

        created = create_manual_joint(
            prepared,
            male_face_id=male_face,
            center_unit=(0.0, 0.0, 0.0008),
            height_mm=HEIGHT_MM,
            settings=settings,
        )

        self.assertGreater(created.record["cap_relief_mm"], 0.02)
        self.assertGreater(created.record["embed_compensation_mm"], 0.0)
        self.assertGreater(created.record["embed_relief_guard_mm"], 0.0)
        self.assertGreater(created.record["embed_mm"], 1.0)
        self.assertGreaterEqual(created.record["footprint_coverage_ratio"], 0.995)
        self.assertGreaterEqual(created.record["contact_safety_ratio"], 1.0)
        for part_id in range(2):
            result_mesh = _part_mesh(created.after.final, part_id)
            result_mesh.fix_normals(multibody=True)
            self.assertTrue(result_mesh.is_watertight)
            self.assertTrue(result_mesh.is_volume)
            self.assertEqual(len(result_mesh.split(only_watertight=False)), 1)

        replayed = replay_manual_joint(
            prepared,
            created.record,
            height_mm=HEIGHT_MM,
        )
        self.assertEqual(created.record["embed_mm"], replayed.record["embed_mm"])
        self.assertEqual(
            created.record["overlap_volume_mm3"],
            replayed.record["overlap_volume_mm3"],
        )
        np.testing.assert_allclose(
            replayed.after.final.vertices_unit,
            created.after.final.vertices_unit,
            atol=1e-12,
        )
        np.testing.assert_array_equal(
            replayed.after.final.faces,
            created.after.final.faces,
        )

    def test_point_like_contact_is_rejected_by_volume_balance(self) -> None:
        class VolumeOnly:
            def __init__(self, volume: float) -> None:
                self.volume = volume

        # 8 x 5 mm footprint touching by only 0.01 mm gives 0.4 mm3 of
        # overlap.  A one-body union alone could accept this, but it is not a
        # printable attachment across the requested footprint.
        with self.assertRaisesRegex(ManualJointError, "接触が不足"):
            _joint_overlap_diagnostics(
                VolumeOnly(1000.0),
                VolumeOnly(160.4),
                VolumeOnly(1160.0),
                footprint_area_mm2=40.0,
                embed_mm=1.0,
                base_embed_mm=1.0,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
