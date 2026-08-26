# 公開用サンプル

このフォルダーでは、プロジェクトが直接作成したCC0の合成サンプルと、今後追加する可能性がある生成サービス由来の公開専用デモを明確に分けます。

## CC0の合成回帰サンプル

`synthetic_multipart_vertex_color.obj`は、実在の人物、キャラクター、製品、ブランド、生成サービスの出力に依存せず、このプロジェクトの公開検証用としてゼロから作成した小型の合成モデルです。個人所有の実モデルや元画像を配布せずに、OBJ読込、パーツ認識、頂点カラー、閉鎖性、色変換を再現確認する目的で使用します。

macOS alpha協力テスト用の`ChromaMatter-Public-Four-Color-Test.glb`は、
`generate_macos_alpha_test_glb.py`からworkflow内で決定的に生成します。基本形状の
直方体4個と赤・青・白・黒の`COLOR_0`だけで構成し、外部texture、private metadata、
生成service由来素材を含みません。構成と確認手順は
`MACOS_ALPHA_TEST_MODEL_README.md`を参照してください。GLB binaryはrepositoryへ
直接保存せず、テスター成果物を作るworkflow内で生成します。

## サンプルの構成

- 頂点18個、三角形24面
- `o`と`g`で明示した3パーツ
- すべての頂点が`v x y z r g b`形式
- RGBは0～1の正規化値
- 直方体、八面体、四面体からなる、互いに独立した閉じた単純形状
- UV、テクスチャ、MTL、ロゴ、文字、既知のキャラクターデザインを不使用

期待されるパーツ名は次の3つです。

1. `Calibration_Base`
2. `Gradient_Octahedron`
3. `Accent_Tetrahedron`

## ChromaMatterでの確認手順

1. `synthetic_multipart_vertex_color.obj`を開きます。
2. 3パーツとして認識され、元の配置と頂点色が維持されていることを確認します。
3. パーツ処理の状態で、問題のある開口境界が0件であることを確認します。
4. 変換色プレビューで、各面の色が16色以内の設定へ割り当てられることを確認します。
5. 必要に応じてマニュアル修正、プロジェクト保存、3MF出力を確認します。

このファイルは小さな回帰テスト用です。複雑な実モデルの処理速度、微小穴修復、自己交差修復、実際のフィラメント発色、スライサーや実機での造形品質を証明するものではありません。

## テキスト上の簡易確認

リポジトリのルートで次を実行すると、基本構成を確認できます。

```powershell
rg -c "^v " samples\synthetic_multipart_vertex_color.obj  # 18
rg -c "^f " samples\synthetic_multipart_vertex_color.obj  # 24
rg -c "^o " samples\synthetic_multipart_vertex_color.obj  # 3
rg -c "^g " samples\synthetic_multipart_vertex_color.obj  # 3
```

## 公開条件

このフォルダー内の合成OBJ、説明文、プロンプト本文は`LICENSE.txt`に従いCC0 1.0で提供します。プロンプトを外部サービスへ入力して生成したファイルは、このサンプルのCC0対象には自動的には含まれません。生成物を使用または配布できる範囲は、利用したサービスの規約、入力素材の権利、適用法を利用者自身で確認してください。

## 将来の公開専用デモ

完全にオリジナルな汎用プロンプトから新規生成した2D画像、頂点カラーOBJ、ChromaMatterが出力した3MFを、デモンストレーション用として配布する計画です。実ファイルはまだこのフォルダーへ追加していません。

追加時は、デモごとに`DEMO_MODEL_RIGHTS_RECORD_TEMPLATE_JA.md`から権利記録を作成し、生成サービス／プラン／日付／モデルID、正確なpromptとseed、入力画像権利、第三者IPの確認、再配布可否、適用ライセンス、attribution、各ファイルのSHA-256を記録します。生成サービスの条件がCC BY 4.0の場合、合成サンプル用の`LICENSE.txt`は適用せず、デモ固有のCC BY 4.0表示を維持します。
