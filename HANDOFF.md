# ChromaMatter cross-PC handoff

Updated: 2026-08-25
Current worktree branch: `codex/r32-2-experimental-flat4-large-glb-2d-filter`
Published release-development source: `codex/r32-2-demo-3mf`; the frozen
published release source is `v0.8beta-r32.2` /
`aba20685d2fd6987621b2e1e6624f46ea84912a3`
Previous release: `v0.8beta-r32.1` remains immutable previous evidence.
Public version: `0.8beta` (do not change without an explicit owner request)
Current published prerelease revision: `r32.2`; Windows numeric version remains `0.8.0.0`

## Current objective

Maintain the published r32.2 prerelease and its manifest-locked derived 3MF demo
outputs without changing any tagged asset. TetGen remains under its AGPL route;
the ChromaMatter application remains `GPL-3.0-or-later`; each third-party
license remains preserved. The Windows ZIP is paired with the complete
corresponding-source bundle, SBOM, component map, notices, relinking
instructions, workflow video, and detached checksums.

Published `v0.8beta-r32` at commit
`86e34b2a9468f81768ee134a680a792b1a83df05` is immutable previous evidence.
Do not replace its tag, assets, or `SHA256SUMS-r32.txt`. The r32.1 update uses
new `ChromaMatter-0.8beta-r32.1-*` asset names and `SHA256SUMS-r32.1.txt`.

The r32.1 scope changes the preview label to AI Model Color and adds the
rights-cleared Hi3D multipart GLB/reference demo to the Windows package with
short instructions, part-name warnings, and mandatory Weak Black guidance.
The r32 modelling and 3MF contracts remain unchanged.

## Current published state (supersedes historical checkpoints below)

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
- **0.8beta limitation:** multipart solidification is not universally reliable.
  The bundled `DemoData` succeeds, but other multipart OBJ/GLB files can fail
  solidification or 3MF export. This incomplete compatibility is one reason the
  product remains `0.8beta`.

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
