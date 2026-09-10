#!/usr/bin/env bash
# Prepare the source-backed ChromaMatter Linux alpha without redistributing
# third-party binary wheels inside this archive.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
LOCK_FILE="$SCRIPT_DIR/source/fixed_app/requirements-build-linux-x86_64.lock"
VENV_DIR="$SCRIPT_DIR/.venv-linux-source-alpha"
PYTHON_VERSION="3.13.14"
FONT_PACKAGES=(
    fonts-noto-cjk
    xfonts-base
    xfonts-intl-japanese
    xfonts-intl-japanese-big
)

fail() {
    printf 'ChromaMatter Linux source alpha setup stopped: %s\n' "$1" >&2
    exit 1
}

[[ "$(uname -s)" == "Linux" ]] || fail "Linux is required."
[[ "$(uname -m)" == "x86_64" ]] || fail "This alpha currently supports x86_64 only."
[[ -f "$LOCK_FILE" ]] || fail "The pinned Linux requirements lock is missing."
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    fail "No graphical display was detected; use an Ubuntu desktop or WSLg terminal."
fi

if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    [[ "${ID:-}" == "ubuntu" ]] || fail "Ubuntu 22.04 or newer is required for this test build."
    case "${VERSION_ID:-}" in
        22.04|22.10|23.*|24.*|25.*|26.*|27.*|28.*|29.*) ;;
        *) fail "Ubuntu 22.04 or newer is required; found ${VERSION_ID:-unknown}." ;;
    esac
else
    fail "/etc/os-release is unavailable, so the supported Ubuntu version cannot be verified."
fi

command -v dpkg-query >/dev/null 2>&1 || fail "dpkg-query is required on the supported Ubuntu path."
missing_fonts=()
for package_name in "${FONT_PACKAGES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$package_name" 2>/dev/null | grep -q '^install ok installed$'; then
        missing_fonts+=("$package_name")
    fi
done
if ((${#missing_fonts[@]})); then
    cat >&2 <<'EOF'
Japanese UI fonts are missing. Install the supported Ubuntu font packages, then run this script again:

  sudo apt-get update
  sudo apt-get install -y fonts-noto-cjk xfonts-base xfonts-intl-japanese xfonts-intl-japanese-big

The installer does not run sudo automatically.
EOF
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    cat >&2 <<'EOF'
The uv Python manager is required but was not found.

Install uv from its official instructions, open a new terminal, and run this script again:
  https://docs.astral.sh/uv/getting-started/installation/

This archive deliberately does not download or execute a remote installer automatically.
EOF
    exit 1
fi

printf 'Preparing managed CPython %s...\n' "$PYTHON_VERSION"
uv python install "$PYTHON_VERSION"
MANAGED_PYTHON="$(uv python find --managed-python "$PYTHON_VERSION")"
[[ -x "$MANAGED_PYTHON" ]] || fail "uv did not provide an executable managed Python $PYTHON_VERSION."

observed_python="$($MANAGED_PYTHON -c 'import platform, sys; print(".".join(map(str, sys.version_info[:3])) + " " + platform.machine())')"
[[ "$observed_python" == "$PYTHON_VERSION x86_64" ]] || fail "Unexpected managed Python: $observed_python"

printf 'Creating the local environment at %s...\n' "$VENV_DIR"
uv venv --python "$MANAGED_PYTHON" "$VENV_DIR"
uv pip sync \
    --python "$VENV_DIR/bin/python" \
    --require-hashes \
    --only-binary=:all: \
    --strict \
    "$LOCK_FILE"

printf 'Running the packaged-source self-test...\n'
PYTHONDONTWRITEBYTECODE=1 \
    "$VENV_DIR/bin/python" \
    "$SCRIPT_DIR/source/fixed_app/TripoSpectrumMapper_fixed.py" \
    --self-test
printf 'Running the Linux native/render self-test...\n'
PYTHONDONTWRITEBYTECODE=1 \
    "$VENV_DIR/bin/python" \
    "$SCRIPT_DIR/source/fixed_app/TripoSpectrumMapper_fixed.py" \
    --linux-alpha-self-test

cat <<EOF

ChromaMatter Linux source alpha setup completed.

Start it with:
  ./RUN_LINUX_SOURCE_ALPHA.sh

The first setup downloads the exact hash-pinned Python wheels directly from
their package index. The virtual environment stays inside this extracted
folder and can be removed safely by deleting:
  $VENV_DIR
EOF
