# ChromaMatter macOS Source Tester Alpha 協力テスト手順

これは、**Apple Silicon / macOS 15以降**向けの簡易テスト手順です。
ChromaMatterの表示versionは`0.8beta`のままです。

## 現在使えるもの

固定source tag `v0.8beta-macos-source-alpha1`から、**Source Tester Alphaを
今すぐ試せます**。

**[Source Tester AlphaのZIPをダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-alpha1/ChromaMatter-0.8beta-macos-source-alpha1.zip)**

対応する[tag／Releaseページ](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-alpha1)に、
`SHA256SUMS-macos-source-alpha1.txt`として正しいSHA-256を掲載します。

これは案内付きランチャーを含むsource codeです。完成済み`.app`のZIPでも、正式な
macOS Releaseでもありません。事前buildしたapplicationは、253件のMach-Oについて
source／build／再link根拠の確認が残っているため、引き続き未公開です。GitHub
Actionsの名前に`diagnostics`を含むartifactは診断reportであり、applicationでは
ありません。

source launcherはMacと導入fileを検証し、必要なら公式Python 3.13.14を導入し、
hash-lock済み依存関係をテスター本人のMacへ取得して、self-test後にsourceから
ChromaMatterを起動します。この経路は、事前build appの配布保留を解除したり
迂回したりするものではありません。

## 必要な環境

- M1、M2、M3、M4以降のApple Silicon Mac（Intel Macは対象外）
- macOS 15以降
- 初回setup時のinternet接続
- 初回のみ数百MB程度のdownloadと数分程度のsetup時間の目安
- Mac仕様と個人情報を除いたTerminal出力を報告できること

programming知識、printer、有料AI account、private modelは不要です。最初から
大切なmodelを使用しないでください。

## 初回setup

1. 上のsource ZIPをdownloadし、tag／ReleaseページのSHA-256と比較します。
   Terminalへ`shasum -a 256 `と最後のspaceまで入力し、ZIPをdragしてReturnを
   押します。一致しない場合は中止します。
2. FinderでZIPを完全に展開し、展開したfolderを開きます。
3. `START_MACOS_SOURCE_ALPHA.command`をControl-clickし、**「開く」**を選びます。
   確認画面が出た場合も「開く」を選びます。Gatekeeper全体は無効にしません。
4. Python 3.13.14がない場合、launcherは公式installerをdownloadし、SHA-256を
   検証してAppleのInstallerで開きます。表示に従ってinstallを完了します。
   Macの管理者passwordを求められる場合があります。
5. 元のTerminalへ戻り、Returnを押します。Pythonが見つからないmessageが出た
   場合だけ、Terminalを閉じて`.command` fileをもう一度開きます。
6. Terminalを閉じずに待ちます。launcherは
   `~/Library/Application Support/ChromaMatter Source Alpha/`へtest環境を作り、
   hash-lock済み依存関係だけを取得し、必須self-test後にChromaMatterを開きます。

初回はPythonと依存関係を取得するため時間がかかります。2回目以降は検証済みの
local環境を再利用します。テスト中は展開したsource folderを残し、同じ`.command`
fileから起動してください。

Mac種類、macOS version、Python download、SHA-256、依存lock、self-testのどこかで
止まった場合は、Terminalのmessageを報告してください。Terminalで`sudo`を使う、
lock fileを書き換える、失敗したpackageを未固定版へ差し替える操作はしません。

## 10分の基本テスト

launcherは次の場所へ小さなCC0 test modelを生成します。

`~/Library/Application Support/ChromaMatter Source Alpha/TestData/ChromaMatter-Public-Four-Color-Test.glb`

赤・青・白・黒の閉じたbox 4個だけで、character、brand、texture、外部resource、
private metadataは含みません。

1. 自動self-testが成功し、main windowが30秒以上操作できることを確認します。
2. 日本語と英語を切り替え、主要buttonとlabelが読めることを確認します。
3. **OBJ / GLBを開く**から上記の`ChromaMatter-Public-Four-Color-Test.glb`を開きます。
4. 回転・pan・zoomを行い、4色のboxが表示されることを確認します。
5. **Full Spectrum（混色）**を選び、previewが表示されることを確認します。
6. **Flat 4 Colors**を選び、F5以降の混色stateを使わずF1～F4だけになることを
   確認します。
7. **Manual Editing**でFillを1か所に使い、UndoとRedoを確認します。
8. 3MFを書き出します。このclosed modelは成功する想定です。安全に拒否された場合も
   test上は失敗として記録し、誤解を招く不完全3MFが残らないことを確認します。
9. projectを保存して終了し、`.command`から再起動して読み込みます。mode、F1～F4、
   手修正が維持されることを確認します。
10. 任意で、3MFをSnapmaker Orcaから**projectとして**開きます。基本software
    testでは印刷しません。

各項目を「成功・失敗・未確認」で記録します。60秒以上進捗が見えない場合は、
待った時間を記録してそのtestを止めてください。

## 既知のalpha制限

- 通常のdrag-and-drop Mac applicationではなく、sourceからのtestです。
- source launcherはDeveloper ID署名・Apple公証済みappではないため、
  Control-clickから「開く」が必要になる場合があります。
- Intel MacおよびmacOS 14以前は対象外です。
- Snapmaker Orcaは手動で開く必要がある場合があります。
- 最初のMac testではpen pressureを対象外とし、mouseまたはtrackpadを使用します。
- multipart、破損、圧縮、animationなど一部のmodelは安全に拒否される場合があります。
- 色精度やprinter安全性は、このsoftware testだけでは確認できません。

## 報告方法

- 成功・一部成功、setupの質問、一般的な感想は
  [macOS Alpha Testing discussion](https://github.com/Ponkichi0718/ChromaMatter/discussions/9)へ投稿します。
- 再現するcrash、停止、表示／入力、読込、色割当、出力、文書の問題は、1件ずつ
  [macOS alpha Issue form](https://github.com/Ponkichi0718/ChromaMatter/issues/new?template=macos_alpha_report.yml)で報告します。

source tag `v0.8beta-macos-source-alpha1`、Mac model／chip／RAM、macOS version、
launcher／self-test結果、問題が起きた手順、期待した結果、実際の結果、個人情報を
除いたself-test JSONまたはTerminal末尾を記載してください。source commitは分かる
場合だけで構いません。windowが開かなかった場合はTerminal出力が最も重要です。

## privacyと通信

初回setupは、検証済みの公式Python 3.13.14 installerとhash-lock済み依存関係を
取得するため、公式Python download先とPython package indexへ接続します。その後、
ChromaMatterはOBJ、GLB、画像、project、3MFをMac内で処理し、project運営serverへ
意図的にuploadしません。

private modelを添付しないでください。購入品、顧客、機密、第三者のmodelは絶対に
uploadしません。Terminal出力、project、screenshotにはuser名、home path、非公開
filename、account情報が入る場合があるため、投稿前に削除します。security上の問題は
公開Issueではなく、非公開の
[Report a vulnerability](https://github.com/Ponkichi0718/ChromaMatter/security/advisories/new)
を使います。

Source Tester Alphaを改変ZIPとして再配布したり、別serviceへ転載したりしないで
ください。正確なsource tagへlinkしてください。ChromaMatter sourceは
GPL-3.0-or-laterで、第三者componentにはそれぞれの条件が適用されます。
