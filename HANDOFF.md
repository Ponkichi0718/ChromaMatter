# ChromaMatter cross-PC handoff

Updated: 2026-08-23
Branch: `codex/r32-full-spectrum-workflow`
Draft PR: <https://github.com/Ponkichi0718/ChromaMatter/pull/1>
Public version: `0.8beta` (do not change without an explicit owner request)

## Current objective

Prepare a redistributable Windows r32 release while retaining TetGen under its
AGPL route. Keep the ChromaMatter application under `GPL-3.0-or-later`, preserve
each third-party license, and publish the Windows ZIP only together with a
single complete corresponding-source bundle containing both the matching
application source and all required third-party source, plus the SBOM,
component map, notices, relinking instructions, and checksums.

This continuation resumed from GitHub on the home PC. The latest pushed source
checkpoint before the current toolchain-contract correction is
`195bf66cb6918326f77c4c668e600bcf1d617ec6`; local `HEAD`, the upstream feature
branch, and Draft PR #1 all pointed to it at the start of this correction. The
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
- Binary publication remains NO-GO. Remaining gates are controlled PyTetWild
  rebuild evidence; updating the application lock to that wheel; a
  `release-approved` complete corresponding-source bundle; a current clean
  binary build with packaged self-test and Japanese/English UI smoke;
  fresh-extract manifest/privacy/archive/checksum parity; and immutable HTTPS
  Release URLs with every required asset published simultaneously.

## 2026-08-23 binary-publication compliance continuation (current)

- Added exact path/case/size/SHA-256 identities for 19 non-Qt PyMeshLab native
  files and 7 Qt DLLs. The generator and software stage independently reject
  missing or mismatched audited native identities.
- Added a reviewed Qt closure manifest covering 50 static components and 51
  byte-exact licence assets. The PyInstaller spec, component-map/SBOM generator,
  and software stage all consume it fail closed.
- Added a PyTetWild static/header closure contract covering 20 components, 29
  byte-exact licence assets, and 15 source archives. It is intentionally
  `release_gate.status=blocked`: the historical PyPI wheel/PYD is audit-only,
  and a controlled rebuilt wheel/PYD plus matching application lock do not yet
  exist.
- The component map now records PyTetWild closure validation violations and the
  SBOM carries the matching validation count. The software stage independently
  enforces the wrapper identity, sorted 20-component mapping, 29 assets, and
  blocked release gate whenever a PyTetWild runtime is present. Packages that
  genuinely do not contain PyTetWild remain stageable.
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
- A fresh public-source stage passes at 395 files including the manifest and
  394 manifest records. Both the staged privacy audit and an independent
  path/SHA-256 parity check report zero missing, extra, or mismatched files.
  Source publication eligibility is true for this validated source-only scope;
  binary publication eligibility remains false.
- A current generator probe against the old audit-only package failed closed as
  designed. It reported the historical PyTetWild wheel/application-lock
  mismatch and blocked closure gate; that old package is not release evidence.

## Current state

- Latest pushed checkpoint `195bf66cb6918326f77c4c668e600bcf1d617ec6` is already on
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
- The new internal multipart test ZIP validates the current application bytes
  for owner testing only. It deliberately bypasses the public software stage
  because the approved corresponding-source and controlled PyTetWild rebuild
  evidence do not yet exist; it does not change binary publication NO-GO.
- `CURRENT_STATE.json` now records the latest source regression and public-source
  stage separately from the historical pre-multipart binary preflight. Do not
  treat the old executable hash or file counts as evidence for this worktree.
- Source publication and binary publication are separate. Existing public
  source history remains available; the new Windows binary remains NO-GO.
- The corresponding-source manifest deliberately remains candidate-only until
  the new PyTetWild repaired wheel, distinct raw wheel, exact eight direct audit
  logs, attestation, rebuild lock, and final source stage exist. The MeshLab
  acquisition lock is complete, but its final staged bundle has not yet been
  produced. The verified public-source preview above is a source-tree
  completeness check, not that final corresponding-source bundle.
- All prospective native inputs are present and fixed. The verified offline
  Visual Studio Build Tools 17.14.39 layout was installed successfully on
  2026-08-23 at `C:\ChromaMatterToolchain\VS2022BuildTools`. The installed
  instance is complete and launchable, selects VCTools 14.44.35207 and Windows
  SDK 10.0.26100.0, and matches the fixed layout evidence. No reinstall or
  redownload is required. No PyTetWild wheel has yet been built from the
  corrected recipe; the next blocker is the controlled outbound-isolated build.
- The root `SOURCE_MANIFEST_SHA256.txt` is historical and stale for this changed
  tree. Regenerate it only through final source staging after release inputs are
  frozen; do not edit it manually as present evidence.

## Next exact task

1. Review Draft PR #1 from `codex/r32-full-spectrum-workflow`; keep `main`, tags,
   and public Releases unchanged until the binary publication gates below pass.
2. Keep the successful verified offline VS installation at
   `C:\ChromaMatterToolchain\VS2022BuildTools`; do not reinstall, redownload, or
   substitute a newer channel, MSVC toolset, or SDK. Commit and push the
   corrected toolchain identity contract before producing rebuild evidence.
3. Enforce an OS/hypervisor outbound deny-all policy (or physically disconnect
   the builder), then run `tooling/BUILD_PYTETWILD_WINDOWS.ps1` with
   `-OsNetworkIsolationConfirmed` and a new, unused output directory. Preserve
   the repaired wheel, distinct raw wheel, exact eight direct audit logs, build
   recipe, 39-package lock, source patch, and attestation together.
4. Replace the historical PyTetWild hash in the application
   `requirements-build.lock`, then use `BOOTSTRAP_WINDOWS.ps1 -PyTetWildWheel`
   from a new clone/venv. Preserve the wheel, application lock, rebuild lock,
   hashed build requirements, recipe, and attestation.
5. Stage full corresponding source with the complete MeshLab archive lock and
   every PyTetWild bound evidence input. When passing a verified rebuild lock,
   pass the repaired release wheel with `-PyTetWildWheel`, the distinct
   pre-repair wheel with `-PyTetWildRawWheel`, and the directory containing the
   audit logs with `-PyTetWildAuditLogs`, in addition to the recipe, hashed
   requirements, source patch, attestation, and exact application lock. Require
   the recipe, hashed requirements, source patch, and application lock to
   byte-match their canonical paths at the exact project commit. Require output
   `COMPONENT_SOURCES.json` status `release-approved`.
6. Freeze artifact names and immutable HTTPS source-offer URLs. From a new clean
   build root run the full regression and PyInstaller build, then run
   `tooling/generate_binary_compliance_inventory.py` with its required
   `--package-root`, `--sbom-output`, and `--component-map-output` arguments.
7. Stage and fresh-extract the software and source archives; run packaged
   self-test, Japanese/English UI smoke, manifest, privacy, CRC, byte-parity,
   relinking, and checksum audits.
8. Publish the Windows ZIP, complete corresponding source, SBOM, component map,
   and detached checksum simultaneously at the exact immutable HTTPS Release
   URLs already embedded in the source offers. Backpatch `CURRENT_STATE.json`
   and public status documents only with those exact results. Keep
   `binary_publication_eligible=false` until every gate passes.

Controlled prospective matrix (inputs acquired and hashed, but not yet a
completed build): CPython 3.12.10 x64 builder; Visual Studio Build
Tools 2022 17.14.39; VCTools directory 14.44.35207; `cl.exe` file version
19.44.35228.0 and product version 14.44.35228.0; `link.exe` file and product
version 14.44.35228.0; Windows SDK 10.0.26100; CMake
3.29.6; Ninja Python distribution 1.13.0; nanobind 2.12.0 at commit
`2a61ad2494d09fecb2e13322c1383342c299900d`; cibuildwheel 3.3.1;
scikit-build-core 0.12.2; delvewheel 1.12.1; abi3audit 0.0.26; build 1.5.0;
MPIR 3.0.0 `he025d50_1002`; NumPy 2.5.1 for the isolated normal-import smoke.
The VS layout is fixed at 714 files, 2,651,377,645 bytes, tree SHA-256
`2b6a89bb69aa7de013fc055828258a3a91c7c333f0c6be831a750990922fed3a`.
This is a new prospective rebuild, not a claim about the expired historical CI
environment.

The installed-toolchain audit confirmed that 14.44.35211 is the CRT
redistributable version, not `Microsoft.VCToolsVersion.default.txt`. The build
recipe now checks the exact VCTools, compiler, and linker identities above. It
also resolves the SDK from the 64-bit native, 64-bit WOW6432Node, and 32-bit
view `KitsRoot10` values and accepts exactly one distinct candidate containing
both the fixed x64 `signtool.exe` and `kernel32.lib`; the current native
registry root is incomplete and the verified SDK root is the WOW6432Node
candidate. An explicit `-WindowsSdkRoot` remains supported but must itself be
the one complete root.

For that future verified-lock stage, the `-PyTetWildAuditLogs` directory must
contain exactly these eight direct files and nothing else:
`visual-studio-layout-verification.log`, `build-wheel.log`,
`delvewheel-show-raw.log`, `delvewheel-repair.log`,
`abi3audit.log`, `native-dependency-closure.log`, `native-smoke-install.log`, and
`native-normal-import.log`. Nested entries, extra files, and symlinks are
rejected. Staging verifies the separate raw and repaired wheel identities and
all eight log SHA-256 values against the build attestation, then copies them to
`build-evidence/pytetwild/raw-wheel/`,
`build-evidence/pytetwild/repaired-wheel/`, and
`build-evidence/pytetwild/logs/`, respectively. None of those staged evidence
outputs exists yet.

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
- `licenses/BUILD_ENVIRONMENT_EN.md`
- `licenses/BUILD_ENVIRONMENT_JA.md`
- `publication/BINARY_RELEASE_HANDOFF_JA.md`
- `source/fixed_app/TripoSpectrumMapper_fixed.spec`
- `source/fixed_app/test_corresponding_source_tooling.py`
- `source/fixed_app/test_decal_image.py`
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
- Production corresponding-source manifest validation: PASS with intended
  status `candidate-only-not-release-approved`.
- Public-source stage: 395 files including `SOURCE_MANIFEST_SHA256.txt`, 394
  manifest records, privacy audit PASS, independent exact path/SHA-256 parity
  PASS with zero missing, extra, or mismatched files.
- PyTetWild-containing old audit-package probes: FAIL-CLOSED as intended; no
  publication destination/archive was retained and no old package became
  release evidence.
- PowerShell parser, nine machine-readable JSON manifests, 189 Python files,
  `pip check`, and `git diff --check`: PASS. Two byte-preserved upstream Qt
  `qt_attribution.json` assets contain upstream control characters and are not
  treated as application JSON; their exact bytes are validated by the Qt
  manifest/hash tests.

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
