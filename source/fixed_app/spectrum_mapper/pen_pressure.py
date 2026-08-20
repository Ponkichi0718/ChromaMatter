"""Best-effort Windows pen-pressure sampling for the Tk paint canvas.

Tk 8.6 promotes pen input to ordinary mouse events but does not expose the
pressure carried by ``WM_POINTER``.  This module observes those native
messages without consuming them.  The ordinary Tk button/motion pipeline
therefore remains authoritative, while callers can correlate a fresh native
sample with the matching Tk event.

The bridge is deliberately fail-open: importing it is safe on every platform,
and any unavailable API, invalid HWND, driver failure, or teardown race merely
disables pressure.  No native API is ever read from a paint worker thread.
"""

from __future__ import annotations

from collections import deque
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import math
import os
import time
from typing import Any, Callable, Iterable, Protocol


# Windows Pointer messages and values from winuser.h.
WM_NCDESTROY = 0x0082
WM_POINTERUPDATE = 0x0245
WM_POINTERDOWN = 0x0246
WM_POINTERUP = 0x0247
POINTER_MESSAGES = frozenset((WM_POINTERUPDATE, WM_POINTERDOWN, WM_POINTERUP))
PT_PEN = 3
POINTER_FLAG_INCONTACT = 0x00000004
PEN_MASK_PRESSURE = 0x00000001
PEN_PRESSURE_MAX = 1024.0


_UINT32 = ctypes.c_uint32
_INT32 = ctypes.c_int32
_UINT64 = ctypes.c_uint64
_UINT_PTR = ctypes.c_size_t
_DWORD_PTR = ctypes.c_size_t
_LRESULT = ctypes.c_ssize_t


class _POINT(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class _POINTER_INFO(ctypes.Structure):
    # Keep this declaration in the exact winuser.h order.  In particular,
    # pointer-sized handles and PerformanceCount require native alignment on
    # 64-bit Python.
    _fields_ = (
        ("pointerType", _UINT32),
        ("pointerId", _UINT32),
        ("frameId", _UINT32),
        ("pointerFlags", _UINT32),
        ("sourceDevice", wintypes.HANDLE),
        ("hwndTarget", wintypes.HWND),
        ("ptPixelLocation", _POINT),
        ("ptHimetricLocation", _POINT),
        ("ptPixelLocationRaw", _POINT),
        ("ptHimetricLocationRaw", _POINT),
        ("dwTime", wintypes.DWORD),
        ("historyCount", _UINT32),
        ("InputData", _INT32),
        ("dwKeyStates", wintypes.DWORD),
        ("PerformanceCount", _UINT64),
        ("ButtonChangeType", _UINT32),
    )


class _POINTER_PEN_INFO(ctypes.Structure):
    _fields_ = (
        ("pointerInfo", _POINTER_INFO),
        ("penFlags", _UINT32),
        ("penMask", _UINT32),
        ("pressure", _UINT32),
        ("rotation", _UINT32),
        ("tiltX", _INT32),
        ("tiltY", _INT32),
    )


_CALLBACK_FACTORY = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_SUBCLASSPROC = _CALLBACK_FACTORY(
    _LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    _UINT_PTR,
    _DWORD_PTR,
)


@dataclass(frozen=True, slots=True)
class NativePenSample:
    """A normalized pressure sample in the observed HWND's client space."""

    x: float
    y: float
    pressure: float
    in_contact: bool = True


@dataclass(frozen=True, slots=True)
class TimedPenSample:
    x: float
    y: float
    pressure: float
    received_ns: int
    in_contact: bool


class PointerApi(Protocol):
    """Small injectable surface used by the native bridge and fake tests."""

    available: bool
    unavailable_reason: str

    def make_callback(self, callback: Callable[..., int]) -> Any: ...

    def set_window_subclass(
        self, hwnd: int, callback: Any, subclass_id: int
    ) -> bool: ...

    def remove_window_subclass(
        self, hwnd: int, callback: Any, subclass_id: int
    ) -> bool: ...

    def def_subclass_proc(
        self, hwnd: int, message: int, wparam: int, lparam: int
    ) -> int: ...

    def read_pen_sample(self, pointer_id: int, hwnd: int) -> NativePenSample | None: ...


class WindowsPointerApi:
    """ctypes wrapper for the Windows Pointer and common-controls APIs."""

    def __init__(self) -> None:
        self.available = False
        self.unavailable_reason = "Windows Pointer API is unavailable"
        self._user32 = None
        self._comctl32 = None
        if os.name != "nt":
            self.unavailable_reason = "Pen pressure is supported on Windows only"
            return
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
            get_pointer_type = user32.GetPointerType
            get_pointer_type.argtypes = (_UINT32, ctypes.POINTER(_UINT32))
            get_pointer_type.restype = wintypes.BOOL
            get_pointer_pen_info = user32.GetPointerPenInfo
            get_pointer_pen_info.argtypes = (
                _UINT32,
                ctypes.POINTER(_POINTER_PEN_INFO),
            )
            get_pointer_pen_info.restype = wintypes.BOOL
            screen_to_client = user32.ScreenToClient
            screen_to_client.argtypes = (wintypes.HWND, ctypes.POINTER(_POINT))
            screen_to_client.restype = wintypes.BOOL

            set_window_subclass = comctl32.SetWindowSubclass
            set_window_subclass.argtypes = (
                wintypes.HWND,
                _SUBCLASSPROC,
                _UINT_PTR,
                _DWORD_PTR,
            )
            set_window_subclass.restype = wintypes.BOOL
            remove_window_subclass = comctl32.RemoveWindowSubclass
            remove_window_subclass.argtypes = (
                wintypes.HWND,
                _SUBCLASSPROC,
                _UINT_PTR,
            )
            remove_window_subclass.restype = wintypes.BOOL
            def_subclass_proc = comctl32.DefSubclassProc
            def_subclass_proc.argtypes = (
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            def_subclass_proc.restype = _LRESULT
        except (AttributeError, OSError) as exc:
            self.unavailable_reason = f"{type(exc).__name__}: {exc}"
            return

        self._user32 = user32
        self._comctl32 = comctl32
        self._get_pointer_type = get_pointer_type
        self._get_pointer_pen_info = get_pointer_pen_info
        self._screen_to_client = screen_to_client
        self._set_window_subclass = set_window_subclass
        self._remove_window_subclass = remove_window_subclass
        self._def_subclass_proc = def_subclass_proc
        self.available = True
        self.unavailable_reason = ""

    def make_callback(self, callback: Callable[..., int]) -> Any:
        return _SUBCLASSPROC(callback)

    def set_window_subclass(
        self, hwnd: int, callback: Any, subclass_id: int
    ) -> bool:
        if not self.available:
            return False
        return bool(
            self._set_window_subclass(
                wintypes.HWND(int(hwnd)),
                callback,
                _UINT_PTR(int(subclass_id)),
                _DWORD_PTR(0),
            )
        )

    def remove_window_subclass(
        self, hwnd: int, callback: Any, subclass_id: int
    ) -> bool:
        if not self.available or not hwnd:
            return False
        try:
            return bool(
                self._remove_window_subclass(
                    wintypes.HWND(int(hwnd)),
                    callback,
                    _UINT_PTR(int(subclass_id)),
                )
            )
        except (AttributeError, OSError, ValueError):
            return False

    def def_subclass_proc(
        self, hwnd: int, message: int, wparam: int, lparam: int
    ) -> int:
        return int(
            self._def_subclass_proc(
                wintypes.HWND(int(hwnd)),
                wintypes.UINT(int(message)),
                wintypes.WPARAM(int(wparam)),
                wintypes.LPARAM(int(lparam)),
            )
        )

    def read_pen_sample(self, pointer_id: int, hwnd: int) -> NativePenSample | None:
        if not self.available:
            return None
        pointer_type = _UINT32(0)
        if not self._get_pointer_type(
            _UINT32(int(pointer_id)), ctypes.byref(pointer_type)
        ):
            return None
        if int(pointer_type.value) != PT_PEN:
            return None
        info = _POINTER_PEN_INFO()
        if not self._get_pointer_pen_info(
            _UINT32(int(pointer_id)), ctypes.byref(info)
        ):
            return None
        if not (int(info.penMask) & PEN_MASK_PRESSURE):
            return None
        point = _POINT(
            int(info.pointerInfo.ptPixelLocation.x),
            int(info.pointerInfo.ptPixelLocation.y),
        )
        if not self._screen_to_client(
            wintypes.HWND(int(hwnd)), ctypes.byref(point)
        ):
            return None
        return NativePenSample(
            float(point.x),
            float(point.y),
            normalize_pressure(float(info.pressure), PEN_PRESSURE_MAX),
            bool(int(info.pointerInfo.pointerFlags) & POINTER_FLAG_INCONTACT),
        )


class PenSampleHistory:
    """Correlate native samples with subsequently promoted Tk mouse events."""

    def __init__(
        self,
        *,
        max_samples: int = 64,
        max_age_ms: float = 140.0,
        max_distance_pixels: float = 24.0,
    ) -> None:
        self._samples: deque[TimedPenSample] = deque(maxlen=max(1, int(max_samples)))
        self.max_age_ns = max(0, int(float(max_age_ms) * 1_000_000.0))
        self.max_distance_sq = max(0.0, float(max_distance_pixels)) ** 2
        self.detected = False

    def add(self, sample: NativePenSample, received_ns: int) -> None:
        pressure = float(sample.pressure)
        if not math.isfinite(pressure):
            return
        value = min(1.0, max(0.0, pressure))
        self._samples.append(
            TimedPenSample(
                float(sample.x),
                float(sample.y),
                value,
                int(received_ns),
                bool(sample.in_contact),
            )
        )
        self.detected = True

    def match(self, x: float, y: float, now_ns: int) -> float | None:
        px = float(x)
        py = float(y)
        current = int(now_ns)
        for sample in reversed(self._samples):
            age = current - int(sample.received_ns)
            if age < 0:
                continue
            if age > self.max_age_ns:
                break
            if not sample.in_contact:
                continue
            dx = px - sample.x
            dy = py - sample.y
            if dx * dx + dy * dy <= self.max_distance_sq:
                return float(sample.pressure)
        return None


class PenPressureBridge:
    """Observe pressure for one Tk widget while preserving its mouse events."""

    def __init__(
        self,
        widget: Any,
        *,
        api: PointerApi | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        history: PenSampleHistory | None = None,
    ) -> None:
        self.widget = widget
        self.api: PointerApi = api if api is not None else WindowsPointerApi()
        self._clock_ns = clock_ns
        self.history = history if history is not None else PenSampleHistory()
        self.enabled = False
        self.installed = False
        self.closed = False
        self.last_error = ""
        self._hwnd = 0
        self._destroy_bind_id = None
        # SetWindowSubclass identifies one callback/id pair.  Keep it nonzero
        # and pointer-sized without leaking a Python address through refData.
        self._subclass_id = (id(self) & ((1 << (ctypes.sizeof(_UINT_PTR) * 8)) - 1)) or 1
        self._callback = None

        if not bool(getattr(self.api, "available", False)):
            self.last_error = str(
                getattr(self.api, "unavailable_reason", "Pen pressure is unavailable")
            )
            return
        try:
            # winfo_id is an HWND for native Tk widgets on Windows.  Calling
            # update_idletasks here guarantees the child Canvas exists.
            widget.update_idletasks()
            self._hwnd = int(widget.winfo_id())
            if self._hwnd <= 0:
                raise RuntimeError("Tk did not provide a valid canvas HWND")
            self._callback = self.api.make_callback(self._window_proc)
            self.installed = bool(
                self.api.set_window_subclass(
                    self._hwnd, self._callback, self._subclass_id
                )
            )
            if not self.installed:
                raise RuntimeError("SetWindowSubclass failed")
            self.enabled = True
            try:
                self._destroy_bind_id = widget.bind(
                    "<Destroy>", self._on_widget_destroy, add="+"
                )
            except Exception:
                # Explicit editor teardown remains sufficient.
                pass
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.enabled = False
            self.installed = False

    @property
    def detected(self) -> bool:
        return bool(self.history.detected)

    @property
    def availability(self) -> str:
        if not self.enabled:
            return "unavailable"
        return "detected" if self.detected else "waiting"

    def _window_proc(
        self,
        hwnd: int,
        message: int,
        wparam: int,
        lparam: int,
        _subclass_id: int,
        _ref_data: int,
    ) -> int:
        # A ctypes callback must never leak an exception into native code.
        destroying = int(message) == WM_NCDESTROY
        try:
            if self.enabled and int(message) in POINTER_MESSAGES:
                pointer_id = int(wparam) & 0xFFFF
                sample = self.api.read_pen_sample(pointer_id, int(hwnd))
                if sample is not None:
                    self.history.add(sample, int(self._clock_ns()))
        except BaseException as exc:  # pragma: no cover - native safety net
            self.last_error = f"{type(exc).__name__}: {exc}"
        if destroying and self.installed and self._callback is not None:
            try:
                self.api.remove_window_subclass(
                    int(hwnd), self._callback, self._subclass_id
                )
            except BaseException as exc:  # pragma: no cover - native teardown
                self.last_error = f"{type(exc).__name__}: {exc}"
        try:
            # Observational only: never return 0 in place of the Tk/common-
            # controls procedure, otherwise pen input could stop promoting to
            # the existing Button/B1-Motion bindings.
            result = self.api.def_subclass_proc(
                int(hwnd), int(message), int(wparam), int(lparam)
            )
        except BaseException as exc:  # pragma: no cover - defensive fallback
            self.last_error = f"{type(exc).__name__}: {exc}"
            result = 0
        if destroying:
            self.enabled = False
            self.installed = False
            self._hwnd = 0
        return int(result)

    def pressure_for_event(self, event: Any) -> float | None:
        if not self.enabled:
            return None
        try:
            return self.history.match(
                float(event.x),
                float(event.y),
                int(self._clock_ns()),
            )
        except (AttributeError, TypeError, ValueError):
            return None

    def _on_widget_destroy(self, event: Any) -> None:
        if getattr(event, "widget", None) is self.widget:
            self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.enabled = False
        widget = self.widget
        if widget is not None and self._destroy_bind_id:
            try:
                widget.unbind("<Destroy>", self._destroy_bind_id)
            except Exception:
                pass
        self._destroy_bind_id = None
        removed = not self.installed
        if self.installed and self._hwnd and self._callback is not None:
            try:
                removed = bool(self.api.remove_window_subclass(
                    self._hwnd, self._callback, self._subclass_id
                ))
            except BaseException as exc:  # pragma: no cover - teardown safety
                self.last_error = f"{type(exc).__name__}: {exc}"
        self.installed = False
        self.widget = None
        if removed:
            # Callback lifetime extends through successful removal.  Releasing
            # it afterwards also breaks the callback -> bound method -> bridge
            # reference cycle, preventing a Tk widget from being finalized on
            # a paint worker thread during cyclic garbage collection.
            self._callback = None


def normalize_pressure(raw: float, maximum: float = PEN_PRESSURE_MAX) -> float:
    value = float(raw)
    limit = float(maximum)
    if not math.isfinite(value) or not math.isfinite(limit) or limit <= 0.0:
        return 0.0
    return min(1.0, max(0.0, value / limit))


def pressure_radius_scale(
    pressure: float,
    *,
    minimum_scale: float = 0.15,
    gamma: float = 0.70,
) -> float:
    """Map normalized pressure to a stable 15%-to-100% radius curve."""

    value = min(1.0, max(0.0, float(pressure)))
    minimum = min(1.0, max(0.01, float(minimum_scale)))
    exponent = max(0.05, float(gamma))
    return minimum + (1.0 - minimum) * value**exponent


def _as_xy_points(points: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    result = tuple((float(x), float(y)) for x, y in points)
    if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in result):
        raise ValueError("stroke points must be finite")
    return result


def automatic_taper_scales(
    points: Iterable[tuple[float, float]],
    *,
    minimum_scale: float = 0.15,
    ramp_length_pixels: float | None = None,
    base_radius_pixels: float = 4.0,
) -> tuple[float, ...]:
    """Return deterministic thin-end scales using cumulative stroke length."""

    values = _as_xy_points(points)
    if not values:
        return ()
    minimum = min(1.0, max(0.01, float(minimum_scale)))
    if len(values) == 1:
        return (minimum,)
    cumulative = [0.0]
    for first, second in zip(values, values[1:]):
        cumulative.append(
            cumulative[-1]
            + math.hypot(second[0] - first[0], second[1] - first[1])
        )
    total = cumulative[-1]
    if total <= 1.0e-9:
        return tuple(minimum for _point in values)
    requested_ramp = (
        max(6.0, float(base_radius_pixels) * 2.0)
        if ramp_length_pixels is None
        else max(1.0e-6, float(ramp_length_pixels))
    )
    # Even a short gesture gets a full-width middle instead of becoming one
    # uniformly tiny line.  A two-point stroke remains intentionally thin.
    ramp = min(requested_ramp, total * 0.5)
    if ramp <= 1.0e-9:
        return tuple(minimum for _point in values)

    def smoothstep(amount: float) -> float:
        clipped = min(1.0, max(0.0, amount))
        return clipped * clipped * (3.0 - 2.0 * clipped)

    output = []
    for distance in cumulative:
        end_distance = min(distance, total - distance)
        amount = smoothstep(end_distance / ramp)
        output.append(minimum + (1.0 - minimum) * amount)
    return tuple(output)


def pressure_or_taper_scales(
    points: Iterable[tuple[float, float]],
    pressures: Iterable[float | None],
    *,
    minimum_scale: float = 0.15,
    gamma: float = 0.70,
    base_radius_pixels: float = 4.0,
) -> tuple[tuple[float, ...], str]:
    """Resolve one immutable width profile for both feedback and geometry.

    If at least one fresh native pressure value was correlated with the
    gesture, missing samples are linearly interpolated (edge gaps use the
    nearest valid pressure).  Otherwise a deterministic arc-length taper is
    returned.
    """

    values = _as_xy_points(points)
    raw = tuple(pressures)
    if len(raw) != len(values):
        raise ValueError("pressure sample count must match stroke points")
    valid = [
        index
        for index, pressure in enumerate(raw)
        if pressure is not None and math.isfinite(float(pressure))
    ]
    if not valid:
        return (
            automatic_taper_scales(
                values,
                minimum_scale=minimum_scale,
                base_radius_pixels=base_radius_pixels,
            ),
            "taper",
        )

    normalized: list[float] = [0.0] * len(values)
    for index in valid:
        normalized[index] = min(1.0, max(0.0, float(raw[index])))
    first = valid[0]
    for index in range(first):
        normalized[index] = normalized[first]
    for left, right in zip(valid, valid[1:]):
        span = right - left
        for index in range(left + 1, right):
            amount = (index - left) / span
            normalized[index] = (
                normalized[left] * (1.0 - amount) + normalized[right] * amount
            )
    last = valid[-1]
    for index in range(last + 1, len(values)):
        normalized[index] = normalized[last]
    return (
        tuple(
            pressure_radius_scale(
                value,
                minimum_scale=minimum_scale,
                gamma=gamma,
            )
            for value in normalized
        ),
        "pressure",
    )


__all__ = [
    "NativePenSample",
    "PEN_MASK_PRESSURE",
    "POINTER_FLAG_INCONTACT",
    "POINTER_MESSAGES",
    "PT_PEN",
    "PenPressureBridge",
    "PenSampleHistory",
    "TimedPenSample",
    "WM_NCDESTROY",
    "WM_POINTERDOWN",
    "WM_POINTERUPDATE",
    "WM_POINTERUP",
    "WindowsPointerApi",
    "automatic_taper_scales",
    "normalize_pressure",
    "pressure_or_taper_scales",
    "pressure_radius_scale",
]
