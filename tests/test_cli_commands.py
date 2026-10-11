from __future__ import annotations

import unittest
import os
from pathlib import Path
from unittest.mock import patch

from connections.cli_commands import (
    API_BRIDGE_CLI,
    PROJECT_DIR,
    api_bridge_install_command,
    tiktok_command,
)


class CliCommandTests(unittest.TestCase):
    def test_tiktok_command_invokes_existing_module_cli(self) -> None:
        command = tiktok_command("@creator")
        self.assertEqual(
            command[1:],
            ["-u", "-m", "connections.tiktok", "@creator"],
        )

    def test_installer_command_uses_cli_flags(self) -> None:
        command = api_bridge_install_command(
            "1.21.11",
            "fabric",
            Path("D:/Minecraft/instance/mods"),
            force=True,
        )
        self.assertEqual(command[1], "-u")
        self.assertEqual(Path(command[2]), API_BRIDGE_CLI)
        self.assertEqual(
            command[3:],
            [
                "--mcversion",
                "1.21.11",
                "--modloader",
                "fabric",
                "--dir",
                os.fspath(Path("D:/Minecraft/instance/mods")),
                "--force",
            ],
        )
        self.assertTrue(API_BRIDGE_CLI.is_relative_to(PROJECT_DIR))

    def test_cli_builders_reject_missing_arguments(self) -> None:
        with self.assertRaises(ValueError):
            tiktok_command(" ")
        with self.assertRaises(ValueError):
            api_bridge_install_command("", "fabric", "mods")
        with self.assertRaises(ValueError):
            api_bridge_install_command("1.21.11", " ", "mods")

    def test_frozen_commands_use_the_bundled_worker_executable(self) -> None:
        worker = Path("C:/Program Files/Free2Play/Free2PlayWorker.exe")
        with (
            patch("connections.cli_commands.sys.frozen", True, create=True),
            patch("connections.cli_commands.sys.executable", str(worker.parent / "Free2Play.exe")),
        ):
            tiktok = tiktok_command("creator")
            installer = api_bridge_install_command(
                "1.21.11",
                "fabric",
                "C:/Minecraft/mods",
            )

        self.assertEqual(Path(tiktok[0]), worker)
        self.assertEqual(tiktok[1:], ["--f2p-worker-tiktok", "creator"])
        self.assertEqual(Path(installer[0]), worker)
        self.assertEqual(
            installer[1:],
            [
                "--f2p-worker-api-bridge",
                "--mcversion",
                "1.21.11",
                "--modloader",
                "fabric",
                "--dir",
                "C:/Minecraft/mods",
            ],
        )


if __name__ == "__main__":
    unittest.main()
