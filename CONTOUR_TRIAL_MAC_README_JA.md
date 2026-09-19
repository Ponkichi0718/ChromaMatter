# ChromaMatter Orca 輪郭ガイド試験版 — Mac Apple Silicon

2026-09-20。2026-09-19 の日本語輪郭ガイド版と同じ機能ソースを、Mac 用に包装する試験版です。正式安定版ではありません。

対象は Apple Silicon、macOS 15 以降です。生成された `CM-Contour-Trial-20260920-arm64-app.zip` を Mac 上で展開し、`Snapmaker Orca with CM Test.app` を使用します。Python の別途インストールは不要です。Intel Mac 版ではありません。

ローカルの ad-hoc 署名のみで、Developer ID 署名・Apple の公証は行いません。macOS が開く操作をブロックした場合は、入手元を確認したうえで macOS の「プライバシーとセキュリティ」から個別に許可してください。

既存の専用 ChromaMatter Orca と設定を共有するため、必要な設定とモデルを事前に別名保存してください。正式版の上書き、既存 3MF の上書きは避け、新しい保存先で試してください。

5〜8 基本候補は計画用です。U1 の物理 4 本への自動グループ化は未実装で、未整理の印刷出力は停止します。輪郭切断は 1 volume / 1 instance の閉筒部位向けです。複雑な分岐や未対応 paint、ダボ、実印刷の成立を保証しません。分割後は配置を確認してください。

CI で確認するのはビルド、内包 helper の起動、署名整合、本体 CLI 起動です。Mac GUI、GPU、実モデルの色編集往復、輪郭切断、スライス、実印刷は未確認です。Windows の確認結果を Mac の確認済み結果として扱いません。

再構築用ソースは `CM-Contour-Trial-20260920-Mac-BuildInputs-r2.zip`、対応する workflow と `ci/` の 2 ファイルです。固定 upstream `Snapmaker/OrcaSlicer` の commit `5417538a1c47d64d57b0401c095f40d1bcd7c9da` に、内包 `native-ci-delta.zip` の manifest を照合して適用します。helper は同梱ソースから作成します。依存ソースは固定 upstream の取得 recipe に従います。上流全体を内包する ZIP ではありません。

workflow は手動実行のみで、標準 `macos-15` runner を 1 job 使用します。完了 ZIP と `SHA256SUMS` を一緒に保管してください。Actions artifact の保存期間は 1 日です。

ビルド入力 ZIP は公開 trial release の追加ソース asset です。Git へ binary/archive を commit せず、workflow が固定 URL と SHA-256 を照合して取得します。Git の変更は feature branch と PR を使用します。
