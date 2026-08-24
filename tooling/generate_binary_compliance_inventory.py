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

try:
    from tooling.pytetwild_static_closure_contract import (
        HISTORICAL_PYTETWILD_PYD_SHA256,
        load_pytetwild_static_closure_contract,
    )
except ModuleNotFoundError:  # Direct ``python tooling/...py`` execution.
    from pytetwild_static_closure_contract import (  # type: ignore[no-redef]
        HISTORICAL_PYTETWILD_PYD_SHA256,
        load_pytetwild_static_closure_contract,
    )


GENERATOR_NAME = "ChromaMatter binary compliance inventory"
GENERATOR_VERSION = "1"
NATIVE_SUFFIXES = {".dll", ".exe", ".pyd"}
REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
REPO_ROOT = Path(__file__).resolve().parent.parent
PYMESHLAB_NATIVE_IDENTITIES_PATH = (
    REPO_ROOT / "tooling" / "pymeshlab_audited_native_identities.json"
)
QT_STATIC_COMPONENTS_PATH = REPO_ROOT / "tooling" / "qt_static_components.json"
PINNED_PYMESHLAB_VERSION = "2025.7.post1"
PINNED_PYMESHLAB_WHEEL_SHA256 = (
    "25eb2578dd6c4d1b2e0253fb3b4f8f7895e8bb4f3f1236832db0ab58e6a44998"
)
PINNED_PYMESHLAB_SOURCE_COMMIT = (
    "1dc199f9b6c43e58b6db346ba4600866b950b8ae"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PYTETWILD_STATIC_CLOSURE_MAPPING_BASIS = (
    "controlled-pytetwild-static-closure"
)
PYTETWILD_STATIC_CLOSURE_VIOLATION_CODES = frozenset(
    {
        "application-lock-historical-wheel-forbidden",
        "application-lock-wheel-identity-mismatch",
        "historical-wrapper-forbidden",
        "manifest-release-blocked",
        "wrapper-missing",
        "wrapper-path-case-mismatch",
        "wrapper-sha256-mismatch",
    }
)


@dataclass(frozen=True)
class Component:
    component_id: str
    name: str
    version: str
    license: str
    source: str
    purl: str = ""
    license_assets: tuple[str, ...] = ()
    license_is_spdx: bool = True


@dataclass(frozen=True)
class ScannedFile:
    path: str
    size: int
    sha256: str
    file_type: str


@dataclass(frozen=True)
class AuditedNativeIdentity:
    path: str
    size: int
    sha256: str
    component_ids: tuple[str, ...]
    source_manifest: str


def _component(
    component_id: str,
    name: str,
    version: str,
    license_expression: str,
    source: str,
    purl: str = "",
    license_assets: tuple[str, ...] = (),
    license_is_spdx: bool = True,
) -> Component:
    return Component(
        component_id,
        name,
        version,
        license_expression,
        source,
        purl,
        license_assets,
        license_is_spdx,
    )


def _load_json_object(path: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot load canonical {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Canonical {label} must be a JSON object: {path}")
    return payload


def _require_exact_keys(value: dict, expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        raise RuntimeError(
            f"{context} has unexpected fields: "
            f"missing={sorted(expected - actual)!r}, extra={sorted(actual - expected)!r}"
        )


def _require_safe_package_path(
    value: object,
    context: str,
    *,
    prefix: str,
    suffix: str = "",
) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError(f"{context} is not a canonical package path: {value!r}")
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or parsed.as_posix() != value
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or not value.startswith(prefix)
        or (suffix and not value.casefold().endswith(suffix.casefold()))
    ):
        raise RuntimeError(f"{context} is not a canonical package path: {value!r}")
    return value


def _require_sha256(value: object, context: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise RuntimeError(f"{context} is not a lowercase SHA-256 value")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


STATIC_COMPONENTS = {
    item.component_id: item
    for item in (
        _component(
            "chromamatter",
            "ChromaMatter",
            "0.8beta-r32.2",
            "GPL-3.0-or-later",
            "https://github.com/Ponkichi0718/ChromaMatter",
            license_assets=("_internal/licenses/LICENSE_APP.txt",),
        ),
        _component(
            "cpython",
            "CPython",
            "3.13.14",
            "Python-2.0",
            "https://github.com/python/cpython/tree/v3.13.14",
            "pkg:generic/cpython@3.13.14",
            ("_internal/licenses/cpython/LICENSE.txt",),
        ),
        _component(
            "cpython-bzip2",
            "bzip2 / libbzip2 carried by CPython",
            "1.0.8",
            "bzip2-1.0.6",
            "https://github.com/python/cpython-source-deps/tree/"
            "05301997b2f9590f49c672cf3dfd3d3dfa7ad521",
            "pkg:generic/bzip2@1.0.8",
            ("_internal/licenses/LICENSE_CPYTHON_BZIP2.txt",),
        ),
        _component(
            "cpython-liblzma",
            "XZ Utils liblzma carried by CPython",
            "5.2.5",
            "LicenseRef-XZ-Utils-Public-Domain",
            "https://github.com/python/cpython-source-deps/tree/"
            "c6bc0c612605622aaef101a33a751f9de2ecc193",
            "pkg:generic/xz@5.2.5",
            ("_internal/licenses/LICENSE_CPYTHON_XZ.txt",),
        ),
        _component(
            "cpython-expat",
            "Expat carried by CPython",
            "2.8.1",
            "MIT",
            "https://github.com/python/cpython/tree/"
            "fd17997c3866d61e0e7bd8201b1d8f35b40a40bd/Modules/expat",
            "pkg:generic/expat@2.8.1",
            ("_internal/licenses/LICENSE_CPYTHON_EXPAT.txt",),
        ),
        _component(
            "cpython-libmpdec",
            "libmpdec carried by CPython",
            "4.0.0",
            "BSD-2-Clause",
            "https://github.com/python/cpython-source-deps/tree/"
            "780e21d43a92832d12c2add68fcc8e03cee38bcf",
            "pkg:generic/libmpdec@4.0.0",
            ("_internal/licenses/LICENSE_CPYTHON_LIBMPDEC.txt",),
        ),
        _component(
            "pyinstaller",
            "PyInstaller bootloader and run-time hooks",
            "6.20.0",
            "(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0",
            "https://github.com/pyinstaller/pyinstaller/tree/v6.20.0",
            "pkg:pypi/pyinstaller@6.20.0",
            ("_internal/licenses/pyinstaller/COPYING.txt",),
        ),
        _component(
            "openssl",
            "OpenSSL",
            "3.0.21",
            "Apache-2.0",
            "https://github.com/openssl/openssl/tree/openssl-3.0.21",
            license_assets=("_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt",),
        ),
        _component(
            "sqlite",
            "SQLite",
            "3.50.4",
            "LicenseRef-SQLite-Public-Domain",
            "https://github.com/python/cpython-source-deps/tree/"
            "c8123bc55da6467f4ef3e9b70cdb67cecf33b937",
            license_assets=("_internal/licenses/NOTICE_SQLITE_PUBLIC_DOMAIN.txt",),
        ),
        _component(
            "tcl-tk",
            "Tcl/Tk",
            "8.6.15",
            "TCL",
            "https://www.tcl.tk/software/tcltk/8.6.html",
            license_assets=("_internal/licenses/tcl-tk/license.terms",),
        ),
        _component(
            "libffi",
            "libffi runtime",
            "ABI 8",
            "MIT",
            "https://github.com/libffi/libffi",
            license_assets=("_internal/licenses/cpython/LICENSE.txt",),
        ),
        _component(
            "zlib",
            "zlib",
            "1.3.1",
            "Zlib",
            "https://github.com/madler/zlib/tree/v1.3.1",
            license_assets=("_internal/licenses/LICENSE_LIB3MF_ZLIB.txt",),
        ),
        _component(
            "microsoft-ucrt-10.0.19041.1",
            "Microsoft Universal C Runtime",
            "10.0.19041.1",
            "LicenseRef-Microsoft-Windows-SDK-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
            # The audited package does not carry UCRT/API-set binaries.  Keep
            # the ownership rule for future builds, but intentionally declare
            # no asset: if such a file is ever bundled, validation must stop
            # until the exact Microsoft redistributable terms are reviewed.
        ),
        _component(
            "msvc-14.50.35719",
            "Microsoft Visual C++ Runtime",
            "14.50.35719",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
            license_assets=("_internal/licenses/msvc-runtime/LICENSE",),
        ),
        _component(
            "msvc-14.42.34438",
            "Microsoft Visual C++ Runtime",
            "14.42.34438",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
            license_assets=("_internal/licenses/msvc-runtime/LICENSE",),
        ),
        _component(
            "msvc-14.40.33810",
            "Microsoft Visual C++ Runtime",
            "14.40.33810",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
            license_assets=("_internal/licenses/msvc-runtime/LICENSE",),
        ),
        _component(
            "msvc-14.44.35211",
            "Microsoft Visual C++ Runtime",
            "14.44.35211",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
            license_assets=("_internal/licenses/msvc-runtime/LICENSE",),
        ),
        _component(
            "msvc-14.44.35215",
            "Microsoft Visual C++ Runtime",
            "14.44.35215",
            "LicenseRef-Microsoft-Visual-Cpp-Redistributable",
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
            license_assets=("_internal/licenses/msvc-runtime/LICENSE",),
        ),
        _component(
            "numpy",
            "NumPy",
            "2.5.1",
            "BSD-3-Clause",
            "https://github.com/numpy/numpy/tree/v2.5.1",
            "pkg:pypi/numpy@2.5.1",
            ("_internal/licenses/numpy/LICENSE.txt",),
        ),
        _component(
            "scipy",
            "SciPy",
            "1.18.0",
            "BSD-3-Clause",
            "https://github.com/scipy/scipy/tree/v1.18.0",
            "pkg:pypi/scipy@1.18.0",
            ("_internal/licenses/scipy/LICENSE.txt",),
        ),
        _component(
            "pillow",
            "Pillow",
            "11.2.1",
            "HPND",
            "https://github.com/python-pillow/Pillow/tree/11.2.1",
            "pkg:pypi/pillow@11.2.1",
            ("_internal/licenses/pillow/LICENSE",),
        ),
        _component(
            "moderngl",
            "ModernGL",
            "5.12.0",
            "MIT",
            "https://github.com/moderngl/moderngl/tree/5.12.0",
            "pkg:pypi/moderngl@5.12.0",
            ("_internal/licenses/moderngl/LICENSE",),
        ),
        _component(
            "glcontext",
            "glcontext",
            "3.0.0",
            "MIT",
            "https://github.com/moderngl/glcontext/tree/3.0.0",
            "pkg:pypi/glcontext@3.0.0",
            ("_internal/licenses/glcontext/LICENSE",),
        ),
        _component(
            "manifold3d",
            "Manifold3D",
            "3.5.2",
            "Apache-2.0",
            "https://github.com/elalish/manifold/tree/v3.5.2",
            "pkg:pypi/manifold3d@3.5.2",
            ("_internal/licenses/manifold3d/LICENSE",),
        ),
        _component(
            "mapbox-earcut",
            "mapbox-earcut",
            "2.0.0",
            "ISC",
            "https://github.com/skogler/mapbox_earcut_python/tree/v2.0.0",
            "pkg:pypi/mapbox-earcut@2.0.0",
            ("_internal/licenses/mapbox-earcut/LICENSE.md",),
        ),
        _component(
            "rtree",
            "Rtree",
            "1.4.1",
            "MIT",
            "https://github.com/Toblerity/rtree/tree/1.4.1",
            "pkg:pypi/rtree@1.4.1",
            ("_internal/licenses/rtree/LICENSE.txt",),
        ),
        _component(
            "libspatialindex",
            "libspatialindex bundled by Rtree",
            "2.1.0",
            "MIT",
            "https://github.com/libspatialindex/libspatialindex/tree/"
            "175b56a9541e76982d13dbbf0c9b8f0b8d752619",
            "pkg:generic/libspatialindex@2.1.0",
            ("_internal/licenses/LICENSE_LIBSPATIALINDEX_2_1_0.txt",),
        ),
        _component(
            "tetgen",
            "tetgen Python wrapper and modified TetGen core",
            "0.8.3 / 1.6.0",
            "MIT AND AGPL-3.0-or-later",
            "https://github.com/pyvista/tetgen/tree/v0.8.3",
            "pkg:pypi/tetgen@0.8.3",
            (
                "_internal/licenses/tetgen/LICENSE",
                "_internal/licenses/tetgen/tetgen-license",
            ),
        ),
        _component(
            "pytetwild",
            "PyTetWild / fTetWild",
            "0.3.0 / d7d99bb4387a07895b9adce058dc7305f6b6e5ab",
            "MPL-2.0",
            "https://github.com/pyvista/pytetwild/tree/v0.3.0",
            "pkg:pypi/pytetwild@0.3.0",
            ("_internal/licenses/pytetwild/LICENSE",),
        ),
        _component(
            "mpir",
            "MPIR",
            "3.0.0",
            "LGPL-3.0-or-later AND GPL-3.0-or-later",
            "https://github.com/wbhart/mpir/tree/mpir-3.0.0",
            license_assets=(
                "_internal/licenses/LGPL-3.0.txt",
                "_internal/licenses/GPL-3.0.txt",
            ),
        ),
        _component(
            "pymeshlab",
            "PyMeshLab",
            "2025.7.post1",
            "GPL-3.0-only",
            "https://github.com/cnr-isti-vclab/PyMeshLab/tree/v2025.7.post1",
            "pkg:pypi/pymeshlab@2025.7.post1",
            ("_internal/licenses/pymeshlab/LICENSE",),
        ),
        _component(
            "meshlab",
            "MeshLab / VCGLib",
            "d876376e3cc4f92d257e248023d82cbac5b03c7d",
            "GPL-3.0-only",
            "https://github.com/cnr-isti-vclab/meshlab/tree/"
            "d876376e3cc4f92d257e248023d82cbac5b03c7d",
            license_assets=("_internal/licenses/GPL-3.0.txt",),
        ),
        _component(
            "qt",
            "Qt",
            "5.15.2",
            "LGPL-3.0-only",
            "https://download.qt.io/archive/qt/5.15/5.15.2/single/",
            "pkg:generic/qt@5.15.2",
            (
                "_internal/licenses/LICENSE_QT_LGPL_3_0.txt",
                "_internal/licenses/NOTICE_QT.txt",
            ),
        ),
        _component(
            "mesa-llvmpipe",
            "Mesa llvmpipe distributed by Qt",
            "12.0.0-rc2",
            "MIT AND BSL-1.0",
            "https://download.qt.io/development_releases/prebuilt/llvmpipe/windows/",
            license_assets=(
                "_internal/licenses/LICENSE_MESA_12_0_RC2.html",
                "_internal/licenses/NOTICE_MESA_LLVM.txt",
            ),
        ),
        _component(
            "llvm-mesa",
            "LLVM statically linked into Mesa llvmpipe",
            "3.6.2",
            "NCSA",
            "https://releases.llvm.org/3.6.2/",
            "pkg:generic/llvm@3.6.2",
            ("_internal/licenses/LICENSE_LLVM_3_6_2.txt",),
        ),
        _component(
            "embree",
            "Intel Embree",
            "4.3.3",
            "Apache-2.0",
            "https://github.com/RenderKit/embree/tree/v4.3.3",
            license_assets=("_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt",),
        ),
        _component(
            "onetbb-pymeshlab",
            "oneTBB",
            "2021.11.0",
            "Apache-2.0",
            "https://github.com/uxlfoundation/oneTBB/tree/v2021.11.0",
            license_assets=("_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt",),
        ),
        _component(
            "xerces-c",
            "Xerces-C++",
            "3.2.4",
            "Apache-2.0",
            "https://github.com/apache/xerces-c/tree/v3.2.4",
            license_assets=(
                "_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt",
                "_internal/licenses/NOTICE_XERCES_C_3_2_4.txt",
            ),
        ),
        _component(
            "lib3mf",
            "lib3mf",
            "2.4.1",
            "BSD-2-Clause",
            "https://github.com/3MFConsortium/lib3mf/tree/v2.4.1",
            license_assets=("_internal/licenses/LICENSE_LIB3MF.txt",),
        ),
        _component(
            "lib3mf-cpp-base64",
            "cpp-base64 statically linked into lib3mf",
            "V2.rc.08",
            "Zlib",
            "https://github.com/ReneNyffenegger/cpp-base64/tree/V2.rc.08",
            license_assets=(
                "_internal/licenses/LICENSE_LIB3MF_CPP_BASE64.txt",
            ),
        ),
        _component(
            "lib3mf-fast-float",
            "fast_float statically linked into lib3mf",
            "6.0.0",
            "MIT",
            "https://github.com/fastfloat/fast_float/tree/v6.0.0",
            "pkg:generic/fast_float@6.0.0",
            ("_internal/licenses/LICENSE_LIB3MF_FAST_FLOAT.txt",),
        ),
        _component(
            "lib3mf-zlib",
            "zlib statically linked into lib3mf",
            "1.3.1",
            "Zlib",
            "https://github.com/3MFConsortium/lib3mf/tree/"
            "20c335489c69d15c64f3eaf1e15143b8176901f5/submodules/zlib",
            "pkg:generic/zlib@1.3.1",
            ("_internal/licenses/LICENSE_LIB3MF_ZLIB.txt",),
        ),
        _component(
            "lib3mf-libzip",
            "libzip statically linked into lib3mf",
            "1.10.1",
            "BSD-3-Clause",
            "https://github.com/nih-at/libzip/tree/v1.10.1",
            "pkg:generic/libzip@1.10.1",
            ("_internal/licenses/LICENSE_LIB3MF_LIBZIP.txt",),
        ),
        _component(
            "gmp",
            "GMP",
            "5.0.1",
            "LGPL-3.0-or-later OR GPL-2.0-or-later",
            "https://gmplib.org/",
            license_assets=("_internal/licenses/LGPL-3.0.txt",),
        ),
        _component(
            "mpfr",
            "MPFR",
            "3.0.0",
            "LGPL-3.0-or-later",
            "https://www.mpfr.org/mpfr-3.0.0/",
            license_assets=("_internal/licenses/LGPL-3.0.txt",),
        ),
        _component(
            "libe57format",
            "libE57Format",
            "3.1.1",
            "BSL-1.0",
            "https://github.com/asmaloney/libE57Format/tree/v3.1.1",
            license_assets=(
                "_internal/licenses/LICENSE_LIBE57FORMAT_3_1_1.md",
            ),
        ),
        _component(
            "glew",
            "GLEW",
            "2.2.0",
            "BSD-3-Clause AND MIT",
            "https://github.com/nigels-com/glew/tree/glew-2.2.0",
            license_assets=("_internal/licenses/LICENSE_GLEW_2_2_0.txt",),
        ),
        _component(
            "lib3ds",
            "lib3ds",
            "1.3.0",
            "LGPL-2.1-or-later",
            "https://github.com/cnr-isti-vclab/meshlab/blob/"
            "d876376e3cc4f92d257e248023d82cbac5b03c7d/"
            "src/external/lib3ds.cmake",
            license_assets=("_internal/licenses/LGPL-2.1.txt",),
        ),
        _component(
            "u3d",
            "U3D",
            "1.5.2",
            "Apache-2.0",
            "https://github.com/alemuntoni/u3d/tree/1.5.2",
            license_assets=(
                "_internal/licenses/LICENSE_U3D.txt",
                "_internal/licenses/NOTICE_U3D_ADDITIONAL.txt",
            ),
        ),
        _component(
            "u3d-zlib",
            "zlib statically linked into U3D IFXCore",
            "1.2.8",
            "Zlib",
            "https://github.com/alemuntoni/u3d/tree/"
            "b0de4e7f829228d09552bd012c7376dd1d27c584/RTL/Dependencies/zlib",
            "pkg:generic/zlib@1.2.8",
            ("_internal/licenses/LICENSE_U3D_ZLIB.txt",),
        ),
        _component(
            "u3d-libpng",
            "libpng statically linked into U3D IFXCore",
            "1.6.2",
            "Libpng",
            "https://github.com/alemuntoni/u3d/tree/"
            "b0de4e7f829228d09552bd012c7376dd1d27c584/RTL/Dependencies/png",
            "pkg:generic/libpng@1.6.2",
            ("_internal/licenses/LICENSE_U3D_LIBPNG.txt",),
        ),
        _component(
            "u3d-ijg-jpeg",
            "Independent JPEG Group JPEG statically linked into U3D IFXCore",
            "9",
            "IJG",
            "https://github.com/alemuntoni/u3d/tree/"
            "b0de4e7f829228d09552bd012c7376dd1d27c584/RTL/Dependencies/jpeg",
            license_assets=("_internal/licenses/LICENSE_U3D_IJG_JPEG.txt",),
        ),
        _component(
            "u3d-fnvhash",
            "FNVHash statically linked into U3D IFXCore",
            "1.5",
            "LicenseRef-FNV-Public-Domain",
            "https://github.com/alemuntoni/u3d/blob/"
            "b0de4e7f829228d09552bd012c7376dd1d27c584/"
            "RTL/Dependencies/FNVHash/FNVPlusPlus.h",
            license_assets=(
                "_internal/licenses/NOTICE_U3D_ADDITIONAL.txt",
                "_internal/licenses/NOTICE_U3D_FNVHASH.txt",
            ),
        ),
        _component(
            "u3d-shewchuk-predicates",
            "Shewchuk robust predicates statically linked into U3D IFXCore",
            "1996-05-18",
            "LicenseRef-Shewchuk-Public-Domain",
            "https://github.com/alemuntoni/u3d/blob/"
            "b0de4e7f829228d09552bd012c7376dd1d27c584/"
            "RTL/Dependencies/Predicates/predicates.cpp",
            license_assets=(
                "_internal/licenses/NOTICE_U3D_ADDITIONAL.txt",
                "_internal/licenses/NOTICE_U3D_SHEWCHUK_PREDICATES.txt",
            ),
        ),
        _component(
            "u3d-wcmatch",
            "wcmatch statically linked into U3D IFXCore",
            "0.5",
            "LicenseRef-WCMATCH-Freeware",
            "https://github.com/alemuntoni/u3d/tree/"
            "b0de4e7f829228d09552bd012c7376dd1d27c584/"
            "RTL/Dependencies/WildCards",
            license_assets=(
                "_internal/licenses/NOTICE_U3D_ADDITIONAL.txt",
                "_internal/licenses/LICENSE_U3D_WCMATCH.txt",
            ),
        ),
        _component(
            "u3d-graphics-gems-iv",
            "Graphics Gems IV Delaunay code modified in U3D IFXCore",
            "1994",
            "Apache-2.0 AND LicenseRef-Graphics-Gems-Unrestricted",
            "https://github.com/alemuntoni/u3d/blob/"
            "b0de4e7f829228d09552bd012c7376dd1d27c584/"
            "RTL/Component/Generators/Glyph2D/CIFXQuadEdge.cpp",
            license_assets=(
                "_internal/licenses/LICENSE_U3D.txt",
                "_internal/licenses/NOTICE_U3D_ADDITIONAL.txt",
                "_internal/licenses/NOTICE_U3D_GRAPHICS_GEMS_IV.txt",
            ),
        ),
        _component(
            "u3d-nick-bobic-quaternion",
            "Nick Bobic quaternion code modified in U3D IFXCore",
            "1998-02",
            "Apache-2.0 AND Zlib",
            "https://github.com/alemuntoni/u3d/blob/"
            "b0de4e7f829228d09552bd012c7376dd1d27c584/"
            "RTL/Kernel/Include/IFXQuaternion.h",
            license_assets=(
                "_internal/licenses/LICENSE_U3D.txt",
                "_internal/licenses/NOTICE_U3D_ADDITIONAL.txt",
                "_internal/licenses/LICENSE_U3D_NICK_BOBIC_QUATERNION.txt",
            ),
        ),
        _component(
            "muparser",
            "muparser",
            "2.3.5",
            "BSD-2-Clause",
            "https://github.com/beltoforion/muparser/tree/v2.3.5",
            license_assets=("_internal/licenses/LICENSE_MUPARSER_2_3_5.txt",),
        ),
        _component(
            "shapely",
            "Shapely",
            "2.1.2",
            "BSD-3-Clause",
            "https://github.com/shapely/shapely/tree/2.1.2",
            "pkg:pypi/shapely@2.1.2",
            ("_internal/licenses/shapely/LICENSE.txt",),
        ),
        _component(
            "geos",
            "GEOS",
            "3.13.1",
            "LGPL-2.1-or-later",
            "https://github.com/libgeos/geos/tree/3.13.1",
            "pkg:generic/geos@3.13.1",
            ("_internal/licenses/shapely/LICENSE_GEOS",),
        ),
        _component(
            "trimesh",
            "trimesh",
            "5.0.0",
            "MIT",
            "https://github.com/mikedh/trimesh/tree/5.0.0",
            "pkg:pypi/trimesh@5.0.0",
            ("_internal/licenses/trimesh/LICENSE.md",),
        ),
    )
}

# Exact bytes expected in a binary package for every component-specific
# governing text.  These digests bind the packaged assets to the reviewed
# source inputs/notices rather than accepting an empty or unrelated file with
# the expected name.  CPython's digest is the LICENSE.txt installed by the
# pinned official Windows CPython 3.13.14 runtime.
LICENSE_ASSET_SHA256 = {
    "_internal/licenses/cpython/LICENSE.txt":
        "62bec384df47b0328307db41455ff6ea2559e5546b394ac69148561b21703120",
    "_internal/licenses/LICENSE_CPYTHON_BZIP2.txt":
        "c6dbbf828498be844a89eaa3b84adbab3199e342eb5cb2ed2f0d4ba7ec0f38a3",
    "_internal/licenses/LICENSE_CPYTHON_EXPAT.txt":
        "31b15de82aa19a845156169a17a5488bf597e561b2c318d159ed583139b25e87",
    "_internal/licenses/LICENSE_CPYTHON_LIBMPDEC.txt":
        "2713324211652ce4a60e6e21e54f9dc3004299e591b0933a352f1a89c5fb53c2",
    "_internal/licenses/LICENSE_CPYTHON_XZ.txt":
        "bcb02973ef6e87ea73d331b3a80df7748407f17efdb784b61b47e0e610d3bb5c",
    "_internal/licenses/LICENSE_LIB3MF.txt":
        "0b9774586d7ce2374a17834e7734bb545c539f3c85acc99624ba2fda5900cccc",
    "_internal/licenses/LICENSE_LIB3MF_CPP_BASE64.txt":
        "225e4f90a91b20bd0e19b5ded35dc2689a046a8859ecd6fb606770972d16040d",
    "_internal/licenses/LICENSE_LIB3MF_FAST_FLOAT.txt":
        "e562f3f974ced7e69dd1db77b820b36bcf8f30377f1aa105723fba449c53c4e6",
    "_internal/licenses/LICENSE_LIB3MF_LIBZIP.txt":
        "01c022eca6d566e2e8792fd0f091a28653b2a608319922bcd4de91c49d1438e1",
    "_internal/licenses/LICENSE_LIB3MF_ZLIB.txt":
        "845efc77857d485d91fb3e0b884aaa929368c717ae8186b66fe1ed2495753243",
    "_internal/licenses/LICENSE_LLVM_3_6_2.txt":
        "e3bc36440fc927c62d5cc24efeefe225a14d4e34ffeb0c92e430625cce9ee444",
    "_internal/licenses/LICENSE_MESA_12_0_RC2.html":
        "cbe57ea6c5a26c334dd11d62b46e723a9cfea6faa879fa5a44c115e2d4e1aa01",
    "_internal/licenses/LICENSE_QT_ANGLE.txt":
        "77af9c9fc2710ee66b8282291a9392a9a61f1d5b3ad6e478d0b6c544de5f9aca",
    "_internal/licenses/LICENSE_QT_LGPL_3_0.txt":
        "da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768",
    "_internal/licenses/LICENSE_U3D.txt":
        "c95bae1d1ce0235ecccd3560b772ec1efb97f348a79f0fbe0a634f0c2ccefe2c",
    "_internal/licenses/LICENSE_U3D_IJG_JPEG.txt":
        "96f90664b7ff2b7b8dfa58a5729d5d17c0512fe4eaef9bfde3a425c069383b0c",
    "_internal/licenses/LICENSE_U3D_NICK_BOBIC_QUATERNION.txt":
        "14d09c83a5bb7610ceefbb64873c208497a25480c61cb2d1467919937f489c33",
    "_internal/licenses/LICENSE_U3D_LIBPNG.txt":
        "ff47dc1785a1cc29780aa3b784056d30aae9e94a8369eea78c0bc29cfb903db1",
    "_internal/licenses/LICENSE_U3D_ZLIB.txt":
        "e84272121a333ae1ed222a953cbc067bab13d18724446300e8f49bbaceccfdaf",
    "_internal/licenses/LICENSE_U3D_WCMATCH.txt":
        "8cc9f62f6a0a4b947d11fd8fdf21c719fd4430c3a8328983e799b0c08ae6d039",
    "_internal/licenses/NOTICE_MESA_LLVM.txt":
        "aa0a952a1dd8f0d8c7368ec84a1db8f3ab1e01643c8722bf9c139ed3aad8114c",
    "_internal/licenses/NOTICE_QT.txt":
        "4e7c529497440a48fdefaa21514425d193d33eabac3139ccb46a65348965d337",
    "_internal/licenses/NOTICE_U3D_ADDITIONAL.txt":
        "4104dbe308b04c58b202a4f9697c261f2ac176c118756f2bc72585017349f227",
    "_internal/licenses/NOTICE_U3D_FNVHASH.txt":
        "47a70773721eb8dc9051469aa41d5445a88e7465314904989892e0030fb4b91e",
    "_internal/licenses/NOTICE_U3D_GRAPHICS_GEMS_IV.txt":
        "2e8f143f641facb2ceed3c4bbd56abeb792b7d24ebcbe894fa411683d0875445",
    "_internal/licenses/NOTICE_U3D_SHEWCHUK_PREDICATES.txt":
        "3394615532a97dc5f4c1999ad7565d5afde54a0ce6ba0b7f770c84b2b666e99d",
    "_internal/licenses/GPL-3.0.txt":
        "230184f60bae2feaf244f10a8bac053c8ff33a183bcc365b4d8b876d2b7f4809",
    "_internal/licenses/LGPL-2.1.txt":
        "138b2c2f9450073d7c116abe397ca4382625671c752b7a9a5f320b33fc3f3f2a",
    "_internal/licenses/LGPL-3.0.txt":
        "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
    "_internal/licenses/LICENSE_APP.txt":
        "c70d1d656a8f458cd1aac55aa1b0613d2fba9c3f724d32ab652eeb36d6737285",
    "_internal/licenses/LICENSE_GLEW_2_2_0.txt":
        "8991cd11befec7c6a63662700f03c0cc42e864b6e77c7e70b80297c951a7f0ff",
    "_internal/licenses/LICENSE_LIBE57FORMAT_3_1_1.md":
        "c9bff75738922193e67fa726fa225535870d2aa1059f91452c411736284ad566",
    "_internal/licenses/LICENSE_LIBSPATIALINDEX_2_1_0.txt":
        "b63ebfaca9d7ce582580f3e11acabc9d2e37c46ce234533f7fa8a6c7278898a0",
    "_internal/licenses/LICENSE_MUPARSER_2_3_5.txt":
        "3f8478de95e7204280324fe148fd5b15e1599ba007aad1494abffc631e8b81a5",
    "_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt":
        "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    "_internal/licenses/NOTICE_SQLITE_PUBLIC_DOMAIN.txt":
        "6df44914b7626e1a88a86540f02281db308899af2142cc1021cf01f61988971d",
    "_internal/licenses/NOTICE_XERCES_C_3_2_4.txt":
        "95e5cca2ff3d0801841d9d17f0eec16bfb02dd6893ff7e55da4ec5a5dd30aa52",
    "_internal/licenses/glcontext/LICENSE":
        "e16bf53d871fd580e43c800aacd8e10aa7a49505701aceec1f708aeaac97dfa7",
    "_internal/licenses/manifold3d/LICENSE":
        "1eb85fc97224598dad1852b5d6483bbcf0aa8608790dcc657a5a2a761ae9c8c6",
    "_internal/licenses/mapbox-earcut/LICENSE.md":
        "48fe37f9d436d604ab4ce8cfc653e2ab8c6d6638f82d4038f0f2ab8d9a76784d",
    "_internal/licenses/moderngl/LICENSE":
        "8606170445f8a941c0517c8e57da97f6a0d0e974d10db901dbbc3b7bd650ec9f",
    "_internal/licenses/msvc-runtime/LICENSE":
        "1df9136ed423271633e0a49436f10672f81d0d98758efdd80463cb312ebb5bc7",
    "_internal/licenses/numpy/LICENSE.txt":
        "a804dff0ead9fadc5293456410bcbfc32bf024be9c4513459663fb7b442d2341",
    "_internal/licenses/pillow/LICENSE":
        "fd31630d7502b4964511c5508dd20ef044ef40935e7b511384f0b400ff7d42d0",
    "_internal/licenses/pyinstaller/COPYING.txt":
        "dcf75fdb959db1e3b41c0f8505069d2ece781b5ec6b3d0a4d30975cfc6580245",
    "_internal/licenses/pymeshlab/LICENSE":
        "230184f60bae2feaf244f10a8bac053c8ff33a183bcc365b4d8b876d2b7f4809",
    "_internal/licenses/pytetwild/LICENSE":
        "9343f5b1b62ea515a5c68112bdb62ad94ce8316e8c5c0f382e5b6a47ee26128e",
    "_internal/licenses/rtree/LICENSE.txt":
        "de223ba53080158085f705e424664e3f79b1418fb347bea76b7d6211c56064de",
    "_internal/licenses/scipy/LICENSE.txt":
        "f0f5c56b298ec9795df1199edc328a987242716d14a1bde6813112e22dc15f99",
    "_internal/licenses/shapely/LICENSE.txt":
        "e8cd7d34604d2758ff589f0f34d6ed79c3f7fb14aaf5e12fb09221421391a3bf",
    "_internal/licenses/shapely/LICENSE_GEOS":
        "91a5bb11df4d44bfddc0c68db43681705326107781599fb6c6ff821042072d64",
    "_internal/licenses/tcl-tk/license.terms":
        "0d1e4405f6273f091732764ed89b57066be63ce64869be6c71ea337dc4f2f9b5",
    "_internal/licenses/tetgen/LICENSE":
        "80de6e0756dad15182df6491c93c8f60e6b52b647c2c577da5f29e20967a6f48",
    "_internal/licenses/tetgen/tetgen-license":
        "bb48fb2a9b22a03d5f1ca6ede21857bcfa8aad28b81dfdd67e32440e23926893",
    "_internal/licenses/trimesh/LICENSE.md":
        "fe27b5ef8710676cc85255da28a32f394e2ef3f4ce47075a1c732a9ea1d7bd03",
}


def _load_qt_static_component_contract() -> tuple[
    dict[str, Component], dict[str, str], list[AuditedNativeIdentity]
]:
    payload = _load_json_object(QT_STATIC_COMPONENTS_PATH, "Qt static-component manifest")
    required_top_level = {
        "schema_version",
        "document_id",
        "scope",
        "generated_from_read_only_audit",
        "qt_runtime_component",
        "binary_provenance",
        "files",
        "static_components",
        "license_assets",
        "implementation_notes",
    }
    _require_exact_keys(payload, required_top_level, "Qt static-component manifest")
    if payload["schema_version"] != 1:
        raise RuntimeError("Qt static-component manifest has an unsupported schema")
    if payload["document_id"] != "chromamatter-qt-static-components-5.15.2-msvc2019-x64":
        raise RuntimeError("Qt static-component manifest has the wrong document ID")

    provenance = payload["binary_provenance"]
    if not isinstance(provenance, dict):
        raise RuntimeError("Qt binary_provenance must be an object")
    _require_exact_keys(
        provenance,
        {
            "package_id",
            "package_version",
            "updates_xml_url",
            "pymeshlab",
            "official_binary_archives",
            "source_archives",
        },
        "Qt binary provenance",
    )
    if (
        provenance["package_id"] != "qt.qt5.5152.win64_msvc2019_64"
        or provenance["package_version"] != "5.15.2-0-202011130602"
        or not isinstance(provenance["updates_xml_url"], str)
        or not provenance["updates_xml_url"].startswith("https://download.qt.io/")
    ):
        raise RuntimeError("Qt binary provenance has the wrong package binding")
    pymeshlab = provenance.get("pymeshlab")
    if not isinstance(pymeshlab, dict):
        raise RuntimeError("Qt binary provenance is missing its PyMeshLab binding")
    _require_exact_keys(
        pymeshlab,
        {
            "version",
            "tag_commit",
            "wheel_sha256",
            "workflow_url",
            "qt_version_declared",
        },
        "Qt PyMeshLab provenance",
    )
    if (
        pymeshlab.get("version") != PINNED_PYMESHLAB_VERSION
        or pymeshlab.get("tag_commit") != PINNED_PYMESHLAB_SOURCE_COMMIT
        or pymeshlab.get("wheel_sha256") != PINNED_PYMESHLAB_WHEEL_SHA256
        or pymeshlab.get("qt_version_declared") != "5.15.2"
    ):
        raise RuntimeError("Qt static-component manifest has the wrong PyMeshLab binding")

    qt_runtime = payload["qt_runtime_component"]
    if not isinstance(qt_runtime, dict):
        raise RuntimeError("Qt runtime binding must be an object")
    _require_exact_keys(
        qt_runtime,
        {"id", "version", "license_expression", "source_url", "note"},
        "Qt runtime binding",
    )
    if (
        qt_runtime.get("id") != "qt"
        or qt_runtime.get("version") != "5.15.2"
        or qt_runtime.get("license_expression") != "LGPL-3.0-only"
        or qt_runtime.get("source_url") != STATIC_COMPONENTS["qt"].source
    ):
        raise RuntimeError("Qt static-component manifest has the wrong Qt runtime binding")

    official_archives = provenance.get("official_binary_archives")
    if not isinstance(official_archives, list) or not official_archives:
        raise RuntimeError("Qt official_binary_archives must be a non-empty array")
    official_archive_ids: set[str] = set()
    for index, archive in enumerate(official_archives):
        if not isinstance(archive, dict):
            raise RuntimeError(f"Qt official binary archive {index} must be an object")
        _require_exact_keys(
            archive,
            {"id", "url", "sha256"},
            f"Qt official binary archive {index}",
        )
        archive_id = archive["id"]
        if (
            not isinstance(archive_id, str)
            or not archive_id
            or archive_id in official_archive_ids
            or not isinstance(archive["url"], str)
            or not archive["url"].startswith("https://download.qt.io/")
        ):
            raise RuntimeError(f"Qt official binary archive {index} is invalid")
        _require_sha256(archive["sha256"], f"Qt official binary archive {archive_id}")
        official_archive_ids.add(archive_id)

    source_archives = provenance.get("source_archives")
    if not isinstance(source_archives, list):
        raise RuntimeError("Qt source_archives must be an array")
    source_urls: dict[str, str] = {}
    for index, source_archive in enumerate(source_archives):
        if not isinstance(source_archive, dict):
            raise RuntimeError(f"Qt source archive {index} must be an object")
        archive_id = source_archive.get("id")
        if archive_id == "qt-5.15.2-corresponding-source":
            expected_source_keys = {
                "id",
                "url",
                "sha256",
                "existing_spec_path",
                "covers_all_qt_components",
                "modules",
            }
        elif archive_id in {
            "qtbase-source-5.15.2",
            "qtimageformats-source-5.15.2",
        }:
            expected_source_keys = {"id", "url", "sha256", "qt_tag", "commit"}
        elif archive_id == "chromium-base-license-28b5":
            expected_source_keys = {"id", "url", "sha256", "commit"}
        else:
            raise RuntimeError(f"Qt source archive {index} has an unknown identity")
        _require_exact_keys(
            source_archive,
            expected_source_keys,
            f"Qt source archive {index}",
        )
        source_url = source_archive.get("url")
        if (
            not isinstance(archive_id, str)
            or not archive_id
            or not isinstance(source_url, str)
            or not source_url.startswith("https://")
            or archive_id in source_urls
        ):
            raise RuntimeError(f"Qt source archive {index} has an invalid identity")
        _require_sha256(source_archive.get("sha256"), f"Qt source archive {archive_id}")
        source_urls[archive_id] = source_url
    if "qt-5.15.2-corresponding-source" not in source_urls:
        raise RuntimeError("Qt corresponding-source archive binding is missing")

    raw_assets = payload["license_assets"]
    if not isinstance(raw_assets, dict) or not raw_assets:
        raise RuntimeError("Qt license_assets must be a non-empty object")
    packaged_assets: dict[str, str] = {}
    source_to_packaged: dict[str, str] = {}
    seen_source_assets: set[str] = set()
    for source_path, record in raw_assets.items():
        source_path = _require_safe_package_path(
            source_path,
            "Qt license asset",
            prefix="source/fixed_app/licenses/qt-5.15.2/",
        )
        if source_path.casefold() in seen_source_assets:
            raise RuntimeError(f"Qt license asset path collides by case: {source_path}")
        seen_source_assets.add(source_path.casefold())
        if not isinstance(record, dict):
            raise RuntimeError(f"Qt license asset record must be an object: {source_path}")
        _require_exact_keys(
            record,
            {"sha256", "size", "byte_preserving", "upstream"},
            f"Qt license asset record {source_path}",
        )
        expected_sha256 = _require_sha256(
            record["sha256"], f"Qt license asset {source_path}"
        )
        if (
            not isinstance(record["size"], int)
            or isinstance(record["size"], bool)
            or record["size"] <= 0
            or record["byte_preserving"] is not True
        ):
            raise RuntimeError(f"Qt license asset has invalid size/byte policy: {source_path}")
        local_asset = REPO_ROOT / Path(*PurePosixPath(source_path).parts)
        if not local_asset.is_file():
            raise RuntimeError(f"Qt license asset is missing: {source_path}")
        if local_asset.stat().st_size != record["size"]:
            raise RuntimeError(f"Qt license asset size does not match: {source_path}")
        if _sha256_file(local_asset) != expected_sha256:
            raise RuntimeError(f"Qt license asset SHA-256 does not match: {source_path}")
        packaged_path = "_internal/" + source_path.removeprefix("source/fixed_app/")
        _require_safe_package_path(
            packaged_path,
            "Packaged Qt license asset",
            prefix="_internal/licenses/qt-5.15.2/",
        )
        if packaged_path in packaged_assets:
            raise RuntimeError(f"Duplicate packaged Qt license asset: {packaged_path}")
        source_to_packaged[source_path] = packaged_path
        packaged_assets[packaged_path] = expected_sha256

    raw_components = payload["static_components"]
    if not isinstance(raw_components, list) or not raw_components:
        raise RuntimeError("Qt static_components must be a non-empty array")
    components: dict[str, Component] = {}
    component_runtime_files: dict[str, set[str]] = {}
    for index, record in enumerate(raw_components):
        if not isinstance(record, dict):
            raise RuntimeError(f"Qt static component {index} must be an object")
        _require_exact_keys(
            record,
            {
                "id",
                "name",
                "version",
                "version_basis",
                "license_expression",
                "license_assets",
                "source",
                "runtime_files",
                "provenance",
            },
            f"Qt static component {index}",
        )
        component_id = record["id"]
        if (
            not isinstance(component_id, str)
            or not re.fullmatch(r"qt-[a-z0-9][a-z0-9-]*", component_id)
            or component_id in components
            or component_id in STATIC_COMPONENTS
        ):
            raise RuntimeError(f"Qt static component has an invalid ID: {component_id!r}")
        name = record["name"]
        version = record["version"]
        license_expression = record["license_expression"]
        if not all(isinstance(value, str) and value for value in (name, version, license_expression)):
            raise RuntimeError(f"Qt static component metadata is incomplete: {component_id}")
        source = record["source"]
        if not isinstance(source, dict):
            raise RuntimeError(f"Qt static component source must be an object: {component_id}")
        expected_source_keys = {
            "archive_id",
            "module",
            "qt_tag",
            "module_commit",
            "corresponding_source_member_root",
        }
        if component_id == "qt-angle-chromium-base":
            expected_source_keys.update(
                {"upstream_repository", "upstream_commit", "upstream_license_url"}
            )
        _require_exact_keys(
            source,
            expected_source_keys,
            f"Qt static component source {component_id}",
        )
        archive_id = source.get("archive_id")
        if archive_id != "qt-5.15.2-corresponding-source":
            raise RuntimeError(f"Qt static component source is not canonical: {component_id}")
        source_url = source_urls[archive_id]

        raw_component_assets = record["license_assets"]
        if not isinstance(raw_component_assets, list) or not raw_component_assets:
            raise RuntimeError(f"Qt static component has no license assets: {component_id}")
        converted_assets: list[str] = []
        for source_asset in raw_component_assets:
            if source_asset not in source_to_packaged:
                raise RuntimeError(
                    f"Qt static component references an unknown license asset: "
                    f"{component_id}: {source_asset!r}"
                )
            converted_assets.append(source_to_packaged[source_asset])
        if len(converted_assets) != len(set(converted_assets)):
            raise RuntimeError(f"Qt static component repeats a license asset: {component_id}")

        raw_runtime_files = record["runtime_files"]
        if not isinstance(raw_runtime_files, list) or not raw_runtime_files:
            raise RuntimeError(f"Qt static component has no runtime files: {component_id}")
        runtime_files: set[str] = set()
        for runtime_path in raw_runtime_files:
            runtime_path = _require_safe_package_path(
                runtime_path,
                f"Qt runtime file for {component_id}",
                prefix="_internal/pymeshlab/",
                suffix=".dll",
            )
            if runtime_path in runtime_files:
                raise RuntimeError(f"Qt static component repeats a runtime file: {component_id}")
            runtime_files.add(runtime_path)
        component_runtime_files[component_id] = runtime_files
        components[component_id] = _component(
            component_id,
            name,
            version,
            license_expression,
            source_url,
            license_assets=tuple(converted_assets),
        )

    raw_files = payload["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise RuntimeError("Qt files must be a non-empty array")
    identities: list[AuditedNativeIdentity] = []
    seen_paths: set[str] = set()
    reverse_runtime_files: dict[str, set[str]] = {
        component_id: set() for component_id in components
    }
    for index, record in enumerate(raw_files):
        if not isinstance(record, dict):
            raise RuntimeError(f"Qt audited file {index} must be an object")
        _require_exact_keys(
            record,
            {
                "path",
                "size",
                "sha256",
                "pe_version",
                "official_archive_id",
                "official_archive_member",
                "runtime_component_ids",
            },
            f"Qt audited file {index}",
        )
        path = _require_safe_package_path(
            record["path"],
            f"Qt audited file {index}",
            prefix="_internal/pymeshlab/",
            suffix=".dll",
        )
        if path.casefold() in seen_paths:
            raise RuntimeError(f"Qt audited file path collides by case: {path}")
        seen_paths.add(path.casefold())
        size = record["size"]
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise RuntimeError(f"Qt audited file has an invalid size: {path}")
        sha256 = _require_sha256(record["sha256"], f"Qt audited file {path}")
        if record["pe_version"] != "5.15.2.0":
            raise RuntimeError(f"Qt audited file has the wrong PE version: {path}")
        if (
            record["official_archive_id"] not in official_archive_ids
            or not isinstance(record["official_archive_member"], str)
            or not record["official_archive_member"]
            or "\\" in record["official_archive_member"]
            or any(
                part in {"", ".", ".."}
                for part in PurePosixPath(record["official_archive_member"]).parts
            )
        ):
            raise RuntimeError(f"Qt audited file has invalid archive provenance: {path}")
        component_ids = record["runtime_component_ids"]
        if (
            not isinstance(component_ids, list)
            or not component_ids
            or component_ids[0] != "qt"
            or len(component_ids) != len(set(component_ids))
        ):
            raise RuntimeError(f"Qt audited file has invalid component IDs: {path}")
        for component_id in component_ids:
            if component_id not in components and component_id != "qt":
                raise RuntimeError(
                    f"Qt audited file references an unknown component: "
                    f"{path}: {component_id}"
                )
            if component_id != "qt":
                reverse_runtime_files[component_id].add(path)
        identities.append(
            AuditedNativeIdentity(
                path=path,
                size=size,
                sha256=sha256,
                component_ids=tuple(component_ids),
                source_manifest="tooling/qt_static_components.json",
            )
        )
    if reverse_runtime_files != component_runtime_files:
        raise RuntimeError("Qt runtime/component mapping is not bidirectional")
    referenced_assets = {
        asset for component in components.values() for asset in component.license_assets
    }
    if referenced_assets != set(packaged_assets):
        raise RuntimeError("Qt license-asset mapping is not closed")
    return components, packaged_assets, identities


def _load_pymeshlab_native_identity_contract() -> list[AuditedNativeIdentity]:
    payload = _load_json_object(
        PYMESHLAB_NATIVE_IDENTITIES_PATH, "PyMeshLab audited-native manifest"
    )
    _require_exact_keys(
        payload,
        {"schema_version", "distribution", "purpose", "identities"},
        "PyMeshLab audited-native manifest",
    )
    if payload["schema_version"] != 1:
        raise RuntimeError("PyMeshLab audited-native manifest has an unsupported schema")
    distribution = payload["distribution"]
    if not isinstance(distribution, dict):
        raise RuntimeError("PyMeshLab distribution binding must be an object")
    _require_exact_keys(
        distribution,
        {"name", "version", "wheel_sha256", "source_commit"},
        "PyMeshLab distribution binding",
    )
    if (
        distribution["name"] != "pymeshlab"
        or distribution["version"] != PINNED_PYMESHLAB_VERSION
        or distribution["wheel_sha256"] != PINNED_PYMESHLAB_WHEEL_SHA256
        or distribution["source_commit"] != PINNED_PYMESHLAB_SOURCE_COMMIT
    ):
        raise RuntimeError("PyMeshLab audited-native manifest has the wrong distribution binding")
    records = payload["identities"]
    if not isinstance(records, list) or not records:
        raise RuntimeError("PyMeshLab audited-native identities must be a non-empty array")
    identities: list[AuditedNativeIdentity] = []
    seen_paths: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise RuntimeError(f"PyMeshLab audited identity {index} must be an object")
        _require_exact_keys(
            record,
            {"path", "size", "sha256", "audited_components"},
            f"PyMeshLab audited identity {index}",
        )
        path = _require_safe_package_path(
            record["path"],
            f"PyMeshLab audited identity {index}",
            prefix="_internal/pymeshlab/",
            suffix=".dll",
        )
        if path.casefold() in seen_paths:
            raise RuntimeError(f"PyMeshLab audited path collides by case: {path}")
        seen_paths.add(path.casefold())
        size = record["size"]
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise RuntimeError(f"PyMeshLab audited identity has an invalid size: {path}")
        sha256 = _require_sha256(record["sha256"], f"PyMeshLab audited identity {path}")
        component_ids = record["audited_components"]
        if (
            not isinstance(component_ids, list)
            or not component_ids
            or component_ids != sorted(set(component_ids))
        ):
            raise RuntimeError(f"PyMeshLab audited identity components are invalid: {path}")
        identities.append(
            AuditedNativeIdentity(
                path=path,
                size=size,
                sha256=sha256,
                component_ids=tuple(component_ids),
                source_manifest="tooling/pymeshlab_audited_native_identities.json",
            )
        )
    expected_order = sorted(
        (identity.path for identity in identities), key=lambda value: (value.casefold(), value)
    )
    if [identity.path for identity in identities] != expected_order:
        raise RuntimeError("PyMeshLab audited-native identities are not canonically sorted")
    return identities


QT_STATIC_COMPONENTS, QT_LICENSE_ASSET_SHA256, QT_AUDITED_NATIVE_IDENTITIES = (
    _load_qt_static_component_contract()
)
STATIC_COMPONENTS.update(QT_STATIC_COMPONENTS)
for _license_asset, _license_sha256 in QT_LICENSE_ASSET_SHA256.items():
    if (
        _license_asset in LICENSE_ASSET_SHA256
        and LICENSE_ASSET_SHA256[_license_asset] != _license_sha256
    ):
        raise RuntimeError(f"Conflicting Qt license asset SHA-256: {_license_asset}")
    LICENSE_ASSET_SHA256[_license_asset] = _license_sha256

PYTETWILD_STATIC_CLOSURE_CONTRACT = load_pytetwild_static_closure_contract()
for _asset in PYTETWILD_STATIC_CLOSURE_CONTRACT.license_assets.values():
    if (
        _asset.packaged_path in LICENSE_ASSET_SHA256
        and LICENSE_ASSET_SHA256[_asset.packaged_path] != _asset.sha256
    ):
        raise RuntimeError(
            "Conflicting PyTetWild static-closure license asset SHA-256: "
            f"{_asset.packaged_path}"
        )
    LICENSE_ASSET_SHA256[_asset.packaged_path] = _asset.sha256

_pytetwild_component_collisions = (
    set(PYTETWILD_STATIC_CLOSURE_CONTRACT.components) & set(STATIC_COMPONENTS)
)
if _pytetwild_component_collisions != {"pytetwild"}:
    raise RuntimeError(
        "Unexpected PyTetWild static-closure component collision: "
        f"{sorted(_pytetwild_component_collisions)!r}"
    )
for _component_id in PYTETWILD_STATIC_CLOSURE_CONTRACT.static_component_ids:
    _record = PYTETWILD_STATIC_CLOSURE_CONTRACT.components[_component_id]
    _source = PYTETWILD_STATIC_CLOSURE_CONTRACT.source_archives[
        _record.source_archive_ids[0]
    ].source_url
    _purl = ""
    _license_assets = tuple(
        PYTETWILD_STATIC_CLOSURE_CONTRACT.packaged_license_paths[_asset_id]
        for _asset_id in _record.license_asset_ids
    )
    if _component_id == "pytetwild":
        _existing = STATIC_COMPONENTS[_component_id]
        _purl = _existing.purl
        _license_assets = tuple(
            dict.fromkeys(_existing.license_assets + _license_assets)
        )
    STATIC_COMPONENTS[_component_id] = _component(
        _component_id,
        _record.name,
        _record.version,
        _record.license_expression,
        _source,
        _purl,
        _license_assets,
    )

_PYMESHLAB_AUDITED_NATIVE_IDENTITIES = _load_pymeshlab_native_identity_contract()
for _identity in _PYMESHLAB_AUDITED_NATIVE_IDENTITIES:
    for _component_id in _identity.component_ids:
        if _component_id not in STATIC_COMPONENTS:
            raise RuntimeError(
                f"PyMeshLab audited identity references unknown component: "
                f"{_identity.path}: {_component_id}"
            )

AUDITED_NATIVE_IDENTITIES: dict[str, AuditedNativeIdentity] = {}
for _identity in _PYMESHLAB_AUDITED_NATIVE_IDENTITIES + QT_AUDITED_NATIVE_IDENTITIES:
    if _identity.path.casefold() in AUDITED_NATIVE_IDENTITIES:
        raise RuntimeError(f"Audited native identity path collides: {_identity.path}")
    AUDITED_NATIVE_IDENTITIES[_identity.path.casefold()] = _identity


STATIC_PACKAGE_KEYS = {
    "glcontext": "glcontext",
    "manifold3d": "manifold3d",
    "mapbox-earcut": "mapbox-earcut",
    "moderngl": "moderngl",
    "numpy": "numpy",
    "pillow": "pillow",
    "pymeshlab": "pymeshlab",
    "pytetwild": "pytetwild",
    "rtree": "rtree",
    "scipy": "scipy",
    "shapely": "shapely",
    "tetgen": "tetgen",
    "trimesh": "trimesh",
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


def _metadata_license(message) -> tuple[str, bool]:
    expression = _metadata_value(message, "License-Expression")
    if expression:
        return expression, True
    classifiers = [
        item.removeprefix("License ::").strip()
        for item in message.get_all("Classifier", [])
        if item.startswith("License ::")
    ]
    if classifiers:
        return " | ".join(sorted(classifiers)), False
    value = _metadata_value(message, "License")
    if value and value.casefold() != "unknown":
        return value, False
    return "NOASSERTION", False


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
            license_value, license_is_spdx = _metadata_license(message)
            components[component_id] = Component(
                component_id=component_id,
                name=name,
                version=version,
                license=license_value,
                source=_metadata_source(message),
                purl=f"pkg:pypi/{normalized_name}@{version}",
                license_is_spdx=license_is_spdx,
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


def _pytetwild_runtime_present(files: Iterable[ScannedFile]) -> bool:
    for item in files:
        lower = item.path.casefold()
        if (
            lower.startswith("_internal/pytetwild/")
            or lower.startswith("_internal/pytetwild.libs/")
            or (
                lower.startswith("_internal/pytetwild-")
                and ".dist-info/" in lower
            )
        ):
            return True
    return False


def _pytetwild_static_closure_violations(
    files: Iterable[ScannedFile],
) -> list[str]:
    items = list(files)
    if not _pytetwild_runtime_present(items):
        return []

    contract = PYTETWILD_STATIC_CLOSURE_CONTRACT
    violations: set[str] = set()
    if not contract.manifest_claims_release_eligible:
        violations.add("manifest-release-blocked")
    if contract.application_wheel_sha256 == contract.historical_wheel_sha256:
        violations.add("application-lock-historical-wheel-forbidden")
    if (
        contract.controlled_wheel_sha256 is None
        or contract.application_wheel_sha256 != contract.controlled_wheel_sha256
    ):
        violations.add("application-lock-wheel-identity-mismatch")

    expected_path = contract.packaged_pyd_path
    by_casefold = {item.path.casefold(): item for item in items}
    wrapper = by_casefold.get(expected_path.casefold())
    if wrapper is None:
        violations.add("wrapper-missing")
    else:
        if wrapper.path != expected_path:
            violations.add("wrapper-path-case-mismatch")
        if wrapper.sha256 == HISTORICAL_PYTETWILD_PYD_SHA256:
            violations.add("historical-wrapper-forbidden")
        if (
            contract.controlled_pyd_sha256 is not None
            and wrapper.sha256 != contract.controlled_pyd_sha256
        ):
            violations.add("wrapper-sha256-mismatch")

    unexpected_codes = violations - PYTETWILD_STATIC_CLOSURE_VIOLATION_CODES
    if unexpected_codes:
        raise RuntimeError(
            "Internal PyTetWild static-closure validation emitted unknown codes: "
            f"{sorted(unexpected_codes)!r}"
        )
    return sorted(violations)


def explicit_native_mapping(item: ScannedFile) -> tuple[list[str], str, str]:
    """Return component ids, rule name, and system-runtime provenance."""

    path = item.path
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
    if lower.startswith("_internal/pytetwild.libs/") and (
        base.startswith("msvcp140-") or base.startswith("concrt140-")
    ):
        return ["pytetwild", "msvc-14.44.35211"], "wheel-repair-runtime", ""
    if "msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll" in lower:
        return ["msvc-14.40.33810"], "msvc-file-version", ""
    if lower.startswith("_internal/shapely.libs/") and base.startswith("msvcp140-"):
        return ["shapely", "msvc-14.44.35215"], "wheel-repair-runtime", ""

    if lower in {"_internal/python3.dll", "_internal/python313.dll"}:
        return ["cpython"], "cpython-runtime", ""
    if lower.startswith("_internal/") and "/" not in lower.removeprefix("_internal/"):
        if base in PYTHON_STDLIB_NATIVE:
            _add(components, "cpython")
            if base == "_bz2.pyd":
                _add(components, "cpython-bzip2")
            if base == "_lzma.pyd":
                _add(components, "cpython-liblzma")
            if base in {"_elementtree.pyd", "pyexpat.pyd"}:
                _add(components, "cpython-expat")
            if base == "_decimal.pyd":
                _add(components, "cpython-libmpdec")
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
        ("_internal/rtree/", "rtree"),
    )
    for prefix, component_id in prefix_rules:
        if lower.startswith(prefix):
            component_ids = [component_id]
            if prefix == "_internal/rtree/" and lower.startswith(
                "_internal/rtree/lib/"
            ):
                _add(component_ids, "libspatialindex")
            return component_ids, "pinned-wheel-path", ""
    if lower == "_internal/manifold3d.cp313-win_amd64.pyd":
        return ["manifold3d"], "pinned-wheel-path", ""
    if lower == "_internal/tetgen/_tetgen.pyd":
        return ["tetgen"], "tetgen-wrapper-with-static-core", ""
    if lower == PYTETWILD_STATIC_CLOSURE_CONTRACT.packaged_pyd_path.casefold():
        contract = PYTETWILD_STATIC_CLOSURE_CONTRACT
        if (
            contract.release_eligible
            and contract.controlled_pyd_sha256 is not None
            and item.path == contract.packaged_pyd_path
            and item.sha256 == contract.controlled_pyd_sha256
            and item.sha256 != HISTORICAL_PYTETWILD_PYD_SHA256
        ):
            return (
                list(contract.static_component_ids),
                PYTETWILD_STATIC_CLOSURE_MAPPING_BASIS,
                "",
            )
        return ["pytetwild"], "unapproved-pytetwild-static-closure", ""
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
        audited_identity = AUDITED_NATIVE_IDENTITIES.get(lower)
        if (
            audited_identity is not None
            and item.path == audited_identity.path
            and item.size == audited_identity.size
            and item.sha256 == audited_identity.sha256
        ):
            _add(components, *audited_identity.component_ids)
            reason += "+audited-native-identity"
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
    # These fields are mandatory for every component that reaches the output.
    # Empty/missing declarations remain visible in a failed report instead of
    # being silently omitted and mistaken for a complete inventory.
    payload["license_assets"] = list(component.license_assets)
    payload["license_asset_sha256"] = {
        path: LICENSE_ASSET_SHA256[path]
        for path in component.license_assets
        if path in LICENSE_ASSET_SHA256
    }
    return payload


def _cyclonedx_licenses(value: str, *, is_spdx_expression: bool) -> list[dict]:
    if is_spdx_expression:
        return [{"expression": value}]
    # Package metadata sometimes contains a human-readable classifier or
    # NOASSERTION rather than a valid SPDX expression.  CycloneDX's named form
    # preserves that value without pretending it was legally normalized.
    return [{"license": {"name": value}}]


def _cyclonedx_component_properties(component: Component) -> list[dict]:
    asset_hashes = {
        path: LICENSE_ASSET_SHA256[path]
        for path in component.license_assets
        if path in LICENSE_ASSET_SHA256
    }
    return [
        {
            "name": "chromamatter:component:license-assets",
            "value": json.dumps(
                asset_hashes,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    ]


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
        application.license_assets,
        application.license_is_spdx,
    )

    mapped_files: list[dict] = []
    used_components: set[str] = set()
    unmapped_native: list[str] = []
    native_count = 0
    for item in files:
        native = PurePosixPath(item.path).suffix.lower() in NATIVE_SUFFIXES
        explicit, rule, system_provenance = explicit_native_mapping(item)
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
    scanned_by_path = {item.path.casefold(): item for item in files}
    pymeshlab_runtime_present = any(
        item.path.casefold().startswith("_internal/pymeshlab/") for item in files
    )
    missing_audited_native_identities: list[dict] = []
    mismatched_audited_native_identities: list[dict] = []
    if pymeshlab_runtime_present:
        for identity in sorted(
            AUDITED_NATIVE_IDENTITIES.values(), key=lambda value: _sort_key(value.path)
        ):
            actual = scanned_by_path.get(identity.path.casefold())
            if actual is None:
                missing_audited_native_identities.append(
                    {
                        "path": identity.path,
                        "expected_size": identity.size,
                        "expected_sha256": identity.sha256,
                        "source_manifest": identity.source_manifest,
                    }
                )
                continue
            mismatch_reasons: list[str] = []
            if actual.path != identity.path:
                mismatch_reasons.append("path-case-mismatch")
            if actual.size != identity.size:
                mismatch_reasons.append("size-mismatch")
            if actual.sha256 != identity.sha256:
                mismatch_reasons.append("sha256-mismatch")
            if mismatch_reasons:
                mismatched_audited_native_identities.append(
                    {
                        "path": actual.path,
                        "expected_path": identity.path,
                        "expected_size": identity.size,
                        "actual_size": actual.size,
                        "expected_sha256": identity.sha256,
                        "actual_sha256": actual.sha256,
                        "reasons": mismatch_reasons,
                        "source_manifest": identity.source_manifest,
                    }
                )
    pytetwild_static_closure_violations = (
        _pytetwild_static_closure_violations(files)
    )
    missing_license_assets = []
    invalid_license_assets = []
    for component_id in sorted(used_components):
        component = components.get(component_id)
        if component is None:
            invalid_license_assets.append(
                {
                    "component": component_id,
                    "path": "",
                    "reason": "unknown-component",
                    "expected_sha256": "",
                    "actual_sha256": "",
                }
            )
            continue
        if not component.license_assets:
            invalid_license_assets.append(
                {
                    "component": component_id,
                    "path": "",
                    "reason": "no-license-assets-declared",
                    "expected_sha256": "",
                    "actual_sha256": "",
                }
            )
            continue
        for asset in component.license_assets:
            expected_sha256 = LICENSE_ASSET_SHA256.get(asset, "")
            if not expected_sha256:
                invalid_license_assets.append(
                    {
                        "component": component_id,
                        "path": asset,
                        "reason": "missing-expected-sha256",
                        "expected_sha256": "",
                        "actual_sha256": "",
                    }
                )
            packaged = scanned_by_path.get(asset.casefold())
            if packaged is None:
                missing_license_assets.append(
                    {"component": component_id, "path": asset}
                )
                continue
            if not expected_sha256:
                # The missing hardcoded digest was already recorded above.
                invalid_license_assets[-1]["actual_sha256"] = packaged.sha256
            elif packaged.sha256 != expected_sha256:
                invalid_license_assets.append(
                    {
                        "component": component_id,
                        "path": asset,
                        "reason": "sha256-mismatch",
                        "expected_sha256": expected_sha256,
                        "actual_sha256": packaged.sha256,
                    }
                )
    validation = {
        "passed": (
            not unmapped_native
            and not reparse_points
            and not missing_audited_native_identities
            and not mismatched_audited_native_identities
            and not pytetwild_static_closure_violations
            and not missing_license_assets
            and not invalid_license_assets
        ),
        "file_count": len(files),
        "native_file_count": native_count,
        "mapped_native_file_count": native_count - len(unmapped_native),
        "unmapped_native_files": unmapped_native,
        "reparse_points_not_traversed": reparse_points,
        "missing_audited_native_identities": missing_audited_native_identities,
        "mismatched_audited_native_identities": mismatched_audited_native_identities,
        "pytetwild_static_closure_violations": (
            pytetwild_static_closure_violations
        ),
        "missing_component_license_assets": missing_license_assets,
        "invalid_component_license_assets": invalid_license_assets,
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
            "licenses": _cyclonedx_licenses(
                component.license,
                is_spdx_expression=component.license_is_spdx,
            ),
            "externalReferences": [
                {"type": "website", "url": component.source}
            ],
            "properties": _cyclonedx_component_properties(component),
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
                "licenses": _cyclonedx_licenses(
                    app_component.license,
                    is_spdx_expression=app_component.license_is_spdx,
                ),
                "externalReferences": [
                    {"type": "website", "url": app_component.source}
                ],
                "hashes": [{"alg": "SHA-256", "content": package_digest}],
                "properties": _cyclonedx_component_properties(app_component),
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
                {
                    "name": "chromamatter:validation:missing-audited-native-count",
                    "value": str(len(missing_audited_native_identities)),
                },
                {
                    "name": "chromamatter:validation:mismatched-audited-native-count",
                    "value": str(len(mismatched_audited_native_identities)),
                },
                {
                    "name": (
                        "chromamatter:validation:"
                        "pytetwild-static-closure-violation-count"
                    ),
                    "value": str(len(pytetwild_static_closure_violations)),
                },
                {
                    "name": "chromamatter:validation:missing-license-asset-count",
                    "value": str(len(missing_license_assets)),
                },
                {
                    "name": "chromamatter:validation:invalid-license-asset-count",
                    "value": str(len(invalid_license_assets)),
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
    if validation["pytetwild_static_closure_violations"]:
        print("PyTetWild static-closure violations:", file=sys.stderr)
        for reason in validation["pytetwild_static_closure_violations"]:
            print(f"  {reason}", file=sys.stderr)
    if validation["missing_component_license_assets"]:
        print("Missing component license assets:", file=sys.stderr)
        for item in validation["missing_component_license_assets"]:
            print(
                f"  {item['component']}: {item['path']}",
                file=sys.stderr,
            )
    if validation["invalid_component_license_assets"]:
        print("Invalid component license assets:", file=sys.stderr)
        for item in validation["invalid_component_license_assets"]:
            print(
                f"  {item['component']}: {item['path']} "
                f"({item['reason']}; expected={item['expected_sha256']}; "
                f"actual={item['actual_sha256']})",
                file=sys.stderr,
            )
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
