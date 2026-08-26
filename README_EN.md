# ChromaMatter — AI Model Print Studio 0.8beta (r32.2)

<p align="center">
  <img src="source/fixed_app/assets/obj_adjuster_icon.png" width="160" alt="ChromaMatter icon">
</p>

[日本語版はこちら](README_JA.md)

## Choose a version

| Channel | Best for | Open |
| --- | --- | --- |
| **Published r32.2** | The current downloadable Windows build and the documented Full Spectrum workflow | **[Download stable r32.2](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2)** |
| **Experimental Flat Four Test 3** | Testing Flat Four with conservative eye-white preservation and skin-highlight correction, plus the large-static-GLB path and 2D Colour Filter, before integration | **[Download the Windows test ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2-flat4-test3/ChromaMatter-0.8beta-r32.2-flat4-test3-win64.zip)** · [Release notes](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2-flat4-test3) · [Draft PR #7](https://github.com/Ponkichi0718/ChromaMatter/pull/7) |
| **macOS Source-backed App Alpha** | Finder `.app` testing on Apple Silicon / macOS 15+; first launch prepares the hash-locked source runtime | **[Download the macOS app ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-app-alpha1/ChromaMatter-0.8beta-macos-source-app-alpha1.zip)** · [Release/checksum](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-app-alpha1) · [English install/test guide](publication/MACOS_SOURCE_APP_TESTING_EN.md) · [Test hub](publication/MACOS_ALPHA_HUB_EN.md) |

The experimental workstream is an integration candidate, not a permanent fork.
**Flat Four Test 3 is now available as a separate public pre-release.** Extract
the whole ZIP before starting it. Stable r32.2 below does not contain Flat Four;
the test Release and Draft PR #7 remain the experimental status hubs.

**The macOS Source-backed App Alpha is available for Apple Silicon / macOS
15+.** Download the fixed ZIP, extract it completely, then Control-click
`ChromaMatter Source Alpha.app` and choose **Open**. It verifies official
Python 3.13.14 and installs only hash-locked dependencies on the tester's Mac.
It is a Finder app but not a self-contained frozen build. That separate route
remains blocked because 153 packaged Mach-O files have unresolved
source/build/relink closure evidence. A `diagnostics` artifact is not the app.
[Draft PR #12](https://github.com/Ponkichi0718/ChromaMatter/pull/12) contains
the separate source and review history.

## Download for Windows

**[Download ChromaMatter 0.8beta r32.2 for Windows (ZIP)](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-win64.zip)**

Extract the entire ZIP before starting. If the direct download does not open, use the [v0.8beta-r32.2 Release page](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2) and select `ChromaMatter-0.8beta-r32.2-win64.zip` under **Assets**.

## Explore ChromaMatter

- **[Features and controls](FEATURES_EN.md)** — filament suggestions, mixed palettes, calibration, Brush, Airbrush, Smudge, and Eyedropper
- **[Original-model workflow, project examples, and print results](FEATURES_EN.md#project-examples)**
- **[Simple workflow demo — about two minutes](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-simple-workflow-demo.mp4)**
- **[日本語の機能・操作案内](FEATURES_JA.md)**

`v0.8beta-r32.2` is published as an Innovation Fund preview prerelease. Its
Windows package, complete corresponding source, SBOM, component map, workflow
video, and detached checksums were all downloaded without authentication and
reverified after publication.

**Important 0.8 beta limitation:** Solidification of multipart models is still unstable. The bundled `DemoData` is a confirmed successful case, but other multipart files may fail to solidify or export as 3MF. This incomplete compatibility is one reason ChromaMatter remains `0.8beta`.

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

## Physical U1 result

A public full-body, one-piece sample completed on a Snapmaker U1 in **48 hours** and used about **220 g including the prime tower**. At normal viewing distance, its deliberately graphic shading reads as form and depth. The recorded limitations are rear support scarring, a loose stand, and colour boundaries that can look less clean at close range. See [ChromaMatter Sample Character — Print Results](https://note.com/ponkichi0718/n/nf6c77165127c) for the result and video.

The privacy-reviewed, captioned [Simple Workflow Demo (about two minutes)](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-simple-workflow-demo.mp4) is published as a separate `v0.8beta-r32.2` asset. It shows the path from a compatible OBJ/GLB through size and geometry preparation, Full Spectrum 3MF export and validation, opening and slicing the project in Snapmaker Orca, and the U1 print. The published copy is 125.33 seconds, 1920 x 1080 H.264, and intentionally has no audio.

This is a practical print observation, not a guarantee that every model, filament set, slicer profile, or printer will reproduce the same result. Inspect the generated project and slice preview before printing.

ChromaMatter is an independent desktop project. The published stable build is
for Windows; a separate Apple Silicon macOS alpha is being validated by
volunteers. It is not an official or affiliated product of TripoAI, Hi3D AI,
Snapmaker, OpenAI, Apple, or any other third party.

## Current status

- **Published release:** [`v0.8beta-r32.2`](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2)
- **Frozen release source:** tag `v0.8beta-r32.2`, commit [`aba20685d2fd6987621b2e1e6624f46ea84912a3`](https://github.com/Ponkichi0718/ChromaMatter/commit/aba20685d2fd6987621b2e1e6624f46ea84912a3)
- **Published asset set:** Windows ZIP, complete corresponding source, SBOM, component map, workflow video, and detached checksums
- **Published r32.2 test data:** Rights-cleared Hi3D multipart GLB and reference image are included under `DemoData/`
- **Published demo outputs:** Seven derived 3MF reference outputs under `DemoData/3MF/`; one combined project and six part-specific projects
- **Physical U1 validation:** The linked public print completed; it does not prove compatibility with every model or production setup
- **macOS tester path:** Source-backed Finder `.app` available for Apple Silicon/macOS 15+; the guided launcher verifies official Python 3.13.14 and hash-locked dependencies locally
- **macOS technical status:** Apple Silicon/macOS 15+ CI passes source, native, packaged self-test, Japanese UI, and English UI checks; the latest successful run published diagnostics only
- **macOS self-contained-app gate:** the source-backed `.app` is separate; all 317 frozen-app Mach-O paths are classified, but 153 still have unresolved source/relink closure evidence
- **macOS starter test:** The source launcher generates a deterministic CC0 red/blue/white/black four-box GLB; English and Japanese 10-minute guides and the dedicated Issue form are available
- **Version:** `0.8beta`

The documentation on the default branch may receive corrections after publication. For the exact source that produced the downloadable r32.2 files, use the frozen tag and commit above.

## Experimental test workstream — not included in r32.2

This experimental branch contains the following additions for a separate test
channel. They are **not** present in the r32.2 Windows download or its frozen
source tag:

- **Flat Four** makes a deterministic, area-weighted proposal of four distinct
  physical filament colours. It creates no mixed-colour recipes, and a Flat
  Four 3MF uses only F1-F4.
- The experimental **2D Colour Filter** offers **Cel Colour** and **Shaded
  Monochrome**. It bakes a fixed-front, geometry-aware stepped light into
  printable colour targets; it is not a screen-space renderer and cannot
  recreate authored line art, PBR materials, or texture detail absent from the
  mesh colours.
- The normal static-GLB limits remain 512 MiB, three million vertices, and
  three million triangles. A separate beta path can admit a static
  `TRIANGLES` scene with 3,000,001-5,000,000 triangles only after explicit
  confirmation and with face-count adjustment enabled; it must produce a
  working model of at most 450,000 faces. Unsupported or ambiguous input fails
  closed, and reduction can remove fine geometry and baked texture detail.
- This workstream writes project schema `obj-adjuster.project.v13`; schema v12
  remains readable and defaults to the legacy Full Spectrum mode.

These additions have local source-level regression coverage only. They do not
inherit the published r32.2 binary, package, or physical-print validation.

## Four things ChromaMatter does

1. **Bridges AI model formats to printing.** Opens vertex-coloured OBJ and static GLB with embedded base colour, then keeps processing local to the PC.
2. **Maps model colour to four real filaments.** Proposes F1-F4 from a material-aware filament library and builds a 16, 24, or 32-state Full Spectrum palette.
3. **Lets you inspect and refine the result.** Compares source colour with converted colour, supports 3D manual editing, and explicitly applies experimental F1-F4 changes to both preview and 3MF.
4. **Exports a safer Orca project.** Performs topology checks, safely welds only proven seams when eligible, and records a conservative Full Spectrum layer-cycle and prime-tower baseline.

[See the visual feature overview](FEATURES_EN.md) · [Read the public print result](https://note.com/ponkichi0718/n/nf6c77165127c) · [Read the Japanese development journal on note](https://note.com/ponkichi0718)

## Quick Start

Use the published [`v0.8beta-r32.2` Release](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2) for the matching r32.2 source and Windows package. To run the frozen release source, check out tag `v0.8beta-r32.2` on Windows with Python 3.13:

```powershell
git clone https://github.com/Ponkichi0718/ChromaMatter.git
cd ChromaMatter
$pyTetWildWheel = "C:\path\to\pytetwild-0.3.0-cp312-abi3-win_amd64.whl"
.\BOOTSTRAP_WINDOWS.ps1 -PyTetWildWheel $pyTetWildWheel
.\.venv\Scripts\python.exe .\source\fixed_app\TripoSpectrumMapper_fixed.py
```

r32.2 retains the controlled PyTetWild wheel pin by SHA-256, so a bare bootstrap intentionally fails instead of downloading the different historical PyPI wheel. Use the repaired wheel from the published [complete corresponding-source ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip) at `build-evidence/pytetwild/repaired-wheel/`, or reproduce it with the controlled recipe before passing its local path. `-PyTetWildWheelhouse` is also supported; `-SkipInstall` is only for an already verified environment.

Then:

1. Open a vertex-coloured OBJ or supported static GLB.
2. Review the proposed F1-F4 filaments and palette size.
3. Optionally refine colours or apply a different F1-F4 combination.
4. Check size and geometry, export 3MF, then open it **as a project** in Snapmaker Orca and inspect the slice preview before printing.

The bootstrap installs pinned build dependencies and runs the test suite. See [BUILD_AND_TEST.ps1](BUILD_AND_TEST.ps1), [PRIVACY.md](PRIVACY.md), and [THIRD_PARTY_LICENSES.txt](licenses/THIRD_PARTY_LICENSES.txt) for the complete source-build and distribution context.

## Technical details

The public display version remains pinned to `0.8beta`. The published edition
is `AI Model Print Studio r32.2`, with artifact slug
`r32.2-ai-model-print-studio`; the Windows numeric version remains `0.8.0.0`.

## AI Model Print Studio r32.2

r32.2 keeps the r32.1 application and fail-closed 3MF contracts and adds seven
derived demo outputs: one combined six-mesh project plus six part-specific
projects. Hi3D-derived part labels do not match the visible geometry, so inspect
each project instead of trusting its filename. When regenerating the demo,
select the F slot that physically holds black and **always apply the Weak Black
5–25% preset before 3MF export**. Multipart solidification remains unstable;
the bundled demo is a successful case, not a compatibility guarantee. The exact
tagged build, complete corresponding source, Windows package, fresh extraction,
checksums, and post-publication downloads all passed their release gates.

## AI Model Print Studio r32.1

r32.1 is immutable published previous evidence. It keeps the r32 modelling and
3MF contracts while renaming the preview heading to `AI Model Color` and adding
a rights-cleared Hi3D multipart GLB plus its reference image under `DemoData/`.
Its binaries and source assets are frozen at commit
`b575b93d973ed67e7ada986469b10b4490eef4e5`; later candidate work does not
change or validate those release files.

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

## Published validation

The exact r32.2 release build was produced from commit
`aba20685d2fd6987621b2e1e6624f46ea84912a3`. Its full regression ran 1,298
tests: 1,296 passed, 2 optional skips, and 0 failed. Packaged and independently
fresh-extracted self-tests plus Japanese and English UI smoke tests passed. The
Windows package contains 1,527 files, including 10 manifest-locked DemoData
payloads and seven 3MF projects.

The release compliance inventory passed with 1,455 files. The complete
corresponding-source archive is `release-approved`, contains 42,806 files, and
has zero known source-closure gaps. All six public r32.2 assets were downloaded
without authentication after publication and matched their expected sizes and
SHA-256 checksums. The Windows ZIP SHA-256 is
`2CEADA98661BAC5D49B759542151C4C484FFF4269D6B5D142EC32FEC544F06D0`; the
complete corresponding-source ZIP SHA-256 is
`DCC7EC1AE74F4B790CCAC6B9B18286C7BDAB2829E779F0532E01708727680500`.

The results below are immutable **r32.1 previous evidence** and do not validate
r32.2.

The exact r32.1 release build was produced from commit `b575b93d973ed67e7ada986469b10b4490eef4e5`. Its focused suite passed 113 tests. Its full regression recorded 1,277 tests: 1,274 passed, 3 optional skips, and 0 failures. Packaged self-test and isolated-profile Japanese and English UI smoke tests passed.

The release compliance inventory passed with 1,455 files and 256 native files. The Windows package contains 1,518 files; its packaged and independently fresh-extracted self-tests and UI smokes passed. The complete corresponding-source bundle is `release-approved` with no known source-closure gaps. All six public assets were downloaded without authentication after publication and matched their expected sizes and SHA-256 checksums. The Windows ZIP SHA-256 is `1215CF77D8C8CB8AA5CE91DC7C84AE13404F3AA46221321807AD2E8A19F9064A`; the complete corresponding-source ZIP SHA-256 is `D5A64F3022265BCE7C5C2DFA0358DFC2C94EEA541A5A4AC5671CE3BA829BE4CC`.

The published r32 Release and the following r31 and Creator Studio r30 results
are **previous evidence** for their own revisions and do not validate r32.2.

- r30 full regression: Python `3.13.14`, `Ran 1019 tests in 86.932s: OK (skipped=1)`, 1018 passed / 1 optional skip
- PyInstaller `6.20.0` clean build at `C:\OBJAdjR30FIX1`, packaged self-test, and isolated-profile Japanese/English UI smoke: passed
- r30 public source 225 files / 224 manifest records, software 1,404 files / 1,403 manifest records, fresh extraction, archive/privacy, and detached `SHA256SUMS-r30.txt` contract: passed

The exact ChromaMatter r31 source **previous evidence** is Python `3.13.14`, `Ran 1024 tests in 100.656s: OK (skipped=1)`, 1023 passed / 1 optional skip, `BUILD_AND_TEST.ps1 -RuntimeRoot .\.venv -Build -BuildOutputRoot C:\OBJAdjR31CM1`, PyInstaller `6.20.0`, packaged smoke, a 13,986,866-byte `ChromaMatter.exe`, SHA-256 `208167A225A37BAAAA473B574B2F746E46427FD0CA63FC5B7201BF3394243743`, r31 source stage 227/226, software 1,404/1,403, and external `SHA256SUMS-r31.txt`. It does not validate r32.1. The unchanged icon retains its `passed-by-creator-declaration`, fictional `ZENITH DYNAMICS CORP.` wording, and non-affiliation explanation.

Icon publication-rights status: `passed-by-creator-declaration` (2026-08-20).

- r27 full regression: Python `3.13.14`, PyInstaller `6.20`, `Ran 890 tests in 68.257s: OK (skipped=1)`, 889 passed / 1 optional skip
- preflight EXE: 13,683,090 bytes, version `0.8beta`, SHA-256 `F2AB0AF025430FF3D5587D6C7B2A68365B8C091A7775697A24DDB84DF34EF056`
- public-source stage: 204 files / 203 manifest records
- software stage: 1,340 files / 1,339 manifest records
- source and software ZIP structure, manifest equality, path safety, CRC, and privacy: passed

The published r32.1 Release and the r32, r31, r30, and r27 evidence above apply
only to those older artifacts. Multipart solidification can still fail outside
the bundled r32.2 demo, and physical XP-PEN validation remains pending. Icon
publication rights and owner legal acceptance for the declared asset scope
remain recorded.

See [CURRENT_STATE.json](CURRENT_STATE.json) and [PROVENANCE.md](PROVENANCE.md) for the canonical boundary.

## Development and tests

On Windows with Python 3.13, run:

```powershell
$pyTetWildWheel = "C:\path\to\pytetwild-0.3.0-cp312-abi3-win_amd64.whl"
.\BOOTSTRAP_WINDOWS.ps1 -PyTetWildWheel $pyTetWildWheel
```

`-Build` creates a PyInstaller one-folder build after the full regression. The distributable r32.2 files are the immutable assets on the [`v0.8beta-r32.2` Release page](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2); local build and staging directories are not release artifacts.

## Privacy and licensing

Do not include non-public validation assets or identifying details in the public tree or a future release candidate. Public samples require traceable rights and provenance.

The application is `GPL-3.0-or-later`. Bundled dependencies have their own licences, and TetGen itself is `AGPL-3.0-or-later`. Review `licenses/` and the publication checklist before binary distribution.

## AI-use disclosure

ChromaMatter uses AI assistance, including ChatGPT and OpenAI Codex, across planning, specification, implementation, testing, documentation, image creation, and GitHub publication work. The project author makes the final decisions on requirements, acceptance, physical validation, and publication.

AI-generated code, images, and explanations may contain technical errors or unnatural wording. Verify critical print settings against the source, generated 3MF, slicer preview, and your own hardware. Please report anything suspicious through [GitHub Issues](https://github.com/Ponkichi0718/ChromaMatter/issues).
