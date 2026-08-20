from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))

from spectrum_mapper.i18n import Translator  # noqa: E402
from spectrum_mapper.manual_joints import (  # noqa: E402
    MANUAL_JOINT_WORKFLOW_KEYS,
    ManualJointError,
    assess_manual_joint_availability,
    list_manual_joint_interfaces,
    resolve_manual_joint_target,
)
from test_manual_joints import HEIGHT_MM, _prepared_pair  # noqa: E402


class ManualJointAvailabilityTests(unittest.TestCase):
    def test_ready_state_lists_interface_and_eligible_parts(self) -> None:
        prepared, _repair = _prepared_pair()
        status = assess_manual_joint_availability(prepared)
        self.assertTrue(status.available)
        self.assertEqual(status.code, "ready")
        self.assertEqual(status.interface_count, 1)
        self.assertEqual(status.eligible_part_ids, (0, 1))
        self.assertEqual(status.next_step_key, "joint.workflow.select_male")
        self.assertEqual(status.workflow_keys, MANUAL_JOINT_WORKFLOW_KEYS)
        self.assertEqual(status.message_values, {"interfaces": 1})
        self.assertIn(
            "1 組",
            Translator("ja").text(status.message_key, **status.message_values),
        )

    def test_open_parts_tell_user_to_solidify_and_reopen_manual_editing(self) -> None:
        prepared, _repair = _prepared_pair()
        prepared.assembly["solidify_parts"] = False
        prepared.assembly["all_parts_watertight"] = False
        prepared.assembly["repair_records"] = []
        status = assess_manual_joint_availability(prepared)
        self.assertFalse(status.available)
        self.assertEqual(status.code, "needs_solidify")
        self.assertEqual(status.next_step_key, "joint.workflow.solidify")
        with self.assertRaisesRegex(
            ManualJointError, "閉立体化.*マニュアル修正を開き直して"
        ):
            list_manual_joint_interfaces(prepared)

    def test_closed_model_without_generated_pair_is_explicit_beta_boundary(self) -> None:
        prepared, _repair = _prepared_pair()
        prepared.assembly["repair_records"] = [
            {
                "method": "partitioned_shared_caps",
                "identity": True,
                "interfaces": [],
            }
        ]
        status = assess_manual_joint_availability(prepared)
        self.assertFalse(status.available)
        self.assertEqual(status.code, "beta_no_planar_shared_interface")
        self.assertIsNone(status.next_step_key)
        with self.assertRaisesRegex(ManualJointError, "ジョイントβ版では非対応"):
            list_manual_joint_interfaces(prepared)

    def test_curved_volume_partition_is_not_misreported_as_needing_repair(self) -> None:
        prepared, _repair = _prepared_pair()
        prepared.assembly["repair_method"] = "volume_partition"
        prepared.assembly["repair_records"] = [
            {"method": "volume_partition", "closed": True}
        ]
        status = assess_manual_joint_availability(prepared)
        self.assertEqual(status.code, "beta_no_planar_shared_interface")
        self.assertEqual(
            status.message_key,
            "joint.availability.beta_no_planar_shared_interface",
        )

    def test_joint_and_split_states_have_distinct_recovery_actions(self) -> None:
        prepared, _repair = _prepared_pair()

        automatic = deepcopy(prepared)
        automatic.assembly["joint_records"] = [{"automatic": True}]
        status = assess_manual_joint_availability(automatic)
        self.assertEqual(status.code, "automatic_joint_conflict")
        self.assertEqual(status.next_step_key, "joint.workflow.disable_auto_joint")

        manual = deepcopy(prepared)
        manual.assembly["manual_joint_records"] = [{"manual": True}]
        status = assess_manual_joint_availability(manual)
        self.assertEqual(status.code, "already_jointed")
        self.assertEqual(status.next_step_key, "joint.workflow.undo_existing_joint")

        separated = deepcopy(prepared)
        separated.assembly["manual_part_assignment"] = True
        status = assess_manual_joint_availability(separated)
        self.assertEqual(status.code, "freehand_split_unsupported")
        self.assertEqual(status.next_step_key, "joint.workflow.reprocess_before_split")

    def test_malformed_interface_metadata_is_reported_without_throwing(self) -> None:
        prepared, _repair = _prepared_pair()
        prepared.assembly["repair_records"] = [
            {"method": "partitioned_shared_caps", "interfaces": "broken"}
        ]
        status = assess_manual_joint_availability(prepared)
        self.assertEqual(status.code, "invalid_metadata")
        self.assertIn("not a list", status.technical_detail)

    def test_wrong_exterior_face_error_explains_what_to_click(self) -> None:
        prepared, _repair = _prepared_pair()
        interface = list_manual_joint_interfaces(prepared)[0]
        exterior = next(
            int(face_id)
            for face_id in np.flatnonzero(prepared.final.face_part_ids == 0)
            if int(face_id) not in interface.first_cap_face_ids
        )
        center = prepared.final.vertices_unit[
            prepared.final.faces[exterior]
        ].mean(axis=0)
        with self.assertRaisesRegex(
            ManualJointError,
            "雄側を編集パーツ.*相手を透明または非表示.*平面をクリック",
        ):
            resolve_manual_joint_target(
                prepared,
                male_face_id=exterior,
                center_unit=center,
                height_mm=HEIGHT_MM,
            )


class ManualJointGuidanceTranslationTests(unittest.TestCase):
    def test_workflow_is_complete_in_japanese_and_english(self) -> None:
        ja = Translator("ja")
        en = Translator("en")
        japanese_steps = [ja.text(key) for key in MANUAL_JOINT_WORKFLOW_KEYS]
        english_steps = [en.text(key) for key in MANUAL_JOINT_WORKFLOW_KEYS]
        self.assertEqual(len(japanese_steps), 6)
        self.assertIn("閉立体化", japanese_steps[0])
        self.assertIn("開き直す", japanese_steps[1])
        self.assertIn("編集パーツ", japanese_steps[2])
        self.assertIn("透明または非表示", japanese_steps[3])
        self.assertIn("ジョイント配置 β", japanese_steps[4])
        self.assertIn("平面接合面", japanese_steps[5])
        self.assertTrue(all(step[0].isdigit() for step in english_steps))
        unsupported = ja.text(
            "joint.availability.beta_no_planar_shared_interface"
        )
        self.assertIn("ジョイントβ版では非対応", unsupported)

    def test_ready_copy_includes_interface_count(self) -> None:
        message = Translator("en").text(
            "joint.availability.ready", interfaces=2
        )
        self.assertIn("2 generated planar interface", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
