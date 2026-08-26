from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys


FIXED_APP = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXED_APP))

from spectrum_mapper import platform_runtime
from spectrum_mapper import volume_partition


class ApplicationDataPathTests(unittest.TestCase):
    def test_explicit_application_data_directory_is_platform_independent(self) -> None:
        result = platform_runtime.application_data_directory(
            platform_name="darwin",
            environ={
                platform_runtime.APPLICATION_DATA_DIRECTORY_ENV: (
                    "/tmp/chromamatter-isolated-profile"
                )
            },
            home=Path("/Users/must-not-be-used"),
        )

        self.assertEqual(
            result.resolve(strict=False),
            Path("/tmp/chromamatter-isolated-profile").resolve(strict=False),
        )

    def test_relative_application_data_override_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an absolute path"):
            platform_runtime.application_data_directory(
                platform_name="darwin",
                environ={
                    platform_runtime.APPLICATION_DATA_DIRECTORY_ENV: (
                        "relative/profile"
                    )
                },
                home=Path("/Users/must-not-be-used"),
            )

    def test_windows_keeps_legacy_profile_directory(self) -> None:
        result = platform_runtime.application_data_directory(
            platform_name="win32",
            environ={"APPDATA": r"C:\Users\test\AppData\Roaming"},
            home=Path(r"C:\Users\test"),
        )

        self.assertEqual(
            result,
            Path(r"C:\Users\test\AppData\Roaming") / "TripoSpectrumMapper",
        )

    def test_macos_uses_application_support(self) -> None:
        result = platform_runtime.application_data_directory(
            platform_name="darwin",
            environ={"APPDATA": "/must/not/be/used"},
            home=Path("/Users/tester"),
        )

        self.assertEqual(
            result,
            Path("/Users/tester/Library/Application Support/ChromaMatter"),
        )

    def test_only_macos_title_is_marked_alpha(self) -> None:
        base = "ChromaMatter — AI Model Print Studio 0.8beta (r32.2)"

        self.assertEqual(
            platform_runtime.application_window_title(
                base, platform_name="win32"
            ),
            base,
        )
        self.assertEqual(
            platform_runtime.application_window_title(
                base, platform_name="darwin"
            ),
            f"{base} — macOS alpha",
        )


class DesktopLaunchTests(unittest.TestCase):
    def test_open_folder_preserves_windows_startfile(self) -> None:
        startfile = Mock()
        popen = Mock()

        platform_runtime.open_folder(
            Path(r"C:\output"),
            platform_name="win32",
            startfile=startfile,
            popen=popen,
        )

        startfile.assert_called_once_with(Path(r"C:\output"))
        popen.assert_not_called()

    def test_open_folder_uses_finder_on_macos(self) -> None:
        popen = Mock()

        platform_runtime.open_folder(
            "/Users/tester/output",
            platform_name="darwin",
            popen=popen,
        )

        popen.assert_called_once_with(["open", "/Users/tester/output"])

    def test_finds_and_launches_macos_application_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            applications = temporary_path / "Applications"
            bundle = applications / "Snapmaker Orca.app"
            bundle.mkdir(parents=True)

            found = platform_runtime.find_snapmaker_orca(
                platform_name="darwin",
                home=temporary_path / "home",
                applications_directory=applications,
                which=lambda _name: None,
            )

            self.assertEqual(found, bundle)
            popen = Mock()
            platform_runtime.launch_snapmaker_orca(
                found,
                platform_name="darwin",
                popen=popen,
            )
            popen.assert_called_once_with(["open", str(bundle)])

    def test_windows_orca_command_remains_direct(self) -> None:
        executable = Path(r"C:\Program Files\Snapmaker_Orca\snapmaker-orca.exe")
        popen = Mock()

        platform_runtime.launch_snapmaker_orca(
            executable,
            platform_name="win32",
            popen=popen,
        )

        popen.assert_called_once_with(
            [str(executable)], cwd=str(executable.parent)
        )


class MacTetWildLoaderTests(unittest.TestCase):
    def test_loads_abi3_so_with_package_dylibs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "pytetwild"
            libraries = package / ".dylibs"
            libraries.mkdir(parents=True)
            wrapper = package / "PyfTetWildWrapper.abi3.so"
            wrapper.write_bytes(b"test extension placeholder")
            dylib = libraries / "libgmp.10.dylib"
            dylib.write_bytes(b"test dylib placeholder")
            native_module = object()
            loader = SimpleNamespace(exec_module=Mock())
            module_spec = SimpleNamespace(loader=loader)
            package_spec = SimpleNamespace(
                submodule_search_locations=(str(package),)
            )
            dylib_handle = object()

            with (
                patch.object(volume_partition, "_TETWILD_WRAPPER", None),
                patch.object(volume_partition, "_DLL_HANDLES", []),
                patch.object(volume_partition.sys, "platform", "darwin"),
                patch.object(
                    volume_partition.importlib.util,
                    "find_spec",
                    return_value=package_spec,
                ),
                patch.object(
                    volume_partition.importlib.machinery,
                    "EXTENSION_SUFFIXES",
                    [".abi3.so", ".so"],
                ),
                patch.object(
                    volume_partition.ctypes,
                    "CDLL",
                    return_value=dylib_handle,
                ) as cdll,
                patch.object(
                    volume_partition.importlib.util,
                    "spec_from_file_location",
                    return_value=module_spec,
                ) as spec_from_file,
                patch.object(
                    volume_partition.importlib.util,
                    "module_from_spec",
                    return_value=native_module,
                ),
            ):
                loaded = volume_partition._load_tetwild_wrapper()

            self.assertIs(loaded, native_module)
            cdll.assert_called_once_with(
                str(dylib),
                mode=getattr(volume_partition.ctypes, "RTLD_GLOBAL", 0),
            )
            spec_from_file.assert_called_once_with(
                "PyfTetWildWrapper", wrapper
            )
            loader.exec_module.assert_called_once_with(native_module)

    def test_windows_loader_keeps_pyd_and_sibling_dll_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "pytetwild"
            libraries = root / "pytetwild.libs"
            package.mkdir()
            libraries.mkdir()
            wrapper = package / "PyfTetWildWrapper.abi3.pyd"
            wrapper.write_bytes(b"test extension placeholder")
            native_module = object()
            loader = SimpleNamespace(exec_module=Mock())
            module_spec = SimpleNamespace(loader=loader)
            package_spec = SimpleNamespace(
                submodule_search_locations=(str(package),)
            )
            directory_handle = object()

            with (
                patch.object(volume_partition, "_TETWILD_WRAPPER", None),
                patch.object(volume_partition, "_DLL_HANDLES", []),
                patch.object(volume_partition.sys, "platform", "win32"),
                patch.object(
                    volume_partition.importlib.util,
                    "find_spec",
                    return_value=package_spec,
                ),
                patch.object(
                    volume_partition.importlib.machinery,
                    "EXTENSION_SUFFIXES",
                    [".abi3.pyd", ".pyd"],
                ),
                patch.object(
                    volume_partition.os,
                    "add_dll_directory",
                    return_value=directory_handle,
                    create=True,
                ) as add_dll_directory,
                patch.object(
                    volume_partition.importlib.util,
                    "spec_from_file_location",
                    return_value=module_spec,
                ) as spec_from_file,
                patch.object(
                    volume_partition.importlib.util,
                    "module_from_spec",
                    return_value=native_module,
                ),
            ):
                loaded = volume_partition._load_tetwild_wrapper()

            self.assertIs(loaded, native_module)
            add_dll_directory.assert_called_once_with(str(libraries))
            spec_from_file.assert_called_once_with(
                "PyfTetWildWrapper", wrapper
            )
            loader.exec_module.assert_called_once_with(native_module)


if __name__ == "__main__":
    unittest.main()
