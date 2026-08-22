# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from pathlib import PurePosixPath
import hashlib
import importlib.metadata
import importlib.util
import json
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

TCL_TK_LICENSE = (
    Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms"
).resolve()
if not TCL_TK_LICENSE.is_file():
    raise RuntimeError(
        f"Required Tcl/Tk runtime license is missing: {TCL_TK_LICENSE}"
    )
TCL_TK_LICENSE_DATAS = [(str(TCL_TK_LICENSE), "licenses/tcl-tk")]


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


def audited_manifest_license_datas(manifest_name, *, path_is_key=False):
    """Collect only byte-verified license assets declared by one manifest."""

    manifest_path = (PROJECT / "tooling" / manifest_name).resolve()
    if not manifest_path.is_file():
        raise RuntimeError(f"Required license manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read license manifest: {manifest_path}") from exc
    if manifest.get("schema_version") != 1:
        raise RuntimeError(f"Unsupported license manifest schema: {manifest_path}")
    records = manifest.get("license_assets")
    if not isinstance(records, dict) or not records:
        raise RuntimeError(f"License manifest has no assets: {manifest_path}")

    source_root = (PROJECT / "source" / "fixed_app" / "licenses").resolve()
    datas = []
    seen = set()
    for record_key, record in sorted(records.items()):
        if not isinstance(record, dict):
            raise RuntimeError(f"Invalid license manifest record: {record_key}")
        source_relative = record_key if path_is_key else record.get("path")
        if not isinstance(source_relative, str):
            raise RuntimeError(f"License manifest path is missing: {record_key}")
        pure = PurePosixPath(source_relative)
        if (
            not source_relative.startswith("source/fixed_app/licenses/")
            or "\\" in source_relative
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
            or source_relative in seen
        ):
            raise RuntimeError(f"Unsafe or duplicate license asset: {source_relative}")
        seen.add(source_relative)
        source = (PROJECT / Path(*pure.parts)).resolve()
        try:
            relative_to_license_root = source.relative_to(source_root)
        except ValueError as exc:
            raise RuntimeError(f"License asset escaped its root: {source}") from exc
        if not source.is_file():
            raise RuntimeError(f"Required license asset is missing: {source}")
        expected_size = record.get("size", record.get("bytes"))
        expected_sha256 = record.get("sha256")
        actual_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        if (
            not isinstance(expected_size, int)
            or expected_size < 0
            or source.stat().st_size != expected_size
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or actual_sha256 != expected_sha256
        ):
            raise RuntimeError(f"License asset identity mismatch: {source_relative}")
        destination = (PurePosixPath("licenses") / PurePosixPath(
            relative_to_license_root.as_posix()
        ).parent).as_posix()
        datas.append((str(source), destination))
    return datas


AUDITED_LICENSE_DATAS = (
    audited_manifest_license_datas("qt_static_components.json", path_is_key=True)
    + audited_manifest_license_datas("pytetwild_static_closure.json")
)


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
        "numpy",
        "numpy-2.5.1.dist-info/licenses/LICENSE.txt",
        "licenses/numpy",
    ),
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

APP_LICENSE_DATAS = [
    (str(PROJECT / "licenses" / filename), "licenses")
    for filename in (
        "AGPL-3.0.txt",
        "BINARY_COMPONENT_MAP.schema.json",
        "BUILD_ENVIRONMENT_EN.md",
        "BUILD_ENVIRONMENT_JA.md",
        "LICENSE_APP.txt",
        "LICENSE_CPYTHON_BZIP2.txt",
        "LICENSE_CPYTHON_EXPAT.txt",
        "LICENSE_CPYTHON_LIBMPDEC.txt",
        "LICENSE_CPYTHON_XZ.txt",
        "LICENSE_LIB3MF.txt",
        "LICENSE_LIB3MF_CPP_BASE64.txt",
        "LICENSE_LIB3MF_FAST_FLOAT.txt",
        "LICENSE_LIB3MF_LIBZIP.txt",
        "LICENSE_LIB3MF_ZLIB.txt",
        "LICENSE_LLVM_3_6_2.txt",
        "LICENSE_MESA_12_0_RC2.html",
        "LICENSE_GLEW_2_2_0.txt",
        "LICENSE_LIBE57FORMAT_3_1_1.md",
        "LICENSE_LIBSPATIALINDEX_2_1_0.txt",
        "LICENSE_MUPARSER_2_3_5.txt",
        "LICENSE_QT_ANGLE.txt",
        "LICENSE_QT_LGPL_3_0.txt",
        "LICENSE_U3D.txt",
        "LICENSE_U3D_IJG_JPEG.txt",
        "LICENSE_U3D_LIBPNG.txt",
        "LICENSE_U3D_NICK_BOBIC_QUATERNION.txt",
        "LICENSE_U3D_WCMATCH.txt",
        "LICENSE_U3D_ZLIB.txt",
        "NOTICE_MESA_LLVM.txt",
        "NOTICE_QT.txt",
        "NOTICE_SQLITE_PUBLIC_DOMAIN.txt",
        "NOTICE_U3D_ADDITIONAL.txt",
        "NOTICE_U3D_FNVHASH.txt",
        "NOTICE_U3D_GRAPHICS_GEMS_IV.txt",
        "NOTICE_U3D_SHEWCHUK_PREDICATES.txt",
        "NOTICE_XERCES_C_3_2_4.txt",
        "GPL-3.0.txt",
        "LGPL-2.1.txt",
        "LGPL-3.0.txt",
        "MPL-2.0.txt",
        "RELINKING_EN.md",
        "RELINKING_JA.md",
        "THIRD_PARTY_NOTICES_EN.txt",
        "THIRD_PARTY_NOTICES_JA.txt",
        "THIRD_PARTY_LICENSES.txt",
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
    + APP_LICENSE_DATAS
    + AUDITED_LICENSE_DATAS
    + CPYTHON_LICENSE_DATAS
    + TCL_TK_LICENSE_DATAS,
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
        "PIL.ImageTk",
    ]
    + collect_submodules("scipy._external.array_api_compat.common")
    + collect_submodules("scipy._external.array_api_compat.numpy"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(APP / "pymeshlab_runtime_hook.py")],
    # Decal beta has no public r32 entry point.  Keep its source and source-run
    # tests, but do not ship the unused SVG/Rust renderer in the public frozen
    # application.  PNG decoding remains available through Pillow.
    excludes=["resvg", "resvg._resvg"],
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
