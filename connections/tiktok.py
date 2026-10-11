"""Conexión a TikTok LIVE con salida de eventos JSON Lines.

Uso:
    python -m connections.tiktok nombre_de_usuario

Cada línea escrita en stdout es un objeto JSON independiente.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable

from TikTokLive import TikTokLiveClient
from TikTokLive.client.web.routes.fetch_gift_list import FailedFetchGiftListError
from TikTokLive.events import (
    CommentEvent,
    ConnectEvent,
    DisconnectEvent,
    FollowEvent,
    GiftEvent,
    JoinEvent,
    LikeEvent,
    LiveEndEvent,
    ShareEvent,
)

JsonLineWriter = Callable[[str], None]


def _gift_catalog_items(
    gift_info: Mapping[str, Any] | None,
) -> list[dict[str, object]]:
    if gift_info is None:
        return []
    gifts = gift_info.get("gifts", [])
    if isinstance(gifts, Mapping):
        items = gifts.values()
    elif isinstance(gifts, list):
        items = gifts
    else:
        return []

    catalog: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        record: dict[str, object] = {"name": name.strip()}
        gift_id = item.get("id", item.get("gift_id"))
        if gift_id is not None:
            record["gift_id"] = str(gift_id)
        diamond_count = item.get("diamond_count")
        if isinstance(diamond_count, (int, float)) and not isinstance(
            diamond_count, bool
        ):
            record["diamond_count"] = diamond_count
        catalog.append(record)
    return catalog


def _profile(user: object | None) -> dict[str, object | None]:
    if user is None:
        return {
            "userid": None,
            "shortname": None,
            "user": None,
            "avatar": None,
            "verified": None,
        }

    user_id = getattr(user, "id_str", None) or getattr(user, "id", None)
    display_name = getattr(user, "display_id", None) or getattr(
        user, "special_id", None
    )
    avatar = getattr(user, "avatar_thumb", None)
    avatar_urls = getattr(avatar, "url_list", None)

    return {
        "userid": str(user_id) if user_id is not None else None,
        "shortname": display_name,
        "user": getattr(user, "nickname", None),
        "avatar": avatar_urls[0] if avatar_urls else None,
        "verified": getattr(user, "verified", None),
    }


def create_client(
    unique_id: str, writer: JsonLineWriter | None = None
) -> TikTokLiveClient:
    """Crea un cliente y registra los eventos JSON de LIVE."""
    username = unique_id.strip().removeprefix("@")
    if not username:
        raise ValueError("Debes proporcionar el nombre de usuario de TikTok.")

    write_line = writer or (lambda line: print(line, flush=True))
    client = TikTokLiveClient(unique_id=username)
    room_id: int | None = None

    def emit(
        event_name: str,
        event: object | None = None,
        *,
        text: str | None = None,
        amount: int | None = None,
        event_type: str | None = None,
        **details: object,
    ) -> None:
        data: dict[str, object | None] = {
            "event": event_name,
            "event_id": (
                str(message_id)
                if (
                    message_id := getattr(
                        getattr(event, "common", None), "msg_id", None
                    )
                )
                is not None
                else None
            ),
            **_profile(getattr(event, "user", None)),
            "text": text,
            "amount": amount,
            "type": event_type or event_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "room_id": room_id,
            "gift_id": None,
            "gift_name": None,
            "diamond_count": None,
            "total_diamond_count": None,
            "repeat_count": None,
            "repeat_end": None,
        }
        data.update(details)
        write_line(json.dumps(data, ensure_ascii=False))

    @client.on(ConnectEvent)
    async def on_connect(event: ConnectEvent) -> None:
        nonlocal room_id
        room_id = event.room_id
        emit("connect", event)
        gift_info = client.gift_info
        if gift_info is None:
            return
        catalog = _gift_catalog_items(gift_info)
        if catalog:
            emit("gift_catalog", gifts=catalog)
        else:
            emit(
                "gift_catalog_error",
                message=(
                    "TikTokLive no devolvió una lista de regalos reconocible. "
                    "Puedes escribir el nombre manualmente."
                ),
            )

    @client.on(CommentEvent)
    async def on_comment(event: CommentEvent) -> None:
        emit("comment", event, text=event.content)

    @client.on(GiftEvent)
    async def on_gift(event: GiftEvent) -> None:
        gift = event.gift
        gift_name = gift.name if gift else None
        gift_id = gift.id if gift else event.gift_id
        diamond_count = gift.diamond_count if gift else None
        repeat_count = event.repeat_count
        emit(
            "gift",
            event,
            amount=repeat_count,
            event_type=gift_name or "gift",
            gift_id=gift_id,
            gift_name=gift_name,
            diamond_count=diamond_count,
            total_diamond_count=(
                diamond_count * repeat_count if diamond_count is not None else None
            ),
            repeat_count=repeat_count,
            repeat_end=event.repeat_end,
        )

    @client.on(FollowEvent)
    async def on_follow(event: FollowEvent) -> None:
        emit("follow", event)

    @client.on(ShareEvent)
    async def on_share(event: ShareEvent) -> None:
        emit("share", event)

    @client.on(LikeEvent)
    async def on_like(event: LikeEvent) -> None:
        emit(
            "like",
            event,
            amount=event.count,
            count=event.count,
            total=event.total,
        )

    @client.on(JoinEvent)
    async def on_join(event: JoinEvent) -> None:
        emit("join", event, member_count=event.member_count)

    @client.on(LiveEndEvent)
    async def on_live_end(event: LiveEndEvent) -> None:
        emit("live_end", event)

    @client.on(DisconnectEvent)
    async def on_disconnect(event: DisconnectEvent) -> None:
        emit("disconnect", event)

    return client


def run_client(client: TikTokLiveClient, writer: JsonLineWriter) -> None:
    """Try loading TikTok's gift catalog, then preserve LIVE connection on failure."""
    try:
        client.run(fetch_gift_info=True)
    except FailedFetchGiftListError:
        writer(
            json.dumps(
                {
                    "event": "gift_catalog_error",
                    "message": (
                        "No se pudo consultar el catálogo de regalos de TikTok. "
                        "La conexión LIVE continuará y puedes escribir el regalo "
                        "manualmente."
                    ),
                },
                ensure_ascii=False,
            )
        )
        client.run()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Escucha un LIVE de TikTok y emite eventos JSON Lines."
    )
    parser.add_argument("username", help="Nombre de usuario de TikTok (con o sin @)")
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    write_line = lambda line: print(line, flush=True)
    run_client(create_client(args.username, write_line), write_line)


if __name__ == "__main__":
    main()
