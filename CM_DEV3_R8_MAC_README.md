# Snapmaker Orca with CM dev3-R8 — Apple Silicon

This development build contains the current PaintFlow/color-adjustment, local plane-cut, connector, bridge, and protection-brush changes, including the R8 connected protection brush, effective/conflicting protection overlays, and area-based automatic protection-side comparison. It also includes the preceding plate-local slice/material routing and original-source backup compression reuse. Model-color display remains available while the cut plane is visible. Its base is Snapmaker Orca 2.4.0 (internal version 01.10.01.50), with matching importer/editor sources and POSIX process launchers. The release label is **dev3-R8**; it does not change the underlying project schema or stock version number.

Requires Apple Silicon and macOS 15 or later. Extract `CM-dev3-R8-macos-arm64-app.zip` and open `Snapmaker Orca with CM dev3-R8.app`. Python is bundled. Intel Macs are not supported. The bundle has an ad-hoc signature only; it has no Developer ID signature or Apple notarization.

Keep existing applications, settings, and models. Save development-build projects under new names. CM-only project settings require a compatible CM build; stock Orca and older CM releases are not equivalent readers. The existing CM data-directory rules are retained; this package does not isolate existing CM settings or migrate stock settings.

As in the prior Mac build, the auxiliary detailed color-diagnostics view cannot re-analyze an external original GLB; embedded original colors and normal model-color display/editing are separate paths.

The source packet and `SOURCE_MANIFEST.json` identify the exact native/helper source and upstream reference. Native dependency recipes remain based on Snapmaker Orca 2.4.0, including OpenSSL 3.5.7. Dependencies are downloaded during a build. This is not an offline SDK.

CI checks compilation, bundled helper command-line startup, native `--help`, required resources/notices, and ad-hoc signature integrity. Before native compilation, the bundled editor validates one synthetic eight-face, 57-state, two-volume session to load its actual modules without starting a GUI. Mac GUI/GPU behavior, real-model editing/cutting, connector placement, slicing, printing, color accuracy, and TD calibration are not verified by these build checks. Windows GUI results are not Mac GUI results.

The manual workflow uses one standard `macos-15` arm64 runner with Xcode 16.2. Its concurrency group is shared with the older Mac workflows, and its artifacts remain available for one day. It does not change releases, download pages, or billing settings. The established `cm240_build_macos.sh`, helper pins, and cache keys are deliberately reused for compatible dependency builds; dev3-R8 packaging is separate. App cache hits still require the exact full source-packet SHA256.
