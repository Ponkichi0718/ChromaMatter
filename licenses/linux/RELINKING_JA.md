# ChromaMatter Linux x86_64 technical alpha：native library の置換・再リンク

ChromaMatter は PyInstaller one-folder application として配布します。
native library は `_internal` 配下の独立した ELF file のままで、単一の
静的リンク済み実行ファイルには変換しません。ただし、置換可能な構成
であることと、実際に置換を検証済みであることは別です。

1. application directory を復元可能な形で複製します。
2. `BINARY_COMPONENT_MAP.json` で対象 library を確認します。owner または
   corresponding source が未解決の file は置換対象にしません。
3. staged corresponding source から x86_64 shared library をビルドし、
   command、compiler、設定、SHA-256 を記録します。
4. 対応付けられた shared object だけを置換し、期待される SONAME または
   package 内 symlink chain を維持します。absolute RPATH/RUNPATH は追加
   しません。
5. application の `_internal` を `LD_LIBRARY_PATH` に指定し、
   `readelf -h`、`readelf -d`、`patchelf --print-rpath`、`ldd` を実行します。
   依存先は application 内または通常の system library root だけに解決
   されなければなりません。
6. packaged self-test、Linux native/render self-test、日本語・英語 UI
   smoke、および置換した library を使用する機能を実行します。
7. inventory を再生成し、意図した file・symlink・hash 以外が変化して
   いないことを確認します。

Qt、GEOS、GMP、libgomp、Tcl/Tk など LGPL の対象となる library は、
実際に置換できる状態を保つ必要があります。owner、source、SONAME、
symlink chain、検証手順のいずれかが不足する場合、Linux 配布ゲートは
必ず blocked のままにします。
