"""Comandos para ejecutar los conectores existentes como procesos CLI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
API_BRIDGE_CLI = Path(__file__).resolve().with_name("APIBridge.py")
WORKER_NAME = "Free2PlayWorker.exe"


def _worker_command(*arguments: str) -> list[str]:
    """Use the bundled console worker when running as a frozen application."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name(WORKER_NAME)), *arguments]
    return [sys.executable, "-u", *arguments]


def tiktok_command(username: str) -> list[str]:
    """Construye el comando del CLI TikTok, cuyo argumento es el usuario."""
    clean_username = username.strip()
    if not clean_username:
        raise ValueError("Debes indicar un usuario de TikTok.")
    if getattr(sys, "frozen", False):
        return _worker_command("--f2p-worker-tiktok", clean_username)
    return _worker_command("-m", "connections.tiktok", clean_username)


def api_bridge_install_command(
    minecraft_version: str,
    modloader: str,
    destination: str | os.PathLike[str],
    *,
    force: bool = False,
) -> list[str]:
    """Construye los argumentos documentados del CLI del instalador."""
    version = minecraft_version.strip()
    loader = modloader.strip()
    if not version:
        raise ValueError("Debes indicar la versión de Minecraft.")
    if not loader:
        raise ValueError("Debes indicar el mod loader.")

    if getattr(sys, "frozen", False):
        command = _worker_command(
            "--f2p-worker-api-bridge",
            "--mcversion",
            version,
            "--modloader",
            loader,
            "--dir",
            os.fspath(destination),
        )
    else:
        command = _worker_command(
            str(API_BRIDGE_CLI),
            "--mcversion",
            version,
            "--modloader",
            loader,
            "--dir",
            os.fspath(destination),
        )
    if force:
        command.append("--force")
    return command
