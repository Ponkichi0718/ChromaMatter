# Filament database attribution

The bundled `filament_color_database_2026-08.sqlite` combines catalog data,
a small set of physical swatch measurements, and a separate dated table of
Amazon.co.jp manufacturer-qualification evidence. It does not imply current
availability, endorsement, or a guaranteed printed-color match.

## Open Filament Database catalog data

- Source: OpenFilamentCollective, Open Filament Database
- Existing 15-brand PLA base snapshot: `v2026.07.31`
- ABS/PETG extension and four budget-brand PLA/ABS/PETG snapshot:
  `v2026.08.16`
- Extension commit:
  `81b06c646ef310fe7911cb230f96094e78bdeb43`
- Source URL: <https://github.com/OpenFilamentCollective/open-filament-database>
- License: MIT
- Governing text: `LICENSE_OPEN_FILAMENT_DATABASE.txt`
- Changes made by ChromaMatter: selected active single-colour PLA, ABS and
  PETG variants; normalized material labels to `PLA`/`ABS`/`PETG`; calculated
  Lab/HSV and finish penalties; retained stable upstream UUIDs in record IDs;
  and excluded multi-colour arrays rather than guessing one colour.

## Amazon.co.jp manufacturer qualification

- Retrieval date: 2026-08-19
- Stored fields: manufacturer, representative material/product label, ASIN,
  product URL, rating, review count, search query, date and acceptance rule
- Acceptance rule: rating at least 4.0 **and** at least 20 reviews
- Scope: manufacturer qualification only for Geeetech, CC3D, Kingroon and
  TINMORRY
- Storage: `amazon_jp_evidence` table, separate from `catalog_colors`

These changing marketplace facts are not a colour-data source. Qualification
of a representative product permits the manufacturer's OFD-backed
PLA/ABS/PETG catalog to be included; it does not state that each colour/SKU is
individually reviewed or currently in stock. No Amazon image was used to infer
a HEX value. AmazonBasics was excluded because a current own-brand PLA listing
was not found in the checked Amazon.co.jp results.

## FilamentColors.xyz measured swatches

- Attribution: FilamentColors.xyz
- Source: <https://filamentcolors.xyz/>
- Licensing statement: <https://filamentcolors.xyz/about/>
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)
- License URL: <https://creativecommons.org/licenses/by/4.0/>
- Governing text: `LICENSE_CC_BY_4.0.txt`
- Scope used here: 41 physical measured PLA swatches
- Per-record source: the original swatch page is retained in each
  `measured_swatches.source_url` value in the SQLite database.
- Changes made by ChromaMatter: selected a PLA-focused subset; normalized HEX
  values; normalized the catalog relationship; and calculated Lab and derived
  CIEDE2000/Delta E values for matching and review.
- Original measured-dataset retrieval and build date: 2026-08-07

The FilamentColors.xyz About page states that images, text, and data on the
production application are licensed under CC BY 4.0. This attribution identifies
the adapted material, links its source and license, and describes the changes.
