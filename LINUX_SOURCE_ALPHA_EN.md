# ChromaMatter Linux x86_64 Source Alpha

This is the public Linux testing path for the ChromaMatter 0.9 development
source. It runs
the reviewed ChromaMatter source directly and downloads the exact hash-pinned
third-party wheels during local setup. It is not a standalone frozen Linux
binary and it is not a stable release.

The principal 0.9 upgrade is improved 3MF output accuracy and success for
ordinary single-logical GLB input. Exact duplicate seams can be welded, and
only strictly planar tiny openings no wider than 2.0 mm may be locally capped;
repair itself remains strict. Exports start with **High**, the existing
fail-closed geometry-check level. Complex multipart repair is still
input-dependent.

## Supported test environment

- Ubuntu 22.04 or newer
- x86_64 CPU
- Graphical desktop session or WSLg
- Internet access during first setup
- `uv` Python manager
- Approximately 1 GB of free space for the managed Python environment and
  dependencies

## Setup

1. Extract the complete archive into a normal writable folder.
2. Install `uv` using its official instructions if it is not already present:
   <https://docs.astral.sh/uv/getting-started/installation/>
3. Open a terminal in the extracted folder.
4. Run:

   ```bash
   chmod +x INSTALL_LINUX_SOURCE_ALPHA.sh RUN_LINUX_SOURCE_ALPHA.sh
   ./INSTALL_LINUX_SOURCE_ALPHA.sh
   ```

5. Start ChromaMatter:

   ```bash
   ./RUN_LINUX_SOURCE_ALPHA.sh
   ```

The setup script does not run `sudo` automatically. If the required Japanese
fonts are missing, it stops and shows this command:

```bash
sudo apt-get update
sudo apt-get install -y fonts-noto-cjk xfonts-base xfonts-intl-japanese xfonts-intl-japanese-big
```

## What to test

`DemoData` is **not bundled** with this application. Download the optional demo
separately from the [official download page](https://chromamatter.app/download)
and read its README and NOTICE before using the source GLB or reference image.
You can keep it in any normal data folder; it does not need to be placed inside
the application folder.

Start with a small OBJ or GLB model rather than a complex production model.
Please check:

1. Japanese and English UI text is visible.
2. OBJ and GLB import works.
3. Full Spectrum and Flat Four previews update correctly.
4. Manual colour correction remains usable.
5. **Output Settings** in the bottom bar opens a separate window and keeps your
   settings when closed. **Solidify** is an independent button beside
   **Export 3MF**; use it when repair is needed.
6. **Geometry check** starts at **High**. **Medium**, **Low**, and **Ignore defects
   (not recommended)** change export-only checks, not the model or strict manual
   Solidify operation. Lower settings can export damaged geometry and require
   confirmation. Colour and archive checks remain mandatory.
7. Snapmaker Orca can open the exported 3MF. Inspect its Slice Preview before
   printing, regardless of the selected geometry-check level.

Use the Linux feedback form at <https://chromamatter.app/feedback/linux>.
Include Ubuntu version, desktop environment, the step that failed, exact error
text, and whether the model may be shared privately. Do not upload confidential
models or toolpaths.

## Current limitations

- Unsigned experimental alpha.
- Snapmaker U1 physical-print validation is still in progress.
- Flat Four remains experimental.
- The first setup downloads dependencies and can take several minutes.
- A standalone frozen Linux archive remains under a separate third-party
  binary/source/relink compliance audit.

ChromaMatter itself is licensed under GPL-3.0-or-later. See `LICENSE`,
`licenses/`, and the repository documentation for source and third-party
notices.
