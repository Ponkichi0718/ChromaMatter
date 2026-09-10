# macOS LGPLライブラリ差替え・再リンク手順（DRAFT）

製品表示version：**0.9**

対象：Apple Silicon、macOS 15以降
状態：**実機ボランティアMacで未検証・配布承認ではありません**

ChromaMatterはPyInstallerの`.app` bundleとして作成します。Python wheelには、
PyMeshLab内のQt、Shapely内のGEOS、上流PyTetWild arm64 wheel内のGMPなど、
LGPL対象の動的libraryが含まれる場合があります。各libraryには固有の条件が
残ります。この文書は予定している差替え経路を示しますが、現在のalphaが
検証に合格したことを示しません。

## 外部テスト開始前に必要なもの

配布物には次を含める必要があります。

- 最終`.app`のinventoryから生成した正確な`BINARY_COMPONENT_MAP.json`と
  `SBOM.spdx.json`
- LGPL原文とwheelに付属するすべてのlicense・notice
- 実際に同梱したLGPL libraryに対応する完全なsourceとbuild情報
- 最終bundle内の実pathとApple Silicon実機での差替え成功結果を反映した
  この手順書

最終pathは`BINARY_COMPONENT_MAP.json`を正とします。このDRAFTやWindows版の
pathから推測してはいけません。

## 予定している差替え手順

1. `ChromaMatter-macOS-Alpha.app`の未変更copyとSHA-256を保存します。
2. Apple Silicon用の互換LGPL libraryを入手またはbuildします。公開ABI、
   install name、architecture、最小macOS versionをcomponent mapの元libraryと
   合わせます。
3. `.app`を別のtest場所へcopyし、`Contents/Frameworks`内でcomponent mapに
   記録された対象`.dylib`またはframeworkだけを置き換えます。
4. install nameが異なる場合はAppleの`install_name_tool`を使い、inventoryに
   記録された`@rpath`、`@loader_path`またはframework identityへ合わせます。
   開発PC固有の絶対pathを追加してはいけません。
5. 変更したtest bundleをlocalで再署名します。

   ```sh
   codesign --force --deep --sign - ChromaMatter-macOS-Alpha.app
   codesign --verify --deep --strict --verbose=2 ChromaMatter-macOS-Alpha.app
   ```

6. 変更後bundleに対して、repositoryのpackaged self-test、日本語・英語UI
   smoke、app audit、app inventory生成を再実行します。
7. 新旧inventoryを比較します。対象libraryと依存署名は変化し得ますが、
   無関係な実行byteが変化してはいけません。
8. Gatekeeperの確認が出る場合はFinderの「開く」を使用します。
   Gatekeeper全体を無効化してはいけません。

## 現在の制限

- bundleはad-hoc署名で、Developer ID署名・Apple公証済みではありません。
- LGPL codeがwheelへ独立差替えできない形で埋め込まれている場合は、app全体
  のsource buildを保守的な代替経路とします。
- Qt plugin、GEOS/Shapely ABI、PyTetWildのGMP loader pathは、最終byteでの
  実機検証が必要です。
- appが起動するだけでは差替え証拠になりません。変更したlibraryが実際に
  loadされ、関係する機能testが成功する必要があります。

同じsource commit・app inventory SHA-256を指定した
`DISTRIBUTION_APPROVAL.json`が`approved`になるまでは、この文書を技術DRAFT
として扱い、appを再配布しないでください。

この文書は技術上の安全策であり、法律相談ではありません。
