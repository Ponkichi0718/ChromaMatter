# ChromaMatter 0.9 for Windows

[日本語](README_JA.md)

ChromaMatter maps the colours of a vertex-coloured OBJ or supported GLB to
four physical filaments and creates a 3MF project for inspection in Snapmaker
Orca. It is an independent project and is not an official or affiliated
product of TripoAI, Hi3D AI, Snapmaker, OpenAI, or any other third party.

## What's new in 0.9

The main upgrade is **improved 3MF output accuracy and repair
success for ordinary single-model GLB files**. The repair path can join proven
coincident seams, remove narrowly qualified microscopic debris, and repair
eligible tiny planar openings. With **High**, the initial geometry-check
setting, the result must still pass the existing final solid and 3MF checks.

Complex multipart models remain input-dependent and may still fail. If repair
stops, the imported original geometry, colours, and manual edits are preserved;
the failure window no longer offers a separate 3D boundary-inspection screen.
The Radial Experiment has been removed from the application interface.

## Quick start

1. Extract the whole ZIP to a **new folder**. Do not run it inside the ZIP or
   overwrite an older installation; keep `ChromaMatter.exe` and `_internal`
   together.
2. Run `START_CHROMAMATTER.cmd` or `ChromaMatter.exe`.
3. Choose **Open OBJ / GLB** and load your model. A fresh profile starts in
   **Flat Four** mode; choose **Full Spectrum** for mixed colours. Review F1-F4
   and the preview, and apply any pending filament-colour edits.
4. Click **Output Settings** in the bottom bar to open its separate window and
   check the output size. **Solidify** is an independent button beside
   **Export 3MF**; use it if repair is needed and wait for it to finish. Large
   missing surfaces or complex failures may need a separate repair tool.
5. Choose **Export 3MF** and a new output location. Keep the original model and
   save a project folder if you want to continue editing later.
6. Open the 3MF **as a project** in Snapmaker Orca and inspect tool order,
   materials, geometry, and the slice preview before printing.

**Geometry check** starts at **High**. **Medium**, **Low**, and **Ignore defects
(not recommended)** change export-only checks; they do not repair the model or
change the strict manual Solidify operation. Lower settings can export damaged
geometry and require confirmation. Colour and archive checks remain mandatory.

`DemoData` is **not bundled** with this application. Download the optional demo
separately from the [official download page](https://chromamatter.app/download).
The source GLB and reference image come with their own README/NOTICE documents
and manifest; read those documents before using them. This application package
contains **no sample or generated 3MF**.

## Flat Four

- Flat Four assigns broad colour regions directly to F1-F4 and is the default
  for a new profile and a newly opened model.
- Meaningful white and black details are preserved conservatively. Small
  high-confidence white or gray lighting patches on a smooth chromatic surface
  may be folded into the surrounding chromatic slot.
- Four physical F1-F4 slots and the 3MF state schema remain present. Manual
  Editing remains authoritative.
- Full Spectrum remains available; select it when mixed filament states are
  desired.

Manual Editing includes brushes, an airbrush, an eyedropper, fill, and blending.
Experimental **Cel Colour** and **Shaded Monochrome** filters remain available
for printable stepped shading. Their appearance depends on the source colours,
geometry, palette, and real filaments; they do not guarantee a hand-painted look.

**Important limitations:** this is not semantic AI recognition. Automatic
colour classification can misinterpret baked lighting, shadows, small details,
or ambiguous materials. Multipart solidification and per-part 3MF export are
input-dependent beta features. Repair remains strict; export uses your selected
geometry-check level and does not guarantee printability.

## Scope and limitations

- Windows x64 is supported by this package.
- OBJ vertex colour is expected in `v x y z r g b` form.
- GLB support targets static embedded base colour and `COLOR_0`. Animation,
  skinning, morph targets, Draco, meshopt, BasisU, and external URIs are
  unsupported.
- Hi3D-style multipart GLB support is beta and unofficial. ChromaMatter
  suppresses categorical part-identification `COLOR_0` only when the available
  evidence agrees; otherwise ordinary authored colour is preserved.
- Displayed and printed colour are not guaranteed to match. Use a comparison
  chart and test print with the same materials and production conditions.
- Displaying or importing a model does not guarantee automatic repair,
  watertightness, slicing, or printability.

This package is unsigned, so Windows may display a protection warning. First
verify the download source, the exact archive's SHA-256, and any available
signing information. Do not disable Windows protection or bypass a warning for
a file whose origin you cannot verify.

## Privacy and issue reports

Model processing stays on the PC and is not intentionally uploaded to a
project-operated server. See [PRIVACY.md](PRIVACY.md) for details.

Do not attach a private model to a public issue. Report the ChromaMatter and
Windows versions, reproduction steps, and error text. If a model is required,
create a new minimal fixture that is safe to share.

## Licence and source

ChromaMatter is licensed under `GPL-3.0-or-later`. See [LICENSE.txt](LICENSE.txt)
and [licenses](licenses/) for the applicable terms and third-party notices. The
complete corresponding-source location for this binary is recorded in
[licenses/SOURCE_OFFER_EN.txt](licenses/SOURCE_OFFER_EN.txt).

`SOFTWARE_PACKAGE_SHA256.txt` covers the files inside this package. Release-level
checksums, when published, must match this exact build and archive.
