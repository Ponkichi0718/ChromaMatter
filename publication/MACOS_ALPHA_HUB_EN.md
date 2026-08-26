# Welcome: ChromaMatter macOS Source Tester Alpha

Thank you for volunteering. This is the starting point for the separate
**Apple Silicon / macOS 15+** test path.

## Start here

The source-based tester is available now:

1. **[Download the fixed Source Tester Alpha ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-alpha1/ChromaMatter-0.8beta-macos-source-alpha1.zip)** and verify it against `SHA256SUMS-macos-source-alpha1.txt` on the [tag/Release page](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-alpha1).
2. Read the [English setup and 10-minute test guide](MACOS_ALPHA_TESTING_EN.md).
3. Extract the ZIP, Control-click `START_MACOS_SOURCE_ALPHA.command`, and
   choose **Open**.
4. Let the launcher verify/install official Python 3.13.14 and the hash-locked
   dependencies. After Installer finishes, return to Terminal and press Return;
   reopen the launcher only if it still cannot find Python.
5. Run the generated public four-colour GLB test and report the result.

The generated fixture is `ChromaMatter-Public-Four-Color-Test.glb`. The full
path and click-by-click checks are in the guide.

No programming knowledge, printer, paid AI account, or private model is
needed. The first setup downloads several hundred MB and may take several
minutes. Later launches reuse the local environment.

## Important: this is not the prebuilt app

The downloadable item above is the tagged source code with a guided launcher.
There is **no approved prebuilt `.app` ZIP**. Prebuilt distribution remains on
hold because 253 packaged Mach-O files still have unresolved
source/build/relink closure evidence. A `diagnostics` artifact is a report,
not an application.

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
Test route: Source Tester Alpha
Source tag: v0.8beta-macos-source-alpha1
Source commit (optional if unknown):
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
