# r32.1公開済み／r32.2候補 Windows バイナリ公開 引継ぎ

更新日: 2026-08-24
対象リポジトリ: <https://github.com/Ponkichi0718/ChromaMatter>
作業ブランチ: `codex/r32-2-demo-3mf`

`v0.8beta-r32.1`はcommit `b575b93d973ed67e7ada986469b10b4490eef4e5`に
固定したGitHub prereleaseとして公開済みです。Windows ZIP、完全対応ソース、SBOM、
component map、操作動画、`SHA256SUMS-r32.1.txt`の6 assetは、未認証の再取得でも
size／SHA-256一致を確認済みです。公開済み`v0.8beta-r32`と`v0.8beta-r32.1`の
tag／assetは変更しません。

Release: <https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.1>

Windows ZIP: <https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.1/ChromaMatter-0.8beta-r32.1-win64.zip>

## r32.2ローカル候補（未公開）

r32.1の公開assetは変更せず、新しい`v0.8beta-r32.2`候補としてWindows ZIPと完全対応
ソースを作り直す。表示versionは`0.8beta`、Windows数値versionは`0.8.0.0`のままに
する。r32.2候補は全release gateが完了するまで公開済みとは記載しない。

manifestに固定する`DemoData`入力・派生出力は次のとおり。公開payload rootには、この
一覧とcanonical manifestに記載したfile以外を置かない。

- `Original AI model Color.glb`
- `Reference.jpg`
- `3MF/Original AI model Color_FullSpectrum.3mf`
- `3MF/Original AI model Color_FullSpectrum_parts_2/`内の個別3MF 6件
- `3MF/Original AI model Color_FullSpectrum_parts_2/パーツ別3MF_manifest.json`

manifest外のローカル検証sidecarやその他の生成物は公開payloadに含めない。
`$demoDataPayloadRoot`と`$demoDataManifest`を指定して
stageし、manifest外file、hash不一致、危険な3MF member、private path tokenが1件でも
あればfail closedとする。r32.2の対応ソースURL・SBOM・component map・checksumは、
exact candidate commitで再生成した値へ差し替える。前記r32.1の公開結果とhashは
previous evidenceであり、r32.2を検証しない。

> **0.8betaの重要な制約:** パーツ化modelの閉立体化はまだ不安定です。同梱
> `DemoData`では成功していますが、他のmultipart OBJ／GLBでは閉立体化または
> 3MF出力に失敗することがあります。この互換性の未完成が0.8betaである理由の一つです。

以下の工程と停止条件を、r32.2のexact candidate commitと新しい空の出力rootで
再実行します。記載済みのr32.1結果はprevious evidenceであり、r32.2の代用にしません。

## 最重要の停止条件

- 既存の `ChromaMatter_0.8beta-r32-ai-model-print-studio.zip` と、その中の
  `ChromaMatter.exe` は公開しない。これらは機能検証用の旧成果物であり、今回追加した
  ライセンス原文、ソース案内、SBOM、コンポーネントマップを含まない。
- ChromaMatter本体のライセンスは `GPL-3.0-or-later` のまま維持する。
  TetGen 1.6.0部分は `AGPL-3.0-or-later`、その他の第三者部品は各自のライセンスを維持する。
  配布物全体を一語でAGPLへ「変更した」と説明しない。
- Windows ZIPだけを単独公開しない。同じGitHub Releaseから、ChromaMatter本体と
  第三者部品を一つにまとめた完全な対応ソースbundle、SBOM、component map、
  SHA256SUMSを同時に取得できる状態にしてから公開する。GitHub自動生成source ZIPは
  補助資料にとどめ、`SOURCE_OFFER`の取得先にはしない。
- 対応ソース生成の `known_gaps` が1件でも未解決、clean build・full regression・
  fresh-extract監査のいずれかが未実施または失敗なら、バイナリ公開はNO-GOとする。

## このチェックポイントまでに実装したもの

- Python 3.13.14と25個のWindows wheelをSHA-256で固定した
  `source/fixed_app/requirements-build.lock`。
- `BOOTSTRAP_WINDOWS.ps1` の `--require-hashes --only-binary=:all:` インストール。
- 全ファイル、DLL、PYD、EXEを列挙し、未分類native/reparse pointを拒否する
  `tooling/generate_binary_compliance_inventory.py`。
- CycloneDX 1.5 `SBOM.cdx.json` と `BINARY_COMPONENT_MAP.json` の生成。
- アプリ内の日本語／英語「ライセンス」画面。
- AGPL/GPL/LGPL/MPL原文、第三者通知、SOURCE_OFFERテンプレート、
  LGPLのQt/GEOS差替え説明、build環境説明。
- component固有license原文と静的link component coverage。CPython extension依存、
  Qt／Mesa／LLVM、U3D／lib3mf subcomponent、PyInstaller、Embree同梱oneTBBを
  component map／SBOMへ複数帰属で記録し、software stageで原文とIDをfail-closed検証する。
- PyInstallerでwheel由来のライセンス原文を保持し、実行時不要のWindows `.lib`だけを除外する設定。
- 対応ソース候補を、完全commit、再帰submodule、検証済みarchiveから作る
  `tooling/stage_corresponding_source.py` / `.ps1`。
- software stageで、最終ソースURL、SBOM、binary component map、各license、
  placeholder残存、native未分類をfail-closedに検査する処理。
- 公開treeから欠けていた `tooling/update_budget_filament_library.py` を復元した。
- PyTetWildのWindows再build用に、39個のPython wheelをSHA-256固定したlock、
  全714ファイルを固定したVisual Studio offline layout、固定source commit、MPIR、
  Eigen、通常importまで検証するbuild recipeを用意した。
- PyVistaを入れないChromaMatter用途でも通常importできるよう、PyTetWild 0.3.0の
  optional accessor修正を独立patchとしてhash固定し、対応ソース証拠へ結合した。
- build、delvewheel、abi3、native closure、通常importなど8個の監査logを保存し、
  それぞれのSHA-256をbuild attestationへ結合するようにした。
- MeshLab Windows依存archive 21件の取得元・hash lockを完成させた。TinyGLTF履歴
  archive内の署名なし`premake5.exe`は保存のみ、実行禁止として扱う。
- 対応ソースのZIP/TAR展開は、NUL、非正規／Windows危険path、暗号化、特殊entry、
  Unicode・大文字小文字衝突、file/ancestor衝突をfail-closedで拒否する。
- 採用前の作業treeから公開ソースpreviewを実生成し、privacy監査と全394 manifest
  entryの独立SHA-256再検証に成功した。採用後にsource bytesが変わったため、これは
  previous evidenceであり、最終対応ソースbundleは再生成する。

## 公開前に残っていたブロッカー（完了済み履歴）

公開済みr32の結果はimmutableなprevious evidenceとして分離しました。r32.1ではexact
tagged sourceに対してfocused 113 PASS、full regression 1,277件中1,274 PASS／
3 optional SKIP／0 FAIL、clean build、packaged self-test、日英UI smoke、source・software
stage、fresh-extract監査を新しく実施し、すべて通過しました。以下の番号付き項目は、
公開時に満たしたgateを将来の再releaseでも省略しないための記録です。

controlled PyTetWild run `20260823-174626-089357844d4b`はcommit
`5feb198eef3432cdec19a0367d53e1b52bd4a363`で成功し、outbound deny-allとcleanup、
raw／repaired wheel、exact 8 logs、12 source archives、通常import、attestationを独立監査
済みである。application lockはrepaired wheel SHA-256
`e3b11ac058266d277b0f83448c6023d5da98e731d0d016e461dbce4ebdfd613d`を採用済みで、
static-closure contractもwheelとPYDを固定している。現在のcandidateに同じUAC付きbuildを
再実行する必要はない。固定入力またはtoolchainを変更した場合だけ、新しいcontrolled runを
別rootで行う。

1. **release-approved完全対応ソースbundle**
   MeshLab外部archive lockとPyTetWild証拠を使って実際のbundleを生成し、
   `known_gaps=[]`と`release-approved`を確認する。
2. **現行sourceからのclean binary build**
   旧r32 build証拠は今回の変更後sourceを検証しない。新しい空build rootで作り直し、
   packaged self-testと隔離profileのJA/EN UI smokeを通す。
3. **fresh-extract実成果物監査**
   manifest、privacy、ZIP CRC、folder／ZIP／fresh-extract byte parity、checksum、
   Qt／GEOS差替えsmokeを実施する。
4. **immutable HTTPS GitHub Release**
   source offerへ最終Release URLを固定し、Windows ZIP、完全対応ソース、SBOM、
   component map、SHA256SUMSを同じtag／Releaseへ同時掲載する。

component固有license assetと静的link subcomponent coverageは実装済みである。ただし、
次のclean binaryでcomponent map／SBOMと同梱原文を再生成・再検証するまでは、過去buildを
今回の公開証拠へ流用しない。

## 自宅PCでの再開

```powershell
git clone https://github.com/Ponkichi0718/ChromaMatter.git
Set-Location .\ChromaMatter
git fetch origin
git switch codex/r32-2-demo-3mf
git status --short
```

最初にこの文書と、次の機械可読ファイルを読む。

- `tooling/corresponding_source_components.json`
- `source/fixed_app/requirements-build.lock`
- `licenses/THIRD_PARTY_NOTICES_EN.txt`
- `licenses/RELINKING_JA.md`
- `CURRENT_STATE.json`

小さい検証から開始する。

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -B -m unittest `
  source.fixed_app.test_legal_notice `
  source.fixed_app.test_binary_compliance_inventory `
  source.fixed_app.test_corresponding_source_tooling `
  source.fixed_app.test_release_tooling

& $python .\tooling\stage_corresponding_source.py `
  --manifest .\tooling\corresponding_source_components.json `
  --validate-manifest-only
```

固定環境とclean buildは、既存 `.venv` を再利用せず新しいcloneで行う。

PyTetWild build前に、OS/hypervisorで外向き通信をdeny-allにするか物理的に切断する。
recipe内の疎通probeとprocess proxyは補助防御であり、OSレベル遮断そのものではない。
遮断を確認した作業者だけが次のswitchを付ける。

この環境の実測identityは、VCTools directory 14.44.35207、`cl.exe` file version
19.44.35228.0／product version 14.44.35228.0、`link.exe` file／product version
14.44.35228.0である。14.44.35211はCRT
redistributableのversionなのでVCTools directoryとして使用しない。SDK rootを
明示しない場合は、64-bit native／64-bit WOW6432Node／32-bit viewの
`KitsRoot10`候補から、固定versionのx64 `signtool.exe`と`kernel32.lib`を両方持つ
正確に1個のdistinct rootだけをrecipeが採用する。
現在はnative候補が不完全で、WOW6432Node候補に正確なSDKがある。
Windows PowerShell 5.1でlocalized `vswhere.exe -utf8` JSONを壊さないよう、recipeは
そのnative呼出中だけconsole output decoderを厳密なBOMなしUTF-8へ固定し、`finally`で
以前のencodingへ戻す。この復元契約を外さない。
また、multiline Python sourceをnative `python -c`へ直接渡すと埋込みquoteが失われるため、
全multiline probeを`Get-ControlledPythonArguments`で厳密なUTF-8 bytesからBase64化し、
固定ASCII bootstrapと元argvを別々に渡す。このtransportも直接`-c`へ戻さない。

```powershell
$newControlledRoot = Join-Path 'C:\ChromaMatterToolchain' `
  ('pytetwild-controlled-build-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tooling\BUILD_PYTETWILD_WINDOWS.ps1 `
  -OsNetworkIsolationConfirmed `
  -OutputRoot $newControlledRoot
```

上記は固定入力が変わった場合の再現用であり、現在の採用済みrunを上書きしない。
採用済みrunのrepaired wheelと同名のpre-repair raw wheelは別directoryに保存済みで、
attestation、recipe、39-package lock、source patch、次のexact 8 direct audit logsも
同じrelease evidenceとして保存済みである。

- `visual-studio-layout-verification.log`
- `build-wheel.log`
- `delvewheel-show-raw.log`
- `delvewheel-repair.log`
- `abi3audit.log`
- `native-dependency-closure.log`
- `native-smoke-install.log`
- `native-normal-import.log`

監査log用directoryにはこの8個のdirect fileだけを置く。extra file、nested entry、
symlinkを含めない。application lockは採用済みwheelへ更新済みである。

```powershell
$releaseRunRoot = Join-Path 'C:\ChromaMatterToolchain' `
  ('r322-release-candidate-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $releaseRunRoot) {
  throw "Release run root already exists; choose a new empty root: $releaseRunRoot"
}
$releaseInputs = Join-Path $releaseRunRoot 'inputs'
$buildRoot = Join-Path $releaseRunRoot 'build'
$releaseAssetRoot = Join-Path $releaseRunRoot 'assets'
New-Item -ItemType Directory -Path $releaseRunRoot | Out-Null
New-Item -ItemType Directory -Path $releaseInputs | Out-Null
New-Item -ItemType Directory -Path $releaseAssetRoot | Out-Null

# 採用済みcontrolled runはread-only入力として再利用する。release出力先には使わない。
$controlledRoot = 'C:\ChromaMatterToolchain\pytetwild-controlled-build-20260823-174626-089357844d4b'
$repairedWheels = @(Get-ChildItem -LiteralPath (Join-Path $controlledRoot 'wheel') `
  -Filter 'pytetwild-0.3.0-cp312-abi3-win_amd64.whl' -File)
$rawWheels = @(Get-ChildItem -LiteralPath (Join-Path $controlledRoot 'raw-wheel') `
  -Filter 'pytetwild-0.3.0-cp312-abi3-win_amd64.whl' -File)
if ($repairedWheels.Count -ne 1 -or $rawWheels.Count -ne 1) {
  throw 'Expected exactly one repaired wheel and one distinct raw wheel'
}
$repairedWheel = $repairedWheels[0].FullName
$rawWheel = $rawWheels[0].FullName

powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1 `
  -PyTetWildWheel $repairedWheel
powershell.exe -ExecutionPolicy Bypass -File .\BUILD_AND_TEST.ps1 `
  -RuntimeRoot .\.venv `
  -Build `
  -BuildOutputRoot $buildRoot

$complianceRoot = Join-Path $buildRoot 'compliance'
New-Item -ItemType Directory -Force -Path $complianceRoot | Out-Null
& .\.venv\Scripts\python.exe -B .\tooling\generate_binary_compliance_inventory.py `
  --package-root (Join-Path $buildRoot 'dist\ChromaMatter') `
  --sbom-output (Join-Path $complianceRoot 'SBOM.cdx.json') `
  --component-map-output (Join-Path $complianceRoot 'BINARY_COMPONENT_MAP.json')
if ($LASTEXITCODE -ne 0) { throw 'Binary compliance inventory failed' }
```

対応ソース取得は、外部archive lockとPyTetWild controlled rebuildの証拠一式を
指定して実行する。入力manifestはcandidate固定であり、実取得・hash検証によって
すべてのgapが閉じた場合だけ、出力`COMPONENT_SOURCES.json`が
`release-approved`へ自動昇格する。大容量取得なので、空き容量を先に確認する。
build recipe、PyTetWild build requirements lock、source patch、application lockは
改行変換されたworking-tree fileではなく、指定commitの各canonical blobを
byte-for-byteで書き出したものを使う。4入力とも最終stage前にcommitされている
必要があり、working-tree-onlyの差し替えは拒否される。

```powershell
$python = '.\.venv\Scripts\python.exe'
$projectCommit = (git rev-parse HEAD).Trim()
@'
from pathlib import Path
import subprocess
import sys

commit, destination_root = sys.argv[1:]
files = (
    "tooling/BUILD_PYTETWILD_WINDOWS.ps1",
    "tooling/requirements-pytetwild-build.lock",
    "tooling/patches/pytetwild-0.3.0-optional-pyvista.patch",
    "source/fixed_app/requirements-build.lock",
)
root = Path(destination_root)
root.mkdir(parents=True, exist_ok=True)
for relative in files:
    payload = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{relative}"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    (root / Path(relative).name).write_bytes(payload)
'@ | & $python -B - $projectCommit $releaseInputs
if ($LASTEXITCODE -ne 0) { throw 'Exact committed build inputs export failed' }
$buildRecipe = Join-Path $releaseInputs 'BUILD_PYTETWILD_WINDOWS.ps1'
$buildRequirements = Join-Path $releaseInputs 'requirements-pytetwild-build.lock'
$sourcePatch = Join-Path $releaseInputs 'pytetwild-0.3.0-optional-pyvista.patch'
$applicationLock = Join-Path $releaseInputs 'requirements-build.lock'
$auditLogs = Join-Path $controlledRoot 'logs'
$buildAttestation = Join-Path $controlledRoot 'pytetwild-build-attestation.json'
$rebuildLock = Join-Path $releaseInputs 'pytetwild-rebuild-lock.json'

& $python -B .\tooling\generate_pytetwild_rebuild_lock.py `
  --output $rebuildLock `
  --component-manifest .\tooling\corresponding_source_components.json `
  --project-repository (Get-Location).Path `
  --project-commit $projectCommit `
  --repaired-wheel $repairedWheel `
  --raw-wheel $rawWheel `
  --audit-logs $auditLogs `
  --build-recipe $buildRecipe `
  --build-requirements $buildRequirements `
  --source-patch $sourcePatch `
  --build-attestation $buildAttestation `
  --application-requirements-lock $applicationLock
if ($LASTEXITCODE -ne 0) { throw 'PyTetWild rebuild lock generation failed' }

$sourceStage = Join-Path $releaseAssetRoot `
  'ChromaMatter-0.8beta-r32.2-complete-corresponding-source'
$sourceArchive = "$sourceStage.zip"

Get-PSDrive C
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_corresponding_source.ps1 `
  -Destination $sourceStage `
  -Cache C:\CMR32SourceCache `
  -ProjectRepository (Get-Location).Path `
  -ProjectCommit $projectCommit `
  -ExternalArchiveLock .\tooling\meshlab_windows_external_archives.lock.json `
  -PyTetWildRebuildLock $rebuildLock `
  -PyTetWildWheel $repairedWheel `
  -PyTetWildRawWheel $rawWheel `
  -PyTetWildAuditLogs $auditLogs `
  -PyTetWildBuildRecipe $buildRecipe `
  -PyTetWildBuildRequirements $buildRequirements `
  -PyTetWildSourcePatch $sourcePatch `
  -PyTetWildBuildAttestation $buildAttestation `
  -ApplicationRequirementsLock $applicationLock `
  -Archive $sourceArchive

$sourceManifest = Join-Path $sourceStage 'COMPONENT_SOURCES.json'
$sourceSha256 = (Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash
$softwareStage = Join-Path $releaseAssetRoot 'ChromaMatter-0.8beta-r32.2-win64'
$demoDataPayloadRoot = Join-Path $releaseInputs 'ChromaMatter-r32.2-DemoData-payloads'
$demoDataManifest = Join-Path `
  (Get-Location).Path `
  'source\fixed_app\public_binary\DemoData\DEMO_DATA_MANIFEST.json'

# $demoDataPayloadRootにはmanifest記載の次の10 payloadだけを置く。
#   Original AI model Color.glb
#   Reference.jpg
#   3MF\Original AI model Color_FullSpectrum.3mf
#   3MF\Original AI model Color_FullSpectrum_parts_2\01_RightArm_FullSpectrum.3mf
#   3MF\Original AI model Color_FullSpectrum_parts_2\02_LeftLeg_FullSpectrum.3mf
#   3MF\Original AI model Color_FullSpectrum_parts_2\03_Head_FullSpectrum.3mf
#   3MF\Original AI model Color_FullSpectrum_parts_2\04_LeftArm_FullSpectrum.3mf
#   3MF\Original AI model Color_FullSpectrum_parts_2\05_Torso_FullSpectrum.3mf
#   3MF\Original AI model Color_FullSpectrum_parts_2\06_RightLeg_FullSpectrum.3mf
#   3MF\Original AI model Color_FullSpectrum_parts_2\パーツ別3MF_manifest.json
# canonical README／NOTICE／manifestはrepositoryからstage scriptが同梱する。
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_software_package.ps1 `
  -BuiltAppRoot (Join-Path $buildRoot 'dist\ChromaMatter') `
  -Destination $softwareStage `
  -BinaryComponentMapPath (Join-Path $complianceRoot 'BINARY_COMPONENT_MAP.json') `
  -SbomPath (Join-Path $complianceRoot 'SBOM.cdx.json') `
  -CorrespondingSourceArchivePath $sourceArchive `
  -CorrespondingSourceManifestPath $sourceManifest `
  -CorrespondingSourceArchiveSha256 $sourceSha256 `
  -CorrespondingSourceProjectCommit $projectCommit `
  -CorrespondingSourceUrl https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip `
  -DemoDataRoot $demoDataPayloadRoot `
  -DemoDataManifestPath $demoDataManifest

# Buildで生成したJSON bytesを再serializeせず、固定したRelease asset名へcopyする。
$sbomInput = Join-Path $complianceRoot 'SBOM.cdx.json'
$componentMapInput = Join-Path $complianceRoot 'BINARY_COMPONENT_MAP.json'
$sbomAsset = Join-Path $releaseAssetRoot 'ChromaMatter-0.8beta-r32.2-SBOM.cdx.json'
$componentMapAsset = Join-Path $releaseAssetRoot `
  'ChromaMatter-0.8beta-r32.2-BINARY_COMPONENT_MAP.json'
foreach ($target in @($sbomAsset, $componentMapAsset)) {
  if (Test-Path -LiteralPath $target) {
    throw "Release asset already exists; use a new empty release root: $target"
  }
}
Copy-Item -LiteralPath $sbomInput -Destination $sbomAsset
Copy-Item -LiteralPath $componentMapInput -Destination $componentMapAsset

# Build出力、software stage内、version付きRelease assetのsize／SHA-256を3者照合する。
$paritySets = @(
  @($sbomInput, (Join-Path $softwareStage 'licenses\SBOM.cdx.json'), $sbomAsset),
  @($componentMapInput, (Join-Path $softwareStage 'licenses\BINARY_COMPONENT_MAP.json'), $componentMapAsset)
)
foreach ($paths in $paritySets) {
  $files = @($paths | ForEach-Object { Get-Item -LiteralPath $_ })
  $sizes = @($files | ForEach-Object { $_.Length })
  $hashes = @($paths | ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash })
  if (($sizes | Sort-Object -Unique).Count -ne 1 -or
      ($hashes | Sort-Object -Unique).Count -ne 1) {
    throw "SBOM/component-map byte parity failed: $($paths -join ', ')"
  }
}
```

verified rebuild lockを渡す場合、`-PyTetWildRawWheel`と
`-PyTetWildAuditLogs`も必須である。stage toolはrepaired wheelを
`build-evidence/pytetwild/repaired-wheel/`、raw wheelを
`build-evidence/pytetwild/raw-wheel/`へ別々に保存する。さらに上記8個だけが
監査log directory直下にあることを確認し、それぞれのfilenameとSHA-256を
attestationの`output.audit_logs`と照合してから
`build-evidence/pytetwild/logs/`へ保存する。両wheelについてもattestationに
結合された別々のidentity/hashを検証する。これは将来の最終stage手順であり、
現時点でbuildまたはbuild-evidence stagingが完了したという記録ではない。

## 想定する同時公開asset

- `ChromaMatter-0.8beta-r32.2-win64.zip`
- `ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip`
  （ChromaMatter本体と第三者対応ソースを含む。大きすぎる場合だけ番号付きで分割し、
  `SOURCE_OFFER`にも全partの取得方法を明記する）
- `ChromaMatter-0.8beta-r32.2-SBOM.cdx.json`
- `ChromaMatter-0.8beta-r32.2-BINARY_COMPONENT_MAP.json`
- `ChromaMatter-simple-workflow-demo.mp4`
  （約2分の補助動画。OBJ／GLB読込から3MF出力、Snapmaker Orcaでのslice、
  U1造形までの基本workflowを示す。software ZIPには同梱しない）
- `SHA256SUMS-r32.2.txt`

公開候補tagは `v0.8beta-r32.2`、上記asset名は大文字小文字を含めて固定する。
`SHA256SUMS-r32.2.txt` は補助動画を含む手動添付payload assetをすべて記録する。
最低でもsoftware ZIP、完全対応ソースZIP、version付きSBOM、version付きcomponent map、
補助動画の5件を含め、対応ソースを分割した場合は全partも含める。
`SHA256SUMS-r32.2.txt` 自身はchecksum行の対象に含めない。

GitHubが自動生成する `Source code (zip)` はsubmoduleを含まないため、第三者対応ソースの
代用にしない。完全な対応ソースbundleのimmutable HTTPS最終Release URLを
`SOURCE_OFFER_EN/JA.txt` に反映してからsoftware ZIPを作り、上記assetを同時公開する。

## 公開サンプルについて

project ownerは、同梱候補の分割GLBが有料Hi3D planで生成されたこと、owner自身が作成した
reference画像とともに公開・再配布してよいことを確認した。canonical
`DEMO_DATA_MANIFEST.json`は10 payload（GLB、参照画像、結合3MF、個別3MF 6件、
part manifest）の固定path、size、SHA-256とこの権利gateを記録する。
software stageはmanifestと実bytesが完全一致しない限り失敗する。この確認はowner declaration
であり、第三者IPの独立した法務clearanceやHi3Dとの提携・承認を意味しない。

## 完了条件

最後に、Releaseから全assetを別の空directoryへ再downloadしてhashを照合し、
win64 fresh extractの `--self-test`、日本語／英語 `--ui-smoke`、対応ソースmanifest監査が
すべて通った時だけ `binary_publication_eligible=true` へ変更する。

この文書は技術的・保守的な配布チェックリストであり、法律相談ではない。
