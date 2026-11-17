# Sorca CM v1.1 — Pre-release / 開発版 — Windows・macOS・Linux

**Sorca CMの現行統合開発版です。** ChromaMatterの色処理をSnapmaker Orca 2.4.0へ統合した非公式版で、Pre-releaseとして公開しています。旧単体版ChromaMatterを別にインストールする必要はありません。

GitHubの「Latest」と `/releases/latest` APIは、旧単体版ChromaMatter v0.9を示します。現行の統合開発版を試す方は、このページのOS別リンクを使用してください。

**This is the current integrated development release of Sorca CM.** It brings ChromaMatter’s colour workflows into Snapmaker Orca 2.4.0 as an unofficial pre-release. A separate installation of the legacy standalone ChromaMatter app is not required.

GitHub’s “Latest” label and `/releases/latest` API point to the legacy standalone ChromaMatter v0.9. To try the current integrated development release, use the OS-specific links on this page.

[公式ダウンロードページ / Download page](https://chromamatter.app/download) · [図解マニュアル / Illustrated manual](https://chromamatter.app/manual) · [旧単体版v0.9 / Legacy standalone v0.9](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.9)

## 開発版・検証範囲 / Development pre-release — validation scope

- **Windows：** 対象GUI・保存／再読込・回帰テストを確認しています。実モデルスライスは先行の共通カットビルドで確認し、最終ペイント変更はGUI・Undo／Redo・保存／再読込を確認しています。
- **macOS／Linux：** ビルド・CLI・配布物を検査済みですが、GUI操作と実モデルスライスは未検証です。
- **全OS：実印刷・ダボ嵌合は未検証です。**

- **Windows:** Targeted GUI, save/reload and regression checks have been performed. Real-model slicing was checked on the preceding common cut build; the final painting changes passed GUI, Undo/Redo and save/reload checks.
- **macOS/Linux:** Build, CLI and archive checks have been performed, but GUI operation and real-model slicing remain unverified.
- **All platforms: physical printing and connector fit remain unverified.**

原本と旧版を残し、アーカイブ全体を新しいフォルダーへ展開してください。印刷前にスライス結果を確認してください。

Keep original projects and older versions, and extract the complete archive into a new folder. Inspect the sliced result before printing.

## アプリをダウンロード / Download the application

| OS | アプリ / Application | 展開後の起動入口 / Launch after extraction |
| --- | --- | --- |
| Windows x64 | [Sorca-CM-v1.1-Windows-x64.zip](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-v1.1/Sorca-CM-v1.1-Windows-x64.zip) | `Sorca CM.exe` |
| Apple Silicon・macOS 15以降 / macOS 15+ | [Sorca-CM-v1.1-macos-arm64-app.zip](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-v1.1/Sorca-CM-v1.1-macos-arm64-app.zip) | `Sorca CM.app` |
| Ubuntu 22.04・x86_64・glibc 2.35 | [Sorca-CM-v1.1-Linux-x86_64.tar.gz](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-v1.1/Sorca-CM-v1.1-Linux-x86_64.tar.gz) | `./Start-Sorca-CM.sh` |

WindowsのWeb機能にはMicrosoft Edge WebView2 Runtimeが必要です。Mac版はad-hoc署名のみで、Developer ID署名・Apple公証はありません。Intel Macには対応していません。Linux版はGTK3・WebKit2GTK 4.0・GStreamer・OpenGL/EGL等の依存ライブラリが必要で、AppImageではありません。

既存CM版と設定先を共有する場合があります。設定をバックアップし、切り替え前に他のCM版を閉じてください。

Windows web features require Microsoft Edge WebView2 Runtime. The Mac app is ad-hoc signed, without Developer ID signing or Apple notarization; Intel Macs are not supported. Linux requires GTK3, WebKit2GTK 4.0, GStreamer, OpenGL/EGL and their dependencies; this package is not an AppImage.

Existing CM editions may share settings. Back up your settings and close other editions before switching.

## ファイルの選び方 / Choosing files

アプリを実行する方は、上表のOS別ファイルを選んでください。`previous-20261103-*`は以前の配布物を保存したもので、通常のダウンロード対象ではありません。

3OSの対応ソースは[Sorca-CM-v1.1-source.tar.gz](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-v1.1/Sorca-CM-v1.1-source.tar.gz)です。GitHubが自動生成する「Source code」のZIP／tar.gzは旧単体版リポジトリのスナップショットであり、この統合版の対応ソースではありません。別リリースの「build inputs」は開発・ビルド用で、アプリではありません。

To run the app, choose the OS-specific package in the table above. Files beginning with `previous-20261103-` preserve earlier packages and are not the normal download choice.

Use [Sorca-CM-v1.1-source.tar.gz](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-v1.1/Sorca-CM-v1.1-source.tar.gz) for the corresponding source on all three platforms. GitHub’s automatically generated “Source code” ZIP/tar.gz archives represent the historical standalone repository, not the corresponding source for this integration. Separate “build inputs” releases contain development/build materials, not applications.

[SHA-256チェックサム / SHA-256 checksums](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-v1.1/SHA256SUMS.txt) · [配布物情報 / Package information](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-v1.1/RELEASE_INFO.json)

## 強化した機能

- **カット・ふた・ダボ**：操作パネルを整理。中央が平らなふたの幅・高さを調整でき、一体ダボを付ける側も選べます。
- **切断後の扱いやすさ**：再切断、接地、底面候補を改善。実際は4本なのに5色と判定され、スライスできない不具合を修正しました。
- **Full Spectrum配色**：元データとの対応が確認できる切断済みパーツへ、配色を貼り直せます。
- **ペイント**：折り目スライダーを常時表示。「面全体（塗り残しも）」で、同じ色の上から連続する面をまとめて塗り直せます。角度で範囲を制限でき、従来の「同じ色」も使えます。

Windows・macOS・Linux向けのv1.1配布物があります。検証範囲はOSごとに異なります。

## What’s improved

- **Cuts, caps and attached pegs:** clearer controls, adjustable flat-centre cap width/height, and a choice of which side receives the attached peg.
- **After cutting:** improved repeated cuts, bed placement and base-face candidates; fixed a false five-material error that blocked slicing parts using four materials.
- **Full Spectrum transfer:** reapply colours to cut parts whose correspondence with the retained source can be verified.
- **Painting:** an always-visible crease-angle slider and a whole-surface fill option that repaints missed islands even when clicking the selected colour. An angle threshold limits the connected area; same-colour fill remains available.

v1.1 packages are available for Windows, macOS and Linux. Validation coverage differs by platform. Whole-surface fill also replaces intentional patterns within the selected area; use Undo when needed.

## Verification and scope / 検証範囲

Development prerelease based on Snapmaker Orca 2.4.0. Windows has targeted GUI, save/reload, regression and real-model slicing checks; the final painting changes also passed GUI/Undo/Redo/save/reload checks. Linux has build/CLI/dependency/archive checks. Mac has CI build/signature/CLI and arm64 archive verification. **Mac/Linux GUI and real-model slicing, and physical printing/connector fit on all OSes, remain unverified.** These packages do not claim a fix for physical surface debris or calibrated colour reproduction.

Windowsは対象操作と保存・再読込・実モデルのスライスを確認済み。Mac／LinuxのGUI・実モデルスライス、全OSの実印刷・ダボ嵌合は未確認です。実際に5本以上使うプレートの制限は維持しています。複雑な形状の切断やふたは、スライス結果を確認してください。

オンラインの図解マニュアルは、2026年11月5日にv1.1対応へ更新しました。過去版の画面例と未検証事項は本文中で区別しています。マニュアルの更新は、新たな実印刷・光学検証を示すものではありません。

The online illustrated manual was updated for v1.1 on 2026-11-05. Historical UI examples and unverified results are identified in the guide. This documentation update does not establish new physical-print or optical validation.

Partial transparent-coat and colour-lithophane experiments are not promoted as v1.1 features. Earlier releases remain available. See `SHA256SUMS.txt` and `RELEASE_INFO.json` for exact package identities; use the release-specific source archives rather than GitHub’s automatic source ZIP of the historical standalone repository.
