# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import importlib.metadata
import importlib.util
import sys

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


# PyInstaller supplies SPECPATH as the directory containing this spec.  Every
# application input is kept in the readable source tree so a clean checkout can
# be built without an older executable or recovered bytecode.
APP = Path(SPECPATH).resolve()
PROJECT = APP.parents[1]

# Bundle the complete license shipped with the exact CPython runtime used to
# freeze the application.  BUILD_AND_TEST.ps1 already rejects any interpreter
# other than 3.13.14, so this remains bound to the packaged python313.dll.
CPYTHON_LICENSE = (Path(sys.base_prefix) / "LICENSE.txt").resolve()
if not CPYTHON_LICENSE.is_file():
    raise RuntimeError(
        f"Required CPython runtime license is missing: {CPYTHON_LICENSE}"
    )
CPYTHON_LICENSE_DATAS = [(str(CPYTHON_LICENSE), "licenses/cpython")]


def package_directory(package_name):
    """Resolve an installed package without importing its ``__init__``."""

    package_spec = importlib.util.find_spec(package_name)
    if package_spec is None or not package_spec.submodule_search_locations:
        raise RuntimeError(f"Required build package is missing: {package_name}")
    return Path(next(iter(package_spec.submodule_search_locations))).resolve()


def distribution_file(distribution_name, relative_path):
    """Return a file shipped in an installed wheel/distribution."""

    path = Path(
        importlib.metadata.distribution(distribution_name).locate_file(relative_path)
    ).resolve()
    if not path.is_file():
        raise RuntimeError(
            f"Required distribution file is missing: {distribution_name}/{relative_path}"
        )
    return path


# PyTetWild's public package imports optional PyVista.  The application instead
# loads its compiled raw-array wrapper directly, so preserve the wheel layout
# expected by spectrum_mapper.volume_partition._load_tetwild_wrapper().
PYTETWILD_PACKAGE = package_directory("pytetwild")
PYTETWILD_LIBS = PYTETWILD_PACKAGE.parent / "pytetwild.libs"
PYTETWILD_WRAPPERS = sorted(PYTETWILD_PACKAGE.glob("PyfTetWildWrapper*.pyd"))
PYTETWILD_DLLS = sorted(PYTETWILD_LIBS.glob("*.dll"))
if not PYTETWILD_WRAPPERS or not PYTETWILD_DLLS:
    raise RuntimeError("The installed pytetwild wheel has an unexpected layout")

VOLUME_BINARIES = [
    *((str(path), "pytetwild") for path in PYTETWILD_WRAPPERS),
    *((str(path), "pytetwild.libs") for path in PYTETWILD_DLLS),
]

# copy_metadata keeps importlib.metadata.version() working in the frozen app.
# Explicit copies under licenses/ make all governing license texts visible to
# end users without having to inspect the bundled dist-info directories.
VOLUME_DATAS = (
    copy_metadata("pytetwild")
    + copy_metadata("tetgen")
    + [
        (
            str(
                distribution_file(
                    "pytetwild", "pytetwild-0.3.0.dist-info/licenses/LICENSE"
                )
            ),
            "licenses/pytetwild",
        ),
        (
            str(
                distribution_file(
                    "tetgen", "tetgen-0.8.3.dist-info/licenses/LICENSE"
                )
            ),
            "licenses/tetgen",
        ),
        (
            str(
                distribution_file(
                    "tetgen",
                    "tetgen-0.8.3.dist-info/licenses/src/tetgen-license",
                )
            ),
            "licenses/tetgen",
        ),
        (str(APP / "THIRD_PARTY_VOLUME_LICENSES_JA.md"), "."),
    ]
)

# Preserve exact notice files shipped by the pinned wheels.  PyInstaller hooks
# do not consistently retain dist-info metadata, especially for PyMeshLab and
# Shapely, so release builds copy these files to a stable visible location.
WHEEL_LICENSE_FILES = (
    (
        "pymeshlab",
        "pymeshlab-2025.7.post1.dist-info/licenses/LICENSE",
        "licenses/pymeshlab",
    ),
    (
        "shapely",
        "shapely-2.1.2.dist-info/licenses/LICENSE.txt",
        "licenses/shapely",
    ),
    (
        "shapely",
        "shapely-2.1.2.dist-info/licenses/LICENSE_GEOS",
        "licenses/shapely",
    ),
    (
        "shapely",
        "shapely-2.1.2.dist-info/licenses/LICENSE_win32",
        "licenses/shapely",
    ),
    (
        "msvc-runtime",
        "msvc_runtime-14.44.35112.dist-info/licenses/LICENSE",
        "licenses/msvc-runtime",
    ),
    ("scipy", "scipy-1.18.0.dist-info/LICENSE.txt", "licenses/scipy"),
    (
        "pillow",
        "pillow-11.2.1.dist-info/licenses/LICENSE",
        "licenses/pillow",
    ),
    (
        "pyinstaller",
        "pyinstaller-6.20.0.dist-info/licenses/COPYING.txt",
        "licenses/pyinstaller",
    ),
    (
        "manifold3d",
        "manifold3d-3.5.2.dist-info/licenses/LICENSE",
        "licenses/manifold3d",
    ),
    (
        "mapbox-earcut",
        "mapbox_earcut-2.0.0.dist-info/licenses/LICENSE.md",
        "licenses/mapbox-earcut",
    ),
    (
        "networkx",
        "networkx-3.5.dist-info/licenses/LICENSE.txt",
        "licenses/networkx",
    ),
    (
        "rtree",
        "rtree-1.4.1.dist-info/licenses/LICENSE.txt",
        "licenses/rtree",
    ),
    ("moderngl", "moderngl-5.12.0.dist-info/LICENSE", "licenses/moderngl"),
    ("glcontext", "glcontext-3.0.0.dist-info/LICENSE", "licenses/glcontext"),
    (
        "trimesh",
        "trimesh-5.0.0.dist-info/licenses/LICENSE.md",
        "licenses/trimesh",
    ),
)
WHEEL_LICENSE_DATAS = [
    (str(distribution_file(distribution, relative)), destination)
    for distribution, relative, destination in WHEEL_LICENSE_FILES
]

# The decal SVG loader uses the pinned resvg-py Windows wheel.  The extension
# module itself is collected through the explicit hidden import below.  Keep
# importlib.metadata.version("resvg") functional and expose the wheel's MIT
# text plus its CycloneDX list of compiled Rust crates to end users.  Do not
# use a whole-distribution metadata copy here: a wheel installed from a local
# probe path can carry direct_url.json containing that workstation's absolute
# path.
# Instead copy the privacy-safe metadata subset required at runtime.
RESVG_DIST_INFO = "resvg-0.2.0.dist-info"
RESVG_DATAS = [
    (
        str(distribution_file("resvg", f"{RESVG_DIST_INFO}/METADATA")),
        RESVG_DIST_INFO,
    ),
    (
        str(distribution_file("resvg", f"{RESVG_DIST_INFO}/WHEEL")),
        RESVG_DIST_INFO,
    ),
    (
        str(
            distribution_file(
                "resvg", f"{RESVG_DIST_INFO}/licenses/LICENSE.txt"
            )
        ),
        f"{RESVG_DIST_INFO}/licenses",
    ),
    (
        str(
            distribution_file(
                "resvg", f"{RESVG_DIST_INFO}/sboms/resvg.cyclonedx.json"
            )
        ),
        f"{RESVG_DIST_INFO}/sboms",
    ),
    (
        str(
            distribution_file(
                "resvg", f"{RESVG_DIST_INFO}/licenses/LICENSE.txt"
            )
        ),
        "licenses/resvg-py",
    ),
    (
        str(
            distribution_file(
                "resvg", f"{RESVG_DIST_INFO}/sboms/resvg.cyclonedx.json"
            )
        ),
        "licenses/resvg-py",
    ),
]

APP_LICENSE_DATAS = [
    (str(PROJECT / "licenses" / filename), "licenses")
    for filename in (
        "AGPL-3.0.txt",
        "BINARY_COMPONENT_MAP.schema.json",
        "BUILD_ENVIRONMENT_EN.md",
        "BUILD_ENVIRONMENT_JA.md",
        "LICENSE_APP.txt",
        "GPL-3.0.txt",
        "LGPL-2.1.txt",
        "LGPL-3.0.txt",
        "MPL-2.0.txt",
        "RELINKING_EN.md",
        "RELINKING_JA.md",
        "THIRD_PARTY_NOTICES_EN.txt",
        "THIRD_PARTY_NOTICES_JA.txt",
        "THIRD_PARTY_LICENSES.txt",
        "LICENSE_RESVG_PY.txt",
        "LICENSE_RESVG_MIT.txt",
        "LICENSE_RESVG_APACHE_2.0.txt",
    )
]

# Keep the offline candidate database and all governing attribution/license
# documents together under the same runtime-relative path.  In a PyInstaller 6
# one-folder build this destination is available as
# ``sys._MEIPASS/resources/filament_db``.  The application resolver also checks
# ``resources/filament_db`` beside ChromaMatter.exe for an unpacked external
# fallback, and the source-tree location during development.
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
    ]
    + FILAMENT_DATABASE_DATAS
    + VOLUME_DATAS
    + WHEEL_LICENSE_DATAS
    + RESVG_DATAS
    + APP_LICENSE_DATAS
    + CPYTHON_LICENSE_DATAS,
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
        # Trimesh discovers these optional geometry backends at runtime.
        # Keeping them explicit ensures their compiled extension modules (and
        # Rtree's spatialindex DLLs via its standard PyInstaller hook) survive
        # the frozen build.
        "trimesh",
        "manifold3d",
        "shapely",
        "mapbox_earcut",
        "networkx",
        "rtree",
        "moderngl",
        "glcontext",
        "resvg",
        "resvg._resvg",
        "PIL.ImageTk",
    ]
    + collect_submodules("scipy._external.array_api_compat.common")
    + collect_submodules("scipy._external.array_api_compat.numpy"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(APP / "pymeshlab_runtime_hook.py")],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# PyInstaller's upstream pymeshlab hook collects the wheel's test meshes as
# data.  They are not runtime dependencies and must not enter a release
# package, whose staging audit intentionally rejects embedded model files.
def is_windows_import_library(entry):
    """True for link-time .lib archives, which are never runtime payloads."""

    return any(
        str(value).replace("\\", "/").casefold().endswith(".lib")
        for value in entry[:2]
    )


def is_private_install_origin_metadata(entry):
    """True for pip direct-URL metadata that can contain a local absolute path."""

    destination = str(entry[0]).replace("\\", "/").casefold()
    return ".dist-info/" in destination and destination.endswith("/direct_url.json")


a.datas = [
    entry
    for entry in a.datas
    if (
        not entry[0]
        .replace("\\", "/")
        .casefold()
        .startswith("pymeshlab/tests/")
        and not is_private_install_origin_metadata(entry)
        and not is_windows_import_library(entry)
    )
]
# Qt and other wheel hooks can classify import/development archives as either
# data or binaries.  Windows loads DLLs at runtime; .lib files are link-time
# inputs and are excluded from both collections without removing plugin DLLs.
a.binaries = [
    entry for entry in a.binaries if not is_windows_import_library(entry)
]
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
    # Radial Lab depends on several native geometry extensions. Keep the
    # frozen runtime deterministic and avoid optional UPX rewriting of them.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP / "assets" / "obj_adjuster_icon.ico"),
    version=str(APP / "version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ChromaMatter",
)
