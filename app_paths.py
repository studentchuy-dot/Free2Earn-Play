"""User-writable paths for Free2Play data."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


APP_NAME = "Free2Play"


def user_data_dir() -> Path:
    """Return the per-user roaming data directory."""
    appdata = os.environ.get("APPDATA")
    base_dir = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base_dir / APP_NAME


def prepare_user_data_dir(
    legacy_dir: str | os.PathLike[str],
    *,
    data_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Create the data directory and migrate legacy JSON files if needed."""
    destination = Path(data_dir) if data_dir is not None else user_data_dir()
    destination.mkdir(parents=True, exist_ok=True)
    source_dir = Path(legacy_dir)
    for filename in ("rules.json", "profiles.json"):
        source = source_dir / filename
        target = destination / filename
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
    return destination
