param(
    [string]$PythonExe = "",
    [switch]$Build,
    [switch]$SkipInstall,
    [string]$BuildOutputRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvRoot = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$requirementsLock = Join-Path $repoRoot `
    "source\fixed_app\requirements-build.lock"

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonExe) {
        $resolvedPython = (Resolve-Path -LiteralPath $PythonExe).Path
        & $resolvedPython -m venv $venvRoot
    } elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3.13 -m venv $venvRoot
    } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -m venv $venvRoot
    } else {
        throw "Python 3.13.14 was not found. Install it or pass -PythonExe."
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the local .venv. Python 3.13.14 is required."
    }
}

$version = & $venvPython -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0 -or $version -ne "3.13.14") {
    throw "The local environment must use Python 3.13.14; found $version"
}

if (-not $SkipInstall) {
    if (-not (Test-Path -LiteralPath $requirementsLock -PathType Leaf)) {
        throw "Hashed build lock is missing: $requirementsLock"
    }
    & $venvPython -m pip install `
        --require-hashes `
        --only-binary=:all: `
        -r $requirementsLock
    if ($LASTEXITCODE -ne 0) {
        throw "Hash-locked binary dependency installation failed."
    }
}

$buildScript = Join-Path $repoRoot "BUILD_AND_TEST.ps1"
if ($Build) {
    & $buildScript `
        -RuntimeRoot $venvRoot `
        -Build `
        -BuildOutputRoot $BuildOutputRoot
} else {
    & $buildScript -RuntimeRoot $venvRoot
}
if ($LASTEXITCODE -ne 0) {
    throw "Build/test workflow failed."
}
