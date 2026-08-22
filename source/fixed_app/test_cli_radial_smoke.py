from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import cli


class PackagedRadialSmokeTests(unittest.TestCase):
    def test_public_spec_excludes_source_only_svg_renderer(self) -> None:
        fixed_app = Path(__file__).resolve().parent
        spec_path = fixed_app / "TripoSpectrumMapper_fixed.spec"
        spec_text = spec_path.read_text(encoding="utf-8")
        tree = ast.parse(spec_text, filename=str(spec_path))
        analysis = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Analysis"
        )
        keywords = {item.arg: item.value for item in analysis.keywords}
        hidden_imports = {
            value.value
            for value in ast.walk(keywords["hiddenimports"])
            if isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        }
        excluded = {
            value.value
            for value in ast.walk(keywords["excludes"])
            if isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        }

        self.assertEqual(excluded, {"resvg", "resvg._resvg"})
        self.assertTrue({"resvg", "resvg._resvg"}.isdisjoint(hidden_imports))
        self.assertIn("spectrum_mapper.decal_image", hidden_imports)
        for removed_runtime_asset in (
            "RESVG_DATAS",
            "resvg-0.2.0.dist-info",
            "licenses/resvg-py",
            "LICENSE_RESVG_PY.txt",
            "LICENSE_RESVG_MIT.txt",
        ):
            with self.subTest(removed_runtime_asset=removed_runtime_asset):
                self.assertNotIn(removed_runtime_asset, spec_text)
        for requirements_name in (
            "requirements-build.txt",
            "requirements-build.lock",
        ):
            requirements = (fixed_app / requirements_name).read_text(
                encoding="utf-8"
            )
            self.assertIn("resvg==0.2.0", requirements)

    def test_public_spec_collects_only_manifest_pinned_native_license_assets(self) -> None:
        spec_path = Path(__file__).resolve().parent / "TripoSpectrumMapper_fixed.spec"
        spec_text = spec_path.read_text(encoding="utf-8")
        self.assertIn("def audited_manifest_license_datas", spec_text)
        self.assertIn('"qt_static_components.json"', spec_text)
        self.assertIn('"pytetwild_static_closure.json"', spec_text)
        self.assertIn("actual_sha256 != expected_sha256", spec_text)
        self.assertIn("+ AUDITED_LICENSE_DATAS", spec_text)

    def test_frozen_public_decal_smoke_keeps_png_and_marks_svg_not_packaged(
        self,
    ) -> None:
        from spectrum_mapper import decal_image

        original_loader = decal_image.load_decal_bytes
        requested_filenames: list[str] = []

        def guarded_loader(*args, **kwargs):
            filename = str(kwargs.get("filename", ""))
            requested_filenames.append(filename)
            if filename.casefold().endswith(".svg"):
                raise AssertionError("frozen public smoke must not request SVG")
            return original_loader(*args, **kwargs)

        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "_MEIPASS", str(Path.cwd()), create=True),
            mock.patch.object(
                decal_image,
                "load_decal_bytes",
                side_effect=guarded_loader,
            ),
        ):
            result = cli._decal_runtime_smoke()

        self.assertEqual(requested_filenames, ["packaged-self-test.png"])
        self.assertEqual(result["resvg"], "not-packaged")
        self.assertTrue(result["decal_png_smoke"])
        self.assertEqual(result["decal_png_status"], "ok")
        self.assertIsNone(result["decal_svg_smoke"])
        self.assertEqual(result["decal_svg_status"], "not-packaged")
        self.assertFalse(result["decal_svg_required"])
        self.assertEqual(
            result["decal_loader_status"],
            "ok; SVG/resvg not-packaged",
        )
        self.assertTrue(result["ok"])

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
        self.assertEqual(data["decal_png_status"], "ok")
        self.assertTrue(data["decal_svg_smoke"])
        self.assertEqual(data["decal_svg_status"], "ok")
        self.assertTrue(data["decal_svg_required"])
        self.assertEqual(data["decal_loader_status"], "ok")
        self.assertTrue(data["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
