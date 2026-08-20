from __future__ import annotations

import unittest
from unittest import mock

from spectrum_mapper.cli import _color_depth_export_smoke
from spectrum_mapper import (
    color_depth_exact_partition,
    color_depth_head_geometry,
    radial_export,
)


class PackagedColorDepthSmokeTests(unittest.TestCase):
    def test_exact_partition_manifold_writer_and_reopen_smoke(self) -> None:
        with (
            mock.patch.object(
                color_depth_exact_partition,
                "build_conforming_color_depth_partition",
                wraps=color_depth_exact_partition.build_conforming_color_depth_partition,
            ) as exact_provider,
            mock.patch.object(
                color_depth_head_geometry,
                "manifoldize_labeled_tetrahedra",
                wraps=color_depth_head_geometry.manifoldize_labeled_tetrahedra,
            ) as manifoldizer,
            mock.patch.object(
                radial_export,
                "write_radial_3mf_atomic",
                wraps=radial_export.write_radial_3mf_atomic,
            ) as writer,
            mock.patch.object(
                radial_export,
                "validate_radial_3mf",
                wraps=radial_export.validate_radial_3mf,
            ) as reopen_validator,
        ):
            ok, status = _color_depth_export_smoke()
        self.assertTrue(ok, status)
        self.assertEqual(status, "ok")
        exact_provider.assert_called_once()
        manifoldizer.assert_called_once()
        writer.assert_called_once()
        # The atomic writer validates its temporary archive before publish;
        # the smoke then independently reopens the published path.
        self.assertEqual(reopen_validator.call_count, 2)
        self.assertTrue(
            str(reopen_validator.call_args_list[-1].args[0]).endswith(
                "color-depth-self-test.3mf"
            )
        )


if __name__ == "__main__":
    unittest.main()
