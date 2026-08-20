from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.models import AppSettings, MeshLevel, ObjAsset, PreparedGeometry
from spectrum_mapper.part_names import (
    PartNameError,
    apply_part_name_overrides,
    collect_part_name_overrides,
    rename_prepared_part,
)


PART_KEYS = ("0:body", "1:cloak")


def _level() -> MeshLevel:
    vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [2.0, 0.0, 0.0],
            [3.0, 0.0, 0.0],
            [2.0, 1.0, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int32)
    return MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=np.full((6, 3), 0.5, dtype=np.float64),
        areas_unit=np.asarray([0.5, 0.5], dtype=np.float64),
        neighbors=None,
        face_part_ids=np.asarray([0, 1], dtype=np.int16),
        part_names=("Body", "Cloak"),
        part_keys=PART_KEYS,
    )


def _prepared() -> PreparedGeometry:
    final = _level()
    preview = _level()
    source = ObjAsset(
        path=Path("fixture.obj"),
        sha256="a" * 64,
        file_size=1,
        vertices=final.vertices_unit,
        colors=final.vertex_colors,
        faces=final.faces,
        original_vertex_count=6,
        original_face_count=2,
        warnings=[],
        part_names=final.part_names,
        part_keys=PART_KEYS,
        face_part_ids=final.face_part_ids,
    )
    return PreparedGeometry(
        source=source,
        final=final,
        preview=preview,
        clean_vertex_count=6,
        clean_face_count=2,
        removed_vertices=0,
        removed_faces=0,
        topology={"watertight": False},
        source_area_unit=1.0,
        source_volume_unit=0.0,
        simplified_area_unit=1.0,
        simplified_volume_unit=0.0,
        source_dimensions_unit=np.asarray([3.0, 1.0, 0.0]),
        warnings=[],
        part_names=final.part_names,
        part_keys=PART_KEYS,
        part_stats=[
            {"id": 0, "key": PART_KEYS[0], "name": "Body"},
            {"id": 1, "key": PART_KEYS[1], "name": "Cloak"},
        ],
    )


class PartNameTests(unittest.TestCase):
    def test_rename_changes_only_display_metadata(self) -> None:
        prepared = _prepared()
        before_ids = prepared.final.face_part_ids.copy()
        before_keys = tuple(prepared.final.part_keys)

        result = rename_prepared_part(prepared, PART_KEYS[1], "青いマント")

        self.assertEqual(result, "青いマント")
        self.assertEqual(prepared.final.part_names, ("Body", "青いマント"))
        self.assertEqual(prepared.preview.part_names, ("Body", "青いマント"))
        self.assertEqual(prepared.part_names, ("Body", "青いマント"))
        self.assertEqual(prepared.part_stats[1]["name"], "青いマント")
        self.assertEqual(prepared.final.part_keys, before_keys)
        np.testing.assert_array_equal(prepared.final.face_part_ids, before_ids)

    def test_blank_duplicate_and_control_character_names_are_rejected(self) -> None:
        for value in ("", " body ", "line\nbreak"):
            with self.subTest(value=value):
                prepared = _prepared()
                with self.assertRaises(PartNameError):
                    rename_prepared_part(prepared, PART_KEYS[1], value)
                self.assertEqual(prepared.final.part_names, ("Body", "Cloak"))

    def test_saved_overrides_follow_stable_keys_and_ignore_unknown_keys(self) -> None:
        prepared = _prepared()

        active = apply_part_name_overrides(
            prepared,
            {PART_KEYS[0]: "胴体", "old:model:key": "古い名前"},
        )

        self.assertEqual(active, {PART_KEYS[0]: "胴体"})
        self.assertEqual(prepared.final.part_names, ("胴体", "Cloak"))
        self.assertEqual(
            collect_part_name_overrides(prepared),
            {PART_KEYS[0]: "胴体", PART_KEYS[1]: "Cloak"},
        )

    def test_saved_names_can_be_swapped_atomically(self) -> None:
        prepared = _prepared()

        apply_part_name_overrides(
            prepared,
            {PART_KEYS[0]: "Cloak", PART_KEYS[1]: "Body"},
        )

        self.assertEqual(prepared.final.part_names, ("Cloak", "Body"))
        self.assertEqual(prepared.final.part_keys, PART_KEYS)

    def test_settings_round_trip_names_and_valid_backgrounds(self) -> None:
        settings = AppSettings(
            part_names={PART_KEYS[0]: "胴体", PART_KEYS[1]: "外套"},
            manual_view_backgrounds={"a" * 64: "light"},
        )

        restored = AppSettings.from_dict(settings.to_dict())

        self.assertEqual(restored.part_names, settings.part_names)
        self.assertEqual(
            restored.manual_view_backgrounds,
            settings.manual_view_backgrounds,
        )
        malformed = AppSettings.from_dict(
            {
                "manual_view_backgrounds": {
                    "not-a-sha": "light",
                    "b" * 64: "unknown",
                    "c" * 64: "neutral",
                }
            }
        )
        self.assertEqual(
            malformed.manual_view_backgrounds,
            {"c" * 64: "neutral"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
