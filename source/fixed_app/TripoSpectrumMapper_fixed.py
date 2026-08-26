from __future__ import annotations

import sys

if "--macos-alpha-self-test" in sys.argv[1:]:
    # Keep the packaged macOS admission probe independent from application
    # hotfix imports.  In particular, PyMeshLab and ModernGL must be loaded by
    # the gate itself so their native/plugin failures become explicit JSON
    # checks instead of unrelated startup output.
    from spectrum_mapper import cli as _macos_alpha_cli

    main = _macos_alpha_cli.main
else:
    import spectrum_mapper_hotfix
    from surface_resolution_hotfix import apply_surface_resolution_hotfix
    from final_shading_hotfix import install_export_adaptive_hotfix

    # Installation order is part of the frozen-release contract.  The portable
    # Generic PLA writer is installed by spectrum_mapper_hotfix first, surface
    # validation wraps that writer second, and export-adaptive shading remains
    # the outermost writer wrapper.
    apply_surface_resolution_hotfix()
    install_export_adaptive_hotfix()

    from spectrum_mapper.cli import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
