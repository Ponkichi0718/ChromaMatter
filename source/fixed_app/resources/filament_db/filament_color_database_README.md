# Filament Color Database (2026-08)

- Build date: 2026-08-19
- Materials: PLA (default), ABS, PETG
- Scope: 19 brands and 3,497 active single-colour catalog variants
  - PLA: 2,577
  - ABS: 268
  - PETG: 652
- Physical measured swatches: 41 (PLA)
- Color pipeline: sRGB D65 -> CIELAB D65 -> CIEDE2000

The canonical SQLite filename is `filament_color_database_2026-08.sqlite`.
The file contains three materials; the UI still starts in PLA mode.

This offline database powers **Filament candidates beta** and the owned
filament picker. For each base slot F1-F4, ChromaMatter can show up to three
close candidates in the selected material, ranked with CIEDE2000
(`Delta E 00`). A row is explicitly identified as a physical measurement or a
catalog/display value.

## Catalog snapshots

- Existing 15-brand PLA base: Open Filament Database `v2026.07.31`
- ABS/PETG extension for those brands: OFD `v2026.08.16`
- Geeetech, CC3D, Kingroon and TINMORRY PLA/ABS/PETG: OFD `v2026.08.16`
  (commit `81b06c646ef310fe7911cb230f96094e78bdeb43`)

Only active variants with one OFD `color_hex` are imported. Gradient and
co-extruded arrays are not silently reduced to their first colour.

## Budget-brand qualification

The four added budget manufacturers were qualified at the **manufacturer
level**, not separately for every colour or SKU. On 2026-08-19 at least one
representative Amazon.co.jp filament result for each manufacturer met the
conservative rule:

`rating >= 4.0 AND review_count >= 20`

Fourteen dated result records (ASIN, URL, rating, review count, query and
material) are stored in the separate `amazon_jp_evidence` table. They are
evidence for including the manufacturer's OFD catalog only. They do **not**
mean that every catalog colour was reviewed, and they are never used to infer
HEX values, stock, price, print quality, or colour accuracy. AmazonBasics was
reviewed as a candidate but excluded because no current own-brand PLA result
was found in the checked Amazon.co.jp search.

## Important limitations

1. `reference_hex` is an OFD catalog/display value, not a guaranteed physical
   print measurement.
2. `catalog_active (OFD)` only means "not marked discontinued" in the pinned
   source snapshot; it is not live inventory.
3. Amazon ratings, review counts, prices and availability can change at any
   time. ChromaMatter is not affiliated with or endorsed by the listed stores
   or manufacturers.
4. Gloss, matte texture, translucency, layer height, nozzle, temperature,
   lighting, camera, and filament lot all change perceived color.
5. The 41 physical measurements are PLA-only. An unlinked measured swatch is
   treated as PLA for compatibility.
6. ABS has substantially fewer OFD-backed colours than PLA in this snapshot.
   A material count is catalog coverage, not a guarantee that the desired
   colour gamut can be reproduced.
7. Amazon manufacturer qualification is evidence of marketplace review volume,
   not evidence of colour accuracy or material-specific colour coverage.
8. For production accuracy, print a standardized swatch and measure it with a
   colorimeter under controlled conditions.

## Recommended matching order

1. Select exactly one material: PLA, ABS, or PETG (PLA is the initial mode).
2. Convert the target sRGB hex to Lab (D65).
3. Filter `comparison_eligible = 1` and the selected material.
4. Filter finish and owned inventory if requested.
5. Compute CIEDE2000.
6. Rank by `deltaE00 + finish_penalty`.
7. Prefer a physical-measurement row when available for that material.

Candidate names are reference information, not live stock information or a
purchase recommendation.

## Reproducible update

`tooling/update_budget_filament_library.py` rebuilds the OFD extension and the
dated Amazon evidence table from the pinned OFD checkout. It preserves every
existing base-PLA record ID. Amazon pages are not scraped by the build script;
their dated factual snapshot is deliberately reviewed and committed.

## Files

- `filament_color_database_2026-08.sqlite` — application integration
- `filament_color_database_README.md` — scope and matching limitations
- `ATTRIBUTION.md` — sources, attribution, and changes made
- `LICENSE_OPEN_FILAMENT_DATABASE.txt` — Open Filament Database MIT text
- `LICENSE_CC_BY_4.0.txt` — FilamentColors.xyz data license text
