# ChromaMatter 公開前のライセンス・権利整理

更新日: 2026-08-20  
対象: ChromaMatter — AI Model Print Studio 0.8beta r31 のsource-only公開と、将来の実行ファイル配布

## 先に結論

TetGen が AGPL のオープンソースであることだけを理由に、「そのまま公開・配布して問題ない」とは判断できません。AGPL は利用を禁止するライセンスではありませんが、配布方法に応じたソースコード、ライセンス表示、ビルド情報などの提供義務があります。

さらに、現在の配布候補には PyMeshLab、Qt、GEOS、Python ランタイムなども関係します。そのため、TetGen だけを確認しても EXE 配布全体の確認は完了しません。

現時点の推奨順序は次のとおりです。

1. 個人データと由来不明物を除去した「ソースのみ」の公開候補を先に整える。
2. 新しい空の環境で再現できることをクリーンクローン検証する。
3. EXE は、全依存関係、対応ソース、ライセンス表示、再リンク・置換可能性を含むバイナリ配布監査が完了するまで公開しない。

これは法的助言ではありません。正式な公開、とくに企業への提案や広い範囲へのバイナリ配布の前には、ライセンスに詳しい専門家による最終確認が望まれます。

2026-08-20、project ownerは現在記録されている技術監査、ライセンス表示、既知の制約を確認したうえで、ChromaMatter r31の公開GOを出しました。このGOはproject ownerによる公開判断であり、独立した法律事務所のreview、商標登録可能性の判定、第三者意匠clearanceを完了したという意味ではありません。

## 1. TetGen の扱い

### 構成

現在確認している Python パッケージ tetgen 0.8.3 では、Python ラッパー部分は MIT License、同梱される TetGen C++ 1.6.0 本体は AGPL-3.0-or-later です。

- Python ラッパー: MIT
- TetGen C++ 本体: AGPL-3.0-or-later
- AGPL 条件が用途に合わない場合: WIAS が案内する商用ライセンスが選択肢

ラッパーが MIT であっても、実際に呼び出される TetGen 本体の AGPL 条件は消えません。

### まだ公開しない現在の個人利用

AGPL ソフトウェアを自分の PC 内だけで実行・検証すること自体は、通常、それだけで一般公開を要求するものではありません。いまの非公開開発を直ちに公開する必要がある、という意味ではありません。

一方、GitHub へソースを置く、EXE や ZIP を第三者へ渡す、限定テスターへ配布するといった行為は公開範囲や配布義務の検討対象です。ソフトの操作画面を動画で紹介することと、プログラム本体を配布することも区別します。ただし、動画に映すモデルや画像の権利確認は別に必要です。

### ChromaMatter の GPL との関係

ChromaMatter のアプリケーションコードは現在 GPL-3.0-or-later を予定しています。GNU の説明では、GPLv3 の部分と AGPLv3 の部分を組み合わせることはできますが、各部分のライセンスはそのまま残り、組み合わせ全体には AGPL 側の追加条件も関係します。

Python 拡張モジュールとの結合が法的に一つの結合作品となるかは、具体的な実装と法域を含む個別判断です。ただし GNU FAQ は、密接な動的リンクを結合作品として扱う立場を示しています。本プロジェクトでは安全側に立ち、TetGen を使用する構成を AGPL 対応が必要な構成として管理します。

### ソースのみ公開する場合

ソースのみでも、次を行います。

- ChromaMatter 本体のライセンスを明示する。
- PyTetWild/fTetWildとTetGenを曲面境界の閉立体化・再帰分割に使う依存関係として明示し、MPLのPyTetWild/fTetWild、MITのtetgenラッパー、AGPLのTetGen本体を区別して表示する。
- TetGen の機能を無効にしても基本機能が動くのか、必須なのかを README に明記する。
- TetGen をリポジトリへ複製する場合は、正確な版、著作権表示、ライセンス全文、変更内容を保持する。
- 依存先の URL だけに頼らず、公開時に使用した正確なソース版を保存できる状態にする。

ソースのみの公開はバイナリ配布より確認項目が少なく、最初の公開形態として推奨します。ただし「ソースなら無条件で自由」という意味ではありません。

### EXE を配布する場合

TetGen を含む EXE または配布フォルダーを公開する前に、少なくとも次を満たす必要があります。

- 配布バイナリに対応する ChromaMatter と TetGen の正確な対応ソースを提供する。
- ロックファイル、ビルド手順、パッチ、生成に必要なスクリプトを保存する。
- AGPL-3.0-or-later、GPL-3.0-or-later、MPL-2.0、MIT の各通知とライセンス全文を同梱する。
- アプリ内の「ライセンス」画面または同等に見つけやすい場所から通知へ到達できるようにする。
- ソースの入手方法を、配布物と同じ時点で明確に案内する。
- 変更した TetGen がある場合は、その変更を明示して対応ソースに含める。

将来、ブラウザー版、クラウド版、サーバー処理などで TetGen をネットワーク越しに利用させる場合は、AGPL 第13条のネットワーク利用者向けソース提供も別途設計する必要があります。現在のローカルデスクトップ版には、その機能はありません。

### 商用利用について

AGPL は商用利用や有償配布を禁止していません。ただし AGPL の条件を守る必要があります。ソース公開要件が製品方針に合わない場合は、WIAS の TetGen 商用ライセンスを検討します。

## 2. TetGen 以外のバイナリ配布上の確認事項

現在の第三者ライセンス一覧では、少なくとも次が重要です。

| 構成要素 | 確認されているライセンス | 公開前の要点 |
|---|---|---|
| PyTetWild 0.3.0 / fTetWild | MPL-2.0 | 通知、ライセンス原文、対応ソースの入手方法、MPL対象ファイルを変更した場合の変更済みソースを確認する |
| PyMeshLab 2025.7.post1 | GPL-3.0 | GPL 対応ソース、通知、配布物との対応関係を確認する |
| Qt 5.15.2 | LGPL-3.0、GPL または商用の選択肢 | 採用するライセンス経路を固定し、ライセンス全文、通知、ライブラリの置換・再リンク、デバッグの権利を妨げない配布方法を確認する |
| GEOS | LGPL-2.1 | 対応する通知、ライセンス、ソース入手方法を確認する |
| Python、Tcl/Tk、NumPy、SciPy、Pillow など | 各ライセンス | 正確な版と通知を最終配布物から再棚卸しする |
| Microsoft Visual C++ Runtime | Microsoft の再頒布条件 | 使用版と再頒布可能なファイルを確認する |
| PyInstaller | GPL 例外付き | PyInstaller 自体と同梱依存関係を混同せず、それぞれの条件を確認する |

とくに Qt は、「LGPL と書いてあるから EXE に入れてよい」だけでは不十分です。PyInstaller または wheel による具体的な梱包方法で、利用者が Qt ライブラリを置換できるか、必要な対応ソースやインストール情報をどう提供するか、リバースエンジニアリングを契約で禁止していないかを確認します。静的リンク、単一ファイル化、一時展開型の構成では追加確認が必要です。

したがって、TetGen の条件を満たしたことだけではバイナリ配布は許可判定できません。最終的な EXE から SBOM または同等の依存関係一覧を作り、実際に同梱された DLL、Python パッケージ、モデルデータ、フォント、アイコンを一件ずつ確認します。

## 3. 旧 EXE、recovered_pyc、旧アイコンを除外する理由

ここでいう「権利」とは、ファイルを所持しているかではなく、そのファイルを公開、複製、改変、再配布できる根拠が確認できるかという意味です。

### 旧 EXE

EXE には、自作コードだけでなく、第三者ライブラリ、画像、フォント、モデル、ビルド時の素材が含まれる場合があります。元のソースと依存関係、各ライセンス、ビルド経路を説明できない旧 EXE は公開しません。

### recovered_pyc と復元コード

pyc はコンパイル済み Python コードであり、元ソースから生じた著作物です。pyc から復元したコードも、復元したという事実だけで新しい権利が発生するわけではありません。元コードの作成者、ライセンス、第三者コードとの境界を説明できないものは公開コードの根拠にしません。

### 旧アイコン

アイコンは著作権の対象になり得ます。また、図柄によっては商標やブランド表示にも関係します。EXE から取り出したことや、以前のアプリで使用していたことだけでは再配布権の証明になりません。公開版には、出所と許諾を記録できる新規アイコン、または明確な再利用ライセンスのある素材を使用します。

### ChromaMatter r31アイコンのcreator declaration

2026-08-20、利用者兼creatorは、r31アイコンのロボットについて、参考資料の影響はあるものの、既存characterや実在製品を再現する意図のないオリジナルの架空機体であると申告しました。また、胸部の`ZENITH DYNAMICS CORP.`は実在組織との関係を示す意図のない創作上の文言であり、この画像をChromaMatterのrepository、実行file、screenshot、動画、Innovation Fund応募で公開・再配布することを承認しました。

release review時のbasic exact-match web checkでは`ZENITH DYNAMICS CORP.`と`ChromaMatter`の完全一致を確認できませんでした。一方で、近似名`Zenith Dynamics`を使用する複数の実在組織があります。このため「同名企業が世界に存在しない」「商標上clearである」とは記載せず、実在のZenith Dynamics各社とは無関係であることを表示します。

以上により、r31 icon publication rightsは**passed-by-creator-declaration**、このasset scopeのlegal gateは**project owner accepted**と記録します。これは独立した商標調査、第三者の意匠・likeness clearance、法的意見、全法域での無侵害保証ではありません。creatorは残余riskを認識したうえで公開GOを選択しています。

### 公開時の扱い

次は公開リポジトリ、Git 履歴、リリース ZIP、EXE から除外します。

- source/recovered_pyc
- source/original_icon_source.exe
- 旧 EXE と旧配布フォルダー
- 復元過程だけに使用した中間コード
- 由来を証明できない旧アイコン

将来、作成記録や元ライセンスによって権利が確認できた場合だけ、個別に再評価します。除外は「違法と確定した」という意味ではなく、公開可能だと立証できていないものを安全側で保留する措置です。

## 4. Codex を利用した開発の権利と表示

本プロジェクトでは、提案者が目的、仕様、UI、受入判断、実機検証方針を決め、OpenAI Codex を実装、テスト、文書作成の支援に利用しています。

OpenAI の利用規約上、OpenAI と利用者の関係では、法令上許される範囲で出力の権利は利用者に帰属します。ただし、次の点は別です。

- 入力した旧コード、画像、モデル、アイコンに第三者の権利があれば、その権利は消えない。
- AI 出力が既存の第三者コードと同一または類似でないことを自動的に保証するものではない。
- 出力は他の利用者の出力と同一または類似する場合がある。
- 公開者自身が内容を確認し、ライセンス、品質、安全性に責任を持つ。

そのため、「Codex が作ったから自由に公開できる」とは扱いません。公開資料には、AI 支援開発であること、人間が仕様決定と検証を行うこと、OpenAI が本プロジェクトを後援または承認しているわけではないことを明記します。

## 5. 実モデル、画像、3MF、動画の扱い

実際の検証に使うモデル、元画像、出力 3MF は、公開リポジトリや配布物には含めません。動画に表示する場合も公開行為であるため、作成者、入力画像、生成サービスの契約プラン、生成日、利用条件、第三者ブランドの有無を記録します。

「ファイルをダウンロード配布しない」ことはリスクを下げますが、動画公開の権利確認を不要にはしません。詳細は [PRIVATE_SAMPLE_POLICY_JA.md](PRIVATE_SAMPLE_POLICY_JA.md) に定めます。

## 6. 現時点の公開判定

| 項目 | 現在の判断 | 公開前に必要なこと |
|---|---|---|
| 整理済みソースのみ | **source-publication-approved** | `ChromaMatter_0.8beta-r31-source-public-20260820`のprivacy、license notice、clean build／test、final stage、archive parity、CRC、identity／icon／tooling、Downloads配置、detached checksum照合が完了 |
| EXE・software配布 ZIP | 保留 | ownerの公開GOでも第三者license義務は免除されない。PyTetWild/fTetWild、TetGen、PyMeshLab、Qt、GEOS等を含むexact binary再配布監査を完了する |
| 旧 EXE、recovered_pyc、旧アイコン | 除外 | 権利と由来が文書で確認できるまで公開しない |
| 合成テストデータ | 公開候補 | 自作生成手順とライセンスを明示 |
| 実モデル・元画像・3MF | 非配布 | 動画表示だけでも権利記録を残す |
| Snapmaker Orca 一貫操作 | 未完了 | 動画チェックリストに沿った実機能確認 |
| Snapmaker U1 物理造形 | 未完了 | 実フィラメントでの造形、色、寸法、ジョイント評価 |

`publication_eligible=true`の範囲は`source-only`に限定します。checksum値は外部detached recordだけを正本とし、canonical source文書には埋め込みません。物理XP-PEN検証とU1造形matrixは未完了evidenceとして残しますが、2026-08-20のowner decisionではソース公開を止めるhard gateではなく、既知の制約として明示する扱いです。EXE／software ZIPには第三者binary再配布監査が別のhard gateとして残ります。

## 7. 一次情報

- TetGen License FAQ: https://wias-berlin.de/software/tetgen/FAQ-license.jsp
- tetgen 0.8.3 repository: https://github.com/pyvista/tetgen/tree/v0.8.3
- tetgen Python wrapper MIT License: https://github.com/pyvista/tetgen/blob/v0.8.3/LICENSE
- bundled TetGen core license: https://github.com/pyvista/tetgen/blob/v0.8.3/src/tetgen-license
- GNU Affero General Public License v3: https://www.gnu.org/licenses/agpl-3.0.en.html
- GNU FAQ, GPL plug-ins and linking: https://www.gnu.org/licenses/gpl-faq.en.html#GPLPlugins
- GNU FAQ, GPLv3 and AGPLv3 combination: https://www.gnu.org/licenses/gpl-faq.en.html#AGPLGPL
- GNU FAQ, AGPL remote interaction: https://www.gnu.org/licenses/gpl-faq.en.html#AGPLv3InteractingRemotely
- Qt Open Source Licensing Obligations: https://www.qt.io/licensing/open-source-lgpl-obligations
- OpenAI Terms of Use: https://openai.com/policies/terms-of-use/
- OpenAI Sharing and Publication Policy: https://openai.com/policies/sharing-publication-policy/
- OpenAI Brand Guidelines: https://openai.com/brand/
- Tripo Terms of Service: https://www.tripo3d.ai/terms
- Tripo Pricing: https://www.tripo3d.ai/pricing
- Creative Commons Attribution 4.0: https://creativecommons.org/licenses/by/4.0/
