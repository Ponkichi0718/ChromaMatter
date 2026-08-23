# ChromaMatter 0.8beta (r32)

[English](README_EN.md)

ChromaMatterは、頂点カラー付きOBJまたは対応GLBの色を4本のフィラメントへ割り当て、Snapmaker Orcaで確認できる3MFを作るWindowsデスクトップアプリです。独立したプロジェクトであり、TripoAI、Hi3D AI、Snapmaker、OpenAIその他の第三者による公式・提携製品ではありません。

## はじめ方

1. ZIPを通常のフォルダーへすべて展開します。
2. `START_CHROMAMATTER.cmd`または`ChromaMatter.exe`を起動します。
3. OBJ／GLBを開き、F1～F4、混色数、サイズ、形状を確認して3MFを書き出します。
4. 3MFをSnapmaker Orcaで**プロジェクトとして開き**、ツール順、材料、スライスプレビューを確認してから印刷します。

Windowsが保護画面を表示した場合は、公式ReleaseのSHA-256と、署名が提供されている場合はその署名情報を先に確認してください。確認できないファイルの警告を無条件に回避しないでください。

## 対応範囲と注意

- Windows x64向けです。
- OBJは`v x y z r g b`形式の頂点カラーを想定します。
- GLBは静的な埋込baseColor／`COLOR_0`を対象とします。animation、skin、morph、Draco、meshopt、BasisU、外部URIには対応しません。
- 画面色と実際の造形色は一致を保証しません。同じ材料・造形条件の比較チャートとテスト印刷で確認してください。
- 「閉立体化」は証明できる条件だけを処理します。表示できるモデルでも、自動修復や印刷可能性を保証するものではありません。
- 大規模モデルの準備、閉立体化、手動修正には時間とメモリが必要です。

## プライバシー、不具合報告

モデル処理はPC内で行い、プロジェクト運営者のサーバーへ意図的にアップロードしません。詳しくは[PRIVACY.md](PRIVACY.md)を参照してください。

不具合報告では私有モデルを添付せず、ChromaMatterのバージョン、Windowsのバージョン、再現手順、エラー文を共有してください。必要な場合は、共有用に新しく作成した最小モデルを使用してください。

## ライセンスとソース

ChromaMatter本体は`GPL-3.0-or-later`です。本文は[LICENSE.txt](LICENSE.txt)、第三者の条件と通知は[licenses](licenses/)にあります。このバイナリに対応する完全なソースの取得先は[licenses/SOURCE_OFFER_JA.txt](licenses/SOURCE_OFFER_JA.txt)を確認してください。

パッケージ内ファイルのSHA-256は`SOFTWARE_PACKAGE_SHA256.txt`、Release全体のSHA-256は同じReleaseに置かれる`SHA256SUMS-r32.txt`を正本とします。
