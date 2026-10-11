#!/usr/bin/env python3
"""Download a compatible API Bridge .jar from Modrinth.

Examples:
  python download_api_bridge.py --mcversion 26.1.2 --modloader fabric --dir ./mods
  python download_api_bridge.py --mcversion 26.1.2 --modloader fabric --dir "%APPDATA%\\.minecraft\\mods"
  python download_api_bridge.py --mcversion 26.1.2 --modloader fabric --dir ./mods --dry-run

This script downloads API Bridge only. It does not install other mods/dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

API_BASE = "https://api.modrinth.com/v2"
PROJECT_SLUG = "api-bridge"
USER_AGENT = "FreeToPlay-API-Bridge-Downloader/0.1 (local mod installer)"
CHUNK_SIZE = 1024 * 128


class DownloadError(RuntimeError):
    pass


def http_get_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=25) as response:
            data = response.read()
        return json.loads(data.decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise DownloadError(f"Modrinth no encontró el recurso: {url}") from exc
        raise DownloadError(f"Modrinth respondió HTTP {exc.code} al consultar la API.") from exc
    except URLError as exc:
        raise DownloadError(
            f"No se pudo conectar con Modrinth: {exc.reason}. Comprueba tu conexión."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DownloadError("La API de Modrinth devolvió una respuesta no válida.") from exc


def normalize_loader(value: str) -> str:
    aliases = {
        "neo-forge": "neoforge",
        "neo_forge": "neoforge",
        "quiltmc": "quilt",
    }
    normalized = value.strip().lower()
    return aliases.get(normalized, normalized)


def matches_game_version(requested: str, supported: list[str]) -> bool:
    """Support exact versions and simple Modrinth family labels such as 26.1.x."""
    requested = requested.strip().lower()
    for item in supported:
        item = str(item).strip().lower()
        if item == requested:
            return True
        # Example: metadata says 26.1.x and the user requests 26.1.2.
        if item.endswith(".x"):
            prefix = item[:-1]  # retains the trailing dot, e.g. "26.1."
            if requested.startswith(prefix) and requested[len(prefix):].isdigit():
                return True
        # Some projects use a wildcard form such as 26.*.
        if "*" in item:
            regex = "^" + re.escape(item).replace(r"\*", r"[^.]+") + "$"
            if re.match(regex, requested):
                return True
    return False


def get_project_versions() -> list[dict[str, Any]]:
    # Fetch all versions so that, on a mismatch, the script can show alternatives
    # for other Minecraft versions and loaders too.
    url = f"{API_BASE}/project/{quote(PROJECT_SLUG)}/version?include_changelog=false"
    payload = http_get_json(url)
    if not isinstance(payload, list):
        raise DownloadError("La respuesta de versiones de Modrinth no tiene el formato esperado.")
    return payload


def published_versions_for_loader(versions: list[dict[str, Any]], loader: str) -> list[dict[str, Any]]:
    found = [v for v in versions if loader in [normalize_loader(x) for x in v.get("loaders", [])]]
    # Most recent first, according to the published ISO timestamp.
    found.sort(key=lambda v: str(v.get("date_published", "")), reverse=True)
    return found


def show_supported_versions(versions: list[dict[str, Any]], loader: str) -> None:
    matches = published_versions_for_loader(versions, loader)
    if not matches:
        loaders = sorted({normalize_loader(x) for v in versions for x in v.get("loaders", [])})
        print(f"No hay versiones publicadas de API Bridge para el loader '{loader}'.")
        print("Loaders que aparecen en los metadatos: " + (", ".join(loaders) if loaders else "ninguno"))
        return

    supported: set[str] = set()
    for version in matches:
        supported.update(str(x) for x in version.get("game_versions", []))

    def version_sort_key(value: str) -> tuple[int, object]:
        parts = value.split(".")
        if all(part.isdigit() for part in parts):
            return (1, tuple(int(part) for part in parts))
        return (0, value)

    print(f"Versiones de Minecraft declaradas para API Bridge con '{loader}':")
    for item in sorted(supported, key=version_sort_key, reverse=True):
        print(f"  - {item}")
    print("\nVersiones del mod publicadas recientemente:")
    for version in matches[:10]:
        game_versions = ", ".join(str(x) for x in version.get("game_versions", [])) or "sin versión declarada"
        number = version.get("version_number", "versión desconocida")
        channel = version.get("version_type", "desconocido")
        print(f"  - {number} [{channel}] — Minecraft: {game_versions}")


def pick_release(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    # Prefer stable releases; if none exist for the requested target, use a beta/alpha
    # only when it is the sole compatible option and tell the user about it.
    candidates.sort(key=lambda v: str(v.get("date_published", "")), reverse=True)
    releases = [v for v in candidates if v.get("version_type", "release") == "release"]
    return (releases or candidates)[0]


def expand_destination(raw_path: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(raw_path))
    # On Windows, expandvars also supports %APPDATA%. On other OSes, use it as provided.
    return Path(expanded).resolve()


def safe_filename(raw_name: str) -> str:
    # Never let a remote filename write outside the destination directory.
    name = Path(raw_name.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise DownloadError("Modrinth devolvió un nombre de archivo no válido.")
    if not name.lower().endswith(".jar"):
        raise DownloadError(f"El archivo principal no parece un mod .jar: {name}")
    return name


def download_and_verify(
    file_meta: dict[str, Any],
    destination: Path,
    force: bool,
    output: Callable[[str], None] | None = print,
) -> Path:
    url = file_meta.get("url")
    raw_name = file_meta.get("filename")
    hashes = file_meta.get("hashes") or {}
    if not isinstance(url, str) or not url.startswith("https://"):
        raise DownloadError("La URL de descarga no es válida o no usa HTTPS.")
    if not isinstance(raw_name, str):
        raise DownloadError("Modrinth no indicó el nombre del archivo.")

    filename = safe_filename(raw_name)
    target = destination / filename
    expected_sha512 = hashes.get("sha512")
    expected_sha1 = hashes.get("sha1")

    if target.exists() and not force:
        # If there's an expected hash, avoid downloading an identical file again.
        if expected_sha512 or expected_sha1:
            current = hashlib.sha512() if expected_sha512 else hashlib.sha1()
            with target.open("rb") as existing:
                for chunk in iter(lambda: existing.read(CHUNK_SIZE), b""):
                    current.update(chunk)
            expected = expected_sha512 or expected_sha1
            if current.hexdigest().lower() == expected.lower():
                if output is not None:
                    output(f"Ya existe y coincide con el hash publicado: {target}")
                return target
        raise DownloadError(
            f"El archivo ya existe y no se sobrescribirá: {target}\n"
            "Elige otra carpeta, elimina el archivo existente o usa --force para reemplazarlo."
        )

    temp = destination / (filename + ".part")
    sha512 = hashlib.sha512()
    sha1 = hashlib.sha1()
    request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with urlopen(request, timeout=60) as response, temp.open("wb") as output:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                sha512.update(chunk)
                sha1.update(chunk)
        if temp.stat().st_size < 4:
            raise DownloadError("La descarga está vacía o incompleta.")
        with temp.open("rb") as downloaded:
            if downloaded.read(4)[:2] != b"PK":
                raise DownloadError("El archivo descargado no parece un JAR/ZIP válido.")
        if expected_sha512 and sha512.hexdigest().lower() != expected_sha512.lower():
            raise DownloadError("Falló la comprobación SHA-512; el archivo se descartó.")
        if not expected_sha512 and expected_sha1 and sha1.hexdigest().lower() != expected_sha1.lower():
            raise DownloadError("Falló la comprobación SHA-1; el archivo se descartó.")
        if not expected_sha512 and not expected_sha1:
            if output is not None:
                output("Aviso: Modrinth no publicó un hash para verificar este archivo.")
        os.replace(temp, target)
        return target
    except (HTTPError, URLError) as exc:
        raise DownloadError(f"Falló la descarga: {exc}") from exc
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass


def install_api_bridge(
    mcversion: str,
    modloader: str,
    destination: str | os.PathLike[str],
    force: bool = False,
) -> Path:
    """Descarga y verifica el JAR compatible dentro de la carpeta indicada."""
    requested_mc = mcversion.strip()
    loader = normalize_loader(modloader)
    if not requested_mc:
        raise DownloadError("La versión de Minecraft no puede estar vacía.")
    if not loader:
        raise DownloadError("El mod loader no puede estar vacío.")

    versions = get_project_versions()
    compatible = [
        version
        for version in published_versions_for_loader(versions, loader)
        if matches_game_version(
            requested_mc,
            [str(item) for item in version.get("game_versions", [])],
        )
        and version.get("status", "listed") == "listed"
    ]
    if not compatible:
        raise DownloadError(
            f"No hay una versión publicada de API Bridge compatible con "
            f"Minecraft {requested_mc} y loader '{loader}'."
        )

    selected = pick_release(compatible)
    files = selected.get("files") or []
    if not files:
        raise DownloadError(
            "La versión compatible no tiene archivos descargables publicados."
        )
    primary_files = [item for item in files if item.get("primary")]
    file_meta = (primary_files or files)[0]

    target_directory = expand_destination(os.fspath(destination))
    target_directory.mkdir(parents=True, exist_ok=True)
    return download_and_verify(
        file_meta,
        target_directory,
        force=force,
        output=None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Descarga únicamente API Bridge desde Modrinth para la versión y loader indicados."
    )
    parser.add_argument("--mcversion", required=True, help="Versión de Minecraft, por ejemplo 26.1.2")
    parser.add_argument("--modloader", required=True, help="Mod loader, por ejemplo fabric, forge o neoforge")
    parser.add_argument("--dir", default="./mods", help="Carpeta destino (por defecto: ./mods)")
    parser.add_argument("--dry-run", action="store_true", help="Solo comprueba compatibilidad; no descarga nada")
    parser.add_argument("--force", action="store_true", help="Permite reemplazar un archivo de igual nombre")
    args = parser.parse_args()

    requested_mc = args.mcversion.strip()
    loader = normalize_loader(args.modloader)
    if not requested_mc:
        parser.error("--mcversion no puede estar vacío")
    if not loader:
        parser.error("--modloader no puede estar vacío")

    try:
        versions = get_project_versions()
        loader_versions = published_versions_for_loader(versions, loader)
        compatible = [
            v for v in loader_versions
            if matches_game_version(requested_mc, [str(x) for x in v.get("game_versions", [])])
            and v.get("status", "listed") == "listed"
        ]

        if not compatible:
            print(f"No se encontró una versión publicada de API Bridge compatible con Minecraft {requested_mc} y loader '{loader}'.\n")
            show_supported_versions(versions, loader)
            return 2

        selected = pick_release(compatible)
        files = selected.get("files") or []
        if not files:
            raise DownloadError("La versión compatible no tiene archivos descargables publicados.")
        primary_files = [item for item in files if item.get("primary")]
        file_meta = (primary_files or files)[0]

        version_number = selected.get("version_number", "desconocida")
        channel = selected.get("version_type", "desconocido")
        print(f"Proyecto: API Bridge (Modrinth: {PROJECT_SLUG})")
        print(f"Minecraft solicitado: {requested_mc}")
        print(f"Loader solicitado: {loader}")
        print(f"Versión del mod elegida: {version_number} ({channel})")
        print("Minecraft declarado en esa versión: " + ", ".join(selected.get("game_versions", [])))
        print(f"Archivo: {file_meta.get('filename', '(sin nombre)')}")

        dependencies = [d for d in selected.get("dependencies", []) if d.get("dependency_type") == "required"]
        if dependencies:
            print("\nDependencias obligatorias declaradas (NO se descargarán; este script descarga solo API Bridge):")
            for dep in dependencies:
                print(f"  - proyecto={dep.get('project_id', 'desconocido')}; versión={dep.get('version_id') or 'la compatible'}")

        destination = expand_destination(args.dir)
        print(f"Carpeta destino: {destination}")
        if args.dry_run:
            print("Modo --dry-run: compatible; no se descargó ni modificó ningún archivo.")
            return 0

        destination.mkdir(parents=True, exist_ok=True)
        saved = download_and_verify(file_meta, destination, args.force)
        print(f"\nDescarga completada y verificada: {saved}")
        if dependencies:
            print("Recuerda instalar por separado las dependencias obligatorias que correspondan a esa versión.")
        return 0

    except DownloadError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperación cancelada.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
