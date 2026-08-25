# ChromaMatter 0.8beta (r32.2 Flat Four Test 3)

[English](README_EN.md)

ChromaMatterは、頂点カラー付きOBJまたは対応GLBの色を4本のフィラメントへ割り当て、Snapmaker Orcaで確認できる3MFを作るWindowsデスクトップアプリです。独立したプロジェクトであり、TripoAI、Hi3D AI、Snapmaker、OpenAIその他の第三者による公式・提携製品ではありません。

## はじめ方

1. ZIPを通常のフォルダーへすべて展開します。
2. `START_CHROMAMATTER.cmd`または`ChromaMatter.exe`を起動します。
3. OBJ／GLBを開き、F1～F4、混色数、サイズ、形状を確認して3MFを書き出します。
4. 3MFをSnapmaker Orcaで**プロジェクトとして開き**、ツール順、材料、スライスプレビューを確認してから印刷します。

このTest 3 packageには`DemoData`を同梱しません。利用する権利のあるmodelだけを開き、
私有のsource modelを公開issueへ添付しないでください。

公開済み安定版r32.2 packageだけの過去記録です（このTest 3 packageではありません）:
同梱の`DemoData`は閉立体化・3MF出力の成功を確認しています。その結果はTest 3や
ほかの入力fileを検証するものではありません。

## Flat Four Test 3

- Flat Fourは白を一律に除去しません。黒い線に隣接する目の白など、意味のある小さな
  白は白いtargetとして保持し、黒い細部も保持します。
- 肌などの滑らかな有彩色面に焼き込まれた、小さく確度の高い白／灰色の照明斑だけを、
  その境界で使われている有彩色F slotへ保守的にまとめます。
- 保持された白が印刷対象総面積の**0.01%以上**なら、自動提案で白に近いfilamentを
  1 slot確保します。0.01%未満の白は吸収せずに残しますが、それだけでは白spoolを
  強制しないため、選択済みF1～F4の最寄色へ割り当てられる場合があります。
- 4つの物理F1～F4 slotと3MF state schemaは常に維持します。必要な白が残らない
  modelでは実際のpaint IDが3色だけになる場合があります。Manual Editingを優先し、
  Full Spectrumの動作は変更しません。

**重要な制限:** これは意味認識AIではありません。暗い線、折り目、part境界のない
滑らかな肌色面に囲まれた小さな白は、焼付ハイライトと誤認して吸収する場合があります。
再利用できる隣接情報がない50万面超のopen meshでは、この自動補正だけをfail-closedで
skipします。multipartの閉立体化とpart別3MFも入力依存のbeta機能です。このexact
Test 3 packageのphysical printer validationは未実施です。

Windowsが保護画面を表示した場合は、公式ReleaseのSHA-256と、署名が提供されている場合はその署名情報を先に確認してください。確認できないファイルの警告を無条件に回避しないでください。

## 対応範囲と注意

- Windows x64向けです。
- OBJは`v x y z r g b`形式の頂点カラーを想定します。
- GLBは静的な埋込baseColor／`COLOR_0`を対象とします。animation、skin、morph、Draco、meshopt、BasisU、外部URIには対応しません。
- Hi3D系分割GLB対応はβ・非公式です。パーツ識別用`COLOR_0`は、exporter、node、material、共通texture、既知paletteの証拠がすべて一致した場合だけ除外し、それ以外の通常の作者指定色は保持します。
- パーツ化モデルの閉立体化はまだ不安定です。このTest 3 packageには`DemoData`を同梱せず、他の分割ファイルでは閉立体化または3MF出力に失敗することがあります。この互換性が未完成であることが、ChromaMatterを`0.8beta`としている理由の一つです。
- 対応する分割GLBでは元partを別々に閉立体化し、別part同士を溶接せず、結合3MFと任意のpart別独立3MFへ出力できます。非対応・曖昧なfileは安全停止し、すべてのHi3D出力との互換性は保証しません。
- 画面色と実際の造形色は一致を保証しません。同じ材料・造形条件の比較チャートとテスト印刷で確認してください。
- 「閉立体化」は証明できる条件だけを処理します。表示できるモデルでも、自動修復や印刷可能性を保証するものではありません。
- 大規模モデルの準備、閉立体化、手動修正には時間とメモリが必要です。

## プライバシー、不具合報告

モデル処理はPC内で行い、プロジェクト運営者のサーバーへ意図的にアップロードしません。詳しくは[PRIVACY.md](PRIVACY.md)を参照してください。

不具合報告では私有モデルを添付せず、ChromaMatterのバージョン、Windowsのバージョン、再現手順、エラー文を共有してください。必要な場合は、共有用に新しく作成した最小モデルを使用してください。

## ライセンスとソース

ChromaMatter本体は`GPL-3.0-or-later`です。本文は[LICENSE.txt](LICENSE.txt)、第三者の条件と通知は[licenses](licenses/)にあります。このバイナリに対応する完全なソースの取得先は[licenses/SOURCE_OFFER_JA.txt](licenses/SOURCE_OFFER_JA.txt)を確認してください。

package内fileのSHA-256は`SOFTWARE_PACKAGE_SHA256.txt`、Test 3 Release全体の
SHA-256は、同じReleaseに公開された時点の
`SHA256SUMS-r32.2-flat4-test3.txt`を正本とします。Test 3のrelease gate完了までは、
immutableな公開済み`v0.8beta-r32.2` packageと`SHA256SUMS-r32.2.txt`を使用して
ください。
