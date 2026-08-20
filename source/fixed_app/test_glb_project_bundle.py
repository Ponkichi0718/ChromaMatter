from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from spectrum_mapper.paint import (
    decode_manual_overrides,
    encode_manual_overrides,
    mesh_fingerprint,
)

from spectrum_mapper.project_bundle import (
    BUNDLE_SCHEMA,
    LEGACY_BUNDLE_SCHEMA,
    ProjectBundleError,
    default_project_folder_name,
    inspect_project_path,
    save_project_bundle_in_parent,
)

from test_project_bundle import prepared_geometry


def _payload() -> dict[str, object]:
    return {
        "schema": "obj-adjuster.project.v12",
        "settings": {"geometry": {}, "palette": {}, "tone": {}},
        "obj_path": r"C:\private\robot.glb",
        "parts": [],
    }


class GlbPortableProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "Hi3D ロボット.glb"
        # The portable codec treats a source as opaque, hash-protected bytes;
        # GLB decoding belongs to the model importer and is tested separately.
        self.source.write_bytes(b"glTF" + (2).to_bytes(4, "little") + b"opaque")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_glb_bundle_uses_generic_manifest_and_preserves_source_bytes(self) -> None:
        saved = save_project_bundle_in_parent(
            self.root,
            self.source,
            _payload(),
        )

        self.assertEqual(saved.folder.name, "Hi3D ロボット_project")
        self.assertEqual(saved.source_asset.name, "source.glb")
        self.assertEqual(saved.source_format, "glb")
        self.assertEqual(saved.source_asset.read_bytes(), self.source.read_bytes())
        wrapper = json.loads(saved.project_json.read_text(encoding="utf-8"))
        self.assertEqual(wrapper["schema"], BUNDLE_SCHEMA)
        self.assertNotIn("source_obj", wrapper)
        self.assertEqual(
            wrapper["source_asset"],
            {
                "relative_path": "source.glb",
                "original_name": self.source.name,
                "format": "glb",
                "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                "fingerprint": "sha256:"
                + hashlib.sha256(self.source.read_bytes()).hexdigest(),
                "size_bytes": self.source.stat().st_size,
            },
        )

        loaded = inspect_project_path(saved.folder)
        self.assertTrue(loaded.source_ready)
        self.assertEqual(loaded.source_asset, saved.source_asset)
        self.assertEqual(loaded.source_obj, saved.source_asset)  # compatibility
        self.assertEqual(loaded.source_format, "glb")
        self.assertEqual(loaded.source_sha256, saved.source_sha256)

    def test_glb_manifest_format_and_canonical_member_are_fail_closed(self) -> None:
        for mutation in ("wrong-format", "wrong-member"):
            with self.subTest(mutation=mutation):
                saved = save_project_bundle_in_parent(
                    self.root,
                    self.source,
                    _payload(),
                    project_folder_name=f"{mutation}_project",
                )
                wrapper = json.loads(saved.project_json.read_text(encoding="utf-8"))
                if mutation == "wrong-format":
                    wrapper["source_asset"]["format"] = "obj"
                else:
                    wrapper["source_asset"]["relative_path"] = "renamed.glb"
                saved.project_json.write_text(json.dumps(wrapper), encoding="utf-8")
                with self.assertRaises(ProjectBundleError) as raised:
                    inspect_project_path(saved.folder)
                self.assertIn(
                    raised.exception.code,
                    {"source_format_mismatch", "invalid_bundle_manifest"},
                )

    def test_v1_source_obj_bundle_remains_readable(self) -> None:
        obj = self.root / "legacy.obj"
        obj.write_text(
            "v 0 0 0 1 0 0\nv 1 0 0 0 1 0\nv 0 1 0 0 0 1\nf 1 2 3\n",
            encoding="utf-8",
        )
        payload = _payload()
        payload["obj_path"] = r"C:\private\legacy.obj"
        saved = save_project_bundle_in_parent(
            self.root,
            obj,
            payload,
            project_folder_name="legacy_v1_project",
        )
        wrapper = json.loads(saved.project_json.read_text(encoding="utf-8"))
        wrapper["schema"] = LEGACY_BUNDLE_SCHEMA
        legacy_manifest = dict(wrapper.pop("source_asset"))
        legacy_manifest.pop("format", None)
        wrapper["source_obj"] = legacy_manifest
        saved.project_json.write_text(json.dumps(wrapper), encoding="utf-8")

        loaded = inspect_project_path(saved.folder)
        self.assertTrue(loaded.source_ready)
        self.assertEqual(loaded.source_format, "obj")
        self.assertEqual(loaded.source_asset.name, "source.obj")

    def test_v2_obj_alias_is_exact_and_disagreement_is_rejected(self) -> None:
        obj = self.root / "current.obj"
        obj.write_text(
            "v 0 0 0 1 0 0\nv 1 0 0 0 1 0\nv 0 1 0 0 0 1\nf 1 2 3\n",
            encoding="utf-8",
        )
        saved = save_project_bundle_in_parent(
            self.root,
            obj,
            _payload(),
            project_folder_name="current_obj_project",
        )
        wrapper = json.loads(saved.project_json.read_text(encoding="utf-8"))
        self.assertEqual(wrapper["schema"], BUNDLE_SCHEMA)
        self.assertEqual(wrapper["source_obj"], wrapper["source_asset"])
        self.assertEqual(wrapper["source_asset"]["format"], "obj")

        wrapper["source_obj"]["original_name"] = "different.obj"
        saved.project_json.write_text(json.dumps(wrapper), encoding="utf-8")
        with self.assertRaises(ProjectBundleError) as raised:
            inspect_project_path(saved.folder)
        self.assertEqual(raised.exception.code, "source_manifest_alias_mismatch")

    def test_folder_name_is_format_neutral(self) -> None:
        self.assertEqual(
            default_project_folder_name(self.source),
            "Hi3D ロボット_project",
        )

    def test_repaired_glb_snapshot_roundtrip_keeps_manual_roots_exact(self) -> None:
        prepared = prepared_geometry(self.source)
        prepared.topology = {"watertight": True, "boundary_edges": 0}
        prepared.assembly = {
            "solidify_parts": True,
            "single_mesh_generic": True,
            "repair_method": "coincident_vertex_seam_weld",
            "all_parts_watertight": True,
        }
        fingerprint = mesh_fingerprint(prepared.final)
        overrides = np.asarray([7], dtype=np.int8)
        payload = _payload()
        payload["manual_paint"] = encode_manual_overrides(
            overrides, fingerprint
        )
        geometry_key = ("explicit-glb-seam-weld", True)

        saved = save_project_bundle_in_parent(
            self.root,
            self.source,
            payload,
            project_folder_name="repaired_glb_project",
            prepared_geometry=prepared,
            prepared_geometry_key=geometry_key,
        )
        loaded = inspect_project_path(saved.folder)
        snapshot = loaded.load_exact_prepared_geometry(
            expected_geometry_key=geometry_key
        )
        loaded.verify_prepared_mesh_fingerprint(
            mesh_fingerprint(snapshot.prepared.final)
        )
        restored = decode_manual_overrides(
            loaded.project_data["manual_paint"],
            expected_face_count=len(snapshot.prepared.final.faces),
            expected_fingerprint=mesh_fingerprint(snapshot.prepared.final),
        )

        np.testing.assert_array_equal(restored, overrides)
        np.testing.assert_array_equal(
            snapshot.prepared.final.faces, prepared.final.faces
        )
        np.testing.assert_array_equal(
            snapshot.prepared.final.vertices_unit,
            prepared.final.vertices_unit,
        )
        self.assertEqual(
            snapshot.prepared.assembly.get("repair_method"),
            "coincident_vertex_seam_weld",
        )


if __name__ == "__main__":
    unittest.main()
