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
$requirements = Join-Path $repoRoot "source\fixed_app\requirements-build.txt"

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonExe) {
        $resolvedPython = (Resolve-Path -LiteralPath $PythonExe).Path
        & $resolvedPython -m venv $venvRoot
    } elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3.13 -m venv $venvRoot
    } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -m venv $venvRoot
    } else {
        throw "Python 3.13 was not found. Install it or pass -PythonExe."
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the local .venv. Python 3.13 is required."
    }
}

$version = & $venvPython -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0 -or -not $version.StartsWith("3.13.")) {
    throw "The local environment must use Python 3.13; found $version"
}

if (-not $SkipInstall) {
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip upgrade failed."
    }
    & $venvPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
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
