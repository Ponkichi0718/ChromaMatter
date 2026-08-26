# ChromaMatter macOS Source Tester Alpha

This is the short testing guide for **Apple Silicon Macs running macOS 15 or
newer**. The displayed ChromaMatter version remains `0.8beta`.

## What is available now

The **Source Tester Alpha is available now** from the fixed source tag
`v0.8beta-macos-source-alpha1`:

**[Download the Source Tester Alpha ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-alpha1/ChromaMatter-0.8beta-macos-source-alpha1.zip)**

The matching [tag/Release page](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-alpha1)
publishes the expected SHA-256 in `SHA256SUMS-macos-source-alpha1.txt`.

This is source code with a guided launcher. It is **not a prebuilt `.app` ZIP**
and not a supported public macOS Release. A prebuilt application is still on
hold because source/build/relink closure evidence remains unresolved for 253
packaged Mach-O files. A GitHub Actions artifact with `diagnostics` in its name
is a report, not the application.

The source launcher verifies the Mac and setup inputs, uses the official
Python 3.13.14 installer when needed, installs exact hash-locked dependencies
on the tester's own Mac, runs the self-test, and starts ChromaMatter from
source. This route does not remove or bypass the prebuilt-app distribution
hold.

## Before you start

You need:

- an Apple Silicon Mac (M1, M2, M3, M4, or later), not an Intel Mac;
- macOS 15 or newer;
- an internet connection for the first setup;
- time for a first download of several hundred MB, which may take several
  minutes; and
- permission to share your Mac specifications and sanitized Terminal output.

No programming knowledge, printer, paid AI account, or private model is
needed. Do not start with an important model.

## First setup

1. Download the source ZIP above. Compare its SHA-256 with the value on the
   tag/Release page. In Terminal, run `shasum -a 256 `, drag the ZIP into the
   Terminal window, and press Return. Stop if the values differ.
2. Extract the ZIP completely in Finder and open the extracted folder.
3. Control-click `START_MACOS_SOURCE_ALPHA.command`, choose **Open**, and
   confirm **Open** if macOS asks. Do not disable Gatekeeper globally.
4. If Python 3.13.14 is missing, the launcher downloads the official installer,
   verifies its SHA-256, and opens Apple's Installer. Complete that installer.
   It may request the Mac administrator password.
5. Return to the original Terminal window and press Return. If the launcher
   still cannot find Python, close it and open the `.command` file again.
6. Leave Terminal open. The launcher creates the test environment under
   `~/Library/Application Support/ChromaMatter Source Alpha/`, obtains only the
   hash-locked dependencies, runs the required self-test, and then opens the
   ChromaMatter window.

The first setup is slower because it downloads Python and dependencies. Later
launches reuse the verified local environment: keep the extracted source
folder and open the same `.command` file again.

Stop and report the Terminal message if the architecture, macOS version,
Python download, SHA-256 check, dependency lock, or self-test fails. Do not use
`sudo` in Terminal, edit the lock file, or replace a failed dependency with an
unlocked package.

## 10-minute basic test

The launcher creates a small CC0 test model here:

`~/Library/Application Support/ChromaMatter Source Alpha/TestData/ChromaMatter-Public-Four-Color-Test.glb`

It contains four closed red, blue, white, and black boxes. It contains no
character, brand, texture, external resource, or private metadata.

1. Confirm that the automatic self-test passes and the main window remains
   responsive for 30 seconds.
2. Switch between Japanese and English. Check that the main buttons remain
   readable.
3. Choose **Open OBJ / GLB** and open
   `ChromaMatter-Public-Four-Color-Test.glb` from the path above.
4. Orbit, pan, and zoom. All four coloured boxes should remain visible.
5. Select **Full Spectrum (Mixed)** and confirm that its preview appears.
6. Select **Flat 4 Colors** and confirm that the preview uses physical F1-F4,
   without an F5+ mixed state.
7. Open **Manual Editing**, use **Fill** on one box, then test Undo and Redo.
8. Export a 3MF. This supplied closed model should export successfully; a safe
   refusal is still a test failure and must not leave a misleading partial
   file.
9. Save a project, quit ChromaMatter, launch it again with the `.command`
   file, and reload the project. Check that the mode, F1-F4 colours, and manual
   edit remain unchanged.
10. Optional: open the 3MF **as a project** in Snapmaker Orca. Do not print for
    this basic software test.

Record **Pass**, **Fail**, or **Not tested** for each step. If one operation
shows no progress for more than 60 seconds, note the wait time and stop that
test.

## Known alpha limits

- This is source-based testing, not a normal drag-and-drop Mac application.
- The source launcher itself is not Developer ID signed or Apple-notarized, so
  Control-click > Open may be required.
- Intel Macs and macOS 14 or older are not supported by this alpha.
- Snapmaker Orca may need to be opened manually.
- Pen pressure is not part of the first Mac target; use a mouse or trackpad.
- Some multipart, damaged, compressed, animated, or otherwise unsupported
  models may be rejected safely.
- Physical colour accuracy and printer safety are not proven by this software
  test.

## Report a result

- For a successful or partly successful result, setup question, or general
  observation, use the
  [macOS Alpha Testing discussion](https://github.com/Ponkichi0718/ChromaMatter/discussions/9).
- For one reproducible crash, hang, display/input problem, import failure,
  wrong colour assignment, export failure, or documentation defect, use the
  [macOS alpha Issue form](https://github.com/Ponkichi0718/ChromaMatter/issues/new?template=macos_alpha_report.yml).

Include the source tag `v0.8beta-macos-source-alpha1`, Mac model/chip/RAM,
macOS version, launcher/self-test result, exact failing step, expected result,
actual result, and sanitized self-test JSON or final Terminal lines. The source
commit is optional when unknown. If the window never opens, the Terminal
output is the most useful evidence.

## Privacy and network access

The first setup connects to the official Python download and the Python
package index to obtain the verified Python 3.13.14 installer and hash-locked
dependencies. ChromaMatter then processes OBJ, GLB, project, image, and 3MF
data locally and does not intentionally upload those files to a project-
operated server.

Do not attach a private model. Never upload a purchased, customer,
confidential, or third-party model. Terminal output, projects, and screenshots
may contain user names, home-folder paths, private filenames, or account
details; remove them before posting. Use the repository's private
[Report a vulnerability](https://github.com/Ponkichi0718/ChromaMatter/security/advisories/new)
route for a suspected security issue.

Do not redistribute the Source Tester Alpha as a modified ZIP or mirror it on
another service. Link to the exact source tag instead. ChromaMatter source is
GPL-3.0-or-later, and third-party components retain their own terms.
