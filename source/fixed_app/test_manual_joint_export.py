from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

# Install the production portable 3MF writer.
import spectrum_mapper_hotfix  # noqa: F401,E402
from spectrum_mapper.manual_joints import (  # noqa: E402
    ManualJointSettings,
    create_manual_joint,
    list_manual_joint_interfaces,
)
from spectrum_mapper.models import AppSettings, GeometrySettings  # noqa: E402
from spectrum_mapper.workflow import export_bundle  # noqa: E402
from test_manual_joints import HEIGHT_MM, _prepared_pair  # noqa: E402


class ManualJointExportTests(unittest.TestCase):
    def test_jointed_pair_exports_as_two_watertight_008_projects(self) -> None:
        prepared, _repair = _prepared_pair()
        interface = list_manual_joint_interfaces(prepared)[0]
        male_face = interface.first_cap_face_ids[0]
        center = np.asarray(prepared.final.vertices_unit)[
            np.asarray(prepared.final.faces)[male_face]
        ].mean(axis=0)
        joint = create_manual_joint(
            prepared,
            male_face_id=male_face,
            center_unit=center,
            height_mm=HEIGHT_MM,
            settings=ManualJointSettings(
                width_mm=6.0,
                height_mm=4.0,
                depth_mm=6.0,
                clearance_mm=0.25,
            ),
        )
        settings = AppSettings(
            geometry=GeometrySettings(
                height_mm=HEIGHT_MM,
                target_faces=10_000,
                preview_faces=10_000,
                min_component_faces=1,
                auto_joints=False,
                export_individual_parts=True,
            )
        )

        with tempfile.TemporaryDirectory() as folder:
            result = export_bundle(
                joint.after,
                settings,
                Path(folder) / "manual_joint.3mf",
                include_vertex_obj=False,
            )
            self.assertTrue(result.model_path.is_file())
            self.assertEqual(result.validation["parts"], 2)
            self.assertEqual(result.validation["components"], 2)
            self.assertEqual(result.validation["watertight_parts"], 2)
            self.assertEqual(result.validation["validated_solid_parts"], 2)
            self.assertEqual(result.validation["layer_height_mm"], 0.08)
            self.assertEqual(result.validation["initial_layer_height_mm"], 0.2)
            self.assertEqual(len(result.part_model_paths), 2)
            self.assertTrue(all(path.is_file() for path in result.part_model_paths))

            with ZipFile(result.model_path) as archive:
                self.assertIsNone(archive.testzip())
                assembly = json.loads(
                    archive.read("Metadata/tripo_assembly.json").decode("utf-8")
                )
                project = json.loads(
                    archive.read("Metadata/project_settings.config").decode("utf-8")
                )
            manual_records = assembly["manual_joint_records"]
            self.assertEqual(len(manual_records), 1)
            self.assertEqual(
                manual_records[0]["positioning"],
                "user_selected_surface_point",
            )
            self.assertEqual(
                manual_records[0]["contact_validation"],
                "passed_volume_balance",
            )
            self.assertEqual(project["layer_height"], "0.08")
            self.assertEqual(project["initial_layer_print_height"], "0.2")
            self.assertEqual(project["adaptive_layer_height"], "0")

            report = json.loads(result.report_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(
                report["assembly"]["manual_joint_records"][0]["shape"],
                "keyed_rectangle",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
