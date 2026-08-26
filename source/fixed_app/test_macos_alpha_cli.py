from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np


FIXED_APP = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXED_APP))

from spectrum_mapper import cli


class _Framebuffer:
    def __init__(self, pixel: bytes = bytes((17, 91, 203, 255))) -> None:
        self.pixel = pixel
        self.used = False
        self.cleared: tuple[float, ...] | None = None
        self.released = False

    def use(self) -> None:
        self.used = True

    def clear(self, *rgba: float) -> None:
        self.cleared = tuple(rgba)

    def read(self, *, components: int, dtype: str) -> bytes:
        if components != 4 or dtype != "f1":
            raise AssertionError("unexpected framebuffer read contract")
        return self.pixel

    def release(self) -> None:
        self.released = True


class _Context:
    def __init__(self, framebuffer: _Framebuffer, version_code: int = 410) -> None:
        self.framebuffer = framebuffer
        self.version_code = version_code
        self.request: tuple[tuple[int, int], int, str] | None = None
        self.released = False

    def simple_framebuffer(
        self,
        size: tuple[int, int],
        *,
        components: int,
        dtype: str,
    ) -> _Framebuffer:
        self.request = (size, components, dtype)
        return self.framebuffer

    def release(self) -> None:
        self.released = True


class _ModernGL:
    def __init__(self, context: _Context) -> None:
        self.context = context
        self.require: int | None = None

    def create_standalone_context(self, *, require: int) -> _Context:
        self.require = require
        return self.context


class _PyMeshLab:
    class Mesh:
        def __init__(self, *, vertex_matrix, face_matrix) -> None:
            self.vertex_matrix = vertex_matrix
            self.face_matrix = face_matrix

    class _MeshSet:
        def __init__(self, owner: "_PyMeshLab") -> None:
            self.owner = owner
            self.mesh = None

        def add_mesh(self, mesh, label: str) -> None:
            self.mesh = mesh
            self.owner.labels.append(label)

        def apply_filter(self, name: str) -> None:
            if self.mesh is None:
                raise AssertionError("filter probe did not add a mesh")
            self.owner.applications.append(name)
            if name == self.owner.failing_filter:
                raise RuntimeError("native filter failed")

    def __init__(
        self,
        *,
        filters: tuple[str, ...] | None = None,
        failing_filter: str | None = None,
    ) -> None:
        self.filters = (
            cli.MACOS_ALPHA_REQUIRED_PYMESHLAB_FILTERS
            if filters is None
            else filters
        )
        self.failing_filter = failing_filter
        self.mesh_sets: list[_PyMeshLab._MeshSet] = []
        self.labels: list[str] = []
        self.applications: list[str] = []

    def filter_list(self) -> list[str]:
        return list(self.filters)

    def MeshSet(self) -> "_PyMeshLab._MeshSet":
        mesh_set = self._MeshSet(self)
        self.mesh_sets.append(mesh_set)
        return mesh_set


def _run_gate(**overrides: object) -> tuple[int, dict[str, object], str]:
    stream = io.StringIO()
    framebuffer = overrides.pop("framebuffer", _Framebuffer())
    context = overrides.pop("context", _Context(framebuffer))
    modern_gl = overrides.pop("moderngl_module", _ModernGL(context))
    values: dict[str, object] = {
        "platform_name": "darwin",
        "system_name": "Darwin",
        "machine_name": "arm64",
        "tetwild_loader": lambda: SimpleNamespace(
            tetrahedralize_mesh=lambda vertices, _faces, *_args: (
                vertices.copy(),
                np.asarray(((0, 1, 2, 3),), dtype=np.int64),
            )
        ),
        "pymeshlab_module": _PyMeshLab(),
        "moderngl_module": modern_gl,
        "output_stream": stream,
    }
    values.update(overrides)
    code = cli.macos_alpha_self_test(**values)
    text = stream.getvalue()
    return code, json.loads(text), text


class MacOSAlphaSelfTestTests(unittest.TestCase):
    def test_exact_hidden_flag(self) -> None:
        parser = cli.build_parser()

        self.assertNotIn(cli.MACOS_ALPHA_SELF_TEST_FLAG, parser.format_help())
        parsed = parser.parse_args([cli.MACOS_ALPHA_SELF_TEST_FLAG])
        self.assertTrue(parsed.macos_alpha_self_test)

    def test_main_routes_only_to_dedicated_gate(self) -> None:
        with (
            patch.object(cli, "macos_alpha_self_test", return_value=23) as gate,
            patch.object(cli, "self_test") as windows_gate,
        ):
            result = cli.main([cli.MACOS_ALPHA_SELF_TEST_FLAG])

        self.assertEqual(result, 23)
        gate.assert_called_once_with()
        windows_gate.assert_not_called()

    @unittest.skipIf(sys.platform == "darwin", "non-macOS entrypoint rejection")
    def test_entrypoint_emits_only_ascii_json_on_non_macos(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(FIXED_APP)

        completed = subprocess.run(
            [
                sys.executable,
                str(FIXED_APP / "TripoSpectrumMapper_fixed.py"),
                cli.MACOS_ALPHA_SELF_TEST_FLAG,
            ],
            cwd=FIXED_APP.parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertTrue(completed.stdout.startswith("{"), completed.stdout)
        completed.stdout.encode("ascii")
        data = json.loads(completed.stdout)
        self.assertFalse(data["ok"])
        self.assertEqual(data["gate"], cli.MACOS_ALPHA_SELF_TEST_FLAG)

    def test_existing_and_macos_self_tests_are_mutually_exclusive(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--self-test", cli.MACOS_ALPHA_SELF_TEST_FLAG])

        self.assertEqual(raised.exception.code, 2)

    def test_rejects_non_darwin_without_loading_native_dependencies(self) -> None:
        loader = Mock()
        filters = Mock()
        create_context = Mock()
        stream = io.StringIO()

        code = cli.macos_alpha_self_test(
            platform_name="win32",
            system_name="Windows",
            machine_name="AMD64",
            tetwild_loader=loader,
            pymeshlab_module=SimpleNamespace(filter_list=filters),
            moderngl_module=SimpleNamespace(
                create_standalone_context=create_context
            ),
            output_stream=stream,
        )
        data = json.loads(stream.getvalue())

        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertFalse(data["checks"]["platform"]["ok"])
        loader.assert_not_called()
        filters.assert_not_called()
        create_context.assert_not_called()

    def test_rejects_rosetta_x86_64(self) -> None:
        code, data, _text = _run_gate(machine_name="x86_64")

        self.assertEqual(code, 1)
        self.assertFalse(data["checks"]["platform"]["ok"])

    def test_all_native_and_gpu_gates_pass_on_darwin_arm64(self) -> None:
        framebuffer = _Framebuffer()
        context = _Context(framebuffer)
        modern_gl = _ModernGL(context)
        pymeshlab_module = _PyMeshLab()

        code, data, text = _run_gate(
            framebuffer=framebuffer,
            context=context,
            moderngl_module=modern_gl,
            pymeshlab_module=pymeshlab_module,
        )

        self.assertEqual(code, 0, data)
        self.assertTrue(data["ok"])
        self.assertEqual(
            data["schema"], "chromamatter.macos-alpha-self-test.v1"
        )
        self.assertEqual(data["gate"], cli.MACOS_ALPHA_SELF_TEST_FLAG)
        self.assertTrue(data["checks"]["pytetwild_wrapper"]["ok"])
        self.assertGreaterEqual(
            data["checks"]["pytetwild_wrapper"]["tetrahedron_count"],
            1,
        )
        self.assertTrue(data["checks"]["pymeshlab_filters"]["ok"])
        self.assertEqual(
            pymeshlab_module.applications,
            list(cli.MACOS_ALPHA_REQUIRED_PYMESHLAB_FILTERS),
        )
        self.assertEqual(len(pymeshlab_module.mesh_sets), 5)
        self.assertTrue(
            all(
                value["ok"]
                for value in data["checks"]["pymeshlab_filters"][
                    "applications"
                ].values()
            )
        )
        self.assertTrue(data["checks"]["moderngl_framebuffer"]["ok"])
        self.assertEqual(modern_gl.require, 330)
        self.assertEqual(context.request, ((1, 1), 4, "f1"))
        self.assertTrue(framebuffer.used)
        self.assertTrue(framebuffer.released)
        self.assertTrue(context.released)
        text.encode("ascii")

    def test_missing_one_required_pymeshlab_filter_fails(self) -> None:
        missing = cli.MACOS_ALPHA_REQUIRED_PYMESHLAB_FILTERS[-1]
        available = cli.MACOS_ALPHA_REQUIRED_PYMESHLAB_FILTERS[:-1]

        code, data, _text = _run_gate(
            pymeshlab_module=_PyMeshLab(filters=available)
        )

        self.assertEqual(code, 1)
        check = data["checks"]["pymeshlab_filters"]
        self.assertFalse(check["ok"])
        self.assertEqual(check["missing"], [missing])

    def test_one_required_filter_application_failure_fails(self) -> None:
        failing = cli.MACOS_ALPHA_REQUIRED_PYMESHLAB_FILTERS[2]
        pymeshlab_module = _PyMeshLab(failing_filter=failing)

        code, data, _text = _run_gate(
            pymeshlab_module=pymeshlab_module
        )

        self.assertEqual(code, 1)
        check = data["checks"]["pymeshlab_filters"]
        self.assertFalse(check["ok"])
        self.assertEqual(check["missing"], [])
        self.assertEqual(check["failed_applications"], [failing])
        self.assertFalse(check["applications"][failing]["ok"])
        self.assertIn(
            "native filter failed",
            check["applications"][failing]["status"],
        )

    def test_wrapper_without_tetrahedralize_entrypoint_fails(self) -> None:
        code, data, _text = _run_gate(
            tetwild_loader=lambda: SimpleNamespace()
        )

        self.assertEqual(code, 1)
        self.assertFalse(data["checks"]["pytetwild_wrapper"]["ok"])

    def test_tetwild_native_execution_failure_fails(self) -> None:
        def fail(*_args):
            raise RuntimeError("native tetrahedralization failed")

        code, data, _text = _run_gate(
            tetwild_loader=lambda: SimpleNamespace(tetrahedralize_mesh=fail)
        )

        self.assertEqual(code, 1)
        check = data["checks"]["pytetwild_wrapper"]
        self.assertFalse(check["ok"])
        self.assertIn("native tetrahedralization failed", check["status"])

    def test_framebuffer_read_mismatch_fails_and_releases_resources(self) -> None:
        framebuffer = _Framebuffer(pixel=bytes((0, 0, 0, 0)))
        context = _Context(framebuffer)

        code, data, _text = _run_gate(
            framebuffer=framebuffer,
            context=context,
            moderngl_module=_ModernGL(context),
        )

        self.assertEqual(code, 1)
        self.assertFalse(data["checks"]["moderngl_framebuffer"]["ok"])
        self.assertIn(
            "framebuffer clear/read mismatch",
            data["checks"]["moderngl_framebuffer"]["status"],
        )
        self.assertTrue(framebuffer.released)
        self.assertTrue(context.released)

    def test_failure_text_is_ascii_safe_json(self) -> None:
        code, data, text = _run_gate(
            tetwild_loader=lambda: (_ for _ in ()).throw(
                RuntimeError("読み込み失敗")
            )
        )

        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        text.encode("ascii")
        self.assertIn("\\u8aad", text)


if __name__ == "__main__":
    unittest.main()
