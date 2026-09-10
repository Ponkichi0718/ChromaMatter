#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON_BIN="$SCRIPT_DIR/.venv-linux-source-alpha/bin/python"
ENTRYPOINT="$SCRIPT_DIR/source/fixed_app/TripoSpectrumMapper_fixed.py"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
    echo "This technical alpha currently supports Linux x86_64 only." >&2
    exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "The Linux source environment is not installed." >&2
    echo "Run ./INSTALL_LINUX_SOURCE_ALPHA.sh first." >&2
    exit 1
fi
if [[ ! -f "$ENTRYPOINT" ]]; then
    echo "The ChromaMatter source entrypoint is missing." >&2
    exit 1
fi
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo "No graphical display was detected (DISPLAY and WAYLAND_DISPLAY are empty)." >&2
    echo "Start this script from an Ubuntu desktop session or WSLg terminal." >&2
    exit 1
fi

export PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON_BIN" "$ENTRYPOINT" "$@"
