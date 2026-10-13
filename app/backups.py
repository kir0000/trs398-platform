"""Backups of the database: a consistent copy of the SQLite file (the backup API, safe while the program works), compressed,
made every day inside the program and kept for BACKUP_KEEP_DAYS days. The restore tool (tools/restore.py) brings a copy back."""
from __future__ import annotations

import gzip
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from app import db

STALE_AFTER = timedelta(hours=36)
PATTERN = "trs398_*.db.gz"
_lock = threading.Lock()
log = logging.getLogger("trs398.backups")


def backup_dir() -> Path:
    p = Path(os.environ["BACKUP_DIR"]) if os.environ.get("BACKUP_DIR") else db.data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def keep_days() -> int:
    try:
        return max(1, int(os.environ.get("BACKUP_KEEP_DAYS", "30")))
    except ValueError:
        return 30


def make(now: datetime | None = None, folder: Path | None = None) -> Path:
    """A compressed copy of the database right now; copies older than the keeping period are removed. Returns its path."""
    now = now or datetime.now()
    folder = folder or backup_dir()
    target = folder / f"trs398_{now:%Y-%m-%d_%H%M%S}.db.gz"
    with _lock:
        fd, tmp = tempfile.mkstemp(suffix=".db", dir=str(folder))
        os.close(fd)
        try:
            src = sqlite3.connect(str(db.db_path()))
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)                      # a consistent snapshot, writers are not blocked for long
            finally:
                dst.close()
                src.close()
            with open(tmp, "rb") as f_in, gzip.open(target, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)
        finally:
            Path(tmp).unlink(missing_ok=True)
        cutoff = time.time() - keep_days() * 86400
        for old in folder.glob(PATTERN):
            if old != target and old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
    return target


def recent(limit: int = 15) -> list[dict]:
    """The newest copies (name, when, size_kb) and the safety copies kept by restore (folder keep/)."""
    folder = backup_dir()
    out = []
    for pattern, kind in ((PATTERN, "авто"), (f"keep/{PATTERN}", "сохранённая")):
        for p in folder.glob(pattern):
            out.append({"name": p.relative_to(folder).as_posix(), "when": datetime.fromtimestamp(p.stat().st_mtime),
                        "size_kb": max(1, p.stat().st_size // 1024), "kind": kind})
    return sorted(out, key=lambda r: r["when"], reverse=True)[:limit]


def request_now() -> bool:
    """Make a copy right now (the button of the administrator). False if the folder is not writable."""
    try:
        path = make()
        log.info("backup made: %s", path.name)
        return True
    except OSError:
        log.exception("the backup failed")
        return False


def latest(now: datetime | None = None) -> dict:
    """{'found': bool, 'name', 'when', 'size_kb', 'count', 'stale', 'message'} for the newest copy."""
    now = now or datetime.now()
    files = sorted(backup_dir().glob(PATTERN), key=lambda p: p.stat().st_mtime)
    if not files:
        return {"found": False, "stale": True, "count": 0,
                "message": "Резервных копий нет. Перед удалением данных сделайте копию вручную (кнопка «Сделать копию сейчас»)."}
    newest = files[-1]
    when = datetime.fromtimestamp(newest.stat().st_mtime)
    stale = now - when > STALE_AFTER
    return {"found": True, "name": newest.name, "when": when, "size_kb": max(1, newest.stat().st_size // 1024),
            "count": len(files), "stale": stale,
            "message": ("Последняя резервная копия старше 36 часов: программа должна быть запущена в течение дня." if stale
                        else "Резервная копия свежая.")}


def due(now: datetime | None = None) -> bool:
    """A daily copy is due when the hour of the day (BACKUP_HOUR, local time) has come and today's copy does not exist yet."""
    now = now or datetime.now()
    try:
        hour = int(os.environ.get("BACKUP_HOUR", "2"))
    except ValueError:
        hour = 2
    if now.hour < hour:
        return False
    today = f"trs398_{now:%Y-%m-%d}_"
    return not any(p.name.startswith(today) for p in backup_dir().glob(PATTERN))


def start_scheduler(interval_s: int = 600) -> threading.Thread:
    """A background thread that makes the daily copy (also at the start of the program if the day's copy is missing)."""
    def loop():
        while True:
            try:
                if due():
                    make()
            except Exception:                      # a failed copy must never stop the program; the page of backups shows that it is stale
                log.exception("the daily backup failed")
            time.sleep(interval_s)
    t = threading.Thread(target=loop, name="trs398-backup", daemon=True)
    t.start()
    return t
