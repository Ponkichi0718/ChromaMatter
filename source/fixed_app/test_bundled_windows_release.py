"""Self-contained Windows delivery retains the ordinary release safety gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import test_release_tooling as release_fixtures


class BundledWindowsReleaseDocumentationTests(unittest.TestCase):
    def test_bilingual_rebuild_docs_use_current_bundle_and_attested_recipe(self) -> None:
        for language in ("EN", "JA"):
            with self.subTest(language=language):
                document = (release_fixtures.REPO_ROOT / "licenses" /
                            f"BUILD_ENVIRONMENT_{language}.md").read_text(encoding="utf-8")
                self.assertIn("ChromaMatter-0.9-complete-corresponding-source.zip", document)
                self.assertIn("-Destination C:\\release\\ChromaMatter-0.9-win64", document)
                self.assertIn("-BundleCorrespondingSource", document)
                self.assertIn("corresponding-source/", document)
                self.assertIn("-Offline", document)
                self.assertIn(
                    "-File .\\tooling\\recipes\\BUILD_PYTETWILD_WINDOWS_20260823.ps1",
                    document,
                )
                self.assertIn("-RequirementsLock .\\tooling\\requirements-pytetwild-build.lock", document)
                self.assertIn(
                    "-PyTetWildSourcePatch .\\tooling\\patches\\pytetwild-0.3.0-optional-pyvista.patch",
                    document,
                )
                self.assertIn(
                    "d00cc6cdbc61abeaa040dfc81a3dfe7086ac0027685d798ac70f46e14e4360c8",
                    document,
                )
                self.assertNotIn("github.com/OWNER/REPO", document)
                self.assertNotIn("ChromaMatter-0.8beta-r32-complete-corresponding-source", document)


@unittest.skipUnless(release_fixtures.POWERSHELL, "Windows PowerShell is unavailable")
class BundledWindowsReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        # Compose the existing fully mapped synthetic-runtime fixture without
        # inheriting (and thereby rerunning) its entire release test suite.
        self.fixture = release_fixtures.SoftwarePackageStageTests()

    @staticmethod
    def _without_network_url(arguments: tuple[str, ...]) -> tuple[str, ...]:
        index = arguments.index("-CorrespondingSourceUrl")
        return arguments[:index] + arguments[index + 2 :]

    def _stage(self, root: Path, **fixture_options):
        built = self.fixture._fake_build(root)
        destination = root / "ChromaMatter-0.9-win64"
        arguments = self.fixture._compliance_arguments(
            root, built, destination, **fixture_options
        )
        result = release_fixtures._run_powershell(
            release_fixtures.SOFTWARE_STAGE_SCRIPT,
            "-BuiltAppRoot", str(built),
            "-Destination", str(destination),
            "-BundleCorrespondingSource",
            *self._without_network_url(arguments),
        )
        return result, destination, arguments

    def test_bundled_archive_is_exact_and_covered_by_manifest_and_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, destination, arguments = self._stage(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            source_path = Path(self.fixture._argument_value(
                arguments, "-CorrespondingSourceArchivePath"
            ))
            relative_source = "corresponding-source/" + source_path.name
            bundled = destination / relative_source
            source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
            self.assertEqual(bundled.read_bytes(), source_path.read_bytes())
            release_fixtures._assert_relative_manifest(
                self, destination, "SOFTWARE_PACKAGE_SHA256.txt"
            )
            manifest = (destination / "SOFTWARE_PACKAGE_SHA256.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn(source_digest.upper() + "  " + relative_source, manifest)
            for language in ("EN", "JA"):
                notice = (destination / "licenses" / f"SOURCE_OFFER_{language}.txt").read_text(
                    encoding="utf-8"
                )
                self.assertIn(relative_source, notice)
                self.assertIn(source_digest.upper(), notice)
                self.assertIn(self.fixture.CORRESPONDING_SOURCE_COMMIT, notice)
                self.assertNotIn("@@", notice)
                self.assertNotIn("https://", notice)
            japanese_notice = (destination / "licenses" / "SOURCE_OFFER_JA.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("完全対応ソースを同梱", japanese_notice)
            with ZipFile(Path(f"{destination}.zip")) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(
                    archive.read(destination.name + "/" + relative_source),
                    source_path.read_bytes(),
                )

    def test_bundle_retains_all_exact_source_approval_checks(self) -> None:
        cases = (
            ({"source_hash_override": "0" * 64}, "SHA-256 does not match"),
            ({"source_bundle_status": "candidate-only-not-release-approved"}, "not release-approved"),
            ({"source_known_gaps": ({"id": "unresolved-native-input"},)}, "not release-approved"),
            ({"source_expected_commit": "2" * 40}, "exact project commit"),
            ({"archive_manifest_matches": False}, "does not byte-match the archive"),
        )
        for options, message in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                result, destination, _ = self._stage(root, **options)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn(message, output)
                self.assertFalse(destination.exists())
                self.assertFalse(Path(f"{destination}.zip").exists())
                self.fixture._assert_no_stage_debris(root, destination)

    def test_bundle_does_not_accept_a_network_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self.fixture._fake_build(root)
            destination = root / "inconsistent-source-location"
            arguments = self.fixture._compliance_arguments(root, built, destination)
            result = release_fixtures._run_powershell(
                release_fixtures.SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot", str(built),
                "-Destination", str(destination),
                "-BundleCorrespondingSource", *arguments,
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("must not also declare a network source URL", output)
            self.assertFalse(destination.exists())

    def test_network_delivery_still_requires_a_real_source_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self.fixture._fake_build(root)
            destination = root / "missing-source-location"
            arguments = self.fixture._compliance_arguments(root, built, destination)
            result = release_fixtures._run_powershell(
                release_fixtures.SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot", str(built),
                "-Destination", str(destination),
                *self._without_network_url(arguments),
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("CorrespondingSourceUrl is required", output)
            self.assertFalse(destination.exists())

    def test_bundled_delivery_still_rejects_stale_runtime_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self.fixture._fake_build(root)
            destination = root / "stale-runtime-inventory"
            arguments = self.fixture._compliance_arguments(root, built, destination)
            map_path = Path(self.fixture._argument_value(arguments, "-BinaryComponentMapPath"))
            component_map = json.loads(map_path.read_text(encoding="utf-8"))
            component_map["package"]["version"] = "0.8beta-r32.2"
            map_path.write_text(json.dumps(component_map), encoding="utf-8")
            result = release_fixtures._run_powershell(
                release_fixtures.SOFTWARE_STAGE_SCRIPT,
                "-BuiltAppRoot", str(built),
                "-Destination", str(destination),
                "-BundleCorrespondingSource",
                *self._without_network_url(arguments),
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("wrong package identity", output)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
