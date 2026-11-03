# Sorca CM v1.1

Colour editing, mixing and cutting inside Snapmaker Orca. / Snapmaker Orcaで配色・ペイント・分割を。

**[Download / ダウンロード](https://chromamatter.app/download)** · **[Manual / マニュアル](https://chromamatter.app/manual)**

## 強化した機能

- **カット・ふた・ダボ**：操作パネルを整理。中央が平らなふたの幅・高さを調整でき、一体ダボを付ける側も選べます。
- **切断後の扱いやすさ**：再切断、接地、底面候補を改善。実際は4本なのに5色と判定され、スライスできない不具合を修正しました。
- **Full Spectrum配色**：元データとの対応が確認できる切断済みパーツへ、配色を貼り直せます。
- **ペイント**：折り目スライダーを常時表示。「面全体（塗り残しも）」で、同じ色の上から連続する面をまとめて塗り直せます。角度で範囲を制限でき、従来の「同じ色」も使えます。

**Windows・Mac・Linuxの3OSで、同じv1.1の機能を使えます。**

## What’s improved

- **Cuts, caps and attached pegs:** clearer controls, adjustable flat-centre cap width/height, and a choice of which side receives the attached peg.
- **After cutting:** improved repeated cuts, bed placement and base-face candidates; fixed a false five-material error that blocked slicing parts using four materials.
- **Full Spectrum transfer:** reapply colours to cut parts whose correspondence with the retained source can be verified.
- **Painting:** an always-visible crease-angle slider and a whole-surface fill option that repaints missed islands even when clicking the selected colour. An angle threshold limits the connected area; same-colour fill remains available.

**Windows, Mac and Linux include the same v1.1 features.** Whole-surface fill also replaces intentional patterns within the selected area; use Undo when needed.

## Choose your download / ダウンロード

| OS | Application | Corresponding source |
| --- | --- | --- |
| Windows x64 | `Sorca-CM-v1.1-Windows-x64.zip` | `Sorca-CM-v1.1-source.tar.gz` |
| Apple Silicon, macOS 15+ | `Sorca-CM-v1.1-macos-arm64-app.zip` | `Sorca-CM-v1.1-source.tar.gz` |
| Ubuntu 22.04 x86_64, glibc 2.35 | `Sorca-CM-v1.1-Linux-x86_64.tar.gz` | `Sorca-CM-v1.1-source.tar.gz` |

Extract the complete archive into a new folder. Windows: open **Sorca CM.exe** at the package root. Mac: open **Sorca CM.app**. Linux: run **Start-Sorca-CM.sh**. Windows web features require WebView2; Linux requires GTK3, WebKit2GTK 4.0, GStreamer and OpenGL/EGL libraries. Mac is **ad-hoc signed only, without Developer ID or notarization**; Intel Macs are not supported.

全体を新しいフォルダーへ展開してください。既存のアプリと原本を残し、版を切り替える前に他のCM版を閉じてください。保存設定の場所を共有する場合があります。

## Verification and scope / 検証範囲

Development prerelease based on Snapmaker Orca 2.4.0. Windows has targeted GUI, save/reload, regression and real-model slicing checks; the final painting changes also passed GUI/Undo/Redo/save/reload checks. Linux has build/CLI/dependency/archive checks. Mac has CI build/signature/CLI and arm64 archive verification. **Mac/Linux GUI and real-model slicing, and physical printing/connector fit on all OSes, remain unverified.** These packages do not claim a fix for physical surface debris or calibrated colour reproduction.

Windowsは対象操作と保存・再読込・実モデルのスライスを確認済み。Mac／LinuxのGUI・実モデルスライス、全OSの実印刷・ダボ嵌合は未確認です。実際に5本以上使うプレートの制限は維持しています。複雑な形状の切断やふたは、スライス結果を確認してください。

The illustrated manual currently covers v1.0; v1.1 cut/paint controls differ. Partial transparent-coat and colour-lithophane experiments are not promoted as v1.1 features. Earlier releases remain available. See `SHA256SUMS.txt` and `RELEASE_INFO.json` for exact package identities; use the release-specific source archives rather than GitHub’s automatic source ZIP of the historical standalone repository.
