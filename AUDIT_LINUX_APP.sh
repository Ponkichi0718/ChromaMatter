#!/usr/bin/env bash
# Fail-closed structural/native audit for the Linux x86_64 technical build.

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: AUDIT_LINUX_APP.sh APP_DIRECTORY [REPORT_FILE]" >&2
    exit 2
fi

APP_DIRECTORY="$1"
REPORT_FILE="${2:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

[[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]] || {
    echo "The Linux technical-build audit requires Linux x86_64." >&2
    exit 1
}
for command_name in file readelf ldd strings getconf patchelf realpath; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required Linux audit tool not found: $command_name" >&2
        exit 1
    }
done
HOST_GLIBC_VERSION="$(getconf GNU_LIBC_VERSION | awk '{print $2}')"
[[ -d "$APP_DIRECTORY" ]] || {
    echo "Application directory is missing: $APP_DIRECTORY" >&2
    exit 1
}

APP_DIRECTORY="$("$PYTHON_BIN" -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$APP_DIRECTORY")"
APP_EXECUTABLE="$APP_DIRECTORY/ChromaMatter"
BUNDLED_LIBRARY_ROOT="$APP_DIRECTORY/_internal"
[[ -x "$APP_EXECUTABLE" ]] || {
    echo "Packaged executable is missing or not executable: $APP_EXECUTABLE" >&2
    exit 1
}
[[ -d "$BUNDLED_LIBRARY_ROOT" ]] || {
    echo "Packaged internal library directory is missing: $BUNDLED_LIBRARY_ROOT" >&2
    exit 1
}

"$PYTHON_BIN" - "$APP_DIRECTORY" <<'PY'
from pathlib import Path
import os
import sys

root = Path(sys.argv[1]).resolve()
private_suffixes = {
    ".obj", ".glb", ".gltf", ".3mf", ".stl", ".ply", ".fbx", ".gcode"
}
for path in root.rglob("*"):
    if path.is_symlink():
        target = Path(os.path.realpath(path))
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise SystemExit(f"Symlink escapes package: {path} -> {target}") from exc
        if not target.exists():
            raise SystemExit(f"Broken symlink in package: {path} -> {target}")
        continue
    if not path.is_file():
        continue
    if path.name.casefold() == "direct_url.json":
        raise SystemExit(f"Private pip installation-origin metadata found: {path}")
    if path.suffix.casefold() in private_suffixes:
        raise SystemExit(f"Model or toolpath payload found in technical build: {path}")

needles = []
for value in (
    str(root),
    os.environ.get("GITHUB_WORKSPACE", ""),
    os.environ.get("RUNNER_TEMP", ""),
    os.environ.get("RUNNER_WORKSPACE", ""),
    os.environ.get("CHROMAMATTER_LINUX_BUILD_SOURCE_ROOT", ""),
    os.environ.get("CHROMAMATTER_LINUX_BUILD_OUTPUT_ROOT", ""),
    os.environ.get("CHROMAMATTER_LINUX_BUILD_PYTHON_PREFIX", ""),
    os.environ.get("CHROMAMATTER_LINUX_BUILD_BASE_PREFIX", ""),
    "C:\\Users\\",
):
    value = value.strip()
    if value in {"", "/", "/usr", "/usr/local", "/opt"}:
        continue
    if value not in needles:
        needles.append(value)

encoded = [(value, value.encode("utf-8")) for value in needles]
for path in root.rglob("*"):
    if not path.is_file() or path.is_symlink():
        continue
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"Cannot read package file for privacy audit: {path}: {exc}")
    for label, needle in encoded:
        if needle in payload:
            raise SystemExit(
                f"Build-host absolute path leaked into {path.relative_to(root)}: {label}"
            )
PY

for resource_name in \
    filament_color_database_2026-08.sqlite \
    filament_color_database_README.md \
    ATTRIBUTION.md \
    LICENSE_OPEN_FILAMENT_DATABASE.txt \
    LICENSE_CC_BY_4.0.txt; do
    resource_count="$(find "$APP_DIRECTORY" -type f -path "*/resources/filament_db/$resource_name" | wc -l | tr -d ' ')"
    [[ "$resource_count" == "1" ]] || {
        echo "Expected one filament resource $resource_name; found $resource_count" >&2
        exit 1
    }
done

if find "$APP_DIRECTORY" -path '*/licenses/native-closure/*' -print -quit | grep -q .; then
    echo "Windows-only native source closure was packaged into the Linux build." >&2
    exit 1
fi
if find "$APP_DIRECTORY" -path '*/licenses/macos/*' -print -quit | grep -q .; then
    echo "macOS-only distribution evidence was packaged into the Linux build." >&2
    exit 1
fi

wrapper_count="$(find "$APP_DIRECTORY" -type f -name 'PyfTetWildWrapper*.so' | wc -l | tr -d ' ')"
pytetwild_library_count="$(find "$APP_DIRECTORY" -type f -path '*/pytetwild.libs/*.so*' | wc -l | tr -d ' ')"
pymeshlab_plugin_count="$(find "$APP_DIRECTORY" -type f -path '*/pymeshlab/lib/plugins/*.so' | wc -l | tr -d ' ')"
[[ "$wrapper_count" == "1" ]] || {
    echo "Expected one PyTetWild Linux wrapper; found $wrapper_count" >&2
    exit 1
}
((pytetwild_library_count >= 2)) || {
    echo "Expected PyTetWild package-local shared libraries; found $pytetwild_library_count" >&2
    exit 1
}
((pymeshlab_plugin_count > 0)) || {
    echo "PyMeshLab Linux filter plugins were not collected." >&2
    exit 1
}

ELF_COUNT=0
while IFS= read -r -d '' candidate; do
    file_description="$(file -b "$candidate")"
    [[ "$file_description" == ELF* ]] || continue
    ELF_COUNT=$((ELF_COUNT + 1))
    [[ "$file_description" == *"ELF 64-bit LSB"* && "$file_description" == *"x86-64"* ]] || {
        echo "Non-x86_64 ELF file: $candidate ($file_description)" >&2
        exit 1
    }
    machine="$(readelf -h "$candidate" | awk -F: '/^[[:space:]]*Machine:/{gsub(/^[[:space:]]+/, "", $2); print $2; exit}')"
    [[ "$machine" == "Advanced Micro Devices X86-64" ]] || {
        echo "Unexpected ELF machine: $candidate ($machine)" >&2
        exit 1
    }

    search_path="$(patchelf --print-rpath "$candidate")"
    if [[ -n "$search_path" ]]; then
        IFS=':' read -r -a search_entries <<<"$search_path"
        for entry in "${search_entries[@]}"; do
            case "$entry" in
                '$ORIGIN'|'$ORIGIN/'*|'${ORIGIN}'|'${ORIGIN}/'*) ;;
                *)
                    echo "Non-package-relative ELF search path: $candidate ($entry)" >&2
                    exit 1
                    ;;
            esac
        done
    fi

    set +e
    # PyInstaller's Linux bootloader prepends `_internal` to LD_LIBRARY_PATH.
    # Reproduce that exact lookup here instead of auditing a nested wheel ELF
    # in an environment that the packaged application never uses.
    dependencies="$(
        env -u LD_PRELOAD -u LD_AUDIT LD_LIBRARY_PATH="$BUNDLED_LIBRARY_ROOT" \
            ldd "$candidate" 2>&1
    )"
    ldd_status=$?
    set -e
    if grep -q 'not found' <<<"$dependencies"; then
        echo "Unresolved ELF dependency: $candidate" >&2
        echo "$dependencies" >&2
        exit 1
    fi
    if ((ldd_status != 0)) && ! grep -Eq 'not a dynamic executable|statically linked' <<<"$dependencies"; then
        echo "ldd failed for $candidate" >&2
        echo "$dependencies" >&2
        exit 1
    fi
    while IFS= read -r resolved_dependency; do
        resolved_dependency="$(realpath "$resolved_dependency")"
        case "$resolved_dependency" in
            "$APP_DIRECTORY"/*|/lib/*|/lib64/*|/usr/lib/*|/usr/lib64/*) ;;
            *)
                echo "ELF dependency resolved outside package/system roots: $candidate -> $resolved_dependency" >&2
                exit 1
                ;;
        esac
    done < <(sed -nE 's/.*=> (\/[^ ]+) \(.*/\1/p' <<<"$dependencies")
done < <(find "$APP_DIRECTORY" -type f -print0)

((ELF_COUNT > 0)) || {
    echo "No ELF files found in Linux application directory." >&2
    exit 1
}

if [[ -n "$REPORT_FILE" ]]; then
    mkdir -p "$(dirname "$REPORT_FILE")"
    cat >"$REPORT_FILE" <<EOF
ChromaMatter Linux x86_64 technical-build audit
Application directory: $(basename "$APP_DIRECTORY")
In-app display version: 0.9
Build-host glibc: $HOST_GLIBC_VERSION
Dependency-wheel glibc floor: 2.35
Compatibility scope: validated on this build host; an Ubuntu 22.04 compatibility claim requires an Ubuntu 22.04 build and run
ELF files checked: $ELF_COUNT
ELF architecture: x86_64 only
Unresolved ELF dependencies: none
Build-host absolute path leakage: none found
PyTetWild wrapper files: $wrapper_count
PyTetWild package-local libraries: $pytetwild_library_count
PyMeshLab filter plugins: $pymeshlab_plugin_count
Symlink confinement: passed
Private model/toolpath payloads: none
pip direct_url.json files: none
Public or tester distribution approved: no
EOF
fi

echo "Linux technical-build audit passed: $ELF_COUNT x86_64 ELF files"
