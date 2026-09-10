from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from spectrum_mapper.engine import (
    EngineError,
    apply_tone,
    apply_tone_faces,
    flat_four_required_white_rgb,
    recolor_level,
    strong_cel_required_physical_rgb,
    strong_cel_required_warm_rgb,
    write_vertex_color_obj,
)
from spectrum_mapper.filament_recommender import recommend_basic_filaments
from spectrum_mapper.gui import _merge_required_physical_rgb
from spectrum_mapper.illustration_filter import (
    ILLUSTRATION_LIGHTS,
    IllustrationFilterError,
    _crease_aware_face_normals,
    _srgb_to_linear,
    _strong_cel_rgb,
    _wrapped_light_with_range,
    apply_illustration_filter,
    apply_illustration_filter_faces,
    apply_illustration_filter_faces_with_bands,
    strong_cel_dark_warm_mask,
    strong_cel_face_light_geometry,
)
from spectrum_mapper.models import (
    AppSettings,
    COLOR_MODE_FLAT_FOUR,
    MeshLevel,
    PaletteSettings,
    ToneSettings,
)
from spectrum_mapper.mixer import palette_mix_specs


def _cube() -> tuple[np.ndarray, np.ndarray]:
    vertices = np.asarray(
        (
            (-1.0, -1.0, -1.0),
            (1.0, -1.0, -1.0),
            (1.0, 1.0, -1.0),
            (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0),
            (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
            (-1.0, 1.0, 1.0),
        ),
        dtype=np.float64,
    )
    faces = np.asarray(
        (
            (0, 2, 1), (0, 3, 2),
            (4, 5, 6), (4, 6, 7),
            (0, 1, 5), (0, 5, 4),
            (1, 2, 6), (1, 6, 5),
            (2, 3, 7), (2, 7, 6),
            (3, 0, 4), (3, 4, 7),
        ),
        dtype=np.int32,
    )
    return vertices, faces


class IllustrationFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vertices, self.faces = _cube()
        self.colors = np.tile(
            np.asarray((0.72, 0.34, 0.18), dtype=np.float64),
            (len(self.vertices), 1),
        )

    def test_off_is_an_exact_non_aliasing_copy(self) -> None:
        result = apply_illustration_filter(
            self.vertices,
            self.faces,
            self.colors,
            mode="off",
            strength=0.78,
            bands=4,
            light="front_left",
        )
        np.testing.assert_array_equal(result, self.colors)
        self.assertFalse(np.shares_memory(result, self.colors))

    def test_cel_preserves_colour_and_responds_to_light_direction(self) -> None:
        left = apply_illustration_filter(
            self.vertices,
            self.faces,
            self.colors,
            mode="cel",
            strength=1.0,
            bands=4,
            light="front_left",
        )
        right = apply_illustration_filter(
            self.vertices,
            self.faces,
            self.colors,
            mode="cel",
            strength=1.0,
            bands=4,
            light="front_right",
        )
        self.assertEqual(left.shape, self.colors.shape)
        self.assertTrue(np.isfinite(left).all())
        self.assertTrue(np.logical_and(left >= 0.0, left <= 1.0).all())
        self.assertFalse(np.array_equal(left, right))
        # Every non-black result keeps the source channel order (red > green > blue).
        self.assertTrue(np.all(left[:, 0] >= left[:, 1]))
        self.assertTrue(np.all(left[:, 1] >= left[:, 2]))

    def test_all_nine_front_view_light_positions_are_supported(self) -> None:
        self.assertEqual(
            ILLUSTRATION_LIGHTS,
            (
                "front_left",
                "top",
                "front_right",
                "left",
                "front",
                "right",
                "bottom_left",
                "bottom",
                "bottom_right",
            ),
        )
        results = {}
        for light in ILLUSTRATION_LIGHTS:
            tone = ToneSettings(
                illustration_mode="cel_strong",
                illustration_strength=0.78,
                illustration_bands=4,
                illustration_light=light,
            )
            self.assertEqual(tone.illustration_light, light)
            results[light] = apply_illustration_filter(
                self.vertices,
                self.faces,
                self.colors,
                mode=tone.illustration_mode,
                strength=tone.illustration_strength,
                bands=tone.illustration_bands,
                light=tone.illustration_light,
            )
            self.assertTrue(np.isfinite(results[light]).all())
        self.assertFalse(np.array_equal(results["top"], results["bottom"]))
        self.assertFalse(
            np.array_equal(results["bottom_left"], results["bottom_right"])
        )

    def test_high_contrast_cel_creates_print_visible_dark_highlights(self) -> None:
        face_colors = np.tile(
            np.asarray((0.04, 0.045, 0.055), dtype=np.float64),
            (len(self.faces), 1),
        )
        result = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=0.78,
            bands=4,
            light="front_left",
        )
        # Faces 4/5 are the front (-Y) plane and 8/9 are the back (+Y).
        # The lit garment must reach a printable mid/light grey rather than
        # remaining an imperceptible near-black multiplier.
        self.assertGreater(float(result[4:6].mean()), 0.68)
        self.assertLess(float(result[8:10].mean()), 0.10)
        self.assertGreater(
            float(result[4:6].mean() - result[8:10].mean()), 0.48
        )

    def test_new_light_defaults_are_pixel_identical_to_legacy_curve(self) -> None:
        diffuse = np.linspace(-1.0, 1.0, 101, dtype=np.float64)
        np.testing.assert_allclose(
            _wrapped_light_with_range(diffuse, 0.4),
            np.clip((diffuse + 0.28) / 1.28, 0.0, 1.0),
            rtol=0.0,
            atol=1.0e-15,
        )
        face_colors = np.tile(
            np.asarray((0.04, 0.045, 0.055), dtype=np.float64),
            (len(self.faces), 1),
        )
        legacy = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=0.78,
            bands=4,
            light="front",
        )
        explicit = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=0.78,
            bands=4,
            light="front",
            light_intensity=1.0,
            light_range=0.4,
        )
        np.testing.assert_array_equal(explicit, legacy)

    def test_detail_gate_defaults_to_exact_legacy_strong_cel_output(self) -> None:
        face_colors = np.tile(
            np.asarray((0.04, 0.045, 0.055), dtype=np.float64),
            (len(self.faces), 1),
        )
        legacy = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=0.78,
            bands=4,
            light="front_left",
        )
        explicit_off = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=0.78,
            bands=4,
            light="front_left",
            detail_strength=0.0,
        )
        np.testing.assert_array_equal(explicit_off, legacy)

    def test_detail_gate_restores_shallow_fold_normals_only(self) -> None:
        angles = np.radians(np.asarray((2.0, 12.0, 30.0)))
        vertices: list[tuple[float, float, float]] = []
        faces: list[tuple[int, int, int]] = []
        for face_id, angle in enumerate(angles):
            start = len(vertices)
            offset = 3.0 * face_id
            vertices.extend(
                (
                    (offset, 0.0, 0.0),
                    (offset + 1.0, 0.0, 0.0),
                    (offset, float(np.cos(angle)), float(np.sin(angle))),
                )
            )
            faces.append((start, start + 1, start + 2))
        geometry = np.asarray(vertices, dtype=np.float64)
        triangles = np.asarray(faces, dtype=np.int32)
        smooth = np.tile((0.0, 0.0, 1.0), (len(geometry), 1))

        legacy = _crease_aware_face_normals(
            geometry, triangles, smooth, detail_strength=0.0
        )
        enhanced = _crease_aware_face_normals(
            geometry, triangles, smooth, detail_strength=1.0
        )
        np.testing.assert_allclose(
            legacy[:2], np.tile((0.0, 0.0, 1.0), (2, 1)), atol=1e-15
        )
        # A 2-degree mismatch remains tessellation noise; a 12-degree wrinkle
        # regains part of its independent direction; a 30-degree crease was
        # already protected by the legacy path and is unchanged.
        np.testing.assert_allclose(enhanced[0], legacy[0], atol=1e-3)
        self.assertGreater(abs(float(enhanced[1, 1])), 0.02)
        self.assertLess(abs(float(enhanced[1, 1])), abs(float(np.sin(angles[1]))))
        np.testing.assert_allclose(enhanced[2], legacy[2], atol=1e-15)

    def test_detail_gate_darkens_lower_bands_without_raising_peak(self) -> None:
        source = np.tile((0.04, 0.04, 0.04), (4, 1)).astype(np.float64)
        graphic_light = np.asarray((0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0))
        legacy = _strong_cel_rgb(
            source,
            _srgb_to_linear(source),
            graphic_light,
            detail_strength=0.0,
        )
        enhanced = _strong_cel_rgb(
            source,
            _srgb_to_linear(source),
            graphic_light,
            detail_strength=1.0,
        )
        self.assertLess(float(enhanced[0].mean()), float(legacy[0].mean()))
        self.assertLess(float(enhanced[1].mean()), float(legacy[1].mean()))
        self.assertLess(float(enhanced[2].mean()), float(legacy[2].mean()))
        np.testing.assert_array_equal(enhanced[3], legacy[3])

    def test_detail_gate_keeps_dark_skin_warm_and_chromatic(self) -> None:
        skin = np.tile((0.23, 0.13, 0.075), (2, 1)).astype(np.float64)
        graphic_light = np.asarray((0.0, 1.0 / 3.0))
        legacy = _strong_cel_rgb(
            skin,
            _srgb_to_linear(skin),
            graphic_light,
            detail_strength=0.0,
        )
        enhanced = _strong_cel_rgb(
            skin,
            _srgb_to_linear(skin),
            graphic_light,
            detail_strength=1.0,
        )
        self.assertTrue(np.all(enhanced[:, 0] > enhanced[:, 1]))
        self.assertTrue(np.all(enhanced[:, 1] > enhanced[:, 2]))
        legacy_saturation = np.ptp(legacy, axis=1) / np.max(legacy, axis=1)
        enhanced_saturation = np.ptp(enhanced, axis=1) / np.max(enhanced, axis=1)
        self.assertTrue(np.all(enhanced_saturation >= legacy_saturation))

    def test_light_range_is_stable_across_a_full_normal_distribution(self) -> None:
        # Cosines from a back-facing normal through grazing to front-facing
        # stand in for an arbitrary closed character rather than one model.
        diffuse = np.linspace(-1.0, 1.0, 2001, dtype=np.float64)
        previous = None
        for light_range in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            current = _wrapped_light_with_range(diffuse, light_range)
            self.assertTrue(np.isfinite(current).all())
            self.assertTrue(np.all(np.diff(current) >= -1.0e-15))
            self.assertAlmostEqual(float(current[-1]), 1.0)
            if previous is not None:
                self.assertTrue(np.all(current >= previous - 1.0e-15))
            previous = current
        self.assertAlmostEqual(float(previous[0]), 0.16)

    def test_light_strength_and_range_control_different_properties(self) -> None:
        face_colors = np.tile(
            np.asarray((0.04, 0.045, 0.055), dtype=np.float64),
            (len(self.faces), 1),
        )
        default_rgb, default_bands = apply_illustration_filter_faces_with_bands(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=1.0,
            bands=4,
            light="front",
            light_intensity=1.0,
            light_range=0.4,
        )
        softer_rgb, softer_bands = apply_illustration_filter_faces_with_bands(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=1.0,
            bands=4,
            light="front",
            light_intensity=0.55,
            light_range=0.4,
        )
        wider_rgb, wider_bands = apply_illustration_filter_faces_with_bands(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=1.0,
            bands=4,
            light="front",
            light_intensity=0.55,
            light_range=1.0,
        )
        # Strength changes band energy, not their geometric placement.
        np.testing.assert_array_equal(softer_bands, default_bands)
        self.assertLess(
            float(softer_rgb[4:6].mean()),
            float(default_rgb[4:6].mean()) - 0.20,
        )
        # Range adds wrap/rear fill without re-brightening the front plane.
        self.assertGreater(
            float(wider_rgb[8:10].mean()),
            float(softer_rgb[8:10].mean()) + 0.04,
        )
        np.testing.assert_allclose(
            wider_rgb[4:6], softer_rgb[4:6], atol=1.0e-12
        )
        self.assertTrue(np.any(wider_bands[8:10] > softer_bands[8:10]))

    def test_captured_strong_cel_geometry_matches_standalone_geometry(self) -> None:
        face_colors = np.tile(
            np.asarray((0.04, 0.045, 0.055), dtype=np.float64),
            (len(self.faces), 1),
        )
        _styled, _bands, scores, normals = (
            apply_illustration_filter_faces_with_bands(
                self.vertices,
                self.faces,
                face_colors,
                mode="cel_strong",
                strength=0.78,
                bands=4,
                light="front_left",
                light_intensity=1.0,
                light_range=0.4,
                detail_strength=0.5,
                _capture_strong_cel_geometry=True,
            )
        )
        expected_scores, expected_normals = strong_cel_face_light_geometry(
            self.vertices,
            self.faces,
            light="front_left",
            light_range=0.4,
            detail_strength=0.5,
        )
        np.testing.assert_array_equal(scores, expected_scores)
        np.testing.assert_array_equal(normals, expected_normals)

    def test_balanced_light_reduces_front_clipping_and_reveals_the_rear(self) -> None:
        face_colors = np.tile(
            np.asarray((0.04, 0.045, 0.055), dtype=np.float64),
            (len(self.faces), 1),
        )
        balanced = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=1.0,
            bands=4,
            light="front",
            light_intensity=0.65,
            light_range=0.65,
        )
        front = float(balanced[4:6].mean())
        rear = float(balanced[8:10].mean())
        self.assertGreater(front, 0.45)
        self.assertLess(front, 0.70)
        self.assertGreater(rear, 0.10)
        self.assertLess(rear, 0.25)
        self.assertGreater(front - rear, 0.30)

    def test_balanced_light_controls_change_print_palette_assignment(self) -> None:
        dark = np.asarray((0.04, 0.045, 0.055), dtype=np.float64)
        triangle = self.vertices[self.faces]
        level = MeshLevel(
            vertices_unit=self.vertices,
            faces=self.faces,
            vertex_colors=np.tile(dark, (len(self.vertices), 1)),
            areas_unit=0.5
            * np.linalg.norm(
                np.cross(
                    triangle[:, 1] - triangle[:, 0],
                    triangle[:, 2] - triangle[:, 0],
                ),
                axis=1,
            ),
            neighbors=None,
        )
        palette = PaletteSettings(
            physical_hex=["#111111", "#FFFFFF", "#808080", "#404040"]
        )

        def recolor(intensity: float, light_range: float):
            return recolor_level(
                level,
                100.0,
                ToneSettings(
                    white_point=1.0,
                    smoothing=False,
                    illustration_mode="cel_strong",
                    illustration_strength=1.0,
                    illustration_bands=4,
                    illustration_light="front",
                    illustration_light_intensity=intensity,
                    illustration_light_range=light_range,
                ),
                palette,
            )

        legacy = recolor(1.0, 0.4)
        balanced = recolor(0.65, 0.65)
        self.assertLess(
            float(balanced.target_face_rgb[4:6].mean()),
            float(legacy.target_face_rgb[4:6].mean()) - 0.10,
        )
        self.assertGreater(
            float(balanced.target_face_rgb[8:10].mean()),
            float(legacy.target_face_rgb[8:10].mean()) + 0.05,
        )

    def test_high_contrast_cel_retains_dark_colour_tint(self) -> None:
        face_colors = np.tile(
            np.asarray((0.05, 0.08, 0.20), dtype=np.float64),
            (len(self.faces), 1),
        )
        result = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=1.0,
            bands=4,
            light="front_left",
        )
        front = result[4]
        self.assertGreater(float(front[2]), float(front[1]))
        self.assertGreater(float(front[1]), float(front[0]))
        self.assertGreater(float(front[2] - front[0]), 0.05)

    def test_high_contrast_cel_does_not_bleach_bright_skin(self) -> None:
        skin = np.asarray((0.72, 0.50, 0.38), dtype=np.float64)
        face_colors = np.tile(skin, (len(self.faces), 1))
        result = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=0.78,
            bands=4,
            light="front_left",
        )
        front = result[4]
        self.assertGreater(float(front[0]), float(front[1]))
        self.assertGreater(float(front[1]), float(front[2]))
        self.assertGreater(float(np.ptp(front)), 0.25)
        self.assertLess(float(np.max(np.abs(front - skin))), 0.08)

    def test_high_contrast_cel_keeps_low_chroma_dark_skin_out_of_gray_slots(
        self,
    ) -> None:
        # Low-light AI textures can encode deep skin with only a small absolute
        # RGB span.  It is still directionally warm and must not be classified
        # as neutral black cloth merely because every channel is dark.
        skin = np.asarray((0x3B, 0x2B, 0x28), dtype=np.float64) / 255.0
        triangle = self.vertices[self.faces]
        level = MeshLevel(
            vertices_unit=self.vertices,
            faces=self.faces,
            vertex_colors=np.tile(skin, (len(self.vertices), 1)),
            areas_unit=0.5
            * np.linalg.norm(
                np.cross(
                    triangle[:, 1] - triangle[:, 0],
                    triangle[:, 2] - triangle[:, 0],
                ),
                axis=1,
            ),
            neighbors=None,
        )
        tone = ToneSettings(
            white_point=1.0,
            smoothing=False,
            illustration_mode="cel_strong",
            illustration_strength=0.78,
            illustration_bands=4,
            illustration_light="front_left",
        )
        result = recolor_level(
            level,
            100.0,
            tone,
            PaletteSettings(
                color_mode=COLOR_MODE_FLAT_FOUR,
                physical_hex=["#111111", "#7F8388", "#7A4A32", "#F5F5F5"],
            ),
        )

        states = set(int(value) for value in result.palette_indices)
        self.assertIn(2, states)
        self.assertNotIn(1, states)
        self.assertNotIn(3, states)
        luma = result.tone_face_rgb @ np.asarray((0.2126, 0.7152, 0.0722))
        highlight = result.tone_face_rgb[int(np.argmax(luma))]
        self.assertGreater(float(luma.max()), 0.55)
        self.assertGreater(float(highlight[0]), float(highlight[1]))
        self.assertGreater(float(highlight[1]), float(highlight[2]))
        required = strong_cel_required_physical_rgb(
            np.tile(skin, (len(self.faces), 1)),
            result.tone_face_rgb,
            level.areas_unit,
            tone,
            COLOR_MODE_FLAT_FOUR,
        )
        self.assertIsNone(required)
        warm_required = strong_cel_required_warm_rgb(
            np.tile(skin, (len(self.faces), 1)),
            level.areas_unit,
            tone,
        )
        self.assertIsNotNone(warm_required)
        self.assertAlmostEqual(float(np.max(warm_required)), 0.70, places=6)
        self.assertTrue(bool(np.all(strong_cel_dark_warm_mask(skin[None, :]))))
        warm_black = np.asarray((0x20, 0x1B, 0x18), dtype=np.float64) / 255.0
        self.assertFalse(
            bool(np.any(strong_cel_dark_warm_mask(warm_black[None, :])))
        )
        warm_black_boundary = (
            np.asarray((0x25, 0x1B, 0x18), dtype=np.float64) / 255.0
        )
        protected_dark_skin = (
            np.asarray((0x2B, 0x20, 0x1E), dtype=np.float64) / 255.0
        )
        self.assertFalse(
            bool(
                np.any(
                    strong_cel_dark_warm_mask(warm_black_boundary[None, :])
                )
            )
        )
        self.assertTrue(
            bool(
                np.all(
                    strong_cel_dark_warm_mask(protected_dark_skin[None, :])
                )
            )
        )

    def test_high_contrast_cel_flat_auto_keeps_lit_skin_with_black_cloth(
        self,
    ) -> None:
        # A realistic dark-character palette combines a large neutral-black
        # garment with a much smaller deep-skin region.  Strong Cel reserves
        # three neutral print bands for the garment, so the remaining Flat
        # Four slot must preserve a skin base rather than selecting a
        # redundant neutral that happens to fit the monitor.
        black = np.asarray((0x12, 0x12, 0x12), dtype=np.float64) / 255.0
        skin = np.asarray((0x3B, 0x2B, 0x28), dtype=np.float64) / 255.0
        black_faces = np.tile(black, (len(self.faces), 1))
        skin_faces = np.tile(skin, (len(self.faces), 1))
        tone = ToneSettings(
            white_point=1.0,
            smoothing=False,
            illustration_mode="cel_strong",
            illustration_strength=0.78,
            illustration_bands=4,
            illustration_light="front_left",
        )
        source = np.vstack((black_faces, skin_faces))
        styled = np.vstack(
            (
                apply_tone_faces(
                    black_faces,
                    tone,
                    vertices_unit=self.vertices,
                    faces=self.faces,
                ),
                apply_tone_faces(
                    skin_faces,
                    tone,
                    vertices_unit=self.vertices,
                    faces=self.faces,
                ),
            )
        )
        areas = np.concatenate(
            (
                np.full(len(self.faces), 0.80 / len(self.faces)),
                np.full(len(self.faces), 0.20 / len(self.faces)),
            )
        )

        required = strong_cel_required_physical_rgb(
            source,
            styled,
            areas,
            tone,
            COLOR_MODE_FLAT_FOUR,
        )
        required = _merge_required_physical_rgb(
            required,
            strong_cel_required_warm_rgb(source, areas, tone),
        )
        recommendation = recommend_basic_filaments(
            styled,
            areas,
            include_mixed_states=False,
            required_physical_rgb=required,
        )
        selected_ids = {candidate.id for candidate in recommendation.candidates}
        self.assertEqual(
            selected_ids,
            {
                "neutral_black",
                "neutral_gray",
                "neutral_white",
                "skin_medium",
            },
        )

    def test_high_contrast_cel_keeps_saturated_dark_flat_colors_chromatic(
        self,
    ) -> None:
        triangle = self.vertices[self.faces]
        areas = 0.5 * np.linalg.norm(
            np.cross(
                triangle[:, 1] - triangle[:, 0],
                triangle[:, 2] - triangle[:, 0],
            ),
            axis=1,
        )
        tone = ToneSettings(
            white_point=1.0,
            smoothing=False,
            illustration_mode="cel_strong",
            illustration_strength=0.78,
            illustration_bands=4,
            illustration_light="front_left",
        )
        for source_hex, physical_hex in (
            ("#0D1730", "#294FA3"),
            ("#3A0810", "#A83245"),
            ("#0B2B14", "#287A3C"),
            ("#241336", "#7545A8"),
        ):
            with self.subTest(source=source_hex):
                source = np.asarray(
                    [int(source_hex[index : index + 2], 16) for index in (1, 3, 5)],
                    dtype=np.float64,
                ) / 255.0
                level = MeshLevel(
                    vertices_unit=self.vertices,
                    faces=self.faces,
                    vertex_colors=np.tile(source, (len(self.vertices), 1)),
                    areas_unit=areas,
                    neighbors=None,
                )
                result = recolor_level(
                    level,
                    100.0,
                    tone,
                    PaletteSettings(
                        color_mode=COLOR_MODE_FLAT_FOUR,
                        physical_hex=[
                            "#111111",
                            "#7F8388",
                            physical_hex,
                            "#F5F5F5",
                        ],
                    ),
                )

                np.testing.assert_array_equal(
                    result.palette_indices,
                    np.full(len(self.faces), 2, dtype=np.int8),
                )
                self.assertIsNone(
                    strong_cel_required_physical_rgb(
                        np.tile(source, (len(self.faces), 1)),
                        result.tone_face_rgb,
                        areas,
                        tone,
                        COLOR_MODE_FLAT_FOUR,
                    )
                )

    def test_high_contrast_cel_strength_zero_is_exact_copy(self) -> None:
        result = apply_illustration_filter(
            self.vertices,
            self.faces,
            self.colors,
            mode="cel_strong",
            strength=0.0,
            bands=4,
            light="front_left",
        )
        np.testing.assert_array_equal(result, self.colors)

    def test_high_contrast_cel_keeps_requested_band_limit(self) -> None:
        face_colors = np.tile(
            np.asarray((0.04, 0.045, 0.055), dtype=np.float64),
            (len(self.faces), 1),
        )
        result = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel_strong",
            strength=1.0,
            bands=4,
            light="front_left",
        )
        self.assertLessEqual(len(np.unique(result, axis=0)), 4)

    def test_high_contrast_cel_full_spectrum_prints_one_state_per_light_band(
        self,
    ) -> None:
        # Generated black cloth is commonly a low-chroma navy rather than
        # equal-channel RGB.  Source-texture noise inside one geometric light
        # band must not fan out across many of the 32 mixed print states.
        split_vertices = self.vertices[self.faces].reshape((-1, 3))
        split_faces = np.arange(len(split_vertices), dtype=np.int32).reshape(
            (-1, 3)
        )
        source_levels = np.linspace(0.03, 0.27, len(split_faces))
        face_colors = np.clip(
            source_levels[:, None]
            + np.asarray((0.0, 0.005, 0.015), dtype=np.float64),
            0.0,
            1.0,
        )
        vertex_colors = np.repeat(face_colors, 3, axis=0)
        tone = ToneSettings(
            white_point=1.0,
            smoothing=False,
            illustration_mode="cel_strong",
            illustration_strength=0.78,
            illustration_bands=4,
            illustration_light="front_left",
        )
        _styled, band_ids = apply_illustration_filter_faces_with_bands(
            split_vertices,
            split_faces,
            face_colors,
            mode=tone.illustration_mode,
            strength=tone.illustration_strength,
            bands=tone.illustration_bands,
            light=tone.illustration_light,
        )
        self.assertIsNotNone(band_ids)
        assert band_ids is not None
        triangle = split_vertices[split_faces]
        level = MeshLevel(
            vertices_unit=split_vertices,
            faces=split_faces,
            vertex_colors=vertex_colors,
            areas_unit=0.5
            * np.linalg.norm(
                np.cross(
                    triangle[:, 1] - triangle[:, 0],
                    triangle[:, 2] - triangle[:, 0],
                ),
                axis=1,
            ),
            neighbors=None,
        )
        active_bands = np.unique(band_ids)
        for palette_state_count in (16, 24, 32):
            with self.subTest(palette_state_count=palette_state_count):
                result = recolor_level(
                    level,
                    100.0,
                    tone,
                    PaletteSettings(
                        palette_state_count=palette_state_count,
                        physical_hex=[
                            "#111111",
                            "#F5F5F5",
                            "#B87354",
                            "#5C738F",
                        ],
                    ),
                )
                for band in active_bands:
                    self.assertEqual(
                        len(
                            np.unique(
                                result.palette_indices[band_ids == band]
                            )
                        ),
                        1,
                    )
                self.assertEqual(
                    len(np.unique(result.palette_indices)),
                    len(active_bands),
                )
                for state in np.unique(result.palette_indices):
                    state = int(state)
                    if state < 4:
                        self.assertIn(state, (0, 1, 3))
                    else:
                        self.assertTrue(
                            3 in palette_mix_specs()[state - 4][:2]
                        )
                self.assertTrue(
                    any(
                        int(state) == 3
                        or (
                            int(state) >= 4
                            and 3 in palette_mix_specs()[int(state) - 4][:2]
                        )
                        for state in np.unique(result.palette_indices)
                    )
                )

    def test_high_contrast_cel_flat_prints_one_state_per_light_band(self) -> None:
        split_vertices = self.vertices[self.faces].reshape((-1, 3))
        split_faces = np.arange(len(split_vertices), dtype=np.int32).reshape(
            (-1, 3)
        )
        source_levels = np.linspace(0.01, 0.30, len(split_faces))
        face_colors = np.repeat(source_levels[:, None], 3, axis=1)
        tone = ToneSettings(
            white_point=1.0,
            smoothing=False,
            illustration_mode="cel_strong",
            illustration_strength=0.78,
            illustration_bands=4,
            illustration_light="front_left",
        )
        _styled, band_ids = apply_illustration_filter_faces_with_bands(
            split_vertices,
            split_faces,
            face_colors,
            mode=tone.illustration_mode,
            strength=tone.illustration_strength,
            bands=tone.illustration_bands,
            light=tone.illustration_light,
        )
        self.assertIsNotNone(band_ids)
        assert band_ids is not None
        triangle = split_vertices[split_faces]
        level = MeshLevel(
            vertices_unit=split_vertices,
            faces=split_faces,
            vertex_colors=np.repeat(face_colors, 3, axis=0),
            areas_unit=0.5
            * np.linalg.norm(
                np.cross(
                    triangle[:, 1] - triangle[:, 0],
                    triangle[:, 2] - triangle[:, 0],
                ),
                axis=1,
            ),
            neighbors=None,
        )
        result = recolor_level(
            level,
            100.0,
            tone,
            PaletteSettings(
                color_mode=COLOR_MODE_FLAT_FOUR,
                physical_hex=["#111111", "#555555", "#AAAAAA", "#F3F3F3"],
            ),
        )
        for band in np.unique(band_ids):
            self.assertEqual(
                len(np.unique(result.palette_indices[band_ids == band])),
                1,
            )

    def test_high_contrast_cel_survives_flat_four_palette_mapping(self) -> None:
        dark = np.tile(
            np.asarray((0.04, 0.045, 0.055), dtype=np.float64),
            (len(self.vertices), 1),
        )
        triangle = self.vertices[self.faces]
        level = MeshLevel(
            vertices_unit=self.vertices,
            faces=self.faces,
            vertex_colors=dark,
            areas_unit=0.5
            * np.linalg.norm(
                np.cross(
                    triangle[:, 1] - triangle[:, 0],
                    triangle[:, 2] - triangle[:, 0],
                ),
                axis=1,
            ),
            neighbors=None,
        )
        result = recolor_level(
            level,
            100.0,
            ToneSettings(
                white_point=1.0,
                smoothing=False,
                illustration_mode="cel_strong",
                illustration_strength=0.78,
                illustration_bands=4,
                illustration_light="front_left",
            ),
            PaletteSettings(
                color_mode=COLOR_MODE_FLAT_FOUR,
                physical_hex=["#111111", "#555555", "#AAAAAA", "#F3F3F3"],
            ),
        )
        self.assertTrue(np.all(result.palette_indices < 4))
        self.assertGreaterEqual(int(result.palette_indices[4]), 2)
        self.assertEqual(int(result.palette_indices[8]), 0)
        self.assertGreaterEqual(len(np.unique(result.palette_indices)), 3)
        self.assertGreaterEqual(
            int(np.count_nonzero(result.palette_indices == 0)),
            len(result.palette_indices) // 2,
        )
        self.assertTrue(result.tone_face_rgb_flat)

    def test_high_contrast_cel_flat_requires_three_neutral_anchors(self) -> None:
        source = np.asarray(
            (
                (0.06, 0.06, 0.06),
                (0.06, 0.06, 0.06),
                (0.06, 0.06, 0.06),
                (0.06, 0.06, 0.06),
                (0.79, 0.55, 0.39),
            ),
            dtype=np.float64,
        )
        styled = np.asarray(
            (
                (0.05, 0.05, 0.05),
                (0.20, 0.20, 0.20),
                (0.55, 0.55, 0.55),
                (0.92, 0.92, 0.92),
                (0.79, 0.55, 0.39),
            ),
            dtype=np.float64,
        )
        areas = np.asarray((0.46, 0.20, 0.12, 0.10, 0.12))

        required = strong_cel_required_physical_rgb(
            source,
            styled,
            areas,
            ToneSettings(illustration_mode="cel_strong"),
            COLOR_MODE_FLAT_FOUR,
        )

        self.assertIsNotNone(required)
        self.assertEqual(required.shape, (3, 3))
        np.testing.assert_allclose(required[0], (0.055, 0.055, 0.055))
        np.testing.assert_allclose(required[1], (0.50, 0.50, 0.50))
        np.testing.assert_allclose(required[2], (0.94, 0.94, 0.94))

    def test_high_contrast_cel_flat_reuses_existing_white_anchor(self) -> None:
        source = np.asarray(
            (
                (0.06, 0.06, 0.06),
                (0.06, 0.06, 0.06),
                (0.06, 0.06, 0.06),
                (0.06, 0.06, 0.06),
                (0.79, 0.55, 0.39),
                (0.96, 0.96, 0.96),
            ),
            dtype=np.float64,
        )
        styled = np.asarray(
            (
                (0.05, 0.05, 0.05),
                (0.20, 0.20, 0.20),
                (0.55, 0.55, 0.55),
                (0.92, 0.92, 0.92),
                (0.79, 0.55, 0.39),
                (0.96, 0.96, 0.96),
            ),
            dtype=np.float64,
        )
        areas = np.asarray((0.45, 0.20, 0.10, 0.08, 0.169, 0.001))
        preserved_white = flat_four_required_white_rgb(styled, areas)
        self.assertIsNotNone(preserved_white)

        # The strong-cel API reserves the garment's black/mid/light anchors.
        # The GUI merge must reuse that light slot for eye/detail white instead
        # of consuming a fourth near-identical neutral physical colour.
        required = strong_cel_required_physical_rgb(
            source,
            styled,
            areas,
            ToneSettings(illustration_mode="cel_strong"),
            COLOR_MODE_FLAT_FOUR,
        )

        self.assertIsNotNone(required)
        self.assertEqual(required.shape, (3, 3))
        merged = _merge_required_physical_rgb(required, preserved_white)
        self.assertEqual(merged.shape, (3, 3))
        light_neutral = (
            (np.min(merged, axis=1) >= 0.75)
            & (np.ptp(merged, axis=1) <= 0.12)
        )
        self.assertEqual(int(np.count_nonzero(light_neutral)), 1)
        self.assertLess(
            float(
                np.max(
                    np.abs(
                        merged[np.flatnonzero(light_neutral)[0]]
                        - preserved_white
                    )
                )
            ),
            0.03,
        )

        recommendation = recommend_basic_filaments(
            styled,
            areas,
            include_mixed_states=False,
            required_physical_rgb=merged,
        )
        selected_ids = {candidate.id for candidate in recommendation.candidates}
        self.assertEqual(
            selected_ids,
            {
                "neutral_black",
                "neutral_gray",
                "neutral_white",
                "skin_medium",
            },
        )
        self.assertNotIn("neutral_silver", selected_ids)

    def test_noir_is_monochrome_and_has_no_more_than_requested_bands(self) -> None:
        result = apply_illustration_filter(
            self.vertices,
            self.faces,
            self.colors,
            mode="noir",
            strength=0.85,
            bands=3,
            light="front",
        )
        np.testing.assert_allclose(result[:, 0], result[:, 1], atol=0.0)
        np.testing.assert_allclose(result[:, 1], result[:, 2], atol=0.0)
        self.assertLessEqual(len(np.unique(result[:, 0])), 3)

    def test_noir_strength_zero_is_an_exact_no_effect_copy(self) -> None:
        result = apply_illustration_filter(
            self.vertices,
            self.faces,
            self.colors,
            mode="noir",
            strength=0.0,
            bands=6,
            light="front_left",
        )
        np.testing.assert_array_equal(result, self.colors)

    def test_printable_face_bands_do_not_depend_on_shared_vertices(self) -> None:
        face_colors = self.colors[self.faces].mean(axis=1)
        shared = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="noir",
            strength=1.0,
            bands=2,
            light="front",
        )
        split_vertices = self.vertices[self.faces].reshape((-1, 3))
        split_faces = np.arange(len(split_vertices), dtype=np.int32).reshape((-1, 3))
        split = apply_illustration_filter_faces(
            split_vertices,
            split_faces,
            face_colors,
            mode="noir",
            strength=1.0,
            bands=2,
            light="front",
        )
        np.testing.assert_allclose(shared, split, atol=0.0)
        self.assertLessEqual(len(np.unique(shared[:, 0])), 2)

    def test_cel_outline_does_not_create_more_than_requested_bands(self) -> None:
        face_colors = np.tile(self.colors[0], (len(self.faces), 1))
        result = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel",
            strength=1.0,
            bands=2,
            light="front_left",
        )
        self.assertLessEqual(len(np.unique(result, axis=0)), 2)

    def test_face_filter_is_invariant_to_isolated_winding_reversal(self) -> None:
        face_colors = self.colors[self.faces].mean(axis=1)
        normal = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel",
            strength=1.0,
            bands=4,
            light="front_left",
        )
        reversed_faces = self.faces.copy()
        reversed_faces[0] = reversed_faces[0, ::-1]
        reversed_result = apply_illustration_filter_faces(
            self.vertices,
            reversed_faces,
            face_colors,
            mode="cel",
            strength=1.0,
            bands=4,
            light="front_left",
        )
        np.testing.assert_allclose(normal, reversed_result, atol=0.0)

    def test_opposite_closed_surfaces_keep_different_lighting(self) -> None:
        face_colors = self.colors[self.faces].mean(axis=1)
        result = apply_illustration_filter_faces(
            self.vertices,
            self.faces,
            face_colors,
            mode="cel",
            strength=1.0,
            bands=4,
            light="front_left",
        )
        self.assertFalse(np.array_equal(result[4], result[8]))

    def test_invalid_controls_fail_before_producing_colours(self) -> None:
        common = dict(
            vertices=self.vertices,
            faces=self.faces,
            colors=self.colors,
            mode="cel",
            strength=0.5,
            bands=4,
            light="front_left",
        )
        for field, value in (
            ("mode", "watercolor"),
            ("strength", 1.01),
            ("bands", 7),
            ("light", "rear"),
            ("light_intensity", 1.51),
            ("light_range", float("nan")),
            ("detail_strength", 1.01),
        ):
            request = dict(common)
            request[field] = value
            with self.subTest(field=field), self.assertRaises(
                IllustrationFilterError
            ):
                apply_illustration_filter(**request)

    def test_apply_tone_requires_geometry_only_when_filter_is_active(self) -> None:
        ordinary = apply_tone(
            self.colors,
            ToneSettings(white_point=1.0, smoothing=False),
        )
        self.assertEqual(ordinary.shape, self.colors.shape)
        active = ToneSettings(
            white_point=1.0,
            smoothing=False,
            illustration_mode="cel",
        )
        with self.assertRaisesRegex(EngineError, "頂点・面情報"):
            apply_tone(self.colors, active)
        styled = apply_tone(
            self.colors,
            active,
            vertices_unit=self.vertices,
            faces=self.faces,
        )
        self.assertFalse(np.array_equal(styled, ordinary))

    def test_settings_round_trip_preserves_experimental_style(self) -> None:
        settings = AppSettings(
            tone=ToneSettings(
                illustration_mode="noir",
                illustration_strength=0.91,
                illustration_bands=3,
                illustration_light="front_right",
                illustration_light_intensity=0.65,
                illustration_light_range=0.75,
            )
        )
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertEqual(asdict(restored.tone), asdict(settings.tone))

    def test_settings_round_trip_preserves_high_contrast_cel(self) -> None:
        settings = AppSettings(
            tone=ToneSettings(
                illustration_mode="cel_strong",
                illustration_strength=0.86,
                illustration_bands=4,
                illustration_light="front_left",
                illustration_detail_strength=0.72,
                illustration_selective_highlight_fraction=0.08,
                illustration_contour_policy="outer_crease",
            )
        )
        self.assertEqual(
            settings.to_dict()["tone"]["illustration_contour_policy"],
            "outer_crease",
        )
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertEqual(asdict(restored.tone), asdict(settings.tone))

    def test_default_project_payload_stays_readable_by_older_builds(self) -> None:
        tone_payload = AppSettings().to_dict()["tone"]
        for key in (
            "illustration_mode",
            "illustration_strength",
            "illustration_bands",
            "illustration_light",
            "illustration_light_intensity",
            "illustration_light_range",
            "illustration_detail_strength",
            "illustration_selective_highlight_fraction",
            "illustration_contour_policy",
        ):
            self.assertNotIn(key, tone_payload)
        dormant_payload = AppSettings(
            tone=ToneSettings(
                illustration_mode="off",
                illustration_strength=0.2,
                illustration_bands=6,
                illustration_light="front_right",
                illustration_contour_policy="outer",
            )
        ).to_dict()["tone"]
        self.assertNotIn("illustration_mode", dormant_payload)
        self.assertNotIn("illustration_contour_policy", dormant_payload)
        active_payload = AppSettings(
            tone=ToneSettings(illustration_mode="cel")
        ).to_dict()["tone"]
        self.assertEqual(active_payload["illustration_mode"], "cel")
        self.assertNotIn("illustration_contour_policy", active_payload)

    def test_invalid_persisted_controls_fail_at_settings_boundary(self) -> None:
        for field, value in (
            ("illustration_mode", "watercolor"),
            ("illustration_strength", float("nan")),
            ("illustration_bands", 8),
            ("illustration_light", "rear"),
            ("illustration_light_intensity", 1.51),
            ("illustration_light_range", -0.01),
            ("illustration_detail_strength", 1.01),
            ("illustration_selective_highlight_fraction", 0.04),
            ("illustration_selective_highlight_fraction", 0.121),
            ("illustration_contour_policy", "all_edges"),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                ToneSettings(**{field: value})

    def test_authoritative_face_tone_keeps_requested_noir_bands(self) -> None:
        tone = ToneSettings(
            white_point=1.0,
            smoothing=False,
            illustration_mode="noir",
            illustration_strength=1.0,
            illustration_bands=2,
            illustration_light="front",
        )
        result = apply_tone_faces(
            self.colors,
            tone,
            vertices_unit=self.vertices,
            faces=self.faces,
        )
        self.assertLessEqual(len(np.unique(result[:, 0])), 2)
        np.testing.assert_allclose(result[:, 0], result[:, 1], atol=0.0)

    def test_recolor_pipeline_maps_the_filtered_monochrome_values(self) -> None:
        triangle = self.vertices[self.faces]
        areas = 0.5 * np.linalg.norm(
            np.cross(
                triangle[:, 1] - triangle[:, 0],
                triangle[:, 2] - triangle[:, 0],
            ),
            axis=1,
        )
        level = MeshLevel(
            vertices_unit=self.vertices,
            faces=self.faces,
            vertex_colors=self.colors,
            areas_unit=areas,
            neighbors=None,
        )
        result = recolor_level(
            level,
            100.0,
            ToneSettings(
                white_point=1.0,
                smoothing=False,
                illustration_mode="noir",
                illustration_strength=0.9,
                illustration_bands=3,
                illustration_light="front",
            ),
            PaletteSettings(),
        )
        self.assertIsNotNone(result.tone_face_rgb)
        self.assertTrue(result.tone_face_rgb_flat)
        np.testing.assert_allclose(
            result.tone_face_rgb[:, 0],
            result.tone_face_rgb[:, 1],
            atol=0.0,
        )
        self.assertEqual(result.palette_indices.shape, (len(self.faces),))
        self.assertTrue(np.isfinite(result.delta_e).all())

    def test_illustration_fallback_obj_splits_shared_vertices_by_face(self) -> None:
        level = MeshLevel(
            vertices_unit=self.vertices,
            faces=self.faces,
            vertex_colors=self.colors,
            areas_unit=np.ones(len(self.faces), dtype=np.float64),
            neighbors=None,
            face_part_ids=np.zeros(len(self.faces), dtype=np.int16),
            part_names=("whole",),
            part_keys=("whole",),
        )
        face_tone = np.linspace(
            0.05, 0.95, len(self.faces), dtype=np.float64
        )[:, None] * np.ones((1, 3), dtype=np.float64)
        result = SimpleNamespace(
            tone_vertex_rgb=self.colors,
            tone_face_rgb=face_tone,
            tone_face_rgb_flat=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "illustration.obj"
            write_vertex_color_obj(
                destination,
                SimpleNamespace(final=level),
                result,
                10.0,
            )
            lines = destination.read_text(encoding="ascii").splitlines()
        vertex_lines = [line for line in lines if line.startswith("v ")]
        face_lines = [line for line in lines if line.startswith("f ")]
        self.assertEqual(len(vertex_lines), 3 * len(self.faces))
        self.assertEqual(len(face_lines), len(self.faces))
        self.assertEqual(face_lines[0], "f 1 2 3")
        self.assertEqual(face_lines[-1], "f 34 35 36")
        first_colours = [line.split()[-3:] for line in vertex_lines[:3]]
        self.assertEqual(first_colours[0], first_colours[1])
        self.assertEqual(first_colours[1], first_colours[2])


if __name__ == "__main__":
    unittest.main()
