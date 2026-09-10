from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from spectrum_mapper import engine
from spectrum_mapper.filament_database import srgb_hex_to_lab
from spectrum_mapper.radial_stage_b import RadialStageBError
from spectrum_mapper import variable_skin_head_coupon as coupon


class VariableSkinHeadSourceTests(unittest.TestCase):
    def test_original_head_is_watertight_left_lit_and_uses_declared_states(
        self,
    ) -> None:
        mesh = coupon.build_blocky_head_mesh()
        topology = engine.edge_topology(mesh.faces, len(mesh.vertices_mm))
        self.assertEqual(0, topology["boundary_edges"])
        self.assertEqual(0, topology["nonmanifold_edges"])
        self.assertGreater(engine.signed_volume(mesh.vertices_mm, mesh.faces), 0.0)
        self.assertLessEqual(
            len(mesh.faces),
            500,
            "The coupon must stay coarse enough for the variable-partition cap",
        )
        self.assertAlmostEqual(36.0, mesh.height_mm, places=9)
        self.assertEqual(coupon.PHYSICAL_HEX, tuple(coupon.head_palette().physical_hex))
        self.assertTrue(
            {
                coupon.STATE_BLACK,
                coupon.STATE_BROWN,
                coupon.STATE_WHITE,
                *coupon.SKIN_RADIAL_STATES,
                *coupon.HAIR_CONVENTIONAL_STATES,
            }.issubset(set(map(int, mesh.face_states)))
        )
        front_skin = [
            int(state)
            for state, direction in zip(
                mesh.face_states, mesh.face_directions, strict=True
            )
            if direction == (0, -1, 0) and int(state) in coupon.SKIN_RADIAL_STATES
        ]
        self.assertGreater(len(set(front_skin)), 2)

    def test_normal_target_lstar_mapping_occupies_all_five_bands(self) -> None:
        schedule = coupon.head_thickness_schedule(coupon.head_palette())
        expected_by_state = {
            4: 0.10,
            22: 0.18,
            16: 0.26,
            23: 0.34,
            10: 0.42,
        }
        self.assertEqual("target_lstar", schedule.basis)
        self.assertEqual(5, schedule.band_count)
        self.assertEqual(set(expected_by_state), set(schedule.thickness_by_state))
        for state, expected in expected_by_state.items():
            self.assertAlmostEqual(
                expected,
                schedule.thickness_by_state[state],
                places=10,
            )
        self.assertEqual(
            [0, 1, 2, 3, 4],
            sorted(item.band_index for item in schedule.states),
        )

    def test_contrast_gate_fixture_is_high_skin_low_hair(self) -> None:
        lstar = [float(srgb_hex_to_lab(value)[0]) for value in coupon.PHYSICAL_HEX]
        self.assertGreaterEqual(abs(lstar[1] - lstar[0]), 35.0)
        self.assertLess(abs(lstar[2] - lstar[0]), 35.0)

    def test_preview_is_deterministic_front_isometric_png(self) -> None:
        mesh = coupon.build_blocky_head_mesh()
        palette = coupon.head_palette()
        with tempfile.TemporaryDirectory(
            prefix="chromamatter-head-preview-test-"
        ) as temporary:
            folder = Path(temporary)
            first = folder / "first.png"
            second = folder / "second.png"
            coupon._write_preview(first, mesh, palette)
            coupon._write_preview(second, mesh, palette)
            with Image.open(first) as preview:
                self.assertEqual((1200, 640), preview.size)
                self.assertEqual("RGB", preview.mode)
            self.assertGreater(first.stat().st_size, 10_000)
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).digest(),
                hashlib.sha256(second.read_bytes()).digest(),
            )

    def test_standalone_reference_obj_reopens_as_watertight_vertex_colour_obj(
        self,
    ) -> None:
        mesh = coupon.build_blocky_head_mesh()
        with tempfile.TemporaryDirectory(
            prefix="chromamatter-head-obj-test-"
        ) as temporary:
            folder = Path(temporary)
            obj_path = folder / "reference_head.obj"
            mtl_path = folder / "reference_head.mtl"
            coupon._write_original_obj_mtl(
                obj_path,
                mtl_path,
                mesh,
                coupon.head_palette(),
            )
            loaded = engine.load_vertex_color_obj(obj_path)
        topology = engine.edge_topology(loaded.faces, len(loaded.vertices))
        self.assertEqual(0, topology["boundary_edges"])
        self.assertEqual(0, topology["nonmanifold_edges"])
        self.assertTrue(np.isfinite(loaded.colors).all())
        self.assertGreater(len(np.unique(np.round(loaded.colors, 6), axis=0)), 5)
        self.assertAlmostEqual(
            mesh.source_volume_mm3,
            engine.signed_volume(loaded.vertices, loaded.faces),
            places=6,
        )


class VariableSkinHeadAdaptiveSafetyTests(unittest.TestCase):
    def test_invalid_adaptive_head_stops_before_any_hybrid_is_emitted(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="chromamatter-head-fail-closed-"
        ) as temporary:
            folder = Path(temporary)
            with self.assertRaises(RadialStageBError) as caught:
                coupon.generate_variable_skin_head_bundle(folder)
            self.assertEqual(
                caught.exception.code,
                "localized_threshold_interface_too_deep",
            )
            hybrid_names = {
                coupon.HYBRID_CONTROL_FILE,
                coupon.HYBRID_CLASSIC_2_FILE,
                coupon.HYBRID_CLASSIC_3_FILE,
                coupon.HYBRID_ARACHNE_3_FILE,
            }
            self.assertTrue(
                hybrid_names.isdisjoint({path.name for path in folder.iterdir()})
            )
            self.assertFalse((folder / "manifest.json").exists())
            self.assertFalse(
                (folder / "variable_skin_head_validation_bundle.zip").exists()
            )


if __name__ == "__main__":
    unittest.main()
