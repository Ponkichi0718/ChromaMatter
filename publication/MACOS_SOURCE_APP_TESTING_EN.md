# ChromaMatter Source-backed App Alpha — Install and Test

This guide is for the Finder-launchable **ChromaMatter Source Alpha.app** on
Apple Silicon Macs running macOS 15 or newer. The displayed product version is
still `0.8beta`.

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

The official candidate ZIP name is:

`ChromaMatter-0.8beta-macos-source-app-alpha1.zip`

After extraction, keep this folder together:

```text
ChromaMatter-0.8beta-macos-source-app-alpha1/
  ChromaMatter Source Alpha.app
  README_INSTALL_AND_TEST_EN.md
  ChromaMatter-Public-Four-Color-Test.glb
  ChromaMatter-Public-Four-Color-Test.glb.sha256
  SOURCE_COMMIT.txt
  SOURCE_BACKED_ALPHA_NOTICE.txt
```

Only use a ZIP linked by the project testing hub or release page together with
the fixed filename and its published SHA-256. A GitHub artifact with
`diagnostics` in its name is not the app.

## Download, verify, and extract

1. Download the fixed ZIP and its `.sha256` or `SHA256SUMS` file from the same
   approved location.
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

## 10-minute basic test

Use `ChromaMatter-Public-Four-Color-Test.glb` beside the app. It is a small CC0
model containing four closed red, blue, white, and black boxes.

1. Confirm that the main window remains responsive for 30 seconds.
2. Switch between Japanese and English and confirm that the main controls stay
   readable.
3. Choose **Open OBJ / GLB** and open the supplied GLB.
4. Orbit, pan, and zoom. All four boxes should remain visible.
5. Select **Full Spectrum (Mixed)** and confirm that its preview appears.
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

## Report a result

For a successful or partial result, setup question, or general observation,
use the [macOS Alpha Testing discussion](https://github.com/Ponkichi0718/ChromaMatter/discussions/9).
For one reproducible defect, use the [macOS alpha Issue form](https://github.com/Ponkichi0718/ChromaMatter/issues/new?template=macos_alpha_report.yml).

Include:

```text
Test route: Source-backed App Alpha
ZIP filename and verified SHA-256:
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
Final sanitized Terminal lines and notes:
```

## Known alpha limits and privacy

- Apple Silicon and macOS 15+ are the only supported test hosts.
- The first setup needs internet access and may download several hundred MB.
- Pen pressure is not part of this first Mac target; use a mouse or trackpad.
- Some multipart, damaged, compressed, animated, or otherwise unsupported
  models may be rejected safely.
- Physical colour accuracy and printer safety are not proven by this test.

ChromaMatter processes model and project data locally and does not
intentionally upload those files to a project-operated server. Never attach a
purchased, customer, confidential, private, or third-party model. Remove user
names, home paths, account details, serial numbers, and private filenames from
Terminal output and screenshots before posting.

Do not redistribute or mirror the tester ZIP or `.app`; link to the exact
approved project location. ChromaMatter application source is
GPL-3.0-or-later, and third-party dependencies retain their own terms.
