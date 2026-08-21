# Exact Windows build environment

The corresponding-source archive is authoritative for a binary release. Use
its pinned requirements, scripts, component map, and sources together; do not
substitute a newer checkout as the source for an older binary.

## Pinned baseline

- Windows x64
- Python 3.13
- PyInstaller 6.20.0, one-folder mode, UPX disabled
- versions in `source/fixed_app/requirements-build.txt`

## Build and test

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1
powershell.exe -ExecutionPolicy Bypass -File .\BUILD_AND_TEST.ps1 `
  -RuntimeRoot .\.venv `
  -Build `
  -BuildOutputRoot C:\ChromaMatterBuild
```

`BUILD_AND_TEST.ps1` verifies Python 3.13, runs tests, invokes the pinned spec,
checks runtime resources, and executes the packaged self-test.

## Binary release stage

`BUILD_AND_TEST.ps1` generates `compliance/BINARY_COMPONENT_MAP.json` and
`compliance/SBOM.cdx.json` from the exact one-folder output.
`tooling/stage_software_package.ps1` requires both generated inventories and
an HTTPS URL for the exact source archive. Failed native-file coverage,
placeholders, missing inventories, and executable hash mismatches stop staging.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_software_package.ps1 `
  -BuiltAppRoot C:\ChromaMatterBuild\dist\ChromaMatter `
  -BinaryComponentMapPath C:\release\BINARY_COMPONENT_MAP.json `
  -SbomPath C:\release\SBOM.cdx.json `
  -CorrespondingSourceUrl https://github.com/OWNER/REPO/releases/download/TAG/SOURCE.zip
```

Publish the binary and exact source archive together. A successful local stage
does not prove that the source URL has been uploaded or is publicly reachable.
