# ChromaMatter — AI Model Print Studio 0.8beta (r32.2 published source)

<p align="center">
  <img src="assets/obj_adjuster_icon.png" width="160" alt="ChromaMatter icon">
</p>

[Japanese](README_fixed_ja.md)

This directory contains the fixed ChromaMatter — AI Model Print Studio source
application. The display version is `0.8beta`, the published edition is
`AI Model Print Studio r32.2`, and the artifact revision is
`r32.2-ai-model-print-studio`; the Windows numeric version remains `0.8.0.0`.

> **Windows download:** [Download ChromaMatter 0.8beta r32.2 for Windows](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-win64.zip)
>
> **Release page:** [v0.8beta-r32.2](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2)
>
> The published build and corresponding source are frozen at commit `aba20685d2fd6987621b2e1e6624f46ea84912a3`.

> **0.8beta multipart limitation:** the bundled `DemoData/` model is a confirmed successful case, but other multipart models can still fail solidification or 3MF export. Multipart repair is not yet reliable for every input; this is one reason the product is labelled `0.8beta`.

See the [visual feature overview and production flow](../../FEATURES_EN.md) and the [development journal, including experiments, failures, and hardware calibration](https://note.com/ponkichi0718).

## r32.2 published prerelease

r32.2 keeps the r32.1 application and fail-closed 3MF contracts and includes
seven derived demo outputs under `DemoData/3MF/`: one combined six-mesh project
and six part-specific projects. Hi3D-derived part labels can disagree with visible
geometry, so inspect every part rather than trusting its filename. When
regenerating the demo, **always apply the Weak Black 5–25% preset before 3MF
export**. Multipart solidification remains unstable beta compatibility. The
exact build, source, package, fresh extraction, checksums, and publication gates passed.

## Flat Four Test 3 publication candidate

This branch is preparing a separate Test 3 prerelease candidate without
changing the published r32.2 Windows package, its frozen source tag, or the
frozen Flat Four Test 2 assets:

- Flat Four derives a deterministic, area-weighted proposal of four distinct
  physical filament colours, creates no mixed recipes, and writes only F1-F4
  into its 3MF colour path.
- White is not removed globally. Eye whites beside dark linework and other
  meaningful small white details remain white targets, while only small,
  high-confidence white/gray lighting patches on a smooth chromatic surface
  such as skin are folded into the chromatic F slot used around their boundary.
- Retained white covering at least 0.01% of total printable area reserves one
  suitable near-white physical filament. Below 0.01%, white remains unabsorbed
  but does not by itself force a white spool and can map to the nearest selected
  F1-F4 colour.
- Four physical F slots and 3MF state metadata are retained even when an output
  effectively uses three paint IDs. Manual Editing remains authoritative, and
  Full Spectrum behaviour is unchanged.
- This is not semantic recognition. A tiny white patch enclosed by one smooth
  skin/tan surface without a dark edge, crease, or part boundary may be absorbed.
  Above 500,000 faces on an open mesh without reusable adjacency, only this
  automatic correction is skipped fail-closed.
- The experimental 2D Colour Filter offers Cel Colour and Shaded Monochrome.
  It bakes fixed-front, geometry-aware stepped shading into printable colour;
  it does not create missing line art, PBR material response, or texture detail.
- Normal static-GLB limits remain 512 MiB, three million vertices, and three
  million triangles. A separate fail-closed beta path can admit a static
  `TRIANGLES` scene with 3,000,001-5,000,000 triangles only after explicit
  confirmation and with face-count adjustment enabled, producing a working
  model of at most 450,000 faces. Reduction can remove fine detail.
- New projects use `obj-adjuster.project.v13`; v12 remains readable and defaults
  to legacy Full Spectrum mode.

The candidate working tree passed 1,431 tests with zero failures and three
optional skips, plus an owner-only clean-build/fresh-extract preflight. That
preflight is not public Release evidence: Test 3 still requires an exact source
commit, clean rebuild, complete corresponding source, compliance assets,
checksums, fresh-extract audit, and publication verification. Physical-printer
validation of the exact Test 3 package is pending.

## r32.1 published previous evidence

r32.1 tag `v0.8beta-r32.1` preserves the r32 modelling and 3MF contracts, changes the public preview
heading to `AI Model Color`, and packages a rights-cleared Hi3D multipart GLB
plus reference image under `DemoData/`. Its prerelease is immutable published
previous evidence and does not validate r32.2.

## r32 output workflow

- When export finds safely matched part boundaries or coincident GLB seams, ChromaMatter announces solidification and resumes export only after it succeeds. Supported multipart GLB keeps separate parts unwelded and applies strict validation to both combined and individual 3MF output.
- Categorical `COLOR_0` in supported Hi3D-style multipart data is suppressed only when exporter, node, material, texture, and known-palette evidence all agree; ordinary authored colour remains unchanged.
- After an individual F1-F4 edit, `Apply Current F1-F4 to Preview / 3MF` updates the right preview and 3MF palette. Automatic proposal remains the default.
- The 3MF records a stable Full Spectrum layer-cycle and prime-tower baseline. Experimental Local Z, advanced dithering, and pointillism remain off, and support stays selectable in Orca.

## GLB input beta

- `Open OBJ / GLB` feeds both `v x y z r g b` vertex-colour OBJ and static GLB with embedded base colour / `COLOR_0` into the common pipeline.
- Scene/node transforms and mesh-node parts are preserved. sRGB textures are filtered and composed in linear space before being baked to vertex colour. Bundle v2 uses `source_asset` and `source.glb`, while legacy OBJ bundle v1 remains readable.
- PBR maps beyond base colour, alpha, animation, skinning, morph targets, Draco, meshopt, BasisU, GPU instancing, and external URIs are unsupported. Texture detail is limited to mesh-vertex resolution; limits are 512 MiB, three million vertices, and three million triangles.
- Supported exploded multipart GLB assets retain their source part structure during per-part normalisation. Individual 3MF export rebases part IDs and vertex references locally and fails closed when the mapping or proof is incomplete or stale.

## r30 single-GLB UV-seam solidification

- Explicit Solidify on a single GLB without part markers accepts apparent openings as UV/texture seams only when coincident boundary edges prove an exact 1:1 reversed pairing.
- Proven seams are vertex-welded before cleanup and QEM. No face is added, removed, or reordered and no part ID changes, so manual paint and adaptive trees retain exact ordered-face carry.
- This path adds no caps. Unmatched, same-direction, or ambiguous boundaries, a non-manifold result, and true holes fail closed while retaining the original geometry.
- Strict 3MF topology checks inspect every `type=model` resource. After mandatory checks pass, a bounded minor QEM self-intersection produces a warning and requires a project-open slice-preview check in Snapmaker Orca.

## r30 Manual Editing

- Pending Airbrush guidance is screen-space feedback. Zoom, pan, orbit, or a programmatic camera change suppresses it immediately, so old trail coordinates are never redrawn into a transformed view.
- The accepted commit token and one-stroke / one-Undo transaction remain alive until the exact frame even after the guide is hidden. Only committed 3D colour is drawn into the new view.
- A batch reads effective state only for candidate roots and reuses validated geometry arrays.
- A compatible nine-layer Airbrush traverses the adaptive tree once; legacy, non-concentric, or non-conforming geometry uses the safe sequential fallback.

## Public UI

- The main window has compact Filament Settings and Output Settings pages.
- The header presents the bundled PNG logo with compact two-line `ChromaMatter` and `AI Model Print Studio` text.
- F1-F4 are compact, and the mixed palette is a read-only, fixed-ratio, F-pair family-major swatch strip.
- Mixed-swatch numbers are presentation-only. Canonical state IDs, manual paint, projects, and 3MF recipes are not renumbered.
- Calibration charts use the same display order while retaining canonical provenance.
- A common 16 / 24 / 32-state choice propagates to existing parts; an explicit part edit remains local.
- The `Reset Four Base Colors` button is not shown in the public UI. Automatic proposals and individual editing remain available.
- `Apply Current F1-F4 to Preview / 3MF` explicitly applies individually edited base colours.
- Physical black correction stays in the mixed-palette frame, geometry reprocessing is one action, and the repair action is labelled Solidify.

## Portable project folder

The standard bundle contains:

```text
source.obj | source.glb
project.json
prepared_geometry.npz
reference.<ext>  # optional
```

Matching snapshots restore prepared geometry and manual paint exactly. Legacy JSON remains readable, but the original OBJ or GLB is selected explicitly when the source cannot be resolved safely.

## Filament candidates beta

- Choose PLA (default), ABS beta, or PETG beta. Each F1-F4 slot lists up to three nearby products from only the selected material and identifies measured versus catalog values with Delta E 00.
- Automatic proposals map real products of the selected material to gamut-balanced anchors before selecting four spools. This prevents the expanded database from collapsing to four similar browns near the model-wide average. Multi-colour and gradient products remain in the manual library but are excluded from automatic proposals.
- In a representative red, black, grey, and brown model software-fit diagnostic, area-weighted coverage within `Delta E 76 <= 12` improved from 28.63% to 98.37%. This is not a printed-colour guarantee.
- All four spools must use one material. A print job never mixes polymers, and the 3MF stores the matching `Generic PLA`, `Generic ABS`, or `Generic PETG` profile.
- ABS has fewer cataloged/measured colors and a smaller gamut than PLA. Missing target colors are approximated within ABS; PLA is never used as fallback. Verify with a physical comparison chart and use a Top Cover on U1.
- Catalog-active status does not guarantee current stock, purchasing availability, spool-lot consistency, or printed colour.
- Automatic four-colour selection uses only the selected material from `%APPDATA%\TripoSpectrumMapper\owned_filaments.json`; it is an approximate beta search, so verify special finishes with a small physical mixing swatch.

## Run

Use a Python 3.13 environment with the required dependencies:

```powershell
python .\TripoSpectrumMapper_fixed.py
python .\TripoSpectrumMapper_fixed.py --self-test
```

Repository-root `BOOTSTRAP_WINDOWS.ps1` is the standard setup and test entry point. r32.2 requires `-PyTetWildWheel C:\path\to\pytetwild-0.3.0-cp312-abi3-win_amd64.whl` (or `-PyTetWildWheelhouse`) because the application lock pins the controlled repaired wheel, not the historical PyPI wheel. The matching official complete corresponding-source release asset stores it under `build-evidence/pytetwild/repaired-wheel/`; `-SkipInstall` is only for an already verified environment.

## r32.2 published validation state

- Exact-tag full regression: 1,298 tests; 1,296 passed, 2 optional skips, 0 failures. The manifest-locked DemoData package contains 10 payloads and seven 3MF projects.
- Exact-commit clean build, packaged/fresh-extracted self-test, Japanese/English UI smoke, source/software stage, final archive/privacy/checksum verification, publication, and unauthenticated redownload: **passed**.
- Source publication eligibility: **true**. Binary publication eligibility: **true** for the exact tagged r32.2 assets.
- The following r32.1 results are immutable previous evidence only.

- Published r32.1 is frozen at commit `b575b93d973ed67e7ada986469b10b4490eef4e5`.
- Focused r32.1 release tests: 113 passed / 0 failed.
- Full r32.1 regression: 1,277 tests total, 1,274 passed / 3 optional skips / 0 failed.
- Packaged self-test and Japanese/English UI smoke passed for the final package and its independent fresh extraction.
- Fail-closed compliance inventory passed for 1,455 files, including 256 native files.
- The Windows package contains 1,518 files and has SHA-256 `1215CF77D8C8CB8AA5CE91DC7C84AE13404F3AA46221321807AD2E8A19F9064A`.
- The complete corresponding-source bundle is `release-approved`, reports no known gaps, and has SHA-256 `D5A64F3022265BCE7C5C2DFA0358DFC2C94EEA541A5A4AC5671CE3BA829BE4CC`.
- All six GitHub Release assets were independently downloaded without authentication and matched their published sizes and SHA-256 values.
- r32.1 source publication eligibility: **true**. r32.1 binary publication eligibility: **true** only for the exact tagged assets above.
- the r32.1, r32, and r31 results below are **previous evidence** and do not validate r32.2

- previous evidence for the post-GLB r28 candidate immediately before the public-UI change: Python `3.13.14`, PyInstaller `6.20.0`, `Ran 992 tests in 87.406s: OK (skipped=1)`, 991 passed / 1 optional skip
- that candidate's clean one-folder build in a new short path: passed
- that candidate's built-package self-test: exit 0 with `pymeshlab=available`, `glb_import_smoke=true`, and overall `ok=true`
- that candidate's built-package Japanese/English UI smoke with isolated profiles: passed
- that candidate's public-source/software ZIP restage, fresh extract, manifest/all-file hash/CRC/path-safety/privacy audit, Downloads placement, and external `SHA256SUMS`: PASS (source 223/222; software 1404/1403)
- Creator Studio r29 exact-source **previous evidence**: Python `3.13.14`, `Ran 998 tests in 83.529s: OK (skipped=1)`, 997 passed / 1 optional skip
- r29 clean-build previous evidence: `C:\OBJAdjR29FIX1`, PyInstaller `6.20.0` one-folder build, packaged `--self-test` exit 0, and isolated-profile Japanese/English UI smoke: passed
- Creator Studio r30 exact-source **previous evidence**: Python `3.13.14`, `Ran 1019 tests in 86.932s: OK (skipped=1)`, 1018 passed / 1 optional skip; PyInstaller `6.20.0` clean build at `C:\OBJAdjR30FIX1`, package/stage/archive/privacy, and detached `SHA256SUMS-r30.txt` contract passed. This evidence does not apply to r31.
- ChromaMatter r31 exact-source previous evidence: Python `3.13.14`, `Ran 1024 tests in 100.656s: OK (skipped=1)`, 1023 passed / 1 optional skip; PyInstaller `6.20.0` clean build at `C:\OBJAdjR31CM1`, built-package self-test, and isolated-profile Japanese/English UI smoke passed; preflight `ChromaMatter.exe` 13,986,866 bytes, FileVersion/ProductVersion `0.8beta`, InternalName `ChromaMatter`, OriginalFilename `ChromaMatter.exe`, SHA-256 `208167A225A37BAAAA473B574B2F746E46427FD0CA63FC5B7201BF3394243743`
- r31 preflight public source: 227 files / 226 manifest records, exact fresh archive, privacy technical GO. Software: 1,404 files / 1,403 manifest records, technical GO. Fresh-extracted self-test and Japanese/English UI smoke: exit 0
- r31 final source-only stage `ChromaMatter_0.8beta-r31-source-public-20260820`: 227 files / 226 manifest records; folder/archive parity, CRC, privacy, 32 staged identity/icon/tooling tests, Downloads placement, and external detached `SHA256SUMS-r31.txt` verification passed
- Creator Studio r27 previous evidence: Python `3.13.14`, PyInstaller `6.20`, and `Ran 890 tests in 68.257s: OK (skipped=1)`, 889 passed / 1 optional skip
- preflight clean build and self-test plus Japanese and English UI smoke on both the built package and a fresh extract: passed
- preflight EXE: 13,683,090 bytes, version `0.8beta`, SHA-256 `F2AB0AF025430FF3D5587D6C7B2A68365B8C091A7775697A24DDB84DF34EF056`
- preflight public source: 204 files / 203 manifest records
- preflight software: 1,340 files / 1,339 manifest records
- preflight ZIP structure, manifest equality, path safety, CRC, and privacy: passed
- r27 previous-evidence release state: `source-published`
- r27 previous-evidence final ZIP SHA-256: `null`
- icon publication rights: `passed-by-creator-declaration` (2026-08-20); the project owner accepted publication for that asset scope, without claiming independent legal clearance
- r31 previous-evidence publication eligibility: true only for its validated `publication_scope=source-only`
- current r32.2 source publication eligibility: true for the exact tagged source asset
- current r32.2 binary publication eligibility: true for the exact tagged Windows asset
- public repository: [https://github.com/Ponkichi0718/ChromaMatter](https://github.com/Ponkichi0718/ChromaMatter) (owner handle `Ponkichi0718`)
- Innovation Fund distribution package: published; physical evidence and submission presentation can continue to evolve without changing the frozen r32.2 artifacts
- physical XP-PEN validation and physical print: pending disclosed limitations, not source-publication blockers

The published r32.1 and r32 Releases and the r31, r30, r29, r28, and r27
results above are **previous evidence** for their respective revisions only and
do not validate r32.2. The unchanged icon, including its robot and fictional
`ZENITH DYNAMICS CORP.` wording, retains the 2026-08-20 creator declaration and
owner acceptance without claiming independent legal clearance. Multipart
solidification remains a disclosed beta limitation.

Creator Studio r26 results are previous evidence as well and do not validate ChromaMatter r31.

## Package identity

- planned Test 3 corresponding source:
  `ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip`
- planned Test 3 Windows package:
  `ChromaMatter-0.8beta-r32.2-flat4-test3-win64.zip`
- planned Test 3 checksum record: `SHA256SUMS-r32.2-flat4-test3.txt`
- published corresponding source: `ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip`
- published Windows package: `ChromaMatter-0.8beta-r32.2-win64.zip`
- published complete corresponding source: `ChromaMatter-0.8beta-r32.1-complete-corresponding-source.zip`
- published Windows package: `ChromaMatter-0.8beta-r32.1-win64.zip`

The published detached checksum file is `SHA256SUMS-r32.2.txt`; all six downloaded Release assets matched it. Completed `SHA256SUMS-r32.1.txt`, `SHA256SUMS-r32.txt`, and `SHA256SUMS-r31.txt` apply only to previous evidence. Self-referential ZIP hashes are not embedded in canonical documents.

## Notes

- OBJ vertex colours are expected in `v x y z r g b` form.
- GLB support targets static embedded base colour / `COLOR_0`; UV detail is limited to the baked vertex-colour resolution.
- Preparing large OBJ/GLB input and Manual Editing at roughly two million faces require substantial time and memory.
- Fail-soft import does not guarantee automatic repair or printability for non-2-manifold geometry.
- Displayed and printed colour depend on production conditions; verify with a calibration chart and test print.
- Do not include non-public validation assets or identifying details in public artifacts.
- The app is `GPL-3.0-or-later`; also review dependency licences and the publication checklist.

See repository-root `CURRENT_STATE.json` and `PROVENANCE.md` for canonical status and evidence boundaries.

## AI-use disclosure

AI assistance, including ChatGPT and OpenAI Codex, was used across planning, specification, implementation, testing, documentation, image creation, and GitHub publication work. AI-generated code and explanations may contain technical errors or unnatural wording, so verify critical settings against the source, generated 3MF, slicer preview, and physical hardware. The project author makes final decisions on requirements, acceptance, physical validation, and publication.
