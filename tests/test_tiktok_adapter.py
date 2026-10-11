from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace

from TikTokLive.client.web.routes.fetch_gift_list import FailedFetchGiftListError

from connections.tiktok import create_client, run_client


class TikTokAdapterTests(unittest.TestCase):
    def test_comment_event_is_json_and_keeps_message_id(self) -> None:
        lines: list[str] = []
        client = create_client("@creator", lines.append)
        user = SimpleNamespace(
            id=42,
            id_str="42",
            display_id="short_name",
            special_id="",
            nickname="Display name",
            avatar_thumb=None,
            verified=False,
        )
        event = SimpleNamespace(
            user=user,
            content="hello",
            common=SimpleNamespace(msg_id=987654),
        )
        callback = next(iter(client._events["CommentEvent"]))
        asyncio.run(callback(event))

        record = json.loads(lines[0])
        self.assertEqual(record["event"], "comment")
        self.assertEqual(record["event_id"], "987654")
        self.assertEqual(record["userid"], "42")
        self.assertEqual(record["shortname"], "short_name")
        self.assertEqual(record["user"], "Display name")
        self.assertEqual(record["text"], "hello")
        client._asyncio_loop.close()

    def test_like_event_exposes_increment_and_total_count(self) -> None:
        lines: list[str] = []
        client = create_client("creator", lines.append)
        event = SimpleNamespace(
            user=None,
            count=7,
            total=107,
            common=SimpleNamespace(msg_id=123),
        )
        callback = next(iter(client._events["LikeEvent"]))
        asyncio.run(callback(event))

        record = json.loads(lines[0])
        self.assertEqual(record["event"], "like")
        self.assertEqual(record["count"], 7)
        self.assertEqual(record["amount"], 7)
        self.assertEqual(record["total"], 107)
        client._asyncio_loop.close()

    def test_connect_emits_tiktok_gift_catalog(self) -> None:
        lines: list[str] = []
        client = create_client("creator", lines.append)
        client._gift_info = {
            "gifts": [
                {"id": 5655, "name": "Rose", "diamond_count": 1},
                {"gift_id": "9001", "name": "Galaxy"},
                {"id": 2, "name": ""},
            ]
        }
        event = SimpleNamespace(room_id=123, common=None, user=None)
        callback = next(iter(client._events["ConnectEvent"]))
        asyncio.run(callback(event))

        records = [json.loads(line) for line in lines]
        self.assertEqual(records[0]["event"], "connect")
        self.assertEqual(records[1]["event"], "gift_catalog")
        self.assertEqual(
            records[1]["gifts"],
            [
                {"name": "Rose", "gift_id": "5655", "diamond_count": 1},
                {"name": "Galaxy", "gift_id": "9001"},
            ],
        )
        client._asyncio_loop.close()

    def test_gift_list_error_does_not_prevent_live_connection_attempt(self) -> None:
        class Client:
            calls: list[dict[str, bool]] = []

            def run(self, **kwargs: bool) -> None:
                self.calls.append(kwargs)
                if kwargs.get("fetch_gift_info"):
                    raise FailedFetchGiftListError()

        client = Client()
        lines: list[str] = []
        run_client(client, lines.append)

        self.assertEqual(client.calls, [{"fetch_gift_info": True}, {}])
        record = json.loads(lines[0])
        self.assertEqual(record["event"], "gift_catalog_error")


if __name__ == "__main__":
    unittest.main()
