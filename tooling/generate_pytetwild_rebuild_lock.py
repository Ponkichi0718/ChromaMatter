#!/usr/bin/env python3
"""Generate and verify a production PyTetWild controlled-rebuild lock.

The blocked template remains historical guidance only.  This tool derives a
new ``verified-controlled-rebuild`` lock from the actual build attestation and
release inputs, writes it to a private temporary file, and asks
``stage_corresponding_source`` to validate that candidate with the exact same
validator used for release staging.  The requested output is published only
after that validation succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from types import ModuleType
from typing import Any


TOOL_VERSION = 1
OUTPUT_FILENAME = "pytetwild-rebuild-lock.json"
TOOLING_ROOT = Path(__file__).resolve().parent
DEFAULT_COMPONENT_MANIFEST = TOOLING_ROOT / "corresponding_source_components.json"
VALIDATOR_PATH = TOOLING_ROOT / "stage_corresponding_source.py"
NANOBIND_SOURCE_URL = "https://github.com/wjakob/nanobind.git"
NANOBIND_REQUIRED_PATHS = (
    "LICENSE",
    "CMakeLists.txt",
    "include/nanobind/nanobind.h",
)


def _load_validator() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "chromamatter_stage_corresponding_source_for_rebuild_lock",
        VALIDATOR_PATH,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load corresponding-source validator: {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


stage_tool = _load_validator()


def _absolute(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _bound_file(path: Path, label: str, validator: ModuleType) -> dict[str, str]:
    if not path.is_file() or validator._is_link_like(path):
        raise validator.StageError(f"{label} is missing or linked: {path}")
    validator._safe_leaf(path.name, f"{label}.filename")
    return {"filename": path.name, "sha256": validator._hash_file(path)}


def _manifest_template(
    manifest: dict[str, Any],
    manifest_path: Path,
    validator: ModuleType,
    rebuild_template_payload: bytes | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validator.validate_component_manifest(manifest)
    policy = manifest.get("pytetwild_rebuild_policy")
    if not isinstance(policy, dict):
        raise validator.StageError("Manifest has no PyTetWild rebuild policy")
    component = next(
        (
            item
            for item in manifest["components"]
            if item.get("id") == policy.get("component")
        ),
        None,
    )
    if component is None:
        raise validator.StageError("Manifest PyTetWild rebuild component is missing")
    relative_template = validator._safe_relative(
        policy.get("template"),
        "pytetwild_rebuild_policy.template",
    )
    template_path = manifest_path.parent.joinpath(
        *PurePosixPath(relative_template).parts
    ).resolve()
    manifest_root = manifest_path.parent.resolve()
    if not validator._is_relative_to(template_path, manifest_root):
        raise validator.StageError("PyTetWild rebuild template escaped the manifest directory")
    if not template_path.is_file() or validator._is_link_like(template_path):
        raise validator.StageError("PyTetWild rebuild template is missing or linked")
    if rebuild_template_payload is None:
        template = validator._json_load(template_path)
    else:
        template = validator._json_load_bytes(
            rebuild_template_payload,
            template_path.name,
        )
    validator._validate_blocked_rebuild_template_data(template, component["commit"])
    template_nanobind = template.get("nanobind")
    if not isinstance(template_nanobind, dict) or (
        template_nanobind.get("source_url") != NANOBIND_SOURCE_URL
        or template_nanobind.get("required_paths") != list(NANOBIND_REQUIRED_PATHS)
    ):
        raise validator.StageError(
            "Blocked PyTetWild template nanobind source requirements have drifted"
        )
    return policy, component, template


def _candidate_lock(
    *,
    manifest: dict[str, Any],
    manifest_path: Path,
    repaired_wheel: Path,
    build_recipe: Path,
    build_requirements: Path,
    source_patch: Path,
    build_attestation: Path,
    application_requirements_lock: Path,
    validator: ModuleType,
    rebuild_template_payload: bytes | None = None,
) -> dict[str, Any]:
    _policy, component, template = _manifest_template(
        manifest,
        manifest_path,
        validator,
        rebuild_template_payload,
    )
    attestation = validator._json_load(build_attestation)
    environment = attestation.get("environment")
    sources = attestation.get("sources")
    if not isinstance(environment, dict) or not isinstance(sources, dict):
        raise validator.StageError(
            "PyTetWild build attestation lacks environment or source evidence"
        )
    missing_environment = sorted(
        validator.PYTETWILD_LOCK_ENVIRONMENT_FIELDS - set(environment)
    )
    if missing_environment:
        raise validator.StageError(
            "PyTetWild build attestation lacks lock environment fields: "
            f"{missing_environment}"
        )
    for field in ("nanobind_commit",):
        if field not in sources:
            raise validator.StageError(
                f"PyTetWild build attestation lacks sources.{field}"
            )

    wheel = {
        **_bound_file(repaired_wheel, "repaired wheel", validator),
        "python_tag": template["wheel"]["python_tag"],
        "abi_tag": template["wheel"]["abi_tag"],
        "platform_tag": template["wheel"]["platform_tag"],
    }
    return {
        "schema_version": 1,
        "lock_status": "verified-controlled-rebuild",
        "scope": "prospective-rebuild-only",
        "historical_wheel": dict(template["historical_wheel"]),
        "pytetwild": {
            "version": component["version"],
            "commit": component["commit"],
        },
        "ftetwild": {"commit": template["ftetwild"]["commit"]},
        "wheel": wheel,
        "nanobind": {
            "version": environment["nanobind_version"],
            "source_url": NANOBIND_SOURCE_URL,
            "commit": sources["nanobind_commit"],
            "required_paths": list(NANOBIND_REQUIRED_PATHS),
        },
        "build_recipe": _bound_file(build_recipe, "build recipe", validator),
        "build_requirements_lock": _bound_file(
            build_requirements,
            "build requirements lock",
            validator,
        ),
        "source_patch": _bound_file(source_patch, "source patch", validator),
        "environment": {
            field: environment[field]
            for field in sorted(validator.PYTETWILD_LOCK_ENVIRONMENT_FIELDS)
        },
        "attestation": _bound_file(
            build_attestation,
            "build attestation",
            validator,
        ),
        "release_binding": _bound_file(
            application_requirements_lock,
            "application requirements lock",
            validator,
        ),
    }


def generate_rebuild_lock(
    *,
    output: str | os.PathLike[str],
    component_manifest: str | os.PathLike[str],
    project_repository: str | os.PathLike[str],
    project_commit: str,
    repaired_wheel: str | os.PathLike[str],
    raw_wheel: str | os.PathLike[str],
    audit_logs: str | os.PathLike[str],
    build_recipe: str | os.PathLike[str],
    build_requirements: str | os.PathLike[str],
    source_patch: str | os.PathLike[str],
    build_attestation: str | os.PathLike[str],
    application_requirements_lock: str | os.PathLike[str],
    validator: ModuleType | None = None,
) -> dict[str, Any]:
    """Generate, validate, and atomically publish one rebuild lock."""

    validator = validator or stage_tool
    output_path = _absolute(output)
    if output_path.name != OUTPUT_FILENAME:
        raise validator.StageError(
            f"Output filename must be exactly {OUTPUT_FILENAME}"
        )
    validator._assert_plain_directory(output_path.parent, "output directory")
    if output_path.exists() or validator._is_link_like(output_path):
        raise validator.StageError(f"Refusing to overwrite rebuild lock: {output_path}")
    if not isinstance(project_commit, str) or not validator.SHA1_RE.fullmatch(
        project_commit
    ):
        raise validator.StageError("project_commit must be a full lowercase commit")

    paths = {
        "component_manifest": _absolute(component_manifest),
        "project_repository": _absolute(project_repository),
        "repaired_wheel": _absolute(repaired_wheel),
        "raw_wheel": _absolute(raw_wheel),
        "audit_logs": _absolute(audit_logs),
        "build_recipe": _absolute(build_recipe),
        "build_requirements": _absolute(build_requirements),
        "source_patch": _absolute(source_patch),
        "build_attestation": _absolute(build_attestation),
        "application_requirements_lock": _absolute(
            application_requirements_lock
        ),
    }
    if output_path in paths.values():
        raise validator.StageError("Output path must not alias a release input")
    if not paths["component_manifest"].is_file() or validator._is_link_like(
        paths["component_manifest"]
    ):
        raise validator.StageError("Component manifest is missing or linked")
    validator._assert_plain_directory(
        paths["project_repository"],
        "project repository",
    )

    manifest, _external_lock, release_input_evidence = (
        validator._verify_release_input_project_bindings(
            paths["component_manifest"],
            paths["project_repository"],
            project_commit,
            bind_external_lock=False,
        )
    )
    rebuild_template_evidence = release_input_evidence.get(
        "pytetwild_rebuild_template"
    )
    candidate = _candidate_lock(
        manifest=manifest,
        manifest_path=paths["component_manifest"],
        repaired_wheel=paths["repaired_wheel"],
        build_recipe=paths["build_recipe"],
        build_requirements=paths["build_requirements"],
        source_patch=paths["source_patch"],
        build_attestation=paths["build_attestation"],
        application_requirements_lock=paths["application_requirements_lock"],
        validator=validator,
        rebuild_template_payload=(
            rebuild_template_evidence["payload"]
            if rebuild_template_evidence is not None
            else None
        ),
    )

    payload = (json.dumps(candidate, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    expected_output_sha256 = hashlib.sha256(payload).hexdigest()
    temporary_path: Path | None = None
    published_sha256: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="xb",
            prefix=f".{OUTPUT_FILENAME}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)

        arguments = argparse.Namespace(
            pytetwild_rebuild_lock=str(temporary_path),
            pytetwild_wheel=str(paths["repaired_wheel"]),
            pytetwild_raw_wheel=str(paths["raw_wheel"]),
            pytetwild_audit_logs=str(paths["audit_logs"]),
            pytetwild_build_recipe=str(paths["build_recipe"]),
            pytetwild_build_requirements=str(paths["build_requirements"]),
            pytetwild_source_patch=str(paths["source_patch"]),
            pytetwild_build_attestation=str(paths["build_attestation"]),
            application_requirements_lock=str(
                paths["application_requirements_lock"]
            ),
        )
        validator._prepare_pytetwild_rebuild(
            manifest,
            paths["component_manifest"],
            arguments,
            project_repository=paths["project_repository"],
            project_commit=project_commit,
            rebuild_template_payload=(
                rebuild_template_evidence["payload"]
                if rebuild_template_evidence is not None
                else None
            ),
        )

        # A hard link provides no-overwrite publication semantics on the same
        # volume.  The validated temporary name is then removed, leaving the
        # exact verified inode at the requested canonical path.
        try:
            os.link(temporary_path, output_path)
        except FileExistsError as exc:
            raise validator.StageError(
                f"Refusing to overwrite rebuild lock: {output_path}"
            ) from exc
        except OSError as exc:
            raise validator.StageError(
                f"Cannot publish validated rebuild lock atomically: {exc}"
            ) from exc
        try:
            published_sha256 = validator._hash_file(output_path)
            if published_sha256 != expected_output_sha256:
                raise validator.StageError(
                    "Published PyTetWild rebuild lock changed during atomic publication"
                )
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
        try:
            temporary_path.unlink()
        except OSError:
            output_path.unlink(missing_ok=True)
            raise
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {
        "schema_version": TOOL_VERSION,
        "status": candidate["lock_status"],
        "filename": output_path.name,
        "sha256": published_sha256,
        "audit_log_count": len(validator.PYTETWILD_AUDIT_LOG_FILES),
        "project_commit": project_commit,
        "wheel": dict(candidate["wheel"]),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a fail-closed PyTetWild controlled-rebuild lock and "
            "verify it with the corresponding-source staging validator."
        )
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--component-manifest",
        default=str(DEFAULT_COMPONENT_MANIFEST),
    )
    parser.add_argument("--project-repository", required=True)
    parser.add_argument("--project-commit", required=True)
    parser.add_argument("--repaired-wheel", required=True)
    parser.add_argument("--raw-wheel", required=True)
    parser.add_argument("--audit-logs", required=True)
    parser.add_argument("--build-recipe", required=True)
    parser.add_argument("--build-requirements", required=True)
    parser.add_argument("--source-patch", required=True)
    parser.add_argument("--build-attestation", required=True)
    parser.add_argument("--application-requirements-lock", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = generate_rebuild_lock(
            output=arguments.output,
            component_manifest=arguments.component_manifest,
            project_repository=arguments.project_repository,
            project_commit=arguments.project_commit,
            repaired_wheel=arguments.repaired_wheel,
            raw_wheel=arguments.raw_wheel,
            audit_logs=arguments.audit_logs,
            build_recipe=arguments.build_recipe,
            build_requirements=arguments.build_requirements,
            source_patch=arguments.source_patch,
            build_attestation=arguments.build_attestation,
            application_requirements_lock=arguments.application_requirements_lock,
        )
    except stage_tool.StageError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
