from __future__ import annotations

from io import BytesIO
import json
import math
import unittest
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import slicer_safety as safety


def diagnostic_codes(items: tuple[safety.SafetyDiagnostic, ...]) -> set[str]:
    return {item.code for item in items}


class ModelSettingsSupportTests(unittest.TestCase):
    def test_disable_changes_only_enabled_value_bytes(self):
        source = (
            b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
            b"<config>\r\n"
            b'  <metadata key="name" value="sample"/>\r\n'
            b'  <metadata key="enable_support" value="1"/>\r\n'
            b"</config>\r\n"
        )
        expected = source.replace(
            b'key="enable_support" value="1"',
            b'key="enable_support" value="0"',
        )

        result = safety.sanitize_model_settings_support(source)

        self.assertTrue(result.changed)
        self.assertFalse(result.has_errors)
        self.assertEqual(result.data, expected)
        self.assertEqual(
            diagnostic_codes(result.diagnostics), {"support_override_disabled"}
        )
        ElementTree.fromstring(result.data)

    def test_disable_handles_single_quotes_attribute_order_and_whitespace(self):
        source = (
            b"<config>\n"
            b" <metadata value = ' 1 ' another='kept' key = 'enable_support' />\n"
            b"</config>"
        )
        result = safety.sanitize_model_settings_support(source)
        self.assertTrue(result.changed)
        self.assertIn(b"value = '0' another='kept'", result.data)
        self.assertIn(b"key = 'enable_support'", result.data)

    def test_disable_handles_namespace_without_reserializing(self):
        source = (
            b'<cfg:config xmlns:cfg="urn:test">'
            b'<cfg:metadata cfg:key="enable_support" cfg:value="1"/>'
            b"</cfg:config>"
        )
        result = safety.sanitize_model_settings_support(source)
        self.assertTrue(result.changed)
        self.assertEqual(result.data.count(b'cfg:value="0"'), 1)
        self.assertNotIn(b'cfg:value="1"', result.data)

    def test_remove_deletes_self_closing_override_only(self):
        source = (
            b"<config>\n"
            b'  <metadata key="name" value="keep"/>\n'
            b'  <metadata key="enable_support" value="1"/>\n'
            b"</config>"
        )
        result = safety.sanitize_model_settings_support(source, mode="remove")
        self.assertTrue(result.changed)
        self.assertNotIn(b"enable_support", result.data)
        self.assertIn(b'value="keep"', result.data)
        self.assertEqual(
            diagnostic_codes(result.diagnostics), {"support_override_removed"}
        )
        ElementTree.fromstring(result.data)

    def test_remove_handles_explicit_empty_element(self):
        source = (
            b"<config>prefix"
            b'<metadata key="enable_support" value="1"></metadata>'
            b"suffix</config>"
        )
        result = safety.sanitize_model_settings_support(source, mode="remove")
        self.assertEqual(result.data, b"<config>prefixsuffix</config>")

    def test_multiple_entries_only_rewrite_enabled_values(self):
        source = (
            b"<config>"
            b'<metadata key="enable_support" value="0"/>'
            b'<metadata key="enable_support" value="1"/>'
            b'<metadata key="enable_support" value="1"/>'
            b"</config>"
        )
        result = safety.sanitize_model_settings_support(source)
        self.assertEqual(result.data.count(b'value="0"'), 3)
        self.assertIn("2", result.diagnostics[0].message)

    def test_comment_containing_fake_metadata_is_preserved(self):
        comment = b'<!-- <metadata key="enable_support" value="1"/> -->'
        source = (
            b"<config>"
            + comment
            + b'<metadata key="enable_support" value="1"/>'
            + b"</config>"
        )
        result = safety.sanitize_model_settings_support(source)
        self.assertIn(comment, result.data)
        self.assertEqual(result.data.count(b'value="1"'), 1)
        self.assertEqual(result.data.count(b'value="0"'), 1)

    def test_already_disabled_and_absent_are_noop(self):
        disabled = b'<config><metadata key="enable_support" value="0"/></config>'
        result = safety.sanitize_model_settings_support(disabled)
        self.assertFalse(result.changed)
        self.assertIs(result.data, disabled)
        self.assertEqual(
            diagnostic_codes(result.diagnostics), {"support_already_disabled"}
        )

        absent = b'<config><metadata key="name" value="sample"/></config>'
        result = safety.sanitize_model_settings_support(absent)
        self.assertFalse(result.changed)
        self.assertEqual(
            diagnostic_codes(result.diagnostics), {"support_override_absent"}
        )

    def test_unrecognized_or_missing_support_value_is_not_guessed(self):
        for source in (
            b'<config><metadata key="enable_support" value="true"/></config>',
            b'<config><metadata key="enable_support"/></config>',
        ):
            with self.subTest(source=source):
                result = safety.sanitize_model_settings_support(source)
                self.assertFalse(result.changed)
                self.assertEqual(result.data, source)
                self.assertEqual(
                    diagnostic_codes(result.diagnostics),
                    {"support_override_unrecognized"},
                )

    def test_malformed_xml_is_returned_byte_for_byte(self):
        source = b'<config><metadata key="enable_support" value="1"></config>'
        result = safety.sanitize_model_settings_support(source)
        self.assertFalse(result.changed)
        self.assertEqual(result.data, source)
        self.assertTrue(result.has_errors)
        self.assertEqual(
            diagnostic_codes(result.diagnostics), {"model_settings_invalid_xml"}
        )

    def test_unsupported_utf16_lexical_rewrite_fails_closed(self):
        text = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<config><metadata key="enable_support" value="1"/></config>'
        )
        source = text.encode("utf-16")
        result = safety.sanitize_model_settings_support(source)
        self.assertFalse(result.changed)
        self.assertEqual(result.data, source)
        self.assertEqual(
            diagnostic_codes(result.diagnostics), {"support_rewrite_not_safe"}
        )

    def test_invalid_mode_and_non_bytes_are_rejected(self):
        with self.assertRaises(ValueError):
            safety.sanitize_model_settings_support(b"<config/>", mode="yes")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            safety.sanitize_model_settings_support("<config/>")  # type: ignore[arg-type]

    def test_simple_bytes_wrapper_matches_rich_result(self):
        source = b'<config><metadata key="enable_support" value="1"/></config>'
        self.assertEqual(
            safety.rewrite_model_settings_support_bytes(source),
            safety.sanitize_model_settings_support(source).data,
        )

    def test_payload_can_be_used_in_zip_copy_without_touching_other_entries(self):
        model_settings = (
            b'<config><metadata key="enable_support" value="1"/></config>'
        )
        source_stream = BytesIO()
        custom = ZipInfo("Metadata/unchanged.bin", date_time=(2024, 1, 2, 3, 4, 6))
        custom.compress_type = ZIP_DEFLATED
        custom.comment = b"keep-comment"
        with ZipFile(source_stream, "w") as archive:
            archive.writestr("Metadata/model_settings.config", model_settings)
            archive.writestr(custom, b"unchanged-payload")

        target_stream = BytesIO()
        with ZipFile(BytesIO(source_stream.getvalue()), "r") as source, ZipFile(
            target_stream, "w"
        ) as target:
            for info in source.infolist():
                payload = source.read(info.filename)
                if info.filename == "Metadata/model_settings.config":
                    payload = safety.rewrite_model_settings_support_bytes(payload)
                target.writestr(info, payload)

        with ZipFile(BytesIO(target_stream.getvalue()), "r") as archive:
            self.assertIn(
                b'value="0"', archive.read("Metadata/model_settings.config")
            )
            self.assertEqual(
                archive.read("Metadata/unchanged.bin"), b"unchanged-payload"
            )
            copied = archive.getinfo("Metadata/unchanged.bin")
            self.assertEqual(copied.date_time, custom.date_time)
            self.assertEqual(copied.comment, custom.comment)
            self.assertIsNone(archive.testzip())


class ProjectSettingsDiagnosticsTests(unittest.TestCase):
    @staticmethod
    def diagnose(settings: object, **kwargs: float):
        data = json.dumps(settings, ensure_ascii=False).encode("utf-8")
        return safety.diagnose_project_settings(data, **kwargs)

    @staticmethod
    def grouped_cycle_settings() -> dict[str, object]:
        return {
            "printer_model": "Snapmaker U1",
            "nozzle_diameter": ["0.4", "0.4", "0.4", "0.4"],
            "filament_colour": ["#111111", "#F5F5F5", "#E32636", "#7A4A32"],
            "mixed_filament_definitions": (
                "1,2,1,1,80,0,g,w,m2,z0,xa0,xb0,d0,o0,u1,cm1,2,12122;"
            ),
            "support_filament": "2",
            "support_interface_filament": "2",
            "flush_into_infill": "0",
            "flush_into_support": "0",
            "flush_into_objects": "0",
        }

    def test_grouped_cycle_static_t17_safety_conditions_are_accepted(self):
        settings = self.grouped_cycle_settings()

        diagnostics = self.diagnose(settings)

        self.assertEqual(diagnostics, ())
        self.assertIn(int(settings["support_filament"]), range(1, 5))
        self.assertIn(int(settings["support_interface_filament"]), range(1, 5))
        self.assertTrue(
            all(
                settings[key] == "0"
                for key in (
                    "flush_into_infill",
                    "flush_into_support",
                    "flush_into_objects",
                )
            )
        )
        self.assertNotIn("enable_support", settings)

    def test_grouped_cycle_current_support_and_purge_overrides_are_rejected(self):
        settings = self.grouped_cycle_settings()
        settings["support_filament"] = "0"
        settings.pop("support_interface_filament")
        settings["flush_into_infill"] = "1"
        settings["flush_into_support"] = "1"
        settings.pop("flush_into_objects")

        diagnostics = self.diagnose(settings)
        codes = diagnostic_codes(diagnostics)

        self.assertIn("grouped_cycle_support_filament_invalid", codes)
        self.assertIn("grouped_cycle_support_interface_filament_invalid", codes)
        self.assertIn("grouped_cycle_flush_override_enabled", codes)
        self.assertEqual(
            {
                item.key
                for item in diagnostics
                if item.code == "grouped_cycle_flush_override_enabled"
            },
            {"flush_into_infill", "flush_into_support", "flush_into_objects"},
        )

    def test_grouped_cycle_any_nonzero_physical_support_tool_is_t17_safe(self):
        settings = self.grouped_cycle_settings()
        settings["support_filament"] = "3"
        settings["support_interface_filament"] = "4"

        diagnostics = self.diagnose(settings)

        self.assertEqual(diagnostics, ())

    def test_ratio_only_legacy_project_does_not_require_grouped_cycle_keys(self):
        diagnostics = self.diagnose(
            {
                "filament_colour": [
                    "#111111",
                    "#F5F5F5",
                    "#E32636",
                    "#7A4A32",
                ],
                "mixed_filament_definitions": (
                    "1,2,1,1,80,0,g,w,m2,z0,xa0,xb0,d0,o0,u1;"
                ),
            }
        )

        self.assertEqual(diagnostics, ())

    def test_metadata_only_project_has_no_line_width_warning(self):
        diagnostics = self.diagnose(
            {
                "printer_model": "Snapmaker U1",
                "nozzle_diameter": ["0.4", "0.4", "0.4", "0.4"],
            }
        )
        self.assertEqual(diagnostics, ())

    def test_zero_width_is_orca_auto_not_an_error(self):
        diagnostics = self.diagnose(
            {
                "line_width": "0",
                "outer_wall_line_width": 0,
                "support_line_width": "0%",
            }
        )
        self.assertEqual(diagnostics, ())

    def test_exact_nonpositive_spacing_boundary_is_error(self):
        layer_height = 0.2
        width = safety.NONPOSITIVE_SPACING_FACTOR * layer_height
        diagnostics = self.diagnose(
            {"layer_height": layer_height, "line_width": width}
        )
        self.assertIn("line_width_nonpositive_spacing", diagnostic_codes(diagnostics))
        error = next(
            item for item in diagnostics if item.code == "line_width_nonpositive_spacing"
        )
        self.assertEqual(error.severity, "error")
        self.assertIn("spacing", error.message)

    def test_width_just_above_boundary_is_not_negative_spacing(self):
        layer_height = 0.2
        width = math.nextafter(
            safety.NONPOSITIVE_SPACING_FACTOR * layer_height, math.inf
        )
        diagnostics = self.diagnose(
            {"layer_height": layer_height, "line_width": width},
            minimum_line_width_mm=0,
        )
        self.assertNotIn(
            "line_width_nonpositive_spacing", diagnostic_codes(diagnostics)
        )

    def test_small_but_positive_spacing_gets_separate_warning(self):
        diagnostics = self.diagnose(
            {"layer_height": "0.1", "outer_wall_line_width": "0.04"}
        )
        self.assertIn("line_width_extremely_small", diagnostic_codes(diagnostics))
        self.assertNotIn(
            "line_width_nonpositive_spacing", diagnostic_codes(diagnostics)
        )

    def test_percent_width_is_resolved_for_all_nozzles(self):
        diagnostics = self.diagnose(
            {
                "layer_height": "0.2",
                "nozzle_diameter": ["0.4", "0.2"],
                "top_surface_line_width": "20%",
            }
        )
        # 20% of 0.2 mm is 0.04 mm, below 0.042920... mm.
        self.assertIn("line_width_nonpositive_spacing", diagnostic_codes(diagnostics))

    def test_initial_layer_uses_initial_layer_height(self):
        diagnostics = self.diagnose(
            {
                "layer_height": "0.1",
                "initial_layer_print_height": "0.3",
                "initial_layer_line_width": "0.06",
            },
            minimum_line_width_mm=0,
        )
        self.assertIn("line_width_nonpositive_spacing", diagnostic_codes(diagnostics))

    def test_initial_layer_falls_back_to_normal_layer_height(self):
        diagnostics = self.diagnose(
            {
                "layer_height": "0.3",
                "initial_layer_line_width": "0.06",
            },
            minimum_line_width_mm=0,
        )
        self.assertIn("line_width_nonpositive_spacing", diagnostic_codes(diagnostics))

    def test_missing_height_and_nozzle_produce_actionable_warnings(self):
        diagnostics = self.diagnose(
            {
                "line_width": "0.4",
                "support_line_width": "50%",
            }
        )
        codes = diagnostic_codes(diagnostics)
        self.assertIn("layer_height_unavailable", codes)
        self.assertIn("line_width_percent_unresolved", codes)

    def test_invalid_line_width_shapes_and_values_do_not_crash(self):
        diagnostics = self.diagnose(
            {
                "layer_height": "0.2",
                "line_width": [],
                "outer_wall_line_width": True,
                "inner_wall_line_width": "abc",
                "support_line_width": None,
                "top_surface_line_width": {},
            }
        )
        codes = diagnostic_codes(diagnostics)
        self.assertIn("line_width_invalid_type", codes)
        self.assertIn("line_width_invalid_value", codes)
        self.assertGreaterEqual(
            sum(item.severity == "error" for item in diagnostics), 5
        )

    def test_negative_nonfinite_and_out_of_range_widths_are_errors(self):
        raw = (
            b'{"layer_height":"0.2","line_width":-0.1,'
            b'"outer_wall_line_width":NaN,'
            b'"inner_wall_line_width":"10.1",'
            b'"support_line_width":"1000.1%","nozzle_diameter":["0.4"]}'
        )
        diagnostics = safety.diagnose_project_settings(raw)
        codes = diagnostic_codes(diagnostics)
        self.assertIn("line_width_negative", codes)
        self.assertIn("line_width_invalid_value", codes)
        self.assertIn("line_width_out_of_range", codes)
        self.assertIn("line_width_percent_out_of_range", codes)

    def test_invalid_layer_and_nozzle_values_are_reported_when_needed(self):
        diagnostics = self.diagnose(
            {
                "layer_height": "bad",
                "line_width": "0.2",
                "nozzle_diameter": ["0", "bad"],
                "support_line_width": "50%",
            }
        )
        codes = diagnostic_codes(diagnostics)
        self.assertIn("layer_height_invalid", codes)
        self.assertIn("nozzle_diameter_nonpositive", codes)
        self.assertIn("nozzle_diameter_invalid", codes)
        self.assertIn("line_width_percent_unresolved", codes)

    def test_malformed_utf8_nonobject_and_duplicate_json_are_diagnosed(self):
        cases = (
            (b"\xff", "project_settings_invalid_utf8"),
            (b"{", "project_settings_invalid_json"),
            (b"[]", "project_settings_not_object"),
            (
                b'{"layer_height":"0.2","line_width":"0.4","line_width":"0.45"}',
                "project_settings_duplicate_key",
            ),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertIn(
                    expected,
                    diagnostic_codes(safety.diagnose_project_settings(raw)),
                )

    def test_utf8_bom_is_supported(self):
        raw = b"\xef\xbb\xbf" + json.dumps(
            {"layer_height": "0.2", "line_width": "0.4"}
        ).encode("utf-8")
        self.assertEqual(safety.diagnose_project_settings(raw), ())

    def test_custom_line_width_suffix_is_checked(self):
        diagnostics = self.diagnose(
            {"layer_height": "0.2", "future_feature_line_width": "0.01"}
        )
        error = next(
            item for item in diagnostics if item.code == "line_width_nonpositive_spacing"
        )
        self.assertEqual(error.key, "future_feature_line_width")

    def test_invalid_minimum_and_non_bytes_raise(self):
        with self.assertRaises(ValueError):
            safety.diagnose_project_settings(b"{}", minimum_line_width_mm=-1)
        with self.assertRaises(ValueError):
            safety.diagnose_project_settings(
                b"{}", minimum_line_width_mm=float("nan")
            )
        with self.assertRaises(TypeError):
            safety.diagnose_project_settings({})  # type: ignore[arg-type]

    def test_alias_and_formatter_keep_diagnostic_codes_available(self):
        raw = b'{"layer_height":"0.2","line_width":"0.01"}'
        direct = safety.diagnose_project_settings(raw)
        alias = safety.diagnose_project_settings_bytes(raw)
        self.assertEqual(alias, direct)
        formatted = safety.format_diagnostics(direct)
        self.assertEqual(len(formatted), len(direct))
        self.assertTrue(all(message.startswith("[") for message in formatted))


if __name__ == "__main__":
    unittest.main()
