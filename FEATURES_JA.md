# ChromaMatterでできること

## AIで生まれた色を、4本のフィラメントで現実へ

ChromaMatter — AI Model Print Studioは、AI生成された色付き3Dモデルを、Snapmaker OrcaのFull Spectrum／Color Mixingワークフロー向け3MFへ変換・調整するWindowsデスクトップツールです。

このプロジェクトが目指しているのは、単なるファイル変換ではありません。AI 3D生成には「実際にカラー造形する出口」を、カラー3Dプリンタには「AIが生み出す多様なモデルという新しい入力」をつくることです。画面の中で完結していた生成モデルと、物を作れる3Dプリンタの間をつなぐことで、双方の利用価値を一段高めます。

[![ChromaMatterの現行開発画面。4本の基本フィラメント、混色パレット、元モデル色とFull Spectrum変換色を並べて確認できる](https://assets.st-note.com/img/1787193863-DjEUKLdVrxFgauov4mzq7QB9.png?width=1200)](https://note.com/ponkichi0718/n/n711977c75aa4)

*開発中画面。4本の実フィラメントから作る混色パレットと、元モデル色／印刷用変換色を同時に確認できます。*

## AIモデルから3MFまでを、ひとつの流れに

頂点カラー付きOBJ、または埋め込みbaseColor／`COLOR_0`を持つ静的GLBを読み込めます。TripoAIだけでなく、Hi3D AIのようにGLBを出力するサービスも同じ制作フローへ取り込めます。モデルの処理はローカルで行い、ChromaMatterから外部サーバーへアップロードしません。

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

## 4本から、混色を含む最大32色へ

印刷に使う基本色はF1～F4の4本です。ChromaMatterはモデルの色域を見て、実在する同一素材のフィラメントから4本を提案し、その組み合わせで16／24／32色の印刷用パレットを構成します。

混色はF1+F2、F1+F3……という組み合わせごとにグラデーション順で表示します。画面、3MF、実機比較チャートで同じ並びと番号を使うため、「どの混色が、モデルのどこに使われているか」を追いやすくしています。

自動提案後にF1～F4を試しに変更した場合は、「現在の4色をプレビュー・3MFへ反映」で右側の変換previewと3MF paletteを更新できます。自動提案は既定のままで、現在の色番号とmanual paintを保って比較できます。

- PLAを既定とし、ABS／PETGはβです。
- 1つの印刷ジョブでは、PLAならPLAだけというように4本を同じ素材で揃えます。
- 異なる素材を混ぜるマルチマテリアル印刷は行いません。

## 実際に入手できるフィラメントで考える

[![メーカー別に製品を探し、色差と仕上げを比較してF1からF4へ割り当てるフィラメント候補ライブラリ](https://assets.st-note.com/img/1787193878-2RMCKirmlunSDIXfhzQgEHpd.png?width=1200)](https://note.com/ponkichi0718/n/n711977c75aa4)

同梱ライブラリにはGeeetech、CC3D、Kingroon、TINMORRYなどを含む19ブランド・3,497色を収録しています。モデルの平均色だけへ近い4本を選ぶのではなく、黒・白・灰・彩色・肌／茶などの色域をカバーできる候補から提案し、似た色だけに偏るのを防ぎます。

カタログ色は候補を探すための近似値です。同じ製品でもロット、造形条件、表面、照明で見え方が変わるため、実物の色一致を保証するものではありません。特にABSはPLAより収録色が少ないため、目的色が存在しない場合があります。

## 混色を見える化し、実機へ近づける

[![画面の混色パレットと同じ順番で並ぶ、番号付きの実機比較チャート](https://assets.st-note.com/img/1787194049-FwXqus5ArK8B4NoU1eIQYzPg.png?width=1200)](https://note.com/ponkichi0718/n/n711977c75aa4)

現在のF1～F4から、番号付きの比較チャート3MFを生成できます。画面の予測色だけで決めず、同じプリンタ・フィラメント・造形条件で実際に出力して、狙った色に近い組み合わせを確認できます。

黒が想定より強く出る場合は、表示色や自動配色を変えず、3MFに記録する黒混色だけを弱める「実機黒補正」を利用できます。これは万能な色校正ではありません。Full Spectrumは物理フィラメントを層ごとに切り替えるため、透過率、壁、傾斜、最上層、プリンタの校正でも結果が変わります。最終判断は比較チャートとSnapmaker Orcaのスライスプレビューで行います。

## 自動変換のあとを、人が仕上げられる

[![ブラシ、エアブラシ、なじませ、スポイトでオリジナルの赤いロボットを補正するマニュアル修正画面](https://assets.st-note.com/img/1787193923-A1VTIhjR6w07qWedXZloDEFU.png?width=1200)](https://note.com/ponkichi0718/n/n711977c75aa4)

基本は自動提案ですが、AIモデル特有の色むらや、変換後に気になる場所だけを3D上で補正できます。

- 陰影、ガンマ、コントラスト、彩度の調整
- Brush、Airbrush、Fill、Smudge、Eyedropper
- 選択パーツと可視面を守る編集、Undo／Redo
- サイズ、面数、形状診断、対応するUV seamの閉立体化
- 全体3MFまたはパーツ別3MF、持ち運べるproject folder

閉立体化は、証明できる境界だけを安全に処理します。閉立体化前に3MF出力を始めた場合も、適格なmodelでは処理を宣言し、成功後に出力を再開します。すべての穴や壊れたモデルを自動修復する機能ではなく、本当の穴へ推測で蓋は追加しません。

出力3MFには安定したFull Spectrum layer-cycleとprime towerのbaselineを記録します。Local Z、advanced dithering、pointillism等の実験設定は有効化せず、supportはSnapmaker Orca側で選択します。最終判断は必ずOrcaのslice previewと実機testで行います。

## AI×3Dプリンタを、もう一つ前へ

AI 3D生成は、専門的なモデリング技術がなくても「作りたい形」を生み出せるようにしました。一方、カラー3Dプリンタは、複数の実フィラメントから画面上の色を物にできる可能性を持っています。ChromaMatterは、その二つの間に残っている色、材料、形状、出力形式のギャップを埋めるプロジェクトです。

生成AIが3Dプリントという新しい出口を得て、3DプリンタがAIモデルという新しい用途を得る。どちらか一方の補助ではなく、それぞれの価値を同時に高められることが、このプロジェクトの一番大きな可能性だと考えています。

まだ`0.8beta`であり、色再現、対応GLB、処理速度、実機校正には改善の余地があります。だからこそ、ソースを公開し、実際の失敗や調整も共有しながら育てていきます。

## 開発記録とAI利用について

成功例だけでなく、黒の出方に悩んだ失敗、フィラメント選び、キャリブレーション、実機出力まで含む記録を[ponkichiのnote](https://note.com/ponkichi0718)で公開しています。

- [ChromaMatterへの改名と現行機能](https://note.com/ponkichi0718/n/n711977c75aa4)
- [公開用オリジナルモデルをAIで作る工程](https://note.com/ponkichi0718/n/nad23088e6f2d)
- [このソフトを作り始めた理由と初期機能](https://note.com/ponkichi0718/n/nc7f466bf8078)

> **AI利用について：** ChromaMatterは、企画整理、仕様設計、実装、テスト、文書化、画像制作、GitHub公開作業の各段階でChatGPT／OpenAI CodexなどのAIを活用しています。最終的な仕様、採否、実機検証、公開判断はプロジェクト作者が行っています。AI生成のコード、画像、説明文には、不自然な表現や技術的な誤りが残る可能性があります。重要な印刷設定はソース、生成3MF、スライサープレビュー、ご自身の実機で確認してください。お気づきの点は[GitHub Issues](https://github.com/Ponkichi0718/ChromaMatter/issues)でお知らせください。

現時点でGitHubに公開しているのはソースコードです。Windowsバイナリは第三者依存関係の再配布条件を確認中のため、まだ公開していません。
