from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
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
            manifest["default_external_archive_lock"],
            EXTERNAL_LOCK.name,
        )
        external = stage_tool._load_external_lock(
            EXTERNAL_LOCK,
            components["meshlab-d876376"]["commit"],
            require_release_provenance=True,
        )
        self.assertEqual(
            external["EMBREE_WIN_LINK"]["sha256"],
            "d4c07f88df9f009dd84e4e9b9dcec32ad7d96f927bd88de00b721b0923d481a9",
        )
        self.assertEqual(
            external["TBB_WIN_LINK"]["sha256"],
            "8e2b48500fe93ab77bad435eea7ed9c513eacb032ee6a90e086d99b7f96bd8d5",
        )
        stage_tool._validate_blocked_rebuild_template(
            REBUILD_TEMPLATE,
            components["pytetwild-0.3.0"]["commit"],
        )

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

    def test_powershell_wrapper_keeps_destination_cache_and_commit_explicit(self) -> None:
        text = POWERSHELL_WRAPPER.read_text(encoding="utf-8")
        for parameter in ("$Destination", "$Cache", "$ProjectRepository", "$ProjectCommit"):
            with self.subTest(parameter=parameter):
                self.assertIn("[Parameter(Mandatory = $true)]", text)
                self.assertIn(parameter, text)
        self.assertIn("--external-archive-lock", text)
        self.assertIn("--pytetwild-rebuild-lock", text)
        self.assertIn("--application-requirements-lock", text)
        self.assertIn("--validate-manifest-only", text)


class CorrespondingSourceFixtureTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path, str, Path]:
        fixture_root = root / "fixture-inputs"
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

        source_archive = fixture_root / "archives" / "source-component"
        source_payload = _zip(source_archive)
        external_archive = fixture_root / "archives" / "external.zip"
        external_payload = _zip(external_archive, "external/source.txt")

        manifest = {
            "schema_version": 1,
            "bundle_id": "fixture-corresponding-source",
            "bundle_status": "candidate-only-not-release-approved",
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
            "meshlab_commit": parent_commit,
            "archives": [
                {
                    "variable": "EXTERNAL_LINK",
                    "url": "https://github.com/example/external.zip",
                    "sha256": hashlib.sha256(external_payload).hexdigest(),
                    "fixture_file": "archives/external.zip",
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


if __name__ == "__main__":
    unittest.main()
