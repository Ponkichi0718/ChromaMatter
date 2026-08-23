[CmdletBinding()]
param(
    [string]$ToolchainRoot = 'C:\ChromaMatterToolchain',
    [string]$OutputRoot = 'C:\ChromaMatterToolchain\pytetwild-controlled-build',
    [string]$RequirementsLock = '',
    [string]$VsInstall = 'C:\ChromaMatterToolchain\VS2022BuildTools',
    [string]$WindowsSdkRoot = '',
    [string]$PyTetWildSourcePatch = '',
    [switch]$OsNetworkIsolationConfirmed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $RequirementsLock) {
    $RequirementsLock = Join-Path $PSScriptRoot 'requirements-pytetwild-build.lock'
}
if (-not $PyTetWildSourcePatch) {
    $PyTetWildSourcePatch = Join-Path `
        $PSScriptRoot 'patches\pytetwild-0.3.0-optional-pyvista.patch'
}
if (-not $OsNetworkIsolationConfirmed.IsPresent) {
    throw (
        'Refusing to start without -OsNetworkIsolationConfirmed. Configure an OS- or ' +
        'hypervisor-level outbound deny-all policy (or physically disconnect the builder), ' +
        'then rerun with the switch to record the operator confirmation.'
    )
}

$Expected = [ordered]@{
    PythonVersion = '3.12.10'
    PythonInstallerSha256 = '67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb'
    PortableGitVersion = '2.55.0.windows.5'
    PortableGitSha256 = '5aa8a20f6e9abb2c755f0e73c91c687701a46b309ad84a0ca6509380fa4ae290'
    VsBootstrapperSha256 = '236367b68ba9a51708263ab10a1c85546cc4a8eca78b365168811d19c4fb2f29'
    VsCatalogSha256 = '3891c3018a07338b3880cbb28088bb22ef7762eb9206523655b2e3972b9d527e'
    VsChannelManifestSha256 = '4c81e902fb7fe2acea779b828e6dc548fe0bbb693df50eda0224263c16686bdd'
    VsLayoutSha256 = '9707247b5e1c5ffdbd2ec97889db8e16ad97361840427a846e21f697c28ed494'
    VsInstallerOpcSha256 = 'e2c0a268ec9b678169ed5ff9c0162ea135d8868c27e7ac67a754b09d16841b71'
    VsLayoutFileCount = 714
    VsLayoutTotalBytes = [long]2651377645
    VsLayoutTreeSha256 = '2b6a89bb69aa7de013fc055828258a3a91c7c333f0c6be831a750990922fed3a'
    VsInstallationVersion = '17.14.37614.0'
    MsvcVersion = '14.44.35207'
    CompilerFileVersion = '19.44.35228.0'
    CompilerProductVersion = '14.44.35228.0'
    LinkerFileVersion = '14.44.35228.0'
    LinkerProductVersion = '14.44.35228.0'
    WindowsSdkVersion = '10.0.26100.0'
    WindowsSdkServicingVersion = '10.0.26100.7705'
    CMakeVersion = '3.29.6'
    NinjaVersion = '1.13.0'
    NinjaCliVersion = '1.13.0.git.kitware.jobserver-pipe-1'
    NumpyVersion = '2.5.1'
    NumpyWheelSha256 = 'f7d60026c0bdb1380e83bfa7a0419c4577ee4b9a08880afcb6dadeb74c649fa2'
    PipVersion = '25.0.1'
    NanobindVersion = '2.12.0'
    CibuildwheelVersion = '3.3.1'
    BuildVersion = '1.5.0'
    ScikitBuildCoreVersion = '0.12.2'
    DelvewheelVersion = '1.12.1'
    Abi3AuditVersion = '0.0.26'
    RequirementsLockSha256 = '486d8230dbdf04c26c375f7df159ae2fc2ca02747f1f710a462d6b4bc1104c9a'
    PyTetWildSourcePatchSha256 = 'a051af2c29279a11110f7b53779fcfc655b6fe19533550717383b7d8c84c9ad6'
    PatchedAccessorSha256 = 'c1bfeb0417cd3109d0ef3ecde6e69e04573571f5050003d330a04c25a5d1030c'
    PyTetWildCommit = 'eea46df87ef58e861956b7a710f42ab58eaa02a0'
    FTetWildCommit = 'd7d99bb4387a07895b9adce058dc7305f6b6e5ab'
    NanobindCommit = '2a61ad2494d09fecb2e13322c1383342c299900d'
    FmtCommit = '40626af88bd7df9a5fb80be7b25ac85b122d6c21'
    SpdlogCommit = '6fa36017cfd5731d617e1a934f0e5ea9c4445b13'
    LibiglCommit = '40e7900ccbd767f1f360e0eb10f0f1a6432e0993'
    PredicatesCommit = 'decb7bc1260e689cbe008109e3cc5d3a5a433aea'
    GeogramCommit = 'fc3eb9bf44d2ee29686592e3ef5f5f4daeda27f8'
    GeogramAmgclCommit = 'ab57038d68ee372ed5df280631051b91f17ed2d1'
    GeogramLibMeshbCommit = '952a157c9d516b28cc6c69cd1550c3e48d4792f9'
    GeogramRplyCommit = '4296cc91b5c8c26d4e7d7aac0cee2b194ffc5800'
    OneTbbCommit = '06ce6212da6710f4bb2d20a1904b018aa44069bf'
    JsonCommit = '0901d33bf6e7dfe6f70fd9d142c8f5c6695c6c5b'
    EigenArchiveSha256 = '8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72'
    MpirArchiveSha256 = 'c7243b2c3f8e849a9367eab8d77babcd8dd5b828d6b5068441297edc86843b69'
}

function Get-Sha256([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Assert-Sha256([string]$Path, [string]$Digest) {
    $actual = Get-Sha256 $Path
    if ($actual -ne $Digest) {
        throw "SHA-256 mismatch for $Path`: expected $Digest, got $actual"
    }
}

function Get-DirectoryTreeEvidence([string]$Path) {
    $root = [System.IO.Path]::GetFullPath($Path).TrimEnd([char]'\', [char]'/')
    $records = New-Object 'System.Collections.Generic.List[string]'
    $caseFoldedPaths = New-Object 'System.Collections.Generic.HashSet[string]' `
        ([System.StringComparer]::OrdinalIgnoreCase)
    [long]$totalBytes = 0
    $entries = @(Get-ChildItem -LiteralPath $root -Force -Recurse)
    foreach ($entry in $entries) {
        if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse point is forbidden in fixed directory tree: $($entry.FullName)"
        }
    }
    foreach ($file in @($entries | Where-Object { -not $_.PSIsContainer })) {
        $relative = $file.FullName.Substring($root.Length + 1) -replace '\\', '/'
        if ($relative.IndexOfAny([char[]]@("`0", "`t", "`r", "`n")) -ge 0) {
            throw "Unsafe path in fixed directory tree: $relative"
        }
        if (-not $caseFoldedPaths.Add($relative)) {
            throw "Case-insensitive duplicate in fixed directory tree: $relative"
        }
        $records.Add("$relative`t$($file.Length)`t$(Get-Sha256 $file.FullName)")
        $totalBytes += $file.Length
    }
    $records.Sort([System.StringComparer]::Ordinal)
    $manifest = [string]::Join("`n", $records) + "`n"
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digestBytes = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($manifest))
    } finally {
        $sha256.Dispose()
    }
    return [pscustomobject]@{
        FileCount = $records.Count
        TotalBytes = $totalBytes
        Sha256 = ([System.BitConverter]::ToString($digestBytes) -replace '-', '').ToLowerInvariant()
    }
}

function Invoke-Checked([string]$FilePath, [string[]]$Arguments) {
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Invoke-Utf8NativeCapture([string]$FilePath, [string[]]$Arguments) {
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw "Command executable is missing: $FilePath"
    }
    $savedConsoleOutputEncoding = [Console]::OutputEncoding
    try {
        # Windows PowerShell 5.1 decodes native stdout using this property.
        # vswhere -utf8 always emits UTF-8, independent of the active console
        # code page, so bind the decoder for this invocation and then restore it.
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false, $true)
        $output = @(& $FilePath @Arguments)
        $exitCode = $LASTEXITCODE
    } finally {
        [Console]::OutputEncoding = $savedConsoleOutputEncoding
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Invoke-Logged(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$LogPath
) {
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw "Command executable is missing: $FilePath"
    }
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 turns native stderr records into terminating
        # NativeCommandError exceptions when the caller uses Stop.  Capture the
        # stream and decide success only from the native process exit code.
        $ErrorActionPreference = 'Continue'
        $output = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    foreach ($line in $output) {
        Write-Host ([string]$line)
    }
    $outputText = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    $logText = @(
        "command=$FilePath $($Arguments -join ' ')",
        "exit_code=$exitCode",
        '--- output ---',
        $outputText
    ) -join [Environment]::NewLine
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText(
        $LogPath,
        $logText + [Environment]::NewLine,
        $encoding
    )
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $outputText
    }
}

function Invoke-CheckedLogged(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$LogPath
) {
    $result = Invoke-Logged $FilePath $Arguments $LogPath
    if ($result.ExitCode -ne 0) {
        throw "Command failed ($($result.ExitCode)): $FilePath $($Arguments -join ' ')"
    }
}

function Get-JsonProperty([object]$Object, [string]$Name) {
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        throw "JSON property is missing: $Name"
    }
    return [string]$property.Value
}

function Assert-GitCommit([string]$Git, [string]$Repository, [string]$Commit) {
    if (-not (Test-Path -LiteralPath $Repository -PathType Container)) {
        throw "Source repository is missing: $Repository"
    }
    $actual = (& $Git -C $Repository rev-parse 'HEAD^{commit}').Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $Commit) {
        throw "Commit mismatch for $Repository`: expected $Commit, got $actual"
    }
}

function ConvertTo-CMakePath([string]$Path) {
    return ([System.IO.Path]::GetFullPath($Path) -replace '\\', '/')
}

function Resolve-WindowsSdkRoot(
    [string]$RequestedRoot,
    [string]$WindowsSdkVersion
) {
    $candidateRoots = New-Object 'System.Collections.Generic.List[string]'
    if (-not [string]::IsNullOrWhiteSpace($RequestedRoot)) {
        $candidateRoots.Add($RequestedRoot)
    } else {
        $registryLocations = @(
            [pscustomobject]@{
                View = [Microsoft.Win32.RegistryView]::Registry64
                Subkey = 'SOFTWARE\Microsoft\Windows Kits\Installed Roots'
            },
            [pscustomobject]@{
                View = [Microsoft.Win32.RegistryView]::Registry64
                Subkey = 'SOFTWARE\WOW6432Node\Microsoft\Windows Kits\Installed Roots'
            },
            [pscustomobject]@{
                View = [Microsoft.Win32.RegistryView]::Registry32
                Subkey = 'SOFTWARE\Microsoft\Windows Kits\Installed Roots'
            }
        )
        foreach ($location in $registryLocations) {
            $registryBase = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
                [Microsoft.Win32.RegistryHive]::LocalMachine,
                $location.View
            )
            try {
                $subkey = $registryBase.OpenSubKey($location.Subkey)
                if ($null -eq $subkey) {
                    continue
                }
                try {
                    $candidate = [string]$subkey.GetValue(
                        'KitsRoot10',
                        $null,
                        [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
                    )
                } finally {
                    $subkey.Dispose()
                }
                if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                    $candidateRoots.Add($candidate)
                }
            } finally {
                $registryBase.Dispose()
            }
        }
    }

    $seenRoots = New-Object 'System.Collections.Generic.HashSet[string]' `
        ([System.StringComparer]::OrdinalIgnoreCase)
    $validRoots = New-Object 'System.Collections.Generic.List[string]'
    foreach ($candidateRoot in $candidateRoots) {
        $fullRoot = [System.IO.Path]::GetFullPath($candidateRoot).TrimEnd(
            [char]'\', [char]'/'
        )
        if (-not $seenRoots.Add($fullRoot)) {
            continue
        }
        $candidateSignTool = Join-Path `
            $fullRoot "bin\$WindowsSdkVersion\x64\signtool.exe"
        $candidateKernelLibrary = Join-Path `
            $fullRoot "Lib\$WindowsSdkVersion\um\x64\kernel32.lib"
        if (
            (Test-Path -LiteralPath $candidateSignTool -PathType Leaf) -and
            (Test-Path -LiteralPath $candidateKernelLibrary -PathType Leaf)
        ) {
            $validRoots.Add($fullRoot)
        }
    }
    if ($validRoots.Count -ne 1) {
        $sourceLabel = if ([string]::IsNullOrWhiteSpace($RequestedRoot)) {
            '64-bit native, 64-bit WOW6432Node, and 32-bit registry candidates'
        } else {
            'the explicit -WindowsSdkRoot candidate'
        }
        throw (
            "Expected exactly one Windows SDK root from $sourceLabel containing " +
            "both signtool.exe and kernel32.lib for $WindowsSdkVersion; found " +
            "$($validRoots.Count)"
        )
    }
    return $validRoots[0]
}

function Import-VsEnvironment(
    [string]$DevCmd,
    [string]$VCToolsFamilyVersion,
    [string]$WindowsSdkVersion
) {
    if (-not (Test-Path -LiteralPath $DevCmd -PathType Leaf)) {
        throw "VsDevCmd.bat is missing: $DevCmd"
    }
    $command = (
        "call `"$DevCmd`" -no_logo -arch=x64 -host_arch=x64 " +
        "-vcvars_ver=$VCToolsFamilyVersion -winsdk=$WindowsSdkVersion >nul && set"
    )
    $lines = & $env:ComSpec /d /s /c $command
    if ($LASTEXITCODE -ne 0) {
        throw "VsDevCmd.bat failed: $LASTEXITCODE"
    }
    foreach ($line in $lines) {
        $separator = $line.IndexOf('=')
        if ($separator -gt 0) {
            $name = $line.Substring(0, $separator)
            $value = $line.Substring($separator + 1)
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}

function Assert-Directory([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label is missing: $Path"
    }
}

function Assert-NetworkIsolation {
    $targets = @(
        @('github.com', 443),
        @('pypi.org', 443),
        @('files.pythonhosted.org', 443),
        @('conda.anaconda.org', 443)
    )
    foreach ($target in $targets) {
        $client = New-Object System.Net.Sockets.TcpClient
        $connected = $false
        $asyncResult = $null
        try {
            $asyncResult = $client.BeginConnect($target[0], [int]$target[1], $null, $null)
            if ($asyncResult.AsyncWaitHandle.WaitOne(1500, $false)) {
                try {
                    $client.EndConnect($asyncResult)
                    $connected = $client.Connected
                } catch [System.Net.Sockets.SocketException] {
                    $connected = $false
                }
            }
        } catch [System.Net.Sockets.SocketException] {
            $connected = $false
        } finally {
            if ($null -ne $asyncResult) {
                $asyncResult.AsyncWaitHandle.Close()
            }
            $client.Close()
        }
        if ($connected) {
            throw (
                "Network isolation check failed: $($target[0]):$($target[1]) is reachable. " +
                'Disconnect the controlled builder from the network and rerun.'
            )
        }
    }
}

function Export-GitTree(
    [string]$Git,
    [string]$Repository,
    [string]$Commit,
    [string]$Archive,
    [string]$Destination
) {
    if (Test-Path -LiteralPath $Archive) {
        throw "Refusing to overwrite source archive: $Archive"
    }
    if (Test-Path -LiteralPath $Destination) {
        throw "Refusing to overwrite exported source: $Destination"
    }
    Invoke-Checked $Git @(
        '-C', $Repository, 'archive', '--format=zip', "--output=$Archive", $Commit
    )
    New-Item -ItemType Directory -Path $Destination | Out-Null
    Expand-Archive -LiteralPath $Archive -DestinationPath $Destination
}

function Expand-SafeTarArchive(
    [string]$Python,
    [string]$Archive,
    [string]$Destination
) {
    if (Test-Path -LiteralPath $Destination) {
        throw "Refusing to overwrite extracted archive: $Destination"
    }
    $extractScript = @'
import pathlib
import sys
import tarfile

archive = pathlib.Path(sys.argv[1]).resolve()
destination = pathlib.Path(sys.argv[2]).resolve()
destination.mkdir(parents=True, exist_ok=False)
with tarfile.open(archive, mode="r:*") as source:
    members = source.getmembers()
    for member in members:
        normalized = member.name.replace("\\", "/")
        path = pathlib.PurePosixPath(normalized)
        if (
            not normalized
            or normalized.startswith("/")
            or path.is_absolute()
            or ".." in path.parts
            or member.issym()
            or member.islnk()
            or member.isdev()
        ):
            raise SystemExit(f"Unsafe tar member: {member.name!r}")
    source.extractall(destination, members=members, filter="data")
'@
    Invoke-Checked $Python @('-c', $extractScript, $Archive, $Destination)
}

$Downloads = Join-Path $ToolchainRoot 'downloads'
$Sources = Join-Path $ToolchainRoot 'sources'
$Wheelhouse = Join-Path $ToolchainRoot 'wheelhouse-pytetwild'
$Python = Join-Path $ToolchainRoot 'Python312\python.exe'
$Git = Join-Path $ToolchainRoot 'PortableGit-2.55.0.5\bin\git.exe'
$VsLayout = Join-Path $ToolchainRoot 'vsbt-layout-17.14.39'
$MpirArchive = Join-Path $Downloads 'mpir-3.0.0-he025d50_1002.tar.bz2'
$EigenArchive = Join-Path $Downloads 'eigen-3.4.0.tar.gz'

Assert-Directory $Downloads 'Download directory'
Assert-Directory $Sources 'Source directory'
Assert-Directory $Wheelhouse 'Offline Python wheelhouse'
Assert-Directory $VsLayout 'Visual Studio offline layout'

Assert-Sha256 $RequirementsLock $Expected.RequirementsLockSha256
Assert-Sha256 $PyTetWildSourcePatch $Expected.PyTetWildSourcePatchSha256
$recipeSha256AtStart = Get-Sha256 $PSCommandPath
$requirementsLockSha256AtStart = Get-Sha256 $RequirementsLock
$sourcePatchSha256AtStart = Get-Sha256 $PyTetWildSourcePatch
Assert-Sha256 (Join-Path $Downloads 'python-3.12.10-amd64.exe') $Expected.PythonInstallerSha256
Assert-Sha256 (Join-Path $Downloads 'PortableGit-2.55.0.5-64-bit.7z.exe') $Expected.PortableGitSha256
Assert-Sha256 (Join-Path $Downloads 'vs_BuildTools-17.14.39.exe') $Expected.VsBootstrapperSha256
Assert-Sha256 $MpirArchive $Expected.MpirArchiveSha256
Assert-Sha256 $EigenArchive $Expected.EigenArchiveSha256
Assert-Sha256 (Join-Path $VsLayout 'Catalog.json') $Expected.VsCatalogSha256
Assert-Sha256 (Join-Path $VsLayout 'ChannelManifest.json') $Expected.VsChannelManifestSha256
Assert-Sha256 (Join-Path $VsLayout 'Layout.json') $Expected.VsLayoutSha256
Assert-Sha256 (Join-Path $VsLayout 'Response.json') $Expected.VsLayoutSha256
Assert-Sha256 (Join-Path $VsLayout 'vs_installer.opc') $Expected.VsInstallerOpcSha256
$vsLayoutEvidence = Get-DirectoryTreeEvidence $VsLayout
if (
    $vsLayoutEvidence.FileCount -ne $Expected.VsLayoutFileCount -or
    $vsLayoutEvidence.TotalBytes -ne $Expected.VsLayoutTotalBytes -or
    $vsLayoutEvidence.Sha256 -ne $Expected.VsLayoutTreeSha256
) {
    throw (
        'Visual Studio offline layout tree mismatch: expected ' +
        "$($Expected.VsLayoutFileCount) files / $($Expected.VsLayoutTotalBytes) bytes / " +
        "$($Expected.VsLayoutTreeSha256), got $($vsLayoutEvidence.FileCount) files / " +
        "$($vsLayoutEvidence.TotalBytes) bytes / $($vsLayoutEvidence.Sha256)"
    )
}
$vsLayoutBootstrapper = Join-Path $VsLayout 'vs_BuildTools-17.14.39.exe'
Assert-Sha256 $vsLayoutBootstrapper $Expected.VsBootstrapperSha256
$vsLayoutVerification = Start-Process -FilePath $vsLayoutBootstrapper -ArgumentList @(
    '--layout', ('"' + $VsLayout + '"'), '--verify', '--passive', '--wait'
) -Wait -PassThru
if ($vsLayoutVerification.ExitCode -ne 0) {
    throw "Microsoft Visual Studio layout verification failed: $($vsLayoutVerification.ExitCode)"
}
$vsLayoutEvidenceAfterVerification = Get-DirectoryTreeEvidence $VsLayout
if ($vsLayoutEvidenceAfterVerification.Sha256 -ne $Expected.VsLayoutTreeSha256) {
    throw 'Visual Studio layout changed during Microsoft verification'
}

$pythonVersion = (& $Python -c 'import platform; print(platform.python_version())').Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne $Expected.PythonVersion) {
    throw "Python mismatch: expected $($Expected.PythonVersion), got $pythonVersion"
}
$gitVersion = (& $Git --version).Trim()
if ($LASTEXITCODE -ne 0 -or $gitVersion -ne "git version $($Expected.PortableGitVersion)") {
    throw "PortableGit mismatch: $gitVersion"
}

$PyTetWild = Join-Path $Sources 'pytetwild-eea46df'
$FTetWild = Join-Path $PyTetWild 'src\fTetWild'
$NanobindSource = Join-Path $Sources 'nanobind-2.12.0'
$FmtSource = Join-Path $Sources 'fmt-11.2.0'
$SpdlogSource = Join-Path $Sources 'spdlog-1.15.3'
$LibiglSource = Join-Path $Sources 'libigl-2.6.0'
$PredicatesSource = Join-Path $Sources 'libigl-predicates'
$GeogramSource = Join-Path $Sources 'geogram-1.9.6'
$TbbSource = Join-Path $Sources 'oneTBB-2022.2.0'
$JsonSource = Join-Path $Sources 'jdumas-json-0901d33'

Assert-GitCommit $Git $PyTetWild $Expected.PyTetWildCommit
Assert-GitCommit $Git $FTetWild $Expected.FTetWildCommit
Assert-GitCommit $Git $NanobindSource $Expected.NanobindCommit
Assert-GitCommit $Git $FmtSource $Expected.FmtCommit
Assert-GitCommit $Git $SpdlogSource $Expected.SpdlogCommit
Assert-GitCommit $Git $LibiglSource $Expected.LibiglCommit
Assert-GitCommit $Git $PredicatesSource $Expected.PredicatesCommit
Assert-GitCommit $Git $GeogramSource $Expected.GeogramCommit
Assert-GitCommit $Git (Join-Path $GeogramSource 'src\lib\geogram\third_party\amgcl') $Expected.GeogramAmgclCommit
Assert-GitCommit $Git (Join-Path $GeogramSource 'src\lib\geogram\third_party\libMeshb') $Expected.GeogramLibMeshbCommit
Assert-GitCommit $Git (Join-Path $GeogramSource 'src\lib\geogram\third_party\rply') $Expected.GeogramRplyCommit
Assert-GitCommit $Git $TbbSource $Expected.OneTbbCommit
Assert-GitCommit $Git $JsonSource $Expected.JsonCommit

$VsVersionFile = Join-Path $VsInstall 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt'
if (-not (Test-Path -LiteralPath $VsVersionFile -PathType Leaf)) {
    throw "Visual Studio Build Tools is not installed at $VsInstall"
}
$MsvcVersion = (Get-Content -Raw -LiteralPath $VsVersionFile).Trim()
if ($MsvcVersion -ne $Expected.MsvcVersion) {
    throw "MSVC toolset mismatch: expected $($Expected.MsvcVersion), got $MsvcVersion"
}
$VsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $VsWhere -PathType Leaf)) {
    throw "vswhere.exe is missing: $VsWhere"
}
try {
    $vsWhereResult = Invoke-Utf8NativeCapture $VsWhere @(
        '-products', '*',
        '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
        '-format', 'json', '-utf8'
    )
} catch {
    throw "vswhere.exe UTF-8 output capture failed: $($_.Exception.Message)"
}
if ($vsWhereResult.ExitCode -ne 0) {
    throw "vswhere.exe failed: $($vsWhereResult.ExitCode)"
}
$vsInstallationsJson = @($vsWhereResult.Output)
try {
    $vsInstallations = @(
        ($vsInstallationsJson -join [Environment]::NewLine) |
            ConvertFrom-Json -ErrorAction Stop
    )
} catch {
    throw "vswhere.exe emitted invalid UTF-8 JSON: $($_.Exception.Message)"
}
$expectedVsPath = [System.IO.Path]::GetFullPath($VsInstall).TrimEnd('\')
$matchingVsInstallations = @($vsInstallations | Where-Object {
    [System.IO.Path]::GetFullPath([string]$_.installationPath).TrimEnd('\') -ieq $expectedVsPath
})
if ($matchingVsInstallations.Count -ne 1) {
    throw "vswhere did not resolve exactly one Build Tools installation at $expectedVsPath"
}
$VsInstallationVersion = [string]$matchingVsInstallations[0].installationVersion
if ($VsInstallationVersion -ne $Expected.VsInstallationVersion) {
    throw (
        "Visual Studio installation mismatch: expected " +
        "$($Expected.VsInstallationVersion), got $VsInstallationVersion"
    )
}
if (
    $matchingVsInstallations[0].productId -ne 'Microsoft.VisualStudio.Product.BuildTools' -or
    $matchingVsInstallations[0].isComplete -ne $true -or
    $matchingVsInstallations[0].isLaunchable -ne $true
) {
    throw 'Visual Studio Build Tools registration is incomplete or not launchable'
}
$Cl = Join-Path $VsInstall "VC\Tools\MSVC\$MsvcVersion\bin\Hostx64\x64\cl.exe"
$Link = Join-Path $VsInstall "VC\Tools\MSVC\$MsvcVersion\bin\Hostx64\x64\link.exe"
$DevCmd = Join-Path $VsInstall 'Common7\Tools\VsDevCmd.bat'
foreach ($required in @($Cl, $Link)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "MSVC executable is missing: $required"
    }
}
$compilerVersionInfo = (Get-Item -LiteralPath $Cl).VersionInfo
$CompilerFileVersion = [string]$compilerVersionInfo.FileVersion
$CompilerProductVersion = [string]$compilerVersionInfo.ProductVersion
$linkerVersionInfo = (Get-Item -LiteralPath $Link).VersionInfo
$LinkerFileVersion = [string]$linkerVersionInfo.FileVersion
$LinkerProductVersion = [string]$linkerVersionInfo.ProductVersion
if ($CompilerFileVersion -cne $Expected.CompilerFileVersion) {
    throw (
        "MSVC compiler file version mismatch: expected " +
        "$($Expected.CompilerFileVersion), got $CompilerFileVersion"
    )
}
if ($CompilerProductVersion -cne $Expected.CompilerProductVersion) {
    throw (
        "MSVC compiler product version mismatch: expected " +
        "$($Expected.CompilerProductVersion), got $CompilerProductVersion"
    )
}
if ($LinkerFileVersion -cne $Expected.LinkerFileVersion) {
    throw (
        "MSVC linker file version mismatch: expected " +
        "$($Expected.LinkerFileVersion), got $LinkerFileVersion"
    )
}
if ($LinkerProductVersion -cne $Expected.LinkerProductVersion) {
    throw (
        "MSVC linker product version mismatch: expected " +
        "$($Expected.LinkerProductVersion), got $LinkerProductVersion"
    )
}
$MsvcFamilyVersion = (($MsvcVersion -split '\.')[0..1] -join '.')
Import-VsEnvironment $DevCmd $MsvcFamilyVersion $Expected.WindowsSdkVersion

$WindowsSdkRoot = Resolve-WindowsSdkRoot $WindowsSdkRoot $Expected.WindowsSdkVersion
$SignTool = Join-Path $WindowsSdkRoot "bin\$($Expected.WindowsSdkVersion)\x64\signtool.exe"
$KernelLibrary = Join-Path $WindowsSdkRoot "Lib\$($Expected.WindowsSdkVersion)\um\x64\kernel32.lib"
foreach ($required in @($SignTool, $KernelLibrary)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Windows SDK input is missing: $required"
    }
}
$actualVCToolsVersion = ([string]$env:VCToolsVersion).TrimEnd('\')
$actualWindowsSdkVersion = ([string]$env:WindowsSDKVersion).TrimEnd('\')
if ($actualVCToolsVersion -ne $MsvcVersion) {
    throw "VsDevCmd selected the wrong MSVC toolset: $actualVCToolsVersion"
}
if ($actualWindowsSdkVersion -ne $Expected.WindowsSdkVersion) {
    throw "VsDevCmd selected the wrong Windows SDK: $actualWindowsSdkVersion"
}
foreach ($commandBinding in @(
    @('cl.exe', $Cl),
    @('link.exe', $Link),
    @('signtool.exe', $SignTool)
)) {
    $resolvedCommand = (Get-Command $commandBinding[0] -CommandType Application).Source
    if (
        -not [System.IO.Path]::GetFullPath($resolvedCommand).Equals(
            [System.IO.Path]::GetFullPath($commandBinding[1]),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "$($commandBinding[0]) resolved outside the fixed toolchain: $resolvedCommand"
    }
}
$sdkProductVersion = (Get-Item -LiteralPath $SignTool).VersionInfo.ProductVersion
if ($sdkProductVersion -notlike "$($Expected.WindowsSdkServicingVersion)*") {
    throw "Windows SDK servicing mismatch: $sdkProductVersion"
}

Assert-NetworkIsolation
$env:GIT_TERMINAL_PROMPT = '0'
$env:GIT_CONFIG_COUNT = '1'
$env:GIT_CONFIG_KEY_0 = 'url.https://offline.invalid/.insteadOf'
$env:GIT_CONFIG_VALUE_0 = 'https://'
$env:HTTP_PROXY = 'http://127.0.0.1:9'
$env:HTTPS_PROXY = 'http://127.0.0.1:9'
$env:ALL_PROXY = 'http://127.0.0.1:9'
$env:NO_PROXY = ''

if (Test-Path -LiteralPath $OutputRoot) {
    throw "Refusing to reuse or overwrite the controlled-build output: $OutputRoot"
}
$createdOutputRoot = New-Item -ItemType Directory -Path $OutputRoot
if (
    -not $createdOutputRoot.PSIsContainer -or
    ($createdOutputRoot.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
) {
    throw "Controlled-build output is not a real directory: $OutputRoot"
}

$BuildTemp = Join-Path $OutputRoot 'tmp'
$createdBuildTemp = New-Item -ItemType Directory -Path $BuildTemp
if (
    -not $createdBuildTemp.PSIsContainer -or
    ($createdBuildTemp.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
) {
    throw "Controlled-build temporary path is not a real directory: $BuildTemp"
}
$BuildTempFullPath = [System.IO.Path]::GetFullPath($createdBuildTemp.FullName).TrimEnd(
    [char]'\', [char]'/'
)
$env:TEMP = $BuildTempFullPath
$env:TMP = $BuildTempFullPath
$env:TMPDIR = $BuildTempFullPath

$tempDirectoryProbe = @'
import json
import pathlib
import sys
import tempfile

def real_full_path(value):
    return str(pathlib.Path(value).resolve(strict=True))

print(json.dumps({
    "expected": real_full_path(sys.argv[1]),
    "actual": real_full_path(tempfile.gettempdir()),
}, sort_keys=True))
'@
$tempDirectoryProbeOutput = @(& $Python -I -c $tempDirectoryProbe $BuildTempFullPath)
if ($LASTEXITCODE -ne 0 -or $tempDirectoryProbeOutput.Count -ne 1) {
    throw 'Fixed Python could not verify the controlled-build temporary directory'
}
try {
    $tempDirectoryEvidence = $tempDirectoryProbeOutput[0] | ConvertFrom-Json
    $expectedTempRealPath = Get-JsonProperty $tempDirectoryEvidence 'expected'
    $actualTempRealPath = Get-JsonProperty $tempDirectoryEvidence 'actual'
} catch {
    throw "Fixed Python returned invalid temporary-directory evidence: $($_.Exception.Message)"
}
if (
    -not $expectedTempRealPath.Equals(
        $BuildTempFullPath,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or
    -not $actualTempRealPath.Equals(
        $BuildTempFullPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    throw (
        'Fixed Python temporary directory escaped the controlled-build root: ' +
        "expected $BuildTempFullPath, resolved expected $expectedTempRealPath, " +
        "resolved actual $actualTempRealPath"
    )
}

$SourceArchives = Join-Path $OutputRoot 'source-archives'
$BuildDependencies = Join-Path $OutputRoot 'dependencies'
$BuildSource = Join-Path $OutputRoot 'source'
$EvidenceLogs = Join-Path $OutputRoot 'logs'
New-Item -ItemType Directory -Path $SourceArchives | Out-Null
New-Item -ItemType Directory -Path $BuildDependencies | Out-Null
New-Item -ItemType Directory -Path $EvidenceLogs | Out-Null
$vsVerificationLog = @(
    "bootstrapper=$vsLayoutBootstrapper",
    "layout=$VsLayout",
    'arguments=--layout <fixed-layout> --verify --passive --wait',
    "exit_code=$($vsLayoutVerification.ExitCode)",
    "tree_sha256_before=$($vsLayoutEvidence.Sha256)",
    "tree_sha256_after=$($vsLayoutEvidenceAfterVerification.Sha256)"
) -join [Environment]::NewLine
[System.IO.File]::WriteAllText(
    (Join-Path $EvidenceLogs 'visual-studio-layout-verification.log'),
    $vsVerificationLog + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)

$PyTetWildArchive = Join-Path $SourceArchives 'pytetwild-source.zip'
Export-GitTree $Git $PyTetWild $Expected.PyTetWildCommit `
    $PyTetWildArchive $BuildSource
Invoke-Checked $Git @(
    '-C', $BuildSource, 'apply', '--check', '--unidiff-zero', $PyTetWildSourcePatch
)
Invoke-Checked $Git @('-C', $BuildSource, 'apply', '--unidiff-zero', $PyTetWildSourcePatch)
$PatchedAccessor = Join-Path $BuildSource 'src\pytetwild\_accessor.py'
Assert-Sha256 $PatchedAccessor $Expected.PatchedAccessorSha256

$FTetWildArchive = Join-Path $SourceArchives 'ftetwild-source.zip'
Invoke-Checked $Git @(
    '-C', $FTetWild, 'archive', '--format=zip',
    "--output=$FTetWildArchive", $Expected.FTetWildCommit
)
$BuildFTetWild = Join-Path $BuildSource 'src\fTetWild'
New-Item -ItemType Directory -Path $BuildFTetWild -Force | Out-Null
Expand-Archive -LiteralPath $FTetWildArchive -DestinationPath $BuildFTetWild -Force

$FmtBuildSource = Join-Path $BuildDependencies 'fmt'
$SpdlogBuildSource = Join-Path $BuildDependencies 'spdlog'
$LibiglBuildSource = Join-Path $BuildDependencies 'libigl'
$PredicatesBuildSource = Join-Path $BuildDependencies 'predicates'
$GeogramBuildSource = Join-Path $BuildDependencies 'geogram'
$TbbBuildSource = Join-Path $BuildDependencies 'onetbb'
$JsonBuildSource = Join-Path $BuildDependencies 'json'

$gitExports = @(
    @('fmt', $FmtSource, $Expected.FmtCommit, $FmtBuildSource),
    @('spdlog', $SpdlogSource, $Expected.SpdlogCommit, $SpdlogBuildSource),
    @('libigl', $LibiglSource, $Expected.LibiglCommit, $LibiglBuildSource),
    @('predicates', $PredicatesSource, $Expected.PredicatesCommit, $PredicatesBuildSource),
    @('geogram', $GeogramSource, $Expected.GeogramCommit, $GeogramBuildSource),
    @('onetbb', $TbbSource, $Expected.OneTbbCommit, $TbbBuildSource),
    @('json', $JsonSource, $Expected.JsonCommit, $JsonBuildSource)
)
foreach ($export in $gitExports) {
    Export-GitTree $Git $export[1] $export[2] `
        (Join-Path $SourceArchives "$($export[0])-source.zip") $export[3]
}

$geogramSubmodules = @(
    @(
        'geogram-amgcl',
        (Join-Path $GeogramSource 'src\lib\geogram\third_party\amgcl'),
        $Expected.GeogramAmgclCommit,
        (Join-Path $GeogramBuildSource 'src\lib\geogram\third_party\amgcl')
    ),
    @(
        'geogram-libmeshb',
        (Join-Path $GeogramSource 'src\lib\geogram\third_party\libMeshb'),
        $Expected.GeogramLibMeshbCommit,
        (Join-Path $GeogramBuildSource 'src\lib\geogram\third_party\libMeshb')
    ),
    @(
        'geogram-rply',
        (Join-Path $GeogramSource 'src\lib\geogram\third_party\rply'),
        $Expected.GeogramRplyCommit,
        (Join-Path $GeogramBuildSource 'src\lib\geogram\third_party\rply')
    )
)
foreach ($submodule in $geogramSubmodules) {
    $archive = Join-Path $SourceArchives "$($submodule[0])-source.zip"
    Invoke-Checked $Git @(
        '-C', $submodule[1], 'archive', '--format=zip',
        "--output=$archive", $submodule[2]
    )
    New-Item -ItemType Directory -Path $submodule[3] -Force | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $submodule[3] -Force
}

$EigenExtractRoot = Join-Path $BuildDependencies 'eigen-package'
$MpirBuildPrefix = Join-Path $BuildDependencies 'mpir-package'
Expand-SafeTarArchive $Python $EigenArchive $EigenExtractRoot
Expand-SafeTarArchive $Python $MpirArchive $MpirBuildPrefix
$EigenBuildSource = Join-Path $EigenExtractRoot 'eigen-3.4.0'
$MpirInclude = Join-Path $MpirBuildPrefix 'Library\include'
$MpirLibrary = Join-Path $MpirBuildPrefix 'Library\lib\gmp.lib'
$MpirBin = Join-Path $MpirBuildPrefix 'Library\bin'
foreach ($required in @(
    (Join-Path $EigenBuildSource 'Eigen\Core'),
    (Join-Path $MpirInclude 'gmp.h'),
    $MpirLibrary,
    (Join-Path $MpirBin 'mpir.dll')
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Freshly extracted build input is missing: $required"
    }
}

$BuilderVenv = Join-Path $OutputRoot 'builder-venv'
Invoke-Checked $Python @('-m', 'venv', $BuilderVenv)
$BuilderPython = Join-Path $BuilderVenv 'Scripts\python.exe'
$Pip = Join-Path $BuilderVenv 'Scripts\pip.exe'

$env:PIP_NO_INDEX = '1'
$env:PIP_FIND_LINKS = $Wheelhouse
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
Invoke-Checked $BuilderPython @(
    '-m', 'pip', 'install',
    '--no-index', "--find-links=$Wheelhouse", '--require-hashes',
    '-r', $RequirementsLock
)
Invoke-Checked $BuilderPython @('-m', 'pip', 'check')
$env:Path = "$(Join-Path $BuilderVenv 'Scripts');$(Split-Path -Parent $Git);$env:Path"

$packageVersions = & $BuilderPython -c @'
import importlib.metadata as m, json
names = ['pip', 'cmake', 'ninja', 'numpy', 'nanobind', 'cibuildwheel', 'build', 'scikit-build-core', 'delvewheel', 'abi3audit']
print(json.dumps({name: m.version(name) for name in names}, sort_keys=True))
'@
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to read the controlled builder package versions'
}
$packageVersions = ($packageVersions -join [Environment]::NewLine) | ConvertFrom-Json
foreach ($pair in @(
    @('pip', $Expected.PipVersion),
    @('cmake', $Expected.CMakeVersion),
    @('ninja', $Expected.NinjaVersion),
    @('numpy', $Expected.NumpyVersion),
    @('nanobind', $Expected.NanobindVersion),
    @('cibuildwheel', $Expected.CibuildwheelVersion),
    @('build', $Expected.BuildVersion),
    @('scikit-build-core', $Expected.ScikitBuildCoreVersion),
    @('delvewheel', $Expected.DelvewheelVersion),
    @('abi3audit', $Expected.Abi3AuditVersion)
)) {
    $actualPackageVersion = Get-JsonProperty $packageVersions $pair[0]
    if ($actualPackageVersion -ne $pair[1]) {
        throw "Builder package mismatch for $($pair[0]): $actualPackageVersion"
    }
}
$CMakeExecutable = Join-Path $BuilderVenv 'Scripts\cmake.exe'
$NinjaExecutable = Join-Path $BuilderVenv 'Scripts\ninja.exe'
foreach ($required in @($CMakeExecutable, $NinjaExecutable)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Controlled build executable is missing: $required"
    }
}
$cmakeCliVersion = @(& $CMakeExecutable --version)[0].Trim()
if ($LASTEXITCODE -ne 0 -or $cmakeCliVersion -ne "cmake version $($Expected.CMakeVersion)") {
    throw "CMake CLI mismatch: $cmakeCliVersion"
}
$ninjaCliVersion = (& $NinjaExecutable --version).Trim()
if ($LASTEXITCODE -ne 0 -or $ninjaCliVersion -ne $Expected.NinjaCliVersion) {
    throw "Ninja CLI mismatch: $ninjaCliVersion"
}

$cmakeArguments = @(
    '-DCMAKE_BUILD_TYPE=Release',
    '-DCMAKE_CXX_STANDARD=17',
    "-DCMAKE_C_COMPILER:FILEPATH=$(ConvertTo-CMakePath $Cl)",
    "-DCMAKE_CXX_COMPILER:FILEPATH=$(ConvertTo-CMakePath $Cl)",
    "-DCMAKE_LINKER:FILEPATH=$(ConvertTo-CMakePath $Link)",
    '-DBUILD_SHARED_LIBS=OFF',
    '-DFETCHCONTENT_FULLY_DISCONNECTED=ON',
    '-DFETCHCONTENT_TRY_FIND_PACKAGE_MODE=NEVER',
    '-DFLOAT_TETWILD_ENABLE_TBB=ON',
    '-DFLOAT_TETWILD_USE_FLOAT=OFF',
    '-DFLOAT_TETWILD_WITH_SANITIZERS=OFF',
    '-DFLOAT_TETWILD_WITH_EXACT_ENVELOPE=OFF',
    '-DLIBIGL_WITH_PREDICATES=ON',
    '-DLIBIGL_WITH_COMISO=OFF',
    '-DLIBIGL_WITH_EMBREE=OFF',
    '-DLIBIGL_WITH_OPENGL=OFF',
    '-DLIBIGL_WITH_OPENGL_GLFW=OFF',
    '-DLIBIGL_WITH_OPENGL_GLFW_IMGUI=OFF',
    '-DLIBIGL_WITH_PNG=OFF',
    '-DLIBIGL_WITH_TETGEN=OFF',
    '-DLIBIGL_WITH_TRIANGLE=OFF',
    '-DLIBIGL_WITH_XML=OFF',
    '-DEIGEN_MPL2_ONLY=ON',
    '-DGEOGRAM_WITH_GRAPHICS=OFF',
    '-DGEOGRAM_WITH_LUA=OFF',
    '-DGEOGRAM_WITH_EXPLORAGRAM=OFF',
    '-DGEOGRAM_WITH_LEGACY_NUMERICS=OFF',
    '-DGEOGRAM_WITH_TRIANGLE=OFF',
    '-DGEOGRAM_WITH_TETGEN=OFF',
    '-DGEOGRAM_WITH_HLBFGS=OFF',
    '-DGEOGRAM_WITH_GEOGRAMPLUS=OFF',
    '-DGEOGRAM_WITH_TBB=OFF',
    "-DGMP_INCLUDE_DIRS:PATH=$(ConvertTo-CMakePath $MpirInclude)",
    "-DGMP_LIBRARIES:FILEPATH=$(ConvertTo-CMakePath $MpirLibrary)",
    "-DFETCHCONTENT_SOURCE_DIR_FMT:PATH=$(ConvertTo-CMakePath $FmtBuildSource)",
    "-DFETCHCONTENT_SOURCE_DIR_SPDLOG:PATH=$(ConvertTo-CMakePath $SpdlogBuildSource)",
    "-DFETCHCONTENT_SOURCE_DIR_LIBIGL:PATH=$(ConvertTo-CMakePath $LibiglBuildSource)",
    "-DFETCHCONTENT_SOURCE_DIR_EIGEN:PATH=$(ConvertTo-CMakePath $EigenBuildSource)",
    "-DFETCHCONTENT_SOURCE_DIR_PREDICATES:PATH=$(ConvertTo-CMakePath $PredicatesBuildSource)",
    "-DFETCHCONTENT_SOURCE_DIR_GEOGRAM:PATH=$(ConvertTo-CMakePath $GeogramBuildSource)",
    "-DFETCHCONTENT_SOURCE_DIR_TBB:PATH=$(ConvertTo-CMakePath $TbbBuildSource)",
    "-DFETCHCONTENT_SOURCE_DIR_JSON:PATH=$(ConvertTo-CMakePath $JsonBuildSource)"
)

$env:GMP_INC = $MpirInclude
$env:GMP_LIB = Split-Path -Parent $MpirLibrary
$env:CMAKE_GENERATOR = 'Ninja'
$env:CMAKE_ARGS = $cmakeArguments -join ' '
$env:CMAKE_BUILD_PARALLEL_LEVEL = [Math]::Max(1, [Environment]::ProcessorCount).ToString()

$RawWheelDirectory = Join-Path $OutputRoot 'raw-wheel'
$WheelDirectory = Join-Path $OutputRoot 'wheel'
New-Item -ItemType Directory -Path $RawWheelDirectory | Out-Null
New-Item -ItemType Directory -Path $WheelDirectory | Out-Null

$startedUtc = [DateTime]::UtcNow.ToString('o')
$buildWheelArguments = @(
    '-m', 'build', '--wheel', '--no-isolation',
    '--outdir', $RawWheelDirectory, $BuildSource
)
Invoke-CheckedLogged $BuilderPython $buildWheelArguments `
    (Join-Path $EvidenceLogs 'build-wheel.log')
$rawWheels = @(
    Get-ChildItem -LiteralPath $RawWheelDirectory `
        -Filter 'pytetwild-0.3.0-cp312-abi3-win_amd64.whl' -File
)
if ($rawWheels.Count -ne 1) {
    throw "Expected exactly one raw cp312-abi3-win_amd64 wheel, got $($rawWheels.Count)"
}

$Delvewheel = Join-Path $BuilderVenv 'Scripts\delvewheel.exe'
$Abi3Audit = Join-Path $BuilderVenv 'Scripts\abi3audit.exe'
$wheelRecordProbe = @'
import base64
import csv
import hashlib
import io
import pathlib
import re
import stat
import sys
import unicodedata
import zipfile

wheel = pathlib.Path(sys.argv[1])
phase = sys.argv[2]
if phase not in {"raw", "repaired"}:
    raise SystemExit(f"unknown wheel audit phase: {phase!r}")
expected_dist_info = "pytetwild-0.3.0.dist-info"
reserved = {"con", "prn", "aux", "nul"}
reserved.update(f"com{number}" for number in range(1, 10))
reserved.update(f"lpt{number}" for number in range(1, 10))
with zipfile.ZipFile(wheel) as archive:
    infos = archive.infolist()
    if not infos or len(infos) > 10000:
        raise SystemExit(f"unsafe wheel member count: {len(infos)}")
    names = [entry.filename for entry in infos]
    if len(names) != len(set(names)):
        raise SystemExit("wheel contains duplicate ZIP member names")
    folded = [unicodedata.normalize("NFC", name).casefold() for name in names]
    if len(folded) != len(set(folded)):
        raise SystemExit("wheel contains Unicode/case-colliding ZIP member names")
    total_size = 0
    for entry in infos:
        raw_name = entry.orig_filename
        name = entry.filename
        parts = name.split("/")
        mode = entry.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if (
            not name
            or raw_name != name
            or "\x00" in raw_name
            or any(ord(character) < 32 or ord(character) == 127 for character in raw_name)
            or "\\" in name
            or name.startswith("/")
            or name.endswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or any(":" in part or part.endswith((".", " ")) for part in parts)
            or pathlib.PureWindowsPath(name).drive
            or pathlib.PureWindowsPath(name).root
            or unicodedata.normalize("NFC", name) != name
            or any(part.split(".", 1)[0].casefold() in reserved for part in parts)
            or entry.is_dir()
            or entry.flag_bits & 0x41
            or file_type not in {0, stat.S_IFREG}
            or entry.external_attr & 0x400
            or entry.file_size > 1024 * 1024 * 1024
        ):
            raise SystemExit(f"unsafe wheel member: {name!r}")
        total_size += entry.file_size
    if total_size > 4 * 1024 * 1024 * 1024:
        raise SystemExit(f"unsafe wheel uncompressed size: {total_size}")
    name_set = set(names)
    for name in names:
        parts = name.split("/")
        for index in range(1, len(parts)):
            if "/".join(parts[:index]) in name_set:
                raise SystemExit(f"wheel has file/ancestor conflict: {name!r}")
    foreign_dist_info = [
        name for name in names
        if ".dist-info/" in name and not name.startswith(expected_dist_info + "/")
    ]
    if foreign_dist_info:
        raise SystemExit(f"wheel contains foreign dist-info files: {foreign_dist_info!r}")
    record_name = expected_dist_info + "/RECORD"
    records = [name for name in names if name.endswith(".dist-info/RECORD")]
    if records != [record_name]:
        raise SystemExit(f"unexpected RECORD set: {records!r}")
    required_metadata = {
        expected_dist_info + "/METADATA",
        expected_dist_info + "/WHEEL",
    }
    delvewheel_metadata = expected_dist_info + "/DELVEWHEEL"
    if not required_metadata.issubset(name_set):
        raise SystemExit("wheel is missing required dist-info metadata")
    if (phase == "repaired") != (delvewheel_metadata in name_set):
        raise SystemExit(f"unexpected DELVEWHEEL metadata state for {phase} wheel")
    with archive.open(record_name) as raw_record:
        reader = csv.reader(
            io.TextIOWrapper(raw_record, encoding="utf-8", newline=""), strict=True
        )
        rows = list(reader)
    seen = set()
    entries = {entry.filename: entry for entry in infos}
    for row in rows:
        if len(row) != 3:
            raise SystemExit(f"invalid RECORD row: {row!r}")
        name, digest, size = row
        if name in seen:
            raise SystemExit(f"duplicate RECORD path: {name!r}")
        seen.add(name)
        if name not in entries:
            raise SystemExit(f"RECORD names a missing wheel member: {name!r}")
        if name == record_name:
            if digest or size:
                raise SystemExit("RECORD self-entry must have empty hash and size")
            continue
        if (
            re.fullmatch(r"sha256=[A-Za-z0-9_-]{43}", digest) is None
            or re.fullmatch(r"(?:0|[1-9][0-9]*)", size) is None
        ):
            raise SystemExit(f"RECORD entry lacks SHA-256 or size: {name!r}")
        data = archive.read(name)
        actual_digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        if digest[7:] != actual_digest or int(size) != len(data):
            raise SystemExit(f"RECORD content mismatch: {name!r}")
    missing = set(names) - seen
    if missing:
        raise SystemExit(f"wheel members missing from RECORD: {sorted(missing)!r}")
print(f"verified RECORD: {wheel.name}")
'@
$rawWheelSha256 = Get-Sha256 $rawWheels[0].FullName
Invoke-Checked $BuilderPython @(
    '-c', $wheelRecordProbe, $rawWheels[0].FullName, 'raw'
)
$rawDelvewheelArguments = @(
    'show', '--add-path', $MpirBin, '-vv', $rawWheels[0].FullName
)
$rawDelvewheelResult = Invoke-Logged $Delvewheel $rawDelvewheelArguments `
    (Join-Path $EvidenceLogs 'delvewheel-show-raw.log')
$rawDelvewheelExit = $rawDelvewheelResult.ExitCode
$rawDelvewheelText = $rawDelvewheelResult.Output
if (
    $rawDelvewheelExit -ne 0 -or
    $rawDelvewheelText -match '\(Error: Not Found\)'
) {
    throw 'Raw wheel DLL analysis found an unresolved dependency'
}
$repairArguments = @(
    'repair', '--wheel-dir', $WheelDirectory, '-v',
    $rawWheels[0].FullName, '--add-path', $MpirBin
)
Invoke-CheckedLogged $Delvewheel $repairArguments `
    (Join-Path $EvidenceLogs 'delvewheel-repair.log')
$wheels = @(Get-ChildItem -LiteralPath $WheelDirectory -Filter 'pytetwild-0.3.0-cp312-abi3-win_amd64.whl' -File)
if ($wheels.Count -ne 1) {
    throw "Expected one repaired cp312-abi3-win_amd64 wheel, got $($wheels.Count)"
}
$wheel = $wheels[0]
$repairedWheelSha256BeforeAudit = Get-Sha256 $wheel.FullName
Invoke-Checked $BuilderPython @('-m', 'zipfile', '-t', $wheel.FullName)
Invoke-Checked $BuilderPython @(
    '-c', $wheelRecordProbe, $wheel.FullName, 'repaired'
)
$abi3AuditArguments = @('--strict', '--report', '--verbose', $wheel.FullName)
Invoke-CheckedLogged $Abi3Audit $abi3AuditArguments `
    (Join-Path $EvidenceLogs 'abi3audit.log')
$nativeDependencyProbe = @'
import hashlib
import io
import os
import pathlib
import sys
import tempfile
import zipfile

from delvewheel import _dll_utils

wheel = pathlib.Path(sys.argv[1]).resolve()
expected_delvewheel = sys.argv[2]
expected_sha256 = sys.argv[3]
wheel_bytes = wheel.read_bytes()
if hashlib.sha256(wheel_bytes).hexdigest() != expected_sha256:
    raise SystemExit("repaired wheel changed between validation and dependency audit")
with tempfile.TemporaryDirectory(prefix="pytetwild-wheel-audit-") as temporary:
    root = pathlib.Path(temporary).resolve()
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
        archive.extractall(root)
    metadata = list(root.glob("*.dist-info/DELVEWHEEL"))
    if len(metadata) != 1:
        raise SystemExit(f"expected one DELVEWHEEL metadata file, got {len(metadata)}")
    first_line = metadata[0].read_text(encoding="utf-8").splitlines()[0]
    if first_line != f"Version: {expected_delvewheel}":
        raise SystemExit(f"unexpected DELVEWHEEL metadata: {first_line!r}")
    wheel_dirs = [str(root)] + [str(path) for path in root.rglob("*") if path.is_dir()]
    binaries = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".pyd", ".dll"}
    )
    if not binaries or not any(path.suffix.casefold() == ".pyd" for path in binaries):
        raise SystemExit("repaired wheel does not contain a native extension")
    unresolved = {}
    external = {}
    for binary in binaries:
        discovered, _, _, not_found = _dll_utils.get_all_needed(
            str(binary), set(), wheel_dirs, "ignore", False, False
        )
        if not_found:
            unresolved[binary.relative_to(root).as_posix()] = sorted(not_found)
        escaped = sorted(
            dependency for dependency in discovered
            if not pathlib.Path(dependency).resolve().is_relative_to(root)
        )
        if escaped:
            external[binary.relative_to(root).as_posix()] = escaped
    if unresolved:
        raise SystemExit(f"unresolved native dependencies: {unresolved!r}")
    if external:
        raise SystemExit(f"unvendored native dependencies: {external!r}")
print(f"verified repaired native dependency closure: {len(binaries)} binaries")
'@
$nativeDependencyArguments = @(
    '-c', $nativeDependencyProbe, $wheel.FullName, $Expected.DelvewheelVersion,
    $repairedWheelSha256BeforeAudit
)
Invoke-CheckedLogged $BuilderPython $nativeDependencyArguments `
    (Join-Path $EvidenceLogs 'native-dependency-closure.log')

$NativeTest = Join-Path $OutputRoot 'native-load-test'
Invoke-Checked $Python @('-m', 'venv', $NativeTest)
$NativePython = Join-Path $NativeTest 'Scripts\python.exe'
$numpyWheels = @(
    Get-ChildItem -LiteralPath $Wheelhouse `
        -Filter "numpy-$($Expected.NumpyVersion)-cp312-cp312-win_amd64.whl" -File
)
if ($numpyWheels.Count -ne 1) {
    throw "Expected exactly one fixed NumPy wheel, got $($numpyWheels.Count)"
}
Assert-Sha256 $numpyWheels[0].FullName $Expected.NumpyWheelSha256
$NativeRequirements = Join-Path $NativeTest 'requirements-native-smoke.lock'
$wheelUri = ([System.Uri]::new($wheel.FullName)).AbsoluteUri
$nativeRequirementsText = @(
    "numpy==$($Expected.NumpyVersion) --hash=sha256:$($Expected.NumpyWheelSha256)",
    "pytetwild @ $wheelUri --hash=sha256:$repairedWheelSha256BeforeAudit"
) -join [Environment]::NewLine
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $NativeRequirements,
    $nativeRequirementsText + [Environment]::NewLine,
    $utf8NoBom
)
$nativeInstallArguments = @(
    '-m', 'pip', 'install', '--disable-pip-version-check',
    '--require-hashes', '--only-binary=:all:', '--no-index', '--no-deps',
    '--find-links', $Wheelhouse, '-r', $NativeRequirements
)
Invoke-CheckedLogged $NativePython $nativeInstallArguments `
    (Join-Path $EvidenceLogs 'native-smoke-install.log')
$nativeProbe = @'
import ctypes
import importlib.metadata
import pathlib
import sys
import sysconfig

site_packages = pathlib.Path(sysconfig.get_paths()["purelib"]).resolve()
import pytetwild
from pytetwild import PyfTetWildWrapper as native

package_path = pathlib.Path(pytetwild.__file__).resolve()
native_path = pathlib.Path(native.__file__).resolve()
if not package_path.is_relative_to(site_packages):
    raise SystemExit(f"pytetwild loaded outside isolated site-packages: {package_path}")
if not native_path.is_relative_to(site_packages):
    raise SystemExit(f"native extension loaded outside isolated site-packages: {native_path}")
if pytetwild.__version__ != "0.3.0" or importlib.metadata.version("pytetwild") != "0.3.0":
    raise SystemExit("unexpected pytetwild package version")
if not callable(pytetwild.tetrahedralize):
    raise SystemExit("pytetwild.tetrahedralize is unavailable")
if not callable(native.tetrahedralize_mesh):
    raise SystemExit("native tetrahedralize_mesh is unavailable")

load_orders = list(site_packages.rglob(".load-order-*"))
if len(load_orders) != 1:
    raise SystemExit(f"expected one delvewheel load-order file, got {len(load_orders)}")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
vendored = [line.strip() for line in load_orders[0].read_text(encoding="utf-8").splitlines() if line.strip()]
if not vendored:
    raise SystemExit("delvewheel load-order file is empty")
not_loaded = []
for reference in vendored:
    name = pathlib.PureWindowsPath(reference).name
    if not kernel32.GetModuleHandleW(name):
        not_loaded.append(name)
if not_loaded:
    raise SystemExit(f"delvewheel did not load vendored DLLs: {not_loaded!r}")
print(f"normal package import passed: {package_path.name}; vendored DLLs: {len(vendored)}")
'@
$HostileCwd = Join-Path $NativeTest 'hostile-cwd'
New-Item -ItemType Directory -Path $HostileCwd | Out-Null
[System.IO.File]::WriteAllText(
    (Join-Path $HostileCwd 'pytetwild.py'),
    "raise RuntimeError('hostile cwd module was imported')`n",
    $utf8NoBom
)
$savedPath = $env:PATH
$savedPythonPath = $env:PYTHONPATH
$savedPythonHome = $env:PYTHONHOME
try {
    $env:PATH = (Join-Path $env:SystemRoot 'System32') + ";$env:SystemRoot"
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONHOME', $null, 'Process')
    Push-Location $HostileCwd
    try {
        Invoke-CheckedLogged $NativePython @('-I', '-c', $nativeProbe) `
            (Join-Path $EvidenceLogs 'native-normal-import.log')
    } finally {
        Pop-Location
    }
} finally {
    $env:PATH = $savedPath
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $savedPythonPath, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONHOME', $savedPythonHome, 'Process')
}

$finishedUtc = [DateTime]::UtcNow.ToString('o')
$wheelSha256 = Get-Sha256 $wheel.FullName
if ($wheelSha256 -ne $repairedWheelSha256BeforeAudit) {
    throw 'Repaired wheel changed after validation'
}
Assert-Sha256 $rawWheels[0].FullName $rawWheelSha256
Assert-Sha256 $PSCommandPath $recipeSha256AtStart
Assert-Sha256 $RequirementsLock $requirementsLockSha256AtStart
Assert-Sha256 $PyTetWildSourcePatch $sourcePatchSha256AtStart
$auditLogFiles = [ordered]@{
    visual_studio_layout_verification = 'visual-studio-layout-verification.log'
    build_wheel = 'build-wheel.log'
    raw_delvewheel_show = 'delvewheel-show-raw.log'
    delvewheel_repair = 'delvewheel-repair.log'
    abi3audit = 'abi3audit.log'
    native_dependency_closure = 'native-dependency-closure.log'
    native_smoke_install = 'native-smoke-install.log'
    native_normal_import = 'native-normal-import.log'
}
$auditLogEvidence = [ordered]@{}
foreach ($auditLogName in $auditLogFiles.Keys) {
    $auditLogFilename = $auditLogFiles[$auditLogName]
    $auditLogPath = Join-Path $EvidenceLogs $auditLogFilename
    if (-not (Test-Path -LiteralPath $auditLogPath -PathType Leaf)) {
        throw "Required audit log is missing: $auditLogPath"
    }
    $auditLogEvidence[$auditLogName] = [ordered]@{
        filename = $auditLogFilename
        sha256 = Get-Sha256 $auditLogPath
    }
}
$attestation = [ordered]@{
    schema_version = 1
    status = 'verified-controlled-rebuild'
    scope = 'prospective-rebuild-only'
    started_utc = $startedUtc
    finished_utc = $finishedUtc
    network_policy = [ordered]@{
        operator_confirmed_os_level_isolation = $OsNetworkIsolationConfirmed.IsPresent
        os_level_enforcement_by_script = $false
        script_enforcement_scope = 'prebuild-probes-and-child-process-guards-only'
        pip_no_index = $true
        fetchcontent_fully_disconnected = $true
        fetchcontent_try_find_package_mode = 'NEVER'
        git_https_rewritten_to_offline_invalid = $true
        process_proxies_rejected_at_loopback_port_9 = $true
        prebuild_direct_connect_probes = 'all-unreachable'
        probe_targets = @(
            'github.com:443',
            'pypi.org:443',
            'files.pythonhosted.org:443',
            'conda.anaconda.org:443'
        )
    }
    sources = [ordered]@{
        pytetwild_commit = $Expected.PyTetWildCommit
        pytetwild_optional_pyvista_patch_sha256 = $sourcePatchSha256AtStart
        pytetwild_patched_accessor_sha256 = $Expected.PatchedAccessorSha256
        ftetwild_commit = $Expected.FTetWildCommit
        nanobind_commit = $Expected.NanobindCommit
        fmt_commit = $Expected.FmtCommit
        spdlog_commit = $Expected.SpdlogCommit
        libigl_commit = $Expected.LibiglCommit
        predicates_commit = $Expected.PredicatesCommit
        geogram_commit = $Expected.GeogramCommit
        geogram_amgcl_commit = $Expected.GeogramAmgclCommit
        geogram_libmeshb_commit = $Expected.GeogramLibMeshbCommit
        geogram_rply_commit = $Expected.GeogramRplyCommit
        onetbb_commit = $Expected.OneTbbCommit
        json_commit = $Expected.JsonCommit
        eigen_archive_sha256 = $Expected.EigenArchiveSha256
        mpir_archive_sha256 = $Expected.MpirArchiveSha256
    }
    environment = [ordered]@{
        runner_image = 'self-hosted-windows-controlled-offline'
        python_version = $pythonVersion
        pip_version = (Get-JsonProperty $packageVersions 'pip')
        visual_studio_installation_version = $VsInstallationVersion
        compiler = "MSVC $MsvcVersion"
        compiler_family_requested_from_vsdevcmd = $MsvcFamilyVersion
        compiler_path = $Cl
        linker_path = $Link
        compiler_file_version = $CompilerFileVersion
        compiler_product_version = $CompilerProductVersion
        linker_file_version = $LinkerFileVersion
        linker_product_version = $LinkerProductVersion
        signtool_path = $SignTool
        windows_sdk_version = $Expected.WindowsSdkVersion
        windows_sdk_servicing_version = $sdkProductVersion
        cmake_version = (Get-JsonProperty $packageVersions 'cmake')
        ninja_version = (Get-JsonProperty $packageVersions 'ninja')
        cmake_cli = $cmakeCliVersion
        ninja_cli = $ninjaCliVersion
        nanobind_version = (Get-JsonProperty $packageVersions 'nanobind')
        cibuildwheel_version = (Get-JsonProperty $packageVersions 'cibuildwheel')
        build_version = (Get-JsonProperty $packageVersions 'build')
        scikit_build_core_version = (Get-JsonProperty $packageVersions 'scikit-build-core')
        delvewheel_version = (Get-JsonProperty $packageVersions 'delvewheel')
        abi3audit_version = (Get-JsonProperty $packageVersions 'abi3audit')
        numpy_version = $Expected.NumpyVersion
    }
    inputs = [ordered]@{
        build_recipe_sha256 = $recipeSha256AtStart
        build_requirements_lock_sha256 = $requirementsLockSha256AtStart
        source_patch_sha256 = $sourcePatchSha256AtStart
        python_installer_sha256 = $Expected.PythonInstallerSha256
        portable_git_sha256 = $Expected.PortableGitSha256
        visual_studio_bootstrapper_sha256 = $Expected.VsBootstrapperSha256
        visual_studio_catalog_sha256 = $Expected.VsCatalogSha256
        visual_studio_channel_manifest_sha256 = $Expected.VsChannelManifestSha256
        visual_studio_layout_sha256 = $Expected.VsLayoutSha256
        visual_studio_installer_opc_sha256 = $Expected.VsInstallerOpcSha256
        visual_studio_layout_file_count = $vsLayoutEvidence.FileCount
        visual_studio_layout_total_bytes = $vsLayoutEvidence.TotalBytes
        visual_studio_layout_tree_sha256 = $vsLayoutEvidence.Sha256
        microsoft_visual_studio_layout_verifier_exit_code = $vsLayoutVerification.ExitCode
        source_archives = [ordered]@{
            pytetwild_sha256 = Get-Sha256 $PyTetWildArchive
            ftetwild_sha256 = Get-Sha256 $FTetWildArchive
            fmt_sha256 = Get-Sha256 (Join-Path $SourceArchives 'fmt-source.zip')
            spdlog_sha256 = Get-Sha256 (Join-Path $SourceArchives 'spdlog-source.zip')
            libigl_sha256 = Get-Sha256 (Join-Path $SourceArchives 'libigl-source.zip')
            predicates_sha256 = Get-Sha256 (Join-Path $SourceArchives 'predicates-source.zip')
            geogram_sha256 = Get-Sha256 (Join-Path $SourceArchives 'geogram-source.zip')
            geogram_amgcl_sha256 = Get-Sha256 (Join-Path $SourceArchives 'geogram-amgcl-source.zip')
            geogram_libmeshb_sha256 = Get-Sha256 (Join-Path $SourceArchives 'geogram-libmeshb-source.zip')
            geogram_rply_sha256 = Get-Sha256 (Join-Path $SourceArchives 'geogram-rply-source.zip')
            onetbb_sha256 = Get-Sha256 (Join-Path $SourceArchives 'onetbb-source.zip')
            json_sha256 = Get-Sha256 (Join-Path $SourceArchives 'json-source.zip')
        }
    }
    output = [ordered]@{
        filename = $wheel.Name
        sha256 = $wheelSha256
        raw_wheel_filename = $rawWheels[0].Name
        raw_wheel_sha256 = $rawWheelSha256
        python_tag = 'cp312'
        abi_tag = 'abi3'
        platform_tag = 'win_amd64'
        zip_test = 'passed'
        raw_wheel_record = 'passed'
        repaired_wheel_record = 'passed'
        abi3audit_strict = 'passed'
        raw_delvewheel_show = 'passed-no-not-found-markers'
        repaired_native_dependency_closure = 'passed'
        repaired_delvewheel_metadata = 'passed'
        native_extension_load = 'passed'
        normal_isolated_package_import = 'passed'
        vendored_dll_load_order = 'passed'
        audit_logs = $auditLogEvidence
    }
}
$AttestationPath = Join-Path $OutputRoot 'pytetwild-build-attestation.json'
$attestationJson = $attestation | ConvertTo-Json -Depth 8
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $AttestationPath,
    $attestationJson + [Environment]::NewLine,
    $utf8NoBom
)

Write-Host "Controlled PyTetWild wheel: $($wheel.FullName)"
Write-Host "Wheel SHA-256: $wheelSha256"
Write-Host "Attestation: $AttestationPath"
