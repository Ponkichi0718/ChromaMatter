# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller definition for the Linux x86_64 technical alpha.

This deliberately remains separate from the proven Windows release spec and
the Apple Silicon alpha spec.  It creates an Ubuntu-22.04-compatible one-folder
technical build only; it does not create or approve a redistribution archive.
"""

from pathlib import Path
from pathlib import PurePosixPath
import importlib.metadata
import importlib.util
import platform
import sys
import tkinter

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


APP = Path(SPECPATH).resolve()
PROJECT = APP.parents[1]
LINUX_APP_NAME = "ChromaMatter-Linux-Alpha"

if not sys.platform.startswith("linux") or platform.machine().casefold() != "x86_64":
    raise RuntimeError("The Linux technical-alpha spec requires Linux x86_64")
if sys.version_info[:3] != (3, 13, 14):
    raise RuntimeError(
        "The Linux technical-alpha spec requires exact CPython 3.13.14"
    )


def require_first_file(description, candidates):
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
    roots = [Path(sys.base_prefix), Path(sys.prefix), Path(sys.executable).resolve().parent]
    roots.extend(list(Path(sys.executable).resolve().parents[:5]))
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
            root / "share" / "doc" / f"python{PYTHON_VERSION}" / "copyright",
            root / "lib" / f"python{PYTHON_VERSION}" / "LICENSE.txt",
        )
    )
CPYTHON_LICENSE = require_first_file(
    "CPython runtime license", CPYTHON_LICENSE_CANDIDATES
)

TCL_INTERPRETER = tkinter.Tcl()
TCL_PATCHLEVEL = str(TCL_INTERPRETER.eval("info patchlevel"))
TK_ROOT = tkinter.Tk()
try:
    TK_PATCHLEVEL = str(TK_ROOT.tk.call("info", "patchlevel"))
finally:
    TK_ROOT.destroy()
TCL_TK_LICENSES = {
    ("8.6.18", "8.6.18"): (
        PROJECT / "licenses" / "LICENSE_TCL_8_6_18.txt",
        PROJECT / "licenses" / "LICENSE_TK_8_6_18.txt",
    ),
    ("9.0.4", "9.0.4"): (
        PROJECT / "licenses" / "LICENSE_TCL_9_0_4.txt",
        PROJECT / "licenses" / "LICENSE_TK_9_0_4.txt",
    ),
}
license_pair = TCL_TK_LICENSES.get((TCL_PATCHLEVEL, TK_PATCHLEVEL))
if license_pair is None:
    raise RuntimeError(
        "The Linux technical build has no reviewed Tcl/Tk license pair for "
        f"Tcl {TCL_PATCHLEVEL} / Tk {TK_PATCHLEVEL}"
    )
TCL_LICENSE = require_first_file("reviewed Tcl license text", (license_pair[0],))
TK_LICENSE = require_first_file("reviewed Tk license text", (license_pair[1],))
TCL_TK_RUNTIME_LIBRARY_NAMES = {
    ("8.6.18", "8.6.18"): ("libtcl8.6.so", "libtk8.6.so"),
    ("9.0.4", "9.0.4"): ("libtcl9.0.so", "libtcl9tk9.0.so"),
}
TCL_TK_BINARIES = []
for library_name in TCL_TK_RUNTIME_LIBRARY_NAMES[(TCL_PATCHLEVEL, TK_PATCHLEVEL)]:
    library_candidates = []
    for root in runtime_roots():
        library_candidates.extend((root / "lib" / library_name, root / library_name))
    library_candidates.extend(
        (
            Path("/usr/lib/x86_64-linux-gnu") / library_name,
            Path("/lib/x86_64-linux-gnu") / library_name,
        )
    )
    runtime_library = require_first_file(
        f"Tcl/Tk runtime library {library_name}", library_candidates
    )
    TCL_TK_BINARIES.append((str(runtime_library), "."))


def package_directory(package_name):
    package_spec = importlib.util.find_spec(package_name)
    if package_spec is None or not package_spec.submodule_search_locations:
        raise RuntimeError(f"Required build package is missing: {package_name}")
    return Path(next(iter(package_spec.submodule_search_locations))).resolve()


def tree_datas(source_root, destination_root):
    source_root = Path(source_root).resolve()
    if not source_root.is_dir():
        raise RuntimeError(f"Required data directory is missing: {source_root}")
    datas = []
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative = source.relative_to(source_root)
        destination = (
            PurePosixPath(destination_root)
            / PurePosixPath(relative.parent.as_posix())
        ).as_posix()
        datas.append((str(source), destination))
    if not datas:
        raise RuntimeError(f"Required data directory is empty: {source_root}")
    return datas


def distribution_license_datas(distribution_name):
    distribution = importlib.metadata.distribution(distribution_name)
    datas = []
    for relative in sorted(distribution.files or (), key=lambda value: str(value).casefold()):
        pure = PurePosixPath(str(relative).replace("\\", "/"))
        filename = pure.name.casefold()
        # Some packages expose importable code below a Python namespace named
        # `licenses`.  Collect only document-like filenames, otherwise pyc
        # files can carry local build paths into the application directory.
        if not filename.startswith(("license", "copying", "notice")):
            continue
        source = Path(distribution.locate_file(relative)).resolve()
        if not source.is_file():
            raise RuntimeError(
                f"Wheel-declared license file is missing: {distribution_name}/{pure}"
            )
        destination = (
            PurePosixPath("licenses")
            / "wheels"
            / distribution_name
            / pure.parent
        )
        datas.append((str(source), destination.as_posix()))
    if not datas:
        raise RuntimeError(f"No wheel-supplied license file found for {distribution_name}")
    return datas


PYTETWILD_PACKAGE = package_directory("pytetwild")
PYTETWILD_LIBRARY_ROOT = PYTETWILD_PACKAGE.parent / "pytetwild.libs"
PYTETWILD_WRAPPERS = sorted(PYTETWILD_PACKAGE.glob("PyfTetWildWrapper*.so"))
PYTETWILD_LIBRARIES = sorted(PYTETWILD_LIBRARY_ROOT.glob("*.so*"))
if len(PYTETWILD_WRAPPERS) != 1 or not PYTETWILD_LIBRARIES:
    raise RuntimeError("The installed Linux x86_64 PyTetWild wheel has an unexpected layout")

VOLUME_BINARIES = [
    *((str(path), "pytetwild") for path in PYTETWILD_WRAPPERS),
    *((str(path), "pytetwild.libs") for path in PYTETWILD_LIBRARIES),
]

METADATA_DISTRIBUTIONS = (
    "altgraph",
    "glcontext",
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
MACOS_RELEASE_ONLY_DOCUMENTS = {
    "MACOS_ALPHA_COMPLIANCE_NOTICE_EN.txt",
    "MACOS_ALPHA_COMPLIANCE_NOTICE_JA.txt",
}
APP_LICENSE_DATAS = []
for entry in tree_datas(PROJECT / "licenses", "licenses"):
    source = Path(entry[0])
    relative = source.relative_to(PROJECT / "licenses")
    if source.name in WINDOWS_RELEASE_ONLY_DOCUMENTS | MACOS_RELEASE_ONLY_DOCUMENTS:
        continue
    if relative.parts[0].casefold() in {"macos", "native-closure"}:
        continue
    APP_LICENSE_DATAS.append(entry)

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
    binaries=VOLUME_BINARIES + TCL_TK_BINARIES,
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
        "PIL._imagingtk",
        "PIL._tkinter_finder",
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


def normalized_destination(entry):
    return str(entry[0]).replace("\\", "/").casefold()


def is_private_install_origin_metadata(entry):
    destination = normalized_destination(entry)
    return ".dist-info/" in destination and destination.endswith("/direct_url.json")


def is_source_only_resvg_metadata(entry):
    destination = normalized_destination(entry)
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
        not normalized_destination(entry).startswith("pymeshlab/tests/")
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
    icon=str(APP / "assets" / "obj_adjuster_icon.png"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=LINUX_APP_NAME,
)
