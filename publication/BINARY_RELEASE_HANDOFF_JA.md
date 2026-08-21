# r32 Windows バイナリ公開 引継ぎ

更新日: 2026-08-21
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
- Windows ZIPだけを単独公開しない。同じGitHub Releaseから、対応するアプリソース、
  第三者対応ソース、SBOM、SHA256SUMSを同時に取得できる状態にしてから公開する。
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
- PyInstallerでwheel由来のライセンス原文を保持し、実行時不要のWindows `.lib`だけを除外する設定。
- 対応ソース候補を、完全commit、再帰submodule、検証済みarchiveから作る
  `tooling/stage_corresponding_source.py` / `.ps1`。
- software stageで、最終ソースURL、SBOM、binary component map、各license、
  placeholder残存、native未分類をfail-closedに検査する処理。
- 公開treeから欠けていた `tooling/update_budget_filament_library.py` を復元した。

## 残っている公開ブロッカー

1. **PyTetWild wheelのbuild provenance**
   現在固定している公開wheelのSHA-256は分かるが、wheel作成時のnanobind等の正確な
   build依存版がwheelと失効済みCIログから確定できない。推測で埋めない。
   公開用には、build依存・toolchain・MPIRを固定してPyTetWild wheelを再buildし、
   新wheelのSHA-256へrequirements lockを更新する。
2. **対応ソースの最終取得**
   MeshLab、VCGLib、PyMeshLab、Qt、GEOS、Shapely、TetGen、PyTetWild/fTetWild、
   MPIRとnative外部依存を実際に取得し、manifestとarchiveを生成する。
3. **新specからのclean build**
   旧r32 build証拠は今回の変更後sourceを検証しない。新しい空build rootで作り直す。
4. **実成果物監査**
   full regression、packaged self-test、JA/EN UI smoke、manifest、privacy、ZIP CRC、
   folder/ZIP/fresh-extract byte parity、Qt/GEOS差替えsmokeを実施する。
5. **GitHub Release**
   PRをレビューしてmergeし、同じtag/Releaseへ全assetを同時掲載する。

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

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1
powershell.exe -ExecutionPolicy Bypass -File .\BUILD_AND_TEST.ps1 `
  -RuntimeRoot .\.venv `
  -Build `
  -BuildOutputRoot C:\CMR32AGPL1
```

対応ソース取得は、manifestに記録された未解決gapをすべて閉じ、外部archive lockを
指定してから実行する。大容量取得なので、空き容量を先に確認する。

```powershell
Get-PSDrive C
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_corresponding_source.ps1 `
  -Destination C:\CMR32Source1 `
  -Cache C:\CMR32SourceCache `
  -ProjectRepository (Get-Location).Path `
  -ProjectCommit (git rev-parse HEAD) `
  -ExternalArchiveLock .\tooling\meshlab_windows_external_archives.lock.json `
  -Archive C:\CMR32Source1.zip
```

## 想定する同時公開asset

- `ChromaMatter-0.8beta-r32-win64.zip`
- `ChromaMatter-0.8beta-r32-app-source.zip`
- `ChromaMatter-0.8beta-r32-third-party-source.zip`
  （大きすぎる場合のみ番号付きで分割）
- `ChromaMatter-0.8beta-r32-SBOM.cdx.json`
- `SHA256SUMS-r32.txt`

GitHubが自動生成する `Source code (zip)` はsubmoduleを含まないため、第三者対応ソースの
代用にしない。最終Release URLを `SOURCE_OFFER_EN/JA.txt` に反映してからsoftware ZIPを作る。

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
