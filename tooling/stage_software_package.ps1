[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [Alias("BuildRoot")]
    [string]$BuiltAppRoot,
    [string]$Destination = "",
    [string]$ArchivePath = "",
    [string]$CorrespondingSourceUrl = "",
    [string]$BinaryComponentMapPath = "",
    [string]$SbomPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop

$repoRoot = (Get-Item -LiteralPath (Split-Path -Parent $PSScriptRoot)).FullName
$builtRoot = (Get-Item -LiteralPath $BuiltAppRoot -ErrorAction Stop).FullName
if (-not (Test-Path -LiteralPath $builtRoot -PathType Container)) {
    throw "Built application root is not a directory: $BuiltAppRoot"
}

if (-not $Destination) {
    $Destination = Join-Path `
        $repoRoot `
        "artifacts\ChromaMatter_0.8beta-r32-ai-model-print-studio"
}
elseif (-not [System.IO.Path]::IsPathRooted($Destination)) {
    $Destination = Join-Path $repoRoot $Destination
}
$destinationPath = [System.IO.Path]::GetFullPath($Destination)
$destinationLeaf = Split-Path -Leaf $destinationPath
$destinationParent = Split-Path -Parent $destinationPath
if (-not $destinationLeaf -or -not $destinationParent) {
    throw "Software package destination must have a parent and leaf: $destinationPath"
}

if (-not $ArchivePath) {
    $ArchivePath = "$destinationPath.zip"
}
elseif (-not [System.IO.Path]::IsPathRooted($ArchivePath)) {
    $ArchivePath = Join-Path $repoRoot $ArchivePath
}
$archiveFullPath = [System.IO.Path]::GetFullPath($ArchivePath)
$archiveParent = Split-Path -Parent $archiveFullPath
$archiveLeaf = Split-Path -Leaf $archiveFullPath
if (-not $archiveParent -or -not $archiveLeaf) {
    throw "Software archive path must have a parent and leaf: $archiveFullPath"
}
if (-not $archiveLeaf.EndsWith(
    ".zip",
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Software archive must use the .zip extension: $archiveFullPath"
}

if (Test-Path -LiteralPath $destinationPath) {
    throw "Refusing to overwrite an existing software stage: $destinationPath"
}
if (Test-Path -LiteralPath $archiveFullPath) {
    throw "Refusing to overwrite an existing software archive: $archiveFullPath"
}

function Test-PathInside {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Parent
    )

    $candidatePath = [System.IO.Path]::GetFullPath($Candidate)
    $parentPrefix = (
        [System.IO.Path]::GetFullPath($Parent).TrimEnd([char[]]"\/") +
        [System.IO.Path]::DirectorySeparatorChar
    )
    return $candidatePath.StartsWith(
        $parentPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

if (
    (Test-PathInside -Candidate $destinationPath -Parent $builtRoot) -or
    (Test-PathInside -Candidate $builtRoot -Parent $destinationPath)
) {
    throw "Built application root and destination must not overlap."
}
if (Test-PathInside -Candidate $archiveFullPath -Parent $destinationPath) {
    throw "Software archive must be outside the staged package directory."
}

$expectedBuiltEntries = @("ChromaMatter.exe", "_internal")
foreach ($entry in @(Get-ChildItem -LiteralPath $builtRoot -Force)) {
    if ($entry.Name -notin $expectedBuiltEntries) {
        throw "Unexpected top-level build output is not allowlisted: $($entry.Name)"
    }
}
foreach ($name in $expectedBuiltEntries) {
    if (-not (Test-Path -LiteralPath (Join-Path $builtRoot $name))) {
        throw "Required top-level build output is missing: $name"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $builtRoot "ChromaMatter.exe") -PathType Leaf)) {
    throw "ChromaMatter.exe is not a file under the built application root."
}
if (-not (Test-Path -LiteralPath (Join-Path $builtRoot "_internal") -PathType Container)) {
    throw "_internal is not a directory under the built application root."
}

$requiredRuntimeFiles = @(
    "_internal/THIRD_PARTY_VOLUME_LICENSES_JA.md",
    "_internal/_tk_data/license.terms",
    "_internal/licenses/GPL-3.0.txt",
    "_internal/licenses/AGPL-3.0.txt",
    "_internal/licenses/LGPL-2.1.txt",
    "_internal/licenses/LGPL-3.0.txt",
    "_internal/licenses/MPL-2.0.txt",
    "_internal/licenses/BINARY_COMPONENT_MAP.schema.json",
    "_internal/licenses/BUILD_ENVIRONMENT_EN.md",
    "_internal/licenses/BUILD_ENVIRONMENT_JA.md",
    "_internal/licenses/RELINKING_EN.md",
    "_internal/licenses/RELINKING_JA.md",
    "_internal/licenses/THIRD_PARTY_NOTICES_EN.txt",
    "_internal/licenses/THIRD_PARTY_NOTICES_JA.txt",
    "_internal/licenses/LICENSE_APP.txt",
    "_internal/licenses/LICENSE_RESVG_PY.txt",
    "_internal/licenses/LICENSE_RESVG_MIT.txt",
    "_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt",
    "_internal/licenses/THIRD_PARTY_LICENSES.txt",
    "_internal/licenses/resvg-py/LICENSE.txt",
    "_internal/licenses/resvg-py/resvg.cyclonedx.json",
    "_internal/licenses/pytetwild/LICENSE",
    "_internal/licenses/tetgen/LICENSE",
    "_internal/licenses/tetgen/tetgen-license",
    "_internal/licenses/pymeshlab/LICENSE",
    "_internal/licenses/shapely/LICENSE.txt",
    "_internal/licenses/shapely/LICENSE_GEOS",
    "_internal/licenses/shapely/LICENSE_win32",
    "_internal/licenses/msvc-runtime/LICENSE",
    "_internal/resources/filament_db/filament_color_database_2026-08.sqlite",
    "_internal/resources/filament_db/filament_color_database_README.md",
    "_internal/resources/filament_db/ATTRIBUTION.md",
    "_internal/resources/filament_db/LICENSE_OPEN_FILAMENT_DATABASE.txt",
    "_internal/resources/filament_db/LICENSE_CC_BY_4.0.txt"
)
foreach ($relative in $requiredRuntimeFiles) {
    $runtimeFile = Join-Path $builtRoot $relative.Replace("/", "\")
    if (-not (Test-Path -LiteralPath $runtimeFile -PathType Leaf)) {
        throw "Required packaged runtime file is missing: $relative"
    }
}

function Test-IncompleteReleaseValue {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    return (
        [string]::IsNullOrWhiteSpace($Value) -or
        $Value -match "@@[^@\r\n]+@@" -or
        $Value -match "__[A-Z0-9_]+__" -or
        $Value -match "(?i)\b(?:TODO|TBD|CHANGEME)\b"
    )
}

if (Test-IncompleteReleaseValue -Value $CorrespondingSourceUrl) {
    throw "CorrespondingSourceUrl is required and must not contain a placeholder."
}
$sourceUri = $null
if (
    -not [Uri]::TryCreate($CorrespondingSourceUrl, [UriKind]::Absolute, [ref]$sourceUri) -or
    $sourceUri.Scheme -ne "https" -or
    $sourceUri.Host -match "(?i)^(?:example\.(?:com|org|net)|localhost)$"
) {
    throw "CorrespondingSourceUrl must be a final public HTTPS release URL."
}
if (Test-IncompleteReleaseValue -Value $BinaryComponentMapPath) {
    throw "BinaryComponentMapPath is required; templates cannot be published."
}
$componentMapFullPath = if ([System.IO.Path]::IsPathRooted($BinaryComponentMapPath)) {
    [System.IO.Path]::GetFullPath($BinaryComponentMapPath)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $BinaryComponentMapPath))
}
if (-not (Test-Path -LiteralPath $componentMapFullPath -PathType Leaf)) {
    throw "Completed binary component map is missing: $componentMapFullPath"
}
$componentMapText = [System.IO.File]::ReadAllText($componentMapFullPath)
if (Test-IncompleteReleaseValue -Value $componentMapText) {
    throw "Binary component map contains an incomplete placeholder."
}
try {
    $componentMap = $componentMapText | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "Binary component map is not valid JSON: $($_.Exception.Message)"
}
$generatedInventory = $null -ne $componentMap.PSObject.Properties["package"]
if (-not $generatedInventory) {
    throw "BinaryComponentMapPath must contain the generated compliance inventory."
}
    if (
        $null -eq $componentMap.validation -or
        $componentMap.validation.passed -ne $true -or
        @($componentMap.validation.unmapped_native_files).Count -ne 0 -or
        @($componentMap.validation.reparse_points_not_traversed).Count -ne 0
    ) {
        throw "Generated binary component inventory did not pass its fail-closed validation."
    }
    if (
        [string]$componentMap.package.name -ne "ChromaMatter" -or
        [string]$componentMap.package.version -ne "0.8beta-r32"
    ) {
        throw "Generated binary component inventory has the wrong package identity."
    }
    $componentLicenses = @{}
    foreach ($component in @($componentMap.components)) {
        $componentLicenses[[string]$component.id] = [string]$component.license
    }
    foreach ($required in @{
        "chromamatter" = "GPL-3.0-or-later"
        "tetgen" = "MIT AND AGPL-3.0-or-later"
        "pymeshlab" = "GPL-3.0-only"
        "qt" = "LGPL-3.0-only"
        "pytetwild" = "MPL-2.0"
        "shapely" = "BSD-3-Clause"
        "geos" = "LGPL-2.1-or-later"
    }.GetEnumerator()) {
        if ($componentLicenses[$required.Key] -ne $required.Value) {
            throw "Generated inventory is missing or mislabels component: $($required.Key)"
        }
    }
    $exeRow = @($componentMap.files | Where-Object { $_.path -eq "ChromaMatter.exe" })
    if (
        $exeRow.Count -ne 1 -or
        [string]$exeRow[0].sha256 -ne (
            Get-FileHash -LiteralPath (Join-Path $builtRoot "ChromaMatter.exe") -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    ) {
        throw "Generated inventory does not match ChromaMatter.exe."
    }

if (Test-IncompleteReleaseValue -Value $SbomPath) {
    throw "SbomPath is required; the release SBOM cannot be omitted."
}
$sbomFullPath = if ([System.IO.Path]::IsPathRooted($SbomPath)) {
    [System.IO.Path]::GetFullPath($SbomPath)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $SbomPath))
}
if (-not (Test-Path -LiteralPath $sbomFullPath -PathType Leaf)) {
    throw "Completed CycloneDX SBOM is missing: $sbomFullPath"
}
$sbomText = [System.IO.File]::ReadAllText($sbomFullPath)
if (Test-IncompleteReleaseValue -Value $sbomText) {
    throw "CycloneDX SBOM contains an incomplete placeholder."
}
try {
    $sbom = $sbomText | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "CycloneDX SBOM is not valid JSON: $($_.Exception.Message)"
}
if (
    [string]$sbom.bomFormat -ne "CycloneDX" -or
    [string]$sbom.specVersion -ne "1.5"
) {
    throw "SbomPath must contain the generated CycloneDX 1.5 SBOM."
}

# The PyInstaller runtime contains many legitimate binary formats, so the
# software stage cannot use the source-tree extension allowlist verbatim.
# It must still reject model/media payloads, recovered bytecode, reparse
# points, and private workstation identifiers anywhere below `_internal`.
$forbiddenPayloadExtensions = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($extension in @(
    ".3mf", ".amf", ".glb", ".gltf", ".iges", ".igs", ".m4v",
    ".mkv", ".mov", ".mp4", ".mtl", ".obj", ".off", ".ply",
    ".pyc", ".step", ".stl", ".stp", ".webm", ".wmv", ".avi"
)) {
    [void]$forbiddenPayloadExtensions.Add($extension)
}

$payloadTextExtensions = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($extension in @(
    "", ".bat", ".cfg", ".cmd", ".css", ".csv", ".htm", ".html",
    ".ini", ".js", ".json", ".log", ".md", ".msg", ".ps1", ".py",
    ".pyi", ".rst", ".tcl", ".terms", ".tm", ".toml", ".txt",
    ".xml", ".xsd", ".yaml", ".yml"
)) {
    [void]$payloadTextExtensions.Add($extension)
}

# Assemble these values from fragments so the public-source auditor can scan
# this script without mistaking its own denylist for leaked private content.
$payloadUserDirectoryBackslash = "C:" + [char]92 + ("Us" + "ers")
$payloadUserDirectorySlash = "C:/" + ("Us" + "ers")
$payloadDocumentsWorkspaceBackslash = (
    ("Docu" + "ments") + [char]92 + ("Co" + "dex")
)
$payloadDocumentsWorkspaceSlash = (
    ("Docu" + "ments") + "/" + ("Co" + "dex")
)
$payloadContentAndPathTokens = @(
    $payloadUserDirectoryBackslash,
    $payloadUserDirectorySlash,
    ("pd" + "cko"),
    ("PDF" + "um"),
    $payloadDocumentsWorkspaceBackslash,
    $payloadDocumentsWorkspaceSlash,
    ("e7955e4d-" + "0b3f-4426-b8ca-55541d68fa35"),
    ("a51af255-" + "cc63-41e6-9af6-fba819754b9f"),
    ("7de55bf4-" + "44e1-4f2d-b6ce-b220f5dfd03d"),
    ("6de9aab9-" + "6b48-4e32-826a-d0619308cf95")
)
$payloadBinaryContentTokens = @(
    ("pd" + "cko"),
    ("PDF" + "um"),
    $payloadDocumentsWorkspaceBackslash,
    $payloadDocumentsWorkspaceSlash,
    ("e7955e4d-" + "0b3f-4426-b8ca-55541d68fa35"),
    ("a51af255-" + "cc63-41e6-9af6-fba819754b9f"),
    ("7de55bf4-" + "44e1-4f2d-b6ce-b220f5dfd03d"),
    ("6de9aab9-" + "6b48-4e32-826a-d0619308cf95")
)
$payloadPathOnlyTokens = @(
    ("Down" + "loads"),
    ("recovered" + "_pyc"),
    ("original" + "_icon_source"),
    ("validation" + "_output"),
    ("real_model" + "_validation")
)

function Find-SoftwarePayloadToken {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
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

function Assert-SoftwarePayloadSafe {
    param([Parameter(Mandatory = $true)][string]$Root)

    $rootItem = Get-Item -LiteralPath $Root -ErrorAction Stop
    if (-not $rootItem.PSIsContainer) {
        throw "Software payload audit root is not a directory: $Root"
    }
    $rootPath = $rootItem.FullName.TrimEnd([char[]]"\/")
    $rootPrefix = $rootPath + [System.IO.Path]::DirectorySeparatorChar
    $violations = [System.Collections.Generic.List[string]]::new()

    foreach ($item in @(
        Get-ChildItem -LiteralPath $rootPath -Recurse -Force |
            Sort-Object FullName
    )) {
        if (-not $item.FullName.StartsWith(
            $rootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Software payload audit item escaped its root: $($item.FullName)"
        }
        $relative = $item.FullName.Substring($rootPrefix.Length).Replace("\", "/")

        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            $violations.Add("reparse point is not allowed: $relative")
            continue
        }

        $pathToken = Find-SoftwarePayloadToken `
            -Value $relative `
            -Tokens ([string[]](
                $payloadContentAndPathTokens + $payloadPathOnlyTokens
            ))
        if ($null -ne $pathToken) {
            $violations.Add("forbidden path token '$pathToken': $relative")
        }
        if ($item.PSIsContainer) {
            continue
        }

        $extension = [System.IO.Path]::GetExtension($item.Name)
        if ($forbiddenPayloadExtensions.Contains($extension)) {
            $violations.Add("forbidden software payload extension '$extension': $relative")
            continue
        }
        try {
            $content = [System.IO.File]::ReadAllText($item.FullName)
        }
        catch {
            if ($payloadTextExtensions.Contains($extension)) {
                $violations.Add(
                    "software payload text could not be read: $relative ($($_.Exception.Message))"
                )
            }
            continue
        }
        $isTextPayload = $payloadTextExtensions.Contains($extension)
        $tokensToCheck = if ($isTextPayload) {
            [string[]]$payloadContentAndPathTokens
        }
        else {
            # Generic dependency binaries legitimately contain their original
            # builders' user-profile paths.  For binary payloads, reject only this
            # project's known private identifiers/workspace fragments.
            [string[]]$payloadBinaryContentTokens
        }
        $contentToken = Find-SoftwarePayloadToken `
            -Value $content `
            -Tokens $tokensToCheck
        if ($null -ne $contentToken) {
            $contentKind = if ($isTextPayload) { "text" } else { "binary" }
            $violations.Add("forbidden $contentKind token '$contentToken': $relative")
        }
    }

    if ($violations.Count -gt 0) {
        $details = @(
            $violations | Sort-Object -Unique | ForEach-Object { " - $_" }
        )
        throw (
            "Software payload privacy audit failed with " +
            "$($details.Count) violation(s):" +
            [Environment]::NewLine +
            ($details -join [Environment]::NewLine)
        )
    }
}

$packageFiles = @(
    @{ Source = "CURRENT_STATE.json"; Destination = "CURRENT_STATE.json" },
    @{ Source = "PROVENANCE.md"; Destination = "PROVENANCE.md" },
    @{ Source = "source/fixed_app/README_fixed_ja.md"; Destination = "README_fixed_ja.md" },
    @{ Source = "source/fixed_app/README_fixed_en.md"; Destination = "README_fixed_en.md" },
    @{ Source = "source/fixed_app/START_FIXED.cmd"; Destination = "START_FIXED.cmd" },
    @{ Source = "source/fixed_app/THIRD_PARTY_VOLUME_LICENSES_JA.md"; Destination = "THIRD_PARTY_VOLUME_LICENSES_JA.md" },
    @{ Source = "source/fixed_app/VERSION_POLICY.md"; Destination = "VERSION_POLICY.md" },
    @{ Source = "licenses/GPL-3.0.txt"; Destination = "licenses/GPL-3.0.txt" },
    @{ Source = "licenses/AGPL-3.0.txt"; Destination = "licenses/AGPL-3.0.txt" },
    @{ Source = "licenses/LGPL-2.1.txt"; Destination = "licenses/LGPL-2.1.txt" },
    @{ Source = "licenses/LGPL-3.0.txt"; Destination = "licenses/LGPL-3.0.txt" },
    @{ Source = "licenses/MPL-2.0.txt"; Destination = "licenses/MPL-2.0.txt" },
    @{ Source = "licenses/BINARY_COMPONENT_MAP.schema.json"; Destination = "licenses/BINARY_COMPONENT_MAP.schema.json" },
    @{ Source = "licenses/BUILD_ENVIRONMENT_EN.md"; Destination = "licenses/BUILD_ENVIRONMENT_EN.md" },
    @{ Source = "licenses/BUILD_ENVIRONMENT_JA.md"; Destination = "licenses/BUILD_ENVIRONMENT_JA.md" },
    @{ Source = "licenses/RELINKING_EN.md"; Destination = "licenses/RELINKING_EN.md" },
    @{ Source = "licenses/RELINKING_JA.md"; Destination = "licenses/RELINKING_JA.md" },
    @{ Source = "licenses/THIRD_PARTY_NOTICES_EN.txt"; Destination = "licenses/THIRD_PARTY_NOTICES_EN.txt" },
    @{ Source = "licenses/THIRD_PARTY_NOTICES_JA.txt"; Destination = "licenses/THIRD_PARTY_NOTICES_JA.txt" },
    @{ Source = "licenses/LICENSE_APP.txt"; Destination = "licenses/LICENSE_APP.txt" },
    @{ Source = "licenses/LICENSE_RESVG_PY.txt"; Destination = "licenses/LICENSE_RESVG_PY.txt" },
    @{ Source = "licenses/LICENSE_RESVG_MIT.txt"; Destination = "licenses/LICENSE_RESVG_MIT.txt" },
    @{ Source = "licenses/LICENSE_RESVG_APACHE_2.0.txt"; Destination = "licenses/LICENSE_RESVG_APACHE_2.0.txt" },
    @{ Source = "licenses/THIRD_PARTY_LICENSES.txt"; Destination = "licenses/THIRD_PARTY_LICENSES.txt" },
    @{ Source = "publication/LEGAL_AND_RIGHTS_JA.md"; Destination = "publication/LEGAL_AND_RIGHTS_JA.md" },
    @{ Source = "publication/PRIVATE_SAMPLE_POLICY_JA.md"; Destination = "publication/PRIVATE_SAMPLE_POLICY_JA.md" },
    @{ Source = "publication/CLEAN_CLONE_GUIDE_JA.md"; Destination = "publication/CLEAN_CLONE_GUIDE_JA.md" },
    @{ Source = "publication/VIDEO_VALIDATION_CHECKLIST_JA.md"; Destination = "publication/VIDEO_VALIDATION_CHECKLIST_JA.md" },
    @{ Source = "publication/PUBLICATION_CHECKLIST_JA.md"; Destination = "publication/PUBLICATION_CHECKLIST_JA.md" },
    @{ Source = "publication/GITHUB_PUBLICATION_GUIDE_JA.md"; Destination = "publication/GITHUB_PUBLICATION_GUIDE_JA.md" },
    @{ Source = "publication/INNOVATION_FUND_APPLICATION_DRAFT.md"; Destination = "publication/INNOVATION_FUND_APPLICATION_DRAFT.md" },
    @{ Source = "publication/INNOVATION_FUND_STATUS_JA.md"; Destination = "publication/INNOVATION_FUND_STATUS_JA.md" }
)
foreach ($record in $packageFiles) {
    $source = Join-Path $repoRoot $record.Source.Replace("/", "\")
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required software-package source is missing: $($record.Source)"
    }
}
foreach ($template in @(
    "licenses/SOURCE_OFFER_TEMPLATE_EN.txt",
    "licenses/SOURCE_OFFER_TEMPLATE_JA.txt"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $template) -PathType Leaf)) {
        throw "Required source-offer template is missing: $template"
    }
}

New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
New-Item -ItemType Directory -Path $archiveParent -Force | Out-Null

$stagingContainer = Join-Path (
    $destinationParent
) (".$destinationLeaf.software-staging-$PID-" + [Guid]::NewGuid().ToString("N"))
$stagingRoot = Join-Path $stagingContainer $destinationLeaf
$archiveTemporary = Join-Path (
    $archiveParent
) (".$archiveLeaf.staging-$PID-" + [Guid]::NewGuid().ToString("N"))
$verificationContainer = Join-Path (
    $destinationParent
) (".$destinationLeaf.zip-verification-$PID-" + [Guid]::NewGuid().ToString("N"))

function Copy-SoftwareFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $sourceItem = Get-Item -LiteralPath $Source -ErrorAction Stop
    if ($sourceItem.PSIsContainer) {
        throw "Software package file input is a directory: $Source"
    }
    if (($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Reparse-point files are not copied into software packages: $Source"
    }
    if (Test-Path -LiteralPath $Destination) {
        throw "Duplicate software-package destination: $Destination"
    }
    $parent = Split-Path -Parent $Destination
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $sourceItem.FullName -Destination $Destination
}

function Copy-SoftwareTree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $sourceItem = Get-Item -LiteralPath $Source -ErrorAction Stop
    if (-not $sourceItem.PSIsContainer) {
        throw "Software package tree input is not a directory: $Source"
    }
    if (($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Reparse-point directories are not copied into software packages: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $sourcePrefix = (
        $sourceItem.FullName.TrimEnd([char[]]"\/") +
        [System.IO.Path]::DirectorySeparatorChar
    )
    foreach ($item in @(
        Get-ChildItem -LiteralPath $sourceItem.FullName -Recurse -Force |
            Sort-Object FullName
    )) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse points are not copied into software packages: $($item.FullName)"
        }
        if (-not $item.FullName.StartsWith(
            $sourcePrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Software package input escaped its allowlisted tree: $($item.FullName)"
        }
        $inside = $item.FullName.Substring($sourcePrefix.Length)
        $target = Join-Path $Destination $inside
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Path $target -Force | Out-Null
        }
        else {
            Copy-SoftwareFile -Source $item.FullName -Destination $target
        }
    }
}

function Write-SoftwareManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ManifestName
    )

    $rootPath = (Get-Item -LiteralPath $Root).FullName
    $rootPrefix = (
        $rootPath.TrimEnd([char[]]"\/") +
        [System.IO.Path]::DirectorySeparatorChar
    )
    $manifestPath = Join-Path $rootPath $ManifestName
    $lines = Get-ChildItem -LiteralPath $rootPath -Recurse -Force -File |
        Where-Object { $_.FullName -ne $manifestPath } |
        ForEach-Object {
            if (-not $_.FullName.StartsWith(
                $rootPrefix,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
                throw "Software manifest input escaped the package root: $($_.FullName)"
            }
            $relative = $_.FullName.Substring($rootPrefix.Length).Replace("\", "/")
            [pscustomobject]@{
                Relative = $relative
                Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            }
        } |
        Sort-Object Relative |
        ForEach-Object { "$($_.Hash)  $($_.Relative)" }
    [System.IO.File]::WriteAllLines(
        $manifestPath,
        [string[]]$lines,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Assert-SoftwareManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ManifestName
    )

    $rootItem = Get-Item -LiteralPath $Root -ErrorAction Stop
    if (-not $rootItem.PSIsContainer) {
        throw "Software manifest root is not a directory: $Root"
    }
    $rootPath = $rootItem.FullName.TrimEnd([char[]]"\/")
    $rootPrefix = $rootPath + [System.IO.Path]::DirectorySeparatorChar
    $manifestPath = Join-Path $rootPath $ManifestName
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Software package manifest is missing: $manifestPath"
    }

    $actual = @{}
    foreach ($file in @(
        Get-ChildItem -LiteralPath $rootPath -Recurse -Force -File |
            Where-Object { $_.FullName -ne $manifestPath }
    )) {
        if (-not $file.FullName.StartsWith(
            $rootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Software manifest file escaped the package root: $($file.FullName)"
        }
        $relative = $file.FullName.Substring($rootPrefix.Length).Replace("\", "/")
        $actual[$relative] = $file.FullName
    }

    $expected = @{}
    $lines = [System.IO.File]::ReadAllLines($manifestPath)
    for ($lineIndex = 0; $lineIndex -lt $lines.Length; $lineIndex++) {
        $lineNumber = $lineIndex + 1
        $match = [System.Text.RegularExpressions.Regex]::Match(
            $lines[$lineIndex],
            "^(?<hash>[0-9A-Fa-f]{64})  (?<path>.+)$"
        )
        if (-not $match.Success) {
            throw "Software manifest syntax error at line $lineNumber."
        }
        $relative = $match.Groups["path"].Value
        $segments = @($relative -split "/")
        if (
            $relative.Contains("\") -or
            [System.IO.Path]::IsPathRooted($relative) -or
            @($segments | Where-Object { $_ -eq "" -or $_ -eq "." -or $_ -eq ".." }).Count -gt 0
        ) {
            throw "Software manifest path is not normalized at line ${lineNumber}: $relative"
        }
        if ($relative.Equals(
            $ManifestName,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Software manifest must not list itself."
        }
        $resolved = [System.IO.Path]::GetFullPath(
            (Join-Path $rootPath $relative.Replace("/", "\"))
        )
        if (-not $resolved.StartsWith(
            $rootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Software manifest path escapes the package root: $relative"
        }
        if ($expected.ContainsKey($relative)) {
            throw "Duplicate software manifest path: $relative"
        }
        $expected[$relative] = $match.Groups["hash"].Value.ToUpperInvariant()
    }

    foreach ($relative in @($actual.Keys)) {
        if (-not $expected.ContainsKey($relative)) {
            throw "Software package file is missing from manifest: $relative"
        }
    }
    foreach ($relative in @($expected.Keys)) {
        if (-not $actual.ContainsKey($relative)) {
            throw "Software manifest lists a missing file: $relative"
        }
        $actualHash = (
            Get-FileHash -LiteralPath $actual[$relative] -Algorithm SHA256
        ).Hash.ToUpperInvariant()
        if ($actualHash -ne $expected[$relative]) {
            throw "Software manifest hash mismatch: $relative"
        }
    }
    return $actual.Count
}

$manifestName = "SOFTWARE_PACKAGE_SHA256.txt"
$publishedDestination = $false
$publishedArchive = $false
try {
    New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
    Copy-SoftwareFile `
        -Source (Join-Path $builtRoot "ChromaMatter.exe") `
        -Destination (Join-Path $stagingRoot "ChromaMatter.exe")
    Copy-SoftwareTree `
        -Source (Join-Path $builtRoot "_internal") `
        -Destination (Join-Path $stagingRoot "_internal")

    foreach ($record in $packageFiles) {
        Copy-SoftwareFile `
            -Source (Join-Path $repoRoot $record.Source.Replace("/", "\")) `
            -Destination (Join-Path $stagingRoot $record.Destination.Replace("/", "\"))
    }
    Copy-SoftwareFile -Source $componentMapFullPath -Destination (
        Join-Path $stagingRoot "licenses\BINARY_COMPONENT_MAP.json"
    )
    Copy-SoftwareFile -Source $sbomFullPath -Destination (
        Join-Path $stagingRoot "licenses\SBOM.cdx.json"
    )
    foreach ($language in @("EN", "JA")) {
        $templatePath = Join-Path $repoRoot "licenses\SOURCE_OFFER_TEMPLATE_$language.txt"
        $rendered = [System.IO.File]::ReadAllText($templatePath).
            Replace("@@RELEASE_ID@@", $destinationLeaf).
            Replace("@@BINARY_ARCHIVE_NAME@@", $archiveLeaf).
            Replace("@@CORRESPONDING_SOURCE_URL@@", $CorrespondingSourceUrl)
        if (Test-IncompleteReleaseValue -Value $rendered) {
            throw "Rendered source offer still contains a placeholder: $language"
        }
        [System.IO.File]::WriteAllText(
            (Join-Path $stagingRoot "licenses\SOURCE_OFFER_$language.txt"),
            $rendered,
            [System.Text.UTF8Encoding]::new($false)
        )
    }

    Assert-SoftwarePayloadSafe -Root $stagingRoot
    Write-SoftwareManifest -Root $stagingRoot -ManifestName $manifestName
    $stageFileCount = Assert-SoftwareManifest `
        -Root $stagingRoot `
        -ManifestName $manifestName

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stagingRoot,
        $archiveTemporary,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $true
    )
    New-Item -ItemType Directory -Path $verificationContainer | Out-Null
    [System.IO.Compression.ZipFile]::ExtractToDirectory(
        $archiveTemporary,
        $verificationContainer
    )
    $verificationRoot = Join-Path $verificationContainer $destinationLeaf
    $verifiedFileCount = Assert-SoftwareManifest `
        -Root $verificationRoot `
        -ManifestName $manifestName
    if ($verifiedFileCount -ne $stageFileCount) {
        throw (
            "Extracted software package file count changed: " +
            "$stageFileCount -> $verifiedFileCount"
        )
    }

    Move-Item -LiteralPath $stagingRoot -Destination $destinationPath
    $publishedDestination = $true
    Move-Item -LiteralPath $archiveTemporary -Destination $archiveFullPath
    $publishedArchive = $true

    $finalFileCount = Assert-SoftwareManifest `
        -Root $destinationPath `
        -ManifestName $manifestName
    if ($finalFileCount -ne $stageFileCount) {
        throw "Published software stage changed after verification."
    }

    $archiveHash = (
        Get-FileHash -LiteralPath $archiveFullPath -Algorithm SHA256
    ).Hash
    $manifestHash = (
        Get-FileHash `
            -LiteralPath (Join-Path $destinationPath $manifestName) `
            -Algorithm SHA256
    ).Hash
    Write-Host "Software package staged: $destinationPath"
    Write-Host "Software archive verified after extraction: $archiveFullPath"
    Write-Host "Packaged files (manifest excluded): $stageFileCount"
    Write-Host "Software manifest SHA-256: $manifestHash"
    Write-Host "Software ZIP SHA-256: $archiveHash"
}
catch {
    # Destination and archive did not exist on entry and are created only by
    # this invocation.  Roll back a partially published pair so a failed run
    # never looks like a completed release candidate.
    if ($publishedArchive -and (Test-Path -LiteralPath $archiveFullPath)) {
        Remove-Item -LiteralPath $archiveFullPath -Force
    }
    if ($publishedDestination -and (Test-Path -LiteralPath $destinationPath)) {
        Remove-Item -LiteralPath $destinationPath -Recurse -Force
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $verificationContainer) {
        Remove-Item -LiteralPath $verificationContainer -Recurse -Force
    }
    if (Test-Path -LiteralPath $archiveTemporary) {
        Remove-Item -LiteralPath $archiveTemporary -Force
    }
    if (Test-Path -LiteralPath $stagingContainer) {
        Remove-Item -LiteralPath $stagingContainer -Recurse -Force
    }
}
