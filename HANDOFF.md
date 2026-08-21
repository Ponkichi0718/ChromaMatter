# ChromaMatter cross-PC handoff

Updated: 2026-08-21
Branch: `codex/r32-full-spectrum-workflow`
Draft PR: <https://github.com/Ponkichi0718/ChromaMatter/pull/1>
Public version: `0.8beta` (do not change without an explicit owner request)

## Current objective

Prepare a redistributable Windows r32 release while retaining TetGen under its
AGPL route. Keep the ChromaMatter application under `GPL-3.0-or-later`, preserve
each third-party license, and publish the Windows ZIP only together with the
matching application source, complete third-party corresponding source, SBOM,
component map, notices, relinking instructions, and checksums.

This session is a local handoff checkpoint. The owner subsequently authorized
one local commit on `codex/r32-full-spectrum-workflow`; push remains
unauthorized until separately requested.

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

## Current state

- The compliance and handoff changes are recorded in one local feature-branch
  commit. The pre-commit checkpoint contained 10 modified tracked files and 28
  intended new files (38 paths total), with `git diff --check` passing.
- Origin still points to
  `7dbbe07ee135de58c37dc24e15880ed4ecc7dfc8`; the new local commit has not been
  transferred to GitHub yet.
- `main` was not modified. The commit was made only on
  `codex/r32-full-spectrum-workflow`, and no push was performed.
- GitHub Desktop on the home PC cannot receive this commit until the owner
  authorizes **Push origin** from this PC. Do not switch the commit target to
  `main`.
- The existing r32 Windows ZIP and EXE predate these compliance changes and are
  **not publishable**.
- `CURRENT_STATE.json` still describes the earlier r32 preflight. That evidence
  is historical for the changed working tree and must be backpatched only after
  the new integrated tests/build. Do not treat the old executable hash or file
  counts as evidence for this worktree.
- Source publication and binary publication are separate. Existing public
  source history remains available; the new Windows binary remains NO-GO.
- The corresponding-source manifest deliberately remains candidate-only while
  unresolved build provenance is present.

## Next exact task

1. Read `AGENTS.md`, this file, `CURRENT_STATE.json`, and
   `publication/BINARY_RELEASE_HANDOFF_JA.md`.
2. Run `git status --short --branch`, inspect the latest local commit, and do
   not discard or rewrite the checkpoint.
3. Run the focused legal/inventory/corresponding-source/staging tests listed
   below. Fix only reproducible failures.
4. Close the PyTetWild prospective-rebuild gate: pin all build dependencies and
   toolchain inputs, build a new wheel without network access during the build,
   verify its RECORD/native payload, and replace the historical wheel hash in
   `requirements-build.lock`. Never guess the unknown historical nanobind version.
5. Generate the complete corresponding-source candidate using the checked-in
   external archive lock. Verify its manifest, privacy, archive paths, and CRC.
6. From a clean clone and new virtual environment, run the full regression and
   clean PyInstaller build. Then stage and fresh-extract the software package.
7. Backpatch `CURRENT_STATE.json` and public status documents only with the new
   exact results. Keep `binary_publication_eligible=false` until every gate passes.
8. Ask the owner separately before pushing. The authorization recorded here
   covers the local checkpoint commit only.

For the normal two-PC cycle after this unpushed checkpoint: authorize and use
**Push origin** on PC A; on PC B, use GitHub Desktop **Fetch origin**, select
the same feature branch, then **Pull origin** before starting. Never edit the
same branch independently on both PCs before pulling the other PC's latest
commit.

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

Current intended groups (verify with `git status` because this file is updated
before each power-off):

- Session protocol: `AGENTS.md`, `HANDOFF.md`,
  `publication/BINARY_RELEASE_HANDOFF_JA.md`.
- Dependency/build: `BOOTSTRAP_WINDOWS.ps1`, `BUILD_AND_TEST.ps1`,
  `source/fixed_app/requirements-build.lock`,
  `source/fixed_app/TripoSpectrumMapper_fixed.spec`.
- UI: `source/fixed_app/spectrum_mapper/gui.py`,
  `source/fixed_app/spectrum_mapper/i18n.py`,
  `source/fixed_app/spectrum_mapper/legal_notice.py`.
- Compliance documents: new and updated files under `licenses/`.
- Compliance tools: `tooling/generate_binary_compliance_inventory.py`,
  `tooling/stage_corresponding_source.py`,
  `tooling/stage_corresponding_source.ps1`,
  `tooling/corresponding_source_components.json`,
  `tooling/meshlab_windows_external_archives.lock.json`,
  `tooling/pytetwild_rebuild_lock.template.json`,
  `tooling/stage_software_package.ps1`,
  `tooling/stage_public_source.ps1`.
- Restored public tool: `tooling/update_budget_filament_library.py`.
- Tests: `source/fixed_app/test_legal_notice.py`,
  `source/fixed_app/test_binary_compliance_inventory.py`,
  `source/fixed_app/test_corresponding_source_tooling.py`, and
  `source/fixed_app/test_release_tooling.py`.
- Ignore rules: `.gitignore`.

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
- Subscription receipts, account screenshots, job IDs, and other rights
  evidence containing personal information. Record only a redacted public
  provenance statement when needed.
