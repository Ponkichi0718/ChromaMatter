# Welcome: ChromaMatter macOS testing

Thank you for volunteering. This is the starting point for the separate
**Apple Silicon / macOS 15+** test path.

## Choose the correct test route

- **Recommended — Source-backed App Alpha 2:** the current prominent download,
  with a normal Finder `.app`, the quick four-box GLB, and the exact stable
  r32.2 15-file DemoData set.
- **Historical — Source-backed App Alpha 1:** the immutable first Finder
  package remains available as previous evidence.
- **Alternative — Source Tester Alpha:** the older ZIP starts the same source
  path directly with `START_MACOS_SOURCE_ALPHA.command`.
- **Pending — self-contained prebuilt app:** the beginner-friendly
  [prebuilt app installation and 10-minute test guide](MACOS_APP_TESTING_EN.md)
  is ready, but the app itself is **not available for download yet**. It will
  be linked only after the separate native-component, corresponding-source,
  relinking, packaging, and fresh-build approval gate passes.

Do not treat a GitHub Actions artifact with `diagnostics` in its name as an
application. It contains reports, not a runnable tester.

## Download Alpha 2

**[Download `ChromaMatter-0.8beta-macos-source-app-alpha2.zip`](https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-macos-source-app-alpha2/ChromaMatter-0.8beta-macos-source-app-alpha2.zip)**
from published GitHub prerelease
[#377168223](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-app-alpha2).
It was published at `2026-08-26T13:33:38Z` from the exact tag/source commit
below.

The frozen public identity is:

- source commit: `34e7ebdc3ec7dae6ad831b5119d574a656b105b0`;
- ZIP size: 217,943,261 bytes;
- ZIP SHA-256:
  `C112396513B0EA21CD867ED016E2D5282F830235E3EBF324E45E3B4FDB647989`;
- detached checksum asset: `SHA256SUMS-macos-source-app-alpha2.txt`, 115 bytes,
  SHA-256
  `8152D72AD978246D8B41BC1A64B2855897CBD43BAE7E36402192EF3883595129`.

Exact-tag run
[#32974429065](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32974429065)
passed. Both Release assets were then downloaded without authentication and
matched their exact sizes and SHA-256 hashes. The public ZIP was freshly
extracted: the 260-file outer package audit passed; DemoData contained exactly
15 files, 10 manifest payloads, and 236,274,418 payload bytes; and the 238-file
app audit passed with zero native-runtime files and the exact source commit.
Alpha 1 remains an
[immutable historical Release](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-macos-source-app-alpha1).

1. Download the exact Alpha 2 ZIP above and verify it against
   `SHA256SUMS-macos-source-app-alpha2.txt` on the Release page.
2. Read the [English installation and 10-minute test guide](MACOS_SOURCE_APP_TESTING_EN.md).
3. Extract the whole ZIP, Control-click `ChromaMatter Source Alpha.app`, and
   choose **Open**.
4. Let the launcher verify/install official Python 3.13.14 and the hash-locked
   dependencies. After Installer finishes, return to Terminal and press Return;
   reopen the launcher only if it still cannot find Python.
5. Run the supplied public four-colour GLB test and report the result.

The public fixture and `DemoData/` are beside the app. DemoData is the exact
stable r32.2 15-file set: its seven included 3MFs are Full Spectrum examples
only and do not prove Flat Four output. Before regenerating them, select the
physical black F slot and enable **Weak Black 5–25%**. Hi3D-derived part names
may not match visible regions, and multipart solidification remains unstable
beta behavior that can fail for another input. The click-by-click checks are
in the guide. The older command-based
[Source Tester Alpha](MACOS_ALPHA_TESTING_EN.md) remains available as a
fallback.

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

Alpha 2 source commit `34e7ebd...` was merged through
[PR #20](https://github.com/Ponkichi0718/ChromaMatter/pull/20). PR CI runs
[#32972636265](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32972636265)
and
[#32972636277](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32972636277),
main runs
[#32973212994](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32973212994)
and
[#32973213199](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32973213199),
and manual package run
[#32973571220](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32973571220)
passed. Exact-tag run #32974429065 and the anonymous public-download audit also
passed as recorded above.

## Share a result

Use [macOS Alpha Testing discussion #9](https://github.com/Ponkichi0718/ChromaMatter/discussions/9)
for a successful/partial result, setup question, or general observation. Copy
this template into a reply:

```text
Overall result: Pass / Partial
Test route: Source-backed App Alpha 2
ZIP: ChromaMatter-0.8beta-macos-source-app-alpha2.zip
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
