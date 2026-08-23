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
    Python3DllSha256 = 'fb975a606e7fbf74f64260e3f60c3490b4f74a183c0926fd6ed1ac4c52ac7b1c'
    PythonVcruntime140Sha256 = '052ad6a20d375957e82aa6a3c441ea548d89be0981516ca7eb306e063d5027f4'
    PythonVcruntime1401Sha256 = '6a99bc0128e0c7d6cbbf615fcc26909565e17d4ca3451b97f8987f9c6acbc6c8'
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
    MsvcRedistributableDirectoryVersion = '14.44.35112'
    MsvcRedistributableFileVersion = '14.44.35211.0'
    Concrt140Sha256 = '2405355f0a58067b258f8df33c327e3a3d716eaac5a3a5aebb757842d85bd376'
    Msvcp140Sha256 = '0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9'
    MpirDllSha256 = '08d901b97a987dd23023ef4273d26fc6e0ff7fcddcdba6b6e39dc057931af994'
    MangledConcrt140Name = 'concrt140-f0bbbe239e5790ab18aee7b037c2c8d7.dll'
    MangledMsvcp140Name = 'msvcp140-0f885b509a685d2bbfa652fed26b5fb3.dll'
    MangledMpirName = 'mpir-edacc3ad4d6953dad7efea4fd55460a3.dll'
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

function Get-ControlledPythonArguments(
    [string]$Source,
    [string[]]$Arguments = @()
) {
    if ([string]::IsNullOrWhiteSpace($Source)) {
        throw 'Controlled Python source must not be empty'
    }
    $strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
    $encodedSource = [Convert]::ToBase64String($strictUtf8.GetBytes($Source))
    $bootstrap = (
        'import base64,sys;' +
        'source=base64.b64decode(sys.argv.pop(1),validate=True);' +
        'exec(compile(source,''<controlled-build>'',''exec''))'
    )
    $pythonArguments = New-Object 'System.Collections.Generic.List[string]'
    foreach ($argument in @('-I', '-c', $bootstrap, $encodedSource)) {
        [void]$pythonArguments.Add($argument)
    }
    foreach ($argument in @($Arguments)) {
        if ($null -eq $argument) {
            throw 'Controlled Python arguments must not contain null values'
        }
        [void]$pythonArguments.Add([string]$argument)
    }
    return $pythonArguments.ToArray()
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

function Assert-DelvewheelDependencySelection(
    [object]$Result,
    [string]$PinnedCrtDirectory,
    [string]$MpirBin,
    [string]$Phase
) {
    if ($Result.ExitCode -ne 0) {
        throw "Delvewheel $Phase failed: $($Result.ExitCode)"
    }
    $output = [string]$Result.Output
    if (
        $output -match '(?i)\(Error: Not Found\)|UserWarning|newer platform toolset' -or
        $output -match '(?i)[a-z]:\\windows\\system32\\(?:concrt140|msvcp140)\.dll'
    ) {
        throw "Delvewheel $Phase reported an unsafe or unresolved dependency selection"
    }
    foreach ($expectedSource in @(
        (Join-Path $PinnedCrtDirectory 'concrt140.dll'),
        (Join-Path $PinnedCrtDirectory 'msvcp140.dll'),
        (Join-Path $MpirBin 'mpir.dll')
    )) {
        if ($output -notmatch [regex]::Escape($expectedSource)) {
            throw "Delvewheel $Phase did not select the pinned dependency: $expectedSource"
        }
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
    $extractArguments = Get-ControlledPythonArguments `
        $extractScript @($Archive, $Destination)
    Invoke-Checked $Python $extractArguments
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
$PythonBaseDirectory = Split-Path -Parent $Python
$PinnedPythonRuntimeFiles = [ordered]@{
    'python3.dll' = $Expected.Python3DllSha256
    'vcruntime140.dll' = $Expected.PythonVcruntime140Sha256
    'vcruntime140_1.dll' = $Expected.PythonVcruntime1401Sha256
}
foreach ($binding in $PinnedPythonRuntimeFiles.GetEnumerator()) {
    $runtimePath = Join-Path $PythonBaseDirectory $binding.Key
    $runtimeItem = Get-Item -LiteralPath $runtimePath -Force -ErrorAction Stop
    if (
        $runtimeItem.PSIsContainer -or
        ($runtimeItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Pinned Python runtime file is unsafe: $runtimePath"
    }
    Assert-Sha256 $runtimePath $binding.Value
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
$PinnedCrtDirectory = Join-Path $VsInstall (
    'VC\Redist\MSVC\' + $Expected.MsvcRedistributableDirectoryVersion +
    '\x64\Microsoft.VC143.CRT'
)
$pinnedCrtDirectoryItem = Get-Item -LiteralPath $PinnedCrtDirectory -Force -ErrorAction Stop
if (
    -not $pinnedCrtDirectoryItem.PSIsContainer -or
    ($pinnedCrtDirectoryItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
) {
    throw "Pinned MSVC redistributable directory is unsafe: $PinnedCrtDirectory"
}
$PinnedCrtFiles = [ordered]@{
    'concrt140.dll' = $Expected.Concrt140Sha256
    'msvcp140.dll' = $Expected.Msvcp140Sha256
}
foreach ($binding in $PinnedCrtFiles.GetEnumerator()) {
    $runtimePath = Join-Path $PinnedCrtDirectory $binding.Key
    $runtimeItem = Get-Item -LiteralPath $runtimePath -Force -ErrorAction Stop
    if (
        $runtimeItem.PSIsContainer -or
        ($runtimeItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Pinned MSVC redistributable file is unsafe: $runtimePath"
    }
    Assert-Sha256 $runtimePath $binding.Value
    if (
        [string]$runtimeItem.VersionInfo.FileVersion -cne
            $Expected.MsvcRedistributableFileVersion -or
        [string]$runtimeItem.VersionInfo.ProductVersion -cne
            $Expected.MsvcRedistributableFileVersion
    ) {
        throw "Pinned MSVC redistributable version mismatch: $runtimePath"
    }
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
$tempDirectoryProbeArguments = Get-ControlledPythonArguments `
    $tempDirectoryProbe @($BuildTempFullPath)
$tempDirectoryProbeOutput = @(& $Python @tempDirectoryProbeArguments)
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
$MpirDll = Join-Path $MpirBin 'mpir.dll'
Assert-Sha256 $MpirDll $Expected.MpirDllSha256
$DelvewheelAddPath = "$PinnedCrtDirectory;$MpirBin"

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

$packageVersionProbe = @'
import importlib.metadata as m, json
names = ['pip', 'cmake', 'ninja', 'numpy', 'nanobind', 'cibuildwheel', 'build', 'scikit-build-core', 'delvewheel', 'abi3audit']
print(json.dumps({name: m.version(name) for name in names}, sort_keys=True))
'@
$packageVersionArguments = Get-ControlledPythonArguments $packageVersionProbe
$packageVersions = & $BuilderPython @packageVersionArguments
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
    member_paths = [name[:-1] if name.endswith("/") else name for name in names]
    folded_member_paths = [
        unicodedata.normalize("NFC", name).casefold() for name in member_paths
    ]
    if len(folded_member_paths) != len(set(folded_member_paths)):
        raise SystemExit("wheel contains a file/directory ZIP member collision")
    total_size = 0
    directory_names = set()
    file_names = set()
    for entry in infos:
        raw_name = entry.orig_filename
        name = entry.filename
        is_directory = entry.is_dir()
        member_path = name[:-1] if is_directory else name
        parts = member_path.split("/")
        mode = entry.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if (
            not name
            or not member_path
            or raw_name != name
            or "\x00" in raw_name
            or any(ord(character) < 32 or ord(character) == 127 for character in raw_name)
            or "\\" in name
            or name.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or any(":" in part or part.endswith((".", " ")) for part in parts)
            or pathlib.PureWindowsPath(member_path).drive
            or pathlib.PureWindowsPath(member_path).root
            or unicodedata.normalize("NFC", name) != name
            or any(part.split(".", 1)[0].casefold() in reserved for part in parts)
            or entry.flag_bits & 0x41
            or entry.external_attr & 0x400
            or entry.file_size > 1024 * 1024 * 1024
            or (
                is_directory
                and (
                    phase != "repaired"
                    or entry.file_size != 0
                    or entry.compress_size != 0
                    or entry.CRC != 0
                    or entry.compress_type != zipfile.ZIP_STORED
                    or file_type != stat.S_IFDIR
                    or not entry.external_attr & 0x10
                )
            )
            or (
                not is_directory
                and (
                    name.endswith("/")
                    or file_type not in {0, stat.S_IFREG}
                    or entry.external_attr & 0x10
                )
            )
        ):
            raise SystemExit(f"unsafe wheel member: {name!r}")
        if is_directory:
            directory_names.add(name)
        else:
            file_names.add(name)
        total_size += entry.file_size
    if total_size > 4 * 1024 * 1024 * 1024:
        raise SystemExit(f"unsafe wheel uncompressed size: {total_size}")
    for directory in directory_names:
        if not any(name.startswith(directory) for name in file_names):
            raise SystemExit(f"wheel contains an orphan directory member: {directory!r}")
    folded_file_names = {
        unicodedata.normalize("NFC", name).casefold() for name in file_names
    }
    for member_path in member_paths:
        parts = member_path.split("/")
        for index in range(1, len(parts)):
            ancestor = unicodedata.normalize(
                "NFC", "/".join(parts[:index])
            ).casefold()
            if ancestor in folded_file_names:
                raise SystemExit(f"wheel has file/ancestor conflict: {member_path!r}")
    name_set = set(names)
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
    entries = {entry.filename: entry for entry in infos if not entry.is_dir()}
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
    missing = file_names - seen
    if missing:
        raise SystemExit(f"wheel members missing from RECORD: {sorted(missing)!r}")
print(f"verified RECORD: {wheel.name}")
'@
$rawWheelSha256 = Get-Sha256 $rawWheels[0].FullName
$rawWheelRecordArguments = Get-ControlledPythonArguments `
    $wheelRecordProbe @($rawWheels[0].FullName, 'raw')
Invoke-Checked $BuilderPython $rawWheelRecordArguments
$rawDelvewheelArguments = @(
    'show', '--add-path', $DelvewheelAddPath, '-vv', $rawWheels[0].FullName
)
$rawDelvewheelResult = Invoke-Logged $Delvewheel $rawDelvewheelArguments `
    (Join-Path $EvidenceLogs 'delvewheel-show-raw.log')
Assert-DelvewheelDependencySelection `
    $rawDelvewheelResult $PinnedCrtDirectory $MpirBin 'show'
$repairArguments = @(
    'repair', '--wheel-dir', $WheelDirectory, '-v',
    $rawWheels[0].FullName, '--add-path', $DelvewheelAddPath
)
$repairResult = Invoke-Logged $Delvewheel $repairArguments `
    (Join-Path $EvidenceLogs 'delvewheel-repair.log')
Assert-DelvewheelDependencySelection `
    $repairResult $PinnedCrtDirectory $MpirBin 'repair'
$wheels = @(Get-ChildItem -LiteralPath $WheelDirectory -Filter 'pytetwild-0.3.0-cp312-abi3-win_amd64.whl' -File)
if ($wheels.Count -ne 1) {
    throw "Expected one repaired cp312-abi3-win_amd64 wheel, got $($wheels.Count)"
}
$wheel = $wheels[0]
$repairedWheelSha256BeforeAudit = Get-Sha256 $wheel.FullName
Invoke-Checked $BuilderPython @('-m', 'zipfile', '-t', $wheel.FullName)
$repairedWheelRecordArguments = Get-ControlledPythonArguments `
    $wheelRecordProbe @($wheel.FullName, 'repaired')
Invoke-Checked $BuilderPython $repairedWheelRecordArguments
$abi3AuditArguments = @('--strict', '--report', '--verbose', $wheel.FullName)
Invoke-CheckedLogged $Abi3Audit $abi3AuditArguments `
    (Join-Path $EvidenceLogs 'abi3audit.log')
$nativeDependencyProbe = @'
import hashlib
import io
import pathlib
import re
import sys
import tempfile
import zipfile

from delvewheel import _dll_list, _dll_utils

wheel = pathlib.Path(sys.argv[1]).resolve()
expected_delvewheel = sys.argv[2]
expected_sha256 = sys.argv[3]
expected_vendored = {
    "concrt140": sys.argv[4].casefold(),
    "msvcp140": sys.argv[5].casefold(),
    "mpir": sys.argv[6].casefold(),
}
excluded_runtime = {"vcruntime140.dll", "vcruntime140_1.dll"}
expected_ignored = {
    "advapi32.dll",
    "api-ms-win-crt-convert-l1-1-0.dll",
    "api-ms-win-crt-environment-l1-1-0.dll",
    "api-ms-win-crt-filesystem-l1-1-0.dll",
    "api-ms-win-crt-heap-l1-1-0.dll",
    "api-ms-win-crt-locale-l1-1-0.dll",
    "api-ms-win-crt-math-l1-1-0.dll",
    "api-ms-win-crt-runtime-l1-1-0.dll",
    "api-ms-win-crt-stdio-l1-1-0.dll",
    "api-ms-win-crt-string-l1-1-0.dll",
    "api-ms-win-crt-time-l1-1-0.dll",
    "api-ms-win-crt-utility-l1-1-0.dll",
    "kernel32.dll",
    "python3.dll",
    "shell32.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
}
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
    vendored_directory = (root / "pytetwild.libs").resolve(strict=True)
    vendored_dlls = sorted(vendored_directory.glob("*.dll"))
    expected_extension = (root / "pytetwild" / "PyfTetWildWrapper.pyd").resolve(strict=True)
    pyds = sorted(path.resolve() for path in root.rglob("*.pyd"))
    if pyds != [expected_extension]:
        raise SystemExit(
            f"unexpected native extension set: "
            f"{[path.relative_to(root).as_posix() for path in pyds]!r}"
        )
    all_dlls = sorted(path.resolve() for path in root.rglob("*.dll"))
    if set(all_dlls) != set(vendored_dlls):
        raise SystemExit(
            f"native DLL escaped pytetwild.libs: "
            f"{[path.relative_to(root).as_posix() for path in all_dlls]!r}"
        )
    binaries = [expected_extension, *vendored_dlls]
    wrong_architecture = sorted(
        path.relative_to(root).as_posix() for path in binaries
        if _dll_utils.get_arch(str(path)) is not _dll_list.MachineType.AMD64
    )
    if wrong_architecture:
        raise SystemExit(f"repaired wheel contains non-AMD64 binaries: {wrong_architecture!r}")
    matched_vendored = set()
    vendored_by_stem = {}
    for stem, expected_name in expected_vendored.items():
        pattern = re.compile(rf"{re.escape(stem)}-[0-9a-f]{{32}}\.dll", re.IGNORECASE)
        if pattern.fullmatch(expected_name) is None:
            raise SystemExit(f"unsafe expected mangled DLL name: {expected_name!r}")
        matches = [
            path for path in vendored_dlls
            if path.name.casefold() == expected_name
        ]
        if len(matches) != 1:
            raise SystemExit(
                f"expected one mangled {stem} DLL, got {[path.name for path in matches]!r}"
            )
        matched_vendored.add(matches[0].name.casefold())
        vendored_by_stem[stem] = matches[0]
    unexpected_vendored = sorted(
        path.name for path in vendored_dlls
        if path.name.casefold() not in matched_vendored
    )
    if unexpected_vendored or len(vendored_dlls) != len(expected_vendored):
        raise SystemExit(f"unexpected vendored DLLs: {unexpected_vendored!r}")
    if any(path.name.casefold().startswith("vcruntime140") for path in vendored_dlls):
        raise SystemExit("MSVC platform runtime was unexpectedly vendored")
    api_crt = {
        "api-ms-win-crt-convert-l1-1-0.dll",
        "api-ms-win-crt-environment-l1-1-0.dll",
        "api-ms-win-crt-filesystem-l1-1-0.dll",
        "api-ms-win-crt-heap-l1-1-0.dll",
        "api-ms-win-crt-locale-l1-1-0.dll",
        "api-ms-win-crt-math-l1-1-0.dll",
        "api-ms-win-crt-runtime-l1-1-0.dll",
        "api-ms-win-crt-stdio-l1-1-0.dll",
        "api-ms-win-crt-string-l1-1-0.dll",
        "api-ms-win-crt-time-l1-1-0.dll",
        "api-ms-win-crt-utility-l1-1-0.dll",
    }
    expected_direct = {
        expected_extension: expected_ignored | matched_vendored,
        vendored_by_stem["concrt140"]: {
            "api-ms-win-crt-heap-l1-1-0.dll",
            "api-ms-win-crt-math-l1-1-0.dll",
            "api-ms-win-crt-runtime-l1-1-0.dll",
            "api-ms-win-crt-stdio-l1-1-0.dll",
            "api-ms-win-crt-string-l1-1-0.dll",
            "kernel32.dll",
            "vcruntime140.dll",
            "vcruntime140_1.dll",
            expected_vendored["msvcp140"],
        },
        vendored_by_stem["mpir"]: {
            "api-ms-win-crt-convert-l1-1-0.dll",
            "api-ms-win-crt-heap-l1-1-0.dll",
            "api-ms-win-crt-locale-l1-1-0.dll",
            "api-ms-win-crt-runtime-l1-1-0.dll",
            "api-ms-win-crt-stdio-l1-1-0.dll",
            "api-ms-win-crt-string-l1-1-0.dll",
            "kernel32.dll",
            "vcruntime140.dll",
            expected_vendored["msvcp140"],
        },
        vendored_by_stem["msvcp140"]: api_crt | {
            "kernel32.dll",
            "vcruntime140.dll",
            "vcruntime140_1.dll",
        },
    }
    for binary, expected_dependencies in expected_direct.items():
        direct_dependencies = {
            name.casefold() for name in _dll_utils.get_direct_needed(str(binary))
        }
        if direct_dependencies != expected_dependencies:
            raise SystemExit(
                f"unexpected direct import graph for "
                f"{binary.relative_to(root).as_posix()!r}: "
                f"{sorted(direct_dependencies)!r}"
            )
    unresolved = {}
    external = {}
    observed_ignored = set()
    observed_discovered_vendored = set()
    for binary in binaries:
        discovered, associated, ignored, not_found = _dll_utils.get_all_needed(
            str(binary), excluded_runtime, wheel_dirs, "ignore", False, False
        )
        if not_found:
            unresolved[binary.relative_to(root).as_posix()] = sorted(not_found)
        if associated:
            raise SystemExit(
                f"unexpected native associated files for "
                f"{binary.relative_to(root).as_posix()!r}: {sorted(associated)!r}"
            )
        observed_ignored.update(name.casefold() for name in ignored)
        for dependency in sorted(discovered):
            resolved_dependency = pathlib.Path(dependency).resolve(strict=True)
            if resolved_dependency.is_relative_to(root):
                if resolved_dependency.parent == vendored_directory:
                    observed_discovered_vendored.add(resolved_dependency.name.casefold())
                continue
            external.setdefault(binary.relative_to(root).as_posix(), []).append(
                str(resolved_dependency)
            )
    if unresolved:
        raise SystemExit(f"unresolved native dependencies: {unresolved!r}")
    if external:
        raise SystemExit(f"unvendored native dependencies: {external!r}")
    if observed_ignored != expected_ignored:
        raise SystemExit(
            "unexpected target-provided native dependency set: "
            f"{sorted(observed_ignored)!r}"
        )
    if observed_discovered_vendored != matched_vendored:
        raise SystemExit(
            "unexpected discovered vendored DLL set: "
            f"{sorted(observed_discovered_vendored)!r}"
        )
print(
    "verified repaired native dependency policy: "
    f"{len(binaries)} binaries; vendored={len(vendored_dlls)}; "
    f"target-provided={len(observed_ignored)}"
)
'@
$nativeDependencyArguments = Get-ControlledPythonArguments $nativeDependencyProbe @(
    $wheel.FullName,
    $Expected.DelvewheelVersion,
    $repairedWheelSha256BeforeAudit,
    $Expected.MangledConcrt140Name,
    $Expected.MangledMsvcp140Name,
    $Expected.MangledMpirName
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
import os
import pathlib
import re
import sys
import sysconfig

site_packages = pathlib.Path(sysconfig.get_paths()["purelib"]).resolve(strict=True)
package_directory = (site_packages / "pytetwild").resolve(strict=True)
package_init = (package_directory / "__init__.py").resolve(strict=True)
libs_directory = (site_packages / "pytetwild.libs").resolve(strict=True)
numpy_libs_directory = (site_packages / "numpy.libs").resolve(strict=True)
if not package_directory.is_relative_to(site_packages):
    raise SystemExit(f"pytetwild package escaped isolated site-packages: {package_directory}")
if not libs_directory.is_relative_to(site_packages) or not libs_directory.is_dir():
    raise SystemExit(f"vendored DLL directory escaped isolated site-packages: {libs_directory}")
if not numpy_libs_directory.is_relative_to(site_packages) or not numpy_libs_directory.is_dir():
    raise SystemExit(f"NumPy DLL directory escaped isolated site-packages: {numpy_libs_directory}")

metadata_files = list(site_packages.glob("pytetwild-0.3.0.dist-info/DELVEWHEEL"))
if len(metadata_files) != 1:
    raise SystemExit(f"expected one installed DELVEWHEEL metadata file, got {len(metadata_files)}")
metadata_lines = metadata_files[0].read_text(encoding="utf-8").splitlines()
if not metadata_lines or metadata_lines[0] != "Version: 1.12.1":
    raise SystemExit("installed DELVEWHEEL metadata version mismatch")

init_text = package_init.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
start_marker = "# start delvewheel patch"
end_marker = "# end delvewheel patch"
if init_text.count(start_marker) != 1 or init_text.count(end_marker) != 1:
    raise SystemExit("delvewheel add_dll_directory patch markers are missing or duplicated")
patch_start = init_text.index(start_marker)
patch_end = init_text.index(end_marker) + len(end_marker)
expected_patch = """# start delvewheel patch
def _delvewheel_patch_1_12_1():
    import os
    if os.path.isdir(libs_dir := os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'pytetwild.libs'))):
        os.add_dll_directory(libs_dir)


_delvewheel_patch_1_12_1()
del _delvewheel_patch_1_12_1
# end delvewheel patch"""
if init_text[patch_start:patch_end] != expected_patch:
    raise SystemExit("unexpected delvewheel 1.12.1 add_dll_directory patch")
if init_text.count("os.add_dll_directory") != 1:
    raise SystemExit("unexpected add_dll_directory call count in delvewheel patch")
import_statement = "from .pytetwild import"
if import_statement not in init_text or patch_start >= init_text.index(import_statement):
    raise SystemExit("delvewheel patch does not precede the native package import")
if "LoadLibraryExW" in init_text or ".load-order-" in init_text:
    raise SystemExit("unexpected legacy delvewheel load-order patch")
load_orders = list(site_packages.rglob(".load-order-*"))
if load_orders:
    raise SystemExit(f"unexpected delvewheel load-order files: {load_orders!r}")

vendored_dlls = sorted(libs_directory.glob("*.dll"))
expected_vendored = {
    "concrt140": sys.argv[1].casefold(),
    "msvcp140": sys.argv[2].casefold(),
    "mpir": sys.argv[3].casefold(),
}
if len(vendored_dlls) != len(expected_vendored):
    raise SystemExit(f"unexpected vendored DLL count: {[path.name for path in vendored_dlls]!r}")
for stem, expected_name in expected_vendored.items():
    pattern = re.compile(rf"{re.escape(stem)}-[0-9a-f]{{32}}\.dll", re.IGNORECASE)
    if pattern.fullmatch(expected_name) is None:
        raise SystemExit(f"unsafe expected mangled DLL name: {expected_name!r}")
actual_vendored_names = {path.name.casefold() for path in vendored_dlls}
if actual_vendored_names != set(expected_vendored.values()):
    raise SystemExit(
        f"unexpected vendored DLL set: {sorted(actual_vendored_names)!r}"
    )
if any(path.name.casefold().startswith("vcruntime140") for path in vendored_dlls):
    raise SystemExit("MSVC platform runtime was unexpectedly vendored")

add_dll_directory_events = []
def audit_hook(event, arguments):
    if event == "os.add_dll_directory":
        add_dll_directory_events.append(arguments)
sys.addaudithook(audit_hook)

import pytetwild
from pytetwild import PyfTetWildWrapper as native

if any(len(arguments) != 1 for arguments in add_dll_directory_events):
    raise SystemExit(
        f"malformed os.add_dll_directory audit events: {add_dll_directory_events!r}"
    )
audited_dll_directories = [
    pathlib.Path(arguments[0]).resolve(strict=True)
    for arguments in add_dll_directory_events
]
expected_audited_directories = [libs_directory, numpy_libs_directory]
if [os.path.normcase(str(path)) for path in audited_dll_directories] != [
    os.path.normcase(str(path)) for path in expected_audited_directories
]:
    raise SystemExit(
        f"os.add_dll_directory targeted unexpected paths: {audited_dll_directories!r}"
    )

package_path = pathlib.Path(pytetwild.__file__).resolve()
native_path = pathlib.Path(native.__file__).resolve()
expected_native_path = (package_directory / "PyfTetWildWrapper.pyd").resolve(strict=True)
if package_path != package_init:
    raise SystemExit(f"pytetwild loaded from an unexpected path: {package_path}")
if native_path != expected_native_path:
    raise SystemExit(f"native extension loaded from an unexpected path: {native_path}")
if pytetwild.__version__ != "0.3.0" or importlib.metadata.version("pytetwild") != "0.3.0":
    raise SystemExit("unexpected pytetwild package version")
if not callable(pytetwild.tetrahedralize):
    raise SystemExit("pytetwild.tetrahedralize is unavailable")
if not callable(native.tetrahedralize_mesh):
    raise SystemExit("native tetrahedralize_mesh is unavailable")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleFileNameW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_uint32,
]
kernel32.GetModuleFileNameW.restype = ctypes.c_uint32
def loaded_module_path(name):
    handle = kernel32.GetModuleHandleW(name)
    if not handle:
        raise SystemExit(f"required native module is not loaded: {name}")
    loaded_path_buffer = ctypes.create_unicode_buffer(32768)
    loaded_path_length = kernel32.GetModuleFileNameW(
        handle,
        loaded_path_buffer,
        len(loaded_path_buffer),
    )
    if loaded_path_length == 0 or loaded_path_length >= len(loaded_path_buffer) - 1:
        raise SystemExit(f"unable to resolve loaded native module path: {name}")
    return pathlib.Path(loaded_path_buffer.value).resolve(strict=True)

for expected_path in vendored_dlls:
    loaded_path = loaded_module_path(expected_path.name)
    if os.path.normcase(str(loaded_path)) != os.path.normcase(str(expected_path.resolve())):
        raise SystemExit(
            f"vendored DLL loaded from the wrong path: {expected_path.name}: {loaded_path}"
        )

base_python_directory = pathlib.Path(sys.base_prefix).resolve(strict=True)
for runtime_name in ("python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
    expected_runtime_path = (base_python_directory / runtime_name).resolve(strict=True)
    loaded_path = loaded_module_path(runtime_name)
    if os.path.normcase(str(loaded_path)) != os.path.normcase(str(expected_runtime_path)):
        raise SystemExit(
            f"Python host runtime loaded from the wrong path: {runtime_name}: {loaded_path}"
        )
print(
    f"normal package import passed: {package_path.name}; "
    f"vendored DLLs: {len(vendored_dlls)}; add_dll_directory patch: passed"
)
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
        $nativeProbeArguments = Get-ControlledPythonArguments $nativeProbe @(
            $Expected.MangledConcrt140Name,
            $Expected.MangledMsvcp140Name,
            $Expected.MangledMpirName
        )
        Invoke-CheckedLogged $NativePython $nativeProbeArguments `
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
Assert-Sha256 $MpirDll $Expected.MpirDllSha256
foreach ($binding in $PinnedPythonRuntimeFiles.GetEnumerator()) {
    Assert-Sha256 (Join-Path $PythonBaseDirectory $binding.Key) $binding.Value
}
foreach ($binding in $PinnedCrtFiles.GetEnumerator()) {
    $runtimePath = Join-Path $PinnedCrtDirectory $binding.Key
    Assert-Sha256 $runtimePath $binding.Value
    $runtimeItem = Get-Item -LiteralPath $runtimePath -Force -ErrorAction Stop
    if (
        [string]$runtimeItem.VersionInfo.FileVersion -cne
            $Expected.MsvcRedistributableFileVersion -or
        [string]$runtimeItem.VersionInfo.ProductVersion -cne
            $Expected.MsvcRedistributableFileVersion
    ) {
        throw "Pinned MSVC redistributable changed during the build: $runtimePath"
    }
}
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
        vendored_dll_runtime_load = 'passed'
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
