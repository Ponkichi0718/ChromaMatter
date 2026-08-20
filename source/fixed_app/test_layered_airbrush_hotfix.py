from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import time
import tkinter as tk
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

import spectrum_mapper_hotfix as _application_hotfix  # noqa: F401
import smooth_paint
import smooth_paint_hotfix
from spectrum_mapper.models import AppSettings, GeometrySettings
from spectrum_mapper.paint_gui import PaintEditorWindow


class LayeredAirbrushHotfixIntegrationTests(unittest.TestCase):
    def test_real_worker_matches_sequential_roots_history_and_round_brush(self) -> None:
        from test_gui_integration import _pump, _tetra_prepared

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        prepared = _tetra_prepared()
        editor = None
        original_layered = smooth_paint.apply_layered_variable_capsule_segments
        original_layer_planner = smooth_paint_hotfix.airbrush_state_layers
        original_effective_mapping = (
            smooth_paint_hotfix._effective_states_for_face_mapping
        )
        records: list[dict[str, object]] = []
        process_faces: list[int] = []
        mismatches: list[tuple[str, str]] = []

        def fixed_nine_layers(
            source_state: int,
            target_state: int,
            *_args: object,
            **_kwargs: object,
        ) -> tuple[tuple[float, int], ...]:
            # Nine printable bands exercise the exact production loop shape.
            states = tuple(
                (int(target_state) + offset) % smooth_paint.STATE_COUNT
                for offset in range(8, -1, -1)
            )
            return tuple(
                (float(fraction), state)
                for fraction, state in zip(
                    np.linspace(0.96, 0.08, 9),
                    states,
                    strict=True,
                )
            )

        def record_effective_mapping(session, face_mapping):
            faces, states = original_effective_mapping(session, face_mapping)
            process_faces[:] = [int(face) for face in faces]
            return faces, states

        def audited_layered(
            node,
            vertices,
            segments_xy,
            radii,
            layers,
            **kwargs,
        ):
            before = node.clone()
            expected = before.clone()
            sequential_changed = False
            for radius_fraction, state in layers:
                result = smooth_paint.apply_variable_capsule_segments(
                    expected,
                    vertices,
                    segments_xy,
                    np.asarray(radii, dtype=np.float64)
                    * float(radius_fraction),
                    int(state),
                    **kwargs,
                )
                sequential_changed = sequential_changed or bool(result.changed)
            expected_code = smooth_paint.encode_paint_color(expected)
            actual_result = original_layered(
                node,
                vertices,
                segments_xy,
                radii,
                layers,
                **kwargs,
            )
            actual_code = smooth_paint.encode_paint_color(node)
            if expected_code != actual_code:
                mismatches.append((expected_code, actual_code))
            records.append(
                {
                    "before": before,
                    "expected": expected,
                    "vertices": np.asarray(vertices, dtype=np.float64).copy(),
                    "segments": np.asarray(segments_xy, dtype=np.float64).copy(),
                    "radii": np.asarray(radii, dtype=np.float64).copy(),
                    "layers": tuple(layers),
                    "kwargs": dict(kwargs),
                    "sequential_changed": sequential_changed,
                    "fused_changed": bool(actual_result.changed),
                }
            )
            return actual_result

        smooth_paint_hotfix.airbrush_state_layers = fixed_nine_layers
        smooth_paint_hotfix._effective_states_for_face_mapping = (
            record_effective_mapping
        )
        smooth_paint.apply_layered_variable_capsule_segments = audited_layered
        try:
            editor = PaintEditorWindow(
                root,
                prepared,
                AppSettings(
                    geometry=GeometrySettings(
                        height_mm=50.0,
                        target_faces=1_000,
                        preview_faces=1_000,
                        up_axis="Y",
                        min_component_faces=1,
                    )
                ),
                None,
                None,
                lambda _values: None,
            )
            editor.window.geometry("1100x780+30+30")
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor.face_ids is not None
                        and editor.target_mapping is not None
                        and not editor._job_running
                    ),
                ),
                editor.status_var.get(),
            )
            ids = np.asarray(editor.face_ids)
            left, top, width, height, render_width, render_height = (
                editor.target_mapping
            )

            def canvas_point(render_x: int, render_y: int) -> tuple[int, int]:
                return (
                    int(round(left + (render_x + 0.5) * width / render_width)),
                    int(round(top + (render_y + 0.5) * height / render_height)),
                )

            start = end = None
            for row in sorted(
                range(ids.shape[0]),
                key=lambda y: int(np.count_nonzero(ids[y] >= 0)),
                reverse=True,
            ):
                visible_x = np.flatnonzero(ids[row] >= 0)
                if len(visible_x) < 8:
                    continue
                candidate_start = canvas_point(
                    int(visible_x[len(visible_x) * 2 // 5]), row
                )
                candidate_end = canvas_point(
                    int(visible_x[len(visible_x) * 3 // 5]), row
                )
                if (
                    editor._face_at(*candidate_start) >= 0
                    and editor._face_at(*candidate_end) >= 0
                ):
                    start, end = candidate_start, candidate_end
                    break
            self.assertIsNotNone(start, "no paintable airbrush segment was found")
            self.assertIsNotNone(end, "no paintable airbrush segment was found")

            before_overrides = editor._session.overrides.copy()
            used_states = set(
                int(state) for state in np.asarray(editor.effective_indices)
            )
            target_state = next(
                state
                for state in range(smooth_paint.STATE_COUNT)
                if state not in used_states
            )
            editor.paint_state_var.set(target_state)
            editor.tool_var.set("airbrush")
            editor.airbrush_strength_var.set(100.0)
            editor.edge_guard_var.set(False)
            editor.brush_radius_var.set(2.0)
            editor._hotfix_stroke_debounce_ms = 1
            editor._on_left_press(SimpleNamespace(x=start[0], y=start[1], state=0))
            editor._on_left_motion(SimpleNamespace(x=end[0], y=end[1], state=0))
            editor._on_left_release(SimpleNamespace(x=end[0], y=end[1], state=0))
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor._session.undo_depth == 1
                        and editor._hotfix_pending_stroke_batch is None
                        and not editor._job_running
                    ),
                    timeout=10.0,
                ),
                editor.status_var.get(),
            )

            self.assertTrue(records)
            self.assertEqual(mismatches, [])
            self.assertEqual(len(records), len(process_faces))
            expected_changed_faces = [
                face
                for face, record in zip(process_faces, records, strict=True)
                if smooth_paint.encode_paint_color(record["before"])
                != smooth_paint.encode_paint_color(record["expected"])
            ]
            command = editor._session._undo[-1]
            np.testing.assert_array_equal(
                command.indices,
                np.asarray(sorted(expected_changed_faces), dtype=np.int32),
            )
            self.assertEqual(
                set(int(face) for face in command.indices),
                set(command._hotfix_tree_keys),
            )

            expected_by_face = {
                face: record["expected"]
                for face, record in zip(process_faces, records, strict=True)
            }
            automatic = np.asarray(editor._session.auto_indices, dtype=np.int8)
            for face in command.indices:
                face_id = int(face)
                expected = expected_by_face[face_id]
                if expected.is_leaf:
                    self.assertNotIn(face_id, editor._hotfix_tree_store)
                    expected_override = (
                        -1
                        if int(expected.state) == int(automatic[face_id])
                        else int(expected.state)
                    )
                    self.assertEqual(
                        int(editor._session.overrides[face_id]),
                        expected_override,
                    )
                else:
                    self.assertEqual(
                        smooth_paint.encode_paint_color(
                            editor._hotfix_tree_store[face_id]
                        ),
                        smooth_paint.encode_paint_color(expected),
                    )

            after_codes = {
                int(face): smooth_paint.encode_paint_color(node)
                for face, node in editor._hotfix_tree_store.items()
            }
            after_overrides = editor._session.overrides.copy()
            editor._session.undo()
            self.assertEqual(editor._hotfix_tree_store, {})
            np.testing.assert_array_equal(editor._session.overrides, before_overrides)
            editor._session.redo()
            self.assertEqual(
                {
                    int(face): smooth_paint.encode_paint_color(node)
                    for face, node in editor._hotfix_tree_store.items()
                },
                after_codes,
            )
            np.testing.assert_array_equal(editor._session.overrides, after_overrides)

            # Benchmark the exact per-face geometries captured by the real
            # worker, excluding UI/render time and the audit wrapper itself.
            def sequential_process() -> tuple[str, ...]:
                codes: list[str] = []
                for record in records:
                    node = record["before"].clone()
                    for radius_fraction, state in record["layers"]:
                        smooth_paint.apply_variable_capsule_segments(
                            node,
                            record["vertices"],
                            record["segments"],
                            record["radii"] * float(radius_fraction),
                            int(state),
                            **record["kwargs"],
                        )
                    codes.append(smooth_paint.encode_paint_color(node))
                return tuple(codes)

            def fused_process() -> tuple[str, ...]:
                codes: list[str] = []
                for record in records:
                    node = record["before"].clone()
                    original_layered(
                        node,
                        record["vertices"],
                        record["segments"],
                        record["radii"],
                        record["layers"],
                        **record["kwargs"],
                    )
                    codes.append(smooth_paint.encode_paint_color(node))
                return tuple(codes)

            self.assertEqual(sequential_process(), fused_process())
            timings: dict[str, list[float]] = {"sequential": [], "fused": []}
            for name, function in (
                ("sequential", sequential_process),
                ("fused", fused_process),
            ):
                for _ in range(3):
                    started = time.perf_counter()
                    function()
                    timings[name].append(time.perf_counter() - started)
            sequential_elapsed = min(timings["sequential"])
            fused_elapsed = min(timings["fused"])
            print(
                "real-worker layered airbrush speedup: "
                f"{sequential_elapsed / fused_elapsed:.2f}x "
                f"({sequential_elapsed:.4f}s -> {fused_elapsed:.4f}s, "
                f"roots={len(records)})"
            )
            self.assertLess(fused_elapsed, sequential_elapsed * 0.75)

            # A normal round brush must not enter the new layered path.
            layered_call_count = len(records)
            editor.tool_var.set("brush")
            editor.paint_state_var.set((target_state + 1) % smooth_paint.STATE_COUNT)
            editor._hotfix_brush_shape_var.set("round")
            editor._on_left_press(SimpleNamespace(x=start[0], y=start[1], state=0))
            editor._on_left_motion(SimpleNamespace(x=end[0], y=end[1], state=0))
            editor._on_left_release(SimpleNamespace(x=end[0], y=end[1], state=0))
            self.assertTrue(
                _pump(
                    root,
                    lambda: (
                        editor._session.undo_depth == 2
                        and editor._hotfix_pending_stroke_batch is None
                        and not editor._job_running
                    ),
                    timeout=10.0,
                ),
                editor.status_var.get(),
            )
            self.assertEqual(len(records), layered_call_count)
        finally:
            smooth_paint.apply_layered_variable_capsule_segments = original_layered
            smooth_paint_hotfix.airbrush_state_layers = original_layer_planner
            smooth_paint_hotfix._effective_states_for_face_mapping = (
                original_effective_mapping
            )
            if editor is not None:
                try:
                    editor.close()
                    _pump(root, lambda: not editor.window.winfo_exists(), 5.0)
                except Exception:
                    pass
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
