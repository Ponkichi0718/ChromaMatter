# ChromaMatterでできること

## AIで生まれた色を、4本のフィラメントで現実へ

ChromaMatter — AI Model Print Studioは、AI生成された色付き3Dモデルを、Snapmaker OrcaのFull Spectrum／Color Mixingワークフロー向け3MFへ変換・調整するWindowsデスクトップツールです。

このプロジェクトが目指しているのは、単なるファイル変換ではありません。AI 3D生成には「実際にカラー造形する出口」を、カラー3Dプリンタには「AIが生み出す多様なモデルという新しい入力」をつくることです。画面の中で完結していた生成モデルと、物を作れる3Dプリンタの間をつなぐことで、双方の利用価値を一段高めます。

## 0.9開発版の主な更新：3MF出力精度・成功率の向上

0.9で最も大きな更新は、通常の単一論理GLBから有効な3MFへ書き出すまでの
精度と成功率の向上です。同一座標の重複シームを結合し、幅2.0 mm以下で厳密に
平面と確認できる微小開口だけを局所的に補修できます。書き出す前には従来どおり、
閉立体、非多様体辺、面向き、正体積、縮退面、自己交差をfail-closedで検証します。
通常の継ぎ目検証を内部の微小断片が妨げる場合は、主表面が全体の99.5%以上を占め、
除外対象が内部の微小な反転閉殻または範囲内の開いた微小断片だと証明でき、残す
主表面だけでも選択的な継ぎ目統合で閉じる場合に限って再試行します。正体積の独立
パーツは削除せず安全停止し、再メッシュやボクセル化も行いません。
複雑なパーツ化モデルの修復はまだ入力依存で、0.9で完全解決したとは扱いません。
この修復処理は共通エンジンへ実装しており、次回それぞれ検証する
Windows・macOS・Linuxの0.9 buildで同じロジックを使用します。

現在のソースは`0.9（r33）`開発版です。このソースから0.9の実行ファイルはまだ
package・公開していません。

> **最新の公開済みWindowsプレリリース（過去の0.8版）：** [ChromaMatter 0.8beta r32.2を直接ダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-win64.zip)。起動前にZIP全体を展開してください。checksum、対応ソース、同じ版の関連assetは[r32.2プレリリースページ](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2)で確認できます。

> **r32.2公開済みprerelease：** packageには結合1件とpart別6件の派生demo 3MFを
> 収録しています。exact build、完全対応source、archive、checksum、公開後の未認証
> 再download検証はすべてPASSしています。

<a id="experimental-workstream"></a>
## Flat Four Test 3候補 — 安定版r32.2 Windows版には未収録

この実験branchでは、公開済みの安定版r32.2 packageと、固定済みFlat Four Test 2
assetを変更せず、別のTest 3 prerelease候補を準備しています。

- **Flat Four**はモデル表面の面積を加味し、重複しない4本の実フィラメントを
  自動提案します。混色recipeは作らず、3MF出力もF1～F4だけを使用します。
- Test 3は白を一律に除去しません。黒い線に隣接する目の白など、意味のある小さな白は
  白いtargetとして保持します。肌などの滑らかな有彩色面に焼き込まれた、小さく確度の
  高い白／灰色の照明斑だけを、その境界で使われる有彩色F slotへまとめます。
- 保持された白が印刷対象総面積の**0.01%以上**なら、白に近い実filamentを1 slot
  確保します。0.01%未満の白は吸収せずに残しますが、それだけでは白spoolを強制せず、
  選択済みF1～F4の最寄色へ割り当てられる場合があります。
- 4つの物理F slotと3MF state情報は維持し、実際のpaint IDが3色だけになる場合も
  あります。Manual Editingを優先し、Full Spectrumの動作は変更しません。
- これはtopologyを使うfilterで、意味認識ではありません。暗い線、折り目、part境界の
  ない滑らかな肌色面に囲まれた小さな白は吸収される場合があります。再利用できる
  隣接情報がない50万面超のopen meshでは、この自動補正だけをfail-closedでskipします。
- 実験的な**2D彩色フィルター**は、**Cel Colour（セル彩色）**と
  **Shaded Monochrome（陰影モノクロ）**を提供します。形状を使った固定正面光と
  段階的な陰影を印刷対象色へ焼き付けます。輪郭線生成やPBR rendererではなく、
  結果はmesh normalと元色に依存し、入力にない細部は生成しません。
- 静的GLBの通常上限は512 MiB／300万頂点／300万三角形のままです。別のβ経路では、
  300万超～500万三角形の静的`TRIANGLES` sceneだけを、明示確認と面数調整ONを
  条件として最大45万面の作業用modelへ縮約します。非対応・曖昧なcaseは
  fail-closedで停止し、細かな形状や焼付textureが失われる場合があります。

このワークストリームはproject schema `obj-adjuster.project.v13`を書き出し、v12を
旧来のFull Spectrum dataとして引き続き読み込みます。Test 3候補working treeは
1,431 test／0 FAIL／3 optional SKIPと、owner-onlyのclean build／fresh-extract
preflightを通過しました。公開にはexact commitからのrebuild、完全対応source、
compliance asset、checksum、fresh-extract監査、公開検証が必要です。exact Test 3
packageのphysical printer validationは未実施です。

## 見たい内容へ

- [実験中のFlat Four／2D彩色／大規模GLB](#experimental-workstream)
- [OBJ／GLBの読み込みから3MF出力まで](#model-workflow)
- [Hi3D系分割GLB対応](#multipart-glb)
- [オリジナル作品の制作工程と過去の画面](#project-examples)
- [4本のフィラメントから16／24／32色を作る仕組み](#palette-system)
- [フィラメント候補ライブラリ](#filament-library)
- [混色比較チャートと実機黒補正](#calibration)
- [ブラシ・エアブラシ・塗りつぶし・なじませ・スポイト](#manual-editing)
- [公開sampleの実機出力結果と分割GLBの記録](https://note.com/ponkichi0718/n/nf6c77165127c)
- [開発記録・AI利用について](#development-journal)
- [ブラシ・フィラメント候補を追加した元記事](https://note.com/ponkichi0718/n/n711977c75aa4)

[![ChromaMatterの現行開発画面。4本の基本フィラメント、混色パレット、元モデル色とFull Spectrum変換色を並べて確認できる](https://assets.st-note.com/img/1787193863-DjEUKLdVrxFgauov4mzq7QB9.png?width=1200)](https://note.com/ponkichi0718/n/n711977c75aa4)

*開発中画面。4本の実フィラメントから作る混色パレットと、元モデル色／印刷用変換色を同時に確認できます。*

<a id="model-workflow"></a>
## AIモデルから3MFまでを、ひとつの流れに

頂点カラー付きOBJ、または埋め込みbaseColor／`COLOR_0`を持つ静的GLBを読み込めます。TripoAIだけでなく、Hi3D AIのようにGLBを出力するサービスも同じ制作フローへ取り込めます。対応する分割GLBはパーツ構成を保ったまま閉立体化し、結合3MFまたはパーツ別3MFへ出力できます。モデルの処理はローカルで行い、ChromaMatterから外部サーバーへアップロードしません。

<a id="multipart-glb"></a>
## Hi3D系分割GLB対応（β・非公式）

ChromaMatterは独立projectであり、Hi3D AIの公式・提携製品ではありません。Hi3Dから出力されるすべてのfileとの互換性を保証するものではありません。対応する静的・埋込assetのGLBに限り、mesh node単位のpartと配置を保って、色変換と3MF出力へ進めます。

- パーツ識別用の`COLOR_0`は、exporter由来、node構造、material、共通baseColor texture、既知の識別palette順がすべて一致した場合だけ除外します。証明が不足する場合、通常の作者指定頂点色はglTF標準どおりbaseColorへ乗算して保持します。
- 元のpartは一つずつ正規化・閉立体化し、別part同士を溶接しません。importした面と修復で追加した面も区別して追跡します。
- 検証に合格したassemblyは、結合3MFに加えて、指定時には各印刷partの独立3MFとmanifestを出力できます。part対応やprovenanceが不完全・古い場合は、検証を弱めず安全停止します。
- exactに証明できたseamと、利用者が明示した上限内の微小平面修復だけが対象です。animation、skin、morph、Draco、meshopt、BasisU、外部URI、曖昧または非対応のgeometryはβ対応外です。

[公開sampleの実機結果と分割GLBの開発記録](https://note.com/ponkichi0718/n/nf6c77165127c)では、識別色を本来のbaseColorから分離する必要性と、現在のpart別出力経路を記録しています。

<a id="project-examples"></a>
## オリジナル作品の制作工程と過去の画面

<table>
  <tr>
    <td width="50%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038136-QYcX12yPUL4fzm5RWZNbiEqM.jpg?width=1200" alt="AIで生成したオリジナルの赤いロボットの元画像"></a></td>
    <td width="50%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038182-v0C8IT5i1jVeKLdNX3ZygYu4.png?width=1200" alt="元画像から生成したオリジナルロボットの3Dモデル"></a></td>
  </tr>
  <tr>
    <td align="center">1. AIで作ったオリジナルの2D原案</td>
    <td align="center">2. 2D原案から色付き3Dモデルを生成</td>
  </tr>
  <tr>
    <td width="50%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038261-fQtHZho5CXvrYl94M7zJOqLD.png?width=1200" alt="元画像、AIモデル色、Full Spectrum変換色を比較する開発版ChromaMatter"></a></td>
    <td width="50%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038285-sNiOGxEzyLoRrklQAXH7BJ8W.png?width=1200" alt="ChromaMatterから出力したオリジナルロボットの3MFをSnapmaker Orcaで開いた状態"></a></td>
  </tr>
  <tr>
    <td align="center">3. 元画像／AIモデル色／印刷用変換色を比較</td>
    <td align="center">4. 4色と混色情報を含む3MFとして確認</td>
  </tr>
</table>

*画像は開発記録時点の画面を含みます。Snapmaker Orcaは第三者製品であり、ChromaMatterはSnapmaker、TripoAI、Hi3D AIその他第三者の公式・提携製品ではありません。*

<a id="palette-system"></a>
## 4本から、混色を含む最大32色へ

印刷に使う基本色はF1～F4の4本です。ChromaMatterはモデルの色域を見て、実在する同一素材のフィラメントから4本を提案し、その組み合わせで16／24／32色の印刷用パレットを構成します。

混色はF1+F2、F1+F3……という組み合わせごとにグラデーション順で表示します。画面、3MF、実機比較チャートで同じ並びと番号を使うため、「どの混色が、モデルのどこに使われているか」を追いやすくしています。

自動提案後にF1～F4を試しに変更した場合は、「現在の4色をプレビュー・3MFへ反映」で右側の変換previewと3MF paletteを更新できます。自動提案は既定のままで、現在の色番号とmanual paintを保って比較できます。

- PLAを既定とし、ABS／PETGはβです。
- 1つの印刷ジョブでは、PLAならPLAだけというように4本を同じ素材で揃えます。
- 異なる素材を混ぜるマルチマテリアル印刷は行いません。

<a id="filament-library"></a>
## 実際に入手できるフィラメントで考える

[![メーカー別に製品を探し、色差と仕上げを比較してF1からF4へ割り当てるフィラメント候補ライブラリ](https://assets.st-note.com/img/1787193878-2RMCKirmlunSDIXfhzQgEHpd.png?width=1200)](https://note.com/ponkichi0718/n/n711977c75aa4)

同梱ライブラリにはGeeetech、CC3D、Kingroon、TINMORRYなどを含む19ブランド・3,497色を収録しています。モデルの平均色だけへ近い4本を選ぶのではなく、黒・白・灰・彩色・肌／茶などの色域をカバーできる候補から提案し、似た色だけに偏るのを防ぎます。

カタログ色は候補を探すための近似値です。同じ製品でもロット、造形条件、表面、照明で見え方が変わるため、実物の色一致を保証するものではありません。特にABSはPLAより収録色が少ないため、目的色が存在しない場合があります。

<a id="calibration"></a>
## 混色を見える化し、実機へ近づける

[![画面の混色パレットと同じ順番で並ぶ、番号付きの実機比較チャート](https://assets.st-note.com/img/1787194049-FwXqus5ArK8B4NoU1eIQYzPg.png?width=1200)](https://note.com/ponkichi0718/n/n711977c75aa4)

現在のF1～F4から、番号付きの比較チャート3MFを生成できます。画面の予測色だけで決めず、同じプリンタ・フィラメント・造形条件で実際に出力して、狙った色に近い組み合わせを確認できます。

黒が想定より強く出る場合は、表示色や自動配色を変えず、3MFに記録する黒混色だけを弱める「実機黒補正」を利用できます。これは万能な色校正ではありません。Full Spectrumは物理フィラメントを層ごとに切り替えるため、透過率、壁、傾斜、最上層、プリンタの校正でも結果が変わります。最終判断は比較チャートとSnapmaker Orcaのスライスプレビューで行います。

<a id="manual-editing"></a>
## 自動変換のあとを、人が仕上げられる

[![ブラシ、エアブラシ、なじませ、スポイトでオリジナルの赤いロボットを補正するマニュアル修正画面](https://assets.st-note.com/img/1787193923-A1VTIhjR6w07qWedXZloDEFU.png?width=1200)](https://note.com/ponkichi0718/n/n711977c75aa4)

基本は自動提案ですが、AIモデル特有の色むらや、変換後に気になる場所だけを3D上で補正できます。

- 陰影、ガンマ、コントラスト、彩度の調整
- Brush、Airbrush、Fill、Smudge、Eyedropper
- 選択パーツと可視面を守る編集、Undo／Redo
- サイズ、面数、形状診断、対応するUV seamの閉立体化
- 全体3MFまたはパーツ別3MF、持ち運べるproject folder

閉立体化は、証明できる境界だけを安全に処理します。対応する分割GLBでは別パーツ同士を溶接せず、元面と修復面を区別して追跡します。Hi3D系の識別用疑似色も、exporter・node・material・texture・既知paletteの条件がすべて揃った場合だけ除外し、通常の作者指定色は残します。閉立体化前に3MF出力を始めた場合も、適格なmodelでは処理を宣言し、成功後に出力を再開します。すべての穴や壊れたモデルを自動修復する機能ではありません。0.9開発sourceの単一論理GLBは、証明できる完全一致seamを先に統合し、残った閉じた境界loopの幅が2.0 mm以下かつ平面性のずれが0.02 mm以下の場合だけ、厳密な局所平面capを追加できます。対応する分割GLBにも同じ微小開口上限を適用します。それより大きい穴、非平面・曖昧・non-manifoldな開口はfail-closedで停止し、修復後のmeshを出力前に再検証します。

出力3MFには安定したFull Spectrum layer-cycleとprime towerのbaselineを記録します。Local Z、advanced dithering、pointillism等の実験設定は有効化せず、supportはSnapmaker Orca側で選択します。最終判断は必ずOrcaのslice previewと実機testで行います。

## AI×3Dプリンタを、もう一つ前へ

AI 3D生成は、専門的なモデリング技術がなくても「作りたい形」を生み出せるようにしました。一方、カラー3Dプリンタは、複数の実フィラメントから画面上の色を物にできる可能性を持っています。ChromaMatterは、その二つの間に残っている色、材料、形状、出力形式のギャップを埋めるプロジェクトです。

生成AIが3Dプリントという新しい出口を得て、3DプリンタがAIモデルという新しい用途を得る。どちらか一方の補助ではなく、それぞれの価値を同時に高められることが、このプロジェクトの一番大きな可能性だと考えています。

公開済みWindows版は`0.8beta r32.2`で、現在の作業ソースは`0.9（r33）`開発版です。色再現、対応GLB、処理速度、実機校正には引き続き改善の余地があります。だからこそ、ソースを公開し、実際の失敗や調整も共有しながら育てていきます。

<a id="development-journal"></a>
## 開発記録とAI利用について

成功例だけでなく、黒の出方に悩んだ失敗、フィラメント選び、キャリブレーション、実機出力まで含む記録を[ponkichiのnote](https://note.com/ponkichi0718)で公開しています。

- [ChromaMatterへの改名と現行機能](https://note.com/ponkichi0718/n/n711977c75aa4)
- [公開用オリジナルモデルをAIで作る工程](https://note.com/ponkichi0718/n/nad23088e6f2d)
- [公開sampleの実機結果と分割GLB対応](https://note.com/ponkichi0718/n/nf6c77165127c)
- [このソフトを作り始めた理由と初期機能](https://note.com/ponkichi0718/n/nc7f466bf8078)

> **AI利用について：** ChromaMatterは、企画整理、仕様設計、実装、テスト、文書化、画像制作、GitHub公開作業の各段階でChatGPT／OpenAI CodexなどのAIを活用しています。最終的な仕様、採否、実機検証、公開判断はプロジェクト作者が行っています。AI生成のコード、画像、説明文には、不自然な表現や技術的な誤りが残る可能性があります。重要な印刷設定はソース、生成3MF、スライサープレビュー、ご自身の実機で確認してください。お気づきの点は[GitHub Issues](https://github.com/Ponkichi0718/ChromaMatter/issues)でお知らせください。

公開済み`v0.8beta-r32`と`v0.8beta-r32.1`はimmutableなprevious evidenceで、tag、asset、checksumを差し替えません。`v0.8beta-r32.2`は現在、評価用の**プレリリース**として公開しています。[Windows ZIPを直接ダウンロード](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-win64.zip)し、同じプレリリースページにある対応ソース、compliance asset、checksumと組み合わせて確認してください。単独で転載されたEXEは正規の配布確認に使わないでください。

r32.2は公開済みprereleaseです。`DemoData/3MF/`には、公開demo GLBから
派生した結合project 1件とpart別project 6件を収録しています。Hi3D由来のpart labelは
見た目のgeometryと一致しないためfilenameで判断せず、demoを再出力するときは
**必ず「黒弱め 5〜25%」presetを適用**してください。

r32.1 Windows packageの`DemoData/`に同梱した分割GLBでは、閉立体化から3MF出力までの完走を確認しています。GLBは **Generated by Hi3D** であり、Hi3D対応は非公式βです。ただし、他の分割modelでも成功する保証はありません。topology、開口境界、non-manifold geometry、非対応GLB機能、曖昧なpart provenanceが異なると、閉立体化または3MF出力が安全停止する場合があります。このmodel依存の制限も、公開済みr32.2を`0.8beta`としていた理由の一つです。
