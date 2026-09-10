#!/usr/bin/env bash
# Build and validate the separate Apple Silicon / macOS 15+ Developer ID
# unsigned, unnotarized alpha. PyInstaller applies an ad-hoc signature.
# This never signs with a Developer ID, notarizes, publishes a Release, or
# modifies the Windows build path.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
FIXED_APP="$SCRIPT_DIR/source/fixed_app"
SPEC="$FIXED_APP/TripoSpectrumMapper_macos_arm64.spec"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT_ROOT="$SCRIPT_DIR/build_output/macos-arm64"
RUN_SOURCE_TESTS=1
UI_SMOKE_MODE="best-effort"

usage() {
    cat <<'EOF'
Usage: BUILD_MACOS_ARM64.sh [options]

Options:
  --python PATH              CPython 3.13.14 executable (default: python3)
  --output-root PATH         Build root (default: build_output/macos-arm64)
  --skip-source-tests        Skip the full source unittest discovery run
  --ui-smoke MODE            required, best-effort, or skip
  -h, --help                 Show this help

Dependencies are not installed by this script. Install the hash-locked
source/fixed_app/requirements-build-macos-arm64.lock first.
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
    *)
        echo "--ui-smoke must be required, best-effort, or skip" >&2
        exit 2
        ;;
esac

[[ "$(uname -s)" == "Darwin" ]] || {
    echo "This build must run on macOS." >&2
    exit 1
}
[[ "$(uname -m)" == "arm64" ]] || {
    echo "This first alpha is Apple Silicon arm64 only." >&2
    exit 1
}

command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "Python executable not found: $PYTHON_BIN" >&2
    exit 1
}
for command_name in codesign file lipo plutil sw_vers; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required macOS tool not found: $command_name" >&2
        exit 1
    }
done

PYTHON_BIN="$("$PYTHON_BIN" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
PYTHON_MACHINE="$("$PYTHON_BIN" -c 'import platform; print(platform.machine())')"
MACOS_MAJOR="$(sw_vers -productVersion | awk -F. '{print $1}')"

[[ "$PYTHON_VERSION" == "3.13.14" ]] || {
    echo "The alpha lock requires Python 3.13.14; found $PYTHON_VERSION" >&2
    exit 1
}
[[ "$PYTHON_MACHINE" == "arm64" ]] || {
    echo "The Python runtime must be arm64; found $PYTHON_MACHINE" >&2
    exit 1
}
[[ "$MACOS_MAJOR" =~ ^[0-9]+$ ]] && ((MACOS_MAJOR >= 15)) || {
    echo "This alpha requires macOS 15 or newer." >&2
    exit 1
}

OUTPUT_ROOT="$("$PYTHON_BIN" -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$OUTPUT_ROOT")"
case "$OUTPUT_ROOT" in
    ""|/|"$SCRIPT_DIR")
        echo "Unsafe build output root: $OUTPUT_ROOT" >&2
        exit 1
        ;;
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
        raise SystemExit(
            f"Repository-local output must remain below {allowed}: {output}"
        ) from exc
PY

DIST_PATH="$OUTPUT_ROOT/dist"
WORK_PATH="$OUTPUT_ROOT/work"
VALIDATION_PATH="$OUTPUT_ROOT/validation"
APP_BUNDLE="$DIST_PATH/ChromaMatter-macOS-Alpha.app"
APP_EXECUTABLE="$APP_BUNDLE/Contents/MacOS/ChromaMatter"

mkdir -p "$OUTPUT_ROOT"
for clean_path in "$DIST_PATH" "$WORK_PATH" "$VALIDATION_PATH"; do
    case "$clean_path" in
        "$OUTPUT_ROOT"/*) rm -rf -- "$clean_path" ;;
        *) echo "Refusing unsafe cleanup: $clean_path" >&2; exit 1 ;;
    esac
done
mkdir -p "$VALIDATION_PATH"

export PYTHONPATH="$SCRIPT_DIR:$FIXED_APP"
export PYTHONDONTWRITEBYTECODE=1

run_macos_alpha_gate() {
    local label="$1"
    local output_path="$2"
    shift 2
    local output
    if ! output="$("$@" --macos-alpha-self-test)"; then
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

assert platform.machine() == "arm64"
assert tkinter.TkVersion >= 8.6
assert _load_tetwild_wrapper() is not None
assert pymeshlab.MeshSet() is not None
print("Apple Silicon native dependency probe passed.")
PY

# This stronger platform gate performs real PyMeshLab filter execution,
# PyTetWild native loading, and a real ModernGL framebuffer draw/read. It is
# intentionally separate from the portable packaged self-test.
run_macos_alpha_gate \
    "Source macOS alpha native/render self-test" \
    "$VALIDATION_PATH/MACOS_ALPHA_SOURCE_SELF_TEST.json" \
    "$PYTHON_BIN" "$FIXED_APP/TripoSpectrumMapper_fixed.py"

SOURCE_TEST_STATUS="skipped"
if ((RUN_SOURCE_TESTS)); then
    "$PYTHON_BIN" -B - "$SCRIPT_DIR" <<'PY'
from pathlib import Path
from datetime import datetime, timezone
import faulthandler
import sys
import time
import unittest

repository = Path(sys.argv[1]).resolve()
fixed_app = repository / "source" / "fixed_app"

# These modules validate the immutable Windows package, DLL identities,
# Windows-only controlled PyTetWild rebuild, and Windows Release staging. They
# remain active in the Windows pipeline and are not weakened or rewritten for
# macOS. The macOS alpha has separate packaging gates below.
windows_release_only = {
    "test_audited_native_identities.py",
    "test_binary_compliance_inventory.py",
    "test_corresponding_source_tooling.py",
    "test_pytetwild_static_closure.py",
    "test_pytetwild_static_closure_contract.py",
    "test_pytetwild_static_closure_notices.py",
    "test_qt_static_components.py",
    "test_release_identity.py",
    "test_release_tooling.py",
}

module_names = []
for path in sorted(fixed_app.rglob("test_*.py")):
    if path.name in windows_release_only:
        continue
    relative = path.relative_to(repository).with_suffix("")
    module_names.append(".".join(relative.parts))

if not module_names:
    raise SystemExit("No macOS source tests were selected")

class DiagnosticTextTestResult(unittest.TextTestResult):
    def _log_phase(self, phase, test):
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.stream.write(
            f"\n[macos-source-test] {phase} {timestamp} "
            f"monotonic={time.monotonic():.3f} {test.id()}\n"
        )
        self.stream.flush()

    def startTest(self, test):
        self._log_phase("START", test)
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        self._log_phase("STOP", test)


# A periodic all-thread dump identifies native/Tk waits without interrupting
# a test, changing its result, or adding a platform-specific skip.
faulthandler.enable(file=sys.stderr, all_threads=True)
try:
    faulthandler.dump_traceback_later(60, repeat=True, file=sys.stderr)
    suite = unittest.defaultTestLoader.loadTestsFromNames(module_names)
    result = unittest.TextTestRunner(
        verbosity=2, resultclass=DiagnosticTextTestResult
    ).run(suite)
finally:
    faulthandler.cancel_dump_traceback_later()
print(
    f"macOS source suite: {result.testsRun} tests; "
    f"failures={len(result.failures)} errors={len(result.errors)} "
    f"skipped={len(result.skipped)}"
)
if not result.wasSuccessful():
    raise SystemExit(1)
PY
    SOURCE_TEST_STATUS="passed (Windows-only package/compliance modules excluded)"
fi

"$PYTHON_BIN" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$DIST_PATH" \
    --workpath "$WORK_PATH" \
    "$SPEC"

[[ -d "$APP_BUNDLE" ]] || { echo "App bundle is missing: $APP_BUNDLE" >&2; exit 1; }
[[ -x "$APP_EXECUTABLE" ]] || {
    echo "Packaged executable is missing or not executable: $APP_EXECUTABLE" >&2
    exit 1
}

PYTHON_BIN="$PYTHON_BIN" bash "$SCRIPT_DIR/AUDIT_MACOS_APP.sh" \
    "$APP_BUNDLE" \
    "$VALIDATION_PATH/MACOS_ALPHA_APP_AUDIT.txt"

# Preserve deterministic observed-bundle facts after the structural audit.
# This JSON is diagnostic input for the later component/SBOM/source reviews;
# it is not itself a distribution approval or ownership mapping.
"$PYTHON_BIN" "$SCRIPT_DIR/tooling/generate_macos_app_inventory.py" \
    --app-bundle "$APP_BUNDLE" \
    --output "$VALIDATION_PATH/MACOS_ALPHA_APP_INVENTORY.json"

"$APP_EXECUTABLE" --self-test
run_macos_alpha_gate \
    "Packaged macOS alpha native/render self-test" \
    "$VALIDATION_PATH/MACOS_ALPHA_PACKAGED_SELF_TEST.json" \
    "$APP_EXECUTABLE"

SMOKE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/chromamatter-macos-ui-smoke.XXXXXX")"
cleanup_smoke() {
    case "$SMOKE_ROOT" in
        "${TMPDIR:-/tmp}"/chromamatter-macos-ui-smoke.*) rm -rf -- "$SMOKE_ROOT" ;;
        *) echo "Refusing unsafe smoke cleanup: $SMOKE_ROOT" >&2 ;;
    esac
}
trap cleanup_smoke EXIT

run_ui_smoke() {
    local language="$1"
    local profile="$SMOKE_ROOT/$language"
    mkdir -p "$profile/data" "$profile/tmp"
    "$PYTHON_BIN" - \
        "$APP_EXECUTABLE" "$language" "$profile/data" "$profile/tmp" <<'PY'
import os
import subprocess
import sys

executable, language, data_directory, temporary_directory = sys.argv[1:]
environment = os.environ.copy()
environment["CHROMAMATTER_DATA_DIRECTORY"] = data_directory
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
    raise SystemExit(
        f"{language} packaged UI smoke exited with {completed.returncode}"
    )
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
        echo "::warning::Hosted macOS UI smoke was not conclusive: ja=$UI_SMOKE_JA en=$UI_SMOKE_EN"
    fi
fi

cat >"$VALIDATION_PATH/MACOS_ALPHA_BUILD_REPORT.txt" <<EOF
ChromaMatter Apple Silicon macOS 15+ Developer ID unsigned, unnotarized alpha
Bundle signature: ad-hoc (not Developer ID)
Display version: 0.9
Python: $PYTHON_VERSION arm64
macOS: $(sw_vers -productVersion)
Source tests: $SOURCE_TEST_STATUS
Native dependency probe: passed
Observed app inventory: MACOS_ALPHA_APP_INVENTORY.json generated after app audit
Packaged self-test: passed
macOS alpha native/render self-test (source and packaged): passed
Packaged UI smoke (Japanese): $UI_SMOKE_JA
Packaged UI smoke (English): $UI_SMOKE_EN
Bundle identifier: io.github.ponkichi0718.chromamatter.alpha
Developer ID signed: no
Apple notarized: no
Public Release eligible: no
EOF

echo "macOS alpha build completed: $APP_BUNDLE"
echo "Validation report: $VALIDATION_PATH/MACOS_ALPHA_BUILD_REPORT.txt"
