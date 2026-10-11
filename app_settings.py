"""Cifrado y almacenamiento local de ajustes de Free2Play para Windows."""

from __future__ import annotations

import base64
import binascii
import ctypes
import json
import os
import tempfile
from collections.abc import Mapping
from ctypes import wintypes
from pathlib import Path
from typing import Any


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _dpapi_transform(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("El cifrado de ajustes VIP requiere Windows DPAPI.")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    if decrypt:
        transform = crypt32.CryptUnprotectData
        transform.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        transform.restype = wintypes.BOOL
        succeeded = transform(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
    else:
        transform = crypt32.CryptProtectData
        transform.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        transform.restype = wintypes.BOOL
        succeeded = transform(
            ctypes.byref(input_blob),
            "Free2Play settings",
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )

    if not succeeded:
        raise ctypes.WinError(ctypes.get_last_error())
    if not output_blob.pbData:
        raise OSError("Windows DPAPI devolvió un resultado vacío.")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        local_free(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


class AppSettingsStore:
    """Guarda el valor VIP cifrado y ligado al usuario actual de Windows."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        if path is None:
            local_app_data = os.environ.get("LOCALAPPDATA")
            base_dir = (
                Path(local_app_data)
                if local_app_data
                else Path.home() / "AppData" / "Local"
            )
            path = base_dir / "Free2Play" / "settings.json"
        self.path = Path(path)

    def _read_settings(self) -> dict[str, Any]:
        try:
            settings_text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise ValueError(f"No se pudo leer la configuración: {exc}") from exc
        try:
            settings: Any = json.loads(settings_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"No se pudo leer la configuración: {exc}") from exc
        if not isinstance(settings, dict):
            raise ValueError("La configuración debe ser un objeto JSON.")
        return settings

    def _write_settings(self, settings: Mapping[str, Any]) -> None:
        payload = json.dumps(settings, ensure_ascii=False, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = temporary_file.name
                temporary_file.write(payload)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def load_vip(self) -> bool:
        settings = self._read_settings()
        encrypted_vip = settings.get("VIP")
        if encrypted_vip is None:
            return False
        if not isinstance(encrypted_vip, str):
            raise ValueError("La configuración cifrada no contiene un valor VIP válido.")
        try:
            encrypted = base64.b64decode(encrypted_vip, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("El valor VIP cifrado no tiene un formato válido.") from exc
        value = _dpapi_transform(encrypted, decrypt=True)
        if value == b"true":
            return True
        if value == b"false":
            return False
        raise ValueError("El valor VIP descifrado no es un booleano válido.")

    def save_vip(self, vip: bool) -> None:
        if type(vip) is not bool:
            raise TypeError("El valor VIP debe ser bool.")
        encrypted = _dpapi_transform(
            b"true" if vip else b"false",
            decrypt=False,
        )
        settings = self._read_settings()
        settings["VIP"] = base64.b64encode(encrypted).decode("ascii")
        self._write_settings(settings)

    def load_preferences(self) -> dict[str, Any]:
        settings = self._read_settings()
        preferences = settings.get("preferences", {})
        if not isinstance(preferences, dict):
            raise ValueError("Las preferencias guardadas no tienen un formato válido.")
        return preferences

    def save_preferences(self, preferences: Mapping[str, Any]) -> None:
        settings = self._read_settings()
        settings["preferences"] = dict(preferences)
        self._write_settings(settings)
