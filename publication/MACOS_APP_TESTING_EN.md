# ChromaMatter macOS Prebuilt App Tester

> **Status: not available for download yet.** This page prepares volunteers
> for the future prebuilt `.app` test. It is not a download approval. The app
> will be linked only after the exact build passes the separate
> native-component, corresponding-source, relinking, packaging, and fresh-
> extraction approval gate.

The currently available alternative is the
[Source Tester Alpha](MACOS_ALPHA_TESTING_EN.md). It uses a guided source
launcher and is a different test route.

## What the approved package will contain

After approval, the official tester ZIP will contain:

- `ChromaMatter-macOS-Alpha.app`;
- this English guide and a Japanese guide;
- `ChromaMatter-Public-Four-Color-Test.glb`;
- a SHA-256 record for the public test model;
- `SOURCE_COMMIT.txt` and build/self-test records; and
- the applicable licence, notice, component, and corresponding-source
  information.

The approved download link and the ZIP's 64-character SHA-256 will appear in
the [macOS Alpha Testing discussion](https://github.com/Ponkichi0718/ChromaMatter/discussions/9)
and the [English macOS testing hub](MACOS_ALPHA_HUB_EN.md). Until both are
posted, there is no valid prebuilt app download.

A GitHub Actions artifact with `diagnostics` in its name is a report, not the
app. Do not download an app from a comment, mirror, direct message, or
unverified third-party link.

## Before you start

You need:

- an Apple Silicon Mac (M1, M2, M3, M4, or later), not an Intel Mac;
- macOS 15 or newer;
- the approved tester ZIP and its matching SHA-256; and
- permission to share your Mac specifications and sanitized screenshots if
  something fails.

No Python installation, programming knowledge, printer, paid AI account, or
private model is needed. Start with the supplied public test model.

The tester app is an alpha. It is expected to be Developer ID unsigned and
not notarized unless the approved download notice explicitly says otherwise.
It is not a supported public macOS release.

## Download and verify — only after approval

1. Follow the approved link from the testing hub or discussion. Confirm that
   the artifact name and SHA-256 match the same approval post.
2. In Terminal, type `shasum -a 256 `, including the final space.
3. Drag the downloaded ZIP into Terminal and press Return.
4. Compare all 64 characters with the published SHA-256. Stop if even one
   character differs.
5. Extract the ZIP completely in Finder. Do not run the app from inside the
   ZIP and do not move the `.app` out by itself; keep the supplied guide,
   test model, notices, and evidence files together.

## First launch

1. Read `TESTER_ONLY_NOT_A_RELEASE.txt` and the English compliance notice in
   the extracted folder.
2. Control-click `ChromaMatter-macOS-Alpha.app` and choose **Open**.
3. Choose **Open** again if macOS asks for confirmation.
4. If macOS offers **Open Anyway**, use **System Settings > Privacy &
   Security** and confirm only this ChromaMatter copy.
5. Wait for the main window, then leave it open for 30 seconds. The app should
   remain responsive.

Do not disable Gatekeeper, run `xattr` commands, replace files inside the app,
or use `sudo`. If macOS says the app is damaged, cannot be verified, or cannot
be opened, stop and report the exact message. Do not search for a bypass.

## 10-minute basic test

Use `ChromaMatter-Public-Four-Color-Test.glb` from the extracted tester
folder. It is a small CC0 model containing four closed red, blue, white, and
black boxes.

1. Confirm that the main window remains responsive for 30 seconds.
2. Switch between Japanese and English. Confirm that the main controls remain
   readable.
3. Choose **Open OBJ / GLB** and open the supplied four-colour GLB.
4. Orbit, pan, and zoom. All four boxes should stay visible.
5. Select **Full Spectrum (Mixed)** and confirm that its preview appears.
6. Select **Flat 4 Colors** and confirm that the preview uses physical F1-F4
   only, without an F5+ mixed state.
7. Open **Manual Editing**, use **Fill** on one box, then test Undo and Redo.
8. Export a 3MF. The supplied model is already closed and should export
   successfully. A refusal is a failed test and must not leave a misleading
   partial file.
9. Save a project, quit the app normally, reopen it, and reload the project.
   Confirm that the colour mode, F1-F4 colours, and manual edit are retained.
10. Optional: open the 3MF **as a project** in Snapmaker Orca. Do not print it
    for this basic software test.

Record **Pass**, **Fail**, or **Not tested** for each step. If an operation
shows no progress for more than 60 seconds, note the wait time and stop that
test.

## Report a result

For a successful or partial result, setup question, or general observation,
use the
[macOS Alpha Testing discussion](https://github.com/Ponkichi0718/ChromaMatter/discussions/9).
For one reproducible defect, use the
[macOS alpha Issue form](https://github.com/Ponkichi0718/ChromaMatter/issues/new?template=macos_alpha_report.yml).

Copy this template into your report:

```text
Overall result: Pass / Partial / Fail
Test route: Gated prebuilt .app artifact
Approved artifact name:
Verified ZIP SHA-256:
Source commit (from SOURCE_COMMIT.txt):
Mac model and chip:
RAM:
macOS version:
First launch: Pass / Fail
Japanese UI: Pass / Fail / Not tested
English UI: Pass / Fail / Not tested
Public four-colour GLB and view controls: Pass / Fail / Not tested
Full Spectrum: Pass / Fail / Not tested
Flat Four F1-F4 only: Pass / Fail / Not tested
Manual Fill / Undo / Redo: Pass / Fail / Not tested
3MF export: Pass / Fail / Not tested
Project save / reload: Pass / Fail / Not tested
Snapmaker Orca version and result:
Notes:
```

For a launch failure, include the exact macOS dialog text and a screenshot if
possible. Do not post an app bundle, crash dump, or Terminal output before
checking it for personal paths and private filenames.

## Known alpha limits

- Apple Silicon and macOS 15+ are the only targets for this tester.
- The app may require Control-click > Open because it is expected to be
  unsigned and unnotarized.
- Pen pressure is not part of the first Mac target; use a mouse or trackpad.
- Some multipart, damaged, compressed, animated, or otherwise unsupported
  models may be rejected safely.
- Physical colour accuracy and printer safety are not proven by this software
  test.

## Privacy and redistribution

ChromaMatter processes OBJ, GLB, project, image, and 3MF data locally and does
not intentionally upload those files to a project-operated server.

Do not test with or attach a purchased, customer, confidential, private, or
third-party model. Remove names, home-folder paths, account details, serial
numbers, and private filenames from screenshots and reports.

Do not redistribute or mirror the tester ZIP or `.app`. Link to the exact
approved post instead. For a suspected security issue, use the private
[Report a vulnerability](https://github.com/Ponkichi0718/ChromaMatter/security/advisories/new)
route rather than a public post. ChromaMatter application source is
GPL-3.0-or-later, and third-party components retain their own terms.
