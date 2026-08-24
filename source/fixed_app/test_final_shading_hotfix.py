from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

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
        self.seen_tone_faces: list[np.ndarray | None] = []

        def generate_auto_shading(*args, **kwargs):
            del args
            mask = np.asarray(kwargs["face_mask"], dtype=bool).copy()
            self.seen_masks.append(mask)
            tone_faces = kwargs.get("tone_face_rgb")
            self.seen_tone_faces.append(
                None
                if tone_faces is None
                else np.asarray(tone_faces, dtype=np.float64).copy()
            )
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

    def test_flat_illustration_tone_is_passed_to_export_auto_shading(self) -> None:
        prepared = SimpleNamespace(final=self.level)
        tone_faces = np.asarray(
            ((0.2, 0.2, 0.2), (0.8, 0.8, 0.8)), dtype=np.float64
        )
        self.colors.tone_face_rgb = tone_faces
        self.colors.tone_face_rgb_flat = True

        result = self._generate(prepared)

        self.assertFalse(result.cache_hit)
        np.testing.assert_array_equal(self.seen_tone_faces[-1], tone_faces)

    def test_dominant_roots_delta_e_uses_tone_face_rgb(self) -> None:
        level = SimpleNamespace(
            faces=self.level.faces,
            areas_unit=np.asarray((0.5, 0.5), dtype=np.float64),
        )
        tone_faces = np.asarray(
            ((0.25, 0.25, 0.25), (0.75, 0.75, 0.75)),
            dtype=np.float64,
        )
        colors = SimpleNamespace(
            palette_indices=np.asarray((0, 1), dtype=np.int16),
            target_face_rgb=self.palette_rgb[[0, 1]].copy(),
            tone_vertex_rgb=np.full((4, 3), 0.5, dtype=np.float64),
            tone_face_rgb=tone_faces,
            # Deliberately unrelated raw source colours.  These must not enter
            # the post-adaptive report metric.
            source_face_rgb=np.asarray(
                ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), dtype=np.float64
            ),
            palette_face_counts=np.asarray((1, 1), dtype=np.int64),
            palette_area_fractions=np.asarray((0.5, 0.5), dtype=np.float64),
            delta_e=np.zeros(2, dtype=np.float64),
        )

        updated, _changed = hotfix.apply_dominant_roots(
            colors,
            level,
            {0: SimpleNamespace(dominant_state=lambda: 1)},
            self.palette_rgb,
        )

        expected = np.linalg.norm(
            hotfix._srgb_to_lab(tone_faces)
            - hotfix._srgb_to_lab(updated.target_face_rgb),
            axis=1,
        )
        np.testing.assert_allclose(updated.delta_e, expected, atol=0.0)

    def test_flat_four_writer_bypasses_adaptive_pipeline_without_mutating_colors(
        self,
    ) -> None:
        core_calls: list[tuple[object, object]] = []

        def core_writer(
            destination,
            prepared,
            colors,
            height_mm,
            palette,
            part_palettes=None,
            print_uses_global_palette=False,
        ):
            del destination, height_mm, part_palettes, print_uses_global_palette
            core_calls.append((colors, palette))
            return {"writer": "core"}

        def no_op(*args, **kwargs):
            del args, kwargs

        engine = SimpleNamespace(
            apply_palette_overrides=no_op,
            apply_palette_overrides_parts=no_op,
        )
        workflow = SimpleNamespace(
            write_3mf_atomic=core_writer,
        )
        smooth_hotfix = SimpleNamespace(
            _palette_rgb=lambda palette, mixer: np.zeros((32, 3), dtype=np.float64),
        )
        modules = {
            "spectrum_mapper.engine": engine,
            "spectrum_mapper.workflow": workflow,
            "spectrum_mapper.mixer": SimpleNamespace(),
            "auto_shading": SimpleNamespace(),
            "smooth_paint": SimpleNamespace(),
            "smooth_paint_hotfix": smooth_hotfix,
        }

        prepared = SimpleNamespace(final=self.level)
        cached = {"fingerprint": "mixed-state-cache", "trees": {0: "cached-tree"}}
        existing_trees = {1: "manual-tree"}
        setattr(prepared, hotfix.AUTO_CACHE_ATTRIBUTE, cached)
        setattr(prepared, hotfix.TREE_ATTRIBUTE, existing_trees)
        colors = SimpleNamespace(
            palette_indices=np.asarray((4, 31), dtype=np.int16),
            target_face_rgb=np.asarray(
                ((0.25, 0.25, 0.25), (0.75, 0.75, 0.75)), dtype=np.float64
            ),
        )
        original_indices = colors.palette_indices.copy()
        flat_palette = SimpleNamespace(color_mode="flat_four")
        export_colors = SimpleNamespace(
            palette_indices=np.asarray((7, 12), dtype=np.int16)
        )
        adaptive = SimpleNamespace(
            merged_trees={0: "generated-tree"},
            auto_trees={0: "generated-tree"},
            validation_dict=lambda changed: {"dominant_root_changes": changed},
        )
        installed_before = hotfix._INSTALLED
        try:
            hotfix._INSTALLED = False
            with (
                mock.patch.object(
                    hotfix.importlib,
                    "import_module",
                    side_effect=lambda name: modules[name],
                ),
                mock.patch.object(
                    hotfix, "generate_export_adaptive", return_value=adaptive
                ) as generate,
                mock.patch.object(
                    hotfix,
                    "apply_dominant_roots",
                    return_value=(export_colors, 2),
                ) as dominant,
                mock.patch.object(hotfix, "_sync_color_result") as sync,
            ):
                self.assertTrue(hotfix.install_export_adaptive_hotfix())
                validation = workflow.write_3mf_atomic(
                    "flat.3mf",
                    prepared,
                    colors,
                    10.0,
                    flat_palette,
                )

                self.assertEqual(validation, {"writer": "core"})
                generate.assert_not_called()
                dominant.assert_not_called()
                sync.assert_not_called()
                self.assertEqual(len(core_calls), 1)
                self.assertIs(core_calls[0][0], colors)
                self.assertIs(core_calls[0][1], flat_palette)

                # The adjacent Full Spectrum branch keeps the established
                # adaptive generation, dominant-root, and sync behavior.
                full_palette = SimpleNamespace(color_mode="full_spectrum")
                full_validation = workflow.write_3mf_atomic(
                    "full.3mf",
                    prepared,
                    colors,
                    10.0,
                    full_palette,
                )
                self.assertEqual(full_validation["writer"], "core")
                self.assertEqual(
                    full_validation["r8_export_adaptive"]["status"],
                    "generated",
                )
                generate.assert_called_once()
                dominant.assert_called_once()
                sync.assert_called_once_with(colors, export_colors)
                self.assertEqual(len(core_calls), 2)
                self.assertIs(core_calls[1][0], export_colors)
                self.assertIs(core_calls[1][1], full_palette)
        finally:
            hotfix._INSTALLED = installed_before

        np.testing.assert_array_equal(colors.palette_indices, original_indices)
        self.assertIs(getattr(prepared, hotfix.AUTO_CACHE_ATTRIBUTE), cached)
        self.assertIs(getattr(prepared, hotfix.TREE_ATTRIBUTE), existing_trees)


if __name__ == "__main__":
    unittest.main()
