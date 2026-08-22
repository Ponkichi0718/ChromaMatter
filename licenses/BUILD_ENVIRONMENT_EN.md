# Exact Windows build environment

The corresponding-source archive is authoritative for a binary release. Use
its pinned requirements, scripts, component map, and sources together; do not
substitute a newer checkout as the source for an older binary.

## Pinned baseline

- Windows x64
- Python 3.13.14 x64
- PyInstaller 6.20.0, one-folder mode, UPX disabled
- versions and SHA-256 hashes in `source/fixed_app/requirements-build.lock`

## Build and test

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1
powershell.exe -ExecutionPolicy Bypass -File .\BUILD_AND_TEST.ps1 `
  -RuntimeRoot .\.venv `
  -Build `
  -BuildOutputRoot C:\ChromaMatterBuild
```

## Controlled PyTetWild rebuild

Build a release wheel with `tooling/BUILD_PYTETWILD_WINDOWS.ps1`,
`tooling/requirements-pytetwild-build.lock`, and
`tooling/patches/pytetwild-0.3.0-optional-pyvista.patch` as one bound input set.
The recipe checks CPython 3.12.10, VS Build Tools 17.14.39, MSVC 14.44.35211,
Windows SDK 10.0.26100.7705, fixed source commits, MPIR, Eigen, and 39 hashed
Python wheels.

Before running it, enforce outbound deny-all at the OS or hypervisor layer, or
physically disconnect the builder. The switch below records the operator's
confirmation; it does not claim that the script configured the OS firewall.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tooling\BUILD_PYTETWILD_WINDOWS.ps1 `
  -OsNetworkIsolationConfirmed `
  -OutputRoot C:\ChromaMatterToolchain\pytetwild-controlled-build-001
```

After a future successful rebuild, preserve the repaired release wheel and the
distinct pre-repair raw wheel without allowing their identical filenames to
overwrite each other. Preserve both wheels together with the attestation,
recipe, requirements lock, source patch, and exactly these eight direct audit
log files:

- `visual-studio-layout-verification.log`
- `build-wheel.log`
- `delvewheel-show-raw.log`
- `delvewheel-repair.log`
- `abi3audit.log`
- `native-dependency-closure.log`
- `native-smoke-install.log`
- `native-normal-import.log`

The audit-log directory must contain only those eight direct files: no extra
file, nested entry, or symlink is permitted.

To use a controlled-rebuild PyTetWild wheel, first update the PyTetWild
SHA-256 in `requirements-build.lock` to that wheel and use a new virtual
environment with an explicit input. Bootstrap stops if the wheel, version,
ABI tag, or hash differs.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1 `
  -PyTetWildWheel C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl
```

When a verified PyTetWild rebuild lock is supplied to the corresponding-source
stage, `-PyTetWildRawWheel` and `-PyTetWildAuditLogs` are also mandatory. The
following is a future staging example, not a record of a completed build:

```powershell
$projectCommit = (git rev-parse HEAD).Trim()
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_corresponding_source.ps1 `
  -Destination C:\ChromaMatterSource `
  -Cache C:\ChromaMatterSourceCache `
  -ProjectRepository (Get-Location).Path `
  -ProjectCommit $projectCommit `
  -ExternalArchiveLock .\tooling\meshlab_windows_external_archives.lock.json `
  -PyTetWildRebuildLock C:\release-inputs\pytetwild-rebuild-lock.json `
  -PyTetWildWheel C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl `
  -PyTetWildRawWheel C:\release-inputs\raw-wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl `
  -PyTetWildAuditLogs C:\release-inputs\pytetwild-audit-logs `
  -PyTetWildBuildRecipe C:\release-inputs\BUILD_PYTETWILD_WINDOWS.ps1 `
  -PyTetWildBuildRequirements C:\release-inputs\requirements-pytetwild-build.lock `
  -PyTetWildSourcePatch C:\release-inputs\pytetwild-0.3.0-optional-pyvista.patch `
  -PyTetWildBuildAttestation C:\release-inputs\pytetwild-build-attestation.json `
  -ApplicationRequirementsLock C:\release-inputs\requirements-build.lock `
  -Archive C:\ChromaMatterSource.zip
```

The supplied build recipe, PyTetWild build-requirements lock, source patch, and
application requirements lock must byte-match their canonical blobs at
`$projectCommit`. Commit those static inputs before final staging; otherwise a
working-tree-only copy is rejected. The stage verifies the distinct raw and
repaired wheel identities and hashes, plus the filename and SHA-256 of every
audit log, against the attestation. It then stages them separately under
`build-evidence/pytetwild/raw-wheel/`,
`build-evidence/pytetwild/repaired-wheel/`, and
`build-evidence/pytetwild/logs/`. No such final evidence stage has been run yet.

`BUILD_AND_TEST.ps1` verifies Python 3.13.14, runs tests, invokes the pinned spec,
checks runtime resources, and executes the packaged self-test.

## Binary release stage

`BUILD_AND_TEST.ps1` generates `compliance/BINARY_COMPONENT_MAP.json` and
`compliance/SBOM.cdx.json` from the exact one-folder output.
`tooling/stage_software_package.ps1` requires both generated inventories, the
final complete corresponding-source archive and its external manifest, the
archive SHA-256, the exact ChromaMatter source commit, and an HTTPS Release URL
whose asset name matches the verified archive. The stage rejects a bundle unless
`COMPONENT_SOURCES.json` is `release-approved`, has no `known_gaps`, matches the
requested project commit byte-for-byte inside the archive, and passes all binary
inventory checks.

```powershell
$sourceArchive = 'C:\release\ChromaMatter-0.8beta-r32-complete-corresponding-source.zip'
$sourceManifest = 'C:\release\ChromaMatter-0.8beta-r32-complete-corresponding-source\COMPONENT_SOURCES.json'
$sourceCommit = (git rev-parse HEAD).Trim()
$sourceSha256 = (Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_software_package.ps1 `
  -BuiltAppRoot C:\ChromaMatterBuild\dist\ChromaMatter `
  -BinaryComponentMapPath C:\release\BINARY_COMPONENT_MAP.json `
  -SbomPath C:\release\SBOM.cdx.json `
  -CorrespondingSourceArchivePath $sourceArchive `
  -CorrespondingSourceManifestPath $sourceManifest `
  -CorrespondingSourceArchiveSha256 $sourceSha256 `
  -CorrespondingSourceProjectCommit $sourceCommit `
  -CorrespondingSourceUrl https://github.com/OWNER/REPO/releases/download/TAG/ChromaMatter-0.8beta-r32-complete-corresponding-source.zip
```

Publish the binary and exact source archive together. A successful local stage
does not prove that the source URL has been uploaded or is publicly reachable.
