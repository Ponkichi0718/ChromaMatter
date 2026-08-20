from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import engine, workflow
from spectrum_mapper.generated_surface_color import (
    ADAPTIVE_ALLOWED_MASK_ATTRIBUTE,
    FACE_PROVENANCE_LOCAL_CAP,
    FACE_PROVENANCE_PLANAR_CAP,
    FACE_PROVENANCE_VOLUME_INTERFACE,
    attach_generated_surface_export_context,
    build_generated_surface_masks,
    constrain_adaptive_allowed_mask,
    derive_part_face_provenance,
    make_face_provenance_record,
    optimize_generated_hidden_colors,
    propagate_face_provenance,
    validate_face_provenance,
)
from spectrum_mapper.models import (
    ColorResult,
    GeometrySettings,
    MeshLevel,
    ObjAsset,
    PaletteSettings,
    PreparedGeometry,
)


CORE_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def _subdivided_cube(
    offset_x: float,
    subdivisions: int = 6,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return a watertight cube whose generated top has deep interior faces."""

    vertex_ids: dict[tuple[int, int, int], int] = {}
    vertices: list[np.ndarray] = []
    faces: list[tuple[int, int, int]] = []
    provenance: list[int] = []

    def vertex_id(value: np.ndarray) -> int:
        key = tuple(int(item) for item in value)
        if key not in vertex_ids:
            vertex_ids[key] = len(vertices)
            vertices.append(value.astype(np.float64) / float(subdivisions))
        return vertex_ids[key]

    # cross(du, dv) points outwards for every listed surface.
    surfaces = (
        (np.asarray([0, 0, subdivisions]), np.asarray([1, 0, 0]), np.asarray([0, 1, 0]), True),
        (np.asarray([0, 0, 0]), np.asarray([0, 1, 0]), np.asarray([1, 0, 0]), False),
        (np.asarray([subdivisions, 0, 0]), np.asarray([0, 1, 0]), np.asarray([0, 0, 1]), False),
        (np.asarray([0, 0, 0]), np.asarray([0, 0, 1]), np.asarray([0, 1, 0]), False),
        (np.asarray([0, subdivisions, 0]), np.asarray([0, 0, 1]), np.asarray([1, 0, 0]), False),
        (np.asarray([0, 0, 0]), np.asarray([1, 0, 0]), np.asarray([0, 0, 1]), False),
    )
    for base, axis_u, axis_v, generated in surfaces:
        for v_index in range(subdivisions):
            for u_index in range(subdivisions):
                p00 = base + axis_u * u_index + axis_v * v_index
                p10 = p00 + axis_u
                p11 = p10 + axis_v
                p01 = p00 + axis_v
                ids = tuple(vertex_id(point) for point in (p00, p10, p11, p01))
                faces.extend(((ids[0], ids[1], ids[2]), (ids[0], ids[2], ids[3])))
                provenance.extend((int(FACE_PROVENANCE_PLANAR_CAP) if generated else 0,) * 2)

    vertex_array = np.asarray(vertices, dtype=np.float64)
    vertex_array[:, 0] += float(offset_x)
    return (
        vertex_array,
        np.asarray(faces, dtype=np.int32),
        np.asarray(provenance, dtype=np.uint8),
    )


def _fixture() -> tuple[PreparedGeometry, ColorResult]:
    first = _subdivided_cube(0.0)
    second = _subdivided_cube(1.5)
    vertices = np.vstack((first[0], second[0]))
    faces = np.vstack((first[1], second[1] + len(first[0]))).astype(np.int32)
    provenance = np.concatenate((first[2], second[2]))
    part_ids = np.concatenate(
        (
            np.zeros(len(first[1]), dtype=np.int16),
            np.ones(len(second[1]), dtype=np.int16),
        )
    )
    vertex_colors = np.vstack(
        (
            np.tile(np.asarray([0.25, 0.20, 0.15]), (len(first[0]), 1)),
            np.tile(np.asarray([0.15, 0.25, 0.35]), (len(second[0]), 1)),
        )
    )
    areas = engine.triangle_areas(vertices, faces)
    level = MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=vertex_colors,
        areas_unit=areas,
        neighbors=engine.face_neighbors_partial(faces, len(vertices)),
        face_part_ids=part_ids,
        part_names=("warm", "cool"),
        part_keys=("0:warm", "1:cool"),
        face_provenance=provenance,
    )
    topology = engine.edge_topology(faces, len(vertices))
    if not topology["watertight"]:
        raise AssertionError(topology)
    source = ObjAsset(
        path=Path("generated-surface-test.obj"),
        sha256="0" * 64,
        file_size=1,
        vertices=vertices.copy(),
        colors=vertex_colors.copy(),
        faces=faces.copy(),
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=[],
        part_names=level.part_names,
        part_keys=level.part_keys,
        face_part_ids=part_ids.copy(),
        part_face_counts=(len(first[1]), len(second[1])),
        part_vertex_counts=(len(first[0]), len(second[0])),
        part_marker_kind="object",
        has_explicit_parts=True,
    )
    prepared = PreparedGeometry(
        source=source,
        final=level,
        preview=level,
        clean_vertex_count=len(vertices),
        clean_face_count=len(faces),
        removed_vertices=0,
        removed_faces=0,
        topology=topology,
        source_area_unit=float(areas.sum()),
        source_volume_unit=2.0,
        simplified_area_unit=float(areas.sum()),
        simplified_volume_unit=2.0,
        source_dimensions_unit=np.ptp(vertices, axis=0),
        warnings=[],
        part_names=level.part_names,
        part_keys=level.part_keys,
        part_stats=[{"id": 0}, {"id": 1}],
        assembly={"solidify_parts": True, "all_parts_watertight": True},
    )
    prepared.assembly["generated_surface_provenance"] = make_face_provenance_record(level)

    indices = np.empty(len(faces), dtype=np.int8)
    indices[part_ids == 0] = 1
    indices[part_ids == 1] = 2
    generated_ids = np.flatnonzero(provenance != 0)
    indices[generated_ids] = (generated_ids % 6).astype(np.int8)
    palette_tables = np.zeros((2, 16, 3), dtype=np.float64)
    palette_tables[0] = np.linspace(0.05, 0.80, 16)[:, None]
    palette_tables[1] = np.linspace(0.90, 0.15, 16)[:, None]
    target = palette_tables[part_ids, indices]
    counts = np.bincount(indices, minlength=16)
    area_by_state = np.bincount(indices, weights=areas * 100.0, minlength=16)
    colors = ColorResult(
        tone_vertex_rgb=vertex_colors.copy(),
        source_face_rgb=vertex_colors[faces].mean(axis=1),
        palette_indices=indices,
        target_face_rgb=target,
        delta_e=np.zeros(len(faces), dtype=np.float64),
        smoothed_faces=0,
        palette_face_counts=counts,
        palette_area_fractions=area_by_state / area_by_state.sum(),
        pink_area_fraction=0.0,
        part_metrics=[{"part_id": 0, "part_key": "0:warm"}, {"part_id": 1, "part_key": "1:cool"}],
    )
    return prepared, colors


def _slice_colors(colors: ColorResult, selected: np.ndarray, areas: np.ndarray) -> ColorResult:
    indices = np.asarray(colors.palette_indices)[selected].copy()
    area_by_state = np.bincount(indices, weights=areas, minlength=16)
    return ColorResult(
        tone_vertex_rgb=np.empty((0, 3), dtype=np.float64),
        source_face_rgb=np.asarray(colors.source_face_rgb)[selected].copy(),
        palette_indices=indices,
        target_face_rgb=np.asarray(colors.target_face_rgb)[selected].copy(),
        delta_e=np.asarray(colors.delta_e)[selected].copy(),
        smoothed_faces=colors.smoothed_faces,
        palette_face_counts=np.bincount(indices, minlength=16),
        palette_area_fractions=area_by_state / max(float(area_by_state.sum()), 1e-12),
        pink_area_fraction=0.0,
        manual_override_faces=colors.manual_override_faces,
        part_metrics=[],
    )


def _paint_codes(path: Path) -> list[str]:
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    return [
        triangle.attrib["paint_color"]
        for triangle in root.findall(f".//{CORE_NS}triangle")
    ]


def _matching_open_box_asset() -> ObjAsset:
    def box(z0: float, z1: float, omit_top: bool) -> tuple[np.ndarray, np.ndarray]:
        vertices = np.asarray(
            [
                [-0.2, -0.15, z0], [0.2, -0.15, z0],
                [0.2, 0.15, z0], [-0.2, 0.15, z0],
                [-0.2, -0.15, z1], [0.2, -0.15, z1],
                [0.2, 0.15, z1], [-0.2, 0.15, z1],
            ],
            dtype=np.float64,
        )
        sides = {
            "bottom": ((0, 2, 1), (0, 3, 2)),
            "top": ((4, 5, 6), (4, 6, 7)),
            "front": ((0, 1, 5), (0, 5, 4)),
            "right": ((1, 2, 6), (1, 6, 5)),
            "back": ((2, 3, 7), (2, 7, 6)),
            "left": ((3, 0, 4), (3, 4, 7)),
        }
        omitted = "top" if omit_top else "bottom"
        faces = np.asarray(
            [face for name, values in sides.items() if name != omitted for face in values],
            dtype=np.int32,
        )
        return vertices, faces

    first = box(-0.2, 0.0, True)
    second = box(0.0, 0.2, False)
    vertices = np.vstack((first[0], second[0]))
    faces = np.vstack((first[1], second[1] + len(first[0]))).astype(np.int32)
    colors = np.tile(np.asarray([0.3, 0.4, 0.5]), (len(vertices), 1))
    part_ids = np.concatenate(
        (
            np.zeros(len(first[1]), dtype=np.int16),
            np.ones(len(second[1]), dtype=np.int16),
        )
    )
    return ObjAsset(
        path=Path("matching-open-boxes.obj"),
        sha256="1" * 64,
        file_size=1,
        vertices=vertices,
        colors=colors,
        faces=faces,
        original_vertex_count=len(vertices),
        original_face_count=len(faces),
        warnings=[],
        part_names=("lower", "upper"),
        part_keys=("0:lower", "1:upper"),
        face_part_ids=part_ids,
        part_face_counts=(len(first[1]), len(second[1])),
        part_vertex_counts=(len(first[0]), len(second[0])),
        part_marker_kind="object",
        has_explicit_parts=True,
    )


class GeneratedSurfaceProvenanceTests(unittest.TestCase):
    def test_prepare_geometry_installs_planar_cap_provenance_on_final_level(self) -> None:
        prepared = engine.prepare_geometry(
            _matching_open_box_asset(),
            GeometrySettings(
                height_mm=100.0,
                target_faces=1_000,
                preview_faces=1_000,
                up_axis="Z",
                min_component_faces=0,
                preserve_parts=True,
                solidify_parts=True,
            ),
        )
        validation = validate_face_provenance(prepared)
        self.assertTrue(validation.valid, validation.reason)
        self.assertEqual(
            np.count_nonzero(
                prepared.final.face_provenance == FACE_PROVENANCE_PLANAR_CAP
            ),
            4,
        )
        self.assertEqual(
            validation.record["generated_face_count"], 4
        )

    def test_repair_metadata_builds_local_provenance_and_stale_topology_skips(self) -> None:
        records = [
            {
                "method": "strict_planar_unmatched_boundary_caps",
                "loops": [{"part_id": 0, "cap_face_ids": [8, 9]}],
            },
            {
                "method": "partitioned_shared_caps",
                "interfaces": [
                    {"cap_face_range_by_part": {"0": [10, 12], "1": [6, 8]}}
                ],
            },
        ]
        result, diagnostic = derive_part_face_provenance((12, 11), records)
        self.assertEqual(diagnostic["status"], "fresh")
        self.assertIsNotNone(result)
        assert result is not None
        np.testing.assert_array_equal(result[0][8:10], FACE_PROVENANCE_LOCAL_CAP)
        np.testing.assert_array_equal(result[0][10:12], FACE_PROVENANCE_PLANAR_CAP)
        np.testing.assert_array_equal(result[1][6:8], FACE_PROVENANCE_PLANAR_CAP)

        volume_records = records + [
            {
                "method": "recursive_volume_partition",
                "parts": [
                    {"part_id": 0, "generated_face_ranges": []},
                    {"part_id": 1, "generated_face_ranges": [[8, 11]]},
                ],
            }
        ]
        volume_result, volume_diagnostic = derive_part_face_provenance(
            (12, 11), volume_records
        )
        self.assertTrue(
            volume_diagnostic["volume_rebuild_superseded_earlier_face_ids"]
        )
        assert volume_result is not None
        self.assertFalse(np.any(volume_result[0]))
        self.assertFalse(np.any(volume_result[1][6:8]))
        np.testing.assert_array_equal(
            volume_result[1][8:11], FACE_PROVENANCE_VOLUME_INTERFACE
        )

        stale, stale_diagnostic = derive_part_face_provenance(
            (12, 11), volume_records, topology_changed=True
        )
        self.assertIsNone(stale)
        self.assertEqual(stale_diagnostic["reason"], "topology_changed_after_repair")

    def test_refinement_contract_copies_parent_origin_to_every_child(self) -> None:
        parent = np.asarray([0, 1, 2, 3], dtype=np.uint8)
        parent_ids = np.asarray([0, 1, 1, 1, 2, 3, 3], dtype=np.int32)
        np.testing.assert_array_equal(
            propagate_face_provenance(parent, parent_ids),
            [0, 1, 1, 1, 2, 3, 3],
        )
        with self.assertRaisesRegex(ValueError, "unknown parent"):
            propagate_face_provenance(parent, [0, -1])


class GeneratedSurfaceColourTests(unittest.TestCase):
    def test_only_hidden_unedited_faces_collapse_and_publish_adaptive_mask(self) -> None:
        prepared, colors = _fixture()
        geometry_before = prepared.final.vertices_unit.copy()
        faces_before = prepared.final.faces.copy()
        masks = build_generated_surface_masks(prepared, 10.0)
        self.assertTrue(masks.valid)
        self.assertGreater(np.count_nonzero(masks.guard), 0)
        hidden_ids = np.flatnonzero(masks.hidden)
        self.assertGreater(len(hidden_ids), 4)

        manual_face = int(hidden_ids[0])
        tree_face = int(hidden_ids[1])
        manual = np.full(len(prepared.final.faces), -1, dtype=np.int8)
        manual[manual_face] = 7
        colors.palette_indices[manual_face] = 7
        colors.palette_indices[tree_face] = 8
        prepared._hotfix_subtriangle_paint = {tree_face: object()}
        before_states = colors.palette_indices.copy()

        result = optimize_generated_hidden_colors(
            prepared, colors, 10.0, manual_overrides=manual
        )
        attach_generated_surface_export_context(prepared, result)

        np.testing.assert_array_equal(prepared.final.vertices_unit, geometry_before)
        np.testing.assert_array_equal(prepared.final.faces, faces_before)
        np.testing.assert_array_equal(
            result.colors.palette_indices[masks.guard], before_states[masks.guard]
        )
        self.assertEqual(int(result.colors.palette_indices[manual_face]), 7)
        self.assertEqual(int(result.colors.palette_indices[tree_face]), 8)
        self.assertFalse(result.collapsed_mask[manual_face])
        self.assertFalse(result.collapsed_mask[tree_face])
        np.testing.assert_array_equal(
            ~result.adaptive_allowed_mask, result.collapsed_mask
        )
        np.testing.assert_array_equal(
            getattr(prepared, ADAPTIVE_ALLOWED_MASK_ATTRIBUTE),
            result.adaptive_allowed_mask,
        )
        caller_allowed = np.ones(len(result.adaptive_allowed_mask), dtype=bool)
        caller_allowed[0] = False
        np.testing.assert_array_equal(
            constrain_adaptive_allowed_mask(prepared, caller_allowed),
            caller_allowed & result.adaptive_allowed_mask,
        )
        part_ids = prepared.final.face_part_ids
        self.assertEqual(
            np.unique(result.colors.palette_indices[result.collapsed_mask & (part_ids == 0)]).tolist(),
            [1],
        )
        self.assertEqual(
            np.unique(result.colors.palette_indices[result.collapsed_mask & (part_ids == 1)]).tolist(),
            [2],
        )

    def test_stale_joint_or_topology_does_not_change_colours(self) -> None:
        prepared, colors = _fixture()
        prepared.assembly["manual_joint_topology_changed"] = True
        before = colors.palette_indices.copy()
        result = optimize_generated_hidden_colors(prepared, colors, 10.0)
        self.assertIs(result.colors, colors)
        np.testing.assert_array_equal(result.colors.palette_indices, before)
        self.assertEqual(result.diagnostic["reason"], "joint_topology_not_covered")
        self.assertTrue(np.all(result.adaptive_allowed_mask))

        prepared, colors = _fixture()
        prepared.final.faces[[0, 1]] = prepared.final.faces[[1, 0]]
        self.assertFalse(validate_face_provenance(prepared).valid)
        result = optimize_generated_hidden_colors(prepared, colors, 10.0)
        self.assertEqual(result.diagnostic["reason"], "topology_fingerprint_mismatch")

    def test_combined_and_individual_3mf_keep_the_same_optimized_states(self) -> None:
        prepared, colors = _fixture()
        masks = build_generated_surface_masks(prepared, 10.0)
        hidden_ids = np.flatnonzero(masks.hidden)
        manual = np.full(len(prepared.final.faces), -1, dtype=np.int8)
        manual[int(hidden_ids[0])] = int(colors.palette_indices[hidden_ids[0]])
        combined = optimize_generated_hidden_colors(
            prepared, colors, 10.0, manual_overrides=manual
        )
        attach_generated_surface_export_context(prepared, combined)

        palette = PaletteSettings()
        with tempfile.TemporaryDirectory() as folder:
            combined_path = Path(folder) / "combined.3mf"
            engine.write_3mf_atomic(
                combined_path,
                prepared,
                combined.colors,
                10.0,
                palette,
            )
            expected_combined = [
                engine.PAINT_CODES[int(value)]
                for value in combined.colors.palette_indices
            ]
            self.assertEqual(_paint_codes(combined_path), expected_combined)

            for part_id in range(2):
                part_prepared, source_face_ids = workflow._extract_prepared_part(
                    prepared, part_id
                )
                local = _slice_colors(
                    colors,
                    source_face_ids,
                    part_prepared.final.areas_unit * 100.0,
                )
                # Tone colours are vertex-indexed and must follow the compacted
                # individual-part geometry.
                local.tone_vertex_rgb = part_prepared.final.vertex_colors.copy()
                part_result = optimize_generated_hidden_colors(
                    part_prepared,
                    local,
                    10.0,
                    manual_overrides=manual[source_face_ids],
                )
                attach_generated_surface_export_context(part_prepared, part_result)
                np.testing.assert_array_equal(
                    part_result.colors.palette_indices,
                    combined.colors.palette_indices[source_face_ids],
                )
                part_path = Path(folder) / f"part-{part_id}.3mf"
                engine.write_3mf_atomic(
                    part_path,
                    part_prepared,
                    part_result.colors,
                    10.0,
                    palette,
                )
                self.assertEqual(
                    _paint_codes(part_path),
                    [
                        engine.PAINT_CODES[int(value)]
                        for value in combined.colors.palette_indices[source_face_ids]
                    ],
                )
                with ZipFile(part_path) as archive:
                    metadata = archive.read("Metadata/tripo_assembly.json").decode("utf-8")
                self.assertIn("generated_surface_color_export", metadata)


if __name__ == "__main__":
    unittest.main()
