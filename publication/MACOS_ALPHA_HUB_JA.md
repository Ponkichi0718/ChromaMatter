# ChromaMatter macOS Source Tester Alpha テスト案内

協力ありがとうございます。これは、**Apple Silicon / macOS 15以降**向けの
独立したtest経路です。

## ここから開始

sourceから起動するテスター版を今すぐ試せます。

1. **[固定Source Tester Alpha ZIPをダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-alpha1/ChromaMatter-0.8beta-macos-source-alpha1.zip)**し、[tag／Releaseページ](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-alpha1)の`SHA256SUMS-macos-source-alpha1.txt`と照合します。
2. [日本語の初回setup・10分テスト手順](MACOS_ALPHA_TESTING_JA.md)を読みます。
3. ZIPを展開し、`START_MACOS_SOURCE_ALPHA.command`をControl-clickして
   **「開く」**を選びます。
4. launcherに公式Python 3.13.14とhash-lock済み依存関係を検証・導入させます。
   Installer完了後はTerminalへ戻ってReturnを押し、Pythonが見つからない場合だけ
   launcherを開き直します。
5. 自動生成される公開4色GLBで確認し、結果を報告します。

生成されるfixtureは`ChromaMatter-Public-Four-Color-Test.glb`です。保存先と
click-by-click手順は日本語guideに記載しています。

programming知識、printer、有料AI account、private modelは不要です。初回のみ
数百MB程度のdownloadがあり、数分かかる場合があります。2回目以降はlocal環境を
再利用します。

## 重要：事前buildしたappではありません

上のdownloadは、案内付きlauncherを含む固定source codeです。
**承認済みの事前build `.app` ZIPはありません。** 253件のMach-Oについて
source／build／再link根拠が未解決のため、app配布は保留中です。`diagnostics`と
書かれたartifactは診断reportであり、applicationではありません。

Apple Siliconでのsource test、native probe、packaged self-test、日英UI smokeは
[技術CI #32947038458](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32947038458)で
成功しています。[Draft PR #12](https://github.com/Ponkichi0718/ChromaMatter/pull/12)は
sourceとreviewの作業場所です。どちらもtester downloadではありません。

## 結果を投稿

成功・一部成功、setupの質問、一般的な感想は
[macOS Alpha Testing discussion #9](https://github.com/Ponkichi0718/ChromaMatter/discussions/9)へ
投稿します。

```text
全体結果: 成功 / 一部成功
test経路: Source Tester Alpha
source tag: v0.8beta-macos-source-alpha1
source commit（不明なら省略）:
Mac model / chip:
RAM:
macOS version:
公式Python setup: 成功 / 導入済み / 失敗
hash-lock依存関係setup: 成功 / 失敗
自動self-test: 成功 / 失敗
日本語UI: 成功 / 失敗 / 未確認
英語UI: 成功 / 失敗 / 未確認
公開4色GLB・表示操作: 成功 / 失敗 / 未確認
Full Spectrum: 成功 / 失敗 / 未確認
Flat Four F1～F4のみ: 成功 / 失敗 / 未確認
Manual Fill / Undo / Redo: 成功 / 失敗 / 未確認
3MF出力: 成功 / 失敗 / 未確認
project保存・再読込: 成功 / 失敗 / 未確認
Snapmaker Orca versionと結果:
補足:
```

再現するcrash、停止、setup失敗、表示／入力、読込、色割当、出力、文書の問題は
[macOS alpha Issue form](https://github.com/Ponkichi0718/ChromaMatter/issues/new?template=macos_alpha_report.yml)へ
1件ずつ報告します。

## privacyとalpha範囲

初回setupは、検証済み公式Python installerとhash-lock済みPython依存関係の取得に
限り通信します。その後のmodel／project処理はlocalで行われ、project運営serverへ
意図的にuploadしません。

private、購入品、顧客、機密、第三者のmodelは添付しません。Terminal出力と
screenshotからuser名、home path、account情報、serial number、非公開filenameを
削除します。変更したtester ZIPを再配布せず、正確なtagへlinkしてください。

security上の問題は公開投稿を使わず、非公開の
[Report a vulnerability](https://github.com/Ponkichi0718/ChromaMatter/security/advisories/new)
から報告します。

source launcherはDeveloper ID署名・Apple公証済みappではありません。表示versionは
`0.8beta`のままで、Intel Macは対象外です。正式supportされたmacOS Releaseでは
ありません。Windows安定版とWindows Flat Four Test 3は別downloadです。
