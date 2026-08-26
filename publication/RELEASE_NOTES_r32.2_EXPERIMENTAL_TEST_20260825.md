# ChromaMatter 0.8beta r32.2 Experimental Test — Draft Release Notes

Status: **GitHub Draft Release created — not published**.

This document defines a separate test channel. It does not replace, retag, or
modify the immutable Innovation Fund-facing `v0.8beta-r32.2` release or any of
its assets. The application-visible revision intentionally remains
`0.8beta (r32.2)`.

## GitHub identity

- Branch: `codex/r32-2-experimental-flat4-large-glb-2d-filter`
- Draft tag: `v0.8beta-r32.2-experimental-20260825`
- Source commit: `0d768fb6b3a0c68328b3c94b6ed48eff9a80ad13`
- Draft PR: [#7](https://github.com/Ponkichi0718/ChromaMatter/pull/7)
- Draft title: `ChromaMatter 0.8beta r32.2 Experimental Test — Flat Four / Large GLB / 2D Colour Filter`
- Release settings: keep as **Draft** during review; if it is later published,
  mark it **Pre-release**.
- Draft assets:
  - `ChromaMatter-0.8beta-r32.2-experimental-20260825-win64.zip`
  - `ChromaMatter-0.8beta-r32.2-experimental-20260825-win64.zip.sha256`
- Windows ZIP SHA-256:
  `686823CDBC6C325B8B281E5820D0B73E9A8911D47B845B515C92A3ED565BBE56`

Do not move or recreate `v0.8beta-r32.2`. Test assets must use a new name that
contains the experimental tag identity and must never reuse an existing r32.2
asset name.

## GitHub Release body — 日本語

> **Experimental Test / 実験テスト版**
>
> これは評価とフィードバック収集のためのWindowsテスト版です。
> Innovation Fund向けに公開済みの安定したr32.2配布版ではありません。
> 公開済みtag `v0.8beta-r32.2`と、そのRelease assetは変更していません。
> アプリ内の表示revisionは互換性を優先して`0.8beta (r32.2)`のままです。

### 今回試せる機能

- **Large GLB:** 大規模／multipart GLBの読み込みとproject復元経路を改善しました。
  すべてのGLBを開ける保証ではなく、対応可否はmodel構造と利用可能memoryに依存します。
- **Flat Four:** Full Spectrumとは別に、F1〜F4の4物理色だけで単純に塗り分ける
  modeを追加しました。自動提案は印刷面積を重視して4色を選びます。
- **2D彩色:** model前方に固定したlightと面normalを使い、印刷可能な色へ
  二次元的な陰影を加える実験filterを追加しました。ink線抽出やmaterial rendererでは
  ありません。
- **Flat Fix1:** Full Spectrum由来の休止中の混色stateが残っていてもFlat出力を
  非破壊でF1〜F4へ投影し、F1〜F4の手入力や候補選択をpreviewへ即時反映します。
  Full Spectrumへ戻したときの保存済み設定は維持されます。

### 重要な制限

- パーツ化modelの閉立体化とパーツ別3MF出力は、引き続き不安定なbeta機能です。
  成功するfileがある一方、形状、開口、重なり、非manifold状態によっては
  閉立体化または3MF出力に失敗します。安全検証を迂回して出力するものではありません。
- 2D彩色は固定正面lightによる簡易stylizerです。camera-spaceの輪郭線やPBR materialを
  再現する機能ではなく、結果は選択した4色／混色paletteに制約されます。
- Windows executableは未署名です。Windows SmartScreenの警告が表示される場合が
  あります。入手元とchecksumを確認し、不明なfileは実行しないでください。
- このテスト版はInnovation Fund向け公開済みr32.2の品質証拠や代替配布物ではありません。

### 検証実績

- Full regression: **1,375 tests、失敗0、任意の環境依存skip 3**。
- Packaged `--self-test`: PASS。
- Packaged Japanese UI smoke: PASS。
- Packaged English UI smoke: PASS。
- Fresh extraction後のself-testと日英UI smoke: PASS。

上記は今回の評価buildに対する技術検証であり、すべてのmodelでの読み込み、閉立体化、
3MF出力、slice、実機印刷を保証するものではありません。

### 一般公開前に必要なもの

一般配布へ進める前に、公開対象のexact commitから次を再生成し、相互のidentity、size、
SHA-256を検証して同じReleaseへ揃える必要があります。

- Complete corresponding source
- CycloneDX SBOM
- Binary component map
- Detached checksum record

これらのrelease gateが完了するまでは、一般公開可能な配布版とは扱いません。

## GitHub Release body — English

> **Experimental Test**
>
> This Windows build is provided for evaluation and feedback. It is **not the
> Innovation Fund stable r32.2 distribution**. The published
> `v0.8beta-r32.2` tag and all of its Release assets remain unchanged. The
> in-application revision intentionally remains `0.8beta (r32.2)` for this
> low-risk test channel.

### Features under test

- **Large GLB:** Improves loading and project restoration paths for large and
  multipart GLB files. This does not guarantee that every GLB will open;
  compatibility remains dependent on model structure and available memory.
- **Flat Four:** Adds a simple F1–F4 physical-colour workflow beside Full
  Spectrum. Automatic recommendation gives more weight to printable surface
  area when selecting four colours.
- **2D Colour Filter:** Adds an experimental printable stylizer using a fixed
  front light and surface normals. It is not camera-space ink-line extraction
  or a material renderer.
- **Flat Fix1:** Dormant Full Spectrum mixed states are projected
  non-destructively to F1–F4 at the Flat export boundary. F1–F4 manual entry
  and recommendation changes refresh the Flat preview immediately, while the
  stored Full Spectrum configuration remains available when switching back.

### Important limitations

- Multipart solidification and per-part 3MF export remain unstable beta
  features. Some files succeed, while others can fail because of holes,
  overlaps, non-manifold geometry, or other model-specific conditions. The
  fail-closed safety validation is not bypassed to force an export.
- The 2D filter is a fixed-front-light stylizer, not an outline or PBR material
  renderer. Results are bounded by the selected four-colour or mixed-colour
  printable palette.
- The Windows executable is unsigned. Windows SmartScreen may display a
  warning. Verify the download source and checksum, and do not run an unknown
  file.
- This test build is neither evidence for nor a replacement of the published
  Innovation Fund-facing r32.2 distribution.

### Validation completed

- Full regression: **1,375 tests, zero failures, three optional
  environment-dependent skips**.
- Packaged `--self-test`: PASS.
- Packaged Japanese UI smoke: PASS.
- Packaged English UI smoke: PASS.
- Fresh-extracted self-test and both language UI smokes: PASS.

This evidence applies only to the evaluated build. It is not a guarantee that
every model will load, solidify, export, slice, or print successfully.

### Required before general publication

Before general distribution, the following artifacts must be regenerated from
the exact release commit and published together only after their identities,
sizes, and SHA-256 values agree:

- Complete corresponding source
- CycloneDX SBOM
- Binary component map
- Detached checksum record

Until those release gates are complete, this draft must not be treated as a
general-public binary release.
