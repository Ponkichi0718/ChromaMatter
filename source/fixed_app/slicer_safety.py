"""Small, side-effect-free safety checks for Snapmaker Orca 3MF metadata.

The functions in this module deliberately operate on entry payloads rather
than opening a 3MF archive themselves.  A caller can therefore use the result
with its existing atomic ZIP-copy routine while preserving every unrelated
entry and :class:`zipfile.ZipInfo` attribute.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Literal, Sequence
from xml.parsers import expat


# Flow::rounded_rectangle_extrusion_spacing() in OrcaSlicer uses this exact
# geometric term and rejects a zero result as well as a negative one.
NONPOSITIVE_SPACING_FACTOR = 1.0 - math.pi / 4.0

# Below this absolute width the setting is suspicious even if an unusually
# small layer height happens to keep the rounded-rectangle spacing positive.
# This is diagnostic-only; no project setting is silently rewritten.
DEFAULT_MIN_LINE_WIDTH_MM = 0.05
MAX_LINE_WIDTH_MM = 10.0
MAX_LINE_WIDTH_PERCENT = 1000.0

SupportMode = Literal["disable", "remove"]
Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class SafetyDiagnostic:
    """A stable machine code plus a ready-to-display Japanese message."""

    code: str
    severity: Severity
    message: str
    key: str | None = None
    value: str | None = None


@dataclass(frozen=True, slots=True)
class BytesRewriteResult:
    """Result of a pure bytes-to-bytes metadata rewrite."""

    data: bytes
    changed: bool
    diagnostics: tuple[SafetyDiagnostic, ...]

    @property
    def has_errors(self) -> bool:
        return any(item.severity == "error" for item in self.diagnostics)


@dataclass(frozen=True, slots=True)
class _XmlElementFrame:
    name: str
    start: int
    start_tag_end: int
    self_closing: bool
    support_value: str | None


@dataclass(frozen=True, slots=True)
class _SupportElement:
    start: int
    start_tag_end: int
    end: int
    value: str


@dataclass(frozen=True, slots=True)
class _NumberSetting:
    number: float
    is_percent: bool
    display: str


_ATTRIBUTE_RE = re.compile(
    rb"(?P<name>[A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*"
    rb"(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)


def _diag(
    code: str,
    severity: Severity,
    message: str,
    *,
    key: str | None = None,
    value: object | None = None,
) -> SafetyDiagnostic:
    return SafetyDiagnostic(
        code=code,
        severity=severity,
        message=message,
        key=key,
        value=None if value is None else str(value),
    )


def _require_bytes(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        raise TypeError("metadata payload must be bytes")
    return data


def _local_name(name: str) -> str:
    return name.rsplit(":", 1)[-1]


def _find_xml_tag_end(data: bytes, start: int) -> int:
    """Return the exclusive end of one XML tag without decoding the file."""

    if start < 0 or start >= len(data) or data[start : start + 1] != b"<":
        raise ValueError("XML parser returned an unusable byte offset")
    quote: int | None = None
    for index in range(start + 1, len(data)):
        byte = data[index]
        if quote is None:
            if byte in (ord("'"), ord('"')):
                quote = byte
            elif byte == ord(">"):
                return index + 1
        elif byte == quote:
            quote = None
    raise ValueError("XML tag is not terminated")


def _collect_support_elements(data: bytes) -> tuple[list[_SupportElement], list[str | None]]:
    """Parse XML and retain exact byte spans for enable_support metadata."""

    parser = expat.ParserCreate()
    stack: list[_XmlElementFrame] = []
    targets: list[_SupportElement] = []
    all_values: list[str | None] = []

    def start_element(name: str, attributes: dict[str, str]) -> None:
        start = parser.CurrentByteIndex
        tag_end = _find_xml_tag_end(data, start)
        raw_tag = data[start:tag_end]
        key = next(
            (
                item
                for attr_name, item in attributes.items()
                if _local_name(attr_name) == "key"
            ),
            None,
        )
        value = next(
            (
                item
                for attr_name, item in attributes.items()
                if _local_name(attr_name) == "value"
            ),
            None,
        )
        support_value = None
        if _local_name(name) == "metadata" and key == "enable_support":
            support_value = value
            all_values.append(value)
        stack.append(
            _XmlElementFrame(
                name=name,
                start=start,
                start_tag_end=tag_end,
                self_closing=raw_tag.rstrip().endswith(b"/>"),
                support_value=support_value,
            )
        )

    def end_element(name: str) -> None:
        if not stack:
            raise ValueError("XML element stack underflow")
        frame = stack.pop()
        if frame.name != name:
            raise ValueError("XML element stack mismatch")
        if frame.support_value is None:
            return
        if frame.self_closing:
            end = frame.start_tag_end
        else:
            end = _find_xml_tag_end(data, parser.CurrentByteIndex)
        targets.append(
            _SupportElement(
                start=frame.start,
                start_tag_end=frame.start_tag_end,
                end=end,
                value=frame.support_value,
            )
        )

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    # Do not resolve external entities from untrusted project metadata.
    parser.ExternalEntityRefHandler = lambda *_args: 0
    parser.Parse(data, True)
    if stack:
        raise ValueError("XML element stack was not exhausted")
    return targets, all_values


def _value_span_in_start_tag(data: bytes, element: _SupportElement) -> tuple[int, int]:
    raw_tag = data[element.start : element.start_tag_end]
    matches = [
        match
        for match in _ATTRIBUTE_RE.finditer(raw_tag)
        if _local_name(match.group("name").decode("ascii")) == "value"
    ]
    if len(matches) != 1:
        raise ValueError("enable_support metadata does not have one lexical value attribute")
    match = matches[0]
    return element.start + match.start("value"), element.start + match.end("value")


def _apply_byte_edits(
    data: bytes, edits: Sequence[tuple[int, int, bytes]]
) -> bytes:
    previous_start = len(data)
    result = data
    for start, end, replacement in sorted(edits, reverse=True):
        if not (0 <= start <= end <= previous_start):
            raise ValueError("overlapping or out-of-range byte edits")
        result = result[:start] + replacement + result[end:]
        previous_start = start
    return result


def sanitize_model_settings_support(
    data: bytes, *, mode: SupportMode = "disable"
) -> BytesRewriteResult:
    """Disable a forced ``enable_support=1`` override without ZIP side effects.

    ``mode="disable"`` changes only the value bytes to ``0``.  ``mode="remove"``
    removes the complete metadata element.  Unrelated whitespace, comments,
    element ordering, and encoding bytes are retained.  On malformed or
    lexically unsupported XML the original payload is returned unchanged with
    an error diagnostic.
    """

    original = _require_bytes(data)
    if mode not in ("disable", "remove"):
        raise ValueError("mode must be 'disable' or 'remove'")

    try:
        elements, all_values = _collect_support_elements(original)
    except (expat.ExpatError, UnicodeError, ValueError) as exc:
        return BytesRewriteResult(
            original,
            False,
            (
                _diag(
                    "model_settings_invalid_xml",
                    "error",
                    f"model_settings.config は不正なXMLのため変更していません: {exc}",
                ),
            ),
        )

    enabled = [item for item in elements if item.value.strip() == "1"]
    if not enabled:
        if not all_values:
            diagnostic = _diag(
                "support_override_absent",
                "info",
                "enable_support の強制指定はありません。",
                key="enable_support",
            )
        elif all(value is not None and value.strip() == "0" for value in all_values):
            diagnostic = _diag(
                "support_already_disabled",
                "info",
                "enable_support は既に 0 です。",
                key="enable_support",
                value="0",
            )
        else:
            rendered = ", ".join("<missing>" if value is None else value for value in all_values)
            diagnostic = _diag(
                "support_override_unrecognized",
                "warning",
                f"enable_support に 0/1 以外の値があります ({rendered})。安全のため変更していません。",
                key="enable_support",
                value=rendered,
            )
        return BytesRewriteResult(original, False, (diagnostic,))

    try:
        if mode == "remove":
            edits = [(item.start, item.end, b"") for item in enabled]
        else:
            edits = [(*_value_span_in_start_tag(original, item), b"0") for item in enabled]
        updated = _apply_byte_edits(original, edits)
        # A second parse makes the safety property explicit before callers put
        # these bytes back into an otherwise valid ZIP archive.
        remaining, values = _collect_support_elements(updated)
        if any(item.value.strip() == "1" for item in remaining):
            raise ValueError("an enabled support override remains after rewrite")
        if mode == "disable" and sum(value == "0" for value in values) < len(enabled):
            raise ValueError("rewritten support values could not be verified")
    except (expat.ExpatError, UnicodeError, ValueError) as exc:
        return BytesRewriteResult(
            original,
            False,
            (
                _diag(
                    "support_rewrite_not_safe",
                    "error",
                    f"enable_support を安全に変更できないため元データを維持しました: {exc}",
                    key="enable_support",
                    value="1",
                ),
            ),
        )

    action = "削除" if mode == "remove" else "0 に変更"
    return BytesRewriteResult(
        updated,
        updated != original,
        (
            _diag(
                "support_override_removed" if mode == "remove" else "support_override_disabled",
                "info",
                f"強制サポート指定 {len(enabled)} 件を{action}しました。",
                key="enable_support",
                value="1",
            ),
        ),
    )


def rewrite_model_settings_support_bytes(
    data: bytes, *, mode: SupportMode = "disable"
) -> bytes:
    """Convenience bytes-in/bytes-out wrapper for an atomic ZIP copy loop."""

    return sanitize_model_settings_support(data, mode=mode).data


def _decode_project_json(data: bytes) -> tuple[object | None, list[str], SafetyDiagnostic | None]:
    duplicates: list[str] = []

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return (
            None,
            duplicates,
            _diag(
                "project_settings_invalid_utf8",
                "error",
                f"project_settings.config はUTF-8として読めません: {exc}",
            ),
        )
    try:
        decoded = json.loads(text, object_pairs_hook=object_pairs)
    except (json.JSONDecodeError, RecursionError) as exc:
        return (
            None,
            duplicates,
            _diag(
                "project_settings_invalid_json",
                "error",
                f"project_settings.config は不正なJSONです: {exc}",
            ),
        )
    return decoded, duplicates, None


def _number_setting(value: object, *, allow_percent: bool) -> _NumberSetting | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return _NumberSetting(number, False, str(value)) if math.isfinite(number) else None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    is_percent = stripped.endswith("%")
    if is_percent:
        if not allow_percent:
            return None
        stripped = stripped[:-1].strip()
    elif "%" in stripped:
        return None
    try:
        number = float(stripped)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return _NumberSetting(number, is_percent, value)


def _positive_values(
    settings: dict[str, object],
    key: str,
    diagnostics: list[SafetyDiagnostic],
    *,
    allow_percent: bool = False,
) -> list[float]:
    if key not in settings:
        return []
    raw = settings[key]
    values = raw if isinstance(raw, list) else [raw]
    if not values:
        diagnostics.append(
            _diag(
                f"{key}_empty",
                "error",
                f"{key} が空配列です。",
                key=key,
                value=raw,
            )
        )
        return []
    result: list[float] = []
    for index, item in enumerate(values):
        parsed = _number_setting(item, allow_percent=allow_percent)
        item_key = key if not isinstance(raw, list) else f"{key}[{index}]"
        if parsed is None or parsed.is_percent:
            diagnostics.append(
                _diag(
                    f"{key}_invalid",
                    "error",
                    f"{item_key} は正のmm数値ではありません ({item!r})。",
                    key=item_key,
                    value=item,
                )
            )
        elif parsed.number <= 0:
            diagnostics.append(
                _diag(
                    f"{key}_nonpositive",
                    "error",
                    f"{item_key} は 0 より大きい値が必要です ({parsed.number:g})。",
                    key=item_key,
                    value=parsed.display,
                )
            )
        else:
            result.append(parsed.number)
    return result


def _line_width_keys(settings: dict[str, object]) -> list[str]:
    return sorted(
        key
        for key in settings
        if key == "line_width" or key.endswith("_line_width")
    )


def _resolved_widths(
    parsed: _NumberSetting,
    nozzles: list[float],
) -> list[float]:
    if not parsed.is_percent:
        return [parsed.number]
    return [parsed.number * nozzle / 100.0 for nozzle in nozzles]


def _has_grouped_cycle_definition(settings: dict[str, object]) -> bool:
    """Return whether a Cycle row contains an ``outer,inner`` tool pattern."""

    definitions = settings.get("mixed_filament_definitions")
    if not isinstance(definitions, str):
        return False
    for row in definitions.split(";"):
        _prefix, marker, manual_pattern = row.partition(",cm1,")
        if marker and "," in manual_pattern:
            return True
    return False


def _physical_tool_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        candidate = int(value.strip())
    else:
        return None
    return candidate if 1 <= candidate <= 4 else None


def _diagnose_grouped_cycle_safety(
    settings: dict[str, object],
) -> list[SafetyDiagnostic]:
    """Check the static conditions that keep grouped Cycle IDs out of T4+."""

    if not _has_grouped_cycle_definition(settings):
        return []

    diagnostics: list[SafetyDiagnostic] = []
    for key, invalid_code in (
        (
            "support_filament",
            "grouped_cycle_support_filament_invalid",
        ),
        (
            "support_interface_filament",
            "grouped_cycle_support_interface_filament_invalid",
        ),
    ):
        raw = settings.get(key)
        tool = _physical_tool_id(raw)
        if tool is None:
            diagnostics.append(
                _diag(
                    invalid_code,
                    "error",
                    f"Grouped Cycleでは{key}をcurrent(0)ではなく物理F1〜F4へ固定する必要があります。",
                    key=key,
                    value="<missing>" if key not in settings else raw,
                )
            )

    for key in (
        "flush_into_infill",
        "flush_into_support",
        "flush_into_objects",
    ):
        raw = settings.get(key)
        if str(raw).strip() != "0":
            diagnostics.append(
                _diag(
                    "grouped_cycle_flush_override_enabled",
                    "error",
                    f"Grouped Cycleでは{key}=0が必須です。purge-to-print overrideは壁分割を停止させます。",
                    key=key,
                    value="<missing>" if key not in settings else raw,
                )
            )
    return diagnostics


def diagnose_project_settings(
    data: bytes,
    *,
    minimum_line_width_mm: float = DEFAULT_MIN_LINE_WIDTH_MM,
) -> tuple[SafetyDiagnostic, ...]:
    """Diagnose Orca line-width and grouped-Cycle tool-selection hazards.

    The function never changes JSON.  Numeric strings and ``"NN%"`` values are
    understood.  A literal zero is treated as Orca's documented auto/inherit
    sentinel.  Positive explicit widths are checked against
    ``(1 - pi/4) * layer_height``.  Percent values are resolved against every
    positive ``nozzle_diameter`` entry, because the project entry alone does
    not identify which tool will print a painted region.
    """

    _require_bytes(data)
    if (
        isinstance(minimum_line_width_mm, bool)
        or not isinstance(minimum_line_width_mm, (int, float))
        or not math.isfinite(float(minimum_line_width_mm))
        or float(minimum_line_width_mm) < 0
    ):
        raise ValueError("minimum_line_width_mm must be a finite non-negative number")

    decoded, duplicates, decode_error = _decode_project_json(data)
    if decode_error is not None:
        return (decode_error,)
    if not isinstance(decoded, dict):
        return (
            _diag(
                "project_settings_not_object",
                "error",
                "project_settings.config のルートはJSONオブジェクトである必要があります。",
                value=type(decoded).__name__,
            ),
        )

    settings: dict[str, object] = decoded
    diagnostics: list[SafetyDiagnostic] = []
    for key in sorted(set(duplicates)):
        diagnostics.append(
            _diag(
                "project_settings_duplicate_key",
                "warning",
                f"JSONキー {key} が重複しています。最後の値だけが有効になるため確認してください。",
                key=key,
            )
        )

    diagnostics.extend(_diagnose_grouped_cycle_safety(settings))

    width_keys = _line_width_keys(settings)
    if not width_keys:
        return tuple(diagnostics)

    # Heights are only required when there is an explicit positive width.  A
    # metadata-only project and a project containing only auto widths should
    # not gain alarming diagnostics merely because it relies on a print preset.
    height_diagnostics: list[SafetyDiagnostic] = []
    layer_heights = _positive_values(settings, "layer_height", height_diagnostics)
    initial_heights = _positive_values(
        settings, "initial_layer_print_height", height_diagnostics
    )

    nozzles_loaded = False
    nozzles: list[float] = []
    nozzle_diagnostics: list[SafetyDiagnostic] = []

    explicit_width_seen = False
    height_warning_emitted: set[str] = set()
    for key in width_keys:
        raw = settings[key]
        if isinstance(raw, list) or isinstance(raw, dict) or raw is None:
            diagnostics.append(
                _diag(
                    "line_width_invalid_type",
                    "error",
                    f"{key} は単一の数値または数値文字列である必要があります ({raw!r})。",
                    key=key,
                    value=raw,
                )
            )
            continue
        parsed = _number_setting(raw, allow_percent=True)
        if parsed is None:
            diagnostics.append(
                _diag(
                    "line_width_invalid_value",
                    "error",
                    f"{key} の線幅を数値として解釈できません ({raw!r})。",
                    key=key,
                    value=raw,
                )
            )
            continue
        if parsed.number < 0:
            diagnostics.append(
                _diag(
                    "line_width_negative",
                    "error",
                    f"{key} に負の線幅 {parsed.display!r} が設定されています。",
                    key=key,
                    value=parsed.display,
                )
            )
            continue
        if parsed.number == 0:
            # Orca uses exactly zero as auto/default or role inheritance.
            continue
        explicit_width_seen = True

        if parsed.is_percent and parsed.number > MAX_LINE_WIDTH_PERCENT:
            diagnostics.append(
                _diag(
                    "line_width_percent_out_of_range",
                    "error",
                    f"{key}={parsed.display!r} はOrcaの上限 {MAX_LINE_WIDTH_PERCENT:g}% を超えています。",
                    key=key,
                    value=parsed.display,
                )
            )
            continue
        if not parsed.is_percent and parsed.number > MAX_LINE_WIDTH_MM:
            diagnostics.append(
                _diag(
                    "line_width_out_of_range",
                    "error",
                    f"{key}={parsed.number:g} mm はOrcaの上限 {MAX_LINE_WIDTH_MM:g} mm を超えています。",
                    key=key,
                    value=parsed.display,
                )
            )
            continue

        if parsed.is_percent:
            if not nozzles_loaded:
                nozzles_loaded = True
                nozzles = _positive_values(
                    settings, "nozzle_diameter", nozzle_diagnostics
                )
            if not nozzles:
                diagnostics.append(
                    _diag(
                        "line_width_percent_unresolved",
                        "warning",
                        f"{key}={parsed.display!r} は nozzle_diameter がないためmm換算できません。",
                        key=key,
                        value=parsed.display,
                    )
                )
                continue

        widths = _resolved_widths(parsed, nozzles)
        comparison_heights = (
            initial_heights or layer_heights
            if key == "initial_layer_line_width"
            else layer_heights
        )
        if not comparison_heights:
            height_key = (
                "initial_layer_print_height/layer_height"
                if key == "initial_layer_line_width"
                else "layer_height"
            )
            if height_key not in height_warning_emitted:
                diagnostics.append(
                    _diag(
                        "layer_height_unavailable",
                        "warning",
                        f"{height_key} がないため線幅と層高からspacingを検証できません。",
                        key=height_key,
                    )
                )
                height_warning_emitted.add(height_key)

        unsafe_pairs = [
            (width, height, NONPOSITIVE_SPACING_FACTOR * height)
            for width in widths
            for height in comparison_heights
            if width <= NONPOSITIVE_SPACING_FACTOR * height
        ]
        if unsafe_pairs:
            width, height, threshold = max(unsafe_pairs, key=lambda item: item[2] - item[0])
            diagnostics.append(
                _diag(
                    "line_width_nonpositive_spacing",
                    "error",
                    (
                        f"{key} の有効線幅 {width:.6g} mm は、層高 {height:.6g} mm の"
                        f"安全境界 {threshold:.6g} mm 以下です。Orcaで負またはゼロのspacingになります。"
                    ),
                    key=key,
                    value=parsed.display,
                )
            )
            continue

        smallest_width = min(widths)
        if 0 < smallest_width < float(minimum_line_width_mm):
            diagnostics.append(
                _diag(
                    "line_width_extremely_small",
                    "warning",
                    (
                        f"{key} の有効線幅 {smallest_width:.6g} mm は極小です"
                        f"（確認基準 {float(minimum_line_width_mm):g} mm）。"
                    ),
                    key=key,
                    value=parsed.display,
                )
            )

    if explicit_width_seen:
        diagnostics.extend(height_diagnostics)
    if nozzles_loaded:
        diagnostics.extend(nozzle_diagnostics)
    return tuple(diagnostics)


def diagnose_project_settings_bytes(
    data: bytes,
    *,
    minimum_line_width_mm: float = DEFAULT_MIN_LINE_WIDTH_MM,
) -> tuple[SafetyDiagnostic, ...]:
    """Explicitly named alias for callers working with ZIP entry bytes."""

    return diagnose_project_settings(
        data, minimum_line_width_mm=minimum_line_width_mm
    )


def format_diagnostics(diagnostics: Sequence[SafetyDiagnostic]) -> tuple[str, ...]:
    """Return concise display strings without discarding stable codes."""

    return tuple(
        f"[{item.severity.upper()}] {item.message}" for item in diagnostics
    )


__all__ = [
    "BytesRewriteResult",
    "DEFAULT_MIN_LINE_WIDTH_MM",
    "MAX_LINE_WIDTH_MM",
    "MAX_LINE_WIDTH_PERCENT",
    "NONPOSITIVE_SPACING_FACTOR",
    "SafetyDiagnostic",
    "diagnose_project_settings",
    "diagnose_project_settings_bytes",
    "format_diagnostics",
    "rewrite_model_settings_support_bytes",
    "sanitize_model_settings_support",
]
