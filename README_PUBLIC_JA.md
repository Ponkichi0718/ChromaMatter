# ChromaMatter — AI Model Print Studio 0.8beta（r32.2）

<p align="center">
  <img src="source/fixed_app/assets/obj_adjuster_icon.png" width="180" alt="ChromaMatter icon">
</p>

[English README](README.md)

## 使うバージョンを選ぶ

| 種別 | 向いている用途 | 開く場所 |
| --- | --- | --- |
| **公開安定版 r32.2** | 現在ダウンロードできるWindows版と、検証済みのFull Spectrum制作フローを使う | **[安定版r32.2をダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2)** |
| **Flat Four Test 3（実験版）** | Flat Four、白／灰色ハイライト補正、大容量静的GLB、2D彩色フィルターを統合前に試す | **[Windowsテスト版ZIPをダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2-flat4-test3/ChromaMatter-0.8beta-r32.2-flat4-test3-win64.zip)** · [説明と注意事項](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2-flat4-test3) · [Draft PR #7](https://github.com/Ponkichi0718/ChromaMatter/pull/7) |
| **macOS Apple Silicon alpha** | macOS 15以降での協力テスト。Developer ID未署名・未公証で、正式Releaseではありません | **[英語のテスターガイドから開始](publication/MACOS_ALPHA_TESTING_EN.md)** · [テスト掲示板](https://github.com/Ponkichi0718/ChromaMatter/discussions/9) · [再現する不具合を報告](https://github.com/Ponkichi0718/ChromaMatter/issues/new?template=macos_alpha_report.yml) |

実験テスト版は恒久的な別系統ではなく、検証後に通常版へ統合する候補です。
**Flat Four Test 3を別の公開プレリリースとしてダウンロードできます。**
ZIP全体を展開してから起動してください。下の安定版r32.2にはFlat Fourが
入っていないため、Test 3 ReleaseとDraft PR #7を実験版の案内先にしています。

**macOSテスター版はまだ配布承認前です。** Apple Silicon上のCIと配布確認が
通った正確な1つのbuildだけを、上の英語ガイドから案内します。`diagnostics`と
書かれたartifactはapplicationではありません。

## Windows版をダウンロード

**[ChromaMatter 0.8beta r32.2 Windows版（ZIP）をダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-win64.zip)**

ダウンロード後は、ZIPをすべて展開してから起動してください。直リンクで始まらない場合は、[v0.8beta-r32.2のReleaseページ](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2)を開き、**Assets**内の`ChromaMatter-0.8beta-r32.2-win64.zip`を選んでください。

## 機能・作品を見る

- **[機能・操作を画像で見る](FEATURES_JA.md)** — フィラメント候補、混色、実機補正、ブラシ、エアブラシ、なじませ、スポイト
- **[オリジナル作品の制作工程・過去画面・実機出力例を見る](FEATURES_JA.md#project-examples)**
- **[約2分のシンプルな使い方を見る](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-simple-workflow-demo.mp4)**

`v0.8beta-r32.2`はInnovation Fund向けpreviewのGitHub prereleaseとして公開済みです。
Windows package、完全対応source、SBOM、component map、操作動画、detached checksumの
6 assetを公開後に未認証で再downloadし、sizeとSHA-256を再確認しています。

**0.8 betaの重要な制限:** パーツ化モデルの閉立体化はまだ不安定です。同梱の`DemoData`は閉立体化・3MF出力の成功を確認していますが、他の分割ファイルでは閉立体化または3MF出力に失敗することがあります。この互換性が未完成であることが、ChromaMatterを`0.8beta`としている理由の一つです。

ChromaMatter — AI Model Print Studioは、AI生成された頂点カラー付きOBJまたはUV baseColor付きGLBを、Snapmaker OrcaのFull Spectrum／Color Mixingワークフロー向け3MFへ変換・調整するデスクトップツールです。公開安定版はWindows用で、Apple Silicon macOS版は別alphaとして協力検証中です。独立プロジェクトであり、TripoAI、Hi3D AI、Snapmaker、OpenAI、Appleその他第三者の公式・提携製品ではありません。

**AIで作った3Dを、画面の中だけで終わらせない。** ChromaMatterは、AI 3D生成に「カラー造形という出口」を、3Dプリンタに「AIモデルという新しい入力」をつくり、それぞれの利用価値を高めるための橋渡しを目指しています。

- [画像で見る主な機能と制作フロー](FEATURES_JA.md)
- [試作・失敗・実機調整を含む開発記録（note）](https://note.com/ponkichi0718)

## 実機出力結果

全身一体の公開sampleは、Snapmaker U1で**48時間**、prime tower込み**約220 g**で完走しました。意図したグラフィック調の陰影は、通常の鑑賞距離では形と奥行きとして読み取れます。一方で、背面のsupport跡、台座の緩さ、近くで見たときに色境界が整って見えにくい箇所が残りました。結果と動画は[ChromaMatter サンプルキャラ出力編](https://note.com/ponkichi0718/n/nf6c77165127c)で公開しています。

privacy確認済み・字幕付きの[`v0.8beta-r32.2`「シンプルな使い方」（約2分）](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-simple-workflow-demo.mp4)は、公開済みReleaseの独立動画assetです。対応OBJ／GLBの読込、サイズ・形状準備、Full Spectrum 3MFの出力・検証、Snapmaker Orcaでprojectとして開いてsliceする手順、U1での造形までを一続きで確認できます。公開用copyは125.33秒、1920×1080、H.264、音声なしです。

これは実機で確認した観測結果であり、すべてのmodel、filament構成、slicer profile、printerで同じ結果になることを保証するものではありません。印刷前に生成projectとslice previewを確認してください。

公開表示versionは利用者指定どおり`0.8beta`に固定し、公開済みeditionを
`AI Model Print Studio r32.2`、artifact slugを
`r32.2-ai-model-print-studio`とします。Windowsの数値versionも`0.8.0.0`のままです。

[`v0.8beta-r32.2` Release](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2)は、Windows ZIP、完全対応ソース、SBOM、component map、動画、detached checksumを一組として公開済みです。Releaseの正確なsourceはtag `v0.8beta-r32.2`、commit [`aba20685d2fd6987621b2e1e6624f46ea84912a3`](https://github.com/Ponkichi0718/ChromaMatter/commit/aba20685d2fd6987621b2e1e6624f46ea84912a3)に固定しています。default branchの文書だけが公開後に更新される場合がありますが、Releaseのbinaryとsource assetは変わりません。

## AI Model Print Studio r32.2

r32.2はr32.1のapplicationとfail-closed 3MF契約を維持し、`DemoData/3MF/`へ結合6 mesh project
1件とpart別project 6件、計7件の派生demo 3MFを収録しています。Hi3D由来のpart
labelは見た目の形状と一致しないため、filenameを信用せず各projectのgeometryを
確認してください。demoを再出力するときは、実際に黒を入れるF slotを選び、3MF
出力前に**必ず「黒弱め 5〜25%」presetを適用**します。パーツ化modelの閉立体化は
まだ不安定で、同梱demoは成功例であって互換性保証ではありません。r32.2のexact
build、完全対応source、package、fresh extract、checksum、公開後の再download検証は
すべてPASSしています。

## AI Model Print Studio r32.1（公開済みprevious evidence）

r32.1はimmutableな公開済みprevious evidenceです。r32のmodel処理／3MF契約を
維持し、preview表記を「AIモデル色」へ改め、権利確認済みのHi3D分割GLBと元画像を
Windows packageの`DemoData/`へ同梱しました。binaryとsource assetはcommit
`b575b93d973ed67e7ada986469b10b4490eef4e5`に固定され、r32.2の作業はこれらの
配布fileを変更せず、r32.2を検証する証拠としても流用しません。

## AI Model Print Studio r32

r32は、分割GLBをパーツ構成のまま閉立体化して個別3MFへ出力する経路、識別用の疑似色を限定条件で除外する処理、手動変更したF1～F4の変換previewへの明示反映、保守的なSnapmaker Orca Full Spectrum設定を追加します。r31で統一した公開名とアイコン、OBJ／GLB／3MF、project schema、旧設定保存先はそのまま維持します。

### GLB入力 β

- 公開画面の「OBJ / GLBを開く」から、頂点カラーOBJまたは埋込baseColor付きの静的GLBを選べます。Hi3D AIのように頂点カラーOBJを出さないサービスも同じ制作pipelineへ取り込めます。
- GLBのscene／node transform、mesh-node単位のpart、`COLOR_0`、baseColor factor／textureを読み、sRGBを線形空間で補間・合成して既存の頂点色へ焼き付けます。元GLBをサーバーへuploadしません。
- 印刷色に使うのはbaseColorだけです。normal／metallic／roughness map、透明度、animation、skin、morph、Draco、meshopt、BasisU、GPU instancing、外部URIは再現せずfail-closedで停止します。
- UV textureはmesh頂点でsampleするため、面より細かい模様は失われ、面数削減で差が広がる場合があります。上限は512 MiB、300万頂点、300万三角形です。

### 単一GLBのUV seam閉立体化

- part情報がない単一GLBでは、同一座標の境界edgeが逆向きにexact 1:1対応するUV／texture seamかを検証します。閉立体化せず3MF出力を始めた場合も、安全に処理できるmodelだけは閉立体化を宣言して実行し、成功後に出力を再開します。
- 証明できたseamだけを、cleanupとQEM面数削減より前に頂点統合します。三角形の追加・削除・順番変更とpart ID変更を行わないため、manual paintとadaptive treeのface対応をexact carryします。
- この経路は蓋を追加しません。未対応・同方向・曖昧なseam、非manifold化、本当の穴はfail-closedで停止し、処理前のgeometryを維持します。
- 3MF出力前のstrict topology検証は、build item直下だけでなく全`type=model` resourceを対象にします。必須の閉立体検証後にQEM由来の上限内の微小自己交差だけが残る場合はwarningとし、Snapmaker Orcaで「プロジェクトとして開く」を選んだslice preview確認を必須にします。
- 3MFには安定したFull Spectrum layer-cycleとprime towerのbaselineを記録します。Local Z、advanced dithering、pointillism等の実験設定は有効化せず、supportはSnapmaker Orca側で選びます。

### 分割GLBの閉立体化と個別3MF

- 対応する分割GLBは、元のパーツ境界と配置を維持したままパーツ単位で正規化します。別パーツ同士を溶接せず、修復で追加した面も元面と区別して追跡します。
- Hi3D系の分割データで使われる識別用`COLOR_0`は、exporter、node、material、texture、既知paletteの条件がすべて一致した場合だけ除外します。通常の作者指定頂点色は変更しません。
- 結合3MFだけでなく「各印刷パーツを個別3MFで保存」にも同じ厳格検証を適用します。個別出力ではパーツIDと頂点参照を局所番号へ組み直し、不完全または古い対応情報はfail-closedで停止します。

### Manual Editingの表示安定化

- Airbrushの確定待ちguideは2Dのscreen-space feedbackです。viewが変わらない間だけ表示し、zoom、pan、orbit、またはprogrammatic camera changeを検出した瞬間に消します。古い軌跡を変換後の画面座標へ描き直しません。
- guideを消しても、受付済みcommit tokenと1 stroke = 1 Undoのtransactionはexact frameまで保持します。確定した3D色は新しいviewで正しく表示します。
- 円形soft falloff、噴射時間による濃度、visible-face／selected-part guard、Brush、Fill、Smudge、Eyedropper、Windows Pointer pressure／fallback taperの結果は変えません。

### 手修正が増えたときの処理軽量化

- paint batchは対象rootだけのlocal effective-stateを取得し、検証済みgeometry配列を再利用します。各batchで全sceneの色配列とgeometryを作り直しません。
- 互換性を確認できる9層Airbrushはadaptive treeを1回だけtraversalします。旧形式、非同心、または分割形状が前提に合わない場合は、実績のある逐次処理へ安全にfallbackします。
- optimized pathと逐次処理で、encoded output、changed roots、override、adaptive tree、Undo／Redoが一致することを回帰testで確認しています。

### 公開画面

- メイン画面は「フィラメント設定」と「出力設定」の2ページです。長い説明や中間previewタブを減らし、3D previewを広くしています。
- ヘッダーは同梱PNGロゴ、`ChromaMatter`、`AI Model Print Studio`をcompactな2段表示にします。
- mixed paletteはF1+F2、F1+F3…のfamily-major順に固定比率を横並びで示します。表示番号はUI／比較chart専用で、canonical state ID、project、manual paint、3MF recipeは変えません。
- 「全体共通」で16／24／32色を選ぶと既存の全パーツへ反映し、個別パーツ編集中は対象パーツだけを変更します。
- 「基本4色を初期値へ戻す」は公開画面に表示しません。モデルからの自動提案と個別の色編集は維持します。
- 個別変更したF1～F4は「現在の4色をプレビュー・3MFへ反映」で右側previewと3MF paletteへ適用できます。自動提案は既定のままで、既存manual paintはcanonical stateとして保持します。
- 実機黒補正はmixed palette内に置き、表示色と自動配色を保ったまま3MF出力の黒混色だけを弱めます。
- 出力設定の形状再処理は1操作、修復名は「閉立体化」です。

### フィラメント候補β

- PLA（初期値）／ABS β／PETG βを切り替え、選択した1素材だけでF1～F4の候補・手持ちフィラメント・3MFのGeneric material profileを統一します。異素材は1つの印刷ジョブへ混在させません。
- 自動提案は、拡張DB全体をモデルの平均色へ近い順に並べません。選択素材内の実在製品を黒・白・灰・彩色・肌／茶の基準へ対応付けた色域バランス済み候補から4本を選び、似た茶系4本へ偏る回帰を防ぎます。多色／グラデーション糸は自動提案だけから除外し、手動ライブラリには残します。
- 代表的な赤・黒・灰・茶モデルのsoftware-fit診断では、面積加重`ΔE76 <= 12`のcoverageが修正前28.63%から修正後98.37%へ改善しました。これは画面上の近似評価であり、実機の印刷色を保証する数値ではありません。
- Open Filament Databaseの固定snapshotを使い、Geeetech、CC3D、Kingroon、TINMORRYを含む19ブランド・3,497色を収録しています。ABSはPLAより収録色と実測色が少なく、目的色の再現を保証しません。
- 上記4社は、2026-08-19にAmazon.co.jpの代表商品が「星4.0以上かつレビュー20件以上」を満たしたことをメーカー単位の採用根拠にしています。個々の色・SKU・在庫・色精度をAmazon評価済みという意味ではなく、HEXはAmazon画像から推測していません。

件数、出典、再現手順、注意事項は[フィラメント色DB資料](source/fixed_app/resources/filament_db/filament_color_database_README.md)を参照してください。

### Portable project folder

「プロジェクト保存」は次のportable folderを作ります。

```text
project-folder/
  source.obj | source.glb
  project.json
  prepared_geometry.npz
  reference.<ext>        # 元画像がある場合だけ
```

- bundleが一致すればprepared geometryとmanual paintをexact restoreします。
- folderを移動しても内部の相対参照で開けます。
- bundle v2は`source_asset`を正本とし、GLBは`source.glb`を保持します。旧OBJ bundle v1も読めます。
- 旧JSON projectも読めますが、元modelを安全に特定できない場合は利用者がOBJ／GLBを明示選択します。

## 基本手順

1. 「OBJ / GLBを開く」で頂点カラー付きOBJまたはbaseColor付きGLBを選びます。
2. F1～F4と混色数を確認し、必要ならパーツpaletteを調整します。
3. 「マニュアル修正」で色を修正します。
4. 出力設定でサイズと形状診断を確認します。
5. 3MFを書き出し、Snapmaker Orcaでtool順、material profile、previewを確認します。

## 入力・出力上の注意

- OBJ頂点カラーは`v x y z r g b`形式を想定します。
- GLBは静的な埋込baseColor／`COLOR_0`を対象とし、細部は頂点色へ焼き付けた解像度になります。
- 非2-manifold面を含むOBJ／GLBはfail-softで表示・手修正できますが、自動修復や印刷可能性を保証しません。
- 大規模OBJ／GLBの準備や閉立体化には時間とメモリが必要で、200万面級のManual Editingは重くなる場合があります。
- 画面色と実機色は一致を保証しません。同じ造形条件のtest printで確認してください。
- 実験engineのsourceは研究継続のため残していますが、公開workflowからは到達できません。

## 公開済み検証結果

exact r32.2 release buildはcommit
`aba20685d2fd6987621b2e1e6624f46ea84912a3`から生成しました。full regressionは
1,298 test中1,296 PASS／2 optional SKIP／0 FAILです。package内と独立fresh extract後の
self-test／日英UI smokeがPASSし、Windows packageは1,527 file、manifest固定の
DemoData 10 payloadと7件の3MFを収録しています。

release compliance inventoryは1,455 fileでPASSしました。完全対応source archiveは
`release-approved`、42,806 file、既知のsource closure gapは0件です。公開後にr32.2の
6 assetを未認証で再downloadし、sizeとSHA-256の一致を確認しました。Windows ZIPの
SHA-256は`2CEADA98661BAC5D49B759542151C4C484FFF4269D6B5D142EC32FEC544F06D0`、
完全対応source ZIPは
`DCC7EC1AE74F4B790CCAC6B9B18286C7BDAB2829E779F0532E01708727680500`です。

以下はimmutableな**r32.1 previous evidence**であり、r32.2の検証には流用しません。

exact r32.1 release buildはcommit `b575b93d973ed67e7ada986469b10b4490eef4e5`から生成しました。focused suiteは113 test PASS、full regressionは1,277 test中1,274 PASS／3 optional SKIP／0 FAILです。packaged self-testと隔離profileの日英UI smokeもPASSしました。

release compliance inventoryは1,455 file／native 256 fileでPASSしました。Windows packageは1,518 fileで、package内と独立fresh extract後のself-test／日英UI smokeがPASSしています。完全対応ソースbundleは`release-approved`で、既知のsource closure gapはありません。公開後に6 assetを未認証で再downloadし、sizeとSHA-256の一致を確認しました。Windows ZIPのSHA-256は`1215CF77D8C8CB8AA5CE91DC7C84AE13404F3AA46221321807AD2E8A19F9064A`、完全対応ソースZIPは`D5A64F3022265BCE7C5C2DFA0358DFC2C94EEA541A5A4AC5671CE3BA829BE4CC`です。

公開済みr32 Releaseと以下のr31およびCreator Studio r30の結果は各revisionだけに
適用する**previous evidence**で、r32.2へ流用しません。

- r30 full regression: Python `3.13.14`、`Ran 1019 tests in 86.932s: OK (skipped=1)`、1018 PASS／1 optional SKIP
- `C:\OBJAdjR30FIX1`でのPyInstaller `6.20.0` clean build、packaged self-test、隔離profileの日英UI smoke: PASS
- r30 public source 225 files／224 manifest records、software 1,404 files／1,403 manifest records、fresh extract、archive／privacy、detached `SHA256SUMS-r30.txt`契約: PASS

ChromaMatter r31 exact sourceの**previous evidence**は、Python `3.13.14`で`Ran 1024 tests in 100.656s: OK (skipped=1)`、1023 PASS／1 optional SKIPです。`BUILD_AND_TEST.ps1 -RuntimeRoot .\.venv -Build -BuildOutputRoot C:\OBJAdjR31CM1`、PyInstaller `6.20.0` clean build、packaged smoke、13,986,866-byteの`ChromaMatter.exe`、SHA-256 `208167A225A37BAAAA473B574B2F746E46427FD0CA63FC5B7201BF3394243743`、r31 source stage 227／226、software 1,404／1,403、外部`SHA256SUMS-r31.txt`まで完了しました。これはr32.1を検証しません。アイコンの`passed-by-creator-declaration`、`ZENITH DYNAMICS CORP.`の創作文言、非提携説明は、変更していない同一assetについて保持します。

Icon publication-rights status: `passed-by-creator-declaration`（2026-08-20）。

- r27 full regression: Python `3.13.14`、PyInstaller `6.20`、`Ran 890 tests in 68.257s: OK (skipped=1)`、889 PASS／1 optional SKIP
- preflight EXE: 13,683,090 bytes、version `0.8beta`、SHA-256 `F2AB0AF025430FF3D5587D6C7B2A68365B8C091A7775697A24DDB84DF34EF056`
- public source stage: 204 files／203 manifest records
- software stage: 1,340 files／1,339 manifest records
- source／software ZIP、manifest equality、path safety、CRC、privacy: PASS

公開済みr32.1 Releaseと上記r32、r31、r30、r27の証拠は、それぞれの旧artifact
だけに適用します。r32.2同梱demo以外ではパーツ化modelの閉立体化に失敗することが
あり、physical XP-PEN validationもpendingです。icon publication
rightsと当該asset scopeのowner legal acceptanceはcreator declarationにより
記録済みです。

正本は[CURRENT_STATE.json](CURRENT_STATE.json)と[PROVENANCE.md](PROVENANCE.md)です。

## 開発・テスト

WindowsとPython 3.13で次を実行します。

```powershell
$pyTetWildWheel = "C:\path\to\pytetwild-0.3.0-cp312-abi3-win_amd64.whl"
.\BOOTSTRAP_WINDOWS.ps1 -PyTetWildWheel $pyTetWildWheel
```

r32.2はcontrolled PyTetWild wheelをSHA-256で固定しているため、引数なしのbootstrapは異なる過去のPyPI wheelへ戻らず、明示的に停止します。公開済みの[完全対応ソースZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip)内の`build-evidence/pytetwild/repaired-wheel/`にある修復wheel、またはcontrolled recipeで再現したwheelのローカルpathを渡してください。`-PyTetWildWheelhouse`も使用できます。`-SkipInstall`は検証済み環境の再テスト専用です。

`-Build`は全回帰後にPyInstaller one-folder buildを作成します。配布対象のr32.2 fileは[`v0.8beta-r32.2` Releaseページ](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2)にあるimmutable assetです。ローカルのbuild／stage folderはRelease assetではありません。

## プライバシーとライセンス

公開treeや将来の配布候補へ、非公開の検証assetまたは識別可能な詳細を含めません。公開sampleは権利と由来を確認できるものだけを使用します。

アプリケーションは`GPL-3.0-or-later`です。同梱依存関係には別ライセンスがあり、TetGen本体は`AGPL-3.0-or-later`です。公開済みbinaryのライセンス情報は`licenses/`と完全対応ソースassetに収録しています。

## AI利用について

ChromaMatterは、企画整理、仕様設計、実装、テスト、文書化、画像制作、GitHub公開作業の各段階でChatGPT／OpenAI CodexなどのAIを活用しています。最終的な仕様、採否、実機検証、公開判断はプロジェクト作者が行っています。

AI生成のコード、画像、説明文には、不自然な表現や技術的な誤りが残る可能性があります。重要な印刷設定はソース、生成3MF、スライサープレビュー、ご自身の実機で確認してください。お気づきの点は[GitHub Issues](https://github.com/Ponkichi0718/ChromaMatter/issues)でお知らせください。
