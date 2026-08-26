from __future__ import annotations

from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

from samples import generate_macos_alpha_test_glb
from tooling import stage_macos_source_package as package_tool


FIXED_APP = Path(__file__).resolve().parent
REPOSITORY = FIXED_APP.parents[1]


class MacOSSourcePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        head = subprocess.run(
            ["git", "-C", os.fspath(REPOSITORY), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
        if head.returncode != 0:
            raise unittest.SkipTest("source package tests require a Git worktree")
        cls.source_commit = head.stdout.strip()
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)

        cls.app = cls.root / package_tool.APP_NAME
        package_tool.source_app.stage(
            REPOSITORY,
            cls.app,
            cls.source_commit,
        )

        cls.public_test = cls.root / package_tool.PUBLIC_TEST_NAME
        cls.public_test.write_bytes(generate_macos_alpha_test_glb.build_glb_bytes())

        cls.contract, payload_data = cls._synthetic_contract()
        cls.demo = cls.root / "input-demo"
        cls.demo.mkdir()
        (cls.demo / package_tool.DEMO_MANIFEST_NAME).write_bytes(
            cls.contract.manifest_bytes
        )
        for name, data in cls.contract.documents.items():
            (cls.demo / name).write_bytes(data)
        for payload in cls.contract.payloads:
            path = cls.demo.joinpath(*PurePosixPath(payload.path).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload_data[payload.path])

        cls.stable_archive = cls.root / package_tool.STABLE_ARCHIVE_NAME
        cls._write_archive(cls.stable_archive)
        cls.stable_archive_bytes = cls.stable_archive.stat().st_size
        cls.stable_archive_sha256 = hashlib.sha256(
            cls.stable_archive.read_bytes()
        ).hexdigest()

        cls.package = cls.root / package_tool.PACKAGE_NAME
        with cls._production_input_patches():
            package_tool.stage(
                REPOSITORY,
                cls.app,
                cls.demo,
                cls.stable_archive,
                cls.public_test,
                cls.package,
                cls.source_commit,
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @classmethod
    def _synthetic_contract(
        cls,
    ) -> tuple[package_tool.DemoContract, dict[str, bytes]]:
        payloads: list[package_tool.DemoPayload] = []
        payload_data: dict[str, bytes] = {}
        for index, expected in enumerate(package_tool.EXPECTED_DEMO_PAYLOADS):
            path, _size, _sha256, media_type, role = expected
            data = f"reviewed-test-payload-{index}\n".encode("ascii")
            payload_data[path] = data
            payloads.append(
                package_tool.DemoPayload(
                    path=path,
                    bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    media_type=media_type,
                    role=role,
                )
            )
        documents = {
            name: f"canonical {name}\n".encode("utf-8")
            for name in package_tool.DEMO_DOCUMENTS
        }
        manifest = {
            "schema_version": 2,
            "document_id": package_tool.DEMO_DOCUMENT_ID,
            "release_status": "approved-for-publication",
            "expected_documents": list(package_tool.DEMO_DOCUMENTS),
            "payloads": [
                {
                    "path": payload.path,
                    "bytes": payload.bytes,
                    "sha256": payload.sha256,
                    "media_type": payload.media_type,
                    "role": payload.role,
                }
                for payload in payloads
            ],
            "publication_gate": package_tool.EXPECTED_PUBLICATION_GATE,
        }
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        ).encode("ascii")
        return (
            package_tool.DemoContract(
                manifest_bytes=manifest_bytes,
                documents=documents,
                payloads=tuple(payloads),
            ),
            payload_data,
        )

    @classmethod
    def _write_archive(
        cls,
        path: Path,
        *,
        extra_members: dict[str, bytes] | None = None,
    ) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                f"{package_tool.STABLE_ARCHIVE_ROOT}/ChromaMatter.exe",
                b"synthetic non-demo package member",
            )
            for file in sorted(cls.demo.rglob("*"), key=lambda item: item.as_posix()):
                if file.is_file():
                    relative = file.relative_to(cls.demo).as_posix()
                    archive.writestr(
                        f"{package_tool.STABLE_DEMO_PREFIX}/{relative}",
                        file.read_bytes(),
                    )
            for name, data in (extra_members or {}).items():
                archive.writestr(name, data)

    @classmethod
    @contextmanager
    def _production_input_patches(cls):
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    package_tool,
                    "_load_demo_contract",
                    return_value=cls.contract,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    package_tool,
                    "STABLE_ARCHIVE_BYTES",
                    cls.stable_archive_bytes,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    package_tool,
                    "STABLE_ARCHIVE_SHA256",
                    cls.stable_archive_sha256,
                )
            )
            yield

    def _fresh_package(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        destination = Path(temporary.name) / package_tool.PACKAGE_NAME
        shutil.copytree(self.package, destination)
        return temporary, destination

    def _audit(self, package: Path) -> dict[str, object]:
        with self._production_input_patches():
            return package_tool.audit(REPOSITORY, package)

    @contextmanager
    def _archive_input_patches(self, archive: Path):
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    package_tool,
                    "_load_demo_contract",
                    return_value=self.contract,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    package_tool,
                    "STABLE_ARCHIVE_BYTES",
                    archive.stat().st_size,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    package_tool,
                    "STABLE_ARCHIVE_SHA256",
                    hashlib.sha256(archive.read_bytes()).hexdigest(),
                )
            )
            yield

    def test_verified_archive_extracts_exact_demo_data_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "DemoData"
            with self._production_input_patches():
                package_tool.extract_demo_data(
                    REPOSITORY,
                    self.stable_archive,
                    output,
                    self.source_commit,
                )
            self.assertTrue(output.is_dir())
            self.assertEqual(
                {
                    path.relative_to(output).as_posix()
                    for path in output.rglob("*")
                    if path.is_file()
                },
                package_tool._expected_demo_files(self.contract),
            )
            package_tool._validate_demo_data(output, self.contract)

    def test_stable_archive_byte_tamper_fails_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            archive = Path(raw) / package_tool.STABLE_ARCHIVE_NAME
            shutil.copyfile(self.stable_archive, archive)
            damaged = bytearray(archive.read_bytes())
            damaged[-1] ^= 0x01
            archive.write_bytes(damaged)
            output = Path(raw) / "DemoData"
            with mock.patch.object(
                package_tool,
                "STABLE_ARCHIVE_BYTES",
                self.stable_archive_bytes,
            ), mock.patch.object(
                package_tool,
                "STABLE_ARCHIVE_SHA256",
                self.stable_archive_sha256,
            ):
                with self.assertRaisesRegex(
                    package_tool.SourcePackageError,
                    "archive SHA-256 is invalid",
                ):
                    package_tool.extract_demo_data(
                        REPOSITORY,
                        archive,
                        output,
                        self.source_commit,
                    )
            self.assertFalse(output.exists())

    def test_unexpected_demo_archive_entry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            archive = Path(raw) / package_tool.STABLE_ARCHIVE_NAME
            self._write_archive(
                archive,
                extra_members={
                    f"{package_tool.STABLE_DEMO_PREFIX}/unexpected.txt": b"extra"
                },
            )
            output = Path(raw) / "DemoData"
            with self._archive_input_patches(archive):
                with self.assertRaisesRegex(
                    package_tool.SourcePackageError,
                    "Unexpected DemoData file",
                ):
                    package_tool.extract_demo_data(
                        REPOSITORY,
                        archive,
                        output,
                        self.source_commit,
                    )
            self.assertFalse(output.exists())

    def test_traversal_and_backslash_archive_entries_fail_closed(self) -> None:
        for unsafe in (
            "../escape.txt",
            f"{package_tool.STABLE_ARCHIVE_ROOT}/DemoData/../escape.txt",
            f"{package_tool.STABLE_ARCHIVE_ROOT}\\DemoData\\escape.txt",
        ):
            with self.subTest(path=unsafe), tempfile.TemporaryDirectory() as raw:
                archive = Path(raw) / package_tool.STABLE_ARCHIVE_NAME
                self._write_archive(archive, extra_members={unsafe: b"escape"})
                output = Path(raw) / "DemoData"
                with self._archive_input_patches(archive):
                    with self.assertRaisesRegex(
                        package_tool.SourcePackageError,
                        "archive path|Unexpected DemoData file",
                    ):
                        package_tool.extract_demo_data(
                            REPOSITORY,
                            archive,
                            output,
                            self.source_commit,
                        )
                self.assertFalse(output.exists())

    def test_duplicate_and_symlink_archive_entries_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            archive = Path(raw) / package_tool.STABLE_ARCHIVE_NAME
            duplicate = (
                f"{package_tool.STABLE_DEMO_PREFIX}/"
                f"{self.contract.payloads[0].path}"
            )
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Duplicate name:",
                    category=UserWarning,
                )
                self._write_archive(archive, extra_members={duplicate: b"duplicate"})
            output = Path(raw) / "DemoData"
            with self._archive_input_patches(archive):
                with self.assertRaisesRegex(
                    package_tool.SourcePackageError,
                    "Duplicate stable archive path",
                ):
                    package_tool.extract_demo_data(
                        REPOSITORY,
                        archive,
                        output,
                        self.source_commit,
                    )
            self.assertFalse(output.exists())

        with tempfile.TemporaryDirectory() as raw:
            archive = Path(raw) / package_tool.STABLE_ARCHIVE_NAME
            self._write_archive(archive)
            link = zipfile.ZipInfo(
                f"{package_tool.STABLE_DEMO_PREFIX}/unexpected-link"
            )
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(
                archive,
                "a",
                compression=zipfile.ZIP_DEFLATED,
            ) as package:
                package.writestr(link, "README_EN.md")
            output = Path(raw) / "DemoData"
            with self._archive_input_patches(archive):
                with self.assertRaisesRegex(
                    package_tool.SourcePackageError,
                    "Special archive member",
                ):
                    package_tool.extract_demo_data(
                        REPOSITORY,
                        archive,
                        output,
                        self.source_commit,
                    )
            self.assertFalse(output.exists())

    def test_stable_r32_2_contract_is_exact_and_rights_approved(self) -> None:
        contract = package_tool._load_demo_contract(
            REPOSITORY,
            self.source_commit,
        )
        self.assertEqual(len(contract.payloads), package_tool.DEMO_PAYLOAD_COUNT)
        self.assertEqual(contract.payload_bytes, package_tool.DEMO_PAYLOAD_BYTES)
        self.assertEqual(
            sum(item.path.casefold().endswith(".3mf") for item in contract.payloads),
            package_tool.DEMO_3MF_COUNT,
        )
        self.assertEqual(
            hashlib.sha256(contract.manifest_bytes).hexdigest(),
            package_tool.DEMO_CANONICAL_FILE_SHA256[
                package_tool.DEMO_MANIFEST_NAME
            ],
        )
        self.assertEqual(
            package_tool.STABLE_ARCHIVE_NAME,
            "ChromaMatter-0.8beta-r32.2-win64.zip",
        )
        self.assertEqual(package_tool.STABLE_ARCHIVE_BYTES, 327_268_369)
        self.assertEqual(
            package_tool.STABLE_ARCHIVE_SHA256,
            "2ceada98661bac5d49b759542151c4c484fff4269d6b5d142ec32fec544f06d0",
        )

    def test_stage_and_independent_fresh_copy_audit(self) -> None:
        self.assertEqual(
            {item.name for item in self.package.iterdir()},
            package_tool._expected_top_level(),
        )
        manifest = json.loads(
            (self.package / package_tool.PACKAGE_MANIFEST_NAME).read_text(
                encoding="ascii"
            )
        )
        record_paths = {item["path"] for item in manifest["records"]}
        self.assertNotIn(package_tool.PACKAGE_MANIFEST_NAME, record_paths)
        self.assertNotIn(package_tool.PACKAGE_CHECKSUM_NAME, record_paths)
        self.assertIn(
            "DemoData/Original AI model Color.glb",
            record_paths,
        )
        self.assertIn(
            f"{package_tool.APP_NAME}/Contents/Info.plist",
            record_paths,
        )
        self.assertEqual(
            manifest["stable_demo_data"]["source_release_tag"],
            package_tool.STABLE_RELEASE_TAG,
        )
        checksum_lines = (
            self.package / package_tool.PACKAGE_CHECKSUM_NAME
        ).read_text(encoding="utf-8").splitlines()
        self.assertTrue(
            any(
                line.endswith("  " + package_tool.PACKAGE_MANIFEST_NAME)
                for line in checksum_lines
            )
        )
        self.assertFalse(
            any(
                line.endswith("  " + package_tool.PACKAGE_CHECKSUM_NAME)
                for line in checksum_lines
            )
        )
        checksum_paths: list[str] = []
        for line in checksum_lines:
            digest, separator, relative = line.partition("  ")
            self.assertEqual(separator, "  ")
            self.assertEqual(len(digest), 64)
            self.assertEqual(digest, digest.upper())
            self.assertNotIn("\\", relative)
            checksum_paths.append(relative)
        self.assertEqual(checksum_paths, sorted(checksum_paths))

        temporary, fresh = self._fresh_package()
        try:
            result = self._audit(fresh)
            self.assertEqual(
                result["status"],
                "source-backed-package-audit-passed",
            )
            self.assertEqual(result["source_commit"], self.source_commit)
            self.assertEqual(result["demo_file_count"], 15)
            self.assertEqual(result["demo_payload_count"], 10)
        finally:
            temporary.cleanup()

    def test_demo_payload_tamper_fails_closed(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            target = fresh / "DemoData" / self.contract.payloads[0].path
            target.write_bytes(target.read_bytes() + b"tamper")
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "DemoData payload mismatch",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_demo_document_tamper_fails_closed(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            target = fresh / "DemoData" / package_tool.DEMO_DOCUMENTS[0]
            target.write_bytes(target.read_bytes() + b"tamper")
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "document bytes do not match",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_outer_manifest_tamper_fails_closed(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            path = fresh / package_tool.PACKAGE_MANIFEST_NAME
            manifest = json.loads(path.read_text(encoding="ascii"))
            manifest["records"][0]["sha256"] = "0" * 64
            path.write_text(
                json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True)
                + "\n",
                encoding="ascii",
                newline="\n",
            )
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "manifest records mismatch",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_checksum_tamper_and_missing_file_fail_closed(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            path = fresh / package_tool.PACKAGE_CHECKSUM_NAME
            data = path.read_bytes()
            path.write_bytes((b"0" if data[:1] != b"0" else b"1") + data[1:])
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "checksum record does not match",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

        temporary, fresh = self._fresh_package()
        try:
            (fresh / package_tool.PACKAGE_CHECKSUM_NAME).unlink()
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "top-level allowlist mismatch",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_regenerated_manifests_cannot_hide_embedded_source_tamper(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            app = fresh / package_tool.APP_NAME
            target = (
                app
                / "Contents"
                / "Resources"
                / package_tool.source_app.SOURCE_DIRECTORY
                / "FEATURES_EN.md"
            )
            target.write_bytes(target.read_bytes() + b"\nforged embedded source\n")

            # Reproduce an internally self-consistent forgery: regenerate the
            # inner app manifest, outer manifest, and package checksum.  The
            # independent Git-byte comparison must still reject it.
            package_tool.source_app._write_manifest(app, self.source_commit)
            with self._production_input_patches():
                package_tool._write_package_manifest(
                    fresh,
                    self.source_commit,
                    self.contract,
                )
                (fresh / package_tool.PACKAGE_CHECKSUM_NAME).write_bytes(
                    package_tool._software_checksum_bytes(fresh)
                )
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "differs from the exact Git source commit",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_non_demo_file_tamper_fails_closed(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            target = fresh / package_tool.INSTALL_GUIDE_NAME
            target.write_bytes(target.read_bytes() + b"tamper")
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "Installation guide differs",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_source_commit_mismatch_fails_closed(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            (fresh / package_tool.SOURCE_COMMIT_NAME).write_text(
                "f" * 40 + "\n",
                encoding="ascii",
                newline="\n",
            )
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "SOURCE_COMMIT.txt does not match",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_extra_file_and_directory_fail_closed(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            (fresh / "unexpected.txt").write_text("unexpected", encoding="ascii")
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "top-level allowlist mismatch",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

        temporary, fresh = self._fresh_package()
        try:
            (fresh / "DemoData" / "empty-extra").mkdir()
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "DemoData allowlist mismatch",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_demo_symlink_fails_closed_when_supported(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            target = fresh / "DemoData" / self.contract.payloads[0].path
            link_target = Path(temporary.name) / "link-target.bin"
            link_target.write_bytes(target.read_bytes())
            target.unlink()
            try:
                target.symlink_to(link_target)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "Symlink is forbidden",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_required_root_symlink_is_rejected_before_content_read(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            target = fresh / package_tool.SOURCE_COMMIT_NAME
            outside = Path(temporary.name) / "outside-commit.txt"
            outside.write_text(self.source_commit + "\n", encoding="ascii")
            target.unlink()
            try:
                target.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "Symlink is forbidden",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_control_and_normalization_ambiguous_paths_are_rejected(self) -> None:
        for unsafe in ("line\nbreak", "tab\tpath", "return\rpath"):
            with self.subTest(path=unsafe), self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "Unsafe package path",
            ):
                package_tool._safe_relative(unsafe)
        self.assertEqual(
            package_tool._normalized_path_key("DemoData/e\N{COMBINING ACUTE ACCENT}"),
            package_tool._normalized_path_key("DemoData/\N{LATIN SMALL LETTER E WITH ACUTE}"),
        )

    @unittest.skipIf(os.name == "nt", "FIFO special files are POSIX-only")
    def test_demo_special_file_fails_closed(self) -> None:
        temporary, fresh = self._fresh_package()
        try:
            fifo = fresh / "DemoData" / self.contract.payloads[0].path
            fifo.unlink()
            os.mkfifo(fifo)
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "Special file is forbidden",
            ):
                self._audit(fresh)
        finally:
            temporary.cleanup()

    def test_wrong_package_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wrong = Path(raw) / "alpha2-wrong-name"
            with self.assertRaisesRegex(
                package_tool.SourcePackageError,
                "named exactly",
            ):
                with mock.patch.object(
                    package_tool,
                    "_load_demo_contract",
                    return_value=self.contract,
                ):
                    package_tool.stage(
                        REPOSITORY,
                        self.app,
                        self.demo,
                        self.stable_archive,
                        self.public_test,
                        wrong,
                        self.source_commit,
                    )


if __name__ == "__main__":
    unittest.main()
