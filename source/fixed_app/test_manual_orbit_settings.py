from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import MapperApp, _geometry_key
from spectrum_mapper.models import AppSettings, PaletteSettings
from test_part_integration import two_part_prepared


class ManualOrbitSettingsTests(unittest.TestCase):
    def test_from_dict_accepts_only_a_real_boolean(self) -> None:
        self.assertTrue(
            AppSettings.from_dict(
                {"manual_orbit_inverted": True}
            ).manual_orbit_inverted
        )
        for invalid in (1, 0, "true", "false", None, [], {}):
            with self.subTest(value=invalid):
                restored = AppSettings.from_dict(
                    {"manual_orbit_inverted": invalid}
                )
                self.assertFalse(restored.manual_orbit_inverted)

    def test_to_dict_keeps_the_global_orbit_preference(self) -> None:
        settings = AppSettings(manual_orbit_inverted=True)
        self.assertIs(settings.to_dict()["manual_orbit_inverted"], True)

    def test_direction_callback_updates_settings_and_saves_immediately(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app.settings = AppSettings()
        app._save_persistent_settings = Mock()

        MapperApp._on_manual_orbit_direction_changed(app, True)

        self.assertTrue(app.settings.manual_orbit_inverted)
        app._save_persistent_settings.assert_called_once_with()

    def test_persistent_file_keeps_orbit_but_removes_model_identity(self) -> None:
        app = MapperApp.__new__(MapperApp)
        digest = "a" * 64
        settings = AppSettings(
            part_palettes={"private-part": PaletteSettings()},
            part_names={"private-part": "Private Part"},
            manual_view_backgrounds={digest: "light"},
            manual_orbit_inverted=True,
        )
        app._variables_to_settings = lambda *, show_error=False: settings

        with TemporaryDirectory() as temporary:
            target_dir = Path(temporary)
            with patch(
                "spectrum_mapper.gui._configuration_dir",
                return_value=target_dir,
            ):
                MapperApp._save_persistent_settings(app)
            payload = json.loads(
                (target_dir / "settings.json").read_text(encoding="utf-8-sig")
            )

        self.assertIs(payload["manual_orbit_inverted"], True)
        self.assertEqual(payload["palette_state_count"], 16)
        self.assertIn("geometry", payload)
        self.assertNotIn("tone", payload)
        self.assertNotIn("palette", payload)
        self.assertNotIn("part_palettes", payload)
        self.assertNotIn("part_names", payload)
        self.assertNotIn("manual_view_backgrounds", payload)

    def test_open_editor_receives_the_persistent_direction_callback(self) -> None:
        app = MapperApp.__new__(MapperApp)
        prepared = two_part_prepared()
        settings = AppSettings(manual_orbit_inverted=False)
        app.root = object()
        app.prepared = prepared
        app.obj_path = prepared.source.path
        app.prepared_key = _geometry_key(settings.geometry)
        app.paint_editor = None
        app.settings = settings
        app.reference_image = None
        app.manual_overrides = None
        app._open_boundary_diagnostics_on_paint = False
        app.i18n = SimpleNamespace(language="ja")
        app._variables_to_settings = lambda *, show_error=True: settings
        app._solidify_parts_from_paint_editor = lambda: None
        app._save_persistent_settings = Mock()
        captured: dict[str, object] = {}

        def fake_editor(*_args, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace()

        with patch("spectrum_mapper.gui.PaintEditorWindow", side_effect=fake_editor):
            MapperApp._open_paint_editor(app)

        callback = captured.get("on_orbit_direction_changed")
        self.assertTrue(callable(callback))
        callback(True)
        self.assertTrue(app.settings.manual_orbit_inverted)
        app._save_persistent_settings.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
