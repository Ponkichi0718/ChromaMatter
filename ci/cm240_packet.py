"""Create/verify a reviewable full source packet. This script never uploads it."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile

NATIVE_ROOTS = {"src", "deps", "deps_src", "resources", "localization", "cmake"}
NATIVE_FILES = {"CMakeLists.txt", "version.inc", "LICENSE.txt", "build_release_macos.sh"}
EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", "build", "dist", "venv", ".venv", "CMakeFiles", "DL_CACHE", "logs", "verification"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".exe", ".dll", ".pyd", ".pdb", ".obj", ".o", ".a", ".lib", ".log", ".dmp", ".gcode"}
PRIVATE_NAMES = re.compile(r"(?:^|[_-])(?:handoff|progress|report|result|status|receipt|provenance)(?:[_\-.]|$)", re.I)
PRIVATE_CONTENT = re.compile(rb"(?:[C-Z]:[/\\](?:Users|Dev)[/\\]|github_pat_[A-Za-z0-9_]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)", re.I)
HELPER_NOTICE_FILES = {"vendor-manifest.json", "license-manifest.json", "THIRD_PARTY_NOTICES.md", "LICENSE"}
HELPER_ASSETS = {"vendor/assets/mixer_model.npz", "vendor/assets/mixer_model_PROVENANCE.md"}
MODEL_SUFFIXES = {".3mf", ".glb", ".gltf", ".stl", ".obj", ".step", ".stp"}
# Exact stock 2.4.0 bytes: an upstream SVG's authoring path, literal PEM header
# recognizers, and a comment describing path redaction. They are not user data
# or credentials. Any subsequent change must be reviewed again.
REVIEWED_STOCK_MATCHES = {
    "native/resources/profiles/Ratrig/ratrig_logo.svg": "172c474882a6f094fefc0b0ac4ff5b0a508d390c75ab364057b55a18c57d2831",
    "native/src/slic3r/Utils/MoonRaker.cpp": "bccb081e3af99bce256a5499a2a2c2b6b36d2abf5880b65f68a49ecefa82e7b0",
    "native/src/slic3r/Utils/SnapLogClient.hpp": "a4398ad616a1f28fd6e8f9626f4362bcba69a91cf669122f5f49faab89d73e57",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def selected(root, kind):
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        name = relative.as_posix()
        if any(part in EXCLUDE_DIRS for part in relative.parts):
            continue
        if not path.is_file():
            continue
        if path.is_symlink():
            raise RuntimeError("Symlink requires review: " + kind + "/" + name)
        if path.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        if kind == "native":
            if name not in NATIVE_FILES and relative.parts[0] not in NATIVE_ROOTS:
                continue
            if path.name in {"AGENTS.md", "CLAUDE.md"} or PRIVATE_NAMES.search(path.name):
                continue
            # Stock rendering resources (e.g. printer beds) remain necessary.
            # User models elsewhere are not part of a native build.
            if path.suffix.lower() in MODEL_SUFFIXES and relative.parts[0] != "resources":
                continue
        else:
            is_notice = relative.parts[0] == "licenses" or name in HELPER_NOTICE_FILES or name in HELPER_ASSETS
            is_module = path.suffix == ".py" and not path.name.startswith(("test_", "build_", "verify_", "collect_"))
            if not is_notice and not is_module:
                continue
            if PRIVATE_NAMES.search(path.name) and name not in HELPER_ASSETS:
                continue
            if path.suffix.lower() in MODEL_SUFFIXES:
                continue
        yield path, name


def create(args):
    roots = [(args.native.resolve(strict=True), "native"),
             ((args.helpers / "importer").resolve(strict=True), "helpers/importer"),
             ((args.helpers / "editor").resolve(strict=True), "helpers/editor")]
    records, payload, blocked = [], [], []
    # Optional local-only markers are never recorded in packets or logs.
    markers = [value.encode() for value in os.environ.get("CM_PACKET_PRIVATE_MARKERS", "").split("\x1f") if value]
    for root, prefix in roots:
        for path, relative in selected(root, "native" if prefix == "native" else "helper"):
            data = path.read_bytes()
            member = prefix + "/" + relative
            if ((PRIVATE_CONTENT.search(data) and REVIEWED_STOCK_MATCHES.get(member) != sha256(data))
                    or any(marker.lower() in data.lower() for marker in markers)):
                blocked.append(member)
            records.append({"path": member, "bytes": len(data), "sha256": sha256(data)})
            payload.append((path, member))
    summary = {"file_count": len(records), "bytes": sum(item["bytes"] for item in records),
               "blocked_files": blocked, "archive_created": False}
    print(json.dumps(summary, indent=2))
    if blocked:
        raise RuntimeError("Private-path/credential-pattern scan failed; no archive created")
    if args.scan_only:
        return
    if args.output is None:
        raise RuntimeError("--output is required unless --scan-only is specified")
    if args.output.exists():
        raise RuntimeError("Refusing to overwrite the source packet")
    manifest = {"schema": "chromamatter.cm240.full-source.v1", "upstream": "https://github.com/Snapmaker/OrcaSlicer",
                "upstream_commit": "b1831e5dcb464172de33783142425aafda834fbc", "snapshot": "Window1-2.4.0-fillfix-POSIX",
                "version": "2.4.0 / 01.10.01.50", "file_count": len(records), "files": records,
                "scope": "Native build inputs and matching helper sources; no user models, local logs, profiles, or SDKs",
                "mac_build_completed": False, "mac_gui_verified": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream, tarfile.open(fileobj=stream, mode="w:gz", compresslevel=6) as archive:
        for (path, member), record in zip(payload, records):
            data = path.read_bytes()
            if sha256(data) != record["sha256"]:
                raise RuntimeError("Source changed while packaging: " + member)
            info = tarfile.TarInfo(member)
            # Windows copies lose POSIX executable bits. Restore script modes
            # from their explicit interpreter marker or shell-file extension.
            mode = 0o755 if data.startswith(b"#!") or path.suffix in {".sh", ".command"} else 0o644
            info.size, info.mode, info.mtime = len(data), mode, 0
            archive.addfile(info, io.BytesIO(data))
        data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
        info = tarfile.TarInfo("SOURCE_MANIFEST.json")
        info.size, info.mode, info.mtime = len(data), 0o644, 0
        archive.addfile(info, io.BytesIO(data))
    with args.output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    print(json.dumps({"archive": args.output.name, "bytes": args.output.stat().st_size, "sha256": digest}))


def extract(args):
    destination = args.destination.resolve(strict=True)
    with tarfile.open(args.archive, "r:gz") as archive:
        members = archive.getmembers()
        names = set()
        for member in members:
            relative = PurePosixPath(member.name)
            if not member.isfile() or relative.is_absolute() or ".." in relative.parts or "\\" in member.name:
                raise RuntimeError("Unexpected archive member")
            if member.name in names or (relative.parts[0] not in {"native", "helpers"} and member.name != "SOURCE_MANIFEST.json"):
                raise RuntimeError("Duplicate or unapproved archive member")
            names.add(member.name)
            if (destination / member.name).exists():
                raise RuntimeError("Extraction target already exists")
        manifest = json.load(archive.extractfile("SOURCE_MANIFEST.json"))
        if manifest.get("schema") != "chromamatter.cm240.full-source.v1":
            raise RuntimeError("Unexpected manifest schema")
        expected = {row["path"]: row for row in manifest["files"]}
        if (set(expected) != names - {"SOURCE_MANIFEST.json"}
                or len(expected) != manifest["file_count"] or len(expected) != len(manifest["files"])):
            raise RuntimeError("Manifest inventory mismatch")
        for member in members:
            if member.name == "SOURCE_MANIFEST.json":
                continue
            data = archive.extractfile(member).read()
            record = expected[member.name]
            if len(data) != record["bytes"] or sha256(data) != record["sha256"]:
                raise RuntimeError("Source hash mismatch: " + member.name)
        archive.extractall(destination, filter="data")
    print("Verified and extracted", manifest["file_count"], "source files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("create")
    pack.add_argument("--native", type=Path, required=True)
    pack.add_argument("--helpers", type=Path, required=True)
    pack.add_argument("--output", type=Path)
    pack.add_argument("--scan-only", action="store_true")
    unpack = sub.add_parser("extract")
    unpack.add_argument("--archive", type=Path, required=True)
    unpack.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    (create if args.command == "create" else extract)(args)


if __name__ == "__main__":
    main()
