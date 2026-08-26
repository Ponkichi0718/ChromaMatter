#!/usr/bin/env python3
"""Generate deterministic, observed-facts-only diagnostics for a macOS app.

This inventory is deliberately not an SBOM, a binary component ownership map,
a corresponding-source decision, or a distribution approval.  It records the
bytes and metadata that are actually present in one audited ``.app`` bundle so
that those separate reviews have reproducible input evidence.
"""

from __future__ import annotations

import argparse
import csv
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
from typing import Callable, Iterable, Sequence


SCHEMA = "chromamatter.macos-app-inventory"
SCHEMA_VERSION = 1
GENERATOR_VERSION = 1
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}
PLIST_IDENTITY_KEYS = (
    "CFBundleDisplayName",
    "CFBundleExecutable",
    "CFBundleGetInfoString",
    "CFBundleIdentifier",
    "CFBundleName",
    "CFBundleShortVersionString",
    "CFBundleVersion",
    "LSArchitecturePriority",
    "LSMinimumSystemVersion",
    "NSHighResolutionCapable",
    "NSHumanReadableCopyright",
)
CODE_SIGN_DETAIL_KEYS = {
    "CandidateCDHash sha256": "candidate_cdhash_sha256",
    "CDHash": "cdhash",
    "CMSDigest": "cms_digest",
    "CMSDigestType": "cms_digest_type",
    "CodeDirectory": "code_directory",
    "Executable": "executable",
    "Format": "format",
    "Hash choices": "hash_choices",
    "Identifier": "identifier",
    "Info.plist entries": "info_plist_entries",
    "Internal requirements count": "internal_requirements_count",
    "Runtime Version": "runtime_version",
    "Sealed Resources version": "sealed_resources_version",
    "Signature": "signature",
    "TeamIdentifier": "team_identifier",
}


class InventoryError(RuntimeError):
    """Raised when an app cannot be inventoried without ambiguous evidence."""


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run_command(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(value) for value in arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _canonical_bundle_path(bundle: Path, path: Path) -> str:
    try:
        relative = path.relative_to(bundle)
    except ValueError as exc:
        raise InventoryError(f"Path is outside app bundle: {path.name}") from exc
    normalized = unicodedata.normalize("NFC", relative.as_posix())
    if normalized in {"", "."} or PurePosixPath(normalized).is_absolute():
        raise InventoryError(f"Invalid bundle-relative path: {normalized!r}")
    if any(part in {"", ".", ".."} for part in PurePosixPath(normalized).parts):
        raise InventoryError(f"Noncanonical bundle-relative path: {normalized!r}")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file_fact(bundle: Path, path: Path) -> dict[str, object]:
    metadata = path.stat(follow_symlinks=False)
    return {
        "path": _canonical_bundle_path(bundle, path),
        "sha256": _sha256(path),
        "size": metadata.st_size,
    }


def describe_symlink_target(
    bundle: Path,
    link_path: Path,
    raw_target: str,
    *,
    target_exists: bool,
) -> dict[str, object]:
    """Return a privacy-safe symlink target and confinement description."""

    bundle = bundle.resolve()
    raw = Path(raw_target)
    candidate = raw if raw.is_absolute() else link_path.parent / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved_relative = _canonical_bundle_path(bundle, resolved)
    except InventoryError:
        confined = False
        resolved_relative = None
    else:
        confined = True

    if raw.is_absolute():
        if confined:
            reported_target = resolved_relative
            target_form = "bundle-absolute-normalized"
        else:
            reported_target = "<outside-bundle-redacted>"
            target_form = "absolute-outside-bundle-redacted"
    else:
        reported_target = unicodedata.normalize("NFC", raw_target.replace("\\", "/"))
        target_form = "link-relative"

    return {
        "confined_to_bundle": confined,
        "resolved_path": resolved_relative,
        "target": reported_target,
        "target_exists": bool(target_exists),
        "target_form": target_form,
    }


def _iter_bundle_entries(bundle: Path) -> Iterable[tuple[Path, str]]:
    """Walk without following directory symlinks and yield files/symlinks."""

    for directory, directory_names, file_names in os.walk(
        bundle, topdown=True, followlinks=False
    ):
        directory_path = Path(directory)
        directory_names.sort(key=lambda value: unicodedata.normalize("NFC", value))
        file_names.sort(key=lambda value: unicodedata.normalize("NFC", value))

        retained_directories: list[str] = []
        for name in directory_names:
            candidate = directory_path / name
            if candidate.is_symlink():
                yield candidate, "symlink"
            else:
                retained_directories.append(name)
        directory_names[:] = retained_directories

        for name in file_names:
            candidate = directory_path / name
            mode = candidate.lstat().st_mode
            if stat.S_ISLNK(mode):
                yield candidate, "symlink"
            elif stat.S_ISREG(mode):
                yield candidate, "regular"
            else:
                raise InventoryError(
                    "Unsupported special file in app bundle: "
                    + _canonical_bundle_path(bundle, candidate)
                )


def _is_macho(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) in MACHO_MAGICS


def _require_command(
    runner: CommandRunner, arguments: Sequence[str], description: str
) -> subprocess.CompletedProcess[str]:
    completed = runner(arguments)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise InventoryError(
            f"{description} failed with exit {completed.returncode}: {detail}"
        )
    return completed


def _macho_fact(path: Path, runner: CommandRunner) -> dict[str, object]:
    file_result = _require_command(runner, ("file", "-b", str(path)), "file")
    lipo_result = _require_command(runner, ("lipo", "-archs", str(path)), "lipo")
    otool_result = _require_command(runner, ("otool", "-L", str(path)), "otool")

    architectures = sorted(set(lipo_result.stdout.strip().split()))
    if not architectures:
        raise InventoryError(f"lipo returned no architecture for {path.name}")

    dependencies: list[str] = []
    for line in otool_result.stdout.splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        install_name = stripped.rsplit(" (", 1)[0]
        dependencies.append(install_name)

    return {
        "architectures": architectures,
        "dependencies": sorted(set(dependencies)),
        "file_description": file_result.stdout.strip(),
    }


def _normalise_tool_line(line: str, bundle: Path) -> str:
    result = line.strip()
    for candidate in sorted(
        {str(bundle), str(bundle.resolve())}, key=len, reverse=True
    ):
        result = result.replace(candidate, "<APP_BUNDLE>")
    return result


def _code_signing_fact(bundle: Path, runner: CommandRunner) -> dict[str, object]:
    verify = runner(
        ("codesign", "--verify", "--deep", "--strict", "--verbose=2", str(bundle))
    )
    verify_lines = sorted(
        {
            normalized
            for normalized in (
                _normalise_tool_line(line, bundle)
                for line in (verify.stdout + "\n" + verify.stderr).splitlines()
            )
            if normalized
        }
    )

    display = runner(("codesign", "-dv", "--verbose=4", str(bundle)))
    display_lines = (display.stdout + "\n" + display.stderr).splitlines()
    details: dict[str, object] = {}
    authority_count = 0
    for line in display_lines:
        normalized = _normalise_tool_line(line, bundle)
        if normalized.startswith("Authority="):
            # The count proves whether an identity chain was displayed without
            # copying a possibly personal certificate common name into logs.
            authority_count += 1
            continue
        if normalized.startswith("CodeDirectory "):
            details["code_directory"] = normalized.removeprefix("CodeDirectory ")
            continue
        if "=" not in normalized:
            continue
        key, value = normalized.split("=", 1)
        output_key = CODE_SIGN_DETAIL_KEYS.get(key)
        if output_key is not None:
            details[output_key] = value

    signature = str(details.get("signature", ""))
    return {
        "ad_hoc": signature.casefold() == "adhoc",
        "details": details,
        "details_exit_code": display.returncode,
        "identity_authority_count": authority_count,
        "normalization": (
            "bundle absolute paths are replaced with <APP_BUNDLE>; certificate "
            "authority names and signing timestamps are intentionally omitted"
        ),
        "verify_exit_code": verify.returncode,
        "verify_messages": verify_lines,
        "verify_ok": verify.returncode == 0,
    }


def _plist_identity(info_plist: Path) -> dict[str, object]:
    try:
        with info_plist.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise InventoryError(f"Cannot parse Info.plist: {exc}") from exc
    if not isinstance(payload, dict):
        raise InventoryError("Info.plist root is not a dictionary")

    identity: dict[str, object] = {}
    for key in PLIST_IDENTITY_KEYS:
        value = payload.get(key)
        if isinstance(value, (str, bool, int)):
            identity[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            identity[key] = list(value)
    return identity


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _is_dist_info_root(part: str) -> bool:
    return part.casefold().endswith(".dist-info")


def _distribution_roots(file_facts: Sequence[dict[str, object]]) -> list[str]:
    roots: set[str] = set()
    paths = {str(fact["path"]) for fact in file_facts}
    for fact in file_facts:
        parts = PurePosixPath(str(fact["path"])).parts
        for index, part in enumerate(parts):
            if _is_dist_info_root(part):
                root = PurePosixPath(*parts[: index + 1]).as_posix()
                # A copied license can itself retain a ``.dist-info`` parent
                # below licenses/wheels.  Treat only roots carrying packaged
                # METADATA as observed installed distributions.
                if f"{root}/METADATA" in paths:
                    roots.add(root)
                break
    return sorted(roots)


def _file_fact_map(
    file_facts: Sequence[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {str(fact["path"]): fact for fact in file_facts}


def _metadata_message(path: Path):
    try:
        return BytesParser(policy=compat32).parsebytes(path.read_bytes())
    except (OSError, UnicodeError) as exc:
        raise InventoryError(f"Cannot parse packaged metadata {path.name}: {exc}") from exc


def _record_fact(path: Path, fact: dict[str, object]) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    invalid_rows = 0
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                if len(row) != 3 or "\x00" in row[0]:
                    invalid_rows += 1
                    continue
                wheel_path = unicodedata.normalize("NFC", row[0].replace("\\", "/"))
                if PurePosixPath(wheel_path).is_absolute():
                    invalid_rows += 1
                    continue
                try:
                    declared_size: int | None = int(row[2]) if row[2] else None
                except ValueError:
                    invalid_rows += 1
                    continue
                entries.append(
                    {
                        "declared_hash": row[1] or None,
                        "declared_size": declared_size,
                        "wheel_record_path": wheel_path,
                    }
                )
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InventoryError(f"Cannot parse packaged RECORD {path.name}: {exc}") from exc

    entries.sort(
        key=lambda item: (
            str(item["wheel_record_path"]),
            str(item["declared_hash"] or ""),
            -1 if item["declared_size"] is None else int(item["declared_size"]),
        )
    )
    return {
        "available": True,
        "entry_count": len(entries),
        "entries": entries,
        "invalid_or_absolute_row_count": invalid_rows,
        "path": fact["path"],
        "sha256": fact["sha256"],
        "size": fact["size"],
    }


def _wheel_fact(path: Path, fact: dict[str, object]) -> dict[str, object]:
    message = _metadata_message(path)
    return {
        "generator": message.get("Generator"),
        "path": fact["path"],
        "root_is_purelib": message.get("Root-Is-Purelib"),
        "sha256": fact["sha256"],
        "size": fact["size"],
        "tags": sorted(message.get_all("Tag", [])),
        "wheel_version": message.get("Wheel-Version"),
    }


def _license_facts_for_distribution(
    distribution_name: str | None,
    dist_info_root: str,
    file_facts: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    canonical_name = (
        _canonical_distribution_name(distribution_name) if distribution_name else None
    )
    result: list[dict[str, object]] = []
    root_prefix = dist_info_root + "/"
    for fact in file_facts:
        path = str(fact["path"])
        parts = PurePosixPath(path).parts
        lower_parts = tuple(part.casefold() for part in parts)
        filename = parts[-1].casefold()
        inside_dist_info = path.startswith(root_prefix)
        dist_info_license = inside_dist_info and (
            "licenses" in lower_parts
            or filename.startswith(("license", "copying", "notice"))
        )

        wheel_license = False
        for index in range(len(parts) - 2):
            if lower_parts[index : index + 2] != ("licenses", "wheels"):
                continue
            packaged_name = _canonical_distribution_name(parts[index + 2])
            wheel_license = canonical_name is not None and packaged_name == canonical_name
            if wheel_license:
                break

        if dist_info_license or wheel_license:
            result.append(
                {
                    "path": fact["path"],
                    "sha256": fact["sha256"],
                    "size": fact["size"],
                }
            )
    return sorted(result, key=lambda item: str(item["path"]))


def _packaged_distributions(
    bundle: Path, file_facts: Sequence[dict[str, object]]
) -> list[dict[str, object]]:
    fact_by_path = _file_fact_map(file_facts)
    distributions: list[dict[str, object]] = []
    for dist_info_root in _distribution_roots(file_facts):
        metadata_key = f"{dist_info_root}/METADATA"
        metadata_fact = fact_by_path.get(metadata_key)
        name: str | None = None
        version: str | None = None
        metadata_output: dict[str, object] = {"available": False}
        if metadata_fact is not None:
            metadata_path = bundle / PurePosixPath(metadata_key)
            message = _metadata_message(metadata_path)
            name = message.get("Name")
            version = message.get("Version")
            metadata_output = {
                "available": True,
                "path": metadata_fact["path"],
                "sha256": metadata_fact["sha256"],
                "size": metadata_fact["size"],
            }

        wheel_key = f"{dist_info_root}/WHEEL"
        wheel_fact = fact_by_path.get(wheel_key)
        wheel_output: dict[str, object] = {"available": False}
        if wheel_fact is not None:
            wheel_output = {
                "available": True,
                **_wheel_fact(bundle / PurePosixPath(wheel_key), wheel_fact),
            }

        record_key = f"{dist_info_root}/RECORD"
        record_file_fact = fact_by_path.get(record_key)
        record_output: dict[str, object] = {"available": False}
        if record_file_fact is not None:
            record_output = _record_fact(
                bundle / PurePosixPath(record_key), record_file_fact
            )

        direct_url_key = f"{dist_info_root}/direct_url.json"
        distributions.append(
            {
                "canonical_name": (
                    _canonical_distribution_name(name) if name is not None else None
                ),
                "direct_url_metadata_present": direct_url_key in fact_by_path,
                "dist_info_path": dist_info_root,
                "license_files": _license_facts_for_distribution(
                    name, dist_info_root, file_facts
                ),
                "metadata": metadata_output,
                "name": name,
                "provenance_scope": (
                    "observed packaged .dist-info metadata and RECORD only; no "
                    "binary ownership conclusion"
                ),
                "record": record_output,
                "version": version,
                "wheel": wheel_output,
            }
        )

    distributions.sort(
        key=lambda item: (
            str(item["canonical_name"] or ""),
            str(item["version"] or ""),
            str(item["dist_info_path"]),
        )
    )
    return distributions


def collect_inventory(
    app_bundle: Path,
    *,
    runner: CommandRunner = _run_command,
    platform_name: str = sys.platform,
) -> dict[str, object]:
    if platform_name != "darwin":
        raise InventoryError("The macOS app inventory can run only on macOS")

    app_bundle = Path(app_bundle)
    if app_bundle.suffix.casefold() != ".app" or not app_bundle.is_dir():
        raise InventoryError("Input must be an existing macOS .app bundle")
    app_bundle = app_bundle.resolve()
    info_plist = app_bundle / "Contents" / "Info.plist"
    if not info_plist.is_file() or info_plist.is_symlink():
        raise InventoryError("App bundle has no regular Contents/Info.plist")

    regular_paths: list[Path] = []
    symlinks: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for path, entry_type in _iter_bundle_entries(app_bundle):
        relative = _canonical_bundle_path(app_bundle, path)
        collision_key = relative.casefold()
        if collision_key in seen_paths:
            raise InventoryError(f"Case-insensitive bundle path collision: {relative}")
        seen_paths.add(collision_key)
        if entry_type == "regular":
            regular_paths.append(path)
            continue
        raw_target = os.readlink(path)
        target = describe_symlink_target(
            app_bundle,
            path,
            raw_target,
            target_exists=path.exists(),
        )
        symlink_fact = {"path": relative, **target}
        symlinks.append(symlink_fact)
        if not target["confined_to_bundle"] or not target["target_exists"]:
            raise InventoryError(f"Unsafe or broken app symlink: {relative}")

    regular_files: list[dict[str, object]] = []
    macho_count = 0
    for path in sorted(
        regular_paths, key=lambda candidate: _canonical_bundle_path(app_bundle, candidate)
    ):
        fact = _regular_file_fact(app_bundle, path)
        if _is_macho(path):
            fact["mach_o"] = _macho_fact(path, runner)
            macho_count += 1
        regular_files.append(fact)
    symlinks.sort(key=lambda item: str(item["path"]))

    if macho_count == 0:
        raise InventoryError("No Mach-O regular file was found in the app bundle")

    identity = _plist_identity(info_plist)
    code_signing = _code_signing_fact(app_bundle, runner)
    return {
        "bundle": {
            "identity": identity,
            "info_plist_path": "Contents/Info.plist",
            "name": app_bundle.name,
        },
        "code_signing": code_signing,
        "counts": {
            "mach_o_files": macho_count,
            "packaged_distributions": len(_distribution_roots(regular_files)),
            "regular_files": len(regular_files),
            "symlinks": len(symlinks),
        },
        "generator": {
            "name": "generate_macos_app_inventory.py",
            "version": GENERATOR_VERSION,
        },
        "packaged_distributions": _packaged_distributions(app_bundle, regular_files),
        "purpose": (
            "observed app-bundle diagnostics only; not an SBOM, component ownership "
            "map, corresponding-source decision, legal conclusion, or distribution approval"
        ),
        "regular_files": regular_files,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "symlinks": symlinks,
    }


def write_inventory(payload: dict[str, object], output: Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    try:
        bundle = arguments.app_bundle.resolve()
        output = arguments.output.resolve()
        try:
            output.relative_to(bundle)
        except ValueError:
            pass
        else:
            raise InventoryError("Inventory output must remain outside the signed app bundle")
        payload = collect_inventory(bundle)
        write_inventory(payload, output)
    except InventoryError as exc:
        print(f"macOS app inventory failed: {exc}", file=sys.stderr)
        return 1
    print(f"macOS app inventory written: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
