[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [Alias("BuildRoot")]
    [string]$BuiltAppRoot,
    [string]$Destination = "",
    [string]$ArchivePath = "",
    [string]$CorrespondingSourceUrl = "",
    [string]$CorrespondingSourceArchivePath = "",
    [string]$CorrespondingSourceManifestPath = "",
    [string]$CorrespondingSourceArchiveSha256 = "",
    [string]$CorrespondingSourceProjectCommit = "",
    [string]$BinaryComponentMapPath = "",
    [string]$SbomPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop

$repoRoot = (Get-Item -LiteralPath (Split-Path -Parent $PSScriptRoot)).FullName
Import-Module `
    (Join-Path $PSScriptRoot "SoftwareZipContract.psm1") `
    -Force `
    -ErrorAction Stop
$builtRoot = (Get-Item -LiteralPath $BuiltAppRoot -ErrorAction Stop).FullName
if (-not (Test-Path -LiteralPath $builtRoot -PathType Container)) {
    throw "Built application root is not a directory: $BuiltAppRoot"
}

if (-not $Destination) {
    $Destination = Join-Path `
        $repoRoot `
        "artifacts\ChromaMatter-0.8beta-r32-win64"
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

function Read-CanonicalJsonObject {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Canonical $Label is missing: $Path"
    }
    try {
        $value = [System.IO.File]::ReadAllText($Path) |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Canonical $Label is not valid JSON: $($_.Exception.Message)"
    }
    if ($null -eq $value -or $value -is [System.Array]) {
        throw "Canonical $Label must be a JSON object."
    }
    return $value
}

function Assert-ExactJsonProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $wanted = @($Expected | Sort-Object -CaseSensitive)
    if (@(Compare-Object $wanted $actual -CaseSensitive).Count -ne 0) {
        throw "$Context has missing or unexpected fields."
    }
}

function Assert-CanonicalRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Prefix,
        [Parameter(Mandatory = $true)][string]$Context,
        [string]$Suffix = ""
    )

    if (
        [string]::IsNullOrWhiteSpace($Path) -or
        $Path.Contains("\") -or
        [System.IO.Path]::IsPathRooted($Path) -or
        $Path.Split("/") -contains "" -or
        $Path.Split("/") -contains "." -or
        $Path.Split("/") -contains ".." -or
        -not $Path.StartsWith($Prefix, [System.StringComparison]::Ordinal) -or
        (
            $Suffix -and
            -not $Path.EndsWith($Suffix, [System.StringComparison]::OrdinalIgnoreCase)
        )
    ) {
        throw "$Context is not a canonical relative path: $Path"
    }
}

function Assert-ExactStringSet {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Actual,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $actualStrings = @($Actual | ForEach-Object { [string]$_ })
    $actualSet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($value in $actualStrings) {
        if ([string]::IsNullOrWhiteSpace($value) -or -not $actualSet.Add($value)) {
            throw "$Context contains a blank or duplicate value."
        }
    }
    $actualSorted = @($actualStrings | Sort-Object -CaseSensitive)
    $expectedSorted = @($Expected | Sort-Object -CaseSensitive)
    if (
        $actualStrings.Count -ne $Expected.Count -or
        @(Compare-Object $expectedSorted $actualSorted -CaseSensitive).Count -ne 0
    ) {
        throw "$Context does not match the exact canonical set."
    }
}

$pinnedPyMeshLabVersion = "2025.7.post1"
$pinnedPyMeshLabWheelSha256 = (
    "25eb2578dd6c4d1b2e0253fb3b4f8f7895e8bb4f3f1236832db0ab58e6a44998"
)
$pinnedPyMeshLabSourceCommit = (
    "1dc199f9b6c43e58b6db346ba4600866b950b8ae"
)
$qtStaticManifest = Read-CanonicalJsonObject `
    -Path (Join-Path $repoRoot "tooling\qt_static_components.json") `
    -Label "Qt static-component manifest"
$pyMeshLabIdentityManifest = Read-CanonicalJsonObject `
    -Path (Join-Path $repoRoot "tooling\pymeshlab_audited_native_identities.json") `
    -Label "PyMeshLab audited-native manifest"
$pytetwildStaticManifest = Read-CanonicalJsonObject `
    -Path (Join-Path $repoRoot "tooling\pytetwild_static_closure.json") `
    -Label "PyTetWild static-closure manifest"

Assert-ExactJsonProperties `
    -Value $qtStaticManifest `
    -Expected @(
        "schema_version", "document_id", "scope", "generated_from_read_only_audit",
        "qt_runtime_component", "binary_provenance", "files", "static_components",
        "license_assets", "implementation_notes"
    ) `
    -Context "Qt static-component manifest"
Assert-ExactJsonProperties `
    -Value $pyMeshLabIdentityManifest `
    -Expected @("schema_version", "distribution", "purpose", "identities") `
    -Context "PyMeshLab audited-native manifest"
if (
    [int]$qtStaticManifest.schema_version -ne 1 -or
    [int]$pyMeshLabIdentityManifest.schema_version -ne 1
) {
    throw "Canonical audited-native manifests have unsupported schema versions."
}

$pyMeshLabDistribution = $pyMeshLabIdentityManifest.distribution
Assert-ExactJsonProperties `
    -Value $pyMeshLabDistribution `
    -Expected @("name", "version", "wheel_sha256", "source_commit") `
    -Context "PyMeshLab distribution binding"
$qtRuntime = $qtStaticManifest.qt_runtime_component
Assert-ExactJsonProperties `
    -Value $qtRuntime `
    -Expected @("id", "version", "license_expression", "source_url", "note") `
    -Context "Qt runtime binding"
$qtBinaryProvenance = $qtStaticManifest.binary_provenance
Assert-ExactJsonProperties `
    -Value $qtBinaryProvenance `
    -Expected @(
        "package_id", "package_version", "updates_xml_url", "pymeshlab",
        "official_binary_archives", "source_archives"
    ) `
    -Context "Qt binary provenance"
$qtPyMeshLab = $qtStaticManifest.binary_provenance.pymeshlab
Assert-ExactJsonProperties `
    -Value $qtPyMeshLab `
    -Expected @(
        "version", "tag_commit", "wheel_sha256", "workflow_url",
        "qt_version_declared"
    ) `
    -Context "Qt PyMeshLab provenance"
if (
    [string]$pyMeshLabDistribution.name -cne "pymeshlab" -or
    [string]$pyMeshLabDistribution.version -cne $pinnedPyMeshLabVersion -or
    [string]$pyMeshLabDistribution.wheel_sha256 -cne $pinnedPyMeshLabWheelSha256 -or
    [string]$pyMeshLabDistribution.source_commit -cne $pinnedPyMeshLabSourceCommit -or
    [string]$qtPyMeshLab.version -cne $pinnedPyMeshLabVersion -or
    [string]$qtPyMeshLab.wheel_sha256 -cne $pinnedPyMeshLabWheelSha256 -or
    [string]$qtPyMeshLab.tag_commit -cne $pinnedPyMeshLabSourceCommit -or
    [string]$qtPyMeshLab.qt_version_declared -cne "5.15.2" -or
    [string]$qtRuntime.id -cne "qt" -or
    [string]$qtRuntime.version -cne "5.15.2" -or
    [string]$qtRuntime.license_expression -cne "LGPL-3.0-only" -or
    [string]$qtRuntime.source_url -cne (
        "https://download.qt.io/archive/qt/5.15/5.15.2/single/"
    ) -or
    [string]$qtBinaryProvenance.package_id -cne (
        "qt.qt5.5152.win64_msvc2019_64"
    ) -or
    [string]$qtBinaryProvenance.package_version -cne (
        "5.15.2-0-202011130602"
    )
) {
    throw "Canonical audited-native manifests have the wrong PyMeshLab binding."
}

$qtSourceRows = @(
    $qtStaticManifest.binary_provenance.source_archives |
        Where-Object { [string]$_.id -ceq "qt-5.15.2-corresponding-source" }
)
if (
    $qtSourceRows.Count -ne 1 -or
    [string]$qtSourceRows[0].url -cnotmatch "^https://" -or
    [string]$qtSourceRows[0].sha256 -cnotmatch "^[0-9a-f]{64}$"
) {
    throw "Qt corresponding-source archive binding is missing or invalid."
}
$qtComponentSourceUrl = [string]$qtSourceRows[0].url

$qtLicenseExpectations = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($property in @($qtStaticManifest.license_assets.PSObject.Properties)) {
    $sourcePath = [string]$property.Name
    Assert-CanonicalRelativePath `
        -Path $sourcePath `
        -Prefix "source/fixed_app/licenses/qt-5.15.2/" `
        -Context "Qt license asset"
    $record = $property.Value
    Assert-ExactJsonProperties `
        -Value $record `
        -Expected @("sha256", "size", "byte_preserving", "upstream") `
        -Context "Qt license asset $sourcePath"
    $expectedSha256 = [string]$record.sha256
    if (
        $expectedSha256 -cnotmatch "^[0-9a-f]{64}$" -or
        [long]$record.size -le 0 -or
        $record.byte_preserving -ne $true
    ) {
        throw "Qt license asset has invalid fixed metadata: $sourcePath"
    }
    $packagedPath = "_internal/" + $sourcePath.Substring("source/fixed_app/".Length)
    Assert-CanonicalRelativePath `
        -Path $packagedPath `
        -Prefix "_internal/licenses/qt-5.15.2/" `
        -Context "Packaged Qt license asset"
    if ($qtLicenseExpectations.ContainsKey($packagedPath)) {
        throw "Qt license asset destination is duplicated: $packagedPath"
    }
    $sourceFullPath = Join-Path $repoRoot $sourcePath.Replace("/", "\")
    if (-not (Test-Path -LiteralPath $sourceFullPath -PathType Leaf)) {
        throw "Qt license asset source is missing: $sourcePath"
    }
    $sourceFile = Get-Item -LiteralPath $sourceFullPath
    $sourceSha256 = (
        Get-FileHash -LiteralPath $sourceFullPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        [long]$sourceFile.Length -ne [long]$record.size -or
        $sourceSha256 -cne $expectedSha256
    ) {
        throw "Qt license asset source does not match its canonical identity: $sourcePath"
    }
    $qtLicenseExpectations.Add(
        $packagedPath,
        [pscustomobject]@{
            source_path = $sourcePath
            size = [long]$record.size
            sha256 = $expectedSha256
        }
    )
}
if ($qtLicenseExpectations.Count -ne 51) {
    throw "Qt static-component manifest must bind exactly 51 license assets."
}

$qtComponentExpectations = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
$qtComponentRuntimeExpectations = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($record in @($qtStaticManifest.static_components)) {
    Assert-ExactJsonProperties `
        -Value $record `
        -Expected @(
            "id", "name", "version", "version_basis", "license_expression",
            "license_assets", "source", "runtime_files", "provenance"
        ) `
        -Context "Qt static component"
    $componentId = [string]$record.id
    if (
        $componentId -cnotmatch "^qt-[a-z0-9][a-z0-9-]*$" -or
        $qtComponentExpectations.ContainsKey($componentId) -or
        [string]::IsNullOrWhiteSpace([string]$record.name) -or
        [string]::IsNullOrWhiteSpace([string]$record.version) -or
        [string]::IsNullOrWhiteSpace([string]$record.license_expression) -or
        [string]$record.source.archive_id -cne "qt-5.15.2-corresponding-source"
    ) {
        throw "Qt static component metadata is invalid: $componentId"
    }
    $assets = [System.Collections.Generic.List[string]]::new()
    $assetSet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($sourceAssetValue in @($record.license_assets)) {
        $sourceAsset = [string]$sourceAssetValue
        Assert-CanonicalRelativePath `
            -Path $sourceAsset `
            -Prefix "source/fixed_app/licenses/qt-5.15.2/" `
            -Context "Qt static component license asset"
        $packagedAsset = "_internal/" + $sourceAsset.Substring("source/fixed_app/".Length)
        if (
            -not $qtLicenseExpectations.ContainsKey($packagedAsset) -or
            -not $assetSet.Add($packagedAsset)
        ) {
            throw "Qt static component has an unknown/duplicate license asset: $componentId"
        }
        $assets.Add($packagedAsset)
    }
    if ($assets.Count -eq 0) {
        throw "Qt static component has no license assets: $componentId"
    }
    $runtimePaths = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($runtimePathValue in @($record.runtime_files)) {
        $runtimePath = [string]$runtimePathValue
        Assert-CanonicalRelativePath `
            -Path $runtimePath `
            -Prefix "_internal/pymeshlab/" `
            -Suffix ".dll" `
            -Context "Qt static component runtime file"
        if (-not $runtimePaths.Add($runtimePath)) {
            throw "Qt static component repeats a runtime file: $componentId"
        }
    }
    if ($runtimePaths.Count -eq 0) {
        throw "Qt static component has no runtime files: $componentId"
    }
    $qtComponentExpectations.Add(
        $componentId,
        [pscustomobject]@{
            name = [string]$record.name
            version = [string]$record.version
            license = [string]$record.license_expression
            source = $qtComponentSourceUrl
            license_assets = @($assets)
        }
    )
    $qtComponentRuntimeExpectations.Add($componentId, $runtimePaths)
}
if ($qtComponentExpectations.Count -ne 50) {
    throw "Qt static-component manifest must bind exactly 50 components."
}

$auditedNativeExpectations = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
$pyMeshLabAuditedCount = 0
foreach ($record in @($pyMeshLabIdentityManifest.identities)) {
    Assert-ExactJsonProperties `
        -Value $record `
        -Expected @("path", "size", "sha256", "audited_components") `
        -Context "PyMeshLab audited native identity"
    $path = [string]$record.path
    Assert-CanonicalRelativePath `
        -Path $path `
        -Prefix "_internal/pymeshlab/" `
        -Suffix ".dll" `
        -Context "PyMeshLab audited native identity"
    $componentIds = @(
        $record.audited_components | ForEach-Object { [string]$_ }
    )
    $componentIdSet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($componentId in $componentIds) {
        if (
            [string]::IsNullOrWhiteSpace($componentId) -or
            -not $componentIdSet.Add($componentId)
        ) {
            throw "PyMeshLab audited native components are invalid: $path"
        }
    }
    $canonicalComponentIds = @($componentIds | Sort-Object -CaseSensitive)
    if (
        $auditedNativeExpectations.ContainsKey($path) -or
        [long]$record.size -le 0 -or
        [string]$record.sha256 -cnotmatch "^[0-9a-f]{64}$" -or
        $componentIds.Count -eq 0 -or
        @(Compare-Object $componentIds $canonicalComponentIds -CaseSensitive).Count -ne 0
    ) {
        throw "PyMeshLab audited native identity is invalid: $path"
    }
    $auditedNativeExpectations.Add(
        $path,
        [pscustomobject]@{
            path = $path
            size = [long]$record.size
            sha256 = [string]$record.sha256
            components = $componentIds
            source_manifest = "tooling/pymeshlab_audited_native_identities.json"
        }
    )
    $pyMeshLabAuditedCount += 1
}
$qtReverseRuntimeExpectations = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($componentId in $qtComponentRuntimeExpectations.Keys) {
    $qtReverseRuntimeExpectations.Add(
        $componentId,
        [System.Collections.Generic.HashSet[string]]::new(
            [System.StringComparer]::Ordinal
        )
    )
}
$qtAuditedCount = 0
foreach ($record in @($qtStaticManifest.files)) {
    Assert-ExactJsonProperties `
        -Value $record `
        -Expected @(
            "path", "size", "sha256", "pe_version", "official_archive_id",
            "official_archive_member", "runtime_component_ids"
        ) `
        -Context "Qt audited native identity"
    $path = [string]$record.path
    Assert-CanonicalRelativePath `
        -Path $path `
        -Prefix "_internal/pymeshlab/" `
        -Suffix ".dll" `
        -Context "Qt audited native identity"
    $runtimeComponentIds = @(
        $record.runtime_component_ids | ForEach-Object { [string]$_ }
    )
    $runtimeComponentIdSet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($componentId in $runtimeComponentIds) {
        if (
            [string]::IsNullOrWhiteSpace($componentId) -or
            -not $runtimeComponentIdSet.Add($componentId) -or
            (
                $componentId -cne "qt" -and
                -not $qtComponentRuntimeExpectations.ContainsKey($componentId)
            )
        ) {
            throw "Qt audited native component IDs are invalid: $path"
        }
        if ($componentId -cne "qt") {
            [void]$qtReverseRuntimeExpectations[$componentId].Add($path)
        }
    }
    if (
        $auditedNativeExpectations.ContainsKey($path) -or
        [long]$record.size -le 0 -or
        [string]$record.sha256 -cnotmatch "^[0-9a-f]{64}$" -or
        [string]$record.pe_version -cne "5.15.2.0" -or
        $runtimeComponentIds.Count -eq 0 -or
        [string]$runtimeComponentIds[0] -cne "qt"
    ) {
        throw "Qt audited native identity is invalid: $path"
    }
    $auditedNativeExpectations.Add(
        $path,
        [pscustomobject]@{
            path = $path
            size = [long]$record.size
            sha256 = [string]$record.sha256
            components = $runtimeComponentIds
            source_manifest = "tooling/qt_static_components.json"
        }
    )
    $qtAuditedCount += 1
}
foreach ($componentId in $qtComponentRuntimeExpectations.Keys) {
    $forward = @($qtComponentRuntimeExpectations[$componentId] | Sort-Object -CaseSensitive)
    $reverse = @($qtReverseRuntimeExpectations[$componentId] | Sort-Object -CaseSensitive)
    if (@(Compare-Object $forward $reverse -CaseSensitive).Count -ne 0) {
        throw "Qt runtime/component mapping is not bidirectional: $componentId"
    }
}
if (
    $pyMeshLabAuditedCount -ne 19 -or
    $qtAuditedCount -ne 7 -or
    $auditedNativeExpectations.Count -ne 26
) {
    throw "Canonical manifests must bind exactly 26 audited native identities."
}

# Independently re-validate the PyTetWild static-link closure in PowerShell.
# The Python inventory generator uses its own strict loader; release staging
# must not merely trust the generator's conclusion or a self-consistent map.
$pytetwildExpectedComponentIds = @(
    "eigen", "fmt", "ftetwild", "geogram", "geogram-amgcl",
    "geogram-libmeshb", "geogram-poissonrecon", "geogram-rply",
    "geogram-stb-image", "geogram-stb-image-write", "geogram-xatlas",
    "geogram-zlib", "jdumas-json", "libigl", "libigl-predicates",
    "nanobind", "nanobind-robin-map", "onetbb", "pytetwild", "spdlog"
)
$pytetwildExpectedSourceArchiveIds = @(
    "eigen-source", "fmt-source", "ftetwild-source", "geogram-amgcl-source",
    "geogram-libmeshb-source", "geogram-rply-source", "geogram-source",
    "jdumas-json-source", "libigl-predicates-source", "libigl-source",
    "nanobind-robin-map-source", "nanobind-source", "onetbb-source",
    "pytetwild-source", "spdlog-source"
)
$pytetwildExpectedLicenseAssetIds = @(
    "eigen-apache", "eigen-bsd", "eigen-gpl", "eigen-lgpl",
    "eigen-minpack", "eigen-mpl2", "eigen-readme", "fmt-license",
    "ftetwild-mpl2", "geogram-amgcl-license", "geogram-libmeshb-license",
    "geogram-license", "geogram-poissonrecon-license",
    "geogram-rply-license", "geogram-stb-image-notice",
    "geogram-stb-image-write-notice", "geogram-xatlas-header-notice",
    "geogram-xatlas-source-notices", "geogram-zlib-license",
    "jdumas-json-license", "libigl-gpl", "libigl-mpl2",
    "libigl-predicates-readme", "libigl-predicates-source-notice",
    "nanobind-license", "nanobind-robin-map-license", "onetbb-license",
    "pytetwild-license", "spdlog-license"
)
$pytetwildExpectedCmakeDefinitions = @(
    "BUILD_SHARED_LIBS=OFF", "EIGEN_MPL2_ONLY=ON",
    "FLOAT_TETWILD_ENABLE_TBB=ON", "GEOGRAM_WITH_TBB=OFF",
    "LIBIGL_WITH_PREDICATES=ON"
)
$pytetwildHistoricalWheelSha256 = (
    "11964e295a54cf9e2f6920a920aeeba27668c9b14e369a86f72ec5baa4f46060"
)
$pytetwildHistoricalPydSha256 = (
    "ac801b37e298ee83be35f41193d384f64ef4b5064006e0019a209edff48495de"
)
$pytetwildPackagedWrapperPath = "_internal/pytetwild/PyfTetWildWrapper.pyd"
$pytetwildMappingBasis = "controlled-pytetwild-static-closure"

Assert-ExactJsonProperties `
    -Value $pytetwildStaticManifest `
    -Expected @(
        "schema_version", "manifest_id", "scope", "release_gate",
        "build_binding", "source_archives", "license_assets", "components"
    ) `
    -Context "PyTetWild static-closure manifest"
if (
    [int]$pytetwildStaticManifest.schema_version -ne 1 -or
    [string]$pytetwildStaticManifest.manifest_id -cne (
        "chromamatter-pytetwild-static-closure"
    ) -or
    [string]::IsNullOrWhiteSpace([string]$pytetwildStaticManifest.scope)
) {
    throw "Canonical PyTetWild static-closure manifest identity is invalid."
}

$pytetwildReleaseGate = $pytetwildStaticManifest.release_gate
Assert-ExactJsonProperties `
    -Value $pytetwildReleaseGate `
    -Expected @("status", "release_eligible", "blockers") `
    -Context "PyTetWild static-closure release gate"
$pytetwildUnresolvedBlockers = 0
$pytetwildBlockerIds = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($blocker in @($pytetwildReleaseGate.blockers)) {
    Assert-ExactJsonProperties `
        -Value $blocker `
        -Expected @("id", "resolved", "reason") `
        -Context "PyTetWild static-closure release blocker"
    $blockerId = [string]$blocker.id
    if (
        $blockerId -cnotmatch "^[a-z0-9]+(?:-[a-z0-9]+)*$" -or
        -not $pytetwildBlockerIds.Add($blockerId) -or
        [string]::IsNullOrWhiteSpace([string]$blocker.reason) -or
        $blocker.resolved -isnot [bool]
    ) {
        throw "PyTetWild static-closure release blocker is invalid."
    }
    if ($blocker.resolved -ne $true) { $pytetwildUnresolvedBlockers += 1 }
}
$pytetwildManifestClaimsReleaseEligible = (
    $pytetwildReleaseGate.release_eligible -eq $true
)
if ($pytetwildManifestClaimsReleaseEligible) {
    if (
        [string]$pytetwildReleaseGate.status -cne "release-approved" -or
        $pytetwildUnresolvedBlockers -ne 0
    ) {
        throw "PyTetWild manifest claims eligibility without an approved gate."
    }
}
elseif (
    [string]$pytetwildReleaseGate.status -cne "blocked" -or
    $pytetwildUnresolvedBlockers -eq 0
) {
    throw "Blocked PyTetWild manifest must retain an unresolved release blocker."
}

$pytetwildBuildBinding = $pytetwildStaticManifest.build_binding
Assert-ExactJsonProperties `
    -Value $pytetwildBuildBinding `
    -Expected @(
        "recipe_path", "recipe_bytes", "recipe_sha256",
        "required_cmake_definitions", "source_archive_recipe",
        "historical_audited_package", "controlled_rebuild"
    ) `
    -Context "PyTetWild static-closure build binding"
if ([string]$pytetwildBuildBinding.recipe_path -cne "tooling/BUILD_PYTETWILD_WINDOWS.ps1") {
    throw "PyTetWild controlled build recipe path changed."
}
Assert-ExactStringSet `
    -Actual @($pytetwildBuildBinding.required_cmake_definitions) `
    -Expected $pytetwildExpectedCmakeDefinitions `
    -Context "PyTetWild controlled CMake definitions"
$pytetwildRecipePath = Join-Path $repoRoot "tooling\BUILD_PYTETWILD_WINDOWS.ps1"
if (-not (Test-Path -LiteralPath $pytetwildRecipePath -PathType Leaf)) {
    throw "PyTetWild controlled build recipe is missing."
}
$pytetwildRecipe = Get-Item -LiteralPath $pytetwildRecipePath
if (($pytetwildRecipe.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "PyTetWild controlled build recipe must not be a reparse point."
}
$pytetwildRecipeSha256 = (
    Get-FileHash -LiteralPath $pytetwildRecipePath -Algorithm SHA256
).Hash.ToLowerInvariant()
if (
    [long]$pytetwildBuildBinding.recipe_bytes -ne [long]$pytetwildRecipe.Length -or
    [string]$pytetwildBuildBinding.recipe_sha256 -cne $pytetwildRecipeSha256
) {
    throw "PyTetWild controlled build recipe identity does not match the manifest."
}
$pytetwildRecipeText = [System.IO.File]::ReadAllText($pytetwildRecipePath)
foreach ($definition in $pytetwildExpectedCmakeDefinitions) {
    if (-not $pytetwildRecipeText.Contains("'-D$definition'")) {
        throw "PyTetWild controlled recipe does not apply -D$definition."
    }
}

$pytetwildArchiveRecipe = $pytetwildBuildBinding.source_archive_recipe
Assert-ExactJsonProperties `
    -Value $pytetwildArchiveRecipe `
    -Expected @("tool", "tool_version", "arguments", "note") `
    -Context "PyTetWild source-archive recipe"
$pytetwildArchiveArguments = @(
    $pytetwildArchiveRecipe.arguments | ForEach-Object { [string]$_ }
)
if (
    [string]$pytetwildArchiveRecipe.tool -cne "PortableGit" -or
    [string]$pytetwildArchiveRecipe.tool_version -cne "2.55.0.windows.5" -or
    $pytetwildArchiveArguments.Count -ne 2 -or
    [string]$pytetwildArchiveArguments[0] -cne "archive" -or
    [string]$pytetwildArchiveArguments[1] -cne "--format=zip" -or
    [string]::IsNullOrWhiteSpace([string]$pytetwildArchiveRecipe.note)
) {
    throw "PyTetWild source-archive recipe identity changed."
}

$pytetwildHistorical = $pytetwildBuildBinding.historical_audited_package
Assert-ExactJsonProperties `
    -Value $pytetwildHistorical `
    -Expected @(
        "package", "version", "pyd_relative_path", "pyd_bytes", "pyd_sha256",
        "disposition", "reason"
    ) `
    -Context "Historical PyTetWild identity"
if (
    [string]$pytetwildHistorical.package -cne "pytetwild" -or
    [string]$pytetwildHistorical.version -cne "0.3.0" -or
    [string]$pytetwildHistorical.pyd_relative_path -cne (
        "pytetwild/PyfTetWildWrapper.pyd"
    ) -or
    [long]$pytetwildHistorical.pyd_bytes -ne 5897728 -or
    [string]$pytetwildHistorical.pyd_sha256 -cne $pytetwildHistoricalPydSha256 -or
    [string]$pytetwildHistorical.disposition -cne (
        "excluded-historical-audit-only"
    ) -or
    [string]::IsNullOrWhiteSpace([string]$pytetwildHistorical.reason)
) {
    throw "Historical PyTetWild identity/disposition changed."
}

$pytetwildControlled = $pytetwildBuildBinding.controlled_rebuild
Assert-ExactJsonProperties `
    -Value $pytetwildControlled `
    -Expected @(
        "status", "package", "version", "wheel_tag", "wheel_sha256",
        "pyd_relative_path", "pyd_sha256", "approval_requires"
    ) `
    -Context "Controlled PyTetWild rebuild"
$pytetwildApprovalRequirements = @(
    $pytetwildControlled.approval_requires | ForEach-Object { [string]$_ }
)
$pytetwildApprovalSet = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($requirement in $pytetwildApprovalRequirements) {
    if ([string]::IsNullOrWhiteSpace($requirement) -or -not $pytetwildApprovalSet.Add($requirement)) {
        throw "Controlled PyTetWild approval requirements are invalid."
    }
}
if (
    -not $pytetwildApprovalSet.Contains("wheel_sha256") -or
    -not $pytetwildApprovalSet.Contains("pyd_sha256") -or
    [string]$pytetwildControlled.package -cne "pytetwild" -or
    [string]$pytetwildControlled.version -cne "0.3.0" -or
    [string]$pytetwildControlled.wheel_tag -cne "cp312-abi3-win_amd64" -or
    [string]$pytetwildControlled.pyd_relative_path -cne (
        "pytetwild/PyfTetWildWrapper.pyd"
    )
) {
    throw "Controlled PyTetWild rebuild identity is incomplete or changed."
}
$pytetwildControlledWheelSha256 = if ($null -eq $pytetwildControlled.wheel_sha256) {
    ""
} else { [string]$pytetwildControlled.wheel_sha256 }
$pytetwildControlledPydSha256 = if ($null -eq $pytetwildControlled.pyd_sha256) {
    ""
} else { [string]$pytetwildControlled.pyd_sha256 }
$pytetwildControlledApproved = (
    [string]$pytetwildControlled.status -ceq "approved" -and
    $pytetwildControlledWheelSha256 -cmatch "^[0-9a-f]{64}$" -and
    $pytetwildControlledPydSha256 -cmatch "^[0-9a-f]{64}$"
)
if ($pytetwildManifestClaimsReleaseEligible) {
    if (
        -not $pytetwildControlledApproved -or
        $pytetwildControlledWheelSha256 -ceq $pytetwildHistoricalWheelSha256 -or
        $pytetwildControlledPydSha256 -ceq $pytetwildHistoricalPydSha256 -or
        $pytetwildControlledWheelSha256 -ceq $pytetwildControlledPydSha256
    ) {
        throw "Approved PyTetWild manifest lacks distinct controlled binary identities."
    }
}
elseif (
    [string]$pytetwildControlled.status -cne "blocked-awaiting-build" -or
    $pytetwildControlledWheelSha256 -ne "" -or
    $pytetwildControlledPydSha256 -ne ""
) {
    throw "Blocked PyTetWild manifest must await null wheel/PYD identities."
}

$pytetwildSourceProperties = @(
    $pytetwildStaticManifest.source_archives.PSObject.Properties
)
Assert-ExactStringSet `
    -Actual @($pytetwildSourceProperties | ForEach-Object { $_.Name }) `
    -Expected $pytetwildExpectedSourceArchiveIds `
    -Context "PyTetWild static-closure source archives"
$pytetwildSourcesById = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
$pytetwildSourceFilenames = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($property in $pytetwildSourceProperties) {
    $archiveId = [string]$property.Name
    $record = $property.Value
    Assert-ExactJsonProperties `
        -Value $record `
        -Expected @(
            "filename", "kind", "source_url", "version", "revision", "bytes",
            "sha256"
        ) `
        -Context "PyTetWild source archive $archiveId"
    $filename = [string]$record.filename
    if (
        [string]::IsNullOrWhiteSpace($filename) -or
        $filename.Contains("/") -or $filename.Contains("\") -or
        -not $pytetwildSourceFilenames.Add($filename) -or
        [string]$record.source_url -cnotmatch "^https://" -or
        [string]::IsNullOrWhiteSpace([string]$record.version) -or
        [string]::IsNullOrWhiteSpace([string]$record.revision) -or
        [long]$record.bytes -le 0 -or
        [string]$record.sha256 -cnotmatch "^[0-9a-f]{64}$"
    ) {
        throw "PyTetWild source archive metadata is invalid: $archiveId"
    }
    $pytetwildSourcesById.Add($archiveId, $record)
}

$pytetwildAssetProperties = @(
    $pytetwildStaticManifest.license_assets.PSObject.Properties
)
Assert-ExactStringSet `
    -Actual @($pytetwildAssetProperties | ForEach-Object { $_.Name }) `
    -Expected $pytetwildExpectedLicenseAssetIds `
    -Context "PyTetWild static-closure license assets"
$pytetwildAssetsById = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
$pytetwildLicenseExpectations = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($property in $pytetwildAssetProperties) {
    $assetId = [string]$property.Name
    $record = $property.Value
    Assert-ExactJsonProperties `
        -Value $record `
        -Expected @("path", "upstream_path", "bytes", "sha256") `
        -Context "PyTetWild license asset $assetId"
    $sourcePath = [string]$record.path
    Assert-CanonicalRelativePath `
        -Path $sourcePath `
        -Prefix "source/fixed_app/licenses/pytetwild-closure/" `
        -Context "PyTetWild license asset $assetId"
    Assert-CanonicalRelativePath `
        -Path ([string]$record.upstream_path) `
        -Prefix "" `
        -Context "PyTetWild upstream license path $assetId"
    $packagedPath = "_internal/" + $sourcePath.Substring("source/fixed_app/".Length)
    Assert-CanonicalRelativePath `
        -Path $packagedPath `
        -Prefix "_internal/licenses/pytetwild-closure/" `
        -Context "Packaged PyTetWild license asset $assetId"
    $sourceFullPath = Join-Path $repoRoot $sourcePath.Replace("/", "\")
    if (-not (Test-Path -LiteralPath $sourceFullPath -PathType Leaf)) {
        throw "PyTetWild license asset source is missing: $sourcePath"
    }
    $sourceFile = Get-Item -LiteralPath $sourceFullPath
    $sourceSha256 = (
        Get-FileHash -LiteralPath $sourceFullPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        ($sourceFile.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        [long]$record.bytes -le 0 -or
        [long]$record.bytes -ne [long]$sourceFile.Length -or
        [string]$record.sha256 -cnotmatch "^[0-9a-f]{64}$" -or
        [string]$record.sha256 -cne $sourceSha256 -or
        $pytetwildLicenseExpectations.ContainsKey($packagedPath)
    ) {
        throw "PyTetWild license asset identity is invalid: $sourcePath"
    }
    $expectation = [pscustomobject]@{
        id = $assetId
        packaged_path = $packagedPath
        size = [long]$record.bytes
        sha256 = [string]$record.sha256
    }
    $pytetwildAssetsById.Add($assetId, $expectation)
    $pytetwildLicenseExpectations.Add($packagedPath, $expectation)
}

$pytetwildComponentProperties = @(
    $pytetwildStaticManifest.components.PSObject.Properties
)
Assert-ExactStringSet `
    -Actual @($pytetwildComponentProperties | ForEach-Object { $_.Name }) `
    -Expected $pytetwildExpectedComponentIds `
    -Context "PyTetWild static-closure components"
$pytetwildComponentExpectations = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
$pytetwildUsedSourceIds = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
$pytetwildUsedAssetIds = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($property in $pytetwildComponentProperties) {
    $componentId = [string]$property.Name
    $record = $property.Value
    $expectedFields = @(
        "name", "version", "license_expression", "source_archive_ids",
        "license_asset_ids", "inclusion_basis"
    )
    if ($null -ne $record.PSObject.Properties["dependencies"]) {
        $expectedFields += "dependencies"
    }
    if ($null -ne $record.PSObject.Properties["license_route"]) {
        $expectedFields += "license_route"
    }
    Assert-ExactJsonProperties `
        -Value $record `
        -Expected $expectedFields `
        -Context "PyTetWild static component $componentId"
    if (
        [string]::IsNullOrWhiteSpace([string]$record.name) -or
        [string]::IsNullOrWhiteSpace([string]$record.version) -or
        [string]::IsNullOrWhiteSpace([string]$record.license_expression) -or
        [string]::IsNullOrWhiteSpace([string]$record.inclusion_basis) -or
        (
            $null -ne $record.PSObject.Properties["license_route"] -and
            [string]::IsNullOrWhiteSpace([string]$record.license_route)
        )
    ) {
        throw "PyTetWild static component metadata is incomplete: $componentId"
    }
    $sourceIds = @($record.source_archive_ids | ForEach-Object { [string]$_ })
    $sourceIdSet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    if ($sourceIds.Count -eq 0) {
        throw "PyTetWild static component has no source binding: $componentId"
    }
    foreach ($sourceId in $sourceIds) {
        if (
            [string]::IsNullOrWhiteSpace($sourceId) -or
            -not $sourceIdSet.Add($sourceId) -or
            -not $pytetwildSourcesById.ContainsKey($sourceId)
        ) {
            throw "PyTetWild static component has an invalid source binding: $componentId"
        }
        [void]$pytetwildUsedSourceIds.Add($sourceId)
    }
    $assetIds = @($record.license_asset_ids | ForEach-Object { [string]$_ })
    $assetIdSet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    $packagedAssets = [System.Collections.Generic.List[string]]::new()
    foreach ($assetId in $assetIds) {
        if (
            [string]::IsNullOrWhiteSpace($assetId) -or
            -not $assetIdSet.Add($assetId) -or
            -not $pytetwildAssetsById.ContainsKey($assetId)
        ) {
            throw "PyTetWild static component has an invalid license binding: $componentId"
        }
        [void]$pytetwildUsedAssetIds.Add($assetId)
        $packagedAssets.Add([string]$pytetwildAssetsById[$assetId].packaged_path)
    }
    if ($packagedAssets.Count -eq 0) {
        throw "PyTetWild static component has no license assets: $componentId"
    }
    $dependencyIds = if ($null -eq $record.PSObject.Properties["dependencies"]) {
        @()
    } else { @($record.dependencies | ForEach-Object { [string]$_ }) }
    $dependencySet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($dependencyId in $dependencyIds) {
        if (
            $dependencyId -ceq $componentId -or
            -not $dependencySet.Add($dependencyId) -or
            $dependencyId -notin $pytetwildExpectedComponentIds
        ) {
            throw "PyTetWild static component has an invalid dependency: $componentId"
        }
    }
    $sourceRecord = $pytetwildSourcesById[$sourceIds[0]]
    $pytetwildComponentExpectations.Add(
        $componentId,
        [pscustomobject]@{
            name = [string]$record.name
            version = [string]$record.version
            license = [string]$record.license_expression
            source = [string]$sourceRecord.source_url
            license_assets = @($packagedAssets)
        }
    )
}
Assert-ExactStringSet `
    -Actual @($pytetwildUsedSourceIds) `
    -Expected $pytetwildExpectedSourceArchiveIds `
    -Context "Referenced PyTetWild source archives"
Assert-ExactStringSet `
    -Actual @($pytetwildUsedAssetIds) `
    -Expected $pytetwildExpectedLicenseAssetIds `
    -Context "Referenced PyTetWild license assets"

$pytetwildApplicationLockPath = Join-Path $repoRoot "source\fixed_app\requirements-build.lock"
if (-not (Test-Path -LiteralPath $pytetwildApplicationLockPath -PathType Leaf)) {
    throw "Canonical application requirements lock is missing."
}
$pytetwildApplicationLock = Get-Item -LiteralPath $pytetwildApplicationLockPath
if (($pytetwildApplicationLock.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Canonical application requirements lock must not be a reparse point."
}
$pytetwildApplicationLockText = [System.IO.File]::ReadAllText(
    $pytetwildApplicationLockPath
)
$pytetwildRecordStarts = [regex]::Matches(
    $pytetwildApplicationLockText,
    "(?im)^[ \t]*pytetwild(?:==|[ \t]|\[)"
)
$pytetwildLockBindings = [regex]::Matches(
    $pytetwildApplicationLockText,
    "(?m)^[ \t]*pytetwild==0\.3\.0[ \t]*\\[ \t]*\r?\n" +
        "[ \t]*--hash=sha256:(?<sha>[0-9a-f]{64})[ \t]*\r?$"
)
if ($pytetwildRecordStarts.Count -ne 1 -or $pytetwildLockBindings.Count -ne 1) {
    throw "Application lock must contain one exact PyTetWild 0.3.0 SHA-256 record."
}
$pytetwildApplicationWheelSha256 = [string](
    $pytetwildLockBindings[0].Groups["sha"].Value
)
$pytetwildEffectiveReleaseEligible = (
    $pytetwildManifestClaimsReleaseEligible -and
    $pytetwildControlledApproved -and
    $pytetwildApplicationWheelSha256 -ceq $pytetwildControlledWheelSha256 -and
    $pytetwildApplicationWheelSha256 -cne $pytetwildHistoricalWheelSha256
)

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

$pytetwildRuntimePresent = $false
$pytetwildInternalRoot = (Get-Item -LiteralPath (Join-Path $builtRoot "_internal")).FullName
$pytetwildInternalPrefix = (
    $pytetwildInternalRoot.TrimEnd([char[]]"\/") +
    [System.IO.Path]::DirectorySeparatorChar
)
foreach ($item in @(Get-ChildItem -LiteralPath $pytetwildInternalRoot -Recurse -Force)) {
    if (-not $item.FullName.StartsWith(
        $pytetwildInternalPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "PyTetWild runtime detection escaped _internal: $($item.FullName)"
    }
    $insideInternal = $item.FullName.Substring(
        $pytetwildInternalPrefix.Length
    ).Replace("\", "/")
    $lowerInsideInternal = $insideInternal.ToLowerInvariant()
    if (
        $lowerInsideInternal -eq "pytetwild" -or
        $lowerInsideInternal.StartsWith("pytetwild/") -or
        $lowerInsideInternal -eq "pytetwild.libs" -or
        $lowerInsideInternal.StartsWith("pytetwild.libs/") -or
        $lowerInsideInternal -match "^pytetwild-[^/]+\.dist-info(?:/|$)"
    ) {
        $pytetwildRuntimePresent = $true
        break
    }
}
if ($pytetwildRuntimePresent -and -not $pytetwildEffectiveReleaseEligible) {
    $issues = [System.Collections.Generic.List[string]]::new()
    if (-not $pytetwildManifestClaimsReleaseEligible) {
        $issues.Add("manifest-release-blocked")
    }
    if (-not $pytetwildControlledApproved) {
        $issues.Add("controlled-rebuild-not-approved")
    }
    if ($pytetwildApplicationWheelSha256 -ceq $pytetwildHistoricalWheelSha256) {
        $issues.Add("application-lock-historical-wheel-forbidden")
    }
    elseif ($pytetwildApplicationWheelSha256 -cne $pytetwildControlledWheelSha256) {
        $issues.Add("application-lock-wheel-identity-mismatch")
    }
    throw (
        "PyTetWild static-closure release gate is blocked: " +
        (@($issues | Sort-Object -Unique -CaseSensitive) -join ", ")
    )
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
    "_internal/licenses/LICENSE_CPYTHON_BZIP2.txt",
    "_internal/licenses/LICENSE_CPYTHON_EXPAT.txt",
    "_internal/licenses/LICENSE_CPYTHON_LIBMPDEC.txt",
    "_internal/licenses/LICENSE_CPYTHON_XZ.txt",
    "_internal/licenses/LICENSE_LIB3MF.txt",
    "_internal/licenses/LICENSE_LIB3MF_CPP_BASE64.txt",
    "_internal/licenses/LICENSE_LIB3MF_FAST_FLOAT.txt",
    "_internal/licenses/LICENSE_LIB3MF_LIBZIP.txt",
    "_internal/licenses/LICENSE_LIB3MF_ZLIB.txt",
    "_internal/licenses/LICENSE_LLVM_3_6_2.txt",
    "_internal/licenses/LICENSE_MESA_12_0_RC2.html",
    "_internal/licenses/LICENSE_GLEW_2_2_0.txt",
    "_internal/licenses/LICENSE_LIBE57FORMAT_3_1_1.md",
    "_internal/licenses/LICENSE_LIBSPATIALINDEX_2_1_0.txt",
    "_internal/licenses/LICENSE_MUPARSER_2_3_5.txt",
    "_internal/licenses/LICENSE_QT_ANGLE.txt",
    "_internal/licenses/LICENSE_QT_LGPL_3_0.txt",
    "_internal/licenses/LICENSE_U3D.txt",
    "_internal/licenses/LICENSE_U3D_IJG_JPEG.txt",
    "_internal/licenses/LICENSE_U3D_LIBPNG.txt",
    "_internal/licenses/LICENSE_U3D_ZLIB.txt",
    "_internal/licenses/NOTICE_MESA_LLVM.txt",
    "_internal/licenses/NOTICE_QT.txt",
    "_internal/licenses/NOTICE_SQLITE_PUBLIC_DOMAIN.txt",
    "_internal/licenses/NOTICE_U3D_ADDITIONAL.txt",
    "_internal/licenses/NOTICE_U3D_FNVHASH.txt",
    "_internal/licenses/NOTICE_U3D_SHEWCHUK_PREDICATES.txt",
    "_internal/licenses/NOTICE_XERCES_C_3_2_4.txt",
    "_internal/licenses/LICENSE_U3D_WCMATCH.txt",
    "_internal/licenses/NOTICE_U3D_GRAPHICS_GEMS_IV.txt",
    "_internal/licenses/LICENSE_U3D_NICK_BOBIC_QUATERNION.txt",
    "_internal/licenses/LICENSE_RESVG_APACHE_2.0.txt",
    "_internal/licenses/THIRD_PARTY_LICENSES.txt",
    "_internal/licenses/cpython/LICENSE.txt",
    "_internal/licenses/tcl-tk/license.terms",
    "_internal/licenses/numpy/LICENSE.txt",
    "_internal/licenses/glcontext/LICENSE",
    "_internal/licenses/manifold3d/LICENSE",
    "_internal/licenses/mapbox-earcut/LICENSE.md",
    "_internal/licenses/moderngl/LICENSE",
    "_internal/licenses/pillow/LICENSE",
    "_internal/licenses/pyinstaller/COPYING.txt",
    "_internal/licenses/rtree/LICENSE.txt",
    "_internal/licenses/scipy/LICENSE.txt",
    "_internal/licenses/trimesh/LICENSE.md",
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
$requiredRuntimeFiles += @($qtLicenseExpectations.Keys | Sort-Object -CaseSensitive)
if ($pytetwildRuntimePresent) {
    $requiredRuntimeFiles += @(
        $pytetwildLicenseExpectations.Keys | Sort-Object -CaseSensitive
    )
}
foreach ($relative in $requiredRuntimeFiles) {
    $runtimeFile = Join-Path $builtRoot $relative.Replace("/", "\")
    if (-not (Test-Path -LiteralPath $runtimeFile -PathType Leaf)) {
        throw "Required packaged runtime file is missing: $relative"
    }
}

function Test-IncompleteReleaseValue {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
        [switch]$ReleaseUrl
    )
    $releaseUrlHasPlaceholder = $false
    if ($ReleaseUrl) {
        $placeholderUri = $null
        $releaseUrlHasPlaceholder = (
            $Value -match '\\' -or
            $Value -match '(?i)%[0-9a-f]{2}'
        )
        if (
            -not $releaseUrlHasPlaceholder -and
            [Uri]::TryCreate($Value, [UriKind]::Absolute, [ref]$placeholderUri)
        ) {
            $canonicalReleaseLocation = (
                $placeholderUri.Host + $placeholderUri.AbsolutePath
            )
            $releaseUrlHasPlaceholder = (
                $canonicalReleaseLocation -match
                    '(?i)(?:^|/)(?:OWNER|REPO|TAG)(?:/|$)'
            )
        }
    }
    return (
        [string]::IsNullOrWhiteSpace($Value) -or
        $Value -match "@@[^@\r\n]+@@" -or
        $Value -match "__[A-Z0-9_]+__" -or
        $Value -match "(?i)\b(?:TODO|TBD|CHANGEME)\b" -or
        $releaseUrlHasPlaceholder
    )
}

function Get-BinaryInventoryFileType {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $extension = [System.IO.Path]::GetExtension($RelativePath).ToLowerInvariant()
    if ($extension -eq ".exe") { return "native-executable" }
    if ($extension -eq ".dll") { return "native-library" }
    if ($extension -eq ".pyd") { return "python-extension" }
    if ($extension -eq ".pyc") { return "python-bytecode" }
    if (
        $extension -in @(".txt", ".md") -and
        $RelativePath -match "(?i)(^|/)(license|copying|notice)"
    ) {
        return "license-or-notice"
    }
    if ($RelativePath -match "(?i)\.dist-info/") {
        return "python-package-metadata"
    }
    return "data-or-source"
}

function Get-InventoryContentSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IEnumerable]$Rows
    )

    # Sort-Object uses the current culture and can order punctuation
    # differently from the generator's ordinal `(casefold, original)` key.
    # The package digest must be byte-for-byte reproducible across locales.
    $ordered = [object[]]@($Rows)
    $comparison = [System.Comparison[object]]{
        param([object]$Left, [object]$Right)

        $leftPath = [string]$Left.path
        $rightPath = [string]$Right.path
        $result = [System.StringComparer]::Ordinal.Compare(
            $leftPath.ToLowerInvariant(),
            $rightPath.ToLowerInvariant()
        )
        if ($result -eq 0) {
            $result = [System.StringComparer]::Ordinal.Compare(
                $leftPath,
                $rightPath
            )
        }
        return $result
    }
    [System.Array]::Sort($ordered, $comparison)
    $stream = [System.IO.MemoryStream]::new()
    $hasher = $null
    try {
        foreach ($row in $ordered) {
            $values = @(
                [string]$row.path,
                [string]([long]$row.size),
                [string]$row.sha256
            )
            for ($index = 0; $index -lt $values.Count; $index += 1) {
                $value = $values[$index]
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($value)
                $stream.Write($bytes, 0, $bytes.Length)
                if ($index -lt 2) {
                    $stream.WriteByte(0)
                }
            }
            $stream.WriteByte(10)
        }
        $stream.Position = 0
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        return (
            $hasher.ComputeHash($stream) |
                ForEach-Object { $_.ToString("x2") }
        ) -join ""
    }
    finally {
        if ($null -ne $hasher) { $hasher.Dispose() }
        $stream.Dispose()
    }
}

function Get-RequiredSbomProperty {
    param(
        [Parameter(Mandatory = $true)]$Properties,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $matches = @($Properties | Where-Object { [string]$_.name -ceq $Name })
    if ($matches.Count -ne 1) {
        throw "$Context must contain exactly one '$Name' property."
    }
    return [string]$matches[0].value
}

function Assert-SbomComponentMatchesMap {
    param(
        [Parameter(Mandatory = $true)][object]$SbomComponent,
        [Parameter(Mandatory = $true)][object]$MapComponent,
        [Parameter(Mandatory = $true)][string]$Context
    )

    if (
        [string]$SbomComponent.name -cne [string]$MapComponent.name -or
        [string]$SbomComponent.version -cne [string]$MapComponent.version
    ) {
        throw "$Context identity does not match the component map."
    }

    $licenses = @($SbomComponent.licenses)
    if ($licenses.Count -ne 1) {
        throw "$Context must contain exactly one license declaration."
    }
    $expressionProperty = $licenses[0].PSObject.Properties["expression"]
    $licenseProperty = $licenses[0].PSObject.Properties["license"]
    $licenseMatches = (
        $null -ne $expressionProperty -and
        $null -eq $licenseProperty -and
        [string]$expressionProperty.Value -ceq [string]$MapComponent.license
    ) -or (
        $null -eq $expressionProperty -and
        $null -ne $licenseProperty -and
        [string]$licenseProperty.Value.name -ceq [string]$MapComponent.license
    )
    if (-not $licenseMatches) {
        throw "$Context license does not match the component map."
    }

    $references = @($SbomComponent.externalReferences)
    if (
        $references.Count -ne 1 -or
        [string]$references[0].type -cne "website" -or
        [string]$references[0].url -cne [string]$MapComponent.source
    ) {
        throw "$Context source reference does not match the component map."
    }

    $mapHasPurl = $null -ne $MapComponent.PSObject.Properties["purl"] -and
        -not [string]::IsNullOrWhiteSpace([string]$MapComponent.purl)
    $sbomHasPurl = $null -ne $SbomComponent.PSObject.Properties["purl"] -and
        -not [string]::IsNullOrWhiteSpace([string]$SbomComponent.purl)
    if (
        $mapHasPurl -ne $sbomHasPurl -or
        ($mapHasPurl -and [string]$SbomComponent.purl -cne [string]$MapComponent.purl)
    ) {
        throw "$Context purl does not match the component map."
    }

    $assetJson = Get-RequiredSbomProperty `
        -Properties @($SbomComponent.properties) `
        -Name "chromamatter:component:license-assets" `
        -Context $Context
    if (@($SbomComponent.properties).Count -ne 1) {
        throw "$Context contains unexpected component properties."
    }
    try {
        $sbomAssets = $assetJson | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "$Context license-asset property is not valid JSON."
    }
    $sbomAssetProperties = @($sbomAssets.PSObject.Properties)
    $mapAssetProperties = @($MapComponent.license_asset_sha256.PSObject.Properties)
    if ($sbomAssetProperties.Count -ne $mapAssetProperties.Count) {
        throw "$Context license-asset hashes do not match the component map."
    }
    foreach ($mapAsset in $mapAssetProperties) {
        $sbomAsset = $sbomAssets.PSObject.Properties[[string]$mapAsset.Name]
        if (
            $null -eq $sbomAsset -or
            [string]$sbomAsset.Value -cne [string]$mapAsset.Value
        ) {
            throw "$Context license-asset hashes do not match the component map."
        }
    }
}

if (Test-IncompleteReleaseValue -Value $CorrespondingSourceUrl -ReleaseUrl) {
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
$correspondingSourceAssetName = [Uri]::UnescapeDataString(
    [System.IO.Path]::GetFileName($sourceUri.AbsolutePath)
)
if ([string]::IsNullOrWhiteSpace($correspondingSourceAssetName)) {
    throw "CorrespondingSourceUrl must identify one release asset."
}
if (Test-IncompleteReleaseValue -Value $CorrespondingSourceArchivePath) {
    throw "CorrespondingSourceArchivePath is required for the final complete source bundle."
}
$correspondingSourceArchiveFullPath = if (
    [System.IO.Path]::IsPathRooted($CorrespondingSourceArchivePath)
) {
    [System.IO.Path]::GetFullPath($CorrespondingSourceArchivePath)
}
else {
    [System.IO.Path]::GetFullPath(
        (Join-Path $repoRoot $CorrespondingSourceArchivePath)
    )
}
if (-not (Test-Path -LiteralPath $correspondingSourceArchiveFullPath -PathType Leaf)) {
    throw "Complete corresponding-source archive is missing: $correspondingSourceArchiveFullPath"
}
$correspondingSourceArchiveLeaf = Split-Path -Leaf $correspondingSourceArchiveFullPath
if (-not $correspondingSourceArchiveLeaf.Equals(
    "ChromaMatter-0.8beta-r32-complete-corresponding-source.zip",
    [System.StringComparison]::Ordinal
)) {
    throw (
        "Complete corresponding-source archive has the wrong release asset name: " +
        $correspondingSourceArchiveLeaf
    )
}
if (-not $correspondingSourceAssetName.Equals(
    $correspondingSourceArchiveLeaf,
    [System.StringComparison]::Ordinal
)) {
    throw (
        "Corresponding source URL asset name does not match the verified archive: " +
        "$correspondingSourceAssetName != $correspondingSourceArchiveLeaf"
    )
}
if (
    (Test-IncompleteReleaseValue -Value $CorrespondingSourceArchiveSha256) -or
    $CorrespondingSourceArchiveSha256 -notmatch "^[0-9A-Fa-f]{64}$"
) {
    throw "CorrespondingSourceArchiveSha256 must be one complete SHA-256 digest."
}
$actualCorrespondingSourceArchiveSha256 = (
    Get-FileHash -LiteralPath $correspondingSourceArchiveFullPath -Algorithm SHA256
).Hash.ToUpperInvariant()
if ($actualCorrespondingSourceArchiveSha256 -ne (
    $CorrespondingSourceArchiveSha256.ToUpperInvariant()
)) {
    throw "Complete corresponding-source archive SHA-256 does not match."
}
if (Test-IncompleteReleaseValue -Value $CorrespondingSourceProjectCommit) {
    throw "CorrespondingSourceProjectCommit is required."
}
if ($CorrespondingSourceProjectCommit -notmatch "^[0-9a-f]{40}$") {
    throw "CorrespondingSourceProjectCommit must be one full lowercase Git commit."
}
if (Test-IncompleteReleaseValue -Value $CorrespondingSourceManifestPath) {
    throw "CorrespondingSourceManifestPath is required."
}
$correspondingSourceManifestFullPath = if (
    [System.IO.Path]::IsPathRooted($CorrespondingSourceManifestPath)
) {
    [System.IO.Path]::GetFullPath($CorrespondingSourceManifestPath)
}
else {
    [System.IO.Path]::GetFullPath(
        (Join-Path $repoRoot $CorrespondingSourceManifestPath)
    )
}
if (-not (Test-Path -LiteralPath $correspondingSourceManifestFullPath -PathType Leaf)) {
    throw "Complete corresponding-source manifest is missing: $correspondingSourceManifestFullPath"
}
$correspondingSourceManifestText = [System.IO.File]::ReadAllText(
    $correspondingSourceManifestFullPath
)
if (Test-IncompleteReleaseValue -Value $correspondingSourceManifestText) {
    throw "Complete corresponding-source manifest contains an incomplete placeholder."
}
try {
    $correspondingSourceManifest = (
        $correspondingSourceManifestText | ConvertFrom-Json -ErrorAction Stop
    )
}
catch {
    throw "Complete corresponding-source manifest is not valid JSON: $($_.Exception.Message)"
}
$knownGapsProperty = $correspondingSourceManifest.PSObject.Properties["known_gaps"]
if (
    [int]$correspondingSourceManifest.schema_version -ne 1 -or
    [string]$correspondingSourceManifest.bundle_id -ne
        "chromamatter-windows-corresponding-source" -or
    [string]$correspondingSourceManifest.bundle_status -ne "release-approved" -or
    $correspondingSourceManifest.deterministic_metadata -ne $true -or
    $null -eq $knownGapsProperty -or
    $null -eq $knownGapsProperty.Value -or
    -not ($knownGapsProperty.Value -is [System.Array]) -or
    @($knownGapsProperty.Value).Count -ne 0
) {
    throw (
        "Complete corresponding-source manifest is not release-approved " +
        "with an empty known_gaps array."
    )
}
$correspondingSourceProjectRows = @(
    $correspondingSourceManifest.components |
        Where-Object { [string]$_.id -eq "chromamatter" }
)
if (
    $correspondingSourceProjectRows.Count -ne 1 -or
    [string]$correspondingSourceProjectRows[0].kind -ne
        "local-git-commit-export" -or
    [string]$correspondingSourceProjectRows[0].commit -ne
        $CorrespondingSourceProjectCommit
) {
    throw "Complete corresponding-source manifest does not match the exact project commit."
}

Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
$correspondingSourceZip = $null
try {
    $correspondingSourceZip = [System.IO.Compression.ZipFile]::OpenRead(
        $correspondingSourceArchiveFullPath
    )
    $archivedManifestEntries = @(
        $correspondingSourceZip.Entries |
            Where-Object {
                $_.FullName.Replace("\", "/") -match
                    "(^|/)COMPONENT_SOURCES[.]json$"
            }
    )
    if ($archivedManifestEntries.Count -ne 1) {
        throw "Complete corresponding-source archive must contain one COMPONENT_SOURCES.json."
    }
    $archivedManifestStream = $null
    $archivedManifestHasher = $null
    try {
        $archivedManifestStream = $archivedManifestEntries[0].Open()
        $archivedManifestHasher = [System.Security.Cryptography.SHA256]::Create()
        $archivedManifestSha256 = (
            $archivedManifestHasher.ComputeHash($archivedManifestStream) |
                ForEach-Object { $_.ToString("X2") }
        ) -join ""
    }
    finally {
        if ($null -ne $archivedManifestHasher) {
            $archivedManifestHasher.Dispose()
        }
        if ($null -ne $archivedManifestStream) {
            $archivedManifestStream.Dispose()
        }
    }
}
catch {
    throw "Complete corresponding-source archive validation failed: $($_.Exception.Message)"
}
finally {
    if ($null -ne $correspondingSourceZip) {
        $correspondingSourceZip.Dispose()
    }
}
$suppliedManifestSha256 = (
    Get-FileHash -LiteralPath $correspondingSourceManifestFullPath -Algorithm SHA256
).Hash.ToUpperInvariant()
if ($archivedManifestSha256 -ne $suppliedManifestSha256) {
    throw "Complete corresponding-source manifest does not byte-match the archive."
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
        @($componentMap.validation.reparse_points_not_traversed).Count -ne 0 -or
        @($componentMap.validation.missing_audited_native_identities).Count -ne 0 -or
        @($componentMap.validation.mismatched_audited_native_identities).Count -ne 0 -or
        @($componentMap.validation.pytetwild_static_closure_violations).Count -ne 0 -or
        @($componentMap.validation.missing_component_license_assets).Count -ne 0 -or
        @($componentMap.validation.invalid_component_license_assets).Count -ne 0
    ) {
        throw "Generated binary component inventory did not pass its fail-closed validation."
    }
    if (
        [string]$componentMap.package.name -ne "ChromaMatter" -or
        [string]$componentMap.package.version -ne "0.8beta-r32"
    ) {
        throw "Generated binary component inventory has the wrong package identity."
    }

    $builtRootPrefix = $builtRoot.TrimEnd([char[]]"\/") +
        [System.IO.Path]::DirectorySeparatorChar
    $actualInventoryRows = [System.Collections.Generic.List[object]]::new()
    $actualInventoryByPath = [System.Collections.Generic.Dictionary[string, object]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($item in @(
        Get-ChildItem -LiteralPath $builtRoot -Recurse -Force |
            Sort-Object FullName
    )) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Built application contains a reparse point: $($item.FullName)"
        }
        if ($item.PSIsContainer) { continue }
        if (-not $item.FullName.StartsWith(
            $builtRootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Built application inventory item escaped its root: $($item.FullName)"
        }
        $relative = $item.FullName.Substring($builtRootPrefix.Length).Replace("\", "/")
        if ($actualInventoryByPath.ContainsKey($relative)) {
            throw "Built application contains a case-colliding path: $relative"
        }
        $actualRow = [pscustomobject]@{
            path = $relative
            size = [long]$item.Length
            sha256 = (
                Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            file_type = Get-BinaryInventoryFileType -RelativePath $relative
        }
        $actualInventoryRows.Add($actualRow)
        $actualInventoryByPath.Add($relative, $actualRow)
    }

    $mapRows = @($componentMap.files)
    if ($mapRows.Count -ne $actualInventoryRows.Count) {
        throw (
            "Generated inventory file count does not match BuiltAppRoot: " +
            "map=$($mapRows.Count), actual=$($actualInventoryRows.Count)."
        )
    }
    $mapByPath = [System.Collections.Generic.Dictionary[string, object]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($row in $mapRows) {
        $relative = [string]$row.path
        if (
            [string]::IsNullOrWhiteSpace($relative) -or
            $relative.Contains("\") -or
            [System.IO.Path]::IsPathRooted($relative) -or
            $relative.Split("/") -contains ".." -or
            $mapByPath.ContainsKey($relative)
        ) {
            throw "Generated inventory contains an unsafe or duplicate path: $relative"
        }
        $mapByPath.Add($relative, $row)
        if (-not $actualInventoryByPath.ContainsKey($relative)) {
            throw "Generated inventory references a file outside BuiltAppRoot: $relative"
        }
        $actual = $actualInventoryByPath[$relative]
        if ([long]$row.size -ne [long]$actual.size) {
            throw "Generated inventory size does not match BuiltAppRoot: $relative"
        }
        if (
            [string]$row.sha256 -cnotmatch "^[0-9a-f]{64}$" -or
            [string]$row.sha256 -cne [string]$actual.sha256
        ) {
            throw "Generated inventory SHA-256 does not match BuiltAppRoot: $relative"
        }
        if ([string]$row.file_type -ne [string]$actual.file_type) {
            throw "Generated inventory file type does not match BuiltAppRoot: $relative"
        }
    }
    foreach ($actual in $actualInventoryRows) {
        if (-not $mapByPath.ContainsKey([string]$actual.path)) {
            throw "Generated inventory omits a BuiltAppRoot file: $($actual.path)"
        }
    }
    $actualNativeCount = @(
        $mapRows | Where-Object {
            [string]$_.file_type -in @(
                "native-executable", "native-library", "python-extension"
            )
        }
    ).Count
    $actualMappedNativeCount = @(
        $mapRows | Where-Object {
            [string]$_.file_type -in @(
                "native-executable", "native-library", "python-extension"
            ) -and @($_.components).Count -gt 0
        }
    ).Count
    if (
        [int]$componentMap.validation.file_count -ne $mapRows.Count -or
        [int]$componentMap.validation.native_file_count -ne $actualNativeCount -or
        [int]$componentMap.validation.mapped_native_file_count -ne $actualMappedNativeCount -or
        $actualMappedNativeCount -ne $actualNativeCount
    ) {
        throw "Generated inventory validation counts do not match BuiltAppRoot."
    }
    $actualPackageDigest = Get-InventoryContentSha256 -Rows $actualInventoryRows
    if ([string]$componentMap.package.content_sha256 -cne $actualPackageDigest) {
        throw "Generated inventory package digest does not match BuiltAppRoot."
    }

    foreach ($identity in $auditedNativeExpectations.Values) {
        $relative = [string]$identity.path
        if (-not $actualInventoryByPath.ContainsKey($relative)) {
            throw "BuiltAppRoot is missing audited native identity: $relative"
        }
        $actual = $actualInventoryByPath[$relative]
        if (
            [string]$actual.path -cne $relative -or
            [long]$actual.size -ne [long]$identity.size -or
            [string]$actual.sha256 -cne [string]$identity.sha256
        ) {
            throw "BuiltAppRoot audited native identity does not match: $relative"
        }
        if (-not $mapByPath.ContainsKey($relative)) {
            throw "Component map is missing audited native identity: $relative"
        }
        $mapIdentity = $mapByPath[$relative]
        $expectedComponents = @(
            @("meshlab", "pymeshlab") + @($identity.components) |
                Sort-Object -Unique -CaseSensitive
        )
        $actualComponents = @(
            $mapIdentity.components |
                ForEach-Object { [string]$_ } |
                Sort-Object -Unique -CaseSensitive
        )
        if (
            @(Compare-Object $expectedComponents $actualComponents -CaseSensitive).Count -ne 0 -or
            [string]$mapIdentity.mapping_basis -cne (
                "pymeshlab-wheel-path+audited-native-identity"
            )
        ) {
            throw "Component map audited native ownership does not match: $relative"
        }
    }

    $componentLicenses = @{}
    $componentsById = @{}
    foreach ($component in @($componentMap.components)) {
        $componentId = [string]$component.id
        if (
            [string]::IsNullOrWhiteSpace($componentId) -or
            $componentLicenses.ContainsKey($componentId)
        ) {
            throw "Generated inventory contains a blank or duplicate component ID."
        }
        $componentLicenses[$componentId] = [string]$component.license
        $componentsById[$componentId] = $component
    }
    foreach ($required in @{
        "chromamatter" = "GPL-3.0-or-later"
        "cpython" = "Python-2.0"
        "cpython-bzip2" = "bzip2-1.0.6"
        "cpython-liblzma" = "LicenseRef-XZ-Utils-Public-Domain"
        "cpython-expat" = "MIT"
        "cpython-libmpdec" = "BSD-2-Clause"
        "pyinstaller" = "(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0"
        "tetgen" = "MIT AND AGPL-3.0-or-later"
        "pymeshlab" = "GPL-3.0-only"
        "qt" = "LGPL-3.0-only"
        "mesa-llvmpipe" = "MIT AND BSL-1.0"
        "llvm-mesa" = "NCSA"
        "lib3mf" = "BSD-2-Clause"
        "lib3mf-cpp-base64" = "Zlib"
        "lib3mf-fast-float" = "MIT"
        "lib3mf-zlib" = "Zlib"
        "lib3mf-libzip" = "BSD-3-Clause"
        "u3d" = "Apache-2.0"
        "u3d-zlib" = "Zlib"
        "u3d-libpng" = "Libpng"
        "u3d-ijg-jpeg" = "IJG"
        "u3d-fnvhash" = "LicenseRef-FNV-Public-Domain"
        "u3d-shewchuk-predicates" = "LicenseRef-Shewchuk-Public-Domain"
        "u3d-wcmatch" = "LicenseRef-WCMATCH-Freeware"
        "u3d-graphics-gems-iv" = "Apache-2.0 AND LicenseRef-Graphics-Gems-Unrestricted"
        "u3d-nick-bobic-quaternion" = "Apache-2.0 AND Zlib"
        "pytetwild" = "MPL-2.0"
        "shapely" = "BSD-3-Clause"
        "geos" = "LGPL-2.1-or-later"
    }.GetEnumerator()) {
        if ($componentLicenses[$required.Key] -ne $required.Value) {
            throw "Generated inventory is missing or mislabels component: $($required.Key)"
        }
    }
    if ($componentsById.ContainsKey("qt-angle")) {
        throw "Generated inventory contains the retired aggregate qt-angle component."
    }
    $qtRuntimeComponent = $componentsById["qt"]
    if (
        [string]$qtRuntimeComponent.version -cne [string]$qtRuntime.version -or
        [string]$qtRuntimeComponent.license -cne [string]$qtRuntime.license_expression -or
        [string]$qtRuntimeComponent.source -cne [string]$qtRuntime.source_url
    ) {
        throw "Generated inventory Qt runtime metadata does not match its manifest."
    }
    $pyMeshLabComponent = $componentsById["pymeshlab"]
    $expectedPyMeshLabSource = (
        "https://github.com/cnr-isti-vclab/PyMeshLab/tree/v" +
        $pinnedPyMeshLabVersion
    )
    if (
        [string]$pyMeshLabComponent.version -cne $pinnedPyMeshLabVersion -or
        [string]$pyMeshLabComponent.source -cne $expectedPyMeshLabSource
    ) {
        throw "Generated inventory PyMeshLab metadata does not match its manifest."
    }
    foreach ($expectedQtComponent in $qtComponentExpectations.GetEnumerator()) {
        $componentId = [string]$expectedQtComponent.Key
        if (-not $componentsById.ContainsKey($componentId)) {
            throw "Generated inventory is missing Qt static component: $componentId"
        }
        $expected = $expectedQtComponent.Value
        $actual = $componentsById[$componentId]
        $hasPurl = $null -ne $actual.PSObject.Properties["purl"] -and
            -not [string]::IsNullOrWhiteSpace([string]$actual.purl)
        if (
            [string]$actual.name -cne [string]$expected.name -or
            [string]$actual.version -cne [string]$expected.version -or
            [string]$actual.license -cne [string]$expected.license -or
            [string]$actual.source -cne [string]$expected.source -or
            $hasPurl
        ) {
            throw "Qt static component metadata does not match its manifest: $componentId"
        }
        $expectedAssets = @($expected.license_assets | Sort-Object -CaseSensitive)
        $actualAssets = @(
            $actual.license_assets |
                ForEach-Object { [string]$_ } |
                Sort-Object -CaseSensitive
        )
        if (@(Compare-Object $expectedAssets $actualAssets -CaseSensitive).Count -ne 0) {
            throw "Qt static component license assets do not match: $componentId"
        }
        $actualAssetHashes = @($actual.license_asset_sha256.PSObject.Properties)
        if ($actualAssetHashes.Count -ne $expectedAssets.Count) {
            throw "Qt static component license asset hashes do not match: $componentId"
        }
        foreach ($asset in $expectedAssets) {
            $hashProperty = $actual.license_asset_sha256.PSObject.Properties[$asset]
            if (
                $null -eq $hashProperty -or
                [string]$hashProperty.Value -cne [string]$qtLicenseExpectations[$asset].sha256
            ) {
                throw "Qt static component license asset hash does not match: $componentId"
            }
        }
    }
    if ($pytetwildRuntimePresent) {
        if (-not $mapByPath.ContainsKey($pytetwildPackagedWrapperPath)) {
            throw "Component map is missing the controlled PyTetWild wrapper."
        }
        $pytetwildWrapperRow = $mapByPath[$pytetwildPackagedWrapperPath]
        $pytetwildWrapperComponents = @(
            $pytetwildWrapperRow.components | ForEach-Object { [string]$_ }
        )
        $pytetwildExpectedSortedComponents = @(
            $pytetwildExpectedComponentIds | Sort-Object -CaseSensitive
        )
        $pytetwildWrapperComponentsMatch = (
            $pytetwildWrapperComponents.Count -eq
                $pytetwildExpectedSortedComponents.Count
        )
        if ($pytetwildWrapperComponentsMatch) {
            for (
                $index = 0
                $index -lt $pytetwildExpectedSortedComponents.Count
                $index += 1
            ) {
                if (
                    [string]$pytetwildWrapperComponents[$index] -cne
                    [string]$pytetwildExpectedSortedComponents[$index]
                ) {
                    $pytetwildWrapperComponentsMatch = $false
                    break
                }
            }
        }
        if (
            [string]$pytetwildWrapperRow.path -cne $pytetwildPackagedWrapperPath -or
            [string]$pytetwildWrapperRow.file_type -cne "python-extension" -or
            [string]$pytetwildWrapperRow.mapping_basis -cne $pytetwildMappingBasis -or
            [string]$pytetwildWrapperRow.sha256 -cne $pytetwildControlledPydSha256 -or
            [string]$pytetwildWrapperRow.sha256 -ceq $pytetwildHistoricalPydSha256 -or
            -not $pytetwildWrapperComponentsMatch
        ) {
            throw "Controlled PyTetWild wrapper mapping does not match the approved closure."
        }
        foreach ($componentId in $pytetwildExpectedComponentIds) {
            if (-not $componentsById.ContainsKey($componentId)) {
                throw "Component map is missing PyTetWild static component: $componentId"
            }
            $expected = $pytetwildComponentExpectations[$componentId]
            $actual = $componentsById[$componentId]
            $hasPurl = $null -ne $actual.PSObject.Properties["purl"] -and
                -not [string]::IsNullOrWhiteSpace([string]$actual.purl)
            $expectedHasPurl = $componentId -ceq "pytetwild"
            if (
                [string]$actual.name -cne [string]$expected.name -or
                [string]$actual.version -cne [string]$expected.version -or
                [string]$actual.license -cne [string]$expected.license -or
                [string]$actual.source -cne [string]$expected.source -or
                $hasPurl -ne $expectedHasPurl -or
                (
                    $expectedHasPurl -and
                    [string]$actual.purl -cne "pkg:pypi/pytetwild@0.3.0"
                )
            ) {
                throw "PyTetWild static component metadata does not match: $componentId"
            }
            $expectedAssets = @($expected.license_assets)
            if ($componentId -ceq "pytetwild") {
                $expectedAssets = @("_internal/licenses/pytetwild/LICENSE") + $expectedAssets
            }
            $actualAssets = @(
                $actual.license_assets | ForEach-Object { [string]$_ }
            )
            $assetsMatch = $actualAssets.Count -eq $expectedAssets.Count
            if ($assetsMatch) {
                for (
                    $index = 0
                    $index -lt $expectedAssets.Count
                    $index += 1
                ) {
                    if (
                        [string]$actualAssets[$index] -cne
                        [string]$expectedAssets[$index]
                    ) {
                        $assetsMatch = $false
                        break
                    }
                }
            }
            if (
                -not $assetsMatch
            ) {
                throw "PyTetWild static component license assets do not match: $componentId"
            }
            $actualAssetHashes = @($actual.license_asset_sha256.PSObject.Properties)
            if ($actualAssetHashes.Count -ne $expectedAssets.Count) {
                throw "PyTetWild static component license hashes do not match: $componentId"
            }
            foreach ($asset in $expectedAssets) {
                $hashProperty = $actual.license_asset_sha256.PSObject.Properties[$asset]
                $expectedHash = if ($asset -ceq "_internal/licenses/pytetwild/LICENSE") {
                    if (-not $mapByPath.ContainsKey($asset)) {
                        throw "Packaged PyTetWild wheel license is missing from the inventory."
                    }
                    [string]$mapByPath[$asset].sha256
                }
                else {
                    [string]$pytetwildLicenseExpectations[$asset].sha256
                }
                if (
                    $null -eq $hashProperty -or
                    [string]$hashProperty.Value -cne $expectedHash
                ) {
                    throw "PyTetWild static component license hash does not match: $componentId"
                }
            }
        }
        foreach ($row in $mapRows) {
            if ([string]$row.path -ceq $pytetwildPackagedWrapperPath) { continue }
            foreach ($componentIdValue in @($row.components)) {
                $componentId = [string]$componentIdValue
                if (
                    $componentId -cne "pytetwild" -and
                    $componentId -in $pytetwildExpectedComponentIds
                ) {
                    throw (
                        "PyTetWild static component is mapped outside the controlled " +
                        "wrapper: $componentId -> $($row.path)"
                    )
                }
            }
        }
    }
    $usedComponentIds = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($row in $mapRows) {
        $rowComponents = @($row.components)
        if (
            [string]$row.file_type -in @(
                "native-executable", "native-library", "python-extension"
            ) -and $rowComponents.Count -eq 0
        ) {
            throw "Generated inventory leaves a native file unmapped: $($row.path)"
        }
        foreach ($componentIdValue in $rowComponents) {
            $componentId = [string]$componentIdValue
            if (-not $componentLicenses.ContainsKey($componentId)) {
                throw (
                    "Generated inventory file references an unknown component " +
                    "'$componentId': $($row.path)"
                )
            }
            [void]$usedComponentIds.Add($componentId)
        }
    }
    foreach ($componentId in $componentLicenses.Keys) {
        if (-not $usedComponentIds.Contains([string]$componentId)) {
            throw "Generated inventory contains an unused component: $componentId"
        }
    }
    foreach ($componentId in $usedComponentIds) {
        $component = $componentsById[$componentId]
        if (
            $null -eq $component.PSObject.Properties["license_assets"] -or
            $null -eq $component.PSObject.Properties["license_asset_sha256"]
        ) {
            throw (
                "Used component '$componentId' must declare license_assets " +
                "and license_asset_sha256."
            )
        }
        $assets = @($component.license_assets)
        if ($assets.Count -eq 0) {
            throw "Used component '$componentId' has empty license_assets."
        }
        $assetSet = [System.Collections.Generic.HashSet[string]]::new(
            [System.StringComparer]::Ordinal
        )
        foreach ($assetValue in $assets) {
            $asset = [string]$assetValue
            if (
                [string]::IsNullOrWhiteSpace($asset) -or
                -not $asset.StartsWith(
                    "_internal/licenses/",
                    [System.StringComparison]::Ordinal
                ) -or
                $asset.Contains("\") -or
                [System.IO.Path]::IsPathRooted($asset) -or
                $asset.Split("/") -contains ".." -or
                -not $assetSet.Add($asset)
            ) {
                throw (
                    "Used component '$componentId' has an unsafe or duplicate " +
                    "license asset path: $asset"
                )
            }
        }
        $hashProperties = @(
            $component.license_asset_sha256.PSObject.Properties
        )
        if ($hashProperties.Count -eq 0) {
            throw "Used component '$componentId' has an empty license_asset_sha256 map."
        }
        $hashKeys = [System.Collections.Generic.HashSet[string]]::new(
            [System.StringComparer]::Ordinal
        )
        foreach ($hashProperty in $hashProperties) {
            $hashAsset = [string]$hashProperty.Name
            if (-not $hashKeys.Add($hashAsset)) {
                throw "Used component '$componentId' has a duplicate asset hash key."
            }
            if (-not $assetSet.Contains($hashAsset)) {
                throw (
                    "Used component '$componentId' has an undeclared license " +
                    "asset hash: $hashAsset"
                )
            }
            $expectedHash = [string]$hashProperty.Value
            if ($expectedHash -cnotmatch "^[0-9a-f]{64}$") {
                throw (
                    "Used component '$componentId' has an invalid license " +
                    "asset SHA-256: $hashAsset"
                )
            }
            if (-not $mapByPath.ContainsKey($hashAsset)) {
                throw (
                    "Used component '$componentId' license asset is not in " +
                    "the generated file inventory: $hashAsset"
                )
            }
            if ([string]$mapByPath[$hashAsset].sha256 -cne $expectedHash) {
                throw (
                    "Used component '$componentId' license asset SHA-256 " +
                    "does not match the generated file inventory: $hashAsset"
                )
            }
        }
        if ($hashKeys.Count -ne $assetSet.Count) {
            $missingHash = @(
                $assetSet | Where-Object { -not $hashKeys.Contains($_) }
            ) | Select-Object -First 1
            throw (
                "Used component '$componentId' is missing a hardcoded " +
                "license asset SHA-256: $missingHash"
            )
        }
    }
    $exeRow = @($componentMap.files | Where-Object { $_.path -eq "ChromaMatter.exe" })
    if (
        $exeRow.Count -ne 1 -or
        @($exeRow[0].components | Where-Object { $_ -eq "chromamatter" }).Count -ne 1 -or
        @($exeRow[0].components | Where-Object { $_ -eq "pyinstaller" }).Count -ne 1 -or
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
$sbomRefs = @($sbom.components | ForEach-Object { [string]$_.'bom-ref' })
foreach ($requiredSbomRef in @(
    "component:cpython",
    "component:cpython-bzip2",
    "component:cpython-liblzma",
    "component:cpython-expat",
    "component:cpython-libmpdec",
    "component:pyinstaller",
    "component:qt",
    "component:mesa-llvmpipe",
    "component:llvm-mesa",
    "component:lib3mf",
    "component:lib3mf-cpp-base64",
    "component:lib3mf-fast-float",
    "component:lib3mf-zlib",
    "component:lib3mf-libzip",
    "component:u3d",
    "component:u3d-zlib",
    "component:u3d-libpng",
    "component:u3d-ijg-jpeg",
    "component:u3d-fnvhash",
    "component:u3d-shewchuk-predicates",
    "component:u3d-wcmatch",
    "component:u3d-graphics-gems-iv",
    "component:u3d-nick-bobic-quaternion"
)) {
    if ($requiredSbomRef -notin $sbomRefs) {
        throw "CycloneDX SBOM is missing required component: $requiredSbomRef"
    }
}

$metadataComponent = $sbom.metadata.component
if (
    $null -eq $metadataComponent -or
    [string]$metadataComponent.'bom-ref' -ne "component:chromamatter" -or
    [string]$metadataComponent.name -ne "ChromaMatter" -or
    [string]$metadataComponent.version -ne "0.8beta-r32"
) {
    throw "CycloneDX SBOM metadata has the wrong application identity."
}
Assert-SbomComponentMatchesMap `
    -SbomComponent $metadataComponent `
    -MapComponent $componentsById["chromamatter"] `
    -Context "CycloneDX application component"
$metadataPackageHashes = @(
    $metadataComponent.hashes | Where-Object { [string]$_.alg -eq "SHA-256" }
)
if (
    $metadataPackageHashes.Count -ne 1 -or
    [string]$metadataPackageHashes[0].content -cne $actualPackageDigest
) {
    throw "CycloneDX SBOM package digest does not match BuiltAppRoot."
}

$sbomLibraryByRef = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($component in @($sbom.components | Where-Object { $_.type -eq "library" })) {
    $reference = [string]$component.'bom-ref'
    if (
        [string]::IsNullOrWhiteSpace($reference) -or
        $sbomLibraryByRef.ContainsKey($reference)
    ) {
        throw "CycloneDX SBOM contains a blank or duplicate library reference."
    }
    $sbomLibraryByRef.Add($reference, $component)
}
$expectedLibraryRefs = @(
    $componentMap.components |
        Where-Object { [string]$_.id -ne "chromamatter" } |
        ForEach-Object { "component:$([string]$_.id)" } |
        Sort-Object
)
$actualLibraryRefs = @($sbomLibraryByRef.Keys | Sort-Object)
if (@(Compare-Object $expectedLibraryRefs $actualLibraryRefs).Count -ne 0) {
    throw "CycloneDX SBOM library components do not match the component map."
}
foreach ($component in @($componentMap.components)) {
    $componentId = [string]$component.id
    if ($componentId -eq "chromamatter") { continue }
    $reference = "component:$componentId"
    $sbomComponent = $sbomLibraryByRef[$reference]
    Assert-SbomComponentMatchesMap `
        -SbomComponent $sbomComponent `
        -MapComponent $component `
        -Context "CycloneDX SBOM library $reference"
}

$sbomFileByRef = [System.Collections.Generic.Dictionary[string, object]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($component in @($sbom.components | Where-Object { $_.type -eq "file" })) {
    $reference = [string]$component.'bom-ref'
    if (
        [string]::IsNullOrWhiteSpace($reference) -or
        $sbomFileByRef.ContainsKey($reference)
    ) {
        throw "CycloneDX SBOM contains a blank or duplicate file reference."
    }
    $sbomFileByRef.Add($reference, $component)
}
if ($sbomFileByRef.Count -ne $mapRows.Count) {
    throw "CycloneDX SBOM file count does not match the component map."
}
foreach ($row in $mapRows) {
    $reference = "file:$([string]$row.path)"
    if (-not $sbomFileByRef.ContainsKey($reference)) {
        throw "CycloneDX SBOM omits component-map file: $($row.path)"
    }
    $sbomFile = $sbomFileByRef[$reference]
    if ([string]$sbomFile.name -cne [string]$row.path) {
        throw "CycloneDX SBOM file name does not match: $($row.path)"
    }
    $fileHashes = @(
        $sbomFile.hashes | Where-Object { [string]$_.alg -eq "SHA-256" }
    )
    if (
        $fileHashes.Count -ne 1 -or
        [string]$fileHashes[0].content -cne [string]$row.sha256
    ) {
        throw "CycloneDX SBOM file hash does not match: $($row.path)"
    }
    $sbomSize = Get-RequiredSbomProperty `
        -Properties @($sbomFile.properties) `
        -Name "chromamatter:file:size" `
        -Context "CycloneDX file $($row.path)"
    $sbomType = Get-RequiredSbomProperty `
        -Properties @($sbomFile.properties) `
        -Name "chromamatter:file:type" `
        -Context "CycloneDX file $($row.path)"
    if (
        $sbomSize -cne [string]([long]$row.size) -or
        $sbomType -cne [string]$row.file_type
    ) {
        throw "CycloneDX SBOM file metadata does not match: $($row.path)"
    }
    $componentProperties = @(
        $sbomFile.properties |
            Where-Object { [string]$_.name -eq "chromamatter:file:components" }
    )
    $expectedComponents = (@($row.components) | ForEach-Object { [string]$_ }) -join ","
    if ($expectedComponents) {
        if (
            $componentProperties.Count -ne 1 -or
            [string]$componentProperties[0].value -cne $expectedComponents
        ) {
            throw "CycloneDX SBOM file component mapping does not match: $($row.path)"
        }
    }
    elseif ($componentProperties.Count -ne 0) {
        throw "CycloneDX SBOM adds an unexpected file component mapping: $($row.path)"
    }
}

$rootDependencies = @(
    $sbom.dependencies |
        Where-Object { [string]$_.ref -eq "component:chromamatter" }
)
if ($rootDependencies.Count -ne 1) {
    throw "CycloneDX SBOM must contain one ChromaMatter dependency root."
}
$actualDependencyRefs = @(
    $rootDependencies[0].dependsOn | ForEach-Object { [string]$_ } | Sort-Object
)
if (@(Compare-Object $expectedLibraryRefs $actualDependencyRefs).Count -ne 0) {
    throw "CycloneDX SBOM dependency root does not match the component map."
}

$sbomValidationProperties = @($sbom.metadata.properties)
foreach ($record in @(
    @("chromamatter:validation:passed", "true"),
    @(
        "chromamatter:validation:unmapped-native-count",
        [string]@($componentMap.validation.unmapped_native_files).Count
    ),
    @(
        "chromamatter:validation:reparse-count",
        [string]@($componentMap.validation.reparse_points_not_traversed).Count
    ),
    @(
        "chromamatter:validation:missing-audited-native-count",
        [string]@($componentMap.validation.missing_audited_native_identities).Count
    ),
    @(
        "chromamatter:validation:mismatched-audited-native-count",
        [string]@($componentMap.validation.mismatched_audited_native_identities).Count
    ),
    @(
        "chromamatter:validation:pytetwild-static-closure-violation-count",
        [string]@($componentMap.validation.pytetwild_static_closure_violations).Count
    ),
    @(
        "chromamatter:validation:missing-license-asset-count",
        [string]@($componentMap.validation.missing_component_license_assets).Count
    ),
    @(
        "chromamatter:validation:invalid-license-asset-count",
        [string]@($componentMap.validation.invalid_component_license_assets).Count
    )
)) {
    $actualValue = Get-RequiredSbomProperty `
        -Properties $sbomValidationProperties `
        -Name $record[0] `
        -Context "CycloneDX metadata"
    if ($actualValue -cne $record[1]) {
        throw "CycloneDX SBOM validation metadata does not match: $($record[0])"
    }
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

# Generic workstation-path fragments are always rejected.  Operator-specific
# identifiers must be supplied outside Git through the optional, semicolon-
# delimited CHROMAMATTER_PRIVATE_AUDIT_TOKENS process environment variable.
# Keeping those values out of this source prevents the denylist itself from
# publishing the private identifiers it is intended to catch.
$payloadUserDirectoryBackslash = "C:" + [char]92 + ("Us" + "ers")
$payloadUserDirectorySlash = "C:/" + ("Us" + "ers")
$payloadDocumentsWorkspaceBackslash = (
    ("Docu" + "ments") + [char]92 + ("Co" + "dex")
)
$payloadDocumentsWorkspaceSlash = (
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
$payloadContentAndPathTokens = @(
    $payloadUserDirectoryBackslash,
    $payloadUserDirectorySlash,
    $payloadDocumentsWorkspaceBackslash,
    $payloadDocumentsWorkspaceSlash
)
$payloadBinaryContentTokens = @(
    $payloadDocumentsWorkspaceBackslash,
    $payloadDocumentsWorkspaceSlash
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
        $configuredPathToken = Find-SoftwarePayloadToken `
            -Value $relative `
            -Tokens ([string[]]$configuredPrivateAuditTokens)
        $displayRelative = if ($null -ne $configuredPathToken) {
            "<redacted-path>"
        }
        else {
            $relative
        }

        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            $violations.Add("reparse point is not allowed: $displayRelative")
            continue
        }

        $pathToken = Find-SoftwarePayloadToken `
            -Value $relative `
            -Tokens ([string[]](
                $payloadContentAndPathTokens + $payloadPathOnlyTokens
        ))
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
        if ($forbiddenPayloadExtensions.Contains($extension)) {
            $violations.Add(
                "forbidden software payload extension '$extension': $displayRelative"
            )
            continue
        }
        try {
            $content = [System.IO.File]::ReadAllText($item.FullName)
        }
        catch {
            if ($payloadTextExtensions.Contains($extension)) {
                $readFailure = if ($displayRelative -eq "<redacted-path>") {
                    "software payload text could not be read: $displayRelative"
                }
                else {
                    "software payload text could not be read: $displayRelative ($($_.Exception.Message))"
                }
                $violations.Add($readFailure)
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
            $violations.Add(
                "forbidden $contentKind token '$contentToken': $displayRelative"
            )
        }
        $configuredContentToken = Find-SoftwarePayloadToken `
            -Value $content `
            -Tokens ([string[]]$configuredPrivateAuditTokens)
        if ($null -ne $configuredContentToken) {
            $contentKind = if ($isTextPayload) { "text" } else { "binary" }
            $violations.Add(
                "forbidden configured private $contentKind token: $displayRelative"
            )
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
    @{ Source = "source/fixed_app/public_binary/README_JA.md"; Destination = "README_JA.md" },
    @{ Source = "source/fixed_app/public_binary/README_EN.md"; Destination = "README_EN.md" },
    @{ Source = "source/fixed_app/public_binary/PRIVACY.md"; Destination = "PRIVACY.md" },
    @{ Source = "source/fixed_app/public_binary/START_CHROMAMATTER.cmd"; Destination = "START_CHROMAMATTER.cmd" },
    @{ Source = "LICENSE"; Destination = "LICENSE.txt" },
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
    @{ Source = "licenses/LICENSE_CPYTHON_BZIP2.txt"; Destination = "licenses/LICENSE_CPYTHON_BZIP2.txt" },
    @{ Source = "licenses/LICENSE_CPYTHON_EXPAT.txt"; Destination = "licenses/LICENSE_CPYTHON_EXPAT.txt" },
    @{ Source = "licenses/LICENSE_CPYTHON_LIBMPDEC.txt"; Destination = "licenses/LICENSE_CPYTHON_LIBMPDEC.txt" },
    @{ Source = "licenses/LICENSE_CPYTHON_XZ.txt"; Destination = "licenses/LICENSE_CPYTHON_XZ.txt" },
    @{ Source = "licenses/LICENSE_LIB3MF.txt"; Destination = "licenses/LICENSE_LIB3MF.txt" },
    @{ Source = "licenses/LICENSE_LIB3MF_CPP_BASE64.txt"; Destination = "licenses/LICENSE_LIB3MF_CPP_BASE64.txt" },
    @{ Source = "licenses/LICENSE_LIB3MF_FAST_FLOAT.txt"; Destination = "licenses/LICENSE_LIB3MF_FAST_FLOAT.txt" },
    @{ Source = "licenses/LICENSE_LIB3MF_LIBZIP.txt"; Destination = "licenses/LICENSE_LIB3MF_LIBZIP.txt" },
    @{ Source = "licenses/LICENSE_LIB3MF_ZLIB.txt"; Destination = "licenses/LICENSE_LIB3MF_ZLIB.txt" },
    @{ Source = "licenses/LICENSE_LLVM_3_6_2.txt"; Destination = "licenses/LICENSE_LLVM_3_6_2.txt" },
    @{ Source = "licenses/LICENSE_MESA_12_0_RC2.html"; Destination = "licenses/LICENSE_MESA_12_0_RC2.html" },
    @{ Source = "licenses/LICENSE_GLEW_2_2_0.txt"; Destination = "licenses/LICENSE_GLEW_2_2_0.txt" },
    @{ Source = "licenses/LICENSE_LIBE57FORMAT_3_1_1.md"; Destination = "licenses/LICENSE_LIBE57FORMAT_3_1_1.md" },
    @{ Source = "licenses/LICENSE_LIBSPATIALINDEX_2_1_0.txt"; Destination = "licenses/LICENSE_LIBSPATIALINDEX_2_1_0.txt" },
    @{ Source = "licenses/LICENSE_MUPARSER_2_3_5.txt"; Destination = "licenses/LICENSE_MUPARSER_2_3_5.txt" },
    @{ Source = "licenses/LICENSE_QT_ANGLE.txt"; Destination = "licenses/LICENSE_QT_ANGLE.txt" },
    @{ Source = "licenses/LICENSE_QT_LGPL_3_0.txt"; Destination = "licenses/LICENSE_QT_LGPL_3_0.txt" },
    @{ Source = "licenses/LICENSE_U3D.txt"; Destination = "licenses/LICENSE_U3D.txt" },
    @{ Source = "licenses/LICENSE_U3D_IJG_JPEG.txt"; Destination = "licenses/LICENSE_U3D_IJG_JPEG.txt" },
    @{ Source = "licenses/LICENSE_U3D_LIBPNG.txt"; Destination = "licenses/LICENSE_U3D_LIBPNG.txt" },
    @{ Source = "licenses/LICENSE_U3D_ZLIB.txt"; Destination = "licenses/LICENSE_U3D_ZLIB.txt" },
    @{ Source = "licenses/NOTICE_MESA_LLVM.txt"; Destination = "licenses/NOTICE_MESA_LLVM.txt" },
    @{ Source = "licenses/NOTICE_QT.txt"; Destination = "licenses/NOTICE_QT.txt" },
    @{ Source = "licenses/NOTICE_SQLITE_PUBLIC_DOMAIN.txt"; Destination = "licenses/NOTICE_SQLITE_PUBLIC_DOMAIN.txt" },
    @{ Source = "licenses/NOTICE_U3D_ADDITIONAL.txt"; Destination = "licenses/NOTICE_U3D_ADDITIONAL.txt" },
    @{ Source = "licenses/NOTICE_U3D_FNVHASH.txt"; Destination = "licenses/NOTICE_U3D_FNVHASH.txt" },
    @{ Source = "licenses/NOTICE_U3D_SHEWCHUK_PREDICATES.txt"; Destination = "licenses/NOTICE_U3D_SHEWCHUK_PREDICATES.txt" },
    @{ Source = "licenses/NOTICE_XERCES_C_3_2_4.txt"; Destination = "licenses/NOTICE_XERCES_C_3_2_4.txt" },
    @{ Source = "licenses/LICENSE_U3D_WCMATCH.txt"; Destination = "licenses/LICENSE_U3D_WCMATCH.txt" },
    @{ Source = "licenses/NOTICE_U3D_GRAPHICS_GEMS_IV.txt"; Destination = "licenses/NOTICE_U3D_GRAPHICS_GEMS_IV.txt" },
    @{ Source = "licenses/LICENSE_U3D_NICK_BOBIC_QUATERNION.txt"; Destination = "licenses/LICENSE_U3D_NICK_BOBIC_QUATERNION.txt" },
    @{ Source = "licenses/LICENSE_RESVG_APACHE_2.0.txt"; Destination = "licenses/LICENSE_RESVG_APACHE_2.0.txt" },
    @{ Source = "licenses/THIRD_PARTY_LICENSES.txt"; Destination = "licenses/THIRD_PARTY_LICENSES.txt" },
    @{ Source = "source/fixed_app/THIRD_PARTY_VOLUME_LICENSES_JA.md"; Destination = "licenses/THIRD_PARTY_VOLUME_LICENSES_JA.md" }
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

function Ensure-SoftwareOutputParent {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (Test-Path -LiteralPath $Path) {
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
            throw "$Label is not a directory: $Path"
        }
        return
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

Ensure-SoftwareOutputParent `
    -Path $destinationParent `
    -Label "Software-package destination parent"
Ensure-SoftwareOutputParent `
    -Path $archiveParent `
    -Label "Software-package archive parent"

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
            Replace("@@CORRESPONDING_SOURCE_URL@@", $CorrespondingSourceUrl).
            Replace(
                "@@CORRESPONDING_SOURCE_ARCHIVE_NAME@@",
                $correspondingSourceArchiveLeaf
            ).
            Replace(
                "@@CORRESPONDING_SOURCE_SHA256@@",
                $actualCorrespondingSourceArchiveSha256
            ).
            Replace(
                "@@CORRESPONDING_SOURCE_PROJECT_COMMIT@@",
                $CorrespondingSourceProjectCommit
            )
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

    $stagingPrefix = (
        $stagingRoot.TrimEnd([char[]]"\/") +
        [System.IO.Path]::DirectorySeparatorChar
    )
    $expectedArchiveRelativeFiles = @(
        Get-ChildItem -LiteralPath $stagingRoot -Recurse -Force -File |
            ForEach-Object {
                if (-not $_.FullName.StartsWith(
                    $stagingPrefix,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) {
                    throw "Software ZIP input escaped the staging root: $($_.FullName)"
                }
                $_.FullName.Substring($stagingPrefix.Length).Replace("\", "/")
            } |
            Sort-Object -CaseSensitive
    )
    $createdArchiveFileCount = New-CanonicalSoftwareZip `
        -Root $stagingRoot `
        -ArchivePath $archiveTemporary `
        -RootName $destinationLeaf
    if ($createdArchiveFileCount -ne $expectedArchiveRelativeFiles.Count) {
        throw (
            "Software ZIP creation file count changed: " +
            "$($expectedArchiveRelativeFiles.Count) -> $createdArchiveFileCount"
        )
    }
    $auditedArchiveFileCount = Test-CanonicalSoftwareZip `
        -ArchivePath $archiveTemporary `
        -ExpectedRootName $destinationLeaf `
        -ExpectedRelativeFiles $expectedArchiveRelativeFiles
    if ($auditedArchiveFileCount -ne $createdArchiveFileCount) {
        throw (
            "Software ZIP audit file count changed: " +
            "$createdArchiveFileCount -> $auditedArchiveFileCount"
        )
    }

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
