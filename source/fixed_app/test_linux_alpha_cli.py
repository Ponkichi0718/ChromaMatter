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
        self.released = False

    def use(self) -> None:
        pass

    def clear(self, *_rgba: float) -> None:
        pass

    def read(self, *, components: int, dtype: str) -> bytes:
        if components != 4 or dtype != "f1":
            raise AssertionError("unexpected framebuffer contract")
        return self.pixel

    def release(self) -> None:
        self.released = True


class _Context:
    version_code = 450

    def __init__(self, framebuffer: _Framebuffer) -> None:
        self.framebuffer = framebuffer
        self.released = False

    def simple_framebuffer(self, size, *, components: int, dtype: str):
        if size != (1, 1) or components != 4 or dtype != "f1":
            raise AssertionError("unexpected framebuffer request")
        return self.framebuffer

    def release(self) -> None:
        self.released = True


class _ModernGL:
    def __init__(self) -> None:
        self.framebuffer = _Framebuffer()
        self.context = _Context(self.framebuffer)
        self.require = None

    def create_standalone_context(self, *, require: int):
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

        def add_mesh(self, mesh, _label: str) -> None:
            self.mesh = mesh

        def apply_filter(self, name: str) -> None:
            if self.mesh is None:
                raise AssertionError("filter applied without a mesh")
            self.owner.applications.append(name)

    def __init__(self) -> None:
        self.applications: list[str] = []

    def filter_list(self) -> list[str]:
        return list(cli.MACOS_ALPHA_REQUIRED_PYMESHLAB_FILTERS)

    def MeshSet(self):
        return self._MeshSet(self)


def _passing_gate(**overrides: object):
    stream = io.StringIO()
    modern_gl = _ModernGL()
    values: dict[str, object] = {
        "platform_name": "linux",
        "system_name": "Linux",
        "machine_name": "x86_64",
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
    code = cli.linux_alpha_self_test(**values)
    return code, json.loads(stream.getvalue()), modern_gl, stream.getvalue()


class LinuxAlphaSelfTestTests(unittest.TestCase):
    def test_hidden_flag_and_main_routing(self) -> None:
        parser = cli.build_parser()
        self.assertNotIn(cli.LINUX_ALPHA_SELF_TEST_FLAG, parser.format_help())
        self.assertTrue(
            parser.parse_args(
                [cli.LINUX_ALPHA_SELF_TEST_FLAG]
            ).linux_alpha_self_test
        )
        with patch.object(cli, "linux_alpha_self_test", return_value=19) as gate:
            self.assertEqual(cli.main([cli.LINUX_ALPHA_SELF_TEST_FLAG]), 19)
        gate.assert_called_once_with()

    @unittest.skipIf(sys.platform.startswith("linux"), "non-Linux rejection")
    def test_entrypoint_rejects_non_linux_with_ascii_json_only(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(FIXED_APP)
        completed = subprocess.run(
            [
                sys.executable,
                str(FIXED_APP / "TripoSpectrumMapper_fixed.py"),
                cli.LINUX_ALPHA_SELF_TEST_FLAG,
            ],
            cwd=FIXED_APP.parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        completed.stdout.encode("ascii")
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["gate"], cli.LINUX_ALPHA_SELF_TEST_FLAG)

    def test_self_test_flags_are_mutually_exclusive(self) -> None:
        for arguments in (
            ["--self-test", cli.LINUX_ALPHA_SELF_TEST_FLAG],
            [
                cli.MACOS_ALPHA_SELF_TEST_FLAG,
                cli.LINUX_ALPHA_SELF_TEST_FLAG,
            ],
        ):
            with self.subTest(arguments=arguments):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        cli.main(arguments)
                self.assertEqual(raised.exception.code, 2)

    def test_rejects_other_platform_without_loading_native_dependencies(self) -> None:
        loader = Mock()
        filters = Mock()
        create_context = Mock()
        stream = io.StringIO()
        code = cli.linux_alpha_self_test(
            platform_name="darwin",
            system_name="Darwin",
            machine_name="arm64",
            tetwild_loader=loader,
            pymeshlab_module=SimpleNamespace(filter_list=filters),
            moderngl_module=SimpleNamespace(
                create_standalone_context=create_context
            ),
            output_stream=stream,
        )
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stream.getvalue())["ok"])
        loader.assert_not_called()
        filters.assert_not_called()
        create_context.assert_not_called()

    def test_rejects_linux_arm64(self) -> None:
        code, payload, _modern_gl, _text = _passing_gate(
            machine_name="aarch64"
        )
        self.assertEqual(code, 1)
        self.assertFalse(payload["checks"]["platform"]["ok"])

    def test_all_real_operation_contracts_pass_for_linux_x86_64(self) -> None:
        pymeshlab_module = _PyMeshLab()
        code, payload, modern_gl, text = _passing_gate(
            pymeshlab_module=pymeshlab_module
        )
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["schema"], "chromamatter.linux-alpha-self-test.v1"
        )
        self.assertTrue(payload["checks"]["pytetwild_wrapper"]["ok"])
        self.assertTrue(payload["checks"]["pymeshlab_filters"]["ok"])
        self.assertTrue(payload["checks"]["moderngl_framebuffer"]["ok"])
        self.assertEqual(
            pymeshlab_module.applications,
            list(cli.MACOS_ALPHA_REQUIRED_PYMESHLAB_FILTERS),
        )
        self.assertEqual(modern_gl.require, 330)
        self.assertTrue(modern_gl.framebuffer.released)
        self.assertTrue(modern_gl.context.released)
        text.encode("ascii")

    def test_failure_message_remains_ascii_safe_json(self) -> None:
        code, payload, _modern_gl, text = _passing_gate(
            tetwild_loader=lambda: (_ for _ in ()).throw(
                RuntimeError("読み込み失敗")
            )
        )
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        text.encode("ascii")
        self.assertIn("\\u8aad", text)


if __name__ == "__main__":
    unittest.main()
