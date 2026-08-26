from __future__ import annotations

import ctypes
import os
from types import SimpleNamespace
import unittest

from spectrum_mapper import pen_pressure as pressure
from spectrum_mapper.i18n import Translator


class _FakeWidget:
    def __init__(self) -> None:
        self.bindings = []

    def update_idletasks(self) -> None:
        pass

    def winfo_id(self) -> int:
        return 12345

    def bind(self, sequence, callback, add=None):
        self.bindings.append((sequence, callback, add))
        return "binding"


class _FakeApi:
    available = True
    unavailable_reason = ""

    def __init__(self) -> None:
        self.samples = []
        self.installs = []
        self.removals = []
        self.forwarded = []
        self.raise_on_read = False

    def make_callback(self, callback):
        return callback

    def set_window_subclass(self, hwnd, callback, subclass_id):
        self.installs.append((hwnd, callback, subclass_id))
        return True

    def remove_window_subclass(self, hwnd, callback, subclass_id):
        self.removals.append((hwnd, callback, subclass_id))
        return True

    def def_subclass_proc(self, hwnd, message, wparam, lparam):
        self.forwarded.append((hwnd, message, wparam, lparam))
        return 731

    def read_pen_sample(self, pointer_id, hwnd):
        if self.raise_on_read:
            raise RuntimeError("synthetic driver failure")
        if not self.samples:
            return None
        return self.samples.pop(0)


class _UnavailableApi(_FakeApi):
    available = False
    unavailable_reason = "unsupported"


class PenPressureTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Win32 ABI layout")
    def test_win32_constants_and_native_layout_match_64_bit_headers(self) -> None:
        self.assertEqual(pressure.WM_POINTERUPDATE, 0x0245)
        self.assertEqual(pressure.WM_POINTERDOWN, 0x0246)
        self.assertEqual(pressure.WM_POINTERUP, 0x0247)
        self.assertEqual(pressure.PT_PEN, 3)
        self.assertEqual(pressure.PEN_MASK_PRESSURE, 1)
        self.assertEqual(ctypes.sizeof(pressure._POINT), 8)
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(pressure._POINTER_INFO), 96)
            self.assertEqual(ctypes.sizeof(pressure._POINTER_PEN_INFO), 120)
            self.assertEqual(pressure._POINTER_INFO.PerformanceCount.offset, 80)
            self.assertEqual(pressure._POINTER_PEN_INFO.pressure.offset, 104)

    def test_bridge_observes_pressure_but_always_forwards_to_tk(self) -> None:
        api = _FakeApi()
        api.samples.append(pressure.NativePenSample(40.0, 30.0, 0.25, True))
        now = [1_000_000_000]
        bridge = pressure.PenPressureBridge(
            _FakeWidget(), api=api, clock_ns=lambda: now[0]
        )
        self.assertTrue(bridge.enabled)
        callback = api.installs[0][1]
        result = callback(
            12345,
            pressure.WM_POINTERUPDATE,
            77,
            99,
            api.installs[0][2],
            0,
        )
        self.assertEqual(result, 731)
        self.assertEqual(api.forwarded, [(12345, pressure.WM_POINTERUPDATE, 77, 99)])
        self.assertAlmostEqual(
            bridge.pressure_for_event(SimpleNamespace(x=40, y=30)), 0.25
        )
        self.assertTrue(bridge.detected)

    def test_driver_exception_is_contained_and_message_still_forwards(self) -> None:
        api = _FakeApi()
        api.raise_on_read = True
        bridge = pressure.PenPressureBridge(_FakeWidget(), api=api)
        callback = api.installs[0][1]
        self.assertEqual(
            callback(12345, pressure.WM_POINTERDOWN, 5, 6, 7, 0),
            731,
        )
        self.assertIn("synthetic driver failure", bridge.last_error)
        self.assertEqual(len(api.forwarded), 1)

    def test_close_holds_callback_through_remove_then_breaks_native_cycle(self) -> None:
        api = _FakeApi()
        bridge = pressure.PenPressureBridge(_FakeWidget(), api=api)
        callback = bridge._callback
        bridge.close()
        bridge.close()
        self.assertEqual(len(api.removals), 1)
        self.assertIs(api.removals[0][1], callback)
        self.assertIsNone(bridge._callback)
        self.assertIsNone(bridge.widget)
        self.assertFalse(bridge.enabled)

    def test_native_destroy_removes_subclass_and_still_forwards(self) -> None:
        api = _FakeApi()
        bridge = pressure.PenPressureBridge(_FakeWidget(), api=api)
        callback = api.installs[0][1]
        self.assertEqual(
            callback(12345, pressure.WM_NCDESTROY, 0, 0, 1, 0),
            731,
        )
        self.assertEqual(len(api.removals), 1)
        self.assertEqual(api.forwarded[-1][1], pressure.WM_NCDESTROY)
        self.assertFalse(bridge.installed)

    def test_unsupported_platform_api_fails_open(self) -> None:
        api = _UnavailableApi()
        bridge = pressure.PenPressureBridge(_FakeWidget(), api=api)
        self.assertFalse(bridge.enabled)
        self.assertEqual(bridge.availability, "unavailable")
        self.assertEqual(api.installs, [])
        self.assertIsNone(
            bridge.pressure_for_event(SimpleNamespace(x=1, y=2))
        )

    def test_history_rejects_stale_distant_and_hover_samples(self) -> None:
        history = pressure.PenSampleHistory(
            max_age_ms=100.0, max_distance_pixels=5.0
        )
        history.add(pressure.NativePenSample(10, 10, 0.4, True), 1_000_000_000)
        self.assertAlmostEqual(history.match(12, 12, 1_050_000_000), 0.4)
        self.assertIsNone(history.match(20, 20, 1_050_000_000))
        self.assertIsNone(history.match(10, 10, 1_101_000_000))
        history.add(pressure.NativePenSample(10, 10, 0.0, False), 2_000_000_000)
        self.assertIsNone(history.match(10, 10, 2_001_000_000))

    def test_pressure_curve_has_requested_minimum_and_full_radius(self) -> None:
        values = [
            pressure.pressure_radius_scale(value)
            for value in (0.0, 0.2, 0.5, 0.8, 1.0)
        ]
        self.assertAlmostEqual(values[0], 0.15)
        self.assertAlmostEqual(values[-1], 1.0)
        self.assertEqual(values, sorted(values))
        self.assertEqual(pressure.normalize_pressure(4096, 8191), 4096 / 8191)

    def test_pressure_profile_interpolates_missing_samples(self) -> None:
        scales, source = pressure.pressure_or_taper_scales(
            [(0, 0), (5, 0), (10, 0)],
            [0.0, None, 1.0],
        )
        self.assertEqual(source, "pressure")
        self.assertAlmostEqual(scales[0], 0.15)
        self.assertAlmostEqual(scales[-1], 1.0)
        self.assertGreater(scales[1], scales[0])
        self.assertLess(scales[1], scales[-1])

    def test_missing_pressure_uses_arc_length_taper(self) -> None:
        scales, source = pressure.pressure_or_taper_scales(
            [(0, 0), (5, 0), (10, 0)],
            [None, None, None],
            base_radius_pixels=2.0,
        )
        self.assertEqual(source, "taper")
        self.assertEqual(scales, (0.15, 1.0, 0.15))
        self.assertEqual(
            pressure.automatic_taper_scales([(3, 4)]),
            (0.15,),
        )

    def test_pressure_nib_and_availability_copy_is_bilingual(self) -> None:
        self.assertIn("筆圧ペン", Translator("ja").text("paint.pressure_taper_nib"))
        self.assertIn("Pressure Pen", Translator("en").text("paint.pressure_taper_nib"))
        self.assertIn("Windows Ink", Translator("ja").text("paint.pressure_waiting"))
        self.assertIn("waiting", Translator("en").text("paint.pressure_waiting"))


if __name__ == "__main__":
    unittest.main()
