# Snapmaker Orca with CM

**Color adjustment, local cutting and material tools in one Orca workflow.**

[日本語](README_JA.md) · [Official website](https://chromamatter.app/) · [Downloads and setup](https://chromamatter.app/download)

## Download — dev3-R8 experimental

An unofficial modification of Snapmaker Orca 2.4.0. **dev3-R8 is a development release**, not a guarantee that every model or printer workflow will work.

| Windows | macOS | Linux |
| --- | --- | --- |
| [Download ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/Snapmaker-Orca-CM-dev3-R8-Windows-x64.zip) | [Download app ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/CM-dev3-R8-macos-arm64-app.zip) | [Download tar.gz](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/Snapmaker-Orca-CM-dev3-R8-Linux-x86_64.tar.gz) |
| x64 | Apple Silicon · macOS 15+ | x86_64 · Ubuntu 22.04 |

[Release notes, checksums and source](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/cm-orca-dev3-r8-20261013)

- **Keep originals.** Work on copies and save projects under new names. Inspect the slice preview before printing.
- **Windows settings are shared with existing CM builds.** Extracting this package to another folder does not isolate its settings. Back up settings before trying it.
- **Mac:** ad-hoc signature only; no Developer ID signature or Apple notarization. Intel Macs are not supported.
- CM-specific project data requires a compatible CM build. Stock Orca and older CM versions are not equivalent readers.

## What is included

- **Color:** Full Spectrum, CMY and Flat Color workflows; brush editing, color replacement and shading tools.
- **Cut:** movable and rotatable cut planes, optional X/Y limits, cut-surface and attached plug/socket connector tools.
- **Protection and bridges:** connected-surface protection brushes, protection overlays, and two-point cylindrical or rectangular bridges.
- **Plate-local materials (eligible Flat Color projects):** a plate using no more than four physical materials can be sliced even when the project contains more palette candidates. A plate actually using five or more still needs manual changes; colors are not automatically merged.
- **Editing responsiveness:** reuse of validated compressed original-source data reduces repeated backup work. An initial cache miss can still require compression.

Protection assistance follows geometry, not the meaning of a model's parts. Check the protected region and cut side before applying a cut. Difficult geometry can still fail.

## Validation and limits

Build/startup checks and focused regression tests are separate from real-model operation and printing. **Mac and Linux GUI operation, real-model editing/cutting, slicing and printing have not been verified for these packages.** Windows results do not establish equivalent behavior on those platforms. R8 GUI/printing behavior is not exhaustively validated.

Color previews are estimates, not a calibrated guarantee of printed color. Results depend on the model, filament, printer and settings. Keep the experimental status and check the actual output.

## Source and project background

[Windows matching source ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/Snapmaker-Orca-CM-dev3-R8-Windows-source.zip) · [Linux build supplement](https://github.com/Ponkichi0718/ChromaMatter/releases/download/cm-orca-dev3-r8-20261013/CM-dev3-R8-Linux-Source-Supplement-20261013.zip)

Release-specific corresponding source and build information are listed with the [dev3-R8 release](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/cm-orca-dev3-r8-20261013). The [R8 native/helper build inputs](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/cm-orca-dev3-r8-build-inputs-20261012) are source material, not an application download or an offline SDK. Use the release-specific sources for Orca; the repository's older standalone source tree is historical.

**ChromaMatter is the underlying color-processing technology that grew into this Orca integration.** The earlier standalone application is retained as project history, rather than presented here as another product to download. Its historical source, records and licensing remain separate from the evidence for this Orca release.

[License](LICENSE) · [Third-party notices](licenses/) · [Security](SECURITY.md)
