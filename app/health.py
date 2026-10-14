"""The state of the database file: a quick integrity check at the start of the program, after every daily backup and on demand.
A damaged file shows a red banner on every page (and on the page "About"): do not enter data, restore the last good backup."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from app import db

log = logging.getLogger("trs398.health")
_state: dict = {"ok": True, "message": "", "checked": None}
MAX_ANSWER_LINES = 5                                   # at most this many lines of the answer of SQLite are kept


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
    _state.update(ok=ok, message=message, checked=datetime.now())
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
