"""The settings kept in <data>/settings.json: port, access from the network, the folder for the second copy of the backups."""
from __future__ import annotations

import json
from pathlib import Path

from app import db

DEFAULTS = {"port": 8000, "lan": False, "backup_copy_dir": ""}


def path() -> Path:
    return db.data_dir() / "settings.json"


def load() -> dict:
    try:
        return {**DEFAULTS, **json.loads(path().read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(s: dict) -> None:
    path().write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
