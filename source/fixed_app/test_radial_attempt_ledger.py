import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tooling" / "radial_attempt_ledger.py"
SPEC = importlib.util.spec_from_file_location("radial_attempt_ledger", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
ledger_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ledger_tool)

SYNTHETIC_PRIVATE_ROOT = "X:" + r"\synthetic-private\owner\model"
SYNTHETIC_PRIVATE_PREFIX = "X:" + r"\synthetic-private"
SYNTHETIC_ALTERNATE_ROOT = "Y:" + r"\synthetic-confidential"


def _artifact(kind, payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "kind": kind,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "payload": payload,
    }


def _precheck(
    *,
    schema="chromamatter.tooling.generic-radial-launcher.v3",
    source_sha="a" * 64,
    selected_faces=60_000,
    selected_vertices=30_002,
    part_key="gltf:scene=0:path=private:mesh=7",
    palette=None,
    strict_zero=True,
    simplification=False,
    active_bands=3,
    created_utc="2026-09-02T01:02:03+00:00",
    private_root=SYNTHETIC_PRIVATE_ROOT,
):
    physical = palette or ["#111111", "#F5F5F5", "#2453C7", "#00A6C7"]
    topology = {
        "edge_topology": {
            "boundary_edges": 0,
            "nonmanifold_edges": 0,
            "inconsistent_winding_edges": 0,
            "degenerate_faces": 0,
        },
        "solid_quality": {
            "boundary_edges": 0,
            "nonmanifold_edges": 0,
            "inconsistent_winding_edges": 0,
            "degenerate_faces": 0,
            "body_count": 1,
            "watertight": True,
            "winding_consistent": True,
            "positive_volume": True,
            "self_intersecting_faces": 0 if strict_zero else -1,
            "self_intersecting_face_ids_complete": strict_zero,
        },
    }
    if strict_zero:
        topology["self_intersection_gate"] = {
            "policy": "actual_selected_post_qem_strict_zero",
            "check_completed": True,
            "self_intersecting_faces": 0,
            "strict_zero_verified": True,
        }
    return {
        "schema": schema,
        "status": "preflight_passed",
        "created_utc": created_utc,
        "configuration": {
            "input": private_root + r"\Private Character.glb",
            "part_key": part_key,
            "part_name": "Private Head Name",
            "physical_hex": physical,
            "black_slot_zero_based": 0,
            "black_extruder": 1,
            "geometry": {
                "height_mm": 150.0,
                "target_faces": 80_000,
                "target_faces_scope": "whole_prepared_assembly",
                "adjust_face_count": simplification,
                "preview_faces": 80_000,
                "preserve_parts": True,
                "solidify_parts": False,
            },
            "tone": {
                "black_point": 0.75,
                "white_point": 0.875,
                "gamma": 1.2,
                "contrast": 0.6,
                "saturation": 1.0,
            },
            "radial": {
                "conversion_mode": "selective_hybrid",
                "skin_thickness_mode": "adaptive",
                "wall_generator": "arachne",
                "layer_height_mm": 0.1,
                "process_profile": "sparse_15pct",
                "sparse_infill_density_percent": 15,
                "minimum_lstar_delta": 35.0,
                "adaptive_min_thickness_mm": 0.1,
                "adaptive_max_thickness_mm": 0.3,
                "adaptive_gamma": 1.5,
                "adaptive_bands": 4,
            },
            "strict_preflight_gate": {
                "minimum_active_bands": 2,
                "minimum_inter_band_thresholds": 1,
                "minimum_faces_per_active_band": 5,
            },
            "output_root": private_root + r"\Output",
        },
        "source": {
            "path": private_root + r"\Private Character.glb",
            "sha256": source_sha,
            "bytes": 123_456,
            "source_vertices": selected_vertices,
            "source_faces": selected_faces,
            "source_part_count": 5,
            "prepared_vertices": selected_vertices + 10_000,
            "prepared_faces": selected_faces + 20_000,
            "prepared_parts": [
                {
                    "part_id": 0,
                    "part_key": part_key,
                    "part_name": "Private Head Name",
                    "faces": selected_faces,
                }
            ],
            "warnings": [private_root + r"\Private warning path"],
        },
        "selection": {
            "part_id": 0,
            "part_key": part_key,
            "part_name": "Private Head Name",
            "faces": selected_faces,
            "selected_vertices": selected_vertices,
            "selected_faces": selected_faces,
            "source_face_id_count": selected_faces,
        },
        "preparation_provenance": {
            "selected_part_stats": {
                "pre_qem_face_count": selected_faces,
                "post_qem_source_face_count": selected_faces,
                "final_faces": selected_faces,
                "final_vertices": selected_vertices,
            },
            "generated_surface_provenance": {
                "topology_sha256": "b" * 64,
                "includes_topology_edits": False,
                "generated_face_count": 0,
                "face_count": selected_faces + 20_000,
                "vertex_count": selected_vertices + 10_000,
            },
            "multipart_qem": {
                "simplification_applied": simplification,
                "source_triangle_geometry_preserved": not simplification,
                "source_triangle_ancestry_proven": False,
                "qem_max_output_ratio_numerator": 3,
                "qem_max_output_ratio_denominator": 4,
            },
        },
        "topology": topology,
        "palette": {
            "physical_hex": physical,
            "black_extruder": 1,
            "used_state_face_counts": {"0": 100, "1": 100},
        },
        "adaptive_schedule": {
            "strict_gate": {
                "active_band_count": active_bands,
                "inter_band_threshold_count": max(0, active_bands - 1),
                "partition_outer_depth_boundary_count": active_bands,
                "minimum_faces_per_active_band": 5,
                "active_thicknesses_mm": [0.1, 0.2, 0.3][:active_bands],
            }
        },
    }


def _run(precheck, status="running"):
    payload = {
        "schema": precheck["schema"],
        "status": status,
        "started_utc": "2026-09-02T01:03:00+00:00",
        "destination": SYNTHETIC_PRIVATE_ROOT + r"\output\private.3mf",
        "precheck": copy.deepcopy(precheck),
    }
    if status == "passed":
        payload["completed_utc"] = "2026-09-02T01:04:00+00:00"
        payload["result"] = {
            "model_path": SYNTHETIC_PRIVATE_ROOT + r"\output\private.3mf",
            "validation": {"passed": True},
        }
    return payload


def _failed(code, details=None):
    return {
        "schema": "chromamatter.tooling.generic-radial-launcher.v3",
        "status": "failed",
        "failed_utc": "2026-09-02T01:05:00+00:00",
        "error": {
            "exception_type": "PrivateException",
            "code": code,
            "details": dict(details or {}),
            "message": "Private Character failed at " + SYNTHETIC_PRIVATE_ROOT,
            "traceback": "Traceback " + SYNTHETIC_PRIVATE_ROOT + ".py",
        },
    }


class RadialAttemptLedgerTests(unittest.TestCase):
    def _record(self, precheck=None, failure=None, run_status="running"):
        artifacts = {}
        if precheck is not None:
            artifacts["PRECHECK"] = _artifact("PRECHECK", precheck)
            artifacts["RUN"] = _artifact("RUN", _run(precheck, run_status))
        if failure is not None:
            artifacts["FAILED"] = _artifact("FAILED", failure)
        return ledger_tool.build_attempt_record(artifacts)

    def test_correctness_key_ignores_paths_names_and_timestamps(self):
        first = _precheck()
        second = _precheck(
            created_utc="2026-09-03T05:06:07+00:00",
            private_root=SYNTHETIC_ALTERNATE_ROOT,
        )
        first_record = self._record(first)
        second_record = self._record(second)
        self.assertEqual(
            first_record["correctness_key"]["sha256"],
            second_record["correctness_key"]["sha256"],
        )
        self.assertEqual(
            first_record["geometry_fingerprint"]["sha256"],
            second_record["geometry_fingerprint"]["sha256"],
        )
        self.assertNotEqual(first_record["attempt_id"], second_record["attempt_id"])

    def test_private_artifact_content_is_not_copied(self):
        precheck = _precheck()
        record = self._record(
            precheck,
            _failed(
                "variable_partition_cell_limit_exceeded",
                {
                    "phase": "preallocation",
                    "exact_capacity": 3_000_000,
                    "maximum": 2_000_000,
                    "private_path": SYNTHETIC_PRIVATE_ROOT + ".glb",
                    "SecretModelNode": {"violating_triangles": 7},
                },
            ),
        )
        serialized = json.dumps(record, ensure_ascii=False)
        for forbidden in (
            SYNTHETIC_PRIVATE_PREFIX,
            "SecretModel",
            "SecretModelNode",
            "Private Character",
            "Private Head Name",
            "gltf:scene=0:path=private:mesh=7",
            "Traceback",
            "a" * 64,
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(
            [event["kind"] for event in record["events"]],
            ["PRECHECK", "RUN", "FAILED"],
        )

    def test_palette_changes_correctness_but_not_geometry(self):
        first = self._record(_precheck())
        second = self._record(
            _precheck(palette=["#111111", "#EEEEEE", "#2453C7", "#00A6C7"])
        )
        self.assertEqual(
            first["geometry_fingerprint"]["sha256"],
            second["geometry_fingerprint"]["sha256"],
        )
        self.assertNotEqual(
            first["correctness_key"]["sha256"],
            second["correctness_key"]["sha256"],
        )

    def test_cross_model_structural_key_is_review_only(self):
        first = self._record(_precheck(source_sha="1" * 64, part_key="mesh-one"))
        second = self._record(_precheck(source_sha="2" * 64, part_key="mesh-two"))
        self.assertNotEqual(
            first["geometry_fingerprint"]["sha256"],
            second["geometry_fingerprint"]["sha256"],
        )
        self.assertEqual(
            first["geometry_fingerprint"]["structural_sha256"],
            second["geometry_fingerprint"]["structural_sha256"],
        )
        self.assertEqual(
            first["geometry_fingerprint"]["structural_use"],
            "review_and_statistics_only",
        )
        merged = ledger_tool.merge_attempts(None, [first, second])
        self.assertEqual(
            merged["statistics"]["repeated_structural_fingerprint_count"], 1
        )

    def test_geometry_change_changes_exact_and_structural_keys(self):
        first = self._record(_precheck(selected_faces=60_000))
        second = self._record(_precheck(selected_faces=140_000))
        self.assertNotEqual(
            first["geometry_fingerprint"]["sha256"],
            second["geometry_fingerprint"]["sha256"],
        )
        self.assertNotEqual(
            first["geometry_fingerprint"]["structural_sha256"],
            second["geometry_fingerprint"]["structural_sha256"],
        )

    def test_capacity_failure_proposes_only_bounded_preflight_candidates(self):
        record = self._record(
            _precheck(),
            _failed(
                "variable_partition_cell_limit_exceeded",
                {
                    "phase": "preallocation",
                    "threshold_mm": 0.2,
                    "exact_capacity": 3_000_000,
                    "input_cells": 1_500_000,
                    "maximum": 2_000_000,
                },
            ),
        )
        self.assertEqual(record["failure"]["stage"], "exact_partition")
        self.assertEqual(record["failure"]["category"], "cell_capacity")
        first = record["recommendations"][0]
        self.assertEqual(first["action"], "probe_safer_selected_part_reduction")
        self.assertEqual(
            first["parameters"]["candidate_selected_part_face_upper_bound"],
            32_000,
        )
        for recommendation in record["recommendations"]:
            self.assertIs(recommendation["automatic_run_allowed"], False)
            self.assertEqual(
                recommendation["safety_contract"], ledger_tool.SAFETY_CONTRACT
            )
            self.assertEqual(recommendation["next_mode"], "preflight_only")
            self.assertEqual(
                recommendation["safety_contract"]["maximum_partition_cells"],
                2_000_000,
            )
            self.assertEqual(
                recommendation["safety_contract"]["maximum_error_mm"], 0.05
            )

    def test_legacy_unverified_precheck_blocks_capacity_advice(self):
        legacy = _precheck(
            schema="chromamatter.tooling.generic-radial-launcher.v1",
            strict_zero=False,
        )
        failure = _failed(
            "tetgen_exact_boundary_failed",
            {"error": "The input surface mesh contains self-intersections."},
        )
        failure["schema"] = legacy["schema"]
        record = self._record(legacy, failure)
        self.assertFalse(record["correctness_key"]["complete"])
        self.assertEqual(
            [item["action"] for item in record["recommendations"]],
            ["repeat_current_strict_preflight"],
        )

    def test_running_and_passed_attempts_do_not_invent_retries(self):
        running = self._record(_precheck(), run_status="running")
        passed = self._record(_precheck(), run_status="passed")
        self.assertEqual(running["outcome"], "running")
        self.assertEqual(passed["outcome"], "passed")
        self.assertEqual(running["attempt_id"], passed["attempt_id"])
        self.assertEqual(running["recommendations"], [])
        self.assertEqual(passed["recommendations"], [])
        merged = ledger_tool.merge_attempts(None, [running, passed])
        self.assertEqual(merged["statistics"]["attempt_count"], 1)
        self.assertEqual(merged["attempts"][0]["outcome"], "passed")

    def test_unknown_failure_requires_manual_diagnosis(self):
        record = self._record(_precheck(), _failed("unexpected_widget_fault"))
        self.assertEqual(record["failure"]["stage"], "unknown")
        self.assertEqual(record["failure"]["code"], "unclassified_error")
        self.assertIn("unclassified_code_digest", record["failure"])
        self.assertNotIn("unexpected_widget_fault", json.dumps(record))
        self.assertEqual(
            record["recommendations"][0]["action"], "manual_diagnosis_only"
        )

    def test_stagnation_family_requires_safer_geometry_preflight_review(self):
        codes = (
            "adaptive_interface_stagnation_not_contracted",
            "adaptive_interface_stagnation_diameter_not_contracted",
            "adaptive_stagnation_direction_seed_limit",
            "adaptive_stagnation_future_direction_guard",
        )
        for code in codes:
            with self.subTest(code=code):
                record = self._record(
                    _precheck(),
                    _failed(
                        code,
                        {
                            "phase": "interface_refinement",
                            "maximum": 2_000_000,
                            "refinement_passes": 2,
                            "maximum_child_parent_diameter_ratio": 0.91,
                        },
                    ),
                )
                self.assertEqual(
                    record["failure"]["stage"], "interface_refinement"
                )
                self.assertEqual(record["failure"]["category"], "stagnation")
                self.assertEqual(record["failure"]["code"], code)
                self.assertNotIn("unclassified_code_digest", record["failure"])
                self.assertEqual(len(record["recommendations"]), 1)
                recommendation = record["recommendations"][0]
                self.assertEqual(
                    recommendation["action"],
                    "review_safer_geometry_before_interface_preflight",
                )
                self.assertIs(recommendation["automatic_run_allowed"], False)
                self.assertEqual(recommendation["next_mode"], "preflight_only")
                self.assertEqual(
                    recommendation["safety_contract"],
                    ledger_tool.SAFETY_CONTRACT,
                )
                self.assertIs(
                    recommendation["parameters"]["rerun_unchanged_allowed"],
                    False,
                )

    def test_invalid_stagnation_internal_code_remains_manual(self):
        code = "invalid_adaptive_stagnation_parent_cells"
        record = self._record(_precheck(), _failed(code))
        self.assertEqual(record["failure"]["stage"], "unknown")
        self.assertEqual(record["failure"]["code"], "unclassified_error")
        self.assertEqual(
            record["recommendations"][0]["action"], "manual_diagnosis_only"
        )

    def test_fallback_metadata_is_numeric_boolean_and_privacy_minimized(self):
        record = self._record(
            _precheck(),
            _failed(
                "localized_threshold_interface_too_deep",
                {
                    "threshold_mm": 0.1666667,
                    "refinement_cause": "interface",
                    "local_refinement_rounds": 8,
                    "ordinary_interface_refinement_rounds": 7,
                    "stagnation_fallback_refinement_rounds": 1,
                    "partner_refinement_rounds": 0,
                    "stagnation_policy": {
                        "use_full_diameter_fallback": True,
                        "same_spatial_lineage": True,
                        "spatial_lineage_overlap_fraction": 1.0,
                        "overdepth_contraction_ratio": 0.82,
                        "reason": "private model path must not be retained",
                        "signature": {
                            "origin_cell_sha256": "a" * 64,
                            "origin_cell_ids": [1, 2, 3],
                        },
                    },
                    "refinement_budget_route": {
                        "allowed": True,
                        "exhausted_interface_budget_replacement": True,
                        "maximum_stagnation_fallback_rounds": 1,
                        "route": "private_named_route",
                    },
                    "completed_local_refinement_rounds": [
                        {"parent_cell_examples": [4, 5, 6]}
                    ],
                },
            ),
        )
        evidence = record["failure"]["evidence"]
        self.assertEqual(record["failure"]["category"], "depth_proof")
        self.assertEqual(
            evidence["fallback_summary.refinement_cause"], "interface"
        )
        self.assertEqual(evidence["fallback_summary.local_refinement_rounds"], 8)
        self.assertIs(
            evidence["stagnation_policy.use_full_diameter_fallback"], True
        )
        self.assertEqual(
            evidence["stagnation_policy.overdepth_contraction_ratio"], 0.82
        )
        self.assertIs(
            evidence[
                "refinement_budget_route.exhausted_interface_budget_replacement"
            ],
            True,
        )
        serialized = json.dumps(record, sort_keys=True)
        for private in (
            "private model path",
            "private_named_route",
            "origin_cell_sha256",
            "origin_cell_ids",
            "parent_cell_examples",
        ):
            self.assertNotIn(private, serialized)

    def test_failed_only_preflight_record_remains_incomplete(self):
        failure = _failed("selected_part_self_intersection_detected")
        record = ledger_tool.build_attempt_record(
            {"FAILED": _artifact("FAILED", failure)}
        )
        self.assertEqual(record["outcome"], "failed")
        self.assertEqual(
            [event["kind"] for event in record["events"]], ["FAILED"]
        )
        self.assertFalse(record["correctness_key"]["complete"])
        self.assertEqual(
            [item["action"] for item in record["recommendations"]],
            ["repeat_current_strict_preflight"],
        )

    def test_merge_is_idempotent_and_builds_indexes(self):
        record = self._record(
            _precheck(),
            _failed(
                "variable_partition_cell_limit_exceeded",
                {"exact_capacity": 3_000_000, "maximum": 2_000_000},
            ),
        )
        once = ledger_tool.merge_attempts(None, [record])
        twice = ledger_tool.merge_attempts(once, [record])
        self.assertEqual(once, twice)
        self.assertEqual(twice["statistics"]["attempt_count"], 1)
        correctness = record["correctness_key"]["sha256"]
        self.assertEqual(
            twice["indexes"]["by_correctness_key"][correctness],
            [record["attempt_id"]],
        )

    def test_direct_and_embedded_precheck_conflict_fails_closed(self):
        direct = _precheck()
        embedded = _precheck(
            palette=["#111111", "#EEEEEE", "#2453C7", "#00A6C7"]
        )
        artifacts = {
            "PRECHECK": _artifact("PRECHECK", direct),
            "RUN": _artifact("RUN", _run(embedded)),
        }
        with self.assertRaisesRegex(
            ledger_tool.LedgerError, "run_precheck_conflicts"
        ):
            ledger_tool.build_attempt_record(artifacts)

    def test_changed_safety_contract_is_rejected(self):
        ledger = ledger_tool.new_ledger()
        ledger["safety_contract"]["maximum_partition_cells"] = 2_000_001
        with self.assertRaisesRegex(
            ledger_tool.LedgerError, "ledger_safety_contract_changed"
        ):
            ledger_tool.merge_attempts(ledger, [])
        changed_policy = ledger_tool.new_ledger()
        changed_policy["policy"]["automatic_retry_allowed"] = True
        with self.assertRaisesRegex(
            ledger_tool.LedgerError, "ledger_policy_changed"
        ):
            ledger_tool.merge_attempts(changed_policy, [])

    def test_existing_ledger_with_private_field_is_rejected(self):
        record = self._record(_precheck())
        ledger = ledger_tool.merge_attempts(None, [record])
        ledger["attempts"][0]["configuration"]["input"] = (
            SYNTHETIC_PRIVATE_ROOT + ".glb"
        )
        with self.assertRaisesRegex(
            ledger_tool.LedgerError,
            "ledger_contains_forbidden_private_field",
        ):
            ledger_tool.merge_attempts(ledger, [])

    def test_cli_ingest_writes_atomic_privacy_minimized_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            precheck = _precheck()
            failure = _failed(
                "variable_partition_cell_limit_exceeded",
                {"exact_capacity": 3_000_000, "maximum": 2_000_000},
            )
            (root / "private_job_PRECHECK.json").write_text(
                json.dumps(precheck), encoding="utf-8"
            )
            (root / "private_job_RUN.json").write_text(
                json.dumps(_run(precheck)), encoding="utf-8"
            )
            (root / "private_job_FAILED.json").write_text(
                json.dumps(failure), encoding="utf-8"
            )
            ledger_path = root / "attempts.json"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = ledger_tool.main(
                    [
                        "ingest",
                        "--ledger",
                        str(ledger_path),
                        str(root),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("ledger_updated", output.getvalue())
            payload = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["statistics"]["attempt_count"], 1)
            serialized = ledger_path.read_text(encoding="utf-8")
            self.assertNotIn("Private Character", serialized)
            self.assertNotIn(SYNTHETIC_PRIVATE_PREFIX, serialized)
            self.assertEqual(list(root.glob("attempts.json.*.tmp")), [])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    ledger_tool.main(["validate", "--ledger", str(ledger_path)]),
                    0,
                )

    def test_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "attempt_PRECHECK.json"
            path.write_text(
                "{"
                '"schema":"chromamatter.tooling.generic-radial-launcher.v3",'
                '"schema":"chromamatter.tooling.generic-radial-launcher.v3",'
                '"status":"preflight_passed"'
                "}",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ledger_tool.LedgerError, "duplicate_json_key"
            ):
                ledger_tool.collect_artifact_groups([path])


if __name__ == "__main__":
    unittest.main()
