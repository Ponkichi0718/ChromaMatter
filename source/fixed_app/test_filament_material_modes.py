from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

import numpy as np
from PIL import Image

import spectrum_mapper_hotfix  # noqa: F401  installs the packaged writer chain
from spectrum_mapper import calibration_chart, engine, workflow
from spectrum_mapper.filament_database import (
    FilamentMatcher,
    FilamentProduct,
    FilamentRepository,
)
from spectrum_mapper.filament_materials import generic_filament_profile
from spectrum_mapper.gui import (
    MATERIAL_GAMUT_WARNING_MEAN_DELTA_E76,
    MapperApp,
    _mix_optimizer_settings_key,
)
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import (
    AppSettings,
    FilamentSnapshotRef,
    PaletteSettings,
)
from spectrum_mapper.owned_filaments import (
    OwnedFilamentSelectionError,
    recommend_from_owned_filaments,
)

from test_part_exports import (
    COOL_FILAMENTS,
    PART_KEYS,
    WARM_FILAMENTS,
    _two_watertight_tetrahedra,
)


def _product(product_id: str, color: str, material: str) -> FilamentProduct:
    return FilamentProduct(
        product_id=product_id,
        brand="Fixture",
        series=f"{material} Standard",
        color_name=product_id,
        matched_hex=color,
        finish_class="Standard / Opaque",
        source_kind="catalog",
        source_url="https://example.invalid/fixture",
        record_id=product_id,
        measurement_id=None,
        material=material,
        alias_product_ids=(product_id,),
    )


def _cross_material_settings() -> AppSettings:
    settings = AppSettings(
        palette=PaletteSettings(material="PLA", physical_hex=list(WARM_FILAMENTS)),
        part_palettes={
            PART_KEYS[1]: PaletteSettings(
                material="ABS", physical_hex=list(COOL_FILAMENTS)
            )
        },
    )
    settings.geometry.height_mm = 20.0
    settings.geometry.export_individual_parts = True
    settings.tone.smoothing = False
    return settings


def _project_filament_profiles(path: Path) -> list[str]:
    with ZipFile(path) as archive:
        project = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
    return list(project["filament_settings_id"])


class MaterialSchemaTests(unittest.TestCase):
    def test_repository_and_matcher_never_cross_selected_material(self) -> None:
        repository = FilamentRepository()
        matcher = FilamentMatcher()
        for material in ("PLA", "ABS", "PETG"):
            with self.subTest(material=material):
                products = repository.list_products(material=material)
                self.assertGreaterEqual(len({item.matched_hex for item in products}), 4)
                self.assertTrue(all(item.material == material for item in products))
                matches = matcher.find_matches("#808080", limit=12, material=material)
                self.assertEqual(len(matches), 12)
                self.assertTrue(all(item.material == material for item in matches))

    def test_old_projects_and_product_snapshots_migrate_to_pla(self) -> None:
        restored = AppSettings.from_dict(
            {
                "palette": {"physical_hex": list(WARM_FILAMENTS)},
                "part_palettes": {
                    "coat": {"physical_hex": list(COOL_FILAMENTS)}
                },
            }
        )
        self.assertEqual(restored.palette.material, "PLA")
        self.assertEqual(restored.part_palettes["coat"].material, "PLA")
        ref = FilamentSnapshotRef.from_mapping(
            {
                "product_id": "legacy",
                "brand": "Legacy",
                "series": "PLA",
                "color_name": "Black",
                "matched_hex": WARM_FILAMENTS[0],
                "finish_class": "standard",
                "source": "catalog",
            }
        )
        self.assertIsNotNone(ref)
        self.assertEqual(ref.material, "PLA")

    def test_material_and_product_identity_round_trip_without_cross_fallback(self) -> None:
        ref = FilamentSnapshotRef(
            product_id="abs:black",
            brand="Fixture",
            series="ABS",
            color_name="Black",
            matched_hex=COOL_FILAMENTS[0],
            finish_class="standard",
            source="catalog",
            material="ABS",
        )
        settings = AppSettings(
            palette=PaletteSettings(
                material="ABS",
                physical_hex=list(COOL_FILAMENTS),
                physical_filament_refs=[ref, None, None, None],
            ),
            part_palettes={
                "petg": PaletteSettings(
                    material="PETG", physical_hex=list(WARM_FILAMENTS)
                )
            },
        )
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertEqual(restored.palette.material, "ABS")
        self.assertEqual(restored.palette.physical_filament_refs[0].material, "ABS")
        self.assertEqual(restored.part_palettes["petg"].material, "PETG")

        # A legacy PLA product identity must not survive assignment to an ABS
        # palette even if its saved HEX happens to match exactly.
        pla_ref = FilamentSnapshotRef(
            product_id="pla:black",
            brand="Fixture",
            series="PLA",
            color_name="Black",
            matched_hex=COOL_FILAMENTS[0],
            finish_class="standard",
            source="catalog",
            material="PLA",
        )
        abs_palette = PaletteSettings(
            material="ABS",
            physical_hex=list(COOL_FILAMENTS),
            physical_filament_refs=[pla_ref, None, None, None],
        )
        self.assertIsNone(abs_palette.physical_filament_refs[0])

    def test_optimizer_stale_key_includes_global_and_part_material(self) -> None:
        pla = AppSettings(palette=PaletteSettings(material="PLA"))
        abs_settings = AppSettings(palette=PaletteSettings(material="ABS"))
        self.assertNotEqual(
            _mix_optimizer_settings_key(pla),
            _mix_optimizer_settings_key(abs_settings),
        )
        local_pla = AppSettings(part_palettes={"coat": PaletteSettings(material="PLA")})
        local_petg = AppSettings(part_palettes={"coat": PaletteSettings(material="PETG")})
        self.assertNotEqual(
            _mix_optimizer_settings_key(local_pla),
            _mix_optimizer_settings_key(local_petg),
        )


class MaterialSafetyTests(unittest.TestCase):
    def test_busy_app_disables_and_rejects_material_mode_switch(self) -> None:
        app = MapperApp.__new__(MapperApp)
        app.busy = True
        app.root = object()
        app.i18n = Translator("en")
        app.settings = AppSettings()
        app.active_part_key = None
        buttons = {material: Mock() for material in ("PLA", "ABS", "PETG")}
        app.material_buttons = buttons

        app._refresh_material_mode_buttons("PLA")
        for button in buttons.values():
            self.assertEqual(button.configure.call_args.kwargs["state"], "disabled")
        with patch("spectrum_mapper.gui.messagebox.showinfo") as shown:
            app._change_material_mode("ABS")
        shown.assert_called_once()
        self.assertEqual(app.settings.palette.material, "PLA")

    def test_owned_configuration_rejects_one_cross_material_product(self) -> None:
        products = (
            _product("abs-black", "#101010", "ABS"),
            _product("abs-white", "#F0F0F0", "ABS"),
            _product("abs-red", "#D02020", "ABS"),
            _product("pla-blue", "#2040D0", "PLA"),
        )
        with self.assertRaisesRegex(OwnedFilamentSelectionError, "異素材"):
            recommend_from_owned_filaments(
                np.asarray(((20, 20, 20), (230, 230, 230)), dtype=np.uint8),
                owned_products=products,
                material="ABS",
                max_passes=1,
            )

    def test_owned_abs_candidates_retain_abs_identity(self) -> None:
        products = (
            _product("abs-black", "#101010", "ABS"),
            _product("abs-white", "#F0F0F0", "ABS"),
            _product("abs-red", "#D02020", "ABS"),
            _product("abs-blue", "#2040D0", "ABS"),
        )
        result = recommend_from_owned_filaments(
            np.asarray(
                ((20, 20, 20), (230, 230, 230), (200, 30, 30), (30, 50, 190)),
                dtype=np.uint8,
            ),
            owned_products=products,
            material="ABS",
            max_passes=1,
        )
        self.assertTrue(
            all(candidate.material == "ABS" for candidate in result.selection.candidates)
        )
        self.assertTrue(all(product.material == "ABS" for product in result.candidates))

    def test_direct_combined_writer_rejects_different_part_materials(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _cross_material_settings()
        colors = engine.recolor_level_parts(
            prepared.final,
            settings.geometry.height_mm,
            settings.tone,
            settings.palette,
            settings.part_palettes,
        )
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "unsafe.3mf"
            with self.assertRaisesRegex(engine.EngineError, "independent part"):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.geometry.height_mm,
                    settings.palette,
                    settings.part_palettes,
                    False,
                )
            with self.assertRaisesRegex(engine.EngineError, "independent part"):
                engine.write_3mf_atomic(
                    destination,
                    prepared,
                    colors,
                    settings.geometry.height_mm,
                    settings.palette,
                    settings.part_palettes,
                    True,
                )
            self.assertFalse(destination.exists())

    def test_cross_material_bundle_requires_explicit_individual_only(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _cross_material_settings()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "assembly.3mf"
            with self.assertRaisesRegex(ValueError, "混在"):
                workflow.export_bundle(
                    prepared,
                    settings,
                    destination,
                    include_vertex_obj=False,
                )
            with self.assertRaisesRegex(ValueError, "強制統合"):
                workflow.export_bundle(
                    prepared,
                    settings,
                    destination,
                    include_vertex_obj=False,
                    force_common_palette=True,
                )
            self.assertFalse(destination.exists())

    def test_individual_only_refuses_a_stale_combined_destination(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _cross_material_settings()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "assembly.3mf"
            stale = b"old combined project must remain untouched"
            destination.write_bytes(stale)
            with self.assertRaisesRegex(ValueError, "既存の統合3MF"):
                workflow.export_bundle(
                    prepared,
                    settings,
                    destination,
                    include_vertex_obj=False,
                    individual_only=True,
                )
            self.assertEqual(destination.read_bytes(), stale)
            self.assertFalse((Path(folder) / "assembly_parts").exists())
            self.assertFalse((Path(folder) / "assembly_validation.json").exists())

    def test_repeated_part_export_uses_a_fresh_folder_without_stale_jobs(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _cross_material_settings()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "assembly.3mf"
            first = workflow._write_individual_part_models(
                prepared, settings, destination, None, None
            )
            stale = first[0].parent / "stale_old_part.3mf"
            stale.write_bytes(b"stale")
            second = workflow._write_individual_part_models(
                prepared, settings, destination, None, None
            )
            self.assertNotEqual(first[0].parent, second[0].parent)
            self.assertTrue(stale.is_file())
            self.assertEqual(len(tuple(second[0].parent.glob("*.3mf"))), 2)
            self.assertFalse((second[0].parent / stale.name).exists())

    def test_individual_only_uses_local_colors_and_generic_material_profiles(self) -> None:
        prepared = _two_watertight_tetrahedra()
        settings = _cross_material_settings()
        expected = engine.recolor_level_parts(
            prepared.final,
            settings.geometry.height_mm,
            settings.tone,
            settings.palette,
            settings.part_palettes,
        )
        captured: dict[str, np.ndarray] = {}

        def render(_reference, _level, colors, **_kwargs):
            captured["target"] = np.asarray(colors.target_face_rgb).copy()
            return Image.new("RGB", (32, 32), "white")

        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "assembly.3mf"
            with patch(
                "spectrum_mapper.renderer.render_three_column_comparison",
                side_effect=render,
            ):
                result = workflow.export_bundle(
                    prepared,
                    settings,
                    destination,
                    include_vertex_obj=False,
                    individual_only=True,
                )

            self.assertTrue(result.individual_only)
            self.assertIsNone(result.model_path)
            self.assertFalse(destination.exists())
            self.assertEqual(len(result.part_model_paths), 2)
            self.assertEqual(
                _project_filament_profiles(result.part_model_paths[0]),
                ["Generic PLA"] * 4,
            )
            self.assertEqual(
                _project_filament_profiles(result.part_model_paths[1]),
                ["Generic ABS"] * 4,
            )
            np.testing.assert_allclose(captured["target"], expected.target_face_rgb)

            manifest = json.loads(
                (
                    result.part_model_paths[0].parent
                    / "パーツ別3MF_manifest.json"
                ).read_text(encoding="utf-8-sig")
            )
            self.assertEqual(
                [item["material"] for item in manifest["parts"]],
                ["PLA", "ABS"],
            )
            report = json.loads(result.report_path.read_text(encoding="utf-8-sig"))
            self.assertTrue(report["parts"]["individual_only"])
            self.assertEqual(
                report["print_profile"]["individual_part_materials"],
                ["ABS", "PLA"],
            )
            guide = result.guide_path.read_text(encoding="utf-8-sig")
            self.assertIn("Generic PLA", guide)
            self.assertIn("Generic ABS", guide)


class MaterialGuideAndLanguageTests(unittest.TestCase):
    def test_generic_profile_names_are_exact(self) -> None:
        self.assertEqual(generic_filament_profile("PLA"), "Generic PLA")
        self.assertEqual(generic_filament_profile("ABS"), "Generic ABS")
        self.assertEqual(generic_filament_profile("PETG"), "Generic PETG")

    def test_normal_and_chart_guides_follow_material(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            abs_palette = PaletteSettings(material="ABS")
            petg_palette = PaletteSettings(material="PETG")
            normal = root / "normal.txt"
            engine.write_guide(normal, Path("part.3mf"), 20.0, abs_palette)
            normal_text = normal.read_text(encoding="utf-8-sig")
            self.assertIn("Generic ABS", normal_text)
            self.assertIn("Top Cover", normal_text)
            self.assertNotIn("Generic PLAは仮設定", normal_text)

            chart_en = root / "chart_en.md"
            calibration_chart._write_guide(
                chart_en,
                "chart.3mf",
                petg_palette,
                ({},),
                language="en",
                target_label="PETG fixture",
            )
            en_text = chart_en.read_text(encoding="utf-8")
            self.assertIn("Generic PETG placeholders", en_text)
            self.assertIn("PETG beta", en_text)
            self.assertIn("never used as fallback", en_text)

            chart_ja = root / "chart_ja.md"
            calibration_chart._write_guide(
                chart_ja,
                "chart.3mf",
                abs_palette,
                ({},),
                language="ja",
                target_label="ABS fixture",
            )
            ja_text = chart_ja.read_text(encoding="utf-8")
            self.assertIn("Generic ABS", ja_text)
            self.assertIn("Top Cover", ja_text)
            self.assertIn("ABS内だけで近似", ja_text)

    def test_material_ui_and_cross_material_export_text_are_bilingual(self) -> None:
        ja = Translator("ja")
        en = Translator("en")
        self.assertEqual(ja.text("palette.material_pla"), "PLAで混色")
        self.assertEqual(en.text("palette.material_abs"), "Mix with ABS β")
        self.assertIn("Top Cover", ja.text("palette.abs_warning"))
        self.assertIn("never used as fallback", en.text("palette.abs_warning"))
        self.assertIn(
            "independent material-specific 3MF",
            en.text("export.cross_material_body", materials="PLA / ABS"),
        )
        individual_done = en.text(
            "export.individual_only_done_body",
            folder="C:/output/parts",
            count=2,
        )
        self.assertIn("Open as project", individual_done)
        self.assertNotIn("保存", individual_done)
        self.assertIn(
            "候補色 268色",
            ja.text(
                "palette.material_result_metric",
                material="ABS",
                count=268,
                delta=19.25,
            ),
        )
        self.assertGreater(MATERIAL_GAMUT_WARNING_MEAN_DELTA_E76, 0.0)


if __name__ == "__main__":
    unittest.main()
