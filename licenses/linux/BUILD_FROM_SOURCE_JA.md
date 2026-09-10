# ChromaMatter Linux x86_64 technical alpha：ソースからのビルド

この文書は、Linux technical alpha と同時に配布された正確なソース
コミットおよび依存関係・ソース manifest にだけ適用されます。別の
コミット、wheel、アーカイブの確認済みを意味しません。

## 再現用の基準環境

- Ubuntu 22.04 x86_64（glibc 2.35）
- CPython 3.13.14
- `requirements-build-linux-x86_64.lock` に記録された正確なハッシュ
- staged source payload が指定するコンパイラ・ビルドツール、および
  GNU binutils、`file`、`patchelf`、`realpath`
- `BUILD_LINUX_X86_64.sh` に記載された日本語フォントパッケージ

## 再ビルド手順

1. 展開・取り込み前に、すべての source payload を
   `SOURCE_PAYLOADS.json` と外部 checksum に照合します。
2. ChromaMatter の Git bundle を
   `CORRESPONDING_SOURCE_MANIFEST.json` の commit へ復元し、記録された
   submodule と native source もすべて復元します。
3. 空の CPython 3.13.14 環境を作り、Linux lock とファイル名・SHA-256
   が一致する wheel だけを `--require-hashes --only-binary=:all:` で
   インストールします。
4. リポジトリ直下から、未使用の source、Python prefix、output
   directory を指定して `BUILD_LINUX_X86_64.sh` を実行します。
5. 出力された one-folder application を保持し、
   `AUDIT_LINUX_APP.sh`、packaged self-test、native/render self-test、
   日本語・英語 UI smoke を実行します。
6. その正確な bytes から Linux inventory、component map、SPDX SBOM、
   corresponding-source manifest を再生成します。古い build の証拠は
  流用できません。

native library を置き換えた場合は `RELINKING_JA.md` の確認に加え、
上記の clean build と packaged-runtime 検証をすべてやり直します。
