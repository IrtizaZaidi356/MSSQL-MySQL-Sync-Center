"""Load and save application settings."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = APP_ROOT / "config" / "settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    # These defaults match the folder layout discussed with the user.
    # Change them in the UI if your sync scripts are stored elsewhere.
    "scripts_directory": r"D:\IZ_DA_Working\Python\MSSQL_MYSQL_Sync",
    "working_directory": r"D:\IZ_DA_Working\Python",
    "python_executable": sys.executable,
    "interval_minutes": 15,
    "script_timeout_minutes": 60,
    "include_patterns": ["transfer_*.py", "sync_*.py", "update_*.py"],
    "exclude_files": ["main.py", "sync_manager.py"],
    "auto_start": False,
}


def load_settings() -> dict[str, Any]:
    """Load user settings, filling missing keys with defaults."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Any] = {}
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, json.JSONDecodeError):
            saved = {}

    settings = DEFAULT_SETTINGS.copy()
    settings.update(saved)

    if not isinstance(settings.get("include_patterns"), list):
        settings["include_patterns"] = DEFAULT_SETTINGS["include_patterns"].copy()
    if not isinstance(settings.get("exclude_files"), list):
        settings["exclude_files"] = DEFAULT_SETTINGS["exclude_files"].copy()

    return settings


def save_settings(settings: dict[str, Any]) -> None:
    """Persist settings as readable JSON."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = SETTINGS_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps(settings, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_file.replace(SETTINGS_FILE)
