from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest


FIXED_APP = Path(__file__).resolve().parent
REPOSITORY = FIXED_APP.parents[1]
TOOL_PATH = REPOSITORY / "tooling" / "generate_macos_app_inventory.py"

SPEC = importlib.util.spec_from_file_location("macos_app_inventory", TOOL_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import guard
    raise RuntimeError(f"Cannot load {TOOL_PATH}")
INVENTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVENTORY)


class FakeMacTools:
    def __init__(self, bundle: Path) -> None:
        self.bundle = bundle.resolve()
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, arguments):
        arguments = tuple(str(value) for value in arguments)
        self.calls.append(arguments)
        command = arguments[0]
        if command == "file":
            return subprocess.CompletedProcess(
                arguments, 0, "Mach-O 64-bit executable arm64\n", ""
            )
        if command == "lipo":
            return subprocess.CompletedProcess(arguments, 0, "arm64\n", "")
        if command == "otool":
            return subprocess.CompletedProcess(
                arguments,
                0,
                (
                    f"{arguments[-1]}:\n"
                    "\t@rpath/libdemo.dylib (compatibility version 1.0.0, "
                    "current version 1.2.3)\n"
                    "\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, "
                    "current version 1336.61.1)\n"
                ),
                "",
            )
        if command == "codesign" and "--verify" in arguments:
            return subprocess.CompletedProcess(
                arguments,
                0,
                "",
                f"{self.bundle}: valid on disk\n{self.bundle}: satisfies its Designated Requirement\n",
            )
        if command == "codesign" and "-dv" in arguments:
            return subprocess.CompletedProcess(
                arguments,
                0,
                "",
                "\n".join(
                    (
                        f"Executable={self.bundle}/Contents/MacOS/ChromaMatter",
                        "Identifier=io.github.ponkichi0718.chromamatter.alpha",
                        "Format=app bundle with Mach-O thin (arm64)",
                        "CodeDirectory v=20500 size=123 flags=0x2(adhoc) hashes=3+7 location=embedded",
                        "Signature=adhoc",
                        "Info.plist entries=12",
                        "TeamIdentifier=not set",
                        "Authority=Private Developer Name",
                        "Timestamp=26 Aug 2026 at 10:00:00",
                    )
                )
                + "\n",
            )
        return subprocess.CompletedProcess(arguments, 127, "", "unexpected command")


class MacOSAppInventoryTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> Path:
        bundle = root / "ChromaMatter-macOS-Alpha.app"
        executable = bundle / "Contents" / "MacOS" / "ChromaMatter"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"\xcf\xfa\xed\xfe" + b"test-mach-o")

        info = {
            "CFBundleDisplayName": "ChromaMatter macOS Alpha",
            "CFBundleExecutable": "ChromaMatter",
            "CFBundleGetInfoString": "ChromaMatter 0.8beta macOS alpha",
            "CFBundleIdentifier": "io.github.ponkichi0718.chromamatter.alpha",
            "CFBundleName": "ChromaMatter macOS Alpha",
            "CFBundleShortVersionString": "0.8.0",
            "CFBundleVersion": "800",
            "LSArchitecturePriority": ["arm64"],
            "LSMinimumSystemVersion": "15.0",
            "NSHighResolutionCapable": True,
            "UnrelatedPrivateBuildValue": str(root),
        }
        info_path = bundle / "Contents" / "Info.plist"
        with info_path.open("wb") as handle:
            plistlib.dump(info, handle, sort_keys=True)

        dist_info = (
            bundle
            / "Contents"
            / "Frameworks"
            / "demo_package-1.2.3.dist-info"
        )
        (dist_info / "licenses").mkdir(parents=True)
        (dist_info / "METADATA").write_text(
            "Metadata-Version: 2.4\nName: Demo-Package\nVersion: 1.2.3\n",
            encoding="utf-8",
        )
        (dist_info / "WHEEL").write_text(
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: false\n"
            "Tag: cp313-cp313-macosx_15_0_arm64\n",
            encoding="utf-8",
        )
        (dist_info / "RECORD").write_text(
            "demo/__init__.py,sha256=YWJj,4\n"
            "demo_package-1.2.3.dist-info/licenses/LICENSE.txt,sha256=ZGVm,7\n"
            "../../../bin/demo,,\n",
            encoding="utf-8",
        )
        (dist_info / "licenses" / "LICENSE.txt").write_text(
            "Demo license\n", encoding="utf-8"
        )
        copied_license = (
            bundle
            / "Contents"
            / "Resources"
            / "licenses"
            / "wheels"
            / "demo-package"
            / "demo_package-1.2.3.dist-info"
            / "licenses"
            / "LICENSE.txt"
        )
        copied_license.parent.mkdir(parents=True)
        copied_license.write_text("Demo license\n", encoding="utf-8")
        return bundle

    def test_collects_deterministic_bundle_relative_observed_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle = self.make_bundle(Path(temporary_directory))
            runner = FakeMacTools(bundle)
            first = INVENTORY.collect_inventory(
                bundle, runner=runner, platform_name="darwin"
            )
            second = INVENTORY.collect_inventory(
                bundle, runner=FakeMacTools(bundle), platform_name="darwin"
            )
            self.assertEqual(first, second)

            encoded = json.dumps(first, ensure_ascii=False, sort_keys=True)
            self.assertNotIn(str(bundle.resolve()), encoded)
            self.assertNotIn("Private Developer Name", encoded)
            self.assertNotIn("UnrelatedPrivateBuildValue", encoded)
            self.assertEqual(first["schema"], "chromamatter.macos-app-inventory")
            self.assertEqual(first["schema_version"], 1)
            self.assertIn("not an SBOM", first["purpose"])

            self.assertEqual(
                first["bundle"]["identity"]["CFBundleIdentifier"],
                "io.github.ponkichi0718.chromamatter.alpha",
            )
            self.assertEqual(first["counts"]["mach_o_files"], 1)
            executable = next(
                fact
                for fact in first["regular_files"]
                if fact["path"] == "Contents/MacOS/ChromaMatter"
            )
            self.assertEqual(executable["size"], len(b"\xcf\xfa\xed\xfetest-mach-o"))
            self.assertEqual(
                executable["sha256"],
                hashlib.sha256(b"\xcf\xfa\xed\xfetest-mach-o").hexdigest(),
            )
            self.assertEqual(executable["mach_o"]["architectures"], ["arm64"])
            self.assertEqual(
                executable["mach_o"]["dependencies"],
                ["/usr/lib/libSystem.B.dylib", "@rpath/libdemo.dylib"],
            )

            signing = first["code_signing"]
            self.assertTrue(signing["verify_ok"])
            self.assertTrue(signing["ad_hoc"])
            self.assertEqual(signing["identity_authority_count"], 1)
            self.assertEqual(signing["details"]["signature"], "adhoc")
            self.assertIn("flags=0x2(adhoc)", signing["details"]["code_directory"])
            self.assertIn("<APP_BUNDLE>", signing["details"]["executable"])

            distributions = first["packaged_distributions"]
            self.assertEqual(len(distributions), 1)
            distribution = distributions[0]
            self.assertEqual(distribution["name"], "Demo-Package")
            self.assertEqual(distribution["version"], "1.2.3")
            self.assertEqual(distribution["canonical_name"], "demo-package")
            self.assertTrue(distribution["metadata"]["available"])
            self.assertTrue(distribution["wheel"]["available"])
            self.assertEqual(
                distribution["wheel"]["tags"],
                ["cp313-cp313-macosx_15_0_arm64"],
            )
            self.assertTrue(distribution["record"]["available"])
            self.assertEqual(distribution["record"]["entry_count"], 3)
            self.assertEqual(
                distribution["record"]["invalid_or_absolute_row_count"], 0
            )
            self.assertEqual(len(distribution["license_files"]), 2)
            self.assertFalse(distribution["direct_url_metadata_present"])

            output = Path(temporary_directory) / "inventory.json"
            INVENTORY.write_inventory(first, output)
            first_bytes = output.read_bytes()
            INVENTORY.write_inventory(second, output)
            self.assertEqual(output.read_bytes(), first_bytes)
            self.assertEqual(json.loads(first_bytes), first)

    def test_symlink_target_reports_confinement_without_absolute_path_leak(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bundle = root / "Example.app"
            link = bundle / "Contents" / "Frameworks" / "Current"
            target = bundle / "Contents" / "MacOS" / "Example"
            target.parent.mkdir(parents=True)
            target.write_text("x", encoding="utf-8")

            inside = INVENTORY.describe_symlink_target(
                bundle,
                link,
                "../MacOS/Example",
                target_exists=True,
            )
            self.assertTrue(inside["confined_to_bundle"])
            self.assertEqual(inside["resolved_path"], "Contents/MacOS/Example")
            self.assertEqual(inside["target_form"], "link-relative")

            outside_path = root.parent / "outside-private-path"
            outside = INVENTORY.describe_symlink_target(
                bundle,
                link,
                str(outside_path.resolve()),
                target_exists=True,
            )
            self.assertFalse(outside["confined_to_bundle"])
            self.assertIsNone(outside["resolved_path"])
            self.assertEqual(outside["target"], "<outside-bundle-redacted>")
            self.assertNotIn(str(outside_path.resolve()), json.dumps(outside))

    def test_non_macos_and_non_app_inputs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(INVENTORY.InventoryError, "only on macOS"):
                INVENTORY.collect_inventory(root, platform_name="win32")
            with self.assertRaisesRegex(INVENTORY.InventoryError, "macOS .app"):
                INVENTORY.collect_inventory(root, platform_name="darwin")

    def test_cli_has_macos_only_guard_and_observed_facts_scope(self) -> None:
        text = TOOL_PATH.read_text(encoding="utf-8")
        self.assertIn('platform_name != "darwin"', text)
        self.assertIn("No Mach-O regular file", text)
        self.assertIn("Unsafe or broken app symlink", text)
        self.assertIn("not an SBOM", text)
        self.assertIn("binary ownership conclusion", text)
        self.assertNotIn("distribution_approved", text)
        self.assertNotIn('"approved"', text)


if __name__ == "__main__":
    unittest.main()
