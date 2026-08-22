from __future__ import annotations

import argparse
import base64
import copy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "tooling" / "stage_corresponding_source.py"
COMPONENT_MANIFEST = REPO_ROOT / "tooling" / "corresponding_source_components.json"
EXTERNAL_LOCK = REPO_ROOT / "tooling" / "meshlab_windows_external_archives.lock.json"
REBUILD_TEMPLATE = REPO_ROOT / "tooling" / "pytetwild_rebuild_lock.template.json"
POWERSHELL_WRAPPER = REPO_ROOT / "tooling" / "stage_corresponding_source.ps1"

SPEC = importlib.util.spec_from_file_location("stage_corresponding_source", HELPER)
assert SPEC is not None and SPEC.loader is not None
stage_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_tool)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout.strip()


def _new_repository(path: Path, files: dict[str, str]) -> str:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "fixture@example.invalid")
    _git(path, "config", "user.name", "Fixture Builder")
    for relative, content in files.items():
        destination = path / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")
    _git(path, "add", "--all")
    _git(path, "commit", "-m", "fixture")
    return _git(path, "rev-parse", "HEAD")


def _zip(path: Path, name: str = "source/ok.txt") -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(name, b"fixture source\n")
    return path.read_bytes()


def _record_sha256(payload: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return f"sha256={encoded.decode('ascii')}"


def _pytetwild_wheel(
    path: Path,
    record_case: str = "valid",
    *,
    repaired: bool = True,
) -> dict[str, str]:
    dist_info = "pytetwild-0.3.0.dist-info"
    record_name = f"{dist_info}/RECORD"
    files = {
        "pytetwild/__init__.py": b"from ._pytetwild import tetrahedralize\n",
        "pytetwild/_pytetwild.pyd": b"fixture compiled wrapper\n",
        "pytetwild/data,fixture.txt": b"CSV quoted path\n",
        f"{dist_info}/METADATA": b"Name: pytetwild\nVersion: 0.3.0\n",
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nTag: cp312-abi3-win_amd64\n",
    }
    if repaired:
        files["pytetwild.libs/mpir-fixture.dll"] = b"fixture MPIR runtime\n"
        files[f"{dist_info}/DELVEWHEEL"] = b"Version: 1.12.1\n"
    rows = [
        [name, _record_sha256(payload), str(len(payload))]
        for name, payload in files.items()
    ]
    rows.append([record_name, "", ""])
    if record_case == "missing":
        rows.pop(0)
    elif record_case == "unknown":
        rows.append(["pytetwild/unknown.txt", _record_sha256(b"unknown"), "7"])
    elif record_case == "duplicate":
        rows.append(list(rows[0]))
    elif record_case == "case-duplicate":
        duplicate = list(rows[0])
        duplicate[0] = duplicate[0].upper()
        rows.append(duplicate)
    elif record_case == "unsafe":
        rows[0][0] = "../pytetwild.py"
    elif record_case == "hash":
        rows[0][1] = _record_sha256(b"wrong")
    elif record_case == "size":
        rows[0][2] = str(int(rows[0][2]) + 1)
    elif record_case == "record-self":
        rows[-1][1] = _record_sha256(b"not allowed")
    elif record_case != "valid":
        raise AssertionError(f"Unknown RECORD fixture case: {record_case}")

    record_buffer = io.StringIO(newline="")
    writer = csv.writer(record_buffer, lineterminator="\n")
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, payload in files.items():
            package.writestr(name, payload)
        package.writestr(record_name, record_buffer.getvalue().encode("utf-8"))
    return {
        "filename": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "python_tag": "cp312",
        "abi_tag": "abi3",
        "platform_tag": "win_amd64",
    }


def _release_provenance(asset_name: str, asset_id: int) -> dict[str, object]:
    return {
        "asset_name": asset_name,
        "github_asset_id": asset_id,
        "github_release_id": 12345,
        "github_release_tag": "fixture-v1",
        "asset_created_at": "2026-08-21T00:00:00Z",
        "asset_updated_at": "2026-08-21T00:01:00Z",
        "release_repository_url": "https://github.com/example/dependencies",
        "release_api_url": "https://api.github.com/repos/example/dependencies/releases/12345",
        "asset_api_url": f"https://api.github.com/repos/example/dependencies/releases/assets/{asset_id}",
        "resolved_download_url": f"https://github.com/example/{asset_name}",
        "sha256_method": "downloaded-official-github-release-asset",
    }


class CorrespondingSourceManifestTests(unittest.TestCase):
    def test_release_manifest_pins_exact_audited_sources(self) -> None:
        manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
        components = stage_tool.validate_component_manifest(manifest)
        expected_commits = {
            "tetgen-python-0.8.3": "af5ff36f069f7f203db031c24e1f05d109d8c25c",
            "pytetwild-0.3.0": "eea46df87ef58e861956b7a710f42ab58eaa02a0",
            "ftetwild-d7d99bb": "d7d99bb4387a07895b9adce058dc7305f6b6e5ab",
            "pymeshlab-2025.7.post1": "1dc199f9b6c43e58b6db346ba4600866b950b8ae",
            "meshlab-d876376": "d876376e3cc4f92d257e248023d82cbac5b03c7d",
            "pymeshlab-onetbb-2021.11.0": "8b829acc65569019edb896c5150d427f288e8aba",
            "pymeshlab-pybind11-2.13.6": "a2e59f0e7065404b44dfe92a28aca47ba1378dc4",
            "meshlab-vcglib-2025.07": "c94ef4e12e9ea3ae986d9af91005be8328d13719",
            "shapely-2.1.2": "5fb639d1056888d135fe56bfaf750c9648addeec",
            "geos-3.13.1": "431568d6e311e0bbfb057b4ec3d44d0d3ba3335f",
            "mpir-3.0.0": "cdd444aedfcbb190f00328526ef278428702d56e",
            "pyinstaller-6.20.0": "8a6172796b56aa428980c3628663ba08e77ad81e",
        }
        for component_id, commit in expected_commits.items():
            with self.subTest(component_id=component_id):
                self.assertEqual(components[component_id]["commit"], commit)

        self.assertEqual(
            components["qt-5.15.2"]["sha256"],
            "3a530d1b243b5dec00bc54937455471aaa3e56849d2593edb8ded07228202240",
        )
        self.assertIn("gitlab.com", manifest["allowed_redirect_host_suffixes"])
        mpir_required = set(components["mpir-3.0.0"]["required_paths"])
        self.assertTrue({"COPYING", "COPYING.LIB"}.issubset(mpir_required))
        self.assertEqual(
            components["ftetwild-json"]["required_paths"],
            ["LICENSE.MIT", "include/nlohmann/json.hpp"],
        )
        self.assertEqual(
            components["ftetwild-geogram-1.9.6"]["required_gitlinks"],
            [
                {
                    "path": "src/lib/geogram/third_party/amgcl",
                    "url": "https://github.com/ddemidov/amgcl.git",
                    "commit": "ab57038d68ee372ed5df280631051b91f17ed2d1",
                },
                {
                    "path": "src/lib/geogram/third_party/libMeshb",
                    "url": "https://github.com/LoicMarechal/libMeshb.git",
                    "commit": "952a157c9d516b28cc6c69cd1550c3e48d4792f9",
                },
                {
                    "path": "src/lib/geogram/third_party/rply",
                    "url": "https://github.com/diegonehab/rply.git",
                    "commit": "4296cc91b5c8c26d4e7d7aac0cee2b194ffc5800",
                },
            ],
        )
        self.assertEqual(
            manifest["pytetwild_rebuild_policy"]["nanobind_required_gitlinks"],
            [
                {
                    "path": "ext/robin_map",
                    "url": "https://github.com/Tessil/robin-map.git",
                }
            ],
        )

        relations = {
            (item["parent"], item["path"]): item["child"]
            for item in manifest["submodule_relations"]
        }
        self.assertEqual(
            relations[("pytetwild-0.3.0", "src/fTetWild")],
            "ftetwild-d7d99bb",
        )
        self.assertEqual(
            relations[("pymeshlab-2025.7.post1", "src/meshlab")],
            "meshlab-d876376",
        )
        self.assertEqual(
            relations[("meshlab-d876376", "src/vcglib")],
            "meshlab-vcglib-2025.07",
        )
        self.assertFalse(
            any(parent == "ftetwild-geogram-1.9.6" for parent, _path in relations)
        )
        geogram_destination = components["ftetwild-geogram-1.9.6"]["destination"]
        self.assertFalse(
            any(
                component_id != "ftetwild-geogram-1.9.6"
                and component["destination"].startswith(f"{geogram_destination}/")
                for component_id, component in components.items()
            )
        )

        mesh_runtime_evidence = next(
            item
            for item in manifest["pin_evidence"]
            if item["component"] == "meshlab-d876376"
            and item["path"] == "src/external/embree.cmake"
        )
        self.assertEqual(
            mesh_runtime_evidence["required_literals"],
            [
                "set(EMBREE_MINOR 3.3)",
                "set(EMBREE_WIN_LINK https://github.com/embree/embree/releases/download/v${EMBREE_VER}/embree-${EMBREE_VER}.x64.windows.zip)",
                "${EMBREE_WIN_DIR}/bin/tbb12.dll",
            ],
        )

        rule = manifest["dynamic_archive_rules"][0]
        self.assertEqual(
            sorted(rule["known_unhashed_variables"]),
            ["EMBREE_WIN_LINK", "TBB_WIN_LINK"],
        )
        self.assertTrue(rule["require_sha256_lock_for_unhashed"])
        self.assertEqual(
            set(rule["excluded_variables"]),
            {"EMBREE_LINK", "ISPC_LINK"},
        )
        self.assertEqual(
            {gap["id"] for gap in manifest["known_gaps"]},
            {
                "pytetwild-nanobind-exact-build-version",
                "meshlab-md5-only-external-archives",
            },
        )
        self.assertEqual(
            manifest["release_approval"],
            {
                "status": "release-approved",
                "requires_all_known_gaps_resolved": True,
                "required_gap_ids": [
                    "pytetwild-nanobind-exact-build-version",
                    "meshlab-md5-only-external-archives",
                ],
            },
        )
        gap_resolvers = {
            gap["id"]: gap["resolution_evidence"] for gap in manifest["known_gaps"]
        }
        self.assertEqual(
            gap_resolvers["pytetwild-nanobind-exact-build-version"],
            {"kind": "pytetwild-controlled-rebuild"},
        )
        self.assertEqual(
            gap_resolvers["meshlab-md5-only-external-archives"],
            {
                "kind": "complete-dynamic-archive-sha256-lock",
                "rule_id": "meshlab-windows-external-build-inputs",
            },
        )
        self.assertEqual(
            manifest["default_external_archive_lock"],
            EXTERNAL_LOCK.name,
        )
        external = stage_tool._load_external_lock(
            EXTERNAL_LOCK,
            components["meshlab-d876376"]["commit"],
            require_release_provenance=True,
            expected_exclusions=rule["excluded_variables"],
        )
        self.assertEqual(len(external), 21)
        self.assertEqual(
            external["EMBREE_WIN_LINK"]["sha256"],
            "d4c07f88df9f009dd84e4e9b9dcec32ad7d96f927bd88de00b721b0923d481a9",
        )
        self.assertEqual(
            external["TBB_WIN_LINK"]["sha256"],
            "8e2b48500fe93ab77bad435eea7ed9c513eacb032ee6a90e086d99b7f96bd8d5",
        )
        self.assertEqual(
            components["pymeshlab-onetbb-2021.11.0"]["version"],
            "2021.11.0",
        )
        self.assertEqual(
            components["pymeshlab-onetbb-2021.11.0"]["required_paths"],
            ["LICENSE.txt", "CMakeLists.txt"],
        )
        self.assertEqual(
            components["pymeshlab-onetbb-2021.11.0"]["url"],
            "https://github.com/uxlfoundation/oneTBB.git",
        )
        stage_tool._validate_blocked_rebuild_template(
            REBUILD_TEMPLATE,
            components["pytetwild-0.3.0"]["commit"],
        )

    def test_complete_windows_external_lock_v2_is_strict_and_review_bound(self) -> None:
        manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
        rule = manifest["dynamic_archive_rules"][0]
        lock = json.loads(EXTERNAL_LOCK.read_text(encoding="utf-8"))
        self.assertEqual(lock["schema_version"], 2)
        self.assertEqual(lock["platform"], "windows")
        self.assertEqual(lock["platform_exclusions"], rule["excluded_variables"])
        self.assertEqual(len(lock["archives"]), 21)
        self.assertEqual(
            {entry["provenance"]["provenance_kind"] for entry in lock["archives"]},
            stage_tool.EXTERNAL_ARCHIVE_PROVENANCE_KINDS,
        )
        tinygltf = next(
            entry for entry in lock["archives"] if entry["variable"] == "TINYGLTF_LINK"
        )
        self.assertEqual(
            tinygltf["provenance"]["meshlab_only_paths"],
            ["tools/windows/premake5.exe"],
        )
        self.assertEqual(
            tinygltf["provenance"]["meshlab_only_file_execution_policy"],
            "preserve-do-not-execute",
        )
        self.assertTrue(tinygltf["provenance"]["security_review_required"])
        self.assertEqual(
            tinygltf["provenance"]["release_review_status"],
            "required-before-binary-release",
        )

        with self.assertRaisesRegex(stage_tool.StageError, "expected platform exclusions"):
            stage_tool._load_external_lock(
                EXTERNAL_LOCK,
                lock["meshlab_commit"],
                require_release_provenance=True,
            )

    def test_external_lock_v2_rejects_provenance_or_identity_drift(self) -> None:
        base = json.loads(EXTERNAL_LOCK.read_text(encoding="utf-8"))
        exclusions = base["platform_exclusions"]

        def entry(data: dict, variable: str) -> dict:
            return next(item for item in data["archives"] if item["variable"] == variable)

        cases = {
            "top-level-extra": lambda data: data.update({"unreviewed": True}),
            "exclusion-drift": lambda data: data["platform_exclusions"].update(
                {"EMBREE_LINK": "changed"}
            ),
            "release-asset-id": lambda data: entry(data, "CGAL_LINK")[
                "provenance"
            ].update({"github_asset_id": 1}),
            "tag-commit": lambda data: entry(data, "CORTO_LINK")["provenance"].update(
                {"peeled_commit_sha": "0" * 40}
            ),
            "official-checksum": lambda data: entry(data, "BOOST_LINK")[
                "provenance"
            ].update({"official_sha256": "0" * 64}),
            "official-project-md5": lambda data: entry(data, "OPENCTM_LINK")[
                "provenance"
            ].update({"official_md5": "0" * 32}),
            "mirror-size": lambda data: entry(data, "LIB3DS_LINK")[
                "provenance"
            ].update({"official_reference_byte_size": 1}),
            "tinygltf-policy": lambda data: entry(data, "TINYGLTF_LINK")[
                "provenance"
            ].update({"security_review_required": False}),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, mutate in cases.items():
                with self.subTest(name=name):
                    changed = copy.deepcopy(base)
                    mutate(changed)
                    path = root / f"{name}.json"
                    path.write_text(
                        json.dumps(changed, indent=2) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    with self.assertRaises(stage_tool.StageError):
                        stage_tool._load_external_lock(
                            path,
                            base["meshlab_commit"],
                            require_release_provenance=True,
                            expected_exclusions=exclusions,
                        )

    def test_tinygltf_known_extra_member_is_hashed_without_execution(self) -> None:
        lock = json.loads(EXTERNAL_LOCK.read_text(encoding="utf-8"))
        tinygltf = next(
            entry for entry in lock["archives"] if entry["variable"] == "TINYGLTF_LINK"
        )
        payload = b"fixture unsigned executable; never execute\n"
        fixture = copy.deepcopy(tinygltf)
        fixture["provenance"]["meshlab_only_file_sha256"] = hashlib.sha256(
            payload
        ).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "tinygltf.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
                package.writestr("tinygltf-2.6.3/README.md", b"fixture\n")
                package.writestr(
                    "tinygltf-2.6.3/tools/windows/premake5.exe",
                    payload,
                )
            stage_tool._verify_declared_nonexecuted_archive_member(archive, fixture)

            fixture["provenance"]["meshlab_only_file_sha256"] = "0" * 64
            with self.assertRaisesRegex(stage_tool.StageError, "does not match its lock"):
                stage_tool._verify_declared_nonexecuted_archive_member(archive, fixture)

    def test_status_string_alone_cannot_approve_a_manifest(self) -> None:
        manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
        manifest["bundle_status"] = "release-approved"
        with self.assertRaisesRegex(stage_tool.StageError, "must remain candidate"):
            stage_tool.validate_component_manifest(manifest)

        manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
        manifest["known_gaps"].pop()
        with self.assertRaisesRegex(stage_tool.StageError, "must match every known gap"):
            stage_tool.validate_component_manifest(manifest)

    def test_required_gitlink_manifest_expectations_fail_closed(self) -> None:
        manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
        geogram = next(
            component
            for component in manifest["components"]
            if component["id"] == "ftetwild-geogram-1.9.6"
        )
        geogram["required_gitlinks"].append(dict(geogram["required_gitlinks"][0]))
        with self.assertRaisesRegex(stage_tool.StageError, "duplicate path"):
            stage_tool.validate_component_manifest(manifest)

        manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
        manifest["pytetwild_rebuild_policy"].pop("nanobind_required_gitlinks")
        with self.assertRaisesRegex(stage_tool.StageError, "non-empty array"):
            stage_tool.validate_component_manifest(manifest)

    def test_release_state_requires_verified_evidence_for_every_gap(self) -> None:
        manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
        pytetwild = {
            "id": "pytetwild-nanobind-exact-build-version",
            "resolution": "verified-controlled-rebuild",
            "rebuild_lock_sha256": "1" * 64,
            "historical_wheel": {
                "sha256": "11964e295a54cf9e2f6920a920aeeba27668c9b14e369a86f72ec5baa4f46060",
                "nanobind_version_status": "unknown-not-asserted",
                "release_disposition": "excluded",
            },
            "wheel": {"filename": "repaired.whl", "sha256": "3" * 64},
            "raw_wheel": {"filename": "raw.whl", "sha256": "4" * 64},
            "nanobind": {
                "version": "2.12.0",
                "source_url": "https://github.com/wjakob/nanobind.git",
                "commit": "2a61ad2494d09fecb2e13322c1383342c299900d",
            },
            "environment": {
                "python_version": "3.12.10",
                "pip_version": "25.0.1",
                "cibuildwheel_version": "3.3.1",
                "runner_image": "self-hosted-windows-controlled-offline",
                "compiler": "MSVC 14.44.35211",
                "compiler_family_requested_from_vsdevcmd": "14.44",
                "visual_studio_installation_version": "17.14.37614.0",
                "cmake_version": "3.29.6",
                "ninja_version": "1.13.0",
                "nanobind_version": "2.12.0",
                "build_version": "1.5.0",
                "scikit_build_core_version": "0.12.2",
                "delvewheel_version": "1.12.1",
                "abi3audit_version": "0.0.26",
                "numpy_version": "2.5.1",
                "windows_sdk_version": "10.0.26100.0",
                "windows_sdk_servicing_version": "10.0.26100.7705",
            },
            "bound_evidence": {
                name: {"filename": f"{name}.fixture", "sha256": "6" * 64}
                for name in (
                    "build_recipe",
                    "build_requirements_lock",
                    "source_patch",
                    "attestation",
                    "release_binding",
                )
            },
            "audit_logs": {
                name: {"filename": filename, "sha256": "7" * 64}
                for name, filename in stage_tool.PYTETWILD_AUDIT_LOG_FILES.items()
            },
        }
        meshlab = {
            "id": "meshlab-md5-only-external-archives",
            "resolution": "verified-complete-dynamic-archive-sha256-lock",
            "rule_id": "meshlab-windows-external-build-inputs",
            "external_archive_lock_sha256": "6" * 64,
            "locked_variables": ["ARCHIVE_A"],
            "archive_count": 1,
        }

        status, unresolved, resolved = stage_tool._evaluate_release_state(manifest, [])
        self.assertEqual(status, "candidate-only-not-release-approved")
        self.assertEqual(len(unresolved), 2)
        self.assertEqual(resolved, [])

        status, unresolved, resolved = stage_tool._evaluate_release_state(
            manifest,
            [pytetwild],
        )
        self.assertEqual(status, "candidate-only-not-release-approved")
        self.assertEqual(
            [gap["id"] for gap in unresolved],
            ["meshlab-md5-only-external-archives"],
        )
        self.assertEqual(resolved, [pytetwild])

        status, unresolved, resolved = stage_tool._evaluate_release_state(
            manifest,
            [meshlab, pytetwild],
        )
        self.assertEqual(status, "release-approved")
        self.assertEqual(unresolved, [])
        self.assertEqual(resolved, [pytetwild, meshlab])

        missing_patch = copy.deepcopy(pytetwild)
        missing_patch["bound_evidence"].pop("source_patch")
        with self.assertRaisesRegex(stage_tool.StageError, "complete bound build evidence"):
            stage_tool._evaluate_release_state(manifest, [missing_patch, meshlab])

        missing_raw = copy.deepcopy(pytetwild)
        missing_raw.pop("raw_wheel")
        with self.assertRaisesRegex(stage_tool.StageError, r"missing=\['raw_wheel'\]"):
            stage_tool._evaluate_release_state(manifest, [missing_raw, meshlab])

        extra_audit = copy.deepcopy(pytetwild)
        extra_audit["audit_logs"]["unexpected"] = {
            "filename": "unexpected.log",
            "sha256": "8" * 64,
        }
        with self.assertRaisesRegex(stage_tool.StageError, r"unknown=\['unexpected'\]"):
            stage_tool._evaluate_release_state(manifest, [extra_audit, meshlab])

        invalid = dict(meshlab, resolution="sha256-lock")
        with self.assertRaisesRegex(stage_tool.StageError, "complete SHA-256 lock"):
            stage_tool._evaluate_release_state(manifest, [pytetwild, invalid])

    def test_redirect_allowlist_uses_host_boundaries(self) -> None:
        suffixes = ("gitlab.com", "github.com")
        self.assertTrue(stage_tool._host_allowed("gitlab.com", suffixes))
        self.assertTrue(stage_tool._host_allowed("assets.github.com", suffixes))
        self.assertFalse(stage_tool._host_allowed("evilgitlab.com", suffixes))
        self.assertFalse(stage_tool._host_allowed("github.com.evil.invalid", suffixes))

    def test_archive_traversal_and_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            traversal = root / "traversal.zip"
            with zipfile.ZipFile(traversal, "w") as package:
                package.writestr("../outside.txt", b"no")
            with self.assertRaisesRegex(stage_tool.StageError, "traversal"):
                stage_tool._validate_archive_members(traversal)

            linked = root / "linked.zip"
            with zipfile.ZipFile(linked, "w") as package:
                info = zipfile.ZipInfo("source/link")
                info.create_system = 3
                info.external_attr = ((stat.S_IFLNK | 0o777) << 16)
                package.writestr(info, "target")
            with self.assertRaisesRegex(stage_tool.StageError, "links are forbidden"):
                stage_tool._validate_archive_members(linked)

            duplicate_directory = root / "duplicate-directory.zip"
            with zipfile.ZipFile(duplicate_directory, "w") as package:
                package.writestr("lib/", b"")
                package.writestr("lib/", b"")
                package.writestr("lib/source.txt", b"ok")
            stage_tool._validate_archive_members(duplicate_directory)

            duplicate_file = root / "duplicate-file.zip"
            with zipfile.ZipFile(duplicate_file, "w") as package:
                package.writestr("source.txt", b"one")
                package.writestr("source.txt", b"two")
            with self.assertRaisesRegex(stage_tool.StageError, "Duplicate"):
                stage_tool._validate_archive_members(duplicate_file)

            extracted = root / "duplicate-directory-extracted"
            stage_tool._safe_extract_zip(duplicate_directory, extracted)
            self.assertEqual((extracted / "lib" / "source.txt").read_bytes(), b"ok")

    def test_archive_member_paths_reject_noncanonical_windows_and_unicode_names(self) -> None:
        cases = {
            "source//file.txt": "non-normal",
            "source/./file.txt": "non-normal",
            "./source/file.txt": "non-normal",
            "source/../file.txt": "traversal",
            "C:/source/file.txt": "Unsafe|drive",
            "C:source.txt": "Unsafe|drive",
            "//server/share/file.txt": "Unsafe|root",
            "source\\file.txt": "Unsafe",
            "source/file.txt:stream": "ADS",
            "source/CON.txt": "reserved Windows name",
            "source/file.": "Windows-unsafe",
            "source/file ": "Windows-unsafe",
            "source/control\n.txt": "control character",
            "source/cafe\u0301.txt": "NFC-normalized",
            "source/nul\x00hidden.txt": "control character",
        }
        for name, message in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(stage_tool.StageError, message):
                    stage_tool._archive_member_parts(name)

        self.assertEqual(
            stage_tool._archive_member_parts("source/lib/", is_directory=True),
            ("source", "lib"),
        )

    def test_zip_original_name_encryption_special_and_reparse_are_rejected(self) -> None:
        nul_name = zipfile.ZipInfo("source/safe.txt")
        nul_name.orig_filename = "source/nul\x00hidden.txt"
        with self.assertRaisesRegex(stage_tool.StageError, "original name"):
            stage_tool._zip_member_details(nul_name)

        for flag in (0x01, 0x40, 0x41):
            with self.subTest(flag=flag):
                encrypted = zipfile.ZipInfo("source/encrypted.txt")
                encrypted.flag_bits = flag
                with self.assertRaisesRegex(stage_tool.StageError, "Encrypted"):
                    stage_tool._zip_member_details(encrypted)

        special_types = {
            "symlink": stat.S_IFLNK,
            "fifo": stat.S_IFIFO,
            "socket": stat.S_IFSOCK,
            "block": stat.S_IFBLK,
            "character": stat.S_IFCHR,
        }
        for label, file_type in special_types.items():
            with self.subTest(kind=label):
                special = zipfile.ZipInfo(f"source/{label}")
                special.create_system = 3
                special.external_attr = ((file_type | 0o600) << 16)
                with self.assertRaisesRegex(stage_tool.StageError, "forbidden"):
                    stage_tool._zip_member_details(special)

        reparse = zipfile.ZipInfo("source/reparse")
        reparse.create_system = 0
        reparse.external_attr = 0x400
        with self.assertRaisesRegex(stage_tool.StageError, "reparse-point"):
            stage_tool._zip_member_details(reparse)

    def test_zip_validator_rejects_nul_case_and_file_ancestor_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            nul_archive = root / "nul.zip"
            with zipfile.ZipFile(nul_archive, "w") as package:
                package.writestr("source/X.txt", b"bad")
            payload = nul_archive.read_bytes()
            self.assertEqual(payload.count(b"source/X.txt"), 2)
            nul_archive.write_bytes(payload.replace(b"source/X.txt", b"source/\x00.txt"))
            with self.assertRaisesRegex(stage_tool.StageError, "original name"):
                stage_tool._validate_archive_members(nul_archive)

            collisions = {
                "case": (("Source/file.txt", b"one"), ("source/FILE.txt", b"two")),
                "parent-first": (("source", b"file"), ("source/child.txt", b"child")),
                "parent-last": (("source/child.txt", b"child"), ("SOURCE", b"file")),
            }
            for label, members in collisions.items():
                with self.subTest(case=label):
                    archive = root / f"{label}.zip"
                    with zipfile.ZipFile(archive, "w") as package:
                        for name, data in members:
                            package.writestr(name, data)
                    with self.assertRaisesRegex(
                        stage_tool.StageError,
                        "Duplicate|file/ancestor",
                    ):
                        stage_tool._validate_archive_members(archive)
            with self.assertRaisesRegex(stage_tool.StageError, "file/ancestor"):
                stage_tool._safe_extract_zip(
                    root / "parent-first.zip",
                    root / "parent-first-extracted",
                )

    def test_tar_validation_and_extraction_share_canonical_tree_rules(self) -> None:
        def add_file(package: tarfile.TarFile, name: str, data: bytes = b"ok") -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            package.addfile(info, io.BytesIO(data))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = root / "valid.tar"
            with tarfile.open(valid, "w") as package:
                for _ in range(2):
                    directory = tarfile.TarInfo("source/lib/")
                    directory.type = tarfile.DIRTYPE
                    package.addfile(directory)
                add_file(package, "source/lib/file.txt")
            stage_tool._validate_archive_members(valid)
            destination = root / "valid-extracted"
            stage_tool._safe_extract_tar(valid, destination)
            self.assertEqual((destination / "source/lib/file.txt").read_bytes(), b"ok")

            malformed = root / "malformed.tar"
            with tarfile.open(malformed, "w") as package:
                add_file(package, "source//file.txt")
            with self.assertRaisesRegex(stage_tool.StageError, "non-normal"):
                stage_tool._validate_archive_members(malformed)

            ancestor = root / "ancestor.tar"
            with tarfile.open(ancestor, "w") as package:
                add_file(package, "source")
                add_file(package, "source/file.txt")
            with self.assertRaisesRegex(stage_tool.StageError, "file/ancestor"):
                stage_tool._validate_archive_members(ancestor)
            with self.assertRaisesRegex(stage_tool.StageError, "file/ancestor"):
                stage_tool._safe_extract_tar(ancestor, root / "ancestor-extracted")

            special = root / "special.tar"
            with tarfile.open(special, "w") as package:
                fifo = tarfile.TarInfo("source/fifo")
                fifo.type = tarfile.FIFOTYPE
                package.addfile(fifo)
            with self.assertRaisesRegex(stage_tool.StageError, "special member"):
                stage_tool._validate_archive_members(special)

    def test_pytetwild_wheel_record_covers_and_hashes_every_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "pytetwild-0.3.0-cp312-abi3-win_amd64.whl"
            specification = _pytetwild_wheel(wheel)
            stage_tool._verify_pytetwild_wheel(wheel, specification)

    def test_pytetwild_wheel_record_rejects_incomplete_or_ambiguous_paths(self) -> None:
        cases = {
            "missing": "missing entries",
            "unknown": "unknown entries",
            "duplicate": "duplicate path",
            "case-duplicate": "duplicate path",
            "unsafe": "traversal|non-normal",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for record_case, message in cases.items():
                with self.subTest(record_case=record_case):
                    wheel = root / f"pytetwild-{record_case}.whl"
                    specification = _pytetwild_wheel(wheel, record_case)
                    with self.assertRaisesRegex(stage_tool.StageError, message):
                        stage_tool._verify_pytetwild_wheel(wheel, specification)

    def test_pytetwild_wheel_record_rejects_hash_size_and_self_binding(self) -> None:
        cases = {
            "hash": "SHA-256 mismatch",
            "size": "size mismatch",
            "record-self": "own hash and size empty",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for record_case, message in cases.items():
                with self.subTest(record_case=record_case):
                    wheel = root / f"pytetwild-{record_case}.whl"
                    specification = _pytetwild_wheel(wheel, record_case)
                    with self.assertRaisesRegex(stage_tool.StageError, message):
                        stage_tool._verify_pytetwild_wheel(wheel, specification)

    def test_application_requirements_bind_only_the_repaired_pytetwild_wheel(
        self,
    ) -> None:
        repaired = "1" * 64
        historical = "2" * 64
        wrong = "3" * 64

        def declaration(name: str, version: str, *hashes: str) -> str:
            return (
                f"{name}=={version} "
                + " ".join(f"--hash=sha256:{digest}" for digest in hashes)
                + "\n"
            )

        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "requirements-build.lock"
            lock.write_text(
                declaration("numpy", "2.5.1", wrong)
                + declaration("pytetwild", "0.3.0", repaired),
                encoding="utf-8",
                newline="\n",
            )
            stage_tool._verify_application_requirements_lock(
                lock,
                repaired,
                historical,
            )

            cases = {
                "rebuilt hash moved to another package": (
                    declaration("pytetwild", "0.3.0", wrong)
                    + declaration("numpy", "2.5.1", repaired),
                    "exactly the repaired wheel",
                ),
                "multiple PyTetWild hashes": (
                    declaration("pytetwild", "0.3.0", repaired, wrong),
                    "exactly the repaired wheel",
                ),
                "duplicate identical PyTetWild hash": (
                    declaration("pytetwild", "0.3.0", repaired, repaired),
                    "repeats a SHA-256: pytetwild",
                ),
                "duplicate PyTetWild declaration": (
                    declaration("pytetwild", "0.3.0", repaired)
                    + declaration("pytetwild", "0.3.0", repaired),
                    "Duplicate Application requirements lock requirement: pytetwild",
                ),
                "historical PyTetWild hash": (
                    declaration("pytetwild", "0.3.0", historical),
                    "historical PyTetWild wheel",
                ),
                "wrong PyTetWild version": (
                    declaration("pytetwild", "0.3.1", repaired),
                    "must pin pytetwild==0.3.0",
                ),
                "rebuilt hash duplicated by another package": (
                    declaration("pytetwild", "0.3.0", repaired)
                    + declaration("numpy", "2.5.1", repaired),
                    "hash to other packages",
                ),
            }
            for label, (content, message) in cases.items():
                with self.subTest(case=label):
                    lock.write_text(content, encoding="utf-8", newline="\n")
                    with self.assertRaisesRegex(stage_tool.StageError, message):
                        stage_tool._verify_application_requirements_lock(
                            lock,
                            repaired,
                            historical,
                        )

    def test_release_binding_must_match_the_exact_project_commit_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / "release-inputs" / "pytetwild-0.3.0-cp312-abi3-win_amd64.whl"
            wheel_specification = _pytetwild_wheel(wheel)
            raw_wheel = (
                root
                / "release-inputs"
                / "raw-wheel"
                / "pytetwild-0.3.0-cp312-abi3-win_amd64.whl"
            )
            raw_wheel_specification = _pytetwild_wheel(raw_wheel, repaired=False)
            application_text = (
                "pytetwild==0.3.0 \\\n"
                f"    --hash=sha256:{wheel_specification['sha256']}\n"
            )
            recipe_text = "# controlled rebuild fixture\n"
            requirement_versions = {
                "abi3audit": "0.0.26",
                "build": "1.5.0",
                "cibuildwheel": "3.3.1",
                "cmake": "3.29.6",
                "delvewheel": "1.12.1",
                "nanobind": "2.12.0",
                "ninja": "1.13.0",
                "numpy": "2.5.1",
                "scikit-build-core": "0.12.2",
            }
            build_requirements_text = (
                "\n".join(
                    f"{name}=={version} --hash=sha256:{'a' * 64}"
                    for name, version in requirement_versions.items()
                )
                + "\n"
            )
            source_patch_text = (
                "--- a/pytetwild/_accessor.py\n"
                "+++ b/pytetwild/_accessor.py\n"
                "@@ fixture optional PyVista import @@\n"
            )
            repository = root / "project"
            commit = _new_repository(
                repository,
                {
                    stage_tool.APPLICATION_REQUIREMENTS_LOCK_PATH: application_text,
                    stage_tool.PYTETWILD_BUILD_RECIPE_PATH: recipe_text,
                    stage_tool.PYTETWILD_BUILD_REQUIREMENTS_PATH: (
                        build_requirements_text
                    ),
                    stage_tool.PYTETWILD_SOURCE_PATCH_PATH: source_patch_text,
                },
            )
            committed_copy = root / "release-inputs" / "requirements-build.lock"
            committed_copy.write_bytes(application_text.encode("utf-8"))
            recipe = root / "release-inputs" / "BUILD_PYTETWILD_WINDOWS.ps1"
            recipe.write_text(recipe_text, encoding="utf-8", newline="\n")
            attestation = root / "release-inputs" / "pytetwild-build-attestation.json"
            build_requirements = root / "release-inputs" / "requirements-pytetwild-build.lock"
            build_requirements.write_text(
                build_requirements_text,
                encoding="utf-8",
                newline="\n",
            )
            source_patch = (
                root
                / "release-inputs"
                / "pytetwild-0.3.0-optional-pyvista.patch"
            )
            source_patch.write_text(
                source_patch_text,
                encoding="utf-8",
                newline="\n",
            )

            def bound(path: Path) -> dict[str, str]:
                return {
                    "filename": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            audit_logs = root / "release-inputs" / "audit-logs"
            audit_logs.mkdir(parents=True)
            audit_log_evidence = {}
            for name, filename in stage_tool.PYTETWILD_AUDIT_LOG_FILES.items():
                log = audit_logs / filename
                log.write_text(
                    "command=C:\\ChromaMatterToolchain\\fixture.exe --verify\n"
                    "exit_code=0\n"
                    "--- output ---\n"
                    f"verified {name}\n",
                    encoding="utf-8",
                    newline="\n",
                )
                audit_log_evidence[name] = bound(log)

            lock_environment = {
                "python_version": "3.12.10",
                "pip_version": "25.0.1",
                "cibuildwheel_version": "3.3.1",
                "runner_image": "self-hosted-windows-controlled-offline",
                "compiler": "MSVC 14.44.35211",
                "compiler_family_requested_from_vsdevcmd": "14.44",
                "visual_studio_installation_version": "17.14.37614.0",
                "cmake_version": "3.29.6",
                "ninja_version": "1.13.0",
                "nanobind_version": "2.12.0",
                "build_version": "1.5.0",
                "scikit_build_core_version": "0.12.2",
                "delvewheel_version": "1.12.1",
                "abi3audit_version": "0.0.26",
                "numpy_version": "2.5.1",
                "windows_sdk_version": "10.0.26100.0",
                "windows_sdk_servicing_version": "10.0.26100.7705",
            }
            attestation_data = {
                "schema_version": 1,
                "status": "verified-controlled-rebuild",
                "scope": "prospective-rebuild-only",
                "started_utc": "2026-08-22T00:00:00.0000000Z",
                "finished_utc": "2026-08-22T00:05:00.0000000Z",
                "network_policy": {
                    "operator_confirmed_os_level_isolation": True,
                    "os_level_enforcement_by_script": False,
                    "script_enforcement_scope": (
                        "prebuild-probes-and-child-process-guards-only"
                    ),
                    "pip_no_index": True,
                    "fetchcontent_fully_disconnected": True,
                    "fetchcontent_try_find_package_mode": "NEVER",
                    "git_https_rewritten_to_offline_invalid": True,
                    "process_proxies_rejected_at_loopback_port_9": True,
                    "prebuild_direct_connect_probes": "all-unreachable",
                    "probe_targets": [
                        "github.com:443",
                        "pypi.org:443",
                        "files.pythonhosted.org:443",
                        "conda.anaconda.org:443",
                    ],
                },
                "sources": {
                    "pytetwild_commit": "eea46df87ef58e861956b7a710f42ab58eaa02a0",
                    "pytetwild_optional_pyvista_patch_sha256": bound(source_patch)["sha256"],
                    "pytetwild_patched_accessor_sha256": (
                        "c1bfeb0417cd3109d0ef3ecde6e69e04573571f5050003d330a04c25a5d1030c"
                    ),
                    "ftetwild_commit": "d7d99bb4387a07895b9adce058dc7305f6b6e5ab",
                    "nanobind_commit": "2a61ad2494d09fecb2e13322c1383342c299900d",
                    "fmt_commit": "40626af88bd7df9a5fb80be7b25ac85b122d6c21",
                    "spdlog_commit": "6fa36017cfd5731d617e1a934f0e5ea9c4445b13",
                    "libigl_commit": "40e7900ccbd767f1f360e0eb10f0f1a6432e0993",
                    "predicates_commit": "decb7bc1260e689cbe008109e3cc5d3a5a433aea",
                    "geogram_commit": "fc3eb9bf44d2ee29686592e3ef5f5f4daeda27f8",
                    "geogram_amgcl_commit": "ab57038d68ee372ed5df280631051b91f17ed2d1",
                    "geogram_libmeshb_commit": "952a157c9d516b28cc6c69cd1550c3e48d4792f9",
                    "geogram_rply_commit": "4296cc91b5c8c26d4e7d7aac0cee2b194ffc5800",
                    "onetbb_commit": "06ce6212da6710f4bb2d20a1904b018aa44069bf",
                    "json_commit": "0901d33bf6e7dfe6f70fd9d142c8f5c6695c6c5b",
                    "eigen_archive_sha256": (
                        "8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72"
                    ),
                    "mpir_archive_sha256": (
                        "c7243b2c3f8e849a9367eab8d77babcd8dd5b828d6b5068441297edc86843b69"
                    ),
                },
                "environment": {
                    **lock_environment,
                    "compiler_path": r"C:\ChromaMatterToolchain\VS\cl.exe",
                    "linker_path": r"C:\ChromaMatterToolchain\VS\link.exe",
                    "compiler_file_version": "19.44.35221.0",
                    "signtool_path": r"C:\ChromaMatterToolchain\SDK\signtool.exe",
                    "cmake_cli": "cmake version 3.29.6",
                    "ninja_cli": "1.13.0.git.kitware.jobserver-pipe-1",
                },
                "inputs": {
                    "build_recipe_sha256": bound(recipe)["sha256"],
                    "build_requirements_lock_sha256": bound(build_requirements)[
                        "sha256"
                    ],
                    "source_patch_sha256": bound(source_patch)["sha256"],
                    "python_installer_sha256": (
                        "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
                    ),
                    "portable_git_sha256": (
                        "5aa8a20f6e9abb2c755f0e73c91c687701a46b309ad84a0ca6509380fa4ae290"
                    ),
                    "visual_studio_bootstrapper_sha256": (
                        "236367b68ba9a51708263ab10a1c85546cc4a8eca78b365168811d19c4fb2f29"
                    ),
                    "visual_studio_catalog_sha256": (
                        "3891c3018a07338b3880cbb28088bb22ef7762eb9206523655b2e3972b9d527e"
                    ),
                    "visual_studio_channel_manifest_sha256": (
                        "4c81e902fb7fe2acea779b828e6dc548fe0bbb693df50eda0224263c16686bdd"
                    ),
                    "visual_studio_layout_sha256": (
                        "9707247b5e1c5ffdbd2ec97889db8e16ad97361840427a846e21f697c28ed494"
                    ),
                    "visual_studio_installer_opc_sha256": (
                        "e2c0a268ec9b678169ed5ff9c0162ea135d8868c27e7ac67a754b09d16841b71"
                    ),
                    "visual_studio_layout_file_count": 714,
                    "visual_studio_layout_total_bytes": 2651377645,
                    "visual_studio_layout_tree_sha256": (
                        "2b6a89bb69aa7de013fc055828258a3a91c7c333f0c6be831a750990922fed3a"
                    ),
                    "microsoft_visual_studio_layout_verifier_exit_code": 0,
                    "source_archives": {
                        name: f"{index:x}" * 64
                        for index, name in enumerate(
                            sorted(stage_tool.PYTETWILD_SOURCE_ARCHIVE_FIELDS),
                            start=1,
                        )
                    },
                },
                "output": {
                    **wheel_specification,
                    "raw_wheel_filename": raw_wheel_specification["filename"],
                    "raw_wheel_sha256": raw_wheel_specification["sha256"],
                    "zip_test": "passed",
                    "raw_wheel_record": "passed",
                    "repaired_wheel_record": "passed",
                    "abi3audit_strict": "passed",
                    "raw_delvewheel_show": "passed-no-not-found-markers",
                    "repaired_native_dependency_closure": "passed",
                    "repaired_delvewheel_metadata": "passed",
                    "native_extension_load": "passed",
                    "normal_isolated_package_import": "passed",
                    "vendored_dll_load_order": "passed",
                    "audit_logs": audit_log_evidence,
                },
            }
            attestation.write_text(
                json.dumps(attestation_data, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
            rebuild_lock = root / "release-inputs" / "pytetwild-rebuild-lock.json"
            rebuild_data = {
                "schema_version": 1,
                "lock_status": "verified-controlled-rebuild",
                "scope": "prospective-rebuild-only",
                "historical_wheel": {
                    "sha256": "11964e295a54cf9e2f6920a920aeeba27668c9b14e369a86f72ec5baa4f46060",
                    "nanobind_version_status": "unknown-not-asserted",
                    "release_disposition": "excluded",
                },
                "pytetwild": {
                    "version": "0.3.0",
                    "commit": "eea46df87ef58e861956b7a710f42ab58eaa02a0",
                },
                "ftetwild": {"commit": "d7d99bb4387a07895b9adce058dc7305f6b6e5ab"},
                "wheel": wheel_specification,
                "nanobind": {
                    "version": "2.12.0",
                    "source_url": "https://github.com/wjakob/nanobind.git",
                    "commit": "2a61ad2494d09fecb2e13322c1383342c299900d",
                    "required_paths": ["LICENSE", "CMakeLists.txt"],
                },
                "build_recipe": bound(recipe),
                "build_requirements_lock": bound(build_requirements),
                "source_patch": bound(source_patch),
                "environment": lock_environment,
                "attestation": bound(attestation),
                "release_binding": bound(committed_copy),
            }
            rebuild_lock.write_text(
                json.dumps(rebuild_data, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            arguments = argparse.Namespace(
                pytetwild_rebuild_lock=str(rebuild_lock),
                pytetwild_wheel=str(wheel),
                pytetwild_raw_wheel=str(raw_wheel),
                pytetwild_audit_logs=str(audit_logs),
                pytetwild_build_recipe=str(recipe),
                pytetwild_build_requirements=str(build_requirements),
                pytetwild_source_patch=str(source_patch),
                pytetwild_build_attestation=str(attestation),
                application_requirements_lock=str(committed_copy),
            )

            def write_attestation_fixture(value: dict) -> None:
                attestation.write_text(
                    json.dumps(value, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                rebuild_data["attestation"] = bound(attestation)
                rebuild_lock.write_text(
                    json.dumps(rebuild_data, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )

            component, evidence, files = stage_tool._prepare_pytetwild_rebuild(
                manifest,
                COMPONENT_MANIFEST,
                arguments,
                project_repository=repository,
                project_commit=commit,
            )
            self.assertEqual(
                component["required_gitlinks"],
                [
                    {
                        "path": "ext/robin_map",
                        "url": "https://github.com/Tessil/robin-map.git",
                    }
                ],
            )
            self.assertEqual(
                evidence["bound_evidence"]["release_binding"],
                bound(committed_copy),
            )
            self.assertEqual(
                evidence["bound_evidence"]["source_patch"],
                bound(source_patch),
            )
            self.assertIn(
                (
                    source_patch.resolve(),
                    f"build-evidence/pytetwild/{source_patch.name}",
                ),
                files,
            )
            self.assertEqual(evidence["raw_wheel"], bound(raw_wheel))
            self.assertEqual(evidence["audit_logs"], audit_log_evidence)
            self.assertIn(
                (
                    raw_wheel.resolve(),
                    f"build-evidence/pytetwild/raw-wheel/{raw_wheel.name}",
                ),
                files,
            )
            self.assertIn(
                (
                    wheel.resolve(),
                    f"build-evidence/pytetwild/repaired-wheel/{wheel.name}",
                ),
                files,
            )
            for filename in stage_tool.PYTETWILD_AUDIT_LOG_FILES.values():
                self.assertIn(
                    (
                        (audit_logs / filename).resolve(),
                        f"build-evidence/pytetwild/logs/{filename}",
                    ),
                    files,
                )

            for attribute, option in (
                ("pytetwild_raw_wheel", "--pytetwild-raw-wheel"),
                ("pytetwild_audit_logs", "--pytetwild-audit-logs"),
            ):
                with self.subTest(missing_argument=option):
                    missing_arguments = argparse.Namespace(**vars(arguments))
                    setattr(missing_arguments, attribute, None)
                    with self.assertRaisesRegex(stage_tool.StageError, option):
                        stage_tool._prepare_pytetwild_rebuild(
                            manifest,
                            COMPONENT_MANIFEST,
                            missing_arguments,
                            project_repository=repository,
                            project_commit=commit,
                        )

            attestation_drifts = (
                (
                    "network policy",
                    ("network_policy", "pip_no_index"),
                    False,
                    "network_policy.pip_no_index differs",
                ),
                (
                    "source commit",
                    ("sources", "fmt_commit"),
                    "0" * 40,
                    "sources.fmt_commit differs",
                ),
                (
                    "environment",
                    ("environment", "runner_image"),
                    "windows-2025",
                    "environment.runner_image differs",
                ),
                (
                    "pass flag",
                    ("output", "abi3audit_strict"),
                    False,
                    "output.abi3audit_strict differs",
                ),
            )
            for label, (section, field), value, message in attestation_drifts:
                with self.subTest(attestation_drift=label):
                    changed = copy.deepcopy(attestation_data)
                    changed[section][field] = value
                    write_attestation_fixture(changed)
                    with self.assertRaisesRegex(stage_tool.StageError, message):
                        stage_tool._prepare_pytetwild_rebuild(
                            manifest,
                            COMPONENT_MANIFEST,
                            arguments,
                            project_repository=repository,
                            project_commit=commit,
                        )

            missing_pass = copy.deepcopy(attestation_data)
            missing_pass["output"].pop("zip_test")
            write_attestation_fixture(missing_pass)
            with self.assertRaisesRegex(stage_tool.StageError, r"missing=\['zip_test'\]"):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    arguments,
                    project_repository=repository,
                    project_commit=commit,
                )
            write_attestation_fixture(attestation_data)

            raw_wheel_bytes = raw_wheel.read_bytes()
            raw_wheel.write_bytes(raw_wheel_bytes + b"raw wheel drift")
            with self.assertRaisesRegex(stage_tool.StageError, "raw wheel SHA-256"):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    arguments,
                    project_repository=repository,
                    project_commit=commit,
                )
            raw_wheel.write_bytes(raw_wheel_bytes)

            audit_name = "native_normal_import"
            audit_path = audit_logs / stage_tool.PYTETWILD_AUDIT_LOG_FILES[audit_name]
            audit_bytes = audit_path.read_bytes()
            audit_path.write_bytes(audit_bytes + b"hash drift\n")
            with self.assertRaisesRegex(stage_tool.StageError, "audit log .* SHA-256"):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    arguments,
                    project_repository=repository,
                    project_commit=commit,
                )
            audit_path.write_bytes(audit_bytes)

            missing_path = audit_path.with_suffix(".missing")
            audit_path.rename(missing_path)
            try:
                with self.assertRaisesRegex(stage_tool.StageError, "exactly the eight"):
                    stage_tool._prepare_pytetwild_rebuild(
                        manifest,
                        COMPONENT_MANIFEST,
                        arguments,
                        project_repository=repository,
                        project_commit=commit,
                    )
            finally:
                missing_path.rename(audit_path)

            extra_log = audit_logs / "unexpected.log"
            extra_log.write_text("exit_code=0\n", encoding="utf-8", newline="\n")
            try:
                with self.assertRaisesRegex(stage_tool.StageError, "exactly the eight"):
                    stage_tool._prepare_pytetwild_rebuild(
                        manifest,
                        COMPONENT_MANIFEST,
                        arguments,
                        project_repository=repository,
                        project_commit=commit,
                    )
            finally:
                extra_log.unlink()

            real_link_check = stage_tool._is_link_like
            with mock.patch.object(
                stage_tool,
                "_is_link_like",
                side_effect=lambda path: path == audit_path or real_link_check(path),
            ):
                with self.assertRaisesRegex(stage_tool.StageError, "missing or linked"):
                    stage_tool._prepare_pytetwild_rebuild(
                        manifest,
                        COMPONENT_MANIFEST,
                        arguments,
                        project_repository=repository,
                        project_commit=commit,
                    )

            with mock.patch.object(
                stage_tool,
                "_is_link_like",
                side_effect=lambda path: path == audit_logs or real_link_check(path),
            ):
                with self.assertRaisesRegex(stage_tool.StageError, "real directory"):
                    stage_tool._prepare_pytetwild_rebuild(
                        manifest,
                        COMPONENT_MANIFEST,
                        arguments,
                        project_repository=repository,
                        project_commit=commit,
                    )

            private_log = (
                "command=C:\\Users\\Private Builder\\tool.exe --verify\n"
                "exit_code=0\n"
            ).encode("utf-8")
            audit_path.write_bytes(private_log)
            private_attestation = copy.deepcopy(attestation_data)
            private_attestation["output"]["audit_logs"][audit_name] = bound(audit_path)
            write_attestation_fixture(private_attestation)
            with self.assertRaisesRegex(stage_tool.StageError, "private absolute user path"):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    arguments,
                    project_repository=repository,
                    project_commit=commit,
                )
            audit_path.write_bytes(audit_bytes)
            write_attestation_fixture(attestation_data)

            unc_private_log = (
                "command=\\\\build-server\\Users\\Private Builder\\tool.exe --verify\n"
                "exit_code=0\n"
            ).encode("utf-8")
            audit_path.write_bytes(unc_private_log)
            unc_private_attestation = copy.deepcopy(attestation_data)
            unc_private_attestation["output"]["audit_logs"][audit_name] = bound(
                audit_path
            )
            write_attestation_fixture(unc_private_attestation)
            with self.assertRaisesRegex(stage_tool.StageError, "private absolute user path"):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    arguments,
                    project_repository=repository,
                    project_commit=commit,
                )
            audit_path.write_bytes(audit_bytes)

            json_escaped_unc = copy.deepcopy(attestation_data)
            json_escaped_unc["environment"]["compiler_path"] = (
                r"\\build-server\Users\Private Builder\cl.exe"
            )
            write_attestation_fixture(json_escaped_unc)
            with self.assertRaisesRegex(stage_tool.StageError, "private absolute user path"):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    arguments,
                    project_repository=repository,
                    project_commit=commit,
                )
            write_attestation_fixture(attestation_data)

            missing_patch_arguments = argparse.Namespace(**vars(arguments))
            missing_patch_arguments.pytetwild_source_patch = None
            with self.assertRaisesRegex(
                stage_tool.StageError,
                "--pytetwild-source-patch",
            ):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    missing_patch_arguments,
                    project_repository=repository,
                    project_commit=commit,
                )

            lock_without_patch = copy.deepcopy(rebuild_data)
            lock_without_patch.pop("source_patch")
            rebuild_lock.write_text(
                json.dumps(lock_without_patch, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(stage_tool.StageError, r"missing=\['source_patch'\]"):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    arguments,
                    project_repository=repository,
                    project_commit=commit,
                )
            rebuild_lock.write_text(
                json.dumps(rebuild_data, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            original_patch = source_patch.read_bytes()
            source_patch.write_bytes(original_patch + b"# drift\n")
            with self.assertRaisesRegex(stage_tool.StageError, "source_patch SHA-256"):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    arguments,
                    project_repository=repository,
                    project_commit=commit,
                )
            source_patch.write_bytes(original_patch)

            for section, field in (
                ("inputs", "build_recipe_sha256"),
                ("inputs", "build_requirements_lock_sha256"),
                ("inputs", "source_patch_sha256"),
                ("sources", "pytetwild_optional_pyvista_patch_sha256"),
            ):
                with self.subTest(attestation_drift=f"{section}.{field}"):
                    changed_attestation = copy.deepcopy(attestation_data)
                    changed_attestation[section][field] = "0" * 64
                    attestation.write_text(
                        json.dumps(changed_attestation, indent=2) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    rebuild_data["attestation"] = bound(attestation)
                    rebuild_lock.write_text(
                        json.dumps(rebuild_data, indent=2) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    with self.assertRaisesRegex(
                        stage_tool.StageError,
                        "attestation .* differs",
                    ):
                        stage_tool._prepare_pytetwild_rebuild(
                            manifest,
                            COMPONENT_MANIFEST,
                            arguments,
                            project_repository=repository,
                            project_commit=commit,
                        )

            attestation.write_text(
                json.dumps(attestation_data, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            rebuild_data["attestation"] = bound(attestation)

            static_input_drifts = (
                (
                    "build_recipe",
                    recipe,
                    ("inputs", "build_recipe_sha256"),
                    None,
                    "PyTetWild build recipe",
                ),
                (
                    "build_requirements_lock",
                    build_requirements,
                    ("inputs", "build_requirements_lock_sha256"),
                    None,
                    "PyTetWild build requirements lock",
                ),
                (
                    "source_patch",
                    source_patch,
                    ("inputs", "source_patch_sha256"),
                    ("sources", "pytetwild_optional_pyvista_patch_sha256"),
                    "PyTetWild source patch",
                ),
            )
            for lock_key, path, primary_field, secondary_field, label in static_input_drifts:
                with self.subTest(uncommitted_static_input=lock_key):
                    original = path.read_bytes()
                    path.write_bytes(original + b"# working-tree-only drift\n")
                    changed_attestation = copy.deepcopy(attestation_data)
                    changed_hash = bound(path)["sha256"]
                    changed_attestation[primary_field[0]][primary_field[1]] = changed_hash
                    if secondary_field is not None:
                        changed_attestation[secondary_field[0]][secondary_field[1]] = (
                            changed_hash
                        )
                    rebuild_data[lock_key] = bound(path)
                    write_attestation_fixture(changed_attestation)
                    with self.assertRaisesRegex(
                        stage_tool.StageError,
                        f"{label} does not byte-match the exact project commit",
                    ):
                        stage_tool._prepare_pytetwild_rebuild(
                            manifest,
                            COMPONENT_MANIFEST,
                            arguments,
                            project_repository=repository,
                            project_commit=commit,
                        )
                    path.write_bytes(original)
                    rebuild_data[lock_key] = bound(path)
                    write_attestation_fixture(attestation_data)

            committed_copy.write_text(
                application_text + "# uncommitted release-binding drift\n",
                encoding="utf-8",
                newline="\n",
            )
            rebuild_data["release_binding"] = bound(committed_copy)
            rebuild_lock.write_text(
                json.dumps(rebuild_data, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(stage_tool.StageError, "exact project commit"):
                stage_tool._prepare_pytetwild_rebuild(
                    manifest,
                    COMPONENT_MANIFEST,
                    arguments,
                    project_repository=repository,
                    project_commit=commit,
                )

    def test_powershell_wrapper_keeps_destination_cache_and_commit_explicit(self) -> None:
        text = POWERSHELL_WRAPPER.read_text(encoding="utf-8")
        for parameter in ("$Destination", "$Cache", "$ProjectRepository", "$ProjectCommit"):
            with self.subTest(parameter=parameter):
                self.assertIn("[Parameter(Mandatory = $true)]", text)
                self.assertIn(parameter, text)
        self.assertIn("--external-archive-lock", text)
        self.assertIn("--pytetwild-rebuild-lock", text)
        self.assertIn("$PyTetWildSourcePatch", text)
        self.assertIn("--pytetwild-source-patch", text)
        self.assertIn("$PyTetWildRawWheel", text)
        self.assertIn("--pytetwild-raw-wheel", text)
        self.assertIn("$PyTetWildAuditLogs", text)
        self.assertIn("--pytetwild-audit-logs", text)
        self.assertIn("--application-requirements-lock", text)
        self.assertIn("--validate-manifest-only", text)
        parsed = stage_tool._parser().parse_args(
            ["--pytetwild-source-patch", "optional-pyvista.patch"]
        )
        self.assertEqual(parsed.pytetwild_source_patch, "optional-pyvista.patch")
        parsed = stage_tool._parser().parse_args(
            [
                "--pytetwild-raw-wheel",
                "raw.whl",
                "--pytetwild-audit-logs",
                "audit-logs",
            ]
        )
        self.assertEqual(parsed.pytetwild_raw_wheel, "raw.whl")
        self.assertEqual(parsed.pytetwild_audit_logs, "audit-logs")


class CorrespondingSourceFixtureTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path, str, Path]:
        fixture_root = root / "fixture-inputs"
        source_archive = fixture_root / "archives" / "source-component"
        source_payload = _zip(source_archive)
        external_archive = fixture_root / "archives" / "external.zip"
        external_payload = _zip(external_archive, "external/source.txt")
        legacy_archive = fixture_root / "archives" / "legacy_link"
        legacy_payload = _zip(legacy_archive, "legacy/source.txt")
        legacy_md5 = hashlib.md5(legacy_payload).hexdigest()

        child = fixture_root / "git" / "child"
        child_commit = _new_repository(child, {"LICENSE": "child license\n"})

        parent = fixture_root / "git" / "parent"
        parent_commit = _new_repository(
            parent,
            {
                ".gitattributes": "pins.txt export-ignore\n",
                "LICENSE": "parent license\n",
                "pins.txt": "dependency-pin\n",
                "src/external/example.cmake": (
                    "set(EXTERNAL_LINK https://github.com/example/external.zip)\n"
                    "# set(EXTERNAL_MD5 00000000000000000000000000000000)\n"
                    "set(LEGACY_LINK https://github.com/example/legacy.zip)\n"
                    f"set(LEGACY_MD5 {legacy_md5})\n"
                ),
            },
        )
        (parent / ".gitmodules").write_text(
            '[submodule "dependency"]\n'
            "\tpath = deps/child\n"
            "\turl = https://github.com/example/child.git\n",
            encoding="utf-8",
            newline="\n",
        )
        _git(parent, "add", ".gitmodules")
        _git(
            parent,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{child_commit},deps/child",
        )
        _git(parent, "commit", "-m", "pin child gitlink")
        parent_commit = _git(parent, "rev-parse", "HEAD")

        project = root / "project-repository"
        project_commit = _new_repository(project, {"tracked.txt": "tracked source\n"})
        (project / "untracked-private.txt").write_text(
            "C:" + "\\" + "Users" + "\\" + "private" + "\\" + "secret\n",
            encoding="utf-8",
        )

        manifest = {
            "schema_version": 1,
            "bundle_id": "fixture-corresponding-source",
            "bundle_status": "candidate-only-not-release-approved",
            "release_approval": {
                "status": "release-approved",
                "requires_all_known_gaps_resolved": True,
                "required_gap_ids": ["fixture-md5-only-external-archives"],
            },
            "known_gaps": [
                {
                    "id": "fixture-md5-only-external-archives",
                    "status": "unresolved",
                    "reason": "The legacy fixture archive has only an upstream MD5.",
                    "resolution_evidence": {
                        "kind": "complete-dynamic-archive-sha256-lock",
                        "rule_id": "external-inputs",
                    },
                }
            ],
            "project": {
                "id": "project",
                "display_name": "Fixture Project",
                "public_url": "https://github.com/example/project.git",
                "destination": "components/project",
            },
            "allowed_redirect_host_suffixes": ["github.com"],
            "components": [
                {
                    "id": "parent",
                    "display_name": "Parent",
                    "version": parent_commit,
                    "kind": "git",
                    "url": "https://github.com/example/parent.git",
                    "commit": parent_commit,
                    "destination": "components/parent",
                    "required_paths": ["LICENSE", "pins.txt"],
                },
                {
                    "id": "child",
                    "display_name": "Child",
                    "version": child_commit,
                    "kind": "git",
                    "url": "https://github.com/example/child.git",
                    "commit": child_commit,
                    "destination": "components/parent/deps/child",
                    "required_paths": ["LICENSE"],
                },
                {
                    "id": "source-archive",
                    "display_name": "Source archive",
                    "version": "1",
                    "kind": "archive",
                    "urls": ["https://github.com/example/source.zip"],
                    "sha256": hashlib.sha256(source_payload).hexdigest(),
                    "destination": "components/source/source.zip",
                    "stage_mode": "preserve",
                    "validate_archive_members": True,
                    "fixture_file": "archives/source-component",
                },
            ],
            "submodule_relations": [
                {"parent": "parent", "path": "deps/child", "child": "child"}
            ],
            "pin_evidence": [
                {
                    "component": "parent",
                    "path": "pins.txt",
                    "required_literals": ["dependency-pin"],
                }
            ],
            "dynamic_archive_rules": [
                {
                    "id": "external-inputs",
                    "component": "parent",
                    "source_glob": "src/external/*.cmake",
                    "link_variable_suffix": "_LINK",
                    "md5_variable_suffix": "_MD5",
                    "destination": "components/parent/external-archives",
                    "known_unhashed_variables": ["EXTERNAL_LINK"],
                    "excluded_variables": {},
                    "require_sha256_lock_for_unhashed": True,
                    "require_release_asset_provenance": True,
                    "validate_archive_members": True,
                }
            ],
        }
        manifest_path = root / "fixture-components.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        lock = {
            "schema_version": 1,
            "lock_status": "verified-official-release-assets",
            "meshlab_commit": parent_commit,
            "archives": [
                {
                    "variable": "EXTERNAL_LINK",
                    "url": "https://github.com/example/external.zip",
                    "sha256": hashlib.sha256(external_payload).hexdigest(),
                    "byte_size": len(external_payload),
                    "fixture_file": "archives/external.zip",
                    "provenance": _release_provenance("external.zip", 1001),
                }
            ],
        }
        lock_path = root / "external-lock.json"
        lock_path.write_text(
            json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return manifest_path, fixture_root, project, project_commit, lock_path

    def _run(
        self,
        manifest: Path,
        fixture_root: Path,
        project: Path,
        project_commit: str,
        destination: Path,
        cache: Path,
        lock: Path | None,
    ) -> int:
        arguments = [
            "--manifest",
            str(manifest),
            "--destination",
            str(destination),
            "--cache",
            str(cache),
            "--project-repository",
            str(project),
            "--project-commit",
            project_commit,
            "--fixture-root",
            str(fixture_root),
            "--offline",
        ]
        if lock is not None:
            arguments.extend(("--external-archive-lock", str(lock)))
        return stage_tool.main(arguments)

    def test_required_implicit_gitlinks_are_verified_and_recursively_staged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture_root = root / "fixture-inputs"

            leaf = fixture_root / "git" / "parent-deps-child-ext-robin_map"
            leaf_commit = _new_repository(leaf, {"LICENSE": "leaf license\n"})

            child = fixture_root / "git" / "parent-deps-child"
            child_commit = _new_repository(child, {"LICENSE": "child license\n"})
            (child / ".gitmodules").write_text(
                '[submodule "robin_map"]\n'
                "\tpath = ext/robin_map\n"
                "\turl = https://github.com/Tessil/robin-map.git\n",
                encoding="utf-8",
                newline="\n",
            )
            _git(child, "add", ".gitmodules")
            _git(
                child,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{leaf_commit},ext/robin_map",
            )
            _git(child, "commit", "-m", "pin recursive implicit gitlink")
            child_commit = _git(child, "rev-parse", "HEAD")

            parent = fixture_root / "git" / "parent"
            parent_commit = _new_repository(parent, {"LICENSE": "parent license\n"})
            (parent / ".gitmodules").write_text(
                '[submodule "child"]\n'
                "\tpath = deps/child\n"
                "\turl = https://github.com/example/child.git\n",
                encoding="utf-8",
                newline="\n",
            )
            _git(parent, "add", ".gitmodules")
            _git(
                parent,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{child_commit},deps/child",
            )
            _git(parent, "commit", "-m", "pin required implicit gitlink")
            parent_commit = _git(parent, "rev-parse", "HEAD")

            component = {
                "id": "parent",
                "display_name": "Parent",
                "version": parent_commit,
                "kind": "git",
                "url": "https://github.com/example/parent.git",
                "commit": parent_commit,
                "destination": "components/parent",
                "required_paths": ["LICENSE"],
                "required_gitlinks": [
                    {
                        "path": "deps/child",
                        "url": "https://github.com/example/child.git",
                        "commit": child_commit,
                    }
                ],
            }
            stage_tool._component_map({"components": [component]})
            manifest = {
                "known_gaps": [],
                "submodule_relations": [],
                "allowed_redirect_host_suffixes": ["github.com"],
            }
            cache = root / "cache"
            cache.mkdir()
            stage_root = root / "stage"
            stage_root.mkdir()
            stager = stage_tool._Stager(
                manifest,
                {"parent": component},
                stage_root,
                cache,
                parent,
                parent_commit,
                external_lock_path=None,
                offline=True,
                fixture_root=fixture_root,
            )

            stager._stage_git_component(component)

            self.assertTrue(
                (stage_root / "components/parent/deps/child/LICENSE").is_file()
            )
            self.assertTrue(
                (
                    stage_root
                    / "components/parent/deps/child/ext/robin_map/LICENSE"
                ).is_file()
            )
            implicit = {
                record["destination"]: record["discovery"]
                for record in stager.records
                if "discovery" in record
            }
            self.assertEqual(
                implicit,
                {
                    "components/parent/deps/child": {
                        "parent_component": "parent",
                        "submodule_path": "deps/child",
                    },
                    "components/parent/deps/child/ext/robin_map": {
                        "parent_component": "parent-deps-child",
                        "submodule_path": "ext/robin_map",
                    },
                },
            )

            drifted = dict(component)
            drifted["required_gitlinks"] = [
                dict(component["required_gitlinks"][0], commit="0" * 40)
            ]
            drift_stage = root / "drift-stage"
            drift_stage.mkdir()
            drift_stager = stage_tool._Stager(
                manifest,
                {"parent": drifted},
                drift_stage,
                cache,
                parent,
                parent_commit,
                external_lock_path=None,
                offline=True,
                fixture_root=fixture_root,
            )
            with self.assertRaisesRegex(stage_tool.StageError, "commit drift"):
                drift_stager._stage_git_component(drifted)

    def test_missing_external_sha256_lock_fails_before_bundle_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, fixture_root, project, project_commit, _lock = self._fixture(root)
            destination = root / "out" / "bundle"
            result = self._run(
                manifest,
                fixture_root,
                project,
                project_commit,
                destination,
                root / "cache",
                None,
            )
            self.assertEqual(result, 2)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(f"{destination}.zip").exists())

    def test_fixture_stage_is_recursive_private_path_free_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, fixture_root, project, project_commit, lock = self._fixture(root)
            archives: list[Path] = []
            for name in ("out-a", "out-b"):
                destination = root / name / "bundle"
                result = self._run(
                    manifest,
                    fixture_root,
                    project,
                    project_commit,
                    destination,
                    root / "cache",
                    lock,
                )
                self.assertEqual(result, 0)
                self.assertTrue((destination / "components/parent/deps/child/LICENSE").is_file())
                self.assertTrue((destination / "components/project/tracked.txt").is_file())
                self.assertFalse(
                    (destination / "components/project/untracked-private.txt").exists()
                )
                self.assertTrue(
                    (
                        destination
                        / "components/parent/external-archives/external_link.zip"
                    ).is_file()
                )
                provenance_text = (destination / "COMPONENT_SOURCES.json").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn(str(root), provenance_text)
                provenance = json.loads(provenance_text)
                self.assertEqual(
                    provenance["bundle_status"],
                    "candidate-only-not-release-approved",
                )
                self.assertEqual(
                    [gap["id"] for gap in provenance["known_gaps"]],
                    ["fixture-md5-only-external-archives"],
                )
                self.assertNotIn("resolved_constraints", provenance)
                manifest_lines = (destination / "SOURCE_MANIFEST_SHA256.txt").read_text(
                    encoding="utf-8"
                ).splitlines()
                self.assertTrue(manifest_lines)
                self.assertTrue(all("  components/" in line or "  COMPONENT_" in line for line in manifest_lines))
                archives.append(Path(f"{destination}.zip"))
            self.assertEqual(
                hashlib.sha256(archives[0].read_bytes()).hexdigest(),
                hashlib.sha256(archives[1].read_bytes()).hexdigest(),
            )

    def test_complete_dynamic_sha256_lock_transitions_to_release_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, fixture_root, project, project_commit, candidate_lock = self._fixture(
                root
            )
            final_lock_data = json.loads(candidate_lock.read_text(encoding="utf-8"))
            legacy_payload = (fixture_root / "archives" / "legacy_link").read_bytes()
            final_lock_data["archives"].append(
                {
                    "variable": "LEGACY_LINK",
                    "url": "https://github.com/example/legacy.zip",
                    "sha256": hashlib.sha256(legacy_payload).hexdigest(),
                    "byte_size": len(legacy_payload),
                    "fixture_file": "archives/legacy_link",
                    "provenance": _release_provenance("legacy.zip", 1002),
                }
            )
            final_lock = root / "final-external-lock.json"
            final_lock.write_text(
                json.dumps(final_lock_data, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            destination = root / "out" / "bundle"
            result = self._run(
                manifest,
                fixture_root,
                project,
                project_commit,
                destination,
                root / "cache",
                final_lock,
            )
            self.assertEqual(result, 0)
            provenance = json.loads(
                (destination / "COMPONENT_SOURCES.json").read_text(encoding="utf-8")
            )
            self.assertEqual(provenance["bundle_status"], "release-approved")
            self.assertEqual(provenance["known_gaps"], [])
            self.assertEqual(
                provenance["resolved_constraints"],
                [
                    {
                        "archive_count": 2,
                        "external_archive_lock_sha256": hashlib.sha256(
                            final_lock.read_bytes()
                        ).hexdigest(),
                        "id": "fixture-md5-only-external-archives",
                        "locked_variables": ["EXTERNAL_LINK", "LEGACY_LINK"],
                        "resolution": "verified-complete-dynamic-archive-sha256-lock",
                        "rule_id": "external-inputs",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
