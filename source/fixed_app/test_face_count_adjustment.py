from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import (
    MapperApp,
    _geometry_key,
    _mix_optimizer_settings_key,
    _paint_topology_key,
)
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import AppSettings, GeometrySettings


class FaceCountAdjustmentTests(unittest.TestCase):
    def test_old_project_defaults_to_established_adjustment(self) -> None:
        settings = AppSettings.from_dict(
            {"geometry": {"target_faces": 123_456}}
        )

        self.assertTrue(settings.geometry.adjust_face_count)
        self.assertEqual(settings.geometry.target_faces, 123_456)

    def test_new_project_round_trip_preserves_full_resolution_choice(self) -> None:
        settings = AppSettings()
        settings.geometry.adjust_face_count = False

        restored = AppSettings.from_dict(settings.to_dict())

        self.assertFalse(restored.geometry.adjust_face_count)

    def test_target_is_not_a_geometry_or_paint_key_when_adjustment_is_off(self) -> None:
        first = GeometrySettings(adjust_face_count=False, target_faces=16_000)
        second = GeometrySettings(adjust_face_count=False, target_faces=32_000)

        self.assertEqual(_geometry_key(first), _geometry_key(second))
        self.assertEqual(_paint_topology_key(first), _paint_topology_key(second))

        first.adjust_face_count = True
        second.adjust_face_count = True
        self.assertNotEqual(_geometry_key(first), _geometry_key(second))
        self.assertNotEqual(_paint_topology_key(first), _paint_topology_key(second))

    def test_target_is_not_a_mix_key_when_adjustment_is_off(self) -> None:
        first = AppSettings()
        second = AppSettings.from_dict(first.to_dict())
        first.geometry.adjust_face_count = False
        second.geometry.adjust_face_count = False
        first.geometry.target_faces = 16_000
        second.geometry.target_faces = 32_000

        self.assertEqual(
            _mix_optimizer_settings_key(first),
            _mix_optimizer_settings_key(second),
        )

        first.geometry.adjust_face_count = True
        second.geometry.adjust_face_count = True
        self.assertNotEqual(
            _mix_optimizer_settings_key(first),
            _mix_optimizer_settings_key(second),
        )

    def test_high_full_resolution_model_requires_confirmation_for_manual_editing(self) -> None:
        app = MapperApp.__new__(MapperApp)
        settings = AppSettings()
        settings.geometry.adjust_face_count = False
        app.prepared = SimpleNamespace(
            final=SimpleNamespace(faces=range(500_000))
        )
        app.obj_path = Path("synthetic.obj")
        app.prepared_key = _geometry_key(settings.geometry)
        app._variables_to_settings = lambda **_kwargs: settings
        app._manual_high_face_warning_key = None
        app.i18n = Translator("ja")
        app.root = object()
        app.paint_editor = None

        with patch(
            "spectrum_mapper.gui.messagebox.askyesno", return_value=False
        ) as confirm:
            MapperApp._open_paint_editor(app)

        confirm.assert_called_once()
        self.assertIn("500,000面", confirm.call_args.args[1])
        self.assertIsNone(app._manual_high_face_warning_key)

    def test_cancelled_restore_keeps_applied_mode_and_target_value(self) -> None:
        class Variable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        app = MapperApp.__new__(MapperApp)
        app.paint_editor = None
        app.obj_path = Path("synthetic.obj")
        app.asset = object()
        app.prepared = object()
        app.prepared_key = (450_000, 80_000)
        app.adjust_face_count_var = Variable(True)
        app.target_faces_var = Variable(450_000)
        app._manual_high_face_warning_key = None

        with (
            patch.object(app, "_note_mix_input_change"),
            patch.object(app, "_update_face_count_status"),
            patch.object(app, "_process_geometry", return_value=False),
        ):
            MapperApp._restore_original_face_count(app)

        self.assertTrue(app.adjust_face_count_var.get())
        self.assertEqual(app.target_faces_var.get(), 450_000)


if __name__ == "__main__":
    unittest.main()
