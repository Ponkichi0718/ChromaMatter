from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest


FIXED_APP = Path(__file__).resolve().parent
REPOSITORY = FIXED_APP.parents[1]
STAGER = REPOSITORY / "tooling" / "stage_macos_source_app.py"
WORKFLOW = REPOSITORY / ".github" / "workflows" / "macos-source-alpha.yml"
TEST_GUIDE = REPOSITORY / "publication" / "MACOS_SOURCE_APP_TESTING_EN.md"
APP_NAME = "ChromaMatter Source Alpha.app"
FORBIDDEN_MAGIC = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
    b"\x7fELF",
}


class MacOSSourceBackedAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        head = subprocess.run(
            ["git", "-C", os.fspath(REPOSITORY), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
        if head.returncode != 0:
            raise unittest.SkipTest("source-app staging tests require a Git worktree")
        cls.source_commit = head.stdout.strip()
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.app = cls.root / APP_NAME
        completed = subprocess.run(
            [
                sys.executable,
                os.fspath(STAGER),
                "stage",
                "--repository-root",
                os.fspath(REPOSITORY),
                "--output",
                os.fspath(cls.app),
                "--source-commit",
                cls.source_commit,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
        cls.stage_result = json.loads(completed.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_bundle_is_finder_app_with_source_alpha_identity(self) -> None:
        plist = plistlib.loads((self.app / "Contents" / "Info.plist").read_bytes())
        self.assertEqual(plist["CFBundlePackageType"], "APPL")
        self.assertEqual(plist["CFBundleDisplayName"], "ChromaMatter Source Alpha")
        self.assertEqual(
            plist["CFBundleIdentifier"],
            "io.github.ponkichi0718.chromamatter.source-alpha",
        )
        self.assertEqual(plist["LSMinimumSystemVersion"], "15.0")
        self.assertEqual(plist["LSArchitecturePriority"], ["arm64"])
        self.assertTrue((self.app / "Contents" / "Resources" / "AppIcon.icns").is_file())

    def test_wrapper_opens_existing_launcher_in_terminal_without_bypasses(self) -> None:
        wrapper = (
            self.app / "Contents" / "MacOS" / "ChromaMatterSourceAlpha"
        ).read_text(encoding="utf-8")
        self.assertIn("exec /usr/bin/open -a Terminal", wrapper)
        self.assertIn('exec "$SOURCE_LAUNCHER" "$@"', wrapper)
        self.assertIn("START_MACOS_SOURCE_ALPHA.command", wrapper)
        executable = "\n".join(
            line for line in wrapper.splitlines() if not line.lstrip().startswith("#")
        )
        for forbidden in (
            r"(?m)^\s*sudo\b",
            r"(?m)^\s*spctl\b",
            r"(?m)^\s*xattr\b",
            r"(?m)^\s*installer\s+-pkg\b",
            r"(?m)^\s*codesign\b",
        ):
            self.assertIsNone(re.search(forbidden, executable, re.IGNORECASE))

    def test_bundle_carries_production_source_but_not_tests_or_build_recipe(self) -> None:
        source_root = (
            self.app / "Contents" / "Resources" / "ChromaMatterSource"
        )
        launcher = source_root / "START_MACOS_SOURCE_ALPHA.command"
        self.assertTrue(launcher.is_file())
        for required in (
            "source/fixed_app/TripoSpectrumMapper_fixed.py",
            "source/fixed_app/spectrum_mapper/gui.py",
            "source/fixed_app/assets/mixer_model.npz",
            "source/fixed_app/resources/filament_db/filament_color_database_2026-08.sqlite",
            "samples/generate_macos_alpha_test_glb.py",
            "licenses/GPL-3.0.txt",
            "LICENSE",
        ):
            with self.subTest(required=required):
                self.assertTrue(source_root.joinpath(*required.split("/")).is_file())
        self.assertFalse(
            (source_root / "source" / "fixed_app" / "test_macos_packaging.py").exists()
        )
        self.assertFalse(
            (source_root / "source" / "fixed_app" / "TripoSpectrumMapper_macos_arm64.spec").exists()
        )
        self.assertFalse((source_root / "source" / "fixed_app" / "public_binary").exists())

    def test_stage_is_bound_to_head_and_uses_committed_source_bytes(self) -> None:
        mismatched = self.root / "mismatch" / APP_NAME
        completed = subprocess.run(
            [
                sys.executable,
                os.fspath(STAGER),
                "stage",
                "--repository-root",
                os.fspath(REPOSITORY),
                "--output",
                os.fspath(mismatched),
                "--source-commit",
                "f" * 40,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must equal repository HEAD", completed.stderr)

        committed_launcher = subprocess.run(
            [
                "git",
                "-C",
                os.fspath(REPOSITORY),
                "show",
                f"{self.source_commit}:START_MACOS_SOURCE_ALPHA.command",
            ],
            capture_output=True,
            check=True,
        ).stdout
        bundled_launcher = (
            self.app
            / "Contents"
            / "Resources"
            / "ChromaMatterSource"
            / "START_MACOS_SOURCE_ALPHA.command"
        ).read_bytes()
        self.assertEqual(bundled_launcher, committed_launcher)

    def test_manifest_is_exact_and_declares_no_bundled_runtime(self) -> None:
        path = (
            self.app
            / "Contents"
            / "Resources"
            / "SOURCE_BACKED_APP_MANIFEST.json"
        )
        manifest = json.loads(path.read_text(encoding="ascii"))
        self.assertEqual(manifest["schema"], "chromamatter.macos-source-backed-app.v1")
        self.assertEqual(manifest["source_commit"], self.source_commit)
        self.assertTrue(manifest["source_backed"])
        self.assertFalse(manifest["bundled_python_runtime"])
        self.assertFalse(manifest["bundled_third_party_runtime_binaries"])
        self.assertFalse(manifest["prebuilt_app_distribution_gate_bypassed"])
        self.assertTrue(manifest["first_launch_opens_terminal"])
        self.assertEqual(
            self.stage_result["status"], "source-backed-app-audit-passed"
        )
        self.assertEqual(self.stage_result["native_runtime_binary_count"], 0)

    def test_every_payload_is_regular_and_contains_no_native_binary_magic(self) -> None:
        forbidden_suffixes = {
            ".a",
            ".bundle",
            ".dll",
            ".dylib",
            ".exe",
            ".framework",
            ".o",
            ".pkg",
            ".pyc",
            ".pyd",
            ".so",
            ".whl",
        }
        for path in self.app.rglob("*"):
            if path.is_dir():
                continue
            relative = path.relative_to(self.app).as_posix()
            with self.subTest(path=relative):
                self.assertFalse(path.is_symlink())
                self.assertTrue(path.is_file())
                self.assertNotIn(path.suffix.casefold(), forbidden_suffixes)
                self.assertNotIn(path.read_bytes()[:4], FORBIDDEN_MAGIC)

    def test_independent_audit_passes_and_tamper_fails(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                os.fspath(STAGER),
                "audit",
                "--app-bundle",
                os.fspath(self.app),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        target = (
            self.app
            / "Contents"
            / "Resources"
            / "ChromaMatterSource"
            / "FEATURES_EN.md"
        )
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"\n")
            rejected = subprocess.run(
                [
                    sys.executable,
                    os.fspath(STAGER),
                    "audit",
                    "--app-bundle",
                    os.fspath(self.app),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("manifest mismatch", rejected.stderr)
        finally:
            target.write_bytes(original)

    def test_ci_exercises_embedded_launcher_and_fresh_archive_audit(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("tooling/stage_macos_source_app.py stage", workflow)
        self.assertGreaterEqual(
            workflow.count("tooling/stage_macos_source_app.py audit"),
            2,
        )
        self.assertGreaterEqual(
            workflow.count('Contents/MacOS/ChromaMatterSourceAlpha" --self-test-only'),
            1,
        )
        self.assertIn("ditto -c -k --keepParent", workflow)
        self.assertIn("ditto -x -k", workflow)
        self.assertIn("README_INSTALL_AND_TEST_EN.md", workflow)
        self.assertGreaterEqual(
            workflow.count(
                "CHROMAMATTER_ALPHA_HOME: ${{ runner.temp }}/chromamatter-source-alpha"
            ),
            3,
        )
        self.assertIn("ChromaMatter-Public-Four-Color-Test.glb.sha256", workflow)
        self.assertIn("SOURCE_COMMIT.txt", workflow)
        self.assertIn("workflow_commit != root_commit", workflow)
        self.assertIn("root_commit != manifest_commit", workflow)
        self.assertIn("ChromaMatter-0.8beta-macos-source-app-alpha1.zip", workflow)
        self.assertIn("ChromaMatter-0.8beta-macos-source-app-alpha1.zip.sha256", workflow)
        self.assertIn("SHA256SUMS-macos-source-app-alpha1.txt", workflow)
        self.assertIn("open -W -n", workflow)
        self.assertIn('--env "CHROMAMATTER_ALPHA_HOME=', workflow)
        self.assertIn('--env "CHROMAMATTER_PYTHON=', workflow)
        self.assertIn('"$fresh_app" --args --self-test-only', workflow)
        self.assertIn(
            "LaunchServices source-app self-test did not report ok=true",
            workflow,
        )
        self.assertIn("upload_source_app_alpha:", workflow)
        self.assertIn('"v0.8beta-macos-source-app-alpha*"', workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("inputs.upload_source_app_alpha == true", workflow)
        self.assertIn("no bundled Python/runtime/Mach-O", workflow)
        self.assertIn("not evidence for the frozen prebuilt", workflow)
        self.assertNotIn("gh release", workflow.casefold())

    def test_english_guide_matches_the_source_backed_package(self) -> None:
        guide = TEST_GUIDE.read_text(encoding="utf-8")
        compact = " ".join(guide.split())
        self.assertIn("ChromaMatter Source Alpha.app", guide)
        self.assertIn("ChromaMatter-0.8beta-macos-source-app-alpha1.zip", guide)
        self.assertIn("README_INSTALL_AND_TEST_EN.md", guide)
        self.assertIn("SOURCE_COMMIT.txt", guide)
        self.assertIn("source-backed", guide.casefold())
        self.assertIn("does not contain a prebuilt Python runtime", compact)
        self.assertIn("Control-click", guide)
        self.assertIn("10-minute basic test", guide)
        self.assertIn("Do not disable Gatekeeper", guide)
        self.assertIn("Do not redistribute", guide)


if __name__ == "__main__":
    unittest.main()
