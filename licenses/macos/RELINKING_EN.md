# macOS LGPL replacement and relinking guide (DRAFT)

Product display version: **0.8beta**  
Target: Apple Silicon, macOS 15 or newer  
State: **not yet validated on a volunteer Mac; not distribution approval**

ChromaMatter is packaged as a PyInstaller `.app` bundle. Some Python wheels may
carry dynamically linked libraries governed by the LGPL, including Qt within
PyMeshLab, GEOS within Shapely, and GMP within the upstream PyTetWild arm64
wheel. Each library keeps its own terms. This guide describes the intended
replacement route; it does not claim that the current alpha has passed it.

## What must be supplied before external testing

The package must include:

- the exact `BINARY_COMPONENT_MAP.json` and `SBOM.spdx.json` generated from the
  final `.app` inventory;
- the LGPL texts and every wheel-supplied license/notice file;
- complete corresponding source and build information for the exact bundled
  LGPL libraries;
- this guide, updated with the actual bundle paths and a successful replacement
  test on Apple Silicon.

`BINARY_COMPONENT_MAP.json` is authoritative for the final paths. Do not infer
them from this draft or reuse paths from the Windows package.

## Intended replacement procedure

1. Keep an untouched copy of `ChromaMatter-macOS-Alpha.app` and its SHA-256.
2. Obtain or build a compatible modified LGPL library for Apple Silicon. Match
   the library's public ABI, install name, architecture, and minimum macOS
   version to the original recorded in the component map.
3. Copy the `.app` to a new test location. Replace only the mapped LGPL
   `.dylib` or framework file inside `Contents/Frameworks`.
4. If the replacement uses a different Mach-O install name, use Apple's
   `install_name_tool` to restore the exact `@rpath`, `@loader_path`, or
   framework identity recorded by the inventory. Do not add absolute paths to
   a developer machine.
5. Re-sign the modified test bundle locally:

   ```sh
   codesign --force --deep --sign - ChromaMatter-macOS-Alpha.app
   codesign --verify --deep --strict --verbose=2 ChromaMatter-macOS-Alpha.app
   ```

6. Re-run the repository's packaged self-test, Japanese and English UI smoke
   tests, app audit, and app-inventory generator against the modified bundle.
7. Compare the new inventory with the original. The intended library and its
   dependent signatures may change; unrelated executable bytes must not.
8. Launch with Finder's **Open** action if Gatekeeper asks. Never disable
   Gatekeeper globally.

## Current limitations

- The bundle is ad-hoc signed, not Developer ID signed or notarized.
- A source rebuild of the whole application is currently the conservative
  fallback if a wheel embeds LGPL code in a way that is not independently
  replaceable.
- Qt plugin compatibility, GEOS/Shapely ABI compatibility, and the PyTetWild
  GMP loader path still require validation on the final app bytes.
- Successful application launch alone is not relinking evidence. The modified
  library must be loaded and the affected feature must pass a functional test.

Until `DISTRIBUTION_APPROVAL.json` says `approved` for the same source commit
and app-inventory SHA-256, treat these steps as an engineering draft and do not
redistribute the app.

This document is an engineering safeguard, not legal advice.
