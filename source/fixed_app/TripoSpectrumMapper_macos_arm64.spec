# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller definition for the separate Apple Silicon macOS alpha.

This spec deliberately does not import or modify the proven Windows release
spec.  It builds an arm64-only ``.app`` with a distinct bundle identifier and
an unmistakable alpha name.  Developer ID signing, notarization, and the
platform-specific third-party binary audit are separate publication gates.
"""

from pathlib import Path
from pathlib import PurePosixPath
import importlib.metadata
import importlib.util
import sys
import tkinter

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


APP = Path(SPECPATH).resolve()
PROJECT = APP.parents[1]
MACOS_APP_NAME = "ChromaMatter-macOS-Alpha"


def require_first_file(description, candidates):
    """Return the first existing file from a small deterministic candidate set."""

    checked = []
    for candidate in candidates:
        path = Path(candidate).expanduser().resolve()
        if path in checked:
            continue
        checked.append(path)
        if path.is_file():
            return path
    raise RuntimeError(
        f"Required {description} is missing. Checked: "
        + ", ".join(str(path) for path in checked)
    )


def runtime_roots():
    """Return bounded Python installation roots used only for license lookup."""

    roots = [Path(sys.base_prefix), Path(sys.prefix), Path(sys.executable).resolve().parent]
    executable = Path(sys.executable).resolve()
    roots.extend(list(executable.parents[:5]))
    unique = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"
CPYTHON_LICENSE_CANDIDATES = []
for root in runtime_roots():
    CPYTHON_LICENSE_CANDIDATES.extend(
        (
            root / "LICENSE.txt",
            root / "LICENSE",
            root / "lib" / f"python{PYTHON_VERSION}" / "LICENSE.txt",
            root
            / "Resources"
            / "English.lproj"
            / "Documentation"
            / "LICENSE.txt",
            root
            / "Resources"
            / "Python.app"
            / "Contents"
            / "Resources"
            / "English.lproj"
            / "Documentation"
            / "LICENSE.txt",
            root
            / "Python.framework"
            / "Versions"
            / PYTHON_VERSION
            / "Resources"
            / "English.lproj"
            / "Documentation"
            / "LICENSE.txt",
        )
    )
CPYTHON_LICENSE = require_first_file(
    "CPython runtime license", CPYTHON_LICENSE_CANDIDATES
)

TCL_INTERPRETER = tkinter.Tcl()
TCL_LIBRARY = Path(TCL_INTERPRETER.eval("info library")).resolve()
TCL_PATCHLEVEL = str(TCL_INTERPRETER.eval("info patchlevel"))
if TCL_PATCHLEVEL != "8.6.18":
    raise RuntimeError(
        "The pinned CPython 3.13.14 macOS build must carry Tcl/Tk 8.6.18; "
        f"found Tcl {TCL_PATCHLEVEL}"
    )
TCL_LICENSE = require_first_file(
    "reviewed Tcl 8.6.18 license",
    (PROJECT / "licenses" / "LICENSE_TCL_8_6_18.txt",),
)
TK_LICENSE = require_first_file(
    "reviewed Tk 8.6.18 license",
    (PROJECT / "licenses" / "LICENSE_TK_8_6_18.txt",),
)


def package_directory(package_name):
    """Resolve an installed package without importing its ``__init__``."""

    package_spec = importlib.util.find_spec(package_name)
    if package_spec is None or not package_spec.submodule_search_locations:
        raise RuntimeError(f"Required build package is missing: {package_name}")
    return Path(next(iter(package_spec.submodule_search_locations))).resolve()


def tree_datas(source_root, destination_root):
    """Collect a checked source tree while preserving its relative layout."""

    source_root = Path(source_root).resolve()
    if not source_root.is_dir():
        raise RuntimeError(f"Required data directory is missing: {source_root}")
    datas = []
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative = source.relative_to(source_root)
        destination = (PurePosixPath(destination_root) / PurePosixPath(
            relative.parent.as_posix()
        )).as_posix()
        datas.append((str(source), destination))
    if not datas:
        raise RuntimeError(f"Required data directory is empty: {source_root}")
    return datas


def distribution_license_datas(distribution_name):
    """Copy wheel-supplied license/notice files to a user-visible directory."""

    distribution = importlib.metadata.distribution(distribution_name)
    files = distribution.files or ()
    datas = []
    for relative in sorted(files, key=lambda value: str(value).casefold()):
        pure = PurePosixPath(str(relative).replace("\\", "/"))
        lower_parts = tuple(part.casefold() for part in pure.parts)
        filename = pure.name.casefold()
        is_license_tree = "licenses" in lower_parts
        is_named_notice = filename.startswith(("license", "copying", "notice"))
        if not (is_license_tree or is_named_notice):
            continue
        source = Path(distribution.locate_file(relative)).resolve()
        if not source.is_file():
            raise RuntimeError(
                f"Wheel-declared license file is missing: {distribution_name}/{pure}"
            )
        # Preserve the wheel-relative parent so vendored packages with several
        # identically named LICENSE files cannot overwrite one another.
        destination = (
            PurePosixPath("licenses")
            / "wheels"
            / distribution_name
            / pure.parent
        )
        datas.append((str(source), destination.as_posix()))
    if not datas:
        raise RuntimeError(
            f"No wheel-supplied license file found for {distribution_name}"
        )
    return datas


PYTETWILD_PACKAGE = package_directory("pytetwild")
PYTETWILD_DYLIB_ROOT = PYTETWILD_PACKAGE / ".dylibs"
PYTETWILD_WRAPPERS = sorted(PYTETWILD_PACKAGE.glob("PyfTetWildWrapper*.so"))
PYTETWILD_DYLIBS = sorted(PYTETWILD_DYLIB_ROOT.glob("*.dylib"))
if not PYTETWILD_WRAPPERS or not PYTETWILD_DYLIBS:
    raise RuntimeError(
        "The installed macOS arm64 PyTetWild wheel has an unexpected layout"
    )

VOLUME_BINARIES = [
    *((str(path), "pytetwild") for path in PYTETWILD_WRAPPERS),
    # PyInstaller preserves the wheel input path here, then encodes the
    # leading-dot directory as ``__dot__dylibs`` inside the final .app and
    # rewrites the Mach-O dependency to that packaged location.
    *((str(path), "pytetwild/.dylibs") for path in PYTETWILD_DYLIBS),
]

METADATA_DISTRIBUTIONS = (
    "altgraph",
    "glcontext",
    "macholib",
    "manifold3d",
    "mapbox-earcut",
    "moderngl",
    "networkx",
    "numpy",
    "packaging",
    "pillow",
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "pymeshlab",
    "pytetwild",
    "resvg",
    "rtree",
    "scipy",
    "setuptools",
    "shapely",
    "tetgen",
    "trimesh",
)
METADATA_DATAS = []
WHEEL_LICENSE_DATAS = []
for distribution_name in METADATA_DISTRIBUTIONS:
    METADATA_DATAS.extend(copy_metadata(distribution_name))
    WHEEL_LICENSE_DATAS.extend(distribution_license_datas(distribution_name))

WINDOWS_RELEASE_ONLY_DOCUMENTS = {
    "BUILD_ENVIRONMENT_EN.md",
    "BUILD_ENVIRONMENT_JA.md",
    "RELINKING_EN.md",
    "RELINKING_JA.md",
    "SOURCE_OFFER_TEMPLATE_EN.txt",
    "SOURCE_OFFER_TEMPLATE_JA.txt",
    "THIRD_PARTY_LICENSES.txt",
    "THIRD_PARTY_NOTICES_EN.txt",
    "THIRD_PARTY_NOTICES_JA.txt",
}
APP_LICENSE_DATAS = [
    entry
    for entry in tree_datas(PROJECT / "licenses", "licenses")
    if Path(entry[0]).name not in WINDOWS_RELEASE_ONLY_DOCUMENTS
    # Exact-build distribution evidence is staged beside the app after the
    # observed bundle inventory is generated.  Keeping it outside the signed
    # app avoids a circular inventory -> evidence -> changed-app dependency.
    and Path(entry[0]).relative_to(PROJECT / "licenses").parts[0].casefold()
    != "macos"
]
FILAMENT_DATABASE_DIR = APP / "resources" / "filament_db"
FILAMENT_DATABASE_FILENAMES = (
    "filament_color_database_2026-08.sqlite",
    "filament_color_database_README.md",
    "ATTRIBUTION.md",
    "LICENSE_OPEN_FILAMENT_DATABASE.txt",
    "LICENSE_CC_BY_4.0.txt",
)
FILAMENT_DATABASE_DATAS = []
for filename in FILAMENT_DATABASE_FILENAMES:
    source = FILAMENT_DATABASE_DIR / filename
    if not source.is_file():
        raise RuntimeError(f"Required filament database resource is missing: {source}")
    FILAMENT_DATABASE_DATAS.append((str(source), "resources/filament_db"))


a = Analysis(
    [str(APP / "TripoSpectrumMapper_fixed.py")],
    pathex=[str(APP)],
    binaries=VOLUME_BINARIES,
    datas=[
        (str(APP / "assets" / "mixer_model.npz"), "assets"),
        (str(APP / "assets" / "obj_adjuster_icon.png"), "assets"),
        (str(CPYTHON_LICENSE), "licenses/cpython"),
        (str(TCL_LICENSE), "licenses/tcl-tk"),
        (str(TK_LICENSE), "licenses/tcl-tk"),
        (str(APP / "THIRD_PARTY_VOLUME_LICENSES_JA.md"), "."),
    ]
    + FILAMENT_DATABASE_DATAS
    + METADATA_DATAS
    + WHEEL_LICENSE_DATAS
    + APP_LICENSE_DATAS,
    hiddenimports=[
        "spectrum_mapper",
        "spectrum_mapper.assembly",
        "spectrum_mapper.cli",
        "spectrum_mapper.engine",
        "spectrum_mapper.gltf_import",
        "spectrum_mapper.gui",
        "spectrum_mapper.mixer",
        "spectrum_mapper.models",
        "spectrum_mapper.paint",
        "spectrum_mapper.paint_gui",
        "spectrum_mapper.decal_image",
        "spectrum_mapper.palette_state_count",
        "spectrum_mapper.parts",
        "spectrum_mapper.radial_export",
        "spectrum_mapper.radial_shell",
        "spectrum_mapper.radial_workflow",
        "spectrum_mapper.color_depth",
        "spectrum_mapper.color_depth_recipes",
        "spectrum_mapper.color_depth_workflow",
        "spectrum_mapper.color_depth_3mf_input",
        "spectrum_mapper.color_depth_head_geometry",
        "spectrum_mapper.color_depth_exact_partition",
        "spectrum_mapper.material_manifold",
        "spectrum_mapper.filament_candidate_gui",
        "spectrum_mapper.filament_database",
        "spectrum_mapper.filament_recommender",
        "spectrum_mapper.owned_filaments",
        "spectrum_mapper.calibration_chart",
        "spectrum_mapper.freehand_split",
        "spectrum_mapper.i18n",
        "spectrum_mapper.reference_parts",
        "spectrum_mapper.renderer",
        "spectrum_mapper.generated_surface_color",
        "spectrum_mapper.volume_partition",
        "spectrum_mapper.workflow",
        "surface_resolution_hotfix",
        "final_shading_hotfix",
        "rotation_hotfix",
        "adaptive_gpu_overlay",
        "smooth_paint",
        "smooth_paint_hotfix",
        "auto_shading",
        "slicer_safety",
        "brush_cursor_hotfix",
        "scipy.sparse",
        "scipy.sparse.csgraph",
        "pymeshlab",
        "tetgen",
        "tetgen._tetgen",
        "trimesh",
        "manifold3d",
        "shapely",
        "mapbox_earcut",
        "networkx",
        "rtree",
        "moderngl",
        "glcontext",
        "PIL.ImageTk",
    ]
    + collect_submodules("scipy._external.array_api_compat.common")
    + collect_submodules("scipy._external.array_api_compat.numpy"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(APP / "pymeshlab_runtime_hook.py")],
    excludes=["resvg", "resvg._resvg"],
    noarchive=False,
    optimize=0,
)


def is_private_install_origin_metadata(entry):
    destination = str(entry[0]).replace("\\", "/").casefold()
    return ".dist-info/" in destination and destination.endswith("/direct_url.json")


def is_source_only_resvg_metadata(entry):
    destination = str(entry[0]).replace("\\", "/").casefold()
    return destination == "resvg-0.2.0.dist-info" or destination.startswith(
        "resvg-0.2.0.dist-info/"
    )


def is_link_time_archive(entry):
    return any(
        str(value).replace("\\", "/").casefold().endswith((".a", ".la", ".lib"))
        for value in entry[:2]
    )


a.datas = [
    entry
    for entry in a.datas
    if (
        not entry[0].replace("\\", "/").casefold().startswith("pymeshlab/tests/")
        and not is_private_install_origin_metadata(entry)
        and not is_source_only_resvg_metadata(entry)
        and not is_link_time_archive(entry)
    )
]
a.binaries = [entry for entry in a.binaries if not is_link_time_archive(entry)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChromaMatter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP / "assets" / "obj_adjuster_icon.png"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=MACOS_APP_NAME,
)
app = BUNDLE(
    coll,
    name=f"{MACOS_APP_NAME}.app",
    icon=str(APP / "assets" / "obj_adjuster_icon.png"),
    bundle_identifier="io.github.ponkichi0718.chromamatter.alpha",
    version="0.9.0",
    info_plist={
        "CFBundleDisplayName": "ChromaMatter macOS Alpha",
        "CFBundleName": "ChromaMatter macOS Alpha",
        "CFBundleGetInfoString": "ChromaMatter 0.9 macOS alpha",
        # Apple bundle metadata remains numeric and follows the in-app 0.9
        # product version.
        "CFBundleShortVersionString": "0.9.0",
        "CFBundleVersion": "900",
        "LSMinimumSystemVersion": "15.0",
        "LSArchitecturePriority": ["arm64"],
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Copyright (c) 2026 ChromaMatter contributors",
    },
)
