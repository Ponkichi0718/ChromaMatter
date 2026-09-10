from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.gui import (
    MapperApp,
    _developer_features_enabled_from_mapping,
    _fresh_settings_for_new_obj,
    _persistent_preferences_from_mapping,
    _persistent_preferences_payload,
    _project_settings_from_mapping,
    _recommendation_policy_from_mapping,
)
from spectrum_mapper.filament_recommender import (
    DEFAULT_RECOMMENDATION_POLICY,
    RECOMMENDATION_POLICY_BASIC,
    RECOMMENDATION_POLICY_FLEXIBLE,
)
from spectrum_mapper.models import (
    AppSettings,
    COLOR_MODE_FLAT_FOUR,
    COLOR_MODE_FULL_SPECTRUM,
    DEFAULT_NEW_COLOR_MODE,
    ColorDepthSettings,
    GeometrySettings,
    PaletteSettings,
    RadialSettings,
    ToneSettings,
)
from spectrum_mapper.platform_runtime import APPLICATION_DATA_DIRECTORY_ENV


class Variable:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


def model_settings(*, state_count: int = 24) -> AppSettings:
    return AppSettings(
        geometry=GeometrySettings(height_mm=123.0, target_faces=321_000),
        tone=ToneSettings(black_point=0.25, contrast=1.4, saturation=0.7),
        palette=PaletteSettings(
            palette_state_count=state_count,
            physical_hex=["#101010", "#E32636", "#6F38A8", "#C98B63"],
            mix_ratios_b=[41] * 6,
            secondary_mix_ratios_b=[79] * 6,
        ),
        part_palettes={"old-part": PaletteSettings(physical_hex=["#112233"] * 4)},
        part_names={"old-part": "Old model"},
        radial=RadialSettings(outer_skin_thickness_mm=0.22),
        manual_view_backgrounds={"a" * 64: "light"},
        manual_orbit_inverted=True,
    )


def bare_app(settings: AppSettings) -> MapperApp:
    app = MapperApp.__new__(MapperApp)
    app.paint_editor = None
    app.busy = False
    app.root = object()
    app.i18n = SimpleNamespace(text=lambda key, **_kwargs: key)
    app.settings = settings
    app.active_part_key = "old-part"
    app._auto_recommend_after_geometry = False
    app._project_obj_recovery_pending = False
    app._cancel_eyedropper = Mock()
    app._note_mix_input_change = Mock()
    app._sync_tone_variables = Mock()
    app._load_palette_variables = Mock()
    app._refresh_palette_widgets = Mock()
    app._clear_mix_optimization_undo = Mock()
    app._update_face_count_status = Mock()
    app._process_geometry = Mock(return_value=True)
    app.manual_overrides = np.asarray([3], dtype=np.int8)
    app.manual_fingerprint = "old"
    app.pending_manual_payload = {"paint": "pending"}
    app.manual_part_partition = {"parts": "old"}
    app.pending_manual_part_partition = {"parts": "pending"}
    app.manual_joint_record = {"joint": "old"}
    app.pending_manual_joint_record = {"joint": "pending"}
    app.part_recommendations = {"old-part": object()}
    app.part_target_var = Variable("old-part")
    app.part_name_var = Variable("Old model")
    app.main_active_part_var = Variable("old-part")
    app.recommendation_var = Variable("old recommendation")
    app.solidify_parts_var = Variable(True)
    app.repair_unmatched_boundaries_var = Variable(True)
    app.auto_joints_var = Variable(True)
    app.adjust_face_count_var = Variable(True)
    app._open_boundary_diagnostics_on_paint = True
    app._manual_high_face_warning_key = ("old",)
    app.obj_path = None
    app.obj_name_var = Variable("OBJ: old.obj")
    return app


class NewObjDefaultTests(unittest.TestCase):
    def test_new_session_defaults_to_flat_four_without_rewriting_legacy_projects(self) -> None:
        self.assertEqual(DEFAULT_NEW_COLOR_MODE, COLOR_MODE_FLAT_FOUR)
        self.assertEqual(
            _persistent_preferences_from_mapping({}).palette.color_mode,
            COLOR_MODE_FLAT_FOUR,
        )
        self.assertEqual(
            _persistent_preferences_from_mapping(
                {"color_mode": COLOR_MODE_FULL_SPECTRUM}
            ).palette.color_mode,
            COLOR_MODE_FULL_SPECTRUM,
        )
        self.assertEqual(
            _project_settings_from_mapping(
                {"schema": "obj-adjuster.project.v12", "settings": {}}
            ).palette.color_mode,
            COLOR_MODE_FULL_SPECTRUM,
        )

    def test_missing_preferences_file_starts_in_flat_four(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = MapperApp.__new__(MapperApp)
            with patch.dict(
                os.environ,
                {APPLICATION_DATA_DIRECTORY_ENV: temporary},
            ):
                restored = app._load_persistent_settings()
        self.assertEqual(restored.palette.color_mode, COLOR_MODE_FLAT_FOUR)

    def test_public_load_sanitizes_every_hidden_experiment(self) -> None:
        stale_palette = PaletteSettings(
            black_free_gradient_enabled=True,
            surface_shell_enabled=True,
        )
        stale = AppSettings(
            geometry=GeometrySettings(
                auto_joints=True,
                split_enabled=True,
            ),
            color_depth=ColorDepthSettings(experimental_enabled=True),
            palette=stale_palette,
            part_palettes={
                "coat": PaletteSettings(
                    black_free_gradient_enabled=True,
                    surface_shell_enabled=True,
                )
            },
        )
        restored = _project_settings_from_mapping(
            {
                "schema": "obj-adjuster.project.v11",
                "settings": stale.to_dict(),
            },
            developer_features_enabled=True,
        )

        self.assertFalse(restored.geometry.auto_joints)
        self.assertFalse(restored.geometry.split_enabled)
        self.assertFalse(restored.color_depth.experimental_enabled)
        for palette in (restored.palette, *restored.part_palettes.values()):
            self.assertFalse(palette.black_free_gradient_enabled)
            self.assertFalse(palette.surface_shell_enabled)

    def test_legacy_persistent_colors_and_tone_are_ignored(self) -> None:
        old = model_settings(state_count=24).to_dict()
        restored = _persistent_preferences_from_mapping(old)

        self.assertEqual(restored.geometry.height_mm, 123.0)
        self.assertEqual(restored.geometry.target_faces, 321_000)
        self.assertEqual(restored.palette.palette_state_count, 24)
        self.assertEqual(restored.palette.physical_hex, PaletteSettings().physical_hex)
        self.assertEqual(restored.palette.mix_ratios_b, [33] * 6)
        self.assertEqual(restored.tone, ToneSettings())
        self.assertEqual(restored.part_palettes, {})
        self.assertEqual(restored.part_names, {})
        self.assertTrue(restored.manual_orbit_inverted)

    def test_new_persistent_payload_contains_only_cross_model_preferences(self) -> None:
        payload = _persistent_preferences_payload(model_settings(state_count=32))

        self.assertEqual(
            payload["schema"],
            "obj-adjuster.preferences.v5-developer-features",
        )
        self.assertFalse(payload["developer_features_enabled"])
        self.assertEqual(
            payload["recommendation_policy"],
            RECOMMENDATION_POLICY_FLEXIBLE,
        )
        self.assertEqual(payload["palette_state_count"], 32)
        self.assertIn("geometry", payload)
        self.assertEqual(
            payload["radial"]["outer_skin_thickness_mm"], 0.22
        )
        self.assertFalse(payload["color_depth"]["experimental_enabled"])
        self.assertEqual(payload["color_depth"]["outer_thickness_mm"], 0.15)
        self.assertTrue(payload["manual_orbit_inverted"])
        for forbidden in (
            "tone",
            "palette",
            "part_palettes",
            "part_names",
            "manual_view_backgrounds",
        ):
            self.assertNotIn(forbidden, payload)

    def test_recommendation_policy_is_global_and_defaults_to_current_flexible_mode(
        self,
    ) -> None:
        self.assertEqual(
            _recommendation_policy_from_mapping({}),
            DEFAULT_RECOMMENDATION_POLICY,
        )
        self.assertEqual(
            _recommendation_policy_from_mapping(
                {"recommendation_policy": RECOMMENDATION_POLICY_BASIC}
            ),
            RECOMMENDATION_POLICY_BASIC,
        )
        self.assertEqual(
            _recommendation_policy_from_mapping(
                {"recommendation_policy": "unsupported"}
            ),
            RECOMMENDATION_POLICY_FLEXIBLE,
        )
        payload = _persistent_preferences_payload(
            model_settings(),
            recommendation_policy=RECOMMENDATION_POLICY_BASIC,
        )
        self.assertEqual(
            _recommendation_policy_from_mapping(payload),
            RECOMMENDATION_POLICY_BASIC,
        )
        self.assertNotIn("recommendation_policy", AppSettings().to_dict())

    def test_developer_feature_preference_is_strict_and_fail_closed(self) -> None:
        schema = "obj-adjuster.preferences.v5-developer-features"
        self.assertTrue(
            _developer_features_enabled_from_mapping(
                {"schema": schema, "developer_features_enabled": True}
            )
        )
        for value in (False, 1, 0, "true", "false", None, [], {}):
            with self.subTest(value=value):
                self.assertFalse(
                    _developer_features_enabled_from_mapping(
                        {
                            "schema": schema,
                            "developer_features_enabled": value,
                        }
                    )
                )
        self.assertFalse(
            _developer_features_enabled_from_mapping(
                {
                    "schema": "obj-adjuster.preferences.v4-color-depth-lab",
                    "developer_features_enabled": True,
                }
            )
        )
        self.assertFalse(_developer_features_enabled_from_mapping({}))

    def test_developer_feature_preference_round_trips_outside_app_settings(self) -> None:
        payload = _persistent_preferences_payload(
            model_settings(), developer_features_enabled=True
        )
        self.assertTrue(_developer_features_enabled_from_mapping(payload))
        self.assertTrue(payload["developer_features_enabled"])
        self.assertNotIn("developer_features_enabled", AppSettings().to_dict())

    def test_persistent_loader_commits_only_the_global_v5_gate(self) -> None:
        payload = _persistent_preferences_payload(
            model_settings(),
            developer_features_enabled=True,
            recommendation_policy=RECOMMENDATION_POLICY_BASIC,
        )
        with tempfile.TemporaryDirectory() as temporary:
            settings_path = Path(temporary) / "settings.json"
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps(payload), encoding="utf-8-sig"
            )
            app = MapperApp.__new__(MapperApp)
            with patch.dict(
                os.environ,
                {APPLICATION_DATA_DIRECTORY_ENV: temporary},
            ):
                restored = app._load_persistent_settings()
        self.assertTrue(app._loaded_developer_features_enabled)
        self.assertEqual(
            app._loaded_recommendation_policy,
            RECOMMENDATION_POLICY_BASIC,
        )
        self.assertIsInstance(restored, AppSettings)
        self.assertNotIn("developer_features_enabled", restored.to_dict())

    def test_fresh_obj_resets_model_color_state_but_keeps_quality(self) -> None:
        fresh = _fresh_settings_for_new_obj(model_settings(state_count=32))

        self.assertEqual(fresh.geometry.height_mm, 123.0)
        self.assertEqual(fresh.palette.palette_state_count, 32)
        self.assertEqual(fresh.palette.physical_hex, PaletteSettings().physical_hex)
        self.assertEqual(fresh.tone, ToneSettings())
        self.assertEqual(fresh.part_palettes, {})
        self.assertEqual(fresh.part_names, {})
        self.assertEqual(fresh.radial.outer_skin_thickness_mm, 0.22)
        self.assertTrue(fresh.manual_orbit_inverted)
        self.assertEqual(fresh.manual_view_backgrounds, {"a" * 64: "light"})

    def test_open_new_obj_resets_then_requests_automatic_recommendation(self) -> None:
        app = bare_app(model_settings(state_count=24))
        with patch(
            "spectrum_mapper.gui.filedialog.askopenfilename",
            return_value="C:/models/new.obj",
        ):
            MapperApp._choose_obj(app)

        self.assertEqual(app.obj_path, Path("C:/models/new.obj"))
        self.assertEqual(app.settings.tone, ToneSettings())
        self.assertEqual(app.settings.palette.palette_state_count, 24)
        self.assertEqual(app.settings.palette.physical_hex, PaletteSettings().physical_hex)
        self.assertEqual(app.settings.part_palettes, {})
        self.assertIsNone(app.manual_overrides)
        self.assertIsNone(app.pending_manual_payload)
        self.assertTrue(app._auto_recommend_after_geometry)
        self.assertFalse(app.solidify_parts_var.get())
        self.assertFalse(app.repair_unmatched_boundaries_var.get())
        self.assertFalse(app.auto_joints_var.get())
        self.assertFalse(app.adjust_face_count_var.get())
        app._process_geometry.assert_called_once_with(reuse_asset=False)

    def test_later_obj_selection_can_restore_a_project_with_a_moved_source(self) -> None:
        settings = model_settings(state_count=32)
        app = bare_app(settings)
        app._project_obj_recovery_pending = True
        pending_paint = app.pending_manual_payload
        pending_parts = app.pending_manual_part_partition
        pending_joint = app.pending_manual_joint_record

        with patch(
            "spectrum_mapper.gui.filedialog.askopenfilename",
            return_value="D:/moved/original.obj",
        ):
            MapperApp._choose_obj(app)

        self.assertIs(app.settings, settings)
        self.assertIs(app.pending_manual_payload, pending_paint)
        self.assertIs(app.pending_manual_part_partition, pending_parts)
        self.assertIs(app.pending_manual_joint_record, pending_joint)
        self.assertTrue(app.solidify_parts_var.get())
        self.assertTrue(app.adjust_face_count_var.get())
        self.assertFalse(app._auto_recommend_after_geometry)
        self.assertTrue(app._project_obj_recovery_pending)
        kwargs = app._process_geometry.call_args.kwargs
        self.assertFalse(kwargs["reuse_asset"])
        self.assertTrue(callable(kwargs["after_done"]))
        kwargs["after_done"]()
        self.assertFalse(app._project_obj_recovery_pending)

    def test_queued_new_obj_recommendation_cannot_overwrite_project_load(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app.obj_path = Path("C:/models/new.obj")
        app.prepared = object()
        app.busy = False
        app._auto_recommend_after_geometry = False
        app._recommend_all_parts = Mock()
        app.root = SimpleNamespace(after=Mock())

        MapperApp._run_new_obj_auto_recommendation(
            app, Path("C:/models/new.obj")
        )

        app._recommend_all_parts.assert_not_called()
        app.root.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
