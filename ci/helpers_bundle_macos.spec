# Package the unchanged onedir helpers as proper nested macOS application bundles.
from pathlib import Path

original_spec = Path(SPECPATH).parent / "tools" / "helpers_macos.spec"
exec(compile(original_spec.read_text(), str(original_spec), "exec"))
bundle = BUNDLE(coll, name=f"{NAME}.app",
                bundle_identifier=f"app.chromamatter.orca.{NAME}",
                info_plist={"LSMinimumSystemVersion": "15.0", "LSUIElement": True})
