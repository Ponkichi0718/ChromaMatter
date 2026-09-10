#!/usr/bin/env bash
# Build and validate the separate Ubuntu-22.04+ Linux x86_64 technical alpha.
# This script never publishes, archives, or uploads the application directory.

set -euo pipefail

ORIGINAL_ARGUMENTS=("$@")
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
FIXED_APP="$SCRIPT_DIR/source/fixed_app"
SPEC="$FIXED_APP/TripoSpectrumMapper_linux_x86_64.spec"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT_ROOT="$SCRIPT_DIR/build_output/linux-x86_64"
RUN_SOURCE_TESTS=1
UI_SMOKE_MODE="best-effort"

usage() {
    cat <<'EOF'
Usage: BUILD_LINUX_X86_64.sh [options]

Options:
  --python PATH              CPython 3.13.14 executable (default: python3)
  --output-root PATH         Build root (default: build_output/linux-x86_64)
  --skip-source-tests        Skip the selected portable source test suite
  --ui-smoke MODE            required, best-effort, or skip
  -h, --help                 Show this help

Install source/fixed_app/requirements-build-linux-x86_64.lock first. The
output is a diagnostics-only technical build, not a distribution package.
The Japanese UI also requires these host fonts on minimal Ubuntu/WSL:
  sudo apt-get install -y fonts-noto-cjk xfonts-base \
    xfonts-intl-japanese xfonts-intl-japanese-big
EOF
}

while (($#)); do
    case "$1" in
        --python)
            [[ $# -ge 2 ]] || { echo "--python requires a value" >&2; exit 2; }
            PYTHON_BIN="$2"
            shift 2
            ;;
        --output-root)
            [[ $# -ge 2 ]] || { echo "--output-root requires a value" >&2; exit 2; }
            OUTPUT_ROOT="$2"
            shift 2
            ;;
        --skip-source-tests)
            RUN_SOURCE_TESTS=0
            shift
            ;;
        --ui-smoke)
            [[ $# -ge 2 ]] || { echo "--ui-smoke requires a value" >&2; exit 2; }
            UI_SMOKE_MODE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$UI_SMOKE_MODE" in
    required|best-effort|skip) ;;
    *) echo "--ui-smoke must be required, best-effort, or skip" >&2; exit 2 ;;
esac

[[ "$(uname -s)" == "Linux" ]] || {
    echo "This technical build must run on Linux." >&2
    exit 1
}
[[ "$(uname -m)" == "x86_64" ]] || {
    echo "This first Linux technical build is x86_64 only." >&2
    exit 1
}
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "Python executable not found: $PYTHON_BIN" >&2
    exit 1
}
for command_name in file readelf ldd strings getconf patchelf realpath; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required Linux build/audit tool not found: $command_name" >&2
        exit 1
    }
done

PYTHON_BIN="$("$PYTHON_BIN" -c 'import os, sys; print(os.path.abspath(sys.executable))')"
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
PYTHON_MACHINE="$("$PYTHON_BIN" -c 'import platform; print(platform.machine())')"
GLIBC_VERSION="$(getconf GNU_LIBC_VERSION | awk '{print $2}')"
[[ "$PYTHON_VERSION" == "3.13.14" ]] || {
    echo "The Linux lock requires Python 3.13.14; found $PYTHON_VERSION" >&2
    exit 1
}
[[ "$PYTHON_MACHINE" == "x86_64" ]] || {
    echo "The Python runtime must be x86_64; found $PYTHON_MACHINE" >&2
    exit 1
}
"$PYTHON_BIN" - "$GLIBC_VERSION" <<'PY'
import sys

try:
    parts = tuple(int(value) for value in sys.argv[1].split(".")[:2])
except ValueError as exc:
    raise SystemExit(f"Unrecognized glibc version: {sys.argv[1]}") from exc
if parts < (2, 35):
    raise SystemExit(f"The Linux wheel lock requires glibc 2.35+; found {sys.argv[1]}")
PY

# ModernGL and the Tk UI both need an X server. Start one automatically when
# the caller did not already provide DISPLAY; the recursion guard is explicit.
if [[ -z "${DISPLAY:-}" && "${CHROMAMATTER_LINUX_XVFB_ACTIVE:-}" != "1" ]]; then
    command -v xvfb-run >/dev/null 2>&1 || {
        echo "DISPLAY is unset and xvfb-run is unavailable." >&2
        exit 1
    }
    export CHROMAMATTER_LINUX_XVFB_ACTIVE=1
    # A bare Xvfb session has no stable hardware-GL path.  Pin its validation
    # run to Mesa software rendering so glcontext teardown cannot race Tk/X11.
    export LIBGL_ALWAYS_SOFTWARE=1
    exec xvfb-run -a -s "-screen 0 1920x1080x24" \
        bash "$SCRIPT_DIR/BUILD_LINUX_X86_64.sh" "${ORIGINAL_ARGUMENTS[@]}"
fi

TCL_PATCHLEVEL="$("$PYTHON_BIN" -c 'import tkinter; print(tkinter.Tcl().eval("info patchlevel"))')"
TK_PATCHLEVEL="$("$PYTHON_BIN" -c 'import tkinter; root = tkinter.Tk(); print(root.tk.call("info", "patchlevel")); root.destroy()')"
UI_FONT_PROBE="$("$PYTHON_BIN" - "$FIXED_APP" <<'PY'
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(sys.argv[1])))
from spectrum_mapper.ui_fonts import (  # noqa: E402
    LinuxJapaneseFontUnavailable,
    resolve_ui_font,
)

root = tk.Tk()
root.withdraw()
try:
    probe = resolve_ui_font(root, platform_name="linux")
except LinuxJapaneseFontUnavailable as exc:
    raise SystemExit(str(exc)) from exc
finally:
    root.destroy()
print(
    f"{probe.family}:{probe.japanese_width}; "
    f"Pillow={probe.pillow_font_path}"
)
PY
)"

OUTPUT_ROOT="$("$PYTHON_BIN" -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$OUTPUT_ROOT")"
case "$OUTPUT_ROOT" in
    ""|/|"$SCRIPT_DIR") echo "Unsafe build output root: $OUTPUT_ROOT" >&2; exit 1 ;;
esac
"$PYTHON_BIN" - "$SCRIPT_DIR" "$OUTPUT_ROOT" <<'PY'
from pathlib import Path
import sys

repository = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
try:
    output.relative_to(repository)
except ValueError:
    pass
else:
    allowed = (repository / "build_output").resolve()
    try:
        output.relative_to(allowed)
    except ValueError as exc:
        raise SystemExit(f"Repository-local output must remain below {allowed}: {output}") from exc
PY

DIST_PATH="$OUTPUT_ROOT/dist"
WORK_PATH="$OUTPUT_ROOT/work"
VALIDATION_PATH="$OUTPUT_ROOT/validation"
APP_DIRECTORY="$DIST_PATH/ChromaMatter-Linux-Alpha"
APP_EXECUTABLE="$APP_DIRECTORY/ChromaMatter"

mkdir -p "$OUTPUT_ROOT"
for clean_path in "$DIST_PATH" "$WORK_PATH" "$VALIDATION_PATH"; do
    case "$clean_path" in
        "$OUTPUT_ROOT"/*) rm -rf -- "$clean_path" ;;
        *) echo "Refusing unsafe cleanup: $clean_path" >&2; exit 1 ;;
    esac
done
mkdir -p "$VALIDATION_PATH"

# Every validation and packaging step must resolve imports from this exact
# source snapshot, regardless of the directory from which the script was
# invoked.  Relative output arguments have already been made absolute above.
cd "$SCRIPT_DIR"

export PYTHONPATH="$SCRIPT_DIR:$FIXED_APP"
export PYTHONDONTWRITEBYTECODE=1
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export CHROMAMATTER_LINUX_BUILD_SOURCE_ROOT="$SCRIPT_DIR"
export CHROMAMATTER_LINUX_BUILD_OUTPUT_ROOT="$OUTPUT_ROOT"
export CHROMAMATTER_LINUX_BUILD_PYTHON_PREFIX="$("$PYTHON_BIN" -c 'import sys; print(sys.prefix)')"
export CHROMAMATTER_LINUX_BUILD_BASE_PREFIX="$("$PYTHON_BIN" -c 'import sys; print(sys.base_prefix)')"

run_linux_alpha_gate() {
    local label="$1"
    local output_path="$2"
    shift 2
    local output
    if ! output="$("$@" --linux-alpha-self-test)"; then
        printf '%s\n' "$output" >"$output_path"
        echo "$label failed; JSON output saved to $output_path" >&2
        return 1
    fi
    printf '%s\n' "$output" >"$output_path"
    "$PYTHON_BIN" - "$output_path" "$label" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
label = sys.argv[2]
try:
    payload = json.loads(path.read_text(encoding="ascii"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"{label} did not emit one ASCII JSON document: {exc}") from exc
if payload.get("ok") is not True:
    raise SystemExit(f"{label} returned JSON without top-level ok=true")
print(f"{label} passed with top-level ok=true")
PY
}

"$PYTHON_BIN" -m pip check
"$PYTHON_BIN" - <<'PY'
import platform
import tkinter

import glcontext
import manifold3d
import mapbox_earcut
import moderngl
import numpy
import pymeshlab
import scipy
import shapely
import tetgen
import trimesh

from spectrum_mapper.volume_partition import _load_tetwild_wrapper

assert platform.machine() == "x86_64"
assert tkinter.TkVersion >= 8.6
assert _load_tetwild_wrapper() is not None
assert pymeshlab.MeshSet() is not None
print("Linux x86_64 native dependency probe passed.")
PY

run_linux_alpha_gate \
    "Source Linux native/render self-test" \
    "$VALIDATION_PATH/LINUX_ALPHA_SOURCE_SELF_TEST.json" \
    "$PYTHON_BIN" "$FIXED_APP/TripoSpectrumMapper_fixed.py"

SOURCE_TEST_STATUS="skipped"
if ((RUN_SOURCE_TESTS)); then
    "$PYTHON_BIN" -B - "$SCRIPT_DIR" <<'PY'
from pathlib import Path
import importlib
import os
import sys
import unittest

repository = Path(sys.argv[1]).resolve()
fixed_app = repository / "source" / "fixed_app"
os.chdir(repository)
for required_path in (str(fixed_app), str(repository)):
    while required_path in sys.path:
        sys.path.remove(required_path)
    sys.path.insert(0, required_path)
platform_package_only = {
    "test_audited_native_identities.py",
    "test_binary_compliance_inventory.py",
    "test_corresponding_source_tooling.py",
    "test_macos_app_inventory.py",
    "test_macos_compliance_evidence.py",
    "test_macos_packaging.py",
    "test_macos_source_coverage.py",
    "test_pytetwild_static_closure.py",
    "test_pytetwild_static_closure_contract.py",
    "test_pytetwild_static_closure_notices.py",
    "test_qt_static_components.py",
    "test_release_identity.py",
    "test_release_tooling.py",
}
module_names = []
for path in sorted(fixed_app.rglob("test_*.py")):
    if path.name in platform_package_only:
        continue
    module_names.append(".".join(path.relative_to(repository).with_suffix("").parts))
if not module_names:
    raise SystemExit("No Linux source tests were selected")
for module_name in module_names:
    module = importlib.import_module(module_name)
    origin = Path(module.__file__).resolve()
    try:
        origin.relative_to(repository)
    except ValueError as exc:
        raise SystemExit(
            f"Linux source test escaped the exact snapshot: {module_name} -> {origin}"
        ) from exc
suite = unittest.defaultTestLoader.loadTestsFromNames(module_names)
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(
    f"Linux source suite: {result.testsRun} tests; failures={len(result.failures)} "
    f"errors={len(result.errors)} skipped={len(result.skipped)}"
)
if not result.wasSuccessful():
    raise SystemExit(1)
PY
    SOURCE_TEST_STATUS="passed (Windows release and macOS package/compliance modules excluded)"
fi

"$PYTHON_BIN" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$DIST_PATH" \
    --workpath "$WORK_PATH" \
    "$SPEC"

[[ -d "$APP_DIRECTORY" ]] || {
    echo "Application directory is missing: $APP_DIRECTORY" >&2
    exit 1
}
[[ -x "$APP_EXECUTABLE" ]] || {
    echo "Packaged executable is missing or not executable: $APP_EXECUTABLE" >&2
    exit 1
}

SANITIZED_ELF_SEARCH_PATHS=0
while IFS= read -r -d '' candidate; do
    file_description="$(file -b "$candidate")"
    [[ "$file_description" == ELF* ]] || continue
    current_rpath="$(patchelf --print-rpath "$candidate")"
    [[ -n "$current_rpath" ]] || continue
    IFS=':' read -r -a rpath_entries <<<"$current_rpath"
    safe_entries=()
    changed=0
    for entry in "${rpath_entries[@]}"; do
        case "$entry" in
            '$ORIGIN'|'$ORIGIN/'*|'${ORIGIN}'|'${ORIGIN}/'*)
                safe_entries+=("$entry")
                ;;
            "") ;;
            *) changed=1 ;;
        esac
    done
    if ((changed)); then
        if ((${#safe_entries[@]})); then
            (IFS=':'; patchelf --set-rpath "${safe_entries[*]}" "$candidate")
        else
            patchelf --remove-rpath "$candidate"
        fi
        SANITIZED_ELF_SEARCH_PATHS=$((SANITIZED_ELF_SEARCH_PATHS + 1))
    fi
done < <(find "$APP_DIRECTORY" -type f -print0)

PYTHON_BIN="$PYTHON_BIN" bash "$SCRIPT_DIR/AUDIT_LINUX_APP.sh" \
    "$APP_DIRECTORY" \
    "$VALIDATION_PATH/LINUX_ALPHA_APP_AUDIT.txt"

"$APP_EXECUTABLE" --self-test
run_linux_alpha_gate \
    "Packaged Linux native/render self-test" \
    "$VALIDATION_PATH/LINUX_ALPHA_PACKAGED_SELF_TEST.json" \
    "$APP_EXECUTABLE"

SMOKE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/chromamatter-linux-ui-smoke.XXXXXX")"
cleanup_smoke() {
    case "$SMOKE_ROOT" in
        "${TMPDIR:-/tmp}"/chromamatter-linux-ui-smoke.*) rm -rf -- "$SMOKE_ROOT" ;;
        *) echo "Refusing unsafe smoke cleanup: $SMOKE_ROOT" >&2 ;;
    esac
}
trap cleanup_smoke EXIT

run_ui_smoke() {
    local language="$1"
    local profile="$SMOKE_ROOT/$language"
    mkdir -p "$profile/data" "$profile/config" "$profile/tmp"
    "$PYTHON_BIN" - "$APP_EXECUTABLE" "$language" "$profile/data" "$profile/config" "$profile/tmp" <<'PY'
import os
import subprocess
import sys

executable, language, data_directory, config_directory, temporary_directory = sys.argv[1:]
environment = os.environ.copy()
environment["CHROMAMATTER_DATA_DIRECTORY"] = data_directory
environment["XDG_CONFIG_HOME"] = config_directory
environment["TMPDIR"] = temporary_directory
environment["CHROMAMATTER_UI_SMOKE_LANGUAGE"] = language
try:
    completed = subprocess.run(
        [executable, "--ui-smoke", "--ui-smoke-language", language],
        env=environment,
        timeout=45,
        check=False,
    )
except subprocess.TimeoutExpired as exc:
    raise SystemExit(f"{language} packaged UI smoke timed out after 45 seconds") from exc
if completed.returncode != 0:
    raise SystemExit(f"{language} packaged UI smoke exited with {completed.returncode}")
PY
}

UI_SMOKE_JA="skipped"
UI_SMOKE_EN="skipped"
if [[ "$UI_SMOKE_MODE" != "skip" ]]; then
    set +e
    run_ui_smoke ja
    ja_status=$?
    run_ui_smoke en
    en_status=$?
    set -e
    [[ $ja_status -eq 0 ]] && UI_SMOKE_JA="passed" || UI_SMOKE_JA="failed($ja_status)"
    [[ $en_status -eq 0 ]] && UI_SMOKE_EN="passed" || UI_SMOKE_EN="failed($en_status)"
    if [[ "$UI_SMOKE_MODE" == "required" ]] && ((ja_status != 0 || en_status != 0)); then
        echo "Required packaged UI smoke failed: ja=$UI_SMOKE_JA en=$UI_SMOKE_EN" >&2
        exit 1
    fi
    if [[ "$UI_SMOKE_MODE" == "best-effort" ]] && ((ja_status != 0 || en_status != 0)); then
        echo "Linux UI smoke was inconclusive: ja=$UI_SMOKE_JA en=$UI_SMOKE_EN" >&2
    fi
fi

cat >"$VALIDATION_PATH/LINUX_ALPHA_BUILD_REPORT.txt" <<EOF
ChromaMatter Ubuntu 22.04+ Linux x86_64 technical alpha
Display version: 0.9
Python: $PYTHON_VERSION x86_64
glibc: $GLIBC_VERSION
Tcl/Tk: $TCL_PATCHLEVEL / $TK_PATCHLEVEL
Linux UI font / Japanese glyph width: $UI_FONT_PROBE
patchelf: $(patchelf --version)
ELF files with absolute search paths sanitized: $SANITIZED_ELF_SEARCH_PATHS
Source tests: $SOURCE_TEST_STATUS
Native dependency probe: passed
Packaged self-test: passed
Linux native/render self-test (source and packaged): passed
Packaged UI smoke (Japanese): $UI_SMOKE_JA
Packaged UI smoke (English): $UI_SMOKE_EN
Signed: no
Public or tester distribution approved: no
Application bundle/archive uploaded: no
EOF

echo "Linux technical build completed: $APP_DIRECTORY"
echo "Validation report: $VALIDATION_PATH/LINUX_ALPHA_BUILD_REPORT.txt"
