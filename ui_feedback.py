"""Visual status, log categories, sounds, and desktop notifications."""

from __future__ import annotations

from winotify import Notification, audio

STATUS_COLORS: dict[str, str] = {
    "connected": "#22c55e",
    "active": "#22c55e",
    "error": "#ef4444",
    "connecting": "#3b82f6",
    "disconnected": "#94a3b8",
    "paused": "#94a3b8",
}


def status_color(state: str) -> str:
    try:
        return STATUS_COLORS[state]
    except KeyError as exc:
        raise ValueError(f"Estado visual desconocido: {state}") from exc


def classify_log_entry(
    event_type: str,
    result: str,
    detail: str,
) -> tuple[str, str]:
    """Return a short channel badge and severity for the activity log."""
    searchable = f"{result} {detail}".casefold()
    if event_type.casefold() in {"get", "http get"} or "get /" in searchable:
        category = "GET"
    elif (
        event_type.casefold() in {"post", "http post"}
        or "post /" in searchable
        or "solicitud de comandos" in searchable
        or "api bridge encoló" in searchable
        or "api bridge aceptó" in searchable
        or "api bridge rechazó" in searchable
        or "falló la secuencia" in searchable
        or "comando:" in searchable
    ):
        category = "POST"
    elif event_type.casefold() in {
        "tiktok",
        "connect",
        "disconnect",
        "live_end",
        "comment",
        "gift",
        "follow",
        "share",
        "like",
        "join",
    }:
        category = "LIVE"
    else:
        category = "APP"

    if any(
        marker in searchable
        for marker in (
            "error",
            "falló",
            "fallida",
            "rechazó",
            "no se pudo",
            "no válido",
            "no válida",
            "http 4",
            "http 5",
            "falló",
            "fallo",
        )
    ):
        severity = "error"
    elif any(
        marker in searchable
        for marker in (
            "advertencia",
            "warning",
            "esperando",
            "pendiente",
            "comprobando",
            "no hay unidades",
        )
    ):
        severity = "warning"
    elif any(
        marker in searchable
        for marker in (
            "conectado",
            "correcta",
            "aceptó",
            "encoló",
            "completada",
            "iniciada",
            "activada",
        )
    ):
        severity = "success"
    else:
        severity = "normal"
    return category, severity


def play_status_sound(state: str) -> None:
    """Play a built-in Windows sound alias asynchronously."""
    import winsound

    try:
        sound_alias = {
            "connected": "SystemAsterisk",
            "disconnected": "SystemExclamation",
            "error": "SystemHand",
        }[state]
    except KeyError as exc:
        raise ValueError(f"Estado de sonido desconocido: {state}") from exc
    winsound.PlaySound(
        sound_alias,
        winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
    )


def send_desktop_notification(title: str, message: str) -> None:
    """Send a short Windows toast without duplicating the separate sound."""
    toast = Notification(
        app_id="Free2Play",
        title=title,
        msg=message,
        duration="short",
    )
    toast.set_audio(audio.Silent, loop=False)
    toast.show()
