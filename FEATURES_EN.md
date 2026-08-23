# What ChromaMatter Does

<p align="center">
  <img src="source/fixed_app/assets/obj_adjuster_icon.png" width="220" alt="ChromaMatter — AI Model Print Studio">
</p>

## From AI-generated colour to four physical filaments

ChromaMatter — AI Model Print Studio turns AI-generated coloured 3D models into 3MF projects for the Snapmaker Orca Full Spectrum / Color Mixing workflow.

This is more than a file-format converter. The project gives AI 3D generation a route into physical colour printing and gives a colour 3D printer a new source of printable models.

<a href="https://note.com/ponkichi0718/n/n711977c75aa4"><img src="https://assets.st-note.com/img/1787193863-DjEUKLdVrxFgauov4mzq7QB9.png?width=1200" alt="Current ChromaMatter development UI showing four base filaments, mixed palette, source colour, and Full Spectrum preview"></a>

*Current development UI. Four real filaments, the mixed palette, and source versus converted colour remain visible together.*

<table>
  <tr>
    <td width="25%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038136-QYcX12yPUL4fzm5RWZNbiEqM.jpg?width=1200" alt="Original AI-assisted concept image used for the public workflow"></a></td>
    <td width="25%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038182-v0C8IT5i1jVeKLdNX3ZygYu4.png?width=1200" alt="Coloured 3D model generated from the original concept"></a></td>
    <td width="25%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038261-fQtHZho5CXvrYl94M7zJOqLD.png?width=1200" alt="ChromaMatter comparing the source, AI model, and Full Spectrum colours"></a></td>
    <td width="25%"><a href="https://note.com/ponkichi0718/n/nad23088e6f2d"><img src="https://assets.st-note.com/img/1787038285-sNiOGxEzyLoRrklQAXH7BJ8W.png?width=1200" alt="The exported ChromaMatter 3MF opened as a Snapmaker Orca project"></a></td>
  </tr>
  <tr>
    <td align="center">1. AI-assisted original concept</td>
    <td align="center">2. Generated colour 3D model</td>
    <td align="center">3. Inspect and convert in ChromaMatter</td>
    <td align="center">4. Verify the 3MF in Snapmaker Orca</td>
  </tr>
</table>

These are previously published project images linked from the author's note. A full-body, one-piece U1 result is now documented in [ChromaMatter Sample Character — Print Results](https://note.com/ponkichi0718/n/nf6c77165127c); the exact release-bound sample, hashes, filament records, Orca/U1 profile, and comparison set are still being assembled. The [development journal on note](https://note.com/ponkichi0718) contains the longer experiment history.

## 1. One local workflow for OBJ and GLB

ChromaMatter accepts:

- OBJ containing per-vertex colour as `v x y z r g b`
- static GLB containing `COLOR_0`, embedded base-colour factors, or embedded base-colour textures

Scene and node transforms are applied, supported GLB colour is baked into the existing vertex-colour pipeline, and the source model stays on the local PC. Supported multipart GLB assets retain their part structure through solidification and can be exported as a combined 3MF or one 3MF per print part. Unsupported compression, animation, skinning, external assets, and other ambiguous inputs fail closed instead of being silently approximated.

## 2. Limited, unofficial Hi3D-style multipart GLB support (beta)

ChromaMatter is independent and is not an official or affiliated Hi3D AI product. It does not claim compatibility with every file produced by Hi3D. For a supported static GLB with embedded assets, it can preserve mesh-node parts and their placement through the colour and 3MF workflow.

- A categorical part-identification `COLOR_0` is suppressed only when exporter provenance, node structure, materials, a shared base-colour texture, and the known identification-palette sequence all agree. If that proof is incomplete, ordinary authored vertex colour keeps the normal glTF multiply behaviour.
- Each source part is normalised and solidified independently. Separate parts are not welded together, and imported faces remain distinguishable from repair-generated faces.
- A validated assembly can be exported as one combined 3MF and, when requested, as standalone 3MF files per print part with a manifest. Incomplete or stale part/provenance mapping stops safely instead of weakening validation.
- Only proven exact seams and narrowly bounded, explicitly requested tiny planar repairs are eligible. Animation, skinning, morph targets, Draco, meshopt, BasisU, external URIs, and unsupported or ambiguous geometry remain outside this beta scope.

The [public print and multipart-GLB development record](https://note.com/ponkichi0718/n/nf6c77165127c) shows why identification colours must be separated from the intended base colour and records the current per-part export path.

## 3. Four filaments, up to 32 printable colour states

<a href="https://note.com/ponkichi0718/n/n711977c75aa4"><img src="https://assets.st-note.com/img/1787193878-2RMCKirmlunSDIXfhzQgEHpd.png?width=1200" alt="Filament candidate library for assigning real products to F1 through F4"></a>

F1-F4 are four physical filaments of one selected material. ChromaMatter proposes a balanced set from a bundled real-product colour library, then constructs a 16, 24, or 32-state palette including Full Spectrum combinations such as F1+F2 and F1+F3.

The same state order is used in the preview, 3MF, and numbered calibration chart. If you want to try a different F1-F4 combination, **Apply Current F1-F4 to Preview / 3MF** updates the converted preview and output palette without discarding canonical state IDs or existing manual paint.

PLA is the default. ABS and PETG support are beta. A single project does not intentionally mix different material families.

## 4. Compare, calibrate, and manually refine

<a href="https://note.com/ponkichi0718/n/n711977c75aa4"><img src="https://assets.st-note.com/img/1787194049-FwXqus5ArK8B4NoU1eIQYzPg.png?width=1200" alt="Numbered physical comparison chart arranged in the same order as the ChromaMatter palette"></a>

The main view places the original model colour beside the Full Spectrum conversion so differences are visible before export. Manual Editing can then correct only the areas that need human judgement.

<a href="https://note.com/ponkichi0718/n/n711977c75aa4"><img src="https://assets.st-note.com/img/1787193923-A1VTIhjR6w07qWedXZloDEFU.png?width=1200" alt="Manual Editing with Brush, Airbrush, Smudge, and Eyedropper controls"></a>

- shading, gamma, contrast, and saturation controls
- Brush, Airbrush, Fill, Smudge, and Eyedropper
- visible-face and selected-part guards
- Undo / Redo and portable project folders
- a numbered 3MF comparison chart generated from the current F1-F4 palette

Catalogue colours and on-screen previews are estimates, not promises of physical colour. Filament translucency, walls, slopes, top layers, calibration, and integer layer switching can all change the printed result. Use a calibration chart and the Orca slice preview for final decisions.

## 5. Safer 3MF export for Snapmaker Orca

Before export, ChromaMatter checks the prepared geometry. An eligible GLB can safely weld apparent openings only when coincident boundary edges prove exact 1:1 reversed UV or texture seams. Supported multipart assets are normalised independently per source part, without welding separate parts together, while source and repair-generated faces remain distinguishable. Hi3D-style categorical identification colour is suppressed only when exporter, node, material, texture, and known-palette evidence all agree; ordinary authored colour remains intact. If export needs solidification, the app announces it, processes the model, and resumes only after success.

This is deliberately not a universal hole repair tool. During supported multipart repair, only a closed unmatched boundary loop with a span of at most 2.0 mm and planarity deviation of at most 0.02 mm may receive a strictly local planar cap. Larger, non-planar, ambiguous, or non-manifold openings remain fail-closed; the single-GLB UV-seam welding path never adds caps.

The exported project records a conservative Full Spectrum layer-cycle and prime-tower baseline. Experimental Local Z, advanced dithering, and pointillism remain disabled. Support, material calibration, temperature, flow, speed, and retraction stay under the user's control in Snapmaker Orca.

## Why the project is still beta

ChromaMatter is currently `0.8beta`.

- Source code is public.
- A Windows binary is not public while the [third-party binary redistribution audit](licenses/THIRD_PARTY_LICENSES.txt) is in progress.
- A rights-cleared public test model is in preparation.
- A public physical U1 result has been observed; exact release-bound reproducibility validation remains in progress.

The project is independent and is not an official or affiliated product of TripoAI, Hi3D AI, Snapmaker, OpenAI, or any other third party.

## Development process and AI disclosure

ChatGPT, OpenAI Codex, and other AI tools have been used throughout planning, specification, implementation, testing, documentation, image work, and GitHub publication. The project author makes the final decisions about behaviour, acceptance, physical validation, and release.

AI-generated code and writing can contain awkward language or technical mistakes. Please verify important settings in the source, exported 3MF, Snapmaker Orca preview, and your own hardware. Reports are welcome through [GitHub Issues](https://github.com/Ponkichi0718/ChromaMatter/issues).

- [Public sample-character print result and multipart GLB development record](https://note.com/ponkichi0718/n/nf6c77165127c)

[Back to the English README](README.md) · [日本語の機能紹介](FEATURES_JA.md) · [Development journal](https://note.com/ponkichi0718)
