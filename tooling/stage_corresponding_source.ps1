[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [Parameter(Mandatory = $true)]
    [string]$Cache,

    [Parameter(Mandatory = $true)]
    [string]$ProjectRepository,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ProjectCommit,

    [string]$Archive = "",
    [string]$ComponentManifest = "",
    [string]$ExternalArchiveLock = "",
    [string]$PyTetWildRebuildLock = "",
    [string]$PyTetWildWheel = "",
    [string]$PyTetWildBuildRecipe = "",
    [string]$PyTetWildBuildRequirements = "",
    [string]$PyTetWildBuildAttestation = "",
    [string]$ApplicationRequirementsLock = "",
    [string]$PythonExe = "",
    [switch]$Offline,
    [switch]$ValidateManifestOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$helper = Join-Path $PSScriptRoot "stage_corresponding_source.py"
if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) {
    throw "Corresponding-source Python helper is missing: $helper"
}
if (-not $ComponentManifest) {
    $ComponentManifest = Join-Path `
        $PSScriptRoot `
        "corresponding_source_components.json"
}
if (-not (Test-Path -LiteralPath $ComponentManifest -PathType Leaf)) {
    throw "Component manifest is missing: $ComponentManifest"
}

$pythonCommand = ""
$pythonArguments = @()
if ($PythonExe) {
    $pythonCommand = $PythonExe
}
elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    $pythonCommand = "python.exe"
}
elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $pythonCommand = "py.exe"
    $pythonArguments += "-3"
}
else {
    throw "Python 3 was not found. Pass -PythonExe with an explicit interpreter."
}

$pythonArguments += @(
    $helper,
    "--manifest",
    $ComponentManifest
)
if ($ValidateManifestOnly) {
    $pythonArguments += "--validate-manifest-only"
}
else {
    $pythonArguments += @(
        "--destination",
        $Destination,
        "--cache",
        $Cache,
        "--project-repository",
        $ProjectRepository,
        "--project-commit",
        $ProjectCommit
    )
    if ($Archive) {
        $pythonArguments += @("--archive", $Archive)
    }
    if ($ExternalArchiveLock) {
        $pythonArguments += @(
            "--external-archive-lock",
            $ExternalArchiveLock
        )
    }
    $rebuildArguments = @(
        @($PyTetWildRebuildLock, "--pytetwild-rebuild-lock"),
        @($PyTetWildWheel, "--pytetwild-wheel"),
        @($PyTetWildBuildRecipe, "--pytetwild-build-recipe"),
        @($PyTetWildBuildRequirements, "--pytetwild-build-requirements"),
        @($PyTetWildBuildAttestation, "--pytetwild-build-attestation"),
        @($ApplicationRequirementsLock, "--application-requirements-lock")
    )
    foreach ($binding in $rebuildArguments) {
        if ($binding[0]) {
            $pythonArguments += @($binding[1], $binding[0])
        }
    }
    if ($Offline) {
        $pythonArguments += "--offline"
    }
}

& $pythonCommand @pythonArguments
if ($LASTEXITCODE -ne 0) {
    throw "Corresponding-source staging failed with exit code $LASTEXITCODE."
}
