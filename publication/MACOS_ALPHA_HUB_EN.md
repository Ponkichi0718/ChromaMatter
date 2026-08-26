# Welcome: ChromaMatter macOS Alpha Testing

Thank you for volunteering. This board is the friendly starting point for the
separate ChromaMatter **Apple Silicon / macOS 15+ alpha**.

## Download status

**There is no approved tester download yet.** Start with the guide and testing
board below, and wait for the single approved build entry on this page. A
GitHub Actions artifact with `diagnostics` in its name is not the application.

When a build is approved, the owner will update this post with exactly one:

- approved workflow run URL and expiry date;
- application artifact name;
- source commit from `SOURCE_COMMIT.txt`;
- ZIP SHA-256.

Do not use an app sent through a comment, mirror, or file-sharing service.

## Start here

1. Read the [English volunteer test guide](https://github.com/Ponkichi0718/ChromaMatter/blob/main/publication/MACOS_ALPHA_TESTING_EN.md).
2. When the approved build appears above, verify its SHA-256.
3. Run the 10-minute checklist with the supplied public four-colour GLB.
4. Reply here with a successful or partly successful compatibility result.
5. For one reproducible defect, use the [macOS alpha Issue form](https://github.com/Ponkichi0718/ChromaMatter/issues/new?template=macos_alpha_report.yml).

No programming knowledge, printer, paid AI account, or private model is needed
for the required test. The supplied CC0 GLB contains only four coloured boxes.

## Current engineering status

The Apple Silicon app now builds and passes source tests, native dependency
probes, packaged native/rendering self-tests, and Japanese and English UI smoke
tests. The latest successful technical run is
[#32947038458](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32947038458)
at source commit `9404926a6aadbb918ade7855f4141e263c3aafba`. It uploaded
diagnostics only.

Distribution is not approved. All 317 packaged Mach-O paths are classified,
but 253 still have unresolved source/relink closure evidence.
[Draft PR #12](https://github.com/Ponkichi0718/ChromaMatter/pull/12) is the open
source and review workspace; it is not a tester download.

## Share a successful result

Copy this template into a reply:

```text
Overall result: Pass / Partial
Approved workflow run:
Artifact name:
Source commit:
ZIP SHA-256 verified: Yes / No
Mac model and chip:
RAM:
macOS version:
Japanese UI: Pass / Fail / Not tested
English UI: Pass / Fail / Not tested
Public GLB and view controls: Pass / Fail / Not tested
Full Spectrum: Pass / Fail / Not tested
Flat Four F1-F4 only: Pass / Fail / Not tested
Manual Fill / Undo / Redo: Pass / Fail / Not tested
3MF export: Pass / Fail / Not tested
Snapmaker Orca version and result:
Project save / reload: Pass / Fail / Not tested
Notes:
```

## What belongs in an Issue

Use the dedicated Issue form for a repeatable crash, hang, blank preview,
supported OBJ/GLB import failure, incorrect Flat Four F5+ assignment,
fail-closed/export problem, Orca-open problem, save/reload change, or a concrete
documentation error. Please keep one defect per Issue.

Use this Discussion for successful results, setup questions, general
observations, and comparing Apple Silicon configurations.

## Privacy and alpha boundaries

This alpha is ad-hoc signed, has no Apple Developer ID signature, is not
notarized, and is not a supported public macOS Release. Do not redistribute it.
Never upload a private, purchased, customer, confidential, or third-party
model. Remove user names, home paths, account details, serial numbers, and
private filenames from screenshots and logs. Do not post credentials or a
security vulnerability publicly; use the private
[Report a vulnerability](https://github.com/Ponkichi0718/ChromaMatter/security/advisories/new)
form instead.

The displayed application version remains `0.8beta`. The stable Windows build
and Windows Flat Four Test 3 remain separate downloads.
