from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

import auto_shading
import smooth_paint
import smooth_paint_hotfix
import spectrum_mapper_hotfix as runtime_hotfix
from spectrum_mapper.models import MeshLevel, PaletteSettings
from spectrum_mapper.paint import PaintSession
from spectrum_mapper.paint_gui import PaintEditorWindow


class _Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Button:
    def __init__(self, state: str = "normal"):
        self.state = state

    def configure(self, *, state: str):
        self.state = state


class AutoShadingIntegrationTests(unittest.TestCase):
    def test_boundary_scope_is_one_ring_and_preserves_manual_work(self) -> None:
        session = SimpleNamespace(
            overrides=np.asarray((-1, 4, -1, -1, -1), dtype=np.int8),
            neighbors=np.asarray(
                (
                    (1, -1, -1),
                    (0, 2, -1),
                    (1, 3, -1),
                    (2, 4, -1),
                    (3, -1, -1),
                ),
                dtype=np.int32,
            ),
            effective_indices=lambda: np.asarray(
                (0, 4, 1, 2, 2), dtype=np.int8
            ),
        )
        trees = {3: smooth_paint.PaintNode(2)}

        all_unedited = smooth_paint_hotfix._auto_shading_face_mask(
            session,
            trees,
            boundary_only=False,
        )
        boundary = smooth_paint_hotfix._auto_shading_face_mask(
            session,
            trees,
            boundary_only=True,
        )

        np.testing.assert_array_equal(
            all_unedited,
            np.asarray((True, False, True, False, True)),
        )
        np.testing.assert_array_equal(
            boundary,
            np.asarray((True, False, True, False, False)),
        )

    def test_worker_commits_one_command_and_undo_redo_restore_tree(self) -> None:
        vertices = np.asarray(
            ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)),
            dtype=np.float64,
        )
        faces = np.asarray(((0, 1, 2),), dtype=np.int32)
        level = MeshLevel(
            vertices,
            faces,
            np.zeros((3, 3), dtype=np.float64),
            np.asarray((2.0,), dtype=np.float64),
            np.full((1, 3), -1, dtype=np.int32),
        )
        session = PaintSession(
            level,
            100.0,
            np.asarray((0,), dtype=np.int8),
        )
        store: dict[int, smooth_paint.PaintNode] = {}
        owner = SimpleNamespace(_hotfix_tree_revision=0)
        session._hotfix_tree_store = store
        session._hotfix_tree_owner = owner
        generated_tree = smooth_paint.PaintNode.branch(
            tuple(smooth_paint.PaintNode(state) for state in (0, 1, 1, 1)),
            split_sides=3,
        )
        generated = auto_shading.AutoShadingResult(
            trees={0: generated_tree},
            candidate_faces=1,
            selected_faces=1,
            adaptive_faces=1,
            total_leaves=4,
            reserved_leaves=4,
            skipped_small_faces=0,
            budget_limited=False,
        )
        refresh_calls: list[tuple[str, int]] = []

        def refresh(message: str, changed: int):
            refresh_calls.append((message, changed))
            return {"message": message, "changed": changed}

        editor = object.__new__(PaintEditorWindow)
        editor._session = session
        editor._auto_colors = SimpleNamespace(
            tone_vertex_rgb=np.asarray(
                ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.5, 0.5)),
                dtype=np.float64,
            )
        )
        editor._hotfix_tree_store = store
        editor._hotfix_tree_owner = owner
        editor.prepared = owner
        editor.level = level
        editor.settings = SimpleNamespace(
            geometry=SimpleNamespace(height_mm=100.0),
            palette=PaletteSettings(),
        )
        editor._worker_refresh_after_edit = refresh

        with mock.patch.object(
            smooth_paint_hotfix.auto_shading,
            "generate_auto_shading",
            return_value=generated,
        ) as generate:
            snapshot = editor._run_auto_shading("standard", 0.4, False)

        self.assertTrue(snapshot["_hotfix_auto_shading_done"])
        self.assertNotIn("_hotfix_auto_shading_error", snapshot)
        self.assertEqual(len(session._undo), 1)
        self.assertEqual(refresh_calls, [("面内グラデーションを生成しました", 1)])
        self.assertEqual(owner._hotfix_tree_revision, 1)
        self.assertIs(store[0], generated_tree)
        self.assertEqual(int(session.overrides[0]), 1)

        call = generate.call_args
        self.assertTrue(bool(call.kwargs["face_mask"][0]))
        self.assertEqual(call.kwargs["options"].max_depth, 2)
        self.assertAlmostEqual(call.kwargs["options"].dither_strength, 0.4)

        encoded = smooth_paint.encode_paint_color(store[0])
        command = session._undo[-1]
        self.assertIsNot(command._hotfix_tree_after[0], store[0])
        session.undo()
        self.assertNotIn(0, store)
        self.assertEqual(int(session.overrides[0]), -1)
        session.redo()
        self.assertEqual(smooth_paint.encode_paint_color(store[0]), encoded)
        self.assertEqual(int(session.overrides[0]), 1)

    def test_queue_disables_button_and_submits_one_worker_job(self) -> None:
        button = _Button()
        status = _Variable("")
        submitted = []
        editor = SimpleNamespace(
            _close_requested=False,
            _hotfix_auto_shading_active=False,
            _hotfix_auto_shading_button=button,
            _hotfix_auto_shading_quality_var=_Variable("高品質"),
            _hotfix_auto_shading_strength_var=_Variable(75.0),
            _hotfix_auto_shading_boundary_var=_Variable(True),
            _hotfix_pending_stroke_batch=None,
            _hotfix_stroke_debounce_after=None,
            _commit_active_stroke=lambda: None,
            status_var=status,
            _submit=lambda kind, work: submitted.append((kind, work)),
        )

        PaintEditorWindow._queue_auto_shading(editor)

        self.assertTrue(editor._hotfix_auto_shading_active)
        self.assertEqual(button.state, "disabled")
        self.assertEqual(status.get(), "面内グラデーションを生成しています…")
        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0][0], "edit")

    def test_completion_snapshot_reenables_button_and_reports_error(self) -> None:
        button = _Button("disabled")
        consumed = []
        editor = SimpleNamespace(
            _hotfix_auto_shading_active=True,
            _hotfix_auto_shading_button=button,
            _close_requested=False,
            window=object(),
        )
        snapshot = {
            "_hotfix_auto_shading_done": True,
            "_hotfix_auto_shading_error": "synthetic failure",
            "message": "failed",
            "changed": 0,
        }

        with (
            mock.patch.object(
                runtime_hotfix,
                "_original_consume_snapshot",
                side_effect=lambda target, value: consumed.append((target, value)),
            ),
            mock.patch.object(
                runtime_hotfix.paint_gui.messagebox,
                "showerror",
            ) as showerror,
        ):
            PaintEditorWindow._consume_snapshot(editor, snapshot)

        self.assertFalse(editor._hotfix_auto_shading_active)
        self.assertEqual(button.state, "normal")
        self.assertEqual(consumed, [(editor, snapshot)])
        showerror.assert_called_once_with(
            "面内グラデーションを生成できません",
            "synthetic failure",
            parent=editor.window,
        )


if __name__ == "__main__":
    unittest.main()
