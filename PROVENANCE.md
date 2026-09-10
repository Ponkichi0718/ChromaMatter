# ChromaMatter — AI Model Print Studio 0.9 (r33) provenance

更新日: 2026-09-05
現在の開発revision: `r33-ai-model-print-studio`

## 0.9開発チェックポイント

0.9の主なversion-up機能は、通常の単一論理GLBから3MFへ出力する際の精度と
成功率の向上です。同一座標の重複シームを結合し、幅2.0 mm以下で厳密に平面な
微小開口だけを局所補修できます。補修後も閉立体、非多様体辺、面向き、正体積、
縮退面、自己交差の最終検証をfail-closedで行います。複雑なパーツ化モデルの修復は
入力依存であり、0.9で完全解決したとは主張しません。

失敗後の3D開口確認導線は削除し、ラジアル実験は公開UIから削除して設定読込時にも
無効化します。互換性と研究記録のため実験sourceは保持します。現時点では0.9の
実行ファイル、archive、tag、releaseを作成・公開していません。

以下は公開済み0.8beta系列の由来と固定済み証拠です。既存tag、asset、checksum、
commitを0.9として読み替えたり差し替えたりしません。

## 1. 公開済み0.8beta系列のプロジェクトとidentity

ChromaMatter — AI Model Print Studioは、AI生成された頂点カラー付きOBJまたはUV baseColor texture付きGLBを、Snapmaker OrcaのFull Spectrum／Color Mixingワークフロー向け3MFへ変換・調整する独立プロジェクトです。Hi3D AI、TripoAI、Snapmaker、Blender、ZBrush、Substance 3D Painter、OpenAIまたは各社の公式・提携製品ではありません。

表示versionは利用者の指定どおり`0.8beta`、Windows数値versionは`0.8.0.0`に固定し、人向けeditionを`AI Model Print Studio r32.1`とします。

- published complete corresponding source: `ChromaMatter-0.8beta-r32.1-complete-corresponding-source.zip`
- published Windows package: `ChromaMatter-0.8beta-r32.1-win64.zip`
- immutable release tag: `v0.8beta-r32.1`
- exact tagged commit: `b575b93d973ed67e7ada986469b10b4490eef4e5`
- release: [https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.1](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.1)
- direct Windows download: [ChromaMatter-0.8beta-r32.1-win64.zip](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.1/ChromaMatter-0.8beta-r32.1-win64.zip)

## 2. r32.1更新とr32出力workflowの継承

r32.1は公開previewの「Tripo 元モデル色」を「AIモデル色」へ変更し、権利確認済みのHi3D分割GLBと元画像をWindows packageの`DemoData/`へ加えるpost-r32更新です。demoではimportしたpart名をsemanticな印刷part名として信用せずpreviewで対象を確認し、3MF出力前に実際の最暗filamentを選んで「黒弱め 5〜25%」presetを必ず適用します。model処理、閉立体化、識別色抑制、palette、manual paint、3MF provenanceのr32契約は変更しません。公開済み`v0.8beta-r32`のtag／assetは変更せずprevious evidenceとして保持します。

> **分割モデル閉立体化の0.8beta制約:** 同梱`DemoData/`は閉立体化と3MF出力の成功を確認済みですが、ほかの分割modelでは閉立体化または3MF出力に失敗する場合があります。すべての入力を安定して修復できる段階ではなく、これが`0.8beta`である理由の一つです。

r32は、閉立体化前の適格modelを3MF出力しようとした場合に、安全確認済みのpart境界またはGLB同一座標seamだけを閉立体化すると宣言し、成功後に同じ出力操作を再開します。本当の穴へ推測で蓋を追加せず、対応を証明できない境界、非manifold結果、または処理失敗は従来どおりfail-closedです。

基本F1～F4を利用者が個別変更した場合は、明示的な「現在の4色をプレビュー・3MFへ反映」操作で、既存のmanual paintをcanonical stateのまま再解釈してFull Spectrum previewと3MF paletteを更新します。model読込時の自動提案を既定とし、色変更だけでmanual paintやproject stateを破壊しません。

3MFにはSnapmaker Orca Full Spectrumの安定したlayer-cycleとprime-tower baselineを明示します。Local Z、advanced dithering、pointillism等の実験設定は有効化せず、supportはChromaMatterから強制しません。これは印刷品質の保証ではなく、Snapmaker Orcaでprojectとして開き、slice previewと実機条件を確認する前提です。

### 実験的テストワークストリーム

この実験ブランチには、公開済みr32.2 tag／binary／対応sourceを変更せず、次の機能が
入っています。

- Flat Fourは、モデル表面の面積加重color distributionから、同一素材かつ重複しない
  4本の実フィラメントを決定的に提案します。混色recipeは生成せず、Flat Fourの
  3MFは物理tool F1～F4だけを使用します。既存のmixed stateやmanual paintを
  破壊して保存し直すのではなく、Flat出力境界でF1～F4へ投影します。
- 2D彩色フィルターのCel ColourとShaded Monochromeは、mesh normalを使った
  固定正面光と2～6段階の陰影を通常の印刷対象RGBへ焼き付けます。geometry、part、
  manual paintを変更するscreen-space effectではありません。描線生成、PBR lighting、
  元textureにない細部の復元は行いません。
- 静的GLBの通常limitは512 MiB／300万頂点／300万三角形のままです。別のβ経路は、
  頂点上限を満たす300万超～500万三角形の静的`TRIANGLES` sceneだけを、利用者の
  明示確認と面数調整ONを条件に最大45万面の作業用modelへ縮約します。条件外、
  曖昧な構造、file差し替え、縮約後limit超過はfail-closedです。縮約は細かな形状や
  頂点へ焼き付けたtexture detailを失う場合があります。
- このワークストリームはproject schema `obj-adjuster.project.v13`を書き、v12を
  旧来のFull Spectrum modeとして読み込みます。palette canonical state ID、physical
  tool F1～F4、portable bundle v2は維持します。

現時点の証拠はローカルsource回帰testだけです。公開済みr32.2のbinary、package、
実機出力の検証実績を、この未公開ワークストリームへ流用しません。個人所有modelや
内部packageを公開source、manifest、配布物へ加えません。

r31は公開名を`ChromaMatter — AI Model Print Studio`へ変更し、利用者提供画像を基にした新しいアイコンへ統一します。原本、透過PNG、ICOの変換内容とSHA-256はアイコンprovenance sidecarに記録します。2026-08-20、利用者兼project creatorは、ロボットが参考資料の影響を受けつつも既存character／製品を再現する意図のないオリジナルの架空機体であり、胸部の`ZENITH DYNAMICS CORP.`も実在組織との関係を示す意図のない創作上の文言であると申告し、この画像をChromaMatterのrepository、実行file、画像、動画、Innovation Fund応募で公開・再配布することを承認して公開GOを出しました。この記録はcreator declarationであって、独立した商標調査、第三者意匠clearance、法的意見ではありません。basic exact-match web checkでは`ZENITH DYNAMICS CORP.`と`ChromaMatter`の完全一致を確認できませんでしたが、近似名`Zenith Dynamics`を使う複数の実在組織があるため、非提携を明示し、世界的な権利clearanceを主張しません。既存project、settings、schemaを読み続けるため、保存形式内の`obj-adjuster.*`識別子と旧AppData保存先は互換性識別子として維持します。

r30はr29の混色palette／比較chart、フィラメントDB、OBJ／GLB入力、自動提案修正、公開UI整理を継承し、part markerのない単一GLBに安全なUV seam閉立体化を追加します。canonical palette state ID、manual paint、3MF recipeは変更しません。project bundleはGLB sourceを保持できるv2で、v1 OBJ bundleも引き続き読み込めます。

### 自動フィラメント提案の色域修正

自動提案だけは、選択素材内の実在製品を黒・白・灰・彩色・肌／茶の基準へ対応付けた色域バランス済みpoolから選びます。拡張DB全体をモデルの平均色に近い順で先に絞り、類似色4本へ収束する経路は使いません。多色／gradient／color-changing製品は自動poolから除外しますが、手動libraryからは削除しません。PLA、ABS、PETGのpoolは分離し、別素材をfallbackに使いません。

代表的な赤・黒・灰・茶モデルを用いたsoftware-fit診断では、面積加重`ΔE76 <= 12` coverageが修正前28.63%から修正後98.37%へ改善しました。これはcatalog色とmodel色の近似評価で、spool lot、光学特性、造形条件を含む実機印刷色の保証ではありません。

### Camera changeとAirbrush feedback

Airbrushの確定待ちguideは、確定色そのものではなくscreen-spaceの操作feedbackです。zoom、pan、orbit、programmatic camera changeのいずれかでview mappingが変わった場合、旧2D座標を再描画すると3D上の塗り位置とは無関係な軌跡になります。

r30でもcamera signatureとmappingをfeedback生成時に記録し、現在のviewと一致しないfeedbackを即時抑止します。抑止は表示だけに作用し、受付済みcommit token、exact-frame待ち、1 stroke = 1 Undoのtransactionを破棄しません。確定色は新しいcameraで通常の3D描画へ反映します。

### Accumulated manual-paint performance

- paint batchはcandidate rootに限定したeffective-state取得を使います。
- 検証済みgeometry配列をbatch間で再利用します。
- 互換性を確認できる9層Airbrushはadaptive treeを1回traversalします。
- 旧形式、非同心、または前提外のlayer geometryは、結果が確立している逐次pathへfail-safeでfallbackします。

optimized pathと逐次pathについて、encoded output、changed roots、override、adaptive tree、Undo／Redoの一致を回帰testで確認しています。公開機能のcircular soft falloff、time build-up、visible-face／selected-part guardとpalette state semanticsは変更しません。

### Decal betaの非公開化

デカールの読込、strict SVG preflight、投影、焼き付け、tree-aware Undoの実装とtestは、将来の再検証用にsourceへ保持します。依存関係のlicense／SBOM契約も削除しません。

一方、現在の公開Manual Editingからは「デカール β」を完全に非表示とします。ribbon tab、button、menu、画像open callback、shortcutのどれも生成／bindingされず、利用者が実装を起動する公開経路はありません。

旧projectは引き続き読み込みます。過去のbuildで焼き付けた色は通常のmanual paintとして保持されます。source PNG／SVGと編集可能decal layerは従来からproject dataではありません。

### GLB input beta

r30は、Hi3D AI等から出力されるstatic GLB／glTF 2.0 meshを直接読み込みます。scene／node transform、node instance、複数part、indexed／non-indexed triangle、triangle strip／fan、strided／normalized／sparse accessor、`COLOR_0`、materialのbaseColor factorと埋込baseColor textureを扱います。baseColor textureはsRGBをlinearへ戻してからfilterし、焼き付けた頂点色を既存の16／24／32色変換へ渡します。

外部URI、animation、skin、morph target、Draco／meshopt／BasisU圧縮、GPU instancing、壊れたchunk／accessor／image、非有限transformはfail-closedで拒否します。PBRのmetallic-roughness／normal等は色入力に使わず、未decodeのままwarningを表示します。custom importerはPython標準library、NumPy、Pillowだけを使い、PyInstallerのin-memory GLB self-testでも埋込texture decodeを検証します。

これはβのvertex bakeです。UV textureの細部を面内textureとして保持する機能ではなく、各頂点でsampleした色を補間するため、細いmarkや急な色境界は失われる場合があります。面数削減を行うとその傾向は強くなります。alpha blend／mask、PBR lighting、animation、skin、morph、compressed GLBは対象外です。

利用者所有の約200万面Hi3D系GLB 2件で、1 partと7 parts、8192px baseColor texture、part名保持、未使用PBR mapのlazy skip、prepare／previewまでread-only確認しました。これらの非公開assetはcopy、hash記録、manifest、配布物へ含めていません。

### 単一GLBのUV seam閉立体化

「閉立体化」を明示実行した単一GLBで、同一座標の境界edgeがexact 1:1かつ逆向きに対応するときだけ、UV／texture seamとして頂点を統合します。このproofはcleanup／QEM面数削減より前に行い、face追加・削除・順番変更とpart ID変更を禁止します。したがってordered faceに紐付くmanual paintとadaptive treeをexact carryできます。

これは穴埋めではなく、蓋を追加しません。未対応、同方向、複数候補、非manifold化、退化、本当の穴はfail-closedで停止し、GUIは処理前のgeometryを維持します。3MF strict topology検証はbuild item直下だけでなく全`type=model` resourceを対象とします。必須のsolid check後にQEM由来の上限内の微小自己交差だけが残る場合はwarningとし、Snapmaker Orcaでprojectとして開いたslice preview確認を出力guideへ含めます。

## 3. 継続する公開契約

- latest published r32.2 public version: `0.8beta`（現在の未公開開発sourceは`0.9`）
- published r32.2 project schema: `obj-adjuster.project.v12`
- experimental test workstream project schema: `obj-adjuster.project.v13`（v12は旧来のFull Spectrum modeとして読込。v11以前で素材指定がないprojectはPLAとして読込）
- portable bundle v2: `source.obj`または`source.glb`、`project.json`、`prepared_geometry.npz`、optional reference image（v1 OBJ bundleも読込可）
- palette canonical state IDs: 不変
- physical tools: F1～F4
- mixed-state表示番号: UI／chart専用のpresentation mapping
- legacy JSON: explicit source model選択を伴うOBJ互換経路
- material contract: PLA既定。ABS／PETGはβで、1つのFull Spectrum jobは同一素材4本のみ
- public Manual Editing: デカール βの入口なし、実装はsourceに保持
- public Filament Settings: 「基本4色を初期値へ戻す」の入口なし

メイン画面、mixed palette、calibration chart、全体共通palette count、実機黒補正、公開機能の境界、Manual Editingのtool配置はCreator Studio r26の公開契約を継続します。

## 4. r32.1公開済み検証とr32 previous evidence

`v0.8beta-r32.1`はInnovation Fund向けWindows prereleaseとして公開済みです。release tagは検証済みsourceと配布assetをcommit `b575b93d973ed67e7ada986469b10b4490eef4e5`へ固定し、後続のdocumentation-onlyな`main`更新はtagまたはrelease assetのbytesを変更しません。

- focused release test: 113 PASS／0 FAIL
- full regression: Python `3.13.14`、全1,277件、1,274 PASS／3 optional SKIP／0 FAIL（234.260秒）
- clean Windows build、packaged self-test、隔離profileの日英UI smoke: PASS
- 独立fresh extractでのself-test、日英UI smoke、DemoData manifest／hash: PASS
- fail-closed compliance inventory: 1,455 files（native 256 files）でPASS
- Windows package: 234,650,536 bytes、1,518 files、SHA-256 `1215CF77D8C8CB8AA5CE91DC7C84AE13404F3AA46221321807AD2E8A19F9064A`
- Windows package manifest SHA-256: `9E9DEFF9B36FE2DCFE9767B19CBF445ACAD6153A213D4B0D36C89E4CDBB3D23C`
- executable: 14,018,519 bytes、SHA-256 `E7392BF7C9EF627420459802642B6211B93DC454AEC6127C67F2FD3F45719E63`
- 完全対応ソース: 1,365,864,778 bytes、`release-approved`、known gapsなし、SHA-256 `D5A64F3022265BCE7C5C2DFA0358DFC2C94EEA541A5A4AC5671CE3BA829BE4CC`
- SBOM SHA-256: `D825C318E1387CDDA18AF25D4611E8B81CE1C8DAAA9AB6C180C420BEBF7CF1A0`
- binary component map SHA-256: `EB5053860139E3AA0E78B4D6857728A8B6D05DB747D70C30AC7EBD1A7A2DCB2C`
- workflow video SHA-256: `F55F9505EC7385D27A933799F9EEFD1C2499A77B86B0BB1162832320E88FEE61`
- detached `SHA256SUMS-r32.1.txt` SHA-256: `B8D76A07C30568F9E42002B67BFE4DAA5F4339B0A2224C529C85984FF7B1E640`
- 公開後、全6 Release assetを未認証で独立downloadし、sizeとSHA-256がすべて一致
- exact tagged完全対応ソースのsource publication eligibility: **true**
- exact tagged Windows assetのbinary publication eligibility: **true**

physical XP-PEN validationとphysical printはpendingの既知制約ですが、上記exact prereleaseの公開blockerではありません。分割model閉立体化も、同梱demoの成功だけを一般化せず、入力によって失敗し得る0.8beta制約として継続開示します。

公開済みr32のexact final build logはPython `3.13.14`で`Ran 1270 tests in 236.319s: OK (skipped=3)`、1267 PASS／3 optional SKIP／0 FAILを記録し、clean build、packaged self-test、日英UI smokeもPASSしました。controlled PyTetWild run `20260823-174626-089357844d4b`、application lock、release-approved static-closure contractも採用済みです。これらと、以前の1048-test結果、`C:\OBJAdjR32CM3`のbuild証拠、SHA-256 `8BBABEACCF9B47AC2750C86B7C38966E46F00A624C648036D600C9601CF86EBB`のEXEはr32系の**previous evidence**であり、r32.1 binaryを検証しません。

採用前のr32 public-source stageは395 files／394 manifest recordsで、manifest全SHA、privacy、独立path／SHA-256 parityがPASSしました。以前のsoftware stage 1,404 files／1,403 manifest recordsとfresh software self-test／日英UI smokeも**previous evidence**です。これらは上記のexact r32.1 build、stage、fresh extract、detached checksum、Git-tree parity、GitHub prerelease公開を置き換える証拠ではありません。

以下のr31結果は公開済みrevisionだけに適用する**previous evidence**であり、r32.1を検証しません。

Creator Studio r30には次のsoftware evidenceがあります。ChromaMatter r31、公開済みr32、および現在のr32.1 exact sourceには流用しない**previous evidence**です。

- Python `3.13.14` full regression: `Ran 1019 tests in 86.932s: OK (skipped=1)`、1018 PASS／1 optional SKIP
- `C:\OBJAdjR30FIX1`、PyInstaller `6.20.0` clean one-folder build: PASS
- packaged `--self-test`、isolated Japanese UI smoke／English UI smoke: PASS
- r30 public source 225 files／224 manifest records、software 1,404 files／1,403 manifest records、fresh extract、archive／privacy、Downloads配置、detached `SHA256SUMS-r30.txt`契約: PASS

ChromaMatter r31 exact sourceの**previous evidence**は、Python `3.13.14`で`Ran 1024 tests in 100.656s: OK (skipped=1)`、1023 PASS／1 optional SKIPです。`BUILD_AND_TEST.ps1 -RuntimeRoot .\.venv -Build -BuildOutputRoot C:\OBJAdjR31CM1`はexit 0で、PyInstaller `6.20.0` clean one-folder build、built package self-test、隔離profileの日英UI smokeもPASSしました。preflight `C:\OBJAdjR31CM1\dist\ChromaMatter\ChromaMatter.exe`は13,986,866 bytes、FileVersion／ProductVersion `0.8beta`、InternalName `ChromaMatter`、OriginalFilename `ChromaMatter.exe`、ProductName `ChromaMatter — AI Model Print Studio`、SHA-256 `208167A225A37BAAAA473B574B2F746E46427FD0CA63FC5B7201BF3394243743`です。

r31 preflight public sourceは227 files（manifest含む）／226 manifest recordsで、fresh archiveとの内容一致とprivacy監査を含めtechnical source GOでした。softwareは1,404 files（manifest含む）／1,403 manifest recordsでtechnical GO、fresh extractのself-test／Japanese UI smoke／English UI smokeはいずれもexit 0でした。preflight ZIPのhashとsizeは自己参照を避けるためcanonical文書へ埋め込みません。

次はCreator Studio r27だけに適用する**previous evidence**です。

- Python `3.13.14` full regression: `Ran 890 tests in 68.257s: OK (skipped=1)`、889 PASS／1 optional SKIP
- PyInstaller `6.20` clean one-folder build: PASS
- built packageとfresh extract双方のself-test／Japanese UI smoke／English UI smoke: PASS
- preflight EXE: 13,683,090 bytes、version `0.8beta`、SHA-256 `F2AB0AF025430FF3D5587D6C7B2A68365B8C091A7775697A24DDB84DF34EF056`
- public-source stage: 204 files total／203 manifest records
- software stage: 1,340 files total／1,339 manifest records
- source／software ZIP、manifest equality、path safety、CRC、privacy: PASS

この証拠はr27 artifactだけに適用し、r32.1 source、binary、package、checksumの検証には流用しません。preflight ZIP hashはcanonical文書へ埋め込みません。

r32以前のregression／build／artifact evidenceはr32.1 sourceへ流用しません。公開済みr32 Releaseはtag `v0.8beta-r32`、commit `86e34b2a9468f81768ee134a680a792b1a83df05`に固定されたprevious evidenceです。project ownerは2026-08-20にr31公開GOを出し、icon publication rightsはcreator declarationによりpass、当該asset scopeのlegal gateはowner acceptanceとして完了しました。これは独立した法務clearanceではありません。最終r31 source-only stage `ChromaMatter_0.8beta-r31-source-public-20260820`は227 files／226 manifest recordsで、folder／archive parity、CRC、privacy、staged identity／icon／tooling 32 testsを全て通過しました。Downloads配置と外部detached `SHA256SUMS-r31.txt`の照合もr31 source-only distributionについて完了しています。repositoryはpublic owner handle `Ponkichi0718`により[https://github.com/Ponkichi0718/ChromaMatter](https://github.com/Ponkichi0718/ChromaMatter)で公開されています。現在の`binary_publication_eligible=true`は、上記exact tagged r32.1 Windows assetだけに適用します。

## 5. Previous evidence

公開済みChromaMatter r32、r31およびCreator Studio r30、r29、r28、r27の上記結果は**previous evidence only**であり、ChromaMatter r32.1のsource、binary、package、checksumを検証しません。r32.1にはsection 4のexact tagged release evidenceだけを適用します。

Creator Studio r26のsource regression、clean build、packaged self-test、日英UI smoke、stage、fresh-extract、privacy、archive、detached-checksum監査もr26 artifactだけのprevious evidenceです。

Creator Studio r25、Surface Paint r24、それ以前の結果も各revisionだけに限定した履歴です。

## 6. 外部設計資料

描画UIの設計検討では、公式資料の[Blender Stroke](https://docs.blender.org/manual/en/4.5/sculpt_paint/brush/stroke.html)、[Blender Texture Paint](https://docs.blender.org/manual/en/4.2/sculpt_paint/texture_paint/tools.html)、[ZBrush Polypaint](https://help.maxon.net/zbr/en-us/Content/html/user-guide/3d-modeling/painting-your-model/polypaint/polypaint.html)、[ZBrush Lazy Mouse](https://help.maxon.net/zbr/en-us/Content/html/reference-guide/stroke/lazy-mouse/lazy-mouse.html)、[Substance 3D Painter Paint brush](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/paint-tools/paint-brush)と[Polygon Fill](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/paint-tools/polygon-fill)を参照しました。

r30は離散印刷stateと互換なsoft falloff、time build-up、visible-face／part guard、sample、smudge、fillを継続します。非破壊paint layer、clone、symmetry、stencil、generated cavity／AO／curvature maskは現行機能ではありません。

## 7. 配布・プライバシー

公開sourceと配布候補には、非公開の検証OBJ／GLB／textureその他のassetや識別可能な詳細を含めません。公開文書には一般化した機能契約と、再現可能なpublic-source testだけを記録します。

r32.1配布checksum `SHA256SUMS-r32.1.txt`はほかの5 assetと同時に公開済みで、全6 assetの未認証再downloadによるsize／SHA-256照合にPASSしています。完成済みの`SHA256SUMS-r32.txt`と`SHA256SUMS-r31.txt`はprevious evidenceだけに適用します。canonical文書へfinal ZIPの自己参照hashは埋め込みません。
