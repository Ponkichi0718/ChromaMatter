from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

import smooth_paint
from smooth_paint_hotfix import carry_adaptive_trees_if_face_identity_exact
from spectrum_mapper.gui import MapperApp, _geometry_key
from spectrum_mapper.models import AppSettings, GeometrySettings
from spectrum_mapper.models import MeshLevel
from spectrum_mapper.paint import exact_face_paint_identity, mesh_fingerprint


def _levels() -> tuple[MeshLevel, MeshLevel]:
    """Return the same two ordered triangles before/after a seam-index weld."""

    before_vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0],  # UV-seam duplicate of vertex 1
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],  # UV-seam duplicate of vertex 2
        ],
        dtype=np.float64,
    )
    before_faces = np.asarray([[0, 1, 2], [5, 3, 4]], dtype=np.int32)
    after_vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
        ],
        dtype=np.float64,
    )
    after_faces = np.asarray([[0, 1, 2], [2, 1, 3]], dtype=np.int32)
    colors_before = np.zeros((len(before_vertices), 3), dtype=np.float64)
    colors_after = np.zeros((len(after_vertices), 3), dtype=np.float64)
    areas = np.asarray([0.5, 0.5], dtype=np.float64)
    neighbors = np.asarray([[-1, 1, -1], [-1, -1, 0]], dtype=np.int32)
    part_ids = np.zeros(2, dtype=np.int16)
    before = MeshLevel(
        vertices_unit=before_vertices,
        faces=before_faces,
        vertex_colors=colors_before,
        areas_unit=areas,
        neighbors=neighbors,
        face_part_ids=part_ids,
        part_names=("body",),
        part_keys=("0:body",),
    )
    after = MeshLevel(
        vertices_unit=after_vertices,
        faces=after_faces,
        vertex_colors=colors_after,
        areas_unit=areas.copy(),
        neighbors=neighbors.copy(),
        face_part_ids=part_ids.copy(),
        part_names=("body",),
        part_keys=("0:body",),
    )
    return before, after


class _Var:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


def _prepared(level: MeshLevel, *, solidified: bool) -> SimpleNamespace:
    source = SimpleNamespace(
        path=Path("C:/models/hi3d.glb"),
        sha256="same-private-source-digest",
    )
    assembly: dict[str, object] = {}
    if solidified:
        assembly = {
            "solidify_parts": True,
            "single_mesh_generic": True,
            "repair_method": "coincident_vertex_seam_weld",
            "repair_records": [
                {
                    "method": "coincident_vertex_seam_weld",
                    "source_triangle_geometry_preserved": True,
                    "simplification_applied": False,
                }
            ],
            "all_parts_watertight": True,
        }
    return SimpleNamespace(
        source=source,
        final=level,
        assembly=assembly,
        topology={"watertight": bool(solidified)},
    )


def _process_app(
    before: SimpleNamespace,
    after: SimpleNamespace,
    overrides: np.ndarray | None,
) -> MapperApp:
    old_settings = AppSettings(
        geometry=GeometrySettings(adjust_face_count=False, solidify_parts=False)
    )
    new_settings = AppSettings(
        geometry=GeometrySettings(adjust_face_count=False, solidify_parts=True)
    )
    app = MapperApp.__new__(MapperApp)
    app.root = object()
    app.paint_editor = None
    app.source_path = Path("C:/models/hi3d.glb")
    app.asset = before.source
    app.prepared = before
    app.prepared_key = _geometry_key(old_settings.geometry)
    app.manual_part_partition = None
    app.pending_manual_part_partition = None
    app.manual_joint_record = None
    app.pending_manual_joint_record = None
    app.pending_manual_payload = None
    app.manual_overrides = None if overrides is None else overrides.copy()
    app.manual_fingerprint = mesh_fingerprint(before.final)
    app.settings = new_settings
    app._variables_to_settings = Mock(return_value=new_settings)
    app._thread_progress = Mock()
    app._note_mix_input_change = Mock()
    app._refresh_black_free_gradient_widgets = Mock()
    app._update_face_count_status = Mock()
    app._refresh_part_selector = Mock()
    app._update_assembly_status = Mock()
    app._schedule_preview = Mock()
    app._auto_recommend_after_geometry = False
    app._manual_high_face_warning_key = None
    app.status_var = _Var("")

    def submit(_label, work, done, *, on_error=None):
        try:
            value = work()
        except Exception as exc:  # pragma: no cover - diagnostic guard
            if on_error is not None:
                return bool(on_error(exc, ""))
            raise
        done(value)
        return True

    app._submit_main = submit
    return app


class ExactGlbPaintIdentityTests(unittest.TestCase):
    def test_vertex_index_weld_is_exact_when_ordered_triangles_and_parts_match(self) -> None:
        before, after = _levels()

        self.assertTrue(exact_face_paint_identity(before, after, chunk_faces=1))

    def test_any_coordinate_bit_part_id_or_part_key_change_fails_proof(self) -> None:
        before, after = _levels()

        changed_vertices = after.vertices_unit.copy()
        changed_vertices[3, 0] = np.nextafter(changed_vertices[3, 0], 2.0)
        self.assertFalse(
            exact_face_paint_identity(
                before,
                replace(after, vertices_unit=changed_vertices),
            )
        )
        self.assertFalse(
            exact_face_paint_identity(
                before,
                replace(after, face_part_ids=np.asarray([0, 1], dtype=np.int16)),
            )
        )
        self.assertFalse(
            exact_face_paint_identity(
                before,
                replace(after, part_keys=("0:different",)),
            )
        )

    def test_triangle_reordering_and_face_count_change_fail_proof(self) -> None:
        before, after = _levels()
        reordered = after.faces.copy()
        reordered[1] = reordered[1, [1, 0, 2]]
        self.assertFalse(
            exact_face_paint_identity(before, replace(after, faces=reordered))
        )
        self.assertFalse(
            exact_face_paint_identity(
                before,
                replace(
                    after,
                    faces=after.faces[:1].copy(),
                    areas_unit=after.areas_unit[:1].copy(),
                    face_part_ids=after.face_part_ids[:1].copy(),
                ),
            )
        )


class ExactGlbAdaptiveCarryTests(unittest.TestCase):
    def test_exact_seam_weld_clones_every_adaptive_root(self) -> None:
        before_level, after_level = _levels()
        tree = smooth_paint.PaintNode.branch(
            [smooth_paint.PaintNode(value) for value in (1, 2, 3, 4)],
            split_sides=3,
        )
        before = SimpleNamespace(
            final=before_level,
            _hotfix_subtriangle_paint={1: tree},
            _hotfix_tree_revision=7,
        )
        after = SimpleNamespace(final=after_level)

        exact, count = carry_adaptive_trees_if_face_identity_exact(before, after)

        self.assertTrue(exact)
        self.assertEqual(count, 1)
        self.assertEqual(after._hotfix_tree_revision, 7)
        self.assertIsNot(after._hotfix_subtriangle_paint[1], tree)
        self.assertEqual(
            smooth_paint.encode_paint_color(after._hotfix_subtriangle_paint[1]),
            smooth_paint.encode_paint_color(tree),
        )

    def test_no_tree_is_carried_when_exact_geometry_proof_fails(self) -> None:
        before_level, after_level = _levels()
        changed_vertices = after_level.vertices_unit.copy()
        changed_vertices[3, 0] += 0.001
        after_level = replace(after_level, vertices_unit=changed_vertices)
        before = SimpleNamespace(
            final=before_level,
            _hotfix_subtriangle_paint={0: smooth_paint.PaintNode(3)},
        )
        after = SimpleNamespace(final=after_level)

        exact, count = carry_adaptive_trees_if_face_identity_exact(before, after)

        self.assertFalse(exact)
        self.assertEqual(count, 0)
        self.assertFalse(hasattr(after, "_hotfix_subtriangle_paint"))


class ExactGlbGuiCarryTests(unittest.TestCase):
    def test_explicit_seam_weld_carries_root_overrides_and_adaptive_trees_exactly(
        self,
    ) -> None:
        before_level, after_level = _levels()
        before = _prepared(before_level, solidified=False)
        after = _prepared(after_level, solidified=True)
        tree = smooth_paint.PaintNode.branch(
            [smooth_paint.PaintNode(value) for value in (1, 2, 3, 4)],
            split_sides=3,
        )
        before._hotfix_subtriangle_paint = {1: tree}
        before._hotfix_tree_revision = 9
        overrides = np.asarray([-1, 6], dtype=np.int8)
        app = _process_app(before, after, overrides)

        with (
            patch("spectrum_mapper.gui.prepare_geometry", return_value=after),
            patch("spectrum_mapper.gui.messagebox.askyesno", return_value=True),
            patch(
                "spectrum_mapper.gui.remap_manual_overrides",
                side_effect=AssertionError("exact seam carry must not approximate"),
            ),
        ):
            self.assertTrue(app._process_geometry(reuse_asset=True))

        np.testing.assert_array_equal(app.manual_overrides, overrides)
        self.assertIsNot(app.manual_overrides, overrides)
        self.assertEqual(app.manual_fingerprint, mesh_fingerprint(after.final))
        self.assertEqual(set(after._hotfix_subtriangle_paint), {1})
        self.assertIsNot(after._hotfix_subtriangle_paint[1], tree)
        self.assertIn("面順・形状一致で完全引継ぎ", app.status_var.get())
        self.assertIn("適応ブラシ 1面を完全引継ぎ", app.status_var.get())

    def test_qem_or_failed_exact_proof_keeps_nearest_root_remap_and_drops_trees(
        self,
    ) -> None:
        before_level, after_level = _levels()
        changed = after_level.vertices_unit.copy()
        changed[3, 0] += 0.01
        after_level = replace(after_level, vertices_unit=changed)
        before = _prepared(before_level, solidified=False)
        after = _prepared(after_level, solidified=True)
        repair = after.assembly["repair_records"][0]
        repair["source_triangle_geometry_preserved"] = False
        repair["simplification_applied"] = True
        before._hotfix_subtriangle_paint = {1: smooth_paint.PaintNode(2)}
        overrides = np.asarray([-1, 6], dtype=np.int8)
        remapped = np.asarray([5, 4], dtype=np.int8)
        app = _process_app(before, after, overrides)

        with (
            patch("spectrum_mapper.gui.prepare_geometry", return_value=after),
            patch("spectrum_mapper.gui.messagebox.askyesno", return_value=True),
            patch(
                "spectrum_mapper.gui.remap_manual_overrides",
                return_value=remapped.copy(),
            ) as remap,
        ):
            self.assertTrue(app._process_geometry(reuse_asset=True))

        remap.assert_called_once()
        np.testing.assert_array_equal(app.manual_overrides, remapped)
        self.assertFalse(hasattr(after, "_hotfix_subtriangle_paint"))
        self.assertIn("近傍面へ引継ぎ・要確認", app.status_var.get())
        self.assertNotIn("完全引継ぎ", app.status_var.get())

    def test_adaptive_tree_alone_triggers_topology_confirmation(self) -> None:
        before_level, after_level = _levels()
        before = _prepared(before_level, solidified=False)
        after = _prepared(after_level, solidified=True)
        before._hotfix_subtriangle_paint = {0: smooth_paint.PaintNode(1)}
        app = _process_app(before, after, None)

        with (
            patch("spectrum_mapper.gui.prepare_geometry") as prepare,
            patch("spectrum_mapper.gui.messagebox.askyesno", return_value=False),
        ):
            self.assertFalse(app._process_geometry(reuse_asset=True))

        prepare.assert_not_called()
        self.assertIs(app.prepared, before)
        self.assertEqual(before._hotfix_subtriangle_paint[0].state, 1)

    def test_invalid_tree_store_is_all_or_nothing(self) -> None:
        before_level, after_level = _levels()
        before = SimpleNamespace(
            final=before_level,
            _hotfix_subtriangle_paint={
                0: smooth_paint.PaintNode(3),
                len(before_level.faces): smooth_paint.PaintNode(4),
            },
        )
        after = SimpleNamespace(final=after_level)

        exact, count = carry_adaptive_trees_if_face_identity_exact(before, after)

        self.assertFalse(exact)
        self.assertEqual(count, 0)
        self.assertFalse(hasattr(after, "_hotfix_subtriangle_paint"))


if __name__ == "__main__":
    unittest.main()
