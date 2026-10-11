from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_paths import prepare_user_data_dir, user_data_dir


class AppPathsTests(unittest.TestCase):
    def test_user_data_dir_uses_roaming_appdata(self) -> None:
        with patch.dict(os.environ, {"APPDATA": "C:/Users/test/AppData/Roaming"}):
            self.assertEqual(
                user_data_dir(),
                Path("C:/Users/test/AppData/Roaming/Free2Play"),
            )

    def test_migrates_legacy_files_without_overwriting_existing_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy"
            destination = root / "appdata"
            legacy.mkdir()
            (legacy / "rules.json").write_text('{"rules":[]}', encoding="utf-8")
            (legacy / "profiles.json").write_text(
                '{"profiles":[]}',
                encoding="utf-8",
            )
            destination.mkdir()
            existing_profiles = destination / "profiles.json"
            existing_profiles.write_text('{"profiles":["kept"]}', encoding="utf-8")

            result = prepare_user_data_dir(legacy, data_dir=destination)

            self.assertEqual(result, destination)
            self.assertEqual(
                (destination / "rules.json").read_text(encoding="utf-8"),
                '{"rules":[]}',
            )
            self.assertEqual(
                existing_profiles.read_text(encoding="utf-8"),
                '{"profiles":["kept"]}',
            )

    def test_creates_data_directory_when_there_is_nothing_to_migrate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "new-data"

            result = prepare_user_data_dir(Path(directory) / "missing", data_dir=destination)

            self.assertEqual(result, destination)
            self.assertTrue(destination.is_dir())


if __name__ == "__main__":
    unittest.main()
