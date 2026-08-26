# ChromaMatter public four-colour GLB / 公開4色GLB

## English

`ChromaMatter-Public-Four-Color-Test.glb` is generated during the macOS alpha
workflow by `generate_macos_alpha_test_glb.py`. It is a deterministic CC0 test
fixture made only from four elementary boxes; no AI service, reference image,
private model, brand, character, texture, or network input is used.

The GLB is deliberately small and simple:

- 1 scene, 1 node, 1 mesh, 1 `TRIANGLES` primitive
- 32 vertices and 48 triangles
- four separate positive-volume watertight bodies
- normalized unsigned-byte `COLOR_0` with exact red, blue, white, and black
- no image, texture, material, external URI, animation, skin, or private
  metadata
- deterministic SHA-256:
  `1b6092448e62a93f5e29a9c6dda1265a7a2179c2eacd293f7d8f02d1f268c563`

Suggested smoke test:

1. Open the GLB and confirm four coloured blocks appear.
2. In Full Spectrum, change the total palette colours from 16 to 32 and confirm
   that the preview recalculates. Then compare the Full Spectrum and Flat Four
   previews; all four source colours should remain easy to distinguish.
3. Try a small Manual Editing fill, then Undo and Redo.
4. Open Output Settings. The model is already watertight; Solidify should not
   invent caps or report an open boundary.
5. For a compact print test, set output height to about 20 mm.
6. Export 3MF and open it manually in Snapmaker Orca. Confirm all four blocks
   and their colour assignments are present.
7. Save and reload a ChromaMatter project containing this model.

This fixture verifies the selectable 32-state processing path and Flat Four
switching, but its four flat source colours do not force all 32 mixed states to
appear at once. It does not prove compatibility with large, textured, animated,
damaged, or generator-specific GLBs, colour accuracy of physical filament, or
printer safety.

The generator, this README, and the generated GLB are covered by
`samples/LICENSE.txt` (CC0 1.0 Universal). The macOS application alpha has
separate tester-only restrictions; the CC0 status of this test model does not
make the application bundle approved for redistribution.

## 日本語

`ChromaMatter-Public-Four-Color-Test.glb`は、macOS alpha workflow内で
`generate_macos_alpha_test_glb.py`から生成します。基本形状の直方体4個だけで
作った決定的なCC0 test fixtureです。AI service、reference画像、private model、
brand、character、texture、network入力は一切使用しません。

GLBの構成は次のとおりです。

- 1 scene、1 node、1 mesh、1つの`TRIANGLES` primitive
- 32頂点、48三角形
- 正の体積を持つ、互いに離れた閉立体4個
- 正規化unsigned byteの`COLOR_0`に、赤・青・白・黒を正確に記録
- image、texture、material、外部URI、animation、skin、private metadataなし
- 決定的SHA-256：
  `1b6092448e62a93f5e29a9c6dda1265a7a2179c2eacd293f7d8f02d1f268c563`

確認手順：

1. GLBを開き、色の異なるblockが4個表示されることを確認します。
2. Full Spectrumの混色数を初期値16から32へ変更し、previewが再計算されることを
   確認します。その後Full SpectrumとFlat Fourのpreviewを比較し、4色を区別
   できることを確認します。
3. Manual Editingで小さく塗りつぶし、UndoとRedoを確認します。
4. 出力設定を開きます。元から閉立体なので、閉立体化で不要な蓋を追加したり、
   開口境界として警告したりしないことを確認します。
5. 小さな造形testでは、出力高さを約20 mmにします。
6. 3MFを書き出してSnapmaker Orcaから手動で開き、4個のblockと色割当を
   確認します。
7. このmodelを含むChromaMatter projectを保存し、再読込します。

このfixtureでは、選択可能な32-state処理経路とFlat Fourへの切替を確認できます。
ただし元色は平坦な4色だけなので、32種類の混色stateすべてを同時に表示する
swatch chartではありません。大規模・texture付き・animation・破損・generator
固有GLBとの互換性、filamentの実発色、printerの安全性も証明しません。

generator、このREADME、生成GLBには`samples/LICENSE.txt`のCC0 1.0 Universalを
適用します。macOS app alphaには別のtester限定条件があります。このtest modelが
CC0であっても、app bundleの再配布が承認されたことにはなりません。
