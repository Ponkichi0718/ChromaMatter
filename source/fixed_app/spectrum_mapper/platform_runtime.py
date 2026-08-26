"""Small platform boundary for desktop paths and application launching.

The geometry and 3MF code stays platform-neutral.  This module contains the
few desktop operations that genuinely differ between Windows and macOS so the
Windows release path remains unchanged while the macOS alpha can be built and
tested independently.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import sys
from typing import Any


WINDOWS_LEGACY_PROFILE_DIRECTORY_NAME = "TripoSpectrumMapper"
PORTABLE_PROFILE_DIRECTORY_NAME = "ChromaMatter"
APPLICATION_DATA_DIRECTORY_ENV = "CHROMAMATTER_DATA_DIRECTORY"


def _platform_name(value: str | None = None) -> str:
    return str(sys.platform if value is None else value).strip().lower()


def application_data_directory(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
) -> Path:
    """Return the per-user ChromaMatter data directory for this platform.

    The historical ``TripoSpectrumMapper`` directory name is retained so
    existing Windows settings and owned-filament inventories keep working.
    """

    platform_value = _platform_name(platform_name)
    environment = os.environ if environ is None else environ
    home_directory = Path.home() if home is None else Path(home)
    explicit_directory = str(
        environment.get(APPLICATION_DATA_DIRECTORY_ENV, "")
    ).strip()
    if explicit_directory:
        explicit_path = Path(explicit_directory).expanduser()
        target_absolute = (
            PureWindowsPath(explicit_directory).is_absolute()
            if platform_value.startswith("win")
            else PurePosixPath(explicit_directory).is_absolute()
        )
        if not target_absolute:
            raise ValueError(
                f"{APPLICATION_DATA_DIRECTORY_ENV} must be an absolute path"
            )
        # In production the requested platform and host always match. Keeping
        # the lexical target path in cross-platform unit tests avoids letting
        # the test host reinterpret a foreign absolute-path syntax.
        if platform_value == _platform_name():
            return explicit_path.resolve(strict=False)
        return explicit_path
    if platform_value.startswith("win"):
        configured = str(environment.get("APPDATA", "")).strip()
        base = (
            Path(configured)
            if configured
            else home_directory / "AppData" / "Roaming"
        )
    elif platform_value == "darwin":
        base = home_directory / "Library" / "Application Support"
    else:
        configured = str(environment.get("XDG_CONFIG_HOME", "")).strip()
        base = Path(configured) if configured else home_directory / ".config"
    directory_name = (
        WINDOWS_LEGACY_PROFILE_DIRECTORY_NAME
        if platform_value.startswith("win")
        else PORTABLE_PROFILE_DIRECTORY_NAME
    )
    return base / directory_name


def application_window_title(
    base_title: str,
    *,
    platform_name: str | None = None,
) -> str:
    """Mark only the macOS build as an alpha without changing its version."""

    if _platform_name(platform_name) == "darwin":
        return f"{base_title} — macOS alpha"
    return str(base_title)


def open_folder_command(
    folder: str | os.PathLike[str],
    *,
    platform_name: str | None = None,
) -> tuple[str, ...] | None:
    """Return the non-Windows folder-open command.

    Windows deliberately returns ``None`` because ShellExecute via
    :func:`os.startfile` preserves the established Explorer behaviour.
    """

    platform_value = _platform_name(platform_name)
    target = os.fspath(folder)
    if platform_value.startswith("win"):
        return None
    if platform_value == "darwin":
        return ("open", target)
    return ("xdg-open", target)


def open_folder(
    folder: str | os.PathLike[str],
    *,
    platform_name: str | None = None,
    startfile: Callable[[Any], Any] | None = None,
    popen: Callable[..., Any] | None = None,
) -> None:
    """Open *folder* in Finder, Explorer, or the desktop file manager."""

    platform_value = _platform_name(platform_name)
    target = Path(folder)
    if platform_value.startswith("win"):
        opener = startfile or getattr(os, "startfile", None)
        if opener is None:
            raise OSError("Windows folder opener is unavailable")
        opener(target)
        return
    launcher = subprocess.Popen if popen is None else popen
    command = open_folder_command(folder, platform_name=platform_value)
    if command is None:  # Defensive: the Windows path returned above.
        raise OSError("Folder-open command is unavailable")
    launcher(list(command))


def snapmaker_orca_candidates(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
    applications_directory: str | os.PathLike[str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> tuple[Path, ...]:
    """Return deterministic Snapmaker Orca application candidates."""

    platform_value = _platform_name(platform_name)
    environment = os.environ if environ is None else environ
    home_directory = Path.home() if home is None else Path(home)
    executable_finder = shutil.which if which is None else which
    candidates: list[Path] = []
    if platform_value == "darwin":
        applications = (
            Path("/Applications")
            if applications_directory is None
            else Path(applications_directory)
        )
        for directory in (applications, home_directory / "Applications"):
            candidates.extend(
                (
                    directory / "Snapmaker Orca.app",
                    directory / "Snapmaker_Orca.app",
                )
            )
        command_names: Sequence[str] = (
            "snapmaker-orca",
            "Snapmaker Orca",
            "Snapmaker_Orca",
        )
    elif platform_value.startswith("win"):
        program_files = Path(
            str(environment.get("ProgramFiles", r"C:\Program Files"))
        )
        local_app_data_value = str(environment.get("LOCALAPPDATA", "")).strip()
        local_app_data = Path(local_app_data_value) if local_app_data_value else None
        candidates.extend(
            (
                program_files / "Snapmaker_Orca" / "snapmaker-orca.exe",
                program_files / "Snapmaker Orca" / "Snapmaker Orca.exe",
            )
        )
        if local_app_data is not None:
            candidates.extend(
                (
                    local_app_data
                    / "Programs"
                    / "Snapmaker Orca"
                    / "Snapmaker Orca.exe",
                    local_app_data
                    / "Snapmaker Orca"
                    / "Snapmaker Orca.exe",
                )
            )
        command_names = (
            "Snapmaker Orca.exe",
            "snapmaker-orca.exe",
            "Snapmaker_Orca.exe",
        )
    else:
        command_names = ("snapmaker-orca", "Snapmaker_Orca")

    discovered: list[Path] = []
    for name in command_names:
        located = executable_finder(name)
        if located:
            discovered.append(Path(located))

    result: list[Path] = []
    seen: set[str] = set()
    for candidate in (*discovered, *candidates):
        key = str(candidate)
        if platform_value.startswith("win"):
            key = key.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return tuple(result)


def find_snapmaker_orca(
    *,
    platform_name: str | None = None,
    **candidate_options: Any,
) -> Path | None:
    """Return the first existing executable or macOS application bundle."""

    platform_value = _platform_name(platform_name)
    for candidate in snapmaker_orca_candidates(
        platform_name=platform_value,
        **candidate_options,
    ):
        if platform_value == "darwin" and candidate.suffix.casefold() == ".app":
            if candidate.is_dir():
                return candidate
        elif candidate.is_file():
            return candidate
    return None


def snapmaker_orca_launch_command(
    application: str | os.PathLike[str],
    *,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    """Return the direct, shell-free command for one selected installation."""

    platform_value = _platform_name(platform_name)
    target = Path(application)
    if platform_value == "darwin" and target.suffix.casefold() == ".app":
        return ("open", str(target))
    return (str(target),)


def launch_snapmaker_orca(
    application: str | os.PathLike[str],
    *,
    platform_name: str | None = None,
    popen: Callable[..., Any] | None = None,
) -> None:
    """Launch the selected Snapmaker Orca install without invoking a shell."""

    platform_value = _platform_name(platform_name)
    target = Path(application)
    command = snapmaker_orca_launch_command(
        target,
        platform_name=platform_value,
    )
    launcher = subprocess.Popen if popen is None else popen
    if platform_value == "darwin" and target.suffix.casefold() == ".app":
        launcher(list(command))
    else:
        launcher(list(command), cwd=str(target.parent))
