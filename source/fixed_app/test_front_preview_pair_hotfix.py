from __future__ import annotations

from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))

import spectrum_mapper_hotfix as hotfix  # noqa: E402
from spectrum_mapper import gui, renderer, workflow  # noqa: E402


class _Level:
    def __init__(self) -> None:
        self.vertices_unit = np.asarray(
            [
                [-1.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [-1.0, 0.0, 1.0],
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        self.faces = np.asarray([[0, 1, 2], [1, 3, 4]], dtype=np.int32)
        self.face_part_ids = np.asarray([0, 1], dtype=np.int16)
        self._hotfix_palette = object()
        self._hotfix_part_palette_rgb_tables = np.zeros((2, 16, 3), dtype=np.float32)
        self._hotfix_face_part_ids = self.face_part_ids


def _closed_cube_level():
    vertices = np.asarray(
        [
            [-1.0, -1.0, -1.0],
            [1.0, -1.0, -1.0],
            [1.0, 1.0, -1.0],
            [-1.0, 1.0, -1.0],
            [-1.0, -1.0, 1.0],
            [1.0, -1.0, 1.0],
            [1.0, 1.0, 1.0],
            [-1.0, 1.0, 1.0],
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            (0, 2, 1),
            (0, 3, 2),
            (4, 5, 6),
            (4, 6, 7),
            (0, 1, 5),
            (0, 5, 4),
            (3, 7, 6),
            (3, 6, 2),
            (0, 4, 7),
            (0, 7, 3),
            (1, 2, 6),
            (1, 6, 5),
        ],
        dtype=np.int32,
    )
    return SimpleNamespace(
        vertices_unit=vertices,
        faces=faces,
        face_part_ids=np.zeros(len(faces), dtype=np.int16),
    )


def _closed_cube_result():
    face_count = 12
    return SimpleNamespace(
        source_face_rgb=np.tile(
            np.asarray([[0.80, 0.12, 0.16]], dtype=np.float64),
            (face_count, 1),
        ),
        target_face_rgb=np.tile(
            np.asarray([[0.12, 0.75, 0.25]], dtype=np.float64),
            (face_count, 1),
        ),
        tone_face_rgb_flat=False,
    )


class _FakeInteractiveRenderer:
    instances: list["_FakeInteractiveRenderer"] = []

    def __init__(self, level, *, size, background) -> None:
        self.level = level
        self.size = size
        self.background = background
        self.closed = False
        self.render_calls: list[dict[str, object]] = []
        type(self).instances.append(self)

    def render(self, _result, **kwargs):
        self.render_calls.append(dict(kwargs))
        source = Image.new("RGB", self.size, (11, 12, 13))
        target = Image.new("RGB", self.size, (21, 22, 23))
        face_ids = np.full((self.size[1], self.size[0]), -1, dtype=np.int32)
        face_ids[2:8, 2:8] = 0
        face_ids[2:8, 8:14] = 1
        return renderer.InteractiveRenderFrame(
            source=source,
            target=target,
            face_ids=face_ids if kwargs.get("render_face_ids") else None,
            camera=renderer.CameraState(),
            pixels_per_unit=1.0,
        )

    def close(self) -> None:
        self.closed = True


class FrontPreviewPairHotfixTests(unittest.TestCase):
    def setUp(self) -> None:
        hotfix._discard_preview_renderer(threading.get_ident())
        _FakeInteractiveRenderer.instances.clear()

    def tearDown(self) -> None:
        hotfix._discard_preview_renderer(threading.get_ident())

    def test_runtime_namespaces_share_the_compatibility_wrapper(self) -> None:
        self.assertIs(
            renderer.render_front_preview_pair,
            hotfix._render_front_preview_pair_fixed,
        )
        self.assertIs(gui.render_front_preview_pair, renderer.render_front_preview_pair)
        self.assertIs(
            workflow.render_front_preview_pair,
            renderer.render_front_preview_pair,
        )

    def test_pair_preserves_adaptive_compose_then_outlines_and_reuses_cache(self) -> None:
        level = _Level()
        result = object()
        adaptive_trees = {0: object()}
        compose_calls: list[dict[str, object]] = []
        outline_inputs: list[tuple[int, int, int]] = []

        def compose(image, passed_level, passed_trees, **kwargs):
            self.assertIs(passed_level, level)
            self.assertIs(passed_trees, adaptive_trees)
            compose_calls.append(dict(kwargs))
            output = image.copy()
            output.putpixel((0, 0), (101, 102, 103))
            return output

        def outline(image, _face_ids, _part_ids, _part, **_kwargs):
            outline_inputs.append(image.getpixel((0, 0)))
            return image.copy()

        with (
            mock.patch.object(
                hotfix.renderer,
                "InteractiveMeshRenderer",
                _FakeInteractiveRenderer,
            ),
            mock.patch.object(
                hotfix._smooth_paint_hotfix,
                "lookup_tree_context",
                return_value=(adaptive_trees, 4),
            ),
            mock.patch.object(
                hotfix._smooth_paint_hotfix,
                "compose_target_image",
                side_effect=compose,
            ),
            mock.patch.object(
                hotfix.renderer,
                "overlay_active_part_outline",
                side_effect=outline,
            ),
        ):
            pair = renderer.render_front_preview_pair(
                level,
                result,
                size=(16, 16),
                background=(1, 2, 3),
                active_part_id=0,
            )
            legacy_target = renderer.render_front_preview(
                level,
                result,
                mode="target",
                size=(16, 16),
                background=(1, 2, 3),
            )

        self.assertEqual(len(_FakeInteractiveRenderer.instances), 1)
        instance = _FakeInteractiveRenderer.instances[0]
        self.assertEqual(len(instance.render_calls), 2)
        self.assertEqual(
            instance.render_calls[0],
            {
                "render_source": True,
                "render_target": True,
                "render_face_ids": True,
                "shaded": True,
            },
        )
        self.assertEqual(pair.face_ids.shape, (16, 16))
        self.assertEqual(pair.target.getpixel((0, 0)), (101, 102, 103))
        self.assertEqual(legacy_target.getpixel((0, 0)), (101, 102, 103))
        # Source is outlined first; target must already contain the adaptive
        # composite when its outline is applied.
        self.assertEqual(outline_inputs, [(11, 12, 13), (101, 102, 103)])
        self.assertEqual(len(compose_calls), 2)
        self.assertIs(
            compose_calls[0]["part_palette_rgb_tables"],
            level._hotfix_part_palette_rgb_tables,
        )
        self.assertIs(
            compose_calls[0]["face_part_ids"], level._hotfix_face_part_ids
        )

    def test_pair_falls_back_to_original_api_and_discards_broken_cache(self) -> None:
        level = _Level()
        sentinel = renderer.FrontPreviewPair(
            source=Image.new("RGB", (16, 16), (1, 1, 1)),
            target=Image.new("RGB", (16, 16), (2, 2, 2)),
            face_ids=np.full((16, 16), -1, dtype=np.int32),
        )

        class BrokenRenderer(_FakeInteractiveRenderer):
            def render(self, _result, **_kwargs):
                raise RuntimeError("simulated cached renderer failure")

        with (
            mock.patch.object(hotfix.renderer, "InteractiveMeshRenderer", BrokenRenderer),
            mock.patch.object(
                hotfix._smooth_paint_hotfix,
                "lookup_tree_context",
                return_value=None,
            ),
            mock.patch.object(
                hotfix,
                "_original_render_front_preview_pair",
                return_value=sentinel,
            ) as fallback,
        ):
            actual = renderer.render_front_preview_pair(
                level,
                object(),
                size=(16, 16),
                background=(1, 2, 3),
            )

        self.assertIs(actual, sentinel)
        fallback.assert_called_once()
        self.assertNotIn(threading.get_ident(), hotfix._preview_renderers)
        self.assertTrue(BrokenRenderer.instances[-1].closed)

    def test_named_view_composes_adaptive_paint_with_the_exact_named_mvp(
        self,
    ) -> None:
        level = _Level()
        adaptive_trees = {0: object()}
        face_ids = np.full((16, 16), -1, dtype=np.int32)
        face_ids[2:14, 2:14] = 0
        canonical = renderer.FrontPreviewPair(
            source=Image.new("RGB", (16, 16), (11, 12, 13)),
            target=Image.new("RGB", (16, 16), (21, 22, 23)),
            face_ids=face_ids,
        )
        compose_calls: list[dict[str, object]] = []

        def compose(image, passed_level, passed_trees, **kwargs):
            self.assertIs(passed_level, level)
            self.assertIs(passed_trees, adaptive_trees)
            compose_calls.append(dict(kwargs))
            output = image.copy()
            output.putpixel((0, 0), (101, 102, 103))
            return output

        with (
            mock.patch.object(
                hotfix,
                "_original_render_front_preview_pair",
                return_value=canonical,
            ) as canonical_render,
            mock.patch.object(
                hotfix._smooth_paint_hotfix,
                "lookup_tree_context",
                return_value=(adaptive_trees, 4),
            ),
            mock.patch.object(
                hotfix._smooth_paint_hotfix,
                "compose_target_image",
                side_effect=compose,
            ),
        ):
            pair = renderer.render_front_preview_pair(
                level,
                object(),
                size=(16, 16),
                background=(1, 2, 3),
                direction="back",
            )

        self.assertEqual(pair.target.getpixel((0, 0)), (101, 102, 103))
        self.assertEqual(len(compose_calls), 1)
        self.assertIsNone(compose_calls[0]["camera"])
        np.testing.assert_allclose(
            compose_calls[0]["projection_mvp"],
            renderer._camera_mvp(level.vertices_unit, (16, 16), "back"),
        )
        self.assertEqual(
            canonical_render.call_args.kwargs["active_part_id"], None
        )
        self.assertEqual(
            canonical_render.call_args.kwargs["direction"], "back"
        )

    def test_returning_to_front_rebuilds_renderer_after_named_view(self) -> None:
        level = _Level()
        result = object()
        named_pair = renderer.FrontPreviewPair(
            source=Image.new("RGB", (16, 16), (31, 32, 33)),
            target=Image.new("RGB", (16, 16), (41, 42, 43)),
            face_ids=np.full((16, 16), -1, dtype=np.int32),
        )

        with (
            mock.patch.object(
                hotfix.renderer,
                "InteractiveMeshRenderer",
                _FakeInteractiveRenderer,
            ),
            mock.patch.object(
                hotfix._smooth_paint_hotfix,
                "lookup_tree_context",
                return_value=None,
            ),
            mock.patch.object(
                hotfix,
                "_original_render_front_preview_pair",
                return_value=named_pair,
            ),
        ):
            first_front = renderer.render_front_preview_pair(
                level,
                result,
                size=(16, 16),
                background=(1, 2, 3),
                direction="front",
            )
            named = renderer.render_front_preview_pair(
                level,
                result,
                size=(16, 16),
                background=(1, 2, 3),
                direction="back",
            )
            returned_front = renderer.render_front_preview_pair(
                level,
                result,
                size=(16, 16),
                background=(1, 2, 3),
                direction="front",
            )

        self.assertEqual(first_front.source.getpixel((0, 0)), (11, 12, 13))
        self.assertIs(named.source, named_pair.source)
        self.assertIs(named.target, named_pair.target)
        self.assertEqual(returned_front.source.getpixel((0, 0)), (11, 12, 13))
        self.assertEqual(len(_FakeInteractiveRenderer.instances), 2)
        self.assertTrue(_FakeInteractiveRenderer.instances[0].closed)
        self.assertFalse(_FakeInteractiveRenderer.instances[1].closed)

    def test_single_source_preview_also_rebuilds_after_named_view(self) -> None:
        level = _Level()
        result = object()
        named_image = Image.new("RGB", (16, 16), (31, 32, 33))

        with (
            mock.patch.object(
                hotfix.renderer,
                "InteractiveMeshRenderer",
                _FakeInteractiveRenderer,
            ),
            mock.patch.object(
                hotfix,
                "_original_render_front_preview",
                return_value=named_image,
            ) as canonical_render,
        ):
            first_front = renderer.render_front_preview(
                level,
                result,
                mode="source",
                size=(16, 16),
                background=(1, 2, 3),
                direction="front",
            )
            named = renderer.render_front_preview(
                level,
                result,
                mode="source",
                size=(16, 16),
                background=(1, 2, 3),
                direction="left",
            )
            returned_front = renderer.render_front_preview(
                level,
                result,
                mode="source",
                size=(16, 16),
                background=(1, 2, 3),
                direction="front",
            )

        self.assertEqual(first_front.getpixel((0, 0)), (11, 12, 13))
        self.assertIs(named, named_image)
        self.assertEqual(returned_front.getpixel((0, 0)), (11, 12, 13))
        self.assertEqual(len(_FakeInteractiveRenderer.instances), 2)
        self.assertTrue(_FakeInteractiveRenderer.instances[0].closed)
        self.assertFalse(_FakeInteractiveRenderer.instances[1].closed)
        self.assertEqual(canonical_render.call_args.kwargs["direction"], "left")

    def test_real_gpu_front_pixels_remain_exact_after_every_named_view(self) -> None:
        level = _closed_cube_level()
        result = _closed_cube_result()
        background = np.asarray((9, 12, 17), dtype=np.uint8)

        try:
            first = renderer.render_front_preview_pair(
                level,
                result,
                size=(96, 120),
                background=tuple(int(value) for value in background),
                direction="front",
            )
        except renderer.RendererError as exc:
            self.skipTest(str(exc))
        expected_source = np.asarray(first.source).copy()
        expected_front = np.asarray(first.target).copy()
        expected_face_ids = np.asarray(first.face_ids).copy()
        self.assertGreater(
            int(
                np.count_nonzero(
                    np.any(expected_front != background[None, None, :], axis=2)
                )
            ),
            0,
        )
        self.assertTrue(bool(np.any(expected_face_ids >= 0)))
        self.assertGreaterEqual(int(expected_face_ids.min()), -1)
        self.assertLess(int(expected_face_ids.max()), len(level.faces))

        for direction in ("back", "left", "right", "top", "bottom"):
            with self.subTest(direction=direction):
                named = renderer.render_front_preview_pair(
                    level,
                    result,
                    size=(96, 120),
                    background=tuple(int(value) for value in background),
                    direction=direction,
                )
                named_pixels = np.asarray(named.target)
                self.assertGreater(
                    int(
                        np.count_nonzero(
                            np.any(
                                named_pixels != background[None, None, :],
                                axis=2,
                            )
                        )
                    ),
                    0,
                )
                returned = renderer.render_front_preview_pair(
                    level,
                    result,
                    size=(96, 120),
                    background=tuple(int(value) for value in background),
                    direction="front",
                )
                np.testing.assert_array_equal(
                    np.asarray(returned.target),
                    expected_front,
                )
                np.testing.assert_array_equal(
                    np.asarray(returned.source),
                    expected_source,
                )
                np.testing.assert_array_equal(
                    np.asarray(returned.face_ids),
                    expected_face_ids,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
