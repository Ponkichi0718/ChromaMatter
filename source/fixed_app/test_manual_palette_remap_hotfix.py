from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class ManualPaletteRemapHotfixTests(unittest.TestCase):
    def test_installed_manual_initialization_contract_for_16_24_32_states(self) -> None:
        """Exercise the same pre-imported function path used by PaintEditor.

        ``paint_gui`` imports ``apply_palette_overrides_parts`` before the r8
        hotfix is installed.  That original part function subsequently calls
        the patched global ``engine.apply_palette_overrides`` with
        ``remap_out_of_range=False``.  Run the contract in a fresh interpreter
        so test ordering cannot hide an installation/signature regression.
        """

        script = textwrap.dedent(
            r"""
            import json
            import numpy as np

            import TripoSpectrumMapper_fixed
            from final_shading_hotfix import MANUAL_MASK_ATTRIBUTE
            from spectrum_mapper import engine, paint_gui
            from spectrum_mapper.mixer import PALETTE_STATE_COUNT
            from spectrum_mapper.models import ColorResult, MeshLevel, PaletteSettings

            vertices = []
            faces = []
            for part_id in range(3):
                x = float(part_id * 2)
                first = len(vertices)
                vertices.extend(((x, 0, 0), (x + 1, 0, 0), (x, 1, 0)))
                faces.append((first, first + 1, first + 2))

            level = MeshLevel(
                vertices_unit=np.asarray(vertices, dtype=np.float64),
                faces=np.asarray(faces, dtype=np.int32),
                vertex_colors=np.zeros((9, 3), dtype=np.float64),
                areas_unit=np.full(3, 0.5, dtype=np.float64),
                neighbors=None,
                face_part_ids=np.asarray((0, 1, 2), dtype=np.int16),
                part_names=("A", "B", "C"),
                part_keys=("a", "b", "c"),
            )
            colors = ColorResult(
                tone_vertex_rgb=np.zeros((9, 3), dtype=np.float64),
                source_face_rgb=np.zeros((3, 3), dtype=np.float64),
                palette_indices=np.zeros(3, dtype=np.int8),
                target_face_rgb=np.zeros((3, 3), dtype=np.float64),
                delta_e=np.zeros(3, dtype=np.float64),
                smoothed_faces=0,
                palette_face_counts=np.zeros(PALETTE_STATE_COUNT, dtype=np.int64),
                palette_area_fractions=np.zeros(PALETTE_STATE_COUNT, dtype=np.float64),
                pink_area_fraction=0.0,
            )
            global_palette = PaletteSettings(palette_state_count=32)
            part_palettes = {
                "a": PaletteSettings(palette_state_count=16),
                "b": PaletteSettings(palette_state_count=24),
                "c": PaletteSettings(palette_state_count=32),
            }
            overrides = np.asarray((31, 31, 31), dtype=np.int8)

            # PaintEditor holds this pre-install alias.  It is the exact route
            # that previously raised the unexpected-keyword TypeError.
            editor_result = paint_gui.apply_palette_overrides_parts(
                level,
                180.0,
                global_palette,
                part_palettes,
                colors,
                overrides,
            )
            installed_result = engine.apply_palette_overrides_parts(
                level,
                180.0,
                global_palette,
                part_palettes,
                colors,
                overrides,
            )

            editor_states = editor_result.palette_indices.tolist()
            installed_states = installed_result.palette_indices.tolist()
            assert editor_states == installed_states
            assert 0 <= editor_states[0] < 16
            assert 0 <= editor_states[1] < 24
            assert editor_states[2] == 31
            assert getattr(installed_result, MANUAL_MASK_ATTRIBUTE).tolist() == [
                True,
                True,
                True,
            ]

            # The wrapper must also preserve the public keyword contract.  A
            # caller that has already done a local remap may explicitly retain
            # state 31 even while the supplied global palette is set to 16.
            direct = engine.apply_palette_overrides(
                level,
                180.0,
                PaletteSettings(palette_state_count=16),
                colors,
                np.asarray((31, -1, -1), dtype=np.int8),
                remap_out_of_range=False,
            )
            assert direct.palette_indices.tolist() == [31, 0, 0]
            assert getattr(direct, MANUAL_MASK_ATTRIBUTE).tolist() == [
                True,
                False,
                False,
            ]
            print("MANUAL_REMAP_RESULT=" + json.dumps(editor_states))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parent,
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        self.assertIn("MANUAL_REMAP_RESULT=", completed.stdout)
        payload = completed.stdout.rsplit("MANUAL_REMAP_RESULT=", 1)[1].splitlines()[0]
        states = json.loads(payload)
        self.assertLess(states[0], 16)
        self.assertLess(states[1], 24)
        self.assertEqual(states[2], 31)


if __name__ == "__main__":
    unittest.main()
