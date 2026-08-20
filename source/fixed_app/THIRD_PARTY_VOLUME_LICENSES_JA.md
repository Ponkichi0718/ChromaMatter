# 曲面パーツ閉立体化で使用する第三者ソフトウェア

ChromaMatter — AI Model Print Studioの曲面パーツ閉立体化は、次の第三者ソフトウェアをローカルで使用します。この処理はルールベースの形状処理であり、AIサービス、Codex、クラウドAPI、外部ネットワークには接続しません。

## PyTetWild 0.3.0 / fTetWild

- 用途：開いた曲面から四面体ボリュームを生成
- PyTetWild Pythonラッパー：Mozilla Public License 2.0（MPL-2.0）
- wheelに含まれるfTetWild：MPL-2.0
- PyTetWild：<https://github.com/pyvista/pytetwild>
- fTetWild：<https://github.com/wildmeshing/fTetWild>
- 配布物内のライセンス原文：`_internal/licenses/pytetwild/LICENSE`

実行形式を配布する場合は、MPL-2.0の原文を保持し、対象ソフトウェアのソースコードを合理的な方法で入手できるようにする必要があります。変更したMPL対象ファイルを配布するときは、その変更済みソースもMPL-2.0に従って提供します。

## tetgen 0.8.3 / TetGen 1.6.0

- 用途：外表面を保った四面体化と再帰的なパーツ分離
- tetgen Pythonラッパー：MIT License
- wheelに含まれるTetGen C++本体：GNU Affero General Public License version 3 or later（AGPL-3.0-or-later）、またはWIASの商用ライセンス
- Pythonラッパー：<https://github.com/pyvista/tetgen>
- TetGen公式ライセンスFAQ：<https://wias-berlin.de/software/tetgen/FAQ-license.jsp>
- 配布物内のMIT原文：`_internal/licenses/tetgen/LICENSE`
- 配布物内のTetGenライセンスとAGPL原文：`_internal/licenses/tetgen/tetgen-license`

MITのPythonラッパーとTetGen本体は別のライセンスです。TetGenを含む実行形式を第三者へ渡す場合は、対応する完全なソース、変更内容、ビルド・インストールに必要な情報、ライセンス表示、ソース入手方法を、適用されるAGPL条件に従って用意する必要があります。AGPL条件を採用できない用途では、WIASの商用ライセンスを検討してください。

## 配布前の注意

アプリにはこの2製品以外にも、PyMeshLab、Qt、NumPy、SciPyなど複数の依存物があります。TetGenだけを確認してもWindows配布物全体の確認は完了しません。公開前に、配布する正確なバイナリを対象として、`_internal/licenses/THIRD_PARTY_LICENSES.txt`、各依存物の原文、対応ソース、表示方法を確認してください。

この文書は実務上の整理であり、法的助言ではありません。
