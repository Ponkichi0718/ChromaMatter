# ChromaMatter — Snapmaker U1 Innovation Fund 応募準備状況

更新日: 2026-08-23
対象: `ChromaMatter — AI Model Print Studio 0.8beta` r32 candidate（以下「r32候補」）。r32は、3MF出力時の安全な自動閉立体化、手動変更したF1～F4を`現在の4色をプレビュー・3MFへ反映`で明示適用する経路、安定したFull Spectrum layer-cycle／prime-tower baselineを追加します。public version `0.8beta`、schema、アイコン、既存設定互換性は維持します。採用後r32 exact sourceはPython 3.13.14で1,244 tests中1,242 PASS／2 optional SKIP／0 FAILです。現行sourceからのclean build、packaged smoke、source/software stage、checksum、GitHub updateはpendingで、EXE path／size／hashを推測しません。r31 source-only repositoryはowner handle `Ponkichi0718`により[GitHub](https://github.com/Ponkichi0718/ChromaMatter)で公開済みですが、r31の実測値はr32へ流用しないprevious evidenceです。全身一体の公開sampleがU1で48時間、prime tower込み約220 gで完走した観測はnoteで公開済みですが、exact r32 release、sample／3MF hash、4本のfilament、Orca版、U1 profileへ紐づくrelease-bound再現性証拠はpendingです。binary publication eligibilityは最終binary gate完了までfalse、Innovation Fund submission readyも権利処理、release同一性、cover／video／community postの全gateが揃うまでfalseです。

## 結論

**r31 source-only repositoryとU1実機の公開観測は存在するが、r32更新はrelease gate完了までpending。Innovation Fundへの提出は、権利、exact revision／hash、Orca／U1条件、公開assetを一組にしたrelease-bound demoが揃うまで未readyとする。EXEは第三者binary再配布監査まで公開しない。**

ChromaMatterは、Full Spectrumそのものを作り直すのではなく、**AI生成された頂点カラーOBJまたはUV baseColor付きGLBを、色・パーツ・陰影を生かしたSnapmaker Orca用Full Spectrum 3MFへ持ち込む前処理と修正の空白**を埋める。Hi3D AI等から出力された条件適合の静的分割GLBへはβ対応するが、ChromaMatterは独立・非公式・非提携であり、Hi3Dから出力されるすべてのfileとの互換性を保証しない。これはU1に明確に結び付いた実用課題であり、Innovation Fundの「Innovation & Technical Depth」「Openness & Quality」「Practicality & Adaptability」の三軸と合う。

一方、公式応募一覧には、GLB/OBJ、手持ち色、dither、mesh repairを扱う`ditherforge`など近い領域の応募が既にある。単に「OBJを多色3MFへ変換するソフト」と説明すると埋もれる。勝ち筋は、次の一文へ絞ることにある。

> TripoAI等の頂点カラーOBJと、Hi3D AI等から出力された条件適合の静的分割GLBへのβ対応（独立・非公式・非提携。すべての出力との互換性は保証しない）を、4本の実フィラメントとFull Spectrumの離散混色へ対応付け、元の陰影を見ながら3Dで手直しし、パーツ構成と色recipeを保ったSnapmaker Orca用3MFへ渡す、ローカル完結型AI Model Print Studio。

## 公式日程と応募条件

[Snapmaker U1 Innovation Fund公式ページ](https://www.snapmaker.com/en-US/innovation-fund)の2026-08-19確認時点では、Phase 1は**2026-09-07締切**、評価終了は09-22、結果発表は09-30。Phase 2は10-01から12-31までである。応募前に、公開GitHubまたは一般公開ページを用意し、Snapmaker communityで共有してからフォームへ送る流れが示されている。

- 審査: 技術委員会80%、community vote 20%
- 中核評価軸: Innovation & Technical Depth、Openness & Quality、Practicality & Adaptability
- フォーム: 名前、メール、project名、公開URL、category、short description、任意のcover image
- cover image推奨: 640×360 px、16:9、PNG/JPG、最大5 MB
- U1所有は必須ではないが、公式FAQは実機debugを強く推奨
- 受賞後もIPは応募者に残り、追加協業は個別交渉と説明されている

注意: 公式ページにはlocale／表示世代による文言差がある。現行en-US版は「open sourceを好むがclosed sourceも可」とする一方、en-GB版にはopen-source確認文とclosed-source可のFAQが同居している。ChromaMatterはGPL公開を前提にできるため、争点を作らず**source-firstのopen-source応募**とし、送信日に表示された応募文とFAQをPDFまたはスクリーンショットで保存する。

## ビジョンと解決する利用者課題

### ビジョン

モデリングや筆塗りに習熟していない利用者でも、画像生成→TripoAI等の3D生成、またはHi3D AI等から出力された条件適合の静的分割GLBへのβ対応→ChromaMatter→Snapmaker Orca→U1という流れで、4本のフィラメントから「無塗装でも陰影と中間色を感じる造形物」を作れる状態を目指す。Hi3D対応は独立・非公式・非提携であり、すべての出力を保証しない。

### 現在の痛点

- 頂点カラーOBJをOrcaへ直接入れても、元の色領域をFull Spectrumの混色recipeとして利用できない。
- Hi3D AI等がGLBまたはOBJ＋UV textureを出力する場合があるが、UV textureをFull Spectrumの離散色へ安全に焼き付けて編集・復元する入口が不足している。ChromaMatterのHi3D対応は条件適合の静的分割GLBに限る独立・非公式・非提携のβ機能で、すべてのHi3D出力との互換性は保証しない。
- AI生成meshは複数パーツ、開口、非manifold、表面meshなどを含みやすく、slicer修復で色や形が失われる場合がある。
- 4本の実フィラメントは画面上のRGBと同じ発色をせず、とくに黒や高隠蔽色は理論比率より強く見える。
- 自動変換だけでは顔、陰影境界、細部に修正が必要だが、高面数meshの手塗りは重くなりやすい。
- 色、パーツ、手修正、3MF recipeを保ったまま試行錯誤を保存・再開する手段が必要である。

## 現在の解決策

公開workflowとして確認できる範囲は次のとおり。

- `v x y z r g b`形式の頂点カラーOBJを読み込み、ローカルWindows上で処理する。
- 静的GLBのscene transform、mesh-node part、`COLOR_0`、baseColor factor／textureを読み、sRGBを線形空間で補間・合成して既存の頂点色pipelineへ焼き付ける。PBR lighting mapやanimation等は推測せず明示的に対象外とする。
- F1～F4の基本フィラメント、パーツ別palette、16／24／32色の離散混色stateへ対応付ける。
- PLAを既定素材とし、ABS／PETGは同一素材4本だけで構成するβモードとして扱う。異素材partは統合3MFへ混在させず、素材別の個別3MFとして出力できる。
- フィラメントライブラリはPLA 2,577色、ABS 268色、PETG 652色を収録する。ABS／PETGで4色不足または近似誤差が大きい場合はPLAで補わず、色域不足を明示する。
- 基本色の自動提案、手持ちフィラメント情報、混色palette、実機黒補正、比較用calibration chartを一つのworkflowにまとめる。
- 自動提案は選択素材内の実在製品を色域バランス済み基準へ対応付けてから4本を選ぶ。多色／gradient糸は手動libraryへ残し、自動提案だけから外す。代表的な赤・黒・灰・茶modelのsoftware-fit coverage（面積加重`ΔE76 <= 12`）は28.63%から98.37%へ改善したが、印刷色の保証ではない。
- mixed paletteをF1+F2、F1+F3…のfamily-major順で示し、比較チャートも同じ表示順・表示番号へ統一する。内部canonical state IDと3MF recipeは変更しない。
- Brush、Fill、Smudge、Eyedropper、soft Airbrush、part／visible-face guard、Undo／Redoを備えた3D Manual Editingを行う。
- 開いたmeshもfail-softで表示・手修正し、必要時に「閉立体化」を明示実行する。単一GLBでは、同一点の境界edgeが逆向きにexact 1:1対応するUV seamだけをcleanup／QEMより前に統合し、面や蓋を追加しない。本当の穴、曖昧な境界、非manifold結果はfail-closedで停止する。
- 3MFのstrict topology検証は全`type=model` resourceを対象にする。必須検証後の上限内の微小QEM自己交差だけはwarningとし、Snapmaker Orcaでprojectとして開いたslice preview確認を要求する。manual paintとadaptive treeはordered faceへexact carryする。
- 全体3MFとパーツ別3MFで、F1～F4、パーツ、canonical palette stateを保持する。
- `source.obj`または`source.glb`、`project.json`、`prepared_geometry.npz`、任意の参照画像からなるportable project folder v2で、検証済みgeometryと手修正を復元する。旧OBJ bundle v1は引き続き読める。
- OBJ、GLB、画像、project、3MFをproject運営サーバーへ意図的にuploadしないローカル処理である。

研究用のデカール、分割、ジョイント、ColorDepth、Radial、黒内壁化等はsourceに残るが、現在の公開UIからは到達できない。「基本4色を初期値へ戻す」も公開しない。応募では「搭載済み機能」として数を増やさず、今使える公開workflowへ集中する。

## 現時点の実証

### Software evidence

[CURRENT_STATE.json](../CURRENT_STATE.json)と[PROVENANCE.md](../PROVENANCE.md)が現在の正本である。

- Creator Studio r29 **previous evidence**: Python 3.13.14で`Ran 998 tests in 83.529s ... OK (skipped=1)`、997 PASS／任意1 SKIP
- r29 previous evidence: `C:\OBJAdjR29FIX1`、PyInstaller 6.20.0 clean build、packaged `--self-test`、隔離profileの日英UI smokeはPASS。stage以降は未完了
- Creator Studio r28 previous evidence: Python 3.13.14で`Ran 992 tests in 87.406s ... OK (skipped=1)`、991 PASS／任意1 SKIP、clean build／package／archive監査はPASS
- Creator Studio r30 **previous evidence**: Python 3.13.14、`Ran 1019 tests in 86.932s: OK (skipped=1)`、1018 PASS／任意1 SKIP。`C:\OBJAdjR30FIX1`でのPyInstaller `6.20.0` clean build、package／stage／archive／privacy／detached `SHA256SUMS-r30.txt`契約: PASS。r32へは適用しない
- ChromaMatter r31 exact source **previous evidence**: Python 3.13.14、`Ran 1024 tests in 100.656s: OK (skipped=1)`、1023 PASS／任意1 SKIP。`C:\OBJAdjR31CM1`でのPyInstaller `6.20.0` clean build、built package self-test、1920×1080の隔離profile日英UI smoke: PASS。preflight `ChromaMatter.exe`は13,986,866 bytes、SHA-256 `208167A225A37BAAAA473B574B2F746E46427FD0CA63FC5B7201BF3394243743`
- r31 final source-only stage **previous evidence** `ChromaMatter_0.8beta-r31-source-public-20260820`: 227 files／226 manifest records、folder／archive parity、CRC、privacy、staged identity／icon／tooling 32 tests、Downloads配置、外部detached `SHA256SUMS-r31.txt`照合: PASS
- r31 software preflight **previous evidence**: 1,404 files／1,403 manifest records、fresh-extracted self-test／日英UI smoke: exit 0。ただし第三者binary再配布監査未完了のため公開対象外
- ChromaMatter r32 candidate: 採用後exact source full regressionは1,244 tests中1,242 PASS／2 optional SKIP／0 FAIL。現行sourceからのclean build、packaged smoke、1920×1080日英UI smoke、final stage／archive／privacy／identity、Downloads配置、外部detached `SHA256SUMS-r32.txt`、GitHub updateはpending。1280×720は対応対象外の既知制約
- 非公開の大規模GLBはread-only検証だけに使い、実modelをcopy、hash記録、manifest登録、配布しない

r31以前のevidenceはr32へ適用しない。r31のsource regression／clean build／built package smoke／final source-only stage／archive／privacy／identityとpublication decisionはprevious evidenceで、公開先は[https://github.com/Ponkichi0718/ChromaMatter](https://github.com/Ponkichi0718/ChromaMatter)、owner handleは`Ponkichi0718`である。変更していないiconのcreator-declarationだけはasset provenanceとして保持する。r32のsource regressionはcurrent PASSだが、release state、source publication eligibility、checksum、GitHub updateはpendingである。binary publication eligibilityとInnovation Fund submission readyもfalseである。

### Development and physical evidence on note

開発の動機から失敗、原因追跡、再出力までを公開している点は強い。宣伝用の成功写真だけでなく、黒の隠蔽力、toolhead XYずれ、flow calibration、面数、混色数を実物で検証している。

- [最初の紹介: TripoAI頂点色→Full Spectrum、色保持修復、自動提案、手修正](https://note.com/ponkichi0718/n/nc786429d4804)
- [用途と機能の説明: 無塗装でも塗装したような造形を簡単に](https://note.com/ponkichi0718/n/nc7f466bf8078)
- [初回実出力: フードのgradientと顔の陰影を確認、黒の強さと積層を課題化](https://note.com/ponkichi0718/n/nea201d9ace37)
- [16→32色、面数増加、白・茶filament変更の比較](https://note.com/ponkichi0718/n/nd14cdfd8f937)
- [失敗記録: 黒混色の可視化、32色palette、手持ちfilament反映を追加](https://note.com/ponkichi0718/n/nb7e5c00d006f)
- [再出力: 黒補正、toolhead XY／flow calibrationで改善](https://note.com/ponkichi0718/n/n628186c33d88)
- [全身造形の完結報告: 材質感と色味、残る黒積層、接着面の課題](https://note.com/ponkichi0718/n/n36b89097dad8)
- [公開サンプルの生成と最終出力開始](https://note.com/ponkichi0718/n/nad23088e6f2d)
- [公開sampleの実機結果: 全身一体48時間／約220 g、残るsupport・台座・色境界、分割GLB対応](https://note.com/ponkichi0718/n/nf6c77165127c)

これは「実機に触れていない概念実証」ではない。全身一体sampleは48時間、prime tower込み約220 gで完走し、通常の鑑賞距離では意図したグラフィック調の陰影が形と奥行きとして読めた。一方、背面support跡、台座の緩さ、近接時の色境界を課題として隠さず記録している。ただし応募証拠としては、記事の写真と設定が同一revision、同一3MF、同一filament lotへ追跡できる形にまだ整理されていない。r32 exact releaseに紐づく公開デモとして同じ流れを一度通し直す必要がある。

## 類似応募との比較と差別化

公式ページには2026-08-19時点で41件が掲載され、うち3D Model Editor 6件、3MF Converter 2件とされている。

| 公式掲載project | 公式説明上の中心 | ChromaMatterが明確に示すべき違い |
|---|---|---|
| Full Spectrum（sponsored） | 4本をlayer交互配置して100+中間色を生成 | 競合ではなく土台。AI頂点色をFull Spectrum recipeへ準備・修正する上流toolとして敬意を明示 |
| ditherforge | 902 commits（2026-08-19確認）の成熟tool。GLB／3MF／STL／OBJ／COLLADA、複数object、inventory＋TD、palette選択、複数dither、透過simulation、repair、split／peg、sticker、swatch calibration、複数printer profile | 入出力形式、inventory、dither、repair、split、calibration自体を独自性としない。AI生成の高面数GLB／multipart頂点カラーOBJから、4本で作るSnapmaker Full Spectrumのcanonical virtual state、part別4色、同一3D上のmanual surface correction、実機黒補正、project／Orca recipeのportable restoreまでを一続きで実証 |
| orcaslicer-imagemap | 画像textureをmodel側面へmapping | 2D texture貼付ではなく、既存3D頂点色・陰影・part semanticsの保持と修正 |
| Kromacut | 2D画像からlayered color print、filament適応、3D preview | 2D relief生成ではなく、自由形状のmultipart vertex-color OBJを直接扱う |
| Surface Color Stitch（sponsored） | top surfaceを独立layer stackへ分解 | top surface effectではなく、figure全周のvertex colorをpart単位で変換・修正 |
| 3MF converters／Nozzle Buddy系 | slicer間の3MF変換と設定保持 | 既存3MF変換ではなく、AI OBJからFull Spectrum-ready 3MFを制作するauthoring段階 |
| OrcaSlicer FS UI rework | Orca内部のmixed-filament UI改善 | slicer UIではなく、Orcaへ入る前のmodel preparation、manual paint、part workflow |

競合に「ない」と断定するより、応募動画でChromaMatter固有のend-to-end contractを実演する。特にditherforgeは広い入力、filament TD、dither、repair、calibrationまで持つため、単純な機能表ではChromaMatterが優位とは言えない。最大の差別化は機能数ではなく、**4本の物理toolから生まれるFull Spectrumの離散mixed stateをauthoring単位として扱い、生成AIのmultipart頂点色をpart別に編集し、失敗と補正を同じrecipeでU1実機まで追跡すること**である。

## 勝ち筋／負け筋

### 勝ち筋

1. 完成写真を先に見せ、「無塗装・4本・0.08 mm・Full Spectrum」と短く提示する。
2. 元画像→Tripo頂点カラーOBJ→自動palette→Manual Editing→比較chart→Orca layer preview→U1完成品を90秒程度で一本につなぐ。
3. 黒で失敗した試作と、可視化・calibration・実機黒補正で改善した試作を並べる。失敗から生まれた機能は技術的説得力になる。
4. GitHubで合成sample、setup、test、architecture、known limitationsを再現可能にする。
5. `Full Spectrumを置き換える`ではなく、`Full SpectrumをAI model creatorが使える入口へ広げる`と表現する。

### 現実的なtier見込み

以下は公式判定ではなく、現状の公開証拠と競合成熟度からの内部評価である。

| tier | 見込み | 必要な追加証拠 |
|---|---|---|
| Active Builder | **十分狙える** | public GitHub、r32 exact gate、権利処理済みsample、Orca reopen／slice、U1完走動画、正直なknown limitations |
| Eco-Enhancer | **証拠次第で可能** | 同一sample／hashで失敗→calibration→改善を追跡し、clean clone再現と少なくとも1件の第三者再現を加える |
| U1 Pioneer | **現状では難しい** | ditherforge等より機能数を増やすだけでは不十分。Full Spectrum canonical state authoringの公開仕様、定量色評価、複数model／filament、第三者が再利用できるformatまたはAPIが必要 |

### 負け筋

- 「AIで全部作った多機能converter」とだけ説明し、技術的contractと人間による検証責任が見えない。
- ditherforge等との違いが`Tripo専用`だけに見える。
- 画面操作の長い動画で、完成品とU1での価値が後半まで出ない。
- r32と異なる旧画面、番号の不一致、未校正の黒をcover画像に使う。
- 第三者characterであるオルランドゥを応募の主cover／配布sampleにする。
- 現在出力中のsampleが既存robot作品を連想させる状態のまま、由来・prompt・Tripo plan・再配布権を確認せず公開する。
- EXE license監査が未完了なのにbinaryを先に配る。

## 公開実機sampleの使い方

完成写真と動画は公開済みの観測記録として使用できる。ただしInnovation Fundの主coverとrelease-bound demoへ使うのは、次の条件を満たす場合だけとする。

1. 正面・背面・左右・45度、同一照明・white balance・背景で撮影する。
2. 元2D、OBJ／GLB preview、ChromaMatter変換preview、Orca layer preview、完成品を同じ向きで並べる。
3. 使用したr32 commit／artifact hash、OBJ／GLB hash、3MF hash、Orca版、U1 profile、4本の製品名・lot、0.08 mm、壁・infill・support、造形時間、filament change回数を記録する。
4. 近接写真でgradient、陰影、黒境界、積層痕、part seamを隠さず示す。
5. 2D生成・色変更・3D生成に使ったservice、plan、日付、正確なprompt、seed、入力画像の権利、再配布条件、必要なattributionを権利台帳へ残す。
6. 記事内で既存robot作品への強い着想を述べているため、既存character、logo、固有silhouetteへの類似を人間が確認する。判断が曖昧なら、応募coverにはより抽象的で完全オリジナルな別sampleを使い、このsampleは非配布の開発記録に留める。

完成写真単独より、**失敗版／改善版／最終版の三体比較**が強い。黒補正とcalibrationの必要性が一枚で伝わるためである。

## 審査軸別の提出戦略

| 審査軸 | 現在の強み | 応募直前に足す証拠 |
|---|---|---|
| Innovation & Technical Depth | 頂点色／UV baseColor GLB→canonical Full Spectrum state、part palette、3D manual correction、色保持3MF、adaptive paint性能、安全なUV seam閉立体化、実機黒補正 | r32 architecture図、GLB texture bake／1:1 seam proof／strict type=model検証とpalette／chart順序test、自動提案の素材分離／色域回帰test、実入力から3MFまでのstate追跡例、処理時間・memory計測 |
| Openness & Quality | GPL source方針、public GitHub、fail-closed seam契約、採用後r32 exact source regression PASS、r31の公開済みprevious evidence | r32 clean build／package smoke／日英UI smoke／final stage／archive／privacy／identity、CI結果、signed provenance、SBOM方針、issue template |
| Practicality & Adaptability | noteに実際の失敗、再出力、U1 calibration、完成全身造形がある | 公開sampleでOrca open→slice→save→reopen→U1 printを一続きに記録。4色／16・24・32色とpart output matrix |
| Community 20% | 継続的なnote記事と制作物がある | GitHub README、英語字幕付き短編、Snapmaker Forum投稿を同日に公開し、質問・再現報告を受け付ける |

## 未解決リスク

- r31のsource regression／clean build／built package smokeとfinal source-only stage／archive／privacy／identity、owner publication decision、public GitHubと公開URLからのclone／32 testsはprevious evidenceとしてGO。r32 exact source regressionはPASSしたが、clean build以降のrelease gate、CI、第三者binary再配布監査、権利処理済みsample一式の公開は未完了。
- ABS／PETG混色はβであり、素材別ライブラリと3MF profileの整合までは検証しているが、U1実機での同素材4本による色再現matrixは未完了。ABSは色数・色域が狭く、Top Coverを含む造形条件も別途検証が必要である。
- 実機黒補正とcalibration chartを、複数black／white、16／24／32色で定量比較したmatrixがない。
- 大規模OBJ／GLBの読込、準備、閉立体化は時間とmemoryを要し、200万面級のManual Editingはβ境界である。
- GLBのUV色はmesh頂点へsampleして焼き付けるため、面より細かいtexture detailは失われ、面数削減で差が広がる場合がある。baseColor以外のnormal／metallic／roughness／透明度、animation、skin、morph、Draco等は再現しない。
- 非manifold meshはfail-softで扱えるが、任意modelの自動修復・印刷可能性を保証しない。
- TripoAI以外の頂点カラーOBJに対する実機validationが薄い。応募では入力契約を狭く正確に書く。
- physical XP-PEN操作と、r32 exact buildのU1一貫試験が未完了。
- UIを簡素化した一方、初見利用者が4色選択、混色state、part palette、black correctionを理解できるonboarding evidenceがない。
- project ownerによるr31 sourceの公開承認は記録済み。r32 source更新の公開判断はpending。公開handle `Ponkichi0718`とrepository URLは反映済みで、公開連絡先のGitHub metadata反映は未完了。

## IP・ライセンス・プライバシー

- application code: `GPL-3.0-or-later`
- TetGen core: `AGPL-3.0-or-later`または別途商用license
- PyMeshLab: GPL-3.0、PyTetWild/fTetWild: MPL-2.0、Qt／GEOSその他にも個別条件あり
- 現在の方針: **source-onlyを先に公開し、EXEは最終binaryのSBOM、対応source、通知、Qt置換／再link条件等を監査するまで保留**
- 旧EXE、recovered PYC、由来不明asset、私有OBJ／画像／3MF／動画素材は公開treeへ含めない
- 公開sampleは合成OBJ、または権利gateを通した新規original modelだけにする
- local project／filament inventoryにはpathや製品snapshotが含まれ得るため、issue添付前に確認する
- OpenAI Codexを開発支援に使用したことを明示し、仕様、採否、test、公開責任は提案者が負う
- Snapmaker、Full Spectrum、TripoAI、Hi3D AI、OpenAIの公式・提携・承認製品ではないと明示する
- ChromaMatter iconは2026-08-20のcreator declarationにより公開承認済み。ロボットはオリジナルの架空機体、`ZENITH DYNAMICS CORP.`は創作文言と申告されている。basic exact-match web checkで完全一致は未確認だが、近似名`Zenith Dynamics`を使う実在組織が複数あるため、それらとの非提携を明示し、独立した商標／意匠clearanceを主張しない

詳細は[PUBLICATION_CHECKLIST_JA.md](PUBLICATION_CHECKLIST_JA.md)、[LEGAL_AND_RIGHTS_JA.md](LEGAL_AND_RIGHTS_JA.md)、[PRIVACY.md](../PRIVACY.md)を参照する。本項は法的助言ではない。

## 応募assetの推奨構成

1. **Public GitHub**: source、README日英、LICENSE、PROVENANCE、setup、合成sample、tests、known limitations
2. **640×360 cover**: 元2D／AI GLB・OBJ／U1完成品の3分割。文字は「4 Filaments / AI 3D Color / Full Spectrum 3MF」程度
3. **シンプルな使い方（約2分）**: [Release asset `ChromaMatter-simple-workflow-demo.mp4`](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32/ChromaMatter-simple-workflow-demo.mp4)。対応OBJ／GLB→サイズ・形状準備→Full Spectrum 3MF export／validation→Snapmaker Orcaでproject open／slice→U1 print。privacy確認済みの公開用copyは125.33秒、1920×1080、H.264、音声なし、37,708,741 bytes。Git treeへ入れず、最終Releaseで他assetと同時uploadする
4. **90秒hero video**: 完成品→入力→自動変換→1箇所手修正→chart→Orca→print。日英字幕
5. **3～5分technical demo**: part palette、16／24／32、黒補正、portable restore、per-part 3MF、Orca reopen
6. **一枚architecture図**: Vertex Color OBJ / UV baseColor GLB → palette fitting → canonical states → manual overrides → Snapmaker 3MF
7. **validation表**: version／commit、tests、sample hash、Orca版、U1条件、成功・既知問題
8. **community post**: noteまとめ＋Snapmaker Forum英語投稿＋GitHub issue導線

応募categoryは、現在の価値を最も表す`3D Model Editor`を第一候補、選択肢に無ければ`Software`とする。`3MF Converter`だけではManual Editing、part palette、calibrationの価値が伝わりにくい。

## GO／NO-GO基準

### Phase 1 GO

- [x] 2026-08-20、project ownerが公開GOを出し、icon creator declarationと非提携方針を記録した
- [x] paletteと比較chartが同じfamily-major順・同じ表示番号で、canonical ID／3MF recipe不変をtestした
- [x] r31 exact release identity／regression／GUI layoutを含むfull regression（1023 PASS＋任意1 SKIP）を完了した
- [x] r31 exact clean build、packaged self-test、1920×1080の日英UI smokeを完了した
- [x] r31 preflight source／software stage、fresh extract、manifest／privacy auditを完了した
- [x] r31 final source-only restage、Downloads配置、detached checksum、archive／CRC／privacy／identity契約を完了した
- [x] Public GitHubをclean cloneし、source公開範囲の32 testsを再実行した
- [x] r32採用後exact source full regression（1,242 PASS＋2 optional SKIP）を完了した
- [ ] r32現行sourceからのclean build、packaged self-test、1920×1080の日英UI smokeを完了した
- [ ] r32 final source／software stage、fresh extract、manifest／archive／privacy／identityを完了した
- [ ] r32 source-only artifactのDownloads配置と外部detached `SHA256SUMS-r32.txt`照合を完了した
- [ ] r32 source-only updateをGitHubへ反映し、公開treeとfinal stageの一致を確認した
- [ ] 権利処理済みpublic sample workflowを記載手順だけで再現した
- [x] project ownerによるr31 sourceの公開承認を記録した
- [ ] project ownerによるexact r32 source updateの公開判断を記録した
- [x] public repository URLとowner handle `Ponkichi0718`を確定した
- [ ] 公開連絡先、GPL／第三者通知のGitHub表示を確定した
- [ ] 応募sampleの権利記録と第三者IP確認を完了した
- [ ] 公開sampleでOrca open→slice→save→reopenを完走した
- [ ] 同じsampleをU1で完走し、完成写真、条件、失敗／制限を公開した
- [ ] `ChromaMatter-simple-workflow-demo.mp4`を最終Releaseへ同時uploadし、sign-in不要の公開URLとchecksumを確認した
- [ ] cover、short description、90秒video、forum postを公開URLから閲覧できる

### NO-GO／Phase 2へ送る条件

- 上の権利、provenance、privacy、source再現性のいずれかが未完了
- r32 exact 3MFがOrcaで再open／sliceできない、またはpalette／part semanticsが崩れる
- 公開sampleが既存IPに似ており、公開・再配布条件を説明できない
- 実機結果が応募の中心主張「陰影と中間色を無塗装で再現」を支持しない

内部freezeを2026-09-02、応募を09-04までに置けば、公式09-07締切前に修正余地を残せる。品質gateを満たせなければ無理にPhase 1へ出さず、10-01開始のPhase 2でcalibration matrixと公開再現報告を増やす。

## 忖度なしのready判定

| 項目 | 判定 |
|---|---|
| 問題設定とU1との関連 | 強い |
| prototypeの技術深度 | 強い |
| 実機で可能性を示した証拠 | あり。ただしrevision追跡を要整理 |
| 競合との差別化 | 可能。ただし応募文と動画で明文化必須 |
| source quality | r31以前はprevious evidence。r32採用後exact source full regressionは1,244 tests中1,242 PASS／2 optional SKIP。clean build、built package smoke、1920×1080日英UI smoke、final stage、archive／CRC／privacy／identity、Downloads配置、detached checksumはpending |
| public release／legal | r31は`source-published`、r32 updateはpending。公開先は[GitHub](https://github.com/Ponkichi0718/ChromaMatter)。変更していないicon asset scopeはcreator declarationでowner accepted。binaryは第三者再配布監査待ち |
| 応募asset | 作成途中 |

**現時点の総合判断は「r31 source-only repositoryは公開済み、r32 updateとInnovation Fund提出物はまだ未完成」。** 中位以上を狙える題材だが、top tierを争うには、機能数を増やすよりも、original public sampleによる再現可能な一貫実証、競合との一文差別化、public repository運用品質の三つが必要である。
