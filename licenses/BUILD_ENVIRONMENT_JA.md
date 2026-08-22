# Windows版の正確なビルド環境

バイナリリリースでは対応ソースアーカイブを正しい入力とします。固定した依存
関係、スクリプト、構成表、ソースを一組で使用し、新しいcheckoutを古い
バイナリの対応ソースとして扱わないでください。

## 固定する基本環境

- Windows x64
- Python 3.13.14 x64
- PyInstaller 6.20.0、one-folder形式、UPX無効
- `source/fixed_app/requirements-build.lock`の固定バージョンとSHA-256

## ビルドとテスト

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1
powershell.exe -ExecutionPolicy Bypass -File .\BUILD_AND_TEST.ps1 `
  -RuntimeRoot .\.venv `
  -Build `
  -BuildOutputRoot C:\ChromaMatterBuild
```

## PyTetWildのcontrolled rebuild

公開wheelは、`tooling/BUILD_PYTETWILD_WINDOWS.ps1`、
`tooling/requirements-pytetwild-build.lock`、および
`tooling/patches/pytetwild-0.3.0-optional-pyvista.patch`を一組で使用します。
recipeはCPython 3.12.10、VS Build Tools 17.14.39、インストール済みVCTools
directory version 14.44.35207、`cl.exe` file version 19.44.35228.0／product
version 14.44.35228.0、`link.exe` file／product version 14.44.35228.0、
Windows SDK 10.0.26100.7705、固定source commit、MPIR、Eigen、39個のhash済み
Python wheelを検証します。近接して見える14.44.35211は
CRT redistributableのversionであり、インストール済みVCTools directory version
ではありません。

`-WindowsSdkRoot`を明示しない場合、recipeは64-bit native、64-bit
WOW6432Node、32-bit viewの`KitsRoot10` registry値を調べ、固定versionのx64
`signtool.exe`と`kernel32.lib`の両方を含むdistinct rootが正確に1個だけある場合に
採用します。native側のregistry rootが不完全でも、正確なSDKが
`Program Files (x86)`側にある構成へ対応し、完全なrootが0個または複数ならbuildを
停止します。

実行前にOSまたはhypervisorで外向き通信をdeny-allにするか、builderを物理的に
切断してください。次のswitchは作業者による確認記録であり、script自体がOSの
firewallを設定したという意味ではありません。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tooling\BUILD_PYTETWILD_WINDOWS.ps1 `
  -OsNetworkIsolationConfirmed `
  -OutputRoot C:\ChromaMatterToolchain\pytetwild-controlled-build-001
```

将来buildが成功した場合は、repaired release wheelとpre-repairのraw wheelが
同名でも上書きせず、別々に保存します。両wheel、attestation、recipe、
requirements lock、source patch、および次のexact 8 direct audit logsを一組の
release evidenceとして保存します。

- `visual-studio-layout-verification.log`
- `build-wheel.log`
- `delvewheel-show-raw.log`
- `delvewheel-repair.log`
- `abi3audit.log`
- `native-dependency-closure.log`
- `native-smoke-install.log`
- `native-normal-import.log`

監査log用directoryには、この8個のdirect fileだけを置きます。extra file、
nested entry、symlinkを含めてはいけません。

controlled rebuildしたPyTetWild wheelを使う場合は、先に
`requirements-build.lock`のPyTetWild SHA-256をそのwheelへ更新し、新しい
virtual environmentで次のように明示します。wheel、version、ABI tag、hashが
一致しない場合はbootstrapが停止します。

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1 `
  -PyTetWildWheel C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl
```

verified PyTetWild rebuild lockを対応ソースstageへ渡す場合は、
`-PyTetWildRawWheel`と`-PyTetWildAuditLogs`も必須です。次は将来のstage例であり、
build完了の記録ではありません。

```powershell
$projectCommit = (git rev-parse HEAD).Trim()
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_corresponding_source.ps1 `
  -Destination C:\ChromaMatterSource `
  -Cache C:\ChromaMatterSourceCache `
  -ProjectRepository (Get-Location).Path `
  -ProjectCommit $projectCommit `
  -ExternalArchiveLock .\tooling\meshlab_windows_external_archives.lock.json `
  -PyTetWildRebuildLock C:\release-inputs\pytetwild-rebuild-lock.json `
  -PyTetWildWheel C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl `
  -PyTetWildRawWheel C:\release-inputs\raw-wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl `
  -PyTetWildAuditLogs C:\release-inputs\pytetwild-audit-logs `
  -PyTetWildBuildRecipe C:\release-inputs\BUILD_PYTETWILD_WINDOWS.ps1 `
  -PyTetWildBuildRequirements C:\release-inputs\requirements-pytetwild-build.lock `
  -PyTetWildSourcePatch C:\release-inputs\pytetwild-0.3.0-optional-pyvista.patch `
  -PyTetWildBuildAttestation C:\release-inputs\pytetwild-build-attestation.json `
  -ApplicationRequirementsLock C:\release-inputs\requirements-build.lock `
  -Archive C:\ChromaMatterSource.zip
```

この例のbuild recipe、PyTetWild build requirements lock、source patch、
application requirements lockは、`$projectCommit`にある各canonical blobと
byte-for-byteで一致させます。最終stage前にこれらの静的入力をcommitしていない
場合、working-tree-onlyのcopyは拒否されます。stage toolはraw/repaired wheelの
別々のidentity/hashと、8個すべての監査logのfilename/SHA-256をattestationに
照合します。その後、各証拠を
`build-evidence/pytetwild/raw-wheel/`、
`build-evidence/pytetwild/repaired-wheel/`、
`build-evidence/pytetwild/logs/`へ別々にstageします。この最終evidence stageは
現時点では未実施です。

`BUILD_AND_TEST.ps1`はPython 3.13.14確認、テスト、固定specでのビルド、必須
ランタイム資材、パッケージ版self-testを確認します。

## バイナリ配布ステージ

`BUILD_AND_TEST.ps1`は正確なone-folder出力から
`compliance/BINARY_COMPONENT_MAP.json`と`compliance/SBOM.cdx.json`を生成
します。配布ステージは両方に加え、最終完全対応ソースarchive、外部manifest、
archiveのSHA-256、ChromaMatterのexact source commit、検証済みarchiveとasset名が
一致するHTTPS Release URLを必須にします。`COMPONENT_SOURCES.json`が
`release-approved`、`known_gaps=[]`、指定commitと一致し、archive内のmanifestと
byte一致する場合だけ続行します。ネイティブファイルの対応漏れ、未入力、
プレースホルダー、EXEハッシュ不一致もfail-closedで停止します。

```powershell
$sourceArchive = 'C:\release\ChromaMatter-0.8beta-r32-complete-corresponding-source.zip'
$sourceManifest = 'C:\release\ChromaMatter-0.8beta-r32-complete-corresponding-source\COMPONENT_SOURCES.json'
$sourceCommit = (git rev-parse HEAD).Trim()
$sourceSha256 = (Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_software_package.ps1 `
  -BuiltAppRoot C:\ChromaMatterBuild\dist\ChromaMatter `
  -BinaryComponentMapPath C:\release\BINARY_COMPONENT_MAP.json `
  -SbomPath C:\release\SBOM.cdx.json `
  -CorrespondingSourceArchivePath $sourceArchive `
  -CorrespondingSourceManifestPath $sourceManifest `
  -CorrespondingSourceArchiveSha256 $sourceSha256 `
  -CorrespondingSourceProjectCommit $sourceCommit `
  -CorrespondingSourceUrl https://github.com/OWNER/REPO/releases/download/TAG/ChromaMatter-0.8beta-r32-complete-corresponding-source.zip
```

バイナリと正確なソースを同時に公開してください。ローカルでの成功は、そのURL
へのアップロードや公開到達性までは証明しません。
