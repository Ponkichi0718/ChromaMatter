from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

import final_shading_hotfix as hotfix
from spectrum_mapper.generated_surface_color import (
    ADAPTIVE_ALLOWED_MASK_ATTRIBUTE,
)


class _Options:
    def __init__(self, **values) -> None:
        self.values = values


class FinalShadingHotfixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.level = SimpleNamespace(
            vertices_unit=np.asarray(
                (
                    (0.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                    (1.0, 1.0, 0.0),
                    (0.0, 1.0, 0.0),
                ),
                dtype=np.float64,
            ),
            faces=np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int32),
        )
        self.palette_rgb = np.asarray(
            ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), dtype=np.float64
        )
        self.colors = SimpleNamespace(
            palette_indices=np.asarray((0, 1), dtype=np.int16),
            target_face_rgb=np.asarray(
                ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
                dtype=np.float64,
            ),
            tone_vertex_rgb=np.full((4, 3), 0.5, dtype=np.float64),
            manual_override_faces=0,
        )
        self.palette = SimpleNamespace(enabled_states=(True, True))
        self.smooth_paint = SimpleNamespace(
            encode_paint_color=lambda node: str(node)
        )
        self.seen_masks: list[np.ndarray] = []

        def generate_auto_shading(*args, **kwargs):
            del args
            mask = np.asarray(kwargs["face_mask"], dtype=bool).copy()
            self.seen_masks.append(mask)
            count = int(np.count_nonzero(mask))
            return SimpleNamespace(
                trees={
                    int(face): f"tree-{int(face)}"
                    for face in np.flatnonzero(mask)
                },
                candidate_faces=count,
                selected_faces=count,
                adaptive_faces=count,
                total_leaves=count,
                budget_limited=False,
            )

        self.auto_shading = SimpleNamespace(
            AutoShadingOptions=_Options,
            generate_auto_shading=generate_auto_shading,
        )

    def _generate(self, prepared: object):
        return hotfix.generate_export_adaptive(
            prepared,
            self.colors,
            10.0,
            self.palette,
            palette_rgb=self.palette_rgb,
            auto_shading_module=self.auto_shading,
            smooth_paint_module=self.smooth_paint,
        )

    def test_hidden_generated_faces_are_excluded_and_mask_changes_cache_key(self) -> None:
        prepared = SimpleNamespace(final=self.level)
        setattr(
            prepared,
            ADAPTIVE_ALLOWED_MASK_ATTRIBUTE,
            np.asarray((False, True), dtype=bool),
        )

        hidden = self._generate(prepared)
        self.assertEqual(self.seen_masks[-1].tolist(), [False, True])
        self.assertEqual(set(hidden.auto_trees), {1})

        # Even a corrupted/restored cache entry cannot bypass the current
        # generated-surface policy at the cache-consumption boundary.
        cache = getattr(prepared, hotfix.AUTO_CACHE_ATTRIBUTE)
        cache["trees"] = {0: "stale-hidden-tree", **cache["trees"]}
        filtered = self._generate(prepared)
        self.assertTrue(filtered.cache_hit)
        self.assertEqual(set(filtered.auto_trees), {1})
        self.assertTrue(
            any("outside the current allowed mask" in value for value in filtered.warnings)
        )

        # A provenance/export-policy refresh may make a previously hidden face
        # eligible.  That change must invalidate the earlier adaptive cache.
        setattr(
            prepared,
            ADAPTIVE_ALLOWED_MASK_ATTRIBUTE,
            np.asarray((True, True), dtype=bool),
        )
        visible = self._generate(prepared)
        self.assertEqual(self.seen_masks[-1].tolist(), [True, True])
        self.assertFalse(visible.cache_hit)
        self.assertNotEqual(hidden.input_fingerprint, visible.input_fingerprint)

        cached = self._generate(prepared)
        self.assertTrue(cached.cache_hit)
        self.assertEqual(len(self.seen_masks), 2)

    def test_missing_generated_mask_keeps_original_r8_fingerprint_contract(self) -> None:
        without_context = SimpleNamespace(final=self.level)
        first = self._generate(without_context)

        all_allowed = SimpleNamespace(final=self.level)
        setattr(
            all_allowed,
            ADAPTIVE_ALLOWED_MASK_ATTRIBUTE,
            np.asarray((True, True), dtype=bool),
        )
        second = self._generate(all_allowed)

        self.assertEqual(first.input_fingerprint, second.input_fingerprint)
        self.assertEqual(first.auto_trees, second.auto_trees)


if __name__ == "__main__":
    unittest.main()
