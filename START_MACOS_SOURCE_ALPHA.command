#!/usr/bin/env bash
# ChromaMatter Apple Silicon / macOS 15+ source-alpha launcher.
#
# This launcher deliberately runs the reviewed source tree. It does not fetch
# or unpack an application ZIP, change Gatekeeper settings, install with sudo,
# sign an app, notarize an app, or bypass the separate packaged-app release
# gate.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
FIXED_APP="$SCRIPT_DIR/source/fixed_app"
ENTRYPOINT="$FIXED_APP/TripoSpectrumMapper_fixed.py"
RUNTIME_LOCK="$FIXED_APP/requirements-runtime-macos-arm64.lock"
GLB_GENERATOR="$SCRIPT_DIR/samples/generate_macos_alpha_test_glb.py"

PYTHON_VERSION_REQUIRED="3.13.14"
SOURCE_ALPHA_TAG="0.9-macos-source-app"
PYTHON_INSTALLER_URL="https://www.python.org/ftp/python/3.13.14/python-3.13.14-macos11.pkg"
PYTHON_INSTALLER_SHA256="8e58affb218c155a1dfdc27b291f817129669f8760e7a297adb2e4439ba5d2e8"
PUBLIC_GLB_SHA256="1b6092448e62a93f5e29a9c6dda1265a7a2179c2eacd293f7d8f02d1f268c563"

SELF_TEST_ONLY=0

usage() {
    cat <<'EOF'
Usage: START_MACOS_SOURCE_ALPHA.command [--self-test-only]

  --self-test-only  Prepare the private runtime, generate the public CC0 GLB,
                    and run the native/render gate without opening the GUI.

CI-only environment overrides:
  CHROMAMATTER_PYTHON     Exact native arm64 CPython 3.13.14 executable.
  CHROMAMATTER_ALPHA_HOME Absolute private runtime/data root.
EOF
}

while (($#)); do
    case "$1" in
        --self-test-only)
            SELF_TEST_ONLY=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

DEFAULT_SUPPORT_ROOT="${HOME:?HOME is not set}/Library/Application Support/ChromaMatter Source Alpha"
SUPPORT_ROOT="${CHROMAMATTER_ALPHA_HOME:-$DEFAULT_SUPPORT_ROOT}"
CACHE_DIR="$SUPPORT_ROOT/Cache"
PROFILE_DIR="$SUPPORT_ROOT/Profile"
TEST_DATA_DIR="$SUPPORT_ROOT/TestData"
VALIDATION_DIR="$SUPPORT_ROOT/Validation"
VENV_DIR="$SUPPORT_ROOT/venv-$PYTHON_VERSION_REQUIRED"
INSTALLER_PATH="$CACHE_DIR/python-$PYTHON_VERSION_REQUIRED-macos11.pkg"
PUBLIC_GLB="$TEST_DATA_DIR/ChromaMatter-Public-Four-Color-Test.glb"
SELF_TEST_JSON="$VALIDATION_DIR/macos-alpha-self-test.json"

TEMP_DOWNLOAD=""
TEMP_VENV=""

cleanup() {
    if [[ -n "$TEMP_DOWNLOAD" && -f "$TEMP_DOWNLOAD" ]]; then
        case "$TEMP_DOWNLOAD" in
            "$CACHE_DIR"/.python-download.*) rm -f -- "$TEMP_DOWNLOAD" ;;
        esac
    fi
    if [[ -n "$TEMP_VENV" && -d "$TEMP_VENV" ]]; then
        case "$TEMP_VENV" in
            "$SUPPORT_ROOT"/.venv-build.*) rm -rf -- "$TEMP_VENV" ;;
        esac
    fi
}
trap cleanup EXIT

fail() {
    printf '\nChromaMatter source alpha could not start:\n%s\n' "$1" >&2
    printf 'The existing application and your model files were not changed.\n' >&2
    exit 1
}

require_file() {
    [[ -f "$1" && ! -L "$1" ]] || fail "Required source file is missing or is a symbolic link: $1"
}

python_matches_alpha() {
    local candidate="$1"
    [[ -x "$candidate" ]] || return 1
    "$candidate" - <<'PY' >/dev/null 2>&1
import platform
import sys

raise SystemExit(
    0
    if sys.version_info[:3] == (3, 13, 14) and platform.machine() == "arm64"
    else 1
)
PY
}

find_python() {
    local candidate=""
    if [[ -n "${CHROMAMATTER_PYTHON:-}" ]]; then
        python_matches_alpha "$CHROMAMATTER_PYTHON" ||
            fail "CHROMAMATTER_PYTHON must be native arm64 CPython 3.13.14."
        "$CHROMAMATTER_PYTHON" -c 'import os, sys; print(os.path.realpath(sys.executable))'
        return 0
    fi
    local -a candidates=(
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"
        "/usr/local/bin/python3.13"
    )
    if command -v python3.13 >/dev/null 2>&1; then
        candidates+=("$(command -v python3.13)")
    fi
    for candidate in "${candidates[@]}"; do
        if python_matches_alpha "$candidate"; then
            "$candidate" -c 'import os, sys; print(os.path.realpath(sys.executable))'
            return 0
        fi
    done
    return 1
}

download_verified_python_installer() {
    local actual_sha256=""
    mkdir -p -- "$CACHE_DIR"

    if [[ -f "$INSTALLER_PATH" && ! -L "$INSTALLER_PATH" ]]; then
        actual_sha256="$(shasum -a 256 "$INSTALLER_PATH" | awk '{print $1}')"
        if [[ "$actual_sha256" == "$PYTHON_INSTALLER_SHA256" ]]; then
            pkgutil --check-signature "$INSTALLER_PATH" >/dev/null
            return 0
        fi
    fi

    TEMP_DOWNLOAD="$(mktemp "$CACHE_DIR/.python-download.XXXXXX")"
    printf '\nDownloading the official CPython %s installer...\n' "$PYTHON_VERSION_REQUIRED"
    curl \
        --proto '=https' \
        --tlsv1.2 \
        --fail \
        --location \
        --show-error \
        --output "$TEMP_DOWNLOAD" \
        "$PYTHON_INSTALLER_URL"

    actual_sha256="$(shasum -a 256 "$TEMP_DOWNLOAD" | awk '{print $1}')"
    [[ "$actual_sha256" == "$PYTHON_INSTALLER_SHA256" ]] || \
        fail "The downloaded Python installer SHA-256 did not match Python.org."
    pkgutil --check-signature "$TEMP_DOWNLOAD" >/dev/null || \
        fail "macOS did not accept the Python installer signature."

    mv -f -- "$TEMP_DOWNLOAD" "$INSTALLER_PATH"
    TEMP_DOWNLOAD=""
}

install_python_interactively() {
    download_verified_python_installer
    cat <<'EOF'

Python 3.13.14 is required and was not found.
The verified official Python.org installer will now open.

1. Complete the normal macOS Installer screens.
2. Return to this Terminal window.
3. Press Return to continue ChromaMatter setup.

ChromaMatter does not enter your password, use sudo, or disable macOS security.
EOF
    open "$INSTALLER_PATH"
    read -r -p "Press Return after Python installation is complete: " _answer
}

venv_matches_lock() {
    local lock_sha256="$1"
    local marker="$VENV_DIR/.chromamatter-runtime-lock.sha256"
    [[ -x "$VENV_DIR/bin/python" && -f "$marker" && ! -L "$VENV_DIR" ]] || return 1
    python_matches_alpha "$VENV_DIR/bin/python" || return 1
    [[ "$(tr -d '\r\n' <"$marker")" == "$lock_sha256" ]] || return 1
    "$VENV_DIR/bin/python" - "$RUNTIME_LOCK" <<'PY' >/dev/null 2>&1 || return 1
import importlib.metadata
from pathlib import Path
import re
import sys

lock = Path(sys.argv[1]).read_text(encoding="utf-8")
expected = dict(
    re.findall(r"(?m)^([A-Za-z0-9._-]+)==([^ \\]+) \\$", lock)
)
if not expected:
    raise SystemExit(1)
for name, version in expected.items():
    try:
        installed = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        raise SystemExit(1)
    if installed != version:
        raise SystemExit(1)
PY
    "$VENV_DIR/bin/python" -m pip check >/dev/null 2>&1
}

build_runtime_venv() {
    local base_python="$1"
    local lock_sha256="$2"
    local marker=""

    TEMP_VENV="$SUPPORT_ROOT/.venv-build.$$"
    [[ ! -e "$TEMP_VENV" ]] || fail "Temporary environment path already exists: $TEMP_VENV"

    printf '\nPreparing the private ChromaMatter runtime environment...\n'
    "$base_python" -m venv "$TEMP_VENV"
    "$TEMP_VENV/bin/python" -m pip install \
        --disable-pip-version-check \
        --require-hashes \
        --only-binary=:all: \
        --no-deps \
        -r "$RUNTIME_LOCK"
    "$TEMP_VENV/bin/python" -m pip check
    python_matches_alpha "$TEMP_VENV/bin/python" || \
        fail "The new private Python environment is not native arm64 CPython 3.13.14."

    marker="$TEMP_VENV/.chromamatter-runtime-lock.sha256"
    printf '%s\n' "$lock_sha256" >"$marker"

    if [[ -e "$VENV_DIR" ]]; then
        case "$VENV_DIR" in
            "$SUPPORT_ROOT"/venv-3.13.14) rm -rf -- "$VENV_DIR" ;;
            *) fail "Refusing to replace an unexpected environment path: $VENV_DIR" ;;
        esac
    fi
    mv -- "$TEMP_VENV" "$VENV_DIR"
    TEMP_VENV=""
}

printf 'ChromaMatter Apple Silicon macOS 15+ source alpha\n'
printf 'Source tester tag: %s\n' "$SOURCE_ALPHA_TAG"

[[ "$(uname -s)" == "Darwin" ]] || fail "This launcher must run on macOS."
[[ "$(uname -m)" == "arm64" ]] || fail "This alpha requires an Apple Silicon Mac running natively."
[[ "$SUPPORT_ROOT" == /* && "$SUPPORT_ROOT" != "/" ]] || \
    fail "CHROMAMATTER_ALPHA_HOME must be an absolute path other than /."

for command_name in awk curl mktemp open pkgutil shasum sw_vers; do
    command -v "$command_name" >/dev/null 2>&1 || fail "Required macOS tool is missing: $command_name"
done

MACOS_MAJOR="$(sw_vers -productVersion | awk -F. '{print $1}')"
[[ "$MACOS_MAJOR" =~ ^[0-9]+$ ]] && ((MACOS_MAJOR >= 15)) || \
    fail "This alpha requires macOS 15 or newer."

require_file "$ENTRYPOINT"
require_file "$RUNTIME_LOCK"
require_file "$GLB_GENERATOR"

mkdir -p -- "$PROFILE_DIR" "$TEST_DATA_DIR" "$VALIDATION_DIR"

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    [[ -z "${CHROMAMATTER_PYTHON:-}" ]] || \
        fail "The requested CHROMAMATTER_PYTHON runtime is unavailable."
    install_python_interactively
    PYTHON_BIN="$(find_python || true)"
fi
[[ -n "$PYTHON_BIN" ]] || \
    fail "CPython 3.13.14 arm64 was not found after installation. Run this launcher again after Installer finishes."

LOCK_SHA256="$(shasum -a 256 "$RUNTIME_LOCK" | awk '{print $1}')"
if ! venv_matches_lock "$LOCK_SHA256"; then
    build_runtime_venv "$PYTHON_BIN" "$LOCK_SHA256"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
export PYTHONPATH="$SCRIPT_DIR:$FIXED_APP"
export PYTHONDONTWRITEBYTECODE=1
export CHROMAMATTER_DATA_DIRECTORY="$PROFILE_DIR"

printf '\nGenerating the rights-safe CC0 four-colour test GLB...\n'
"$VENV_PYTHON" "$GLB_GENERATOR" --output "$PUBLIC_GLB"
[[ "$(shasum -a 256 "$PUBLIC_GLB" | awk '{print $1}')" == "$PUBLIC_GLB_SHA256" ]] || \
    fail "The generated public test GLB did not match its deterministic SHA-256."

printf '\nRunning the native PyTetWild/PyMeshLab and ModernGL render self-test...\n'
if ! "$VENV_PYTHON" "$ENTRYPOINT" --macos-alpha-self-test >"$SELF_TEST_JSON"; then
    cat "$SELF_TEST_JSON" >&2 || true
    fail "The native/render self-test failed. Its JSON report is in $SELF_TEST_JSON"
fi
"$VENV_PYTHON" - "$SELF_TEST_JSON" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="ascii"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"Invalid macOS alpha self-test JSON: {exc}") from exc
if payload.get("ok") is not True:
    raise SystemExit("macOS alpha self-test did not report ok=true")
PY

if ((SELF_TEST_ONLY)); then
    printf '\nSelf-test-only setup passed.\n'
    printf 'Public test model: %s\n' "$PUBLIC_GLB"
    printf 'Self-test report: %s\n' "$SELF_TEST_JSON"
    exit 0
fi

printf '\nSelf-test passed. Starting ChromaMatter...\n'
printf 'Public test model: %s\n\n' "$PUBLIC_GLB"
cd -- "$SCRIPT_DIR"
exec "$VENV_PYTHON" "$ENTRYPOINT"
