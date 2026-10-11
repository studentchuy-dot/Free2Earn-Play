"""Cliente HTTP pequeño para el API local de API Bridge."""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)


class MinecraftApiError(RuntimeError):
    """Error al consultar o ejecutar una acción mediante API Bridge."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        response_body: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.response_body = response_body


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> None:
        _ = (request, file_pointer, code, message, headers, new_url)
        return None


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: str
    content_type: str


@dataclass(frozen=True)
class CommandExecution:
    command: str
    response: ApiResponse | None
    error: str | None = None
    error_status: int | None = None
    error_body: str = ""


def _request(
    base_url: str,
    token: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    timeout: float = 5.0,
) -> ApiResponse:
    if not token:
        raise MinecraftApiError("No hay un token de API Bridge disponible.")

    base = base_url.strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MinecraftApiError("La dirección del API debe comenzar con http:// o https://.")
    if parsed.query or parsed.fragment:
        raise MinecraftApiError("La dirección del API no debe incluir query ni fragmento.")
    if parsed.username or parsed.password:
        raise MinecraftApiError("La dirección del API no debe contener credenciales.")
    hostname = parsed.hostname or ""
    try:
        is_loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_loopback = hostname.casefold() == "localhost"
    if not is_loopback:
        raise MinecraftApiError(
            "Por seguridad, el token solo se envía a una dirección local "
            "(localhost o loopback)."
        )

    data = None
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{base}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        opener = build_opener(_NoRedirectHandler)
        with opener.open(request, timeout=timeout) as response:
            body = response.read(65537)
            if len(body) > 65536:
                raise MinecraftApiError("La respuesta del API supera el límite de lectura.")
            return ApiResponse(
                status=response.status,
                body=body.decode("utf-8", errors="replace"),
                content_type=response.headers.get("Content-Type", ""),
            )
    except HTTPError as exc:
        error_body = exc.read(65537).decode("utf-8", errors="replace")
        if len(error_body) > 65536:
            error_body = error_body[:65536] + "…"
        if exc.code in {401, 403}:
            raise MinecraftApiError(
                "API Bridge rechazó la autenticación (HTTP "
                f"{exc.code}). Revisa el token del registro de esta instancia.",
                status=exc.code,
                response_body=error_body,
            ) from exc
        raise MinecraftApiError(
            f"API Bridge respondió HTTP {exc.code}.",
            status=exc.code,
            response_body=error_body,
        ) from exc
    except URLError as exc:
        raise MinecraftApiError(
            "No se pudo conectar con API Bridge. Comprueba que Minecraft y el "
            "mod estén iniciados y que la dirección/puerto sean correctos."
        ) from exc
    except TimeoutError as exc:
        raise MinecraftApiError("La conexión con API Bridge agotó el tiempo de espera.") from exc
    except OSError as exc:
        raise MinecraftApiError(
            "Ocurrió un error de red al conectar con API Bridge."
        ) from exc


def test_connection(
    token: str,
    base_url: str = "http://127.0.0.1:25566",
    timeout: float = 5.0,
) -> ApiResponse:
    """Consulta GET /api/, endpoint documentado para listar el API disponible."""
    response = _request(base_url, token, "/api/", timeout=timeout)
    if not 200 <= response.status < 300:
        raise MinecraftApiError(
            f"API Bridge respondió HTTP {response.status} al probar la conexión."
        )
    return response


def execute_command(
    token: str,
    command: str,
    base_url: str = "http://127.0.0.1:25566",
    timeout: float = 5.0,
) -> ApiResponse:
    """Envía un comando usando POST /api/command y el formato documentado."""
    if not command.strip():
        raise MinecraftApiError("El comando de Minecraft no puede estar vacío.")
    response = _request(
        base_url,
        token,
        "/api/command",
        method="POST",
        payload={"command": command.strip()},
        timeout=timeout,
    )
    if not 200 <= response.status < 300:
        raise MinecraftApiError(
            f"API Bridge respondió HTTP {response.status} al enviar el comando."
        )
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("success") is False:
        message = payload.get("message")
        raise MinecraftApiError(
            str(message) if message else "API Bridge rechazó el comando.",
            status=response.status,
            response_body=response.body,
        )
    return response


def execute_command_sequence(
    token: str,
    commands: list[str],
    base_url: str = "http://127.0.0.1:25566",
    timeout: float = 5.0,
) -> list[CommandExecution]:
    """Send commands in order and stop at the first rejected request."""
    outcomes: list[CommandExecution] = []
    for command in commands:
        try:
            response = execute_command(
                token,
                command,
                base_url,
                timeout,
            )
        except MinecraftApiError as exc:
            outcomes.append(
                CommandExecution(
                    command,
                    None,
                    str(exc),
                    exc.status,
                    exc.response_body,
                )
            )
            break
        outcomes.append(CommandExecution(command, response))
    return outcomes
