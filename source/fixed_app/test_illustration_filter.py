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
    recolor_level,
    write_vertex_color_obj,
)
from spectrum_mapper.illustration_filter import (
    IllustrationFilterError,
    apply_illustration_filter,
    apply_illustration_filter_faces,
)
from spectrum_mapper.models import (
    AppSettings,
    MeshLevel,
    PaletteSettings,
    ToneSettings,
)


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
            )
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
        ):
            self.assertNotIn(key, tone_payload)
        dormant_payload = AppSettings(
            tone=ToneSettings(
                illustration_mode="off",
                illustration_strength=0.2,
                illustration_bands=6,
                illustration_light="front_right",
            )
        ).to_dict()["tone"]
        self.assertNotIn("illustration_mode", dormant_payload)
        active_payload = AppSettings(
            tone=ToneSettings(illustration_mode="cel")
        ).to_dict()["tone"]
        self.assertEqual(active_payload["illustration_mode"], "cel")

    def test_invalid_persisted_controls_fail_at_settings_boundary(self) -> None:
        for field, value in (
            ("illustration_mode", "watercolor"),
            ("illustration_strength", float("nan")),
            ("illustration_bands", 8),
            ("illustration_light", "rear"),
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
