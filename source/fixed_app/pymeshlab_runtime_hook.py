"""Register PyMeshLab's bundled DLL directory before frozen imports.

Python 3.13 on Windows no longer resolves extension-module dependencies from a
PATH entry alone. PyInstaller places ``pmeshlab*.pyd`` and its Qt/MeshLab DLLs
together under ``sys._MEIPASS/pymeshlab``; retaining the directory handles for
the process lifetime lets Windows resolve those native dependencies without
changing source-mode behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


_DLL_DIRECTORY_HANDLES: list[object] = []


def _register_frozen_pymeshlab_directories() -> None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if not bundle_root or add_dll_directory is None:
        return

    package_root = Path(bundle_root) / "pymeshlab"
    candidates = (package_root, package_root / "lib")
    existing = [path for path in candidates if path.is_dir()]
    if not existing:
        return

    for path in existing:
        _DLL_DIRECTORY_HANDLES.append(add_dll_directory(str(path)))

    current_path = os.environ.get("PATH", "")
    prefix = os.pathsep.join(str(path) for path in existing)
    os.environ["PATH"] = prefix + (os.pathsep + current_path if current_path else "")

    plugin_root = package_root / "plugins"
    if plugin_root.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugin_root))


_register_frozen_pymeshlab_directories()
