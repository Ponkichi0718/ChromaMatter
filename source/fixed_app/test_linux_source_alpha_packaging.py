from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[2]
PACKAGER = REPOSITORY / "PACKAGE_LINUX_SOURCE_ALPHA.py"
SPEC = importlib.util.spec_from_file_location("linux_source_packager_test", PACKAGER)
assert SPEC is not None and SPEC.loader is not None
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


class LinuxSourceAlphaPackagingTests(unittest.TestCase):
    def test_packager_is_tracked_source_and_parses(self) -> None:
        source = PACKAGER.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('["git", "archive"', source)
        self.assertIn('["git", "ls-tree"', source)

    def test_packager_requires_exact_clean_commit_and_fresh_extract(self) -> None:
        source = PACKAGER.read_text(encoding="utf-8")
        for phrase in (
            '"rev-parse", "HEAD"',
            '"diff", "--quiet"',
            '"diff", "--cached", "--quiet"',
            'mode != "100755"',
            'filter="data"',
            'os.access(path, os.X_OK)',
            '"bash", "-n"',
            '"archive_sha256"',
            '"requirements_lock_sha256"',
        ):
            self.assertIn(phrase, source)

    def test_packager_excludes_common_binary_and_toolpath_payloads(self) -> None:
        source = PACKAGER.read_text(encoding="utf-8")
        for suffix in (".exe", ".dll", ".pyd", ".whl", ".3mf", ".gcode"):
            self.assertIn(f'"{suffix}"', source)


class LinuxSourceAlphaCrossHostTests(unittest.TestCase):
    COMMIT = "a" * 40

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="linux-source-candidate-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.archive = self.root / "candidate.tar.xz"
        self.audit_path = self.root / "audit.json"
        self.files = {
            "INSTALL_LINUX_SOURCE_ALPHA.sh": (b"#!/bin/sh\nexit 0\n", 0o755),
            "RUN_LINUX_SOURCE_ALPHA.sh": (b"#!/bin/sh\nexit 0\n", 0o755),
            packager.LOCK_RELATIVE: (b"sample==1 --hash=sha256:abc\n", 0o644),
            "source/fixed_app/example.py": (b"print('source only')\n", 0o644),
        }
        self.commands: list[list[str]] = []

    @staticmethod
    def write_tar(path: Path, entries: list[tuple[str, bytes, int]], *, compressed: bool = False) -> None:
        with tarfile.open(path, "w:xz" if compressed else "w") as archive:
            for name, data, mode in entries:
                info = tarfile.TarInfo(name)
                info.mode = mode
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def git_command(self, command: list[str], **_kwargs: object) -> str:
        self.commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return self.COMMIT
        if command[:2] == ["git", "diff"]:
            return ""
        if command[:2] == ["git", "ls-tree"]:
            relative = command[-1]
            mode = "100755" if self.files[relative][1] & 0o111 else "100644"
            return f"{mode} blob {'b' * 40}\t{relative}"
        if command[:2] == ["git", "show"]:
            return "1700000000"
        if command[:2] == ["git", "archive"]:
            destination = Path(command[command.index("-o") + 1])
            self.write_tar(destination, [
                (f"{packager.ARCHIVE_ROOT}/{name}", data, mode)
                for name, (data, mode) in self.files.items()
            ])
            return ""
        if command[:2] == ["bash", "-n"]:
            return ""
        self.fail(f"unexpected command: {command}")

    def build(self, *, cross_host: bool = True) -> dict[str, object]:
        with mock.patch.object(packager, "_run", side_effect=self.git_command):
            return packager.package(
                self.repository, self.archive, self.audit_path, self.COMMIT,
                cross_host_source_candidate=cross_host,
            )

    def expected_files(self) -> dict[str, dict[str, object]]:
        return {
            name: {
                "bytes": len(data), "mode": mode,
                "sha256": hashlib.sha256(data).hexdigest().upper(),
            }
            for name, (data, mode) in self.files.items()
        }

    def rewrite_archive(self, mutate) -> None:
        with tarfile.open(self.archive, "r:xz") as archive:
            entries = [
                (entry.name, archive.extractfile(entry).read(), entry.mode)
                for entry in archive.getmembers() if entry.isfile()
            ]
        self.write_tar(self.archive, mutate(entries), compressed=True)

    def audit(self) -> dict[str, object]:
        lock_hash = hashlib.sha256(self.files[packager.LOCK_RELATIVE][0]).hexdigest().upper()
        return packager._audit_archive(
            self.archive, self.COMMIT, lock_hash, self.expected_files(), cross_host=True,
        )

    def test_non_linux_default_still_refuses(self) -> None:
        with mock.patch.object(packager.sys, "platform", "win32"):
            with self.assertRaisesRegex(packager.PackageError, "run this packager on Linux"):
                self.build(cross_host=False)
        self.assertFalse(self.archive.exists())

    def test_cross_host_preserves_git_modes_and_reports_native_pending(self) -> None:
        with mock.patch.object(packager.sys, "platform", "win32"), mock.patch.object(
            packager.os, "access", side_effect=AssertionError("Windows X_OK is not a Git mode"),
        ):
            result = self.build()
        self.assertEqual(result["verification_mode"], "cross-host-static")
        self.assertEqual(result["shell_syntax"], "not-run-cross-host")
        self.assertEqual(result["linux_native_runtime_validation"], "pending-target-host")
        self.assertIs(result["frozen_binary_distribution_approved"], False)
        self.assertEqual(result["source_file_hashes_and_modes"], "passed")
        self.assertFalse(any(command[0] == "bash" for command in self.commands))
        with tarfile.open(self.archive, "r:xz") as archive:
            for relative, (_, mode) in self.files.items():
                self.assertEqual(archive.getmember(f"{packager.ARCHIVE_ROOT}/{relative}").mode, mode)
        self.assertEqual(json.loads(self.audit_path.read_text())["source_commit"], self.COMMIT)

    def test_default_linux_keeps_executable_and_shell_audits(self) -> None:
        with mock.patch.object(packager.sys, "platform", "linux"), mock.patch.object(
            packager.os, "access", return_value=True,
        ) as access:
            result = self.build(cross_host=False)
        self.assertEqual(access.call_count, 2)
        self.assertEqual(sum(command[0] == "bash" for command in self.commands), 2)
        self.assertEqual(result["verification_mode"], "linux-host-source-audit")
        self.assertEqual(result["shell_syntax"], "passed")

    def test_cross_host_cannot_bypass_dirty_checkout(self) -> None:
        real_command = self.git_command

        def command(arguments, **kwargs):
            if arguments[:2] == ["git", "diff"]:
                raise packager.PackageError("tracked worktree audit failed")
            return real_command(arguments, **kwargs)

        with mock.patch.object(packager, "_run", side_effect=command):
            with self.assertRaisesRegex(packager.PackageError, "worktree audit failed"):
                packager.package(self.repository, self.archive, self.audit_path, self.COMMIT,
                                 cross_host_source_candidate=True)
        self.assertFalse(self.archive.exists())

    def test_cross_host_requires_exact_commit(self) -> None:
        with mock.patch.object(packager, "_run", side_effect=self.git_command):
            with self.assertRaisesRegex(packager.PackageError, "exact checkout HEAD"):
                packager.package(self.repository, self.archive, self.audit_path, "b" * 40,
                                 cross_host_source_candidate=True)

    def test_archive_and_audit_cannot_overwrite_each_other(self) -> None:
        with self.assertRaisesRegex(packager.PackageError, "must be different files"):
            packager.package(self.repository, self.archive, self.archive, self.COMMIT,
                             cross_host_source_candidate=True)

    def test_cli_cross_host_mode_is_explicit_opt_in(self) -> None:
        base_arguments = [str(PACKAGER), "--repository", str(self.repository),
                          "--archive", str(self.archive), "--audit", str(self.audit_path),
                          "--source-commit", self.COMMIT]
        for option, expected in (([], False), (["--cross-host-source-candidate"], True)):
            with self.subTest(expected=expected), mock.patch.object(
                packager.sys, "argv", base_arguments + option,
            ), mock.patch.object(packager, "package", return_value={}) as build, mock.patch(
                "sys.stdout", new_callable=io.StringIO,
            ):
                self.assertEqual(packager.main(), 0)
                self.assertIs(build.call_args.kwargs["cross_host_source_candidate"], expected)

    def test_required_launcher_must_be_executable_in_git(self) -> None:
        name = packager.REQUIRED_EXECUTABLES[0]
        self.files[name] = (self.files[name][0], 0o644)
        with self.assertRaisesRegex(packager.PackageError, "must be tracked executable"):
            self.build()

    def test_archive_rejects_changed_source_bytes(self) -> None:
        self.build()
        self.rewrite_archive(lambda entries: [
            (name, b"changed", mode) if name.endswith("example.py") else (name, data, mode)
            for name, data, mode in entries
        ])
        with self.assertRaisesRegex(packager.PackageError, "paths, bytes or Git executable modes differ"):
            self.audit()

    def test_archive_rejects_extra_permission_bits(self) -> None:
        self.build()
        self.rewrite_archive(lambda entries: [
            (name, data, 0o777 if name.endswith(".sh") else mode)
            for name, data, mode in entries
        ])
        with self.assertRaisesRegex(packager.PackageError, "noncanonical archive permission"):
            self.audit()

    def test_archive_rejects_unexpected_and_missing_paths(self) -> None:
        self.build()
        self.rewrite_archive(lambda entries: [entry for entry in entries if not entry[0].endswith("example.py")])
        with self.assertRaisesRegex(packager.PackageError, "paths, bytes or Git executable modes differ"):
            self.audit()

    def test_archive_rejects_false_native_verification_metadata(self) -> None:
        self.build()

        def change(entries):
            changed = []
            for name, data, mode in entries:
                if name.endswith(packager.RELEASE_METADATA):
                    metadata = json.loads(data)
                    metadata["linux_native_runtime_validation"] = "passed"
                    data = json.dumps(metadata).encode()
                changed.append((name, data, mode))
            return changed

        self.rewrite_archive(change)
        with self.assertRaisesRegex(packager.PackageError, "misrepresents the verification scope"):
            self.audit()

    def test_rejects_runtime_or_demo_payload_before_extraction(self) -> None:
        for name in ("runtime.whl", "libcore.so", "DemoData/Reference.jpg", "private.glb"):
            with self.subTest(name=name):
                candidate = self.root / "hostile.tar"
                self.write_tar(candidate, [(f"{packager.ARCHIVE_ROOT}/{name}", b"payload", 0o644)])
                with tarfile.open(candidate) as archive, self.assertRaises(packager.PackageError):
                    packager._source_members(archive)

    def test_rejects_alias_paths_links_duplicates_and_devices(self) -> None:
        for name in ("/outside", f"{packager.ARCHIVE_ROOT}/../bad", f"{packager.ARCHIVE_ROOT}//bad",
                     f"{packager.ARCHIVE_ROOT}/./bad", f"{packager.ARCHIVE_ROOT}\\bad"):
            with self.subTest(name=name), self.assertRaises(packager.PackageError):
                packager._safe_member(name)
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind):
                candidate = self.root / "hostile.tar"
                with tarfile.open(candidate, "w") as archive:
                    entry = tarfile.TarInfo(f"{packager.ARCHIVE_ROOT}/bad")
                    entry.type = kind
                    entry.linkname = "outside"
                    archive.addfile(entry)
                with tarfile.open(candidate) as archive, self.assertRaises(packager.PackageError):
                    packager._source_members(archive)
        candidate = self.root / "duplicate.tar"
        self.write_tar(candidate, [(f"{packager.ARCHIVE_ROOT}/{name}", b"source", 0o644)
                                   for name in ("same.py", "SAME.py")])
        with tarfile.open(candidate) as archive, self.assertRaisesRegex(packager.PackageError, "duplicate"):
            packager._source_members(archive)


if __name__ == "__main__":
    unittest.main()
