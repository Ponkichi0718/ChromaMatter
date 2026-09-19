#!/bin/bash
set -euo pipefail

# Run on the disposable GitHub macos-15 ARM runner, never on the Windows tree.
stage=${1:?Expected preflight, deps, app, or package}
root=$(cd "$(dirname "$0")/.." && pwd)
source_dir="$root/native"
build_dir="$root/cm-build"
deps_dir="$build_dir/deps-install"
# Keep the upstream native deployment target: wxWidgets uses legacy APIs whose
# declarations are unavailable when compiling with a macOS 15 minimum target.
# The final bundle still requires 15.0 because of its bundled Python helpers.
export MACOSX_DEPLOYMENT_TARGET=12.0
export CMAKE_BUILD_PARALLEL_LEVEL=2
test "$(uname -m)" = arm64
mkdir -p "$build_dir"

install_helpers() {
  local app="$1" helper folder
  mkdir -p "$app/Contents/Helpers"
  for helper in cm-glb-import cm-paint-editor; do
    folder="$helper"
    if [[ "$helper" = cm-glb-import ]]; then folder=cm-import; fi
    ditto "$root/helper-build/dist/$helper.app" "$app/Contents/Helpers/$helper.app"
    mkdir -p "$app/Contents/MacOS/$folder"
    ln -s "../../Helpers/$helper.app/Contents/MacOS/$helper" "$app/Contents/MacOS/$folder/$helper"
    codesign --force --sign - "$app/Contents/Helpers/$helper.app"
    codesign --verify --deep --strict "$app/Contents/Helpers/$helper.app"
  done
}

collect_native_notices() {
  local app="$1"
  python - "$source_dir" "$build_dir/deps" "$app/Contents/SharedSupport/NativeNotices" <<'PY'
from pathlib import Path
import os
import shutil
import sys

native, dependencies, target = map(Path, sys.argv[1:])
target.mkdir(parents=True, exist_ok=False)
shutil.copy2(native / 'LICENSE.txt', target / 'LICENSE.txt')
copied = 0
for label, root in [('native-source', native), ('downloaded-native-dependencies', dependencies)]:
    if not root.is_dir():
        raise RuntimeError('Native dependency sources unavailable for notice collection')
    for directory, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders if name not in {'.git', 'CMakeFiles', '__pycache__'})
        for name in sorted(files):
            path = Path(directory) / name
            if not name.lower().startswith(('license', 'copying', 'notice', 'copyright')):
                continue
            if path.is_symlink() or path.suffix.lower() not in {'', '.txt', '.md', '.rst', '.html', '.htm', '.lesser', '.readme'}:
                continue
            content = path.read_bytes()
            if b'\0' in content:
                continue
            destination = target / label / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            copied += 1
print('Retained existing native notices:', copied)
PY
}

case "$stage" in
  preflight)
    # Exercise the final nested-helper layout before the expensive native build.
    app="$root/preflight/HelperCheck.app"
    test ! -e "$app"
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    # Build our own tiny stub; copying an OS binary also copies protected flags.
    xcrun clang -arch arm64 -mmacosx-version-min=12.0 -x c -o "$app/Contents/MacOS/HelperCheck" - <<'C'
int main(void) { return 0; }
C
    python - "$app/Contents/Info.plist" <<'PY'
import plistlib
import sys
with open(sys.argv[1], 'wb') as stream:
    plistlib.dump({'CFBundleExecutable': 'HelperCheck', 'CFBundlePackageType': 'APPL',
                  'CFBundleIdentifier': 'app.chromamatter.orca.helpercheck',
                  'CFBundleVersion': '1', 'LSMinimumSystemVersion': '15.0'}, stream)
PY
    install_helpers "$app"
    codesign --force --sign - "$app"
    codesign --verify --deep --strict "$app"
    "$app/Contents/MacOS/cm-import/cm-glb-import" --help
    "$app/Contents/MacOS/cm-paint-editor/cm-paint-editor" --help
    ;;
  deps)
    # The cached build is beside native/, under the outer private Git checkout.
    # OCCT/OpenCV patches must be relative to that actual Git root, not native/.
    patch_root=$(git -C "$build_dir" rev-parse --show-toplevel)
    test "$patch_root" = "$root"
    python - "$source_dir/deps/CMakeLists.txt" "$patch_root" <<'PY'
from pathlib import Path
import sys

recipe = Path(sys.argv[1])
old = 'file(RELATIVE_PATH BINARY_DIR_REL  ${CMAKE_SOURCE_DIR}/.. ${CMAKE_BINARY_DIR})'
new = 'file(RELATIVE_PATH BINARY_DIR_REL  "' + sys.argv[2] + '" ${CMAKE_BINARY_DIR})'
text = recipe.read_text()
if old in text:
    assert text.count(old) == 1, 'Unexpected dependency patch-root definition'
    recipe.write_text(text.replace(old, new))
else:
    assert new in text, 'Upstream dependency patch-root definition changed'
PY
    cmake -S "$source_dir/deps" -B "$build_dir/deps" -G Ninja \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 \
      -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0 -DOPENSSL_ARCH=darwin64-arm64-cc \
      -DDESTDIR="$deps_dir" -DDEP_DOWNLOAD_DIR="$build_dir/downloads" \
      -DDEP_BUILD_JOBS=2 -DSLIC3R_SENTRY=OFF
    cmake --build "$build_dir/deps" --target deps --parallel 1
    ;;
  app)
    cmake -S "$source_dir" -B "$build_dir/app" -G Ninja \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 \
      -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0 -DCMAKE_MACOSX_BUNDLE=ON \
      -DCMAKE_PREFIX_PATH="$deps_dir/usr/local" -DSLIC3R_STATIC=ON \
      -DSLIC3R_PCH=ON -DSLIC3R_SENTRY=OFF -DBUILD_TESTS=OFF \
      -DORCA_TOOLS=OFF -DSLIC3R_DESKTOP_INTEGRATION=OFF -DBBL_RELEASE_TO_PUBLIC=1
    cmake --build "$build_dir/app" --target Snapmaker_Orca --parallel 2
    source_app="$build_dir/app/src/Snapmaker_Orca.app"
    if [[ ! -d "$source_app" ]]; then source_app="$build_dir/app/src/Snapmaker Orca.app"; fi
    # Keep notices in the app before the existing completed-app cache is saved.
    collect_native_notices "$source_app"
    ;;
  package)
    source_app="$build_dir/app/src/Snapmaker_Orca.app"
    if [[ ! -d "$source_app" ]]; then
      source_app="$build_dir/app/src/Snapmaker Orca.app"
    fi
    test -d "$source_app"
    mkdir -p "$root/package" "$root/artifacts"
    app="$root/package/Snapmaker Orca with CM Test.app"
    test ! -e "$app"
    ditto "$source_app" "$app"
    # CMake's development Resources symlink must become real bundled resources.
    if [[ -L "$app/Contents/Resources" ]]; then
      unlink "$app/Contents/Resources"
      ditto "$source_dir/resources" "$app/Contents/Resources"
    fi
    # The native app target does not build gettext_po_to_mo automatically.
    # Generate directly in this new app, including on packaging-only retries.
    if ! msgfmt_tool=$(command -v msgfmt); then
      if [[ ! -x "$(brew --prefix gettext)/bin/msgfmt" ]]; then brew install gettext; fi
      msgfmt_tool="$(brew --prefix gettext)/bin/msgfmt"
    fi
    for po in "$source_dir"/localization/i18n/*/Snapmaker_Orca*.po; do
      locale_dir=$(basename "$(dirname "$po")")
      mkdir -p "$app/Contents/Resources/i18n/$locale_dir"
      "$msgfmt_tool" --check-format -o "$app/Contents/Resources/i18n/$locale_dir/Snapmaker_Orca.mo" "$po"
    done
    test -s "$app/Contents/Resources/i18n/ja/Snapmaker_Orca.mo"
    install_helpers "$app"
    test -s "$app/Contents/SharedSupport/NativeNotices/LICENSE.txt"
    cp "$root/CONTOUR_TRIAL_MAC_README_JA.md" "$app/Contents/SharedSupport/"
    cp "$root/CONTOUR_TRIAL_MAC_SOURCE.json" "$app/Contents/SharedSupport/"
    /usr/libexec/PlistBuddy -c 'Set :CFBundleDisplayName Snapmaker Orca with CM Test' "$app/Contents/Info.plist" || \
      /usr/libexec/PlistBuddy -c 'Add :CFBundleDisplayName string Snapmaker Orca with CM Test' "$app/Contents/Info.plist"
    /usr/libexec/PlistBuddy -c 'Set :LSMinimumSystemVersion 15.0' "$app/Contents/Info.plist" || \
      /usr/libexec/PlistBuddy -c 'Add :LSMinimumSystemVersion string 15.0' "$app/Contents/Info.plist"
    # Local ad-hoc signature only: no Developer ID, notarization, or credentials.
    codesign --force --sign - "$app"
    codesign --verify --deep --strict "$app"
    file "$app/Contents/MacOS/Snapmaker_Orca"
    "$app/Contents/MacOS/cm-import/cm-glb-import" --help
    "$app/Contents/MacOS/Snapmaker_Orca" --help > "$root/artifacts/cli-help.txt" 2>&1
    ditto -c -k --sequesterRsrc --keepParent "$app" "$root/artifacts/CM-Contour-Trial-20260920-arm64-app.zip"
    shasum -a 256 "$root/artifacts/CM-Contour-Trial-20260920-arm64-app.zip" > "$root/artifacts/SHA256SUMS"
    cp "$root/CONTOUR_TRIAL_MAC_README_JA.md" "$root/artifacts/"
    cp "$root/CONTOUR_TRIAL_MAC_SOURCE.json" "$root/artifacts/"
    ;;
  *) printf 'Unknown build stage: %s\n' "$stage" >&2; exit 2 ;;
esac
