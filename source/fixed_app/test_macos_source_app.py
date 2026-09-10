from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile

from tooling import stage_macos_source_app as app_tool


REPOSITORY = Path(__file__).resolve().parents[2]


class MacOSSourceBackedAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is required for exact-source fixtures")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.repository = cls.root / "repository"
        cls.repository.mkdir()
        # Commit a synthetic fixture only: never stage or commit the owner's tree.
        fixture = {
            ".gitattributes": b"*.command text eol=lf\n",
            "LICENSE": b"Synthetic licence fixture\n",
            "FEATURES_EN.md": b"Synthetic features\n",
            "source/fixed_app/TripoSpectrumMapper_fixed.py": b"# fixture entrypoint\n",
            "source/fixed_app/spectrum_mapper/cli.py": b"# fixture cli\n",
            "source/fixed_app/spectrum_mapper/export_validation.py": b"# current policy fixture\n",
            "source/fixed_app/assets/mixer_model.npz": b"non-native asset fixture\n",
            "source/fixed_app/test_private.py": b"# never package tests\n",
            "source/fixed_app/public_binary/DemoData/private.glb": b"must not package\n",
            "samples/generate_macos_alpha_test_glb.py": b"# rights-safe generator fixture\n",
        }
        for relative in (app_tool.SOURCE_LAUNCHER, app_tool.TEST_GUIDE,
                         "source/fixed_app/requirements-runtime-macos-arm64.lock",
                         "source/fixed_app/assets/obj_adjuster_icon.png"):
            fixture[relative] = (REPOSITORY / relative).read_bytes()
        for relative, payload in fixture.items():
            target = cls.repository / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        cls.git("init", "--quiet")
        cls.git("config", "core.autocrlf", "false")
        cls.git("add", ".")
        cls.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "commit", "--quiet", "-m", "Synthetic source-app fixture")
        cls.source_commit = cls.git("rev-parse", "HEAD").strip()
        cls.app = cls.root / "stage" / app_tool.APP_NAME
        app_tool.stage(cls.repository, cls.app, cls.source_commit)

    @classmethod
    def git(cls, *arguments: str) -> str:
        return subprocess.run(["git", "-C", str(cls.repository), *arguments],
                              capture_output=True, text=True, check=True).stdout

    def copied_app(self, root: Path) -> Path:
        app = root / app_tool.APP_NAME
        shutil.copytree(self.app, app)
        return app

    def test_finder_identity_and_truthful_source_only_scope(self) -> None:
        plist = plistlib.loads((self.app / "Contents/Info.plist").read_bytes())
        self.assertEqual(plist["CFBundlePackageType"], "APPL")
        self.assertEqual(plist["CFBundleShortVersionString"], "0.9.0")
        self.assertEqual(plist["CFBundleVersion"], "900")
        self.assertEqual(plist["LSMinimumSystemVersion"], "15.0")
        self.assertEqual(plist["LSArchitecturePriority"], ["arm64"])
        report = app_tool.audit(self.app)
        self.assertEqual(report["native_runtime_binary_count"], 0)
        self.assertFalse(report["demo_data_bundled"])
        self.assertEqual(report["native_validation_status"], "not-run-on-macos-for-this-source-commit")
        notice = (self.app / "Contents/Resources" / app_tool.NOTICE_NAME).read_text()
        self.assertIn("not been runtime-tested on macOS", notice)
        self.assertNotIn("153-file", notice)

    def test_committed_current_modules_but_no_tests_demo_or_runtime(self) -> None:
        source = self.app / "Contents/Resources" / app_tool.SOURCE_DIRECTORY
        committed_launcher = subprocess.check_output([
            "git", "-C", str(self.repository), "show",
            f"{self.source_commit}:{app_tool.SOURCE_LAUNCHER}",
        ])
        self.assertEqual((source / app_tool.SOURCE_LAUNCHER).read_bytes(),
                         committed_launcher)
        self.assertTrue((source / "source/fixed_app/spectrum_mapper/export_validation.py").is_file())
        self.assertFalse((source / "source/fixed_app/test_private.py").exists())
        self.assertFalse((source / "source/fixed_app/public_binary").exists())
        for path in self.app.rglob("*"):
            if path.is_file():
                self.assertNotIn(path.suffix.casefold(), app_tool.FORBIDDEN_SUFFIXES)

    def test_unsafe_paths_and_unicode_keys(self) -> None:
        for relative in ("../bad", "/bad", "C:/bad", "a\\bad", "a/../bad", "a//bad", "a/./bad", "line\nbad"):
            with self.subTest(relative=relative), self.assertRaises(app_tool.SourceAppError):
                app_tool._safe_relative(relative)
        self.assertEqual(app_tool._normalized_path_key("e\u0301.txt"),
                         app_tool._normalized_path_key("\u00e9.txt"))

    def test_wrapper_opens_terminal_without_security_bypass(self) -> None:
        text = (self.app / "Contents/MacOS" / app_tool.EXECUTABLE_NAME).read_text()
        self.assertIn('exec "$SOURCE_LAUNCHER" "$@"', text)
        self.assertIn("exec /usr/bin/open -a Terminal", text)
        executable = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
        for command in ("sudo ", "spctl ", "xattr ", "codesign ", "installer -pkg"):
            self.assertNotIn(command, executable)

    def test_nonhead_and_existing_output_are_rejected(self) -> None:
        with self.assertRaisesRegex(app_tool.SourceAppError, "must equal repository HEAD"):
            app_tool.stage(self.repository, self.root / "invalid" / app_tool.APP_NAME, "f" * 40)
        with self.assertRaisesRegex(app_tool.SourceAppError, "existing app bundle"):
            app_tool.stage(self.repository, self.app, self.source_commit)

    def test_dirty_and_untracked_source_are_rejected(self) -> None:
        target = self.repository / "FEATURES_EN.md"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"uncommitted\n")
            with self.assertRaisesRegex(app_tool.SourceAppError, "clean committed"):
                app_tool.stage(self.repository, self.root / "dirty" / app_tool.APP_NAME, self.source_commit)
        finally:
            target.write_bytes(original)
        untracked = self.repository / "new_feature.py"
        try:
            untracked.write_text("# untracked\n")
            with self.assertRaisesRegex(app_tool.SourceAppError, "clean committed"):
                app_tool.stage(self.repository, self.root / "untracked" / app_tool.APP_NAME, self.source_commit)
        finally:
            untracked.unlink()

    def test_added_native_payloads_or_demo_fail(self) -> None:
        for relative, payload in (("native.data", b"\x7fELFfake"),
                                  ("library.data", b"\xcf\xfa\xed\xfefake"),
                                  ("runtime.whl", b"wheel"),
                                  ("DemoData/model.glb", b"glTF")):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as raw:
                app = self.copied_app(Path(raw))
                target = app / "Contents/Resources" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                with self.assertRaises(app_tool.SourceAppError):
                    app_tool.audit(app)

    def test_tampering_and_fabricated_native_validation_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            app = self.copied_app(Path(raw))
            target = app / "Contents/Resources" / app_tool.SOURCE_DIRECTORY / "FEATURES_EN.md"
            target.write_bytes(target.read_bytes() + b"changed")
            with self.assertRaisesRegex(app_tool.SourceAppError, "manifest mismatch"):
                app_tool.audit(app)
        with tempfile.TemporaryDirectory() as raw:
            app = self.copied_app(Path(raw))
            target = app / "Contents/Resources" / app_tool.MANIFEST_NAME
            manifest = json.loads(target.read_text())
            manifest["native_validation_status"] = "passed"
            target.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(app_tool.SourceAppError, "native validation scope"):
                app_tool.audit(app)

    def test_cross_host_zip_preserves_modes_fresh_audit_and_no_demo(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            archive = Path(raw) / (app_tool.PACKAGE_ROOT + ".zip")
            report = app_tool.package(self.repository, archive, self.source_commit)
            self.assertEqual(report["fresh_extract_audit"], "passed")
            self.assertFalse(report["demo_data_bundled"])
            self.assertEqual(report["archive_sha256"], app_tool._sha256(archive))
            with zipfile.ZipFile(archive) as zipped:
                self.assertIsNone(zipped.testzip())
                executable_count = 0
                for entry in zipped.infolist():
                    self.assertNotIn("demodata", entry.filename.casefold())
                    self.assertEqual(entry.create_system, 3)
                    self.assertEqual(stat.S_IFMT(entry.external_attr >> 16), stat.S_IFREG)
                    if Path(entry.filename).name in {app_tool.EXECUTABLE_NAME, app_tool.SOURCE_LAUNCHER}:
                        self.assertEqual(stat.S_IMODE(entry.external_attr >> 16), 0o755)
                        executable_count += 1
                self.assertEqual(executable_count, 2)
                self.assertIn(app_tool.PACKAGE_ROOT + "/README_INSTALL_AND_TEST_EN.md", zipped.namelist())
            with self.assertRaisesRegex(app_tool.SourceAppError, "fixed fresh"):
                app_tool.package(self.repository, archive, self.source_commit)

    def test_guide_explains_current_ui_and_no_demo_or_native_claim(self) -> None:
        guide = (REPOSITORY / app_tool.TEST_GUIDE).read_text(encoding="utf-8")
        for text in ("0.9", "Output Settings", "Solidify", "Flat Four", "High",
                     "Ignore defects (not", "not bundled", "https://chromamatter.app/download",
                     "native testing", "Do not disable Gatekeeper", "Slice Preview"):
            self.assertIn(text, guide)


if __name__ == "__main__":
    unittest.main()
