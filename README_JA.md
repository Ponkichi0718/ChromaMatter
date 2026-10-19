# Snapmaker Orca with CM

**色調整・部位カット・材料設定を、Orcaの中で。**

[English](README.md) · [公式サイト](https://chromamatter.app/) · [ダウンロード・導入案内](https://chromamatter.app/download)

## Snapmaker U1 Innovation Fund 受賞

**Ponkichi0718** の **ChromaMatter -AI Model Print Studio** が、**Snapmaker U1 Innovation Fund 第1期（2026年）**の最終結果で **第3賞（賞金1,500米ドル）**を受賞しました。

[公式結果](https://www.snapmaker.com/innovation-fund) · [公式フォーラムの発表](https://forum.snapmaker.com/t/built-by-makers-meet-the-20-snapmaker-u1-innovation-fund-winners/43667/1)

応募時は独立アプリでしたが、現在は Snapmaker Orca に統合した実験版 **Orca with CM** として開発を続けています。受賞は応募したプロジェクトに対するもので、現在の実験版の検証完了や動作保証を意味するものではありません。

## ダウンロード — dev3-R8 実験版

Snapmaker Orca 2.4.0をベースにした非公式改良版です。**dev3-R8は開発中の実験版**で、すべてのモデルや印刷条件での動作を保証するものではありません。

| Windows | macOS | Linux |
| --- | --- | --- |
| [ZIPをダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/Snapmaker-Orca-CM-dev3-R8-Windows-x64.zip) | [アプリZIPをダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/CM-dev3-R8-macos-arm64-app.zip) | [tar.gzをダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/Snapmaker-Orca-CM-dev3-R8-Linux-x86_64.tar.gz) |
| x64 | Apple Silicon・macOS 15以降 | x86_64・Ubuntu 22.04 |

[更新内容・チェックサム・対応ソース](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/cm-orca-dev3-r8-20261013)

- **原本を残してください。** コピーで作業し、プロジェクトは別名保存してください。印刷前にスライス結果を確認してください。
- **Windows版は既存のCM版と設定保存先を共有します。** 別フォルダーに展開しても設定は分離されません。試す前に設定をバックアップしてください。
- **Mac版:** ad-hoc署名のみです。Developer ID署名・Apple公証はありません。Intel Macには対応していません。
- CM専用のプロジェクト情報には互換性のあるCM版が必要です。通常のOrcaや古いCM版で同じように扱えるとは限りません。

## 主な機能

- **色調整:** Full Spectrum・CMY・Flat Color、ブラシ編集、色の置き換え、陰影調整。
- **カット:** 平面の移動・回転、任意のX/Y範囲制限、切断面と一体型の凸・穴コネクター。
- **保護・ブリッジ:** つながった表面を選ぶ保護ブラシ、保護範囲表示、2点を結ぶ円柱・四角のブリッジ。
- **プレート別の材料処理（対応するFlat Colorプロジェクト）:** プロジェクト全体の色候補が多くても、そのプレートで実際に使う物理材料が4種類以内ならスライスできます。実際に5種類以上を使うプレートは手動調整が必要です。自動的な色の統合は行いません。
- **編集時の待ち時間対策:** 検証済みの元データ圧縮結果を再利用し、繰り返しのバックアップ処理を軽くします。初回など、キャッシュがない場合は圧縮処理が必要です。

保護補助は形状を扱うもので、部位の意味を自動判定する機能ではありません。適用前に保護範囲と切断する側を確認してください。複雑な形状では処理に失敗する場合があります。

## 検証範囲と注意

ビルド・起動確認や個別の回帰試験と、実モデルの操作・印刷は別です。**今回のMac・Linux版では、GUI操作、実モデルの編集・カット、スライス、印刷は未検証です。** Windowsでの結果は、他OSで同じ動作を保証しません。R8のGUI・印刷動作を網羅的に検証したものでもありません。

表示色は予測であり、校正済みの印刷色を保証するものではありません。モデル・フィラメント・プリンター・設定によって結果が変わります。実験版として、実際の出力を確認してご利用ください。

## 対応ソースと技術の背景

[Windows対応ソースZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/Snapmaker-Orca-CM-dev3-R8-Windows-source.zip) · [Linuxビルド補足](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/CM-dev3-R8-Linux-Source-Supplement-20261013.zip)

この版の対応ソース・ビルド情報は[dev3-R8リリース](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/cm-orca-dev3-r8-20261013)で案内します。[R8のnative/helperビルド入力](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/cm-orca-dev3-r8-build-inputs-20261012)はソース資料で、アプリやオフラインSDKではありません。Orca版の再現には版ごとの対応ソースを使用してください。リポジトリ内の旧単体版ソースは過去の記録です。

**ChromaMatterは、このOrca統合版の基礎となった色処理技術です。** 以前の単体アプリは開発の経緯として残し、ここでは別製品のダウンロードとして案内しません。過去のソース・記録・ライセンスは保持し、今回のOrca版の検証結果とは区別します。

[ライセンス](LICENSE) · [第三者ライセンス](licenses/) · [セキュリティ](SECURITY.md)
