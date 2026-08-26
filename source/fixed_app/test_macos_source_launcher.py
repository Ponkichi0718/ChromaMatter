from __future__ import annotations

import re
from pathlib import Path
import shutil
import subprocess
import unittest


FIXED_APP = Path(__file__).resolve().parent
REPOSITORY = FIXED_APP.parents[1]
LAUNCHER = REPOSITORY / "START_MACOS_SOURCE_ALPHA.command"
RUNTIME_LOCK = FIXED_APP / "requirements-runtime-macos-arm64.lock"
BUILD_LOCK = FIXED_APP / "requirements-build-macos-arm64.lock"

EXPECTED_RUNTIME_PACKAGES = {
    "glcontext",
    "manifold3d",
    "mapbox-earcut",
    "moderngl",
    "networkx",
    "numpy",
    "packaging",
    "pillow",
    "pymeshlab",
    "pytetwild",
    "resvg",
    "rtree",
    "scipy",
    "shapely",
    "tetgen",
    "trimesh",
}
BUILD_ONLY_PACKAGES = {
    "altgraph",
    "macholib",
    "pip",
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "setuptools",
    "wheel",
}
REQUIREMENT_RE = re.compile(
    r"^(?P<name>[a-z0-9][a-z0-9._-]*)==(?P<version>[^ \\]+) \\\n"
    r"    --hash=sha256:(?P<sha>[0-9a-f]{64})$",
    re.MULTILINE,
)


def _requirements(path: Path) -> dict[str, tuple[str, str]]:
    return {
        match.group("name").lower(): (
            match.group("version"),
            match.group("sha"),
        )
        for match in REQUIREMENT_RE.finditer(path.read_text(encoding="utf-8"))
    }


class MacOSSourceLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")
        cls.runtime = _requirements(RUNTIME_LOCK)
        cls.build = _requirements(BUILD_LOCK)

    def test_runtime_lock_is_exact_reviewed_build_lock_subset(self) -> None:
        self.assertEqual(set(self.runtime), EXPECTED_RUNTIME_PACKAGES)
        self.assertTrue(BUILD_ONLY_PACKAGES.isdisjoint(self.runtime))
        for name, identity in self.runtime.items():
            self.assertIn(name, self.build)
            self.assertEqual(identity, self.build[name])

    def test_official_python_installer_is_version_and_sha_locked(self) -> None:
        self.assertIn('PYTHON_VERSION_REQUIRED="3.13.14"', self.launcher)
        self.assertIn(
            'PYTHON_INSTALLER_URL="https://www.python.org/ftp/python/3.13.14/'
            'python-3.13.14-macos11.pkg"',
            self.launcher,
        )
        self.assertIn(
            'PYTHON_INSTALLER_SHA256="8e58affb218c155a1dfdc27b291f8171'
            '29669f8760e7a297adb2e4439ba5d2e8"',
            self.launcher,
        )
        self.assertLess(
            self.launcher.index('shasum -a 256 "$TEMP_DOWNLOAD"'),
            self.launcher.index('open "$INSTALLER_PATH"'),
        )
        self.assertIn('pkgutil --check-signature "$TEMP_DOWNLOAD"', self.launcher)

    def test_source_runtime_stays_in_application_support(self) -> None:
        self.assertIn(
            'Library/Application Support/ChromaMatter Source Alpha',
            self.launcher,
        )
        self.assertIn('VENV_DIR="$SUPPORT_ROOT/venv-$PYTHON_VERSION_REQUIRED"', self.launcher)
        self.assertIn('CHROMAMATTER_DATA_DIRECTORY="$PROFILE_DIR"', self.launcher)
        self.assertIn("--require-hashes", self.launcher)
        self.assertIn("--only-binary=:all:", self.launcher)
        self.assertIn("--no-deps", self.launcher)
        self.assertIn("importlib.metadata.version(name)", self.launcher)

    def test_ci_overrides_and_self_test_only_mode_are_explicit(self) -> None:
        self.assertIn(
            'SOURCE_ALPHA_TAG="v0.8beta-macos-source-alpha1"',
            self.launcher,
        )
        self.assertIn('printf \'Source tester tag: %s\\n\'', self.launcher)
        self.assertIn("CHROMAMATTER_PYTHON", self.launcher)
        self.assertIn("CHROMAMATTER_ALPHA_HOME", self.launcher)
        self.assertIn("--self-test-only", self.launcher)
        self.assertIn("if ((SELF_TEST_ONLY)); then", self.launcher)
        self.assertLess(
            self.launcher.index('payload.get("ok") is not True'),
            self.launcher.index("if ((SELF_TEST_ONLY)); then"),
        )
        self.assertLess(
            self.launcher.index("if ((SELF_TEST_ONLY)); then"),
            self.launcher.index('exec "$VENV_PYTHON" "$ENTRYPOINT"'),
        )

    def test_launcher_has_no_security_or_packaged_app_bypass(self) -> None:
        executable_lines = "\n".join(
            line for line in self.launcher.splitlines() if not line.lstrip().startswith("#")
        )
        for forbidden in (
            r"(?m)^\s*sudo\b",
            r"(?m)^\s*spctl\b",
            r"(?m)^\s*xattr\b",
            r"(?m)^\s*installer\s+-pkg\b",
            r"\.app\.zip",
            r"tester ZIP",
        ):
            self.assertIsNone(re.search(forbidden, executable_lines, re.IGNORECASE))

    def test_cc0_fixture_and_native_render_gate_precede_gui(self) -> None:
        self.assertIn(
            'PUBLIC_GLB_SHA256="1b6092448e62a93f5e29a9c6dda1265'
            'a7a2179c2eacd293f7d8f02d1f268c563"',
            self.launcher,
        )
        generator = self.launcher.index('"$VENV_PYTHON" "$GLB_GENERATOR"')
        gate = self.launcher.index("--macos-alpha-self-test")
        launch = self.launcher.index('exec "$VENV_PYTHON" "$ENTRYPOINT"')
        self.assertLess(generator, gate)
        self.assertLess(gate, launch)
        self.assertIn('payload.get("ok") is not True', self.launcher)

    def test_shell_syntax_when_bash_is_available(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is not available on this test host")
        completed = subprocess.run(
            [bash, "-n", str(LAUNCHER)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
