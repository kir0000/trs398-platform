"""The state of the database file: a quick integrity check at the start of the program, after every daily backup and on demand.
A damaged file shows a red banner on every page (and on the page "About"): do not enter data, restore the last good backup."""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from app import db

log = logging.getLogger("trs398.health")
_state: dict = {"ok": True, "message": "", "checked": None, "sync": ""}
MAX_ANSWER_LINES = 5                                   # at most this many lines of the answer of SQLite are kept


# a folder that a cloud client synchronises: the files of a database are copied half-written and the copies of two computers get mixed up
SYNC_NAMES = {"yandex.disk": "Яндекс.Диск", "yandexdisk": "Яндекс.Диск", "яндекс.диск": "Яндекс.Диск", "яндекс диск": "Яндекс.Диск",
              "onedrive": "OneDrive", "dropbox": "Dropbox", "google drive": "Google Drive", "googledrive": "Google Drive",
              "icloud": "iCloud", "nextcloud": "Nextcloud", "owncloud": "ownCloud", "pcloud": "pCloud"}
SYNC_MARKERS = {".dropbox": "Dropbox", ".dropbox.cache": "Dropbox", ".owncloudsync.log": "ownCloud", ".nextcloudsync.log": "Nextcloud"}


def sync_service(path=None) -> str:
    """The name of the cloud service that synchronises the data folder ("" if none is recognised): by the OneDrive variables of Windows,
    by the names of the folders on the way and by the marker files that some clients leave in the root of their folder."""
    p = Path(path or db.data_dir()).resolve()
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = os.environ.get(env)
        if root:
            try:
                p.relative_to(Path(root).resolve())
                return "OneDrive"
            except ValueError:
                pass
    for folder in (p, *p.parents):
        name = folder.name.lower()
        for token, service in SYNC_NAMES.items():
            if token in name:
                return service
        for marker, service in SYNC_MARKERS.items():
            try:
                if (folder / marker).exists():
                    return service
            except OSError:
                pass
    return ""


def check(path=None) -> dict:
    """PRAGMA quick_check of the database (a few milliseconds for the usual size); the answer is kept for the pages."""
    path = path or db.db_path()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            rows = [r[0] for r in conn.execute("PRAGMA quick_check").fetchall()][:MAX_ANSWER_LINES]
        finally:
            conn.close()
        ok = rows == ["ok"]
        message = "" if ok else "; ".join(str(r) for r in rows)
    except sqlite3.Error as e:
        ok, message = False, str(e)
    service = sync_service(Path(path).parent)
    if service:
        log.warning("the data folder is synchronised by %s: this can damage the database file", service)
    _state.update(ok=ok, message=message, checked=datetime.now(), sync=service)
    if ok:
        log.info("the database passed the integrity check")
    else:
        log.error("the integrity check of the database failed: %s", message)
        db.system_event("db_check_failed", "system", None, {"error": message[:200]})
    return dict(_state)


def status() -> dict:
    return dict(_state)


def problem() -> str:
    """The text of the problem for the banner, "" while everything is fine."""
    return "" if _state["ok"] else (_state["message"] or "the database file is damaged")
