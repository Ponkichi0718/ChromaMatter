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
        "artifacts\ChromaMatter-0.9-source-public"
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
    "publication/BINARY_RELEASE_HANDOFF_JA.md",
    "publication/RELEASE_NOTES_r32.1.md",
    "publication/RELEASE_NOTES_r32.2.md"
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
$requiredDemoDataDocumentFiles = @(
    "source/fixed_app/public_binary/DemoData/README_EN.md",
    "source/fixed_app/public_binary/DemoData/README_JA.md",
    "source/fixed_app/public_binary/DemoData/NOTICE_EN.md",
    "source/fixed_app/public_binary/DemoData/NOTICE_JA.md",
    "source/fixed_app/public_binary/DemoData/DEMO_DATA_MANIFEST.json"
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
    "tooling/recipes/BUILD_PYTETWILD_WINDOWS_20260823.ps1",
    "tooling/recipes/README.md",
    "tooling/requirements-pytetwild-build.lock",
    "tooling/patches/pytetwild-0.3.0-optional-pyvista.patch",
    "tooling/meshlab_windows_external_archives.lock.json",
    "tooling/pytetwild_rebuild_lock.template.json",
    "tooling/stage_corresponding_source.py",
    "tooling/stage_corresponding_source.ps1",
    "tooling/stage_public_source.ps1",
    "tooling/stage_software_package.ps1",
    "tooling/SoftwareZipContract.psm1"
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
    $requiredDemoDataDocumentFiles +
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
) + "DemoData"
foreach ($entry in @(Get-ChildItem -LiteralPath $publicBinaryDirectory -Force)) {
    if (
        ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $entry.Name -notin $allowedPublicBinaryNames -or
        ($entry.Name -ceq "DemoData" -and -not $entry.PSIsContainer) -or
        ($entry.Name -cne "DemoData" -and $entry.PSIsContainer)
    ) {
        throw "Unexpected public-binary entry is not allowlisted: $($entry.Name)"
    }
}
if (@(Get-ChildItem -LiteralPath $publicBinaryDirectory -Force).Count -ne 5) {
    throw "Public-binary directory must contain four files and DemoData."
}

$publicDemoDataDirectory = Join-Path $publicBinaryDirectory "DemoData"
$expectedDemoDataDocumentNames = @(
    $requiredDemoDataDocumentFiles |
        ForEach-Object { Split-Path -Leaf $_ }
)
foreach ($entry in @(Get-ChildItem -LiteralPath $publicDemoDataDirectory -Force)) {
    if (
        $entry.PSIsContainer -or
        ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $entry.Name -notin $expectedDemoDataDocumentNames
    ) {
        throw "Unexpected public DemoData document entry: $($entry.Name)"
    }
}
if (@(Get-ChildItem -LiteralPath $publicDemoDataDirectory -Force -File).Count -ne 5) {
    throw "Public DemoData document directory must contain exactly five files."
}

# The corresponding-source preview carries the canonical allowlist used later
# by the binary stage.  Refuse a malformed, privacy-unsafe, or stale document
# here rather than publishing source that cannot reproduce the software
# package.  ConvertFrom-Json alone is not sufficient for this gate because it
# discards earlier duplicate properties and raw-text scanning misses escaped
# path separators.  The small PS5.1-compatible scanner below validates JSON
# syntax before object materialization, rejects duplicate properties in every
# object, and scans every decoded JSON string for private tokens.
$publicManifestScannerType = (
    [System.Management.Automation.PSTypeName]::new(
        "ChromaMatter.PublicManifestJsonScanner"
    )
).Type
if (-not $publicManifestScannerType) {
    $publicManifestScannerSource = @'
using System;
using System.Collections.Generic;
using System.Text;

namespace ChromaMatter
{
    public sealed class PublicManifestJsonScanner
    {
        private readonly string text;
        private readonly string[] privateTokens;
        private readonly string context;
        private int index;

        private PublicManifestJsonScanner(
            string text,
            string[] privateTokens,
            string context)
        {
            if (text == null)
            {
                throw new ArgumentNullException("text");
            }
            this.text = text;
            this.privateTokens = privateTokens ?? new string[0];
            this.context = String.IsNullOrEmpty(context) ? "JSON" : context;
        }

        public static void Validate(
            string text,
            string[] privateTokens,
            string context)
        {
            PublicManifestJsonScanner scanner =
                new PublicManifestJsonScanner(text, privateTokens, context);
            scanner.SkipWhitespace();
            scanner.ParseValue();
            scanner.SkipWhitespace();
            if (scanner.index != scanner.text.Length)
            {
                scanner.Fail("contains data after the top-level JSON value");
            }
        }

        private void ParseValue()
        {
            if (index >= text.Length)
            {
                Fail("ends before a JSON value is complete");
            }

            char current = text[index];
            if (current == '{')
            {
                ParseObject();
            }
            else if (current == '[')
            {
                ParseArray();
            }
            else if (current == '"')
            {
                ParseString();
            }
            else if (current == 't')
            {
                ParseLiteral("true");
            }
            else if (current == 'f')
            {
                ParseLiteral("false");
            }
            else if (current == 'n')
            {
                ParseLiteral("null");
            }
            else if (current == '-' || (current >= '0' && current <= '9'))
            {
                ParseNumber();
            }
            else
            {
                Fail("contains an invalid JSON value");
            }
        }

        private void ParseObject()
        {
            index++;
            SkipWhitespace();
            HashSet<string> names = new HashSet<string>(StringComparer.Ordinal);
            if (TryConsume('}'))
            {
                return;
            }

            while (true)
            {
                if (index >= text.Length || text[index] != '"')
                {
                    Fail("contains an object property without a JSON string name");
                }
                string name = ParseString();
                if (!names.Add(name))
                {
                    Fail("contains a duplicate JSON object property");
                }
                SkipWhitespace();
                Require(':');
                SkipWhitespace();
                ParseValue();
                SkipWhitespace();
                if (TryConsume('}'))
                {
                    return;
                }
                Require(',');
                SkipWhitespace();
            }
        }

        private void ParseArray()
        {
            index++;
            SkipWhitespace();
            if (TryConsume(']'))
            {
                return;
            }

            while (true)
            {
                ParseValue();
                SkipWhitespace();
                if (TryConsume(']'))
                {
                    return;
                }
                Require(',');
                SkipWhitespace();
            }
        }

        private string ParseString()
        {
            Require('"');
            StringBuilder decoded = new StringBuilder();
            while (index < text.Length)
            {
                char current = text[index++];
                if (current == '"')
                {
                    string value = decoded.ToString();
                    AssertNoPrivateToken(value);
                    return value;
                }
                if (current < 0x20)
                {
                    Fail("contains an unescaped control character in a JSON string");
                }
                if (current != '\\')
                {
                    decoded.Append(current);
                    continue;
                }
                if (index >= text.Length)
                {
                    Fail("ends during a JSON string escape");
                }
                char escaped = text[index++];
                switch (escaped)
                {
                    case '"': decoded.Append('"'); break;
                    case '\\': decoded.Append('\\'); break;
                    case '/': decoded.Append('/'); break;
                    case 'b': decoded.Append('\b'); break;
                    case 'f': decoded.Append('\f'); break;
                    case 'n': decoded.Append('\n'); break;
                    case 'r': decoded.Append('\r'); break;
                    case 't': decoded.Append('\t'); break;
                    case 'u': decoded.Append(ParseUnicodeEscape()); break;
                    default:
                        Fail("contains an invalid JSON string escape");
                        break;
                }
            }
            Fail("ends before a JSON string is closed");
            return null;
        }

        private char ParseUnicodeEscape()
        {
            if (index + 4 > text.Length)
            {
                Fail("ends during a JSON Unicode escape");
            }
            int value = 0;
            for (int offset = 0; offset < 4; offset++)
            {
                char current = text[index++];
                int digit;
                if (current >= '0' && current <= '9')
                {
                    digit = current - '0';
                }
                else if (current >= 'a' && current <= 'f')
                {
                    digit = current - 'a' + 10;
                }
                else if (current >= 'A' && current <= 'F')
                {
                    digit = current - 'A' + 10;
                }
                else
                {
                    Fail("contains an invalid JSON Unicode escape");
                    return '\0';
                }
                value = (value * 16) + digit;
            }
            return (char)value;
        }

        private void ParseNumber()
        {
            if (TryConsume('-') && index >= text.Length)
            {
                Fail("ends during a JSON number");
            }
            if (TryConsume('0'))
            {
                if (index < text.Length && text[index] >= '0' && text[index] <= '9')
                {
                    Fail("contains a JSON number with a leading zero");
                }
            }
            else
            {
                RequireDigitOneToNine();
                while (index < text.Length && text[index] >= '0' && text[index] <= '9')
                {
                    index++;
                }
            }
            if (TryConsume('.'))
            {
                RequireDigit();
                while (index < text.Length && text[index] >= '0' && text[index] <= '9')
                {
                    index++;
                }
            }
            if (index < text.Length && (text[index] == 'e' || text[index] == 'E'))
            {
                index++;
                if (index < text.Length && (text[index] == '+' || text[index] == '-'))
                {
                    index++;
                }
                RequireDigit();
                while (index < text.Length && text[index] >= '0' && text[index] <= '9')
                {
                    index++;
                }
            }
        }

        private void ParseLiteral(string literal)
        {
            if (index + literal.Length > text.Length ||
                !String.Equals(
                    text.Substring(index, literal.Length),
                    literal,
                    StringComparison.Ordinal))
            {
                Fail("contains an invalid JSON literal");
            }
            index += literal.Length;
        }

        private void AssertNoPrivateToken(string value)
        {
            foreach (string token in privateTokens)
            {
                if (!String.IsNullOrEmpty(token) &&
                    value.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    Fail("contains a forbidden private token in decoded JSON text");
                }
            }
        }

        private void Require(char expected)
        {
            if (index >= text.Length || text[index] != expected)
            {
                Fail("contains invalid JSON punctuation");
            }
            index++;
        }

        private void RequireDigit()
        {
            if (index >= text.Length || text[index] < '0' || text[index] > '9')
            {
                Fail("contains an incomplete JSON number");
            }
        }

        private void RequireDigitOneToNine()
        {
            if (index >= text.Length || text[index] < '1' || text[index] > '9')
            {
                Fail("contains an invalid JSON number");
            }
            index++;
        }

        private bool TryConsume(char expected)
        {
            if (index < text.Length && text[index] == expected)
            {
                index++;
                return true;
            }
            return false;
        }

        private void SkipWhitespace()
        {
            while (index < text.Length)
            {
                char current = text[index];
                if (current != ' ' && current != '\t' &&
                    current != '\r' && current != '\n')
                {
                    return;
                }
                index++;
            }
        }

        private void Fail(string message)
        {
            throw new InvalidOperationException(context + " " + message + ".");
        }
    }
}
'@
    Add-Type -TypeDefinition $publicManifestScannerSource -Language CSharp
}

function Get-PublicManifestPrivateAuditTokens {
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

$publicManifestUserDirectoryBackslash = "C:" + [char]92 + ("Us" + "ers")
$publicManifestUserDirectorySlash = "C:/" + ("Us" + "ers")
$publicManifestDocumentsWorkspaceBackslash = (
    ("Docu" + "ments") + [char]92 + ("Co" + "dex")
)
$publicManifestDocumentsWorkspaceSlash = (
    ("Docu" + "ments") + "/" + ("Co" + "dex")
)
$publicManifestPrivateTokens = [string[]]@(
    $publicManifestUserDirectoryBackslash,
    $publicManifestUserDirectorySlash,
    $publicManifestDocumentsWorkspaceBackslash,
    $publicManifestDocumentsWorkspaceSlash
) + [string[]]@(Get-PublicManifestPrivateAuditTokens)

function Assert-PublicManifestExactProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Context
    )

    if ($Value -isnot [System.Management.Automation.PSCustomObject]) {
        throw "$Context must be a JSON object."
    }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $wanted = @($Expected | Sort-Object -CaseSensitive)
    if (
        $actual.Count -ne $wanted.Count -or
        @(Compare-Object $wanted $actual -CaseSensitive).Count -ne 0
    ) {
        throw "$Context has missing or unexpected fields."
    }
}

$expectedDemoPayloadSpecs = @(
    [pscustomobject]@{
        Path = "Original AI model Color.glb"
        MediaType = "model/gltf-binary"
        Role = "multipart-glb-demo"
    },
    [pscustomobject]@{
        Path = "Reference.jpg"
        MediaType = "image/jpeg"
        Role = "reference-image"
    }
)
$expectedDemoDocuments = @("README_EN.md", "README_JA.md", "NOTICE_EN.md", "NOTICE_JA.md")

function Read-ValidatedPublicDemoManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $manifestItem = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (
        $manifestItem.PSIsContainer -or
        ($manifestItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "$Context must be a regular file and not a reparse point."
    }
    try {
        $manifestBytes = [System.IO.File]::ReadAllBytes($manifestItem.FullName)
        $manifestText = [System.Text.UTF8Encoding]::new($false, $true).GetString(
            $manifestBytes
        )
    }
    catch {
        throw "$Context is not strict UTF-8 text."
    }
    try {
        [ChromaMatter.PublicManifestJsonScanner]::Validate(
            $manifestText,
            $publicManifestPrivateTokens,
            $Context
        )
    }
    catch {
        throw $_.Exception.Message
    }
    try {
        $manifest = $manifestText | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "$Context is not readable JSON."
    }

    Assert-PublicManifestExactProperties `
        -Value $manifest `
        -Expected @(
            "schema_version", "document_id", "release_status",
            "payload_profile", "expected_documents", "payloads",
            "publication_gate"
        ) `
        -Context $Context
    if (
        $null -eq $manifest.schema_version -or
        $manifest.schema_version.GetType().FullName -notin @(
            "System.Int32", "System.Int64"
        ) -or
        [long]$manifest.schema_version -ne 3 -or
        $manifest.document_id -isnot [string] -or
        [string]$manifest.document_id -cne
            "chromamatter.demo-data.source-only.v1" -or
        $manifest.payload_profile -isnot [string] -or
        [string]$manifest.payload_profile -cne
            "source-model-and-reference-only" -or
        $manifest.release_status -isnot [string] -or
        [string]$manifest.release_status -cne "approved-for-publication"
    ) {
        throw "$Context has the wrong source-only identity or JSON value types."
    }

    if ($manifest.expected_documents -isnot [System.Array]) {
        throw "$Context expected_documents must be a JSON array."
    }
    $manifestDocuments = @($manifest.expected_documents)
    if ($manifestDocuments.Count -ne $expectedDemoDocuments.Count) {
        throw "Canonical DemoData manifest has the wrong document set."
    }
    for ($index = 0; $index -lt $expectedDemoDocuments.Count; $index++) {
        if (
            $manifestDocuments[$index] -isnot [string] -or
            [string]$manifestDocuments[$index] -cne $expectedDemoDocuments[$index]
        ) {
            throw "$Context has the wrong ordered document set."
        }
    }

    if ($manifest.payloads -isnot [System.Array]) {
        throw "$Context payloads must be a JSON array."
    }
    $manifestPayloads = @($manifest.payloads)
    if (@(
        $manifestPayloads | Where-Object {
            $_.path -is [string] -and
            [System.IO.Path]::GetExtension([string]$_.path) -ieq ".3mf"
        }
    ).Count -ne 0) {
        throw "$Context source-only profile forbids every 3MF payload."
    }
    if ($manifestPayloads.Count -ne $expectedDemoPayloadSpecs.Count) {
        throw "$Context must contain exactly 2 payloads."
    }
    for ($index = 0; $index -lt $expectedDemoPayloadSpecs.Count; $index++) {
        $payload = $manifestPayloads[$index]
        $spec = $expectedDemoPayloadSpecs[$index]
        Assert-PublicManifestExactProperties `
            -Value $payload `
            -Expected @("path", "bytes", "sha256", "media_type", "role") `
            -Context "$Context payload record $($index + 1)"
        if (
            $payload.path -isnot [string] -or
            [string]$payload.path -cne [string]$spec.Path -or
            $payload.media_type -isnot [string] -or
            [string]$payload.media_type -cne [string]$spec.MediaType -or
            $payload.role -isnot [string] -or
            [string]$payload.role -cne [string]$spec.Role
        ) {
            throw "$Context payload record $($index + 1) has the wrong identity."
        }
        if (
            $null -eq $payload.bytes -or
            $payload.bytes.GetType().FullName -notin @(
                "System.Int32", "System.Int64"
            ) -or
            [long]$payload.bytes -le 0
        ) {
            throw "$Context payload byte size must be a positive JSON integer."
        }
        if (
            $payload.sha256 -isnot [string] -or
            [string]$payload.sha256 -cnotmatch "^[0-9a-f]{64}$"
        ) {
            throw "$Context payload SHA-256 must be lowercase hexadecimal."
        }
    }

    $demoGate = $manifest.publication_gate
    Assert-PublicManifestExactProperties `
        -Value $demoGate `
        -Expected @(
            "status", "raw_glb_redistribution_confirmed",
            "reference_image_redistribution_confirmed",
            "hi3d_plan_terms_confirmed",
            "derived_3mf_payloads_included"
        ) `
        -Context "$Context publication gate"
    if (
        $demoGate.status -isnot [string] -or
        [string]$demoGate.status -cne "approved-for-publication" -or
        $demoGate.raw_glb_redistribution_confirmed -isnot [bool] -or
        $demoGate.raw_glb_redistribution_confirmed -ne $true -or
        $demoGate.reference_image_redistribution_confirmed -isnot [bool] -or
        $demoGate.reference_image_redistribution_confirmed -ne $true -or
        $demoGate.hi3d_plan_terms_confirmed -isnot [bool] -or
        $demoGate.hi3d_plan_terms_confirmed -ne $true -or
        $demoGate.derived_3mf_payloads_included -isnot [bool] -or
        $demoGate.derived_3mf_payloads_included -ne $false
    ) {
        throw "$Context publication gate is not strictly approved."
    }
    return $manifest
}

$demoManifestPath = Join-Path $publicDemoDataDirectory "DEMO_DATA_MANIFEST.json"
$demoManifest = Read-ValidatedPublicDemoManifest `
    -Path $demoManifestPath `
    -Context "Canonical DemoData manifest"
$validatedDemoManifestSha256 = (
    Get-FileHash -LiteralPath $demoManifestPath -Algorithm SHA256
).Hash

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
foreach ($relative in $requiredDemoDataDocumentFiles) {
    Copy-PublicFile -RelativePath $relative
}
$stagedDemoManifestPath = Join-Path `
    $temporaryPath `
    "source/fixed_app/public_binary/DemoData/DEMO_DATA_MANIFEST.json"
$stagedDemoManifest = Read-ValidatedPublicDemoManifest `
    -Path $stagedDemoManifestPath `
    -Context "Staged DemoData manifest"
$stagedDemoManifestSha256 = (
    Get-FileHash -LiteralPath $stagedDemoManifestPath -Algorithm SHA256
).Hash
if ($stagedDemoManifestSha256 -cne $validatedDemoManifestSha256) {
    throw (
        "Canonical DemoData manifest changed after validation; " +
        "refusing the public-source stage."
    )
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
