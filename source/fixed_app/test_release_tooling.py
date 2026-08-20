from __future__ import annotations

import contextlib
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import cli


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPO_ROOT / "tooling" / "audit_public_tree.ps1"
SOURCE_STAGE_SCRIPT = REPO_ROOT / "tooling" / "stage_public_source.ps1"
SOFTWARE_STAGE_SCRIPT = REPO_ROOT / "tooling" / "stage_software_package.ps1"
BUILD_SCRIPT = REPO_ROOT / "BUILD_AND_TEST.ps1"
SPEC_FILE = REPO_ROOT / "source" / "fixed_app" / "TripoSpectrumMapper_fixed.spec"
POWERSHELL = shutil.which("powershell.exe")


def _run_powershell(
    script: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if POWERSHELL is None:
        raise unittest.SkipTest("Windows PowerShell is unavailable")
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
        env=environment,
    )


def _manifest_line(path: str, content: bytes) -> str:
    return f"{hashlib.sha256(content).hexdigest().upper()}  {path}"


def _write_source_manifest(root: Path, lines: list[str] | None = None) -> None:
    if lines is None:
        lines = []
        for path in sorted(
            candidate
            for candidate in root.rglob("*")
            if candidate.is_file()
            and candidate.name != "SOURCE_MANIFEST_SHA256.txt"
        ):
            relative = path.relative_to(root).as_posix()
            lines.append(_manifest_line(relative, path.read_bytes()))
    payload = "\n".join(lines)
    if lines:
        payload += "\n"
    (root / "SOURCE_MANIFEST_SHA256.txt").write_text(
        payload,
        encoding="utf-8",
    )


def _assert_relative_manifest(test: unittest.TestCase, root: Path, name: str) -> None:
    manifest = root / name
    rows = manifest.read_text(encoding="utf-8").splitlines()
    expected: dict[str, str] = {}
    for row in rows:
        digest, separator, relative = row.partition("  ")
        test.assertEqual(separator, "  ")
        test.assertRegex(digest, r"^[0-9A-F]{64}$")
        test.assertNotIn(relative.casefold(), expected)
        expected[relative.casefold()] = digest

    actual = {
        path.relative_to(root).as_posix().casefold(): path
        for path in root.rglob("*")
        if path.is_file() and path != manifest
    }
    test.assertEqual(set(expected), set(actual))
    for relative, path in actual.items():
        test.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            expected[relative],
        )


class PublicManifestAuditTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[bytes, bytes]:
        first = b"first public file\n"
        second = b"second public file\n"
        (root / "first.txt").write_bytes(first)
        (root / "nested").mkdir()
        (root / "nested" / "second.txt").write_bytes(second)
        return first, second

    def test_valid_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "public-stage"
            root.mkdir()
            self._fixture(root)
            _write_source_manifest(root)

            result = _run_powershell(
                AUDIT_SCRIPT,
                "-Root",
                str(root),
                "-RequireManifest",
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Public-tree audit passed", result.stdout)

    def test_required_manifest_absence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "public-stage"
            root.mkdir()
            self._fixture(root)

            result = _run_powershell(
                AUDIT_SCRIPT,
                "-Root",
                str(root),
                "-RequireManifest",
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("required source manifest is missing", output)

    def test_manifest_negative_cases_fail_closed(self) -> None:
        cases = {
            "syntax": (
                lambda _first, _second: ["not a manifest row"],
                "manifest syntax error",
            ),
            "duplicate": (
                lambda first, second: [
                    _manifest_line("first.txt", first),
                    _manifest_line("FIRST.TXT", first),
                    _manifest_line("nested/second.txt", second),
                ],
                "duplicate manifest path",
            ),
            "missing": (
                lambda first, _second: [_manifest_line("first.txt", first)],
                "file is missing from manifest",
            ),
            "extra": (
                lambda first, second: [
                    _manifest_line("first.txt", first),
                    _manifest_line("nested/second.txt", second),
                    _manifest_line("ghost.txt", b"ghost"),
                ],
                "manifest lists a missing file",
            ),
            "hash": (
                lambda _first, second: [
                    f"{'0' * 64}  first.txt",
                    _manifest_line("nested/second.txt", second),
                ],
                "manifest hash mismatch",
            ),
            "traversal": (
                lambda first, second: [
                    _manifest_line("first.txt", first),
                    _manifest_line("nested/second.txt", second),
                    _manifest_line("../outside.txt", b"outside"),
                ],
                "manifest path is not a normalized",
            ),
        }
        for name, (make_lines, expected_error) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "public-stage"
                root.mkdir()
                first, second = self._fixture(root)
                _write_source_manifest(root, make_lines(first, second))

                result = _run_powershell(AUDIT_SCRIPT, "-Root", str(root))

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn(expected_error, output)


class PackagedLanguageSmokeTests(unittest.TestCase):
    def test_cli_applies_explicit_smoke_language_only_around_launch(self) -> None:
        observed: list[str | None] = []

        def fake_launch(**_kwargs: object) -> int:
            observed.append(os.environ.get("TRIPO_SPECTRUM_LANGUAGE"))
            return 0

        with (
            mock.patch.dict(
                os.environ,
                {"TRIPO_SPECTRUM_LANGUAGE": "ja"},
                clear=False,
            ),
            mock.patch("spectrum_mapper.gui.launch_app", side_effect=fake_launch) as launch,
        ):
            self.assertEqual(
                cli.main(["--ui-smoke", "--ui-smoke-language", "en"]),
                0,
            )
            self.assertEqual(os.environ["TRIPO_SPECTRUM_LANGUAGE"], "ja")

        self.assertEqual(observed, ["en"])
        launch.assert_called_once_with(smoke_test=True, initial_project=None)

    def test_smoke_language_without_smoke_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--ui-smoke-language", "en"])
        self.assertEqual(raised.exception.code, 2)

    def test_build_runs_both_explicit_packaged_languages(self) -> None:
        build = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('foreach ($language in @("ja", "en"))', build)
        self.assertIn(
            '-ArgumentList "--ui-smoke", "--ui-smoke-language", $Language',
            build,
        )
        self.assertIn(
            "Invoke-PackagedUiSmoke -Executable $exe -Language $language",
            build,
        )

    def test_build_smoke_profile_is_isolated_from_existing_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_appdata = root / "real-roaming"
            real_local_appdata = root / "real-local"
            settings = real_appdata / "TripoSpectrumMapper" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text("real-user-settings\n", encoding="utf-8")
            real_local_appdata.mkdir()
            capture = root / "smoke-environments.txt"

            fake_executable = root / "fake-ui-smoke.cmd"
            fake_executable.write_text(
                "@echo off\n"
                "if not exist \"%APPDATA%\\TripoSpectrumMapper\" "
                "mkdir \"%APPDATA%\\TripoSpectrumMapper\"\n"
                "> \"%APPDATA%\\TripoSpectrumMapper\\settings.json\" "
                "echo smoke-mutated-settings\n"
                ">> \"%R21_SMOKE_CAPTURE%\" echo APPDATA=%APPDATA%\n"
                ">> \"%R21_SMOKE_CAPTURE%\" echo LOCALAPPDATA=%LOCALAPPDATA%\n"
                "exit /b 0\n",
                encoding="ascii",
            )

            harness = root / "invoke-isolated-smoke.ps1"
            harness.write_text(
                "param([string]$BuildScript, [string]$FakeExecutable)\n"
                "$tokens = $null\n"
                "$parseErrors = $null\n"
                "$ast = [System.Management.Automation.Language.Parser]::ParseFile(\n"
                "    $BuildScript, [ref]$tokens, [ref]$parseErrors\n"
                ")\n"
                "if ($parseErrors.Count -ne 0) { throw 'BUILD_AND_TEST parse failed' }\n"
                "$definition = $ast.Find({\n"
                "    param($node)\n"
                "    $node -is "
                "[System.Management.Automation.Language.FunctionDefinitionAst] -and\n"
                "    $node.Name -eq 'Invoke-PackagedUiSmoke'\n"
                "}, $true)\n"
                "if ($null -eq $definition) { throw 'Smoke helper was not found' }\n"
                ". ([ScriptBlock]::Create($definition.Extent.Text))\n"
                "Invoke-PackagedUiSmoke -Executable $FakeExecutable -Language ja\n"
                "Invoke-PackagedUiSmoke -Executable $FakeExecutable -Language en\n"
                "Write-Output ('RESTORED_APPDATA=' + $env:APPDATA)\n"
                "Write-Output ('RESTORED_LOCALAPPDATA=' + $env:LOCALAPPDATA)\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "APPDATA": str(real_appdata),
                    "LOCALAPPDATA": str(real_local_appdata),
                    "R21_SMOKE_CAPTURE": str(capture),
                }
            )

            result = _run_powershell(
                harness,
                "-BuildScript",
                str(BUILD_SCRIPT),
                "-FakeExecutable",
                str(fake_executable),
                environment=environment,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertEqual(settings.read_text(encoding="utf-8"), "real-user-settings\n")
            self.assertIn(f"RESTORED_APPDATA={real_appdata}", result.stdout)
            self.assertIn(
                f"RESTORED_LOCALAPPDATA={real_local_appdata}",
                result.stdout,
            )
            observed = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(observed), 4)
            smoke_roots: list[Path] = []
            for index in (0, 2):
                smoke_appdata = Path(observed[index].partition("=")[2])
                smoke_local = Path(observed[index + 1].partition("=")[2])
                self.assertNotEqual(smoke_appdata, real_appdata)
                self.assertNotEqual(smoke_local, real_local_appdata)
                self.assertEqual(smoke_appdata.parent, smoke_local.parent)
                smoke_roots.append(smoke_appdata.parents[1])
            self.assertNotEqual(smoke_roots[0], smoke_roots[1])
            self.assertTrue(all(not path.exists() for path in smoke_roots))


class SoftwarePackageStageTests(unittest.TestCase):
    REQUIRED_RUNTIME_FILES = (
        "_internal/THIRD_PARTY_VOLUME_LICENSES_JA.md",
        "_internal/_tk_data/license.terms",
        "_internal/licenses/GPL-3.0.txt",
        "_internal/licenses/LICENSE_APP.txt",
        "_internal/licenses/LICENSE_RESVG_PY.txt",
        "_internal/licenses/LICENSE_RESVG_MIT.txt",
        "_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt",
        "_internal/licenses/THIRD_PARTY_LICENSES.txt",
        "_internal/licenses/resvg-py/LICENSE.txt",
        "_internal/licenses/resvg-py/resvg.cyclonedx.json",
        "_internal/licenses/pytetwild/LICENSE",
        "_internal/licenses/tetgen/LICENSE",
        "_internal/licenses/tetgen/tetgen-license",
        "_internal/resources/filament_db/filament_color_database_2026-08.sqlite",
        "_internal/resources/filament_db/filament_color_database_README.md",
        "_internal/resources/filament_db/ATTRIBUTION.md",
        "_internal/resources/filament_db/LICENSE_OPEN_FILAMENT_DATABASE.txt",
        "_internal/resources/filament_db/LICENSE_CC_BY_4.0.txt",
    )

    def _fake_build(self, root: Path) -> Path:
        built = root / "dist" / "ChromaMatter"
        built.mkdir(parents=True)
        (built / "ChromaMatter.exe").write_bytes(b"MZ\x00synthetic-test-exe")
        for index, relative in enumerate(self.REQUIRED_RUNTIME_FILES):
            path = built / Path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"runtime fixture {index}\n".encode("utf-8"))
        (built / "_internal" / "runtime.dll").write_bytes(b"synthetic dll")
        # Real PyInstaller collections may contain legitimate zero-byte text
        # placeholders.  The privacy scanner must inspect them without
        # PowerShell rejecting the empty string before token matching.
        (built / "_internal" / "empty.txt").write_bytes(b"")
        return built

    def _assert_no_stage_debris(self, root: Path, destination: Path) -> None:
        prefix = f".{destination.name}."
        self.assertFalse(
            [path.name for path in root.iterdir() if path.name.startswith(prefix)]
        )

    def test_stage_manifest_zip_and_extracted_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)
            destination = root / "ChromaMatter_0.8beta-r31-ai-model-print-studio"
            archive = Path(f"{destination}.zip")

            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertTrue(destination.is_dir())
            self.assertTrue(archive.is_file())
            _assert_relative_manifest(
                self,
                destination,
                "SOFTWARE_PACKAGE_SHA256.txt",
            )
            self.assertEqual(
                (destination / "ChromaMatter.exe").read_bytes(),
                b"MZ\x00synthetic-test-exe",
            )
            self.assertTrue((destination / "licenses" / "GPL-3.0.txt").is_file())
            self.assertTrue(
                (destination / "publication" / "LEGAL_AND_RIGHTS_JA.md").is_file()
            )
            extracted = root / "independent-extract"
            with ZipFile(archive) as package:
                file_names = {
                    name for name in package.namelist() if not name.endswith("/")
                }
                package.extractall(extracted)
            prefix = f"{destination.name}/"
            self.assertTrue(file_names)
            self.assertTrue(all(name.startswith(prefix) for name in file_names))
            self.assertIn(
                prefix + "SOFTWARE_PACKAGE_SHA256.txt",
                file_names,
            )
            _assert_relative_manifest(
                self,
                extracted / destination.name,
                "SOFTWARE_PACKAGE_SHA256.txt",
            )
            self.assertIn("Software archive verified after extraction", output)

    def test_unexpected_top_level_build_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)
            (built / "private.log").write_text("must not ship", encoding="utf-8")
            destination = root / "rejected-package"

            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("Unexpected top-level build output", output)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(f"{destination}.zip").exists())
            self._assert_no_stage_debris(root, destination)

    def test_private_model_inside_internal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)
            (built / "_internal" / "private_model.3mf").write_bytes(
                b"private geometry"
            )
            destination = root / "rejected-private-model"

            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("forbidden software payload extension '.3mf'", output)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(f"{destination}.zip").exists())
            self._assert_no_stage_debris(root, destination)

    def test_sensitive_text_inside_internal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)
            private_path = (
                "C:" + "\\" + "Us" + "ers" + "\\" + "PDF" + "um" + "\\model"
            )
            (built / "_internal" / "private.log").write_text(
                private_path,
                encoding="utf-8",
            )
            destination = root / "rejected-private-text"

            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("forbidden text token", output)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(f"{destination}.zip").exists())
            self._assert_no_stage_debris(root, destination)

    def test_sensitive_identifier_inside_binary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)
            private_identifier = ("PDF" + "um").encode("ascii")
            (built / "_internal" / "private.dll").write_bytes(
                b"synthetic-binary\x00" + private_identifier + b"\x00"
            )
            destination = root / "rejected-private-binary"

            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("forbidden binary token", output)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(f"{destination}.zip").exists())
            self._assert_no_stage_debris(root, destination)

    def test_existing_outputs_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)

            existing_destination = root / "existing-destination"
            existing_destination.mkdir()
            destination_marker = existing_destination / "keep.txt"
            destination_marker.write_text("keep destination\n", encoding="utf-8")
            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(existing_destination),
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("Refusing to overwrite an existing software stage", output)
            self.assertEqual(
                destination_marker.read_text(encoding="utf-8"),
                "keep destination\n",
            )

            destination = root / "new-destination"
            existing_archive = root / "existing.zip"
            existing_archive.write_bytes(b"keep archive")
            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
                "-ArchivePath",
                str(existing_archive),
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("Refusing to overwrite an existing software archive", output)
            self.assertEqual(existing_archive.read_bytes(), b"keep archive")
            self.assertFalse(destination.exists())

    def test_spec_drops_upstream_pymeshlab_test_meshes(self) -> None:
        spec = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn('.startswith("pymeshlab/tests/")', spec)

    def test_spec_registers_frozen_pymeshlab_dll_directory(self) -> None:
        spec = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn(
            'runtime_hooks=[str(APP / "pymeshlab_runtime_hook.py")]',
            spec,
        )
        runtime_hook = (
            REPO_ROOT / "source" / "fixed_app" / "pymeshlab_runtime_hook.py"
        ).read_text(encoding="utf-8")
        self.assertIn('getattr(os, "add_dll_directory", None)', runtime_hook)
        self.assertIn('Path(bundle_root) / "pymeshlab"', runtime_hook)
        self.assertIn("_DLL_DIRECTORY_HANDLES.append", runtime_hook)

    def test_spec_bundles_established_toolbar_brand_asset(self) -> None:
        spec = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn(
            '(str(APP / "assets" / "obj_adjuster_icon.png"), "assets")',
            spec,
        )
        self.assertTrue(
            (
                REPO_ROOT
                / "source"
                / "fixed_app"
                / "assets"
                / "obj_adjuster_icon.png"
            ).is_file()
        )

    def test_spec_bundles_dynamic_gltf_importer(self) -> None:
        spec = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn('"spectrum_mapper.gltf_import"', spec)
        self.assertTrue(
            (
                REPO_ROOT
                / "source"
                / "fixed_app"
                / "spectrum_mapper"
                / "gltf_import.py"
            ).is_file()
        )

    def test_public_source_stage_includes_packaging_tool(self) -> None:
        stage = (REPO_ROOT / "tooling" / "stage_public_source.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('"tooling/stage_software_package.ps1"', stage)


class PublicSourceStageRollbackTests(unittest.TestCase):
    REQUIRED_ROOT_FILES = (
        ".gitignore",
        ".gitattributes",
        "BUILD_AND_TEST.ps1",
        "BOOTSTRAP_WINDOWS.ps1",
        "RUN_TESTS.cmd",
        "CURRENT_STATE.json",
        "PROVENANCE.md",
        "FEATURES_JA.md",
        "README_PUBLIC_JA.md",
        "README_PUBLIC_EN.md",
    )
    REQUIRED_PUBLICATION_FILES = (
        "publication/LEGAL_AND_RIGHTS_JA.md",
        "publication/PRIVATE_SAMPLE_POLICY_JA.md",
        "publication/CLEAN_CLONE_GUIDE_JA.md",
        "publication/VIDEO_VALIDATION_CHECKLIST_JA.md",
        "publication/PUBLICATION_CHECKLIST_JA.md",
        "publication/GITHUB_PUBLICATION_GUIDE_JA.md",
        "publication/INNOVATION_FUND_APPLICATION_DRAFT.md",
        "publication/INNOVATION_FUND_STATUS_JA.md",
    )
    REQUIRED_FIXED_APP_FILES = (
        "source/fixed_app/TripoSpectrumMapper_fixed.py",
        "source/fixed_app/TripoSpectrumMapper_fixed.spec",
        "source/fixed_app/requirements-build.txt",
        "source/fixed_app/START_FIXED.cmd",
        "source/fixed_app/version_info.txt",
        "source/fixed_app/VERSION_POLICY.md",
        "source/fixed_app/README_fixed_ja.md",
        "source/fixed_app/README_fixed_en.md",
        "source/fixed_app/THIRD_PARTY_VOLUME_LICENSES_JA.md",
        "source/fixed_app/orca_paint_vectors.json",
        "source/fixed_app/adaptive_gpu_overlay.py",
        "source/fixed_app/auto_shading.py",
        "source/fixed_app/brush_cursor_hotfix.py",
        "source/fixed_app/rotation_hotfix.py",
        "source/fixed_app/pymeshlab_runtime_hook.py",
        "source/fixed_app/slicer_safety.py",
        "source/fixed_app/smooth_paint.py",
        "source/fixed_app/smooth_paint_hotfix.py",
        "source/fixed_app/spectrum_mapper_hotfix.py",
        "source/fixed_app/surface_resolution_hotfix.py",
        "source/fixed_app/final_shading_hotfix.py",
        "source/fixed_app/test_tetra.obj",
        "source/fixed_app/assets/mixer_model.npz",
        "source/fixed_app/assets/chromamatter_icon_PROVENANCE.md",
        "source/fixed_app/assets/obj_adjuster_icon.ico",
        "source/fixed_app/assets/obj_adjuster_icon.png",
    )

    def _source_fixture(self, root: Path) -> Path:
        fixture = root / "fixture-repository"
        for relative in (
            self.REQUIRED_ROOT_FILES
            + self.REQUIRED_PUBLICATION_FILES
            + self.REQUIRED_FIXED_APP_FILES
        ):
            path = fixture / Path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic public source fixture\n")

        required_directories = (
            "licenses",
            "samples",
            "source/fixed_app/spectrum_mapper",
            "source/fixed_app/resources/filament_db",
            "source/fixed_app/tests",
        )
        for relative in required_directories:
            (fixture / Path(relative)).mkdir(parents=True, exist_ok=True)
        (fixture / "licenses" / "GPL-3.0.txt").write_text(
            "synthetic license\n",
            encoding="utf-8",
        )

        tooling = fixture / "tooling"
        tooling.mkdir(parents=True)
        shutil.copy2(SOURCE_STAGE_SCRIPT, tooling / SOURCE_STAGE_SCRIPT.name)
        shutil.copy2(AUDIT_SCRIPT, tooling / AUDIT_SCRIPT.name)
        shutil.copy2(
            SOFTWARE_STAGE_SCRIPT,
            tooling / SOFTWARE_STAGE_SCRIPT.name,
        )
        (tooling / "generate_public_icon.py").write_text(
            "# synthetic public fixture\n",
            encoding="utf-8",
        )
        return fixture

    def _assert_no_source_stage_debris(
        self,
        destination_parent: Path,
        destination: Path,
    ) -> None:
        prefix = f".{destination.name}.staging-"
        self.assertFalse(
            [
                path.name
                for path in destination_parent.iterdir()
                if path.name.startswith(prefix)
            ]
        )

    def test_privacy_audit_failure_rolls_back_only_new_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._source_fixture(root)
            private_identifier = "PDF" + "um"
            (fixture / "PROVENANCE.md").write_text(
                f"private owner: {private_identifier}\n",
                encoding="utf-8",
            )

            output_root = root / "release-output"
            output_root.mkdir()
            existing_destination = output_root / "existing-source-stage"
            existing_destination.mkdir()
            marker = existing_destination / "keep.txt"
            marker.write_text("keep existing destination\n", encoding="utf-8")

            destination = output_root / "audit-failure-source-stage"
            result = _run_powershell(
                fixture / "tooling" / SOURCE_STAGE_SCRIPT.name,
                "-Destination",
                str(destination),
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("Public-tree audit failed", output)
            self.assertIn("forbidden text token", output)
            self.assertFalse(destination.exists())
            self._assert_no_source_stage_debris(output_root, destination)
            self.assertEqual(
                marker.read_text(encoding="utf-8"),
                "keep existing destination\n",
            )

            existing_result = _run_powershell(
                fixture / "tooling" / SOURCE_STAGE_SCRIPT.name,
                "-Destination",
                str(existing_destination),
            )
            existing_output = existing_result.stdout + existing_result.stderr
            self.assertNotEqual(existing_result.returncode, 0, existing_output)
            self.assertIn(
                "Refusing to overwrite an existing public-source stage",
                existing_output,
            )
            self.assertEqual(
                marker.read_text(encoding="utf-8"),
                "keep existing destination\n",
            )
            self._assert_no_source_stage_debris(
                output_root,
                existing_destination,
            )


if __name__ == "__main__":
    unittest.main()
