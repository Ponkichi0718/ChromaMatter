# ChromaMatter 0.8beta r32.2 — Flat Four Test 3

Status: **publication candidate — not yet tagged or published**.

This is a separate experimental Windows prerelease candidate. It does not
replace, retag, or modify the immutable `v0.8beta-r32.2` release or the frozen
Flat Four Test 2 assets. The application-visible version remains
`0.8beta (r32.2)`.

## Planned GitHub identity

- Branch: `codex/r32-2-experimental-flat4-large-glb-2d-filter`
- Planned tag: `v0.8beta-r32.2-flat4-test3`
- Source commit: pending exact candidate freeze
- Draft PR: [#7](https://github.com/Ponkichi0718/ChromaMatter/pull/7)
- Planned Windows asset:
  `ChromaMatter-0.8beta-r32.2-flat4-test3-win64.zip`
- Planned complete corresponding source:
  `ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip`
- Planned SBOM:
  `ChromaMatter-0.8beta-r32.2-flat4-test3-SBOM.cdx.json`
- Planned binary component map:
  `ChromaMatter-0.8beta-r32.2-flat4-test3-BINARY_COMPONENT_MAP.json`
- Planned checksum record: `SHA256SUMS-r32.2-flat4-test3.txt`

The Test 3 package intentionally contains no bundled `DemoData`. Private
models, generated previews, and derived 3MF files are not release payloads.

## GitHub Release body — 日本語

> **Flat Four Test 3 / Windows実験テスト版**
>
> これは評価とfeedback収集のための公開候補です。安定版
> `v0.8beta-r32.2`と、固定済みのFlat Four Test 2 tag／assetは変更しません。
> 公開後はZIP全体を展開してから起動してください。

### Test 3の変更点

- Flat Fourに、形状のつながりを使った保守的な白／灰色ハイライト補正を追加しました。
  肌などの滑らかな有彩色面に焼き込まれた、小さく確度の高い白・灰色の照明斑だけを、
  その境界で実際に使われている有彩色F slotへまとめます。
- **白を一律に除去する処理ではありません。** 黒い線に隣接する目の白など、意味の
  ある小さな白はハイライトとして吸収せず、白いtargetとして保持します。黒い細部も
  保持します。
- 保持された白が印刷対象の総面積の**0.01%以上**を占める場合、自動filament提案は
  白に近い実filamentを1 slot確保します。0.01%未満のごく小さな残存白はtargetとして
  残りますが、それだけでは白spoolを強制しないため、選ばれたF1～F4の最寄色へ割り当て
  られる場合があります。
- F1～F4の4物理slotと3MFのstate情報は維持します。必要な白が残らないmodelでは、
  実際の塗り分けが3色だけになる場合があります。Manual Editingの手塗りを優先し、
  Full Spectrumの動作は変更しません。

### 重要な制限

- これは意味認識AIではありません。暗い線、折り目、part境界のない滑らかな肌色面に
  完全に囲まれた小さな白は、焼付ハイライトと区別できず吸収される場合があります。
  必要な白はManual Editingで指定してください。
- 再利用できる隣接情報がない50万面超のopen meshでは、この自動ハイライト補正だけを
  安全側でskipします。ほかのFlat Four処理は継続します。
- multipartの閉立体化とpart別3MF出力は、引き続き入力依存のbeta機能です。安全検証を
  迂回して出力を強制しません。
- このexact Test 3 packageのphysical printer validationは未実施です。画面色と実機色の
  一致を保証せず、Windows executableも未署名です。入手元、SHA-256、Orcaのslice
  previewを確認してください。

### 公開前の検証状態

- Working-tree full regression: **1,431 tests、失敗0、optional skip 3**。
- Owner-only clean build、packaged／fresh-extracted self-test、日英UI smoke、binary
  inventory、archive／privacy検証: PASS。
- 上記はpreflight evidenceです。公開対象のexact commitからfull regression、clean
  build、complete corresponding source、SBOM、component map、checksum、fresh-extract
  監査を再生成・再検証するまで、Test 3を公開済みまたは一般配布可能とは扱いません。

## GitHub Release body — English

> **Flat Four Test 3 / Experimental Windows build**
>
> This is a publication candidate for evaluation and feedback. It does not
> modify the stable `v0.8beta-r32.2` release or the frozen Flat Four Test 2 tag
> and assets. After publication, extract the complete ZIP before launching it.

### What changed in Test 3

- Flat Four now has a conservative topology-aware white/gray highlight
  correction. Only small, high-confidence lighting patches baked into a smooth
  chromatic surface such as skin are folded into the chromatic F slot actually
  used around their boundary.
- **White is not removed globally.** Meaningful small white details, including
  eye whites beside dark linework, are not absorbed as highlights and remain
  white targets. Black detail is also preserved.
- When retained white covers at least **0.01%** of the total printable area,
  automatic filament recommendation reserves one suitable near-white physical
  filament. White below 0.01% remains an unabsorbed target but does not by
  itself force a white spool, so it can map to the nearest selected F1-F4 colour.
- All four physical F1-F4 slots and 3MF state metadata remain intact. A model
  with no intentional white left may effectively use only three paint IDs.
  Manual Editing stays authoritative, and Full Spectrum behaviour is unchanged.

### Important limitations

- This is not semantic AI recognition. A tiny white patch fully enclosed by one
  smooth skin/tan surface, without a dark edge, crease, or part boundary, can be
  indistinguishable from a baked highlight and may be absorbed. Specify
  intentional white with Manual Editing when needed.
- On an open mesh above 500,000 faces without reusable adjacency, only this
  automatic highlight correction is skipped fail-closed; the rest of Flat Four
  continues.
- Multipart solidification and per-part 3MF export remain input-dependent beta
  features. Safety validation is not bypassed to force an export.
- Physical-printer validation of this exact Test 3 package is pending. Screen
  colour is not a print-colour guarantee, and the Windows executable is
  unsigned. Verify the source, SHA-256, and Orca slice preview.

### Pre-publication validation state

- Working-tree full regression: **1,431 tests, zero failures, three optional
  skips**.
- Owner-only clean build, packaged/fresh-extracted self-test, both language UI
  smokes, binary inventory, archive checks, and privacy checks: PASS.
- This is preflight evidence only. Test 3 must not be described as published or
  generally distributable until the exact release commit has regenerated and
  passed the full regression, clean build, complete corresponding source, SBOM,
  component map, checksums, fresh-extract audit, and publication checks.
