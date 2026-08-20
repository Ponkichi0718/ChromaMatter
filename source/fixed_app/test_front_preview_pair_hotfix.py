from __future__ import annotations

from pathlib import Path
import sys
import threading
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
