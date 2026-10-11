from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import api_bridge_auth
from api_bridge_auth import find_api_bridge_token


TOKEN = "0123456789abcdef" * 4
LOG_LINE = (
    "INFO: mcapi.key not provided! Generated random auth token: "
    f"{TOKEN}\n"
)


class FindApiBridgeTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.log_path = Path(self.temp_dir.name) / "latest.log"

    def test_finds_64_character_hex_token(self) -> None:
        self.log_path.write_text(LOG_LINE, encoding="utf-8")
        self.assertEqual(find_api_bridge_token(self.log_path), TOKEN)

    def test_returns_last_token_when_log_has_multiple_starts(self) -> None:
        second_token = "fedcba9876543210" * 4
        self.log_path.write_text(
            LOG_LINE
            + "mcapi.key not provided! Generated random auth token: "
            + second_token,
            encoding="utf-8",
        )
        self.assertEqual(find_api_bridge_token(self.log_path), second_token)

    def test_rejects_wrong_length_and_non_hex_tokens(self) -> None:
        self.log_path.write_text(
            "mcapi.key not provided! Generated random auth token: "
            + "a" * 63
            + "\nmcapi.key not provided! Generated random auth token: "
            + "g" * 64,
            encoding="utf-8",
        )
        self.assertIsNone(find_api_bridge_token(self.log_path))

    def test_rejects_a_65_character_hex_value(self) -> None:
        self.log_path.write_text(
            "mcapi.key not provided! Generated random auth token: "
            + "a" * 65,
            encoding="utf-8",
        )
        self.assertIsNone(find_api_bridge_token(self.log_path))

    def test_missing_and_empty_files_return_none(self) -> None:
        self.assertIsNone(find_api_bridge_token(self.log_path))
        self.log_path.touch()
        self.assertIsNone(find_api_bridge_token(self.log_path))

    def test_permission_error_returns_none(self) -> None:
        with patch.object(Path, "open", side_effect=PermissionError):
            self.assertIsNone(find_api_bridge_token(self.log_path))

    def test_retries_once_if_log_changes_during_read(self) -> None:
        self.log_path.write_text(LOG_LINE, encoding="utf-8")
        original_fstat = api_bridge_auth.os.fstat
        changed = False

        def changing_fstat(file_descriptor: int):
            nonlocal changed
            result = original_fstat(file_descriptor)
            if not changed:
                changed = True
                self.log_path.write_text(LOG_LINE + "new line\n", encoding="utf-8")
            return result

        with patch.object(api_bridge_auth.os, "fstat", changing_fstat):
            self.assertEqual(find_api_bridge_token(self.log_path), TOKEN)

    def test_json_cli_does_not_expose_token_by_default(self) -> None:
        self.log_path.write_text(LOG_LINE, encoding="utf-8")
        output = StringIO()
        with redirect_stdout(output):
            exit_code = api_bridge_auth.main(
                ["--log", str(self.log_path), "--json"]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["found"])
        self.assertIsNone(result["token"])
        self.assertNotIn(TOKEN, output.getvalue())

    def test_show_token_requires_explicit_flag(self) -> None:
        self.log_path.write_text(LOG_LINE, encoding="utf-8")
        output = StringIO()
        with redirect_stdout(output):
            exit_code = api_bridge_auth.main(
                ["--log", str(self.log_path), "--json", "--show-token"]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["token"], TOKEN)

    def test_instance_dir_resolves_its_own_log(self) -> None:
        instance_dir = Path(self.temp_dir.name) / "modded-instance"
        log_path = instance_dir / "logs" / "latest.log"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(LOG_LINE, encoding="utf-8")
        output = StringIO()

        with redirect_stdout(output):
            exit_code = api_bridge_auth.main(
                ["--instance-dir", str(instance_dir), "--json"]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["log_path"], str(log_path))

    def test_minecraft_dir_resolves_logs_latest_log(self) -> None:
        log_path = Path(self.temp_dir.name) / "logs" / "latest.log"
        log_path.parent.mkdir()
        log_path.write_text(LOG_LINE, encoding="utf-8")
        output = StringIO()

        with redirect_stdout(output):
            exit_code = api_bridge_auth.main(
                ["--minecraft-dir", self.temp_dir.name, "--json"]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["log_path"], str(log_path))

    def test_wait_can_be_cancelled_with_ctrl_c(self) -> None:
        self.log_path.write_text("Minecraft starting\n", encoding="utf-8")
        output = StringIO()
        with (
            redirect_stdout(output),
            redirect_stderr(StringIO()),
            patch.object(api_bridge_auth.time, "sleep", side_effect=KeyboardInterrupt),
        ):
            exit_code = api_bridge_auth.main(
                ["--log", str(self.log_path), "--wait", "--json"]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 130)
        self.assertEqual(result["status"], "wait_cancelled")
        self.assertFalse(result["found"])

    def test_default_path_uses_appdata(self) -> None:
        with patch.dict(os.environ, {"APPDATA": self.temp_dir.name}):
            self.assertEqual(
                api_bridge_auth._default_log_path(),
                Path(self.temp_dir.name) / ".minecraft" / "logs" / "latest.log",
            )


if __name__ == "__main__":
    unittest.main()
