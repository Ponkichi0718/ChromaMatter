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

# Generic workstation-path fragments are always rejected.  Operator-specific
# identifiers must be supplied outside Git through the optional, semicolon-
# delimited CHROMAMATTER_PRIVATE_AUDIT_TOKENS process environment variable.
# Keeping those values out of this source prevents the denylist itself from
# publishing the private identifiers it is intended to catch.
$userDirectoryBackslash = "C:" + [char]92 + ("Us" + "ers")
$userDirectorySlash = "C:/" + ("Us" + "ers")
$documentsWorkspaceBackslash = (
    ("Docu" + "ments") + [char]92 + ("Co" + "dex")
)
$documentsWorkspaceSlash = (
    ("Docu" + "ments") + "/" + ("Co" + "dex")
)

function Get-ConfiguredPrivateAuditTokens {
    $variableName = "CHROMAMATTER_PRIVATE_AUDIT_TOKENS"
    $rawValue = [Environment]::GetEnvironmentVariable($variableName, "Process")
    if ([string]::IsNullOrWhiteSpace($rawValue)) {
        return [string[]]@()
    }

    $tokens = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $segments = $rawValue.Split([char]";")
    for ($index = 0; $index -lt $segments.Length; $index++) {
        $token = $segments[$index].Trim()
        if ($token.Length -eq 0) {
            throw (
                "$variableName contains an empty token at position " +
                "$($index + 1). Remove duplicate or trailing separators."
            )
        }
        if ($token.Length -lt 3 -or $token.Length -gt 512) {
            throw "$variableName tokens must contain between 3 and 512 characters."
        }
        foreach ($character in $token.ToCharArray()) {
            if ([char]::IsControl($character)) {
                throw "$variableName tokens must not contain control characters."
            }
        }
        if ($seen.Add($token)) {
            $tokens.Add($token)
        }
    }
    return [string[]]$tokens.ToArray()
}

$configuredPrivateAuditTokens = @(Get-ConfiguredPrivateAuditTokens)

$contentAndPathTokens = @(
    $userDirectoryBackslash,
    $userDirectorySlash,
    $documentsWorkspaceBackslash,
    $documentsWorkspaceSlash
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
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Tokens
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

function Get-AuditDisplayPath {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)

    $configuredToken = Find-InsensitiveToken `
        -Value $Value `
        -Tokens ([string[]]$configuredPrivateAuditTokens)
    if ($null -ne $configuredToken) {
        return "<redacted-path>"
    }
    return $Value
}

$items = @(Get-ChildItem -LiteralPath $rootPath -Recurse -Force)
foreach ($item in $items) {
    $relative = Get-AuditRelativePath -FullName $item.FullName
    $configuredPathToken = Find-InsensitiveToken `
        -Value $relative `
        -Tokens ([string[]]$configuredPrivateAuditTokens)
    $displayRelative = Get-AuditDisplayPath -Value $relative

    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        $violations.Add("reparse point is not allowed: $displayRelative")
        continue
    }

    $pathToken = Find-InsensitiveToken `
        -Value $relative `
        -Tokens ([string[]]($contentAndPathTokens + $pathOnlyTokens))
    if ($null -ne $pathToken) {
        $violations.Add("forbidden path token '$pathToken': $displayRelative")
    }
    if ($null -ne $configuredPathToken) {
        $violations.Add(
            "forbidden configured private token in path: $displayRelative"
        )
    }

    if ($item.PSIsContainer) {
        continue
    }

    $extension = [System.IO.Path]::GetExtension($item.Name)
    if ($forbiddenExtensions.Contains($extension)) {
        $violations.Add("forbidden file extension '$extension': $displayRelative")
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
            $violations.Add(
                "OBJ is outside the approved sample/test paths: $displayRelative"
            )
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
        $readFailure = if ($displayRelative -eq "<redacted-path>") {
            "text file could not be read: $displayRelative"
        }
        else {
            "text file could not be read: $displayRelative ($($_.Exception.Message))"
        }
        $violations.Add($readFailure)
        continue
    }

    $contentToken = Find-InsensitiveToken `
        -Value $content `
        -Tokens ([string[]]$contentAndPathTokens)
    if ($null -ne $contentToken) {
        $violations.Add("forbidden text token '$contentToken': $displayRelative")
    }
    $configuredContentToken = Find-InsensitiveToken `
        -Value $content `
        -Tokens ([string[]]$configuredPrivateAuditTokens)
    if ($null -ne $configuredContentToken) {
        $violations.Add(
            "forbidden configured private text token: $displayRelative"
        )
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
        $displayRelative = Get-AuditDisplayPath -Value $relative
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
                "manifest path is not a normalized forward-slash relative path at line ${lineNumber}: $displayRelative"
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
                "manifest path could not be resolved at line ${lineNumber}: $displayRelative"
            )
            continue
        }
        if (-not $resolvedEntry.StartsWith(
            $rootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            $violations.Add(
                "manifest path escapes the audited root: $displayRelative"
            )
            continue
        }
        if ($manifestEntries.ContainsKey($relative)) {
            $violations.Add(
                "duplicate manifest path at line ${lineNumber}: $displayRelative"
            )
            continue
        }
        $manifestEntries[$relative] = $expectedHash
    }

    foreach ($relative in @($actualFiles.Keys | Sort-Object)) {
        if (-not $manifestEntries.ContainsKey($relative)) {
            $displayRelative = Get-AuditDisplayPath -Value $relative
            $violations.Add("file is missing from manifest: $displayRelative")
        }
    }
    foreach ($relative in @($manifestEntries.Keys | Sort-Object)) {
        $displayRelative = Get-AuditDisplayPath -Value $relative
        if (-not $actualFiles.ContainsKey($relative)) {
            $violations.Add("manifest lists a missing file: $displayRelative")
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
            $hashFailure = if ($displayRelative -eq "<redacted-path>") {
                "manifest file could not be hashed: $displayRelative"
            }
            else {
                "manifest file could not be hashed: $displayRelative ($($_.Exception.Message))"
            }
            $violations.Add($hashFailure)
            continue
        }
        if ($actualHash -ne $manifestEntries[$relative]) {
            $violations.Add("manifest hash mismatch: $displayRelative")
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
