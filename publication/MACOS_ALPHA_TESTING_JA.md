# ChromaMatter macOS alpha 協力テスト手順

これは、Windows安定版およびWindows Flat Four Test 3とは別の
**Apple Silicon / macOS 15以降 / Developer ID未署名・未公証
（ad-hoc署名）alpha**です。
表示versionは意図的に`0.8beta`のままです。

## テスト前の確認

- M1、M2、M3、M4以降のApple Silicon MacとmacOS 15以降を使用します。
- repositoryの`macOS Apple Silicon Developer ID unsigned, unnotarized alpha`
  GitHub Actionsで、所有者がテスター成果物の作成を明示的に有効にした
  実行結果だけを取得します。Mac用のネイティブ構成・対応ソース・再リンク
  監査が完了するまでは、この成果物作成自体がCIで遮断されます。
- 成果物内の`MACOS_ALPHA_COMPLIANCE_NOTICE_JA.txt`を先に読みます。このalpha
  を再配布したり、別のダウンロード先へ転載したりしないでください。
- 非公開、購入品、顧客、第三者のモデルは自分のMac内だけに置きます。
  報告のためにモデル本体を渡す必要はありません。

## 初回起動

1. 内側のZIPを完全に展開します。archive内からappを直接起動しません。
2. 同梱されたSHA-256とdownloadしたZIPのSHA-256が一致することを確認します。
3. Finderから`ChromaMatter-macOS-Alpha.app`を開きます。
4. このalphaにはad-hoc署名がありますが、Developer ID署名とApple公証は
   ありません。そのため初回のdouble-clickがmacOSに止められる場合が
   あります。Finderのcontext menuにある「開く」、または「システム設定 >
   プライバシーとセキュリティ」の個別app許可を使います。Gatekeeper全体を
   無効にしないでください。
5. titleとiconでmacOS alphaであることを確認します。

Finderの「開く」と個別app許可でも起動できない場合に限り、SHA-256確認後、
Terminalで次を実行できます。`sudo`は不要です。

```bash
xattr -dr com.apple.quarantine "/path/to/ChromaMatter-macOS-Alpha.app"
open "/path/to/ChromaMatter-macOS-Alpha.app"
```

## 確認してほしい順番

各項目を「成功・一部成功・失敗」で記録してください。

1. 日本語で起動・終了し、次に英語でも起動・終了する。
2. 権利上問題のない小さな頂点color OBJを開く。
3. 権利上問題のない小さなstatic color GLBを開く。
4. 元モデル色、Full Spectrum、Flat Fourのpreviewを確認する。
5. 回転・pan・zoomと、小さなManual Editingのbrush/fill操作を行う。
6. その編集をUndo/Redoする。
7. 適したtest modelで閉立体化し、fail-closed警告があれば残す。
8. 3MFを書き出し、Snapmaker Orcaから手動で開く。
9. ChromaMatter projectを保存し、終了・再起動後に読み込む。
10. 可能なら、より大きなGLBでmemory不足やUI停止を確認する。

最初のalphaではSnapmaker Orcaの自動起動がすべてのMacで動かない可能性が
あります。書き出した3MFをOrcaから手動で開いた結果でも構いません。
pen pressureは最初のmacOS確認対象外で、mouseまたはtrackpadを想定します。

## 報告方法

repositoryの**macOS alpha report** Issue formを使います。Mac model/chip、
macOS version、成果物のsource commit、個人情報を除いたscreenshotやterminal
出力を記載してください。user名、home path、account情報、公開できないmodel名
は削除します。private modelは添付せず、formatとおおよそのsizeだけを書きます。

CI self-testとGUI起動smokeだけでは、Retina layout、実際のWindowServer/OpenGL、
入力操作、Orca連携、実機印刷を確認できません。これらは協力テスターの報告を
確認材料にします。
