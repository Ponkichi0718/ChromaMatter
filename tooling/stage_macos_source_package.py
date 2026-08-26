#!/usr/bin/env python3
"""Stage and audit the manifest-locked macOS source-app alpha2 package.

The Finder app remains source-backed and binary-free.  The comparatively large
rights-cleared DemoData payload is supplied out-of-tree from the immutable
v0.8beta-r32.2 Windows Release, verified against the canonical Git-tracked
manifest, and placed beside (never inside) the app bundle.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile

try:  # Package import in tests; direct import when executed as a script.
    from . import stage_macos_source_app as source_app
except ImportError:  # pragma: no cover - exercised by the command-line path
    import stage_macos_source_app as source_app  # type: ignore[no-redef]


SCHEMA = "chromamatter.macos-source-backed-package.v1"
PACKAGE_NAME = "ChromaMatter-0.8beta-macos-source-app-alpha2"
PACKAGE_MANIFEST_NAME = "SOURCE_APP_PACKAGE_MANIFEST.json"
PACKAGE_CHECKSUM_NAME = "SOFTWARE_PACKAGE_SHA256.txt"
APP_NAME = source_app.APP_NAME
INSTALL_GUIDE_NAME = "README_INSTALL_AND_TEST_EN.md"
SOURCE_COMMIT_NAME = "SOURCE_COMMIT.txt"
SOURCE_NOTICE_NAME = source_app.NOTICE_NAME
PUBLIC_TEST_NAME = "ChromaMatter-Public-Four-Color-Test.glb"
PUBLIC_TEST_CHECKSUM_NAME = PUBLIC_TEST_NAME + ".sha256"
PUBLIC_TEST_BYTES = 1524
PUBLIC_TEST_SHA256 = (
    "1b6092448e62a93f5e29a9c6dda1265a7a2179c2eacd293f7d8f02d1f268c563"
)

STABLE_RELEASE_TAG = "v0.8beta-r32.2"
STABLE_ARCHIVE_NAME = "ChromaMatter-0.8beta-r32.2-win64.zip"
STABLE_ARCHIVE_BYTES = 327_268_369
STABLE_ARCHIVE_SHA256 = (
    "2ceada98661bac5d49b759542151c4c484fff4269d6b5d142ec32fec544f06d0"
)
STABLE_ARCHIVE_URL = (
    "https://github.com/Ponkichi0718/ChromaMatter/releases/download/"
    f"{STABLE_RELEASE_TAG}/{STABLE_ARCHIVE_NAME}"
)
STABLE_ARCHIVE_ROOT = "ChromaMatter-0.8beta-r32.2-win64"
STABLE_DEMO_PREFIX = f"{STABLE_ARCHIVE_ROOT}/DemoData"

GUIDE_SOURCE_PATH = "publication/MACOS_SOURCE_APP_TESTING_EN.md"
DEMO_SOURCE_PREFIX = "source/fixed_app/public_binary/DemoData"
DEMO_MANIFEST_NAME = "DEMO_DATA_MANIFEST.json"
DEMO_MANIFEST_PATH = f"{DEMO_SOURCE_PREFIX}/{DEMO_MANIFEST_NAME}"
DEMO_DOCUMENT_ID = "chromamatter.demo-data.r32.2"
DEMO_PAYLOAD_COUNT = 10
DEMO_PAYLOAD_BYTES = 236_274_418
DEMO_3MF_COUNT = 7
DEMO_DOCUMENTS = (
    "README_EN.md",
    "README_JA.md",
    "NOTICE_EN.md",
    "NOTICE_JA.md",
)
DEMO_CANONICAL_FILE_SHA256 = {
    DEMO_MANIFEST_NAME: (
        "8b36409e9c8cf73da239b4d995077d4b9e771b56926da8cbe8bcd0960d5261de"
    ),
    "README_EN.md": (
        "bdbb806b65da892010ad67002fbedf0eacf23dfb9f0516f647d758972a9dc894"
    ),
    "README_JA.md": (
        "a19b1eb2e70b2d548d80849541f3222818b77170fb61af9fcbeda49330bda8a0"
    ),
    "NOTICE_EN.md": (
        "03612dd0f1421e1f5c170be3008592b05af0dc3385fc0156322665bd50f8f7b8"
    ),
    "NOTICE_JA.md": (
        "7131fef7327b25d767f62df10a8ae2b4de4d5bd3e8d4c7a81b653fb9bd8fd6cb"
    ),
}

EXPECTED_PUBLICATION_GATE = {
    "status": "approved-for-publication",
    "raw_glb_redistribution_confirmed": True,
    "reference_image_redistribution_confirmed": True,
    "derived_3mf_redistribution_confirmed": True,
    "hi3d_plan_terms_confirmed": True,
}

EXPECTED_DEMO_PAYLOADS = (
    (
        "Original AI model Color.glb",
        141_530_440,
        "1bff30d3210cd13e233d4f4a5b9ed895858f0ab524fd8fc06124a4cbd27298aa",
        "model/gltf-binary",
        "multipart-glb-demo",
    ),
    (
        "Reference.jpg",
        2_081_096,
        "71d6bf8534abcec9922d14a3768554636999837540af068d4d42c0cdbd12732b",
        "image/jpeg",
        "reference-image",
    ),
    (
        "3MF/Original AI model Color_FullSpectrum.3mf",
        45_591_194,
        "76c783191e2b5d6c39977816090f6e4d45d7094ca799098439b400f683c55e8f",
        "model/3mf",
        "combined-full-spectrum-3mf-demo",
    ),
    (
        "3MF/Original AI model Color_FullSpectrum_parts_2/"
        "01_RightArm_FullSpectrum.3mf",
        13_408_178,
        "8a2a0ead1e42c6f0ecc1bac0603a14e0d634725b03830581893c8b2e8fcc77ff",
        "model/3mf",
        "individual-part-3mf-demo",
    ),
    (
        "3MF/Original AI model Color_FullSpectrum_parts_2/"
        "02_LeftLeg_FullSpectrum.3mf",
        5_458_207,
        "4f20d63986a4cb6887ebf8de8fa06df64bbaa860e6151af9e227cd0dc49e8bdd",
        "model/3mf",
        "individual-part-3mf-demo",
    ),
    (
        "3MF/Original AI model Color_FullSpectrum_parts_2/"
        "03_Head_FullSpectrum.3mf",
        918_803,
        "30aa9acaf158e17b21358a86edec3fd57be265b76eb5f9aee10acf6f2072896f",
        "model/3mf",
        "individual-part-3mf-demo",
    ),
    (
        "3MF/Original AI model Color_FullSpectrum_parts_2/"
        "04_LeftArm_FullSpectrum.3mf",
        13_586_172,
        "f1bd49bd8ed9512f246d8ebba7bb7532b04ff09522605abe16c3885b49ecc636",
        "model/3mf",
        "individual-part-3mf-demo",
    ),
    (
        "3MF/Original AI model Color_FullSpectrum_parts_2/"
        "05_Torso_FullSpectrum.3mf",
        8_170_540,
        "9c1b08b7c870a31abf24b9c664473aef32cf76cca0c6fd1ed4aed94001e95833",
        "model/3mf",
        "individual-part-3mf-demo",
    ),
    (
        "3MF/Original AI model Color_FullSpectrum_parts_2/"
        "06_RightLeg_FullSpectrum.3mf",
        5_514_149,
        "f8f1946d6a33f4813370064c384abd9cfdf3516fb019ef87a2f532f009541ee8",
        "model/3mf",
        "individual-part-3mf-demo",
    ),
    (
        "3MF/Original AI model Color_FullSpectrum_parts_2/"
        "\u30d1\u30fc\u30c4\u52253MF_manifest.json",
        15_639,
        "c6bc21c225ac69e3d5df2c2de1a45457aa225d49d87527cd3cf4282d7da59d7c",
        "application/json",
        "individual-part-3mf-manifest",
    ),
)


class SourcePackageError(RuntimeError):
    """A fail-closed source-app outer-package staging or audit error."""


@dataclass(frozen=True)
class DemoPayload:
    path: str
    bytes: int
    sha256: str
    media_type: str
    role: str


@dataclass(frozen=True)
class DemoContract:
    manifest_bytes: bytes
    documents: dict[str, bytes]
    payloads: tuple[DemoPayload, ...]

    @property
    def payload_bytes(self) -> int:
        return sum(item.bytes for item in self.payloads)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    candidate = PurePosixPath(value)
    if (
        not value
        or candidate.is_absolute()
        or "\\" in value
        or any(unicodedata.category(character) == "Cc" for character in value)
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise SourcePackageError(f"Unsafe package path: {value!r}")
    return candidate


def _normalized_path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _git_output(repository: Path, arguments: list[str]) -> bytes:
    completed = subprocess.run(
        ["git", "-C", os.fspath(repository), *arguments],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SourcePackageError(f"Git source query failed: {detail}")
    return completed.stdout


def _git_head(repository: Path) -> str:
    try:
        value = _git_output(
            repository, ["rev-parse", "--verify", "HEAD^{commit}"]
        ).decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SourcePackageError("Git returned a non-ASCII HEAD object ID") from exc
    if len(value) != 40:
        raise SourcePackageError("Git HEAD is not an exact commit ID")
    return value.casefold()


def _git_blob(repository: Path, source_commit: str, relative: str) -> bytes:
    _safe_relative(relative)
    return _git_output(repository, ["show", f"{source_commit}:{relative}"])


def _validate_source_commit(repository: Path, source_commit: str) -> str:
    repository = repository.resolve()
    if not repository.is_dir() or not (repository / ".git").exists():
        raise SourcePackageError("Repository root must be an existing Git worktree")
    if len(source_commit) != 40:
        raise SourcePackageError("Source commit must be an exact 40-character ID")
    try:
        int(source_commit, 16)
    except ValueError as exc:
        raise SourcePackageError("Source commit must be hexadecimal") from exc
    source_commit = source_commit.casefold()
    head = _git_head(repository)
    if source_commit != head:
        raise SourcePackageError(
            "Source commit must equal repository HEAD: "
            f"requested={source_commit}, HEAD={head}"
        )
    return source_commit


def _load_demo_contract(repository: Path, source_commit: str) -> DemoContract:
    manifest_bytes = _git_blob(repository, source_commit, DEMO_MANIFEST_PATH)
    if _sha256_bytes(manifest_bytes) != DEMO_CANONICAL_FILE_SHA256[DEMO_MANIFEST_NAME]:
        raise SourcePackageError(
            "Canonical DemoData manifest does not match stable r32.2"
        )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourcePackageError("Canonical DemoData manifest is invalid") from exc

    if (
        manifest.get("schema_version") != 2
        or manifest.get("document_id") != DEMO_DOCUMENT_ID
        or manifest.get("release_status") != "approved-for-publication"
        or manifest.get("expected_documents") != list(DEMO_DOCUMENTS)
        or manifest.get("publication_gate") != EXPECTED_PUBLICATION_GATE
    ):
        raise SourcePackageError("Canonical DemoData publication contract is invalid")

    raw_payloads = manifest.get("payloads")
    if not isinstance(raw_payloads, list):
        raise SourcePackageError("Canonical DemoData payload list is invalid")
    payloads: list[DemoPayload] = []
    for raw in raw_payloads:
        if not isinstance(raw, dict) or set(raw) != {
            "path",
            "bytes",
            "sha256",
            "media_type",
            "role",
        }:
            raise SourcePackageError("Canonical DemoData payload record is invalid")
        path = raw.get("path")
        size = raw.get("bytes")
        sha256 = raw.get("sha256")
        media_type = raw.get("media_type")
        role = raw.get("role")
        if (
            not isinstance(path, str)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or sha256 != sha256.casefold()
            or not isinstance(media_type, str)
            or not isinstance(role, str)
        ):
            raise SourcePackageError("Canonical DemoData payload fields are invalid")
        _safe_relative(path)
        payloads.append(DemoPayload(path, size, sha256, media_type, role))

    expected = tuple(DemoPayload(*item) for item in EXPECTED_DEMO_PAYLOADS)
    if tuple(payloads) != expected:
        raise SourcePackageError(
            "Canonical DemoData payloads differ from stable r32.2"
        )
    if (
        len(payloads) != DEMO_PAYLOAD_COUNT
        or sum(item.bytes for item in payloads) != DEMO_PAYLOAD_BYTES
        or sum(item.path.casefold().endswith(".3mf") for item in payloads)
        != DEMO_3MF_COUNT
    ):
        raise SourcePackageError("Canonical DemoData totals are invalid")

    documents: dict[str, bytes] = {}
    for name in DEMO_DOCUMENTS:
        data = _git_blob(repository, source_commit, f"{DEMO_SOURCE_PREFIX}/{name}")
        if _sha256_bytes(data) != DEMO_CANONICAL_FILE_SHA256[name]:
            raise SourcePackageError(
                f"Canonical DemoData document differs from stable r32.2: {name}"
            )
        documents[name] = data
    return DemoContract(manifest_bytes, documents, tuple(payloads))


def _expected_demo_files(contract: DemoContract) -> set[str]:
    return {
        DEMO_MANIFEST_NAME,
        *contract.documents,
        *(payload.path for payload in contract.payloads),
    }


def _expected_directories(files: set[str]) -> set[str]:
    directories: set[str] = set()
    for relative in files:
        pure = _safe_relative(relative)
        for index in range(1, len(pure.parts)):
            directories.add(PurePosixPath(*pure.parts[:index]).as_posix())
    return directories


def _inspect_exact_tree(root: Path, expected_files: set[str]) -> None:
    if root.is_symlink() or not root.is_dir():
        raise SourcePackageError(f"Expected a normal directory: {root}")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    folded: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        _safe_relative(relative)
        previous = folded.setdefault(_normalized_path_key(relative), relative)
        if previous != relative:
            raise SourcePackageError(
                f"Case-colliding package paths are forbidden: {previous}, {relative}"
            )
        if path.is_symlink():
            raise SourcePackageError(f"Symlink is forbidden: {relative}")
        if path.is_dir():
            actual_directories.add(relative)
        elif path.is_file():
            actual_files.add(relative)
        else:
            raise SourcePackageError(f"Special file is forbidden: {relative}")
    expected_directories = _expected_directories(expected_files)
    if actual_files != expected_files or actual_directories != expected_directories:
        raise SourcePackageError(
            "DemoData allowlist mismatch: "
            f"missing_files={sorted(expected_files - actual_files)}, "
            f"extra_files={sorted(actual_files - expected_files)}, "
            f"missing_directories={sorted(expected_directories - actual_directories)}, "
            f"extra_directories={sorted(actual_directories - expected_directories)}"
        )


def _validate_demo_data(root: Path, contract: DemoContract) -> None:
    expected_files = _expected_demo_files(contract)
    if len(expected_files) != len(contract.payloads) + len(contract.documents) + 1:
        raise SourcePackageError("DemoData contract contains duplicate paths")
    _inspect_exact_tree(root, expected_files)
    if (root / DEMO_MANIFEST_NAME).read_bytes() != contract.manifest_bytes:
        raise SourcePackageError("DemoData manifest bytes do not match canonical Git data")
    for name, data in contract.documents.items():
        if (root / name).read_bytes() != data:
            raise SourcePackageError(
                f"DemoData document bytes do not match canonical Git data: {name}"
            )
    for payload in contract.payloads:
        path = root.joinpath(*PurePosixPath(payload.path).parts)
        if path.stat().st_size != payload.bytes or _sha256(path) != payload.sha256:
            raise SourcePackageError(f"DemoData payload mismatch: {payload.path}")


def _package_records(package_root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    folded: dict[str, str] = {}
    for path in sorted(package_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(package_root).as_posix()
        _safe_relative(relative)
        previous = folded.setdefault(_normalized_path_key(relative), relative)
        if previous != relative:
            raise SourcePackageError(
                f"Case-colliding package paths are forbidden: {previous}, {relative}"
            )
        if path.is_symlink():
            raise SourcePackageError(f"Symlink is forbidden in package: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SourcePackageError(f"Special file is forbidden in package: {relative}")
        if relative in {PACKAGE_MANIFEST_NAME, PACKAGE_CHECKSUM_NAME}:
            continue
        records.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return records


def _record_identity(root: Path) -> dict[str, tuple[int, str]]:
    return {
        str(item["path"]): (int(item["bytes"]), str(item["sha256"]))
        for item in _package_records(root)
    }


def _validate_exact_source_app(
    repository: Path,
    app_bundle: Path,
    source_commit: str,
) -> dict[str, object]:
    """Bind the supplied app bytes to a freshly staged exact Git commit.

    The app's own manifest proves internal consistency, but an attacker could
    otherwise change an embedded source file and regenerate that manifest.
    Re-staging from the reviewed Git blobs makes the outer package audit an
    independent exact-source check.
    """

    result = source_app.audit(app_bundle)
    if result.get("source_commit") != source_commit:
        raise SourcePackageError("App manifest source commit differs from package source")
    with tempfile.TemporaryDirectory(prefix=".chromamatter-expected-source-app-") as raw:
        expected = Path(raw) / APP_NAME
        source_app.stage(repository, expected, source_commit)
        expected_records = _record_identity(expected)
        actual_records = _record_identity(app_bundle)
    if expected_records != actual_records:
        missing = sorted(set(expected_records) - set(actual_records))
        extra = sorted(set(actual_records) - set(expected_records))
        changed = sorted(
            path
            for path in set(expected_records).intersection(actual_records)
            if expected_records[path] != actual_records[path]
        )
        raise SourcePackageError(
            "App bundle differs from the exact Git source commit: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    return result


def _software_checksum_bytes(package_root: Path) -> bytes:
    records: list[tuple[str, str]] = []
    folded: dict[str, str] = {}
    for path in sorted(package_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(package_root).as_posix()
        _safe_relative(relative)
        previous = folded.setdefault(_normalized_path_key(relative), relative)
        if previous != relative:
            raise SourcePackageError(
                f"Case-colliding package paths are forbidden: {previous}, {relative}"
            )
        if path.is_symlink():
            raise SourcePackageError(f"Symlink is forbidden in package: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SourcePackageError(f"Special file is forbidden in package: {relative}")
        if relative == PACKAGE_CHECKSUM_NAME:
            continue
        records.append((relative, _sha256(path).upper()))
    return "".join(f"{sha256}  {relative}\n" for relative, sha256 in records).encode(
        "utf-8"
    )


def _expected_top_level() -> set[str]:
    return {
        APP_NAME,
        INSTALL_GUIDE_NAME,
        SOURCE_COMMIT_NAME,
        SOURCE_NOTICE_NAME,
        PUBLIC_TEST_NAME,
        PUBLIC_TEST_CHECKSUM_NAME,
        "DemoData",
        PACKAGE_MANIFEST_NAME,
        PACKAGE_CHECKSUM_NAME,
    }


def _validate_top_level(package_root: Path) -> None:
    if package_root.is_symlink() or not package_root.is_dir():
        raise SourcePackageError("Package root must be a normal directory")
    if package_root.name != PACKAGE_NAME:
        raise SourcePackageError(f"Package root must be named exactly {PACKAGE_NAME!r}")
    actual = {path.name for path in package_root.iterdir()}
    expected = _expected_top_level()
    if actual != expected:
        raise SourcePackageError(
            "Package top-level allowlist mismatch: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _manifest_document(source_commit: str, contract: DemoContract) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "package_name": PACKAGE_NAME,
        "source_commit": source_commit,
        "source_backed": True,
        "bundled_python_runtime": False,
        "stable_demo_data": {
            "source_release_tag": STABLE_RELEASE_TAG,
            "source_archive": STABLE_ARCHIVE_NAME,
            "source_archive_url": STABLE_ARCHIVE_URL,
            "source_archive_bytes": STABLE_ARCHIVE_BYTES,
            "source_archive_sha256": STABLE_ARCHIVE_SHA256,
            "document_id": DEMO_DOCUMENT_ID,
            "payload_count": len(contract.payloads),
            "payload_bytes": contract.payload_bytes,
            "file_count_including_documents_and_manifest": len(
                _expected_demo_files(contract)
            ),
        },
    }


def _write_package_manifest(
    package_root: Path,
    source_commit: str,
    contract: DemoContract,
) -> None:
    manifest = _manifest_document(source_commit, contract)
    manifest["records"] = _package_records(package_root)
    destination = package_root / PACKAGE_MANIFEST_NAME
    destination.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    destination.chmod(0o644)


def _validate_public_test(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise SourcePackageError("Public four-colour test GLB is missing or unsafe")
    if path.stat().st_size != PUBLIC_TEST_BYTES or _sha256(path) != PUBLIC_TEST_SHA256:
        raise SourcePackageError("Public four-colour test GLB identity is invalid")


def _copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise SourcePackageError(f"Package source file is missing or unsafe: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o644)


def _validate_stable_archive(path: Path) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.name != STABLE_ARCHIVE_NAME
    ):
        raise SourcePackageError(
            f"Stable source archive must be a normal file named {STABLE_ARCHIVE_NAME!r}"
        )
    if path.stat().st_size != STABLE_ARCHIVE_BYTES:
        raise SourcePackageError("Stable r32.2 archive byte size is invalid")
    if _sha256(path) != STABLE_ARCHIVE_SHA256:
        raise SourcePackageError("Stable r32.2 archive SHA-256 is invalid")


def _normalized_archive_key(value: str) -> str:
    return unicodedata.normalize("NFC", value.rstrip("/")).casefold()


def _inspect_archive_members(
    archive: zipfile.ZipFile,
    contract: DemoContract,
) -> dict[str, zipfile.ZipInfo]:
    expected_demo_files = _expected_demo_files(contract)
    expected_members = {
        f"{STABLE_DEMO_PREFIX}/{relative}": relative
        for relative in expected_demo_files
    }
    expected_sizes = {
        DEMO_MANIFEST_NAME: len(contract.manifest_bytes),
        **{name: len(data) for name, data in contract.documents.items()},
        **{payload.path: payload.bytes for payload in contract.payloads},
    }
    expected_demo_directories = {
        f"{STABLE_DEMO_PREFIX}/{relative}"
        for relative in _expected_directories(expected_demo_files)
    }
    expected_demo_directories.add(STABLE_DEMO_PREFIX)

    seen_exact: set[str] = set()
    seen_normalized: dict[str, str] = {}
    member_types: dict[str, str] = {}
    selected: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        name = info.filename
        if (
            not name
            or "\x00" in name
            or "\\" in name
            or name.startswith("/")
        ):
            raise SourcePackageError(f"Unsafe stable archive path: {name!r}")
        candidate = PurePosixPath(name)
        if (
            candidate.is_absolute()
            or any(part in {"", ".", ".."} or ":" in part for part in candidate.parts)
            or candidate.as_posix() != name.rstrip("/")
        ):
            raise SourcePackageError(f"Noncanonical stable archive path: {name!r}")

        canonical = name.rstrip("/")
        if canonical in seen_exact:
            raise SourcePackageError(f"Duplicate stable archive path: {canonical}")
        seen_exact.add(canonical)
        normalized = _normalized_archive_key(canonical)
        previous = seen_normalized.setdefault(normalized, canonical)
        if previous != canonical:
            raise SourcePackageError(
                "Case/Unicode-colliding stable archive paths: "
                f"{previous!r}, {canonical!r}"
            )
        if info.flag_bits & 0x1:
            raise SourcePackageError(f"Encrypted stable archive member: {canonical}")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise SourcePackageError(
                f"Unsupported stable archive compression: {canonical}"
            )

        unix_mode = info.external_attr >> 16
        unix_type = stat.S_IFMT(unix_mode)
        dos_attributes = info.external_attr & 0xFFFF
        if dos_attributes & 0x0400:
            raise SourcePackageError(f"Reparse-point archive member: {canonical}")
        is_directory = info.is_dir()
        if unix_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise SourcePackageError(f"Special archive member: {canonical}")
        if is_directory and unix_type == stat.S_IFREG:
            raise SourcePackageError(f"Conflicting archive directory type: {canonical}")
        if not is_directory and unix_type == stat.S_IFDIR:
            raise SourcePackageError(f"Conflicting archive file type: {canonical}")
        member_types[canonical] = "directory" if is_directory else "file"

        canonical_parts = PurePosixPath(canonical).parts
        demo_prefix_parts = PurePosixPath(STABLE_DEMO_PREFIX).parts
        if len(canonical_parts) >= len(demo_prefix_parts):
            candidate_prefix = PurePosixPath(
                *canonical_parts[: len(demo_prefix_parts)]
            ).as_posix()
            if (
                _normalized_archive_key(candidate_prefix)
                == _normalized_archive_key(STABLE_DEMO_PREFIX)
                and candidate_prefix != STABLE_DEMO_PREFIX
            ):
                raise SourcePackageError(
                    "Case/Unicode-colliding DemoData archive prefix: "
                    f"{candidate_prefix!r}"
                )
        under_demo = canonical == STABLE_DEMO_PREFIX or canonical.startswith(
            STABLE_DEMO_PREFIX + "/"
        )
        if not under_demo:
            continue
        if is_directory:
            if canonical not in expected_demo_directories:
                raise SourcePackageError(
                    f"Unexpected DemoData directory in stable archive: {canonical}"
                )
            continue
        relative = expected_members.get(canonical)
        if relative is None:
            raise SourcePackageError(
                f"Unexpected DemoData file in stable archive: {canonical}"
            )
        if canonical in selected:
            raise SourcePackageError(f"Duplicate DemoData file: {canonical}")
        if info.file_size != expected_sizes[relative]:
            raise SourcePackageError(
                f"DemoData archive member byte size is invalid: {canonical}"
            )
        selected[canonical] = info

    for canonical, kind in member_types.items():
        parts = PurePosixPath(canonical).parts
        for index in range(1, len(parts)):
            ancestor = PurePosixPath(*parts[:index]).as_posix()
            if member_types.get(ancestor) == "file":
                raise SourcePackageError(
                    f"Stable archive file/ancestor conflict: {ancestor}, {canonical}"
                )

    missing = sorted(set(expected_members) - set(selected))
    if missing:
        raise SourcePackageError(
            f"Stable archive is missing canonical DemoData files: {missing}"
        )
    return selected


def extract_demo_data(
    repository: Path,
    stable_archive: Path,
    output: Path,
    source_commit: str,
) -> None:
    repository = repository.resolve()
    source_commit = _validate_source_commit(repository, source_commit)
    stable_archive = stable_archive.absolute()
    _validate_stable_archive(stable_archive)
    contract = _load_demo_contract(repository, source_commit)

    output = output.absolute()
    if output.name != "DemoData":
        raise SourcePackageError("Extracted DemoData output must be named exactly 'DemoData'")
    if output.exists() or output.is_symlink():
        raise SourcePackageError(f"Refusing to replace existing DemoData: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        archive = zipfile.ZipFile(stable_archive, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourcePackageError("Stable r32.2 archive is not a readable ZIP") from exc
    with archive:
        selected = _inspect_archive_members(archive, contract)
        with tempfile.TemporaryDirectory(
            prefix=".chromamatter-demo-data-", dir=output.parent
        ) as raw:
            temporary = Path(raw) / "DemoData"
            temporary.mkdir()
            for member_name, relative in sorted(
                (
                    (f"{STABLE_DEMO_PREFIX}/{path}", path)
                    for path in _expected_demo_files(contract)
                ),
                key=lambda item: item[0],
            ):
                info = selected[member_name]
                destination = temporary.joinpath(*PurePosixPath(relative).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with archive.open(info, "r") as source, destination.open("xb") as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    raise SourcePackageError(
                        f"Cannot extract canonical DemoData file: {relative}"
                    ) from exc
                destination.chmod(0o644)
            _validate_demo_data(temporary, contract)
            temporary.rename(output)


def stage(
    repository: Path,
    app_bundle: Path,
    demo_data_root: Path,
    stable_archive: Path,
    public_test_glb: Path,
    output: Path,
    source_commit: str,
) -> None:
    repository = repository.resolve()
    source_commit = _validate_source_commit(repository, source_commit)
    output = output.absolute()
    if output.name != PACKAGE_NAME:
        raise SourcePackageError(f"Output package must be named exactly {PACKAGE_NAME!r}")
    if output.exists() or output.is_symlink():
        raise SourcePackageError(f"Refusing to replace an existing package: {output}")

    app_bundle = app_bundle.absolute()
    if app_bundle.is_symlink() or app_bundle.name != APP_NAME:
        raise SourcePackageError(f"Input app must be named exactly {APP_NAME!r}")
    _validate_exact_source_app(repository, app_bundle, source_commit)

    contract = _load_demo_contract(repository, source_commit)
    _validate_stable_archive(stable_archive.absolute())
    _validate_demo_data(demo_data_root.absolute(), contract)
    _validate_public_test(public_test_glb.absolute())
    guide_bytes = _git_blob(repository, source_commit, GUIDE_SOURCE_PATH)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".chromamatter-source-package-", dir=output.parent
    ) as raw:
        temporary = Path(raw) / PACKAGE_NAME
        temporary.mkdir()
        shutil.copytree(app_bundle, temporary / APP_NAME)
        (temporary / INSTALL_GUIDE_NAME).write_bytes(guide_bytes)
        (temporary / INSTALL_GUIDE_NAME).chmod(0o644)
        _copy_file(public_test_glb, temporary / PUBLIC_TEST_NAME)
        (temporary / PUBLIC_TEST_CHECKSUM_NAME).write_text(
            f"{PUBLIC_TEST_SHA256}  {PUBLIC_TEST_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        (temporary / SOURCE_COMMIT_NAME).write_text(
            source_commit + "\n", encoding="ascii", newline="\n"
        )
        notice = app_bundle / "Contents" / "Resources" / SOURCE_NOTICE_NAME
        _copy_file(notice, temporary / SOURCE_NOTICE_NAME)

        demo_destination = temporary / "DemoData"
        demo_destination.mkdir()
        for relative in sorted(_expected_demo_files(contract)):
            pure = _safe_relative(relative)
            _copy_file(
                demo_data_root.joinpath(*pure.parts),
                demo_destination.joinpath(*pure.parts),
            )

        _write_package_manifest(temporary, source_commit, contract)
        (temporary / PACKAGE_CHECKSUM_NAME).write_bytes(
            _software_checksum_bytes(temporary)
        )
        (temporary / PACKAGE_CHECKSUM_NAME).chmod(0o644)
        audit(repository, temporary)
        temporary.rename(output)


def audit(repository: Path, package_root: Path) -> dict[str, object]:
    repository = repository.resolve()
    package_root = package_root.absolute()
    _validate_top_level(package_root)
    # Reject every symlink/special file and hash the complete non-self record
    # set before reading any required package file.  This prevents an
    # untrusted root entry from redirecting or blocking an earlier read.
    actual_records = _record_identity(package_root)
    manifest_path = package_root / PACKAGE_MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise SourcePackageError("Outer package manifest is missing or unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourcePackageError("Outer package manifest is invalid") from exc

    source_commit = manifest.get("source_commit")
    if not isinstance(source_commit, str):
        raise SourcePackageError("Outer package manifest has no source commit")
    source_commit = _validate_source_commit(repository, source_commit)
    contract = _load_demo_contract(repository, source_commit)

    expected_metadata = _manifest_document(source_commit, contract)
    for key, expected in expected_metadata.items():
        if manifest.get(key) != expected:
            raise SourcePackageError(f"Outer package manifest mismatch: {key}")
    if set(manifest) != {*expected_metadata, "records"}:
        raise SourcePackageError("Outer package manifest has unexpected fields")

    commit_bytes = (package_root / SOURCE_COMMIT_NAME).read_bytes()
    if commit_bytes != (source_commit + "\n").encode("ascii"):
        raise SourcePackageError("SOURCE_COMMIT.txt does not match the package manifest")

    app_bundle = package_root / APP_NAME
    _validate_exact_source_app(repository, app_bundle, source_commit)
    guide = _git_blob(repository, source_commit, GUIDE_SOURCE_PATH)
    if (package_root / INSTALL_GUIDE_NAME).read_bytes() != guide:
        raise SourcePackageError("Installation guide differs from the exact source commit")
    app_notice = app_bundle / "Contents" / "Resources" / SOURCE_NOTICE_NAME
    if (package_root / SOURCE_NOTICE_NAME).read_bytes() != app_notice.read_bytes():
        raise SourcePackageError("Root notice differs from the audited app notice")
    _validate_public_test(package_root / PUBLIC_TEST_NAME)
    expected_checksum = f"{PUBLIC_TEST_SHA256}  {PUBLIC_TEST_NAME}\n".encode("ascii")
    if (package_root / PUBLIC_TEST_CHECKSUM_NAME).read_bytes() != expected_checksum:
        raise SourcePackageError("Public test GLB checksum file is invalid")
    _validate_demo_data(package_root / "DemoData", contract)

    raw_records = manifest.get("records")
    if not isinstance(raw_records, list):
        raise SourcePackageError("Outer package manifest records are invalid")
    expected_records: dict[str, tuple[int, str]] = {}
    previous_path = ""
    for item in raw_records:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            raise SourcePackageError("Outer package manifest record is invalid")
        relative = item.get("path")
        size = item.get("bytes")
        sha256 = item.get("sha256")
        if (
            not isinstance(relative, str)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or sha256 != sha256.casefold()
            or relative in expected_records
        ):
            raise SourcePackageError("Outer package manifest record fields are invalid")
        _safe_relative(relative)
        if previous_path and relative <= previous_path:
            raise SourcePackageError("Outer package manifest records are not sorted")
        previous_path = relative
        expected_records[relative] = (size, sha256)

    if expected_records != actual_records:
        missing = sorted(set(expected_records) - set(actual_records))
        extra = sorted(set(actual_records) - set(expected_records))
        changed = sorted(
            path
            for path in set(expected_records).intersection(actual_records)
            if expected_records[path] != actual_records[path]
        )
        raise SourcePackageError(
            "Outer package manifest records mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    checksum_path = package_root / PACKAGE_CHECKSUM_NAME
    if checksum_path.is_symlink() or not checksum_path.is_file():
        raise SourcePackageError("Package checksum record is missing or unsafe")
    if checksum_path.read_bytes() != _software_checksum_bytes(package_root):
        raise SourcePackageError("Package checksum record does not match package bytes")
    return {
        "schema": SCHEMA,
        "package": os.fspath(package_root),
        "source_commit": source_commit,
        "file_count": len(actual_records) + 2,
        "demo_file_count": len(_expected_demo_files(contract)),
        "demo_payload_count": len(contract.payloads),
        "demo_payload_bytes": contract.payload_bytes,
        "status": "source-backed-package-audit-passed",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    stage_parser = subparsers.add_parser("stage", help="stage a fresh alpha2 package")
    stage_parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    stage_parser.add_argument("--app-bundle", type=Path, required=True)
    stage_parser.add_argument("--demo-data-root", type=Path, required=True)
    stage_parser.add_argument("--stable-archive", type=Path, required=True)
    stage_parser.add_argument("--public-test-glb", type=Path, required=True)
    stage_parser.add_argument("--output", type=Path, required=True)
    stage_parser.add_argument("--source-commit", required=True)

    audit_parser = subparsers.add_parser("audit", help="audit an alpha2 package")
    audit_parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    audit_parser.add_argument("--package-root", type=Path, required=True)

    extract_parser = subparsers.add_parser(
        "extract-demo",
        help="verify the stable r32.2 ZIP and atomically extract canonical DemoData",
    )
    extract_parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    extract_parser.add_argument("--stable-archive", type=Path, required=True)
    extract_parser.add_argument("--output", type=Path, required=True)
    extract_parser.add_argument("--source-commit", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.operation == "stage":
            stage(
                arguments.repository_root,
                arguments.app_bundle,
                arguments.demo_data_root,
                arguments.stable_archive,
                arguments.public_test_glb,
                arguments.output,
                arguments.source_commit,
            )
            result = audit(arguments.repository_root, arguments.output)
        elif arguments.operation == "audit":
            result = audit(arguments.repository_root, arguments.package_root)
        else:
            extract_demo_data(
                arguments.repository_root,
                arguments.stable_archive,
                arguments.output,
                arguments.source_commit,
            )
            result = {
                "schema": SCHEMA,
                "demo_data": os.fspath(arguments.output.absolute()),
                "source_commit": arguments.source_commit.casefold(),
                "file_count": 15,
                "payload_count": DEMO_PAYLOAD_COUNT,
                "payload_bytes": DEMO_PAYLOAD_BYTES,
                "status": "stable-demo-data-extraction-passed",
            }
    except (SourcePackageError, source_app.SourceAppError) as exc:
        print(f"macOS source package error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
