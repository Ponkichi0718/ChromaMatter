# ChromaMatter — Innovation Fund応募原稿案

更新日: 2026-08-20  
状態: **`ChromaMatter_0.8beta-r31-source-public-20260820`のsource-only repositoryは[GitHub](https://github.com/Ponkichi0718/ChromaMatter)で公開済み。Innovation Fund submission readyはfalseで、応募文は未投稿・未提出。残る角括弧のplaceholderと応募sample実証値を置換するまで提出しない。EXE／software ZIPは第三者binary再配布監査まで公開しない。**  
対象: `ChromaMatter — AI Model Print Studio 0.8beta` r31候補

## 1. 応募の基本情報

### 推奨project名

**ChromaMatter — AI Model Print Studio**

- 製品名は`ChromaMatter`、taglineは`AI Model Print Studio`に統一する。
- short descriptionで「AI生成modelを何へ変えるtoolか」を一読で伝える。
- `Snapmaker`、`TripoAI`、`Hi3D AI`をproject名へ含めず、公式・提携製品との誤認を避ける。

### 推奨category

**3D Model Editor**

`3MF Converter`ではなく、入力modelのpart、palette、表面色を編集してから3MFを制作するため。応募formにこの選択肢がない場合のみ`Software`を選ぶ。

### 一文positioning

> A local authoring bridge from high-poly vertex-colour OBJ and textured GLB models to editable, reproducible Snapmaker Orca Full Spectrum projects.

> 高密度な頂点カラーOBJとUV baseColor付きGLBを、編集可能で再現可能なSnapmaker Orca Full Spectrum projectへつなぐローカル制作tool。

### 応募form用short description（EN・推奨稿）

> ChromaMatter turns high-poly vertex-colour OBJ and textured GLB models into Snapmaker Orca Full Spectrum 3MF projects. It maps each part to four physical filaments and 16/24/32 canonical mixed states, supports in-place 3D surface correction and real-print black calibration, and preserves parts, recipes, and edits in a portable local project.

文字数をさらに削る必要がある場合:

> ChromaMatter converts multipart vertex-colour OBJ and textured GLB models into editable Snapmaker Orca Full Spectrum 3MF projects, mapping four physical filaments to canonical mixed states while preserving parts, manual surface corrections, calibration, and portable project data.

### 日本語訳

> ChromaMatterは、高密度な頂点カラーOBJとUV baseColor付きGLBをSnapmaker Orca Full Spectrum用3MFへ変換します。パーツごとに4本の実フィラメントと16／24／32のcanonical混色stateを対応付け、3D上の表面色修正と実機黒補正を行い、パーツ、混色recipe、手修正をportableなlocal projectとして保持します。

### 応募時の非提携表記

> ChromaMatter is an independent open-source project. It is not an official or affiliated product of Snapmaker, TripoAI, Hi3D AI, OpenAI, or any filament manufacturer.

### アイコンのcreator declaration

2026-08-20、creatorはChromaMatterアイコンのロボットを、参考資料の影響を受けつつも既存character／製品を再現する意図のないオリジナルの架空機体、胸部の`ZENITH DYNAMICS CORP.`を実在組織との関係を意図しない創作文言と申告し、repository、実行file、screenshot、動画、Innovation Fund応募での公開・再配布を承認しました。project ownerはこの申告を根拠に公開GOを出しています。

basic exact-match web checkでは`ZENITH DYNAMICS CORP.`と`ChromaMatter`の完全一致を確認できませんでしたが、近似名`Zenith Dynamics`を使う実在組織は複数あります。応募ではそれらとの非提携を明示します。この記録はcreator declarationとowner decisionであり、独立した商標調査、第三者意匠clearance、法的意見ではありません。応募sample自体の権利／provenance gateはアイコンとは別に完了させます。

## 2. 競合を踏まえた勝ち筋

### ditherforgeを正しく位置付ける

[ditherforge](https://github.com/rtwfroody/ditherforge)は2026-08-19確認時点で902 commitsを持ち、GLB／3MF／STL／OBJ／COLLADA、複数object、filament collectionとTD、palette自動選択、複数dither、translucency simulation、mesh repair、split、sticker、swatch calibration、複数printer profileを扱う成熟したtoolである。したがって、次をChromaMatterだけの独自機能とは主張しない。

- OBJ／3MF変換
- 手持ちfilamentからの色選択
- 色数削減、dithering、色補正
- non-manifold repair
- model split、joint、calibration plate
- U1用profile入り3MF

### ChromaMatterが実証すべき固有のworkflow

機能の有無ではなく、次の**一続きの制作contract**で差別化する。

1. TripoAI等の高面数・複数パーツ`v x y z r g b`頂点カラーOBJ、またはHi3D AI等のUV baseColor付き静的GLBを読む。
2. 各partへ4本の実フィラメントを個別に割り当てる。
3. Full Spectrumの4本のtoolと16／24／32の離散的なvirtual mixed-filament stateへ対応付ける。
4. 同じ3D model上で、頂点色由来の陰影を見ながら表面をBrush／Fill／Smudge／Eyedropperで修正する。
5. 実機で強く出る黒をcalibration chartとoutput recipeで補正する。
6. part構成、canonical state ID、手修正、prepared geometryをportable projectで復元する。
7. Snapmaker Orcaで再open可能なcombined／per-part 3MFへ渡す。

言い切るべき価値は、**「4色へ減らす」ではなく「4本から生まれるFull Spectrum stateを、AI生成modelの制作単位として編集・保存する」**こと。

### 忖度なしのtier見込み

これは公式判定ではなく、現状の証拠からの内部評価である。

| tier | 現時点の見込み | 到達条件 |
|---|---|---|
| Active Builder | **十分狙える** | public GitHub、exact release gate、権利処理済みsample、U1完走動画、known limitationsを同時公開 |
| Eco-Enhancer | **証拠次第で可能** | 失敗→calibration→改善を同一sample／hashで追跡し、clean clone再現、Orca reopen、少なくとも1件の第三者再現を追加 |
| U1 Pioneer | **現状では難しい** | ditherforge等より広い機能数では勝ちにくい。Full Spectrum canonical state authoringの技術仕様、定量色評価、複数model／filamentでの実証、communityが再利用できるformatまたはAPIまで示す必要がある |

## 3. Cover image brief（640×360）

### 目的

縮小表示でも3秒で「元の色付き3D modelが、4本のfilamentでFull Spectrum造形になった」と分かる一枚にする。

### layout

- canvas: 640×360 px、16:9、PNG、sRGB
- 背景: 明るいneutral grayまたはoff-white。dark UI全画面は使わない。
- 左 31%: 同じ角度の頂点カラーOBJ preview
- 中央 31%: ChromaMatterの変換preview。余計なpanelを閉じ、modelと4本のF1–F4 swatchだけを見せる
- 右 38%: 同じ角度のU1実機完成品。輪郭、gradient、part seamが読める照明
- 矢印: 左→中央→右を細いcyan lineで接続
- 上部headline: `VERTEX COLOR → FULL SPECTRUM`
- 下部subline: `4 PHYSICAL FILAMENTS · 16/24/32 MIXED STATES`
- 左下に小さくproduct名: `ChromaMatter — AI Model Print Studio 0.8beta`
- 右下に小さく: `Open source · Local workflow`

### 使用する実物asset

- OBJ screenshot: `[PATH / SHA-256 / CAMERA ANGLE]`
- app screenshot: `[PATH / r31 COMMIT / CAMERA ANGLE]`
- final print photo: `[PATH / PHOTO DATE / CAMERA / WHITE BALANCE]`
- sample rights record: `[URL OR LEDGER ID]`

### coverで避けるもの

- 権利未確認character、第三者logo、既存作品に強く似たsilhouette
- `AI automatically paints perfectly`、`100% accurate colour`、`official`等の未実証表現
- 未公開研究機能のbutton
- old revision UI、palette番号が比較chartと違う画面
- 実物より彩度を上げる画像補正

## 4. 90秒hero video — shot list / script

完成品を最初に出す。操作説明動画ではなく、問題・解決・実証の順にする。字幕は英語を主、同じ意味の日本語を2行目に置く。音声なしでも理解できる構成とする。

| 時間 | 映像 | English subtitle / narration | 日本語字幕 |
|---:|---|---|---|
| 0–5秒 | 完成品をゆっくり45度回転。横に元OBJの同角度を0.8秒だけ重ねる | `This colour came from four physical filaments — with no surface painting after printing. [VERIFY]` | `この色は4本の実フィラメントから生まれました。造形後の表面塗装はありません。[要確認]` |
| 5–11秒 | 元画像→頂点カラーOBJ／UV texture GLB→Orcaで困る箇所を高速3cut | `AI models can carry rich vertex or texture colour, but that colour is not yet a Full Spectrum recipe.` | `AI modelの頂点色やtexture色は、そのままではFull Spectrumのrecipeになりません。` |
| 11–18秒 | ChromaMatterで権利処理済みsample GLBまたはOBJをopen。part listを見せる | `ChromaMatter opens high-poly vertex-colour OBJ and textured GLB models locally.` | `ChromaMatterは、高面数の頂点カラーOBJとtexture付きGLBをlocalで開きます。` |
| 18–28秒 | partを選択し、F1–F4の提案とpart別paletteを切替 | `Each part can use its own four-filament base palette.` | `各パーツに、それぞれ4本の基本フィラメントを設定できます。` |
| 28–37秒 | F1+F2、F1+F3…が横並びの16／24／32 mixed palette。比較chartも同じ番号順へmatchするcut | `The four tools become 16, 24, or 32 stable Full Spectrum states — shown in the same order everywhere.` | `4本を16・24・32の安定したFull Spectrum stateへ展開し、表示順を統一します。` |
| 37–47秒 | 顔または境界をBrush→Smudge→Undo。一筆だけ | `Correct a shadow edge directly on the 3D surface without flattening the original shading.` | `元の陰影を潰さず、3D表面上で影の境界を手直しします。` |
| 47–56秒 | calibration chart／黒state focus／実機黒補正のbefore-after | `A printed calibration chart reveals when black is stronger than the screen prediction.` | `実機chartで、画面予測より強く出る黒を確認します。` |
| 56–66秒 | combined／per-part 3MF export、Orcaでtool listとlayer preview | `Export keeps the parts and canonical colour recipes for Snapmaker Orca.` | `パーツとcanonical色recipeを保持してSnapmaker Orcaへ渡します。` |
| 66–76秒 | U1で造形中のtime-lapse。4 toolheadが分かるshot | `The U1 prints the same recipe with four loaded filaments.` | `U1が、4本のfilamentで同じrecipeを造形します。` |
| 76–85秒 | 黒が強い失敗版→補正版→最終版を同じ照明で横並び | `The goal is not a perfect simulation. It is a measurable path from failed colour to a better physical result.` | `完全な色再現を装うのではなく、失敗色から実物を改善できる測定可能な工程を作ります。` |
| 85–90秒 | GitHub URL、project名、完成品 | `ChromaMatter 0.8beta — open source, local, and ready for makers to test.` | `ChromaMatter 0.8beta — open sourceでlocal。次はmakerの皆さんと検証します。` |

### 90秒動画の収録条件

- `[FINAL SAMPLE OBJ SHA-256]`
- `[FINAL SAMPLE 3MF SHA-256]`
- `[R31 SOURCE COMMIT / TAG]`
- `[SNAPMAKER ORCA VERSION]`
- `[U1 FIRMWARE VERSION]`
- `[F1–F4 PRODUCT / COLOUR / LOT]`
- `[LAYER HEIGHT: expected 0.08 mm; verify actual profile]`
- `[PRINT TIME / FILAMENT CHANGES / TOTAL MASS]`
- `[NO POST-PRINT PAINT: YES/NO]`

## 5. 3～5分technical demo outline

### 0:00–0:20 — 結果と入力契約

- 完成品、元GLB／OBJ、Orca previewを同じ角度で提示。
- `v x y z r g b`頂点カラーまたはGLB UV baseColor、権利処理済みpublic sample、r31 commit hashを画面に出す。
- 「任意meshの完全修復や画面色との完全一致は保証しない」と冒頭で境界を示す。

### 0:20–0:55 — multipart modelとpart palette

- GLB／OBJをopenし、認識したpart数とface数を示す。
- 2つのpartを切り替え、それぞれのF1–F4を表示。
- 基本filament候補は提案であり、inventoryや実物に合わせて利用者が確定することを説明。

### 0:55–1:30 — Full Spectrum state mapping

- 16→24→32を切り替え、F-pair family-major順を表示。
- 比較chartの番号が同じ並びであることをside-by-sideで示す。
- 表示番号と内部canonical state IDを分離している理由を10秒で説明: project／manual paint／3MF recipe互換を守るため。

### 1:30–2:10 — 3D manual surface correction

- visible-face／selected-part guardをon。
- Brushで陰影境界を1回修正、Smudge、Undo／Redo。
- original shadingを単色へflattenしていないことをbefore-afterで示す。
- 高面数modelでの処理時間を字幕表示: `[LOAD s / OPEN EDITOR s / STROKE LATENCY ms / RAM GB]`。

### 2:10–2:45 — physical calibration

- calibration bundleを生成し、CSV／guide／chart 3MFを見せる。
- 同一filament／layer条件のprinted chart写真を重ねる。
- 実機黒補正はdisplay colourではなく3MF output recipeだけへ作用する、と説明。

### 2:45–3:15 — portable restore

- project folder内の`source.obj`または`source.glb`、`project.json`、`prepared_geometry.npz`、reference imageを見せる。
- folderを別pathへ移し、project load後にpart、camera、palette、manual correctionが復元することを実演。

### 3:15–3:55 — Orca contract

- combined 3MFとper-part 3MFを出力。
- Snapmaker Orcaでopenし、F1–F4、mixed states、part、0.08 mm profile、layer previewを確認。
- save→close→reopen→sliceまで連続収録し、編集途中をcutしない。

### 3:55–4:25 — 実機と正直な限界

- U1 time-lapse、完成品、失敗版を提示。
- 黒の隠蔽力、filament lot、照明、geometry defectで結果が変わることを明示。
- 現在の実証範囲はWindows、Snapmaker U1、TripoAI由来OBJとHi3D AI由来GLBであると説明。GLBはbaseColorを頂点へ焼き付け、PBR lighting mapやanimationを再現しないβ境界も示す。

### 4:25–5:00 — 再現参加への導線

- public GitHub、sample、exact checksum、issue template、Snapmaker Forum URL。
- third-party testとして募集したい結果を明示: 別filament 4色、別vertex-colour OBJ、16／24／32比較。

## 6. GitHub README hero section（EN、そのまま貼付可能）

```markdown
# ChromaMatter — AI Model Print Studio

**Turn high-poly vertex-colour OBJ and textured GLB models into editable Snapmaker Orca Full Spectrum projects.**

ChromaMatter maps each model part to four physical filaments and 16, 24, or 32 canonical mixed states, lets you correct colour directly on the 3D surface, and exports combined or per-part 3MF while preserving the colour recipe. Portable project folders keep the source OBJ or GLB, prepared geometry, palettes, and manual edits together.

![AI colour model to Full Spectrum workflow](docs/images/hero-640x360.png)

> **Independent project.** ChromaMatter is not an official or affiliated product of Snapmaker, TripoAI, Hi3D AI, OpenAI, or any filament manufacturer.

## Why it exists

Vertex-coloured or textured AI models can look richly shaded on screen, but a U1 print has four physical tools and a finite set of Full Spectrum states. ChromaMatter makes that conversion an authoring workflow instead of a one-click black box:

- preserve multipart structure and assign a separate four-filament base palette per part;
- keep each Full Spectrum job within one material family, with PLA as the default and opt-in beta workflows for four-ABS or four-PETG palettes;
- map colour to stable Full Spectrum mixed states without renumbering project or 3MF recipes;
- inspect and correct shadow boundaries with Brush, Fill, Smudge, and Eyedropper on the 3D surface;
- generate a calibration chart and compensate for physically dominant black mixtures;
- save a portable local project and export combined or per-part Snapmaker Orca 3MF.

## 90-second overview

[![Watch the ChromaMatter overview](docs/images/video-cover-640x360.png)]([VIDEO_URL])

## Reproduce the public demo

- Release: `[TAG / COMMIT]`
- Source ZIP SHA-256: `[SHA256]`
- Demo source GLB/OBJ SHA-256: `[SHA256]`
- Demo 3MF SHA-256: `[SHA256]`
- Snapmaker Orca: `[VERSION]`
- Printer: Snapmaker U1, `[FIRMWARE]`
- Layer height: `[0.08 mm — VERIFY]`
- Physical filaments: `[F1]`, `[F2]`, `[F3]`, `[F4]`

See [Quick Start](docs/QUICK_START_EN.md), [Validation](docs/VALIDATION.md), [Known Limitations](docs/KNOWN_LIMITATIONS.md), and [Sample Rights & Provenance](samples/PROVENANCE.md).
```

READMEではditherforgeを攻撃的に比較しない。必要なら`Related projects`で敬意をもって紹介し、ChromaMatterがFull Spectrum canonical state authoringへ特化していることだけを書く。

## 7. Snapmaker Forum / community post

### English post

**Title:** ChromaMatter 0.8beta — editing coloured AI models for the U1 Full Spectrum workflow

> Hi everyone,
>
> I am building **ChromaMatter — AI Model Print Studio**, an independent open-source Windows tool for a gap I encountered while printing vertex-coloured and textured AI models on the Snapmaker U1.
>
> A generated OBJ or GLB may already contain rich colour and shading, but the printer has four physical filaments and Snapmaker Orca Full Spectrum works through discrete mixed-filament states. ChromaMatter bakes GLB base colour into the same local authoring pipeline, keeps multipart structure, assigns a separate four-filament palette per part, maps the model to 16/24/32 Full Spectrum states, and lets the user correct colour directly on the 3D surface before exporting combined or per-part 3MF.
>
> The project also generates a calibration chart and can reduce physically dominant black mixtures in the output recipe. A portable project folder keeps the source OBJ or GLB, prepared geometry, palettes, and manual edits together so the work can be reopened on another path.
>
> This is not a claim of perfect screen-to-print colour. Filament opacity, lot, lighting, geometry, and slicer settings all matter. My goal is to make the failures visible and the correction path reproducible. The linked demo records the exact source revision, OBJ/3MF hashes, four filaments, Snapmaker Orca version, U1 settings, and the failed and improved prints.
>
> **Project:** https://github.com/Ponkichi0718/ChromaMatter  
> **90-second demo:** [VIDEO_URL]  
> **Development and physical-print log:** [NOTE_INDEX_URL]  
> **Public sample and reproduction steps:** [SAMPLE_URL]
>
> I would especially value tests with:
>
> 1. a different set of four physical filaments;
> 2. a vertex-colour OBJ or textured GLB from another AI service;
> 3. 16 vs 24 vs 32 mixed states;
> 4. large multipart meshes and per-part export.
>
> ChromaMatter is independent and is not an official or affiliated product of Snapmaker, TripoAI, Hi3D AI, OpenAI, or any filament manufacturer. I built it with deep respect for the work behind the U1, Snapmaker Orca, Full Spectrum, and the wider open-source colour-printing community.

### 日本語post

**タイトル:** ChromaMatter 0.8beta — 色付きAI modelをU1 Full Spectrum用に編集するopen-source tool

> こんにちは。
>
> Snapmaker U1で頂点カラー／UV texture付きAI modelを造形する中で感じた空白を埋めるため、Windows用open-source tool **ChromaMatter — AI Model Print Studio**を開発しています。
>
> 生成OBJ／GLBには豊かな色と陰影があっても、実機に入るのは4本のfilamentで、Snapmaker Orca Full Spectrumは離散的な混色stateを使います。ChromaMatterは、GLBのbaseColorも既存の頂点色pipelineへ焼き付け、複数partを保持し、partごとに4本の基本paletteを設定し、16／24／32のFull Spectrum stateへ対応付けたうえで、3D表面上を手直ししてcombined／part別3MFへ出力します。
>
> 実機calibration chartと、強く出やすい黒混色をoutput recipe側で弱める補正も備えています。source OBJ／GLB、prepared geometry、palette、手修正をportable project folderにまとめるため、別pathでも作業を復元できます。
>
> これは画面色と実物色の完全一致を保証するものではありません。filamentの隠蔽力、lot、照明、geometry、slicer設定で結果は変わります。目標は、失敗を見えるようにし、補正工程を再現可能にすることです。公開demoには、exact revision、OBJ／3MF hash、4本のfilament、Snapmaker Orca版、U1条件、失敗版と改善版を記録します。
>
> **GitHub:** https://github.com/Ponkichi0718/ChromaMatter  
> **90秒demo:** [VIDEO_URL]  
> **開発・実機造形記録:** [NOTE_INDEX_URL]  
> **公開sampleと再現手順:** [SAMPLE_URL]
>
> 特に、別の4色filament、別AI serviceの頂点カラーOBJ／texture付きGLB、16／24／32の比較、大型multipart modelで試していただける方を探しています。
>
> ChromaMatterは独立projectであり、Snapmaker、TripoAI、Hi3D AI、OpenAI、各filament makerの公式・提携製品ではありません。U1、Snapmaker Orca、Full Spectrum、open-source color printing communityへの敬意を前提に開発しています。

## 8. Evidence / claim checklist

### A. release同一性

- [x] public repository URL: `https://github.com/Ponkichi0718/ChromaMatter`
- [x] initial source publication commit: `a01ba4baa791809a5a6621fac35956dc65479216`（release tagは未作成）
- [ ] source ZIP name／SHA-256: `[FILE / HASH]`
- [ ] software ZIP name／SHA-256: `[FILE / HASH]`
- [ ] public sample OBJ name／SHA-256: `[FILE / HASH]`
- [ ] combined 3MF name／SHA-256: `[FILE / HASH]`
- [ ] per-part 3MF names／SHA-256: `[FILES / HASHES]`
- [ ] calibration bundle name／SHA-256: `[FILE / HASH]`
- [ ] screenshotに写るeditionとrelease tagが一致

### B. source quality

- [x] 2026-08-20 owner publication GOとicon creator declaration／非提携方針を記録
- [x] r31 exact source full regression: Python 3.13.14、1023 PASS／任意1 SKIP、100.656秒
- [x] clean build、built self-test、日英UI smoke
- [x] preflight fresh extract self-test、日英UI smoke、manifest／archive／path safety／privacy audit
- [x] final source-only restage、Downloads配置、detached `SHA256SUMS-r31.txt`、archive／CRC／privacy／identity照合
- [ ] clean cloneでsetup／test／public sampleを第三者手順だけで再現
- [ ] GPL、第三者license notice、TetGen／Qt等binary distribution条件を確認
- [ ] known limitations、issue template、security／privacy窓口

### C. sample権利とprovenance

- [ ] 2D生成service／plan／date／prompt／seed: `[RECORD]`
- [ ] TripoAI等3D生成service／plan／date／input: `[RECORD]`
- [ ] model、画像、動画、音源の公開／改変／再配布権
- [ ] 既存character、logo、特徴的silhouetteとの類似をhuman review
- [ ] public sampleのlicenseとattribution file
- [ ] private検証file、個人path、account名、API keyが公開treeにない

### D. UI／workflow claim

- [ ] F1+F2、F1+F3…のpaletteと比較chartが同じ表示順・番号
- [ ] canonical state ID／旧project／manual paint／3MF recipe不変のtest
- [ ] part別F1–F4、16／24／32を実modelでscreen capture
- [ ] Manual EditingのBrush／Fill／Smudge／Eyedropper／Undoを一続きで収録
- [ ] portable folderを別pathへ移しexact restore
- [ ] combined／per-part 3MFをOrcaでsave→close→reopen→slice
- [ ] `Solidify`は任意meshの完全修復を保証しないと記載

### E. physical print claim

- [ ] final print photo front／back／left／right／45°: `[PATHS]`
- [ ] same-lighting failed／improved／final comparison: `[PATHS]`
- [ ] U1 firmware／Snapmaker Orca version／profile
- [ ] F1–F4 maker、product、colour、lot、actual measured colour if available
- [ ] layer height、nozzle、walls、infill、support、scale
- [ ] print time、mass、filament changes、failed attempts
- [ ] `no post-print surface paint`を主張する場合、実際に塗装していないことを確認
- [ ] 黒補正before／afterを同じgeometry・照明・filament・profileで比較
- [ ] 画面色との完全一致やpaint-like resultを保証しない

### F. 応募とcommunity

- [ ] [Innovation Fund公式ページ](https://www.snapmaker.com/en-US/innovation-fund)の送信日条件を再確認し、画面を保存
- [ ] 640×360 cover、90秒video、technical demoがpublic URLでsign-in不要
- [ ] Snapmaker Forum等へcommunity post
- [ ] form short descriptionとGitHub READMEの主張が一致
- [ ] 応募category `3D Model Editor`
- [ ] official affiliationを示す表現なし
- [ ] ditherforge等の既存projectを正確に紹介し、独自性を誇張しない
- [ ] 質問、bug、再現報告を受ける公開issue導線

## 9. 最終submit前の順番

1. r31 exact source-only release gateは完了。EXE／software ZIPは第三者binary再配布監査まで保留する。
2. 権利処理済みsampleを同じr31でGLB／OBJ→project→3MF→Orca→U1まで完走する。
3. hash、profile、filament、失敗／改善写真を記録する。
4. 公開済みGitHubへREADME hero、sample、known limitations、validationを追記する。
5. 90秒hero videoとtechnical demoを公開する。
6. Snapmaker Forumへ投稿し、URLを保存する。
7. 公式formへproject URL、category、short description、coverを入力する。
8. 送信前画面、送信完了画面、当日の規約／FAQを保存する。

## 10. 最終判断

応募文を強くするために、これ以上featureを増やす必要はない。現在の課題は**同一revisionと同一sampleで、software contractと実機結果を一本につなぐこと**である。

公開前に必ず揃える最低線は、`public source + exact test evidence + original redistributable sample + Orca reopen/slice + U1 final print + honest limitations`。これが揃えばActive Builderは現実的で、実機calibrationの定量比較と第三者再現まで加わればEco-Enhancerを狙える。U1 Pioneerを主目標に誇張するより、Full Spectrum creator workflowの新しい入口を確実に実証する方が勝率は高い。
