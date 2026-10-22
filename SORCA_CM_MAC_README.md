# Sorca CM — macOS Apple Silicon build

This is the Snapmaker Orca based Sorca CM application. The upstream startup logo and internal project formats remain unchanged.

## Scope

- Apple Silicon, macOS 15 or later. This package is not an Intel or Universal build.
- The app and matching GLB/color-editor helpers are built from the source packet identified by `SOURCE_MANIFEST.json`.
- The package is ad-hoc signed, not Apple Developer ID signed or notarized. Treat macOS first-launch trust checks separately from compilation checks.
- Current macOS GUI behavior, color editing, model slicing, device communication and physical printing have not been verified.
- Transparent coat, color lithophane, shape-line cutting, recess-color suggestions and reflection suppression remain beta features.

## Opening and preserving existing work

Keep the old version and projects. Extract `Sorca CM.app` into a new location and open it explicitly after reviewing the source and package hashes. The package does not register stock Orca file/URL associations. It uses the existing CM application identity and data-directory logic; this build has not been checked interactively on a Mac.

## Evidence included with a successful build

`BUILD_RECORD.json` records the exact source packet, workflow revision and completed package checks. CLI and helper smoke tests do not establish GUI or print correctness. The synthetic GLB smoke test covers v8 fixed four-material import, three-material dark slots, reserved coating material, face-order preservation and original input bytes. It does not claim optical color accuracy.

`SOURCE_MANIFEST.json` identifies each source file; `SHA256SUMS` identifies the final ZIP. Upstream and bundled dependency notices are in `Contents/SharedSupport/NativeNotices` and the helper bundles.

## Build history

The older dev3-R8 Apple Silicon workflow succeeded on 2026-10-12 ([run 38262621204](https://github.com/Ponkichi0718/ChromaMatter/actions/runs/38262621204)). That success is evidence for the older source only. The 2026-10-22 Sorca CM workflow uses a separate source-only prerelease and manual dispatch. Check the current Actions run and its BUILD_RECORD.json for completion; configuration publication alone is not a successful macOS build.
