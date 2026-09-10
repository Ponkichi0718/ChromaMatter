# ChromaMatter — AI Model Print Studio 0.9（r33）

<p align="center">
  <img src="source/fixed_app/assets/obj_adjuster_icon.png" width="180" alt="ChromaMatter icon">
</p>

[English README](README.md)

## 0.9の主な更新：3MF出力精度・成功率の向上

0.9の中心は、通常の単一論理GLBから3MFへ出力する際の精度と成功率の向上です。
証明できる完全一致の継ぎ目を先に統合し、残った開口のうち幅2.0 mm以下かつ厳格に
平面と判定できる微小な穴だけを限定補修します。形状チェックの初期値［高］では、
穴なし・非多様体なし・面向き・正体積・自己交差を従来どおり安全側で最終検証します。
通常の継ぎ目検証を内部の微小断片が妨げる場合は、主表面が全体の
99.5%以上を占め、除外対象が内部の微小な反転閉殻または範囲内の開いた微小断片だと
証明でき、残す主表面だけでも選択的な継ぎ目統合で閉じる場合に限って再試行します。
正体積の独立パーツがある場合は削除せず安全停止し、再メッシュやボクセル化も行いません。
複雑なパーツ化モデルの修復はまだ入力依存であり、0.9で完全解決した
とは扱いません。ラジアル実験はアプリ画面から削除しました。
公式サイトではChromaMatter 0.9を配布しています。このリポジトリのアプリソースは、
公開Windows版のcommit `5059163a1a6d05e823c44323558f344ad000b580` に対応します。
現在の配布案内と独立したCI設定は別途更新しています。macOS・Linux版の正確な
対応ソースは、それぞれの配布bundleを参照してください。
詳細は[0.9の配布物とソースの範囲](RELEASE_0.9.md)に記載しています。

## ダウンロード

[公式ダウンロードページ](https://chromamatter.app/download)と同じ、既存の0.9配布物です。

| OS | 配布内容 | ダウンロード |
| --- | --- | --- |
| **Windows 64-bit** | ChromaMatter 0.9アプリZIP。新規作業はFlat Fourで始まり、同じアプリでFull Spectrumも選べます。 | [Windows ZIP](https://chromamatter.app/downloads/ChromaMatter-0.9-win64-app.zip) |
| **macOS** | Apple Silicon／macOS 15以降向け0.9 technical alpha。 | [macOS ZIP](https://chromamatter.app/downloads/ChromaMatter-0.9-macos-arm64-app.zip) |
| **Linux x86_64** | Ubuntu 22.04以降向け0.9 technical alpha。 | [Linux archive](https://chromamatter.app/downloads/ChromaMatter-0.9-linux-x86_64.tar.xz) |

完全対応ソースはOSごとの公式別配布です。
[Windows](https://chromamatter.app/downloads/ChromaMatter-0.9-complete-corresponding-source.zip)、
[macOS](https://chromamatter.app/downloads/ChromaMatter-0.9-macOS-corresponding-source.zip)、
[Linux](https://chromamatter.app/downloads/ChromaMatter-0.9-Linux-complete-corresponding-source.zip)から、
使用するアプリと同じOSのbundleを取得してください。このリポジトリのWindows用
ソースcommitが、3種類すべてのバイナリに共通するという意味ではありません。

Windows配布名：`ChromaMatter-0.9-win64-app.zip`（115,342,658 bytes）。
SHA-256：`947116390bf3c71158b313edd213043c42a7c11e84e178764bcd5ef23d3d7329`。

アプリのarchive全体を展開してから起動してください。DemoDataは同梱せず、公式で
別途配布しています。過去のReleaseと配布物は変更していません。今回のリポジトリ
同期では、アプリの再ビルドや各OS上の動作、GUI、スライス、実印刷の再検証は行っていません。

## 機能・作品を見る

- **[機能・操作を画像で見る](FEATURES_JA.md)** — フィラメント候補、混色、実機補正、ブラシ、エアブラシ、なじませ、スポイト
- **[オリジナル作品の制作工程・過去画面・実機出力例を見る](FEATURES_JA.md#project-examples)**
- **[約2分のシンプルな使い方を見る](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-simple-workflow-demo.mp4)**

`v0.8beta-r32.2`は過去に公開したInnovation Fund向けpreviewのGitHub prereleaseです。
Windows package、完全対応source、SBOM、component map、操作動画、detached checksumの
6 assetを公開後に未認証で再downloadし、sizeとSHA-256を再確認しています。

**過去の0.8 betaの制限:** パーツ化モデルの閉立体化は入力依存でした。確認済みのdemo結果は、ほかのモデルでも成功する証明ではありません。これらはr32.2の観測記録であり、0.9を新たに検証した結果ではありません。

ChromaMatter — AI Model Print Studioは、AI生成された頂点カラー付きOBJまたはUV baseColor付きGLBを、4本の実フィラメントで扱える3MFへ変換・調整するデスクトップツールです。Windows版に加え、macOSとLinuxの協力検証経路があります。独立プロジェクトであり、TripoAI、Hi3D AI、Snapmaker、OpenAI、Appleその他第三者の公式・提携製品ではありません。

**AIで作った3Dを、画面の中だけで終わらせない。** ChromaMatterは、AI 3D生成に「カラー造形という出口」を、3Dプリンタに「AIモデルという新しい入力」をつくり、それぞれの利用価値を高めるための橋渡しを目指しています。

- [画像で見る主な機能と制作フロー](FEATURES_JA.md)
- [試作・失敗・実機調整を含む開発記録（note）](https://note.com/ponkichi0718)

## 実機出力結果

全身一体の公開sampleは、Snapmaker U1で**48時間**、prime tower込み**約220 g**で完走しました。意図したグラフィック調の陰影は、通常の鑑賞距離では形と奥行きとして読み取れます。一方で、背面のsupport跡、台座の緩さ、近くで見たときに色境界が整って見えにくい箇所が残りました。結果と動画は[ChromaMatter サンプルキャラ出力編](https://note.com/ponkichi0718/n/nf6c77165127c)で公開しています。

privacy確認済み・字幕付きの[`v0.8beta-r32.2`「シンプルな使い方」（約2分）](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-simple-workflow-demo.mp4)は、公開済みReleaseの独立動画assetです。対応OBJ／GLBの読込、サイズ・形状準備、Full Spectrum 3MFの出力・検証、Snapmaker Orcaでprojectとして開いてsliceする手順、U1での造形までを一続きで確認できます。公開用copyは125.33秒、1920×1080、H.264、音声なしです。

これは実機で確認した観測結果であり、すべてのmodel、filament構成、slicer profile、printerで同じ結果になることを保証するものではありません。印刷前に生成projectとslice previewを確認してください。

公開Windows版は`0.9（r33）`で、数値versionは`0.9.0.0`です。
公開済み`0.8beta（r32.2）`と`r32.2-ai-model-print-studio` artifactは、過去の
release証跡として変更しません。

ChromaMatterは、Windows／macOS／Linuxをそれぞれ案内する独立desktop projectです。TripoAI、Hi3D AI、Snapmaker、OpenAI、Appleその他の第三者による公式製品・提携製品ではありません。

## 現在の状態

- **公式の配布version:** 0.9。このリポジトリのアプリソースは、上記のWindows用ソースcommitに対応します。
- **色変換:** 新規作業とcommand-line変換は**Flat Four**で開始します。同じアプリで**Full Spectrum**も選べ、旧schema v12 projectはFull Spectrumとして開きます。
- **macOS・Linux:** 公式0.9 technical alphaとOS別の対応ソースを上で案内しています。各バイナリの正確なソースとOS固有の検証記録は、それぞれのbundleを参照してください。
- **DemoData:** アプリには同梱せず、公式で別途配布しています。
- **実機記録:** リンク先の過去sampleはSnapmaker U1で完走しました。すべてのモデル・条件での成功や、今回の0.9実印刷検証を示すものではありません。
- **過去のrelease evidence:** [`v0.8beta-r32.2` Release](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2)とcommit [`aba20685d2fd6987621b2e1e6624f46ea84912a3`](https://github.com/Ponkichi0718/ChromaMatter/commit/aba20685d2fd6987621b2e1e6624f46ea84912a3)は変更しません。そのソース・バイナリ・checksum・検証結果は、そのreleaseだけに適用します。

現在の配布物と今回の同期範囲は[RELEASE_0.9.md](RELEASE_0.9.md)を参照してください。

## Flat FourとFull Spectrum

新しい作業ではFlat Fourを初期値とし、混色recipeが有効なmodelではFull Spectrumを任意で選べます。

- **Flat Four**は、モデル表面の面積を加味して、重複しない4本の実フィラメントを
  決定的に自動提案します。混色recipeは作らず、Flat Fourの3MFはF1～F4だけを
  使用します。
- **2D彩色フィルター**は、**Cel Colour（セル彩色）**と
  **Shaded Monochrome（陰影モノクロ）**を提供します。形状を使った固定正面光と
  段階的な陰影を印刷対象色へ焼き付ける処理で、screen-space rendererでは
  ありません。元データにない描線、PBR material、texture細部は再現できません。
- 静的GLBの通常上限は512 MiB／300万頂点／300万三角形のままです。別のβ経路では、
  300万超～500万三角形の静的`TRIANGLES` sceneに限り、明示確認と面数調整ONを
  条件として、最大45万面の作業用modelへ縮約して読み込めます。非対応・曖昧な
  inputはfail-closedで停止し、縮約により細かな形状や焼付textureが失われる場合が
  あります。
- 現在のsourceはproject schema `obj-adjuster.project.v13`を書き出します。
  v12は引き続き読込でき、旧来のFull Spectrum modeとして開きます。

現在のsourceと今後のpackageは、それぞれ独立した回帰test・package・compliance gateを
通す必要があります。過去のr32.2 binaryや実機出力の検証実績は流用しません。

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
4. 画面下部の［出力設定］から別ウィンドウを開き、サイズを確認します。
   ［閉立体化］は［3MFを書き出す］の隣にある独立ボタンです。修復が必要な場合に実行します。
5. 3MFを新しい保存先へ書き出し、Snapmaker Orcaでtool順、material profile、スライスプレビューを確認します。

［形状チェック］の初期値は［高］です。［中］［低］［形状の不具合を無視（非推奨）］は
出力時の検証だけを変更し、モデルを修復したり手動の［閉立体化］を緩めたりしません。
［高］以外では問題のある形状も出力される場合があり、毎回確認が必要です。
色とアーカイブ構造の検証はどの設定でも維持します。

## 入力・出力上の注意

- OBJ頂点カラーは`v x y z r g b`形式を想定します。
- GLBは静的な埋込baseColor／`COLOR_0`を対象とし、細部は頂点色へ焼き付けた解像度になります。
- 非2-manifold面を含むOBJ／GLBはfail-softで表示・手修正できますが、自動修復や印刷可能性を保証しません。
- 大規模OBJ／GLBの準備や閉立体化には時間とメモリが必要で、200万面級のManual Editingは重くなる場合があります。
- 画面色と実機色は一致を保証しません。同じ造形条件のtest printで確認してください。
- 実験engineのsourceは研究継続のため残していますが、公開workflowからは到達できません。

## 過去の公開版の検証結果

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

## 開発・テスト（過去のr32.2再現）

以下はtag `v0.8beta-r32.2` の再現手順です。現在の0.9の対応ソースは
[RELEASE_0.9.md](RELEASE_0.9.md)から取得してください。WindowsとPython 3.13で実行します。

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
