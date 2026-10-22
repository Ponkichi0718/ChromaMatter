"""One synthetic editor admission, using the established 8-face/57-state fixture.

The construction matches helpers/editor/tests/test_external_editor.py::fixture
used by the successful 2026-09-20 Linux packaging admission. Standard-library
binary packing avoids requiring a separate NumPy install on a helper-cache hit.
No user model or GUI is involved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def fixture(directory):
    states, volumes = 57, 2
    palette = [{"id": i + 5, "name": f"A/B {i}/{states - 1}",
                "rgb": [round(255 * i / (states - 1)), 80, 180],
                "weights": [states - 1 - i, i, 0, 0], "weight_total": states - 1,
                "recipe": {"opaque": f"original-{i}"}} for i in range(states)]
    vertices = struct.pack("<12f", 0, 0, 0, 10, 0, 0, 0, 10, 0, 0, 0, 10)
    triangles = struct.pack("<12I", 0, 2, 1, 0, 1, 3, 1, 2, 3, 2, 0, 3)
    ids = struct.pack("<4I", 5, 5, 6, states + 4)
    records = []
    for v in range(volumes):
        for name, data, suffix in (("vertices", vertices, "f32"), ("triangles", triangles, "u32"), ("states", ids, "u32")):
            (directory / f"volume_{v}.{name}.{suffix}").write_bytes(data)
        transform = [1.0, 0.0, 0.0, float(20 * v), 0.0, 1.0, 0.0, 0.0,
                     0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        records.append({"index": v, "name": f"Part{v}", "vertex_count": 4, "face_count": 4,
                        "vertices": f"volume_{v}.vertices.f32", "triangles": f"volume_{v}.triangles.u32",
                        "states": f"volume_{v}.states.u32", "transform": transform, "mesh_sha256": "b" * 64})
    data = {"schema": "chromamatter.paint-session.v1", "token": "a" * 64, "object_id": 99,
            "palette": palette, "physical_colors": ["#00FFFF", "#FF00FF", "#808080", "#808080"], "volumes": records}
    (directory / "manifest.json").write_text(json.dumps(data), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    session = output / "session"
    session.mkdir()
    fixture(session)
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in session.iterdir()}
    result = subprocess.run([str(args.editor.resolve(strict=True)), "--session", str(session), "--validate-only"],
                            capture_output=True, text=True, timeout=60)
    (output / "editor-validation.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Bundled editor admission failed; see editor-validation.log and session/error.json")
    report = json.loads((session / "validation.json").read_text(encoding="utf-8"))
    expected = {"valid": True, "faces": 8, "states": 57, "volumes": 2, "gui": "not_started"}
    if report != expected or (session / "result.json").exists():
        raise RuntimeError("Unexpected editor admission report or edit result")
    for name, digest in before.items():
        if hashlib.sha256((session / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Editor admission changed a source fixture file")
    summary = {"editor_validate_exit_code": result.returncode, "editor": report,
               "fixture": "synthetic-two-tetrahedra", "gui_tested": False,
               "full_regression_run": False, "slicing_tested": False}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
