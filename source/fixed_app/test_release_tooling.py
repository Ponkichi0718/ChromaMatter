from __future__ import annotations

import base64
import contextlib
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
from zipfile import ZipFile, ZipInfo


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper import cli


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPO_ROOT / "tooling" / "audit_public_tree.ps1"
SOURCE_STAGE_SCRIPT = REPO_ROOT / "tooling" / "stage_public_source.ps1"
SOFTWARE_STAGE_SCRIPT = REPO_ROOT / "tooling" / "stage_software_package.ps1"
BUILD_SCRIPT = REPO_ROOT / "BUILD_AND_TEST.ps1"
BOOTSTRAP_SCRIPT = REPO_ROOT / "BOOTSTRAP_WINDOWS.ps1"
PYTETWILD_BUILD_RECIPE = REPO_ROOT / "tooling" / "BUILD_PYTETWILD_WINDOWS.ps1"
PYTETWILD_BUILD_LOCK = REPO_ROOT / "tooling" / "requirements-pytetwild-build.lock"
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


class BootstrapWindowsPyTetWildTests(unittest.TestCase):
    WHEEL_NAME = "pytetwild-0.3.0-cp312-abi3-win_amd64.whl"

    def _write_lock(
        self,
        root: Path,
        sha256: str,
        *,
        version: str = "0.3.0",
    ) -> Path:
        lock = root / "requirements-build.lock"
        lock.write_text(
            f"pytetwild=={version} "
            + "\\\n"
            + f"    --hash=sha256:{sha256}\n",
            encoding="utf-8",
        )
        return lock

    def _write_resolver_harness(self, root: Path) -> Path:
        harness = root / "resolve-pytetwild-wheel.ps1"
        harness.write_text(
            "param(\n"
            "    [string]$BootstrapScript,\n"
            "    [string]$RequirementsLock,\n"
            "    [string]$Wheel = '',\n"
            "    [string]$Wheelhouse = ''\n"
            ")\n"
            "$tokens = $null\n"
            "$parseErrors = $null\n"
            "$ast = [System.Management.Automation.Language.Parser]::ParseFile(\n"
            "    $BootstrapScript, [ref]$tokens, [ref]$parseErrors\n"
            ")\n"
            "if ($parseErrors.Count -ne 0) { throw 'BOOTSTRAP parse failed' }\n"
            "$definition = $ast.Find({\n"
            "    param($node)\n"
            "    $node -is "
            "[System.Management.Automation.Language.FunctionDefinitionAst] -and\n"
            "    $node.Name -eq 'Resolve-LockedPyTetWildWheel'\n"
            "}, $true)\n"
            "if ($null -eq $definition) { throw 'Wheel resolver was not found' }\n"
            ". ([ScriptBlock]::Create($definition.Extent.Text))\n"
            "$result = Resolve-LockedPyTetWildWheel "
            "-RequirementsLock $RequirementsLock "
            "-Wheel $Wheel -Wheelhouse $Wheelhouse\n"
            "if ($null -ne $result) {\n"
            "    Write-Output ('PATH=' + $result.Path)\n"
            "    Write-Output ('VERSION=' + $result.Version)\n"
            "    Write-Output ('SHA256=' + $result.Sha256)\n"
            "}\n",
            encoding="utf-8",
        )
        return harness

    def _resolve(
        self,
        root: Path,
        lock: Path,
        *,
        wheel: Path | None = None,
        wheelhouse: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            "-BootstrapScript",
            str(BOOTSTRAP_SCRIPT),
            "-RequirementsLock",
            str(lock),
        ]
        if wheel is not None:
            arguments.extend(("-Wheel", str(wheel)))
        if wheelhouse is not None:
            arguments.extend(("-Wheelhouse", str(wheelhouse)))
        return _run_powershell(
            self._write_resolver_harness(root),
            *arguments,
        )

    def test_bootstrap_powershell_parser_accepts_script(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Path(temporary) / "parse-bootstrap.ps1"
            harness.write_text(
                "param([string]$BootstrapScript)\n"
                "$tokens = $null\n"
                "$parseErrors = $null\n"
                "[System.Management.Automation.Language.Parser]::ParseFile(\n"
                "    $BootstrapScript, [ref]$tokens, [ref]$parseErrors\n"
                ") | Out-Null\n"
                "if ($parseErrors.Count -ne 0) {\n"
                "    $parseErrors | ForEach-Object { Write-Error $_.Message }\n"
                "    exit 1\n"
                "}\n"
                "Write-Output 'BOOTSTRAP PowerShell parser passed'\n",
                encoding="utf-8",
            )

            result = _run_powershell(
                harness,
                "-BootstrapScript",
                str(BOOTSTRAP_SCRIPT),
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PowerShell parser passed", result.stdout)

    def test_locked_wheel_resolves_from_file_and_wheelhouse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / self.WHEEL_NAME
            wheel.write_bytes(b"controlled rebuild wheel\n")
            sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
            lock = self._write_lock(root, sha256)
            (root / "unrelated-1.0-py3-none-any.whl").write_bytes(b"unrelated")

            for source, arguments in (
                ("wheel", {"wheel": wheel}),
                ("wheelhouse", {"wheelhouse": root}),
            ):
                with self.subTest(source=source):
                    result = self._resolve(root, lock, **arguments)
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 0, output)
                    self.assertIn(f"PATH={wheel.resolve()}", result.stdout)
                    self.assertIn("VERSION=0.3.0", result.stdout)
                    self.assertIn(f"SHA256={sha256}", result.stdout)

    def test_wheel_identity_version_and_tags_fail_closed(self) -> None:
        cases = {
            "distribution": (
                "other-0.3.0-cp312-abi3-win_amd64.whl",
                "distribution must be PyTetWild",
            ),
            "version": (
                "pytetwild-0.3.1-cp312-abi3-win_amd64.whl",
                "does not match locked version",
            ),
            "python_tag": (
                "pytetwild-0.3.0-cp313-abi3-win_amd64.whl",
                "does not match required tag",
            ),
            "abi_tag": (
                "pytetwild-0.3.0-cp312-cp312-win_amd64.whl",
                "does not match required tag",
            ),
            "platform_tag": (
                "pytetwild-0.3.0-cp312-abi3-manylinux_x86_64.whl",
                "does not match required tag",
            ),
            "malformed": (
                "pytetwild-0.3.0.whl",
                "Invalid PyTetWild wheel filename",
            ),
        }
        for name, (filename, expected_error) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                wheel = root / filename
                wheel.write_bytes(f"{name} wheel\n".encode("ascii"))
                sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
                lock = self._write_lock(root, sha256)

                result = self._resolve(root, lock, wheel=wheel)

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn(expected_error, output)

    def test_missing_ambiguous_and_hash_mismatched_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self._write_lock(root, "0" * 64)

            missing = self._resolve(root, lock, wheel=root / self.WHEEL_NAME)
            missing_output = missing.stdout + missing.stderr
            self.assertNotEqual(missing.returncode, 0, missing_output)
            self.assertIn("does not exist as a file", missing_output)

            missing_wheelhouse = self._resolve(
                root,
                lock,
                wheelhouse=root / "missing-wheelhouse",
            )
            missing_wheelhouse_output = (
                missing_wheelhouse.stdout + missing_wheelhouse.stderr
            )
            self.assertNotEqual(
                missing_wheelhouse.returncode,
                0,
                missing_wheelhouse_output,
            )
            self.assertIn("does not exist as a directory", missing_wheelhouse_output)

            wheel = root / self.WHEEL_NAME
            wheel.write_bytes(b"hash mismatch\n")
            mismatch = self._resolve(root, lock, wheel=wheel)
            mismatch_output = mismatch.stdout + mismatch.stderr
            self.assertNotEqual(mismatch.returncode, 0, mismatch_output)
            self.assertIn("SHA-256 does not match", mismatch_output)

            second = root / "pytetwild-0.3.1-cp312-abi3-win_amd64.whl"
            second.write_bytes(b"ambiguous\n")
            ambiguous = self._resolve(root, lock, wheelhouse=root)
            ambiguous_output = ambiguous.stdout + ambiguous.stderr
            self.assertNotEqual(ambiguous.returncode, 0, ambiguous_output)
            self.assertIn("exactly one top-level", ambiguous_output)

            both = self._resolve(root, lock, wheel=wheel, wheelhouse=root)
            both_output = both.stdout + both.stderr
            self.assertNotEqual(both.returncode, 0, both_output)
            self.assertIn("Pass only one of", both_output)

    def test_local_preinstall_is_hash_locked_and_does_not_offline_all_dependencies(
        self,
    ) -> None:
        bootstrap = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('[string]$PyTetWildWheel = ""', bootstrap)
        self.assertIn('[string]$PyTetWildWheelhouse = ""', bootstrap)
        self.assertIn("pytetwild @ $wheelUri", bootstrap)
        for option in (
            "--require-hashes",
            "--only-binary=:all:",
            "--no-index",
            "--no-deps",
            "--force-reinstall",
        ):
            with self.subTest(option=option):
                self.assertIn(option, bootstrap)
        self.assertEqual(bootstrap.count("--no-index"), 1)
        self.assertIn(
            "    & $venvPython -m pip install `\n"
            "        --require-hashes `\n"
            "        --only-binary=:all: `\n"
            "        -r $requirementsLock",
            bootstrap,
        )
        self.assertLess(
            bootstrap.index("$localPyTetWild = Resolve-LockedPyTetWildWheel"),
            bootstrap.index("if (-not (Test-Path -LiteralPath $venvPython))"),
        )
        self.assertIn("with -SkipInstall", bootstrap)
        spec = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn("def is_private_install_origin_metadata(entry):", spec)
        self.assertIn('.endswith("/direct_url.json")', spec)
        self.assertIn("and not is_private_install_origin_metadata(entry)", spec)


class ControlledPyTetWildBuildRecipeTests(unittest.TestCase):
    @staticmethod
    def _wheel_record_probe() -> str:
        recipe = PYTETWILD_BUILD_RECIPE.read_text(encoding="utf-8")
        match = re.search(
            r"\$wheelRecordProbe = @'\n(.*?)\n'@",
            recipe,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError("wheel RECORD probe was not found")
        return match.group(1)

    @staticmethod
    def _write_probe_wheel(
        wheel: Path,
        *,
        phase: str,
        extra_members: tuple[tuple[str | ZipInfo, bytes], ...] = (),
    ) -> None:
        dist_info = "pytetwild-0.3.0.dist-info"
        members: list[tuple[str | ZipInfo, bytes]] = [
            ("pytetwild/__init__.py", b"__version__ = '0.3.0'\n"),
            (f"{dist_info}/METADATA", b"Name: pytetwild\nVersion: 0.3.0\n"),
            (
                f"{dist_info}/WHEEL",
                b"Wheel-Version: 1.0\nTag: cp312-abi3-win_amd64\n",
            ),
        ]
        if phase == "repaired":
            members.append((f"{dist_info}/DELVEWHEEL", b"Version: 1.12.1\n"))
        members.extend(extra_members)

        rows: list[list[str]] = []
        for member, data in members:
            name = member.filename if isinstance(member, ZipInfo) else member
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode(
                "ascii"
            ).rstrip("=")
            rows.append([name, f"sha256={digest}", str(len(data))])
        record_name = f"{dist_info}/RECORD"
        rows.append([record_name, "", ""])
        record_buffer = io.StringIO(newline="")
        csv.writer(record_buffer, lineterminator="\n").writerows(rows)
        members.append((record_name, record_buffer.getvalue().encode("utf-8")))

        with ZipFile(wheel, "w") as archive:
            for member, data in members:
                archive.writestr(member, data)

    def _run_wheel_record_probe(
        self,
        wheel: Path,
        phase: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-c", self._wheel_record_probe(), str(wheel), phase],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
        )

    def test_recipe_is_windows_powershell_compatible(self) -> None:
        if POWERSHELL is None:
            self.skipTest("Windows PowerShell is unavailable")
        escaped = str(PYTETWILD_BUILD_RECIPE).replace("'", "''")
        command = (
            "$tokens=$null; $errors=$null; "
            "[void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{escaped}', [ref]$tokens, [ref]$errors); "
            "if($errors){$errors | ForEach-Object {$_.ToString()}; exit 1}"
        )
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = PYTETWILD_BUILD_RECIPE.read_text(encoding="utf-8")
        self.assertNotIn("ConvertFrom-Json -AsHashtable", text)
        self.assertNotIn("-Encoding utf8NoBOM", text)
        self.assertFalse(
            PYTETWILD_BUILD_RECIPE.read_bytes().startswith(b"\xef\xbb\xbf")
        )

    def test_recipe_pins_python_temp_to_the_controlled_output(self) -> None:
        text = PYTETWILD_BUILD_RECIPE.read_text(encoding="utf-8")
        expected_fragments = (
            "$BuildTemp = Join-Path $OutputRoot 'tmp'",
            "$env:TEMP = $BuildTempFullPath",
            "$env:TMP = $BuildTempFullPath",
            "$env:TMPDIR = $BuildTempFullPath",
            "pathlib.Path(value).resolve(strict=True)",
            "real_full_path(tempfile.gettempdir())",
            "$tempDirectoryProbeOutput = @(& $Python -I -c",
            "[System.StringComparison]::OrdinalIgnoreCase",
            "Fixed Python temporary directory escaped the controlled-build root",
        )
        for expected in expected_fragments:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

        output_creation = text.index(
            "$createdOutputRoot = New-Item -ItemType Directory -Path $OutputRoot"
        )
        build_temp_creation = text.index(
            "$createdBuildTemp = New-Item -ItemType Directory -Path $BuildTemp"
        )
        temp_environment = text.index("$env:TEMP = $BuildTempFullPath")
        temp_probe = text.index("$tempDirectoryProbeOutput = @(& $Python -I -c")
        first_build_export = text.index("$PyTetWildArchive = Join-Path")
        build_wheel = text.index(
            "Invoke-CheckedLogged $BuilderPython $buildWheelArguments"
        )
        first_audit = text.index(
            "$rawDelvewheelResult = Invoke-Logged $Delvewheel"
        )
        self.assertLess(output_creation, build_temp_creation)
        self.assertLess(build_temp_creation, temp_environment)
        self.assertLess(temp_environment, temp_probe)
        self.assertLess(temp_probe, first_build_export)
        self.assertLess(temp_probe, build_wheel)
        self.assertLess(temp_probe, first_audit)

    def test_logged_native_commands_capture_stderr_before_exit_evaluation(self) -> None:
        if POWERSHELL is None:
            self.skipTest("Windows PowerShell is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            recipe = str(PYTETWILD_BUILD_RECIPE).replace("'", "''")
            success_log = str(Path(temporary) / "success.log").replace("'", "''")
            failure_log = str(Path(temporary) / "failure.log").replace("'", "''")
            command = f"""
$tokens=$null
$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile(
    '{recipe}', [ref]$tokens, [ref]$errors
)
if ($errors.Count) {{ throw ($errors -join [Environment]::NewLine) }}
foreach ($functionName in @('Invoke-Logged', 'Invoke-CheckedLogged')) {{
    $definitions = @($ast.FindAll({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }}, $true))
    if ($definitions.Count -ne 1) {{
        throw "Expected exactly one definition for $functionName"
    }}
    Invoke-Expression $definitions[0].Extent.Text
}}
$ErrorActionPreference = 'Stop'
$successArguments = @(
    '/d', '/s', '/c',
    'echo stdout-ok & echo stderr-ok 1>&2 & exit /b 0'
)
$success = Invoke-Logged $env:ComSpec $successArguments '{success_log}'
if ($success.ExitCode -ne 0 -or $ErrorActionPreference -ne 'Stop') {{
    throw 'Successful logged command did not preserve its result or EAP'
}}
$successText = [System.IO.File]::ReadAllText('{success_log}')
if (
    $successText -notmatch 'exit_code=0' -or
    $successText -notmatch 'stdout-ok' -or
    $successText -notmatch 'stderr-ok'
) {{
    throw 'Successful logged command evidence is incomplete'
}}
$failureArguments = @(
    '/d', '/s', '/c',
    'echo failure-stdout & echo failure-stderr 1>&2 & exit /b 7'
)
$failedAsExpected = $false
try {{
    Invoke-CheckedLogged $env:ComSpec $failureArguments '{failure_log}'
}} catch {{
    if ($_.Exception.Message -notlike 'Command failed (7):*') {{ throw }}
    $failedAsExpected = $true
}}
if (-not $failedAsExpected -or $ErrorActionPreference -ne 'Stop') {{
    throw 'Failed logged command did not throw after preserving EAP'
}}
$failureText = [System.IO.File]::ReadAllText('{failure_log}')
if (
    $failureText -notmatch 'exit_code=7' -or
    $failureText -notmatch 'failure-stdout' -or
    $failureText -notmatch 'failure-stderr'
) {{
    throw 'Failed logged command evidence is incomplete'
}}
foreach ($path in @('{success_log}', '{failure_log}')) {{
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if (
        $bytes.Length -ge 3 -and
        $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
    ) {{
        throw "Audit log unexpectedly contains a UTF-8 BOM: $path"
    }}
}}
"""
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-Command", command],
                check=False,
                capture_output=True,
                text=True,
                errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_recipe_exports_immutable_sources_before_building(self) -> None:
        text = PYTETWILD_BUILD_RECIPE.read_text(encoding="utf-8")
        for expected in (
            "function Export-GitTree",
            "function Expand-SafeTarArchive",
            "$FmtBuildSource",
            "$SpdlogBuildSource",
            "$LibiglBuildSource",
            "$EigenBuildSource",
            "$PredicatesBuildSource",
            "$GeogramBuildSource",
            "$TbbBuildSource",
            "$JsonBuildSource",
            "geogram-amgcl-source.zip",
            "geogram-libmeshb-source.zip",
            "geogram-rply-source.zip",
        ):
            self.assertIn(expected, text)
        for mutable_source in (
            "FETCHCONTENT_SOURCE_DIR_FMT:PATH=$(ConvertTo-CMakePath $FmtSource)",
            "FETCHCONTENT_SOURCE_DIR_GEOGRAM:PATH=$(ConvertTo-CMakePath $GeogramSource)",
            "FETCHCONTENT_SOURCE_DIR_TBB:PATH=$(ConvertTo-CMakePath $TbbSource)",
        ):
            self.assertNotIn(mutable_source, text)

    def test_wheel_record_probe_accepts_canonical_raw_and_repaired_wheels(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for phase in ("raw", "repaired"):
                with self.subTest(phase=phase):
                    wheel = root / f"{phase}.whl"
                    self._write_probe_wheel(wheel, phase=phase)
                    result = self._run_wheel_record_probe(wheel, phase)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("verified RECORD", result.stdout)

    def test_wheel_record_probe_rejects_noncanonical_and_special_members(self) -> None:
        symlink = ZipInfo("symlink")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases: dict[str, str | ZipInfo] = {
            "absolute": "/absolute",
            "drive_absolute": "C:/drive",
            "drive_relative": "C:relative",
            "double_separator": "a//b",
            "dot_component": "a/./b",
            "leading_dot": "./a",
            "parent_component": "a/../b",
            "alternate_stream": "a:stream",
            "reserved": "CON.txt",
            "trailing_dot": "trailing.",
            "trailing_space": "trailing ",
            "explicit_directory": "explicit/",
            "control": "control\x01name",
            "non_nfc": "e\u0301.txt",
            "symlink": symlink,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, member in cases.items():
                with self.subTest(case=label):
                    wheel = root / f"{label}.whl"
                    self._write_probe_wheel(
                        wheel,
                        phase="raw",
                        extra_members=((member, b"unsafe"),),
                    )
                    result = self._run_wheel_record_probe(wheel, "raw")
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("unsafe wheel member", result.stderr)

            nul_wheel = root / "nul.whl"
            self._write_probe_wheel(
                nul_wheel,
                phase="raw",
                extra_members=(("safeXtruncated", b"unsafe"),),
            )
            nul_bytes = nul_wheel.read_bytes().replace(
                b"safeXtruncated", b"safe\x00truncated"
            )
            self.assertNotEqual(nul_bytes, nul_wheel.read_bytes())
            nul_wheel.write_bytes(nul_bytes)
            nul_result = self._run_wheel_record_probe(nul_wheel, "raw")
            self.assertNotEqual(nul_result.returncode, 0, nul_result.stdout)
            self.assertIn("unsafe wheel member", nul_result.stderr)

            backslash_wheel = root / "backslash.whl"
            self._write_probe_wheel(
                backslash_wheel,
                phase="raw",
                extra_members=(("aXb", b"unsafe"),),
            )
            backslash_bytes = backslash_wheel.read_bytes().replace(b"aXb", b"a\\b")
            self.assertNotEqual(backslash_bytes, backslash_wheel.read_bytes())
            backslash_wheel.write_bytes(backslash_bytes)
            backslash_result = self._run_wheel_record_probe(backslash_wheel, "raw")
            self.assertNotEqual(backslash_result.returncode, 0, backslash_result.stdout)
            self.assertIn("unsafe wheel member", backslash_result.stderr)

    def test_wheel_record_probe_rejects_collisions_and_ancestor_conflicts(self) -> None:
        cases = {
            "case_collision": (("Case.txt", b"a"), ("case.txt", b"b")),
            "ancestor_conflict": (("parent", b"a"), ("parent/child", b"b")),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, members in cases.items():
                with self.subTest(case=label):
                    wheel = root / f"{label}.whl"
                    self._write_probe_wheel(
                        wheel,
                        phase="raw",
                        extra_members=members,
                    )
                    result = self._run_wheel_record_probe(wheel, "raw")
                    self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_recipe_fails_closed_and_audits_both_wheels(self) -> None:
        text = PYTETWILD_BUILD_RECIPE.read_text(encoding="utf-8")
        for expected in (
            "Assert-NetworkIsolation",
            "[switch]$OsNetworkIsolationConfirmed",
            "operator_confirmed_os_level_isolation",
            "os_level_enforcement_by_script = $false",
            "-vcvars_ver=$VCToolsFamilyVersion",
            "-DCMAKE_C_COMPILER:FILEPATH=",
            "-DCMAKE_CXX_COMPILER:FILEPATH=",
            "-DCMAKE_LINKER:FILEPATH=",
            "function Get-DirectoryTreeEvidence",
            "VsLayoutFileCount = 714",
            "VsLayoutTreeSha256 = '2b6a89bb69aa7de013fc055828258a3a91c7c333f0c6be831a750990922fed3a'",
            "visual_studio_layout_tree_sha256",
            "Reparse point is forbidden in fixed directory tree",
            "Microsoft Visual Studio layout verification failed",
            "Start-Process -FilePath $vsLayoutBootstrapper",
            "PyTetWildSourcePatchSha256 = 'a051af2c29279a11110f7b53779fcfc655b6fe19533550717383b7d8c84c9ad6'",
            "'apply', '--check', '--unidiff-zero', $PyTetWildSourcePatch",
            "Assert-Sha256 $PSCommandPath $recipeSha256AtStart",
            "source_patch_sha256 = $sourcePatchSha256AtStart",
            "function Invoke-Logged",
            "$savedErrorActionPreference = $ErrorActionPreference",
            "$ErrorActionPreference = 'Continue'",
            "$ErrorActionPreference = $savedErrorActionPreference",
            "$env:PIP_NO_INDEX = '1'",
            "'-DFETCHCONTENT_FULLY_DISCONNECTED=ON'",
            "'-DFETCHCONTENT_TRY_FIND_PACKAGE_MODE=NEVER'",
            "'show', '--add-path', $MpirBin, '-vv'",
            "'repair', '--wheel-dir', $WheelDirectory, '-v'",
            "entry.orig_filename",
            "pathlib.PureWindowsPath(name).drive",
            'any(part in {"", ".", ".."} for part in parts)',
            "entry.flag_bits & 0x41",
            "csv.reader(",
            're.fullmatch(r"(?:0|[1-9][0-9]*)"',
            "'-c', $wheelRecordProbe, $rawWheels[0].FullName, 'raw'",
            "'-c', $wheelRecordProbe, $wheel.FullName, 'repaired'",
            "Invoke-CheckedLogged $Abi3Audit $abi3AuditArguments",
            "native_extension_load = 'passed'",
            "normal_isolated_package_import = 'passed'",
            "from pytetwild import PyfTetWildWrapper as native",
            "kernel32.GetModuleHandleW",
            "Invoke-CheckedLogged $NativePython @('-I', '-c', $nativeProbe)",
            "--require-hashes', '--only-binary=:all:'",
            "runner_image = 'self-hosted-windows-controlled-offline'",
            "numpy_version = $Expected.NumpyVersion",
            "$auditLogEvidence = [ordered]@{}",
            "visual-studio-layout-verification.log",
            "native-normal-import.log",
            "audit_logs = $auditLogEvidence",
        ):
            self.assertIn(expected, text)

    def test_build_inputs_are_explicitly_public_tree_candidates(self) -> None:
        ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tooling/BUILD_PYTETWILD_WINDOWS.ps1", ignored)
        self.assertIn("!tooling/requirements-pytetwild-build.lock", ignored)
        self.assertIn(
            "!tooling/patches/pytetwild-0.3.0-optional-pyvista.patch", ignored
        )
        lock = PYTETWILD_BUILD_LOCK.read_text(encoding="utf-8")
        lock_sha256 = hashlib.sha256(PYTETWILD_BUILD_LOCK.read_bytes()).hexdigest()
        recipe = PYTETWILD_BUILD_RECIPE.read_text(encoding="utf-8")
        self.assertIn(f"RequirementsLockSha256 = '{lock_sha256}'", recipe)
        pins = re.findall(r"(?m)^([A-Za-z0-9_.-]+)==([^\s\\]+)\s*\\$", lock)
        self.assertEqual(len(pins), 39)
        self.assertEqual(len({name.casefold() for name, _ in pins}), 39)
        self.assertEqual(lock.count("--hash=sha256:"), 39)
        self.assertIn(("numpy", "2.5.1"), pins)


class PackagedLanguageSmokeTests(unittest.TestCase):
    def test_cli_applies_explicit_smoke_language_only_around_launch(self) -> None:
        observed: list[str | None] = []

        def fake_launch(**_kwargs: object) -> int:
            observed.append(os.environ.get("TRIPO_SPECTRUM_LANGUAGE"))
            return 0

        fake_gui = types.ModuleType("spectrum_mapper.gui")
        launch = mock.Mock(side_effect=fake_launch)
        fake_gui.launch_app = launch
        with (
            mock.patch.dict(
                os.environ,
                {"TRIPO_SPECTRUM_LANGUAGE": "ja"},
                clear=False,
            ),
            mock.patch.dict(sys.modules, {"spectrum_mapper.gui": fake_gui}),
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
    CORRESPONDING_SOURCE_ASSET = (
        "ChromaMatter-0.8beta-r32-complete-corresponding-source.zip"
    )
    CORRESPONDING_SOURCE_COMMIT = "1" * 40
    REQUIRED_RUNTIME_FILES = (
        "_internal/THIRD_PARTY_VOLUME_LICENSES_JA.md",
        "_internal/_tk_data/license.terms",
        "_internal/licenses/GPL-3.0.txt",
        "_internal/licenses/AGPL-3.0.txt",
        "_internal/licenses/LGPL-2.1.txt",
        "_internal/licenses/LGPL-3.0.txt",
        "_internal/licenses/MPL-2.0.txt",
        "_internal/licenses/BINARY_COMPONENT_MAP.schema.json",
        "_internal/licenses/BUILD_ENVIRONMENT_EN.md",
        "_internal/licenses/BUILD_ENVIRONMENT_JA.md",
        "_internal/licenses/RELINKING_EN.md",
        "_internal/licenses/RELINKING_JA.md",
        "_internal/licenses/THIRD_PARTY_NOTICES_EN.txt",
        "_internal/licenses/THIRD_PARTY_NOTICES_JA.txt",
        "_internal/licenses/LICENSE_APP.txt",
        "_internal/licenses/LICENSE_RESVG_PY.txt",
        "_internal/licenses/LICENSE_RESVG_MIT.txt",
        "_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt",
        "_internal/licenses/THIRD_PARTY_LICENSES.txt",
        "_internal/licenses/cpython/LICENSE.txt",
        "_internal/licenses/pyinstaller/COPYING.txt",
        "_internal/licenses/resvg-py/LICENSE.txt",
        "_internal/licenses/resvg-py/resvg.cyclonedx.json",
        "_internal/licenses/pytetwild/LICENSE",
        "_internal/licenses/tetgen/LICENSE",
        "_internal/licenses/tetgen/tetgen-license",
        "_internal/licenses/pymeshlab/LICENSE",
        "_internal/licenses/shapely/LICENSE.txt",
        "_internal/licenses/shapely/LICENSE_GEOS",
        "_internal/licenses/shapely/LICENSE_win32",
        "_internal/licenses/msvc-runtime/LICENSE",
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

    def _compliance_arguments(
        self,
        root: Path,
        built: Path,
        destination: Path,
        *,
        archive: Path | None = None,
        source_bundle_status: str = "release-approved",
        source_known_gaps: tuple[dict[str, object], ...] = (),
        source_manifest_commit: str | None = None,
        source_expected_commit: str | None = None,
        source_url_asset_name: str | None = None,
        source_hash_override: str | None = None,
        archive_manifest_matches: bool = True,
    ) -> tuple[str, ...]:
        archive = archive or Path(f"{destination}.zip")
        source_manifest_commit = (
            source_manifest_commit or self.CORRESPONDING_SOURCE_COMMIT
        )
        source_expected_commit = source_expected_commit or source_manifest_commit
        source_url_asset_name = (
            source_url_asset_name or self.CORRESPONDING_SOURCE_ASSET
        )
        source_url = (
            "https://github.com/Ponkichi0718/ChromaMatter/"
            f"releases/download/test/{source_url_asset_name}"
        )
        source_manifest = {
            "bundle_id": "chromamatter-windows-corresponding-source",
            "bundle_status": source_bundle_status,
            "components": [
                {
                    "commit": source_manifest_commit,
                    "destination": "components/ChromaMatter",
                    "display_name": "ChromaMatter",
                    "id": "chromamatter",
                    "kind": "local-git-commit-export",
                    "source_url": (
                        "https://github.com/Ponkichi0718/ChromaMatter.git"
                    ),
                }
            ],
            "deterministic_metadata": True,
            "known_gaps": list(source_known_gaps),
            "schema_version": 1,
            "tool_version": "test-fixture",
        }
        source_manifest_path = root / "COMPONENT_SOURCES.json"
        source_manifest_payload = (
            json.dumps(source_manifest, sort_keys=True) + "\n"
        ).encode("utf-8")
        source_manifest_path.write_bytes(source_manifest_payload)
        source_archive = root / self.CORRESPONDING_SOURCE_ASSET
        archived_manifest_payload = source_manifest_payload
        if not archive_manifest_matches:
            archived_manifest = dict(source_manifest)
            archived_manifest["archive_fixture_variant"] = True
            archived_manifest_payload = (
                json.dumps(archived_manifest, sort_keys=True) + "\n"
            ).encode("utf-8")
        with ZipFile(source_archive, "w") as package:
            prefix = "ChromaMatter-complete-corresponding-source/"
            package.writestr(prefix + "COMPONENT_SOURCES.json", archived_manifest_payload)
            package.writestr(
                prefix + "components/ChromaMatter/README.md",
                b"synthetic complete corresponding source\n",
            )
        source_archive_sha256 = hashlib.sha256(source_archive.read_bytes()).hexdigest()
        if source_hash_override is not None:
            source_archive_sha256 = source_hash_override
        versions = {
            "chromamatter": ("0.8beta-r32", "GPL-3.0-or-later"),
            "cpython": ("3.13.14", "Python-2.0"),
            "pyinstaller": (
                "6.20.0",
                "(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0",
            ),
            "tetgen": ("0.8.3 / 1.6.0", "MIT AND AGPL-3.0-or-later"),
            "pymeshlab": ("2025.7.post1", "GPL-3.0-only"),
            "qt": ("5.15.2", "LGPL-3.0-only"),
            "pytetwild": ("0.3.0", "MPL-2.0"),
            "shapely": ("2.1.2", "BSD-3-Clause"),
            "geos": ("3.13.1", "LGPL-2.1-or-later"),
            "msvc-runtime": (
                "14.44.35112",
                "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            ),
        }
        components = [
            {
                "id": component_id,
                "name": component_id,
                "version": version,
                "license": license_expression,
                "source": f"https://github.com/example/{component_id}",
            }
            for component_id, (version, license_expression) in versions.items()
        ]
        exe_sha256 = hashlib.sha256(
            (built / "ChromaMatter.exe").read_bytes()
        ).hexdigest()
        component_map = {
            "schema": (
                "https://github.com/Ponkichi0718/ChromaMatter/"
                "schemas/binary-component-map-v1"
            ),
            "schema_version": 1,
            "generator": {"name": "fixture", "version": "1"},
            "package": {
                "name": "ChromaMatter",
                "version": "0.8beta-r32",
                "root": ".",
                "content_sha256": exe_sha256,
            },
            "components": components,
            "files": [
                {
                    "path": "ChromaMatter.exe",
                    "size": (built / "ChromaMatter.exe").stat().st_size,
                    "sha256": exe_sha256,
                    "file_type": "native",
                    "package_owners": [],
                    "components": ["chromamatter", "pyinstaller"],
                    "mapping_basis": "fixture",
                }
            ],
            "validation": {
                "passed": True,
                "file_count": 1,
                "native_file_count": 1,
                "mapped_native_file_count": 1,
                "unmapped_native_files": [],
                "reparse_points_not_traversed": [],
            },
        }
        map_path = root / f"{destination.name}-component-map.json"
        map_path.write_text(
            json.dumps(component_map, ensure_ascii=False),
            encoding="utf-8",
        )
        sbom_path = root / f"{destination.name}-sbom.json"
        sbom_path.write_text(
            json.dumps(
                {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.5",
                    "components": [
                        {"bom-ref": "component:cpython"},
                        {"bom-ref": "component:pyinstaller"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return (
            "-CorrespondingSourceUrl",
            source_url,
            "-CorrespondingSourceArchivePath",
            str(source_archive),
            "-CorrespondingSourceManifestPath",
            str(source_manifest_path),
            "-CorrespondingSourceArchiveSha256",
            source_archive_sha256,
            "-CorrespondingSourceProjectCommit",
            source_expected_commit,
            "-BinaryComponentMapPath",
            str(map_path),
            "-SbomPath",
            str(sbom_path),
        )

    @staticmethod
    def _argument_value(arguments: tuple[str, ...], name: str) -> str:
        index = arguments.index(name)
        return arguments[index + 1]

    def test_stage_manifest_zip_and_extracted_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)
            destination = root / "ChromaMatter_0.8beta-r32-ai-model-print-studio"
            archive = Path(f"{destination}.zip")
            compliance_arguments = self._compliance_arguments(
                root,
                built,
                destination,
            )

            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
                *compliance_arguments,
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
            source_offer = (
                destination / "licenses" / "SOURCE_OFFER_EN.txt"
            ).read_text(encoding="utf-8")
            self.assertIn(
                "releases/download/test/" + self.CORRESPONDING_SOURCE_ASSET,
                source_offer,
            )
            self.assertIn(self.CORRESPONDING_SOURCE_ASSET, source_offer)
            self.assertIn(
                self._argument_value(
                    compliance_arguments,
                    "-CorrespondingSourceArchiveSha256",
                ).upper(),
                source_offer,
            )
            self.assertIn(self.CORRESPONDING_SOURCE_COMMIT, source_offer)
            self.assertNotIn("@@", source_offer)
            self.assertTrue(
                (destination / "licenses" / "BINARY_COMPONENT_MAP.json").is_file()
            )
            self.assertTrue(
                (destination / "licenses" / "SBOM.cdx.json").is_file()
            )
            self.assertEqual(
                {
                    path.name
                    for path in destination.iterdir()
                    if path.is_file()
                },
                {
                    "ChromaMatter.exe",
                    "LICENSE.txt",
                    "PRIVACY.md",
                    "README_EN.md",
                    "README_JA.md",
                    "SOFTWARE_PACKAGE_SHA256.txt",
                    "START_CHROMAMATTER.cmd",
                },
            )
            self.assertTrue((destination / "_internal").is_dir())
            self.assertTrue((destination / "licenses").is_dir())
            for excluded in (
                "CURRENT_STATE.json",
                "PROVENANCE.md",
                "VERSION_POLICY.md",
                "README_fixed_ja.md",
                "README_fixed_en.md",
                "START_FIXED.cmd",
                "publication",
            ):
                with self.subTest(excluded=excluded):
                    self.assertFalse((destination / excluded).exists())
            for readme_name in ("README_JA.md", "README_EN.md"):
                readme = (destination / readme_name).read_text(encoding="utf-8")
                self.assertIn("START_CHROMAMATTER.cmd", readme)
                self.assertIn("SOFTWARE_PACKAGE_SHA256.txt", readme)
                self.assertNotIn("CURRENT_STATE", readme)
                self.assertNotIn("PROVENANCE", readme)
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

    def test_complete_corresponding_source_gate_fails_closed(self) -> None:
        cases = (
            (
                "candidate bundle",
                {"source_bundle_status": "candidate-only-not-release-approved"},
                "not release-approved with an empty known_gaps array",
            ),
            (
                "unresolved gap",
                {
                    "source_known_gaps": (
                        {"id": "unresolved-source", "status": "unresolved"},
                    )
                },
                "not release-approved with an empty known_gaps array",
            ),
            (
                "wrong project commit",
                {"source_expected_commit": "2" * 40},
                "does not match the exact project commit",
            ),
            (
                "wrong archive hash",
                {"source_hash_override": "0" * 64},
                "archive SHA-256 does not match",
            ),
            (
                "URL asset mismatch",
                {"source_url_asset_name": "source.zip"},
                "URL asset name does not match",
            ),
            (
                "archived manifest mismatch",
                {"archive_manifest_matches": False},
                "manifest does not byte-match the archive",
            ),
        )
        for label, options, expected_error in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                built = self._fake_build(root)
                destination = root / "rejected-package"
                arguments = self._compliance_arguments(
                    root,
                    built,
                    destination,
                    **options,
                )

                result = _run_powershell(
                    SOFTWARE_STAGE_SCRIPT,
                    "-BuiltAppRoot",
                    str(built),
                    "-Destination",
                    str(destination),
                    *arguments,
                )

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn(expected_error, output)
                self.assertFalse(destination.exists())
                self.assertFalse(Path(f"{destination}.zip").exists())

    def test_stage_reuses_existing_output_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)
            destination_parent = root / "existing-stage-parent"
            archive_parent = root / "existing-archive-parent"
            destination_parent.mkdir()
            archive_parent.mkdir()
            stage_marker = destination_parent / "keep-stage-parent.txt"
            archive_marker = archive_parent / "keep-archive-parent.txt"
            stage_marker.write_text("keep\n", encoding="utf-8")
            archive_marker.write_text("keep\n", encoding="utf-8")
            destination = destination_parent / "public-package"
            archive = archive_parent / "public-package.zip"

            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
                "-ArchivePath",
                str(archive),
                *self._compliance_arguments(
                    root,
                    built,
                    destination,
                    archive=archive,
                ),
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertTrue(destination.is_dir())
            self.assertTrue(archive.is_file())
            self.assertEqual(stage_marker.read_text(encoding="utf-8"), "keep\n")
            self.assertEqual(archive_marker.read_text(encoding="utf-8"), "keep\n")

    def test_stage_rejects_a_file_used_as_an_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)
            parent_file = root / "not-a-directory"
            parent_file.write_text("keep\n", encoding="utf-8")
            destination = parent_file / "public-package"
            archive = root / "public-package.zip"

            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
                "-ArchivePath",
                str(archive),
                *self._compliance_arguments(
                    root,
                    built,
                    destination,
                    archive=archive,
                ),
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn(
                "Software-package destination parent is not a directory",
                output,
            )
            self.assertEqual(parent_file.read_text(encoding="utf-8"), "keep\n")
            self.assertFalse(archive.exists())

    def test_stage_script_uses_only_public_binary_documents(self) -> None:
        stage = SOFTWARE_STAGE_SCRIPT.read_text(encoding="utf-8")
        for required in (
            "source/fixed_app/public_binary/README_JA.md",
            "source/fixed_app/public_binary/README_EN.md",
            "source/fixed_app/public_binary/PRIVACY.md",
            "source/fixed_app/public_binary/START_CHROMAMATTER.cmd",
            '@{ Source = "LICENSE"; Destination = "LICENSE.txt" }',
        ):
            with self.subTest(required=required):
                self.assertIn(required, stage)
        for excluded in (
            '@{ Source = "CURRENT_STATE.json"',
            '@{ Source = "PROVENANCE.md"',
            "source/fixed_app/VERSION_POLICY.md",
            "source/fixed_app/README_fixed_ja.md",
            "source/fixed_app/README_fixed_en.md",
            "publication/INNOVATION_FUND_APPLICATION_DRAFT.md",
            "publication/INNOVATION_FUND_STATUS_JA.md",
        ):
            with self.subTest(excluded=excluded):
                self.assertNotIn(excluded, stage)

    def test_software_stage_uses_public_win64_default_name(self) -> None:
        stage = SOFTWARE_STAGE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            '"artifacts\\ChromaMatter-0.8beta-r32-win64"',
            stage,
        )
        policy = (
            REPO_ROOT / "source" / "fixed_app" / "VERSION_POLICY.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Public software artifact: `ChromaMatter-0.8beta-r32-win64`",
            policy,
        )

    def test_software_stage_requires_frozen_runtime_compliance_assets(self) -> None:
        stage = SOFTWARE_STAGE_SCRIPT.read_text(encoding="utf-8")
        for required in (
            '"_internal/licenses/cpython/LICENSE.txt"',
            '"_internal/licenses/pyinstaller/COPYING.txt"',
            '"cpython" = "Python-2.0"',
            '"pyinstaller" = "(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0"',
            '"component:cpython"',
            '"component:pyinstaller"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, stage)

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
                *self._compliance_arguments(root, built, destination),
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
                *self._compliance_arguments(root, built, destination),
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
                *self._compliance_arguments(root, built, destination),
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
                *self._compliance_arguments(root, built, destination),
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
                *self._compliance_arguments(root, built, existing_destination),
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
                *self._compliance_arguments(
                    root,
                    built,
                    destination,
                    archive=existing_archive,
                ),
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("Refusing to overwrite an existing software archive", output)
            self.assertEqual(existing_archive.read_bytes(), b"keep archive")
            self.assertFalse(destination.exists())

    def test_missing_source_offer_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self._fake_build(root)
            destination = root / "missing-compliance-inputs"
            result = _run_powershell(
                SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot",
                str(built),
                "-Destination",
                str(destination),
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("CorrespondingSourceUrl is required", output)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(f"{destination}.zip").exists())

    def test_spec_drops_upstream_pymeshlab_test_meshes(self) -> None:
        spec = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn('.startswith("pymeshlab/tests/")', spec)

    def test_spec_uses_the_pinned_pyinstaller_wheel_license_path(self) -> None:
        spec = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn(
            '"pyinstaller-6.20.0.dist-info/licenses/COPYING.txt"',
            spec,
        )
        self.assertNotIn(
            '"pyinstaller-6.20.0.dist-info/COPYING.txt"',
            spec,
        )

    def test_spec_drops_link_time_lib_archives_from_data_and_binaries(self) -> None:
        spec = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn("def is_windows_import_library(entry):", spec)
        self.assertIn("and not is_windows_import_library(entry)", spec)
        self.assertIn(
            "a.binaries = [\n"
            "    entry for entry in a.binaries if not is_windows_import_library(entry)\n"
            "]",
            spec,
        )

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
        self.assertIn('"tooling/stage_corresponding_source.py"', stage)
        self.assertIn('"tooling/stage_corresponding_source.ps1"', stage)
        self.assertIn('"tooling/corresponding_source_components.json"', stage)
        self.assertIn('"tooling/BUILD_PYTETWILD_WINDOWS.ps1"', stage)
        self.assertIn('"tooling/requirements-pytetwild-build.lock"', stage)
        self.assertIn(
            '"tooling/patches/pytetwild-0.3.0-optional-pyvista.patch"', stage
        )
        self.assertIn('"tooling/meshlab_windows_external_archives.lock.json"', stage)
        self.assertIn('"tooling/pytetwild_rebuild_lock.template.json"', stage)
        self.assertIn('"tooling/generate_binary_compliance_inventory.py"', stage)
        self.assertIn('"tooling/update_budget_filament_library.py"', stage)
        self.assertIn('"source/fixed_app/requirements-build.lock"', stage)
        self.assertIn('"AGENTS.md"', stage)
        self.assertIn('"HANDOFF.md"', stage)
        self.assertIn('"publication/BINARY_RELEASE_HANDOFF_JA.md"', stage)
        for relative in (
            "source/fixed_app/public_binary/README_JA.md",
            "source/fixed_app/public_binary/README_EN.md",
            "source/fixed_app/public_binary/PRIVACY.md",
            "source/fixed_app/public_binary/START_CHROMAMATTER.cmd",
        ):
            with self.subTest(public_binary_file=relative):
                self.assertIn(f'"{relative}"', stage)
        self.assertNotIn(
            'Copy-PublicDirectory -RelativePath "source/fixed_app/public_binary"',
            stage,
        )
        self.assertIn("Unexpected public-binary entry is not allowlisted", stage)

    def test_public_source_stage_reuses_an_existing_destination_parent(self) -> None:
        stage = (REPO_ROOT / "tooling" / "stage_public_source.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "if (Test-Path -LiteralPath $destinationParent)",
            stage,
        )
        self.assertIn(
            "Public-source destination parent is not a directory",
            stage,
        )

    def test_public_source_stage_uses_english_default_and_feedback_templates(self) -> None:
        stage = (REPO_ROOT / "tooling" / "stage_public_source.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('"FEATURES_EN.md"', stage)
        self.assertIn(
            '-SourceRelativePath "README_PUBLIC_EN.md" `\n'
            '    -DestinationRelativePath "README.md"',
            stage,
        )
        self.assertIn(
            '-SourceRelativePath "README_PUBLIC_JA.md" `\n'
            '    -DestinationRelativePath "README_JA.md"',
            stage,
        )
        for relative in (
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/ISSUE_TEMPLATE/compatibility_report.yml",
            ".github/ISSUE_TEMPLATE/config.yml",
        ):
            with self.subTest(relative=relative):
                self.assertIn(f'"{relative}"', stage)

    def test_github_feedback_templates_are_structured_and_privacy_safe(self) -> None:
        forms = (
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/ISSUE_TEMPLATE/compatibility_report.yml",
        )
        for relative in forms:
            with self.subTest(relative=relative):
                text = (REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertTrue(text.startswith("name: "))
                self.assertIn("\ndescription: ", text)
                self.assertIn("\nbody:\n", text)
                self.assertNotIn("\t", text)
                ids = re.findall(r"(?m)^    id: ([a-z0-9_]+)$", text)
                self.assertTrue(ids)
                self.assertEqual(len(ids), len(set(ids)))
                self.assertIn("validations:\n      required: true", text)

        form_texts = tuple(
            (REPO_ROOT / relative).read_text(encoding="utf-8").casefold()
            for relative in forms
        )
        compatibility = form_texts[2]
        for text in form_texts:
            self.assertIn("personal paths", text)
            self.assertIn("permission to share", text)
        self.assertIn("  - compatibility\n", compatibility)

        config = (
            REPO_ROOT / ".github/ISSUE_TEMPLATE/config.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("blank_issues_enabled: false", config)
        self.assertIn("https://note.com/ponkichi0718", config)

    def test_gitignore_keeps_required_publication_inputs_addable(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for required_negation in (
            "!publication/INNOVATION_FUND_APPLICATION_DRAFT.md",
            "!publication/INNOVATION_FUND_STATUS_JA.md",
            "!publication/BINARY_RELEASE_HANDOFF_JA.md",
            "!tooling/generate_binary_compliance_inventory.py",
            "!tooling/update_budget_filament_library.py",
            "!tooling/corresponding_source_components.json",
            "!tooling/BUILD_PYTETWILD_WINDOWS.ps1",
            "!tooling/requirements-pytetwild-build.lock",
            "!tooling/patches/pytetwild-0.3.0-optional-pyvista.patch",
            "!tooling/meshlab_windows_external_archives.lock.json",
            "!tooling/pytetwild_rebuild_lock.template.json",
            "!tooling/stage_corresponding_source.py",
            "!tooling/stage_corresponding_source.ps1",
            "!tooling/stage_software_package.ps1",
        ):
            with self.subTest(required_negation=required_negation):
                self.assertIn(required_negation, gitignore.splitlines())


class PublicSourceStageRollbackTests(unittest.TestCase):
    REQUIRED_ROOT_FILES = (
        ".gitignore",
        ".gitattributes",
        "BUILD_AND_TEST.ps1",
        "BOOTSTRAP_WINDOWS.ps1",
        "AGENTS.md",
        "HANDOFF.md",
        "RUN_TESTS.cmd",
        "CURRENT_STATE.json",
        "PROVENANCE.md",
        "FEATURES_EN.md",
        "FEATURES_JA.md",
        "README_PUBLIC_JA.md",
        "README_PUBLIC_EN.md",
    )
    REQUIRED_GITHUB_FILES = (
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/compatibility_report.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
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
        "publication/BINARY_RELEASE_HANDOFF_JA.md",
    )
    REQUIRED_FIXED_APP_FILES = (
        "source/fixed_app/TripoSpectrumMapper_fixed.py",
        "source/fixed_app/TripoSpectrumMapper_fixed.spec",
        "source/fixed_app/requirements-build.lock",
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
    REQUIRED_PUBLIC_BINARY_FILES = (
        "source/fixed_app/public_binary/README_JA.md",
        "source/fixed_app/public_binary/README_EN.md",
        "source/fixed_app/public_binary/PRIVACY.md",
        "source/fixed_app/public_binary/START_CHROMAMATTER.cmd",
    )

    def _source_fixture(self, root: Path) -> Path:
        fixture = root / "fixture-repository"
        for relative in (
            self.REQUIRED_ROOT_FILES
            + self.REQUIRED_GITHUB_FILES
            + self.REQUIRED_PUBLICATION_FILES
            + self.REQUIRED_FIXED_APP_FILES
            + self.REQUIRED_PUBLIC_BINARY_FILES
        ):
            path = fixture / Path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic public source fixture\n")

        required_directories = (
            "licenses",
            "samples",
            "source/fixed_app/spectrum_mapper",
            "source/fixed_app/resources/filament_db",
            "source/fixed_app/public_binary",
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
        shutil.copy2(
            REPO_ROOT / "tooling" / "stage_corresponding_source.py",
            tooling / "stage_corresponding_source.py",
        )
        shutil.copy2(
            REPO_ROOT / "tooling" / "stage_corresponding_source.ps1",
            tooling / "stage_corresponding_source.ps1",
        )
        shutil.copy2(
            REPO_ROOT / "tooling" / "corresponding_source_components.json",
            tooling / "corresponding_source_components.json",
        )
        shutil.copy2(
            REPO_ROOT / "tooling" / "BUILD_PYTETWILD_WINDOWS.ps1",
            tooling / "BUILD_PYTETWILD_WINDOWS.ps1",
        )
        shutil.copy2(
            REPO_ROOT / "tooling" / "requirements-pytetwild-build.lock",
            tooling / "requirements-pytetwild-build.lock",
        )
        patch_directory = tooling / "patches"
        patch_directory.mkdir()
        shutil.copy2(
            REPO_ROOT
            / "tooling"
            / "patches"
            / "pytetwild-0.3.0-optional-pyvista.patch",
            patch_directory / "pytetwild-0.3.0-optional-pyvista.patch",
        )
        shutil.copy2(
            REPO_ROOT / "tooling" / "meshlab_windows_external_archives.lock.json",
            tooling / "meshlab_windows_external_archives.lock.json",
        )
        shutil.copy2(
            REPO_ROOT / "tooling" / "pytetwild_rebuild_lock.template.json",
            tooling / "pytetwild_rebuild_lock.template.json",
        )
        shutil.copy2(
            REPO_ROOT / "tooling" / "generate_binary_compliance_inventory.py",
            tooling / "generate_binary_compliance_inventory.py",
        )
        shutil.copy2(
            REPO_ROOT / "tooling" / "update_budget_filament_library.py",
            tooling / "update_budget_filament_library.py",
        )
        shutil.copy2(
            REPO_ROOT / "source" / "fixed_app" / "test_binary_compliance_inventory.py",
            fixture / "source" / "fixed_app" / "test_binary_compliance_inventory.py",
        )
        (tooling / "generate_public_icon.py").write_text(
            "# synthetic public fixture\n",
            encoding="utf-8",
        )
        return fixture

    def test_public_binary_documents_are_copied_into_public_source_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._source_fixture(root)
            destination = root / "release-output" / "public-source-stage"

            result = _run_powershell(
                fixture / "tooling" / SOURCE_STAGE_SCRIPT.name,
                "-Destination",
                str(destination),
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            for relative in self.REQUIRED_PUBLIC_BINARY_FILES:
                with self.subTest(relative=relative):
                    self.assertTrue((destination / relative).is_file())
            manifest = (destination / "SOURCE_MANIFEST_SHA256.txt").read_text(
                encoding="utf-8"
            )
            for relative in self.REQUIRED_PUBLIC_BINARY_FILES:
                with self.subTest(manifest_entry=relative):
                    self.assertIn(relative, manifest)

    def test_unknown_public_binary_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._source_fixture(root)
            extra = fixture / "source" / "fixed_app" / "public_binary" / "UNLISTED.md"
            extra.write_text("ordinary unlisted release note\n", encoding="utf-8")
            output_root = root / "release-output"
            destination = output_root / "public-source-stage"

            result = _run_powershell(
                fixture / "tooling" / SOURCE_STAGE_SCRIPT.name,
                "-Destination",
                str(destination),
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("Unexpected public-binary entry is not allowlisted", output)
            self.assertFalse(destination.exists())
            self.assertFalse(output_root.exists())

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
