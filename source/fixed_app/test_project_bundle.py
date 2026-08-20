from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spectrum_mapper import project_bundle
from spectrum_mapper.project_bundle import (
    BUNDLE_SCHEMA,
    GeometryRestoreState,
    ProjectBundleError,
    ProjectLoadState,
    default_project_folder_name,
    inspect_project_path,
    save_project_bundle,
    save_project_bundle_in_parent,
)
from spectrum_mapper.models import MeshLevel, ObjAsset, PreparedGeometry
from spectrum_mapper.paint import mesh_fingerprint


def project_payload(
    *, manual: bool = False, manual_fingerprint: str = "mesh-face-order-123"
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "obj-adjuster.project.v12",
        "settings": {"geometry": {}, "palette": {}, "tone": {}},
        "obj_path": r"C:\private\character.obj",
        "reference_path": r"C:\private\reference.png",
        "parts": [],
    }
    if manual:
        value["manual_paint"] = {
            "schema": "obj-adjuster.manual-paint.v1",
            "mesh_fingerprint": manual_fingerprint,
            "runs": [],
        }
    return value


def read_wrapper(folder: Path) -> dict[str, object]:
    return json.loads((folder / "project.json").read_text(encoding="utf-8"))


def prepared_geometry(source: Path) -> PreparedGeometry:
    vertices = project_bundle.np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        dtype=project_bundle.np.float64,
    )
    colors = project_bundle.np.asarray(
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=project_bundle.np.float64,
    )
    faces = project_bundle.np.asarray([[0, 1, 2]], dtype=project_bundle.np.int32)
    area = project_bundle.np.asarray([0.5], dtype=project_bundle.np.float64)
    neighbors = project_bundle.np.asarray([[-1, -1, -1]], dtype=project_bundle.np.int32)
    part_ids = project_bundle.np.asarray([0], dtype=project_bundle.np.int32)
    level = MeshLevel(
        vertices_unit=vertices,
        faces=faces,
        vertex_colors=colors,
        areas_unit=area,
        neighbors=neighbors,
        face_part_ids=part_ids,
        part_names=("body",),
        part_keys=("part:body",),
        face_provenance=project_bundle.np.asarray([0], dtype=project_bundle.np.uint8),
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    asset = ObjAsset(
        path=source,
        sha256=digest,
        file_size=source.stat().st_size,
        vertices=vertices.copy(),
        colors=colors.copy(),
        faces=faces.copy(),
        original_vertex_count=3,
        original_face_count=1,
        warnings=[],
        part_names=("body",),
        part_keys=("part:body",),
        face_part_ids=part_ids.copy(),
        part_face_counts=(1,),
        part_vertex_counts=(3,),
        part_marker_kind="object",
        has_explicit_parts=True,
    )
    return PreparedGeometry(
        source=asset,
        final=level,
        preview=level,
        clean_vertex_count=3,
        clean_face_count=1,
        removed_vertices=0,
        removed_faces=0,
        topology={"watertight": False, "boundary_edges": 3},
        source_area_unit=0.5,
        source_volume_unit=0.0,
        simplified_area_unit=0.5,
        simplified_volume_unit=0.0,
        source_dimensions_unit=project_bundle.np.asarray([1.0, 1.0, 0.0]),
        warnings=[],
        part_names=("body",),
        part_keys=("part:body",),
        part_stats=[{"id": 0, "name": "body", "faces": 1}],
        assembly={"all_parts_watertight": False},
    )


class PortableProjectBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "勇者.obj"
        self.source_bytes = (
            b"o body\n"
            b"v 0 0 0 255 0 0\n"
            b"v 1 0 0 0 255 0\n"
            b"v 0 1 0 0 0 255\n"
            b"f 1 2 3\n"
        )
        self.source.write_bytes(self.source_bytes)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_parent_workflow_creates_obj_named_folder_with_portable_members(self) -> None:
        result = save_project_bundle_in_parent(
            self.root,
            self.source,
            project_payload(),
        )

        self.assertEqual(result.folder.name, "勇者_project")
        self.assertEqual(result.project_json.name, "project.json")
        self.assertEqual(result.source_obj.name, "source.obj")
        self.assertEqual(result.source_obj.read_bytes(), self.source_bytes)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)  # copied, not moved
        self.assertEqual(
            result.source_sha256,
            hashlib.sha256(self.source_bytes).hexdigest(),
        )
        wrapper = read_wrapper(result.folder)
        self.assertEqual(wrapper["schema"], BUNDLE_SCHEMA)
        self.assertEqual(wrapper["source_obj"]["relative_path"], "source.obj")
        self.assertNotIn("obj_path", wrapper["project"])
        self.assertNotIn("reference_path", wrapper["project"])
        encoded = result.project_json.read_text(encoding="utf-8")
        self.assertNotIn(str(self.source.parent), encoded)
        self.assertEqual(
            set(result.omitted_private_fields), {"obj_path", "reference_path"}
        )

    def test_folder_and_its_json_both_resolve_and_verify_bundled_obj(self) -> None:
        saved = save_project_bundle_in_parent(
            self.root, self.source, project_payload()
        )

        by_folder = inspect_project_path(saved.folder)
        by_json = inspect_project_path(saved.project_json)

        for loaded in (by_folder, by_json):
            self.assertEqual(loaded.state, ProjectLoadState.READY)
            self.assertTrue(loaded.source_ready)
            self.assertEqual(loaded.source_obj, saved.source_obj)
            self.assertEqual(loaded.source_sha256, saved.source_sha256)
            self.assertNotIn("obj_path", loaded.project_data)
            self.assertEqual(
                loaded.geometry_restore_state,
                GeometryRestoreState.NOT_REQUIRED,
            )

    def test_manual_paint_is_not_reported_restored_until_mesh_is_verified(self) -> None:
        saved = save_project_bundle_in_parent(
            self.root,
            self.source,
            project_payload(manual=True),
        )
        loaded = inspect_project_path(saved.folder)

        self.assertEqual(
            loaded.state,
            ProjectLoadState.READY_REQUIRES_GEOMETRY_VERIFICATION,
        )
        self.assertTrue(loaded.source_ready)
        self.assertTrue(loaded.manual_geometry_verification_required)
        self.assertEqual(
            loaded.geometry_restore_state,
            GeometryRestoreState.REBUILD_AND_VERIFY,
        )
        self.assertIn("nondeterministic", loaded.geometry_restore_reason)
        self.assertTrue(
            loaded.verify_prepared_mesh_fingerprint("mesh-face-order-123")
        )
        with self.assertRaises(ProjectBundleError) as raised:
            loaded.verify_prepared_mesh_fingerprint("different")
        self.assertEqual(
            raised.exception.code, "prepared_geometry_fingerprint_mismatch"
        )

    def test_optional_prepared_snapshot_is_hashed_but_still_requires_mesh_check(self) -> None:
        prepared = prepared_geometry(self.source)
        fingerprint = mesh_fingerprint(prepared.final)
        geometry_key = (None, 80_000, "Y", 25, False, True, False)
        saved = save_project_bundle_in_parent(
            self.root,
            self.source,
            project_payload(manual=True, manual_fingerprint=fingerprint),
            prepared_geometry=prepared,
            prepared_geometry_key=geometry_key,
        )
        loaded = inspect_project_path(saved.folder)

        self.assertEqual(
            loaded.geometry_restore_state,
            GeometryRestoreState.SNAPSHOT_AVAILABLE_UNVERIFIED,
        )
        self.assertEqual(
            loaded.state,
            ProjectLoadState.READY_REQUIRES_GEOMETRY_VERIFICATION,
        )
        self.assertEqual(
            loaded.prepared_geometry_snapshot,
            saved.folder / "prepared_geometry.npz",
        )
        self.assertIn("must still be verified", loaded.geometry_restore_reason)
        decoded = loaded.load_exact_prepared_geometry(
            expected_geometry_key=geometry_key
        )
        self.assertEqual(decoded.paint_mesh_fingerprint, fingerprint)
        self.assertEqual(decoded.geometry_key, geometry_key)
        self.assertEqual(decoded.prepared.source.path, saved.source_obj)
        project_bundle.np.testing.assert_array_equal(
            decoded.prepared.final.faces,
            prepared.final.faces,
        )
        project_bundle.np.testing.assert_allclose(
            decoded.prepared.final.vertices_unit,
            prepared.final.vertices_unit,
        )

        loaded.prepared_geometry_snapshot.write_bytes(b"tampered")
        with self.assertRaises(ProjectBundleError) as raised:
            inspect_project_path(saved.folder)
        self.assertIn(
            raised.exception.code,
            {"bundle_member_size_mismatch", "bundle_member_sha256_mismatch"},
        )

    def test_reference_image_is_copied_and_resolved_relatively(self) -> None:
        reference = self.root / "元画像.PNG"
        reference.write_bytes(b"not decoded here; content is hash protected")
        saved = save_project_bundle_in_parent(
            self.root,
            self.source,
            project_payload(),
            reference_image=reference,
        )
        loaded = inspect_project_path(saved.folder)

        self.assertEqual(saved.reference_image.name, "reference.png")
        self.assertEqual(loaded.reference_image, saved.reference_image)
        self.assertEqual(loaded.reference_image.read_bytes(), reference.read_bytes())
        wrapper = read_wrapper(saved.folder)
        self.assertEqual(
            wrapper["reference_image"]["relative_path"], "reference.png"
        )

    def test_existing_destination_is_never_overwritten(self) -> None:
        destination = self.root / "existing_project"
        destination.mkdir()
        marker = destination / "keep.txt"
        marker.write_text("user data", encoding="utf-8")

        with self.assertRaises(ProjectBundleError) as raised:
            save_project_bundle(destination, self.source, project_payload())

        self.assertEqual(raised.exception.code, "destination_exists")
        self.assertEqual(marker.read_text(encoding="utf-8"), "user data")
        self.assertEqual(list(self.root.glob(".existing_project.tmp-*")), [])

    def test_atomic_staging_rolls_back_copy_failure_without_debris(self) -> None:
        destination = self.root / "copy_failure_project"
        with patch.object(
            project_bundle,
            "_copy_regular_file",
            side_effect=OSError("injected copy failure"),
        ):
            with self.assertRaises(OSError):
                save_project_bundle(destination, self.source, project_payload())

        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".copy_failure_project.tmp-*")), [])

    def test_atomic_staging_rolls_back_rename_failure_without_debris(self) -> None:
        destination = self.root / "rename_failure_project"
        with patch.object(
            project_bundle.os,
            "rename",
            side_effect=OSError("injected rename failure"),
        ):
            with self.assertRaises(OSError):
                save_project_bundle(destination, self.source, project_payload())

        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".rename_failure_project.tmp-*")), [])

    def test_nested_absolute_path_is_rejected_before_staging(self) -> None:
        payload = project_payload()
        payload["private"] = {"cache": r"D:\private\mesh.bin"}
        destination = self.root / "private_path_project"

        with self.assertRaises(ProjectBundleError) as raised:
            save_project_bundle(destination, self.source, payload)

        self.assertEqual(raised.exception.code, "absolute_path_in_project")
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".private_path_project.tmp-*")), [])

    def test_missing_and_tampered_bundled_obj_fail_closed(self) -> None:
        first = save_project_bundle(
            self.root / "missing_project", self.source, project_payload()
        )
        first.source_obj.unlink()
        with self.assertRaises(ProjectBundleError) as missing:
            inspect_project_path(first.folder)
        self.assertEqual(missing.exception.code, "bundled_obj_missing")

        second = save_project_bundle(
            self.root / "tampered_project", self.source, project_payload()
        )
        second.source_obj.write_bytes(b"changed but same project")
        with self.assertRaises(ProjectBundleError) as tampered:
            inspect_project_path(second.folder)
        self.assertIn(
            tampered.exception.code,
            {"bundle_member_size_mismatch", "bundle_member_sha256_mismatch"},
        )

    def test_traversal_absolute_and_wrong_suffix_manifest_paths_are_rejected(self) -> None:
        cases = ("../escape.obj", r"C:\escape.obj", "source.txt")
        for index, relative in enumerate(cases):
            with self.subTest(relative=relative):
                saved = save_project_bundle(
                    self.root / f"unsafe_{index}", self.source, project_payload()
                )
                wrapper = read_wrapper(saved.folder)
                wrapper["source_obj"]["relative_path"] = relative
                saved.project_json.write_text(
                    json.dumps(wrapper), encoding="utf-8"
                )
                with self.assertRaises(ProjectBundleError) as raised:
                    inspect_project_path(saved.folder)
                self.assertIn(
                    raised.exception.code,
                    {"unsafe_relative_path", "unexpected_member_type"},
                )

    def test_reparse_or_symlink_source_is_rejected(self) -> None:
        with patch.object(
            project_bundle,
            "_is_reparse_point",
            side_effect=lambda path: Path(path) == self.source,
        ):
            with self.assertRaises(ProjectBundleError) as raised:
                save_project_bundle(
                    self.root / "link_project", self.source, project_payload()
                )
        self.assertEqual(raised.exception.code, "unsafe_link_or_reparse")

    def test_unknown_outer_and_inner_schemas_are_rejected(self) -> None:
        unknown = self.root / "unknown.json"
        unknown.write_text(json.dumps({"schema": "something.else"}), encoding="utf-8")
        with self.assertRaises(ProjectBundleError) as outer:
            inspect_project_path(unknown)
        self.assertEqual(outer.exception.code, "unsupported_project_schema")

        saved = save_project_bundle(
            self.root / "wrong_inner_project", self.source, project_payload()
        )
        wrapper = read_wrapper(saved.folder)
        wrapper["project"]["schema"] = "obj-adjuster.project.v999"
        saved.project_json.write_text(json.dumps(wrapper), encoding="utf-8")
        with self.assertRaises(ProjectBundleError) as inner:
            inspect_project_path(saved.folder)
        self.assertEqual(inner.exception.code, "unsupported_project_schema")

    def test_legacy_json_needs_source_and_does_not_emit_false_mismatch(self) -> None:
        legacy = self.root / "legacy.json"
        payload = project_payload(manual=True)
        payload["manual_parts"] = {"mesh_fingerprint": "old-parts"}
        payload["manual_joint"] = {"base_mesh_fingerprint": "old-joint"}
        legacy.write_text(json.dumps(payload), encoding="utf-8")

        loaded = inspect_project_path(legacy)

        self.assertEqual(loaded.state, ProjectLoadState.NEEDS_SOURCE_OBJ)
        self.assertFalse(loaded.source_ready)
        self.assertIsNone(loaded.source_obj)
        self.assertEqual(loaded.legacy_source_name, "character.obj")
        self.assertNotIn("obj_path", loaded.project_data)
        self.assertNotIn("manual_parts", loaded.project_data)
        self.assertNotIn("manual_joint", loaded.project_data)
        self.assertEqual(
            set(loaded.ignored_features), {"manual_parts", "manual_joint"}
        )
        self.assertEqual(
            loaded.expected_mesh_fingerprints,
            {"manual_paint": "mesh-face-order-123"},
        )

    def test_new_bundle_omits_removed_split_and_joint_payloads(self) -> None:
        payload = project_payload(manual=True)
        payload["manual_parts"] = {"mesh_fingerprint": "old-parts"}
        payload["manual_joint"] = {"base_mesh_fingerprint": "old-joint"}
        saved = save_project_bundle_in_parent(self.root, self.source, payload)
        wrapper = read_wrapper(saved.folder)

        self.assertNotIn("manual_parts", wrapper["project"])
        self.assertNotIn("manual_joint", wrapper["project"])
        self.assertIn("manual_parts", saved.omitted_private_fields)
        self.assertIn("manual_joint", saved.omitted_private_fields)
        self.assertEqual(
            wrapper["restore_contract"]["expected_mesh_fingerprints"],
            {"manual_paint": "mesh-face-order-123"},
        )

    def test_duplicate_json_keys_are_rejected(self) -> None:
        duplicate = self.root / "duplicate.json"
        duplicate.write_text(
            '{"schema":"obj-adjuster.project.v11","schema":"obj-adjuster.project.v11","settings":{}}',
            encoding="utf-8",
        )
        with self.assertRaises(ProjectBundleError) as raised:
            inspect_project_path(duplicate)
        self.assertEqual(raised.exception.code, "duplicate_json_key")

    def test_unsafe_names_and_wrong_save_schema_are_rejected(self) -> None:
        self.assertEqual(default_project_folder_name(self.source), "勇者_project")
        with self.assertRaises(ProjectBundleError) as name_error:
            save_project_bundle_in_parent(
                self.root,
                self.source,
                project_payload(),
                project_folder_name="../escape",
            )
        self.assertEqual(name_error.exception.code, "unsafe_project_folder_name")

        payload = project_payload()
        payload["schema"] = "obj-adjuster.project.v10"
        with self.assertRaises(ProjectBundleError) as schema_error:
            save_project_bundle(
                self.root / "old_schema_project", self.source, payload
            )
        self.assertEqual(schema_error.exception.code, "unsupported_project_schema")


if __name__ == "__main__":
    unittest.main()
