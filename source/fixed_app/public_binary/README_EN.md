# ChromaMatter 0.8beta (r32.2 Flat Four Test 3)

[日本語](README_JA.md)

ChromaMatter is a Windows desktop application that maps the colours of a vertex-coloured OBJ or supported GLB to four physical filaments and creates a 3MF project for inspection in Snapmaker Orca. It is an independent project and is not an official or affiliated product of TripoAI, Hi3D AI, Snapmaker, OpenAI, or any other third party.

## Quick start

1. Extract the whole ZIP to a normal folder.
2. Run `START_CHROMAMATTER.cmd` or `ChromaMatter.exe`.
3. Open an OBJ or GLB, review F1-F4, mixed-state count, size, and geometry, then export 3MF.
4. Open the 3MF **as a project** in Snapmaker Orca and inspect tool order, materials, and the slice preview before printing.

This Test 3 package intentionally contains no bundled `DemoData`. Open only a
model that you are permitted to use, and keep private source models out of
public issue attachments.

Historical stable-r32.2 package record only (not this Test 3 package): The bundled `DemoData` is a confirmed successful case there. That evidence does not validate Test 3 or other inputs.

## Flat Four Test 3

- Flat Four does not remove white globally. Meaningful small white details,
  including eye whites beside dark linework, remain white targets; black detail
  is also preserved.
- Only small, high-confidence white/gray lighting patches on a smooth chromatic
  surface such as skin are conservatively folded into the chromatic F slot used
  around their boundary.
- Retained white covering at least **0.01%** of the total printable area reserves
  a suitable near-white filament during automatic recommendation. White below
  0.01% remains unabsorbed but does not by itself force a white spool, so it can
  map to the nearest selected F1-F4 colour.
- Four physical F1-F4 slots and the 3MF state schema are always retained. A model
  with no intentional white left may effectively use only three paint IDs.
  Manual Editing remains authoritative, and Full Spectrum is unchanged.

**Important limitations:** this is not semantic AI recognition. A tiny white
patch enclosed by one smooth skin/tan surface without a dark edge, crease, or
part boundary may be mistaken for a baked highlight. On an open mesh above
500,000 faces without reusable adjacency, only this automatic highlight
correction is skipped fail-closed. Multipart solidification and per-part 3MF
export also remain input-dependent beta features. This exact Test 3 package has
not yet been validated on a physical printer.

If Windows displays a protection warning, first verify the SHA-256 on the official Release page and any signing information when a signature is provided. Do not bypass a warning for a file whose origin you cannot verify.

## Scope and limitations

- Windows x64 is supported.
- OBJ vertex colour is expected in `v x y z r g b` form.
- GLB support targets static embedded base colour and `COLOR_0`. Animation, skinning, morph targets, Draco, meshopt, BasisU, and external URIs are unsupported.
- Hi3D-style multipart GLB support is beta and unofficial. ChromaMatter suppresses categorical part-identification `COLOR_0` only when exporter, node, material, shared-texture, and known-palette evidence all agree; otherwise ordinary authored colour is preserved.
- Solidification of multipart models is still unstable. This Test 3 package does not bundle `DemoData`; other multipart files may fail to solidify or export as 3MF. This incomplete compatibility is one reason ChromaMatter remains `0.8beta`.
- For an eligible multipart GLB, source parts are solidified independently without welding separate parts together, then may be exported as one combined 3MF and optional standalone 3MF files per print part. Unsupported or ambiguous files stop safely; compatibility with every Hi3D export is not guaranteed.
- Displayed and printed colour are not guaranteed to match. Use a comparison chart and test print with the same materials and production conditions.
- Solidify acts only when its safety conditions can be proven. Displaying a model does not guarantee automatic repair or printability.
- Preparing, solidifying, and manually editing large models can require substantial time and memory.

## Privacy and issue reports

Model processing stays on the PC and is not intentionally uploaded to a project-operated server. See [PRIVACY.md](PRIVACY.md) for details.

Do not attach a private model to an issue. Report the ChromaMatter version, Windows version, reproduction steps, and error text. If a model is required, create a new minimal fixture that is safe to share.

## Licence and source

ChromaMatter is licensed under `GPL-3.0-or-later`. See [LICENSE.txt](LICENSE.txt) for the licence text and [licenses](licenses/) for third-party terms and notices. The location of the complete corresponding source for this binary is recorded in [licenses/SOURCE_OFFER_EN.txt](licenses/SOURCE_OFFER_EN.txt).

`SOFTWARE_PACKAGE_SHA256.txt` covers files inside this package.
`SHA256SUMS-r32.2-flat4-test3.txt`, when published alongside the matching Test 3
Release assets, is the checksum authority for that complete experimental
Release. Until the Test 3 release gate passes, use the immutable published
`v0.8beta-r32.2` package and its `SHA256SUMS-r32.2.txt`.
