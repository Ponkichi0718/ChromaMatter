#!/usr/bin/env python3
"""Generate deterministic compliance inventories for a PyInstaller folder.

The input must be an explicit one-folder package root.  The scanner never
follows symlinks or Windows reparse points, records every regular file by its
package-relative path, and fails closed when a native executable has neither a
high-risk rule nor ownership from an installed wheel's ``RECORD`` file.

This is technical inventory tooling, not a legal conclusion.  Its component
metadata deliberately points to the exact upstream version that must be
covered by the release's separately prepared license/source materials.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Iterable


GENERATOR_NAME = "ChromaMatter binary compliance inventory"
GENERATOR_VERSION = "1"
NATIVE_SUFFIXES = {".dll", ".exe", ".pyd"}
REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True)
class Component:
    component_id: str
    name: str
    version: str
    license: str
    source: str
    purl: str = ""


@dataclass(frozen=True)
class ScannedFile:
    path: str
    size: int
    sha256: str
    file_type: str


def _component(
    component_id: str,
    name: str,
    version: str,
    license_expression: str,
    source: str,
    purl: str = "",
) -> Component:
    return Component(
        component_id,
        name,
        version,
        license_expression,
        source,
        purl,
    )


STATIC_COMPONENTS = {
    item.component_id: item
    for item in (
        _component(
            "chromamatter",
            "ChromaMatter",
            "0.8beta-r32",
            "GPL-3.0-or-later",
            "https://github.com/Ponkichi0718/ChromaMatter",
        ),
        _component(
            "cpython",
            "CPython",
            "3.13.14",
            "Python-2.0",
            "https://github.com/python/cpython/tree/v3.13.14",
            "pkg:generic/cpython@3.13.14",
        ),
        _component(
            "pyinstaller",
            "PyInstaller bootloader and run-time hooks",
            "6.20.0",
            "(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0",
            "https://github.com/pyinstaller/pyinstaller/tree/v6.20.0",
            "pkg:pypi/pyinstaller@6.20.0",
        ),
        _component(
            "openssl",
            "OpenSSL",
            "3.0.21",
            "Apache-2.0",
            "https://github.com/openssl/openssl/tree/openssl-3.0.21",
        ),
        _component(
            "sqlite",
            "SQLite",
            "3.50.4",
            "blessing",
            "https://sqlite.org/2025/",
        ),
        _component(
            "tcl-tk",
            "Tcl/Tk",
            "8.6.15",
            "TCL",
            "https://www.tcl.tk/software/tcltk/8.6.html",
        ),
        _component(
            "libffi",
            "libffi runtime",
            "ABI 8",
            "MIT",
            "https://github.com/libffi/libffi",
        ),
        _component(
            "zlib",
            "zlib",
            "1.3.1",
            "Zlib",
            "https://github.com/madler/zlib/tree/v1.3.1",
        ),
        _component(
            "microsoft-ucrt-10.0.19041.1",
            "Microsoft Universal C Runtime",
            "10.0.19041.1",
            "LicenseRef-Microsoft-Windows-SDK-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
        ),
        _component(
            "msvc-14.50.35719",
            "Microsoft Visual C++ Runtime",
            "14.50.35719",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
        ),
        _component(
            "msvc-14.42.34438",
            "Microsoft Visual C++ Runtime",
            "14.42.34438",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
        ),
        _component(
            "msvc-14.40.33810",
            "Microsoft Visual C++ Runtime",
            "14.40.33810",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
        ),
        _component(
            "msvc-14.44.35208",
            "Microsoft Visual C++ Runtime",
            "14.44.35208",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
        ),
        _component(
            "msvc-14.44.35215",
            "Microsoft Visual C++ Runtime",
            "14.44.35215",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
        ),
        _component(
            "numpy",
            "NumPy",
            "2.5.1",
            "BSD-3-Clause",
            "https://github.com/numpy/numpy/tree/v2.5.1",
            "pkg:pypi/numpy@2.5.1",
        ),
        _component(
            "scipy",
            "SciPy",
            "1.18.0",
            "BSD-3-Clause",
            "https://github.com/scipy/scipy/tree/v1.18.0",
            "pkg:pypi/scipy@1.18.0",
        ),
        _component(
            "pillow",
            "Pillow",
            "11.2.1",
            "HPND",
            "https://github.com/python-pillow/Pillow/tree/11.2.1",
            "pkg:pypi/pillow@11.2.1",
        ),
        _component(
            "moderngl",
            "ModernGL",
            "5.12.0",
            "MIT",
            "https://github.com/moderngl/moderngl/tree/5.12.0",
            "pkg:pypi/moderngl@5.12.0",
        ),
        _component(
            "glcontext",
            "glcontext",
            "3.0.0",
            "MIT",
            "https://github.com/moderngl/glcontext/tree/3.0.0",
            "pkg:pypi/glcontext@3.0.0",
        ),
        _component(
            "manifold3d",
            "Manifold3D",
            "3.5.2",
            "Apache-2.0",
            "https://github.com/elalish/manifold/tree/v3.5.2",
            "pkg:pypi/manifold3d@3.5.2",
        ),
        _component(
            "mapbox-earcut",
            "mapbox-earcut",
            "2.0.0",
            "ISC",
            "https://github.com/skogler/mapbox_earcut_python/tree/v2.0.0",
            "pkg:pypi/mapbox-earcut@2.0.0",
        ),
        _component(
            "resvg",
            "resvg-py",
            "0.2.0",
            "MIT",
            "https://github.com/briceyan/resvg-py/tree/v0.2.0",
            "pkg:pypi/resvg@0.2.0",
        ),
        _component(
            "rtree",
            "Rtree / libspatialindex",
            "1.4.1",
            "MIT",
            "https://github.com/Toblerity/rtree/tree/1.4.1",
            "pkg:pypi/rtree@1.4.1",
        ),
        _component(
            "tetgen",
            "tetgen Python wrapper and modified TetGen core",
            "0.8.3 / 1.6.0",
            "MIT AND AGPL-3.0-or-later",
            "https://github.com/pyvista/tetgen/tree/v0.8.3",
            "pkg:pypi/tetgen@0.8.3",
        ),
        _component(
            "pytetwild",
            "PyTetWild / fTetWild",
            "0.3.0 / d7d99bb4387a07895b9adce058dc7305f6b6e5ab",
            "MPL-2.0",
            "https://github.com/pyvista/pytetwild/tree/v0.3.0",
            "pkg:pypi/pytetwild@0.3.0",
        ),
        _component(
            "mpir",
            "MPIR",
            "3.0.0",
            "LGPL-3.0-or-later AND GPL-3.0-or-later",
            "https://github.com/wbhart/mpir/tree/mpir-3.0.0",
        ),
        _component(
            "pymeshlab",
            "PyMeshLab",
            "2025.7.post1",
            "GPL-3.0-only",
            "https://github.com/cnr-isti-vclab/PyMeshLab/tree/v2025.7.post1",
            "pkg:pypi/pymeshlab@2025.7.post1",
        ),
        _component(
            "meshlab",
            "MeshLab / VCGLib",
            "d876376e3cc4f92d257e248023d82cbac5b03c7d",
            "GPL-3.0-only",
            "https://github.com/cnr-isti-vclab/meshlab/tree/"
            "d876376e3cc4f92d257e248023d82cbac5b03c7d",
        ),
        _component(
            "qt",
            "Qt",
            "5.15.2",
            "LGPL-3.0-only",
            "https://download.qt.io/archive/qt/5.15/5.15.2/single/",
            "pkg:generic/qt@5.15.2",
        ),
        _component(
            "qt-angle",
            "Qt ANGLE runtime",
            "5.15.2",
            "BSD-3-Clause",
            "https://download.qt.io/archive/qt/5.15/5.15.2/single/",
        ),
        _component(
            "mesa-llvmpipe",
            "Mesa llvmpipe distributed by Qt",
            "12.0-rc2",
            "MIT AND BSL-1.0",
            "https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt5_5152/",
        ),
        _component(
            "embree",
            "Intel Embree",
            "4.3.3",
            "Apache-2.0",
            "https://github.com/RenderKit/embree/tree/v4.3.3",
        ),
        _component(
            "onetbb-pymeshlab",
            "oneTBB",
            "2021.11.0",
            "Apache-2.0",
            "https://github.com/uxlfoundation/oneTBB/tree/v2021.11.0",
        ),
        _component(
            "xerces-c",
            "Xerces-C++",
            "3.2.4",
            "Apache-2.0",
            "https://github.com/apache/xerces-c/tree/v3.2.4",
        ),
        _component(
            "lib3mf",
            "lib3mf",
            "2.4.1",
            "BSD-2-Clause",
            "https://github.com/3MFConsortium/lib3mf/tree/v2.4.1",
        ),
        _component(
            "gmp",
            "GMP",
            "5.0.1",
            "LGPL-3.0-or-later OR GPL-2.0-or-later",
            "https://gmplib.org/",
        ),
        _component(
            "mpfr",
            "MPFR",
            "3.0.0",
            "LGPL-3.0-or-later",
            "https://www.mpfr.org/mpfr-3.0.0/",
        ),
        _component(
            "libe57format",
            "libE57Format",
            "3.1.1",
            "BSL-1.0",
            "https://github.com/asmaloney/libE57Format/tree/v3.1.1",
        ),
        _component(
            "glew",
            "GLEW",
            "2.2.0",
            "BSD-3-Clause AND MIT",
            "https://github.com/nigels-com/glew/tree/glew-2.2.0",
        ),
        _component(
            "lib3ds",
            "lib3ds",
            "1.3.0",
            "LGPL-2.1-or-later",
            "https://github.com/cnr-isti-vclab/meshlab/blob/"
            "d876376e3cc4f92d257e248023d82cbac5b03c7d/"
            "src/external/lib3ds.cmake",
        ),
        _component(
            "u3d",
            "U3D",
            "1.5.2",
            "Apache-2.0",
            "https://github.com/alemuntoni/u3d/tree/1.5.2",
        ),
        _component(
            "muparser",
            "muparser",
            "2.3.5",
            "BSD-2-Clause",
            "https://github.com/beltoforion/muparser/tree/v2.3.5",
        ),
        _component(
            "shapely",
            "Shapely",
            "2.1.2",
            "BSD-3-Clause",
            "https://github.com/shapely/shapely/tree/2.1.2",
            "pkg:pypi/shapely@2.1.2",
        ),
        _component(
            "geos",
            "GEOS",
            "3.13.1",
            "LGPL-2.1-or-later",
            "https://github.com/libgeos/geos/tree/3.13.1",
            "pkg:generic/geos@3.13.1",
        ),
    )
}


STATIC_PACKAGE_KEYS = {
    "glcontext": "glcontext",
    "manifold3d": "manifold3d",
    "mapbox-earcut": "mapbox-earcut",
    "moderngl": "moderngl",
    "numpy": "numpy",
    "pillow": "pillow",
    "pymeshlab": "pymeshlab",
    "pytetwild": "pytetwild",
    "resvg": "resvg",
    "rtree": "rtree",
    "scipy": "scipy",
    "shapely": "shapely",
    "tetgen": "tetgen",
}


PYTHON_STDLIB_NATIVE = {
    "_asyncio.pyd",
    "_bz2.pyd",
    "_ctypes.pyd",
    "_decimal.pyd",
    "_elementtree.pyd",
    "_hashlib.pyd",
    "_lzma.pyd",
    "_multiprocessing.pyd",
    "_overlapped.pyd",
    "_queue.pyd",
    "_socket.pyd",
    "_sqlite3.pyd",
    "_ssl.pyd",
    "_tkinter.pyd",
    "_uuid.pyd",
    "_wmi.pyd",
    "pyexpat.pyd",
    "select.pyd",
    "unicodedata.pyd",
    "winsound.pyd",
}


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _sort_key(path: str) -> tuple[str, str]:
    return (path.casefold(), path)


def _file_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".exe":
        return "native-executable"
    if suffix == ".dll":
        return "native-library"
    if suffix == ".pyd":
        return "python-extension"
    if suffix == ".pyc":
        return "python-bytecode"
    if suffix in {".txt", ".md"} and re.search(
        r"(^|/)(license|copying|notice)", path, re.IGNORECASE
    ):
        return "license-or-notice"
    if ".dist-info/" in path.casefold():
        return "python-package-metadata"
    return "data-or-source"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_package_tree(root: Path) -> tuple[list[ScannedFile], list[str]]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Package root is not a directory: {root}")

    files: list[ScannedFile] = []
    reparse_points: list[str] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: (item.name.casefold(), item.name))
        child_directories: list[Path] = []
        for entry in entries:
            absolute = Path(entry.path)
            relative = absolute.relative_to(root).as_posix()
            first = entry.stat(follow_symlinks=False)
            is_reparse = entry.is_symlink() or bool(
                getattr(first, "st_file_attributes", 0) & REPARSE_ATTRIBUTE
            )
            if is_reparse:
                reparse_points.append(relative)
                continue
            if stat.S_ISDIR(first.st_mode):
                child_directories.append(absolute)
                continue
            if not stat.S_ISREG(first.st_mode):
                reparse_points.append(relative)
                continue
            sha256 = _sha256_file(absolute)
            second = absolute.stat(follow_symlinks=False)
            if (
                first.st_size != second.st_size
                or first.st_mtime_ns != second.st_mtime_ns
            ):
                raise RuntimeError(f"File changed while hashing: {relative}")
            files.append(
                ScannedFile(relative, first.st_size, sha256, _file_type(relative))
            )
        stack.extend(reversed(child_directories))

    files.sort(key=lambda item: _sort_key(item.path))
    reparse_points.sort(key=_sort_key)
    return files, reparse_points


def _metadata_value(message, name: str) -> str:
    value = message.get(name, "")
    return " ".join(value.split())


def _metadata_source(message) -> str:
    candidates: list[tuple[str, str]] = []
    for raw in message.get_all("Project-URL", []):
        label, separator, url = raw.partition(",")
        if separator:
            candidates.append((label.strip().casefold(), url.strip()))
    for preferred in ("source code", "source", "repository", "homepage"):
        for label, url in candidates:
            if label == preferred:
                return url
    return _metadata_value(message, "Home-page")


def _metadata_license(message) -> str:
    expression = _metadata_value(message, "License-Expression")
    if expression:
        return expression
    classifiers = [
        item.removeprefix("License ::").strip()
        for item in message.get_all("Classifier", [])
        if item.startswith("License ::")
    ]
    if classifiers:
        return " | ".join(sorted(classifiers))
    value = _metadata_value(message, "License")
    return value if value and value.casefold() != "unknown" else "NOASSERTION"


def read_python_package_ownership(
    root: Path, files: Iterable[ScannedFile]
) -> tuple[dict[str, list[str]], dict[str, Component]]:
    by_path = {item.path.casefold(): item for item in files}
    metadata_paths = sorted(
        (
            item.path
            for item in files
            if item.path.casefold().endswith(".dist-info/metadata")
        ),
        key=_sort_key,
    )
    owners: dict[str, list[str]] = {}
    components: dict[str, Component] = {}

    for metadata_relative in metadata_paths:
        metadata_path = root / Path(*PurePosixPath(metadata_relative).parts)
        message = Parser().parsestr(
            metadata_path.read_text(encoding="utf-8", errors="replace")
        )
        name = _metadata_value(message, "Name")
        version = _metadata_value(message, "Version")
        if not name or not version:
            continue
        normalized_name = canonical_name(name)
        component_id = STATIC_PACKAGE_KEYS.get(
            normalized_name, f"pypi:{normalized_name}@{version}"
        )
        if component_id not in STATIC_COMPONENTS:
            components[component_id] = Component(
                component_id=component_id,
                name=name,
                version=version,
                license=_metadata_license(message),
                source=_metadata_source(message),
                purl=f"pkg:pypi/{normalized_name}@{version}",
            )

        dist_info_relative = PurePosixPath(metadata_relative).parent
        site_root = dist_info_relative.parent
        record_relative = (dist_info_relative / "RECORD").as_posix()
        record_item = by_path.get(record_relative.casefold())
        if record_item is None:
            continue
        record_path = root / Path(*PurePosixPath(record_item.path).parts)
        with record_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.reader(handle):
                if not row:
                    continue
                record_name = row[0].replace("\\", "/")
                record_parts = PurePosixPath(record_name).parts
                if not record_parts or any(part in {"", ".", ".."} for part in record_parts):
                    continue
                candidate = (site_root / PurePosixPath(*record_parts)).as_posix()
                actual = by_path.get(candidate.casefold())
                if actual is None:
                    continue
                values = owners.setdefault(actual.path, [])
                if component_id not in values:
                    values.append(component_id)

    for values in owners.values():
        values.sort()
    return owners, components


def _add(values: list[str], *component_ids: str) -> None:
    for component_id in component_ids:
        if component_id not in values:
            values.append(component_id)


def explicit_native_mapping(path: str) -> tuple[list[str], str, str]:
    """Return component ids, rule name, and system-runtime provenance."""

    lower = path.casefold()
    base = PurePosixPath(lower).name
    components: list[str] = []
    reason = ""
    system_provenance = ""

    if lower == "chromamatter.exe":
        # A frozen entry point contains both the application archive and the
        # PyInstaller bootloader.  Keep the embedded build tool visible in the
        # component map/SBOM instead of attributing the whole executable only
        # to ChromaMatter.
        return ["chromamatter", "pyinstaller"], "frozen-application-entry-point", ""

    is_internal_root_file = lower.startswith("_internal/") and "/" not in (
        lower.removeprefix("_internal/")
    )
    if is_internal_root_file and (
        base.startswith("api-ms-win-") or base == "ucrtbase.dll"
    ):
        return (
            ["microsoft-ucrt-10.0.19041.1"],
            "explicit-system-runtime-allowlist",
            "Microsoft Universal CRT files carried by the pinned Windows runtime wheel",
        )

    if lower in {
        "_internal/msvcp140.dll",
        "_internal/msvcp140_1.dll",
        "_internal/vcomp140.dll",
    }:
        return ["msvc-14.50.35719"], "msvc-file-version", ""
    if lower in {
        "_internal/vcruntime140.dll",
        "_internal/vcruntime140_1.dll",
    }:
        return ["msvc-14.42.34438"], "msvc-file-version", ""
    if "msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll" in lower:
        return ["msvc-14.40.33810"], "msvc-file-version", ""
    if lower.startswith("_internal/pytetwild.libs/") and (
        base.startswith("msvcp140-") or base.startswith("concrt140-")
    ):
        return ["pytetwild", "msvc-14.44.35208"], "wheel-repair-runtime", ""
    if lower.startswith("_internal/shapely.libs/") and base.startswith("msvcp140-"):
        return ["shapely", "msvc-14.44.35215"], "wheel-repair-runtime", ""

    if lower in {"_internal/python3.dll", "_internal/python313.dll"}:
        return ["cpython"], "cpython-runtime", ""
    if lower.startswith("_internal/") and "/" not in lower.removeprefix("_internal/"):
        if base in PYTHON_STDLIB_NATIVE:
            _add(components, "cpython")
            if base in {"_ssl.pyd", "_hashlib.pyd"}:
                _add(components, "openssl")
            if base == "_sqlite3.pyd":
                _add(components, "sqlite")
            if base == "_tkinter.pyd":
                _add(components, "tcl-tk")
            return components, "cpython-standard-library-extension", ""
    if lower in {"_internal/libcrypto-3.dll", "_internal/libssl-3.dll"}:
        return ["openssl"], "cpython-runtime-dependency", ""
    if lower == "_internal/sqlite3.dll":
        return ["sqlite"], "cpython-runtime-dependency", ""
    if lower in {"_internal/tcl86t.dll", "_internal/tk86t.dll"}:
        return ["tcl-tk"], "cpython-runtime-dependency", ""
    if lower == "_internal/libffi-8.dll":
        return ["libffi"], "cpython-runtime-dependency", ""
    if lower == "_internal/zlib1.dll":
        return ["zlib"], "cpython-runtime-dependency", ""

    prefix_rules = (
        ("_internal/numpy/", "numpy"),
        ("_internal/numpy.libs/", "numpy"),
        ("_internal/scipy/", "scipy"),
        ("_internal/scipy.libs/", "scipy"),
        ("_internal/pil/", "pillow"),
        ("_internal/glcontext/", "glcontext"),
        ("_internal/moderngl/", "moderngl"),
        ("_internal/mapbox_earcut/", "mapbox-earcut"),
        ("_internal/resvg/", "resvg"),
        ("_internal/rtree/", "rtree"),
    )
    for prefix, component_id in prefix_rules:
        if lower.startswith(prefix):
            return [component_id], "pinned-wheel-path", ""
    if lower == "_internal/manifold3d.cp313-win_amd64.pyd":
        return ["manifold3d"], "pinned-wheel-path", ""
    if lower == "_internal/tetgen/_tetgen.pyd":
        return ["tetgen"], "tetgen-wrapper-with-static-core", ""
    if lower == "_internal/pytetwild/pyftetwildwrapper.pyd":
        return ["pytetwild"], "pytetwild-wrapper-with-static-ftetwild", ""
    if lower.startswith("_internal/pytetwild.libs/") and base.startswith("mpir-"):
        return ["pytetwild", "mpir"], "pytetwild-repaired-wheel-dependency", ""
    if lower.startswith("_internal/shapely/"):
        return ["shapely"], "pinned-wheel-path", ""
    if lower.startswith("_internal/shapely.libs/") and base.startswith("geos"):
        return ["shapely", "geos"], "shapely-repaired-wheel-dependency", ""

    if lower.startswith("_internal/pymeshlab/"):
        _add(components, "pymeshlab", "meshlab")
        reason = "pymeshlab-wheel-path"
        qt_plugin_parts = (
            "/bearer/",
            "/iconengines/",
            "/imageformats/",
            "/platforms/",
            "/styles/",
        )
        if base.startswith("qt5") or any(part in lower for part in qt_plugin_parts):
            _add(components, "qt")
        if base in {"libegl.dll", "libglesv2.dll"}:
            _add(components, "qt", "qt-angle")
        if base == "opengl32sw.dll":
            _add(components, "qt", "mesa-llvmpipe")
        if base in {"embree4.dll", "tbb12.dll"} or base == "filter_embree.dll":
            _add(components, "embree", "onetbb-pymeshlab")
        if base in {"xerces-c_3_2.dll"}:
            _add(components, "xerces-c")
        if base == "lib3mf.dll" or base == "io_3mf.dll":
            _add(components, "lib3mf")
        if base == "libgmp-10.dll":
            _add(components, "gmp")
        if base == "libmpfr-4.dll":
            _add(components, "mpfr")
        if base in {"e57format.dll", "io_e57.dll"}:
            _add(components, "libe57format")
        if base == "external-glew.dll":
            _add(components, "glew")
        if base in {"external-lib3ds.dll", "io_3ds.dll"}:
            _add(components, "lib3ds")
        if base.startswith("ifx") or base == "io_u3d.dll":
            _add(components, "u3d")
        if base == "muparser.dll":
            _add(components, "muparser")
        return components, reason, ""

    return [], "", ""


def detect_application_license(root: Path) -> str:
    candidates = (
        root / "licenses" / "LICENSE_APP.txt",
        root / "_internal" / "licenses" / "LICENSE_APP.txt",
    )
    pattern = re.compile(r"^SPDX-License-Identifier:\s*(\S.+?)\s*$", re.MULTILINE)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        match = pattern.search(candidate.read_text(encoding="utf-8", errors="replace"))
        if match:
            return match.group(1)
    # The release tree is licensed GPL-3.0-or-later.  A packaged
    # LICENSE_APP.txt remains authoritative when present, while this default
    # keeps source-tree and deliberately minimal test fixtures accurate.
    return "GPL-3.0-or-later"


def _component_payload(component: Component) -> dict:
    payload = {
        "id": component.component_id,
        "name": component.name,
        "version": component.version,
        "license": component.license,
        "source": component.source,
    }
    if component.purl:
        payload["purl"] = component.purl
    return payload


def _cyclonedx_licenses(value: str) -> list[dict]:
    # Package metadata sometimes contains a human-readable classifier rather
    # than a valid SPDX expression.  CycloneDX's named-license form preserves
    # that value without pretending it has been normalized by a legal review.
    return [{"license": {"name": value}}]


def build_inventories(root: Path) -> tuple[dict, dict]:
    files, reparse_points = scan_package_tree(root)
    owners, discovered_components = read_python_package_ownership(root, files)
    components = dict(STATIC_COMPONENTS)
    components.update(discovered_components)
    application = components["chromamatter"]
    components["chromamatter"] = Component(
        application.component_id,
        application.name,
        application.version,
        detect_application_license(root),
        application.source,
        application.purl,
    )

    mapped_files: list[dict] = []
    used_components: set[str] = set()
    unmapped_native: list[str] = []
    native_count = 0
    for item in files:
        native = PurePosixPath(item.path).suffix.lower() in NATIVE_SUFFIXES
        explicit, rule, system_provenance = explicit_native_mapping(item.path)
        package_owners = list(owners.get(item.path, []))
        component_ids = list(explicit)
        for owner in package_owners:
            if owner not in component_ids:
                component_ids.append(owner)
        component_ids.sort()
        if native:
            native_count += 1
            if not component_ids:
                unmapped_native.append(item.path)
        used_components.update(component_ids)
        row = asdict(item)
        row["package_owners"] = package_owners
        row["components"] = component_ids
        row["mapping_basis"] = rule or ("dist-info-record" if package_owners else "")
        if system_provenance:
            row["system_runtime_allowlist"] = {
                "provenance": system_provenance,
                "component": component_ids[0],
            }
        mapped_files.append(row)

    unmapped_native.sort(key=_sort_key)
    inventory_digest = hashlib.sha256()
    for item in files:
        inventory_digest.update(item.path.encode("utf-8"))
        inventory_digest.update(b"\0")
        inventory_digest.update(str(item.size).encode("ascii"))
        inventory_digest.update(b"\0")
        inventory_digest.update(item.sha256.encode("ascii"))
        inventory_digest.update(b"\n")
    package_digest = inventory_digest.hexdigest()
    validation = {
        "passed": not unmapped_native and not reparse_points,
        "file_count": len(files),
        "native_file_count": native_count,
        "mapped_native_file_count": native_count - len(unmapped_native),
        "unmapped_native_files": unmapped_native,
        "reparse_points_not_traversed": reparse_points,
    }

    component_map = {
        "schema": "https://github.com/Ponkichi0718/ChromaMatter/schemas/binary-component-map-v1",
        "schema_version": 1,
        "generator": {
            "name": GENERATOR_NAME,
            "version": GENERATOR_VERSION,
        },
        "package": {
            "name": "ChromaMatter",
            "version": application.version,
            "root": ".",
            "content_sha256": package_digest,
        },
        "components": [
            _component_payload(components[key])
            for key in sorted(used_components)
            if key in components
        ],
        "files": mapped_files,
        "validation": validation,
    }

    library_components = []
    for key in sorted(used_components):
        if key not in components or key == "chromamatter":
            continue
        component = components[key]
        payload = {
            "type": "library",
            "bom-ref": f"component:{key}",
            "name": component.name,
            "version": component.version,
            "licenses": _cyclonedx_licenses(component.license),
            "externalReferences": [
                {"type": "website", "url": component.source}
            ],
        }
        if component.purl:
            payload["purl"] = component.purl
        library_components.append(payload)

    file_components = []
    for row in mapped_files:
        properties = [
            {"name": "chromamatter:file:size", "value": str(row["size"])},
            {"name": "chromamatter:file:type", "value": row["file_type"]},
        ]
        if row["components"]:
            properties.append(
                {
                    "name": "chromamatter:file:components",
                    "value": ",".join(row["components"]),
                }
            )
        file_components.append(
            {
                "type": "file",
                "bom-ref": f"file:{row['path']}",
                "name": row["path"],
                "hashes": [{"alg": "SHA-256", "content": row["sha256"]}],
                "properties": properties,
            }
        )

    app_component = components["chromamatter"]
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:"
        + str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "https://github.com/Ponkichi0718/ChromaMatter/binary/"
                + package_digest,
            )
        ),
        "version": 1,
        "metadata": {
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": GENERATOR_NAME,
                        "version": GENERATOR_VERSION,
                    }
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": "component:chromamatter",
                "name": app_component.name,
                "version": app_component.version,
                "licenses": _cyclonedx_licenses(app_component.license),
                "hashes": [{"alg": "SHA-256", "content": package_digest}],
            },
            "properties": [
                {
                    "name": "chromamatter:validation:passed",
                    "value": str(validation["passed"]).lower(),
                },
                {
                    "name": "chromamatter:validation:unmapped-native-count",
                    "value": str(len(unmapped_native)),
                },
                {
                    "name": "chromamatter:validation:reparse-count",
                    "value": str(len(reparse_points)),
                },
            ],
        },
        "components": library_components + file_components,
        "dependencies": [
            {
                "ref": "component:chromamatter",
                "dependsOn": [
                    f"component:{key}"
                    for key in sorted(used_components)
                    if key != "chromamatter" and key in components
                ],
            }
        ],
    }
    return sbom, component_map


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
    ) as handle:
        handle.write(serialized)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _outside_root(output: Path, root: Path) -> Path:
    # ``resolve(strict=False)`` follows any existing parent junction/symlink.
    # Plain ``abspath`` would allow an apparently external output path to point
    # back into the package tree through a reparse point.
    absolute = Path(os.path.abspath(output)).resolve(strict=False)
    try:
        absolute.relative_to(root)
    except ValueError:
        return absolute
    raise ValueError(
        "Inventory outputs must be outside the scanned package root to avoid "
        "self-referential hashes."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--sbom-output", required=True, type=Path)
    parser.add_argument("--component-map-output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.package_root.resolve(strict=True)
    sbom_output = _outside_root(args.sbom_output, root)
    component_output = _outside_root(args.component_map_output, root)
    if sbom_output == component_output:
        raise ValueError("SBOM and component-map outputs must be different files.")
    sbom, component_map = build_inventories(root)
    _write_json_atomic(sbom_output, sbom)
    _write_json_atomic(component_output, component_map)

    validation = component_map["validation"]
    if validation["unmapped_native_files"]:
        print("Unmapped native files:", file=sys.stderr)
        for path in validation["unmapped_native_files"]:
            print(f"  {path}", file=sys.stderr)
    if validation["reparse_points_not_traversed"]:
        print("Reparse points were not traversed:", file=sys.stderr)
        for path in validation["reparse_points_not_traversed"]:
            print(f"  {path}", file=sys.stderr)
    if not validation["passed"]:
        return 2
    print(
        "Compliance inventory passed: "
        f"{validation['file_count']} files, "
        f"{validation['native_file_count']} native files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
