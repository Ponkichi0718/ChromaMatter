# Welcome: ChromaMatter macOS testing

Thank you for volunteering. This is the starting point for the separate
**Apple Silicon / macOS 15+** test path.

## Choose the correct test route

- **Recommended — Source-backed App Alpha:** a normal Finder `.app` that opens
  the reviewed, hash-locked setup in Terminal. Use the download below.
- **Alternative — Source Tester Alpha:** the older ZIP starts the same source
  path directly with `START_MACOS_SOURCE_ALPHA.command`.
- **Pending — self-contained prebuilt app:** the beginner-friendly
  [prebuilt app installation and 10-minute test guide](MACOS_APP_TESTING_EN.md)
  is ready, but the app itself is **not available for download yet**. It will
  be linked only after the separate native-component, corresponding-source,
  relinking, packaging, and fresh-build approval gate passes.

Do not treat a GitHub Actions artifact with `diagnostics` in its name as an
application. It contains reports, not a runnable tester.

## Start here

The Finder-launchable source-backed app is available now:

1. **[Download ChromaMatter Source Alpha.app for macOS](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-app-alpha1/ChromaMatter-0.8beta-macos-source-app-alpha1.zip)** and verify it against `SHA256SUMS-macos-source-app-alpha1.txt` on the [Release page](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-app-alpha1).
2. Read the [English installation and 10-minute test guide](MACOS_SOURCE_APP_TESTING_EN.md).
3. Extract the whole ZIP, Control-click `ChromaMatter Source Alpha.app`, and
   choose **Open**.
4. Let the launcher verify/install official Python 3.13.14 and the hash-locked
   dependencies. After Installer finishes, return to Terminal and press Return;
   reopen the launcher only if it still cannot find Python.
5. Run the generated public four-colour GLB test and report the result.

The public fixture is beside the app as
`ChromaMatter-Public-Four-Color-Test.glb`. The click-by-click checks are in the
guide. The older command-based [Source Tester Alpha](MACOS_ALPHA_TESTING_EN.md)
remains available as a fallback.

No programming knowledge, printer, paid AI account, or private model is
needed. The first setup downloads several hundred MB and may take several
minutes. Later launches reuse the local environment.

## Important: what this `.app` contains

The downloadable item is a Finder `.app`, but it is **source-backed**: it does
not bundle Python or third-party native libraries. It opens a visible Terminal
setup, verifies official Python 3.13.14 and installs exact hash-locked
dependencies on the tester's Mac. There is **no approved self-contained
prebuilt app**. That separate route remains on hold because 153 packaged native
files still have unresolved source/build/relink closure evidence. The future
self-contained route has its own
[English installation and test guide](MACOS_APP_TESTING_EN.md), but that guide
does not make the app downloadable or approved.

The Apple Silicon app has already passed source tests, native probes, packaged
self-test, and Japanese/English UI smoke in
[technical CI run #32947038458](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32947038458).
[Draft PR #12](https://github.com/Ponkichi0718/ChromaMatter/pull/12) remains the
separate source/review workspace. Neither is a tester download.

## Share a result

Use [macOS Alpha Testing discussion #9](https://github.com/Ponkichi0718/ChromaMatter/discussions/9)
for a successful/partial result, setup question, or general observation. Copy
this template into a reply:

```text
Overall result: Pass / Partial
Test route: Source-backed App Alpha
ZIP: ChromaMatter-0.8beta-macos-source-app-alpha1.zip
Source commit (SOURCE_COMMIT.txt):
Mac model and chip:
RAM:
macOS version:
Official Python setup: Pass / Already installed / Fail
Hash-locked dependency setup: Pass / Fail
Automatic self-test: Pass / Fail
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

For one reproducible crash, hang, setup failure, display/input problem, import
failure, wrong colour assignment, export problem, or documentation defect, use
the [macOS alpha Issue form](https://github.com/Ponkichi0718/ChromaMatter/issues/new?template=macos_alpha_report.yml).

## Privacy and boundaries

The first setup connects only to obtain the verified official Python installer
and hash-locked Python dependencies. Model and project processing then stays
local; ChromaMatter does not intentionally upload them to a project-operated
server.

Never attach a private, purchased, customer, confidential, or third-party
model. Remove user names, home paths, account details, serial numbers, and
private filenames from Terminal output and screenshots. Do not redistribute a
modified tester ZIP; link to the exact tag instead.

For a suspected security issue, use the private
[Report a vulnerability](https://github.com/Ponkichi0718/ChromaMatter/security/advisories/new)
route rather than a public post.

The source launcher is not Developer ID signed or Apple-notarized, the product
remains `0.8beta`, Intel Macs are unsupported, and this is not a supported
public macOS Release. The stable Windows build and Windows Flat Four Test 3
remain separate downloads.
