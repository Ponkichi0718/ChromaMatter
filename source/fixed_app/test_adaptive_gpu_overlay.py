from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

import adaptive_gpu_overlay as gpu_overlay
import smooth_paint
import smooth_paint_hotfix
from spectrum_mapper.models import AppSettings, PaletteSettings


try:
    from spectrum_mapper import renderer as _renderer_module
except ImportError:  # The mesh-only tests remain usable without recovered pyc.
    _renderer_module = None


if _renderer_module is not None:
    _RendererBase = _renderer_module.InteractiveMeshRenderer

    class _DepthProbeRenderer(_RendererBase):
        # Freeze the original methods on this test-only subclass.  Importing
        # the complete hotfix suite later may patch the production base class.
        __init__ = _RendererBase.__init__
        _render_color_image = _RendererBase._render_color_image
        _release_resources = _RendererBase._release_resources
        _adaptive_gpu_overlay_applied = False

    class _CacheProbeRenderer(_RendererBase):
        __init__ = _RendererBase.__init__
        _render_color_image = _RendererBase._render_color_image
        _release_resources = _RendererBase._release_resources
        _adaptive_gpu_overlay_applied = False

    class _ArenaProbeRenderer(_RendererBase):
        __init__ = _RendererBase.__init__
        _render_color_image = _RendererBase._render_color_image
        _release_resources = _RendererBase._release_resources
        _adaptive_gpu_overlay_applied = False

    class _ErrorProbeRenderer(_RendererBase):
        __init__ = _RendererBase.__init__
        _render_color_image = _RendererBase._render_color_image
        _release_resources = _RendererBase._release_resources
        _adaptive_gpu_overlay_applied = False


class _ProbePalette:
    physical_hex = ["#000000"] * 4
    mix_hex_overrides = [None] * 6
    mix_ratios_b = [50] * 6


class _GreenProbeMixer:
    @staticmethod
    def build_palette_rgb(_physical, _overrides, _ratios):
        return ["#00FF00"] * 10, np.repeat(
            np.asarray([[0.0, 1.0, 0.0]], dtype=np.float32), 10, axis=0
        )


class _FakeBuffer:
    def __init__(self, byte_count: int, *, initialized: bool) -> None:
        self.byte_count = int(byte_count)
        self.initialized = bool(initialized)
        self.writes: list[tuple[int, int]] = []
        self.released = False

    def write(self, data: bytes, *, offset: int = 0) -> None:
        size = len(data)
        if int(offset) < 0 or int(offset) + size > self.byte_count:
            raise ValueError("fake buffer write exceeds its allocation")
        self.writes.append((int(offset), size))

    def release(self) -> None:
        self.released = True


class _FakeVao:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _FakeContext:
    def __init__(self) -> None:
        self.buffers: list[_FakeBuffer] = []
        self.vaos: list[_FakeVao] = []

    def buffer(
        self,
        data: bytes | None = None,
        *,
        reserve: int = 0,
        dynamic: bool = False,
    ) -> _FakeBuffer:
        del dynamic
        initialized = data is not None
        byte_count = len(data) if data is not None else int(reserve)
        buffer = _FakeBuffer(byte_count, initialized=initialized)
        self.buffers.append(buffer)
        return buffer

    def vertex_array(self, _program, _bindings) -> _FakeVao:
        vao = _FakeVao()
        self.vaos.append(vao)
        return vao


def _branch(states: tuple[int, int, int, int]) -> smooth_paint.PaintNode:
    return smooth_paint.PaintNode.branch(
        tuple(smooth_paint.PaintNode(state) for state in states),
        split_sides=3,
    )


def _probe_level(store: dict[int, smooth_paint.PaintNode]) -> SimpleNamespace:
    # The winding faces the recovered renderer's default -Y camera.
    return SimpleNamespace(
        vertices_unit=np.asarray(
            ((-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (0.0, 0.0, 1.0)),
            dtype=np.float32,
        ),
        faces=np.asarray(((0, 1, 2),), dtype=np.int32),
        _hotfix_palette=_ProbePalette(),
        _probe_store=store,
        _probe_revision=1,
    )


def _probe_result(face_count: int = 1) -> SimpleNamespace:
    red = np.repeat(
        np.asarray(((1.0, 0.0, 0.0),), dtype=np.float32),
        int(face_count),
        axis=0,
    )
    return SimpleNamespace(source_face_rgb=red.copy(), target_face_rgb=red.copy())


def _grid_probe_level(
    face_count: int,
    store: dict[int, smooth_paint.PaintNode],
) -> SimpleNamespace:
    columns = max(1, int(np.ceil(np.sqrt(face_count))))
    rows = max(1, int(np.ceil(face_count / columns)))
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for face in range(face_count):
        column = face % columns
        row = face // columns
        x0 = -0.95 + 1.9 * column / columns
        x1 = -0.95 + 1.9 * (column + 0.78) / columns
        z0 = -0.95 + 1.9 * row / rows
        z1 = -0.95 + 1.9 * (row + 0.78) / rows
        start = len(vertices)
        vertices.extend(((x0, 0.0, z0), (x1, 0.0, z0), ((x0 + x1) / 2, 0.0, z1)))
        faces.append((start, start + 1, start + 2))
    return SimpleNamespace(
        vertices_unit=np.asarray(vertices, dtype=np.float32),
        faces=np.asarray(faces, dtype=np.int32),
        _hotfix_palette=_ProbePalette(),
        _probe_store=store,
        _probe_revision=1,
    )


def _deeper_branch(state: int) -> smooth_paint.PaintNode:
    root = smooth_paint.PaintNode(state)
    root.split_four()
    for child_index, child in enumerate(root.children):
        child.split_four()
        for leaf_index, leaf in enumerate(child.children):
            leaf.make_leaf((state + child_index + leaf_index + 1) % 10)
    return root


def _full_branch(depth: int, state: int) -> smooth_paint.PaintNode:
    root = smooth_paint.PaintNode(state)
    frontier = [root]
    for level in range(int(depth)):
        following = []
        for node in frontier:
            node.split_four()
            for child_index, child in enumerate(node.children):
                child.make_leaf((state + level + child_index) % 10)
                following.append(child)
        frontier = following
    return root


def _midpoint_tree_from_states(
    depth: int,
    states: list[int] | tuple[int, ...],
) -> smooth_paint.PaintNode:
    values = tuple(int(state) for state in states)
    expected = 4 ** int(depth)
    if len(values) != expected:
        raise ValueError("leaf-state count does not match depth")

    def build(start: int, count: int, remaining: int) -> smooth_paint.PaintNode:
        first = values[start]
        if all(values[index] == first for index in range(start + 1, start + count)):
            return smooth_paint.PaintNode(first)
        child_count = count // 4
        return smooth_paint.PaintNode.branch(
            tuple(
                build(start + child * child_count, child_count, remaining - 1)
                for child in range(4)
            ),
            split_sides=3,
        ).collapse()

    return build(0, expected, int(depth))


class AdaptiveGpuOverlayMeshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vertices = np.asarray(
            [
                [0.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [0.0, 2.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        self.faces = np.asarray([[0, 1, 2], [0, 3, 1]], dtype=np.int32)
        self.palette = np.linspace(0.05, 0.95, 30, dtype=np.float32).reshape(10, 3)

    def test_palette_usage_focus_is_a_small_display_lut_transform(self) -> None:
        focused = gpu_overlay._palette_usage_focus_table(
            self.palette,
            2,
            highlight=True,
        )
        muted = gpu_overlay._palette_usage_focus_table(
            self.palette,
            2,
            highlight=False,
        )
        self.assertEqual(focused.shape, self.palette.shape)
        self.assertGreater(float(focused[2, 1]), float(muted[2, 1]))
        np.testing.assert_allclose(focused[0], muted[0])
        np.testing.assert_array_equal(self.palette, np.linspace(0.05, 0.95, 30, dtype=np.float32).reshape(10, 3))

    def test_branch_becomes_one_gpu_triangle_per_leaf(self) -> None:
        node = smooth_paint.PaintNode(0)
        node.split_four()
        for state, child in enumerate(node.children):
            child.make_leaf(state + 1)

        packed = gpu_overlay.build_root_overlay_chunk(
            self.vertices, self.faces, 0, node, self.palette
        )

        self.assertEqual(packed.shape, (12, 9))
        for state in range(1, 5):
            expected = np.repeat(self.palette[state][None, :], 3, axis=0)
            np.testing.assert_allclose(
                packed[(state - 1) * 3 : state * 3, 6:9], expected
            )
        np.testing.assert_allclose(
            packed[:, 3:6],
            np.repeat(np.asarray([[0.0, 0.0, 1.0]]), len(packed), axis=0),
        )

        # Four midpoint children exactly cover the original triangle.
        child_area = 0.0
        for index in range(0, len(packed), 3):
            triangle = packed[index : index + 3, 0:3]
            child_area += 0.5 * float(
                np.linalg.norm(
                    np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
                )
            )
        self.assertAlmostEqual(child_area, 2.0, places=6)

    def test_leaf_invalid_face_and_degenerate_face_need_no_overlay(self) -> None:
        leaf = smooth_paint.PaintNode(2)
        self.assertEqual(
            len(
                gpu_overlay.build_root_overlay_chunk(
                    self.vertices, self.faces, 0, leaf, self.palette
                )
            ),
            0,
        )
        self.assertEqual(
            len(
                gpu_overlay.build_root_overlay_chunk(
                    self.vertices, self.faces, 99, leaf, self.palette
                )
            ),
            0,
        )

        branch = smooth_paint.PaintNode(0)
        branch.split_four()
        degenerate_faces = np.asarray([[0, 0, 0]], dtype=np.int32)
        self.assertEqual(
            len(
                gpu_overlay.build_root_overlay_chunk(
                    self.vertices, degenerate_faces, 0, branch, self.palette
                )
            ),
            0,
        )

    def test_overlay_info_marker_is_explicit(self) -> None:
        from PIL import Image

        image = Image.new("RGB", (8, 8))
        self.assertFalse(gpu_overlay.image_has_gpu_overlay(image))
        image.info[gpu_overlay.GPU_OVERLAY_INFO_KEY] = 4
        self.assertTrue(gpu_overlay.image_has_gpu_overlay(image))

    def test_batched_midpoint_chunks_match_general_orca_geometry(self) -> None:
        nodes = [
            _midpoint_tree_from_states(1, [0, 1, 2, 3]),
            _midpoint_tree_from_states(
                2,
                [0] * 4 + [1, 2, 1, 2] + [3] * 4 + [4, 5, 6, 7],
            ),
            _midpoint_tree_from_states(
                3,
                [
                    (leaf // 4) % 10 if leaf < 32 else leaf % 10
                    for leaf in range(64)
                ],
            ),
            smooth_paint.PaintNode.branch(
                (smooth_paint.PaintNode(2), smooth_paint.PaintNode(7)),
                split_sides=1,
                special_side=2,
            ),
            _full_branch(4, 3),
        ]
        level = _grid_probe_level(len(nodes), {})
        roots = list(enumerate(nodes))
        expected = [
            gpu_overlay.build_root_overlay_chunk(
                level.vertices_unit,
                level.faces,
                face,
                node,
                self.palette,
            )
            for face, node in roots
        ]

        with mock.patch.object(
            gpu_overlay,
            "build_root_overlay_chunk",
            wraps=gpu_overlay.build_root_overlay_chunk,
        ) as fallback:
            actual = gpu_overlay._build_root_overlay_chunks_batched(
                level.vertices_unit,
                level.faces,
                roots,
                self.palette,
                batch_roots=2,
            )

        self.assertEqual(fallback.call_count, 2)
        self.assertEqual(len(actual), len(expected))
        for scalar, batched in zip(expected, actual, strict=True):
            self.assertEqual(batched.shape, scalar.shape)
            np.testing.assert_array_equal(batched, scalar)

    def test_batched_chunks_select_the_palette_of_each_root_part(self) -> None:
        nodes = [
            _midpoint_tree_from_states(1, [0, 1, 2, 3]),
            _midpoint_tree_from_states(1, [4, 5, 6, 7]),
            _midpoint_tree_from_states(2, list(range(10)) + [9] * 6),
            smooth_paint.PaintNode.branch(
                (smooth_paint.PaintNode(2), smooth_paint.PaintNode(7)),
                split_sides=1,
                special_side=2,
            ),
        ]
        level = _grid_probe_level(len(nodes), {})
        roots = list(enumerate(nodes))
        second_palette = np.flip(self.palette, axis=0).copy()
        tables = np.stack((self.palette, second_palette), axis=0)
        face_part_ids = np.asarray((0, 1, 0, 1), dtype=np.int16)
        expected = [
            gpu_overlay.build_root_overlay_chunk(
                level.vertices_unit,
                level.faces,
                face,
                node,
                tables[int(face_part_ids[face])],
            )
            for face, node in roots
        ]

        actual = gpu_overlay._build_root_overlay_chunks_batched(
            level.vertices_unit,
            level.faces,
            roots,
            self.palette,
            batch_roots=2,
            face_part_ids=face_part_ids,
            part_palette_rgb_tables=tables,
        )

        for scalar, batched in zip(expected, actual, strict=True):
            np.testing.assert_array_equal(batched, scalar)

    def test_changing_one_part_palette_rebuilds_only_that_parts_roots(self) -> None:
        face_count = 40
        context = _FakeContext()
        faces = np.repeat(
            np.asarray([[0, 1, 2]], dtype=np.int32), face_count, axis=0
        )
        arena = gpu_overlay._OverlayArena(
            context,
            object(),
            self.vertices,
            faces,
            page_vertex_floor=768,
        )
        store = {
            face: _branch((0, 1, 2, 3)) for face in range(face_count)
        }
        face_part_ids = np.arange(face_count, dtype=np.int16) % 2
        tables = np.stack(
            (self.palette, np.flip(self.palette, axis=0)), axis=0
        ).astype(np.float32)
        keys = (("part", 0, "a"), ("part", 1, "b"))

        self.assertTrue(
            arena.sync(
                store,
                ("unused-common",),
                tables[0],
                face_part_ids=face_part_ids,
                part_palette_rgb_tables=tables,
                part_palette_keys=keys,
            )
        )
        allocations = {
            face: cached[3] for face, cached in arena.chunks.items()
        }
        unchanged_chunks = {
            face: cached[2]
            for face, cached in arena.chunks.items()
            if int(face_part_ids[face]) == 0
        }

        changed_tables = tables.copy()
        changed_tables[1] = np.float32(0.25)
        changed_keys = (keys[0], ("part", 1, "changed"))
        self.assertTrue(
            arena.sync(
                store,
                ("unused-common",),
                changed_tables[0],
                face_part_ids=face_part_ids,
                part_palette_rgb_tables=changed_tables,
                part_palette_keys=changed_keys,
            )
        )

        changed_root_count = face_count // 2
        chunk_bytes = 12 * gpu_overlay._VERTEX_STRIDE
        self.assertEqual(arena.rebuilt_roots, changed_root_count)
        self.assertEqual(arena.full_upload_bytes, 0)
        self.assertEqual(arena.partial_write_calls, changed_root_count)
        self.assertEqual(
            arena.partial_upload_bytes, changed_root_count * chunk_bytes
        )
        for face, cached in arena.chunks.items():
            self.assertIs(cached[3], allocations[face])
            if int(face_part_ids[face]) == 0:
                self.assertIs(cached[2], unchanged_chunks[face])
            else:
                np.testing.assert_array_equal(
                    cached[2][:, 6:9],
                    np.full((12, 3), 0.25, dtype=np.float32),
                )

    def test_editor_context_enables_multipart_gpu_routing(self) -> None:
        settings = AppSettings()
        settings.part_palettes["1:accent"] = PaletteSettings(
            physical_hex=["#000000", "#FFFFFF", "#FF0000", "#00FF00"]
        )
        level = SimpleNamespace(
            faces=np.asarray(((0, 1, 2), (3, 4, 5)), dtype=np.int32),
            part_keys=("0:body", "1:accent"),
            face_part_ids=np.asarray((0, 1), dtype=np.int16),
        )

        smooth_paint_hotfix._configure_gpu_palette_routing(settings, level)

        self.assertIsNotNone(level._hotfix_palette)
        self.assertEqual(level._hotfix_part_palette_rgb_tables.shape, (2, 32, 3))
        np.testing.assert_array_equal(level._hotfix_face_part_ids, (0, 1))
        self.assertFalse(level._hotfix_part_palette_rgb_tables.flags.writeable)
        self.assertFalse(level._hotfix_face_part_ids.flags.writeable)
        self.assertEqual(len(level._hotfix_part_palette_tokens), 2)

    def test_large_sync_writes_once_per_page_then_keeps_partial_updates(self) -> None:
        face_count = 300
        context = _FakeContext()
        arena = gpu_overlay._OverlayArena(
            context,
            object(),
            self.vertices,
            np.repeat(
                np.asarray([[0, 1, 2]], dtype=np.int32),
                face_count,
                axis=0,
            ),
            page_vertex_floor=96,
        )
        store = {
            face: _branch(
                (face % 10, (face + 1) % 10, (face + 2) % 10, (face + 3) % 10)
            )
            for face in range(face_count)
        }
        chunk_bytes = 12 * 9 * np.dtype(np.float32).itemsize

        with mock.patch.object(
            gpu_overlay,
            "build_root_overlay_chunk",
            wraps=gpu_overlay.build_root_overlay_chunk,
        ) as builder:
            self.assertTrue(arena.sync(store, ("palette-a",), self.palette))
            self.assertEqual(builder.call_count, 0)

            first_pages = tuple(arena.pages)
            first_buffers = tuple(page.buffer for page in first_pages)
            self.assertGreater(len(first_pages), 1)
            self.assertEqual(len(arena.chunks), face_count)
            self.assertEqual(arena.rebuilt_roots, face_count)
            self.assertEqual(arena.created_pages, len(first_pages))
            self.assertEqual(arena.released_pages, 0)
            self.assertEqual(arena.partial_write_calls, 0)
            self.assertEqual(arena.partial_upload_bytes, 0)
            self.assertEqual(
                arena.full_upload_bytes,
                sum(page.capacity_vertices for page in first_pages)
                * gpu_overlay._VERTEX_STRIDE,
            )
            for page in first_pages:
                self.assertEqual(
                    page.buffer.writes,
                    [(0, page.capacity_vertices * gpu_overlay._VERTEX_STRIDE)],
                )
                self.assertFalse(page.buffer.initialized)
                self.assertEqual(
                    len(page.allocations),
                    sum(
                        value[3].page is page
                        for value in arena.chunks.values()
                    ),
                )

            # A large palette invalidation takes the same page-batched route
            # and releases the prior generation only after the upload succeeds.
            builder.reset_mock()
            self.assertTrue(arena.sync(store, ("palette-b",), self.palette))
            self.assertEqual(builder.call_count, 0)
            self.assertEqual(arena.rebuilt_roots, face_count)
            self.assertEqual(arena.partial_write_calls, 0)
            self.assertEqual(arena.released_pages, len(first_pages))
            self.assertTrue(all(buffer.released for buffer in first_buffers))
            for page in arena.pages:
                self.assertEqual(len(page.buffer.writes), 1)

            # Once the bulk generation is established, an ordinary edit still
            # updates only that root's stable allocation.
            unchanged_allocation = arena.chunks[1][3]
            changed_allocation = arena.chunks[0][3]
            writes_before = sum(len(page.buffer.writes) for page in arena.pages)
            store[0] = _branch((9, 8, 7, 6))
            builder.reset_mock()
            self.assertTrue(arena.sync(store, ("palette-b",), self.palette))
            self.assertEqual(builder.call_count, 1)
            self.assertEqual(arena.rebuilt_roots, 1)
            self.assertEqual(arena.created_pages, 0)
            self.assertEqual(arena.released_pages, 0)
            self.assertEqual(arena.full_upload_bytes, 0)
            self.assertEqual(arena.partial_write_calls, 1)
            self.assertEqual(arena.partial_upload_bytes, chunk_bytes)
            self.assertEqual(
                sum(len(page.buffer.writes) for page in arena.pages),
                writes_before + 1,
            )
            self.assertIs(arena.chunks[0][3], changed_allocation)
            self.assertIs(arena.chunks[1][3], unchanged_allocation)

        final_buffers = tuple(page.buffer for page in arena.pages)
        arena.release()
        self.assertTrue(all(buffer.released for buffer in final_buffers))
        self.assertEqual(arena.pages, [])
        self.assertEqual(arena.chunks, {})


@unittest.skipIf(_renderer_module is None, "recovered renderer is unavailable")
class AdaptiveGpuOverlayIntegrationTests(unittest.TestCase):
    def test_large_initial_sync_uses_real_reserved_gpu_page(self) -> None:
        class BulkProbeRenderer(_RendererBase):
            __init__ = _RendererBase.__init__
            _render_color_image = _RendererBase._render_color_image
            _release_resources = _RendererBase._release_resources
            _adaptive_gpu_overlay_applied = False

        renderer_api = SimpleNamespace(
            InteractiveMeshRenderer=BulkProbeRenderer,
            moderngl=_renderer_module.moderngl,
        )
        gpu_overlay.install_gpu_overlay(
            renderer_api,
            _GreenProbeMixer,
            lambda level: (level._probe_store, level._probe_revision),
        )
        face_count = 300
        store = {
            face: _branch(
                (face % 10, (face + 1) % 10, (face + 2) % 10, (face + 3) % 10)
            )
            for face in range(face_count)
        }
        level = _grid_probe_level(face_count, store)
        try:
            renderer = BulkProbeRenderer(
                level, size=(192, 192), background=(0, 0, 0)
            )
        except _renderer_module.RendererError as exc:
            self.skipTest(f"OpenGL 3.3 test context is unavailable: {exc}")

        try:
            frame = renderer.render(
                _probe_result(face_count),
                render_source=False,
                render_face_ids=False,
            )
            self.assertTrue(gpu_overlay.image_has_gpu_overlay(frame.target))
            self.assertEqual(renderer._hotfix_overlay_rebuilt_roots, face_count)
            self.assertEqual(renderer._hotfix_overlay_partial_write_calls, 0)
            self.assertEqual(renderer._hotfix_overlay_partial_upload_bytes, 0)
            self.assertEqual(renderer._hotfix_overlay_created_pages, 1)
            self.assertEqual(len(renderer._hotfix_overlay_pages), 1)
            self.assertEqual(renderer._hotfix_overlay_vertex_count, face_count * 12)
        finally:
            renderer.close()

    def test_polygon_offset_prevents_base_colour_holes_across_orbit(self) -> None:
        renderer_api = SimpleNamespace(
            InteractiveMeshRenderer=_DepthProbeRenderer,
            moderngl=_renderer_module.moderngl,
        )
        gpu_overlay.install_gpu_overlay(
            renderer_api,
            _GreenProbeMixer,
            lambda level: (level._probe_store, level._probe_revision),
        )
        level = _probe_level({0: _branch((1, 2, 3, 4))})
        try:
            renderer = _DepthProbeRenderer(
                level, size=(240, 240), background=(0, 0, 0)
            )
        except _renderer_module.RendererError as exc:
            self.skipTest(f"OpenGL 3.3 test context is unavailable: {exc}")

        try:
            for yaw, pitch in (
                (0.0, 0.0),
                (15.0, 0.0),
                (45.0, 0.0),
                (75.0, 20.0),
                (-75.0, -20.0),
                (30.0, 25.0),
            ):
                with self.subTest(yaw=yaw, pitch=pitch):
                    frame = renderer.render(
                        _probe_result(),
                        camera=_renderer_module.CameraState(yaw, pitch, 1.0),
                        render_source=False,
                        render_face_ids=False,
                    )
                    self.assertTrue(gpu_overlay.image_has_gpu_overlay(frame.target))
                    pixels = np.asarray(frame.target)
                    green = (
                        (pixels[:, :, 1].astype(np.int16) > pixels[:, :, 0] + 10)
                        & (pixels[:, :, 1] > 10)
                    )
                    base_red_holes = (
                        (pixels[:, :, 0].astype(np.int16) > pixels[:, :, 1] + 10)
                        & (pixels[:, :, 0] > 10)
                    )
                    self.assertGreater(int(green.sum()), 100)
                    self.assertEqual(
                        int(base_red_holes.sum()),
                        0,
                        "coplanar base colour leaked through the adaptive overlay",
                    )
        finally:
            renderer.close()

    def test_chunk_cache_uses_strong_node_identity(self) -> None:
        renderer_api = SimpleNamespace(
            InteractiveMeshRenderer=_CacheProbeRenderer,
            moderngl=_renderer_module.moderngl,
        )
        gpu_overlay.install_gpu_overlay(
            renderer_api,
            _GreenProbeMixer,
            lambda level: (level._probe_store, level._probe_revision),
        )
        first = _branch((1, 2, 3, 4))
        level = _probe_level({0: first})
        try:
            renderer = _CacheProbeRenderer(
                level, size=(96, 96), background=(0, 0, 0)
            )
        except _renderer_module.RendererError as exc:
            self.skipTest(f"OpenGL 3.3 test context is unavailable: {exc}")

        try:
            renderer.render(
                _probe_result(), render_source=False, render_face_ids=False
            )
            self.assertEqual(renderer._hotfix_overlay_rebuilt_roots, 1)
            self.assertIs(renderer._hotfix_overlay_chunks[0][0], first)

            # A global revision may advance even when this particular root did
            # not change.  Its strong identity permits safe chunk reuse.
            level._probe_revision += 1
            renderer.render(
                _probe_result(), render_source=False, render_face_ids=False
            )
            self.assertEqual(renderer._hotfix_overlay_rebuilt_roots, 0)
            self.assertIs(renderer._hotfix_overlay_chunks[0][0], first)

            replacement = _branch((5, 6, 7, 8))
            level._probe_store[0] = replacement
            level._probe_revision += 1
            renderer.render(
                _probe_result(), render_source=False, render_face_ids=False
            )
            self.assertEqual(renderer._hotfix_overlay_rebuilt_roots, 1)
            self.assertIs(renderer._hotfix_overlay_chunks[0][0], replacement)
        finally:
            renderer.close()
        self.assertIsNone(renderer._hotfix_overlay_vao)
        self.assertIsNone(renderer._hotfix_overlay_buffer)
        self.assertEqual(renderer._hotfix_overlay_chunks, {})

    def test_one_changed_root_uses_partial_write_not_full_reupload(self) -> None:
        renderer_api = SimpleNamespace(
            InteractiveMeshRenderer=_ArenaProbeRenderer,
            moderngl=_renderer_module.moderngl,
        )
        gpu_overlay.install_gpu_overlay(
            renderer_api,
            _GreenProbeMixer,
            lambda level: (level._probe_store, level._probe_revision),
        )
        face_count = 96
        store = {
            face: _branch(
                (
                    face % 10,
                    (face + 1) % 10,
                    (face + 2) % 10,
                    (face + 3) % 10,
                )
            )
            for face in range(face_count)
        }
        level = _grid_probe_level(face_count, store)
        try:
            renderer = _ArenaProbeRenderer(
                level, size=(192, 192), background=(0, 0, 0)
            )
        except _renderer_module.RendererError as exc:
            self.skipTest(f"OpenGL 3.3 test context is unavailable: {exc}")

        try:
            first_frame = renderer.render(
                _probe_result(face_count),
                render_source=False,
                render_face_ids=False,
            )
            self.assertTrue(gpu_overlay.image_has_gpu_overlay(first_frame.target))
            self.assertEqual(renderer._hotfix_overlay_rebuilt_roots, face_count)
            self.assertGreater(renderer._hotfix_overlay_full_upload_bytes, 0)
            initial_pages = tuple(renderer._hotfix_overlay_pages)
            unchanged_allocation = renderer._hotfix_overlay_chunks[1][3]
            total_chunk_bytes = sum(
                value[2].nbytes
                for value in renderer._hotfix_overlay_chunks.values()
            )

            replacement = _branch((9, 8, 7, 6))
            store[0] = replacement
            level._probe_revision += 1
            second_frame = renderer.render(
                _probe_result(face_count),
                render_source=False,
                render_face_ids=False,
            )

            self.assertTrue(gpu_overlay.image_has_gpu_overlay(second_frame.target))
            self.assertEqual(renderer._hotfix_overlay_rebuilt_roots, 1)
            self.assertEqual(renderer._hotfix_overlay_full_upload_bytes, 0)
            self.assertEqual(renderer._hotfix_overlay_partial_write_calls, 1)
            self.assertEqual(
                renderer._hotfix_overlay_partial_upload_bytes,
                renderer._hotfix_overlay_chunks[0][2].nbytes,
            )
            self.assertLess(
                renderer._hotfix_overlay_uploaded_bytes,
                total_chunk_bytes // 10,
            )
            self.assertEqual(tuple(renderer._hotfix_overlay_pages), initial_pages)
            self.assertIs(
                renderer._hotfix_overlay_chunks[1][3], unchanged_allocation
            )
            self.assertIs(renderer._hotfix_overlay_chunks[0][0], replacement)
        finally:
            renderer.close()

    def test_every_leaf_is_drawn_when_overlay_spans_multiple_pages(self) -> None:
        class MultiPageProbeRenderer(_RendererBase):
            __init__ = _RendererBase.__init__
            _render_color_image = _RendererBase._render_color_image
            _release_resources = _RendererBase._release_resources
            _adaptive_gpu_overlay_applied = False

        renderer_api = SimpleNamespace(
            InteractiveMeshRenderer=MultiPageProbeRenderer,
            moderngl=_renderer_module.moderngl,
        )
        gpu_overlay.install_gpu_overlay(
            renderer_api,
            _GreenProbeMixer,
            lambda level: (level._probe_store, level._probe_revision),
        )
        # Each depth-6 root occupies a complete default page.  Both source
        # triangles must therefore be covered by two separate VAO draws.
        store = {0: _full_branch(6, 0), 1: _full_branch(6, 4)}
        level = _grid_probe_level(2, store)
        try:
            renderer = MultiPageProbeRenderer(
                level, size=(240, 240), background=(0, 0, 0)
            )
        except _renderer_module.RendererError as exc:
            self.skipTest(f"OpenGL 3.3 test context is unavailable: {exc}")

        try:
            frame = renderer.render(
                _probe_result(2), render_source=False, render_face_ids=False
            )
            self.assertTrue(gpu_overlay.image_has_gpu_overlay(frame.target))
            self.assertEqual(len(renderer._hotfix_overlay_pages), 2)
            self.assertEqual(renderer._hotfix_overlay_vertex_count, 24_576)
            pixels = np.asarray(frame.target)
            green = (
                (pixels[:, :, 1].astype(np.int16) > pixels[:, :, 0] + 10)
                & (pixels[:, :, 1] > 10)
            )
            red = (
                (pixels[:, :, 0].astype(np.int16) > pixels[:, :, 1] + 10)
                & (pixels[:, :, 0] > 10)
            )
            self.assertGreater(int(green.sum()), 100)
            self.assertEqual(int(red.sum()), 0)
        finally:
            renderer.close()

    def test_arena_handles_growth_delete_add_palette_and_releases_pages(self) -> None:
        renderer_api = SimpleNamespace(
            InteractiveMeshRenderer=_ArenaProbeRenderer,
            moderngl=_renderer_module.moderngl,
        )
        # Each test process may run this after the preceding method patched the
        # same class.  Use a fresh subclass so install remains isolated.
        class LifecycleProbeRenderer(_RendererBase):
            __init__ = _RendererBase.__init__
            _render_color_image = _RendererBase._render_color_image
            _release_resources = _RendererBase._release_resources
            _adaptive_gpu_overlay_applied = False

        renderer_api.InteractiveMeshRenderer = LifecycleProbeRenderer
        gpu_overlay.install_gpu_overlay(
            renderer_api,
            _GreenProbeMixer,
            lambda level: (level._probe_store, level._probe_revision),
        )
        store = {0: _branch((0, 1, 2, 3)), 1: _branch((4, 5, 6, 7))}
        level = _grid_probe_level(4, store)
        try:
            renderer = LifecycleProbeRenderer(
                level, size=(128, 128), background=(0, 0, 0)
            )
        except _renderer_module.RendererError as exc:
            self.skipTest(f"OpenGL 3.3 test context is unavailable: {exc}")

        pages_seen = []
        try:
            renderer.render(
                _probe_result(4), render_source=False, render_face_ids=False
            )
            pages_seen.extend(renderer._hotfix_overlay_pages)
            old_allocation = renderer._hotfix_overlay_chunks[0][3]

            # A deeper replacement exceeds the root's original allocation and
            # moves only that root to another free range.
            grown = _deeper_branch(2)
            store[0] = grown
            level._probe_revision += 1
            renderer.render(
                _probe_result(4), render_source=False, render_face_ids=False
            )
            grown_entry = renderer._hotfix_overlay_chunks[0]
            self.assertIs(grown_entry[0], grown)
            self.assertGreater(len(grown_entry[2]), old_allocation.capacity_vertices)
            self.assertIsNot(grown_entry[3], old_allocation)
            self.assertEqual(renderer._hotfix_overlay_full_upload_bytes, 0)

            # Deletion clears the old range; adding another face safely reuses
            # arena space without recreating every page.
            store.pop(1)
            level._probe_revision += 1
            renderer.render(
                _probe_result(4), render_source=False, render_face_ids=False
            )
            self.assertNotIn(1, renderer._hotfix_overlay_chunks)
            self.assertGreater(renderer._hotfix_overlay_partial_upload_bytes, 0)

            added = _branch((7, 6, 5, 4))
            store[2] = added
            level._probe_revision += 1
            renderer.render(
                _probe_result(4), render_source=False, render_face_ids=False
            )
            self.assertIs(renderer._hotfix_overlay_chunks[2][0], added)
            self.assertEqual(renderer._hotfix_overlay_full_upload_bytes, 0)

            # Palette changes intentionally recolour every root, but retain
            # allocations and use local writes rather than new VBOs.
            allocations = {
                face: value[3]
                for face, value in renderer._hotfix_overlay_chunks.items()
            }
            level._hotfix_palette.mix_ratios_b = [33] * 6
            level._probe_revision += 1
            renderer.render(
                _probe_result(4), render_source=False, render_face_ids=False
            )
            self.assertEqual(
                renderer._hotfix_overlay_rebuilt_roots, len(store)
            )
            self.assertEqual(renderer._hotfix_overlay_full_upload_bytes, 0)
            for face, allocation in allocations.items():
                self.assertIs(
                    renderer._hotfix_overlay_chunks[face][3], allocation
                )
            pages_seen.extend(renderer._hotfix_overlay_pages)
        finally:
            renderer.close()
        self.assertEqual(renderer._hotfix_overlay_pages, [])
        self.assertEqual(renderer._hotfix_overlay_chunks, {})
        self.assertTrue(pages_seen)

    def test_renderer_uses_part_tables_without_a_common_palette(self) -> None:
        class MultipartProbeRenderer(_RendererBase):
            __init__ = _RendererBase.__init__
            _render_color_image = _RendererBase._render_color_image
            _release_resources = _RendererBase._release_resources
            _adaptive_gpu_overlay_applied = False

        renderer_api = SimpleNamespace(
            InteractiveMeshRenderer=MultipartProbeRenderer,
            moderngl=_renderer_module.moderngl,
        )
        gpu_overlay.install_gpu_overlay(
            renderer_api,
            _GreenProbeMixer,
            lambda level: (level._probe_store, level._probe_revision),
        )
        store = {0: _branch((0, 0, 0, 0)), 1: _branch((0, 0, 0, 0))}
        level = _grid_probe_level(2, store)
        level._hotfix_palette = None
        green = np.repeat(
            np.asarray(((0.0, 1.0, 0.0),), dtype=np.float32), 10, axis=0
        )
        blue = np.repeat(
            np.asarray(((0.0, 0.0, 1.0),), dtype=np.float32), 10, axis=0
        )
        level._hotfix_part_palette_rgb_tables = np.stack((green, blue), axis=0)
        level._hotfix_face_part_ids = np.asarray((0, 1), dtype=np.int16)
        try:
            renderer = MultipartProbeRenderer(
                level, size=(128, 128), background=(0, 0, 0)
            )
        except _renderer_module.RendererError as exc:
            self.skipTest(f"OpenGL 3.3 test context is unavailable: {exc}")

        try:
            first = renderer.render(
                _probe_result(2), render_source=False, render_face_ids=False
            )
            self.assertTrue(gpu_overlay.image_has_gpu_overlay(first.target))
            self.assertEqual(renderer._hotfix_overlay_rebuilt_roots, 2)
            np.testing.assert_array_equal(
                renderer._hotfix_overlay_chunks[0][2][:, 6:9],
                np.repeat(green[0][None, :], 12, axis=0),
            )
            np.testing.assert_array_equal(
                renderer._hotfix_overlay_chunks[1][2][:, 6:9],
                np.repeat(blue[0][None, :], 12, axis=0),
            )
            body_allocation = renderer._hotfix_overlay_chunks[0][3]
            accent_allocation = renderer._hotfix_overlay_chunks[1][3]

            yellow = np.repeat(
                np.asarray(((1.0, 1.0, 0.0),), dtype=np.float32),
                10,
                axis=0,
            )
            level._hotfix_part_palette_rgb_tables = np.stack(
                (green, yellow), axis=0
            )
            level._probe_revision += 1
            second = renderer.render(
                _probe_result(2), render_source=False, render_face_ids=False
            )

            self.assertTrue(gpu_overlay.image_has_gpu_overlay(second.target))
            self.assertEqual(renderer._hotfix_overlay_rebuilt_roots, 1)
            self.assertEqual(renderer._hotfix_overlay_full_upload_bytes, 0)
            self.assertEqual(renderer._hotfix_overlay_partial_write_calls, 1)
            self.assertIs(
                renderer._hotfix_overlay_chunks[0][3], body_allocation
            )
            self.assertIs(
                renderer._hotfix_overlay_chunks[1][3], accent_allocation
            )
            np.testing.assert_array_equal(
                renderer._hotfix_overlay_chunks[1][2][:, 6:9],
                np.repeat(yellow[0][None, :], 12, axis=0),
            )
        finally:
            renderer.close()

    def test_failed_build_is_suppressed_for_the_same_revision_token(self) -> None:
        renderer_api = SimpleNamespace(
            InteractiveMeshRenderer=_ErrorProbeRenderer,
            moderngl=_renderer_module.moderngl,
        )
        gpu_overlay.install_gpu_overlay(
            renderer_api,
            _GreenProbeMixer,
            lambda level: (level._probe_store, level._probe_revision),
        )
        level = _probe_level({0: _branch((1, 2, 3, 4))})
        try:
            renderer = _ErrorProbeRenderer(
                level, size=(96, 96), background=(0, 0, 0)
            )
        except _renderer_module.RendererError as exc:
            self.skipTest(f"OpenGL 3.3 test context is unavailable: {exc}")

        try:
            with mock.patch.object(
                gpu_overlay,
                "build_root_overlay_chunk",
                side_effect=RuntimeError("synthetic arena build failure"),
            ) as builder:
                first = renderer.render(
                    _probe_result(), render_source=False, render_face_ids=False
                )
                second = renderer.render(
                    _probe_result(), render_source=False, render_face_ids=False
                )
                self.assertFalse(gpu_overlay.image_has_gpu_overlay(first.target))
                self.assertFalse(gpu_overlay.image_has_gpu_overlay(second.target))
                self.assertEqual(builder.call_count, 1)
                self.assertEqual(renderer._hotfix_overlay_pages, [])

                level._probe_revision += 1
                renderer.render(
                    _probe_result(), render_source=False, render_face_ids=False
                )
                self.assertEqual(builder.call_count, 2)
        finally:
            renderer.close()


if __name__ == "__main__":
    unittest.main()
