# ChromaMatter 0.9

The downloads below are the existing packages from the [official site](https://chromamatter.app/download). This update synchronizes the repository with the published Windows application source and prepares the same application files for GitHub distribution. It adds no new experimental features and does not rebuild the applications.

下記は[公式サイト](https://chromamatter.app/download)で配布中の0.9と同じファイルです。公開Windows版に対応するソースをリポジトリへ同期し、既存アプリをそのままGitHubへ掲載するための更新です。実験機能の追加やアプリの再ビルドは行っていません。

## Applications / アプリ

| Platform / OS | Package / 配布物 | Scope / 対象 |
| --- | --- | --- |
| Windows 64-bit | [ChromaMatter-0.9-win64-app.zip](https://chromamatter.app/downloads/ChromaMatter-0.9-win64-app.zip) | ChromaMatter 0.9 |
| macOS | [ChromaMatter-0.9-macos-arm64-app.zip](https://chromamatter.app/downloads/ChromaMatter-0.9-macos-arm64-app.zip) | Technical alpha; Apple Silicon, macOS 15+ |
| Linux x86_64 | [ChromaMatter-0.9-linux-x86_64.tar.xz](https://chromamatter.app/downloads/ChromaMatter-0.9-linux-x86_64.tar.xz) | Technical alpha; Ubuntu 22.04+ |

## Corresponding source / 完全対応ソース

Use the separate source bundle for the application and platform you downloaded. It includes the relevant application and third-party source materials; it is not required merely to run the application.

対応ソースはOSごとの別配布です。使用するアプリと同じOSのbundleを選んでください。アプリと依存部品の対応ソースを含みますが、アプリを起動するだけなら取得は不要です。

| Platform / OS | Source bundle / ソースbundle |
| --- | --- |
| Windows | [ChromaMatter-0.9-complete-corresponding-source.zip](https://chromamatter.app/downloads/ChromaMatter-0.9-complete-corresponding-source.zip) |
| macOS | [ChromaMatter-0.9-macOS-corresponding-source.zip](https://chromamatter.app/downloads/ChromaMatter-0.9-macOS-corresponding-source.zip) |
| Linux | [ChromaMatter-0.9-Linux-complete-corresponding-source.zip](https://chromamatter.app/downloads/ChromaMatter-0.9-Linux-complete-corresponding-source.zip) |

The repository's application source corresponds to the Windows/Linux checkpoint `5059163a1a6d05e823c44323558f344ad000b580`. macOS uses `c629f428868e26f11dbcd679983ee2cd74d9c1cd`. The exact application snapshots are available as [Windows/Linux source ZIP](https://chromamatter.app/build-inputs/ChromaMatter-0.9-source-5059163-8935f8d4.zip) (518 files) and [macOS source ZIP](https://chromamatter.app/build-inputs/ChromaMatter-0.9-source-c629f42-2e185dc1.zip) (597 files). These smaller snapshots contain application source; use the complete bundles above for third-party corresponding source. Current publication documentation and the independent CI dispatcher are recorded separately. Historical 0.8 releases remain unchanged.

リポジトリのアプリソースはWindows／Linux版のcommit `5059163a1a6d05e823c44323558f344ad000b580` に対応します。macOS版は `c629f428868e26f11dbcd679983ee2cd74d9c1cd` です。アプリ本体の正確なスナップショットは、上のWindows／Linux用ZIP（518ファイル）とmacOS用ZIP（597ファイル）から取得できます。依存部品を含む完全対応ソースはOS別bundleを使用してください。現在の配布案内と独立したCI設定は別途更新しています。過去の0.8配布物は保持しています。

## Verification scope / 今回の確認範囲

The three application archives were downloaded and matched the current official catalog's sizes and SHA-256 hashes. The large corresponding-source archives' hashes are taken from that catalog; those three complete files were not downloaded again for this update. No new build, platform-native execution, GUI, slicing or print tests were performed. File identities and verification methods are listed in [publication/RELEASE_0.9.json](publication/RELEASE_0.9.json).

アプリ3種類は実際にダウンロードし、現行公式カタログのサイズ・SHA-256と一致を確認しました。大容量の完全対応ソース3種類はカタログ値を記録しており、今回全文の再ダウンロードはしていません。新規ビルド、各OS上での実行、GUI、スライス、実印刷の再検証は行っていません。ファイル情報と照合方法は[publication/RELEASE_0.9.json](publication/RELEASE_0.9.json)に記載しています。
