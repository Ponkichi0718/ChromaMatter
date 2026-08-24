# ChromaMatter 0.8beta (r32.1)

[日本語](README_JA.md)

ChromaMatter is a Windows desktop application that maps the colours of a vertex-coloured OBJ or supported GLB to four physical filaments and creates a 3MF project for inspection in Snapmaker Orca. It is an independent project and is not an official or affiliated product of TripoAI, Hi3D AI, Snapmaker, OpenAI, or any other third party.

## Quick start

1. Extract the whole ZIP to a normal folder.
2. Run `START_CHROMAMATTER.cmd` or `ChromaMatter.exe`.
3. Open an OBJ or GLB, review F1-F4, mixed-state count, size, and geometry, then export 3MF.
4. Open the 3MF **as a project** in Snapmaker Orca and inspect tool order, materials, and the slice preview before printing.

To try the shortest workflow with the bundled Hi3D multipart GLB, see [DemoData/README_EN.md](DemoData/README_EN.md).

**Important 0.8 beta limitation:** Solidification of multipart models is still unstable. The bundled `DemoData` is a confirmed successful case, but other multipart files may fail to solidify or export as 3MF. This incomplete compatibility is one reason ChromaMatter remains `0.8beta`.

If Windows displays a protection warning, first verify the SHA-256 on the official Release page and any signing information when a signature is provided. Do not bypass a warning for a file whose origin you cannot verify.

## Scope and limitations

- Windows x64 is supported.
- OBJ vertex colour is expected in `v x y z r g b` form.
- GLB support targets static embedded base colour and `COLOR_0`. Animation, skinning, morph targets, Draco, meshopt, BasisU, and external URIs are unsupported.
- Hi3D-style multipart GLB support is beta and unofficial. ChromaMatter suppresses categorical part-identification `COLOR_0` only when exporter, node, material, shared-texture, and known-palette evidence all agree; otherwise ordinary authored colour is preserved.
- For an eligible multipart GLB, source parts are solidified independently without welding separate parts together, then may be exported as one combined 3MF and optional standalone 3MF files per print part. Unsupported or ambiguous files stop safely; compatibility with every Hi3D export is not guaranteed.
- Displayed and printed colour are not guaranteed to match. Use a comparison chart and test print with the same materials and production conditions.
- Solidify acts only when its safety conditions can be proven. Displaying a model does not guarantee automatic repair or printability.
- Preparing, solidifying, and manually editing large models can require substantial time and memory.

## Privacy and issue reports

Model processing stays on the PC and is not intentionally uploaded to a project-operated server. See [PRIVACY.md](PRIVACY.md) for details.

Do not attach a private model to an issue. Report the ChromaMatter version, Windows version, reproduction steps, and error text. If a model is required, create a new minimal fixture that is safe to share.

## Licence and source

ChromaMatter is licensed under `GPL-3.0-or-later`. See [LICENSE.txt](LICENSE.txt) for the licence text and [licenses](licenses/) for third-party terms and notices. The location of the complete corresponding source for this binary is recorded in [licenses/SOURCE_OFFER_EN.txt](licenses/SOURCE_OFFER_EN.txt).

`SOFTWARE_PACKAGE_SHA256.txt` covers files inside this package. `SHA256SUMS-r32.1.txt`, published alongside the Release assets, is the checksum authority for the complete Release.
