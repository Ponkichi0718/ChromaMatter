#!/usr/bin/env bash
# Fail-closed structural/native audit for the Apple Silicon tester app.

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: AUDIT_MACOS_APP.sh APP_BUNDLE [REPORT_FILE]" >&2
    exit 2
fi

APP_BUNDLE="$1"
REPORT_FILE="${2:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

[[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]] || {
    echo "The macOS alpha audit requires an Apple Silicon macOS host." >&2
    exit 1
}
[[ -d "$APP_BUNDLE" ]] || { echo "App bundle is missing: $APP_BUNDLE" >&2; exit 1; }

APP_BUNDLE="$("$PYTHON_BIN" -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$APP_BUNDLE")"
INFO_PLIST="$APP_BUNDLE/Contents/Info.plist"
APP_EXECUTABLE="$APP_BUNDLE/Contents/MacOS/ChromaMatter"

[[ -f "$INFO_PLIST" ]] || { echo "Info.plist is missing." >&2; exit 1; }
[[ -x "$APP_EXECUTABLE" ]] || { echo "App executable is missing or not executable." >&2; exit 1; }

plutil -lint "$INFO_PLIST"
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST")" == \
    "io.github.ponkichi0718.chromamatter.alpha" ]]
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$INFO_PLIST")" == \
    "0.8.0" ]]
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleGetInfoString' "$INFO_PLIST")" == \
    "ChromaMatter 0.8beta macOS alpha" ]]
[[ "$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$INFO_PLIST")" == \
    "15.0" ]]

codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
SIGNATURE_DETAILS="$(codesign -dv --verbose=4 "$APP_BUNDLE" 2>&1)"
grep -q 'Signature=adhoc' <<<"$SIGNATURE_DETAILS" || {
    echo "Expected an ad-hoc signed tester bundle, not a release signature." >&2
    exit 1
}

"$PYTHON_BIN" - "$APP_BUNDLE" <<'PY'
from pathlib import Path
import os
import sys

bundle = Path(sys.argv[1]).resolve()
for link in bundle.rglob("*"):
    if not link.is_symlink():
        continue
    target = Path(os.path.realpath(link))
    try:
        target.relative_to(bundle)
    except ValueError as exc:
        raise SystemExit(f"Symlink escapes app bundle: {link} -> {target}") from exc
    if not target.exists():
        raise SystemExit(f"Broken symlink in app bundle: {link} -> {target}")

private_suffixes = {
    ".obj", ".glb", ".gltf", ".3mf", ".stl", ".ply", ".fbx", ".gcode"
}
for path in bundle.rglob("*"):
    if not path.is_file():
        continue
    if path.name.casefold() == "direct_url.json":
        raise SystemExit(f"Private pip installation origin metadata found: {path}")
    if path.suffix.casefold() in private_suffixes:
        raise SystemExit(f"Model or toolpath payload found in alpha app: {path}")
PY

for resource_name in \
    filament_color_database_2026-08.sqlite \
    filament_color_database_README.md \
    ATTRIBUTION.md \
    LICENSE_OPEN_FILAMENT_DATABASE.txt \
    LICENSE_CC_BY_4.0.txt; do
    resource_count="$(find "$APP_BUNDLE" -type f -path "*/resources/filament_db/$resource_name" | wc -l | tr -d ' ')"
    [[ "$resource_count" == "1" ]] || {
        echo "Expected one packaged filament resource $resource_name; found $resource_count" >&2
        exit 1
    }
done

for notice_name in \
    MACOS_ALPHA_COMPLIANCE_NOTICE_EN.txt \
    MACOS_ALPHA_COMPLIANCE_NOTICE_JA.txt; do
    notice_count="$(find "$APP_BUNDLE" -type f -name "$notice_name" | wc -l | tr -d ' ')"
    [[ "$notice_count" == "1" ]] || {
        echo "Expected one packaged macOS alpha notice $notice_name; found $notice_count" >&2
        exit 1
    }
done

if find "$APP_BUNDLE" -path '*/licenses/native-closure/*' -print -quit | grep -q .; then
    echo "Windows-only native source closure was packaged into the macOS alpha." >&2
    exit 1
fi

wrapper_count="$(find "$APP_BUNDLE" -type f -name 'PyfTetWildWrapper*.so' | wc -l | tr -d ' ')"
gmp_count="$(find "$APP_BUNDLE" -type f -path '*/pytetwild/.dylibs/libgmp.10.dylib' | wc -l | tr -d ' ')"
plugin_count="$(find "$APP_BUNDLE" -type f -path '*/pymeshlab/PlugIns/*' | wc -l | tr -d ' ')"
[[ "$wrapper_count" == "1" ]] || {
    echo "Expected one packaged PyTetWild .so wrapper; found $wrapper_count" >&2
    exit 1
}
[[ "$gmp_count" == "1" ]] || {
    echo "Expected pytetwild/.dylibs/libgmp.10.dylib; found $gmp_count" >&2
    exit 1
}
((plugin_count > 0)) || {
    echo "PyMeshLab PlugIns were not collected by the standard PyInstaller hook." >&2
    exit 1
}

MACHO_COUNT=0
while IFS= read -r -d '' candidate; do
    file_description="$(file -b "$candidate")"
    [[ "$file_description" == Mach-O* ]] || continue
    MACHO_COUNT=$((MACHO_COUNT + 1))
    architectures="$(lipo -archs "$candidate")"
    [[ "$architectures" == "arm64" ]] || {
        echo "Non-arm64-only Mach-O: $candidate ($architectures)" >&2
        exit 1
    }

    while IFS= read -r dependency; do
        dependency="${dependency#${dependency%%[![:space:]]*}}"
        dependency="${dependency%% (*}"
        [[ -n "$dependency" ]] || continue
        case "$dependency" in
            @rpath/*|@loader_path/*|@executable_path/*|/System/Library/*|/usr/lib/*)
                ;;
            *)
                echo "Non-relocatable Mach-O dependency: $candidate -> $dependency" >&2
                exit 1
                ;;
        esac
    done < <(otool -L "$candidate" | tail -n +2)
done < <(find "$APP_BUNDLE" -type f -print0)

((MACHO_COUNT > 0)) || { echo "No Mach-O files found in app bundle." >&2; exit 1; }

if [[ -n "$REPORT_FILE" ]]; then
    mkdir -p "$(dirname "$REPORT_FILE")"
    cat >"$REPORT_FILE" <<EOF
ChromaMatter macOS alpha app audit
Bundle: $(basename "$APP_BUNDLE")
Bundle identifier: io.github.ponkichi0718.chromamatter.alpha
Bundle short version: 0.8.0
In-app display version: 0.8beta
Minimum macOS: 15.0
Mach-O files checked: $MACHO_COUNT
Mach-O architecture: arm64 only
Mach-O build-host absolute dependencies: none
PyTetWild wrapper files: $wrapper_count
PyTetWild package-local GMP libraries: $gmp_count
PyMeshLab PlugIn files: $plugin_count
Symlink confinement: passed
Private model/toolpath payloads: none
pip direct_url.json files: none
Code signature: ad-hoc only (not Developer ID)
Apple notarization: not performed
Public Release eligibility: no
EOF
fi

echo "macOS alpha app audit passed: $MACHO_COUNT arm64 Mach-O files"
