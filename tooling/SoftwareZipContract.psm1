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
$script:ThreeMfSmallMemberLimit = 16L * 1024L * 1024L
$script:ThreeMfMeshMemberLimit = 512L * 1024L * 1024L
$script:ThreeMfTotalExpansionLimit = 768L * 1024L * 1024L
$script:ThreeMfCompressionRatioLimit = 200L

if ($null -eq ("ChromaMatter.Release.Crc32Reader" -as [type])) {
    $releaseTypeSource = @"
using System;
using System.IO;
using System.Xml;

namespace ChromaMatter.Release
{
    public sealed class Crc32ReadResult
    {
        public ulong Bytes { get; set; }
        public uint Crc32 { get; set; }
    }

    public static class Crc32Reader
    {
        private static readonly uint[] Table = BuildTable();

        private static uint[] BuildTable()
        {
            var table = new uint[256];
            for (uint index = 0; index < table.Length; index++)
            {
                uint value = index;
                for (int bit = 0; bit < 8; bit++)
                {
                    value = (value & 1U) != 0U
                        ? 0xEDB88320U ^ (value >> 1)
                        : value >> 1;
                }
                table[index] = value;
            }
            return table;
        }

        public static Crc32ReadResult Read(Stream stream)
        {
            return Read(stream, ulong.MaxValue);
        }

        public static Crc32ReadResult Read(Stream stream, ulong maximumBytes)
        {
            if (stream == null) throw new ArgumentNullException("stream");
            var buffer = new byte[1024 * 1024];
            uint crc = 0xFFFFFFFFU;
            ulong bytes = 0U;
            int count;
            while ((count = stream.Read(buffer, 0, buffer.Length)) > 0)
            {
                bytes += (uint)count;
                if (bytes > maximumBytes)
                {
                    throw new InvalidDataException(
                        "Decompressed data exceeds the configured expansion limit."
                    );
                }
                for (int offset = 0; offset < count; offset++)
                {
                    crc = Table[(crc ^ buffer[offset]) & 0xFFU] ^ (crc >> 8);
                }
            }
            return new Crc32ReadResult
            {
                Bytes = bytes,
                Crc32 = crc ^ 0xFFFFFFFFU
            };
        }
    }

    public static class XmlPrivateTokenScanner
    {
        private static void AssertNoPrivateToken(string value, string[] tokens)
        {
            if (String.IsNullOrEmpty(value) || tokens == null) return;
            foreach (string token in tokens)
            {
                if (!String.IsNullOrEmpty(token) &&
                    value.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    throw new InvalidDataException(
                        "Decoded XML contains a forbidden workstation/private token."
                    );
                }
            }
        }

        public static void AssertNoPrivateTokens(
            Stream stream,
            string[] tokens,
            long maximumCharacters)
        {
            if (stream == null) throw new ArgumentNullException("stream");
            var settings = new XmlReaderSettings
            {
                DtdProcessing = DtdProcessing.Prohibit,
                XmlResolver = null,
                CloseInput = false,
                MaxCharactersFromEntities = 0,
                MaxCharactersInDocument = maximumCharacters
            };
            using (XmlReader reader = XmlReader.Create(stream, settings))
            {
                while (reader.Read())
                {
                    if (reader.HasValue)
                    {
                        AssertNoPrivateToken(reader.Value, tokens);
                    }
                    if (reader.NodeType == XmlNodeType.Element)
                    {
                        AssertNoPrivateToken(reader.Name, tokens);
                        AssertNoPrivateToken(reader.NamespaceURI, tokens);
                        if (reader.HasAttributes)
                        {
                            reader.MoveToFirstAttribute();
                            do
                            {
                                AssertNoPrivateToken(reader.Name, tokens);
                                AssertNoPrivateToken(reader.Value, tokens);
                            }
                            while (reader.MoveToNextAttribute());
                            reader.MoveToElement();
                        }
                    }
                }
            }
        }
    }
}
"@
    if ($PSVersionTable.PSEdition -eq "Desktop") {
        Add-Type `
            -TypeDefinition $releaseTypeSource `
            -Language CSharp `
            -ReferencedAssemblies @("System.Xml.dll") `
            -ErrorAction Stop
    }
    else {
        Add-Type `
            -TypeDefinition $releaseTypeSource `
            -Language CSharp `
            -ErrorAction Stop
    }
}

if ($null -eq ("ChromaMatter.Release.StrictJsonScanner" -as [type])) {
    $strictJsonTypeSource = @"
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace ChromaMatter.Release
{
    public static class StrictJsonScanner
    {
        private sealed class Parser
        {
            private readonly string text;
            private readonly string[] tokens;
            private readonly bool rejectDuplicateKeys;
            private int index;
            private int depth;

            public Parser(string text, string[] tokens, bool rejectDuplicateKeys)
            {
                if (text == null) throw new ArgumentNullException("text");
                this.text = text;
                this.tokens = tokens ?? new string[0];
                this.rejectDuplicateKeys = rejectDuplicateKeys;
            }

            public void ParseDocument()
            {
                if (text.Length > 0 && text[0] == '\uFEFF') index++;
                SkipWhitespace();
                ParseValue();
                SkipWhitespace();
                if (index != text.Length)
                {
                    Fail("JSON contains trailing data.");
                }
            }

            private void ParseValue()
            {
                if (index >= text.Length) Fail("JSON value is missing.");
                char value = text[index];
                if (value == '{')
                {
                    ParseObject();
                }
                else if (value == '[')
                {
                    ParseArray();
                }
                else if (value == '"')
                {
                    ParseString();
                }
                else if (value == 't')
                {
                    ParseLiteral("true");
                }
                else if (value == 'f')
                {
                    ParseLiteral("false");
                }
                else if (value == 'n')
                {
                    ParseLiteral("null");
                }
                else if (value == '-' || (value >= '0' && value <= '9'))
                {
                    ParseNumber();
                }
                else
                {
                    Fail("JSON contains an invalid value token.");
                }
            }

            private void ParseObject()
            {
                EnterContainer();
                try
                {
                    index++;
                    SkipWhitespace();
                    var keys = new HashSet<string>(StringComparer.Ordinal);
                    if (Consume('}')) return;
                    while (true)
                    {
                        if (index >= text.Length || text[index] != '"')
                        {
                            Fail("JSON object key is not a string.");
                        }
                        string key = ParseString();
                        if (!keys.Add(key) && rejectDuplicateKeys)
                        {
                            Fail("JSON contains a duplicate object key.");
                        }
                        SkipWhitespace();
                        Expect(':');
                        SkipWhitespace();
                        ParseValue();
                        SkipWhitespace();
                        if (Consume('}')) return;
                        Expect(',');
                        SkipWhitespace();
                    }
                }
                finally
                {
                    depth--;
                }
            }

            private void ParseArray()
            {
                EnterContainer();
                try
                {
                    index++;
                    SkipWhitespace();
                    if (Consume(']')) return;
                    while (true)
                    {
                        ParseValue();
                        SkipWhitespace();
                        if (Consume(']')) return;
                        Expect(',');
                        SkipWhitespace();
                    }
                }
                finally
                {
                    depth--;
                }
            }

            private string ParseString()
            {
                Expect('"');
                var value = new StringBuilder();
                while (index < text.Length)
                {
                    char current = text[index++];
                    if (current == '"')
                    {
                        string decoded = value.ToString();
                        AssertNoPrivateToken(decoded, tokens);
                        return decoded;
                    }
                    if (current < 0x20)
                    {
                        Fail("JSON string contains an unescaped control character.");
                    }
                    if (current != '\\')
                    {
                        if (Char.IsHighSurrogate(current))
                        {
                            if (index >= text.Length || !Char.IsLowSurrogate(text[index]))
                            {
                                Fail("JSON string contains an invalid surrogate pair.");
                            }
                            value.Append(current);
                            value.Append(text[index++]);
                        }
                        else if (Char.IsLowSurrogate(current))
                        {
                            Fail("JSON string contains an invalid surrogate pair.");
                        }
                        else
                        {
                            value.Append(current);
                        }
                        continue;
                    }
                    if (index >= text.Length) Fail("JSON string escape is truncated.");
                    char escape = text[index++];
                    switch (escape)
                    {
                        case '"': value.Append('"'); break;
                        case '\\': value.Append('\\'); break;
                        case '/': value.Append('/'); break;
                        case 'b': value.Append('\b'); break;
                        case 'f': value.Append('\f'); break;
                        case 'n': value.Append('\n'); break;
                        case 'r': value.Append('\r'); break;
                        case 't': value.Append('\t'); break;
                        case 'u':
                            int first = ParseHexQuad();
                            if (first >= 0xD800 && first <= 0xDBFF)
                            {
                                if (
                                    index + 2 > text.Length ||
                                    text[index] != '\\' ||
                                    text[index + 1] != 'u'
                                )
                                {
                                    Fail("JSON string contains an invalid surrogate pair.");
                                }
                                index += 2;
                                int second = ParseHexQuad();
                                if (second < 0xDC00 || second > 0xDFFF)
                                {
                                    Fail("JSON string contains an invalid surrogate pair.");
                                }
                                int codePoint = 0x10000 +
                                    ((first - 0xD800) << 10) +
                                    (second - 0xDC00);
                                value.Append(Char.ConvertFromUtf32(codePoint));
                            }
                            else if (first >= 0xDC00 && first <= 0xDFFF)
                            {
                                Fail("JSON string contains an invalid surrogate pair.");
                            }
                            else
                            {
                                value.Append((char)first);
                            }
                            break;
                        default:
                            Fail("JSON string contains an invalid escape.");
                            break;
                    }
                }
                Fail("JSON string is unterminated.");
                return null;
            }

            private int ParseHexQuad()
            {
                if (index + 4 > text.Length) Fail("JSON Unicode escape is truncated.");
                int result = 0;
                for (int offset = 0; offset < 4; offset++)
                {
                    char digit = text[index++];
                    int value;
                    if (digit >= '0' && digit <= '9') value = digit - '0';
                    else if (digit >= 'a' && digit <= 'f') value = digit - 'a' + 10;
                    else if (digit >= 'A' && digit <= 'F') value = digit - 'A' + 10;
                    else
                    {
                        Fail("JSON Unicode escape contains a non-hex digit.");
                        value = 0;
                    }
                    result = (result << 4) | value;
                }
                return result;
            }

            private void ParseNumber()
            {
                if (Consume('-') && index >= text.Length)
                {
                    Fail("JSON number is truncated.");
                }
                if (Consume('0'))
                {
                    if (index < text.Length && Char.IsDigit(text[index]))
                    {
                        Fail("JSON number contains a leading zero.");
                    }
                }
                else
                {
                    if (index >= text.Length || text[index] < '1' || text[index] > '9')
                    {
                        Fail("JSON number has no integer digits.");
                    }
                    while (index < text.Length && Char.IsDigit(text[index])) index++;
                }
                if (Consume('.'))
                {
                    if (index >= text.Length || !Char.IsDigit(text[index]))
                    {
                        Fail("JSON number has no fractional digits.");
                    }
                    while (index < text.Length && Char.IsDigit(text[index])) index++;
                }
                if (index < text.Length && (text[index] == 'e' || text[index] == 'E'))
                {
                    index++;
                    if (index < text.Length && (text[index] == '+' || text[index] == '-'))
                    {
                        index++;
                    }
                    if (index >= text.Length || !Char.IsDigit(text[index]))
                    {
                        Fail("JSON number has no exponent digits.");
                    }
                    while (index < text.Length && Char.IsDigit(text[index])) index++;
                }
            }

            private void ParseLiteral(string literal)
            {
                if (
                    index + literal.Length > text.Length ||
                    !String.Equals(
                        text.Substring(index, literal.Length),
                        literal,
                        StringComparison.Ordinal
                    )
                )
                {
                    Fail("JSON literal is invalid.");
                }
                index += literal.Length;
            }

            private void SkipWhitespace()
            {
                while (index < text.Length)
                {
                    char value = text[index];
                    if (value != ' ' && value != '\t' && value != '\r' && value != '\n')
                    {
                        return;
                    }
                    index++;
                }
            }

            private bool Consume(char expected)
            {
                if (index < text.Length && text[index] == expected)
                {
                    index++;
                    return true;
                }
                return false;
            }

            private void Expect(char expected)
            {
                if (!Consume(expected))
                {
                    Fail("JSON punctuation is invalid.");
                }
            }

            private void EnterContainer()
            {
                depth++;
                if (depth > 128) Fail("JSON nesting exceeds the supported depth.");
            }

            private static void AssertNoPrivateToken(string value, string[] tokens)
            {
                foreach (string token in tokens)
                {
                    if (
                        !String.IsNullOrEmpty(token) &&
                        value.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0
                    )
                    {
                        throw new InvalidDataException(
                            "Decoded JSON contains a forbidden workstation/private token."
                        );
                    }
                }
            }

            private static void Fail(string message)
            {
                throw new InvalidDataException(message);
            }
        }

        public static void AssertNoPrivateTokens(string text, string[] tokens)
        {
            AssertNoPrivateTokens(text, tokens, true);
        }

        public static void AssertNoPrivateTokens(
            string text,
            string[] tokens,
            bool rejectDuplicateKeys)
        {
            new Parser(text, tokens, rejectDuplicateKeys).ParseDocument();
        }
    }
}
"@
    Add-Type `
        -TypeDefinition $strictJsonTypeSource `
        -Language CSharp `
        -ErrorAction Stop
}

if ($null -eq ("ChromaMatter.Release.ThreeMfMeshValidator" -as [type])) {
    $threeMfMeshTypeSource = @"
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Xml;

namespace ChromaMatter.Release
{
    public static class ThreeMfMeshValidator
    {
        private const string CoreNamespace =
            "http://schemas.microsoft.com/3dmanufacturing/core/2015/02";

        public static string[] Validate(
            Stream stream,
            long maximumCharacters,
            string context)
        {
            if (stream == null) throw new ArgumentNullException("stream");
            if (String.IsNullOrEmpty(context)) context = "3MF object model";
            var settings = new XmlReaderSettings
            {
                DtdProcessing = DtdProcessing.Prohibit,
                XmlResolver = null,
                CloseInput = false,
                MaxCharactersFromEntities = 0,
                MaxCharactersInDocument = maximumCharacters
            };
            var ids = new List<string>();
            var seenIds = new HashSet<string>(StringComparer.Ordinal);
            int modelDepth = -1;
            int resourcesDepth = -1;
            string currentObject = null;
            int objectDepth = -1;
            int meshDepth = -1;
            int verticesDepth = -1;
            int trianglesDepth = -1;
            bool meshSeen = false;
            bool verticesSeen = false;
            bool trianglesSeen = false;
            long vertexCount = 0;
            long triangleCount = 0;
            bool sawRoot = false;
            bool resourcesSeen = false;

            using (XmlReader reader = XmlReader.Create(stream, settings))
            {
                while (reader.Read())
                {
                    if (reader.NodeType == XmlNodeType.Element)
                    {
                        if (!sawRoot)
                        {
                            if (
                                reader.LocalName != "model" ||
                                reader.NamespaceURI != CoreNamespace ||
                                reader.GetAttribute("unit") != "millimeter"
                            )
                            {
                                Fail(context, "has an invalid 3MF model root or unit.");
                            }
                            sawRoot = true;
                            modelDepth = reader.Depth;
                        }

                        if (
                            reader.LocalName == "resources" &&
                            reader.NamespaceURI == CoreNamespace
                        )
                        {
                            if (
                                reader.Depth != modelDepth + 1 ||
                                resourcesSeen ||
                                reader.IsEmptyElement
                            )
                            {
                                Fail(context, "contains empty, duplicate, or misplaced resources.");
                            }
                            resourcesSeen = true;
                            resourcesDepth = reader.Depth;
                        }
                        else if (
                            reader.LocalName == "object" &&
                            reader.NamespaceURI == CoreNamespace
                        )
                        {
                            if (
                                resourcesDepth < 0 ||
                                reader.Depth != resourcesDepth + 1 ||
                                currentObject != null ||
                                reader.IsEmptyElement
                            )
                            {
                                Fail(context, "contains an empty, nested, or misplaced object.");
                            }
                            string id = reader.GetAttribute("id");
                            if (!IsPositiveDecimal(id) || !seenIds.Add(id))
                            {
                                Fail(context, "contains a blank, invalid, or duplicate object id.");
                            }
                            ids.Add(id);
                            currentObject = id;
                            objectDepth = reader.Depth;
                            meshDepth = -1;
                            verticesDepth = -1;
                            trianglesDepth = -1;
                            meshSeen = false;
                            verticesSeen = false;
                            trianglesSeen = false;
                            vertexCount = 0;
                            triangleCount = 0;
                        }
                        else if (
                            reader.LocalName == "mesh" &&
                            reader.NamespaceURI == CoreNamespace
                        )
                        {
                            if (
                                currentObject == null ||
                                reader.Depth != objectDepth + 1 ||
                                meshSeen ||
                                reader.IsEmptyElement
                            )
                            {
                                Fail(context, "contains an empty, duplicate, or misplaced mesh.");
                            }
                            meshSeen = true;
                            meshDepth = reader.Depth;
                        }
                        else if (
                            reader.LocalName == "vertices" &&
                            reader.NamespaceURI == CoreNamespace
                        )
                        {
                            if (
                                meshDepth < 0 ||
                                reader.Depth != meshDepth + 1 ||
                                verticesSeen ||
                                trianglesSeen ||
                                reader.IsEmptyElement
                            )
                            {
                                Fail(context, "contains empty, duplicate, or misplaced vertices.");
                            }
                            verticesSeen = true;
                            verticesDepth = reader.Depth;
                        }
                        else if (
                            reader.LocalName == "triangles" &&
                            reader.NamespaceURI == CoreNamespace
                        )
                        {
                            if (
                                meshDepth < 0 ||
                                reader.Depth != meshDepth + 1 ||
                                !verticesSeen ||
                                trianglesSeen ||
                                reader.IsEmptyElement
                            )
                            {
                                Fail(context, "contains empty, duplicate, or misplaced triangles.");
                            }
                            trianglesSeen = true;
                            trianglesDepth = reader.Depth;
                        }
                        else if (
                            reader.LocalName == "vertex" &&
                            reader.NamespaceURI == CoreNamespace
                        )
                        {
                            if (
                                verticesDepth < 0 ||
                                reader.Depth != verticesDepth + 1 ||
                                !reader.IsEmptyElement
                            )
                            {
                                Fail(context, "contains a misplaced or non-empty vertex.");
                            }
                            ValidateCoordinate(reader.GetAttribute("x"), context);
                            ValidateCoordinate(reader.GetAttribute("y"), context);
                            ValidateCoordinate(reader.GetAttribute("z"), context);
                            checked { vertexCount++; }
                        }
                        else if (
                            reader.LocalName == "triangle" &&
                            reader.NamespaceURI == CoreNamespace
                        )
                        {
                            if (
                                trianglesDepth < 0 ||
                                reader.Depth != trianglesDepth + 1 ||
                                !reader.IsEmptyElement
                            )
                            {
                                Fail(context, "contains a misplaced or non-empty triangle.");
                            }
                            ValidateVertexIndex(reader.GetAttribute("v1"), vertexCount, context);
                            ValidateVertexIndex(reader.GetAttribute("v2"), vertexCount, context);
                            ValidateVertexIndex(reader.GetAttribute("v3"), vertexCount, context);
                            checked { triangleCount++; }
                        }
                        else if (currentObject != null)
                        {
                            if (
                                verticesDepth >= 0 &&
                                reader.Depth == verticesDepth + 1
                            )
                            {
                                Fail(context, "contains an unsupported element directly under vertices.");
                            }
                            if (
                                trianglesDepth >= 0 &&
                                reader.Depth == trianglesDepth + 1
                            )
                            {
                                Fail(context, "contains an unsupported element directly under triangles.");
                            }
                            if (
                                meshDepth >= 0 &&
                                reader.Depth == meshDepth + 1
                            )
                            {
                                Fail(context, "contains an unsupported element directly under mesh.");
                            }
                            if (reader.Depth == objectDepth + 1)
                            {
                                Fail(context, "contains an unsupported element directly under object.");
                            }
                        }
                    }
                    else if (reader.NodeType == XmlNodeType.EndElement)
                    {
                        if (
                            reader.LocalName == "vertices" &&
                            reader.NamespaceURI == CoreNamespace &&
                            reader.Depth == verticesDepth
                        )
                        {
                            verticesDepth = -1;
                        }
                        else if (
                            reader.LocalName == "triangles" &&
                            reader.NamespaceURI == CoreNamespace &&
                            reader.Depth == trianglesDepth
                        )
                        {
                            trianglesDepth = -1;
                        }
                        else if (
                            reader.LocalName == "mesh" &&
                            reader.NamespaceURI == CoreNamespace &&
                            reader.Depth == meshDepth
                        )
                        {
                            if (
                                !verticesSeen ||
                                !trianglesSeen ||
                                vertexCount <= 0 ||
                                triangleCount <= 0
                            )
                            {
                                Fail(context, "contains a mesh without printable vertices and triangles.");
                            }
                            meshDepth = -1;
                        }
                        else if (
                            reader.LocalName == "object" &&
                            reader.NamespaceURI == CoreNamespace &&
                            reader.Depth == objectDepth
                        )
                        {
                            if (!meshSeen || meshDepth >= 0)
                            {
                                Fail(context, "contains an object without one complete mesh.");
                            }
                            currentObject = null;
                            objectDepth = -1;
                        }
                        else if (
                            reader.LocalName == "resources" &&
                            reader.NamespaceURI == CoreNamespace &&
                            reader.Depth == resourcesDepth
                        )
                        {
                            if (currentObject != null)
                            {
                                Fail(context, "contains an incomplete object resource.");
                            }
                            resourcesDepth = -1;
                        }
                    }
                }
            }
            if (
                !sawRoot ||
                !resourcesSeen ||
                resourcesDepth >= 0 ||
                ids.Count == 0 ||
                currentObject != null
            )
            {
                Fail(context, "contains no complete printable mesh objects.");
            }
            return ids.ToArray();
        }

        private static bool IsPositiveDecimal(string value)
        {
            if (String.IsNullOrEmpty(value) || value[0] < '1' || value[0] > '9')
            {
                return false;
            }
            for (int index = 1; index < value.Length; index++)
            {
                if (value[index] < '0' || value[index] > '9') return false;
            }
            return true;
        }

        private static void ValidateCoordinate(string value, string context)
        {
            double parsed;
            if (
                String.IsNullOrEmpty(value) ||
                !Double.TryParse(
                    value,
                    NumberStyles.Float,
                    CultureInfo.InvariantCulture,
                    out parsed
                ) ||
                Double.IsNaN(parsed) ||
                Double.IsInfinity(parsed)
            )
            {
                Fail(context, "contains a vertex with an invalid coordinate.");
            }
        }

        private static void ValidateVertexIndex(
            string value,
            long vertexCount,
            string context)
        {
            long parsed;
            if (
                String.IsNullOrEmpty(value) ||
                !Int64.TryParse(
                    value,
                    NumberStyles.None,
                    CultureInfo.InvariantCulture,
                    out parsed
                ) ||
                parsed < 0 ||
                parsed >= vertexCount
            )
            {
                Fail(context, "contains a triangle with an out-of-range vertex index.");
            }
        }

        private static void Fail(string context, string message)
        {
            throw new InvalidDataException(context + " " + message);
        }
    }
}
"@
    if ($PSVersionTable.PSEdition -eq "Desktop") {
        Add-Type `
            -TypeDefinition $threeMfMeshTypeSource `
            -Language CSharp `
            -ReferencedAssemblies @("System.Xml.dll") `
            -ErrorAction Stop
    }
    else {
        Add-Type `
            -TypeDefinition $threeMfMeshTypeSource `
            -Language CSharp `
            -ErrorAction Stop
    }
}

if ($null -eq ("ChromaMatter.Release.Utf16TokenScanner" -as [type])) {
    $utf16TokenScannerSource = @"
using System;
using System.IO;
using System.Text;

namespace ChromaMatter.Release
{
    public static class Utf16TokenScanner
    {
        public static string Find(string path, string[] tokens)
        {
            if (String.IsNullOrEmpty(path)) throw new ArgumentNullException("path");
            if (tokens == null || tokens.Length == 0) return null;
            int maximumTokenLength = 0;
            foreach (string token in tokens)
            {
                if (!String.IsNullOrEmpty(token))
                {
                    maximumTokenLength = Math.Max(maximumTokenLength, token.Length);
                }
            }
            if (maximumTokenLength == 0) return null;

            foreach (bool bigEndian in new bool[] { false, true })
            {
                foreach (int byteOffset in new int[] { 0, 1 })
                {
                    string found = FindWithEncoding(
                        path,
                        tokens,
                        maximumTokenLength,
                        bigEndian,
                        byteOffset);
                    if (found != null) return found;
                }
            }
            return null;
        }

        private static string FindWithEncoding(
            string path,
            string[] tokens,
            int maximumTokenLength,
            bool bigEndian,
            int byteOffset)
        {
            using (FileStream stream = new FileStream(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read))
            {
                if (stream.Length <= byteOffset) return null;
                stream.Position = byteOffset;
                Encoding encoding = new UnicodeEncoding(
                    bigEndian,
                    false,
                    false);
                using (StreamReader reader = new StreamReader(
                    stream,
                    encoding,
                    false,
                    65536,
                    false))
                {
                    char[] buffer = new char[65536];
                    string tail = String.Empty;
                    int count;
                    while ((count = reader.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        string window = tail + new String(buffer, 0, count);
                        foreach (string token in tokens)
                        {
                            if (!String.IsNullOrEmpty(token) &&
                                window.IndexOf(
                                    token,
                                    StringComparison.OrdinalIgnoreCase) >= 0)
                            {
                                return token;
                            }
                        }
                        int tailLength = Math.Min(
                            Math.Max(0, maximumTokenLength - 1),
                            window.Length);
                        tail = tailLength == 0
                            ? String.Empty
                            : window.Substring(window.Length - tailLength);
                    }
                }
            }
            return null;
        }
    }
}
"@
    Add-Type `
        -TypeDefinition $utf16TokenScannerSource `
        -Language CSharp `
        -ErrorAction Stop
}
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
        $endCommentLength = -1
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
                    $endCommentLength = [int]$commentLength
                    break
                }
            }
        }
        if ($endIndex -lt 0) {
            throw "Software ZIP has no unique terminal end record."
        }
        if ($endCommentLength -ne 0) {
            throw "Software ZIP archive comments are forbidden."
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
            $crc32 = $reader.ReadUInt32()
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
            if ($extraLength -ne 0) {
                throw "Software ZIP central extra fields are forbidden."
            }
            if ($commentLength -ne 0) {
                throw "Software ZIP member comments are forbidden."
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
            if (($flags -band 0x0008) -ne 0) {
                throw "Software ZIP data descriptors are forbidden: $name"
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
            $localCrc32 = $reader.ReadUInt32()
            $localCompressedSize = $reader.ReadUInt32()
            $localUncompressedSize = $reader.ReadUInt32()
            $localNameLength = $reader.ReadUInt16()
            $localExtraLength = $reader.ReadUInt16()
            if ($localExtraLength -ne 0) {
                throw "Software ZIP local extra fields are forbidden: $name"
            }
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
            $localDataEnd = [int64]$stream.Position + [int64]$compressedSize
            if ($localDataEnd -gt [int64]$centralOffset) {
                throw "Software ZIP local member data overlaps the central directory: $name"
            }
            if (
                $localFlags -ne $flags -or
                $localMethod -ne $method -or
                -not (Test-ByteArraysEqual -Left $localNameBytes -Right $nameBytes)
            ) {
                throw "Software ZIP local and central original names or flags disagree: $name"
            }
            if (
                $localCrc32 -ne $crc32 -or
                $localCompressedSize -ne $compressedSize -or
                $localUncompressedSize -ne $uncompressedSize
            ) {
                throw "Software ZIP local and central integrity metadata disagree: $name"
            }
            if (($localFlags -band 0x0041) -ne 0) {
                throw "Encrypted software ZIP local member is forbidden: $name"
            }
            [void]$stream.Seek($nextCentralOffset, [System.IO.SeekOrigin]::Begin)

            $records.Add([pscustomobject]@{
                Name = $name
                Flags = $flags
                Method = $method
                Crc32 = [uint32]$crc32
                ExternalAttributes = $externalAttributes
                CompressedSize = [uint64]$compressedSize
                UncompressedSize = [uint64]$uncompressedSize
                LocalOffset = [int64]$localOffset
                LocalEnd = [int64]$localDataEnd
                CentralOffset = [int64]$recordOffset
            })
        }
        if ($stream.Position -ne $centralEnd) {
            throw "Software ZIP central directory contains trailing or missing records."
        }
        [int64]$expectedLocalOffset = 0
        foreach ($record in @($records | Sort-Object LocalOffset)) {
            if ([int64]$record.LocalOffset -ne $expectedLocalOffset) {
                throw "Software ZIP contains a preamble, gap, or overlapping local member."
            }
            $expectedLocalOffset = [int64]$record.LocalEnd
        }
        if ($expectedLocalOffset -ne [int64]$centralOffset) {
            throw "Software ZIP contains unreferenced data before the central directory."
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
            $false
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
                $integrity = [ChromaMatter.Release.Crc32Reader]::Read(
                    $entryStream
                )
                if ([uint64]$integrity.Bytes -ne [uint64]$entry.Length) {
                    throw "Software ZIP member length changed while reading: $($entry.FullName)"
                }
                if ([uint32]$integrity.Crc32 -ne [uint32]$raw.Crc32) {
                    throw "Software ZIP member CRC-32 mismatch: $($entry.FullName)"
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

function Assert-StringHasNoPrivateTokens {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Tokens,
        [Parameter(Mandatory = $true)][string]$Context
    )

    foreach ($token in $Tokens) {
        if (
            -not [string]::IsNullOrEmpty($token) -and
            $Value.IndexOf(
                $token,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -ge 0
        ) {
            throw "$Context contains a forbidden workstation/private token."
        }
    }
}

function Assert-JsonValueHasNoPrivateTokens {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Tokens,
        [Parameter(Mandatory = $true)][string]$Context,
        [int]$Depth = 0
    )

    if ($null -eq $Value) {
        return
    }
    if ($Depth -gt 64) {
        throw "$Context exceeds the supported JSON nesting depth."
    }
    if ($Value -is [string]) {
        Assert-StringHasNoPrivateTokens `
            -Value ([string]$Value) `
            -Tokens $Tokens `
            -Context $Context
        return
    }
    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($key in $Value.Keys) {
            Assert-StringHasNoPrivateTokens `
                -Value ([string]$key) `
                -Tokens $Tokens `
                -Context $Context
            Assert-JsonValueHasNoPrivateTokens `
                -Value $Value[$key] `
                -Tokens $Tokens `
                -Context $Context `
                -Depth ($Depth + 1)
        }
        return
    }
    if (
        $Value -is [System.Collections.IEnumerable] -and
        $Value -isnot [string]
    ) {
        foreach ($item in $Value) {
            Assert-JsonValueHasNoPrivateTokens `
                -Value $item `
                -Tokens $Tokens `
                -Context $Context `
                -Depth ($Depth + 1)
        }
        return
    }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        foreach ($property in $Value.PSObject.Properties) {
            Assert-StringHasNoPrivateTokens `
                -Value ([string]$property.Name) `
                -Tokens $Tokens `
                -Context $Context
            Assert-JsonValueHasNoPrivateTokens `
                -Value $property.Value `
                -Tokens $Tokens `
                -Context $Context `
                -Depth ($Depth + 1)
        }
    }
}

function Get-ChromaMatterInnermostExceptionMessage {
    param(
        [Parameter(Mandatory = $true)][System.Exception]$Exception
    )

    $current = $Exception
    $message = [string]$current.Message
    for ($depth = 0; $depth -lt 16; $depth++) {
        if ($null -eq $current.InnerException) {
            break
        }
        $current = $current.InnerException
        if (-not [string]::IsNullOrWhiteSpace($current.Message)) {
            $message = [string]$current.Message
        }
    }
    return $message
}

function Assert-ChromaMatterJsonFileNoPrivateTokens {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$PrivateTokens,
        [string]$Context = "JSON file",
        [bool]$RejectDuplicateKeys = $false
    )

    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($item.PSIsContainer) {
        throw "$Context is not a regular file."
    }
    if ([long]$item.Length -gt 64L * 1024L * 1024L) {
        throw "$Context exceeds the supported JSON size limit."
    }
    try {
        $text = [System.IO.File]::ReadAllText(
            $item.FullName,
            [System.Text.UTF8Encoding]::new($false, $true)
        )
        [ChromaMatter.Release.StrictJsonScanner]::AssertNoPrivateTokens(
            $text,
            $PrivateTokens,
            $RejectDuplicateKeys
        )
        $value = $text | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $value) {
            throw "empty JSON"
        }
        Assert-JsonValueHasNoPrivateTokens `
            -Value $value `
            -Tokens $PrivateTokens `
            -Context $Context
    }
    catch {
        $detail = Get-ChromaMatterInnermostExceptionMessage `
            -Exception $_.Exception
        if (
            $detail -like "*forbidden workstation/private token*" -or
            $detail -like "*duplicate object key*" -or
            $detail -like "*supported JSON*"
        ) {
            throw "$Context validation failed: $detail"
        }
        throw "$Context is not readable strict UTF-8 JSON."
    }
}

function Assert-ThreeMfTextHasNoPrivateTokens {
    param(
        [Parameter(Mandatory = $true)]$Entry,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Tokens,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $maxTokenLength = 0
    foreach ($token in $Tokens) {
        if (-not [string]::IsNullOrEmpty($token)) {
            $maxTokenLength = [Math]::Max($maxTokenLength, $token.Length)
        }
    }
    $stream = $Entry.Open()
    $reader = $null
    try {
        $reader = [System.IO.StreamReader]::new(
            $stream,
            [System.Text.UTF8Encoding]::new($false, $true),
            $true,
            65536,
            $false
        )
        $buffer = [char[]]::new(65536)
        $carry = ""
        while (($count = $reader.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $segment = [System.String]::new($buffer, 0, $count)
            $candidate = $carry + $segment
            foreach ($token in $Tokens) {
                if (
                    -not [string]::IsNullOrEmpty($token) -and
                    $candidate.IndexOf(
                        $token,
                        [System.StringComparison]::OrdinalIgnoreCase
                    ) -ge 0
                ) {
                    throw "$Context contains a forbidden workstation/private token."
                }
            }
            $carryLength = [Math]::Min(
                [Math]::Max(0, $maxTokenLength - 1),
                $candidate.Length
            )
            $carry = if ($carryLength -gt 0) {
                $candidate.Substring($candidate.Length - $carryLength)
            }
            else {
                ""
            }
        }
    }
    catch {
        if ($_.Exception.Message -like "*forbidden workstation/private token*") {
            throw
        }
        throw "$Context is not readable strict UTF-8 text."
    }
    finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }
        else {
            $stream.Dispose()
        }
    }
}

function Assert-ThreeMfXmlReadable {
    param(
        [Parameter(Mandatory = $true)]$Entry,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $settings = [System.Xml.XmlReaderSettings]::new()
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $settings.CloseInput = $true
    $stream = $Entry.Open()
    $reader = $null
    try {
        $reader = [System.Xml.XmlReader]::Create($stream, $settings)
        while ($reader.Read()) {
        }
    }
    catch {
        throw "$Context is not readable XML."
    }
    finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }
        else {
            $stream.Dispose()
        }
    }
}

function Assert-XmlReaderNodeHasNoPrivateTokens {
    param(
        [Parameter(Mandatory = $true)][System.Xml.XmlReader]$Reader,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Tokens,
        [Parameter(Mandatory = $true)][string]$Context
    )

    if ($Reader.HasValue) {
        Assert-StringHasNoPrivateTokens `
            -Value ([string]$Reader.Value) `
            -Tokens $Tokens `
            -Context $Context
    }
    if (
        $Reader.NodeType -eq [System.Xml.XmlNodeType]::Element -and
        $Reader.HasAttributes
    ) {
        [void]$Reader.MoveToFirstAttribute()
        do {
            Assert-StringHasNoPrivateTokens `
                -Value ([string]$Reader.Name) `
                -Tokens $Tokens `
                -Context $Context
            Assert-StringHasNoPrivateTokens `
                -Value ([string]$Reader.Value) `
                -Tokens $Tokens `
                -Context $Context
        } while ($Reader.MoveToNextAttribute())
        [void]$Reader.MoveToElement()
    }
}

function Read-ThreeMfXmlDocument {
    param(
        [Parameter(Mandatory = $true)]$Entry,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Tokens,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $settings = [System.Xml.XmlReaderSettings]::new()
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $settings.CloseInput = $true
    $settings.MaxCharactersFromEntities = 0
    $settings.MaxCharactersInDocument = $script:ThreeMfSmallMemberLimit
    $stream = $Entry.Open()
    $reader = $null
    try {
        $reader = [System.Xml.XmlReader]::Create($stream, $settings)
        $document = [System.Xml.XmlDocument]::new()
        $document.XmlResolver = $null
        $document.Load($reader)
        foreach ($node in @($document.SelectNodes("//@* | //text()"))) {
            Assert-StringHasNoPrivateTokens `
                -Value ([string]$node.Value) `
                -Tokens $Tokens `
                -Context $Context
        }
        return ,$document
    }
    catch {
        if ($_.Exception.Message -like "*forbidden workstation/private token*") {
            throw
        }
        throw "$Context is not readable bounded XML."
    }
    finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }
        else {
            $stream.Dispose()
        }
    }
}

function Assert-ThreeMfXmlDecodedContentHasNoPrivateTokens {
    param(
        [Parameter(Mandatory = $true)]$Entry,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Tokens,
        [Parameter(Mandatory = $true)][uint64]$MaximumCharacters,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $stream = $Entry.Open()
    try {
        [ChromaMatter.Release.XmlPrivateTokenScanner]::AssertNoPrivateTokens(
            $stream,
            $Tokens,
            [long]$MaximumCharacters
        )
    }
    catch {
        if ($_.Exception.Message -like "*forbidden workstation/private token*") {
            throw "$Context contains a forbidden workstation/private token."
        }
        throw "$Context is not readable bounded XML."
    }
    finally {
        $stream.Dispose()
    }
}

function Assert-ThreeMfContentTypes {
    param(
        [Parameter(Mandatory = $true)][System.Xml.XmlDocument]$Document,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    $root = $Document.DocumentElement
    if (
        $null -eq $root -or
        $root.LocalName -cne "Types" -or
        $root.NamespaceURI -cne $namespace
    ) {
        throw "$Context has an invalid content-types root element."
    }
    $expected = @{
        rels = "application/vnd.openxmlformats-package.relationships+xml"
        model = "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"
        config = "application/octet-stream"
        json = "application/json"
    }
    $actual = [System.Collections.Generic.Dictionary[string, string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($child in @($root.ChildNodes)) {
        if ($child.NodeType -ne [System.Xml.XmlNodeType]::Element) {
            continue
        }
        if (
            $child.LocalName -cne "Default" -or
            $child.NamespaceURI -cne $namespace
        ) {
            throw "$Context contains an unsupported content-type declaration."
        }
        $extension = [string]$child.GetAttribute("Extension")
        $contentType = [string]$child.GetAttribute("ContentType")
        if (
            [string]::IsNullOrWhiteSpace($extension) -or
            [string]::IsNullOrWhiteSpace($contentType) -or
            $actual.ContainsKey($extension)
        ) {
            throw "$Context contains a blank or duplicate content-type mapping."
        }
        $actual.Add($extension, $contentType)
    }
    if ($actual.Count -ne $expected.Count) {
        throw "$Context does not contain the exact required content-type mappings."
    }
    foreach ($extension in $expected.Keys) {
        if (
            -not $actual.ContainsKey($extension) -or
            $actual[$extension] -cne [string]$expected[$extension]
        ) {
            throw "$Context has a missing or invalid '$extension' content type."
        }
    }
}

function Assert-ThreeMfRelationshipDocument {
    param(
        [Parameter(Mandatory = $true)][System.Xml.XmlDocument]$Document,
        [Parameter(Mandatory = $true)][string]$ExpectedTarget,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    $relationshipType = (
        "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
    )
    $root = $Document.DocumentElement
    if (
        $null -eq $root -or
        $root.LocalName -cne "Relationships" -or
        $root.NamespaceURI -cne $namespace
    ) {
        throw "$Context has an invalid relationships root element."
    }
    $relationships = @(
        $root.ChildNodes |
            Where-Object { $_.NodeType -eq [System.Xml.XmlNodeType]::Element }
    )
    if ($relationships.Count -ne 1) {
        throw "$Context must contain exactly one model relationship."
    }
    $relationship = $relationships[0]
    if (
        $relationship.LocalName -cne "Relationship" -or
        $relationship.NamespaceURI -cne $namespace -or
        [string]::IsNullOrWhiteSpace($relationship.GetAttribute("Id")) -or
        $relationship.GetAttribute("Type") -cne $relationshipType -or
        $relationship.GetAttribute("Target") -cne $ExpectedTarget -or
        $relationship.HasAttribute("TargetMode")
    ) {
        throw "$Context does not reference the exact required internal model target."
    }
    $targetWithoutRoot = $ExpectedTarget.TrimStart([char]"/")
    [void](Assert-CanonicalSoftwareZipPath `
        -Name "__chromamatter_3mf__/$targetWithoutRoot" `
        -ExpectedRootName "__chromamatter_3mf__" `
        -Context $Context)
}

function Get-ThreeMfObjectModelSummary {
    param(
        [Parameter(Mandatory = $true)]$Entry,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Tokens,
        [Parameter(Mandatory = $true)][string]$Context
    )

    Assert-ThreeMfXmlDecodedContentHasNoPrivateTokens `
        -Entry $Entry `
        -Tokens $Tokens `
        -MaximumCharacters ([uint64]$script:ThreeMfMeshMemberLimit) `
        -Context $Context
    $stream = $Entry.Open()
    try {
        $objectIds = [ChromaMatter.Release.ThreeMfMeshValidator]::Validate(
            $stream,
            [long]$script:ThreeMfMeshMemberLimit,
            $Context
        )
    }
    catch {
        $detail = Get-ChromaMatterInnermostExceptionMessage `
            -Exception $_.Exception
        throw "$Context is not a readable bounded 3MF object model: $detail"
    }
    finally {
        $stream.Dispose()
    }
    return ,([pscustomobject]@{
        ObjectIds = [string[]]$objectIds
    })
}

function Assert-ThreeMfMainModel {
    param(
        [Parameter(Mandatory = $true)][System.Xml.XmlDocument]$Document,
        [Parameter(Mandatory = $true)][string[]]$ObjectModelIds,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $coreNamespace = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    $productionNamespace = (
        "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
    )
    $root = $Document.DocumentElement
    if (
        $null -eq $root -or
        $root.LocalName -cne "model" -or
        $root.NamespaceURI -cne $coreNamespace -or
        $root.GetAttribute("unit") -cne "millimeter"
    ) {
        throw "$Context has an invalid 3MF model root or unit."
    }
    $namespaces = [System.Xml.XmlNamespaceManager]::new($Document.NameTable)
    $namespaces.AddNamespace("c", $coreNamespace)
    $mainObjectIds = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    $mainObjects = @($Document.SelectNodes(
        "/c:model/c:resources/c:object",
        $namespaces
    ))
    $exactComponentCount = 0
    foreach ($object in $mainObjects) {
        $id = [string]$object.GetAttribute("id")
        if (
            $id -cnotmatch "^[1-9][0-9]*$" -or
            -not $mainObjectIds.Add($id)
        ) {
            throw "$Context contains a blank, invalid, or duplicate resource id."
        }
        $objectElements = @(
            $object.ChildNodes |
                Where-Object {
                    $_.NodeType -eq [System.Xml.XmlNodeType]::Element
                }
        )
        if (
            $objectElements.Count -ne 1 -or
            $objectElements[0].LocalName -cne "components" -or
            $objectElements[0].NamespaceURI -cne $coreNamespace
        ) {
            throw "$Context has an empty or invalid components container."
        }
        $componentElements = @(
            $objectElements[0].ChildNodes |
                Where-Object {
                    $_.NodeType -eq [System.Xml.XmlNodeType]::Element
                }
        )
        if ($componentElements.Count -eq 0) {
            throw "$Context has an empty or invalid components container."
        }
        foreach ($component in $componentElements) {
            if (
                $component.LocalName -cne "component" -or
                $component.NamespaceURI -cne $coreNamespace
            ) {
                throw "$Context contains an unsupported components child element."
            }
            $exactComponentCount++
        }
    }
    if ($mainObjectIds.Count -eq 0) {
        throw "$Context contains no main resource object."
    }
    $objectModelIdSet = [System.Collections.Generic.HashSet[string]]::new(
        $ObjectModelIds,
        [System.StringComparer]::Ordinal
    )
    $components = @($Document.SelectNodes(
        "/c:model/c:resources/c:object/c:components/c:component",
        $namespaces
    ))
    $allComponents = @($Document.SelectNodes("//c:component", $namespaces))
    $allComponentContainers = @($Document.SelectNodes("//c:components", $namespaces))
    if (
        $components.Count -eq 0 -or
        $components.Count -ne $exactComponentCount -or
        $allComponents.Count -ne $components.Count -or
        $allComponentContainers.Count -ne $mainObjects.Count
    ) {
        throw "$Context contains an empty or misplaced object-model component."
    }
    foreach ($component in $components) {
        $path = [string]$component.GetAttribute("path", $productionNamespace)
        $objectId = [string]$component.GetAttribute("objectid")
        if (
            $path -cne "/3D/Objects/object_1.model" -or
            -not $objectModelIdSet.Contains($objectId)
        ) {
            throw "$Context contains an unresolved object-model component."
        }
    }
    $buildItems = @($Document.SelectNodes("/c:model/c:build/c:item", $namespaces))
    if ($buildItems.Count -eq 0) {
        throw "$Context contains no build item."
    }
    foreach ($item in $buildItems) {
        if (-not $mainObjectIds.Contains([string]$item.GetAttribute("objectid"))) {
            throw "$Context contains an unresolved build-item object reference."
        }
    }
}

function Assert-ThreeMfJsonReadable {
    param(
        [Parameter(Mandatory = $true)]$Entry,
        [Parameter(Mandatory = $true)][string]$Context,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Tokens
    )

    $stream = $Entry.Open()
    $reader = $null
    try {
        $reader = [System.IO.StreamReader]::new(
            $stream,
            [System.Text.UTF8Encoding]::new($false, $true),
            $true,
            65536,
            $false
        )
        $text = $reader.ReadToEnd()
        [ChromaMatter.Release.StrictJsonScanner]::AssertNoPrivateTokens(
            $text,
            $Tokens
        )
        $value = $text | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $value) {
            throw "empty JSON"
        }
        Assert-JsonValueHasNoPrivateTokens `
            -Value $value `
            -Tokens $Tokens `
            -Context $Context
    }
    catch {
        $detail = Get-ChromaMatterInnermostExceptionMessage `
            -Exception $_.Exception
        if (
            $detail -like "*forbidden workstation/private token*" -or
            $detail -like "*duplicate object key*"
        ) {
            throw "$Context validation failed: $detail"
        }
        throw "$Context is not readable JSON."
    }
    finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }
        else {
            $stream.Dispose()
        }
    }
}

function Test-ChromaMatterDemoThreeMf {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$PrivateTokens
    )

    $expectedNames = @(
        "[Content_Types].xml",
        "_rels/.rels",
        "3D/3dmodel.model",
        "3D/_rels/3dmodel.model.rels",
        "3D/Objects/object_1.model",
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
        "Metadata/full_spectrum_palette.json",
        "Metadata/tripo_part_palettes.json",
        "Metadata/tripo_assembly.json"
    )
    $expected = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($name in $expectedNames) {
        [void]$expected.Add($name)
    }
    $jsonNames = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($name in @(
        "Metadata/project_settings.config",
        "Metadata/full_spectrum_palette.json",
        "Metadata/tripo_part_palettes.json",
        "Metadata/tripo_assembly.json"
    )) {
        [void]$jsonNames.Add($name)
    }

    $rawRecords = @(Read-SoftwareZipRawRecords -ArchivePath $ArchivePath)
    $seen = @{}
    $knownAncestors = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    $rawByName = [System.Collections.Generic.Dictionary[string, object]]::new(
        [System.StringComparer]::Ordinal
    )
    [uint64]$totalExpandedBytes = 0
    foreach ($record in $rawRecords) {
        $probeName = "__chromamatter_3mf__/$($record.Name)"
        $segments = Assert-CanonicalSoftwareZipPath `
            -Name $probeName `
            -ExpectedRootName "__chromamatter_3mf__" `
            -Context "Demo 3MF member path"
        Register-SoftwareZipPath `
            -Segments $segments `
            -Name $record.Name `
            -Seen $seen `
            -KnownAncestors $knownAncestors
        if (-not $expected.Contains([string]$record.Name)) {
            throw "Demo 3MF contains an unexpected member: $($record.Name)"
        }
        $memberLimit = if (
            [string]$record.Name -ceq "3D/Objects/object_1.model"
        ) {
            [uint64]$script:ThreeMfMeshMemberLimit
        }
        else {
            [uint64]$script:ThreeMfSmallMemberLimit
        }
        if ([uint64]$record.UncompressedSize -gt $memberLimit) {
            throw "Demo 3MF member exceeds its expansion limit: $($record.Name)"
        }
        $totalExpandedBytes += [uint64]$record.UncompressedSize
        if (
            $totalExpandedBytes -gt
                [uint64]$script:ThreeMfTotalExpansionLimit
        ) {
            throw "Demo 3MF exceeds its total expansion limit."
        }
        if (
            [uint64]$record.UncompressedSize -gt 1048576L -and
            (
                [uint64]$record.CompressedSize -eq 0 -or
                (
                    [double]$record.UncompressedSize /
                    [double]$record.CompressedSize
                ) -gt [double]$script:ThreeMfCompressionRatioLimit
            )
        ) {
            throw "Demo 3MF member has an unsafe expansion ratio: $($record.Name)"
        }
        $rawByName.Add([string]$record.Name, $record)
        foreach ($token in $PrivateTokens) {
            if (
                -not [string]::IsNullOrEmpty($token) -and
                ([string]$record.Name).IndexOf(
                    $token,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -ge 0
            ) {
                throw "Demo 3MF member path contains a forbidden private token."
            }
        }
    }
    if ($rawRecords.Count -ne $expected.Count) {
        throw "Demo 3MF must contain the exact 10-member ChromaMatter output set."
    }

    $stream = [System.IO.File]::Open(
        $ArchivePath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $archive = $null
    $archiveReady = $false
    try {
        $archive = [System.IO.Compression.ZipArchive]::new(
            $stream,
            [System.IO.Compression.ZipArchiveMode]::Read,
            $false,
            $script:ZipUtf8
        )
        $archiveReady = $true
        if ($archive.Entries.Count -ne $rawRecords.Count) {
            throw "Demo 3MF raw and decoded member counts disagree."
        }
        $entries = [System.Collections.Generic.Dictionary[string, object]]::new(
            [System.StringComparer]::Ordinal
        )
        foreach ($entry in $archive.Entries) {
            if ($entries.ContainsKey($entry.FullName)) {
                throw "Demo 3MF contains a duplicate decoded member."
            }
            $entries.Add($entry.FullName, $entry)
        }
        foreach ($name in $expectedNames) {
            if (-not $entries.ContainsKey($name)) {
                throw "Demo 3MF is missing a required member: $name"
            }
            $entry = $entries[$name]
            $raw = $rawByName[$name]
            if ($entry.Length -le 0) {
                throw "Demo 3MF member is empty: $name"
            }
            if (
                [uint64]$entry.Length -ne [uint64]$raw.UncompressedSize -or
                [uint64]$entry.CompressedLength -ne [uint64]$raw.CompressedSize
            ) {
                throw "Demo 3MF member sizes disagree with the original ZIP record: $name"
            }
            $entryStream = $entry.Open()
            try {
                $readLimit = if ($name -ceq "3D/Objects/object_1.model") {
                    [uint64]$script:ThreeMfMeshMemberLimit
                }
                else {
                    [uint64]$script:ThreeMfSmallMemberLimit
                }
                try {
                    $integrity = [ChromaMatter.Release.Crc32Reader]::Read(
                        $entryStream,
                        $readLimit
                    )
                }
                catch [System.IO.InvalidDataException] {
                    throw "Demo 3MF member exceeds its expansion limit: $name"
                }
            }
            finally {
                $entryStream.Dispose()
            }
            if (
                [uint64]$integrity.Bytes -ne [uint64]$raw.UncompressedSize -or
                [uint32]$integrity.Crc32 -ne [uint32]$raw.Crc32
            ) {
                throw "Demo 3MF member CRC-32 mismatch: $name"
            }
            Assert-ThreeMfTextHasNoPrivateTokens `
                -Entry $entry `
                -Tokens $PrivateTokens `
                -Context "Demo 3MF member $name"
            if ($jsonNames.Contains($name)) {
                Assert-ThreeMfJsonReadable `
                    -Entry $entry `
                    -Context "Demo 3MF member $name" `
                    -Tokens $PrivateTokens
            }
        }

        $contentTypesDocument = Read-ThreeMfXmlDocument `
            -Entry $entries["[Content_Types].xml"] `
            -Tokens $PrivateTokens `
            -Context "Demo 3MF content types"
        Assert-ThreeMfContentTypes `
            -Document $contentTypesDocument `
            -Context "Demo 3MF content types"
        $rootRelationshipsDocument = Read-ThreeMfXmlDocument `
            -Entry $entries["_rels/.rels"] `
            -Tokens $PrivateTokens `
            -Context "Demo 3MF root relationships"
        Assert-ThreeMfRelationshipDocument `
            -Document $rootRelationshipsDocument `
            -ExpectedTarget "/3D/3dmodel.model" `
            -Context "Demo 3MF root relationships"
        $modelRelationshipsDocument = Read-ThreeMfXmlDocument `
            -Entry $entries["3D/_rels/3dmodel.model.rels"] `
            -Tokens $PrivateTokens `
            -Context "Demo 3MF model relationships"
        Assert-ThreeMfRelationshipDocument `
            -Document $modelRelationshipsDocument `
            -ExpectedTarget "/3D/Objects/object_1.model" `
            -Context "Demo 3MF model relationships"
        $mainModelDocument = Read-ThreeMfXmlDocument `
            -Entry $entries["3D/3dmodel.model"] `
            -Tokens $PrivateTokens `
            -Context "Demo 3MF main model"
        [void](Read-ThreeMfXmlDocument `
            -Entry $entries["Metadata/model_settings.config"] `
            -Tokens $PrivateTokens `
            -Context "Demo 3MF model settings")
        $objectSummary = Get-ThreeMfObjectModelSummary `
            -Entry $entries["3D/Objects/object_1.model"] `
            -Tokens $PrivateTokens `
            -Context "Demo 3MF object model"
        Assert-ThreeMfMainModel `
            -Document $mainModelDocument `
            -ObjectModelIds ([string[]]$objectSummary.ObjectIds) `
            -Context "Demo 3MF main model"
    }
    catch {
        $detail = Get-ChromaMatterInnermostExceptionMessage `
            -Exception $_.Exception
        if ($archiveReady) {
            throw "Demo 3MF validation failed: $detail"
        }
        throw "Demo 3MF is not a readable ZIP archive."
    }
    finally {
        if ($null -ne $archive) {
            $archive.Dispose()
        }
        $stream.Dispose()
    }
    return $rawRecords.Count
}

Export-ModuleMember -Function `
    New-CanonicalSoftwareZip, `
    Test-CanonicalSoftwareZip, `
    Test-ChromaMatterDemoThreeMf, `
    Assert-ChromaMatterJsonFileNoPrivateTokens
