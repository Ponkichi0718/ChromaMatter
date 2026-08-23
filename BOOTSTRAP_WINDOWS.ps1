param(
    [string]$PythonExe = "",
    [switch]$Build,
    [switch]$SkipInstall,
    [string]$BuildOutputRoot = "",
    [string]$PyTetWildWheel = "",
    [string]$PyTetWildWheelhouse = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvRoot = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$requirementsLock = Join-Path $repoRoot `
    "source\fixed_app\requirements-build.lock"

if (
    -not $SkipInstall -and
    -not $PyTetWildWheel -and
    -not $PyTetWildWheelhouse
) {
    throw (
        "This r32 application lock pins the controlled PyTetWild wheel, " +
        "which is not available from the public Python package index. " +
        "Pass its exact local path with -PyTetWildWheel or the directory " +
        "containing exactly that wheel with -PyTetWildWheelhouse. Use " +
        "-SkipInstall only with an already verified environment."
    )
}

function Resolve-LockedPyTetWildWheel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RequirementsLock,
        [string]$Wheel = "",
        [string]$Wheelhouse = ""
    )

    if ($Wheel -and $Wheelhouse) {
        throw "Pass only one of -PyTetWildWheel or -PyTetWildWheelhouse."
    }
    if (-not $Wheel -and -not $Wheelhouse) {
        return $null
    }
    if (-not (Test-Path -LiteralPath $RequirementsLock -PathType Leaf)) {
        throw "Hashed build lock is missing: $RequirementsLock"
    }

    $resolvedLock = (Resolve-Path -LiteralPath $RequirementsLock).Path
    $lockText = [System.IO.File]::ReadAllText($resolvedLock)
    $declarations = [regex]::Matches(
        $lockText,
        '(?im)^[ \t]*pytetwild=='
    )
    $lockedRequirementPattern = (
        '(?im)^[ \t]*pytetwild==' +
        '(?<version>[^\s\\]+)[ \t]*\\[ \t]*\r?\n' +
        '[ \t]*--hash=sha256:(?<sha256>[0-9a-f]{64})[ \t]*\r?$'
    )
    $lockedRequirements = [regex]::Matches(
        $lockText,
        $lockedRequirementPattern
    )
    if ($declarations.Count -ne 1 -or $lockedRequirements.Count -ne 1) {
        throw (
            "Hashed build lock must contain exactly one PyTetWild " +
            "requirement with exactly one SHA-256 hash."
        )
    }
    $lockedVersion = $lockedRequirements[0].Groups["version"].Value
    $lockedSha256 = (
        $lockedRequirements[0].Groups["sha256"].Value.ToLowerInvariant()
    )

    $resolvedWheel = ""
    if ($Wheel) {
        if (-not (Test-Path -LiteralPath $Wheel -PathType Leaf)) {
            throw "PyTetWild wheel does not exist as a file: $Wheel"
        }
        $resolvedWheel = (Resolve-Path -LiteralPath $Wheel).Path
    }
    else {
        if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
            throw "PyTetWild wheelhouse does not exist as a directory: $Wheelhouse"
        }
        $resolvedWheelhouse = (Resolve-Path -LiteralPath $Wheelhouse).Path
        $candidates = @(
            Get-ChildItem -LiteralPath $resolvedWheelhouse -File -Filter "*.whl" |
                Where-Object { $_.Name -match '(?i)^pytetwild-' }
        )
        if ($candidates.Count -ne 1) {
            throw (
                "PyTetWild wheelhouse must contain exactly one top-level " +
                "pytetwild-*.whl file; found $($candidates.Count)."
            )
        }
        $resolvedWheel = $candidates[0].FullName
    }

    $wheelName = [System.IO.Path]::GetFileName($resolvedWheel)
    $wheelNamePattern = (
        '^(?<distribution>[^-]+)-(?<version>[^-]+)' +
        '(?:-(?<build>[0-9][^-]*))?-' +
        '(?<python>[^-]+)-(?<abi>[^-]+)-(?<platform>[^-]+)\.whl$'
    )
    $wheelNameMatch = [regex]::Match(
        $wheelName,
        $wheelNamePattern,
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    if (-not $wheelNameMatch.Success) {
        throw "Invalid PyTetWild wheel filename: $wheelName"
    }

    $distribution = (
        $wheelNameMatch.Groups["distribution"].Value -replace '[-_.]+', '-'
    ).ToLowerInvariant()
    if ($distribution -ne "pytetwild") {
        throw "Local wheel distribution must be PyTetWild; found $distribution."
    }
    $wheelVersion = $wheelNameMatch.Groups["version"].Value
    if ($wheelVersion -ne $lockedVersion) {
        throw (
            "PyTetWild wheel version $wheelVersion does not match " +
            "locked version $lockedVersion."
        )
    }
    $wheelTag = @(
        $wheelNameMatch.Groups["python"].Value,
        $wheelNameMatch.Groups["abi"].Value,
        $wheelNameMatch.Groups["platform"].Value
    ) -join "-"
    $expectedWheelTag = "cp312-abi3-win_amd64"
    if ($wheelTag.ToLowerInvariant() -ne $expectedWheelTag) {
        throw (
            "PyTetWild wheel tag $wheelTag does not match required tag " +
            "$expectedWheelTag."
        )
    }

    $wheelStream = [System.IO.File]::OpenRead($resolvedWheel)
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            $actualSha256 = (
                [System.BitConverter]::ToString(
                    $sha256.ComputeHash($wheelStream)
                ) -replace '-', ''
            ).ToLowerInvariant()
        }
        finally {
            $sha256.Dispose()
        }
    }
    finally {
        $wheelStream.Dispose()
    }
    if ($actualSha256 -ne $lockedSha256) {
        throw (
            "PyTetWild wheel SHA-256 does not match the hashed build lock. " +
            "Expected $lockedSha256; found $actualSha256."
        )
    }

    return [PSCustomObject]@{
        Path = $resolvedWheel
        Version = $lockedVersion
        Sha256 = $lockedSha256
    }
}

$localPyTetWild = $null
if ($PyTetWildWheel -or $PyTetWildWheelhouse) {
    if ($SkipInstall) {
        throw (
            "-PyTetWildWheel and -PyTetWildWheelhouse cannot be used " +
            "with -SkipInstall."
        )
    }
    $localPyTetWild = Resolve-LockedPyTetWildWheel `
        -RequirementsLock $requirementsLock `
        -Wheel $PyTetWildWheel `
        -Wheelhouse $PyTetWildWheelhouse
}

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
    if ($null -ne $localPyTetWild) {
        $temporaryRequirement = Join-Path `
            ([System.IO.Path]::GetTempPath()) `
            ("chromamatter-pytetwild-{0}.txt" -f [guid]::NewGuid().ToString("N"))
        try {
            $wheelUri = [System.Uri]::new($localPyTetWild.Path).AbsoluteUri
            $requirementLine = (
                "pytetwild @ $wheelUri " +
                "--hash=sha256:$($localPyTetWild.Sha256)"
            )
            $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
            [System.IO.File]::WriteAllText(
                $temporaryRequirement,
                $requirementLine + [Environment]::NewLine,
                $utf8NoBom
            )
            & $venvPython -m pip install `
                --require-hashes `
                --only-binary=:all: `
                --no-index `
                --no-deps `
                --force-reinstall `
                -r $temporaryRequirement
            if ($LASTEXITCODE -ne 0) {
                throw "Hash-locked local PyTetWild wheel installation failed."
            }
        }
        finally {
            if (Test-Path -LiteralPath $temporaryRequirement -PathType Leaf) {
                Remove-Item -LiteralPath $temporaryRequirement -Force
            }
        }
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
