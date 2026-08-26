# ChromaMatter macOS Alpha テスト案内

協力ありがとうございます。これは、**Apple Silicon / macOS 15以降**向けの
独立したtest経路です。

## 推奨経路：Source-backed App Alpha 2

Apple Silicon／macOS 15以降で、通常の`.app`としてFinderから起動できます。
ただしPythonなどを内蔵した自己完結版ではなく、初回にTerminalで検証済み環境を
準備するsource-backed版です。

**[`ChromaMatter-0.8beta-macos-source-app-alpha2.zip`をダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-app-alpha2/ChromaMatter-0.8beta-macos-source-app-alpha2.zip)**
します。GitHub prerelease
[#377168223](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-app-alpha2)は
`2026-08-26T13:33:38Z`に、下記の正確なtag／source commitから公開しました。

公開assetの固定identityは次のとおりです。

- source commit: `34e7ebdc3ec7dae6ad831b5119d574a656b105b0`
- ZIP size: 217,943,261 bytes
- ZIP SHA-256:
  `C112396513B0EA21CD867ED016E2D5282F830235E3EBF324E45E3B4FDB647989`
- detached checksum asset: `SHA256SUMS-macos-source-app-alpha2.txt`、115 bytes、
  SHA-256
  `8152D72AD978246D8B41BC1A64B2855897CBD43BAE7E36402192EF3883595129`

exact-tag run
[#32974429065](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32974429065)は
成功しました。公開後に両assetを未認証で再downloadし、正確なsizeとSHA-256の一致を
確認しました。公開ZIPをfresh extractionし、外側package 260 files、DemoData正確な
15 files／10 payloads／236,274,418 payload bytes、app 238 files／native runtime 0／
上記source commitの監査がすべて成功しました。Alpha 1は
[変更しない過去のRelease](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-app-alpha1)として
残します。

1. 上の正確なAlpha 2 ZIPをdownloadし、同じReleaseページの
   `SHA256SUMS-macos-source-app-alpha2.txt`と照合します。
2. [英語の導入・10分テスト手順](MACOS_SOURCE_APP_TESTING_EN.md)を読みます。
3. ZIP全体を展開し、`ChromaMatter Source Alpha.app`をControl-clickして
   **「開く」**を選びます。
4. launcherに公式Python 3.13.14とhash-lock済み依存関係を検証・導入させます。
   Installer完了後はTerminalへ戻ってReturnを押し、Pythonが見つからない場合だけ
   launcherを開き直します。
5. 同梱する公開4色GLBで確認し、結果を報告します。

公開fixtureの`ChromaMatter-Public-Four-Color-Test.glb`と`DemoData/`はappと
同じfolderに入っています。DemoDataは安定版r32.2の正確な15-file setです。同梱する
7件の3MFはFull Spectrum例だけで、Flat Four出力の証拠ではありません。再出力前に
実際に黒を入れるF slotを選び、**Weak Black 5–25%**を有効にしてください。Hi3D由来の
part名は見た目の領域と一致しない場合があり、multipartの閉立体化は別inputで失敗し得る
不安定なbeta機能のままです。従来の`.command`版は
[日本語guide](MACOS_ALPHA_TESTING_JA.md)から引き続き利用できます。

programming知識、printer、有料AI account、private modelは不要です。初回のみ
数百MB程度のdownloadがあり、数分かかる場合があります。2回目以降はlocal環境を
再利用します。

## 重要：自己完結型appではありません

上のdownloadはFinderで起動できる`.app`ですが、Python runtimeや第三者native
libraryは内蔵していません。初回にTerminalが開き、公式Python 3.13.14と
hash-lock済み依存関係を本人のMacへ準備します。**自己完結型の事前build appは
まだ未公開です。** 153件のMach-Oについてsource／build／再link根拠が未解決で、
`diagnostics` artifactはapplicationではありません。

Alpha 2 source commit `34e7ebd...`は
[PR #20](https://github.com/Ponkichi0718/ChromaMatter/pull/20)でmerge済みです。PR CI
[#32972636265](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32972636265)／
[#32972636277](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32972636277)、
main CI
[#32973212994](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32973212994)／
[#32973213199](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32973213199)、
manual package run
[#32973571220](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32973571220)は
成功しました。exact-tag run #32974429065と公開後の未認証download監査も上記のとおり
成功しています。

## 結果を投稿

成功・一部成功、setupの質問、一般的な感想は
[macOS Alpha Testing discussion #9](https://github.com/Ponkichi0718/ChromaMatter/discussions/9)へ
投稿します。

```text
全体結果: 成功 / 一部成功
test経路: Source-backed App Alpha 2
ZIP: ChromaMatter-0.8beta-macos-source-app-alpha2.zip
source commit（SOURCE_COMMIT.txt）:
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
