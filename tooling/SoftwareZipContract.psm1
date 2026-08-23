Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop

$script:ZipUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
$script:ZipCp437 = [System.Text.Encoding]::GetEncoding(
    437,
    [System.Text.EncoderFallback]::ExceptionFallback,
    [System.Text.DecoderFallback]::ExceptionFallback
)
$script:WindowsReservedZipSegments = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($name in @(
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
)) {
    [void]$script:WindowsReservedZipSegments.Add($name)
}

function Get-SoftwareZipPathKey {
    param([Parameter(Mandatory = $true)][string]$Name)

    return $Name.Normalize(
        [System.Text.NormalizationForm]::FormC
    ).ToUpperInvariant()
}

function Assert-CanonicalSoftwareZipPath {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedRootName,
        [Parameter(Mandatory = $true)][string]$Context
    )

    if (
        [string]::IsNullOrWhiteSpace($Name) -or
        $Name.IndexOf([char]0) -ge 0 -or
        $Name.Contains("\") -or
        $Name.StartsWith("/", [System.StringComparison]::Ordinal) -or
        $Name -match "^[A-Za-z]:" -or
        [System.IO.Path]::IsPathRooted($Name)
    ) {
        throw "$Context is not a canonical POSIX relative path: $Name"
    }

    $segments = @($Name.Split(
        [char[]]"/",
        [System.StringSplitOptions]::None
    ))
    if (
        $segments.Count -lt 2 -or
        -not $segments[0].Equals(
            $ExpectedRootName,
            [System.StringComparison]::Ordinal
        )
    ) {
        throw "$Context has an unexpected archive root: $Name"
    }

    foreach ($segment in $segments) {
        if (
            [string]::IsNullOrEmpty($segment) -or
            $segment -eq "." -or
            $segment -eq ".." -or
            $segment.Contains(":") -or
            $segment.IndexOfAny([char[]]'<>"|?*') -ge 0 -or
            $segment.EndsWith(".", [System.StringComparison]::Ordinal) -or
            $segment.EndsWith(" ", [System.StringComparison]::Ordinal)
        ) {
            throw "$Context contains an unsafe Windows path segment: $Name"
        }
        foreach ($character in $segment.ToCharArray()) {
            if ([int]$character -lt 32) {
                throw "$Context contains a control character: $Name"
            }
        }
        $deviceStem = $segment.Split([char[]]".", 2)[0]
        if ($script:WindowsReservedZipSegments.Contains($deviceStem)) {
            throw "$Context contains a reserved Windows path segment: $Name"
        }
    }
    return $segments
}

function Assert-SoftwareZipExtraFields {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $offset = 0
    while ($offset -lt $Bytes.Length) {
        if ($Bytes.Length - $offset -lt 4) {
            throw "$Context contains a truncated ZIP extra field."
        }
        $headerId = [System.BitConverter]::ToUInt16($Bytes, $offset)
        $dataSize = [System.BitConverter]::ToUInt16($Bytes, $offset + 2)
        $offset += 4
        if ($dataSize -gt $Bytes.Length - $offset) {
            throw "$Context contains a truncated ZIP extra-field payload."
        }
        # Info-ZIP Unicode Path can make extractors use a name other than the
        # central-directory name.  Software ZIPs use the UTF-8 flag instead.
        if ($headerId -eq 0x7075) {
            throw "$Context contains an ambiguous Unicode Path extra field."
        }
        $offset += $dataSize
    }
}

function Read-ExactSoftwareZipBytes {
    param(
        [Parameter(Mandatory = $true)][System.IO.BinaryReader]$Reader,
        [Parameter(Mandatory = $true)][int]$Count,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $bytes = $Reader.ReadBytes($Count)
    if ($bytes.Length -ne $Count) {
        throw "$Context is truncated."
    }
    # Preserve an empty byte array as a non-null object in the PowerShell
    # pipeline; otherwise a valid zero-length extra/comment field becomes null.
    return ,([byte[]]$bytes)
}

function Test-ByteArraysEqual {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][byte[]]$Left,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][byte[]]$Right
    )

    if ($Left.Length -ne $Right.Length) {
        return $false
    }
    for ($index = 0; $index -lt $Left.Length; $index++) {
        if ($Left[$index] -ne $Right[$index]) {
            return $false
        }
    }
    return $true
}

function ConvertFrom-SoftwareZipNameBytes {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][uint16]$Flags,
        [Parameter(Mandatory = $true)][string]$Context
    )

    if ($Bytes.Length -eq 0 -or $Bytes -contains [byte]0) {
        throw "$Context has an empty or NUL-containing original name."
    }
    $encoding = if (($Flags -band 0x0800) -ne 0) {
        $script:ZipUtf8
    }
    else {
        $script:ZipCp437
    }
    try {
        $name = $encoding.GetString($Bytes)
        $canonicalBytes = $encoding.GetBytes($name)
    }
    catch {
        throw "$Context name encoding is invalid: $($_.Exception.Message)"
    }
    if (-not (Test-ByteArraysEqual -Left $Bytes -Right $canonicalBytes)) {
        throw "$Context original name has a noncanonical byte encoding."
    }
    return $name
}

function Read-SoftwareZipRawRecords {
    param([Parameter(Mandatory = $true)][string]$ArchivePath)

    $stream = [System.IO.File]::Open(
        $ArchivePath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $reader = [System.IO.BinaryReader]::new($stream)
    try {
        if ($stream.Length -lt 22) {
            throw "Software ZIP is too short to contain an end record."
        }
        $tailLength = [int][Math]::Min([int64]65557, $stream.Length)
        [void]$stream.Seek(-$tailLength, [System.IO.SeekOrigin]::End)
        $tail = Read-ExactSoftwareZipBytes `
            -Reader $reader `
            -Count $tailLength `
            -Context "Software ZIP tail"
        $endIndex = -1
        for ($index = $tail.Length - 22; $index -ge 0; $index--) {
            if (
                $tail[$index] -eq 0x50 -and
                $tail[$index + 1] -eq 0x4B -and
                $tail[$index + 2] -eq 0x05 -and
                $tail[$index + 3] -eq 0x06
            ) {
                $commentLength = [System.BitConverter]::ToUInt16(
                    $tail,
                    $index + 20
                )
                if ($index + 22 + $commentLength -eq $tail.Length) {
                    $endIndex = $index
                    break
                }
            }
        }
        if ($endIndex -lt 0) {
            throw "Software ZIP has no unique terminal end record."
        }

        $diskNumber = [System.BitConverter]::ToUInt16($tail, $endIndex + 4)
        $centralDisk = [System.BitConverter]::ToUInt16($tail, $endIndex + 6)
        $entriesOnDisk = [System.BitConverter]::ToUInt16($tail, $endIndex + 8)
        $entryCount = [System.BitConverter]::ToUInt16($tail, $endIndex + 10)
        $centralSize = [System.BitConverter]::ToUInt32($tail, $endIndex + 12)
        $centralOffset = [System.BitConverter]::ToUInt32($tail, $endIndex + 16)
        if (
            $diskNumber -ne 0 -or
            $centralDisk -ne 0 -or
            $entriesOnDisk -ne $entryCount -or
            $entryCount -eq 0xFFFF -or
            $centralSize -eq 0xFFFFFFFFL -or
            $centralOffset -eq 0xFFFFFFFFL
        ) {
            throw "Software ZIP uses unsupported split-disk or ZIP64 directory metadata."
        }
        $endOffset = $stream.Length - $tailLength + $endIndex
        $centralEnd = [int64]$centralOffset + [int64]$centralSize
        if ($centralEnd -ne $endOffset -or $centralEnd -gt $stream.Length) {
            throw "Software ZIP central directory has an invalid extent."
        }

        $records = [System.Collections.Generic.List[object]]::new()
        [void]$stream.Seek([int64]$centralOffset, [System.IO.SeekOrigin]::Begin)
        for ($recordIndex = 0; $recordIndex -lt $entryCount; $recordIndex++) {
            $recordOffset = $stream.Position
            if ($reader.ReadUInt32() -ne 0x02014B50L) {
                throw "Software ZIP central-directory signature is invalid."
            }
            $versionMadeBy = $reader.ReadUInt16()
            [void]$reader.ReadUInt16() # version needed
            $flags = $reader.ReadUInt16()
            $method = $reader.ReadUInt16()
            [void]$reader.ReadUInt16() # time
            [void]$reader.ReadUInt16() # date
            [void]$reader.ReadUInt32() # CRC-32
            $compressedSize = $reader.ReadUInt32()
            $uncompressedSize = $reader.ReadUInt32()
            $nameLength = $reader.ReadUInt16()
            $extraLength = $reader.ReadUInt16()
            $commentLength = $reader.ReadUInt16()
            $diskStart = $reader.ReadUInt16()
            [void]$reader.ReadUInt16() # internal attributes
            $externalAttributes = $reader.ReadUInt32()
            $localOffset = $reader.ReadUInt32()
            if (
                $compressedSize -eq 0xFFFFFFFFL -or
                $uncompressedSize -eq 0xFFFFFFFFL -or
                $localOffset -eq 0xFFFFFFFFL -or
                $diskStart -ne 0
            ) {
                throw "Software ZIP uses unsupported ZIP64 or split entry metadata."
            }
            $nameBytes = Read-ExactSoftwareZipBytes `
                -Reader $reader `
                -Count $nameLength `
                -Context "Software ZIP central name"
            $extraBytes = Read-ExactSoftwareZipBytes `
                -Reader $reader `
                -Count $extraLength `
                -Context "Software ZIP central extra field"
            [void](Read-ExactSoftwareZipBytes `
                -Reader $reader `
                -Count $commentLength `
                -Context "Software ZIP central comment")
            $nextCentralOffset = $stream.Position
            Assert-SoftwareZipExtraFields `
                -Bytes $extraBytes `
                -Context "Software ZIP central entry $recordIndex"
            $name = ConvertFrom-SoftwareZipNameBytes `
                -Bytes $nameBytes `
                -Flags $flags `
                -Context "Software ZIP central entry $recordIndex"

            if (($flags -band 0x0041) -ne 0) {
                throw "Encrypted software ZIP member is forbidden: $name"
            }
            if ($method -notin @(0, 8)) {
                throw "Unsupported software ZIP compression method for: $name"
            }
            if (($externalAttributes -band 0x00000400L) -ne 0) {
                throw "Software ZIP reparse-point member is forbidden: $name"
            }
            if (($externalAttributes -band 0x00000010L) -ne 0) {
                throw "Software ZIP directory member is forbidden: $name"
            }
            $mode = [int](($externalAttributes -shr 16) -band 0xFFFFL)
            $fileType = $mode -band 0xF000
            if ($fileType -eq 0xA000) {
                throw "Software ZIP symlink member is forbidden: $name"
            }
            if ($fileType -notin @(0, 0x8000)) {
                throw "Software ZIP special member is forbidden: $name"
            }

            if ([int64]$localOffset + 30L -gt $stream.Length) {
                throw "Software ZIP local header is outside the archive: $name"
            }
            [void]$stream.Seek([int64]$localOffset, [System.IO.SeekOrigin]::Begin)
            if ($reader.ReadUInt32() -ne 0x04034B50L) {
                throw "Software ZIP local-header signature is invalid: $name"
            }
            [void]$reader.ReadUInt16() # version needed
            $localFlags = $reader.ReadUInt16()
            $localMethod = $reader.ReadUInt16()
            [void]$reader.ReadUInt16() # time
            [void]$reader.ReadUInt16() # date
            [void]$reader.ReadUInt32() # CRC-32
            [void]$reader.ReadUInt32() # compressed size
            [void]$reader.ReadUInt32() # uncompressed size
            $localNameLength = $reader.ReadUInt16()
            $localExtraLength = $reader.ReadUInt16()
            $localNameBytes = Read-ExactSoftwareZipBytes `
                -Reader $reader `
                -Count $localNameLength `
                -Context "Software ZIP local name"
            $localExtraBytes = Read-ExactSoftwareZipBytes `
                -Reader $reader `
                -Count $localExtraLength `
                -Context "Software ZIP local extra field"
            Assert-SoftwareZipExtraFields `
                -Bytes $localExtraBytes `
                -Context "Software ZIP local entry $recordIndex"
            if (
                $localFlags -ne $flags -or
                $localMethod -ne $method -or
                -not (Test-ByteArraysEqual -Left $localNameBytes -Right $nameBytes)
            ) {
                throw "Software ZIP local and central original names or flags disagree: $name"
            }
            if (($localFlags -band 0x0041) -ne 0) {
                throw "Encrypted software ZIP local member is forbidden: $name"
            }
            [void]$stream.Seek($nextCentralOffset, [System.IO.SeekOrigin]::Begin)

            $records.Add([pscustomobject]@{
                Name = $name
                Flags = $flags
                Method = $method
                ExternalAttributes = $externalAttributes
                CompressedSize = [uint64]$compressedSize
                UncompressedSize = [uint64]$uncompressedSize
                CentralOffset = [int64]$recordOffset
            })
        }
        if ($stream.Position -ne $centralEnd) {
            throw "Software ZIP central directory contains trailing or missing records."
        }
        return @($records)
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

function Register-SoftwareZipPath {
    param(
        [Parameter(Mandatory = $true)][string[]]$Segments,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Seen,
        [Parameter(Mandatory = $true)]$KnownAncestors
    )

    $normalizedSegments = @(
        $Segments | ForEach-Object { Get-SoftwareZipPathKey -Name $_ }
    )
    $key = $normalizedSegments -join "/"
    if ($Seen.ContainsKey($key)) {
        throw "Duplicate casefold-equivalent software ZIP member: $Name"
    }
    for ($index = 1; $index -lt $normalizedSegments.Count; $index++) {
        $ancestor = $normalizedSegments[0..($index - 1)] -join "/"
        if ($Seen.ContainsKey($ancestor)) {
            throw "Software ZIP file/ancestor conflict: $Name"
        }
        [void]$KnownAncestors.Add($ancestor)
    }
    if ($KnownAncestors.Contains($key)) {
        throw "Software ZIP file/ancestor conflict: $Name"
    }
    $Seen[$key] = $Name
}

function New-CanonicalSoftwareZip {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][string]$RootName
    )

    if ($RootName.Contains("/") -or $RootName.Contains("\")) {
        throw "Software ZIP root name must be one path segment: $RootName"
    }
    [void](Assert-CanonicalSoftwareZipPath `
        -Name "$RootName/probe" `
        -ExpectedRootName $RootName `
        -Context "Software ZIP root name")
    $rootItem = Get-Item -LiteralPath $Root -ErrorAction Stop
    if (-not $rootItem.PSIsContainer) {
        throw "Software ZIP input is not a directory: $Root"
    }
    if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Software ZIP input root must not be a reparse point: $Root"
    }
    if (Test-Path -LiteralPath $ArchivePath) {
        throw "Refusing to overwrite a software ZIP: $ArchivePath"
    }

    $rootPath = $rootItem.FullName.TrimEnd([char[]]"\/")
    $rootPrefix = $rootPath + [System.IO.Path]::DirectorySeparatorChar
    $seen = @{}
    $knownAncestors = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    $files = [System.Collections.Generic.List[object]]::new()
    foreach ($item in @(
        Get-ChildItem -LiteralPath $rootPath -Recurse -Force |
            Sort-Object FullName
    )) {
        if (
            -not $item.FullName.StartsWith(
                $rootPrefix,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw "Software ZIP input escaped its root: $($item.FullName)"
        }
        $relative = $item.FullName.Substring($rootPrefix.Length).Replace("\", "/")
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Software ZIP input contains a reparse point: $relative"
        }
        if ($item.PSIsContainer) {
            continue
        }
        $archiveName = "$RootName/$relative"
        $segments = Assert-CanonicalSoftwareZipPath `
            -Name $archiveName `
            -ExpectedRootName $RootName `
            -Context "Software ZIP staged path"
        Register-SoftwareZipPath `
            -Segments $segments `
            -Name $archiveName `
            -Seen $seen `
            -KnownAncestors $knownAncestors
        $files.Add([pscustomobject]@{
            Source = $item.FullName
            ArchiveName = $archiveName
        })
    }
    if ($files.Count -eq 0) {
        throw "Software ZIP input contains no files."
    }

    $archiveStream = [System.IO.File]::Open(
        $ArchivePath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    $archive = $null
    try {
        $archive = [System.IO.Compression.ZipArchive]::new(
            $archiveStream,
            [System.IO.Compression.ZipArchiveMode]::Create,
            $false,
            $script:ZipUtf8
        )
        $regularFileAttributes = [System.BitConverter]::ToInt32(
            [System.BitConverter]::GetBytes([uint32]2175008800),
            0
        )
        foreach ($record in @($files | Sort-Object ArchiveName)) {
            $entry = $archive.CreateEntry(
                $record.ArchiveName,
                [System.IO.Compression.CompressionLevel]::Optimal
            )
            $entry.ExternalAttributes = $regularFileAttributes
            $sourceStream = [System.IO.File]::Open(
                $record.Source,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::Read
            )
            $entryStream = $null
            try {
                $entryStream = $entry.Open()
                $sourceStream.CopyTo($entryStream)
            }
            finally {
                if ($null -ne $entryStream) {
                    $entryStream.Dispose()
                }
                $sourceStream.Dispose()
            }
        }
    }
    finally {
        if ($null -ne $archive) {
            $archive.Dispose()
        }
        $archiveStream.Dispose()
    }
    return $files.Count
}

function Test-CanonicalSoftwareZip {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][string]$ExpectedRootName,
        [string[]]$ExpectedRelativeFiles = @()
    )

    $archiveItem = Get-Item -LiteralPath $ArchivePath -ErrorAction Stop
    if ($archiveItem.PSIsContainer) {
        throw "Software ZIP path is not a file: $ArchivePath"
    }
    if (($archiveItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Software ZIP itself must not be a reparse point: $ArchivePath"
    }

    $rawRecords = @(Read-SoftwareZipRawRecords -ArchivePath $archiveItem.FullName)
    if ($rawRecords.Count -eq 0) {
        throw "Software ZIP contains no members."
    }
    $seen = @{}
    $knownAncestors = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($record in $rawRecords) {
        $segments = Assert-CanonicalSoftwareZipPath `
            -Name $record.Name `
            -ExpectedRootName $ExpectedRootName `
            -Context "Software ZIP original member name"
        Register-SoftwareZipPath `
            -Segments $segments `
            -Name $record.Name `
            -Seen $seen `
            -KnownAncestors $knownAncestors
    }

    $stream = [System.IO.File]::Open(
        $archiveItem.FullName,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $archive = $null
    try {
        $archive = [System.IO.Compression.ZipArchive]::new(
            $stream,
            [System.IO.Compression.ZipArchiveMode]::Read,
            $false,
            $script:ZipUtf8
        )
        if ($archive.Entries.Count -ne $rawRecords.Count) {
            throw "Software ZIP raw and decoded member counts disagree."
        }
        for ($index = 0; $index -lt $rawRecords.Count; $index++) {
            $entry = $archive.Entries[$index]
            $raw = $rawRecords[$index]
            if (-not $entry.FullName.Equals(
                $raw.Name,
                [System.StringComparison]::Ordinal
            )) {
                throw "Software ZIP decoded name disagrees with its original raw name."
            }
            if (
                $entry.FullName.EndsWith("/", [System.StringComparison]::Ordinal) -or
                $entry.Name.Length -eq 0
            ) {
                throw "Software ZIP directory member is forbidden: $($entry.FullName)"
            }
            $entryStream = $entry.Open()
            try {
                $buffer = [byte[]]::new(1048576)
                [uint64]$observedLength = 0
                while (($count = $entryStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $observedLength += [uint64]$count
                }
                if ($observedLength -ne [uint64]$entry.Length) {
                    throw "Software ZIP member length changed while reading: $($entry.FullName)"
                }
            }
            finally {
                $entryStream.Dispose()
            }
        }
    }
    finally {
        if ($null -ne $archive) {
            $archive.Dispose()
        }
        $stream.Dispose()
    }

    if ($ExpectedRelativeFiles.Count -gt 0) {
        $expected = [System.Collections.Generic.HashSet[string]]::new(
            [System.StringComparer]::Ordinal
        )
        foreach ($relative in $ExpectedRelativeFiles) {
            $name = "$ExpectedRootName/$relative"
            [void](Assert-CanonicalSoftwareZipPath `
                -Name $name `
                -ExpectedRootName $ExpectedRootName `
                -Context "Expected software ZIP path")
            if (-not $expected.Add($name)) {
                throw "Expected software ZIP paths contain a duplicate: $name"
            }
        }
        if ($expected.Count -ne $rawRecords.Count) {
            throw "Software ZIP member count does not match the staged file set."
        }
        foreach ($record in $rawRecords) {
            if (-not $expected.Contains($record.Name)) {
                throw "Software ZIP contains an unexpected member: $($record.Name)"
            }
        }
    }
    return $rawRecords.Count
}

Export-ModuleMember -Function New-CanonicalSoftwareZip, Test-CanonicalSoftwareZip
