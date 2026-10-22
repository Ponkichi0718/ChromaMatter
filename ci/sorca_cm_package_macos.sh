#!/bin/bash
set -euo pipefail
root=${GITHUB_WORKSPACE:?Use the disposable GitHub runner workspace}
config="$root/build-config"
source_dir="$root/native"
source_app="$root/cm-build/app/src/Snapmaker_Orca.app"
app="$root/package/Sorca CM.app"
label=${SORCA_RELEASE_LABEL:?Expected reviewed source release label}
[[ "$label" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]]
artifact="Sorca-CM-${label}-macos-arm64-app.zip"
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
cp "$config/SORCA_CM_MAC_README.md" "$root/SOURCE_MANIFEST.json" "$app/Contents/SharedSupport/"
python - "$app/Contents/Info.plist" "$root/SOURCE_MANIFEST.json" "$label" <<'PY'
import json, plistlib, sys
path, manifest, label = sys.argv[1:]
assert json.load(open(manifest))['release_label'] == label
with open(path, 'rb') as stream:
    info = plistlib.load(stream)
# Display branding only: executable, internal app key, existing bundle identifier
# and startup graphics are unchanged. CM explicitly disables OS associations.
info['CFBundleDisplayName'] = 'Sorca CM'
info['CFBundleName'] = 'Sorca CM'
info['LSMinimumSystemVersion'] = '15.0'
info.pop('CFBundleURLTypes', None)
info.pop('CFBundleDocumentTypes', None)
with open(path, 'wb') as stream:
    plistlib.dump(info, stream)
PY
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"
file "$app/Contents/MacOS/Snapmaker_Orca"
lipo -verify_arch arm64 "$app/Contents/MacOS/Snapmaker_Orca"
"$app/Contents/MacOS/cm-import/cm-glb-import" --help
"$app/Contents/MacOS/cm-paint-editor/cm-paint-editor" --help
"$app/Contents/MacOS/Snapmaker_Orca" --help > "$root/artifacts/cli-help.txt" 2>&1
python - "$root/artifacts/BUILD_RECORD.json" <<'PY'
from pathlib import Path
import json, sys
path = Path(sys.argv[1]); record = json.loads(path.read_text())
record.update(status='package_cli_signature_checks_passed', native_build_completed=True,
              helper_cli_checked=True, ad_hoc_signature_checked=True)
path.write_text(json.dumps(record, indent=2) + '\n')
PY
cp "$root/artifacts/BUILD_RECORD.json" "$app/Contents/SharedSupport/"
# Adding build evidence changes resources, so sign and verify the final bytes.
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"
ditto -c -k --sequesterRsrc --keepParent "$app" "$root/artifacts/$artifact"
(cd "$root/artifacts" && shasum -a 256 "$artifact" > SHA256SUMS)
cp "$config/SORCA_CM_MAC_README.md" "$root/SOURCE_MANIFEST.json" "$root/artifacts/"
