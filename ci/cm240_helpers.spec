"""Two matching source helpers as nested arm64 application bundles."""
from pathlib import Path
import importlib.metadata
import os
import sys
import sysconfig
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

APP = Path(os.environ["CM_HELPER_SOURCE"]).resolve()
NAME = os.environ["CM_HELPER_NAME"]
if sys.platform != "darwin" or NAME not in ("cm-glb-import", "cm-paint-editor"):
    raise RuntimeError("macOS helpers only")
datas = [(str(APP / "licenses"), "licenses")]
candidates = [Path(sys.base_prefix) / "LICENSE.txt",
              Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
              Path(sys.base_prefix) / "Resources/English.lproj/Documentation/LICENSE.txt",
              Path(sys.base_prefix) / "Resources/Python.app/Contents/Resources/English.lproj/Documentation/LICENSE.txt"]
python_license = next((path for path in candidates if path.is_file()), None)
if python_license is None:
    raise RuntimeError("CPython license missing")
datas.append((str(python_license), "licenses/cpython"))
if NAME == "cm-glb-import":
    entry = "chromamatter_glb_import.py"
    packages = ["numpy", "scipy", "pillow", "pymeshlab", "trimesh", "rtree", "networkx", "shapely", "pyinstaller"]
    datas += [(str(APP / "vendor/assets/mixer_model.npz"), "assets"),
              (str(APP / "vendor/assets/mixer_model_PROVENANCE.md"), "assets"),
              (str(APP / "LICENSE"), "."), (str(APP / "vendor-manifest.json"), "licenses")]
    hiddenimports = ["PIL.PngImagePlugin", "PIL.JpegImagePlugin", "rtree", "pymeshlab"]
    hiddenimports += collect_submodules("scipy._external.array_api_compat.common")
    hiddenimports += collect_submodules("scipy._external.array_api_compat.numpy")
    runtime_hooks = [str(APP / "pymeshlab_runtime_hook.py")]
    excludes = ["tkinter", "matplotlib", "PySide6", "PyQt6", "PyQt5", "pytetwild", "tetgen", "pyvista", "vtk",
                "resvg", "moderngl", "glcontext", "IPython", "pytest", "pandas", "sympy", "tqdm", "spectrum_mapper.gui"]
else:
    entry = "cm_paint_editor.py"
    packages = ["numpy", "Pillow", "moderngl", "glcontext", "pyinstaller"]
    datas += [(str(APP / name), ".") for name in ("vendor-manifest.json", "license-manifest.json", "THIRD_PARTY_NOTICES.md")]
    hiddenimports = collect_submodules("glcontext") + ["moderngl", "_moderngl", "PIL._tkinter_finder"]
    runtime_hooks = []
    excludes = ["spectrum_mapper.engine", "pymeshlab", "trimesh", "scipy", "shapely", "PyQt5", "PySide6", "matplotlib",
                "pytest", "IPython", "notebook", "tkinter.test", "numpy.tests"]
for name in packages:
    distribution = importlib.metadata.distribution(name)
    datas += copy_metadata(name)
    for relative in distribution.files or []:
        text = str(relative).replace("\\", "/")
        if ".dist-info/" in text and ("/licenses/" in text or Path(text).name.lower().startswith(("license", "copying", "notice"))):
            path = Path(distribution.locate_file(relative))
            if path.is_file():
                datas.append((str(path), "licenses/" + name))
a = Analysis([str(APP / entry)], pathex=[str(APP), str(APP / "vendor")], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=runtime_hooks,
             excludes=excludes, noarchive=False, optimize=0)
def keep(item):
    name = str(item[0]).replace("\\", "/").casefold()
    return not (name.startswith("pymeshlab/tests/") or name.endswith((".lib", ".a", ".la"))
                or (".dist-info/" in name and name.endswith("/direct_url.json")))
a.datas = [item for item in a.datas if keep(item)]
a.binaries = [item for item in a.binaries if keep(item)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, disable_windowed_traceback=False, argv_emulation=False,
          target_arch="arm64", codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)
bundle = BUNDLE(coll, name=f"{NAME}.app", bundle_identifier=f"app.chromamatter.orca.{NAME}",
                info_plist={"LSMinimumSystemVersion": "15.0", "LSUIElement": True})
