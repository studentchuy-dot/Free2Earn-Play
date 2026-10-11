from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from connections.minecraft_api import (
    MinecraftApiError,
    execute_command,
    execute_command_sequence,
    test_connection,
)


class FakeResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args
        return None

    def read(self, size: int = -1) -> bytes:
        del size
        return b'{"ok":true}'


class MinecraftApiTests(unittest.TestCase):
    @patch("connections.minecraft_api.build_opener")
    def test_connection_uses_documented_index_and_bearer_header(
        self, mocked: MagicMock
    ) -> None:
        mocked.return_value.open.return_value = FakeResponse()
        response = test_connection("secret-token")
        request = mocked.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:25566/api/")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")
        self.assertEqual(response.status, 200)

    @patch("connections.minecraft_api.build_opener")
    def test_command_uses_documented_path_and_body(
        self, mocked: MagicMock
    ) -> None:
        mocked.return_value.open.return_value = FakeResponse()
        execute_command("secret-token", "say Hello")
        request = mocked.return_value.open.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:25566/api/command",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"command": "say Hello"},
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")

    def test_missing_token_and_bad_url_are_reported(self) -> None:
        with self.assertRaises(MinecraftApiError):
            test_connection("")
        with self.assertRaises(MinecraftApiError):
            test_connection("token", "not a URL")
        with self.assertRaisesRegex(MinecraftApiError, "dirección local"):
            test_connection("token", "https://example.com")

    @patch(
        "connections.minecraft_api.build_opener",
        side_effect=HTTPError("http://localhost/api/", 401, "Unauthorized", {}, io.BytesIO()),
    )
    def test_auth_failure_does_not_echo_token(self, _mocked: MagicMock) -> None:
        self.assertIsNotNone(_mocked)
        with self.assertRaisesRegex(MinecraftApiError, "HTTP 401") as raised:
            test_connection("do-not-print-me")
        self.assertNotIn("do-not-print-me", str(raised.exception))

    @patch(
        "connections.minecraft_api.build_opener",
        side_effect=URLError("offline"),
    )
    def test_connection_error_is_actionable(self, _mocked: MagicMock) -> None:
        self.assertIsNotNone(_mocked)
        with self.assertRaisesRegex(MinecraftApiError, "Minecraft"):
            test_connection("token")

    @patch("connections.minecraft_api.execute_command")
    def test_command_sequence_is_ordered_and_stops_at_first_error(
        self, mocked: MagicMock
    ) -> None:
        mocked.side_effect = [
            FakeResponse(),
            MinecraftApiError("bad command"),
            FakeResponse(),
        ]

        outcomes = execute_command_sequence(
            "token",
            ["say first", "not_a_command", "say never"],
        )

        self.assertEqual([outcome.command for outcome in outcomes], [
            "say first",
            "not_a_command",
        ])
        self.assertIsNotNone(outcomes[0].response)
        self.assertEqual(outcomes[1].error, "bad command")
        self.assertEqual(mocked.call_count, 2)

    @patch("connections.minecraft_api.build_opener")
    def test_command_rejects_api_json_failure_even_when_http_is_200(
        self, mocked: MagicMock
    ) -> None:
        response = FakeResponse()
        response.read = lambda _size=-1: (
            b'{"success":false,"message":"Invalid command"}'
        )
        mocked.return_value.open.return_value = response

        outcomes = execute_command_sequence("token", ["not_a_command"])

        self.assertEqual(outcomes[0].error, "Invalid command")
        self.assertEqual(outcomes[0].error_status, 200)
        self.assertIn('"success":false', outcomes[0].error_body)


if __name__ == "__main__":
    unittest.main()
