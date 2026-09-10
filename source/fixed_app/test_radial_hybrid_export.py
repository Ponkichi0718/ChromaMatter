from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import numpy as np

from spectrum_mapper.engine import PAINT_CODES
from spectrum_mapper.radial_export import (
    RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010,
    RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
)
from spectrum_mapper.radial_hybrid_export import (
    RADIAL_HYBRID_SCHEMA,
    RadialHybridExportError,
    package_from_selective_hybrid,
    validate_hybrid_3mf,
    write_hybrid_3mf_atomic,
)


PHYSICAL = ("#121212", "#F5F5F5", "#EB3B41", "#F2C94C")
_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def _box_geometry(
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    vertices = np.asarray(
        [
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y1, z0),
            (x0, y1, z0),
            (x0, y0, z1),
            (x1, y0, z1),
            (x1, y1, z1),
            (x0, y1, z1),
        ],
        dtype=np.float64,
    )
    # The x-min diagonal deliberately matches the neighbouring box's x-max
    # diagonal with opposite winding.  This is an exact-touch material
    # manifold, not three merely adjacent visual shells.
    faces = np.asarray(
        [
            (0, 2, 1), (0, 3, 2),       # bottom
            (4, 5, 6), (4, 6, 7),       # top
            (0, 1, 5), (0, 5, 4),       # y-min
            (1, 2, 6), (1, 6, 5),       # x-max
            (2, 3, 7), (2, 7, 6),       # y-max
            (0, 7, 3), (0, 4, 7),       # x-min, matched opposite winding
        ],
        dtype=np.int32,
    )
    return vertices, faces


def _part(
    name: str,
    role: str,
    extruder: int,
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
    exterior_mask: list[bool],
    paint_states: list[int],
) -> SimpleNamespace:
    vertices, faces = _box_geometry(minimum, maximum)
    return SimpleNamespace(
        name=name,
        role=role,
        physical_extruder=extruder,
        vertices_mm=vertices,
        faces=faces,
        external_face_mask=np.asarray(exterior_mask, dtype=np.bool_),
        paint_state_ids=np.asarray(paint_states, dtype=np.int16),
        source_state=None,
    )


def _result(*, shell_shift: float = 0.0) -> SimpleNamespace:
    core_exterior = [True] * 12
    core_exterior[6] = core_exterior[7] = False
    core_paint = [0 if value else -1 for value in core_exterior]

    carrier_exterior = [True] * 12
    for index in (6, 7, 10, 11):
        carrier_exterior[index] = False
    carrier_paint = [-1] * 12
    painted_indices = [
        index for index, value in enumerate(carrier_exterior) if value
    ]
    for offset, index in enumerate(painted_indices):
        # Exercise every non-black physical state F2/F3/F4 as well as an
        # ordinary Ratio state.  The carrier's physical fallback is black, so
        # omission of any of these paint attributes would be visibly wrong.
        carrier_paint[index] = (1, 2, 3, 4)[offset % 4]

    shell_exterior = [True] * 12
    shell_exterior[10] = shell_exterior[11] = False
    shell_paint = [-1] * 12
    return SimpleNamespace(
        plan=SimpleNamespace(black_extruder=1),
        source_volume_mm3=3.0,
        output_volume_mm3=3.0,
        parts=(
            _part(
                "Black conventional carrier",
                "conventional_painted_carrier",
                1,
                (0.0, 0.0, 0.0),
                (1.0, 1.0, 1.0),
                core_exterior,
                core_paint,
            ),
            _part(
                "Legacy physical and Ratio carrier",
                "conventional_painted_carrier",
                1,
                (1.0, 0.0, 0.0),
                (2.0, 1.0, 1.0),
                carrier_exterior,
                carrier_paint,
            ),
            _part(
                "Eligible physical partner shell",
                "partner_outer_shell",
                3,
                (2.0 + shell_shift, 0.0, 0.0),
                (3.0 + shell_shift, 1.0, 1.0),
                shell_exterior,
                shell_paint,
            ),
        ),
        metadata={
            "material_manifold": True,
            "source_exterior_preserved_exactly": True,
            "shared_interface_partition_exact": True,
            "external_surface_coverage_exact": True,
            "gap_mm": 0.0,
            "positive_overlap_mm3": 0.0,
            "source_volume_mm3": 3.0,
            "output_volume_mm3": 3.0,
        },
    )


def _palette() -> SimpleNamespace:
    return SimpleNamespace(
        physical_hex=PHYSICAL,
        palette_state_count=16,
        mix_ratios_b=[33] * 6,
        secondary_mix_ratios_b=[67] * 6,
        output_mix_ratios_b=None,
    )


class RadialHybridExportTests(unittest.TestCase):
    def test_partition_proof_preserves_binary64_coordinate_precision(self) -> None:
        base = _result()
        boundary = 50.0
        narrow_boundary = boundary + 2.0e-11
        spans = (
            ((49.0, 0.0, 0.0), (boundary, 1.0, 1.0)),
            ((boundary, 0.0, 0.0), (narrow_boundary, 1.0, 1.0)),
            ((narrow_boundary, 0.0, 0.0), (narrow_boundary + 1.0, 1.0, 1.0)),
        )
        parts = tuple(
            _part(
                raw.name,
                raw.role,
                raw.physical_extruder,
                minimum,
                maximum,
                raw.external_face_mask.tolist(),
                raw.paint_state_ids.tolist(),
            )
            for raw, (minimum, maximum) in zip(base.parts, spans, strict=True)
        )
        result = SimpleNamespace(
            plan=base.plan,
            source_volume_mm3=2.0,
            output_volume_mm3=2.0,
            parts=parts,
            metadata={
                **base.metadata,
                "source_volume_mm3": 2.0,
                "output_volume_mm3": 2.0,
            },
        )

        package = package_from_selective_hybrid(
            result,
            _palette(),
            process_profile=RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010,
            layer_height_mm=0.10,
        )

        self.assertEqual(len(package.parts), 3)
        self.assertEqual(package.radial_package.process_profile,
                         RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010)

    def test_synthetic_material_manifold_round_trip(self) -> None:
        package = package_from_selective_hybrid(
            _result(),
            _palette(),
            process_profile=RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010,
            layer_height_mm=0.10,
        )
        self.assertEqual(
            [part.role for part in package.parts],
            [
                "conventional_painted_carrier",
                "conventional_painted_carrier",
                "partner_outer_shell",
            ],
        )
        self.assertEqual(
            [part.base_role for part in package.parts],
            ["pure_black_core", "light_core", "partner_outer_shell"],
        )
        self.assertNotIn(",cm1,", package.mixed_filament_definitions)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selective_stage_b.3mf"
            validation = write_hybrid_3mf_atomic(
                path,
                package,
                title="Selective Stage B synthetic proof",
            )
            self.assertTrue(validation.static_validation_ok)
            self.assertFalse(validation.physical_materials_only)
            self.assertEqual(validation.physical_extruders, (1, 1, 3))

            reopened = validate_hybrid_3mf(path)
            self.assertTrue(reopened.static_validation_ok)
            self.assertEqual(reopened.faces, 36)
            with zipfile.ZipFile(path) as archive:
                project = json.loads(
                    archive.read("Metadata/project_settings.config")
                )
                metadata = json.loads(
                    archive.read("Metadata/radial_shell_experimental.json")
                )
                model = ET.fromstring(
                    archive.read("3D/Objects/radial_parts.model")
                )
            self.assertEqual(metadata["schema"], RADIAL_HYBRID_SCHEMA)
            self.assertFalse(metadata["physical_materials_only"])
            self.assertEqual(project["layer_height"], "0.1")
            self.assertEqual(project["wall_generator"], "arachne")
            self.assertEqual(project["sparse_infill_density"], "15%")
            self.assertEqual(project["top_shell_layers"], "2")
            self.assertEqual(project["bottom_shell_layers"], "2")
            self.assertTrue(project["mixed_filament_definitions"])
            self.assertNotIn(",cm1,", project["mixed_filament_definitions"])
            self.assertEqual(metadata["sparse_infill_density_percent"], 15)
            self.assertEqual(
                metadata["safety"]["sparse_infill_density_percent"],
                15,
            )
            self.assertTrue(metadata["safety"]["closed_physical_volumes"])
            self.assertTrue(
                all(
                    part["closed_physical_volume"]
                    for part in metadata["parts"]
                )
            )
            self.assertEqual(
                metadata["base_radial_metadata"]["safety"][
                    "sparse_infill_density_percent"
                ],
                15,
            )
            objects = model.findall(
                f".//{{{_CORE_NS}}}resources/{{{_CORE_NS}}}object"
            )
            paint_counts = [
                sum(
                    "paint_color" in triangle.attrib
                    for triangle in obj.findall(
                        f".//{{{_CORE_NS}}}triangle"
                    )
                )
                for obj in objects
            ]
            self.assertEqual(paint_counts, [10, 8, 0])
            carrier_codes = {
                triangle.attrib["paint_color"]
                for triangle in objects[1].findall(
                    f".//{{{_CORE_NS}}}triangle"
                )
                if "paint_color" in triangle.attrib
            }
            self.assertEqual(
                carrier_codes,
                {PAINT_CODES[state] for state in (1, 2, 3, 4)},
            )

    def test_gap_between_claimed_interface_parts_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            RadialHybridExportError,
            "source-exterior provenance drifted",
        ):
            package_from_selective_hybrid(
                _result(shell_shift=0.01),
                _palette(),
                process_profile=RADIAL_PROCESS_PROFILE_GENERAL_CLASSIC_010,
                layer_height_mm=0.10,
            )

    def test_validator_rejects_restoring_100_percent_sparse_infill(self) -> None:
        package = package_from_selective_hybrid(
            _result(),
            _palette(),
            process_profile=RADIAL_PROCESS_PROFILE_GENERAL_ARACHNE_010,
            layer_height_mm=0.10,
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "arachne-15.3mf"
            tampered = Path(directory) / "arachne-forced-solid.3mf"
            write_hybrid_3mf_atomic(source, package)
            with zipfile.ZipFile(source) as archive:
                members = {
                    name: archive.read(name) for name in archive.namelist()
                }
            project = json.loads(
                members["Metadata/project_settings.config"]
            )
            project["sparse_infill_density"] = "100%"
            members["Metadata/project_settings.config"] = json.dumps(
                project,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, value in members.items():
                    archive.writestr(name, value)

            with self.assertRaisesRegex(
                RadialHybridExportError,
                "sparse infill drifted",
            ):
                validate_hybrid_3mf(tampered)


if __name__ == "__main__":
    unittest.main()
