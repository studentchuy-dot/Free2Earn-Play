"""Extrae de forma local el token de autenticación de API Bridge."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import TypeAlias

PathInput: TypeAlias = str | os.PathLike[str]

_TOKEN_PATTERN = re.compile(
    r"mcapi\.key not provided![ \t]*"
    r"Generated random auth token:[ \t]*"
    r"(?<![0-9a-fA-F])([0-9a-fA-F]{64})(?![0-9a-fA-F])"
)
_READ_ATTEMPTS = 2
_POLL_INTERVAL_SECONDS = 1.0


def _file_signature(file_stat: os.stat_result) -> tuple[int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


def _path_signature(path: Path) -> tuple[int, int, int, int] | None:
    try:
        return _file_signature(path.stat())
    except OSError:
        return None


def _inspect_log(log_path: PathInput) -> tuple[str | None, str]:
    """Retorna token y estado interno, sin imprimir ni registrar el token."""
    try:
        path = Path(log_path)
    except (TypeError, ValueError):
        return None, "invalid_path"

    for _ in range(_READ_ATTEMPTS):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as log_file:
                before = os.fstat(log_file.fileno())
                content = log_file.read()
                after = os.fstat(log_file.fileno())
            current_path = path.stat()
        except FileNotFoundError:
            return None, "file_not_found"
        except PermissionError:
            return None, "permission_denied"
        except OSError:
            return None, "read_error"

        if not (
            _file_signature(before)
            == _file_signature(after)
            == _file_signature(current_path)
        ):
            continue

        if not content:
            return None, "empty_file"

        matches = list(_TOKEN_PATTERN.finditer(content))
        if matches:
            return matches[-1].group(1), "found"
        return None, "token_not_found"

    return None, "log_changed"


def find_api_bridge_token(log_path: PathInput) -> str | None:
    """Devuelve el token hex de 64 caracteres, o ``None`` si no está disponible.

    Los errores habituales de ruta, permisos, lectura y cambios concurrentes
    se convierten en ``None`` para que la aplicación que importe esta función
    pueda decidir cómo actuar sin recibir excepciones inesperadas.
    """
    return _inspect_log(log_path)[0]


def _default_log_path() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / ".minecraft" / "logs" / "latest.log"


def _select_log_path(args: argparse.Namespace) -> Path | None:
    if args.log:
        return Path(args.log)
    if args.instance_dir:
        return Path(args.instance_dir) / "logs" / "latest.log"
    if args.minecraft_dir:
        return Path(args.minecraft_dir) / "logs" / "latest.log"
    return _default_log_path()


def _status_message(status: str, path: Path | None) -> str:
    location = f" ({path})" if path is not None else ""
    messages = {
        "found": f"Token API Bridge encontrado{location}.",
        "file_not_found": (
            f"No existe el archivo de registro{location}. "
            "Selecciona la instancia correcta con --instance-dir o indica "
            "el archivo exacto con --log."
        ),
        "permission_denied": (
            f"Acceso denegado al registro{location}. Comprueba sus permisos."
        ),
        "empty_file": f"El archivo de registro está vacío{location}.",
        "token_not_found": (
            f"El registro no contiene el token de API Bridge{location}. "
            "Confirma que API Bridge haya iniciado."
        ),
        "log_changed": (
            f"El registro cambió durante la lectura{location}; "
            "vuelve a intentarlo o usa --wait."
        ),
        "read_error": f"No se pudo leer el registro{location}.",
        "invalid_path": "La ruta al registro no es válida.",
        "default_path_unavailable": (
            "No se encontró APPDATA. Indica la instancia correcta con "
            "--instance-dir o --log."
        ),
        "wait_cancelled": "Espera cancelada por el usuario.",
    }
    return messages.get(status, f"No se pudo obtener el token ({status}).")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Busca localmente en latest.log el token de autenticación "
            "generado por API Bridge."
        )
    )
    parser.add_argument("--log", help="Ruta exacta al archivo latest.log.")
    parser.add_argument(
        "--instance-dir",
        help="Directorio de una instancia; se usa logs/latest.log.",
    )
    parser.add_argument(
        "--minecraft-dir",
        help="Directorio base de Minecraft; se usa logs/latest.log.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Reintenta cada segundo hasta hallar el token; Ctrl+C cancela.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime un resultado JSON; el token se omite salvo con --show-token.",
    )
    parser.add_argument(
        "--show-token",
        action="store_true",
        help="Permite mostrar explícitamente el token en la salida.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    log_path = _select_log_path(args)
    status = "default_path_unavailable" if log_path is None else "token_not_found"
    token: str | None = None

    try:
        if log_path is not None:
            token, status = _inspect_log(log_path)
            if args.wait and token is None:
                print(
                    f"Esperando el token en {log_path}; Ctrl+C cancela.",
                    file=sys.stderr,
                    flush=True,
                )
                last_signature = _path_signature(log_path)
                while token is None:
                    time.sleep(_POLL_INTERVAL_SECONDS)
                    current_signature = _path_signature(log_path)
                    if (
                        current_signature == last_signature
                        and status
                        not in {"permission_denied", "read_error", "log_changed"}
                    ):
                        continue
                    token, status = _inspect_log(log_path)
                    last_signature = current_signature
    except KeyboardInterrupt:
        status = "wait_cancelled"
        token = None

    success = token is not None
    result: dict[str, str | bool | None] = {
        "status": status,
        "found": success,
        "log_path": str(log_path) if log_path is not None else None,
        "token": token if success and args.show_token else None,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(_status_message(status, log_path))
        if success:
            if args.show_token:
                print(token)
            else:
                print("El token no se muestra; usa --show-token si lo necesitas.")
    return 0 if success else (130 if status == "wait_cancelled" else 1)


if __name__ == "__main__":
    sys.exit(main())
