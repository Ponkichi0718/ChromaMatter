[CmdletBinding()]
param(
    [Alias("OutputRoot")]
    [string]$Destination = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop

$repoRoot = (Get-Item -LiteralPath (Split-Path -Parent $PSScriptRoot)).FullName
if (-not $Destination) {
    $Destination = Join-Path `
        $repoRoot `
        "artifacts\ChromaMatter-0.8beta-r32-source-public-20260823"
}
elseif (-not [System.IO.Path]::IsPathRooted($Destination)) {
    $Destination = Join-Path $repoRoot $Destination
}
$destinationPath = [System.IO.Path]::GetFullPath($Destination)

if (Test-Path -LiteralPath $destinationPath) {
    throw "Refusing to overwrite an existing public-source stage: $destinationPath"
}

$requiredRootFiles = @(
    ".gitignore",
    ".gitattributes",
    "BUILD_AND_TEST.ps1",
    "BOOTSTRAP_WINDOWS.ps1",
    "AGENTS.md",
    "HANDOFF.md",
    "RUN_TESTS.cmd",
    "CURRENT_STATE.json",
    "PROVENANCE.md",
    "FEATURES_EN.md",
    "FEATURES_JA.md"
)
$optionalRootFiles = @(
    "README_PUBLIC_JA.md",
    "README_PUBLIC_EN.md",
    "PRIVACY.md"
)
$requiredGithubFiles = @(
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/compatibility_report.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml"
)
$requiredPublicationFiles = @(
    "publication/LEGAL_AND_RIGHTS_JA.md",
    "publication/PRIVATE_SAMPLE_POLICY_JA.md",
    "publication/CLEAN_CLONE_GUIDE_JA.md",
    "publication/VIDEO_VALIDATION_CHECKLIST_JA.md",
    "publication/PUBLICATION_CHECKLIST_JA.md",
    "publication/GITHUB_PUBLICATION_GUIDE_JA.md",
    "publication/INNOVATION_FUND_APPLICATION_DRAFT.md",
    "publication/INNOVATION_FUND_STATUS_JA.md",
    "publication/BINARY_RELEASE_HANDOFF_JA.md"
)
$requiredFixedAppFiles = @(
    "source/fixed_app/TripoSpectrumMapper_fixed.py",
    "source/fixed_app/TripoSpectrumMapper_fixed.spec",
    "source/fixed_app/requirements-build.lock",
    "source/fixed_app/requirements-build.txt",
    "source/fixed_app/START_FIXED.cmd",
    "source/fixed_app/version_info.txt",
    "source/fixed_app/VERSION_POLICY.md",
    "source/fixed_app/README_fixed_ja.md",
    "source/fixed_app/README_fixed_en.md",
    "source/fixed_app/THIRD_PARTY_VOLUME_LICENSES_JA.md",
    "source/fixed_app/orca_paint_vectors.json",
    "source/fixed_app/adaptive_gpu_overlay.py",
    "source/fixed_app/auto_shading.py",
    "source/fixed_app/brush_cursor_hotfix.py",
    "source/fixed_app/rotation_hotfix.py",
    "source/fixed_app/pymeshlab_runtime_hook.py",
    "source/fixed_app/slicer_safety.py",
    "source/fixed_app/smooth_paint.py",
    "source/fixed_app/smooth_paint_hotfix.py",
    "source/fixed_app/spectrum_mapper_hotfix.py",
    "source/fixed_app/surface_resolution_hotfix.py",
    "source/fixed_app/final_shading_hotfix.py",
    "source/fixed_app/test_tetra.obj",
    "source/fixed_app/assets/mixer_model.npz",
    "source/fixed_app/assets/chromamatter_icon_PROVENANCE.md",
    "source/fixed_app/assets/obj_adjuster_icon.ico",
    "source/fixed_app/assets/obj_adjuster_icon.png"
)
$optionalFixedAppFiles = @(
    "source/fixed_app/assets/mixer_model_PROVENANCE.md"
)
$requiredPublicBinaryFiles = @(
    "source/fixed_app/public_binary/README_JA.md",
    "source/fixed_app/public_binary/README_EN.md",
    "source/fixed_app/public_binary/PRIVACY.md",
    "source/fixed_app/public_binary/START_CHROMAMATTER.cmd"
)
$requiredToolingFiles = @(
    "tooling/generate_public_icon.py",
    "tooling/audit_public_tree.ps1",
    "tooling/generate_binary_compliance_inventory.py",
    "tooling/generate_pytetwild_rebuild_lock.py",
    "tooling/pytetwild_static_closure_contract.py",
    "tooling/pymeshlab_audited_native_identities.json",
    "tooling/qt_static_components.json",
    "tooling/pytetwild_static_closure.json",
    "tooling/update_budget_filament_library.py",
    "tooling/corresponding_source_components.json",
    "tooling/BUILD_PYTETWILD_WINDOWS.ps1",
    "tooling/requirements-pytetwild-build.lock",
    "tooling/patches/pytetwild-0.3.0-optional-pyvista.patch",
    "tooling/meshlab_windows_external_archives.lock.json",
    "tooling/pytetwild_rebuild_lock.template.json",
    "tooling/stage_corresponding_source.py",
    "tooling/stage_corresponding_source.ps1",
    "tooling/stage_public_source.ps1",
    "tooling/stage_software_package.ps1"
)
$optionalToolingFiles = @(
    "tooling/build_mixer_model.py"
)
$requiredDirectories = @(
    "licenses",
    "samples",
    "source/fixed_app/licenses",
    "source/fixed_app/spectrum_mapper",
    "source/fixed_app/resources/filament_db"
)

foreach ($relative in (
    $requiredRootFiles +
    $requiredGithubFiles +
    $requiredPublicationFiles +
    $requiredFixedAppFiles +
    $requiredPublicBinaryFiles +
    $requiredToolingFiles
)) {
    $source = Join-Path $repoRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required public-source input is missing: $relative"
    }
}
foreach ($relative in $requiredDirectories) {
    $source = Join-Path $repoRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Required public-source directory is missing: $relative"
    }
}

$publicBinaryDirectory = Join-Path $repoRoot "source/fixed_app/public_binary"
if (-not (Test-Path -LiteralPath $publicBinaryDirectory -PathType Container)) {
    throw "Required public-binary directory is missing: $publicBinaryDirectory"
}
$allowedPublicBinaryNames = @(
    $requiredPublicBinaryFiles |
        ForEach-Object { Split-Path -Leaf $_ }
)
foreach ($entry in @(Get-ChildItem -LiteralPath $publicBinaryDirectory -Force)) {
    if (
        $entry.PSIsContainer -or
        ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $entry.Name -notin $allowedPublicBinaryNames
    ) {
        throw "Unexpected public-binary entry is not allowlisted: $($entry.Name)"
    }
}
if (@(Get-ChildItem -LiteralPath $publicBinaryDirectory -Force -File).Count -ne 4) {
    throw "Public-binary directory must contain exactly four allowlisted files."
}

$destinationParent = Split-Path -Parent $destinationPath
$destinationLeaf = Split-Path -Leaf $destinationPath
if (-not $destinationParent -or -not $destinationLeaf) {
    throw "Public-source destination must have a parent and leaf: $destinationPath"
}
if (Test-Path -LiteralPath $destinationParent) {
    if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
        throw "Public-source destination parent is not a directory: $destinationParent"
    }
}
else {
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
}

$temporaryLeafPrefix = ".$destinationLeaf.staging-$PID-"
$temporaryLeaf = $temporaryLeafPrefix + [Guid]::NewGuid().ToString("N")
$temporaryPath = [System.IO.Path]::GetFullPath((Join-Path (
    $destinationParent
) $temporaryLeaf))
$resolvedDestinationParent = [System.IO.Path]::GetFullPath($destinationParent)
$resolvedTemporaryParent = [System.IO.Path]::GetFullPath(
    (Split-Path -Parent $temporaryPath)
)
$resolvedTemporaryLeaf = Split-Path -Leaf $temporaryPath
$temporaryLeafPattern = (
    "^" +
    [System.Text.RegularExpressions.Regex]::Escape($temporaryLeafPrefix) +
    "[0-9a-fA-F]{32}$"
)
$temporaryPathIsVerified = (
    $resolvedTemporaryParent.Equals(
        $resolvedDestinationParent,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -and
    [System.Text.RegularExpressions.Regex]::IsMatch(
        $resolvedTemporaryLeaf,
        $temporaryLeafPattern
    ) -and
    -not $temporaryPath.Equals(
        $destinationPath,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -and
    -not $temporaryPath.Equals(
        $resolvedDestinationParent,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -and
    -not $temporaryPath.Equals(
        $repoRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    )
)
if (-not $temporaryPathIsVerified) {
    throw "Refusing to use an unverified public-source staging path: $temporaryPath"
}

$temporaryCreated = $false
try {
    New-Item -ItemType Directory -Path $temporaryPath | Out-Null
    $temporaryCreated = $true

function Copy-PublicFile {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $source = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required public-source file is missing: $RelativePath"
    }

    $destination = Join-Path $temporaryPath $RelativePath
    if (Test-Path -LiteralPath $destination) {
        throw "Duplicate public-source destination: $RelativePath"
    }
    $parent = Split-Path -Parent $destination
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $source -Destination $destination
}

function Copy-PublicAlias {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRelativePath,
        [Parameter(Mandatory = $true)][string]$DestinationRelativePath
    )

    $source = Join-Path $repoRoot $SourceRelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required public-source alias input is missing: $SourceRelativePath"
    }
    $destination = Join-Path $temporaryPath $DestinationRelativePath
    if (Test-Path -LiteralPath $destination) {
        throw "Duplicate public-source alias destination: $DestinationRelativePath"
    }
    $parent = Split-Path -Parent $destination
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $source -Destination $destination
}

function Copy-PublicDirectory {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $sourceDirectory = Get-Item -LiteralPath (Join-Path $repoRoot $RelativePath)
    if (-not $sourceDirectory.PSIsContainer) {
        throw "Required public-source directory is missing: $RelativePath"
    }

    $sourcePrefix = (
        $sourceDirectory.FullName.TrimEnd([char[]]"\/") +
        [System.IO.Path]::DirectorySeparatorChar
    )
    foreach ($file in @(
        Get-ChildItem -LiteralPath $sourceDirectory.FullName -Recurse -Force -File |
            Sort-Object FullName
    )) {
        if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse points are not copied into the public stage: $($file.FullName)"
        }
        if (-not $file.FullName.StartsWith(
            $sourcePrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Public-source input escaped its allowed directory: $($file.FullName)"
        }
        $inside = $file.FullName.Substring($sourcePrefix.Length)
        Copy-PublicFile -RelativePath (Join-Path $RelativePath $inside)
    }
}

foreach ($relative in $requiredRootFiles) {
    Copy-PublicFile -RelativePath $relative
}
foreach ($relative in $optionalRootFiles) {
    if (Test-Path -LiteralPath (Join-Path $repoRoot $relative) -PathType Leaf) {
        Copy-PublicFile -RelativePath $relative
    }
}

# GitHub-recognized entry files are generated inside the reviewed stage so
# users never need to mutate a validated tree and invalidate its manifest.
Copy-PublicAlias `
    -SourceRelativePath "README_PUBLIC_EN.md" `
    -DestinationRelativePath "README.md"
Copy-PublicAlias `
    -SourceRelativePath "README_PUBLIC_EN.md" `
    -DestinationRelativePath "README_EN.md"
Copy-PublicAlias `
    -SourceRelativePath "README_PUBLIC_JA.md" `
    -DestinationRelativePath "README_JA.md"
Copy-PublicAlias `
    -SourceRelativePath "licenses/GPL-3.0.txt" `
    -DestinationRelativePath "LICENSE"

foreach ($relative in $requiredPublicationFiles) {
    Copy-PublicFile -RelativePath $relative
}
foreach ($relative in $requiredGithubFiles) {
    Copy-PublicFile -RelativePath $relative
}

Copy-PublicDirectory -RelativePath "licenses"
Copy-PublicDirectory -RelativePath "samples"

foreach ($relative in $requiredFixedAppFiles) {
    Copy-PublicFile -RelativePath $relative
}
foreach ($relative in $optionalFixedAppFiles) {
    if (Test-Path -LiteralPath (Join-Path $repoRoot $relative) -PathType Leaf) {
        Copy-PublicFile -RelativePath $relative
    }
}
Copy-PublicDirectory -RelativePath "source/fixed_app/resources/filament_db"
Copy-PublicDirectory -RelativePath "source/fixed_app/licenses"
foreach ($relative in $requiredPublicBinaryFiles) {
    Copy-PublicFile -RelativePath $relative
}
foreach ($file in @(
    Get-ChildItem -LiteralPath (Join-Path $repoRoot "source/fixed_app/spectrum_mapper") `
        -File -Filter "*.py" |
        Sort-Object Name
)) {
    Copy-PublicFile -RelativePath ("source/fixed_app/spectrum_mapper/" + $file.Name)
}
foreach ($file in @(
    Get-ChildItem -LiteralPath (Join-Path $repoRoot "source/fixed_app") `
        -File -Filter "test_*.py" |
        Sort-Object Name
)) {
    Copy-PublicFile -RelativePath ("source/fixed_app/" + $file.Name)
}
foreach ($file in @(
    Get-ChildItem -LiteralPath (Join-Path $repoRoot "source/fixed_app/tests") `
        -Recurse -File -Filter "*.py" |
        Sort-Object FullName
)) {
    $testsRoot = (
        (Join-Path $repoRoot "source/fixed_app/tests").TrimEnd([char[]]"\/") +
        [System.IO.Path]::DirectorySeparatorChar
    )
    $inside = $file.FullName.Substring($testsRoot.Length)
    Copy-PublicFile -RelativePath (Join-Path "source/fixed_app/tests" $inside)
}
foreach ($relative in $requiredToolingFiles) {
    Copy-PublicFile -RelativePath $relative
}
foreach ($relative in $optionalToolingFiles) {
    if (Test-Path -LiteralPath (Join-Path $repoRoot $relative) -PathType Leaf) {
        Copy-PublicFile -RelativePath $relative
    }
}

$auditScript = Join-Path $temporaryPath "tooling/audit_public_tree.ps1"
& $auditScript -Root $temporaryPath

$manifestName = "SOURCE_MANIFEST_SHA256.txt"
$manifestPath = Join-Path $temporaryPath $manifestName
$temporaryPrefix = (
    $temporaryPath.TrimEnd([char[]]"\/") +
    [System.IO.Path]::DirectorySeparatorChar
)
$manifestLines = Get-ChildItem -LiteralPath $temporaryPath -Recurse -Force -File |
    Where-Object { $_.FullName -ne $manifestPath } |
    ForEach-Object {
        if (-not $_.FullName.StartsWith(
            $temporaryPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Manifest input escaped the public stage: $($_.FullName)"
        }
        $relative = $_.FullName.Substring($temporaryPrefix.Length).Replace("\", "/")
        [pscustomobject]@{
            Relative = $relative
            Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    } |
    Sort-Object Relative |
    ForEach-Object { "$($_.Hash)  $($_.Relative)" }
[System.IO.File]::WriteAllLines(
    $manifestPath,
    [string[]]$manifestLines,
    [System.Text.UTF8Encoding]::new($false)
)

# The second pass also checks the generated relative-path manifest.
& $auditScript -Root $temporaryPath -RequireManifest

    if (Test-Path -LiteralPath $destinationPath) {
        throw "Refusing to overwrite an existing public-source stage: $destinationPath"
    }
    Move-Item -LiteralPath $temporaryPath -Destination $destinationPath
    Write-Host "Public source preview staged without overwriting: $destinationPath"
    Write-Host "SHA-256 manifest: $(Join-Path $destinationPath $manifestName)"
}
finally {
    if ($temporaryCreated -and (Test-Path -LiteralPath $temporaryPath)) {
        $temporaryItem = Get-Item -LiteralPath $temporaryPath -Force -ErrorAction Stop
        if (
            -not $temporaryPathIsVerified -or
            -not $temporaryItem.PSIsContainer -or
            ($temporaryItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not $temporaryItem.FullName.Equals(
                $temporaryPath,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw "Refusing to remove an unverified public-source staging path: $temporaryPath"
        }
        Remove-Item -LiteralPath $temporaryPath -Recurse -Force
    }
}
