# Snapmaker Orca with CM 2.4.0 — Apple Silicon trial

This build uses the Window1 2.4.0 source (version 01.10.01.50), including the transparent-window fill adjacency correction, with matching importer/editor source and POSIX process launchers.

Requires Apple Silicon and macOS 15 or later. Extract `CM-240-Window1-arm64-app.zip` and open `Snapmaker Orca with CM 2.4.0 Test.app`. Python is bundled. Intel Macs are not supported. The bundle has an ad-hoc signature only; it has no Developer ID signature or Apple notarization.

Keep existing applications, settings, and models. Save trial projects under new names. CM-only project settings require a compatible CM build; stock Orca and older CM releases are not equivalent readers. The source retains the existing CM 2.4.0 data-directory rules; it is not a migration of stock settings.

The source packet and `SOURCE_MANIFEST.json` contain the corresponding native source, matching helper source, source hashes, and upstream reference. The native dependency recipes are those of Snapmaker Orca 2.4.0, including OpenSSL 3.5.7. Dependencies are downloaded during a build. This is not an offline SDK or build environment.

CI checks compilation, bundled helper command-line startup, native `--help`, required resources/notices, and ad-hoc signature integrity. Before compiling native dependencies, one synthetic eight-face, 57-state, two-volume editor session is validated by the bundled editor to load its actual renderer modules without a GUI. Mac GUI/GPU behavior, real-model editing, slicing, print support, actual printing, transparency, color accuracy, and TD calibration are not verified by this build. Existing Window1/Region6 feature limits remain; a successful build does not establish general contour-cut compatibility.

The workflow is manual, uses one standard `macos-15` arm64 runner, and retains its artifact for one day. No release assets, download pages, or billing settings are changed by the workflow.
