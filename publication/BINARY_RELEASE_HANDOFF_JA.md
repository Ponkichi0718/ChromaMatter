# r32 Windows バイナリ公開 引継ぎ

更新日: 2026-08-23
対象リポジトリ: <https://github.com/Ponkichi0718/ChromaMatter>
作業ブランチ: `codex/r32-full-spectrum-workflow`
Draft PR: <https://github.com/Ponkichi0718/ChromaMatter/pull/1>

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
- 現在の作業treeから公開ソースpreviewを実生成し、privacy監査と全266 manifest
  entryの独立SHA-256再検証に成功した。ただしこれは最終対応ソースbundleではない。

## 残っている公開ブロッカー

2026-08-23時点で、最新sourceはfull regression 1,179件（1 optional skip）、
現在の公開source stageは395 files／394 manifest records、privacy audit、独立
SHA-256 parityまでPASSした。Python 3.13.14のfull regressionは1,234 tests中
1,232 PASS／2 optional SKIP／0 FAIL、release／compliance集中テスト178件も
1 optional SKIP以外PASSしている。これはsource-only branch更新の証拠であり、
Windows binaryの公開GOではない。前回273／272 stageは変更前のprevious evidenceである。

1. **controlled PyTetWild再build証拠**
   prospective build入力とrecipeは固定済みだが、管理者権限が必要なVisual Studio
   Build Toolsのoffline installと、OSレベルで通信を遮断した実buildは未実施。
2. **application lock更新**
   新wheelのSHA-256へapplication requirements lockを更新する。clean bootstrapには
   `-PyTetWildWheel`または`-PyTetWildWheelhouse`でそのwheelを明示し、通常indexの
   歴史wheelへ戻らないようにする。
3. **release-approved完全対応ソースbundle**
   MeshLab外部archive lockとPyTetWild証拠を使って実際のbundleを生成し、
   `known_gaps=[]`と`release-approved`を確認する。
4. **現行sourceからのclean binary build**
   旧r32 build証拠は今回の変更後sourceを検証しない。新しい空build rootで作り直し、
   packaged self-testと隔離profileのJA/EN UI smokeを通す。
5. **fresh-extract実成果物監査**
   manifest、privacy、ZIP CRC、folder／ZIP／fresh-extract byte parity、checksum、
   Qt／GEOS差替えsmokeを実施する。
6. **immutable HTTPS GitHub Release**
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
git switch --track origin/codex/r32-full-spectrum-workflow
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

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tooling\BUILD_PYTETWILD_WINDOWS.ps1 `
  -OsNetworkIsolationConfirmed `
  -OutputRoot C:\ChromaMatterToolchain\pytetwild-controlled-build-001
```

将来buildが成功した場合は、repaired wheelと同名でもpre-repairのraw wheelを
上書きせず別fileとして保存する。さらにattestation、recipe、39-package lock、
source patch、次のexact 8 direct audit logsを同じrelease evidenceとして保存する。

- `visual-studio-layout-verification.log`
- `build-wheel.log`
- `delvewheel-show-raw.log`
- `delvewheel-repair.log`
- `abi3audit.log`
- `native-dependency-closure.log`
- `native-smoke-install.log`
- `native-normal-import.log`

監査log用directoryにはこの8個のdirect fileだけを置く。extra file、nested entry、
symlinkを含めない。その後にapplication lockを新しいrepaired wheelへ更新する。

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1 `
  -PyTetWildWheel C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl
powershell.exe -ExecutionPolicy Bypass -File .\BUILD_AND_TEST.ps1 `
  -RuntimeRoot .\.venv `
  -Build `
  -BuildOutputRoot C:\CMR32AGPL1

$complianceRoot = 'C:\CMR32AGPL1\compliance'
New-Item -ItemType Directory -Force -Path $complianceRoot | Out-Null
& .\.venv\Scripts\python.exe -B .\tooling\generate_binary_compliance_inventory.py `
  --package-root C:\CMR32AGPL1\dist\ChromaMatter `
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
$releaseInputs = 'C:\release-inputs'
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
$controlledRoot = 'C:\ChromaMatterToolchain\pytetwild-controlled-build-001'
$repairedWheels = @(Get-ChildItem -LiteralPath (Join-Path $controlledRoot 'wheel') `
  -Filter 'pytetwild-0.3.0-cp312-abi3-win_amd64.whl' -File)
$rawWheels = @(Get-ChildItem -LiteralPath (Join-Path $controlledRoot 'raw-wheel') `
  -Filter 'pytetwild-0.3.0-cp312-abi3-win_amd64.whl' -File)
if ($repairedWheels.Count -ne 1 -or $rawWheels.Count -ne 1) {
  throw 'Expected exactly one repaired wheel and one distinct raw wheel'
}
$repairedWheel = $repairedWheels[0].FullName
$rawWheel = $rawWheels[0].FullName
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

$sourceStage = 'C:\release\ChromaMatter-0.8beta-r32-complete-corresponding-source'
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
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_software_package.ps1 `
  -BuiltAppRoot C:\CMR32AGPL1\dist\ChromaMatter `
  -Destination C:\release\ChromaMatter-0.8beta-r32-win64 `
  -BinaryComponentMapPath C:\CMR32AGPL1\compliance\BINARY_COMPONENT_MAP.json `
  -SbomPath C:\CMR32AGPL1\compliance\SBOM.cdx.json `
  -CorrespondingSourceArchivePath $sourceArchive `
  -CorrespondingSourceManifestPath $sourceManifest `
  -CorrespondingSourceArchiveSha256 $sourceSha256 `
  -CorrespondingSourceProjectCommit $projectCommit `
  -CorrespondingSourceUrl https://github.com/Ponkichi0718/ChromaMatter/releases/download/TAG/ChromaMatter-0.8beta-r32-complete-corresponding-source.zip
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

- `ChromaMatter-0.8beta-r32-win64.zip`
- `ChromaMatter-0.8beta-r32-complete-corresponding-source.zip`
  （ChromaMatter本体と第三者対応ソースを含む。大きすぎる場合だけ番号付きで分割し、
  `SOURCE_OFFER`にも全partの取得方法を明記する）
- `ChromaMatter-0.8beta-r32-SBOM.cdx.json`
- `ChromaMatter-0.8beta-r32-BINARY_COMPONENT_MAP.json`
- `SHA256SUMS-r32.txt`

GitHubが自動生成する `Source code (zip)` はsubmoduleを含まないため、第三者対応ソースの
代用にしない。完全な対応ソースbundleのimmutable HTTPS最終Release URLを
`SOURCE_OFFER_EN/JA.txt` に反映してからsoftware ZIPを作り、上記assetを同時公開する。

## 公開サンプルについて

作者申告では、公開候補はHi3D Proで生成した3Dモデルで、元の2D生成工程では
TripoAI Proを使用している。サンプルを実際に同梱・公開する前に、生成日、job ID、
当時のplan証跡、入力／出力hash、利用規約の保存、必要なHi3D attributionを記録する。
サブスクリプション加入だけを第三者権利の包括保証とは表現しない。

## 完了条件

最後に、Releaseから全assetを別の空directoryへ再downloadしてhashを照合し、
win64 fresh extractの `--self-test`、日本語／英語 `--ui-smoke`、対応ソースmanifest監査が
すべて通った時だけ `binary_publication_eligible=true` へ変更する。

この文書は技術的・保守的な配布チェックリストであり、法律相談ではない。
