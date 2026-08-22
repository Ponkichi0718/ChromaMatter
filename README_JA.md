# ChromaMatter — AI Model Print Studio 0.8beta (r32)

<p align="center">
  <img src="source/fixed_app/assets/obj_adjuster_icon.png" width="180" alt="ChromaMatter icon">
</p>

[English README](README.md)

ChromaMatter — AI Model Print Studioは、AI生成された頂点カラー付きOBJまたはUV baseColor付きGLBを、Snapmaker OrcaのFull Spectrum／Color Mixingワークフロー向け3MFへ変換・調整するWindowsデスクトップツールです。独立プロジェクトであり、TripoAI、Hi3D AI、Snapmaker、OpenAIその他第三者の公式・提携製品ではありません。

**AIで作った3Dを、画面の中だけで終わらせない。** ChromaMatterは、AI 3D生成に「カラー造形という出口」を、3Dプリンタに「AIモデルという新しい入力」をつくり、それぞれの利用価値を高めるための橋渡しを目指しています。

- [画像で見る主な機能と制作フロー](FEATURES_JA.md)
- [試作・失敗・実機調整を含む開発記録（note）](https://note.com/ponkichi0718)

公開表示versionは利用者指定どおり`0.8beta`に固定し、editionを`AI Model Print Studio r32`、artifact slugを`r32-ai-model-print-studio`とします。Windowsの数値versionも`0.8.0.0`のままです。

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

## 検証とrelease gate

現在の作業treeはQt／PyMeshLab identity manifest、PyTetWild static-closure contract、resvgのfrozen runtime除外、追加fail-closed package testsを含め、Python `3.13.14`のfull regressionで`Ran 1234 tests: OK (skipped=2)`、1232 PASS／2 optional SKIP／0 FAILです。release／compliance集中テスト178件も1 optional SKIP以外PASSしました。public-source再stageは395 files／394 manifest recordsでprivacy auditと独立SHA-256 parityがPASSしました。

component固有license原文と静的link componentのcoverageは実装済みで、fail-closedなinventory testもPASSしています。旧r32 EXE／ZIPは今回のsourceと一致しないため公開しません。新しいWindows実行ZIPには、controlled PyTetWild再build証拠、そのwheelへ更新したapplication lock、`release-approved`完全対応ソースbundle、現行sourceからのclean binary buildとpackaged self-test／日英UI smoke、fresh-extractのmanifest／privacy／archive／checksum parity、全assetを同時掲載するimmutable HTTPS Release URLが必要です。現時点の`binary publication eligibility`は**false**です。

以下のr31およびCreator Studio r30の結果は各revisionだけに適用する**previous evidence**で、r32へ流用しません。

- r30 full regression: Python `3.13.14`、`Ran 1019 tests in 86.932s: OK (skipped=1)`、1018 PASS／1 optional SKIP
- `C:\OBJAdjR30FIX1`でのPyInstaller `6.20.0` clean build、packaged self-test、隔離profileの日英UI smoke: PASS
- r30 public source 225 files／224 manifest records、software 1,404 files／1,403 manifest records、fresh extract、archive／privacy、detached `SHA256SUMS-r30.txt`契約: PASS

ChromaMatter r31 exact sourceの**previous evidence**は、Python `3.13.14`で`Ran 1024 tests in 100.656s: OK (skipped=1)`、1023 PASS／1 optional SKIPです。`BUILD_AND_TEST.ps1 -RuntimeRoot .\.venv -Build -BuildOutputRoot C:\OBJAdjR31CM1`、PyInstaller `6.20.0` clean build、packaged smoke、13,986,866-byteの`ChromaMatter.exe`、SHA-256 `208167A225A37BAAAA473B574B2F746E46427FD0CA63FC5B7201BF3394243743`、r31 source stage 227／226、software 1,404／1,403、外部`SHA256SUMS-r31.txt`まで完了しました。これはr32を検証しません。アイコンの`passed-by-creator-declaration`、`ZENITH DYNAMICS CORP.`の創作文言、非提携説明は、変更していない同一assetについて保持します。

Icon publication-rights status: `passed-by-creator-declaration`（2026-08-20）。

- r27 full regression: Python `3.13.14`、PyInstaller `6.20`、`Ran 890 tests in 68.257s: OK (skipped=1)`、889 PASS／1 optional SKIP
- preflight EXE: 13,683,090 bytes、version `0.8beta`、SHA-256 `F2AB0AF025430FF3D5587D6C7B2A68365B8C091A7775697A24DDB84DF34EF056`
- public source stage: 204 files／203 manifest records
- software stage: 1,340 files／1,339 manifest records
- source／software ZIP、manifest equality、path safety、CRC、privacy: PASS

上記r31、r30、r27の証拠は各artifactだけに適用し、ChromaMatter r32の合格証拠には流用しません。r29、r28、r26の結果も同様に**previous evidence**です。icon publication rightsと当該asset scopeのowner legal acceptanceはcreator declarationにより記録済みです。physical XP-PEN validationとphysical printはpendingの既知制約です。`binary publication eligibility`は上記の最終release engineering gateがすべて通るまでfalse、`Innovation Fund submission ready`も権利処理済みsampleとOrca／U1 evidenceが揃うまでfalseです。

正本は[CURRENT_STATE.json](CURRENT_STATE.json)と[PROVENANCE.md](PROVENANCE.md)です。

## 開発・テスト

WindowsとPython 3.13で次を実行します。

```powershell
.\BOOTSTRAP_WINDOWS.ps1
```

`-Build`は全回帰後にPyInstaller one-folder buildを作成します。r32の予定stage名は次のとおりで、検証完了までは配布しません。

- source candidate: `ChromaMatter-0.8beta-r32-source-public-20260823`
- gated Windows package: `ChromaMatter-0.8beta-r32-win64`

## プライバシーとライセンス

公開treeや配布候補へ、非公開の検証assetまたは識別可能な詳細を含めません。公開sampleは権利と由来を確認できるものだけを使用します。

アプリケーションは`GPL-3.0-or-later`です。同梱依存関係には別ライセンスがあり、TetGen本体は`AGPL-3.0-or-later`です。binary配布前に`licenses/`とpublication checklistを確認してください。

## AI利用について

ChromaMatterは、企画整理、仕様設計、実装、テスト、文書化、画像制作、GitHub公開作業の各段階でChatGPT／OpenAI CodexなどのAIを活用しています。最終的な仕様、採否、実機検証、公開判断はプロジェクト作者が行っています。

AI生成のコード、画像、説明文には、不自然な表現や技術的な誤りが残る可能性があります。重要な印刷設定はソース、生成3MF、スライサープレビュー、ご自身の実機で確認してください。お気づきの点は[GitHub Issues](https://github.com/Ponkichi0718/ChromaMatter/issues)でお知らせください。
