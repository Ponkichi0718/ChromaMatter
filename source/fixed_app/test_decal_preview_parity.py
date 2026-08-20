from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))

import smooth_paint  # noqa: E402
from spectrum_mapper import decal_projection as decal_projection_module  # noqa: E402
from spectrum_mapper.decal_projection import (  # noqa: E402
    DecalBakePlan,
    DecalProjectionCancelled,
    DecalTransform,
    _camera_signature,
    _rasterize_gl_triangle,
    _project_triangles,
    build_decal_preview,
    commit_decal_bake,
    composite_planned_decal_preview,
    plan_decal_bake,
    rasterize_decal_bake_plan,
    rasterize_existing_tree_states,
)
from spectrum_mapper.models import MeshLevel  # noqa: E402
from spectrum_mapper.paint import PaintSession  # noqa: E402
from spectrum_mapper import renderer as renderer_module  # noqa: E402
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


def face_id_map(
    level: MeshLevel, camera: CameraState, size: tuple[int, int]
) -> tuple[np.ndarray, np.ndarray]:
    triangles = _project_triangles(
        level, np.arange(len(level.faces), dtype=np.int32), camera, size
    )
    ids = np.full((size[1], size[0]), -1, dtype=np.int8)
    # Use the same half-open pixel-centre convention as the production pick
    # pass.  PIL's inclusive integer polygon rule adds an extra diagonal/outer
    # row and is precisely the preview/apply mismatch guarded by this module.
    unrestricted = np.zeros(ids.shape, dtype=np.int32)
    for face, triangle in enumerate(triangles):
        _rasterize_gl_triangle(
            ids,
            unrestricted,
            triangle,
            face=0,
            state=face,
        )
    return ids.astype(np.int32), triangles


def basic_palette() -> np.ndarray:
    colors = np.zeros((32, 3), dtype=np.float64)
    colors[0] = (0.15, 0.15, 0.15)
    colors[1] = (0.95, 0.05, 0.05)
    colors[2] = (0.05, 0.95, 0.05)
    for state in range(3, 32):
        colors[state] = state / 31.0
    return colors


def _read_uint_framebuffer_top_left(framebuffer, size: tuple[int, int]) -> np.ndarray:
    pixels = framebuffer.read(components=1, dtype="u4", alignment=1)
    raw = np.frombuffer(pixels, dtype=np.uint32).reshape(size[1], size[0])
    return np.flipud(raw).astype(np.int16, copy=True) - 1


def _render_gpu_face_ids(
    context,
    level: MeshLevel,
    camera: CameraState,
    size: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Render the production vertex/MVP/pixel-coverage path into R32UI."""

    vertices = np.asarray(level.vertices_unit, dtype=np.float32)
    faces = np.asarray(level.faces, dtype=np.int32)
    positions = np.ascontiguousarray(vertices[faces].reshape(-1, 3))
    mvp, _clean, _ppu = renderer_module._orbit_camera_mvp(vertices, size, camera)
    program = buffer = vao = texture = depth = framebuffer = None
    try:
        program = context.program(
            vertex_shader="""
                #version 330
                uniform mat4 mvp;
                in vec3 in_position;
                flat out uint v_face_id;
                void main() {
                    gl_Position = mvp * vec4(in_position, 1.0);
                    v_face_id = uint(gl_VertexID / 3) + 1u;
                }
            """,
            fragment_shader="""
                #version 330
                flat in uint v_face_id;
                layout(location = 0) out uint out_face_id;
                void main() { out_face_id = v_face_id; }
            """,
        )
        buffer = context.buffer(positions.tobytes())
        vao = context.vertex_array(program, [(buffer, "3f", "in_position")])
        texture = context.texture(size, 1, dtype="u4")
        depth = context.depth_renderbuffer(size)
        framebuffer = context.framebuffer([texture], depth)
        program["mvp"].write(mvp.T.astype(np.float32).tobytes())
        framebuffer.use()
        context.viewport = (0, 0, size[0], size[1])
        framebuffer.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        context.enable(renderer_module.moderngl.DEPTH_TEST | renderer_module.moderngl.CULL_FACE)
        context.disable(renderer_module.moderngl.BLEND)
        context.front_face = "ccw"
        context.cull_face = "back"
        vao.render(mode=renderer_module.moderngl.TRIANGLES)
        return _read_uint_framebuffer_top_left(framebuffer, size), mvp
    finally:
        for resource in (framebuffer, depth, texture, vao, buffer, program):
            if resource is not None:
                resource.release()


def _render_gpu_tree_states(
    context,
    level: MeshLevel,
    node: smooth_paint.PaintNode,
    mvp: np.ndarray,
    size: tuple[int, int],
) -> np.ndarray:
    """Render one adaptive tree with the production overlay's leaf geometry."""

    vertices = np.asarray(level.vertices_unit, dtype=np.float32)
    root = vertices[np.asarray(level.faces, dtype=np.int32)[0]]
    leaves = tuple(
        smooth_paint.iter_leaf_triangles(
            node, root, max_depth=smooth_paint.MAX_DEPTH
        )
    )
    positions = np.ascontiguousarray(
        np.asarray([leaf.vertices for leaf in leaves], dtype=np.float32).reshape(-1, 3)
    )
    states = np.ascontiguousarray(
        np.repeat(
            np.asarray([int(leaf.state) + 1 for leaf in leaves], dtype=np.uint32),
            3,
        )
    )
    program = position_buffer = state_buffer = vao = texture = depth = framebuffer = None
    try:
        program = context.program(
            vertex_shader="""
                #version 330
                uniform mat4 mvp;
                in vec3 in_position;
                in uint in_state;
                flat out uint v_state;
                void main() {
                    gl_Position = mvp * vec4(in_position, 1.0);
                    v_state = in_state;
                }
            """,
            fragment_shader="""
                #version 330
                flat in uint v_state;
                layout(location = 0) out uint out_state;
                void main() { out_state = v_state; }
            """,
        )
        position_buffer = context.buffer(positions.tobytes())
        state_buffer = context.buffer(states.tobytes())
        vao = context.vertex_array(
            program,
            [
                (position_buffer, "3f", "in_position"),
                (state_buffer, "1u", "in_state"),
            ],
        )
        texture = context.texture(size, 1, dtype="u4")
        depth = context.depth_renderbuffer(size)
        framebuffer = context.framebuffer([texture], depth)
        program["mvp"].write(np.asarray(mvp, dtype=np.float32).T.tobytes())
        framebuffer.use()
        context.viewport = (0, 0, size[0], size[1])
        framebuffer.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        context.enable(renderer_module.moderngl.DEPTH_TEST | renderer_module.moderngl.CULL_FACE)
        context.disable(renderer_module.moderngl.BLEND)
        context.front_face = "ccw"
        context.cull_face = "back"
        vao.render(mode=renderer_module.moderngl.TRIANGLES)
        return _read_uint_framebuffer_top_left(framebuffer, size)
    finally:
        for resource in (
            framebuffer,
            depth,
            texture,
            vao,
            state_buffer,
            position_buffer,
            program,
        ):
            if resource is not None:
                resource.release()


class PlannedPreviewParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.level = one_triangle()
        self.camera = CameraState()
        self.size = (128, 128)
        self.ids, self.triangles = face_id_map(
            self.level, self.camera, self.size
        )
        self.session = PaintSession(
            self.level, 100.0, np.asarray((0,), dtype=np.int8)
        )
        self.center = tuple(np.mean(self.triangles[0], axis=0))

    def _ring_preview(self):
        rgba = np.zeros((64, 64, 4), dtype=np.uint8)
        yy, xx = np.mgrid[:64, :64]
        radius = np.sqrt((xx - 31.5) ** 2 + (yy - 31.5) ** 2)
        ring = (radius >= 18.0) & (radius <= 27.0)
        rgba[ring] = (255, 0, 0, 255)
        return build_decal_preview(
            rgba,
            DecalTransform(self.center, 78.0, rotation_degrees=11.0),
            self.ids,
            self.session.allowed_face_mask,
            np.asarray((True,)),
            basic_palette(),
            np.ones(32, dtype=bool),
            mode="selected",
            selected_state=1,
            frame_generation=7,
        )

    def test_thin_ring_plan_raster_is_identical_to_post_bake_tree_raster(self) -> None:
        preview = self._ring_preview()
        before = rasterize_existing_tree_states(
            self.level,
            {},
            self.ids,
            self.camera,
            self.size,
            self.session.effective_indices(),
        )
        plan = plan_decal_bake(
            self.level,
            self.session,
            preview,
            self.camera,
            self.size,
            {},
            protect_manual=False,
            max_depth=smooth_paint.MAX_DEPTH,
        )
        planned = rasterize_decal_bake_plan(
            self.level,
            preview,
            plan,
            self.camera,
            self.size,
            base_state_map=before,
        )

        store: dict[int, smooth_paint.PaintNode] = {}
        commit_decal_bake(
            self.session,
            store,
            None,
            plan,
            current_frame_generation=7,
            current_camera=self.camera,
        )
        after = rasterize_existing_tree_states(
            self.level,
            store,
            self.ids,
            self.camera,
            self.size,
            self.session.effective_indices(),
        )
        expected = np.where(after != before, after, -1).astype(np.int8)
        np.testing.assert_array_equal(planned, expected)
        planned_pixels = planned >= 0
        expected_pixels = expected >= 0
        intersection = int(np.count_nonzero(planned_pixels & expected_pixels))
        union = int(np.count_nonzero(planned_pixels | expected_pixels))
        self.assertGreater(union, 0)
        self.assertEqual(intersection / union, 1.0)
        self.assertFalse(planned.flags.writeable)

    def test_thin_ring_plan_raster_matches_actual_moderngl_leaf_coverage(self) -> None:
        try:
            context = renderer_module._create_context()
        except renderer_module.RendererError as exc:
            self.skipTest(f"OpenGL 3.3 test context is unavailable: {exc}")
        try:
            gpu_ids, mvp = _render_gpu_face_ids(
                context, self.level, self.camera, self.size
            )
            self.assertGreater(int(np.count_nonzero(gpu_ids == 0)), 100)
            session = PaintSession(
                self.level, 100.0, np.asarray((0,), dtype=np.int8)
            )
            rgba = np.zeros((64, 64, 4), dtype=np.uint8)
            yy, xx = np.mgrid[:64, :64]
            radius = np.sqrt((xx - 31.5) ** 2 + (yy - 31.5) ** 2)
            rgba[(radius >= 18.0) & (radius <= 27.0)] = (255, 0, 0, 255)
            preview = build_decal_preview(
                rgba,
                DecalTransform(self.center, 78.0, rotation_degrees=11.0),
                gpu_ids,
                session.allowed_face_mask,
                np.asarray((True,)),
                basic_palette(),
                np.ones(32, dtype=bool),
                mode="selected",
                selected_state=1,
                frame_generation=13,
            )
            plan = plan_decal_bake(
                self.level,
                session,
                preview,
                self.camera,
                self.size,
                {},
                protect_manual=False,
                max_depth=smooth_paint.MAX_DEPTH,
            )
            self.assertFalse(plan.nodes_by_face[0].is_leaf)
            planned = rasterize_decal_bake_plan(
                self.level,
                preview,
                plan,
                self.camera,
                self.size,
                changed_only=False,
            )
            gpu_states = _render_gpu_tree_states(
                context,
                self.level,
                plan.nodes_by_face[0],
                mvp,
                self.size,
            )
            gpu_states[gpu_ids != 0] = -1
            visible = gpu_ids == 0
            agreement = float(np.mean(planned[visible] == gpu_states[visible]))
            planned_ring = planned == 1
            gpu_ring = gpu_states == 1
            intersection = int(np.count_nonzero(planned_ring & gpu_ring))
            union = int(np.count_nonzero(planned_ring | gpu_ring))
            self.assertGreater(union, 0)
            self.assertGreaterEqual(agreement, 0.999)
            self.assertGreaterEqual(intersection / union, 0.999)
        finally:
            context.release()

    def test_protected_or_noop_plan_raster_is_empty(self) -> None:
        preview = self._ring_preview()
        self.session.overrides[0] = 2
        protected = plan_decal_bake(
            self.level,
            self.session,
            preview,
            self.camera,
            self.size,
            {},
            protect_manual=True,
        )
        current = rasterize_existing_tree_states(
            self.level,
            {},
            self.ids,
            self.camera,
            self.size,
            self.session.effective_indices(),
        )
        raster = rasterize_decal_bake_plan(
            self.level,
            preview,
            protected,
            self.camera,
            self.size,
            base_state_map=current,
        )
        self.assertEqual(int(np.count_nonzero(raster >= 0)), 0)
        self.assertEqual(protected.protected_faces, 1)

    def test_semitransparent_overwrite_uses_exact_adaptive_underlay(self) -> None:
        colors = np.zeros((32, 3), dtype=np.float64)
        colors[0] = (0.0, 0.0, 0.0)
        colors[1] = (1.0, 0.0, 0.0)
        colors[2] = (0.0, 1.0, 0.0)
        colors[3] = (0.735, 0.0, 0.0)
        colors[4] = (0.735, 0.735, 0.0)
        enabled = np.zeros(32, dtype=bool)
        enabled[:5] = True
        existing = smooth_paint.PaintNode.branch(
            tuple(smooth_paint.PaintNode(value) for value in (0, 2, 0, 2))
        )
        store = {0: existing.clone()}
        self.session.overrides[0] = existing.dominant_state()
        before = rasterize_existing_tree_states(
            self.level,
            store,
            self.ids,
            self.camera,
            self.size,
            self.session.effective_indices(),
        )
        rgba = np.asarray([[[255, 0, 0, 128]]], dtype=np.uint8)
        preview = build_decal_preview(
            rgba,
            DecalTransform(self.center, 220.0),
            self.ids,
            self.session.allowed_face_mask,
            np.asarray((True,)),
            colors,
            enabled,
            base_state_map=before,
            frame_generation=9,
        )
        self.assertEqual(set(int(value) for value in np.unique(preview.state_map[preview.state_map >= 0])), {3, 4})
        plan = plan_decal_bake(
            self.level,
            self.session,
            preview,
            self.camera,
            self.size,
            store,
            protect_manual=False,
        )
        planned = rasterize_decal_bake_plan(
            self.level,
            preview,
            plan,
            self.camera,
            self.size,
            base_state_map=before,
            existing_trees=store,
        )
        commit_decal_bake(
            self.session,
            store,
            None,
            plan,
            current_frame_generation=9,
            current_camera=self.camera,
        )
        after = rasterize_existing_tree_states(
            self.level,
            store,
            self.ids,
            self.camera,
            self.size,
            self.session.effective_indices(),
        )
        expected = np.where(after != before, after, -1).astype(np.int8)
        np.testing.assert_array_equal(planned, expected)

    def test_shading_composite_uses_current_pixel_state_and_preserves_others(self) -> None:
        colors = np.zeros((32, 3), dtype=np.float64)
        colors[0] = (0.50, 0.35, 0.20)
        colors[1] = (0.15, 0.75, 0.40)
        current = np.full(self.ids.shape, -1, dtype=np.int8)
        current[self.ids == 0] = 0
        planned = np.full(self.ids.shape, -1, dtype=np.int8)
        ys, xs = np.nonzero(self.ids == 0)
        chosen = (ys > np.median(ys)) & (xs < np.median(xs))
        planned[ys[chosen], xs[chosen]] = 1
        source = np.full((*self.ids.shape, 3), (19, 23, 29), dtype=np.uint8)
        shaded = np.rint(colors[0] * 0.87 * 255.0).astype(np.uint8)
        source[self.ids == 0] = shaded
        base = Image.fromarray(source, "RGB")
        plan = DecalBakePlan(
            mesh_fingerprint="test",
            frame_generation=None,
            camera_signature=_camera_signature(self.camera),
            face_indices=np.asarray((0,), dtype=np.int32),
            expected_overrides=np.asarray((-1,), dtype=np.int8),
            expected_tree_codes=MappingProxyType({0: None}),
            nodes_by_face=MappingProxyType({0: smooth_paint.PaintNode(1)}),
            protected_faces=0,
            disconnected_faces=0,
            adaptive_roots=0,
            total_nodes=1,
            target_pixels=int(np.count_nonzero(planned >= 0)),
        )
        result = np.asarray(
            composite_planned_decal_preview(
                base,
                planned,
                self.ids,
                plan,
                colors,
                base_state_map=current,
            )
        )
        weights = np.asarray((0.2126, 0.7152, 0.0722))
        measured_luma = (shaded.astype(np.float64) / 255.0) @ weights
        shade = np.clip(measured_luma / max(float(colors[0] @ weights), 0.018), 0.22, 1.35)
        expected_color = np.rint(np.clip(colors[1] * shade, 0.0, 1.0) * 255.0).astype(np.uint8)
        self.assertTrue(np.all(result[planned == 1] == expected_color))
        np.testing.assert_array_equal(result[planned < 0], source[planned < 0])

    def test_large_tree_rasters_honor_immediate_request_cancellation(self) -> None:
        # A real history is capped by faces/nodes, but cancellation must be
        # checked before even walking a very large mapping supplied by a
        # closing preview request.
        large_store = {
            face: smooth_paint.PaintNode(0) for face in range(25_000)
        }
        with self.assertRaises(DecalProjectionCancelled):
            rasterize_existing_tree_states(
                self.level,
                large_store,
                self.ids,
                self.camera,
                self.size,
                self.session.effective_indices(),
                cancelled=lambda: True,
            )

        preview = self._ring_preview()
        plan = plan_decal_bake(
            self.level,
            self.session,
            preview,
            self.camera,
            self.size,
            {},
            protect_manual=False,
        )
        with self.assertRaises(DecalProjectionCancelled):
            rasterize_decal_bake_plan(
                self.level,
                preview,
                plan,
                self.camera,
                self.size,
                base_face_states=self.session.effective_indices(),
                cancelled=lambda: True,
            )

    def test_existing_history_is_filtered_to_exact_visible_face_ids(self) -> None:
        face_count = 2_048
        base = one_triangle()
        level = MeshLevel(
            vertices_unit=base.vertices_unit,
            faces=np.tile(base.faces, (face_count, 1)),
            vertex_colors=base.vertex_colors,
            areas_unit=np.full(face_count, 2.0, dtype=np.float64),
            neighbors=None,
            face_part_ids=np.zeros(face_count, dtype=np.int16),
            part_names=("part",),
            part_keys=("part",),
        )
        ids = np.full((32, 32), -1, dtype=np.int32)
        ids[8:24, 8:24] = 0
        store = {face: smooth_paint.PaintNode(face % 2) for face in range(face_count)}
        store[0] = smooth_paint.PaintNode.branch(
            tuple(smooth_paint.PaintNode(value) for value in (0, 1, 0, 1))
        )
        with patch.object(
            decal_projection_module,
            "_gpu_projected_triangles",
            wraps=decal_projection_module._gpu_projected_triangles,
        ) as projected:
            rasterize_existing_tree_states(
                level,
                store,
                ids,
                self.camera,
                (32, 32),
                np.zeros(face_count, dtype=np.int8),
            )
        projected.assert_called_once()
        self.assertEqual(projected.call_args.args[0].shape, (4, 3, 3))


if __name__ == "__main__":
    unittest.main()
