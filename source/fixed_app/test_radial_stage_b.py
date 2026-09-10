from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.color_depth_head_geometry import (
    ColorDepthSourceSurface,
    ConformingColorDepthPartition,
)
from spectrum_mapper.material_manifold import (
    ManifoldMaterialPart,
    MaterialManifoldResult,
)
from spectrum_mapper.models import AppSettings, PaletteSettings, RadialSettings
from spectrum_mapper.radial_stage_b import (
    RadialStageBError,
    build_radial_stage_b_geometry,
    build_selective_hybrid,
    plan_radial_stage_b,
    plan_radial_stage_b_from_eligible_partners,
    restore_stage_b_paint_states,
    write_radial_stage_b_3mf,
)


def _settings() -> AppSettings:
    return AppSettings(
        palette=PaletteSettings(
            physical_hex=["#111111", "#FFFFFF", "#303030", "#FFB040"],
        ),
        radial=RadialSettings(
            outer_skin_thickness_mm=0.15,
            minimum_lstar_delta=35.0,
        ),
    )


_SOURCE_VERTICES = np.asarray(
    [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)
_SOURCE_FACES = np.asarray(
    [
        [1, 2, 3],
        [0, 3, 2],
        [0, 1, 3],
        [0, 2, 1],
    ],
    dtype=np.int32,
)
_SOURCE_STATES = np.asarray([4, 0, 5, 7], dtype=np.int16)


def _source() -> ColorDepthSourceSurface:
    return ColorDepthSourceSurface(
        vertices_mm=_SOURCE_VERTICES,
        faces=_SOURCE_FACES,
        face_target_labels=_SOURCE_STATES,
        height_mm=1.0,
        source_name="synthetic-tetrahedron",
        source_sha256="a" * 64,
        source_volume_mm3=1.0 / 6.0,
        metadata={"fixture": True},
    )


def _partition() -> ConformingColorDepthPartition:
    return ConformingColorDepthPartition(
        nodes_mm=np.vstack((_SOURCE_VERTICES, [[0.2, 0.2, 0.2]])),
        tetrahedra=np.asarray([[0, 1, 2, 3]], dtype=np.int32),
        cell_owner_labels=np.asarray([4], dtype=np.int32),
        cell_depth_bounds_mm=np.asarray([[0.0, 0.15]], dtype=np.float64),
        cell_materials=np.asarray([2], dtype=np.int8),
        unsafe_outer_only_cells=np.asarray([False], dtype=bool),
        exterior_faces=_SOURCE_FACES,
        exterior_owner_cells=np.zeros(4, dtype=np.int32),
        exterior_source_face_ids=np.arange(4, dtype=np.int32),
        threshold_interface_conforming=True,
        shared_interface_partition_exact=True,
        max_safe_threshold_error_mm=0.0,
        metadata={"fixture": True},
    )


def _raw_part(
    *,
    extruder: int,
    source_faces: np.ndarray,
) -> ManifoldMaterialPart:
    source_faces = np.asarray(source_faces, dtype=np.int32)
    return ManifoldMaterialPart(
        vertices_mm=np.vstack((_SOURCE_VERTICES, [[0.2, 0.2, 0.2]])),
        faces=np.tile(np.asarray([[0, 1, 2]], dtype=np.int32), (len(source_faces), 1)),
        extruder=extruder,
        source_faces=source_faces,
        source_owner_cells=np.zeros(len(source_faces), dtype=np.int32),
        output_face_source=np.arange(len(source_faces), dtype=np.int32),
        face_components=np.zeros(len(source_faces), dtype=np.int32),
        metadata={"fixture": True},
    )


def _manifold() -> MaterialManifoldResult:
    # Carrier owns the three conventional exterior faces plus one internal
    # black/partner interface.  The F2 shell owns the selected exterior face
    # plus the opposite side of that exact interface.
    carrier = _raw_part(
        extruder=1,
        source_faces=np.vstack((_SOURCE_FACES[1:], [[0, 1, 4]])),
    )
    shell = _raw_part(
        extruder=2,
        source_faces=np.vstack((_SOURCE_FACES[0], [[0, 4, 1]])),
    )
    return MaterialManifoldResult(
        parts=(carrier, shell),
        source_volume_mm3=1.0 / 6.0,
        output_volume_mm3=1.0 / 6.0,
        cell_materials=np.asarray([1, 2], dtype=np.int8),
        interfaces=({"materials": [1, 2], "gap_mm": 0.0},),
        metadata={
            "external_surface_coverage_exact": True,
            "shared_interface_partition_exact": True,
            "gap_mm": 0.0,
            "positive_overlap_mm3": 0.0,
        },
    )


class RadialStageBPlanTests(unittest.TestCase):
    def test_automatic_plan_selects_only_used_high_contrast_black_mix(self) -> None:
        plan = plan_radial_stage_b(
            _settings(),
            _SOURCE_STATES,
            black_slot=0,
        )

        self.assertEqual(plan.radial_state_ids, (4,))
        self.assertEqual(plan.conventional_state_ids, (0, 5, 7))
        self.assertEqual(plan.recipes[4].outer_physical, 2)
        self.assertEqual(plan.recipes[4].backing_physical, 1)
        self.assertEqual(plan.recipes[5].outer_physical, 1)
        self.assertEqual(plan.decision(0).reason, "pure-black-preserved")
        self.assertEqual(
            plan.decision(5).reason,
            "black-mix-below-lstar-threshold",
        )
        self.assertEqual(
            plan.decision(7).reason,
            "nonblack-or-pure-state-preserved",
        )
        self.assertAlmostEqual(plan.minimum_lstar_delta, 35.0)
        self.assertGreater(plan.decision(4).lstar_delta, 35.0)

    def test_explicit_below_threshold_state_fails_closed(self) -> None:
        with self.assertRaises(RadialStageBError) as caught:
            plan_radial_stage_b(
                _settings(),
                _SOURCE_STATES,
                black_slot=0,
                selected_state_ids=[5],
            )
        self.assertEqual(
            caught.exception.code,
            "selected_state_contrast_below_threshold",
        )

    def test_explicit_subset_leaves_other_qualified_state_conventional(self) -> None:
        states = np.asarray([4, 6, 0], dtype=np.int16)
        plan = plan_radial_stage_b(
            _settings(),
            states,
            black_slot=0,
            selected_state_ids=[4],
        )
        self.assertEqual(plan.radial_state_ids, (4,))
        self.assertEqual(plan.conventional_state_ids, (0, 6))
        self.assertEqual(
            plan.decision(6).reason,
            "qualifying-state-not-selected",
        )

    def test_stage_b_requires_at_least_one_conventional_surface(self) -> None:
        with self.assertRaises(RadialStageBError) as caught:
            plan_radial_stage_b(
                _settings(),
                np.asarray([4, 4], dtype=np.int16),
                black_slot=0,
            )
        self.assertEqual(
            caught.exception.code,
            "hybrid_conventional_surface_required",
        )

    def test_large_integer_state_does_not_wrap_before_range_check(self) -> None:
        with self.assertRaises(RadialStageBError) as caught:
            plan_radial_stage_b(
                _settings(),
                np.asarray([65536], dtype=np.int64),
                black_slot=0,
            )
        self.assertEqual(caught.exception.code, "face_state_out_of_range")
        self.assertEqual(caught.exception.details["maximum"], 65536)

    def test_prequalified_mapping_plan_is_none_safe_and_requires_hybrid(self) -> None:
        plan = plan_radial_stage_b_from_eligible_partners(
            _SOURCE_STATES,
            eligible_state_partners={4: 2, 6: 4},
            black_extruder=1,
            outer_skin_thickness_mm=0.15,
        )
        payload = plan.to_dict()
        self.assertIsNone(payload["black_lstar"])
        self.assertIsNone(payload["minimum_lstar_delta"])
        self.assertEqual(plan.radial_state_ids, (4,))
        self.assertEqual(plan.conventional_state_ids, (0, 5, 7))

        with self.assertRaises(RadialStageBError) as caught:
            plan_radial_stage_b_from_eligible_partners(
                np.asarray([4, 4], dtype=np.int16),
                eligible_state_partners={4: 2},
                black_extruder=1,
                outer_skin_thickness_mm=0.15,
            )
        self.assertEqual(
            caught.exception.code,
            "hybrid_conventional_surface_required",
        )

    def test_prequalified_plan_accepts_exact_per_state_depth_bands(self) -> None:
        states = np.asarray([4, 10, 0], dtype=np.int16)
        plan = plan_radial_stage_b_from_eligible_partners(
            states,
            eligible_state_partners={4: 2, 10: 2},
            black_extruder=1,
            outer_skin_thickness_mm=0.15,
            state_skin_thickness_mm={4: 0.10, 10: 0.30},
        )

        self.assertEqual(
            plan.state_outer_skin_thickness_mm,
            {4: 0.10, 10: 0.30},
        )
        self.assertAlmostEqual(plan.recipes[4].outer_thickness_mm, 0.10)
        self.assertAlmostEqual(plan.recipes[10].outer_thickness_mm, 0.30)
        # The conventional black/black recipe has no material interface.  It
        # reuses the minimum selected band rather than adding a seventh seam.
        self.assertAlmostEqual(plan.recipes[0].outer_thickness_mm, 0.10)
        self.assertTrue(plan.metadata["variable_outer_skin_thickness"])
        self.assertEqual(plan.metadata["outer_skin_thickness_band_count"], 2)
        self.assertEqual(
            plan.to_dict()["state_outer_skin_thickness_mm"],
            {"4": 0.10, "10": 0.30},
        )

    def test_equal_state_depths_preserve_uniform_recipe_behavior(self) -> None:
        states = np.asarray([4, 10, 0], dtype=np.int16)
        baseline = plan_radial_stage_b_from_eligible_partners(
            states,
            eligible_state_partners={4: 2, 10: 2},
            black_extruder=1,
            outer_skin_thickness_mm=0.15,
        )
        explicit = plan_radial_stage_b_from_eligible_partners(
            states,
            eligible_state_partners={4: 2, 10: 2},
            black_extruder=1,
            outer_skin_thickness_mm=0.15,
            state_skin_thickness_mm={4: 0.15, 10: 0.15},
        )
        self.assertEqual(
            [item.outer_thickness_mm for item in baseline.recipes.values()],
            [item.outer_thickness_mm for item in explicit.recipes.values()],
        )
        self.assertFalse(explicit.metadata["variable_outer_skin_thickness"])

    def test_invalid_state_depth_mapping_fails_closed(self) -> None:
        with self.assertRaises(RadialStageBError) as caught:
            plan_radial_stage_b_from_eligible_partners(
                np.asarray([4, 0], dtype=np.int16),
                eligible_state_partners={4: 2},
                black_extruder=1,
                outer_skin_thickness_mm=0.15,
                state_skin_thickness_mm={5: 0.20},
            )
        self.assertEqual(
            caught.exception.code,
            "state_skin_thickness_state_not_selected",
        )

    def test_partial_state_depth_mapping_fails_closed(self) -> None:
        with self.assertRaises(RadialStageBError) as caught:
            plan_radial_stage_b_from_eligible_partners(
                np.asarray([4, 10, 0], dtype=np.int16),
                eligible_state_partners={4: 2, 10: 2},
                black_extruder=1,
                outer_skin_thickness_mm=0.15,
                state_skin_thickness_mm={4: 0.10},
            )
        self.assertEqual(
            caught.exception.code,
            "state_skin_thickness_state_missing",
        )
        self.assertEqual(caught.exception.details["state_ids"], [10])


class RadialStageBProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _source()
        self.partition = _partition()
        self.plan = plan_radial_stage_b(
            _settings(),
            _SOURCE_STATES,
            black_slot=0,
            selected_state_ids=[4],
        )

    def test_restore_uses_exact_exterior_provenance_and_unpainted_interfaces(self) -> None:
        parts = restore_stage_b_paint_states(
            self.source,
            self.partition,
            _manifold(),
            self.plan,
        )
        self.assertEqual(len(parts), 2)
        carrier = next(
            part for part in parts if part.role == "conventional_painted_carrier"
        )
        shell = next(part for part in parts if part.role == "partner_outer_shell")

        np.testing.assert_array_equal(
            carrier.paint_state_ids,
            np.asarray([0, 5, 7, -1], dtype=np.int16),
        )
        np.testing.assert_array_equal(
            carrier.source_face_ids,
            np.asarray([1, 2, 3, -1], dtype=np.int32),
        )
        np.testing.assert_array_equal(
            carrier.external_face_mask,
            np.asarray([True, True, True, False]),
        )
        np.testing.assert_array_equal(
            shell.paint_state_ids,
            np.asarray([-1, -1], dtype=np.int16),
        )
        np.testing.assert_array_equal(
            shell.source_face_ids,
            np.asarray([0, -1], dtype=np.int32),
        )
        np.testing.assert_array_equal(
            shell.external_face_mask,
            np.asarray([True, False]),
        )
        self.assertFalse(carrier.paint_state_ids.flags.writeable)
        self.assertFalse(shell.external_face_mask.flags.writeable)
        self.assertTrue(carrier.metadata["source_exterior_paint_restored"])
        self.assertFalse(shell.metadata["source_exterior_paint_restored"])
        self.assertTrue(shell.metadata["source_exterior_is_physical_skin"])

    def test_selected_state_may_not_leak_to_black_carrier(self) -> None:
        manifold = _manifold()
        exposed = _raw_part(
            extruder=1,
            source_faces=np.vstack((_SOURCE_FACES, [[0, 1, 4]])),
        )
        manifold = replace(manifold, parts=(exposed, manifold.parts[1]))
        with self.assertRaises(RadialStageBError) as caught:
            restore_stage_b_paint_states(
                self.source,
                self.partition,
                manifold,
                self.plan,
            )
        self.assertEqual(
            caught.exception.code,
            "eligible_surface_exposed_on_black_carrier",
        )

    def test_geometry_result_records_strict_zero_gap_proofs(self) -> None:
        arrays = (
            np.asarray(self.partition.nodes_mm),
            np.asarray(self.partition.tetrahedra),
            np.asarray(self.partition.cell_owner_labels),
            np.asarray(self.partition.cell_depth_bounds_mm),
            np.asarray(self.partition.cell_materials),
            np.asarray(self.partition.unsafe_outer_only_cells),
        )
        with (
            mock.patch(
                "spectrum_mapper.radial_stage_b._validate_partition_arrays",
                return_value=arrays,
            ),
            mock.patch(
                "spectrum_mapper.radial_stage_b._validate_visible_exterior",
                return_value={"external_surface_coverage_exact": True},
            ),
            mock.patch(
                "spectrum_mapper.radial_stage_b.manifoldize_labeled_tetrahedra",
                return_value=_manifold(),
            ),
        ):
            result = build_radial_stage_b_geometry(
                self.source,
                self.plan,
                partition_provider=lambda *_args, **_kwargs: self.partition,
            )

        self.assertTrue(result.metadata["material_manifold"])
        self.assertTrue(result.metadata["source_exterior_preserved_exactly"])
        self.assertTrue(result.metadata["external_surface_coverage_exact"])
        self.assertTrue(result.metadata["shared_interface_partition_exact"])
        self.assertEqual(result.metadata["gap_mm"], 0.0)
        self.assertEqual(result.metadata["positive_overlap_mm3"], 0.0)
        self.assertEqual(result.metadata["volume_error_mm3"], 0.0)
        self.assertEqual(
            result.metadata["state_outer_skin_thickness_mm"],
            {"4": 0.15},
        )

    def test_variable_skin_rejects_unsafe_partner_cells(self) -> None:
        source = replace(
            self.source,
            face_target_labels=np.asarray([4, 10, 0, 5], dtype=np.int16),
        )
        plan = plan_radial_stage_b_from_eligible_partners(
            source.face_target_labels,
            eligible_state_partners={4: 2, 10: 2},
            black_extruder=1,
            outer_skin_thickness_mm=0.15,
            state_skin_thickness_mm={4: 0.10, 10: 0.30},
        )
        bad_partition = replace(
            self.partition,
            unsafe_outer_only_cells=np.asarray([True], dtype=bool),
            metadata={"adaptive_partner_depth_samples_verified": True},
        )
        arrays = (
            np.asarray(bad_partition.nodes_mm),
            np.asarray(bad_partition.tetrahedra),
            np.asarray(bad_partition.cell_owner_labels),
            np.asarray(bad_partition.cell_depth_bounds_mm),
            np.asarray(bad_partition.cell_materials),
            np.asarray(bad_partition.unsafe_outer_only_cells),
        )
        with mock.patch(
            "spectrum_mapper.radial_stage_b._validate_partition_arrays",
            return_value=arrays,
        ):
            with self.assertRaises(RadialStageBError) as caught:
                build_radial_stage_b_geometry(
                    source,
                    plan,
                    partition_provider=lambda *_args, **_kwargs: bad_partition,
                )
        self.assertEqual(
            caught.exception.code,
            "adaptive_partner_unsafe_outer_cells",
        )

    def test_variable_skin_requires_true_distance_depth_proof(self) -> None:
        source = replace(
            self.source,
            face_target_labels=np.asarray([4, 10, 0, 5], dtype=np.int16),
        )
        plan = plan_radial_stage_b_from_eligible_partners(
            source.face_target_labels,
            eligible_state_partners={4: 2, 10: 2},
            black_extruder=1,
            outer_skin_thickness_mm=0.15,
            state_skin_thickness_mm={4: 0.10, 10: 0.30},
        )
        arrays = (
            np.asarray(self.partition.nodes_mm),
            np.asarray(self.partition.tetrahedra),
            np.asarray(self.partition.cell_owner_labels),
            np.asarray(self.partition.cell_depth_bounds_mm),
            np.asarray(self.partition.cell_materials),
            np.asarray(self.partition.unsafe_outer_only_cells),
        )
        with mock.patch(
            "spectrum_mapper.radial_stage_b._validate_partition_arrays",
            return_value=arrays,
        ):
            with self.assertRaises(RadialStageBError) as caught:
                build_radial_stage_b_geometry(
                    source,
                    plan,
                    partition_provider=lambda *_args, **_kwargs: self.partition,
                )
        self.assertEqual(
            caught.exception.code,
            "adaptive_partner_depth_proof_required",
        )

    def test_variable_skin_recomputes_depth_despite_provider_claim(self) -> None:
        source = replace(
            self.source,
            vertices_mm=10.0 * np.asarray(self.source.vertices_mm),
            face_target_labels=np.asarray([4, 10, 0, 5], dtype=np.int16),
            height_mm=10.0,
            source_volume_mm3=1000.0 / 6.0,
        )
        plan = plan_radial_stage_b_from_eligible_partners(
            source.face_target_labels,
            eligible_state_partners={4: 2, 10: 2},
            black_extruder=1,
            outer_skin_thickness_mm=0.15,
            state_skin_thickness_mm={4: 0.10, 10: 0.30},
        )
        malicious = replace(
            self.partition,
            metadata={"adaptive_partner_depth_samples_verified": True},
        )
        arrays = (
            np.asarray(malicious.nodes_mm),
            np.asarray(malicious.tetrahedra),
            np.asarray(malicious.cell_owner_labels),
            np.asarray(malicious.cell_depth_bounds_mm),
            np.asarray(malicious.cell_materials),
            np.asarray(malicious.unsafe_outer_only_cells),
        )
        with mock.patch(
            "spectrum_mapper.radial_stage_b._validate_partition_arrays",
            return_value=arrays,
        ):
            with self.assertRaises(RadialStageBError) as caught:
                build_radial_stage_b_geometry(
                    source,
                    plan,
                    partition_provider=lambda *_args, **_kwargs: malicious,
                )
        self.assertEqual(caught.exception.code, "adaptive_partner_cell_too_deep")
        self.assertEqual(
            caught.exception.details["verifier"],
            "radial-stage-b-independent-source-distance",
        )

    def test_missing_manifold_proof_is_rejected(self) -> None:
        arrays = (
            np.asarray(self.partition.nodes_mm),
            np.asarray(self.partition.tetrahedra),
            np.asarray(self.partition.cell_owner_labels),
            np.asarray(self.partition.cell_depth_bounds_mm),
            np.asarray(self.partition.cell_materials),
            np.asarray(self.partition.unsafe_outer_only_cells),
        )
        bad = replace(
            _manifold(),
            metadata={
                "external_surface_coverage_exact": True,
                "gap_mm": 0.0,
                "positive_overlap_mm3": 0.0,
            },
        )
        with (
            mock.patch(
                "spectrum_mapper.radial_stage_b._validate_partition_arrays",
                return_value=arrays,
            ),
            mock.patch(
                "spectrum_mapper.radial_stage_b._validate_visible_exterior",
                return_value={"external_surface_coverage_exact": True},
            ),
            mock.patch(
                "spectrum_mapper.radial_stage_b.manifoldize_labeled_tetrahedra",
                return_value=bad,
            ),
        ):
            with self.assertRaises(RadialStageBError) as caught:
                build_radial_stage_b_geometry(
                    self.source,
                    self.plan,
                    partition_provider=lambda *_args, **_kwargs: self.partition,
                )
        self.assertEqual(
            caught.exception.code,
            "material_manifold_interface_proof_required",
        )

    def test_application_adapter_preserves_requested_contract(self) -> None:
        sentinel = object()
        with mock.patch(
            "spectrum_mapper.radial_stage_b.build_radial_stage_b_geometry",
            return_value=sentinel,
        ) as builder:
            result = build_selective_hybrid(
                self.source,
                1.0,
                _SOURCE_STATES,
                {4: 2},
                1,
                0.15,
            )
        self.assertIs(result, sentinel)
        passed_source, passed_plan = builder.call_args.args
        np.testing.assert_array_equal(
            passed_source.face_target_labels,
            self.source.face_target_labels,
        )
        self.assertEqual(passed_source.source_name, self.source.source_name)
        self.assertEqual(passed_plan.radial_state_ids, (4,))
        self.assertEqual(passed_plan.conventional_state_ids, (0, 5, 7))

    def test_application_adapter_forwards_per_state_depth(self) -> None:
        sentinel = object()
        with mock.patch(
            "spectrum_mapper.radial_stage_b.build_radial_stage_b_geometry",
            return_value=sentinel,
        ) as builder:
            result = build_selective_hybrid(
                self.source,
                1.0,
                _SOURCE_STATES,
                {4: 2},
                1,
                0.15,
                state_skin_thickness_mm={4: 0.25},
            )
        self.assertIs(result, sentinel)
        passed_plan = builder.call_args.args[1]
        self.assertEqual(passed_plan.state_outer_skin_thickness_mm, {4: 0.25})
        self.assertAlmostEqual(passed_plan.recipes[4].outer_thickness_mm, 0.25)

    def test_archive_writer_remains_fail_closed(self) -> None:
        with self.assertRaises(RadialStageBError) as caught:
            write_radial_stage_b_3mf(None)
        self.assertEqual(
            caught.exception.code,
            "hybrid_3mf_writer_not_implemented",
        )


if __name__ == "__main__":
    unittest.main()
