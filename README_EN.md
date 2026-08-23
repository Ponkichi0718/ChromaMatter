# ChromaMatter — AI Model Print Studio 0.8beta (r32)

<p align="center">
  <img src="source/fixed_app/assets/obj_adjuster_icon.png" width="160" alt="ChromaMatter icon">
</p>

[日本語版はこちら](README_JA.md)

**Turn AI-generated color OBJ and GLB models into Snapmaker U1 Full Spectrum 3MF projects using four physical filaments.**

<table>
  <tr>
    <td width="25%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038136-QYcX12yPUL4fzm5RWZNbiEqM.jpg?width=1200" alt="Original AI-assisted concept image used for the public ChromaMatter workflow"></a></td>
    <td width="25%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038182-v0C8IT5i1jVeKLdNX3ZygYu4.png?width=1200" alt="Coloured 3D model generated from the original concept"></a></td>
    <td width="25%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038261-fQtHZho5CXvrYl94M7zJOqLD.png?width=1200" alt="ChromaMatter comparing source, model, and Full Spectrum colours"></a></td>
    <td width="25%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038285-sNiOGxEzyLoRrklQAXH7BJ8W.png?width=1200" alt="ChromaMatter 3MF project opened in Snapmaker Orca"></a></td>
  </tr>
  <tr>
    <td align="center">AI concept</td>
    <td align="center">Colour 3D model</td>
    <td align="center">ChromaMatter</td>
    <td align="center">Snapmaker Orca</td>
  </tr>
</table>

**Physical U1 print validation is in progress, so no finished-print image is presented as validated evidence yet.**

ChromaMatter is an independent Windows desktop project. It is not an official or affiliated product of TripoAI, Hi3D AI, Snapmaker, OpenAI, or any other third party.

## Current status

- **Source code:** Public
- **Windows binary:** Not yet public
- **Reason:** Component-specific licence/static-link coverage is implemented; the final release-engineering gates below are pending
- **Public test model:** In preparation
- **Physical U1 validation:** In progress
- **Version:** `0.8beta`

## Four things ChromaMatter does

1. **Bridges AI model formats to printing.** Opens vertex-coloured OBJ and static GLB with embedded base colour, then keeps processing local to the PC.
2. **Maps model colour to four real filaments.** Proposes F1-F4 from a material-aware filament library and builds a 16, 24, or 32-state Full Spectrum palette.
3. **Lets you inspect and refine the result.** Compares source colour with converted colour, supports 3D manual editing, and explicitly applies experimental F1-F4 changes to both preview and 3MF.
4. **Exports a safer Orca project.** Performs topology checks, safely welds only proven seams when eligible, and records a conservative Full Spectrum layer-cycle and prime-tower baseline.

[See the visual feature overview](FEATURES_EN.md) · [Read the Japanese development journal on note](https://note.com/ponkichi0718)

## Quick Start

ChromaMatter currently ships as source code. On Windows with Python 3.13 installed:

```powershell
git clone https://github.com/Ponkichi0718/ChromaMatter.git
cd ChromaMatter
.\BOOTSTRAP_WINDOWS.ps1
.\.venv\Scripts\python.exe .\source\fixed_app\TripoSpectrumMapper_fixed.py
```

Then:

1. Open a vertex-coloured OBJ or supported static GLB.
2. Review the proposed F1-F4 filaments and palette size.
3. Optionally refine colours or apply a different F1-F4 combination.
4. Check size and geometry, export 3MF, then open it **as a project** in Snapmaker Orca and inspect the slice preview before printing.

The bootstrap installs pinned build dependencies and runs the test suite. See [BUILD_AND_TEST.ps1](BUILD_AND_TEST.ps1), [PRIVACY.md](PRIVACY.md), and [THIRD_PARTY_LICENSES.txt](licenses/THIRD_PARTY_LICENSES.txt) for the complete source-build and distribution context.

## Technical details

The public display version remains pinned to `0.8beta`. This edition is `AI Model Print Studio r32`, with artifact slug `r32-ai-model-print-studio`; the Windows numeric version remains `0.8.0.0`.

## AI Model Print Studio r32

r32 adds a multipart GLB path that preserves part structure through solidification and individual 3MF export, narrowly suppresses proven categorical identification colours, explicitly applies edited F1-F4 colours to the converted preview, and records a conservative Snapmaker Orca Full Spectrum project baseline. The public name and icon established in r31, existing OBJ/GLB/3MF workflows, project schemas, and legacy settings locations remain compatible.

### GLB input beta

- `Open OBJ / GLB` accepts vertex-coloured OBJ or static GLB with embedded base colour, so services such as Hi3D AI that do not export vertex-coloured OBJ can enter the same authoring pipeline.
- Scene/node transforms, mesh-node parts, `COLOR_0`, base-colour factors, and base-colour textures are read. sRGB texels are filtered and composed in linear space before being baked into the existing vertex-colour pipeline. Source GLB files are not uploaded.
- Printing uses base colour only. Normal/metallic/roughness maps, alpha, animation, skinning, morph targets, Draco, meshopt, BasisU, GPU instancing, and external URIs are not reproduced and fail closed.
- UV colour is sampled at mesh vertices, so texture detail finer than the tessellation can be lost and face reduction can increase that difference. Limits are 512 MiB, three million vertices, and three million triangles.

### Single-GLB UV-seam solidification

- On a single GLB without part markers, apparent open edges are accepted as UV/texture seams only when coincident boundary edges prove an exact 1:1 reversed pairing. If export starts before solidification, an eligible model announces and runs that safe step, then resumes export only after success.
- Proven seams are vertex-welded before cleanup and QEM reduction. No triangle is added, removed, or reordered and no part ID changes, so manual paint and adaptive trees retain exact ordered-face carry.
- This path adds no caps. Unmatched, same-direction, or ambiguous seams, a non-manifold result, and true holes fail closed while retaining the pre-operation geometry.
- Strict pre-export 3MF topology checks cover every `type=model` resource, not only direct build items. If only a bounded minor QEM self-intersection remains after mandatory solid checks pass, export warns and requires opening the file as a project in Snapmaker Orca and checking the slice preview.
- The 3MF records a stable Full Spectrum layer-cycle and prime-tower baseline. Experimental Local Z, advanced dithering, and pointillism remain disabled, while support selection stays in Snapmaker Orca.

### Multipart GLB solidification and individual 3MF export

- Supported exploded GLB assets are normalised per source part while retaining the original part boundaries and placement. Separate parts are never welded together, and repair-generated faces remain distinguishable from imported source faces.
- Categorical `COLOR_0` used by supported Hi3D-style part exports is suppressed only when exporter, node, material, texture, and known-palette evidence all agree. Ordinary authored vertex colours are left unchanged.
- The same strict validation protects both combined 3MF and `save each print part as an individual 3MF`. Individual export rebases part IDs and vertex references locally, and fails closed when the mapping or proof is incomplete or stale.

### Stable Manual Editing feedback

- The pending Airbrush guide is 2D screen-space feedback. It remains visible only while the view is unchanged and is suppressed as soon as zoom, pan, orbit, or a programmatic camera change begins. Old trail coordinates are never redrawn into a transformed view.
- Hiding that guide does not discard the accepted commit token or the one-stroke / one-Undo transaction. Both remain alive until the exact frame arrives, and the committed 3D colour appears in the correct transformed view.
- Circular soft falloff, time-based density, the visible-face and selected-part guards, Brush, Fill, Smudge, Eyedropper, Windows Pointer pressure, and fallback taper retain their committed result.

### Lower accumulated manual-paint cost

- A paint batch reads effective state only for candidate roots and reuses validated geometry arrays instead of rematerialising full-scene colour and geometry for every batch.
- A compatible nine-layer Airbrush batch traverses the adaptive tree once. Legacy, non-concentric, or otherwise non-conforming layer geometry safely falls back to the proven sequential path.
- Regression tests verify matching encoded output, changed roots, overrides, adaptive trees, and Undo/Redo semantics between the optimised and sequential paths.

### Public workspace

- The main window is organised into compact Filament Settings and Output Settings pages, leaving more room for the 3D preview.
- The header presents the bundled PNG logo with compact two-line `ChromaMatter` and `AI Model Print Studio` text.
- The read-only mixed palette shows fixed ratios in F1+F2, F1+F3, and subsequent F-pair family-major order. Visible numbers are presentation-only; canonical state IDs, projects, manual paint, and 3MF recipes are unchanged.
- A common 16 / 24 / 32-state selection propagates to existing parts; an explicitly selected part can still be adjusted locally.
- `Reset Four Base Colors` is not shown in the public workspace. Model-derived automatic proposals and individual colour editing remain available.
- After an individual F1-F4 edit, `Apply Current F1-F4 to Preview / 3MF` updates the right-hand preview and 3MF palette. Automatic proposal remains the default, and existing manual paint remains canonical-state data.
- Physical black correction stays inside the mixed-palette frame and alters only the relevant 3MF output recipe.
- Output geometry reprocessing is one action, and the public repair action is labelled Solidify.

### Filament candidates beta

- Switch between PLA (default), ABS beta, and PETG beta. F1-F4 candidates, owned inventory, and the Generic material profile written to 3MF are restricted to the selected single material; one print job never mixes polymers.
- Automatic proposals no longer rank the whole expanded database by distance to the model-wide average colour. Four products are selected from real products of the chosen material mapped to gamut-balanced black, white, grey, chromatic, and skin/brown anchors. This prevents the regression to four similar browns. Multi-colour and gradient spools remain browsable in the manual library but are excluded from automatic proposals.
- In a representative red, black, grey, and brown model software-fit diagnostic, area-weighted coverage within `Delta E 76 <= 12` improved from 28.63% before the fix to 98.37% after it. This is a screen-space approximation metric, not a printed-colour guarantee.
- The pinned Open Filament Database snapshot contains 3,497 colours across 19 brands, including Geeetech, CC3D, Kingroon, and TINMORRY. ABS has fewer catalogued and physically measured colours than PLA, so coverage does not guarantee that a target gamut can be reproduced.
- Those four manufacturers qualified at brand level because a representative Amazon.co.jp filament result met `rating >= 4.0 AND review_count >= 20` on 2026-08-19. This is not a review of every colour, SKU, stock state, or colour accuracy, and no HEX value is inferred from Amazon imagery.

See the [filament colour database notes](source/fixed_app/resources/filament_db/filament_color_database_README.md) for counts, sources, reproducibility, and limitations.

### Portable project folder

Project Save creates this portable folder:

```text
project-folder/
  source.obj | source.glb
  project.json
  prepared_geometry.npz
  reference.<ext>        # only when a reference image is present
```

- Matching bundles restore prepared geometry and manual paint exactly.
- Relative references continue to work after the folder is moved.
- Bundle v2 makes `source_asset` authoritative and retains GLB as `source.glb`; legacy OBJ bundle v1 remains readable.
- Legacy JSON projects remain readable. When their source cannot be resolved safely, the user explicitly selects the original OBJ or GLB.

## Basic workflow

1. Use `Open OBJ / GLB` for a vertex-coloured OBJ or base-colour GLB.
2. Confirm F1-F4 and the common mixed-state count, then adjust a part palette if needed.
3. Use Manual Editing for colour corrections.
4. Check size and geometry diagnostics in Output Settings.
5. Export 3MF and verify tool order, material profiles, and preview in Snapmaker Orca.

## Input and output notes

- OBJ vertex colour is expected in `v x y z r g b` form.
- GLB support targets static embedded base colour / `COLOR_0`; fine detail is limited by the vertex-colour bake resolution.
- Fail-soft display and manual editing of non-2-manifold OBJ/GLB input do not guarantee automatic repair or printability.
- Preparing or solidifying a large OBJ/GLB can require substantial time and memory, and Manual Editing on roughly two million faces may be heavy.
- Displayed and printed colour are not guaranteed to match; use a test print under the same production conditions.
- Research engines remain in source for continued development but cannot be reached from the public workflow.

## Validation and release gates

The current working tree passed the full Python `3.13.14` regression after the Qt/PyMeshLab identity manifests, PyTetWild static-closure contract, corrected controlled-toolchain identity, and Windows PowerShell 5.1-safe native Python-probe transport: `Ran 1239 tests: OK (skipped=2)`, 1237 passed / 2 optional skips / 0 failed. The focused release/compliance set passed 178 tests with 1 optional skip. A fresh public-source stage passed at 395 files / 394 manifest records with privacy audit and independent SHA-256 parity.

Component-specific licence texts and static-linked component coverage are implemented and covered by fail-closed inventory tests. The old r32 EXE/ZIP does not match this source and will not be published. A new Windows ZIP requires: controlled PyTetWild rebuild evidence; the application lock updated to that wheel; a `release-approved` complete corresponding-source bundle; a current clean binary build with packaged self-test and Japanese/English UI smoke; fresh-extract manifest/privacy/archive/checksum parity; and immutable HTTPS Release URLs with all assets published simultaneously. `binary publication eligibility` is currently **false**.

The following r31 and Creator Studio r30 results are **previous evidence** for their own revisions and do not validate r32.

- r30 full regression: Python `3.13.14`, `Ran 1019 tests in 86.932s: OK (skipped=1)`, 1018 passed / 1 optional skip
- PyInstaller `6.20.0` clean build at `C:\OBJAdjR30FIX1`, packaged self-test, and isolated-profile Japanese/English UI smoke: passed
- r30 public source 225 files / 224 manifest records, software 1,404 files / 1,403 manifest records, fresh extraction, archive/privacy, and detached `SHA256SUMS-r30.txt` contract: passed

The exact ChromaMatter r31 source **previous evidence** is Python `3.13.14`, `Ran 1024 tests in 100.656s: OK (skipped=1)`, 1023 passed / 1 optional skip, `BUILD_AND_TEST.ps1 -RuntimeRoot .\.venv -Build -BuildOutputRoot C:\OBJAdjR31CM1`, PyInstaller `6.20.0`, packaged smoke, a 13,986,866-byte `ChromaMatter.exe`, SHA-256 `208167A225A37BAAAA473B574B2F746E46427FD0CA63FC5B7201BF3394243743`, r31 source stage 227/226, software 1,404/1,403, and external `SHA256SUMS-r31.txt`. It does not validate r32. The unchanged icon retains its `passed-by-creator-declaration`, fictional `ZENITH DYNAMICS CORP.` wording, and non-affiliation explanation.

Icon publication-rights status: `passed-by-creator-declaration` (2026-08-20).

- r27 full regression: Python `3.13.14`, PyInstaller `6.20`, `Ran 890 tests in 68.257s: OK (skipped=1)`, 889 passed / 1 optional skip
- preflight EXE: 13,683,090 bytes, version `0.8beta`, SHA-256 `F2AB0AF025430FF3D5587D6C7B2A68365B8C091A7775697A24DDB84DF34EF056`
- public-source stage: 204 files / 203 manifest records
- software stage: 1,340 files / 1,339 manifest records
- source and software ZIP structure, manifest equality, path safety, CRC, and privacy: passed

The r31, r30, and r27 evidence above applies only to those artifacts and does not validate ChromaMatter r32. The r29, r28, and r26 results are likewise **previous evidence**. Icon publication rights and owner legal acceptance for that declared asset scope are recorded. Physical XP-PEN and print validation remain pending limitations. `binary publication eligibility` stays false until every final release-engineering gate listed above passes; `Innovation Fund submission ready` also stays false until the rights-cleared sample and Orca/U1 evidence exist.

See [CURRENT_STATE.json](CURRENT_STATE.json) and [PROVENANCE.md](PROVENANCE.md) for the canonical boundary.

## Development and tests

On Windows with Python 3.13, run:

```powershell
.\BOOTSTRAP_WINDOWS.ps1
```

`-Build` creates a PyInstaller one-folder build after the full regression. The planned r32 stage names remain non-distributable until validation completes:

- source candidate: `ChromaMatter-0.8beta-r32-source-public-20260823`
- gated Windows package: `ChromaMatter-0.8beta-r32-win64`

## Privacy and licensing

Do not include non-public validation assets or identifying details in the public tree or release candidate. Public samples require traceable rights and provenance.

The application is `GPL-3.0-or-later`. Bundled dependencies have their own licences, and TetGen itself is `AGPL-3.0-or-later`. Review `licenses/` and the publication checklist before binary distribution.

## AI-use disclosure

ChromaMatter uses AI assistance, including ChatGPT and OpenAI Codex, across planning, specification, implementation, testing, documentation, image creation, and GitHub publication work. The project author makes the final decisions on requirements, acceptance, physical validation, and publication.

AI-generated code, images, and explanations may contain technical errors or unnatural wording. Verify critical print settings against the source, generated 3MF, slicer preview, and your own hardware. Please report anything suspicious through [GitHub Issues](https://github.com/Ponkichi0718/ChromaMatter/issues).
