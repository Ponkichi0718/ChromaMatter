from __future__ import annotations

from pathlib import Path
import re
import unittest


FIXED_APP = Path(__file__).resolve().parent
REPOSITORY = FIXED_APP.parents[1]
LOCK = FIXED_APP / "requirements-build-macos-arm64.lock"
SPEC = FIXED_APP / "TripoSpectrumMapper_macos_arm64.spec"
BUILD_SCRIPT = REPOSITORY / "BUILD_MACOS_ARM64.sh"
AUDIT_SCRIPT = REPOSITORY / "AUDIT_MACOS_APP.sh"
INVENTORY_TOOL = REPOSITORY / "tooling" / "generate_macos_app_inventory.py"
WORKFLOW = REPOSITORY / ".github" / "workflows" / "macos-arm64-alpha.yml"
ISSUE_TEMPLATE = (
    REPOSITORY / ".github" / "ISSUE_TEMPLATE" / "macos_alpha_report.yml"
)
TEST_GUIDES = (
    REPOSITORY / "publication" / "MACOS_ALPHA_TESTING_EN.md",
    REPOSITORY / "publication" / "MACOS_ALPHA_TESTING_JA.md",
)
COMPLIANCE_NOTICES = (
    REPOSITORY / "licenses" / "MACOS_ALPHA_COMPLIANCE_NOTICE_EN.txt",
    REPOSITORY / "licenses" / "MACOS_ALPHA_COMPLIANCE_NOTICE_JA.txt",
)


class MacOSAlphaDependencyLockTests(unittest.TestCase):
    def test_lock_is_arm64_binary_only_and_separate_from_windows(self) -> None:
        text = LOCK.read_text(encoding="utf-8")
        self.assertIn("Apple Silicon / macOS 15+ / CPython 3.13.14", text)
        self.assertIn("pytetwild==0.3.0", text)
        self.assertIn(
            "e0f7edd8d2e29f1439cf78dde9d2be63b3c0d4091d402b8cb291f5ca75c0312e",
            text,
        )
        self.assertIn("macholib==1.16.3", text)
        for windows_only in ("msvc_runtime", "pefile", "pywin32-ctypes"):
            self.assertNotIn(windows_only, text)
        self.assertNotIn("requirements-build.lock\n", text)

        logical = text.replace("\\\n", " ")
        requirements = [
            line.strip()
            for line in logical.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(len(requirements), 23)
        for requirement in requirements:
            with self.subTest(requirement=requirement):
                self.assertRegex(requirement, r"^[A-Za-z0-9_.-]+==[^ ]+ ")
                self.assertRegex(requirement, r"--hash=sha256:[0-9a-f]{64}$")

    def test_windows_lock_and_spec_remain_present(self) -> None:
        self.assertTrue((FIXED_APP / "requirements-build.lock").is_file())
        self.assertTrue((FIXED_APP / "TripoSpectrumMapper_fixed.spec").is_file())


class MacOSAlphaSpecTests(unittest.TestCase):
    def test_spec_builds_distinct_arm64_alpha_app(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn('target_arch="arm64"', text)
        self.assertIn('name=f"{MACOS_APP_NAME}.app"', text)
        self.assertIn("ChromaMatter-macOS-Alpha", text)
        self.assertIn("io.github.ponkichi0718.chromamatter.alpha", text)
        self.assertIn('"CFBundleShortVersionString": "0.8.0"', text)
        self.assertIn('"CFBundleVersion": "800"', text)
        self.assertIn("ChromaMatter 0.8beta macOS alpha", text)
        self.assertIn('version="0.8.0"', text)
        self.assertIn('"LSMinimumSystemVersion": "15.0"', text)
        self.assertIn('codesign_identity=None', text)
        self.assertNotIn("version_info.txt", text)
        self.assertNotIn("obj_adjuster_icon.ico", text)

    def test_spec_preserves_macos_pytetwild_layout_and_standard_pymeshlab_hook(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn('PYTETWILD_PACKAGE / ".dylibs"', text)
        self.assertIn('glob("PyfTetWildWrapper*.so")', text)
        self.assertIn('"pytetwild/.dylibs"', text)
        self.assertNotIn("pytetwild.libs", text)
        self.assertNotIn("*.pyd", text)
        self.assertIn('"pymeshlab"', text)
        self.assertNotIn("pymeshlab.Frameworks", text)
        self.assertNotIn("collect_dynamic_libs", text)

    def test_spec_bundles_mac_notice_and_filters_private_metadata(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertTrue(
            (REPOSITORY / "licenses" / "MACOS_ALPHA_COMPLIANCE_NOTICE_EN.txt").is_file()
        )
        self.assertTrue(
            (REPOSITORY / "licenses" / "MACOS_ALPHA_COMPLIANCE_NOTICE_JA.txt").is_file()
        )
        self.assertIn("tree_datas(PROJECT / \"licenses\"", text)
        self.assertIn("is_private_install_origin_metadata", text)
        self.assertIn("WINDOWS_RELEASE_ONLY_DOCUMENTS", text)
        self.assertIn('!= "macos"', text)
        self.assertIn("circular inventory", text)
        self.assertNotIn("licenses/native-closure", text)
        self.assertIn("/ pure.parent", text)

    def test_spec_pins_and_bundles_exact_tcl_tk_licenses(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        for component in ("TCL", "TK"):
            license_path = (
                REPOSITORY / "licenses" / f"LICENSE_{component}_8_6_18.txt"
            )
            with self.subTest(component=component):
                self.assertTrue(license_path.is_file())
                self.assertIn(
                    "notice is included verbatim in any distributions",
                    license_path.read_text(encoding="utf-8"),
                )
                self.assertIn(license_path.name, text)
        self.assertIn('TCL_PATCHLEVEL != "8.6.18"', text)
        self.assertNotIn("TCL_TK_LICENSE_CANDIDATES", text)


class MacOSAlphaAutomationTests(unittest.TestCase):
    def test_build_and_audit_scripts_keep_platform_gates_fail_closed(self) -> None:
        build = BUILD_SCRIPT.read_text(encoding="utf-8")
        audit = AUDIT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('[[ "$(uname -m)" == "arm64" ]]', build)
        self.assertIn('[[ "$PYTHON_VERSION" == "3.13.14" ]]', build)
        self.assertIn("--require-hashes", WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("AUDIT_MACOS_APP.sh", build)
        self.assertTrue(INVENTORY_TOOL.is_file())
        self.assertIn("generate_macos_app_inventory.py", build)
        self.assertIn("MACOS_ALPHA_APP_INVENTORY.json", build)
        self.assertLess(
            build.index("AUDIT_MACOS_APP.sh"),
            build.index("generate_macos_app_inventory.py"),
        )
        self.assertIn("--self-test", build)
        self.assertIn("run_macos_alpha_gate", build)
        self.assertIn('payload.get("ok") is not True', build)
        self.assertIn("--ui-smoke", build)
        self.assertIn("timeout=45", build)
        gui = (FIXED_APP / "spectrum_mapper" / "gui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("winfo_ismapped", gui)
        self.assertIn("Packaged UI smoke window is invalid", gui)
        self.assertIn("windows_release_only", build)
        self.assertIn("test_audited_native_identities.py", build)

        self.assertIn("codesign --verify --deep --strict", audit)
        self.assertIn("Signature=adhoc", audit)
        self.assertIn("PyfTetWildWrapper*.so", audit)
        self.assertIn("pytetwild/__dot__dylibs/libgmp.10.dylib", audit)
        self.assertIn("pymeshlab/PlugIns", audit)
        self.assertIn("otool -L", audit)
        self.assertIn("Non-relocatable Mach-O dependency", audit)
        self.assertIn("direct_url.json", audit)
        self.assertIn("Windows-only native source closure", audit)

    def test_workflow_is_ci_only_and_tester_zip_upload_is_opt_in(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("runs-on: macos-15", text)
        self.assertEqual(text.count('"tooling/generate_macos_app_inventory.py"'), 1)
        self.assertIn("uses: actions/setup-python@v7", text)
        self.assertIn("  push:\n", text)
        self.assertNotIn("  pull_request:\n", text)
        self.assertIn('python-version: "3.13.14"', text)
        self.assertIn("architecture: arm64", text)
        self.assertIn("upload_tester_alpha:", text)
        self.assertRegex(
            text,
            r"upload_tester_alpha:\n(?:.*\n){0,5}\s+default: false",
        )
        self.assertGreaterEqual(text.count("inputs.upload_tester_alpha"), 3)
        self.assertIn("MACOS_ALPHA_TESTER_DISTRIBUTION_APPROVED", text)
        self.assertIn("MACOS_ALPHA_APPROVED_SOURCE_COMMIT", text)
        self.assertIn("SOURCE_COMMIT: ${{ github.sha }}", text)
        self.assertIn("ref: ${{ github.sha }}", text)
        self.assertNotIn("$GITHUB_SHA", text)
        self.assertIn("DISTRIBUTION_APPROVAL.json", text)
        self.assertIn("BINARY_COMPONENT_MAP.json", text)
        self.assertIn("SBOM.spdx.json", text)
        self.assertIn("CORRESPONDING_SOURCE_MANIFEST.json", text)
        self.assertIn('sources.get("status") != "release-approved"', text)
        self.assertIn("still declare pending work", text)
        self.assertIn("upload_tester_alpha=false", text)
        self.assertIn("ditto -c -k --sequesterRsrc --keepParent", text)
        self.assertIn("ditto -x -k", text)
        self.assertIn("TESTER_ONLY_NOT_A_RELEASE.txt", text)
        self.assertIn("MACOS_ALPHA_SOURCE_OFFER_STATUS.txt", text)
        self.assertNotIn("is not yet a macOS-specific", text)
        self.assertIn('"$executable" --macos-alpha-self-test', text)
        self.assertIn("CHROMAMATTER_DATA_DIRECTORY", text)
        self.assertNotIn('HOME="$profile/home"', text)
        self.assertIn('payload.get("ok") is not True', text)
        self.assertIn("--ui-smoke required", text)
        self.assertIn(
            '[executable, "--ui-smoke", "--ui-smoke-language", language]',
            text,
        )
        self.assertIn("timeout=45", text)
        self.assertIn("developer-id-unsigned-unnotarized-alpha", text)
        self.assertIn("retention-days: 7", text)
        self.assertIn("GITHUB_STEP_SUMMARY", text)
        self.assertIn("TESTER ZIP CREATED", text)
        self.assertIn("DIAGNOSTICS ONLY", text)
        self.assertGreaterEqual(text.count("MACOS_ALPHA_APP_INVENTORY.json"), 2)
        self.assertIn("discussions/9", text)
        self.assertNotIn("gh release", text.casefold())
        self.assertNotIn("softprops/action-gh-release", text.casefold())

    def test_tester_documents_and_issue_form_protect_private_models(self) -> None:
        for path in (*TEST_GUIDES, *COMPLIANCE_NOTICES):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())
                text = path.read_text(encoding="utf-8")
                self.assertIn("0.8beta", text)

        english = TEST_GUIDES[0].read_text(encoding="utf-8")
        japanese = TEST_GUIDES[1].read_text(encoding="utf-8")
        english_compact = " ".join(english.split())
        self.assertIn("Apple Silicon", english)
        self.assertIn("Developer ID", english)
        self.assertIn("Do not redistribute", english_compact)
        self.assertIn("Do not attach a private model", english)
        self.assertIn("Apple Silicon", japanese)
        self.assertIn("再配布", japanese)
        self.assertIn("private model", japanese)

        issue = ISSUE_TEMPLATE.read_text(encoding="utf-8")
        for expected in (
            "Mac model, chip, and RAM",
            "macOS version",
            "Approved workflow run URL or run ID",
            "Artifact filename and ZIP SHA-256",
            "Public four-colour GLB",
            "Flat Four F1-F4 only",
            "Manual Fill / Undo / Redo",
            "Output preparation / Solidify",
            "3MF export",
            "Snapmaker Orca",
            "Project save / reload",
            "After a failed export, was a new 3MF left behind?",
            "Sanitized macOS alpha self-test result",
            "did not attach or link a private",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, issue)


if __name__ == "__main__":
    unittest.main()
