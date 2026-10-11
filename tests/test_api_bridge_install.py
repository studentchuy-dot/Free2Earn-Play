from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connections import APIBridge


def project_version(
    version: str,
    *,
    game_versions: list[str],
    loaders: list[str],
    version_type: str = "release",
) -> dict[str, object]:
    return {
        "version_number": version,
        "game_versions": game_versions,
        "loaders": loaders,
        "version_type": version_type,
        "status": "listed",
        "date_published": "2026-01-01T00:00:00Z",
        "files": [
            {
                "filename": "api-bridge.jar",
                "url": "https://example.test/api-bridge.jar",
                "hashes": {},
                "primary": True,
            }
        ],
    }


class ApiBridgeInstallTests(unittest.TestCase):
    def test_installer_selects_matching_release_and_downloads_into_destination(self) -> None:
        compatible = project_version(
            "1.0.0",
            game_versions=["1.21.1"],
            loaders=["fabric"],
        )
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory).resolve() / "mods" / "api-bridge.jar"
            with (
                patch.object(APIBridge, "get_project_versions", return_value=[compatible]),
                patch.object(
                    APIBridge,
                    "download_and_verify",
                    return_value=expected,
                ) as download,
            ):
                result = APIBridge.install_api_bridge(
                    "1.21.1",
                    "fabric",
                    Path(directory) / "mods",
                )

        self.assertEqual(result, expected)
        self.assertEqual(download.call_args.args[0], compatible["files"][0])
        self.assertIsNone(download.call_args.kwargs["output"])

    def test_installer_reports_incompatible_game_and_loader(self) -> None:
        version = project_version(
            "1.0.0",
            game_versions=["1.21.1"],
            loaders=["fabric"],
        )
        with patch.object(APIBridge, "get_project_versions", return_value=[version]):
            with self.assertRaisesRegex(APIBridge.DownloadError, "compatible"):
                APIBridge.install_api_bridge(
                    "1.20.1",
                    "forge",
                    "mods",
                )


if __name__ == "__main__":
    unittest.main()
