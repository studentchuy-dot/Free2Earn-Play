from __future__ import annotations

import unittest
from unittest.mock import patch

import ui_feedback


class UiFeedbackTests(unittest.TestCase):
    def test_status_colors_include_all_supported_states(self) -> None:
        for state in (
            "connected",
            "active",
            "error",
            "connecting",
            "disconnected",
            "paused",
        ):
            with self.subTest(state=state):
                self.assertTrue(ui_feedback.status_color(state).startswith("#"))

    def test_unknown_status_state_is_reported(self) -> None:
        with self.assertRaisesRegex(ValueError, "desconocido"):
            ui_feedback.status_color("unknown")

    def test_http_get_categories_include_explicit_failed_get(self) -> None:
        self.assertEqual(
            ui_feedback.classify_log_entry(
                "HTTP GET", "Prueba de conexión fallida", "Connection refused"
            ),
            ("GET", "error"),
        )

    def test_http_post_categories_include_rejected_commands(self) -> None:
        self.assertEqual(
            ui_feedback.classify_log_entry(
                "gift", "API Bridge rechazó el comando", "HTTP 401"
            ),
            ("POST", "error"),
        )

    def test_tiktok_events_are_live_and_successful_events_are_green(self) -> None:
        self.assertEqual(
            ui_feedback.classify_log_entry("comment", "Recibido", "hola"),
            ("LIVE", "normal"),
        )
        self.assertEqual(
            ui_feedback.classify_log_entry(
                "TikTok", "Conectado al LIVE", ""
            ),
            ("LIVE", "success"),
        )

    def test_sound_uses_async_builtin_windows_alias(self) -> None:
        with patch("winsound.PlaySound") as play_sound, patch(
            "winsound.SND_ALIAS", 1, create=True
        ), patch("winsound.SND_ASYNC", 2, create=True), patch(
            "winsound.SND_NODEFAULT", 4, create=True
        ):
            ui_feedback.play_status_sound("connected")

        play_sound.assert_called_once_with(
            "SystemAsterisk", 1 | 2 | 4
        )

    def test_notification_is_silent_and_contains_only_supplied_text(self) -> None:
        with patch("ui_feedback.Notification") as notification_type, patch(
            "ui_feedback.audio"
        ) as notification_audio:
            ui_feedback.send_desktop_notification(
                "Connected", "Ready for events"
            )

        notification_type.assert_called_once_with(
            app_id="Free2Play",
            title="Connected",
            msg="Ready for events",
            duration="short",
        )
        notification_type.return_value.set_audio.assert_called_once_with(
            notification_audio.Silent, loop=False
        )
        notification_type.return_value.show.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
