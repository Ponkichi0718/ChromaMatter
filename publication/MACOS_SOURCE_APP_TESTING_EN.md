# ChromaMatter Source-backed App Alpha 2 — Install and Test

This guide is for the Finder-launchable **ChromaMatter Source Alpha.app** in
the published Alpha 2 package on Apple Silicon Macs running macOS 15 or newer.
The displayed product version is still `0.8beta`. Source-backed App Alpha 1
remains an immutable historical Release. Alpha 2 is GitHub prerelease
[#377168223](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-app-alpha2),
published at `2026-08-26T13:33:38Z` from exact tag/source commit
`34e7ebdc3ec7dae6ad831b5119d574a656b105b0`.

## Read this distinction first

This is a real `.app` bundle for Finder, but it is **source-backed**. It does
not contain a prebuilt Python runtime or third-party native libraries. Opening
the app starts the reviewed source launcher in Terminal. On first launch that
launcher may install the verified official Python 3.13.14 package and exact
hash-locked dependencies on your Mac, run an automatic native/render self-
test, and then start ChromaMatter from source.

This route does not bypass or replace the separate prebuilt-app approval gate.
It is not Developer ID signed or Apple-notarized. Do not disable Gatekeeper,
run `xattr` commands, or use `sudo` to make it open.

## Package contents

The fixed public ZIP name is:

`ChromaMatter-0.8beta-macos-source-app-alpha2.zip`

Its frozen public identity is 217,943,261 bytes with SHA-256
`C112396513B0EA21CD867ED016E2D5282F830235E3EBF324E45E3B4FDB647989`.
The detached `SHA256SUMS-macos-source-app-alpha2.txt` asset is 115 bytes with
SHA-256 `8152D72AD978246D8B41BC1A64B2855897CBD43BAE7E36402192EF3883595129`.

After extraction, keep this folder together:

```text
ChromaMatter-0.8beta-macos-source-app-alpha2/
  ChromaMatter Source Alpha.app/
  README_INSTALL_AND_TEST_EN.md
  SOURCE_BACKED_ALPHA_NOTICE.txt
  SOURCE_COMMIT.txt
  ChromaMatter-Public-Four-Color-Test.glb
  ChromaMatter-Public-Four-Color-Test.glb.sha256
  DemoData/
    DEMO_DATA_MANIFEST.json
    README_EN.md
    README_JA.md
    NOTICE_EN.md
    NOTICE_JA.md
    Original AI model Color.glb
    Reference.jpg
    3MF/
      Original AI model Color_FullSpectrum.3mf
      Original AI model Color_FullSpectrum_parts_2/
        01_RightArm_FullSpectrum.3mf
        02_LeftLeg_FullSpectrum.3mf
        03_Head_FullSpectrum.3mf
        04_LeftArm_FullSpectrum.3mf
        05_Torso_FullSpectrum.3mf
        06_RightLeg_FullSpectrum.3mf
        パーツ別3MF_manifest.json
  SOURCE_APP_PACKAGE_MANIFEST.json
  SOFTWARE_PACKAGE_SHA256.txt
```

`DemoData/` has exactly 15 canonical files: four README/NOTICE documents, the
canonical `DEMO_DATA_MANIFEST.json`, the original GLB and reference image,
seven Full Spectrum 3MF outputs, and the part-output manifest. It stays beside
the app and must never be moved into the `.app` bundle. The outer JSON package
manifest independently covers every regular package file except itself and
`SOFTWARE_PACKAGE_SHA256.txt`. The checksum file is sorted; each line uses an
uppercase SHA-256 digest, two ASCII spaces, and a POSIX path. It covers every
other regular file, including `SOURCE_APP_PACKAGE_MANIFEST.json`, and excludes
only itself. The DemoData manifest remains the stable r32.2 payload allowlist
and hash authority.

Exact-tag run
[#32974429065](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32974429065)
passed. Both public Release assets were downloaded without authentication and
matched the sizes and hashes above. A fresh public extraction passed the
260-file outer package audit; DemoData contained exactly 15 files, 10 manifest
payloads, and 236,274,418 payload bytes; and the 238-file app audit passed with
zero native-runtime files and the exact source commit. A local staging folder,
manual-run artifact, or GitHub artifact with `diagnostics` in its name is not
the published app package.

## Download, verify, and extract

1. Download the
   [fixed Alpha 2 ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-app-alpha2/ChromaMatter-0.8beta-macos-source-app-alpha2.zip)
   and
   [`SHA256SUMS-macos-source-app-alpha2.txt`](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-app-alpha2/SHA256SUMS-macos-source-app-alpha2.txt)
   from the same approved Release.
2. In Terminal, type `shasum -a 256 `, including the trailing space. Drag the
   ZIP into Terminal and press Return.
3. Compare all 64 characters with the supplied checksum. Stop if they differ.
4. Extract the ZIP completely in Finder. Do not run the app from inside the ZIP
   and do not move the `.app` away from the guide and public test model.
5. Optional: verify the model by opening Terminal in the extracted folder and
   running `shasum -a 256 -c ChromaMatter-Public-Four-Color-Test.glb.sha256`.

## First launch

1. Read `SOURCE_BACKED_ALPHA_NOTICE.txt`.
2. Control-click **ChromaMatter Source Alpha.app** and choose **Open**.
3. Choose **Open** again if macOS asks. If macOS offers **Open Anyway**, use
   **System Settings > Privacy & Security** for this copy only.
4. Terminal opens and shows setup progress. Keep it open.
5. If Python 3.13.14 is missing, the launcher downloads the official installer,
   verifies its SHA-256 and signature, and opens Apple's Installer. Complete
   the normal Installer screens, return to the original Terminal window, and
   press Return. The Installer itself may request an administrator password.
6. Wait while exact hash-locked dependencies are installed under
   `~/Library/Application Support/ChromaMatter Source Alpha/` and the automatic
   native/render self-test runs.
7. ChromaMatter opens only after that self-test passes. Later app launches reuse
   the private environment.

Stop and report the final Terminal lines if setup or self-test fails. Do not
edit the dependency lock, install a different package manually, or search for
a macOS security bypass.

## 10-minute quick-fixture test

Use `ChromaMatter-Public-Four-Color-Test.glb` beside the app. It is a small CC0
model containing four closed red, blue, white, and black boxes.

1. Confirm that the main window remains responsive for 30 seconds.
2. Switch between Japanese and English and confirm that the main controls stay
   readable.
3. Choose **Open OBJ / GLB** and open the supplied GLB.
4. Orbit, pan, and zoom. All four boxes should remain visible.
5. Select **Full Spectrum (Mixed)**, change the total palette colours from the
   default 16 to **32**, and confirm that the preview recalculates. This checks
   the 32-state processing path; the four-colour fixture does not force every
   mixed state to appear on the model at once.
6. Select **Flat 4 Colors** and confirm that it uses physical F1-F4 only,
   without an F5+ mixed state.
7. Open **Manual Editing**, use **Fill** on one box, then test Undo and Redo.
8. Export a 3MF. This closed public model should export successfully and a
   failed export must not leave a misleading partial file.
9. Save a project, quit ChromaMatter, open the app again, and reload the
   project. Confirm that the mode, F1-F4 colours, and manual edit remain.
10. Optional: open the 3MF **as a project** in Snapmaker Orca. Do not print it
    for this basic software test.

Record **Pass**, **Fail**, or **Not tested** for every step. If one operation
shows no progress for more than 60 seconds, note the wait and stop that step.

## Extended stable r32.2 DemoData test

The quick four-box GLB is deliberately tiny. `DemoData/Original AI model
Color.glb` is the realistic six-part Hi3D-generated input used by the stable
r32.2 release. It exercises a substantially larger multipart, 32-state Full
Spectrum path. This extended test can take much longer than ten minutes.

1. Read `DemoData/README_EN.md`, `DemoData/NOTICE_EN.md`, and
   `DemoData/DEMO_DATA_MANIFEST.json`. Do not add, rename, regenerate, or
   replace anything in `DemoData/` when checking the published package.
2. Open `DemoData/Original AI model Color.glb` and, if useful, its adjacent
   `Reference.jpg`. Select **Full Spectrum (Mixed)** and explicitly select 32
   total palette states.
3. Before regenerating any 3MF, under **Filament Settings > Physical Black
   Correction**, select the F slot that will physically contain black and
   enable **Weak Black (5–25%)**. This is mandatory for this demo workflow.
4. Do not trust the Hi3D-derived part names as descriptions of the visible
   regions. `RightArm`, `LeftLeg`, and the other labels can disagree with the
   geometry you see; inspect every part visually.
5. Under **Output Settings**, choose **Solidify**. Multipart solidification is
   still unstable beta behavior and can fail. If it fails, record the exact
   message; do not bypass the closed-solid or 3MF validation gate.
6. Inspect the included combined 3MF and six part-specific 3MFs under
   `DemoData/3MF/` by opening them **as projects** in Snapmaker Orca. Check
   geometry, materials, tool order, and slice preview before any print.
7. Treat all seven included 3MFs as **Full Spectrum examples only**. They do
   not prove Flat Four output. A Flat Four claim requires a newly exported
   Flat Four project from the live GLB and its own inspection; do not relabel
   an included Full Spectrum file as Flat Four evidence.

The stable multipart GLB is a confirmed successful r32.2 example, not a
promise that every Hi3D or multipart GLB will solidify, export, slice, or print.

## Report a result

For a successful or partial result, setup question, or general observation,
use the [macOS Alpha Testing discussion](https://github.com/Ponkichi0718/ChromaMatter/discussions/9).
For one reproducible defect, use the [macOS alpha Issue form](https://github.com/Ponkichi0718/ChromaMatter/issues/new?template=macos_alpha_report.yml).

Include:

```text
Test route: Source-backed App Alpha 2
ZIP filename: ChromaMatter-0.8beta-macos-source-app-alpha2.zip
Verified ZIP SHA-256: C112396513B0EA21CD867ED016E2D5282F830235E3EBF324E45E3B4FDB647989
Source commit (SOURCE_COMMIT.txt):
Mac model/chip/RAM:
macOS version:
First setup: Pass / Fail
Automatic self-test: Pass / Fail
Japanese UI: Pass / Fail / Not tested
English UI: Pass / Fail / Not tested
Public GLB / Full Spectrum / Flat Four: Pass / Fail / Not tested
Manual Fill / Undo / Redo: Pass / Fail / Not tested
3MF export: Pass / Fail / Not tested
Project save / reload: Pass / Fail / Not tested
Stable DemoData 32-state load: Pass / Fail / Not tested
Weak Black 5–25% selected before DemoData export: Yes / No / Not tested
Stable DemoData solidify / included Full Spectrum 3MF review: Pass / Fail / Not tested
Final sanitized Terminal lines and notes:
```

## Known alpha limits and privacy

- Apple Silicon and macOS 15+ are the only supported test hosts.
- The first setup needs internet access and may download several hundred MB.
- Pen pressure is not part of this first Mac target; use a mouse or trackpad.
- Some multipart, damaged, compressed, animated, or otherwise unsupported
  models may be rejected safely.
- The supplied four-box GLB checks both Full Spectrum 32-state processing and
  Flat Four switching, but it does not force or visibly cover all 32 mixed
  states simultaneously.
- The stable multipart GLB is the realistic 32-state/Hi3D input. Its part names
  may not match visible regions, and **Weak Black 5–25% is mandatory** before
  regenerating its 3MF outputs.
- All seven included DemoData 3MFs are Full Spectrum examples. They do not
  establish that a Flat Four export was created or inspected.
- Multipart solidification remains unstable beta behavior. The included stable
  example succeeded, but another multipart GLB can fail solidification or 3MF
  export without any validation gate being weakened.
- Physical colour accuracy and printer safety are not proven by this test.

ChromaMatter processes model and project data locally and does not
intentionally upload those files to a project-operated server. Never attach a
purchased, customer, confidential, private, or third-party model. Remove user
names, home paths, account details, serial numbers, and private filenames from
Terminal output and screenshots before posting.

Do not redistribute or mirror the tester ZIP or `.app`; link to the exact
approved project location. ChromaMatter application source is
GPL-3.0-or-later, and third-party dependencies retain their own terms.
