[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$Root,
    [switch]$RequireManifest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop

$rootItem = Get-Item -LiteralPath $Root -ErrorAction Stop
if (-not $rootItem.PSIsContainer) {
    throw "Public-tree audit root is not a directory: $Root"
}

$rootPath = $rootItem.FullName.TrimEnd([char[]]"\/")
$rootPrefix = $rootPath + [System.IO.Path]::DirectorySeparatorChar
$violations = [System.Collections.Generic.List[string]]::new()

# Assemble sensitive tokens from fragments.  This keeps the auditor from
# reporting its own source file while still checking every other staged text
# file without exemptions.
$userDirectoryBackslash = "C:" + [char]92 + ("Us" + "ers")
$userDirectorySlash = "C:/" + ("Us" + "ers")
$documentsWorkspaceBackslash = (
    ("Docu" + "ments") + [char]92 + ("Co" + "dex")
)
$documentsWorkspaceSlash = (
    ("Docu" + "ments") + "/" + ("Co" + "dex")
)

$contentAndPathTokens = @(
    $userDirectoryBackslash,
    $userDirectorySlash,
    ("pd" + "cko"),
    ("PDF" + "um"),
    $documentsWorkspaceBackslash,
    $documentsWorkspaceSlash,
    ("e7955e4d-" + "0b3f-4426-b8ca-55541d68fa35"),
    ("a51af255-" + "cc63-41e6-9af6-fba819754b9f"),
    ("7de55bf4-" + "44e1-4f2d-b6ce-b220f5dfd03d"),
    ("6de9aab9-" + "6b48-4e32-826a-d0619308cf95")
)

# These are forbidden as staged file or directory names.  They may still be
# discussed in the provenance, legal, state, or ignore documentation.
$pathOnlyTokens = @(
    ("Down" + "loads"),
    ("recovered" + "_pyc"),
    ("original" + "_icon_source"),
    ("validation" + "_output"),
    ("real_model" + "_validation")
)

$forbiddenExtensions = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($extension in @(
    ".exe", ".pyc", ".3mf", ".stl", ".mp4", ".mov", ".webm"
)) {
    [void]$forbiddenExtensions.Add($extension)
}

$explicitlyAllowedBinaryExtensions = (
    [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
)
foreach ($extension in @(".ico", ".png", ".npz", ".sqlite")) {
    [void]$explicitlyAllowedBinaryExtensions.Add($extension)
}

$textExtensions = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($extension in @(
    "", ".bat", ".cfg", ".cmd", ".css", ".csv", ".gitattributes",
    ".gitignore", ".html", ".ini", ".js", ".json", ".md", ".obj",
    ".ps1", ".psd1", ".psm1", ".py", ".pyi", ".rst", ".spec",
    ".toml", ".ts", ".txt", ".xml", ".yaml", ".yml"
)) {
    [void]$textExtensions.Add($extension)
}

function Get-AuditRelativePath {
    param([Parameter(Mandatory = $true)][string]$FullName)

    if (-not $FullName.StartsWith(
        $rootPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Audited item escaped the requested root: $FullName"
    }
    return $FullName.Substring($rootPrefix.Length).Replace("\", "/")
}

function Find-InsensitiveToken {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string[]]$Tokens
    )

    foreach ($token in $Tokens) {
        if ($Value.IndexOf(
            $token,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -ge 0) {
            return $token
        }
    }
    return $null
}

$items = @(Get-ChildItem -LiteralPath $rootPath -Recurse -Force)
foreach ($item in $items) {
    $relative = Get-AuditRelativePath -FullName $item.FullName

    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        $violations.Add("reparse point is not allowed: $relative")
        continue
    }

    $pathToken = Find-InsensitiveToken `
        -Value $relative `
        -Tokens ([string[]]($contentAndPathTokens + $pathOnlyTokens))
    if ($null -ne $pathToken) {
        $violations.Add("forbidden path token '$pathToken': $relative")
    }

    if ($item.PSIsContainer) {
        continue
    }

    $extension = [System.IO.Path]::GetExtension($item.Name)
    if ($forbiddenExtensions.Contains($extension)) {
        $violations.Add("forbidden file extension '$extension': $relative")
    }

    if ($extension.Equals(".obj", [System.StringComparison]::OrdinalIgnoreCase)) {
        $sampleObject = $relative.StartsWith(
            "samples/",
            [System.StringComparison]::OrdinalIgnoreCase
        )
        $syntheticTestObject = $relative.Equals(
            "source/fixed_app/test_tetra.obj",
            [System.StringComparison]::OrdinalIgnoreCase
        )
        if (-not $sampleObject -and -not $syntheticTestObject) {
            $violations.Add("OBJ is outside the approved sample/test paths: $relative")
        }
    }

    if ($explicitlyAllowedBinaryExtensions.Contains($extension)) {
        continue
    }
    if (-not $textExtensions.Contains($extension)) {
        continue
    }

    try {
        $content = [System.IO.File]::ReadAllText($item.FullName)
    }
    catch {
        $violations.Add("text file could not be read: $relative ($($_.Exception.Message))")
        continue
    }

    $contentToken = Find-InsensitiveToken `
        -Value $content `
        -Tokens ([string[]]$contentAndPathTokens)
    if ($null -ne $contentToken) {
        $violations.Add("forbidden text token '$contentToken': $relative")
    }
}

# The first staging pass intentionally runs before the manifest exists.  Once
# SOURCE_MANIFEST_SHA256.txt is present, treat it as a strict relative-path
# inventory rather than merely another text file.  This makes a later audit
# detect hand edits, omitted files, injected files, duplicate paths, and path
# traversal instead of only re-running the privacy/extension checks above.
$manifestName = "SOURCE_MANIFEST_SHA256.txt"
$manifestPath = Join-Path $rootPath $manifestName
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    $actualFiles = @{}
    foreach ($file in @($items | Where-Object { -not $_.PSIsContainer })) {
        $relative = Get-AuditRelativePath -FullName $file.FullName
        if ($relative.Equals(
            $manifestName,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            continue
        }
        $actualFiles[$relative] = $file.FullName
    }

    $manifestEntries = @{}
    $manifestLines = [System.IO.File]::ReadAllLines($manifestPath)
    for ($lineIndex = 0; $lineIndex -lt $manifestLines.Length; $lineIndex++) {
        $lineNumber = $lineIndex + 1
        $line = $manifestLines[$lineIndex]
        $match = [System.Text.RegularExpressions.Regex]::Match(
            $line,
            "^(?<hash>[0-9A-Fa-f]{64})  (?<path>.+)$"
        )
        if (-not $match.Success) {
            $violations.Add(
                "manifest syntax error at line ${lineNumber}: expected 64 hex characters, two spaces, and a relative path"
            )
            continue
        }

        $expectedHash = $match.Groups["hash"].Value.ToUpperInvariant()
        $relative = $match.Groups["path"].Value
        $segments = @($relative -split "/")
        $invalidSegment = @(
            $segments | Where-Object { $_ -eq "" -or $_ -eq "." -or $_ -eq ".." }
        ).Count -gt 0
        if (
            $relative.Contains("\") -or
            [System.IO.Path]::IsPathRooted($relative) -or
            $invalidSegment
        ) {
            $violations.Add(
                "manifest path is not a normalized forward-slash relative path at line ${lineNumber}: $relative"
            )
            continue
        }
        if ($relative.Equals(
            $manifestName,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            $violations.Add("manifest must not list itself at line ${lineNumber}")
            continue
        }

        try {
            $resolvedEntry = [System.IO.Path]::GetFullPath(
                (Join-Path $rootPath $relative.Replace("/", "\"))
            )
        }
        catch {
            $violations.Add(
                "manifest path could not be resolved at line ${lineNumber}: $relative"
            )
            continue
        }
        if (-not $resolvedEntry.StartsWith(
            $rootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            $violations.Add("manifest path escapes the audited root: $relative")
            continue
        }
        if ($manifestEntries.ContainsKey($relative)) {
            $violations.Add("duplicate manifest path at line ${lineNumber}: $relative")
            continue
        }
        $manifestEntries[$relative] = $expectedHash
    }

    foreach ($relative in @($actualFiles.Keys | Sort-Object)) {
        if (-not $manifestEntries.ContainsKey($relative)) {
            $violations.Add("file is missing from manifest: $relative")
        }
    }
    foreach ($relative in @($manifestEntries.Keys | Sort-Object)) {
        if (-not $actualFiles.ContainsKey($relative)) {
            $violations.Add("manifest lists a missing file: $relative")
            continue
        }
        try {
            $actualHash = (
                Get-FileHash `
                    -LiteralPath $actualFiles[$relative] `
                    -Algorithm SHA256
            ).Hash.ToUpperInvariant()
        }
        catch {
            $violations.Add(
                "manifest file could not be hashed: $relative ($($_.Exception.Message))"
            )
            continue
        }
        if ($actualHash -ne $manifestEntries[$relative]) {
            $violations.Add("manifest hash mismatch: $relative")
        }
    }
}
elseif ($RequireManifest) {
    $violations.Add("required source manifest is missing: $manifestName")
}

if ($violations.Count -gt 0) {
    $details = @(
        $violations | Sort-Object -Unique | ForEach-Object { " - $_" }
    )
    throw (
        "Public-tree audit failed with $($details.Count) violation(s):" +
        [Environment]::NewLine +
        ($details -join [Environment]::NewLine)
    )
}

$fileCount = @($items | Where-Object { -not $_.PSIsContainer }).Count
Write-Host "Public-tree audit passed: $fileCount files under $rootPath"
