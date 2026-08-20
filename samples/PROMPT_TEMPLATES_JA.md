# 頂点カラーOBJ生成用の汎用プロンプト

以下は、公開可能な検証モデルを新しく用意するときの出発点となる汎用プロンプトです。特定のサービス、企業、製品、作品、作者、画風、人物、キャラクター、ブランドを指定していません。本文は`LICENSE.txt`に従いCC0 1.0で提供します。

プロンプト自体がCC0であっても、生成物が自動的にCC0になるわけではありません。生成物の所有、利用、改変、公開、再配布の可否は、利用した生成サービスの規約、入力素材の権利、適用法を確認してください。

以下の文章はテンプレートです。実際に公開デモを生成するときは、入力した文章を省略せず権利記録へコピーし、negative prompt、seed、生成設定、サービス／プラン／日付も記録してください。seedを提供しないサービスでは「提供なし」と記録します。

## 1. 抽象的な幾何造形

```text
完全にオリジナルの抽象的な幾何造形を作成してください。全体は3個の見分けやすいパーツで構成し、それぞれを閉じた自己交差のない立体にしてください。薄すぎる面、空中に孤立した微小片、重複面、非多様体エッジを作らないでください。各パーツには明確に異なる色域を与え、明部から暗部へ緩やかに変化する頂点カラーを含めてください。出力OBJでは各頂点を v x y z r g b 形式とし、パーツごとに固有の o と g を設定してください。UV、テクスチャ、文字、ロゴ、紋章、既知の人物やキャラクターを使用しないでください。
```

## 2. 有機的なカラーテスト形状

```text
特定の生物や既存作品を模倣しない、完全にオリジナルの有機的なカラーテスト形状を作成してください。大きな本体、丸みのある上部、小さなアクセント部品の3パーツに分け、組み立て位置を保ったまま各パーツを独立した閉立体にしてください。表面には暖色、寒色、中立色を含む滑らかな頂点カラーの変化を設けてください。三角形の密度は均一にし、極端に細長い三角形、内部面、重複頂点、自己交差、開口を避けてください。OBJの頂点は v x y z r g b、パーツは o と g で明示してください。文字、ロゴ、ブランド、既知の人物、既知のキャラクター、既存作品の意匠は含めないでください。
```

## 3. パーツ別配色の検証モデル

```text
頂点カラー変換とパーツ別配色を検証するための、完全にオリジナルな小型3Dモデルを作成してください。単純な台座、中央の多面体、横に配置した小型部品の3つを作り、各部品は閉じた多様体メッシュにしてください。台座は青から水色、中央は白から紫と赤、小型部品は黄から緑へ変化させ、色の境界には急変と緩やかなグラデーションの両方を含めてください。各頂点に0から1のRGB値を保存し、OBJでは v x y z r g b を使用してください。各パーツを別々の o と g にし、面は三角形にしてください。テクスチャ、UV依存色、文字、ロゴ、既存のデザインやキャラクターは使わないでください。
```

## 4. 配布デモ用の完全オリジナル2D画像

```text
Create a completely original, non-branded full-body reference image for a small collectible 3D-print demonstration figure. Design a friendly abstract "chromatic garden guardian" that combines smooth botanical curves with simple geometric armour, without resembling any real person, known character, franchise, product, artist's style, culture-specific costume, or existing creature. Give it one broad stable body, a crown-like leaf shell, two rounded side ornaments, and a simple pedestal, with every major element clearly separated and thick enough to become a printable part. Use four distinct base colour families—cyan, warm magenta, golden yellow, and deep neutral grey—with smooth light-to-shadow transitions and several visible intermediate colours. Keep the silhouette readable, avoid weapons, text, letters, numbers, logos, watermarks, transparent materials, fur, complex lace, extremely thin projections, and floating details. Show a centred three-quarter front view on a plain light-grey background with the entire figure visible, even studio lighting, and no additional objects. This image must be a new design created only from this prompt and suitable as the authorised reference for generating and publicly distributing a demonstration 3D model, subject to the generation service's terms.
```

この画像を実際に配布または3D生成の入力へ使う場合は、画像生成サービス側についても契約プラン、規約、再配布条件、適用ライセンスを記録します。「この文章がオリジナル」であることと「生成画像を自由に再ライセンスできる」ことは別です。

## 5. 配布デモ用の完全オリジナル3Dモデル

```text
Create a new 3D-printable demonstration model based only on the authorised original "chromatic garden guardian" reference supplied with this request. Do not introduce any known character, franchise, brand, logo, text, real person's likeness, artist imitation, copyrighted costume, or unrelated design. Preserve the reference's overall proportions and colour layout while simplifying ambiguous details into clean original geometry. Build four logical, correctly positioned parts: pedestal, main body, crown-like leaf shell, and paired side ornaments grouped as one part. Each part must be a closed watertight manifold shell with consistent outward normals, no self-intersections, no internal duplicate surfaces, no zero-area faces, no floating fragments, and no features thinner than practical small-figurine printing permits. Keep contact and assembly areas broad and avoid fragile single-point connections. Use an even triangle density that supports smooth colour boundaries without unnecessary micro-triangles. Embed colour directly as per-vertex RGB in OBJ lines using v x y z r g b values from 0 to 1; do not rely on textures, UV maps, or MTL colours. Preserve four primary colour families—cyan, warm magenta, golden yellow, and deep neutral grey—and include smooth intermediate shading that can demonstrate a 16-state mixed-filament palette. Give each logical part its own descriptive o and g names. Export the assembled pose as one OBJ while retaining those explicit part markers.
```

生成サービスが頂点カラーOBJや閉じたパーツを保証しない場合、この文章は目標仕様として扱い、ChromaMatterで開く前に実ファイルを診断します。画像入力を使った場合は、その画像のファイル名とSHA-256も権利記録へ追加します。

## 共通の除外指示

生成サービスが除外指示へ対応している場合は、次を追加できます。

```text
除外: 既知の人物、既知のキャラクター、既存作品、ブランド、ロゴ、文字、透かし、署名、武器の意匠、宗教的または政治的な記号、実在製品の外観、コピーされた造形、開いたメッシュ、内部面、重複面、自己交差、非多様体、浮遊する微小片、極端に薄い部品、テクスチャだけで表現した色。
```

生成後は、頂点カラーが実際にOBJの各`v`行へ含まれていること、各パーツが`o`または`g`で分かれていること、公開・再配布できる生成物であることを個別に確認してください。
