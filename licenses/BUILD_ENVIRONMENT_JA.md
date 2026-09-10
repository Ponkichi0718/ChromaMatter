# Windows版の正確なビルド環境

バイナリリリースでは対応ソースアーカイブを正しい入力とします。固定した依存
関係、スクリプト、構成表、ソースを一組で使用し、新しいcheckoutを古い
バイナリの対応ソースとして扱わないでください。

**Windows 0.9 のソース同梱配布**では、アプリと同じフォルダの
`corresponding-source/` に完全対応ソース ZIP を置きます。正確なファイル名、
SHA-256、アプリのコミットは `licenses/SOURCE_OFFER_JA.txt` に記録します。
通常のアプリ実行ではソースを展開する必要はありません。以下は再現手順であり、
0.9 のビルドや公開が完了したという証拠ではありません。出力先は毎回、新しい
空のディレクトリを使用してください。

## 固定する基本環境

- Windows x64
- Python 3.13.14 x64
- PyInstaller 6.20.0、one-folder形式、UPX無効
- `source/fixed_app/requirements-build.lock`の固定バージョンとSHA-256

## ビルドとテスト

```powershell
$pyTetWildWheel = 'C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl'
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1 `
  -PyTetWildWheel $pyTetWildWheel
powershell.exe -ExecutionPolicy Bypass -File .\BUILD_AND_TEST.ps1 `
  -RuntimeRoot .\.venv `
  -Build `
  -BuildOutputRoot C:\ChromaMatterBuild
```

## PyTetWildのcontrolled rebuild

採用済み公開wheelは、変更しない固定recipe
`tooling/recipes/BUILD_PYTETWILD_WINDOWS_20260823.ps1`、
`tooling/requirements-pytetwild-build.lock`、および
`tooling/patches/pytetwild-0.3.0-optional-pyvista.patch`を一組で使用します。
固定recipeは82,572 bytes、SHA-256は
`d00cc6cdbc61abeaa040dfc81a3dfe7086ac0027685d798ac70f46e14e4360c8`です。
別ファイルの `tooling/BUILD_PYTETWILD_WINDOWS.ps1` は開発用recipeであり、
その変更は採用済みwheelの証拠にはなりません。採用済みwheelの検証では
代用しないでください。正確なwheelと完全な検証済みbuild証拠を再利用する場合、
native rebuildや管理者確認を再度行う必要はありません。入力やtoolchainを
変更する場合は、新しいbuild証拠を生成して監査してください。
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

Windows PowerShell 5.1では、`vswhere.exe -utf8`の呼出中だけ
`[Console]::OutputEncoding`を厳密なBOMなしUTF-8へ変更し、`finally`で元のencodingへ
復元します。これにより、localized installation nameをactive console code pageで
誤ってdecodeしてJSONを壊すことを防ぎます。

Windows PowerShell 5.1は、multiline sourceをnativeの`python -c`へ直接渡した場合、
埋込みdouble quoteを失うこともあります。recipe内の全multiline Python probeは
`Get-ControlledPythonArguments`を通し、厳密なUTF-8 source bytesをBase64化して、固定の
ASCII bootstrapと元のpositional argumentsを別々に渡します。このtransportを直接の
multiline `-c`引数へ戻さないでください。

実行前にOSまたはhypervisorで外向き通信をdeny-allにするか、builderを物理的に
切断してください。次のswitchは作業者による確認記録であり、script自体がOSの
firewallを設定したという意味ではありません。

```powershell
$newControlledRoot = Join-Path 'C:\ChromaMatterToolchain' `
  ('pytetwild-controlled-build-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tooling\recipes\BUILD_PYTETWILD_WINDOWS_20260823.ps1 `
  -RequirementsLock .\tooling\requirements-pytetwild-build.lock `
  -PyTetWildSourcePatch .\tooling\patches\pytetwild-0.3.0-optional-pyvista.patch `
  -OsNetworkIsolationConfirmed `
  -OutputRoot $newControlledRoot
```

`recipes/` 内に保存したrecipeを実行するときは、上記のlockとpatchへの明示的な
指定が必要です。過去の採用済みcontrolled run
`20260823-174626-089357844d4b`はproject commit
`5feb198eef3432cdec19a0367d53e1b52bd4a363`で成功しました。repaired wheelの
SHA-256は`e3b11ac058266d277b0f83448c6023d5da98e731d0d016e461dbce4ebdfd613d`、
attestationのSHA-256は
`3989fd1debe8b6c984938c4a64ee5fb3bcce1b612cf83524ea309b1fae3cde9f`です。
repaired release wheelとpre-repairのraw wheelは、同名でも上書きしないよう別々に
保存しています。両wheel、attestation、recipe、requirements lock、source patch、
および次のexact 8 direct audit logsを一組のrelease evidenceとして保存します。

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

application lockはすでに採用済みrepaired wheelを固定しています。新しいvirtual
environmentでそのwheelを明示してください。version、ABI tag、SHA-256が一致しない
場合はbootstrapが停止します。将来別wheelへ置き換える場合は、使用前にreview済みの
application lockとstatic-closure contract更新が必要です。

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1 `
  -PyTetWildWheel C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl
```

verified PyTetWild rebuild lockを対応ソースstageへ渡す場合は、
`-PyTetWildRawWheel`と`-PyTetWildAuditLogs`も必須です。
`tooling/generate_pytetwild_rebuild_lock.py` で正確なアプリコミット用のlockを
新しく生成してください。古いアプリの承認を流用するのではなく、native wheelの
保存済み証拠を今回の固定入力へ照合します。次の例は、固定入力をそのコミットから
byte単位で `C:\release-inputs` に書き出し、完全な検証済みソースcacheを準備済み
であることを前提にします。`-Offline` はcacheの不足を取得せずエラーにします。
Pythonやtoolchainの初期導入までオフライン化する指定ではありません。

```powershell
$projectCommit = (git rev-parse HEAD).Trim()
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_corresponding_source.ps1 `
  -Destination C:\release\ChromaMatter-0.9-complete-corresponding-source `
  -Cache C:\ChromaMatterSourceCache `
  -ProjectRepository (Get-Location).Path `
  -ProjectCommit $projectCommit `
  -ExternalArchiveLock .\tooling\meshlab_windows_external_archives.lock.json `
  -PyTetWildRebuildLock C:\release-inputs\pytetwild-rebuild-lock.json `
  -PyTetWildWheel C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl `
  -PyTetWildRawWheel C:\release-inputs\raw-wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl `
  -PyTetWildAuditLogs C:\release-inputs\pytetwild-audit-logs `
  -PyTetWildBuildRecipe C:\release-inputs\BUILD_PYTETWILD_WINDOWS_20260823.ps1 `
  -PyTetWildBuildRequirements C:\release-inputs\requirements-pytetwild-build.lock `
  -PyTetWildSourcePatch C:\release-inputs\pytetwild-0.3.0-optional-pyvista.patch `
  -PyTetWildBuildAttestation C:\release-inputs\pytetwild-build-attestation.json `
  -ApplicationRequirementsLock C:\release-inputs\requirements-build.lock `
  -Offline `
  -Archive C:\release\ChromaMatter-0.9-complete-corresponding-source.zip
```

この例のbuild recipe、PyTetWild build requirements lock、source patch、
application requirements lockは、`$projectCommit`にある各canonical blobと
byte-for-byteで一致させます。最終stage前にこれらの静的入力をcommitしていない
場合、working-tree-onlyのcopyは拒否されます。stage toolはraw/repaired wheelの
別々のidentity/hashと、8個すべての監査logのfilename/SHA-256をattestationに
照合します。その後、各証拠を
`build-evidence/pytetwild/raw-wheel/`、
`build-evidence/pytetwild/repaired-wheel/`、
`build-evidence/pytetwild/logs/`へ別々にstageします。アプリコミットが変わるたびに
完全対応ソースを再生成・再検証してください。過去に成功した対応ソースbundleは、
新しい配布物の内容を証明しません。

`BUILD_AND_TEST.ps1`はPython 3.13.14確認、テスト、固定specでのビルド、必須
ランタイム資材、パッケージ版self-testを確認します。

## バイナリ配布ステージ

`BUILD_AND_TEST.ps1`は正確なone-folder出力から
`compliance/BINARY_COMPONENT_MAP.json`と`compliance/SBOM.cdx.json`を生成
します。配布ステージは両方に加え、最終完全対応ソースarchive、外部manifest、
archiveのSHA-256、ChromaMatterのexact source commitを必須にします。
ソースの提供方式は、検証済みarchiveを同梱する `-BundleCorrespondingSource`、
または同じファイル名の実在する最終HTTPS assetを示す `-CorrespondingSourceUrl`
のどちらか一方を指定します。両方は指定できません。`COMPONENT_SOURCES.json`が
`release-approved`、`known_gaps=[]`、指定commitと一致し、archive内のmanifestと
byte一致する場合だけ続行します。ネイティブファイルの対応漏れ、未入力、
プレースホルダー、EXEハッシュ不一致もfail-closedで停止します。

```powershell
$sourceArchive = 'C:\release\ChromaMatter-0.9-complete-corresponding-source.zip'
$sourceManifest = 'C:\release\ChromaMatter-0.9-complete-corresponding-source\COMPONENT_SOURCES.json'
$sourceCommit = (git rev-parse HEAD).Trim()
$sourceSha256 = (Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_software_package.ps1 `
  -BuiltAppRoot C:\ChromaMatterBuild\dist\ChromaMatter `
  -Destination C:\release\ChromaMatter-0.9-win64 `
  -BinaryComponentMapPath C:\ChromaMatterBuild\compliance\BINARY_COMPONENT_MAP.json `
  -SbomPath C:\ChromaMatterBuild\compliance\SBOM.cdx.json `
  -CorrespondingSourceArchivePath $sourceArchive `
  -CorrespondingSourceManifestPath $sourceManifest `
  -CorrespondingSourceArchiveSha256 $sourceSha256 `
  -CorrespondingSourceProjectCommit $sourceCommit `
  -BundleCorrespondingSource
```

承認済みデモを含める場合は、
`source/fixed_app/public_binary/DemoData/DEMO_DATA_MANIFEST.json` に記載された
GLBとJPGだけを置いたフォルダを `-DemoDataRoot` で追加指定します。他のモデルや
サンプル3MFを混ぜないでください。stageは両payloadのhashを検証し、正規の日英
README・NOTICEを一緒に同梱します。

ソース同梱ZIPでは、`corresponding-source/` に検証済みarchiveを保存します。
再配布でも実行版と一緒に渡してください。copy後に再hashし、ソフト全体の
manifest・ZIP再展開チェックにも含めます。本体だけでなく第三者対応ソースも
含むため、ZIPは大きくなります。ローカルstageの成功は、サイトでの公開、
コード署名、実機印刷の成功を証明しません。

ソースを別に配信する場合は `-BundleCorrespondingSource` を付けず、実在する
`-CorrespondingSourceUrl` を指定し、正確なソースと実行版を同等のアクセス条件で
同時公開してください。ローカルstageだけではURLへのuploadや公開到達性までは
確認できません。stageを通すために未公開の予定URLを作らないでください。
