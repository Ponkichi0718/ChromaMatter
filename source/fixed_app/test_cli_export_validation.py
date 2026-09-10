from __future__ import annotations

import contextlib
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, patch

from spectrum_mapper.cli import build_parser, convert, main
from spectrum_mapper.engine import EngineError
from spectrum_mapper.models import AppSettings, EXPORT_VALIDATION_LEVELS


class CliExportValidationTests(unittest.TestCase):
    def _arguments(self, *extra: str):
        return build_parser().parse_args(
            ["--convert", "model.glb", "--output", "model.3mf", *extra]
        )

    def _convert(self, args):
        asset = object()
        prepared = object()
        result = SimpleNamespace(
            model_path=Path("model.3mf"), report_path=Path("model_report.json")
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch(
                "spectrum_mapper.engine.load_vertex_color_model",
                return_value=asset,
            ) as loader,
            patch(
                "spectrum_mapper.engine.prepare_geometry",
                return_value=prepared,
            ) as prepare,
            patch(
                "spectrum_mapper.workflow.export_bundle", return_value=result
            ) as export,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(convert(args), 0)
        loader.assert_called_once_with(
            Path("model.glb"), ANY, allow_large_reduced_source=True
        )
        prepare.assert_called_once_with(asset, ANY, ANY)
        export.assert_called_once_with(
            prepared, ANY, Path("model.3mf"), None,
            include_vertex_obj=True, progress=ANY,
        )
        self.assertIs(prepare.call_args.args[1], export.call_args.args[1].geometry)
        self.assertIn("3MF: model.3mf", stdout.getvalue())
        return export.call_args.args[1], stderr.getvalue()

    def test_parser_choices_match_settings_contract(self):
        parser = build_parser()
        action = next(
            action for action in parser._actions
            if action.dest == "export_validation"
        )
        self.assertEqual(tuple(action.choices), EXPORT_VALIDATION_LEVELS)
        for level in EXPORT_VALIDATION_LEVELS:
            with self.subTest(level=level):
                self.assertEqual(
                    self._arguments("--export-validation", level).export_validation,
                    level,
                )

    def test_omitted_flag_does_not_override_saved_settings(self):
        self.assertIsNone(self._arguments().export_validation)

    def test_parser_rejects_invalid_explicit_levels(self):
        for level in ("HIGH", "none", "off", "", "disabled"):
            with self.subTest(level=level), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    self._arguments("--export-validation", level)
                self.assertEqual(raised.exception.code, 2)

    def test_policy_flag_without_conversion_is_not_silently_ignored(self):
        for extra in ([], ["--self-test"], ["--model", "model.glb"]):
            with self.subTest(extra=extra):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                    main(["--export-validation", "low", *extra])
                self.assertIn("--export-validation requires --convert", stderr.getvalue())

    def test_default_high_keeps_safe_preparation_and_default_palette(self):
        settings, warning = self._convert(self._arguments())
        self.assertEqual(settings.export_validation_level, "high")
        self.assertTrue(settings.geometry.solidify_parts)
        self.assertTrue(settings.geometry.adjust_face_count)
        self.assertFalse(settings.geometry.auto_joints)
        self.assertEqual(settings.geometry.height_mm, 180.0)
        self.assertEqual(settings.palette.color_mode, "flat_four")
        self.assertEqual(warning, "")

    def test_legacy_namespace_without_new_flag_still_uses_high(self):
        args = self._arguments()
        del args.export_validation
        settings, warning = self._convert(args)
        self.assertEqual(settings.export_validation_level, "high")
        self.assertTrue(settings.geometry.solidify_parts)
        self.assertEqual(warning, "")

    def test_each_explicit_policy_reaches_export_without_other_changes(self):
        for level in EXPORT_VALIDATION_LEVELS:
            with self.subTest(level=level):
                settings, warning = self._convert(
                    self._arguments("--export-validation", level)
                )
                self.assertEqual(settings.export_validation_level, level)
                self.assertEqual(
                    settings.geometry.solidify_parts, level in {"high", "medium"}
                )
                self.assertTrue(settings.geometry.adjust_face_count)
                self.assertFalse(settings.geometry.auto_joints)
                self.assertEqual(settings.palette.color_mode, "flat_four")
                if level == "high":
                    self.assertEqual(warning, "")
                else:
                    self.assertIn(f"'{level}'", warning)
                    self.assertIn("self-intersections are not checked", warning)
                    self.assertIn("Archive, color and printer-setting checks remain enabled", warning)
                    self.assertIn("Inspect the 3MF in your slicer", warning)
                    if level == "ignore":
                        self.assertIn("not recommended", warning)

    def test_saved_nonhigh_policy_is_respected_and_warned(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            for level in ("medium", "low", "ignore"):
                with self.subTest(level=level):
                    saved = AppSettings(export_validation_level=level)
                    saved.geometry.solidify_parts = True
                    saved.geometry.adjust_face_count = False
                    saved.geometry.auto_joints = True
                    saved.geometry.height_mm = 150.0
                    path.write_text(json.dumps(saved.to_dict()), encoding="utf-8")
                    settings, warning = self._convert(
                        self._arguments("--settings", str(path))
                    )
                    self.assertEqual(settings.export_validation_level, level)
                    self.assertEqual(settings.geometry.solidify_parts, level == "medium")
                    self.assertTrue(settings.geometry.adjust_face_count)
                    self.assertFalse(settings.geometry.auto_joints)
                    self.assertEqual(settings.geometry.height_mm, 150.0)
                    self.assertEqual(asdict(settings.palette), asdict(saved.palette))
                    self.assertIn(f"'{level}'", warning)

    def test_explicit_policy_overrides_saved_policy_in_both_directions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            for saved_level, override in (("ignore", "high"), ("high", "low")):
                with self.subTest(saved=saved_level, override=override):
                    saved = AppSettings(export_validation_level=saved_level)
                    path.write_text(json.dumps(saved.to_dict()), encoding="utf-8")
                    settings, warning = self._convert(self._arguments(
                        "--settings", str(path), "--export-validation", override
                    ))
                    self.assertEqual(settings.export_validation_level, override)
                    self.assertEqual(settings.geometry.solidify_parts, override == "high")
                    self.assertEqual(bool(warning), override != "high")

    def test_malformed_saved_policy_fails_safe_to_high(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            saved = AppSettings().to_dict()
            saved["export_validation_level"] = "relaxed"
            path.write_text(json.dumps(saved), encoding="utf-8")
            settings, warning = self._convert(self._arguments("--settings", str(path)))
            self.assertEqual(settings.export_validation_level, "high")
            self.assertTrue(settings.geometry.solidify_parts)
            self.assertEqual(warning, "")

    def test_invalid_direct_override_stops_before_model_loading(self):
        for value in ("relaxed", "HIGH", False, [], {}):
            with self.subTest(value=value):
                args = self._arguments()
                args.export_validation = value
                with patch("spectrum_mapper.engine.load_vertex_color_model") as loader:
                    with self.assertRaisesRegex(SystemExit, "--export-validation must"):
                        convert(args)
                loader.assert_not_called()

    def test_nonhigh_does_not_swallow_preparation_or_export_failures(self):
        for level in ("medium", "low", "ignore"):
            for failing_step in ("prepare_geometry", "export_bundle"):
                with self.subTest(level=level, failing_step=failing_step):
                    failure = EngineError("mandatory validation failed")
                    with (
                        patch("spectrum_mapper.engine.load_vertex_color_model"),
                        patch("spectrum_mapper.engine.prepare_geometry") as prepare,
                        patch("spectrum_mapper.workflow.export_bundle") as export,
                        contextlib.redirect_stderr(io.StringIO()),
                    ):
                        failing = prepare if failing_step == "prepare_geometry" else export
                        failing.side_effect = failure
                        with self.assertRaises(EngineError) as raised:
                            convert(self._arguments("--export-validation", level))
                        self.assertIs(raised.exception, failure)
                        if failing_step == "prepare_geometry":
                            export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
