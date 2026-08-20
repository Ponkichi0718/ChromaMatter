from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile

import numpy as np


FIXED_APP = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXED_APP))

# Match the packaged application's writer installation order.  In particular,
# a calibration test must exercise the real portable-material writer and the
# outer adaptive-shading bypass instead of the unpatched source writer.
import spectrum_mapper_hotfix  # noqa: E402,F401
from final_shading_hotfix import (  # noqa: E402
    _calibration_chart_disables_adaptive,
)

from spectrum_mapper import calibration_chart as calibration  # noqa: E402
from spectrum_mapper import engine  # noqa: E402
from spectrum_mapper import mixer  # noqa: E402
from spectrum_mapper.models import (  # noqa: E402
    FilamentSnapshotRef,
    PaletteSettings,
)


PHYSICAL_HEX = ("#111111", "#F5F5F5", "#E32636", "#7A4A32")
SCREENSHOT_PALETTE_HEX = (
    "#111111", "#F5F5F5", "#E32636", "#7A4A32",
    "#4E5C73", "#481C20", "#2C2620", "#F69AAF",
    "#D0B3AA", "#C23030", "#98A5B9", "#8D2329",
    "#4F382A", "#F05873", "#A97D6B", "#A03C30",
    "#738098", "#691F25", "#3D2F25", "#F57790",
    "#BD978B", "#B23530", "#3C4A5E", "#ACB8C8",
    "#381B1D", "#9F252A", "#24211D", "#583D2C",
    "#F5AEBF", "#ED4B64", "#D9C2BA", "#9E705B",
)
FIXED_TIME = datetime(2026, 8, 11, 6, 30, 0, tzinfo=timezone.utc)


def calibration_writer_for_parent_tests(
    destination,
    prepared,
    colors,
    height_mm,
    palette,
    part_palettes=None,
    print_uses_global_palette=False,
):
    """Exercise the portable writer without installing global outer wrappers.

    The packaged wrapper chain is covered in an isolated subprocess below.
    Keeping it out of this discovery process prevents its process-wide monkey
    patches from changing the writer identity expected by older regression
    modules that run later in the same interpreter.
    """

    validation = spectrum_mapper_hotfix._write_3mf_atomic_fixed(
        destination,
        prepared,
        colors,
        height_mm,
        palette,
        part_palettes,
        print_uses_global_palette,
    )
    validation["r8_export_adaptive"] = {
        "status": "disabled_calibration",
        "automatic_tree_faces": 0,
        "merged_tree_faces": 0,
        "adaptive_faces": 0,
        "manual_protected_faces": 0,
    }
    return validation


def make_palette(
    state_count: int,
    *,
    display_override: bool = False,
    filament_refs: bool = False,
    physical_hex: tuple[str, str, str, str] = PHYSICAL_HEX,
    black_output_preset: bool = False,
    surface_shell: bool = False,
) -> PaletteSettings:
    physical_values = tuple(physical_hex)
    refs = [None] * 4
    if filament_refs:
        refs = [
            FilamentSnapshotRef(
                product_id=f"fixture-spool-{index + 1}",
                brand="Fixture",
                series="PLA",
                color_name=f"F{index + 1}",
                matched_hex=color,
                finish_class="matte",
                source="test",
            )
            for index, color in enumerate(physical_values)
        ]
    overrides: list[str | None] = [None] * 6
    if display_override:
        overrides[0] = "#123456"
    output_ratios = (
        mixer.black_output_ratio_preset(
            0,
            [33] * 6,
            [67] * 6,
        )
        if black_output_preset
        else None
    )
    return PaletteSettings(
        palette_state_count=state_count,
        physical_hex=list(physical_values),
        enabled_states=[index % 3 != 1 for index in range(32)],
        mix_hex_overrides=overrides,
        mix_ratios_b=[33] * 6,
        secondary_mix_ratios_b=[67] * 6,
        output_mix_ratios_b=output_ratios,
        surface_shell_enabled=surface_shell,
        physical_filament_refs=refs,
    )


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


class CalibrationRecipeTests(unittest.TestCase):
    def test_current_32_state_palette_matches_the_reported_screenshot(self) -> None:
        rows = calibration.palette_calibration_rows(
            PaletteSettings(
                palette_state_count=32,
                physical_hex=list(PHYSICAL_HEX),
                enabled_states=[True] * 32,
                mix_ratios_b=[33] * 6,
                secondary_mix_ratios_b=[67] * 6,
            )
        )
        self.assertEqual(len(rows), 32)
        self.assertEqual(
            tuple(str(row["ui_display_hex"]) for row in rows),
            SCREENSHOT_PALETTE_HEX,
        )
        state_18 = rows[17]
        self.assertEqual(state_18["name"], "F1+F3 B50%")
        self.assertEqual(state_18["filament_a"], "F1")
        self.assertEqual(state_18["filament_b"], "F3")
        self.assertEqual(state_18["requested_b_percent"], 50.0)
        self.assertEqual(state_18["effective_b_percent"], 50.0)
        self.assertEqual(state_18["cadence"], "A1:B1")
        self.assertEqual(state_18["ui_display_hex"], "#691F25")

    def test_f1_black_preset_separates_display_target_from_output_cadence(self) -> None:
        rows = calibration.palette_calibration_rows(
            make_palette(32, black_output_preset=True)
        )
        expected = {
            5: (33.0, 80.0, "A1:B4", 80.0),
            6: (33.0, 80.0, "A1:B4", 80.0),
            7: (33.0, 80.0, "A1:B4", 80.0),
            11: (67.0, 90.0, "A1:B9", 90.0),
            12: (67.0, 90.0, "A1:B9", 90.0),
            13: (67.0, 90.0, "A1:B9", 90.0),
            17: (50.0, 86.0, "A1:B6", 85.714),
            18: (50.0, 86.0, "A1:B6", 85.714),
            19: (50.0, 86.0, "A1:B6", 85.714),
            23: (25.0, 75.0, "A1:B3", 75.0),
            24: (75.0, 95.0, "A1:B19", 95.0),
            25: (25.0, 75.0, "A1:B3", 75.0),
            26: (75.0, 95.0, "A1:B19", 95.0),
            27: (25.0, 75.0, "A1:B3", 75.0),
            28: (75.0, 95.0, "A1:B19", 95.0),
        }
        for state, (display_b, output_b, cadence, effective_b) in expected.items():
            with self.subTest(state=state):
                row = rows[state - 1]
                self.assertEqual(row["filament_a"], "F1")
                self.assertEqual(row["display_target_b_percent"], display_b)
                self.assertEqual(row["requested_output_b_percent"], output_b)
                self.assertEqual(row["orca_cadence"], cadence)
                self.assertEqual(row["effective_orca_b_percent"], effective_b)
                self.assertEqual(row["ui_display_hex"], row["display_target_hex"])
        self.assertEqual(rows[0]["requested_output_b_percent"], 0.0)
        self.assertFalse(rows[0]["output_ratio_override_active"])
        self.assertEqual(rows[0]["orca_cadence"], "single")
        self.assertEqual(rows[7]["filament_a"], "F2")
        self.assertEqual(rows[7]["display_target_b_percent"], 33.0)
        self.assertEqual(rows[7]["requested_output_b_percent"], 33.0)
        self.assertFalse(rows[7]["output_ratio_override_active"])

        # Sidecar colour predictions explicitly use Orca's integer cadence,
        # even when this module runs without the packaged mixer hotfix.
        raw_mix = spectrum_mapper_hotfix._original_mix_rgb8
        expected_s5 = mixer.rgb8_to_hex(
            raw_mix(
                mixer.hex_to_rgb8(PHYSICAL_HEX[0]),
                mixer.hex_to_rgb8(PHYSICAL_HEX[1]),
                mixer.orca_effective_mix_ratio(0.80),
            )
        )
        self.assertEqual(rows[4]["output_ratio_predicted_hex"], expected_s5)

    def test_rows_follow_selected_16_24_or_32_state_boundary(self) -> None:
        for state_count in (16, 24, 32):
            with self.subTest(state_count=state_count):
                palette = make_palette(state_count, display_override=True)
                before = asdict(palette)
                rows = calibration.palette_calibration_rows(palette)
                self.assertEqual(len(rows), state_count)
                self.assertEqual(
                    [int(row["state"]) for row in rows],
                    list(range(1, state_count + 1)),
                )
                # Disabled assignment states remain printable calibration
                # coupons, and display-only overrides are identified separately.
                self.assertFalse(bool(rows[1]["enabled_for_assignment"]))
                self.assertEqual(rows[4]["ui_display_hex"], "#123456")
                self.assertNotEqual(
                    rows[4]["ui_display_hex"],
                    rows[4]["print_ratio_predicted_hex"],
                )
                self.assertEqual(asdict(palette), before)

    def test_public_order_is_family_major_without_renumbering_states(self) -> None:
        palette = make_palette(32)
        before = asdict(palette)
        canonical = calibration.palette_calibration_rows(palette)
        displayed = calibration.palette_family_display_rows(palette)

        expected_state_ids = [
            23, 5, 17, 11, 24,       # F1+F2, 25 -> 75% B
            25, 6, 18, 12, 26,       # F1+F3
            27, 7, 19, 13, 28,       # F1+F4
            29, 8, 20, 14, 30,       # F2+F3
            31, 9, 21, 15, 32,       # F2+F4
            10, 22, 16,               # F3+F4
            1, 2, 3, 4,               # physical labels, unnumbered
        ]
        self.assertEqual(
            [int(row["state"]) for row in displayed], expected_state_ids
        )
        self.assertEqual(
            [row["chart_number"] for row in displayed],
            list(range(1, 29)) + [None] * 4,
        )
        self.assertEqual(
            [str(row["display_label"]) for row in displayed[-4:]],
            ["F1", "F2", "F3", "F4"],
        )
        self.assertEqual(
            [int(row["state"]) for row in canonical], list(range(1, 33))
        )
        self.assertEqual(
            [
                (
                    int(row["state"]),
                    str(row["filament_a"]),
                    str(row["filament_b"]),
                    float(row["requested_output_b_percent"]),
                )
                for row in canonical
            ],
            [
                (
                    int(row["state"]),
                    str(row["filament_a"]),
                    str(row["filament_b"]),
                    float(row["requested_output_b_percent"]),
                )
                for row in calibration.palette_calibration_rows(palette)
            ],
        )
        self.assertEqual(asdict(palette), before)

        self.assertEqual(
            mixer.palette_family_display_state_indices(
                32,
                palette.mix_ratios_b,
                palette.secondary_mix_ratios_b,
            ),
            tuple(state - 1 for state in expected_state_ids),
        )
        self.assertEqual(
            calibration._palette_family_grid_positions(displayed),
            (
                [(0, column) for column in range(5)]
                + [(1, column) for column in range(5)]
                + [(2, column) for column in range(5)]
                + [(3, column) for column in range(5)]
                + [(4, column) for column in range(5)]
                + [(5, column) for column in range(3)]
                + [(6, column) for column in range(4)]
            ),
        )


class CalibrationGeometryTests(unittest.TestCase):
    def test_each_supported_chart_is_a_uniform_watertight_part_grid(self) -> None:
        for state_count in (16, 24, 32):
            with self.subTest(state_count=state_count):
                chart = calibration.build_calibration_chart_mesh(
                    make_palette(state_count)
                )
                self.assertEqual(chart.row_count, 7)
                self.assertEqual(len(chart.part_names), state_count + 1)
                self.assertEqual(len(chart.vertices_mm), 10 + 8 * state_count)
                self.assertEqual(len(chart.faces), 16 + 12 * state_count)
                self.assertEqual(
                    chart.part_face_counts,
                    (16,) + (12,) * state_count,
                )
                expected_display_states = [
                    int(row["state"]) - 1
                    for row in calibration.palette_family_display_rows(
                        make_palette(state_count)
                    )
                ]
                self.assertEqual(
                    chart.part_state_indices,
                    (calibration.BASE_STATE, *expected_display_states),
                )
                display_rows = calibration.palette_family_display_rows(
                    make_palette(state_count)
                )
                grid_positions = calibration._palette_family_grid_positions(
                    display_rows
                )
                for display_index, (grid_row, grid_column) in enumerate(
                    grid_positions, start=1
                ):
                    selected = np.flatnonzero(
                        chart.face_part_ids == display_index
                    )
                    used_vertices = np.unique(chart.faces[selected])
                    center = chart.vertices_mm[used_vertices, :2].mean(axis=0)
                    np.testing.assert_allclose(
                        center,
                        (-24.0 + 12.0 * grid_column, 34.0 - 12.0 * grid_row),
                        rtol=0.0,
                        atol=1.0e-12,
                    )
                np.testing.assert_allclose(
                    np.ptp(chart.vertices_mm, axis=0),
                    (62.0, 90.0, 6.44),
                    rtol=0.0,
                    atol=1.0e-12,
                )
                for part_id in range(state_count + 1):
                    selected = np.flatnonzero(chart.face_part_ids == part_id)
                    source_faces = chart.faces[selected]
                    used_vertices = np.unique(source_faces)
                    local_faces = np.searchsorted(used_vertices, source_faces)
                    quality = engine.mesh_quality(
                        chart.vertices_mm[used_vertices],
                        local_faces,
                        check_self_intersections=False,
                    )
                    self.assertTrue(quality["watertight"], part_id)
                    self.assertTrue(quality["winding_consistent"], part_id)
                    self.assertTrue(quality["positive_volume"], part_id)
                    self.assertEqual(quality["body_count"], 1, part_id)
                    self.assertEqual(quality["degenerate_faces"], 0, part_id)
                    expected_state = chart.part_state_indices[part_id]
                    self.assertEqual(
                        set(int(value) for value in chart.palette_indices[selected]),
                        {expected_state},
                    )

    def test_adaptive_bypass_requires_the_complete_purpose_built_identity(self) -> None:
        palette = make_palette(16)
        chart = calibration.build_calibration_chart_mesh(palette)
        prepared, colors = calibration._prepared_chart(chart, palette)
        self.assertTrue(_calibration_chart_disables_adaptive(prepared))
        self.assertEqual(colors.manual_override_faces, 0)
        self.assertFalse(hasattr(colors, "_r8_manual_override_mask"))
        self.assertFalse(hasattr(prepared, "_r8_export_adaptive_config"))

        incomplete = SimpleNamespace(
            assembly={"calibration_chart": {"adaptive_paint": False}},
            topology={"purpose_built_calibration": True},
        )
        self.assertFalse(_calibration_chart_disables_adaptive(incomplete))
        wrong_topology = SimpleNamespace(
            assembly={
                "calibration_chart": {
                    "schema": calibration.CALIBRATION_SCHEMA,
                    "adaptive_paint": False,
                    "all_swatch_faces_uniform": True,
                }
            },
            topology={"purpose_built_calibration": False},
        )
        self.assertFalse(_calibration_chart_disables_adaptive(wrong_topology))


class CalibrationBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.writer_patch = mock.patch.object(
            calibration.engine,
            "write_3mf_atomic",
            side_effect=calibration_writer_for_parent_tests,
        )
        cls.writer_patch.start()
        cls.temporary = tempfile.TemporaryDirectory()
        cls.parent = Path(cls.temporary.name)
        cls.results = {}
        for state_count in (16, 24, 32):
            physical_hex = (
                ("#102030", "#336699", "#C04030", "#806040")
                if state_count == 16
                else PHYSICAL_HEX
            )
            cls.results[state_count] = calibration.generate_palette_calibration_bundle(
                cls.parent,
                make_palette(
                    state_count,
                    display_override=True,
                    filament_refs=True,
                    physical_hex=physical_hex,
                    black_output_preset=True,
                ),
                language="ja",
                target_label="テスト配色",
                created_at=FIXED_TIME,
            )
        cls.legacy_result = calibration.generate_palette_calibration_bundle(
            cls.parent,
            make_palette(16, filament_refs=True),
            language="en",
            target_label="legacy output recipe",
            created_at=FIXED_TIME,
        )
        cls.shell_results = {
            state_count: calibration.generate_palette_calibration_bundle(
                cls.parent,
                make_palette(
                    state_count,
                    black_output_preset=True,
                    surface_shell=True,
                ),
                language="ja",
                target_label=f"2-wall shell {state_count}",
                created_at=FIXED_TIME,
            )
            for state_count in (16, 24, 32)
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()
        cls.writer_patch.stop()

    def test_real_writer_generates_all_supported_uniform_leaf_charts(self) -> None:
        for state_count, result in self.results.items():
            with self.subTest(state_count=state_count):
                report = result.validation
                self.assertTrue(report["valid"])
                self.assertEqual(report["object_count"], state_count + 1)
                self.assertEqual(
                    report["dimensions_mm"],
                    [62.0, 90.0, 6.44],
                )
                self.assertTrue(report["all_objects_uniform"])
                self.assertTrue(report["part_face_counts_exact"])
                self.assertTrue(report["paint_colors_are_leaf_codes"])
                self.assertEqual(report["unknown_or_adaptive_paint_codes"], [])
                self.assertTrue(report["portable_p1_matches_paint_color"])
                self.assertTrue(report["portable_pid_matches_basematerials"])
                self.assertTrue(report["physical_filament_refs_exact"])
                self.assertTrue(report["enabled_states_exact"])
                self.assertTrue(report["mixed_definitions_exact"])
                self.assertEqual(
                    len(report["output_mix_ratios_b_percent"]),
                    28,
                )
                self.assertEqual(
                    len(report["print_mix_specs"]),
                    state_count - 4,
                )
                self.assertTrue(report["calibration_metadata_exact"])
                self.assertTrue(report["adaptive_bypass_exact"])
                adaptive = report["writer_validation"]["r8_export_adaptive"]
                self.assertEqual(adaptive["status"], "disabled_calibration")
                self.assertEqual(adaptive["automatic_tree_faces"], 0)
                self.assertEqual(adaptive["manual_protected_faces"], 0)

                with zipfile.ZipFile(result.model_path) as archive:
                    root = ET.fromstring(
                        archive.read("3D/Objects/object_1.model")
                    )
                objects = [
                    item for item in root.iter() if local_name(item.tag) == "object"
                ]
                chart = calibration.build_calibration_chart_mesh(
                    make_palette(
                        state_count,
                        display_override=True,
                        filament_refs=True,
                        physical_hex=(
                            ("#102030", "#336699", "#C04030", "#806040")
                            if state_count == 16
                            else PHYSICAL_HEX
                        ),
                        black_output_preset=True,
                    )
                )
                for object_index, obj in enumerate(objects):
                    expected_state = chart.part_state_indices[object_index]
                    expected_code = engine.PAINT_CODES[expected_state]
                    codes = [
                        item.attrib.get("paint_color")
                        for item in obj.iter()
                        if local_name(item.tag) == "triangle"
                    ]
                    self.assertTrue(codes)
                    self.assertEqual(set(codes), {expected_code})

    def test_legacy_bundle_omits_output_only_metadata(self) -> None:
        report = self.legacy_result.validation
        self.assertTrue(report["valid"])
        self.assertIsNone(report["output_mix_ratios_b_percent"])
        self.assertIsNone(report["print_mix_specs"])
        snapshot = json.loads(
            self.legacy_result.snapshot_path.read_text(encoding="utf-8")
        )
        self.assertIsNone(snapshot["palette"]["output_mix_ratios_b"])
        self.assertTrue(
            all(
                not bool(row["output_ratio_override_active"])
                for row in snapshot["states"]
            )
        )
        guide = self.legacy_result.guide_path.read_text(encoding="utf-8")
        self.assertNotIn("output-only ratio profile is active", guide)

    def test_surface_shell_requests_migrate_to_safe_ratio_bundles(self) -> None:
        for state_count, result in self.shell_results.items():
            with self.subTest(state_count=state_count):
                report = result.validation
                self.assertTrue(report["valid"])
                self.assertFalse(report["surface_shell_enabled"])
                self.assertTrue(report["surface_shell_exact"])
                self.assertEqual(report["surface_shell_applied_rows"], 0)
                self.assertEqual(report["surface_shell_passthrough_rows"], 0)
                self.assertEqual(report["surface_shell_fallback_rows"], 0)
                writer_report = report["writer_validation"]
                self.assertEqual(
                    writer_report["mixed_definition_cycle_rows"], 0
                )
                self.assertFalse(
                    writer_report["unsafe_grouped_cycle_detected"]
                )
                with zipfile.ZipFile(result.model_path) as archive:
                    project = json.loads(
                        archive.read("Metadata/project_settings.config")
                    )
                    metadata = json.loads(
                        archive.read("Metadata/full_spectrum_palette.json")
                    )
                for key in (
                    "wall_loops",
                    "wall_generator",
                    "outer_wall_line_width",
                    "inner_wall_line_width",
                    "support_filament",
                    "support_interface_filament",
                    "flush_into_infill",
                    "flush_into_support",
                    "flush_into_objects",
                ):
                    self.assertNotIn(key, project)
                active = project["mixed_filament_definitions"].split(";")[
                    : state_count - 4
                ]
                self.assertTrue(all(",m2," in row for row in active))
                self.assertEqual(sum(",cm1," in row for row in active), 0)
                self.assertNotIn("surface_shell", metadata)
                with result.mapping_path.open(
                    "r", encoding="utf-8-sig", newline=""
                ) as stream:
                    mapping = list(csv.DictReader(stream))
                self.assertEqual(mapping[4]["surface_shell_enabled"], "False")
                self.assertEqual(mapping[4]["surface_shell_applied"], "False")
                self.assertFalse(mapping[4]["surface_shell_manual_pattern"])
                snapshot = json.loads(
                    result.snapshot_path.read_text(encoding="utf-8")
                )
                self.assertFalse(
                    snapshot["palette"]["surface_shell_enabled"]
                )
                guide = result.guide_path.read_text(encoding="utf-8")
                self.assertNotIn("Cycle適用", guide)
                self.assertIn("出力専用比率profileが有効", guide)

    def test_packaged_writer_chain_disables_adaptive_in_an_isolated_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw_parent:
            output_json = Path(raw_parent) / "result.json"
            script = r'''
import json
from pathlib import Path
import sys

fixed_app = Path(sys.argv[1]).resolve()
parent = Path(sys.argv[2]).resolve()
output_json = Path(sys.argv[3]).resolve()
sys.path.insert(0, str(fixed_app))

import spectrum_mapper_hotfix
from surface_resolution_hotfix import apply_surface_resolution_hotfix
from final_shading_hotfix import install_export_adaptive_hotfix

apply_surface_resolution_hotfix()
install_export_adaptive_hotfix()

from spectrum_mapper.calibration_chart import generate_palette_calibration_bundle
from spectrum_mapper.models import PaletteSettings

result = generate_palette_calibration_bundle(
    parent,
    PaletteSettings(
        palette_state_count=16,
        physical_hex=["#111111", "#F5F5F5", "#E32636", "#7A4A32"],
        enabled_states=[True] * 32,
        mix_ratios_b=[33] * 6,
        secondary_mix_ratios_b=[67] * 6,
    ),
    language="ja",
    target_label="subprocess",
)
output_json.write_text(
    json.dumps(
        {
            "valid": bool(result.validation["valid"]),
            "status": result.validation["writer_validation"]
                ["r8_export_adaptive"]["status"],
            "adaptive": int(result.validation["writer_validation"]
                ["r8_export_adaptive"]["adaptive_faces"]),
            "unknown": result.validation["unknown_or_adaptive_paint_codes"],
        }
    ),
    encoding="utf-8",
)
'''
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(FIXED_APP),
                    raw_parent,
                    str(output_json),
                ],
                cwd=FIXED_APP,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + "\n" + completed.stderr,
            )
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["status"], "disabled_calibration")
            self.assertEqual(payload["adaptive"], 0)
            self.assertEqual(payload["unknown"], [])

    def test_f2_backing_uses_the_selected_color_and_is_not_described_as_white(self) -> None:
        result = self.results[16]
        snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["palette"]["physical_hex"][1], "#336699")
        guide = result.guide_path.read_text(encoding="utf-8")
        self.assertIn("F2台座", guide)
        self.assertNotIn("F2白台座", guide)

        with zipfile.ZipFile(result.model_path) as archive:
            root = ET.fromstring(archive.read("3D/Objects/object_1.model"))
        materials = next(
            item for item in root.iter() if local_name(item.tag) == "basematerials"
        )
        material_rows = [
            item for item in materials if local_name(item.tag) == "base"
        ]
        self.assertEqual(material_rows[1].attrib["displaycolor"][:7], "#336699")

    def test_mapping_snapshot_and_manifest_preserve_the_clicked_palette(self) -> None:
        result = self.results[32]
        with result.mapping_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 32)
        state_5 = next(row for row in rows if row["state"] == "5")
        self.assertEqual(state_5["chart_number"], "2")
        self.assertEqual(state_5["display_label"], "02")
        self.assertEqual(state_5["f_pair"], "F1+F2")
        self.assertEqual(state_5["fixed_ratio"], "67/33%")
        self.assertEqual(state_5["ui_display_hex"], "#123456")
        self.assertNotEqual(
            state_5["ui_display_hex"], state_5["print_ratio_predicted_hex"]
        )
        self.assertIn("display_target_b_percent", state_5)
        self.assertIn("requested_output_b_percent", state_5)
        self.assertIn("effective_orca_b_percent", state_5)
        self.assertIn("orca_cadence", state_5)
        self.assertEqual(state_5["display_target_b_percent"], "33.0")
        self.assertEqual(state_5["requested_output_b_percent"], "80.0")
        self.assertEqual(state_5["orca_cadence"], "A1:B4")
        self.assertEqual(state_5["output_ratio_override_active"], "True")
        self.assertIn("measured_slope_L", rows[0])
        self.assertIn("side_appearance_notes", rows[0])

        snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["target_label"], "テスト配色")
        self.assertEqual(snapshot["chart"]["state_count"], 32)
        self.assertEqual(
            snapshot["palette"]["physical_filament_refs"][0]["product_id"],
            "fixture-spool-1",
        )
        self.assertEqual(len(snapshot["palette"]["output_mix_ratios_b"]), 28)
        self.assertEqual(
            snapshot["states"][4]["requested_output_b_percent"],
            80.0,
        )
        self.assertEqual(
            [row["state"] for row in snapshot["states"]],
            list(range(1, 33)),
        )
        self.assertEqual(
            [row["chart_number"] for row in snapshot["chart_rows"]],
            list(range(1, 29)) + [None] * 4,
        )
        expected_chart_states = [
            int(row["state"]) for row in snapshot["chart_rows"]
        ]
        self.assertEqual(
            snapshot["chart"]["object_state_ids"], expected_chart_states
        )
        self.assertEqual(
            result.validation["calibration_metadata"][
                "chart_object_state_ids"
            ],
            expected_chart_states,
        )
        self.assertTrue(result.validation["chart_object_order_exact"])
        guide = result.guide_path.read_text(encoding="utf-8")
        self.assertIn("出力専用比率profile", guide)
        self.assertIn("表示番号 / Fペア / 固定比率", guide)
        self.assertIn("内部state ID", guide)
        self.assertIn("実測LUTとして自動読込み・自動適用はされません", guide)
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["state_count"], 32)
        self.assertEqual(
            [row["state"] for row in manifest["presentation_order"]],
            expected_chart_states,
        )
        self.assertEqual(
            [row["chart_number"] for row in manifest["presentation_order"]],
            list(range(1, 29)) + [None] * 4,
        )
        self.assertEqual(len(manifest["files"]), 6)
        for item in manifest["files"]:
            artifact = result.folder / item["name"]
            self.assertEqual(item["bytes"], artifact.stat().st_size)
            self.assertEqual(item["sha256"], sha256(artifact))

    def test_bundle_folders_are_unique_without_overwriting_an_existing_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw_parent:
            parent = Path(raw_parent)
            first = calibration.generate_palette_calibration_bundle(
                parent,
                make_palette(16),
                language="en",
                created_at=FIXED_TIME,
            )
            original_manifest = first.manifest_path.read_bytes()
            second = calibration.generate_palette_calibration_bundle(
                parent,
                make_palette(16),
                language="en",
                created_at=FIXED_TIME,
            )
            self.assertNotEqual(first.folder, second.folder)
            self.assertEqual(second.folder.name, first.folder.name + "-2")
            self.assertEqual(first.manifest_path.read_bytes(), original_manifest)

    def test_failure_before_publish_removes_staging_and_leaves_parent_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw_parent:
            parent = Path(raw_parent)
            with mock.patch.object(
                calibration,
                "_write_legend",
                side_effect=RuntimeError("injected legend failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected legend failure"):
                    calibration.generate_palette_calibration_bundle(
                        parent,
                        make_palette(16),
                        created_at=FIXED_TIME,
                    )
            self.assertEqual(list(parent.iterdir()), [])

    def test_direct_bundle_creation_refuses_a_nonempty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_output:
            output = Path(raw_output)
            marker = output / "owned-by-user.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                calibration.create_palette_calibration_bundle(
                    output,
                    make_palette(16),
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main(verbosity=2)
