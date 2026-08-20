# ChromaMatter — AI Model Print Studio 0.8beta (r31)

<p align="center">
  <img src="source/fixed_app/assets/obj_adjuster_icon.png" width="180" alt="ChromaMatter icon">
</p>

[Japanese README](README_PUBLIC_JA.md)

ChromaMatter — AI Model Print Studio is a Windows desktop tool that converts and adjusts AI-generated vertex-coloured OBJ or UV-base-colour GLB models for the Snapmaker Orca Full Spectrum / Color Mixing 3MF workflow. It is an independent project and is not an official or affiliated product of TripoAI, Hi3D AI, Snapmaker, OpenAI, or any other third party.

The public display version remains pinned to `0.8beta` as requested. This edition is `AI Model Print Studio r31`, with artifact slug `r31-ai-model-print-studio`; the Windows numeric version remains `0.8.0.0`.

## AI Model Print Studio r31

r31 is an identity release that unifies the public name and icon as ChromaMatter. Existing OBJ/GLB/3MF workflows, project schemas, and legacy settings locations remain readable for compatibility.

### GLB input beta

- `Open OBJ / GLB` accepts vertex-coloured OBJ or static GLB with embedded base colour, so services such as Hi3D AI that do not export vertex-coloured OBJ can enter the same authoring pipeline.
- Scene/node transforms, mesh-node parts, `COLOR_0`, base-colour factors, and base-colour textures are read. sRGB texels are filtered and composed in linear space before being baked into the existing vertex-colour pipeline. Source GLB files are not uploaded.
- Printing uses base colour only. Normal/metallic/roughness maps, alpha, animation, skinning, morph targets, Draco, meshopt, BasisU, GPU instancing, and external URIs are not reproduced and fail closed.
- UV colour is sampled at mesh vertices, so texture detail finer than the tessellation can be lost and face reduction can increase that difference. Limits are 512 MiB, three million vertices, and three million triangles.

### Single-GLB UV-seam solidification

- When the user explicitly selects Solidify on a single GLB without part markers, apparent open edges are accepted as UV/texture seams only when coincident boundary edges prove an exact 1:1 reversed pairing.
- Proven seams are vertex-welded before cleanup and QEM reduction. No triangle is added, removed, or reordered and no part ID changes, so manual paint and adaptive trees retain exact ordered-face carry.
- This path adds no caps. Unmatched, same-direction, or ambiguous seams, a non-manifold result, and true holes fail closed while retaining the pre-operation geometry.
- Strict pre-export 3MF topology checks cover every `type=model` resource, not only direct build items. If only a bounded minor QEM self-intersection remains after mandatory solid checks pass, export warns and requires opening the file as a project in Snapmaker Orca and checking the slice preview.

### Stable Manual Editing feedback

- The pending Airbrush guide is 2D screen-space feedback. It remains visible only while the view is unchanged and is suppressed as soon as zoom, pan, orbit, or a programmatic camera change begins. Old trail coordinates are never redrawn into a transformed view.
- Hiding that guide does not discard the accepted commit token or the one-stroke / one-Undo transaction. Both remain alive until the exact frame arrives, and the committed 3D colour appears in the correct transformed view.
- Circular soft falloff, time-based density, the visible-face and selected-part guards, Brush, Fill, Smudge, Eyedropper, Windows Pointer pressure, and fallback taper retain their committed result.

### Lower accumulated manual-paint cost

- A paint batch reads effective state only for candidate roots and reuses validated geometry arrays instead of rematerialising full-scene colour and geometry for every batch.
- A compatible nine-layer Airbrush batch traverses the adaptive tree once. Legacy, non-concentric, or otherwise non-conforming layer geometry safely falls back to the proven sequential path.
- Regression tests verify matching encoded output, changed roots, overrides, adaptive trees, and Undo/Redo semantics between the optimised and sequential paths.

### Decal beta (source retained, hidden from the public UI)

- Decal loading, projection, baking, and safety tests remain in source for future validation.
- The current public Manual Editing workspace has no decal ribbon tab, button, menu, image-open callback, or shortcut, so users cannot invoke the feature.
- Older projects remain readable. Colours baked by an earlier build remain ordinary manual-paint data; source PNG/SVG files and editable decal layers were never project data.

### Public workspace

- The main window is organised into compact Filament Settings and Output Settings pages, leaving more room for the 3D preview.
- The header presents the bundled PNG logo with compact two-line `ChromaMatter` and `AI Model Print Studio` text.
- The read-only mixed palette shows fixed ratios in F1+F2, F1+F3, and subsequent F-pair family-major order. Visible numbers are presentation-only; canonical state IDs, projects, manual paint, and 3MF recipes are unchanged.
- A common 16 / 24 / 32-state selection propagates to existing parts; an explicitly selected part can still be adjusted locally.
- `Reset Four Base Colors` is not shown in the public workspace. Model-derived automatic proposals and individual colour editing remain available.
- Physical black correction stays inside the mixed-palette frame and alters only the relevant 3MF output recipe.
- Output geometry reprocessing is one action, and the public repair action is labelled Solidify.

Black-Free Gradient, ColorDepth, Radial, Decal beta, black-inner-wall, split, joint, Help Center, safe-seam-only, manual-joint reprocess, and the separate 3D open-boundary entry point are not exposed in the public UI. Stale opt-ins from older projects or preferences are sanitised to safe defaults when loaded.

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

Creator Studio r30 has the following software evidence. It is **previous evidence** only and does not validate the current exact r31 source after the ChromaMatter public name, icon, and executable identity change.

- r30 full regression: Python `3.13.14`, `Ran 1019 tests in 86.932s: OK (skipped=1)`, 1018 passed / 1 optional skip
- PyInstaller `6.20.0` clean build at `C:\OBJAdjR30FIX1`, packaged self-test, and isolated-profile Japanese/English UI smoke: passed
- r30 public source 225 files / 224 manifest records, software 1,404 files / 1,403 manifest records, fresh extraction, archive/privacy, and detached `SHA256SUMS-r30.txt` contract: passed

The current exact ChromaMatter r31 source passed on Python `3.13.14` with `Ran 1024 tests in 100.656s: OK (skipped=1)`, 1023 passed / 1 optional skip. `BUILD_AND_TEST.ps1 -RuntimeRoot .\.venv -Build -BuildOutputRoot C:\OBJAdjR31CM1` exited 0; the PyInstaller `6.20.0` clean one-folder build, built-package self-test, and isolated-profile Japanese/English UI smoke passed. The preflight `ChromaMatter.exe` is 13,986,866 bytes with FileVersion/ProductVersion `0.8beta`, InternalName `ChromaMatter`, OriginalFilename `ChromaMatter.exe`, and SHA-256 `208167A225A37BAAAA473B574B2F746E46427FD0CA63FC5B7201BF3394243743`. On 2026-08-20 the project owner gave publication GO, and the ChromaMatter icon-rights gate is `passed-by-creator-declaration`. The creator states that the robot is an original fictional machine and `ZENITH DYNAMICS CORP.` is fictional wording with no intended real-world affiliation. This is not independent trademark/design clearance or legal advice, and no affiliation with organizations using the close name `Zenith Dynamics` is claimed. The final source-only stage `ChromaMatter_0.8beta-r31-source-public-20260820` passed with 227 files / 226 manifest records, folder/archive parity, CRC, privacy, and 32 staged identity/icon/tooling tests; Downloads placement and detached `SHA256SUMS-r31.txt` verification were completed externally. Release state is `source-publication-approved`; `publication_eligible=true` applies only to `publication_scope=source-only`, and source publication eligibility is true. Binary publication eligibility remains false until the third-party binary redistribution audit is complete. Innovation Fund submission readiness remains false pending the public repository URL/handle, rights-cleared sample, Orca/U1 evidence, cover/video, and community post. Physical XP-PEN/print validation remains a disclosed limitation rather than a source-publication blocker. The external detached checksum record is authoritative and canonical ZIP hash fields remain `null`.

Icon publication-rights status: `passed-by-creator-declaration` (2026-08-20).

- r27 full regression: Python `3.13.14`, PyInstaller `6.20`, `Ran 890 tests in 68.257s: OK (skipped=1)`, 889 passed / 1 optional skip
- preflight EXE: 13,683,090 bytes, version `0.8beta`, SHA-256 `F2AB0AF025430FF3D5587D6C7B2A68365B8C091A7775697A24DDB84DF34EF056`
- public-source stage: 204 files / 203 manifest records
- software stage: 1,340 files / 1,339 manifest records
- source and software ZIP structure, manifest equality, path safety, CRC, and privacy: passed

The r30 and r27 evidence above applies only to those artifacts and does not validate ChromaMatter r31. The r29, r28, and r26 results are likewise **previous evidence**. Icon publication rights and owner legal acceptance for that declared asset scope are recorded. Physical XP-PEN and print validation remain pending limitations. The EXE/software ZIP will not be published until the third-party binary redistribution audit for PyTetWild/fTetWild, TetGen, PyMeshLab, Qt, GEOS, and the exact packaged dependency set is complete.

See [CURRENT_STATE.json](CURRENT_STATE.json) and [PROVENANCE.md](PROVENANCE.md) for the canonical boundary.

## Development and tests

On Windows with Python 3.13, run:

```powershell
.\BOOTSTRAP_WINDOWS.ps1
```

`-Build` creates a PyInstaller one-folder build after the full regression. The r31 default stage names are:

- approved source-only release: `ChromaMatter_0.8beta-r31-source-public-20260820`
- non-public software preflight: `ChromaMatter_0.8beta-r31-ai-model-print-studio`

## Privacy and licensing

Do not include non-public validation assets or identifying details in the public tree or release candidate. Public samples require traceable rights and provenance.

The application is `GPL-3.0-or-later`. Bundled dependencies have their own licences, and TetGen itself is `AGPL-3.0-or-later`. Review `licenses/` and the publication checklist before binary distribution.

OpenAI Codex was used during development. Product requirements, validation, acceptance, and publication decisions remain with the project proposer.
