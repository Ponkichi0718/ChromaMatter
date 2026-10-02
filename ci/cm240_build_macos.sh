#!/bin/bash
set -euo pipefail
stage=${1:?Expected preflight, deps, app, or package}
root=${GITHUB_WORKSPACE:?Use the disposable GitHub runner workspace}
config="$root/build-config"
source_dir="$root/native"
build_dir="$root/cm-build"
deps_dir="$build_dir/deps-install"
export MACOSX_DEPLOYMENT_TARGET=12.0
export CMAKE_BUILD_PARALLEL_LEVEL=2
test "$(uname -m)" = arm64
mkdir -p "$build_dir" "$root/artifacts"
# Keep source and ExternalProject builds outside the build-config Git checkout.
# Then upstream OCCT/OpenCV git-apply steps use their own source directory and
# need no old 2.3.6 dependency recipe or patch-root rewrite.
if git -C "$build_dir" rev-parse --show-toplevel >/dev/null 2>&1; then
  printf 'Dependency build must be outside a Git checkout.\n' >&2
  exit 1
fi
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
case "$stage" in
  preflight)
    app="$root/preflight/HelperCheck.app"
    test ! -e "$app"
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    xcrun clang -arch arm64 -mmacosx-version-min=12.0 -x c -o "$app/Contents/MacOS/HelperCheck" - <<'C'
int main(void) { return 0; }
C
    python - "$app/Contents/Info.plist" <<'PY'
import plistlib, sys
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
    python "$config/ci/cm240_editor_smoke.py" \
      --editor "$app/Contents/MacOS/cm-paint-editor/cm-paint-editor" \
      --output "$root/artifacts/editor-preflight"
    ;;
  deps)
    grep -q 'openssl-3.5.7' "$source_dir/deps/OpenSSL/OpenSSL.cmake"
    cmake -S "$source_dir/deps" -B "$build_dir/deps" -G Ninja \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 \
      -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0 -DOPENSSL_ARCH=darwin64-arm64-cc \
      -DDESTDIR="$deps_dir" -DDEP_DOWNLOAD_DIR="$build_dir/downloads" -DSLIC3R_SENTRY=OFF
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
    test -d "$source_app"
    python - "$source_dir" "$build_dir/deps" "$source_app/Contents/SharedSupport/NativeNotices" <<'PY'
from pathlib import Path
import os, shutil, sys
native, dependencies, target = map(Path, sys.argv[1:])
target.mkdir(parents=True, exist_ok=False)
shutil.copy2(native / 'LICENSE.txt', target / 'LICENSE.txt')
for label, root in [('native-source', native), ('downloaded-native-dependencies', dependencies)]:
    for directory, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders if name not in {'.git', 'CMakeFiles', '__pycache__'})
        for name in sorted(files):
            path = Path(directory) / name
            if not name.lower().startswith(('license', 'copying', 'notice', 'copyright')):
                continue
            if path.is_symlink() or path.suffix.lower() not in {'', '.txt', '.md', '.rst', '.html', '.htm', '.lesser', '.readme'}:
                continue
            if b'\0' in path.read_bytes():
                continue
            destination = target / label / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
PY
    ;;
  package)
    source_app="$build_dir/app/src/Snapmaker_Orca.app"
    test -d "$source_app"
    app="$root/package/Snapmaker Orca with CM 2.4.0 Test.app"
    test ! -e "$app"
    mkdir -p "$root/package"
    ditto "$source_app" "$app"
    if [[ -L "$app/Contents/Resources" ]]; then
      unlink "$app/Contents/Resources"
      ditto "$source_dir/resources" "$app/Contents/Resources"
    fi
    for po in "$source_dir"/localization/i18n/*/Snapmaker_Orca*.po; do
      locale_dir=$(basename "$(dirname "$po")")
      mkdir -p "$app/Contents/Resources/i18n/$locale_dir"
      msgfmt --check-format -o "$app/Contents/Resources/i18n/$locale_dir/Snapmaker_Orca.mo" "$po"
    done
    test -s "$app/Contents/Resources/i18n/ja/Snapmaker_Orca.mo"
    install_helpers "$app"
    test -s "$app/Contents/SharedSupport/NativeNotices/LICENSE.txt"
    cp "$config/CM240_MAC_README.md" "$root/SOURCE_MANIFEST.json" "$app/Contents/SharedSupport/"
    /usr/libexec/PlistBuddy -c 'Set :CFBundleDisplayName Snapmaker Orca with CM 2.4.0 Test' "$app/Contents/Info.plist" || \
      /usr/libexec/PlistBuddy -c 'Add :CFBundleDisplayName string Snapmaker Orca with CM 2.4.0 Test' "$app/Contents/Info.plist"
    /usr/libexec/PlistBuddy -c 'Set :LSMinimumSystemVersion 15.0' "$app/Contents/Info.plist" || \
      /usr/libexec/PlistBuddy -c 'Add :LSMinimumSystemVersion string 15.0' "$app/Contents/Info.plist"
    codesign --force --sign - "$app"
    codesign --verify --deep --strict "$app"
    file "$app/Contents/MacOS/Snapmaker_Orca"
    "$app/Contents/MacOS/cm-import/cm-glb-import" --help
    "$app/Contents/MacOS/cm-paint-editor/cm-paint-editor" --help
    "$app/Contents/MacOS/Snapmaker_Orca" --help > "$root/artifacts/cli-help.txt" 2>&1
    ditto -c -k --sequesterRsrc --keepParent "$app" "$root/artifacts/CM-240-Window1-arm64-app.zip"
    shasum -a 256 "$root/artifacts/CM-240-Window1-arm64-app.zip" > "$root/artifacts/SHA256SUMS"
    cp "$config/CM240_MAC_README.md" "$root/SOURCE_MANIFEST.json" "$root/artifacts/"
    ;;
  *) printf 'Unknown stage: %s\n' "$stage" >&2; exit 2 ;;
esac
