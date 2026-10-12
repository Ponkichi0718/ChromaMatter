#!/bin/bash
set -euo pipefail
root=${GITHUB_WORKSPACE:?Use the disposable GitHub runner workspace}
config="$root/build-config"
source_dir="$root/native"
source_app="$root/cm-build/app/src/Snapmaker_Orca.app"
app="$root/package/Snapmaker Orca with CM dev3.app"
test "$(uname -m)" = arm64
test -d "$source_app"
test ! -e "$app"
mkdir -p "$root/package" "$root/artifacts"
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
test -s "$app/Contents/SharedSupport/NativeNotices/LICENSE.txt"
cp "$config/CM_DEV3_MAC_README.md" "$root/SOURCE_MANIFEST.json" "$app/Contents/SharedSupport/"
/usr/libexec/PlistBuddy -c 'Set :CFBundleDisplayName Snapmaker Orca with CM dev3' "$app/Contents/Info.plist" || \
  /usr/libexec/PlistBuddy -c 'Add :CFBundleDisplayName string Snapmaker Orca with CM dev3' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :LSMinimumSystemVersion 15.0' "$app/Contents/Info.plist" || \
  /usr/libexec/PlistBuddy -c 'Add :LSMinimumSystemVersion string 15.0' "$app/Contents/Info.plist"
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"
file "$app/Contents/MacOS/Snapmaker_Orca"
"$app/Contents/MacOS/cm-import/cm-glb-import" --help
"$app/Contents/MacOS/cm-paint-editor/cm-paint-editor" --help
"$app/Contents/MacOS/Snapmaker_Orca" --help > "$root/artifacts/cli-help.txt" 2>&1
ditto -c -k --sequesterRsrc --keepParent "$app" "$root/artifacts/CM-dev3-macos-arm64-app.zip"
(cd "$root/artifacts" && shasum -a 256 CM-dev3-macos-arm64-app.zip > SHA256SUMS)
cp "$config/CM_DEV3_MAC_README.md" "$root/SOURCE_MANIFEST.json" "$root/artifacts/"
