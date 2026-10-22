"""Record build input identities without recording runner secrets or user paths."""
import argparse
import json
import os
from pathlib import Path
import platform

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
manifest = json.loads(Path("SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
record = {
    "release_label": manifest["release_label"],
    "source_tree_sha256": manifest["source_tree_sha256"],
    "source_packet_sha256": os.environ.get("SOURCE_SHA256"),
    "workflow_commit": os.environ.get("GITHUB_SHA"),
    "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF"),
    "run_id": os.environ.get("GITHUB_RUN_ID"),
    "python": platform.python_version(), "machine": platform.machine(),
    "gui_verified": False, "physical_print_verified": False,
    "notarized": False, "status": "inputs_verified_before_build"
}
args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
