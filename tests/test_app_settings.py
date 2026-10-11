from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_settings import AppSettingsStore


class AppSettingsStoreTests(unittest.TestCase):
    def test_missing_file_defaults_to_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AppSettingsStore(Path(directory) / "settings.json")

            self.assertFalse(store.load_vip())

    def test_saves_vip_ciphertext_and_loads_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = AppSettingsStore(path)
            protected_values: list[bytes] = []

            def protect(value: bytes, *, decrypt: bool) -> bytes:
                if decrypt:
                    self.assertEqual(value, b"protected:true")
                    return b"true"
                protected_values.append(value)
                return b"protected:" + value

            with patch("app_settings._dpapi_transform", side_effect=protect):
                store.save_vip(True)
                stored = json.loads(path.read_text(encoding="utf-8"))

                self.assertEqual(protected_values, [b"true"])
                self.assertNotIn("true", path.read_text(encoding="utf-8"))
                self.assertEqual(
                    base64.b64decode(stored["VIP"]),
                    b"protected:true",
                )
                self.assertTrue(store.load_vip())

    def test_rejects_non_boolean_vip_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AppSettingsStore(Path(directory) / "settings.json")

            with self.assertRaises(TypeError):
                store.save_vip(1)  # type: ignore[arg-type]

    def test_rejects_invalid_encrypted_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"VIP":"not-base64"}', encoding="utf-8")

            with self.assertRaises(ValueError):
                AppSettingsStore(path).load_vip()

    def test_preferences_round_trip_without_replacing_vip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = AppSettingsStore(path)
            with patch(
                "app_settings._dpapi_transform",
                side_effect=lambda value, *, decrypt: (
                    b"true" if decrypt else b"protected-vip"
                ),
            ):
                store.save_vip(True)
                store.save_preferences(
                    {
                        "tiktok_username": "creator",
                        "instance_dir": "C:/Minecraft/instance",
                        "auto_connect_tiktok": True,
                    }
                )

                self.assertTrue(store.load_vip())
                self.assertEqual(
                    store.load_preferences(),
                    {
                        "tiktok_username": "creator",
                        "instance_dir": "C:/Minecraft/instance",
                        "auto_connect_tiktok": True,
                    },
                )


if __name__ == "__main__":
    unittest.main()
