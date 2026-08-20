from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import cli


class PackagedRadialSmokeTests(unittest.TestCase):
    def test_native_radial_geometry_writer_and_reopen_validation(self) -> None:
        ok, status = cli._radial_export_smoke()
        self.assertTrue(ok, status)
        self.assertEqual(status, "ok")

    def test_release_entrypoint_json_includes_passing_radial_gate(self) -> None:
        fixed_app = Path(__file__).resolve().parent
        handoff = fixed_app.parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            (str(handoff), str(fixed_app))
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(fixed_app / "TripoSpectrumMapper_fixed.py"),
                "--self-test",
            ],
            cwd=handoff,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        start = completed.stdout.find("{")
        self.assertGreaterEqual(start, 0, completed.stdout + completed.stderr)
        data, _end = json.JSONDecoder().raw_decode(completed.stdout[start:])
        self.assertEqual(completed.returncode, 0, data)
        self.assertTrue(data["radial_export_smoke"])
        self.assertEqual(data["radial_export_status"], "ok")
        self.assertEqual(data["resvg"], "0.2.0")
        self.assertTrue(data["decal_png_smoke"])
        self.assertTrue(data["decal_svg_smoke"])
        self.assertEqual(data["decal_loader_status"], "ok")
        self.assertTrue(data["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
