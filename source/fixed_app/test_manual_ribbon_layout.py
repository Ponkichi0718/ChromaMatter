from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.paint_gui import compute_manual_canvas_layout  # noqa: E402


class ManualCanvasLayoutTests(unittest.TestCase):
    def test_hidden_reference_gives_the_whole_workspace_to_3d(self) -> None:
        layout = compute_manual_canvas_layout(1400, 900, False)

        self.assertIsNone(layout["reference"])
        self.assertEqual(layout["target"], (14, 1372))
        self.assertEqual(layout["panel_height"], 838)

    def test_visible_reference_uses_thirty_percent_without_overlap(self) -> None:
        layout = compute_manual_canvas_layout(1400, 900, True)
        reference_x, reference_width = layout["reference"]
        target_x, target_width = layout["target"]

        self.assertEqual(reference_x, 14)
        self.assertEqual(reference_width, int((1400 - 28 - 14) * 0.30))
        self.assertEqual(target_x, reference_x + reference_width + 14)
        self.assertEqual(target_x + target_width, 1400 - 14)
        self.assertGreater(target_width, reference_width)

    def test_small_initial_tk_size_uses_safe_workspace_floors(self) -> None:
        layout = compute_manual_canvas_layout(1, 1, False)

        self.assertEqual(layout["width"], 720)
        self.assertEqual(layout["height"], 420)
        self.assertGreaterEqual(layout["target"][1], 420)
        self.assertGreaterEqual(layout["panel_height"], 300)


if __name__ == "__main__":
    unittest.main()
