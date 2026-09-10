#!/usr/bin/env python3
"""Generate reviewable, deliberately non-approved macOS alpha evidence.

The input is the byte-level ``.app`` inventory produced on the macOS runner.
This tool binds that inventory to the exact source commit and hash-locked
dependency catalog, emits an SPDX 2.3 SBOM and review manifests, and fails on
unknown or internally inconsistent runtime evidence.  It never grants release
or tester-distribution approval; that remains a separate owner/legal review.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = Path(__file__).with_name("macos_compliance_components.json")
DEFAULT_LOCK = REPO_ROOT / "source" / "fixed_app" / "requirements-build-macos-arm64.lock"
RELINKING_TEMPLATES = REPO_ROOT / "licenses" / "macos"
GENERATOR_NAME = "ChromaMatter-macOS-compliance-evidence"
GENERATOR_VERSION = "1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
LOCK_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
SYSTEM_DEPENDENCY_PREFIXES = ("/System/Library/", "/usr/lib/")
RELOCATABLE_DEPENDENCY_PREFIXES = ("@executable_path/", "@loader_path/", "@rpath/")
REQUIRED_OUTPUTS = (
    "DISTRIBUTION_APPROVAL.json",
    "BINARY_COMPONENT_MAP.json",
    "SBOM.spdx.json",
    "CORRESPONDING_SOURCE_MANIFEST.json",
    "RELINKING_EN.md",
    "RELINKING_JA.md",
    "MACOS_ALPHA_SOURCE_OFFER_STATUS.txt",
)


class EvidenceError(RuntimeError):
    """Raised when an input cannot support honest evidence generation."""


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvidenceError(f"JSON root must be an object: {path}")
    return payload


def _safe_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise EvidenceError(f"{label} must be a non-empty POSIX path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise EvidenceError(f"{label} is unsafe: {value!r}")
    return pure.as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write_text(path, serialized)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _parse_lock(path: Path) -> dict[str, str]:
    locked: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LOCK_RE.match(line.strip())
        if not match:
            continue
        name = _canonical_name(match.group(1))
        if name in locked:
            raise EvidenceError(f"Duplicate package in macOS lock: {name}")
        locked[name] = match.group(2)
    if not locked:
        raise EvidenceError(f"No requirements found in {path}")
    return locked


def _validate_catalog(catalog: dict[str, Any], locked: dict[str, str]) -> dict[str, dict[str, Any]]:
    if catalog.get("schema") != "chromamatter.macos-compliance-component-catalog.v1":
        raise EvidenceError("Unsupported macOS component catalog schema")
    raw = catalog.get("distributions")
    if not isinstance(raw, dict):
        raise EvidenceError("Catalog distributions must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_name, component in raw.items():
        name = _canonical_name(raw_name)
        if not isinstance(component, dict):
            raise EvidenceError(f"Catalog entry must be an object: {raw_name}")
        if name in normalized:
            raise EvidenceError(f"Duplicate canonical catalog name: {name}")
        normalized[name] = component
        if component.get("version") != locked.get(name):
            raise EvidenceError(
                f"Catalog/lock version mismatch for {name}: "
                f"{component.get('version')!r} != {locked.get(name)!r}"
            )
        if not isinstance(component.get("license_declared"), str):
            raise EvidenceError(f"Missing license declaration for {name}")
        source_url = component.get("source_url")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            raise EvidenceError(f"Source URL is not HTTPS for {name}")
        digest = component.get("source_sha256")
        if digest is not None and (not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)):
            raise EvidenceError(f"Invalid source SHA-256 for {name}")
        prefixes = component.get("path_prefixes")
        if not isinstance(prefixes, list) or not prefixes:
            raise EvidenceError(f"No bundle path prefixes for {name}")
        for index, prefix in enumerate(prefixes):
            _safe_relative_path(prefix, f"{name}.path_prefixes[{index}]")
    missing = sorted(set(locked) - set(normalized))
    extra = sorted(set(normalized) - set(locked))
    if missing or extra:
        raise EvidenceError(f"Catalog does not exactly cover lock; missing={missing}, extra={extra}")
    return normalized


def _validate_inventory(inventory: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if inventory.get("schema") != "chromamatter.macos-app-inventory":
        raise EvidenceError("Unsupported macOS app inventory schema")
    if inventory.get("schema_version") != 1:
        raise EvidenceError("Unsupported macOS app inventory version")
    files = inventory.get("regular_files")
    symlinks = inventory.get("symlinks")
    distributions = inventory.get("packaged_distributions")
    if not isinstance(files, list) or not files:
        raise EvidenceError("Inventory has no regular files")
    if not isinstance(symlinks, list) or not isinstance(distributions, list):
        raise EvidenceError("Inventory symlinks/distributions are malformed")
    bundle = inventory.get("bundle")
    if not isinstance(bundle, dict) or bundle.get("name") != "ChromaMatter-macOS-Alpha.app":
        raise EvidenceError("Inventory is not for the expected macOS alpha bundle")
    identity = bundle.get("identity")
    if not isinstance(identity, dict):
        raise EvidenceError("Inventory bundle identity is missing")
    required_identity = {
        "CFBundleExecutable": "ChromaMatter",
        "CFBundleIdentifier": "io.github.ponkichi0718.chromamatter.alpha",
    }
    for key, expected in required_identity.items():
        if identity.get(key) != expected:
            raise EvidenceError(f"Unexpected bundle identity {key}: {identity.get(key)!r}")

    seen: set[str] = set()
    issues: list[str] = []
    for index, row in enumerate(files):
        if not isinstance(row, dict):
            raise EvidenceError(f"regular_files[{index}] is not an object")
        path = _safe_relative_path(row.get("path"), f"regular_files[{index}].path")
        folded = path.casefold()
        if folded in seen:
            raise EvidenceError(f"Duplicate/case-colliding inventory path: {path}")
        seen.add(folded)
        digest = row.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise EvidenceError(f"Invalid file SHA-256: {path}")
        if not isinstance(row.get("size"), int) or row["size"] < 0:
            raise EvidenceError(f"Invalid file size: {path}")
        macho = row.get("mach_o")
        if macho is None:
            continue
        if not isinstance(macho, dict):
            raise EvidenceError(f"Malformed Mach-O record: {path}")
        architectures = macho.get("architectures")
        if architectures != ["arm64"]:
            issues.append(f"non-arm64-or-unverified-architecture:{path}:{architectures!r}")
        dependencies = macho.get("dependencies")
        if not isinstance(dependencies, list):
            raise EvidenceError(f"Mach-O dependencies are malformed: {path}")
        for dependency in dependencies:
            if not isinstance(dependency, str) or not dependency:
                raise EvidenceError(f"Invalid Mach-O dependency: {path}")
            if dependency.startswith(("@", "/")) and not dependency.startswith(
                SYSTEM_DEPENDENCY_PREFIXES + RELOCATABLE_DEPENDENCY_PREFIXES
            ):
                issues.append(f"non-relocatable-dependency:{path}:{dependency}")

    for index, link in enumerate(symlinks):
        if not isinstance(link, dict):
            raise EvidenceError(f"symlinks[{index}] is not an object")
        path = _safe_relative_path(link.get("path"), f"symlinks[{index}].path")
        if link.get("confined_to_bundle") is not True:
            issues.append(f"unconfined-symlink:{path}")
        if link.get("target_exists") is not True:
            issues.append(f"broken-symlink:{path}")

    signing = inventory.get("code_signing")
    if not isinstance(signing, dict):
        raise EvidenceError("Inventory code_signing must be an object")
    if signing.get("verify_ok") is not True:
        issues.append("codesign-verification-failed")
    if signing.get("ad_hoc") is not True:
        issues.append("unexpected-signing-mode")
    counts = inventory.get("counts")
    expected_counts = {
        "regular_files": len(files),
        "symlinks": len(symlinks),
        "mach_o_files": sum(row.get("mach_o") is not None for row in files),
        "packaged_distributions": len(distributions),
    }
    if not isinstance(counts, dict):
        raise EvidenceError("Inventory counts must be an object")
    for key, expected in expected_counts.items():
        if counts.get(key) != expected:
            raise EvidenceError(
                f"Inventory count mismatch for {key}: {counts.get(key)!r} != {expected}"
            )
    for distribution in distributions:
        if not isinstance(distribution, dict):
            raise EvidenceError("Packaged distribution record is not an object")
        if distribution.get("direct_url_metadata_present") is True:
            issues.append(
                "direct-url-metadata-present:"
                + str(distribution.get("canonical_name") or distribution.get("name"))
            )
        record = distribution.get("record")
        if not isinstance(record, dict) or record.get("available") is not True:
            issues.append(
                "missing-wheel-record:"
                + str(distribution.get("canonical_name") or distribution.get("name"))
            )
        elif record.get("invalid_or_absolute_row_count") != 0:
            issues.append(
                "invalid-wheel-record-paths:"
                + str(distribution.get("canonical_name") or distribution.get("name"))
            )
    return files, distributions, sorted(set(issues))


def _owner_for_path(path: str, catalog: dict[str, dict[str, Any]]) -> str | None:
    folded = path.casefold()
    matches: list[tuple[int, str]] = []
    for name, component in catalog.items():
        for prefix in component["path_prefixes"]:
            normalized = prefix.casefold().rstrip("/")
            if (
                folded == normalized
                or folded.startswith(normalized + "/")
                or folded.startswith(normalized + ".")
            ):
                matches.append((len(normalized), name))
    if matches:
        return max(matches)[1]
    if folded.startswith("contents/frameworks/python.framework/"):
        return "cpython-3.13.14-macos-runtime"
    if folded.startswith("contents/frameworks/python3__dot__13/"):
        return "cpython-3.13.14-macos-runtime"
    if folded.startswith(("contents/frameworks/_tcl_data/", "contents/frameworks/_tk_data/")):
        return "tcl-tk-8.6.18"
    if folded in ("contents/frameworks/tcl", "contents/frameworks/tk"):
        return "tcl-tk-8.6.18"
    if folded in (
        "contents/frameworks/libcrypto.3.dylib",
        "contents/frameworks/libssl.3.dylib",
    ):
        return "cpython-openssl-macos-runtime"
    if folded == "contents/macos/chromamatter":
        return "chromamatter"
    if folded.startswith("contents/frameworks/") and "/" not in path[len("Contents/Frameworks/") :]:
        name = PurePosixPath(path).name.casefold()
        if name.startswith("_") and name.endswith((".so", ".dylib")):
            return "cpython-3.13.14-macos-runtime"
    return None


def _spdx_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"SPDXRef-{kind}-{digest}"


def _component_rows(
    distributions: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
    locked: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[str] = set()
    for distribution in sorted(
        distributions,
        key=lambda value: _canonical_name(str(value.get("canonical_name") or value.get("name") or "")),
    ):
        name = _canonical_name(str(distribution.get("canonical_name") or distribution.get("name") or ""))
        if not name or name in seen:
            raise EvidenceError(f"Invalid or duplicate packaged distribution: {name!r}")
        seen.add(name)
        if name not in catalog:
            raise EvidenceError(f"Packaged distribution is absent from catalog: {name}")
        version = distribution.get("version")
        if version != locked[name]:
            raise EvidenceError(
                f"Packaged distribution does not match lock: {name} {version!r} != {locked[name]!r}"
            )
        license_files = distribution.get("license_files")
        if not isinstance(license_files, list) or not license_files:
            issues.append(f"missing-wheel-license-evidence:{name}")
            license_files = []
        normalized_licenses = []
        for index, item in enumerate(license_files):
            if not isinstance(item, dict):
                raise EvidenceError(f"Malformed license record for {name}")
            path = _safe_relative_path(item.get("path"), f"{name}.license_files[{index}].path")
            digest = item.get("sha256")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise EvidenceError(f"Invalid license SHA-256 for {name}: {path}")
            normalized_licenses.append(
                {"path": path, "size": item.get("size"), "sha256": digest}
            )
        component = catalog[name]
        record = distribution.get("record")
        record_summary = None
        if isinstance(record, dict):
            record_summary = {
                key: record.get(key)
                for key in (
                    "available",
                    "path",
                    "size",
                    "sha256",
                    "entry_count",
                    "invalid_or_absolute_row_count",
                )
            }
        rows.append(
            {
                "id": f"python-distribution:{name}",
                "name": name,
                "version": version,
                "license_declared": component["license_declared"],
                "license_note": component.get("license_note"),
                "source": {
                    "url": component["source_url"],
                    "sha256": component.get("source_sha256"),
                    "commit": component.get("source_commit"),
                },
                "wheel": distribution.get("wheel"),
                "record": record_summary,
                "license_files": normalized_licenses,
            }
        )
    return rows, issues


def generate_evidence(
    inventory_path: Path,
    source_commit: str,
    created_utc: str,
    catalog_path: Path = DEFAULT_CATALOG,
    lock_path: Path = DEFAULT_LOCK,
) -> dict[str, Any]:
    if not COMMIT_RE.fullmatch(source_commit):
        raise EvidenceError("source commit must be exactly 40 lowercase hexadecimal characters")
    try:
        parsed_time = dt.datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("created UTC time must be ISO-8601") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() != dt.timedelta(0):
        raise EvidenceError("created UTC time must include the UTC offset")

    inventory_path = inventory_path.resolve(strict=True)
    inventory_digest = _sha256_file(inventory_path)
    inventory = _read_json(inventory_path)
    locked = _parse_lock(lock_path.resolve(strict=True))
    raw_catalog = _read_json(catalog_path.resolve(strict=True))
    catalog = _validate_catalog(raw_catalog, locked)
    files, distributions, mechanical_issues = _validate_inventory(inventory)
    components, component_issues = _component_rows(distributions, catalog, locked)
    files_by_path = {row["path"].casefold(): row for row in files}
    for component in components:
        for license_file in component["license_files"]:
            inventoried = files_by_path.get(license_file["path"].casefold())
            if inventoried is None:
                component_issues.append(
                    f"wheel-license-file-not-in-app:{component['name']}:{license_file['path']}"
                )
            elif (
                inventoried["sha256"] != license_file["sha256"]
                or inventoried["size"] != license_file["size"]
            ):
                component_issues.append(
                    f"wheel-license-file-identity-mismatch:{component['name']}:{license_file['path']}"
                )

    native_files: list[dict[str, Any]] = []
    owner_issues: list[str] = []
    for row in files:
        macho = row.get("mach_o")
        if macho is None:
            continue
        owner = _owner_for_path(row["path"], catalog)
        if owner is None:
            owner_issues.append(f"unmapped-native-owner:{row['path']}")
        native_files.append(
            {
                "path": row["path"],
                "size": row["size"],
                "sha256": row["sha256"],
                "owner": owner,
                "architectures": macho["architectures"],
                "dependencies": macho["dependencies"],
            }
        )
    validation_issues = sorted(set(mechanical_issues + component_issues + owner_issues))
    map_status = "blocked" if validation_issues else "review-required"
    known_closures = raw_catalog.get("known_native_closures")
    if not isinstance(known_closures, list) or not known_closures:
        raise EvidenceError("Catalog has no known native closure declarations")

    common = {
        "source_commit": source_commit,
        "inventory_sha256": inventory_digest,
    }
    raw_signing = inventory.get("code_signing") or {}
    signing_details = raw_signing.get("details") or {}
    component_map = {
        "schema": "chromamatter.macos-binary-component-map.v1",
        "status": map_status,
        **common,
        "bundle": inventory.get("bundle"),
        "counts": inventory.get("counts"),
        "code_signing": {
            "verify_ok": raw_signing.get("verify_ok"),
            "ad_hoc": raw_signing.get("ad_hoc"),
            "identity_authority_count": raw_signing.get("identity_authority_count"),
            "verify_exit_code": raw_signing.get("verify_exit_code"),
            "details_exit_code": raw_signing.get("details_exit_code"),
            "normalization": raw_signing.get("normalization"),
            "details": {
                key: signing_details.get(key)
                for key in (
                    "format",
                    "identifier",
                    "signature",
                    "team_identifier",
                    "cdhash",
                    "cms_digest",
                )
            },
            "full_messages": "bound by inventory_sha256; not duplicated here",
        },
        "components": components,
        "known_native_closures": known_closures,
        "native_files": native_files,
        "validation": {
            "mechanically_consistent": not validation_issues,
            "issues": validation_issues,
            "human_native_closure_review_complete": False,
            "legal_review_complete": False,
        },
    }

    app_spdx = "SPDXRef-Package-ChromaMatter"
    packages: list[dict[str, Any]] = [
        {
            "name": "ChromaMatter",
            "SPDXID": app_spdx,
            "versionInfo": "0.9",
            "downloadLocation": f"https://github.com/Ponkichi0718/ChromaMatter/tree/{source_commit}",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "GPL-3.0-or-later",
            "copyrightText": "NOASSERTION",
            "sourceInfo": f"Exact source commit {source_commit}",
        }
    ]
    package_ids: dict[str, str] = {}
    for component in components:
        name = component["name"]
        spdx_id = _spdx_id("Package", name)
        package_ids[name] = spdx_id
        source = component["source"]
        packages.append(
            {
                "name": name,
                "SPDXID": spdx_id,
                "versionInfo": component["version"],
                "downloadLocation": source["url"],
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": component["license_declared"],
                "copyrightText": "NOASSERTION",
                "sourceInfo": "Source archive SHA-256: "
                + (source.get("sha256") or "not yet established for this wheel pairing"),
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:pypi/{name}@{component['version']}",
                    }
                ],
            }
        )
    closure_package_ids: dict[str, str] = {}
    for closure in known_closures:
        closure_id = closure.get("id")
        if not isinstance(closure_id, str) or not closure_id:
            raise EvidenceError("Known native closure lacks an id")
        spdx_id = _spdx_id("NativeClosure", closure_id)
        closure_package_ids[closure_id] = spdx_id
        packages.append(
            {
                "name": closure.get("name") or closure_id,
                "SPDXID": spdx_id,
                "versionInfo": closure.get("version") or "NOASSERTION",
                "downloadLocation": closure["source_url"],
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": closure["license_declared"],
                "copyrightText": "NOASSERTION",
                "sourceInfo": (
                    "Native-closure review state: "
                    + str(closure.get("review_status") or "not-recorded")
                ),
            }
        )

    relationships: list[dict[str, str]] = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": app_spdx,
        }
    ]
    for package_id in package_ids.values():
        relationships.append(
            {
                "spdxElementId": app_spdx,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": package_id,
            }
        )
    for package_id in closure_package_ids.values():
        relationships.append(
            {
                "spdxElementId": app_spdx,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": package_id,
            }
        )
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "ChromaMatter-macOS-Alpha-0.9",
        "documentNamespace": (
            "https://github.com/Ponkichi0718/ChromaMatter/spdx/macos-alpha/"
            + source_commit
            + "/"
            + inventory_digest
        ),
        "creationInfo": {
            "created": created_utc,
            "creators": [f"Tool: {GENERATOR_NAME}-{GENERATOR_VERSION}"],
            "comment": "Generated inventory evidence; not distribution approval.",
        },
        "documentDescribes": [app_spdx],
        "packages": packages,
        "relationships": relationships,
        "annotations": [
            {
                "annotationDate": created_utc,
                "annotationType": "OTHER",
                "annotator": f"Tool: {GENERATOR_NAME}-{GENERATOR_VERSION}",
                "comment": (
                    f"macOS app inventory SHA-256 {inventory_digest}; "
                    f"component-map status {map_status}; human review pending. "
                    "Per-file SHA-256 and Mach-O ownership records are in "
                    "BINARY_COMPONENT_MAP.json rather than duplicated as SPDX files."
                ),
            }
        ],
    }

    source_components = []
    for component in components:
        source = component["source"]
        source_components.append(
            {
                "component_id": component["id"],
                "name": component["name"],
                "version": component["version"],
                "license_declared": component["license_declared"],
                "source_url": source["url"],
                "source_sha256": source.get("sha256"),
                "source_commit": source.get("commit"),
                "pairing_status": (
                    "version-and-sha256-pinned-source-candidate"
                    if source.get("sha256")
                    else "blocked-no-source-archive-sha256"
                ),
            }
        )
    gaps = [
        {
            "id": "native-binary-to-source-closure-review",
            "status": "unresolved",
            "reason": "Each Mach-O file and bundled/static native component must be paired with complete source and build provenance.",
        },
        {
            "id": "pymeshlab-arm64-wheel-closure",
            "status": "unresolved",
            "reason": "The PyMeshLab arm64 wheel has no PyPI sdist and its MeshLab/Qt/native closure is not yet byte-bound to complete sources.",
        },
        {
            "id": "pytetwild-arm64-wheel-closure",
            "status": "unresolved",
            "reason": "The upstream arm64 PyTetWild wheel is distinct from the approved Windows controlled rebuild; fTetWild/GMP/build inputs require separate proof.",
        },
        {
            "id": "lgpl-relinking-practical-validation",
            "status": "unresolved",
            "reason": "Qt, GEOS, GMP and any other LGPL libraries must be identified and replacement/relinking steps verified on an actual volunteer Mac.",
        },
        {
            "id": "complete-corresponding-source-archive",
            "status": "unresolved",
            "reason": "No complete source archive and immutable public checksum/URL are paired with this exact app inventory yet.",
        },
        {
            "id": "owner-distribution-approval",
            "status": "unresolved",
            "reason": "The project owner has not approved this exact source commit and app inventory for external tester distribution.",
        },
    ]
    if validation_issues:
        gaps.insert(
            0,
            {
                "id": "app-inventory-validation",
                "status": "unresolved",
                "reason": "Mechanical app inventory checks failed: " + "; ".join(validation_issues),
            },
        )
    sources = {
        "schema": "chromamatter.macos-corresponding-source-manifest.v1",
        "status": "candidate-only",
        **common,
        "application_source": {
            "url": f"https://github.com/Ponkichi0718/ChromaMatter/tree/{source_commit}",
            "commit": source_commit,
            "license": "GPL-3.0-or-later",
        },
        "component_sources": source_components,
        "known_native_closures": known_closures,
        "known_gaps": gaps,
        "complete_archive": {
            "url": None,
            "sha256": None,
            "status": "not-built-or-reviewed",
        },
    }
    approval = {
        "schema": "chromamatter.macos-distribution-approval.v1",
        "status": "blocked",
        **common,
        "scope": "Apple Silicon macOS 15+ external volunteer alpha testing",
        "signing": "ad-hoc-only-developer-id-unsigned-unnotarized",
        "generated_by": f"{GENERATOR_NAME}-{GENERATOR_VERSION}",
        "automatic_approval_permitted": False,
        "owner_approval": {
            "approved": False,
            "reviewer": None,
            "reviewed_at": None,
        },
        "blockers": [gap["id"] for gap in gaps],
        "required_final_actions": [
            "Review every Mach-O ownership and dependency mapping.",
            "Publish and checksum complete corresponding source for the exact app bytes.",
            "Validate LGPL replacement/relinking instructions on Apple Silicon.",
            "Update bilingual notices so they no longer declare pending work.",
            "Record explicit owner approval for this exact commit and inventory.",
        ],
    }
    source_offer = (
        "MACOS ALPHA CORRESPONDING SOURCE STATUS: BLOCKED\n"
        "================================================\n\n"
        f"Source commit: {source_commit}\n"
        f"App inventory SHA-256: {inventory_digest}\n"
        "Manifest status: candidate-only\n"
        "Complete source archive URL: not available\n"
        "Complete source archive SHA-256: not available\n\n"
        "Do not distribute the tester app while this file says BLOCKED. The public\n"
        "repository contains the application source, but it is not yet the reviewed\n"
        "complete corresponding-source package for every bundled macOS native binary.\n"
        "See CORRESPONDING_SOURCE_MANIFEST.json for the unresolved component closures.\n"
    )
    return {
        "DISTRIBUTION_APPROVAL.json": approval,
        "BINARY_COMPONENT_MAP.json": component_map,
        "SBOM.spdx.json": sbom,
        "CORRESPONDING_SOURCE_MANIFEST.json": sources,
        "MACOS_ALPHA_SOURCE_OFFER_STATUS.txt": source_offer,
    }


def validate_generated_evidence(output_dir: Path) -> None:
    for name in REQUIRED_OUTPUTS:
        path = output_dir / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise EvidenceError(f"Required evidence output is missing or unsafe: {path}")
    approval = _read_json(output_dir / "DISTRIBUTION_APPROVAL.json")
    component_map = _read_json(output_dir / "BINARY_COMPONENT_MAP.json")
    sbom = _read_json(output_dir / "SBOM.spdx.json")
    sources = _read_json(output_dir / "CORRESPONDING_SOURCE_MANIFEST.json")
    if approval.get("schema") != "chromamatter.macos-distribution-approval.v1":
        raise EvidenceError("Generated approval schema is invalid")
    if approval.get("status") != "blocked" or approval.get("automatic_approval_permitted") is not False:
        raise EvidenceError("The generator must not create distribution approval")
    if component_map.get("status") not in ("blocked", "review-required"):
        raise EvidenceError("Generated component-map status is invalid")
    if sbom.get("spdxVersion") != "SPDX-2.3" or sbom.get("dataLicense") != "CC0-1.0":
        raise EvidenceError("Generated SPDX document identity is invalid")
    if sources.get("status") != "candidate-only":
        raise EvidenceError("The generator must not approve corresponding source")
    identities = {
        (payload.get("source_commit"), payload.get("inventory_sha256"))
        for payload in (approval, component_map, sources)
    }
    if len(identities) != 1:
        raise EvidenceError("Evidence outputs do not bind the same commit/inventory")
    for name in ("RELINKING_EN.md", "RELINKING_JA.md"):
        text = (output_dir / name).read_text(encoding="utf-8")
        if "DRAFT" not in text or "0.9" not in text:
            raise EvidenceError(f"Relinking template lacks its draft/version warning: {name}")


def write_evidence(output_dir: Path, payloads: dict[str, Any]) -> None:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        path = output_dir / name
        if isinstance(payload, dict):
            _write_json(path, payload)
        else:
            _write_text(path, str(payload))
    for name in ("RELINKING_EN.md", "RELINKING_JA.md"):
        source = RELINKING_TEMPLATES / name
        if not source.is_file():
            raise EvidenceError(f"Canonical relinking template is missing: {source}")
        destination = output_dir / name
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
    validate_generated_evidence(output_dir)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--created-utc", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payloads = generate_evidence(
        args.inventory,
        args.source_commit,
        args.created_utc,
        catalog_path=args.catalog,
        lock_path=args.lock,
    )
    write_evidence(args.output_dir, payloads)
    component_status = payloads["BINARY_COMPONENT_MAP.json"]["status"]
    print(
        f"Generated mechanically validated macOS evidence ({component_status}); "
        "external tester distribution remains BLOCKED pending human review."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
