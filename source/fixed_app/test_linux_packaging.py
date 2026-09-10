from __future__ import annotations

import hashlib
from pathlib import Path
import re
import unittest


FIXED_APP = Path(__file__).resolve().parent
REPOSITORY = FIXED_APP.parents[1]
LOCK = FIXED_APP / "requirements-build-linux-x86_64.lock"
SPEC = FIXED_APP / "TripoSpectrumMapper_linux_x86_64.spec"
BUILD_SCRIPT = REPOSITORY / "BUILD_LINUX_X86_64.sh"
AUDIT_SCRIPT = REPOSITORY / "AUDIT_LINUX_APP.sh"
WORKFLOW = REPOSITORY / ".github" / "workflows" / "linux-x86_64-alpha.yml"


class LinuxDependencyLockTests(unittest.TestCase):
    def test_lock_is_binary_only_linux_x86_64_and_separate(self) -> None:
        text = LOCK.read_text(encoding="utf-8")
        self.assertIn("Ubuntu 22.04+ / CPython 3.13.14", text)
        self.assertIn("pytetwild==0.3.0", text)
        self.assertIn("pymeshlab==2025.7.post1", text)
        for non_linux in ("macholib", "msvc_runtime", "pefile", "pywin32-ctypes"):
            self.assertNotIn(non_linux, text)
        self.assertNotIn("requirements-build.lock\n", text)

        logical = text.replace("\\\n", " ")
        requirements = [
            line.strip()
            for line in logical.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(len(requirements), 22)
        for requirement in requirements:
            with self.subTest(requirement=requirement):
                self.assertRegex(requirement, r"^[A-Za-z0-9_.-]+==[^ ]+ ")
                self.assertRegex(requirement, r"--hash=sha256:[0-9a-f]{64}$")

    def test_existing_windows_and_macos_locks_remain_present(self) -> None:
        self.assertTrue((FIXED_APP / "requirements-build.lock").is_file())
        self.assertTrue(
            (FIXED_APP / "requirements-build-macos-arm64.lock").is_file()
        )


class LinuxPyInstallerSpecTests(unittest.TestCase):
    def test_spec_is_a_distinct_one_folder_linux_build(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn('LINUX_APP_NAME = "ChromaMatter-Linux-Alpha"', text)
        self.assertIn('platform.machine().casefold() != "x86_64"', text)
        self.assertIn("sys.version_info[:3] != (3, 13, 14)", text)
        self.assertIn('name=LINUX_APP_NAME', text)
        self.assertNotIn("BUNDLE(", text)
        self.assertNotIn('target_arch="arm64"', text)

    def test_spec_preserves_linux_pytetwild_and_pymeshlab_layout(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn('PYTETWILD_PACKAGE.parent / "pytetwild.libs"', text)
        self.assertIn('glob("PyfTetWildWrapper*.so")', text)
        self.assertIn('glob("*.so*")', text)
        self.assertIn('"pytetwild.libs"', text)
        self.assertIn('"pymeshlab"', text)
        self.assertIn('("9.0.4", "9.0.4"): ("libtcl9.0.so", "libtcl9tk9.0.so")', text)
        self.assertIn("VOLUME_BINARIES + TCL_TK_BINARIES", text)
        self.assertIn('"PIL._imagingtk"', text)
        self.assertIn('"PIL._tkinter_finder"', text)
        self.assertNotIn("*.pyd", text)
        self.assertNotIn(".dylibs", text)

    def test_spec_filters_private_metadata_and_platform_evidence(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("is_private_install_origin_metadata", text)
        self.assertIn('{"macos", "native-closure"}', text)
        self.assertIn('excludes=["resvg", "resvg._resvg"]', text)
        self.assertIn("distribution_license_datas", text)
        self.assertNotIn('"licenses" not in lower_parts', text)
        self.assertIn('filename.startswith(("license", "copying", "notice"))', text)

    def test_spec_binds_the_reviewed_tcl_tk_runtime_license_pair(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        expected = {
            "LICENSE_TCL_9_0_4.txt": (
                "c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16"
            ),
            "LICENSE_TK_9_0_4.txt": (
                "2cde822b93ca16ae535c954b7dfe658b4ad10df2a193628d1b358f1765e8b198"
            ),
        }
        self.assertIn("TK_PATCHLEVEL", text)
        self.assertIn('(\"8.6.18\", \"8.6.18\")', text)
        self.assertIn('(\"9.0.4\", \"9.0.4\")', text)
        for filename, digest in expected.items():
            with self.subTest(filename=filename):
                path = REPOSITORY / "licenses" / filename
                self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                self.assertIn(filename, text)


class LinuxBuildAutomationTests(unittest.TestCase):
    def test_build_and_audit_are_fail_closed_and_diagnostics_only(self) -> None:
        build = BUILD_SCRIPT.read_text(encoding="utf-8")
        audit = AUDIT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('[[ "$(uname -m)" == "x86_64" ]]', build)
        self.assertIn('[[ "$PYTHON_VERSION" == "3.13.14" ]]', build)
        self.assertIn("os.path.abspath(sys.executable)", build)
        self.assertNotIn("os.path.realpath(sys.executable)", build)
        self.assertIn('cd "$SCRIPT_DIR"', build)
        self.assertIn("os.chdir(repository)", build)
        self.assertIn("Linux source test escaped the exact snapshot", build)
        self.assertIn("glibc 2.35+", build)
        self.assertIn("patchelf --set-rpath", build)
        self.assertIn("patchelf --remove-rpath", build)
        self.assertIn("ELF files with absolute search paths sanitized", build)
        self.assertIn("--linux-alpha-self-test", build)
        self.assertIn("AUDIT_LINUX_APP.sh", build)
        self.assertIn('"$APP_EXECUTABLE" --self-test', build)
        self.assertIn("--ui-smoke", build)
        self.assertIn("timeout=45", build)
        self.assertIn("Tcl/Tk: $TCL_PATCHLEVEL / $TK_PATCHLEVEL", build)
        self.assertIn("resolve_ui_font", build)
        self.assertIn("Linux UI font / Japanese glyph width", build)
        self.assertIn("xfonts-intl-japanese", build)
        self.assertIn("CHROMAMATTER_LINUX_BUILD_SOURCE_ROOT", build)
        self.assertIn("CHROMAMATTER_LINUX_BUILD_PYTHON_PREFIX", build)
        self.assertNotIn("zip ", build.casefold())
        self.assertNotIn("upload-release-asset", build.casefold())
        self.assertNotIn("gh release", build.casefold())

        workflow = WORKFLOW.read_text(encoding="utf-8")
        for package in (
            "fonts-noto-cjk",
            "xfonts-base",
            "xfonts-intl-japanese",
            "xfonts-intl-japanese-big",
        ):
            with self.subTest(font_package=package):
                self.assertIn(package, workflow)

        self.assertIn("readelf -h", audit)
        self.assertIn("ldd \"$candidate\"", audit)
        self.assertIn('LD_LIBRARY_PATH="$BUNDLED_LIBRARY_ROOT"', audit)
        self.assertIn("-u LD_AUDIT", audit)
        self.assertIn("Non-package-relative ELF search path", audit)
        self.assertIn("ELF dependency resolved outside package/system roots", audit)
        self.assertIn("Non-x86_64 ELF file", audit)
        self.assertIn("Unresolved ELF dependency", audit)
        self.assertIn("Symlink escapes package", audit)
        self.assertIn("direct_url.json", audit)
        self.assertIn("Build-host absolute path leaked", audit)
        self.assertIn("CHROMAMATTER_LINUX_BUILD_SOURCE_ROOT", audit)
        self.assertIn("CHROMAMATTER_LINUX_BUILD_PYTHON_PREFIX", audit)
        runner_workspace = "/" + "home/runner/work/"
        self.assertNotIn(f'    "{runner_workspace}",', audit)
        self.assertIn("Build-host glibc:", audit)
        self.assertIn("an Ubuntu 22.04 compatibility claim requires", audit)
        self.assertIn("Public or tester distribution approved: no", audit)

    def test_workflow_uploads_reports_but_never_the_application(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-22.04", text)
        self.assertIn("uses: actions/setup-python@v7", text)
        self.assertIn('python-version: "3.13.14"', text)
        self.assertIn("architecture: x64", text)
        self.assertIn("xdg-utils", text)
        self.assertIn("--require-hashes", text)
        self.assertIn("--only-binary=:all:", text)
        self.assertIn("BUILD_LINUX_X86_64.sh", text)
        self.assertIn("actions/upload-artifact@v4", text)
        self.assertIn(
            "path: ${{ runner.temp }}/chromamatter-linux-diagnostics/",
            text,
        )
        self.assertNotIn("  pull_request:\n", text)
        self.assertNotIn("upload-release-asset", text.casefold())
        self.assertNotIn("softprops/action-gh-release", text.casefold())
        upload_blocks = re.findall(
            r"uses: actions/upload-artifact@v4(?P<body>.*?)(?=\n\s*- name:|\Z)",
            text,
            flags=re.DOTALL,
        )
        self.assertEqual(len(upload_blocks), 1)
        self.assertNotIn("/dist", upload_blocks[0])
        self.assertNotIn("ChromaMatter-Linux-Alpha", upload_blocks[0])


if __name__ == "__main__":
    unittest.main()
