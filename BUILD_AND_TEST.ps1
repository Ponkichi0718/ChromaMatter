param(
    [string]$RuntimeRoot = "",
    [switch]$Build,
    [string]$BuildOutputRoot = ""
)

$ErrorActionPreference = "Stop"

$handoffRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRoot = Join-Path $handoffRoot "source"
$fixedApp = Join-Path $sourceRoot "fixed_app"
$filamentResourceRoot = Join-Path $fixedApp "resources\filament_db"
$filamentResourceFiles = @(
    "filament_color_database_2026-08.sqlite",
    "filament_color_database_README.md",
    "ATTRIBUTION.md",
    "LICENSE_OPEN_FILAMENT_DATABASE.txt",
    "LICENSE_CC_BY_4.0.txt"
)

function Invoke-PackagedUiSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)]
        [ValidateSet("ja", "en")]
        [string]$Language
    )

    # The GUI persists settings when its smoke-test window closes.  Give every
    # language run a fresh profile so a release build never reads or rewrites
    # the operator's real TripoSpectrumMapper preferences.
    $temporaryBase = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()
    ).TrimEnd([char[]]"\/")
    $temporaryPrefix = $temporaryBase + [System.IO.Path]::DirectorySeparatorChar
    $smokeLeafPrefix = "ChromaMatter-packaged-ui-smoke-$PID-$Language-"
    $smokeRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $temporaryBase (
            $smokeLeafPrefix + [Guid]::NewGuid().ToString("N")
        ))
    )
    if (
        -not $smokeRoot.StartsWith(
            $temporaryPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (Split-Path -Leaf $smokeRoot).StartsWith(
            $smokeLeafPrefix,
            [System.StringComparison]::Ordinal
        )
    ) {
        throw "Unsafe packaged UI-smoke temporary path: $smokeRoot"
    }

    $smokeAppData = Join-Path $smokeRoot "AppData\Roaming"
    $smokeLocalAppData = Join-Path $smokeRoot "AppData\Local"
    $previousAppData = [Environment]::GetEnvironmentVariable(
        "APPDATA",
        [EnvironmentVariableTarget]::Process
    )
    $previousLocalAppData = [Environment]::GetEnvironmentVariable(
        "LOCALAPPDATA",
        [EnvironmentVariableTarget]::Process
    )

    try {
        New-Item -ItemType Directory -Path $smokeAppData -Force | Out-Null
        New-Item -ItemType Directory -Path $smokeLocalAppData -Force | Out-Null
        [Environment]::SetEnvironmentVariable(
            "APPDATA",
            $smokeAppData,
            [EnvironmentVariableTarget]::Process
        )
        [Environment]::SetEnvironmentVariable(
            "LOCALAPPDATA",
            $smokeLocalAppData,
            [EnvironmentVariableTarget]::Process
        )

        $uiSmoke = Start-Process `
            -FilePath $Executable `
            -ArgumentList "--ui-smoke", "--ui-smoke-language", $Language `
            -Wait `
            -PassThru `
            -WindowStyle Hidden
        if ($uiSmoke.ExitCode -ne 0) {
            throw "Packaged $Language UI smoke test failed."
        }
        Write-Host "Packaged $Language UI smoke test passed."
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            "APPDATA",
            $previousAppData,
            [EnvironmentVariableTarget]::Process
        )
        [Environment]::SetEnvironmentVariable(
            "LOCALAPPDATA",
            $previousLocalAppData,
            [EnvironmentVariableTarget]::Process
        )

        if (Test-Path -LiteralPath $smokeRoot) {
            $cleanupPath = [System.IO.Path]::GetFullPath($smokeRoot)
            if (
                -not $cleanupPath.StartsWith(
                    $temporaryPrefix,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -or
                -not (Split-Path -Leaf $cleanupPath).StartsWith(
                    $smokeLeafPrefix,
                    [System.StringComparison]::Ordinal
                )
            ) {
                throw "Refusing unsafe packaged UI-smoke cleanup: $cleanupPath"
            }
            Remove-Item -LiteralPath $cleanupPath -Recurse -Force
        }
    }
}

if (-not $RuntimeRoot) {
    $localVenv = Join-Path $handoffRoot ".venv"
    if (Test-Path -LiteralPath $localVenv) {
        $RuntimeRoot = $localVenv
    }
}

if (-not $RuntimeRoot) {
    throw (
        "Python 3.13 environment not found. Run BOOTSTRAP_WINDOWS.ps1 first, " +
        "or pass -RuntimeRoot C:\path\to\venv."
    )
}

$RuntimeRoot = (Resolve-Path -LiteralPath $RuntimeRoot).Path
$python = Join-Path $RuntimeRoot "Scripts\python.exe"
$pyinstaller = Join-Path $RuntimeRoot "Scripts\pyinstaller.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "python.exe not found: $python"
}

foreach ($filename in $filamentResourceFiles) {
    $resource = Join-Path $filamentResourceRoot $filename
    if (-not (Test-Path -LiteralPath $resource -PathType Leaf)) {
        throw "Required filament database resource is missing: $resource"
    }
}

$pythonVersion = & $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0 -or -not $pythonVersion.StartsWith("3.13.")) {
    throw "The tested build environment requires Python 3.13; found $pythonVersion"
}

$env:PYTHONPATH = "$handoffRoot;$fixedApp"
& $python -m unittest discover -s $fixedApp -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) {
    throw "Unit tests failed."
}

if (-not $Build) {
    Write-Host "Regression suite completed. Add -Build to create a new one-folder package."
    exit 0
}

if (-not (Test-Path -LiteralPath $pyinstaller)) {
    throw "pyinstaller.exe not found: $pyinstaller"
}

if ($BuildOutputRoot) {
    if ([System.IO.Path]::IsPathRooted($BuildOutputRoot)) {
        $buildOutput = [System.IO.Path]::GetFullPath($BuildOutputRoot)
    } else {
        $buildOutput = [System.IO.Path]::GetFullPath(
            (Join-Path $handoffRoot $BuildOutputRoot)
        )
    }
} else {
    $buildOutput = Join-Path $handoffRoot "build_output"
}
$distPath = Join-Path $buildOutput "dist"
$workPath = Join-Path $buildOutput "work"
$spec = Join-Path $fixedApp "TripoSpectrumMapper_fixed.spec"

& $pyinstaller --noconfirm --clean --distpath $distPath --workpath $workPath $spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

# PyInstaller 6 one-folder builds expose bundled datas below sys._MEIPASS,
# which maps to the `_internal` directory beside the executable.  Verify the
# exact runtime-relative resource set before running packaged smoke tests.
$bundledFilamentRoot = Join-Path $distPath `
    "ChromaMatter\_internal\resources\filament_db"
foreach ($filename in $filamentResourceFiles) {
    $resource = Join-Path $bundledFilamentRoot $filename
    if (-not (Test-Path -LiteralPath $resource -PathType Leaf)) {
        throw "Packaged filament database resource is missing: $resource"
    }
}

$exe = Join-Path $distPath "ChromaMatter\ChromaMatter.exe"
$selfTest = Start-Process -FilePath $exe -ArgumentList "--self-test" -Wait -PassThru -WindowStyle Hidden
if ($selfTest.ExitCode -ne 0) {
    throw "Packaged self-test failed."
}
foreach ($language in @("ja", "en")) {
    Invoke-PackagedUiSmoke -Executable $exe -Language $language
}

Write-Host "Build and smoke tests completed: $exe"
