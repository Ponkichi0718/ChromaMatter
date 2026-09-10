# Exact Windows build environment

The corresponding-source archive is authoritative for a binary release. Use
its pinned requirements, scripts, component map, and sources together; do not
substitute a newer checkout as the source for an older binary.

For a self-contained **0.9 Windows** distribution, the complete source ZIP is
inside `corresponding-source/` beside the application. Its exact filename,
SHA-256, and application commit are recorded in `licenses/SOURCE_OFFER_EN.txt`.
You do not need to extract the source archive to run the application. The
commands below are reproduction instructions, not evidence of a completed or
published 0.9 build. Use new, empty output directories for each attempt.

## Pinned baseline

- Windows x64
- Python 3.13.14 x64
- PyInstaller 6.20.0, one-folder mode, UPX disabled
- versions and SHA-256 hashes in `source/fixed_app/requirements-build.lock`

## Build and test

```powershell
$pyTetWildWheel = 'C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl'
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1 `
  -PyTetWildWheel $pyTetWildWheel
powershell.exe -ExecutionPolicy Bypass -File .\BUILD_AND_TEST.ps1 `
  -RuntimeRoot .\.venv `
  -Build `
  -BuildOutputRoot C:\ChromaMatterBuild
```

## Controlled PyTetWild rebuild

The adopted release wheel is bound to the immutable recipe
`tooling/recipes/BUILD_PYTETWILD_WINDOWS_20260823.ps1`,
`tooling/requirements-pytetwild-build.lock`, and
`tooling/patches/pytetwild-0.3.0-optional-pyvista.patch` as one bound input set.
The frozen recipe is 82,572 bytes with SHA-256
`d00cc6cdbc61abeaa040dfc81a3dfe7086ac0027685d798ac70f46e14e4360c8`.
The separate `tooling/BUILD_PYTETWILD_WINDOWS.ps1` is a development recipe;
changes to it are not evidence for the already adopted wheel. Do not substitute
it when verifying that wheel. Reusing the exact wheel and its complete verified
build evidence does not require another native rebuild or administrator prompt.
If the inputs or toolchain change, produce and audit new build evidence instead.
The recipe checks CPython 3.12.10, VS Build Tools 17.14.39, the installed
VCTools directory version 14.44.35207, `cl.exe` file version 19.44.35228.0 and
product version 14.44.35228.0, `link.exe` file and product version
14.44.35228.0, Windows SDK 10.0.26100.7705, fixed source commits, MPIR, Eigen,
and 39 hashed Python wheels. The nearby 14.44.35211
value belongs to the CRT redistributable and is not the installed VCTools
directory version.

Unless `-WindowsSdkRoot` is supplied, the recipe examines the 64-bit native,
64-bit WOW6432Node, and 32-bit-view `KitsRoot10` registry values and accepts
exactly one distinct root that contains both the fixed-version x64
`signtool.exe` and `kernel32.lib`. This is necessary when the native registry
root is incomplete but the exact SDK is installed under `Program Files (x86)`;
zero or multiple complete roots stop the build.

On Windows PowerShell 5.1, the recipe scopes `[Console]::OutputEncoding` to
strict UTF-8 without a BOM only while invoking `vswhere.exe -utf8`, then
restores the previous encoding in `finally`. This prevents localized
installation names in the JSON from being decoded through the active console
code page.

Windows PowerShell 5.1 can also strip embedded double quotes when multiline
source is passed directly to a native `python -c` invocation. The recipe routes
every multiline Python probe through `Get-ControlledPythonArguments`, which
encodes strict UTF-8 source bytes as Base64 and sends a fixed ASCII bootstrap
plus the original positional arguments. Do not replace this transport with a
direct multiline `-c` argument.

Before running it, enforce outbound deny-all at the OS or hypervisor layer, or
physically disconnect the builder. The switch below records the operator's
confirmation; it does not claim that the script configured the OS firewall.

```powershell
$newControlledRoot = Join-Path 'C:\ChromaMatterToolchain' `
  ('pytetwild-controlled-build-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tooling\recipes\BUILD_PYTETWILD_WINDOWS_20260823.ps1 `
  -RequirementsLock .\tooling\requirements-pytetwild-build.lock `
  -PyTetWildSourcePatch .\tooling\patches\pytetwild-0.3.0-optional-pyvista.patch `
  -OsNetworkIsolationConfirmed `
  -OutputRoot $newControlledRoot
```

These explicit lock and patch paths are required when running the preserved
recipe from its `recipes/` directory. The historical adopted controlled run
`20260823-174626-089357844d4b` succeeded at project
commit `5feb198eef3432cdec19a0367d53e1b52bd4a363`. Its repaired wheel SHA-256 is
`e3b11ac058266d277b0f83448c6023d5da98e731d0d016e461dbce4ebdfd613d` and its
attestation SHA-256 is
`3989fd1debe8b6c984938c4a64ee5fb3bcce1b612cf83524ea309b1fae3cde9f`.
The repaired release wheel and distinct pre-repair raw wheel are preserved
separately so their identical filenames cannot overwrite each other. Preserve
both wheels together with the attestation, recipe, requirements lock, source
patch, and exactly these eight direct audit log files:

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

The application lock already binds the adopted repaired wheel. Use a new
virtual environment and provide that wheel explicitly. Bootstrap stops if its
version, ABI tag, or SHA-256 differs. A future replacement wheel requires a
reviewed lock and static-closure update before it may be used.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1 `
  -PyTetWildWheel C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl
```

When a verified PyTetWild rebuild lock is supplied to the corresponding-source
stage, `-PyTetWildRawWheel` and `-PyTetWildAuditLogs` are also mandatory. Generate
a new lock for the exact application commit with
`tooling/generate_pytetwild_rebuild_lock.py`; this verifies the native wheel's
preserved evidence against the current canonical inputs rather than reusing an
older application's approval. The example below assumes the fixed inputs have
been exported byte-for-byte from that commit to `C:\release-inputs` and the
complete verified source cache is already present. `-Offline` refuses missing
cache entries instead of fetching them. It does not make initial Python or
toolchain installation offline:

```powershell
$projectCommit = (git rev-parse HEAD).Trim()
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_corresponding_source.ps1 `
  -Destination C:\release\ChromaMatter-0.9-complete-corresponding-source `
  -Cache C:\ChromaMatterSourceCache `
  -ProjectRepository (Get-Location).Path `
  -ProjectCommit $projectCommit `
  -ExternalArchiveLock .\tooling\meshlab_windows_external_archives.lock.json `
  -PyTetWildRebuildLock C:\release-inputs\pytetwild-rebuild-lock.json `
  -PyTetWildWheel C:\release-inputs\wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl `
  -PyTetWildRawWheel C:\release-inputs\raw-wheel\pytetwild-0.3.0-cp312-abi3-win_amd64.whl `
  -PyTetWildAuditLogs C:\release-inputs\pytetwild-audit-logs `
  -PyTetWildBuildRecipe C:\release-inputs\BUILD_PYTETWILD_WINDOWS_20260823.ps1 `
  -PyTetWildBuildRequirements C:\release-inputs\requirements-pytetwild-build.lock `
  -PyTetWildSourcePatch C:\release-inputs\pytetwild-0.3.0-optional-pyvista.patch `
  -PyTetWildBuildAttestation C:\release-inputs\pytetwild-build-attestation.json `
  -ApplicationRequirementsLock C:\release-inputs\requirements-build.lock `
  -Offline `
  -Archive C:\release\ChromaMatter-0.9-complete-corresponding-source.zip
```

The supplied build recipe, PyTetWild build-requirements lock, source patch, and
application requirements lock must byte-match their canonical blobs at
`$projectCommit`. Commit those static inputs before final staging; otherwise a
working-tree-only copy is rejected. The stage verifies the distinct raw and
repaired wheel identities and hashes, plus the filename and SHA-256 of every
audit log, against the attestation. It then stages them separately under
`build-evidence/pytetwild/raw-wheel/`,
`build-evidence/pytetwild/repaired-wheel/`, and
`build-evidence/pytetwild/logs/`. Regenerate and verify the complete archive for
each new application commit; historical successful source bundles do not prove
the contents of a new package.

`BUILD_AND_TEST.ps1` verifies Python 3.13.14, runs tests, invokes the pinned spec,
checks runtime resources, and executes the packaged self-test.

## Binary release stage

`BUILD_AND_TEST.ps1` generates `compliance/BINARY_COMPONENT_MAP.json` and
`compliance/SBOM.cdx.json` from the exact one-folder output.
`tooling/stage_software_package.ps1` requires both generated inventories, the
final complete corresponding-source archive and its external manifest, the
archive SHA-256, and the exact ChromaMatter source commit. Choose one source
delivery method: `-BundleCorrespondingSource` embeds the verified archive, or
`-CorrespondingSourceUrl` identifies a real final HTTPS asset with the same
filename. Do not specify both. The stage rejects a bundle unless
`COMPONENT_SOURCES.json` is `release-approved`, has no `known_gaps`, matches the
requested project commit byte-for-byte inside the archive, and passes all binary
inventory checks.

```powershell
$sourceArchive = 'C:\release\ChromaMatter-0.9-complete-corresponding-source.zip'
$sourceManifest = 'C:\release\ChromaMatter-0.9-complete-corresponding-source\COMPONENT_SOURCES.json'
$sourceCommit = (git rev-parse HEAD).Trim()
$sourceSha256 = (Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_software_package.ps1 `
  -BuiltAppRoot C:\ChromaMatterBuild\dist\ChromaMatter `
  -Destination C:\release\ChromaMatter-0.9-win64 `
  -BinaryComponentMapPath C:\ChromaMatterBuild\compliance\BINARY_COMPONENT_MAP.json `
  -SbomPath C:\ChromaMatterBuild\compliance\SBOM.cdx.json `
  -CorrespondingSourceArchivePath $sourceArchive `
  -CorrespondingSourceManifestPath $sourceManifest `
  -CorrespondingSourceArchiveSha256 $sourceSha256 `
  -CorrespondingSourceProjectCommit $sourceCommit `
  -BundleCorrespondingSource
```

For the approved demo, additionally supply `-DemoDataRoot` pointing to a folder
containing exactly the GLB and JPG listed in
`source/fixed_app/public_binary/DemoData/DEMO_DATA_MANIFEST.json`. No other model
or sample 3MF belongs in that folder. The stage verifies both payload hashes
and includes the canonical bilingual README/NOTICE files.

The self-contained ZIP includes the verified source archive under
`corresponding-source/`. Keep it with the executable when redistributing. The
source copy is rehashed and covered by the same software manifest and fresh
ZIP-extraction checks as every other payload. The archive is larger because it
contains third-party sources as well as the application. A local successful
stage is not evidence of site publication, code signing, or physical printing.

For separate network delivery, omit `-BundleCorrespondingSource`, supply the
real `-CorrespondingSourceUrl`, and publish the exact source and binary together
under equivalent access conditions. A local stage does not prove that URL is
uploaded or publicly reachable. Do not invent a future URL to complete staging.
