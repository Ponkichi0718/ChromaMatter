import hashlib
import json
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_APP = REPO_ROOT / "source" / "fixed_app"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ReleaseIdentityTests(unittest.TestCase):
    def test_entrypoint_installs_release_hotfixes_in_required_order(self):
        entrypoint = read_text(FIXED_APP / "TripoSpectrumMapper_fixed.py")
        ordered_markers = (
            "import spectrum_mapper_hotfix",
            "from surface_resolution_hotfix import apply_surface_resolution_hotfix",
            "from final_shading_hotfix import install_export_adaptive_hotfix",
            "apply_surface_resolution_hotfix()",
            "install_export_adaptive_hotfix()",
            "from spectrum_mapper.cli import main",
        )
        positions = [entrypoint.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(1, entrypoint.count("apply_surface_resolution_hotfix()"))
        self.assertEqual(1, entrypoint.count("install_export_adaptive_hotfix()"))

    def test_pyinstaller_and_build_paths_use_chromamatter(self):
        spec = read_text(FIXED_APP / "TripoSpectrumMapper_fixed.spec")
        self.assertEqual(2, spec.count('name="ChromaMatter"'))
        self.assertNotIn('name="TripoSpectrumMapper_fixed"', spec)
        for module in (
            "surface_resolution_hotfix",
            "final_shading_hotfix",
            "spectrum_mapper.generated_surface_color",
            "spectrum_mapper.filament_candidate_gui",
            "spectrum_mapper.owned_filaments",
            "spectrum_mapper.calibration_chart",
            "spectrum_mapper.palette_state_count",
        ):
            with self.subTest(module=module):
                self.assertIn(f'"{module}"', spec)

        build_script = read_text(REPO_ROOT / "BUILD_AND_TEST.ps1")
        self.assertIn(
            'Join-Path $distPath "ChromaMatter\\ChromaMatter.exe"',
            build_script,
        )
        self.assertIn(
            '"ChromaMatter\\_internal\\resources\\filament_db"',
            build_script,
        )
        self.assertIn("ChromaMatter-packaged-ui-smoke-", build_script)
        self.assertNotIn(
            'TripoSpectrumMapper_fixed\\TripoSpectrumMapper_fixed.exe',
            build_script,
        )

    def test_launcher_targets_the_packaged_executable(self):
        launcher = read_text(FIXED_APP / "START_FIXED.cmd")
        self.assertIn("%~dp0ChromaMatter.exe", launcher)
        self.assertNotIn("TripoSpectrumMapper_fixed.exe", launcher)

    def test_display_version_and_numeric_resource_remain_pinned(self):
        package_init = read_text(FIXED_APP / "spectrum_mapper" / "__init__.py")
        runtime_hotfix = read_text(FIXED_APP / "spectrum_mapper_hotfix.py")
        version_info = read_text(FIXED_APP / "version_info.txt")
        version_policy = read_text(FIXED_APP / "VERSION_POLICY.md")

        self.assertIn('__version__ = "0.8beta"', package_init)
        self.assertIn('HOTFIX_VERSION = "0.8beta"', runtime_hotfix)
        self.assertIn("filevers=(0, 8, 0, 0)", version_info)
        self.assertIn("prodvers=(0, 8, 0, 0)", version_info)
        self.assertIn("FileVersion', u'0.8beta'", version_info)
        self.assertIn("ProductVersion', u'0.8beta'", version_info)
        self.assertIn("InternalName', u'ChromaMatter'", version_info)
        self.assertIn("OriginalFilename', u'ChromaMatter.exe'", version_info)
        self.assertIn("Public displayed version: `0.8beta`", version_policy)

    def test_r32_2_edition_and_default_artifact_names_are_pinned(self):
        package_init = read_text(FIXED_APP / "spectrum_mapper" / "__init__.py")
        public_stage = read_text(
            REPO_ROOT / "tooling" / "stage_public_source.ps1"
        )
        software_stage = read_text(
            REPO_ROOT / "tooling" / "stage_software_package.ps1"
        )

        self.assertIn('APP_NAME = "ChromaMatter"', package_init)
        self.assertIn('APP_TAGLINE = "AI Model Print Studio"', package_init)
        self.assertIn('RELEASE_REVISION = "r32.2"', package_init)
        self.assertIn(
            "ChromaMatter-0.8beta-r32.2-source-public-20260824",
            public_stage,
        )
        self.assertIn(
            "ChromaMatter-0.8beta-r32.2-win64",
            software_stage,
        )
        self.assertNotIn("r29-creator-studio_HANDOFF", public_stage)
        self.assertNotIn('r29-creator-studio"', software_stage)
        self.assertIn(
            "Refusing to overwrite an existing public-source stage",
            public_stage,
        )
        for relative in (
            "publication/INNOVATION_FUND_APPLICATION_DRAFT.md",
            "publication/INNOVATION_FUND_STATUS_JA.md",
        ):
            with self.subTest(innovation_fund_document=relative):
                self.assertIn(relative, public_stage)
                self.assertNotIn(relative, software_stage)

    def test_r32_2_handoff_requires_manifest_locked_demo_data(self):
        handoff = read_text(
            REPO_ROOT / "publication" / "BINARY_RELEASE_HANDOFF_JA.md"
        )
        for required in (
            "git switch codex/r32-2-demo-3mf",
            "$releaseRunRoot",
            "$releaseInputs = Join-Path $releaseRunRoot 'inputs'",
            "$buildRoot = Join-Path $releaseRunRoot 'build'",
            "$releaseAssetRoot = Join-Path $releaseRunRoot 'assets'",
            "Release run root already exists; choose a new empty root",
            "$sourceCache = 'C:\\ChromaMatterToolchain\\corresponding-source-cache-r32'",
            "-Cache $sourceCache",
            "-Offline",
            "$demoDataPayloadRoot",
            "$demoDataPayloadRoot = Join-Path $releaseInputs 'DemoData-payloads'",
            "$demoDataManifest",
            "-DemoDataRoot $demoDataPayloadRoot",
            "-DemoDataManifestPath $demoDataManifest",
            "source\\fixed_app\\public_binary\\DemoData\\DEMO_DATA_MANIFEST.json",
            "Original AI model Color.glb",
            "Reference.jpg",
            "Original AI model Color_FullSpectrum.3mf",
            "Original AI model Color_FullSpectrum_parts_2",
        ):
            with self.subTest(required=required):
                self.assertIn(required, handoff)
        for stale_fixed_root in (
            "C:\\release\\",
            r"C:\release-inputs",
            r"C:\CMR32AGPL1",
            r"C:\CMR32SourceCache",
            "ChromaMatter-r32.2-DemoData-payloads",
        ):
            with self.subTest(stale_fixed_root=stale_fixed_root):
                self.assertNotIn(stale_fixed_root, handoff)

    def test_handoff_state_records_published_r32_2_and_previous_r32_1_evidence(self):
        state = json.loads(read_text(REPO_ROOT / "CURRENT_STATE.json"))
        self.assertEqual(
            "ChromaMatter — AI Model Print Studio",
            state["product"],
        )
        self.assertEqual("0.8beta", state["display_version"])
        self.assertEqual("0.8beta", state["package_version"])
        self.assertEqual("AI Model Print Studio r32.2", state["edition"])
        self.assertEqual("r32.2-ai-model-print-studio", state["artifact_slug"])
        self.assertEqual(
            "v0.8beta-r32.2-published-prerelease-exact-tagged-build",
            state["status"],
        )
        self.assertTrue(state["version_policy"]["pinned_until_explicit_user_request"])
        self.assertTrue(
            state["version_policy"]["edition_and_artifact_revision_may_advance_independently"]
        )

        required_bundle = state["project_format"]["portable_folder"]["required"]
        self.assertEqual(
            ["source.obj or source.glb", "project.json", "prepared_geometry.npz"],
            required_bundle,
        )

        validation = state["validation"]
        for passed_gate in (
            "implementation_focused_source",
            "release_focused_identity_regression_tooling_gui_layout",
        ):
            with self.subTest(passed_gate=passed_gate):
                self.assertTrue(validation[passed_gate].startswith("passed"))
        self.assertTrue(
            validation["current_public_ui_focused_regression"].startswith("passed")
        )
        self.assertTrue(validation["current_full_regression"].startswith("passed"))
        self.assertIn("Ran 1298 tests", validation["current_full_regression"])
        self.assertIn("1296 passed", validation["current_full_regression"])
        self.assertIn("2 optional skips", validation["current_full_regression"])
        self.assertIn("0 failed", validation["current_full_regression"])
        self.assertIn(
            "VCTools directory 14.44.35207",
            validation["controlled_toolchain_install_and_contract"],
        )
        self.assertIn(
            "20260823-174626-089357844d4b",
            validation["controlled_toolchain_install_and_contract"],
        )
        self.assertIn(
            "zero residual firewall rules or scheduled tasks",
            validation["controlled_toolchain_install_and_contract"],
        )
        controlled_run = validation["latest_controlled_pytetwild_run"]
        self.assertEqual(
            "20260823-174626-089357844d4b",
            controlled_run["run_id"],
        )
        self.assertEqual(
            "verified-controlled-rebuild-adopted-by-current-source-contract",
            controlled_run["status"],
        )
        self.assertEqual(
            "5feb198eef3432cdec19a0367d53e1b52bd4a363",
            controlled_run["repository_commit"],
        )
        self.assertEqual(8, controlled_run["direct_audit_logs_present"])
        self.assertEqual(8, controlled_run["direct_audit_logs_required"])
        self.assertTrue(controlled_run["attestation_generated"])
        self.assertEqual(
            "e3b11ac058266d277b0f83448c6023d5da98e731d0d016e461dbce4ebdfd613d",
            controlled_run["repaired_wheel"]["sha256"],
        )
        self.assertEqual(1_637_633, controlled_run["repaired_wheel"]["bytes"])
        self.assertEqual(
            "9fbedacd1286a7e792a1503490669916d8a449cf9948ccc0f2899fdcda7c8089",
            controlled_run["raw_wheel"]["sha256"],
        )
        self.assertEqual(
            "26a091b53279407014899c046691958c9df07e22703576da6a45d68a9be22430",
            controlled_run["extension_pyd"]["sha256"],
        )
        self.assertEqual(
            "3989fd1debe8b6c984938c4a64ee5fb3bcce1b612cf83524ea309b1fae3cde9f",
            controlled_run["attestation"]["sha256"],
        )
        self.assertEqual(
            "verified-controlled-rebuild",
            controlled_run["attestation"]["status"],
        )
        self.assertEqual("release-approved", controlled_run["static_closure_status"])
        application_lock = FIXED_APP / "requirements-build.lock"
        self.assertEqual(
            hashlib.sha256(application_lock.read_bytes()).hexdigest(),
            controlled_run["application_requirements_lock_sha256"],
        )
        self.assertEqual(
            controlled_run["repaired_wheel"]["sha256"],
            controlled_run["application_locked_wheel_sha256"],
        )
        self.assertTrue(validation["current_clean_build_and_packaged_smoke"].startswith("passed"))
        self.assertIn(
            "fresh-extracted self-test",
            validation["current_clean_build_and_packaged_smoke"],
        )
        stage_audit = validation["current_stage_archive_privacy_and_checksum_audit"]
        self.assertTrue(stage_audit.startswith("passed for the exact r32.2 release"))
        self.assertIn("1527 files", stage_audit)
        self.assertIn("seven 3MF projects", stage_audit)
        self.assertIn("without authentication", stage_audit)
        self.assertTrue(
            validation["binary_component_licence_and_static_link_coverage"].startswith("passed")
        )
        self.assertIn(
            "1455 packaged binary files",
            validation["binary_component_licence_and_static_link_coverage"],
        )
        self.assertIn(
            "zero known gaps",
            validation["binary_component_licence_and_static_link_coverage"],
        )
        previous_r29 = validation["previous_r29_candidate_validation"]
        self.assertEqual("previous evidence only", previous_r29["status"])
        self.assertIn("Ran 998 tests in 83.529s", previous_r29["full_regression"])
        self.assertIn("C:\\OBJAdjR29FIX1", previous_r29["clean_build"])
        self.assertTrue(validation["legal_review"].startswith("accepted-by-project-owner"))
        self.assertTrue(
            validation["icon_publication_rights"].startswith(
                "passed-by-creator-declaration"
            )
        )
        for gate in ("physical_xp_pen", "physical_print"):
            self.assertEqual("pending", validation[gate])

        output_contract = "\n".join(state["current_features"]["output"])
        for expected in (
            "single GLB",
            "exact 1:1 reversed boundary",
            "before cleanup and QEM",
            "does not add caps",
            "true holes fail closed",
            "type=model",
            "bounded minor self-intersection",
            "Snapmaker Orca",
            "Manual paint",
            "adaptive",
            "announces the safe solidification step",
            "prime-tower baseline",
            "support selection",
        ):
            with self.subTest(output_contract=expected):
                self.assertIn(expected, output_contract)

        public_window_contract = "\n".join(
            state["current_features"]["public_main_window"]
        )
        self.assertIn("Apply Current F1-F4 to Preview / 3MF", public_window_contract)
        self.assertIn("automatic proposal remains the default", public_window_contract)

        manual_contract = "\n".join(state["current_features"]["manual_editing"])
        self.assertIn(
            "no ribbon tab, button, menu, image-open callback, or shortcut",
            manual_contract,
        )

        release = state["release"]
        self.assertEqual(
            "v0.8beta-r32.2-published-prerelease-exact-tagged-build",
            release["state"],
        )
        self.assertEqual("r32.2-ai-model-print-studio", release["target_revision"])
        self.assertEqual(
            "ChromaMatter-0.8beta-r32.2-complete-corresponding-source",
            release["public_source_default"],
        )
        self.assertEqual(
            "ChromaMatter-0.8beta-r32.2-win64",
            release["software_package_default"],
        )
        latest = release["latest_source_branch_validation"]
        self.assertEqual("published-prerelease-exact-tagged-build", latest["status"])
        self.assertEqual("v0.8beta-r32.2", latest["tag"])
        self.assertEqual(
            "aba20685d2fd6987621b2e1e6624f46ea84912a3",
            latest["tagged_commit"],
        )
        self.assertEqual(
            "https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2",
            latest["release_url"],
        )
        self.assertEqual(
            "https://github.com/Ponkichi0718/ChromaMatter/releases/download/"
            "v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-win64.zip",
            latest["direct_windows_download"],
        )
        self.assertTrue(latest["source_full_regression"].startswith("passed"))
        self.assertIn("Ran 1298 tests", latest["source_full_regression"])
        self.assertIn("1296 passed", latest["source_full_regression"])
        self.assertTrue(latest["source_publication_eligible"])
        self.assertEqual(
            "ChromaMatter-0.8beta-r32.2-complete-corresponding-source",
            latest["public_source_stage"]["expected_root"],
        )
        source_stage = latest["public_source_stage"]
        self.assertEqual("release-approved", source_stage["status"])
        self.assertEqual(1_365_909_916, source_stage["bytes"])
        self.assertEqual(
            "DCC7EC1AE74F4B790CCAC6B9B18286C7BDAB2829E779F0532E01708727680500",
            source_stage["sha256"],
        )
        self.assertEqual(42_806, source_stage["archive_files"])
        self.assertEqual(42_805, source_stage["manifest_records"])
        self.assertEqual(1_907_645_679, source_stage["manifest_summed_bytes"])
        self.assertEqual(64, source_stage["component_count"])
        self.assertEqual([], source_stage["known_gaps"])
        self.assertTrue(latest["binary_publication_eligible"])
        self.assertEqual([], latest["binary_publication_blockers"])
        package = latest["software_package"]
        self.assertEqual(327_268_369, package["bytes"])
        self.assertEqual(
            "2CEADA98661BAC5D49B759542151C4C484FFF4269D6B5D142EC32FEC544F06D0",
            package["sha256"],
        )
        self.assertEqual(1527, package["fresh_extracted_files"])
        self.assertEqual(1526, package["manifest_records"])
        self.assertEqual(10, package["demo_payloads"])
        self.assertEqual(7, package["demo_3mf_projects"])
        for passed_smoke in (
            "packaged_self_test",
            "fresh_extracted_self_test",
            "ui_smoke_ja",
            "ui_smoke_en",
        ):
            with self.subTest(passed_smoke=passed_smoke):
                self.assertEqual("passed", package[passed_smoke])
        self.assertIn("codex/r32-2-demo-3mf", latest["branch"])
        self.assertIn("without authentication", latest["public_asset_verification"])
        expected_assets = {
            "ChromaMatter-0.8beta-r32.2-win64.zip": (
                327_268_369,
                "2CEADA98661BAC5D49B759542151C4C484FFF4269D6B5D142EC32FEC544F06D0",
            ),
            "ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip": (
                1_365_909_916,
                "DCC7EC1AE74F4B790CCAC6B9B18286C7BDAB2829E779F0532E01708727680500",
            ),
            "ChromaMatter-0.8beta-r32.2-SBOM.cdx.json": (
                937_715,
                "2A1B293BF081ABA9A070F16E97523AF1B72301A6250E8D6BBBF446716DCAACE5",
            ),
            "ChromaMatter-0.8beta-r32.2-BINARY_COMPONENT_MAP.json": (
                526_076,
                "3620E4597CBBDA83A34F9F15DB3813D417853597DD5EC57EEFEC2245C652D868",
            ),
            "ChromaMatter-simple-workflow-demo.mp4": (
                37_708_741,
                "F55F9505EC7385D27A933799F9EEFD1C2499A77B86B0BB1162832320E88FEE61",
            ),
            "SHA256SUMS-r32.2.txt": (
                560,
                "45D355E2DA9864CA83D314BC63FD3DA5AA5B428706D40491596E12EAB06D1218",
            ),
        }
        self.assertEqual(set(expected_assets), set(latest["release_assets"]))
        self.assertEqual(set(expected_assets), set(latest["release_asset_sizes"]))
        for filename, (size, sha256) in expected_assets.items():
            with self.subTest(release_asset=filename):
                self.assertEqual(size, latest["release_asset_sizes"][filename])
                self.assertEqual(sha256, latest["release_assets"][filename])
        self.assertIn(
            "other multipart files may still fail",
            state["validation"]["multipart_solidification_beta_limitation"],
        )
        distribution = release["distribution_policy"]
        self.assertTrue(distribution["published_location_claimed"])
        self.assertTrue(distribution["downloads_placement_claimed"])
        self.assertIn("published", distribution["artifact_checksum_record"])
        self.assertIn("without authentication", distribution["artifact_checksum_record"])
        published_r32_1 = release["previous_r32_1_public_release"]
        self.assertEqual(
            "previous evidence only: published-prerelease-exact-tagged-build",
            published_r32_1["status"],
        )
        self.assertEqual("v0.8beta-r32.1", published_r32_1["tag"])
        self.assertEqual(
            "b575b93d973ed67e7ada986469b10b4490eef4e5",
            published_r32_1["tagged_commit"],
        )
        self.assertIn("Ran 1277 tests", published_r32_1["source_full_regression"])
        self.assertIn("1274 passed", published_r32_1["source_full_regression"])
        self.assertTrue(published_r32_1["source_publication_eligible"])
        self.assertTrue(published_r32_1["binary_publication_eligible"])
        self.assertEqual(
            "1215CF77D8C8CB8AA5CE91DC7C84AE13404F3AA46221321807AD2E8A19F9064A",
            published_r32_1["software_package"]["sha256"],
        )
        self.assertIn("does not validate r32.2", published_r32_1["scope"])
        published_r32 = release["previous_r32_public_release"]
        self.assertEqual("previous evidence only: published", published_r32["status"])
        self.assertEqual("v0.8beta-r32", published_r32["tag"])
        self.assertEqual(
            "86e34b2a9468f81768ee134a680a792b1a83df05",
            published_r32["commit"],
        )
        self.assertIn("Ran 1270 tests", published_r32["exact_final_full_regression"])
        self.assertIn("1267 passed", published_r32["exact_final_full_regression"])
        self.assertIn("3 optional skips", published_r32["exact_final_full_regression"])
        self.assertIn(
            "previous evidence only",
            published_r32["clean_build_packaged_self_test_and_ui_smoke"],
        )
        self.assertIn("does not validate r32.1 or r32.2", published_r32["scope"])
        current = release["previous_r32_pre_compliance_candidate_validation"]
        self.assertEqual(
            "previous evidence only: pre-compliance artifacts audited",
            current["status"],
        )
        self.assertIn(
            "Ran 1048 tests in 90.160s: OK (skipped=1)",
            current["source_full_regression"],
        )
        self.assertIn("1047 passed", current["source_full_regression"])
        self.assertIn("0 failed", current["source_full_regression"])
        for gate in (
            "current_focused_release_identity_regression",
            "current_focused_ui_regression",
            "clean_build",
            "packaged_self_test",
            "packaged_ui_smoke_ja",
            "packaged_ui_smoke_en",
        ):
            with self.subTest(release_passed_gate=gate):
                self.assertTrue(current[gate].startswith("previous evidence only:"))
        self.assertIn("C:\\OBJAdjR32CM3", current["clean_build"])
        self.assertIn("PyInstaller 6.20.0", current["clean_build"])
        for gate in (
            "fresh_extracted_self_test",
            "fresh_extracted_ui_smoke_ja",
            "fresh_extracted_ui_smoke_en",
            "source_and_software_archive_audit",
        ):
            with self.subTest(release_preflight_gate=gate):
                self.assertTrue(current[gate].startswith("previous evidence only:"))
        executable = current["preflight_executable"]
        self.assertEqual(
            "C:\\OBJAdjR32CM3\\dist\\ChromaMatter\\ChromaMatter.exe",
            executable["path"],
        )
        self.assertEqual(13_997_622, executable["bytes"])
        self.assertEqual(
            "8BBABEACCF9B47AC2750C86B7C38966E46F00A624C648036D600C9601CF86EBB",
            executable["sha256"],
        )
        self.assertEqual("0.8beta", executable["file_version"])
        self.assertEqual("0.8beta", executable["product_version"])
        self.assertEqual("ChromaMatter", executable["internal_name"])
        self.assertEqual("ChromaMatter.exe", executable["original_filename"])
        self.assertEqual(
            "ChromaMatter — AI Model Print Studio",
            executable["product_name"],
        )
        self.assertEqual(
            "previous evidence only: passed",
            executable["version_and_product_identity"],
        )
        self.assertIn("not current r32 release evidence", executable["scope"])
        self.assertTrue(
            current["external_checksum_record"].startswith(
                "previous evidence only:"
            )
        )
        public_stage = current["public_source_stage"]
        self.assertEqual(
            "previous evidence only: preflight passed before adoption",
            public_stage["status"],
        )
        self.assertEqual(
            "ChromaMatter_0.8beta-r32-source-public-20260821",
            public_stage["expected_root"],
        )
        self.assertEqual(230, public_stage["total_files_including_manifest"])
        self.assertEqual(229, public_stage["manifest_records"])
        self.assertTrue(public_stage["fresh_archive_exact"])
        self.assertTrue(
            public_stage["privacy_audit"].startswith("previous evidence only:")
        )
        self.assertTrue(
            public_stage["folder_archive_crc_parity"].startswith(
                "previous evidence only:"
            )
        )
        self.assertIn("33 tests", public_stage["staged_identity_icon_tooling"])
        software_stage = current["software_package_stage"]
        self.assertEqual(
            "previous evidence only: preflight passed before compliance/adoption changes",
            software_stage["status"],
        )
        self.assertEqual(
            "ChromaMatter_0.8beta-r32-ai-model-print-studio",
            software_stage["expected_root"],
        )
        self.assertEqual(1404, software_stage["total_files_including_manifest"])
        self.assertEqual(1403, software_stage["manifest_records"])
        self.assertTrue(
            software_stage["privacy_audit"].startswith("previous evidence only:")
        )
        for hash_field in (
            "final_zip_sha256",
            "public_source_zip_sha256",
            "software_package_zip_sha256",
        ):
            self.assertIsNone(current[hash_field])
        self.assertFalse(current["zip_hashes_and_sizes_embedded_in_canonical_documents"])
        self.assertFalse(current["downloads_placement_claimed"])
        self.assertFalse(current["source_publication_eligible"])
        self.assertIn(
            "previous pre-compliance evidence only",
            current["source_publication_status"],
        )
        self.assertEqual(
            "https://github.com/Ponkichi0718/ChromaMatter",
            current["public_repository_url"],
        )
        self.assertEqual("Ponkichi0718", current["public_repository_owner_handle"])
        self.assertEqual("public", current["public_repository_visibility"])
        self.assertEqual("main", current["public_repository_default_branch"])
        self.assertFalse(current["binary_publication_eligible"])
        self.assertIn("controlled PyTetWild wheel/PYD", current["binary_publication_blocker"])
        self.assertIn("are approved", current["binary_publication_blocker"])
        self.assertIn("application lock", current["binary_publication_blocker"])
        self.assertIn("immutable HTTPS Release URLs", current["binary_publication_blocker"])
        self.assertFalse(current["innovation_fund_submission_ready"])
        self.assertNotIn(
            "public repository URL and handle",
            current["innovation_fund_submission_blockers"],
        )
        self.assertTrue(
            current["publication_decision"].startswith(
                "previous preflight approval only"
            )
        )
        self.assertIn("previous r31 creator declaration", current["icon_publication_rights"])
        previous_r31 = release["previous_r31_candidate_validation"]
        self.assertTrue(previous_r31["status"].startswith("previous evidence only"))
        self.assertIn("Ran 1024 tests in 100.656s", previous_r31["source_full_regression"])
        self.assertEqual(
            "208167A225A37BAAAA473B574B2F746E46427FD0CA63FC5B7201BF3394243743",
            previous_r31["preflight_executable"]["sha256"],
        )
        previous_r30 = release["previous_r30_candidate_validation"]
        self.assertEqual("previous evidence only", previous_r30["status"])
        self.assertIn("Ran 1019 tests in 86.932s", previous_r30["source_full_regression"])
        self.assertFalse(previous_r30["applies_to_r32"])
        self.assertFalse(previous_r30["applies_to_r32_1"])

    def test_public_state_has_no_private_asset_or_recording_details(self):
        public_documents = (
            REPO_ROOT / "README.md",
            REPO_ROOT / "README_EN.md",
            REPO_ROOT / "README_JA.md",
            REPO_ROOT / "README_PUBLIC_JA.md",
            REPO_ROOT / "README_PUBLIC_EN.md",
            REPO_ROOT / "FEATURES_EN.md",
            FIXED_APP / "README_fixed_ja.md",
            FIXED_APP / "README_fixed_en.md",
            REPO_ROOT / "CURRENT_STATE.json",
            REPO_ROOT / "PROVENANCE.md",
        )
        combined = "\n".join(read_text(path) for path in public_documents)
        for forbidden in (
            "private_filename",
            "private_path",
            "private_sha256",
            "recording_filename",
            "recording_path",
            "video_sha256",
            "model_face_count",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined.casefold())
        self.assertNotIn("c:\\users", combined.casefold())

    def test_all_seven_readmes_describe_r32_2_and_r32_1_history(self):
        readmes = (
            REPO_ROOT / "README.md",
            REPO_ROOT / "README_EN.md",
            REPO_ROOT / "README_JA.md",
            REPO_ROOT / "README_PUBLIC_JA.md",
            REPO_ROOT / "README_PUBLIC_EN.md",
            FIXED_APP / "README_fixed_ja.md",
            FIXED_APP / "README_fixed_en.md",
        )
        for path in readmes:
            with self.subTest(path=path):
                text = read_text(path)
                folded = text.casefold()
                compact = folded.replace(",", "")
                for required in (
                    "ChromaMatter",
                    "AI Model Print Studio r32.2",
                    "r32.2-ai-model-print-studio",
                    "0.8beta",
                    "source.obj",
                    "source.glb",
                    "project.json",
                    "prepared_geometry.npz",
                    "GLB",
                    "1:1",
                    "QEM",
                    "type=model",
                    "Orca",
                    "manual",
                    "adaptive",
                    "1277",
                    "1274",
                    "r31",
                    "XP-PEN",
                    "passed-by-creator-declaration",
                    "ZENITH DYNAMICS CORP.",
                    "release-approved",
                    "b575b93d973ed67e7ada986469b10b4490eef4e5",
                    "1215CF77D8C8CB8AA5CE91DC7C84AE13404F3AA46221321807AD2E8A19F9064A",
                    "D5A64F3022265BCE7C5C2DFA0358DFC2C94EEA541A5A4AC5671CE3BA829BE4CC",
                    "ChromaMatter-0.8beta-r32.2-win64",
                    "r32.1",
                    "https://github.com/Ponkichi0718/ChromaMatter",
                ):
                    with self.subTest(path=path, required=required):
                        self.assertIn(required.casefold().replace(",", ""), compact)
                self.assertIn("previous evidence", folded)
                self.assertIn("pending", folded)
                self.assertIn("r32.2", folded)
                if path.parent == REPO_ROOT:
                    self.assertIn("v0.8beta-r32.2", folded)
                else:
                    self.assertIn("v0.8beta-r32.1", folded)
                self.assertIn("demodata/3mf", folded)
                self.assertTrue("seven" in folded or "7件" in text)
                self.assertTrue("weak black" in folded or "黒弱め" in text)
                self.assertTrue(
                    "part labels" in folded
                    or "labelは見た目" in text
                    or "labelはgeometry" in folded
                )
                self.assertTrue("no cap" in folded or "蓋を追加" in text)
                self.assertTrue("true hole" in folded or "本当の穴" in text)
                self.assertIn("https://note.com/ponkichi0718", folded)
                expected_features = (
                    "features_ja.md"
                    if path.name.casefold().endswith("_ja.md")
                    else "features_en.md"
                )
                self.assertIn(expected_features, folded)
                self.assertTrue(
                    "ai-use disclosure" in folded or "ai利用について" in folded
                )
                self.assertTrue(
                    "github publication" in folded or "github公開作業" in folded
                )
                self.assertTrue(
                    "technical errors" in folded or "技術的な誤り" in text
                )
                if path.name.casefold().endswith("_ja.md"):
                    self.assertIn("DemoData", text)
                    self.assertTrue("他の" in text or "ほかの" in text)
                    self.assertIn("3MF出力", text)
                else:
                    self.assertIn("bundled `demodata", folded)
                    self.assertIn("other multipart", folded)
                    self.assertIn("3mf export", folded)
                self.assertNotIn("decal beta", folded)
                self.assertNotIn("デカール β", text)

        public_build_docs = (
            REPO_ROOT / "licenses" / "BUILD_ENVIRONMENT_EN.md",
            REPO_ROOT / "licenses" / "BUILD_ENVIRONMENT_JA.md",
            REPO_ROOT / "publication" / "GITHUB_PUBLICATION_GUIDE_JA.md",
        )
        for path in public_build_docs:
            with self.subTest(public_build_doc=path):
                lines = read_text(path).splitlines()
                bootstrap_lines = [
                    index
                    for index, line in enumerate(lines)
                    if "BOOTSTRAP_WINDOWS.ps1" in line
                ]
                self.assertTrue(bootstrap_lines)
                for index in bootstrap_lines:
                    line = lines[index]
                    if (
                        "-PyTetWildWheel" in line
                        or "-PyTetWildWheelhouse" in line
                    ):
                        continue
                    self.assertTrue(
                        line.rstrip().endswith("`")
                        and index + 1 < len(lines)
                        and (
                            "-PyTetWildWheel" in lines[index + 1]
                            or "-PyTetWildWheelhouse" in lines[index + 1]
                        ),
                        f"Bare bootstrap example is not allowed in {path}: {line}",
                    )

    def test_github_readme_defaults_to_english_with_exact_japanese_alias(self):
        english = read_text(REPO_ROOT / "README_PUBLIC_EN.md")
        japanese = read_text(REPO_ROOT / "README_PUBLIC_JA.md")
        self.assertEqual(english, read_text(REPO_ROOT / "README.md"))
        self.assertEqual(english, read_text(REPO_ROOT / "README_EN.md"))
        self.assertEqual(japanese, read_text(REPO_ROOT / "README_JA.md"))

    def test_english_landing_page_is_concise_and_uses_approved_images_only(self):
        readme = read_text(REPO_ROOT / "README.md")
        features = read_text(REPO_ROOT / "FEATURES_EN.md")
        self.assertIn(
            "Turn AI-generated color OBJ and GLB models into Snapmaker U1 "
            "Full Spectrum 3MF projects using four physical filaments.",
            readme,
        )
        for required in (
            "## Download for Windows",
            "ChromaMatter-0.8beta-r32.2-win64.zip",
            "## Current status",
            "**Published release:** [`v0.8beta-r32.2`]",
            "**Frozen release source:** tag `v0.8beta-r32.2`",
            "**Published asset set:** Windows ZIP, complete corresponding source, "
            "SBOM, component map, workflow video, and detached checksums",
            "**Published r32.2 test data:** Rights-cleared Hi3D multipart GLB "
            "and reference image are included under `DemoData/`",
            "**Published demo outputs:** Seven derived 3MF reference outputs "
            "under `DemoData/3MF/`; one combined project and six part-specific projects",
            "**Physical U1 validation:** The linked public print completed; "
            "it does not prove compatibility with every model or production setup",
            "Solidification of multipart models is still unstable.",
            "## Four things ChromaMatter does",
            "## Quick Start",
            "## Technical details",
            "[日本語版はこちら](README_JA.md)",
            "[See the visual feature overview](FEATURES_EN.md)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)
        positions = [
            readme.index(marker)
            for marker in (
                "## Download for Windows",
                "Turn AI-generated color OBJ and GLB models",
                "AI concept",
                "## Current status",
                "## Four things ChromaMatter does",
                "## Quick Start",
                "## Technical details",
            )
        ]
        self.assertEqual(positions, sorted(positions))
        japanese = read_text(REPO_ROOT / "README_JA.md")
        self.assertIn("## Windows版をダウンロード", japanese)
        self.assertIn("ChromaMatter-0.8beta-r32.2-win64.zip", japanese)
        allowed_image_sources = {
            "source/fixed_app/assets/obj_adjuster_icon.png",
            "https://assets.st-note.com/img/1787038136-QYcX12yPUL4fzm5RWZNbiEqM.jpg?width=1200",
            "https://assets.st-note.com/img/1787038182-v0C8IT5i1jVeKLdNX3ZygYu4.png?width=1200",
            "https://assets.st-note.com/img/1787038261-fQtHZho5CXvrYl94M7zJOqLD.png?width=1200",
            "https://assets.st-note.com/img/1787038285-sNiOGxEzyLoRrklQAXH7BJ8W.png?width=1200",
            "https://assets.st-note.com/img/1787193863-DjEUKLdVrxFgauov4mzq7QB9.png?width=1200",
            "https://assets.st-note.com/img/1787193878-2RMCKirmlunSDIXfhzQgEHpd.png?width=1200",
            "https://assets.st-note.com/img/1787194049-FwXqus5ArK8B4NoU1eIQYzPg.png?width=1200",
            "https://assets.st-note.com/img/1787193923-A1VTIhjR6w07qWedXZloDEFU.png?width=1200",
        }
        expected_image_counts = {"README.md": 5, "FEATURES_EN.md": 9}
        for name, document in (("README.md", readme), ("FEATURES_EN.md", features)):
            sources = re.findall(r'<img[^>]+src="([^"]+)"', document)
            self.assertEqual(expected_image_counts[name], len(sources))
            for source in sources:
                with self.subTest(image_source=source):
                    self.assertIn(source, allowed_image_sources)
            self.assertNotIn("decal", document.casefold())
        self.assertIn("## Physical U1 result", readme)
        self.assertIn("48 hours", readme)
        self.assertIn("220 g including the prime tower", readme)
        self.assertIn("not a guarantee that every model", readme)
        self.assertIn(
            "ChromaMatter-simple-workflow-demo.mp4",
            readme,
        )
        self.assertIn(
            "## 2. Limited, unofficial Hi3D-style multipart GLB support (beta)",
            features,
        )
        self.assertIn("It does not claim compatibility with every file", features)
        self.assertIn("nf6c77165127c", features)

        japanese_features = read_text(REPO_ROOT / "FEATURES_JA.md")
        self.assertIn("## Hi3D系分割GLB対応（β・非公式）", japanese_features)
        self.assertIn("すべてのfileとの互換性を保証するものではありません", japanese_features)
        self.assertIn("nf6c77165127c", japanese_features)

        binary_en = read_text(FIXED_APP / "public_binary" / "README_EN.md")
        binary_ja = read_text(FIXED_APP / "public_binary" / "README_JA.md")
        self.assertIn("Hi3D-style multipart GLB support is beta and unofficial", binary_en)
        self.assertIn("Hi3D系分割GLB対応はβ・非公式", binary_ja)

    def test_public_docs_keep_multipart_solidification_beta_disclosure(self):
        english_markers = (
            "Solidification of multipart models is still unstable.",
            "The bundled `DemoData` is a confirmed successful case",
            "other multipart files may fail to solidify or export as 3MF",
            "one reason ChromaMatter remains `0.8beta`",
        )
        japanese_markers = (
            "パーツ化モデルの閉立体化はまだ不安定です。",
            "同梱の`DemoData`は閉立体化・3MF出力の成功を確認しています",
            "他の分割ファイルでは閉立体化または3MF出力に失敗することがあります",
            "ChromaMatterを`0.8beta`としている理由の一つです",
        )
        demo_root = FIXED_APP / "public_binary" / "DemoData"
        release_notes = REPO_ROOT / "publication" / "RELEASE_NOTES_r32.2.md"
        english_docs = (
            REPO_ROOT / "README.md",
            FIXED_APP / "public_binary" / "README_EN.md",
            demo_root / "README_EN.md",
            demo_root / "NOTICE_EN.md",
            release_notes,
        )
        japanese_docs = (
            REPO_ROOT / "README_JA.md",
            FIXED_APP / "public_binary" / "README_JA.md",
            demo_root / "README_JA.md",
            demo_root / "NOTICE_JA.md",
            release_notes,
        )
        for path in english_docs:
            document = read_text(path)
            for marker in english_markers:
                with self.subTest(path=path, marker=marker):
                    self.assertIn(marker, document)
        for path in japanese_docs:
            document = read_text(path)
            for marker in japanese_markers:
                with self.subTest(path=path, marker=marker):
                    self.assertIn(marker, document)

        status_docs = (
            REPO_ROOT / "FEATURES_EN.md",
            REPO_ROOT / "FEATURES_JA.md",
            REPO_ROOT / "PROVENANCE.md",
            REPO_ROOT / "HANDOFF.md",
            REPO_ROOT / "publication" / "BINARY_RELEASE_HANDOFF_JA.md",
            REPO_ROOT / "publication" / "PUBLICATION_CHECKLIST_JA.md",
            REPO_ROOT / "publication" / "GITHUB_PUBLICATION_GUIDE_JA.md",
            REPO_ROOT / "publication" / "LEGAL_AND_RIGHTS_JA.md",
            REPO_ROOT / "publication" / "INNOVATION_FUND_APPLICATION_DRAFT.md",
            REPO_ROOT / "publication" / "INNOVATION_FUND_STATUS_JA.md",
            REPO_ROOT / "publication" / "VIDEO_VALIDATION_CHECKLIST_JA.md",
        )
        for path in status_docs:
            document = read_text(path).casefold()
            with self.subTest(status_document=path):
                self.assertIn("0.8beta", document)
                self.assertIn("demodata", document)
                self.assertIn("3mf", document)
                self.assertTrue(
                    "multipart" in document
                    or "パーツ化" in document
                    or "分割" in document
                )
                self.assertTrue("fail" in document or "失敗" in document)

        english_landing = read_text(REPO_ROOT / "README.md")
        self.assertLess(
            english_landing.index(english_markers[0]),
            english_landing.index("Turn AI-generated color OBJ and GLB models"),
        )
        japanese_landing = read_text(REPO_ROOT / "README_JA.md")
        self.assertLess(
            japanese_landing.index(japanese_markers[0]),
            japanese_landing.index("ChromaMatter — AI Model Print Studioは"),
        )


if __name__ == "__main__":
    unittest.main()
