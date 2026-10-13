"""CSV run-history persistence and application logging."""

from __future__ import annotations

import csv
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any

APP_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = APP_ROOT / "logs"
HISTORY_FILE = LOG_DIR / "run_history.csv"
LOG_FILE = LOG_DIR / "sync_manager.log"
_HISTORY_LOCK = Lock()

HISTORY_FIELDS = [
    "started_at",
    "script",
    "status",
    "new_records",
    "count_source",
    "duration_seconds",
    "return_code",
    "message",
]


def get_logger() -> logging.Logger:
    """Create a rotating logger that can safely be used from worker threads."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mssql_mysql_sync_manager")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
            )
        )
        logger.addHandler(handler)

    return logger


def append_history(result: dict[str, Any]) -> None:
    """Append one script result to the CSV history file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with _HISTORY_LOCK:
        file_exists = HISTORY_FILE.exists() and HISTORY_FILE.stat().st_size > 0
        with HISTORY_FILE.open("a", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=HISTORY_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow({key: result.get(key, "") for key in HISTORY_FIELDS})
