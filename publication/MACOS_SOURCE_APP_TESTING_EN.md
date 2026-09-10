# ChromaMatter 0.9 — macOS source-backed app

This Apple Silicon / macOS 15+ test package includes **ChromaMatter Source
Alpha.app**, the current application source and a guided launcher. It is not
a standalone frozen executable: Python and the hash-locked dependencies are
installed on your Mac during first setup.

The current source includes Full Spectrum, Flat Four, manual editing, the
separate Output Settings window and selectable export geometry checks. High
is the default. Shared-source and package tests on Windows do not establish
that this exact version works on macOS; Mac startup, Finder, rendering and
3MF output still need native testing. The automatic startup self-test is an
additional check, not proof that every model will export or print.

## Download and first launch

1. Obtain `ChromaMatter-0.9-macos-source-app.zip` and its matching SHA-256 from
   the project. Verify the checksum with `shasum -a 256` before extracting.
2. Extract the ZIP completely. Keep `ChromaMatter Source Alpha.app`,
   `README_INSTALL_AND_TEST_EN.md`, `SOURCE_COMMIT.txt`, the notice and manifest
   together. DemoData is **not bundled**; it is a separate download from
   [the download page](https://chromamatter.app/download).
3. Control-click the app and choose **Open**. If macOS offers **Open Anyway**,
   use **System Settings > Privacy & Security** for this copy only. The app
   is not Developer ID signed or Apple-notarized. Do not disable Gatekeeper,
   remove quarantine with commands or use a security bypass.
4. Terminal opens and displays setup. Keep that window open. An internet
   connection is required on first launch; dependencies can take several
   hundred MB. If native Python 3.13.14 is missing, the launcher verifies the
   official Python.org installer hash/signature and opens Apple's Installer.
   Complete it, return to Terminal and press Return. The official installer
   may request your administrator password; ChromaMatter does not enter it.
5. The private runtime is created under
   `~/Library/Application Support/ChromaMatter Source Alpha/`. The app starts
   only after its native/render self-test succeeds. Later launches reuse the
   matching runtime. Model files are processed locally, not uploaded.

If setup fails, retain the final Terminal message and report it. Do not change
dependency hashes or install arbitrary replacement versions to force startup.
Intel Macs and macOS below 15 are not supported by this package.

## Quick test

The launcher generates a tiny rights-safe four-box GLB in its Application
Support `TestData` folder. This is not the separately downloaded Hi3D DemoData;
no GLB, image or 3MF demonstration payload is included in the app ZIP.

1. Switch Japanese/English and verify the footer buttons **Output Settings**,
   **Solidify**, **Export 3MF**. Open/close Output Settings; edited values should
   survive Close, Escape and reopening.
2. Open the generated four-box GLB or a model you may use. Test rotation,
   zoom, Full Spectrum with 32 palette states, and Flat Four. Four-box colours
   alone do not demonstrate all 32 mixed states visually.
3. In Manual Editing, try Fill, Undo and Redo. Save/reopen a project and check
   colours, edits and output settings.
4. For ordinary output leave the geometry check at **High**, use **Solidify**
   if needed, and export. Multiple or damaged parts may still fail repair.
5. Lower checks are explicit experimental choices; **Ignore defects (not
   recommended)** does not repair a model. Confirm the short warning each
   time. A successful archive export does not establish a closed or printable
   model. Always inspect the resulting project in Orca **Slice Preview**
   before printing, especially after any non-High export.

For separate DemoData, read its own README/NOTICE before use. Its part names
may not match geometry, and its prescribed physical black correction remains
important. Previously successful demo outputs do not guarantee other models.

Report Pass / Fail / Not tested for setup, UI language, rendering, each colour
mode, project reload, export and Orca preview. Include the source commit from
`SOURCE_COMMIT.txt`, ZIP checksum, Mac chip/RAM and macOS version. Remove
private filenames, home paths and customer models from diagnostic reports.

## Package scope

The ZIP contains application source, shell launchers and non-native assets,
with executable Unix permissions retained. It contains no Python runtime,
third-party native binary, wheel, virtual environment or DemoData. The source
manifest and fresh-extraction checks verify packaging, not native execution.
No current native Mac success or publication is asserted by this guide.

This source-backed route does not weaken or satisfy the separate frozen
macOS binary's source/build/relink distribution gate. ChromaMatter application
code remains GPL-3.0-or-later; dependencies retain their own licences.
