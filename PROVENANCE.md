# ChromaMatter — AI Model Print Studio 0.8beta (r32) provenance

更新日: 2026-08-21  
対象revision: `r32-ai-model-print-studio`

## 1. プロジェクトとidentity

ChromaMatter — AI Model Print Studioは、AI生成された頂点カラー付きOBJまたはUV baseColor texture付きGLBを、Snapmaker OrcaのFull Spectrum／Color Mixingワークフロー向け3MFへ変換・調整する独立プロジェクトです。Hi3D AI、TripoAI、Snapmaker、Blender、ZBrush、Substance 3D Painter、OpenAIまたは各社の公式・提携製品ではありません。

表示versionは利用者の指定どおり`0.8beta`、Windows数値versionは`0.8.0.0`に固定し、人向けeditionを`AI Model Print Studio r32`とします。

- public source: `ChromaMatter-0.8beta-r32-source-public-20260823`
- software package: `ChromaMatter-0.8beta-r32-win64`

## 2. r32出力workflowとr31 identity継承

r32は、閉立体化前の適格modelを3MF出力しようとした場合に、安全確認済みのpart境界またはGLB同一座標seamだけを閉立体化すると宣言し、成功後に同じ出力操作を再開します。本当の穴へ推測で蓋を追加せず、対応を証明できない境界、非manifold結果、または処理失敗は従来どおりfail-closedです。

基本F1～F4を利用者が個別変更した場合は、明示的な「現在の4色をプレビュー・3MFへ反映」操作で、既存のmanual paintをcanonical stateのまま再解釈してFull Spectrum previewと3MF paletteを更新します。model読込時の自動提案を既定とし、色変更だけでmanual paintやproject stateを破壊しません。

3MFにはSnapmaker Orca Full Spectrumの安定したlayer-cycleとprime-tower baselineを明示します。Local Z、advanced dithering、pointillism等の実験設定は有効化せず、supportはChromaMatterから強制しません。これは印刷品質の保証ではなく、Snapmaker Orcaでprojectとして開き、slice previewと実機条件を確認する前提です。

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

- public version: `0.8beta`
- project schema: `obj-adjuster.project.v12`（v11以前で素材指定がないprojectはPLAとして読込）
- portable bundle v2: `source.obj`または`source.glb`、`project.json`、`prepared_geometry.npz`、optional reference image（v1 OBJ bundleも読込可）
- palette canonical state IDs: 不変
- physical tools: F1～F4
- mixed-state表示番号: UI／chart専用のpresentation mapping
- legacy JSON: explicit source model選択を伴うOBJ互換経路
- material contract: PLA既定。ABS／PETGはβで、1つのFull Spectrum jobは同一素材4本のみ
- public Manual Editing: デカール βの入口なし、実装はsourceに保持
- public Filament Settings: 「基本4色を初期値へ戻す」の入口なし

メイン画面、mixed palette、calibration chart、全体共通palette count、実機黒補正、公開機能の境界、Manual Editingのtool配置はCreator Studio r26の公開契約を継続します。

## 4. r32検証状態

r32の採用後current exact-source full regressionはPython `3.13.14`で`Ran 1244 tests in 185.852s: OK (skipped=2)`、1242 PASS／2 optional SKIP／0 FAILです。controlled PyTetWild run `20260823-174626-089357844d4b`、application lock、release-approved static-closure contractも採用済みです。以前の1048-test結果、`C:\OBJAdjR32CM3`のPyInstaller build／packaged self-test／日英UI smoke、およびSHA-256 `8BBABEACCF9B47AC2750C86B7C38966E46F00A624C648036D600C9601CF86EBB`のEXEは、現在のcompliance／adoption変更より前の**previous evidence**であり、現行r32 binaryを検証しません。

採用前のr32 public-source stageは395 files／394 manifest recordsで、manifest全SHA、privacy、独立path／SHA-256 parityがPASSしました。採用によってsource bytesが変わったため、final corresponding-source stageは再生成が必要です。以前のsoftware stage 1,404 files／1,403 manifest recordsとfresh software self-test／日英UI smokeも**previous evidence**です。現行sourceからのclean build、final source／software stage、fresh extract、detached `SHA256SUMS-r32.txt`、Git-tree parity、GitHub更新は**pending**です。

以下のr31結果は公開済みrevisionだけに適用する**previous evidence**であり、r32を検証しません。

Creator Studio r30には次のsoftware evidenceがあります。ChromaMatter r31および現在のr32 exact sourceには流用しない**previous evidence**です。

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

この証拠はr27 artifactだけに適用し、r32 source、binary、package、checksumの検証には流用しません。preflight ZIP hashはcanonical文書へ埋め込みません。

r31以前のregression／build／artifact evidenceはr32 sourceへ流用しません。上記1244-test r32 source regressionだけが現行exact evidenceで、r32の旧build／smoke／stageはprevious evidenceです。project ownerは2026-08-20にr31公開GOを出し、icon publication rightsはcreator declarationによりpass、当該asset scopeのlegal gateはowner acceptanceとして完了しました。これは独立した法務clearanceではありません。最終r31 source-only stage `ChromaMatter_0.8beta-r31-source-public-20260820`は227 files／226 manifest recordsで、folder／archive parity、CRC、privacy、staged identity／icon／tooling 32 testsを全て通過しました。Downloads配置と外部detached `SHA256SUMS-r31.txt`の照合もr31 source-only distributionについて完了しています。source-only repositoryはpublic owner handle `Ponkichi0718`により[https://github.com/Ponkichi0718/ChromaMatter](https://github.com/Ponkichi0718/ChromaMatter)で公開されています。r32更新はまだ公開済みと主張しません。現行sourceからのclean buildと全package gateが完了するまで`binary_publication_eligible`はfalseです。

## 5. Previous evidence

ChromaMatter r31およびCreator Studio r30、r29、r28、r27の上記結果は**previous evidence only**であり、ChromaMatter r32のsource、binary、package、checksumを検証しません。

Creator Studio r26のsource regression、clean build、packaged self-test、日英UI smoke、stage、fresh-extract、privacy、archive、detached-checksum監査もr26 artifactだけのprevious evidenceです。

Creator Studio r25、Surface Paint r24、それ以前の結果も各revisionだけに限定した履歴です。

## 6. 外部設計資料

描画UIの設計検討では、公式資料の[Blender Stroke](https://docs.blender.org/manual/en/4.5/sculpt_paint/brush/stroke.html)、[Blender Texture Paint](https://docs.blender.org/manual/en/4.2/sculpt_paint/texture_paint/tools.html)、[ZBrush Polypaint](https://help.maxon.net/zbr/en-us/Content/html/user-guide/3d-modeling/painting-your-model/polypaint/polypaint.html)、[ZBrush Lazy Mouse](https://help.maxon.net/zbr/en-us/Content/html/reference-guide/stroke/lazy-mouse/lazy-mouse.html)、[Substance 3D Painter Paint brush](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/paint-tools/paint-brush)と[Polygon Fill](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/paint-tools/polygon-fill)を参照しました。

r30は離散印刷stateと互換なsoft falloff、time build-up、visible-face／part guard、sample、smudge、fillを継続します。非破壊paint layer、clone、symmetry、stencil、generated cavity／AO／curvature maskは現行機能ではありません。

## 7. 配布・プライバシー

公開sourceと配布候補には、非公開の検証OBJ／GLB／textureその他のassetや識別可能な詳細を含めません。公開文書には一般化した機能契約と、再現可能なpublic-source testだけを記録します。

r32配布checksum `SHA256SUMS-r32.txt`はfinal restage後に外部作成するため現在pendingです。完成済みの`SHA256SUMS-r31.txt`はr31 previous evidenceだけに適用します。canonical文書へfinal ZIPの自己参照hashは埋め込みません。
