from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from spectrum_mapper.engine import write_guide
from spectrum_mapper.models import PaletteSettings


class OutputGuideTests(unittest.TestCase):
    def test_full_spectrum_model_is_opened_as_project(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "guide.txt"
            write_guide(
                path,
                Path("model.3mf"),
                180.0,
                PaletteSettings(),
            )
            text = path.read_text(encoding="utf-8-sig")

        self.assertIn("Open as project / プロジェクトとして開く", text)
        self.assertIn("Import geometry / 形状として読み込み", text)
        self.assertIn("選びません", text)


if __name__ == "__main__":
    unittest.main()
