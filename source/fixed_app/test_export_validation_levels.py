from __future__ import annotations

import copy
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np

from spectrum_mapper import engine, workflow
from spectrum_mapper.export_validation import LEVELS, accepts_topology, require_level
from spectrum_mapper.models import AppSettings, ToneSettings
from test_part_exports import _two_watertight_tetrahedra, _settings_with_distinct_part_filaments


def fixture(kind="closed"):
    prepared, _ = workflow._extract_prepared_part(_two_watertight_tetrahedra(), 0)
    prepared.assembly = {"solidify_parts": False}
    vertices = prepared.final.vertices_unit.copy()
    faces = prepared.final.faces.copy()
    if kind == "open":
        faces = faces[:-1]
    elif kind == "reversed":
        faces = faces[:, ::-1].copy()
    elif kind == "winding":
        faces[0] = faces[0, ::-1]
    elif kind == "nonmanifold":
        faces = np.vstack((faces, faces[0]))
    elif kind == "degenerate":
        faces = np.vstack((faces, [0, 0, 1]))
    elif kind in {"multiple", "intersecting"}:
        shift = [3., 0., 0.] if kind == "multiple" else [.2, .2, .2]
        vertices = np.vstack((vertices, vertices + shift))
        faces = np.vstack((faces, faces + 4))
    prepared.final.vertices_unit = vertices
    prepared.final.faces = faces
    prepared.final.vertex_colors = np.tile([.4, .3, .2], (len(vertices), 1))
    prepared.final.areas_unit = engine.triangle_areas(vertices, faces)
    prepared.final.neighbors = engine.face_neighbors_partial(faces, len(vertices))
    prepared.final.face_part_ids = np.zeros(len(faces), dtype=np.int16)
    prepared.preview = prepared.final
    prepared.topology = engine.edge_topology(faces, len(vertices))
    prepared.clean_vertex_count = len(vertices)
    prepared.clean_face_count = len(faces)
    prepared.source_area_unit = prepared.simplified_area_unit = float(prepared.final.areas_unit.sum())
    prepared.source_volume_unit = prepared.simplified_volume_unit = engine.signed_volume(vertices, faces)
    settings = AppSettings()
    colours = engine.recolor_level(prepared.final, 50., ToneSettings(), settings.palette)
    return prepared, settings, colours


def write(path, prepared, settings, colours, level):
    return engine._CORE_WRITE_3MF_ATOMIC(
        path, prepared, colours, 50., settings.palette,
        export_validation_level=level,
    )


def validate(path, prepared, level):
    with ZipFile(path) as archive:
        project = json.loads(archive.read("Metadata/project_settings.config"))
    return engine.validate_3mf(
        path, len(prepared.final.vertices_unit), len(prepared.final.faces),
        project["filament_colour"], project["mixed_filament_definitions"],
        export_validation_level=level,
    )


def mutate_archive(path, transform):
    with ZipFile(path) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    transform(payloads)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)


class ExportValidationLevelsTests(unittest.TestCase):
    def test_exact_enum_and_no_accidental_truthy_relaxation(self):
        for value in (None, True, False, 0, "", "HIGH", "auto", [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                require_level(value)
        self.assertEqual(tuple(require_level(v) for v in LEVELS), LEVELS)

    def test_real_mesh_acceptance_matrix_is_monotonic(self):
        cases = {
            "closed": {"high", "medium", "low", "ignore"},
            "open": {"low", "ignore"},
            "multiple": {"medium", "low", "ignore"},
            "intersecting": {"medium", "low", "ignore"},
            "reversed": {"low", "ignore"},
            "winding": {"ignore"},
            "nonmanifold": {"ignore"},
            "degenerate": {"ignore"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            for kind, allowed in cases.items():
                prepared, settings, colours = fixture(kind)
                before = prepared.final.faces.copy()
                for level in LEVELS:
                    with self.subTest(kind=kind, level=level):
                        path = Path(temporary) / f"{kind}-{level}.3mf"
                        if level not in allowed:
                            with self.assertRaises(engine.EngineError):
                                write(path, prepared, settings, colours, level)
                            self.assertFalse(path.exists())
                            continue
                        result = write(path, prepared, settings, colours, level)
                        self.assertEqual(result["geometry_validation_level"], level)
                        self.assertEqual(result["faces"], len(before))
                        if level != "high":
                            self.assertTrue(result["orca_preview_required"])
                            self.assertFalse(result["valid_solids"])
                            self.assertEqual(result["validated_solid_parts"], 0)
                            self.assertEqual(result["self_intersection_warning_policy"], "not_checked")
                            self.assertEqual(result["part_topologies"][0]["self_intersecting_faces"], -1)
                            self.assertIn("self_intersections_not_checked", result["geometry_warnings"][0]["issues"])
                        validate(path, prepared, level)
                np.testing.assert_array_equal(before, prepared.final.faces)

    def test_relaxed_modes_do_not_call_native_self_intersection_scanner(self):
        prepared, settings, colours = fixture("open")
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            engine.ml, "MeshSet", side_effect=AssertionError("native SI scan must not run")
        ):
            for level in ("low", "ignore"):
                write(Path(temporary) / f"{level}.3mf", prepared, settings, colours, level)

    def test_individual_exports_preserve_policy_and_truthful_aggregate(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary, patch(
            "spectrum_mapper.renderer.render_three_column_comparison",
            return_value=Image.new("RGB", (10, 10)),
        ):
            for level in LEVELS:
                with self.subTest(level=level):
                    prepared = _two_watertight_tetrahedra()
                    settings = _settings_with_distinct_part_filaments()
                    settings.export_validation_level = level
                    result = workflow.export_bundle(
                        prepared, settings, Path(temporary) / f"parts-{level}.3mf",
                        individual_only=True, include_vertex_obj=False,
                    )
                    self.assertEqual(len(result.part_model_paths), 2)
                    self.assertIsNone(result.model_path)
                    self.assertEqual(len(result.validation["individual_geometry_validation"]), 2)
                    self.assertEqual(result.validation["valid_solids"], level == "high")
                    report = json.loads(result.report_path.read_text(encoding="utf-8-sig"))
                    self.assertEqual(report["geometry_validation"]["valid_solids"], level == "high")
                    self.assertEqual(report["self_intersection_warning"]["policy"],
                                     "strict_zero" if level == "high" else "not_checked")
                    for path in result.part_model_paths:
                        with ZipFile(path) as archive:
                            metadata = json.loads(archive.read("Metadata/tripo_assembly.json"))
                            self.assertEqual(metadata["export_validation"]["level"], level)

    def test_invalid_arrays_are_never_allowed_or_atomically_replace_destination(self):
        prepared, settings, colours = fixture()
        variants = [
            ("negative", lambda p: p.final.faces.__setitem__((0, 0), -1)),
            ("out_of_range", lambda p: p.final.faces.__setitem__((0, 0), 100)),
            ("fractional", lambda p: setattr(p.final, "faces", p.final.faces.astype(float))),
            ("nan", lambda p: p.final.vertices_unit.__setitem__((0, 0), np.nan)),
            ("infinity", lambda p: p.final.vertices_unit.__setitem__((0, 0), np.inf)),
            ("empty", lambda p: setattr(p.final, "faces", np.empty((0, 3), dtype=np.int32))),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "existing.3mf"
            for label, mutation in variants:
                changed = copy.deepcopy(prepared)
                mutation(changed)
                for level in LEVELS:
                    with self.subTest(label=label, level=level):
                        path.write_bytes(b"previous output")
                        with self.assertRaises(engine.EngineError):
                            write(path, changed, settings, colours, level)
                        self.assertEqual(path.read_bytes(), b"previous output")

    def test_invalid_scale_fails_every_level(self):
        prepared, settings, colours = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            for level in LEVELS:
                for height in (0., -1., np.nan, np.inf, True):
                    with self.subTest(level=level, height=height), self.assertRaises(engine.EngineError):
                        engine._CORE_WRITE_3MF_ATOMIC(
                            Path(temporary) / "bad.3mf", prepared, colours, height,
                            settings.palette, export_validation_level=level,
                        )

    def test_archive_cannot_authorize_its_own_ignore_policy(self):
        prepared, settings, colours = fixture("open")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "open.3mf"
            write(path, prepared, settings, colours, "ignore")
            with self.assertRaises(engine.EngineError):
                validate(path, prepared, "high")
            def tamper(payloads):
                key = "Metadata/tripo_assembly.json"
                data = json.loads(payloads[key])
                data["export_validation"]["level"] = "low"
                payloads[key] = json.dumps(data).encode()
            mutate_archive(path, tamper)
            with self.assertRaises(engine.EngineError):
                validate(path, prepared, "ignore")

    def test_ignore_still_rejects_corrupt_colours_and_invalid_archive_indices(self):
        prepared, settings, colours = fixture("open")
        mutations = {
            "paint": lambda p: p.__setitem__("3D/Objects/object_1.model", p["3D/Objects/object_1.model"].replace(b'paint_color="', b'paint_color="INVALID')),
            "negative_index": lambda p: p.__setitem__("3D/Objects/object_1.model", p["3D/Objects/object_1.model"].replace(b'v1="0"', b'v1="-1"')),
            "nan_vertex": lambda p: p.__setitem__("3D/Objects/object_1.model", re.sub(rb'\bx="[^"]*"', b'x="nan"', p["3D/Objects/object_1.model"], count=1)),
            "filaments": lambda p: p.__setitem__("Metadata/project_settings.config", p["Metadata/project_settings.config"].replace(settings.palette.physical_hex[0].encode(), b"#010203")),
        }
        with tempfile.TemporaryDirectory() as temporary:
            for name, mutation in mutations.items():
                with self.subTest(name=name):
                    path = Path(temporary) / f"{name}.3mf"
                    write(path, prepared, settings, colours, "ignore")
                    # Expected colours are anchored by the caller, not the mutated archive.
                    with ZipFile(path) as archive:
                        project = json.loads(archive.read("Metadata/project_settings.config"))
                    mutate_archive(path, mutation)
                    with self.assertRaises(engine.EngineError):
                        engine.validate_3mf(path, len(prepared.final.vertices_unit), len(prepared.final.faces),
                                            project["filament_colour"], project["mixed_filament_definitions"],
                                            export_validation_level="ignore")


if __name__ == "__main__":
    unittest.main()
