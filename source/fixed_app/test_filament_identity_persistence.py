from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.engine import write_guide
from spectrum_mapper.gui import (
    _fresh_settings_for_new_obj,
    _persistent_preferences_payload,
)
from spectrum_mapper.models import (
    AppSettings,
    FilamentSnapshotRef,
    PaletteSettings,
)
from spectrum_mapper.parts import palettes_are_print_compatible


def product(
    product_id: str,
    color: str = "#E32B35",
    *,
    finish: str = "Standard / Opaque",
) -> SimpleNamespace:
    return SimpleNamespace(
        product_id=product_id,
        brand="Maker",
        series="PLA Basic",
        color_name="Red",
        matched_hex=color,
        finish_class=finish,
        source_kind="measured",
        snapshot_source_kind=None,
        source_url="https://example.invalid/red",
        record_id="catalog-red",
        measurement_id="measurement-red",
    )


def palette_with_ref(
    product_id: str,
    color: str = "#E32B35",
    *,
    finish: str = "Standard / Opaque",
) -> PaletteSettings:
    ref = FilamentSnapshotRef.from_product(
        product(product_id, color, finish=finish)
    )
    assert ref is not None
    return PaletteSettings(
        physical_hex=[color, "#FFFFFF", "#888888", "#FFCCDD"],
        physical_filament_refs=[ref, None, None, None],
    )


class FilamentIdentityPersistenceTests(unittest.TestCase):
    def test_global_and_part_snapshot_refs_survive_json_project_roundtrip(self) -> None:
        global_palette = palette_with_ref("catalog:global-red")
        part_palette = palette_with_ref(
            "catalog:part-red", finish="Matte"
        )
        settings = AppSettings(
            palette=global_palette,
            part_palettes={"part-a": part_palette},
        )

        encoded = json.loads(json.dumps(settings.to_dict()))
        restored = AppSettings.from_dict(encoded)

        global_ref = restored.palette.physical_filament_refs[0]
        part_ref = restored.part_palettes["part-a"].physical_filament_refs[0]
        self.assertIsNotNone(global_ref)
        self.assertIsNotNone(part_ref)
        assert global_ref is not None and part_ref is not None
        self.assertEqual(global_ref.product_id, "catalog:global-red")
        self.assertEqual(part_ref.product_id, "catalog:part-red")
        self.assertEqual(part_ref.finish_class, "Matte")
        self.assertEqual(global_ref.source, "measured")
        self.assertEqual(global_ref.source_url, "https://example.invalid/red")
        self.assertEqual(global_ref.record_id, "catalog-red")
        self.assertEqual(global_ref.measurement_id, "measurement-red")

    def test_old_projects_and_mismatched_snapshots_fail_closed(self) -> None:
        old = AppSettings.from_dict(
            {"palette": {"physical_hex": ["#111111"] * 4}}
        )
        self.assertEqual(old.palette.physical_filament_refs, [None] * 4)

        raw_ref = FilamentSnapshotRef.from_product(product("catalog:red"))
        assert raw_ref is not None
        mismatched = PaletteSettings(
            physical_hex=["#000000"] * 4,
            physical_filament_refs=[raw_ref, None, None, None],
        )
        self.assertIsNone(mismatched.physical_filament_refs[0])

    def test_cross_model_preferences_never_include_product_identity(self) -> None:
        settings = AppSettings(
            palette=palette_with_ref("catalog:private-model-spool"),
            part_palettes={
                "private-part": palette_with_ref("catalog:private-part-spool")
            },
        )

        payload = _persistent_preferences_payload(settings)
        fresh = _fresh_settings_for_new_obj(settings)

        serialized = json.dumps(payload)
        self.assertNotIn("private-model-spool", serialized)
        self.assertNotIn("private-part-spool", serialized)
        self.assertNotIn("physical_filament_refs", serialized)
        self.assertEqual(fresh.palette.physical_filament_refs, [None] * 4)
        self.assertEqual(fresh.part_palettes, {})

    def test_same_hex_different_product_or_finish_is_not_print_compatible(self) -> None:
        first = palette_with_ref("catalog:red-a")
        different_product = palette_with_ref("catalog:red-b")
        different_finish = palette_with_ref(
            "catalog:red-a", finish="Silk / Metallic"
        )
        same = AppSettings.from_dict(
            AppSettings(palette=first).to_dict()
        ).palette

        self.assertTrue(palettes_are_print_compatible(first, same))
        self.assertFalse(
            palettes_are_print_compatible(first, different_product)
        )
        self.assertFalse(
            palettes_are_print_compatible(first, different_finish)
        )

    def test_output_guide_restores_exact_f_slot_loading_mapping(self) -> None:
        palette = palette_with_ref("catalog:red-a")
        with tempfile.TemporaryDirectory() as folder:
            guide = Path(folder) / "guide.txt"
            write_guide(guide, Path("model.3mf"), 100.0, palette)
            text = guide.read_text(encoding="utf-8-sig")

        self.assertIn("F1 #E32B35", text)
        self.assertIn("Maker / PLA Basic / Red", text)
        self.assertIn("finish=Standard / Opaque", text)
        self.assertIn("source=measured", text)
        self.assertIn("product_id=catalog:red-a", text)


if __name__ == "__main__":
    unittest.main()
