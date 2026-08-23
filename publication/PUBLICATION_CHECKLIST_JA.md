# ChromaMatter 0.8beta 公開準備チェックリスト

更新日: 2026-08-24
現在の方針: **`v0.8beta-r32`は[GitHub](https://github.com/Ponkichi0718/ChromaMatter)で公開済みのimmutableなprevious evidence。r32.1はexact regression／build／stage／checksumが揃うまでpendingとし、新しいtagと同時asset setで公開する。**

このチェックリストは、法的助言ではなく、公開事故を減らすための実務管理表です。

## 現在の到達点

| 項目 | 状態 | 判断 |
|---|---|---|
| 表示バージョン | 完了 | 利用者の指定があるまで`0.8beta`に固定 |
| r32.1 exact release gate | **pending** | functional freeze後のfull regression、clean build、packaged smoke、日英UI smoke、source/software stage、archive、privacy、identity、checksumを実測する。r32以前の結果を流用しない |
| r31 preflight技術監査（previous evidence） | **GO** | source 227／226、software 1,404／1,403、fresh archive／extract、privacy、self-test、日英UI smokeを確認 |
| r31 final source-only restage（previous evidence） | **GO** | source 227／226、folder／archive parity、CRC、privacy、identity／icon／tooling 32 tests、Downloads配置、detached `SHA256SUMS-r31.txt`照合を完了 |
| public repository | **r32公開済み／r32.1更新pending** | `https://github.com/Ponkichi0718/ChromaMatter`、owner handle `Ponkichi0718`、default branch `main` |
| 旧EXEへのビルド依存 | 完了 | 依存を除去。公開候補へ含めない |
| 復元PYCへの実行依存 | 完了 | 293テストをPYCなしで通過。公開候補へ含めない |
| ChromaMatterアイコン | **creator declarationでGO** | creatorがオリジナルの架空機体と創作文言であると申告し、公開・再配布を承認。独立した商標／意匠clearanceではない |
| 個人絶対パス | 完了（自動監査あり） | 公開stageで検出時に失敗 |
| 既存の私有実モデル・画像・3MF | 完了（配布方針） | 公開stage／ZIPへ含めない |
| 公開専用デモモデル | **owner権利申告済み／package監査pending** | Hi3D有料planで生成した分割GLBと、owner作成のreference画像。再配布承認、注意事項、SHA-256をDemoData manifestへ記録し、final package bytesと照合する |
| 公開テストOBJ | 完了 | CC0の抽象的な合成3パーツOBJを用意 |
| 一般プロンプト例 | 完了 | CC0。第三者名・作品名・個人情報なし |
| 混色モデルの来歴 | 完了 | MIT上流コミット、SHA-256、全配列一致、再生成手順を記録 |
| クリーンクローン検証 | r32 previous evidence／r32.1 pending | r32.1 final source stage作成後、空フォルダーとfresh `.venv`から再測定する |
| アプリ基礎コードの公開判断 | **owner GO** | project ownerが現在のsourceを自分のprojectとして公開することを2026-08-20に承認。独立したcode provenance法務監査ではない |
| 公開用ハンドル | **完了** | repository owner handle `Ponkichi0718`をGitHub metadataへ記録 |
| r32.1 EXEの第三者ライセンス監査 | **現行bytesの最終監査pending** | SBOM／component map／対応ソース／通知／license原文のfail-closed実装は完了。ownerの公開GOでもexact r32.1 binaryに対する再生成・照合は免除されない |
| Snapmaker Orca一貫操作 | **未完了** | 動画で開く→スライス→保存→再読込を記録 |
| U1物理造形 | **未完了** | 実際の色、積層、強度、嵌合を記録 |

## 1. 旧EXE、復元PYC、アイコン、復元コード

### 既に解決したこと

- ビルド設定から旧EXEと復元PYCへの参照を削除した。
- 混色データは現行ソース側の権利表示済みコピーを使用する。
- ChromaMatterアイコンは利用者提供PNGを基に生成し、出所・変換内容・SHA-256を同梱provenance sidecarへ記録する。
- 公開stageは旧EXE、復元PYC、復元ツール、旧アイコンをコピーしない。
- 旧ファイルは非公開の作業履歴として残してよいが、Gitの最初の公開履歴へ入れない。

### Creator declarationと残る照合

- [x] 2026-08-20、creatorがロボットを参考資料の影響を受けつつも既存character／製品を再現する意図のないオリジナルの架空機体、`ZENITH DYNAMICS CORP.`を実在組織との関係を示す意図のない創作文言と申告し、提供PNGの公開・再配布を承認した。
- [x] basic exact-match web checkで`ZENITH DYNAMICS CORP.`と`ChromaMatter`の完全一致は未確認。ただし近似名`Zenith Dynamics`を使う実在組織が複数あるため、非提携を明示し、世界的clearanceを主張しない。
- [x] アイコンprovenance sidecarの原本SHA-256と生成物SHA-256が最終source-only stageと一致する。

このicon gateの完了はcreator declarationとproject ownerのrisk acceptanceによるもので、独立した商標調査、第三者意匠clearance、法的意見ではありません。

現行の基礎モジュールには、過去のアプリを復元して改修した系譜があります。旧EXEそのものを配布しないだけで独立したcode provenance監査が完成するわけではありません。一方、2026-08-20のproject owner GOにより、現在のallowlist sourceを自分のprojectとして公開する意思と許可は記録されました。

次の詳細文は、将来より強いprovenance証拠を作る場合の確認templateとして残します。

> 旧アプリは、私が依頼したCodex開発で新規に作られた自分のプロジェクトであり、私に再ライセンス権のない第三者の非公開コードや市販ソフトのコードを入力・コピーしていません。

- [x] project ownerが現在のsourceのsource-first公開を承認した（2026-08-20）。
- [ ] 上の詳細templateを事実として追加署名する場合、確認日と公開に使う本名またはハンドルを記録する。
- [ ] 独立したcode provenance監査が必要な配布先では、追加監査または独立実装範囲を決める。

OpenAIとの関係では利用者が出力を所有しますが、入力した第三者素材の権利まで消えるわけではありません。この確認はその境界を記録するためのものです。

## 2. 個人パスと個人データ

公開物は、開発フォルダー全体から作らず、`tooling/stage_public_source.ps1`のallowlistだけから作ります。`tooling/audit_public_tree.ps1`は、個人ユーザー領域、既知の私有モデル識別子、禁止形式、公開対象外ディレクトリを検出すると失敗します。

- [x] `CURRENT_STATE.json`を相対パスと一般情報だけにした。
- [x] 実モデルを自動探索するテストを廃止し、明示した環境変数がある場合だけ任意検証するようにした。
- [x] build、stage、private validation、temporary geometryを`.gitignore`へ追加した。
- [x] 公開stageへ過去の検証Markdownとローカルtoolingを入れない。
- [x] r31／公開済みr32のfinal stageとarchive監査をprevious evidenceとして保持した。
- [ ] r32.1 final source／software stageのfolder parity、CRC、privacy、manifestを再監査する。

## 3. 配布物を3つに分ける

1. **公開ソース**  
   現行コード、合成テスト、ビルド手順、ライセンス、来歴、合成サンプルだけ。

2. **r32.1 Windows配布候補**
   EXEと実行に必要なファイル、README、ライセンス、対応ソースへの案内、SHA-256、manifest固定済みDemoDataだけ。その他の私有検証物と応募資料は含めない。現行bytesの全バイナリ監査が終わるまで公開しない。

3. **非公開検証保管**  
   実OBJ、元画像、派生3MF、診断画像、元動画素材、スクリーンショット、実モデル検証JSON。Git・公開ZIP・issue添付の対象外。

例外候補は、ownerが掲載を明示承認し、個人情報gateを通過した公開専用copyだけです。r32.1では無音・privacy確認済みの`ChromaMatter-simple-workflow-demo.mp4`をGitHub Releaseの独立assetとして扱い、権利確認済みのHi3D分割GLBとowner作成reference画像だけをexact DemoData manifestに従ってsoftware ZIPへ同梱します。大容量GLB／画像はGit treeと対応ソースZIPへ入れません。これら以外の元動画、元モデル、生成3MFは非公開検証保管のままです。

r32.1 DemoData以外の将来の公開専用デモは、既存の私有検証物から選ばず、`samples/DEMO_MODEL_RIGHTS_RECORD_TEMPLATE_JA.md`の権利ゲートを通過したものだけ、適用ライセンスと帰属表示を添えて追加します。

## 4. TetGenとEXE配布

TetGenはオープンソースなので利用できますが、「GitHubに何かのソースを置けばよい」という意味ではありません。配布する正確なEXEに対応するソース、変更、ビルド・インストール情報、通知、ライセンス原文、ソース入手方法を揃えます。

- [x] tetgen PythonラッパーのMITとTetGen本体のAGPLを区別した。
- [x] 現行PyInstaller specがPyTetWildのMPL、tetgenのMIT、TetGenのAGPL原文を`_internal/licenses/`へ明示同梱することを確認した。
- [x] 個人PCだけで使う現段階では、直ちに一般公開する必要はないと整理した。
- [x] GPLアプリとAGPL部分を組み合わせる場合の追加条件を文書化した。
- [x] PyTetWild／fTetWildのMPL通知、対応ソース、変更、rebuild lockをfail-closedで検証する実装を追加した。
- [x] PyMeshLab／MeshLabのGPL対応ソースmanifestと取得契約を実装した。
- [x] Qtの通知、置換・再リンク説明、静的component coverageを実装した。
- [x] GEOS、Python、Tcl/Tk、Microsoft runtimeを含むSBOM／component map生成を実装した。
- [x] 配布EXEと同一commitのrelease-approved対応ソースだけを受け付けるstage契約を実装した。
- [x] アプリからライセンスとソース入手先へ到達できるUIを実装した。
- [ ] 上記をexact r32.1 final binary／source bytesに対して再生成し、fresh extractionで照合する。
- [ ] 必要なら専門家の確認またはWIASの商用ライセンスを検討する。

公開済みr32のsource／binary Releaseはimmutableなprevious evidenceです。r32.1 EXEは、上の契約をexact final bytesへ適用した第三者binary再配布監査が完了するまで保留します。

## 5. 実モデル、動画、プロンプト

- [x] 既存の私有実OBJ、元画像、3MF、動画編集素材を配布しない方針にした。
- [x] 公開テストはプロジェクトで新規作成した抽象形状だけにした。
- [x] 一般プロンプト例をCC0として分離した。
- [x] 公開専用デモ用の2D画像生成・3Dモデル生成プロンプトと権利記録テンプレートを用意した。
- [x] owner承認済みr32.1 DemoDataの分割GLBとreference画像を選定し、公開・再配布可否を記録した。
- [x] Hi3D有料planでの生成とowner作成reference画像であることを確認し、canonical publication gateへ記録した。
- [x] 配布する2 payloadの固定名、size、SHA-256、用途、注意事項をDemoData manifest／README／NOTICEへ記録した。
- [ ] exact final software stageでpayload bytesとmanifestを照合し、package privacy／archive監査を完了する。
- [ ] 生成サービスの条件がCC BY 4.0の場合はCC BY 4.0を維持し、CC0へ変更しない。
- [ ] 将来Tripo生成物を別途配布する場合は、生成時のTerms／Pricing、plan、入力権利、配布範囲を個別に保存する（今回の2 payload gateとは分離）。
- [ ] 動画に使う私有素材について、作成者、元画像の権利、生成日、生成時のTripoプラン、モデルIDを非公開台帳へ記録する。
- [ ] 収益化、応募動画、ファイル配布では、生成時と公開時の利用条件が明確なモデルだけを使う。
- [ ] 動画から個人パス、ファイル名、アカウント情報、不要なモデルIDを隠す。
- [ ] 動画説明欄とダウンロードページで、非配布素材／公開デモの区別、ライセンス、必要な帰属表示を明記する。

プロンプトを配布しても、生成されるモデルの権利条件までは一緒に付与できません。利用者が使う生成サービス、契約プラン、入力画像、生成物の規約に従う旨を明記します。

## 6. クリーンクローン

クリーンクローンとは、**別の人のPCと同じ条件を、新しい空フォルダーで試すこと**です。現在の開発フォルダーが動くかではなく、公開予定ファイルだけで再現できるかを確認します。

- [x] 公開stageを新しい空フォルダーへ置いた。
- [x] `BOOTSTRAP_WINDOWS.ps1`で新規`.venv`を作った。
- [x] 293テストが成功した（任意の非公開実モデルテスト1件は未指定のためskip）。
- [x] 旧EXE、復元PYC、非公開runtimeが無くてもPyInstaller buildが成功した。
- [x] 新しいEXEでself-testと日本語／英語UI smokeが成功した。
- [x] 合成OBJを読み込み、3パーツ、18頂点、24三角形、18固有色、`explicit_parts=True`を確認した。
- [x] 検証に使用した公開stageの監査とSHA-256 manifestが成功した。

2026-08-06の記録: Python 3.13.14、pip 26.2.1、293テスト成功、packaged self-test／日本語UI smoke／英語UI smokeはいずれもexit 0。検証用EXEは12,802,348 bytes、ProductVersion／FileVersionは`0.8beta`、SHA-256は`BF53225CCFB9C71CE15A0372D2453BEBBC2E584E5D9E421C92D1BA205FD0DBE7`です。この成功は公開候補だけで再現できることの確認であり、未完了の第三者ライセンス監査を省略してEXEを公開してよいという判定ではありません。

## 7. OrcaとU1

これは公開ソースのプライバシー整理とは別の、製品としての実証です。

- [ ] Snapmaker Orcaで「プロジェクトとして開く」。
- [ ] Full Spectrumの4基本色と混色状態を確認する。
- [ ] `0.08 mm`でスライスする。
- [ ] 保存し、閉じて、再読込して色・パーツ・設定が維持されることを確認する。
- [ ] U1で小さい試験片を先に造形する。
- [ ] 実フィラメントの色、陰影、段差、混色境界、造形時間、廃棄量を記録する。
- [ ] 分割パーツでは寸法、雄雌ジョイントの向き、クリアランス、強度を確認する。
- [ ] 成功だけでなく失敗と対策も動画またはレポートへ残す。

詳細は`VIDEO_VALIDATION_CHECKLIST_JA.md`を使います。

## 公開直前の最終ゲート

- [x] 2026-08-20、project ownerが既知の制約とcreator declarationの範囲を確認し、公開GOを出した（独立した法的clearanceの主張ではない）。
- [x] ChromaMatterアイコンのcreator declarationと非提携方針をprovenanceへ記録した。
- [x] project ownerによる現在sourceの公開承認を記録した。
- [x] 公開用handle `Ponkichi0718`とrepository URLを記録した。
- [x] r31 preflight公開stageの監査、full regression、クリーンビルド、fresh extractが成功した（previous evidence）。
- [x] r31 final source-only artifactをDownloadsへ配置し、detached `SHA256SUMS-r31.txt`を作成・照合した（previous evidence）。
- [ ] r32.1 exact full regression、clean build、packaged self-test、1920×1080の日英UI smokeを完了した。
- [ ] r32.1 final source stageのREADME、LICENSE、PROVENANCE、第三者通知、identity／icon／tooling testが一致した。
- [ ] r32.1 final stage／archiveで許可済みDemoData以外の私有実モデルと個人データが0件であることをprivacy監査した。
- [ ] r32.1 artifactをDownloadsへ配置し、外部detached `SHA256SUMS-r32.1.txt`を作成・照合した。
- [ ] 公開専用デモを含める場合、権利記録、再配布条件、適用ライセンス、帰属表示、SHA-256を実ファイルと照合した。
- [x] r32.1はWindows ZIP、完全対応ソース、SBOM、component map、動画、checksumを同時公開する方針とした。
- [ ] r32.1 EXE／software ZIPのバイナリ配布監査が完了した。
- [x] リポジトリURLとソース入手先を公開した。
- [ ] issue運用、公開連絡先、セキュリティ連絡先を決めた。
- [ ] 「公式・認定・提携」と誤解される表現やロゴがない。
