from __future__ import annotations

import sys

import spectrum_mapper_hotfix
from surface_resolution_hotfix import apply_surface_resolution_hotfix
from final_shading_hotfix import install_export_adaptive_hotfix


# Installation order is part of the frozen-release contract.  The portable
# Generic PLA writer is installed by spectrum_mapper_hotfix first, surface
# validation wraps that writer second, and export-adaptive shading remains the
# outermost writer wrapper.
apply_surface_resolution_hotfix()
install_export_adaptive_hotfix()

from spectrum_mapper.cli import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
