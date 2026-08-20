from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw


sys.path.insert(0, str(Path(__file__).resolve().parent))

import smooth_paint  # noqa: E402
from spectrum_mapper.decal_projection import (  # noqa: E402
    DecalProjectionCancelled,
    DecalProjectionError,
    DecalStalePreviewError,
    DecalTransform,
    _project_triangles,
    build_decal_preview,
    commit_decal_bake,
    decal_width_mm_to_pixels,
    plan_decal_bake,
)
from spectrum_mapper.decal_image import DecalImage, load_decal_bytes  # noqa: E402
from spectrum_mapper.models import MeshLevel  # noqa: E402
from spectrum_mapper.paint import PaintSession  # noqa: E402
from spectrum_mapper.renderer import CameraState  # noqa: E402


def one_triangle() -> MeshLevel:
    vertices = np.asarray(
        ((-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (-1.0, 0.0, 1.0)),
        dtype=np.float64,
    )
    return MeshLevel(
        vertices_unit=vertices,
        faces=np.asarray(((0, 1, 2),), dtype=np.int32),
        vertex_colors=np.full((3, 3), 0.5, dtype=np.float64),
        areas_unit=np.asarray((2.0,), dtype=np.float64),
        neighbors=None,
        face_part_ids=np.asarray((0,), dtype=np.int16),
        part_names=("part",),
        part_keys=("part",),
    )


def disconnected_pair() -> MeshLevel:
    vertices = np.asarray(
        (
            (-1.6, 0.0, -1.0),
            (-0.1, 0.0, -1.0),
            (-1.6, 0.0, 1.0),
            (0.1, 0.0, -1.0),
            (1.6, 0.0, -1.0),
            (0.1, 0.0, 1.0),
        ),
        dtype=np.float64,
    )
    return MeshLevel(
        vertices_unit=vertices,
        faces=np.asarray(((0, 1, 2), (3, 4, 5)), dtype=np.int32),
        vertex_colors=np.full((6, 3), 0.5, dtype=np.float64),
        areas_unit=np.asarray((1.5, 1.5), dtype=np.float64),
        neighbors=None,
        face_part_ids=np.asarray((0, 0), dtype=np.int16),
        part_names=("part",),
        part_keys=("part",),
    )


def palette() -> np.ndarray:
    result = np.zeros((32, 3), dtype=np.float64)
    result[1] = (1.0, 0.0, 0.0)
    result[2] = (0.0, 1.0, 0.0)
    result[3] = (1.0, 1.0, 1.0)
    for state in range(4, 32):
        result[state] = state / 31.0
    return result


def raster_face_ids(
    level: MeshLevel,
    camera: CameraState,
    size: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    face_indices = np.arange(len(level.faces), dtype=np.int32)
    triangles = _project_triangles(level, face_indices, camera, size)
    image = Image.new("I", size, -1)
    drawing = ImageDraw.Draw(image)
    for face, triangle in enumerate(triangles):
        drawing.polygon(
            [tuple(float(value) for value in point) for point in triangle],
            fill=int(face),
        )
    return np.asarray(image, dtype=np.int32), triangles


class DecalPreviewTests(unittest.TestCase):
    def test_active_and_visible_masks_clip_before_state_quantization(self) -> None:
        ids = np.asarray(((0, 0, 1, 1),) * 4, dtype=np.int32)
        rgba = np.zeros((2, 2, 4), dtype=np.uint8)
        rgba[...] = (255, 0, 0, 255)
        preview = build_decal_preview(
            DecalImage(rgba, "png"),
            DecalTransform((2.0, 2.0), 4.0),
            ids,
            np.asarray((True, False)),
            np.asarray((True, True)),
            palette(),
            np.asarray((True,) * 16 + (False,) * 16),
            frame_generation=4,
            base_face_states=np.asarray((0, 0), dtype=np.int8),
        )

        np.testing.assert_array_equal(preview.candidate_faces, (0,))
        self.assertTrue(np.all(preview.state_map[:, :2] == 1))
        self.assertTrue(np.all(preview.state_map[:, 2:] == -1))
        self.assertEqual(preview.metrics.clipped_pixels, 8)
        self.assertEqual(preview.frame_generation, 4)
        self.assertFalse(preview.state_map.flags.writeable)

    def test_strict_svg_loader_connects_to_projection_without_temp_files(self) -> None:
        decal = load_decal_bytes(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4">'
            b'<rect width="4" height="4" fill="#ff0000"/></svg>',
            filename="logo.svg",
        )
        ids = np.zeros((4, 4), dtype=np.int32)
        preview = build_decal_preview(
            decal,
            DecalTransform((2.0, 2.0), 4.0),
            ids,
            np.asarray((True,)),
            None,
            palette(),
            np.ones(32, dtype=bool),
            base_face_states=np.asarray((0,), dtype=np.int8),
        )
        self.assertEqual(decal.source_kind, "svg")
        self.assertEqual(tuple(preview.candidate_faces), (0,))
        self.assertTrue(np.all(preview.state_map == 1))

    def test_half_transparent_image_blends_with_current_surface_in_linear_rgb(self) -> None:
        ids = np.zeros((2, 2), dtype=np.int32)
        rgba = np.zeros((1, 1, 4), dtype=np.uint8)
        rgba[...] = (255, 0, 0, 128)
        colors = np.zeros((32, 3), dtype=np.float64)
        colors[0] = (0.0, 0.0, 0.0)
        colors[1] = (1.0, 0.0, 0.0)
        # linear 50% red is encoded near 0.735, not sRGB 0.5.
        colors[2] = (0.735, 0.0, 0.0)
        enabled = np.zeros(32, dtype=bool)
        enabled[:3] = True
        preview = build_decal_preview(
            rgba,
            DecalTransform((1.0, 1.0), 2.0),
            ids,
            np.asarray((True,)),
            None,
            colors,
            enabled,
            base_face_states=np.asarray((0,), dtype=np.int8),
        )
        self.assertTrue(np.all(preview.state_map == 2))
        self.assertTrue(np.all(preview.quantized_overlay_rgba[..., 3] == 255))

        with self.assertRaises(DecalProjectionError):
            build_decal_preview(
                rgba,
                DecalTransform((1.0, 1.0), 2.0),
                ids,
                np.asarray((True,)),
                None,
                colors,
                enabled,
            )

    def test_selected_mode_never_uses_disabled_or_image_colour(self) -> None:
        ids = np.zeros((2, 2), dtype=np.int32)
        rgba = np.asarray([[[0, 255, 0, 128]]], dtype=np.uint8)
        enabled = np.zeros(32, dtype=bool)
        enabled[[0, 7]] = True
        preview = build_decal_preview(
            rgba,
            DecalTransform((1.0, 1.0), 2.0),
            ids,
            np.asarray((True,)),
            None,
            palette(),
            enabled,
            mode="selected",
            selected_state=7,
        )
        self.assertTrue(np.all(preview.state_map == 7))
        with self.assertRaises(DecalProjectionError):
            build_decal_preview(
                rgba,
                DecalTransform((1.0, 1.0), 2.0),
                ids,
                np.asarray((True,)),
                None,
                palette(),
                enabled,
                mode="selected",
                selected_state=6,
            )


class DecalBakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.level = one_triangle()
        self.camera = CameraState()
        self.size = (96, 96)
        self.ids, self.triangles = raster_face_ids(
            self.level, self.camera, self.size
        )
        self.session = PaintSession(
            self.level, 100.0, np.asarray((0,), dtype=np.int8)
        )
        center = tuple(np.mean(self.triangles[0], axis=0))
        rgba = np.zeros((8, 8, 4), dtype=np.uint8)
        rgba[...] = (255, 0, 0, 255)
        self.preview = build_decal_preview(
            rgba,
            DecalTransform(center, 28.0, rotation_degrees=18.0),
            self.ids,
            self.session.allowed_face_mask,
            np.asarray((True,)),
            palette(),
            np.asarray((True,) * 16 + (False,) * 16),
            mode="selected",
            selected_state=1,
            frame_generation=11,
        )

    def test_partial_decal_builds_adaptive_tree_and_one_tree_aware_command(self) -> None:
        store: dict[int, smooth_paint.PaintNode] = {}
        owner = SimpleNamespace(_hotfix_tree_revision=0)
        plan = plan_decal_bake(
            self.level,
            self.session,
            self.preview,
            self.camera,
            self.size,
            store,
            protect_manual=False,
        )
        self.assertEqual(tuple(plan.face_indices), (0,))
        self.assertGreater(plan.adaptive_roots, 0)
        result = commit_decal_bake(
            self.session,
            store,
            owner,
            plan,
            current_frame_generation=11,
            current_camera=self.camera,
        )

        self.assertEqual(self.session.undo_depth, 1)
        self.assertEqual(tuple(result.changed_faces), (0,))
        self.assertIn(0, store)
        self.assertFalse(store[0].is_leaf)
        self.assertEqual(owner._hotfix_tree_revision, 1)
        command = result.command
        self.assertEqual(getattr(command, "_hotfix_tree_keys"), frozenset((0,)))
        self.assertEqual(getattr(command, "_hotfix_tree_before"), {})
        self.assertIn(0, getattr(command, "_hotfix_tree_after"))

    def test_transparent_logo_counter_remains_the_underlying_state(self) -> None:
        rgba = np.zeros((32, 32, 4), dtype=np.uint8)
        rgba[...] = (255, 0, 0, 255)
        rgba[10:22, 10:22, 3] = 0
        center = tuple(np.mean(self.triangles[0], axis=0))
        preview = build_decal_preview(
            rgba,
            DecalTransform(center, 70.0),
            self.ids,
            self.session.allowed_face_mask,
            np.asarray((True,)),
            palette(),
            np.asarray((True,) * 16 + (False,) * 16),
            mode="selected",
            selected_state=1,
        )
        plan = plan_decal_bake(
            self.level,
            self.session,
            preview,
            self.camera,
            self.size,
            {},
            protect_manual=False,
        )
        node = plan.nodes_by_face[0]
        self.assertFalse(node.is_leaf)
        self.assertGreater(node.state_areas()[0], 0.0)
        self.assertGreater(node.state_areas()[1], 0.0)

    def test_default_manual_protection_and_explicit_overwrite_snapshot(self) -> None:
        original = smooth_paint.PaintNode.branch(
            tuple(smooth_paint.PaintNode(state) for state in (2, 0, 0, 0))
        )
        store = {0: original.clone()}
        self.session._hotfix_tree_store = store
        self.session.overrides[0] = original.dominant_state()

        protected = plan_decal_bake(
            self.level,
            self.session,
            self.preview,
            self.camera,
            self.size,
            store,
        )
        self.assertEqual(len(protected.face_indices), 0)
        self.assertEqual(protected.protected_faces, 1)

        overwrite = plan_decal_bake(
            self.level,
            self.session,
            self.preview,
            self.camera,
            self.size,
            store,
            protect_manual=False,
        )
        result = commit_decal_bake(
            self.session,
            store,
            None,
            overwrite,
            current_frame_generation=11,
            current_camera=self.camera,
        )
        before = getattr(result.command, "_hotfix_tree_before")
        self.assertEqual(
            smooth_paint.encode_paint_color(before[0]),
            smooth_paint.encode_paint_color(original),
        )

    def test_stale_generation_camera_part_and_paint_are_rejected(self) -> None:
        plan = plan_decal_bake(
            self.level,
            self.session,
            self.preview,
            self.camera,
            self.size,
            {},
            protect_manual=False,
        )
        with self.assertRaises(DecalStalePreviewError):
            commit_decal_bake(
                self.session, {}, None, plan, current_frame_generation=12
            )
        with self.assertRaises(DecalStalePreviewError):
            commit_decal_bake(
                self.session,
                {},
                None,
                plan,
                current_frame_generation=11,
                current_camera=CameraState(yaw_degrees=1.0),
            )
        with self.assertRaises(DecalStalePreviewError):
            commit_decal_bake(
                self.session,
                {},
                None,
                plan,
                current_frame_generation=11,
                current_camera=self.camera,
                render_dirty=True,
            )
        self.session.allowed_face_mask[0] = False
        with self.assertRaises(DecalStalePreviewError):
            commit_decal_bake(
                self.session,
                {},
                None,
                plan,
                current_frame_generation=11,
                current_camera=self.camera,
            )

    def test_tree_history_round_trips_through_packaged_undo_redo_adapter(self) -> None:
        # The executable installs this adapter before the editor opens.  Import
        # it here, late in the class, so the focused core tests also exercise
        # the real history wrapper rather than only inspecting its attributes.
        import spectrum_mapper_hotfix  # noqa: F401

        store: dict[int, smooth_paint.PaintNode] = {}
        owner = SimpleNamespace(_hotfix_tree_revision=0)
        self.session._hotfix_tree_store = store
        self.session._hotfix_tree_owner = owner
        plan = plan_decal_bake(
            self.level,
            self.session,
            self.preview,
            self.camera,
            self.size,
            store,
            protect_manual=False,
        )
        commit_decal_bake(
            self.session,
            store,
            owner,
            plan,
            current_frame_generation=11,
            current_camera=self.camera,
        )
        after_code = smooth_paint.encode_paint_color(store[0])

        self.session.undo()
        self.assertEqual(store, {})
        np.testing.assert_array_equal(self.session.overrides, (-1,))
        self.session.redo()
        self.assertEqual(smooth_paint.encode_paint_color(store[0]), after_code)
        self.assertGreaterEqual(owner._hotfix_tree_revision, 3)

    def test_cancellation_happens_before_mutation(self) -> None:
        with self.assertRaises(DecalProjectionCancelled):
            plan_decal_bake(
                self.level,
                self.session,
                self.preview,
                self.camera,
                self.size,
                {},
                protect_manual=False,
                cancelled=lambda: True,
            )
        np.testing.assert_array_equal(self.session.overrides, (-1,))
        self.assertEqual(self.session.undo_depth, 0)

    def test_anchor_surface_island_does_not_jump_air_gap(self) -> None:
        level = disconnected_pair()
        camera = CameraState()
        size = (128, 96)
        ids, triangles = raster_face_ids(level, camera, size)
        session = PaintSession(level, 100.0, np.asarray((0, 0), dtype=np.int8))
        center = tuple(np.mean(triangles[0], axis=0))
        rgba = np.zeros((4, 4, 4), dtype=np.uint8)
        rgba[...] = (255, 0, 0, 255)
        preview = build_decal_preview(
            rgba,
            DecalTransform(center, 120.0),
            ids,
            session.allowed_face_mask,
            np.asarray((True, True)),
            palette(),
            np.ones(32, dtype=bool),
            mode="selected",
            selected_state=1,
        )
        self.assertEqual(set(int(value) for value in preview.candidate_faces), {0, 1})
        plan = plan_decal_bake(
            level,
            session,
            preview,
            camera,
            size,
            {},
            protect_manual=False,
        )
        np.testing.assert_array_equal(plan.face_indices, (0,))
        self.assertEqual(plan.disconnected_faces, 1)

    def test_dimension_helper_matches_normalized_model_scale(self) -> None:
        self.assertAlmostEqual(decal_width_mm_to_pixels(25.0, 100.0, 400.0), 100.0)


if __name__ == "__main__":
    unittest.main()
