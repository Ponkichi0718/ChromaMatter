# ChromaMatter cross-PC handoff

## Current publication checkpoint — 2026-09-10

The official website already publishes ChromaMatter `0.9` for Windows,
macOS and Linux. The current owner request explicitly authorizes updating
GitHub application downloads and source to match that existing publication.
This synchronization reuses the three official application archives with
identical bytes; it does not rebuild or alter the applications.

The Windows and Linux application-source baseline is
`5059163a1a6d05e823c44323558f344ad000b580`. macOS has its own corresponding-source
bundle at `c629f428868e26f11dbcd679983ee2cd74d9c1cd`: the application, inventory
and complete-source coverage agree, and the nested application-source ZIP
matches the official `ChromaMatter-0.9-source-c629f42-2e185dc1.zip` byte for byte,
including CRC, archive comment and all 597 files. The platform source bundles
and their existing native rebuild/relink limitations remain distinct.
See [the 0.9 release record](RELEASE_0.9.md) and
[the platform artifact manifest](publication/RELEASE_0.9.json) for the current
archive identities and publication progress.

This source checkpoint records the verified official archives and their build
inputs. GitHub distribution uses the same application bytes and the two exact
application-source ZIPs. The large per-platform complete-source bundles remain
available at their official URLs. Current assets are listed in the
[GitHub 0.9 release](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.9).

Focused source-only regression on the published 518-file snapshot passed
31 tests and 161 subtests, with no failures, errors or skips; all source-file
hashes remained unchanged. The existing Python environment emitted eight
PyMeshLab plugin-load warnings, retained in the private verification record.
These checks used tiny synthetic geometry, mocked CLI conversion and static
release-identity checks. No new application build, GUI test, real-model
conversion or slicer run was performed for this synchronization, and these
results do not clear historical native build or relink limitations.

The dated checkpoints below are preserved historical evidence. Their previous
publication holds and one-step permission limits describe those earlier
sessions; they are not a new permission requirement for the currently
authorized synchronization. Their test results and unresolved technical gates
continue to apply only to the exact artifacts and source revisions named there.

## Historical checkpoint — 2026-09-06

Updated: 2026-09-06
Current worktree branch: `codex/windows-flat4-region-quality`
Current Windows packaged source: `0.9` / `r33` at
`4547ebfdeacfe55394da5e1ba73254cbf49a36ee`, including export-validation
levels and a separate output-settings window. Windows is verified locally;
macOS/Linux source-backed packages are historical, not the requested final
native delivery. Latest executed exact native-build source is local commit `dfdb03d`.
Narrowly approved GitHub build-configuration changes are published. The latest
macOS run completed its full source suite with one later sub-page-width
failure; initial illustration width and prior Tk test stall now pass, but no
frozen Mac app yet. Linux run07 freshly built exact `dfdb03d`
and passed its full suite plus frozen WSLg automated checks. Final native
distribution checks remain pending. Only reviewed build-input source ZIPs are
deployed on the official site;
no new application binaries or download-page changes are published.
A previous frozen Windows 0.9 local
distribution at `d8e3df0` is verified separately below and remains unchanged.
Latest published release-development source: `codex/r32-2-demo-3mf`; the
frozen published release source is `v0.8beta-r32.2` /
`aba20685d2fd6987621b2e1e6624f46ea84912a3`
Previous release: `v0.8beta-r32.1` remains immutable previous evidence.
Current development display version: `0.9`; revision: `r33`; next Windows
numeric version: `0.9.0.0`
Latest published prerelease: `0.8beta` / `r32.2`; its Windows numeric version
remains `0.8.0.0`

## Historical objective — 2026-09-06

Latest execution checkpoint (2026-09-06): `dfdb03d6f2f12fded80caf89ae8598d173fdd243`
was locally committed under the owner's continued-local-commit permission.
Its exact 518-file source ZIP (5,481,681 bytes, SHA-256
`aed537d5bd9146a55f26cd321e8a8b25b7b88303f43355654e4e346ca81c11ac`)
passed independent Git-byte/mode, CRC, privacy and actual Actions extraction
checks on Windows and WSL ext4. Source-only Site32 deployed successfully at
12:46:34UTC; internal source commit `3b2ef43a846d5b62f3952f8e515e73f633ed2426`,
deployment `appgdep_6a9d609b43288191bfe897a81addca4b`. Public full ZIP download
matches. Site23tests/build pass; app/download-page/access changes were not made.

Mac run34034154274/job101489045211 used unchanged workflow7d03426 with
approved_package=false. All1765tests completed120.909s; one failure, zero
errors,11existing skips. The initial English illustration-page checks now
passed, then the later sub-page loop at line610 measured1115>1080. That old
failure message does not identify the selected page. Native/render self-test
passed; no frozen app built. Diagnostic artifact9989642763 (110189bytes,
SHA-256 `cd65e64117dba2e18a2fe09768f0e277130b7b37d2bf2a7ba84b6b511d592780`)
was actually downloaded, hash/CRC checked and all four entries inspected.

Next bounded correction uses the already working Linux stacked Tone-detail
layout on every backend and wraps the Tone title at140. No text truncation,
font reduction, changed callback/value or geometry-validation relaxation.
The focused test adds structural row assertions and failure-only section,
backend and child-geometry diagnostics while retaining1080width/300height.
External Windows candidate passes7original GUItests; all4pages fit at normal
JAEN fonts. Tone with1.25font stress fits918x250. A separate pre-existing
illustration enlarged-font overflow remains recorded, not fixed or hidden.
Canonical adopted Linux focused7tests/newassertions pass0.452s with the full
native-suite import context; independently adopted Windows7tests pass0.587s
after full GUI import, with production bytes unchanged before/after. Actual
Mac proof is still required.

Windows exact dfdb full suite ran1980tests468.081s with one Bash-path failure,
5existing skips. Newly installed WSL Bash treats Windows launcher paths as
Linux paths. The corrected syntax-only test pipes the complete LF UTF-8 script
bytes to bash -n; it does not execute the script, remove assertions or skip.
Text-mode stdin was rejected because Windows addsCRLF; binary stdin fixes it.
All7module tests pass via WSL, with independent actual-launcher/malformed-script
checks on both real WSL and Git Bash passing4of4. A second full run was
interrupted to await this corrected source; no new Windows app was built.
The fresh dfdb corresponding-source ZIP passes42921files/64components/8native
audit logs, but must not be reused as proof for a newer source snapshot.

Linux exact run07 passes1730tests98.918s (zero failures/errors,9existing skips),
518source blobs/modes before/after,319ELF audit and frozen self/native/render/
JAEN tests including separate actualWSLg probes. Final source/relink/package
gates are still pending. External rebuild/replacement investigation does not
mutate or approve the pristine candidate. No new application is published.

At measured usedPercent100, one previously authorized existing usage reset
was consumed successfully; usedPercent returned0 and one reset credit remains.
This conveys no additional commit, workflow or publication authority.

Owner authorization update (2026-09-06): necessary LOCAL feature-branch
commits may continue through native build completion, including the current
two-label wrapping correction and its regression/evidence records. This
supersedes the earlier one-commit limit for subsequent work. No application
source or history is to be pushed to GitHub. Unchanged Actions may consume
new independently reviewed source ZIPs under the existing public build-input
exception. Public app/download changes remain held until build, runtime,
source, privacy and distribution verification complete. Existing reset-credit
authorization is unrelated to these Git/publication boundaries.

Current execution checkpoint (2026-09-06,12:25UTC): the one additional
approved local-only commit completed as `e472c41f4142b0b0aa7857b081931c4f460186ab`.
Only the test helper plus these two evidence documents changed. Exact ZIP
5,477,802bytes SHA-256 `4a9f252e8ac57e6ea713290574b508570e670a74bed78356ae2fb72ad7458a40`
passed independent518blob/mode/privacy/CRC checks and actual unchanged Actions
extraction for both targets on Windows and WSL ext4. Site31 deployed only this
build-input source; internal source `4e8322f375142f50f0176b32e09b6ae886b7e21e`,
deployment `appgdep_6a9d590d29a081918647179ae8f72764`, succeeded12:14:19UTC.
Public URL /build-inputs/ChromaMatter-0.9-source-e472c41-4a9f252e.zip has been
anonymously fully downloaded and rehashed. Build and23tests passed. No public
app/download-page/access changes. Packaging used the unchanged official helper
with a scratch shell-command shim for GitHubDesktop GNU sh; no tool source edits.

Mac run34032541642/job101484655584 completed FAILURE at12:17:37UTC using
unchanged workflow7d03426 and approved_package=false. It was not cancelled:
all1765source tests ran in103.157s, one failure, zero errors,11existing skips.
The sole failure is the English illustration frame's requested width1096>1080
in test_manual_shading_ribbon.py line576. Keep that layout assertion unchanged.
Source/extraction/wheels/native/render passed, including ModernGL4.1 readback,
five PyMeshLab filters, and PyTetWild635nodes/2507tetrahedra. Previously stalled
JA/EN F-slot minimum-size test now passes in0.458s. This verifies the test-helper
correction on this run, not all production GUI behavior. No frozen .app exists.
Diagnostic artifact9989123661,108900bytes, SHA-256
`82985cd9c16a1bb704ddcb285b1509f6109cfb70e17bf4fa5dba69cbb74a066d`
was actually downloaded and hash/CRC verified; all four entries inspected.
SOURCE_ARCHIVE/RESULT identify the exact e472 source and unchanged workflow;
BUILD_LOG confirms the single failure; MACOS_ALPHA_SOURCE_SELF_TEST is ok=true.
Artifact expires2026-09-13T12:17:31Z; retained outside the repository.
Independent read-only review recommends applying existing140px label wrapping
to all platforms for the title and light-direction labels. Shared grid columns
and platform font metrics can enlarge every row; the editor uses clam, so do
not blame Aqua widget chrome specifically. Candidate must preserve1080width,
260/300height, full labels, control sizes, JA/EN and section/value persistence.
Linux fresh exact-source run06 completed12:12:04UTC:1730tests95.835s,
0failures/errors,9existing skips; all518Gitblobs/modes verified pre/post.
Fresh frozen build/319ELF audit/source+frozen native/render/self/required
XvfbJAEN and four actual WSLg native/self/JAEN probes pass. No normalGUI left
running. Build logSHA `41d1253d0a8cc67ee59c59e1b8a45f4e3e2a48e4bfabb64b977d59ac6c0ad778`;
WSLg proofSHA `18a3032af413109edfc9070a165cfab24034f9b26cf41b3860a757ed2bf32f91`.
Runtime exeSHA remains42091df2 as production code is unchanged; this is fresh
run06 evidence, not relabelled old-build approval. Source stale-after messages
remain documented; packaged stderr empty. Final native source/inventory/relink
and package/desktop-installation gates remain pending. External evidence lives
under exact-e472-independent-audit-01 and LINUX_RUN06_EXACT_BUILD_SUMMARY.md;
build tree linux09-committed-20260906-run06. No new binary is published.
Further execution records after e472c41 stay uncommitted; no second commit
or GitHub application/history push authorized in this checkpoint.

Uncommitted follow-up: adopted only the two illustration-label140px wraps
across backends, plus a two-line shared-grid explanation and a focused test
asserting both wraplengths. Existing text/fonts/controls/grid/export logic,
1080width and260/300height assertions are unchanged. Independent external
candidate audit passes the original7tests on Windows and Linux with0skips,
under full native-suite import context. JA/EN x four pages x font-resolution
x1.25label-font stress gives32metrics cases per platform/variant. All candidate
cases fit1080x300; Windows standardEN1015x242->974x251, stressedEN1100x242->962x261;
Linux metrics unchanged. Canonically adopted7Windows tests pass0.544s,0skips;
the same adopted source plus new assertions passes7Linux tests0.642s,0skips
under full native-suite import context, with production/test hashes unchanged.
Evidence: external macos-ribbon-candidate/AUDIT_TWO_LABEL_WRAP.md and raw JSON
logs; exact Mac run report MACOS_RUN34032541642_SUMMARY.md. Do not reuse this as
a Mac pass or mark earlier e472 artifacts as containing the wrap fix.
Next: obtain local-only checkpoint authorization, audit a new exact source
archive, and rerun unchanged Mac Actions. Native distribution/source/relink
and final packaged-runtime gates still follow; no completed app publication.
The owned temporary Site dev server was stopped after source-only deployment;
temporary Site credentials were removed from orchestration storage.

Latest owner-approved wait-helper checkpoint (2026-09-06): the owner said
yes to one additional LOCAL-ONLY commit for the Mac retry. Applied only
`test_filament_candidate_gui._wait_for`: predicate/deadline checks between
nonblocking single-event dispatches instead of unbounded queue draining.
The3second timeout, test bodies/assertions, platform selection, skips,
production UI and all export/native/distribution gates are unchanged.
The canonical full candidate-window module passes25Windows tests20.405s,
no failures/errors/skips; earlier external8Windows and8Linux cases verify
the bounded helper with real busy timer queues. Independent Linux whole-module
with in-memory helper-only patch also passes25tests11.913s,0failures/errors/skips;
its unchanged original source hash is recorded. ResultJSON SHA-256
`360854a90a1841d88f1732aa7f71f68611802c9275f299e91d521faa2ac4964b`.
Exact archive audit is required before dispatch. This is
not yet native Mac proof. Commit only this test file and the two evidence
documents; no application/history push to GitHub. Use a new exact raw-Git-blob
source archive, existing source-only Site authority and unchanged Actions
workflow with approved_package=false. Public app downloads remain untouched.

Latest continuation checkpoint (2026-09-06, 12:00 UTC): the owner approved
the requested single LOCAL-ONLY commit. Exactly five reviewed files were
committed as `56ae04d96553a843548d256014493af9a1bef679`; no application/history
push to GitHub. Subsequent evidence records remain uncommitted, not another
authorized source checkpoint. Exact new source ZIP is 5,473,398 bytes,
SHA-256 `38b1475acee89496abeb44228dab84d63a0104a8d402e97832479f4dec6498f3`.
It uses raw Git blobs without checkout/line-ending filters, a single
ChromaMatterSource/ prefix and the exact commit comment. All 518 file bytes
and modes, CRC/privacy and actual unchanged Actions extraction for both
targets passed independent review. An initial root-level git archive
(`464eb7...`) changed five files through line-ending rules and was rejected;
only its generated unpublished Site copy was removed, with the original
retained for audit. Do not use that rejected archive.

Only the new exact build-input ZIP was added to the Site. Internal Site
source `50a1b20734c4712406befdf46188b5cb8b0ba3dd`, saved version30,
deployment `appgdep_6a9d529f9abc8191bd7b6346b373f8f2` succeeded 11:46:52 UTC.
Build and23tests passed; anonymous chromamatter.app download rehash matches.
Existing 0.8 application downloads, page text, access, previous source ZIP and
DemoData remain untouched. No new binary/download-page publication.
At teardown the owned local preview session had already exited with a Windows
file-watcher EBUSY on an existing source ZIP; it was not running. Production
build/tests and deployed anonymous source-download verification above are
separate successful evidence; no public runtime failure is inferred from the
local watcher. Site checkout is clean at the recorded internal source commit.

Mac diagnostic run `34031258306` was dispatched at11:47 UTC using unchanged
workflow commit `7d03426bae28320841e099a512e893f2e99081e4`, targetmacos-arm64,
new exact source56ae04d and approved_package=false. Source/wheels/source
native-render passed. Repeated live60-second faulthandler stacks show main
thread tkinter.update -> test_filament_candidate_gui._wait_for line180 ->
F-slot minimum-size JA/EN test line419, with one idle executor worker. Root
requested cancellation after capturing repeated stacks. Job101481070039
ended11:55:53UTC; build/test7m28s. No frozen app or native-coverage result.
Do not claim Linux evidence or test-harness changes prove a Mac app fix.

Diagnostic artifact9988794603 is49,301bytes, SHA-256
`abf90a2c2d6267abb6246622d1e4f0ef8bc4e3f30a50e45780332146f632d90b`,
expiry2026-09-13T11:55:48Z. Public API and browser independently confirm
metadata; the new archive has not yet been inspected locally. Live stacks
are evidence, not a substitute for retained-archive verification. Polling
stopped after cancellation. Preserve existing old-run archive separately.

External `macos-wait-candidate/` contains a minimal test-helper-only patch
and regression logs, outside the source. Patch SHA-256
`b6c462ef990d878c7bcdd3b4827115dcb5f2bae144dec10e9dfa2bf92875c5d1`.
Eight Windows tests4.135s and eight Linux/Xvfb tests2.806s pass, retaining
the original JA/EN minimum-width assertions. A continuous Tk timer queue
reproduces the original0.03s helper deadline overrun at0.26-0.29s; single-event
nonblocking pumping returns false at0.0300s. This proves helper hardening,
not the cause of the Mac native stall. A single native event or later
update_idletasks may still block. No production change, assertion removal,
timeout relaxation or platform skip is justified. Candidate remains external,
not applied or committed. Next: obtain another local-only checkpoint approval,
adopt and regression-check the minimal helper, create a new exact source input
and rerun Mac with all native/packaged gates intact. No further GitHub app/history
push or download-page/binary publication. The owner's one authorized local
commit has already been consumed by56ae04d; these evidence docs remain dirty.

Linux run05 is a fresh exact56ae04d build, not a relabelled patched run04.
All518Gitblobs/modes verified before and after build; Python3.13.14/TclTk9.0.4
and the same22-wheel lock. Full unchanged Linux suite:1730 tests,94.177s,
zero failures/errors and9existing skips. Native/source/frozen render,
self-test, required Xvfb JA/EN and319ELF audit pass. Separate actual WSLg
native/self/JA/EN probes also pass; no normal GUI left running. Executable
SHA-256 `42091df2215b79ddfa4029272e51eeeb23ba0fa898816c1d90145fd46ab5c29f`
matches run04 but this is independent new-source evidence. Raw build log
SHA-256 `987c3272604a1eec5907976ca8045673ecd905c8ccb22d186345f5e2b25db56d`;
WSLg proofSHA-256 `9449cb208f4e1c6d9836db59f89b034dc56e44cb9a054af0b59fc6352e88351b`.
Two stale-after Tcl messages during source Help Center tests are retained;
tests pass, separate packaged UI stderr is empty. Formal native inventory,
complete corresponding source/relink and final package approval remain
pending. No DEB/distributable or ordinary Ubuntu desktop compatibility claim.

Authoritative latest checkpoint (2026-09-06, supersedes the older access
findings below): the owner explicitly wants WSL plus Ubuntu installed on THIS
Windows PC and real Linux validation; the earlier interpretation as historical
WSL test evidence was incorrect. Distinguish the actual checks below from a
complete distributable or physical-printer test. Both macOS
and Linux must be built; official download publication must wait until builds
and validation finish. No DemoData is to be bundled.

- WSL installation now succeeded after the owner requested another UAC and
  approved the official signed wsl.exe installer. WSL 2.7.13.0, WSLg 1.0.73.2,
  Ubuntu-22.04 (22.04.5 LTS x86_64), DISPLAY=:0 and WAYLAND_DISPLAY=wayland-0
  are verified on this PC. No reboot or security-policy change was performed.
  Earlier PowerShell installer attempts were cancelled or did not execute;
  they are superseded by this verified direct wsl.exe installation. Native
  dependencies and a dedicated unprivileged Linux build environment are
  installed; the installation alone is not application-test evidence. Never approve
  UAC or restart automatically.
- The owner approved one narrow Actions workflow configuration commit and
  explicitly approved two subsequent configuration-only corrections.
  PR #21 adds ONLY `.github/workflows/native-source-zip.yml` and was squash
  merged at `91dd1ef45f44f204d69db02b27e175f1545a6251`. Application commits,
  models and binaries were NOT pushed. Exact uploaded blob parity passed.
  GitHub rejected job-level `runner.temp` expressions in the first version
  before any native job ran (34026558935; branch 34026191375). Approved PR #22
  fixes only that file via GITHUB_ENV and is merged at
  `2ff5556e72537df623d7ab0cc3573d62695620b9` (13 additions, 5 deletions).
  Exact uploaded blob parity and actionlint 1.7.12 plus the original-error
  negative regression passed. Workflow SHA-256 is
  `f432ea895cef1361b21382a0710be5d4087ca3553ed96b1a960be303566ec802`.
  Manual macos-arm64 run 34027237098 started at 10:22:28 UTC with exact source
  identity below and approved_package=false. It stopped at source download:
  the same Python urllib request locally receives Cloudflare 403/1010 while
  standard curl succeeds. Python setup/path initialization passed, but no
  application build ran in that failed attempt. The owner then explicitly
  approved a standard-curl downloader correction. PR #23 changes only the
  download code in the same workflow (+76/-21), merged at
  `7d03426bae28320841e099a512e893f2e99081e4`. Remote bytes match reviewed
  SHA-256 `c90de931d2a8f55cf6f5e4c09a5f17f05a22b717afb12e97a569854c8d3f0a84`.
  Actionlint, both script syntaxes, exact-source extraction, negative archive
  tests and nine online/offline downloader cases passed. TLS verification,
  exact SHA-256 and public-host/archive checks are retained; no cookies or
  browser impersonation is used. New run `34028493767` began at 10:49:41 UTC
  against the same source, target macos-arm64, approved_package=false. Actual
  Mac source download/extraction and hash-locked wheels passed, followed by
  native dependency and source native/render self-tests. The full source suite
  stopped producing progress after a completed filament-candidate test at
  10:50:55 UTC. GitHub logs are virtualized, so the visible end alone was not
  trusted: after fresh navigation and debounced searches, the next test,
  suite-completion message and PyInstaller output were all absent. The owned
  run was cancelled rather than leaving the 180-minute timeout running;
  job 101473644738 ended 11:14:29 UTC, cancelled after 24m06s in that step.
  No root cause or finished .app is claimed. Diagnostic artifact 9988169515
  (42,018 bytes, SHA-256
  `f33dbe174dd07b2ae8997cde548c1a548715c6d8fb7c2fd32c9e84360a101252`)
  was downloaded through the signed-in UI and hash/CRC-verified. Its four
  regular leaf files were inspected without extraction. Actual retained log:
  419 tests started, 413 explicitly passed, five skipped, one incomplete:
  `FilamentCandidateWindowTests.test_f_slot_actions_fit_in_japanese_and_english_at_minimum_size`.
  This partial final line was absent from the live UI; do not equate the last
  completed direct-flat test with the waiting test. No FAIL/ERROR/traceback or
  suite completion exists. Native source proof includes five PyMeshLab filters,
  real PyTetWild tetrahedralization and ModernGL 4.1 exact framebuffer readback.
  Frozen self/native and packaged JA/EN gates were not reached. Source coverage
  and package steps were skipped; no app was uploaded. Do not rerun the failed old workflow commit
  or enable package upload for source 4547: its final packaging hook is absent.
- Build input is exact source `4547ebfdeacfe55394da5e1ba73254cbf49a36ee`:
  LF source ZIP 5,514,197 bytes, SHA-256
  `ee04c385a39ea37f58e1b4eda41d8742c71db6b32096e026de7941bd8f2daaea`.
  All 518 blobs and executable modes match; CRC, both target extractions,
  ten unsafe-ZIP fixtures and diagnostics filtering passed independent audit.
  The first archive inherited CRLF conversion and is rejected. Do not use it.
- Current official Site source was recovered through Sites (previous saved
  version 28 at `893f3a1b4b93ae764100da71c4082525f31a6fd4`). An isolated
  current checkout, not the stale retained checkout, passed build and 23 tests.
  Internal Site source head is `5c4ba8300a67015433c18229163fd968d3c8342d`:
  its net change is ONLY the reviewed build-input ZIP. The mistaken WSL claim
  was removed before deployment. Owner explicitly allowed this source-only
  exception before native builds. Saved version 29 and deployment
  `appgdep_6a9d3d12c1b08191b1c89f30bc071d91` succeeded at 10:14:56 UTC.
  Anonymous HTTPS download at
  `https://chromamatter.app/build-inputs/ChromaMatter-0.9-source-4547ebf-ee04c385.zip`
  returned exact bytes/SHA-256 above. Public application downloads remain
  0.8; page text is unchanged. No GitHub application-source push, cookie
  transfer or binary publication occurred. All app/download-page publication
  remains held until native builds and validation finish.
- Mac native build/source-coverage and Linux font/runtime/source-closure gates
  remain pending. Scratch reports contain exact remediation maps. Preserve
  the reviewed newer historical Mac plan, but re-audit against fresh binaries.
  Never mark technical diagnostic output as a distributable.
- Linux setup passes the exact 22-wheel lock, Python 3.13.14, Tcl and actual
  Tk 9.0.4, source self-test, PyTetWild, PyMeshLab filters and ModernGL draw/read.
  Pristine-source run01 failed an unchanged X11 light-button height test;
  run02/run03 exposed full-suite-import-only width problems. Preserved run04
  changes only paint_gui.py and smooth_paint_hotfix.py layout on X11. All tests
  are byte-identical; 516/518 original source files are unchanged. Patch SHA
  `3523387073439d80d0a4472fc68164d23c2a7ff7ecd197d0f8e4315a3810b506`.
  It is explicitly source4547 plus a local patch, not an exact4547 binary.
  Seven focused tests and 16 language/font/subpage metric combinations pass.
  Full Linux suite: 1,730 tests in 95.169s, zero failures/errors, unchanged nine
  platform skips. Frozen build, ELF audit and required packaged self/native/
  JA/EN checks pass under Xvfb. Separate actual WSLg packaged native/render,
  self-test and JA/EN smokes also pass without font-path/security changes.
  Executable SHA-256:
  `42091df2215b79ddfa4029272e51eeeb23ba0fa898816c1d90145fd46ab5c29f`.
  Computer Use found the owned WSLg window but captured the background even
  after activation; no interactive pass is claimed. Linux read-only inspection
  confirms that the owned window is mapped and not minimized. Four frozen CLI
  exports passed: closed Full Spectrum32/high and FlatFour/high, open full/low
  and flat/ignore. Independent ZIP CRC/XML/report checks retain truthful
  unclosed/unchecked warnings in low/ignore. No physical printer claim.
  Native source closure and final DEB packaging remain pending. The two reviewed
  UI files have now been adopted into canonical source with hashes matching
  run04 exactly; seven unchanged Windows focused compatibility tests passed
  in 1.333s with no skips. No commit.

Canonical changes are HANDOFF.md, CURRENT_STATE.json, BUILD_MACOS_ARM64.sh and
the two X11 UI files above. All build-config, Site and WSL-preparation files
are in isolated task scratch checkouts. The reviewed diagnostic-only Mac
runner patch is now adopted locally: flushed UTC/monotonic START/STOP test
messages and repeating 60-second all-thread faulthandler dumps, cancelled in
finally. Module selection, test outcomes and all distribution gates are
unchanged. Six diagnostic harness checks and Bash syntax/inline Python checks
pass. Exact build-script SHA-256:
`d116b0a89d4324857c9075be763021eb995423c2f7a667e0c58774af12b9c2a1`.
It has not been uploaded or executed on Mac; it is not a proven hang fix.
An external native-DEB wrapper is also prepared with 19/19 tests on Ubuntu
22.04 and independent review. It requires the existing exact source/native
closure and canonical approved archive; it creates an unapproved candidate,
not automatic release approval. No DEB was built, installed or published.
Four additional frozen WSLg native/self/JA/EN loader probes passed with raw
LD_DEBUG logs and process maps retained outside source. The observed GL path
loads WSL and Windows-vendor graphics libraries not owned by Debian packages;
this is real WSLg evidence, not ordinary Ubuntu driver coverage. No final
LINUX_APP_INVENTORY.json exists yet: the observational file manifest is not
release approval and must not be substituted for canonical native inventory.
The owner explicitly approved one LOCAL-ONLY source checkpoint commit covering
the Linux fix, Mac diagnostics and these records in the latest follow-up.
This record is being included in that checkpoint. GitHub application/history
push remains prohibited. The next Mac diagnostic build will use a new exact
source ZIP from this checkpoint, not the older 4547 input or its build proof.
Never push the
ahead-of-origin application history to GitHub under this workflow-only scope.

Historical access investigation (superseded by the checkpoint above):

Latest follow-up (2026-09-06): the owner requires genuinely ready-to-run
macOS/Linux packages, not source-backed first-run installers, and authorizes
updating the official `chromamatter.app` downloads after the distributables
are complete. DemoData stays separate. Latest clarification allows GitHub
Actions when necessary but explicitly prohibits new commits. The owner says
the old account flag is removed. This supersedes the preceding "leave Git
aside" wording and previous local-only publication scope, not any native
distribution gate. Do not commit or push a workflow change without a new
explicit narrow exception.

Read-only public GitHub inspection succeeded. Main is at `34e7ebd`; 19
branch heads predate local 0.9. Both registered workflows (native macOS and
source-backed macOS Alpha 2) checkout `github.sha` and accept only their
upload boolean, not an external source ZIP/hash. There is no registered
Linux workflow. Unchanged re-runs would build old source, not current 0.9;
none were dispatched. The GitHub connector itself still needs reauthentication.
Next build decision: obtain a narrow exception for a one-time archive-input
workflow update, or a separate native host. Do not represent an old Actions
run as evidence for new software or invent a no-commit source input.

Read-only investigation found no usable Mac/Linux build host here: WSL is
not installed, Docker/Podman are unavailable, and no remote project is
connected. Existing native build scripts are genuine self-contained routes,
but require target-native execution and unresolved distribution evidence.
A later retained macOS audit reduces historical unresolved paths from 253 to
153 on the same 317-path old inventory; it is not current-build approval.
Recover/review that work rather than repeating the already resolved groups.
Linux still has 16 blocked closure records, plus system-font and exact
Tcl/Tk-baseline issues to resolve for no-setup delivery.

The official download page currently shows 0.8 beta packages and separate
DemoData. The owner logged into the source vault successfully, but that UI
only exposes private source transfer and feedback; it does not expose public
release management. No site-deployment connector or page-defined release tool
is available. The retained local Site checkout is demonstrably older than
the public page and must not be deployed over it. Next action is to obtain
the current Site project/deployment surface; preserve existing downloads
until verified replacement assets are available. No application/package
bytes or public pages changed in this follow-up, and nothing was uploaded,
committed or pushed. Only this handoff and CURRENT_STATE record the access
findings; previous verified local artifacts remain unchanged.

The completed earlier cross-platform packaging scope is retained below:

Prepare the latest 0.9 source for Windows, Apple Silicon macOS and Linux
x86_64 users, including the export validation selector and separate Output
Settings window below. The owner authorized a local feature-branch commit
for this task; no GitHub push, site upload or publication is authorized.
DemoData is now a separate download and must not be bundled in these new
application packages. Preserve historical demos, manifests and releases.

Windows uses a fresh exact-commit executable build and corresponding-source
bundle. macOS uses the restored source-backed `.app` launcher (dependencies
are installed on the user's Mac, not redistributed in the archive); Linux
uses the source-backed alpha installer. Source-archive validation on Windows
does not prove native macOS/Linux startup, rendering or export. Keep target
runtime verification explicitly pending and all frozen-native compliance
gates intact. Local packaging and owner delivery are complete as recorded
below; do not reuse old Windows ZIP or native CI evidence for these bytes.

## Latest local cross-platform package checkpoint — 2026-09-06

All three application packages are frozen at source commit
`4547ebfdeacfe55394da5e1ba73254cbf49a36ee`. This is a post-artifact record;
any later documentation-only commit containing these results is not the
packaged source identity. The owner approved local feature-branch commits,
not GitHub pushes, site/source-vault uploads, or public release changes.

Current delivery excludes DemoData payloads. Historical rights/hash manifests
and source-only demo documentation remain in the source tree; no demo model,
reference image, generated 3MF, private model, or test output is bundled.
English/Japanese start guides and SHA256SUMS accompany the three archives.
All local delivery copies match their verified originals by SHA-256.

| Local application artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `ChromaMatter-0.9-win64.zip` | 1468101407 | `c41f2fa588695987d1c7b9af32e5219bfa937fcb946fb5e9e2a2457cb5da09a0` |
| `ChromaMatter-0.9-macos-source-app.zip` | 5833731 | `1f21b7cdadc9603083b7b9b3a4062f77ffa82e524946a22ed656110c96d24db2` |
| `ChromaMatter-0.9-Linux-Source-Alpha1.tar.xz` | 3994312 | `be857308b7aaaaad16d3c2f56786834d534d4b5592a5bf8b7d675e97da81de5d` |

Completed exact-source verification:

- Fresh clean-checkout full regression: 1980 total, 1973 passed, seven
  optional-platform skips, zero failures/errors, 429.793 seconds. Earlier
  preflight had one test-fixture newline failure and is superseded, not final
  artifact evidence. The corrected fixture was committed before this build.
- Windows: fresh hash-locked Python 3.13.14 / PyInstaller build, 1455-file
  runtime and 256-native-file inventory passed. Executable SHA-256:
  `c14a014ac02694d197cd9ffb26c0cda11d554756b0af38e1d07ce8dc2698bff4`.
  Canonical staging and independent final extraction checked all 1512
  manifest files, full file coverage, safe entries/CRC, no DemoData payload,
  and source-bundle parity. Extracted self-test plus JA/EN UI smoke passed
  using fresh isolated profiles and system-only PATH.
- Windows interactive packaged QA confirmed the new footer, separate Output
  Settings window, High default, Close action and application exit. Five
  synthetic exact-executable exports passed: closed/high and open/low in Full
  Spectrum and Flat Four, plus open/ignore Flat Four. Relaxed exports retain
  truthful defect/unchecked metadata. This is not a new real-model slicing
  or printing result; complex multipart repair is still input-dependent.
- Complete corresponding Windows source is bundled: 1365991072 bytes,
  SHA-256 `3f8cfca4459db675b108fa64bb93d8b618bfad4efaea5a9e90bc62f733916cbf`;
  release-approved, no known gaps, 42921 source files, 518 exact project Git
  blobs, 64 components, eight audit logs. Copy-local Qt/GEOS replacement
  audit passed with hash-different ABI-identical marker DLLs and actual
  loader/function probes; no arbitrary ABI/rebuild compatibility is claimed.
- macOS: source-backed unsigned/unnotarized `.app`, Apple Silicon / macOS
  15+, 260 files, exact source hashes, LF launchers and Unix 0755 executable
  modes verified. English installation/test guide included. It downloads
  pinned dependencies during setup; no native runtime/wheels are bundled.
- Linux: source-backed Ubuntu 22.04+ desktop x86_64 installer archive, 519
  files / 609 members, exact source hashes and executable modes verified.
  Host-side cross-host source-candidate audits do not substitute for native
  bash/startup/render/export tests. Installer does not run sudo automatically.

**Remaining gates:** Native setup, rendering and 3MF export of these exact
macOS/Linux packages are untested. Keep them labelled source-backed test
builds, not verified standalone native applications. The existing 253 macOS
Mach-O and 16 Linux frozen-native source/build/relink gaps remain open and
are not bypassed by this source-backed path. Windows engineering distribution
gates passed for its exact archive; external publication remains unauthorized.

Packaging-only issue: the canonical Windows stager completed successfully,
but its external orchestration wrapper misread unset LASTEXITCODE after a
PowerShell-script call. Correcting that wrapper did not restage or change
artifact bytes. Independent extracted-runtime verification passed afterward;
the original wrapper error remains in the local log for traceability.

Changed implementation/documentation groups are the shared export policy/UI
and regressions, restored macOS source launcher/stager/lock/English guide,
Linux cross-host source-candidate stager/tests, current no-DemoData packaging
instructions/tests, newline attributes and this handoff/state record.
Build checkouts, runtimes, dependency caches, source bundles, logs, manifests,
QA profiles and synthetic test outputs remain local-only outside the repo.
No old releases, source data, owner application windows or user edits were
overwritten/deleted. No security bypass, version change, push or upload.
Post-artifact record checks passed: 41 focused release-identity/output-window/
validation-GUI tests in 13.404 seconds, JSON parse and git diff --check. An
initial new summary-status identifier was unsupported by the existing schema
test and was reverted to the accurate established Windows-verified value;
the macOS/Linux native-pending fields remain explicit. No application or test
bytes changed after packaging. Only HANDOFF.md and CURRENT_STATE.json changed
for this post-artifact record; the final diff/status inventory was reviewed.

Next task: owner/volunteer test the exact Mac/Linux artifacts on their stated
OS/architecture, retain setup and export logs, and address actual failures.
Any application/package byte change requires fresh exact-source gates;
do not reuse this record to approve a different archive. The following
preparation and feature sections retain historical evidence only.

Packaging preparation completed before the source checkpoint: restored the
source-backed macOS launcher, runtime-only hash lock, deterministic .app ZIP
stager and English guide; added explicit cross-host Linux source-candidate
assembly with exact Git-derived executable modes and per-file hashes; updated
current distribution guides for the separate output window, validation levels
and separate DemoData download. Focused suites passed: macOS 44 tests (one
optional shell skip), Linux 30 tests (one optional WSL skip), documentation 21
tests (one optional WSL skip). These are host-side source/tooling tests only.
Fresh committed-source regression and actual archive verification follow;
native macOS/Linux runtime results are still pending.

Cross-platform package preflight exposed a test-only LF/CRLF assumption in
the macOS synthetic Git fixture. The stager correctly used committed Git
bytes; the test now compares those bytes, isolates its local Git newline
setting, and `.command` sources explicitly retain LF. Seventeen targeted
tests passed with one optional shell skip, plus all ten source-app tests
passed with the actual CRLF checkout used as fixture input. Rebuild packages
from this corrected checkpoint and rerun the complete committed-source suite;
the previous preflight archive hashes are not final evidence.

The owner confirmed a previously blocked export now succeeds. The current
follow-up moves Output Settings into a reusable separate window, opened beside
Export 3MF on the main footer, with an independent Solidify action beside it.
The old Output Settings ribbon tab is removed. Existing input variables,
pending edits, language settings and geometry/colour validation are preserved.
The initial geometry-check level remains high. See the final checkpoint and
CURRENT_STATE.output_settings_window_development for the current source state.

The preceding follow-up added owner-selected geometry-check levels:
`high` (initial default), `medium`, `low`, and `ignore` (non-recommended).
The owner expressly requested this change to the earlier strict-only export
contract. The software shows a selector without explanatory paragraphs;
non-high exports require a short warning/confirmation each time. Only geometry
acceptance is relaxed; malformed indices, archive structure, colours/materials
and pending palette checks still fail closed. Imported metadata cannot select
a lower policy. Repair algorithms remain strict. See the latest checkpoint at
the end and CURRENT_STATE.export_validation_development for current evidence.

The preceding 0.9 baseline objective is retained here for context:

Prepare ChromaMatter 0.9 with **improved 3MF output accuracy and success** as
the principal version-up feature. Ordinary single-logical GLB input now gets a
conservative pre-export repair path: exact duplicate seams are welded, and only
strictly planar tiny openings no wider than 2.0 mm may be locally capped. The
result must still pass the existing fail-closed watertight, non-manifold,
winding, positive-volume, degeneracy, and self-intersection checks. Complex
multipart repair remains input-dependent and is not claimed as solved.

The failed-repair 3D inspection prompt is removed, and the radial experiment is
removed from the application UI and forced off while its dormant research
source remains available for compatibility. The previous 0.9 Windows binary
and ZIP are now verified locally; they predate the new validation selector.
No 0.9 tag or public release has been created by these local tasks.

Maintain the published r32.2 prerelease and its manifest-locked derived 3MF
demo outputs without changing any tagged asset. TetGen remains under its AGPL
route; the ChromaMatter application remains `GPL-3.0-or-later`; each
third-party license remains preserved. The published Windows ZIP stays paired
with its complete corresponding-source bundle, SBOM, component map, notices,
relinking instructions, workflow video, and detached checksums.

Published `v0.8beta-r32` at commit
`86e34b2a9468f81768ee134a680a792b1a83df05` is immutable previous evidence.
Do not replace its tag, assets, or `SHA256SUMS-r32.txt`. The r32.1 update uses
new `ChromaMatter-0.8beta-r32.1-*` asset names and `SHA256SUMS-r32.1.txt`.

The r32.1 scope changes the preview label to AI Model Color and adds the
rights-cleared Hi3D multipart GLB/reference demo to the Windows package with
short instructions, part-name warnings, and mandatory Weak Black guidance.
The r32 modelling and 3MF contracts remain unchanged.

## Latest published immutable state (supersedes older release checkpoints below)

- Release: <https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2>
- Direct Windows ZIP: <https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2/ChromaMatter-0.8beta-r32.2-win64.zip>
- Full regression: 1,298 total / 1,296 PASS / 2 optional SKIP / 0 FAIL.
- Packaged self-test, independent fresh-extract self-test, and isolated
  Japanese/English UI smoke: PASS.
- Complete corresponding source: `release-approved`, `known_gaps=[]`.
- All six public assets were downloaded without authentication and matched the
  frozen sizes and SHA-256 records.
- The release tag and all attached asset bytes must remain unchanged. Later
  documentation-only commits may update the default branch and Release body.
- **Published 0.8beta limitation:** multipart solidification is not universally reliable.
  The bundled `DemoData` succeeds, but other multipart OBJ/GLB files can fail
  solidification or 3MF export. This incomplete compatibility is one reason the
  published r32.2 binary was labelled `0.8beta`.

Sections below preserve engineering history and pre-publication gates. Any
older statement saying r32.1 or r32.2 is pending or ineligible is historical and is
superseded by this section and `CURRENT_STATE.json`.

## Previous r32 engineering handoff

This continuation resumed from GitHub on the home PC. The controlled build was
bound to pushed source commit
`5feb198eef3432cdec19a0367d53e1b52bd4a363`; local `HEAD`, the upstream feature
branch, and Draft PR #1 pointed to it before adopting the resulting wheel. The
owner authorized updating the feature branch and Draft PR with the current
source checkpoint. `main`, tags, and public Releases remain untouched.

## Completed in this session

- Added an always-visible Japanese/English Licenses window to the desktop UI.
- Added AGPL/LGPL/MPL texts, bilingual notices, source-offer templates,
  relinking instructions, build instructions, and a component-map schema.
- Added a SHA-256-locked Windows dependency file for exact Python 3.13.14.
- Made bootstrap use `--require-hashes --only-binary=:all:`.
- Added deterministic CycloneDX 1.5 SBOM and binary component-map generation;
  unknown native files and reparse points fail closed.
- Updated the PyInstaller spec to preserve wheel-supplied license files and
  remove only link-time `.lib` archives, retaining DLLs and plugins.
- Added fail-closed software staging for the final source URL, SBOM, component
  map, notices, and source-offer generation.
- Added deterministic corresponding-source staging from exact commits,
  recursive submodules, and validated archives.
- Restored the public filament-library updater required by its checked-in test.
- Added the detailed binary-release continuation checklist at
  `publication/BINARY_RELEASE_HANDOFF_JA.md`.
- Added repository-wide `AGENTS.md` and this cross-PC handoff.
- Installed exact Python 3.13.14 in the current user scope and created the
  ignored `.venv` from all 25 hash-locked Windows wheels.
- Added a fail-closed bootstrap input for a controlled-rebuild PyTetWild wheel
  or wheelhouse. The wheel must match the application lock, version, ABI tag,
  platform tag, and SHA-256 before it can be installed without index fallback.
- Added evidence-bound corresponding-source approval. The checked-in manifest
  remains candidate-only; only a staged output with verified PyTetWild rebuild
  evidence and a complete downloaded MeshLab SHA-256 lock can become
  `release-approved`.
- Excluded all pip `direct_url.json` installation-origin metadata from the
  packaged application so a local wheel path cannot leak into the binary.
- Aligned the JA/EN build documents with Python 3.13.14 and the hashed
  `requirements-build.lock` used by the scripts.
- Acquired and verified the prospective native-builder inputs under
  `C:\ChromaMatterToolchain`: CPython 3.12.10, PortableGit 2.55.0.windows.5,
  the exact Visual Studio Build Tools 17.14.39 offline layout, Eigen 3.4.0,
  MPIR 3.0.0, the fixed Git source commits, and the offline Python wheelhouse.
- Added a Windows PyTetWild controlled-rebuild recipe, a 39-package hashed
  build/audit lock, and a separately hashed source patch that makes the
  declared optional PyVista accessor truly optional.
- The recipe verifies all 714 Visual Studio layout files with a deterministic
  tree hash and Microsoft's layout verifier, binds the exact MSVC/SDK paths,
  rejects noncanonical wheel/RECORD paths, audits abi3 and native dependency
  closure, tests the normal delvewheel-assisted package import, and binds eight
  command logs by SHA-256 into the build attestation.
- The final corresponding-source approval gate now validates the complete
  attestation/network/source/environment/input/output schema, the distinct raw
  and repaired wheels, and all eight physical logs. It also byte-compares the
  supplied build recipe, build-requirements lock, source patch, and application
  lock with their canonical files at the exact project commit; self-consistent
  working-tree substitutions cannot approve a release.
- Hardened corresponding-source ZIP/TAR validation and extraction against NUL,
  noncanonical and Windows-dangerous paths, encrypted or special entries,
  Unicode/case collisions, and file/ancestor conflicts.
- Completed the 21-entry MeshLab Windows external-archive lock. The historical
  unsigned TinyGLTF `premake5.exe` is preserved as corresponding source only,
  marked `preserve-do-not-execute`, and remains subject to release review.
- Seeded a reusable local corresponding-source cache with all 21 MeshLab
  archives as verified hard links; each source file was rechecked against the
  locked byte size and SHA-256 before linking.
- Generated and independently reverified an actual public-source preview from
  this worktree: 267 files in the stage, with all 266 non-manifest files covered
  by the SHA-256 manifest.
- Added conservative multipart GLB preparation for compatible exploded assets.
  Exact-coordinate seam duplicates are normalized independently inside each
  source part; parts are never welded to one another. Generated closure faces
  retain separate provenance and remain ineligible for source-face warnings.
- Added narrow automatic suppression of categorical part-identification
  `COLOR_0` data. It is enabled only when the exporter/node/material/texture and
  known ID-palette evidence all match; ordinary authored GLB vertex colours keep
  the standards-compliant multiply behavior.
- Added export-space multipart validation. The exact binary64 millimetre
  coordinates written to 3MF are rechecked before serialization and compared
  with the independently reloaded archive. Per-part QEM warning limits remain
  bounded, source-only, and externally anchored against metadata relabeling.
- Completed a rights-controlled six-part GLB end-to-end validation at the public
  450,000-face default: six 3MF mesh objects/components, all six watertight and
  valid solids, two tiny planar holes repaired, and categorical ID colours
  suppressed. The generated 3MF contained 224,956 vertices and passed its
  internal ZIP/topology/provenance validation. The private sample itself is not
  part of the repository or release.
- Ran the changed working tree's complete source regression: 1,149 tests in
  107.254 seconds, OK with one optional skip. The related multipart/export
  suite also passed 170/170, and `compileall` plus `git diff --check` passed.
- Built a new owner-only internal Windows test package from the current
  working tree after correcting the pinned PyInstaller 6.20.0 wheel-license
  path in the spec and adding a focused regression for that exact path.
- The internal build ran 1,150 tests in 106.340 seconds, OK with one optional
  skip, then passed packaged self-test, isolated Japanese and English UI
  smokes, and the fail-closed binary inventory (1,354 runtime files and 257
  native files).
- Created the local-only archive
  `ChromaMatter_0.8beta-r32-Multipart-INTERNAL-TEST-20260822.zip`: 1,355 files,
  118,994,068 bytes, SHA-256
  `A0174746A9D4301BF67F80D3786ED64BD09B7C7137E8F2C5CBB96CF4355927B5`.
  A fresh extraction matched every relative path and file SHA-256 and again
  passed self-test plus both language UI smokes. This is an unsigned,
  non-public, non-redistributable owner evaluation build only.

## 2026-08-23 source-publication checkpoint

The 1,179-test and 273/272 public-stage results in this section are the previous
checkpoint only. They predate the current Qt/PyMeshLab identity manifests,
PyTetWild static-closure contract, resvg frozen-runtime exclusion, and added
fail-closed package tests, so they must not be reused as evidence for the
current bytes.

- The current multipart and release-hardening worktree passed the full Python
  3.13.14 regression: 1,179 tests in 150.952 seconds, 1,178 passed, one optional
  skip, and zero failures.
- The binary-compliance, corresponding-source, and release-tooling set passed
  80 tests; release identity passed 10 tests.
- A fresh public-source stage passed both public-tree privacy audits and an
  independent manifest check: 273 files total, 272 SHA-256 records, zero
  missing files, zero extra files, and zero hash mismatches.
- Public package staging now accepts only a verified `release-approved`
  complete corresponding-source archive whose asset name, SHA-256, exact
  ChromaMatter commit, external manifest, and archived manifest all agree.
- The end-user ZIP layout is an exact allowlist: `ChromaMatter.exe`, `_internal`,
  four short runtime help/privacy/launcher files, licence materials, SBOM,
  component map, source offers, and its manifest. Development handoff and
  publication-planning documents are excluded.
- Component-specific licence assets and static-linked component coverage are
  implemented in the spec, component map/SBOM generator, publication stage,
  corresponding-source manifest, and fail-closed tests. This includes CPython
  extension dependencies, Qt/Mesa/LLVM, U3D and lib3mf subcomponents,
  PyInstaller, and the Embree-carried oneTBB runtime. The next clean binary must
  still regenerate and validate those outputs.
- Binary publication remains NO-GO. The controlled PyTetWild wheel/PYD,
  matching application lock, and static closure are now approved. Remaining
  gates are a `release-approved` complete corresponding-source bundle; a
  current clean binary build with regenerated inventory, packaged self-test,
  and Japanese/English UI smoke; fresh-extract manifest/privacy/archive/
  checksum parity; and immutable HTTPS Release URLs with every required asset
  published simultaneously.

## 2026-08-23 binary-publication compliance continuation (current)

- Added exact path/case/size/SHA-256 identities for 19 non-Qt PyMeshLab native
  files and 7 Qt DLLs. The generator and software stage independently reject
  missing or mismatched audited native identities.
- Added a reviewed Qt closure manifest covering 50 static components and 51
  byte-exact licence assets. The PyInstaller spec, component-map/SBOM generator,
  and software stage all consume it fail closed.
- Added a PyTetWild static/header closure contract covering 20 components, 29
  byte-exact licence assets, and 15 source archives. After the successful
  controlled rebuild it now records `release_gate.status=release-approved` and
  binds the rebuilt wheel/PYD plus matching application lock. The historical
  PyPI wheel/PYD remains audit-only and excluded from release approval.
- The component map now records PyTetWild closure validation violations and the
  SBOM carries the matching validation count. The software stage independently
  enforces the approved wrapper identity, sorted 20-component mapping, 29
  assets, and matching application-lock wheel whenever a PyTetWild runtime is
  present. Historical or mismatched PyTetWild bytes still fail closed. Packages
  that genuinely do not contain PyTetWild remain stageable.
- The hidden Decal beta remains in source for development tests, but `resvg`
  and `resvg._resvg` are deliberately excluded from the public frozen runtime.
  Source attribution remains public; unused resvg runtime metadata and native
  code are not packaged.
- Focused Qt/PyMeshLab/PyTetWild, binary-compliance, corresponding-source,
  notice, CLI, release-identity, Decal packaging-policy, and software-stage
  tests pass: 178 tests, 177 passed, one optional skip, zero failures.
- The full Python 3.13.14 regression passes: 1,234 tests, 1,232 passed, two
  optional skips, zero failures. The obsolete Decal packaging assertions found
  on the first run were updated to enforce the intended source-only resvg and
  frozen-runtime exclusion contract before this final pass.
- After installing the verified toolchain and correcting its exact identity
  contract, the focused corresponding-source/release/static-closure/notices/
  binary-inventory/release-identity set passed 137/137. The complete Python
  3.13.14 regression then passed 1,236 tests: 1,234 passed, two optional skips,
  and zero failures.
- A pre-adoption public-source stage passed at 395 files including the manifest and
  394 manifest records. Both the staged privacy audit and an independent
  path/SHA-256 parity check report zero missing, extra, or mismatched files.
  Source publication eligibility was true for that earlier validated source-only
  scope. Adoption changed source bytes, so current r32 source and binary
  publication eligibility are false until exact restaging and the remaining
  release gates pass.
- A current generator probe against the old audit-only package failed closed as
  designed. It reported the historical PyTetWild wheel/application-lock
  mismatch and blocked closure gate; that old package is not release evidence.
- The first outbound-isolated rebuild attempt stopped before source export and
  its merged PowerShell stream retained only the first traceback line. The
  local-only launcher now runs the recipe as a separate non-elevated process,
  records stdout and stderr independently, records an unambiguous integer exit
  code, and preserves the elevated firewall guardian's fail-closed cleanup.
- The process-isolated retry exposed and reproduced a Windows PowerShell 5.1
  localized-output defect: `vswhere.exe -utf8` JSON was decoded through the
  active Japanese console code page. The recipe now scopes strict BOM-free
  UTF-8 decoding to that command, restores the previous decoder in `finally`,
  and rejects capture, exit-code, or JSON failures separately.
- The UTF-8 recipe/static-closure follow-up passed 143 focused tests. A later
  controlled run (`20260823-142413-edd113a24226`) received explicit UAC
  approval, verified outbound deny-all, and verified firewall/task cleanup, but
  failed closed before source export because Windows PowerShell 5.1 stripped
  embedded double quotes from a multiline native `python -c` argument. Its
  output root contains only the controlled `tmp` directory; it produced no
  wheel, audit log set, or attestation.
- Every multiline Python payload in the recipe now goes through
  `Get-ControlledPythonArguments`: strict UTF-8 source bytes are Base64 encoded,
  decoded by a fixed ASCII bootstrap, and executed with the original positional
  `sys.argv` preserved. The runtime regression covers double quotes,
  backslashes, non-ASCII source/arguments, and the exact temporary-directory
  probe under Windows PowerShell 5.1. The Base64 transport/release/static-
  closure follow-up passed 78/78. The exact changed source then passed 1,241
  tests: 1,239 passed, two optional skips, and zero failures.
- Controlled run `20260823-160956-6e2612066766` received explicit UAC approval,
  verified outbound deny-all, and completed fail-closed cleanup with zero
  residual firewall rules or scheduled tasks. It compiled all 227 targets and
  produced distinct raw and repaired wheels plus 12 source archives. It then
  failed closed in the repaired-wheel RECORD audit because the wheel contained
  the benign explicit directory members `pytetwild/`, `pytetwild.libs/`, and
  `pytetwild-0.3.0.dist-info/licenses/`. Only four of the required eight direct
  audit logs were produced and no attestation exists. The partial wheels,
  source archives, and logs are not verified release evidence and must not be
  adopted. This failed run is retained only as historical diagnostic evidence.
- The corrected recipe then completed controlled outbound-isolated run
  `20260823-174626-089357844d4b` at exact repository commit
  `5feb198eef3432cdec19a0367d53e1b52bd4a363`. UAC approval and outbound
  deny-all were verified; all 227 targets compiled; the distinct raw and
  repaired wheels, all eight direct audit logs, 12 source archives, and a
  `verified-controlled-rebuild` attestation were produced. Cleanup left zero
  persistent or active firewall rules and no scheduled task.
- Adopted controlled identities in the current source contract: repaired wheel
  `e3b11ac058266d277b0f83448c6023d5da98e731d0d016e461dbce4ebdfd613d`
  (1,637,633 bytes), raw wheel
  `9fbedacd1286a7e792a1503490669916d8a449cf9948ccc0f2899fdcda7c8089`
  (1,088,024 bytes), `PyfTetWildWrapper.pyd`
  `26a091b53279407014899c046691958c9df07e22703576da6a45d68a9be22430`
  (3,927,552 bytes), and attestation
  `3989fd1debe8b6c984938c4a64ee5fb3bcce1b612cf83524ea309b1fae3cde9f`
  (12,445 bytes). The application lock and PyTetWild static closure now bind
  the repaired-wheel identity. This component closure approval does not make
  any Windows application archive publishable.

## Current state

- Entry checkpoint `435895d451ae2b3875249fd789aee92dc30a44bb` is already on
  `origin/codex/r32-full-spectrum-workflow` and Draft PR #1. At entry the branch
  was ahead 4 / behind 0 relative to `main` and ahead 0 / behind 0 relative to
  its upstream.
- The source-publication checkpoint belongs on
  `codex/r32-full-spectrum-workflow` and updates Draft PR #1. `main` was not
  modified; do not move this work to `main` without a separate review and owner
  decision.
- GitHub has no repository Actions workflow, check run, public tag, or public
  Release for this branch. Release validation remains local and manual.
- The existing r32 Windows ZIP and EXE predate these compliance changes and are
  **not publishable**.
- They also predate the multipart GLB, identification-colour suppression, and
  export-space 3MF validation changes above. A clean rebuild, packaged self-test,
  Japanese/English UI smoke, restaging, privacy/archive audit, and fresh detached
  checksums are required before any new binary claim.
- The existing internal multipart test ZIP validates the pre-adoption
  application bytes for owner testing only. It deliberately bypassed the
  public software stage and does not contain the adopted controlled wheel; it
  is not evidence for the current source and does not change binary
  publication NO-GO.
- `CURRENT_STATE.json` now records the latest source regression and public-source
  stage separately from the historical pre-multipart binary preflight. Do not
  treat the old executable hash or file counts as evidence for this worktree.
- Source publication and binary publication are separate. Existing public
  source history remains available; the new Windows binary remains NO-GO.
- The corresponding-source manifest deliberately remains candidate-only until
  the successful run's repaired wheel, distinct raw wheel, exact eight direct
  audit logs, attestation, and a commit-bound generated rebuild lock are staged
  into the final complete bundle. The MeshLab acquisition lock is complete,
  but its final staged bundle has not yet been produced. The verified
  public-source preview above predates adoption and is a source-tree
  completeness checkpoint, not that final corresponding-source bundle.
- All prospective native inputs are present and fixed. The verified offline
  Visual Studio Build Tools 17.14.39 layout was installed successfully on
  2026-08-23 at `C:\ChromaMatterToolchain\VS2022BuildTools`. The installed
  instance is complete and launchable, selects VCTools 14.44.35207 and Windows
  SDK 10.0.26100.0, and matches the fixed layout evidence. No reinstall or
  redownload is required. The controlled rebuild is complete and adopted by
  the application lock/static-closure contract. The remaining blockers are the
  commit-bound rebuild lock, complete corresponding-source stage, clean Windows
  application build, software stage, fresh-extract smoke/audits, and final
  checksum/immutable-URL parity.
- The repository root does not carry a reusable source manifest. Every public
  source or complete corresponding-source stage generates its own
  `SOURCE_MANIFEST_SHA256.txt` only after the exact staged bytes are frozen and
  verifies that manifest before the stage is accepted.

## Next exact task

1. Review Draft PR #1 from `codex/r32-full-spectrum-workflow`; keep `main`, tags,
   and public Releases unchanged until the binary publication gates below pass.
2. Preserve controlled run `20260823-174626-089357844d4b` as one inseparable
   evidence set. Do not substitute the earlier partial wheels or any later
   unbound rebuild. Use `BOOTSTRAP_WINDOWS.ps1 -PyTetWildWheel` with the adopted
   repaired wheel in the release build environment and require its SHA-256 to
   match `source/fixed_app/requirements-build.lock`.
3. Commit the adopted application lock, approved PyTetWild static closure,
   notices, inventory mapping, tests, and state documents. Export the canonical
   recipe, build requirements, source patch, and application lock as exact blobs
   from that commit, then generate the commit-bound PyTetWild rebuild lock.
4. Stage full corresponding source with the complete MeshLab archive lock and
   every PyTetWild bound evidence input. When passing a verified rebuild lock,
   pass the repaired release wheel with `-PyTetWildWheel`, the distinct
   pre-repair wheel with `-PyTetWildRawWheel`, and the directory containing the
   audit logs with `-PyTetWildAuditLogs`, in addition to the recipe, hashed
   requirements, source patch, attestation, and exact application lock. Require
   the recipe, hashed requirements, source patch, and application lock to
   byte-match their canonical paths at the exact project commit. Require output
   `COMPONENT_SOURCES.json` status `release-approved`.
5. Freeze artifact names and immutable HTTPS source-offer URLs. From a new clean
   build root run the full regression and PyInstaller build, then run
   `tooling/generate_binary_compliance_inventory.py` with its required
   `--package-root`, `--sbom-output`, and `--component-map-output` arguments.
6. Stage and fresh-extract the software and source archives; run packaged
   self-test, Japanese/English UI smoke, manifest, privacy, CRC, byte-parity,
   relinking, and checksum audits.
7. Publish the Windows ZIP, complete corresponding source, SBOM, component map,
   and detached checksum simultaneously at the exact immutable HTTPS Release
   URLs already embedded in the source offers. Backpatch `CURRENT_STATE.json`
   and public status documents only with those exact results. Keep
   `binary_publication_eligible=false` until every gate passes.

Controlled completed matrix for run `20260823-174626-089357844d4b`: CPython
3.12.10 x64 builder; Visual Studio Build
Tools 2022 17.14.39; VCTools directory 14.44.35207; `cl.exe` file version
19.44.35228.0 and product version 14.44.35228.0; `link.exe` file and product
version 14.44.35228.0; Windows SDK 10.0.26100; CMake
3.29.6; Ninja Python distribution 1.13.0; nanobind 2.12.0 at commit
`2a61ad2494d09fecb2e13322c1383342c299900d`; cibuildwheel 3.3.1;
scikit-build-core 0.12.2; delvewheel 1.12.1; abi3audit 0.0.26; build 1.5.0;
MPIR 3.0.0 `he025d50_1002`; NumPy 2.5.1 for the isolated normal-import smoke.
The VS layout is fixed at 714 files, 2,651,377,645 bytes, tree SHA-256
`2b6a89bb69aa7de013fc055828258a3a91c7c333f0c6be831a750990922fed3a`.
This is the verified controlled rebuild environment, not a claim about the
expired historical CI environment or a completed Windows application build.

The installed-toolchain audit confirmed that 14.44.35211 is the CRT
redistributable version, not `Microsoft.VCToolsVersion.default.txt`. The build
recipe now checks the exact VCTools, compiler, and linker identities above. It
also resolves the SDK from the 64-bit native, 64-bit WOW6432Node, and 32-bit
view `KitsRoot10` values and accepts exactly one distinct candidate containing
both the fixed x64 `signtool.exe` and `kernel32.lib`; the current native
registry root is incomplete and the verified SDK root is the WOW6432Node
candidate. An explicit `-WindowsSdkRoot` remains supported but must itself be
the one complete root.

The process-isolated controlled-build retry exposed a deterministic Windows
PowerShell 5.1 decoding bug: `vswhere.exe -utf8` JSON containing Japanese text
was decoded through the active console code page. The recipe now invokes that
one command through a scoped strict BOM-free UTF-8 native-output capture and
restores the prior `[Console]::OutputEncoding` in `finally`; a runtime
regression emits and parses non-ASCII UTF-8 JSON and verifies restoration.

The next UAC-approved isolated run exposed a second Windows PowerShell 5.1
native-argument defect: direct multiline `python -c` transport removed embedded
double quotes before Python parsed the source. The fix is intentionally shared
by the temporary-directory, safe-tar, package-version, raw/repaired RECORD,
native-dependency, and isolated-import probes. Each source string is strict
UTF-8/Base64 and only a fixed ASCII bootstrap is transported directly through
`-c`; a negative static contract rejects the old direct multiline forms.

The subsequent controlled run `20260823-160956-6e2612066766` verified UAC,
outbound deny-all, and zero-residual cleanup, compiled all 227 targets, and
created distinct raw/repaired wheels and 12 source archives. It stopped
fail-closed at the repaired-wheel RECORD audit after encountering the explicit
directory members `pytetwild/`, `pytetwild.libs/`, and
`pytetwild-0.3.0.dist-info/licenses/`. Post-run inspection identified those
three entries as benign directory metadata, but the stopped run has only four
of eight required direct logs and no attestation. Its outputs remain partial,
unadoptable evidence.

The corrected retry `20260823-174626-089357844d4b` completed successfully at
commit `5feb198eef3432cdec19a0367d53e1b52bd4a363` with recipe SHA-256
`d00cc6cdbc61abeaa040dfc81a3dfe7086ac0027685d798ac70f46e14e4360c8`.
It produced the attested raw/repaired wheel pair, all eight audit logs, and all
12 source archives; normal isolated import and vendored-DLL runtime loading
passed. The repaired wheel, extension PYD, and attestation identities are
recorded above and in `CURRENT_STATE.json`. Firewall/task cleanup passed with
zero residual state.

For the pending verified-lock/source stage, the `-PyTetWildAuditLogs` directory must
contain exactly these eight direct files and nothing else:
`visual-studio-layout-verification.log`, `build-wheel.log`,
`delvewheel-show-raw.log`, `delvewheel-repair.log`,
`abi3audit.log`, `native-dependency-closure.log`, `native-smoke-install.log`, and
`native-normal-import.log`. Nested entries, extra files, and symlinks are
rejected. Staging verifies the separate raw and repaired wheel identities and
all eight log SHA-256 values against the build attestation, then copies them to
`build-evidence/pytetwild/raw-wheel/`,
`build-evidence/pytetwild/repaired-wheel/`, and
`build-evidence/pytetwild/logs/`, respectively. The local controlled evidence
exists, but no final `release-approved` corresponding-source stage has yet
copied it into a distributable source bundle.

Focused command:

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -B -m unittest `
  source.fixed_app.test_legal_notice `
  source.fixed_app.test_binary_compliance_inventory `
  source.fixed_app.test_corresponding_source_tooling `
  source.fixed_app.test_release_tooling
& $python .\tooling\stage_corresponding_source.py `
  --manifest .\tooling\corresponding_source_components.json `
  --validate-manifest-only
git diff --check
```

## Changed files

Primary continuation paths in the source-publication checkpoint:

- `.gitignore`
- `BOOTSTRAP_WINDOWS.ps1`
- `HANDOFF.md`
- `CURRENT_STATE.json`
- `README.md`
- `README_EN.md`
- `README_JA.md`
- `README_PUBLIC_EN.md`
- `README_PUBLIC_JA.md`
- `licenses/BUILD_ENVIRONMENT_EN.md`
- `licenses/BUILD_ENVIRONMENT_JA.md`
- `publication/BINARY_RELEASE_HANDOFF_JA.md`
- `source/fixed_app/README_fixed_en.md`
- `source/fixed_app/README_fixed_ja.md`
- `source/fixed_app/TripoSpectrumMapper_fixed.spec`
- `source/fixed_app/test_corresponding_source_tooling.py`
- `source/fixed_app/test_decal_image.py`
- `source/fixed_app/test_release_identity.py`
- `source/fixed_app/test_release_tooling.py`
- `tooling/corresponding_source_components.json`
- `tooling/BUILD_PYTETWILD_WINDOWS.ps1`
- `tooling/requirements-pytetwild-build.lock`
- `tooling/patches/pytetwild-0.3.0-optional-pyvista.patch`
- `tooling/meshlab_windows_external_archives.lock.json`
- `tooling/pytetwild_rebuild_lock.template.json`
- `tooling/generate_pytetwild_rebuild_lock.py`
- `tooling/pymeshlab_audited_native_identities.json`
- `tooling/qt_static_components.json`
- `tooling/pytetwild_static_closure.json`
- `tooling/pytetwild_static_closure_contract.py`
- `tooling/stage_corresponding_source.py`
- `tooling/stage_corresponding_source.ps1`
- `tooling/stage_public_source.ps1`

## Tests run

Component-level results reported before the final integrated checkpoint:

- Legal notice focused tests: 29 passed.
- Binary inventory focused tests: 7 passed.
- Corresponding-source fixture tests: 6 passed; public-stage integration: 3 passed.
- Software-stage compliance tests: 4 passed.
- Dependency lock install/download: passed for 25 exact wheels on Python 3.13.14.
- Historical r32 package read-only inventory: 1,404 files, 297 native files,
  zero unmapped native files, zero reparse points; this does not approve that old package.
- An earlier 1,074-test run had one missing-tool error. The public filament
  updater was restored and its focused regression subsequently passed.

Final local checkpoint results:

- Integrated legal notice, binary inventory, corresponding-source, and release
  tooling set: 46 tests passed in 22.108 seconds.
- Full source regression after restoring the missing public tool: 1,076 tests
  in 103.485 seconds, 1,075 passed, 1 optional skip, 0 failures.
- Restored filament-library updater regression: 7 tests passed.
- Release tooling rerun after adding `AGENTS.md` / `HANDOFF.md` to the public
  stage: 24 tests passed in 13.754 seconds.
- Corresponding-source production manifest validation: PASS, with status
  `candidate-only-not-release-approved` as intended.
- PowerShell parser: PASS for bootstrap, build, public stage, software stage,
  and corresponding-source wrapper.
- JSON parse: PASS for the component-map schema, component manifest, MeshLab
  external archive lock, and blocked PyTetWild rebuild template.
- Python compile: PASS for the three new tooling modules and legal notice module.
- Source UI smoke with isolated disposable profiles: Japanese exit 0 and
  English exit 0 using `--ui-smoke --ui-smoke-language ja|en`.
- `git diff --check`: PASS.
- Known non-fatal output: optional PyMeshLab plugins unavailable in the local
  source-test environment; test exit status remained zero.
- Superseded internal multipart test build after the packaging-path fix: 1,150 tests in
  106.340 seconds, 1,149 passed, 1 optional skip, and 0 failures.
- Packaged and fresh-extracted self-tests: PASS. Packaged and fresh-extracted
  isolated Japanese/English UI smokes: PASS. Fresh archive path/SHA-256 parity:
  PASS for all 1,355 files.
- Binary compliance inventory for the internal build: PASS with 1,354 runtime
  files, 257 native files, zero unmapped native files, and zero reparse points.

Continuation results on exact Python 3.13.14:

- Entry full regression before edits: 1,076 tests in 88.420 seconds; 1,075
  passed, 1 optional skip, 0 failures.
- Updated legal/inventory/corresponding-source/release/decal set: 76 tests in
  20.674 seconds, all passed.
- Updated full source regression: 1,084 tests in 88.540 seconds; 1,083 passed,
  1 optional skip, 0 failures.
- `pip check`: PASS for the 25-package exact `.venv`.
- Production corresponding-source manifest validation: PASS and still
  `candidate-only-not-release-approved` because final evidence is absent.
- A production-bundle probe without PyTetWild evidence stopped before any
  network fetch or partial output, as designed; no destination or archive was
  left behind.
- Candidate determinism, partial-gap candidate behavior, complete-evidence
  `release-approved` transition, wheel identity/hash rejection, and install-path
  privacy filtering tests: PASS.
- PowerShell parser, Python compile, and `git diff --check`: PASS after the
  continuation edits.
- Latest corresponding-source/release-tooling set: 61 tests in 29.354 seconds,
  all passed.
- Latest full source regression: 1,107 tests in 98.997 seconds; 1,106 passed,
  1 optional skip, 0 failures.
- Controlled PyTetWild recipe set after the stderr/logging regression test was
  added: 9 tests, all passed. The runtime test exercises
  stdout+stderr with both exit 0 and exit 7 under Windows PowerShell 5.1,
  verifies UTF-8 without BOM, and confirms logs are written before failure.
- Public-source preview staging and privacy audit: PASS. Independent SHA-256
  verification covered exactly all 266 files listed by
  `SOURCE_MANIFEST_SHA256.txt`.
- Offline `pip --dry-run --ignore-installed --no-index --require-hashes`
  resolution: PASS for all 39 controlled PyTetWild build/audit wheels.

Full-resolution multipart continuation on exact Python 3.13.14 (2026-08-22):

- The earlier 1,150-test internal build and default-reduction multipart E2E are
  previous evidence only; they do not validate the no-reduction continuation.
- Compatible multipart normalization now proves every retained triangle is an
  exact-coordinate multiset subset of its imported part, including duplicate
  multiplicity. The inherited-source policy is unavailable after QEM, joint
  topology, coordinate movement, incomplete normalization, or missing proof.
- This is not a self-intersection repair or a general threshold relaxation. A
  finding may be reported as a bounded warning only when all mandatory solid
  checks pass, every selected face is in the externally anchored source prefix,
  count is at most 1% of that source prefix, and selected physical area is at
  most 0.2% of the part. Ordinary and generated-cap intersections still fail
  closed.
- Saved project, preparation, and archive metadata are never a trust source for
  this exception. Preparation derives it from the live exact-coordinate proof;
  exact 3MF write and archive reload recompute complete face IDs and areas and
  recheck external source-prefix, policy, cap-range, geometry-hash, and
  provenance anchors.
- Individual-part 3MF extraction now rebases the selected source part to local
  part ID zero and rebases boundary vertex IDs against the exact extracted
  vertex layout. It projects live multipart proof directly into the child only
  when the parent source limits, normalization, warning policy, repair records,
  generated suffix, and part layout are all complete and mutually consistent.
- Local repair caps and shared-interface caps remain separate provenance types.
  The one-sided shared-interface projection is accepted only under its dedicated
  individual schema with the original source pair and the selected child map;
  missing, stale, or altered proof fails closed instead of weakening validation.
- A non-public six-part high-resolution validation asset was processed with
  face-count reduction disabled: 2,016,940 output faces, six watertight
  consistently wound positive-volume single bodies, and exact combined 3MF
  write/reload validation passed. All six individual 3MF files plus the manifest
  also passed strict archive reload and projected-provenance validation.
  Generated repair caps remained outside the source face range and were never
  accepted as source self-intersections. Categorical identification colours were
  also suppressed. No private asset or derived 3MF is retained in Git or the
  test ZIP, and both disposable validation runs were cleaned completely.
- Fresh current build: 1,168 tests in 113.445 seconds, 1,167 passed,
  1 optional skip, 0 failures;
  packaged and fresh-extracted self-test plus isolated Japanese/English UI
  smokes passed. Binary inventory passed for 1,354 runtime files and 257 native
  files with zero unmapped native files and zero reparse points.
- Current owner-only archive:
  `ChromaMatter_0.8beta-r32-FullResMultipart-INTERNAL-TEST-20260822c.zip`,
  118,851,316 bytes, SHA-256
  `748E3C7962DB21AFB9DDFBABF9082E2E49DECBA4BAF2078EE99A737910E40C19`.
  CRC/encryption/security/path/privacy, deterministic component-map/SBOM, and fresh-extract
  path/size/SHA checks passed for all 1,355 staged files. The earlier archive
  with the `b` suffix is superseded. The current archive remains unsigned,
  non-public, and not release evidence.
- Snapmaker Orca project-open/slice-preview and physical-print confirmation are
  still pending.

Current compliance-integration validation on exact Python 3.13.14
(2026-08-23):

- Focused Qt/PyMeshLab/PyTetWild, binary inventory, corresponding-source,
  software-stage, notices, release identity, CLI, and Decal packaging-policy
  regression: 178 tests, 177 passed, one optional skip, zero failures.
- Latest full source regression after the corrected toolchain identity contract:
  1,236 tests, 1,234 passed, two optional skips, zero failures. The preceding
  1,234-test result remains the pre-toolchain-contract checkpoint.
- Windows PowerShell 5.1 UTF-8 native-capture/static-closure/release follow-up:
  143 focused tests passed. The later Base64 native Python-probe transport,
  release-tooling, and static-closure follow-up passed 78/78. The final changed
  source regression before adoption ran 1,241 tests: 1,239 passed, two optional
  skips, and zero failures. The post-adoption working tree then ran 1,244 tests
  in 185.852 seconds: 1,242 passed, two optional skips, and zero failures.
- Production corresponding-source manifest validation: PASS with intended
  status `candidate-only-not-release-approved`.
- Public-source stage: 395 files including `SOURCE_MANIFEST_SHA256.txt`, 394
  manifest records, privacy audit PASS, independent exact path/SHA-256 parity
  PASS with zero missing, extra, or mismatched files. This stage matches the
  controlled-build source checkpoint and predates wheel-adoption source edits;
  it must be regenerated for final publication evidence.
- Controlled PyTetWild run `20260823-174626-089357844d4b`: PASS at exact
  commit `5feb198eef3432cdec19a0367d53e1b52bd4a363`; outbound deny-all and
  cleanup verified; 227 targets compiled; distinct raw/repaired wheels, all 8
  direct logs, 12 source archives, strict ABI/native/import checks, and the
  `verified-controlled-rebuild` attestation all completed. The application
  lock binds the approved repaired wheel; the static-closure contract binds
  that wheel and its PYD. The attestation remains recorded evidence to be
  machine-bound by the final commit-specific rebuild lock.
- PyTetWild-containing old audit-package probes: FAIL-CLOSED as intended; no
  publication destination/archive was retained and no old package became
  release evidence.
- PowerShell parser, nine machine-readable JSON manifests, 189 Python files,
  `pip check`, and `git diff --check`: PASS. Two byte-preserved upstream Qt
  `qt_attribution.json` assets contain upstream control characters and are not
  treated as application JSON; their exact bytes are validated by the Qt
  manifest/hash tests.
- Controlled-identity state/document follow-up: release identity plus
  PyTetWild static-closure manifest, contract, and notice tests passed 29/29;
  `CURRENT_STATE.json` parsed successfully and `git diff --check` passed. The
  later post-adoption full regression passed 1,244 tests with two optional
  skips. These source-test results do not replace the pending clean binary
  build, corresponding-source restage, or packaged verification.

## 2026-08-23 Innovation Fund public-release continuation

### Objective

Prepare the first public r32 Windows distribution for the Innovation Fund:
the Windows software ZIP, one complete corresponding-source ZIP, a versioned
CycloneDX SBOM, a versioned binary component map, the short workflow video,
and one detached checksum file must be published together. The video is the
simple-use demonstration; it is not a substitute for reproducibility evidence.

### Completed so far

- Created a privacy-reviewed public workflow-video copy as H.264, 1920x1080,
  30 fps, 125.333 seconds, no audio, 37,708,741 bytes, SHA-256
  `F55F9505EC7385D27A933799F9EEFD1C2499A77B86B0BB1162832320E88FEE61`.
  Browser/account chrome, every Explorer interval, personal paths and names,
  filenames, profile markers, and the recorded location label were removed or
  replaced. It must be attached directly to the GitHub Release as
  `ChromaMatter-simple-workflow-demo.mp4`; it must not be committed to Git or
  embedded in the software or corresponding-source ZIP.
- Added the print-result overview, a concise limited/unofficial Hi3D-compatible
  multipart GLB explanation, the planned video link, and safer ZIP-contract
  automation and regression coverage.
- Intermediate clean build at exact commit
  `6ada59418796ab0bbe158fa5a9bcff32e8e188bc` passed 1,246 source tests with two
  optional skips, packaged self-test, isolated Japanese and English UI smoke,
  and the compliance inventory (1,455 runtime files / 256 native files). This
  evidence became historical when the privacy and documentation bytes changed.
- A final public audit identified tracked private denylist values, personal
  Git commit metadata, premature r32 publication wording, and an overbroad demo
  evidence claim. The tracked-value and wording remediation is complete. The
  r32 tree was then reconstructed as one GitHub-noreply commit on the sanitized
  `codex/r32-public-release` branch and proved byte-identical to the reviewed
  feature tree before this manifest/handoff cleanup.
- Repository-local Git identity is now configured to the project owner's
  GitHub noreply address for all new public commits.

### Current state and next exact task

- The superseded feature branch contains earlier commits with personal
  author/committer metadata. Do not tag or merge that history. Continue only
  from `codex/r32-public-release`, keep it as one GitHub-noreply commit ahead of
  `origin/main`, and re-prove the final tree and metadata after any amend.
- The clean build above is not reusable after the privacy/documentation edits.
  Build again from the sanitized public commit in a fresh source checkout and
  fresh output root.
- Generate the commit-bound PyTetWild rebuild lock, stage the offline
  `release-approved` complete corresponding source, materialize and verify the
  versioned SBOM/component-map names, and stage the software ZIP.
- Fresh-extract both ZIPs; verify paths, CRC, manifests, privacy, byte parity,
  source status, hashes, packaged self-test, and isolated Japanese/English UI
  smoke. Generate `SHA256SUMS-r32.txt` for the five other Release assets; the
  checksum file must not list itself.
- Stop before merging, tagging, or publishing the GitHub Release and obtain the
  owner's final confirmation. Command-line push authentication is not currently
  available; use the signed-in GitHub Desktop session or authenticate Git before
  updating the public branch.

### Changed paths in this continuation

- Public READMEs and feature summaries.
- Innovation Fund status/application and release handoff documents.
- `tooling/SoftwareZipContract.psm1`, public-tree/software-stage privacy
  auditing, and release staging tests.
- Privacy-safe test fixtures and clean-clone guidance.

### Validation recorded for this continuation

- Intermediate exact-commit clean build and package smokes: PASS as described
  above; historical only after subsequent source edits.
- Privacy-reviewed, muted workflow-video decode, 3,760-frame identity,
  fine-grained leak-window review, one-second full-duration contact review,
  and final byte identity: PASS at the size and SHA-256 above.
- Focused privacy/documentation regression: 87 tests passed with zero failures;
  PowerShell parsing, tracked private-token scan, README twin parity, JSON parse,
  and `git diff --check` passed.
- The sanitized branch and one-commit public history are complete. The final
  amended-commit full build, staging, extraction, and checksum gates remain
  pending at this checkpoint.

### Continuation-specific prohibitions and local-only material

- Do not publish the old internal ZIP, the intermediate `6ada594` package, or
  any artifact built from history containing personal commit metadata.
- Do not add either the original recording or the 37.7 MB privacy-reviewed
  Release video to Git or the software/source ZIPs.
- Keep the original video, clean-build roots, controlled PyTetWild evidence,
  complete source cache, staging roots, and extracted audit roots outside Git.
- Do not push, merge, tag, or create the public Release until the final
  sanitized-commit gates pass and the owner confirms publication.

## Do not do

- Do not commit directly to `main`.
- Do not publish the existing r32 EXE/ZIP or relabel it as an AGPL-compliant release.
- Do not set `binary_publication_eligible=true` from source-only or old-build evidence.
- Do not remove TetGen/PyMeshLab/Qt/GEOS license obligations by changing labels.
- Do not guess an expired CI build dependency version or claim bit-for-bit reproducibility.
- Do not weaken topology or 3MF fail-closed validation to make a model export.
- Do not commit private models, model names, absolute personal paths, binaries,
  build output, archives, virtual environments, caches, credentials, or personal email.
- Do not use GitHub's automatic source ZIP as the complete third-party source;
  it omits required submodules.

## Local-only files

Keep these outside Git and do not copy them to the public release by default:

- `.venv/` and any temporary exact-lock virtual environment.
- `build/`, `dist/`, `artifacts/`, validation output, and clean-build roots.
- Existing r31/r32 binary folders, ZIPs, and detached checksums.
- Corresponding-source download caches, probe directories, and fresh-extract
  audit directories.
- Disposable `%TEMP%\ChromaMatter-source-ui-smoke-*` profile directories.
- Private input/reference/validation models and all derived exports.
- `C:\ChromaMatterInternalTest_20260822_Multipart01\` (failed build attempt),
  `C:\ChromaMatterInternalTest_20260822_Multipart02\` (successful build), the
  local internal-test stage/archive, and any fresh-extraction audit directory.
- `C:\\ChromaMatterInternalTest_20260822_FullRes01\\` and
  `C:\\ChromaMatterInternalTest_20260822_FullRes02\\` (superseded), plus
  `C:\\ChromaMatterInternalTest_20260822_FullRes03\\` (current internal build),
  plus all FullRes internal stages, archives, fresh extracts, and smoke profiles.
- Subscription receipts, account screenshots, job IDs, and other rights
  evidence containing personal information. Record only a redacted public
  provenance statement when needed.
- `C:\CMR32PYTETPROBE1\` and any later fail-closed software-stage probe output;
  these are local audit evidence only and must not be committed or published.
- `C:\ChromaMatterToolchain\orchestration\` and
  `C:\ChromaMatterToolchain\orchestration-runs\`; these local firewall/build
  launchers and failed-run logs are operational evidence only. Preserve failed
  runs, never treat them as release evidence, and do not copy them into Git or
  a public package.
- `C:\ChromaMatterToolchain\pytetwild-controlled-build-20260823-174626-089357844d4b\`
  and its orchestration-run controls. Preserve them as the successful local
  controlled evidence source, but copy only the exact allowlisted evidence
  through corresponding-source staging; do not commit the local directories.

## 2026-08-24 post-publication documentation checkpoint

### Objective and completed work

- Make the Windows r32.1 ZIP immediately visible from the GitHub landing page.
- Record the exact published-prerelease evidence instead of the superseded
  candidate/pending state.
- State prominently that multipart solidification is still unstable: bundled
  `DemoData` succeeds, while other multipart files may fail solidification or
  3MF export. This incomplete compatibility is one reason for `0.8beta`.
- Align the English/Japanese README aliases, features, provenance, Release
  notes, publication/legal checklists, Innovation Fund drafts, video checklist,
  fixed-source README copies, `CURRENT_STATE.json`, and the disclosure test.
- Correct two nonexistent relative links in the paste-ready Innovation Fund
  README draft.

### Current state and review path

- Public review PR <https://github.com/Ponkichi0718/ChromaMatter/pull/3> was
  squash-merged to `main` as
  `76daf15cd49933cab14839f9535ba4f1d9ef5eba`.
- The frozen `v0.8beta-r32.1` tag still resolves to
  `b575b93d973ed67e7ada986469b10b4490eef4e5`; none of the six Release asset
  bytes were rebuilt, replaced, or retagged.
- The live Release body now matches `publication/RELEASE_NOTES_r32.1.md` and
  includes the Windows direct download plus the multipart beta limitation.
  An unauthenticated final check confirmed all six asset names, sizes, and
  SHA-256 digests are unchanged; the Windows direct-download HEAD request
  returned HTTP 200.

### Validation

- `source.fixed_app.test_release_identity`: 12/12 PASS in the fixed dependency
  environment after the final documentation changes.
- Release tooling, corresponding-source tooling, and legal notice modules:
  135/135 PASS in the fixed dependency environment.
- `CURRENT_STATE.json` parse, README alias parity, local draft-link target
  existence, added-line privacy review, and `git diff --check`: PASS.
- A system-Python attempt lacked the `pymeshlab` package and produced 25 setup
  errors. The same 135 tests passed in the pinned dependency environment, so
  those errors are not source or documentation failures.

### Next task and prohibitions

- No r32.1 source, binary, tag, asset, or public-metadata work remains for this
  documentation request.
- Do not move either release tag, rebuild r32.1, replace any attached asset, or
  weaken topology/3MF validation in response to the documented beta limit.
- Physical XP-PEN validation, a release-bound Orca/U1 reproducibility matrix,
  the 90-second hero/cover/community post, and the Innovation Fund submission
  remain future work. Keep all private models, credentials, build roots, and
  controlled toolchain evidence local-only as listed above.

## 2026-08-24 r32.2 demo-output release-candidate checkpoint (in progress)

### Candidate scope

- The working edition/artifact revision is `AI Model Print Studio r32.2` /
  `r32.2-ai-model-print-studio`. Public display and package version stay
  `0.8beta`; Windows numeric version stays `0.8.0.0`.
- r32.2 is a separate local packaging/demo-output candidate. The immutable
  `v0.8beta-r32.1` tag, six Release assets, hashes, regression, build, and
  publication results remain previous evidence only and must not be changed or
  promoted as current r32.2 evidence.
- The planned Windows package adds exactly seven owner-approved outputs below
  `DemoData/3MF/`: one combined Full Spectrum project plus six part-specific
  projects derived from `Original AI model Color.glb`.
- Hi3D-derived part labels can disagree with visible geometry. Users must
  inspect each project instead of trusting the part filename. Regenerating the
  demo requires selecting the physical black F slot and applying **Weak Black
  5–25% before 3MF export**.
- Multipart solidification remains unstable beta compatibility. The bundled
  demo is a successful case, but other multipart OBJ/GLB files may fail to
  solidify or export as 3MF.

### Release gates still pending

- Freeze the exact r32.2 source commit, preserve the preflight-passed canonical
  10-payload DemoData set byte-for-byte, and continue excluding every local
  validation sidecar and absolute user path. Repeat the clean-build gate from
  that exact commit; the changed working tree has already passed the focused
  and complete source suites recorded below.
- Produce the clean Windows build, packaged self-test, isolated Japanese and
  English UI smokes, software/source stages, and complete corresponding source.
- Independently fresh-extract and reverify manifest parity and all seven derived
  3MF hashes from the final staged ZIP, plus privacy, archive paths/security,
  binary compliance, SBOM/component
  map, executable identity, detached checksums, and final public asset bytes.
- Do not tag, upload, publish, or advertise an r32.2 download until every gate
  passes. Continue linking the frozen r32.1 prerelease in public download copy
  until r32.2 is separately approved and published.

### Local edit checks at this in-progress checkpoint

- `test_gui_layout` plus `test_release_regression`: 17/17 passed in the pinned
  Python 3.13.14 dependency environment.
- `CURRENT_STATE.json` and the canonical DemoData manifest parse as JSON;
  README English/Japanese alias byte parity and `git diff --check` passed.
- The focused packaging, public-source, release-identity, GUI-layout, and
  release-regression run passed 92/92 tests after the final DemoData ZIP/3MF
  hardening. The strict public-source preview staged 403 files and passed its
  manifest and privacy audits.
- The complete changed-working-tree regression passed on Python 3.13.14: 1,298
  tests in 384.281 seconds, 1,295 passed, three optional skips, and zero
  failures. This is not a completed r32.2 release gate; the exact-commit clean
  build, packaged/fresh-extracted smoke, complete corresponding-source stage,
  final archive, and checksum gates remain pending.

## 2026-08-25 experimental Flat Four / Large GLB / 2D colour workstream

- The owner approved publishing the source changes on a dedicated experimental
  branch and keeping them separate from the immutable Innovation Fund r32.2
  release. The intended branch is
  `codex/r32-2-experimental-flat4-large-glb-2d-filter`; do not merge or retag
  r32.2 as part of this workstream.
- The workstream combines three related beta features: a conditional reduced
  working-model path for supported static GLBs above the normal triangle
  ceiling, a fixed-front 2D Colour Filter (Cel Colour and Shaded Monochrome),
  and an area-weighted Flat Colour mode that proposes and exports exactly four
  physical F1-F4 colours without mixed recipes.
- Flat export projects dormant Full Spectrum face states to the nearest current
  F1-F4 only at the output boundary. It does not mutate saved Full Spectrum
  assignments. Manual F1-F4 edits and filament recommendations update the Flat
  preview immediately. Project schema v13 stores the new state and continues
  to read trusted v12 projects.
- Multipart solidification and part-specific 3MF output remain input-dependent
  beta behavior. The conditional large-GLB path remains fail-closed and does
  not claim support for arbitrary damaged, open, skinned, animated, or
  compressed models.
- Final local validation of the changed source completed 1,375 tests in
  379.271 seconds with zero failures and three optional skips. The one-folder
  Windows package passed its self-test and isolated Japanese and English UI
  smoke tests, and an independently extracted copy passed the same checks.
  `git diff --check`, archive path/CRC checks, file-by-file extraction parity,
  and privacy/content audits passed.
- Any GitHub binary test entry must remain a separate draft/experimental
  prerelease until an exact-commit clean rebuild supplies complete
  corresponding source, SBOM, binary component map, notices/relinking
  materials, checksums, and final fresh-extraction evidence. The published
  r32.2 tag and assets remain unchanged.
- Source commit `0d768fb6b3a0c68328b3c94b6ed48eff9a80ad13` was pushed to
  `codex/r32-2-experimental-flat4-large-glb-2d-filter` and tagged
  `v0.8beta-r32.2-experimental-20260825`. Draft PR
  [#7](https://github.com/Ponkichi0718/ChromaMatter/pull/7) is open.
- GitHub Draft Release ID `376019044` stores exactly two owner-review assets:
  a 117,533,412-byte experimental Windows ZIP and its detached checksum. GitHub
  reports the ZIP digest as
  `sha256:686823cdbc6c325b8b281e5820d0b73e9a8911d47b845b515c92a3ed565bbe56`.
  The Release remains both Draft and Pre-release, so it is not a public
  download. The published r32.2 Release remains non-draft with its original
  six assets.
- The exact tagged source commit completed 1,375 tests in 425.435 seconds with
  zero failures and three optional skips. A `git archive` public-tree audit
  passed for 409 files. No later code change was made; the follow-up branch
  commit only records GitHub draft metadata.

## 2026-08-25 Flat Four shadow/fill/Orca-mix correction checkpoint

### Current objective

Keep Flat Four physically limited to F1-F4 in Snapmaker Orca, recover strongly
chromatic armour colours that a dark baked GLB shadow had pulled into physical
black, and let Manual Fill repaint one visibly connected Flat colour region
without weakening Full Spectrum state preservation or export validation.

### Completed in this session

- Flat Four 3MF now stores all six automatic F1-F4 pair rows as Orca's own
  disabled/deleted tombstones. This prevents an enabled application-wide
  `auto_generate_gradients` preference from recreating the six 50/50 rows;
  the rows have no virtual filament IDs and no printable recipes.
- Added a generalized Flat-only chromatic-shadow recovery pass after ordinary
  CIE76 assignment. A face is reconsidered only after landing on an enabled
  neutral physical slot and only when its source RGB span, Lab chroma, and
  normalized-RGB distance retain clear chromatic evidence. Near-neutral black
  is excluded, and Full Spectrum does not enter this path.
- Manual Fill now uses the Flat preview's visible F1-F4 projection only for
  connectivity. Canonical mixed state IDs remain stored, Full Spectrum keeps
  its original boundaries, selected-part masks remain enforced, and the
  accelerated/adaptive paths preserve Undo/Redo.
- Cross-review also fixed capped-history adaptive Fill so one Undo restores the
  whole operation, made same-visible-colour Fill a complete no-op, and kept
  compatibility with older `connected_fill_faces` overrides when no Flat map
  is supplied. The shadow eligibility scan now uses the same fixed 25,000-face
  chunks as its distance pass instead of holding full-input temporary arrays.
- Read-only validation on an owner-supplied private high-face-count GLB
  confirmed the intended aggregate behavior: clearly chromatic shadowed
  regions recovered to an enabled chromatic physical slot, while near-neutral
  dark regions stayed on neutral slots. No asset name, path, hash, exact face
  count, colour-count breakdown, or derived output is recorded publicly.

### Current state

- The application and regression-test changes are committed as
  `0ed8dd404233752fec7b7f63fa13a2a9238e9b38` on
  `codex/r32-2-experimental-flat4-large-glb-2d-filter` and pushed for the
  cross-PC handoff. Draft PR #7 follows that branch automatically.
- No tag, Release edit, binary upload, Windows package replacement, or `main`
  merge was performed. The existing experimental tag/Draft Release assets and
  published r32.2 assets do not contain these corrections.
- Source-level focused and full regression are green. A newly generated Flat
  archive is also inspected by tests for four physical filament entries, zero
  active mixed recipes, exact deleted tombstones, and no printable state above
  F4.

### Next exact task

On the home PC, fetch and check out
`codex/r32-2-experimental-flat4-large-glb-2d-filter`, then continue from source
commit `0ed8dd404233752fec7b7f63fa13a2a9238e9b38` plus the following handoff
metadata commit. Make an exact-commit experimental clean build. In a fresh
extraction, load a newly exported Flat Four 3MF in Snapmaker Orca 2.3.5 and
visually confirm that Color Mixing shows no active mixed rows, the recovered
armour remains chromatic, and Manual Fill can repaint the connected dark-looking
region. Only after those checks should the experimental Draft Release asset be
replaced or promoted.

### Changed files

- `source/fixed_app/spectrum_mapper/engine.py`
- `source/fixed_app/spectrum_mapper/paint.py`
- `source/fixed_app/spectrum_mapper/paint_gui.py`
- `source/fixed_app/spectrum_mapper_hotfix.py`
- `source/fixed_app/smooth_paint_hotfix.py`
- `source/fixed_app/test_flat_chromatic_shadows.py`
- `source/fixed_app/test_flat_color_3mf.py`
- `source/fixed_app/test_flat_manual_paint.py`
- `source/fixed_app/test_hotfix.py`
- `CURRENT_STATE.json`
- `HANDOFF.md`

### Tests run

- Focused Flat Four, 3MF, paint/hotfix, part export, slicer-safety, output-black,
  and black-free-gradient regression: 152 tests, zero failures.
- Full changed-working-tree regression: 1,389 tests in 661.523 seconds, zero
  failures, three optional skips.
- `python -B -m compileall -q source/fixed_app`: PASS.
- `CURRENT_STATE.json` parse, `git diff --check`, and final worktree status are
  rechecked after this checkpoint edit.

### Do not do

- Do not weaken topology or 3MF fail-closed validation and do not restore Flat
  active mixed recipes merely to hide an Orca UI symptom.
- Do not apply the chromatic-shadow recovery path to Full Spectrum or infer a
  colour from neighbouring red faces alone; true black trim must remain black.
- Do not collapse canonical Full Spectrum paint IDs when filling a Flat view.
- Do not merge into `main`, retag r32.2, replace published assets, change
  `0.8beta`, or make further commits/pushes without a new explicit owner
  approval.

### Local-only files

- One owner-supplied private GLB was read only for aggregate colour-assignment
  validation. Its name, path, bytes, and derived preview remain local and must
  not be committed, packaged, or copied into public documentation.
- Local Python environments, temporary Orca source research, build folders,
  caches, and generated diagnostics remain outside the repository.

## 2026-08-25 Flat Four Fix2 owner-only Windows test ZIP

### Current objective

Give the owner a locally testable Windows ZIP whose application-source bytes
are now represented by the committed Flat Four mixed-row suppression,
chromatic-shadow recovery, and visible-state Manual Fill corrections, without
changing the published r32.2 Release or the experimental Draft Release.

### Completed in this session

- The first clean-build candidate correctly stopped at the fail-closed binary
  inventory. Its runtime contained the excluded historical PyTetWild wrapper,
  and PyInstaller had also resolved 40 UCRT/API-set binaries from a Windows
  Performance Toolkit PATH entry. No ZIP was created from that candidate.
- Verified the current published r32.2 complete corresponding-source ZIP against
  the GitHub Release API: 1,365,909,916 bytes and SHA-256
  `DCC7EC1AE74F4B790CCAC6B9B18286C7BDAB2829E779F0532E01708727680500`.
- Extracted only its unique repaired PyTetWild wheel and verified SHA-256
  `E3B11AC058266D277B0F83448C6023D5DA98E731D0D016E461DBCE4EBDFD613D`.
  The installed `PyfTetWildWrapper.pyd` is the approved
  `26A091B53279407014899C046691958C9DF07E22703576DA6A45D68A9BE22430`.
- Created a fresh exact Python 3.13.14 dependency environment and removed only
  the Windows Performance Toolkit entry from the clean-build process PATH.
  The spec and fail-closed inventory rules were not weakened.
- Built a new one-folder Windows application. The package has 1,455 files and
  256 native files; the binary compliance inventory passed with no UCRT/API-set
  payload and exactly one approved PyTetWild wrapper.
- Created the canonical owner-only archive
  `ChromaMatter-0.8beta-r32.2-Flat4-Fix2-INTERNAL-TEST-20260825-win64.zip`:
  117,486,407 bytes, 1,455 files, SHA-256
  `71E7A15A4B3793BB86B3B850D69900CF157E1CCA03FC032A27534B6D53C7E428`.
- Independently extracted the ZIP and confirmed exact relative-path, size, and
  SHA-256 parity for all 1,455 files. The fresh executable passed `--self-test`
  and isolated Japanese and English UI smoke tests. The archive contains zero
  OBJ/GLB/glTF/3MF payloads and zero pip `direct_url.json` files.

### Current state

- The owner-only test ZIP is in the local Downloads folder and is ready for
  hands-on testing.
- The source corrections are committed as
  `0ed8dd404233752fec7b7f63fa13a2a9238e9b38` and pushed on
  `codex/r32-2-experimental-flat4-large-glb-2d-filter`; Draft PR #7 now exposes
  that source for the home-PC handoff.
- No tag, Release edit, binary upload, package replacement, or publication was
  performed. The existing public r32.2 assets and experimental Draft Release
  assets remain unchanged.

### Next exact task

Extract the owner-only ZIP to a new folder and test the same representative GLB:

1. Select Flat Four and confirm the chromatic shoulder/armour shadow is assigned
   to the intended red physical slot while truly neutral black trim stays black.
2. Use Manual Fill on the connected dark-looking region, then verify Undo and
   Redo restore the whole fill as one operation.
3. Export a Flat Four 3MF and open it in Snapmaker Orca 2.3.5. Confirm only F1-F4
   are printable and Color Mixing contains no active six 50/50 pair rows.
4. Report screenshots plus the exact source model/output workflow if any result
   differs; keep the private model outside Git and public issue attachments.

### Changed files

- No additional application or packaging source file was changed to create the
  internal ZIP.
- `CURRENT_STATE.json`
- `HANDOFF.md`

### Tests run

- Exact repaired-PyTetWild environment full regression: 1,389 tests, zero
  failures, two optional skips.
- PyInstaller clean one-folder build: PASS.
- Built-package self-test and isolated Japanese/English UI smoke: PASS.
- Binary compliance inventory: PASS, 1,455 files and 256 native files.
- Canonical ZIP path/CRC/security/file-list validation: PASS.
- Independent fresh-extract relative-path, size, and SHA-256 parity for all
  1,455 files: PASS.
- Fresh-extracted self-test and isolated Japanese/English UI smoke: PASS.
- Package model-payload and pip direct-URL metadata checks: zero findings.

### Do not do

- Do not treat this owner-only archive as public Release evidence; it was built
  before the source checkpoint commit and has not been uploaded.
- Do not upload or replace Draft/Public Release assets until the owner finishes
  the requested Snapmaker Orca and visual model checks.
- Do not weaken topology, 3MF, binary-inventory, or archive fail-closed gates.
- Do not use the rejected historical-wrapper build or restore the Windows
  Performance Toolkit PATH entry during PyInstaller analysis.

### Local-only files

- The internal ZIP, clean/rejected build roots, independent extraction root,
  repaired-wheel extraction, isolated Python environment, and isolated UI-smoke
  profiles are local-only and remain outside Git.
- The owner-supplied private GLB and all outputs derived from it remain local and
  are not included in the ZIP.

## 2026-08-25 Flat Four file-open mode-history correction

### Current objective

Make a newly opened model's Flat Four result independent of whether Flat Four
or Full Spectrum happened to be selected when the file was opened, without
overwriting any later manual filament or palette decision.

### Completed in this session

- Traced the difference to the new-model automatic F1-F4 recommendation. Full
  Spectrum intentionally optimizes the four physical filaments while considering
  mixed states, whereas Flat Four intentionally optimizes against F1-F4 only.
  The old mode switch changed assignment mode but retained the proposal selected
  under the previous mode.
- Added runtime-only provenance for a complete new-model automatic palette. If
  every common/part palette still exactly matches that automatic result, changing
  modes reruns the recommendation under the target mode.
- The provenance comparison excludes only `color_mode`. It includes material,
  F1-F4, product snapshots, enabled states, display/print recipes, assignment
  snapshots, and correction controls. Any manual change or palette-inheritance
  change therefore prevents an automatic overwrite.
- New-file selection and project loading clear the runtime provenance. Saved
  projects continue to load exactly and are not treated as fresh automatic
  proposals.
- Added regressions for automatic Full-to-Flat recomputation, manual-filament
  preservation, a mode switch when no explicit part palette exists, same-source
  geometry reprocessing, and direct-Flat versus Full-then-Flat global/part
  F1-F4 equivalence.
- Added a compact stable-versus-experimental selector to all canonical English
  and Japanese repository README variants. It links published r32.2 to its
  Release and routes Flat Four users to Draft PR #7 and the source branch while
  stating that the workstream is intended for later integration.
- Created and pushed documentation-only branch
  `docs/experimental-version-navigation` at
  `5d87c790406ad3a80a7fd3e31c50bd2cee04bfd9` from `origin/main`, so the same
  selector can reach the default branch without merging application code.
- Opened documentation-only PR #8 from that branch to `main`:
  <https://github.com/Ponkichi0718/ChromaMatter/pull/8>.
- Updated Draft PR #7's title and body so it now separates stable r32.2 from the
  experimental source, links PR #8, lists the current Flat Four corrections and
  validation evidence, and states that no public experimental Windows ZIP exists:
  <https://github.com/Ponkichi0718/ChromaMatter/pull/7>.

### Current state

- The application correction is committed as
  `32b03438dbde322b3e2ff8b070356622d6999ad2` and pushed on
  `codex/r32-2-experimental-flat4-large-glb-2d-filter`; Draft PR #7 follows it.
- The application-plus-README checkpoint is
  `864c7a8db157f0bf2a7601c8123d89514bef8c88`; later commits on the same branch
  only record the GitHub handoff state. Draft PR #7 is open, remains Draft, was
  mergeable at the last GitHub readback, and now serves as the authoritative
  experimental status/testing hub.
- Documentation-only PR #8 is open and mergeable at the last GitHub readback.
  It contains one commit and changes only the five canonical README variants.
- No merge into `main`, tag, Release edit, Draft Release asset replacement,
  binary build, or ZIP replacement was performed.
- The existing Fix2 owner-only ZIP predates this correction and will still show
  the reported file-open mode-history behavior.

### Next exact task

Review and, when explicitly approved, merge documentation-only PR #8 so the
stable-versus-experimental selector appears on the default repository page.
Keep application PR #7 Draft until exact-current-HEAD regression, packaging and
compliance checks, Snapmaker Orca checks, and physical U1 validation are complete.
A later exact-commit clean owner-only Windows ZIP may be created for hands-on
validation of direct Flat versus Full-then-Flat and manual F-slot preservation.

### Changed files

- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/test_flat_color_mode.py`
- `source/fixed_app/test_filament_candidate_gui.py`
- `README.md`
- `README_EN.md`
- `README_JA.md`
- `README_PUBLIC_EN.md`
- `README_PUBLIC_JA.md`
- `CURRENT_STATE.json`
- `HANDOFF.md`

### Tests run

- Repository pinned environment focused regression: 177 tests, zero failures.
- Earlier focused subsets: 42 and 41 tests, zero failures.
- `python -m py_compile` for the changed application/test modules: PASS.
- Documentation-only branch release-identity tests: 12 tests, zero failures.
- Canonical English/Japanese README parity checks: PASS.
- `CURRENT_STATE.json` parse and final `git diff --check`: PASS.
- GitHub readback after public PR metadata publication: PR #7 was
  open/Draft/unmerged at application-plus-README checkpoint `864c7a8`; PR #8
  was open/non-Draft/unmerged with docs HEAD `5d87c79`; both reported mergeable
  at that readback. Subsequent PR #7 commits are handoff metadata only.
- One initial system-Python attempt could not import PyMeshLab. It was an
  environment miss, not a test failure, and was superseded by the repository's
  pinned `.venv` run above.

### Do not do

- Do not make the mode switch always replace F1-F4. The exact automatic-palette
  guard is required to preserve user-selected filaments, recipes, enabled states,
  output ratios, product identities, and part inheritance.
- Do not persist this runtime provenance into project JSON. Project loading must
  continue to preserve the saved palette rather than silently recomputing it.
- Do not weaken topology, 3MF, pending-apply, or Flat Four mixed-state guards.
- Do not merge either PR into `main`, change `0.8beta`, retag, publish a binary,
  or replace a Release asset without fresh explicit owner approval.

### Local-only files

- Existing owner-only ZIPs, private test models, generated outputs, build roots,
  caches, and local environments remain outside Git and public documentation.

## 2026-08-25 Flat Four Test 2 public prerelease

### Outcome

- Published the separate experimental prerelease
  [`v0.8beta-r32.2-flat4-test2`](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2-flat4-test2)
  as GitHub Release ID `376367877`. It is non-Draft and marked Pre-release.
- The annotated tag peels to exact source commit
  `32769037a9173537beeb8574471f4ec9c040c214`. The latest application change in
  that history is the mode-independent automatic Flat Four proposal at
  `32b03438dbde322b3e2ff8b070356622d6999ad2`; the later commits are handoff and
  navigation documentation only.
- The stable `v0.8beta-r32.2` tag, Release, and all six stable assets were left
  unchanged. The older private experimental Draft Release ID `376019044` and
  its Fix1 review assets were not moved, replaced, or promoted.

### Public assets and frozen identities

- `ChromaMatter-0.8beta-r32.2-flat4-test2-win64.zip`: 115,071,442 bytes,
  SHA-256 `B367C0D04EAD74FB3C58A01F8EFA89CD70642C8FF013AA65533D9D86B76467F5`.
- `ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip`:
  1,366,000,690 bytes,
  SHA-256 `B94FBAEB9DCEC170EE356E266BD06FBAE66798FC7039E56AC17BCB872B848686`.
- `ChromaMatter-0.8beta-r32.2-flat4-test2-SBOM.cdx.json`: 937,715 bytes,
  SHA-256 `B68B2EE6BDFF9A80B9630F628284D13C67E662BAA3AE572AC1A0A70C040E03FD`.
- `ChromaMatter-0.8beta-r32.2-flat4-test2-BINARY_COMPONENT_MAP.json`:
  526,076 bytes,
  SHA-256 `21A1A028F1F3205DA537636843101F3D8C0CC4CDA37DC75FCB4CEC9B28D1F865`.
- `SHA256SUMS-r32.2-flat4-test2.txt`: 492 bytes,
  SHA-256 `2A264D1D9675FD8E19FD1D2BD138C923244CB4B83EEDB222100FC328D85A443C`.

### Validation

- Exact-current-commit full regression and clean one-folder build: PASS.
- Built-package self-test and isolated Japanese/English UI smoke: PASS.
- Binary compliance inventory: PASS for 1,455 runtime files and 256 native
  files.
- Public software staging, canonical archive checks, privacy checks, and
  independent fresh extraction: PASS. The fresh package has 1,512 files and a
  1,511-record manifest; path, size, and SHA-256 parity all passed, followed by
  fresh self-test and Japanese/English UI smoke.
- Complete corresponding source: `release-approved`, `known_gaps: []`, and
  bound to commit `32769037a9173537beeb8574471f4ec9c040c214`. Independent fresh
  extraction verified 42,814 files against 42,813 manifest records.
- GitHub reported the same size and digest for all five uploaded assets. After
  publication, all five were downloaded again without authentication and each
  local size/SHA-256 matched exactly.
- Post-publication release-identity, GUI-layout, and release-regression focused
  set: 29 tests passed with zero failures.
- `CURRENT_STATE.json` parse, canonical English/Japanese README byte parity,
  and `git diff --check`: PASS after adding the public download navigation.

### User path and current limitations

- Windows direct download:
  <https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2-flat4-test2/ChromaMatter-0.8beta-r32.2-flat4-test2-win64.zip>
- Users must extract the complete ZIP before running `START_CHROMAMATTER.cmd`
  or `ChromaMatter.exe`.
- The Release is intentionally experimental and unsigned. Multipart
  solidification and part-specific 3MF output remain input-dependent and can
  fail. Large GLB handling remains a narrow fail-closed beta path; the 2D
  Colour Filter is not line-art generation or a PBR renderer. Physical U1
  validation of this exact test package remains pending.

### Follow-up state

- The five canonical README variants now link directly to Flat Four Test 2 in
  the current experimental branch working tree. Commit and push this
  documentation/state checkpoint, then update Draft PR #7 to point to the
  Release and Windows direct download.
- Keep Draft PR #7 unmerged until the experimental application is ready for
  normal-version integration. Do not move the Flat Four Test 2 tag or replace
  its five frozen assets; later test builds require a new tag and Release.
- Keep build roots, fresh-extraction roots, complete-source caches, controlled
  toolchain evidence, and private owner models outside Git.

## 2026-08-26 Flat Four Test 3 eye-white / skin-highlight publication candidate

### Outcome

- Added a Flat-Four-only, topology-aware correction that conservatively absorbs
  small baked white/gray lighting islands on smooth skin or material surfaces
  into the surrounding chromatic physical slot.
- White was not removed globally. Small intentional white details, including eye
  whites next to dark linework, remain white targets rather than being absorbed
  as highlights. Black detail is also retained.
- Retained white reserves a suitable near-white physical filament only when it
  covers at least 0.01% of total printable area. Below 0.01%, white remains an
  unabsorbed target but does not by itself force a white spool and can map to the
  nearest selected F1-F4 colour.
- Flat Four still keeps four physical F1-F4 slots and 3MF schema/state metadata.
  When no intentional white remains, an output may effectively use only three
  paint IDs. Manual paint remains authoritative; Full Spectrum behavior is
  unchanged.
- The classifier fails closed at part boundaries, hard creases, broad or
  disconnected white regions, ambiguous topology, and large unsupported open
  meshes. A model above 500,000 faces without reusable adjacency skips only this
  automatic highlight correction; the remaining Flat Four pipeline continues.

### Validation

- Candidate working-tree preflight regression: 1,431 tests in 398.127 seconds, zero
  failures and three optional skips. Focused 60-test and broader 244-test sets,
  `py_compile`, and `git diff --check`: PASS.
- `face_neighbors_partial` on a 498,002-face grid improved from 7.01 seconds to
  0.091 seconds with the same 1,996 open slots; 1,000 randomized/degenerate
  comparisons matched the former implementation byte-for-byte. Three-million-
  face helper probes reduced transient memory from 163.1 MiB to 1.0 MiB and from
  91.6 MiB to 4.6 MiB.
- Clean one-folder build, packaged self-test, isolated Japanese/English UI smoke,
  and fail-closed binary inventory: PASS for 1,455 runtime files and 256 native
  files.
- Created local owner-only archive
  `ChromaMatter-0.8beta-r32.2-Flat4-Highlights-INTERNAL-TEST-20260825-win64.zip`:
  117,524,346 bytes, 1,457 files, SHA-256
  `0508BC6ACF082FE766F1E4054DBDB82FC999E9E4090A98F18DEBF0F701176F8C`.
- Canonical ZIP path/CRC/security/file-list validation, independent fresh-extract
  path/size/SHA-256 parity, fresh self-test, Japanese/English UI smoke, privacy
  audit, and pip `direct_url.json` audit: PASS. Private model payloads and actual
  pip direct-URL metadata were both zero.

### Current state and limitation

- The validated behavior and its publication documentation are now designated
  the **Flat Four Test 3 publication candidate** on
  `codex/r32-2-experimental-flat4-large-glb-2d-filter`. The commit containing
  this record is the candidate source checkpoint once created; its tag, public
  artifacts, and publication verification are still pending. Stable r32.2 and
  the published Flat Four Test 2 prerelease remain unchanged.
- Planned tag and Windows asset are `v0.8beta-r32.2-flat4-test3` and
  `ChromaMatter-0.8beta-r32.2-flat4-test3-win64.zip`. The matching planned
  compliance assets are the complete corresponding source, Test 3 SBOM, binary
  component map, and `SHA256SUMS-r32.2-flat4-test3.txt`. The Test 3 Windows
  package intentionally contains no `DemoData`.
- A tiny white patch smoothly enclosed only by one skin/tan surface, with no dark
  edge, crease, or part boundary, is semantically indistinguishable from a baked
  highlight and may be absorbed. This is not semantic recognition. Paint
  intentional white manually when needed; manual white overrides remain
  authoritative.
- Physical-printer validation of the exact Test 3 package is pending. The
  owner-only Highlights ZIP is preflight evidence only and must not be uploaded
  or renamed into the public Test 3 asset.
- Canonical root README links remain on the published Test 2 channel at this
  source-candidate stage. Update them to Test 3 only after the new Release and
  direct-download URLs exist and have been verified.
- The ZIP, build/fresh-extraction roots, caches, private models, and generated
  outputs remain local-only and outside Git.

### Remaining publication gates

1. Use the dedicated candidate source checkpoint without private models,
   binaries, build output, caches, or personal paths, then rerun its exact full
   regression and release identity/documentation checks.
2. Clean-build that commit and regenerate the release-approved complete
   corresponding source, SBOM, binary component map, software package, and
   detached checksum record with the final Test 3 source-offer URL.
3. Pass package/archive/privacy/path/CRC/hash parity, packaged and independent
   fresh-extract self-test, and isolated Japanese/English UI smoke.
4. Publish all five assets together under the new Test 3 prerelease tag, then
   download each without authentication and verify its size and SHA-256.
5. Only after those gates pass, update `CURRENT_STATE.json`, this handoff, the
   canonical root README set, and Draft PR #7 with the frozen Test 3 identities.

### Candidate documentation changed

- `publication/RELEASE_NOTES_r32.2_FLAT4_TEST3_20260826.md`
- `source/fixed_app/public_binary/README_EN.md`
- `source/fixed_app/public_binary/README_JA.md`
- `source/fixed_app/README_fixed_en.md`
- `source/fixed_app/README_fixed_ja.md`
- `FEATURES_EN.md`
- `FEATURES_JA.md`
- `CURRENT_STATE.json`
- `HANDOFF.md`

### Do not do

- Do not replace the stable r32.2 or Flat Four Test 2 tags or assets, and do not
  publish Test 3 from the owner-only ZIP.
- Do not claim Test 3 publication eligibility from the working-tree/owner-only
  preflight; the exact committed and staged public bytes require new gates.
- Do not add DemoData, private models, derived private 3MF files, or local build
  evidence to the Test 3 software package or Git tree.

## 2026-08-26 Flat Four Test 3 published prerelease

This section supersedes the pending-publication status above while preserving
that section as the candidate/preflight record.

### Frozen public identity

- Published GitHub prerelease:
  <https://github.com/Ponkichi0718/ChromaMatter/releases/tag/v0.8beta-r32.2-flat4-test3>
- Release ID: `376762493`
- Exact tag/source commit: `v0.8beta-r32.2-flat4-test3` /
  `beddc110922fdccc4a8c48def286014ad23cd0ed`
- Published at: `2026-08-25T22:51:42Z` (`2026-08-26` JST)
- Windows direct download:
  <https://github.com/Ponkichi0718/ChromaMatter/releases/download/v0.8beta-r32.2-flat4-test3/ChromaMatter-0.8beta-r32.2-flat4-test3-win64.zip>
- The Test 3 Windows package intentionally contains no `DemoData`.

### Exact release validation

- The exact-tag full regression passed 1,431 tests in 386.390 seconds with zero
  failures and two optional skips. The exact `BUILD_AND_TEST` rerun passed in
  382.567 seconds with the same two optional skips.
- Keep this distinct from the earlier working-tree preflight: 1,431 tests in
  398.127 seconds with three optional skips. That remains valid historical
  evidence but is not the exact Release result.
- Exact clean build, corresponding-source/compliance staging, packaged checks,
  archive/privacy checks, and detached checksum verification: PASS.
- After publication, all five assets were downloaded again without
  authentication. Every asset matched its frozen byte size and SHA-256.
- The published Windows ZIP was independently fresh-extracted. Its packaged
  self-test and isolated Japanese/English UI smokes passed.

### Frozen five-asset set

- `ChromaMatter-0.8beta-r32.2-flat4-test3-win64.zip`: 115,090,746 bytes,
  SHA-256 `C1B83936AE832EFD985951B0973143E4771B1F1FFF9C7F07ADFF9AF0EE0EB239`
- `ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip`:
  1,366,029,816 bytes, SHA-256
  `A9AE90820D54ED7A9F63ACE2D8915920AE4CBFA496A3256BE2525F06E73ED8EA`
- `ChromaMatter-0.8beta-r32.2-flat4-test3-SBOM.cdx.json`: 937,715 bytes,
  SHA-256 `F50399614D5D70F1528EB02240639341924980A0404A31284DF1771834C1F45F`
- `ChromaMatter-0.8beta-r32.2-flat4-test3-BINARY_COMPONENT_MAP.json`:
  526,076 bytes, SHA-256
  `A1D4A5B0A2C35D243645E00725D3637E60F0CC92F5B34EA8ED1221054C7F5624`
- `SHA256SUMS-r32.2-flat4-test3.txt`: 492 bytes, SHA-256
  `2A5BF037474550EC57166A078BE215F5B80C92BED9771FFB094E76266C8CA1F8`

### Public navigation and remaining limits

- The five canonical root README variants now keep stable r32.2 first and
  preferred, while selecting Flat Four Test 3 as the current experimental
  channel with the verified direct Windows ZIP and Release links. English and
  Japanese aliases must remain byte-identical within their language groups.
- Documentation-only PR #8 was squash-merged into `main` as
  `c5032db5af1bdb678b656493080d9061f49af78a`; its reviewed navigation source was
  Test 3 commit `9d4eb1202cb07a8438fc7e53e05889d2e09ac08c`.
- Flat Four Test 2 remains frozen historical prerelease evidence. Do not move
  its tag or replace its five assets.
- Test 3 does not remove white globally. It preserves eye whites conservatively
  and absorbs only small, high-confidence baked white/gray highlights on smooth
  chromatic surfaces. It is topology-based, not semantic recognition; a small
  intentional white patch can still be misclassified, so manual paint remains
  authoritative.
- Retained white below 0.01% does not force a white spool, all four F1-F4 slots
  remain in the schema, and an output may effectively use only three paint IDs.
  Full Spectrum remains unchanged.
- On an open mesh above 500,000 faces without reusable adjacency, only the
  automatic highlight correction skips fail-closed. Multipart solidification
  and part-specific 3MF remain input-dependent beta features.
- Physical-printer validation of this exact Test 3 package remains pending.
  Do not imply that the successful software/package gates prove a physical
  colour result or compatibility with every multipart model.

## 2026-08-26 default-branch Flat Four Test 3 download navigation

### Current objective

Make the already published Flat Four Test 3 Windows package discoverable from
the default `main` README without merging the experimental application branch
or placing binary/archive bytes in Git history.

### Completed in this session

- Fetched and inspected the home-PC publication commits. Confirmed that the
  white/gray highlight correction is exact tagged source commit
  `beddc110922fdccc4a8c48def286014ad23cd0ed` and that the public Test 3 Release
  links that commit.
- Confirmed the anonymous direct Windows download returns HTTP 200 and reports
  the frozen 115,090,746-byte asset size.
- Fast-forwarded the local documentation worktree to reviewed PR #8 head
  `9d4eb1202cb07a8438fc7e53e05889d2e09ac08c` and revalidated its five-README
  scope.
- With explicit owner approval, squash-merged documentation-only PR #8 into
  `main` as `c5032db5af1bdb678b656493080d9061f49af78a`.
- Confirmed from GitHub and `origin/main` that the default README now shows
  stable r32.2 first and provides the Flat Four Test 3 direct ZIP, Release, and
  Draft PR #7 links.

### Current state

- `main` now exposes both download choices. Stable r32.2 remains the recommended
  Full Spectrum build; Flat Four Test 3 remains a separate unsigned public
  experimental prerelease.
- Draft application PR #7 remains open, Draft, mergeable at the final readback,
  and unmerged. Its application code was not merged into `main`.
- The Test 3 tag and all five frozen Release assets were not moved, replaced, or
  rebuilt during this session.

### Next exact task

Use the main README or the Test 3 Release for owner testing in Snapmaker Orca
and on a small physical print. Keep PR #7 Draft until the experimental behavior
is ready for normal-version integration.

### Changed files

- `CURRENT_STATE.json`
- `HANDOFF.md`

### Tests run

- Documentation branch `source.fixed_app.test_release_identity`: 12 tests,
  zero failures.
- Canonical English/Japanese README byte parity: PASS.
- Anonymous Test 3 Windows direct-download HEAD request: HTTP 200; content
  length 115,090,746 bytes.
- PR #8 final GitHub readback: merged, non-Draft, head `9d4eb12`, merge commit
  `c5032db`; `origin/main` contains the Test 3 links.
- `CURRENT_STATE.json` parse and `git diff --check`: PASS.

### Do not do

- Do not merge Draft PR #7 merely because the download navigation is now on
  `main`; application integration remains a separate validation decision.
- Do not commit Release ZIPs or other binary archives to a branch. Keep public
  binaries as immutable Release assets and link them from source documentation.
- Do not move or replace the stable r32.2, Flat Four Test 2, or Flat Four Test 3
  tags/assets.

### Local-only files

- Private models, generated 3MF files, build roots, caches, local environments,
  and owner-only archives remain outside Git.

## 2026-08-26 Apple Silicon macOS 15+ separate alpha source port

### Current objective

Port the current ChromaMatter source to a clearly separate Apple Silicon macOS
15+ alpha without changing the published Windows releases, weakening topology
or 3MF fail-closed validation, or implying that a Mac build has already been
tested on hardware.

### Completed in this session

- Created local branch `codex/macos-arm64-flat4-test3` from exact source commit
  `9c7be309bc2a8268d0fa9a4a0c63ad444759120d`.
- Added a shared platform runtime for the macOS Application Support directory,
  Finder folder opening, Snapmaker Orca discovery/launch, and a manual
  Snapmaker Orca `Open as project` fallback. The existing Windows settings path
  and launch behavior remain intact.
- Made PyTetWild wrapper discovery understand the packaged macOS `.so` and
  `.dylibs` layout as well as the existing Windows `.pyd` and DLL layout.
- Added a strict hidden macOS alpha self-test. It requires Darwin arm64 and
  executes a real PyTetWild tetrahedralization, the required PyMeshLab filters,
  and a real ModernGL OpenGL 3.3 framebuffer draw/read in both source and
  packaged-app gates.
- Added a separate PyInstaller app spec, exact hash-locked Apple Silicon wheel
  set, macOS build script, fail-closed bundle/native audit, Japanese/English
  compliance notices, volunteer testing guides, and a structured private-data-
  safe issue form.
- Added a `macos-15` GitHub Actions workflow using CPython 3.13.14 arm64.
  Ordinary push and pull-request runs upload diagnostics only.
- Added a deliberately closed external-tester gate. A tester ZIP cannot be
  uploaded unless the exact commit is approved and the macOS binary component
  map, SPDX SBOM, corresponding-source manifest, relinking documents, source
  status, and bilingual notices all pass.
- Kept the in-app display version at `0.8beta`; the Apple bundle uses numeric
  version `0.8.0`, alpha bundle identifier
  `io.github.ponkichi0718.chromamatter.alpha`, ad-hoc signing, and no Developer
  ID signing or Apple notarization.

### Current state

- The source-level port and Windows-hosted validation are complete locally.
  No macOS app, ZIP, GitHub artifact, commit, push, or Release was created.
- A Mac host is not available in this environment. The first real app build,
  native-library audit, OpenGL check, and Japanese/English packaged UI smoke
  therefore remain pending for GitHub Actions on `macos-15`.
- The volunteer testing route is prepared in documentation and CI, but binary
  distribution remains fail-closed because macOS-specific compliance evidence
  is not complete.
- Published Windows stable r32.2 and Flat Four Test assets are unchanged.

### Next exact task

After explicit owner approval, commit and push
`codex/macos-arm64-flat4-test3`. Let the normal diagnostics-only macOS workflow
perform the first build, inspect every uploaded diagnostic, and fix any Mac-only
failure. Do not run the opt-in tester upload until all compliance evidence files
exist, are reviewed for the exact commit, and the gate passes without overrides.

### Changed files

- Runtime and application:
  `source/fixed_app/TripoSpectrumMapper_fixed.py`,
  `source/fixed_app/spectrum_mapper/platform_runtime.py`,
  `source/fixed_app/spectrum_mapper/cli.py`,
  `source/fixed_app/spectrum_mapper/gui.py`,
  `source/fixed_app/spectrum_mapper/calibration_chart.py`,
  `source/fixed_app/spectrum_mapper/i18n.py`,
  `source/fixed_app/spectrum_mapper/owned_filaments.py`,
  `source/fixed_app/spectrum_mapper/renderer.py`,
  `source/fixed_app/spectrum_mapper/volume_partition.py`, and
  `source/fixed_app/spectrum_mapper_hotfix.py`.
- macOS packaging and CI:
  `source/fixed_app/TripoSpectrumMapper_macos_arm64.spec`,
  `source/fixed_app/requirements-build-macos-arm64.lock`,
  `BUILD_MACOS_ARM64.sh`, `AUDIT_MACOS_APP.sh`,
  `.github/workflows/macos-arm64-alpha.yml`, and `.gitignore`.
- Tests:
  `source/fixed_app/test_platform_runtime.py`,
  `source/fixed_app/test_macos_alpha_cli.py`,
  `source/fixed_app/test_macos_packaging.py`, and
  `source/fixed_app/test_calibration_chart_gui.py`.
- Tester/compliance guidance:
  `.github/ISSUE_TEMPLATE/macos_alpha_report.yml`,
  `publication/MACOS_ALPHA_TESTING_EN.md`,
  `publication/MACOS_ALPHA_TESTING_JA.md`,
  `licenses/MACOS_ALPHA_COMPLIANCE_NOTICE_EN.txt`, and
  `licenses/MACOS_ALPHA_COMPLIANCE_NOTICE_JA.txt`.
- State records: `CURRENT_STATE.json` and `HANDOFF.md`.

### Tests run

- Exact-current Windows full regression after all Mac port, gate, packaging,
  and handoff changes: 1,463 tests in 702.607 seconds, zero failures, two
  optional skips.
- Final targeted runtime, native-gate, packaging, i18n, release-identity, and
  packaged-language suite: 58 tests in 3.398 seconds, zero failures.
- Windows source visible-window UI smoke: Japanese and English both passed.
- macOS lock dry-run for macOS 15 arm64, CPython 3.13/`cp313`/`abi3`: all 23
  exact hashed wheels resolved; no source distribution was selected.
- `bash -n` for both macOS scripts, Python `py_compile`, workflow and issue-form
  YAML parsing, `CURRENT_STATE.json` parsing, and `git diff --check`: passed.
- Actual Mac app build and packaged execution: not run; no Mac host is present.

### Do not do

- Do not merge this alpha branch into `main` or modify the published Windows
  releases merely to expose an unverified Mac build.
- Do not weaken the existing topology, closed-solid, or 3MF fail-closed gates
  to make a Mac CI run pass.
- Do not enable external tester ZIP upload by setting repository variables
  alone. The exact-commit approval and every reviewed compliance evidence file
  must also pass the workflow gate.
- Do not call the app Developer ID signed, notarized, generally supported, or
  physically validated.
- Do not commit private models, generated 3MF/toolpath files, local build roots,
  caches, environments, or binary archives.

### Local-only files

- `.venv`, caches, private models, generated output, and future Mac build roots
  remain local-only and outside Git.
- During an earlier packaging cleanup, the ignored local `build_output/`
  directory was removed in full instead of only its intended temporary child.
  No tracked source was removed and the current changes are intact, but any
  older generated artifacts that existed there are not recoverable from Git.
- No Mac `.app` or tester ZIP exists locally.

## 2026-08-26 macOS volunteer test path and public fixture

### Current objective

Make the separate Apple Silicon macOS alpha easy for a first-time volunteer to
download safely, test in about ten minutes, and report without sharing a
private model, while retaining the exact-commit compliance and fail-closed 3MF
distribution gates.

### Completed in this session

- Enabled GitHub Discussions and created the English macOS testing board at
  `https://github.com/Ponkichi0718/ChromaMatter/discussions/9`.
- Reworked the English tester guide around current availability, exact approved
  build identity, checksum verification, Finder first launch, a required
  ten-minute checklist, known limitations, diagnostics, privacy, and clear
  Discussion-versus-Issue reporting.
- Reworked the macOS Issue form to collect workflow/artifact identity, Mac
  hardware, Pass/Fail/Not-tested results, exact reproduction, fail-closed 3MF
  behavior, Orca details, and sanitized self-test evidence.
- Added README routes for the separate Mac alpha without presenting an
  unapproved download as available.
- Added a deterministic CC0 test-model generator. The generated static GLB has
  32 vertices, 48 triangles, four positive-volume watertight boxes, exact red,
  blue, white, and black normalized `COLOR_0`, and no texture, brand, character,
  AI-generated asset, external URI, or private metadata. The binary is generated
  only during approved tester staging and is not committed.
- Added a human-readable GitHub Actions job summary that distinguishes the
  diagnostics artifact from a real tester ZIP and records the exact commit,
  artifact name, SHA-256, seven-day retention, guide, board, and Issue route.

### Current state

- Discussions is live, but this branch and its documentation/Issue form are not
  pushed yet, and the main README does not yet show the Mac route.
- There is no approved Mac application download. Ordinary CI is diagnostics
  only; tester ZIP creation remains blocked by the exact-commit macOS compliance
  evidence gate.
- No real Apple Silicon build or packaged execution has run yet.

### Next exact task

Commit and push `codex/macos-arm64-flat4-test3`, start the first `macos-15`
diagnostics build through its pull request, inspect the run and fix Mac-only
failures. Keep Discussion #9 marked as no-download until an exact build passes
and the macOS distribution evidence is complete. Expose the guide from `main`
through a documentation-only PR; do not merge the Mac application branch into
`main` merely to create the navigation.

### Changed files

- Mac source, package, CI, and tests listed in the preceding macOS handoff.
- Tester UX: `README.md`, `README_EN.md`, `README_PUBLIC_EN.md`,
  `README_JA.md`, `README_PUBLIC_JA.md`,
  `publication/MACOS_ALPHA_TESTING_EN.md`,
  `publication/MACOS_ALPHA_HUB_EN.md`,
  `.github/ISSUE_TEMPLATE/config.yml`, and
  `.github/ISSUE_TEMPLATE/macos_alpha_report.yml`.
- Public fixture: `samples/generate_macos_alpha_test_glb.py`,
  `samples/MACOS_ALPHA_TEST_MODEL_README.md`, `samples/LICENSE.txt`,
  `samples/README_JA.md`, and `source/fixed_app/test_public_macos_glb.py`.
- State: `CURRENT_STATE.json` and `HANDOFF.md`.

### Tests run

- Current tester/package/runtime/release focused suite: 49 tests, zero
  failures.
- Public GLB checks include byte identity, static embedded structure, four exact
  colours, zero boundary/non-manifold edges, four positive watertight bodies,
  existing loader/preflight compatibility, and staging-only generation.
- Workflow and Issue YAML parse: PASS.
- `bash -n` for both Mac scripts, Python compile, README canonical parity tests,
  and `git diff --check`: PASS.
- The preceding exact-current full regression remains valid for the application
  changes; a final full regression will run while the first Mac CI is active.

### Do not do

- Do not call the diagnostics artifact an app or direct testers to it.
- Do not post an approved download in Discussion #9 until the exact Mac build,
  native audit, self-test, UI smoke, and compliance gate all pass.
- Do not commit the generated GLB binary, an `.app`, ZIP, private model, or
  generated 3MF.
- Do not weaken topology, Solidify, or 3MF fail-closed behavior for a CI pass.

### Local-only files

- Local environments, caches, generated GLB copies, Mac build roots, app
  bundles, diagnostics downloads, and tester ZIPs remain outside Git.

## 2026-08-26 first Apple Silicon CI diagnosis

### Current objective

Carry the first real `macos-15` run through packaging without hiding a Mac app
defect or weakening Windows, topology, or 3MF coverage.

### Completed in this session

- Pushed commit `748c05b5d3faaa1987a67ccd1e73b824a5fde44d` and ran
  `https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32938795209`.
- Confirmed on a real Apple Silicon runner that CPython 3.13.14 arm64, all 23
  hash-locked wheels, PyTetWild tetrahedralization, required PyMeshLab filters,
  and ModernGL framebuffer draw/read pass.
- Identified all 10 failures and one error as test portability assumptions:
  Windows modifier masks and Win32 ABI, macOS `/tmp` canonicalization, Aqua
  window clamping, canvas-coordinate rounding, a non-Mac rejection subprocess,
  and a 1.35e-6 ARM64 Delta-E round-off.
- Preserved the behavior coverage by explicitly emulating Windows for the two
  Windows modifier tests, using neutral ordinary-button states elsewhere,
  selecting real accepted canvas pixels, retaining exact Windows layout tests,
  retaining a live positive-size Aqua layout test, and isolating preferences
  with the cross-platform data-directory override.
- Updated Discussion #9 with the accurate no-download first-run status.

### Current state

- The first run did not reach PyInstaller and created diagnostics only. No Mac
  app or tester ZIP was exposed.
- Portability fixes are implemented locally and pass their 11 exact regression
  targets; the full 43-test hotfix module also passes.
- Windows exact commit `748c05b` passed 1,468 tests in 697.983 seconds with two
  optional skips before these test-only portability refinements.

### Next exact task

Commit and push the portability fixes, then follow the automatically triggered
Mac run. If packaging passes, inspect the app audit, packaged native/render
self-test, and Japanese/English UI smoke. Do not request a tester ZIP yet.

### Changed files

- `source/fixed_app/test_hotfix.py`
- `source/fixed_app/test_extended_palette.py`
- `source/fixed_app/test_gui_integration.py`
- `source/fixed_app/test_macos_alpha_cli.py`
- `source/fixed_app/test_manual_paint_r25.py`
- `source/fixed_app/test_new_obj_defaults.py`
- `source/fixed_app/test_pen_pressure.py`
- `source/fixed_app/test_platform_runtime.py`
- `publication/MACOS_ALPHA_HUB_EN.md`
- `CURRENT_STATE.json` and `HANDOFF.md`

### Tests run

- Exact 11 first-run failure targets: 11 passed.
- Entire `source.fixed_app.test_hotfix` module: 43 passed.
- Exact commit `748c05b` Windows full suite: 1,468 passed with two optional
  skips and zero failures.

### Do not do

- Do not remove broad test modules from the Mac runner to make it green.
- Do not interpret the first CI failure as a native-library failure; the strict
  native/render gate passed before the portable source suite stopped.
- Do not distribute the diagnostics artifact or request the gated tester ZIP.

### Local-only files

- Downloaded CI logs and diagnostics remain in a unique temporary directory and
  are not Git inputs or package payloads.

## 2026-08-26 macOS technical CI success and distribution hold (current)

### Current objective

Keep the first macOS volunteer path simple and public-facing while completing
the exact native source/relink evidence required before an external tester ZIP
can be approved.

### Completed in this session

- The volunteer route is the English guide, Discussion #9, and the dedicated
  macOS Issue form. The first approved kit will use the deterministic CC0
  four-box GLB and the 10-minute checklist; no private or complex model is
  needed.
- Apple Silicon technical CI run
  <https://github.com/Ponkichi0718/ChromaMatter/actions/runs/32947038458>
  succeeded from exact source commit
  `9404926a6aadbb918ade7855f4141e263c3aafba`.
- Source tests, native probes, app packaging, packaged native/rendering
  self-test, and Japanese/English UI smoke passed. The run uploaded diagnostics
  only; all tester ZIP steps remained skipped.
- The deterministic app inventory recorded 859 regular files, 207 symlinks,
  317 arm64 Mach-O files, and 20 packaged Python distributions. Its SHA-256 is
  `59113A39C8C7BACB566DD3D23E8374CA56973F1D6DB3A472FDDFBF0EAEE45D22`.
- The fail-closed source-coverage audit maps all 317 Mach-O files uniquely and
  reports 253 with unresolved source/build/relink evidence. Its SHA-256 is
  `73907E2E4C5C95E5893F995E7FC74C557DF57E79A7E6131F80021F2545720DAB`;
  `engineering_gate_passed=false` and `legal_conclusion=false`.
- Automatic Mac CI now runs once for a relevant source-branch push. The
  redundant pull-request event was removed because it rebuilt the same exact
  head for documentation-only PR synchronization events.
- Draft PR #12 remains the separate macOS source/review workspace and is not a
  tester download.

### Current state

- The Apple Silicon `.app` builds and passes the technical CI gate on macOS
  15.7.7 arm64 with CPython 3.13.14.
- There is no approved macOS tester download. A `diagnostics` artifact is not
  the application and must not be given to testers.
- External tester distribution remains blocked by the 253 unresolved native
  source/build/relink closures. The audit cannot create a complete source stage
  while any gap remains and cannot make a legal approval decision.
- This section supersedes the earlier statements that no real Mac app build had
  completed or that the next technical CI run was pending. The first failed run
  remains above as historical diagnosis.

### Next exact task

Resolve and review the 253 source/build/relink closures, generate the
exact-commit corresponding-source evidence, obtain explicit owner approval,
and rerun the fail-closed tester-distribution gate. Keep Discussion #9 in
no-download status and PR #12 as Draft until those steps pass.

### Changed files

- `.github/workflows/macos-arm64-alpha.yml`
- `.gitignore`
- `tooling/audit_macos_source_coverage.py`
- `tooling/macos_source_coverage_plan.json`
- `tooling/stage_macos_corresponding_source.py`
- `source/fixed_app/test_macos_source_coverage.py`
- `source/fixed_app/test_macos_packaging.py`
- `README.md`, `README_EN.md`, and `README_PUBLIC_EN.md`
- `publication/MACOS_ALPHA_TESTING_EN.md`
- `publication/MACOS_ALPHA_HUB_EN.md`
- `CURRENT_STATE.json` and `HANDOFF.md`

### Tests run

- Full Windows regression: 1,478 tests passed with two optional skips and zero
  failures in 686.573 seconds.
- Hardened app-inventory/compliance/source-coverage/packaging suite: 35 passed.
- Exact-source checkout/recording follow-up: 26 focused tests passed.
- Independent adversarial review confirmed input/output overwrite protection,
  exact archive/git-source binding, case/Unicode/path collision rejection, and
  non-legal engineering-gate terminology.
- Final Apple Silicon CI run #32947038458: success; source commit in both
  `CI_ENVIRONMENT.txt` and the coverage report exactly matches `9404926...`.
- Final diagnostics privacy and false-approval scan: passed.

### Do not do

- Do not distribute or describe a diagnostics artifact as the app.
- Do not publish a tester ZIP while any source/relink closure remains open.
- Do not call the alpha Developer ID signed, notarized, generally supported,
  legally approved, or physically validated.
- Do not weaken topology or 3MF fail-closed validation.

### Local-only files

- Downloaded diagnostic ZIPs, extracted inventory/coverage reports, exact wheel
  inspection caches, generated GLB copies, app bundles, and any tester ZIP stay
  outside Git.

## 2026-08-27 Linux x86_64 technical-alpha preparation

### Current objective

Prepare a separate Ubuntu 22.04+ x86_64 technical build of the current Flat
Four Test 3 source without changing or redistributing the published Windows or
macOS builds. The first gate must build and exercise the application on Linux,
but it must upload diagnostics only and must not expose an application archive.

### Completed in this session

- Added a separate exact CPython 3.13.14 Linux x86_64 dependency lock with 22
  official binary wheels. All 22 wheel files resolved for the target and their
  downloaded SHA-256 values matched the values published by PyPI. The lock
  SHA-256 is
  `DB3E5C4C8C2F6F89725131200F27ABDD64940BFB2E72D81B4EE2EABD95A6F007`.
- Added a distinct Linux PyInstaller one-folder spec. It preserves the Linux
  PyTetWild wrapper and package-local shared libraries, uses the normal
  PyMeshLab hook, excludes the hidden Decal `resvg` runtime, filters private
  `direct_url.json` metadata, and keeps Windows/macOS closure evidence out.
- Bound the Tcl/Tk runtime identity to reviewed versioned license files. The
  GitHub toolcache 8.6.18 pair and the local managed-Python 9.0.4 pair are
  accepted explicitly; any unknown patch pair fails closed. The Tcl 9.0.4 and
  Tk 9.0.4 licence bytes match the corresponding upstream release texts.
- Added a strict Linux native/render gate. It performs a real PyTetWild
  tetrahedralization, executes every PyMeshLab filter required by the print
  path, and requires an OpenGL 3.3 framebuffer clear/readback.
- Added a Linux build script that requires Linux x86_64, exact CPython 3.13.14,
  glibc 2.35+, Xvfb or an existing display, source regression, packaged
  self-test, the Linux native/render gate, and Japanese/English packaged UI
  smoke.
- Added a fail-closed application-directory audit for x86_64 ELF identity,
  unresolved shared-library dependencies, non-relocatable build-host paths,
  escaping or broken symlinks, private model/toolpath payloads, pip installation
  origin metadata, and required PyTetWild/PyMeshLab native files.
- Added a GitHub Actions workflow for `ubuntu-22.04`. It builds the one-folder
  application inside the ephemeral runner but uploads only validation reports
  and environment diagnostics for seven days. There is no app, ZIP, tester, or
  Release upload step.
- Added Linux desktop behavior for XDG preferences, `xdg-open`, PATH-based and
  extensionless Snapmaker Orca executables, and an explicit `Linux alpha`
  window suffix while preserving Windows and macOS behavior.

### Current state

- The source, target lock, packaging definition, build/audit scripts, tests,
  and workflow are complete in local branch
  `codex/linux-x86_64-flat4-test3`, based on commit
  `3887224f253fa04996a1240e2c6008b896549b68`.
- WSL2 Ubuntu 24.04.4 x86_64 is now installed and prepared with glibc 2.39,
  native display/audit prerequisites, and a user-scoped CPython 3.13.14 with
  Tcl/Tk 9.0.4. The exact-current Linux build is the next running step.
- Current GitHub account/repository access is restricted: the public REST
  lookup returns 404 and remote reference listing does not complete. Therefore
  the new workflow has not been pushed, started, or observed.
- The previously successful exact macOS technical run remains valid only for
  its recorded commit. The new current bytes still need a new macOS run or a
  real Mac before claiming exact-current macOS validation.
- No Linux executable, application archive, tester artifact, or public download
  has been produced.

### Next exact task

Run the exact-current commit in the prepared WSL2 Ubuntu 24.04 host through
dependency installation, source regression, one-folder build, ELF audit,
packaged self-test, Linux native/render self-test, and both UI smokes. After
GitHub repository access returns, push `codex/linux-x86_64-flat4-test3` and
repeat the same workflow on `ubuntu-22.04` to establish that older glibc
baseline. Keep all application files private until native corresponding-source
and relinking evidence is reviewed separately.

### Changed files

- Linux build and audit: `BUILD_LINUX_X86_64.sh`, `AUDIT_LINUX_APP.sh`,
  `.github/workflows/linux-x86_64-alpha.yml`,
  `source/fixed_app/TripoSpectrumMapper_linux_x86_64.spec`, and
  `source/fixed_app/requirements-build-linux-x86_64.lock`.
- Versioned runtime licences: `licenses/LICENSE_TCL_9_0_4.txt` and
  `licenses/LICENSE_TK_9_0_4.txt`.
- Runtime and entry point: `source/fixed_app/TripoSpectrumMapper_fixed.py`,
  `source/fixed_app/spectrum_mapper/cli.py`,
  `source/fixed_app/spectrum_mapper/platform_runtime.py`, and
  `source/fixed_app/spectrum_mapper/gui.py`.
- Regression: `source/fixed_app/test_linux_alpha_cli.py`,
  `source/fixed_app/test_linux_packaging.py`, and
  `source/fixed_app/test_platform_runtime.py`.
- State: `CURRENT_STATE.json` and `HANDOFF.md`.

### Tests run

- Linux/platform/macOS focused compatibility suite: 52 tests passed with zero
  failures on the Windows development host.
- `bash -n` passed for both Linux shell scripts.
- The GitHub Actions file passed an ad-hoc PyYAML syntax/structure parse; its
  target branch, single build job, and single diagnostics-only artifact upload
  were checked.
- Linux dependency resolution and downloaded-wheel SHA-256 verification:
  22/22 passed with binary wheels only.
- Current complete Windows-host source regression: 1,514 tests in 754.977
  seconds, zero failures, and two optional skips.
- Actual Linux one-folder build, ELF audit, packaged native/render self-test,
  and Japanese/English UI smoke: pending on the now-prepared WSL2 runner.

### Do not do

- Do not describe the workflow file or mocked Windows tests as an actual Linux
  build.
- Do not upload the one-folder application from the technical workflow, and do
  not add a Release or tester-artifact path before the separate source/relink
  audit and explicit owner approval.
- Do not merge this experimental branch into `main`, change version `0.8beta`,
  modify immutable Windows/macOS assets, or weaken topology/3MF fail-closed
  behavior to obtain a Linux pass.
- Do not commit private models, generated 3MF/toolpaths, Linux build roots,
  environments, caches, credentials, or host-specific diagnostic output.

### Local-only files

- `.venv`, caches, private models, generated output, WSL/Linux build
  roots, application directories, validation reports, and archives remain
  local-only and outside Git.
- A temporary ad-hoc PyYAML target under the system temporary directory was
  used only to parse the workflow. It is not under the repository and is not a
  build or publication input.

## 2026-08-27 Linux x86_64 exact WSL technical-build success (current)

### Current objective

Preserve the successful exact-commit Linux technical build as private evidence,
then establish the Ubuntu 22.04 baseline and complete native source/relink review
before any external tester or public distribution is considered.

### Completed in this session

- Built exact source commit `b145e0e6dccf73f9e6b986244a1005e77f26cbfe`
  on WSL2 Ubuntu 24.04.4 x86_64 with glibc 2.39, CPython 3.13.14,
  Tcl/Tk 9.0.4, and patchelf 0.18.0.
- Fixed the Linux build without weakening a gate: exact-snapshot module-origin
  validation, BLAS-stable selected Delta-E recomputation, runtime-equivalent ELF
  dependency lookup, explicit Tcl/Tk shared-library collection, removal of
  unsafe absolute RPATH/RUNPATH components, Pillow Tk hidden imports, and
  package-license filtering that excludes bytecode and local paths.
- Produced a private PyInstaller one-folder application containing 803 regular
  files and 28 confined symlinks, totaling 502,285,134 bytes. The launcher
  SHA-256 is
  `45B39134649B149D2CB6E2B961DB9C19FB3A80A91163380BBC85DF206CB1C774`.
- Audited 319 x86_64 ELF files. No dependency was unresolved, no build-host path
  leak remained, symlink confinement passed, and no private model, toolpath, or
  `direct_url.json` payload was present. Four upstream absolute search paths
  were sanitized before the audit.
- Removed obsolete failed-build and working-tree probe directories after
  verifying their exact resolved paths, reclaiming approximately 1.6 GiB inside
  WSL while preserving the exact `b145e0e` source, successful output, managed
  Python, and dependency environment.

### Current state

- The application builds and executes on WSL2 Ubuntu 24.04.4. Source and
  packaged Linux native/render self-tests, the general packaged self-test, and
  Japanese/English UI smoke all pass.
- This validates only the exact commit above on the Ubuntu 24.04 host. It does
  not yet establish the advertised Ubuntu 22.04 baseline.
- The one-folder application is local-only. No archive, tester artifact,
  Release asset, or public download was created, and distribution approval
  remains false.
- GitHub account/repository access remains restricted, so the diagnostics-only
  `ubuntu-22.04` workflow has not been pushed or observed.
- The earlier successful macOS CI evidence remains tied to its recorded commit;
  these newer bytes still require a real Mac run before exact-current macOS
  validation can be claimed.

### Next exact task

After GitHub access is restored, push
`codex/linux-x86_64-flat4-test3` and run the diagnostics-only
`ubuntu-22.04` workflow. Review its exact source identity, source regression,
ELF audit, packaged self-tests, and both UI smokes. Independently complete the
native corresponding-source/relink review and obtain explicit owner approval
before creating or sharing a Linux application archive.

### Changed files

- Linux implementation and hardening commits from `5b58c27` through
  `b145e0e` cover `BUILD_LINUX_X86_64.sh`, `AUDIT_LINUX_APP.sh`, the Linux
  PyInstaller spec and lock, the diagnostics-only workflow, runtime/platform
  changes, Tcl/Tk licence evidence, and Linux regression tests.
- This final evidence update changes only `CURRENT_STATE.json` and `HANDOFF.md`.

### Tests run

- Exact Linux source suite: 1,276 tests in 69.606 seconds, zero failures, zero
  errors, and three optional skips. Windows release and macOS
  package/compliance modules were excluded by the Linux build contract.
- After this evidence update, 68 focused Windows-host Linux/platform,
  macOS-packaging, release-identity, and palette tests passed. The earlier
  1,514-test Windows full regression predates the numerical-stability fix; a
  new exact-current Windows full regression remains pending.
- Linux source native/render gate: PASS with top-level `ok=true`.
- One-folder application audit: PASS for 319 x86_64 ELF files; unresolved
  dependencies 0; build-host path leaks 0.
- Packaged general self-test: PASS.
- Packaged Linux native/render gate: PASS with top-level `ok=true`.
- Packaged UI smoke in Japanese and English: PASS / PASS.

### Do not do

- Do not describe this private directory as an Ubuntu 22.04-validated download,
  approved tester build, generally supported Linux release, or legal approval.
- Do not archive, upload, publish, or hand the application to a tester until
  native corresponding-source/relink evidence and explicit owner approval pass.
- Do not package the entire local output root: its PyInstaller `work/` data
  intentionally contains host paths. Only the audited
  `dist/ChromaMatter-Linux-Alpha` directory is path-clean, and even that
  directory is not yet distribution-approved.
- Do not merge this experimental branch into `main`, change `0.8beta`, alter
  immutable Windows/macOS assets, or weaken topology/3MF fail-closed checks.
- Do not commit local WSL paths, environments, build outputs, validation
  reports, archives, private models, generated 3MF/toolpaths, or credentials.

### Local-only files

- The exact `b145e0e` source snapshot and its technical output/validation
  directory remain under the ignored WSL home build area. Their host-specific
  absolute paths are intentionally not recorded here.
- The managed CPython installation and exact dependency virtual environment
  remain local-only and must be preserved for repeat validation.

## 2026-08-27 Ubuntu 22.04 Japanese UI and dialog localization (current)

### Current objective

Make both Japanese and English interfaces readable on the Ubuntu 22.04
technical build. Japanese labels must never become blank, and English mode
must not expose Japanese-only progress, completion, warning, or error-dialog
copy. Preserve all topology and 3MF fail-closed behavior.

### Completed in this session

- Reproduced the blank Japanese UI on Linux and proved that it was a Tk font
  availability problem rather than file encoding. The managed Tk 9.0.4
  runtime saw only a Latin `fixed` font until the X11 Japanese fonts were
  installed; Pillow separately required Noto CJK.
- Added one shared Linux font resolver. It requires a Tk font that measures
  Japanese glyphs and a Pillow-renderable Noto CJK font. Missing prerequisites
  now stop with an actionable English package-install message instead of
  opening an unreadable window.
- Replaced fixed Windows font declarations throughout the main UI, Manual
  Editing, help, legal notice, filament candidate, renderer, calibration, and
  workflow surfaces.
- Moved placeholder Japanese text from Pillow-only rendering to Tk Canvas text
  so it uses the verified UI font.
- Localized backend phase/progress text, status results, completion and warning
  dialogs, color-picker copy, manual-edit operations, and automatic-shading
  completion errors.
- Added `Translator.dialog_detail_text()`. Japanese UI retains detailed native
  exception text. English UI retains English details but replaces unknown
  Japanese exception or traceback text with a concise English fallback, so an
  English warning window cannot silently switch languages.
- Added defensive translator fallbacks for lightweight recovery/test hosts;
  this preserves older fixture behavior without affecting a normally
  initialized application.
- Added Linux font and dialog/status localization regression coverage and made
  shell/YAML line endings explicit.

### Current state

- Branch remains `codex/linux-x86_64-flat4-test3`; `HEAD` is
  `a7e2832b2d651af371f13bc68f7568e2b8a53ecf` with the changes above still
  uncommitted.
- The complete Windows regression passed immediately before the final
  Windows-only Snapmaker Orca message routing cleanup: 1,530 tests in 723.807
  seconds, zero failures, two optional skips. The exact-current 31-test
  i18n/output/release/auto-shading set passed after that final cleanup.
- The current functional source snapshot builds and runs on WSL2 Ubuntu
  22.04.5 x86_64 with glibc 2.35, CPython 3.13.14, Tcl/Tk 9.0.4, and patchelf
  0.14.3.
- The private one-folder technical application contains 803 regular files and
  28 confined symlinks, with an apparent directory size of 502,485,534 bytes.
  Launcher SHA-256 is
  `3CE00FE776DF8A2DC8D73FFA9F226E3B1587D560D4C1C97F001D30FB75299ACF`.
- The technical build is not a distribution ZIP. It currently depends on host
  Tk Japanese fonts plus Noto CJK and remains blocked by Linux-specific
  component/source/relink/archive evidence.

### Next exact task

After explicit owner authorization, commit the current font/dialog-i18n work
on the feature branch. Before any tester ZIP, create and verify a Linux
component map and SBOM, complete corresponding-source and relinking evidence,
freeze the required license/font payload, and prove a symlink- and executable-
mode-preserving archive by fresh extraction. When GitHub access returns, run
the diagnostics-only Ubuntu 22.04 workflow against the committed bytes.

### Changed files

- Linux prerequisites/build routing: `.gitattributes`,
  `.github/workflows/linux-x86_64-alpha.yml`, and
  `BUILD_LINUX_X86_64.sh`.
- Font/runtime surfaces: `spectrum_mapper/ui_fonts.py`, `gui.py`,
  `paint_gui.py`, `filament_candidate_gui.py`, `help_center.py`,
  `legal_notice.py`, `renderer.py`, `calibration_chart.py`, `workflow.py`,
  `spectrum_mapper_hotfix.py`, and `smooth_paint_hotfix.py`.
- Localization/tests: `spectrum_mapper/i18n.py`, `test_i18n.py`,
  `test_ui_fonts.py`, `test_auto_shading_integration.py`, and
  `test_linux_packaging.py`.
- State: `CURRENT_STATE.json` and `HANDOFF.md`.

### Tests run

- Focused completion/warning/font/regression set: 88 tests passed.
- Full Windows source regression immediately before the final Windows-only
  Orca localization cleanup: 1,530 tests in 723.807 seconds,
  `OK (skipped=2)`.
- Exact-current i18n/output/release/auto-shading regression after the final
  cleanup: 31 tests passed.
- Ubuntu 22.04 mounted-source UI smoke: Japanese PASS; English PASS.
- Ubuntu 22.04 source native/render gate: PASS with top-level `ok=true`.
- Ubuntu 22.04 application audit: PASS for 319 x86_64 ELF files; four unsafe
  upstream absolute search paths sanitized; no unresolved dependency or
  build-host path leak.
- Packaged general self-test and packaged native/render gate: PASS / PASS.
- Packaged UI smoke: Japanese PASS; English PASS. Font probe selected Tk
  `gothic` with Japanese glyph width 80 and Pillow Noto Sans CJK.
- `git diff --check`: PASS.

### Do not do

- Do not publish, upload, archive, or give this directory to testers yet. It is
  an unsigned private technical build, not a Linux release candidate.
- Do not call the current host-font-dependent directory a self-contained ZIP.
- Do not treat the 319-file ELF architecture/dependency audit as a complete
  component map, SBOM, corresponding-source review, or relinking proof.
- Do not merge into `main`, change `0.8beta`, alter frozen Windows/macOS
  releases, or weaken topology/3MF fail-closed checks.
- Do not commit WSL build roots, validation output, environments, caches,
  private models, generated toolpaths/3MF, credentials, or host-specific paths.

### Local-only files

- The current Ubuntu 22.04 source snapshot, one-folder application, validation
  reports, and temporary UI-smoke profiles remain in the ignored WSL home/tmp
  areas and outside Git; host-specific absolute paths are intentionally not
  recorded here.
- The managed CPython 3.13.14 environment and installed Japanese font packages
  must remain available for repeat technical validation.

## Linux source-backed alpha publication checkpoint (2026-08-27)

### Current objective

Make a Linux test path downloadable from `chromamatter.app` without weakening
the third-party redistribution gate for the separate frozen application.

### Completed in this session

- Localized remaining variable-mediated English-UI paths in automatic filament
  recommendation, reference-image notes, part-print status, colour mixing, and
  Manual Editing eyedropper results. The static UI sink test now detects a
  Japanese literal assigned to a local variable before it reaches a Tk status
  or label sink.
- Added source-backed Linux setup and launch scripts for Ubuntu 22.04+ x86_64.
  Setup requires a graphical session, the four documented Japanese font
  packages, and `uv`; it creates a local CPython 3.13.14 environment and
  installs only the 22 exact hash-pinned wheels from the Linux lock. It never
  runs `sudo`, `curl`, or `wget` automatically.
- Added an English tester guide and a deterministic exact-Git-source tar.xz
  packager with fixed metadata, executable-mode checks, forbidden binary and
  toolpath checks, and independent fresh extraction.
- Added fail-closed standalone-binary evidence generation for the Linux
  component map, SPDX 2.3 SBOM, source manifest/stage, owner decision, and
  final archive approval. All 319 ELF files map to one candidate owner without
  ambiguity, but 16 source/build/relink closure gaps correctly keep the binary
  gate blocked.
- Added a GNU tar.xz standalone-archive contract that preserves symlinks and
  executable modes and requires an archive-external owner approval sidecar,
  avoiding circular approval hashes.
- Removed macOS-only compliance notices from the future Linux spec payload.

### Current state

- The feature branch still has these changes uncommitted. The source-backed
  alpha is the only Linux path intended for immediate publication.
- The existing private 481 MiB one-folder application must not be reused or
  shared: it predates the spec cleanup and lacks complete native source/relink
  closure.
- The standalone binary gate reports 16 unresolved closures even though all
  319 ELF paths are classified. Its component-map/SBOM evidence is engineering
  evidence, not a legal conclusion.
- The official download site will receive the source-backed artifact only
  after an exact clean commit and Ubuntu 22.04 fresh-install test.

### Next exact task

Commit this reviewed checkpoint on `codex/linux-x86_64-flat4-test3`, create the
source-backed tar.xz from that exact commit, fresh-extract it on Ubuntu 22.04,
run installer self-test plus native/render and Japanese/English UI smoke, then
allowlist and upload the immutable artifact to the official site. Keep its
download link hidden until the uploaded size and SHA-256 verify, then request
the final public Sites promotion.

### Changed files

- Linux UI/runtime localization: `spectrum_mapper/ui_fonts.py`, `gui.py`,
  `paint_gui.py`, `i18n.py`, related UI modules, build workflow/script, and
  focused tests.
- Source-backed Linux alpha: `INSTALL_LINUX_SOURCE_ALPHA.sh`,
  `RUN_LINUX_SOURCE_ALPHA.sh`, `LINUX_SOURCE_ALPHA_EN.md`,
  `PACKAGE_LINUX_SOURCE_ALPHA.py`, and its tests.
- Frozen-binary fail-closed tooling: `PACKAGE_LINUX_RELEASE.py`, Linux
  compliance generator/stager/approval tools, catalog, licenses, spec, and
  tests.
- Public source entry points: `README.md`, `README_EN.md`, and `README_JA.md`.

### Tests run

- Exact-current Windows full regression after the Linux UI work: 1,532 tests
  in 728.420 seconds, zero failures/errors, two optional skips.
- Final Linux i18n/font/compliance/archive/source-alpha focused set: 64 tests,
  zero failures, two Linux-only archive skips on Windows.
- Source-alpha-specific installer/packager contract: 8 tests passed.
- Standalone archive GNU tar.xz round trip on Ubuntu 22.04: 9 tests passed.
- Previous current-source Ubuntu 22.04 native/render, packaged self-test, and
  Japanese/English UI smokes remain passed evidence; the new exact commit still
  requires its own source-backed fresh-install run.
- Python compile and `git diff --check`: passed.

### Do not do

- Do not publish the 481 MiB frozen one-folder application or describe it as a
  distribution candidate.
- Do not present the source-backed alpha as a standalone binary, stable build,
  or physical U1 validation.
- Do not include third-party wheels in the source-backed archive; setup must
  download only hash-pinned wheels locally.
- Do not close, waive, or reinterpret the 16 standalone native closure gaps.
- Do not merge directly to `main`, change `0.8beta`, mutate Windows/macOS
  artifacts, expose Decal beta, or weaken topology/3MF fail-closed checks.

### Local-only files

- Existing WSL build outputs, validation reports, virtual environments,
  upload credentials, future tar.xz artifacts, and upload state remain ignored
  and outside Git.

## 2026-08-28 Flat Four default, source-only DemoData, and three-OS site checkpoint

### Current objective

Use one ChromaMatter product path across Windows, macOS, and Linux. New sessions
and command-line conversions start in Flat Four while Full Spectrum remains
available. The next package's DemoData contains only the rights-cleared source
GLB and its reference image. It contains no generated or sample Flat Four 3MF.

### Completed in this session

- Made Flat Four the new-session and no-settings command-line default.
- Preserved an explicitly saved Full Spectrum choice and preserved legacy
  schema-v12 projects without `color_mode` as Full Spectrum.
- Changed the public DemoData contract to exactly two payloads:
  `Original AI model Color.glb` and `Reference.jpg`.
- Changed Windows software and public-source staging to reject every `.3mf`,
  `3MF` directory, extra payload, missing payload, size mismatch, or SHA-256
  mismatch. No Flat Four 3MF was generated or added.
- Updated the English and Japanese repository/runtime documentation to explain
  the source-only DemoData and the single Flat-Four-default product path.
- Strengthened the frozen Linux standalone gate around 16 exact native owner
  groups. A status label alone cannot approve distribution; native identity,
  corresponding source, build provenance, replacement/relink proof, functional
  validation, and owner approval are required.
- Updated and published `chromamatter.app` as Windows / macOS / Linux choices,
  without a stable-versus-test product split. The friendly Windows download
  name routes to the existing eligible Flat Four Test 3 bytes. The page states
  that the next exact Windows package will make Flat Four the new-session
  default and that the Linux standalone remains withheld.

### Current state

- Work remains on feature branch `codex/linux-x86_64-flat4-test3`; `main` was
  not modified by the application work.
- Public display version remains `0.8beta`.
- The changed source is fully regression-tested, but no Windows, macOS, or
  Linux application binary was built from these exact bytes.
- A new public Windows package is blocked on this PC because the complete
  corresponding-source cache, controlled raw PyTetWild wheel, required audit
  logs, rebuild attestation, and an existing complete corresponding-source
  archive are not available here. The repaired application wheel alone is not
  sufficient distribution evidence.
- A frozen Linux standalone application remains blocked by all 16 unresolved
  native source/build/relink owner groups. The source-backed Linux alpha is a
  separate route and is not a standalone app.
- Sites production version 13 was deployed successfully from site commit
  `0efb5774b0339d772ce1e003e833da34c2914062`. The `/download` and `/status`
  routes returned HTTP 200 and disclosed the platform and gate boundaries.

### Next exact task

Restore the complete Windows corresponding-source and controlled rebuild
evidence from the other development PC or recreate it through the controlled
recipe. Then commit a clean exact source checkpoint, build once from that
commit, regenerate the component map and SBOM, stage the source-only DemoData,
create a uniquely named Windows archive, independently fresh-extract it, and
pass self-test plus Japanese/English UI smoke before replacing the current
Windows site object. Separately close all 16 Linux native owner groups before
creating or sharing a standalone Linux archive.

### Changed files

- Flat Four defaults: `source/fixed_app/spectrum_mapper/models.py`,
  `source/fixed_app/spectrum_mapper/gui.py`, and
  `source/fixed_app/spectrum_mapper/cli.py`.
- DemoData/runtime documentation: `source/fixed_app/public_binary/DemoData/`,
  `source/fixed_app/public_binary/README_EN.md`,
  `source/fixed_app/public_binary/README_JA.md`, and
  `source/fixed_app/public_binary/PRIVACY.md`.
- Staging: `tooling/stage_software_package.ps1` and
  `tooling/stage_public_source.ps1`.
- Linux closure: `PACKAGE_LINUX_RELEASE.py`,
  `tooling/linux_native_closure_contract.json`,
  `tooling/generate_linux_compliance_evidence.py`,
  `tooling/stage_linux_corresponding_source.py`, and
  `tooling/approve_linux_distribution.py`.
- Repository README aliases, focused regression tests, `CURRENT_STATE.json`,
  and this `HANDOFF.md`.
- The official site changes live in the separate site repository at commit
  `0efb5774b0339d772ce1e003e833da34c2914062`.

### Tests run

- Focused defaults, GLB/project compatibility, release identity, source-only
  DemoData staging, and Linux compliance/archive suite: 155 tests passed, two
  optional skips, zero failures.
- Exact changed-working-tree full regression with Python 3.13.14: 1,566 tests
  in 604.156 seconds, zero failures and four optional skips.
- Release identity documentation tests: 12 passed.
- Site build and lint: passed; three existing image-optimization warnings and
  zero errors.
- Site route checks: `/`, `/download`, `/status`, and `/feedback` returned
  HTTP 200. Production `/download` showed Windows, macOS, Linux, the friendly
  Windows filename, and the Linux standalone hold.

### Do not do

- Do not add a generated Flat Four 3MF, any other 3MF, or a `3MF` directory to
  DemoData.
- Do not describe the current public Windows archive as the exact build of this
  new Flat-Four-default source. It is the previous eligible Test 3 binary behind
  a friendlier download name.
- Do not publish a new Windows binary without the exact complete corresponding
  source and controlled rebuild evidence.
- Do not publish or hand out a frozen Linux standalone application while any
  of the 16 native source/build/relink owner groups remains blocked.
- Do not merge directly into `main`, change `0.8beta`, expose Decal beta, or
  weaken topology, watertightness, winding, volume, self-intersection, pending-
  palette-apply, or 3MF fail-closed checks.

### Local-only files

- The repository virtual environment, controlled PyTetWild wheel, build roots,
  source caches, validation output, generated archives, private models, and
  generated 3MF/toolpaths remain outside Git.
- Site build archives under the ignored site `work` directory remain local.

## 2026-08-28 Windows Flat Four region quality and six-view preview checkpoint

### Current objective

Improve the Windows Flat Four result on dark chromatic surfaces without
reclassifying deliberate black detail, provide an opt-in connected Fill for
shaded same-color-family faces, and let the main source/converted comparison
switch together between front, back, left, right, top, and bottom views.

### Completed in this session

- Added a conservative topology-backed recovery pass for very dark chromatic
  regions that were assigned to an achromatic F1-F4 slot. Multi-face recovery
  requires one-part connectivity, smooth normals, and boundary agreement with
  the target physical color. A stricter closed-neighborhood rule handles only
  isolated one-triangle notches.
- Protected coherent recovered faces from the existing majority smoother while
  leaving isolated weak candidates eligible for the normal smoothing policy.
- Kept Full Spectrum behavior outside the new recovery path and retained
  conservative no-op limits for missing topology, ambiguous regions, and more
  than 500,000 weak candidates.
- Added a Flat Four-only, default-off Manual Editing option named
  `Include connected shaded regions of the same color family`. It expands Fill
  through untouched automatic faces classified as the requested color family,
  remains inside the active part, stops at true black/nonmatching faces, and
  preserves earlier manual non-target corrections.
- Existing target-color faces are traversal bridges only: they are not turned
  into redundant manual overrides and their adaptive sub-face trees are not
  deleted. Equal-RGB F1-F4 slots are treated as equivalent bridges without
  rewriting their stored slot IDs.
- Added synchronized front/back/left/right/top/bottom orthographic controls to
  the main preview. Source and converted panels use the same direction and
  face-ID map. Adaptive sub-face manual paint is composed with the exact named
  view matrix before the selected-part outline.
- Reviewed the GLB/OBJ research note against the implementation. Current GLB
  import already combines base-color inputs in linear space and excludes PBR
  display maps from print color; current OBJ import remains vertex-RGB-only and
  ignores MTL/UV with a warning. Material/primitive/color-source provenance is
  not yet retained to the Flat Four stage, so the new manual option is described
  as a same-color-family estimate rather than a material-ID operation.

### Current state

- Work is uncommitted on branch `codex/windows-flat4-region-quality`; `main`,
  public tags, and published assets were not changed.
- Public display version remains `0.8beta`.
- Source-level focused regression is green. No Windows executable or archive
  was built from these bytes, and the changed behavior has not yet received a
  final owner visual check in the real Windows GUI.
- The existing Windows public-package gate remains unchanged: this PC still
  lacks the complete exact corresponding-source and controlled-rebuild evidence
  required for a new distributable binary.

### Next exact task

Open the source application on Windows with a rights-controlled representative
model. Compare all six source/converted views, especially the rear surface;
confirm that dark red regions recover without losing deliberate black trim.
Then enable the new Fill option, test red over an automatically black-looking
shaded patch, verify Undo/Redo and preserved prior manual corrections, export a
Flat Four 3MF, and inspect its four physical colors in Snapmaker Orca. Adjust
the conservative thresholds only from this visual evidence. After owner
approval, run the exact-current complete regression in an environment with the
audited native/package evidence, update this handoff, and commit only when
explicitly authorized.

### Changed files

- Flat Four classification and smoothing:
  `source/fixed_app/spectrum_mapper/engine.py`.
- Manual Fill core/UI and adaptive/large-fill compatibility:
  `source/fixed_app/spectrum_mapper/paint.py`,
  `source/fixed_app/spectrum_mapper/paint_gui.py`,
  `source/fixed_app/smooth_paint_hotfix.py`, and
  `source/fixed_app/spectrum_mapper_hotfix.py`.
- Six-view UI/rendering and localization:
  `source/fixed_app/spectrum_mapper/gui.py`,
  `source/fixed_app/spectrum_mapper/renderer.py`, and
  `source/fixed_app/spectrum_mapper/i18n.py`.
- Regression coverage: `source/fixed_app/test_flat_chromatic_shadows.py`,
  `source/fixed_app/test_flat_manual_paint.py`,
  `source/fixed_app/test_hotfix.py`,
  `source/fixed_app/test_front_preview_pair_hotfix.py`, and the new
  `source/fixed_app/test_preview_directions.py`.
- State handoff: `HANDOFF.md`.

### Tests run

- Exact-current Flat Four, Fill/hotfix, six-view, Manual Editing, localization,
  and main-layout set: 157 tests passed, zero failures.
- Broader Flat Four/paint/preview/GUI set before the final named-view adaptive
  fix: 221 tests passed, zero failures. A second independent focused review
  after that fix passed 68 tests.
- A representative multi-million-face local model completed the changed color
  pass in approximately 3.3 seconds after geometry preparation. Its private
  identity and path remain outside the repository.
- `python -m compileall -q source/fixed_app`: passed.
- `git diff --check`: passed after the source changes; rerun once more after
  this handoff update before ending the session.
- A complete discovery run was attempted but encountered the existing local
  audited-native/binary-package evidence failures and was stopped. It is not a
  full-regression pass and is not package evidence.

### Do not do

- Do not widen the shadow thresholds globally or treat every dark warm face as
  red; deliberate black trim and stylized line work must remain protected.
- Do not describe the opt-in Fill as a true GLB material operation until
  face-level material/primitive provenance is retained through preparation.
- Do not let automatic recomputation overwrite a manually changed palette or
  earlier manual face corrections.
- Do not publish, upload, or describe a package as built from these bytes.
- Do not merge into `main`, change `0.8beta`, expose Decal beta, or weaken any
  topology, solidification, pending-palette, or 3MF fail-closed gate.

### Local-only files

- The virtual environment, private validation models, generated previews and
  3MF files, caches, build roots, and any future test archive remain ignored and
  outside Git. Their names and paths must not be added to public files.

## 2026-08-28 Windows Flat Four owner comparison build checkpoint

### Current objective

Provide the owner with a runnable Windows comparison build for the current
Flat Four shadow-region, same-color-family Fill, and six-view preview changes,
without presenting it as a public or compliance-approved package.

### Completed in this session

- Re-ran the exact changed-area and adjacent regression set, including the
  Flat Four 3MF four-physical-color contract.
- Built a fresh Windows one-folder application directly with the pinned local
  Python 3.13.14 environment and PyInstaller 6.20.0 after the repository's
  normal all-tests build entry stopped on the already-recorded local
  distribution-evidence failures.
- Passed the packaged `--self-test` and isolated Japanese and English
  `--ui-smoke` runs.
- Created a canonical owner-only archive whose root name contains
  `WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE`. The archive contains 1,455 files,
  contains no OBJ, GLB, glTF, 3MF, or `direct_url.json`, and passed canonical
  ZIP path, CRC, and exact-file-list validation.
- Independently extracted the archive into a new local directory, repeated the
  packaged self-test and both language UI smokes, and byte-checked every one of
  the 1,455 extracted files against the build tree by SHA-256.

### Current state

- Work remains uncommitted on branch `codex/windows-flat4-region-quality`.
- Public display version remains `0.8beta`; no Git branch, tag, Release, site,
  or public asset was changed.
- Local owner-only archive:
  `ChromaMatter-0.8beta-Flat4-RegionQuality-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260828-win64.zip`.
- Archive size: 117,628,051 bytes.
- Archive SHA-256:
  `62FE7DF1AE114D1526A79E1DC9112A06F297FB29866794D8FBD6715194FF3332`.
- The archive is runnable evidence for local UI comparison only. It is not a
  controlled, corresponding-source-approved, redistributable, or public
  release artifact.
- The fail-closed binary inventory generator still rejects the current local
  evidence because the controlled PyTetWild recipe byte count differs from its
  recorded closure binding. This did not get bypassed or reclassified.

### Next exact task

Have the owner compare the rear and front results with the same model in this
build. Check all six synchronized source/converted views; confirm that dark red
regions improve while deliberate black trim remains black; test the optional
same-color-family Fill, Undo/Redo, and earlier manual corrections; then export
a Flat Four 3MF and confirm in Snapmaker Orca that only F1-F4 physical colors
are active. Use those observations for any threshold adjustment. Do not move
this archive to a public channel. A future public Windows package still needs a
committed exact source checkpoint, restored corresponding-source and controlled
rebuild evidence, a clean all-tests build, regenerated inventory/SBOM, and the
full release gate.

### Changed files

- No application source file was changed during packaging.
- This `HANDOFF.md` was updated with the local comparison-build evidence.
- All build, ZIP, extraction, smoke-profile, and audit-attempt outputs remain
  outside Git.

### Tests run

- Flat Four, dark-color recovery, highlight handling, Manual Editing, adaptive
  paint, six-view rendering, localization, GUI integration/layout, and Flat
  Four 3MF contract: 228 tests passed in 16.306 seconds, zero failures.
- `python -m compileall -q source/fixed_app`: passed.
- `git diff --check`: passed after this handoff update.
- Normal `BUILD_AND_TEST.ps1 -Build` discovery was attempted and stopped after
  the known audited-native, binary-package, and corresponding-source evidence
  tests failed; it did not reach PyInstaller and is not a full-regression pass.
- Direct clean PyInstaller one-folder build: passed; 1,455 packaged files.
- Built-tree self-test: passed.
- Built-tree isolated Japanese and English UI smokes: passed.
- Canonical ZIP create/audit: passed for all 1,455 files.
- Fresh-extract self-test and isolated Japanese/English UI smokes: passed.
- Fresh-extract path, size, and SHA-256 parity against the build tree: passed
  for all 1,455 files.
- Binary inventory/SBOM generation: failed closed with
  `Controlled PyTetWild recipe byte count changed`; no passing inventory or
  SBOM is claimed for this archive.

### Do not do

- Do not upload, publish, redistribute, rename, or relabel this owner-only ZIP
  as an alpha, beta release, public test build, or compliance-approved package.
- Do not use this build as evidence for a future commit; it was produced from
  an uncommitted working tree and the local runtime derives from Microsoft
  Store Python rather than the recovered official-Python controlled venv.
- Do not suppress the binary inventory failure or weaken any corresponding-
  source, topology, solidification, pending-palette, or 3MF fail-closed gate.
- Do not commit the ZIP, executable, build tree, extraction tree, smoke
  profiles, private models, or generated model outputs.

### Local-only files

- Fresh build root:
  `C:\ChromaMatterValidation\windows-flat4-region-quality-workingtree-20260828-01`.
- Fresh extraction root: `C:\CMFreshTest-20260828-01`.
- The owner-only ZIP is stored locally on the operator's Desktop; its absolute
  user-profile path is intentionally not recorded here.

## 2026-08-28 Flat Four dark-region next-step checkpoint

### Current objective

Move beyond the first boundary-supported dark-colour correction after the
owner reported that its visible effect was too small. Recover coherent dark
panels on large GLBs without globally loosening the Flat Four thresholds or
turning deliberate black trim into a chromatic filament.

### Completed in this session

- Identified two independent reasons for the weak result. Region recovery was
  silently disabled whenever a model exceeded 500,000 faces without reusable
  adjacency, and an otherwise unanimous dark component still required at
  least 60% of its exterior boundary to have the exact same F-slot already.
- Added bounded candidate-only edge scanning for large meshes. It keeps only
  the selected face-edge keys, scans the complete triangle set in 100,000-face
  chunks, rejects open/degenerate/non-manifold edges, and avoids allocating or
  sorting the complete multi-million-face adjacency table.
- Added a conservative component self-evidence path. A component must contain
  at least four connected faces, at least two strong colour seeds, at least a
  33% strong-seed share, stable normalized-RGB direction, smooth internal
  topology, and no open or cross-part edge. Existing warm-black and true-black
  guards remain outside this path.
- Changed hard creases from a whole-component veto into graph barriers before
  connected-component analysis. One folded or degenerate edge can no longer
  suppress an otherwise separate smooth panel, while recovery still does not
  cross that edge.
- Added a two-ring darkest-core continuation. A new face needs two smooth
  same-part edge votes from one accepted target and must independently prefer
  that physical hue over its neutral F-slot under bounded low-energy gates.
  Proximity alone remains insufficient, so warm black does not grow from a red
  panel.
- Confirmed by source review that GLB primitive/material identity is not
  retained through current preparation/QEM. The new logic therefore remains a
  topology-and-colour estimate and is not described as material-aware.

### Current state

- Work remains uncommitted on `codex/windows-flat4-region-quality`; `main`,
  public tags, Releases, the download site, and published binaries are
  unchanged.
- Public display version remains `0.8beta` / `r32.2`.
- A local Windows owner-comparison ZIP was produced only for visual testing:
  `ChromaMatter-0.8beta-Flat4-RegionQuality-NextStep1-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260828-win64.zip`.
- ZIP size: 117,673,536 bytes. SHA-256:
  `1491C0872C86757D2528EA516C6365181784056BA149535147BFBF7EA78E5F9B`.
- The archive contains 1,455 files, no OBJ/GLB/glTF/3MF or `direct_url.json`,
  and is not a controlled, corresponding-source-approved, redistributable, or
  public release artifact.

### Tests run

- Updated Flat Four chromatic-shadow module: 28 tests passed.
- Flat Four, Manual Editing, hotfix, paired preview, and six-direction focused
  set under Python 3.13.14: 157 tests passed.
- The seven Flat Four modules: 102 tests passed after the new cases were added.
- A representative approximately 1.5-million-face GLB that formerly skipped
  region analysis completed high-confidence recovery plus the new sparse
  region/core pass. The added region pass recovered 699 faces in about 0.52
  seconds on this host; the model identity and path remain outside Git.
- `python -m compileall -q source/fixed_app`: passed.
- `git diff --check`: passed before this handoff update and must be rerun.
- Full discovery ran 1,603 tests and reached the already-recorded local release
  evidence failures: 55 failures, 9 errors, and 5 skips, led by the controlled
  PyTetWild recipe-byte binding and dependent package/inventory tests. This is
  not a full-regression pass and no release eligibility is claimed.
- Fresh PyInstaller 6.20.0 / Python 3.13.14 one-folder build: passed.
- Built-tree self-test and isolated Japanese/English UI smokes: passed.
- ZIP CRC/path/read audit, exact 1,455-file list, and prohibited-model scan:
  passed.
- Fresh extraction self-test and isolated Japanese/English UI smokes: passed;
  every extracted file matched the staging tree by size and SHA-256.

### Next exact task

Have the owner compare the same difficult Flat Four model with the new local
ZIP, especially broad dark red/brown panels, their deepest shaded cores, hard
creases, and deliberate black line work. Export a Flat Four 3MF and verify that
only F1-F4 are used in Snapmaker Orca. If the visible gain is still too small,
the next algorithmic step is source-colour-family boundary voting or a clearly
user-controlled region tool; do not globally lower neutral/chroma thresholds.

### Do not do

- Do not upload, publish, redistribute, rename, or relabel this working-tree
  ZIP as an alpha, beta release, public test build, or compliance-approved
  package.
- Do not claim primitive/material-aware recovery. Adding true face-level
  appearance provenance would require schema, preparation/QEM lineage, project
  bundle, split/joint, and export changes.
- Do not merge, commit, push, change `0.8beta` / `r32.2`, or weaken topology,
  pending-palette, 3MF validation, controlled-build, or release gates without
  explicit owner authorization.
- Keep build roots, extracted test trees, profiles, private models, generated
  outputs, and archives outside Git.

## 2026-08-29 named-view to Front black-preview checkpoint

### Current objective

Fix the owner-reported preview failure where the initial Front view renders
normally, but returning to Front after any other named direction can render an
entirely black or otherwise corrupted comparison image.

### Root cause and fix

- Front uses a persistent `InteractiveMeshRenderer` cached per preview worker,
  level identity, size, and background. The five non-Front directions use the
  canonical renderer, which creates and releases a separate standalone OpenGL
  context on the same single worker thread.
- On the tested Windows/glcontext path, releasing the temporary named-view
  context does not restore the older cached Front context as current. The old
  renderer still passes its thread/closed checks and can return black or
  undefined framebuffer data without raising, so the exception fallback never
  runs.
- Both the paired and single preview wrappers now close and remove the cached
  Front renderer before entering a canonical non-Front render. Returning to
  Front therefore creates a fresh context, framebuffer, depth buffer, and
  programs instead of reusing invalid GL state.
- This is a display-only lifecycle correction. Camera matrices, direction
  labels, mesh colours, manual paint, palette assignment, and 3MF output are
  unchanged.

### Verification

- The old lifecycle was reproduced with real ModernGL by temporarily disabling
  the cache discard at runtime: `front -> back -> front` changed a valid Front
  frame into a nearly all-black/corrupt frame without an exception.
- With the fix enabled, returning from each of Back, Left, Right, Top, and
  Bottom produces source RGB, target RGB, and face-ID arrays byte-for-byte
  identical to the initial Front frame.
- Added deterministic fake-renderer lifecycle tests for the paired and single
  APIs plus a real-GPU six-direction return-to-Front pixel/face-ID regression.
- Flat Four, preview, rotation, hotfix, and adaptive-overlay focused set:
  207 tests passed. The final front-preview hotfix module: 7 tests passed.
- `python -m compileall -q source/fixed_app` and the final
  `git diff --check` passed.
- Fresh direct PyInstaller 6.20.0 / Python 3.13.14 one-folder build passed.
  Built-tree and fresh-extracted self-tests plus isolated Japanese and English
  UI smokes passed. ZIP path/CRC/read validation and exact 1,455-file fresh
  extraction parity passed.

### Local owner-only build

- `ChromaMatter-0.8beta-Flat4-RegionQuality-NextStep1-FrontViewFix-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260829-win64.zip`
- Size: 117,699,010 bytes.
- SHA-256:
  `93E301A8BC3234A5DE8979A221BA9D783E943CFFD136F71C3906547738103C34`.
- The archive remains a local working-tree comparison build. It was not
  committed, pushed, uploaded, or published and is not release/compliance
  evidence.

### Next exact task

Have the owner open the same model, cycle through all six directions in any
order, and repeatedly return to Front. Confirm both AI Model Color and the
converted preview remain visible and that Manual Editing still opens from the
converted panel. Continue evaluating the Flat Four dark-region change from the
same build. Do not publish this archive.

## 2026-08-29 command-line direct model-open checkpoint

### Objective and completed work

- Added a direct GUI model route: `--model MODEL` opens an OBJ or GLB through
  the same picker-backed preflight, fresh-model settings, and ordinary geometry
  preparation path used by the main window.
- Added `--confirm-large-model` as an explicit command-line acknowledgement for
  the already-supported reduced large-GLB route. Without it, the existing GUI
  confirmation remains mandatory. With it, only a plan that still passes the
  static-TRIANGLES, vertex, byte, and reduced-source ceilings is admitted.
- Directly opened multipart models still start with Solidify, unmatched-boundary
  repair, and automatic joints disabled. The direct route therefore creates an
  editable working model without silently changing topology.
- Kept project, conversion, UI-smoke, and self-test modes mutually exclusive
  with direct model open where combining them would otherwise ignore an input.

### Current state and next task

- The source direct-open route and its synthetic tests pass. Japanese and
  English source UI smokes also pass.
- No packaged executable was rebuilt in this checkpoint. A caller can use
  `TripoSpectrumMapper_fixed.py --model MODEL --confirm-large-model` with the
  pinned source environment for an explicitly acknowledged supported large
  GLB.
- Next, connect the local repair application's one-click handoff to these two
  flags and perform the owner-visible model review. Keep 3MF export governed by
  the existing solidification, topology, volume, winding, and self-intersection
  gates.

### Changed files and validation

- `source/fixed_app/spectrum_mapper/cli.py`
- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/test_direct_model_open.py`
- Direct-open, new-model, GLB GUI/project, GLB importer, GUI layout, packaged
  language CLI, and macOS/Linux alpha CLI regression: 88 tests passed.
- Release identity regression: 12 tests passed.
- Japanese and English source UI smoke: passed.
- Python compile and `git diff --check`: passed.

### Do not do and local-only files

- Do not interpret `--confirm-large-model` as a topology or export override.
  It acknowledges only the bounded working-model reduction already described
  by the GUI; unsupported or over-limit GLB files still fail closed.
- Do not commit a private model, its name/path/hash, generated output, build
  directory, environment, cache, or validation sidecar. No private asset or
  derived output was added by this checkpoint.

## 2026-08-30 High-Contrast Cel and clickable light-pad checkpoint

### Objective and completed work

- Added an experimental `High-Contrast Cel` / `セル彩色（強調）` mode for
  physical prints whose black garments lost nearly all visible shading.
- Unlike ordinary multiplicative shading, the strong mode assigns bounded
  absolute lightness targets to dark surfaces. At four bands it retains a
  near-black ink band and creates printable dark-grey, mid-grey, and
  light-grey highlight targets before the user-strength blend.
- Preserved chromatic dark materials instead of forcing every dark source into
  neutral grey. A narrow warm-material classifier protects sufficiently warm
  dark skin/brown ramps while excluding neutral and mildly warm black cloth;
  saturated navy, red, green, and purple retain their colour direction.
- Flat Four automatic filament recommendation reserves black, mid-grey, and a
  shared light/white endpoint when a large black surface needs them. Dark warm
  skin can reserve one brighter warm physical filament instead of losing its
  remaining slot to a redundant silver/grey filament.
- Extended the fixed-front illustration light from the compatible three saved
  choices to nine positions. Manual Editing now exposes a compact clickable
  3-by-3 arrow pad for upper, side, centre, and lower light directions. The
  original upper-left, front, and upper-right saved values and vectors remain
  accepted unchanged.
- The light remains geometry-aware rather than screen-painted: surface normals
  and the selected light vector make folds and silhouette-facing changes enter
  different stepped bands. It is not ambient occlusion and does not invent
  folds missing from the mesh.

### Current state and next task

- Work remains uncommitted on `codex/windows-flat4-region-quality`; no GitHub
  branch, tag, Release, site object, published binary, or public version was
  changed.
- A new owner-only Windows comparison archive is ready locally:
  `ChromaMatter-0.8beta-HighContrastCel-LightPad-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260830-02-win64.zip`.
- Archive size: 117,666,593 bytes. SHA-256:
  `CBB6490F14CA74D37B64F56F0D299AB37C7FFDA7377DF478F69B3320DF621138`.
- Next, test one representative black-clothing model with High-Contrast Cel at
  the default 78% strength and four bands. Compare several 3-by-3 light-pad
  positions, rerun automatic filament recommendation after selecting the
  desired light, then inspect the exported Flat Four 3MF in Snapmaker Orca and
  on a small physical print. Confirm that the warm skin slot remains skin-like
  while the garment shows at least three physically distinct dark/light bands.

### Changed files

- Strong Cel filtering and warm-material classification:
  `source/fixed_app/spectrum_mapper/illustration_filter.py`.
- Flat Four print anchors, warm recovery, smoothing protection, and output
  mapping: `source/fixed_app/spectrum_mapper/engine.py`.
- Automatic physical-filament proposal integration:
  `source/fixed_app/spectrum_mapper/gui.py`.
- Saved-setting validation and nine light directions:
  `source/fixed_app/spectrum_mapper/models.py`.
- Manual Editing mode and clickable light-pad UI:
  `source/fixed_app/spectrum_mapper/paint_gui.py`.
- The nine light buttons use larger targets, dark high-contrast selection,
  and visible keyboard focus; their invoke/value mapping is covered by the
  live-Tk structure test.
- Japanese/English labels: `source/fixed_app/spectrum_mapper/i18n.py`.
- Regression: `source/fixed_app/test_illustration_filter.py`,
  `source/fixed_app/test_strong_cel_print.py`, and
  `source/fixed_app/test_manual_shading_ribbon.py`.

### Validation

- High-Contrast Cel, all nine light directions, Manual Editing shading UI,
  parent-window state bridge, localization, Flat Four highlight/shadow/mapping,
  manual paint/hotfix, and front-preview lifecycle set: 208 tests passed with
  zero failures.
- The tighter algorithm/palette audit separately passed 63 related tests,
  including neutral/warm-black boundaries, dark-skin retention, and saturated
  dark-colour preservation.
- Python compilation and `git diff --check`: passed.
- Direct clean PyInstaller 6.20.0 / Python 3.13.14 one-folder build: passed with
  1,455 files. Built-tree self-test and isolated Japanese/English UI smoke:
  passed.
- Canonical ZIP creation and path/CRC/exact-file-list audit: passed for all
  1,455 files. No model, 3MF, media payload, reparse point, or pip
  `direct_url.json` was included.
- Independent fresh extraction matched every relative path, byte size, and
  SHA-256 against the built tree. Fresh-extracted self-test and isolated
  Japanese/English UI smoke: passed.
- Complete discovery still reaches the already-recorded local release and
  corresponding-source evidence failures. Therefore this checkpoint does not
  claim a complete regression or public-distribution approval.

### Do not do and local-only files

- Do not upload, publish, redistribute, rename, or relabel this working-tree
  archive as an alpha, beta Release, public test build, or compliance-approved
  package.
- Do not treat monitor-visible grey as physical-print validation. The exact
  filament combination and small print must still be checked, especially the
  balance between warm skin and neutral garment highlights.
- Do not merge, commit, push, change `0.8beta`, or weaken topology,
  solidification, pending-palette, 3MF, controlled-build, or publication gates
  without explicit owner authorization.
- The archive, build tree, independent extraction, smoke profiles, private
  validation models, generated previews, and 3MF outputs remain local-only and
  outside Git.

## 2026-08-30 High-Contrast Cel light-first band-ramp checkpoint

### Objective and completed work

- Reordered the practical High-Contrast Cel workflow around lighting first:
  choose the light direction, derive geometric shadow/mid/highlight band IDs,
  and only then choose printable palette states.
- Preserved the band IDs through tone filtering and automatic assignment.  On
  dark low-chroma garments, one geometric light band now resolves to exactly
  one monotonic neutral print state instead of independently nearest-mapping
  every triangle into the 16/24/32-state Full Spectrum palette.
- Added conservative same-part region growth from strict dark-cloth seeds into
  broad baked grey highlights.  It is limited to low-chroma faces connected by
  smooth edges and requires two distinct dark seed contacts.  Warm skin, white
  eyes, silver details, hard creases, and separate parts are covered by
  fail-closed regressions.
- Kept manual face paint authoritative.  Generic smoothing, Flat recovery, and
  the hidden black-free remap run before the final automatic band mapping so
  they cannot reintroduce within-band speckle afterward.
- Manual Editing now offers an explicit `Suggest 4 Colors for Cel` action only
  in High-Contrast Cel mode.  It flushes the current light/tone setting first,
  protects manually chosen palettes behind confirmation, synchronizes both
  Full Spectrum and Flat Four previews, preserves custom output mix ratios,
  and recommends Physical Black Correction for Full Spectrum physical prints
  without enabling or changing it silently.

### Validation

- High-Contrast Cel filter and printable-state focused set: 47 tests passed.
- Broader illustration, Flat Four, Full Spectrum, Manual Editing, hotfix,
  palette, preview-direction, localization, and black-output set: 290 tests
  passed in 38.612 seconds.
- `python -m compileall -q source/fixed_app` and `git diff --check`: passed.
- Fresh direct PyInstaller 6.20.0 / Python 3.13.14 one-folder build: passed
  with 1,455 files.  Built-tree self-test and isolated Japanese/English UI
  smokes: passed.
- Canonical ZIP CRC/path/read/size/SHA-256 audit: passed for all 1,455 files.
  No OBJ, GLB, glTF, 3MF, reparse point, or pip `direct_url.json` entered the
  package.  Its relative path set exactly matches the previous safe build.
- Independent fresh extraction matched every staged file by relative path,
  byte size, and SHA-256 before and after testing.  Fresh-extracted self-test
  and isolated Japanese/English UI smokes: passed.

### Local owner-only build

- `ChromaMatter-0.8beta-HighContrastCel-BandRamp-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260830-03-win64.zip`
- Size: 117,685,131 bytes.
- SHA-256:
  `BAECD47FDE89E4A5A5C8D1866C6D92D28CB739333F5E1756A3D19324337B42AA`.
- Desktop copy and validation-root source archive are byte-identical.  This is
  an owner-only physical-comparison build; it was not committed, pushed,
  uploaded, published, or used to change the public version.

### Next exact task and limits

Select the desired 3-by-3 light direction before requesting the Cel-specific
four-colour proposal.  For a Full Spectrum physical print, explicitly enable
Physical Black Correction, export the 3MF, and compare a small black-garment
print for at least three visible dark/light bands while confirming that skin,
eyes, and metallic accents remain separate.

This checkpoint does not yet physically validate a particular filament set.
Very small isolated black details, open meshes without face neighbours, and
near-zero filter strength remain known conservative edge cases.  Do not
publish or relabel this working-tree archive, commit/push the dirty branch, or
weaken topology, pending-palette, 3MF, controlled-build, or release gates
without explicit owner authorization.

## 2026-08-30 Generic coloured-light High-Contrast Cel checkpoint

### Objective and reusable behavior

- Generalized the successful blue-black garment treatment so it is not tied
  to one character or model.  Full Spectrum High-Contrast Cel now identifies
  broad, connected, low-chroma dark material regions by part/material group,
  seed contact, lifted-area, filter-strength, and minimum-area gates.
- Neutral black receives a cool blue-grey printable ramp.  Existing dark navy
  or violet material instead keeps its source hue and is lifted along that hue,
  so different models do not all become the same blue.
- Warm skin, white/eye regions, small isolated black details, saturated armour,
  metallic accents, custom mix/output ratios, and manual face paint remain
  protected.  Flat Four and non-Strong-Cel modes retain their prior behavior.
- Added separate `Light Strength` (band luminance) and `Light Range` (angular
  coverage/rear fill) controls.  Their legacy defaults reproduce the old light
  curve, while direction, strength, and range can now be tuned independently.

### Reproduction profile and verification

- Measured dark-clothing reference ramp: `#080C15`, `#1F252D`, `#445B78`,
  `#536A8B`.  The generic synthetic integration case maps these at DeltaE76
  5.47, 3.44, 2.79, and 4.74 without using the skin endpoint.
- Front-artwork comparison profile: reset global black/white/gamma/contrast/
  saturation controls, then Strong Cel, 4 bands, Style Amount 78%, Light
  Strength 45%, Light Range 30%, and an upper-left or upper-right light.
- All-around readability profile: Light Strength 65% and Light Range 65%.
  This reduces front clipping while lifting rear faces into a dark visible
  band.  Exact physical color still requires the owner's filament chart and a
  small print comparison.
- The independent integration regression covers a generic neutral garment,
  navy material, dark warm skin, a small black eye, and saturated red armour.
  Together with the related suite, 308 tests passed; `compileall` and
  `git diff --check` passed.

### Local owner-only build

- `ChromaMatter-0.8beta-HighContrastCel-ColoredLight-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260830-04-win64.zip`
- Size: 117,704,609 bytes.
- SHA-256:
  `A69A00D9B12064DAE794B481AB1F667E3A7B5B2F8469146747E284BEEF3A4792`.
- Fresh direct one-folder build contains 1,455 files.  Built and independently
  extracted self-tests and isolated Japanese/English UI smokes passed.  ZIP
  CRC/path/read/size/SHA-256 audit and post-smoke fresh-extract parity passed.
  The new and previous safe builds have identical relative path sets; no model,
  3MF, reparse point, `direct_url.json`, or suspicious secret-named file entered
  the package.
- Desktop and validation-root ZIPs are byte-identical.  This build remains an
  internal physical-comparison build and was not committed, pushed, uploaded,
  published, or used to alter the public version.

### Next exact task and limits

Print the same small dark-garment crop with the front-artwork and all-around
profiles, using the same four filaments and slicer settings.  Record front,
side, and back photos under fixed lighting.  Tune only the generic thresholds
and ramp roles from those observations; do not introduce character names or
model-specific mesh IDs into the algorithm.

## 2026-08-31 Source Vault import verification checkpoint

### Current objective

Resume the latest generic coloured-light High-Contrast Cel working tree from
the authenticated private Source Vault on this Windows development PC without
losing the earlier local Flat Four work or weakening any release gate.

### Completed in this session

- Downloaded private version `Generic Colored-Light Cel WT 20260831` as both
  the authoritative source ZIP and the complete committed-history Git bundle.
- Matched both downloaded SHA-256 values to the values displayed by the Source
  Vault and passed `git bundle verify` for the complete SHA-1 history through
  `a94f6cd9add8d76f7debf9a388f896a0c7ee8407`.
- Audited the ZIP's 576 entries: one root, 486 files, 90 directories, valid CRC
  for every file, safe canonical paths, no duplicate/case-fold collision,
  encryption, symlink, special file, nested archive, executable binary,
  private model, generated model output, credential, or host path.
- Reconstructed the bundle in a separate sibling checkout, overlaid the ZIP,
  and byte-compared all 486 files before synchronizing the same snapshot into
  the normal development checkout. Ignored environments and local-only data
  were not removed or replaced.
- The restored Git state contains 28 content-changing tracked files and four
  untracked regression modules. There are no staged files and no tracked
  deletion. Public version, tags, releases, and site objects were unchanged.

### Current state

- Branch remains `codex/windows-flat4-region-quality` at committed base
  `a94f6cd9add8d76f7debf9a388f896a0c7ee8407` with the restored working-tree
  changes uncommitted.
- Source ZIP SHA-256:
  `606B7A0F403B1BDED0F759D3302D80E40FD3B8542A06A6D1C9B1AD3D18714191`.
- Git bundle SHA-256:
  `C9C60CB9A78901492A1F74890E879861D770726EBB6BCE78707A1013E47ADE7E`.
- All 486 repository files matched the extracted Source Vault snapshot before
  this handoff-only import record was appended.
- `CURRENT_STATE.json` is still the conservative 2026-08-28 record. It does
  not yet describe the High-Contrast Cel working tree, but its pending Windows,
  macOS, Linux, topology, 3MF, and distribution gates remain authoritative.
- This is a resumed internal working tree, not a release or redistributable
  binary checkpoint.

### Next exact task

Update the state documentation for High-Contrast Cel before any packaging
work, then run the owner comparison described in the preceding checkpoint:
use the same rights-controlled dark-garment crop with the front-artwork and
all-around light profiles, fixed filaments and slicer settings, and record
front/side/back observations. Keep algorithm tuning generic and based on that
evidence.

### Changed files

- The Source Vault ZIP restored its complete cumulative 32-change working-tree
  snapshot; do not cherry-pick only the Cel-looking files because the UI,
  GLB/project, preview, paint, localization, and regression changes are linked.
- This `HANDOFF.md` gained the local import-verification record after byte
  parity was established.
- No file was staged, committed, pushed, published, or added to a release.

### Tests run

- Source ZIP SHA-256, full CRC/path/entry audit, fresh extraction, and 486-file
  path/size/SHA-256 parity: passed.
- Git bundle SHA-256 and complete-history verification: passed.
- Primary Cel integration/filter/print/UI proposal set: 99 tests passed.
- Exact related Cel, Flat Four, Manual Editing, preview, localization,
  black-output, GLB, and project-bundle set: 308 tests passed in 21.995 seconds
  with zero failures or errors after using the repository root plus fixed-app
  module path. Two earlier invocations used incomplete module search paths and
  produced import-only errors; they did not expose an application failure.
- `python -m compileall -q source/fixed_app`: passed.
- `CURRENT_STATE.json` strict PowerShell JSON parse: passed.
- `git diff --check`: passed before this handoff update and must be rerun once
  after it.

### Do not do

- Do not commit or push this dirty working tree without explicit owner
  authorization.
- Do not publish or relabel the Source Vault ZIP, Git bundle, sibling checkout,
  or owner-only Windows comparison build as a public alpha/beta/release.
- Do not treat the Git bundle alone as the current source; it contains only
  committed history, while the ZIP is authoritative for the restored dirty
  bytes.
- Do not weaken topology, solidification, pending-palette, 3MF, controlled-
  build, corresponding-source, or publication gates.

### Local-only files

- Downloaded private artifacts, the fresh extraction, the verification sibling
  checkout, and the pre-import untracked-file backup remain outside Git.
- Virtual environments, private validation models, build/extraction roots,
  generated previews/3MF, and smoke profiles remain ignored and local-only.

## 2026-08-31 Selectable automatic-proposal gamut checkpoint

### Current objective

Let users choose whether future automatic four-filament proposals use the
current expanded cool-grey gamut or the earlier basic-colours-and-skin gamut,
without changing an already selected F1-F4 palette.

### Completed in this session

- Added a global, persisted `Auto-Proposal Color Range` selector with Japanese
  and English labels. `Expanded (allow blue/violet grey)` remains the default
  so existing current behavior is preserved; `Classic basic colors + skin
  tones` restores the earlier automatic anchor set.
- Defined the classic set as the same automatic neutral, primary, and skin
  anchors with only `cool_blue_gray` and `cool_violet_gray` removed. The three
  `CATEGORY_INTERMEDIATE` catalog entries remain manual-only in both modes.
- Applied the policy before curated anchors are mapped to real product IDs, in
  both the product-database path and the offline PLA fallback. No post-mapping
  product-ID filter was added.
- Routed whole-model, selected-part, new-model automatic, and Strong Cel
  proposals through the same policy-aware recommendation function.
- Kept a policy switch non-destructive: it saves the preference and affects
  only the next proposal. It does not re-run a proposal or alter current
  F1-F4 values.
- Captured the policy on the Tk main thread before background work starts and
  included it in the request/current snapshots. A result is discarded as
  stale if the policy changes while analysis is running.

### Current state

- Branch and committed base are unchanged; this remains an uncommitted dirty
  Windows working tree and no public version value was changed.
- The selector is intentionally a cross-model preference in `settings.json`,
  not part of `AppSettings` or a model/project colour snapshot.
- Existing projects and existing palettes therefore keep their saved colour
  state, while subsequent proposal buttons use the currently selected range.

### Next exact task

Open a rights-controlled comparison model, keep every model/tone/filament
setting fixed, and run one proposal in each range. Confirm that Expanded may
choose the cool blue-grey/violet-grey anchors for a suitable broad cool
surface, while Classic chooses only the earlier basic/skin set. Then compare
the resulting preview and small physical print before considering a release.

### Changed files

- `source/fixed_app/spectrum_mapper/filament_recommender.py`
- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/spectrum_mapper/i18n.py`
- `source/fixed_app/test_filament_recommender.py`
- `source/fixed_app/test_filament_candidate_gui.py`
- `source/fixed_app/test_new_obj_defaults.py`
- `HANDOFF.md`

### Tests run

- Recommendation policy, persistence, and GUI focused set: 57 tests passed.
- Localization, Strong Cel bridge/print, Cel light integration, and Flat Four
  related set: 69 tests passed.
- The policy regression verifies the exact 17-anchor Expanded and 15-anchor
  Classic sets, a deterministic input whose proposal differs between them,
  pre-product-ID database mapping, non-destructive UI switching, persisted
  fallback behavior, and stale asynchronous-result rejection.
- A repository-wide discovery run was attempted but manually stopped after
  failures/errors appeared outside the completed focused sets; because it was
  interrupted, it produced no trustworthy final test count or failure summary.
- `python -m compileall -q source/fixed_app` and `git diff --check`: passed.

### Do not do

- Do not silently change the default from Expanded or reinterpret the toggle
  as permission to use manual-only `CATEGORY_INTERMEDIATE` entries.
- Do not filter after mapping to real filament product IDs, and do not read a
  Tk variable from recommendation background work.
- Do not automatically replace the current palette when the selector changes.
- Do not commit, push, package, upload, publish, or weaken topology, pending-
  palette, 3MF, controlled-build, corresponding-source, or publication gates.

### Local-only files

- No new model, 3MF, binary, build directory, cache, credential, or private
  filename was added by this work.

## 2026-08-31 Shadow-balanced High-Contrast Cel output checkpoint

### Current objective

Tune the High-Contrast Cel print profile so a rights-controlled, dark-clothed
single-mesh GLB keeps its cool base colour while showing readable graphic
light and shadow on both the front and rear, then produce one fail-closed 3MF.

### Completed in this session

- Compared the former `0.78 / 4 bands / front-left / 0.45 / 0.30` profile
  against hard-light, refined intermediate, broad-range, and four-band sweeps.
- Rejected the hard-light profiles because large surfaces mapped to white or
  light grey, and rejected the two-band profiles because they lost the cool
  garment ramp.
- Selected `Style 0.92 / 4 bands / top / Light Strength 0.52 / Light Range
  0.55`. It keeps a four-step black-to-cool-blue ramp, adds clear face-shaped
  shadows to the front, and retains readable dark detail on the rear.
- Generated one local Full Spectrum 32-state, 180 mm, 450,000-face 3MF with
  automatic PLA endpoints and physical black correction on its darkest slot.
- The generated package passed CRC, entry-count, vertex/face/part, watertight,
  positive-volume, self-intersection, palette, physical-filament, cycle, and
  surface-shell checks. No source model or output was added to the repository.

### Current state

- Branch, committed base, public version, and release state are unchanged.
- The generated 3MF and comparison images are owner-only local validation
  artifacts. Snapmaker Orca opening, slicing, and a physical print are still
  required before this profile can be treated as generally validated.

### Next exact task

Open the new local 3MF as a project in Snapmaker Orca, verify four physical
spools and 32 Full Spectrum states, inspect front/side/back layer previews for
unexpected black regions or white clipping, and make a small physical print.
Record whether `0.52 / 0.55` needs a model-independent preset or remains only a
comparison profile.

### Changed files

- `HANDOFF.md` only for this output-tuning record. The generated files and
  sweep helper remain outside the repository.
- No file was staged, committed, pushed, packaged, uploaded, or published.

### Tests run

- Focused automatic-proposal policy set: 57 tests passed.
- Related Cel, Flat Four, Manual Editing, preview, localization, black-output,
  GLB, and project-bundle set: 311 application tests passed. The first
  invocation had two module-search-path-only import errors; both exact tests
  passed when rerun with the repository root and fixed-app paths.
- `python -m compileall -q source/fixed_app`: passed.
- Generated 3MF: 10 ZIP members, CRC passed, 224,996 vertices, 450,000 faces,
  one watertight positive-volume part, zero self-intersection warning parts,
  Full Spectrum 32 states, and four physical filaments.
- `git diff --check`: passed before this checkpoint and must be rerun after it.

### Do not do

- Do not publish the rights-controlled input, local preview, 3MF, settings,
  hashes, paths, or owner-only comparison outputs.
- Do not call this a release preset until Orca slicing and physical output are
  checked, and do not weaken any topology or 3MF validation gate.
- Do not commit or push without explicit owner authorization.

### Local-only files

- Rights-controlled input model, generated 3MF, preview, validation report,
  settings, comparison grids, and helper scripts remain outside Git.

## 2026-08-31 Opt-in High-Contrast Cel source-detail checkpoint

### Current objective

Preserve coherent source-texture wrinkles and shallow geometric folds in
High-Contrast Cel while increasing shadow separation, without adding print
states, changing the established brightest band, or affecting existing
projects unless the new detail control is explicitly enabled.

### Completed in this session

- Added `ToneSettings.illustration_detail_strength` as a validated `0..1`
  control with an exact default of `0.0`. A zero value is omitted from project
  JSON, and all GUI/settings reconstruction paths preserve it without adding a
  visible control yet.
- Kept the legacy Strong Cel result exact at zero. When enabled, crease-aware
  normals keep up-to-five-degree tessellation noise smooth, progressively
  restore shallow folds between five and twenty degrees, and retain existing
  hard-crease handling above twenty degrees.
- Added a topology-backed source-detail pass for dark garments. Only a
  connected multi-face patch with sufficient printable area and robust source
  luminance contrast may move by one already-requested cel band. Singleton
  triangles, missing/malformed topology, separate parts, weak contrast, and
  warm skin/brown faces fail closed.
- Expanded contrast downward only: the established absolute Strong Cel target
  is multiplied by a shadow-only factor whose four default-band values at full
  detail are approximately `0.68 / 0.77 / 0.87 / 1.00`. The brightest band's
  target and channel balance remain unchanged.
- Added an opt-in wider warm-source guard. Dark skin keeps stronger source hue
  in lower bands, and the garment-detail mask excludes those warm faces.
- Added a narrow Full Spectrum recovery: a warm source face that nearest-Lab
  mapping put into a neutral/cool state may move only to an enabled warm recipe
  within 30 degrees of source hue and 12 L* of its current state. It does not
  lift the highlight, does not touch neutral/cool clothing, and is exactly off
  at detail zero.
- No topology, solidification, 3MF validation, requested-band limit, Flat Four
  four-state boundary, public version, or publication code was weakened.

### Current state

- The source behavior is implemented and regression-tested but the new detail
  strength intentionally has no user-facing slider/preset yet. Owner model
  comparison is required before choosing a safe default preset or exposing it.
- Existing project files and zero-detail calls retain the legacy output. A
  nonzero value round-trips through project settings for controlled tests.
- This remains an uncommitted dirty Windows working tree on the existing
  feature branch. No binary or release was produced.

### Next exact task

Run a fixed-filament front/side/back comparison at detail `0.0`, `0.5`, and
`1.0` on a rights-controlled model. Verify that broad garment wrinkles become
readable without triangle speckle, that the brightest highlight is unchanged,
that skin shadows use a warm recipe rather than grey, and that Full Spectrum
uses no more states than the requested cel bands on the garment. If the result
is general, add a localized UI control with default zero and explicit preview
refresh semantics.

### Changed files

- `source/fixed_app/spectrum_mapper/models.py`
- `source/fixed_app/spectrum_mapper/illustration_filter.py`
- `source/fixed_app/spectrum_mapper/engine.py`
- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/spectrum_mapper/paint_gui.py`
- `source/fixed_app/test_illustration_filter.py`
- `source/fixed_app/test_strong_cel_print.py`
- `HANDOFF.md`

### Tests run

- `py_compile` for the five changed runtime modules and two focused test
  modules: passed.
- Illustration-filter and Strong Cel print focused set: 70 tests passed.
- Regressions cover exact default-off output, shallow-fold restoration,
  shadow-only contrast with an unchanged peak, warm-skin saturation, connected
  multi-face wrinkle acceptance, singleton rejection, warm-face garment
  exclusion, missing-topology no-op, requested-band bounds, same-L* Full
  Spectrum warm-recipe recovery, and exact default-off recovery.
- PyMeshLab emitted its existing unavailable Qt-plugin warnings; no test failed
  or errored.
- `git diff --check`: passed before this checkpoint and must be rerun once
  after it.

### Do not do

- Do not make the detail value nonzero by default or add a UI default before
  controlled preview, slicer, and physical comparison.
- Do not relax the multi-face/topology/area/contrast gates to preserve a single
  dark triangle, and do not allow the pass to invent a band or palette state.
- Do not apply the warm-recipe recovery to neutral/cool garments or select a
  brighter recipe merely to increase saturation.
- Do not commit, push, package, upload, publish, or weaken topology, pending-
  palette, 3MF, controlled-build, corresponding-source, or publication gates.

### Local-only files

- No model, preview, 3MF, binary, build directory, cache, credential, or
  identifying filename was added by this work.

## 2026-08-31 Contour-and-warm-shadow validation checkpoint

### Current objective

Validate the opt-in Strong Cel detail layer on one rights-controlled dark-
garment GLB, keeping the established highlight while making garment wrinkles,
shape boundaries, and skin shadows more readable in a printable 3MF.

### Completed in this session

- Compared detail strengths `0.00`, `0.35`, `0.55`, `0.75`, `0.85`, and
  `1.00`, then compared wider light coverage at `0.65` and `0.70`.
- Selected `Style 0.92 / 4 bands / top / Light Strength 0.60 / Light Range
  0.70 / Detail 1.00` for the owner-only print comparison. This preserved the
  lightest target, added dark connected wrinkle regions on the front, retained
  readable rear garment regions, and kept face/hand shadows in the warm recipe
  family instead of neutral grey.
- Generated one local Full Spectrum 32-state, 180 mm, 450,000-face 3MF using
  white, black, skin, and muted blue physical endpoints.
- The package passed every fail-closed package check. No input model, output,
  settings, hash, identifying filename, or private path entered the repository.

### Current state

- The detail layer remains opt-in and has no visible UI control. Existing
  projects remain unchanged at the exact default of zero.
- This selected profile is an owner comparison artifact, not a release default.
  Snapmaker Orca slicing and a physical print still remain required.
- The branch remains dirty and uncommitted; no release or publication action
  was taken.

### Next exact task

Open the new local 3MF in Snapmaker Orca, inspect front/side/back layer colours,
confirm that the dark wrinkle regions do not become isolated triangle speckle,
and check that face and hand shadows use the skin/black recipe family. If the
physical result is successful, expose a localized detail control that defaults
to zero and refreshes preview/3MF explicitly.

### Changed files

- Runtime and focused test files listed in the preceding source-detail
  checkpoint, plus this `HANDOFF.md` validation record.
- Local sweep/export helpers were adjusted outside the repository only.
- No file was staged, committed, pushed, packaged for release, uploaded, or
  published.

### Tests run

- Illustration-filter and Strong Cel focused set: 70 tests passed.
- Expanded illustration, Strong Cel, light/palette integration, GLB project,
  project bundle, GUI bundle, main shading bridge, and hotfix set: 176 tests
  passed.
- `git diff --check`: passed before this checkpoint and must be rerun after it.
- Generated 3MF: 10 ZIP members, CRC passed, 224,996 vertices, 450,000 faces,
  one watertight validated part, zero self-intersection warning parts, Full
  Spectrum 32 states, four physical filaments, no unsafe grouped cycle, and no
  surface shell.

### Do not do

- Do not publish the rights-controlled input or any local comparison/export
  artifact.
- Do not make Detail nonzero by default or call this a release preset before
  Orca slicing and physical validation.
- Do not weaken the topology, component, palette-state, or 3MF validation gates.
- Do not commit or push without explicit owner authorization.

### Local-only files

- Rights-controlled input, comparison grids, generated 3MF, preview, settings,
  report, guide, and helper scripts remain outside Git.

## 2026-08-31 Selective-highlight Strong Cel checkpoint

### Current objective

Add a separate, default-off Strong Cel trial that keeps most non-warm source
colour in a dark base, limits all lifted non-warm bands to a small coherent
surface fraction, darkens geometry-proven folds, and preserves warm skin.

### Completed in this session

- Added `illustration_selective_highlight_fraction`, accepted only as `0` or
  `0.05..0.12`. Zero is omitted from project JSON and preserves the existing
  Strong Cel/detail output exactly; no user-facing control was added.
- Added topology-capped selective tone generation. A single local-maximum face
  may seed growth, but the final lifted component must contain at least two
  faces and 0.5 square millimetres. Equal-score plateaus are accepted or
  rejected whole, the combined lifted area cannot exceed the requested
  fraction, and the peak band has its own 3 percent cap.
- Preserved warm faces at their ordinary Strong Cel RGB and band. Geometry
  crease evidence darkens only the darker owner face; a source-luma difference
  alone cannot create an outline. Missing, one-way, cross-part, oversized, or
  otherwise invalid topology fails closed to the ordinary result.
- Routed recolour/export and both automatic filament recommendation paths
  through the same authoritative selective face-tone helper. The legacy band
  smoothing/detail pass is skipped only when the selective profile actually
  applies; a failed trial continues through the exact established path.
- A synthetic 100-face test at `0.08` produces 8 percent combined lifted area,
  2 percent peak area, 40 percent mid-base, and 52 percent dark base without
  adding a band. Owner-side model sweeps at `0.05` and `0.07` also produced the
  intended visibly narrow lit regions.

### Current state

- The trial is implemented and reproducible through project settings, but is
  intentionally internal/default-off pending wider visual, slicer, and physical
  comparison. Existing Strong Cel at detail `0` or `1` remains unchanged when
  the selective fraction is zero.
- No requested band count, Flat Four four-state boundary, 3MF fail-closed
  check, topology gate, version, or release state was changed.
- The shared Windows working tree remains dirty and uncommitted. No package,
  upload, publication, commit, or push was performed.

### Next exact task

Compare `0`, `0.05`, `0.07`, and `0.08` with fixed filaments in front, side,
and rear views, then inspect the resulting layers in Snapmaker Orca. Confirm
that the non-warm band-2-plus-band-3 area stays within the requested cap, warm
skin remains unchanged, geometry folds do not become triangle noise, and a
coarse isolated face produces no highlight. Only after that comparison should
a localized preset/control be considered.

### Changed files

- `source/fixed_app/spectrum_mapper/models.py`
- `source/fixed_app/spectrum_mapper/illustration_filter.py`
- `source/fixed_app/spectrum_mapper/engine.py`
- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/spectrum_mapper/paint_gui.py`
- `source/fixed_app/test_illustration_filter.py`
- `source/fixed_app/test_strong_cel_print.py`
- `HANDOFF.md`

### Tests run

- `python -B -m compileall -q spectrum_mapper`: passed.
- Strong Cel, illustration, filament recommendation GUI, cel-light palette,
  new-model defaults, project bundle, and project bundle GUI focused set:
  156 tests passed.
- Regressions cover the exact default-off path, 8 percent combined lift cap,
  3 percent peak-only cap, indivisible oversized plateaus, isolated singleton
  rejection, malformed topology rejection, warm-face preservation, darker-side
  coherent crease ownership, project round-trip, and GUI proposal compatibility.
- PyMeshLab emitted its existing unavailable Qt-plugin warnings; no test failed
  or errored.

### Do not do

- Do not make the selective fraction nonzero by default or expose it in the UI
  before controlled layer and physical-print comparison.
- Do not split an equal-score plateau by face order, accept an isolated coarse
  face, cross a part boundary, or allow later smoothing/detail to grow a
  successfully capped lifted region.
- Do not darken warm skin through this trial or use source-luma contrast alone
  as crease evidence.
- Do not commit, push, package, upload, publish, or weaken topology, 3MF,
  palette-state, corresponding-source, or release gates.

### Local-only files

- All rights-controlled inputs, visual sweeps, 3MF outputs, reports, and helper
  scripts remain outside Git. No identifying model name or private path was
  added to this handoff.

## 2026-08-31 Selective-highlight performance checkpoint

### Current objective

Remove the multi-minute selective-highlight plateau-growth bottleneck without
changing whole-tie-group selection, area caps, topology gates, or output bands.

### Completed in this session

- Replaced the repeated full-face/full-edge scan inside every growth ring with
  a one-time sparse plateau adjacency graph and a maximum-score heap frontier.
- The frontier still accepts or rejects every currently exposed equal-score
  plateau group as one unit. Newly exposed higher-score plateaus return to the
  same heap, so the result does not assume monotonic geometry or depend on face
  or component numbering.
- Added an exact-reference regression covering 40 deterministic randomized
  reciprocal graphs. The new selected-component mask and accumulated area
  match the former full-edge algorithm exactly in every case.
- An in-memory 450,000-plateau chain benchmark selected 36,000 plateaus (8
  percent) in 0.192 seconds for the growth helper. This benchmark isolates the
  removed quadratic scan; complete model preparation and mapping still include
  other geometry, Lab, recommendation, and 3MF work.

### Current state

- The optimized growth path is active only when the default-off selective
  profile is enabled. Existing Strong Cel and failed selective profiles retain
  their previous paths.
- No cap, plateau grouping rule, warm-face behavior, crease rule, requested
  band count, Flat Four boundary, or fail-closed check was changed.
- The working tree remains dirty and uncommitted; no package, upload, commit,
  or push was performed.

### Next exact task

Repeat one 80,000-face preview and one 450,000-face automatic recommendation
with the same settings used before optimization. Record end-to-end wall time,
confirm the same lifted-area distribution and filament proposal, and profile
the remaining stages only if the complete operation is still unexpectedly
slow.

### Changed files

- `source/fixed_app/spectrum_mapper/engine.py`
- `source/fixed_app/test_strong_cel_print.py`
- `HANDOFF.md`

### Tests run

- `python -B -m compileall -q spectrum_mapper`: passed.
- Strong Cel, illustration, filament recommendation GUI, cel-light palette,
  new-model defaults, project bundle, and project bundle GUI focused set:
  157 tests passed.
- The randomized old-versus-new growth equivalence test passed all 40 cases.
- `git diff --check`: passed.
- PyMeshLab emitted its existing unavailable Qt-plugin warnings; no test failed
  or errored.

### Do not do

- Do not replace whole-score frontier groups with per-face or per-component
  truncation merely to hit the requested percentage exactly.
- Do not remove reciprocal-topology, final component, area, part-boundary, or
  fail-closed gates for additional speed.
- Do not treat the isolated helper benchmark as complete preview/export time.
- Do not commit, push, package, upload, publish, or change release state.

### Local-only files

- No model, preview, 3MF, benchmark artifact, binary, cache, identifying name,
  or private path was added to Git.

## 2026-08-31 Selective-highlight owner comparison checkpoint

### Current objective

Produce a human-review reference for the default-off selective trial and
separate artistic judgement from source-model colour-area matching.

### Completed in this session

- Compared the same prepared preview with 5, 8, and 12 percent lifted-area
  caps, three key-light directions, three style amounts, and three internal
  fold-response values while retaining one fixed four-filament palette.
- Chose 5 percent as the conservative reference for this dark-clothing case:
  it retains narrow chest, sleeve, and hem accents while avoiding the broad
  lifted panels seen in the established Strong Cel path.
- Generated two local-only validated 450,000-face Full Spectrum 3MF references:
  one with the fixed white/black/skin/cool-blue palette used by the comparison,
  and one with the current automatic filament proposal.
- Wrote a local-only Japanese adjustment guide that treats surface percentage
  only as an anti-runaway control, not as similarity to the source model. It
  recommends deciding light direction, lifted area, shadow depth, light
  strength, bands, and finally contour response in that order.
- Confirmed that the existing internal detail value is not a useful independent
  contour-strength control on this sample. A future UI should expose contour
  policy separately from light direction, lifted area, and shadow depth.

### Current state

- The fixed-palette 450,000-face reference completed in 125.350 seconds after
  the growth optimization; the automatic-palette reference completed in
  150.052 seconds. Both passed the package checks recorded below.
- A 12-variant 80,000-face visual control study, including one full geometry
  preparation, completed in about 67 seconds after optimization.
- This remains an internal/default-off source trial. No UI control, build,
  release, publication, commit, or push was made.

### Next exact task

Review the fixed-palette reference in Snapmaker Orca and compare the 5, 8, and
12 percent images by eye. Decide whether the intended product control should be
named `Highlight Area` and whether contour should be a three-state policy
(`Outer`, `Outer + Crease`, `Outer + Crease + Proven Fold`) before adding UI.

### Changed files

- `HANDOFF.md`

### Tests run

- Independent `test_strong_cel_print` plus `test_illustration_filter`: 77 tests
  passed.
- `python -m compileall -q spectrum_mapper`: passed.
- `git diff --check`: passed.
- Both generated 3MF packages passed CRC, 10-entry structure, 450,000-face,
  one-part watertight/validated-solid, strict-zero self-intersection, Full
  Spectrum 32-state, four-physical-filament, no-unsafe-cycle, and surface-shell
  disabled checks.
- The local review ZIP contains 15 members and passed `ZipFile.testzip()`.
- PyMeshLab emitted its existing unavailable Qt-plugin warnings only.

### Do not do

- Do not judge this stylized result by matching its colour-area percentages to
  the source GLB; percentages are an internal cap, and visual judgement is the
  acceptance criterion.
- Do not expose the internal detail value as `Contour Strength`; it showed too
  little independent effect and controls a different mechanism.
- Do not publish or commit any local reference, rights-controlled input,
  derived 3MF, comparison image, guide, helper script, or identifying path.

### Local-only files

- The two 3MF references, visual control grid, Japanese guide, ZIP, settings,
  reports, previews, and helper scripts remain outside Git.

## 2026-08-31 Selective-highlight Windows test UI checkpoint

### Current objective

Expose the owner-requested selective-highlight trial in the Windows manual
editor without changing the default Strong Cel result or publishing it as a
normal release.

### Completed in this session

- Added a bilingual `Highlight Area` control to the High-Contrast Cel section
  with exactly four presets: `Standard`, `5% (Recommended)`, `8%`, and `12%`.
- Kept `Standard` at the exact default-off value `0.0`; existing projects and
  ordinary Strong Cel therefore retain the established output unless the
  owner deliberately selects a capped-area preset.
- Disabled all four presets outside High-Contrast Cel while retaining the
  chosen value for a later return to that mode.
- Connected the control to the existing tone callback, parent/editor bridge,
  and project-backed `ToneSettings` field. Parent-approved tone reapplication
  restores the visible percentage without rounding the stored fraction.
- Added Japanese and English labels and live language-refresh coverage.

### Current state

- The control is source-complete and regression-tested for a local Windows
  evaluation build. No commit, push, package, upload, or public release was
  performed in this checkpoint.
- The previous prohibition on exposing the value before owner review is
  superseded only for this explicitly requested local test build. The public
  default and published release remain unchanged.

### Next exact task

Create a fresh local-only standalone Windows test ZIP from this exact dirty
working tree, run packaged self-test and Japanese/English UI smoke, then ask
the owner to compare `Standard`, `5%`, `8%`, and `12%` on the same model and
view direction.

### Changed files

- `source/fixed_app/spectrum_mapper/paint_gui.py`
- `source/fixed_app/spectrum_mapper/i18n.py`
- `source/fixed_app/test_manual_shading_ribbon.py`
- `source/fixed_app/test_main_shading_bridge.py`
- `HANDOFF.md`

### Tests run

- Manual shading UI, main/editor bridge, i18n, project bundle, illustration,
  and Strong Cel focused set: 151 tests passed with zero failures.
- Live Tk coverage confirms the presets are disabled outside High-Contrast
  Cel, enabled inside it, and relabelled correctly in Japanese and English.
- `python -m compileall -q source/fixed_app`: passed.
- `git diff --check`: passed.
- PyMeshLab emitted its existing unavailable Qt-plugin warnings only.

### Do not do

- Do not make `5%`, `8%`, or `12%` the silent default; `Standard` must remain
  byte-compatible with the established default-off path.
- Do not present this local test control or any resulting binary as a new
  public stable release without exact-current packaging/compliance evidence.
- Do not commit, push, publish, or include private models or generated 3MF
  output as part of this checkpoint.

### Local-only files

- The future Windows test build, ZIP, extracted smoke-test copy, private
  models, and generated comparison outputs remain outside Git.

## 2026-08-31 Selective-highlight owner-only Windows build checkpoint

### Current objective

Produce the explicitly requested standalone Windows comparison build for the
new `Highlight Area` presets without weakening or bypassing the public binary
and corresponding-source gates.

### Completed in this session

- Built a fresh PyInstaller 6.20.0 one-folder application with Python 3.13.14
  from the exact current dirty working tree and an isolated native search path.
- Added a local-only Japanese test guide beside the executable. It documents
  `Standard`, `5% (Recommended)`, `8%`, and `12%`, the recommended initial
  Strong Cel values, six-direction comparison, and Snapmaker Orca checks.
- Created a canonical owner-only ZIP whose root and filename contain
  `WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE`.
- The archive contains 1,456 files and no OBJ, GLB, glTF, 3MF,
  `direct_url.json`, or reparse point. Canonical path, original-name, CRC-32,
  and exact file-list checks passed.
- Independently extracted the ZIP and byte-compared all 1,456 relative files
  against the build tree by size and SHA-256 with zero missing, extra, or
  mismatched files.

### Current state

- Owner-only archive:
  `ChromaMatter-0.8beta-SelectiveHighlight-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260831-win64.zip`.
- Archive size: 117,696,704 bytes. SHA-256:
  `BA46BB0242394D3CF380E9E73864A36D30E8A60D0F2A57259AA55066E78953E4`.
- The built and fresh-extracted executables report FileVersion and
  ProductVersion `0.8beta`.
- This is a local visual-comparison build only. It was not committed, pushed,
  uploaded, published, or presented as a redistributable release.
- The public inventory/corresponding-source gate remains closed. The current
  inventory generator rejected the changed controlled PyTetWild recipe byte
  identity, as intended. The archive must not be redistributed until that
  exact-source evidence is rebuilt and approved.

### Next exact task

Use the same local OBJ or GLB and unchanged F1-F4 palette to compare
`Standard`, `5%`, `8%`, and `12%` from the front and rear. Export the preferred
setting, inspect all sides and layer colors in Snapmaker Orca, and report any
isolated triangle, lost skin color, broad bright panel, or dark merged region.

### Changed files

- Source/test files listed in the preceding Windows test UI checkpoint.
- `HANDOFF.md`.
- The guide, build tree, smoke profiles, fresh extraction, and ZIP are local
  only and remain outside Git.

### Tests run

- Independent focused UI/bridge/project/Strong Cel/i18n set: 151 tests passed.
- `python -B -m compileall -q source/fixed_app/spectrum_mapper`: passed.
- Fresh PyInstaller one-folder build: passed.
- Built-tree packaged `--self-test`: passed.
- Built-tree isolated Japanese and English `--ui-smoke`: passed.
- Canonical ZIP validation: 1,456 members passed path, CRC-32, and exact-list
  checks.
- Fresh extraction parity: 1,456 source / 1,456 extracted, zero missing,
  extra, size, or SHA-256 mismatches.
- Fresh-extracted packaged `--self-test` and isolated Japanese/English
  `--ui-smoke`: passed.
- `git diff --check`: passed before this appended checkpoint and must be run
  once more after it.
- The full release-oriented test entry was not accepted as release evidence:
  its compliance fixtures encountered the already-known exact-source/native
  evidence failures, and the run was stopped before packaging. Those failures
  were not bypassed.

### Do not do

- Do not redistribute, upload, publish, release, or treat this ZIP as public
  binary evidence.
- Do not make a capped highlight preset the default, weaken topology/3MF
  checks, or bypass the controlled-build/corresponding-source gates.
- Do not commit or push without an explicit owner request.

### Local-only files

- The owner-only ZIP, build/work tree, smoke profiles, fresh extraction, test
  guide, private models, and generated 3MF comparisons remain outside Git.

## 2026-08-31 Selective-contour policy UI checkpoint

### Current objective

Let the owner compare three conservative contour-face policies inside the
Selective Highlight trial without changing the established default output or
turning the option into authored line art.

### Completed in this session

- Added `ToneSettings.illustration_contour_policy` with `outer`,
  `outer_crease`, and `outer_crease_fold`; validation rejects any other value.
- Kept `outer_crease_fold` as the default and exact historical evidence union:
  silhouette, strong crease, and geometry-supported confirmed fold.
- Restricted `outer` to silhouette evidence and `outer_crease` to silhouette
  plus strong-crease evidence. The existing darker-owner, two-face/0.5 mm2,
  warm-material preservation, part-local topology, and fail-closed gates are
  unchanged.
- Added three Japanese/English Manual Editing radio choices immediately after
  `Highlight Area`. They are enabled only for High-Contrast Cel with a 5%, 8%,
  or 12% selective-highlight preset; the chosen value is retained while the
  controls are disabled.
- Added explanatory copy clarifying that this assigns nearby faces to an
  existing darker print colour and does not draw lines.
- Preserved legacy project structure: the contour key is removed while the
  illustration filter is off and is also omitted for the active default
  `outer_crease_fold`; a non-default active selection round-trips.
- Propagated the policy through the main/editor tone bridge, mix-optimizer cache
  identity, selective engine path, and report metadata.

### Current state

- Source and focused tests are green. No executable was rebuilt in this
  checkpoint.
- The preceding owner-only Selective Highlight ZIP predates these source bytes
  and does not contain the new contour controls. It is now stale evidence and
  must not be presented as this checkpoint's package.

### Next exact task

Build a fresh owner-only Windows comparison ZIP from these exact working-tree
bytes, then compare all three contour policies on the same model, palette,
view, and 5% Highlight Area before deciding which policy should remain the
default.

### Changed files

- `source/fixed_app/spectrum_mapper/models.py`
- `source/fixed_app/spectrum_mapper/engine.py`
- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/spectrum_mapper/paint_gui.py`
- `source/fixed_app/spectrum_mapper/i18n.py`
- `source/fixed_app/test_strong_cel_print.py`
- `source/fixed_app/test_illustration_filter.py`
- `source/fixed_app/test_manual_shading_ribbon.py`
- `source/fixed_app/test_main_shading_bridge.py`
- `source/fixed_app/test_black_free_gradient.py`
- `HANDOFF.md`

### Tests run

- Focused Strong Cel, illustration, live Manual Editing UI, main/editor bridge,
  report, project bundle, i18n, filament proposal, and new-model default set:
  221 tests passed with zero failures.
- A narrower post-edit Manual Editing/main bridge rerun: 15 tests passed with
  zero failures.
- `python -m compileall -q source/fixed_app/spectrum_mapper`: passed.
- `git diff --check`: passed before this appended checkpoint and must be run
  once more after it.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not broaden any policy beyond its named geometry evidence or remove the
  darker-owner/coherence/warm/fail-closed guards.
- Do not change the default away from `outer_crease_fold` until visual and Orca
  comparison evidence justifies a separate owner decision.
- Do not reuse the earlier Windows ZIP as package evidence for these bytes.
- Do not commit, push, publish, or distribute without explicit owner approval
  and exact-current package/compliance validation.

### Local-only files

- Any future comparison build/ZIP, private models, generated 3MF files,
  screenshots, and source-vault transfer archives remain outside Git.

## 2026-08-31 Selective-contour owner-only Windows build checkpoint

### Current objective

Provide the owner with a standalone Windows comparison build containing the
three new conservative contour-face policies, while keeping the public binary
and corresponding-source gates closed.

### Completed in this session

- Built a fresh PyInstaller 6.20.0 one-folder application with Python 3.13.14
  from the exact current dirty working tree.
- Included a local-only Japanese guide covering Highlight Area, all three
  contour choices, recommended comparison conditions, 3MF export, and Orca
  inspection.
- Repacked the archive with the short internal root `ChromaMatter/`. The first
  validation archive used a long internal folder name and exceeded the legacy
  Windows 260-character path limit in the intentionally long validation
  destination; that archive was superseded and retained only as a local
  diagnostic backup.
- Verified that the corrected ZIP contains 1,456 files and no OBJ, GLB, glTF,
  3MF, `direct_url.json`, or reparse point.
- Extracted the corrected ZIP to a clean short path and byte-compared all
  1,456 relative files against the build tree using SHA-256 with zero missing,
  extra, or mismatched files.

### Current state

- Owner-only archive:
  `ChromaMatter-0.8beta-SelectiveHighlight-ContourPolicy-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260831-win64.zip`.
- Archive size: 114,782,891 bytes. SHA-256:
  `5C35329C29BCD98C0EAC35FE5CF1A283593E898FA2534EDFCE9C162CEC04D28B`.
- The archive root is `ChromaMatter/`; the deepest path in the clean short-path
  extraction was 134 characters.
- This is an unsigned local owner-comparison build only. It was not committed,
  pushed, uploaded, published, or presented as redistributable.
- The public inventory/corresponding-source gate remains closed; no gate was
  bypassed or weakened for this build.

### Next exact task

Extract the ZIP, open the same local OBJ or GLB with the same F1-F4 palette,
select High-Contrast Cel plus 5% Highlight Area, and compare `Silhouette Only`,
`Silhouette + Sharp Edges`, and `Silhouette + Edges + Confirmed Folds` from all
six views. Export the preferred result and inspect colour regions and layers in
Snapmaker Orca.

### Changed files

- Source and test files listed in the preceding Selective-contour policy UI
  checkpoint.
- `HANDOFF.md`.
- Build trees, smoke profiles, diagnostic extraction, guide, and ZIP remain
  local only and outside Git.

### Tests run

- Independent focused Strong Cel, illustration, Manual Editing UI,
  main/editor bridge, project bundle, i18n, filament, and defaults set:
  222 tests passed with zero failures.
- `python -B -m compileall -q source/fixed_app`: passed.
- Built-tree packaged `--self-test`: passed.
- Built-tree isolated Japanese and English `--ui-smoke`: passed.
- Corrected ZIP validation: 1,456 files under `ChromaMatter/`.
- Corrected clean extraction parity: 1,456 source / 1,456 extracted, zero
  missing, extra, or SHA-256 mismatches.
- Corrected fresh-extracted packaged `--self-test`: exit 0.
- Corrected fresh-extracted isolated Japanese and English `--ui-smoke`: exit
  0 for both languages.
- `git diff --check`: must be run once more after this appended checkpoint.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not redistribute, upload, publish, or release this owner-only ZIP.
- Do not remove the contour evidence/coherence/warm/fail-closed guards or
  weaken topology/3MF validation.
- Do not change version `0.8beta`, commit, or push without an explicit owner
  request.

### Local-only files

- The corrected owner-only ZIP, superseded long-root diagnostic archive, build
  tree, smoke profiles, fresh extraction, test guide, private models, and
  generated 3MF comparisons remain outside Git.

## 2026-08-31 Compact shading sub-pages checkpoint

### Current objective

Reduce the Manual Editing shading ribbon height while retaining every existing
tone, 2D-colour, mix-optimization, and in-face correction control and callback.

### Completed in this session

- Replaced the four vertically stacked shading groups with one compact row of
  four session-only sub-pages: `Tone`, `2D Color`, `Mixes`, and `In-face`
  (`全体`, `2D彩色`, `混色`, `面内補正` in Japanese).
- Kept the existing four frames alive in the same grid cell and changed only
  their visibility. The initial page is 2D Color; no ToneSettings or project
  schema field was added.
- Preserved the selected sub-page through live language changes and ribbon
  collapse/re-expansion without recreating controls, callbacks, or the public
  `auto_shading_host` extension surface.
- Moved the long mix-optimization explanation to a wrapped second row and
  placed the in-face hotfix host below its heading to cap English width.
- Added live Tk regressions for Japanese/English labels, exactly one visible
  sub-page, frame/host identity, value retention, ribbon folding, and page
  dimensions. Strong Cel remains within a 300-pixel shading-page height and
  each tested sub-page remains within 1080 pixels width.

### Current state

- Source and focused tests are green. No executable, ZIP, commit, push, upload,
  or publication was produced for these changed bytes.
- The previous owner-only comparison ZIP predates this layout change and is
  stale package evidence.

### Next exact task

Open Manual Editing at 1480 x 900 in Japanese and English, switch through all
four shading sub-pages, and visually confirm that the 2D Color controls remain
comfortable to use before building any new owner-only comparison package.

### Changed files

- `source/fixed_app/spectrum_mapper/paint_gui.py`
- `source/fixed_app/test_manual_shading_ribbon.py`
- `HANDOFF.md`

### Tests run

- Manual shading, main/editor bridge, i18n, and production hotfix focused set:
  82 tests passed with zero failures.
- `python -B -m compileall -q source/fixed_app`: passed.
- `git diff --check`: passed before this handoff append and must be run once
  more after it.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not persist the shading sub-page choice into projects or recreate any of
  the four control frames while switching pages.
- Do not replace or move the public `auto_shading_host` contract, weaken any
  shading, topology, 3MF, or palette-state safety guard, or reuse the stale
  owner-only ZIP as evidence for these bytes.
- Do not change version `0.8beta`, commit, push, package, upload, or publish
  without the project owner's explicit authorization and exact-current gates.

### Local-only files

- No model, screenshot, generated 3MF, binary, archive, smoke profile, cache,
  private path, or identifying asset was added to Git.

## 2026-08-31 Compact shading and palette-flow owner test checkpoint

### Current objective

Make the Manual Editing shading ribbon compact and make manual F1-F4 edits
behave predictably when `Common to All` is selected, without weakening the
Full Spectrum pending/export guard or changing existing manual colour IDs.

### Completed in this session

- Kept the compact four-page shading ribbon from the preceding checkpoint:
  `Tone`, `2D Color`, `Mixes`, and `In-face`, with `2D Color` selected first.
- When `Common to All` is active, valid manual F1-F4 changes now synchronize
  the physical HEX values and compatible filament references into existing
  explicit part palettes. Per-part mix ratios, output ratios, state routing,
  assignment snapshots, and manual face corrections remain intact.
- Flat Four now refreshes the whole model and any open Manual Editing window
  immediately. Its redundant Apply button is hidden and replaced by a short
  immediate-application explanation.
- Full Spectrum still stages physical-colour changes and blocks 3MF export
  until they are applied. With `Common to All` selected, the single clearly
  labelled Apply action now refreshes the whole model and clears the staged
  targets together.
- The old whole-palette copy action is hidden for `Common to All`; it is shown
  only for an individual part and is labelled as copying that part's complete
  four-colour setup to every part.
- Preserved the mode-specific result message from reference-image F1-F4
  sampling instead of overwriting it with obsolete generic Apply guidance.
- Built a fresh unsigned owner-comparison Windows one-folder application from
  the exact current working tree and packaged it under the short
  `ChromaMatter/` archive root with a local Japanese test guide.

### Current state

- Local owner-only archive:
  `ChromaMatter-0.8beta-CompactShading-PaletteFlow-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260831-win64.zip`.
- Size: 118,598,951 bytes. SHA-256:
  `B6055AA0C9BACEEB3B03E84B801777A54B5BB30F8F296662B091B15E7D3ABA81`.
- The archive has 1,500 files and passed full byte/hash parity after a fresh
  extraction. It contains no OBJ, GLB, glTF, 3MF, `direct_url.json`, or
  reparse point.
- This remains a dirty-working-tree, unsigned, owner-comparison build. It was
  not committed, pushed, uploaded, published, or approved for redistribution.
- Version remains `0.8beta`; topology and 3MF fail-closed validation were not
  changed.

### Next exact task

Open the new owner-only build with a representative multipart model. In Flat
Four, edit F1-F4 while `Common to All` is selected and confirm every part and
the preview update immediately. In Full Spectrum, confirm the one common Apply
action updates the whole model and that export remains blocked before Apply.
Then open Manual Editing and visually check all four shading sub-pages in both
Japanese and English at the normal 1480 x 900 window size.

### Changed files

- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/spectrum_mapper/i18n.py`
- `source/fixed_app/spectrum_mapper/paint_gui.py`
- `source/fixed_app/test_manual_palette_apply.py`
- `source/fixed_app/test_manual_shading_ribbon.py`
- `HANDOFF.md`

### Tests run

- Integrated palette, shading, i18n, Flat Four, part, project, and hotfix set:
  219 tests passed with zero failures.
- Final palette/i18n rerun after status-copy cleanup: 42 tests passed.
- Source `--self-test`: passed.
- Source Japanese and English `--ui-smoke`: passed.
- `python -B -m compileall -q source/fixed_app`: passed.
- Fresh PyInstaller 6.20.0 / Python 3.13.14 one-folder build: passed.
- Built-tree packaged `--self-test` and isolated Japanese/English
  `--ui-smoke`: passed.
- Fresh ZIP extraction parity: 1,500 source / 1,500 extracted files, zero
  missing, extra, size, or SHA-256 mismatches.
- Fresh-extracted packaged `--self-test` and isolated Japanese/English
  `--ui-smoke`: passed.
- `git diff --check`: must be rerun after this appended checkpoint.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not remove the Full Spectrum pending/export guard, rewrite per-part mix or
  state routing during a Common F1-F4 edit, or weaken topology/3MF validation.
- Do not persist the shading sub-page choice into project files or recreate
  the control frames while switching pages.
- Do not redistribute, upload, publish, or present the owner-only ZIP as a
  release artifact.
- Do not change version `0.8beta`, commit, or push without explicit owner
  instruction.

### Local-only files

- The owner-only ZIP, PyInstaller build/work tree, isolated smoke profiles,
  fresh extraction, and Japanese test guide remain outside Git.

## 2026-09-01 radial binary64 serialization precision checkpoint

### Current objective

Prevent valid thin selective-hybrid material regions from collapsing when the
radial 3MF package and its exact-partition proof enter archive coordinate
space, without weakening any geometry or archive validator.

### Completed in this session

- Identified that the ordinary 3MF writer preserves binary64 coordinates with
  17 significant digits while the radial writer and hybrid partition keys
  used only 12.
- Changed both radial paths to 17 significant digits. Distinct binary64
  vertices therefore remain distinct after XML serialization, while exact
  shared interfaces still compare in the same archive coordinate space.
- Added regressions using a positive-volume thin region whose vertices are
  distinct in binary64 but collide at 12 significant digits. The hybrid
  package proof and full radial write/reopen path now both pass.

### Current state

- The precision-only fix is present in the dirty, uncommitted working tree.
- No topology, manifold, winding, signed-volume, exact-interface, archive
  reopen, or fail-closed policy was relaxed.
- No private model, generated 3MF, binary, archive, commit, push, or
  publication was produced by this focused task.

### Next exact task

Retry the separately held owner-only selective-hybrid export once with the
same settings. If it passes packaging, complete the existing independent 3MF
reopen checks and inspect every layer in Orca before any physical print. Treat
any new geometry or validation error as a separate fail-closed condition.

### Changed files

- `source/fixed_app/spectrum_mapper/radial_export.py`
- `source/fixed_app/spectrum_mapper/radial_hybrid_export.py`
- `source/fixed_app/test_radial_export.py`
- `source/fixed_app/test_radial_hybrid_export.py`
- `HANDOFF.md`

### Tests run

- Core radial writer/hybrid regression: 14 / 14 passed.
- Radial writer, hybrid, Stage B, workflow, thickness, and visual-proof set:
  57 / 57 passed.
- Black/compact coupon and variable-skin head set: 32 / 32 passed.
- Touched-file `py_compile`: passed.
- `git diff --check`: passed before this handoff append and must be rerun.

### Do not do

- Do not reduce coordinate precision again, quantize exact interfaces, or
  weaken zero-area, manifold, winding, volume, partition, or archive-reopen
  validation to make an export succeed.
- Do not treat the precision fix as physical-print evidence or print before
  complete slicer inspection.
- Do not change `0.8beta`, commit, push, package, upload, or publish without
  explicit owner authorization and the applicable current-tree gates.

### Local-only files

- The private input and any independently generated validation output remain
  outside Git and are not identified in this handoff.

## 2026-09-01 Corrected radial visual proof, OBJ, and Windows owner build

### Current objective

Replace the invalid synthetic-head hybrid artifacts with a proof set that
separates visible five-tone appearance from physical radial-shell geometry,
make the bundled OBJ reopen through ChromaMatter's actual vertex-colour path,
and provide a fresh owner-only Windows build containing the deep-partner
safety fix.

### Completed in this session

- Added an independent analytic visual-proof generator. The LOOK ONLY 3MF
  visibly carries five white-to-black states. The radial 3MF carries five
  closed F2 shells around closed F1 cores at 0.10 / 0.18 / 0.26 / 0.34 /
  0.42 mm; its normal surface is intentionally F2-only and its proof is the
  sliced middle-layer cross-section near Z=6 mm.
- Added a ChromaMatter-compatible test OBJ. Every vertex line is
  `v X Y Z R G B`; planar inset subdivision preserves a closed source surface
  while 88.82 percent of its area carries exact categorical palette colours.
- Added an actual-3MF XML regression that ignores self-declared metadata and
  re-derives core/shell topology, opposite shared-interface winding, volume,
  and all five interface distances from serialized mesh coordinates.
- Preserved the adaptive safety boundary: the generic coarse head cannot
  satisfy the 0.10 mm sampled-distance contract, so it leaves no hybrid 3MF,
  manifest, or archive. The analytic proof is explicitly not evidence that an
  arbitrary AI model passed production adaptive partitioning.
- Built a fresh Python 3.13.14 / PyInstaller 6.20.0 Windows one-folder app from
  the exact corrected dirty working tree and packaged it with a corrected
  Japanese owner guide.

### Current state

- Corrected proof/OBJ ZIP (local Desktop only):
  `ChromaMatter-Radial-Visual-Proof-CORRECTED-20260901.zip`.
- Proof ZIP size: 159,695 bytes. SHA-256:
  `076719DF846EA6727CF6D0ADC0FAA6A278BE1040A19D7F0C985E830A5AEC1C26`.
- Corrected Windows owner-only ZIP (local Desktop only):
  `ChromaMatter_0.8beta_VariableSkin_CORRECTED_Windows_OWNER_ONLY_INTERNAL_NON-DISTRIBUTABLE_20260901.zip`.
- Windows ZIP size: 117,584,952 bytes. SHA-256:
  `366FD1AE5C356BED6B93EAF4791EBF9DBF999A33CD0B4B239B058BA53528E4CC`.
- The version remains `0.8beta`. Neither ZIP was uploaded, published,
  committed, or pushed.
- Public binary compliance remains intentionally fail-closed on
  `Controlled PyTetWild recipe byte count changed`; no contract, expected
  byte count, or gate was altered.

### Next exact task

Open `07_ChromaMatter_import_test_head.obj` in the corrected Windows build and
confirm the five broad tone bands plus pure black/white/brown details. In
Snapmaker Orca, use `00_REFERENCE_LOOK_ONLY_visible_cel_bands.3mf` only for
visible shade order. Slice `06_RADIAL_SECTION_5BAND.3mf` at 0.10 mm and inspect
the middle layer near Z=6 mm in Filament or Line Type view; record whether the
0.10 and 0.18 mm shells disappear or widen with a 0.4 mm nozzle. Do not use
the older head hybrid files.

### Changed files

- `source/fixed_app/spectrum_mapper/color_depth_exact_partition.py`
- `source/fixed_app/spectrum_mapper/radial_stage_b.py`
- `source/fixed_app/spectrum_mapper/variable_skin_head_coupon.py`
- `source/fixed_app/spectrum_mapper/radial_visual_proof.py` (new)
- `source/fixed_app/test_color_depth_exact_partition.py`
- `source/fixed_app/test_radial_stage_b.py`
- `source/fixed_app/test_variable_skin_head_coupon.py` (new)
- `source/fixed_app/test_radial_visual_proof.py` (new)
- `HANDOFF.md`

Other dirty working-tree changes are pre-existing user-owned work and remain
preserved.

### Tests run

- Root integrated adaptive partition, Stage B, head fail-close, proof/OBJ,
  thickness, hybrid writer, workflow, and radial writer: 74 / 74 passed.
- Independent focused review: 57 / 57 passed; legacy / Stage A: 24 / 24
  passed; zero skips.
- Passing six-band adaptive fixture: 9,120 cells, 592.71137777897 mm3,
  unsafe cells and unsafe partner volume both zero; maximum sampled overdepth
  by band 0.00100--0.00304 mm under the fixed 0.05 mm limit.
- Actual corrected radial 3MF re-read from ZIP/XML without metadata: all five
  core/shell pairs closed and winding-consistent; 12 opposite shared triangles
  per band; volume residual at most 1.137e-13 mm3; all five interface distances
  matched their analytic values.
- OBJ actual load and standard prepare: 1,458 XYZRGB vertices, 2,912 faces,
  boundary and non-manifold edges zero, watertight, 17,496.0 mm3 before and
  after reload.
- Fresh PyInstaller build, built-tree packaged self-test, and isolated Japanese
  and English UI smoke: passed.
- Windows ZIP canonical/case/CRC audit and fresh extraction parity:
  1,456 / 1,456 files matched by relative path, length, and SHA-256.
- Fresh-extracted packaged self-test and isolated Japanese and English UI
  smoke: passed. Required corrected radial modules were present in the frozen
  executable archive.
- A broad repository discovery was not used as the green functional gate: its
  public-compliance tests stop on the unchanged PyTetWild recipe byte-count
  mismatch. The corresponding focused functional and legacy suites above are
  green; the public inventory probe exited 1 and emitted no SBOM/component map.
- `git diff --check`, `git diff --stat`, and final `git status` must be recorded
  after this append.

### Do not do

- Do not describe the finite 15-point/cell and 7-point/interface sampled
  distance contract as a mathematical all-points continuum proof.
- Do not force a generic model through after `localized_threshold_interface_too_deep`
  or `adaptive_partner_cell_too_deep`; retain the fail-closed result.
- Do not reuse or redistribute either the old invalid head bundle or the
  superseded pre-fix Windows ZIP.
- Do not publish or redistribute the corrected Windows ZIP while the public
  compliance gate remains closed.
- Do not change version `0.8beta`, commit, push, upload, or publish without
  explicit owner authorization.

### Local-only files

- Corrected proof folder/ZIP and the retained invalid diagnostic folders on
  the Desktop.
- Corrected build/work/stage/fresh-extraction/smoke evidence under
  `C:\ChromaMatterTestBuilds\VariableSkin-Corrected-20260901`.
- Corrected owner-only Windows ZIP and its Japanese guide. No generated 3MF,
  OBJ, private model, binary, or package was added to Git.

## 2026-09-01 Adaptive variable-skin deep-partner safety checkpoint

### Current objective

Prevent adaptive multi-threshold Stage B from emitting partner material deeper
than the requested 0.10--0.42 mm shell while preserving uniform and legacy
partition behaviour.

### Completed in this session

- Localised adaptive unsafe columns instead of propagating outer material
  through their full depth; unresolved interfaces now fail closed.
- Added true closest-source checks at 15 points per partner tetrahedron and 7
  points per material-changing interface triangle.
- Added an independent Stage-B 15-point distance check that does not trust a
  partition provider's proof metadata.
- Added the 48-face coarse-box regression for the former deep-partner leak and
  a passing six-band adaptive proof fixture.
- Removed the invalid five-hybrid head-bundle success regression. The coarse
  head now explicitly stops before any hybrid, manifest, or bundle archive is
  emitted; its standalone vertex-colour OBJ and preview remain validated.

### Current state

- Production adaptive geometry is fail-closed when the requested shell cannot
  be represented within the fixed 0.05 mm overdepth tolerance.
- The coarse synthetic head does not currently produce a production adaptive
  hybrid; this is intentional and must not be described as a successful
  arbitrary-mesh partition.
- The separate visual proof is an analytic validation coupon and does not claim
  that arbitrary production meshes passed the adaptive partition.

### Next exact task

Run broader exact-current regression, then independently inspect the analytic
visual-proof 3MF in the target slicer. Do not re-enable the invalid coarse-head
hybrid path unless it satisfies the same independent distance proof.

### Changed files

- `source/fixed_app/spectrum_mapper/color_depth_exact_partition.py`
- `source/fixed_app/spectrum_mapper/radial_stage_b.py`
- `source/fixed_app/test_color_depth_exact_partition.py`
- `source/fixed_app/test_radial_stage_b.py`
- `source/fixed_app/test_variable_skin_head_coupon.py`
- `HANDOFF.md`

### Tests run

- Adaptive exact partition, Stage B, radial workflow, hybrid export, head
  fail-close/source, and analytic visual proof: 57 tests passed, zero failures,
  zero skips.
- Touched-source `py_compile`: passed.
- `git diff --check`: passed before this handoff append and must be rerun.

### Do not do

- Do not weaken the 0.05 mm partner-depth gate or trust provider metadata in
  place of Stage-B's independent source-distance check.
- Do not publish or reuse the invalid earlier coarse-head hybrid outputs.
- Do not change version `0.8beta`, commit, push, or publish without explicit
  owner authorization.

### Local-only files

- Geometry audit output and generated visual-proof bundles remain outside Git.
  No private model or generated 3MF was added to the repository.

## 2026-09-01 SUPERSEDED / INVALID Variable-skin synthetic-head checkpoint

**Do not use the five hybrid 3MF files recorded in this historical
checkpoint.** A later independent mesh audit found that the partner material
occupied 29.40 percent of the solid and reached 8.719 mm from the source
surface despite a requested maximum of 0.42 mm. The corrected safety
checkpoint above replaces these geometry claims. The old Desktop folder is
marked `INVALID_DO_NOT_USE.md` and is retained only as diagnostic evidence.

### Current objective

Test whether selective black-core radial conversion can use a target-colour-
dependent partner skin to create printable lightness bands, while preserving
pure black and keeping low-Delta-L-star colours on the conventional carrier.
Provide a small original head-shaped comparison coupon without presenting the
experiment as production-ready for arbitrary models.

### Completed in this session

- Added an explicit `uniform` / `adaptive` partner-skin mode for Selective
  Hybrid. Legacy or missing project data remains `uniform`, and normal 3MF plus
  uniform Stage A behaviour is unchanged.
- Added deterministic target-L-star mapping to four through six thickness
  bands. Partial or extra state maps, part-palette HEX override differences,
  invalid ranges, and unrepresentable material visibility fail closed.
- Corrected multi-threshold depth propagation by recomputing the true closest-
  source-surface distance for generated nodes. Each changing label in a
  multi-threshold partition must retain both safe outer and safe backing cells.
- Preserved the existing uniform/single-band outer-only fallback contracts and
  kept the 2,000,000-cell pre/post allocation limit.
- Added an original 36 mm blocky head coupon with a front-left cel light: five
  skin bands use 0.10 / 0.18 / 0.26 / 0.34 / 0.42 mm adaptive partner skins;
  brown hair remains conventional and authored black facial details remain
  pure black.
- Generated five 0.10 mm comparison 3MFs outside Git: conventional Classic;
  Selective Hybrid Classic 3 walls / 100% control; Classic 2 walls / 15% probe;
  Classic 3 walls / 15% candidate; and Arachne 3 walls / 15% probe.
- Reopened every 3MF with the dedicated validator and verified watertightness,
  positive volume, routing, adaptive thickness, exact interfaces, and per-part
  wall/infill overrides. The bundle ZIP/member allowlist and payload hashes
  were also checked.

### Current state

- Source geometry contracts and independent review are green for validation
  coupons. General-model production use is still not approved.
- Desktop comparison bundle (local-only filename):
  `variable_skin_head_validation_bundle.zip`.
- Bundle size: 985,573 bytes. SHA-256:
  `135B359F656B0F80F59A1B89A6C5B4EB0005FC36D82743923986626B4D8239DE`.
- The bundle declares `scope=synthetic-coupon-only`, `experimental=true`,
  `slice_only=true`, `print_allowed=false`, and
  `general_model_production_eligible=false`.
- A 594-vertex / 1,184-face first head correctly stopped on the cell limit; the
  final 210-vertex / 416-face closed coupon passed. Large or finely segmented
  models can still exhaust time or memory before a complete predictive bound.

### Next exact task

Open all five comparison 3MFs in Snapmaker Orca. Verify object/part overrides,
then inspect every layer in Filament and Line Type views before printing. Start
with the Classic 3-wall / 15% candidate. Compare the 100% control, 2-wall / 15%
lower-bound probe, and Arachne path-width probe at identical 0.10 mm settings.
Record time, material, missing thin bands, exposed black, top/bottom behaviour,
and colour continuity in the included observation sheet.

### Changed files

- `source/fixed_app/spectrum_mapper/models.py`
- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/spectrum_mapper/i18n.py`
- `source/fixed_app/spectrum_mapper/project_bundle.py`
- `source/fixed_app/spectrum_mapper/color_depth_exact_partition.py`
- `source/fixed_app/spectrum_mapper/radial_workflow.py`
- `source/fixed_app/spectrum_mapper/radial_stage_b.py` (new)
- `source/fixed_app/spectrum_mapper/radial_hybrid_export.py` (new)
- `source/fixed_app/spectrum_mapper/radial_thickness.py` (new)
- `source/fixed_app/spectrum_mapper/variable_skin_head_coupon.py` (new)
- Corresponding focused tests, plus this `HANDOFF.md` checkpoint.

Other dirty working-tree changes are pre-existing user-owned work and remain
preserved. No commit or push was made.

### Tests run

- Geometry/Stage B focused set: 83 / 83 passed.
- Independent safety/compatibility review: 108 / 108 passed.
- Final synthetic-head bundle suite: 12 / 12 passed.
- Root integrated adaptive-skin, writer, project, UI, i18n, and head run:
  148 / 148 passed in 69.822 seconds.
- Five 3MF dedicated reopen validations, manifest payload parity, ZIP allowlist,
  `py_compile`, and `git diff --check`: passed.
- PyMeshLab emitted only its existing unavailable optional-plugin warnings.

### Do not do

- Do not enable adaptive skin by default or call it production-ready for
  general AI models. A single backing tetrahedron proves geometric presence,
  not a printable minimum cross-section or visible optical result.
- Do not raise the 2,000,000-cell cap to force a model through, weaken exact
  interface/exterior/gap/overlap proofs, or bypass any fail-closed validator.
- Do not infer an optical gradient from Arachne alone. Adaptive geometry creates
  the thickness ladder; Arachne only changes thin-feature path-width planning.
- Do not print before full Orca layer inspection, and do not publish or
  redistribute the owner-only application or coupon bundle.
- Do not change version `0.8beta`, commit, or push without explicit owner
  instruction.

### Local-only files

- The five generated 3MF files, original OBJ/MTL coupon, preview, state mapping,
  observation sheet, bilingual guides, manifest, and comparison ZIP under the
  Desktop folder above.
- The separate Windows owner-only build and its external build/evidence tree
  recorded in the preceding Variable-skin owner-only Windows checkpoint.

## 2026-09-01 SUPERSEDED Variable-skin owner-only Windows build checkpoint

The owner-only ZIP recorded below contains source bytes from before the
deep-partner safety fix and must not be used for the corrected comparison. Use
the later CORRECTED owner-only package checkpoint instead.

### Current objective

Provide the owner with a standalone Windows comparison build for the selective-
hybrid adaptive-skin experiment, without including the separate synthetic-head
coupon bundle and without weakening or bypassing any public binary gate.

### Completed in this session

- Froze and fingerprinted the exact current dirty source tree used by the
  package: 641 source/licence/manifest files, tree SHA-256
  `482BEEB3D795B4B0C121371DD241AC955ACBA996DAD5E2056C824700B2A9B363`.
  The same fingerprint was reproduced after packaging.
- Built a fresh Python 3.13.14 / PyInstaller 6.20.0 one-folder application in
  a new short external root with the isolated native search path used by the
  controlled build script.
- Independently inspected the built and fresh-extracted executable archives.
  `spectrum_mapper.radial_thickness`, `radial_stage_b`,
  `radial_hybrid_export`, and `color_depth_exact_partition` are all frozen in
  the executable.
- Added a local Japanese owner guide marked `OWNER ONLY / INTERNAL /
  NON-DISTRIBUTABLE / SLICE ONLY`. It explains adaptive thickness, the
  conventional / Classic / Arachne comparison, and mandatory all-layer Orca
  inspection.
- Staged 1,456 files: the 1,455-file one-folder application plus the guide.
  No test model, OBJ, GLB, glTF, 3MF, coupon bundle, JPEG, pip
  `direct_url.json`, or reparse point entered the package.
- Validated canonical ZIP member paths, case uniqueness, member lengths,
  readability/CRC, and the exact file list. A separate fresh extraction then
  matched all 1,456 relative paths, byte sizes, and SHA-256 values.

### Current state

- Local owner-only archive:
  `ChromaMatter_0.8beta_VariableSkin_Windows_OWNER_ONLY_INTERNAL_NON-DISTRIBUTABLE_20260901.zip`.
- Archive size: 117,581,168 bytes. SHA-256:
  `881FA3767B9AF8AE8E86FEAEA123C3231D589630D8D65AB5BAD89FBC9AD0250F`.
- The archive contains `ChromaMatter/` and
  `VARIABLE_SKIN_OWNER_TEST_GUIDE_JA.md`. ProductVersion and FileVersion remain
  `0.8beta`.
- This is an unsigned, dirty-working-tree owner comparison build only. It was
  not committed, pushed, uploaded, published, or approved for redistribution.
- The public compliance probe remains closed and exits 1 before inventory
  generation with
  `pytetwild_static_closure_contract.ContractError: Controlled PyTetWild recipe byte count changed`.
  No expected byte count, manifest, or gate was altered to bypass it.

### Next exact task

Extract the complete ZIP, read the owner guide, and compare an ordinary 3MF
with selective-hybrid adaptive skin at 0.10 mm. Start with Delta-L-star 35,
0.10-0.60 mm, gamma 1.0, and five bands. In Snapmaker Orca inspect every layer
before any physical print. Compare Classic 100% as a control, Classic 2 walls /
15% as a lower-bound probe, Classic 3 walls / 15% as the current candidate,
and Arachne 3 walls / 15% only as a thin-feature path-width comparison.

### Changed files

- `HANDOFF.md` gained this post-validation checkpoint.
- No application source, test, spec, licence, or manifest file was changed by
  this packaging task.

### Tests run

- Clean PyInstaller one-folder build under an isolated PATH: passed.
- Built executable frozen-module inspection for all four required variable-
  skin/Stage-B modules: passed.
- Built-tree packaged `--self-test`: exit 0.
- Built-tree isolated Japanese and English `--ui-smoke`: exit 0 for both.
- Stage privacy/runtime audit: 1,456 files; zero model/3MF/JPEG payloads, zero
  `direct_url.json`, zero reparse points, and all required filament resources
  present.
- ZIP canonical path/case/CRC/exact-list validation: 1,456 files passed.
- Fresh-extraction parity: 1,456 / 1,456 paths matched by length and SHA-256.
- Fresh-extracted packaged `--self-test`: exit 0.
- Fresh-extracted isolated Japanese and English `--ui-smoke`: exit 0 for both.
- Fresh-extracted frozen-module and privacy audits: passed.
- Public compliance probe: expected fail-closed exit 1 on the unchanged
  controlled-PyTetWild recipe byte-count contract.
- `git diff --check`, `git diff --stat`, and final `git status` must be recorded
  after this append.

### Do not do

- Do not redistribute, upload, publish, release, or describe this ZIP as public
  binary evidence.
- Do not include or merge the separate head/coupon ZIP, generated 3MF files, or
  any private model into this application archive.
- Do not update only the expected PyTetWild recipe size/hash or weaken the
  public compliance, topology, watertightness, winding, volume, interface,
  archive-reopen, or 3MF fail-closed gates.
- Do not change version `0.8beta`, commit, or push without explicit owner
  authorization.

### Local-only files

- Build, work, stage, isolated profiles, and fresh extraction:
  `C:\ChromaMatterTestBuilds\VariableSkin-20260901`.
- Owner-only ZIP and standalone Japanese guide on the Desktop; the same guide
  is also copied inside the ZIP.
- The separate synthetic-head comparison bundle remains local and was not
  copied into the Windows application archive.

## 2026-09-01 selective-hybrid radial owner-test checkpoint

### Current objective

Add an explicitly selected Stage B hybrid radial experiment without changing
normal 3MF export or the established uniform Stage A path. Only used,
high-Delta-L-star black-mix states may become a physical partner-filament skin
over a black core. Pure black, low-contrast black mixes, non-black states, and
pure physical F2/F3/F4 states must retain the conventional painted carrier.

### Completed in this session

- Added persisted `uniform_stage_a` and `selective_hybrid` conversion modes.
  Missing or legacy project data always migrates to Stage A; Stage B requires
  explicit user selection.
- Added Japanese/English mode selection, explanation, confirmation, progress,
  and completion text without changing the normal export action.
- Added exact conforming-tetra Stage B geometry partitioning with source-face
  provenance, exact exterior coverage, exact-touch interfaces, opposite
  winding validation, positive-volume checks, and zero-gap/zero-overlap proof.
- Added a dedicated hybrid 3MF package writer and independent archive reopen
  validator. Only conventional carrier exterior faces receive ordinary
  Full Spectrum paint metadata; radial partner shells and internal interfaces
  remain unpainted.
- Routed Stage B through the radial workflow only after palette compatibility,
  watertightness, Delta-L-star classification, and used-state checks succeed.
- Built a local owner-only Windows test application and confirmed that both
  `spectrum_mapper.radial_stage_b` and
  `spectrum_mapper.radial_hybrid_export` are present in the frozen EXE.
- Added a bilingual owner-test guide that marks the build `SLICE ONLY` and
  requires complete Snapmaker Orca layer inspection.

### Current state

- Stage B source behavior and a real non-mocked cube partition -> hybrid 3MF
  -> archive-reopen round trip pass.
- The owner-only Windows ZIP exists locally as
  `ChromaMatter_0.8beta_SelectiveHybrid_Windows_OWNER_ONLY_TEST_20260901.zip`.
  It is 117,544,100 bytes with SHA-256
  `060604335911252B01769430918272BCDBF3516DD713E7F78BABC19F9ABC9656`.
- The ZIP contains 1,456 files. Fresh extraction matched every relative path,
  byte size, and SHA-256. It contains no OBJ, GLB, glTF, 3MF, JPEG, or private
  model payload and no `direct_url.json` metadata.
- This artifact is not a public release, is not redistribution eligible, and
  is not physical-print evidence. U1/Orca physical validation remains pending.
- Full regression completed 1,770 tests with 54 failures, 28 errors, and four
  optional skips. The failures cascade from an existing fail-closed PyTetWild
  evidence drift: the tracked build recipe bytes/hash no longer match the
  approved static-closure contract after later VS-layout/PowerShell changes.
  The selective-hybrid and radial coupon suites pass independently and have no
  reference to that contract. No audit value was altered to bypass the gate.

### Next exact task

Open one ordinary 3MF as the baseline, then export Selective Hybrid with
0.10 mm layer height, 0.15 mm partner skin, Delta-L-star threshold 35, and the
actual black-filament F slot. In Snapmaker Orca, compare Classic first and then
Arachne at identical settings. Inspect every layer for intended pure black,
partner-skin continuity, slopes, top/bottom surfaces, color boundaries, gaps,
overlap, missing regions, floating volumes, and unintended black exposure.
Do not physically print until this slice review is accepted. Separately,
rebuild and re-attest the changed PyTetWild recipe before any public binary is
considered.

### Changed files

- `source/fixed_app/spectrum_mapper/models.py`
- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/spectrum_mapper/i18n.py`
- `source/fixed_app/spectrum_mapper/radial_workflow.py`
- `source/fixed_app/spectrum_mapper/radial_stage_b.py` (new)
- `source/fixed_app/spectrum_mapper/radial_hybrid_export.py` (new)
- `source/fixed_app/test_radial_gui.py`
- `source/fixed_app/test_gui_layout.py`
- `source/fixed_app/test_i18n.py`
- `source/fixed_app/test_radial_workflow.py`
- `source/fixed_app/test_radial_stage_b.py` (new)
- `source/fixed_app/test_radial_hybrid_export.py` (new)
- `HANDOFF.md`

Other pre-existing working-tree changes remain user-owned and were preserved.

### Tests run

- Stage B geometry tests: 12/12 passed.
- Stage B writer/export tests: 24/24 passed.
- Focused radial workflow, writer, GUI, and Stage A regressions: 53/53 passed.
- Broader radial, i18n, layout, project/default, hotfix, and shading set:
  194/194 passed; one harmless Tk `after` callback warning was observed.
- Black radial coupon: 15/15 passed.
- Compact radial coupon: 11/11 passed.
- Real non-mocked conforming partition -> hybrid 3MF -> reopen smoke: passed.
- Full source discovery: 1,770 tests in 516.744 seconds; 54 failures,
  28 errors, four optional skips, blocked by the existing PyTetWild evidence
  identity drift described above. The build script stopped before building as
  designed.
- Separate isolated-path owner-test PyInstaller build: passed.
- Frozen-module presence, required filament resources, packaged self-test,
  isolated Japanese UI smoke, and isolated English UI smoke: passed.
- Fresh-extracted packaged self-test and both UI smokes: passed.
- ZIP fresh-extraction path/size/SHA-256 parity for all 1,456 files: passed.
- Target-module `py_compile` and final `git diff --check`: passed.
- Binary compliance inventory was not claimed or bypassed; public eligibility
  remains blocked by the source/evidence gate.

### Do not do

- Do not publish, upload, redistribute, or call the owner-test ZIP a release.
- Do not update only the expected PyTetWild bytes/hash. A changed recipe needs
  a controlled rebuild, attestation, closure evidence, and exact-source review.
- Do not weaken topology, winding, watertightness, volume, interface, paint,
  archive-reopen, or 3MF fail-closed validation.
- Do not change normal 3MF output, uniform Stage A defaults, or old-project
  migration while evaluating Stage B.
- Do not print a Stage B result before complete Orca layer inspection.
- Do not change `0.8beta`, commit, or push without explicit owner instruction.

### Local-only files

- The owner-only ZIP and bilingual test guide.
- The external PyInstaller dist/work tree and its archive-inspection evidence.
- Built-tree and fresh-extracted smoke profiles.
- The fresh extraction and local Stage B validation outputs.

## 2026-09-01 Contrast-gated Radial Stage A source checkpoint

### Current objective

Restore the radial black-core experiment as an explicit Windows source-level
test path without weakening pure-black output globally.  Use a numeric
lightness gate so only a selected black filament paired with a sufficiently
lighter arbitrary partner is eligible for the separate radial export.

### Completed in this session

- Reintroduced a public Output Settings entry for `Radial Stage A`, separate
  from normal Full Spectrum and Flat Four 3MF export and OFF by default for a
  newly opened model.
- Added an explicit opt-in, black F-slot selector, 0.10--0.60 mm partner-skin
  thickness, provisional CIELAB `delta L*` threshold, and Classic/Arachne wall
  generator selector.
- The contrast gate is calculated from the configured F1--F4 display HEX
  colours.  The default threshold is 35.0; every black/partner F combination
  is displayed as eligible or below threshold.  The partner is no longer
  hard-coded to white.
- Preserved pure-black faces and below-threshold black mixes as ineligible.
  The current fail-closed Stage A builder does not approximate or silently
  combine conventional and radial treatment: it accepts exactly one
  watertight part whose complete exterior is one identical eligible
  black-containing mixed state, and rejects pure-black faces, another state,
  partial painting, low contrast, or multiple parts.
- Added general-model 0.10 mm Classic and Arachne process profiles with one
  wall.  Legacy 0.20 mm remains readable for Classic only; 0.20 mm Arachne is
  rejected before writing.
- The generated 3MF, validation JSON, and SLICE ONLY guide record the actual
  and minimum `delta L*`, black and partner L* values, selected process
  profile, wall generator, skin thickness, and layer height.
- Added localized Japanese/English opt-in, confirmation, limitation, status,
  and actionable fail-closed messages.  The UI explicitly states that the HEX
  gate is provisional and real filament transmission/pigment behaviour still
  requires physical calibration.
- Kept normal preview and ordinary 3MF writers unchanged.  Turning Stage A on
  only enables its separate export button.

### Current state

- Source implementation is complete in the dirty, uncommitted working tree on
  `codex/windows-flat4-region-quality`.
- Fixed radial layer height is 0.10 mm, initial layer height is 0.20 mm, the
  provisional default threshold is `delta L* = 35.0`, and both Classic and
  Arachne general profiles are archive-validated.
- This is source evidence only.  No new executable, ZIP, upload, publication,
  commit, or push was produced.  Existing Windows public-binary compliance and
  exact corresponding-source gates remain unresolved and authoritative.
- Stage A is not selective hybrid output.  It cannot yet retain ordinary pure
  black regions while radially converting different high-contrast regions in
  the same model.

### Next exact task

Use one public or synthetic watertight one-part model whose complete exterior
is one eligible black/partner mixed state.  Compare Classic and Arachne at the
same 0.10 mm layer height and test at least 0.15, 0.21, and 0.30 mm partner
skins in Snapmaker Orca layer preview, then on the U1 only after preview is
clean.  Record actual filament pairs and physical results before changing the
provisional threshold.  Design a separately reviewed Stage B selective hybrid
builder only after this evidence exists.  Build an owner-only Windows package
only after an explicit request and exact-current packaging checks.

### Changed files

- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/spectrum_mapper/i18n.py`
- `source/fixed_app/spectrum_mapper/models.py`
- `source/fixed_app/spectrum_mapper/radial_export.py`
- `source/fixed_app/spectrum_mapper/radial_workflow.py`
- `source/fixed_app/test_gui_layout.py`
- `source/fixed_app/test_i18n.py`
- `source/fixed_app/test_radial_export.py`
- `source/fixed_app/test_radial_gui.py`
- `source/fixed_app/test_radial_workflow.py`
- `HANDOFF.md`

### Tests run

- Integrated Radial settings, workflow, dedicated 3MF writer/shell, public GUI
  layout, i18n, new-model defaults, and project round-trip set: 132 tests
  passed with zero failures.
- The Radial workflow set re-opened 0.10 mm Classic/Arachne and legacy 0.20 mm
  archives and verified project metadata; all 8 tests passed after the final
  guide-title update.
- Source `--self-test`: passed, including radial archive smoke.
- Isolated Japanese and English source `--ui-smoke`: passed.
- `python -B -m compileall -q` for the changed source/tests: passed.
- `git diff --check`: passed before this handoff append and must be run once
  more after it.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not treat display-HEX `delta L* = 35` as a physically calibrated optical
  threshold.  Filament opacity, pigment, temperature, line width, wall
  planning, and layer geometry still require actual-print evidence.
- Do not claim Stage A can mix conventional pure-black regions and selective
  radial regions in one model.  The current builder deliberately rejects that
  case rather than approximating it.
- Do not weaken watertightness, positive-volume, exact-touch, exterior
  preservation, archive re-open, or SLICE ONLY checks to make a model export.
- Do not change version `0.8beta`, build/publish a redistributable binary,
  commit, push, upload, or modify a public release without explicit owner
  authorization and all applicable gates.

### Local-only files

- No private model, generated 3MF, executable, archive, or identifying asset
  was added.  Isolated source-smoke application-data directories may remain
  under the system temporary directory and contain no project/model payload.

## 2026-09-01 Large corner-frustum v3 artifact checkpoint

### Current objective

Finish and locally package the owner-requested approximately three-times-linear
white/black comparison coupon with a horizontal top and unmistakable underside
method identifiers.

### Completed in this session

- Finalized the 42 x 42 x 22.8 mm corner frustum with a 9 x 9 mm horizontal
  top, two vertical faces, and two sloped faces.
- Kept the radial white-shell probes at 0.42, 0.30, 0.21, 0.15, and 0.10 mm.
- Stopped the final black core at Z=22.7 mm and closed the complete top with a
  0.10 mm physical-white cap; there is no intentional top black window.
- Exact-partitioned the first 0.20 mm layer into physical black/white tiles for
  centred underside-readable `Z`, `C`, and `A` identifiers.
- Clarified in machine-readable metadata that the black underside identifier is
  the sole exception to the otherwise white base exterior.
- Added direct tamper coverage for horizontal-cap geometry drift and clarified
  the difference between the slicer top-shell request and the 0.10 mm geometric
  cap in both READMEs.
- Generated and independently audited the local v3 bundle and ZIP.

### Current state

- Local bundle folder:
  `artifacts/large_black_radial_frustum_0p10_v3`.
- Local ZIP:
  `artifacts/ChromaMatter_large_black_radial_frustum_0p10_v3.zip`.
- ZIP size: 35,745 bytes. SHA-256:
  `95F1D86BB9EA332CC1E284016D1397003E190DA2CCBE255BB2E3525145FD3FB3`.
- The analytical model volume is 17,099.4 mm3, approximately 34 times the old
  14 mm corner-apex coupon. The README tells the operator to slice one project
  at a time and inspect Orca's time/material estimate.
- All three projects remain experimental and `SLICE ONLY`. No physical print
  or verified Orca G-code was produced. A direct 2.3.6 GUI executable call was
  absorbed by already-running single-instance Orca windows and produced no
  result file, so it is not slicing evidence.
- Work remains uncommitted on `codex/windows-flat4-region-quality`; version
  `0.8beta`, public branches, Releases, and sites were not changed.

### Next exact task

Open each v3 3MF separately in Snapmaker Orca. Inspect every layer in Filament
and Line Width views, confirm only F1 black/F2 white are used, confirm the
horizontal top remains fully white in both radial projects, and check that the
underside identifier reads `Z`, `C`, or `A`. Record estimates and findings in
`observation_sheet.csv`; do not print any project whose preview drops/widens a
shell or exposes a black core on an unintended exterior surface.

### Changed files

- `source/fixed_app/spectrum_mapper/compact_black_radial_coupon.py`
- `source/fixed_app/spectrum_mapper/radial_export.py`
- `source/fixed_app/test_compact_black_radial_coupon.py`
- `HANDOFF.md`

### Tests run

- Radial/compact focused regression after final metadata, README, and tamper
  changes: 20 tests passed.
- Broader radial, CLI, black-coupon, color-depth, workflow, and 3MF-input set:
  121 tests passed before the final test-only metadata assertion; application
  output bytes were unchanged by that assertion.
- Re-opened all three generated 3MF files through the dedicated fail-closed
  validator with explicit method names: passed.
- ZIP CRC, duplicate-name, traversal/path, exact member, manifest byte count,
  and every payload SHA-256 check: passed for 11 members.
- AST parse for the generator, radial exporter, and dedicated test: passed.
- `git diff --check`: passed before this append and must be rerun.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not interpret 0.10 mm as production-safe; it is an aggressive retention
  probe below the nominal line width.
- Do not add an intentional black top window or mirror the underside glyphs
  back into top-view reading order.
- Do not compare radial band names as calibrated optical black percentages.
- Do not weaken geometry, interface, archive, process-profile, physical-tool,
  or 3MF fail-closed gates.
- Do not commit, push, upload, publish, or change version `0.8beta` without
  explicit owner authorization and the applicable exact-current gates.

### Local-only files

- The generated v3 folder and ZIP are ignored local artifacts. They are not
  repository source, release evidence, or a public asset.

## 2026-09-01 Large corner-frustum radial coupon v3 checkpoint

### Current objective

Replace the 14 mm corner-apex coupon with an approximately three-times-linear
specimen that exposes a horizontal top-cap test and remains unmistakable after
printing as conventional, Classic, or Arachne.

### Completed in this session

- Advanced the generator to a 42 x 42 x 22.8 mm corner frustum with a 9 x 9 mm
  horizontal top. X=0 and Y=0 stay vertical; the opposite faces are sloped.
- Kept the five radial thickness probes at 0.42, 0.30, 0.21, 0.15, and 0.10 mm.
- Removed the old intentional pure-black apex. In the final 0.10 mm band, the
  black core terminates 0.10 mm below the top and an exact full-area physical
  white cap covers the complete horizontal top in both Classic and Arachne.
- Partitioned the complete first 0.20 mm layer into physical black/white tiles
  carrying centred `Z`, `C`, and `A` identifiers. Their bitmaps are stored
  X-mirrored so they read normally from the finished underside.
- Added separate fail-closed large-frustum Classic/Arachne process profiles and
  schema markers; the prior compact profile identifiers remain present.
- Updated deterministic geometry, archive, profile, identifier, top-cap,
  manifest, CSV, and bilingual instruction coverage for the v3 generator.

### Current state

- Source generation and dedicated validation pass. No repository artifact,
  ZIP, commit, push, upload, publication, Orca slice, or physical print was
  produced in this subtask.
- Existing ignored compact v2 artifacts were not modified.
- The v3 projects remain experimental and SLICE ONLY. The 0.10 mm Arachne
  setting remains a retention limit probe rather than a production claim.

### Next exact task

Generate the v3 artifact folder and ZIP, independently re-open all three 3MF
projects, verify manifest/CRC/SHA parity, then inspect every layer in Snapmaker
Orca Filament and Line Width views. Confirm the Z/C/A underside marks are
readable, the 9 x 9 mm top is fully white in both radial projects, and no black
core reaches an unintended exterior face before any physical print.

### Changed files

- `source/fixed_app/spectrum_mapper/compact_black_radial_coupon.py`
- `source/fixed_app/spectrum_mapper/radial_export.py`
- `source/fixed_app/test_compact_black_radial_coupon.py`
- `HANDOFF.md`

### Tests run

- Compact v3 plus radial-export focused regression: 19 tests passed with zero
  failures.
- Dedicated compact v3 set alone: 10 tests passed.
- Python compile for the generator and radial exporter: passed.
- Focused `git diff --check`: passed before this handoff append and must be run
  once more after it.
- PyMeshLab emitted only the existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not introduce an intentional black top window; the horizontal v3 top must
  remain a complete 0.10 mm physical-white cap above the black core.
- Do not mirror the underside identifiers back into model-XY reading order;
  they must read correctly only after viewing the finished underside.
- Do not weaken geometry, interface, physical-tool, process-profile, archive,
  or 3MF fail-closed validation, or treat 0.10 mm as production-safe.
- Do not change version `0.8beta`, commit, push, upload, or publish without
  explicit owner authorization and exact-current gates.

### Local-only files

- Temporary generated v3 smoke bundles were created only under the host temp
  directory and are not repository artifacts or release evidence. Existing v2
  artifacts remain ignored and untouched.

## 2026-09-01 Compact white/black radial pyramid checkpoint

### Current objective

Replace the slow multi-cell black-band experiment with one small white/black
specimen that compares conventional Z-cadence colour against physical radial
shells, including shell thicknesses below the previous 0.15 mm limit.

### Completed in this session

- Added a purpose-built 14 x 14 x 7.6 mm corner-apex pyramid. The X=0 and Y=0
  faces are vertical; the other two faces are sloped.
- Divided the single visual specimen into seven exact-contact height bands:
  white control, five mixed references, and a 0.4 mm pure-black apex control.
- Aligned every conventional mixed band to an integer cadence length at
  0.10 mm layers.
- Added equal-normal white shell probes at 0.42, 0.30, 0.21, 0.15, and
  0.10 mm around physical black cores.
- Added conventional, Radial Classic, and Radial Arachne 3MF generators.
  Classic uses one wall with thin-wall detection; Arachne uses one wall,
  20% minimum feature, 25% normal-layer minimum bead, and 85% initial-layer
  minimum bead.
- Added compact-only process profiles without relaxing the production Radial
  MVP profile or its fail-closed validation.
- Added exact geometry, volume, winding, shared-interface, part identity,
  F1/F2-only, project-setting, archive-member, relationship-byte, and
  tamper-rejection validation.
- Marked radial optical black percentage as uncalibrated. The 5-25% labels are
  conventional positional references, not claims of equivalent visual tone.
- Generated Japanese/English instructions, a band map, an observation sheet,
  validation reports, and a SHA-256 manifest.

### Current state

- Preferred local test bundle:
  `artifacts/ChromaMatter_compact_black_radial_pyramid_0p10_v2.zip`.
- ZIP size: 30,202 bytes. SHA-256:
  `48DF17BCDA0139BBC66E4334439DE83B6E538ECBD39D500FA8BA022F1025CF05`.
- The bundle contains three 3MF projects plus Japanese/English instructions,
  CSV records, validation JSON, and `manifest.json`.
- `artifacts/compact_black_radial_pyramid_0p10_v1/` is a superseded local
  pre-audit generation and must not be handed out as current evidence.
- No Snapmaker Orca GUI slicing or physical U1 print has been performed on
  this machine. The projects remain experimental and SLICE ONLY.
- No commit, push, upload, or publication occurred. Version remains
  `0.8beta`.

### Next exact task

Open the three v2 projects in Snapmaker Orca without repair or setting
substitution. Slice each and inspect every layer in Filament and Line Width.
Confirm that only F1 black and F2 white occur on the model, record whether the
0.21/0.15/0.10 mm shells disappear or widen, and do not print any preview in
which black reaches an intermediate external face. If all previews are safe,
print the three projects under the same material and machine conditions and
record results in `observation_sheet.csv`.

### Changed files

- `source/fixed_app/spectrum_mapper/compact_black_radial_coupon.py`
- `source/fixed_app/spectrum_mapper/radial_export.py`
- `source/fixed_app/test_compact_black_radial_coupon.py`
- `source/fixed_app/test_radial_export.py`
- `HANDOFF.md`

### Tests run

- Compact plus existing black-coupon focused set: 32 tests passed.
- Radial, CLI radial smoke, compact/legacy coupon, and ColorDepth regression:
  118 tests passed with zero failures.
- All three generated v2 3MF files reopened through their dedicated
  fail-closed validators.
- Bundle ZIP: 11 unique entries, CRC clean; all 10 manifest payload hashes and
  byte counts matched.
- `py_compile` for the compact generator and radial exporter: passed.
- `git diff --check`: must be run once more after this handoff append.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not treat the Arachne 0.10 mm setting as a production recommendation or
  as proof that a true 0.10 mm extrusion bead is achievable.
- Do not describe radial reference bands as calibrated 5-25% optical black.
- Do not disable the prime tower, purge into the model, merge/repair the
  volumes, or print before all-layer Filament and Line Width inspection.
- Do not weaken topology, physical-tool, relationship, process-profile, or
  3MF fail-closed validation.
- Do not change version `0.8beta`, commit, push, upload, or publish without an
  explicit owner instruction and the applicable exact-current gates.

### Local-only files

- The v2 test bundle and generated 3MF/CSV/validation artifacts remain under
  `artifacts/` and outside Git. The superseded v1 folder is also local-only.
  No private model, personal identifier, binary application, or build output
  was added to the repository.

## 2026-09-01 black-band radial and Arachne coupon checkpoint

### Current objective

Determine whether a physical radial colour architecture can keep pure black
available while preventing weak-black Ratio layers from appearing as visible
horizontal bands, and measure how shell thickness and Arachne affect the
available colour range on vertical, sloped, top, and downward-facing surfaces.

### Completed in this session

- Added coupon-only 0.10 mm Classic and Arachne radial process profiles. Both
  use two walls, Thin wall OFF, 0.42 / 0.45 mm outer / inner widths, five
  top/bottom layers, 100% infill, and physical F1-F4 materials only.
- Kept the existing 0.20 mm radial MVP profile unchanged.
- Added a deterministic three-lane purpose-built coupon: White, Yellow, and
  Skin against F1 pure black, with Partner 100%, Black 5%, 10%, 14.3%, 20%,
  25%, and Black 100% controls.
- Added partner-shell thickness probes of 1.05, 0.84, 0.63, 0.42, and 0.21 mm.
  Each cell includes vertical front/rear walls, 30 and 60 degree slopes, a
  horizontal top, a downward horizontal face, and a downward 45 degree face.
- Generated three otherwise comparable 3MF projects: conventional Z-ratio,
  physical radial Classic, and physical radial Arachne.
- Made the coupon validators fail closed on archive-member drift, duplicate
  members, relationships, project and model settings, hidden per-object/plate
  overrides, transforms, deterministic geometry and paint states, canonical
  coupon metadata, topology, exact radial interfaces, Production extension
  declarations, and malformed/duplicate Production UUIDs.
- Added Japanese/English instructions, layout image, mapping and observation
  CSV files, research notes, validation records, and a SHA-256 manifest.

### Current state

- Latest local bundle folder:
  `artifacts/black_radial_coupon_0p10_arachne_v6`.
- Latest local ZIP:
  `artifacts/ChromaMatter_black_radial_coupon_0p10_arachne_v6.zip`.
- ZIP size is 151,362 bytes; CRC passed and all 13 manifest-listed files
  matched their recorded byte counts and SHA-256 values.
- ZIP SHA-256:
  `0DBE54FF8552DC13247D47DFCBC055C12C5EB3DF1B17BDD917E2B5804045EFB2`.
- Static 3MF and geometry validation passed. These are still experimental,
  slice-only coupons and are not physically calibrated or print-approved.
- Snapmaker Orca 2.3.6 command-line slicing returned launcher exit code 0 but
  produced no G-code and wrote a new fatal Sentry event. This does not prove a
  coupon defect or compatibility. GUI open, slice, and all-layer Filament /
  Toolpath inspection remain mandatory before printing.
- No commit, push, upload, or publication occurred.

### Next exact task

Open each of the three v6 projects in the installed Snapmaker Orca GUI. Confirm
F1-F4 only, then slice without automatic repair or geometry merging. Inspect
all layers for missing 0.21 / 0.42 mm skins, black reaching an exterior face,
or unexpected T4+ tools. Print the conventional and both radial coupons at the
same 0.10 mm settings, photograph them under the same light, and complete
`observation_sheet.csv` before choosing a production shell-thickness policy.

### Changed files

- `source/fixed_app/spectrum_mapper/radial_export.py`
- `source/fixed_app/spectrum_mapper/black_radial_coupon.py` (new)
- `source/fixed_app/test_radial_export.py`
- `source/fixed_app/test_black_radial_coupon.py` (new)
- `HANDOFF.md`

### Tests run

- Focused coupon and radial-export suite: 24 tests passed.
- Radial, coupon, CLI smoke, and colour-depth regression suite: 109 tests
  passed initially; the final schema-hardening run passed 110 tests.
- Generated-v6 ZIP CRC: passed.
- Generated-v6 manifest: 13 / 13 files matched size and SHA-256.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not call Arachne an optical mixer. It only changes path-width planning;
  the partner shell geometry remains the optical control variable.
- Do not infer that a preserved 0.21 mm feature is printed at 0.21 mm. With a
  0.4 mm nozzle and 85% minimum bead, Arachne may widen it toward 0.34 mm.
- Do not publish these coupons as calibrated settings, bypass the GUI
  all-layer inspection, weaken topology/3MF fail-closed validation, alter
  version `0.8beta`, commit, or push without explicit authorization.

### Local-only files

- The v2-v6 coupon folders, ZIP, Orca CLI probe output, and generated Sentry
  event are ignored/local artifacts. No private model, generated 3MF, G-code,
  binary, build tree, or distribution archive was added to Git.

## 2026-08-31 Private Source Vault Strong-Cel performance snapshot

### Current objective

Preserve the exact current Windows Strong-Cel performance working tree in the
authenticated private Source Vault so another trusted PC can resume without
GitHub and without transferring private models or build products.

### Completed in this session

- Created an authoritative working-tree source ZIP from exactly the 486 paths
  returned by `git ls-files --cached --others --exclude-standard`.
- Created and verified a complete-history Git bundle with `git bundle create
  --all` and `git bundle verify`. The bundle contains committed history only;
  the ZIP remains authoritative for the uncommitted source bytes.
- Audited the ZIP root, canonical paths, case-fold uniqueness, CRC/readability,
  exact file list, and fresh extraction. All 486 extracted files matched the
  repository by relative path, length, and SHA-256.
- Passed the repository public-tree privacy audit on both the staged and fresh-
  extracted source trees. No executable, native binary, nested archive,
  generated 3MF/model output, private model, build/dist/venv/cache, reparse
  point, password, key, or private customer payload entered the snapshot.
- Uploaded and finalized both artifacts under private version
  `Windows Strong Cel Performance WT 20260831`, platform `Windows`, based on
  `Generic Colored-Light Cel WT 20260831`.
- Confirmed the Source Vault lists the new version as latest and reports the
  same SHA-256 values as the local audited artifacts.

### Current state

- Branch: `codex/windows-flat4-region-quality`.
- Committed base recorded by the Vault:
  `a94f6cd9add8d76f7debf9a388f896a0c7ee8407`.
- Vault source snapshot:
  `ChromaMatter-source-Windows-Strong-Cel-Performance-WT-20260831-20260831.zip`.
  Size: 5,118,785 bytes. SHA-256:
  `6ABB9ED7E59C0F4E11DD91F0E406021587459954E7744A9BA3580D566F80B8B6`.
- Vault history artifact:
  `ChromaMatter-history-Windows-Strong-Cel-Performance-WT-20260831-20260831.bundle`.
  Size: 5,627,954 bytes. SHA-256:
  `8A8EE75D38991770CA759D3D34B714A218890064D0BF377187DC0CB86E672FBD`.
- The private version is an internal transfer checkpoint, not a commit,
  release, public binary, or public-distribution approval.

### Next exact task

On the next trusted PC, download both artifacts from the private Source Vault,
verify the displayed SHA-256 values, restore the Git bundle into a separate
checkout, and overlay the source ZIP. Treat the ZIP as authoritative for the
dirty working-tree bytes before running the recorded focused regressions.

### Changed files

- `HANDOFF.md` gained this post-upload record only.
- No application source changed while creating or uploading the snapshot.
- Because this record can only be written after successful finalization, it is
  intentionally the sole local post-upload delta and is not inside the already
  immutable Source Vault ZIP.

### Tests run

- Source listing and forbidden-payload audit: 486 files, passed.
- Canonical ZIP contract and fresh-extraction path/size/SHA-256 parity:
  486 / 486 files, passed.
- Staged and fresh-extracted public-tree privacy audit: passed.
- Git bundle complete-history verification: passed.
- Source Vault server-side upload verification and displayed local-hash parity:
  ZIP and bundle both passed.
- `git diff --check`: must be rerun after this handoff append.

### Do not do

- Do not treat the Git bundle alone as the current source; it cannot contain
  the uncommitted Strong-Cel, palette, preview, GLB/project, paint, and test
  bytes carried by the ZIP.
- Do not publish either private artifact, relabel it as a release, or weaken
  topology, pending-palette, 3MF, controlled-build, corresponding-source, or
  public binary compliance gates.
- Do not change version `0.8beta`, commit, or push without explicit owner
  instruction.

### Local-only files

- The original transfer ZIP, Git bundle, staging tree, fresh extraction, and
  owner-only Windows executable package remain outside Git. They may be
  removed later only after the private Vault artifacts are independently
  downloaded and hash-verified on the receiving PC.

## 2026-08-31 Strong-Cel real-model performance checkpoint

### Current objective

Reduce the colour-rich Strong-Cel/Selective Highlight processing time while
preserving the exact face colours, palette assignments, whole-score grouping,
and fail-closed topology behavior.

### Completed in this session

- Replaced the base-mid allocation's distinct-score-by-full-face scan with one
  stable descending sort and whole-score slices. Equal-score faces retain their
  original face order for area summation, and the first oversized group still
  stops selection exactly as before.
- Added old-versus-new exact-reference coverage over 80 deterministic random
  cases, an oversized-tie stop case, and a 100,000-distinct-score case.
- Reused the continuous Strong-Cel light scores and crease-aware face normals
  already produced by the ordinary tone pass when Selective Highlight runs.
  The expensive winding/orientation and normal pass now runs once instead of
  twice.
- Deferred the face-to-vertex preview approximation until the optional
  face-authoritative selective result succeeds or fails closed, eliminating a
  complete approximation that was previously built and discarded on success.
- Added exact parity tests between captured and standalone light geometry,
  between cached and fallback selective output, and a pipeline regression that
  proves the standalone second normal pass is not called.

### Current state

- On one local-only multipart GLB reduced to the same 444,571-face prepared
  mesh, plain recolouring fell from 60.133 seconds to 26.617 seconds, a 55.7
  percent reduction. The intermediate stable-sort-only result was 52.826
  seconds.
- Normal orientation fell from two calls totalling 49.669 seconds to one call
  taking 23.662 seconds. That one remaining pass is geometry-authoritative and
  was deliberately retained.
- Palette-index, target-face-RGB, tone-face-RGB, and band-ID SHA-256 hashes all
  match the pre-optimization baseline exactly. Palette counts, band counts,
  and `selective_applied=true` also match.
- Model preparation varied around 47 seconds in these runs and was measured
  separately; this checkpoint optimizes Strong-Cel recolouring, not mesh
  cleanup/decimation.
- The version remains `0.8beta`. The worktree remains dirty and uncommitted;
  no executable, ZIP, upload, publication, commit, or push was produced.

### Next exact task

Run the source build on the owner's original high-face-count setting and note
the total prepare-versus-recolour split. If preparation remains the dominant
delay, profile cleanup/decimation separately before changing its algorithms.
Build a new owner-only Windows comparison package only after an explicit
request and exact-current packaging checks.

### Changed files

- `source/fixed_app/spectrum_mapper/engine.py`
- `source/fixed_app/spectrum_mapper/illustration_filter.py`
- `source/fixed_app/test_strong_cel_print.py`
- `source/fixed_app/test_illustration_filter.py`
- `HANDOFF.md`

### Tests run

- Integrated Strong Cel, illustration, cel-light palette, shading bridge,
  manual palette, project, GLB, Flat Four, recommendation, and 3MF-related
  focused set: 278 tests passed with zero failures.
- Real-model before/after benchmark: four authoritative output hashes and all
  palette/band counts matched exactly.
- `python -B -m compileall -q` for the touched source/tests: passed.
- `git diff --check`: passed before this handoff append and must be run once
  more after it.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not skip the one remaining winding/orientation pass or trust imported
  winding blindly for more speed; it remains authoritative geometry evidence.
- Do not split equal-score groups, change area budgets, remove reciprocal
  topology or component gates, or weaken any 3MF fail-closed validation.
- Do not treat the measured mesh-preparation time as improved by this change.
- Do not change version `0.8beta`, commit, push, package, upload, or publish
  without explicit owner authorization and the applicable current-tree gates.

### Local-only files

- The benchmark input, prepared mesh, timing/profile data, and hash helper
  remain outside Git. No private model name, private path, generated 3MF,
  binary, archive, or identifying asset was added to the repository.

## 2026-08-31 Strong-Cel performance owner-test package checkpoint

### Current objective

Provide the owner with a directly runnable Windows comparison build containing
the exact Strong-Cel performance changes from the preceding checkpoint.

### Completed in this session

- Built a fresh Windows x86_64 PyInstaller one-folder application from the
  exact current dirty working tree using Python 3.13.14 and PyInstaller 6.20.0.
- Added a Japanese owner-test guide covering same-model/same-face-count timing,
  colour/band comparison, manual editing, and optional 3MF inspection.
- Packaged the application under the short `ChromaMatter/` archive root.
- Verified the built and fresh-extracted executables with packaged self-test
  and isolated Japanese and English UI smoke runs.
- Compared every built file with the fresh extraction by relative path, size,
  and SHA-256; all 1,456 files matched exactly.
- Confirmed zero OBJ, GLB, glTF, 3MF, `direct_url.json`, or reparse-point
  payloads before archiving.

### Current state

- Local owner-only archive:
  `ChromaMatter-0.8beta-StrongCel-Performance-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260831-win64.zip`.
- Size: 117,466,864 bytes. SHA-256:
  `121BB00ED2BAAF6425B9262497A7F9C168F3A84503949E7EBE5DCDD047D35DCB`.
- This is an unsigned, uncommitted owner-comparison build. It was not pushed,
  uploaded, published, or approved for redistribution.
- The public binary compliance inventory remains fail-closed because the
  existing controlled PyTetWild recipe byte count does not match its pinned
  contract. The archive is therefore intentionally labelled internal and
  non-distributable; no public-release claim is made.

### Next exact task

Extract the ZIP, open `ChromaMatter/ChromaMatter.exe`, and run the same heavy
GLB at the same final-face and Strong-Cel settings used previously. Record mesh
preparation time separately from recolouring time and visually compare colour
regions, contours, highlight area, and F1-F4 assignments. Do not redistribute
this build.

### Changed files

- `HANDOFF.md`
- No application source changed while packaging; the executable contains the
  exact source from the preceding performance checkpoint.

### Tests run

- Pre-package integrated functional regression: 278 tests passed.
- Touched-source compile and `git diff --check`: passed.
- Fresh PyInstaller one-folder build: passed.
- Built-tree packaged self-test: passed.
- Built-tree Japanese and English UI smoke: passed.
- Fresh extraction parity: 1,456 / 1,456 files matched by relative path,
  length, and SHA-256.
- Fresh-extracted packaged self-test: passed.
- Fresh-extracted Japanese and English UI smoke: passed.
- Public compliance inventory: intentionally not passed; stopped on the
  controlled PyTetWild recipe byte-count contract mismatch described above.
- `git diff --check` must be rerun after this handoff append.

### Do not do

- Do not publish or redistribute this archive, describe it as a release, or
  bypass the PyTetWild/compliance contract to make the public gate green.
- Do not reuse the previous Intermediate Colors owner ZIP as performance-build
  evidence; it predates these source bytes.
- Do not change version `0.8beta`, commit, push, upload, or publish without
  explicit owner authorization and the applicable exact-current gates.

### Local-only files

- The owner-test ZIP, build/work tree, fresh extraction, isolated profiles,
  Japanese guide, and failed public inventory scratch directory remain outside
  Git. No private model or generated 3MF was added to the repository.

## 2026-08-31 Expanded intermediate-colour proposal checkpoint

### Current objective

Make the user-selectable Expanded automatic-proposal range match its name by
including curated intermediate colours, while keeping Classic behaviour and
manual palette/provenance safety unchanged.

### Completed in this session

- Changed the Japanese selector label from
  `拡張（青灰・紫灰も許可）` to `拡張（中間色も許可）`; English is now
  `Expanded (include intermediate colors)`.
- Expanded mode now promotes the existing curated beige, dusty rose, and
  burgundy anchors into automatic F1-F4 candidates, in addition to blue grey
  and violet grey.
- Classic remains the original 15 automatic primary/neutral/skin anchors and
  excludes all five Expanded-only anchors.
- Kept `DEFAULT_CURATED_CATALOG` intermediate entries manual-only. Only the
  three explicitly curated built-in IDs are promoted in Expanded mode;
  arbitrary external `CATEGORY_INTERMEDIATE` entries remain hard-excluded.
- Added direct regressions proving each of the three promoted intermediate
  anchors can be selected for a dominant matching model colour, is absent from
  Classic results, and is included in database-anchor mapping only for
  Expanded mode.
- Built and fully checked a fresh owner-comparison Windows package from the
  exact current working tree.

### Current state

- Local owner-only archive:
  `ChromaMatter-0.8beta-CompactUI-IntermediateColors-WORKINGTREE-INTERNAL-NON-DISTRIBUTABLE-20260831-win64.zip`.
- Size: 118,599,569 bytes. SHA-256:
  `1FADB3E38E365C585D44C3237F77E009487643488CF701C309FB62F82C83DD3E`.
- Archive root is `ChromaMatter/`; all 1,500 files passed fresh-extraction
  byte/hash parity. No OBJ, GLB, glTF, 3MF, `direct_url.json`, or reparse point
  is present.
- The immediately preceding CompactShading/PaletteFlow ZIP predates this
  proposal-range change and is stale evidence.
- No commit, push, upload, publication, or release authorization occurred.

### Next exact task

In the new owner-only build, run automatic proposal on models dominated by
beige, muted rose, or burgundy areas with Expanded selected, then switch to
Classic and repeat. Confirm Expanded can choose the matching intermediate
spool while Classic remains primary/neutral/skin-only, and confirm switching
the selector alone does not alter the current F1-F4 palette.

### Changed files

- `source/fixed_app/spectrum_mapper/filament_recommender.py`
- `source/fixed_app/spectrum_mapper/i18n.py`
- `source/fixed_app/test_filament_recommender.py`
- `source/fixed_app/test_filament_candidate_gui.py`
- `HANDOFF.md`

### Tests run

- Integrated recommendation, selector, defaults, Strong Cel, compact shading,
  palette flow, Flat Four, part, project, i18n, and hotfix set: 295 tests
  passed with zero failures.
- `python -B -m compileall -q source/fixed_app`: passed.
- Source `--self-test` and Japanese/English `--ui-smoke`: passed.
- Fresh PyInstaller 6.20.0 / Python 3.13.14 one-folder build: passed.
- Built-tree packaged `--self-test` and isolated Japanese/English
  `--ui-smoke`: passed.
- ZIP fresh-extraction parity: 1,500 source / 1,500 extracted files, zero
  missing, extra, size, or SHA-256 mismatches.
- Fresh-extracted packaged `--self-test` and isolated Japanese/English
  `--ui-smoke`: passed.
- `git diff --check`: must be rerun after this appended checkpoint.
- PyMeshLab emitted only its existing unavailable optional Qt-plugin warnings.

### Do not do

- Do not make arbitrary external intermediate-category products automatically
  eligible; only the explicit curated Expanded anchors are authorized here.
- Do not alter F1-F4 merely by switching the proposal-range selector or weaken
  manual palette/provenance, Full Spectrum pending/export, topology, or 3MF
  fail-closed guards.
- Do not redistribute, upload, publish, or present the owner-only ZIP as a
  release artifact.
- Do not change version `0.8beta`, commit, or push without explicit owner
  instruction.

### Local-only files

- The owner-only ZIP, PyInstaller build/work tree, isolated smoke profiles,
  fresh extraction, and Japanese test guide remain outside Git.

## 2026-09-02 Adaptive radial/Arachne cross-model safety checkpoint

### Current objective

Preserve the current uncommitted radial and selective-hybrid research as a
private cross-PC source checkpoint.  Generalize adaptive partner-skin depth
handling beyond one owner model while continuing to fail closed whenever the
requested depth cannot be proved within the fixed safety tolerance.

### Completed in this session

- Added a bounded adaptive overdepth refinement path for selective-hybrid
  radial partitions.  It may run seven ordinary interface refinements and one
  stagnation fallback, with a hard total limit of eight attempts.
- Added fail-closed stagnation detection and contraction evidence.  The
  fallback may continue only after proving that its interface diameter
  contracts; partner-side routing and a ninth attempt remain prohibited.
- Kept the fixed sampled-distance overdepth tolerance at 0.05 mm.  A real
  cross-model probe reduced the measured error from 0.23045 mm to 0.19061 mm
  and proved contraction, but still stopped safely because it did not meet the
  tolerance.  No 3MF was produced from that failed probe.
- Added generic cross-model radial tooling plus a privacy-minimized attempt
  ledger.  The ledger records bounded categorical diagnostics and numeric
  safety evidence without model names, source paths, part names, cell IDs,
  free text, or geometry-lineage hashes.
- Preserved the successfully validated owner-only head export as local-only
  evidence.  It used Selective Hybrid, adaptive radial partner skin, Arachne,
  the selected black filament, and 15 percent sparse infill.  Weak Black /
  physical black correction was not applied; pure-black regions kept the
  configured black filament unchanged.

### Current state

- Authoritative working tree: branch `codex/windows-flat4-region-quality` at
  committed base `a94f6cd9add8d76f7debf9a388f896a0c7ee8407`, plus the current
  uncommitted source changes.
- The source snapshot set is exactly the regular files returned by
  `git ls-files --cached --others --exclude-standard`: 503 files totaling
  16,491,932 bytes before this handoff append.
- Compared with the previous private Variable Skin Radial Safety snapshot,
  the current tree has three added paths and sixteen changed paths.  Ignored
  bytecode caches from the earlier extracted copy are correctly absent.
- Generic adaptive export remains fail closed.  A contraction proof allows a
  bounded final attempt; it does not waive the 0.05 mm depth contract and does
  not authorize unsafe 3MF output.
- This checkpoint is private source transfer only.  It is not a commit, public
  release, redistributable binary, Orca all-layer approval, or physical-print
  validation.

### Next exact task

Restore the source ZIP over the matching Git-bundle checkout on the next
trusted PC, rerun the focused adaptive/radial suite, and continue searching
for a genuinely independent model that passes the fixed 0.05 mm overdepth
contract without pathological near-global radial eligibility.  Inspect every
successful 3MF in Orca before any print and keep physical calibration separate
from geometry safety.

### Changed files since the previous private source checkpoint

- `.gitignore`
- `HANDOFF.md`
- `source/fixed_app/spectrum_mapper/color_depth_exact_partition.py`
- `source/fixed_app/spectrum_mapper/gui.py`
- `source/fixed_app/spectrum_mapper/i18n.py`
- `source/fixed_app/spectrum_mapper/radial_export.py`
- `source/fixed_app/spectrum_mapper/radial_hybrid_export.py`
- `source/fixed_app/spectrum_mapper/radial_shell.py`
- `source/fixed_app/spectrum_mapper/radial_workflow.py`
- `source/fixed_app/test_color_depth_exact_partition.py`
- `source/fixed_app/test_i18n.py`
- `source/fixed_app/test_radial_export.py`
- `source/fixed_app/test_radial_gui.py`
- `source/fixed_app/test_radial_hybrid_export.py`
- `source/fixed_app/test_radial_shell.py`
- `source/fixed_app/test_radial_workflow.py`
- `source/fixed_app/test_radial_attempt_ledger.py` (new)
- `tooling/radial_attempt_ledger.py` (new)
- `tooling/run_generic_radial_model.py` (new)

### Tests run

- Adaptive partition, fallback, radial, workflow, and linked focused set:
  148 tests passed across 10 modules.
- Privacy-minimized attempt-ledger suite: 19 tests passed.
- Target-module `py_compile`: passed.
- `git diff --check`: passed before this handoff append and must be rerun.
- Independent implementation review: accepted.
- Cross-model execution proved bounded fallback and contraction, then stopped
  safely at 0.19061 mm because the 0.05 mm contract was not met.

### Do not do

- Do not interpret contraction alone as export approval or relax the 0.05 mm
  sampled-distance tolerance.
- Do not permit partner routing, an unbounded retry loop, or more than eight
  total refinement attempts.
- Do not treat the owner-only successful output as evidence that every model
  is safe, and do not claim that Weak Black was applied to it.
- Do not include private models, model-derived 3MF/project/validation output,
  binaries, archives, caches, host paths, credentials, or identifying data in
  the repository or private source ZIP.
- Do not change version `0.8beta`, commit, push, or publish without explicit
  owner authorization and the applicable exact-current gates.

### Local-only files

- The owner-only head 3MF, repaired project, source model, validation records,
  Orca inspection material, cross-model run outputs, and privacy-minimized
  diagnostic ledger remain outside Git and outside the source snapshot.

## 2026-09-02 Large Full Spectrum frustum regeneration checkpoint

### Current objective

Regenerate only the large conventional Full Spectrum Z-cadence comparison
project.  Do not deliver the Radial Classic or Radial Arachne variants.

### Completed in this session

- Generated one local-only 42 x 42 x 22.8 mm large corner-frustum 3MF with a
  9 x 9 mm horizontal top:
  `ChromaMatter_black_gradient_frustum_v3_conventional_Z_0p10.3mf`.
- Used the conventional Full Spectrum writer with the 32-state global palette.
  The model uses only F1 black and F2 white plus the canonical F1+F2 Ratio
  states, with a readable `Z` identifier on the finished underside.
- Preserved the coupon's intentional output-only Weak Black preset.  The
  gradient bands use the effective 5/10/14.3/20/25-percent black references;
  the pure-black underside identifier remains pure black.
- Did not generate or retain the Classic/Arachne comparison outputs in the
  delivered folder.

### Current state

- Output size: 11,374 bytes.
- SHA-256:
  `1056142EDF523062B59470BEF588DD70A6907D08D87C5FA7628994F65FA710BC`.
- Dedicated fail-closed re-open validation passed: 23 parts, 23 validated
  positive solid parts, CRC clean, Ratio-only, physical slots F1/F2, 0.10 mm
  layer height, and the expected state IDs 1/2/5/11/17/23/24.
- The project remains `experimental`, `SLICE ONLY`, and `print_allowed=False`.
  It is not an Orca all-layer or physical-print approval.

### Next exact task

Open the single project in Snapmaker Orca without repair, merge, or rotation.
Inspect every layer in Filament and Line Width views, confirm that only F1/F2
occur on the model, keep the prime tower, and do not print if an unintended
black exterior or missing narrow feature appears.

### Changed files

- `HANDOFF.md` only.  No application or generator source was changed.

### Tests run

- Exact generated-file validator: passed.
- Three conventional geometry/identifier/inset focused tests: passed.
- Full compact comparison module: five tests passed and six errored because
  the unrequested Radial Classic generator currently reports `Radial part
  identity drifted at part 1`.  The exact conventional output and its
  dedicated validator were unaffected; do not claim the whole comparison
  bundle is healthy.
- `git diff --check`: must be rerun after this handoff append.

### Do not do

- Do not describe the file as a physical radial-shell project; it is the
  conventional Z-cadence Full Spectrum comparison.
- Do not claim that Weak Black is absent, or that the 5-25-percent labels are
  physically calibrated optical percentages.
- Do not print before the required Orca all-layer inspection.
- Do not commit, upload, publish, or add this generated 3MF to a source ZIP.

### Local-only files

- The generated 3MF remains outside Git and outside the private source vault.

## 2026-09-02 Large Radial Arachne frustum follow-up checkpoint

### Current objective

Add the matching large physical Radial Arachne comparison project beside the
already generated conventional Full Spectrum file, without overwriting it or
generating the unrequested Classic variant.

### Completed in this session

- Fixed the large-frustum validator's stale per-part metadata expectation.
  The shared radial writer intentionally records `closed_physical_volume`;
  the compact validator alone still expected the legacy `solid_infill` key.
  This was a validator false failure in both Classic and Arachne output, not
  malformed radial geometry.
- Added regression coverage that requires `closed_physical_volume=True` for
  every radial part and rejects the legacy serialized `solid_infill` key.
- Generated one local-only 42 x 42 x 22.8 mm Arachne 3MF with a 9 x 9 mm
  horizontal top and readable `A` underside identifier:
  `ChromaMatter_black_gradient_frustum_v3_radial_arachne_A_0p10.3mf`.
- The Arachne file contains 23 validated positive closed parts, five radial
  interfaces, pure physical F1 black cores and F2 white shells, and no Ratio
  definitions or Weak Black transformation.

### Current state

- Output size: 9,597 bytes.
- SHA-256:
  `BE5DBA9647D951B8A3905A8F68A533EA7D181D18181D735251DB06DECD89CAA9`.
- Dedicated independent re-open validation passed: CRC clean, 23/23 closed
  solid parts, physical slots F1/F2 only, zero mixed-definition rows, Arachne
  wall generator, one wall loop, thin-wall detection disabled, 0.10 mm layer
  height, and a 0.10 mm full-white top cap.
- The embedded Arachne experiment remains `SLICE ONLY`,
  `print_allowed=False`, and requires explicit Orca all-layer approval.  Its
  aggressive process settings are 20% minimum feature, 25% minimum bead, and
  85% initial-layer minimum bead.  Sparse infill is explicitly 15%, matching
  the general radial policy and the owner's direction that black need not be
  100% infill; closed-volume validation remains a separate contract.

### Changed files

- `HANDOFF.md`
- `source/fixed_app/spectrum_mapper/compact_black_radial_coupon.py`
- `source/fixed_app/spectrum_mapper/radial_export.py`
- `source/fixed_app/test_compact_black_radial_coupon.py`

### Tests run

- `test_compact_black_radial_coupon` plus `test_radial_export`: 22 tests
  passed.
- Exact generated-file validation in a fresh process: passed.
- Target `py_compile` and `git diff --check`: passed.

### Known follow-up

- Generic and compact radial validation currently verify part order, geometry,
  material slots, project settings, and JSON identities, but a mutation of only
  a child-model XML object's `name` attribute is not yet rejected.  Add an
  explicit child-name/model-settings/JSON-name equality gate and tamper test
  before treating metadata identity validation as complete.

### Next exact task

Open the Arachne project in Snapmaker Orca without repair, merge, or rotation.
Inspect every layer in Filament and Line Width views, confirm the intended F1
core/F2 shell alternation and narrow-feature retention, keep the prime tower,
and do not print if a shell disappears or an unexpected material appears.

### Do not do

- Do not treat `closed_physical_volume` as a request for 100% black infill;
  closure and slicer sparse-infill density are separate contracts.
- Do not claim that this project uses Full Spectrum Ratio mixing or Weak Black.
- Do not describe the file as print approved before Orca all-layer inspection.
- Do not commit, upload, publish, or add the generated 3MF to a source ZIP.

### Local-only files

- Both generated comparison 3MFs remain outside Git and outside the private
  source vault in the same owner-local Desktop folder.

## 2026-09-02 Latest owner-test package and safe-storage cleanup checkpoint

### Current objective

Create a fresh Windows ZIP from the current working tree, preserve everything
needed for continued Flat Four / radial / Arachne development, and remove only
audited obsolete build products, exact duplicates, and superseded caches that
were consuming local storage.

### Completed in this session

- Fixed an import-order-dependent test and export defect caused by the runtime
  hotfix replacing the public 3MF writer.  The engine now retains an explicit
  core-writer alias, and the compact comparison generator always uses that
  unpatched core writer.  Regression coverage verifies that loading the runtime
  hotfix cannot add project-only markers or other payload changes to compact
  comparison files.
- Built a fresh one-folder Windows owner-test package from the current dirty
  working tree using the retained r32.2 release environment.  The resulting
  archive is named
  `ChromaMatter-0.8beta-r32.2-LATEST-WORKINGTREE-OWNER-TEST-NON-DISTRIBUTABLE-20260902-win64.zip`.
- Verified the canonical `ChromaMatter/` archive root, 1,455-file inventory,
  CRC integrity, fresh-extraction file-size/SHA-256 parity, built and extracted
  self-tests, Japanese and English UI smoke starts, packaged-source policy, and
  all six required frozen radial / exact-partition modules.
- Preserved the active working tree, Git-history bundle, current r32.2 build
  environment, dependency source foundations, successful controlled rebuild
  evidence, current owner-test build tree, current radial/Arachne outputs, and
  the latest repaired multipart test project.
- Removed only audited obsolete data: old r8-r27 build/release trees,
  superseded owner-test packages, redundant extracted macOS candidates, old
  application-specific temporary caches, abandoned export staging, and
  byte-for-byte duplicate owner files after SHA-256 comparison.  One old
  OneDrive-backed application folder and one temporary dependency bootstrap
  containing reparse points were deliberately retained rather than crossing a
  filesystem boundary.
- The cleanup removed 88,221,399,121 logical bytes.  At the final post-cleanup
  measurement, system-drive free space was 87,809,949,696 bytes (81.78 GiB)
  above the pre-cleanup measurement.  These removals were permanent and not
  sent to the Recycle Bin.

### Current package state

- Windows owner-test ZIP size: 117,620,371 bytes.
- Windows owner-test ZIP SHA-256:
  `C7F5AFE72826B35E363F53FE8FA94FE1295A4FF579D21E1CC5E4EDD7D9156FB5`.
- The package is for owner testing only.  It is not a public stable build and
  must remain explicitly `NON-DISTRIBUTABLE` because the current public
  corresponding-source / controlled-build evidence does not yet match this
  dirty working-tree binary exactly.
- A final 503-file source working-tree snapshot must be generated immediately
  after this checkpoint so this exact handoff text is included.  Its exact
  filename, size, and SHA-256 belong in the task result rather than in this
  self-referential snapshot.  A verified complete Git-history bundle is
  retained beside it; superseded source ZIPs and temporary Git indexes should
  then be removed.

### Changed files

- `HANDOFF.md`
- `source/fixed_app/spectrum_mapper/engine.py`
- `source/fixed_app/spectrum_mapper/compact_black_radial_coupon.py`
- `source/fixed_app/test_compact_black_radial_coupon.py`

### Tests run

- Long integrated Python suite: 414/414 passed.
- Focused GUI layout / compact comparison / main shading bridge suite: 32/32
  passed.
- Runtime-hotfix import-order permutations: all passed.
- Source `compileall`: passed.
- Source `--self-test`: passed.
- Fresh build and fresh extraction `--self-test`: passed.
- Japanese and English UI smoke starts for both built and freshly extracted
  trees: passed.
- Frozen-module, source-policy, archive-CRC, and 1,455-file parity audits:
  passed.
- `git diff --check`: must be rerun after this handoff append.

### Next exact task

Use the owner-test ZIP for local functional testing only.  Before any public
replacement release, create matching corresponding-source material and a
controlled reproducible build/evidence set from the exact release tree, then
repeat the package and smoke audits under the public-release policy.

### Do not do

- Do not publish or redistribute the owner-test ZIP as a stable Windows build.
- Do not delete the active working tree, history bundle, retained r32.2 release
  environment, dependency source foundations, controlled rebuild evidence,
  current radial/Arachne outputs, or repaired multipart project.
- Do not use the conflicted legacy checkout as the source of truth.
- Do not commit, push, upload, or publish this checkpoint without an explicit
  owner request.

## 2026-09-06 ChromaMatter 0.9 output-accuracy checkpoint

### Version objective

The current source is now labelled `0.9` / `r33`.  The principal 0.9 upgrade
is **improved 3MF output accuracy and export success**, especially for an
ordinary single-logical GLB.  This is a source-development checkpoint only;
no 0.9 Windows, macOS, or Linux binary, archive, tag, or public release has
been created.

### Completed in this session

- Added a conservative single-logical GLB repair route.  It first welds only
  proven reverse-oriented exact-coordinate texture seams, then allows only
  remaining planar openings no wider than 2.0 mm to use the existing strict
  local cap repair.
- Revalidates the final result as watertight, consistently wound, and
  positive-volume.  A repair that cannot satisfy those gates remains a hard
  failure and the original model is preserved.
- Corrected generated-cap metadata so added faces never become negative
  "removed face" counts, cap faces are recorded as `LOCAL_CAP` only when their
  exact face-row geometry survives, and later simplification invalidates stale
  provenance fail-closed.
- Corrected the 2.0 mm physical-size gate so it uses the geometry that remains
  after configured tiny-component cleanup.  A far-away decorative island that
  will be discarded can no longer shrink the calculated hole size and make a
  genuinely large opening eligible for an automatic cap.
- Changed repeated tiny-hole validation from a complete topology rescan for
  every opening to an incremental edge index plus one independent final full
  topology proof per touched part.  Existing face order, cap IDs, and per-loop
  before/after records are preserved, while duplicate or stale loops still
  fail closed.
- Added a bounded dominant-surface fallback for an ordinary single-logical GLB
  whose otherwise valid texture-seamed surface is obstructed by microscopic
  embedded debris.  It runs only after the ordinary seam proof fails, requires
  one component to own at least 99.5% of all faces, classifies every discarded
  component under strict face/area/volume/containment limits, and independently
  proves that the retained surface closes through the production selective
  reverse-boundary seam weld.  A separate positive-volume solid is retained and
  causes a fail-closed stop.  No remesh, voxelization, or filename/hash-specific
  exception is used.  Inverted-shell containment stops before ray testing when
  its conservative upper bound exceeds 50,000,000 triangle-ray checks, and the
  proved selective-seam result is reused rather than computed twice.  If that
  retained surface was already indexed-watertight, its truthful identity record
  is admitted to the bounded source-preserved self-intersection policy only when
  its complete nested filter provenance, source-triangle preservation, count
  conservation, and serialized 3MF vertex/face counts remain exact; a plain
  identity record or altered provenance remains blocked.
- Added project snapshot round-trip coverage for repaired cap provenance.
- Removed the repair-failure path that offered or opened 3D boundary
  diagnostics.  The failure window now reports the failure without instructing
  the user to inspect red openings in 3D.
- Removed Radial Experiment from the ChromaMatter UI and forces legacy radial
  preferences/project values off.  The research implementation and tests stay
  in the source tree only for compatibility and possible future study.
- Updated the application version, Windows/macOS metadata, README aliases,
  feature documents, platform packaging/audit configuration, and issue form
  so they identify `0.9` / `r33` and describe output accuracy as the principal
  upgrade.  Published `0.8beta-r32.2` assets and evidence remain historical and
  immutable.
- Kept this repair route in the shared application engine used by all desktop
  targets.  The next separately validated Windows, macOS, and Linux 0.9 builds
  therefore receive the same repair behavior; no platform binary has been
  built or published at this checkpoint.

### Validation

- 489 focused output, repair, project, GUI, dormant-radial compatibility,
  hotfix, version, packaging-policy, and platform tests passed with zero
  failures.
- A previously failing private 371,939-face ordinary single-logical GLB passed
  the integrated Full Spectrum path.  The fallback proved and removed 393
  micro-debris faces, retained 371,546 source faces, and the final selective
  seam result contained 185,775 vertices, one positive watertight body, and
  zero boundary, non-manifold, winding, or degenerate errors.  Internal write
  validation and an independent reopened-3MF validation both passed in about
  16.6 seconds total.  The temporary 3MF was deleted, the source GLB
  hash/size/mtime remained
  unchanged, and the private asset was not copied into the repository.
- The source `--self-test` reported `ChromaMatter — AI Model Print Studio 0.9`
  and `ok: true`.
- Python `compileall`, `git diff --check`, and English/Japanese README alias
  identity checks passed.

### Scope still open

- Complex multipart repair remains input-dependent.  This checkpoint improves
  the ordinary single-logical GLB path and does not claim that all multipart
  models can now be closed or exported.
- No 0.9 package has been built or published.  Packaging requires a separate
  owner request and a fresh corresponding-source/compliance audit.
- The complete historical `test_release_tooling` suite is not green in this
  working tree: 36 of its 96 tests stop at the pre-existing PyTetWild frozen
  recipe/manifest identity mismatch.  The recipe and frozen release evidence
  were not changed as part of 0.9; resolve and re-audit that identity before a
  future public package is staged.

### Do not do

- Do not weaken final solid validation to increase the apparent success rate.
- Do not expose the dormant Radial Experiment controls in the public UI.
- Do not overwrite or relabel the published `0.8beta-r32.2` release artifacts.
- Do not commit, push, package, upload, or publish without an explicit owner
  request.

## 2026-09-06 — Windows 0.9 distributable preparation

### Objective and authority

The owner requested a Windows distribution first and explicitly approved a
local commit on the current feature branch so the executable and corresponding
source identify exactly the same source snapshot. GitHub push, website upload,
and publication are not authorized by this task.

### Candidate changes and evidence

- Current Windows package defaults, application component inventory, bilingual
  binary README and DemoData documents identify 0.9. Historical r32.2 records
  are preserved separately and tested as immutable history.
- Added an optional offline distribution mode that physically includes the
  verified complete corresponding-source ZIP under `corresponding-source/`.
  English/Japanese notices point to that real relative file. Exact source
  commit, source approval, manifests, SHA-256, native identities, license
  assets, privacy and fresh-extract ZIP gates remain mandatory.
- The actual attested PyTetWild recipe is now preserved byte-for-byte under
  `tooling/recipes/BUILD_PYTETWILD_WINDOWS_20260823.ps1`. The evolved developer
  recipe is not overwritten. The canonical closure binds the frozen recipe
  and its exact historical toolchain layout while retaining all wheel/PYD,
  raw-wheel, eight physical audit-log and attestation checks. Controlled
  native inputs and complete source caches are available locally; earlier
  missing-input and recipe-mismatch entries above are historical.
- Fresh Python 3.13.14 environment installation used the exact hash-verified
  controlled dependency wheel and the unchanged application hash lock. No
  replacement native wheel, elevated toolchain install, or UAC is needed.
- A dormant coupon regression caused by hotfix import order now calls the
  existing stable core writer, matching the compact coupon implementation.
  Archive validation is unchanged; both coupon suites pass 28 tests, including
  a real hotfix-first regression. This does not restore Radial Experiment UI.
- Optional Linux shell testing now detects whether the actual WSL test distro
  is installed; Windows' unconfigured launcher stub is not Linux evidence.
- Source-gate checks at this checkpoint: existing release tooling 96 tests
  passed; final closure/corresponding-source suites 66 passed; bundled Windows
  source mode 5 passed including exact-source negative cases. The initial broad
  source run exposed these packaging/import-order issues and was not a passing
  release run. A fresh full committed-source run is required below.

### Current state and next action

No new 0.9 binary is eligible yet. Finish the private-data audit, checkpoint the
source locally, build from an exact clean checkout, and run full regression,
packaged self-test, Japanese/English UI smoke, previously failing GLB-to-3MF,
exact complete-source assembly, native compliance inventory, ZIP CRC and
fresh-extract file-hash verification. Only after all gates pass should a local
Windows distribution ZIP be handed to the owner. Do not call an old package
or a source-only test a new executable verification.

Build output, virtual environment, complete-source dependency caches, private
validation input/output and logs remain local-only outside the repository.
Only the existing rights-approved source GLB/reference DemoData pair may enter
the distributable; generated/sample 3MF and private model data remain excluded.
No macOS/Linux binary or public release is produced by this Windows task.

## 2026-09-06 — Windows 0.9 local distributable verified

### Outcome and exact source identity

The owner-approved local feature-branch checkpoint and Windows distribution
are complete. All Windows gates left pending in the preparation entry above
have passed for this exact artifact. No GitHub push, site upload, remote
release, historical-release replacement or publication was performed.

- Frozen build and corresponding-source commit:
  `d8e3df0e69fb95c07ddf00fe52c4cf25152cbb62`.
- Software: `ChromaMatter-0.9-win64.zip`, 1,587,920,956 bytes, SHA-256
  `cdd5d2bd85946f93d1b77d4ec004d15f488f659fc90166e3c6dd67ed999b363e`.
- Executable SHA-256:
  `73a7cfc378595c77092971bc05563b2a7638522ea85eab22857a8a0a23ca487a`.
- Bundled complete corresponding source:
  `corresponding-source/ChromaMatter-0.9-complete-corresponding-source.zip`,
  1,365,921,068 bytes, SHA-256
  `279314a71570c8ae1876cf6530b202bed4517886c67e15e58f0fd26288b33a6f`.

This section and the matching CURRENT_STATE entry are post-artifact evidence
only, not compiled or packaged changes. They identify the frozen commit above,
not a later documentation-only HEAD. The source bundle necessarily preserves
that commit's pre-build checkpoint; this newer verification record supersedes
its pending status without altering or relabelling the verified artifact.

### Validation and limits

- Exact-source full regression: 1,894 tests in 458.149 seconds, zero failures,
  six optional skips. Fresh hash-locked Python 3.13.14 environment; dependency
  check passed. Compilation used the exact clean source checkout.
- Packaged self-test and Japanese/English UI smoke passed before packaging
  and again from an independently extracted final ZIP with fresh preferences
  and a system-only PATH. File resources, component map and SBOM identify 0.9.
- Native inventory: 1,455 runtime files, 256 native files, gate passed.
  Copy-local Qt/GEOS replacement checks and function probes passed with
  hash-different, ABI-identical DLLs carrying inert PE markers. This tests the
  replacement path, not arbitrary ABI compatibility or a fresh library build.
- Complete source: 42,909 file hashes, 506 exact committed project blobs,
  64 component records, eight native audit logs and the approved wheel/recipe
  closure verified independently; no known gaps.
- The exact executable exported a previously failing ordinary single-logical
  GLB through Full Spectrum 32 and Flat Four without QEM reduction. Both final
  3MFs independently passed CRC, serialized geometry, colour and recipe checks;
  371,546 retained faces, 185,775 vertices and one closed positive-volume body.
  Flat Four contained no mixed states. A bounded source-preserved warning for
  67 self-intersecting faces remains; do not claim zero self-intersections.
  The private input and executable were unchanged.
- Optional six-part public-demo export exceeded a 180-second test budget:
  outcome unknown, neither a passing test nor a proven export failure.
  Complex multipart success is not claimed and remains explicitly limited.
- Final software ZIP: canonical staging plus independent fresh extraction
  verified CRC, safe entry names, all 1,519 manifest records, absence of extra
  files, exact source archive and rights-approved demo payloads. Standalone
  self-test / Japanese / English smoke exits were all zero. The desktop ZIP
  copy has the same SHA-256. No private model or generated 3MF is distributed.
- The first independent verification helper stopped before runtime checks
  because a plain Python environment dictionary used the wrong Windows key
  case. Correcting that external helper and using a new extraction folder
  produced the passing second audit; the application and ZIP were not changed.

### Handoff and prohibited actions

The local desktop delivery folder is `ChromaMatter-0.9-Windows-Distribution`
and contains the software ZIP and checksum sidecar. Complete source, English
and Japanese instructions, license notices and the approved demo pair are
inside the software ZIP. This executable is unsigned.

This post-build checkpoint changes only HANDOFF.md and CURRENT_STATE.json.
Release-identity/bundled-release focused tests passed: 19 tests in 28.665
seconds. JSON parse and diff check passed; diff stat and feature-branch status
were checked, with only these two evidence files changed. Earlier source
changes are captured in the exact release commit and its preceding two local
commits; do not change packaged files without a fresh build and all gates.

All environment caches, build outputs, independent source/ZIP/replacement
audit logs and private model validation inputs/outputs remain local-only
outside the repository. Never add their private asset names, hashes or paths
to public records. Do not expose dormant radial controls or bypass geometry
validation. No new macOS or Linux binary has been built or tested here.

Next task: owner tests the Windows ZIP and, if desired, separately authorizes
publication. macOS/Linux need their own exact native build, source/compliance
and runtime checks before their 0.9 archives can be offered. This successful
Windows package is not evidence for another platform's executable.

## 2026-09-06 — Owner-selected export geometry checks (local source test)

### Request and implementation

The owner explicitly requested graduated acceptance rather than mandatory
strict repair for every export. Initial value is **high**; the ignore choice
is labelled **non-recommended**. Per owner preference there is no technical
explanation row in the application, only the compact selector and short
non-high confirmation. The default answer is No and consent is never persisted.

The current implementation is geometry-only:

- High preserves the previous strict solid/provenance policy and its bounded
  source-proven self-intersection warnings.
- Medium retains closed/manifold, winding, positive-volume and nondegenerate
  requirements but permits multiple bodies and does not scan self-intersections.
- Low also allows openings/nonpositive-or-undefined closed volume; manifold
  edges, consistent winding, nondegenerate triangles and at least one body
  remain required.
- Ignore permits measured topology defects. It neither repairs geometry nor
  claims a valid solid. Orca Slice Preview still needs user review.
- Every mode rejects nonempty-array violations, nonfinite coordinates/height,
  noninteger/out-of-range/negative triangle indices before integer narrowing or
  native processing, and retains archive, colour, filament/material, printer
  settings and pending-palette guards. No blanket EngineError suppression.
- Explicit caller policy is forwarded through all three portable/surface/
  adaptive adapters and individual exports. Assembly metadata records it but
  cannot authorize its own weaker validator policy. Non-high self-intersection
  status is truthfully `not_checked` with raw count -1, never `strict_zero`.
- UI/CLI low and ignore bypass automatic Solidify without changing manual
  repair algorithms. Policy persistence does not change geometry/paint cache
  keys. The CLI exposes `--export-validation` only alongside `--convert`.
- Reports and per-part manifests aggregate real validation outcomes at every
  level. A high individual-only export of two valid solids reports true solid
  validation; lower modes do not falsely claim a checked/repaired solid.

### Verification

- Focused final set: 61 tests passed, including eight geometry-policy cases
  with extensive matrix/subcase coverage, malformed numerical/index/colour
  rejection, atomic retention of an old destination, archive-policy tampering,
  individual output aggregation, actual-entrypoint Full Spectrum/Flat Four,
  JA/EN GUI/settings, CLI and material-mode compatibility.
- Fresh application regression after the last report fixes: 1,769 tests in
  145.322 seconds, zero failures, six optional skips. Only three unchanged
  distribution-tooling suites were excluded from this application-only run.
- Earlier full preflight: 1,933 tests in 445.412 seconds, zero failures, six
  optional skips. It started before the final aggregate-report correction, so
  it is not exact final packaged-binary evidence; the subsequent application
  regression and focused tests cover the corrected bytes.
- Source entrypoint self-test and isolated Japanese/English UI smoke passed.
  Real-entrypoint synthetic open-mesh export rejects high/medium and permits
  low/ignore through both Full Spectrum adaptive and Flat Four. Archive CRC,
  metadata, palette roots and no mixed Flat Four states were verified.
- Source-only approved public six-part GLB checks used explicit ignore mode.
  Without QEM reduction, both Full Spectrum 32 and Flat Four completed the
  combined 3MF with 2,054,777 faces; independent CRC/policy/palette checks passed.
  The full CLI bundles both reached the 180-second budget during individual
  export (Full Spectrum at part 1/6, Flat Four at part 5/6). This is partial
  evidence, not a complete full-resolution bundle success or validation error.
- A separate reduction fallback with a 200,000-face target retained 196,925
  faces. Both modes completed the combined 3MF, all six child 3MFs, manifest and
  report, including independent verification (102.56 seconds Full Spectrum;
  65.05 seconds Flat Four). Policy/warning propagation, CRC, checksums and
  palette checks passed; Flat Four had no mixed states. `valid_solids=false`
  and unchecked self-intersections remained truthful. Inputs were unchanged.
  Neither experiment tested actual Orca slicing or printing.
- After handoff/state updates, 53 release-identity/new-feature tests passed in
  3.240 seconds; JSON parse and diff check passed. Final public-demo evidence
  updates are documentation-only. Diff stat and feature-branch status were
  inspected; no files were staged or committed.

### Delivery, changed files and next task

The owner's desktop contains `ChromaMatter-0.9-Validation-Test.cmd`, a local
test launcher for the changed working source and existing pinned Python
runtime. It isolates preferences/data from the previous application. This is
not a portable ZIP or a newly frozen executable. The previous verified Windows
ZIP, its exact corresponding source and all remote publications are untouched.

Changes: AGENTS.md's explicit owner-requested export exception; models, GUI,
i18n, CLI, engine, workflow; the three existing writer adapters; the small new
export_validation module and four focused test modules. This checkpoint also
updates HANDOFF.md and CURRENT_STATE.json. No native dependency, license,
public version, radial visibility or packaging gate changed.

The current feature source is uncommitted. Do not push, publish, overwrite the
old ZIP or claim that it includes the new selector. A new public/frozen package
needs a separately authorized exact source checkpoint, fresh build/source/
runtime/archive gates and publication authority. All logs, local demo exports,
test profiles and launcher paths remain outside the repository; no private
input model was committed or included in a public artifact.

Next: owner tests a formerly failing model using the local launcher and the
selector; confirm the resulting geometry in Orca Slice Preview. If requested,
prepare a new exact Windows test/distribution ZIP after committing the source
with explicit authority. Other OS source shares the policy, but no macOS/Linux
binary has been built or claimed by this task.

## 2026-09-06 — Output settings and Solidify beside Export 3MF

### Objective and implementation

The owner confirmed successful export with the new validation policy, then
requested a clearer export route. The main footer now orders Output Settings,
Solidify, Export 3MF. Only Filament Settings remains in the upper ribbon.

- Output Settings opens a single modeless Toplevel constructed once during
  startup, before settings binding and localization. Close, Escape and the
  titlebar X withdraw it without destroying controls or resetting edits.
- Existing size/mesh and per-part output options moved into this window. The
  geometry-check selector is first in Output Options; high remains the initial
  default, ignore remains non-recommended, with no new technical explanation.
- The window uses two columns at normal width and stacks its sections when
  narrowed; vertical scrolling keeps the Close action independently reachable.
- Solidify is a separate footer action using the existing guarded unified
  repair flow. Its early busy/closing guard runs before repair flags mutate.
  It is disabled until a source is available. There is no duplicate Solidify
  control inside the settings window.
- A successful worker start hides settings and disables both new actions.
  Completion/error callbacks update them after installing or clearing source
  state; callbacks starting another job keep them disabled. This includes exact
  project restoration, which installs its source inside the completion callback.
- A bounded status-message host prevents long progress/error text from pushing
  the footer buttons outside the client area. Settings window titles and
  buttons update on live language changes. The legacy internal output-tab
  request routes to the new window without changing the filament ribbon.
- Export acceptance, repair algorithms, pending-palette guards, manual paint,
  preferences/project serialization, version and hidden experiments are unchanged.

### Verification and scope

The initial focused GUI/i18n/window suite passed 50 tests. The application
regression then passed 1,778 tests in 181.568 seconds, with six expected optional
skips and no failures. It excludes only the three unchanged slow packaging
suites and predates the final post-callback button-refresh fix. Independent Tk
reproduction confirms that fix enables Solidify after a completed project load;
the final focused run passed 92 tests in 24.876 seconds with no skips or failures.
It includes four new actual-queue callback regressions (source installed/cleared,
chained busy job, worker/error-callback recovery), window/layout/localization,
validation UI, help compatibility, release identity and real export adapters.
JSON parse, diff check, diff stat and feature-branch status also passed/recorded.

Computer-use checks of the actual source-entrypoint app verified the main
footer, separate settings opening/closing, and Japanese/English window text.
The setting window's geometry check is visible first. Automated tests also
verify footer containment at 1180x740 and 1540x920 even with very long status
text, narrow-window stacking, scroll access and retained pending values. This
is source-runtime/UI evidence, not a new binary, model-repair or printability
claim. Broader existing filament-panel layout was not redesigned in this task.

### Delivery and next task

Restart the existing desktop `ChromaMatter-0.9-Validation-Test.cmd` to use the
new arrangement. It still runs the local working source with separate owner
test preferences. No new ZIP, executable, source-vault upload, commit or public
release was created. The earlier verified Windows ZIP remains unchanged and
does not contain either this window or the validation selector.

Changed in this follow-up: gui.py, i18n.py, test_gui_layout.py, test_i18n.py,
new test_output_settings_window.py, HANDOFF.md and CURRENT_STATE.json. Prior
uncommitted validation-level work is preserved. The isolated QA launcher,
profiles and test logs stay outside the repository; no private models were
read or exported for this layout task. Both interactive QA sessions were closed.

Next: owner checks this route with an existing project. Build/release/commit
still requires the corresponding explicit authority and exact fresh gates;
do not claim the old packaged Windows bytes include these source-only changes.
