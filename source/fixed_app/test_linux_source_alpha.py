from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[2]
INSTALLER = REPOSITORY / "INSTALL_LINUX_SOURCE_ALPHA.sh"
LAUNCHER = REPOSITORY / "RUN_LINUX_SOURCE_ALPHA.sh"
GUIDE = REPOSITORY / "LINUX_SOURCE_ALPHA_EN.md"


def _wsl_has_test_distribution() -> bool:
    """The Windows wsl.exe launcher can exist without WSL or a distro installed."""
    try:
        probe = subprocess.run(
            ["wsl.exe", "--list", "--quiet"],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if probe.returncode != 0:
        return False
    encoding = "utf-16-le" if b"\x00" in probe.stdout else "utf-8-sig"
    names = probe.stdout.decode(encoding, errors="replace").splitlines()
    return "Ubuntu-22.04" in {name.strip().lstrip("\ufeff") for name in names}


class LinuxSourceAlphaTests(unittest.TestCase):
    def test_wsl_probe_requires_the_actual_test_distribution(self) -> None:
        for code, output, expected in (
            (1, "WSL is not installed", False),
            (0, "Ubuntu-24.04\n", False),
            (0, "Ubuntu-22.04\n", True),
        ):
            with self.subTest(code=code, output=output), mock.patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], code, output.encode("utf-16-le"), b""
                ),
            ):
                self.assertEqual(_wsl_has_test_distribution(), expected)

    def test_required_files_exist_and_use_lf(self) -> None:
        for path in (INSTALLER, LAUNCHER, GUIDE):
            self.assertTrue(path.is_file(), path)
            self.assertNotIn(b"\r\n", path.read_bytes(), path)

    def test_installer_is_fail_closed_and_hash_pinned(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('PYTHON_VERSION="3.13.14"', text)
        self.assertIn("--managed-python", text)
        self.assertIn("--require-hashes", text)
        self.assertIn("--only-binary=:all:", text)
        self.assertIn("--strict", text)
        self.assertIn("--self-test", text)
        self.assertIn("--linux-alpha-self-test", text)
        self.assertIn("dpkg-query", text)
        self.assertNotIn("sudo apt-get install", text.split("cat >&2", 1)[0])
        self.assertNotIn("curl ", text)
        self.assertNotIn("wget ", text)

    def test_launcher_uses_only_the_local_environment(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn(".venv-linux-source-alpha/bin/python", text)
        self.assertIn("TripoSpectrumMapper_fixed.py", text)
        self.assertIn('exec "$PYTHON_BIN" "$ENTRYPOINT" "$@"', text)
        self.assertNotIn("python3 ", text)

    def test_guide_discloses_source_backed_alpha_boundaries(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        for phrase in (
            "not a standalone frozen Linux binary",
            "Ubuntu 22.04 or newer",
            "Flat Four remains experimental",
            "third-party binary/source/relink compliance audit",
            "https://chromamatter.app/feedback/linux",
        ):
            self.assertIn(phrase, normalized)

    @unittest.skipUnless(
        sys.platform == "win32" and shutil.which("wsl.exe") is not None,
        "WSL is unavailable",
    )
    def test_shell_syntax_when_wsl_is_available(self) -> None:
        if not _wsl_has_test_distribution():
            self.skipTest("WSL Ubuntu-22.04 is not installed")
        for path in (INSTALLER, LAUNCHER):
            resolved = path.resolve()
            drive = resolved.drive.rstrip(":").lower()
            linux_path = f"/mnt/{drive}/{resolved.as_posix()[3:]}"
            completed = subprocess.run(
                ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-n", linux_path],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
