# Windows版のLGPLライブラリを差し替える方法

ChromaMatterはPyInstallerの**one-folder**形式です。QtとGEOSは
`ChromaMatter.exe`へ埋め込まず、別DLLとして配置します。リリースごとの正確な
場所は`BINARY_COMPONENT_MAP.json`を正とします。

## Qt 5.15.2

PyMeshLab wheel由来のQt DLLは`_internal/pymeshlab/`以下にあり、
`Qt5Core.dll`、`Qt5Gui.dll`、`Qt5Network.dll`、`Qt5OpenGL.dll`、
`Qt5Svg.dll`、`Qt5Widgets.dll`、`Qt5Xml.dll`のほか、プラグインと翻訳
ファイルを含みます。この配布ではQtのLGPL-3.0選択肢を使用します。

1. 対応ソースからABI互換のWindows x64 Qt 5.15.2一式をビルドします。
2. ChromaMatterを終了し、展開済みパッケージ全体をバックアップします。
3. 相互に互換なQt DLL一式と影響するプラグインをまとめて差し替え、構成表の
   ファイル名と配置を維持します。
4. `ChromaMatter.exe --self-test`を実行し、非公開データを使わずにGLB読込、
   メッシュ修復、3MF出力も確認します。

異なるABIやビルド条件のQt DLL・プラグインを混在させないでください。

## GEOS 3.13.1

Shapely wheel由来のGEOS本体とGEOS C API DLLは
`_internal/Shapely.libs/`以下にあります。この配布ではGEOSを
LGPL-2.1-or-laterで使用します。

1. 対応ソースからABI互換のWindows x64 GEOS 3.13.1本体とC API DLLを
   ビルドします。
2. ChromaMatterを終了してバックアップし、構成表に記載されたDLLの組を、
   期待されるファイル名のまま差し替えます。
3. `ChromaMatter.exe --self-test`とShapely/Trimeshの形状処理を確認します。

パッケージのSHA-256マニフェストは未変更の公式配布物を示します。LGPL DLLを
差し替えればハッシュが変わるのは正常です。これは完全性確認用で、実行を
ロックするものではありません。ABI非互換の差し替えは読込に失敗する可能性が
あり、変更後の組合せは無保証です。
