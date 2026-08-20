from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import MeshLevel
from spectrum_mapper.reference_parts import (
    extract_corner_foreground,
    match_reference_to_parts,
    render_front_part_ids,
)


def two_part_level() -> MeshLevel:
    return MeshLevel(
        vertices_unit=np.asarray(
            (
                (-1.0, 0.0, 0.0),
                (0.0, 0.0, 0.0),
                (-1.0, 0.0, 1.0),
                (1.0, 0.0, 0.0),
                (1.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        ),
        faces=np.asarray(((0, 1, 2), (1, 3, 4)), dtype=np.int32),
        vertex_colors=np.zeros((5, 3), dtype=np.float64),
        areas_unit=np.ones(2, dtype=np.float64),
        neighbors=None,
        face_part_ids=np.asarray((0, 1), dtype=np.int16),
        part_names=("left garment", "right garment"),
        part_keys=("part-left", "part-right"),
    )


def id_callback(id_map: np.ndarray):
    def render(_level, _result, **kwargs):
        if kwargs.get("shaded") is not False:
            raise AssertionError("part-id rendering must disable shading")
        if kwargs.get("mode") != "target":
            raise AssertionError("part-id rendering must use target face colours")
        return id_map.copy()

    return render


def white_image(height: int, width: int) -> np.ndarray:
    return np.full((height, width, 3), 255, dtype=np.uint8)


class ForegroundExtractionTests(unittest.TestCase):
    def test_four_corner_background_is_removed_without_losing_center(self) -> None:
        image = white_image(40, 50)
        image[10:30, 15:35] = (220, 25, 35)

        extraction = extract_corner_foreground(image)

        self.assertEqual(extraction.bbox, (15, 10, 35, 30))
        self.assertFalse(bool(extraction.mask[0, 0]))
        self.assertFalse(bool(extraction.mask[-1, -1]))
        self.assertTrue(bool(extraction.mask[20, 25]))
        self.assertEqual(int(np.count_nonzero(extraction.mask)), 400)
        self.assertEqual(extraction.corner_rgb, ((255, 255, 255),) * 4)


class ReferencePartMatchingTests(unittest.TestCase):
    def test_synthetic_render_callback_returns_exact_part_ids(self) -> None:
        id_map = np.full((24, 32), -1, dtype=np.int32)
        id_map[4:20, 5:16] = 0
        id_map[4:20, 16:27] = 1

        rendered = render_front_part_ids(
            two_part_level(),
            size=(32, 24),
            render_callback=id_callback(id_map),
        )

        np.testing.assert_array_equal(rendered, id_map)

    def test_render_front_preview_gamma_is_compensated_before_rgb_decode(self) -> None:
        expected = np.full((24, 32), -1, dtype=np.int32)
        expected[4:20, 5:16] = 0
        expected[4:20, 16:27] = 1

        def simulated_front_preview(_level, result, **_kwargs):
            framebuffer = np.zeros((24, 32, 3), dtype=np.uint8)
            # This is the fragment shader's conversion in render_front_preview.
            output_rgb = np.clip(
                np.rint(np.power(result.target_face_rgb, 1.0 / 1.04) * 255.0),
                0,
                255,
            ).astype(np.uint8)
            framebuffer[4:20, 5:16] = output_rgb[0]
            framebuffer[4:20, 16:27] = output_rgb[1]
            return framebuffer

        rendered = render_front_part_ids(
            two_part_level(),
            size=(32, 24),
            render_callback=simulated_front_preview,
        )

        np.testing.assert_array_equal(rendered, expected)

    def test_bbox_normalization_separates_reference_colours_by_visible_part(self) -> None:
        id_map = np.full((60, 80), -1, dtype=np.int32)
        id_map[10:50, 20:40] = 0
        id_map[10:50, 40:60] = 1
        reference = white_image(100, 120)
        reference[20:80, 30:60] = (230, 25, 35)
        reference[20:80, 60:90] = (25, 50, 230)

        match = match_reference_to_parts(
            two_part_level(),
            reference,
            render_callback=id_callback(id_map),
            render_size=(80, 60),
            max_samples_per_part=800,
            max_total_samples=1_000,
        )

        self.assertTrue(match.matched)
        self.assertFalse(match.mirrored)
        self.assertAlmostEqual(match.selected_iou, 1.0)
        self.assertEqual(match.silhouette_bbox, (20, 10, 60, 50))
        self.assertEqual(match.foreground_bbox, (30, 20, 90, 80))
        self.assertEqual(len(match.parts), 2)
        left, right = match.parts
        self.assertEqual((left.part_key, right.part_key), ("part-left", "part-right"))
        self.assertEqual(left.sample_count, 500)
        self.assertEqual(right.sample_count, 500)
        self.assertLess(float(left.rgb_samples[:, 2].mean()), 60.0)
        self.assertGreater(float(left.rgb_samples[:, 0].mean()), 200.0)
        self.assertGreater(float(right.rgb_samples[:, 2].mean()), 200.0)
        self.assertLess(float(right.rgb_samples[:, 0].mean()), 60.0)
        self.assertAlmostEqual(left.confidence, 1.0)
        self.assertAlmostEqual(right.confidence, 1.0)

    def test_horizontally_mirrored_reference_wins_by_iou(self) -> None:
        id_map = np.full((64, 64), -1, dtype=np.int32)
        id_map[10:50, 10:17] = 0
        id_map[43:50, 10:45] = 0
        reference = white_image(70, 70)
        # Same L silhouette, but reflected horizontally inside the same bbox.
        reference[10:50, 38:45] = (20, 190, 70)
        reference[43:50, 10:45] = (20, 190, 70)

        match = match_reference_to_parts(
            two_part_level(),
            reference,
            render_callback=id_callback(id_map),
            render_size=(64, 64),
        )

        self.assertTrue(match.matched)
        self.assertTrue(match.mirrored)
        self.assertGreater(match.mirrored_iou, match.normal_iou)
        self.assertAlmostEqual(match.mirrored_iou, 1.0)
        self.assertEqual(len(match.parts), 1)
        self.assertGreater(match.parts[0].sample_count, 0)

    def test_low_iou_returns_empty_samples_for_obj_colour_fallback(self) -> None:
        id_map = np.full((64, 64), -1, dtype=np.int32)
        id_map[10:50, 10:17] = 0
        id_map[43:50, 10:45] = 0
        reference = white_image(70, 70)
        # A T shape deliberately differs from the model L in either direction.
        reference[10:17, 10:45] = (170, 30, 200)
        reference[10:50, 24:31] = (170, 30, 200)

        match = match_reference_to_parts(
            two_part_level(),
            reference,
            render_callback=id_callback(id_map),
            render_size=(64, 64),
            minimum_iou=0.90,
        )

        self.assertFalse(match.matched)
        self.assertTrue(match.fallback_used)
        self.assertLess(match.selected_iou, 0.90)
        self.assertIn("below", match.reason)
        self.assertEqual(len(match.parts), 1)
        self.assertEqual(match.parts[0].sample_count, 0)
        self.assertEqual(match.parts[0].confidence, 0.0)

    def test_large_visible_regions_obey_per_part_and_global_sample_caps(self) -> None:
        id_map = np.full((520, 520), -1, dtype=np.int32)
        id_map[10:510, 10:260] = 0
        id_map[10:510, 260:510] = 1
        reference = white_image(600, 600)
        reference[50:550, 50:300] = (240, 80, 25)
        reference[50:550, 300:550] = (35, 165, 220)

        match = match_reference_to_parts(
            two_part_level(),
            reference,
            render_callback=id_callback(id_map),
            render_size=(520, 520),
            max_samples_per_part=700,
            max_total_samples=1_000,
        )

        self.assertTrue(match.matched)
        self.assertLessEqual(sum(part.sample_count for part in match.parts), 1_000)
        self.assertTrue(all(part.sample_count <= 700 for part in match.parts))
        self.assertEqual([part.sample_count for part in match.parts], [500, 500])


if __name__ == "__main__":
    unittest.main(verbosity=2)
