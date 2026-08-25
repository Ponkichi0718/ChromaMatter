from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.engine import (
    _absorb_flat_four_embedded_achromatic_islands,
    _local_part_neighbors,
    apply_palette_overrides,
    face_neighbors_partial,
    prepare_flat_four_recommendation_samples,
    recolor_level,
    recolor_level_parts,
    srgb_to_lab,
)
from spectrum_mapper.models import (
    COLOR_MODE_FLAT_FOUR,
    COLOR_MODE_FULL_SPECTRUM,
    MeshLevel,
    PaletteSettings,
    ToneSettings,
)
from spectrum_mapper.parts import assignment_palette_rgb_table


PALETTE = ["#121212", "#33384A", "#EDC09D", "#F5F5F5"]
SKIN = "#EDC09D"
WHITE_HIGHLIGHT = "#F8F3EE"
GRAY_HIGHLIGHT = "#B8B8B8"
BLACK = "#171717"


def _rgb(hex_color: str) -> np.ndarray:
    value = hex_color.lstrip("#")
    return np.asarray(
        [int(value[index : index + 2], 16) / 255.0 for index in (0, 2, 4)],
        dtype=np.float64,
    )


def _star_level(center: str, boundary: tuple[str, str, str]) -> MeshLevel:
    # One centre triangle and one coplanar triangle across each edge.  The
    # explicit face graph is the evidence used by the Flat-only classifier.
    vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.5, 0.8660254, 0.0],
            [0.5, -0.8660254, 0.0],
            [1.5, 0.8660254, 0.0],
            [-0.5, 0.8660254, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [[0, 1, 2], [1, 0, 3], [2, 1, 4], [0, 2, 5]],
        dtype=np.int32,
    )
    face_colors = np.asarray(
        [_rgb(center), *(_rgb(color) for color in boundary)],
        dtype=np.float64,
    )
    # Faces do not share colour vertices in a real colour-per-vertex model at
    # a hard colour boundary.  For this focused engine fixture, repeat the
    # desired face colour through an expanded, per-face vertex buffer.
    expanded_vertices = vertices[faces].reshape(-1, 3)
    expanded_faces = np.arange(12, dtype=np.int32).reshape(-1, 3)
    expanded_colors = np.repeat(face_colors, 3, axis=0)
    return MeshLevel(
        vertices_unit=expanded_vertices,
        faces=expanded_faces,
        vertex_colors=expanded_colors,
        areas_unit=np.asarray([0.25, 5.0, 5.0, 5.0], dtype=np.float64),
        neighbors=np.asarray(
            [[1, 2, 3], [0, -1, -1], [0, -1, -1], [0, -1, -1]],
            dtype=np.int32,
        ),
    )


def _shared_star_level(*, multipart: bool = False) -> MeshLevel:
    vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.5, 0.8660254, 0.0],
            [0.5, -0.8660254, 0.0],
            [1.5, 0.8660254, 0.0],
            [-0.5, 0.8660254, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [[0, 1, 2], [1, 0, 3], [2, 1, 4], [0, 2, 5]],
        dtype=np.int32,
    )
    # Shared highlight vertices plus saturated outer vertices produce one pale
    # centre and three coherent warm boundary faces while retaining real edge
    # topology.  This mirrors an open vertex-colour GLB rather than an explicit
    # synthetic neighbors fixture.
    colors = np.asarray(
        [_rgb(WHITE_HIGHLIGHT)] * 3 + [_rgb("#A03000")] * 3,
        dtype=np.float64,
    )
    if multipart:
        second_vertices = vertices + np.asarray([3.0, 0.0, 0.0])
        vertices = np.vstack((vertices, second_vertices))
        faces = np.vstack((faces, faces + 6))
        colors = np.vstack((colors, colors))
    face_count = len(faces)
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=colors,
        areas_unit=np.tile(np.asarray([0.25, 5.0, 5.0, 5.0]), face_count // 4),
        neighbors=None,
        face_part_ids=(
            np.repeat(np.arange(2, dtype=np.int16), 4)
            if multipart
            else np.empty(0, dtype=np.int16)
        ),
        part_names=("left", "right") if multipart else (),
        part_keys=("left", "right") if multipart else (),
    )


class FlatAchromaticHighlightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=list(PALETTE),
        )
        self.tone = ToneSettings(white_point=1.0, smoothing=False)

    def _result(self, center: str, boundary: tuple[str, str, str]):
        return recolor_level(
            _star_level(center, boundary),
            1.0,
            self.tone,
            self.palette,
        )

    def test_white_skin_highlight_is_absorbed_into_skin(self) -> None:
        result = self._result(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))

        self.assertEqual(int(result.palette_indices[0]), 2)
        np.testing.assert_array_equal(result.palette_indices[1:], [2, 2, 2])

    def test_open_shared_vertex_level_uses_flat_only_partial_topology(self) -> None:
        result = recolor_level(
            _shared_star_level(),
            1.0,
            self.tone,
            self.palette,
        )

        np.testing.assert_array_equal(result.palette_indices, [2, 2, 2, 2])

    def test_open_multipart_level_uses_local_flat_partial_topology(self) -> None:
        result = recolor_level_parts(
            _shared_star_level(multipart=True),
            1.0,
            self.tone,
            self.palette,
            {"right": self.palette},
        )

        np.testing.assert_array_equal(result.palette_indices, [2] * 8)

    def test_explicit_white_manual_paint_remains_authoritative(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        automatic = recolor_level(
            level, 1.0, self.tone, self.palette
        )
        overrides = np.full(4, -1, dtype=np.int8)
        overrides[0] = 3

        painted = apply_palette_overrides(
            level,
            1.0,
            self.palette,
            automatic,
            overrides,
        )

        self.assertEqual(int(automatic.palette_indices[0]), 2)
        self.assertEqual(int(painted.palette_indices[0]), 3)

    def test_gray_skin_highlight_is_absorbed_into_skin(self) -> None:
        result = self._result(GRAY_HIGHLIGHT, (SKIN, SKIN, SKIN))

        self.assertEqual(int(result.palette_indices[0]), 2)

    def test_eye_white_beside_dark_line_work_is_preserved(self) -> None:
        result = self._result(WHITE_HIGHLIGHT, (SKIN, BLACK, BLACK))

        self.assertEqual(int(result.palette_indices[0]), 3)

    def test_true_black_detail_is_never_treated_as_highlight(self) -> None:
        result = self._result(BLACK, (SKIN, SKIN, SKIN))

        self.assertEqual(int(result.palette_indices[0]), 0)

    def test_disconnected_white_part_is_preserved(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        level.neighbors = np.full((4, 3), -1, dtype=np.int32)

        result = recolor_level(level, 1.0, self.tone, self.palette)

        self.assertEqual(int(result.palette_indices[0]), 3)

    def test_broad_white_surface_is_preserved(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        level.areas_unit = np.asarray([20.0, 1.0, 1.0, 1.0])

        result = recolor_level(level, 1.0, self.tone, self.palette)

        self.assertEqual(int(result.palette_indices[0]), 3)

    def test_white_across_a_hard_crease_is_preserved(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        # Tilt one surrounding face well past the conservative smooth-angle
        # gate.  The colour island is therefore possible trim/armour, not a
        # safe baked-lighting correction.
        level.vertices_unit[5, 2] = 2.0

        result = recolor_level(level, 1.0, self.tone, self.palette)

        self.assertEqual(int(result.palette_indices[0]), 3)

    def test_default_tone_recovers_skin_chroma_clipped_by_white_point(self) -> None:
        level = _star_level(SKIN, (SKIN, SKIN, SKIN))
        tone = ToneSettings(white_point=0.60, saturation=1.0, smoothing=False)

        result = recolor_level(level, 1.0, tone, self.palette)

        self.assertEqual(int(result.palette_indices[0]), 2)

    def test_white_point_clipping_keeps_recommendation_and_output_aligned(
        self,
    ) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        tone = ToneSettings(white_point=0.60, saturation=1.0, smoothing=False)

        result = recolor_level(level, 1.0, tone, self.palette)

        np.testing.assert_array_equal(result.palette_indices, [2, 2, 2, 2])

    def test_intentional_desaturation_does_not_restore_raw_skin_chroma(self) -> None:
        level = _star_level(SKIN, (SKIN, SKIN, SKIN))
        level.neighbors = np.full((4, 3), -1, dtype=np.int32)
        tone = ToneSettings(white_point=1.0, saturation=0.0, smoothing=False)

        result = recolor_level(level, 1.0, tone, self.palette)

        self.assertNotEqual(int(result.palette_indices[0]), 2)

    def test_near_default_saturation_has_no_numerical_cliff(self) -> None:
        level = _star_level(SKIN, (SKIN, SKIN, SKIN))
        tone = ToneSettings(
            white_point=0.60,
            saturation=0.999999998,
            smoothing=False,
        )

        result = recolor_level(level, 1.0, tone, self.palette)

        self.assertEqual(int(result.palette_indices[0]), 2)

    def test_explicit_saturation_step_is_respected(self) -> None:
        level = _star_level(SKIN, (SKIN, SKIN, SKIN))
        level.neighbors = np.full((4, 3), -1, dtype=np.int32)
        tone = ToneSettings(
            white_point=0.60,
            saturation=0.98,
            smoothing=False,
        )

        result = recolor_level(level, 1.0, tone, self.palette)

        self.assertNotEqual(int(result.palette_indices[0]), 2)

    def test_medium_dark_skin_highlight_is_absorbed(self) -> None:
        dark_skin = "#C68642"
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=["#121212", "#33384A", dark_skin, "#F5F5F5"],
        )

        result = recolor_level(
            _star_level(
                WHITE_HIGHLIGHT,
                (dark_skin, dark_skin, dark_skin),
            ),
            1.0,
            self.tone,
            palette,
        )

        self.assertEqual(int(result.palette_indices[0]), 2)

    def test_reversed_boundary_winding_is_not_considered_smooth(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        level.faces[1, [1, 2]] = level.faces[1, [2, 1]]

        result = recolor_level(level, 1.0, self.tone, self.palette)

        self.assertEqual(int(result.palette_indices[0]), 3)

    def test_recommendation_replaces_highlight_rgb_without_losing_area(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        face_rgb = level.vertex_colors[level.faces].mean(axis=1)

        adjusted, count = prepare_flat_four_recommendation_samples(
            face_rgb,
            level.areas_unit,
            level.neighbors,
            level.vertices_unit,
            level.faces,
        )

        self.assertEqual(count, 1)
        np.testing.assert_allclose(adjusted[0], _rgb(SKIN), atol=2e-6)
        np.testing.assert_allclose(adjusted[1:], face_rgb[1:])
        np.testing.assert_array_equal(
            level.areas_unit, np.asarray([0.25, 5.0, 5.0, 5.0])
        )

    def test_recommendation_preserves_eye_white(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, BLACK, BLACK))
        face_rgb = level.vertex_colors[level.faces].mean(axis=1)

        adjusted, count = prepare_flat_four_recommendation_samples(
            face_rgb,
            level.areas_unit,
            level.neighbors,
            level.vertices_unit,
            level.faces,
        )

        self.assertEqual(count, 0)
        np.testing.assert_allclose(adjusted, face_rgb)

    def test_recommendation_recovers_raw_skin_clipped_to_white(self) -> None:
        level = _star_level(SKIN, (SKIN, SKIN, SKIN))
        source_rgb = level.vertex_colors[level.faces].mean(axis=1)
        tone_rgb = np.ones_like(source_rgb)

        adjusted, count = prepare_flat_four_recommendation_samples(
            tone_rgb,
            level.areas_unit,
            None,
            level.vertices_unit,
            level.faces,
            source_face_rgb=source_rgb,
        )

        self.assertEqual(count, 4)
        np.testing.assert_allclose(
            adjusted, np.repeat(_rgb(SKIN)[None, :], 4, axis=0)
        )

    def test_global_recommendation_neighbors_do_not_cross_parts(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        selected = np.arange(4, dtype=np.int64)
        local = _local_part_neighbors(
            level.neighbors,
            selected,
            4,
            np.asarray([0, 1, 1, 1], dtype=np.int16),
        )
        face_rgb = level.vertex_colors[level.faces].mean(axis=1)

        adjusted, count = prepare_flat_four_recommendation_samples(
            face_rgb,
            level.areas_unit,
            local,
            level.vertices_unit,
            level.faces,
        )

        self.assertEqual(count, 0)
        np.testing.assert_allclose(adjusted, face_rgb)

    def test_common_palette_assignment_does_not_cross_parts(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        level.face_part_ids = np.asarray([0, 1, 1, 1], dtype=np.int16)

        result = recolor_level(level, 1.0, self.tone, self.palette)

        self.assertEqual(int(result.palette_indices[0]), 3)
        np.testing.assert_array_equal(result.palette_indices[1:], [2, 2, 2])

    def test_group_area_gate_is_not_diluted_by_an_unrelated_large_part(
        self,
    ) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        extra_vertices = np.asarray(
            [[10.0, 0.0, 0.0], [11.0, 0.0, 0.0], [10.0, 1.0, 0.0]],
            dtype=np.float64,
        )
        level.vertices_unit = np.vstack((level.vertices_unit, extra_vertices))
        level.faces = np.vstack(
            (level.faces, np.asarray([[12, 13, 14]], dtype=np.int32))
        )
        level.vertex_colors = np.vstack(
            (level.vertex_colors, np.repeat(_rgb(SKIN)[None, :], 3, axis=0))
        )
        level.areas_unit = np.asarray([0.25, 1.0, 1.0, 1.0, 100.0])
        level.neighbors = np.vstack(
            (level.neighbors, np.asarray([[-1, -1, -1]], dtype=np.int32))
        )
        face_rgb = level.vertex_colors[level.faces].mean(axis=1)

        adjusted, count = prepare_flat_four_recommendation_samples(
            face_rgb,
            level.areas_unit,
            level.neighbors,
            level.vertices_unit,
            level.faces,
            face_group_ids=np.asarray([0, 0, 0, 0, 1], dtype=np.int16),
        )

        self.assertEqual(count, 0)
        np.testing.assert_allclose(adjusted, face_rgb)

    def test_sparse_global_group_id_is_valid_for_a_local_part(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        face_rgb = level.vertex_colors[level.faces].mean(axis=1)

        adjusted, count = prepare_flat_four_recommendation_samples(
            face_rgb,
            level.areas_unit,
            level.neighbors,
            level.vertices_unit,
            level.faces,
            face_group_ids=np.full(4, 5, dtype=np.int16),
        )

        self.assertEqual(count, 1)
        np.testing.assert_allclose(adjusted[0], _rgb(SKIN), atol=2e-6)

    def test_partial_production_neighbors_absorb_only_closed_local_island(
        self,
    ) -> None:
        vertices = np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.5, 0.8660254, 0.0],
                [0.5, -0.8660254, 0.0],
                [1.5, 0.8660254, 0.0],
                [-0.5, 0.8660254, 0.0],
            ],
            dtype=np.float64,
        )
        faces = np.asarray(
            [[0, 1, 2], [1, 0, 3], [2, 1, 4], [0, 2, 5]],
            dtype=np.int32,
        )
        neighbors = face_neighbors_partial(faces, len(vertices))
        face_rgb = np.asarray(
            [_rgb(WHITE_HIGHLIGHT), _rgb(SKIN), _rgb(SKIN), _rgb(SKIN)]
        )

        adjusted, count = prepare_flat_four_recommendation_samples(
            face_rgb,
            np.asarray([0.25, 5.0, 5.0, 5.0]),
            neighbors,
            vertices,
            faces,
        )

        self.assertEqual(count, 1)
        np.testing.assert_allclose(adjusted[0], _rgb(SKIN), atol=2e-6)

    def test_flat_topology_is_built_lazily_for_an_eligible_open_mesh(
        self,
    ) -> None:
        vertices = np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.5, 0.8660254, 0.0],
                [0.5, -0.8660254, 0.0],
                [1.5, 0.8660254, 0.0],
                [-0.5, 0.8660254, 0.0],
            ],
            dtype=np.float64,
        )
        faces = np.asarray(
            [[0, 1, 2], [1, 0, 3], [2, 1, 4], [0, 2, 5]],
            dtype=np.int32,
        )
        face_rgb = np.asarray(
            [_rgb(WHITE_HIGHLIGHT), _rgb(SKIN), _rgb(SKIN), _rgb(SKIN)]
        )

        with patch(
            "spectrum_mapper.engine.face_neighbors_partial",
            wraps=face_neighbors_partial,
        ) as build_neighbors:
            adjusted, count = prepare_flat_four_recommendation_samples(
                face_rgb,
                np.asarray([0.25, 5.0, 5.0, 5.0]),
                None,
                vertices,
                faces,
            )

        build_neighbors.assert_called_once()
        self.assertEqual(count, 1)
        np.testing.assert_allclose(adjusted[0], _rgb(SKIN), atol=2e-6)

    def test_flat_topology_is_skipped_without_achromatic_candidates(
        self,
    ) -> None:
        face_rgb = np.asarray([_rgb(SKIN)], dtype=np.float64)
        with patch(
            "spectrum_mapper.engine.flat_four_topology_neighbors",
            side_effect=AssertionError("topology should not be built"),
        ):
            adjusted, count = prepare_flat_four_recommendation_samples(
                face_rgb,
                np.ones(1, dtype=np.float64),
                None,
                np.asarray(
                    [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float64,
                ),
                np.asarray([[0, 1, 2]], dtype=np.int32),
            )

        self.assertEqual(count, 0)
        np.testing.assert_allclose(adjusted, face_rgb)

    def test_flat_topology_is_skipped_above_candidate_safety_limit(
        self,
    ) -> None:
        face_count = 500_001
        face_rgb = np.repeat(_rgb(WHITE_HIGHLIGHT)[None, :], face_count, axis=0)
        with patch(
            "spectrum_mapper.engine.flat_four_topology_neighbors",
            side_effect=AssertionError("topology should not be built"),
        ):
            adjusted, count = prepare_flat_four_recommendation_samples(
                face_rgb,
                np.ones(face_count, dtype=np.float64),
                None,
                np.asarray(
                    [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float64,
                ),
                np.zeros((face_count, 3), dtype=np.int32),
            )

        self.assertEqual(count, 0)
        self.assertIs(adjusted, face_rgb)

    def test_flat_topology_is_skipped_when_open_mesh_itself_is_too_large(
        self,
    ) -> None:
        level = _shared_star_level()
        face_rgb = level.vertex_colors[level.faces].mean(axis=1)
        with (
            patch("spectrum_mapper.engine._FLAT_TOPOLOGY_BUILD_FACE_LIMIT", 3),
            patch(
                "spectrum_mapper.engine.flat_four_topology_neighbors",
                side_effect=AssertionError("oversized topology should not be built"),
            ),
        ):
            adjusted, count = prepare_flat_four_recommendation_samples(
                face_rgb,
                level.areas_unit,
                None,
                level.vertices_unit,
                level.faces,
            )

        self.assertEqual(count, 0)
        np.testing.assert_allclose(adjusted, face_rgb)

    def test_absorption_uses_the_actual_surrounding_flat_slot(self) -> None:
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FLAT_FOUR,
            physical_hex=["#121212", "#33384A", "#B07050", "#F5F5F5"],
        )

        result = recolor_level(
            _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN)),
            1.0,
            self.tone,
            palette,
        )

        np.testing.assert_array_equal(result.palette_indices, [2, 2, 2, 2])

    def test_full_spectrum_does_not_enter_flat_absorption(self) -> None:
        palette = PaletteSettings(
            color_mode=COLOR_MODE_FULL_SPECTRUM,
            physical_hex=list(PALETTE),
        )
        with patch(
            "spectrum_mapper.engine._absorb_flat_four_embedded_achromatic_islands",
            side_effect=AssertionError("Flat absorption entered Full Spectrum"),
        ):
            recolor_level(
                _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN)),
                1.0,
                self.tone,
                palette,
            )

        with patch(
            "spectrum_mapper.engine._flat_four_lab_chunks",
            side_effect=AssertionError("Flat Lab conversion entered Full Spectrum"),
        ):
            recolor_level(
                _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN)),
                1.0,
                self.tone,
                palette,
            )

    def test_disabled_skin_slot_fails_closed(self) -> None:
        level = _star_level(WHITE_HIGHLIGHT, (SKIN, SKIN, SKIN))
        palette_rgb = assignment_palette_rgb_table(self.palette)
        indices = np.asarray([3, 2, 2, 2], dtype=np.int8)
        enabled = np.asarray(self.palette.enabled_states, dtype=bool)
        enabled[2] = False
        face_rgb = level.vertex_colors[level.faces].mean(axis=1)

        remapped, count = _absorb_flat_four_embedded_achromatic_islands(
            indices,
            srgb_to_lab(face_rgb),
            srgb_to_lab(palette_rgb),
            enabled,
            level.areas_unit,
            level.neighbors,
            level.vertices_unit,
            level.faces,
        )

        self.assertEqual(count, 0)
        self.assertEqual(int(remapped[0]), 3)


if __name__ == "__main__":
    unittest.main()
