# ChromaMatter GitHub公開手順

更新日: 2026-08-21  
対象: ChromaMatter — AI Model Print Studio `0.8beta`の初回ソース公開記録とr32更新手順  
方針: **r31 source-only repositoryは公開済み。r32 updateはexact regression／build／stage／checksum完了までpendingで、EXEとReleaseは保留する。**

r31 final source-only stageは227 files／226 manifest recordsでfresh archive exact、privacy、identity／icon／tooling 32 tests、Downloads配置、detached `SHA256SUMS-r31.txt`照合まで完了した**previous evidence**です。owner handle `Ponkichi0718`の[public repository](https://github.com/Ponkichi0718/ChromaMatter)へ公開済みで、個人メールを含まない初回公開commitは`a01ba4baa791809a5a6621fac35956dc65479216`です。software 1,404 files／1,403 manifest recordsのpreflight self-test／日英UI smokeもr31だけの技術evidenceです。r32のfile数、manifest数、commit、hash、GitHub反映は未測定・未実施であり、完了として記録しません。

## 最初に守ること

GitHubへ入れるのは、`tooling/stage_public_source.ps1`で生成した**公開候補フォルダーの中身だけ**です。

次のものをGitHub Desktopへ追加しないでください。

- 非公開の開発ワークスペース全体
- 旧HANDOFF ZIP、旧EXE、`recovered_pyc`
- `release_stage*`、`build_output`、`validation_output*`
- DownloadsやDesktopにある実モデル、画像、3MF、動画
- 権利記録を作っていないデモOBJ

一度Gitへcommitしたファイルは、後で画面上から削除しても過去のcommitに残ります。PrivateからPublicへ変更すると、それまでのcommit履歴も公開されます。そのため、最初のcommitから公開候補だけを使います。

現在の公開候補を後から直接編集し続けるのではなく、コード、アイコン、README、サンプルなどを変更するたびにステージングスクリプトから新しい候補を作り直してください。

## 全体の流れ

1. 公開名とcommit用メールを決める。
2. 公開候補を新しく生成する。
3. 自動生成された`README.md`と`LICENSE`を確認する。
4. 公開候補だけで監査、テスト、起動確認を行う。
5. GitHub Desktopで新しいローカルリポジトリを作る。
6. 最初は`Private`としてGitHubへ送る。
7. Web上とクリーンクローンで再確認する。
8. 最終チェックがすべて終わった後に`Public`へ変更する。
9. EXEを含むReleaseは、ライセンス監査と実機確認の後日に行う。

## 1. 公開名とメールアドレスを決める

### GitHub上で表示する名前

本名を公開する必要はありません。継続して使用できるGitHubユーザー名またはハンドル名を一つ決めます。

公開前に最低限、次の表示を同じ考え方でそろえます。

- GitHubプロフィールの表示名
- Git commitの作成者名
- `licenses/LICENSE_APP.txt`の著作権表示
- READMEや提案資料に記載する開発者名

例:

```text
Copyright (c) 2026 Ponkichi0718 and ChromaMatter contributors
```

公開用handleは`Ponkichi0718`です。公開後に名前を頻繁に変えると、作者と履歴の対応が分かりにくくなるため、この記録を維持します。

### 個人メールをcommitへ出さない設定

1. GitHub.com右上のプロフィール画像から`Settings`を開く。
2. 左側の`Emails`を開く。
3. `Keep my email addresses private`を有効にする。
4. 表示されたGitHubの`noreply`アドレスを確認する。
5. GitHub Desktopで`File` → `Options` → `Git`を開く。
6. `Name`に公開名、`Email`にGitHubの`noreply`アドレスを設定する。

すでに作ったcommitの作者メールは、この設定を変えただけでは書き換わりません。公開候補の最初のcommitより前に設定します。

## 2. 公開候補を新しく生成する

非公開の開発フォルダーをPowerShellで開き、重複しない候補名を指定して実行します。

```powershell
.\tooling\stage_public_source.ps1 `
  -Destination ".\artifacts\ChromaMatter-0.8beta-r32-source-public-20260823-candidate-1"
```

スクリプトは既存フォルダーを上書きしません。内容を変更した場合は`r2`、`r3`のように新しい名前で作り直します。

正常終了時には次が行われます。

- allowlistに登録された公開予定ファイルだけをコピー
- 個人絶対パス、既知の私有ファイル、EXE、PYC、3MF、動画などの監査
- `SOURCE_MANIFEST_SHA256.txt`の生成
- manifest生成後の再監査

この出力フォルダーの**中身**がGitHubへ入れる候補です。親にある`artifacts`フォルダー全体は公開しません。

## 3. GitHub用のREADMEとLICENSEを確認する

`stage_public_source.ps1`は、公開候補を生成するときに次の3ファイルも自動配置します。手作業でコピーする必要はありません。

- `README.md`: GitHubのトップに自動表示する日本語README
- `README_EN.md`: 英語版
- `LICENSE`: GitHubが認識しやすいルートのGPL version 3全文

`README.md`、`README_EN.md`、`LICENSE`が公開候補のルートに存在することを確認します。`licenses/LICENSE_APP.txt`と`licenses/THIRD_PARTY_LICENSES.txt`も残します。`LICENSE`だけにまとめて第三者ライセンスを削除してはいけません。

公開候補はこれらを含めた状態で監査とmanifest生成が完了しています。念のため再確認する場合は次を実行します。

```powershell
.\tooling\audit_public_tree.ps1 -Root .
```

公開候補の中身を手作業で変更すると`SOURCE_MANIFEST_SHA256.txt`と一致しなくなります。誤字修正を含め、変更は元の開発フォルダーで行い、ステージングスクリプトから新しい候補を作り直してください。

古いstageの`SOURCE_MANIFEST_SHA256.txt`を新しい候補へコピーしてはいけません。`.gitignore`は公開に必要な`publication/INNOVATION_FUND_APPLICATION_DRAFT.md`、`publication/INNOVATION_FUND_STATUS_JA.md`、`tooling/stage_software_package.ps1`を明示的に除外解除しているため、`git add`後にこの3点が欠落していないことも確認します。

## 4. 配布するデモデータの条件と置き場所

プロンプトから生成したモデルでも、権利確認なしで自動的に配布可能になるわけではありません。実用的なプロンプト生成デモは、ソースのGit履歴へ入れず、**別のGitHub Release添付ZIP**として配布します。特にOBJや参照画像が大きい場合、この分離を維持します。

ソースリポジトリには、現在の抽象形状による小さな合成テストだけを残します。実用デモを更新してもソース履歴が肥大化せず、ソースのライセンスとデモ素材の権利条件も分けて表示できます。

Releaseへ入れるのは、次を記録できたデモだけにします。

- 自分で作成した一般的なプロンプトである
- 第三者のキャラクター名、商品名、ロゴ、作家名、特定作品の再現指示を含まない
- 入力画像を使った場合、その画像を自分で作成したか配布許可がある
- 生成サービス名、利用プラン、生成日、モデルID
- 生成時に適用された利用規約のURLと確認日
- そのプランで生成物の再配布と、予定する利用形態が許可されている
- 公開するOBJ、参照画像、任意の3MFなどの対象ファイル名
- 適用するサンプルライセンスと、ライセンスを設定できる根拠

配布ZIPの例:

```text
ChromaMatter-demo-01.zip
  demo_model.obj
  reference_image.png
  demo_output.3mf          # 配布する場合だけ
  PROMPT.txt               # 公開可能な一般プロンプト
  DEMO_LICENSE.txt
  DEMO_PROVENANCE.md
  SHA256SUMS.txt
```

`DEMO_PROVENANCE.md`へ公開可能な権利記録を残します。モデルIDや契約情報を公開したくない場合は、公開用記録と非公開の証拠資料を分け、公開用記録から非公開資料を参照します。ZIP自体のSHA-256もRelease notesに記載します。

最初はGitHub Releaseを`Draft`として作り、外部から見える形で試したい段階でも`Set as a pre-release`を選びます。権利記録、OBJ読み込み、色変換、3MF出力、必要ならSnapmaker Orcaでの確認が終わるまでは正式公開しません。

実験用に持っている別の実モデルや画像を配布ZIPへ混ぜないでください。ZIP作成元もソースリポジトリの外に置き、誤ってcommitされないようにします。

## 5. GitHub DesktopでPrivateリポジトリを作る

### A. GitHubアカウントだけを作成済みの場合

この手順が最も分かりやすい方法です。

1. GitHub Desktopをインストールし、作成済みのGitHubアカウントでサインインする。
2. `File` → `New repository...`を開く。
3. `Name`を`ChromaMatter`など、公開予定の名前にする。
4. `Local path`には、非公開の開発フォルダーとは別の、新しい公開作業場所を選ぶ。
5. Git ignoreとLicenseの自動追加は`None`にする。今回の候補には監査済みの`.gitignore`とGPLの`LICENSE`があるためです。
6. `Create repository`を押す。
7. エクスプローラーで、公開候補フォルダーの**中身だけ**を新しいリポジトリへコピーする。
8. GitHub Desktopの`Changes`で追加ファイルを確認する。

ここで、開発ワークスペース、HANDOFF ZIP、EXE、実モデルが表示されたらcommitせず、コピー先を確認し直します。

### B. GitHub.comですでに空のリポジトリを作成済みの場合

1. GitHub.comで、そのリポジトリが`Private`であることを先に確認する。
2. GitHub Desktopで`File` → `Clone repository...`を開く。
3. `GitHub.com`タブから対象リポジトリを選ぶ。
4. 非公開の開発フォルダーとは別の空の保存先へcloneする。
5. 公開候補フォルダーの**中身だけ**をclone先へコピーする。
6. GitHub Desktopの`Changes`で追加・置換されたファイルを確認する。

WebでREADMEやLICENSEを自動生成済みでも問題ありませんが、今回用意した監査済みの`README.md`と`LICENSE`へ揃えます。異なる履歴を無理に結合せず、最初のcommitが何を含むかを必ず確認します。

## 6. 最初のcommitとPrivateでの送信

GitHub Desktopの`Changes`一覧を上から下まで確認します。

特に、次がないことを確認します。

- `.exe`、`.pyc`、`.3mf`、動画、旧ZIP
- `source/recovered_pyc`
- `release_stage`、`build_output`、`validation_output`
- 個人の実OBJや画像
- Windowsのユーザーフォルダーから始まる個人絶対パス
- APIキー、トークン、パスワード、個人メール

問題がなければ次のようにcommitします。

1. 左下の`Summary`へ`Initial source-only preview`と入力する。
2. `Commit to main`を押す。
3. 上部の`Publish repository`を押す。
4. 名前と説明を確認する。
5. **`Keep this code private`を必ずオンにする。**
6. 個人アカウントへ置く場合、`Organization`は`None`を選ぶ。
7. `Publish Repository`を押す。

すでにGitHub.comのPrivateリポジトリをcloneした場合は、`Push origin`を押します。

この段階ではGitHub上に送信されますが、リポジトリはPrivateなので一般公開されません。ただし、GitHubへ送信すること自体を避けたい秘密情報は、Privateにも入れない方針を維持します。

## 7. Privateのまま確認する

GitHub Desktopで`Repository` → `View on GitHub`を開き、次を確認します。

- リポジトリ名の横に`Private`と表示される
- トップに日本語の`README.md`が正しく表示される
- `LICENSE`がルートにある
- `source/fixed_app`、`samples`、`licenses`、`publication`の範囲が想定どおり
- 旧EXE、復元物、実モデル、実画像、3MF、動画がない
- commit作者名とメール表示が意図どおり
- 説明文がSnapmaker、TripoAI、OpenAIなどの公式製品・提携製品だと誤認させない

可能なら、ログアウト状態またはシークレットウィンドウでURLを開き、Privateの間は内容を閲覧できないことも確認します。

### GitHubからクリーンクローンする

GitHub DesktopでPrivateリポジトリを別の空フォルダーへcloneし直し、公開候補だけで次を行います。

```powershell
.\tooling\audit_public_tree.ps1 -Root .
$pyTetWildWheel = 'C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl'
.\BOOTSTRAP_WINDOWS.ps1 -PyTetWildWheel $pyTetWildWheel
```

必要に応じてテスト、日英UI起動、ソースビルドを確認します。ただし生成された`.venv`や`build_output`は`.gitignore`対象であり、commitしません。

## 8. Publicへ変更する直前の確認

次がすべて完了するまでPrivateのままにします。

- [x] 公開名／handle `Ponkichi0718`とGitHub `noreply` commit用メールを確定した
- [x] README、`LICENSE`、第三者ライセンスを確認した
- [x] 最新アイコンへ変更後に公開候補を再生成した
- [x] 公開候補監査に合格した
- [x] GitHubからのクリーンクローンで32 testsを再実行した
- [x] Public化前後の全ファイルとcommit履歴を確認した
- [x] ソースGit履歴には抽象形状の合成テストだけが入っている
- [x] 配布予定の実用デモはソースと別管理し、権利記録を作成する方針を維持した
- [x] デモ以外の実モデル、画像、3MF、動画を含めていない
- [x] EXEを含めていない
- [x] APIキー、トークン、個人メール、個人絶対パスがない
- [ ] r32 exact sourceをfinal restageし、fresh archive／privacy／identity／manifest／外部detached `SHA256SUMS-r32.txt`を照合した
- [ ] r32 source-only差分をGitHubへ反映し、公開treeとfinal stageの一致を確認した

## 9. PrivateからPublicへ変更する

公開する日になったら、GitHub.comで行います。

1. 対象リポジトリを開く。
2. 上部の`Settings`を開く。
3. `General`ページの最下部にある`Danger Zone`まで移動する。
4. `Change repository visibility`の`Change visibility`を押す。
5. `Public`を選ぶ。
6. 対象リポジトリ名が正しいことを確認する。
7. 影響を理解した確認項目に同意する。
8. `Make this repository public`を押す。

Publicへ変更すると、コードだけでなく過去のcommit履歴や公開対象となるActionsログも第三者から見られ、誰でもforkできる状態になります。変更前のPrivate確認を公開判定として扱います。

## 10. 容量制限と置き場所

GitHub公式の主な制限は次のとおりです。

| 方法 | 1ファイルの扱い |
|---|---:|
| GitHub.comのブラウザーから追加 | 最大25 MiB |
| 通常のGit／GitHub Desktop | 50 MiBを超えると警告、100 MiBを超えるファイルは拒否 |
| Git LFS | 100 MiBを超える大きな追跡ファイル向け。上限と容量・通信枠はプラン依存 |
| GitHub Releaseの添付ファイル | 1ファイル2 GiB未満 |

今回の公開候補はファイル数も多いため、ブラウザーへ一つずつアップロードせずGitHub Desktopを使います。

- ソース、文書、現在の小さな抽象形状テストOBJ: 通常のGit
- プロンプト生成した実用デモOBJ、参照画像、任意の3MF: ソースGitへ入れず、別のRelease添付ZIP
- 監査後の配布用EXEやZIP: 通常のcommitには入れず、後日のGitHub Release

Git LFSは、共同編集などの理由で大きなファイルをGitの版管理対象にする必要がある場合の選択肢です。今回のデモ配布はRelease添付ZIPを第一選択とするため、通常はGit LFSへ入れません。

## 11. デモReleaseとEXE Releaseは分けて後日行う

初回はソースリポジトリの公開までに留めます。プロンプト生成デモのReleaseと`0.8beta`のEXE Releaseは、ソース公開と分けて後日作ります。

### デモデータのRelease

デモZIPは、Section 4の権利台帳とファイル構成を満たしてから添付します。

- 最初は`Draft`で内容、ライセンス、SHA-256を確認する
- ベータ機能の実演データである間は`Pre-release`として公開する
- OBJ、参照画像、任意の3MFを一つのZIPへまとめる
- `DEMO_LICENSE.txt`と`DEMO_PROVENANCE.md`を必ず同梱する
- ソースコード用のGPLがデモ素材へ自動適用されるとは考えず、デモの条件を別に明記する

### EXEのRelease

EXE Releaseを作る条件は次のとおりです。

- TetGen、PyMeshLab、Qt、PyTetWild、GEOS、Pythonランタイムなどを含むバイナリ全体のライセンス監査
- 対応ソースとビルド手順の固定
- Windowsのクリーン環境で起動確認
- Snapmaker Orcaへの受け渡し確認
- U1での小規模な物理造形確認
- EXE／ZIPのSHA-256記録
- Release notesへベータ版の制限と既知問題を記載

GitHubがタグから自動生成するソースZIPと、手動添付するEXE／配布ZIPは別物です。バイナリ監査が終わるまでは、EXEを通常のGitにもReleaseにも置きません。

## 12. 短いCLI代替手順

コマンド操作に慣れている場合だけ使用します。以下は、公開候補フォルダーでREADMEとLICENSEを整え、GitHub CLIがインストール済みであることを前提に、**Private**リポジトリを新規作成する例です。

```powershell
git init -b main
git config user.name "YOUR_GITHUB_HANDLE"
git config user.email "ID+YOUR_GITHUB_HANDLE@users.noreply.github.com"
git status
git add .
git status
git commit -m "Initial source-only preview"
gh repo create ChromaMatter --private --source . --remote origin --push
```

`git add .`の後、二回目の`git status`で対象をすべて確認してからcommitします。`gh`がない場合や認証設定が分からない場合は、GitHub Desktopの手順を使います。

すでにGitHub.comに空のPrivateリポジトリがあり、URLを把握している場合は次の形です。

```powershell
git init -b main
git add .
git status
git commit -m "Initial source-only preview"
git remote add origin https://github.com/YOUR_GITHUB_HANDLE/ChromaMatter.git
git push -u origin main
```

上のCLIは今後の再公開時に使うtemplateです。初回r31は`https://github.com/Ponkichi0718/ChromaMatter`の`main`へsource-onlyで公開済みで、個人メールを除いた初回公開commitは`a01ba4baa791809a5a6621fac35956dc65479216`です。r32 commitはexact final stageが完了するまでpendingで、値を先に記録しません。

## GitHub公式資料

- [GitHub Desktopで既存プロジェクトを追加する](https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-an-existing-project-to-github-using-github-desktop)
- [GitHub Desktopで最初のリポジトリを作る](https://docs.github.com/en/desktop/overview/creating-your-first-repository-using-github-desktop)
- [リポジトリの可視性を変更する](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility)
- [GitHubの大きなファイルに関する制限](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
- [Git Large File Storageについて](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage)
- [GitHub Releasesについて](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [commit用メールアドレスを設定する](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address)
